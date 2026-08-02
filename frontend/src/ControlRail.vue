<script setup lang="ts">
import { computed, ref } from "vue";
import { Check, CircleAlert, Gauge, History, MapPinned, Pause, Play, RotateCcw, Square } from "lucide-vue-next";
import type { ApiError, RunRate, RunRecord, ScenarioBundle, ScenarioDraft } from "./api";

const props = defineProps<{
  scenarios: ScenarioBundle[];
  selectedScenarioId: string | null;
  runs: RunRecord[];
  selectedRun: RunRecord | null;
  loading: boolean;
  error: ApiError | null;
  draft: ScenarioDraft | null;
  generationLoading: boolean;
}>();

const emit = defineEmits<{
  (event: "select-scenario", scenarioId: string): void;
  (event: "select-run", runId: string): void;
  (event: "start", seed?: number): void;
  (event: "command", action: "pause" | "resume" | "end"): void;
  (event: "set-rate", rate: RunRate): void;
  (event: "generate-town", payload: { generationSeed?: number; population: number }): void;
}>();

const seedInput = ref("");
const generationSeedInput = ref("");
const populationInput = ref("11499");
const rateOptions: RunRate[] = [0.5, 1, 2, 4];

const selectedScenario = computed(() =>
  props.scenarios.find((scenario) => scenario.config.scenario_id === props.selectedScenarioId),
);

const activeRun = computed(() => props.selectedRun?.status === "running" || props.selectedRun?.status === "paused");
const canStart = computed(() =>
  (Boolean(props.selectedScenarioId) || (props.draft?.compile_status === "ready" && Boolean(props.draft.bundle)))
  && !props.runs.some((run) => run.status === "running" || run.status === "paused"),
);

function start() {
  const parsed = seedInput.value.trim() === "" ? undefined : Number(seedInput.value);
  emit("start", parsed !== undefined && Number.isSafeInteger(parsed) ? parsed : undefined);
}

function generateTown() {
  const population = Number(populationInput.value);
  const seedText = generationSeedInput.value.trim();
  const generationSeed = seedText === "" ? undefined : Number(seedText);
  if (!Number.isSafeInteger(population) || population < 100 || population > 100_000) return;
  if (generationSeed !== undefined && (!Number.isSafeInteger(generationSeed) || generationSeed < 0)) return;
  emit("generate-town", { population, ...(generationSeed === undefined ? {} : { generationSeed }) });
}

function statusLabel(status: RunRecord["status"]): string {
  return { running: "运行中", paused: "已暂停", ended: "已结束", failed: "异常终止" }[status];
}

function timeLabel(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(value));
}
</script>

<template>
  <aside class="control-rail" aria-label="运行控制">
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
    <section class="rail-section rail-section--scenario">
      <div class="section-kicker"><MapPinned :size="14" aria-hidden="true" /> 场景</div>
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
    </section>

    <section class="rail-section rail-section--controls">
      <div class="section-kicker"><Gauge :size="14" aria-hidden="true" /> 调度</div>
      <div class="seed-row">
        <label class="field-label" for="seed-input">Seed</label>
        <input id="seed-input" v-model="seedInput" class="text-field" inputmode="numeric" placeholder="自动生成" />
      </div>
      <button class="action-button action-button--primary" type="button" :disabled="!canStart || loading" @click="start">
        <Play :size="16" fill="currentColor" aria-hidden="true" />
        <span>启动模拟</span>
      </button>
      <div class="command-grid">
        <button class="action-button" type="button" :disabled="selectedRun?.status !== 'running' || loading" title="暂停当前运行" @click="emit('command', 'pause')">
          <Pause :size="15" aria-hidden="true" /><span>暂停</span>
        </button>
        <button class="action-button" type="button" :disabled="selectedRun?.status !== 'paused' || loading" title="继续当前运行" @click="emit('command', 'resume')">
          <RotateCcw :size="15" aria-hidden="true" /><span>继续</span>
        </button>
        <button class="action-button action-button--danger" type="button" :disabled="!activeRun || loading" title="结束当前运行" @click="emit('command', 'end')">
          <Square :size="14" fill="currentColor" aria-hidden="true" /><span>结束</span>
        </button>
      </div>
      <label class="field-label" for="rate-select">运行速率</label>
      <select
        id="rate-select"
        class="select-field"
        :value="selectedRun?.rate ?? 1"
        :disabled="!activeRun || loading"
        @change="emit('set-rate', Number(($event.target as HTMLSelectElement).value) as RunRate)"
      >
        <option v-for="rate in rateOptions" :key="rate" :value="rate">{{ rate }}×</option>
      </select>
    </section>

    <section class="rail-section rail-section--history">
      <div class="section-kicker"><History :size="14" aria-hidden="true" /> 历史运行</div>
      <div v-if="runs.length === 0" class="empty-line">还没有运行记录</div>
      <div v-else class="run-list" role="list">
        <button
          v-for="run in runs"
          :key="run.id"
          class="run-row"
          :class="{ 'run-row--selected': selectedRun?.id === run.id }"
          type="button"
          role="listitem"
          @click="emit('select-run', run.id)"
        >
          <span class="run-row__status" :class="`status-${run.status}`" aria-hidden="true"></span>
          <span class="run-row__main">
            <strong>{{ timeLabel(run.started_at) }}</strong>
            <small>{{ run.scenario_id }} · tick {{ run.current_tick }}</small>
          </span>
          <span class="run-row__label">{{ statusLabel(run.status) }}</span>
          <Check v-if="selectedRun?.id === run.id" :size="14" aria-hidden="true" />
        </button>
      </div>
    </section>

    <div v-if="error" class="rail-error" role="alert">
      <CircleAlert :size="16" aria-hidden="true" />
      <span>{{ error.message }}</span>
    </div>
  </aside>
</template>
