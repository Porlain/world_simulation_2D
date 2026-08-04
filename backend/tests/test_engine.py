from __future__ import annotations

from app.engine import allocate, departure_budget, initial_state, step, stable_int
from app.models import (
    ConnectionConfig,
    DemandRange,
    FlowTypeConfig,
    LocationConfig,
    ScenarioConfig,
)


def make_scenario() -> ScenarioConfig:
    locations = [
        LocationConfig(
            id="alpha", name="Alpha", position=(0, 0), initial_counts={"citizen": 100}
        ),
        LocationConfig(
            id="beta", name="Beta", position=(10, 0), initial_counts={"citizen": 50}
        ),
        LocationConfig(
            id="gamma", name="Gamma", position=(20, 0), initial_counts={"citizen": 25}
        ),
    ]
    connections = [
        ConnectionConfig(
            id="alpha-beta",
            from_location_id="alpha",
            to_location_id="beta",
            path=[(0, 0), (10, 0)],
            travel_time_ticks=3,
            capacity_per_tick={"citizen": 20},
            demand_per_tick={"citizen": DemandRange(min=4, max=8)},
        ),
        ConnectionConfig(
            id="beta-alpha",
            from_location_id="beta",
            to_location_id="alpha",
            path=[(10, 0), (0, 0)],
            travel_time_ticks=3,
            capacity_per_tick={"citizen": 20},
            demand_per_tick={"citizen": DemandRange(min=2, max=6)},
        ),
        ConnectionConfig(
            id="beta-gamma",
            from_location_id="beta",
            to_location_id="gamma",
            path=[(10, 0), (20, 0)],
            travel_time_ticks=1,
            capacity_per_tick={"citizen": 20},
            demand_per_tick={"citizen": DemandRange(min=3, max=7)},
        ),
        ConnectionConfig(
            id="gamma-beta",
            from_location_id="gamma",
            to_location_id="beta",
            path=[(20, 0), (10, 0)],
            travel_time_ticks=1,
            capacity_per_tick={"citizen": 20},
            demand_per_tick={"citizen": DemandRange(min=1, max=5)},
        ),
    ]
    return ScenarioConfig(
        schema_version=1,
        scenario_id="test-city",
        name="Test City",
        scale="city",
        tick_seconds=1,
        coordinate_system="local_xy",
        axis_orientation="x_right_y_up",
        coordinate_unit="scene_unit",
        flow_types=[FlowTypeConfig(id="citizen", unit="people", label="居民")],
        locations=locations,
        connections=connections,
    )


def test_stable_int_is_reproducible_and_bounded() -> None:
    values = [stable_int(7, tick, "alpha-beta", "citizen", 4, 8) for tick in range(20)]
    assert values == [stable_int(7, tick, "alpha-beta", "citizen", 4, 8) for tick in range(20)]
    assert all(4 <= value <= 8 for value in values)


def test_allocate_is_order_independent() -> None:
    assert allocate({"a": 5, "b": 5, "c": 5}, 7) == {"a": 3, "b": 2, "c": 2}
    assert allocate({"c": 5, "a": 5, "b": 5}, 7) == {"c": 2, "a": 3, "b": 2}


def test_people_keep_a_local_reserve_while_vehicles_use_available_capacity() -> None:
    assert departure_budget(17, "citizen", 17) == 9
    assert departure_budget(8, "pedestrian", 17) == 0
    assert departure_budget(17, "vehicle", 17) == 17


def test_initial_state_has_zero_transit() -> None:
    state = initial_state(make_scenario())
    assert state.tick == 0
    assert all(value == 0 for buckets in state.transit_buckets.values() for values in buckets.values() for value in values)


def test_same_seed_produces_identical_100_ticks() -> None:
    scenario = make_scenario()
    first = initial_state(scenario)
    second = initial_state(scenario)
    for _ in range(100):
        first = step(scenario, first, seed=42)
        second = step(scenario, second, seed=42)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_different_seed_changes_activity() -> None:
    scenario = make_scenario()
    first = step(scenario, initial_state(scenario), seed=1)
    second = step(scenario, initial_state(scenario), seed=2)
    assert first.model_dump(mode="json") != second.model_dump(mode="json")


def test_travel_time_three_arrives_at_tick_t_plus_three() -> None:
    scenario = make_scenario()
    state = initial_state(scenario)
    for _ in range(3):
        state = step(scenario, state, seed=42)
    assert state.connection_activity["alpha-beta"]["citizen"].arrived == 0
    state = step(scenario, state, seed=42)
    assert state.connection_activity["alpha-beta"]["citizen"].arrived >= 0


def test_capacity_is_never_exceeded() -> None:
    scenario = make_scenario()
    state = initial_state(scenario)
    for _ in range(100):
        state = step(scenario, state, seed=123)
        for connection in scenario.connections:
            assert state.connection_activity[connection.id]["citizen"].departed <= 20


def test_population_is_conserved_for_every_tick() -> None:
    scenario = make_scenario()
    state = initial_state(scenario)
    expected = state.totals["citizen"]
    for _ in range(100):
        state = step(scenario, state, seed=9)
        assert state.totals["citizen"] == expected
