from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.engine import initial_state, step
from app.scenario import load_scenario
from app.storage import ActiveRunExists, StaleRunState, Storage


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def scenario():
    return load_scenario(ROOT / "scenarios" / "demo-city")


def test_initialize_creates_two_business_tables(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "flow.sqlite3")
    storage.initialize()
    with sqlite3.connect(storage.db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {"runs", "tick_snapshots"}.issubset(tables)
    assert "scenario_versions" not in tables


def test_create_run_persists_tick_zero_and_scene(tmp_path: Path, scenario) -> None:
    storage = Storage(tmp_path / "flow.sqlite3")
    storage.initialize()
    run = storage.create_run(scenario, seed=42, initial_state=initial_state(scenario.config))
    assert run.current_tick == 0
    detail = storage.get_detail(run.id, include_scenario=True)
    assert detail.scenario_bundle_json == scenario.bundle_json
    assert detail.latest_snapshot.tick == 0


def test_only_one_active_run_is_allowed(tmp_path: Path, scenario) -> None:
    storage = Storage(tmp_path / "flow.sqlite3")
    storage.initialize()
    state = initial_state(scenario.config)
    storage.create_run(scenario, seed=1, initial_state=state)
    with pytest.raises(ActiveRunExists):
        storage.create_run(scenario, seed=2, initial_state=state)


def test_commit_tick_is_atomic_and_guarded(tmp_path: Path, scenario) -> None:
    storage = Storage(tmp_path / "flow.sqlite3")
    storage.initialize()
    state = initial_state(scenario.config)
    run = storage.create_run(scenario, seed=1, initial_state=state)
    next_state = step(scenario.config, state, seed=run.seed)
    storage.commit_tick(run.id, expected_tick=0, next_state=next_state)
    assert storage.get_run(run.id).current_tick == 1
    assert storage.get_snapshot(run.id, 1).tick == 1
    with pytest.raises(StaleRunState):
        storage.commit_tick(run.id, expected_tick=0, next_state=step(scenario.config, next_state, run.seed))
    assert storage.get_run(run.id).current_tick == 1


def test_recover_interrupted_runs_marks_active_as_failed(tmp_path: Path, scenario) -> None:
    storage = Storage(tmp_path / "flow.sqlite3")
    storage.initialize()
    run = storage.create_run(scenario, seed=1, initial_state=initial_state(scenario.config))
    assert storage.recover_interrupted_runs() == 1
    recovered = storage.get_run(run.id)
    assert recovered.status == "failed"
    assert recovered.error_code == "process_interrupted"
