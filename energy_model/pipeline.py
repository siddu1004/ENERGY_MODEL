"""Shared pipeline: USDZ -> floor loads -> building hourly load components (kW)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .geometry import Building
from .loads import building_loads
from .rc_model import simulate_floor


def floor_case(b: Building, reg, top: bool):
    L = building_loads(b, reg, top_floor=top)
    ss = sum(r.coil_total for r in L.values() if r.on_chiller)
    dyn = simulate_floor(L, b.floor_area, b.volume, reg, q_max_W=1.3 * ss.max())
    return L, ss, dyn


@dataclass
class BuildingProfile:
    """Hourly building coil-load components in kW (24 values each)."""
    room_s: np.ndarray     # room sensible removed (dynamic, incl. pull-down)
    vent_s: np.ndarray     # outdoor-air sensible
    lat_room: np.ndarray   # people + infiltration latent
    lat_vent: np.ndarray   # outdoor-air latent
    occupied: np.ndarray   # bool
    n_floors: int

    @property
    def coil_total(self):
        return self.room_s + self.vent_s + self.lat_room + self.lat_vent


def _floor_components(b, reg, top):
    L, _, dyn = floor_case(b, reg, top)
    rl = [r for r in L.values() if r.on_chiller]
    occ = (np.arange(24) >= reg["occ_start_h"]) & (np.arange(24) < reg["occ_end_h"])

    def tot(k):
        return sum(r.hourly[k] for r in rl) / 1e3 * occ

    return dict(room_s=dyn.Q_sensible_W / 1e3, vent_s=tot("vent_s"),
                lat_room=tot("people_l") + tot("infil_l"), lat_vent=tot("vent_l")), occ


def assume_floors(b, reg, capacity_kW, fill=0.90) -> int:
    """Largest N (N-1 intermediate + 1 top) with building peak <= fill * capacity."""
    _, _, d_int = floor_case(b, reg, False)
    _, _, d_top = floor_case(b, reg, True)
    n = 1
    while (n * d_int.Q_coil_W + d_top.Q_coil_W).max() / 1e3 <= fill * capacity_kW:
        n += 1
    return n


def building_profile(b, reg, n_floors: int) -> BuildingProfile:
    mid, occ = _floor_components(b, reg, False)
    top, _ = _floor_components(b, reg, True)
    comp = {k: (n_floors - 1) * mid[k] + top[k] for k in mid}
    return BuildingProfile(**comp, occupied=occ, n_floors=n_floors)
