"""Conversational engineering assistant (prototype of the AI reasoning layer).

The LLM interprets the engineer and explains; every number comes from the
deterministic engine via tools (energy_model/agent_tools.py). Approval and
rejection are human-only commands handled here, never by the model.

    pip install anthropic
    python3 scripts/assistant.py          # needs Anthropic credentials

Human-only commands:  /approve R1   /reject R1 <reason>   /quit
"""

from __future__ import annotations

import sys
from pathlib import Path

import anthropic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from energy_model.agent_tools import TOOLS, dispatch  # noqa: E402
from energy_model.session import Session  # noqa: E402

MODEL = "claude-opus-5-5"

SYSTEM = """You are the engineering assistant of a building energy modelling and chiller-plant optimisation system.
You work for a building services engineer, who stays in control of every decision.

How you work:
- Every number you state must come from a tool result in this conversation. Never estimate, recall or invent values. \
If no tool gives a number, say so.
- Before quoting results, call get_status. Before discussing inputs, check list_parameters for each value's provenance \
and say whether it is measured, engineer-supplied, assumed or hypothetical.
- Call set_parameter only when the engineer has explicitly asked for that change, and pass their exact words as \
engineer_quote. If the request is ambiguous (for example "CHWS 7" could mean keeping the return temperature or keeping \
the ΔT), ask which they mean before changing anything.
- After any change, report the diff the tool returns and any new questions it raised.
- Proactively raise open questions from list_open_questions, highest priority first. Mention only those that \
matter for what the engineer is doing. SAFETY and CONFLICT items always come first.
- When asked "why", use explain_chws_decision or show_calculation and explain the physics in plain engineering \
language: the equations, the assumptions, and which constraints bind.
- Never describe predictions as measured or validated. All savings are predicted until verified by metered data.
- You cannot approve or reject recommendations and you cannot change equipment. When a recommendation is ready, \
tell the engineer they can approve it with /approve <id>, and mention anything that blocks approval.
- Be concise. Use short tables for numbers."""


def run_turn(client, session, messages):
    """Manual tool loop for one engineer message."""
    while True:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM,
            tools=TOOLS,
            messages=messages,
            output_config={"effort": "high"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        messages.append({"role": "assistant", "content": response.content})  # keep thinking/tool blocks intact

        if response.stop_reason == "refusal":
            print("\n[assistant declined this request]")
            return
        if response.stop_reason == "max_tokens":
            print("\n[response truncated: max_tokens reached]")
            return
        if response.stop_reason == "pause_turn":
            continue

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if not tool_uses:
            for b in response.content:
                if b.type == "text":
                    print(f"\n🤖 {b.text}")
            return
        results = []
        for t in tool_uses:
            print(f"   · engine: {t.name}({t.input})")
            out = dispatch(session, t.name, t.input)
            results.append({"type": "tool_result", "tool_use_id": t.id, "content": out,
                            "is_error": out.startswith('{"error"')})
        messages.append({"role": "user", "content": results})   # all results in one message


def main():
    print("Loading engineering model…")
    session = Session()
    client = anthropic.Anthropic()
    messages = []
    print("Ready. Talk to the assistant. Human-only: /approve <id>, /reject <id> <reason>, /quit")
    while True:
        try:
            text = input("\n🧑‍🔧 ").strip()
        except EOFError:
            break
        if not text:
            continue
        if text == "/quit":
            break
        if text.startswith(("/approve", "/reject")):
            parts = text.split(maxsplit=2)
            if len(parts) < 2 or parts[1] not in session.recs:
                print("   usage: /approve <id> | /reject <id> <reason>  (id from a proposed recommendation)")
                continue
            cmd, rid, *note = parts
            ok, blockers = session.decide(rid, cmd[1:], note=note[0] if note else "")
            msg = (f"{rid}: {session.recs[rid].status}" if ok
                   else f"{rid} blocked by: {', '.join(q.key for q in blockers)}")
            print(f"   [human decision] {msg}")
            # tell the model what the human decided, so the conversation stays consistent
            messages.append({"role": "user", "content": f"[Human decision recorded by the interface] {msg}"})
            continue
        messages.append({"role": "user", "content": text})
        run_turn(client, session, messages)
    out = ROOT / "reports" / "stage6"
    out.mkdir(parents=True, exist_ok=True)
    session.dump_log(out / "assistant_audit_log.json")


if __name__ == "__main__":
    main()
