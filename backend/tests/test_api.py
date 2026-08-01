from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


ROOT = Path(__file__).resolve().parents[2]


def client_for(tmp_path: Path) -> TestClient:
    application = create_app(
        db_path=tmp_path / "flow.sqlite3",
        scenario_dir=ROOT / "scenarios",
        static_dir=tmp_path / "empty-static",
    )
    return TestClient(application)


def test_list_scenarios_returns_normalized_bundle(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        response = client.get("/api/scenarios")
    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["config"]["scenario_id"] == "demo-city"
    assert len(body["items"][0]["config"]["connections"]) == 28


def test_create_pause_resume_end_and_snapshot(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        created = client.post("/api/runs", json={"scenario_id": "demo-city", "seed": 7})
        assert created.status_code == 201
        run = created.json()["run"]
        assert run["current_tick"] == 0
        run_id = run["id"]

        paused = client.post(f"/api/runs/{run_id}/commands", json={"action": "pause"})
        assert paused.status_code == 200
        assert paused.json()["run"]["status"] == "paused"
        assert client.post(
            f"/api/runs/{run_id}/commands", json={"action": "pause"}
        ).json()["run"]["status"] == "paused"

        resumed = client.post(f"/api/runs/{run_id}/commands", json={"action": "resume"})
        assert resumed.status_code == 200
        assert resumed.json()["run"]["status"] == "running"

        snapshot = client.get(f"/api/runs/{run_id}/snapshots/0")
        assert snapshot.status_code == 200
        assert snapshot.json()["tick"] == 0

        ended = client.post(f"/api/runs/{run_id}/commands", json={"action": "end"})
        assert ended.status_code == 200
        assert ended.json()["run"]["status"] == "ended"
        assert client.post(
            f"/api/runs/{run_id}/commands", json={"action": "resume"}
        ).status_code == 409


def test_only_one_active_run_and_validation_errors(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        first = client.post("/api/runs", json={"scenario_id": "demo-city", "seed": 1})
        assert first.status_code == 201
        second = client.post("/api/runs", json={"scenario_id": "demo-city", "seed": 2})
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "active_run_exists"
        invalid = client.post(
            "/api/runs/nope/commands", json={"action": "set_rate"}
        )
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "validation_error"


def test_scheduler_commits_a_tick(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        created = client.post("/api/runs", json={"scenario_id": "demo-city", "seed": 11})
        run_id = created.json()["run"]["id"]
        deadline = time.monotonic() + 2.5
        tick = 0
        while time.monotonic() < deadline:
            detail = client.get(f"/api/runs/{run_id}").json()
            tick = detail["run"]["current_tick"]
            if tick >= 1:
                break
            time.sleep(0.05)
        assert tick >= 1
        client.post(f"/api/runs/{run_id}/commands", json={"action": "end"})


def test_invalid_scenario_and_missing_snapshot_are_mapped(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        missing = client.post("/api/runs", json={"scenario_id": "missing"})
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "scenario_not_found"

        created = client.post("/api/runs", json={"scenario_id": "demo-city", "seed": 3})
        run_id = created.json()["run"]["id"]
        missing_snapshot = client.get(f"/api/runs/{run_id}/snapshots/99")
        assert missing_snapshot.status_code == 404
        assert missing_snapshot.json()["error"]["code"] == "snapshot_not_found"
        client.post(f"/api/runs/{run_id}/commands", json={"action": "end"})
