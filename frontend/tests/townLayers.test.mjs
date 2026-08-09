import assert from "node:assert/strict";
import test from "node:test";

import { assembleTownFlowData, assembleTownRenderData } from "../src/townLayers.ts";

function physicalRoadFixture() {
  const bundle = {
    config: {
      schema_version: 1,
      scenario_id: "physical-road-test",
      name: "Physical Road Test",
      scale: "city",
      tick_seconds: 1,
      coordinate_system: "local_xy",
      axis_orientation: "x_right_y_up",
      coordinate_unit: "scene_unit",
      flow_types: [{ id: "pedestrian", unit: "people", label: "People" }],
      locations: [
        { id: "from", name: "From", position: [0, 0], initial_counts: { pedestrian: 10 } },
        { id: "to", name: "To", position: [10, 10], initial_counts: { pedestrian: 0 } },
      ],
      connections: [],
    },
    checksum: "test",
    town_skeleton: {
      schema_version: 2,
      scenario_id: "physical-road-test",
      name: "Physical Road Test",
      generation_seed: 1,
      generator_version: "watabou-v1",
      requested_population: 10,
      initial_vehicle_count: 5,
      coordinate_system: "local_xy",
      coordinate_unit: "meter",
      axis_orientation: "x_right_y_up",
      bounds: [0, 0, 10, 10],
      boundary: [[0, 0], [10, 0], [10, 10], [0, 10]],
      districts: [],
      buildings: [],
      junctions: [
        { id: "j-from", position: [0, 2], kind: "normal" },
        { id: "j-mid", position: [5, 2], kind: "normal" },
        { id: "j-to", position: [5, 8], kind: "normal" },
      ],
      streets: [
        {
          id: "street-a",
          from_junction_id: "j-from",
          to_junction_id: "j-mid",
          path: [[0, 2], [5, 2]],
          width: 4,
          kind: "secondary",
          pedestrian_access: true,
          vehicle_access: true,
        },
        {
          id: "street-b",
          from_junction_id: "j-mid",
          to_junction_id: "j-to",
          path: [[5, 2], [5, 8]],
          width: 4,
          kind: "secondary",
          pedestrian_access: true,
          vehicle_access: true,
        },
      ],
      walkways: [],
      landmarks: [],
      district_names: {},
    },
    simulation_package: {
      schema_version: 2,
      tick_seconds: 1,
      flow_types: [{ id: "pedestrian", unit: "people", label: "People" }],
      locations: [
        { id: "from", name: "From", kind: "district", position: [0, 0], initial_counts: { pedestrian: 10 } },
        { id: "to", name: "To", kind: "district", position: [10, 10], initial_counts: { pedestrian: 0 } },
      ],
      connections: [{
        id: "connection",
        from_location_id: "from",
        to_location_id: "to",
        street_segment_ids: ["street-a", "street-b"],
        street_directions: ["forward", "forward"],
        path: [[0, 0], [10, 10]],
        travel_time_ticks: { pedestrian: 10 },
        capacity_per_tick: { pedestrian: 10 },
        demand_per_tick: { pedestrian: { min: 0, max: 10 } },
      }],
      bindings: {
        location_feature_ids: { from: [], to: [] },
        connection_street_ids: { connection: ["street-a", "street-b"] },
      },
      street_graph: null,
    },
  };
  const snapshot = {
    schema_version: 1,
    tick: 3,
    location_counts: { from: { pedestrian: 0 }, to: { pedestrian: 0 } },
    transit_buckets: { connection: { pedestrian: [0, 0, 10] } },
    connection_activity: { connection: { pedestrian: { departed: 0, arrived: 0 } } },
    totals: { pedestrian: 10 },
  };
  return { bundle, snapshot };
}

test("legacy flow markers stay on the rendered street chain", () => {
  const { bundle, snapshot } = physicalRoadFixture();
  const renderedPath = [[0, 2], [5, 2], [5, 8]];
  const renderedSegments = [renderedPath.slice(0, 2), renderedPath.slice(1)];

  const data = assembleTownFlowData(bundle, snapshot);

  assert.ok(data.peopleMarkers.length > 0);
  for (const marker of data.peopleMarkers) {
    assert.ok(
      renderedSegments.some((segment) => JSON.stringify(marker.path) === JSON.stringify(segment)),
      `marker left the rendered street chain: ${JSON.stringify(marker.path)}`,
    );
    const [x, y] = marker.position;
    assert.ok(y === 2 || x === 5, `marker left the rendered street at ${x},${y}`);
  }
});

test("old town skeletons do not invent walkways from building outlines", () => {
  const { bundle, snapshot } = physicalRoadFixture();
  delete bundle.town_skeleton.walkways;
  bundle.town_skeleton.districts.push({
    id: "district",
    kind: "residential",
    polygon: [[6, 0], [10, 0], [10, 4], [6, 4]],
  });
  bundle.town_skeleton.buildings.push({
    id: "building",
    district_id: "district",
    kind: "residential",
    polygon: [[7, 1], [9, 1], [9, 3], [7, 3]],
    anchor: [8, 2],
  });
  bundle.simulation_package.bindings.location_feature_ids.from = ["district", "building"];
  snapshot.location_counts.from.pedestrian = 10;
  snapshot.transit_buckets.connection.pedestrian = [0, 0, 0];

  const data = assembleTownFlowData(bundle, snapshot);

  assert.equal(data.peopleMarkers.length, 0);
  assert.ok(data.roads.every((road) => !road.id.startsWith("walkway-fallback-")));
});

test("legacy bundles without a town skeleton keep their rendered connection roads", () => {
  const { bundle, snapshot } = physicalRoadFixture();
  delete bundle.town_skeleton;

  const data = assembleTownFlowData(bundle, snapshot);

  assert.ok(data.peopleMarkers.length > 0);
  assert.ok(data.peopleMarkers.every((marker) => JSON.stringify(marker.path) === JSON.stringify([[0, 0], [10, 10]])));
});

test("walled towns render a continuous perimeter", () => {
  const { bundle } = physicalRoadFixture();
  bundle.town_skeleton.landmarks.push({
    id: "gate",
    kind: "gate",
    name: "城门",
    position: [0, 0],
  });

  const data = assembleTownRenderData(bundle);
  const { boundary } = bundle.town_skeleton;

  assert.equal(data.walls.length, boundary.length);
  for (const [index, wall] of data.walls.entries()) {
    assert.deepEqual(wall.path, [boundary[index], boundary[(index + 1) % boundary.length]]);
  }
});

test("special landmarks expose the complete ward as a functional range", () => {
  const { bundle } = physicalRoadFixture();
  const district = {
    id: "district-market",
    kind: "market",
    polygon: [[6, 0], [10, 0], [10, 4], [6, 4]],
  };
  bundle.town_skeleton.districts.push(district);
  bundle.town_skeleton.buildings.push({
    id: "market-building",
    district_id: district.id,
    kind: "market",
    polygon: [[7, 1], [8, 1], [8, 2], [7, 2]],
    anchor: [7.5, 1.5],
  });
  bundle.town_skeleton.landmarks.push({
    id: "landmark-market",
    building_id: "market-building",
    kind: "market",
    name: "集市广场",
    position: [7.5, 1.5],
  });

  const data = assembleTownRenderData(bundle);
  assert.deepEqual(data.functionalZones, [{
    id: "functional-zone-market-district-market",
    sourceId: "district-market",
    name: "集市广场范围",
    kind: "market",
    polygon: district.polygon,
    position: [8, 2],
  }]);
});

test("rendered streets stop at the town boundary", () => {
  const { bundle } = physicalRoadFixture();
  bundle.town_skeleton.streets[0].path = [[0, 2], [15, 2]];

  const data = assembleTownRenderData(bundle);

  assert.deepEqual(data.streets[0].path, [[0, 2], [10, 2]]);
});
