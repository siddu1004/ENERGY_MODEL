"""Regression tests for the Stage 2 calculation core."""

import json
from pathlib import Path

import numpy as np
import pytest

from energy_model import plant
from energy_model.climate import irradiance, sun_position
from energy_model.defaults import default_registry
from energy_model.geometry import load_usdz
from energy_model.loads import building_loads
from energy_model.rc_model import simulate_floor

ROOT = Path(__file__).resolve().parents[1]
USDZ = ROOT / "sample_data" / "sample_building.usdz"
XLSX = ROOT / "sample_data" / "sample_chiller_calculations.xlsx"
TRUTH = json.loads((ROOT / "sample_data" / "sample_building_ground_truth.json").read_text())


@pytest.fixture(scope="module")
def building():
    return load_usdz(USDZ)


def test_geometry_totals_match_ground_truth(building):
    s = building.summary()
    for k in ("floor_area_m2", "volume_m3", "exterior_wall_gross_area_m2", "exterior_window_area_m2"):
        assert s[k] == pytest.approx(TRUTH["totals"][k], abs=1e-3)


def test_geometry_per_wall_exterior_and_windows(building):
    for name, room in building.rooms.items():
        gt = TRUTH["rooms"][name]
        assert room.floor_area == pytest.approx(gt["floor_area_m2"])
        for wall, gw in zip(room.walls, gt["walls"]):
            assert (wall.exterior_length > 0) == gw["exterior"], (name, wall.name)
            win = sum(o.area for o in wall.exterior_openings("Window"))
            assert win == pytest.approx(gw["window_area_m2"] if gw["exterior"] else 0, abs=1e-3)


def test_python_plant_reproduces_excel():
    excel = plant.read_excel_results(XLSX)
    py = plant.design_point(plant.read_excel_inputs(XLSX))
    for k, v in excel.items():
        assert py[k] == pytest.approx(v, rel=1e-9), k


def test_energy_balance_heat_rejection():
    d = plant.design_point(plant.read_excel_inputs(XLSX))
    assert d["Q_rej_kW"] == pytest.approx(d["Q_load_kW"] + d["Chiller_kW"])


def test_partload_fit_quality():
    fit = plant.fit_partload(XLSX)
    assert fit.r2 > 0.99
    assert fit.power_fraction(1.0) == pytest.approx(1.0, abs=0.03)


def test_solar_noon_symmetry():
    # east wall at 9:00 == west wall at 15:00 (solar time)
    assert irradiance(9, 90, 90, 17.4, 141) == pytest.approx(irradiance(15, 270, 90, 17.4, 141))
    alt, _ = sun_position(12, 17.4, 141)
    assert alt > 85


def test_rc_model_is_periodic_and_holds_setpoint(building):
    reg = default_registry()
    L = building_loads(building, reg)
    res = simulate_floor(L, building.floor_area, building.volume, reg, q_max_W=1e6, days=10)
    assert res.T_mass[0] == pytest.approx(res.T_mass[-1], abs=0.2)
    assert np.all(res.T_air[8:20] < reg["T_in"] + 1.0)
