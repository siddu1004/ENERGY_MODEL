# Stage 4: Human-in-the-loop demonstration

Scripted engineer ↔ system conversation run against the real engine (`energy_model/session.py`). The *AI layer* line shows which deterministic engine call the engineer's words map to. **All numbers are computed, not written by hand.** Values are predictions on synthetic data.

## 0. Session start: the system briefs the engineer

🤖 **System:** I have analysed the sample building (14 floors assumed) and the 250 TR chiller plant. Baseline (CHWS 6.0 °C, constant-speed pumps and fans): **3,124 kWh/day** on the design day. An optimised hourly schedule predicts **2,336 kWh/day (25.2 % saving)**. Before relying on this, I need your input on the items below. I've only listed items that change the result materially.

**Open questions (priority order):**

- **[HIGH]** The scan covers one 600 m² floor but the chiller is 250 TR. I assumed 14 floors so the building peak is about 90 % of capacity. Every load and saving scales with this number. How many floors does the chiller serve?  
  Options: Confirm · Enter floor count · Chiller also serves other loads
- **[HIGH]** The optimised schedule relies on variable speed for AHU fans, CHW pumps and tower fans. I don't know which have VFDs installed. Approval is blocked until this is confirmed.  
  Options: All have VFDs · Specify which ones · None (constant speed)  
  ⛔ Blocks: approval
- **[MEDIUM]** Building loads are uncalibrated (no measured data). Savings are model-to-model predictions.  
  Options: Provide BMS chiller load / energy data

🤖 **System:** I also checked two uncertain inputs to decide whether they are worth your time (threshold: ask only if daily energy swings ≥ 2 %):

| Assumption | Range tested | Daily energy swing | Asked? |
|---|---|---:|---|
| Wall colour (solar absorptance) | 0.5 – 0.7 | 1.1% | **no**, logged only |
| Design outdoor max (°C) | 36 – 40 | 11.3% | **yes**, added as a MEDIUM question |

## 1. Answering a proactive question: floors served


> 🧑‍🔧 **Engineer:** It's 14 floors. That's correct.
>
> <sub>AI layer → engine call: `answer('floors', 'confirmed', floors_served=14)`</sub>

🤖 **System:** Recorded. `floors_served` = 14, source upgraded **assumed → engineer**. The value is unchanged, so no recalculation is needed.


> 🧑‍🔧 **Engineer:** What if it were only 6 floors?
>
> <sub>AI layer → engine call: `what_if(floors_served=6)  # does not change the session`</sub>

🤖 **System:** With 6 floors the baseline peak chiller load would be 416 kW (47% of capacity) and the saving 48.8 %. I would then raise this:

- **[HIGH]** Peak chiller load is only 47% of capacity with 6 floors. The chiller would run below 50 % most of the time (cycling, poor efficiency). Is the floor count right, or does the chiller serve other loads?

🤖 **System:** Nothing in the session was changed by this what-if.

## 2. Scenario 1: changing an assumption

🤖 **System:** The current model assumes a chilled-water supply temperature of 6.0 °C.


> 🧑‍🔧 **Engineer:** Change it to 7 °C.
>
> <sub>AI layer → engine call: `preview_chws(7.0)  # ambiguity check before changing`</sub>

🤖 **System:** Quick check before I change it. 'CHWS 7 °C' can mean two different things for the hydronic calculation:

| Interpretation | CHWR | ΔT | Flow for full capacity | CHW pump (design) |
|---|---:|---:|---:|---:|
| keep return | 12 °C | 5 K | 151 m³/h | 18.3 kW |
| keep ΔT | 13 °C | 6 K | 126 m³/h | 15.2 kW |

Which one do you mean?


> 🧑‍🔧 **Engineer:** Keep the return at 12 °C.
>
> <sub>AI layer → engine call: `set('baseline_CHWS', 7.0)`</sub>

🤖 **System:** Updated and recalculated the full chain (design point → hourly baseline → optimisation):

**What changed:**

| Quantity | Before | After | Change |
|---|---:|---:|---:|
| design CHW ΔT (K) | 6.00 | 5.00 | -16.7 % |
| design CHW flow (m³/h) | 126.02 | 151.23 | +20.0 % |
| design CHW pump (kW) | 15.23 | 18.27 | +20.0 % |
| baseline chiller kWh/day | 1,824.96 | 1,768.29 | -3.1 % |
| baseline total kWh/day | 3,124.45 | 3,067.78 | -1.8 % |
| predicted saving (%) | 25.22 | 23.84 | -1.4 pp |
| annual saving (INR) | 2,269,472.59 | 2,106,269.09 | -7.2 % |

🤖 **System:** Interpretation: the hourly model sees the chiller's efficiency gain from warmer water (about −3 % chiller energy). The Excel-style design calculation cannot see it because it uses a constant kW/TR. It does show the hydronic penalty: a 5 K ΔT needs 20 % more flow. Savings from optimisation shrink slightly because the new baseline is already better. This change raised a new question:

**New question raised:**

- **[HIGH]** With CHWS 7.0 °C / CHWR 12.0 °C the ΔT is 5.0 K, so delivering full chiller capacity needs 151 m³/h. The pump is rated for ≈126 m³/h (+20%). Above the pump's range, full capacity cannot be delivered.  
  Options: Accept: building peak needs less than full capacity · Keep ΔT 6 K (raise return set-point) · Provide pump curve


> 🧑‍🔧 **Engineer:** Accept. The building peak never needs full chiller capacity.
>
> <sub>AI layer → engine call: `answer('flow_range', 'accept')`</sub>

🤖 **System:** Recorded with your reason in the audit log.

## 3. Scenario 2: questioning an optimisation

🤖 **System:** Increasing chilled-water supply temperature may reduce compressor energy consumption.


> 🧑‍🔧 **Engineer:** Why do you think this is beneficial?
>
> <sub>AI layer → engine call: `explain_chws(hour=15)`</sub>

🤖 **System:** **The thermodynamic reason.** The compressor lifts heat from the evaporating temperature (set by CHWS) to the condensing temperature (set by the condenser water). Warmer chilled water means a smaller lift, so less compressor work per kW of cooling.

- From the fitted chiller model at 15:00: ∂P_chiller/∂CHWS = **-4.84 kW per K** (-3.1% of chiller power per K).

🤖 **System:** **But the system answer is different.** The optimiser chose CHWS = 6.17 °C at 15:00, not higher, because raising it by 1 K has knock-on effects:

| Effect of CHWS +1 K at 15:00 | Value |
|---|---:|
| Coil sensible capacity at same airflow | −31 kW (warmer water → less heat removed) |
| AHU fan speed needed to still meet the load | 72% → 80% |
| Chiller power | -2.7 kW |
| Fan power | +7.2 kW |
| Other (pump, tower) | +0.0 kW |
| **Net** | **+4.5 kW** |

Binding constraints at the optimum: **coil, supply_air**.

🤖 **System:** So raising CHWS helps the chiller but not the system at this hour. Fan power rises faster (roughly with speed³) than the compressor saves. **This conclusion depends on assumed coil and fan data.** With a larger coil or more efficient fans the optimum moves to warmer water. Real coil data would settle it.

## 4. Scenario 3: human correction with measured data

🤖 **System:** The estimated chiller load at 15:00 on the design day is 814 kW.


> 🧑‍🔧 **Engineer:** That's incorrect. The BMS shows a measured load of 690 kW at 15:00.
>
> <sub>AI layer → engine call: `measure_chiller_load(hour=15, kW=690, note='BMS trend')`</sub>

🤖 **System:** Replaced. The model over-predicted by **+18.0%**. What I changed and what I didn't:

- ✅ Calibrated the **building-load multiplier** 1.00 → **0.832** (source: measured). Only the uncertain building load is scaled.
- ✅ Fan heat and pump heat in the measured figure are physics-known and were **not** scaled.
- ❌ No thermodynamic equations were changed. Calibration adjusts uncertain *parameters*, never physical laws.

**What changed:**

| Quantity | Before | After | Change |
|---|---:|---:|---:|
| baseline peak chiller load (kW) | 855.32 | 724.33 | -15.3 % |
| baseline chiller kWh/day | 1,768.29 | 1,413.94 | -20.0 % |
| baseline total kWh/day | 3,067.78 | 2,713.42 | -11.6 % |
| optimised total kWh/day | 2,336.43 | 1,809.28 | -22.6 % |
| predicted saving (%) | 23.84 | 33.32 | +9.5 pp |
| annual saving (INR) | 2,106,269.09 | 2,603,929.74 | +23.6 % |
| optimised CHWS range (°C) | 5.76–7.11 | 6.47–8.49 |  |

🤖 **System:** **How the recommendation changed:** with less load the coil has spare capacity, so warmer water now pays off. Optimal CHWS moved from 5.8–7.1 °C to **6.5–8.5 °C**. This is the same trade-off as in Scenario 2, now landing on a different point.

**Follow-up question raised:**

- **[MEDIUM]** Calibrated on 1 point(s) only. One hour cannot separate load error from schedule or weather error. Can you share at least a week of hourly BMS chiller data?  
  Options: Upload BMS trend · Accept single-point calibration


> 🧑‍🔧 **Engineer:** Also, the flow meter shows 25 kg/s with a 5 K ΔT at that time.
>
> <sub>AI layer → engine call: `check_measurement_consistency(flow_kg_s=25, dT=5, load_kW=690)`</sub>

**Conflict detected:**

- **[CONFLICT]** Measurements disagree: ṁ·cp·ΔT = 25 × 4.186 × 5 = 523 kW, but the reported load is 690 kW (-24%). At least one is wrong (flow-meter calibration, sensor placement, or a different time window). I will not use any of them until resolved.  
  Options: Flow reading is wrong · ΔT sensors are wrong · Load figure is wrong · Check the time window


> 🧑‍🔧 **Engineer:** The flow meter is known to under-read. Ignore it.
>
> <sub>AI layer → engine call: `answer('energy_balance', 'flow meter wrong')`</sub>

🤖 **System:** Recorded. The flow reading is excluded; the 690 kW load stays as the calibration point. I've logged a maintenance note that the flow meter needs recalibration.

## 5. Proactive safety check


> 🧑‍🔧 **Engineer:** Set the chilled-water supply to 3 °C for more dehumidification.
>
> <sub>AI layer → engine call: `set('baseline_CHWS', 3.0)`</sub>

**Rejected:**

- **[SAFETY]** baseline_CHWS = 3.0 rejected: outside safe range 5.0–12.0 (below 5 °C risks evaporator freezing / outside chiller data; above 12 °C the coil cannot dehumidify). Nothing was changed.  
  Options: Use a value within 5.0–12.0 · Explain the special case (needs supervisor override)

🤖 **System:** I did not apply it. If you need more dehumidification I can instead tighten the RH limit and let the optimiser find a safe operating point.


> 🧑‍🔧 **Engineer:** OK, leave it at 7 °C.
>
> <sub>AI layer → engine call: `answer('unsafe_baseline_CHWS', 'withdrawn')`</sub>

## 6. Scenario 4: recommendation, calculations, modification, approval

🤖 **System:** I found an operating schedule that reduces estimated energy by **33.3 %** (2,713 → 1,809 kWh/day, ≈ INR 2,603,930/yr if every day were the design day). Confidence: **MEDIUM** · Status: **PREDICTED (not validated)** · Recommendation **R1**.


> 🧑‍🔧 **Engineer:** Show me the calculations.
>
> <sub>AI layer → engine call: `show_calculation(hour=15)`</sub>

🤖 **System:** Hour 15:00, baseline vs recommended. Every line is one model equation:

| Step | Equation | Baseline | Recommended |
|---|---|---:|---:|
| Set-points | `CHWS / pump / fan / tower` | 7.00 °C / 100% / 100% / 100% | 6.80 °C / 62% / 60% / 55% |
| AHU fan power | `P₀·f·(c+(1−c)f²)` | 59.6 kW | 18.3 kW |
| Mixed-air temp | `T_room + Q_vent/(ṁ_a c_p)` | 25.00 °C | 25.68 °C |
| Coil sensible duty | `Q_room + Q_vent + fan heat` | 548 kW | 507 kW |
| Coil capacity | `ε·C_min·(T_mixed − CHWS)` | 771 kW | 507 kW |
| Supply-air temp (≥ 12 °C) | `T_room − Q_room/(ṁ_a c_p)` | 16.9 °C | 12.0 °C |
| Dew point needed vs CHWS + 4 K | `RH ≤ limit` | 13.8 vs 11.0 °C | 13.5 vs 10.8 °C |
| CHW pump power | `P₀·f·(c+(1−c)f²)` | 15.2 kW | 4.8 kW |
| Chiller load | `coil total + pump heat` | 690 kW | 638 kW |
| Evaporator ΔT (≤ 9 K) | `Q/(ṁ_w c_p)` | 4.7 K | 7.0 K |
| Heat rejected | `Q_chiller + P_chiller` | 819 kW | 759 kW |
| Condenser water ECWT | `T_wb + approach(Q_rej, f_t)` | 28.58 °C | 29.47 °C |
| Chiller power | `regression P(L, CHWS, ECWT)` | 128.6 kW (COP 5.37) | 120.4 kW (COP 5.30) |
| Tower fan power | `P₀·f_t³` | 15.0 kW | 2.5 kW |
| CW pump power | `constant speed` | 18.5 kW | 18.5 kW |
| **Total plant power** | `Σ` | **236.9 kW** | **164.5 kW** |

Saving at this hour: **72.4 kW (30.6%)**. Wet-bulb 25.9 °C. Coil UA 92 kW/K (assumed margin).


> 🧑‍🔧 **Engineer:** The AHU fans can't go below 75 % airflow. That's our minimum ventilation setting.
>
> <sub>AI layer → engine call: `set('fan_min', 0.75)`</sub>

**What changed:**

| Quantity | Before | After | Change |
|---|---:|---:|---:|
| optimised total kWh/day | 1,809.28 | 1,923.68 | +6.3 % |
| predicted saving (%) | 33.32 | 29.10 | -4.2 pp |
| annual saving (INR) | 2,603,929.74 | 2,274,453.29 | -12.7 % |
| optimised CHWS range (°C) | 6.47–8.49 | 7.23–9.66 |  |

🤖 **System:** Re-optimised with the new limit. With less freedom on airflow, the optimiser now saves energy by running warmer chilled water, which affects dehumidification:

**Trade-off raised before I propose anything:**

- **[MEDIUM]** To save energy the optimiser raises CHWS until the humidity limit binds: dew-point margin for RH ≤ 55% is only 0.00 K in some hours. If the latent load is higher than modelled, indoor RH would exceed the limit. Trade-off: energy vs humidity risk.  
  Options: Accept · Tighten RH limit (costs energy) · Provide measured indoor RH


> 🧑‍🔧 **Engineer:** Comfort comes first. Use 50 % RH as the limit.
>
> <sub>AI layer → engine call: `answer('humidity_margin', 'tighten', RH_max=0.50)`</sub>

**What changed:**

| Quantity | Before | After | Change |
|---|---:|---:|---:|
| optimised total kWh/day | 1,923.68 | 1,949.31 | +1.3 % |
| predicted saving (%) | 29.10 | 28.16 | -0.9 pp |
| annual saving (INR) | 2,274,453.29 | 2,200,640.85 | -3.2 % |
| optimised CHWS range (°C) | 7.23–9.66 | 7.23–8.12 |  |

🤖 **System:** Recommendation **R2**: saving 28.2 % (5.2 pp less than R1, which is now SUPERSEDED by R2). That difference is the energy cost of your ventilation and comfort limits.


> 🧑‍🔧 **Engineer:** Approve R2.
>
> <sub>AI layer → engine call: `decide('R2', 'approve')`</sub>

🤖 **System:** I can't mark it approved yet. This open question blocks approval:

- **[HIGH]** The optimised schedule relies on variable speed for AHU fans, CHW pumps and tower fans. I don't know which have VFDs installed. Approval is blocked until this is confirmed.


> 🧑‍🔧 **Engineer:** The AHU fans and CHW pumps have VFDs. The cooling-tower fans are constant speed.
>
> <sub>AI layer → engine call: `answer('vfd', ..., vfd_ahu=True, vfd_chw_pump=True, vfd_tower=False)`</sub>

**Recalculated with tower fans locked at 100 %:**

| Quantity | Before | After | Change |
|---|---:|---:|---:|
| optimised total kWh/day | 1,949.31 | 2,061.38 | +5.7 % |
| predicted saving (%) | 28.16 | 24.03 | -4.1 pp |
| annual saving (INR) | 2,200,640.85 | 1,877,875.37 | -14.7 % |
| optimised CHWS range (°C) | 7.23–8.12 | 7.22–8.12 |  |

🤖 **System:** Updated recommendation **R3**: saving **24.0 %** (2,713 → 2,061 kWh/day). Confidence MEDIUM.


> 🧑‍🔧 **Engineer:** Approve R3.
>
> <sub>AI layer → engine call: `decide('R3', 'approve')`</sub>

🤖 **System:** R3 status: **APPROVED FOR SUPERVISED TRIAL**.

⚠ **No equipment setting has been changed.** This system has no write access to the BMS. Next steps for the operator: (1) trial the schedule for 2 weeks on comparable days, (2) meter chiller, pump and fan kWh before and after, (3) watch zone RH and supply-air temperature, (4) feed the measured data back so the prediction can move from PREDICTED to VALIDATED.

**Recommended schedule (hourly set-points):**

| Hour | CHWS °C | CHW pump | AHU fan | Tower fan |
|---|---:|---:|---:|---:|
| 8:00 | 7.22 | 65% | 75% | 100% |
| 9:00 | 8.12 | 50% | 75% | 100% |
| 10:00 | 8.12 | 50% | 75% | 100% |
| 11:00 | 8.12 | 50% | 75% | 100% |
| 12:00 | 8.12 | 50% | 75% | 100% |
| 13:00 | 8.12 | 50% | 75% | 100% |
| 14:00 | 8.12 | 52% | 75% | 100% |
| 15:00 | 8.12 | 52% | 75% | 100% |
| 16:00 | 8.12 | 50% | 75% | 100% |
| 17:00 | 8.12 | 50% | 75% | 100% |
| 18:00 | 8.12 | 50% | 75% | 100% |
| 19:00 | 8.12 | 50% | 75% | 100% |

## 7. What the system recorded

**Parameters and their provenance now:**

| Parameter | Value | Source |
|---|---|---|
| baseline_CHWS | 7.000 | engineer |
| baseline_CHWR | 12.000 | hypothetical |
| floors_served | 14 | engineer |
| load_calibration | 0.832 | measured |
| coil_margin | 1.150 | assumed |
| RH_max | 0.500 | engineer |
| T_sa_min | 12.000 | assumed |
| fan_min | 0.750 | engineer |
| vfd_ahu | True | engineer |
| vfd_chw_pump | True | engineer |
| vfd_tower | False | engineer |
| tariff | 8.000 | assumed |

**Recommendations:**

| ID | Saving | Confidence | Status |
|---|---:|---|---|
| R1 | 33.3 % | MEDIUM | SUPERSEDED by R2 |
| R2 | 28.2 % | MEDIUM | SUPERSEDED by R3 |
| R3 | 24.0 % | MEDIUM | APPROVED FOR SUPERVISED TRIAL |

**Prediction accuracy tracking:**

| Hour | Predicted | Measured | Error |
|---|---:|---:|---:|
| 15:00 | 814 kW | 690 kW | +18.0% |

**Audit log:** 38 events (6 recompute, 9 question, 2 assumption_assessed, 6 answer, 7 change, 1 measurement, 1 consistency_check, 1 rejected_change, 3 recommendation, 1 approval_blocked, 1 decision). Full log: `audit_log.json`.

**Still open:**

- [MEDIUM] assume_T_out_max: 'T_out_max' is assumed (38.0). Over 36.0–40.0 daily energy swings 11.3%. Can you confirm it?
- [MEDIUM] more_data: Calibrated on 1 point(s) only. One hour cannot separate load error from schedule or weather error. Can you share at least a week of hourly B…