import assert from "node:assert/strict";
import test from "node:test";

import { allianceFlowPoint, createAlliance } from "../src/alliance.ts";

function pointInsidePolygon(point, polygon) {
  let inside = false;
  for (let index = 0, previous = polygon.length - 1; index < polygon.length; previous = index++) {
    const current = polygon[index];
    const prior = polygon[previous];
    if ((current[1] > point[1]) !== (prior[1] > point[1])) {
      const edgeX = (prior[0] - current[0]) * (point[1] - current[1])
        / (prior[1] - current[1]) + current[0];
      if (point[0] < edgeX) inside = !inside;
    }
  }
  return inside;
}

function boundingArea(polygon) {
  const xs = polygon.map(([x]) => x);
  const ys = polygon.map(([, y]) => y);
  return (Math.max(...xs) - Math.min(...xs)) * (Math.max(...ys) - Math.min(...ys));
}

test("alliance generation is deterministic and keeps its settlement hierarchy", () => {
  const first = createAlliance(1234);
  const second = createAlliance(1234);
  const anotherWorld = createAlliance(5678);

  assert.deepEqual(first, second);
  assert.notDeepEqual(first.territory, anotherWorld.territory);
  assert.notDeepEqual(first.landmasses, anotherWorld.landmasses);
  assert.notDeepEqual(first.rivers, anotherWorld.rivers);
  assert.notDeepEqual(first.mountains, anotherWorld.mountains);
  assert.equal(first.settlements.filter((item) => item.kind === "capital").length, 5);
  assert.equal(first.settlements.filter((item) => item.kind === "town").length, 23);
  assert.equal(first.settlements.filter((item) => item.kind === "village").length, 69);
  assert.equal(first.roads.length, 97);
  assert.ok(first.mountains.length >= 3);
  assert.ok(first.rivers.length >= 3);
  assert.ok(first.lakes.length >= 3);
  assert.equal(first.landmasses.length, 1);
  assert.equal(first.countries.length, 11);
  assert.ok(first.countries.every((country) => country.polygon.length >= 3));
  assert.equal(first.regions.length, 5);
  assert.ok(first.regions.every((region) => region.polygon.length >= 3));
  assert.ok(first.regions.every((region) => first.settlements.some((settlement) => settlement.id === region.capitalId)));

  const byId = new Map(first.settlements.map((item) => [item.id, item]));
  for (const settlement of first.settlements.filter((item) => item.parentId)) {
    assert.ok(byId.get(settlement.parentId));
    assert.ok(byId.get(settlement.parentId).children.includes(settlement.id));
  }

  const capitals = first.settlements.filter((item) => item.kind === "capital");
  assert.ok(capitals.every((capital) => (capital.influenceRadius ?? 0) >= 120));
  assert.ok(capitals.every((capital) => capital.children.length >= 4));
  assert.equal(first.settlements.filter((item) => item.boundaryAnchor).length, 7);
  const findCapital = (settlement) => {
    let current = settlement;
    while (current.parentId) current = byId.get(current.parentId);
    return current;
  };
  for (const settlement of first.settlements.filter((item) => item.kind !== "capital")) {
    const capital = findCapital(settlement);
    assert.ok(
      Math.hypot(settlement.position[0] - capital.position[0], settlement.position[1] - capital.position[1]) <= (capital.influenceRadius ?? 0),
      `${settlement.name} falls outside ${capital.name} influence range`,
    );
  }
  for (const corner of first.territory) {
    const nearestBoundaryTown = first.settlements
      .filter((item) => item.kind === "town" && item.boundaryAnchor)
      .reduce(
        (distance, town) => Math.min(distance, Math.hypot(town.position[0] - corner[0], town.position[1] - corner[1])),
        Infinity,
      );
    assert.ok(nearestBoundaryTown <= 250, `no boundary town near ${corner}`);
  }
  const xs = first.territory.map(([x]) => x);
  const ys = first.territory.map(([, y]) => y);
  assert.ok(Math.max(...xs) - Math.min(...xs) <= 760);
  assert.ok(Math.max(...ys) - Math.min(...ys) <= 600);
});

test("the alliance occupies a seeded subsection of one host continent", () => {
  const territoryCenters = new Set();
  for (const seed of [2, 3, 1234, 5678, 20260808]) {
    const alliance = createAlliance(seed);
    assert.equal(alliance.landmasses.length, 1);
    assert.ok(
      alliance.territory.every((item) => pointInsidePolygon(item, alliance.landmasses[0])),
      `seed ${seed} has territory outside the main continent`,
    );
    assert.ok(
      boundingArea(alliance.territory) / boundingArea(alliance.landmasses[0]) < 0.16,
      `seed ${seed} makes the alliance too large for its host continent`,
    );
    const center = alliance.territory.reduce(
      (result, [x, y]) => [result[0] + x / alliance.territory.length, result[1] + y / alliance.territory.length],
      [0, 0],
    );
    territoryCenters.add(center.map((value) => Math.round(value)).join(","));
  }
  assert.ok(territoryCenters.size >= 4, "the alliance position should vary with the world seed");
});

test("alliance roads meet only at declared settlements", () => {
  const alliance = createAlliance(20260808);
  const orientation = (start, end, point) =>
    (end[0] - start[0]) * (point[1] - start[1]) - (end[1] - start[1]) * (point[0] - start[0]);
  const crosses = (left, right) =>
    orientation(left.path[0], left.path[1], right.path[0]) * orientation(left.path[0], left.path[1], right.path[1]) < 0
    && orientation(right.path[0], right.path[1], left.path[0]) * orientation(right.path[0], right.path[1], left.path[1]) < 0;

  for (let leftIndex = 0; leftIndex < alliance.roads.length; leftIndex += 1) {
    for (let rightIndex = leftIndex + 1; rightIndex < alliance.roads.length; rightIndex += 1) {
      const left = alliance.roads[leftIndex];
      const right = alliance.roads[rightIndex];
      const sharesSettlement = [left.fromId, left.toId].some((id) => id === right.fromId || id === right.toId);
      if (!sharesSettlement) assert.equal(crosses(left, right), false, `${left.id} crosses ${right.id}`);
    }
  }
});

test("alliance flow points remain on a road path", () => {
  const alliance = createAlliance(4321);
  for (const road of alliance.roads) {
    assert.deepEqual(allianceFlowPoint(road.path, 0), road.path[0]);
    assert.deepEqual(allianceFlowPoint(road.path, 1), road.path[0]);
    assert.ok(allianceFlowPoint(road.path, 0.5).every(Number.isFinite));
  }
});
