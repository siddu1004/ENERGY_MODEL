# Intelligent Building Energy Modelling & Optimisation: prototype

Prototype of an engineering assistant that reads a building's 3D model (USDZ), estimates its cooling loads, models the chilled-water plant, finds minimum-energy operating points under comfort and equipment constraints, and works with an engineer who stays in control.

> All data here is **synthetic**, and all savings are **predicted, not validated**. See the Stage 5 review before quoting any number.

## Stages

| Stage | What | Report |
|---|---|---|
| — | Synthetic sample building (USDZ) and chiller workbook (Excel) | [`sample_data/README.md`](sample_data/README.md) |
| 2 | Geometry → loads → dynamic RC model → plant energy | [`reports/stage2/report.md`](reports/stage2/report.md) |
| 3 | Curve fitting, calculus, constrained optimisation, sensitivity, scenarios | [`reports/stage3/report.md`](reports/stage3/report.md) |
| 4 | Human-in-the-loop session: changes, explanations, corrections, approvals | [`reports/stage4/transcript.md`](reports/stage4/transcript.md) |
| 5 | Critical review with stress experiments | [`reports/stage5/review.md`](reports/stage5/review.md) |
| 6 | Implementation architecture + AI tool layer | [`reports/stage6/architecture.md`](reports/stage6/architecture.md) |

## Run

```bash
pip install -r requirements.txt
python3 -m pytest -q                      # 23 regression tests
python3 scripts/stage2_run.py             # regenerate a stage report (2, 3, 4, 5 similarly)
python3 scripts/engineer_cli.py           # interactive engine session, no LLM
python3 scripts/assistant.py              # conversational assistant (needs Anthropic credentials)
```

## Layout

- `energy_model/`: deterministic calculation core (geometry, climate, loads, RC model, component models, optimiser, session, AI tools)
- `scripts/`: sample-data generators, stage runners, CLI, assistant
- `sample_data/`: synthetic USDZ, Excel workbook, ground truth
- `reports/`: stage reports, charts, audit logs
- `tests/`: regression tests
