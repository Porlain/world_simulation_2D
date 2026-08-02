from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .drafts import (
    DraftCapacityReached,
    DraftManager,
    DraftNotFound,
    DraftNotReady,
    ScenarioCompileFailed,
    loaded_scenario_from_draft,
)
from .models import RunCommandRequest, RunCreateRequest, TownGenerationRequest
from .runs import EngineHost, RunNotActive, ScenarioNotFound
from .scenario import ScenarioCatalog, ScenarioValidationError
from .storage import (
    ActiveRunExists,
    RunNotFound,
    SnapshotNotFound,
    StaleRunState,
    Storage,
    StorageError,
)
from .town import TownGenerationError


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_path(value: str | Path | None, default: Path) -> Path:
    if value is None:
        return default
    path = Path(value)
    return path if path.is_absolute() else Path.cwd() / path


def resolve_paths(
    db_path: str | Path | None = None,
    scenario_dir: str | Path | None = None,
    static_dir: str | Path | None = None,
) -> tuple[Path, Path, Path]:
    root = _project_root()
    return (
        _resolve_path(db_path or os.environ.get("FLOW_DB_PATH"), root / "data" / "flow.sqlite3"),
        _resolve_path(scenario_dir or os.environ.get("FLOW_SCENARIO_DIR"), root / "scenarios"),
        _resolve_path(static_dir or os.environ.get("FLOW_STATIC_DIR"), root / "frontend" / "dist"),
    )


def _error(code: str, message: str, status_code: int, details: dict[str, Any] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


def _record_payload(record) -> dict[str, Any]:
    return asdict(record)


def _scenario_payload(loaded) -> dict[str, Any]:
    return {"config": loaded.config.model_dump(mode="json"), "checksum": loaded.checksum}


def _detail_payload(detail, include_scenario: bool) -> dict[str, Any]:
    scenario = None
    if include_scenario and detail.scenario_bundle_json is not None:
        raw_bundle = json.loads(detail.scenario_bundle_json)
        if raw_bundle.get("schema_version") == 2:
            scenario = {
                "config": raw_bundle["config"],
                "checksum": detail.run.scenario_checksum,
                "town_skeleton": raw_bundle["town_skeleton"],
                "simulation_package": raw_bundle["simulation_package"],
                "bundle_checksum": detail.run.scenario_checksum,
            }
        else:
            scenario = {"config": raw_bundle, "checksum": detail.run.scenario_checksum}
    return {
        "run": _record_payload(detail.run),
        "scenario": scenario,
        "tick_range": {"min": detail.tick_min, "max": detail.tick_max},
        "latest_snapshot": {
            "run_id": detail.run.id,
            "tick": detail.latest_snapshot.tick,
            "state": detail.latest_snapshot.model_dump(mode="json"),
        },
    }


def create_app(
    db_path: str | Path | None = None,
    scenario_dir: str | Path | None = None,
    static_dir: str | Path | None = None,
) -> FastAPI:
    resolved_db, resolved_scenarios, resolved_static = resolve_paths(
        db_path, scenario_dir, static_dir
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        storage = Storage(resolved_db)

        async def prepare_storage() -> Storage:
            await asyncio.to_thread(storage.initialize)
            await asyncio.to_thread(storage.recover_interrupted_runs)
            return storage

        storage_task = asyncio.create_task(prepare_storage())
        catalog_task = asyncio.create_task(
            asyncio.to_thread(ScenarioCatalog.load_all, resolved_scenarios)
        )
        storage, catalog = await asyncio.gather(storage_task, catalog_task)
        controller = EngineHost(storage, catalog)
        drafts = DraftManager()
        await controller.start_scheduler()
        application.state.storage = storage
        application.state.catalog = catalog
        application.state.controller = controller
        application.state.drafts = drafts
        application.state.storage_ready = True
        application.state.catalog_ready = True
        try:
            yield
        finally:
            await drafts.close()
            await controller.stop_scheduler()

    application = FastAPI(title="World Simulation 2D API", lifespan=lifespan)

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exception: RequestValidationError):
        errors = jsonable_encoder(exception.errors(), exclude={"ctx"})
        return _error("validation_error", "The request is invalid.", 422, {"errors": errors})

    @application.exception_handler(ScenarioValidationError)
    async def scenario_error_handler(_: Request, exception: ScenarioValidationError):
        return _error("scenario_invalid", str(exception), 500)

    @application.exception_handler(TownGenerationError)
    async def town_generation_error_handler(_: Request, exception: TownGenerationError):
        return _error("scenario_generation_failed", str(exception), 500)

    @application.exception_handler(DraftNotFound)
    async def draft_not_found_handler(_: Request, exception: DraftNotFound):
        return _error("draft_not_found", "Scenario draft not found.", 404, {"draft_id": str(exception)})

    @application.exception_handler(DraftCapacityReached)
    async def draft_capacity_handler(_: Request, exception: DraftCapacityReached):
        return _error("draft_capacity_reached", str(exception), 429)

    @application.exception_handler(DraftNotReady)
    async def draft_not_ready_handler(_: Request, exception: DraftNotReady):
        return _error("draft_not_ready", "Scenario draft is still compiling.", 409, {"draft_id": str(exception)})

    @application.exception_handler(ScenarioCompileFailed)
    async def scenario_compile_failed_handler(_: Request, exception: ScenarioCompileFailed):
        return _error("scenario_compile_failed", "Scenario draft compilation failed.", 422, {"draft_id": str(exception)})

    @application.exception_handler(ScenarioNotFound)
    async def scenario_not_found_handler(_: Request, exception: ScenarioNotFound):
        return _error("scenario_not_found", "Scenario not found.", 404, {"scenario_id": str(exception)})

    @application.exception_handler(RunNotFound)
    async def run_not_found_handler(_: Request, exception: RunNotFound):
        return _error("run_not_found", "Run not found.", 404, {"run_id": str(exception)})

    @application.exception_handler(SnapshotNotFound)
    async def snapshot_not_found_handler(_: Request, exception: SnapshotNotFound):
        return _error("snapshot_not_found", "Snapshot not found.", 404)

    @application.exception_handler(ActiveRunExists)
    async def active_run_handler(_: Request, exception: ActiveRunExists):
        return _error("active_run_exists", str(exception), 409)

    @application.exception_handler(RunNotActive)
    async def run_not_active_handler(_: Request, exception: RunNotActive):
        return _error("run_not_active", "The run is not active.", 409, {"run_id": str(exception)})

    @application.exception_handler(StaleRunState)
    async def stale_run_handler(_: Request, exception: StaleRunState):
        return _error("stale_run_state", str(exception), 409)

    @application.exception_handler(StorageError)
    async def storage_error_handler(_: Request, exception: StorageError):
        return _error("storage_error", "The database operation failed.", 500)

    @application.get("/api/health")
    async def health(request: Request):
        controller: EngineHost = request.app.state.controller
        storage_ready = bool(getattr(request.app.state, "storage_ready", False))
        catalog_ready = bool(getattr(request.app.state, "catalog_ready", False))
        ready = storage_ready and catalog_ready and controller.status not in {"booting", "stopped"}
        payload = {
            "status": "ok" if ready else "unavailable",
            "engine_host": controller.status,
            "storage": "ready" if storage_ready else "booting",
            "catalog": "ready" if catalog_ready else "booting",
        }
        return JSONResponse(status_code=200 if ready else 503, content=payload)

    @application.get("/api/scenarios")
    async def list_scenarios(request: Request):
        controller: EngineHost = request.app.state.controller
        return {"items": [_scenario_payload(scenario) for scenario in await controller.list_scenarios()]}

    @application.post("/api/scenario-drafts", status_code=202)
    async def create_scenario_draft(payload: TownGenerationRequest, request: Request):
        drafts: DraftManager = request.app.state.drafts
        draft = await drafts.create(payload)
        return draft.payload()

    @application.get("/api/scenario-drafts/{draft_id}")
    async def get_scenario_draft(draft_id: str, request: Request):
        drafts: DraftManager = request.app.state.drafts
        return (await drafts.get(draft_id)).payload()

    @application.post("/api/runs", status_code=201)
    async def create_run(payload: RunCreateRequest, request: Request):
        controller: EngineHost = request.app.state.controller
        if payload.draft_id is not None:
            drafts: DraftManager = request.app.state.drafts
            draft = await drafts.get(payload.draft_id)
            scenario = loaded_scenario_from_draft(draft)
            active = await controller.start_loaded(scenario, payload.resolved_seed)
        else:
            active = await controller.start(payload.scenario_id, payload.resolved_seed)  # type: ignore[arg-type]
        detail = await controller.get_detail(active.run.id, include_scenario=True)
        return _detail_payload(detail, include_scenario=True)

    @application.get("/api/runs")
    async def list_runs(request: Request, limit: int = Query(default=20, ge=1, le=100)):
        controller: EngineHost = request.app.state.controller
        records = await controller.list_runs(limit)
        return {"items": [_record_payload(record) for record in records]}

    @application.get("/api/runs/{run_id}")
    async def get_run(run_id: str, request: Request, include_scenario: bool = False):
        controller: EngineHost = request.app.state.controller
        detail = await controller.get_detail(run_id, include_scenario)
        return _detail_payload(detail, include_scenario)

    @application.post("/api/runs/{run_id}/commands")
    async def command_run(run_id: str, payload: RunCommandRequest, request: Request):
        controller: EngineHost = request.app.state.controller
        record = await controller.command(run_id, payload)
        return {"run": _record_payload(record)}

    @application.get("/api/runs/{run_id}/snapshots/{tick}")
    async def get_snapshot(run_id: str, tick: int, request: Request):
        if tick < 0:
            raise SnapshotNotFound(f"{run_id}:{tick}")
        controller: EngineHost = request.app.state.controller
        state = await controller.get_snapshot(run_id, tick)
        return {"run_id": run_id, "tick": state.tick, "state": state.model_dump(mode="json")}

    if resolved_static.joinpath("index.html").is_file():
        application.mount("/", StaticFiles(directory=resolved_static, html=True), name="ui")

    return application


app = create_app()
