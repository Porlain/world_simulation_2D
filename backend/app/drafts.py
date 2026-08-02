from __future__ import annotations

import asyncio
from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4

from .flow import FlowCompileError, compile_flow
from .models import SimulationPackage, TownGenerationRequest, TownSkeleton
from .scenario import canonical_json
from .town import generate_town, town_skeleton_checksum

MAX_DRAFTS = 8


class DraftError(RuntimeError):
    pass


class DraftNotFound(DraftError):
    pass


class DraftCapacityReached(DraftError):
    pass


@dataclass
class ScenarioDraft:
    id: str
    town_skeleton: TownSkeleton
    skeleton_checksum: str
    compile_status: str = "compiling"
    simulation_package: SimulationPackage | None = None
    bundle_checksum: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    def payload(self) -> dict[str, object]:
        return {
            "draft_id": self.id,
            "generation_seed": self.town_skeleton.generation_seed,
            "skeleton_checksum": self.skeleton_checksum,
            "compile_status": self.compile_status,
            "town_skeleton": self.town_skeleton.model_dump(mode="json"),
            "simulation_package": (
                self.simulation_package.model_dump(mode="json")
                if self.simulation_package is not None
                else None
            ),
            "bundle_checksum": self.bundle_checksum,
            "error": (
                {"code": self.error_code, "message": self.error_message}
                if self.error_code is not None
                else None
            ),
        }


def bundle_payload(town: TownSkeleton, package: SimulationPackage) -> dict[str, object]:
    return {
        "schema_version": 2,
        "source_metadata": {
            "kind": "generated",
            "version": town.generator_version,
            "generation_seed": town.generation_seed,
            "population": town.requested_population,
        },
        "town_skeleton": town.model_dump(mode="json"),
        "simulation_package": package.model_dump(mode="json"),
    }


def bundle_checksum(town: TownSkeleton, package: SimulationPackage) -> str:
    return sha256(canonical_json(bundle_payload(town, package)).encode("utf-8")).hexdigest()


class DraftManager:
    def __init__(self, max_drafts: int = MAX_DRAFTS):
        self.max_drafts = max_drafts
        self._drafts: dict[str, ScenarioDraft] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    async def create(self, request: TownGenerationRequest) -> ScenarioDraft:
        async with self._lock:
            self._prune_finished()
            if len(self._drafts) >= self.max_drafts:
                raise DraftCapacityReached("draft capacity reached")
            town = await asyncio.to_thread(generate_town, request)
            draft = ScenarioDraft(
                id=uuid4().hex,
                town_skeleton=town,
                skeleton_checksum=town_skeleton_checksum(town),
            )
            self._drafts[draft.id] = draft
            task = asyncio.create_task(self._compile(draft.id, town))
            self._tasks[draft.id] = task
            return draft

    async def get(self, draft_id: str) -> ScenarioDraft:
        async with self._lock:
            draft = self._drafts.get(draft_id)
            if draft is None:
                raise DraftNotFound(draft_id)
            return draft

    async def close(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._drafts.clear()

    def _prune_finished(self) -> None:
        finished = [
            draft_id
            for draft_id, draft in self._drafts.items()
            if draft.compile_status in {"ready", "failed"}
        ]
        for draft_id in finished[: max(0, len(self._drafts) - self.max_drafts + 1)]:
            self._drafts.pop(draft_id, None)
            self._tasks.pop(draft_id, None)

    async def _compile(self, draft_id: str, town: TownSkeleton) -> None:
        try:
            package = await asyncio.to_thread(compile_flow, town)
            checksum = bundle_checksum(town, package)
            async with self._lock:
                draft = self._drafts.get(draft_id)
                if draft is not None:
                    draft.simulation_package = package
                    draft.bundle_checksum = checksum
                    draft.compile_status = "ready"
        except asyncio.CancelledError:
            raise
        except FlowCompileError as error:
            async with self._lock:
                draft = self._drafts.get(draft_id)
                if draft is not None:
                    draft.compile_status = "failed"
                    draft.error_code = "scenario_compile_failed"
                    draft.error_message = str(error)
        except Exception:
            async with self._lock:
                draft = self._drafts.get(draft_id)
                if draft is not None:
                    draft.compile_status = "failed"
                    draft.error_code = "scenario_compile_failed"
                    draft.error_message = "The generated town could not be compiled."
