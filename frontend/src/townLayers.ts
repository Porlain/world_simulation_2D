import { COORDINATE_SYSTEM, type Color, type Layer } from "@deck.gl/core";
import { HeatmapLayer } from "@deck.gl/aggregation-layers";
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
  walls: TownFeature[];
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
  peopleRatio: number;
  vehicleRatio: number;
  peopleCount: number;
  vehicleCount: number;
  peopleDeparted: number;
  vehicleDeparted: number;
}

interface FlowPoint {
  position: Coordinate;
  weight: number;
}

interface FlowMarker extends TownFeature {
  position: Coordinate;
  flow: "people" | "vehicle";
  sourceId: string;
  polygon?: Coordinate[];
}

export interface TownFlowRenderData {
  peopleHeat: FlowPoint[];
  vehicleHeat: FlowPoint[];
  roads: TownFlowRoad[];
  peopleMarkers: FlowMarker[];
  vehicleMarkers: FlowMarker[];
}

const districtColors: Record<DistrictKind, Color> = {
  residential: [111, 112, 111, 18],
  market: [167, 145, 119, 28],
  industrial: [148, 117, 96, 26],
  storage: [127, 133, 119, 24],
  religious: [133, 126, 139, 24],
  civic: [160, 139, 117, 30],
  military: [125, 103, 96, 26],
  stable: [151, 135, 104, 24],
};

const buildingColors: Record<BuildingKind, Color> = {
  residential: [104, 117, 138, 236],
  market: [111, 119, 132, 238],
  workshop: [103, 112, 128, 238],
  storage: [96, 109, 126, 238],
  religious: [115, 119, 137, 242],
  administrative: [94, 108, 129, 244],
  military: [89, 101, 116, 242],
  stable: [108, 115, 129, 238],
};

const landmarkColors: Record<string, Color> = {
  gate: [76, 72, 68, 245],
  plaza: [219, 205, 178, 246],
  market: [170, 125, 105, 245],
  workshop: [154, 116, 92, 245],
  storage: [132, 126, 106, 245],
  religious: [143, 126, 143, 245],
  administrative: [107, 111, 124, 245],
  military: [83, 82, 80, 245],
  stable: [155, 136, 95, 245],
  residential: [109, 119, 134, 245],
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

function wallSegments(boundary: Coordinate[], landmarks: TownLandmark[]): TownFeature[] {
  const gates = landmarks.filter((landmark) => landmark.kind === "gate").map((landmark) => landmark.position);
  const result: TownFeature[] = [];
  for (let index = 0; index < boundary.length; index += 1) {
    const start = boundary[index];
    const end = boundary[(index + 1) % boundary.length];
    const dx = end[0] - start[0];
    const dy = end[1] - start[1];
    const length = Math.hypot(dx, dy);
    const gate = gates.find((point) => {
      const cross = Math.abs(dx * (point[1] - start[1]) - dy * (point[0] - start[0]));
      const dot = (point[0] - start[0]) * dx + (point[1] - start[1]) * dy;
      return cross <= length * 0.01 && dot >= 0 && dot <= length * length;
    });
    if (!gate || length <= 8) {
      result.push({ id: `wall-${index}`, name: "Town Wall", kind: "wall", path: [start, end] });
      continue;
    }
    const ux = dx / length;
    const uy = dy / length;
    result.push(
      {
        id: `wall-${index}-a`,
        name: "Town Wall",
        kind: "wall",
        path: [start, [gate[0] - ux * 4, gate[1] - uy * 4]],
      },
      {
        id: `wall-${index}-b`,
        name: "Town Wall",
        kind: "wall",
        path: [[gate[0] + ux * 4, gate[1] + uy * 4], end],
      },
    );
  }
  return result;
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
    sourceId: feature.id,
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
    case "plaza":
      return [
        part("square", rectangle(position, size * 1.35, size * 1.35)),
        part("fountain", circle(position, size * 0.27, 12)),
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
    return {
      bounds: boundsFromBundle(bundle),
      districts: [],
      buildings: [],
      walls: [],
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
  return {
    bounds: skeleton.bounds,
    districts: skeleton.districts.map((district) => ({
      id: district.id,
      name: district.kind,
      kind: district.kind,
      polygon: district.polygon,
    })),
    buildings: skeleton.buildings.map((building) => ({
      id: building.id,
      name: building.kind,
      kind: building.kind,
      polygon: building.polygon,
    })),
    streets: skeleton.streets.map((street) => ({
      id: street.id,
      name: street.kind,
      kind: street.kind,
      path: street.path,
      width: street.width,
    })),
    walls: wallSegments(skeleton.boundary, skeleton.landmarks),
    landmarks: skeleton.landmarks.map((landmark) => ({
      id: landmark.id,
      name: landmark.name,
      kind: landmark.kind,
      position: landmark.position,
    })),
  };
}

export function createStaticTownLayers(
  data: TownRenderData,
  selectedFeatureId: string | null,
  visibility: TownLayerVisibility = allLayersVisible,
): Layer[] {
  const width = Math.max(1, data.bounds[2] - data.bounds[0]);
  const height = Math.max(1, data.bounds[3] - data.bounds[1]);
  const landmarkSize = Math.max(7, Math.min(18, Math.hypot(width, height) * 0.014));
  const landmarkPolygons = data.landmarks.flatMap((feature) => landmarkMotif(feature, landmarkSize));
  const wallTowers = Array.from(new Map(data.walls.flatMap((wall) => wall.path ?? []).map((position, index) => [
    `${position[0]}:${position[1]}`,
    { id: `wall-tower-${index}`, name: "Wall Tower", kind: "wall", position },
  ])).values());
  const common = { coordinateSystem: COORDINATE_SYSTEM.CARTESIAN } as const;
  return [
    new PolygonLayer<TownFeature>({
      id: "district-fill",
      data: data.districts,
      ...common,
      pickable: true,
      stroked: true,
      filled: true,
      lineWidthUnits: "pixels",
      getPolygon: (feature) => feature.polygon!,
      getFillColor: (feature) => districtColors[feature.kind as DistrictKind] ?? [111, 112, 111, 18],
      getLineColor: (feature) => feature.id === selectedFeatureId ? [181, 106, 63, 220] : [111, 105, 96, 35],
      getLineWidth: (feature) => feature.id === selectedFeatureId ? 2 : 0.5,
    }),
    ...(visibility.buildings ? [new PolygonLayer<TownFeature>({
      id: "building-fill",
      data: data.buildings,
      ...common,
      pickable: true,
      stroked: true,
      filled: true,
      lineWidthUnits: "pixels",
      getPolygon: (feature) => feature.polygon!,
      getFillColor: (feature) => buildingColors[feature.kind as BuildingKind] ?? buildingColors.residential,
      getLineColor: (feature) => feature.id === selectedFeatureId ? [181, 106, 63, 255] : [77, 83, 92, 230],
      getLineWidth: (feature) => feature.id === selectedFeatureId ? 2 : 0.65,
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
      getColor: (feature) => feature.id === selectedFeatureId ? [181, 106, 63, 190] : [163, 160, 151, 210],
      getWidth: (feature) => feature.kind === "primary" ? 8 : feature.kind === "ring" ? 5 : 3,
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
      getColor: (feature) => feature.id === selectedFeatureId ? [181, 106, 63, 255] : [237, 233, 222, 245],
      getWidth: (feature) => feature.kind === "primary" ? 6 : feature.kind === "ring" ? 3.5 : 2,
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
      getColor: (feature) => feature.id === selectedFeatureId ? [181, 106, 63, 255] : [61, 61, 59, 245],
      getWidth: (feature) => feature.id === selectedFeatureId ? 5.5 : 4,
    }),
    new ScatterplotLayer<TownFeature>({
      id: "wall-towers",
      data: wallTowers,
      ...common,
      pickable: false,
      radiusUnits: "pixels",
      getPosition: (feature) => feature.position!,
      getRadius: 3,
      getFillColor: [61, 61, 59, 245],
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
      getFillColor: (feature) => landmarkColors[feature.kind] ?? landmarkColors.residential,
      getLineColor: (feature) => feature.sourceId === selectedFeatureId ? [181, 106, 63, 255] : [63, 61, 56, 225],
      getLineWidth: (feature) => feature.sourceId === selectedFeatureId ? 2.5 : 1,
    }),
    new TextLayer<TownFeature>({
      id: "landmark-labels",
      data: data.landmarks,
      ...common,
      pickable: false,
      billboard: true,
      characterSet: "auto",
      fontFamily: "Georgia",
      fontWeight: 500,
      getText: (feature) => feature.name,
      getPosition: (feature) => feature.position!,
      getColor: [152, 89, 77, 238],
      getSize: 13,
      getPixelOffset: [0, -13],
      getTextAnchor: "middle",
      getAlignmentBaseline: "bottom",
      background: false,
    })] : []),
  ];
}

type FlowConnection = {
  id: string;
  path: Coordinate[];
  capacity: Record<string, number>;
  travelTime: Record<string, number>;
};

function flowConnections(bundle: ScenarioBundle): FlowConnection[] {
  if (bundle.simulation_package) {
    return bundle.simulation_package.connections.map((connection) => ({
      id: connection.id,
      path: connection.path,
      capacity: connection.capacity_per_tick,
      travelTime: connection.travel_time_ticks,
    }));
  }
  return bundle.config.connections.map((connection) => ({
    id: connection.id,
    path: connection.path,
    capacity: connection.capacity_per_tick,
    travelTime: { [bundle.config.flow_types[0]?.id ?? "citizen"]: connection.travel_time_ticks },
  }));
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

function snapshotFlow(snapshot: SnapshotState, connectionId: string, flowId: string): { inTransit: number; departed: number } {
  if (snapshot.schema_version === 2) {
    const value = (snapshot as FlowSnapshot).connections[connectionId]?.[flowId];
    return { inTransit: value?.in_transit ?? 0, departed: value?.departed ?? 0 };
  }
  const value = (snapshot as LegacySnapshotState).connection_activity[connectionId]?.[flowId];
  const buckets = (snapshot as LegacySnapshotState).transit_buckets[connectionId]?.[flowId] ?? [];
  return { inTransit: buckets.reduce((sum, count) => sum + count, 0), departed: value?.departed ?? 0 };
}

function flowLocationCount(snapshot: SnapshotState, locationId: string, flowId: string): number {
  return snapshot.location_counts[locationId]?.[flowId] ?? 0;
}

function markerPolygon(position: Coordinate, size: number, angle: number): Coordinate[] {
  return [0, 1, 2, 3].map((index) => {
    const theta = angle + Math.PI / 4 + index * Math.PI / 2;
    return [position[0] + Math.cos(theta) * size, position[1] + Math.sin(theta) * size];
  });
}

function flowLocations(bundle: ScenarioBundle): Array<{ id: string; position: Coordinate }> {
  return (bundle.simulation_package?.locations ?? bundle.config.locations).map((location) => ({
    id: location.id,
    position: location.position,
  }));
}

export function assembleTownFlowData(
  bundle: ScenarioBundle,
  snapshot: SnapshotState,
  tickProgress = snapshot.tick,
): TownFlowRenderData {
  const { people, vehicle } = flowIds(bundle);
  const connections = flowConnections(bundle);
  const peopleHeat: FlowPoint[] = [];
  const vehicleHeat: FlowPoint[] = [];
  const roads: TownFlowRoad[] = [];
  const peopleMarkers: FlowMarker[] = [];
  const vehicleMarkers: FlowMarker[] = [];
  const locationEntries = flowLocations(bundle);
  const peopleLocationMax = Math.max(1, ...locationEntries.map((location) => people ? flowLocationCount(snapshot, location.id, people) : 0));
  const vehicleLocationMax = Math.max(1, ...locationEntries.map((location) => vehicle ? flowLocationCount(snapshot, location.id, vehicle) : 0));

  for (const location of locationEntries) {
    if (people) peopleHeat.push({ position: location.position, weight: flowLocationCount(snapshot, location.id, people) / peopleLocationMax });
    if (vehicle) vehicleHeat.push({ position: location.position, weight: flowLocationCount(snapshot, location.id, vehicle) / vehicleLocationMax });
  }

  for (const connection of connections) {
    const peopleFlow = people ? snapshotFlow(snapshot, connection.id, people) : { inTransit: 0, departed: 0 };
    const vehicleFlow = vehicle ? snapshotFlow(snapshot, connection.id, vehicle) : { inTransit: 0, departed: 0 };
    const peopleCapacity = Math.max(1, (connection.capacity[people ?? ""] ?? 0) * (connection.travelTime[people ?? ""] ?? 1));
    const vehicleCapacity = Math.max(1, (connection.capacity[vehicle ?? ""] ?? 0) * (connection.travelTime[vehicle ?? ""] ?? 1));
    const peopleRatio = Math.min(1, peopleFlow.inTransit / peopleCapacity);
    const vehicleRatio = Math.min(1, vehicleFlow.inTransit / vehicleCapacity);
    roads.push({
      id: connection.id,
      name: connection.id,
      kind: "flow-road",
      path: connection.path,
      peopleRatio,
      vehicleRatio,
      peopleCount: peopleFlow.inTransit,
      vehicleCount: vehicleFlow.inTransit,
      peopleDeparted: peopleFlow.departed,
      vehicleDeparted: vehicleFlow.departed,
    });

    for (let sample = 0; sample < 7; sample += 1) {
      const point = pathPoint(connection.path, sample / 6);
      if (peopleRatio > 0) peopleHeat.push({ position: point.position, weight: peopleRatio });
      if (vehicleRatio > 0) vehicleHeat.push({ position: point.position, weight: vehicleRatio });
    }

    const addMarkers = (flow: "people" | "vehicle", count: number, travelTime: number, target: FlowMarker[]) => {
      const markerCount = Math.min(flow === "vehicle" ? 18 : 30, Math.max(0, Math.ceil(count / (flow === "vehicle" ? 2 : 18))));
      for (let index = 0; index < markerCount; index += 1) {
        const progress = (tickProgress / Math.max(1, travelTime) + index / markerCount) % 1;
        const point = pathPoint(connection.path, progress);
        target.push({
          id: `${connection.id}-${flow}-${index}`,
          name: flow === "vehicle" ? `车流 · ${Math.round(count)} 辆在途` : `人流 · ${Math.round(count)} 人在途`,
          kind: flow,
          position: point.position,
          path: connection.path,
          flow,
          sourceId: connection.id,
          polygon: flow === "vehicle" ? markerPolygon(point.position, 3.8, point.angle) : undefined,
        });
      }
    };
    if (people) addMarkers("people", peopleFlow.inTransit, connection.travelTime[people] ?? 1, peopleMarkers);
    if (vehicle) addMarkers("vehicle", vehicleFlow.inTransit, connection.travelTime[vehicle] ?? 1, vehicleMarkers);
  }
  return { peopleHeat, vehicleHeat, roads, peopleMarkers, vehicleMarkers };
}

function heatLayer(
  id: string,
  data: FlowPoint[],
  colorRange: Color[],
): Layer {
  return new HeatmapLayer<FlowPoint>({
    id,
    data,
    coordinateSystem: COORDINATE_SYSTEM.CARTESIAN,
    getPosition: (point) => point.position,
    getWeight: (point) => point.weight,
    radiusPixels: 26,
    intensity: 1.25,
    threshold: 0.035,
    colorDomain: [0, 4],
    colorRange,
    pickable: false,
  });
}

export function createDynamicTownLayers(
  bundle: ScenarioBundle,
  snapshot: SnapshotState | null,
  selectedFeatureId: string | null,
  tickProgress?: number,
  visibility: TownLayerVisibility = allLayersVisible,
): Layer[] {
  if (!snapshot) return [];
  const data = assembleTownFlowData(bundle, snapshot, tickProgress ?? snapshot.tick);
  const common = { coordinateSystem: COORDINATE_SYSTEM.CARTESIAN } as const;
  return [
    ...(visibility.roads || visibility.people || visibility.vehicles ? [new PathLayer<TownFlowRoad>({
      id: "flow-road-hit-target",
      data: data.roads,
      ...common,
      pickable: true,
      widthUnits: "pixels",
      capRounded: true,
      jointRounded: true,
      getPath: (road) => road.path,
      getColor: [0, 0, 0, 0],
      getWidth: 12,
    })] : []),
    ...(visibility.heat && data.peopleHeat.length ? [heatLayer("people-heat", data.peopleHeat, [
      [33, 132, 153, 0],
      [36, 196, 187, 72],
      [247, 192, 70, 170],
      [225, 75, 65, 220],
    ])] : []),
    ...(visibility.heat && data.vehicleHeat.length ? [heatLayer("vehicle-heat", data.vehicleHeat, [
      [31, 99, 173, 0],
      [42, 165, 221, 78],
      [126, 111, 224, 168],
      [231, 72, 113, 220],
    ])] : []),
    ...(visibility.people ? [new PathLayer<TownFlowRoad>({
      id: "people-flow-roads",
      data: data.roads,
      ...common,
      widthUnits: "pixels",
      capRounded: true,
      jointRounded: true,
      getPath: (road) => road.path!,
      pickable: false,
      getColor: (road) => [47 + Math.round(145 * road.peopleRatio), 117 - Math.round(48 * road.peopleRatio), 111 - Math.round(42 * road.peopleRatio), road.peopleRatio > 0 ? 105 + Math.round(110 * road.peopleRatio) : 0],
      getWidth: (road) => 2 + road.peopleRatio * 5,
    })] : []),
    ...(visibility.vehicles ? [new PathLayer<TownFlowRoad>({
      id: "vehicle-flow-roads",
      data: data.roads,
      ...common,
      widthUnits: "pixels",
      capRounded: true,
      jointRounded: true,
      getPath: (road) => road.path!,
      pickable: false,
      getColor: (road) => [73 + Math.round(155 * road.vehicleRatio), 124 - Math.round(65 * road.vehicleRatio), 166 - Math.round(72 * road.vehicleRatio), road.vehicleRatio > 0 ? 100 + Math.round(120 * road.vehicleRatio) : 0],
      getWidth: (road) => 1.5 + road.vehicleRatio * 4,
    })] : []),
    ...(visibility.people ? [new ScatterplotLayer<FlowMarker>({
      id: "people-flow-markers",
      data: data.peopleMarkers,
      ...common,
      pickable: true,
      radiusUnits: "pixels",
      stroked: true,
      getPosition: (marker) => marker.position,
      getRadius: () => 3.2,
      getFillColor: (marker) => marker.id.startsWith(`${selectedFeatureId ?? "!"}-`) ? [181, 106, 63, 255] : [47, 117, 111, 235],
      getLineColor: [237, 233, 222, 240],
      getLineWidth: 1,
    })] : []),
    ...(visibility.vehicles ? [new PolygonLayer<FlowMarker>({
      id: "vehicle-flow-markers",
      data: data.vehicleMarkers,
      ...common,
      pickable: true,
      stroked: true,
      filled: true,
      getPolygon: (marker) => marker.polygon!,
      getFillColor: (marker) => marker.id.startsWith(`${selectedFeatureId ?? "!"}-`) ? [181, 106, 63, 255] : [73, 124, 166, 245],
      getLineColor: [237, 233, 222, 240],
      getLineWidth: 1,
    })] : []),
  ];
}
