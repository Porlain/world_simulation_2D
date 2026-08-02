from __future__ import annotations

import math
import secrets
from hashlib import sha256

from .models import (
    Coordinate,
    TownBuilding,
    TownDistrict,
    TownGenerationRequest,
    TownJunction,
    TownLandmark,
    TownSkeleton,
    TownStreet,
)
from .scenario import canonical_json

GENERATOR_VERSION = "radial-v1"
BOUNDARY_POINTS = 16
SPECIAL_BUILDING_KINDS = (
    "administrative",
    "market",
    "religious",
    "military",
    "storage",
    "workshop",
    "stable",
)


class TownGenerationError(ValueError):
    """Raised when generated geometry violates the canonical town contract."""


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return min(maximum, max(minimum, value))


def stable_float(seed: int, namespace: str, ordinal: int) -> float:
    payload = f"{GENERATOR_VERSION}:{seed}:{namespace}:{ordinal}".encode("utf-8")
    number = int.from_bytes(sha256(payload).digest()[:8], "big")
    return number / 2**64


def _point(x: float, y: float) -> Coordinate:
    return (round(x, 6), round(y, 6))


def _lerp(left: Coordinate, right: Coordinate, fraction: float) -> Coordinate:
    return _point(
        left[0] + (right[0] - left[0]) * fraction,
        left[1] + (right[1] - left[1]) * fraction,
    )


def _centroid(polygon: list[Coordinate]) -> Coordinate:
    return _point(
        sum(point[0] for point in polygon) / len(polygon),
        sum(point[1] for point in polygon) / len(polygon),
    )


def _shrink(polygon: list[Coordinate], amount: float) -> list[Coordinate]:
    center = _centroid(polygon)
    return [_lerp(point, center, amount) for point in polygon]


def _distance(left: Coordinate, right: Coordinate) -> float:
    return math.hypot(right[0] - left[0], right[1] - left[1])


def _polygon_area(polygon: list[Coordinate]) -> float:
    return abs(
        sum(
            left[0] * right[1] - right[0] * left[1]
            for left, right in zip(polygon, polygon[1:] + polygon[:1])
        )
    ) / 2


def _angular_distance(left: float, right: float) -> float:
    difference = abs((left - right) % (2 * math.pi))
    return min(difference, 2 * math.pi - difference)


def _boundary_radius(radii: list[float], angle: float) -> float:
    position = (angle % (2 * math.pi)) * len(radii) / (2 * math.pi)
    index = math.floor(position)
    fraction = position - index
    return radii[index % len(radii)] * (1 - fraction) + radii[(index + 1) % len(radii)] * fraction


def _scenario_id(seed: int, population: int) -> str:
    payload = f"{GENERATOR_VERSION}:{seed}:{population}".encode("utf-8")
    return f"town-{sha256(payload).hexdigest()[:16]}"


def _gate_points(boundary: list[Coordinate]) -> dict[str, Coordinate]:
    directions = {
        "east": 0.0,
        "north": math.pi / 2,
        "west": math.pi,
        "south": 3 * math.pi / 2,
    }
    edge_midpoints = [
        _lerp(boundary[index], boundary[(index + 1) % len(boundary)], 0.5)
        for index in range(len(boundary))
    ]
    return {
        name: min(
            edge_midpoints,
            key=lambda point: (
                _angular_distance(math.atan2(point[1], point[0]), target_angle),
                point[0],
                point[1],
            ),
        )
        for name, target_angle in directions.items()
    }


def _building_kind_targets(radius: float, gates: dict[str, Coordinate]) -> dict[str, Coordinate]:
    return {
        "administrative": (0.0, 0.0),
        "market": (radius * 0.18, 0.0),
        "religious": (-radius * 0.14, radius * 0.1),
        "military": gates["north"],
        "storage": gates["south"],
        "workshop": (radius * 0.62, -radius * 0.18),
        "stable": gates["east"],
    }


def _assign_building_kinds(
    buildings: list[dict[str, object]],
    seed: int,
    radius: float,
    gates: dict[str, Coordinate],
) -> dict[str, str]:
    assigned: set[str] = set()
    representatives: dict[str, str] = {}
    for kind, target in _building_kind_targets(radius, gates).items():
        candidate = min(
            (building for building in buildings if building["id"] not in assigned),
            key=lambda building: (
                _distance(building["anchor"], target),  # type: ignore[arg-type]
                str(building["id"]),
            ),
        )
        candidate["kind"] = kind
        building_id = str(candidate["id"])
        assigned.add(building_id)
        representatives[kind] = building_id

    for ordinal, building in enumerate(buildings):
        if building["id"] in assigned:
            continue
        anchor = building["anchor"]
        distance_ratio = _distance(anchor, (0.0, 0.0)) / radius  # type: ignore[arg-type]
        roll = stable_float(seed, "building-kind", ordinal)
        if distance_ratio > 0.62 and roll < 0.05:
            building["kind"] = "workshop"
        elif distance_ratio > 0.62 and roll < 0.08:
            building["kind"] = "storage"
        elif distance_ratio > 0.62 and roll < 0.11:
            building["kind"] = "stable"
        elif distance_ratio < 0.42 and roll < 0.04:
            building["kind"] = "market"
        elif distance_ratio < 0.42 and roll < 0.065:
            building["kind"] = "religious"
    return representatives


def _district_kind(building_kinds: list[str]) -> str:
    priority = (
        ("administrative", "civic"),
        ("military", "military"),
        ("market", "market"),
        ("religious", "religious"),
        ("storage", "storage"),
        ("workshop", "industrial"),
        ("stable", "stable"),
    )
    for building_kind, district_kind in priority:
        if building_kind in building_kinds:
            return district_kind
    return "residential"


def _landmarks(
    buildings: list[TownBuilding],
    representatives: dict[str, str],
    gates: dict[str, Coordinate],
) -> list[TownLandmark]:
    building_by_id = {building.id: building for building in buildings}
    labels = {
        "administrative": "Town Hall",
        "market": "Market",
        "religious": "Temple",
        "military": "Barracks",
        "storage": "Granary",
        "workshop": "Workshop",
        "stable": "Stables",
    }
    landmarks = [
        TownLandmark(id="landmark-plaza", kind="plaza", name="Central Plaza", position=(0.0, 0.0))
    ]
    for direction in ("north", "east", "south", "west"):
        landmarks.append(
            TownLandmark(
                id=f"landmark-{direction}-gate",
                kind="gate",
                name=f"{direction.title()} Gate",
                position=gates[direction],
            )
        )
    for kind in SPECIAL_BUILDING_KINDS:
        building = building_by_id[representatives[kind]]
        landmarks.append(
            TownLandmark(
                id=f"landmark-{kind}",
                building_id=building.id,
                kind=kind,  # type: ignore[arg-type]
                name=labels[kind],
                position=building.anchor,
            )
        )
    return sorted(landmarks, key=lambda landmark: landmark.id)


def generate_town(request: TownGenerationRequest) -> TownSkeleton:
    seed = request.generation_seed if request.generation_seed is not None else secrets.randbits(53)
    population = request.population
    name = request.name or f"Town-{seed}"
    target_buildings = _clamp(math.ceil(population / 20), 40, 2000)
    ring_count = _clamp(math.ceil(math.sqrt(target_buildings / 8)), 2, 8)
    sector_count = _clamp(math.ceil(target_buildings / (ring_count * 3)), 8, 32)
    town_radius = max(180.0, math.sqrt(target_buildings) * 20)

    boundary_radii = [
        town_radius * (0.92 + 0.16 * stable_float(seed, "boundary-radius", index))
        for index in range(BOUNDARY_POINTS)
    ]
    boundary = [
        _point(
            boundary_radii[index] * math.cos(2 * math.pi * index / BOUNDARY_POINTS),
            boundary_radii[index] * math.sin(2 * math.pi * index / BOUNDARY_POINTS),
        )
        for index in range(BOUNDARY_POINTS)
    ]
    gates = _gate_points(boundary)

    sector_angles = [2 * math.pi * index / sector_count for index in range(sector_count)]
    ring_ratios = [0.18 + 0.82 * index / ring_count for index in range(ring_count + 1)]
    grid: dict[tuple[int, int], Coordinate] = {}
    junctions = [TownJunction(id="junction-plaza", position=(0.0, 0.0), kind="plaza")]
    for ring_index, ratio in enumerate(ring_ratios):
        for sector_index, angle in enumerate(sector_angles):
            radius = _boundary_radius(boundary_radii, angle) * ratio
            position = _point(radius * math.cos(angle), radius * math.sin(angle))
            grid[(ring_index, sector_index)] = position
            junctions.append(
                TownJunction(
                    id=f"junction-r{ring_index:02d}-s{sector_index:02d}",
                    position=position,
                    kind="normal",
                )
            )
    for direction, position in gates.items():
        junctions.append(TownJunction(id=f"junction-gate-{direction}", position=position, kind="gate"))

    direction_angles = {"east": 0.0, "north": math.pi / 2, "west": math.pi, "south": 3 * math.pi / 2}
    main_sector_by_direction = {
        direction: min(
            range(sector_count),
            key=lambda index: (_angular_distance(sector_angles[index], angle), index),
        )
        for direction, angle in direction_angles.items()
    }
    main_sectors = set(main_sector_by_direction.values())
    streets: list[TownStreet] = []
    for ring_index in range(ring_count):
        for sector_index in range(sector_count):
            next_sector = (sector_index + 1) % sector_count
            streets.append(
                TownStreet(
                    id=f"street-ring-r{ring_index:02d}-s{sector_index:02d}",
                    from_junction_id=f"junction-r{ring_index:02d}-s{sector_index:02d}",
                    to_junction_id=f"junction-r{ring_index:02d}-s{next_sector:02d}",
                    path=[grid[(ring_index, sector_index)], grid[(ring_index, next_sector)]],
                    width=6.0,
                    kind="ring",
                )
            )
    for ring_index in range(ring_count):
        for sector_index in range(sector_count):
            primary = sector_index in main_sectors
            streets.append(
                TownStreet(
                    id=f"street-radial-r{ring_index:02d}-s{sector_index:02d}",
                    from_junction_id=f"junction-r{ring_index:02d}-s{sector_index:02d}",
                    to_junction_id=f"junction-r{ring_index + 1:02d}-s{sector_index:02d}",
                    path=[grid[(ring_index, sector_index)], grid[(ring_index + 1, sector_index)]],
                    width=8.0 if primary else 4.0,
                    kind="primary" if primary else "secondary",
                )
            )
    for sector_index in sorted(main_sectors):
        streets.append(
            TownStreet(
                id=f"street-plaza-s{sector_index:02d}",
                from_junction_id="junction-plaza",
                to_junction_id=f"junction-r00-s{sector_index:02d}",
                path=[(0.0, 0.0), grid[(0, sector_index)]],
                width=8.0,
                kind="primary",
            )
        )
    for direction, sector_index in main_sector_by_direction.items():
        streets.append(
            TownStreet(
                id=f"street-gate-{direction}",
                from_junction_id=f"junction-gate-{direction}",
                to_junction_id=f"junction-r{ring_count:02d}-s{sector_index:02d}",
                path=[gates[direction], grid[(ring_count, sector_index)]],
                width=8.0,
                kind="primary",
            )
        )

    block_count = ring_count * sector_count
    base_lots, extra_lots = divmod(target_buildings, block_count)
    district_polygons: dict[str, list[Coordinate]] = {}
    building_rows: list[dict[str, object]] = []
    building_ordinal = 0
    block_ordinal = 0
    for ring_index in range(ring_count):
        for sector_index in range(sector_count):
            next_sector = (sector_index + 1) % sector_count
            district_id = f"district-r{ring_index:02d}-s{sector_index:02d}"
            polygon = [
                grid[(ring_index, sector_index)],
                grid[(ring_index + 1, sector_index)],
                grid[(ring_index + 1, next_sector)],
                grid[(ring_index, next_sector)],
            ]
            district_polygons[district_id] = polygon
            inset = _shrink(polygon, 0.12)
            lot_count = base_lots + (1 if block_ordinal < extra_lots else 0)
            if not 1 <= lot_count <= 8:
                raise TownGenerationError("radial-v1 produced an invalid lot count")
            for lot_index in range(lot_count):
                start = lot_index / lot_count
                end = (lot_index + 1) / lot_count
                lot = [
                    _lerp(inset[0], inset[3], start),
                    _lerp(inset[1], inset[2], start),
                    _lerp(inset[1], inset[2], end),
                    _lerp(inset[0], inset[3], end),
                ]
                footprint = _shrink(lot, 0.15)
                building_rows.append(
                    {
                        "id": f"building-{building_ordinal:04d}",
                        "district_id": district_id,
                        "kind": "residential",
                        "polygon": footprint,
                        "anchor": _centroid(footprint),
                    }
                )
                building_ordinal += 1
            block_ordinal += 1

    representatives = _assign_building_kinds(building_rows, seed, town_radius, gates)
    buildings = [TownBuilding.model_validate(row) for row in building_rows]
    buildings_by_district: dict[str, list[str]] = {district_id: [] for district_id in district_polygons}
    for building in buildings:
        buildings_by_district[building.district_id].append(building.kind)
    districts = [
        TownDistrict(
            id=district_id,
            kind=_district_kind(buildings_by_district[district_id]),  # type: ignore[arg-type]
            polygon=polygon,
        )
        for district_id, polygon in sorted(district_polygons.items())
    ]

    skeleton = TownSkeleton(
        scenario_id=_scenario_id(seed, population),
        name=name,
        generation_seed=seed,
        requested_population=population,
        initial_vehicle_count=_clamp(math.floor(population / 80 + 0.5), 5, 1000),
        bounds=(
            min(point[0] for point in boundary),
            min(point[1] for point in boundary),
            max(point[0] for point in boundary),
            max(point[1] for point in boundary),
        ),
        boundary=boundary,
        districts=districts,
        buildings=buildings,
        junctions=sorted(junctions, key=lambda junction: junction.id),
        streets=sorted(streets, key=lambda street: street.id),
        landmarks=_landmarks(buildings, representatives, gates),
    )
    assert_town_invariants(skeleton, target_buildings)
    return skeleton


def assert_town_invariants(town: TownSkeleton, target_buildings: int | None = None) -> None:
    collections = (town.districts, town.buildings, town.junctions, town.streets, town.landmarks)
    for values in collections:
        ids = [value.id for value in values]
        if len(ids) != len(set(ids)):
            raise TownGenerationError("generated town contains duplicate ids")

    district_ids = {district.id for district in town.districts}
    junction_by_id = {junction.id: junction for junction in town.junctions}
    building_ids = {building.id for building in town.buildings}
    if any(building.district_id not in district_ids for building in town.buildings):
        raise TownGenerationError("building references an unknown district")
    for street in town.streets:
        source = junction_by_id.get(street.from_junction_id)
        destination = junction_by_id.get(street.to_junction_id)
        if source is None or destination is None:
            raise TownGenerationError("street references an unknown junction")
        if street.path[0] != source.position or street.path[-1] != destination.position:
            raise TownGenerationError("street path does not match its junctions")
        if _distance(street.path[0], street.path[-1]) <= 0:
            raise TownGenerationError("street has zero length")
    if any(landmark.building_id not in building_ids for landmark in town.landmarks if landmark.building_id):
        raise TownGenerationError("landmark references an unknown building")
    if sum(junction.kind == "gate" for junction in town.junctions) != 4:
        raise TownGenerationError("town must contain four gates")
    if len(town.boundary) != BOUNDARY_POINTS or _polygon_area(town.boundary) <= 0:
        raise TownGenerationError("town boundary is invalid")
    if any(_polygon_area(district.polygon) <= 0 for district in town.districts):
        raise TownGenerationError("district polygon is invalid")
    if any(_polygon_area(building.polygon) <= 0 for building in town.buildings):
        raise TownGenerationError("building polygon is invalid")
    if target_buildings is not None and len(town.buildings) != target_buildings:
        raise TownGenerationError("building count does not match its target")


def town_skeleton_checksum(town: TownSkeleton) -> str:
    payload = canonical_json(town.model_dump(mode="json")).encode("utf-8")
    return sha256(payload).hexdigest()
