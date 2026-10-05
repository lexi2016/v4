<script setup lang="ts">
import { computed } from "vue";
import type { HkPrefixResearch, HkReview } from "../../contracts/review";
const props = defineProps<{ review: HkReview; historical?: HkPrefixResearch }>();

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

const historicalStatus = computed(() => props.historical?.status ?? "CANNOT_CONFIRM");
const historicalReasons = computed(() => props.historical?.cannot_confirm ?? ["HK_PREFIX_RESEARCH_NOT_IN_RESPONSE"]);
const historicalStateRows = computed(() => {
  const distribution = props.historical?.export?.state_distribution ?? {};
  const byEvent = props.historical?.export?.state_distribution_by_event_type ?? {};
  const states = new Set(Object.keys(distribution));
  Object.values(byEvent).forEach((values) => Object.keys(values ?? {}).forEach((state) => states.add(state)));
  return [...states].sort().map((state) => ({
    state,
    label: ({
      NO_ACTIVE_SETUP: "无活动形态",
      WARMUP: "预热期",
      BROKEN_PENDING: "破坏待定",
      RECLAIMED: "收复",
      REPAIR_FAILED_TIMEOUT: "修复超时",
      UNKNOWN: "未知",
    } as Record<string, string>)[state] ?? state,
    total: distribution[state] ?? 0,
    newEvent: byEvent.new_event?.[state] ?? 0,
    continuation: byEvent.continuation_event?.[state] ?? 0,
  }));
});

function numberOrGap(value?: number) {
  return typeof value === "number" ? value.toLocaleString("en-US") : "缺证";
}

function rangeOrGap(value?: readonly string[]) {
  return value?.length ? value.join(" → ") : "缺证";
}

function shortHash(value?: string) {
  return value ? `${value.slice(0, 12)}…` : "缺证";
}
</script>

<template>
  <section class="review-hk-panel" aria-label="HK close review">
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
        <thead><tr><th>排名</th><th>代码</th><th>名称</th><th>收盘涨幅</th><th>0.2</th><th>阶段并集</th><th>归因</th></tr></thead>
        <tbody>
          <tr v-for="row in review.model_selection_review?.top20_attribution ?? []" :key="row.code">
            <td>{{ row.rank ?? "-" }}</td><td>{{ row.code ?? "-" }}</td><td>{{ row.name ?? "-" }}</td><td>{{ percent(row.pct_chg_close) }}</td>
            <td>{{ hitLabel(row.model_0_2_hit) }}</td><td>{{ hitLabel(row.stage_union_hit) }}</td><td>{{ classification(row.classification) }}</td>
          </tr>
          <tr v-if="!(review.model_selection_review?.top20_attribution?.length)"><td colspan="7">该交易日没有可展示的收盘 Top20 归因，不把缺失解释为 0 命中。</td></tr>
        </tbody>
      </table>
    </div>
  </section>

  <section class="review-hk-prefix-panel" aria-label="HK historical prefix research" data-testid="hk-prefix-research">
    <div class="section-heading">
      <div>
        <span class="eyebrow">HISTORICAL_PREFIX_RESEARCH</span>
        <h2>历史前缀研究资产</h2>
      </div>
      <p>{{ historicalStatus }} · 独立于每日选股</p>
    </div>
    <p class="review-pending">历史 prefix 代理只作状态与证据展示，不作为 alpha、买入或每日选股结论。</p>

    <p v-if="historicalStatus !== 'READY'" class="review-pending">
      历史资产未通过固定 binding 校验；当前状态保持 {{ historicalStatus }}，不把缺失解释为 0。
    </p>
    <ul v-if="historicalStatus !== 'READY'" class="review-prefix-cannot-confirm">
      <li v-for="reason in historicalReasons" :key="reason">{{ reason }}</li>
    </ul>

    <template v-if="historicalStatus === 'READY' && historical">
      <div class="review-metric-grid">
        <article><span>冻结窗口</span><strong>{{ numberOrGap(historical.export?.series_count) }} × {{ numberOrGap(historical.export?.rows_per_series) }}</strong><small>{{ numberOrGap(historical.export?.total_rows) }} 行匿名 OHLCV</small></article>
        <article><span>冻结绑定</span><strong>{{ numberOrGap(historical.binding?.groups) }} 组 / {{ numberOrGap(historical.binding?.controls) }} 对照</strong><small>不可重采样 · {{ numberOrGap(historical.binding?.series_count) }} 条序列</small></article>
        <article><span>源覆盖</span><strong>{{ numberOrGap(historical.source?.symbols) }} 个代码</strong><small>{{ numberOrGap(historical.source?.rows) }} 行 · {{ rangeOrGap(historical.source?.date_range) }}</small></article>
        <article><span>市场日连接</span><strong>{{ numberOrGap(historical.calendar?.market_day_count) }} 日</strong><small>{{ historical.calendar?.certification ?? "缺证" }}</small></article>
        <article class="review-prefix-contract-card"><span>末日可判覆盖</span><strong>{{ historical.export?.coverage_fraction ?? `${historical.export?.complete_terminal_pairs ?? "缺证"}/${historical.binding?.groups ?? "缺证"}` }}</strong><small>{{ historical.export?.coverage_status ?? "缺证" }} · 要求 {{ historical.export?.required_complete_pairs ?? "缺证" }}/{{ historical.binding?.groups ?? "缺证" }}</small></article>
      </div>

      <div class="review-prefix-meta">
        <p><strong>事件窗口：</strong>{{ rangeOrGap(historical.scope?.event_date_range) }}；最长事件年份 {{ historical.scope?.max_event_year ?? "缺证" }}，2026 未消费。</p>
        <p><strong>未知与不可判：</strong>{{ numberOrGap(historical.export?.unknown_series_count) }} 条序列 / {{ numberOrGap(historical.export?.unknown_row_count) }} 行；末日不可判 {{ numberOrGap(historical.export?.terminal_indeterminate_series_count) }} 条，WARMUP 与 UNKNOWN 均不当作已知无活动形态。</p>
        <p><strong>源字段：</strong>{{ historical.source?.volume_source_column ?? "缺证" }}（{{ historical.source?.volume_unit ?? "单位未知" }}）；价格口径 {{ historical.source?.price_basis_status ?? "缺证" }}。</p>
        <p class="review-prefix-gate"><strong>本批覆盖门：</strong>{{ historical.export?.coverage_fraction ?? "缺证" }}，低于要求 {{ historical.export?.required_complete_pairs ?? "缺证" }}/{{ historical.binding?.groups ?? "缺证" }}；状态 {{ historical.export?.coverage_status ?? "缺证" }}。窗口占用仅作描述，不作为末日主效果。</p>
      </div>

      <div class="review-table-wrap">
        <table>
          <caption>末日状态分布（按事件类型分列）</caption>
          <thead><tr><th>状态</th><th>new_event</th><th>continuation_event</th><th>合计</th></tr></thead>
          <tbody>
            <tr v-for="row in historicalStateRows" :key="row.state">
              <td>{{ row.label }} <small>({{ row.state }})</small></td>
              <td>{{ row.newEvent }}</td><td>{{ row.continuation }}</td><td>{{ row.total }}</td>
            </tr>
            <tr v-if="!historicalStateRows.length"><td colspan="4">状态分布缺证。</td></tr>
          </tbody>
        </table>
      </div>

      <div class="review-prefix-meta">
        <p><strong>机器验收：</strong>字段隔离 {{ historical.acceptance?.field_isolation ?? "缺证" }}；未来隔离 {{ historical.acceptance?.future_isolation ?? "缺证" }}；过去正例控制 {{ historical.acceptance?.past_positive_control ?? "缺证" }}；96 序列 CSV 重放 {{ historical.acceptance?.csv_replay ?? "缺证" }}。</p>
        <p><strong>本批结论：</strong>{{ historical.review?.conclusion ?? "缺证" }}</p>
        <p><strong>人工复核：</strong>{{ historical.review?.manual_review_status ?? "NOT_REVIEWED" }}；对照状态 {{ historical.review?.comparison_status ?? "CANNOT_CONFIRM" }}。</p>
      </div>

      <div class="review-prefix-evidence">
        <strong>证据引用</strong>
        <ul>
          <li v-for="item in historical.evidence ?? []" :key="`${item.ref}-${item.sha256}`">
            {{ item.label ?? "证据" }} · {{ item.ref ?? "缺证" }} · {{ shortHash(item.sha256) }}
          </li>
        </ul>
      </div>
      <ul v-if="historical.cannot_confirm?.length" class="review-prefix-cannot-confirm">
        <li v-for="reason in historical.cannot_confirm" :key="reason">{{ reason }}</li>
      </ul>
    </template>
  </section>
</template>
