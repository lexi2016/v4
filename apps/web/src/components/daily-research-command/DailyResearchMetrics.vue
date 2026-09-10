<script setup lang="ts">
import type { DailyResearchPayload } from "./types";

const props = defineProps<{ payload: DailyResearchPayload }>();

const count = (key: keyof DailyResearchPayload["counts"]) => props.payload.counts?.[key] ?? 0;
</script>

<template>
  <section class="daily-research-command__section daily-research-command__metrics" aria-labelledby="daily-research-funnel-title">
    <div class="daily-research-command__section-heading">
      <div>
        <p class="daily-research-command__eyebrow">EXACT-DATE FUNNEL</p>
        <h2 id="daily-research-funnel-title" class="daily-research-command__section-title">从槽位证据到研究池</h2>
      </div>
      <span class="daily-research-command__section-note">不含 latest，不含跨日 fallback</span>
    </div>
    <div class="daily-research-command__funnel" aria-label="research count funnel">
      <div class="daily-research-command__metric-card">
        <span class="daily-research-command__metric-label">raw rows</span>
        <strong class="daily-research-command__metric-value">{{ count("raw_rows") }}</strong>
        <span class="daily-research-command__metric-detail">8 slots input</span>
      </div>
      <span class="daily-research-command__funnel-arrow" aria-hidden="true">→</span>
      <div class="daily-research-command__metric-card">
        <span class="daily-research-command__metric-label">evidence rows</span>
        <strong class="daily-research-command__metric-value">{{ count("evidence_rows") }}</strong>
        <span class="daily-research-command__metric-detail">exact date</span>
      </div>
      <span class="daily-research-command__funnel-arrow" aria-hidden="true">→</span>
      <div class="daily-research-command__metric-card">
        <span class="daily-research-command__metric-label">mention pairs</span>
        <strong class="daily-research-command__metric-value">{{ count("mention_pairs") }} pairs</strong>
        <span class="daily-research-command__metric-detail">stable URL + stock</span>
      </div>
      <span class="daily-research-command__funnel-arrow" aria-hidden="true">→</span>
      <div class="daily-research-command__metric-card">
        <span class="daily-research-command__metric-label">stock rollups</span>
        <strong class="daily-research-command__metric-value">{{ count("stock_rollups") }}</strong>
        <span class="daily-research-command__metric-detail">research pool</span>
      </div>
    </div>
    <div class="daily-research-command__metric-footnotes">
      <span class="daily-research-command__metric-footnote">{{ count("urls") }} URLs</span>
      <span class="daily-research-command__metric-footnote">{{ count("duplicate_pairs") }} duplicate pairs</span>
      <span class="daily-research-command__metric-footnote">excluded {{ count("excluded_rows") }} · date/PIT/invalid {{ props.payload.exclusions ? Object.values(props.payload.exclusions).join("/") : "—" }}</span>
      <span class="daily-research-command__metric-footnote">high_priority {{ count("high_priority") }} · {{ props.payload.high_priority_status?.status ?? "CANNOT_CONFIRM" }}</span>
    </div>
  </section>
</template>
