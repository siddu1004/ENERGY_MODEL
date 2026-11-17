"""Human-in-the-loop behaviour of the engineering session."""

import numpy as np
import pytest

from energy_model.provenance import Source
from energy_model.session import Session


@pytest.fixture(scope="module")
def s():
    return Session()


def test_unsafe_change_rejected_and_state_unchanged(s):
    before = dict(s.summary)
    assert s.set("baseline_CHWS", 3.0) is None
    assert s.p["baseline_CHWS"] == 6.0
    assert s.summary == before
    assert s.questions["unsafe_baseline_CHWS"].priority == "SAFETY"


def test_conflicting_measurements_flagged(s):
    ok, implied = s.check_measurement_consistency(25, 5, 690)
    assert not ok and implied == pytest.approx(523.25)
    assert s.questions["energy_balance"].priority == "CONFLICT"


def test_approval_blocked_until_vfd_known(s):
    r = s.propose()
    ok, blockers = s.decide(r.id, "approve")
    assert not ok and blockers[0].key == "vfd"
    assert r.status == "PROPOSED"


def test_provenance_upgrade_without_recompute(s):
    n_recompute = sum(e["kind"] == "recompute" for e in s.log)
    assert s.answer("floors", "confirmed", floors_served=s.p["floors_served"]) == []
    assert s.p.params["floors_served"].source == Source.ENGINEER
    assert sum(e["kind"] == "recompute" for e in s.log) == n_recompute


def test_calibration_scales_load_not_physics(s):
    coef_before = s.S["sys"].chiller.coef.copy()
    s.measure_chiller_load(15, 690.0)
    assert s.p.params["load_calibration"].source == Source.MEASURED
    assert s.base[15]["Q_chiller_kW"] == pytest.approx(690.0, rel=0.01)   # model now reproduces measurement
    assert np.allclose(s.S["sys"].chiller.coef, coef_before)               # equations untouched


def test_answered_question_not_reasked(s):
    s.answer("more_data", "later")
    s.recompute(reason="test")
    assert s.questions["more_data"].status == "answered"
