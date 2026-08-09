<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { Activity, AlertTriangle, Menu, Moon, Sun, X } from "lucide-vue-next";
import ControlRail from "./ControlRail.vue";
import CityMap from "./CityMap.vue";
import AllianceMap from "./AllianceMap.vue";
import PlaybackTimeline from "./PlaybackTimeline.vue";
import { createAlliance, type AllianceSettlement } from "./alliance";
import type { MapClarity } from "./renderSettings";
import type { FlowAnalysisMode, TownLayerVisibility } from "./townLayers";
import {
  ApiError,
  createDraftRun,
  createRun,
  createScenarioDraft,
  getRun,
  getScenarioDraft,
  getSnapshot,
  listRuns,
  listScenarios,
  sendCommand,
  type ConnectionConfig,
  type RunRate,
  type RunRecord,
  type ScenarioBundle,
  type ScenarioDraft,
  type SnapshotResponse,
  type SnapshotState,
} from "./api";
import {
  clampInspectorWidth,
  clampRailWidth,
  KEYBOARD_STEP,
  INSPECTOR_MIN_WIDTH,
  INSPECTOR_MAX_WIDTH,
  RAIL_MIN_WIDTH,
  RAIL_MAX_WIDTH,
  storedPanelLayout,
  persistPanelLayout,
} from "./resizeUtils";

const scenarios = ref<ScenarioBundle[]>([]);
const recentRuns = ref<RunRecord[]>([]);
const selectedScenarioId = ref<string | null>(null);
const selectedRun = ref<RunRecord | null>(null);
const selectedBundle = ref<ScenarioBundle | null>(null);
const latestSnapshot = ref<SnapshotResponse | null>(null);
const displayedSnapshot = ref<SnapshotState | null>(null);
const followingLatest = ref(true);
const playbackPlaying = ref(false);
const loading = ref(false);
const error = ref<ApiError | null>(null);
const selectedFeatureId = ref<string | null>(null);
const draft = ref<ScenarioDraft | null>(null);
const generationLoading = ref(false);
const analysisFlow = ref<FlowAnalysisMode>("people");
const flowDensity = ref(1);
const mapClarity = ref<MapClarity>("standard");
const mobilePanel = ref<"controls" | "stats" | null>(null);
type WorldView = "alliance" | "town";
const worldView = ref<WorldView>("alliance");
const alliance = createAlliance();
const selectedAllianceId = ref<string | null>(null);
const allianceTransitioning = ref(false);
const worldRunStatus = ref<RunRecord["status"] | "idle">("idle");
const worldRunRate = ref<RunRate>(1);

const THEME_STORAGE_KEY = "world-sim.theme";
type Theme = "pearl" | "night";
function storedTheme(): Theme {
  try {
    const value = localStorage.getItem(THEME_STORAGE_KEY);
    return value === "pearl" ? "pearl" : "night";
  } catch {
    return "night";
  }
}
const theme = ref<Theme>(storedTheme());
let mobilePanelTrigger: HTMLElement | null = null;

const railWidth = ref(storedPanelLayout().railWidth);
const inspectorWidth = ref(storedPanelLayout().inspectorWidth);
const activeResize = ref<"rail" | "inspector" | null>(null);
let resizePointerId: number | undefined;
let resizeFrame: number | undefined;
let resizeOffset = 0;

const workspaceStyle = computed(() => ({
  "--rail-width": `${railWidth.value}px`,
  "--inspector-width": `${inspectorWidth.value}px`,
}));
const layerVisibility = ref<TownLayerVisibility>({
  walls: true,
  roads: true,
  buildings: true,
  landmarks: true,
  people: true,
  vehicles: true,
  heat: true,
});

let pollTimer: number | null = null;
let seekTimer: number | null = null;
let playbackTimer: number | null = null;
let draftPollTimer: number | null = null;
let pollAbort: AbortController | null = null;
let seekAbort: AbortController | null = null;

const activeRun = computed(() => selectedRun.value?.status === "running" || selectedRun.value?.status === "paused");
const latestTick = computed(() => latestSnapshot.value?.tick ?? 0);
const displayedTick = computed(() => displayedSnapshot.value?.tick ?? 0);
const replayable = computed(() => selectedRun.value?.status === "ended" || selectedRun.value?.status === "failed");
const runRate = computed<RunRate>(() => selectedRun.value?.rate ?? 1);
const flowId = computed(() => {
  const types = selectedBundle.value?.simulation_package?.flow_types ?? selectedBundle.value?.config.flow_types ?? [];
  return types.find((flow) => flow.id === "pedestrian" || flow.id === "citizen" || flow.unit === "people")?.id ?? types[0]?.id ?? null;
});
const vehicleFlowId = computed(() => {
  const types = selectedBundle.value?.simulation_package?.flow_types ?? selectedBundle.value?.config.flow_types ?? [];
  return types.find((flow) => flow.id === "vehicle" || flow.unit === "vehicles")?.id ?? null;
});

const activeTownName = computed(() =>
  selectedBundle.value?.town_skeleton?.name
  ?? selectedBundle.value?.config.name
  ?? draft.value?.town_skeleton.name
  ?? "尚无场景",
);

const focusedAllianceSettlement = computed(() =>
  alliance.settlements.find((settlement) => settlement.id === selectedAllianceId.value) ?? null,
);
const focusedAllianceParent = computed(() => {
  const parentId = focusedAllianceSettlement.value?.parentId;
  return parentId ? alliance.settlements.find((settlement) => settlement.id === parentId) ?? null : null;
});

const allianceCounts = computed(() => ({
  capitals: alliance.settlements.filter((settlement) => settlement.kind === "capital").length,
  towns: alliance.settlements.filter((settlement) => settlement.kind === "town").length,
  villages: alliance.settlements.filter((settlement) => settlement.kind === "village").length,
}));

const selectedLocation = computed(() => {
  if (!selectedFeatureId.value || !selectedBundle.value) return null;
  return selectedBundle.value.config.locations.find((location) => location.id === selectedFeatureId.value) ?? null;
});

const selectedConnection = computed<ConnectionConfig | null>(() => {
  if (!selectedFeatureId.value || !selectedBundle.value) return null;
  return selectedBundle.value.config.connections.find((connection) => connection.id === selectedFeatureId.value) ?? null;
});

const selectedStreet = computed(() => {
  if (!selectedFeatureId.value || !selectedBundle.value?.town_skeleton) return null;
  return selectedBundle.value.town_skeleton.streets.find((street) => street.id === selectedFeatureId.value) ?? null;
});

const selectedStreetRoutes = computed(() => {
  if (!selectedStreet.value || !selectedBundle.value?.simulation_package) return [];
  return selectedBundle.value.simulation_package.connections.filter((connection) =>
    connection.street_segment_ids.includes(selectedStreet.value!.id)
    || Object.values(connection.flow_street_segment_ids ?? {}).some((streetIds) => streetIds.includes(selectedStreet.value!.id)),
  );
});

const selectedStreetStats = computed(() => {
  const snapshot = displayedSnapshot.value;
  const street = selectedStreet.value;
  if (!street || !snapshot || snapshot.schema_version !== 2) return null;
  return {
    people: flowId.value ? snapshot.streets?.[street.id]?.[flowId.value] ?? null : null,
    vehicle: vehicleFlowId.value ? snapshot.streets?.[street.id]?.[vehicleFlowId.value] ?? null : null,
  };
});

const selectedLocationStats = computed(() => {
  const location = selectedLocation.value;
  const types = selectedBundle.value?.simulation_package?.flow_types ?? selectedBundle.value?.config.flow_types ?? [];
  const peopleId = types.find((flow) => flow.id === "pedestrian" || flow.id === "citizen" || flow.unit === "people")?.id ?? null;
  const vehicleId = types.find((flow) => flow.id === "vehicle" || flow.unit === "vehicles")?.id ?? null;
  return location ? { people: locationFlowStats(location.id, peopleId), vehicle: locationFlowStats(location.id, vehicleId) } : null;
});

const districtKindLabels: Record<string, string> = {
  residential: "居住",
  market: "市场",
  industrial: "工业",
  storage: "仓储",
  religious: "宗教",
  civic: "行政",
  military: "军事",
  stable: "驿站",
};

const buildingKindLabels: Record<string, string> = {
  residential: "居民楼",
  market: "商铺",
  workshop: "工坊",
  storage: "仓库",
  religious: "神殿",
  administrative: "行政厅",
  military: "兵营",
  stable: "马厩",
};

function aggregateFeatures(locationId: string): Array<{ id: string; label: string; kind: "district" | "building" | "other" }> {
  const bundle = selectedBundle.value;
  const featureIds = bundle?.simulation_package?.bindings.location_feature_ids[locationId] ?? [];
  if (!bundle?.town_skeleton) return [];
  const skeleton = bundle.town_skeleton;
  const districts = new Map(skeleton.districts.map((district) => [district.id, district]));
  const buildings = new Map(skeleton.buildings.map((building) => [building.id, building]));
  return featureIds.map((featureId) => {
    const district = districts.get(featureId);
    if (district) {
      return {
        id: featureId,
        kind: "district" as const,
        label: `${featureId.replace(/^district-/, "").toUpperCase()} · ${districtKindLabels[district.kind] ?? district.kind}`,
      };
    }
    const building = buildings.get(featureId);
    if (building) {
      return {
        id: featureId,
        kind: "building" as const,
        label: `${buildingKindLabels[building.kind] ?? building.kind} ${featureId.replace(/^building-/, "")}`,
      };
    }
    const landmark = skeleton.landmarks.find((item) => item.id === featureId);
    return { id: featureId, kind: "other" as const, label: landmark?.name ?? featureId };
  });
}

const selectedAggregateFeatures = computed(() => selectedLocation.value ? aggregateFeatures(selectedLocation.value.id) : []);
const selectedAggregateDistricts = computed(() => selectedAggregateFeatures.value.filter((feature) => feature.kind === "district"));
const selectedAggregateBuildings = computed(() => selectedAggregateFeatures.value.filter((feature) => feature.kind === "building"));

const totalPeople = computed(() => displayedSnapshot.value?.totals[flowId.value ?? ""] ?? 0);

function connectionActivity(connectionId: string, flowTypeId: string): { departed: number; arrived: number; inTransit: number } {
  const snapshot = displayedSnapshot.value;
  if (!snapshot) return { departed: 0, arrived: 0, inTransit: 0 };
  if (snapshot.schema_version === 2) {
    const value = snapshot.connections[connectionId]?.[flowTypeId];
    return { departed: value?.departed ?? 0, arrived: value?.arrived ?? 0, inTransit: value?.in_transit ?? 0 };
  }
  const value = snapshot.connection_activity[connectionId]?.[flowTypeId];
  const buckets = snapshot.transit_buckets[connectionId]?.[flowTypeId] ?? [];
  return { departed: value?.departed ?? 0, arrived: value?.arrived ?? 0, inTransit: buckets.reduce((sum, count) => sum + count, 0) };
}

function connectionDeparted(connectionId: string, flowTypeId: string): number {
  return connectionActivity(connectionId, flowTypeId).departed;
}

function connectionArrived(connectionId: string, flowTypeId: string): number {
  return connectionActivity(connectionId, flowTypeId).arrived;
}

function locationFlowStats(locationId: string, flowTypeId: string | null) {
  const snapshot = displayedSnapshot.value;
  const bundle = selectedBundle.value;
  if (!snapshot || !bundle || !flowTypeId) return null;
  const connections = bundle.simulation_package?.connections ?? bundle.config.connections;
  const location = bundle.config.locations.find((item) => item.id === locationId);
  const stats = {
    registered: location?.initial_counts[flowTypeId] ?? 0,
    occupants: snapshot.location_counts[locationId]?.[flowTypeId] ?? 0,
    departed: 0,
    arrived: 0,
    approaching: 0,
  };
  for (const connection of connections) {
    const activity = connectionActivity(connection.id, flowTypeId);
    if (connection.from_location_id === locationId) {
      stats.departed += activity.departed;
    }
    if (connection.to_location_id === locationId) {
      stats.arrived += activity.arrived;
      stats.approaching += activity.inTransit;
    }
  }
  return stats;
}

function normalizeError(value: unknown): ApiError {
  if (value instanceof ApiError) return value;
  return new ApiError(0, "client_error", "页面遇到未预期的问题。");
}

function clearTimers() {
  if (pollTimer !== null) window.clearTimeout(pollTimer);
  if (seekTimer !== null) window.clearTimeout(seekTimer);
  if (playbackTimer !== null) window.clearTimeout(playbackTimer);
  if (draftPollTimer !== null) window.clearTimeout(draftPollTimer);
  pollTimer = null;
  seekTimer = null;
  playbackTimer = null;
  draftPollTimer = null;
  pollAbort?.abort();
  seekAbort?.abort();
  pollAbort = null;
  seekAbort = null;
}

async function loadInitial() {
  loading.value = true;
  const [scenarioResult, runsResult] = await Promise.allSettled([listScenarios(), listRuns()]);
  if (scenarioResult.status === "fulfilled") {
    scenarios.value = scenarioResult.value.items;
    selectedScenarioId.value = scenarioResult.value.items[0]?.config.scenario_id ?? null;
    selectedBundle.value = scenarioResult.value.items[0] ?? null;
  } else {
    error.value = normalizeError(scenarioResult.reason);
  }
  if (runsResult.status === "fulfilled") {
    recentRuns.value = runsResult.value.items;
  } else if (!error.value) {
    error.value = normalizeError(runsResult.reason);
  }
  const activeHistoryRun = recentRuns.value.find((run) => run.status === "running" || run.status === "paused");
  if (activeHistoryRun) {
    await selectRun(activeHistoryRun.id);
  } else if (!error.value) {
    worldView.value = "alliance";
  }
  loading.value = false;
}

function updateFromDetail(detail: { run: RunRecord; scenario: ScenarioBundle | null; latest_snapshot: SnapshotResponse }, force = false) {
  if (!force && selectedRun.value?.id === detail.run.id) {
    if (selectedRun.value.status === "paused" && detail.run.status === "running") return;
    if ((selectedRun.value.status === "ended" || selectedRun.value.status === "failed") && (detail.run.status === "running" || detail.run.status === "paused")) return;
    if (latestSnapshot.value && detail.latest_snapshot.tick < latestSnapshot.value.tick) return;
  }
  selectedRun.value = detail.run;
  worldView.value = "town";
  if (detail.scenario) selectedBundle.value = detail.scenario;
  latestSnapshot.value = detail.latest_snapshot;
  displayedSnapshot.value = followingLatest.value ? detail.latest_snapshot.state : displayedSnapshot.value;
  if (!displayedSnapshot.value) displayedSnapshot.value = detail.latest_snapshot.state;
}

async function refreshRuns() {
  try {
    recentRuns.value = (await listRuns()).items;
  } catch (cause) {
    error.value = normalizeError(cause);
  }
}

async function selectScenario(scenarioId: string) {
  if (activeRun.value) return;
  if (draftPollTimer !== null) window.clearTimeout(draftPollTimer);
  draftPollTimer = null;
  generationLoading.value = false;
  draft.value = null;
  selectedScenarioId.value = scenarioId;
  worldView.value = "town";
  selectedAllianceId.value = null;
  selectedBundle.value = scenarios.value.find((scenario) => scenario.config.scenario_id === scenarioId) ?? null;
  selectedFeatureId.value = null;
  latestSnapshot.value = null;
  displayedSnapshot.value = null;
}

async function pollDraft(draftId: string) {
  draftPollTimer = null;
  try {
    const latest = await getScenarioDraft(draftId);
    if (draft.value?.draft_id !== draftId) return;
    draft.value = latest;
    if (latest.compile_status === "ready" && latest.bundle) {
      selectedBundle.value = latest.bundle;
      generationLoading.value = false;
      return;
    }
    if (latest.compile_status === "failed") {
      generationLoading.value = false;
      error.value = new ApiError(422, latest.error?.code ?? "scenario_compile_failed", latest.error?.message ?? "城镇编译失败。");
      return;
    }
    draftPollTimer = window.setTimeout(() => pollDraft(draftId), 200);
  } catch (cause) {
    generationLoading.value = false;
    error.value = normalizeError(cause);
  }
}

async function generateTown(payload: { generationSeed?: number; population: number; generationSize?: "village" | "town" | "city"; name?: string }) {
  if (activeRun.value) return;
  if (draftPollTimer !== null) window.clearTimeout(draftPollTimer);
  generationLoading.value = true;
  error.value = null;
  worldView.value = "town";
  selectedScenarioId.value = null;
  selectedRun.value = null;
  selectedBundle.value = null;
  latestSnapshot.value = null;
  displayedSnapshot.value = null;
  selectedFeatureId.value = null;
  try {
    const created = await createScenarioDraft({
      population: payload.population,
      generator: "watabou-v1",
      ...(payload.name ? { name: payload.name } : {}),
      ...(payload.generationSeed === undefined ? {} : { generation_seed: payload.generationSeed }),
      ...(payload.generationSize ? { generation_size: payload.generationSize } : {}),
    });
    draft.value = created;
    if (created.compile_status === "ready" && created.bundle) {
      selectedBundle.value = created.bundle;
      generationLoading.value = false;
    } else {
      draftPollTimer = window.setTimeout(() => pollDraft(created.draft_id), 100);
    }
  } catch (cause) {
    generationLoading.value = false;
    error.value = normalizeError(cause);
  }
}

function selectAllianceSettlement(settlement: AllianceSettlement) {
  selectedAllianceId.value = settlement.id;
}

function enterAllianceSettlementById(settlementId: string) {
  const settlement = alliance.settlements.find((item) => item.id === settlementId);
  if (settlement) void enterAllianceSettlement(settlement);
}

async function enterAllianceSettlement(settlement = focusedAllianceSettlement.value) {
  if (!settlement || activeRun.value || allianceTransitioning.value) return;
  selectedAllianceId.value = settlement.id;
  allianceTransitioning.value = true;
  await nextTick();
  await generateTown({
    name: settlement.name,
    population: settlement.population,
    generationSeed: settlement.generationSeed,
    generationSize: settlement.kind === "capital" ? "city" : settlement.kind,
  });
  window.setTimeout(() => { allianceTransitioning.value = false; }, 360);
}

function backToAlliance() {
  if (activeRun.value || generationLoading.value) return;
  clearTimers();
  playbackPlaying.value = false;
  followingLatest.value = true;
  worldView.value = "alliance";
  selectedAllianceId.value = null;
  selectedScenarioId.value = null;
  selectedRun.value = null;
  selectedBundle.value = null;
  latestSnapshot.value = null;
  displayedSnapshot.value = null;
  selectedFeatureId.value = null;
  draft.value = null;
  error.value = null;
}

async function startRun(seed?: number) {
  if (!selectedScenarioId.value && !(draft.value?.compile_status === "ready" && draft.value.bundle)) return;
  clearTimers();
  playbackPlaying.value = false;
  loading.value = true;
  error.value = null;
  try {
    const detail = draft.value?.compile_status === "ready" && draft.value.bundle
      ? await createDraftRun(draft.value.draft_id, seed)
      : await createRun(selectedScenarioId.value!, seed);
    followingLatest.value = true;
    updateFromDetail(detail);
    await refreshRuns();
    schedulePoll();
  } catch (cause) {
    error.value = normalizeError(cause);
  } finally {
    loading.value = false;
  }
}

function handleStart(seed?: number) {
  if (worldView.value === "alliance") {
    worldRunStatus.value = "running";
    return;
  }
  void startRun(seed);
}

async function selectRun(runId: string) {
  clearTimers();
  draft.value = null;
  generationLoading.value = false;
  playbackPlaying.value = false;
  loading.value = true;
  error.value = null;
  try {
    const detail = await getRun(runId, true);
    followingLatest.value = true;
    updateFromDetail(detail);
    selectedScenarioId.value = detail.run.scenario_id;
    selectedFeatureId.value = null;
    if (detail.run.status === "running" || detail.run.status === "paused") schedulePoll();
  } catch (cause) {
    error.value = normalizeError(cause);
  } finally {
    loading.value = false;
  }
}

async function command(action: "pause" | "resume" | "end") {
  if (!selectedRun.value) return;
  if (action === "end" && !window.confirm("结束当前模拟？结束后仍可回放，但不能继续推进。")) return;
  if (pollTimer !== null) window.clearTimeout(pollTimer);
  pollTimer = null;
  pollAbort?.abort();
  pollAbort = null;
  loading.value = true;
  error.value = null;
  try {
    const result = await sendCommand(selectedRun.value.id, action);
    selectedRun.value = result.run;
    if (action === "end") {
      clearTimers();
      playbackPlaying.value = false;
    } else {
      if (action === "pause") updateFromDetail(await getRun(result.run.id, false), true);
      schedulePoll();
    }
    await refreshRuns();
  } catch (cause) {
    error.value = normalizeError(cause);
  } finally {
    loading.value = false;
  }
}

function handleCommand(action: "pause" | "resume" | "end") {
  if (worldView.value === "alliance") {
    worldRunStatus.value = action === "pause" ? "paused" : action === "resume" ? "running" : "ended";
    return;
  }
  void command(action);
}

async function setRate(rate: RunRate) {
  if (!selectedRun.value || !activeRun.value) return;
  loading.value = true;
  error.value = null;
  try {
    const result = await sendCommand(selectedRun.value.id, "set_rate", rate);
    selectedRun.value = result.run;
    schedulePoll();
  } catch (cause) {
    error.value = normalizeError(cause);
  } finally {
    loading.value = false;
  }
}

function handleSetRate(rate: RunRate) {
  if (worldView.value === "alliance") {
    worldRunRate.value = rate;
    return;
  }
  void setRate(rate);
}

function schedulePoll(delay = 1000) {
  if (!selectedRun.value || (selectedRun.value.status !== "running" && selectedRun.value.status !== "paused")) return;
  if (pollTimer !== null) window.clearTimeout(pollTimer);
  pollTimer = window.setTimeout(pollLatest, delay);
}

async function pollLatest() {
  pollTimer = null;
  const runId = selectedRun.value?.id;
  if (!runId || !activeRun.value) return;
  pollAbort?.abort();
  pollAbort = new AbortController();
  try {
    const detail = await getRun(runId, false, pollAbort.signal);
    if (selectedRun.value?.id !== runId) return;
    updateFromDetail(detail);
    if (detail.run.status === "running" || detail.run.status === "paused") {
      schedulePoll(1000);
    } else {
      await refreshRuns();
    }
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") return;
    error.value = normalizeError(cause);
    schedulePoll(2000);
  }
}

function seek(tick: number) {
  followingLatest.value = false;
  if (!selectedRun.value) return;
  if (seekTimer !== null) window.clearTimeout(seekTimer);
  seekTimer = window.setTimeout(async () => {
    seekTimer = null;
    const runId = selectedRun.value?.id;
    if (!runId) return;
    seekAbort?.abort();
    seekAbort = new AbortController();
    try {
      const snapshot = await getSnapshot(runId, tick, seekAbort.signal);
      if (selectedRun.value?.id === runId) displayedSnapshot.value = snapshot.state;
    } catch (cause) {
      if (!(cause instanceof DOMException && cause.name === "AbortError")) error.value = normalizeError(cause);
    }
  }, 80);
}

function followLatest() {
  playbackPlaying.value = false;
  if (playbackTimer !== null) window.clearTimeout(playbackTimer);
  followingLatest.value = true;
  if (latestSnapshot.value) displayedSnapshot.value = latestSnapshot.value.state;
}

function togglePlayback() {
  if (!replayable.value) return;
  playbackPlaying.value = !playbackPlaying.value;
  if (playbackPlaying.value) playNext();
  else if (playbackTimer !== null) window.clearTimeout(playbackTimer);
}

async function playNext() {
  if (!playbackPlaying.value || !selectedRun.value || displayedTick.value >= latestTick.value) {
    playbackPlaying.value = false;
    return;
  }
  const nextTick = displayedTick.value + 1;
  try {
    const snapshot = await getSnapshot(selectedRun.value.id, nextTick);
    if (playbackPlaying.value) {
      displayedSnapshot.value = snapshot.state;
      playbackTimer = window.setTimeout(playNext, 1000 / runRate.value);
    }
  } catch (cause) {
    playbackPlaying.value = false;
    error.value = normalizeError(cause);
  }
}

function toggleLayer(layer: keyof TownLayerVisibility) {
  layerVisibility.value[layer] = !layerVisibility.value[layer];
}


function toggleTheme() {
  theme.value = theme.value === "pearl" ? "night" : "pearl";
}
function openMobilePanel(panel: "controls" | "stats", event: MouseEvent) {
  mobilePanelTrigger = event.currentTarget as HTMLElement;
  mobilePanel.value = mobilePanel.value === panel ? null : panel;
}

function closeMobilePanel() {
  mobilePanel.value = null;
  void nextTick(() => mobilePanelTrigger?.focus());
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === "Escape" && mobilePanel.value) closeMobilePanel();
}

function updateResize(clientX: number) {
  const workspace = document.querySelector(".map-workspace");
  const rect = workspace?.getBoundingClientRect();
  if (!rect || !activeResize.value) return;
  if (activeResize.value === "rail") {
    railWidth.value = clampRailWidth(clientX - rect.left - resizeOffset);
  } else {
    inspectorWidth.value = clampInspectorWidth(rect.right - clientX - resizeOffset);
  }
}

function scheduleResize(clientX: number) {
  if (resizeFrame !== undefined) return;
  resizeFrame = window.requestAnimationFrame(() => {
    resizeFrame = undefined;
    updateResize(clientX);
  });
}

function startResize(kind: "rail" | "inspector", event: PointerEvent) {
  if (event.button !== 0) return;
  const workspace = document.querySelector(".map-workspace");
  const rect = workspace?.getBoundingClientRect();
  if (!rect) return;
  activeResize.value = kind;
  resizePointerId = event.pointerId;
  if (kind === "rail") {
    resizeOffset = event.clientX - rect.left - railWidth.value;
  } else {
    resizeOffset = rect.right - event.clientX - inspectorWidth.value;
  }
  (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
  document.documentElement.classList.add(kind === "rail" ? "is-resizing-rail" : "is-resizing-inspector");
  updateResize(event.clientX);
}

function moveResize(event: PointerEvent) {
  if (!activeResize.value || event.pointerId !== resizePointerId) return;
  scheduleResize(event.clientX);
}

function finishResize(event: PointerEvent) {
  if (!activeResize.value || event.pointerId !== resizePointerId) return;
  const handle = event.currentTarget as HTMLElement;
  if (resizeFrame !== undefined) {
    window.cancelAnimationFrame(resizeFrame);
    resizeFrame = undefined;
  }
  updateResize(event.clientX);
  if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
  activeResize.value = null;
  resizePointerId = undefined;
  resizeOffset = 0;
  document.documentElement.classList.remove("is-resizing-rail", "is-resizing-inspector");
  persistPanelLayout(railWidth.value, inspectorWidth.value);
}

function handleResizeKeydown(kind: "rail" | "inspector", event: KeyboardEvent) {
  const current = kind === "rail" ? railWidth.value : inspectorWidth.value;
  const minimum = kind === "rail" ? RAIL_MIN_WIDTH : INSPECTOR_MIN_WIDTH;
  const maximum = kind === "rail" ? RAIL_MAX_WIDTH : INSPECTOR_MAX_WIDTH;
  let next: number | undefined;
  if (event.key === "Home") next = minimum;
  if (event.key === "End") next = maximum;
  if (event.key === "ArrowLeft") next = current - KEYBOARD_STEP;
  if (event.key === "ArrowRight") next = current + KEYBOARD_STEP;
  if (next === undefined) return;
  event.preventDefault();
  const clamped = Math.min(Math.max(minimum, next), maximum);
  if (kind === "rail") railWidth.value = clamped;
  else inspectorWidth.value = clamped;
  persistPanelLayout(railWidth.value, inspectorWidth.value);
}

function featureName(featureId: string): string {
  const location = selectedBundle.value?.config.locations.find((item) => item.id === featureId);
  if (location) return location.name;
  const connection = selectedBundle.value?.config.connections.find((item) => item.id === featureId);
  if (connection) return `${locationName(connection.from_location_id)} → ${locationName(connection.to_location_id)}`;
  const street = selectedBundle.value?.town_skeleton?.streets.find((item) => item.id === featureId);
  const streetLabels: Record<string, string> = {
    primary: "主干道",
    ring: "环路",
    secondary: "次干道",
    lane: "车行巷",
    alley: "步行小巷",
  };
  return street ? `${streetLabels[street.kind] ?? "街道"} ${street.id}` : featureId;
}

function locationName(locationId: string): string {
  return selectedBundle.value?.config.locations.find((location) => location.id === locationId)?.name ?? locationId;
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("zh-CN").format(Math.round(value));
}

function statusLabel(status: RunRecord["status"] | null): string {
  if (!status) return "待命";
  return { running: "运行中", paused: "已暂停", ended: "已结束", failed: "异常终止" }[status];
}

onMounted(() => {
  document.documentElement.dataset.theme = theme.value;
  watch(theme, (value) => {
    document.documentElement.dataset.theme = value;
    try { localStorage.setItem(THEME_STORAGE_KEY, value); } catch { /* noop */ }
  });
  window.addEventListener("keydown", handleKeydown);
  void loadInitial();
});
onUnmounted(() => {
  clearTimers();
  window.removeEventListener("keydown", handleKeydown);
  if (resizeFrame !== undefined) window.cancelAnimationFrame(resizeFrame);
  document.documentElement.classList.remove("is-resizing-rail", "is-resizing-inspector");
});
</script>

<template>
  <div class="app-shell">
    <main class="map-workspace" :style="workspaceStyle">
      <AllianceMap
        v-if="worldView === 'alliance'"
        :alliance="alliance"
        :selected-id="selectedAllianceId"
        :theme="theme"
        :density="flowDensity"
        :running="worldRunStatus === 'running'"
        :run-rate="worldRunRate"
        @select-settlement="selectAllianceSettlement"
      />
      <CityMap
        v-else
        :bundle="selectedBundle"
        :snapshot="displayedSnapshot"
        :run-rate="runRate"
        :running="selectedRun?.status === 'running' && followingLatest"
        :selected-feature-id="selectedFeatureId"
        :visibility="layerVisibility"
        :analysis-flow="analysisFlow"
        :flow-density="flowDensity"
        :map-clarity="mapClarity"
        :theme="theme"
        @select-feature="selectedFeatureId = $event"
        @set-analysis-flow="analysisFlow = $event"
      />

      <header class="map-header">
        <div class="map-title" aria-live="polite">
          <button v-if="worldView === 'town'" class="map-breadcrumb" type="button" :disabled="activeRun || generationLoading" @click="backToAlliance">
            人类联盟总览
          </button>
          <h1>{{ worldView === "alliance" ? alliance.name : activeTownName }}</h1>
          <p v-if="worldView === 'alliance'">
            <span class="status-dot status-idle"></span>
            {{ allianceCounts.capitals }} 主城
            <span aria-hidden="true">·</span>
            {{ allianceCounts.towns }} 城镇
            <span aria-hidden="true">·</span>
            {{ allianceCounts.villages }} 村庄
            <span aria-hidden="true">·</span>
            {{ worldRunStatus === "running" ? "交通运行中" : worldRunStatus === "paused" ? "交通已暂停" : "交通待启动" }}
          </p>
          <p v-else>
            <span class="status-dot" :class="`status-${selectedRun?.status ?? 'idle'}`"></span>
            {{ statusLabel(selectedRun?.status ?? null) }}
            <span aria-hidden="true">·</span>
            {{ formatNumber(totalPeople || selectedBundle?.town_skeleton?.requested_population || 0) }} 居民
            <span v-if="selectedBundle?.town_skeleton" aria-hidden="true">·</span>
            <span v-if="selectedBundle?.town_skeleton">SEED {{ selectedBundle.town_skeleton.generation_seed }}</span>
          </p>
        </div>
      </header>

      <div class="topbar-readout" aria-live="polite">
        <span class="tick-readout">{{ worldView === "alliance" ? `WORLD / ${worldRunStatus.toUpperCase()}` : `T+${displayedTick.toString().padStart(4, "0")}` }}</span>
      </div>
      <div v-if="loading" class="map-loading" role="status"><span class="loading-pip"></span>正在同步</div>

      <nav class="mobile-panel-switcher" aria-label="移动面板">
        <button type="button" :aria-pressed="mobilePanel === 'controls'" @click="openMobilePanel('controls', $event)">
          <Menu :size="17" aria-hidden="true" />控制
        </button>
        <button type="button" :aria-pressed="mobilePanel === 'stats'" @click="openMobilePanel('stats', $event)">
          <Activity :size="17" aria-hidden="true" />统计
        </button>
      </nav>
      <button v-if="mobilePanel" class="mobile-panel-backdrop" type="button" aria-label="关闭面板" @click="closeMobilePanel"></button>

      <div
        class="panel-resizer panel-resizer--inspector"
        :class="{ 'is-active': activeResize === 'inspector' }"
        role="separator"
        aria-label="调整统计面板宽度"
        aria-orientation="vertical"
        :aria-valuemin="INSPECTOR_MIN_WIDTH"
        :aria-valuemax="INSPECTOR_MAX_WIDTH"
        :aria-valuenow="Math.round(inspectorWidth)"
        :aria-valuetext="`${Math.round(inspectorWidth)} 像素`"
        tabindex="0"
        @pointerdown="startResize('inspector', $event)"
        @pointermove="moveResize"
        @pointerup="finishResize"
        @pointercancel="finishResize"
        @keydown="handleResizeKeydown('inspector', $event)"
      ></div>

      <aside
        class="map-inspector"
        :class="{ 'map-inspector--empty': !selectedFeatureId && !selectedAllianceId, 'mobile-panel--open': mobilePanel === 'stats' }"
        aria-label="统计详情"
      >
        <div class="inspector-heading">
          <div>
            <div class="section-kicker">{{ worldView === "alliance" ? "联盟聚落" : selectedFeatureId ? "当前焦点" : "城镇概览" }}</div>
            <strong>{{ worldView === "alliance" ? focusedAllianceSettlement?.name ?? alliance.name : selectedFeatureId ? featureName(selectedFeatureId) : activeTownName }}</strong>
            <small v-if="worldView === 'town' && selectedFeatureId" class="inspector-town-name">{{ activeTownName }}</small>
          </div>
          <button
            v-if="selectedFeatureId || selectedAllianceId || mobilePanel === 'stats'"
            class="icon-button icon-button--small"
            type="button"
            :aria-label="mobilePanel === 'stats' ? '关闭统计面板' : '清除对象选择'"
            :title="mobilePanel === 'stats' ? '关闭面板' : '清除选择'"
            @click="mobilePanel === 'stats' ? closeMobilePanel() : (worldView === 'alliance' ? selectedAllianceId = null : selectedFeatureId = null)"
          >
            <X :size="15" aria-hidden="true" />
          </button>
        </div>
        <div v-if="worldView === 'alliance' && focusedAllianceSettlement" class="alliance-inspector">
          <p class="alliance-inspector__summary">
            {{ focusedAllianceSettlement.kind === "capital" ? "主城" : focusedAllianceSettlement.kind === "town" ? "城镇" : "村庄" }} · {{ focusedAllianceSettlement.region }}
          </p>
          <dl class="metric-list">
            <div><dt>登记人口</dt><dd>{{ formatNumber(focusedAllianceSettlement.population) }}</dd></div>
            <div><dt>上级聚落</dt><dd>{{ focusedAllianceParent?.name ?? "联盟直辖" }}</dd></div>
            <div><dt>下辖聚落</dt><dd>{{ focusedAllianceSettlement.children.length }} 个</dd></div>
            <div v-if="focusedAllianceSettlement.kind === 'capital' && focusedAllianceSettlement.influenceRadius"><dt>辐射半径</dt><dd>{{ Math.round(focusedAllianceSettlement.influenceRadius) }} 地图单位</dd></div>
          </dl>
          <button class="action-button action-button--primary alliance-enter-button" type="button" :disabled="generationLoading || activeRun" @click="enterAllianceSettlement()">
            进入聚落地图
          </button>
        </div>
        <div v-else-if="worldView === 'alliance'" class="alliance-overview">
          <p>点击地图上的聚落查看层级、人口与进入入口。</p>
          <dl class="metric-list overview-metrics">
            <div><dt>主城</dt><dd>{{ allianceCounts.capitals }}</dd></div>
            <div><dt>城镇</dt><dd>{{ allianceCounts.towns }}</dd></div>
            <div><dt>村庄</dt><dd>{{ allianceCounts.villages }}</dd></div>
            <div><dt>联盟道路</dt><dd>{{ alliance.roads.length }}</dd></div>
          </dl>
        </div>
        <div v-else-if="selectedLocation && selectedLocationStats" class="location-inspector">
          <div v-if="selectedLocationStats.people" class="flow-stats-block">
            <div class="section-kicker">人流</div>
            <dl class="metric-list">
              <div><dt>登记人口</dt><dd>{{ formatNumber(selectedLocationStats.people.registered) }}</dd></div>
              <div><dt>当前建筑内</dt><dd>{{ formatNumber(selectedLocationStats.people.occupants) }}</dd></div>
              <div><dt>本 tick 经过</dt><dd>{{ formatNumber(selectedLocationStats.people.departed + selectedLocationStats.people.arrived) }}</dd></div>
              <div><dt>本 tick 出发</dt><dd>{{ formatNumber(selectedLocationStats.people.departed) }}</dd></div>
              <div><dt>本 tick 到达</dt><dd>{{ formatNumber(selectedLocationStats.people.arrived) }}</dd></div>
              <div><dt>即将到达</dt><dd>{{ formatNumber(selectedLocationStats.people.approaching) }}</dd></div>
            </dl>
          </div>
          <div v-if="selectedLocationStats.vehicle" class="flow-stats-block">
            <div class="section-kicker">车流</div>
            <dl class="metric-list">
              <div><dt>登记车辆</dt><dd>{{ formatNumber(selectedLocationStats.vehicle.registered) }}</dd></div>
              <div><dt>当前驻留</dt><dd>{{ formatNumber(selectedLocationStats.vehicle.occupants) }}</dd></div>
              <div><dt>本 tick 经过</dt><dd>{{ formatNumber(selectedLocationStats.vehicle.departed + selectedLocationStats.vehicle.arrived) }}</dd></div>
              <div><dt>本 tick 出发</dt><dd>{{ formatNumber(selectedLocationStats.vehicle.departed) }}</dd></div>
              <div><dt>本 tick 到达</dt><dd>{{ formatNumber(selectedLocationStats.vehicle.arrived) }}</dd></div>
              <div><dt>即将到达</dt><dd>{{ formatNumber(selectedLocationStats.vehicle.approaching) }}</dd></div>
            </dl>
          </div>
          <div v-if="selectedAggregateDistricts.length || selectedAggregateBuildings.length" class="aggregation-block">
            <div class="section-kicker">统计范围</div>
            <div v-if="selectedAggregateDistricts.length" class="aggregation-group">
              <span class="aggregation-label">居民区（{{ selectedAggregateDistricts.length }}）</span>
              <ul class="aggregation-list">
                <li v-for="feature in selectedAggregateDistricts" :key="feature.id">{{ feature.label }}</li>
              </ul>
            </div>
            <div v-if="selectedAggregateBuildings.length" class="aggregation-note">
              关联建筑 {{ formatNumber(selectedAggregateBuildings.length) }} 座
            </div>
          </div>
          <div class="metric-list"><div><dt>坐标</dt><dd>{{ selectedLocation.position[0] }}, {{ selectedLocation.position[1] }}</dd></div></div>
        </div>
        <div v-else-if="selectedStreet && selectedStreetStats" class="street-inspector">
          <div v-if="selectedStreetStats.people" class="flow-stats-block">
            <div class="section-kicker">人流方向</div>
            <dl class="metric-list">
              <div><dt>道路在途</dt><dd>{{ formatNumber(selectedStreetStats.people.in_transit) }}</dd></div>
              <div><dt>顺道路定义 →</dt><dd>{{ formatNumber(selectedStreetStats.people.forward_in_transit) }}</dd></div>
              <div><dt>逆道路定义 ←</dt><dd>{{ formatNumber(selectedStreetStats.people.reverse_in_transit) }}</dd></div>
              <div><dt>净流向</dt><dd>{{ selectedStreetStats.people.forward_in_transit >= selectedStreetStats.people.reverse_in_transit ? "顺向" : "逆向" }} {{ formatNumber(Math.abs(selectedStreetStats.people.forward_in_transit - selectedStreetStats.people.reverse_in_transit)) }}</dd></div>
            </dl>
          </div>
          <div v-if="selectedStreetStats.vehicle" class="flow-stats-block">
            <div class="section-kicker">车流方向</div>
            <dl class="metric-list">
              <div><dt>道路在途</dt><dd>{{ formatNumber(selectedStreetStats.vehicle.in_transit) }}</dd></div>
              <div><dt>顺道路定义 →</dt><dd>{{ formatNumber(selectedStreetStats.vehicle.forward_in_transit) }}</dd></div>
              <div><dt>逆道路定义 ←</dt><dd>{{ formatNumber(selectedStreetStats.vehicle.reverse_in_transit) }}</dd></div>
              <div><dt>净流向</dt><dd>{{ selectedStreetStats.vehicle.forward_in_transit >= selectedStreetStats.vehicle.reverse_in_transit ? "顺向" : "逆向" }} {{ formatNumber(Math.abs(selectedStreetStats.vehicle.forward_in_transit - selectedStreetStats.vehicle.reverse_in_transit)) }}</dd></div>
            </dl>
          </div>
          <dl class="metric-list">
            <div><dt>关联路线</dt><dd>{{ formatNumber(selectedStreetRoutes.length) }} 条</dd></div>
            <div><dt>道路类型</dt><dd>{{ selectedStreet.kind }}</dd></div>
            <div><dt>通行方式</dt><dd>{{ selectedStreet.pedestrian_access !== false ? "行人" : "禁行人" }} · {{ selectedStreet.vehicle_access !== false ? "车辆" : "禁车辆" }}</dd></div>
          </dl>
        </div>
        <dl v-else-if="selectedConnection && displayedSnapshot && flowId" class="metric-list">
          <div><dt>出发点</dt><dd>{{ locationName(selectedConnection.from_location_id) }}</dd></div>
          <div><dt>终点</dt><dd>{{ locationName(selectedConnection.to_location_id) }}</dd></div>
          <div><dt>人流在途</dt><dd>{{ formatNumber(connectionActivity(selectedConnection.id, flowId).inTransit) }}</dd></div>
          <div><dt>人流本 tick 出发</dt><dd>{{ formatNumber(connectionDeparted(selectedConnection.id, flowId)) }}</dd></div>
          <div><dt>人流本 tick 到达</dt><dd>{{ formatNumber(connectionArrived(selectedConnection.id, flowId)) }}</dd></div>
          <template v-if="vehicleFlowId">
            <div><dt>车流在途</dt><dd>{{ formatNumber(connectionActivity(selectedConnection.id, vehicleFlowId).inTransit) }}</dd></div>
            <div><dt>车流本 tick 出发</dt><dd>{{ formatNumber(connectionDeparted(selectedConnection.id, vehicleFlowId)) }}</dd></div>
            <div><dt>车流本 tick 到达</dt><dd>{{ formatNumber(connectionArrived(selectedConnection.id, vehicleFlowId)) }}</dd></div>
          </template>
          <div><dt>道路容量</dt><dd>{{ formatNumber(selectedConnection.capacity_per_tick[flowId] ?? 0) }} / 秒</dd></div>
          <div><dt>旅行时间</dt><dd>{{ selectedConnection.travel_time_ticks }} 秒</dd></div>
        </dl>
        <dl v-else-if="worldView === 'town'" class="metric-list overview-metrics">
          <div><dt>当前居民</dt><dd>{{ formatNumber(totalPeople || selectedBundle?.town_skeleton?.requested_population || 0) }}</dd></div>
          <div><dt>建筑</dt><dd>{{ formatNumber(selectedBundle?.town_skeleton?.buildings.length || 0) }}</dd></div>
          <div><dt>物理街道</dt><dd>{{ formatNumber(selectedBundle?.town_skeleton?.streets.length || 0) }}</dd></div>
          <div><dt>当前 tick</dt><dd>T+{{ displayedTick.toString().padStart(4, "0") }}</dd></div>
        </dl>
        <div v-if="selectedRun?.error_message" class="stats-alert" role="alert">
          <AlertTriangle :size="16" aria-hidden="true" />
          <span>{{ selectedRun.error_message }}</span>
        </div>
      </aside>

      <aside class="menu-drawer" :class="{ 'mobile-panel--open': mobilePanel === 'controls' }" aria-label="控制面板">
        <header class="drawer-header">
          <div>
            <p>WORLD SIMULATION / 01</p>
            <h2 id="menu-title">{{ worldView === "alliance" ? "世界交通" : "城镇流量" }}</h2>
          </div>
          <button class="icon-button icon-button--small mobile-panel-close" type="button" aria-label="关闭控制面板" title="关闭面板" @click="closeMobilePanel">
            <X :size="15" aria-hidden="true" />
          </button>
          <button class="theme-toggle" type="button" :aria-label="theme === 'pearl' ? '切换至夜晚' : '切换至白天'" :title="theme === 'pearl' ? '夜晚模式' : '白天模式'" @click="toggleTheme">
            <Sun v-if="theme === 'night'" :size="16" aria-hidden="true" />
            <Moon v-else :size="16" aria-hidden="true" />
          </button>
        </header>
        <div class="drawer-scroll">
            <ControlRail
              :scenarios="scenarios"
              :selected-scenario-id="selectedScenarioId"
              :runs="recentRuns"
              :selected-run="selectedRun"
              :loading="loading"
              :error="error"
              :draft="draft"
              :generation-loading="generationLoading"
              :layer-visibility="layerVisibility"
              :flow-density="flowDensity"
              :map-clarity="mapClarity"
              :world-view="worldView"
              :alliance-settlements="alliance.settlements"
              :selected-alliance-id="selectedAllianceId"
              :world-run-status="worldRunStatus"
              :world-run-rate="worldRunRate"
              @select-scenario="selectScenario"
              @select-run="selectRun"
              @start="handleStart"
              @command="handleCommand"
              @set-rate="handleSetRate"
              @generate-town="generateTown"
              @toggle-layer="toggleLayer"
              @set-flow-density="flowDensity = $event"
              @set-map-clarity="mapClarity = $event"
              @select-alliance-settlement="enterAllianceSettlementById"
            />
        </div>
      </aside>

      <div
        class="panel-resizer panel-resizer--rail"
        :class="{ 'is-active': activeResize === 'rail' }"
        role="separator"
        aria-label="调整控制面板宽度"
        aria-orientation="vertical"
        :aria-valuemin="RAIL_MIN_WIDTH"
        :aria-valuemax="RAIL_MAX_WIDTH"
        :aria-valuenow="Math.round(railWidth)"
        :aria-valuetext="`${Math.round(railWidth)} 像素`"
        tabindex="0"
        @pointerdown="startResize('rail', $event)"
        @pointermove="moveResize"
        @pointerup="finishResize"
        @pointercancel="finishResize"
        @keydown="handleResizeKeydown('rail', $event)"
      ></div>
    </main>

    <PlaybackTimeline
      :displayed-tick="displayedTick"
      :latest-tick="latestTick"
      :following-latest="followingLatest"
      :running="selectedRun?.status === 'running'"
      :replayable="replayable"
      :playing="playbackPlaying"
      @seek="seek"
      @follow-latest="followLatest"
      @toggle-play="togglePlayback"
    />
  </div>
</template>
