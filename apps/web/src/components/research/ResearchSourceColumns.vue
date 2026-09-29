<script setup lang="ts">
import { financeOriginalUrl, safeExternalUrl, text } from "../../composables/useResearchLane";

defineProps<{
  columns: Array<{ name: string; rows: Array<Record<string, unknown>> }>;
}>();

function sourceUrl(columnName: string, row: Record<string, unknown>): string {
  return columnName === "外部财经" ? financeOriginalUrl(row) : safeExternalUrl(row.url);
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
        <article v-for="row in col.rows.slice(0, 6)" :key="text(row.article_id || row.item_id || row.id || row.title)" class="hourly-feed-card source">
          <div class="hourly-feed-title">{{ text(row.title || row.stock_name || row.stock_code || row.content) }}</div>
          <div class="hourly-summary">{{ text(row.summary || row.body_excerpt_preview || row.evidence_sentence).slice(0, 100) }}</div>
          <a v-if="sourceUrl(col.name, row)" :href="sourceUrl(col.name, row)" target="_blank" rel="noopener noreferrer" class="hourly-pill">打开原文</a>
        </article>
        <div v-if="!col.rows.length" class="empty">{{ col.name }} 无条目。</div>
      </div>
    </section>
  </div>
</template>
