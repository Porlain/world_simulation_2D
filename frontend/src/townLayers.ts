import { COORDINATE_SYSTEM, type Color, type Layer } from "@deck.gl/core";
import { PathStyleExtension } from "@deck.gl/extensions";
import { PathLayer, PolygonLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import type {
  BuildingKind,
  Coordinate,
  FlowSnapshot,
  DistrictKind,
  LegacySnapshotState,
  ScenarioBundle,
  SnapshotState,
  TownLandmark,
  TownStreet,
  TownWalkway,
} from "./api";

export interface TownFeature {
  id: string;
  sourceId?: string;
  name: string;
  kind: string;
  polygon?: Coordinate[];
  path?: Coordinate[];
  position?: Coordinate;
  width?: number;
}

export interface TownRenderData {
  bounds: readonly [number, number, number, number];
  districts: TownFeature[];
  buildings: TownFeature[];
  streets: TownFeature[];
  walkways: TownFeature[];
  walls: TownFeature[];
  ground: TownFeature[];
  functionalZones: TownFeature[];
  landmarks: TownFeature[];
}

export interface TownLayerVisibility {
  walls: boolean;
  roads: boolean;
  buildings: boolean;
  landmarks: boolean;
  people: boolean;
  vehicles: boolean;
  heat: boolean;
}

export type FlowAnalysisMode = "people" | "vehicle";

const allLayersVisible: TownLayerVisibility = {
  walls: true,
  roads: true,
  buildings: true,
  landmarks: true,
  people: true,
  vehicles: true,
  heat: true,
};

export interface TownFlowRoad extends TownFeature {
  path: Coordinate[];
  routeCount: number;
  fromName?: string;
  toName?: string;
  peopleRatio: number;
  vehicleRatio: number;
  peopleCount: number;
  vehicleCount: number;
  peopleEntered: number;
  vehicleEntered: number;
  peopleExited: number;
  vehicleExited: number;
  peopleForward: number;
  peopleReverse: number;
  vehicleForward: number;
  vehicleReverse: number;
  roadKind?: TownStreetKind | "walkway";
  pedestrianAccess?: boolean;
  vehicleAccess?: boolean;
  localEstimate?: boolean;
}

type TownStreetKind = "primary" | "ring" | "secondary" | "lane" | "alley";

interface FlowMarker extends TownFeature {
  position: Coordinate;
  flow: "people" | "vehicle";
  sourceId: string;
  fromName?: string;
  toName?: string;
  polygon: Coordinate[];
  angle: number;
}

interface MarkerCandidate extends FlowMarker {
  weight: number;
  coverageId?: string;
}

interface DirectionalRoad {
  id: string;
  path: Coordinate[];
  direction: "forward" | "reverse";
  count: number;
  ratio: number;
}

export interface TownFlowRenderData {
  roads: TownFlowRoad[];
  peopleMarkers: FlowMarker[];
  vehicleMarkers: FlowMarker[];
}

const districtColors: Record<DistrictKind, Color> = {
  residential: [20, 34, 52, 42],
  market: [56, 44, 30, 46],
  industrial: [42, 40, 38, 44],
  storage: [30, 42, 48, 42],
  religious: [40, 32, 48, 46],
  civic: [30, 42, 56, 48],
  military: [52, 34, 32, 46],
  stable: [46, 40, 30, 44],
};

const pearlDistrictColors: Record<DistrictKind, Color> = {
  residential: [175, 168, 148, 42],
  market: [195, 168, 128, 46],
  industrial: [172, 162, 142, 42],
  storage: [168, 172, 155, 42],
  religious: [180, 155, 145, 46],
  civic: [160, 168, 178, 48],
  military: [185, 155, 135, 46],
  stable: [180, 162, 132, 42],
};

const buildingColors: Record<BuildingKind, Color> = {
  residential: [28, 44, 64, 255],
  market: [72, 54, 38, 255],
  workshop: [54, 50, 44, 255],
  storage: [38, 52, 56, 255],
  religious: [50, 40, 58, 255],
  administrative: [38, 54, 68, 255],
  military: [62, 42, 40, 255],
  stable: [56, 50, 38, 255],
  tavern: [78, 54, 32, 255],
  academy: [38, 50, 68, 255],
  hospital: [68, 64, 56, 255],
};

const pearlBuildingColors: Record<BuildingKind, Color> = {
  residential: [148, 170, 138, 255],
  market: [192, 162, 118, 255],
  workshop: [165, 158, 138, 255],
  storage: [150, 165, 150, 255],
  religious: [170, 148, 162, 255],
  administrative: [138, 158, 182, 255],
  military: [180, 148, 132, 255],
  stable: [170, 158, 128, 255],
  tavern: [192, 152, 110, 255],
  academy: [138, 155, 185, 255],
  hospital: [185, 178, 165, 255],
};

const landmarkColors: Record<string, Color> = {
  gate: [104, 110, 126, 255],
  plaza: [220, 226, 236, 220],
  market: [224, 170, 52, 255],
  workshop: [192, 138, 88, 255],
  storage: [132, 156, 138, 255],
  religious: [150, 120, 178, 255],
  administrative: [82, 148, 212, 255],
  military: [222, 92, 78, 255],
  stable: [178, 148, 78, 255],
  tavern: [212, 150, 68, 255],
  academy: [112, 152, 214, 255],
  hospital: [202, 196, 180, 255],
  residential: [106, 130, 144, 255],
};

const pearlLandmarkColors: Record<string, Color> = {
  gate: [82, 68, 56, 255],
  plaza: [52, 42, 34, 225],
  market: [210, 164, 68, 255],
  workshop: [175, 130, 82, 255],
  storage: [132, 155, 130, 255],
  religious: [152, 118, 170, 255],
  administrative: [72, 138, 192, 255],
  military: [196, 96, 76, 255],
  stable: [170, 140, 76, 255],
  tavern: [202, 142, 62, 255],
  academy: [100, 136, 192, 255],
  hospital: [192, 182, 162, 255],
  residential: [110, 135, 142, 255],
};

const mapColors = {
  selection: [223, 174, 78, 255] as Color,
  selectionSoft: [223, 174, 78, 185] as Color,
  edge: [65, 91, 101, 225] as Color,
  road: [105, 127, 136, 235] as Color,
  walkway: [92, 111, 110, 230] as Color,
  wall: [137, 126, 101, 255] as Color,
  buildingEdge: [76, 104, 116, 215] as Color,
  label: [233, 230, 216, 255] as Color,
  people: [93, 210, 177, 255] as Color,
  vehicle: [112, 177, 218, 255] as Color,
};

const pearlMapColors = {
  selection: [204, 118, 52, 255] as Color,
  selectionSoft: [204, 118, 52, 175] as Color,
  edge: [121, 94, 65, 210] as Color,
  road: [218, 194, 151, 245] as Color,
  walkway: [174, 146, 103, 235] as Color,
  wall: [104, 77, 51, 255] as Color,
  buildingEdge: [105, 78, 52, 205] as Color,
  label: [60, 44, 30, 255] as Color,
  people: [48, 133, 105, 255] as Color,
  vehicle: [56, 106, 151, 255] as Color,
};

const buildingDisplayNames: Record<BuildingKind, string> = {
  residential: "居民楼",
  market: "商铺",
  workshop: "工坊",
  storage: "仓库",
  religious: "神殿",
  administrative: "行政厅",
  military: "兵营",
  stable: "马厩",
  tavern: "酒馆",
  academy: "学院",
  hospital: "医馆",
};

type ZoneRgb = readonly [number, number, number];

const zoneColors: Record<string, ZoneRgb> = {
  administrative: [72, 148, 214],
  market: [220, 166, 65],
  religious: [160, 115, 194],
  military: [212, 88, 78],
  workshop: [197, 126, 74],
  storage: [120, 154, 111],
  stable: [107, 151, 119],
};

const pearlZoneColors: Record<string, ZoneRgb> = {
  administrative: [55, 114, 169],
  market: [181, 126, 38],
  religious: [130, 87, 157],
  military: [166, 67, 57],
  workshop: [157, 91, 46],
  storage: [89, 121, 77],
  stable: [77, 116, 84],
};


function boundsFromBundle(bundle: ScenarioBundle): readonly [number, number, number, number] {
  if (bundle.town_skeleton) return bundle.town_skeleton.bounds;
  const points = [
    ...bundle.config.locations.map((location) => location.position),
    ...bundle.config.connections.flatMap((connection) => connection.path),
  ];
  const xs = points.map((point) => point[0]);
  const ys = points.map((point) => point[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

function polygonCenter(polygon: Coordinate[]): Coordinate {
  return [
    polygon.reduce((sum, point) => sum + point[0], 0) / polygon.length,
    polygon.reduce((sum, point) => sum + point[1], 0) / polygon.length,
  ];
}

function townEdgeBoundary(skeleton: NonNullable<ScenarioBundle["town_skeleton"]>): Coordinate[] {
  const points = skeleton.districts.flatMap((district) => district.polygon);
  if (points.length < 3) return [...skeleton.boundary];
  const sorted = [...new Map(points.map((point) => [`${point[0]}:${point[1]}`, point])).values()]
    .sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const cross = (origin: Coordinate, a: Coordinate, b: Coordinate) =>
    (a[0] - origin[0]) * (b[1] - origin[1]) - (a[1] - origin[1]) * (b[0] - origin[0]);
  const lower: Coordinate[] = [];
  for (const point of sorted) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], point) <= 0) lower.pop();
    lower.push(point);
  }
  const upper: Coordinate[] = [];
  for (const point of [...sorted].reverse()) {
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], point) <= 0) upper.pop();
    upper.push(point);
  }
  const hull = [...lower.slice(0, -1), ...upper.slice(0, -1)];
  return hull.length >= 3 ? hull : [...skeleton.boundary];
}

function projectToBoundary(point: Coordinate, boundary: Coordinate[]): Coordinate {
  let best = boundary[0] ?? point;
  let bestDistance = Number.POSITIVE_INFINITY;
  for (let index = 0; index < boundary.length; index += 1) {
    const start = boundary[index];
    const end = boundary[(index + 1) % boundary.length];
    const dx = end[0] - start[0];
    const dy = end[1] - start[1];
    const lengthSquared = dx * dx + dy * dy;
    const ratio = lengthSquared <= 0 ? 0 : Math.max(0, Math.min(1, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / lengthSquared));
    const candidate: Coordinate = [start[0] + dx * ratio, start[1] + dy * ratio];
    const distance = (candidate[0] - point[0]) ** 2 + (candidate[1] - point[1]) ** 2;
    if (distance < bestDistance) {
      best = candidate;
      bestDistance = distance;
    }
  }
  return best;
}

function pointInsideBoundary(point: Coordinate, boundary: Coordinate[]): boolean {
  let inside = false;
  for (let index = 0; index < boundary.length; index += 1) {
    const start = boundary[index];
    const end = boundary[(index + 1) % boundary.length];
    const cross = (point[0] - start[0]) * (end[1] - start[1]) - (point[1] - start[1]) * (end[0] - start[0]);
    const dot = (point[0] - start[0]) * (point[0] - end[0]) + (point[1] - start[1]) * (point[1] - end[1]);
    if (Math.abs(cross) < 0.001 && dot <= 0) return true;
    if ((start[1] > point[1]) !== (end[1] > point[1])) {
      const xAtY = (end[0] - start[0]) * (point[1] - start[1]) / (end[1] - start[1]) + start[0];
      if (point[0] < xAtY) inside = !inside;
    }
  }
  return inside;
}

function segmentBoundaryParameter(
  start: Coordinate,
  end: Coordinate,
  edgeStart: Coordinate,
  edgeEnd: Coordinate,
): number | null {
  const dx = end[0] - start[0];
  const dy = end[1] - start[1];
  const ex = edgeEnd[0] - edgeStart[0];
  const ey = edgeEnd[1] - edgeStart[1];
  const denominator = dx * ey - dy * ex;
  if (Math.abs(denominator) < 0.000001) return null;
  const offsetX = edgeStart[0] - start[0];
  const offsetY = edgeStart[1] - start[1];
  const t = (offsetX * ey - offsetY * ex) / denominator;
  const u = (offsetX * dy - offsetY * dx) / denominator;
  return t >= 0 && t <= 1 && u >= 0 && u <= 1 ? t : null;
}

function clipPathToBoundary(path: Coordinate[], boundary: Coordinate[]): Coordinate[] {
  if (path.length < 2 || boundary.length < 3) return path;
  const pieces: Coordinate[][] = [];
  let current: Coordinate[] = [];
  const flush = () => {
    if (current.length >= 2) pieces.push(current);
    current = [];
  };
  const samePoint = (left: Coordinate, right: Coordinate) =>
    Math.abs(left[0] - right[0]) < 0.001 && Math.abs(left[1] - right[1]) < 0.001;

  for (let index = 0; index < path.length - 1; index += 1) {
    const start = path[index];
    const end = path[index + 1];
    const parameters = [0, 1];
    for (let edgeIndex = 0; edgeIndex < boundary.length; edgeIndex += 1) {
      const parameter = segmentBoundaryParameter(
        start,
        end,
        boundary[edgeIndex],
        boundary[(edgeIndex + 1) % boundary.length],
      );
      if (parameter !== null) parameters.push(parameter);
    }
    parameters.sort((left, right) => left - right);
    const uniqueParameters = parameters.filter((parameter, parameterIndex) => parameterIndex === 0 || parameter - parameters[parameterIndex - 1] > 0.000001);
    for (let partIndex = 0; partIndex < uniqueParameters.length - 1; partIndex += 1) {
      const from = uniqueParameters[partIndex];
      const to = uniqueParameters[partIndex + 1];
      const midpoint = (from + to) / 2;
      const midpointPoint: Coordinate = [start[0] + (end[0] - start[0]) * midpoint, start[1] + (end[1] - start[1]) * midpoint];
      if (!pointInsideBoundary(midpointPoint, boundary)) {
        flush();
        continue;
      }
      const fromPoint: Coordinate = [start[0] + (end[0] - start[0]) * from, start[1] + (end[1] - start[1]) * from];
      const toPoint: Coordinate = [start[0] + (end[0] - start[0]) * to, start[1] + (end[1] - start[1]) * to];
      if (!current.length) current.push(fromPoint);
      else if (!samePoint(current[current.length - 1], fromPoint)) {
        flush();
        current.push(fromPoint);
      }
      if (!samePoint(current[current.length - 1], toPoint)) current.push(toPoint);
    }
  }
  flush();
  if (!pieces.length) return [];
  return pieces.reduce((longest, piece) => piece.length > longest.length ? piece : longest, pieces[0]);
}

function functionalZones(skeleton: NonNullable<ScenarioBundle["town_skeleton"]>): TownFeature[] {
  const buildings = new Map(skeleton.buildings.map((building) => [building.id, building]));
  const districts = new Map(skeleton.districts.map((district) => [district.id, district]));
  const seen = new Set<string>();
  const zones: TownFeature[] = [];
  for (const landmark of skeleton.landmarks) {
    if (landmark.kind === "gate" || landmark.kind === "plaza" || !landmark.building_id) continue;
    const building = buildings.get(landmark.building_id);
    const district = building ? districts.get(building.district_id) : undefined;
    if (!district || !zoneColors[landmark.kind]) continue;
    const key = `${landmark.kind}:${district.id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    zones.push({
      id: `functional-zone-${landmark.kind}-${district.id}`,
      sourceId: district.id,
      name: `${landmark.name}范围`,
      kind: landmark.kind,
      polygon: district.polygon,
      position: polygonCenter(district.polygon),
    });
  }
  return zones;
}

const locationFeatureCache = new WeakMap<ScenarioBundle, Map<string, string>>();
const walkwayLocationCache = new WeakMap<ScenarioBundle, Map<string, TownWalkway[]>>();
const flowConnectionCache = new WeakMap<ScenarioBundle, FlowConnection[]>();
const flowLocationCache = new WeakMap<ScenarioBundle, Array<{ id: string; name: string; position: Coordinate }>>();
const streetCache = new WeakMap<ScenarioBundle, Map<string, TownStreet>>();

function locationByFeature(bundle: ScenarioBundle): Map<string, string> {
  const cached = locationFeatureCache.get(bundle);
  if (cached) return cached;
  const result = new Map(Object.entries(bundle.simulation_package?.bindings.location_feature_ids ?? {}).flatMap(
    ([locationId, featureIds]) => featureIds.map((featureId) => [featureId, locationId] as [string, string]),
  ));
  locationFeatureCache.set(bundle, result);
  return result;
}

function townWalkways(bundle: ScenarioBundle): TownWalkway[] {
  const skeleton = bundle.town_skeleton;
  if (!skeleton) return [];
  const boundary = townEdgeBoundary(skeleton);
  if (skeleton.walkways !== undefined) {
    return skeleton.walkways
      .map((walkway) => ({ ...walkway, path: clipPathToBoundary(walkway.path, boundary) }))
      .filter((walkway) => walkway.path.length >= 2);
  }

  return [];
}

function walkwaysByLocation(bundle: ScenarioBundle): Map<string, TownWalkway[]> {
  const cached = walkwayLocationCache.get(bundle);
  if (cached) return cached;
  const result = new Map<string, TownWalkway[]>();
  const boundLocation = locationByFeature(bundle);
  for (const walkway of townWalkways(bundle)) {
    const locationId = boundLocation.get(walkway.id)
      ?? boundLocation.get(walkway.district_id)
      ?? `location-${walkway.district_id}`;
    const entries = result.get(locationId) ?? [];
    entries.push(walkway);
    result.set(locationId, entries);
  }
  walkwayLocationCache.set(bundle, result);
  return result;
}

function townStreetsById(bundle: ScenarioBundle): Map<string, TownStreet> {
  const cached = streetCache.get(bundle);
  if (cached) return cached;
  const skeleton = bundle.town_skeleton;
  const boundary = skeleton ? townEdgeBoundary(skeleton) : [];
  const result = new Map(
    (skeleton?.streets ?? [])
      .map((street) => ({ ...street, path: clipPathToBoundary(street.path, boundary) }))
      .filter((street) => street.path.length >= 2)
      .map((street) => [street.id, street] as [string, TownStreet]),
  );
  streetCache.set(bundle, result);
  return result;
}

function wallSegments(boundary: Coordinate[], landmarks: TownLandmark[]): TownFeature[] {
  const gates = landmarks.filter((landmark) => landmark.kind === "gate").map((landmark) => landmark.position);
  // No gate landmarks → not a walled town → don't render walls
  if (gates.length === 0) return [];
  const wornWall = boundary.length <= 12;
  return boundary.map((start, index) => {
    const end = boundary[(index + 1) % boundary.length];
    return {
      id: `wall-${index}`,
      name: wornWall ? "残旧城墙" : "城墙",
      kind: "wall",
      path: [start, end],
      width: wornWall ? 3.2 + (index % 3) * 0.35 : 4,
    };
  });
}

function rectangle(position: Coordinate, width: number, height: number, rotation = 0): Coordinate[] {
  return [
    [-width / 2, -height / 2],
    [width / 2, -height / 2],
    [width / 2, height / 2],
    [-width / 2, height / 2],
  ].map(([x, y]) => [
    position[0] + x * Math.cos(rotation) - y * Math.sin(rotation),
    position[1] + x * Math.sin(rotation) + y * Math.cos(rotation),
  ]);
}

function circle(position: Coordinate, radius: number, sides = 10): Coordinate[] {
  return Array.from({ length: sides }, (_, index) => {
    const angle = index * Math.PI * 2 / sides;
    return [position[0] + Math.cos(angle) * radius, position[1] + Math.sin(angle) * radius];
  });
}

function offset(position: Coordinate, x: number, y: number): Coordinate {
  return [position[0] + x, position[1] + y];
}

function landmarkMotif(feature: TownFeature, size: number): TownFeature[] {
  const position = feature.position ?? [0, 0];
  const part = (id: string, polygon: Coordinate[]): TownFeature => ({
    ...feature,
    id: `${feature.id}-${id}`,
    sourceId: feature.sourceId ?? feature.id,
    polygon,
  });

  switch (feature.kind) {
    case "administrative":
      return [
        part("hall", rectangle(position, size * 1.45, size * 0.9)),
        part("tower", rectangle(offset(position, 0, size * 0.58), size * 0.42, size * 0.58)),
      ];
    case "market":
      return [
        part("court", rectangle(position, size * 0.72, size * 0.72, Math.PI / 4)),
        ...([[0, 0.58], [0.58, 0], [0, -0.58], [-0.58, 0]] as const).map(([x, y], index) =>
          part(`stall-${index}`, rectangle(offset(position, x * size, y * size), size * 0.46, size * 0.3, x === 0 ? 0 : Math.PI / 2)),
        ),
      ];
    case "religious":
      return [
        part("nave", rectangle(position, size * 0.5, size * 1.5)),
        part("crossing", rectangle(position, size * 1.15, size * 0.42)),
        part("dome", circle(offset(position, 0, size * 0.64), size * 0.28)),
      ];
    case "military":
      return [
        part("keep", rectangle(position, size * 1.18, size * 0.94)),
        ...([-1, 1] as const).flatMap((x) => ([-1, 1] as const).map((y) =>
          part(`tower-${x}-${y}`, circle(offset(position, x * size * 0.56, y * size * 0.44), size * 0.25, 8)),
        )),
      ];
    case "storage":
      return [-0.48, 0, 0.48].map((x, index) =>
        part(`granary-${index}`, circle(offset(position, x * size, 0), size * 0.32, 12)),
      );
    case "workshop":
      return [
        part("anvil", rectangle(offset(position, 0, -size * 0.28), size * 1.2, size * 0.38)),
        part("stem", rectangle(position, size * 0.28, size * 0.9, -0.55)),
        part("hammer", rectangle(offset(position, -size * 0.25, size * 0.32), size * 0.82, size * 0.28, -0.55)),
      ];
    case "stable":
      return [
        part("range-a", rectangle(offset(position, -size * 0.34, 0), size * 0.42, size * 1.35)),
        part("range-b", rectangle(offset(position, size * 0.34, 0), size * 0.42, size * 1.35)),
        part("crossing", rectangle(position, size * 0.68, size * 0.24)),
      ];
    case "tavern":
      return [
        part("hall", rectangle(position, size * 1.1, size * 0.85)),
        part("chimney", rectangle(offset(position, size * 0.37, -size * 0.2), size * 0.16, size * 0.35)),
        part("sign", circle(offset(position, 0, size * 0.55), size * 0.22, 6)),
      ];
    case "academy":
      return [
        part("main", rectangle(position, size * 1.25, size * 0.7)),
        part("court", rectangle(offset(position, 0, -size * 0.68), size * 0.6, size * 0.42)),
        part("tower", rectangle(offset(position, 0, size * 0.6), size * 0.32, size * 0.48)),
      ];
    case "hospital":
      return [
        part("hwing", rectangle(position, size * 1.1, size * 0.35)),
        part("vwing", rectangle(position, size * 0.35, size * 1.1)),
        ...([-0.52, 0.52] as const).flatMap((x) => ([-0.52, 0.52] as const).map((y) =>
          part(`court-${x > 0 ? "r" : "l"}-${y > 0 ? "u" : "d"}`, circle(offset(position, x * size, y * size), size * 0.18, 8)),
        )),
      ];
    case "plaza":
      return [
        part("square", rectangle(position, size * 1.35, size * 1.35)),
        part("fountain", circle(position, size * 0.27, 12)),
      ];
    case "fountain":
      return [
        part("basin", circle(position, size * 0.72, 16)),
        part("rim", circle(position, size * 0.52, 12)),
        part("spout", circle(position, size * 0.15, 6)),
        part("splash-n", circle(offset(position, 0, size * 0.33), size * 0.08, 4)),
        part("splash-s", circle(offset(position, 0, -size * 0.33), size * 0.08, 4)),
        part("splash-e", circle(offset(position, size * 0.33, 0), size * 0.08, 4)),
        part("splash-w", circle(offset(position, -size * 0.33, 0), size * 0.08, 4)),
      ];
    case "statue":
      return [
        part("base", rectangle(offset(position, 0, -size * 0.35), size * 0.7, size * 0.3)),
        part("pedestal", rectangle(offset(position, 0, -size * 0.15), size * 0.32, size * 0.5)),
        part("figure", rectangle(offset(position, 0, size * 0.2), size * 0.12, size * 0.38)),
        part("head", circle(offset(position, 0, size * 0.46), size * 0.1, 6)),
      ];
    case "obelisk":
      return [
        part("plinth", rectangle(position, size * 0.6, size * 0.24)),
        part("shaft", [
          [position[0] - size * 0.08, position[1] - size * 0.12],
          [position[0] + size * 0.08, position[1] - size * 0.12],
          [position[0] + size * 0.03, position[1] + size * 0.8],
          [position[0] - size * 0.03, position[1] + size * 0.8],
        ]),
        part("cap", [
          [position[0], position[1] + size * 0.95],
          [position[0] - size * 0.08, position[1] + size * 0.78],
          [position[0] + size * 0.08, position[1] + size * 0.78],
        ]),
      ];
    case "well":
      return [
        part("ring", circle(position, size * 0.5, 14)),
        part("inner", circle(position, size * 0.28, 10)),
        part("roof-beam", rectangle(offset(position, 0, size * 0.3), size * 0.8, size * 0.08)),
        part("roof-beam-2", rectangle(position, size * 0.08, size * 0.8)),
        part("roof", [
          [position[0], position[1] + size * 0.5],
          [position[0] - size * 0.6, position[1] + size * 0.25],
          [position[0] + size * 0.6, position[1] + size * 0.25],
        ]),
      ];
    case "grand-tree":
      return [
        part("trunk", rectangle(position, size * 0.14, size * 0.5)),
        part("canopy", circle(offset(position, 0, size * 0.28), size * 0.62, 18)),
        part("canopy-l", circle(offset(position, -size * 0.28, size * 0.12), size * 0.35, 12)),
        part("canopy-r", circle(offset(position, size * 0.28, size * 0.12), size * 0.35, 12)),
      ];
    case "gate":
      return [
        part("tower-a", rectangle(offset(position, -size * 0.42, 0), size * 0.42, size * 0.86)),
        part("tower-b", rectangle(offset(position, size * 0.42, 0), size * 0.42, size * 0.86)),
        part("lintel", rectangle(offset(position, 0, size * 0.35), size * 0.7, size * 0.22)),
      ];
    default:
      return [part("mark", rectangle(position, size, size, Math.PI / 4))];
  }
}

export function assembleTownRenderData(bundle: ScenarioBundle): TownRenderData {
  const skeleton = bundle.town_skeleton;
  if (!skeleton) {
    const bounds = boundsFromBundle(bundle);
    return {
      bounds,
      districts: [],
      buildings: [],
      walls: [],
      walkways: [],
      ground: [{
        id: "legacy-ground",
        name: "聚落地表",
        kind: "ground",
        polygon: [
          [bounds[0], bounds[1]],
          [bounds[2], bounds[1]],
          [bounds[2], bounds[3]],
          [bounds[0], bounds[3]],
        ],
      }],
      functionalZones: [],
      streets: bundle.config.connections.map((connection) => ({
        id: connection.id,
        name: `${connection.from_location_id} -> ${connection.to_location_id}`,
        kind: "primary",
        path: connection.path,
        width: 4,
      })),
      landmarks: bundle.config.locations.map((location) => ({
        id: location.id,
        name: location.name,
        kind: "plaza",
        position: location.position,
      })),
    };
  }
  const boundLocation = locationByFeature(bundle);
  const townEdge = townEdgeBoundary(skeleton);
  return {
    bounds: skeleton.bounds,
    districts: skeleton.districts.map((district) => ({
      id: district.id,
      sourceId: boundLocation.get(district.id),
      name: district.kind,
      kind: district.kind,
      polygon: district.polygon,
    })),
    buildings: skeleton.buildings.map((building) => ({
      id: building.id,
      sourceId: boundLocation.get(building.id),
      name: buildingDisplayNames[building.kind] ?? building.kind,
      kind: building.kind,
      polygon: building.polygon,
    })),
    streets: skeleton.streets.map((street) => ({
      id: street.id,
      name: street.kind,
      kind: street.kind,
      path: clipPathToBoundary(street.path, townEdge),
      width: street.width,
    })).filter((street) => street.path.length >= 2),
    walkways: townWalkways(bundle).map((walkway) => ({
      id: walkway.id,
      sourceId: boundLocation.get(walkway.id),
      name: "建筑间步道",
      kind: "walkway",
      path: walkway.path,
      width: walkway.width,
    })),
    walls: wallSegments(townEdge, skeleton.landmarks),
    ground: [{ id: "settlement-ground", name: "聚落地表", kind: "ground", polygon: townEdge }],
    functionalZones: functionalZones(skeleton),
    landmarks: skeleton.landmarks.map((landmark) => ({
      id: landmark.id,
      sourceId: boundLocation.get(landmark.id),
      name: landmark.name,
      kind: landmark.kind,
      position: landmark.kind === "gate" ? projectToBoundary(landmark.position, townEdge) : landmark.position,
    })),
  };
}

function colorsForTheme(theme: "pearl" | "night") {
  return {
    mc: theme === "pearl" ? pearlMapColors : mapColors,
    dc: theme === "pearl" ? pearlDistrictColors : districtColors,
    bc: theme === "pearl" ? pearlBuildingColors : buildingColors,
    lc: theme === "pearl" ? pearlLandmarkColors : landmarkColors,
  };
}

export function createStaticTownLayers(
  data: TownRenderData,
  selectedFeatureId: string | null,
  visibility: TownLayerVisibility = allLayersVisible,
  compactLabels = false,
  modelMatrix?: Float32Array,
  theme: "pearl" | "night" = "night",
): Layer[] {
  const width = Math.max(1, data.bounds[2] - data.bounds[0]);
  const height = Math.max(1, data.bounds[3] - data.bounds[1]);
  const landmarkSize = Math.max(7, Math.min(18, Math.hypot(width, height) * 0.014));
  const landmarkPolygons = data.landmarks.flatMap((feature) => landmarkMotif(feature, landmarkSize));
  const compactLabelKinds = new Set(["gate", "plaza", "administrative", "market", "religious"]);
  const labelLandmarks = compactLabels
    ? data.landmarks.filter((feature) => compactLabelKinds.has(feature.kind))
    : data.landmarks;
  const zoneLabels = compactLabels ? data.functionalZones.filter((_, index) => index % 2 === 0) : data.functionalZones;
  const center: Coordinate = [(data.bounds[0] + data.bounds[2]) / 2, (data.bounds[1] + data.bounds[3]) / 2];
  const wallTowers = Array.from(new Map(data.walls.flatMap((wall) => wall.path ?? []).map((position, index) => [
    `${position[0]}:${position[1]}`,
    { id: `wall-tower-${index}`, name: "Wall Tower", kind: "wall", position },
  ])).values());
  const { mc, dc, bc, lc } = colorsForTheme(theme);
  const groundColor: Color = theme === "pearl" ? [148, 111, 66, 62] : [34, 63, 67, 72];
  const common = { coordinateSystem: COORDINATE_SYSTEM.CARTESIAN, ...(modelMatrix ? { modelMatrix } : {}) } as const;
  return [
    new PolygonLayer<TownFeature>({
      id: "settlement-ground",
      data: data.ground,
      ...common,
      pickable: false,
      stroked: false,
      filled: true,
      getPolygon: (feature) => feature.polygon!,
      getFillColor: groundColor,
    }),
    new PolygonLayer<TownFeature>({
      id: "district-fill",
      data: data.districts,
      ...common,
      pickable: true,
      stroked: true,
      filled: true,
      lineWidthUnits: "pixels",
      getPolygon: (feature) => feature.polygon!,
      getFillColor: (feature) => dc[feature.kind as DistrictKind] ?? [54, 81, 91, 30],
      getLineColor: (feature) => feature.id === selectedFeatureId ? mc.selection : mc.buildingEdge,
      getLineWidth: (feature) => feature.id === selectedFeatureId ? 2 : 0.5,
    }),
    ...(visibility.landmarks && data.functionalZones.length ? [new PolygonLayer<TownFeature>({
      id: "functional-zones",
      data: data.functionalZones,
      ...common,
      pickable: false,
      stroked: true,
      filled: true,
      lineWidthUnits: "pixels",
      getPolygon: (feature) => feature.polygon!,
      getFillColor: (feature) => {
        const [r, g, b] = (theme === "pearl" ? pearlZoneColors : zoneColors)[feature.kind] ?? [120, 120, 120];
        return [r, g, b, 40] as Color;
      },
      getLineColor: (feature) => {
        const [r, g, b] = (theme === "pearl" ? pearlZoneColors : zoneColors)[feature.kind] ?? [120, 120, 120];
        return [r, g, b, 160] as Color;
      },
      getLineWidth: 1.25,
    })] : []),
    ...(visibility.buildings ? [new PolygonLayer<TownFeature>({
      id: "building-fill",
      data: data.buildings,
      ...common,
      pickable: true,
      stroked: true,
      filled: true,
      lineWidthUnits: "pixels",
      getPolygon: (feature) => feature.polygon!,
      getFillColor: (feature) => bc[feature.kind as BuildingKind] ?? bc.residential,
      getLineColor: (feature) => feature.id === selectedFeatureId ? mc.selection : mc.buildingEdge,
      getLineWidth: (feature) => feature.id === selectedFeatureId ? 2.5 : 0.85,
    })] : []),
    ...(visibility.roads && data.walkways.length ? [new PathLayer<TownFeature>({
      id: "block-walkway-edge",
      data: data.walkways,
      ...common,
      pickable: false,
      widthUnits: "pixels",
      capRounded: true,
      jointRounded: true,
      getPath: (feature) => feature.path!,
      getColor: mc.edge,
      getWidth: 4,
    }), new PathLayer<TownFeature>({
      id: "block-walkway-base",
      data: data.walkways,
      ...common,
      pickable: false,
      widthUnits: "pixels",
      capRounded: true,
      jointRounded: true,
      getPath: (feature) => feature.path!,
      getColor: mc.walkway,
      getWidth: 2.4,
    })] : []),
    ...(visibility.roads ? [new PathLayer<TownFeature>({
      id: "road-edge",
      data: data.streets,
      ...common,
      pickable: false,
      widthUnits: "pixels",
      capRounded: true,
      jointRounded: true,
      getPath: (feature) => feature.path!,
      getColor: (feature) => feature.id === selectedFeatureId ? mc.selectionSoft : mc.edge,
      getWidth: (feature) => feature.kind === "primary" ? 8 : feature.kind === "ring" ? 5 : feature.kind === "secondary" ? 3 : feature.kind === "lane" ? 1.8 : 1.2,
    }),
    new PathLayer<TownFeature>({
      id: "road-base",
      data: data.streets,
      ...common,
      pickable: true,
      widthUnits: "pixels",
      capRounded: true,
      jointRounded: true,
      getPath: (feature) => feature.path!,
      getColor: (feature) => {
        if (feature.id === selectedFeatureId) return mc.selection;
        if (feature.kind === "alley") return [mc.road[0], mc.road[1], mc.road[2], 135];
        if (feature.kind === "lane") return [mc.road[0], mc.road[1], mc.road[2], 190];
        return mc.road;
      },
      getWidth: (feature) => feature.kind === "primary" ? 6 : feature.kind === "ring" ? 3.5 : feature.kind === "secondary" ? 2 : feature.kind === "lane" ? 1.35 : 0.95,
    })] : []),
    ...(visibility.walls ? [new PathLayer<TownFeature>({
      id: "boundary-wall",
      data: data.walls,
      ...common,
      pickable: true,
      widthUnits: "pixels",
      capRounded: false,
      jointRounded: false,
      getPath: (feature) => feature.path!,
      getColor: (feature) => feature.id === selectedFeatureId ? mc.selection : mc.wall,
      getWidth: (feature) => feature.id === selectedFeatureId ? 5.5 : feature.width ?? 4,
    }),
    new ScatterplotLayer<TownFeature>({
      id: "wall-towers",
      data: wallTowers,
      ...common,
      pickable: false,
      radiusUnits: "pixels",
      getPosition: (feature) => feature.position!,
      getRadius: 3,
      getFillColor: mc.wall,
    })] : []),
    ...(visibility.landmarks ? [new PolygonLayer<TownFeature>({
      id: "landmark-symbols",
      data: landmarkPolygons,
      ...common,
      pickable: true,
      stroked: true,
      filled: true,
      lineWidthUnits: "pixels",
      getPolygon: (feature) => feature.polygon!,
      getFillColor: (feature) => lc[feature.kind] ?? lc.residential,
      getLineColor: (feature) => feature.sourceId === selectedFeatureId ? mc.selection : mc.buildingEdge,
      getLineWidth: (feature) => feature.sourceId === selectedFeatureId ? 2.5 : 1,
    }),
    new TextLayer<TownFeature>({
      id: "functional-zone-labels",
      data: zoneLabels,
      ...common,
      pickable: false,
      billboard: true,
      fontFamily: "Noto Sans SC Variable",
      fontWeight: 600,
      getText: (feature) => feature.name,
      getPosition: (feature) => feature.position!,
      getColor: (feature) => {
        const [r, g, b] = (theme === "pearl" ? pearlZoneColors : zoneColors)[feature.kind] ?? [120, 120, 120];
        return [r, g, b, 210] as Color;
      },
      getSize: compactLabels ? 9 : 10,
      getTextAnchor: "middle",
      getAlignmentBaseline: "center",
      background: true,
      getBackgroundColor: theme === "pearl" ? [248, 244, 232, 185] as Color : [10, 14, 22, 175] as Color,
      backgroundPadding: [3, 2],
    }),
    new TextLayer<TownFeature>({
      id: "landmark-labels",
      data: labelLandmarks,
      ...common,
      pickable: false,
      billboard: true,
      characterSet: "auto",
      fontFamily: "Noto Sans SC Variable",
      fontWeight: 650,
      getText: (feature) => feature.name,
      getPosition: (feature) => feature.position!,
      getColor: mc.label,
      getSize: compactLabels ? 10 : 12,
      getPixelOffset: (feature) => {
        if (feature.kind === "gate" && feature.position) {
          const dx = feature.position[0] - center[0];
          const dy = feature.position[1] - center[1];
          if (Math.abs(dx) > Math.abs(dy)) return [dx > 0 ? -16 : 16, 0];
          return [0, dy > 0 ? -20 : 20];
        }
        const offsets: Record<string, [number, number]> = {
          plaza: compactLabels ? [24, 34] : [0, 28],
          administrative: compactLabels ? [-42, -26] : [0, -24],
          market: compactLabels ? [42, -16] : [40, 0],
          religious: compactLabels ? [-42, -16] : [-40, 0],
          military: [34, -24],
          storage: [30, 25],
          workshop: [38, 18],
          stable: [-38, 18],
        };
        return offsets[feature.kind] ?? [0, -13];
      },
      getTextAnchor: (feature) => {
        if (feature.kind !== "gate" || !feature.position) return "middle";
        const dx = feature.position[0] - center[0];
        const dy = feature.position[1] - center[1];
        if (Math.abs(dx) <= Math.abs(dy)) return "middle";
        return dx > 0 ? "end" : "start";
      },
      getAlignmentBaseline: "bottom",
      background: true,
      getBackgroundColor: theme === "pearl" ? [248, 244, 232, 220] as Color : [10, 14, 22, 225] as Color,
      backgroundPadding: [4, 3],
    })] : []),
  ];
}

type FlowConnection = {
  id: string;
  path: Coordinate[];
  streetIds: string[];
  streetDirections: Array<"forward" | "reverse">;
  flowStreetIds: Record<string, string[]>;
  flowStreetDirections: Record<string, Array<"forward" | "reverse">>;
  fromLocationId: string;
  toLocationId: string;
  capacity: Record<string, number>;
  travelTime: Record<string, number>;
};

function flowConnections(bundle: ScenarioBundle): FlowConnection[] {
  const cached = flowConnectionCache.get(bundle);
  if (cached) return cached;
  let result: FlowConnection[];
  const boundary = bundle.town_skeleton ? townEdgeBoundary(bundle.town_skeleton) : [];
  if (bundle.simulation_package) {
    result = bundle.simulation_package.connections.map((connection) => ({
      id: connection.id,
      path: clipPathToBoundary(connection.path, boundary),
      streetIds: connection.street_segment_ids,
      streetDirections: connection.street_directions ?? [],
      flowStreetIds: connection.flow_street_segment_ids ?? {},
      flowStreetDirections: connection.flow_street_directions ?? {},
      fromLocationId: connection.from_location_id,
      toLocationId: connection.to_location_id,
      capacity: connection.capacity_per_tick,
      travelTime: connection.travel_time_ticks,
    }));
  } else {
    result = bundle.config.connections.map((connection) => ({
      id: connection.id,
      path: clipPathToBoundary(connection.path, boundary),
      streetIds: [connection.id],
      streetDirections: [],
      flowStreetIds: {},
      flowStreetDirections: {},
      fromLocationId: connection.from_location_id,
      toLocationId: connection.to_location_id,
      capacity: connection.capacity_per_tick,
      travelTime: Object.fromEntries(bundle.config.flow_types.map((flow) => [flow.id, connection.travel_time_ticks])),
    }));
  }
  flowConnectionCache.set(bundle, result);
  return result;
}

function flowIds(bundle: ScenarioBundle): { people: string | null; vehicle: string | null } {
  const types = bundle.simulation_package?.flow_types ?? bundle.config.flow_types;
  const people = types.find((flow) => flow.id === "pedestrian" || flow.id === "citizen" || flow.unit === "people")?.id ?? types[0]?.id ?? null;
  const vehicle = types.find((flow) => flow.id === "vehicle" || flow.unit === "vehicles")?.id ?? null;
  return { people, vehicle };
}

function pathPoint(path: Coordinate[], progress: number): { position: Coordinate; angle: number } {
  if (path.length < 2) return { position: path[0] ?? [0, 0], angle: 0 };
  const lengths = path.slice(1).map((point, index) => Math.hypot(point[0] - path[index][0], point[1] - path[index][1]));
  const total = Math.max(0.001, lengths.reduce((sum, length) => sum + length, 0));
  let distance = ((progress % 1) + 1) % 1 * total;
  for (let index = 0; index < lengths.length; index += 1) {
    const length = lengths[index];
    if (distance <= length || index === lengths.length - 1) {
      const start = path[index];
      const end = path[index + 1];
      const ratio = length <= 0 ? 0 : distance / length;
      return {
        position: [start[0] + (end[0] - start[0]) * ratio, start[1] + (end[1] - start[1]) * ratio],
        angle: Math.atan2(end[1] - start[1], end[0] - start[0]),
      };
    }
    distance -= length;
  }
  return { position: path[path.length - 1], angle: 0 };
}

function routeStreetPaths(
  streetsById: Map<string, { path: Coordinate[] }>,
  connection: FlowConnection,
  flowId?: string,
): Coordinate[][] {
  const hasFlowRoute = flowId !== undefined && Object.prototype.hasOwnProperty.call(connection.flowStreetIds, flowId);
  const streetIds = hasFlowRoute ? connection.flowStreetIds[flowId!] : connection.streetIds;
  const streetDirections = hasFlowRoute ? connection.flowStreetDirections[flowId!] : connection.streetDirections;
  if (!streetIds?.length || streetIds.length !== streetDirections?.length || !streetsById.size) {
    return [];
  }
  const paths: Coordinate[][] = [];
  for (const [index, streetId] of streetIds.entries()) {
    const street = streetsById.get(streetId);
    if (!street?.path || street.path.length < 2) return [];
    paths.push(streetDirections[index] === "reverse" ? [...street.path].reverse() : street.path);
  }
  return paths;
}

function joinRoutePaths(paths: Coordinate[][]): Coordinate[] | null {
  return paths.reduce<Coordinate[] | null>((joined, path) => {
    if (joined === null) return null;
    if (!joined.length) return [...path];
    const start = path[0];
    const last = joined[joined.length - 1];
    const beginsAtLast = start[0] === last[0] && start[1] === last[1];
    return beginsAtLast ? [...joined, ...path.slice(1)] : null;
  }, []);
}

function routeStreetIdsForFlow(connection: FlowConnection, flowId: string): string[] {
  if (Object.prototype.hasOwnProperty.call(connection.flowStreetIds, flowId)) {
    return connection.flowStreetIds[flowId];
  }
  return connection.streetIds;
}

function snapshotFlow(snapshot: SnapshotState, connectionId: string, flowId: string): {
  inTransit: number;
  departed: number;
  arrived: number;
  streetInTransit: number[];
} {
  if (snapshot.schema_version === 2) {
    const value = (snapshot as FlowSnapshot).connections[connectionId]?.[flowId];
    return {
      inTransit: value?.in_transit ?? 0,
      departed: value?.departed ?? 0,
      arrived: value?.arrived ?? 0,
      streetInTransit: value?.street_in_transit ?? [],
    };
  }
  const value = (snapshot as LegacySnapshotState).connection_activity[connectionId]?.[flowId];
  const buckets = (snapshot as LegacySnapshotState).transit_buckets[connectionId]?.[flowId] ?? [];
  return {
    inTransit: buckets.reduce((sum, count) => sum + count, 0),
    departed: value?.departed ?? 0,
    arrived: value?.arrived ?? 0,
    streetInTransit: [],
  };
}

function flowRatio(flow: { inTransit: number; departed: number; arrived: number }, capacity: number, travelTime: number): number {
  const occupancyRatio = flow.inTransit / Math.max(1, capacity * travelTime);
  const tickThroughputRatio = Math.max(flow.departed, flow.arrived) / Math.max(1, capacity);
  return Math.min(1, Math.max(occupancyRatio, tickThroughputRatio));
}

function aggregatePhysicalRoads(
  bundle: ScenarioBundle,
  routes: TownFlowRoad[],
  connections: FlowConnection[],
  snapshot: SnapshotState,
  peopleId: string | null,
  vehicleId: string | null,
): TownFlowRoad[] {
  if (!bundle.town_skeleton) return routes;
  const streets = townStreetsById(bundle);
  const streetSnapshots = snapshot.schema_version === 2 ? snapshot.streets : undefined;
  const hasExactStreetData = Boolean(streetSnapshots && Object.keys(streetSnapshots).length);
  const dominantLoads = new Map<string, number>();
  const aggregated = new Map<string, TownFlowRoad>();

  for (const street of streets.values()) {
    const people = peopleId ? streetSnapshots?.[street.id]?.[peopleId] : undefined;
    const vehicle = vehicleId ? streetSnapshots?.[street.id]?.[vehicleId] : undefined;
    aggregated.set(street.id, {
      id: street.id,
      name: street.kind,
      kind: "flow-road",
      path: street.path,
      width: street.width,
      routeCount: 0,
      peopleRatio: 0,
      vehicleRatio: 0,
      peopleCount: people?.in_transit ?? 0,
      vehicleCount: vehicle?.in_transit ?? 0,
      peopleEntered: people?.entered ?? 0,
      vehicleEntered: vehicle?.entered ?? 0,
      peopleExited: people?.exited ?? 0,
      vehicleExited: vehicle?.exited ?? 0,
      peopleForward: people?.forward_in_transit ?? 0,
      peopleReverse: people?.reverse_in_transit ?? 0,
      vehicleForward: vehicle?.forward_in_transit ?? 0,
      vehicleReverse: vehicle?.reverse_in_transit ?? 0,
      roadKind: street.kind,
      pedestrianAccess: street.pedestrian_access !== false,
      vehicleAccess: street.vehicle_access !== false,
    });
  }

  routes.forEach((route, index) => {
    const load = route.peopleCount + route.vehicleCount;
    const connection = connections[index];
    const routeStreetIds = [
      ...connection.streetIds,
      ...Object.values(connection.flowStreetIds).flat(),
    ];
    for (const streetId of new Set(routeStreetIds)) {
      const road = aggregated.get(streetId);
      if (!road) continue;
      road.routeCount += 1;
      if (!hasExactStreetData) {
        road.peopleCount += route.peopleCount;
        road.vehicleCount += route.vehicleCount;
        road.peopleEntered += route.peopleEntered;
        road.vehicleEntered += route.vehicleEntered;
        road.peopleExited += route.peopleExited;
        road.vehicleExited += route.vehicleExited;
      }
      if (!dominantLoads.has(streetId) || load > dominantLoads.get(streetId)!) {
        dominantLoads.set(streetId, load);
        road.sourceId = route.id;
        road.fromName = route.fromName;
        road.toName = route.toName;
      }
    }
  });

  // Walkways are part of the rendered street fabric even though legacy flow
  // snapshots only contain graph-edge counters. Use the local population bound
  // to each district as a low-intensity pedestrian/vehicle density fallback so
  // those visible gaps are represented in the heat layer as well.
  for (const [locationId, walkways] of walkwaysByLocation(bundle)) {
    if (!snapshot.location_counts[locationId]) continue;
    const localPeople = peopleId ? snapshot.location_counts[locationId]?.[peopleId] ?? 0 : 0;
    const localVehicles = vehicleId ? snapshot.location_counts[locationId]?.[vehicleId] ?? 0 : 0;
    for (const walkway of walkways) {
      const peopleCount = walkway.pedestrian_access ? Math.max(0, Math.round(localPeople / walkways.length)) : 0;
      const vehicleCount = walkway.vehicle_access && walkway.width >= 3
        ? Math.max(0, Math.round(localVehicles / walkways.length))
        : 0;
      if (peopleCount <= 0 && vehicleCount <= 0) continue;
      aggregated.set(walkway.id, {
        id: walkway.id,
        name: "建筑间步道",
        kind: "flow-road",
        path: walkway.path,
        width: walkway.width,
        routeCount: 0,
        peopleRatio: 0,
        vehicleRatio: 0,
        peopleCount,
        vehicleCount,
        peopleEntered: 0,
        vehicleEntered: 0,
        peopleExited: 0,
        vehicleExited: 0,
        peopleForward: Math.ceil(peopleCount / 2),
        peopleReverse: Math.floor(peopleCount / 2),
        vehicleForward: Math.ceil(vehicleCount / 2),
        vehicleReverse: Math.floor(vehicleCount / 2),
        roadKind: "walkway",
        pedestrianAccess: walkway.pedestrian_access,
        vehicleAccess: walkway.vehicle_access,
        localEstimate: true,
        sourceId: locationId,
      });
    }
  }

  const roads = [...aggregated.values()];
  const peopleMax = Math.max(1, ...roads.map((road) => road.peopleCount));
  const vehicleMax = Math.max(1, ...roads.map((road) => road.vehicleCount));
  for (const road of roads) {
    road.peopleRatio = road.peopleCount / peopleMax;
    road.vehicleRatio = road.vehicleCount / vehicleMax;
  }
  return roads;
}

function arrowPolygon(position: Coordinate, size: number, angle: number): Coordinate[] {
  const tip: Coordinate = [position[0] + Math.cos(angle) * size, position[1] + Math.sin(angle) * size];
  const wingAngle = 2.4;
  const wingScale = 0.65;
  const left: Coordinate = [
    position[0] + Math.cos(angle + wingAngle) * size * wingScale,
    position[1] + Math.sin(angle + wingAngle) * size * wingScale,
  ];
  const right: Coordinate = [
    position[0] + Math.cos(angle - wingAngle) * size * wingScale,
    position[1] + Math.sin(angle - wingAngle) * size * wingScale,
  ];
  return [tip, left, right];
}

function diamondPolygon(position: Coordinate, size: number): Coordinate[] {
  const [x, y] = position;
  return [
    [x, y + size],
    [x + size, y],
    [x, y - size],
    [x - size, y],
  ];
}

function rayEdgeIntersection(
  rayOrigin: Coordinate,
  rayDir: Coordinate,
  edgeStart: Coordinate,
  edgeEnd: Coordinate,
): number | null {
  const [x1, y1] = rayOrigin;
  const [x2, y2] = [rayOrigin[0] + rayDir[0], rayOrigin[1] + rayDir[1]];
  const [x3, y3] = edgeStart;
  const [x4, y4] = edgeEnd;
  const denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4);
  if (Math.abs(denom) < 0.0001) return null;
  const t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom;
  const u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / denom;
  if (t >= 0 && u >= 0 && u <= 1) return t;
  return null;
}

function buildingBoundaryIntersection(
  center: Coordinate,
  approachDir: Coordinate,
  buildings: { polygon: Coordinate[] }[],
): { point: Coordinate; distance: number } | null {
  let best: { point: Coordinate; distance: number } | null = null;
  for (const building of buildings) {
    const poly = building.polygon;
    for (let i = 0; i < poly.length; i += 1) {
      const start = poly[i];
      const end = poly[(i + 1) % poly.length];
      const t = rayEdgeIntersection(center, approachDir, start, end);
      if (t !== null && (best === null || t < best.distance)) {
        best = { point: [center[0] + approachDir[0] * t, center[1] + approachDir[1] * t], distance: t };
      }
    }
  }
  return best;
}

function stableUnit(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash = Math.imul(hash ^ value.charCodeAt(index), 16777619);
  }
  return (hash >>> 0) / 0xffffffff;
}

function selectDistributedMarkers(candidates: MarkerCandidate[], limit: number): FlowMarker[] {
  const ordered = [...candidates].sort(
    (left, right) => right.weight - left.weight || left.id.localeCompare(right.id),
  );
  const selected: MarkerCandidate[] = [];
  const groups = new Map<string, MarkerCandidate[]>();
  for (const candidate of ordered) {
    const key = candidate.coverageId ?? candidate.sourceId;
    const group = groups.get(key) ?? [];
    group.push(candidate);
    groups.set(key, group);
  }
  const queues = [...groups.values()].sort(
    (left, right) => right[0].weight - left[0].weight || left[0].id.localeCompare(right[0].id),
  );
  while (selected.length < limit) {
    let added = false;
    for (const queue of queues) {
      const candidate = queue.shift();
      if (!candidate) continue;
      selected.push(candidate);
      added = true;
      if (selected.length >= limit) break;
    }
    if (!added) break;
  }
  return selected.map(({ weight: _weight, coverageId: _coverageId, ...marker }) => marker);
}

function adaptiveMarkerLimit(
  candidates: MarkerCandidate[],
  minimum: number,
  maximum: number,
  extraPerCoverage: number,
): number {
  const coverageCount = new Set(
    candidates.map((candidate) => candidate.coverageId ?? candidate.sourceId),
  ).size;
  return Math.min(maximum, Math.max(minimum, Math.ceil(coverageCount * (1 + extraPerCoverage))));
}

function routeMarkerSampleCount(flow: "people" | "vehicle", count: number): number {
  if (flow === "vehicle") {
    return count >= 10 ? 4 : count >= 3 ? 3 : 2;
  }
  return count >= 80 ? 4 : count >= 20 ? 3 : count >= 5 ? 2 : 1;
}

function pathLength(path: Coordinate[]): number {
  return path.slice(1).reduce(
    (total, point, index) => total + Math.hypot(point[0] - path[index][0], point[1] - path[index][1]),
    0,
  );
}

function flowLocations(bundle: ScenarioBundle): Array<{ id: string; name: string; position: Coordinate }> {
  const cached = flowLocationCache.get(bundle);
  if (cached) return cached;
  const result = (bundle.simulation_package?.locations ?? bundle.config.locations).map((location) => ({
    id: location.id,
    name: location.name,
    position: location.position,
  }));
  flowLocationCache.set(bundle, result);
  return result;
}

export function assembleTownFlowData(
  bundle: ScenarioBundle,
  snapshot: SnapshotState,
  tickProgress = snapshot.tick,
  markerDensity = 1,
): TownFlowRenderData {
  const { people, vehicle } = flowIds(bundle);
  const connections = flowConnections(bundle);
  const roads: TownFlowRoad[] = [];
  const peopleCandidates: MarkerCandidate[] = [];
  const vehicleCandidates: MarkerCandidate[] = [];
  const localPeopleCandidates: MarkerCandidate[] = [];
  const localVehicleCandidates: MarkerCandidate[] = [];
  const locationEntries = flowLocations(bundle);
  const locationNames = new Map(locationEntries.map((location) => [location.id, location.name]));
  const streetsById = townStreetsById(bundle);
  for (const connection of connections) {
    const peopleFlow = people
      ? snapshotFlow(snapshot, connection.id, people)
      : { inTransit: 0, departed: 0, arrived: 0, streetInTransit: [] };
    const vehicleFlow = vehicle
      ? snapshotFlow(snapshot, connection.id, vehicle)
      : { inTransit: 0, departed: 0, arrived: 0, streetInTransit: [] };
    const peopleRatio = flowRatio(peopleFlow, connection.capacity[people ?? ""] ?? 0, connection.travelTime[people ?? ""] ?? 1);
    const vehicleRatio = flowRatio(vehicleFlow, connection.capacity[vehicle ?? ""] ?? 0, connection.travelTime[vehicle ?? ""] ?? 1);
    roads.push({
      id: connection.id,
      name: connection.id,
      kind: "flow-road",
      path: connection.path,
      routeCount: 1,
      fromName: locationNames.get(connection.fromLocationId) ?? connection.fromLocationId,
      toName: locationNames.get(connection.toLocationId) ?? connection.toLocationId,
      peopleRatio,
      vehicleRatio,
      peopleCount: peopleFlow.inTransit,
      vehicleCount: vehicleFlow.inTransit,
      peopleEntered: peopleFlow.departed,
      vehicleEntered: vehicleFlow.departed,
      peopleExited: peopleFlow.arrived,
      vehicleExited: vehicleFlow.arrived,
      peopleForward: 0,
      peopleReverse: 0,
      vehicleForward: 0,
      vehicleReverse: 0,
    });
    const addRouteMarkers = (
      flow: "people" | "vehicle",
      count: number,
      streetCounts: number[],
      travelTime: number,
      target: MarkerCandidate[],
    ) => {
      const fromName = locationNames.get(connection.fromLocationId) ?? connection.fromLocationId;
      const toName = locationNames.get(connection.toLocationId) ?? connection.toLocationId;
      const routeFlowId = flow === "vehicle" ? vehicle ?? "vehicle" : people ?? "pedestrian";
      const routeStreetIds = routeStreetIdsForFlow(connection, routeFlowId);
      const paths = bundle.town_skeleton
        ? routeStreetPaths(streetsById, connection, routeFlowId)
        : connection.path.length >= 2 ? [connection.path] : [];
      if (!paths.length || count <= 0) return;
      const exactStreetCounts = streetCounts.length === routeStreetIds.length && routeStreetIds.length > 0;
      const totalPathLength = Math.max(0.001, paths.reduce((total, path) => total + pathLength(path), 0));
      const counts = exactStreetCounts
        ? streetCounts
        : paths.map((path) => count * pathLength(path) / totalPathLength);
      const markerPaths = paths;
      for (const [streetIndex, streetCount] of counts.entries()) {
        if (streetCount <= 0) continue;
        const path = markerPaths[streetIndex];
        if (!path || path.length < 2) continue;
        const coverageId = exactStreetCounts
          ? routeStreetIds[streetIndex] ?? connection.id
          : connection.id;
        const sampleCount = routeMarkerSampleCount(flow, streetCount);
        const baseProgress = tickProgress / Math.max(1, travelTime)
          + stableUnit(`${connection.id}-${flow}-${streetIndex}`);
        for (let sampleIndex = 0; sampleIndex < sampleCount; sampleIndex += 1) {
          const id = `${connection.id}-${flow}-${streetIndex}-${sampleIndex}`;
          const point = pathPoint(path, (baseProgress + sampleIndex / sampleCount) % 1);
          target.push({
            id,
            name: `${flow === "vehicle" ? "车流" : "人流"}\n出发点：${fromName}\n终点：${toName}\n当前街段在途：${Math.round(streetCount).toLocaleString("zh-CN")}\n当前路线在途：${Math.round(count).toLocaleString("zh-CN")}`,
            kind: flow,
            position: point.position,
            path,
            flow,
            sourceId: connection.id,
            fromName,
            toName,
            weight: streetCount / sampleCount,
            coverageId,
            polygon: flow === "vehicle"
              ? arrowPolygon(point.position, 7, point.angle)
              : diamondPolygon(point.position, 4),
            angle: point.angle,
          });
        }
      }
    };
    if (people) {
      addRouteMarkers(
        "people",
        peopleFlow.inTransit,
        peopleFlow.streetInTransit,
        connection.travelTime[people] ?? 1,
        peopleCandidates,
      );
    }
    if (vehicle) {
      addRouteMarkers(
        "vehicle",
        vehicleFlow.inTransit,
        vehicleFlow.streetInTransit,
        connection.travelTime[vehicle] ?? 1,
        vehicleCandidates,
      );
    }
  }

  for (const [locationId, walkways] of walkwaysByLocation(bundle)) {
    const locationName = locationNames.get(locationId) ?? locationId;
    const localPeople = people ? snapshot.location_counts[locationId]?.[people] ?? 0 : 0;
    const localVehicles = vehicle ? snapshot.location_counts[locationId]?.[vehicle] ?? 0 : 0;
    for (const walkway of walkways) {
      const path = walkway.path.length > 1
        ? [...walkway.path, ...walkway.path.slice(0, -1).reverse()]
        : walkway.path;
      const duration = Math.max(6, pathLength(path) / 1.2);
      if (walkway.pedestrian_access && localPeople > 0) {
        const id = `${walkway.id}-local-people`;
        const point = pathPoint(path, tickProgress / duration + stableUnit(id));
        const count = Math.max(1, Math.round(localPeople / walkways.length));
        localPeopleCandidates.push({
          id,
          name: `街区内部人流\n区域：${locationName}\n步道宽度：${walkway.width.toFixed(1)} 米\n附近人数：${count.toLocaleString("zh-CN")}`,
          kind: "people",
          position: point.position,
          path,
          flow: "people",
          sourceId: locationId,
          fromName: locationName,
          toName: locationName,
          weight: localPeople / walkways.length,
          polygon: diamondPolygon(point.position, 3.5),
          angle: point.angle,
        });
      }
      if (walkway.vehicle_access && walkway.width >= 3 && localVehicles > 0) {
        const id = `${walkway.id}-local-vehicle`;
        const point = pathPoint(path, tickProgress / Math.max(6, pathLength(path) / 2.5) + stableUnit(id));
        const count = Math.max(1, Math.round(localVehicles / walkways.length));
        localVehicleCandidates.push({
          id,
          name: `街区内部车流\n区域：${locationName}\n道路宽度：${walkway.width.toFixed(1)} 米\n附近车辆：${count.toLocaleString("zh-CN")}`,
          kind: "vehicle",
          position: point.position,
          path,
          flow: "vehicle",
          sourceId: locationId,
          fromName: locationName,
          toName: locationName,
          weight: localVehicles / walkways.length,
          polygon: arrowPolygon(point.position, 5.5, point.angle),
          angle: point.angle,
        });
      }
    }
  }

  const physicalRoads = aggregatePhysicalRoads(bundle, roads, connections, snapshot, people, vehicle);
  const density = Math.min(2.5, Math.max(0.25, markerDensity));
  const selectedRoutePeople = selectDistributedMarkers(
    peopleCandidates,
    Math.round(adaptiveMarkerLimit(peopleCandidates, 72, 420, 0.75) * density),
  );
  const selectedRouteVehicles = selectDistributedMarkers(
    vehicleCandidates,
    Math.round(adaptiveMarkerLimit(vehicleCandidates, 36, 260, 0.5) * density),
  );
  const selectedLocalPeople = selectDistributedMarkers(
    localPeopleCandidates,
    Math.round(adaptiveMarkerLimit(localPeopleCandidates, 72, 180, 2) * density),
  );
  const selectedLocalVehicles = selectDistributedMarkers(
    localVehicleCandidates,
    Math.round(adaptiveMarkerLimit(localVehicleCandidates, 12, 48, 1) * density),
  );
  return {
    roads: physicalRoads,
    peopleMarkers: [...selectedRoutePeople, ...selectedLocalPeople],
    vehicleMarkers: [...selectedRouteVehicles, ...selectedLocalVehicles],
  };
}

function lerpHeatColor(ratio: number, low: number[], middle: number[], high: number[], alphaBase: number, alphaRange: number): Color {
  const left = ratio < 0.55 ? low : middle;
  const right = ratio < 0.55 ? middle : high;
  const progress = ratio < 0.55 ? ratio / 0.55 : (ratio - 0.55) / 0.45;
  return [
    Math.round(left[0] + (right[0] - left[0]) * progress),
    Math.round(left[1] + (right[1] - left[1]) * progress),
    Math.round(left[2] + (right[2] - left[2]) * progress),
    alphaBase + Math.round(alphaRange * ratio),
  ];
}

// People heat: warm gradient (green → amber → red)
function peopleHeatColor(ratio: number): Color {
  return lerpHeatColor(ratio, [85, 205, 183], [243, 196, 93], [255, 107, 94], 105, 140);
}

// Vehicle heat: cool gradient (sky blue → violet → magenta)
function vehicleHeatColor(ratio: number): Color {
  return lerpHeatColor(ratio, [87, 167, 255], [140, 110, 210], [220, 80, 160], 110, 130);
}

// People heat (pearl theme)
function peopleHeatPearl(ratio: number): Color {
  return lerpHeatColor(ratio, [74, 143, 176], [196, 152, 61], [184, 74, 58], 120, 125);
}

// Vehicle heat (pearl theme)
function vehicleHeatPearl(ratio: number): Color {
  return lerpHeatColor(ratio, [60, 120, 170], [128, 88, 168], [180, 60, 132], 125, 120);
}

function directionalRoadData(roads: TownFlowRoad[], flow: FlowAnalysisMode): DirectionalRoad[] {
  const counts = roads.map((road) => flow === "people"
    ? road.peopleForward + road.peopleReverse
    : road.vehicleForward + road.vehicleReverse);
  const maximum = Math.max(1, ...counts);
  return roads.flatMap((road): DirectionalRoad[] => {
    const forward = flow === "people" ? road.peopleForward : road.vehicleForward;
    const reverse = flow === "people" ? road.peopleReverse : road.vehicleReverse;
    const count = forward + reverse;
    if (count <= 0) return [];
    const direction = forward >= reverse ? "forward" : "reverse";
    return [{
      id: `${road.id}-${flow}-${direction}`,
      path: direction === "forward" ? road.path : [...road.path].reverse(),
      direction,
      count,
      ratio: count / maximum,
    }];
  });
}


function heatColorByTheme(ratio: number, flow: FlowAnalysisMode, theme: "pearl" | "night"): Color {
  if (theme === "pearl") {
    return flow === "vehicle" ? vehicleHeatPearl(ratio) : peopleHeatPearl(ratio);
  }
  return flow === "vehicle" ? vehicleHeatColor(ratio) : peopleHeatColor(ratio);
}

function heatRoadLayer(id: string, data: DirectionalRoad[], flow: FlowAnalysisMode, theme: "pearl" | "night", modelMatrix?: Float32Array): Layer {
  return new PathLayer<DirectionalRoad>({
    id,
    data,
    coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
    ...(modelMatrix ? { modelMatrix } : {}),
    widthUnits: "pixels",
    capRounded: true,
    jointRounded: true,
    getPath: (road) => road.path,
    getColor: (road) => heatColorByTheme(road.ratio, flow, theme),
    getWidth: (road) => 2 + Math.sqrt(road.ratio) * 7,
    pickable: false,
  });
}

export function createDynamicTownLayers(
  bundle: ScenarioBundle,
  snapshot: SnapshotState | null,
  selectedFeatureId: string | null,
  tickProgress?: number,
  visibility: TownLayerVisibility = allLayersVisible,
  analysisFlow: FlowAnalysisMode = "people",
  hoveredObject: TownFeature | null = null,
  modelMatrix?: Float32Array,
  theme: "pearl" | "night" = "night",
  markerDensity = 1,
): Layer[] {
  if (!snapshot) return [];
  const mc = theme === "pearl" ? pearlMapColors : mapColors;
  const data = assembleTownFlowData(bundle, snapshot, tickProgress ?? snapshot.tick, markerDensity);
  const directions = directionalRoadData(data.roads, analysisFlow);
  const common = { coordinateSystem: COORDINATE_SYSTEM.CARTESIAN, ...(modelMatrix ? { modelMatrix } : {}) } as const;
  const streetsById = townStreetsById(bundle);
  const { people: peopleFlowId, vehicle: vehicleFlowId } = flowIds(bundle);

  const hoveredFlowMarker =
    hoveredObject && (hoveredObject.kind === "people" || hoveredObject.kind === "vehicle")
      ? hoveredObject as FlowMarker
      : null;
  let hoverRoutePath: Coordinate[] | null = null;
  let hoverStartPoint: Coordinate | null = null;
  let hoverEndPoint: Coordinate | null = null;
  let hoverEndAngle = 0;
  if (hoveredFlowMarker) {
    const sourceId = (hoveredFlowMarker as FlowMarker & { sourceId?: string }).sourceId;
    let toLocationId: string | null = null;
    if (sourceId) {
      const conn = flowConnections(bundle).find((c) => c.id === sourceId);
      if (conn) {
        const hoverFlowId = hoveredFlowMarker.flow === "vehicle" ? vehicleFlowId : peopleFlowId;
        const streetPaths = hoverFlowId ? routeStreetPaths(streetsById, conn, hoverFlowId) : [];
        hoverRoutePath = streetPaths.length ? joinRoutePaths(streetPaths) : null;
        toLocationId = conn.toLocationId;
      }
    }
    if (!hoverRoutePath) {
      const markerPath = (hoveredFlowMarker as FlowMarker & { path?: Coordinate[] }).path;
      hoverRoutePath = markerPath ? [...markerPath] : null;
    }
    if (hoverRoutePath && hoverRoutePath.length >= 2) {
      hoverStartPoint = hoverRoutePath[0];
      const rawEnd = hoverRoutePath[hoverRoutePath.length - 1];
      const secondLast = hoverRoutePath[hoverRoutePath.length - 2];
      const dx = rawEnd[0] - secondLast[0];
      const dy = rawEnd[1] - secondLast[1];
      const approachLen = Math.hypot(dx, dy);
      const approachDir: Coordinate = dx === 0 && dy === 0 ? [0, -1] : [dx / approachLen, dy / approachLen];
      hoverEndAngle = Math.atan2(dy, dx);

      // Find building boundary intersection for the destination
      let edgePoint: Coordinate = rawEnd;
      if (toLocationId) {
        const bindings = bundle.simulation_package?.bindings;
        const townSkeleton = bundle.town_skeleton;
        if (bindings && townSkeleton) {
          const featureIds = bindings.location_feature_ids[toLocationId] ?? [];
          const targetBuildings = townSkeleton.buildings.filter((b) => featureIds.includes(b.id));
          if (targetBuildings.length > 0) {
            // Shoot ray from center opposite to approach direction (backwards)
            const backDir: Coordinate = [-approachDir[0], -approachDir[1]];
            const hit = buildingBoundaryIntersection(rawEnd, backDir, targetBuildings);
            if (hit) {
              edgePoint = hit.point;
              // Trim the last path point to stop at the building edge
              hoverRoutePath = [
                ...hoverRoutePath.slice(0, -1),
                edgePoint,
              ];
            }
          }
        }
      }
      hoverEndPoint = edgePoint;
    }
  }

  const hoverRouteColor: Color =
    hoveredFlowMarker?.flow === "vehicle"
      ? [mc.vehicle[0], mc.vehicle[1], mc.vehicle[2], 140] as Color
      : [mc.people[0], mc.people[1], mc.people[2], 160] as Color;

  const dashedExtension = new PathStyleExtension({ dash: true });

  return [
    ...(visibility.roads || visibility.people || visibility.vehicles || visibility.heat ? [new PathLayer<TownFlowRoad>({
      id: "flow-road-hit-target",
      data: data.roads,
      ...common,
      pickable: true,
      widthUnits: "pixels",
      capRounded: true,
      jointRounded: true,
      getPath: (road) => road.path,
      getColor: [0, 0, 0, 0],
      getWidth: 14,
    })] : []),
    ...(visibility.heat ? [heatRoadLayer(`${analysisFlow}-direction-heat`, directions, analysisFlow, theme, modelMatrix)] : []),
    ...(visibility.people ? [new ScatterplotLayer<FlowMarker>({
      id: "people-flow-markers",
      data: data.peopleMarkers,
      ...common,
      pickable: true,
      radiusUnits: "pixels" as const,
      getPosition: (marker) => marker.position,
      getRadius: 3,
      getFillColor: (marker) => marker.id.startsWith(`${selectedFeatureId ?? "!"}-`) ? mc.selection : mc.people,
      getLineColor: [16, 20, 22, 200],
      getLineWidth: 1,
      stroked: true,
    })] : []),
    ...(visibility.vehicles ? [new PolygonLayer<FlowMarker>({
      id: "vehicle-flow-markers",
      data: data.vehicleMarkers,
      ...common,
      pickable: true,
      stroked: true,
      filled: true,
      getPolygon: (marker) => marker.polygon,
      getFillColor: (marker) => marker.id.startsWith(`${selectedFeatureId ?? "!"}-`) ? mc.selection : mc.vehicle,
      getLineColor: [16, 20, 22, 245],
      getLineWidth: 1,
    })] : []),
    ...(hoverRoutePath ? [new PathLayer({
      id: "hover-route-line",
      data: [{ path: hoverRoutePath }],
      coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
      ...(modelMatrix ? { modelMatrix } : {}),
      widthUnits: "pixels" as const,
      capRounded: true,
      jointRounded: true,
      getPath: (d: unknown) => (d as { path: Coordinate[] }).path,
      getColor: hoverRouteColor,
      getWidth: 2,
      // PathStyleExtension props
      getDashArray: [5, 4],
      dashJustified: true,
      dashGapPickable: false,
      pickable: false,
      extensions: [dashedExtension],
    })] : []),
    ...(hoverStartPoint ? [new ScatterplotLayer<{ position: Coordinate }>({
      id: "hover-route-start",
      data: [{ position: hoverStartPoint }],
      coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
      ...(modelMatrix ? { modelMatrix } : {}),
      radiusUnits: "pixels",
      getPosition: (d: unknown) => (d as { position: Coordinate }).position,
      getRadius: 3,
      getFillColor: hoverRouteColor,
      getLineColor: [16, 20, 22, 200],
      getLineWidth: 1,
      stroked: true,
      pickable: false,
    })] : []),
    ...(hoverEndPoint ? [new PolygonLayer<{ polygon: Coordinate[] }>({
      id: "hover-route-end",
      data: [{ polygon: arrowPolygon(hoverEndPoint, 3, hoverEndAngle) }],
      coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
      ...(modelMatrix ? { modelMatrix } : {}),
      getPolygon: (d: unknown) => (d as { polygon: Coordinate[] }).polygon,
      getFillColor: hoverRouteColor,
      getLineColor: [16, 20, 22, 200],
      getLineWidth: 1,
      stroked: true,
      filled: true,
      pickable: false,
    })] : []),
  ];
}
