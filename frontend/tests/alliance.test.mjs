import assert from "node:assert/strict";
import test from "node:test";

import { allianceFlowPoint, createAlliance } from "../src/alliance.ts";

test("alliance generation is deterministic and keeps its settlement hierarchy", () => {
  const first = createAlliance(1234);
  const second = createAlliance(1234);

  assert.deepEqual(first, second);
  assert.equal(first.settlements.filter((item) => item.kind === "capital").length, 3);
  assert.equal(first.settlements.filter((item) => item.kind === "town").length, 9);
  assert.equal(first.settlements.filter((item) => item.kind === "village").length, 18);
  assert.equal(first.roads.length, 30);
  assert.ok(first.mountains.length >= 3);
  assert.ok(first.rivers.length >= 3);
  assert.ok(first.lakes.length >= 3);
  assert.ok(first.landmasses.length >= 3);

  const byId = new Map(first.settlements.map((item) => [item.id, item]));
  for (const settlement of first.settlements.filter((item) => item.parentId)) {
    assert.ok(byId.get(settlement.parentId));
    assert.ok(byId.get(settlement.parentId).children.includes(settlement.id));
  }
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
