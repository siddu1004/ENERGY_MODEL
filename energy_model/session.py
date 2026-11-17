"""Engineering session: the deterministic core that an AI assistant drives.

The AI layer (LLM) interprets the engineer's words and calls these methods;
every number it reports comes from here. The session:

  - holds engineer-facing parameters with provenance (Source)
  - validates changes BEFORE applying them (safety bounds)
  - recalculates the whole chain after any change and reports the diff
  - checks results for conflicts / out-of-range values and raises
    prioritised questions (and deliberately suppresses low-impact ones)
  - explains results from the model itself (derivatives, binding constraints)
  - manages recommendations: proposed -> modified / approved / rejected
  - keeps an append-only audit log of every change, measurement and decision

It NEVER writes to equipment. Approval only marks a recommendation as
ready for an authorised operator to trial.
"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass, field

from . import plant
from .defaults import default_registry
from .optimize import Limits
from .provenance import Registry, Source
from .scenarios import PARTS, XLSX, baseline, build, day, optimised

PRIORITY = {"SAFETY": 0, "CONFLICT": 1, "HIGH": 2, "MEDIUM": 3, "LOW": 4}
ASK_THRESHOLD = 0.02     # assumptions changing daily energy < 2 % are logged, not asked

# hard limits checked before any change is accepted
SAFE_BOUNDS = {
    "baseline_CHWS": (5.0, 12.0, "below 5 °C risks evaporator freezing / outside chiller data; "
                                 "above 12 °C the coil cannot dehumidify"),
    "baseline_CHWR": (8.0, 18.0, "outside normal chilled-water return range"),
    "T_sa_min": (10.0, 16.0, "supply air below 10 °C causes draughts / diffuser condensation"),
    "RH_max": (0.40, 0.65, "above 65 % RH risks mould; below 40 % is unnecessary dehumidification"),
    "fan_min": (0.3, 1.0, "AHU minimum airflow must cover ventilation"),
    "floors_served": (1, 60, "implausible floor count"),
}


@dataclass
class Question:
    key: str
    priority: str
    text: str
    options: list[str]
    blocking: str = ""          # what it blocks (e.g. "approval")
    status: str = "open"
    answer: str = ""


@dataclass
class Recommendation:
    id: str
    summary: str
    daily_kWh_baseline: float
    daily_kWh_optimised: float
    saving_pct: float
    annual_saving_cost: float
    setpoints: dict
    binding: list[str]
    assumptions: list[str]
    confidence: str
    status: str = "PROPOSED"
    validation: str = "PREDICTED (not validated)"
    history: list[str] = field(default_factory=list)


class Session:
    def __init__(self):
        p = Registry()
        H, A, U = "hypothetical", "assumed", "unknown"
        p.set("baseline_CHWS", 6.0, "°C", H, "Current chilled-water supply set-point")
        p.set("baseline_CHWR", 12.0, "°C", H, "Design chilled-water return")
        p.set("floors_served", None, "floors", U, "Not in scan; model back-calculates")
        p.set("load_calibration", 1.0, "-", A, "Multiplier on modelled building load; 1.0 = uncalibrated")
        p.set("coil_margin", 1.15, "-", A, "Coil capacity margin over predicted peak")
        p.set("RH_max", 0.55, "-", A, "Max indoor RH")
        p.set("T_sa_min", 12.0, "°C", A, "Min supply-air temperature")
        p.set("fan_min", 0.5, "-", A, "Min AHU airflow fraction")
        p.set("vfd_ahu", None, "-", U, "AHU fans on VFD?")
        p.set("vfd_chw_pump", None, "-", U, "CHW pumps on VFD?")
        p.set("vfd_tower", None, "-", U, "Tower fans on VFD?")
        p.set("tariff", 8.0, "INR/kWh", A, "Electricity tariff")
        self.p = p
        self.reg = default_registry()
        self.log: list[dict] = []
        self.questions: dict[str, Question] = {}
        self.recs: dict[str, Recommendation] = {}
        self.measurements: list[dict] = []
        self.summary: dict = {}
        self._seq = 0
        self.recompute(reason="initial run")

    # ------------------------------------------------------------ helpers
    def _event(self, kind, **data):
        self._seq += 1
        self.log.append(dict(seq=self._seq, kind=kind, **data))

    def _limits(self):
        p = self.p
        # without a VFD the device runs at full speed: lock its bounds to 1.0
        fa = (p["fan_min"], 1.0) if p["vfd_ahu"] is not False else (1.0, 1.0)
        fw = (0.5, 1.0) if p["vfd_chw_pump"] is not False else (1.0, 1.0)
        ft = (0.3, 1.0) if p["vfd_tower"] is not False else (1.0, 1.0)
        return Limits(fa=fa, fw=fw, ft=ft, T_sa_min=p["T_sa_min"], RH_max=p["RH_max"])

    def _excel_design(self):
        pin = plant.read_excel_inputs(XLSX)
        d = {k: pin[k] for k in pin.params}
        d["CHWS_C"], d["CHWR_C"] = self.p["baseline_CHWS"], self.p["baseline_CHWR"]
        return plant.design_point(d), plant.design_point({k: pin[k] for k in pin.params})

    def ask(self, key, priority, text, options, blocking=""):
        q = self.questions.get(key)
        # don't nag: re-ask an answered question only if the situation changed (text has new numbers)
        if q is not None and (q.status == "open" or q.text == text):
            return
        self.questions[key] = Question(key, priority, text, options, blocking)
        self._event("question", key=key, priority=priority, text=text)

    def open_questions(self, min_priority="LOW"):
        lim = PRIORITY[min_priority]
        return sorted((q for q in self.questions.values() if q.status == "open" and PRIORITY[q.priority] <= lim),
                      key=lambda q: PRIORITY[q.priority])

    # ---------------------------------------------------------- recompute
    def recompute(self, reason=""):
        p = self.p
        self.S = build(reg=self.reg, lim=self._limits(), coil_margin=p["coil_margin"],
                       load_scale=p["load_calibration"], n_floors=p["floors_served"])
        if p["floors_served"] is None:
            p.set("floors_served", self.S["n"], "floors", "assumed",
                  "Back-calculated: building peak ≈ 90 % of chiller capacity")
        self.base = baseline(self.S, Ts=p["baseline_CHWS"])
        self.opt = optimised(self.S)
        eb, eo = day(self.base), day(self.opt)
        dx, d0 = self._excel_design()
        days = 360
        new = {
            "design CHW ΔT (K)": dx["CHW_dT"],
            "design CHW flow (m³/h)": dx["CHW_m3_h"],
            "design CHW pump (kW)": dx["CHW_pump_kW"],
            "baseline peak chiller load (kW)": max(r["Q_chiller_kW"] for r in self.base.values()),
            "baseline chiller kWh/day": eb["chiller"],
            "baseline total kWh/day": eb["total"],
            "optimised total kWh/day": eo["total"],
            "predicted saving (%)": 100 * (1 - eo["total"] / eb["total"]),
            "annual saving (INR)": (eb["total"] - eo["total"]) * days * p["tariff"],
            "optimised CHWS range (°C)": (min(r["x"]["Ts"] for r in self.opt.values()),
                                          max(r["x"]["Ts"] for r in self.opt.values())),
        }
        old, self.summary = self.summary, new
        self._design_ref = d0
        self._event("recompute", reason=reason)
        self._validate()
        return self._diff(old, new)

    @staticmethod
    def _diff(old, new):
        rows = []
        for k, v in new.items():
            o = old.get(k)
            if o is None:
                continue
            if isinstance(v, tuple):
                if any(abs(a - b) > 1e-6 for a, b in zip(o, v)):
                    rows.append((k, f"{o[0]:.2f}–{o[1]:.2f}", f"{v[0]:.2f}–{v[1]:.2f}", ""))
            elif abs(v - o) > 1e-6 * max(1, abs(o)):
                chg = f"{v - o:+.1f} pp" if "(%)" in k else (f"{(v/o-1)*100:+.1f} %" if o else "")
                rows.append((k, f"{o:,.2f}", f"{v:,.2f}", chg))
        return rows

    # ---------------------------------------------------------- validators
    def _validate(self):
        p, s = self.p, self.summary
        if p.params["floors_served"].source == Source.ASSUMED:
            self.ask("floors", "HIGH",
                     f"The scan covers one 600 m² floor but the chiller is 250 TR. I assumed {p['floors_served']} "
                     "floors so the building peak is about 90 % of capacity. Every load and saving scales with "
                     "this number. How many floors does the chiller serve?",
                     ["Confirm", "Enter floor count", "Chiller also serves other loads"])
        pump_design = self._design_ref["CHW_m3_h"]
        if s["design CHW flow (m³/h)"] > 1.10 * pump_design:
            self.ask("flow_range", "HIGH",
                     f"With CHWS {p['baseline_CHWS']} °C / CHWR {p['baseline_CHWR']} °C the ΔT is "
                     f"{s['design CHW ΔT (K)']:.1f} K, so delivering full chiller capacity needs "
                     f"{s['design CHW flow (m³/h)']:.0f} m³/h. The pump is rated for ≈{pump_design:.0f} m³/h "
                     f"(+{s['design CHW flow (m³/h)']/pump_design-1:.0%}). Above the pump's range, full "
                     f"capacity cannot be delivered.",
                     ["Accept: building peak needs less than full capacity",
                      "Keep ΔT 6 K (raise return set-point)", "Provide pump curve"])
        peak_plr = s["baseline peak chiller load (kW)"] / self.S["design"]["Q_kW"]
        if peak_plr < 0.5:
            self.ask("oversized", "HIGH",
                     f"Peak chiller load is only {peak_plr:.0%} of capacity with {p['floors_served']} floors. "
                     "The chiller would run below 50 % most of the time (cycling, poor efficiency). "
                     "Is the floor count right, or does the chiller serve other loads?",
                     ["Correct floors served", "Chiller serves other buildings", "Accept"])
        if any(v is None for v in (p["vfd_ahu"], p["vfd_chw_pump"], p["vfd_tower"])):
            self.ask("vfd", "HIGH",
                     "The optimised schedule relies on variable speed for AHU fans, CHW pumps and tower fans. "
                     "I don't know which have VFDs installed. Approval is blocked until this is confirmed.",
                     ["All have VFDs", "Specify which ones", "None (constant speed)"], blocking="approval")
        hum = min(r["g"]["humidity"] for r in self.opt.values())
        if hum < 0.5 and p.params["RH_max"].source != Source.ENGINEER:   # engineer already decided
            self.ask("humidity_margin", "MEDIUM",
                     f"To save energy the optimiser raises CHWS until the humidity limit binds: dew-point margin "
                     f"for RH ≤ {p['RH_max']:.0%} is only {max(hum, 0):.2f} K in some hours. If the latent load is "
                     "higher than modelled, indoor RH would exceed the limit. Trade-off: energy vs humidity risk.",
                     ["Accept", "Tighten RH limit (costs energy)", "Provide measured indoor RH"])
        if p.params["load_calibration"].source == Source.ASSUMED:
            self.ask("calibration", "MEDIUM",
                     "Building loads are uncalibrated (no measured data). Savings are model-to-model predictions.",
                     ["Provide BMS chiller load / energy data"])

    def assess_assumption(self, name, low, high):
        """Impact of an uncertain building-model assumption on daily baseline energy.
        Asks only if the swing is >= ASK_THRESHOLD; otherwise logs and stays quiet."""
        res = []
        for v in (low, high):
            reg = copy.deepcopy(self.reg)
            reg.params[name].value = v
            S = build(reg=reg, lim=self._limits(), coil_margin=self.p["coil_margin"],
                      load_scale=self.p["load_calibration"], n_floors=self.p["floors_served"])
            res.append(day(baseline(S, Ts=self.p["baseline_CHWS"]))["total"])
        swing = (max(res) - min(res)) / self.summary["baseline total kWh/day"]
        asked = swing >= ASK_THRESHOLD
        self._event("assumption_assessed", name=name, range=[low, high], swing=swing, asked=asked)
        if asked:
            self.ask(f"assume_{name}", "MEDIUM",
                     f"'{name}' is assumed ({self.reg[name]}). Over {low}–{high} daily energy swings "
                     f"{swing:.1%}. Can you confirm it?", ["Confirm value", "Enter value", "Run both as scenarios"])
        return swing, asked

    # ------------------------------------------------------- engineer actions
    def _safe(self, name, value):
        if name in SAFE_BOUNDS:
            lo, hi, why = SAFE_BOUNDS[name]
            if not lo <= value <= hi:
                self.ask(f"unsafe_{name}", "SAFETY",
                         f"{name} = {value} rejected: outside safe range {lo}–{hi} ({why}). Nothing was changed.",
                         [f"Use a value within {lo}–{hi}", "Explain the special case (needs supervisor override)"])
                self._event("rejected_change", param=name, value=value, reason=why)
                return False
        return True

    def set_many(self, changes: dict, source="engineer", reason=""):
        """Validate all changes first, apply together, recompute once."""
        if not all(self._safe(k, v) for k, v in changes.items()):
            return None
        changed = []
        for name, value in changes.items():
            old = self.p.params[name]
            old_val, old_src = old.value, old.source.value
            self.p.set(name, value, old.unit, source, old.note)
            self._event("change", param=name, old=old_val, new=value, old_source=old_src,
                        source=source, reason=reason)
            if old_val != value:
                changed.append((name, old_val, value))
        if not changed:
            return []                       # provenance upgrade only; nothing to recompute
        if [c[0] for c in changed] == ["tariff"]:
            _, o, v = changed[0]
            s = self.summary
            s["annual saving (INR)"] *= v / o
            return [("annual saving (INR)", "", f"{s['annual saving (INR)']:,.0f}", "cost only; no physics rerun")]
        return self.recompute(reason=", ".join(f"{n}: {o} → {v}" for n, o, v in changed))

    def set(self, name, value, source="engineer", reason=""):
        return self.set_many({name: value}, source, reason)

    def preview_chws(self, new_Ts):
        """Two readings of 'change CHWS': keep return temp, or keep ΔT."""
        pin = plant.read_excel_inputs(XLSX)
        d = {k: pin[k] for k in pin.params}
        out = {}
        for label, ret in (("keep return", self.p["baseline_CHWR"]),
                           ("keep ΔT", new_Ts + self.p["baseline_CHWR"] - self.p["baseline_CHWS"])):
            d["CHWS_C"], d["CHWR_C"] = new_Ts, ret
            r = plant.design_point(d)
            out[label] = dict(CHWR=ret, dT=r["CHW_dT"], flow=r["CHW_m3_h"], pump=r["CHW_pump_kW"])
        return out

    def revert(self, name):
        for e in reversed(self.log):
            if e["kind"] == "change" and e["param"] == name:
                return self.set(name, e["old"], e["old_source"], reason="revert")
        return None

    def measure_chiller_load(self, hour, kW, note=""):
        """Calibrate the building-load multiplier from one measured chiller load.
        Only the uncertain building load is scaled; fan/pump heat and all
        physics equations stay unchanged."""
        ev = self.base[hour]
        predicted = ev["Q_chiller_kW"]
        fixed = ev["P"]["fan"] + ev["P"]["chw_pump"]          # physics-known heat
        k_old = self.p["load_calibration"]
        k_new = k_old * (kW - fixed) / (predicted - fixed)
        self.measurements.append(dict(hour=hour, quantity="chiller_load_kW", measured=kW,
                                      predicted=predicted, residual=kW - predicted, note=note))
        self._event("measurement", hour=hour, measured=kW, predicted=predicted,
                    error_pct=100 * (predicted / kW - 1), note=note)
        self.p.set("load_calibration", k_new, "-", "measured",
                   f"From {len(self.measurements)} measurement(s); single-point calibration")
        q = self.questions.get("calibration")
        if q:
            q.status, q.answer = "answered", f"1 measured point at {hour}:00"
        diff = self.recompute(reason=f"calibration {k_old:.3f} → {k_new:.3f}")
        if len(self.measurements) < 3:
            self.ask("more_data", "MEDIUM",
                     f"Calibrated on {len(self.measurements)} point(s) only. One hour cannot separate load error from "
                     "schedule or weather error. Can you share at least a week of hourly BMS chiller data?",
                     ["Upload BMS trend", "Accept single-point calibration"])
        return predicted, k_new, diff

    def check_measurement_consistency(self, flow_kg_s, dT, load_kW, tol=0.10):
        """Energy balance Q = ṁ·cp·ΔT between three measured values."""
        q = flow_kg_s * 4.186 * dT
        err = q / load_kW - 1
        self._event("consistency_check", flow=flow_kg_s, dT=dT, load=load_kW, implied=q, error=err)
        if abs(err) > tol:
            self.ask("energy_balance", "CONFLICT",
                     f"Measurements disagree: ṁ·cp·ΔT = {flow_kg_s} × 4.186 × {dT} = {q:.0f} kW, but the reported "
                     f"load is {load_kW:.0f} kW ({err:+.0%}). At least one is wrong (flow-meter calibration, sensor "
                     "placement, or a different time window). I will not use any of them until resolved.",
                     ["Flow reading is wrong", "ΔT sensors are wrong", "Load figure is wrong", "Check the time window"])
            return False, q
        return True, q

    def answer(self, key, answer, **params):
        q = self.questions[key]
        q.status, q.answer = "answered", answer
        self._event("answer", key=key, answer=answer)
        return self.set_many(params, "engineer", reason=f"answer to '{key}'") if params else None

    def what_if(self, **changes):
        """Evaluate a change without altering the session."""
        tmp = copy.deepcopy(self)
        for k, v in changes.items():
            tmp.p.set(k, v, tmp.p.params[k].unit, "engineer")
        tmp.questions = {}
        tmp.recompute(reason="what-if")
        return tmp.summary, tmp.open_questions()

    # --------------------------------------------------------- explanations
    def explain_chws(self, hour=15):
        o, sysm, hr = self.opt[hour], self.S["sys"], self.S["H"][hour]
        x = o["x"]
        dPch = float(sysm.chiller.dP_dTs(o["Q_chiller_kW"], x["Ts"], o["ECWT"]))
        up = x["Ts"] + 1.0
        fa_up = sysm.min_fan_for(up, x["fw"], x["ft"], hr)
        alt = sysm.evaluate((up, x["fw"], max(fa_up or 1.0, x["fa"]), x["ft"]), hr) if fa_up else None
        binding = [k for k, v in o["g"].items() if abs(v) < 1e-3]
        return dict(hour=hour, Ts=x["Ts"], dPch=dPch, P_ch=o["P"]["chiller"], fa=x["fa"], fa_up=fa_up,
                    alt=alt, opt=o, binding=binding, cap_drop=o["coil_cap_kW"] - sysm.coil.capacity(
                        up, o["T_mixed"], x["fa"], x["fw"]))

    def show_calculation(self, hour=15):
        return self.base[hour], self.opt[hour], self.S

    # ------------------------------------------------------ recommendations
    def propose(self):
        eb, eo = day(self.base), day(self.opt)
        rid = f"R{len(self.recs) + 1}"
        assumed = [f"{n} = {pr.value} ({pr.source.value})" for n, pr in self.p.params.items()
                   if pr.source in (Source.ASSUMED, Source.UNKNOWN)]
        measured = self.p.params["load_calibration"].source == Source.MEASURED
        coil_assumed = self.p.params["coil_margin"].source == Source.ASSUMED
        confidence = "LOW" if not measured else ("MEDIUM" if coil_assumed else "MEDIUM-HIGH")
        binding = sorted({k for r in self.opt.values() for k, v in r["g"].items() if abs(v) < 1e-3})
        sp = {h: {k: round(v, 2) for k, v in r["x"].items()} for h, r in self.opt.items()}
        for old in self.recs.values():
            if old.status == "PROPOSED":
                old.status = f"SUPERSEDED by {rid}"
        rec = Recommendation(rid, "Hourly set-point schedule (CHWS, CHW pump, AHU fan, tower fan)",
                             eb["total"], eo["total"], 100 * (1 - eo["total"] / eb["total"]),
                             (eb["total"] - eo["total"]) * 360 * self.p["tariff"], sp, binding, assumed, confidence)
        self.recs[rid] = rec
        self._event("recommendation", id=rid, saving_pct=rec.saving_pct, confidence=confidence)
        return rec

    def decide(self, rid, decision, note=""):
        rec = self.recs[rid]
        if decision == "approve":
            blockers = [q for q in self.open_questions() if q.blocking == "approval"]
            if blockers:
                self._event("approval_blocked", id=rid, by=[q.key for q in blockers])
                return False, blockers
            rec.status = "APPROVED FOR SUPERVISED TRIAL"
        elif decision == "reject":
            rec.status = "REJECTED"
        rec.history.append(f"{decision}: {note}")
        self._event("decision", id=rid, decision=decision, note=note)
        return True, []

    def dump_log(self, path):
        data = dict(log=self.log, questions=[asdict(q) for q in self.questions.values()],
                    recommendations=[asdict(r) for r in self.recs.values()], measurements=self.measurements,
                    parameters={n: dict(value=pr.value, unit=pr.unit, source=pr.source.value, note=pr.note)
                                for n, pr in self.p.params.items()})
        path.write_text(json.dumps(data, indent=2, default=float))


__all__ = ["Session", "PARTS"]
