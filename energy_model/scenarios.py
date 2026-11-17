"""Assemble the full model and run operating scenarios.

build()      loads + component models (hardware sized from BASE assumptions)
baseline()   fixed set-points, constant-speed pumps/fans
improved()   rule-based retrofit an engineer might apply
optimised()  hourly constrained optimisation
day()        daily totals
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from . import plant
from .climate import outdoor_temp, wet_bulb
from .defaults import default_registry
from .geometry import load_usdz
from .hvac import CoilModel, Tower, VariableSpeed, fit_chiller
from .optimize import Hour, Limits, System
from .pipeline import assume_floors, building_profile

ROOT = Path(__file__).resolve().parents[1]
USDZ = ROOT / "sample_data" / "sample_building.usdz"
XLSX = ROOT / "sample_data" / "sample_chiller_calculations.xlsx"
PARTS = ["chiller", "chw_pump", "cw_pump", "tower", "fan"]
COIL_MARGIN = 1.15     # assumed: coil sized 15 % above predicted peak sensible duty
FAN_C, PUMP_C = 0.25, 0.20
DESIGN_ECWT = 29.4     # condenser water temp at design (workbook data reference point)


def build(reg=None, lim=None, coil_margin=COIL_MARGIN, load_scale=1.0, n_floors=None):
    """Assemble loads + component models. Physical equipment (coil UA, tower
    approach) is sized from the BASE assumptions, so scenario changes alter
    operation/loads, not the hardware. `load_scale` scales building loads
    (calibration); `n_floors` overrides the assumed floor count."""
    reg = reg or default_registry()
    reg0 = default_registry()
    b = load_usdz(USDZ)
    pin = plant.read_excel_inputs(XLSX)
    d = plant.design_point(pin)
    n0 = assume_floors(b, reg0, d["Q_kW"])
    n = n_floors or n0
    bp = building_profile(b, reg, n)
    bp0 = building_profile(b, reg0, n0)
    chiller = fit_chiller(XLSX)
    coil = CoilModel(C_a0=pin["Rho_air"] * d["Air_m3_s"] * pin["Cp_air"],
                     C_w0=d["CHW_kg_s"] * pin["Cp_water"])
    fan = VariableSpeed(d["AHU_fan_kW"], FAN_C)
    hrs = [h for h in range(24) if bp.occupied[h]]
    k = max((h for h in range(24) if bp0.occupied[h]), key=lambda h: bp0.room_s[h] + bp0.vent_s[h])
    coil.calibrate(bp0.room_s[k] + bp0.vent_s[k] + fan.power(1.0), 6.0,
                   reg0["T_in"] + bp0.vent_s[k] / coil.C_a0, coil_margin)
    wb_design = wet_bulb(reg0["T_out_max"], reg0["w_out"])
    tower = Tower(d["CT_fan_kW"], DESIGN_ECWT - wb_design, d["Q_rej_kW"])
    sysm = System(chiller, coil, VariableSpeed(d["CHW_pump_kW"], PUMP_C), fan, tower,
                  d["CW_pump_kW"], T_room=reg["T_in"], lim=lim or Limits())
    H = {h: Hour(load_scale * bp.room_s[h], load_scale * bp.vent_s[h], load_scale * bp.lat_room[h],
                 load_scale * bp.lat_vent[h],
                 wet_bulb(outdoor_temp(h, reg["T_out_max"], reg["T_out_range"]), reg["w_out"]))
         for h in hrs}
    return dict(sys=sysm, H=H, hrs=hrs, n=n, design=d, pin=pin, bp=bp, reg=reg)


def baseline(S, Ts=6.0):
    return {h: S["sys"].evaluate((Ts, 1.0, 1.0, 1.0), S["H"][h]) for h in S["hrs"]}


def improved(S):
    """Typical engineer retrofit rules: CHWS 7 °C, pumps track load, VAV fans
    at 13 °C supply air, towers at full speed. Fallbacks keep it feasible."""
    sysm, out = S["sys"], {}
    for h in S["hrs"]:
        hr = S["H"][h]
        Q = hr.room_s + hr.vent_s + hr.lat_room + hr.lat_vent
        fw = float(np.clip(Q / S["design"]["Q_kW"], 0.5, 1.0))
        fa = float(np.clip(hr.room_s / (sysm.coil.C_a0 * (sysm.T_room - 13.0)), 0.5, 1.0))
        ev = None
        for Ts, fw_try in ((7.0, fw), (7.0, 1.0), (6.0, 1.0)):
            ev = sysm.evaluate((Ts, fw_try, fa, 1.0), hr)
            if not ev["feasible"]:
                fa2 = sysm.min_fan_for(Ts, fw_try, 1.0, hr)
                if fa2 is not None:
                    ev = sysm.evaluate((Ts, fw_try, max(fa, fa2), 1.0), hr)
            if ev["feasible"]:
                break
        out[h] = ev
    return out


def optimised(S):
    out, prev = {}, None
    for h in S["hrs"]:
        starts = None if prev is None else [list(prev["x"].values()), [6, 1, 1, 1],
                                            [8, 0.8, 0.85, 0.7], [9.5, 0.9, 0.95, 0.5]]
        out[h] = prev = S["sys"].optimize(S["H"][h], starts)
        if out[h] is None:
            raise RuntimeError(f"no feasible operating point at {h}:00")
    return out


def day(res):
    e = {p: sum(r["P"][p] for r in res.values()) for p in PARTS}
    e["total"] = sum(e[p] for p in PARTS)
    e["cooling"] = sum(r["Q_coil_kW"] for r in res.values())
    e["peak_kW"] = max(r["total_kW"] for r in res.values())
    e["feasible"] = all(r["feasible"] for r in res.values())
    return e
