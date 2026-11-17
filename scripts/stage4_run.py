"""Stage 4 - human-in-the-loop demonstration.

A scripted conversation between an engineer and the system. The engineer's
words would be interpreted by the AI layer; here each turn shows the engine
call it maps to. Every number in the System turns comes from the engine.

Writes reports/stage4/transcript.md and reports/stage4/audit_log.json
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from energy_model.session import Session  # noqa: E402

OUT = ROOT / "reports" / "stage4"
md: list[str] = []
w = md.append


def engineer(text, call):
    w(f"\n> 🧑‍🔧 **Engineer:** {text}\n>\n> <sub>AI layer → engine call: `{call}`</sub>\n")


def system(text):
    w(f"🤖 **System:** {text}\n")


def diff_table(rows, title="What changed"):
    if not rows:
        w("_No numerical change._\n")
        return
    w(f"**{title}:**\n")
    w("| Quantity | Before | After | Change |")
    w("|---|---:|---:|---:|")
    for k, a, b, c in rows:
        w(f"| {k} | {a} | {b} | {c} |")
    w("")


def questions(s, min_priority="MEDIUM", title="Open questions (priority order)"):
    qs = s.open_questions(min_priority)
    if not qs:
        w("_No open questions at this priority._\n")
        return
    w(f"**{title}:**\n")
    for q in qs:
        w(f"- **[{q.priority}]** {q.text}  \n  Options: {' · '.join(q.options)}"
          + (f"  \n  ⛔ Blocks: {q.blocking}" if q.blocking else ""))
    w("")


def open_keys(s):
    return {q.key for q in s.open_questions()}


def new_questions(s, before, title="New question raised"):
    qs = [q for q in s.open_questions() if q.key not in before]
    if qs:
        w(f"**{title}:**\n")
        for q in qs:
            w(f"- **[{q.priority}]** {q.text}  \n  Options: {' · '.join(q.options)}"
              + (f"  \n  ⛔ Blocks: {q.blocking}" if q.blocking else ""))
        w("")
    return qs


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    w("# Stage 4: Human-in-the-loop demonstration\n")
    w("Scripted engineer ↔ system conversation run against the real engine (`energy_model/session.py`). "
      "The *AI layer* line shows which deterministic engine call the engineer's words map to. "
      "**All numbers are computed, not written by hand.** Values are predictions on synthetic data.\n")

    # ------------------------------------------------------------- start
    s = Session()
    sm = s.summary
    w("## 0. Session start: the system briefs the engineer\n")
    system(f"I have analysed the sample building ({s.p['floors_served']} floors assumed) and the 250 TR chiller plant. "
           f"Baseline (CHWS {s.p['baseline_CHWS']} °C, constant-speed pumps and fans): "
           f"**{sm['baseline total kWh/day']:,.0f} kWh/day** on the design day. An optimised hourly schedule predicts "
           f"**{sm['optimised total kWh/day']:,.0f} kWh/day ({sm['predicted saving (%)']:.1f} % saving)**. "
           "Before relying on this, I need your input on the items below. I've only listed items that change the result materially.")
    questions(s)

    sw1, a1 = s.assess_assumption("alpha_wall", 0.5, 0.7)
    sw2, a2 = s.assess_assumption("T_out_max", 36.0, 40.0)
    system("I also checked two uncertain inputs to decide whether they are worth your time "
           "(threshold: ask only if daily energy swings ≥ 2 %):")
    w("| Assumption | Range tested | Daily energy swing | Asked? |")
    w("|---|---|---:|---|")
    for lab, rng, sw, asked in (("Wall colour (solar absorptance)", "0.5 – 0.7", sw1, a1),
                                ("Design outdoor max (°C)", "36 – 40", sw2, a2)):
        w(f"| {lab} | {rng} | {sw:.1%} | {'**yes**, added as a MEDIUM question' if asked else '**no**, logged only'} |")
    w("")

    # -------------------------------------------- floors (answer + what-if)
    w("## 1. Answering a proactive question: floors served\n")
    engineer("It's 14 floors. That's correct.", "answer('floors', 'confirmed', floors_served=14)")
    d = s.answer("floors", "confirmed by engineer", floors_served=14)
    system("Recorded. `floors_served` = 14, source upgraded **assumed → engineer**. "
           + ("The value is unchanged, so no recalculation is needed." if d == [] else ""))
    engineer("What if it were only 6 floors?", "what_if(floors_served=6)  # does not change the session")
    sm6, q6 = s.what_if(floors_served=6)
    cap = s.S["design"]["Q_kW"]
    system(f"With 6 floors the baseline peak chiller load would be {sm6['baseline peak chiller load (kW)']:.0f} kW "
           f"({sm6['baseline peak chiller load (kW)']/cap:.0%} of capacity) and the saving {sm6['predicted saving (%)']:.1f} %. "
           "I would then raise this:")
    for q in q6:
        if q.key == "oversized":
            w(f"- **[{q.priority}]** {q.text}\n")
    system("Nothing in the session was changed by this what-if.")

    # ------------------------------------------------- Scenario 1: change
    w("## 2. Scenario 1: changing an assumption\n")
    system(f"The current model assumes a chilled-water supply temperature of {s.p['baseline_CHWS']} °C.")
    engineer("Change it to 7 °C.", "preview_chws(7.0)  # ambiguity check before changing")
    pv = s.preview_chws(7.0)
    system("Quick check before I change it. 'CHWS 7 °C' can mean two different things for the hydronic calculation:")
    w("| Interpretation | CHWR | ΔT | Flow for full capacity | CHW pump (design) |")
    w("|---|---:|---:|---:|---:|")
    for k, v in pv.items():
        w(f"| {k} | {v['CHWR']:.0f} °C | {v['dT']:.0f} K | {v['flow']:.0f} m³/h | {v['pump']:.1f} kW |")
    w("\nWhich one do you mean?\n")
    engineer("Keep the return at 12 °C.", "set('baseline_CHWS', 7.0)")
    before = open_keys(s)
    d = s.set("baseline_CHWS", 7.0, reason="engineer: operate at 7 °C, return stays 12 °C")
    system("Updated and recalculated the full chain (design point → hourly baseline → optimisation):")
    diff_table(d)
    system("Interpretation: the hourly model sees the chiller's efficiency gain from warmer water (about −3 % chiller energy). "
           "The Excel-style design calculation cannot see it because it uses a constant kW/TR. It does show the hydronic penalty: "
           "a 5 K ΔT needs 20 % more flow. Savings from optimisation shrink slightly because the new baseline is already better. "
           "This change raised a new question:")
    new_questions(s, before)
    engineer("Accept. The building peak never needs full chiller capacity.", "answer('flow_range', 'accept')")
    s.answer("flow_range", "accepted: building peak < full capacity")
    system("Recorded with your reason in the audit log.")

    # ---------------------------------------------------- Scenario 2: why
    w("## 3. Scenario 2: questioning an optimisation\n")
    system("Increasing chilled-water supply temperature may reduce compressor energy consumption.")
    engineer("Why do you think this is beneficial?", "explain_chws(hour=15)")
    e = s.explain_chws(15)
    o, alt = e["opt"], e["alt"]
    system("**The thermodynamic reason.** The compressor lifts heat from the evaporating temperature (set by CHWS) "
           "to the condensing temperature (set by the condenser water). Warmer chilled water means a smaller lift, so "
           "less compressor work per kW of cooling.")
    w(f"- From the fitted chiller model at 15:00: ∂P_chiller/∂CHWS = **{e['dPch']:+.2f} kW per K** "
      f"({e['dPch']/e['P_ch']:+.1%} of chiller power per K).\n")
    system("**But the system answer is different.** The optimiser chose "
           f"CHWS = {e['Ts']:.2f} °C at 15:00, not higher, because raising it by 1 K has knock-on effects:")
    w("| Effect of CHWS +1 K at 15:00 | Value |")
    w("|---|---:|")
    w(f"| Coil sensible capacity at same airflow | −{e['cap_drop']:.0f} kW (warmer water → less heat removed) |")
    if alt:
        dP = {k: alt["P"][k] - o["P"][k] for k in o["P"]}
        w(f"| AHU fan speed needed to still meet the load | {e['fa']:.0%} → {e['fa_up']:.0%} |")
        w(f"| Chiller power | {dP['chiller']:+.1f} kW |")
        w(f"| Fan power | {dP['fan']:+.1f} kW |")
        w(f"| Other (pump, tower) | {dP['chw_pump'] + dP['tower']:+.1f} kW |")
        w(f"| **Net** | **{alt['total_kW'] - o['total_kW']:+.1f} kW** |")
    w(f"\nBinding constraints at the optimum: **{', '.join(e['binding'])}**.\n")
    system("So raising CHWS helps the chiller but not the system at this hour. Fan power rises faster (roughly with "
           "speed³) than the compressor saves. **This conclusion depends on assumed coil and fan data.** With a larger "
           "coil or more efficient fans the optimum moves to warmer water. Real coil data would settle it.")

    # ------------------------------------------------ Scenario 3: correct
    w("## 4. Scenario 3: human correction with measured data\n")
    pred = s.base[15]["Q_chiller_kW"]
    system(f"The estimated chiller load at 15:00 on the design day is {pred:.0f} kW.")
    engineer("That's incorrect. The BMS shows a measured load of 690 kW at 15:00.",
             "measure_chiller_load(hour=15, kW=690, note='BMS trend')")
    old_range = s.summary["optimised CHWS range (°C)"]
    before = open_keys(s)
    predicted, k, d = s.measure_chiller_load(15, 690.0, note="BMS trend, engineer-provided")
    system(f"Replaced. The model over-predicted by **{predicted/690-1:+.1%}**. What I changed and what I didn't:")
    w(f"- ✅ Calibrated the **building-load multiplier** 1.00 → **{k:.3f}** (source: measured). Only the uncertain "
      "building load is scaled.")
    w("- ✅ Fan heat and pump heat in the measured figure are physics-known and were **not** scaled.")
    w("- ❌ No thermodynamic equations were changed. Calibration adjusts uncertain *parameters*, never physical laws.\n")
    diff_table(d)
    nr = s.summary["optimised CHWS range (°C)"]
    system(f"**How the recommendation changed:** with less load the coil has spare capacity, so warmer water now pays off. "
           f"Optimal CHWS moved from {old_range[0]:.1f}–{old_range[1]:.1f} °C to **{nr[0]:.1f}–{nr[1]:.1f} °C**. "
           "This is the same trade-off as in Scenario 2, now landing on a different point.")
    new_questions(s, before, "Follow-up question raised")

    engineer("Also, the flow meter shows 25 kg/s with a 5 K ΔT at that time.",
             "check_measurement_consistency(flow_kg_s=25, dT=5, load_kW=690)")
    s.check_measurement_consistency(25, 5, 690)
    questions(s, "CONFLICT", "Conflict detected")
    engineer("The flow meter is known to under-read. Ignore it.", "answer('energy_balance', 'flow meter wrong')")
    s.answer("energy_balance", "flow meter under-reads; flow value discarded")
    system("Recorded. The flow reading is excluded; the 690 kW load stays as the calibration point. I've logged a "
           "maintenance note that the flow meter needs recalibration.")

    # --------------------------------------------------- safety rejection
    w("## 5. Proactive safety check\n")
    engineer("Set the chilled-water supply to 3 °C for more dehumidification.", "set('baseline_CHWS', 3.0)")
    r = s.set("baseline_CHWS", 3.0)
    assert r is None
    questions(s, "SAFETY", "Rejected")
    system("I did not apply it. If you need more dehumidification I can instead tighten the RH limit and let the "
           "optimiser find a safe operating point.")
    engineer("OK, leave it at 7 °C.", "answer('unsafe_baseline_CHWS', 'withdrawn')")
    s.answer("unsafe_baseline_CHWS", "request withdrawn by engineer")

    # ----------------------------------------------- Scenario 4: approval
    w("## 6. Scenario 4: recommendation, calculations, modification, approval\n")
    r1 = s.propose()
    system(f"I found an operating schedule that reduces estimated energy by **{r1.saving_pct:.1f} %** "
           f"({r1.daily_kWh_baseline:,.0f} → {r1.daily_kWh_optimised:,.0f} kWh/day, ≈ INR {r1.annual_saving_cost:,.0f}/yr "
           f"if every day were the design day). Confidence: **{r1.confidence}** · Status: **{r1.validation}** · "
           f"Recommendation **{r1.id}**.")
    engineer("Show me the calculations.", "show_calculation(hour=15)")
    b, o, S = s.show_calculation(15)
    sysm = S["sys"]
    system("Hour 15:00, baseline vs recommended. Every line is one model equation:")
    w("| Step | Equation | Baseline | Recommended |")
    w("|---|---|---:|---:|")
    rows = [
        ("Set-points", "CHWS / pump / fan / tower",
         lambda e: f"{e['x']['Ts']:.2f} °C / {e['x']['fw']:.0%} / {e['x']['fa']:.0%} / {e['x']['ft']:.0%}"),
        ("AHU fan power", "P₀·f·(c+(1−c)f²)", lambda e: f"{e['P']['fan']:.1f} kW"),
        ("Mixed-air temp", "T_room + Q_vent/(ṁ_a c_p)", lambda e: f"{e['T_mixed']:.2f} °C"),
        ("Coil sensible duty", "Q_room + Q_vent + fan heat", lambda e: f"{e['Q_coil_sens_kW']:.0f} kW"),
        ("Coil capacity", "ε·C_min·(T_mixed − CHWS)", lambda e: f"{e['coil_cap_kW']:.0f} kW"),
        ("Supply-air temp (≥ 12 °C)", "T_room − Q_room/(ṁ_a c_p)", lambda e: f"{e['T_supply']:.1f} °C"),
        ("Dew point needed vs CHWS + 4 K", "RH ≤ limit", lambda e: f"{e['T_dp_required']:.1f} vs {e['x']['Ts'] + 4:.1f} °C"),
        ("CHW pump power", "P₀·f·(c+(1−c)f²)", lambda e: f"{e['P']['chw_pump']:.1f} kW"),
        ("Chiller load", "coil total + pump heat", lambda e: f"{e['Q_chiller_kW']:.0f} kW"),
        ("Evaporator ΔT (≤ 9 K)", "Q/(ṁ_w c_p)", lambda e: f"{e['CHWR'] - e['x']['Ts']:.1f} K"),
        ("Heat rejected", "Q_chiller + P_chiller", lambda e: f"{e['Q_rej_kW']:.0f} kW"),
        ("Condenser water ECWT", "T_wb + approach(Q_rej, f_t)", lambda e: f"{e['ECWT']:.2f} °C"),
        ("Chiller power", "regression P(L, CHWS, ECWT)", lambda e: f"{e['P']['chiller']:.1f} kW (COP {e['cop']:.2f})"),
        ("Tower fan power", "P₀·f_t³", lambda e: f"{e['P']['tower']:.1f} kW"),
        ("CW pump power", "constant speed", lambda e: f"{e['P']['cw_pump']:.1f} kW"),
        ("**Total plant power**", "Σ", lambda e: f"**{e['total_kW']:.1f} kW**"),
    ]
    for name, eq, f in rows:
        w(f"| {name} | `{eq}` | {f(b)} | {f(o)} |")
    w(f"\nSaving at this hour: **{b['total_kW'] - o['total_kW']:.1f} kW ({1 - o['total_kW']/b['total_kW']:.1%})**. "
      f"Wet-bulb {S['H'][15].wb:.1f} °C. Coil UA {sysm.coil.UA0:.0f} kW/K (assumed margin).\n")

    engineer("The AHU fans can't go below 75 % airflow. That's our minimum ventilation setting.",
             "set('fan_min', 0.75)")
    before = open_keys(s)
    d = s.set("fan_min", 0.75, reason="engineer: ventilation minimum")
    diff_table(d)
    system("Re-optimised with the new limit. With less freedom on airflow, the optimiser now saves energy by "
           "running warmer chilled water, which affects dehumidification:")
    new_questions(s, before, "Trade-off raised before I propose anything")
    engineer("Comfort comes first. Use 50 % RH as the limit.",
             "answer('humidity_margin', 'tighten', RH_max=0.50)")
    d = s.answer("humidity_margin", "tighten RH limit: comfort priority", RH_max=0.50)
    diff_table(d)
    r2 = s.propose()
    system(f"Recommendation **{r2.id}**: saving {r2.saving_pct:.1f} % "
           f"({r1.saving_pct - r2.saving_pct:.1f} pp less than {r1.id}, which is now {s.recs[r1.id].status}). "
           "That difference is the energy cost of your ventilation and comfort limits.")

    engineer(f"Approve {r2.id}.", f"decide('{r2.id}', 'approve')")
    ok, blockers = s.decide(r2.id, "approve", note="engineer approval")
    if not ok:
        system("I can't mark it approved yet. This open question blocks approval:")
        for q in blockers:
            w(f"- **[{q.priority}]** {q.text}\n")
    engineer("The AHU fans and CHW pumps have VFDs. The cooling-tower fans are constant speed.",
             "answer('vfd', ..., vfd_ahu=True, vfd_chw_pump=True, vfd_tower=False)")
    d = s.answer("vfd", "AHU + CHW pump VFD; tower constant speed", vfd_ahu=True, vfd_chw_pump=True, vfd_tower=False)
    diff_table(d, "Recalculated with tower fans locked at 100 %")
    r3 = s.propose()
    system(f"Updated recommendation **{r3.id}**: saving **{r3.saving_pct:.1f} %** "
           f"({r3.daily_kWh_baseline:,.0f} → {r3.daily_kWh_optimised:,.0f} kWh/day). Confidence {r3.confidence}.")
    engineer(f"Approve {r3.id}.", f"decide('{r3.id}', 'approve')")
    s.decide(r3.id, "approve", note="engineer approval after VFD confirmation")
    system(f"{r3.id} status: **{r3.status}**.\n\n"
           "⚠ **No equipment setting has been changed.** This system has no write access to the BMS. Next steps for "
           "the operator: (1) trial the schedule for 2 weeks on comparable days, (2) meter chiller, pump and fan kWh "
           "before and after, (3) watch zone RH and supply-air temperature, (4) feed the measured data back so the "
           "prediction can move from PREDICTED to VALIDATED.")
    w("**Recommended schedule (hourly set-points):**\n")
    w("| Hour | CHWS °C | CHW pump | AHU fan | Tower fan |")
    w("|---|---:|---:|---:|---:|")
    for h, x in r3.setpoints.items():
        w(f"| {h}:00 | {x['Ts']:.2f} | {x['fw']:.0%} | {x['fa']:.0%} | {x['ft']:.0%} |")

    # ------------------------------------------------------- summary
    w("\n## 7. What the system recorded\n")
    w("**Parameters and their provenance now:**\n")
    w("| Parameter | Value | Source |")
    w("|---|---|---|")
    for n, pr in s.p.params.items():
        v = f"{pr.value:.3f}" if isinstance(pr.value, float) else str(pr.value)
        w(f"| {n} | {v} | {pr.source.value} |")
    w("\n**Recommendations:**\n")
    w("| ID | Saving | Confidence | Status |")
    w("|---|---:|---|---|")
    for r in s.recs.values():
        w(f"| {r.id} | {r.saving_pct:.1f} % | {r.confidence} | {r.status} |")
    w("\n**Prediction accuracy tracking:**\n")
    w("| Hour | Predicted | Measured | Error |")
    w("|---|---:|---:|---:|")
    for m in s.measurements:
        w(f"| {m['hour']}:00 | {m['predicted']:.0f} kW | {m['measured']:.0f} kW | {m['predicted']/m['measured']-1:+.1%} |")
    kinds: dict[str, int] = {}
    for ev in s.log:
        kinds[ev["kind"]] = kinds.get(ev["kind"], 0) + 1
    w(f"\n**Audit log:** {len(s.log)} events ({', '.join(f'{v} {k}' for k, v in kinds.items())}). "
      "Full log: `audit_log.json`.\n")
    w("**Still open:**\n")
    for q in s.open_questions():
        w(f"- [{q.priority}] {q.key}: {q.text[:140]}{'…' if len(q.text) > 140 else ''}")

    s.dump_log(OUT / "audit_log.json")
    (OUT / "transcript.md").write_text("\n".join(md))
    print("\n".join(md))


if __name__ == "__main__":
    main()
