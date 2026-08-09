<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { LocateFixed, Minus, Plus } from "lucide-vue-next";
import {
  allianceFlowPoint,
  alliancePolygon,
  alliancePath,
  type AllianceModel,
  type AllianceSettlement,
} from "./alliance";
import type { Coordinate } from "./api";

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
  (event: "open-settlement", settlement: AllianceSettlement): void;
}>();

const animationTick = ref(0);
const compactView = ref(false);
const zoomFactor = ref(1);
const viewCenter = ref<[number, number]>([800, 500]);
const isPanning = ref(false);
const dragMoved = ref(false);
let panPointerId: number | null = null;
let lastPointerPosition: [number, number] | null = null;
let animationTimer: number | null = null;

const compactViewBox = computed(() => {
  const xs = props.alliance.territory.map(([x]) => x);
  const ys = props.alliance.territory.map(([, y]) => y);
  const padding = 60;
  const x = Math.max(0, Math.min(...xs) - padding);
  const y = Math.max(0, Math.min(...ys) - padding);
  const right = Math.min(1600, Math.max(...xs) + padding);
  const bottom = Math.min(1000, Math.max(...ys) + padding);
  return `${x} ${y} ${right - x} ${bottom - y}`;
});

const mapViewBox = computed(() => {
  const [baseX, baseY, baseWidth, baseHeight] = compactView.value
    ? compactViewBox.value.split(" ").map(Number)
    : [0, 0, 1600, 1000];
  const width = Math.min(baseWidth, baseWidth / zoomFactor.value);
  const height = Math.min(baseHeight, baseHeight / zoomFactor.value);
  const x = Math.max(baseX, Math.min(baseX + baseWidth - width, viewCenter.value[0] - width / 2));
  const y = Math.max(baseY, Math.min(baseY + baseHeight - height, viewCenter.value[1] - height / 2));
  return `${x} ${y} ${width} ${height}`;
});

const zoomLabel = computed(() => `${Math.round(zoomFactor.value * 100)}%`);
const territoryLabelPosition = computed(() => [
  Math.min(...props.alliance.territory.map(([x]) => x)) + 4,
  Math.max(36, Math.min(...props.alliance.territory.map(([, y]) => y)) - 18),
]);

function viewBoxNumbers(): [number, number, number, number] {
  return mapViewBox.value.split(" ").map(Number) as [number, number, number, number];
}

function clampZoom(value: number): number {
  return Math.max(1, Math.min(8, value));
}

function svgPoint(event: PointerEvent | WheelEvent): [number, number] | null {
  const svg = event.currentTarget instanceof SVGElement ? event.currentTarget : null;
  if (!svg) return null;
  const rect = svg.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  const [x, y, width, height] = viewBoxNumbers();
  return [
    x + ((event.clientX - rect.left) / rect.width) * width,
    y + ((event.clientY - rect.top) / rect.height) * height,
  ];
}

function applyZoom(nextZoom: number, anchor?: [number, number]): void {
  const before = anchor;
  zoomFactor.value = clampZoom(nextZoom);
  if (!before) return;
  const [x, y, width, height] = viewBoxNumbers();
  const cursorRatioX = (before[0] - x) / width;
  const cursorRatioY = (before[1] - y) / height;
  viewCenter.value = [
    before[0] - (cursorRatioX - 0.5) * width,
    before[1] - (cursorRatioY - 0.5) * height,
  ];
}

function zoomIn(): void { applyZoom(zoomFactor.value * 1.25); }
function zoomOut(): void { applyZoom(zoomFactor.value / 1.25); }
function resetView(): void {
  zoomFactor.value = 1;
  if (compactView.value) {
    const [x, y, width, height] = compactViewBox.value.split(" ").map(Number);
    viewCenter.value = [x + width / 2, y + height / 2];
  } else {
    viewCenter.value = [800, 500];
  }
}

function handleWheel(event: WheelEvent): void {
  const anchor = svgPoint(event);
  applyZoom(zoomFactor.value * (event.deltaY < 0 ? 1.2 : 1 / 1.2), anchor ?? undefined);
}

function handlePointerDown(event: PointerEvent): void {
  if (event.button !== 0 && event.button !== 1) return;
  const point = svgPoint(event);
  if (!point) return;
  panPointerId = event.pointerId;
  lastPointerPosition = [event.clientX, event.clientY];
  dragMoved.value = false;
  isPanning.value = true;
  (event.currentTarget as SVGElement).setPointerCapture(event.pointerId);
}

function handlePointerMove(event: PointerEvent): void {
  if (!isPanning.value || event.pointerId !== panPointerId || !lastPointerPosition) return;
  const svg = event.currentTarget as SVGElement;
  const rect = svg.getBoundingClientRect();
  const [, , width, height] = viewBoxNumbers();
  const dx = event.clientX - lastPointerPosition[0];
  const dy = event.clientY - lastPointerPosition[1];
  if (Math.abs(dx) + Math.abs(dy) > 3) dragMoved.value = true;
  viewCenter.value = [
    viewCenter.value[0] - (dx / rect.width) * width,
    viewCenter.value[1] - (dy / rect.height) * height,
  ];
  lastPointerPosition = [event.clientX, event.clientY];
}

function endPointer(event: PointerEvent): void {
  if (event.pointerId !== panPointerId) return;
  isPanning.value = false;
  panPointerId = null;
  lastPointerPosition = null;
  if ((event.currentTarget as SVGElement).hasPointerCapture(event.pointerId)) {
    (event.currentTarget as SVGElement).releasePointerCapture(event.pointerId);
  }
}

function handleSettlementClick(settlement: AllianceSettlement): void {
  if (dragMoved.value) return;
  emit("select-settlement", settlement);
}

function handleSettlementOpen(settlement: AllianceSettlement): void {
  if (dragMoved.value) return;
  emit("open-settlement", settlement);
}

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

// Keep the climate field deterministic: the same world seed always produces the same biome mix.
type TerrainPatchKind = "ice" | "tundra" | "taiga" | "forest" | "meadow" | "steppe" | "desert" | "savanna" | "rainforest" | "wetland" | "rock";

interface TerrainPatch {
  id: string;
  cx: number;
  cy: number;
  rx: number;
  ry: number;
  kind: TerrainPatchKind;
  rotation: number;
  opacity: number;
}

function terrainUnit(seed: number, key: string): number {
  let hash = (seed ^ 0x9e3779b9) >>> 0;
  for (const character of key) hash = Math.imul(hash ^ character.charCodeAt(0), 0x85ebca6b);
  hash ^= hash >>> 13;
  hash = Math.imul(hash, 0xc2b2ae35);
  return ((hash ^ (hash >>> 16)) >>> 0) / 0xffffffff;
}

function terrainBounds(points: Coordinate[]): { x0: number; x1: number; y0: number; y1: number } {
  const xs = points.map(([x]) => x);
  const ys = points.map(([, y]) => y);
  return { x0: Math.min(...xs), x1: Math.max(...xs), y0: Math.min(...ys), y1: Math.max(...ys) };
}

function climateSafeKind(kind: TerrainPatchKind, y: number): TerrainPatchKind {
  const polar = y < 150 || y > 850;
  const cold = y < 315 || y > 685;
  if (kind === "desert" && polar) return "tundra";
  if (kind === "desert" && cold) return "steppe";
  if (kind === "rainforest" && cold) return "forest";
  if (kind === "savanna" && polar) return "steppe";
  if (kind === "wetland" && polar) return "tundra";
  return kind;
}

const terrainPatches = computed<TerrainPatch[]>(() => {
  const recipes: Array<{ kind: TerrainPatchKind; x: number; y: number; rx: number; ry: number }> = [
    { kind: "forest", x: 0.24, y: 0.24, rx: 0.34, ry: 0.34 },
    { kind: "desert", x: 0.70, y: 0.39, rx: 0.31, ry: 0.24 },
    { kind: "wetland", x: 0.48, y: 0.69, rx: 0.29, ry: 0.25 },
    { kind: "rock", x: 0.82, y: 0.18, rx: 0.24, ry: 0.27 },
  ];
  return props.alliance.landmasses.flatMap((landmass, landmassIndex) => {
    const bounds = terrainBounds(landmass);
    const width = Math.max(1, bounds.x1 - bounds.x0);
    const height = Math.max(1, bounds.y1 - bounds.y0);
    return recipes.map((recipe, recipeIndex) => {
      const jitterX = (terrainUnit(props.alliance.seed, `${landmassIndex}:x:${recipeIndex}`) - 0.5) * 0.22;
      const jitterY = (terrainUnit(props.alliance.seed, `${landmassIndex}:y:${recipeIndex}`) - 0.5) * 0.18;
      const cx = bounds.x0 + width * Math.max(0.08, Math.min(0.92, recipe.x + jitterX));
      const cy = bounds.y0 + height * Math.max(0.08, Math.min(0.92, recipe.y + jitterY));
      const variantKind = landmassIndex === 2 && recipeIndex === 0 ? "rainforest" : recipe.kind;
      return {
        id: `terrain-patch-${landmassIndex}-${recipeIndex}`,
        cx,
        cy,
        rx: width * recipe.rx * (0.86 + terrainUnit(props.alliance.seed, `${landmassIndex}:rx:${recipeIndex}`) * 0.2),
        ry: height * recipe.ry * (0.86 + terrainUnit(props.alliance.seed, `${landmassIndex}:ry:${recipeIndex}`) * 0.2),
        kind: climateSafeKind(variantKind, cy),
        rotation: (terrainUnit(props.alliance.seed, `${landmassIndex}:rotation:${recipeIndex}`) - 0.5) * 28,
        opacity: 0.44 + terrainUnit(props.alliance.seed, `${landmassIndex}:opacity:${recipeIndex}`) * 0.16,
      };
    });
  });
});

function landmassVariant(index: number): number {
  const seedOffset = Math.floor(terrainUnit(props.alliance.seed, "landmass-texture-offset") * 4);
  return (index + seedOffset) % 4;
}

function settlementRadius(settlement: AllianceSettlement): number {
  return settlement.kind === "capital" ? 16 : settlement.kind === "town" ? 10 : 5;
}

function settlementClass(settlement: AllianceSettlement): string {
  return `alliance-settlement alliance-settlement--${settlement.kind}${props.selectedId === settlement.id ? " is-selected" : ""}`;
}

function shouldShowSettlementLabel(settlement: AllianceSettlement): boolean {
  if (settlement.kind === "capital") return true;
  if (settlement.kind === "town") return zoomFactor.value >= 1.4;
  return zoomFactor.value >= 2.5;
}

onMounted(() => {
  const updateViewport = () => {
    const nextCompact = window.innerWidth < 900;
    compactView.value = nextCompact;
    if (nextCompact) {
      const [x, y, width, height] = compactViewBox.value.split(" ").map(Number);
      viewCenter.value = [x + width / 2, y + height / 2];
    } else {
      viewCenter.value = [800, 500];
    }
  };
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
    <svg
      class="alliance-map__svg"
      :class="{ 'is-panning': isPanning }"
      :viewBox="mapViewBox"
      role="img"
      aria-label="人类联盟势力范围地图"
      @wheel.prevent="handleWheel"
      @pointerdown="handlePointerDown"
      @pointermove="handlePointerMove"
      @pointerup="endPointer"
      @pointercancel="endPointer"
    >
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
        <pattern id="alliance-land-texture-dry" width="82" height="82" patternUnits="userSpaceOnUse">
          <rect width="82" height="82" class="alliance-land-texture__dry-ground" />
          <path d="M-5 18 C18 7 32 25 58 12 S79 5 88 15 M-8 55 C11 42 36 62 58 47 S79 41 90 52" class="alliance-land-texture__dry-ridge" />
          <path d="M12 70 l7 -4 m24 9 l9 -5 m20 -18 l7 -4" class="alliance-land-texture__dry-speck" />
        </pattern>
        <pattern id="alliance-land-texture-forest" width="74" height="74" patternUnits="userSpaceOnUse">
          <rect width="74" height="74" class="alliance-land-texture__forest-ground" />
          <path d="M4 54 C15 43 22 47 31 34 S48 22 62 28 M-6 20 C10 30 19 18 29 11 S53 4 80 15" class="alliance-land-texture__forest-grain" />
          <circle cx="16" cy="22" r="4" class="alliance-land-texture__canopy" />
          <circle cx="50" cy="50" r="5" class="alliance-land-texture__canopy" />
          <circle cx="63" cy="13" r="2.5" class="alliance-land-texture__canopy-small" />
        </pattern>
        <pattern id="alliance-land-texture-rock" width="88" height="88" patternUnits="userSpaceOnUse">
          <rect width="88" height="88" class="alliance-land-texture__rock-ground" />
          <path d="M-6 65 L23 31 L42 52 L64 17 L94 40 M-10 88 L19 69 L38 83 L72 58 L96 72" class="alliance-land-texture__rock-ridge" />
          <path d="M13 15 l10 8 -13 5 z M58 71 l12 6 -11 6 z" class="alliance-land-texture__rock-facet" />
        </pattern>
        <linearGradient id="alliance-climate-gradient" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="oklch(0.84 0.045 185)" stop-opacity="0.84" />
          <stop offset="0.09" stop-color="oklch(0.68 0.065 163)" stop-opacity="0.56" />
          <stop offset="0.22" stop-color="oklch(0.5 0.095 145)" stop-opacity="0.4" />
          <stop offset="0.37" stop-color="oklch(0.62 0.095 122)" stop-opacity="0.46" />
          <stop offset="0.49" stop-color="oklch(0.66 0.1 82)" stop-opacity="0.56" />
          <stop offset="0.61" stop-color="oklch(0.54 0.115 124)" stop-opacity="0.52" />
          <stop offset="0.76" stop-color="oklch(0.61 0.09 118)" stop-opacity="0.42" />
          <stop offset="0.9" stop-color="oklch(0.69 0.06 160)" stop-opacity="0.54" />
          <stop offset="1" stop-color="oklch(0.84 0.045 185)" stop-opacity="0.84" />
        </linearGradient>
        <radialGradient id="alliance-ice-gradient">
          <stop offset="0" stop-color="oklch(0.92 0.025 186)" stop-opacity="0.76" />
          <stop offset="0.55" stop-color="oklch(0.79 0.05 182)" stop-opacity="0.3" />
          <stop offset="1" stop-color="oklch(0.79 0.05 182)" stop-opacity="0" />
        </radialGradient>
        <radialGradient id="alliance-tundra-gradient">
          <stop offset="0" stop-color="oklch(0.7 0.07 155)" stop-opacity="0.66" />
          <stop offset="0.64" stop-color="oklch(0.62 0.065 151)" stop-opacity="0.22" />
          <stop offset="1" stop-color="oklch(0.62 0.065 151)" stop-opacity="0" />
        </radialGradient>
        <radialGradient id="alliance-taiga-gradient">
          <stop offset="0" stop-color="oklch(0.42 0.1 145)" stop-opacity="0.58" />
          <stop offset="0.7" stop-color="oklch(0.44 0.09 145)" stop-opacity="0.18" />
          <stop offset="1" stop-color="oklch(0.44 0.09 145)" stop-opacity="0" />
        </radialGradient>
        <radialGradient id="alliance-forest-gradient">
          <stop offset="0" stop-color="oklch(0.44 0.12 137)" stop-opacity="0.58" />
          <stop offset="0.68" stop-color="oklch(0.5 0.1 132)" stop-opacity="0.18" />
          <stop offset="1" stop-color="oklch(0.5 0.1 132)" stop-opacity="0" />
        </radialGradient>
        <radialGradient id="alliance-meadow-gradient">
          <stop offset="0" stop-color="oklch(0.65 0.1 119)" stop-opacity="0.58" />
          <stop offset="0.7" stop-color="oklch(0.64 0.08 119)" stop-opacity="0.19" />
          <stop offset="1" stop-color="oklch(0.64 0.08 119)" stop-opacity="0" />
        </radialGradient>
        <radialGradient id="alliance-steppe-gradient">
          <stop offset="0" stop-color="oklch(0.7 0.11 81)" stop-opacity="0.62" />
          <stop offset="0.64" stop-color="oklch(0.67 0.08 82)" stop-opacity="0.24" />
          <stop offset="1" stop-color="oklch(0.67 0.08 82)" stop-opacity="0" />
        </radialGradient>
        <radialGradient id="alliance-desert-gradient">
          <stop offset="0" stop-color="oklch(0.73 0.12 74)" stop-opacity="0.78" />
          <stop offset="0.54" stop-color="oklch(0.68 0.1 73)" stop-opacity="0.38" />
          <stop offset="1" stop-color="oklch(0.68 0.1 73)" stop-opacity="0" />
        </radialGradient>
        <radialGradient id="alliance-savanna-gradient">
          <stop offset="0" stop-color="oklch(0.63 0.11 105)" stop-opacity="0.62" />
          <stop offset="0.68" stop-color="oklch(0.61 0.08 105)" stop-opacity="0.2" />
          <stop offset="1" stop-color="oklch(0.61 0.08 105)" stop-opacity="0" />
        </radialGradient>
        <radialGradient id="alliance-rainforest-gradient">
          <stop offset="0" stop-color="oklch(0.4 0.14 145)" stop-opacity="0.7" />
          <stop offset="0.64" stop-color="oklch(0.45 0.11 143)" stop-opacity="0.24" />
          <stop offset="1" stop-color="oklch(0.45 0.11 143)" stop-opacity="0" />
        </radialGradient>
        <radialGradient id="alliance-wetland-gradient">
          <stop offset="0" stop-color="oklch(0.49 0.1 174)" stop-opacity="0.54" />
          <stop offset="0.66" stop-color="oklch(0.52 0.08 171)" stop-opacity="0.18" />
          <stop offset="1" stop-color="oklch(0.52 0.08 171)" stop-opacity="0" />
        </radialGradient>
        <radialGradient id="alliance-rock-gradient">
          <stop offset="0" stop-color="oklch(0.5 0.045 92)" stop-opacity="0.62" />
          <stop offset="0.64" stop-color="oklch(0.48 0.04 93)" stop-opacity="0.2" />
          <stop offset="1" stop-color="oklch(0.48 0.04 93)" stop-opacity="0" />
        </radialGradient>
        <filter id="alliance-terrain-noise" x="-10%" y="-10%" width="120%" height="120%">
          <feTurbulence type="fractalNoise" baseFrequency="0.012 0.026" numOctaves="3" seed="17" />
          <feColorMatrix type="saturate" values="0" />
          <feComponentTransfer>
            <feFuncA type="table" tableValues="0 0.16" />
          </feComponentTransfer>
        </filter>
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
        <polygon v-for="(landmass, index) in alliance.landmasses" :key="`landmass-${index}`" :points="alliancePolygon(landmass)" :class="['alliance-landmass', `alliance-landmass--variant-${landmassVariant(index)}`]" />
      </g>

      <g class="alliance-climate-field" clip-path="url(#alliance-land-clip)" aria-label="气候渐变">
        <rect x="0" y="0" width="1600" height="1000" class="alliance-climate-field__gradient" />
        <rect x="0" y="0" width="1600" height="1000" class="alliance-climate-field__noise" />
        <ellipse cx="800" cy="52" rx="920" ry="185" class="alliance-climate-wash alliance-climate-wash--ice" />
        <ellipse cx="800" cy="948" rx="920" ry="185" class="alliance-climate-wash alliance-climate-wash--ice" />
        <ellipse v-for="patch in terrainPatches" :key="patch.id" :cx="patch.cx" :cy="patch.cy" :rx="patch.rx" :ry="patch.ry" :transform="`rotate(${patch.rotation} ${patch.cx} ${patch.cy})`" :class="['alliance-biome-patch', `alliance-biome-patch--${patch.kind}`]" :style="{ opacity: patch.opacity }" />
      </g>

      <g class="alliance-territory" aria-label="人类联盟控制区">
        <polygon :points="alliancePolygon(alliance.territory)" class="alliance-territory__fill" />
        <text :x="territoryLabelPosition[0]" :y="territoryLabelPosition[1]" class="alliance-territory__label">人类联盟控制区</text>
      </g>

      <g class="alliance-latitudes" clip-path="url(#alliance-land-clip)">
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
        <g v-for="settlement in alliance.settlements" :key="settlement.id" :class="settlementClass(settlement)" role="button" tabindex="0" :aria-label="`${settlement.name}，双击查看街道细节`" @click="handleSettlementClick(settlement)" @dblclick="handleSettlementOpen(settlement)" @keydown.enter="handleSettlementClick(settlement)">
          <title>{{ settlement.name }} · {{ settlement.kind === "capital" ? "主城" : settlement.kind === "town" ? "城镇" : "村庄" }} · {{ settlement.population.toLocaleString("zh-CN") }} 人</title>
          <circle :cx="settlement.position[0]" :cy="settlement.position[1]" :r="settlementRadius(settlement)" class="alliance-settlement__halo" />
          <circle :cx="settlement.position[0]" :cy="settlement.position[1]" :r="settlementRadius(settlement) * 0.58" class="alliance-settlement__core" />
          <text v-if="shouldShowSettlementLabel(settlement)" :x="settlement.position[0] + settlementRadius(settlement) + 8" :y="settlement.position[1] + 4" class="alliance-settlement__label">{{ settlement.name }}</text>
        </g>
      </g>
    </svg>

    <div class="alliance-map__zoom-controls" aria-label="地图缩放">
      <button type="button" aria-label="放大地图" title="放大地图" @click="zoomIn"><Plus :size="16" aria-hidden="true" /></button>
      <span aria-live="polite">{{ zoomLabel }}</span>
      <button type="button" aria-label="缩小地图" title="缩小地图" @click="zoomOut"><Minus :size="16" aria-hidden="true" /></button>
      <button type="button" aria-label="重置地图视野" title="重置地图视野" @click="resetView"><LocateFixed :size="16" aria-hidden="true" /></button>
    </div>

    <div class="alliance-map__legend" aria-label="联盟地图图例">
      <span><i class="alliance-legend-swatch alliance-legend-swatch--capital"></i>主城 {{ alliance.settlements.filter((item) => item.kind === "capital").length }}</span>
      <span><i class="alliance-legend-swatch alliance-legend-swatch--town"></i>城镇 {{ alliance.settlements.filter((item) => item.kind === "town").length }}</span>
      <span><i class="alliance-legend-swatch alliance-legend-swatch--village"></i>村庄 {{ alliance.settlements.filter((item) => item.kind === "village").length }}</span>
      <span><i class="alliance-legend-line alliance-legend-line--river"></i>河流</span>
      <span><i class="alliance-legend-swatch alliance-legend-swatch--lake"></i>湖泊</span>
      <span><i class="alliance-legend-line alliance-legend-line--road"></i>联盟道路</span>
      <span><i class="alliance-legend-line alliance-legend-line--influence"></i>主城辐射范围</span>
      <span><i class="alliance-legend-biome alliance-legend-biome--polar"></i>冻原</span>
      <span><i class="alliance-legend-biome alliance-legend-biome--temperate"></i>温带</span>
      <span><i class="alliance-legend-biome alliance-legend-biome--arid"></i>干旱带</span>
      <span><i class="alliance-legend-biome alliance-legend-biome--equatorial"></i>湿热带</span>
    </div>
  </div>
</template>

<style scoped>
.alliance-map {
  position: absolute;
  inset: 0 calc(var(--inspector-width) + var(--resizer-size)) 0 calc(var(--rail-width) + var(--resizer-size));
  overflow: hidden;
  --terrain-ocean: oklch(0.27 0.055 215);
  --terrain-land: oklch(0.46 0.08 137);
  --terrain-edge: oklch(0.72 0.07 125);
  --terrain-ink: oklch(0.9 0.035 150);
  background: var(--terrain-ocean);
}

.alliance-map__svg {
  display: block;
  width: 100%;
  height: 100%;
  user-select: none;
  cursor: grab;
  touch-action: none;
}
.alliance-map__svg.is-panning { cursor: grabbing; }
.alliance-map__zoom-controls {
  position: absolute;
  top: 18px;
  right: 18px;
  z-index: 4;
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 5px;
  color: #dbe7d7;
  background: rgb(11 43 47 / 86%);
  border: 1px solid rgb(193 213 185 / 28%);
  border-radius: 5px;
  box-shadow: 0 8px 20px rgb(0 0 0 / 18%);
  font: 700 10px ui-monospace, SFMono-Regular, Menlo, monospace;
}
.alliance-map__zoom-controls button {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  padding: 0;
  color: inherit;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 3px;
}
.alliance-map__zoom-controls button:hover,
.alliance-map__zoom-controls button:focus-visible {
  background: rgb(229 185 87 / 16%);
  border-color: rgb(229 185 87 / 48%);
  outline: none;
}
.alliance-map__zoom-controls span { min-width: 38px; text-align: center; }

.alliance-map__ground { fill: var(--terrain-ocean); }
.alliance-ocean-texture { opacity: 0.16; mix-blend-mode: screen; filter: saturate(0.72) contrast(0.88); }
.alliance-map__grid { fill: url("#alliance-grid"); opacity: 0.24; }
.alliance-grid-line { stroke: oklch(0.75 0.055 155); stroke-width: 1; opacity: 0.14; }
.alliance-landmass { stroke: var(--terrain-edge); stroke-width: 2.2; opacity: 0.94; }
.alliance-landmass--variant-0 { fill: url("#alliance-land-texture"); }
.alliance-landmass--variant-1 { fill: url("#alliance-land-texture-dry"); }
.alliance-landmass--variant-2 { fill: url("#alliance-land-texture-forest"); }
.alliance-landmass--variant-3 { fill: url("#alliance-land-texture-rock"); }
.alliance-land-texture__ground { fill: var(--terrain-land); }
.alliance-land-texture__grain { fill: none; stroke: oklch(0.67 0.07 135); stroke-width: 1; opacity: 0.28; }
.alliance-land-texture__speck { fill: oklch(0.8 0.08 112); opacity: 0.36; }
.alliance-land-texture__dry-ground { fill: oklch(0.58 0.09 90); }
.alliance-land-texture__dry-ridge { fill: none; stroke: oklch(0.72 0.08 84); stroke-width: 1.2; opacity: 0.42; }
.alliance-land-texture__dry-speck { fill: none; stroke: oklch(0.8 0.08 76); stroke-width: 2; opacity: 0.42; }
.alliance-land-texture__forest-ground { fill: oklch(0.43 0.1 141); }
.alliance-land-texture__forest-grain { fill: none; stroke: oklch(0.62 0.1 134); stroke-width: 1.1; opacity: 0.36; }
.alliance-land-texture__canopy { fill: oklch(0.35 0.11 143); opacity: 0.55; }
.alliance-land-texture__canopy-small { fill: oklch(0.7 0.09 125); opacity: 0.5; }
.alliance-land-texture__rock-ground { fill: oklch(0.43 0.05 105); }
.alliance-land-texture__rock-ridge { fill: none; stroke: oklch(0.63 0.05 100); stroke-width: 1.6; opacity: 0.42; }
.alliance-land-texture__rock-facet { fill: oklch(0.7 0.05 94); opacity: 0.34; }
.alliance-climate-field { mix-blend-mode: multiply; pointer-events: none; }
.alliance-climate-field__gradient { fill: url("#alliance-climate-gradient"); opacity: 0.72; }
.alliance-climate-field__noise { fill: oklch(0.74 0.025 120); opacity: 0.22; filter: url("#alliance-terrain-noise"); mix-blend-mode: soft-light; }
.alliance-climate-wash { pointer-events: none; }
.alliance-climate-wash--ice { fill: url("#alliance-ice-gradient"); }
.alliance-biome-patch { pointer-events: none; }
.alliance-biome-patch--ice { fill: url("#alliance-ice-gradient"); }
.alliance-biome-patch--tundra { fill: url("#alliance-tundra-gradient"); }
.alliance-biome-patch--taiga { fill: url("#alliance-taiga-gradient"); }
.alliance-biome-patch--forest { fill: url("#alliance-forest-gradient"); }
.alliance-biome-patch--meadow { fill: url("#alliance-meadow-gradient"); }
.alliance-biome-patch--steppe { fill: url("#alliance-steppe-gradient"); }
.alliance-biome-patch--desert { fill: url("#alliance-desert-gradient"); }
.alliance-biome-patch--savanna { fill: url("#alliance-savanna-gradient"); }
.alliance-biome-patch--rainforest { fill: url("#alliance-rainforest-gradient"); }
.alliance-biome-patch--wetland { fill: url("#alliance-wetland-gradient"); }
.alliance-biome-patch--rock { fill: url("#alliance-rock-gradient"); }
.alliance-band-label { fill: var(--terrain-ink); font: 600 15px "Noto Sans SC Variable", sans-serif; letter-spacing: 1px; opacity: 0.66; paint-order: stroke; stroke: var(--terrain-ocean); stroke-width: 4px; }
.alliance-equator { stroke: oklch(0.82 0.12 88); stroke-width: 2; stroke-dasharray: 9 10; opacity: 0.82; }
.alliance-equator-label { fill: oklch(0.9 0.1 88); font: 700 14px "Noto Sans SC Variable", sans-serif; paint-order: stroke; stroke: var(--terrain-ocean); stroke-width: 4px; }
.alliance-territory__fill { fill: oklch(0.76 0.12 82); fill-opacity: 0.12; stroke: oklch(0.84 0.12 84); stroke-width: 3; stroke-dasharray: 12 10; }
.alliance-territory__label { fill: oklch(0.91 0.1 88); font: 700 19px "Noto Sans SC Variable", sans-serif; letter-spacing: 1px; paint-order: stroke; stroke: oklch(0.28 0.055 203); stroke-width: 6px; }
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
.alliance-legend-biome { display: inline-block; width: 20px; height: 7px; margin-right: 5px; border-radius: 2px; }
.alliance-legend-biome--polar { background: linear-gradient(90deg, oklch(0.84 0.045 185), oklch(0.68 0.065 163)); }
.alliance-legend-biome--temperate { background: linear-gradient(90deg, oklch(0.5 0.095 145), oklch(0.62 0.095 122)); }
.alliance-legend-biome--arid { background: linear-gradient(90deg, oklch(0.66 0.1 82), oklch(0.73 0.12 74)); }
.alliance-legend-biome--equatorial { background: linear-gradient(90deg, oklch(0.54 0.115 124), oklch(0.4 0.14 145)); }

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
