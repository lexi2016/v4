<script setup lang="ts">
import { computed } from "vue";
import type { HkReview } from "../../contracts/review";
const props = defineProps<{ review: HkReview }>();

const partialObservation = computed(() => {
  const payload = props.review.model_selection_review;
  const observation = payload?.observed_stage_union;
  const selectedCodes = observation?.selected_codes;
  const hitCodes = observation?.hit_codes;
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
  };
});

const closeTop20Rows = computed(() => {
  const payload = props.review.model_selection_review;
  if (payload?.top20_attribution?.length) return payload.top20_attribution;
  return payload?.close_top20 ?? [];
});

const hasReviewEvidence = computed(() => {
  const payload = props.review.model_selection_review;
  return Boolean(
    Object.values(payload?.row_counts ?? {}).some((value) => typeof value === "number")
    || payload?.top20_attribution?.length
    || payload?.close_top20?.length
    || typeof payload?.models?.["0.2_prob_active"]?.hit_count === "number"
    || typeof payload?.stage_union?.hit_count === "number"
    || partialObservation.value,
  );
});

function hitTop20(hitCount?: number | null) {
  return typeof hitCount === "number" ? `${hitCount}/20` : "不可用";
}

function percent(value?: number) {
  return typeof value === "number" ? `${value.toFixed(3).replace(/\.?0+$/, "")}%` : "缺证";
}

function classification(value?: string) {
  return ({ shared: "共同命中", model_only: "仅0.2", stage_only: "仅阶段", neither: "均未命中" } as Record<string, string>)[value ?? ""] ?? value ?? "缺证";
}

function hitLabel(value?: boolean | null) {
  return value === true ? "命中" : value === false ? "未命中" : "缺证";
}

function formalStageUnionHit(value?: boolean | null) {
  const metric = props.review.model_selection_review?.stage_union;
  if (metric?.evidence_status !== "READY"
    || typeof metric.selected_count !== "number"
    || typeof metric.hit_count !== "number") return null;
  return value;
}

type PartialObservationState = "OBSERVED_PRESENT" | "NOT_OBSERVED_IN_PARTIAL_ROWS" | "CANNOT_CONFIRM";

function partialObservationState(code?: string): PartialObservationState {
  if (!partialObservation.value || !code) return "CANNOT_CONFIRM";
  return partialObservation.value.selectedCodes.has(code)
    ? "OBSERVED_PRESENT"
    : "NOT_OBSERVED_IN_PARTIAL_ROWS";
}

function partialObservationLabel(code?: string) {
  const state = partialObservationState(code);
  return state === "OBSERVED_PRESENT"
    ? "已在部分行中观察到"
    : state === "NOT_OBSERVED_IN_PARTIAL_ROWS"
      ? "未在现有部分行中观察到"
      : "不能确认";
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
  if (!stages?.length) return "现有证据未见命中";
  return stages.map((stage) => stageTimeLabels[stage] ?? `未识别阶段（${stage}）`).join(" → ");
}
</script>

<template>
  <section class="review-hk-panel" aria-label="HK close review">
    <h2>HK 收盘复盘</h2>
    <p>{{ review.model_selection_review?.status ?? "CANNOT_CONFIRM" }} · {{ review.model_selection_review?.primary_kpi ?? "全港股通收盘涨幅Top20覆盖率" }}</p>
    <p v-if="!hasReviewEvidence" class="review-pending">HK 收盘证据未物化；不把缺失显示为 0 命中。</p>
    <div v-if="hasReviewEvidence" class="review-metric-grid">
      <article><span>0.2 模型</span><strong>{{ hitTop20(review.model_selection_review?.models?.["0.2_prob_active"]?.hit_count) }}</strong><small>入选 {{ review.model_selection_review?.models?.["0.2_prob_active"]?.selected_count ?? "不可用" }}</small></article>
      <article><span>正式七阶段并集</span><strong>{{ hitTop20(review.model_selection_review?.stage_union?.hit_count) }}</strong><small>入选 {{ review.model_selection_review?.stage_union?.selected_count ?? "不可用" }}</small></article>
      <article><span>收盘 Top20</span><strong>{{ review.model_selection_review?.row_counts?.close_top20 ?? review.model_selection_review?.close_top20?.length ?? "不可用" }}</strong><small>精确日期真实收盘标签</small></article>
      <article><span>阶段证据行</span><strong>{{ review.model_selection_review?.row_counts?.stage_rows ?? "不可用" }}</strong><small>仅同日，不跨日回填</small></article>
    </div>
    <article v-if="partialObservation" class="partial-observation" data-state="PARTIAL_OBSERVATION">
      <h3>部分观察并集（不完整）</h3>
      <p><strong>{{ hitTop20(partialObservation.hitCount) }}</strong> 个 Top20 代码在现有部分行中观察到</p>
      <p>{{ partialObservation.stageRows ?? "不可用" }} 条同日观察行（累计行数） · {{ partialObservation.selectedCount }} 个去重代码</p>
      <p>正式七阶段并集仍为缺证；部分观察不代表完整覆盖，不计算正式覆盖率。</p>
    </article>
    <p v-if="review.model_selection_review?.missing_stages?.length">
      缺失阶段：{{ review.model_selection_review.missing_stages.map((stage) => stageTimeLabels[stage] ?? stage).join("、") }}
    </p>
    <p v-for="item in review.model_selection_review?.cannot_confirm ?? []" :key="item">{{ item }}</p>
    <div v-if="hasReviewEvidence" class="review-table-wrap">
      <table>
        <thead><tr><th>排名</th><th>代码</th><th>名称</th><th>收盘涨幅</th><th>0.2</th><th>正式阶段并集</th><th>部分行观察状态</th><th>观察命中阶段（部分证据）</th><th>归因</th></tr></thead>
        <tbody>
          <tr v-for="row in closeTop20Rows" :key="row.code">
            <td>{{ row.rank ?? "-" }}</td><td>{{ row.code ?? "-" }}</td><td>{{ row.name ?? "-" }}</td><td>{{ percent(row.pct_chg_close) }}</td>
            <td>{{ hitLabel(row.model_0_2_hit) }}</td><td>{{ hitLabel(formalStageUnionHit(row.stage_union_hit)) }}</td>
            <td :data-state="partialObservationState(row.code)">{{ partialObservationLabel(row.code) }}</td>
            <td>{{ observedStageLabel(row.all_stages) }}</td><td>{{ classification(row.classification) }}</td>
          </tr>
          <tr v-if="!closeTop20Rows.length"><td colspan="9">该交易日没有可展示的收盘 Top20 归因，不把缺失解释为 0 命中。</td></tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
