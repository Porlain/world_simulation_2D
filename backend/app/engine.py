from __future__ import annotations

from copy import deepcopy
from hashlib import sha256

from .models import ConnectionActivity, ScenarioConfig, SnapshotState


class SimulationInvariantError(ValueError):
    """Raised when a tick would violate simulation conservation rules."""


def stable_int(
    seed: int,
    tick: int,
    connection_id: str,
    flow_type: str,
    minimum: int,
    maximum: int,
) -> int:
    if minimum < 0 or maximum < minimum:
        raise ValueError("invalid stable_int range")
    payload = f"{seed}:{tick}:{connection_id}:{flow_type}".encode("utf-8")
    number = int.from_bytes(sha256(payload).digest()[:8], "big")
    return minimum + number % (maximum - minimum + 1)


def allocate(planned: dict[str, int], available: int) -> dict[str, int]:
    if available < 0 or any(amount < 0 for amount in planned.values()):
        raise ValueError("planned and available values must be non-negative")
    total = sum(planned.values())
    if total <= available:
        return dict(planned)
    if available == 0 or total == 0:
        return {connection_id: 0 for connection_id in planned}

    allocated: dict[str, int] = {}
    remainders: list[tuple[int, str]] = []
    for connection_id, amount in planned.items():
        base, remainder = divmod(amount * available, total)
        allocated[connection_id] = base
        remainders.append((remainder, connection_id))

    missing = available - sum(allocated.values())
    for _, connection_id in sorted(remainders, key=lambda item: (-item[0], item[1]))[:missing]:
        allocated[connection_id] += 1
    return allocated


def initial_state(scenario: ScenarioConfig) -> SnapshotState:
    flow_ids = [flow.id for flow in scenario.flow_types]
    location_counts = {
        location.id: {flow_id: location.initial_counts.get(flow_id, 0) for flow_id in flow_ids}
        for location in scenario.locations
    }
    transit_buckets = {
        connection.id: {
            flow_id: [0] * connection.travel_time_ticks for flow_id in flow_ids
        }
        for connection in scenario.connections
    }
    activity = {
        connection.id: {
            flow_id: ConnectionActivity(departed=0, arrived=0) for flow_id in flow_ids
        }
        for connection in scenario.connections
    }
    totals = {
        flow_id: sum(counts[flow_id] for counts in location_counts.values())
        for flow_id in flow_ids
    }
    state = SnapshotState(
        tick=0,
        location_counts=location_counts,
        transit_buckets=transit_buckets,
        connection_activity=activity,
        totals=totals,
    )
    assert_invariants(None, state, scenario)
    return state


def _total_in_state(state: SnapshotState, flow_id: str) -> int:
    locations = sum(counts.get(flow_id, 0) for counts in state.location_counts.values())
    transit = sum(
        sum(buckets.get(flow_id, [])) for buckets in state.transit_buckets.values()
    )
    return locations + transit


def assert_invariants(
    previous: SnapshotState | None,
    state: SnapshotState,
    scenario: ScenarioConfig,
) -> None:
    connection_by_id = {connection.id: connection for connection in scenario.connections}
    flow_ids = [flow.id for flow in scenario.flow_types]
    if previous is not None and state.tick != previous.tick + 1:
        raise SimulationInvariantError("tick must advance by one")
    for flow_id in flow_ids:
        if state.totals.get(flow_id) != _total_in_state(state, flow_id):
            raise SimulationInvariantError(f"totals mismatch for {flow_id}")
    for location_counts in state.location_counts.values():
        for flow_id in flow_ids:
            if location_counts.get(flow_id, 0) < 0:
                raise SimulationInvariantError("negative location count")
    for connection_id, buckets_by_flow in state.transit_buckets.items():
        connection = connection_by_id[connection_id]
        for flow_id in flow_ids:
            buckets = buckets_by_flow[flow_id]
            if len(buckets) != connection.travel_time_ticks:
                raise SimulationInvariantError("transit bucket length mismatch")
            if any(value < 0 for value in buckets):
                raise SimulationInvariantError("negative transit count")
            activity = state.connection_activity[connection_id][flow_id]
            if activity.departed < 0 or activity.arrived < 0:
                raise SimulationInvariantError("negative activity")
            if activity.departed > connection.capacity_per_tick.get(flow_id, 0):
                raise SimulationInvariantError("connection capacity exceeded")
    if previous is not None:
        for flow_id in flow_ids:
            if _total_in_state(previous, flow_id) != _total_in_state(state, flow_id):
                raise SimulationInvariantError(f"population is not conserved for {flow_id}")


def step(scenario: ScenarioConfig, previous: SnapshotState, seed: int) -> SnapshotState:
    state = previous.model_copy(deep=True)
    state.tick = previous.tick + 1
    flow_ids = [flow.id for flow in scenario.flow_types]
    connection_by_id = {connection.id: connection for connection in scenario.connections}
    location_by_id = {location.id: location for location in scenario.locations}
    outgoing: dict[str, list] = {location.id: [] for location in scenario.locations}
    for connection in sorted(scenario.connections, key=lambda item: item.id):
        outgoing[connection.from_location_id].append(connection)
        for flow_id in flow_ids:
            state.connection_activity[connection.id][flow_id] = ConnectionActivity(
                departed=0, arrived=0
            )

    for connection in sorted(scenario.connections, key=lambda item: item.id):
        for flow_id in flow_ids:
            buckets = state.transit_buckets[connection.id][flow_id]
            arrived = buckets.pop(0)
            buckets.append(0)
            state.location_counts[connection.to_location_id][flow_id] += arrived
            state.connection_activity[connection.id][flow_id].arrived = arrived

    for source_id in sorted(outgoing):
        for flow_id in flow_ids:
            available = state.location_counts[source_id][flow_id]
            planned: dict[str, int] = {}
            for connection in outgoing[source_id]:
                demand = connection.demand_per_tick[flow_id]
                requested = stable_int(
                    seed,
                    state.tick,
                    connection.id,
                    flow_id,
                    demand.min,
                    demand.max,
                )
                planned[connection.id] = min(
                    requested, connection.capacity_per_tick[flow_id]
                )
            actual = allocate(planned, available)
            for connection in outgoing[source_id]:
                amount = actual[connection.id]
                state.location_counts[source_id][flow_id] -= amount
                state.transit_buckets[connection.id][flow_id][-1] += amount
                state.connection_activity[connection.id][flow_id].departed = amount

    state.totals = {flow_id: _total_in_state(state, flow_id) for flow_id in flow_ids}
    assert_invariants(previous, state, scenario)
    return state
