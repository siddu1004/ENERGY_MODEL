"""Minimal interactive console for the engineering session.

This stands in for the conversational AI layer: here the engineer types
structured commands; in production an LLM maps free text to the same calls.

  python3 scripts/engineer_cli.py
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from energy_model.session import Session  # noqa: E402

HELP = """commands:
  status                         key results
  questions                      open questions (priority order)
  params                         parameters with provenance
  set <param> <value>            change a parameter (validated, then full recalculation)
  revert <param>                 undo the last change of a parameter
  whatif <param>=<value> ...     evaluate without changing the session
  measure <hour> <kW>            measured chiller load -> calibration
  check <flow_kg_s> <dT> <kW>    energy-balance consistency of measurements
  answer <key> "<text>" [p=v..]  answer a question (optionally setting parameters)
  why [hour]                     explain the CHWS decision at an hour (default 15)
  calc [hour]                    show the calculation chain baseline vs optimised
  propose                        create a recommendation
  approve <id> | reject <id>     decide on a recommendation (never touches equipment)
  save                           write audit log to reports/stage4/cli_audit_log.json
  quit"""


def val(x):
    lx = x.lower()
    if lx in ("true", "yes"):
        return True
    if lx in ("false", "no"):
        return False
    try:
        return int(x)
    except ValueError:
        try:
            return float(x)
        except ValueError:
            return x


def show_diff(rows):
    if rows is None:
        print("  ✋ change rejected, see `questions`")
        return
    for k, a, b, c in rows or [("(no numerical change)", "", "", "")]:
        print(f"  {k:34s} {a:>14s} → {b:>14s}  {c}")


def main():
    print("Loading model (≈5 s)…")
    s = Session()
    print(HELP)
    while True:
        try:
            line = input("\nengineer> ").strip()
        except EOFError:
            break
        if not line:
            continue
        cmd, *a = shlex.split(line)
        try:
            if cmd == "quit":
                break
            elif cmd == "status":
                for k, v in s.summary.items():
                    print(f"  {k:34s} {v if isinstance(v, tuple) else f'{v:,.2f}'}")
            elif cmd == "questions":
                for q in s.open_questions():
                    print(f"  [{q.priority}] {q.key}: {q.text}\n      options: {' | '.join(q.options)}")
            elif cmd == "params":
                for n, p in s.p.params.items():
                    print(f"  {n:18s} {str(p.value):>10s} {p.unit:8s} {p.source.value}")
            elif cmd == "set":
                show_diff(s.set(a[0], val(a[1]), reason="cli"))
            elif cmd == "revert":
                show_diff(s.revert(a[0]))
            elif cmd == "whatif":
                sm, qs = s.what_if(**{k: val(v) for k, v in (x.split("=") for x in a)})
                for k, v in sm.items():
                    print(f"  {k:34s} {v if isinstance(v, tuple) else f'{v:,.2f}'}")
                for q in qs:
                    print(f"  would ask [{q.priority}] {q.key}")
            elif cmd == "measure":
                pred, k, d = s.measure_chiller_load(int(a[0]), float(a[1]), note="cli")
                print(f"  predicted {pred:.0f} kW, measured {a[1]} kW → load calibration {k:.3f}")
                show_diff(d)
            elif cmd == "check":
                ok, q = s.check_measurement_consistency(float(a[0]), float(a[1]), float(a[2]))
                print(f"  ṁ·cp·ΔT = {q:.0f} kW → {'consistent' if ok else 'CONFLICT, see questions'}")
            elif cmd == "answer":
                show_diff(s.answer(a[0], a[1], **{k: val(v) for k, v in (x.split("=") for x in a[2:])}))
            elif cmd == "why":
                e = s.explain_chws(int(a[0]) if a else 15)
                print(f"  CHWS {e['Ts']:.2f} °C; ∂P_chiller/∂CHWS = {e['dPch']:+.2f} kW/K; binding: {e['binding']}")
                if e["alt"]:
                    print(f"  CHWS +1 K → fan {e['fa']:.0%}→{e['fa_up']:.0%}, net "
                          f"{e['alt']['total_kW'] - e['opt']['total_kW']:+.1f} kW")
            elif cmd == "calc":
                b, o, _ = s.show_calculation(int(a[0]) if a else 15)
                for key in ("total_kW", "Q_chiller_kW", "ECWT", "T_supply", "coil_cap_kW", "Q_coil_sens_kW"):
                    print(f"  {key:16s} {b[key]:10.2f} {o[key]:10.2f}")
                for p in o["P"]:
                    print(f"  P_{p:14s} {b['P'][p]:10.2f} {o['P'][p]:10.2f}")
            elif cmd == "propose":
                r = s.propose()
                print(f"  {r.id}: saving {r.saving_pct:.1f} %, confidence {r.confidence}, {r.validation}")
            elif cmd in ("approve", "reject"):
                ok, blockers = s.decide(a[0], cmd, note="cli")
                print(f"  {a[0]}: {s.recs[a[0]].status}" if ok else
                      "  blocked by: " + ", ".join(q.key for q in blockers))
            elif cmd == "save":
                path = ROOT / "reports" / "stage4" / "cli_audit_log.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                s.dump_log(path)
                print(f"  saved {path}")
            else:
                print(HELP)
        except (IndexError, KeyError, ValueError) as exc:
            print(f"  error: {exc!r}\n{HELP}")


if __name__ == "__main__":
    main()
