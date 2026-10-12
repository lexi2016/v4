<script setup lang="ts">
import { computed } from "vue";
import type { HkReview } from "../../contracts/review";
const props = defineProps<{ review: HkReview }>();

const researchStageUnion = computed(() => {
  const payload = props.review.model_selection_review;
  const observation = payload?.observed_stage_union;
  const selectedCodes = observation?.selected_codes;
  const hitCodes = observation?.hit_codes;
  const stageIds = observation?.stage_ids;
  const validStageIds = Array.isArray(stageIds)
    && stageIds.every((stage) => typeof stage === "string" && stage.trim() !== "")
    && new Set(stageIds).size === stageIds.length;
  const expectedStageCount = observation?.expected_stage_count;
  const validExpectedStageCount = typeof expectedStageCount === "number"
    && Number.isInteger(expectedStageCount)
    && expectedStageCount > 0;
  const cannotConfirm = Array.isArray(observation?.cannot_confirm)
    ? observation.cannot_confirm
    : null;
  const backfillRunIds = Array.isArray(observation?.backfill_run_ids)
    ? observation.backfill_run_ids
    : null;
  if (
    observation?.evidence_status !== "PARTIAL_RESEARCH_ONLY"
    || !Array.isArray(selectedCodes)
    || !selectedCodes.every((code) => typeof code === "string" && code.trim() !== "")
    || !Array.isArray(hitCodes)
    || !hitCodes.every((code) => typeof code === "string" && code.trim() !== "")
    || new Set(selectedCodes).size !== selectedCodes.length
    || new Set(hitCodes).size !== hitCodes.length
    || typeof observation.selected_count !== "number"
    || observation.selected_count !== selectedCodes.length
    || typeof observation.hit_count !== "number"
    || observation.hit_count !== hitCodes.length
    || hitCodes.some((code) => !selectedCodes.includes(code))
  ) return null;
  return {
    selectedCodes: new Set(selectedCodes),
    selectedCount: observation.selected_count,
    hitCount: observation.hit_count,
    stageRows: payload?.row_counts?.stage_rows,
    availableStageCount: validStageIds
      ? stageIds.length
      : null,
    expectedStageCount: validExpectedStageCount
      ? expectedStageCount
      : null,
    complete: validStageIds
      && validExpectedStageCount
      && Array.isArray(stageIds)
      && stageIds.length === expectedStageCount
      && cannotConfirm?.length === 0
      && backfillRunIds?.length === 0,
    cannotConfirm: cannotConfirm ?? [],
  };
});

const observedModel = computed(() => {
  const metric = props.review.model_selection_review?.models?.["observed_0.2_prob_active"];
  if (!metric || !("selected_codes" in metric) || !("hit_codes" in metric)) return null;
  const selectedCodes = metric.selected_codes;
  const hitCodes = metric.hit_codes;
  if (
    metric?.evidence_status !== "PARTIAL_RESEARCH_ONLY"
    || !Array.isArray(selectedCodes)
    || !selectedCodes.every((code) => typeof code === "string" && code.trim() !== "")
    || !Array.isArray(hitCodes)
    || !hitCodes.every((code) => typeof code === "string" && code.trim() !== "")
    || new Set(selectedCodes).size !== selectedCodes.length
    || new Set(hitCodes).size !== hitCodes.length
    || typeof metric.selected_count !== "number"
    || metric.selected_count !== selectedCodes.length
    || typeof metric.hit_count !== "number"
    || metric.hit_count !== hitCodes.length
    || hitCodes.some((code) => !selectedCodes.includes(code))
  ) return null;
  return {
    selectedCount: metric.selected_count,
    hitCount: metric.hit_count,
    expectedCount: metric.unique_score_codes ?? metric.score_rows ?? null,
  };
});

const formalModelFallback = computed(() => {
  const metric = props.review.model_selection_review?.models?.["0.2_prob_active"];
  if (
    metric?.evidence_status !== "READY"
    || typeof metric.selected_count !== "number"
    || !Number.isInteger(metric.selected_count)
    || metric.selected_count < 0
    || typeof metric.hit_count !== "number"
    || !Number.isInteger(metric.hit_count)
    || metric.hit_count < 0
  ) return null;
  return { selectedCount: metric.selected_count, hitCount: metric.hit_count };
});

type CloseTop20Row = {
  code?: string;
  observed_model_0_2_hit?: boolean | null;
  all_stages?: readonly string[];
};

const closeTop20Rows = computed(() => {
  const payload = props.review.model_selection_review;
  if (payload?.top20_attribution?.length) return payload.top20_attribution;
  return payload?.close_top20 ?? [];
});

const researchAvailable = computed(() => closeTop20Rows.value.length === 20
  && (observedModel.value !== null || researchStageUnion.value !== null));

const hk0925Replacement = computed(() => {
  const payload = props.review.model_selection_review;
  const marker = "HK_0925_REPLACED_BY_0930_0935_RESEARCH_ONLY";
  return payload?.cannot_confirm?.includes(marker) === true
    || payload?.observed_stage_union?.cannot_confirm?.includes(marker) === true;
});

const hasReviewEvidence = computed(() => {
  const payload = props.review.model_selection_review;
  return Boolean(
    Object.values(payload?.row_counts ?? {}).some((value) => typeof value === "number")
    || payload?.top20_attribution?.length
    || payload?.close_top20?.length
    || typeof payload?.models?.["0.2_prob_active"]?.hit_count === "number"
    || observedModel.value
    || typeof payload?.stage_union?.hit_count === "number"
    || researchStageUnion.value,
  );
});

function hitTop20(hitCount?: number | null) {
  return typeof hitCount === "number" ? `${hitCount}/20` : "不可用";
}

function percent(value?: number) {
  return typeof value === "number" ? `${value.toFixed(3).replace(/\.?0+$/, "")}%` : "缺证";
}

function top20CoveragePercent(hitCount?: number) {
  return typeof hitCount === "number" ? `${(hitCount / 20 * 100).toFixed(0)}%` : "不可用";
}

function hitLabel(value?: boolean | null) {
  return value === true ? "命中" : value === false ? "未命中" : "缺证";
}

function researchStageHit(code?: string): boolean | null {
  if (!researchStageUnion.value || !code) return null;
  if (researchStageUnion.value.selectedCodes.has(code)) return true;
  return researchStageUnion.value.complete ? false : null;
}

function researchAttribution(row: CloseTop20Row) {
  const modelHit = typeof row.observed_model_0_2_hit === "boolean" ? row.observed_model_0_2_hit : null;
  const stageHit = researchStageHit(row.code);
  if (modelHit === null || stageHit === null) return "研究证据覆盖不足，不能归因";
  if (modelHit && stageHit) return "研究模型与阶段均命中";
  if (modelHit) return "仅研究0.2命中";
  if (stageHit) return "仅研究阶段命中";
  return "研究模型与阶段均未命中";
}

const stageTimeLabels: Record<string, string> = {
  STAGE_0925: "港股通09:20 / A股09:25竞价选股",
  STAGE_0930_0935: "09:30-09:35",
  STAGE_0935_0940: "09:35-09:40",
  STAGE_0940_0945: "09:40-09:45",
  STAGE_0945_1030: "09:45-10:30",
  STAGE_1300_1315: "13:00-13:15",
  STAGE_1445_1500: "14:45-15:00",
  STAGE_1545_1555: "15:45-15:55港股",
};

function observedStageLabel(stages?: readonly string[]) {
  if (!stages?.length) return researchStageUnion.value?.complete ? "研究阶段并集未命中" : "现有阶段行未观察到";
  return stages.map((stage) => {
    if (stage === "STAGE_0925" && hk0925Replacement.value) return "09:20阶段（09:30–09:35替代）";
    return stageTimeLabels[stage] ?? `未识别阶段（${stage}）`;
  }).join(" → ");
}
</script>

<template>
  <section class="review-hk-panel" aria-label="HK close review">
    <h2>HK 收盘复盘</h2>
    <p v-if="researchAvailable" data-testid="hk-research-review-status">研究回补可用（非正式） · {{ review.model_selection_review?.primary_kpi ?? "全港股通收盘涨幅Top20覆盖率" }}</p>
    <p v-else>{{ review.model_selection_review?.status ?? "CANNOT_CONFIRM" }} · {{ review.model_selection_review?.primary_kpi ?? "全港股通收盘涨幅Top20覆盖率" }}</p>
    <p v-if="review.status === 'NON_TRADING_DAY' || review.model_selection_review?.status === 'NON_TRADING_DAY'" class="review-pending" data-testid="hk-close-non-trading">港股市场当日休市，没有收盘 Top20。</p>
    <p v-else-if="!hasReviewEvidence" class="review-pending">HK 收盘证据未物化；不把缺失显示为 0 命中。</p>
    <div v-if="hasReviewEvidence" class="review-metric-grid">
      <article v-if="observedModel"><span>研究选股 0.2（非正式）</span><strong>{{ hitTop20(observedModel.hitCount) }}</strong><small>{{ observedModel.selectedCount }}/{{ observedModel.expectedCount ?? "不可用" }} 行 · Top20 覆盖 {{ top20CoveragePercent(observedModel.hitCount) }} · PIT 未验证 · NO_BUY</small></article>
      <article v-else-if="formalModelFallback" data-testid="hk-formal-model-fallback"><span>0.2 模型指标（现有正式指标）</span><strong>{{ hitTop20(formalModelFallback.hitCount) }}</strong><small>正式候选 {{ formalModelFallback.selectedCount }} 行；逐项研究候选行缺证，未生成研究观察记录。</small></article>
      <article v-else data-testid="hk-observed-model-unavailable"><span>研究选股 0.2</span><strong>不可用</strong><small>没有可用研究候选行或现有正式指标</small></article>
      <article v-if="researchStageUnion" data-testid="hk-observed-stage-union"><span>{{ researchStageUnion.complete ? "研究阶段并集（非正式）" : "研究阶段并集（部分观察）" }}</span><strong>{{ hitTop20(researchStageUnion.hitCount) }}</strong><small>{{ researchStageUnion.availableStageCount ?? "阶段覆盖元数据缺证" }}/{{ researchStageUnion.expectedStageCount ?? "元数据缺证" }} 阶段 · {{ researchStageUnion.stageRows ?? "不可用" }} 行 / {{ researchStageUnion.selectedCount }} 个代码 · Top20 覆盖 {{ top20CoveragePercent(researchStageUnion.hitCount) }} · PIT 未验证 · NO_BUY</small></article>
      <article v-else><span>研究阶段并集</span><strong>不可用</strong><small>没有可用研究阶段行</small></article>
      <article><span>收盘 Top20</span><strong>{{ review.model_selection_review?.row_counts?.close_top20 ?? review.model_selection_review?.close_top20?.length ?? "不可用" }}</strong><small>精确日期真实收盘标签</small></article>
      <article><span>阶段证据行</span><strong>{{ review.model_selection_review?.row_counts?.stage_rows ?? "不可用" }}</strong><small>仅同日，不跨日回填</small></article>
    </div>
    <p v-if="researchStageUnion" class="partial-observation" data-state="RESEARCH_STAGE_UNION">
      {{ researchStageUnion.complete ? "七阶段研究数据覆盖完整；" : "当前研究阶段数据未覆盖完整或覆盖元数据缺证；" }}观察命中仅用于研究核对，不代表正式七阶段并集；PIT 未验证 · NO_BUY。
    </p>
    <p v-if="hk0925Replacement" class="partial-observation" data-testid="hk-0925-substitute-note">09:20阶段由09:30–09:35开盘数据替代补算；实际数据截止09:35。</p>
    <div v-if="hasReviewEvidence" class="review-table-wrap">
      <table>
        <thead><tr><th>排名</th><th>代码</th><th>名称</th><th>收盘涨幅</th><th>研究 0.2（非正式）</th><th>研究七阶段并集</th><th>对应阶段</th><th>研究归因</th></tr></thead>
        <tbody>
          <tr v-for="row in closeTop20Rows" :key="row.code">
            <td>{{ row.rank ?? "-" }}</td><td>{{ row.code ?? "-" }}</td><td>{{ row.name ?? "-" }}</td><td>{{ percent(row.pct_chg_close) }}</td>
            <td>{{ hitLabel(row.observed_model_0_2_hit) }}</td><td>{{ hitLabel(researchStageHit(row.code)) }}</td>
            <td>{{ observedStageLabel(row.all_stages) }}</td><td>{{ researchAttribution(row) }}</td>
          </tr>
          <tr v-if="!closeTop20Rows.length"><td colspan="8">该交易日没有可展示的收盘 Top20 归因，不把缺失解释为 0 命中。</td></tr>
        </tbody>
      </table>
    </div>
    <details v-if="hasReviewEvidence" class="formal-review-details" data-testid="hk-formal-review-details">
      <summary>正式指标、PIT与来源限制（未验证）</summary>
      <p>正式 0.2：{{ review.model_selection_review?.models?.["0.2_prob_active"]?.evidence_status ?? "CANNOT_CONFIRM" }} · 命中 {{ hitTop20(review.model_selection_review?.models?.["0.2_prob_active"]?.hit_count) }} · 入选 {{ review.model_selection_review?.models?.["0.2_prob_active"]?.selected_count ?? "不可用" }}</p>
      <p>正式七阶段并集：{{ review.model_selection_review?.stage_union?.evidence_status ?? "CANNOT_CONFIRM" }} · 命中 {{ hitTop20(review.model_selection_review?.stage_union?.hit_count) }} · 入选 {{ review.model_selection_review?.stage_union?.selected_count ?? "不可用" }}</p>
      <p v-if="review.model_selection_review?.missing_stages?.length">正式缺失阶段：{{ review.model_selection_review.missing_stages.map((stage) => stageTimeLabels[stage] ?? stage).join("、") }}</p>
      <p v-for="item in review.model_selection_review?.cannot_confirm ?? []" :key="item">{{ item }}</p>
    </details>
  </section>
</template>
