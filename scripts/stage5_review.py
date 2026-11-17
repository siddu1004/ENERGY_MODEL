"""Stage 5 - evidence for the critical review.

Four experiments that stress the approach rather than show it off:
  E1  model-truth gap: optimise on the fitted chiller regression, score on the
      TRUE chiller (known, because we generated the synthetic data)
  E2  calibration identifiability: one measured point, two different truths
  E3  robustness: optimised set-points applied to a coil that differs from
      the assumed one
  E4  structural sensitivity: savings vs the assumed fan-law parameter
Writes reports/stage5/experiments.md and calibration.png
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import energy_model.scenarios as sc  # noqa: E402
from energy_model.defaults import ROOM_PROFILES, default_registry  # noqa: E402
from energy_model.hvac import TR  # noqa: E402

OUT = ROOT / "reports" / "stage5"
md: list[str] = []
w = md.append


def true_chiller(Q_kW, Ts, Tc):
    """The generator used to create the synthetic data (no noise)."""
    L = Q_kW / TR
    dts, dtc = Ts - 6, Tc - 29.4
    capft = 1 + 0.030 * dts - 0.010 * dtc
    eirft = 1 - 0.022 * dts + 0.0004 * dts ** 2 + 0.024 * dtc + 0.0003 * dtc ** 2
    plr = L / (250 * capft)
    return 187.5 * capft * eirft * (0.10 + 0.40 * plr + 0.50 * plr ** 2)


def rescore_true(S, res):
    """Re-evaluate a schedule with the true chiller (ECWT re-iterated)."""
    sysm, tot = S["sys"], 0.0
    for h, r in res.items():
        Q, Ts, ft = r["Q_chiller_kW"], r["x"]["Ts"], r["x"]["ft"]
        P = r["P"]["chiller"]
        for _ in range(6):
            ecwt = S["H"][h].wb + sysm.tower.approach(Q + P, ft)
            P = true_chiller(Q, Ts, ecwt)
        tot += r["total_kW"] - r["P"]["chiller"] + P
    return tot


def e1():
    S = sc.build()
    base, opt = sc.baseline(S), sc.optimised(S)
    pb, po = sc.day(base)["total"], sc.day(opt)["total"]
    tb, to = rescore_true(S, base), rescore_true(S, opt)
    ch = S["sys"].chiller
    corners = [(q * 250 * TR, t, c) for q in (0.3, 1.0) for t in (5, 10) for c in (26, 32)]
    inside = [(q * 250 * TR, t, c) for q in (0.6, 0.8) for t in (6, 7, 8) for c in (28, 30)]
    rel = lambda p: abs(float(ch.power(*p)) - true_chiller(*p)) / true_chiller(*p)  # noqa: E731
    w("## E1. Does the saving survive contact with the 'true' chiller?\n")
    w("The synthetic data came from a known generator, so the 'truth' is available. The optimiser used the fitted "
      "regression. Here both schedules are re-scored on the true chiller.\n")
    w("| | Predicted (regression) | 'True' chiller | Gap |")
    w("|---|---:|---:|---:|")
    w(f"| Baseline kWh/day | {pb:,.0f} | {tb:,.0f} | {tb/pb-1:+.1%} |")
    w(f"| Optimised kWh/day | {po:,.0f} | {to:,.0f} | {to/po-1:+.1%} |")
    w(f"| **Saving** | **{1-po/pb:.1%}** | **{1-to/tb:.1%}** | {100*((1-to/tb)-(1-po/pb)):+.1f} pp |")
    w(f"\nRegression error vs truth: ≤ {max(map(rel, inside)):.1%} in the normal operating region, up to "
      f"{max(map(rel, corners)):.1%} at the corners of the data range. **Verdict:** with clean, well-covered data the "
      "regression is good enough for optimisation. Real BMS data is noisier, clustered in a narrow operating band, "
      "and drifts as the chiller ages, so this is a best case.\n")


def e2():
    """Two different truths, each 'measured' at 15:00, model calibrated with one scalar."""
    S0 = sc.build()
    pred0 = sc.baseline(S0)
    hrs = S0["hrs"]
    saved = copy.deepcopy(ROOM_PROFILES)
    truths = {"Truth A: equipment & lighting 35 % lower": dict(profiles=0.65),
              "Truth B: hotter day (T_max 41 °C)": dict(T_out_max=41.0)}
    n = S0["n"]   # same building size everywhere: only the physics input differs

    def loads(reg, scale=1.0, profiles=1.0):
        try:
            for p in ROOM_PROFILES.values():
                for key in ("equip", "light", "equip_fixed_W"):
                    if key in p:
                        p[key] *= profiles
            return {h: r["Q_chiller_kW"] for h, r in
                    sc.baseline(sc.build(reg=reg, load_scale=scale, n_floors=n)).items()}
        finally:
            ROOM_PROFILES.clear()
            ROOM_PROFILES.update(copy.deepcopy(saved))

    def reg_with(T_max):
        reg = default_registry()
        reg.params["T_out_max"].value = T_max
        return reg

    # truth = (internal-gain factor, design-day T_max on the measured day)
    truths = {"Truth A: equipment & lighting 35 % lower": (0.65, 38.0),
              "Truth B: same building, measured on a hotter day (41 °C)": (1.0, 41.0)}
    other_day = 33.0
    results = {}
    for name, (gains, tmax) in truths.items():
        truth = loads(reg_with(tmax), profiles=gains)
        e = pred0[15]
        fixed = e["P"]["fan"] + e["P"]["chw_pump"]
        # the model thinks it is a 38 °C day (the engineer only gave a load reading)
        k = (truth[15] - fixed) / (e["Q_chiller_kW"] - fixed)
        cal = loads(reg_with(38.0), scale=k)
        err = np.array([cal[h] / truth[h] - 1 for h in hrs])
        # predict a DIFFERENT, cooler day with the calibrated model (weather now known correctly)
        t2 = loads(reg_with(other_day), profiles=gains)
        c2 = loads(reg_with(other_day), scale=k)
        e2_day = sum(c2.values()) / sum(t2.values()) - 1
        results[name] = dict(k=k, err=err, truth=truth, cal=cal, other=e2_day)
    w("## E2. Can one measured point calibrate the model?\n")
    w("Two different 'real' situations both produce a 15:00 chiller load that differs from the model. In each "
      "case the model is calibrated on that one reading with a single load multiplier (as in Stage 4). It is then "
      f"checked (a) over the rest of the same day, and (b) on a different, cooler day ({other_day:.0f} °C) where the "
      "weather input is correct.\n")
    w(f"| Truth | Calibration factor | Error at 15:00 | Worst hourly error, same day | Daily error on the {other_day:.0f} °C day |")
    w("|---|---:|---:|---:|---:|")
    for name, r in results.items():
        worst = r["err"][np.argmax(np.abs(r["err"]))]
        w(f"| {name} | {r['k']:.3f} | {r['err'][hrs.index(15)]:+.1%} | {worst:+.1%} | **{r['other']:+.1%}** |")
    w("\n**Verdict:** within the calibration day a one-point scalar looks fine (errors of a few %), which is exactly "
      "why it is dangerous. In Truth B the real cause was *weather*, but the scalar 'learned' that the building "
      "is more heavily loaded. That wrong lesson then carries into every other day as a systematic over-prediction, "
      "and inflates baselines and claimed savings. A correct calibration must attribute error to the right "
      "parameter: measured weather for the same period, many hours across varied days, and separate parameters "
      "(internal gains, envelope UA, infiltration) fitted together by least squares or Bayesian methods. "
      "Acceptance: ASHRAE Guideline 14 (hourly CV(RMSE) ≤ 30 %, NMBE ≤ ±10 %).\n")
    return results, hrs


def e3():
    S = sc.build()
    opt = sc.optimised(S)
    out = {}
    for label, margin in (("Coil 13 % smaller than assumed (margin 1.00)", 1.00),
                          ("Coil 13 % larger than assumed (margin 1.30)", 1.30)):
        St = sc.build(coil_margin=margin)
        applied = {h: St["sys"].evaluate(tuple(opt[h]["x"].values()), St["H"][h]) for h in S["hrs"]}
        short = [max(0.0, -r["g"]["coil"] * 100) for r in applied.values()]
        out[label] = dict(viol=sum(not r["feasible"] for r in applied.values()), short=max(short),
                          sens=max(r["Q_coil_sens_kW"] for r in applied.values()),
                          applied=sc.day(applied)["total"], best=sc.day(sc.optimised(St))["total"])
    w("## E3. What if the coil isn't what we assumed?\n")
    w("The optimised schedule was computed for the assumed coil (15 % margin) and is then applied to a different "
      "'real' coil.\n")
    w("| Real coil | Hours violating constraints | Worst coil shortfall | Energy of our schedule | Best possible on that coil |")
    w("|---|---:|---:|---:|---:|")
    for k, r in out.items():
        w(f"| {k} | {r['viol']} / 12 | {r['short']:.0f} kW ({r['short']/r['sens']:.0%} of sensible duty) | "
          f"{r['applied']:,.0f} kWh | {r['best']:,.0f} kWh |")
    w("\n**Verdict:** the optimum sits *on* the coil-capacity constraint, so a weaker real coil leaves rooms "
      "under-cooled; a stronger one leaves savings on the table. Open-loop set-points from a model are unsafe. "
      "The optimiser should set **targets and limits**, the BMS feedback loops (supply-air and zone temperature) "
      "handle the residual, and comfort constraints need a back-off margin sized from model uncertainty.\n")


def e4():
    out = {}
    original = sc.FAN_C
    try:
        for c in (0.10, 0.25, 0.40):
            sc.FAN_C = c
            S = sc.build()
            b, o = sc.day(sc.baseline(S))["total"], sc.day(sc.optimised(S))["total"]
            out[c] = (b, o, 1 - o / b)
    finally:
        sc.FAN_C = original
    w("## E4. How much does one assumed fan parameter matter?\n")
    w("Fan power law P = P₀·f·(c + (1−c)f²). c is the share of fan pressure that doesn't fall with speed "
      "(duct static-pressure set-point). It is *assumed*.\n")
    w("| c | Baseline kWh/day | Optimised kWh/day | Saving |")
    w("|---:|---:|---:|---:|")
    for c, (b, o, s) in out.items():
        w(f"| {c:.2f}{' (used)' if c == 0.25 else ''} | {b:,.0f} | {o:,.0f} | {s:.1%} |")
    w("\n**Verdict:** one unmeasured parameter moves the headline saving by several points. Fan power vs speed "
      "should come from VFD/BMS trends (kW vs Hz) before any saving is quoted to the client.\n")


def chart(res, hrs):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False})
    fig, ax = plt.subplots(1, 2, figsize=(11, 3.8), dpi=150, sharey=True)
    for a, (name, r) in zip(ax, res.items()):
        a.plot(hrs, [r["truth"][h] for h in hrs], "o-", color="#333", label="'True' building")
        a.plot(hrs, [r["cal"][h] for h in hrs], "s--", color="#c95f5f", label=f"Calibrated model (k = {r['k']:.2f})")
        a.axvline(15, color="#999", ls=":", label="Calibration point (15:00)")
        a.set_title(f"{name}\nerror on a different (33 °C) day: {r['other']:+.1%}", fontsize=9)
        a.set_xlabel("Hour")
        a.legend(frameon=False, fontsize=8)
    ax[0].set_ylabel("Chiller load (kW)")
    fig.suptitle("One-point calibration fits the measured day in both cases, but in B for the wrong reason")
    fig.tight_layout()
    fig.savefig(OUT / "calibration.png")
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    w("# Stage 5: Experiments behind the critical review\n")
    w("All numbers are generated by `scripts/stage5_review.py` against the same engine as Stages 2–4.\n")
    e1()
    res, hrs = e2()
    e3()
    e4()
    chart(res, hrs)
    w("![calibration](calibration.png)\n")
    (OUT / "experiments.md").write_text("\n".join(md))
    print("\n".join(md))


if __name__ == "__main__":
    main()
