"""Dynamic 2-node RC thermal model of one floor (air node + slab mass node).

  C_air · dT_a/dt  = Q_conv(t) + H_env·(T_eq(t) - T_a) + h_m·A_m·(T_m - T_a) - Q_cool
  C_mass · dT_m/dt = Q_rad(t) + h_m·A_m·(T_a - T_m)

  - Envelope conduction + infiltration are linear in T_a, so the steady-state
    loads computed at T_in are re-used:  Q_env(T_a) = Q_env(T_in) - H_env·(T_a - T_in)
  - Radiant parts of solar and internal gains are absorbed by the slab first and
    reach the air later -> peak cooling load is delayed and flattened.
  - Occupied hours: plant holds T_a at setpoint, limited to Q_max (pull-down).
    Unoccupied: plant off, T_a floats.
  - Ventilation and latent loads go straight to the coil (no mass interaction).

Limitations: one lumped zone per floor, intermediate floor (slab exchanges heat
only with this floor's air), explicit Euler with 60 s steps, repeated design
day until periodic.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .loads import CONVECTIVE_ENV, LATENT, RoomLoad


@dataclass
class RCResult:
    hours: np.ndarray
    Q_sensible_W: np.ndarray     # room sensible removed by plant (hourly mean)
    Q_coil_W: np.ndarray         # + ventilation sensible + all latent
    T_air: np.ndarray
    T_mass: np.ndarray
    params: dict


def simulate_floor(loads: dict[str, RoomLoad], floor_area: float, volume: float, reg,
                   q_max_W: float, days: int = 6, dt: float = 60.0) -> RCResult:
    rl = [r for r in loads.values() if r.on_chiller]
    hrs = np.arange(24)
    Ti = reg["T_in"]

    def total(keys):
        return sum(sum(r.hourly[k] for k in keys) for r in rl)

    env_at_Ti = total(CONVECTIVE_ENV)
    H_env = sum(r.H_env for r in rl)
    solar = total(["window_solar"])
    internal = total(["people_s", "lights", "equipment"])
    fs, fi = reg["radiant_frac_solar"], reg["radiant_frac_internal"]
    q_conv = env_at_Ti + (1 - fs) * solar + (1 - fi) * internal
    q_rad = fs * solar + fi * internal
    coil_extra = total(["vent_s"] + LATENT)

    area_on = sum(r.area for r in rl)
    vol_on = volume * area_on / floor_area
    C_air = reg["rho_air"] * reg["cp_air"] * vol_on * reg["air_capacity_multiplier"]
    A_m = 2 * area_on
    C_m = A_m * reg["slab_active_thickness_m"] * reg["concrete_rho_cp"]
    hA = reg["h_mass_air"] * A_m

    steps_per_h = int(3600 / dt)
    Ta = Tm = Ti
    q_hour = np.zeros(24)
    ta_hour = np.zeros(24)
    tm_hour = np.zeros(24)
    for day in range(days):
        last = day == days - 1
        for h in range(24):
            occ = reg["occ_start_h"] <= h < reg["occ_end_h"]
            # hourly forcing held constant within the hour (matches hourly loads)
            qc, qr = q_conv[h], q_rad[h]
            acc_q = acc_ta = acc_tm = 0.0
            for _ in range(steps_per_h):
                net_air = qc - H_env * (Ta - Ti) + hA * (Tm - Ta)
                if occ:
                    # cooling needed to bring Ta to setpoint this step
                    need = net_air + C_air * (Ta - Ti) / dt
                    q = min(max(need, 0.0), q_max_W)
                else:
                    q = 0.0
                Ta += dt * (net_air - q) / C_air
                Tm += dt * (qr + hA * (Ta - Tm)) / C_m
                acc_q += q; acc_ta += Ta; acc_tm += Tm
            if last:
                q_hour[h] = acc_q / steps_per_h
                ta_hour[h] = acc_ta / steps_per_h
                tm_hour[h] = acc_tm / steps_per_h

    occ_mask = np.array([reg["occ_start_h"] <= h < reg["occ_end_h"] for h in hrs])
    coil = q_hour + coil_extra * occ_mask
    return RCResult(hrs, q_hour, coil, ta_hour, tm_hour,
                    dict(C_air_MJ_K=C_air / 1e6, C_mass_MJ_K=C_m / 1e6, hA_W_K=hA,
                         H_env_W_K=H_env, tau_mass_h=C_m / hA / 3600))
