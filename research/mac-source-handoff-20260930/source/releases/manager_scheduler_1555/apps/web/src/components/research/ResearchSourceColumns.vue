<script setup lang="ts">
import {
  UNKNOWN_STOCK_NAME,
  financeOriginalUrl,
  financeOriginalTitle,
  financeSummary,
  financeTitle,
  safeExternalUrl,
  text,
} from "../../composables/useResearchLane";

defineProps<{
  columns: Array<{ name: string; rows: Array<Record<string, unknown>> }>;
}>();

function isFinanceColumn(name: string) {
  return name === "外部财经";
}

function rowTitle(columnName: string, row: Record<string, unknown>) {
  if (isFinanceColumn(columnName)) return financeTitle(row) || UNKNOWN_STOCK_NAME;
  return text(row.title || row.stock_name || row.name || row.content) || UNKNOWN_STOCK_NAME;
}

function rowSummary(columnName: string, row: Record<string, unknown>) {
  if (isFinanceColumn(columnName)) return financeSummary(row);
  return text(row.summary || row.body_excerpt_preview || row.evidence_sentence);
}

function sourceUrl(columnName: string, row: Record<string, unknown>) {
  return isFinanceColumn(columnName) ? financeOriginalUrl(row) : safeExternalUrl(row.url);
}
</script>

<template>
  <div class="hourly-source-columns">
    <section v-for="col in columns" :key="col.name" class="hourly-source-column" :id="col.name === '早盘新闻' ? 'researchWechatSource' : undefined">
      <div class="hourly-source-column-head">
        <h4>{{ col.name }}</h4>
        <span class="hourly-pill">{{ col.rows.length }}</span>
      </div>
      <div class="hourly-column-list">
        <article v-for="row in (isFinanceColumn(col.name) ? col.rows : col.rows.slice(0, 6))" :key="text(row.article_id || row.item_id || row.id || row.title)" class="hourly-feed-card source">
          <div class="hourly-feed-title">{{ rowTitle(col.name, row) }}</div>
          <div v-if="isFinanceColumn(col.name) && financeOriginalTitle(row)" class="hourly-original-title">原题：{{ financeOriginalTitle(row) }}</div>
          <div class="hourly-summary">{{ rowSummary(col.name, row).slice(0, 100) }}</div>
          <a
            v-if="sourceUrl(col.name, row)"
            :href="sourceUrl(col.name, row)"
            target="_blank"
            rel="noopener noreferrer"
            class="hourly-pill"
          >打开原文</a>
        </article>
        <div v-if="!col.rows.length" class="empty">{{ col.name }} 无条目。</div>
      </div>
    </section>
  </div>
</template>
