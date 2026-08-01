from __future__ import annotations

import time
from pathlib import Path

from app.engine import initial_state, step
from app.scenario import ScenarioCatalog
from app.storage import Storage


ROOT = Path(__file__).resolve().parents[2]


def test_demo_city_completes_3600_ticks_within_budget(tmp_path: Path) -> None:
    scenario = ScenarioCatalog.load_all(ROOT / "scenarios").all()[0]
    database = tmp_path / "capacity.sqlite3"
    storage = Storage(database)
    storage.initialize()
    state = initial_state(scenario.config)
    run = storage.create_run(scenario, seed=123, initial_state=state)

    started = time.perf_counter()
    for _ in range(3600):
        next_state = step(scenario.config, state, run.seed)
        storage.commit_tick(run.id, state.tick, next_state)
        state = next_state
    elapsed = time.perf_counter() - started
    storage.set_status(run.id, ("running",), "ended")

    database_bytes = sum(path.stat().st_size for path in tmp_path.glob("capacity.sqlite3*"))
    assert state.tick == 3600
    assert elapsed < 60
    assert database_bytes < 100 * 1024 * 1024
