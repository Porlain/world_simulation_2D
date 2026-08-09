<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import {
  allianceFlowPoint,
  alliancePolygon,
  alliancePath,
  type AllianceModel,
  type AllianceSettlement,
} from "./alliance";

const props = defineProps<{
  alliance: AllianceModel;
  selectedId: string | null;
  theme: "pearl" | "night";
  density: number;
  running: boolean;
  runRate: number;
}>();

const emit = defineEmits<{
  (event: "select-settlement", settlement: AllianceSettlement): void;
}>();

const animationTick = ref(0);
const compactView = ref(false);
let animationTimer: number | null = null;

const mapViewBox = computed(() => compactView.value ? "0 0 950 1000" : "0 0 1600 1000");

const flowDots = computed(() => props.alliance.roads.flatMap((road, roadIndex) => {
  const dots = Math.min(5, Math.max(1, Math.ceil((road.people + road.vehicles) / 700 * props.density)));
  return Array.from({ length: dots }, (_, index) => {
    const progress = animationTick.value / (road.kind === "local" ? 55 : 85)
      + (index + 1) / (dots + 1)
      + roadIndex * 0.071;
    const position = allianceFlowPoint(road.path, progress);
    return {
      id: `${road.id}-${index}`,
      position,
      kind: index % 4 === 0 ? "vehicle" : "people",
    };
  });
}));

function settlementRadius(settlement: AllianceSettlement): number {
  return settlement.kind === "capital" ? 16 : settlement.kind === "town" ? 10 : 5;
}

function settlementClass(settlement: AllianceSettlement): string {
  return `alliance-settlement alliance-settlement--${settlement.kind}${props.selectedId === settlement.id ? " is-selected" : ""}`;
}

onMounted(() => {
  const updateViewport = () => { compactView.value = window.innerWidth < 900; };
  updateViewport();
  window.addEventListener("resize", updateViewport);
  animationTimer = window.setInterval(() => {
    if (props.running) animationTick.value += props.runRate;
  }, 650);
  onUnmounted(() => window.removeEventListener("resize", updateViewport));
});

onUnmounted(() => {
  if (animationTimer !== null) window.clearInterval(animationTimer);
});
</script>

<template>
  <div class="alliance-map" :class="`alliance-map--${theme}`">
    <svg class="alliance-map__svg" :viewBox="mapViewBox" role="img" aria-label="人类联盟势力范围地图">
      <defs>
        <pattern id="alliance-grid" width="48" height="48" patternUnits="userSpaceOnUse">
          <path d="M 48 0 L 0 0 0 48" class="alliance-grid-line" fill="none" />
        </pattern>
        <pattern id="alliance-mountain-hatch" width="42" height="30" patternUnits="userSpaceOnUse">
          <rect width="42" height="30" class="alliance-mountain-hatch__ground" />
          <path d="M2 27 L13 9 L24 27 M18 27 L30 4 L40 27" class="alliance-mountain-hatch__ridge" />
        </pattern>
        <pattern id="alliance-land-texture" width="36" height="36" patternUnits="userSpaceOnUse">
          <rect width="36" height="36" class="alliance-land-texture__ground" />
          <path d="M0 9 L36 3 M-5 26 L28 18 M17 38 L42 31" class="alliance-land-texture__grain" />
          <circle cx="8" cy="18" r="1.3" class="alliance-land-texture__speck" />
          <circle cx="29" cy="28" r="1" class="alliance-land-texture__speck" />
        </pattern>
        <clipPath id="alliance-land-clip">
          <polygon v-for="(landmass, index) in alliance.landmasses" :key="`land-clip-${index}`" :points="alliancePolygon(landmass)" />
        </clipPath>
        <clipPath id="alliance-territory-clip">
          <polygon :points="alliancePolygon(alliance.territory)" />
        </clipPath>
      </defs>
      <rect x="0" y="0" width="1600" height="1000" class="alliance-map__ground" />
      <image x="0" y="0" width="1600" height="1000" href="/assets/ocean-texture.jpg" preserveAspectRatio="xMidYMid slice" class="alliance-ocean-texture" aria-hidden="true" />
      <rect x="0" y="0" width="1600" height="1000" class="alliance-map__grid" />

      <g class="alliance-landmasses" aria-label="陆地">
        <polygon v-for="(landmass, index) in alliance.landmasses" :key="`landmass-${index}`" :points="alliancePolygon(landmass)" class="alliance-landmass" />
      </g>

      <g class="alliance-territory" aria-label="人类联盟控制区">
        <polygon :points="alliancePolygon(alliance.territory)" class="alliance-territory__fill" />
        <text x="115" y="155" class="alliance-territory__label">人类联盟控制区</text>
      </g>

      <g class="alliance-latitudes" clip-path="url(#alliance-land-clip)">
        <rect v-for="band in alliance.bands" :key="band.id" x="0" :y="band.y0" width="1600" :height="band.y1 - band.y0" :class="`alliance-band alliance-band--${band.kind}`" />
        <text v-for="band in alliance.bands" :key="`${band.id}-label`" x="34" :y="(band.y0 + band.y1) / 2" class="alliance-band-label">{{ band.label }}</text>
        <path d="M0 500 L1600 500" class="alliance-equator" />
        <text x="1320" y="492" class="alliance-equator-label">赤道</text>
      </g>

      <g class="alliance-influence-ranges" aria-label="主城辐射范围" clip-path="url(#alliance-territory-clip)">
        <circle
          v-for="(capital, index) in alliance.settlements.filter((item) => item.kind === 'capital')"
          :key="`${capital.id}-influence`"
          :cx="capital.position[0]"
          :cy="capital.position[1]"
          :r="capital.influenceRadius ?? 140"
          :class="`alliance-influence alliance-influence--${index}`"
        />
      </g>

      <g class="alliance-mountains" aria-label="山脉">
        <polygon v-for="(mountain, index) in alliance.mountains" :key="`mountain-${index}`" :points="alliancePolygon(mountain)" class="alliance-mountain" />
      </g>
      <g class="alliance-rivers" aria-label="河流">
        <path v-for="(river, index) in alliance.rivers" :key="`river-${index}`" :d="alliancePath(river)" class="alliance-river" />
      </g>
      <g class="alliance-lakes" aria-label="湖泊">
        <polygon v-for="(lake, index) in alliance.lakes" :key="`lake-${index}`" :points="alliancePolygon(lake)" class="alliance-lake" />
      </g>

      <g class="alliance-roads" aria-label="聚落交通">
        <path v-for="road in alliance.roads" :key="road.id" :d="alliancePath(road.path)" :class="`alliance-road alliance-road--${road.kind}`" />
      </g>
      <g class="alliance-flow" aria-label="联盟交通流">
        <circle v-for="dot in flowDots" :key="dot.id" :cx="dot.position[0]" :cy="dot.position[1]" :class="`alliance-flow-dot alliance-flow-dot--${dot.kind}`" r="3.8" />
      </g>

      <g class="alliance-settlements" aria-label="聚落">
        <g v-for="settlement in alliance.settlements" :key="settlement.id" :class="settlementClass(settlement)" role="button" tabindex="0" @click="emit('select-settlement', settlement)" @keydown.enter="emit('select-settlement', settlement)">
          <title>{{ settlement.name }} · {{ settlement.kind === "capital" ? "主城" : settlement.kind === "town" ? "城镇" : "村庄" }} · {{ settlement.population.toLocaleString("zh-CN") }} 人</title>
          <circle :cx="settlement.position[0]" :cy="settlement.position[1]" :r="settlementRadius(settlement)" class="alliance-settlement__halo" />
          <circle :cx="settlement.position[0]" :cy="settlement.position[1]" :r="settlementRadius(settlement) * 0.58" class="alliance-settlement__core" />
          <text :x="settlement.position[0] + settlementRadius(settlement) + 8" :y="settlement.position[1] + 4" class="alliance-settlement__label">{{ settlement.name }}</text>
        </g>
      </g>
    </svg>

    <div class="alliance-map__legend" aria-label="联盟地图图例">
      <span><i class="alliance-legend-swatch alliance-legend-swatch--capital"></i>主城 {{ alliance.settlements.filter((item) => item.kind === "capital").length }}</span>
      <span><i class="alliance-legend-swatch alliance-legend-swatch--town"></i>城镇 {{ alliance.settlements.filter((item) => item.kind === "town").length }}</span>
      <span><i class="alliance-legend-swatch alliance-legend-swatch--village"></i>村庄 {{ alliance.settlements.filter((item) => item.kind === "village").length }}</span>
      <span><i class="alliance-legend-line alliance-legend-line--river"></i>河流</span>
      <span><i class="alliance-legend-swatch alliance-legend-swatch--lake"></i>湖泊</span>
      <span><i class="alliance-legend-line alliance-legend-line--road"></i>联盟道路</span>
      <span><i class="alliance-legend-line alliance-legend-line--influence"></i>主城辐射范围</span>
    </div>
  </div>
</template>

<style scoped>
.alliance-map {
  position: absolute;
  inset: 0 calc(var(--inspector-width) + var(--resizer-size)) 0 calc(var(--rail-width) + var(--resizer-size));
  overflow: hidden;
  background: #0b2b31;
}

.alliance-map__svg {
  display: block;
  width: 100%;
  height: 100%;
  user-select: none;
}

.alliance-map__ground { fill: #0b2b31; }
.alliance-ocean-texture { opacity: 0.2; mix-blend-mode: screen; }
.alliance-map__grid { fill: url("#alliance-grid"); opacity: 0.24; }
.alliance-grid-line { stroke: #8caea1; stroke-width: 1; opacity: 0.14; }
.alliance-landmass { fill: url("#alliance-land-texture"); stroke: #9ab28e; stroke-width: 2.2; opacity: 0.92; }
.alliance-land-texture__ground { fill: #3f6353; }
.alliance-land-texture__grain { fill: none; stroke: #79977a; stroke-width: 1; opacity: 0.28; }
.alliance-land-texture__speck { fill: #aec18e; opacity: 0.36; }
.alliance-band { opacity: 0.22; }
.alliance-band--polar { fill: #b6d7d2; opacity: 0.16; }
.alliance-band--cold { fill: #4f8c82; }
.alliance-band--temperate { fill: #477b68; }
.alliance-band--equatorial { fill: #8b9560; opacity: 0.18; }
.alliance-band-label { fill: #d7e5d8; font: 600 15px "Noto Sans SC Variable", sans-serif; letter-spacing: 1px; opacity: 0.64; }
.alliance-equator { stroke: #d7bd6a; stroke-width: 2; stroke-dasharray: 9 10; opacity: 0.8; }
.alliance-equator-label { fill: #efd789; font: 700 14px "Noto Sans SC Variable", sans-serif; }
.alliance-territory__fill { fill: #c5a854; fill-opacity: 0.12; stroke: #d9bb66; stroke-width: 3; stroke-dasharray: 12 10; }
.alliance-territory__label { fill: #f1d58a; font: 700 19px "Noto Sans SC Variable", sans-serif; letter-spacing: 1px; paint-order: stroke; stroke: #173235; stroke-width: 6px; }
.alliance-influence { stroke-width: 2.5; stroke-dasharray: 12 10; opacity: 0.9; }
.alliance-influence--0 { fill: #c8a34e; fill-opacity: 0.08; stroke: #e7c86d; }
.alliance-influence--1 { fill: #6fb5a0; fill-opacity: 0.07; stroke: #9bd4bc; }
.alliance-influence--2 { fill: #8a9bc2; fill-opacity: 0.07; stroke: #b6c7e5; }
.alliance-influence--3 { fill: #c97e69; fill-opacity: 0.07; stroke: #e1a28c; }
.alliance-influence--4 { fill: #9c8bc5; fill-opacity: 0.07; stroke: #c5b4e2; }

.alliance-mountain { fill: url("#alliance-mountain-hatch"); stroke: #8eaa92; stroke-width: 2; opacity: 0.9; }
.alliance-mountain-hatch__ground { fill: #314b47; }
.alliance-mountain-hatch__ridge { fill: none; stroke: #779182; stroke-width: 1.6; opacity: 0.7; }
.alliance-river { fill: none; stroke: #73c4cd; stroke-width: 11; stroke-linecap: round; opacity: 0.72; }
.alliance-lake { fill: #2e7e8a; stroke: #8fd1d0; stroke-width: 2; opacity: 0.82; }
.alliance-road { fill: none; stroke-linecap: round; stroke-linejoin: round; }
.alliance-road--imperial { stroke: #e0bc70; stroke-width: 9; opacity: 0.82; }
.alliance-road--regional { stroke: #b3a77f; stroke-width: 5; opacity: 0.72; }
.alliance-road--local { stroke: #879c8d; stroke-width: 2.5; opacity: 0.62; }
.alliance-flow-dot { stroke: #102326; stroke-width: 1.5; }
.alliance-flow-dot--people { fill: #8be2bd; }
.alliance-flow-dot--vehicle { fill: #79b8e8; }

.alliance-settlement { cursor: pointer; outline: none; }
.alliance-settlement__halo { fill: #163d40; stroke: #dbe3c5; stroke-width: 2; }
.alliance-settlement__core { fill: #e5b957; stroke: #142b2e; stroke-width: 2; }
.alliance-settlement--town .alliance-settlement__core { fill: #9fc49c; }
.alliance-settlement--village .alliance-settlement__core { fill: #d6d4a3; }
.alliance-settlement__label { fill: #edf2dd; font: 700 18px "Noto Sans SC Variable", sans-serif; paint-order: stroke; stroke: #132e31; stroke-width: 5px; stroke-linejoin: round; }
.alliance-settlement--village .alliance-settlement__label { font-size: 13px; font-weight: 500; }
.alliance-settlement:hover .alliance-settlement__halo,
.alliance-settlement:focus .alliance-settlement__halo,
.alliance-settlement.is-selected .alliance-settlement__halo { stroke: #ffd579; stroke-width: 4; }

.alliance-map__legend {
  position: absolute;
  left: 24px;
  bottom: 24px;
  display: flex;
  flex-wrap: wrap;
  gap: 12px 18px;
  padding: 11px 14px;
  color: #dae8d9;
  background: rgba(13, 43, 47, 0.9);
  border: 1px solid rgba(193, 213, 185, 0.24);
  font-size: 12px;
}
.alliance-legend-swatch, .alliance-legend-line { display: inline-block; vertical-align: middle; margin-right: 5px; }
.alliance-legend-swatch { width: 9px; height: 9px; border-radius: 50%; border: 2px solid #dbe3c5; background: #e5b957; }
.alliance-legend-swatch--town { background: #9fc49c; }
.alliance-legend-swatch--village { background: #d6d4a3; }
.alliance-legend-swatch--lake { background: #2e7e8a; border-color: #8fd1d0; }
.alliance-legend-line { width: 20px; height: 3px; background: #73c4cd; }
.alliance-legend-line--road { background: #e0bc70; }
.alliance-legend-line--influence { height: 0; border-top: 2px dashed #e7c86d; background: transparent; }

@media (max-width: 899px) {
  .alliance-map { inset: 0; }
  .alliance-map__legend { left: 12px; right: 12px; bottom: 12px; gap: 8px 12px; font-size: 10px; }
  .alliance-settlement__label { font-size: 13px; }
  .alliance-settlement--village .alliance-settlement__label { font-size: 10px; }
}

@media (min-width: 900px) and (max-width: 1199px) {
  .alliance-map { inset-inline-end: 0; }
}
</style>
