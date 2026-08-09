import math

from app.flow import compile_flow, simulation_package_checksum
from app.models import TownGenerationRequest
from app.town import generate_town
from app.watabou_importer import generate_watabou_town


def _town(seed: int = 42, population: int = 12_000):
    return generate_town(
        TownGenerationRequest(generation_seed=seed, population=population, name="Flowtown")
    )


def test_flow_compiler_is_deterministic_and_conserves_both_flows() -> None:
    town = _town()
    first = compile_flow(town)
    second = compile_flow(town)

    assert first == second
    assert simulation_package_checksum(first) == simulation_package_checksum(second)
    assert len(first.locations) == len(town.districts) + 12
    assert sum(location.initial_counts["pedestrian"] for location in first.locations) == 12_000
    assert sum(location.initial_counts["vehicle"] for location in first.locations) == 150
    assert {flow.id for flow in first.flow_types} == {"pedestrian", "vehicle"}


def test_connections_are_bound_to_streets_and_location_endpoints() -> None:
    town = _town(seed=8815907750467, population=11_499)
    package = compile_flow(town)
    locations = {location.id: location for location in package.locations}
    street_ids = {street.id for street in town.streets}

    assert set(package.bindings.location_feature_ids) == set(locations)
    assert "landmark-plaza" in package.bindings.location_feature_ids["location-plaza"]
    assert "landmark-north-gate" in package.bindings.location_feature_ids["location-gate-north"]
    bound_features = {
        feature_id
        for feature_ids in package.bindings.location_feature_ids.values()
        for feature_id in feature_ids
    }
    assert {district.id for district in town.districts} <= bound_features
    assert {building.id for building in town.buildings} <= bound_features
    for district in town.districts:
        assert district.id in package.bindings.location_feature_ids[f"location-{district.id}"]
    for kind in ("administrative", "market", "military", "religious", "stable", "storage", "workshop"):
        location = next(
            item for item in package.locations if item.id == f"location-landmark-{kind}"
        )
        assert location.initial_counts["pedestrian"] > 0
    assert set(package.bindings.connection_street_ids) == {connection.id for connection in package.connections}
    assert package.street_graph is not None
    assert package.street_graph.junctions == town.junctions
    assert package.street_graph.edges == town.streets
    streets_by_id = {street.id: street for street in town.streets}
    assert {
        street_id
        for connection in package.connections
        for street_id in connection.street_segment_ids
    } == street_ids
    for connection in package.connections:
        assert set(connection.street_segment_ids) <= street_ids
        assert len(connection.street_directions) == len(connection.street_segment_ids)
        assert connection.path[0] == locations[connection.from_location_id].position
        assert connection.path[-1] == locations[connection.to_location_id].position
        for flow_id, access_name in (("pedestrian", "pedestrian_access"), ("vehicle", "vehicle_access")):
            route_ids = connection.flow_street_segment_ids.get(flow_id, connection.street_segment_ids)
            route_directions = connection.flow_street_directions.get(flow_id, connection.street_directions)
            assert len(route_ids) == len(route_directions)
            assert all(getattr(streets_by_id[street_id], access_name) for street_id in route_ids)
            if connection.capacity_per_tick[flow_id] > 0:
                assert route_ids
                assert connection.travel_time_ticks[flow_id] >= 1


def test_seed_changes_compiled_package() -> None:
    first = compile_flow(_town(seed=1))
    second = compile_flow(_town(seed=2))

    assert simulation_package_checksum(first) != simulation_package_checksum(second)


def test_watabou_routes_use_gaps_for_people_and_width_for_vehicles() -> None:
    town = generate_watabou_town(
        TownGenerationRequest(generation_seed=42, population=12_000, generation_size="town")
    )
    package = compile_flow(town)
    streets = {street.id: street for street in town.streets}
    bound_features = {
        feature_id
        for feature_ids in package.bindings.location_feature_ids.values()
        for feature_id in feature_ids
    }
    pedestrian_routes = [
        connection.flow_street_segment_ids["pedestrian"]
        for connection in package.connections
        if connection.flow_street_segment_ids["pedestrian"]
    ]
    vehicle_routes = [
        connection.flow_street_segment_ids["vehicle"]
        for connection in package.connections
        if connection.flow_street_segment_ids["vehicle"]
    ]

    assert any(any(streets[street_id].kind == "alley" for street_id in route) for route in pedestrian_routes)
    assert all(all(streets[street_id].pedestrian_access for street_id in route) for route in pedestrian_routes)
    assert all(all(streets[street_id].vehicle_access for street_id in route) for route in vehicle_routes)
    assert any(any(streets[street_id].kind == "lane" for street_id in route) for route in vehicle_routes)
    assert {street_id for route in pedestrian_routes for street_id in route} == set(streets)
    assert {street_id for route in vehicle_routes for street_id in route} == {
        street.id
        for street in town.streets
        if street.vehicle_access and street.width >= 3
    }
    assert town.walkways
    assert {walkway.id for walkway in town.walkways} <= bound_features
    assert all(walkway.pedestrian_access for walkway in town.walkways)
    assert all(not walkway.vehicle_access for walkway in town.walkways)
    assert all(walkway.width < 3 for walkway in town.walkways)
    walkway_points = {point for walkway in town.walkways for point in walkway.path}
    assert any(
        any(point in walkway_points for point in connection.flow_paths["pedestrian"][1:-1])
        for connection in package.connections
        if connection.flow_paths.get("pedestrian")
    )


def _point_in_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        if (current[1] > y) != (previous[1] > y):
            edge_x = (previous[0] - current[0]) * (y - current[1]) / (previous[1] - current[1]) + current[0]
            if x < edge_x:
                inside = not inside
        previous = current
    return inside


def _polygon_area(polygon: list[tuple[float, float]]) -> float:
    return abs(sum(
        left[0] * right[1] - right[0] * left[1]
        for left, right in zip(polygon, polygon[1:] + polygon[:1])
    )) / 2


def _path_samples(path: list[tuple[float, float]], step: float = 1.0):
    for left, right in zip(path, path[1:]):
        length = math.dist(left, right)
        count = max(1, math.ceil(length / step))
        for index in range(count + 1):
            ratio = index / count
            yield (
                left[0] + (right[0] - left[0]) * ratio,
                left[1] + (right[1] - left[1]) * ratio,
            )


def test_watabou_rendered_transport_paths_stay_outside_buildings() -> None:
    town = generate_watabou_town(
        TownGenerationRequest(generation_seed=8142488992956756, population=11_499, generation_size="town")
    )
    building_polygons = [
        (
            (
                min(point[0] for point in building.polygon),
                min(point[1] for point in building.polygon),
                max(point[0] for point in building.polygon),
                max(point[1] for point in building.polygon),
            ),
            building.polygon,
        )
        for building in town.buildings
    ]

    def touches_building(path: list[tuple[float, float]]) -> bool:
        return any(
            _point_in_polygon(point, polygon)
            for point in _path_samples(path)
            for (min_x, min_y, max_x, max_y), polygon in building_polygons
            if min_x <= point[0] <= max_x and min_y <= point[1] <= max_y
        )

    assert town.streets
    assert town.walkways
    assert all(not touches_building(street.path) for street in town.streets)
    assert all(not touches_building(walkway.path) for walkway in town.walkways)
    assert any(street.kind == "alley" and not street.vehicle_access for street in town.streets)
    assert any(street.kind == "lane" and street.vehicle_access for street in town.streets)
    occupied_area = sum(_polygon_area(building.polygon) for building in town.buildings)
    district_area = sum(_polygon_area(district.polygon) for district in town.districts)
    assert 0.5 < occupied_area / district_area < 0.8
