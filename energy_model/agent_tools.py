"""Tool surface that exposes the deterministic engine to an LLM.

Design rules (enforced here, not just in the prompt):
  - Every number the assistant reports must come from one of these tools.
  - The model can READ, EXPLAIN, PROPOSE and record engineer-authorised changes.
  - The model CANNOT approve or reject a recommendation: there is no such tool.
    Decisions happen only in the human interface.
  - Changing a parameter requires the engineer's verbatim instruction
    (`engineer_quote`), which is stored in the audit log with the change.
  - The engine's own safety bounds still apply; a rejected change returns
    the safety question instead of a result.
"""

from __future__ import annotations

import json

from .session import Session


def _tool(name, description, props):
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": props,
            "required": list(props),
            "additionalProperties": False,
        },
    }


HOUR = {"type": "integer", "description": "Clock hour 8-19 (operating hours)"}

TOOLS = [
    _tool("get_status", "Current key results: baseline and optimised energy, predicted saving, design flow, "
          "optimal CHWS range. Call this before quoting any result.", {}),
    _tool("list_parameters", "All engineer-facing parameters with value, unit and provenance "
          "(measured / engineer / assumed / hypothetical / unknown).", {}),
    _tool("list_open_questions", "Open questions in priority order (SAFETY, CONFLICT, HIGH, MEDIUM, LOW), "
          "including which ones block approval.", {}),
    _tool("set_parameter",
          "Change a parameter ONLY when the engineer has explicitly asked for that change. The engine validates "
          "safety bounds, recalculates everything and returns the before/after diff. Parameters: baseline_CHWS, "
          "baseline_CHWR, floors_served, RH_max, T_sa_min, fan_min, coil_margin, tariff, vfd_ahu, vfd_chw_pump, "
          "vfd_tower.",
          {"name": {"type": "string"},
           "value": {"type": ["number", "boolean"]},
           "engineer_quote": {"type": "string",
                              "description": "The engineer's exact words authorising this change"}}),
    _tool("answer_question",
          "Record the engineer's answer to an open question (by key). Use when the engineer answers or "
          "resolves a question without changing a parameter.",
          {"key": {"type": "string"}, "answer": {"type": "string"}}),
    _tool("record_chiller_load_measurement",
          "Record a measured chiller load supplied by the engineer and calibrate the building-load multiplier. "
          "Returns predicted vs measured and the diff.",
          {"hour": HOUR, "measured_kW": {"type": "number"}, "source_note": {"type": "string"}}),
    _tool("check_measurement_consistency",
          "Energy-balance check Q = m·cp·ΔT between measured flow (kg/s), ΔT (K) and load (kW). Raises a CONFLICT "
          "question if they disagree.",
          {"flow_kg_s": {"type": "number"}, "dT_K": {"type": "number"}, "load_kW": {"type": "number"}}),
    _tool("what_if", "Evaluate one parameter change WITHOUT changing the session.",
          {"name": {"type": "string"}, "value": {"type": ["number", "boolean"]}}),
    _tool("explain_chws_decision",
          "Model-based explanation of the chilled-water temperature choice at an hour: chiller derivative, "
          "knock-on fan effect of +1 K, binding constraints.", {"hour": HOUR}),
    _tool("show_calculation", "Equation-by-equation calculation chain, baseline vs optimised, at an hour.",
          {"hour": HOUR}),
    _tool("propose_recommendation",
          "Create a recommendation from the current optimisation (status PROPOSED). Only a human can approve it.",
          {}),
]

ALLOWED_PARAMS = {"baseline_CHWS", "baseline_CHWR", "floors_served", "RH_max", "T_sa_min", "fan_min",
                  "coil_margin", "tariff", "vfd_ahu", "vfd_chw_pump", "vfd_tower"}


def _r(x):
    if isinstance(x, float):
        return round(x, 3)
    if isinstance(x, (list, tuple)):
        return [_r(v) for v in x]
    if isinstance(x, dict):
        return {k: _r(v) for k, v in x.items()}
    return x


def _diff(rows):
    if rows is None:
        return None
    return [dict(quantity=k, before=a, after=b, change=c) for k, a, b, c in rows]


def _questions(s, keys=None):
    return [dict(key=q.key, priority=q.priority, text=q.text, options=q.options, blocks=q.blocking)
            for q in s.open_questions() if keys is None or q.key in keys]


def dispatch(s: Session, name: str, args: dict) -> str:
    """Run one tool call against the session; always returns a JSON string."""
    try:
        out = _dispatch(s, name, args)
    except Exception as exc:          # surfaced to the model as an error tool_result
        out = {"error": f"{type(exc).__name__}: {exc}"}
    return json.dumps(_r(out), default=str)


def _dispatch(s, name, a):
    before = {q.key for q in s.open_questions()}
    if name == "get_status":
        return dict(summary=s.summary, provenance_note="All values PREDICTED; none validated.")
    if name == "list_parameters":
        return {n: dict(value=p.value, unit=p.unit, source=p.source.value, note=p.note)
                for n, p in s.p.params.items()}
    if name == "list_open_questions":
        return _questions(s)
    if name == "set_parameter":
        if a["name"] not in ALLOWED_PARAMS:
            return {"error": f"unknown or non-editable parameter '{a['name']}'"}
        if not a.get("engineer_quote", "").strip():
            return {"error": "refused: no engineer instruction quoted"}
        d = s.set(a["name"], a["value"], "engineer", reason=f"engineer said: {a['engineer_quote']}")
        if d is None:
            return dict(applied=False, reason="rejected by engine safety bounds",
                        questions=_questions(s, {f"unsafe_{a['name']}"}))
        new = {q.key for q in s.open_questions()} - before
        return dict(applied=True, diff=_diff(d), new_questions=_questions(s, new))
    if name == "answer_question":
        if a["key"] not in s.questions:
            return {"error": f"no question '{a['key']}'"}
        s.answer(a["key"], a["answer"])
        return dict(recorded=True)
    if name == "record_chiller_load_measurement":
        pred, k, d = s.measure_chiller_load(a["hour"], a["measured_kW"], note=a["source_note"])
        new = {q.key for q in s.open_questions()} - before
        return dict(predicted_kW=pred, measured_kW=a["measured_kW"],
                    model_error_pct=100 * (pred / a["measured_kW"] - 1), new_load_calibration=k,
                    diff=_diff(d), new_questions=_questions(s, new),
                    note="Only the building-load multiplier was calibrated; physics equations unchanged.")
    if name == "check_measurement_consistency":
        ok, q = s.check_measurement_consistency(a["flow_kg_s"], a["dT_K"], a["load_kW"])
        return dict(consistent=ok, implied_load_kW=q, questions=[] if ok else _questions(s, {"energy_balance"}))
    if name == "what_if":
        if a["name"] not in ALLOWED_PARAMS:
            return {"error": f"unknown parameter '{a['name']}'"}
        sm, qs = s.what_if(**{a["name"]: a["value"]})
        return dict(summary=sm, would_raise=[dict(key=q.key, priority=q.priority, text=q.text) for q in qs],
                    note="Session unchanged.")
    if name == "explain_chws_decision":
        e = s.explain_chws(a["hour"])
        o, alt = e["opt"], e["alt"]
        return dict(hour=e["hour"], chosen_CHWS=e["Ts"], dP_chiller_dCHWS_kW_per_K=e["dPch"],
                    chiller_kW=e["P_ch"], coil_capacity_drop_kW_per_K=e["cap_drop"],
                    fan_speed_now=e["fa"], fan_speed_needed_at_plus_1K=e["fa_up"],
                    net_change_kW_at_plus_1K=(alt["total_kW"] - o["total_kW"]) if alt else None,
                    component_change_kW_at_plus_1K={k: alt["P"][k] - o["P"][k] for k in o["P"]} if alt else None,
                    binding_constraints=e["binding"],
                    assumptions=["coil UA (assumed margin)", "fan law exponent (assumed)",
                                 "chiller regression (synthetic data)"])
    if name == "show_calculation":
        b, o, _ = s.show_calculation(a["hour"])
        keys = ["x", "P", "total_kW", "T_mixed", "Q_coil_sens_kW", "coil_cap_kW", "T_supply", "T_dp_required",
                "Q_chiller_kW", "CHWR", "Q_rej_kW", "ECWT", "cop"]
        return dict(baseline={k: b[k] for k in keys}, optimised={k: o[k] for k in keys})
    if name == "propose_recommendation":
        r = s.propose()
        blockers = [q.key for q in s.open_questions() if q.blocking == "approval"]
        return dict(id=r.id, saving_pct=r.saving_pct, daily_kWh_baseline=r.daily_kWh_baseline,
                    daily_kWh_optimised=r.daily_kWh_optimised, annual_saving_cost=r.annual_saving_cost,
                    confidence=r.confidence, validation=r.validation, binding_constraints=r.binding,
                    approval_blocked_by=blockers,
                    note="Only the engineer can approve, in the interface. No equipment is changed by approval.")
    return {"error": f"unknown tool '{name}'"}
