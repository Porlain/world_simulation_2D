<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { AlertTriangle, Menu, X } from "lucide-vue-next";
import ControlRail from "./ControlRail.vue";
import CityMap from "./CityMap.vue";
import PlaybackTimeline from "./PlaybackTimeline.vue";
import type { TownLayerVisibility } from "./townLayers";
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
const menuDialog = ref<HTMLDialogElement | null>(null);
const menuOpen = ref(false);
const selectedFeatureId = ref<string | null>(null);
const draft = ref<ScenarioDraft | null>(null);
const generationLoading = ref(false);
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

const selectedLocation = computed(() => {
  if (!selectedFeatureId.value || !selectedBundle.value) return null;
  return selectedBundle.value.config.locations.find((location) => location.id === selectedFeatureId.value) ?? null;
});

const selectedConnection = computed<ConnectionConfig | null>(() => {
  if (!selectedFeatureId.value || !selectedBundle.value) return null;
  return selectedBundle.value.config.connections.find((connection) => connection.id === selectedFeatureId.value) ?? null;
});

const totalPeople = computed(() => displayedSnapshot.value?.totals[flowId.value ?? ""] ?? 0);

function connectionDeparted(connectionId: string, flowTypeId: string): number {
  const snapshot = displayedSnapshot.value;
  if (!snapshot) return 0;
  if (snapshot.schema_version === 2) return snapshot.connections[connectionId]?.[flowTypeId]?.departed ?? 0;
  return snapshot.connection_activity[connectionId]?.[flowTypeId]?.departed ?? 0;
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
  loading.value = false;
}

function updateFromDetail(detail: { run: RunRecord; scenario: ScenarioBundle | null; latest_snapshot: SnapshotResponse }, force = false) {
  if (!force && selectedRun.value?.id === detail.run.id) {
    if (selectedRun.value.status === "paused" && detail.run.status === "running") return;
    if ((selectedRun.value.status === "ended" || selectedRun.value.status === "failed") && (detail.run.status === "running" || detail.run.status === "paused")) return;
    if (latestSnapshot.value && detail.latest_snapshot.tick < latestSnapshot.value.tick) return;
  }
  selectedRun.value = detail.run;
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
  selectedBundle.value = scenarios.value.find((scenario) => scenario.config.scenario_id === scenarioId) ?? null;
  selectedFeatureId.value = null;
  latestSnapshot.value = null;
  displayedSnapshot.value = null;
  closeMenu();
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

async function generateTown(payload: { generationSeed?: number; population: number }) {
  if (activeRun.value) return;
  if (draftPollTimer !== null) window.clearTimeout(draftPollTimer);
  generationLoading.value = true;
  error.value = null;
  selectedScenarioId.value = null;
  selectedRun.value = null;
  latestSnapshot.value = null;
  displayedSnapshot.value = null;
  selectedFeatureId.value = null;
  try {
    const created = await createScenarioDraft({
      population: payload.population,
      ...(payload.generationSeed === undefined ? {} : { generation_seed: payload.generationSeed }),
    });
    draft.value = created;
    closeMenu();
    if (created.compile_status === "ready" && created.bundle) {
      selectedBundle.value = created.bundle;
      generationLoading.value = false;
    } else {
      selectedBundle.value = null;
      draftPollTimer = window.setTimeout(() => pollDraft(created.draft_id), 100);
    }
  } catch (cause) {
    generationLoading.value = false;
    error.value = normalizeError(cause);
  }
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
    closeMenu();
  } catch (cause) {
    error.value = normalizeError(cause);
  } finally {
    loading.value = false;
  }
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
    closeMenu();
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

function openMenu() {
  if (!menuDialog.value?.open) menuDialog.value?.showModal();
  menuOpen.value = true;
}

function closeMenu() {
  if (menuDialog.value?.open) menuDialog.value.close();
  menuOpen.value = false;
}

function closeMenuFromBackdrop(event: MouseEvent) {
  if (event.target === menuDialog.value) closeMenu();
}

function toggleLayer(layer: keyof TownLayerVisibility) {
  layerVisibility.value[layer] = !layerVisibility.value[layer];
}

function featureName(featureId: string): string {
  const location = selectedBundle.value?.config.locations.find((item) => item.id === featureId);
  if (location) return location.name;
  const connection = selectedBundle.value?.config.connections.find((item) => item.id === featureId);
  return connection ? `${connection.from_location_id} → ${connection.to_location_id}` : featureId;
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("zh-CN").format(Math.round(value));
}

function statusLabel(status: RunRecord["status"] | null): string {
  if (!status) return "待命";
  return { running: "运行中", paused: "已暂停", ended: "已结束", failed: "异常终止" }[status];
}

onMounted(loadInitial);
onUnmounted(() => {
  clearTimers();
  closeMenu();
});
</script>

<template>
  <div class="app-shell">
    <main class="map-workspace">
      <CityMap
        :bundle="selectedBundle"
        :snapshot="displayedSnapshot"
        :run-rate="runRate"
        :running="selectedRun?.status === 'running' && followingLatest"
        :selected-feature-id="selectedFeatureId"
        :visibility="layerVisibility"
        @select-feature="selectedFeatureId = $event"
      />

      <header class="map-header">
        <div class="map-title" aria-live="polite">
          <h1>{{ selectedBundle?.config.name ?? "世界模拟" }}</h1>
          <p>
            <span class="status-dot" :class="`status-${selectedRun?.status ?? 'idle'}`"></span>
            {{ statusLabel(selectedRun?.status ?? null) }}
            <span aria-hidden="true">·</span>
            {{ formatNumber(totalPeople || selectedBundle?.town_skeleton?.requested_population || 0) }} 居民
            <span v-if="selectedBundle?.town_skeleton" aria-hidden="true">·</span>
            <span v-if="selectedBundle?.town_skeleton">SEED {{ selectedBundle.town_skeleton.generation_seed }}</span>
          </p>
        </div>
        <button class="menu-button" type="button" aria-label="打开 Menu" title="打开 Menu" @click="openMenu">
          <Menu :size="15" aria-hidden="true" />
          <span>Menu</span>
        </button>
      </header>

      <div class="topbar-readout" aria-live="polite">
        <span class="tick-readout">T+{{ displayedTick.toString().padStart(4, "0") }}</span>
      </div>
      <div v-if="loading" class="map-loading" role="status"><span class="loading-pip"></span>正在同步</div>

      <aside v-if="selectedFeatureId && !menuOpen" class="map-inspector" aria-label="当前选中对象">
        <div class="inspector-heading">
          <div>
            <div class="section-kicker">当前焦点</div>
            <strong>{{ featureName(selectedFeatureId) }}</strong>
          </div>
          <button class="icon-button icon-button--small" type="button" aria-label="关闭对象信息" title="关闭" @click="selectedFeatureId = null">
            <X :size="15" aria-hidden="true" />
          </button>
        </div>
        <dl v-if="selectedLocation && displayedSnapshot && flowId" class="metric-list">
          <div><dt>地点存量</dt><dd>{{ formatNumber(displayedSnapshot.location_counts[selectedLocation.id]?.[flowId] ?? 0) }}</dd></div>
          <div><dt>坐标</dt><dd>{{ selectedLocation.position[0] }}, {{ selectedLocation.position[1] }}</dd></div>
        </dl>
        <dl v-else-if="selectedConnection && displayedSnapshot && flowId" class="metric-list">
          <div><dt>刚刚出发</dt><dd>{{ formatNumber(connectionDeparted(selectedConnection.id, flowId)) }}</dd></div>
          <div><dt>道路容量</dt><dd>{{ formatNumber(selectedConnection.capacity_per_tick[flowId] ?? 0) }} / 秒</dd></div>
          <div><dt>旅行时间</dt><dd>{{ selectedConnection.travel_time_ticks }} 秒</dd></div>
        </dl>
      </aside>

      <dialog ref="menuDialog" class="menu-dialog" aria-labelledby="menu-title" @close="menuOpen = false" @click="closeMenuFromBackdrop">
        <div class="menu-drawer">
          <header class="drawer-header">
            <div>
              <p>WORLD SIMULATION / 01</p>
              <h2 id="menu-title">Menu</h2>
            </div>
            <button class="icon-button" type="button" aria-label="关闭 Menu" title="关闭 Menu" @click.stop="closeMenu">
              <X :size="18" aria-hidden="true" />
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
              @select-scenario="selectScenario"
              @select-run="selectRun"
              @start="startRun"
              @command="command"
              @set-rate="setRate"
              @generate-town="generateTown"
              @toggle-layer="toggleLayer"
            />
            <section v-if="selectedFeatureId" class="drawer-selection">
              <div class="section-kicker">当前焦点</div>
              <div class="focus-line"><span class="focus-marker"></span><strong>{{ featureName(selectedFeatureId) }}</strong></div>
              <dl v-if="selectedLocation && displayedSnapshot && flowId" class="metric-list">
                <div><dt>地点存量</dt><dd>{{ formatNumber(displayedSnapshot.location_counts[selectedLocation.id]?.[flowId] ?? 0) }}</dd></div>
                <div><dt>坐标</dt><dd>{{ selectedLocation.position[0] }}, {{ selectedLocation.position[1] }}</dd></div>
              </dl>
              <dl v-else-if="selectedConnection && displayedSnapshot && flowId" class="metric-list">
                <div><dt>刚刚出发</dt><dd>{{ formatNumber(connectionDeparted(selectedConnection.id, flowId)) }}</dd></div>
                <div><dt>道路容量</dt><dd>{{ formatNumber(selectedConnection.capacity_per_tick[flowId] ?? 0) }} / 秒</dd></div>
                <div><dt>旅行时间</dt><dd>{{ selectedConnection.travel_time_ticks }} 秒</dd></div>
              </dl>
            </section>
            <div v-if="selectedRun?.error_message" class="stats-alert" role="alert">
              <AlertTriangle :size="16" aria-hidden="true" />
              <span>{{ selectedRun.error_message }}</span>
            </div>
          </div>
        </div>
      </dialog>
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
