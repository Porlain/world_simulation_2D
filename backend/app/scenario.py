from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .models import ConnectionConfig, ScenarioConfig


class ScenarioValidationError(ValueError):
    """Raised when a scenario cannot be safely loaded."""


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


@dataclass(frozen=True)
class LoadedScenario:
    config: ScenarioConfig
    checksum: str
    bundle_json: str
    bundle_schema_version: int = 1


def _unique_ids(values: list[str], kind: str) -> None:
    if len(values) != len(set(values)):
        raise ScenarioValidationError(f"duplicate {kind} id")


def _validate_counts(config: ScenarioConfig) -> None:
    flow_ids = {flow.id for flow in config.flow_types}
    location_ids = {location.id for location in config.locations}
    connection_ids = {connection.id for connection in config.connections}
    if len(flow_ids) != len(config.flow_types):
        raise ScenarioValidationError("duplicate flow type id")
    if len(location_ids) != len(config.locations):
        raise ScenarioValidationError("duplicate location id")
    if len(connection_ids) != len(config.connections):
        raise ScenarioValidationError("duplicate connection id")

    for location in config.locations:
        unknown = set(location.initial_counts) - flow_ids
        if unknown:
            raise ScenarioValidationError(
                f"location {location.id} has unknown flow types: {sorted(unknown)}"
            )
        if any(value < 0 for value in location.initial_counts.values()):
            raise ScenarioValidationError(f"location {location.id} has negative count")

    for connection in config.connections:
        if connection.from_location_id not in location_ids:
            raise ScenarioValidationError(
                f"connection {connection.id} has unknown source location"
            )
        if connection.to_location_id not in location_ids:
            raise ScenarioValidationError(
                f"connection {connection.id} has unknown destination location"
            )
        if connection.from_location_id == connection.to_location_id:
            raise ScenarioValidationError(f"connection {connection.id} is a self-loop")
        unknown_capacity = set(connection.capacity_per_tick) - flow_ids
        unknown_demand = set(connection.demand_per_tick) - flow_ids
        if unknown_capacity or unknown_demand:
            unknown = sorted(unknown_capacity | unknown_demand)
            raise ScenarioValidationError(
                f"connection {connection.id} has unknown flow types: {unknown}"
            )
        if any(value < 0 for value in connection.capacity_per_tick.values()):
            raise ScenarioValidationError(f"connection {connection.id} has negative capacity")
        for coordinate in connection.path:
            if len(coordinate) != 2:
                raise ScenarioValidationError(f"connection {connection.id} has invalid path")


def _validate_paths(config: ScenarioConfig) -> None:
    positions = {location.id: tuple(location.position) for location in config.locations}
    for connection in config.connections:
        path = [tuple(point) for point in connection.path]
        if path[0] != positions[connection.from_location_id]:
            raise ScenarioValidationError(
                f"connection {connection.id} path does not start at its source"
            )
        if path[-1] != positions[connection.to_location_id]:
            raise ScenarioValidationError(
                f"connection {connection.id} path does not end at its destination"
            )
        length = sum(
            ((right[0] - left[0]) ** 2 + (right[1] - left[1]) ** 2) ** 0.5
            for left, right in zip(path, path[1:])
        )
        if length <= 0:
            raise ScenarioValidationError(f"connection {connection.id} path has zero length")


def _validate_reachability(config: ScenarioConfig) -> None:
    positive_locations = {
        location.id
        for location in config.locations
        if any(count > 0 for count in location.initial_counts.values())
    }
    adjacency: dict[str, set[str]] = {location.id: set() for location in config.locations}
    for connection in config.connections:
        if any(value > 0 for value in connection.capacity_per_tick.values()):
            adjacency[connection.from_location_id].add(connection.to_location_id)

    for start in positive_locations:
        visited = {start}
        queue = [start]
        while queue:
            current = queue.pop(0)
            for destination in adjacency[current]:
                if destination not in visited:
                    visited.add(destination)
                    queue.append(destination)
        if len(visited) == 1:
            raise ScenarioValidationError(
                f"location {start} has no reachable positive-capacity connection"
            )


def normalize_config(config: ScenarioConfig) -> ScenarioConfig:
    flow_types = sorted(config.flow_types, key=lambda item: item.id)
    locations = sorted(config.locations, key=lambda item: item.id)
    connections = sorted(config.connections, key=lambda item: item.id)
    flow_ids = [flow.id for flow in flow_types]

    normalized_locations = []
    for location in locations:
        counts = {flow_id: location.initial_counts.get(flow_id, 0) for flow_id in flow_ids}
        normalized_locations.append(location.model_copy(update={"initial_counts": counts}))

    normalized_connections: list[ConnectionConfig] = []
    for connection in connections:
        capacities = {
            flow_id: connection.capacity_per_tick.get(flow_id, 0) for flow_id in flow_ids
        }
        demands = {
            flow_id: connection.demand_per_tick.get(flow_id, {"min": 0, "max": 0})
            for flow_id in flow_ids
        }
        normalized_connections.append(
            connection.model_copy(
                update={"capacity_per_tick": capacities, "demand_per_tick": demands}
            )
        )

    return config.model_copy(
        update={
            "flow_types": flow_types,
            "locations": normalized_locations,
            "connections": normalized_connections,
        }
    )


def load_scenario(path: Path) -> LoadedScenario:
    scenario_file = path / "scenario.json"
    if not scenario_file.is_file():
        raise ScenarioValidationError(f"missing scenario.json: {path}")
    try:
        raw = json.loads(scenario_file.read_text(encoding="utf-8"))
        config = ScenarioConfig.model_validate(raw)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise ScenarioValidationError(f"invalid scenario {scenario_file}: {error}") from error

    if config.scenario_id != path.name:
        raise ScenarioValidationError(
            f"scenario_id {config.scenario_id!r} does not match directory {path.name!r}"
        )
    _validate_counts(config)
    _validate_paths(config)
    _validate_reachability(config)
    normalized = normalize_config(config)
    bundle_json = canonical_json(normalized.model_dump(mode="json"))
    checksum = sha256(bundle_json.encode("utf-8")).hexdigest()
    return LoadedScenario(config=normalized, checksum=checksum, bundle_json=bundle_json)


class ScenarioCatalog:
    def __init__(self, scenarios: dict[str, LoadedScenario]):
        self._scenarios = dict(scenarios)

    @classmethod
    def load_all(cls, directory: Path) -> "ScenarioCatalog":
        if not directory.is_dir():
            raise ScenarioValidationError(f"missing scenario directory: {directory}")
        scenarios: dict[str, LoadedScenario] = {}
        for path in sorted(directory.iterdir(), key=lambda item: item.name):
            if not path.is_dir():
                continue
            loaded = load_scenario(path)
            if loaded.config.scenario_id in scenarios:
                raise ScenarioValidationError(f"duplicate scenario id: {loaded.config.scenario_id}")
            scenarios[loaded.config.scenario_id] = loaded
        if not scenarios:
            raise ScenarioValidationError(f"no scenarios found in {directory}")
        return cls(scenarios)

    def get(self, scenario_id: str) -> LoadedScenario | None:
        return self._scenarios.get(scenario_id)

    def all(self) -> list[LoadedScenario]:
        return [self._scenarios[key] for key in sorted(self._scenarios)]
