<script setup lang="ts">
import { computed } from "vue";

import type { DailyResearchLineageLayer, DailyResearchPayload } from "./types";

const props = defineProps<{ payload: DailyResearchPayload }>();

const layers = computed<DailyResearchLineageLayer[]>(() => {
  const lineage = props.payload.status === "NOT_MATERIALIZED" ? null : props.payload.lineage;
  const exactProduct = props.payload.date_mode === "EXACT" && props.payload.archive_date === props.payload.resolved_date;
  const current = lineage?.current_sha256;
  const artifactDetail = lineage?.artifact_sha256 ? `SHA ${lineage.artifact_sha256.slice(0, 12)}…` : "missing daily artifact";
  const manifestDetail = lineage?.manifest_sha256 ? `SHA ${lineage.manifest_sha256.slice(0, 12)}…` : "missing manifest";
  const receiptDetail = lineage?.receipt_sha256 ? `SHA ${lineage.receipt_sha256.slice(0, 12)}…` : "missing receipt";
  const currentDetail = current ? `SHA ${current.slice(0, 12)}…` : "current pointer not eligible";
  const chainComplete = Boolean(lineage?.artifact_sha256 && lineage?.manifest_sha256 && lineage?.receipt_sha256 && current && exactProduct);
  return [
    { name: "artifact", status: lineage?.artifact_sha256 ? "VALIDATED" : "CANNOT_CONFIRM", detail: artifactDetail },
    { name: "manifest", status: lineage?.manifest_sha256 ? "VALIDATED" : "CANNOT_CONFIRM", detail: manifestDetail },
    { name: "current", status: current ? "VALIDATED" : "CANNOT_CONFIRM", detail: currentDetail },
    { name: "receipt", status: lineage?.receipt_sha256 ? "VALIDATED" : "CANNOT_CONFIRM", detail: receiptDetail },
    { name: "API", status: chainComplete ? "VALIDATED" : "CANNOT_CONFIRM", detail: exactProduct ? "strict exact-day response" : "requested/resolved date mismatch" },
    { name: "UI", status: chainComplete ? "VALIDATED" : "CANNOT_CONFIRM", detail: chainComplete ? "same-date payload rendered" : "same SHA chain not proven" },
  ];
});
</script>

<template>
  <section class="daily-research-command__section daily-research-command__lineage-section" aria-labelledby="daily-research-lineage-title">
    <div class="daily-research-command__section-heading">
      <div>
        <p class="daily-research-command__eyebrow">EVIDENCE CHAIN</p>
        <h2 id="daily-research-lineage-title" class="daily-research-command__section-title">artifact → manifest → current → receipt → API → UI</h2>
      </div>
      <span class="daily-research-command__section-note">同日期、同一 SHA 链</span>
    </div>
    <div class="daily-research-command__lineage-grid">
      <article v-for="layer in layers" :key="layer.name" class="daily-research-command__lineage-card">
        <div class="daily-research-command__lineage-topline">
          <strong>{{ layer.name }}</strong>
          <span :class="`daily-research-command__lineage-status--${layer.status.toLowerCase()}`">{{ layer.status }}</span>
        </div>
        <p>{{ layer.detail }}</p>
      </article>
    </div>
  </section>
</template>
