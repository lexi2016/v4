<script setup lang="ts">
import { chipList, deskText, text, type LaneRow } from "../../composables/useResearchLane";

defineProps<{ rows: Array<LaneRow>; sourceEntities?: Array<LaneRow>; titleSubjects?: Array<Record<string, unknown>> }>();

const clueTitles = (row: LaneRow): string[] => (
  Array.isArray(row.document_titles) ? row.document_titles.map((title) => text(title)).filter(Boolean) : []
);
</script>

<template>
  <aside class="hourly-priority-pane" aria-label="股票层">
    <div class="hourly-panel-head">
      <div><span class="hourly-eyebrow">股票层</span><h3>priority · 股票研报</h3></div>
      <span class="hourly-pill">{{ rows.length }} 主线</span>
    </div>
    <p class="hourly-meta"><span>研报对象 · 标题角色筛选</span>。仅对原实体作标题角色分类。原评分尚未按角色重建，不能据此放行研究推荐或交易。</p>
    <p v-if="rows.some((row) => row.source === 'MACHINE_CLUE')" class="hourly-meta">
      按文本确定性解析，含券商署名已剔除；仅为线索，不是推荐，不进入信号与买点。
    </p>
    <div class="hourly-impact-list">
      <article
        v-for="row in rows"
        :key="text(row.stock_code)"
        class="hourly-impact-card"
        :class="{ observe: !text(row.formal_overlap) && !text(row.stage_overlap) }"
      >
        <span class="hourly-source-tag key">{{ row.source === "MACHINE_CLUE" ? "机器研报线索" : deskText(row.evidence_level || row.research_status) }}</span>
        <div class="hourly-impact-title">{{ text(row.stock_name || row.name) }} {{ text(row.stock_code || row.code) }}</div>
        <div class="hourly-impact-reason">
          {{ row.source === "MACHINE_CLUE"
            ? (clueTitles(row)[0] || "报告标题 CANNOT_CONFIRM")
            : text(row.latest_evidence_sentence || row.evidence_sentence || row.research_status || row.gate_status) }}
        </div>
        <div class="hourly-chips">
          <span v-if="row.source === 'MACHINE_CLUE'" class="hourly-chip machine-clue-badge">研报提及 ×{{ row.document_count }}</span>
          <span v-for="chip in chipList(row)" :key="chip" class="hourly-chip">{{ chip }}</span>
        </div>
        <div v-if="row.source === 'MACHINE_CLUE'" class="stock-timeline machine-clue-titles">
          <div v-for="(title, index) in clueTitles(row).slice(0, 3)" :key="`${index}-${title}`" class="stock-timeline-event">
            <div class="stock-timeline-head"><span>报告 {{ index + 1 }}</span></div>
            <div class="stock-timeline-body">{{ title }}</div>
          </div>
        </div>
        <div v-else class="stock-timeline">
          <div v-for="event in (row._timeline ?? []).slice(0, 3)" :key="text(event.event_id)" class="stock-timeline-event">
            <div class="stock-timeline-head">
              <span>{{ text(event.event_time).slice(11, 16) }}</span>
              <span>{{ deskText(event.claim_type || event.evidence_level) }}</span>
            </div>
            <div class="stock-timeline-body">{{ text(event.evidence_sentence).slice(0, 150) }}</div>
          </div>
        </div>
      </article>
      <div v-if="!rows.length" class="empty">当前情报日无股票主线；如有原实体，仍保留在下方证据区。</div>
    </div>
    <details v-if="sourceEntities?.length" class="hourly-impact-list">
      <summary>发布机构／正文提及／市场冲突／未绑定实体（{{ sourceEntities.length }}）</summary>
      <article v-for="(row, index) in sourceEntities" :key="`${text(row.stock_code)}-${index}`" class="hourly-impact-card">
        <strong>{{ text(row.stock_name || row.name) }} {{ text(row.stock_code || row.code) }}</strong>
        <p>{{ Array.isArray(row.entity_roles) ? row.entity_roles.join("、") : "角色未确认" }}</p>
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
