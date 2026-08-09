from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from app.models import TownGenerationRequest
from app.town import BOUNDARY_POINTS, generate_town, town_skeleton_checksum
from app.watabou_importer import generate_watabou_town


def test_same_request_generates_identical_town() -> None:
    request = TownGenerationRequest(
        generation_seed=8815907750467,
        population=11499,
        name="Alimontalle",
    )

    first = generate_town(request)
    second = generate_town(request)

    assert first == second
    assert town_skeleton_checksum(first) == town_skeleton_checksum(second)
    assert first.name == "Alimontalle"
    assert len(first.buildings) == math.ceil(11499 / 20)
    assert first.initial_vehicle_count == 144


def test_different_seed_changes_geometry() -> None:
    first = generate_town(TownGenerationRequest(generation_seed=1, population=5000))
    second = generate_town(TownGenerationRequest(generation_seed=2, population=5000))

    assert first.boundary != second.boundary
    assert first.scenario_id != second.scenario_id
    assert first.name != "Town-1"  # no longer falls back to Town-{seed}


@pytest.mark.parametrize(
    ("size", "suffix"),
    [("village", "村"), ("town", "镇"), ("city", "城")],
)
@pytest.mark.parametrize("generator", [generate_town, generate_watabou_town])
def test_generated_name_matches_settlement_scale(generator, size: str, suffix: str) -> None:
    town = generator(TownGenerationRequest(generation_seed=42, population=1000, generation_size=size))
    assert town.name.endswith(suffix)


def test_generated_town_has_complete_geometry_and_function_types() -> None:
    town = generate_town(TownGenerationRequest(generation_seed=42, population=12000))

    assert len(town.boundary) == BOUNDARY_POINTS
    assert sum(junction.kind == "gate" for junction in town.junctions) == 4
    assert {building.kind for building in town.buildings} >= {
        "residential",
        "market",
        "workshop",
        "storage",
        "religious",
        "administrative",
        "military",
        "stable",
    }
    assert {landmark.kind for landmark in town.landmarks} >= {
        "gate",
        "plaza",
        "market",
        "workshop",
        "storage",
        "religious",
        "administrative",
        "military",
        "stable",
    }
    junctions = {junction.id: junction for junction in town.junctions}
    assert all(
        street.kind == "alley" or street.path[0] == junctions[street.from_junction_id].position
        for street in town.streets
    )
    assert all(
        street.kind == "alley" or street.path[-1] == junctions[street.to_junction_id].position
        for street in town.streets
    )


def test_large_population_respects_geometry_cap() -> None:
    town = generate_town(TownGenerationRequest(generation_seed=7, population=100_000))

    assert len(town.buildings) == 2000
    assert town.initial_vehicle_count == 1000
    assert len(town.districts) <= 8 * 32


@pytest.mark.parametrize("population", [99, 100_001])
def test_population_limits_are_validated(population: int) -> None:
    with pytest.raises(ValidationError):
        TownGenerationRequest(generation_seed=1, population=population)


def test_blank_name_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TownGenerationRequest(generation_seed=1, population=1000, name="   ")
