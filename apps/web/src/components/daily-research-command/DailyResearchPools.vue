<script setup lang="ts">
import type { DailyResearchPayload } from "./types";

const props = defineProps<{ payload: DailyResearchPayload }>();

function text(value: unknown, fallback = "—") {
  return value === undefined || value === null || value === "" ? fallback : String(value);
}
</script>

<template>
  <section class="daily-research-command__section daily-research-command__pools-section" aria-labelledby="daily-research-pools-title">
    <div class="daily-research-command__section-heading">
      <div>
        <p class="daily-research-command__eyebrow">RESEARCH POOLS</p>
        <h2 id="daily-research-pools-title" class="daily-research-command__section-title">四层对象，各自有明确含义</h2>
      </div>
      <span class="daily-research-command__section-note">只读；不重算 producer 规则</span>
    </div>

    <div class="daily-research-command__pool-grid">
      <article class="daily-research-command__pool-card" data-pool="evidence_rows">
        <div class="daily-research-command__pool-heading">
          <div><span class="daily-research-command__pool-kicker">LAYER 1</span><h3>evidence_rows</h3></div>
          <strong>{{ props.payload.counts.evidence_rows }} rows</strong>
        </div>
        <p class="daily-research-command__pool-description">exact-date source rows；保留 slot、source row ref 与证据等级。</p>
        <div class="daily-research-command__pool-list" :aria-rowcount="props.payload.evidence_rows.length">
          <div v-for="row in props.payload.evidence_rows" :key="`${row.slot}-${row.source_row_ref}`" class="daily-research-command__pool-row">
            <span>{{ text(row.slot) }} · {{ text(row.stock_code) }}</span>
            <span>{{ text(row.url) }}</span>
          </div>
          <span v-if="!props.payload.evidence_rows.length" class="daily-research-command__pool-empty">0 evidence rows</span>
        </div>
      </article>

      <article class="daily-research-command__pool-card" data-pool="mention_pairs">
        <div class="daily-research-command__pool-heading">
          <div><span class="daily-research-command__pool-kicker">LAYER 2</span><h3>mention_pairs</h3></div>
          <strong>{{ props.payload.counts.mention_pairs }}</strong>
        </div>
        <p class="daily-research-command__pool-description">normalized(url) + stock_code；稳定跨槽去重，保留全部 source refs。</p>
        <div class="daily-research-command__pool-list" :aria-rowcount="props.payload.mention_pairs.length">
          <div v-for="pair in props.payload.mention_pairs" :key="pair.pair_key" class="daily-research-command__pool-row daily-research-command__pool-row--stacked">
            <span><strong>{{ pair.stock_code }}</strong> · {{ pair.duplicate_reason }} · {{ pair.occurrence_count }} occurrences</span>
            <span>{{ pair.normalized_url }} · {{ pair.source_slots.join(" ↔ ") }} · {{ pair.variant_count }} variants</span>
          </div>
          <span v-if="!props.payload.mention_pairs.length" class="daily-research-command__pool-empty">0 mention pairs</span>
        </div>
      </article>

      <article class="daily-research-command__pool-card" data-pool="stock_rollups">
        <div class="daily-research-command__pool-heading">
          <div><span class="daily-research-command__pool-kicker">LAYER 3</span><h3>stock_rollups</h3></div>
          <strong>{{ props.payload.counts.stock_rollups }} stocks</strong>
        </div>
        <p class="daily-research-command__pool-description">mention_pairs 按 stock_code 汇总；不是 producer 的高优先级排序。</p>
        <div class="daily-research-command__pool-list" :aria-rowcount="props.payload.stock_rollups.length">
          <div v-for="stock in props.payload.stock_rollups" :key="stock.stock_code" class="daily-research-command__pool-row daily-research-command__pool-row--stacked">
            <span><strong>{{ stock.stock_code }}</strong> · {{ text(stock.stock_name) }} · {{ stock.mention_pair_count }} pairs</span>
            <span>{{ stock.urls.length }} URLs · slots {{ stock.source_slots.join(", ") }}</span>
          </div>
          <span v-if="!props.payload.stock_rollups.length" class="daily-research-command__pool-empty">0 stock rollups</span>
        </div>
      </article>

      <article class="daily-research-command__pool-card daily-research-command__pool-card--gap" data-pool="high_priority">
        <div class="daily-research-command__pool-heading">
          <div><span class="daily-research-command__pool-kicker">LAYER 4</span><h3>high_priority</h3></div>
          <strong>{{ props.payload.counts.high_priority }}</strong>
        </div>
        <p class="daily-research-command__pool-description">仅接受 producer 冻结 rule_id / rank / reason；本页不自行打分。</p>
        <div v-if="props.payload.high_priority.length" class="daily-research-command__pool-list" :aria-rowcount="props.payload.high_priority.length">
          <div v-for="stock in props.payload.high_priority" :key="`${stock.rule_id}-${stock.stock_code}`" class="daily-research-command__pool-row">
            <span><strong>#{{ stock.rank }} {{ stock.stock_code }}</strong></span>
            <span>{{ stock.rule_id }} · {{ stock.reason }}</span>
          </div>
        </div>
        <div v-else class="daily-research-command__pool-gap">
          <strong>empty · CANNOT_CONFIRM</strong>
          <span>registry={{ props.payload.high_priority_status.registry }} · {{ props.payload.high_priority_status.cannot_confirm ?? "producer rule not declared" }}</span>
        </div>
      </article>
    </div>
  </section>
</template>
