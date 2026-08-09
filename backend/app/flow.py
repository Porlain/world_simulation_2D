from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, replace
from hashlib import sha256

from .models import (
    DemandRange,
    FlowBindings,
    FlowConnection,
    FlowLocation,
    FlowTypeConfig,
    SimulationPackage,
    StreetGraph,
    TownJunction,
    TownSkeleton,
    TownStreet,
)
from .scenario import canonical_json

FLOW_TYPES = (
    FlowTypeConfig(id="pedestrian", unit="people", label="人流"),
    FlowTypeConfig(id="vehicle", unit="vehicles", label="车流"),
)
# A generated town has at most 8 * 32 districts. Keeping one flow location
# per district prevents the overview from hiding most of the town behind a
# handful of sampled nodes; a later building-detail view can refine this.
MAX_FLOW_LOCATIONS = 320
VEHICLE_MIN_WIDTH = 3.0


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
    forward: bool
    pedestrian_access: bool
    vehicle_access: bool


@dataclass(frozen=True)
class _Route:
    distance: float
    street_ids: tuple[str, ...]
    street_directions: tuple[bool, ...]
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
        street_directions=tuple(not forward for forward in reversed(route.street_directions)),
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
        edge = _Edge(
            street.id,
            street.from_junction_id,
            street.to_junction_id,
            path,
            length,
            street.width,
            True,
            street.pedestrian_access,
            street.vehicle_access,
        )
        reverse = _Edge(
            street.id,
            street.to_junction_id,
            street.from_junction_id,
            tuple(reversed(path)),
            length,
            street.width,
            False,
            street.pedestrian_access,
            street.vehicle_access,
        )
        if edge.source not in graph or edge.target not in graph:
            raise FlowCompileError(f"street {street.id} references an unknown junction")
        graph[edge.source].append(edge)
        graph[reverse.source].append(reverse)
    for edges in graph.values():
        edges.sort(key=lambda edge: (edge.target, edge.street_id))
    return graph, streets_by_id


def _dijkstra(
    graph: dict[str, list[_Edge]],
    source: str,
    flow_id: str | None = None,
) -> dict[str, _Route]:
    best: dict[str, tuple[float, tuple[str, ...]]] = {source: (0.0, ())}
    previous: dict[str, tuple[str, _Edge]] = {}
    queue: list[tuple[float, tuple[str, ...], str]] = [(0.0, (), source)]
    while queue:
        distance, street_ids, current = heapq.heappop(queue)
        if best.get(current) != (distance, street_ids):
            continue
        for edge in graph[current]:
            if flow_id == "pedestrian" and not edge.pedestrian_access:
                continue
            if flow_id == "vehicle" and (
                not edge.vehicle_access or edge.width < VEHICLE_MIN_WIDTH
            ):
                continue
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
            routes[target] = _Route(0.0, (), (), ())
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
        routes[target] = _Route(
            distance,
            street_ids,
            tuple(edge.forward for edge in edges),
            tuple(path),
        )
    return routes


def _nearest_junction(
    position: tuple[float, float], junctions: list[TownJunction]
) -> TownJunction:
    return min(junctions, key=lambda junction: (_distance(position, junction.position), junction.id))


def _nearest_routable_junction(
    position: tuple[float, float],
    junctions: list[TownJunction],
    routes_by_junction: dict[str, dict[str, _Route]],
    anchor_id: str,
) -> TownJunction:
    """Snap a location to the nearest junction that can reach the town core."""
    ordered = sorted(junctions, key=lambda junction: (_distance(position, junction.position), junction.id))
    return next(
        (junction for junction in ordered if anchor_id in routes_by_junction.get(junction.id, {})),
        ordered[0],
    )


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
    direction_labels = {"north": "北", "east": "东", "south": "南", "west": "西"}
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
                    name=f"{direction_labels[direction]}城门",
                    kind="gate",
                    position=junction.position,
                    initial_counts={},
                ),
                (junction.id, f"landmark-{direction}-gate"),
                1,
            )
        )

    plaza = next((junction for junction in town.junctions if junction.kind == "plaza"), None)
    if plaza is None:
        raise FlowCompileError("town has no plaza junction")
    candidates.append(
        _Candidate(
            FlowLocation(
                id="location-plaza",
                name="中央广场",
                kind="plaza",
                position=plaza.position,
                initial_counts={},
            ),
            (plaza.id, "landmark-plaza"),
            1,
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
                1,
            )
        )

    building_counts: dict[str, int] = {}
    special_building_ids = {
        landmark.building_id
        for landmark in town.landmarks
        if landmark.building_id is not None
    }
    for building in town.buildings:
        building_counts[building.district_id] = building_counts.get(building.district_id, 0) + 1
    buildings_by_district: dict[str, list[str]] = {}
    for building in town.buildings:
        if building.id not in special_building_ids:
            buildings_by_district.setdefault(building.district_id, []).append(building.id)
    walkways_by_district: dict[str, list[str]] = {}
    for walkway in town.walkways:
        walkways_by_district.setdefault(walkway.district_id, []).append(walkway.id)
    district_candidates = [
        _Candidate(
                FlowLocation(
                    id=f"location-{district.id}",
                    name=town.district_names.get(district.id, f"{town.name} · {district.id}")[:64],
                kind="district",
                position=_centroid(district.polygon),
                initial_counts={},
            ),
            (district.id,),
            building_counts.get(district.id, 0),
        )
        for district in sorted(town.districts, key=lambda item: item.id)
    ]
    selected_districts = _sample_evenly(district_candidates, MAX_FLOW_LOCATIONS - len(candidates))
    if not selected_districts:
        raise FlowCompileError("town has no resident flow locations")

    grouped_features = {
        candidate.location.id: list(candidate.feature_ids)
        for candidate in selected_districts
    }
    selected_by_id = {candidate.location.id: candidate for candidate in selected_districts}
    for district in district_candidates:
        target = selected_by_id.get(district.location.id)
        if target is None:
            target = min(
                selected_districts,
                key=lambda candidate: (
                    _distance(candidate.location.position, district.location.position),
                    candidate.location.id,
                ),
            )
        feature_ids = grouped_features[target.location.id]
        district_id = district.location.id.removeprefix("location-")
        feature_ids.append(district_id)
        feature_ids.extend(buildings_by_district.get(district_id, []))
        feature_ids.extend(walkways_by_district.get(district_id, []))

    return candidates + [
        replace(
            candidate,
            feature_ids=tuple(dict.fromkeys(grouped_features[candidate.location.id])),
        )
        for candidate in selected_districts
    ]


def _walkway_access_paths(
    town: TownSkeleton,
    candidates: list[_Candidate],
    flow_id: str,
) -> dict[str, tuple[tuple[float, float], ...]]:
    """Build the local leg used when a flow enters or leaves a district.

    Walkways stay out of the global junction graph, but pedestrian routes still
    include their nearest local segment. This keeps the graph compact while
    making the route geometry reflect the same building gaps shown on the map.
    """
    if not town.walkways:
        return {}
    building_district = {building.id: building.district_id for building in town.buildings}
    district_ids = {district.id for district in town.districts}
    result: dict[str, tuple[tuple[float, float], ...]] = {}
    for candidate in candidates:
        associated_districts = {
            feature_id if feature_id in district_ids else building_district.get(feature_id)
            for feature_id in candidate.feature_ids
        }
        associated_districts.discard(None)
        local = [
            walkway
            for walkway in town.walkways
            if walkway.district_id in associated_districts
            and (flow_id == "pedestrian" and walkway.pedestrian_access
                 or flow_id == "vehicle" and walkway.vehicle_access and walkway.width >= VEHICLE_MIN_WIDTH)
        ]
        if not local:
            continue
        walkway = min(
            local,
            key=lambda item: (
                min(_distance(candidate.location.position, item.path[0]), _distance(candidate.location.position, item.path[-1])),
                item.id,
            ),
        )
        path = tuple(walkway.path)
        if _distance(candidate.location.position, path[-1]) < _distance(candidate.location.position, path[0]):
            path = tuple(reversed(path))
        result[candidate.location.id] = (candidate.location.position, *path)
    return result


def _route_between(
    left: _Candidate,
    right: _Candidate,
    left_junction: TownJunction,
    right_junction: TownJunction,
    routes: dict[str, _Route],
    left_access: tuple[tuple[float, float], ...] = (),
    right_access: tuple[tuple[float, float], ...] = (),
) -> _Route | None:
    middle = routes.get(right_junction.id)
    if middle is None or not middle.street_ids:
        return None
    path: list[tuple[float, float]] = []
    for point in left_access or (left.location.position,):
        _append_point(path, point)
    _append_point(path, left_junction.position)
    for point in middle.path:
        _append_point(path, point)
    _append_point(path, right_junction.position)
    for point in reversed(right_access or (right.location.position,)):
        _append_point(path, point)
    return _Route(
        _polyline_length(path),
        middle.street_ids,
        middle.street_directions,
        tuple(path),
    )


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

    result: list[tuple[int, int, _Route]] = []
    for left_index, right_index, route in pairs:
        left_root, right_root = find(left_index), find(right_index)
        if left_root == right_root:
            continue
        parent[left_root] = right_root
        result.append((left_index, right_index, route))
    if len(result) != len(candidates) - 1:
        raise FlowCompileError("street graph cannot connect all flow locations")

    return sorted(result, key=lambda item: (item[0], item[1]))


def _route_via_street(
    candidates: list[_Candidate],
    street: TownStreet,
    junctions_by_id: dict[str, TownJunction],
    location_junctions: dict[str, TownJunction],
    junction_routes: dict[str, dict[str, _Route]],
) -> tuple[int, int, _Route] | None:
    """Build a deterministic OD route that explicitly crosses one street.

    The sparse OD graph still provides the town's normal demand structure. This
    second pass adds a route for physical streets that do not occur in that
    graph, keeping traffic tied to the generated street network instead of
    making unused roads decorative only.
    """
    source_options = sorted(
        enumerate(candidates),
        key=lambda item: (
            location_junctions[item[1].location.id].id != street.from_junction_id,
            _distance(item[1].location.position, junctions_by_id[street.from_junction_id].position),
            item[1].location.id,
        ),
    )
    target_options = sorted(
        enumerate(candidates),
        key=lambda item: (
            location_junctions[item[1].location.id].id != street.to_junction_id,
            _distance(item[1].location.position, junctions_by_id[street.to_junction_id].position),
            item[1].location.id,
        ),
    )
    for source_index, source in source_options[:32]:
        source_junction = location_junctions[source.location.id]
        left = junction_routes[source_junction.id].get(street.from_junction_id)
        if left is None or street.id in left.street_ids:
            continue
        for target_index, target in target_options[:32]:
            if source_index == target_index:
                continue
            target_junction = location_junctions[target.location.id]
            right = junction_routes[target_junction.id].get(street.to_junction_id)
            if right is None or street.id in right.street_ids:
                continue
            path: list[tuple[float, float]] = []
            _append_point(path, source.location.position)
            for point in left.path:
                _append_point(path, point)
            for point in street.path:
                _append_point(path, point)
            for point in reversed(right.path):
                _append_point(path, point)
            _append_point(path, target.location.position)
            street_ids = tuple(left.street_ids) + (street.id,) + tuple(reversed(right.street_ids))
            street_directions = (
                tuple(left.street_directions)
                + (True,)
                + tuple(not forward for forward in reversed(right.street_directions))
            )
            return source_index, target_index, _Route(
                _polyline_length(path), street_ids, street_directions, tuple(path)
            )
    fallback: list[tuple[int, float, str, str, int, int, _Route]] = []
    for source_index, source in source_options[:32]:
        source_junction = location_junctions[source.location.id]
        left = junction_routes[source_junction.id].get(street.from_junction_id)
        if left is None:
            continue
        for target_index, target in target_options[:32]:
            if source_index == target_index:
                continue
            target_junction = location_junctions[target.location.id]
            right = junction_routes[target_junction.id].get(street.to_junction_id)
            if right is None:
                continue
            path: list[tuple[float, float]] = []
            _append_point(path, source.location.position)
            for point in left.path:
                _append_point(path, point)
            for point in street.path:
                _append_point(path, point)
            for point in reversed(right.path):
                _append_point(path, point)
            _append_point(path, target.location.position)
            street_ids = tuple(left.street_ids) + (street.id,) + tuple(reversed(right.street_ids))
            street_directions = (
                tuple(left.street_directions)
                + (True,)
                + tuple(not forward for forward in reversed(right.street_directions))
            )
            repeated = int(street.id in left.street_ids) + int(street.id in right.street_ids)
            route = _Route(
                _polyline_length(path), street_ids, street_directions, tuple(path)
            )
            fallback.append((repeated, route.distance, source.location.id, target.location.id, source_index, target_index, route))
    if fallback:
        _, _, _, _, source_index, target_index, route = min(fallback)
        return source_index, target_index, route
    return None


def _add_street_coverage_routes(
    selected_edges: list[tuple[int, int, _Route]],
    candidates: list[_Candidate],
    streets: list[TownStreet],
    junctions_by_id: dict[str, TownJunction],
    location_junctions: dict[str, TownJunction],
    junction_routes: dict[str, dict[str, _Route]],
) -> list[tuple[int, int, _Route]]:
    used_streets = {street_id for _, _, route in selected_edges for street_id in route.street_ids}
    result = list(selected_edges)
    for street in sorted(streets, key=lambda item: item.id):
        if street.id in used_streets:
            continue
        route = _route_via_street(candidates, street, junctions_by_id, location_junctions, junction_routes)
        if route is None:
            continue
        source_index, target_index, oriented = route
        if source_index > target_index:
            source_index, target_index = target_index, source_index
            oriented = _reverse_route(oriented)
        result.append((source_index, target_index, oriented))
        used_streets.update(oriented.street_ids)
    return sorted(result, key=lambda item: (item[0], item[1], item[2].street_ids))


def _connection(
    ordinal: int,
    left: _Candidate,
    right: _Candidate,
    routes_by_flow: dict[str, _Route | None],
    streets_by_id: dict[str, TownStreet],
) -> tuple[FlowConnection, FlowConnection]:
    base_route = routes_by_flow.get("pedestrian") or routes_by_flow.get("vehicle")
    if base_route is None:
        raise FlowCompileError("connection has no traversable route")

    travel_time: dict[str, int] = {}
    capacity: dict[str, int] = {}
    for flow_id, speed in (("pedestrian", 1.4), ("vehicle", 4.0)):
        route = routes_by_flow.get(flow_id)
        if route is None or not route.street_ids:
            travel_time[flow_id] = 1
            capacity[flow_id] = 0
            continue
        route_streets = [streets_by_id[street_id] for street_id in route.street_ids]
        access = (
            all(street.pedestrian_access for street in route_streets)
            if flow_id == "pedestrian"
            else all(
                street.vehicle_access and street.width >= VEHICLE_MIN_WIDTH
                for street in route_streets
            )
        )
        min_width = min(street.width for street in route_streets)
        path_length = max(1.0, _polyline_length(route.path))
        travel_time[flow_id] = min(3600, max(1, math.ceil(path_length / speed)))
        if not access:
            capacity[flow_id] = 0
        elif flow_id == "pedestrian":
            capacity[flow_id] = max(1, math.floor(min_width * 1.5))
        else:
            # A vehicle needs a little more clearance than the visual line
            # width; lane-width streets remain usable, alleys do not.
            capacity[flow_id] = max(1, math.floor(min_width / 2.5))

    route = base_route
    demand = {
        flow_id: DemandRange(min=0, max=max(0, math.floor(value * 0.6)))
        for flow_id, value in capacity.items()
    }

    def build(
        direction: str,
        source: _Candidate,
        target: _Candidate,
        oriented: _Route,
        oriented_routes: dict[str, _Route | None],
    ) -> FlowConnection:
        flow_street_segment_ids = {
            flow_id: list(flow_route.street_ids) if flow_route else []
            for flow_id, flow_route in oriented_routes.items()
        }
        flow_street_directions = {
            flow_id: [
                "forward" if forward else "reverse"
                for forward in flow_route.street_directions
            ] if flow_route else []
            for flow_id, flow_route in oriented_routes.items()
        }
        flow_paths = {
            flow_id: list(flow_route.path) if flow_route else []
            for flow_id, flow_route in oriented_routes.items()
        }
        return FlowConnection(
            id=f"connection-{ordinal:03d}-{direction}",
            from_location_id=source.location.id,
            to_location_id=target.location.id,
            street_segment_ids=list(oriented.street_ids),
            street_directions=[
                "forward" if forward else "reverse"
                for forward in oriented.street_directions
            ],
            path=list(oriented.path),
            flow_street_segment_ids=flow_street_segment_ids,
            flow_street_directions=flow_street_directions,
            flow_paths=flow_paths,
            travel_time_ticks=travel_time,
            capacity_per_tick=capacity,
            demand_per_tick=demand,
        )

    return build("forward", left, right, route, routes_by_flow), build(
        "reverse",
        right,
        left,
        _reverse_route(route),
        {
            flow_id: _reverse_route(flow_route) if flow_route else None
            for flow_id, flow_route in routes_by_flow.items()
        },
    )


def compile_flow(town: TownSkeleton) -> SimulationPackage:
    candidates = sorted(_candidates(town), key=lambda candidate: candidate.location.id)
    if len(candidates) < 2:
        raise FlowCompileError("town needs at least two flow locations")
    graph, streets_by_id = _build_graph(town)
    junctions = sorted(town.junctions, key=lambda junction: junction.id)
    plaza_junction = next((junction for junction in junctions if junction.kind == "plaza"), None)
    if plaza_junction is None:
        raise FlowCompileError("town has no plaza junction")

    flow_ids = ("pedestrian", "vehicle")
    junction_routes_by_flow = {
        flow_id: {
            junction.id: _dijkstra(graph, junction.id, flow_id)
            for junction in junctions
        }
        for flow_id in flow_ids
    }
    walkway_access_by_flow = {
        flow_id: _walkway_access_paths(town, candidates, flow_id)
        for flow_id in flow_ids
    }
    location_junctions_by_flow = {
        flow_id: {
            candidate.location.id: _nearest_routable_junction(
                candidate.location.position,
                junctions,
                junction_routes_by_flow[flow_id],
                plaza_junction.id,
            )
            for candidate in candidates
        }
        for flow_id in flow_ids
    }
    routes_by_flow: dict[str, dict[tuple[str, str], _Route]] = {}
    for flow_id in flow_ids:
        location_junctions = location_junctions_by_flow[flow_id]
        routes: dict[tuple[str, str], _Route] = {}
        for source in candidates:
            source_junction = location_junctions[source.location.id]
            shortest = junction_routes_by_flow[flow_id][source_junction.id]
            for target in candidates:
                if source.location.id == target.location.id:
                    continue
                target_junction = location_junctions[target.location.id]
                route = _route_between(
                    source,
                    target,
                    source_junction,
                    target_junction,
                    shortest,
                    walkway_access_by_flow[flow_id].get(source.location.id, ()),
                    walkway_access_by_flow[flow_id].get(target.location.id, ()),
                )
                if route is not None:
                    routes[(source.location.id, target.location.id)] = route
        routes_by_flow[flow_id] = routes

    selected_edges = _choose_edges(candidates, routes_by_flow["pedestrian"])
    pedestrian_location_junctions = location_junctions_by_flow["pedestrian"]
    pedestrian_junction_routes = junction_routes_by_flow["pedestrian"]
    junctions_by_id = {junction.id: junction for junction in junctions}
    selected_edges = _add_street_coverage_routes(
        selected_edges,
        candidates,
        list(streets_by_id.values()),
        junctions_by_id,
        pedestrian_location_junctions,
        pedestrian_junction_routes,
    )

    vehicle_seed_edges: list[tuple[int, int, _Route]] = []
    for left_index, right_index, _ in selected_edges:
        left, right = candidates[left_index], candidates[right_index]
        vehicle_route = routes_by_flow["vehicle"].get(
            (left.location.id, right.location.id)
        )
        if vehicle_route is not None:
            vehicle_seed_edges.append((left_index, right_index, vehicle_route))
    vehicle_streets = [
        street
        for street in streets_by_id.values()
        if street.vehicle_access and street.width >= VEHICLE_MIN_WIDTH
    ]
    vehicle_coverage_edges = _add_street_coverage_routes(
        vehicle_seed_edges,
        candidates,
        vehicle_streets,
        junctions_by_id,
        location_junctions_by_flow["vehicle"],
        junction_routes_by_flow["vehicle"],
    )
    vehicle_seed_keys = {
        (left_index, right_index, route.street_ids, route.street_directions)
        for left_index, right_index, route in vehicle_seed_edges
    }
    extra_vehicle_edges = [
        edge
        for edge in vehicle_coverage_edges
        if (
            edge[0], edge[1], edge[2].street_ids, edge[2].street_directions
        ) not in vehicle_seed_keys
    ]
    route_specs: list[tuple[int, int, _Route, _Route | None]] = [
        (left_index, right_index, route, None)
        for left_index, right_index, route in selected_edges
    ]
    for left_index, right_index, vehicle_route in extra_vehicle_edges:
        left, right = candidates[left_index], candidates[right_index]
        pedestrian_route = routes_by_flow["pedestrian"].get(
            (left.location.id, right.location.id)
        )
        if pedestrian_route is not None:
            route_specs.append((left_index, right_index, pedestrian_route, vehicle_route))
    route_specs.sort(
        key=lambda item: (
            item[0],
            item[1],
            item[2].street_ids,
            item[3].street_ids if item[3] is not None else (),
        )
    )

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
    for ordinal, (
        left_index,
        right_index,
        pedestrian_route,
        forced_vehicle_route,
    ) in enumerate(route_specs):
        flow_routes: dict[str, _Route | None] = {"pedestrian": pedestrian_route}
        for flow_id in flow_ids:
            if flow_id == "pedestrian":
                continue
            left = candidates[left_index]
            right = candidates[right_index]
            flow_routes[flow_id] = forced_vehicle_route or routes_by_flow[flow_id].get(
                (left.location.id, right.location.id)
            )
        forward, reverse = _connection(
            ordinal,
            candidates[left_index],
            candidates[right_index],
            flow_routes,
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
        street_graph=StreetGraph(
            junctions=list(junctions), edges=list(streets_by_id.values())
        ),
    )
    assert_simulation_package(package, town)
    return package


def assert_simulation_package(package: SimulationPackage, town: TownSkeleton) -> None:
    flow_ids = {flow.id for flow in package.flow_types}
    location_ids = {location.id for location in package.locations}
    street_ids = {street.id for street in town.streets}
    streets_by_id = {street.id: street for street in town.streets}
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
        if len(connection.street_directions) != len(connection.street_segment_ids):
            raise FlowCompileError(f"connection {connection.id} has incomplete street directions")
        oriented_endpoints = [
            (
                (street.from_junction_id, street.to_junction_id)
                if direction == "forward"
                else (street.to_junction_id, street.from_junction_id)
            )
            for street_id, direction in zip(
                connection.street_segment_ids, connection.street_directions
            )
            for street in (streets_by_id[street_id],)
        ]
        if any(
            left[1] != right[0]
            for left, right in zip(oriented_endpoints, oriented_endpoints[1:])
        ):
            raise FlowCompileError(f"connection {connection.id} has a disconnected street route")
        if connection.path[0] != next(location.position for location in package.locations if location.id == connection.from_location_id):
            raise FlowCompileError(f"connection {connection.id} path has an invalid source")
        if connection.path[-1] != next(location.position for location in package.locations if location.id == connection.to_location_id):
            raise FlowCompileError(f"connection {connection.id} path has an invalid destination")
        if _polyline_length(connection.path) <= 0:
            raise FlowCompileError(f"connection {connection.id} has zero length")
        for flow_id, access_name in (("pedestrian", "pedestrian_access"), ("vehicle", "vehicle_access")):
            route_ids = connection.flow_street_segment_ids.get(flow_id, connection.street_segment_ids)
            route_directions = connection.flow_street_directions.get(flow_id, connection.street_directions)
            route_path = connection.flow_paths.get(flow_id, connection.path)
            if len(route_ids) != len(route_directions):
                raise FlowCompileError(f"connection {connection.id} has incomplete {flow_id} route directions")
            if connection.capacity_per_tick[flow_id] > 0 and not route_ids:
                raise FlowCompileError(f"connection {connection.id} has capacity without a {flow_id} route")
            if any(
                not getattr(streets_by_id[street_id], access_name)
                or (flow_id == "vehicle" and streets_by_id[street_id].width < VEHICLE_MIN_WIDTH)
                for street_id in route_ids
            ):
                raise FlowCompileError(f"connection {connection.id} {flow_id} route uses a restricted street")
            if route_path and (
                route_path[0] != next(location.position for location in package.locations if location.id == connection.from_location_id)
                or route_path[-1] != next(location.position for location in package.locations if location.id == connection.to_location_id)
            ):
                raise FlowCompileError(f"connection {connection.id} has an invalid {flow_id} route endpoint")
    if package.street_graph is None:
        raise FlowCompileError("simulation package has no street graph")
    if {junction.id for junction in package.street_graph.junctions} != {
        junction.id for junction in town.junctions
    }:
        raise FlowCompileError("street graph junctions do not match the generated town")
    if {edge.id for edge in package.street_graph.edges} != street_ids:
        raise FlowCompileError("street graph edges do not match the generated town")


def simulation_package_checksum(package: SimulationPackage) -> str:
    payload = canonical_json(package.model_dump(mode="json")).encode("utf-8")
    return sha256(payload).hexdigest()
