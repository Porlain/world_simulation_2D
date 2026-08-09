from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .models import FlowSnapshot, SnapshotState
from .scenario import LoadedScenario, canonical_json

Snapshot = SnapshotState | FlowSnapshot


def parse_snapshot(raw: object) -> Snapshot:
    if isinstance(raw, dict) and raw.get("schema_version") == 2:
        return FlowSnapshot.model_validate(raw)
    return SnapshotState.model_validate(raw)


class StorageError(RuntimeError):
    """Base class for persistence failures."""


class ActiveRunExists(StorageError):
    pass


class RunNotFound(StorageError):
    pass


class SnapshotNotFound(StorageError):
    pass


class StaleRunState(StorageError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class RunRecord:
    id: str
    scenario_id: str
    scenario_name: str | None
    scenario_schema_version: int
    scenario_checksum: str
    seed: int
    status: str
    rate: float
    current_tick: int
    started_at: str
    ended_at: str | None
    error_code: str | None
    error_message: str | None


@dataclass(frozen=True)
class RunDetail:
    run: RunRecord
    scenario_bundle_json: str | None
    tick_min: int
    tick_max: int
    latest_snapshot: Snapshot


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL,
    scenario_schema_version INTEGER NOT NULL CHECK (scenario_schema_version >= 1),
    scenario_checksum TEXT NOT NULL CHECK (length(scenario_checksum) = 64),
    scenario_bundle_json TEXT NOT NULL,
    seed INTEGER NOT NULL CHECK (seed BETWEEN 0 AND 9007199254740991),
    status TEXT NOT NULL CHECK (status IN ('running', 'paused', 'ended', 'failed')),
    rate REAL NOT NULL DEFAULT 1.0 CHECK (rate IN (0.5, 1.0, 2.0, 4.0)),
    current_tick INTEGER NOT NULL DEFAULT 0 CHECK (current_tick >= 0),
    started_at TEXT NOT NULL,
    ended_at TEXT,
    error_code TEXT,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS tick_snapshots (
    run_id TEXT NOT NULL,
    tick INTEGER NOT NULL CHECK (tick >= 0),
    state_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, tick),
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs(started_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_single_active
ON runs((1))
WHERE status IN ('running', 'paused');
"""


class Storage:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                connection.executescript(SCHEMA_SQL)
                connection.execute("PRAGMA user_version = 1")
            elif version != 1:
                raise StorageError(f"unsupported database version: {version}")

    def recover_interrupted_runs(self) -> int:
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE runs
                SET status = 'failed', ended_at = ?, error_code = 'process_interrupted',
                    error_message = 'The process stopped before the run ended.'
                WHERE status IN ('running', 'paused')
                """,
                (now,),
            )
            return cursor.rowcount

    def create_run(
        self,
        scenario: LoadedScenario,
        seed: int,
        initial_state: Snapshot,
        started_at: str | None = None,
    ) -> RunRecord:
        run_id = uuid4().hex
        timestamp = started_at or utc_now()
        state_json = canonical_json(initial_state.model_dump(mode="json"))
        try:
            with self.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    connection.execute(
                        """
                        INSERT INTO runs (
                            id, scenario_id, scenario_schema_version, scenario_checksum,
                            scenario_bundle_json, seed, status, rate, current_tick, started_at
                        ) VALUES (?, ?, ?, ?, ?, ?, 'running', 1.0, 0, ?)
                        """,
                        (
                            run_id,
                            scenario.config.scenario_id,
                            scenario.bundle_schema_version,
                            scenario.checksum,
                            scenario.bundle_json,
                            seed,
                            timestamp,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO tick_snapshots(run_id, tick, state_json, created_at)
                        VALUES (?, 0, ?, ?)
                        """,
                        (run_id, state_json, timestamp),
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
        except sqlite3.IntegrityError as error:
            if "idx_runs_single_active" in str(error) or "UNIQUE constraint failed: index" in str(error):
                raise ActiveRunExists("another run is already active") from error
            raise StorageError(str(error)) from error
        return self.get_run(run_id)

    def list_runs(self, limit: int = 20) -> list[RunRecord]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id, scenario_id, scenario_schema_version, scenario_checksum,
                       scenario_bundle_json,
                       seed, status, rate, current_tick, started_at, ended_at,
                       error_code, error_message
                FROM runs ORDER BY started_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._record(row) for row in rows]

    def get_run(self, run_id: str) -> RunRecord:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, scenario_id, scenario_schema_version, scenario_checksum,
                       scenario_bundle_json,
                       seed, status, rate, current_tick, started_at, ended_at,
                       error_code, error_message
                FROM runs WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            raise RunNotFound(run_id)
        return self._record(row)

    def get_detail(self, run_id: str, include_scenario: bool = False) -> RunDetail:
        run = self.get_run(run_id)
        with self.connect() as connection:
            bounds = connection.execute(
                "SELECT MIN(tick) AS tick_min, MAX(tick) AS tick_max FROM tick_snapshots WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            latest = connection.execute(
                "SELECT state_json FROM tick_snapshots WHERE run_id = ? ORDER BY tick DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            bundle = connection.execute(
                "SELECT scenario_bundle_json FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
        if latest is None or bounds["tick_min"] is None:
            raise SnapshotNotFound(run_id)
        return RunDetail(
            run=run,
            scenario_bundle_json=bundle["scenario_bundle_json"] if include_scenario else None,
            tick_min=int(bounds["tick_min"]),
            tick_max=int(bounds["tick_max"]),
            latest_snapshot=parse_snapshot(json.loads(latest["state_json"])),
        )

    def get_snapshot(self, run_id: str, tick: int) -> Snapshot:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT state_json FROM tick_snapshots WHERE run_id = ? AND tick = ?",
                (run_id, tick),
            ).fetchone()
        if row is None:
            raise SnapshotNotFound(f"{run_id}:{tick}")
        return parse_snapshot(json.loads(row["state_json"]))

    def get_latest_snapshot(self, run_id: str) -> Snapshot:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT state_json FROM tick_snapshots WHERE run_id = ? ORDER BY tick DESC LIMIT 1",
                (run_id,),
            ).fetchone()
        if row is None:
            raise SnapshotNotFound(run_id)
        return parse_snapshot(json.loads(row["state_json"]))

    def commit_tick(
        self,
        run_id: str,
        expected_tick: int,
        next_state: Snapshot,
        created_at: str | None = None,
    ) -> None:
        if next_state.tick != expected_tick + 1:
            raise StaleRunState("next tick does not follow expected tick")
        timestamp = created_at or utc_now()
        state_json = canonical_json(next_state.model_dump(mode="json"))
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    "INSERT INTO tick_snapshots(run_id, tick, state_json, created_at) VALUES (?, ?, ?, ?)",
                    (run_id, next_state.tick, state_json, timestamp),
                )
                cursor = connection.execute(
                    """
                    UPDATE runs SET current_tick = ?
                    WHERE id = ? AND status = 'running' AND current_tick = ?
                    """,
                    (next_state.tick, run_id, expected_tick),
                )
                if cursor.rowcount != 1:
                    raise StaleRunState(run_id)
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def set_status(
        self,
        run_id: str,
        allowed_from: tuple[str, ...],
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> RunRecord:
        if status not in {"running", "paused", "ended", "failed"}:
            raise ValueError(f"invalid status: {status}")
        ended_at = utc_now() if status in {"ended", "failed"} else None
        placeholders = ",".join("?" for _ in allowed_from)
        values: list[object] = [status, ended_at, error_code, error_message, run_id, *allowed_from]
        with self.connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE runs SET status = ?, ended_at = ?, error_code = ?, error_message = ?
                WHERE id = ? AND status IN ({placeholders})
                """,
                values,
            )
            if cursor.rowcount != 1:
                try:
                    return self.get_run(run_id)
                except RunNotFound:
                    raise
                except Exception as error:
                    raise StaleRunState(run_id) from error
        return self.get_run(run_id)

    def set_rate(self, run_id: str, rate: float) -> RunRecord:
        if rate not in {0.5, 1.0, 2.0, 4.0}:
            raise ValueError("unsupported rate")
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE runs SET rate = ? WHERE id = ? AND status IN ('running', 'paused')",
                (rate, run_id),
            )
            if cursor.rowcount != 1:
                self.get_run(run_id)
                raise StaleRunState(run_id)
        return self.get_run(run_id)

    @staticmethod
    def _record(row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            id=row["id"],
            scenario_id=row["scenario_id"],
            scenario_name=Storage._scenario_name(row["scenario_bundle_json"]),
            scenario_schema_version=row["scenario_schema_version"],
            scenario_checksum=row["scenario_checksum"],
            seed=row["seed"],
            status=row["status"],
            rate=row["rate"],
            current_tick=row["current_tick"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            error_code=row["error_code"],
            error_message=row["error_message"],
        )

    @staticmethod
    def _scenario_name(bundle_json: str | None) -> str | None:
        if not bundle_json:
            return None
        try:
            payload = json.loads(bundle_json)
            name = payload.get("town_skeleton", {}).get("name") or payload.get("config", {}).get("name")
            return str(name) if name else None
        except (TypeError, ValueError, AttributeError):
            return None
