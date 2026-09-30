<script setup lang="ts">
import { computed } from "vue";

import type {
  DailyResearchCommandState,
  DailyResearchSafetyKey,
  DailyResearchSafetyValues,
  DailyResearchPayload,
} from "./types";
import { DAILY_RESEARCH_SAFETY_KEYS } from "./types";

const props = defineProps<{
  state: DailyResearchCommandState;
  requestedDate: string | null;
  payload: DailyResearchPayload | null;
  safetyFlags: DailyResearchSafetyValues | null;
}>();

const emit = defineEmits<{
  "date-change": [value: string];
}>();

const inputDate = computed(() => {
  if (!props.requestedDate || props.requestedDate.length !== 8) return "";
  return `${props.requestedDate.slice(0, 4)}-${props.requestedDate.slice(4, 6)}-${props.requestedDate.slice(6)}`;
});

const origin = computed(() => {
  const value = props.payload?.execution_origin;
  return value === "NATURAL" || value === "AUTO_RETRY" || value === "MANUAL_RECOVERY"
    ? value
    : "CANNOT_CONFIRM";
});

function safetyValue(key: DailyResearchSafetyKey): unknown {
  return props.safetyFlags?.[key] ?? props.payload?.[key];
}

function displayValue(value: unknown): string {
  if (value === undefined) return "CANNOT_CONFIRM";
  if (value === null) return "null";
  if (typeof value === "string" || typeof value === "boolean" || typeof value === "number") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return "CANNOT_CONFIRM";
  }
}

function safetyIsValid(key: DailyResearchSafetyKey): boolean {
  const value = safetyValue(key);
  return key === "RESEARCH_ONLY" ? value === true : value === false;
}

function safetyStyle(key: DailyResearchSafetyKey): Record<string, string> {
  if (safetyIsValid(key)) return {};
  return {
    borderColor: "rgba(163, 77, 54, 0.45)",
    color: "#a34d36",
    background: "#fbede8",
  };
}

function onDateChange(event: Event) {
  emit("date-change", (event.target as HTMLInputElement).value);
}

function statusLabel(state: DailyResearchCommandState) {
  return state;
}
</script>

<template>
  <header class="daily-research-command__hero">
    <div class="daily-research-command__hero-copy">
      <p class="daily-research-command__eyebrow">V3.5 / RESEARCH AUTHORITY</p>
      <h1 class="daily-research-command__title">全天研究指挥台</h1>
      <p class="daily-research-command__subtitle">
        只读查看 exact-date 全天产品。小时槽位是血缘证据，不会被提升为全天权威。
      </p>
    </div>

    <div class="daily-research-command__date-control">
      <label class="daily-research-command__label" for="daily-research-date">研究日期</label>
      <input
        id="daily-research-date"
        class="daily-research-command__date-input"
        type="date"
        :value="inputDate"
        aria-label="研究日期"
        @input="onDateChange"
      />
      <span class="daily-research-command__date-hint">Asia/Shanghai · YYYYMMDD</span>
    </div>

    <div class="daily-research-command__authority-summary">
      <div class="daily-research-command__summary-item">
        <strong class="daily-research-command__summary-value">requested {{ requestedDate ?? "—" }}</strong>
      </div>
      <div class="daily-research-command__summary-item">
        <strong class="daily-research-command__summary-value">resolved {{ payload?.resolved_date ?? "CANNOT_CONFIRM" }}</strong>
      </div>
      <div class="daily-research-command__summary-item">
        <span class="daily-research-command__summary-label">timezone</span>
        <strong class="daily-research-command__summary-value">{{ payload?.timezone ?? "Asia/Shanghai" }}</strong>
      </div>
      <div class="daily-research-command__summary-item">
        <span class="daily-research-command__summary-label">date_mode</span>
        <strong class="daily-research-command__summary-value">{{ payload?.date_mode ?? "EXACT" }}</strong>
      </div>
      <div class="daily-research-command__summary-item daily-research-command__summary-item--status">
        <span class="daily-research-command__summary-label">status</span>
        <strong class="daily-research-command__summary-value">{{ statusLabel(state) }}</strong>
      </div>
      <div class="daily-research-command__summary-item">
        <span class="daily-research-command__summary-label">authoritative</span>
        <strong class="daily-research-command__summary-value">{{ payload?.authoritative === true ? "true" : "false" }}</strong>
      </div>
    </div>

    <div class="daily-research-command__hero-footer">
      <div class="daily-research-command__origin-strip" aria-label="execution origin">
        <span class="daily-research-command__origin-label">execution_origin</span>
        <span class="daily-research-command__origin-tag">execution_origin={{ origin }}</span>
      </div>
      <div class="daily-research-command__safety-strip" aria-label="research safety flags">
        <span
          v-for="key in DAILY_RESEARCH_SAFETY_KEYS"
          :key="key"
          class="daily-research-command__safety-flag"
          :class="safetyIsValid(key as DailyResearchSafetyKey) ? 'daily-research-command__safety-flag--valid' : 'daily-research-command__safety-flag--gap'"
          :style="safetyStyle(key as DailyResearchSafetyKey)"
        >{{ key }}={{ displayValue(safetyValue(key as DailyResearchSafetyKey)) }}</span>
      </div>
    </div>
  </header>
</template>
