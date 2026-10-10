<script setup lang="ts">
import { chipList, deskText, text, type LaneRow } from "../../composables/useResearchLane";

defineProps<{ rows: Array<LaneRow>; sourceEntities?: Array<LaneRow>; titleSubjects?: Array<Record<string, unknown>> }>();
</script>

<template>
  <aside class="hourly-priority-pane" aria-label="股票层">
    <div class="hourly-panel-head">
      <div><span class="hourly-eyebrow">股票层</span><h3>研报对象 · 标题角色筛选</h3></div>
      <span class="hourly-pill">{{ rows.length }} 对象</span>
    </div>
    <p class="hourly-meta">仅对原实体作标题角色分类。原评分尚未按角色重建，不能据此放行研究推荐或交易。</p>
    <div class="hourly-impact-list">
      <article
        v-for="row in rows"
        :key="text(row.stock_code)"
        class="hourly-impact-card"
        :class="{ observe: !text(row.formal_overlap) && !text(row.stage_overlap) }"
      >
        <span class="hourly-source-tag key">{{ deskText(row.evidence_level || row.research_status) }}</span>
        <div class="hourly-impact-title">{{ text(row.stock_name || row.name) }} {{ text(row.stock_code || row.code) }}</div>
        <div class="hourly-impact-reason">{{ text(row.latest_evidence_sentence || row.evidence_sentence || row.research_status || row.gate_status) }}</div>
        <div class="hourly-chips">
          <span v-for="chip in chipList(row)" :key="chip" class="hourly-chip">{{ chip }}</span>
        </div>
        <div class="stock-timeline">
          <div v-for="event in (row._timeline ?? []).slice(0, 3)" :key="text(event.event_id)" class="stock-timeline-event">
            <div class="stock-timeline-head">
              <span>{{ text(event.event_time).slice(11, 16) }}</span>
              <span>{{ deskText(event.claim_type || event.evidence_level) }}</span>
            </div>
            <div class="stock-timeline-body">{{ text(event.evidence_sentence).slice(0, 150) }}</div>
          </div>
        </div>
      </article>
      <div v-if="!rows.length" class="empty">当前情报日没有已匹配的研究对象；原实体仍保留在下方证据区。</div>
    </div>
    <details v-if="sourceEntities?.length" class="hourly-impact-list">
      <summary>发布机构／正文提及／市场冲突／未绑定实体（{{ sourceEntities.length }}）</summary>
      <article v-for="(row, index) in sourceEntities" :key="`${text(row.stock_code)}-${index}`" class="hourly-impact-card">
        <strong>{{ text(row.stock_name || row.name) }} {{ text(row.stock_code || row.code) }}</strong>
        <p>{{ Array.isArray(row.entity_roles) ? row.entity_roles.join('、') : '角色未确认' }}</p>
        <p>保留原实体与原评分，不作为已确认研报对象。{{ text(row.latest_evidence_sentence || row.evidence_sentence) }}</p>
      </article>
    </details>
    <details v-if="titleSubjects?.length" class="hourly-impact-list">
      <summary>标题明确的名称和市场代码（原文证据，非证券主表认证）</summary>
      <p v-for="(item, index) in titleSubjects" :key="`${text(item.code)}-${index}`">
        {{ text(item.name) }} {{ text(item.code) }} · {{ text(item.source_title) }}
      </p>
    </details>
  </aside>
</template>
