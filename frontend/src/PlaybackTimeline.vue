<script setup lang="ts">
import { computed } from "vue";
import { ChevronsRight, Pause, Play, Radio } from "lucide-vue-next";

const props = defineProps<{
  displayedTick: number;
  latestTick: number;
  followingLatest: boolean;
  running: boolean;
  replayable: boolean;
  playing: boolean;
}>();

const emit = defineEmits<{
  (event: "seek", tick: number): void;
  (event: "follow-latest"): void;
  (event: "toggle-play"): void;
}>();

const progress = computed(() => props.latestTick === 0 ? 0 : (props.displayedTick / props.latestTick) * 100);
</script>

<template>
  <section class="timeline" aria-label="统一时间轴">
    <div class="timeline-status">
      <Radio :size="15" :class="{ 'pulse-icon': running && followingLatest }" aria-hidden="true" />
      <span>{{ followingLatest ? "跟随最新" : "查看历史" }}</span>
    </div>
    <div class="timeline-track">
      <input
        class="timeline-range"
        type="range"
        min="0"
        :max="Math.max(latestTick, 1)"
        step="1"
        :value="displayedTick"
        :style="{ '--progress': `${progress}%` }"
        :aria-valuetext="`第 ${displayedTick} 秒，共 ${latestTick} 秒`"
        @input="emit('seek', Number(($event.target as HTMLInputElement).value))"
      />
      <div class="timeline-scale">
        <span>T+0000</span>
        <strong>T+{{ displayedTick.toString().padStart(4, "0") }}</strong>
        <span>T+{{ latestTick.toString().padStart(4, "0") }}</span>
      </div>
    </div>
    <div class="timeline-actions">
      <button
        v-if="replayable"
        class="icon-button icon-button--play"
        type="button"
        :aria-label="playing ? '暂停回放' : '播放回放'"
        :title="playing ? '暂停回放' : '播放回放'"
        @click="emit('toggle-play')"
      >
        <Pause v-if="playing" :size="17" fill="currentColor" aria-hidden="true" />
        <Play v-else :size="17" fill="currentColor" aria-hidden="true" />
      </button>
      <button
        class="icon-button"
        type="button"
        :disabled="followingLatest"
        aria-label="返回最新"
        title="返回最新"
        @click="emit('follow-latest')"
      >
        <ChevronsRight :size="17" aria-hidden="true" />
      </button>
    </div>
  </section>
</template>
