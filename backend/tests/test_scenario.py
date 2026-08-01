from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.scenario import ScenarioCatalog, ScenarioValidationError, load_scenario


ROOT = Path(__file__).resolve().parents[2]


def test_demo_city_loads_and_is_stable() -> None:
    loaded = load_scenario(ROOT / "scenarios" / "demo-city")
    assert loaded.config.scenario_id == "demo-city"
    assert len(loaded.config.locations) == 12
    assert len(loaded.config.connections) == 28
    assert len(loaded.checksum) == 64
    assert loaded.bundle_json == loaded.bundle_json.replace(" ", "")


def test_catalog_loads_sorted_scenarios() -> None:
    catalog = ScenarioCatalog.load_all(ROOT / "scenarios")
    assert [scenario.config.scenario_id for scenario in catalog.all()] == ["demo-city"]


def test_path_endpoint_mismatch_is_rejected(tmp_path: Path) -> None:
    source = ROOT / "scenarios" / "demo-city" / "scenario.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["connections"][0]["path"][0] = [999, 999]
    scenario_dir = tmp_path / "demo-city"
    scenario_dir.mkdir()
    (scenario_dir / "scenario.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ScenarioValidationError, match="does not start"):
        load_scenario(scenario_dir)


def test_unknown_flow_type_is_rejected(tmp_path: Path) -> None:
    source = ROOT / "scenarios" / "demo-city" / "scenario.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["locations"][0]["initial_counts"]["ghost"] = 1
    scenario_dir = tmp_path / "demo-city"
    scenario_dir.mkdir()
    (scenario_dir / "scenario.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ScenarioValidationError, match="unknown flow types"):
        load_scenario(scenario_dir)
