from app.flow import compile_flow, simulation_package_checksum
from app.models import TownGenerationRequest
from app.town import generate_town


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
    assert {
        street_id
        for connection in package.connections
        for street_id in connection.street_segment_ids
    } == street_ids
    for connection in package.connections:
        assert set(connection.street_segment_ids) <= street_ids
        assert connection.path[0] == locations[connection.from_location_id].position
        assert connection.path[-1] == locations[connection.to_location_id].position
        assert connection.travel_time_ticks["pedestrian"] >= connection.travel_time_ticks["vehicle"]
        assert connection.capacity_per_tick["pedestrian"] >= connection.capacity_per_tick["vehicle"]


def test_seed_changes_compiled_package() -> None:
    first = compile_flow(_town(seed=1))
    second = compile_flow(_town(seed=2))

    assert simulation_package_checksum(first) != simulation_package_checksum(second)
