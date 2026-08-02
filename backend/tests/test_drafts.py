from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


ROOT = Path(__file__).resolve().parents[2]


def client_for(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            db_path=tmp_path / "flow.sqlite3",
            scenario_dir=ROOT / "scenarios",
            static_dir=tmp_path / "empty-static",
        )
    )


def _wait_ready(client: TestClient, draft_id: str) -> dict:
    deadline = time.monotonic() + 3
    latest: dict = {}
    while time.monotonic() < deadline:
        latest = client.get(f"/api/scenario-drafts/{draft_id}").json()
        if latest["compile_status"] != "compiling":
            return latest
        time.sleep(0.02)
    raise AssertionError(f"draft did not finish compiling: {latest}")


def test_create_draft_returns_skeleton_before_or_after_compile(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        response = client.post(
            "/api/scenario-drafts",
            json={"generation_seed": 8815907750467, "population": 11_499, "name": "Alimontalle"},
        )
        assert response.status_code == 202
        initial = response.json()
        assert initial["generation_seed"] == 8815907750467
        assert initial["town_skeleton"]["generator_version"] == "radial-v1"
        assert initial["compile_status"] in {"compiling", "ready"}

        ready = _wait_ready(client, initial["draft_id"])
        assert ready["compile_status"] == "ready"
        assert ready["simulation_package"]["schema_version"] == 2
        assert ready["bundle_checksum"]
        assert ready["bundle"]["town_skeleton"]["scenario_id"] == ready["town_skeleton"]["scenario_id"]
        assert sum(
            location["initial_counts"]["pedestrian"]
            for location in ready["simulation_package"]["locations"]
        ) == 11_499


def test_same_generation_input_has_same_checksums(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        first = client.post(
            "/api/scenario-drafts", json={"generation_seed": 17, "population": 1000}
        ).json()
        second = client.post(
            "/api/scenario-drafts", json={"generation_seed": 17, "population": 1000}
        ).json()
        first_ready = _wait_ready(client, first["draft_id"])
        second_ready = _wait_ready(client, second["draft_id"])

    assert first_ready["skeleton_checksum"] == second_ready["skeleton_checksum"]
    assert first_ready["bundle_checksum"] == second_ready["bundle_checksum"]


def test_ready_draft_can_start_a_run_with_full_bundle(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        draft = client.post(
            "/api/scenario-drafts",
            json={"generation_seed": 7, "population": 1000, "name": "Run Town"},
        ).json()
        ready = _wait_ready(client, draft["draft_id"])
        created = client.post(
            "/api/runs",
            json={"draft_id": draft["draft_id"], "simulation_seed": 19},
        )
        assert created.status_code == 201
        body = created.json()
        assert body["run"]["scenario_schema_version"] == 2
        assert body["run"]["seed"] == 19
        assert body["scenario"]["town_skeleton"]["scenario_id"] == ready["town_skeleton"]["scenario_id"]
        assert body["scenario"]["simulation_package"]["schema_version"] == 2
        snapshot = client.get(f"/api/runs/{body['run']['id']}/snapshots/0")
        assert snapshot.status_code == 200
        assert snapshot.json()["state"]["schema_version"] == 2
        client.post(f"/api/runs/{body['run']['id']}/commands", json={"action": "end"})


def test_missing_draft_and_invalid_input_are_mapped(tmp_path: Path) -> None:
    with client_for(tmp_path) as client:
        missing = client.get("/api/scenario-drafts/missing")
        invalid = client.post("/api/scenario-drafts", json={"population": 99})
        invalid_target = client.post(
            "/api/runs", json={"scenario_id": "demo-city", "draft_id": "missing"}
        )

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "draft_not_found"
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"
    assert invalid_target.status_code == 422
    assert invalid_target.json()["error"]["code"] == "validation_error"
