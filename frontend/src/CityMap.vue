<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { Deck, OrthographicView, type PickingInfo } from "@deck.gl/core";
import type { RunRate, ScenarioBundle, SnapshotState } from "./api";
import {
  assembleTownRenderData,
  createStaticTownLayers,
  type TownFeature,
  type TownRenderData,
} from "./townLayers";

const props = defineProps<{
  bundle: ScenarioBundle | null;
  snapshot: SnapshotState | null;
  runRate: RunRate;
  running: boolean;
  selectedFeatureId: string | null;
}>();

const emit = defineEmits<{
  (event: "select-feature", featureId: string): void;
}>();

const mapHost = ref<HTMLDivElement | null>(null);
const renderError = ref<string | null>(null);
let deck: Deck<OrthographicView> | null = null;
let resizeObserver: ResizeObserver | null = null;
let renderData: TownRenderData | null = null;

function fittedViewState(data: TownRenderData) {
  const host = mapHost.value?.getBoundingClientRect();
  const width = Math.max(320, host?.width ?? 900);
  const height = Math.max(240, host?.height ?? 600);
  const sceneWidth = Math.max(1, data.bounds[2] - data.bounds[0]);
  const sceneHeight = Math.max(1, data.bounds[3] - data.bounds[1]);
  const zoom = Math.log2(Math.max(0.01, Math.min((width - 80) / sceneWidth, (height - 80) / sceneHeight)));
  return {
    target: [(data.bounds[0] + data.bounds[2]) / 2, (data.bounds[1] + data.bounds[3]) / 2, 0] as [number, number, number],
    zoom,
    minZoom: zoom - 2,
    maxZoom: zoom + 7,
  };
}

function updateLayers(refit = false) {
  if (!deck) return;
  renderData = props.bundle ? assembleTownRenderData(props.bundle) : null;
  deck.setProps({
    layers: renderData ? createStaticTownLayers(renderData, props.selectedFeatureId) : [],
    ...(refit && renderData ? { initialViewState: fittedViewState(renderData) } : {}),
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
    getTooltip: ({ object }: PickingInfo<TownFeature>) => object ? {
      text: object.name,
      style: {
        color: "#d9f2f3",
        backgroundColor: "rgba(4, 19, 27, 0.94)",
        border: "1px solid rgba(89, 211, 224, 0.55)",
        borderRadius: "2px",
        fontSize: "11px",
      },
    } : null,
    onClick: ({ object }: PickingInfo<TownFeature>) => {
      if (object) emit("select-feature", object.id);
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
});

watch(() => props.bundle, () => updateLayers(true));
watch(() => props.selectedFeatureId, () => updateLayers(false));
</script>

<template>
  <div ref="mapHost" class="city-map" aria-label="城镇流量地图">
    <div v-if="!bundle" class="map-empty">暂无场景</div>
    <div v-if="renderError" class="map-render-error" role="alert">{{ renderError }}</div>
    <div class="map-legend map-legend--static" aria-label="地图图例">
      <span><i class="legend-line legend-line--wall"></i>城墙</span>
      <span><i class="legend-line legend-line--road"></i>街道</span>
      <span><i class="legend-building"></i>建筑</span>
      <span><i class="legend-landmark"></i>地标</span>
    </div>
    <div v-if="bundle" class="map-source">{{ bundle.town_skeleton ? "RADIAL-V1" : "LEGACY" }}</div>
    <div v-if="snapshot" class="map-stamp">T+{{ snapshot.tick.toString().padStart(4, "0") }}</div>
  </div>
</template>
