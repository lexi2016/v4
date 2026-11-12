<script setup lang="ts">
import type { AShareReview } from "../../contracts/review";
defineProps<{ review: AShareReview; productionAllowed: false; buyGateUpdated: false; ordersSent: false }>();

function evidenceLabel(row: Readonly<Record<string, unknown>>) {
  const title = row.name ?? row.title ?? row["项目"] ?? row.code ?? row.id ?? "CANNOT_CONFIRM";
  const detail = [row["结果"], row["说明"], row.value].filter(Boolean).map(String).join(" · ");
  return detail ? `${String(title)} · ${detail}` : String(title);
}
</script>

<template>
  <section class="review-evidence-panel">
    <h3>自动复盘/证据缺口</h3>
    <p><strong>来源角色</strong> · {{ review.source_role || "CANNOT_CONFIRM" }}</p>
    <p v-for="row in review.source_evidence ?? []" :key="String(row.source_id ?? row.id ?? row.path)" data-testid="source-evidence-row">{{ evidenceLabel(row) }}</p>
    <p v-for="row in review.quality_gate" :key="String(row.id ?? row.code ?? row['项目'])" data-testid="quality-gap-row">{{ evidenceLabel(row) }}</p>
    <p v-for="item in review.cannot_confirm" :key="item">{{ item }}</p>
    <p class="review-safety">production_allowed={{ productionAllowed }} · buy_gate_updated={{ buyGateUpdated }} · orders_sent={{ ordersSent }}</p>
    <details><summary>路径、哈希与诊断</summary><dl><div><dt>trade_date</dt><dd>{{ review.trade_date ?? "NOT_MATERIALIZED" }}</dd></div><div><dt>schema</dt><dd>{{ review.schema_version ?? "CANNOT_CONFIRM" }}</dd></div><div><dt>model_status</dt><dd>{{ review.model_review?.status ?? "NOT_MATERIALIZED" }}</dd></div><div><dt>source_sha256</dt><dd>{{ review.source_sha256 || "NOT_MATERIALIZED" }}</dd></div><div><dt>write_policy</dt><dd>{{ review.write_policy ?? "CANNOT_CONFIRM" }}</dd></div></dl><p>仅本地只读证据；不生成订单或更新 BUY gate。</p></details>
  </section>
</template>
