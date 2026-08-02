from app.engine import (
    initial_simulation_state,
    project_flow_snapshot,
    step_simulation,
)
from app.flow import compile_flow
from app.models import TownGenerationRequest
from app.town import generate_town


def _package():
    town = generate_town(TownGenerationRequest(generation_seed=23, population=2400))
    return compile_flow(town)


def test_v2_state_uses_queues_and_public_snapshot_hides_buckets() -> None:
    package = _package()
    state = initial_simulation_state(package)
    snapshot = project_flow_snapshot(state, package)

    assert snapshot.schema_version == 2
    assert snapshot.tick == 0
    assert not hasattr(snapshot, "transit_buckets")
    assert snapshot.totals["pedestrian"] == 2400
    assert snapshot.totals["vehicle"] == 30
    assert all(
        len(queue) == connection.travel_time_ticks[flow_id]
        for connection in package.connections
        for flow_id, queue in state.transit_queues[connection.id].items()
    )


def test_v2_engine_is_deterministic_and_conserves_population() -> None:
    package = _package()
    first = initial_simulation_state(package)
    second = initial_simulation_state(package)
    for _ in range(80):
        first = step_simulation(package, first, seed=91)
        second = step_simulation(package, second, seed=91)

    assert first.tick == 80
    assert first.location_counts == second.location_counts
    assert {
        flow_id: sum(queue)
        for queues in first.transit_queues.values()
        for flow_id, queue in queues.items()
    }  # smoke-check all queues remain iterable
    snapshot = project_flow_snapshot(first, package)
    assert snapshot.totals == {"pedestrian": 2400, "vehicle": 30}
    assert all(
        sum(location.get(flow_id, 0) for location in snapshot.location_counts.values())
        + sum(values[flow_id].in_transit for values in snapshot.connections.values())
        == snapshot.totals[flow_id]
        for flow_id in snapshot.totals
    )
