from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass

from .engine import SimulationInvariantError, initial_state, step
from .models import RunCommandRequest, SnapshotState
from .scenario import LoadedScenario, ScenarioCatalog
from .storage import (
    ActiveRunExists,
    RunDetail,
    RunNotFound,
    RunRecord,
    Storage,
    StorageError,
)


class ScenarioNotFound(RuntimeError):
    pass


class RunNotActive(RuntimeError):
    pass


@dataclass
class ActiveRun:
    run: RunRecord
    scenario: LoadedScenario
    state: SnapshotState


class RunController:
    def __init__(self, storage: Storage, catalog: ScenarioCatalog):
        self.storage = storage
        self.catalog = catalog
        self.active_run: ActiveRun | None = None
        self.lock = asyncio.Lock()
        self.wake_event = asyncio.Event()
        self.shutting_down = False
        self.scheduler_task: asyncio.Task[None] | None = None

    async def start_scheduler(self) -> None:
        if self.scheduler_task is not None:
            return
        self.shutting_down = False
        self.scheduler_task = asyncio.create_task(self._scheduler_loop())

    async def stop_scheduler(self) -> None:
        self.shutting_down = True
        self.wake_event.set()
        if self.scheduler_task is not None:
            await self.scheduler_task
            self.scheduler_task = None
        async with self.lock:
            if self.active_run is not None:
                active = self.active_run
                try:
                    active.run = await asyncio.to_thread(
                        self.storage.set_status,
                        active.run.id,
                        ("running", "paused"),
                        "failed",
                        "process_stopped",
                        "The server stopped before the run ended.",
                    )
                except Exception:
                    pass
                self.active_run = None

    async def start(self, scenario_id: str, seed: int | None = None) -> ActiveRun:
        scenario = self.catalog.get(scenario_id)
        if scenario is None:
            raise ScenarioNotFound(scenario_id)
        return await self.start_loaded(scenario, seed)

    async def start_loaded(self, scenario: LoadedScenario, seed: int | None = None) -> ActiveRun:
        async with self.lock:
            if self.active_run is not None:
                raise ActiveRunExists("another run is already active")
            actual_seed = seed if seed is not None else secrets.randbits(53)
            state = initial_state(scenario.config)
            run = await asyncio.to_thread(
                self.storage.create_run, scenario, actual_seed, state
            )
            self.active_run = ActiveRun(run=run, scenario=scenario, state=state)
            self.wake_event.set()
            return self.active_run

    async def command(self, run_id: str, request: RunCommandRequest) -> RunRecord:
        async with self.lock:
            active = self.active_run
            if active is None or active.run.id != run_id:
                try:
                    await asyncio.to_thread(self.storage.get_run, run_id)
                except RunNotFound:
                    raise
                raise RunNotActive(run_id)

            current = active.run.status
            if request.action == "pause":
                if current == "paused":
                    return active.run
                if current != "running":
                    raise RunNotActive(run_id)
                active.run = await asyncio.to_thread(
                    self.storage.set_status, run_id, ("running",), "paused"
                )
            elif request.action == "resume":
                if current == "running":
                    return active.run
                if current != "paused":
                    raise RunNotActive(run_id)
                active.run = await asyncio.to_thread(
                    self.storage.set_status, run_id, ("paused",), "running"
                )
            elif request.action == "end":
                if current not in {"running", "paused"}:
                    raise RunNotActive(run_id)
                active.run = await asyncio.to_thread(
                    self.storage.set_status,
                    run_id,
                    ("running", "paused"),
                    "ended",
                )
                self.active_run = None
            elif request.action == "set_rate":
                active.run = await asyncio.to_thread(
                    self.storage.set_rate, run_id, float(request.rate)
                )
            else:
                raise ValueError(f"unknown command: {request.action}")
            self.wake_event.set()
            return active.run

    async def get_detail(self, run_id: str, include_scenario: bool = False) -> RunDetail:
        return await asyncio.to_thread(self.storage.get_detail, run_id, include_scenario)

    async def get_snapshot(self, run_id: str, tick: int) -> SnapshotState:
        return await asyncio.to_thread(self.storage.get_snapshot, run_id, tick)

    async def list_runs(self, limit: int = 20) -> list[RunRecord]:
        return await asyncio.to_thread(self.storage.list_runs, limit)

    async def list_scenarios(self) -> list[LoadedScenario]:
        return self.catalog.all()

    async def _scheduler_loop(self) -> None:
        while not self.shutting_down:
            active = self.active_run
            if active is None or active.run.status != "running":
                await self.wake_event.wait()
                self.wake_event.clear()
                continue

            interval = active.scenario.config.tick_seconds / active.run.rate
            try:
                await asyncio.wait_for(self.wake_event.wait(), timeout=interval)
                self.wake_event.clear()
                continue
            except asyncio.TimeoutError:
                pass

            async with self.lock:
                if self.shutting_down or self.active_run is None:
                    continue
                active = self.active_run
                if active.run.status != "running":
                    continue
                try:
                    next_state = await asyncio.to_thread(
                        self._compute_and_commit_sync, active
                    )
                except Exception as error:
                    await self._fail_active(active, error)
                    self.active_run = None
                    continue
                active.state = next_state
                active.run = await asyncio.to_thread(self.storage.get_run, active.run.id)

            # A slow tick must not cause a burst of concurrent work. The next
            # loop always waits one fresh interval from the committed tick.

    def _compute_and_commit_sync(self, active: ActiveRun) -> SnapshotState:
        next_state = step(active.scenario.config, active.state, active.run.seed)
        self.storage.commit_tick(active.run.id, active.state.tick, next_state)
        return next_state

    async def _fail_active(self, active: ActiveRun, error: Exception) -> None:
        if isinstance(error, SimulationInvariantError):
            code = "simulation_failed"
            message = "The simulation invariant failed."
        elif isinstance(error, StorageError):
            code = "storage_error"
            message = "The database could not commit the tick."
        else:
            code = "simulation_failed"
            message = "The simulation stopped because of an unexpected error."
        try:
            active.run = await asyncio.to_thread(
                self.storage.set_status,
                active.run.id,
                ("running", "paused"),
                "failed",
                code,
                message,
            )
        except Exception:
            pass
