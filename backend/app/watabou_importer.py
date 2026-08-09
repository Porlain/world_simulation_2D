"""Watabou-style medieval town generator using Voronoi-based organic geometry.

This generates a TownSkeleton by: ... (see module docstring above)
"""

from __future__ import annotations

import math
import random as rand_module
from collections import deque
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

from .models import (
    Coordinate,
    TownBuilding,
    TownDistrict,
    TownGenerationRequest,
    TownJunction,
    TownLandmark,
    TownSkeleton,
    TownStreet,
    TownWalkway,
)
from .names import generate_district_names, generate_town_name, normalize_town_name

GENERATOR_VERSION = "watabou-v1"


# ---------------------------------------------------------------------------
# Deterministic PRNG
# ---------------------------------------------------------------------------

def _stable_float(seed: int, namespace: str, ordinal: int = 0) -> float:
    payload = f"{GENERATOR_VERSION}:{seed}:{namespace}:{ordinal}".encode()
    n = int.from_bytes(sha256(payload).digest()[:8], "big")
    return n / (2**64)


def _stable_shuffle(items: list[Any], seed: int, namespace: str) -> list[Any]:
    pairs = sorted(
        (_stable_float(seed, namespace, i), item) for i, item in enumerate(items)
    )
    return [item for _, item in pairs]


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _point(x: float, y: float) -> Coordinate:
    return (round(x, 6), round(y, 6))


def _centroid(polygon: list[Coordinate]) -> Coordinate:
    return _point(
        sum(p[0] for p in polygon) / len(polygon),
        sum(p[1] for p in polygon) / len(polygon),
    )


def _distance(a: Coordinate, b: Coordinate) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _polygon_area(polygon: list[Coordinate]) -> float:
    return abs(
        sum(
            p0[0] * p1[1] - p1[0] * p0[1]
            for p0, p1 in zip(polygon, polygon[1:] + polygon[:1])
        )
    ) / 2


def _shrink(polygon: list[Coordinate], amount: float) -> list[Coordinate]:
    c = _centroid(polygon)
    return [_point(p[0] + (c[0] - p[0]) * amount, p[1] + (c[1] - p[1]) * amount) for p in polygon]


def _organic_edge_footprint(
    polygon: list[Coordinate],
    patch_shape: list[Coordinate],
    wall_boundary: list[Coordinate],
    walkways: list[list[Coordinate]],
    seed: int,
    ordinal: int,
) -> list[Coordinate]:
    """Rotate and nudge an outer building without crossing its ward or wall."""
    center = _centroid(polygon)
    center_distance = math.hypot(center[0], center[1])
    if center_distance < 0.01:
        return polygon

    outward = (center[0] / center_distance, center[1] / center_distance)
    angle = (_stable_float(seed, "edge-building-angle", ordinal) - 0.5) * 0.2
    shift = 0.2 + _stable_float(seed, "edge-building-shift", ordinal) * 0.65
    cos_angle = math.cos(angle)
    sin_angle = math.sin(angle)

    for strength in (1.0, 0.55, 0.0):
        candidate: list[Coordinate] = []
        for point in polygon:
            dx = point[0] - center[0]
            dy = point[1] - center[1]
            candidate.append(_point(
                center[0] + dx * cos_angle - dy * sin_angle + outward[0] * shift * strength,
                center[1] + dx * sin_angle + dy * cos_angle + outward[1] * shift * strength,
            ))
        if (
            all(_contains(point, patch_shape) and _contains(point, wall_boundary) for point in candidate)
            and not any(_path_crosses_polygon(path, candidate) for path in walkways)
        ):
            return candidate
        angle *= 0.55
        cos_angle = math.cos(angle)
        sin_angle = math.sin(angle)
    return polygon


def _intersection(a: Coordinate, b: Coordinate, c: Coordinate, d: Coordinate) -> Coordinate | None:
    """Line segment intersection AB × CD."""
    denom = (a[0] - b[0]) * (c[1] - d[1]) - (a[1] - b[1]) * (c[0] - d[0])
    if abs(denom) < 1e-10:
        return None
    t = ((a[0] - c[0]) * (c[1] - d[1]) - (a[1] - c[1]) * (c[0] - d[0])) / denom
    u = -((a[0] - b[0]) * (a[1] - c[1]) - (a[1] - b[1]) * (a[0] - c[0])) / denom
    if 0 <= t <= 1 and 0 <= u <= 1:
        return _point(a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
    return None


def _path_crosses_polygon(path: list[Coordinate], polygon: list[Coordinate]) -> bool:
    if any(_contains(point, polygon) for point in path):
        return True
    polygon_edges = list(zip(polygon, polygon[1:] + polygon[:1]))
    return any(
        _intersection(start, end, edge_start, edge_end) is not None
        for start, end in zip(path, path[1:])
        for edge_start, edge_end in polygon_edges
    )


def _poly_cut(
    poly: list[Coordinate], p1: Coordinate, p2: Coordinate
) -> list[list[Coordinate]]:
    """Cut a polygon along the line P1-P2, returning the two halves."""
    n = len(poly)
    hits: list[tuple[int, Coordinate]] = []
    for i in range(n):
        hit = _intersection(poly[i], poly[(i + 1) % n], p1, p2)
        if hit is not None and (not hits or _distance(hit, hits[-1][1]) > 0.1):
            hits.append((i, hit))
    if len(hits) < 2:
        return [poly]
    (i1, h1), (i2, h2) = hits[0], hits[1]
    half_a: list[Coordinate] = [h1]
    idx = (i1 + 1) % n
    while idx != (i2 + 1) % n:
        half_a.append(poly[idx])
        idx = (idx + 1) % n
    half_a.append(h2)

    half_b: list[Coordinate] = [h2]
    idx = (i2 + 1) % n
    while idx != (i1 + 1) % n:
        half_b.append(poly[idx])
        idx = (idx + 1) % n
    half_b.append(h1)

    if _polygon_area(half_a) < 0.1:
        return [half_b]
    if _polygon_area(half_b) < 0.1:
        return [half_a]
    return [half_a, half_b]


# ---------------------------------------------------------------------------
# Voronoi-based town generation
# ---------------------------------------------------------------------------

@dataclass
class Patch:
    shape: list[Coordinate]  # polygon vertices
    ward_kind: str = "residential"
    buildings: list[list[Coordinate]] = field(default_factory=list)
    walkways: list[list[Coordinate]] = field(default_factory=list)
    within_city: bool = False
    within_walls: bool = False
    on_boundary: bool = False


@dataclass
class _WallInfo:
    shape: list[Coordinate]  # boundary polygon
    gates: list[Coordinate]  # gate positions


@dataclass(frozen=True)
class _Artery:
    """A traversable street centerline and its transport classification."""

    path: list[Coordinate]
    kind: str
    width: float
    pedestrian_access: bool = True
    vehicle_access: bool = True


def _resample_polygon(polygon: list[Coordinate], target: int) -> list[Coordinate]:
    """Keep a compact wall for a town and a more circular wall for a city."""
    if target <= 0 or len(polygon) <= target:
        return polygon
    return [polygon[int(index * len(polygon) / target)] for index in range(target)]


def _contains(point: Coordinate, polygon: list[Coordinate]) -> bool:
    inside = False
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        if (start[1] > point[1]) != (end[1] > point[1]):
            x_at_y = (end[0] - start[0]) * (point[1] - start[1]) / (end[1] - start[1]) + start[0]
            if point[0] < x_at_y:
                inside = not inside
    return inside


def _enclosing_boundary(raw: list[Coordinate], target: int | None) -> list[Coordinate]:
    boundary = _resample_polygon(raw, target or len(raw))
    if target is None or len(raw) <= target:
        return boundary
    scale = 1.0
    while scale < 1.35:
        candidate = [_point(point[0] * scale, point[1] * scale) for point in boundary]
        if all(_contains(point, candidate) for point in raw):
            return candidate
        scale += 0.03
    return [_point(point[0] * 1.35, point[1] * 1.35) for point in boundary]


def _generate_watabou_patches(seed: int, size: str = "town") -> tuple[
    list[Patch],
    list[_Artery],  # arteries
    _WallInfo,
    Coordinate,  # center
]:
    """Generate organic blocks from the same principles as TownGeneratorOS.

    TownGeneratorOS builds relaxed Voronoi wards, then derives streets and a
    circumference wall from those wards.  The project intentionally keeps this
    implementation dependency-free, so the ward cells below are generated from
    shared, jittered polar rings. Shared vertices preserve the same continuous
    block topology without requiring a native Voronoi package.
    """
    params: dict[str, tuple[int, int, tuple[float, ...], int | None]] = {
        "village": (2, 8, (28.0, 105.0, 185.0), None),
        # The wall follows the outer ward edge exactly. Towns stay compact
        # with 12 sides; cities get the fuller 20-sided circumference.
        "town": (3, 12, (34.0, 140.0, 255.0, 365.0), 12),
        "city": (4, 20, (42.0, 165.0, 305.0, 450.0, 605.0), 20),
    }
    rings, sectors, radii, wall_vertices = params[size]
    angle_offset = _stable_float(seed, "ward-angle") * (2 * math.pi / sectors)

    ring_points: list[list[Coordinate]] = []
    for ring_index, base_radius in enumerate(radii):
        ring: list[Coordinate] = []
        for sector in range(sectors):
            angle = angle_offset + sector * 2 * math.pi / sectors
            radius = base_radius * (
                0.91 + 0.14 * _stable_float(seed, f"ward-radius-{ring_index}", sector)
            )
            angle += (_stable_float(seed, f"ward-angle-{ring_index}", sector) - 0.5) * 0.06
            ring.append(_point(radius * math.cos(angle), radius * math.sin(angle)))
        ring_points.append(ring)

    center_ring = ring_points[0]
    patches: list[Patch] = [Patch(shape=center_ring, within_city=True, within_walls=size != "village")]
    for ring_index in range(rings):
        inner_ring = ring_points[ring_index]
        outer_ring = ring_points[ring_index + 1]
        for sector in range(sectors):
            next_sector = (sector + 1) % sectors
            shape = [
                inner_ring[sector], outer_ring[sector],
                outer_ring[next_sector], inner_ring[next_sector],
            ]
            patches.append(Patch(
                shape=shape,
                within_city=True,
                within_walls=size != "village",
                on_boundary=ring_index == rings - 1,
            ))

    boundary = _enclosing_boundary(ring_points[-1], wall_vertices)
    gates = _place_gates(boundary) if wall_vertices is not None else []

    center = _point(0.0, 0.0)
    # Streets follow shared ward edges. Connecting ward centroids produces
    # shortcuts through the building footprints generated inside each ward.
    arteries: list[_Artery] = []
    seen_edges: set[tuple[Coordinate, Coordinate]] = set()

    def add(
        start: Coordinate,
        end: Coordinate,
        kind: str,
        width: float,
        vehicle: bool = True,
    ) -> None:
        key = (start, end) if start < end else (end, start)
        if start == end or key in seen_edges:
            return
        seen_edges.add(key)
        arteries.append(_Artery([start, end], kind, width, True, vehicle))

    cardinal = {
        min(range(sectors), key=lambda s: abs(math.atan2(math.sin(angle_offset + s * 2 * math.pi / sectors), math.cos(angle_offset + s * 2 * math.pi / sectors)))),
        min(range(sectors), key=lambda s: abs(math.atan2(math.sin(angle_offset + s * 2 * math.pi / sectors - math.pi / 2), math.cos(angle_offset + s * 2 * math.pi / sectors - math.pi / 2)))),
        min(range(sectors), key=lambda s: abs(math.atan2(math.sin(angle_offset + s * 2 * math.pi / sectors - math.pi), math.cos(angle_offset + s * 2 * math.pi / sectors - math.pi)))),
        min(range(sectors), key=lambda s: abs(math.atan2(math.sin(angle_offset + s * 2 * math.pi / sectors - 3 * math.pi / 2), math.cos(angle_offset + s * 2 * math.pi / sectors - 3 * math.pi / 2)))),
    }
    for ring in ring_points:
        for sector in range(sectors):
            next_sector = (sector + 1) % sectors
            add(ring[sector], ring[next_sector], "ring", 7.0)

    for ring_index in range(len(ring_points) - 1):
        for sector in range(sectors):
            kind = (
                "primary" if sector in cardinal
                else "secondary" if ring_index == 0
                else "lane" if ring_index == 1
                else "alley"
            )
            width = (
                9.0 if kind == "primary"
                else 5.0 if kind == "secondary"
                else 3.5 if kind == "lane"
                else 1.5
            )
            add(
                ring_points[ring_index][sector],
                ring_points[ring_index + 1][sector],
                kind,
                width,
                vehicle=kind != "alley",
            )

    # Keep the central plaza open and connect it to the inner ward boundary.
    for sector in range(sectors):
        add(
            center,
            ring_points[0][sector],
            "primary" if sector in cardinal else "secondary",
            9.0 if sector in cardinal else 5.0,
        )

    for gate in gates:
        target = min(ring_points[-1], key=lambda point: _distance(point, gate))
        add(gate, target, "primary", 9.0)

    wall = _WallInfo(shape=boundary, gates=gates)
    return patches, arteries, wall, center


def _simple_ring(inner: list[Patch]) -> list[Coordinate]:
    """Build a simple boundary ring from outer vertices of inner patches (village outline)."""
    import numpy as np
    all_pts = []
    for p in inner:
        all_pts.extend([[v[0], v[1]] for v in p.shape])
    arr = np.array(all_pts)
    from scipy.spatial import ConvexHull
    hull = ConvexHull(arr)
    hull_pts = [arr[v] for v in hull.vertices]
    n = len(hull_pts)
    target = min(16, n)
    if n > target:
        hull_pts = [hull_pts[int(i * n / target)] for i in range(target)]
    return [_point(float(v[0]), float(v[1])) for v in hull_pts]


def _tight_boundary(inner: list[Patch], target_points: int = 30) -> list[Coordinate]:
    """Compute a boundary polygon that tightly follows the outer edges of inner patches."""
    import numpy as np
    from scipy.spatial import ConvexHull

    raw = _find_circumference(inner)
    if not raw or len(raw) < 3:
        # Fallback: collect all inner shape vertices
        fallback: list[Coordinate] = []
        for p in inner:
            fallback.extend(p.shape)
        raw = fallback

    if len(raw) < 3:
        return list(inner[0].shape)

    pts = np.array([[v[0], v[1]] for v in raw])
    hull = ConvexHull(pts)
    hull_pts = [pts[v] for v in hull.vertices]

    n = len(hull_pts)
    target = min(target_points, n)
    if n > target:
        hull_pts = [hull_pts[int(i * n / target)] for i in range(target)]

    result = []
    for v in hull_pts:
        jx = (0.5 - _stable_float(hash(f"{v[0]:.2f}_{v[1]:.2f}"), "wj", 0)) * 6
        jy = (0.5 - _stable_float(hash(f"{v[0]:.2f}_{v[1]:.2f}"), "wj", 1)) * 6
        result.append(_point(float(v[0]) + jx, float(v[1]) + jy))

    return result


def _convex_hull_of_patches(patches: list[Patch], target_points: int = 64) -> list[Coordinate]:
    """Compute the convex hull of all patch vertices and return a smooth polygon."""
    import numpy as np
    from scipy.spatial import ConvexHull

    pts = []
    for p in patches:
        pts.extend([[v[0], v[1]] for v in p.shape])

    arr = np.array(pts)
    hull = ConvexHull(arr)
    hull_pts = [arr[v] for v in hull.vertices]

    n = len(hull_pts)
    target = min(target_points, n)
    if n > target:
        sampled = [hull_pts[int(i * n / target)] for i in range(target)]
    else:
        sampled = hull_pts

    return [_point(float(v[0]), float(v[1])) for v in sampled]


def _find_circumference(inner: list[Patch]) -> list[Coordinate]:
    """Find the outer boundary polygon of the union of inner patches."""
    if len(inner) == 0:
        return []
    if len(inner) == 1:
        return list(inner[0].shape)

    a_pts: list[Coordinate] = []
    b_pts: list[Coordinate] = []
    for patch in inner:
        s = patch.shape
        for i in range(len(s)):
            p0, p1 = s[i], s[(i + 1) % len(s)]
            outer = True
            for other in inner:
                if other is patch:
                    continue
                if _find_edge_index(other.shape, p1, p0):
                    outer = False
                    break
            if outer:
                a_pts.append(p0)
                b_pts.append(p1)

    result: list[Coordinate] = []
    if not a_pts:
        return list(inner[0].shape)
    idx = 0
    seen: set[int] = set()
    while idx not in seen:
        result.append(a_pts[idx])
        seen.add(idx)
        nxt = -1
        for j, ap in enumerate(a_pts):
            if ap == b_pts[idx]:
                nxt = j
                break
        if nxt == -1 or nxt in seen:
            break
        idx = nxt
    return result


def _find_edge_index(shape: list[Coordinate], a: Coordinate, b: Coordinate) -> int | None:
    for i in range(len(shape)):
        if shape[i] == a and shape[(i + 1) % len(shape)] == b:
            return i
    return None


def _place_gates(boundary: list[Coordinate]) -> list[Coordinate]:
    """Place 4 gates at approximate N/E/S/W directions."""
    if len(boundary) < 4:
        return list(boundary[:4])
    gates = []
    directions = [
        ("north", (0.0, 1.0)),
        ("east", (1.0, 0.0)),
        ("south", (0.0, -1.0)),
        ("west", (-1.0, 0.0)),
    ]
    used: set[int] = set()
    for _, (dx, dy) in directions:
        best_idx, best_dot = -1, float("-inf")
        for i in range(len(boundary)):
            if i in used:
                continue
            bx = boundary[i][0]
            by = boundary[i][1]
            dot = bx * dx + by * dy
            if dot > best_dot:
                best_dot, best_idx = dot, i
        used.add(best_idx)
        gates.append(boundary[best_idx])
    return gates


def _build_streets(
    patches: list[Patch],
    inner: list[Patch],
    gates: list[Coordinate],
    plaza_patch: Patch,
) -> list[list[Coordinate]]:
    """Build a comprehensive street network connecting all city patches."""
    from scipy.spatial import Delaunay as ScipyDelaunay
    import numpy as np

    def _k(pt: Coordinate) -> str:
        return f"{pt[0]:.4f}_{pt[1]:.4f}"

    graph: dict[str, set[str]] = {}
    point_store: dict[str, Coordinate] = {}
    edge_map: dict[tuple[str, str], list[Coordinate]] = {}

    for patch in patches:
        for i in range(len(patch.shape)):
            a = patch.shape[i]
            b = patch.shape[(i + 1) % len(patch.shape)]
            ak, bk = _k(a), _k(b)
            point_store[ak] = a
            point_store[bk] = b
            graph.setdefault(ak, set()).add(bk)
            graph.setdefault(bk, set()).add(ak)
            key = (ak, bk) if ak < bk else (bk, ak)
            edge_map[key] = [a, b]

    centroids = [_centroid(p.shape) for p in inner]
    all_tri_pts = centroids + [g for g in gates] + [_point(0.0, 0.0)]
    tri_pts = np.array(all_tri_pts)

    arteries: list[list[Coordinate]] = []

    if len(tri_pts) >= 4:
        try:
            tri = ScipyDelaunay(tri_pts)
            seen_delaunay: set[tuple[int, int]] = set()
            for simplex in tri.simplices:
                for i in range(3):
                    a_idx, b_idx = simplex[i], simplex[(i + 1) % 3]
                    if a_idx > b_idx:
                        a_idx, b_idx = b_idx, a_idx
                    if (a_idx, b_idx) not in seen_delaunay:
                        seen_delaunay.add((a_idx, b_idx))
                        art = [
                            _point(float(tri_pts[a_idx][0]), float(tri_pts[a_idx][1])),
                            _point(float(tri_pts[b_idx][0]), float(tri_pts[b_idx][1])),
                        ]
                        if _distance(art[0], art[1]) > 20:
                            mx = (art[0][0] + art[1][0]) / 2
                            my = (art[0][1] + art[1][1]) / 2
                            jitter = -4 + 8 * _stable_float(hash(str(a_idx) + str(b_idx)), "curve", 0)
                            dx, dy = art[1][0] - art[0][0], art[1][1] - art[0][1]
                            norm = math.hypot(dx, dy) or 1.0
                            art.insert(1, _point(mx - dy / norm * jitter, my + dx / norm * jitter))
                        arteries.append(art)
        except Exception:
            pass

    # Gate→plaza paths
    center = _point(0.0, 0.0)
    plaza_vertices = list(plaza_patch.shape)
    for gate in gates:
        target = min(plaza_vertices, key=lambda v: _distance(v, gate))
        gk = _k(gate)
        tk = _k(target)
        bpath = _bfs_path(graph, edge_map, point_store, gk, tk)
        if bpath and len(bpath) >= 2:
            arteries.append(bpath)
        else:
            arteries.append([gate, target])

    # Plaza connector
    pv = sorted(plaza_vertices, key=lambda v: _distance(v, center))[0]
    arteries.append([center, pv])

    # Gate ring
    for i, g1 in enumerate(gates):
        g2 = gates[(i + 1) % len(gates)]
        arteries.append([g1, g2])

    return arteries


def _bfs_path(
    graph: dict[str, set[str]],
    edges: dict[tuple[str, str], list[Coordinate]],
    points: dict[str, Coordinate],
    start_key: str,
    end_key: str,
) -> list[Coordinate] | None:
    """BFS on the graph to find a path from start to end, returning coordinates."""
    from collections import deque

    if start_key == end_key:
        return []
    if start_key not in graph or end_key not in graph:
        return None

    queue: deque[tuple[str, list[Coordinate]]] = deque([(start_key, [points[start_key]])])
    visited = {start_key}

    while queue:
        current, path_coords = queue.popleft()
        for neighbor in graph.get(current, set()):
            if neighbor in visited:
                continue
            key = (current, neighbor) if current < neighbor else (neighbor, current)
            seg = edges.get(key)
            next_pt = points[neighbor] if not seg else (seg[1] if seg[0] == points[current] else seg[0])
            new_path = path_coords + [next_pt]
            if neighbor == end_key:
                return new_path
            visited.add(neighbor)
            queue.append((neighbor, new_path))
    return None


# ---------------------------------------------------------------------------
# Building placement — Watabou-style perpendicular bisection (createAlleys)
# ---------------------------------------------------------------------------
# This is a direct reimplementation of the real Watabou Town Generator's
# Ward.createAlleys / Cutter.bisect algorithm:
#   1. Find the longest edge of the block polygon
#   2. Cut perpendicular to that edge at a random ratio
#   3. Gap the cut (ALLEY width) to create an alley between halves
#   4. Recurse on each half until below the size threshold
# This produces rotated rectangular footprints that follow block contours,
# NOT axis-aligned squares.

ALLEY_GAP = 0.6  # matches Watabou's Ward.ALLEY constant
BUILDING_STREET_GAP = 0.75


def _segment_distance(
    left: Coordinate,
    right: Coordinate,
    other_left: Coordinate,
    other_right: Coordinate,
) -> float:
    """Return the shortest distance between two line segments."""
    if _intersection(left, right, other_left, other_right) is not None:
        return 0.0

    def point_to_segment(point: Coordinate, start: Coordinate, end: Coordinate) -> float:
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length_squared = dx * dx + dy * dy
        if length_squared < 1e-12:
            return _distance(point, start)
        t = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared))
        return _distance(point, _point(start[0] + dx * t, start[1] + dy * t))

    return min(
        point_to_segment(left, other_left, other_right),
        point_to_segment(right, other_left, other_right),
        point_to_segment(other_left, left, right),
        point_to_segment(other_right, left, right),
    )


def _path_polygon_distance(path: list[Coordinate], polygon: list[Coordinate]) -> float:
    return min(
        _segment_distance(path_left, path_right, polygon_left, polygon_right)
        for path_left, path_right in zip(path, path[1:])
        for polygon_left, polygon_right in zip(polygon, polygon[1:] + polygon[:1])
    )


def _street_clearance(artery: _Artery) -> float:
    """Reserve the road half-width plus a visible gap around buildings."""
    return artery.width / 2 + BUILDING_STREET_GAP


def _path_near_polygon(
    path: list[Coordinate],
    polygon: list[Coordinate],
    margin: float,
) -> bool:
    """Cheap broad-phase test used before exact segment distance checks."""
    min_x = min(point[0] for point in polygon) - margin
    max_x = max(point[0] for point in polygon) + margin
    min_y = min(point[1] for point in polygon) - margin
    max_y = max(point[1] for point in polygon) + margin
    return any(
        max(min(left[0], right[0]), min_x) <= min(max(left[0], right[0]), max_x)
        and max(min(left[1], right[1]), min_y) <= min(max(left[1], right[1]), max_y)
        for left, right in zip(path, path[1:])
    )


def _clear_building_from_streets(
    polygon: list[Coordinate],
    patch: Patch,
    arteries: list[_Artery],
    walkways: list[list[Coordinate]] | None = None,
) -> list[Coordinate] | None:
    """Keep a footprint outside every artery's physical road corridor.

    Boundary plots can be nudged outward by the organic edge treatment.  A
    final homothetic inset guarantees that the rendered road width still has
    room to exist between the street centerline and a building.
    """
    # Shrink a rejected footprint in place. Using the ward centroid here pulls
    # every edge building toward the middle and creates artificial vacant lots.
    center = _centroid(polygon)

    def acceptable(candidate: list[Coordinate]) -> bool:
        if _polygon_area(candidate) <= 2 or not all(_contains(point, patch.shape) for point in candidate):
            return False
        return all(
            _path_polygon_distance(artery.path, candidate) >= _street_clearance(artery) - 1e-6
            for artery in arteries
        ) and all(_path_polygon_distance(path, candidate) >= 0.12 for path in (walkways or ()))

    if acceptable(polygon):
        return polygon

    for scale in (0.96, 0.92, 0.88, 0.84, 0.80, 0.74, 0.68, 0.60, 0.50, 0.40, 0.30):
        candidate = [
            _point(center[0] + (point[0] - center[0]) * scale, center[1] + (point[1] - center[1]) * scale)
            for point in polygon
        ]
        if acceptable(candidate):
            return candidate
    return None


def _create_buildings(
    patch: Patch,
    arteries: list[_Artery],
    wall_boundary: list[Coordinate],
    size: str = "town",
) -> tuple[list[list[Coordinate]], list[list[Coordinate]]]:
    """Create building footprints via Watabou-style perpendicular bisection."""
    if not patch.within_city:
        return [], []

    block = _inset_for_streets(patch, arteries)
    if block is None or _polygon_area(block) < 10:
        return [], []

    local_arteries = [
        artery
        for artery in arteries
        if _path_near_polygon(artery.path, patch.shape, _street_clearance(artery))
    ]

    block_area = _polygon_area(block)
    patch_key = ":".join(f"{x:.4f},{y:.4f}" for x, y in patch.shape)
    patch_seed = int.from_bytes(sha256(patch_key.encode()).digest()[:8], "big")
    r = _stable_float(patch_seed, "ward-r", 0)

    # Target building count per block, matching real Watabou ward densities
    if patch.ward_kind == "slum":
        target_count = 15 + 30 * r  # 15-45 buildings (dense, chaotic)
        grid_chaos = 0.8
        size_chaos = 0.8
        empty_prob = 0.05
    elif patch.ward_kind in ("residential", "patriciate"):
        target_count = 8 + 12 * r  # 8-20 buildings (roomy, but still continuous)
        grid_chaos = 0.3
        size_chaos = 0.3
        empty_prob = 0.03
    elif patch.ward_kind == "market":
        target_count = 6 + 14 * r  # 6-20 buildings (medium, regular)
        grid_chaos = 0.3
        size_chaos = 0.5
        empty_prob = 0.01
    elif patch.ward_kind == "merchant":
        target_count = 5 + 10 * r  # 5-15 buildings
        grid_chaos = 0.4
        size_chaos = 0.4
        empty_prob = 0.02
    elif patch.ward_kind == "craftsmen":
        target_count = 8 + 18 * r  # 8-26 buildings (moderate density)
        grid_chaos = 0.5
        size_chaos = 0.6
        empty_prob = 0.02
    else:
        target_count = 5 + 15 * r  # 5-20 buildings
        grid_chaos = 0.5
        size_chaos = 0.6
        empty_prob = 0.02

    if patch.on_boundary:
        # The outer ward should read as an organic settlement edge rather than
        # a perfect ring of equal plots.
        grid_chaos = min(0.92, grid_chaos + 0.22)
        size_chaos = min(0.9, size_chaos + 0.18)
        empty_prob = min(0.12, empty_prob + 0.04)

    # Keep the blocks visually compact without pushing large cities into an
    # unnecessarily expensive building count. Villages and towns receive the
    # density lift; cities are already dense at their existing scale.
    density_multiplier: dict[str, float] = {"village": 0.72, "town": 1.15, "city": 1.8}
    target_count = max(2, round(target_count * density_multiplier[size]))

    # min_sq = average building area for recursion threshold
    min_sq = block_area / target_count

    walkways: list[list[Coordinate]] = []
    pieces = _create_alleys(
        block,
        min_sq,
        grid_chaos,
        size_chaos,
        empty_prob,
        patch_seed,
        walkways,
    )

    # Alleys already reserve the physical separation between plots. Keep this
    # secondary inset small so roofs read as a continuous medieval street wall.
    buildings: list[list[Coordinate]] = []
    patch_radii = [math.hypot(point[0], point[1]) for point in patch.shape]
    edge_threshold = min(patch_radii) + (max(patch_radii) - min(patch_radii)) * 0.62
    for piece_index, piece in enumerate(pieces):
        shrunk = _shrink(piece, 0.045 if patch.on_boundary else 0.02)
        if patch.on_boundary and math.hypot(*_centroid(piece)) >= edge_threshold:
            shrunk = _organic_edge_footprint(
                shrunk,
                patch.shape,
                wall_boundary,
                walkways,
                patch_seed,
                piece_index,
            )
        cleared = _clear_building_from_streets(shrunk, patch, local_arteries, walkways)
        if cleared is not None:
            buildings.append(cleared)

    return buildings, walkways


def _create_alleys(
    poly: list[Coordinate],
    min_sq: float,
    grid_chaos: float,
    size_chaos: float,
    empty_prob: float,
    patch_seed: int,
    walkways: list[list[Coordinate]],
    depth: int = 0,
) -> list[list[Coordinate]]:
    """Recursively bisect a polygon perpendicular to its longest edge.

    Direct reimplementation of Watabou's Ward.createAlleys.
    """
    if depth > 30:
        return [poly] if _polygon_area(poly) > 2 else []

    area = _polygon_area(poly)
    if area < 2:
        return []

    # ---- Find longest edge ----
    n = len(poly)
    best_v = 0
    best_len = -1.0
    for i in range(n):
        d = _distance(poly[i], poly[(i + 1) % n])
        if d > best_len:
            best_len = d
            best_v = i

    if best_len < 2.0:
        return [poly] if area > 2 else []

    # ---- Pick a random ratio along that edge ----
    # spread = 0.8 * gridChaos  (real Watabou: ratio = (1-spread)/2 + rand*spread)
    spread = 0.8 * grid_chaos
    ratio = (1 - spread) / 2 + _stable_float(patch_seed, f"ratio-d{depth}", depth) * spread
    ratio = max(0.15, min(0.85, ratio))

    vertex = poly[best_v]
    next_v = poly[(best_v + 1) % n]
    p1 = _point(
        vertex[0] + (next_v[0] - vertex[0]) * ratio,
        vertex[1] + (next_v[1] - vertex[1]) * ratio,
    )

    # ---- Perpendicular direction with angle chaos ----
    dx, dy = next_v[0] - vertex[0], next_v[1] - vertex[1]
    edge_len = math.hypot(dx, dy)
    if edge_len < 0.01:
        return [poly]

    # angleSpread = PI/6 * gridChaos  (0 for small pieces — keeps buildings rectangular)
    angle_spread = math.pi / 6 * grid_chaos * (0.0 if area < min_sq * 4 else 1.0)
    b = (_stable_float(patch_seed, f"angle-d{depth}", depth) - 0.5) * angle_spread
    cos_b, sin_b = math.cos(b), math.sin(b)

    # Perpendicular = (-dy, dx), then rotated by b
    perp_x = (-dy * cos_b - dx * sin_b) / edge_len
    perp_y = (dx * cos_b - dy * sin_b) / edge_len
    p2 = _point(p1[0] + perp_x * 1e5, p1[1] + perp_y * 1e5)

    # ---- Cut the polygon along this line with alley gap ----
    halves = _polygon_cut(poly, p1, p2, ALLEY_GAP, walkways)
    if len(halves) < 2:
        return [poly] if area > 2 else []

    # ---- Recurse ----
    buildings: list[list[Coordinate]] = []
    for hi, half in enumerate(halves):
        half_area = _polygon_area(half)
        if half_area < 2:
            continue

        # Size threshold: minSq * 2^(4 * sizeChaos * (rand - 0.5))
        size_rand = _stable_float(patch_seed, f"size-d{depth}-h{hi}", depth * 100 + hi)
        threshold = min_sq * (2 ** (4 * size_chaos * (size_rand - 0.5)))

        if half_area < threshold:
            if _stable_float(patch_seed, f"empty-d{depth}-h{hi}", depth * 200 + hi) >= empty_prob:
                buildings.append(half)
        else:
            buildings.extend(
                _create_alleys(
                    half,
                    min_sq,
                    grid_chaos,
                    size_chaos,
                    empty_prob,
                    patch_seed,
                    walkways,
                    depth + 1,
                )
            )

    return buildings


def _polygon_cut(
    poly: list[Coordinate],
    p1: Coordinate,
    p2: Coordinate,
    gap: float = 0.0,
    walkways: list[list[Coordinate]] | None = None,
) -> list[list[Coordinate]]:
    """Cut a polygon along the line P1→P2, returning two halves.

    Reimplements Watabou's Polygon.cut + Polygon.peel:
      1. Find two intersection points of the cut line with polygon edges
      2. Split into two halves
      3. If gap > 0, peel each half's cut edge by gap/2 (creates alleys)
    """
    n = len(poly)
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]

    hits: list[tuple[int, float, float]] = []  # (edge_idx, t_cut, t_edge)
    for i in range(n):
        v0, v1 = poly[i], poly[(i + 1) % n]
        ex, ey = v1[0] - v0[0], v1[1] - v0[1]
        t = _line_intersection(p1[0], p1[1], dx, dy, v0[0], v0[1], ex, ey)
        if t is not None and 0 <= t[1] <= 1:
            hits.append((i, t[0], t[1]))

    if len(hits) < 2:
        return [poly]

    # Use first two distinct edge hits; sort by t on cut line
    (e1, t1_c, t1_e), (e2, t2_c, t2_e) = hits[0], hits[1]
    if t1_c > t2_c:
        e1, t1_c, t1_e, e2, t2_c, t2_e = e2, t2_c, t2_e, e1, t1_c, t1_e

    pt1 = _point(p1[0] + dx * t1_c, p1[1] + dy * t1_c)
    pt2 = _point(p1[0] + dx * t2_c, p1[1] + dy * t2_c)

    # half1: [pt1, poly[e1+1..e2], pt2]
    half1: list[Coordinate] = [pt1]
    idx = (e1 + 1) % n
    while idx != (e2 + 1) % n:
        half1.append(poly[idx])
        idx = (idx + 1) % n
    half1.append(pt2)

    # half2: [pt2, poly[e2+1..], poly[0..e1], pt1]
    half2: list[Coordinate] = [pt2]
    idx = (e2 + 1) % n
    while idx != (e1 + 1) % n:
        half2.append(poly[idx])
        idx = (idx + 1) % n
    half2.append(pt1)

    # Peel (inset the cut edge) if gap > 0
    if gap > 0:
        peeled1 = _polygon_peel(half1, pt2, gap / 2)
        peeled2 = _polygon_peel(half2, pt1, gap / 2)
        if peeled1 is None or peeled2 is None:
            return [poly]
        half1, half2 = peeled1, peeled2

    if walkways is not None and _distance(pt1, pt2) > 0.5:
        walkways.append([pt1, pt2])

    # Order: match Watabou's cross-product check for consistency
    edge_vec = _sub(poly[(e1 + 1) % n], poly[e1])
    cross = dx * edge_vec[1] - dy * edge_vec[0]
    return [half1, half2] if cross > 0 else [half2, half1]


def _polygon_peel(
    poly: list[Coordinate], peel_vertex: Coordinate, dist: float,
) -> list[Coordinate] | None:
    """Inset one edge of the polygon by `dist` (Watabou's Polygon.peel).

    Finds the edge starting at peel_vertex, shifts it inward by dist,
    cuts the peel off, and returns the larger (non-peel) half.
    """
    n = len(poly)
    i1: int | None = None
    for i in range(n):
        if poly[i] == peel_vertex:
            i1 = i
            break
    if i1 is None:
        return poly

    i2 = (i1 + 1) % n
    ex = poly[i2][0] - poly[i1][0]
    ey = poly[i2][1] - poly[i1][1]
    v_len = math.hypot(ex, ey)
    if v_len < 0.001:
        return poly

    # Normal (rotate 90° CCW, scale to dist)
    nx = -ey / v_len * dist
    ny = ex / v_len * dist

    new_p1 = _point(poly[i1][0] + nx, poly[i1][1] + ny)
    new_p2 = _point(poly[i2][0] + nx, poly[i2][1] + ny)

    halves = _polygon_cut(poly, new_p1, new_p2, 0.0)
    if len(halves) < 2:
        return poly

    return halves[0] if _polygon_area(halves[0]) > _polygon_area(halves[1]) else halves[1]


def _line_intersection(
    x1: float, y1: float, dx1: float, dy1: float,
    x2: float, y2: float, dx2: float, dy2: float,
) -> tuple[float, float] | None:
    """Intersect two parametric lines. Returns (t_on_line1, t_on_line2) or None."""
    denom = dx1 * dy2 - dy1 * dx2
    if abs(denom) < 1e-12:
        return None
    t = ((x2 - x1) * dy2 - (y2 - y1) * dx2) / denom
    u = ((x2 - x1) * dy1 - (y2 - y1) * dx1) / denom
    return (t, u)


def _sub(a: Coordinate, b: Coordinate) -> tuple[float, float]:
    return (a[0] - b[0], a[1] - b[1])


def _inset_for_streets(
    patch: Patch,
    arteries: list[_Artery],
) -> list[Coordinate] | None:
    """Shrink the patch polygon along edges that are streets."""
    REG = 1.0
    ALLEY = 0.6

    shape = patch.shape
    inset_dists: list[float] = []
    for i in range(len(shape)):
        v0, v1 = shape[i], shape[(i + 1) % len(shape)]
        on_street = False
        edge_width = max(
            (
                artery.width
                for artery in arteries
                for j in range(len(artery.path) - 1)
                if (artery.path[j] == v0 and artery.path[j + 1] == v1)
                or (artery.path[j] == v1 and artery.path[j + 1] == v0)
            ),
            default=0.0,
        )
        inset_dists.append(
            edge_width / 2 + BUILDING_STREET_GAP
            if edge_width > 0
            else (REG / 2 if patch.within_city else ALLEY / 2)
        )

    c = _centroid(shape)
    result: list[Coordinate] = []
    for i, pt in enumerate(shape):
        dist_to_center = _distance(pt, c)
        if dist_to_center < 0.01:
            result.append(pt)
            continue
        fraction = inset_dists[i] / dist_to_center
        fraction = min(fraction, 0.25)
        result.append(_point(
            pt[0] + (c[0] - pt[0]) * fraction,
            pt[1] + (c[1] - pt[1]) * fraction,
        ))

    if _polygon_area(result) < 5:
        return None
    return result


# ---------------------------------------------------------------------------
# Ward assignment
# ---------------------------------------------------------------------------

WARD_KINDS = [
    "craftsmen", "craftsmen", "merchant", "craftsmen", "craftsmen", "cathedral",
    "craftsmen", "craftsmen", "craftsmen", "craftsmen", "craftsmen",
    "craftsmen", "craftsmen", "craftsmen", "administration", "craftsmen",
    "slum", "craftsmen", "slum", "patriciate", "market",
    "slum", "craftsmen", "craftsmen", "craftsmen", "slum",
    "craftsmen", "craftsmen", "craftsmen", "military", "slum",
    "craftsmen", "park", "patriciate", "market", "merchant",
]

WARD_TO_BUILDING_KIND: dict[str, str] = {
    "craftsmen": "workshop",
    "merchant": "market",
    "patriciate": "residential",
    "slum": "residential",
    "administration": "administrative",
    "cathedral": "religious",
    "military": "military",
    "market": "market",
    "park": "residential",
}

WARD_TO_DISTRICT_KIND: dict[str, str] = {
    "craftsmen": "industrial",
    "merchant": "market",
    "patriciate": "residential",
    "slum": "residential",
    "administration": "civic",
    "cathedral": "religious",
    "military": "military",
    "market": "market",
    "park": "residential",
}


def _assign_wards(patches: list[Patch], seed: int, size: str = "town"):
    """Assign ward types to patches, with size-dependent special building limits."""
    inner_wards = [p for p in patches if p.within_city]
    n = len(inner_wards)

    _quotas: dict[str, dict[str, int]] = {
        "village": {"market": 1, "administration": 1},
        "town":    {"market": 2, "administration": 1, "military": 1,
                     "cathedral": 1, "patriciate": 1, "slum": 2, "merchant": 1, "park": 1},
        "city":    {"market": 3, "administration": 1, "military": 2,
                     "cathedral": 2, "patriciate": 2, "slum": 3, "merchant": 2, "park": 1},
    }
    quotas = _quotas[size]

    specials = []
    for kind, count in quotas.items():
        specials.extend([kind] * count)
    specials = _stable_shuffle(specials, seed, "specials")

    fill = max(0, n - len(specials))
    ward_list = specials + ["craftsmen"] * fill
    ward_list = ward_list[:n]

    for i, patch in enumerate(inner_wards):
        patch.ward_kind = ward_list[i % len(ward_list)]

    for patch in patches:
        if not patch.within_city:
            patch.ward_kind = "farm"


# ---------------------------------------------------------------------------
# Junction / Street extraction
# ---------------------------------------------------------------------------

def _extract_junctions_and_streets(
    arteries: list[_Artery],
    boundary: list[Coordinate],
    gates: list[Coordinate],
) -> tuple[list[TownJunction], list[TownStreet]]:
    """Extract junctions and streets from the artery lines and boundary."""
    def _key(pt: Coordinate) -> str:
        return f"{pt[0]:.4f}_{pt[1]:.4f}"

    coord_to_jid: dict[str, str] = {}
    junctions: list[TownJunction] = []

    junctions.append(TownJunction(id="junction-plaza", position=_point(0.0, 0.0), kind="plaza"))
    coord_to_jid[_key((0.0, 0.0))] = "junction-plaza"

    gate_dirs = ["north", "east", "south", "west"]
    for i, gate in enumerate(gates):
        k = _key(gate)
        jid = f"junction-gate-{gate_dirs[i]}"
        junctions.append(TownJunction(id=jid, position=_point(gate[0], gate[1]), kind="gate"))
        coord_to_jid[k] = jid

    st_counter = [0]
    for artery in arteries:
        for pt in [artery.path[0], artery.path[-1]]:
            k = _key(pt)
            if k not in coord_to_jid:
                jid = f"junction-street-{st_counter[0]:04d}"
                st_counter[0] += 1
                junctions.append(TownJunction(id=jid, position=_point(pt[0], pt[1]), kind="normal"))
                coord_to_jid[k] = jid

    streets: list[TownStreet] = []
    for ai, artery in enumerate(arteries):
        if len(artery.path) < 2:
            continue
        sk, ek = _key(artery.path[0]), _key(artery.path[-1])
        if sk not in coord_to_jid or ek not in coord_to_jid:
            continue
        from_jid, to_jid = coord_to_jid[sk], coord_to_jid[ek]
        if from_jid == to_jid:
            continue
        j_from = next(j for j in junctions if j.id == from_jid)
        j_to = next(j for j in junctions if j.id == to_jid)
        path = [j_from.position] + [_point(p[0], p[1]) for p in artery.path[1:-1]] + [j_to.position]
        streets.append(TownStreet(
            id=f"street-{ai:04d}",
            from_junction_id=from_jid,
            to_junction_id=to_jid,
            path=path,
            width=artery.width,
            kind=artery.kind,  # type: ignore[arg-type]
            pedestrian_access=artery.pedestrian_access,
            vehicle_access=artery.vehicle_access,
        ))

    return junctions, streets


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_watabou_town(request: TownGenerationRequest) -> TownSkeleton:
    seed = request.generation_seed if request.generation_seed is not None else rand_module.randint(0, 2**53 - 1)
    population = request.population
    vehicle_count = max(5, min(1000, round(population / 80)))
    size = request.generation_size or "town"
    name = normalize_town_name(request.name, size) if request.name else generate_town_name(seed, size)

    patches, arteries, wall, center = _generate_watabou_patches(seed, size)

    _assign_wards(patches, seed, size)

    for patch_index, patch in enumerate(patches):
        # The innermost ward is the central plaza and must remain open.
        if patch_index == 0:
            patch.buildings, patch.walkways = [], []
        else:
            patch.buildings, patch.walkways = _create_buildings(patch, arteries, wall.shape, size)

    # --- Assemble TownSkeleton ---
    buildings: list[TownBuilding] = []
    districts: list[TownDistrict] = []
    walkways: list[TownWalkway] = []
    building_counter = 0
    walkway_counter = 0

    for pi, patch in enumerate(patches):
        if not patch.within_city or not patch.buildings:
            continue
        district_id = f"district-w{pi:04d}"
        dkind = WARD_TO_DISTRICT_KIND.get(patch.ward_kind, "residential")
        districts.append(TownDistrict(
            id=district_id,
            kind=dkind,  # type: ignore[arg-type]
            polygon=patch.shape,
        ))

        for path in patch.walkways:
            walkways.append(TownWalkway(
                id=f"walkway-{walkway_counter:05d}",
                district_id=district_id,
                path=path,
                width=ALLEY_GAP,
                pedestrian_access=True,
                vehicle_access=False,
            ))
            walkway_counter += 1

        bkind = WARD_TO_BUILDING_KIND.get(patch.ward_kind, "residential")
        for footprint in patch.buildings:
            bid = f"building-{building_counter:05d}"
            building_counter += 1
            buildings.append(TownBuilding(
                id=bid,
                district_id=district_id,
                kind=bkind,  # type: ignore[arg-type]
                polygon=footprint,
                anchor=_centroid(footprint),
            ))

    junctions, streets = _extract_junctions_and_streets(arteries, wall.shape, wall.gates)

    landmarks: list[TownLandmark] = [
        TownLandmark(id="landmark-plaza", kind="plaza", name="中央广场", position=_point(0.0, 0.0))
    ]
    gate_dirs = {"north": 0, "east": 1, "south": 2, "west": 3}
    for direction, idx in gate_dirs.items():
        if idx < len(wall.gates):
            landmarks.append(TownLandmark(
                id=f"landmark-{direction}-gate",
                kind="gate",
                name=f"{ {'north': '北', 'east': '东', 'south': '南', 'west': '西'}[direction] }城门",
                position=wall.gates[idx],
            ))

    bmap_by_kind: dict[str, TownBuilding] = {}
    for b in buildings:
        if b.kind not in bmap_by_kind:
            bmap_by_kind[b.kind] = b
    for kind in ("administrative", "market", "religious", "military", "storage", "workshop", "stable"):
        if kind in bmap_by_kind:
            b = bmap_by_kind[kind]
            name_map = {
                "administrative": "行政府邸", "market": "集市广场", "religious": "古神殿",
                "military": "兵营要塞", "storage": "大粮仓", "workshop": "工坊区", "stable": "马厩场",
            }
            landmarks.append(TownLandmark(
                id=f"landmark-{kind}",
                building_id=b.id,
                kind=kind,  # type: ignore[arg-type]
                name=name_map[kind],
                position=b.anchor,
            ))

    inner = [p for p in patches if p.within_city]
    bound_x = [v[0] for p in inner for v in p.shape] + [v[0] for v in wall.shape]
    bound_y = [v[1] for p in inner for v in p.shape] + [v[1] for v in wall.shape]

    skeleton = TownSkeleton(
        scenario_id=_scenario_id(seed, population),
        name=name,
        generation_seed=seed,
        generator_version="watabou-v1",  # type: ignore[arg-type]
        requested_population=population,
        initial_vehicle_count=vehicle_count,
        bounds=(min(bound_x), min(bound_y), max(bound_x), max(bound_y)),
        boundary=wall.shape,
        districts=districts,
        buildings=buildings,
        junctions=junctions,
        streets=streets,
        walkways=walkways,
        landmarks=landmarks,
        district_names=generate_district_names(seed, districts),
    )
    return skeleton


def patches_flat(patches: list[Patch]) -> list[Coordinate]:
    result: list[Coordinate] = []
    for p in patches:
        result.extend(p.shape)
    return result


def _scenario_id(seed: int, population: int) -> str:
    payload = f"{GENERATOR_VERSION}:{seed}:{population}".encode()
    return f"town-{sha256(payload).hexdigest()[:16]}"
