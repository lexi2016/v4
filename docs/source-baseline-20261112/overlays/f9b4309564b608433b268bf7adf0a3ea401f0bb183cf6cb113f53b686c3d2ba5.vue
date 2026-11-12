<script setup lang="ts">
import {
  chipList,
  deskText,
  financeOriginalUrl,
  financeOriginalTitle,
  financeSummary,
  financeTitle,
  safeExternalUrl,
  stockDisplayTitle,
  text,
} from "../../composables/useResearchLane";

const props = defineProps<{ card: Record<string, unknown> }>();

function isFinanceCard() {
  return text(props.card.source) === "finance"
    || text(props.card.kind) === "finance"
    || text(props.card.source_type) === "external_finance";
}

function cardTitle() {
  return isFinanceCard() ? financeTitle(props.card) : stockDisplayTitle(props.card);
}

function cardSummary() {
  return isFinanceCard()
    ? financeSummary(props.card)
    : text(props.card.summary || props.card.evidence_sentence || props.card.body_excerpt_preview || props.card.content);
}

function cardUrl() {
  return isFinanceCard() ? financeOriginalUrl(props.card) : safeExternalUrl(props.card.url);
}
</script>

<template>
  <article class="hourly-feed-card" :class="text(card.source)">
    <div class="hourly-feed-head">
      <div>
        <div class="hourly-feed-title">{{ cardTitle() }}</div>
        <div v-if="isFinanceCard() && financeOriginalTitle(card)" class="hourly-original-title">原题：{{ financeOriginalTitle(card) }}</div>
        <div class="hourly-meta">{{ text(card.source_name || card.source_type || card.source) }}</div>
      </div>
      <span class="hourly-source-tag source">{{ text(card.source) }}</span>
    </div>
    <div class="hourly-chips">
      <span v-for="chip in chipList(card)" :key="chip" class="hourly-chip">{{ chip }}</span>
    </div>
    <div class="hourly-summary">{{ cardSummary().slice(0, 240) }}</div>
    <div class="hourly-focus-strip">
      <a v-if="cardUrl()" :href="cardUrl()" target="_blank" rel="noopener noreferrer" class="hourly-pill">打开原文</a>
    </div>
  </article>
</template>
