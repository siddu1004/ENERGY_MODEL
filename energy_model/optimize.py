"""Coupled chilled-water system model + constrained optimisation.

Decision variables (per hour), x = [Ts, fw, fa, ft]
  Ts  chilled-water supply temperature (°C)
  fw  CHW pump speed / flow fraction   (VFD)
  fa  AHU supply-air fan speed / flow fraction (VFD)
  ft  cooling-tower fan speed fraction

Objective   P_total(x) = P_chiller + P_chw_pump + P_cw_pump + P_tower + P_fan   (kW)
            (energy E = Σ_hours P_total · 1 h)

Couplings modelled
  - fan heat adds to the coil load, pump heat adds to the chiller load
  - higher Ts -> lower coil capacity -> more airflow or water flow needed
  - higher Ts -> higher dew point of supply air -> less dehumidification
  - tower fan speed -> condenser water temp (ECWT) -> chiller power
  - heat rejected = chiller load + compressor power  (iterated)

Constraints g(x) >= 0
  coil      sensible capacity >= sensible duty
  humidity  Ts + ADP offset <= dew point needed to hold RH_max
  supply    supply-air temp >= T_sa_min (draughts / diffuser condensation)
  evap ΔT   chiller evaporator ΔT <= limit (low-flow protection)
  capacity  chiller load <= available capacity
  PLR       load >= min PLR of the data (no extrapolation / surge)
  ECWT      within the range of the chiller data (no extrapolation)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize

from .climate import dew_point, humidity_ratio
from .hvac import ChillerModel, CoilModel, Tower, VariableSpeed

VARS = ["Ts", "fw", "fa", "ft"]
CONSTRAINTS = ["coil", "humidity", "supply_air", "evap_dT", "capacity", "min_PLR", "ECWT_min", "ECWT_max"]


@dataclass
class Limits:
    Ts: tuple = (5.0, 10.0)
    fw: tuple = (0.5, 1.0)       # min evaporator flow 50 % (assumed, check chiller manual)
    fa: tuple = (0.5, 1.0)       # min airflow for ventilation / distribution (assumed)
    ft: tuple = (0.3, 1.0)
    T_sa_min: float = 12.0
    RH_max: float = 0.55
    adp_offset: float = 4.0      # supply-air dew point achievable ≈ Ts + offset (assumed)
    evap_dT_max: float = 9.0

    def bounds(self):
        return [self.Ts, self.fw, self.fa, self.ft]


@dataclass
class Hour:
    room_s: float
    vent_s: float
    lat_room: float
    lat_vent: float
    wb: float


@dataclass
class System:
    chiller: ChillerModel
    coil: CoilModel
    chw_pump: VariableSpeed
    fan: VariableSpeed
    tower: Tower
    cw_pump_kW: float
    T_room: float = 24.0
    cp_air: float = 1.006       # kJ/kgK
    h_fg: float = 2501.0        # kJ/kg
    lim: Limits = field(default_factory=Limits)
    chiller_scale: float = 1.0  # sensitivity: efficiency improvement multiplier

    def evaluate(self, x, h: Hour) -> dict:
        Ts, fw, fa, ft = (float(v) for v in x)
        lim = self.lim
        P_fan = self.fan.power(fa)
        C_a = self.coil.C_a0 * fa
        T_ma = self.T_room + h.vent_s / C_a
        Q_cs = h.room_s + h.vent_s + P_fan
        cap = self.coil.capacity(Ts, T_ma, fa, fw)
        Q_coil = Q_cs + h.lat_room + h.lat_vent
        P_chw = self.chw_pump.power(fw)
        Q_ch = Q_coil + P_chw
        P_ch = float(self.chiller.power(Q_ch, Ts, 29.4))
        for _ in range(6):                       # heat rejection <-> ECWT fixed point
            Q_rej = Q_ch + P_ch
            ecwt = h.wb + self.tower.approach(Q_rej, ft)
            P_ch = float(self.chiller.power(Q_ch, Ts, ecwt)) * self.chiller_scale
        P_t = self.tower.power(ft)
        total = P_ch + P_chw + self.cw_pump_kW + P_t + P_fan

        m_a = C_a / self.cp_air
        w_req = humidity_ratio(self.T_room, lim.RH_max) - h.lat_room / (m_a * self.h_fg)
        T_supply = self.T_room - h.room_s / C_a
        cap_ch = float(self.chiller.capacity_kW(Ts, ecwt))
        evap_dT = Q_ch / (self.coil.C_w0 * fw)
        g = {
            "coil": (cap - Q_cs) / 100,
            "humidity": dew_point(w_req) - (Ts + lim.adp_offset),
            "supply_air": T_supply - lim.T_sa_min,
            "evap_dT": lim.evap_dT_max - evap_dT,
            "capacity": (cap_ch - Q_ch) / 100,
            "min_PLR": Q_ch / cap_ch - self.chiller.domain["PLR_min"],
            "ECWT_min": ecwt - self.chiller.domain["Tc"][0],
            "ECWT_max": self.chiller.domain["Tc"][1] - ecwt,
        }
        return dict(x=dict(zip(VARS, (Ts, fw, fa, ft))), total_kW=total,
                    P=dict(chiller=P_ch, chw_pump=P_chw, cw_pump=self.cw_pump_kW, tower=P_t, fan=P_fan),
                    Q_chiller_kW=Q_ch, Q_coil_kW=Q_coil, ECWT=ecwt, CHWR=Ts + evap_dT,
                    T_mixed=T_ma, coil_cap_kW=cap, Q_coil_sens_kW=Q_cs, Q_rej_kW=Q_ch + P_ch,
                    T_dp_required=dew_point(w_req), cap_chiller_kW=cap_ch,
                    T_supply=T_supply, PLR=Q_ch / cap_ch, cop=Q_ch / P_ch, g=g,
                    feasible=all(v >= -1e-6 for v in g.values()))

    # ------------------------------------------------------------ solvers
    def optimize(self, h: Hour, starts=None, **overrides):
        """SLSQP from several starts; returns best feasible evaluation."""
        lb = [b[0] for b in self.lim.bounds()]
        ub = [b[1] for b in self.lim.bounds()]
        starts = starts or [[6, 1, 1, 1], [8, 0.8, 0.85, 0.7], [9.5, 0.9, 0.95, 0.5],
                            [7, 0.6, 0.75, 0.9], [9, 0.55, 1.0, 0.4]]
        cons = [{"type": "ineq", "fun": (lambda x, k=k: self.evaluate(x, h)["g"][k])} for k in CONSTRAINTS]
        best = None
        for x0 in starts:
            r = minimize(lambda x: self.evaluate(x, h)["total_kW"], x0, method="SLSQP",
                         bounds=list(zip(lb, ub)), constraints=cons,
                         options=dict(ftol=1e-7, maxiter=300))
            ev = self.evaluate(np.clip(r.x, lb, ub), h)
            if ev["feasible"] and (best is None or ev["total_kW"] < best["total_kW"]):
                best = ev
        return best

    def grid_search(self, h: Hour, n=(21, 11, 21, 15)):
        """Brute-force check of the optimiser (feasible minimum on a grid)."""
        axes = [np.linspace(a, b, k) for (a, b), k in zip(self.lim.bounds(), n)]
        best = None
        for Ts in axes[0]:
            for fw in axes[1]:
                for fa in axes[2]:
                    for ft in axes[3]:
                        ev = self.evaluate((Ts, fw, fa, ft), h)
                        if ev["feasible"] and (best is None or ev["total_kW"] < best["total_kW"]):
                            best = ev
        return best

    def min_fan_for(self, Ts, fw, ft, h: Hour):
        """Smallest fa meeting coil / supply-air / humidity constraints (bisection)."""
        keys = ("coil", "humidity", "supply_air")
        ok = lambda fa: all(self.evaluate((Ts, fw, fa, ft), h)["g"][k] >= 0 for k in keys)  # noqa: E731
        lo, hi = self.lim.fa
        if ok(lo):
            return lo
        if not ok(hi):
            return None
        for _ in range(40):
            mid = (lo + hi) / 2
            lo, hi = (lo, mid) if ok(mid) else (mid, hi)
        return hi
