<script setup lang="ts">
import { deskText, num, text } from "../../composables/useResearchLane";

defineProps<{
  timelineRows: Array<Record<string, unknown>>;
  quality: Record<string, unknown>;
}>();
</script>

<template>
  <aside class="hourly-context-pane" aria-label="本小时状态">
    <div class="hourly-panel-head">
      <div><span class="hourly-eyebrow">本小时状态</span><h3>来源状态</h3></div>
    </div>
    <div class="hourly-source-panel">
      <div class="hourly-eyebrow">07:00-24:00 时间线</div>
      <div class="hourly-quality-list">
        <div v-for="row in timelineRows" :key="text(row.evidence_id)" class="hourly-quality-row">
          <span class="hourly-label">{{ text(row._time) }}</span>
          <strong>{{ text(row.stock_name || row.stock_code) }}</strong>
          <span class="hourly-source-tag key">{{ deskText(row.evidence_level) }}</span>
        </div>
        <div v-if="!timelineRows.length" class="empty">无时间线事件。</div>
      </div>
    </div>
    <div class="hourly-source-panel">
      <div class="hourly-eyebrow">质量状态</div>
      <div class="hourly-quality-list">
        <div class="hourly-quality-row"><span class="hourly-label">原始条目</span><strong>{{ num(quality.raw_item_count) }}</strong></div>
        <div class="hourly-quality-row"><span class="hourly-label">研报条目</span><strong>{{ num(quality.research_item_count) }}</strong></div>
        <div class="hourly-quality-row"><span class="hourly-label">证据行</span><strong>{{ num(quality.stock_evidence_count) }}</strong></div>
        <div class="hourly-quality-row"><span class="hourly-label">股票池</span><strong>{{ num(quality.stock_daily_count) }}</strong></div>
        <div class="hourly-quality-row"><span class="hourly-label">增强证据</span><strong>{{ num(quality.l2_medium_count) }}</strong></div>
        <div class="hourly-quality-row"><span class="hourly-label">强证据</span><strong>{{ num(quality.l3_strong_count) }}</strong></div>
      </div>
    </div>
  </aside>
</template>
