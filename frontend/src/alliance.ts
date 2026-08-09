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

function roadPath(from: Coordinate, to: Coordinate): Coordinate[] {
  return [from, to];
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
    path: roadPath(from.position, to.position),
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
): AllianceSettlement {
  return { id, name, kind, position, population, parentId, children: [], region, generationSeed: seed };
}

export function createAlliance(seed = 20260808): AllianceModel {
  const settlements: AllianceSettlement[] = [];
  const capitals = [
    settlement("capital-north", "北境都", "capital", point(310, 230), 78_000, null, "北方边境", seed + 11),
    settlement("capital-heart", "曙光城", "capital", point(600, 450), 124_000, null, "中央行省", seed + 17),
    settlement("capital-south", "潮汐城", "capital", point(300, 720), 91_000, null, "南部海岸", seed + 23),
  ];
  settlements.push(...capitals);

  const townNames = [
    ["霜桥", "白桦", "铁岭"],
    ["谷门", "长风", "金穗"],
    ["盐港", "南岬", "潮汐湾"],
  ];
  const townOffsets: Coordinate[][] = [
    [[-165, 110], [160, -50], [190, 120]],
    [[-160, -60], [160, -165], [180, 115]],
    [[-150, -70], [90, -190], [220, 40]],
  ];
  const towns: AllianceSettlement[] = [];
  let ordinal = 0;
  capitals.forEach((capital, capitalIndex) => {
    townNames[capitalIndex].forEach((name, townIndex) => {
      const offset = townOffsets[capitalIndex][townIndex];
      const town = settlement(
        `town-${capitalIndex}-${townIndex}`,
        name,
        "town",
        point(capital.position[0] + offset[0], capital.position[1] + offset[1]),
        8_000 + Math.round(stableUnit(seed, `town-pop-${ordinal}`) * 8_500),
        capital.id,
        capital.region,
        seed + 100 + ordinal,
      );
      ordinal += 1;
      towns.push(town);
      settlements.push(town);
      capital.children.push(town.id);
    });
  });

  const villageNames = ["松溪", "麦垄", "石泉", "鹿原", "风车", "榆湾"];
  const villageOffsets: Coordinate[][] = [
    [[-45, 50], [-20, -75]],
    [[55, -55], [-65, -35]],
    [[65, 25], [30, -70]],
    [[-65, 35], [-45, -55]],
    [[55, -45], [45, 60]],
    [[55, -45], [-20, 70]],
    [[-50, 50], [-40, -60]],
    [[55, 35], [10, -70]],
    [[-50, 55], [70, -20]],
  ];
  towns.forEach((town, townIndex) => {
    for (let index = 0; index < 2; index += 1) {
      const offset = villageOffsets[townIndex][index];
      const village = settlement(
        `village-${townIndex}-${index}`,
        `${villageNames[(townIndex * 2 + index) % villageNames.length]}村`,
        "village",
        point(town.position[0] + offset[0], town.position[1] + offset[1]),
        420 + Math.round(stableUnit(seed, `${town.id}:population:${index}`) * 820),
        town.id,
        town.region,
        seed + 500 + townIndex * 2 + index,
      );
      settlements.push(village);
      town.children.push(village.id);
    }
  });

  const byId = new Map(settlements.map((item) => [item.id, item]));
  const roads: AllianceRoad[] = [];
  appendRoad(roads, capitals[0], capitals[1], "imperial");
  appendRoad(roads, capitals[1], capitals[2], "imperial");
  appendRoad(roads, capitals[2], capitals[0], "imperial");
  for (const town of towns) {
    const parent = byId.get(town.parentId ?? "");
    if (parent) appendRoad(roads, parent, town, "regional");
    for (const villageId of town.children) {
      const village = byId.get(villageId);
      if (village) appendRoad(roads, town, village, "local");
    }
  }

  const territory: Coordinate[] = [
    point(70, 100), point(850, 90), point(920, 300), point(870, 580), point(650, 850), point(150, 840), point(45, 560),
  ];
  const landmasses: Coordinate[][] = [
    territory,
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
    territory,
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
