<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { LocateFixed, Minus, Plus } from "lucide-vue-next";
import {
  allianceFlowPoint,
  allianceCell,
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

const worldBounds = computed(() => props.alliance.bounds);
const worldCenter = computed(() => [
  worldBounds.value[0] + worldBounds.value[2] / 2,
  worldBounds.value[1] + worldBounds.value[3] / 2,
] as [number, number]);
const equatorPath = computed(() => `M${worldBounds.value[0]} ${worldCenter.value[1]} H${worldBounds.value[0] + worldBounds.value[2]}`);
const equatorLabelPosition = computed(() => [
  worldBounds.value[0] + worldBounds.value[2] - 280,
  worldCenter.value[1] - 8,
] as [number, number]);

const animationTick = ref(0);
const compactView = ref(false);
const zoomFactor = ref(1);
const viewCenter = ref<[number, number]>(worldCenter.value);
const isPanning = ref(false);
const dragMoved = ref(false);
let panPointerId: number | null = null;
let lastPointerPosition: [number, number] | null = null;
let animationTimer: number | null = null;

const compactViewBox = computed(() => {
  const xs = props.alliance.territory.map(([x]) => x);
  const ys = props.alliance.territory.map(([, y]) => y);
  const padding = 60;
  const x = Math.max(worldBounds.value[0], Math.min(...xs) - padding);
  const y = Math.max(worldBounds.value[1], Math.min(...ys) - padding);
  const right = Math.min(worldBounds.value[0] + worldBounds.value[2], Math.max(...xs) + padding);
  const bottom = Math.min(worldBounds.value[1] + worldBounds.value[3], Math.max(...ys) + padding);
  return `${x} ${y} ${right - x} ${bottom - y}`;
});

const mapViewBox = computed(() => {
  const [baseX, baseY, baseWidth, baseHeight] = compactView.value
    ? compactViewBox.value.split(" ").map(Number)
    : [...worldBounds.value];
  const width = Math.min(baseWidth, baseWidth / zoomFactor.value);
  const height = Math.min(baseHeight, baseHeight / zoomFactor.value);
  const x = Math.max(baseX, Math.min(baseX + baseWidth - width, viewCenter.value[0] - width / 2));
  const y = Math.max(baseY, Math.min(baseY + baseHeight - height, viewCenter.value[1] - height / 2));
  return `${x} ${y} ${width} ${height}`;
});

const zoomLabel = computed(() => `${Math.round(zoomFactor.value * 100)}%`);
const detailLevel = computed<"world" | "regions" | "settlements">(() => {
  if (zoomFactor.value < 1.25) return "world";
  if (zoomFactor.value < 2.35) return "regions";
  return "settlements";
});
const visibleSettlementLabelIds = computed(() => {
  const visible = new Set<string>();
  const accepted: Array<{ position: Coordinate; minX: number; minY: number }> = [];
  const candidates = props.alliance.settlements.filter((settlement) => {
    if (!shouldShowSettlement(settlement)) return false;
    if (settlement.kind === "village") return detailLevel.value === "settlements" && zoomFactor.value >= 2.8;
    return true;
  }).sort((left, right) => {
    const priority = { capital: 0, town: 1, village: 2 } as const;
    return priority[left.kind] - priority[right.kind];
  });
  for (const settlement of candidates) {
    const minX = settlement.kind === "capital" ? 0 : settlement.kind === "town" ? 74 : 56;
    const minY = settlement.kind === "capital" ? 0 : 22;
    const crowded = accepted.some((item) =>
      Math.abs(item.position[0] - settlement.position[0]) < Math.max(item.minX, minX)
      && Math.abs(item.position[1] - settlement.position[1]) < Math.max(item.minY, minY),
    );
    if (crowded) continue;
    visible.add(settlement.id);
    accepted.push({ position: settlement.position, minX, minY });
  }
  return visible;
});
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
    viewCenter.value = worldCenter.value;
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
  polygon: Coordinate[];
  kind: TerrainPatchKind;
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
  const polar = y < 220 || y > 1580;
  const cold = y < 620 || y > 1080;
  if (kind === "desert" && polar) return "tundra";
  if (kind === "desert" && cold) return "steppe";
  if (kind === "rainforest" && cold) return "forest";
  if (kind === "savanna" && polar) return "steppe";
  if (kind === "wetland" && polar) return "tundra";
  return kind;
}

const terrainPatches = computed<TerrainPatch[]>(() => {
  const recipes: Array<{ kind: TerrainPatchKind; x: number; y: number }> = [
    { kind: "ice", x: 0.08, y: 0.08 },
    { kind: "taiga", x: 0.28, y: 0.12 },
    { kind: "forest", x: 0.50, y: 0.16 },
    { kind: "rock", x: 0.74, y: 0.10 },
    { kind: "tundra", x: 0.92, y: 0.22 },
    { kind: "forest", x: 0.18, y: 0.36 },
    { kind: "meadow", x: 0.40, y: 0.34 },
    { kind: "desert", x: 0.65, y: 0.37 },
    { kind: "steppe", x: 0.86, y: 0.40 },
    { kind: "wetland", x: 0.22, y: 0.64 },
    { kind: "savanna", x: 0.46, y: 0.62 },
    { kind: "rainforest", x: 0.71, y: 0.65 },
    { kind: "wetland", x: 0.90, y: 0.68 },
    { kind: "rock", x: 0.34, y: 0.86 },
    { kind: "forest", x: 0.60, y: 0.84 },
    { kind: "ice", x: 0.84, y: 0.90 },
  ];
  return props.alliance.landmasses.flatMap((landmass, landmassIndex) => {
    const bounds = terrainBounds(landmass);
    const width = Math.max(1, bounds.x1 - bounds.x0);
    const height = Math.max(1, bounds.y1 - bounds.y0);
    const sites = recipes.map((recipe, recipeIndex) => {
      const jitterX = (terrainUnit(props.alliance.seed, `${landmassIndex}:x:${recipeIndex}`) - 0.5) * 0.22;
      const jitterY = (terrainUnit(props.alliance.seed, `${landmassIndex}:y:${recipeIndex}`) - 0.5) * 0.18;
      return [
        bounds.x0 + width * Math.max(0.04, Math.min(0.96, recipe.x + jitterX)),
        bounds.y0 + height * Math.max(0.04, Math.min(0.96, recipe.y + jitterY)),
      ] as Coordinate;
    });
    return recipes.map((recipe, recipeIndex) => {
      const site = sites[recipeIndex];
      const cy = site[1];
      const variantKind = landmassIndex === 0 && recipeIndex === 0 ? "rainforest" : recipe.kind;
      return {
        id: `terrain-patch-${landmassIndex}-${recipeIndex}`,
        polygon: allianceCell(site, sites),
        kind: climateSafeKind(variantKind, cy),
        opacity: 0.44 + terrainUnit(props.alliance.seed, `${landmassIndex}:opacity:${recipeIndex}`) * 0.16,
      };
    });
  });
});

function landmassVariant(index: number): number {
  const landmass = props.alliance.landmasses[index];
  const bounds = terrainBounds(landmass);
  const latitude = (bounds.y0 + bounds.y1) / 2;
  const variant = terrainUnit(props.alliance.seed, `landmass-texture-${index}`);
  if (latitude < 420 || latitude > 1580) return variant < 0.55 ? 0 : 3;
  if (latitude < 650 || latitude > 1180) return variant < 0.45 ? 0 : variant < 0.78 ? 2 : 3;
  return variant < 0.2 ? 0 : variant < 0.48 ? 1 : variant < 0.8 ? 2 : 3;
}

function settlementRadius(settlement: AllianceSettlement): number {
  return settlement.kind === "capital" ? 16 : settlement.kind === "town" ? 10 : 5;
}

function settlementMarkerPath(settlement: AllianceSettlement): string {
  const [x, y] = settlement.position;
  const size = settlementRadius(settlement) * (settlement.kind === "capital" ? 1.14 : 1);
  if (settlement.kind === "capital") {
    return `M${x},${y - size} L${x + size * 0.78},${y - size * 0.32} L${x + size * 0.62},${y + size * 0.72} L${x},${y + size} L${x - size * 0.62},${y + size * 0.72} L${x - size * 0.78},${y - size * 0.32} Z`;
  }
  if (settlement.kind === "town") {
    return `M${x},${y - size} L${x + size},${y} L${x},${y + size} L${x - size},${y} Z`;
  }
  return `M${x - size * 0.72},${y - size * 0.72} H${x + size * 0.72} V${y + size * 0.72} H${x - size * 0.72} Z`;
}

function settlementClass(settlement: AllianceSettlement): string {
  return `alliance-settlement alliance-settlement--${settlement.kind}${props.selectedId === settlement.id ? " is-selected" : ""}`;
}

function shouldShowSettlementLabel(settlement: AllianceSettlement): boolean {
  return visibleSettlementLabelIds.value.has(settlement.id);
}

function shouldShowSettlement(settlement: AllianceSettlement): boolean {
  if (detailLevel.value === "world") return settlement.kind === "capital";
  if (detailLevel.value === "regions") return settlement.kind !== "village";
  return true;
}

function regionLabelPosition(region: AllianceModel["regions"][number]): [number, number] {
  const capital = props.alliance.settlements.find((settlement) => settlement.id === region.capitalId);
  if (!capital) return [0, 0];
  return [capital.position[0], capital.position[1] - 34];
}

onMounted(() => {
  const updateViewport = () => {
    const nextCompact = window.innerWidth < 900;
    compactView.value = nextCompact;
    if (nextCompact) {
      const [x, y, width, height] = compactViewBox.value.split(" ").map(Number);
      viewCenter.value = [x + width / 2, y + height / 2];
    } else {
      viewCenter.value = worldCenter.value;
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
          <stop offset="0" stop-color="#d5e7eb" stop-opacity="0.82" />
          <stop offset="0.07" stop-color="#96784b" stop-opacity="0.52" />
          <stop offset="0.16" stop-color="#4b6b32" stop-opacity="0.38" />
          <stop offset="0.28" stop-color="#409c43" stop-opacity="0.42" />
          <stop offset="0.40" stop-color="#c8d68f" stop-opacity="0.48" />
          <stop offset="0.50" stop-color="#d2d082" stop-opacity="0.52" />
          <stop offset="0.60" stop-color="#c8d68f" stop-opacity="0.48" />
          <stop offset="0.72" stop-color="#29bc56" stop-opacity="0.42" />
          <stop offset="0.84" stop-color="#4b6b32" stop-opacity="0.38" />
          <stop offset="0.93" stop-color="#96784b" stop-opacity="0.52" />
          <stop offset="1" stop-color="#d5e7eb" stop-opacity="0.82" />
        </linearGradient>
        <radialGradient id="alliance-ice-gradient">
          <stop offset="0" stop-color="#d5e7eb" stop-opacity="0.74" />
          <stop offset="0.55" stop-color="#cdd4e7" stop-opacity="0.28" />
          <stop offset="1" stop-color="#cdd4e7" stop-opacity="0" />
        </radialGradient>
        <radialGradient id="alliance-tundra-gradient">
          <stop offset="0" stop-color="#96784b" stop-opacity="0.64" />
          <stop offset="0.64" stop-color="#96784b" stop-opacity="0.2" />
          <stop offset="1" stop-color="#96784b" stop-opacity="0" />
        </radialGradient>
        <radialGradient id="alliance-taiga-gradient">
          <stop offset="0" stop-color="#4b6b32" stop-opacity="0.56" />
          <stop offset="0.7" stop-color="#4b6b32" stop-opacity="0.16" />
          <stop offset="1" stop-color="#4b6b32" stop-opacity="0" />
        </radialGradient>
        <radialGradient id="alliance-forest-gradient">
          <stop offset="0" stop-color="#29bc56" stop-opacity="0.56" />
          <stop offset="0.68" stop-color="#29bc56" stop-opacity="0.16" />
          <stop offset="1" stop-color="#29bc56" stop-opacity="0" />
        </radialGradient>
        <radialGradient id="alliance-meadow-gradient">
          <stop offset="0" stop-color="#c8d68f" stop-opacity="0.56" />
          <stop offset="0.7" stop-color="#c8d68f" stop-opacity="0.17" />
          <stop offset="1" stop-color="#c8d68f" stop-opacity="0" />
        </radialGradient>
        <radialGradient id="alliance-steppe-gradient">
          <stop offset="0" stop-color="#d2d082" stop-opacity="0.6" />
          <stop offset="0.64" stop-color="#d2d082" stop-opacity="0.22" />
          <stop offset="1" stop-color="#d2d082" stop-opacity="0" />
        </radialGradient>
        <radialGradient id="alliance-desert-gradient">
          <stop offset="0" stop-color="#fbe79f" stop-opacity="0.76" />
          <stop offset="0.54" stop-color="#fbe79f" stop-opacity="0.36" />
          <stop offset="1" stop-color="#fbe79f" stop-opacity="0" />
        </radialGradient>
        <radialGradient id="alliance-savanna-gradient">
          <stop offset="0" stop-color="#b6d95d" stop-opacity="0.6" />
          <stop offset="0.68" stop-color="#b6d95d" stop-opacity="0.18" />
          <stop offset="1" stop-color="#b6d95d" stop-opacity="0" />
        </radialGradient>
        <radialGradient id="alliance-rainforest-gradient">
          <stop offset="0" stop-color="#7dcb35" stop-opacity="0.68" />
          <stop offset="0.64" stop-color="#7dcb35" stop-opacity="0.22" />
          <stop offset="1" stop-color="#7dcb35" stop-opacity="0" />
        </radialGradient>
        <radialGradient id="alliance-wetland-gradient">
          <stop offset="0" stop-color="#0b9131" stop-opacity="0.52" />
          <stop offset="0.66" stop-color="#0b9131" stop-opacity="0.16" />
          <stop offset="1" stop-color="#0b9131" stop-opacity="0" />
        </radialGradient>
        <radialGradient id="alliance-rock-gradient">
          <stop offset="0" stop-color="#b5b887" stop-opacity="0.6" />
          <stop offset="0.64" stop-color="#b5b887" stop-opacity="0.18" />
          <stop offset="1" stop-color="#b5b887" stop-opacity="0" />
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
      <rect :x="worldBounds[0]" :y="worldBounds[1]" :width="worldBounds[2]" :height="worldBounds[3]" class="alliance-map__ground" />
      <image :x="worldBounds[0]" :y="worldBounds[1]" :width="worldBounds[2]" :height="worldBounds[3]" href="/assets/ocean-texture.jpg" preserveAspectRatio="xMidYMid slice" class="alliance-ocean-texture" aria-hidden="true" />
      <rect :x="worldBounds[0]" :y="worldBounds[1]" :width="worldBounds[2]" :height="worldBounds[3]" class="alliance-map__grid" />

      <g class="alliance-landmasses" aria-label="陆地">
        <polygon v-for="(landmass, index) in alliance.landmasses" :key="`landmass-${index}`" :points="alliancePolygon(landmass)" :class="['alliance-landmass', `alliance-landmass--variant-${landmassVariant(index)}`]" />
      </g>

      <g class="alliance-climate-field" clip-path="url(#alliance-land-clip)" aria-label="气候渐变">
        <rect :x="worldBounds[0]" :y="worldBounds[1]" :width="worldBounds[2]" :height="worldBounds[3]" class="alliance-climate-field__gradient" />
        <rect :x="worldBounds[0]" :y="worldBounds[1]" :width="worldBounds[2]" :height="worldBounds[3]" class="alliance-climate-field__noise" />
        <polygon v-for="patch in terrainPatches" :key="patch.id" :points="alliancePolygon(patch.polygon)" :class="['alliance-biome-patch', `alliance-biome-patch--${patch.kind}`]" :style="{ opacity: patch.opacity }" />
      </g>

      <g class="alliance-countries" clip-path="url(#alliance-land-clip)" aria-label="大陆国家">
        <g v-for="country in alliance.countries" :key="country.id">
          <polygon :points="alliancePolygon(country.polygon)" :class="['alliance-country', `alliance-country--${country.colorIndex % 8}`]" />
          <text v-if="detailLevel !== 'settlements'" :x="country.labelPosition[0]" :y="country.labelPosition[1]" text-anchor="middle" class="alliance-country__label">{{ country.name }}</text>
        </g>
      </g>

      <g class="alliance-territory" aria-label="人类联盟控制区">
        <polygon :points="alliancePolygon(alliance.territory)" class="alliance-territory__fill" />
        <text :x="territoryLabelPosition[0]" :y="territoryLabelPosition[1]" class="alliance-territory__label">人类联盟控制区</text>
      </g>

      <g v-if="detailLevel !== 'world'" class="alliance-regions" aria-label="联盟行政区域" clip-path="url(#alliance-territory-clip)">
        <g v-for="region in alliance.regions" :key="region.id">
          <polygon :points="alliancePolygon(region.polygon)" :class="['alliance-region', `alliance-region--${region.colorIndex}`]" />
          <text v-if="detailLevel === 'regions'" :x="regionLabelPosition(region)[0]" :y="regionLabelPosition(region)[1]" class="alliance-region__label">{{ region.name }}</text>
        </g>
      </g>

      <g class="alliance-latitudes" clip-path="url(#alliance-land-clip)">
        <text v-for="band in alliance.bands" :key="`${band.id}-label`" x="34" :y="(band.y0 + band.y1) / 2" class="alliance-band-label">{{ band.label }}</text>
        <path :d="equatorPath" class="alliance-equator" />
        <text :x="equatorLabelPosition[0]" :y="equatorLabelPosition[1]" class="alliance-equator-label">赤道</text>
      </g>

      <g class="alliance-mountains" clip-path="url(#alliance-land-clip)" aria-label="山脉">
        <path v-for="(mountain, index) in alliance.mountains" :key="`mountain-${index}`" :d="alliancePath(mountain)" class="alliance-mountain" />
      </g>
      <g class="alliance-rivers" clip-path="url(#alliance-land-clip)" aria-label="河流">
        <path v-for="(river, index) in alliance.rivers" :key="`river-${index}`" :d="alliancePath(river)" class="alliance-river" />
      </g>
      <g class="alliance-lakes" clip-path="url(#alliance-land-clip)" aria-label="湖泊">
        <polygon v-for="(lake, index) in alliance.lakes" :key="`lake-${index}`" :points="alliancePolygon(lake)" class="alliance-lake" />
      </g>

      <g class="alliance-roads" aria-label="聚落交通">
        <path v-for="road in alliance.roads" :key="road.id" :d="alliancePath(road.path)" :class="`alliance-road alliance-road--${road.kind}`" />
      </g>
      <g class="alliance-flow" aria-label="联盟交通流">
        <circle v-for="dot in flowDots" :key="dot.id" :cx="dot.position[0]" :cy="dot.position[1]" :class="`alliance-flow-dot alliance-flow-dot--${dot.kind}`" r="3.8" />
      </g>

      <g class="alliance-settlements" aria-label="聚落">
        <template v-for="settlement in alliance.settlements" :key="settlement.id">
          <g v-if="shouldShowSettlement(settlement)" :class="settlementClass(settlement)" role="button" tabindex="0" :aria-label="`${settlement.name}，双击查看街道细节`" @pointerdown.stop @click="handleSettlementClick(settlement)" @dblclick="handleSettlementOpen(settlement)" @keydown.enter="handleSettlementClick(settlement)">
            <title>{{ settlement.name }} · {{ settlement.kind === "capital" ? "主城" : settlement.kind === "town" ? "城镇" : "村庄" }} · {{ settlement.population.toLocaleString("zh-CN") }} 人</title>
            <path :d="settlementMarkerPath(settlement)" class="alliance-settlement__marker" />
            <path v-if="settlement.kind === 'capital'" :d="`M${settlement.position[0]},${settlement.position[1] - 5} L${settlement.position[0] + 5},${settlement.position[1] + 4} L${settlement.position[0]},${settlement.position[1] + 8} L${settlement.position[0] - 5},${settlement.position[1] + 4} Z`" class="alliance-settlement__marker-core" />
            <text v-if="shouldShowSettlementLabel(settlement)" :x="settlement.position[0] + settlementRadius(settlement) + 8" :y="settlement.position[1] + 4" class="alliance-settlement__label">{{ settlement.name }}</text>
          </g>
        </template>
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
      <span><i class="alliance-legend-line alliance-legend-line--region"></i>行政区域</span>
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
  --terrain-ocean: #466eab;
  --terrain-land: #eef6fb;
  --terrain-edge: #b0c4d8;
  --terrain-ink: #3e3e4b;
  background: var(--terrain-ocean);
}
.alliance-map--pearl {
  --terrain-ocean: #5b8cc9;
  --terrain-land: #f5f0e8;
  --terrain-edge: #8a9fb5;
  --terrain-ink: #2e2e38;
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
.alliance-map--pearl .alliance-map__zoom-controls {
  color: oklch(0.27 0.04 245);
  background: oklch(0.91 0.045 95 / 0.9);
  border-color: oklch(0.36 0.05 125 / 0.3);
}

.alliance-map__ground { fill: var(--terrain-ocean); }
.alliance-ocean-texture { opacity: 0.16; mix-blend-mode: screen; filter: saturate(0.72) contrast(0.88); }
.alliance-map__grid { fill: url("#alliance-grid"); opacity: 0.24; }
.alliance-grid-line { stroke: #a6c1fd; stroke-width: 1; opacity: 0.12; }
.alliance-landmass { stroke: var(--terrain-edge); stroke-width: 2.2; opacity: 0.94; }
.alliance-landmass--variant-0 { fill: url("#alliance-land-texture"); }
.alliance-landmass--variant-1 { fill: url("#alliance-land-texture-dry"); }
.alliance-landmass--variant-2 { fill: url("#alliance-land-texture-forest"); }
.alliance-landmass--variant-3 { fill: url("#alliance-land-texture-rock"); }
.alliance-land-texture__ground { fill: var(--terrain-land); }
.alliance-land-texture__grain { fill: none; stroke: #b0c4d8; stroke-width: 1; opacity: 0.24; }
.alliance-land-texture__speck { fill: #b0c4d8; opacity: 0.32; }
.alliance-land-texture__dry-ground { fill: #d9cda4; }
.alliance-land-texture__dry-ridge { fill: none; stroke: #a99d72; stroke-width: 1.2; opacity: 0.3; }
.alliance-land-texture__dry-speck { fill: none; stroke: #8e876d; stroke-width: 2; opacity: 0.28; }
.alliance-land-texture__forest-ground { fill: #9caf8c; }
.alliance-land-texture__forest-grain { fill: none; stroke: #667f62; stroke-width: 1.1; opacity: 0.28; }
.alliance-land-texture__canopy { fill: #718d6a; opacity: 0.36; }
.alliance-land-texture__canopy-small { fill: #b4c49d; opacity: 0.38; }
.alliance-land-texture__rock-ground { fill: #aaa99c; }
.alliance-land-texture__rock-ridge { fill: none; stroke: #777368; stroke-width: 1.6; opacity: 0.32; }
.alliance-land-texture__rock-facet { fill: #c8c6b5; opacity: 0.3; }
.alliance-map--pearl .alliance-land-texture__dry-ground { fill: #f5e9c4; }
.alliance-map--pearl .alliance-land-texture__dry-ridge { stroke: #d2d082; }
.alliance-map--pearl .alliance-land-texture__forest-ground { fill: #4cb86a; }
.alliance-map--pearl .alliance-land-texture__forest-grain { stroke: #409c43; }
.alliance-map--pearl .alliance-land-texture__canopy { fill: #29bc56; }
.alliance-map--pearl .alliance-land-texture__rock-ground { fill: #d4cfb8; }
.alliance-map--pearl .alliance-land-texture__rock-ridge { stroke: #96784b; }
.alliance-map--pearl .alliance-land-texture__rock-facet { fill: #e8e0cc; }
.alliance-climate-field { mix-blend-mode: multiply; pointer-events: none; }
.alliance-climate-field__gradient { fill: url("#alliance-climate-gradient"); opacity: 0.68; }
.alliance-climate-field__noise { fill: #c8d68f; opacity: 0.18; filter: url("#alliance-terrain-noise"); mix-blend-mode: soft-light; }
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
.alliance-countries { pointer-events: none; }
.alliance-country { stroke: #656b68; stroke-width: 3; stroke-dasharray: 9 8; stroke-opacity: 0.58; }
.alliance-country--0 { fill: #dbe7c5; fill-opacity: 0.52; }
.alliance-country--1 { fill: #f0dfad; fill-opacity: 0.5; }
.alliance-country--2 { fill: #c7e2e1; fill-opacity: 0.5; }
.alliance-country--3 { fill: #e8cfc0; fill-opacity: 0.5; }
.alliance-country--4 { fill: #d9d0e8; fill-opacity: 0.5; }
.alliance-country--5 { fill: #d7e2c4; fill-opacity: 0.5; }
.alliance-country--6 { fill: #efd6b7; fill-opacity: 0.5; }
.alliance-country--7 { fill: #cfe0ed; fill-opacity: 0.5; }
.alliance-country__label { fill: #3e3e4b; font: 700 36px "Noto Sans SC Variable", sans-serif; paint-order: stroke; stroke: #f4f0df; stroke-width: 7px; stroke-linejoin: round; }
.alliance-band-label { fill: var(--terrain-ink); font: 600 15px "Noto Sans SC Variable", sans-serif; letter-spacing: 1px; opacity: 0.66; paint-order: stroke; stroke: var(--terrain-ocean); stroke-width: 4px; }
.alliance-equator { stroke: #d06324; stroke-width: 2; stroke-dasharray: 9 10; opacity: 0.82; }
.alliance-equator-label { fill: #3e3e4b; font: 700 14px "Noto Sans SC Variable", sans-serif; paint-order: stroke; stroke: var(--terrain-ocean); stroke-width: 4px; }
.alliance-territory__fill { fill: #e1c76e; fill-opacity: 0.42; stroke: #4f4c46; stroke-width: 3; stroke-dasharray: 12 10; }
.alliance-territory__label { fill: #3e3e4b; font: 700 19px "Noto Sans SC Variable", sans-serif; letter-spacing: 1px; paint-order: stroke; stroke: #eef6fb; stroke-width: 5px; }
.alliance-regions { pointer-events: none; }
.alliance-region { stroke-width: 2.5; stroke-dasharray: 11 9; stroke-linejoin: round; }
.alliance-region--0 { fill: #eef6fb; fill-opacity: 0.32; stroke: #3e3e4b; stroke-opacity: 0.5; }
.alliance-region--1 { fill: #c8d68f; fill-opacity: 0.3; stroke: #3e3e4b; stroke-opacity: 0.5; }
.alliance-region--2 { fill: #a6c1fd; fill-opacity: 0.3; stroke: #3e3e4b; stroke-opacity: 0.5; }
.alliance-region--3 { fill: #fbe79f; fill-opacity: 0.3; stroke: #3e3e4b; stroke-opacity: 0.5; }
.alliance-region--4 { fill: #96784b; fill-opacity: 0.3; stroke: #3e3e4b; stroke-opacity: 0.5; }
.alliance-region__label { fill: #3e3e4b; font: 700 15px "Noto Sans SC Variable", sans-serif; letter-spacing: 0.8px; paint-order: stroke; stroke: #eef6fb; stroke-width: 4px; }

.alliance-mountain { fill: none; stroke: #6f6d68; stroke-width: 8; stroke-dasharray: 1 16; stroke-linecap: round; opacity: 0.72; }
.alliance-river { fill: none; stroke: #5d97bb; stroke-width: 5; stroke-linecap: round; opacity: 0.82; }
.alliance-lake { fill: #a6c1fd; stroke: #5f799d; stroke-width: 2; opacity: 0.78; }
.alliance-road { fill: none; stroke-linecap: round; stroke-linejoin: round; }
.alliance-road--imperial { stroke: #d06324; stroke-width: 9; opacity: 0.82; }
.alliance-road--regional { stroke: #d06324; stroke-width: 5; opacity: 0.64; stroke-dasharray: 8 4; }
.alliance-road--local { stroke: #d06324; stroke-width: 2.5; opacity: 0.48; stroke-dasharray: 3 3; }
.alliance-flow-dot { stroke: #1f3846; stroke-width: 1.5; }
.alliance-flow-dot--people { fill: #5d97bb; }
.alliance-flow-dot--vehicle { fill: #d06324; }

.alliance-settlement { cursor: pointer; outline: none; }
.alliance-settlement__marker { stroke: #3e3e4b; stroke-width: 2.5; stroke-linejoin: round; }
.alliance-settlement--capital .alliance-settlement__marker { fill: #ffffff; fill-opacity: 0.85; }
.alliance-settlement--town .alliance-settlement__marker { fill: #ffffff; fill-opacity: 0.78; }
.alliance-settlement--village .alliance-settlement__marker { fill: #ffffff; fill-opacity: 0.65; }
.alliance-settlement__marker-core { fill: #3e3e4b; stroke: #ffffff; stroke-width: 1.5; pointer-events: none; }
.alliance-settlement__label { fill: #3e3e4b; font: 700 18px "Noto Sans SC Variable", sans-serif; paint-order: stroke; stroke: #ffffff; stroke-width: 4px; stroke-linejoin: round; }
.alliance-settlement--village .alliance-settlement__label { font-size: 13px; font-weight: 500; }
.alliance-settlement:hover .alliance-settlement__marker,
.alliance-settlement:focus .alliance-settlement__marker,
.alliance-settlement.is-selected .alliance-settlement__marker { stroke: #d06324; stroke-width: 4; }

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
.alliance-map--pearl .alliance-map__legend {
  color: oklch(0.27 0.04 245);
  background: oklch(0.91 0.045 95 / 0.92);
  border-color: oklch(0.36 0.05 125 / 0.3);
}
.alliance-legend-swatch, .alliance-legend-line { display: inline-block; vertical-align: middle; margin-right: 5px; }
.alliance-legend-swatch { width: 9px; height: 9px; border-radius: 50%; border: 2px solid #3e3e4b; background: #ffffff; }
.alliance-legend-swatch--town { background: #ffffff; }
.alliance-legend-swatch--village { background: #ffffff; }
.alliance-legend-swatch--lake { background: #a6c1fd; border-color: #5f799d; }
.alliance-legend-line { width: 20px; height: 3px; background: #5d97bb; }
.alliance-legend-line--road { background: #d06324; }
.alliance-legend-line--region { height: 0; border-top: 2px dashed #3e3e4b; background: transparent; }
.alliance-legend-biome { display: inline-block; width: 20px; height: 7px; margin-right: 5px; border-radius: 2px; }
.alliance-legend-biome--polar { background: linear-gradient(90deg, #d5e7eb, #96784b); }
.alliance-legend-biome--temperate { background: linear-gradient(90deg, #4b6b32, #c8d68f); }
.alliance-legend-biome--arid { background: linear-gradient(90deg, #d2d082, #fbe79f); }
.alliance-legend-biome--equatorial { background: linear-gradient(90deg, #29bc56, #7dcb35); }

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
