"""Chiller plant calculations (mirrors the Excel 'Chiller_Plant_Calc' sheet).

design_point()  - same equations/names as the workbook -> cross-validated in tests
fit_partload()  - fit chiller power vs part-load ratio from tabulated data
hourly_energy() - plant electricity for an hourly coil-load profile
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from openpyxl import load_workbook

from .provenance import Registry


def read_excel_inputs(path) -> Registry:
    """Inputs sheet -> Registry (value, unit, source)."""
    ws = load_workbook(path, data_only=True)["Inputs"]
    reg = Registry()
    for name, value, unit, source, note in ws.iter_rows(min_row=2, max_col=5, values_only=True):
        if name and not str(name).startswith("---"):
            reg.set(name, value, unit or "", (source or "unknown").lower()
                    .replace("from_usdz", "usdz"), note or "")
    return reg


def read_excel_results(path) -> dict[str, float]:
    """Cached calculated values from the workbook (needs a recalculated file)."""
    ws = load_workbook(path, data_only=True)["Chiller_Plant_Calc"]
    return {row[1]: row[2] for row in ws.iter_rows(min_row=2, max_col=3, values_only=True)
            if row[1]}


def design_point(p) -> dict[str, float]:
    """All workbook formulas, in the same order. `p` is a Registry or dict."""
    r: dict[str, float] = {}
    r["Q_kW"] = p["Chiller_TR"] * p["kW_per_TR"]
    r["Q_load_kW"] = r["Q_kW"] * p["Load_factor"]
    r["CHW_dT"] = p["CHWR_C"] - p["CHWS_C"]
    r["CHW_kg_s"] = r["Q_kW"] / (p["Cp_water"] * r["CHW_dT"])
    r["CHW_m3_h"] = r["CHW_kg_s"] / p["Rho_water"] * 3600
    r["CHW_L_s"] = r["CHW_kg_s"] / p["Rho_water"] * 1000
    r["CHW_gpm"] = r["CHW_L_s"] * 15.8503
    r["CHW_gpm_per_TR"] = r["CHW_gpm"] / p["Chiller_TR"]
    r["Chiller_kW"] = p["Chiller_TR"] * p["Load_factor"] * p["Chiller_kW_per_TR"]
    r["Chiller_kWTR_chk"] = r["Chiller_kW"] / (r["Q_load_kW"] / p["kW_per_TR"])
    r["Chiller_COP"] = r["Q_load_kW"] / r["Chiller_kW"]
    r["CHW_pump_hyd_kW"] = p["Rho_water"] * p["g"] * (r["CHW_m3_h"] / 3600) * p["CHW_pump_head_m"] / 1000
    r["CHW_pump_kW"] = r["CHW_pump_hyd_kW"] / (p["CHW_pump_eff"] * p["Motor_eff"] * p["VFD_eff"])
    r["Q_rej_kW"] = r["Q_load_kW"] + r["Chiller_kW"]
    r["CW_kg_s"] = r["Q_rej_kW"] / (p["Cp_water"] * p["CW_dT_C"])
    r["CW_m3_h"] = r["CW_kg_s"] / p["Rho_water"] * 3600
    r["CW_pump_kW"] = (p["Rho_water"] * p["g"] * (r["CW_m3_h"] / 3600) * p["CW_pump_head_m"] / 1000
                       / (p["CW_pump_eff"] * p["Motor_eff"] * p["VFD_eff"]))
    r["CT_fan_kW"] = p["Chiller_TR"] * p["Load_factor"] * p["CT_fan_kW_per_TR"]
    r["Q_sens_kW"] = r["Q_load_kW"] * p["SHR"]
    r["Air_m3_s"] = r["Q_sens_kW"] / (p["Rho_air"] * p["Cp_air"] * p["Supply_air_dT_C"])
    r["AHU_fan_kW"] = r["Air_m3_s"] * p["AHU_SFP"]
    r["Total_kW"] = r["Chiller_kW"] + r["CHW_pump_kW"] + r["CW_pump_kW"] + r["CT_fan_kW"] + r["AHU_fan_kW"]
    r["Plant_kW_per_TR"] = r["Total_kW"] / (r["Q_load_kW"] / p["kW_per_TR"])
    r["Chiller_share"] = r["Chiller_kW"] / r["Total_kW"]
    r["E_chiller_day"] = r["Chiller_kW"] * p["Hours_per_day"]
    r["E_day"] = r["Total_kW"] * p["Hours_per_day"]
    r["E_month"] = r["E_day"] * p["Days_per_month"]
    r["E_year"] = r["E_month"] * p["Months_per_year"]
    r["Cost_month"] = r["E_month"] * p["Tariff_per_kWh"]
    r["Cost_year"] = r["E_year"] * p["Tariff_per_kWh"]
    return r


@dataclass
class PartLoadFit:
    coeffs: np.ndarray        # P/P_ref = c0 + c1·PLR + c2·PLR²
    r2: float
    rmse_kW: float
    plr_range: tuple[float, float]
    n_points: int

    def power_fraction(self, plr):
        return np.polyval(self.coeffs[::-1], plr)


def fit_partload(path, chws=6, ecwt=29.4, p_ref_kW=187.5) -> PartLoadFit:
    """Quadratic fit of chiller power fraction vs PLR at one CHWS/ECWT."""
    ws = load_workbook(path, data_only=True)["Chiller_PartLoad_Data"]
    pts = [(row[4], row[5]) for row in ws.iter_rows(min_row=2, values_only=True)
           if isinstance(row[0], (int, float)) and row[1] == chws and abs(row[2] - ecwt) < 1e-6]
    plr = np.array([a for a, _ in pts])
    frac = np.array([b for _, b in pts]) / p_ref_kW
    c = np.polyfit(plr, frac, 2)[::-1]
    pred = np.polyval(c[::-1], plr)
    ss_res = float(((frac - pred) ** 2).sum())
    ss_tot = float(((frac - frac.mean()) ** 2).sum())
    return PartLoadFit(c, 1 - ss_res / ss_tot, float(np.sqrt(ss_res / len(plr))) * p_ref_kW,
                       (float(plr.min()), float(plr.max())), len(plr))


def hourly_energy(coil_load_kW: np.ndarray, p, design: dict, fit: PartLoadFit,
                  on_mask: np.ndarray) -> dict[str, np.ndarray]:
    """Baseline operation: chiller follows load via part-load curve;
    pumps, tower fans and AHU fans run at constant (design) power while on.
    Below the lowest tested PLR the curve is held flat (chiller cycling /
    false loading) - an explicit extrapolation limit."""
    cap = design["Q_kW"]
    plr = np.clip(coil_load_kW / cap, 0, None)
    plr_eval = np.clip(plr, fit.plr_range[0], 1.0)
    p_ref = p["Chiller_TR"] * p["Chiller_kW_per_TR"]
    chiller = np.where(on_mask & (coil_load_kW > 0), p_ref * fit.power_fraction(plr_eval), 0.0)
    on = on_mask.astype(float)
    return {
        "PLR": plr,
        "chiller_kW": chiller,
        "chw_pump_kW": design["CHW_pump_kW"] * on,
        "cw_pump_kW": design["CW_pump_kW"] * on,
        "tower_fan_kW": design["CT_fan_kW"] * on,
        "ahu_fan_kW": design["AHU_fan_kW"] * on,
        "overloaded": plr > 1.0,
        "below_min_plr": (plr < fit.plr_range[0]) & on_mask & (coil_load_kW > 0),
    }
