<script setup lang="ts">
import { computed } from "vue";

import type { DailyResearchPayload } from "./types";

const props = defineProps<{ payload: DailyResearchPayload }>();
const diagnosticLabel = computed(() => {
  const hourly = props.payload.hourly_latest;
  return hourly
    ? `${hourly.slot} · ${hourly.row_count} rows · ${hourly.endpoint_mode === "LATEST_SLOT" ? "SLOT_ONLY" : hourly.endpoint_mode} · is_full_day=${hourly.is_full_day}`
    : "未请求 hourly latest；strict day authority 仅消费 exact day endpoint。";
});
</script>

<template>
  <section v-if="payload.status !== 'NOT_MATERIALIZED'" class="daily-research-command__diagnostic" aria-label="hourly diagnostic">
    <div>
      <p class="daily-research-command__eyebrow">SLOT-ONLY DIAGNOSTIC</p>
      <h2 class="daily-research-command__diagnostic-title">hourly latest 不进入全天漏斗</h2>
    </div>
    <p class="daily-research-command__diagnostic-value">{{ diagnosticLabel }}</p>
  </section>
</template>
