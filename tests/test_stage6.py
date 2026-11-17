"""AI tool layer: schemas are well-formed and the dispatcher enforces the guardrails."""

import json

import pytest

from energy_model.agent_tools import TOOLS, dispatch
from energy_model.session import Session


@pytest.fixture(scope="module")
def s():
    return Session()


def call(s, tool, **args):
    return json.loads(dispatch(s, tool, args))


def test_tool_schemas_strict_and_complete():
    names = " ".join(t["name"] for t in TOOLS)
    assert "approve" not in names and "reject" not in names      # human-only actions
    for t in TOOLS:
        sch = t["input_schema"]
        assert t["strict"] is True and sch["additionalProperties"] is False
        assert set(sch["required"]) == set(sch["properties"])


def test_no_argument_tools_dispatch(s):
    for t in TOOLS:
        if not t["input_schema"]["properties"]:
            assert "error" not in call(s, t["name"])


def test_set_parameter_requires_quote_and_respects_safety(s):
    assert "refused" in call(s, "set_parameter", name="baseline_CHWS", value=7.0, engineer_quote=" ")["error"]
    r = call(s, "set_parameter", name="baseline_CHWS", value=3.0, engineer_quote="set CHWS to 3")
    assert r["applied"] is False and r["questions"][0]["priority"] == "SAFETY"
    assert "unknown" in call(s, "set_parameter", name="U_wall", value=0.1, engineer_quote="x")["error"]


def test_set_parameter_logs_quote(s):
    r = call(s, "set_parameter", name="tariff", value=9.0, engineer_quote="tariff is 9 rupees now")
    assert r["applied"] is True
    assert any(e["kind"] == "change" and "tariff is 9 rupees" in e["reason"] for e in s.log)


def test_unknown_tool_and_bad_input_return_errors(s):
    assert "error" in call(s, "launch_chiller")
    assert "error" in call(s, "answer_question", key="nope", answer="x")
    assert "error" in call(s, "explain_chws_decision")          # missing argument -> error, not crash
