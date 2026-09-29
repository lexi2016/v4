<script setup lang="ts">
import { computed } from "vue";

import {
  chipList,
  feedFetchTimeLabel,
  feedPublishedTimeLabel,
  financeOriginalUrl,
  safeExternalUrl,
  text,
} from "../../composables/useResearchLane";

const props = defineProps<{ card: Record<string, unknown> }>();

const originalUrl = computed(() => {
  const card = props.card;
  const isFinance = text(card.source) === "finance"
    || text(card.kind) === "finance"
    || text(card.source_type) === "finance";
  return isFinance ? financeOriginalUrl(card) : safeExternalUrl(card.url);
});
</script>

<template>
  <article class="hourly-feed-card" :class="text(card.source)">
    <div class="hourly-feed-head">
      <div>
        <div class="hourly-feed-title">{{ text(card.stock_name || card.stock_code || card.title) }}</div>
        <div class="hourly-meta">{{ text(card.source_name || card.source_type || card.source) }}</div>
      </div>
      <span class="hourly-source-tag source">{{ text(card.source) }}</span>
    </div>
    <div class="hourly-evidence-times" aria-label="时间证据">
      <span class="hourly-time-label">{{ feedFetchTimeLabel(card) }}</span>
      <span class="hourly-time-label">{{ feedPublishedTimeLabel(card) }}</span>
    </div>
    <div class="hourly-chips">
      <span v-for="chip in chipList(card)" :key="chip" class="hourly-chip">{{ chip }}</span>
    </div>
    <div class="hourly-summary">{{ text(card.summary || card.evidence_sentence || card.body_excerpt_preview || card.content).slice(0, 240) }}</div>
    <div class="hourly-focus-strip">
      <a v-if="originalUrl" :href="originalUrl" target="_blank" rel="noopener noreferrer" class="hourly-pill">打开原文</a>
    </div>
  </article>
</template>
