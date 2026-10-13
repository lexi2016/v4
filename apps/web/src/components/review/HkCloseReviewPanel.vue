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

function hitLabel(value?: boolean | null) {
  return value === true ? "命中" : value === false ? "未命中" : "缺证";
}

const observedModel = computed(() => {
  const metric = props.review.model_selection_review?.models?.["observed_0.2_prob_active"];
  const selectedCodes = metric?.selected_codes;
  const hitCodes = metric?.hit_codes;
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
    || typeof metric.hit_count !== "number"
    || !Number.isInteger(metric.selected_count)
    || !Number.isInteger(metric.hit_count)
  ) return null;
  return { selectedCount: metric.selected_count, hitCount: metric.hit_count };
});

const observedStageUnion = computed(() => {
  const payload = props.review.model_selection_review;
  const observation = payload?.observed_stage_union;
  const selectedCodes = observation?.selected_codes;
  const hitCodes = observation?.hit_codes;
  const stageIds = observation?.stage_ids;
  const validStageIds = Array.isArray(stageIds)
    && stageIds.every((stage) => typeof stage === "string" && stage.trim() !== "")
    && new Set(stageIds).size === stageIds.length;
  const expectedStageCount = observation?.expected_stage_count;
  const expectedStageCountIsValid = typeof expectedStageCount === "number"
    && Number.isInteger(expectedStageCount)
    && expectedStageCount >= 0;
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
    selectedCount: observation.selected_count,
    hitCount: observation.hit_count,
    stageRows: payload?.row_counts?.stage_rows,
    stageCoverage: validStageIds && expectedStageCountIsValid
      ? `${stageIds?.length ?? "缺证"}/${expectedStageCount} 阶段有观察行`
      : "阶段覆盖元数据缺证",
    cannotConfirm: observation.cannot_confirm ?? [],
  };
});

const stageEvidenceRows = computed(() => {
  const payload = props.review.model_selection_review;
  const labels: Record<string, string> = {
    STAGE_0925: "09:20 竞价二筛", STAGE_0930_0935: "09:30–09:35",
    STAGE_0935_0940: "09:35–09:40", STAGE_0940_0945: "09:40–09:45",
    STAGE_0945_1030: "09:45–10:30", STAGE_1300_1315: "13:00–13:15",
    STAGE_1445_1500: "14:45–15:00",
  };
  const reasons: Record<string, string> = {
    FUTU_AFTERFACT_CAPTURE_NOT_PIT_SAFE: "分钟数据为事后补采，不能证明当时已获得",
    HK_HISTORICAL_ORDERBOOK_UNAVAILABLE: "没有留存该时段盘口",
    HK_ACTIVE_SNAPSHOT_UNAVAILABLE: "没有可用的该时段活跃股快照",
    FUTU_CAPTURE_TIME_NOT_PERSISTED: "原始采集时间未留存",
    HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE: "快照含阶段截止之后的行情，不能用于当时选股",
  };
  return Object.entries(payload?.stage_input_evidence ?? {}).map(([id, evidence]) => {
    const markers = Array.isArray(evidence.source_evidence) ? evidence.source_evidence.filter((v): v is string => typeof v === "string") : [];
    const gaps = Array.isArray(evidence.cannot_confirm) ? evidence.cannot_confirm.filter((v): v is string => typeof v === "string") : [];
    const corrected = evidence.input_count_correction === "SECOND_FILTER_TOP20_NOT_D1_TOP100";
    const ready = payload?.stages?.[id]?.evidence_status === "READY";
    const captured = markers.find((v) => v.startsWith("futu_captured_at="))?.split("=")[1];
    const count = (value: unknown) => typeof value === "number" ? value : "未记录";
    return {
      id, label: labels[id] ?? id, ready, rows: count(evidence.row_count),
      input: `${count(corrected ? evidence.review_source_rows : evidence.source_rows)}/${count(corrected ? evidence.review_expected_rows : evidence.requested_rows)}`,
      reason: corrected ? "已核对完整二筛20行，原先误用Top100作分母；原阶段记录保留"
        : gaps.length ? gaps.map((gap) => reasons[gap] ?? gap).join("；")
        : ready ? "已有阶段依据完整" : "输入覆盖或阶段状态未确认",
      captured,
    };
  });
});

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
    <p v-if="review.model_selection_review?.status === 'NON_TRADING_DAY'" class="review-pending" data-testid="hk-close-calendar-skip">
      港股市场当日休市，没有正式收盘 Top20；收盘命中统计不适用。
    </p>
    <p v-else-if="!hasReviewEvidence" class="review-pending">HK 收盘证据未物化；不把缺失显示为 0 命中。</p>
    <div v-if="hasReviewEvidence" class="review-metric-grid">
      <article v-if="observedModel" data-testid="hk-observed-model">
        <span>研究观察 0.2（非正式）</span><strong>{{ hitTop20(observedModel.hitCount) }}</strong>
        <small>观察候选 {{ observedModel.selectedCount }}/{{ observedModel.expectedCount ?? "不可用" }} 行 · PIT未验证 · NO_BUY</small>
      </article>
      <article v-else-if="formalModelFallback" data-testid="hk-formal-model-fallback">
        <span>0.2候选数据（来自现有正式指标）</span><strong>{{ hitTop20(formalModelFallback.hitCount) }}</strong>
        <small>正式候选 {{ formalModelFallback.selectedCount }} 行；研究观察字段 CANNOT_CONFIRM · PIT未验证 · NO_BUY</small>
      </article>
      <article v-else data-testid="hk-observed-model-unavailable">
        <span>研究观察 0.2</span><strong>不可用</strong><small>没有可验证的正式候选指标或研究观察行</small>
      </article>
      <article><span>七阶段并集</span><strong>{{ hitTop20(review.model_selection_review?.stage_union?.hit_count) }}</strong><small>入选 {{ review.model_selection_review?.stage_union?.selected_count ?? "不可用" }}</small></article>
      <article v-if="observedStageUnion" data-testid="hk-observed-stage-union">
        <span>研究阶段并集（部分观察）</span><strong>{{ hitTop20(observedStageUnion.hitCount) }}</strong>
        <small>{{ observedStageUnion.stageRows ?? "缺证" }} 行 / {{ observedStageUnion.selectedCount }} 个去重代码 · {{ observedStageUnion.stageCoverage }} · PIT未验证 · NO_BUY</small>
      </article>
      <article><span>收盘 Top20</span><strong>{{ review.model_selection_review?.row_counts?.close_top20 ?? review.model_selection_review?.close_top20?.length ?? "不可用" }}</strong><small>精确日期真实收盘标签</small></article>
      <article><span>阶段证据行</span><strong>{{ review.model_selection_review?.row_counts?.stage_rows ?? "不可用" }}</strong><small>仅同日，不跨日回填</small></article>
    </div>
    <p v-if="observedStageUnion" class="review-pending" data-testid="hk-observed-stage-boundary">
      观察并集的数字来自已有同日阶段行；阶段覆盖或PIT缺证不升格为正式七阶段并集。
    </p>
    <section v-if="stageEvidenceRows.length" aria-label="七阶段证据明细" data-testid="hk-stage-evidence">
      <h3>七阶段证据明细</h3>
      <p>复盘依据已核对 {{ stageEvidenceRows.filter((row) => row.ready).length }}/{{ stageEvidenceRows.length }} 个阶段；有观察股票不代表当时的证据齐全。</p>
      <div class="review-table-wrap"><table>
        <thead><tr><th>阶段</th><th>输入行</th><th>展示行</th><th>依据与缺口</th></tr></thead>
        <tbody><tr v-for="row in stageEvidenceRows" :key="row.id">
          <td>{{ row.label }}</td><td>{{ row.input }}</td><td>{{ row.rows }}</td>
          <td>{{ row.reason }}<small v-if="row.captured"> · 采集于 {{ row.captured }}</small></td>
        </tr></tbody>
      </table></div>
    </section>
    <details v-if="review.model_selection_review?.cannot_confirm?.length"><summary>原始缺口代码</summary>
      <p v-for="item in review.model_selection_review?.cannot_confirm ?? []" :key="item">{{ item }}</p>
    </details>
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
