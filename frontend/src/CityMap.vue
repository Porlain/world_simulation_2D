<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { Deck, OrthographicView, type Layer, type PickingInfo } from "@deck.gl/core";
import type { RunRate, ScenarioBundle, SnapshotState } from "./api";
import {
  assembleTownRenderData,
  createDynamicTownLayers,
  createStaticTownLayers,
  type TownFeature,
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
}>();

const emit = defineEmits<{
  (event: "select-feature", featureId: string): void;
}>();

const mapHost = ref<HTMLDivElement | null>(null);
const renderError = ref<string | null>(null);
let deck: Deck<OrthographicView> | null = null;
let resizeObserver: ResizeObserver | null = null;
let renderData: TownRenderData | null = null;
let staticLayers: Layer[] = [];
const viewZoom = ref(0);

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
      `关联线路：${road.routeCount.toLocaleString("zh-CN")} 条`,
      ...(road.fromName && road.toName ? [`主要线路：${road.fromName} → ${road.toName}`] : []),
      `关联人流：${Math.round(road.peopleCount).toLocaleString("zh-CN")} 人在途`,
      `人流本 tick：出发 ${Math.round(road.peopleDeparted).toLocaleString("zh-CN")} / 到达 ${Math.round(road.peopleArrived).toLocaleString("zh-CN")}`,
      `关联车流：${Math.round(road.vehicleCount).toLocaleString("zh-CN")} 辆在途`,
      `车流本 tick：出发 ${Math.round(road.vehicleDeparted).toLocaleString("zh-CN")} / 到达 ${Math.round(road.vehicleArrived).toLocaleString("zh-CN")}`,
    ].join("\n");
  }
  return object.name;
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
  if (rebuildStatic || (props.bundle && !renderData)) {
    renderData = props.bundle ? assembleTownRenderData(props.bundle) : null;
    staticLayers = renderData ? createStaticTownLayers(renderData, props.selectedFeatureId, props.visibility) : [];
  }
  const viewState = refit && renderData ? fittedViewState(renderData) : null;
  if (viewState) viewZoom.value = viewState.zoom;
  const landmarkLayers = staticLayers.filter((layer) => layer.id === "landmark-symbols" || layer.id === "landmark-labels");
  const baseStaticLayers = staticLayers.filter((layer) => layer.id !== "landmark-symbols" && layer.id !== "landmark-labels");
  const dynamicLayers = props.bundle
    ? createDynamicTownLayers(props.bundle, props.snapshot, props.selectedFeatureId, undefined, props.visibility)
    : [];
  const particleLayers = dynamicLayers.filter((layer) => layer.id === "people-flow-markers" || layer.id === "vehicle-flow-markers");
  const baseDynamicLayers = dynamicLayers.filter((layer) => layer.id !== "people-flow-markers" && layer.id !== "vehicle-flow-markers");
  deck.setProps({
    layers: [...baseStaticLayers, ...baseDynamicLayers, ...landmarkLayers, ...particleLayers],
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
    useDevicePixels: true,
    pickingRadius: 4,
    getCursor: ({ isDragging, isHovering }) => isDragging ? "grabbing" : isHovering ? "pointer" : "grab",
    onViewStateChange: ({ viewState }) => {
      if (typeof viewState.zoom === "number") viewZoom.value = viewState.zoom;
    },
    getTooltip: ({ object }: PickingInfo<TownFeature>) => object ? {
      text: tooltipText(object),
      style: {
        color: "#3f3b38",
        backgroundColor: "rgba(237, 233, 222, 0.96)",
        border: "1px solid rgba(63, 61, 56, 0.35)",
        borderRadius: "2px",
        fontSize: "11px",
      },
    } : null,
    onClick: ({ object }: PickingInfo<TownFeature>) => {
      if (object) emit("select-feature", (object as TownFeature & { sourceId?: string }).sourceId ?? object.id);
    },
    onError: (error) => {
      renderError.value = error instanceof Error ? error.message : "WebGL renderer failed";
    },
  });
  resizeObserver = new ResizeObserver(() => deck?.redraw("container resized"));
  resizeObserver.observe(mapHost.value);
  updateLayers(true);
});

onUnmounted(() => {
  resizeObserver?.disconnect();
  deck?.finalize();
  deck = null;
  staticLayers = [];
  renderData = null;
});

watch(() => props.bundle, () => updateLayers(true, true));
watch(() => props.selectedFeatureId, () => updateLayers(false, true));
watch(() => props.snapshot?.tick, () => updateLayers(false));
watch(() => props.visibility, () => updateLayers(false, true), { deep: true });
</script>

<template>
  <div ref="mapHost" class="city-map" aria-label="城镇流量地图">
    <div v-if="!bundle" class="map-empty">暂无场景</div>
    <div v-if="renderError" class="map-render-error" role="alert">{{ renderError }}</div>
    <div class="map-legend map-legend--static" aria-label="地图图例">
      <span v-if="visibility.walls"><i class="legend-line legend-line--wall"></i>城墙</span>
      <span v-if="visibility.roads"><i class="legend-line legend-line--road"></i>街道</span>
      <span v-if="visibility.buildings"><i class="legend-building"></i>建筑</span>
      <span v-if="visibility.landmarks"><i class="legend-landmark"></i>地标</span>
      <span v-if="visibility.people"><i class="legend-dot legend-dot--people"></i>人流</span>
      <span v-if="visibility.vehicles"><i class="legend-diamond legend-diamond--vehicle"></i>车流</span>
      <span v-if="visibility.heat"><i class="legend-heat"></i>热力</span>
    </div>
    <div class="map-scale" aria-label="地图比例尺">
      <span class="map-scale__line" :style="{ width: `${scaleWidth}px` }"></span>
      <strong>{{ scaleLabel }}</strong>
    </div>
    <div class="map-compass" aria-label="指北针">
      <span>N</span>
      <i class="map-compass__vertical"></i>
      <i class="map-compass__horizontal"></i>
    </div>
    <div v-if="bundle" class="map-source">{{ bundle.town_skeleton ? "RADIAL-V1" : "LEGACY" }}</div>
    <div v-if="snapshot" class="map-stamp">T+{{ snapshot.tick.toString().padStart(4, "0") }}</div>
  </div>
</template>
