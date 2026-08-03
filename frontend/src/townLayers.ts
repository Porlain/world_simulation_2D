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

interface FlowRoad extends TownFeature {
  path: Coordinate[];
  peopleRatio: number;
  vehicleRatio: number;
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
  roads: FlowRoad[];
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

function landmarkPolygon(feature: TownFeature, size: number): Coordinate[] {
  const position = feature.position ?? [0, 0];
  const sides = feature.kind === "military" ? 3 : feature.kind === "market" || feature.kind === "stable" ? 6 : feature.kind === "administrative" ? 8 : 4;
  const rotation = feature.kind === "plaza" || feature.kind === "religious" ? Math.PI / 4 : -Math.PI / 2;
  return Array.from({ length: sides }, (_, index) => {
    const angle = rotation + (index * Math.PI * 2) / sides;
    const radius = feature.kind === "gate" ? size * 0.72 : size;
    return [position[0] + Math.cos(angle) * radius, position[1] + Math.sin(angle) * radius];
  });
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

export function createStaticTownLayers(data: TownRenderData, selectedFeatureId: string | null): Layer[] {
  const width = Math.max(1, data.bounds[2] - data.bounds[0]);
  const height = Math.max(1, data.bounds[3] - data.bounds[1]);
  const landmarkSize = Math.max(5, Math.min(14, Math.hypot(width, height) * 0.012));
  const landmarkPolygons = data.landmarks.map((feature) => ({
    ...feature,
    polygon: landmarkPolygon(feature, landmarkSize),
  }));
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
    new PolygonLayer<TownFeature>({
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
    }),
    new PathLayer<TownFeature>({
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
    }),
    new PathLayer<TownFeature>({
      id: "boundary-wall",
      data: data.walls,
      ...common,
      pickable: true,
      widthUnits: "pixels",
      capRounded: false,
      jointRounded: false,
      getPath: (feature) => feature.path!,
      getColor: (feature) => feature.id === selectedFeatureId ? [181, 106, 63, 255] : [61, 61, 59, 245],
      getWidth: (feature) => feature.id === selectedFeatureId ? 4.5 : 3,
    }),
    new PolygonLayer<TownFeature>({
      id: "landmark-symbols",
      data: landmarkPolygons,
      ...common,
      pickable: true,
      stroked: true,
      filled: true,
      lineWidthUnits: "pixels",
      getPolygon: (feature) => feature.polygon!,
      getFillColor: (feature) => landmarkColors[feature.kind] ?? landmarkColors.residential,
      getLineColor: (feature) => feature.id === selectedFeatureId ? [181, 106, 63, 255] : [63, 61, 56, 225],
      getLineWidth: (feature) => feature.id === selectedFeatureId ? 2.5 : 1,
    }),
    new TextLayer<TownFeature>({
      id: "landmark-labels",
      data: data.landmarks.filter((feature) => feature.kind === "gate" || feature.kind === "plaza" || feature.id === selectedFeatureId),
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
    }),
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
  const roads: FlowRoad[] = [];
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
          name: flow === "vehicle" ? "车流" : "人流",
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
): Layer[] {
  if (!snapshot) return [];
  const data = assembleTownFlowData(bundle, snapshot, tickProgress ?? snapshot.tick);
  const common = { coordinateSystem: COORDINATE_SYSTEM.CARTESIAN } as const;
  return [
    heatLayer("people-heat", data.peopleHeat, [
      [33, 132, 153, 0],
      [36, 196, 187, 72],
      [247, 192, 70, 170],
      [225, 75, 65, 220],
    ]),
    heatLayer("vehicle-heat", data.vehicleHeat, [
      [31, 99, 173, 0],
      [42, 165, 221, 78],
      [126, 111, 224, 168],
      [231, 72, 113, 220],
    ]),
    new PathLayer<FlowRoad>({
      id: "people-flow-roads",
      data: data.roads.filter((road) => road.peopleRatio > 0),
      ...common,
      pickable: true,
      widthUnits: "pixels",
      capRounded: true,
      jointRounded: true,
      getPath: (road) => road.path!,
      getColor: (road) => [76 + Math.round(170 * road.peopleRatio), 220 - Math.round(130 * road.peopleRatio), 214 - Math.round(110 * road.peopleRatio), 150 + Math.round(90 * road.peopleRatio)],
      getWidth: (road) => 2 + road.peopleRatio * 5,
    }),
    new PathLayer<FlowRoad>({
      id: "vehicle-flow-roads",
      data: data.roads.filter((road) => road.vehicleRatio > 0),
      ...common,
      pickable: true,
      widthUnits: "pixels",
      capRounded: true,
      jointRounded: true,
      getPath: (road) => road.path!,
      getColor: (road) => [75 + Math.round(160 * road.vehicleRatio), 139 - Math.round(65 * road.vehicleRatio), 236 - Math.round(80 * road.vehicleRatio), 120 + Math.round(100 * road.vehicleRatio)],
      getWidth: (road) => 1.5 + road.vehicleRatio * 4,
    }),
    new ScatterplotLayer<FlowMarker>({
      id: "people-flow-markers",
      data: data.peopleMarkers,
      ...common,
      pickable: true,
      radiusUnits: "pixels",
      stroked: true,
      getPosition: (marker) => marker.position,
      getRadius: () => 3.2,
      getFillColor: (marker) => marker.id.startsWith(`${selectedFeatureId ?? "!"}-`) ? [255, 231, 135, 255] : [151, 245, 224, 235],
      getLineColor: [10, 54, 62, 230],
      getLineWidth: 1,
    }),
    new PolygonLayer<FlowMarker>({
      id: "vehicle-flow-markers",
      data: data.vehicleMarkers,
      ...common,
      pickable: true,
      stroked: true,
      filled: true,
      getPolygon: (marker) => marker.polygon!,
      getFillColor: (marker) => marker.id.startsWith(`${selectedFeatureId ?? "!"}-`) ? [255, 231, 135, 255] : [115, 178, 247, 245],
      getLineColor: [13, 39, 79, 245],
      getLineWidth: 1,
    }),
  ];
}
