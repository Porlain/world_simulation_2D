import type { Coordinate } from "./api";

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
  settlements: AllianceSettlement[];
  roads: AllianceRoad[];
}

const BOUNDS: readonly [number, number, number, number] = [0, 0, 1600, 1000];

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
const ALLIANCE_TARGET_BOUNDS = { x0: 50, x1: 615, y0: 65, y1: 620 };
const ALLIANCE_TERRITORY: Coordinate[] = [
  point(65, 80), point(430, 65), point(590, 145), point(615, 330),
  point(530, 545), point(305, 620), point(95, 580), point(50, 360),
];

function fitAlliancePoint(source: Coordinate): Coordinate {
  const xRatio = (source[0] - ALLIANCE_SOURCE_BOUNDS.x0) / (ALLIANCE_SOURCE_BOUNDS.x1 - ALLIANCE_SOURCE_BOUNDS.x0);
  const yRatio = (source[1] - ALLIANCE_SOURCE_BOUNDS.y0) / (ALLIANCE_SOURCE_BOUNDS.y1 - ALLIANCE_SOURCE_BOUNDS.y0);
  return point(
    ALLIANCE_TARGET_BOUNDS.x0 + xRatio * (ALLIANCE_TARGET_BOUNDS.x1 - ALLIANCE_TARGET_BOUNDS.x0),
    ALLIANCE_TARGET_BOUNDS.y0 + yRatio * (ALLIANCE_TARGET_BOUNDS.y1 - ALLIANCE_TARGET_BOUNDS.y0),
  );
}

function fitAllianceOffset(offset: Coordinate): Coordinate {
  return point(
    offset[0] * (ALLIANCE_TARGET_BOUNDS.x1 - ALLIANCE_TARGET_BOUNDS.x0)
      / (ALLIANCE_SOURCE_BOUNDS.x1 - ALLIANCE_SOURCE_BOUNDS.x0),
    offset[1] * (ALLIANCE_TARGET_BOUNDS.y1 - ALLIANCE_TARGET_BOUNDS.y0)
      / (ALLIANCE_SOURCE_BOUNDS.y1 - ALLIANCE_SOURCE_BOUNDS.y0),
  );
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

function positionInsideTerritory(raw: Coordinate, parent: Coordinate): Coordinate {
  if (pointInsidePolygon(raw, ALLIANCE_TERRITORY)) return point(raw[0], raw[1]);
  for (const parentWeight of [0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 1]) {
    const candidate = point(
      raw[0] + (parent[0] - raw[0]) * parentWeight,
      raw[1] + (parent[1] - raw[1]) * parentWeight,
    );
    if (pointInsidePolygon(candidate, ALLIANCE_TERRITORY)) return candidate;
  }
  return point(parent[0], parent[1]);
}

function roadPath(from: Coordinate, to: Coordinate, kind: AllianceRoad["kind"]): Coordinate[] {
  if (kind === "imperial") return [from, to];
  const dx = to[0] - from[0];
  const dy = to[1] - from[1];
  const length = Math.hypot(dx, dy) || 1;
  const normal: Coordinate = [-dy / length, dx / length];
  const departure = kind === "regional" ? 0.28 : 0.2;
  const offset = kind === "regional" ? 9 : 6;
  const bend = point(
    from[0] + dx * departure + normal[0] * offset,
    from[1] + dy * departure + normal[1] * offset,
  );
  return [from, bend, to];
}

function appendRoad(
  roads: AllianceRoad[],
  from: AllianceSettlement,
  to: AllianceSettlement,
  kind: AllianceRoad["kind"],
): void {
  const peopleRate = kind === "imperial" ? 0.72 : kind === "regional" ? 0.46 : 0.2;
  roads.push({
    id: `alliance-road-${roads.length.toString().padStart(3, "0")}`,
    fromId: from.id,
    toId: to.id,
    path: roadPath(from.position, to.position, kind),
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

export function createAlliance(seed = 20260808): AllianceModel {
  const settlements: AllianceSettlement[] = [];
  const capitals = [
    settlement("capital-northwest", "霜原城", "capital", fitAlliancePoint(point(210, 190)), 78_000, null, "北方边境", seed + 11, { influenceRadius: 135 }),
    settlement("capital-northeast", "晨曦城", "capital", fitAlliancePoint(point(670, 190)), 96_000, null, "东部行省", seed + 17, { influenceRadius: 145 }),
    settlement("capital-heart", "曙光城", "capital", fitAlliancePoint(point(450, 450)), 124_000, null, "中央行省", seed + 23, { influenceRadius: 155 }),
    settlement("capital-southwest", "潮汐城", "capital", fitAlliancePoint(point(200, 700)), 91_000, null, "南部海岸", seed + 29, { influenceRadius: 145 }),
    settlement("capital-southeast", "赤穹城", "capital", fitAlliancePoint(point(660, 700)), 88_000, null, "东南边疆", seed + 31, { influenceRadius: 150 }),
  ];
  settlements.push(...capitals);

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
    ...boundaryTownPlans.map((plan) => ({ ...plan, position: fitAlliancePoint(plan.position), boundaryAnchor: true })),
    ...supportTownPlans.map((plan) => ({
      ...plan,
      position: point(
        capitals[plan.capitalIndex].position[0] + fitAllianceOffset(plan.offset)[0],
        capitals[plan.capitalIndex].position[1] + fitAllianceOffset(plan.offset)[1],
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
      positionInsideTerritory(plan.position, capital.position),
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
      const village = settlement(
        `village-${townIndex.toString().padStart(2, "0")}-${index}`,
        `${villageNames[(townIndex * 3 + index) % villageNames.length]}村`,
        "village",
        positionInsideTerritory(rawPosition, town.position),
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
  const outerCapitalRoadOrder = [0, 1, 4, 3];
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
    ALLIANCE_TERRITORY,
    [point(900, 140), point(1040, 90), point(1190, 150), point(1320, 80), point(1510, 150), point(1600, 360), point(1510, 520), point(1380, 500), point(1260, 600), point(1080, 530), point(950, 430)],
    [point(720, 700), point(900, 650), point(1080, 700), point(1240, 640), point(1440, 760), point(1600, 700), point(1600, 1000), point(720, 1000)],
  ];
  const mountains: Coordinate[][] = [
    [point(930, 70), point(1050, 120), point(1130, 65), point(1240, 145), point(1370, 92), point(1510, 180), point(1450, 330), point(1260, 290), point(1110, 350), point(980, 260)],
    [point(890, 820), point(1040, 700), point(1160, 770), point(1270, 680), point(1410, 760), point(1550, 710), point(1600, 980), point(1080, 980)],
    [point(1350, 390), point(1440, 330), point(1580, 390), point(1510, 590), point(1390, 620), point(1300, 520)],
    [point(70, 900), point(210, 850), point(330, 905), point(470, 860), point(620, 930), point(760, 890), point(840, 1000), point(40, 1000)],
  ];
  const rivers: Coordinate[][] = [
    [point(930, 0), point(1020, 180), point(1110, 310), point(1080, 470), point(1180, 620), point(1110, 810), point(1230, 1000)],
    [point(1570, 0), point(1480, 160), point(1510, 300), point(1430, 450), point(1470, 650), point(1400, 820), point(1510, 1000)],
    [point(930, 570), point(1040, 560), point(1170, 650), point(1300, 630), point(1460, 700)],
  ];
  const lakes: Coordinate[][] = [
    [point(1010, 390), point(1110, 350), point(1200, 390), point(1225, 475), point(1160, 535), point(1050, 505), point(990, 450)],
    [point(1330, 170), point(1410, 130), point(1490, 175), point(1510, 250), point(1450, 300), point(1360, 275)],
    [point(960, 720), point(1040, 680), point(1120, 715), point(1135, 790), point(1060, 825), point(980, 790)],
  ];
  const bands: AllianceTerrainBand[] = [
    { id: "polar-north", label: "北极圈", y0: 0, y1: 135, kind: "polar" },
    { id: "north-temperate", label: "北温带", y0: 135, y1: 390, kind: "cold" },
    { id: "equatorial", label: "赤道带", y0: 390, y1: 610, kind: "equatorial" },
    { id: "south-temperate", label: "南温带", y0: 610, y1: 865, kind: "temperate" },
    { id: "polar-south", label: "南极圈", y0: 865, y1: 1000, kind: "polar" },
  ];
  return {
    name: "人类联盟",
    seed,
    bounds: BOUNDS,
    bands,
    territory: ALLIANCE_TERRITORY,
    landmasses,
    mountains,
    rivers,
    lakes,
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
