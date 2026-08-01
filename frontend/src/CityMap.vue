<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import * as L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { Coordinate, RunRate, ScenarioBundle, SnapshotState } from "./api";

const props = defineProps<{
  bundle: ScenarioBundle | null;
  snapshot: SnapshotState | null;
  runRate: RunRate;
  running: boolean;
}>();

const emit = defineEmits<{
  (event: "select-feature", featureId: string): void;
}>();

const mapHost = ref<HTMLDivElement | null>(null);
const canvas = ref<HTMLCanvasElement | null>(null);
let map: L.Map | null = null;
let featureLayer: L.FeatureGroup | null = null;
let animationFrame = 0;
let resizeObserver: ResizeObserver | null = null;
let snapshotReceivedAt = performance.now();
const connectionLayers = new Map<string, L.Polyline>();
const locationLayers = new Map<string, L.CircleMarker>();
const pathMetrics = new Map<string, { points: Coordinate[]; lengths: number[]; total: number }>();

const locationById = () => new Map((props.bundle?.config.locations ?? []).map((location) => [location.id, location]));

function toLatLng(point: Coordinate): L.LatLng {
  return L.latLng(point[1], point[0]);
}

function pathMetric(path: Coordinate[]) {
  const lengths = [0];
  let total = 0;
  for (let index = 1; index < path.length; index += 1) {
    const dx = path[index][0] - path[index - 1][0];
    const dy = path[index][1] - path[index - 1][1];
    total += Math.hypot(dx, dy);
    lengths.push(total);
  }
  return { points: path, lengths, total };
}

function pointAt(metric: { points: Coordinate[]; lengths: number[]; total: number }, progress: number): Coordinate {
  if (metric.total <= 0) return metric.points[0];
  const distance = Math.min(1, Math.max(0, progress)) * metric.total;
  for (let index = 1; index < metric.lengths.length; index += 1) {
    if (distance <= metric.lengths[index]) {
      const segmentStart = metric.lengths[index - 1];
      const segmentLength = metric.lengths[index] - segmentStart || 1;
      const fraction = (distance - segmentStart) / segmentLength;
      const start = metric.points[index - 1];
      const end = metric.points[index];
      return [start[0] + (end[0] - start[0]) * fraction, start[1] + (end[1] - start[1]) * fraction];
    }
  }
  return metric.points[metric.points.length - 1];
}

function loadBaseMap() {
  if (!map || !featureLayer) return;
  featureLayer.clearLayers();
  connectionLayers.clear();
  locationLayers.clear();
  pathMetrics.clear();
  if (!props.bundle) return;

  const locations = locationById();
  const boundsPoints: L.LatLng[] = [];
  for (const location of props.bundle.config.locations) {
    const point = toLatLng(location.position);
    boundsPoints.push(point);
    const marker = L.circleMarker(point, {
      radius: 8,
      color: "#e7d8bb",
      weight: 2,
      fillColor: "#c28c2c",
      fillOpacity: 0.92,
    });
    marker.bindTooltip(location.name, { direction: "top", offset: [0, -8] });
    marker.on("click", () => emit("select-feature", location.id));
    locationLayers.set(location.id, marker);
    featureLayer.addLayer(marker);
  }
  for (const connection of props.bundle.config.connections) {
    const metric = pathMetric(connection.path);
    pathMetrics.set(connection.id, metric);
    const points = connection.path.map(toLatLng);
    boundsPoints.push(...points);
    const line = L.polyline(points, {
      color: "#b9c2b6",
      opacity: 0.58,
      weight: 3,
      lineCap: "round",
      lineJoin: "round",
    });
    const from = locations.get(connection.from_location_id)?.name ?? connection.from_location_id;
    const to = locations.get(connection.to_location_id)?.name ?? connection.to_location_id;
    line.bindTooltip(`${from} → ${to}`, { sticky: true });
    line.on("click", () => emit("select-feature", connection.id));
    connectionLayers.set(connection.id, line);
    featureLayer.addLayer(line);
  }
  if (boundsPoints.length > 0) {
    map.fitBounds(L.latLngBounds(boundsPoints), { padding: [32, 32] });
  }
  updateStyles();
  resizeCanvas();
}

function updateStyles() {
  if (!props.bundle || !props.snapshot) return;
  const flowId = props.bundle.config.flow_types[0]?.id;
  if (!flowId) return;
  for (const connection of props.bundle.config.connections) {
    const layer = connectionLayers.get(connection.id);
    if (!layer) continue;
    const capacity = connection.capacity_per_tick[flowId] ?? 0;
    const departed = props.snapshot.connection_activity[connection.id]?.[flowId]?.departed ?? 0;
    const ratio = capacity === 0 ? 0 : Math.min(1, departed / capacity);
    const color = ratio >= 0.8 ? "#d56443" : ratio >= 0.5 ? "#d4a445" : "#9cc4b8";
    layer.setStyle({ color, weight: 3 + 5 * Math.sqrt(ratio), opacity: 0.9 });
  }
  const counts = props.snapshot.location_counts;
  const maximum = Math.max(1, ...Object.values(counts).map((values) => values[flowId] ?? 0));
  for (const location of props.bundle.config.locations) {
    const marker = locationLayers.get(location.id);
    if (!marker) continue;
    const ratio = (counts[location.id]?.[flowId] ?? 0) / maximum;
    marker.setStyle({ radius: 7 + 16 * Math.sqrt(ratio), fillColor: ratio > 0.75 ? "#d56443" : "#c28c2c" });
  }
}

function resizeCanvas() {
  if (!canvas.value || !mapHost.value) return;
  const rect = mapHost.value.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.value.width = Math.max(1, Math.floor(rect.width * dpr));
  canvas.value.height = Math.max(1, Math.floor(rect.height * dpr));
  canvas.value.style.width = `${rect.width}px`;
  canvas.value.style.height = `${rect.height}px`;
  requestDraw();
}

function drawParticles() {
  if (!canvas.value || !map || !props.bundle || !props.snapshot) return;
  const context = canvas.value.getContext("2d");
  if (!context) return;
  const snapshot = props.snapshot;
  const dpr = window.devicePixelRatio || 1;
  context.setTransform(dpr, 0, 0, dpr, 0, 0);
  const width = canvas.value.width / dpr;
  const height = canvas.value.height / dpr;
  context.clearRect(0, 0, width, height);
  const flowIds = props.bundle.config.flow_types.map((flow) => flow.id);
  const displayTime = snapshot.tick + (props.running ? Math.min(1, Math.max(0, (performance.now() - snapshotReceivedAt) / (1000 / props.runRate))) : 0);

  for (const connection of props.bundle.config.connections) {
    const metric = pathMetrics.get(connection.id);
    if (!metric) continue;
    const transit = flowIds.reduce((sum, flowId) => sum + (snapshot.transit_buckets[connection.id]?.[flowId]?.reduce((a, b) => a + b, 0) ?? 0), 0);
    const desired = Math.min(20, Math.ceil(transit / 25));
    if (desired <= 0) continue;
    for (let slot = 0; slot < desired; slot += 1) {
      const progress = (slot / desired + displayTime / connection.travel_time_ticks) % 1;
      const point = pointAt(metric, progress);
      const pixel = map.latLngToContainerPoint(toLatLng(point));
      context.beginPath();
      context.fillStyle = slot % 3 === 0 ? "#f0c36b" : "#d56443";
      context.globalAlpha = 0.88;
      context.arc(pixel.x, pixel.y, 2.6, 0, Math.PI * 2);
      context.fill();
    }
  }
  context.globalAlpha = 1;
}

function requestDraw() {
  if (animationFrame || !canvas.value) return;
  animationFrame = requestAnimationFrame(() => {
    animationFrame = 0;
    drawParticles();
    updateStyles();
    if (props.running) requestDraw();
  });
}

onMounted(async () => {
  await nextTick();
  if (!mapHost.value) return;
  map = L.map(mapHost.value, {
    crs: L.CRS.Simple,
    preferCanvas: true,
    zoomControl: true,
    attributionControl: false,
    minZoom: -2,
    maxZoom: 4,
  });
  featureLayer = L.featureGroup().addTo(map);
  map.on("move zoom resize", requestDraw);
  resizeObserver = new ResizeObserver(resizeCanvas);
  resizeObserver.observe(mapHost.value);
  loadBaseMap();
});

onUnmounted(() => {
  if (animationFrame) cancelAnimationFrame(animationFrame);
  resizeObserver?.disconnect();
  map?.remove();
  map = null;
  featureLayer = null;
});

watch(() => props.bundle, loadBaseMap);
watch(() => props.snapshot, () => {
  snapshotReceivedAt = performance.now();
  requestDraw();
}, { deep: true });
watch(() => [props.running, props.runRate], requestDraw);
</script>

<template>
  <div ref="mapHost" class="city-map" aria-label="城市流量地图">
    <canvas ref="canvas" class="flow-canvas" aria-label="街道流量动画" role="img"></canvas>
    <div v-if="!bundle" class="map-empty">选择一个场景开始</div>
    <div class="map-legend" aria-label="流量图例">
      <span><i class="legend-dot legend-dot--clear"></i>通畅</span>
      <span><i class="legend-dot legend-dot--busy"></i>繁忙</span>
      <span><i class="legend-dot legend-dot--full"></i>接近容量</span>
    </div>
    <div v-if="snapshot" class="map-stamp">T+{{ snapshot.tick.toString().padStart(4, "0") }}</div>
  </div>
</template>
