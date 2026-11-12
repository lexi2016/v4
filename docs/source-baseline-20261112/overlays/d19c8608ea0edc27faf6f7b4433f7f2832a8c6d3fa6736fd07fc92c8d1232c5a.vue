<script setup lang="ts">
import { computed } from "vue";
import type { HkReview } from "../../contracts/review";
import { UNKNOWN_STOCK_NAME, text } from "../../composables/useResearchLane";
const props = defineProps<{ review: HkReview }>();

const STAGE_LABELS: Record<string, string> = {
  STAGE_0925: "09:20/09:25竞价参考",
  STAGE_0930_0935: "09:30-09:35",
  STAGE_0935_0940: "09:35-09:40",
  STAGE_0940_0945: "09:40-09:45",
  STAGE_0945_1030: "09:45-10:30",
  STAGE_1300_1315: "13:00-13:15",
  STAGE_1445_1500: "14:45-15:00",
  STAGE_1545_1555: "15:45-15:55港股",
};

const hasReviewEvidence = computed(() => {
  const payload = props.review.model_selection_review;
  return Boolean(
    Object.values(payload?.row_counts ?? {}).some((value) => typeof value === "number")
    || payload?.top20_attribution?.length
    || payload?.close_top20?.length
    || typeof payload?.models?.["0.2_prob_active"]?.hit_count === "number"
    || typeof payload?.stage_union?.hit_count === "number",
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

function hitLabel(value?: boolean) {
  return value === true ? "命中" : value === false ? "未命中" : "缺证";
}

function stageLabel(value?: string | null) {
  const stage = text(value);
  return stage ? STAGE_LABELS[stage] ?? stage : "未进入具体阶段";
}

function firstStage(row: { first_stage?: string | null; all_stages?: readonly string[] }) {
  return stageLabel(text(row.first_stage) || row.all_stages?.[0]);
}

function allStages(row: { all_stages?: readonly string[] }) {
  const stages = (row.all_stages ?? []).map((stage) => stageLabel(stage));
  return stages.length ? stages.join("、") : "未进入具体阶段";
}

function stockName(value?: string) {
  return text(value) || UNKNOWN_STOCK_NAME;
}
</script>

<template>
  <section id="hkCloseReviewPanel" class="review-hk-panel" tabindex="-1" aria-label="HK close review">
    <h2>HK 收盘复盘</h2>
    <p>{{ review.model_selection_review?.status ?? "CANNOT_CONFIRM" }} · {{ review.model_selection_review?.primary_kpi ?? "全港股通收盘涨幅Top20覆盖率" }}</p>
    <p v-if="!hasReviewEvidence" class="review-pending">HK 收盘证据未物化；不把缺失显示为 0 命中。</p>
    <div v-if="hasReviewEvidence" class="review-metric-grid">
      <article><span>0.2 模型</span><strong>{{ hitTop20(review.model_selection_review?.models?.["0.2_prob_active"]?.hit_count) }}</strong><small>入选 {{ review.model_selection_review?.models?.["0.2_prob_active"]?.selected_count ?? "不可用" }}</small></article>
      <article><span>七阶段并集</span><strong>{{ hitTop20(review.model_selection_review?.stage_union?.hit_count) }}</strong><small>入选 {{ review.model_selection_review?.stage_union?.selected_count ?? "不可用" }}</small></article>
      <article><span>收盘 Top20</span><strong>{{ review.model_selection_review?.row_counts?.close_top20 ?? review.model_selection_review?.close_top20?.length ?? "不可用" }}</strong><small>精确日期真实收盘标签</small></article>
      <article><span>阶段证据行</span><strong>{{ review.model_selection_review?.row_counts?.stage_rows ?? "不可用" }}</strong><small>仅同日，不跨日回填</small></article>
    </div>
    <p v-for="item in review.model_selection_review?.cannot_confirm ?? []" :key="item">{{ item }}</p>
    <div v-if="hasReviewEvidence" class="review-table-wrap">
      <table>
        <thead><tr><th>排名</th><th>代码</th><th>名称</th><th>收盘涨幅</th><th>0.2</th><th>阶段并集</th><th>首个阶段</th><th>全部阶段</th><th>归因</th></tr></thead>
        <tbody>
          <tr v-for="row in review.model_selection_review?.top20_attribution ?? []" :key="row.code">
            <td>{{ row.rank ?? "-" }}</td><td>{{ row.code ?? "-" }}</td><td>{{ stockName(row.name) }}</td><td>{{ percent(row.pct_chg_close) }}</td>
            <td>{{ hitLabel(row.model_0_2_hit) }}</td><td>{{ hitLabel(row.stage_union_hit) }}</td><td>{{ firstStage(row) }}</td><td>{{ allStages(row) }}</td><td>{{ classification(row.classification) }}</td>
          </tr>
          <tr v-if="!(review.model_selection_review?.top20_attribution?.length)"><td colspan="9">该交易日没有可展示的收盘 Top20 归因，不把缺失解释为 0 命中。</td></tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
