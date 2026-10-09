<script setup lang="ts">
import { computed } from "vue";
import type { StageExecutionEvidenceReadback } from "../../contracts/runtime";
const props = defineProps<{ evidence: StageExecutionEvidenceReadback }>();

function counter(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : null;
}
function quoteText(requested: number | null, source: number | null, declaredMissing?: unknown) {
  if (requested === null || source === null) {
    return `行情 ${source ?? "未知"} / ${requested ?? "未知"} 只；缺口数量未知`;
  }
  const missing = requested - source;
  if (missing < 0 || (declaredMissing != null && counter(declaredMissing) !== missing)) {
    return `行情计数待核对（来源 ${source}；请求 ${requested}）`;
  }
  return `行情 ${source} / ${requested} 只，缺 ${missing} 只`;
}
function resultBinding(market: string) {
  const binding = props.evidence.selection_artifact_bindings?.[market]?.status;
  const legacy = props.evidence.markets?.[market]?.selection_binding;
  if (binding === "SELECTION_TRIO_CONFLICT" || legacy === "SELECTION_IDENTITY_CONFLICT" || legacy === "SELECTION_COUNT_CONFLICT") {
    return "结果与运行记录的身份冲突，待核对";
  }
  if (binding === "BOUND_TO_VERIFIED_SELECTION_TRIO") return "结果与原执行记录已绑定";
  if (binding === "SELECTION_TRIO_MATCHES_CURRENT_RECEIPT_HISTORY_UNBOUND") return "结果引用相符，历史记录未绑定";
  return "执行记录尚未完整绑定";
}
const marketViews = computed(() => {
  const markets = props.evidence.stage_id === "STAGE_1545_1555" ? ["HK_CONNECT"] : ["A_SHARE", "HK_CONNECT"];
  return markets.map(market => {
    const lane = props.evidence.markets?.[market];
    const hasSummary = Object.prototype.hasOwnProperty.call(props.evidence.selection_results ?? {}, market);
    const result = props.evidence.selection_results?.[market];
    const selected = counter(hasSummary ? result?.selected_rows : lane?.selected_rows);
    const available = hasSummary
      ? (result?.status === "RESULT_AVAILABLE" && selected !== null && selected > 0)
        || (result?.status === "VERIFIED_EMPTY_RESULT" && selected === 0)
      : lane?.selection_binding === "BOUND_TO_VERIFIED_SELECTION" && selected !== null;
    const preselectionBlocked = market === "HK_CONNECT" && (
      lane?.failure_layer === "PRESELECTION_INPUT"
      || lane?.reasons?.some(reason => reason.includes("HK D1 status must be STRICT_0_2_READY"))
    );
    const requested = counter(hasSummary ? (available ? result?.requested_rows : null) : lane?.requested_rows);
    const source = counter(hasSummary ? (available ? result?.source_rows : null) : (lane?.source_rows ?? lane?.observed_rows));
    return {
      market, name: market === "A_SHARE" ? "A股" : "港股通",
      headline: available ? (selected === 0 ? "已保存空结果（0 只）" : `已计算 ${selected} 只`)
        : preselectionBlocked ? "预选池未就绪，未进入算法" : "选股结果待核对",
      quote: quoteText(requested, source, hasSummary && available ? result?.missing_quote_rows : undefined),
      countSource: hasSummary ? (available ? "选股产物计数" : "行情计数未绑定") : "回执记录计数",
      binding: resultBinding(market),
      blockedAttemptWithSavedResult: available && preselectionBlocked,
    };
  });
});
const modeText = computed(() => {
  const mode = props.evidence.attempt_mode;
  if (!mode) return "未记录";
  if (mode === "NATURAL") return "自然触发（NATURAL）";
  if (mode === "RECOVERY") return "补跑（RECOVERY）";
  return `其他方式（${mode}）`;
});
const historyText = computed(() => {
  const binding = props.evidence.receipt_history_binding;
  if (binding === "OWNER_HISTORY_SHA_BOUND") return "已核对";
  if (binding === "OWNER_HISTORY_CONFLICT") return "身份冲突，待核对";
  return !binding || binding === "OWNER_HISTORY_NOT_RECORDED" ? "未记录" : "待核对";
});
const recordTimeText = computed(() => {
  if (!props.evidence.recorded_at) return "原回执未记录";
  return props.evidence.receipt_history_binding === "OWNER_HISTORY_SHA_BOUND"
    && props.evidence.record_time_status === "OWNER_WRITE_CLOCK_RECORDED"
    ? props.evidence.recorded_at : "待核对";
});
function detail(value: unknown) { return JSON.stringify(value, null, 2); }
</script>
<template>
  <section class="execution-evidence" aria-label="阶段选股结果与运行记录">
    <h3>本阶段选股结果</h3>
    <p>{{ evidence.trade_date }} · {{ evidence.stage_id }}</p>
    <div class="execution-markets">
      <article v-for="lane in marketViews" :key="lane.market" :data-market="lane.market">
        <h4>{{ lane.name }}</h4>
        <p class="execution-result"><strong>{{ lane.headline }}</strong></p>
        <p>{{ lane.quote }}<small class="execution-count-source">{{ lane.countSource }}</small></p>
        <p v-if="lane.blockedAttemptWithSavedResult">当前回执：预选池未就绪，未进入算法。</p>
        <p>{{ lane.binding }}</p>
      </article>
    </div>
    <h4>运行记录与验收</h4>
    <dl class="execution-facts">
      <div><dt>运行方式（回执声明）</dt><dd>{{ modeText }}</dd></div>
      <div><dt>原执行方历史记录</dt><dd>{{ historyText }}</dd></div>
      <div><dt>记录时间</dt><dd>{{ recordTimeText }}</dd></div>
      <div><dt>自然时段验收</dt><dd>尚未验证</dd></div>
    </dl>
    <p>执行过程与自然时段仍需独立验收。</p>
    <details><summary>查看运行与来源详情</summary>
      <pre>{{ detail(evidence) }}</pre>
    </details>
  </section>
</template>
<style scoped>
.execution-evidence { padding: 1rem; border: 1px solid #cbd5e1; margin-block: 1rem; }
.execution-markets { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 22rem), 1fr)); gap: 1rem; }
.execution-result { font-size: 1.1rem; }
.execution-count-source { display: block; margin-top: 0.25rem; }
.execution-facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 15rem), 1fr)); gap: 1rem; }
.execution-facts dt { font-weight: 600; }
.execution-facts dd { margin: 0.25rem 0 0; overflow-wrap: anywhere; }
.execution-evidence pre, .execution-evidence code, .execution-evidence p { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
