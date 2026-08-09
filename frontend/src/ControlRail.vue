<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { CircleAlert, Gauge, History, Layers3, MapPinned, Pause, Play, RotateCcw, ScanLine, Square } from "lucide-vue-next";
import type { ApiError, RunRate, RunRecord, RunStatus, ScenarioBundle, ScenarioDraft } from "./api";
import { MAP_CLARITY_OPTIONS, type MapClarity } from "./renderSettings";
import type { TownLayerVisibility } from "./townLayers";
import type { AllianceSettlement } from "./alliance";

const props = defineProps<{
  scenarios: ScenarioBundle[];
  selectedScenarioId: string | null;
  runs: RunRecord[];
  selectedRun: RunRecord | null;
  loading: boolean;
  error: ApiError | null;
  draft: ScenarioDraft | null;
  generationLoading: boolean;
  layerVisibility: TownLayerVisibility;
  flowDensity: number;
  mapClarity: MapClarity;
  worldView: "alliance" | "town";
  allianceSettlements: AllianceSettlement[];
  selectedAllianceId: string | null;
  worldRunStatus: RunStatus | "idle";
  worldRunRate: RunRate;
}>();

const emit = defineEmits<{
  (event: "select-scenario", scenarioId: string): void;
  (event: "select-run", runId: string): void;
  (event: "start", seed?: number): void;
  (event: "command", action: "pause" | "resume" | "end"): void;
  (event: "set-rate", rate: RunRate): void;
  (event: "generate-town", payload: { generationSeed?: number; population: number; generationSize?: "village" | "town" | "city" }): void;
  (event: "toggle-layer", layer: keyof TownLayerVisibility): void;
  (event: "set-flow-density", density: number): void;
  (event: "set-map-clarity", clarity: MapClarity): void;
  (event: "select-alliance-settlement", settlementId: string): void;
}>();

const seedInput = ref("");
const generationSeedInput = ref("");
const generationSizeInput = ref<"village" | "town" | "city">("town");
const populationInput = ref("11499");
const rateOptions: RunRate[] = [0.5, 1, 2, 4];
const layerOptions: Array<{ key: keyof TownLayerVisibility; label: string }> = [
  { key: "walls", label: "城墙" },
  { key: "roads", label: "道路" },
  { key: "buildings", label: "建筑" },
  { key: "landmarks", label: "功能建筑" },
  { key: "people", label: "人流样本" },
  { key: "vehicles", label: "车辆样本" },
  { key: "heat", label: "方向热力" },
];

const selectedScenario = computed(() =>
  props.scenarios.find((scenario) => scenario.config.scenario_id === props.selectedScenarioId),
);
const selectedClarity = computed(() =>
  MAP_CLARITY_OPTIONS.find((option) => option.value === props.mapClarity) ?? MAP_CLARITY_OPTIONS[1],
);

// scenario_id → 城镇名 映射表
const scenarioNameById = computed(() => {
  const map: Record<string, string> = {};
  for (const s of props.scenarios) {
    map[s.config.scenario_id] = s.config.name;
  }
  return map;
});

const activeRun = computed(() => props.selectedRun?.status === "running" || props.selectedRun?.status === "paused");
const controlStatus = computed<RunStatus | "idle">(() =>
  props.worldView === "alliance" ? props.worldRunStatus : props.selectedRun?.status ?? "idle",
);
const controlsActive = computed(() => controlStatus.value === "running" || controlStatus.value === "paused");
const canStart = computed(() => {
  if (props.worldView === "alliance") return controlStatus.value === "idle" || controlStatus.value === "ended" || controlStatus.value === "failed";
  return (Boolean(props.selectedScenarioId) || (props.draft?.compile_status === "ready" && Boolean(props.draft.bundle)))
    && !activeRun.value;
});

function start() {
  const parsed = seedInput.value.trim() === "" ? undefined : Number(seedInput.value);
  emit("start", parsed !== undefined && Number.isSafeInteger(parsed) ? parsed : undefined);
}

function generateTown() {
  const population = Number(populationInput.value);
  const seedText = generationSeedInput.value.trim();
  const generationSeed = seedText === "" ? Math.floor(Math.random() * 9_007_199_254_740_991) : Number(seedText);
  if (!Number.isSafeInteger(population) || population < 100 || population > 100_000) return;
  if (!Number.isSafeInteger(generationSeed) || generationSeed < 0) return;
  emit("generate-town", { population, generationSeed, generationSize: generationSizeInput.value });
}

const PAGE_SIZE = 5;
const MAX_ITEMS = 20;

const historyPage = ref(1);

// 最多展示 20 条，取按 started_at 降序后的前 20
const topRuns = computed(() =>
  [...props.runs].sort((a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime()).slice(0, MAX_ITEMS),
);

const pagedRuns = computed(() => {
  const start = (historyPage.value - 1) * PAGE_SIZE;
  return topRuns.value.slice(start, start + PAGE_SIZE);
});

const historyPageCount = computed(() => Math.max(1, Math.ceil(topRuns.value.length / PAGE_SIZE)));

const runsCount = computed(() => props.runs.length);

// 当数据变化导致页数缩小时回弹到有效页
watch(topRuns, () => {
  if (historyPage.value > historyPageCount.value) historyPage.value = historyPageCount.value;
});

function setHistoryPage(page: number) {
  historyPage.value = Math.min(Math.max(1, page), historyPageCount.value);
}

function runStatusClass(status: RunRecord["status"]): string {
  return { running: "is-running", paused: "is-paused", ended: "is-ended", failed: "is-failed" }[status];
}

function statusLabel(status: RunRecord["status"]): string {
  return { running: "RUNNING", paused: "PAUSED", ended: "ENDED", failed: "FAILED" }[status];
}

function timeLabel(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(value));
}
</script>

<template>
  <aside class="control-rail" aria-label="运行控制">
    <section class="rail-section rail-section--controls">
      <div class="section-kicker"><Gauge :size="14" aria-hidden="true" /> 调度</div>
      <div class="seed-row">
        <label class="field-label" for="seed-input">Seed</label>
        <input id="seed-input" v-model="seedInput" class="text-field" inputmode="numeric" placeholder="自动生成" />
      </div>
      <button class="action-button action-button--primary" type="button" :disabled="!canStart || loading || generationLoading" @click="start">
        <Play :size="16" fill="currentColor" aria-hidden="true" />
        <span>启动模拟</span>
      </button>
      <div class="command-grid">
        <button class="action-button" type="button" :disabled="controlStatus !== 'running' || loading" title="暂停当前运行" @click="emit('command', 'pause')">
          <Pause :size="15" aria-hidden="true" /><span>暂停</span>
        </button>
        <button class="action-button" type="button" :disabled="controlStatus !== 'paused' || loading" title="继续当前运行" @click="emit('command', 'resume')">
          <RotateCcw :size="15" aria-hidden="true" /><span>继续</span>
        </button>
        <button class="action-button action-button--danger" type="button" :disabled="!controlsActive || loading" title="结束当前运行" @click="emit('command', 'end')">
          <Square :size="14" fill="currentColor" aria-hidden="true" /><span>结束</span>
        </button>
      </div>
      <label class="field-label" for="rate-select">运行速率</label>
      <select
        id="rate-select"
        class="select-field"
        :value="worldView === 'alliance' ? worldRunRate : selectedRun?.rate ?? 1"
        :disabled="!controlsActive || loading"
        @change="emit('set-rate', Number(($event.target as HTMLSelectElement).value) as RunRate)"
      >
        <option v-for="rate in rateOptions" :key="rate" :value="rate">{{ rate }}×</option>
      </select>
    </section>

    <section class="rail-section rail-section--generation">
      <div class="section-kicker"><MapPinned :size="14" aria-hidden="true" /> 生成城镇</div>
      <div class="seed-row">
        <label class="field-label" for="generation-seed-input">世界种子</label>
        <input id="generation-seed-input" v-model="generationSeedInput" class="text-field" inputmode="numeric" placeholder="随机生成" :disabled="activeRun || loading || generationLoading" />
      </div>
      <div class="seed-row">
        <label class="field-label" for="population-input">居民数量</label>
        <input id="population-input" v-model="populationInput" class="text-field" type="number" min="100" max="100000" step="1" :disabled="activeRun || loading || generationLoading" />
      </div>
      <div class="seed-row">
        <label class="field-label" for="generation-size-select">城镇规模</label>
        <select id="generation-size-select" v-model="generationSizeInput" class="text-field" :disabled="activeRun || loading || generationLoading">
          <option value="village">村庄</option>
          <option value="town" selected>城镇</option>
          <option value="city">主城</option>
        </select>
      </div>
      <button class="action-button" type="button" :disabled="activeRun || loading || generationLoading" @click="generateTown">
        <Play :size="15" aria-hidden="true" />
        <span>{{ generationLoading ? "正在编译" : "生成城镇" }}</span>
      </button>
      <div v-if="draft" class="scenario-meta">
        <span>{{ draft.town_skeleton.buildings.length }} 座建筑</span>
        <span>{{ draft.town_skeleton.streets.length }} 条街道</span>
        <span>{{ draft.compile_status === "ready" ? "已就绪" : draft.compile_status === "failed" ? "失败" : "编译中" }}</span>
      </div>
    </section>
    <section class="rail-section rail-section--layers">
      <div class="section-kicker"><Layers3 :size="14" aria-hidden="true" /> 地图图层</div>
      <div class="layer-grid">
        <label v-for="option in layerOptions" :key="option.key" class="layer-toggle">
          <input
            type="checkbox"
            :checked="layerVisibility[option.key]"
            @change="emit('toggle-layer', option.key)"
          />
          <span>{{ option.label }}</span>
        </label>
      </div>
    </section>
    <section class="rail-section rail-section--density">
      <div class="section-kicker"><Gauge :size="14" aria-hidden="true" /> 人流密度</div>
      <div class="density-heading">
        <label class="field-label" for="flow-density-input">地图样本密度</label>
        <output for="flow-density-input">{{ props.flowDensity.toFixed(1) }}×</output>
      </div>
      <input
        id="flow-density-input"
        class="density-range"
        type="range"
        min="0.25"
        max="2.5"
        step="0.25"
        :value="props.flowDensity"
        aria-describedby="flow-density-note"
        @input="emit('set-flow-density', Number(($event.target as HTMLInputElement).value))"
      />
      <p id="flow-density-note" class="density-note">只调整地图上的人车样本数量，热力线仍覆盖所有可通行街道。</p>
    </section>
    <section class="rail-section rail-section--clarity">
      <div class="section-kicker"><ScanLine :size="14" aria-hidden="true" /> 渲染清晰度</div>
      <label class="field-label" for="map-clarity-select">地图像素质量</label>
      <select
        id="map-clarity-select"
        class="select-field"
        :value="props.mapClarity"
        @change="emit('set-map-clarity', ($event.target as HTMLSelectElement).value as MapClarity)"
      >
        <option v-for="option in MAP_CLARITY_OPTIONS" :key="option.value" :value="option.value">
          {{ option.label }} · GPU {{ option.cost }}
        </option>
      </select>
      <p class="density-note">{{ selectedClarity.detail }}。建筑和道路由 WebGL/GPU 绘制，路径计算仍由 CPU 负责。</p>
    </section>
    <section class="rail-section rail-section--scenario">
      <div class="section-kicker"><MapPinned :size="14" aria-hidden="true" /> 场景</div>
      <template v-if="worldView === 'alliance'">
        <label class="field-label" for="alliance-settlement-select">联盟聚落</label>
        <select
          id="alliance-settlement-select"
          class="select-field"
          :value="selectedAllianceId ?? ''"
          :disabled="activeRun || loading || generationLoading"
          @change="emit('select-alliance-settlement', ($event.target as HTMLSelectElement).value)"
        >
          <option value="" disabled>选择主城、城镇或村庄</option>
          <optgroup label="主城">
            <option v-for="settlement in allianceSettlements.filter((item) => item.kind === 'capital')" :key="settlement.id" :value="settlement.id">{{ settlement.name }}</option>
          </optgroup>
          <optgroup label="城镇">
            <option v-for="settlement in allianceSettlements.filter((item) => item.kind === 'town')" :key="settlement.id" :value="settlement.id">{{ settlement.name }}</option>
          </optgroup>
          <optgroup label="村庄">
            <option v-for="settlement in allianceSettlements.filter((item) => item.kind === 'village')" :key="settlement.id" :value="settlement.id">{{ settlement.name }}</option>
          </optgroup>
        </select>
        <p class="density-note">选择后将生成对应聚落，并跳转到其真实道路地图。</p>
      </template>
      <template v-else>
      <label class="field-label" for="scenario-select">当前场景</label>
      <select
        id="scenario-select"
        class="select-field"
        :value="selectedScenarioId ?? ''"
        :disabled="activeRun || loading"
        @change="emit('select-scenario', ($event.target as HTMLSelectElement).value)"
      >
        <option value="" disabled>选择场景</option>
        <option v-for="scenario in scenarios" :key="scenario.config.scenario_id" :value="scenario.config.scenario_id">
          {{ scenario.config.name }}
        </option>
      </select>
      <div v-if="selectedScenario" class="scenario-meta">
        <span>{{ selectedScenario.config.locations.length }} 个地点</span>
        <span>{{ selectedScenario.config.connections.length }} 条有向街道</span>
      </div>
      </template>
    </section>

    <section class="rail-section rail-section--history">
      <div class="history-heading">
        <div class="section-kicker"><History :size="14" aria-hidden="true" /> 最近运行</div>
        <span v-if="runsCount" class="history-count">共 {{ runsCount }} 条</span>
      </div>
      <div v-if="runs.length === 0" class="history-empty">还没有运行记录</div>
      <template v-else>
        <div class="history-list" role="list">
          <button
            v-for="run in pagedRuns"
            :key="run.id"
            class="history-row"
            :class="[runStatusClass(run.status), { 'is-selected': selectedRun?.id === run.id }]"
            type="button"
            :aria-current="selectedRun?.id === run.id ? 'true' : undefined"
            @click="emit('select-run', run.id)"
          >
            <i class="history-row__dot" aria-hidden="true"></i>
            <span class="history-row__copy">
              <strong>{{ timeLabel(run.started_at) }}</strong>
              <small>{{ run.scenario_name ?? scenarioNameById[run.scenario_id] ?? run.scenario_id }} · tick {{ run.current_tick }}</small>
            </span>
            <b class="history-row__label">{{ statusLabel(run.status) }}</b>
          </button>
        </div>
        <nav v-if="historyPageCount > 1" class="history-pagination" aria-label="运行记录分页">
          <button
            class="history-pagination__btn"
            type="button"
            :disabled="historyPage === 1"
            aria-label="上一页"
            @click="setHistoryPage(historyPage - 1)"
          >‹</button>
          <div class="history-pagination__pages" role="list">
            <button
              v-for="page in historyPageCount"
              :key="page"
              class="history-pagination__page"
              :class="{ 'is-current': page === historyPage }"
              type="button"
              :aria-label="`第 ${page} 页`"
              :aria-current="page === historyPage ? 'page' : undefined"
              @click="setHistoryPage(page)"
            >{{ page }}</button>
          </div>
          <button
            class="history-pagination__btn"
            type="button"
            :disabled="historyPage === historyPageCount"
            aria-label="下一页"
            @click="setHistoryPage(historyPage + 1)"
          >›</button>
        </nav>
      </template>
    </section>

    <div v-if="error" class="rail-error" role="alert">
      <CircleAlert :size="16" aria-hidden="true" />
      <span>{{ error.message }}</span>
    </div>
  </aside>
</template>
