from app.flow import compile_flow, simulation_package_checksum
from app.models import TownGenerationRequest
from app.town import generate_town


def _town(seed: int = 42, population: int = 12_000):
    return generate_town(
        TownGenerationRequest(generation_seed=seed, population=population, name="Flowtown")
    )


def test_flow_compiler_is_deterministic_and_conserves_both_flows() -> None:
    first = compile_flow(_town())
    second = compile_flow(_town())

    assert first == second
    assert simulation_package_checksum(first) == simulation_package_checksum(second)
    assert len(first.locations) <= 48
    assert sum(location.initial_counts["pedestrian"] for location in first.locations) == 12_000
    assert sum(location.initial_counts["vehicle"] for location in first.locations) == 150
    assert {flow.id for flow in first.flow_types} == {"pedestrian", "vehicle"}


def test_connections_are_bound_to_streets_and_location_endpoints() -> None:
    town = _town(seed=8815907750467, population=11_499)
    package = compile_flow(town)
    locations = {location.id: location for location in package.locations}
    street_ids = {street.id for street in town.streets}

    assert set(package.bindings.location_feature_ids) == set(locations)
    assert set(package.bindings.connection_street_ids) == {connection.id for connection in package.connections}
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
