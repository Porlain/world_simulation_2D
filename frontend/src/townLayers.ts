import { COORDINATE_SYSTEM, type Color, type Layer } from "@deck.gl/core";
import { PathLayer, PolygonLayer, TextLayer } from "@deck.gl/layers";
import type {
  BuildingKind,
  Coordinate,
  DistrictKind,
  ScenarioBundle,
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

const districtColors: Record<DistrictKind, Color> = {
  residential: [18, 91, 112, 54],
  market: [15, 159, 173, 66],
  industrial: [156, 112, 51, 62],
  storage: [55, 128, 126, 62],
  religious: [91, 112, 176, 62],
  civic: [0, 182, 201, 70],
  military: [190, 82, 68, 64],
  stable: [145, 125, 68, 62],
};

const buildingColors: Record<BuildingKind, Color> = {
  residential: [34, 144, 171, 116],
  market: [24, 204, 197, 168],
  workshop: [225, 158, 65, 168],
  storage: [73, 167, 153, 156],
  religious: [121, 143, 216, 176],
  administrative: [26, 203, 222, 190],
  military: [231, 95, 79, 178],
  stable: [185, 156, 74, 166],
};

const landmarkColors: Record<string, Color> = {
  gate: [101, 225, 235, 235],
  plaza: [238, 194, 83, 235],
  market: [34, 232, 213, 235],
  workshop: [244, 164, 71, 235],
  storage: [98, 194, 173, 235],
  religious: [152, 164, 242, 235],
  administrative: [65, 218, 238, 235],
  military: [245, 105, 86, 235],
  stable: [211, 178, 84, 235],
  residential: [91, 186, 208, 235],
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
      getFillColor: (feature) => districtColors[feature.kind as DistrictKind] ?? [20, 94, 112, 48],
      getLineColor: (feature) => feature.id === selectedFeatureId ? [255, 199, 78, 245] : [52, 154, 174, 86],
      getLineWidth: (feature) => feature.id === selectedFeatureId ? 2 : 1,
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
      getColor: [83, 220, 232, 225],
      getWidth: (feature) => feature.id === selectedFeatureId ? 6 : 3,
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
      getColor: (feature) => feature.id === selectedFeatureId ? [255, 193, 69, 250] : feature.kind === "primary" ? [76, 190, 207, 205] : [57, 129, 150, 165],
      getWidth: (feature) => feature.id === selectedFeatureId ? 7 : feature.kind === "primary" ? 4 : feature.kind === "ring" ? 3 : 2,
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
      getLineColor: (feature) => feature.id === selectedFeatureId ? [255, 202, 80, 255] : [91, 207, 221, 126],
      getLineWidth: (feature) => feature.id === selectedFeatureId ? 2.5 : 0.7,
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
      getLineColor: (feature) => feature.id === selectedFeatureId ? [255, 217, 112, 255] : [218, 248, 250, 235],
      getLineWidth: (feature) => feature.id === selectedFeatureId ? 3 : 1.5,
    }),
    new TextLayer<TownFeature>({
      id: "landmark-labels",
      data: data.landmarks,
      ...common,
      pickable: false,
      billboard: true,
      characterSet: "auto",
      fontFamily: "Noto Sans SC Variable",
      fontWeight: 600,
      getText: (feature) => feature.name,
      getPosition: (feature) => feature.position!,
      getColor: [202, 235, 238, 235],
      getSize: 11,
      getPixelOffset: [0, -17],
      getTextAnchor: "middle",
      getAlignmentBaseline: "bottom",
      background: true,
      getBackgroundColor: [6, 23, 31, 194],
      backgroundPadding: [4, 2],
    }),
  ];
}
