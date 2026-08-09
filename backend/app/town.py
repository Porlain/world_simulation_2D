from __future__ import annotations

import math
import re
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
from .names import generate_district_names, generate_town_name, normalize_town_name
from .scenario import canonical_json

GENERATOR_VERSION = "radial-v1"
BOUNDARY_POINTS = 72
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


def _bezier_mid(
    left: Coordinate, right: Coordinate, fraction: float, offset: float,
) -> Coordinate:
    mx = (left[0] + right[0]) / 2
    my = (left[1] + right[1]) / 2
    dx, dy = right[0] - left[0], right[1] - left[1]
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length
    cx, cy = mx + nx * offset, my + ny * offset
    inv = 1 - fraction
    return _point(
        inv * inv * left[0] + 2 * inv * fraction * cx + fraction * fraction * right[0],
        inv * inv * left[1] + 2 * inv * fraction * cy + fraction * fraction * right[1],
    )


def _curved_path(
    start: Coordinate, end: Coordinate, seed: int, path_id: str,
    *, curve_scale: float = 0.03, steps: int = 2,
) -> list[Coordinate]:
    length = math.hypot(end[0] - start[0], end[1] - start[1])
    if length < 6:
        return [start, end]
    offset = (stable_float(seed, f"{path_id}-o", 0) - 0.5) * curve_scale * length * 2
    points: list[Coordinate] = [start]
    for i in range(1, steps):
        frac = i / steps
        wobble = (stable_float(seed, f"{path_id}-w{i}", i) - 0.5) * length * 0.005 * 2
        points.append(_bezier_mid(start, end, frac, offset + wobble))
    points.append(end)
    return points


def _centroid(polygon: list[Coordinate]) -> Coordinate:
    return _point(
        sum(point[0] for point in polygon) / len(polygon),
        sum(point[1] for point in polygon) / len(polygon),
    )


def _shrink(polygon: list[Coordinate], amount: float) -> list[Coordinate]:
    center = _centroid(polygon)
    return [_lerp(point, center, amount) for point in polygon]


def _jitter_polygon(
    polygon: list[Coordinate], seed: int, namespace: str, amount: float = 0.04
) -> list[Coordinate]:
    """Perturb polygon vertices slightly for a more organic, hand-built look."""
    result: list[Coordinate] = []
    for i, pt in enumerate(polygon):
        jx = (0.5 - stable_float(seed, namespace, i * 2)) * amount * _distance(pt, _centroid(polygon))
        jy = (0.5 - stable_float(seed, namespace, i * 2 + 1)) * amount * _distance(pt, _centroid(polygon))
        result.append(_point(pt[0] + jx, pt[1] + jy))
    return result


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
        "administrative": "行政府邸",
        "market": "集市广场",
        "religious": "古神殿",
        "military": "兵营要塞",
        "storage": "大粮仓",
        "workshop": "工坊区",
        "stable": "马厩场",
    }
    landmarks = [
        TownLandmark(id="landmark-plaza", kind="plaza", name="中央广场", position=(0.0, 0.0))
    ]
    direction_labels = {"north": "北", "east": "东", "south": "南", "west": "西"}
    for direction in ("north", "east", "south", "west"):
        landmarks.append(
            TownLandmark(
                id=f"landmark-{direction}-gate",
                kind="gate",
                name=f"{direction_labels[direction]}城门",
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
    size = request.generation_size or "town"
    name = normalize_town_name(request.name, size) if request.name else generate_town_name(seed, size)
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

    streets: list[TownStreet] = []
    direction_angles = {"east": 0.0, "north": math.pi / 2, "west": math.pi, "south": 3 * math.pi / 2}
    cardinal_sectors: dict[str, int] = {}
    for direction, angle in direction_angles.items():
        cardinal_sectors[direction] = min(
            range(sector_count),
            key=lambda idx: (_angular_distance(sector_angles[idx], angle), idx),
        )

    # ── 8 radial axes: 4 cardinals + 4 diagonals (NE/SE/SW/NW) ──
    diagonal_angles = {
        "ne": math.pi / 4,
        "se": 7 * math.pi / 4,
        "sw": 5 * math.pi / 4,
        "nw": 3 * math.pi / 4,
    }
    diagonal_sectors: dict[str, int] = {}
    for diag_name, angle in diagonal_angles.items():
        diag = min(
            range(sector_count),
            key=lambda idx: (_angular_distance(sector_angles[idx], angle), idx),
        )
        # Don't duplicate a cardinal sector
        if diag not in cardinal_sectors.values():
            diagonal_sectors[diag_name] = diag

    radial_axes: list[tuple[str, int]] = [
        *cardinal_sectors.items(), *diagonal_sectors.items()
    ]

    # ── Ring roads: only inner ring, one middle ring, and outer ring ──
    inner_ring = 0
    outer_ring = ring_count
    middle_candidates = list(range(1, ring_count))
    middle_ring = middle_candidates[len(middle_candidates) // 2] if middle_candidates else -1
    ring_indices: list[int] = [inner_ring]
    if middle_ring > 0:
        ring_indices.append(middle_ring)
    ring_indices.append(outer_ring)

    # ── Radial roads ──
    # 8 major axes (4 cardinal + 4 diagonal): primary/secondary, clearly visible
    for axis_name, sector_index in radial_axes:
        is_cardinal = axis_name in cardinal_sectors
        prev_pt: Coordinate = (0.0, 0.0)
        for ring_index in range(ring_count + 1):
            pt = grid[(ring_index, sector_index)]
            streets.append(
                TownStreet(
                    id=f"street-radial-{axis_name}-r{ring_index:02d}",
                    from_junction_id=(
                        "junction-plaza" if ring_index == 0
                        else f"junction-r{ring_index - 1:02d}-s{sector_index:02d}"
                    ),
                    to_junction_id=f"junction-r{ring_index:02d}-s{sector_index:02d}",
                    path=_curved_path(
                        prev_pt, pt, seed,
                        f"radial-{axis_name}-r{ring_index:02d}",
                        curve_scale=0.06 if is_cardinal else 0.05, steps=3 if is_cardinal else 2,
                    ),
                    width=8.0 if is_cardinal else 5.0,
                    kind="primary" if is_cardinal else "secondary",
                )
            )
            prev_pt = pt

    # Thin lanes on remaining sectors for connectivity (very subtle, almost invisible)
    lane_sectors = set(range(sector_count)) - {s for _, s in radial_axes}
    for sector_index in sorted(lane_sectors):
        prev_pt: Coordinate = (0.0, 0.0)
        for ring_index in range(ring_count + 1):
            pt = grid[(ring_index, sector_index)]
            streets.append(
                TownStreet(
                    id=f"street-lane-s{sector_index:02d}-r{ring_index:02d}",
                    from_junction_id=(
                        "junction-plaza" if ring_index == 0
                        else f"junction-r{ring_index - 1:02d}-s{sector_index:02d}"
                    ),
                    to_junction_id=f"junction-r{ring_index:02d}-s{sector_index:02d}",
                    path=_curved_path(
                        prev_pt, pt, seed,
                        f"lane-s{sector_index:02d}-r{ring_index:02d}",
                        curve_scale=0.02,
                    ),
                    width=1.2,
                    kind="lane",
                )
            )
            prev_pt = pt

    # ── Gate streets ──
    for direction, sector_index in cardinal_sectors.items():
        streets.append(
            TownStreet(
                id=f"street-gate-{direction}",
                from_junction_id=f"junction-gate-{direction}",
                to_junction_id=f"junction-r{ring_count:02d}-s{sector_index:02d}",
                path=_curved_path(
                    gates[direction], grid[(ring_count, sector_index)],
                    seed, f"gate-{direction}", curve_scale=0.06, steps=3,
                ),
                width=8.0,
                kind="primary",
            )
        )

    # ── Ring roads ──
    for ring_index in ring_indices:
        for si in range(sector_count):
            nj = (si + 1) % sector_count
            start = grid[(ring_index, si)]
            end = grid[(ring_index, nj)]
            ring_rad = town_radius * ring_ratios[ring_index]
            streets.append(
                TownStreet(
                    id=f"street-ring-r{ring_index:02d}-s{si:02d}",
                    from_junction_id=f"junction-r{ring_index:02d}-s{si:02d}",
                    to_junction_id=f"junction-r{ring_index:02d}-s{nj:02d}",
                    path=_curved_path(
                        start, end, seed, f"ring-r{ring_index:02d}-s{si:02d}",
                        curve_scale=0.03, steps=3,
                    ),
                    width=6.0,
                    kind="ring",
                )
            )

    # ── Diagonal cross streets ──
    # A few long-ish curved roads that cut across multiple districts at an angle,
    # like the organic diagonal streets in old European towns.
    cross_seed = int(stable_float(seed, "cross-seed", 0) * 2**53)
    cross_count = 2 + ring_count // 2  # 3-6 diagonal cross streets
    for ci in range(cross_count):
        # Pick two junction points in different sectors and different rings
        r1 = int(stable_float(cross_seed, f"cross-{ci}-r1", 0) * ring_count)
        s1 = int(stable_float(cross_seed, f"cross-{ci}-s1", 1) * sector_count) % sector_count
        r2 = int(stable_float(cross_seed, f"cross-{ci}-r2", 2) * (ring_count + 1 - r1)) + r1
        if r2 <= r1:
            r2 = r1 + 1
        s2 = int(stable_float(cross_seed, f"cross-{ci}-s2", 3) * sector_count) % sector_count
        # Ensure the two points are at least 45° apart
        if abs(s1 - s2) < sector_count // 8:
            s2 = (s2 + sector_count // 4) % sector_count

        start = grid[(min(r1, ring_count), s1)]
        end = grid[(min(r2, ring_count), s2)]
        streets.append(
            TownStreet(
                id=f"street-cross-{ci:02d}",
                from_junction_id=f"junction-r{min(r1, ring_count):02d}-s{s1:02d}",
                to_junction_id=f"junction-r{min(r2, ring_count):02d}-s{s2:02d}",
                path=_curved_path(
                    start, end, cross_seed, f"cross-{ci:02d}",
                    curve_scale=0.08, steps=4,
                ),
                width=3.5,
                kind="secondary",
            )
        )

    # ── Alley generation: narrow winding lanes inside each district ──
    alley_ordinal = 0
    for ring_index in range(ring_count):
        for sector_index in range(sector_count):
            next_sector = (sector_index + 1) % sector_count
            # The four corners of this district
            a = grid[(ring_index, sector_index)]           # inner-left
            b = grid[(ring_index + 1, sector_index)]       # outer-left
            d = grid[(ring_index, next_sector)]            # inner-right
            c = grid[(ring_index + 1, next_sector)]        # outer-right

            # Alley 1: crosses from inner edge to outer edge (radial direction)
            t0 = 0.3 + stable_float(seed, f"alley-a-r{ring_index:02d}-s{sector_index:02d}", 0) * 0.4
            t1 = 0.3 + stable_float(seed, f"alley-a-r{ring_index:02d}-s{sector_index:02d}", 1) * 0.4
            alley_start = _lerp(a, d, t0)
            alley_end = _lerp(b, c, t1)
            streets.append(
                TownStreet(
                    id=f"street-alley-{alley_ordinal:04d}",
                    from_junction_id="junction-plaza",  # alleys don't have real junctions
                    to_junction_id="junction-plaza",
                    path=_curved_path(
                        alley_start, alley_end, seed,
                        f"alley-{alley_ordinal:04d}", curve_scale=0.06, steps=2,
                    ),
                    width=1.5,
                    kind="alley",
                )
            )
            alley_ordinal += 1

            # Alley 2 (optional, ~70% chance): crosses laterally between the two radial edges
            if stable_float(seed, f"alley-b-r{ring_index:02d}-s{sector_index:02d}", 2) < 0.7:
                s0 = 0.25 + stable_float(seed, f"alley-b-r{ring_index:02d}-s{sector_index:02d}", 3) * 0.5
                s1 = 0.25 + stable_float(seed, f"alley-b-r{ring_index:02d}-s{sector_index:02d}", 4) * 0.5
                alley_start = _lerp(a, b, s0)
                alley_end = _lerp(d, c, s1)
                streets.append(
                    TownStreet(
                        id=f"street-alley-{alley_ordinal:04d}",
                        from_junction_id="junction-plaza",
                        to_junction_id="junction-plaza",
                        path=_curved_path(
                            alley_start, alley_end, seed,
                            f"alley-{alley_ordinal:04d}", curve_scale=0.06, steps=2,
                        ),
                        width=1.5,
                        kind="alley",
                    )
                )
                alley_ordinal += 1

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
                # Non-uniform lot splits for varied building widths
                jitter_s = stable_float(
                    seed, f"split-s-r{ring_index:02d}-s{sector_index:02d}-l{lot_index}", 0
                ) * 0.15
                jitter_e = stable_float(
                    seed, f"split-e-r{ring_index:02d}-s{sector_index:02d}-l{lot_index}", 1
                ) * 0.15
                start = (lot_index + jitter_s) / lot_count
                end = (lot_index + 1 + jitter_e) / lot_count
                # Clamp to stay within [0, 1] and not overlap
                start = max(lot_index / lot_count, min(start, (lot_index + 0.85) / lot_count))
                end = min((lot_index + 1) / lot_count, max(end, (lot_index + 0.15) / lot_count))
                lot = [
                    _lerp(inset[0], inset[3], start),
                    _lerp(inset[1], inset[2], start),
                    _lerp(inset[1], inset[2], end),
                    _lerp(inset[0], inset[3], end),
                ]
                # Vary shrink per building for organic gaps
                shrink_amt = 0.10 + stable_float(
                    seed, f"shrink-r{ring_index:02d}-s{sector_index:02d}-l{lot_index}", 2
                ) * 0.13
                raw = _shrink(lot, shrink_amt)
                # Slight vertex jitter for hand-built character
                footprint = _jitter_polygon(
                    raw, seed,
                    f"jitter-r{ring_index:02d}-s{sector_index:02d}-l{lot_index}",
                    amount=0.05,
                )
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
        district_names=generate_district_names(seed, districts),
    )
    assert_town_invariants(skeleton, target_buildings)
    return skeleton


def assert_town_invariants(town: TownSkeleton, target_buildings: int | None = None) -> None:
    collections = (
        town.districts,
        town.buildings,
        town.junctions,
        town.streets,
        town.walkways,
        town.landmarks,
    )
    for values in collections:
        ids = [value.id for value in values]
        if len(ids) != len(set(ids)):
            raise TownGenerationError("generated town contains duplicate ids")

    district_ids = {district.id for district in town.districts}
    junction_by_id = {junction.id: junction for junction in town.junctions}
    building_ids = {building.id for building in town.buildings}
    if any(building.district_id not in district_ids for building in town.buildings):
        raise TownGenerationError("building references an unknown district")
    if any(walkway.district_id not in district_ids for walkway in town.walkways):
        raise TownGenerationError("walkway references an unknown district")
    if any(_distance(walkway.path[0], walkway.path[-1]) <= 0 for walkway in town.walkways):
        raise TownGenerationError("walkway has zero length")
    for street in town.streets:
        source = junction_by_id.get(street.from_junction_id)
        destination = junction_by_id.get(street.to_junction_id)
        if source is None or destination is None:
            raise TownGenerationError("street references an unknown junction")
        if street.kind != "alley":
            if street.path[0] != source.position or street.path[-1] != destination.position:
                raise TownGenerationError("street path does not match its junctions")
        if _distance(street.path[0], street.path[-1]) <= 0:
            raise TownGenerationError("street has zero length")
    if any(landmark.building_id not in building_ids for landmark in town.landmarks if landmark.building_id):
        raise TownGenerationError("landmark references an unknown building")
    gate_count = sum(junction.kind == "gate" for junction in town.junctions)
    if town.generator_version == "radial-v1" and gate_count != 4:
        raise TownGenerationError("radial town must contain four gates")
    if town.generator_version == "watabou-v1" and gate_count not in {0, 4}:
        raise TownGenerationError("watabou town must contain zero or four gates")
    if (town.generator_version == "radial-v1" and len(town.boundary) != BOUNDARY_POINTS) or _polygon_area(town.boundary) <= 0:
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
