<script setup lang="ts">
import { computed } from "vue";
import type { AShareReview } from "../../contracts/review";
const props = defineProps<{ review: AShareReview; productionAllowed: false; buyGateUpdated: false; ordersSent: false }>();

type FailureRow = Readonly<Record<string, unknown>>;
type ReviewWithFailure = AShareReview & {
  first_failed_layer?: FailureRow;
  failure_chain?: readonly FailureRow[];
  failure_summary?: string;
};
const failureReview = computed(() => props.review as ReviewWithFailure);
const firstFailure = computed(() => failureReview.value.first_failed_layer);
const failureChain = computed<readonly FailureRow[]>(() => failureReview.value.failure_chain ?? []);

function failureValue(row: FailureRow, key: string): string {
  const value = row[key];
  return value === undefined || value === null || value === "" ? "未确认" : String(value);
}

function evidenceLabel(row: Readonly<Record<string, unknown>>) {
  const title = row.name ?? row.title ?? row["项目"] ?? row.code ?? row.id ?? "CANNOT_CONFIRM";
  const detail = [row["结果"], row["说明"], row.value].filter(Boolean).map(String).join(" · ");
  return detail ? `${String(title)} · ${detail}` : String(title);
}
</script>

<template>
  <section class="review-evidence-panel">
    <h3>自动复盘/证据缺口</h3>
    <section v-if="firstFailure" class="review-first-failure-evidence" data-testid="review-first-failure-evidence">
      <h4>首断点与下游失败链</h4>
      <p>{{ failureReview.failure_summary || "首断点与下游失败链未确认" }}</p>
      <div v-for="(row, index) in failureChain" :key="failureValue(row, 'layer') + '-' + index" class="review-first-failure-row" data-testid="review-first-failure-row">
        <strong>{{ failureValue(row, "layer") }} · {{ failureValue(row, "owner") }} · {{ failureValue(row, "status") }}</strong>
        <span>期望日期{{ failureValue(row, "expected_date") }} · 观测日期{{ failureValue(row, "observed_date") }} · {{ failureValue(row, "failure_class") }}</span>
        <span>receipt/path {{ failureValue(row, "receipt_path") }}<template v-if="row.path"> · {{ failureValue(row, "path") }}</template></span>
      </div>
      <p v-if="!failureChain.length">CANNOT_CONFIRM · 首断点链未物化。</p>
    </section>
    <p><strong>来源角色</strong> · {{ review.source_role || "CANNOT_CONFIRM" }}</p>
    <p v-for="row in review.source_evidence ?? []" :key="String(row.source_id ?? row.id ?? row.path)" data-testid="source-evidence-row">{{ evidenceLabel(row) }}</p>
    <p v-for="row in review.quality_gate" :key="String(row.id ?? row.code ?? row['项目'])" data-testid="quality-gap-row">{{ evidenceLabel(row) }}</p>
    <p v-for="item in review.cannot_confirm" :key="item">{{ item }}</p>
    <p class="review-safety">production_allowed={{ productionAllowed }} · buy_gate_updated={{ buyGateUpdated }} · orders_sent={{ ordersSent }}</p>
    <details><summary>路径、哈希与诊断</summary><dl><div><dt>trade_date</dt><dd>{{ review.trade_date ?? "NOT_MATERIALIZED" }}</dd></div><div><dt>schema</dt><dd>{{ review.schema_version ?? "CANNOT_CONFIRM" }}</dd></div><div><dt>model_status</dt><dd>{{ review.model_review?.status ?? "NOT_MATERIALIZED" }}</dd></div><div><dt>source_sha256</dt><dd>{{ review.source_sha256 || "NOT_MATERIALIZED" }}</dd></div><div><dt>write_policy</dt><dd>{{ review.write_policy ?? "CANNOT_CONFIRM" }}</dd></div></dl><p>仅本地只读证据；不生成订单或更新 BUY gate。</p></details>
  </section>
</template>
