import type { Coordinate } from "./api";
import { fractalizeCoastline } from "./coastlineFractal.ts";

export type AllianceSettlementKind = "capital" | "town" | "village";

export interface AllianceSettlement {
  id: string;
  name: string;
  kind: AllianceSettlementKind;
  position: Coordinate;
  population: number;
  parentId: string | null;
  children: string[];
  generationSeed: number;
  region: string;
  influenceRadius?: number;
  boundaryAnchor?: boolean;
}

export interface AllianceRoad {
  id: string;
  fromId: string;
  toId: string;
  path: Coordinate[];
  kind: "imperial" | "regional" | "local";
  people: number;
  vehicles: number;
}

export interface AllianceRegion {
  id: string;
  name: string;
  capitalId: string;
  polygon: Coordinate[];
  colorIndex: number;
}

export interface AllianceTerrainBand {
  id: string;
  label: string;
  y0: number;
  y1: number;
  kind: "polar" | "cold" | "temperate" | "equatorial";
}

export interface AllianceModel {
  name: string;
  seed: number;
  bounds: readonly [number, number, number, number];
  bands: AllianceTerrainBand[];
  territory: Coordinate[];
  landmasses: Coordinate[][];
  mountains: Coordinate[][];
  rivers: Coordinate[][];
  lakes: Coordinate[][];
  regions: AllianceRegion[];
  settlements: AllianceSettlement[];
  roads: AllianceRoad[];
}

const BOUNDS: readonly [number, number, number, number] = [0, 0, 3200, 1800];

function stableUnit(seed: number, key: string): number {
  let hash = (seed ^ 0x811c9dc5) >>> 0;
  for (const character of key) {
    hash = Math.imul(hash ^ character.charCodeAt(0), 0x01000193);
  }
  return (hash >>> 0) / 0xffffffff;
}

function point(x: number, y: number): Coordinate {
  return [Math.round(x * 10) / 10, Math.round(y * 10) / 10];
}

const ALLIANCE_SOURCE_BOUNDS = { x0: 45, x1: 920, y0: 90, y1: 850 };
type AlliancePlacementBounds = { x0: number; x1: number; y0: number; y1: number };

function polygonCentroid(polygon: Coordinate[]): Coordinate {
  let x = 0;
  let y = 0;
  for (const [px, py] of polygon) {
    x += px;
    y += py;
  }
  return point(x / polygon.length, y / polygon.length);
}

function positionInsidePolygon(target: Coordinate, fallback: Coordinate, polygon: Coordinate[]): Coordinate {
  if (pointInsidePolygon(target, polygon)) return target;
  for (const weight of [0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 1]) {
    const candidate = point(
      target[0] + (fallback[0] - target[0]) * weight,
      target[1] + (fallback[1] - target[1]) * weight,
    );
    if (pointInsidePolygon(candidate, polygon)) return candidate;
  }
  return fallback;
}

function alliancePlacement(
  seed: number,
  host: ContinentSpec,
  hostPolygon: Coordinate[],
): AlliancePlacementBounds {
  const hostCenter = polygonCentroid(hostPolygon);
  const width = Math.min(620, Math.max(300, host.radius[0] * 0.82));
  const height = Math.min(460, Math.max(230, host.radius[1] * 0.82));
  const desired = point(
    hostCenter[0] + (stableUnit(seed, "alliance-placement-x") - 0.5) * host.radius[0] * 0.28,
    hostCenter[1] + (stableUnit(seed, "alliance-placement-y") - 0.5) * host.radius[1] * 0.28,
  );
  const center = positionInsidePolygon(desired, hostCenter, hostPolygon);

  // Keep the control area inside the host even when the coastline has a deep bay.
  for (const scale of [1, 0.88, 0.76, 0.64, 0.52]) {
    const candidate = {
      x0: center[0] - width * scale / 2,
      x1: center[0] + width * scale / 2,
      y0: center[1] - height * scale / 2,
      y1: center[1] + height * scale / 2,
    };
    if (allianceTerritory(candidate).every((item) => pointInsidePolygon(item, hostPolygon))) return candidate;
  }
  return {
    x0: hostCenter[0] - width * 0.42,
    x1: hostCenter[0] + width * 0.42,
    y0: hostCenter[1] - height * 0.42,
    y1: hostCenter[1] + height * 0.42,
  };
}

function allianceTerritory(bounds: AlliancePlacementBounds): Coordinate[] {
  const width = bounds.x1 - bounds.x0;
  const height = bounds.y1 - bounds.y0;
  return [
    point(bounds.x0 + width * 0.02, bounds.y0 + height * 0.18),
    point(bounds.x0 + width * 0.12, bounds.y0 + height * 0.05),
    point(bounds.x0 + width * 0.42, bounds.y0),
    point(bounds.x0 + width * 0.7, bounds.y0 + height * 0.05),
    point(bounds.x1 - width * 0.04, bounds.y0 + height * 0.18),
    point(bounds.x1, bounds.y0 + height * 0.39),
    point(bounds.x0 + width * 0.94, bounds.y0 + height * 0.61),
    point(bounds.x1 - width * 0.1, bounds.y1 - height * 0.04),
    point(bounds.x0 + width * 0.68, bounds.y1),
    point(bounds.x0 + width * 0.42, bounds.y1 - height * 0.06),
    point(bounds.x0 + width * 0.18, bounds.y1),
    point(bounds.x0 + width * 0.04, bounds.y1 - height * 0.16),
    point(bounds.x0, bounds.y0 + height * 0.68),
    point(bounds.x0 + width * 0.05, bounds.y0 + height * 0.43),
  ];
}

function fitAlliancePoint(source: Coordinate, bounds: AlliancePlacementBounds): Coordinate {
  const xRatio = (source[0] - ALLIANCE_SOURCE_BOUNDS.x0) / (ALLIANCE_SOURCE_BOUNDS.x1 - ALLIANCE_SOURCE_BOUNDS.x0);
  const yRatio = (source[1] - ALLIANCE_SOURCE_BOUNDS.y0) / (ALLIANCE_SOURCE_BOUNDS.y1 - ALLIANCE_SOURCE_BOUNDS.y0);
  return point(
    bounds.x0 + xRatio * (bounds.x1 - bounds.x0),
    bounds.y0 + yRatio * (bounds.y1 - bounds.y0),
  );
}

function fitAllianceOffset(offset: Coordinate, bounds: AlliancePlacementBounds): Coordinate {
  return point(
    offset[0] * (bounds.x1 - bounds.x0)
      / (ALLIANCE_SOURCE_BOUNDS.x1 - ALLIANCE_SOURCE_BOUNDS.x0),
    offset[1] * (bounds.y1 - bounds.y0)
      / (ALLIANCE_SOURCE_BOUNDS.y1 - ALLIANCE_SOURCE_BOUNDS.y0),
  );
}

function randomizeShape(template: Coordinate[], seed: number, key: string, jitter: number): Coordinate[] {
  const driftX = (stableUnit(seed, `${key}:drift-x`) - 0.5) * jitter * 2;
  const driftY = (stableUnit(seed, `${key}:drift-y`) - 0.5) * jitter * 2;
  return template.map(([x, y], index) => {
    const pointJitter = jitter * 0.45;
    const nextX = x + driftX + (stableUnit(seed, `${key}:${index}:x`) - 0.5) * pointJitter;
    const nextY = y + driftY + (stableUnit(seed, `${key}:${index}:y`) - 0.5) * pointJitter;
    return point(Math.max(0, Math.min(BOUNDS[2], nextX)), Math.max(0, Math.min(BOUNDS[3], nextY)));
  });
}

function lakeShape(center: Coordinate, radius: Coordinate, seed: number, key: string): Coordinate[] {
  return Array.from({ length: 14 }, (_, index) => {
    const angle = index / 14 * Math.PI * 2;
    const radial = 0.78 + stableUnit(seed, `${key}:shore:${index}`) * 0.34;
    return point(
      center[0] + Math.cos(angle) * radius[0] * radial,
      center[1] + Math.sin(angle) * radius[1] * radial,
    );
  });
}

interface ContinentSpec {
  key: string;
  center: Coordinate;
  radius: Coordinate;
  rotation: number;
  vertices?: number;
}

function rotateLocal(local: Coordinate, rotation: number): Coordinate {
  const [x, y] = local;
  const cosine = Math.cos(rotation);
  const sine = Math.sin(rotation);
  return [x * cosine - y * sine, x * sine + y * cosine];
}

function continentShape(spec: ContinentSpec, seed: number): Coordinate[] {
  const vertices = spec.vertices ?? 20;
  const phase2 = stableUnit(seed, `${spec.key}:phase:2`) * Math.PI * 2;
  const phase3 = stableUnit(seed, `${spec.key}:phase:3`) * Math.PI * 2;
  const phase5 = stableUnit(seed, `${spec.key}:phase:5`) * Math.PI * 2;
  const base = Array.from({ length: vertices }, (_, index) => {
    const angle = index / vertices * Math.PI * 2 - Math.PI / 2;
    const lobes = 1
      + Math.sin(angle * 2 + phase2) * 0.12
      + Math.sin(angle * 3 + phase3) * 0.17
      + Math.sin(angle * 5 + phase5) * 0.08;
    const radial = lobes * (0.91 + stableUnit(seed, `${spec.key}:coast:${index}`) * 0.18);
    const local = rotateLocal([
      Math.cos(angle) * spec.radius[0] * radial,
      Math.sin(angle) * spec.radius[1] * radial,
    ], spec.rotation);
    const notch = (stableUnit(seed, `${spec.key}:notch:${index}`) - 0.5) * Math.min(spec.radius[0], spec.radius[1]) * 0.16;
    return point(
      Math.max(16, Math.min(BOUNDS[2] - 16, spec.center[0] + local[0] + Math.cos(angle) * notch)),
      Math.max(16, Math.min(BOUNDS[3] - 16, spec.center[1] + local[1] + Math.sin(angle) * notch)),
    );
  });
  const fractal = fractalizeCoastline(
    base as [number, number][],
    seed,
    Math.round(stableUnit(seed, `${spec.key}:fractal`) * 10_000),
    { width: BOUNDS[2], height: BOUNDS[3] },
    "island",
  );
  return fractal.points.map(([x, y]) => point(x, y));
}

function mountainRange(
  center: Coordinate,
  length: number,
  width: number,
  rotation: number,
  seed: number,
  key: string,
): Coordinate[] {
  const segments = 13;
  const cosine = Math.cos(rotation);
  const sine = Math.sin(rotation);
  const rotate = (local: Coordinate): Coordinate => [
    center[0] + local[0] * cosine - local[1] * sine,
    center[1] + local[0] * sine + local[1] * cosine,
  ];
  return Array.from({ length: segments + 1 }, (_, index) => {
    const ratio = index / segments - 0.5;
    const drift = (stableUnit(seed, `${key}:drift:${index}`) - 0.5) * width;
    const [x, y] = rotate([ratio * length, drift]);
    return point(
      Math.max(0, Math.min(BOUNDS[2], x)),
      Math.max(0, Math.min(BOUNDS[3], y)),
    );
  });
}

function clipToHalfPlane(polygon: Coordinate[], site: Coordinate, other: Coordinate): Coordinate[] {
  if (!polygon.length) return [];
  const midpoint: Coordinate = [(site[0] + other[0]) / 2, (site[1] + other[1]) / 2];
  const normal: Coordinate = [other[0] - site[0], other[1] - site[1]];
  const inside = (candidate: Coordinate) =>
    (candidate[0] - midpoint[0]) * normal[0] + (candidate[1] - midpoint[1]) * normal[1] <= 0.001;
  const intersection = (start: Coordinate, end: Coordinate): Coordinate => {
    const startValue = (start[0] - midpoint[0]) * normal[0] + (start[1] - midpoint[1]) * normal[1];
    const endValue = (end[0] - midpoint[0]) * normal[0] + (end[1] - midpoint[1]) * normal[1];
    const ratio = startValue / (startValue - endValue || 1);
    return point(start[0] + (end[0] - start[0]) * ratio, start[1] + (end[1] - start[1]) * ratio);
  };
  const result: Coordinate[] = [];
  let previous = polygon[polygon.length - 1];
  let previousInside = inside(previous);
  for (const current of polygon) {
    const currentInside = inside(current);
    if (currentInside !== previousInside) result.push(intersection(previous, current));
    if (currentInside) result.push(current);
    previous = current;
    previousInside = currentInside;
  }
  return result;
}

function regionCell(site: Coordinate, sites: Coordinate[]): Coordinate[] {
  let polygon: Coordinate[] = [
    point(0, 0),
    point(BOUNDS[2], 0),
    point(BOUNDS[2], BOUNDS[3]),
    point(0, BOUNDS[3]),
  ];
  for (const other of sites) {
    if (other === site) continue;
    polygon = clipToHalfPlane(polygon, site, other);
  }
  return polygon;
}

function pointInsidePolygon(candidate: Coordinate, polygon: Coordinate[]): boolean {
  let inside = false;
  for (let index = 0, previous = polygon.length - 1; index < polygon.length; previous = index++) {
    const current = polygon[index];
    const previousPoint = polygon[previous];
    if ((current[1] > candidate[1]) !== (previousPoint[1] > candidate[1])) {
      const edgeX = (previousPoint[0] - current[0]) * (candidate[1] - current[1])
        / (previousPoint[1] - current[1]) + current[0];
      if (candidate[0] < edgeX) inside = !inside;
    }
  }
  return inside;
}

function positionInsideTerritory(raw: Coordinate, parent: Coordinate, territory: Coordinate[]): Coordinate {
  if (pointInsidePolygon(raw, territory)) return point(raw[0], raw[1]);
  for (const parentWeight of [0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 1]) {
    const candidate = point(
      raw[0] + (parent[0] - raw[0]) * parentWeight,
      raw[1] + (parent[1] - raw[1]) * parentWeight,
    );
    if (pointInsidePolygon(candidate, territory)) return candidate;
  }
  return point(parent[0], parent[1]);
}

function orientation(start: Coordinate, end: Coordinate, candidate: Coordinate): number {
  return (end[0] - start[0]) * (candidate[1] - start[1])
    - (end[1] - start[1]) * (candidate[0] - start[0]);
}

function keepRoadSide(candidate: Coordinate, anchor: Coordinate, road: [Coordinate, Coordinate]): Coordinate {
  let adjusted = candidate;
  const anchorSide = orientation(road[0], road[1], anchor);
  if (Math.abs(anchorSide) < 0.001) return adjusted;
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const candidateSide = orientation(road[0], road[1], adjusted);
    if (Math.abs(candidateSide) < 0.001 || candidateSide * anchorSide >= 0) return adjusted;
    adjusted = point(
      anchor[0] + (adjusted[0] - anchor[0]) * 0.62,
      anchor[1] + (adjusted[1] - anchor[1]) * 0.62,
    );
  }
  return adjusted;
}

function segmentsCross(leftStart: Coordinate, leftEnd: Coordinate, rightStart: Coordinate, rightEnd: Coordinate): boolean {
  return orientation(leftStart, leftEnd, rightStart) * orientation(leftStart, leftEnd, rightEnd) < 0
    && orientation(rightStart, rightEnd, leftStart) * orientation(rightStart, rightEnd, leftEnd) < 0;
}

function pathCrossesExistingRoad(
  candidate: Coordinate[],
  existing: AllianceRoad,
  sharedSettlementIds: Set<string>,
): boolean {
  if (sharedSettlementIds.has(existing.fromId) || sharedSettlementIds.has(existing.toId)) return false;
  for (let leftIndex = 1; leftIndex < candidate.length; leftIndex += 1) {
    const leftStart = candidate[leftIndex - 1];
    const leftEnd = candidate[leftIndex];
    for (let rightIndex = 1; rightIndex < existing.path.length; rightIndex += 1) {
      if (segmentsCross(leftStart, leftEnd, existing.path[rightIndex - 1], existing.path[rightIndex])) return true;
    }
  }
  return false;
}

function moveEndpointOffExistingRoads(
  from: Coordinate,
  to: Coordinate,
  existingRoads: AllianceRoad[],
  sharedSettlementIds: Set<string>,
): Coordinate {
  let adjusted = to;
  for (let attempt = 0; attempt < 6; attempt += 1) {
    let blocker: [Coordinate, Coordinate] | null = null;
    for (const road of existingRoads) {
      if (sharedSettlementIds.has(road.fromId) || sharedSettlementIds.has(road.toId)) continue;
      for (let index = 1; index < road.path.length; index += 1) {
        if (segmentsCross(from, adjusted, road.path[index - 1], road.path[index])) {
          blocker = [road.path[index - 1], road.path[index]];
          break;
        }
      }
      if (blocker) break;
    }
    if (!blocker) return adjusted;

    const [lineStart, lineEnd] = blocker;
    const dx = lineEnd[0] - lineStart[0];
    const dy = lineEnd[1] - lineStart[1];
    const lengthSquared = dx * dx + dy * dy || 1;
    const projectionRatio = ((adjusted[0] - lineStart[0]) * dx + (adjusted[1] - lineStart[1]) * dy) / lengthSquared;
    const projection = point(lineStart[0] + dx * projectionRatio, lineStart[1] + dy * projectionRatio);
    const normalLength = Math.hypot(dx, dy) || 1;
    const side = Math.sign(orientation(lineStart, lineEnd, from)) || 1;
    adjusted = point(
      projection[0] * 2 - adjusted[0] - dy / normalLength * side * 5,
      projection[1] * 2 - adjusted[1] + dx / normalLength * side * 5,
    );
  }
  return adjusted;
}

function roadPath(
  from: Coordinate,
  to: Coordinate,
  kind: AllianceRoad["kind"],
  existingRoads: AllianceRoad[],
  fromId: string,
  toId: string,
): Coordinate[] {
  if (kind === "imperial") return [from, to];
  const dx = to[0] - from[0];
  const dy = to[1] - from[1];
  const length = Math.hypot(dx, dy) || 1;
  const normal: Coordinate = [-dy / length, dx / length];
  const departure = kind === "regional" ? 0.28 : 0.2;
  const offsets = kind === "regional" ? [9, -9, 15, -15, 24, -24] : [6, -6, 12, -12, 18, -18];
  const departures = [departure, 0.42, 0.58, 0.72];
  const sharedSettlementIds = new Set([fromId, toId]);
  for (const offset of offsets) {
    for (const departureRatio of departures) {
      const bend = point(
        from[0] + dx * departureRatio + normal[0] * offset,
        from[1] + dy * departureRatio + normal[1] * offset,
      );
      const candidate = [from, bend, to];
      if (!existingRoads.some((road) => pathCrossesExistingRoad(candidate, road, sharedSettlementIds))) return candidate;
    }
  }
  return [from, to];
}

function appendRoad(
  roads: AllianceRoad[],
  from: AllianceSettlement,
  to: AllianceSettlement,
  kind: AllianceRoad["kind"],
): void {
  const peopleRate = kind === "imperial" ? 0.72 : kind === "regional" ? 0.46 : 0.2;
  if (kind === "local") {
    to.position = moveEndpointOffExistingRoads(
      from.position,
      to.position,
      roads,
      new Set([from.id, to.id]),
    );
  }
  roads.push({
    id: `alliance-road-${roads.length.toString().padStart(3, "0")}`,
    fromId: from.id,
    toId: to.id,
    path: roadPath(from.position, to.position, kind, roads, from.id, to.id),
    kind,
    people: Math.round((from.population + to.population) * peopleRate / 34),
    vehicles: Math.max(3, Math.round((from.population + to.population) * peopleRate / 900)),
  });
}

function settlement(
  id: string,
  name: string,
  kind: AllianceSettlementKind,
  position: Coordinate,
  population: number,
  parentId: string | null,
  region: string,
  seed: number,
  options: Pick<AllianceSettlement, "influenceRadius" | "boundaryAnchor"> = {},
): AllianceSettlement {
  return {
    id,
    name,
    kind,
    position,
    population,
    parentId,
    children: [],
    region,
    generationSeed: seed,
    ...(options.influenceRadius === undefined ? {} : { influenceRadius: options.influenceRadius }),
    ...(options.boundaryAnchor ? { boundaryAnchor: true } : {}),
  };
}

const CONTINENT_SPECS: ContinentSpec[] = [
  { key: "continent-northwest", center: point(430, 330), radius: point(360, 245), rotation: -0.14, vertices: 28 },
  { key: "continent-northeast", center: point(2680, 315), radius: point(420, 255), rotation: 0.16, vertices: 30 },
  { key: "continent-western", center: point(390, 980), radius: point(295, 235), rotation: -0.2, vertices: 26 },
  { key: "continent-eastern", center: point(2790, 1020), radius: point(325, 250), rotation: 0.1, vertices: 27 },
  { key: "continent-central", center: point(1570, 850), radius: point(650, 430), rotation: -0.06, vertices: 34 },
  { key: "continent-southwest", center: point(700, 1480), radius: point(330, 215), rotation: 0.18, vertices: 26 },
  { key: "continent-southeast", center: point(2460, 1480), radius: point(350, 220), rotation: -0.12, vertices: 27 },
  { key: "continent-south-polar", center: point(1600, 1755), radius: point(650, 72), rotation: 0, vertices: 26 },
];

const ISLAND_SPECS: ContinentSpec[] = [
  { key: "island-north-channel", center: point(1540, 235), radius: point(105, 62), rotation: -0.1, vertices: 16 },
  { key: "island-west-channel", center: point(980, 475), radius: point(92, 66), rotation: 0.2, vertices: 15 },
  { key: "island-east-channel", center: point(2170, 505), radius: point(115, 70), rotation: -0.18, vertices: 17 },
  { key: "island-south-channel", center: point(1580, 1430), radius: point(125, 70), rotation: 0.12, vertices: 17 },
  { key: "island-far-east", center: point(3070, 610), radius: point(72, 125), rotation: 0.18, vertices: 16 },
  { key: "island-far-west", center: point(120, 1450), radius: point(95, 62), rotation: -0.1, vertices: 15 },
];

export function createAlliance(seed = 20260808): AllianceModel {
  const hostIndex = Math.floor(stableUnit(seed, "alliance-host") * (CONTINENT_SPECS.length - 1));
  const hostSpec = CONTINENT_SPECS[hostIndex];
  const continentShapes = CONTINENT_SPECS.map((spec) => continentShape(spec, seed));
  const hostPolygon = continentShapes[hostIndex];
  const placement = alliancePlacement(seed, hostSpec, hostPolygon);
  const territory = allianceTerritory(placement);
  const settlements: AllianceSettlement[] = [];
  const capitals = [
    settlement("capital-northwest", "霜原城", "capital", fitAlliancePoint(point(210, 190), placement), 78_000, null, "北方边境", seed + 11, { influenceRadius: 250 }),
    settlement("capital-northeast", "晨曦城", "capital", fitAlliancePoint(point(670, 190), placement), 96_000, null, "东部行省", seed + 17, { influenceRadius: 255 }),
    settlement("capital-heart", "曙光城", "capital", fitAlliancePoint(point(450, 450), placement), 124_000, null, "中央行省", seed + 23, { influenceRadius: 260 }),
    settlement("capital-southwest", "潮汐城", "capital", fitAlliancePoint(point(200, 700), placement), 91_000, null, "南部海岸", seed + 29, { influenceRadius: 250 }),
    settlement("capital-southeast", "赤穹城", "capital", fitAlliancePoint(point(660, 700), placement), 88_000, null, "东南边疆", seed + 31, { influenceRadius: 255 }),
  ];
  settlements.push(...capitals);
  const regions: AllianceRegion[] = capitals.map((capital, index) => ({
    id: `region-${capital.id}`,
    name: capital.region,
    capitalId: capital.id,
    polygon: regionCell(capital.position, capitals.map((item) => item.position)),
    colorIndex: index,
  }));
  const outerCapitalRoadOrder = [0, 1, 4, 3];
  const imperialSegments: Array<[Coordinate, Coordinate]> = [
    ...outerCapitalRoadOrder.map((capitalIndex, index) => [
      capitals[capitalIndex].position,
      capitals[outerCapitalRoadOrder[(index + 1) % outerCapitalRoadOrder.length]].position,
    ] as [Coordinate, Coordinate]),
    [capitals[2].position, capitals[0].position],
  ];

  const boundaryTownPlans: Array<{ name: string; position: Coordinate; capitalIndex: number }> = [
    { name: "北关镇", position: point(125, 145), capitalIndex: 0 },
    { name: "东岚镇", position: point(785, 135), capitalIndex: 1 },
    { name: "云门镇", position: point(850, 285), capitalIndex: 1 },
    { name: "河湾镇", position: point(810, 530), capitalIndex: 4 },
    { name: "南垦镇", position: point(640, 795), capitalIndex: 4 },
    { name: "榆关镇", position: point(180, 790), capitalIndex: 3 },
    { name: "西岬镇", position: point(110, 535), capitalIndex: 3 },
  ];
  const supportTownPlans: Array<{ name: string; capitalIndex: number; offset: Coordinate }> = [
    { name: "松桥镇", capitalIndex: 0, offset: point(-100, 30) },
    { name: "白桦镇", capitalIndex: 0, offset: point(60, -70) },
    { name: "铁岭镇", capitalIndex: 0, offset: point(40, 95) },
    { name: "谷门镇", capitalIndex: 1, offset: point(-95, -70) },
    { name: "长风镇", capitalIndex: 1, offset: point(100, 15) },
    { name: "金穗镇", capitalIndex: 1, offset: point(10, 100) },
    { name: "中川镇", capitalIndex: 2, offset: point(-125, -105) },
    { name: "枫桥镇", capitalIndex: 2, offset: point(130, -115) },
    { name: "石门镇", capitalIndex: 2, offset: point(-145, 85) },
    { name: "长宁镇", capitalIndex: 2, offset: point(145, 80) },
    { name: "盐港镇", capitalIndex: 3, offset: point(-95, -30) },
    { name: "南岬镇", capitalIndex: 3, offset: point(60, -95) },
    { name: "潮汐镇", capitalIndex: 3, offset: point(20, 100) },
    { name: "云泽镇", capitalIndex: 4, offset: point(-110, -30) },
    { name: "苍原镇", capitalIndex: 4, offset: point(95, -75) },
    { name: "丰林镇", capitalIndex: 4, offset: point(80, 35) },
  ];
  const towns: AllianceSettlement[] = [];
  let ordinal = 0;
  const townPlans = [
    ...boundaryTownPlans.map((plan) => ({ ...plan, position: fitAlliancePoint(plan.position, placement), boundaryAnchor: true })),
    ...supportTownPlans.map((plan) => ({
      ...plan,
      position: point(
        capitals[plan.capitalIndex].position[0] + fitAllianceOffset(plan.offset, placement)[0],
        capitals[plan.capitalIndex].position[1] + fitAllianceOffset(plan.offset, placement)[1],
      ),
      boundaryAnchor: false,
    })),
  ];
  townPlans.forEach((plan, townIndex) => {
    const capital = capitals[plan.capitalIndex];
    const town = settlement(
      `town-${townIndex.toString().padStart(2, "0")}`,
      plan.name,
      "town",
      positionInsideTerritory(plan.position, capital.position, territory),
      8_000 + Math.round(stableUnit(seed, `town-pop-${ordinal}`) * 8_500),
      capital.id,
      capital.region,
      seed + 100 + ordinal,
      { boundaryAnchor: plan.boundaryAnchor },
    );
    ordinal += 1;
    towns.push(town);
    settlements.push(town);
    capital.children.push(town.id);
  });

  const villageNames = ["松溪", "麦垄", "石泉", "鹿原", "风车", "榆湾", "柳岸", "稻香", "石桥", "青禾", "芦湾", "远岫"];
  towns.forEach((town, townIndex) => {
    for (let index = 0; index < 3; index += 1) {
      const angle = index * (Math.PI * 2 / 3) + (stableUnit(seed, `${town.id}:angle`) - 0.5) * 0.5;
      const distance = 32 + stableUnit(seed, `${town.id}:distance:${index}`) * 18;
      const rawPosition = point(
        town.position[0] + Math.cos(angle) * distance,
        town.position[1] + Math.sin(angle) * distance,
      );
      const roadSidePosition = imperialSegments.reduce(
        (candidate, road) => keepRoadSide(candidate, town.position, road),
        rawPosition,
      );
      const village = settlement(
        `village-${townIndex.toString().padStart(2, "0")}-${index}`,
        `${villageNames[(townIndex * 3 + index) % villageNames.length]}村`,
        "village",
        positionInsideTerritory(roadSidePosition, town.position, territory),
        420 + Math.round(stableUnit(seed, `${town.id}:population:${index}`) * 820),
        town.id,
        town.region,
        seed + 500 + townIndex * 3 + index,
      );
      settlements.push(village);
      town.children.push(village.id);
    }
  });

  const byId = new Map(settlements.map((item) => [item.id, item]));
  const roads: AllianceRoad[] = [];
  outerCapitalRoadOrder.forEach((capitalIndex, index) => {
    appendRoad(
      roads,
      capitals[capitalIndex],
      capitals[outerCapitalRoadOrder[(index + 1) % outerCapitalRoadOrder.length]],
      "imperial",
    );
  });
  appendRoad(roads, capitals[2], capitals[0], "imperial");
  for (const town of towns) {
    const parent = byId.get(town.parentId ?? "");
    if (parent) appendRoad(roads, parent, town, "regional");
    for (const villageId of town.children) {
      const village = byId.get(villageId);
      if (village) appendRoad(roads, town, village, "local");
    }
  }

  const landmasses: Coordinate[][] = [
    ...continentShapes,
    ...ISLAND_SPECS.map((spec) => continentShape(spec, seed)),
  ];
  const mountains: Coordinate[][] = [
    mountainRange(point(410, 330), 560, 86, -0.22, seed, "mountain-northwest"),
    mountainRange(point(2680, 320), 680, 92, 0.2, seed, "mountain-northeast"),
    mountainRange(point(390, 980), 470, 78, -0.3, seed, "mountain-western"),
    mountainRange(point(2790, 1020), 500, 80, 0.28, seed, "mountain-eastern"),
    mountainRange(point(1560, 835), 760, 96, -0.08, seed, "mountain-central"),
    mountainRange(point(700, 1480), 450, 74, 0.2, seed, "mountain-southwest"),
    mountainRange(point(2460, 1480), 520, 82, -0.16, seed, "mountain-southeast"),
    mountainRange(point((placement.x0 + placement.x1) / 2, placement.y0 + 205), 560, 76, 0.12, seed, "mountain-alliance"),
  ];
  const rivers: Coordinate[][] = [
    randomizeShape([point(250, 115), point(320, 220), point(350, 360), point(500, 510), point(550, 690)], seed, "river-northwest-a", 30),
    randomizeShape([point(610, 120), point(590, 280), point(660, 410), point(610, 560)], seed, "river-northwest-b", 26),
    randomizeShape([point(2450, 100), point(2520, 260), point(2480, 400), point(2620, 530)], seed, "river-northeast-a", 30),
    randomizeShape([point(2860, 90), point(2790, 270), point(2850, 440), point(2760, 590)], seed, "river-northeast-b", 28),
    randomizeShape([point(280, 790), point(340, 940), point(300, 1100), point(450, 1210)], seed, "river-western", 26),
    randomizeShape([point(2750, 820), point(2700, 960), point(2820, 1110), point(2740, 1215)], seed, "river-eastern", 24),
    randomizeShape([point(1420, 520), point(1480, 680), point(1450, 860), point(1320, 1040), point(1260, 1190)], seed, "river-central-west", 34),
    randomizeShape([point(1800, 510), point(1760, 690), point(1840, 850), point(1900, 1020), point(1860, 1200)], seed, "river-central-east", 32),
    randomizeShape([point(620, 1320), point(700, 1410), point(820, 1510), point(900, 1610)], seed, "river-southwest", 24),
    randomizeShape([point(2550, 1320), point(2470, 1420), point(2520, 1540), point(2440, 1640)], seed, "river-southeast", 25),
    randomizeShape([
      point(placement.x0 + (placement.x1 - placement.x0) * 0.68, placement.y0 + 44),
      point(placement.x0 + (placement.x1 - placement.x0) * 0.72, placement.y0 + 190),
      point(placement.x0 + (placement.x1 - placement.x0) * 0.64, placement.y0 + 370),
      point(placement.x0 + (placement.x1 - placement.x0) * 0.72, placement.y1 + 55),
    ], seed, "river-alliance-east", 24),
    randomizeShape([
      point(placement.x0 + 140, placement.y0 + 110),
      point(placement.x0 + 185, placement.y0 + 230),
      point(placement.x0 + 110, placement.y0 + 390),
      point(placement.x0 + 205, placement.y1 + 40),
    ], seed, "river-alliance-west", 22),
  ];
  const lakeTemplates: Coordinate[][] = [
    lakeShape(point(500, 350), point(58, 40), seed, "lake-northwest"),
    lakeShape(point(2710, 335), point(72, 44), seed, "lake-northeast"),
    lakeShape(point(360, 1040), point(55, 38), seed, "lake-western"),
    lakeShape(point(2830, 1040), point(58, 40), seed, "lake-eastern"),
    lakeShape(point(1600, 840), point(74, 45), seed, "lake-central"),
    lakeShape(point(730, 1500), point(54, 37), seed, "lake-southwest"),
    lakeShape(point(2490, 1500), point(58, 39), seed, "lake-southeast"),
  ];
  const lakes = lakeTemplates.map((lake, index) => fractalizeCoastline(
    lake as [number, number][],
    seed,
    20_000 + index,
    { width: BOUNDS[2], height: BOUNDS[3] },
    "lake",
  ).points.map(([x, y]) => point(x, y)));
  const bands: AllianceTerrainBand[] = [
    { id: "polar-north", label: "北极圈", y0: 0, y1: 220, kind: "polar" },
    { id: "north-temperate", label: "北温带", y0: 220, y1: 620, kind: "cold" },
    { id: "equatorial", label: "赤道带", y0: 620, y1: 1080, kind: "equatorial" },
    { id: "south-temperate", label: "南温带", y0: 1080, y1: 1580, kind: "temperate" },
    { id: "polar-south", label: "南极圈", y0: 1580, y1: 1800, kind: "polar" },
  ];
  return {
    name: "人类联盟",
    seed,
    bounds: BOUNDS,
    bands,
    territory,
    landmasses,
    mountains,
    rivers,
    lakes,
    regions,
    settlements,
    roads,
  };
}

export function alliancePath(path: Coordinate[]): string {
  return path.map(([x, y], index) => `${index === 0 ? "M" : "L"}${x},${y}`).join(" ");
}

export function alliancePolygon(points: Coordinate[]): string {
  return points.map(([x, y]) => `${x},${y}`).join(" ");
}

export function allianceFlowPoint(path: Coordinate[], progress: number): Coordinate {
  const lengths = path.slice(1).map((point, index) => Math.hypot(point[0] - path[index][0], point[1] - path[index][1]));
  const total = lengths.reduce((sum, value) => sum + value, 0) || 1;
  let distance = ((progress % 1) + 1) % 1 * total;
  for (let index = 0; index < lengths.length; index += 1) {
    if (distance <= lengths[index] || index === lengths.length - 1) {
      const ratio = lengths[index] <= 0 ? 0 : distance / lengths[index];
      const start = path[index];
      const end = path[index + 1];
      return point(start[0] + (end[0] - start[0]) * ratio, start[1] + (end[1] - start[1]) * ratio);
    }
    distance -= lengths[index];
  }
  return path[path.length - 1];
}
