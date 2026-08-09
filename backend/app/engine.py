from __future__ import annotations

from bisect import bisect_left
from copy import deepcopy
from collections import deque
from dataclasses import dataclass
from hashlib import sha256
from math import hypot

from .models import (
    ConnectionActivity,
    ConnectionSnapshot,
    FlowConnection,
    FlowSnapshot,
    ScenarioConfig,
    SimulationPackage,
    SnapshotState,
    StreetSnapshot,
)


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


def departure_budget(available: int, flow_id: str, initial_count: int) -> int:
    # Keep half of the initial people at their location while vehicles use full capacity.
    if flow_id in {"pedestrian", "citizen"}:
        reserve = max(1, initial_count // 2)
        return max(0, available - reserve)
    return available


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
            actual = allocate(
                planned,
                departure_budget(
                    available,
                    flow_id,
                    location_by_id[source_id].initial_counts.get(flow_id, 0),
                ),
            )
            for connection in outgoing[source_id]:
                amount = actual[connection.id]
                state.location_counts[source_id][flow_id] -= amount
                state.transit_buckets[connection.id][flow_id][-1] += amount
                state.connection_activity[connection.id][flow_id].departed = amount

    state.totals = {flow_id: _total_in_state(state, flow_id) for flow_id in flow_ids}
    assert_invariants(previous, state, scenario)
    return state


@dataclass
class SimulationState:
    tick: int
    location_counts: dict[str, dict[str, int]]
    transit_queues: dict[str, dict[str, deque[int]]]
    connection_activity: dict[str, dict[str, ConnectionActivity]]
    totals: dict[str, int]


def _flow_total(state: SimulationState, flow_id: str) -> int:
    locations = sum(counts.get(flow_id, 0) for counts in state.location_counts.values())
    transit = sum(
        sum(queue.get(flow_id, deque())) for queue in state.transit_queues.values()
    )
    return locations + transit


def initial_simulation_state(package: SimulationPackage) -> SimulationState:
    flow_ids = [flow.id for flow in package.flow_types]
    location_counts = {
        location.id: {flow_id: location.initial_counts.get(flow_id, 0) for flow_id in flow_ids}
        for location in package.locations
    }
    transit_queues = {
        connection.id: {
            flow_id: deque([0] * connection.travel_time_ticks[flow_id])
            for flow_id in flow_ids
        }
        for connection in package.connections
    }
    activity = {
        connection.id: {
            flow_id: ConnectionActivity(departed=0, arrived=0) for flow_id in flow_ids
        }
        for connection in package.connections
    }
    totals = {flow_id: sum(counts[flow_id] for counts in location_counts.values()) for flow_id in flow_ids}
    state = SimulationState(0, location_counts, transit_queues, activity, totals)
    assert_simulation_invariants(None, state, package)
    return state


def assert_simulation_invariants(
    previous: SimulationState | None,
    state: SimulationState,
    package: SimulationPackage,
) -> None:
    flow_ids = [flow.id for flow in package.flow_types]
    connections = {connection.id: connection for connection in package.connections}
    locations = {location.id for location in package.locations}
    if previous is not None and state.tick != previous.tick + 1:
        raise SimulationInvariantError("tick must advance by one")
    if set(state.location_counts) != locations or set(state.transit_queues) != set(connections):
        raise SimulationInvariantError("simulation state references do not match package")
    for flow_id in flow_ids:
        if state.totals.get(flow_id) != _flow_total(state, flow_id):
            raise SimulationInvariantError(f"totals mismatch for {flow_id}")
    for counts in state.location_counts.values():
        if any(counts.get(flow_id, 0) < 0 for flow_id in flow_ids):
            raise SimulationInvariantError("negative location count")
    for connection_id, queues_by_flow in state.transit_queues.items():
        connection = connections[connection_id]
        for flow_id in flow_ids:
            queue = queues_by_flow[flow_id]
            if len(queue) != connection.travel_time_ticks[flow_id]:
                raise SimulationInvariantError("transit queue length mismatch")
            if any(value < 0 for value in queue):
                raise SimulationInvariantError("negative transit count")
            activity = state.connection_activity[connection_id][flow_id]
            if activity.departed > connection.capacity_per_tick[flow_id]:
                raise SimulationInvariantError("connection capacity exceeded")
    if previous is not None:
        for flow_id in flow_ids:
            if _flow_total(previous, flow_id) != _flow_total(state, flow_id):
                raise SimulationInvariantError(f"population is not conserved for {flow_id}")


def step_simulation(package: SimulationPackage, previous: SimulationState, seed: int) -> SimulationState:
    flow_ids = [flow.id for flow in package.flow_types]
    connections = sorted(package.connections, key=lambda connection: connection.id)
    location_by_id = {location.id: location for location in package.locations}
    state = SimulationState(
        tick=previous.tick + 1,
        location_counts=deepcopy(previous.location_counts),
        transit_queues={
            connection_id: {flow_id: deque(queue) for flow_id, queue in queues.items()}
            for connection_id, queues in previous.transit_queues.items()
        },
        connection_activity={
            connection_id: {
                flow_id: ConnectionActivity(departed=0, arrived=0) for flow_id in flow_ids
            }
            for connection_id in previous.transit_queues
        },
        totals=dict(previous.totals),
    )
    outgoing: dict[str, list] = {location.id: [] for location in package.locations}
    for connection in connections:
        outgoing[connection.from_location_id].append(connection)

    for connection in connections:
        for flow_id in flow_ids:
            queue = state.transit_queues[connection.id][flow_id]
            arrived = queue.popleft()
            queue.append(0)
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
                planned[connection.id] = min(requested, connection.capacity_per_tick[flow_id])
            actual = allocate(
                planned,
                departure_budget(
                    available,
                    flow_id,
                    location_by_id[source_id].initial_counts.get(flow_id, 0),
                ),
            )
            for connection in outgoing[source_id]:
                amount = actual[connection.id]
                state.location_counts[source_id][flow_id] -= amount
                state.transit_queues[connection.id][flow_id][-1] += amount
                state.connection_activity[connection.id][flow_id].departed = amount

    state.totals = {flow_id: _flow_total(state, flow_id) for flow_id in flow_ids}
    assert_simulation_invariants(previous, state, package)
    return state


def _street_bucket_map(
    package: SimulationPackage,
    connection: FlowConnection,
    flow_id: str,
    lengths: dict[str, float],
) -> list[tuple[int, str, str]]:
    if package.street_graph is None:
        return []
    route_street_ids = connection.flow_street_segment_ids.get(flow_id)
    route_directions = connection.flow_street_directions.get(flow_id)
    if route_street_ids is None:
        route_street_ids = connection.street_segment_ids
    if route_directions is None:
        route_directions = connection.street_directions
    if not route_street_ids or not route_directions:
        return []
    route_lengths = [lengths[street_id] for street_id in route_street_ids]
    cumulative: list[float] = []
    total = 0.0
    for length in route_lengths:
        total += length
        cumulative.append(total)
    ticks = connection.travel_time_ticks[flow_id]
    result: list[tuple[int, str, str]] = []
    for index in range(ticks):
        route_index = min(
            len(cumulative) - 1,
            bisect_left(cumulative, total * (ticks - index - 0.5) / ticks),
        )
        result.append(
            (
                route_index,
                route_street_ids[route_index],
                route_directions[route_index],
            )
        )
    return result


def _street_snapshots(
    state: SimulationState, package: SimulationPackage
) -> tuple[
    dict[str, dict[str, StreetSnapshot]],
    dict[str, dict[str, list[int]]],
]:
    if package.street_graph is None:
        return {}, {}
    flow_ids = [flow.id for flow in package.flow_types]
    lengths = {
        edge.id: sum(
            hypot(right[0] - left[0], right[1] - left[1])
            for left, right in zip(edge.path, edge.path[1:])
        )
        for edge in package.street_graph.edges
    }
    values = {
        edge.id: {
            flow_id: {
                "entered": 0,
                "exited": 0,
                "in_transit": 0,
                "forward_in_transit": 0,
                "reverse_in_transit": 0,
            }
            for flow_id in flow_ids
        }
        for edge in package.street_graph.edges
    }
    route_values = {
        connection.id: {
            flow_id: [0] * len(
                connection.flow_street_segment_ids.get(flow_id, connection.street_segment_ids)
            )
            for flow_id in flow_ids
        }
        for connection in package.connections
    }
    for connection in package.connections:
        for flow_id in flow_ids:
            bucket_edges = _street_bucket_map(package, connection, flow_id, lengths)
            if not bucket_edges:
                continue
            queue = state.transit_queues[connection.id][flow_id]
            for index, amount in enumerate(queue):
                if amount <= 0:
                    continue
                route_index, street_id, direction = bucket_edges[index]
                street = values[street_id][flow_id]
                street["in_transit"] += amount
                street[f"{direction}_in_transit"] += amount
                route_values[connection.id][flow_id][route_index] += amount
                previous_edge = (
                    bucket_edges[index + 1]
                    if index + 1 < len(bucket_edges)
                    else None
                )
                if previous_edge != bucket_edges[index]:
                    street["entered"] += amount
                    if previous_edge is not None:
                        values[previous_edge[1]][flow_id]["exited"] += amount
            arrived = state.connection_activity[connection.id][flow_id].arrived
            if arrived:
                values[bucket_edges[0][1]][flow_id]["exited"] += arrived
    return (
        {
            street_id: {
                flow_id: StreetSnapshot.model_validate(flow_values)
                for flow_id, flow_values in street_values.items()
            }
            for street_id, street_values in values.items()
        },
        route_values,
    )


def project_flow_snapshot(state: SimulationState, package: SimulationPackage) -> FlowSnapshot:
    flow_ids = [flow.id for flow in package.flow_types]
    streets, route_street_counts = _street_snapshots(state, package)
    connections = {
        connection.id: {
            flow_id: ConnectionSnapshot(
                departed=state.connection_activity[connection.id][flow_id].departed,
                arrived=state.connection_activity[connection.id][flow_id].arrived,
                in_transit=sum(state.transit_queues[connection.id][flow_id]),
                street_in_transit=route_street_counts.get(connection.id, {}).get(
                    flow_id, []
                ),
            )
            for flow_id in flow_ids
        }
        for connection in package.connections
    }
    snapshot = FlowSnapshot(
        tick=state.tick,
        location_counts=state.location_counts,
        connections=connections,
        streets=streets,
        totals=state.totals,
    )
    for flow_id in flow_ids:
        in_locations = sum(location.get(flow_id, 0) for location in snapshot.location_counts.values())
        in_transit = sum(
            values[flow_id].in_transit for values in snapshot.connections.values()
        )
        if in_locations + in_transit != snapshot.totals[flow_id]:
            raise SimulationInvariantError(f"public totals mismatch for {flow_id}")
        if snapshot.streets:
            street_transit = sum(
                values[flow_id].in_transit for values in snapshot.streets.values()
            )
            if street_transit != in_transit:
                raise SimulationInvariantError(f"street totals mismatch for {flow_id}")
            if any(
                sum(values[flow_id].street_in_transit)
                != values[flow_id].in_transit
                for values in snapshot.connections.values()
            ):
                raise SimulationInvariantError(
                    f"connection street totals mismatch for {flow_id}"
                )
    return snapshot
