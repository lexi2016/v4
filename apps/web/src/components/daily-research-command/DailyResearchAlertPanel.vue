<script setup lang="ts">
import { computed } from "vue";

import type {
  DailyResearchAlert,
  DailyResearchCommandState,
  DailyResearchPayload,
} from "./types";

const props = defineProps<{
  state: DailyResearchCommandState;
  payload: DailyResearchPayload | null;
  errorMessage: string | null;
}>();

const alerts = computed<DailyResearchAlert[]>(() => {
  const declared = props.payload?.alerts ? [...props.payload.alerts] : [];
  const registryGap = props.payload?.high_priority_status?.registry === "MISSING";
  if (registryGap && !declared.some((alert) => alert.code === "REGISTRY_MISSING")) {
    declared.unshift({
      severity: "SEV2",
      code: "REGISTRY_MISSING",
      status: "OPEN",
      message: "JYG stock_mentions registry missing; high_priority remains empty",
      blocks_consumer: true,
      blocks_publish: false,
    });
  }
  return declared;
});

const gaps = computed(() => props.payload?.cannot_confirm ?? []);

const panelTone = computed(() => {
  if (alerts.value.length || gaps.value.length || props.state === "CANNOT_CONFIRM") return "gap";
  if (props.state === "ERROR" || props.state === "REJECTED" || props.state === "STALE") return "error";
  return "neutral";
});
</script>

<template>
  <section
    class="daily-research-command__alert-panel"
    :class="`daily-research-command__alert-panel--${panelTone}`"
    aria-live="polite"
  >
    <div class="daily-research-command__alert-heading">
      <span class="daily-research-command__alert-kicker">CLOSEOUT GATES</span>
      <strong class="daily-research-command__alert-state">{{ state === "CANNOT_CONFIRM" ? "CANNOT_CONFIRM" : "read-only gate" }}</strong>
    </div>
    <div v-if="alerts.length" class="daily-research-command__alert-list">
      <article v-for="alert in alerts" :key="`${alert.code}-${alert.slot ?? 'day'}`" class="daily-research-command__alert-item">
        <strong class="daily-research-command__alert-code">{{ alert.severity ?? "SEV2" }} · {{ alert.code ?? "CANNOT_CONFIRM" }}</strong>
        <span class="daily-research-command__alert-message">{{ alert.message ?? "Declared evidence gap" }}</span>
      </article>
    </div>
    <div v-if="gaps.length" class="daily-research-command__gap-list">
      <span class="daily-research-command__gap-label">cannot_confirm</span>
      <span v-for="gap in gaps" :key="gap" class="daily-research-command__gap-value">{{ gap }}</span>
    </div>
    <p v-if="errorMessage" class="daily-research-command__error-message">{{ errorMessage }}</p>
    <p v-if="!alerts.length && !gaps.length && !errorMessage" class="daily-research-command__alert-empty">
      没有额外声明的 gap；仍以六层 lineage 和 exact-date contract 为准。
    </p>
  </section>
</template>
