"""Room-wise hourly cooling loads (steady-state heat-balance per hour).

For each room and hour (outdoor conditions from the design day), with the
room held at T_in:

  walls     Q = U_wall · A_opaque · (T_solair - T_in),  T_solair = T_out + α·I / h_out
  windows   Q = U_win · A_win · (T_out - T_in)  +  A_win · SHGC · IAC · I
  roof      Q = U_roof · A_roof · (T_solair_roof - T_in)        (top floor only)
  people    Q = n · (sensible, latent)
  lights / equipment  Q = W/m² · A · schedule
  infiltration  Q_s = ṁ·cp·ΔT,  Q_l = ṁ·h_fg·Δω
  ventilation (outdoor air, a COIL load not a room load) - same equations

Limitation: steady-state per hour - no thermal-mass time lag (see rc_model).
All results are in W.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import climate
from .defaults import room_profile
from .geometry import Building, Room

COMPONENTS = ["wall", "window_cond", "window_solar", "roof", "people_s", "lights",
              "equipment", "infil_s", "people_l", "infil_l", "vent_s", "vent_l"]
ROOM_SENSIBLE = ["wall", "window_cond", "window_solar", "roof", "people_s", "lights",
                 "equipment", "infil_s"]
LATENT = ["people_l", "infil_l", "vent_l"]
CONVECTIVE_ENV = ["wall", "window_cond", "roof", "infil_s"]  # depend on T_in linearly


@dataclass
class RoomLoad:
    name: str
    kind: str
    area: float
    people: float
    on_chiller: bool
    H_env: float                                  # W/K, envelope + infiltration conductance
    hourly: dict[str, np.ndarray] = field(default_factory=dict)

    @property
    def room_sensible(self):
        return sum(self.hourly[k] for k in ROOM_SENSIBLE)

    @property
    def coil_total(self):
        return self.room_sensible + sum(self.hourly[k] for k in LATENT) + self.hourly["vent_s"]


def occupied(h, reg):
    return reg["occ_start_h"] <= h < reg["occ_end_h"]


def room_loads(room: Room, reg, hrs=None, top_floor=None) -> RoomLoad:
    hrs = climate.hours() if hrs is None else hrs
    top = reg["floor_position"] == "top" if top_floor is None else top_floor
    kind, prof = room_profile(room.name)
    lat, doy, north = reg["latitude_deg"], reg["day_of_year"], reg["north_offset_deg"]
    Ti = reg["T_in"]
    w_in = climate.humidity_ratio(Ti, reg["RH_in"])
    dw = max(0.0, reg["w_out"] - w_in)
    rho, cp, hfg = reg["rho_air"], reg["cp_air"], reg["h_fg"]

    area = room.floor_area
    people = area / prof["m2_per_person"] if prof["m2_per_person"] else 0.0
    always_on = prof.get("always_on", False)
    on_chiller = not (kind == "server" and not reg["server_on_chiller"])

    # envelope surfaces: (U·A, absorptance-area for sol-air, azimuth) and glazing
    opaque, glazing = [], []
    for w in room.walls:
        if w.exterior_length <= 1e-3:
            continue
        az = w.azimuth(north)
        glass = sum(o.area for o in w.exterior_openings("Window"))
        doors = sum(o.area for o in w.exterior_openings("Door"))
        if reg["exterior_doors_glazed"]:
            glass += doors          # otherwise doors are lumped in as opaque wall
        opaque.append((w.exterior_gross_area - glass, az))
        if glass > 0:
            glazing.append((glass, az))

    infil_m = rho * reg["infiltration_ach"] * room.volume / 3600 if room.is_perimeter else 0.0
    vent_m = rho * (reg["vent_L_s_person"] * people + reg["vent_L_s_m2"] * area) / 1000
    H_env = (sum(reg["U_wall"] * a for a, _ in opaque) + sum(reg["U_window"] * a for a, _ in glazing)
             + (reg["U_roof"] * area if top else 0.0) + infil_m * cp)

    out = {k: np.zeros(len(hrs)) for k in COMPONENTS}
    for i, h in enumerate(hrs):
        To = climate.outdoor_temp(h, reg["T_out_max"], reg["T_out_range"])
        occ = occupied(h, reg)
        for a, az in opaque:
            I = climate.irradiance(h, az, 90, lat, doy)
            out["wall"][i] += reg["U_wall"] * a * (To + reg["alpha_wall"] * I / reg["h_out"] - Ti)
        for a, az in glazing:
            I = climate.irradiance(h, az, 90, lat, doy)
            out["window_cond"][i] += reg["U_window"] * a * (To - Ti)
            out["window_solar"][i] += a * reg["SHGC"] * reg["IAC"] * I
        if top:
            I = climate.irradiance(h, 0, 0, lat, doy)
            # -4 K long-wave sky correction for horizontal surfaces (ASHRAE)
            tsa = To + reg["alpha_roof"] * I / reg["h_out"] - 4.0
            out["roof"][i] = reg["U_roof"] * area * (tsa - Ti)
        sched_l = 1.0 if (occ or always_on) else reg["offhours_light_frac"]
        sched_e = 1.0 if (occ or always_on) else reg["offhours_equip_frac"]
        out["lights"][i] = prof["light"] * area * sched_l
        out["equipment"][i] = prof.get("equip_fixed_W", prof.get("equip", 0) * area) * sched_e
        if occ:
            out["people_s"][i] = people * reg["people_sensible_W"]
            out["people_l"][i] = people * reg["people_latent_W"]
            out["vent_s"][i] = vent_m * cp * (To - Ti)
            out["vent_l"][i] = vent_m * hfg * dw
        out["infil_s"][i] = infil_m * cp * (To - Ti)
        out["infil_l"][i] = infil_m * hfg * dw
    return RoomLoad(room.name, kind, area, people, on_chiller, H_env, out)


def building_loads(b: Building, reg, hrs=None, top_floor=None) -> dict[str, RoomLoad]:
    return {n: room_loads(r, reg, hrs, top_floor) for n, r in b.rooms.items()}
