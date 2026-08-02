from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from hashlib import sha256

from .models import (
    DemandRange,
    FlowBindings,
    FlowConnection,
    FlowLocation,
    FlowTypeConfig,
    SimulationPackage,
    TownJunction,
    TownSkeleton,
    TownStreet,
)
from .scenario import canonical_json

FLOW_TYPES = (
    FlowTypeConfig(id="pedestrian", unit="people", label="人流"),
    FlowTypeConfig(id="vehicle", unit="vehicles", label="车流"),
)
MAX_FLOW_LOCATIONS = 48


class FlowCompileError(ValueError):
    """Raised when a town cannot be compiled into a connected flow graph."""


@dataclass(frozen=True)
class _Edge:
    street_id: str
    source: str
    target: str
    path: tuple[tuple[float, float], ...]
    length: float
    width: float


@dataclass(frozen=True)
class _Route:
    distance: float
    street_ids: tuple[str, ...]
    path: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class _Candidate:
    location: FlowLocation
    feature_ids: tuple[str, ...]
    weight: int


def _distance(left: tuple[float, float], right: tuple[float, float]) -> float:
    return math.hypot(right[0] - left[0], right[1] - left[1])


def _polyline_length(path: tuple[tuple[float, float], ...] | list[tuple[float, float]]) -> float:
    return sum(_distance(left, right) for left, right in zip(path, path[1:]))


def _append_point(path: list[tuple[float, float]], point: tuple[float, float]) -> None:
    if not path or path[-1] != point:
        path.append(point)


def _reverse_route(route: _Route) -> _Route:
    return _Route(
        distance=route.distance,
        street_ids=tuple(reversed(route.street_ids)),
        path=tuple(reversed(route.path)),
    )


def _build_graph(town: TownSkeleton) -> tuple[dict[str, list[_Edge]], dict[str, TownStreet]]:
    streets_by_id = {street.id: street for street in town.streets}
    graph: dict[str, list[_Edge]] = {junction.id: [] for junction in town.junctions}
    for street in town.streets:
        path = tuple(street.path)
        length = _polyline_length(path)
        if length <= 0:
            raise FlowCompileError(f"street {street.id} has zero length")
        edge = _Edge(street.id, street.from_junction_id, street.to_junction_id, path, length, street.width)
        reverse = _Edge(
            street.id,
            street.to_junction_id,
            street.from_junction_id,
            tuple(reversed(path)),
            length,
            street.width,
        )
        if edge.source not in graph or edge.target not in graph:
            raise FlowCompileError(f"street {street.id} references an unknown junction")
        graph[edge.source].append(edge)
        graph[reverse.source].append(reverse)
    for edges in graph.values():
        edges.sort(key=lambda edge: (edge.target, edge.street_id))
    return graph, streets_by_id


def _dijkstra(graph: dict[str, list[_Edge]], source: str) -> dict[str, _Route]:
    best: dict[str, tuple[float, tuple[str, ...]]] = {source: (0.0, ())}
    previous: dict[str, tuple[str, _Edge]] = {}
    queue: list[tuple[float, tuple[str, ...], str]] = [(0.0, (), source)]
    while queue:
        distance, street_ids, current = heapq.heappop(queue)
        if best.get(current) != (distance, street_ids):
            continue
        for edge in graph[current]:
            next_distance = distance + edge.length
            next_street_ids = street_ids + (edge.street_id,)
            old = best.get(edge.target)
            if old is not None and old <= (next_distance, next_street_ids):
                continue
            best[edge.target] = (next_distance, next_street_ids)
            previous[edge.target] = (current, edge)
            heapq.heappush(queue, (next_distance, next_street_ids, edge.target))

    routes: dict[str, _Route] = {}
    for target, (distance, street_ids) in best.items():
        if target == source:
            routes[target] = _Route(0.0, (), ())
            continue
        edges: list[_Edge] = []
        current = target
        while current != source:
            parent, edge = previous[current]
            edges.append(edge)
            current = parent
        edges.reverse()
        path: list[tuple[float, float]] = []
        for edge in edges:
            for point in edge.path:
                _append_point(path, point)
        routes[target] = _Route(distance, street_ids, tuple(path))
    return routes


def _nearest_junction(
    position: tuple[float, float], junctions: list[TownJunction]
) -> TownJunction:
    return min(junctions, key=lambda junction: (_distance(position, junction.position), junction.id))


def _centroid(polygon: list[tuple[float, float]]) -> tuple[float, float]:
    return (
        round(sum(point[0] for point in polygon) / len(polygon), 6),
        round(sum(point[1] for point in polygon) / len(polygon), 6),
    )


def _sample_evenly(values: list[_Candidate], limit: int) -> list[_Candidate]:
    if len(values) <= limit:
        return values
    if limit <= 0:
        return []
    if limit == 1:
        return [values[len(values) // 2]]
    indexes = {(index * (len(values) - 1)) // (limit - 1) for index in range(limit)}
    return [values[index] for index in sorted(indexes)]


def _allocate_total(total: int, candidates: list[_Candidate]) -> dict[str, int]:
    weighted = [(candidate.location.id, max(0, candidate.weight)) for candidate in candidates]
    if not any(weight for _, weight in weighted):
        weighted = [(candidate.location.id, 1) for candidate in candidates]
    weight_sum = sum(weight for _, weight in weighted)
    allocation: dict[str, int] = {}
    remainders: list[tuple[int, str]] = []
    for location_id, weight in weighted:
        base, remainder = divmod(total * weight, weight_sum)
        allocation[location_id] = base
        remainders.append((remainder, location_id))
    for _, location_id in sorted(remainders, key=lambda item: (-item[0], item[1]))[: total - sum(allocation.values())]:
        allocation[location_id] += 1
    return allocation


def _candidates(town: TownSkeleton) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    gate_junctions = sorted(
        (junction for junction in town.junctions if junction.kind == "gate"),
        key=lambda junction: junction.id,
    )
    for junction in gate_junctions:
        direction = junction.id.removeprefix("junction-gate-")
        candidates.append(
            _Candidate(
                FlowLocation(
                    id=f"location-gate-{direction}",
                    name=f"{direction.title()} Gate",
                    kind="gate",
                    position=junction.position,
                    initial_counts={},
                ),
                (junction.id,),
                0,
            )
        )

    plaza = next((junction for junction in town.junctions if junction.kind == "plaza"), None)
    if plaza is None:
        raise FlowCompileError("town has no plaza junction")
    candidates.append(
        _Candidate(
            FlowLocation(
                id="location-plaza",
                name="Central Plaza",
                kind="plaza",
                position=plaza.position,
                initial_counts={},
            ),
            (plaza.id,),
            0,
        )
    )

    for landmark in sorted(town.landmarks, key=lambda item: item.id):
        if landmark.kind in {"gate", "plaza"}:
            continue
        features = [landmark.id]
        if landmark.building_id is not None:
            features.append(landmark.building_id)
        candidates.append(
            _Candidate(
                FlowLocation(
                    id=f"location-landmark-{landmark.kind}",
                    name=landmark.name,
                    kind="landmark",
                    position=landmark.position,
                    initial_counts={},
                ),
                tuple(features),
                0,
            )
        )

    building_counts: dict[str, int] = {}
    for building in town.buildings:
        building_counts[building.district_id] = building_counts.get(building.district_id, 0) + 1
    district_candidates = [
        _Candidate(
                FlowLocation(
                    id=f"location-{district.id}",
                    name=f"{town.name} {district.id}"[:64],
                kind="district",
                position=_centroid(district.polygon),
                initial_counts={},
            ),
            (district.id,),
            building_counts.get(district.id, 0),
        )
        for district in sorted(town.districts, key=lambda item: item.id)
    ]
    return candidates + _sample_evenly(district_candidates, MAX_FLOW_LOCATIONS - len(candidates))


def _route_between(
    left: _Candidate,
    right: _Candidate,
    left_junction: TownJunction,
    right_junction: TownJunction,
    routes: dict[str, _Route],
) -> _Route | None:
    middle = routes.get(right_junction.id)
    if middle is None or not middle.street_ids:
        return None
    path: list[tuple[float, float]] = []
    _append_point(path, left.location.position)
    _append_point(path, left_junction.position)
    for point in middle.path:
        _append_point(path, point)
    _append_point(path, right_junction.position)
    _append_point(path, right.location.position)
    return _Route(_polyline_length(path), middle.street_ids, tuple(path))


def _choose_edges(
    candidates: list[_Candidate],
    routes: dict[tuple[str, str], _Route],
) -> list[tuple[int, int, _Route]]:
    pairs = [
        (left_index, right_index, routes[(left.location.id, right.location.id)])
        for left_index, left in enumerate(candidates)
        for right_index, right in enumerate(candidates[left_index + 1 :], left_index + 1)
        if (left.location.id, right.location.id) in routes
    ]
    pairs.sort(key=lambda item: (item[2].distance, candidates[item[0]].location.id, candidates[item[1]].location.id))
    parent = list(range(len(candidates)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    selected: set[tuple[int, int]] = set()
    result: list[tuple[int, int, _Route]] = []
    for left_index, right_index, route in pairs:
        left_root, right_root = find(left_index), find(right_index)
        if left_root == right_root:
            continue
        parent[left_root] = right_root
        selected.add((left_index, right_index))
        result.append((left_index, right_index, route))
    if len(result) != len(candidates) - 1:
        raise FlowCompileError("street graph cannot connect all flow locations")

    for index, candidate in enumerate(candidates):
        neighbors = sorted(
            (
                (other_index, routes[(candidate.location.id, other.location.id)])
                if (candidate.location.id, other.location.id) in routes
                else (other_index, _reverse_route(routes[(other.location.id, candidate.location.id)]))
                for other_index, other in enumerate(candidates)
                if other_index != index
                and (
                    (candidate.location.id, other.location.id) in routes
                    or (other.location.id, candidate.location.id) in routes
                )
            ),
            key=lambda item: (item[1].distance, candidates[item[0]].location.id),
        )
        added = 0
        for other_index, route in neighbors:
            key = (min(index, other_index), max(index, other_index))
            if key in selected:
                continue
            left_index, right_index = key
            if index != left_index:
                route = _reverse_route(route)
            selected.add(key)
            result.append((left_index, right_index, route))
            added += 1
            if added == 2:
                break
    return sorted(result, key=lambda item: (item[0], item[1]))


def _connection(
    ordinal: int,
    left: _Candidate,
    right: _Candidate,
    route: _Route,
    streets_by_id: dict[str, TownStreet],
) -> tuple[FlowConnection, FlowConnection]:
    min_width = min(streets_by_id[street_id].width for street_id in route.street_ids)
    pedestrian_capacity = max(1, math.floor(min_width * 1.5))
    vehicle_capacity = max(1, math.floor(min_width / 2.5))
    path_length = max(1.0, route.distance)
    travel_time = {
        "pedestrian": min(3600, max(1, math.ceil(path_length / 1.4))),
        "vehicle": min(3600, max(1, math.ceil(path_length / 4.0))),
    }
    capacity = {"pedestrian": pedestrian_capacity, "vehicle": vehicle_capacity}
    demand = {
        flow_id: DemandRange(min=0, max=max(1, math.floor(value * 0.6)))
        for flow_id, value in capacity.items()
    }

    def build(direction: str, source: _Candidate, target: _Candidate, oriented: _Route) -> FlowConnection:
        return FlowConnection(
            id=f"connection-{ordinal:03d}-{direction}",
            from_location_id=source.location.id,
            to_location_id=target.location.id,
            street_segment_ids=list(oriented.street_ids),
            path=list(oriented.path),
            travel_time_ticks=travel_time,
            capacity_per_tick=capacity,
            demand_per_tick=demand,
        )

    return build("forward", left, right, route), build(
        "reverse", right, left, _reverse_route(route)
    )


def compile_flow(town: TownSkeleton) -> SimulationPackage:
    candidates = sorted(_candidates(town), key=lambda candidate: candidate.location.id)
    if len(candidates) < 2:
        raise FlowCompileError("town needs at least two flow locations")
    graph, streets_by_id = _build_graph(town)
    junctions = sorted(town.junctions, key=lambda junction: junction.id)
    location_junctions = {
        candidate.location.id: _nearest_junction(candidate.location.position, junctions)
        for candidate in candidates
    }
    routes: dict[tuple[str, str], _Route] = {}
    for source in candidates:
        shortest = _dijkstra(graph, location_junctions[source.location.id].id)
        for target in candidates:
            if source.location.id == target.location.id:
                continue
            route = _route_between(
                source,
                target,
                location_junctions[source.location.id],
                location_junctions[target.location.id],
                shortest,
            )
            if route is not None:
                routes[(source.location.id, target.location.id)] = route
    selected_edges = _choose_edges(candidates, routes)

    pedestrian_counts = _allocate_total(town.requested_population, candidates)
    vehicle_counts = _allocate_total(town.initial_vehicle_count, candidates)
    locations = [
        candidate.location.model_copy(
            update={
                "initial_counts": {
                    "pedestrian": pedestrian_counts[candidate.location.id],
                    "vehicle": vehicle_counts[candidate.location.id],
                }
            }
        )
        for candidate in candidates
    ]

    connections: list[FlowConnection] = []
    connection_street_ids: dict[str, list[str]] = {}
    for ordinal, (left_index, right_index, route) in enumerate(selected_edges):
        forward, reverse = _connection(
            ordinal,
            candidates[left_index],
            candidates[right_index],
            route,
            streets_by_id,
        )
        connections.extend((forward, reverse))
        connection_street_ids[forward.id] = list(forward.street_segment_ids)
        connection_street_ids[reverse.id] = list(reverse.street_segment_ids)

    package = SimulationPackage(
        flow_types=list(FLOW_TYPES),
        locations=locations,
        connections=connections,
        bindings=FlowBindings(
            location_feature_ids={
                candidate.location.id: list(candidate.feature_ids) for candidate in candidates
            },
            connection_street_ids=connection_street_ids,
        ),
    )
    assert_simulation_package(package, town)
    return package


def assert_simulation_package(package: SimulationPackage, town: TownSkeleton) -> None:
    flow_ids = {flow.id for flow in package.flow_types}
    location_ids = {location.id for location in package.locations}
    street_ids = {street.id for street in town.streets}
    if len(flow_ids) != len(package.flow_types) or len(location_ids) != len(package.locations):
        raise FlowCompileError("simulation package contains duplicate ids")
    if any(set(location.initial_counts) != flow_ids for location in package.locations):
        raise FlowCompileError("location counts do not match flow types")
    if sum(location.initial_counts["pedestrian"] for location in package.locations) != town.requested_population:
        raise FlowCompileError("pedestrian population is not conserved")
    if sum(location.initial_counts["vehicle"] for location in package.locations) != town.initial_vehicle_count:
        raise FlowCompileError("vehicle population is not conserved")
    if set(package.bindings.location_feature_ids) != location_ids:
        raise FlowCompileError("location bindings are incomplete")
    connection_ids = {connection.id for connection in package.connections}
    if len(connection_ids) != len(package.connections):
        raise FlowCompileError("simulation package contains duplicate connection ids")
    if set(package.bindings.connection_street_ids) != connection_ids:
        raise FlowCompileError("connection bindings are incomplete")
    for connection in package.connections:
        if connection.from_location_id not in location_ids or connection.to_location_id not in location_ids:
            raise FlowCompileError(f"connection {connection.id} references an unknown location")
        if connection.from_location_id == connection.to_location_id:
            raise FlowCompileError(f"connection {connection.id} is a self-loop")
        if set(connection.travel_time_ticks) != flow_ids or set(connection.capacity_per_tick) != flow_ids:
            raise FlowCompileError(f"connection {connection.id} has incomplete flow parameters")
        if set(connection.demand_per_tick) != flow_ids:
            raise FlowCompileError(f"connection {connection.id} has incomplete demand parameters")
        if not set(connection.street_segment_ids) <= street_ids:
            raise FlowCompileError(f"connection {connection.id} references an unknown street")
        if connection.path[0] != next(location.position for location in package.locations if location.id == connection.from_location_id):
            raise FlowCompileError(f"connection {connection.id} path has an invalid source")
        if connection.path[-1] != next(location.position for location in package.locations if location.id == connection.to_location_id):
            raise FlowCompileError(f"connection {connection.id} path has an invalid destination")
        if _polyline_length(connection.path) <= 0:
            raise FlowCompileError(f"connection {connection.id} has zero length")


def simulation_package_checksum(package: SimulationPackage) -> str:
    payload = canonical_json(package.model_dump(mode="json")).encode("utf-8")
    return sha256(payload).hexdigest()
