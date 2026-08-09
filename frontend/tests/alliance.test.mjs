import assert from "node:assert/strict";
import test from "node:test";

import { allianceFlowPoint, createAlliance } from "../src/alliance.ts";

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
  assert.ok(first.landmasses.length >= 10);
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
