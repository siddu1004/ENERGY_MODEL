"""Stage 2 - worked hypothetical example, end to end.

USDZ geometry -> room loads (steady-state hourly) -> dynamic RC floor model
-> building scale-up -> chiller plant energy (design point + hourly part-load)
-> uncertainty register.  Writes reports/stage2/report.md and charts.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from energy_model import plant  # noqa: E402
from energy_model.climate import outdoor_temp  # noqa: E402
from energy_model.defaults import default_registry  # noqa: E402
from energy_model.geometry import load_usdz  # noqa: E402
from energy_model.loads import building_loads  # noqa: E402
from energy_model.provenance import Source  # noqa: E402
from energy_model.rc_model import simulate_floor  # noqa: E402

USDZ = ROOT / "sample_data" / "sample_building.usdz"
XLSX = ROOT / "sample_data" / "sample_chiller_calculations.xlsx"
OUT = ROOT / "reports" / "stage2"
TR = 3.51685
PARTS = ["chiller_kW", "chw_pump_kW", "cw_pump_kW", "tower_fan_kW", "ahu_fan_kW"]
PART_LABELS = ["Chiller", "CHW pump", "CW pump", "Tower fans", "AHU fans"]


def coil_profile(L):
    return sum(r.coil_total for r in L.values() if r.on_chiller)


def floor_case(b, reg, top):
    L = building_loads(b, reg, top_floor=top)
    ss = coil_profile(L)
    dyn = simulate_floor(L, b.floor_area, b.volume, reg, q_max_W=1.3 * ss.max())
    return L, ss, dyn


def fmt(x, nd=1):
    return f"{x:,.{nd}f}"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    md: list[str] = []
    w = md.append

    # ---------------- 1. geometry ----------------
    b = load_usdz(USDZ)
    reg = default_registry()
    s = b.summary()
    reg.set("floor_area_m2", s["floor_area_m2"], "m²", Source.USDZ)
    w("# Stage 2 — Worked hypothetical example\n")
    w("> All inputs are synthetic or assumed. Every number below is a **prediction**, "
      "not a measured or validated value.\n")
    w("## 1. Geometry extracted from USDZ\n")
    w(f"Rooms **{s['rooms']}** · floor area **{fmt(s['floor_area_m2'])} m²** · volume "
      f"**{fmt(s['volume_m3'])} m³** · exterior wall **{fmt(s['exterior_wall_gross_area_m2'])} m²** · "
      f"windows **{fmt(s['exterior_window_area_m2'])} m²** · WWR **{s['window_to_wall_ratio']:.1%}**\n")
    w("Parser output matches the ground-truth file exactly (see `tests/`). Exterior walls were "
      "*inferred* from shared-wall geometry; orientation uses the ARKit convention (−Z = north) "
      "as an **assumption**.\n")
    w("| Room | Area m² | Volume m³ | Exterior walls (facing) | Window m² |")
    w("|---|---:|---:|---|---:|")
    compass = {0: "N", 90: "E", 180: "S", 270: "W"}
    for n, r in b.rooms.items():
        ext = [f"{compass[round(x.azimuth())]} {x.exterior_length:.0f} m"
               for x in r.walls if x.exterior_length > 1e-3]
        win = sum(o.area for x in r.walls for o in x.exterior_openings("Window"))
        w(f"| {n} | {fmt(r.floor_area)} | {fmt(r.volume)} | {', '.join(ext) or '— (interior)'} | {fmt(win, 2)} |")

    # ---------------- 2. room loads ----------------
    L, ss, dyn = floor_case(b, reg, top=False)
    hpk = int(ss.argmax())
    w("\n## 2. Room-wise cooling loads (steady-state, design day)\n")
    w(f"Design day: T_max {reg['T_out_max']} °C, range {reg['T_out_range']} K, lat "
      f"{reg['latitude_deg']}°N, 21 May, indoor {reg['T_in']} °C / {reg['RH_in']:.0%} RH. "
      f"Intermediate floor (no roof).\n")
    w("| Room | Type | People | Peak coil kW | Peak hour | W/m² | On chiller? |")
    w("|---|---|---:|---:|---:|---:|---|")
    for n, r in L.items():
        c = r.coil_total
        w(f"| {n} | {r.kind} | {r.people:.1f} | {c.max()/1e3:.1f} | {c.argmax()}:00 | "
          f"{c.max()/r.area:.0f} | {'yes' if r.on_chiller else '**no (assumed)**'} |")
    sum_room_peaks = sum(r.coil_total.max() for r in L.values() if r.on_chiller)
    w(f"\nSum of individual room peaks **{sum_room_peaks/1e3:.1f} kW** vs coincident "
      f"(block) peak **{ss.max()/1e3:.1f} kW at {hpk}:00**: rooms peak at different times "
      f"(east-facing in the morning, west-facing in the afternoon). Size AHUs on room peaks, "
      f"the chiller on the block peak.\n")
    w(f"**Block load breakdown at {hpk}:00 (kW)**\n")
    comp = {k: sum(r.hourly[k][hpk] for r in L.values() if r.on_chiller) / 1e3
            for k in L["Open_Office"].hourly}
    w("| " + " | ".join(comp) + " |")
    w("|" + "---:|" * len(comp))
    w("| " + " | ".join(f"{v:.1f}" for v in comp.values()) + " |")
    lat = comp["people_l"] + comp["infil_l"] + comp["vent_l"]
    tot = sum(comp.values())
    w(f"\nLatent share **{lat/tot:.0%}**. This is what limits how far CHWS can be raised later.\n")

    # ---------------- 3. dynamic ----------------
    w("## 3. Dynamic RC model vs steady-state\n")
    p = dyn.params
    w(f"C_air {p['C_air_MJ_K']:.1f} MJ/K · C_slab {p['C_mass_MJ_K']:.0f} MJ/K · slab time "
      f"constant {p['tau_mass_h']:.1f} h · envelope conductance {p['H_env_W_K']:.0f} W/K\n")
    occ = (np.arange(24) >= reg["occ_start_h"]) & (np.arange(24) < reg["occ_end_h"])
    e_ss = ss[occ].sum() / 1e3
    e_dyn = dyn.Q_coil_W.sum() / 1e3
    w("| | Steady-state | Dynamic (RC) |")
    w("|---|---:|---:|")
    w(f"| Peak coil load kW | {ss.max()/1e3:.1f} | {dyn.Q_coil_W.max()/1e3:.1f} (at {dyn.Q_coil_W.argmax()}:00) |")
    w(f"| Daily cooling kWh_th | {e_ss:.0f} | {e_dyn:.0f} |")
    w(f"| Slab temp at start-up | — | {dyn.T_mass[reg['occ_start_h']]:.1f} °C |")
    w("\nWith the plant off overnight, heat stored in the slab is released next morning: an 8:00 "
      "pull-down spike and a higher load all day. Steady-state under-predicts daily cooling by "
      f"**{(e_dyn/e_ss-1):.0%}** here.\n")

    # ---------------- 4. sensitivity of unknowns ----------------
    w("## 4. How much do the unknowns matter? (one at a time, dynamic model)\n")
    base_peak, base_e = dyn.Q_coil_W.max() / 1e3, e_dyn
    rows = []

    def variant(label, top=False, **changes):
        r2 = copy.deepcopy(reg)
        for k, v in changes.items():
            r2.params[k].value = v
        _, _, d2 = floor_case(b, r2, top)
        rows.append((label, d2.Q_coil_W.max() / 1e3, d2.Q_coil_W.sum() / 1e3))
        return d2

    for ang in (90, 180, 270):
        variant(f"Orientation rotated {ang}°", north_offset_deg=ang)
    variant("U_wall 1.5 → 0.6 (insulated)", U_wall=0.6)
    variant("Double glazing U 2.8, SHGC 0.3", U_window=2.8, SHGC=0.3)
    variant("No blinds (IAC 1.0)", IAC=1.0)
    variant("Outdoor ω 0.020 (very humid)", w_out=0.020)
    variant("T_out_max 42 °C", T_out_max=42.0)
    dyn_top = variant("Top floor (adds roof)", top=True)
    w("| Change | Peak kW | Δ peak | Daily kWh_th | Δ energy |")
    w("|---|---:|---:|---:|---:|")
    w(f"| **Baseline** | {base_peak:.1f} | — | {base_e:.0f} | — |")
    for lab, pk, e in rows:
        w(f"| {lab} | {pk:.1f} | {pk/base_peak-1:+.0%} | {e:.0f} | {e/base_e-1:+.0%} |")
    w("\nOrientation is not in the scan, but for this floor it moves the peak by only a few percent. "
      "Climate, floor position (roof) and glazing matter far more, so those questions get asked first.\n")

    # ---------------- 5. building scale ----------------
    w("## 5. Scaling to the building: the chiller-size question\n")
    int_prof, top_prof = dyn.Q_coil_W / 1e3, dyn_top.Q_coil_W / 1e3
    pin = plant.read_excel_inputs(XLSX)
    design = plant.design_point(pin)
    cap = design["Q_kW"]
    # largest N with (N-1) intermediate + 1 top floor <= 90 % of capacity
    n_floors = 1
    while (n_floors * int_prof + top_prof).max() <= 0.90 * cap:
        n_floors += 1
    bld = (n_floors - 1) * int_prof + top_prof
    reg.set("floors_served", n_floors, "floors", Source.ASSUMED,
            "Back-calculated so building peak ≈ 90 % of chiller capacity")
    w(f"One floor peaks at **{base_peak:.0f} kW ({base_peak/TR:.1f} TR)** but the chiller is "
      f"**{cap:.0f} kW (250 TR)**. The number of floors is NOT in the scan.\n")
    w(f"For a working example we **assume {n_floors} identical floors** ({n_floors-1} intermediate + "
      f"1 top) → building peak **{bld.max():.0f} kW ({bld.max()/TR:.0f} TR, "
      f"{bld.max()/cap:.0%} of capacity)**, {bld.sum():,.0f} kWh_th/day. "
      f"Gross area {n_floors*600:,} m² → {n_floors*600/(bld.max()/TR):.0f} m²/TR.\n")
    w("⚠ **Placeholder. The engineer must confirm floors served.**\n")

    # ---------------- 6. plant ----------------
    fit = plant.fit_partload(XLSX)
    he = plant.hourly_energy(bld, pin, design, fit, occ)
    e_parts = {k: he[k].sum() for k in PARTS}
    e_total = sum(e_parts.values())
    th = bld.sum()
    w("## 6. Chiller plant energy\n")
    w(f"Part-load curve fitted to the workbook data (CHWS 6 °C, ECWT 29.4 °C): "
      f"P/P_ref = {fit.coeffs[0]:.3f} + {fit.coeffs[1]:.3f}·PLR + {fit.coeffs[2]:.3f}·PLR² "
      f"(R² {fit.r2:.4f}, RMSE {fit.rmse_kW:.1f} kW, PLR {fit.plr_range[0]}–{fit.plr_range[1]}, "
      f"{fit.n_points} points).\n")
    w("| | A. Excel method (full load all hours, constant kW/TR) | B. Load-driven (hourly, part-load curve) |")
    w("|---|---:|---:|")
    excel_map = dict(zip(PARTS, ["Chiller_kW", "CHW_pump_kW", "CW_pump_kW", "CT_fan_kW", "AHU_fan_kW"]))
    hrs = pin["Hours_per_day"]
    for k, lab in zip(PARTS, PART_LABELS):
        w(f"| {lab} kWh/day | {design[excel_map[k]]*hrs:,.0f} | {e_parts[k]:,.0f} |")
    days = pin["Days_per_month"] * pin["Months_per_year"]
    w(f"| **Total kWh/day** | **{design['E_day']:,.0f}** | **{e_total:,.0f}** |")
    w(f"| Cooling delivered kWh_th/day | {design['Q_kW']*hrs:,.0f} | {th:,.0f} |")
    w(f"| Average plant kW/TR | {design['Plant_kW_per_TR']:.2f} | {e_total/(th/TR):.2f} |")
    w(f"| Average chiller kW/TR | {pin['Chiller_kW_per_TR']:.2f} | {e_parts['chiller_kW']/(th/TR):.2f} |")
    w(f"| Annual kWh ({days} days) | {design['E_year']:,.0f} | {e_total*days:,.0f} |")
    w(f"| Annual cost @ {pin['Tariff_per_kWh']} INR/kWh | "
      f"{design['Cost_year']:,.0f} | {e_total*days*pin['Tariff_per_kWh']:,.0f} |")
    aux = e_total - e_parts["chiller_kW"]
    w(f"\nIn B the chiller averages {he['PLR'][occ].mean():.0%} PLR, but pumps and fans run at full "
      f"design power regardless → auxiliaries are **{aux/e_total:.0%}** of plant energy "
      f"(vs {1-design['Chiller_share']:.0%} in A). That constant-speed auxiliary energy is the first "
      "optimisation target for Stage 3.\n")
    w("Both columns assume every day is the design day, so annual figures are an **upper bound** "
      "until real weather data and schedules are used.\n")
    if he["overloaded"].any():
        reg.flag("HIGH", "Capacity", "Predicted load exceeds chiller capacity in some hours.")
    if he["below_min_plr"].any():
        reg.flag("MEDIUM", "Part-load", "Load below lowest tested PLR; curve held flat (extrapolation).")

    # ---------------- 7. issues ----------------
    reg.flag("HIGH", "Floors served",
             f"Scan covers 1 floor (600 m²); chiller is 250 TR. Assumed {n_floors} floors to make the "
             "numbers consistent.", ["Enter floors served", "Provide whole-building load", "Accept assumption"])
    rot = [pk for lab, pk, _ in rows if lab.startswith("Orientation")] + [base_peak]
    reg.flag("MEDIUM", "Orientation",
             f"True north unknown. Floor peak ranges {min(rot):.1f}–{max(rot):.1f} kW over 4 orientations.",
             ["Give compass bearing of a façade", "Run all 4 as scenarios"])
    reg.flag("HIGH", "Envelope",
             "U-values, SHGC and shading are assumed (U_wall 1.5, single tinted glass).",
             ["Accept", "Enter construction details", "Run insulated / double-glazed scenarios"])
    reg.flag("HIGH", "Server room",
             "Server room needs 24 h cooling (~12 kW) but the chiller runs 12 h/day. Assumed on separate "
             "cooling.", ["Confirm separate CRAC/DX", "Include in chiller load (24 h operation)"])
    reg.flag("HIGH", "Climate & floor position",
             "Site and design conditions are placeholders (+4 °C → +17 % peak); top floor adds +31 %.",
             ["Enter city / weather file", "Confirm which floor was scanned"])
    reg.flag("MEDIUM", "Room use", "Room function inferred from names; a real scan has no office labels.",
             ["Confirm room types"])
    reg.flag("MEDIUM", "Condenser",
             "Condenser water temperature held at 29.4 °C; really varies with outdoor wet-bulb.",
             ["Provide tower approach / BMS data"])
    reg.flag("LOW", "Simplifications",
             "Interior doors, furniture mass, equation-of-time and wall time-lag ignored.")
    w("## 7. Open issues the system would raise (priority order)\n")
    rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    w("| Priority | Topic | Issue | Engineer options |")
    w("|---|---|---|---|")
    for i in sorted(reg.issues, key=lambda x: rank[x.priority]):
        w(f"| {i.priority} | {i.topic} | {i.message} | {' / '.join(i.options)} |")

    counts: dict[str, int] = {}
    for prm in reg.params.values():
        counts[prm.source.value] = counts.get(prm.source.value, 0) + 1
    w("\n## 8. Provenance of model parameters\n")
    w(" · ".join(f"**{k}** {v}" for k, v in sorted(counts.items())) + "\n")
    w("All outputs in this report are **PREDICTED**. None are VALIDATED; that requires the client's "
      "spreadsheets and measured BMS data.\n")

    charts(reg, L, ss, dyn, he, occ, rows, base_peak)
    w("## Charts\n")
    for f in ("room_loads.png", "load_profile.png", "sensitivity.png", "plant_energy.png"):
        w(f"![{f}]({f})\n")

    (OUT / "report.md").write_text("\n".join(md))
    print("\n".join(md))


def charts(reg, L, ss, dyn, he, occ, rows, base_peak):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False})
    groups = {"Envelope": ["wall", "window_cond", "roof", "infil_s"], "Solar": ["window_solar"],
              "Internal": ["people_s", "lights", "equipment"], "Ventilation": ["vent_s"],
              "Latent": ["people_l", "infil_l", "vent_l"]}
    colors = ["#5b7fa6", "#e8a33d", "#8c6bb1", "#4aa38a", "#c95f5f"]
    h = np.arange(24)

    # 1. room loads stacked at each room's own peak hour
    fig, ax = plt.subplots(figsize=(9, 4.2), dpi=150)
    names = list(L)
    bottom = np.zeros(len(names))
    for (g, keys), c in zip(groups.items(), colors):
        vals = np.array([sum(L[n].hourly[k][L[n].coil_total.argmax()] for k in keys) / 1e3 for n in names])
        ax.bar(names, vals, bottom=bottom, label=g, color=c)
        bottom += vals
    ax.set_ylabel("kW at room peak hour")
    ax.set_title("Room-wise peak cooling load by component (server room: separate cooling, assumed)")
    ax.legend(frameon=False, ncol=5, loc="upper right")
    plt.xticks(rotation=30, ha="right")
    fig.tight_layout(); fig.savefig(OUT / "room_loads.png"); plt.close(fig)

    # 2. profile
    fig, ax = plt.subplots(figsize=(9, 4), dpi=150)
    ax.step(h, np.where(occ, ss / 1e3, np.nan), where="post", label="Steady-state", color="#5b7fa6")
    ax.step(h, dyn.Q_coil_W / 1e3, where="post", label="Dynamic RC", color="#c95f5f")
    ax.set_xlabel("Hour"); ax.set_ylabel("Coil load per floor (kW)")
    ax2 = ax.twinx()
    ax2.plot(h + 0.5, [outdoor_temp(x + 0.5, reg["T_out_max"], reg["T_out_range"]) for x in h],
             color="#999", ls="--", label="Outdoor °C")
    ax2.plot(h + 0.5, dyn.T_mass, color="#e8a33d", ls=":", label="Slab °C")
    ax2.set_ylabel("°C")
    ax.legend(loc="upper left", frameon=False); ax2.legend(loc="upper right", frameon=False)
    ax.set_title("One floor, design day: thermal mass shifts load into the morning")
    fig.tight_layout(); fig.savefig(OUT / "load_profile.png"); plt.close(fig)

    # 3. sensitivity
    fig, ax = plt.subplots(figsize=(8, 4), dpi=150)
    labs = [r[0] for r in rows]
    d = [100 * (r[1] / base_peak - 1) for r in rows]
    order = np.argsort(np.abs(d))
    ax.barh([labs[i] for i in order], [d[i] for i in order],
            color=["#c95f5f" if d[i] > 0 else "#4aa38a" for i in order])
    ax.axvline(0, color="#333", lw=0.8)
    ax.set_xlabel("Change in floor peak load (%)")
    ax.set_title("Sensitivity to unknown inputs (one at a time)")
    fig.tight_layout(); fig.savefig(OUT / "sensitivity.png"); plt.close(fig)

    # 4. plant hourly stacked
    fig, ax = plt.subplots(figsize=(9, 4), dpi=150)
    ax.stackplot(h, *[he[k] for k in PARTS], labels=PART_LABELS, colors=colors, step="post")
    ax.set_xlabel("Hour"); ax.set_ylabel("Electric power (kW)")
    ax.set_ylim(0, 1.35 * sum(he[k] for k in PARTS).max())
    ax2 = ax.twinx()
    ax2.step(h, he["PLR"] * 100, where="post", color="#222", lw=1.2, label="Chiller PLR %")
    ax2.set_ylabel("PLR (%)"); ax2.set_ylim(0, 135)
    ax.legend(loc="upper left", frameon=False, ncol=3); ax2.legend(loc="upper right", frameon=False)
    ax.set_title("Building plant power, design day (load-driven baseline)")
    fig.tight_layout(); fig.savefig(OUT / "plant_energy.png"); plt.close(fig)


if __name__ == "__main__":
    main()
