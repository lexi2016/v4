<script setup lang="ts">
import type { StageExecutionEvidenceReadback } from "../../contracts/runtime";
defineProps<{ evidence: StageExecutionEvidenceReadback }>();
function count(value: number | null | undefined) { return typeof value === "number" && Number.isFinite(value) ? String(value) : "未记录／未绑定"; }
function detail(value: unknown) { return JSON.stringify(value, null, 2); }
</script>
<template>
  <section class="execution-evidence" aria-label="阶段执行声明与选股身份">
    <h3>执行尝试与已验证产物分列</h3>
    <p>{{ evidence.trade_date }} · {{ evidence.stage_id }} · {{ evidence.status }}</p>
    <p>尝试模式（回执声明）：{{ evidence.attempt_mode || "未记录" }} / {{ evidence.due_status || "未记录" }}；记录时间：{{ evidence.recorded_at || "原回执未记录，不推断历史开始时间" }}</p>
    <p>执行状态（声明）：{{ evidence.declared_status || "未记录" }}；节点尝试：{{ count(evidence.node_attempt_count) }} · {{ evidence.node_outcome || "未记录" }}</p>
    <p v-if="evidence.first_failed_layer || evidence.error">首次失败层：{{ evidence.first_failed_layer || "未定位" }}；{{ evidence.error }}</p>
    <p>此处不独立认证自然／补跑血缘。选股身份匹配只验证对应产物引用；原回执自计算SHA不是运行认证。</p>
    <div class="execution-markets">
      <article v-for="(lane, market) in evidence.markets" :key="market">
        <h4>{{ market }} · {{ lane.status || "未记录" }}</h4>
        <p>选股引用：{{ lane.selection_binding }}</p>
        <p>回执计数：请求 {{ count(lane.requested_rows) }} / 来源 {{ count(lane.source_rows ?? lane.observed_rows) }} / 接受 {{ count(lane.accepted_rows) }} / 选择 {{ count(lane.selected_rows) }}</p>
        <p>失败层：{{ lane.failure_layer || "未记录或未定位" }}</p>
        <p v-if="lane.diagnostics">页调用 {{ lane.diagnostics.pages_read ?? "未知" }}；精确成交 {{ lane.diagnostics.exact_time_count ?? "未知" }}；接受成交 {{ lane.diagnostics.accepted_tick_count ?? "未知" }}；READ_ERROR {{ lane.diagnostics.read_error_count ?? "未知" }}。页调用不等于请求宇宙或有效响应页。</p>
        <details><summary>原失败原因、计数与身份（不改写历史）</summary><pre>{{ detail({ reasons: lane.reasons, diagnostics: lane.diagnostics, declared_identity: lane.declared_identity }) }}</pre></details>
      </article>
    </div>
    <details><summary>绑定缺口与所读回执</summary>
      <p v-for="reason in evidence.cannot_confirm" :key="reason">{{ reason }}</p>
      <p>候选宇宙：{{ evidence.candidate_run_id || "未记录" }} · {{ evidence.candidate_binding || "未核验" }}</p>
      <code>{{ evidence.candidate_current_sha256 }}</code>
      <p>读取路径：{{ evidence.receipt_path || "未绑定" }}</p><code>观察到的原字节SHA：{{ evidence.observed_sha256 || "未读取" }}</code>
      <p>历史坏行：{{ evidence.historical_bad_row_status }}；未由未来诊断反填。</p>
    </details>
  </section>
</template>
<style scoped>
.execution-evidence { padding: 1rem; border: 1px solid #cbd5e1; margin-block: 1rem; }
.execution-markets { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 22rem), 1fr)); gap: 1rem; }
.execution-evidence pre, .execution-evidence code, .execution-evidence p { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
