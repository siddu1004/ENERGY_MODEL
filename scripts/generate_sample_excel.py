"""Generate a SYNTHETIC sample chiller-plant calculation workbook.

Stand-in for the client's engineering Excel sheets until real ones arrive.
All calculation cells are LIVE Excel formulas driven by the Inputs sheet,
so an engineer can change an input and Excel recalculates everything.

Every input carries a Source tag:
  HYPOTHETICAL - illustrative value from the project brief
  ASSUMED      - engineering assumption (typical range noted)
  CONSTANT     - physical constant / unit conversion
  FROM_USDZ    - taken from the synthetic sample building model

Output: sample_data/sample_chiller_calculations.xlsx
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.workbook.defined_name import DefinedName

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "sample_data" / "sample_chiller_calculations.xlsx"
TRUTH = ROOT / "sample_data" / "sample_building_ground_truth.json"

HDR = Font(bold=True, color="FFFFFF")
HDR_FILL = PatternFill("solid", fgColor="2F4F6F")
INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")   # yellow = editable
CALC_FILL = PatternFill("solid", fgColor="E2EFDA")    # green = formula
WARN_FILL = PatternFill("solid", fgColor="F8CBAD")

floor_area = json.loads(TRUTH.read_text())["totals"]["floor_area_m2"]

# (name, value, unit, source, note)
INPUTS = [
    ("--- Chiller ---",),
    ("Chiller_TR", 250, "TR", "HYPOTHETICAL", "Rated cooling capacity (project brief)"),
    ("CHWS_C", 6, "°C", "HYPOTHETICAL", "Chilled water supply temperature"),
    ("CHWR_C", 12, "°C", "HYPOTHETICAL", "Chilled water return temperature"),
    ("Chiller_kW_per_TR", 0.75, "kW/TR", "HYPOTHETICAL",
     "Full-load efficiency. Typical water-cooled centrifugal 0.50-0.75"),
    ("Load_factor", 1.0, "-", "ASSUMED",
     "Average load / rated. 1.0 = full load every hour (upper bound; real plants run part-load)"),
    ("--- Operation ---",),
    ("Hours_per_day", 12, "h/day", "HYPOTHETICAL", "Operating hours"),
    ("Days_per_month", 30, "day/month", "ASSUMED", "Use 26 if closed on Sundays"),
    ("Months_per_year", 12, "month/yr", "ASSUMED", "No seasonal shutdown assumed"),
    ("--- Chilled water pump ---",),
    ("CHW_pump_head_m", 30, "m", "ASSUMED", "Total dynamic head. Typical 20-40 m"),
    ("CHW_pump_eff", 0.75, "-", "ASSUMED", "Pump hydraulic efficiency. Typical 0.65-0.85"),
    ("Motor_eff", 0.93, "-", "ASSUMED", "Motor efficiency. IE3 ~0.93-0.95"),
    ("VFD_eff", 0.97, "-", "ASSUMED", "Drive efficiency. Typical 0.95-0.98"),
    ("--- Condenser side ---",),
    ("CW_dT_C", 5, "°C", "ASSUMED", "Condenser water range. Typical 5-6 °C"),
    ("CW_pump_head_m", 25, "m", "ASSUMED", "Typical 15-30 m"),
    ("CW_pump_eff", 0.75, "-", "ASSUMED", ""),
    ("CT_fan_kW_per_TR", 0.06, "kW/TR", "ASSUMED", "Cooling tower fans. Typical 0.04-0.10"),
    ("--- Air side (AHU fans) ---",),
    ("SHR", 0.75, "-", "ASSUMED", "Sensible heat ratio of the coil load"),
    ("Supply_air_dT_C", 11, "°C", "ASSUMED", "Room 24 °C - supply air 13 °C"),
    ("AHU_SFP", 1.2, "kW/(m³/s)", "ASSUMED", "Specific fan power. Typical 0.8-2.0"),
    ("--- Tariff ---",),
    ("Tariff_per_kWh", 8.0, "INR/kWh", "ASSUMED", "Replace with client tariff (and currency)"),
    ("--- Building (from USDZ) ---",),
    ("Scanned_floor_area_m2", floor_area, "m²", "FROM_USDZ",
     "Synthetic sample scan covers ONE floor only"),
    ("Floors_served", None, "floors", "UNKNOWN",
     "NOT in the scan. Engineer must supply - see Building_Load_Check"),
    ("--- Constants ---",),
    ("kW_per_TR", 3.51685, "kW/TR", "CONSTANT", "1 TR = 12,000 BTU/h"),
    ("Cp_water", 4.186, "kJ/(kg·K)", "CONSTANT", ""),
    ("Rho_water", 1000, "kg/m³", "CONSTANT", "≈999.9 at 6 °C"),
    ("g", 9.81, "m/s²", "CONSTANT", ""),
    ("Rho_air", 1.2, "kg/m³", "CONSTANT", ""),
    ("Cp_air", 1.006, "kJ/(kg·K)", "CONSTANT", ""),
]

# (label, name, formula, unit, equation shown to engineer)
CALCS = [
    ("--- 1. Cooling capacity ---",),
    ("Cooling capacity", "Q_kW", "=Chiller_TR*kW_per_TR", "kW", "Q = TR × 3.51685"),
    ("Actual average load", "Q_load_kW", "=Q_kW*Load_factor", "kW", "Q_load = Q × load factor"),
    ("--- 2. Chilled water flow ---",),
    ("CHW ΔT", "CHW_dT", "=CHWR_C-CHWS_C", "°C", "ΔT = T_return - T_supply"),
    ("CHW mass flow", "CHW_kg_s", "=Q_kW/(Cp_water*CHW_dT)", "kg/s", "ṁ = Q / (Cp × ΔT)"),
    ("CHW volume flow", "CHW_m3_h", "=CHW_kg_s/Rho_water*3600", "m³/h", "V = ṁ / ρ"),
    ("CHW volume flow", "CHW_L_s", "=CHW_kg_s/Rho_water*1000", "L/s", ""),
    ("CHW volume flow", "CHW_gpm", "=CHW_L_s*15.8503", "US gpm", "1 L/s = 15.85 gpm"),
    ("Flow per TR", "CHW_gpm_per_TR", "=CHW_gpm/Chiller_TR", "gpm/TR",
     "Rule of thumb 2.4 gpm/TR at 10 °F (5.6 °C) ΔT"),
    ("--- 3. Chiller power & efficiency ---",),
    ("Chiller electrical power", "Chiller_kW", "=Chiller_TR*Load_factor*Chiller_kW_per_TR", "kW",
     "P = TR × kW/TR  (constant kW/TR: ignores part-load curve)"),
    ("Chiller kW/TR (check)", "Chiller_kWTR_chk", "=Chiller_kW/(Q_load_kW/kW_per_TR)", "kW/TR",
     "kW/TR = P / TR"),
    ("Chiller COP", "Chiller_COP", "=Q_load_kW/Chiller_kW", "-", "COP = Q / P = 3.517 / (kW/TR)"),
    ("--- 4. CHW pump ---",),
    ("Hydraulic power", "CHW_pump_hyd_kW", "=Rho_water*g*(CHW_m3_h/3600)*CHW_pump_head_m/1000", "kW",
     "P_hyd = ρ g V H"),
    ("Electrical power", "CHW_pump_kW", "=CHW_pump_hyd_kW/(CHW_pump_eff*Motor_eff*VFD_eff)", "kW",
     "P_el = P_hyd / (η_pump η_motor η_VFD)"),
    ("--- 5. Condenser side ---",),
    ("Heat rejected", "Q_rej_kW", "=Q_load_kW+Chiller_kW", "kW", "Q_rej = Q_evap + P_comp"),
    ("CW mass flow", "CW_kg_s", "=Q_rej_kW/(Cp_water*CW_dT_C)", "kg/s", "ṁ = Q_rej / (Cp ΔT)"),
    ("CW volume flow", "CW_m3_h", "=CW_kg_s/Rho_water*3600", "m³/h", ""),
    ("CW pump electrical", "CW_pump_kW",
     "=Rho_water*g*(CW_m3_h/3600)*CW_pump_head_m/1000/(CW_pump_eff*Motor_eff*VFD_eff)", "kW", ""),
    ("Cooling tower fans", "CT_fan_kW", "=Chiller_TR*Load_factor*CT_fan_kW_per_TR", "kW", ""),
    ("--- 6. AHU fans ---",),
    ("Sensible load", "Q_sens_kW", "=Q_load_kW*SHR", "kW", "Q_s = Q × SHR"),
    ("Supply airflow", "Air_m3_s", "=Q_sens_kW/(Rho_air*Cp_air*Supply_air_dT_C)", "m³/s",
     "V = Q_s / (ρ cp ΔT)"),
    ("AHU fan power", "AHU_fan_kW", "=Air_m3_s*AHU_SFP", "kW", "P = V × SFP"),
    ("--- 7. Total system power ---",),
    ("Total cooling system power", "Total_kW",
     "=Chiller_kW+CHW_pump_kW+CW_pump_kW+CT_fan_kW+AHU_fan_kW", "kW", "Σ components"),
    ("Plant efficiency (all-in)", "Plant_kW_per_TR", "=Total_kW/(Q_load_kW/kW_per_TR)", "kW/TR", ""),
    ("Chiller share of total", "Chiller_share", "=Chiller_kW/Total_kW", "%", ""),
    ("--- 8. Energy & cost ---",),
    ("Chiller energy / day", "E_chiller_day", "=Chiller_kW*Hours_per_day", "kWh/day", "E = P × t"),
    ("Total energy / day", "E_day", "=Total_kW*Hours_per_day", "kWh/day", ""),
    ("Total energy / month", "E_month", "=E_day*Days_per_month", "kWh/month", ""),
    ("Total energy / year", "E_year", "=E_month*Months_per_year", "kWh/yr", ""),
    ("Cost / month", "Cost_month", "=E_month*Tariff_per_kWh", "INR/month", ""),
    ("Cost / year", "Cost_year", "=E_year*Tariff_per_kWh", "INR/yr", ""),
]

PERCENT = {"Chiller_share"}


def header(ws, row, cols):
    for c, text in enumerate(cols, 1):
        cell = ws.cell(row=row, column=c, value=text)
        cell.font, cell.fill = HDR, HDR_FILL


def define(wb, name, sheet, cell):
    wb.defined_names[name] = DefinedName(name, attr_text=f"'{sheet}'!${cell[0]}${cell[1:]}")


def readme(wb):
    ws = wb.active
    ws.title = "README"
    lines = [
        "SYNTHETIC SAMPLE — chiller plant calculation workbook",
        "",
        "This is NOT client data. It is a stand-in for the client's Excel sheets so the",
        "calculation engine can be built and tested before real files arrive.",
        "",
        "Sheets:",
        "  Inputs                 - every input with unit + SOURCE tag (yellow = editable)",
        "  Chiller_Plant_Calc     - live formulas: capacity, flow, power, COP, pumps, fans, energy, cost",
        "  Chiller_PartLoad_Data  - synthetic 'manufacturer-style' power table for curve fitting",
        "  CHW_Pump_Curve         - synthetic pump head/efficiency curve at 100% speed",
        "  Building_Load_Check    - sanity check of chiller size vs scanned floor area",
        "",
        "Source tags: HYPOTHETICAL (brief), ASSUMED (engineering assumption),",
        "  CONSTANT (physics), FROM_USDZ (sample scan), UNKNOWN (must ask engineer).",
        "",
        "Known simplifications (deliberate, to be replaced):",
        "  - Chiller kW/TR held constant; real kW/TR varies with load, CHWS and condenser temp",
        "    (see Chiller_PartLoad_Data).",
        "  - Load_factor = 1.0 means full load for every operating hour -> upper-bound energy.",
        "  - Pump/fan power at design point only; no affinity-law part-load reduction.",
        "  - Raising CHWS saves compressor power but reduces dehumidification - must be",
        "    checked against indoor humidity limits before recommending.",
        "",
        "Chiller_PartLoad_Data was generated from DOE-2 style curves (EIR-f(T), EIR-f(PLR))",
        "with invented coefficients + ±1.5% random noise (seed 42). Replace with the",
        "real chiller's manufacturer selection data or measured BMS data.",
    ]
    for i, line in enumerate(lines, 1):
        ws.cell(row=i, column=1, value=line)
    ws["A1"].font = Font(bold=True, size=14)
    ws.column_dimensions["A"].width = 100


def inputs_sheet(wb):
    ws = wb.create_sheet("Inputs")
    header(ws, 1, ["Parameter", "Value", "Unit", "Source", "Note"])
    r = 2
    for row in INPUTS:
        if len(row) == 1:
            ws.cell(row=r, column=1, value=row[0]).font = Font(bold=True)
        else:
            name, val, unit, src, note = row
            ws.cell(row=r, column=1, value=name)
            v = ws.cell(row=r, column=2, value=val)
            v.fill = WARN_FILL if src == "UNKNOWN" else INPUT_FILL
            ws.cell(row=r, column=3, value=unit)
            ws.cell(row=r, column=4, value=src)
            ws.cell(row=r, column=5, value=note)
            define(wb, name, "Inputs", f"B{r}")
        r += 1
    for col, w in zip("ABCDE", (26, 12, 12, 14, 80)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"


def calc_sheet(wb):
    ws = wb.create_sheet("Chiller_Plant_Calc")
    header(ws, 1, ["Quantity", "Name", "Value", "Unit", "Equation"])
    r = 2
    for row in CALCS:
        if len(row) == 1:
            ws.cell(row=r, column=1, value=row[0]).font = Font(bold=True)
        else:
            label, name, formula, unit, eq = row
            ws.cell(row=r, column=1, value=label)
            ws.cell(row=r, column=2, value=name)
            c = ws.cell(row=r, column=3, value=formula)
            c.fill = CALC_FILL
            c.number_format = "0.0%" if name in PERCENT else "#,##0.00"
            ws.cell(row=r, column=4, value=unit)
            ws.cell(row=r, column=5, value=eq)
            define(wb, name, "Chiller_Plant_Calc", f"C{r}")
        r += 1
    for col, w in zip("ABCDE", (30, 20, 16, 12, 60)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"


def partload_sheet(wb):
    """Synthetic manufacturer-style table: power vs load, CHWS and ECWT."""
    ws = wb.create_sheet("Chiller_PartLoad_Data")
    rng = random.Random(42)
    p_ref, cap_ref = 250 * 0.75, 250.0
    header(ws, 1, ["Load_TR", "CHWS_C", "ECWT_C", "Avail_Capacity_TR", "PLR", "Power_kW", "kW_per_TR"])
    r = 2
    for ecwt in (26.0, 29.4, 32.0):
        for chws in (5, 6, 7, 8, 9, 10):
            dts, dtc = chws - 6, ecwt - 29.4
            capft = 1 + 0.030 * dts - 0.010 * dtc
            eirft = 1 - 0.022 * dts + 0.0004 * dts ** 2 + 0.024 * dtc + 0.0003 * dtc ** 2
            avail = cap_ref * capft
            for pct in range(30, 101, 10):
                load = cap_ref * pct / 100
                if load > avail:
                    continue
                plr = load / avail
                eirfplr = 0.10 + 0.40 * plr + 0.50 * plr ** 2
                # P = P_ref * CAPFT * EIRFT * EIRFPLR  (DOE-2 / EnergyPlus form)
                power = p_ref * capft * eirft * eirfplr * (1 + rng.gauss(0, 0.015))
                ws.append([load, chws, ecwt, round(avail, 1), round(plr, 3),
                           round(power, 1), round(power / load, 3)])
                r += 1
    ws.append([])
    ws.append(["SYNTHETIC. Replace with manufacturer selection data or measured BMS trend data."])
    for col in "ABCDEFG":
        ws.column_dimensions[col].width = 18
    ws.freeze_panes = "A2"


def pump_sheet(wb):
    ws = wb.create_sheet("CHW_Pump_Curve")
    header(ws, 1, ["Flow_m3_h", "Head_m", "Pump_eff", "Shaft_kW"])
    q_des, h_des, h0 = 126.0, 30.0, 40.0
    k = (h0 - h_des) / q_des ** 2
    for q in range(20, 171, 10):
        head = h0 - k * q ** 2
        eff = max(0.0, 0.76 * (1 - ((q - 135) / 135) ** 2))
        shaft = 1000 * 9.81 * q / 3600 * head / 1000 / eff
        ws.append([q, round(head, 2), round(eff, 3), round(shaft, 2)])
    ws.append([])
    ws.append(["SYNTHETIC curve at 100% speed. Design point ≈ 126 m³/h @ 30 m."])
    ws.append(["Affinity laws for VFD speed ratio n: Q ∝ n, H ∝ n², P ∝ n³ "
               "(ignores static head / min ΔP setpoint)."])
    for col in "ABCD":
        ws.column_dimensions[col].width = 14


def building_check_sheet(wb):
    ws = wb.create_sheet("Building_Load_Check")
    header(ws, 1, ["Check", "Value", "Unit", "Comment"])
    rows = [
        ("Scanned floor area", "=Scanned_floor_area_m2", "m²", "From sample USDZ (one floor)"),
        ("Floors served by chiller", "=IF(ISBLANK(Floors_served),\"UNKNOWN\",Floors_served)", "",
         "Not in scan - engineer must provide"),
        ("Area per TR if chiller served only the scanned floor",
         "=Scanned_floor_area_m2/Chiller_TR", "m²/TR",
         "Typical office 18-30 m²/TR. Far below -> chiller serves more than this floor"),
        ("Implied floors (at 25 m²/TR)", "=Chiller_TR*25/Scanned_floor_area_m2", "floors",
         "Rough estimate only"),
        ("Status", "=IF(Scanned_floor_area_m2/Chiller_TR<10,"
                   "\"CHECK: chiller capacity inconsistent with scanned area - ask engineer\",\"OK\")",
         "", ""),
    ]
    for i, row in enumerate(rows, 2):
        for j, v in enumerate(row, 1):
            ws.cell(row=i, column=j, value=v)
        ws.cell(row=i, column=2).fill = CALC_FILL
        ws.cell(row=i, column=2).number_format = "#,##0.00"
    for col, w in zip("ABCD", (52, 22, 10, 70)):
        ws.column_dimensions[col].width = w


def main():
    wb = Workbook()
    readme(wb)
    inputs_sheet(wb)
    calc_sheet(wb)
    partload_sheet(wb)
    pump_sheet(wb)
    building_check_sheet(wb)
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                c.alignment = Alignment(vertical="center")
    OUT.parent.mkdir(exist_ok=True)
    wb.save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
