# Stage 5: Critical review. Does the approach work?

Evidence: Stages 2–4 plus four stress experiments in [`experiments.md`](experiments.md) (E1–E4).
Everything below refers to the **synthetic** building and plant. Nothing has been validated against a real one.

## Bottom line

| Question | Answer |
|---|---|
| Is the mathematics sound? | **Yes.** Equations are physically based, units are consistent, the code reproduces the Excel to 10⁻¹⁵, the optimiser is verified against brute force, and 18 regression tests pass. |
| Is the *workflow* right? | **Yes.** Geometry → loads → plant → constrained system optimisation → human review is the correct structure, and Stage 4 shows engineer control works. |
| Are the *numbers* trustworthy? | **No, not yet.** The 25 % saving is a model-to-model prediction. One assumed fan parameter moves it ±2 pp (E4), coil size ±4–5 pp, and a wrongly attributed calibration biases every other day by 7.5 % (E2). |
| Could it run a real plant today? | **No.** Set-points computed open-loop sit exactly on comfort constraints; if the coil is 13 % weaker than assumed, rooms are under-cooled in 12 of 12 hours (E3). |
| Is it worth continuing? | **Yes.** The weak points are *inputs and calibration*, not the architecture. All of them can be fixed with real data that plants normally already log. |

---

## 1. What works mathematically

| Element | Evidence |
|---|---|
| Unit-consistent hydronic and refrigeration equations (Q = ṁ·cp·ΔT, kW/TR, COP, E = P·t, Q_rej = Q + P) | Python ≡ Excel workbook on all 31 outputs (rel. error 4×10⁻¹⁵) |
| Geometry extraction, incl. inferring exterior walls from shared-wall geometry | Exact match to ground truth (areas, windows, exterior flags) |
| Solar geometry and design-day weather | Symmetry and solar-noon tests pass; magnitudes plausible for 17 °N |
| Dynamic RC thermal model | Periodic, holds set-point, shows the expected night heat-soak and 8:00 pull-down (+8 % daily load vs steady-state) |
| Regression fitting with hold-out testing | R² 0.998, test RMSE 1.9 kW ≈ train RMSE 1.6 kW (no overfitting); **E1:** saving on the *true* chiller is within 0.1 pp of the prediction |
| Calculus on the objective | dE/dTs = 0 at 6.22 °C (cubic fit 6.34 °C), d²E/dTs² = +1.79 > 0 |
| Recognising when calculus is NOT enough | With real constraints the minimum sits on a kink (KKT), so the engine uses SLSQP, checked against a 72,765-point grid |
| System-level optimisation | Found the counter-intuitive result: raising CHWS helps the chiller but hurts the system (+4.5 kW net at 15:00) because fans pay more than the compressor saves |

## 2. What is physically realistic, and what isn't

**Realistic:** energy balances; fan and pump heat entering the loads; condenser temperature following wet-bulb plus tower approach; the trade-off between chilled-water temperature, coil capacity, airflow and dehumidification; affinity-law savings from VFDs; magnitudes (50 kW per floor, COP ≈ 5, plant 0.95–1.2 kW/TR all-in).

**Not realistic, or optimistic:**

| Issue | Why it matters |
|---|---|
| One lumped chiller, one lumped AHU, one zone per floor | A 250 TR plant usually has 2–3 chillers. **Chiller staging/sequencing is often the largest saving** and is missing entirely. Lumping AHUs hides zones that are starved while others are over-cooled. |
| Dry-coil ε-NTU plus a fixed "ADP + 4 K" humidity rule | Real coils are wet; latent capacity depends on coil depth, face velocity and water temperature. The humidity constraint is the one most likely to be wrong, and it is a comfort/mould constraint. |
| Instantaneous hourly set-points, no control dynamics | Real loops have lags, minimum run times, and stability limits on how fast CHWS and pump speed can be reset. |
| Pump/fan law with a fixed pressure fraction *c* | Real VAV systems with static-pressure reset behave differently; **E4: c 0.10 → 0.40 moves the saving 27.0 % → 23.5 %.** |
| Condenser water pump at constant flow, single tower cell | Excludes real optimisation levers (CW flow, number of cells running). |
| Same design day × 360 for "annual" figures | **Upper bound.** Real annual cooling load is often 40–60 % of design-day × days. Savings percentages also change at part load. |
| Interior loads from room *names* | Real scans carry no office/server labels. |

## 3. Assumptions that are too simplistic, ranked by impact on the answer

| Rank | Assumption | Measured impact | Fix |
|---|---|---|---|
| 1 | Floors served / whole-building size | Scales everything; 6 vs 14 floors turns a 90 %-loaded chiller into a 47 % one | Engineer input / as-built drawings |
| 2 | Floor position (roof) and design climate | Top floor +31 % peak; T_max ±2 K → ±11 % daily energy | Floor plan; site weather file (ISHRAE/TMY) |
| 3 | Coil size/performance | Saving ±4–5 pp; **comfort violated in every hour if 13 % weaker (E3)** | AHU coil schedules / selection sheets |
| 4 | Fan & pump part-load behaviour | Saving ±2 pp (E4) | VFD kW-vs-Hz trends from BMS |
| 5 | Glazing / wall U-values, SHGC | −8 to −9 % load for double glazing / insulation | Construction details, or calibrate |
| 6 | Single-scalar calibration | Same day looks fine; **+7.5 % bias on other days if the error is misattributed (E2)** | Multi-parameter calibration over weeks |
| 7 | Chiller curve from tabulated data | Small (E1) **only because the data are clean and well spread** | Manufacturer selection data + BMS trend, refit periodically |
| — | Wall colour, infiltration, minor schedule details | ≤ 1–4 % | Leave assumed; don't bother the engineer |

## 4. Additional engineering models needed

1. **Multi-chiller plant with sequencing/staging logic** (and primary/secondary or variable-primary pumping topology).
2. **Wet-coil model** (e.g. Braun/ASHRAE enthalpy-based ε-NTU) with real latent capacity and supply-air dew point.
3. **Cooling tower model** (Merkel / manufacturer curves) with multiple cells and CW flow as a decision variable.
4. **Zone-level model**: multi-zone RC or EnergyPlus/Modelica co-simulation, with per-zone AHU/VAV boxes and comfort (temperature, RH, ideally PMV).
5. **Annual simulation** with a real hourly weather file and calendar schedules, instead of design day × 360.
6. **Control-aware optimisation**: rolling horizon / model-predictive control with rate limits, minimum run times, and constraint back-off sized from model uncertainty.
7. **Uncertainty propagation**: Monte Carlo or Bayesian posterior over uncertain inputs, so every saving is reported as a range (e.g. P10–P90), not a point.
8. **Fault/drift detection**: residual monitoring (predicted vs measured) to flag sensor faults, fouling, and chiller degradation.

## 5. What cannot be inferred from USDZ geometry

| Available from USDZ | NOT available (must come from people, drawings or data) |
|---|---|
| Room floor areas, heights, volumes | Wall/roof/floor construction, insulation, U-values, thermal mass |
| Wall areas, window and door sizes and positions | Glazing type, SHGC, frames, shading devices |
| Which walls are shared (→ exterior inferred, needs checking) | Whether an "exterior" wall faces outside or an unscanned space |
| Furniture objects (ignored for envelope) | True north / orientation (unless captured with heading) |
| | Floor position (roof/ground), number of floors, other buildings served |
| | Occupancy, schedules, equipment loads, room function |
| | Infiltration/airtightness, ventilation rates |
| | Every HVAC fact: AHUs, coils, ducts, chillers, pumps, VFDs, controls |
| | Weather/climate and operating history |

The scan delivers **the A in U·A·ΔT** reliably. It delivers **none of U, ΔT, SHGC, or the HVAC system.** Treat the USDZ as a geometry accelerator, not an energy model.

## 6. What must be improved before real-world deployment (priority order)

| # | Improvement | Why |
|---|---|---|
| 1 | **Connect to real data:** BMS trends (≥ 4 weeks, hourly: chiller kW, CHW flow/temps, pump/fan kW and speed, outdoor temperature/RH) plus utility meters | Without it every saving is a prediction; calibration is not identifiable (E2) |
| 2 | **Validate against the client's Excel sheets and measured operation**, with acceptance criteria (ASHRAE Guideline 14: hourly CV(RMSE) ≤ 30 %, NMBE ≤ ±10 %) | Turns PREDICTED into VALIDATED |
| 3 | **Replace assumed equipment models with real ones**: chiller selection data, coil schedules, pump curves, VFD kW-vs-Hz | E3/E4: these drive both the saving and comfort safety |
| 4 | **Multi-chiller plant model + sequencing** | Probably the largest real saving lever, currently absent |
| 5 | **Supervisory-only control with back-off margins** (targets and limits to the BMS, never direct actuation; human approval; automatic rollback on comfort alarms) | E3: open-loop optimum on a constraint is unsafe |
| 6 | **Uncertainty ranges on every reported saving** | Stops point estimates being read as promises |
| 7 | **Annual simulation with real weather** | Design-day × 360 overstates annual kWh and cost |
| 8 | **Measurement & verification plan** (IPMVP Option B/C) for any trial | The only way to claim validated savings |
| 9 | **Real-scan adapter** (Apple RoomPlan USDZ hierarchy, multi-floor merge, orientation capture) | Current parser targets the synthetic layout |
| 10 | **Engineering hygiene**: unit library (e.g. pint), versioned model/parameter sets, reproducible runs, role-based approvals | Auditability for a client-facing tool |

## 7. Self-critique: problems we found in our own work

| Found | What happened | Status |
|---|---|---|
| Regression physics check fails at a corner (∂P/∂CHWS > 0 at 30 % load, CHWS 10 °C) | Polynomial artefact; the true slope is negative | Documented; real fix is a physics-structured (DOE-2-form) fit |
| Stage 2 vs Stage 3 baseline differ by 5 % | Stage 3 adds fan/pump heat to the chiller load | Reconciled in the Stage 3 report |
| Calculus demo initially degenerate (minimum on a bound, NaNs) | Pump speed held too low, so the coil was infeasible at high CHWS | Fixed by holding the pump at 100 %; documented |
| Stage 4: answered questions were re-asked; "not worth asking" example was in fact worth asking | Logic bug; infiltration swing was 4.4 %, not < 2 % | Fixed; uses wall colour (1.1 %) instead |
| Stage 5 E2: first run showed almost no calibration effect | `build()` silently re-derived the floor count from the modified building | Fixed by pinning floors; result changed materially |

The last item is a warning for the product itself: **hidden coupling between "assumed" parameters can silently change answers.** The production system needs explicit dependency tracking: when an input changes, it should show which derived assumptions moved too.

## 8. Verdict

The approach **works as an engineering decision-support method**. The physics chain, the system-level optimisation, and the human-in-the-loop controls are sound and demonstrably useful. They already produced one non-obvious, explainable insight (don't simply raise CHWS; slow the fans and pumps instead).

It is **not yet a predictive or control tool**. Its numbers are only as good as the coil, fan, plant-configuration and calibration data behind them, and none of those exist yet. The next step should be to **obtain one real building's BMS trends, equipment schedules and the client's Excel sheets**, then repeat Stages 2–4 against measured data before any saving is presented to the client.
