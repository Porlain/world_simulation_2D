<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { Deck, OrthographicView, type Layer, type PickingInfo } from "@deck.gl/core";
import type { RunRate, ScenarioBundle, SnapshotState } from "./api";
import { MAP_CLARITY_BY_VALUE, type MapClarity } from "./renderSettings";
import {
  assembleTownRenderData,
  createDynamicTownLayers,
  createStaticTownLayers,
  type TownFeature,
  type FlowAnalysisMode,
  type TownFlowRoad,
  type TownLayerVisibility,
  type TownRenderData,
} from "./townLayers";

const props = defineProps<{
  bundle: ScenarioBundle | null;
  snapshot: SnapshotState | null;
  runRate: RunRate;
  running: boolean;
  selectedFeatureId: string | null;
  visibility: TownLayerVisibility;
  analysisFlow: FlowAnalysisMode;
  flowDensity: number;
  mapClarity: MapClarity;
  theme: "pearl" | "night";
}>();

const emit = defineEmits<{
  (event: "select-feature", featureId: string): void;
  (event: "set-analysis-flow", flow: FlowAnalysisMode): void;
}>();

const mapHost = ref<HTMLDivElement | null>(null);
const renderError = ref<string | null>(null);
let deck: Deck<OrthographicView> | null = null;
let resizeObserver: ResizeObserver | null = null;
let renderData: TownRenderData | null = null;
let renderBundle: ScenarioBundle | null = null;
let staticLayers: Layer[] = [];
let compactLabels = false;
const viewZoom = ref(0);
const viewBearing = ref(0);
let hoveredObject: TownFeature | null = null;
let lastHoveredId: string | null = null;

// -- 右键旋转状态 --
let rotating = false;
let lastRotateAngle = 0;

function onRotateStart(e: MouseEvent) {
  if (e.button !== 2) return;
  if (!mapHost.value) return;
  const rect = mapHost.value.getBoundingClientRect();
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;
  lastRotateAngle = Math.atan2(e.clientY - cy, e.clientX - cx);
  rotating = true;
}

function onRotateMove(e: MouseEvent) {
  if (!rotating) return;
  if (!mapHost.value) return;
  const rect = mapHost.value.getBoundingClientRect();
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;
  const angle = Math.atan2(e.clientY - cy, e.clientX - cx);
  let delta = (angle - lastRotateAngle) * (180 / Math.PI);
  if (delta > 180) delta -= 360;
  if (delta < -180) delta += 360;
  viewBearing.value = (viewBearing.value + delta + 360) % 360;
  lastRotateAngle = angle;
}

function onRotateEnd(e: MouseEvent) {
  if (e.button !== 2) return;
  rotating = false;
}

function resetBearing() {
  viewBearing.value = 0;
}

// 计算绕数据中心的旋转矩阵（deck.gl modelMatrix 格式：列优先 Float32Array）
function rotationModelMatrix(
  bearingDeg: number,
  centerX: number,
  centerY: number,
): Float32Array {
  if (bearingDeg === 0) return new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
  const rad = (bearingDeg * Math.PI) / 180;
  const c = Math.cos(rad);
  const s = Math.sin(rad);
  // translate(center) * rotate(θ) * translate(-center)
  const tx = centerX * (1 - c) + centerY * s;
  const ty = centerY * (1 - c) - centerX * s;
  return new Float32Array([
    c,  s, 0, 0,
    -s, c, 0, 0,
    0,  0, 1, 0,
    tx, ty,0, 1,
  ]);
}

const rotateModelMatrix = computed(() => {
  if (!renderData) return new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
  const cx = (renderData.bounds[0] + renderData.bounds[2]) / 2;
  const cy = (renderData.bounds[1] + renderData.bounds[3]) / 2;
  return rotationModelMatrix(viewBearing.value, cx, cy);
});

function niceScale(rawDistance: number): number {
  const exponent = Math.floor(Math.log10(Math.max(rawDistance, 0.001)));
  const base = rawDistance / 10 ** exponent;
  const niceBase = base <= 1 ? 1 : base <= 2 ? 2 : base <= 5 ? 5 : 10;
  return niceBase * 10 ** exponent;
}

const scaleDistance = computed(() => niceScale(110 * 2 ** -viewZoom.value));
const scaleLabel = computed(() => scaleDistance.value >= 1000 ? `${(scaleDistance.value / 1000).toFixed(scaleDistance.value >= 10_000 ? 0 : 1)} km` : `${Math.round(scaleDistance.value)} m`);
const scaleWidth = computed(() => Math.max(48, Math.min(140, 110 * scaleDistance.value / (110 * 2 ** -viewZoom.value))));

function tooltipText(object: TownFeature): string {
  if (object.kind === "flow-road") {
    const road = object as TownFlowRoad;
    return [
      `道路 ${road.id}`,
      `类型：${road.roadKind === "primary" ? "主干道" : road.roadKind === "ring" ? "环路" : road.roadKind === "secondary" ? "次干道" : road.roadKind === "lane" ? "车行巷" : road.roadKind === "alley" ? "步行小巷" : road.roadKind === "walkway" ? "建筑间步道" : "街道"}`,
      `通行：${road.pedestrianAccess !== false ? "行人" : "禁行人"} · ${road.vehicleAccess !== false ? "车辆" : "禁车辆"}`,
      `关联线路：${road.routeCount.toLocaleString("zh-CN")} 条`,
      ...(road.fromName && road.toName ? [`主要线路：${road.fromName} → ${road.toName}`] : []),
      ...(props.analysisFlow === "people" ? [
        `${road.localEstimate ? "街区活动估算" : "人流在途"}：${Math.round(road.peopleCount).toLocaleString("zh-CN")} 人`,
        `本 tick 相对强度：${Math.round(road.peopleRatio * 100)}%`,
        `顺道路定义 → ${Math.round(road.peopleForward).toLocaleString("zh-CN")} 人`,
        `逆道路定义 ← ${Math.round(road.peopleReverse).toLocaleString("zh-CN")} 人`,
        `净流向：${road.peopleForward >= road.peopleReverse ? "顺向" : "逆向"} ${Math.abs(Math.round(road.peopleForward - road.peopleReverse)).toLocaleString("zh-CN")} 人`,
      ] : [
        `${road.localEstimate ? "街区活动估算" : "车流在途"}：${Math.round(road.vehicleCount).toLocaleString("zh-CN")} 辆`,
        `本 tick 相对强度：${Math.round(road.vehicleRatio * 100)}%`,
        `顺道路定义 → ${Math.round(road.vehicleForward).toLocaleString("zh-CN")} 辆`,
        `逆道路定义 ← ${Math.round(road.vehicleReverse).toLocaleString("zh-CN")} 辆`,
        `净流向：${road.vehicleForward >= road.vehicleReverse ? "顺向" : "逆向"} ${Math.abs(Math.round(road.vehicleForward - road.vehicleReverse)).toLocaleString("zh-CN")} 辆`,
      ]),
    ].join("\n");
  }
  const sourceId = (object as TownFeature & { sourceId?: string }).sourceId;
  if (sourceId) {
    const locationText = locationTooltipText(sourceId);
    if (locationText) return locationText;
  }
  return object.name;
}

function snapshotFlowValue(snapshot: SnapshotState, connectionId: string, flowId: string) {
  if (snapshot.schema_version === 2) {
    const value = snapshot.connections[connectionId]?.[flowId];
    return { departed: value?.departed ?? 0, arrived: value?.arrived ?? 0, inTransit: value?.in_transit ?? 0 };
  }
  const activity = snapshot.connection_activity[connectionId]?.[flowId];
  const buckets = snapshot.transit_buckets[connectionId]?.[flowId] ?? [];
  return {
    departed: activity?.departed ?? 0,
    arrived: activity?.arrived ?? 0,
    inTransit: buckets.reduce((sum, count) => sum + count, 0),
  };
}

function locationTooltipText(locationId: string): string | null {
  const bundle = props.bundle;
  const snapshot = props.snapshot;
  if (!bundle || !snapshot) return null;
  const location = bundle.config.locations.find((item) => item.id === locationId);
  if (!location) return null;
  const types = bundle.simulation_package?.flow_types ?? bundle.config.flow_types;
  const peopleId = types.find((flow) => flow.id === "pedestrian" || flow.id === "citizen" || flow.unit === "people")?.id ?? null;
  const vehicleId = types.find((flow) => flow.id === "vehicle" || flow.unit === "vehicles")?.id ?? null;
  const connections = bundle.simulation_package?.connections ?? bundle.config.connections;
  const statsFor = (flowId: string | null) => {
    if (!flowId) return null;
    const stats = {
      registered: location.initial_counts[flowId] ?? 0,
      occupants: snapshot.location_counts[locationId]?.[flowId] ?? 0,
      inTransit: 0,
      departed: 0,
      arrived: 0,
    };
    for (const connection of connections) {
      if (connection.from_location_id !== locationId && connection.to_location_id !== locationId) continue;
      const activity = snapshotFlowValue(snapshot, connection.id, flowId);
      stats.inTransit += activity.inTransit;
      if (connection.from_location_id === locationId) stats.departed += activity.departed;
      if (connection.to_location_id === locationId) stats.arrived += activity.arrived;
    }
    return stats;
  };
  const people = statsFor(peopleId);
  const vehicles = statsFor(vehicleId);
  const bindingIds = bundle.simulation_package?.bindings.location_feature_ids[locationId] ?? [];
  const districtLabels = bundle.town_skeleton
    ? bindingIds
      .map((featureId) => bundle.town_skeleton?.districts.find((district) => district.id === featureId))
      .filter((district): district is NonNullable<typeof district> => Boolean(district))
      .map((district) => district.id.replace(/^district-/, "").toUpperCase())
    : [];
  const lines = [location.name];
  if (districtLabels.length) {
    lines.push(`${districtLabels.length > 1 ? "聚合居民区" : "统计居民区"}：${districtLabels.join("、")}`);
  }
  if (people) {
    lines.push(`人流 · 登记 ${Math.round(people.registered).toLocaleString("zh-CN")} / 当前建筑内 ${Math.round(people.occupants).toLocaleString("zh-CN")} 人`);
    lines.push(`人流 · 道路在途 ${Math.round(people.inTransit).toLocaleString("zh-CN")} 人`);
    lines.push(`人流 · 本 tick 出发 ${Math.round(people.departed).toLocaleString("zh-CN")} / 经过 ${Math.round(people.departed + people.arrived).toLocaleString("zh-CN")} / 到达 ${Math.round(people.arrived).toLocaleString("zh-CN")}`);
  }
  if (vehicles) {
    lines.push(`车流 · 登记 ${Math.round(vehicles.registered).toLocaleString("zh-CN")} / 当前驻留 ${Math.round(vehicles.occupants).toLocaleString("zh-CN")} 辆`);
    lines.push(`车流 · 道路在途 ${Math.round(vehicles.inTransit).toLocaleString("zh-CN")} 辆`);
    lines.push(`车流 · 本 tick 出发 ${Math.round(vehicles.departed).toLocaleString("zh-CN")} / 经过 ${Math.round(vehicles.departed + vehicles.arrived).toLocaleString("zh-CN")} / 到达 ${Math.round(vehicles.arrived).toLocaleString("zh-CN")}`);
  }
  return lines.join("\n");
}

function fittedViewState(data: TownRenderData) {
  const host = mapHost.value?.getBoundingClientRect();
  const width = Math.max(320, host?.width ?? 900);
  const height = Math.max(240, host?.height ?? 600);
  const sceneWidth = Math.max(1, data.bounds[2] - data.bounds[0]);
  const sceneHeight = Math.max(1, data.bounds[3] - data.bounds[1]);
  const horizontalPadding = width < 600 ? 32 : 110;
  const verticalPadding = width < 600 ? 130 : 190;
  const zoom = Math.log2(Math.max(0.01, Math.min((width - horizontalPadding) / sceneWidth, (height - verticalPadding) / sceneHeight)));
  return {
    target: [(data.bounds[0] + data.bounds[2]) / 2, (data.bounds[1] + data.bounds[3]) / 2, 0] as [number, number, number],
    zoom,
    minZoom: zoom - 2,
    maxZoom: zoom + 7,
  };
}

function updateLayers(refit = false, rebuildStatic = false) {
  if (!deck) return;
  const nextCompactLabels = (mapHost.value?.getBoundingClientRect().width ?? 900) < 600;
  if (nextCompactLabels !== compactLabels) {
    compactLabels = nextCompactLabels;
    rebuildStatic = true;
  }
  const bundleChanged = renderBundle !== props.bundle;
  if (bundleChanged || rebuildStatic || (props.bundle && !renderData)) {
    if (bundleChanged) {
      renderData = props.bundle ? assembleTownRenderData(props.bundle) : null;
      renderBundle = props.bundle;
    }
    staticLayers = renderData ? createStaticTownLayers(renderData, props.selectedFeatureId, props.visibility, compactLabels, rotateModelMatrix.value, props.theme) : [];
  }
  const viewState = refit && renderData ? fittedViewState(renderData) : null;
  if (viewState) viewZoom.value = viewState.zoom;
  const landmarkLayerIds = new Set(["landmark-symbols", "landmark-labels", "functional-zone-labels"]);
  const landmarkLayers = staticLayers.filter((layer) => landmarkLayerIds.has(String(layer.id)));
  const baseStaticLayers = staticLayers.filter((layer) => !landmarkLayerIds.has(String(layer.id)));
  const dynamicLayers = props.bundle
    ? createDynamicTownLayers(props.bundle, props.snapshot, props.selectedFeatureId, undefined, props.visibility, props.analysisFlow, hoveredObject, rotateModelMatrix.value, props.theme, props.flowDensity)
    : [];
  const particleLayers = dynamicLayers.filter((layer) => layer.id === "people-flow-markers" || layer.id === "vehicle-flow-markers");
  const baseDynamicLayers = dynamicLayers.filter((layer) => layer.id !== "people-flow-markers" && layer.id !== "vehicle-flow-markers" && layer.id !== "hover-route-line");
  const hoverLayers = dynamicLayers.filter((layer) => layer.id === "hover-route-line");
  deck.setProps({
    layers: [...baseStaticLayers, ...baseDynamicLayers, ...landmarkLayers, ...particleLayers, ...hoverLayers],
    ...(viewState ? { initialViewState: viewState } : {}),
  });
}

onMounted(async () => {
  await nextTick();
  if (!mapHost.value) return;

  deck = new Deck<OrthographicView>({
    parent: mapHost.value,
    width: "100%",
    height: "100%",
    views: new OrthographicView({ id: "town", controller: true, flipY: false }),
    initialViewState: { target: [0, 0, 0], zoom: 0, minZoom: -8, maxZoom: 12 },
    layers: [],
    // Clarity controls device pixels: higher modes spend more GPU memory and fill rate.
    useDevicePixels: MAP_CLARITY_BY_VALUE[props.mapClarity].pixels,
    pickingRadius: 4,
    getCursor: ({ isDragging, isHovering }) => isDragging ? "grabbing" : isHovering ? "pointer" : "grab",
    onViewStateChange: ({ viewState }) => {
      if (typeof viewState.zoom === "number") viewZoom.value = viewState.zoom;
    },
    getTooltip: ({ object }: PickingInfo<TownFeature>) => object ? {
      text: tooltipText(object),
      style: {
        color: props.theme === "pearl" ? "#3d2d22" : "#e5eef0",
        backgroundColor: props.theme === "pearl" ? "rgba(247, 238, 211, 0.96)" : "rgba(31, 45, 55, 0.96)",
        border: props.theme === "pearl" ? "1px solid rgba(102, 77, 51, 0.38)" : "1px solid rgba(164, 193, 204, 0.38)",
        borderRadius: "4px",
        fontSize: "11px",
        maxWidth: "360px",
      },
    } : null,
    onHover: ({ object }: PickingInfo<TownFeature>) => {
      const hoveredId = object?.id ?? null;
      if (hoveredId === lastHoveredId) return;
      lastHoveredId = hoveredId;
      hoveredObject = object ?? null;
      updateLayers(false);
    },
    onClick: ({ object }: PickingInfo<TownFeature>) => {
      if (!object) return;
      emit("select-feature", object.kind === "flow-road"
        ? object.id
        : (object as TownFeature & { sourceId?: string }).sourceId ?? object.id);
    },
    onError: (error) => {
      renderError.value = error instanceof Error ? error.message : "WebGL renderer failed";
    },
  });

  // 右键旋转事件（监听整个窗口，避免被 deck.gl canvas 拦截）
  window.addEventListener("mousedown", onRotateStart);
  window.addEventListener("mousemove", onRotateMove);
  window.addEventListener("mouseup", onRotateEnd);

  resizeObserver = new ResizeObserver(() => updateLayers(false));
  resizeObserver.observe(mapHost.value);
  updateLayers(true);
});

onUnmounted(() => {
  window.removeEventListener("mousedown", onRotateStart);
  window.removeEventListener("mousemove", onRotateMove);
  window.removeEventListener("mouseup", onRotateEnd);
  resizeObserver?.disconnect();
  deck?.finalize();
  deck = null;
  staticLayers = [];
  renderData = null;
  renderBundle = null;
});

// 当 bearing 变化时重建所有图层以更新 modelMatrix
watch(viewBearing, () => updateLayers(false, true));
watch(() => props.bundle, () => updateLayers(true, true));
watch(() => props.selectedFeatureId, () => updateLayers(false, true));
watch(() => props.snapshot?.tick, () => updateLayers(false));
watch(() => props.visibility, () => updateLayers(false, true), { deep: true });
watch(() => props.analysisFlow, () => updateLayers(false));
watch(() => props.flowDensity, () => updateLayers(false));
watch(() => props.theme, () => updateLayers(false, true));
watch(() => props.mapClarity, (value) => {
  deck?.setProps({ useDevicePixels: MAP_CLARITY_BY_VALUE[value].pixels });
});
</script>

<template>
  <div ref="mapHost" class="city-map" aria-label="城镇流量地图" @contextmenu.prevent>
    <div v-if="!bundle" class="map-empty">暂无场景</div>
    <div v-if="renderError" class="map-render-error" role="alert">{{ renderError }}</div>
    <div v-if="bundle" class="map-flow-toggle" aria-label="热力分析对象">
      <button
        type="button"
        :class="{ 'map-flow-toggle--active': analysisFlow === 'people' }"
        :aria-pressed="analysisFlow === 'people'"
        @click="emit('set-analysis-flow', 'people')"
      >人流</button>
      <button
        type="button"
        :class="{ 'map-flow-toggle--active': analysisFlow === 'vehicle' }"
        :aria-pressed="analysisFlow === 'vehicle'"
        @click="emit('set-analysis-flow', 'vehicle')"
      >车流</button>
    </div>
    <div class="map-legend map-legend--static" aria-label="地图图例">
      <span v-if="visibility.walls"><i class="legend-line legend-line--wall"></i>城墙</span>
      <span v-if="visibility.roads"><i class="legend-line legend-line--road"></i>主干道</span>
      <span v-if="visibility.roads"><i class="legend-line legend-line--lane"></i>车行巷</span>
      <span v-if="visibility.roads"><i class="legend-line legend-line--alley"></i>步行小巷</span>
      <span v-if="visibility.roads"><i class="legend-line legend-line--walkway"></i>建筑间步道</span>
      <span v-if="visibility.buildings"><i class="legend-building"></i>建筑</span>
      <span v-if="visibility.landmarks"><i class="legend-landmark"></i>地标</span>
      <span v-if="visibility.landmarks"><i class="legend-zone"></i>功能范围</span>
      <span v-if="visibility.people"><i class="legend-dot legend-dot--people"></i>人流样本</span>
      <span v-if="visibility.vehicles"><i class="legend-arrow"></i>车辆样本</span>
      <span v-if="visibility.heat" title="颜色和线宽表示本 tick 相对强度；箭头表示顺、逆道路定义方向"><i class="legend-heat" :class="{ 'legend-heat--vehicle': analysisFlow === 'vehicle' }"></i>{{ analysisFlow === "people" ? "人流" : "车流" }}方向热力</span>
      <span v-if="visibility.heat"><i class="legend-direction">›</i>箭头方向</span>
    </div>
    <div class="map-scale" aria-label="地图比例尺">
      <span class="map-scale__line" :style="{ width: `${scaleWidth}px` }"></span>
      <strong>{{ scaleLabel }}</strong>
    </div>
    <div class="map-compass" aria-label="指北针" title="点击复位方向" @click="resetBearing">
      <div class="map-compass__inner" :style="{ transform: `rotate(${-viewBearing}deg)` }">
        <span>N</span>
        <i class="map-compass__vertical"></i>
        <i class="map-compass__horizontal"></i>
      </div>
    </div>
    <div v-if="bundle" class="map-source">{{ bundle.town_skeleton?.generator_version?.toUpperCase() ?? "LEGACY" }}</div>
    <div v-if="snapshot" class="map-stamp">T+{{ snapshot.tick.toString().padStart(4, "0") }}</div>
  </div>
</template>
