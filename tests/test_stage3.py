"""Regression tests for Stage 3 component models and optimiser."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from stage3_run import baseline, build  # noqa: E402

from energy_model.hvac import VariableSpeed, fit_chiller  # noqa: E402


@pytest.fixture(scope="module")
def S():
    return build()


def test_chiller_regression_generalises():
    m = fit_chiller(ROOT / "sample_data" / "sample_chiller_calculations.xlsx")
    assert m.stats["r2"] > 0.99
    assert m.stats["test_rmse_kW"] < 2 * m.stats["rmse_kW"] + 0.5   # no gross overfit
    assert m.stats["dP/dTc>0 everywhere"]


def test_affinity_law_endpoints():
    p = VariableSpeed(P0=10.0, c=0.2)
    assert p.power(1.0) == pytest.approx(10.0)
    assert p.power(0.5) == pytest.approx(10.0 * 0.5 * (0.2 + 0.8 * 0.25))


def test_baseline_feasible_every_hour(S):
    assert all(r["feasible"] for r in baseline(S).values())


def test_heat_rejection_consistent(S):
    ev = S["sys"].evaluate((6, 1, 1, 1), S["H"][15])
    q_rej = ev["Q_chiller_kW"] + ev["P"]["chiller"]
    approach = S["sys"].tower.approach(q_rej, 1.0)
    assert ev["ECWT"] == pytest.approx(S["H"][15].wb + approach, abs=0.05)


def test_optimum_feasible_better_than_baseline_and_grid(S):
    sysm, hr = S["sys"], S["H"][15]
    opt = sysm.optimize(hr)
    base = sysm.evaluate((6, 1, 1, 1), hr)
    grid = sysm.grid_search(hr, n=(11, 6, 11, 8))
    assert opt["feasible"]
    assert opt["total_kW"] < base["total_kW"]
    assert opt["total_kW"] <= grid["total_kW"] + 0.5
