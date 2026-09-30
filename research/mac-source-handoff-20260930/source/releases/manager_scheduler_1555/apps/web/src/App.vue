<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from "vue";

import TaskStatusView from "./views/TaskStatusView.vue";
import ReviewView from "./views/ReviewView.vue";
import ResearchView from "./views/ResearchView.vue";
import { loadReview } from "./api/review";
import type { ReviewEnvelope } from "./contracts/review";
import { UNKNOWN_STOCK_NAME } from "./composables/useResearchLane";
import { loadTaskStatus } from "./api/runtime";
import type { TimelineNodeStatus } from "./contracts/runtime";

type StageDefinition = { id: string; label: string; timeline: string };
const stageDefinitions: StageDefinition[] = [
  { id: "STAGE_0925", label: "港股通09:20 / A股09:25竞价选股", timeline: "1. 港股通09:20 / A股09:25竞价选股" },
  { id: "STAGE_0930_0935", label: "09:30-09:35", timeline: "2. 09:30-09:35" },
  { id: "STAGE_0935_0940", label: "09:35-09:40", timeline: "3. 09:35-09:40" },
  { id: "STAGE_0940_0945", label: "09:40-09:45", timeline: "4. 09:40-09:45" },
  { id: "STAGE_0945_1030", label: "09:45-10:30", timeline: "5. 09:45-10:30" },
  { id: "STAGE_1300_1315", label: "13:00-13:15", timeline: "6. 13:00-13:15" },
  { id: "STAGE_1445_1500", label: "14:45-15:00", timeline: "7. 14:45-15:00" },
  { id: "STAGE_1545_1555", label: "15:45-15:55港股", timeline: "8. 15:45-15:55港股" },
];
type ClosingTimelineNode = { position: number; node_id: string; planned_slot: string; label: string };
// The graph generator consumes this stable string timeline.  The render path
// below uses the richer node records, so the parser-facing contract does not
// discard the active page metadata.
const closingTimeline = [
  "9. 16:08 港股通正式收盘：0.2 × 七阶段 Top20",
  "10. 15:00 收盘前总结材料",
  "11. 15:55 收盘后复盘启动",
  "12. 16:05 A股收盘数据与题材骨架",
  "13. 20:30 最新复盘视频检查",
  "14. 20:40 视频下载与转写",
  "15. 20:50 股票字典校正",
  "16. 21:05 视频表格OCR/ASR/新闻对齐",
  "17. 21:08 页面复盘对视频差距",
  "18. 21:10 第三版复盘发布",
  "19. 21:15 8871 刷新与页面验收",
] as const;
const closingTimelineNodes: ClosingTimelineNode[] = [
  { position: 9, node_id: "hkconnect_model_selection_review", planned_slot: "1608", label: "9. 16:08 港股通正式收盘：0.2 × 七阶段 Top20" },
  { position: 10, node_id: "FUPAN_CLOSE_MATERIALS", planned_slot: "1500", label: "10. 15:00 收盘前总结材料" },
  { position: 11, node_id: "FUPAN_REVIEW_START", planned_slot: "1555", label: "11. 15:55 收盘后复盘启动" },
  { position: 12, node_id: "FUPAN_A_SHARE_STRUCTURE", planned_slot: "1605", label: "12. 16:05 A股收盘数据与题材骨架" },
  { position: 13, node_id: "FUPAN_VIDEO_CHECK", planned_slot: "2030", label: "13. 20:30 最新复盘视频检查" },
  { position: 14, node_id: "FUPAN_VIDEO_DOWNLOAD_ASR", planned_slot: "2040", label: "14. 20:40 视频下载与转写" },
  { position: 15, node_id: "FUPAN_STOCKDICT", planned_slot: "2050", label: "15. 20:50 股票字典校正" },
  { position: 16, node_id: "FUPAN_VIDEO_TABLE_OCR_ALIGN", planned_slot: "2105", label: "16. 21:05 视频表格OCR/ASR/新闻对齐" },
  { position: 17, node_id: "FUPAN_VIDEO_GAP", planned_slot: "2108", label: "17. 21:08 页面复盘对视频差距" },
  { position: 18, node_id: "FUPAN_V3_PUBLISH", planned_slot: "2110", label: "18. 21:10 第三版复盘发布" },
  { position: 19, node_id: "FUPAN_8771_VERIFY", planned_slot: "2115", label: "19. 21:15 8871 刷新与页面验收" },
];

type DateResponse = {
  default_date: string; system_date?: string; stage_dates: string[]; review_dates?: string[]; research_dates?: string[]; future_target_dates: string[];
};
type PoolRow = {
  market?: string; symbol?: string; code?: string; stock_name?: string; name?: string; display_name?: string; pool_rank?: number;
  pool_score?: number; signal_date?: string; source_date?: string; article_publish_date?: string;
  publish_date?: string; effective_trade_date?: string; target_date?: string; trade_date?: string;
  source_tag?: string; source_label?: string; source_tags?: string | string[]; source_lanes?: string | string[];
  source_trace?: string | string[]; pool_id?: string;
};
type PoolGroup = {
  pool_id: string; display_name?: string; market?: string; pool_size?: number; returned_rows?: number; rows?: PoolRow[];
  status?: string; recommendation_status?: string; producer_id?: string; source_path?: string;
  cannot_confirm?: Array<string | { reason?: string; description?: string }>;
};
type PoolResponse = {
  data_status: string; rows: PoolRow[]; a_all_pool_rows?: PoolRow[];
  trade_date?: string; date?: string; target_date?: string;
  pools?: PoolGroup[]; market_totals?: { A?: number; HK?: number };
  hk_pool_version?: string; hk_pool_role?: string; blocking_reasons: string[];
};
type StageRow = {
  market?: string; code?: string; symbol?: string; stock_code?: string; name?: string; stock_name?: string;
  rank?: number | string; stage_rank?: number | string; pool_rank?: number | string;
  score?: number; stage_score?: number; stage_rtdata_score?: number;
  d1_change_pct?: number; stage_display_decision?: string; next_validation_time?: string;
  status?: string; source_mode?: string; stage_id?: string; trade_date?: string;
  latest_research_slot?: string; news_quality_score?: number; research_quality_score?: number;
  news_research_reason?: string; source_health?: string;
  cannot_confirm?: string[]; data_level?: string; recommendation_status?: string;
  support_primary_price?: number | string; pressure_price?: number | string;
  invalidation_price?: number | string;
  current_change_pct?: number;
  auction_ref_gap_pct?: number | null;
  first_to_last_ref_pct?: number | null;
  reference_price_hkd?: number | null;
  open_price?: number; last_price?: number; high_price?: number; low_price?: number;
  source_last_bar_time?: string;
};
type MarketSummary = {
  label?: string; candidate_count?: number; source_rows?: number;
  requested_rows?: number; source_status?: string; data_level?: string;
};
type OpeningSecondFilterMarket = {
  refresh_time?: string; strategy?: string; row_count?: number;
};
type OpeningSecondFilter = {
  model_id?: string; model_version?: string; champion_contract?: string;
  markets?: { A?: OpeningSecondFilterMarket; HK?: OpeningSecondFilterMarket };
};
type StageWorkbench = {
  ok?: boolean; trade_date?: string;
  stage: { stage_id: string; label?: string; window?: string; status: string; display_status: string };
  markets?: { A?: MarketSummary; HK?: MarketSummary };
  unified_rows: StageRow[];
  selected_a_rows: number; selected_hk_rows: number; selected_total_rows: number;
  selection_mode: string; response_source?: string; reference_snapshot?: boolean;
  opening_second_filter?: OpeningSecondFilter;
};
type StageTimelineSnapshot = {
  date: string;
  loading: boolean;
  payload?: StageWorkbench;
  error?: string;
};
type ReviewMetric = {
  evidence_status?: string; selected_count?: number | null; hit_count?: number | null;
  coverage_pct?: number | null; precision_pct?: number | null;
};
type ReviewAttributionRow = {
  rank?: number; code?: string; name?: string; pct_chg_close?: number;
  model_0_2_hit?: boolean; stage_union_hit?: boolean; classification?: string;
};
type ModelSelectionReview = {
  schema_version?: string; evidence_mode?: string; reference_snapshot?: boolean; close_source_sha256?: string;
  status?: string; trade_date?: string; primary_kpi?: string;
  models?: Record<string, ReviewMetric>; stages?: Record<string, ReviewMetric>;
  stage_union?: ReviewMetric; row_counts?: Record<string, number>;
  top20_attribution?: ReviewAttributionRow[]; close_top20?: ReviewAttributionRow[];
  missing_stages?: string[]; cannot_confirm?: string[];
  production_allowed?: boolean; buy_gate_updated?: boolean; orders_sent?: boolean;
};
type ReviewResponse = {
  trade_date?: string; reference_snapshot?: boolean;
  schema_version?: string;
  market_reviews?: { HK?: { model_selection_review?: ModelSelectionReview } };
};

const selectedDate = ref("");
const dateData = ref<DateResponse>({ default_date: "", stage_dates: [], future_target_dates: [] });
const pool = ref<PoolResponse | null>(null);
const loading = ref(false);
const loadError = ref("");
let requestVersion = 0;
const selectedStage = ref(stageDefinitions[0].id);
const stageWorkbench = ref<StageWorkbench | null>(null);
const stageLoading = ref(false);
const stageError = ref("");
const stageSnapshots = ref<Record<string, StageTimelineSnapshot>>({});
const stageRunStatus = ref("");
const navigationStatus = ref("");
const taskStatusActive = ref(false);
const researchActive = ref(false);
const closeReviewActive = ref(false);
const closeReviewLoading = ref(false);
const closeReviewError = ref("");
const closeReviewPayload = ref<ReviewEnvelope | null>(null);
const closeReviewPanel = ref<HTMLElement | null>(null);
const timelineStatus = ref<Record<number, TimelineNodeStatus>>({});
let closeReviewRequestVersion = 0;
let stageRequestVersion = 0;
let stageTimelineRequestVersion = 0;
let timelineStatusRequestVersion = 0;

const dateOptions = computed(() =>
  [...new Set([
    ...dateData.value.future_target_dates,
    ...dateData.value.stage_dates,
    ...(dateData.value.review_dates ?? []),
    ...(dateData.value.research_dates ?? []),
  ])].sort(),
);
const dateInputMin = computed(() => formatDateInput(dateOptions.value[0] ?? ""));
const dateInputMax = computed(() => formatDateInput(dateOptions.value.at(-1) ?? ""));
const dateInputTitle = computed(() =>
  dateData.value.future_target_dates.includes(selectedDate.value)
    ? "次日选股池准备（未开盘）"
    : "选择交易日",
);
const currentStageDefinition = computed(() =>
  stageDefinitions.find((stage) => stage.id === selectedStage.value) ?? stageDefinitions[0],
);
const isPreopenStage = computed(() => selectedStage.value === "STAGE_0925");
const aRows = computed(() =>
  (stageWorkbench.value?.unified_rows?.filter((row) => row.market === "A") ?? []).slice(0, 12),
);
const hkRows = computed(() => stageWorkbench.value?.unified_rows?.filter((row) => row.market === "HK") ?? []);
const aPoolRows = computed(() =>
  pool.value?.a_all_pool_rows ?? pool.value?.rows?.filter((row) => row.market === "A") ?? [],
);
const hkPoolRows = computed(() =>
  pool.value?.rows?.filter((row) => row.market === "HK") ?? [],
);
const aPoolPreview = computed(() => aPoolRows.value.slice(0, 20));
const hkPoolPreview = computed(() => hkPoolRows.value.slice(0, 20));
const aPoolTotal = computed(() => pool.value?.market_totals?.A ?? aPoolRows.value.length);
const hkPoolTotal = computed(() => pool.value?.market_totals?.HK ?? hkPoolRows.value.length);
const aSourcePoolCount = computed(() =>
  pool.value?.pools?.filter((group) =>
    group.market === "A" || group.pool_id.startsWith("a_"),
  ).length ?? 0,
);
const independentPools = computed(() => pool.value?.pools ?? []);
const collapsedPools = ref<Record<string, boolean>>({});
const preselectionGroups = computed(() => {
  const byId = new Map(independentPools.value.map((group) => [group.pool_id, group]));
  const group = (poolId: string, domId: string, title?: string) => ({
    ...(byId.get(poolId) ?? { pool_id: poolId, rows: [], status: "CANNOT_CONFIRM" }),
    domId,
    display_name: title ?? byId.get(poolId)?.display_name ?? poolId,
  });
  return [
    {
      pool_id: "a_all_pool_summary",
      domId: "aPreselectGroup",
      display_name: "A股所有预选池汇总",
      market: "A",
      status: pool.value?.data_status,
      pool_size: pool.value?.market_totals?.A ?? pool.value?.a_all_pool_rows?.length ?? 0,
      returned_rows: pool.value?.a_all_pool_rows?.length ?? 0,
      rows: pool.value?.a_all_pool_rows ?? [],
    },
    group("hkconnect_d1_top100", "hkPreselectGroup", "港股通 D-1 预选池"),
    group("wechat_public_account_v3_preselect", "wechatPreselectGroup", "公众号股票池"),
    group("a_d1_premarket_pool", "selectorPreselectGroup", "A股 D-1 主预选池"),
    group("a_d1_stage7_fenshi_review_pool", "fenshiPreselectGroup", "A股 D-1 Stage7/分时复盘池"),
    group("a_d1_fupan_watchlist_pool", "fupanPreselectGroup", "A股 D-1 复盘继续观察池"),
    group("a_share_baimao_research_map", "baimaoPreselectGroup", "白毛卡点研究池"),
    group("a_share_research_recommendation_pool", "researchPreselectGroup", "A股研究推荐池"),
  ];
});
function togglePool(poolId: string) {
  collapsedPools.value = { ...collapsedPools.value, [poolId]: !collapsedPools.value[poolId] };
}
function poolRows(group: PoolGroup) {
  return group.rows ?? [];
}
function poolEvidenceReason(group: PoolGroup) {
  const item = group.cannot_confirm?.[0];
  if (typeof item === "string") return item;
  return item?.reason || item?.description || "";
}
function poolRowCode(row: PoolRow) {
  return row.symbol || row.code || "WATCH_ONLY";
}
function poolRowName(row: PoolRow) {
  const code = poolRowCode(row);
  return [row.display_name, row.stock_name, row.name]
    .map((value) => value?.trim() || "")
    .find((value) => value && value !== code) || UNKNOWN_STOCK_NAME;
}
function poolMetadataText(value?: string | string[]) {
  return Array.isArray(value) ? value.filter(Boolean).join(" / ") : value || "";
}
function poolRowSource(row: PoolRow, group: PoolGroup) {
  return poolMetadataText(row.source_tags)
    || row.source_label
    || row.source_tag
    || poolMetadataText(row.source_lanes)
    || group.producer_id
    || group.status
    || "来源状态未提供";
}
function poolRowSourceLane(row: PoolRow) {
  return poolMetadataText(row.source_lanes);
}
function poolCountLabel(group: PoolGroup) {
  const total = group.pool_size ?? group.rows?.length ?? 0;
  const returned = group.returned_rows
    ?? (group.pool_id === "a_all_pool_summary" ? group.rows?.length ?? 0 : total);
  return returned < total ? `当前显示 ${returned} / 共 ${total} 条` : `完整 ${total} 条`;
}
function poolRowSignalDate(row: PoolRow) {
  return row.signal_date
    || row.source_date
    || row.article_publish_date
    || row.publish_date
    || row.effective_trade_date
    || row.target_date
    || row.trade_date
    || "该池未提供信号日";
}
const referenceMode = computed(() =>
  stageWorkbench.value?.selection_mode === "MIGRATED_REFERENCE_WORKBENCH",
);
const v11OpeningFilter = computed(() =>
  isPreopenStage.value
  && stageWorkbench.value?.selection_mode === "V1_1_CHAMPION_DUAL_MARKET"
    ? stageWorkbench.value.opening_second_filter
    : undefined,
);
const phaseStatus = computed(() => {
  if (referenceMode.value) return "参考快照";
  if (stageWorkbench.value?.selected_total_rows) return "观察材料已生成";
  return "数据待补齐";
});
const aSummary = computed(() => stageWorkbench.value?.markets?.A ?? {});
const hkSummary = computed(() => stageWorkbench.value?.markets?.HK ?? {});
const showAStageEvidenceGap = computed(() =>
  (aSummary.value.requested_rows ?? 0) > 0
  && aSummary.value.source_rows === 0
  && aSummary.value.candidate_count === 0
  && stageWorkbench.value?.selected_a_rows === 0,
);
const closeReview = computed(() =>
  (closeReviewPayload.value?.market_reviews.HK.model_selection_review ?? {}) as ModelSelectionReview,
);
const closeReviewHasValidSnapshot = computed(() => {
  const payload = closeReviewPayload.value;
  if (!payload || payload.trade_date !== selectedDate.value) return false;
  const model = payload.market_reviews?.HK?.model_selection_review;
  if (!Array.isArray(model?.close_top20) || model.close_top20.length === 0) return false;
  if (payload.reference_snapshot === true || model.reference_snapshot === true) return true;
  return payload.schema_version === "v3_5.review_envelope.v1"
    && payload.reference_snapshot === false
    && model.schema_version === "v3_5.close_review.v1"
    && model.evidence_mode === "V3_5_NATIVE_PRODUCTION"
    && model.reference_snapshot === false
    && typeof model.close_source_sha256 === "string"
    && /^[0-9a-f]{64}$/.test(model.close_source_sha256);
});
const stage7Explanation = computed(() => {
  if (selectedStage.value !== "STAGE_1445_1500" || !stageWorkbench.value) return "";
  const requested = hkSummary.value.requested_rows ?? hkSummary.value.source_rows ?? 0;
  const source = hkSummary.value.source_rows ?? 0;
  const actual = stageWorkbench.value.selected_hk_rows ?? 0;
  const status = stageWorkbench.value.stage.status || stageWorkbench.value.stage.display_status || "CANNOT_CONFIRM";
  return `最多10 / 实际${actual} · 请求${requested} / 可确认行${source} / 阶段候选${hkSummary.value.candidate_count ?? 0} · ${status}`;
});
const modelMetric = computed(() => closeReview.value.models?.["0.2_prob_active"] ?? {});
const stageUnionMetric = computed(() => closeReview.value.stage_union ?? {});
const closeReviewEvidenceLabel = computed(() => {
  if (closeReview.value.evidence_mode === "V3_5_NATIVE_PRODUCTION") return "V3.5 原生收盘证据";
  return "收盘证据未导入";
});
const reviewEvidenceGaps = computed(() =>
  [...new Set([...(closeReview.value.missing_stages ?? []), ...(closeReview.value.cannot_confirm ?? [])])],
);

function formatPercent(value?: number) {
  return typeof value === "number" ? `${value.toFixed(3).replace(/\.?0+$/, "")}%` : "阶段行情未生成";
}

function assertExactResponseDate(
  payload: unknown,
  requestedDate: string,
  fields: readonly string[],
  label: string,
) {
  if (!payload || typeof payload !== "object") {
    throw new Error(`${label}日期证据错误：响应不是对象，未展示该响应。`);
  }
  const record = payload as Record<string, unknown>;
  const presentFields = fields.filter((field) => Object.prototype.hasOwnProperty.call(record, field));
  if (!presentFields.length) {
    throw new Error(`${label}日期证据错误：响应缺少 ${fields.join("/")}，未展示该响应。`);
  }
  const mismatch = presentFields.find((field) => record[field] !== requestedDate);
  if (mismatch) {
    throw new Error(`${label}日期证据错误：响应 ${mismatch}=${String(record[mismatch])}，请求=${requestedDate}，未展示该响应。`);
  }
}

function formatDateInput(value: string) {
  return /^\d{8}$/.test(value)
    ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`
    : "";
}
function compactDateInput(value: string) {
  return value.replaceAll("-", "");
}
function evidenceValue(value?: number | string) {
  return value === undefined || value === null || value === "" ? "该字段未在当前阶段生成" : value;
}
function rowCode(row: StageRow) {
  return row.code || row.symbol || row.stock_code || "WATCH_ONLY";
}
function rowName(row: StageRow) {
  const code = rowCode(row);
  return [row.name, row.stock_name]
    .map((value) => value?.trim() || "")
    .find((value) => value && value !== code) || UNKNOWN_STOCK_NAME;
}
function rowRank(row: StageRow) {
  return row.rank ?? row.stage_rank ?? row.pool_rank ?? "-";
}
function aShareChangePct(row: StageRow) {
  if (typeof row.current_change_pct === "number") return row.current_change_pct;
  if (typeof row.d1_change_pct === "number") return row.d1_change_pct;
  if (
    typeof row.open_price === "number"
    && row.open_price !== 0
    && typeof row.last_price === "number"
  ) {
    return (row.last_price / row.open_price - 1) * 100;
  }
  return undefined;
}
function rowSupport(row: StageRow) {
  return row.support_primary_price ?? row.low_price;
}
function rowPressure(row: StageRow) {
  return row.pressure_price ?? row.high_price;
}
function rowInvalidation(row: StageRow) {
  return row.invalidation_price ?? row.low_price;
}
function rowNextEvidence(row: StageRow) {
  return row.next_validation_time || row.source_last_bar_time || "";
}
function rowScore(row: StageRow) {
  const value = row.score ?? row.stage_score ?? row.stage_rtdata_score;
  return typeof value === "number" ? Number(value.toFixed(3)) : value ?? "阶段分未在当前阶段生成";
}
function qualityScore(value?: number) {
  return typeof value === "number" ? Number(value.toFixed(3)) : "该时段未提供";
}
function is0920D1ReferenceRow(row: StageRow) {
  return row.source_mode === "HK_CONNECT_D1_PRESELECT_REFERENCE"
    && row.status === "WAITING_0920_SECOND_FILTER";
}
function is0920AuctionQuoteRow(row: StageRow) {
  return isPreopenStage.value
    && !is0920D1ReferenceRow(row)
    && row.source_mode === "HK_CONNECT_AUCTION_SECOND_FILTER_STAGE_0925";
}
function hkChangeLabel(row: StageRow) {
  if (is0920AuctionQuoteRow(row)) return "参考价阶段变化";
  return typeof row.d1_change_pct === "number" ? "D-1涨幅" : "阶段涨幅";
}
function hkChangeValue(row: StageRow) {
  if (isPreopenStage.value && is0920D1ReferenceRow(row)) return "D-1参考，待09:20二筛";
  if (is0920AuctionQuoteRow(row)) return formatPercent(row.first_to_last_ref_pct ?? undefined);
  return formatPercent(row.d1_change_pct ?? row.current_change_pct);
}
function hkScoreLabel(row: StageRow) {
  return isPreopenStage.value && is0920D1ReferenceRow(row) ? "D-1参考分" : "二筛分";
}
function rowMissingFields(row: StageRow) {
  const missing: string[] = [];
  if (typeof row.d1_change_pct !== "number" && typeof row.current_change_pct !== "number") missing.push("涨幅");
  if (row.score == null && row.stage_score == null && row.stage_rtdata_score == null) missing.push("二筛分");
  if (row.support_primary_price == null || row.support_primary_price === "") missing.push("支撑位");
  if (row.pressure_price == null || row.pressure_price === "") missing.push("压力位");
  if (row.invalidation_price == null || row.invalidation_price === "") missing.push("失效位");
  if (!row.next_validation_time) missing.push("下次验证");
  return missing;
}
function hitTop20(metric: ReviewMetric) {
  return typeof metric.hit_count === "number" ? `${metric.hit_count}/20` : "不可用";
}
function reviewClassification(value?: string) {
  return ({
    shared: "共同命中",
    model_only: "仅0.2",
    stage_only: "仅阶段",
    missed: "漏掉Top20",
  } as Record<string, string>)[value || ""] || value || "不可确认";
}
function showNavigationStatus(label: string) {
  taskStatusActive.value = false;
  researchActive.value = false;
  navigationStatus.value = `${label} · 状态以任务 receipt 为准。`;
}
function timelineNodeStatus(node: ClosingTimelineNode): TimelineNodeStatus {
  return timelineStatus.value[node.position] ?? {
    position: node.position,
    node_id: node.node_id,
    label: node.label,
    planned_slot: node.planned_slot,
    owner_id: "CANNOT_CONFIRM",
    status: "CANNOT_CONFIRM",
    reason: "TASK_STATUS_NOT_LOADED",
    result_code: "TASK_STATUS_NOT_LOADED",
    production_allowed: false,
    buy_gate_updated: false,
    orders_sent: false,
  };
}
function timelineStatusText(node: ClosingTimelineNode) {
  const row = timelineNodeStatus(node);
  return row.reason ? `${row.status} · ${row.reason}` : row.status;
}
async function loadTimelineStatus(date = selectedDate.value) {
  if (!date) return;
  const version = ++timelineStatusRequestVersion;
  try {
    const payload = await loadTaskStatus(date);
    if (version !== timelineStatusRequestVersion || date !== selectedDate.value) return;
    timelineStatus.value = Object.fromEntries(
      (payload.timeline_nodes ?? []).map((row) => [row.position, row]),
    );
  } catch {
    if (version === timelineStatusRequestVersion && date === selectedDate.value) timelineStatus.value = {};
  }
}
function openTaskStatus() {
  taskStatusActive.value = true;
  researchActive.value = false;
  closeReviewActive.value = false;
  navigationStatus.value = "";
}
function openResearch() {
  taskStatusActive.value = false;
  closeReviewActive.value = false;
  researchActive.value = true;
  navigationStatus.value = "";
}

async function focusCloseReviewTop() {
  await nextTick();
  const panel = document.getElementById("hkCloseReviewPanel") ?? closeReviewPanel.value;
  if (!panel) return;
  panel.scrollIntoView?.({ behavior: "smooth", block: "start" });
  panel.focus?.({ preventScroll: true });
}
function scrollToPool() {
  taskStatusActive.value = false;
  researchActive.value = false;
  document.querySelector("#unifiedPreselectPanel")?.scrollIntoView({ behavior: "smooth" });
}

async function loadPool(date = selectedDate.value) {
  if (!date) return;
  const version = ++requestVersion;
  const requestedDate = date;
  loading.value = true;
  pool.value = null;
  loadError.value = "";
  try {
    const response = await fetch(`/api/v3/preselection-pools?date=${encodeURIComponent(requestedDate)}&limit=200`);
    if (!response.ok) throw new Error("request failed");
    const payload = await response.json();
    assertExactResponseDate(payload, requestedDate, ["trade_date", "date", "target_date"], "D-1 预选池");
    if (version === requestVersion && requestedDate === selectedDate.value) pool.value = payload;
  } catch (reason) {
    if (version === requestVersion && requestedDate === selectedDate.value) {
      loadError.value = reason instanceof Error ? reason.message : "D-1 预选池读取失败，请重新选择交易日。";
    }
  } finally {
    if (version === requestVersion && requestedDate === selectedDate.value) loading.value = false;
  }
}

function setStageTimelineSnapshot(stageId: string, snapshot: StageTimelineSnapshot) {
  if (snapshot.date !== selectedDate.value) return;
  stageSnapshots.value = { ...stageSnapshots.value, [stageId]: snapshot };
}

function timelineStageSnapshot(stageId: string) {
  const snapshot = stageSnapshots.value[stageId];
  return snapshot?.date === selectedDate.value ? snapshot : undefined;
}

function timelineStageStatus(stageId: string) {
  const stagePosition = stageDefinitions.findIndex((stage) => stage.id === stageId) + 1;
  const task = timelineStatus.value[stagePosition];
  // A scheduled stage that is explicitly not due must remain truthful even
  // when a reference/workbench snapshot is already readable.  Once its slot
  // is due, the stage snapshot remains the richer candidate evidence.
  if (task?.status === "PENDING_NOT_DUE" || task?.status === "NON_TRADING_DAY") {
    return task.reason ? `${task.status} · ${task.reason}` : task.status;
  }
  const snapshot = timelineStageSnapshot(stageId);
  if (!snapshot || snapshot.loading) return "读取中";
  if (snapshot.error || !snapshot.payload) return "读取失败/点击重试";
  return snapshot.payload.stage.status || snapshot.payload.stage.display_status || "CANNOT_CONFIRM";
}

function timelineStageCounts(stageId: string) {
  const snapshot = timelineStageSnapshot(stageId);
  if (!snapshot || snapshot.loading) return "读取中";
  if (snapshot.error || !snapshot.payload) return "读取失败/点击重试";
  return `A ${snapshot.payload.selected_a_rows ?? 0} / HK ${snapshot.payload.selected_hk_rows ?? 0}`;
}

function hasStageTimelineForDate(date: string) {
  return stageDefinitions.every((stage) => stageSnapshots.value[stage.id]?.date === date);
}

async function loadStageTimeline(date: string, currentStage: string, currentPayload: StageWorkbench | null) {
  if (!date || date !== selectedDate.value) return;
  const version = ++stageTimelineRequestVersion;
  const currentPayloadMatches = currentPayload?.trade_date === date
    && currentPayload.stage?.stage_id === currentStage;
  const initialSnapshots: Record<string, StageTimelineSnapshot> = {};
  for (const stage of stageDefinitions) {
    if (stage.id === currentStage && currentPayloadMatches) {
      initialSnapshots[stage.id] = { date, loading: false, payload: currentPayload };
    } else {
      initialSnapshots[stage.id] = { date, loading: true };
    }
  }
  stageSnapshots.value = initialSnapshots;

  const stagesToLoad = stageDefinitions.filter((stage) => !currentPayloadMatches || stage.id !== currentStage);
  await Promise.all(stagesToLoad.map(async (stage) => {
    try {
      const response = await fetch(
        `/api/v3/workbench/stage?date=${encodeURIComponent(date)}&stage=${encodeURIComponent(stage.id)}&limit=50`,
      );
      if (!response.ok) throw new Error("request failed");
      const payload = await response.json() as StageWorkbench;
      if (payload.trade_date && payload.trade_date !== date) throw new Error("date mismatch");
      if (version === stageTimelineRequestVersion && date === selectedDate.value) {
        setStageTimelineSnapshot(stage.id, { date, loading: false, payload });
      }
    } catch {
      if (version === stageTimelineRequestVersion && date === selectedDate.value) {
        setStageTimelineSnapshot(stage.id, { date, loading: false, error: "阶段工作台读取失败" });
      }
    }
  }));
}

async function loadStage(stage = selectedStage.value, preserveRunStatus = false) {
  taskStatusActive.value = false;
  researchActive.value = false;
  closeReviewActive.value = false;
  navigationStatus.value = "";
  selectedStage.value = stage;
  if (!preserveRunStatus) stageRunStatus.value = "";
  if (!selectedDate.value) {
    stageError.value = "请先选择交易日。";
    stageWorkbench.value = null;
    return;
  }
  const requestedDate = selectedDate.value;
  const version = ++stageRequestVersion;
  stageLoading.value = true;
  stageError.value = "";
  stageWorkbench.value = null;
  setStageTimelineSnapshot(stage, { date: requestedDate, loading: true });
  try {
    const response = await fetch(
      `/api/v3/workbench/stage?date=${encodeURIComponent(requestedDate)}&stage=${encodeURIComponent(stage)}&limit=50`,
    );
    if (!response.ok) throw new Error("request failed");
    const payload = await response.json() as StageWorkbench;
    if (payload.trade_date && payload.trade_date !== requestedDate) throw new Error("date mismatch");
    if (version === stageRequestVersion && requestedDate === selectedDate.value) {
      stageWorkbench.value = payload;
      setStageTimelineSnapshot(stage, { date: requestedDate, loading: false, payload });
      if (!hasStageTimelineForDate(requestedDate)) void loadStageTimeline(requestedDate, stage, payload);
    }
  } catch {
    if (version === stageRequestVersion && requestedDate === selectedDate.value) {
      stageError.value = "阶段工作台读取失败。";
      setStageTimelineSnapshot(stage, { date: requestedDate, loading: false, error: stageError.value });
    }
  } finally {
    if (version === stageRequestVersion && requestedDate === selectedDate.value) stageLoading.value = false;
  }
}

async function loadCloseReview() {
  taskStatusActive.value = false;
  researchActive.value = false;
  if (!selectedDate.value) return;
  closeReviewActive.value = true;
  closeReviewLoading.value = true;
  closeReviewError.value = "";
  closeReviewPayload.value = null;
  navigationStatus.value = "";
  const version = ++closeReviewRequestVersion;
  const requestedDate = selectedDate.value;
  try {
    const payload = await loadReview(requestedDate);
    assertExactResponseDate(payload, requestedDate, ["trade_date"], "16:08 港股通收盘复盘");
    if (version === closeReviewRequestVersion && requestedDate === selectedDate.value) {
      closeReviewPayload.value = payload;
      closeReviewLoading.value = false;
      await focusCloseReviewTop();
    }
  } catch (reason) {
    if (version === closeReviewRequestVersion && requestedDate === selectedDate.value) {
      closeReviewError.value = reason instanceof Error ? reason.message : "16:08 港股通收盘复盘读取失败。";
    }
  } finally {
    if (version === closeReviewRequestVersion && requestedDate === selectedDate.value) closeReviewLoading.value = false;
  }
}

async function ensureStage(force = false) {
  if (!selectedDate.value) return;
  stageLoading.value = true;
  stageError.value = "";
  try {
    const query = new URLSearchParams({ date: selectedDate.value, stage: selectedStage.value });
    if (force) query.set("force", "true");
    const response = await fetch(`/api/v3/workbench/stage/ensure?${query.toString()}`, { method: "POST" });
    if (!response.ok) throw new Error("request failed");
    const payload = await response.json();
    stageRunStatus.value = payload.ensure_status || "CANNOT_CONFIRM";
    await loadStage(selectedStage.value, true);
  } catch {
    stageError.value = "阶段运行失败，请查看失败 receipt。";
    stageLoading.value = false;
  }
}

async function onDateChange() {
  const requestedDate = selectedDate.value;
  stageTimelineRequestVersion += 1;
  stageSnapshots.value = {};
  if (researchActive.value) {
    await loadTimelineStatus(requestedDate);
  } else if (closeReviewActive.value) {
    await Promise.all([loadPool(requestedDate), loadCloseReview(), loadTimelineStatus(requestedDate)]);
  } else {
    await Promise.all([loadPool(requestedDate), loadStage(), loadTimelineStatus(requestedDate)]);
  }
}

async function onDateInputChange(event: Event) {
  const input = event.currentTarget as HTMLInputElement;
  const compact = compactDateInput(input.value);
  if (!dateOptions.value.includes(compact)) {
    input.setCustomValidity("请选择日历中的有效交易日");
    input.value = formatDateInput(selectedDate.value);
    input.reportValidity();
    return;
  }
  input.setCustomValidity("");
  selectedDate.value = compact;
  syncSelectedDateQuery(compact);
  await onDateChange();
}

function syncSelectedDateQuery(date: string) {
  if (!date) return;
  const params = new URLSearchParams(window.location.search);
  params.set("date", date);
  const systemDate = dateData.value.system_date;
  if (systemDate) params.set("date_anchor", systemDate);
  window.history.replaceState(
    window.history.state,
    "",
    `${window.location.pathname}?${params.toString()}${window.location.hash}`,
  );
}

onMounted(async () => {
  try {
    const [dateList, laneDates] = await Promise.all([
      fetch("/api/v1/runs/date-list").then((r) => (r.ok ? r.json() : Promise.reject(new Error("request failed")))),
      fetch("/api/v3/research/dates")
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null),
    ]);
    dateData.value = {
      ...dateList,
      // Merge the V3 research-module dates so the date picker can switch to
      // any available research lane date even when the local stage calendar
      // only covers the current day (e.g. a fresh V3.5 data root).
      research_dates: [...new Set([...(dateList.research_dates ?? []), ...((laneDates?.research_dates as string[] | undefined) ?? [])])].sort(),
    };
    const params = new URLSearchParams(window.location.search);
    const requestedDate = params.get("date");
    const requestedStage = params.get("stage");
    const requestedView = params.get("view");
    if (requestedStage && stageDefinitions.some((stage) => stage.id === requestedStage)) {
      selectedStage.value = requestedStage;
    }
    // An explicit URL date is an addressable read-only slice.  Keep it even
    // when the catalog's default points at an older evidence date or the
    // target day only has a partial pool set; date_anchor is navigation
    // context and must not replace the requested date.
    const explicitDate = requestedDate && /^\d{8}$/.test(requestedDate) ? requestedDate : "";
    selectedDate.value = explicitDate || dateData.value.default_date || dateOptions.value[0] || "";
    if (!explicitDate) syncSelectedDateQuery(selectedDate.value);
    await Promise.all([loadPool(), loadStage(), loadTimelineStatus()]);
    if (requestedView === "research") {
      openResearch();
    } else if (requestedView === "review") {
      await loadCloseReview();
    }
  } catch {
    loadError.value = "交易日目录读取失败。";
    stageError.value = "交易日目录读取失败。";
  }
});
</script>

<template>
  <main class="dashboard-shell">
    <header class="page-header">
      <div>
        <h1>v3 阶段选股</h1>
        <p>阶段选股只读取同一 date + stage 的 A股与港股通阶段工作台；只读观察，不打开 BUY gate，不接交易接口，不生成 live order。</p>
      </div>
      <span class="runtime-badge">V3.5 · 8873 独立运行</span>
    </header>

    <section class="control-panel" aria-label="页面控制">
      <label>交易日
        <input
          type="date"
          aria-label="交易日（日历选择）"
          :value="formatDateInput(selectedDate)"
          :min="dateInputMin"
          :max="dateInputMax"
          :title="dateInputTitle"
          @change="onDateInputChange"
        />
      </label>
      <label>阶段
        <select v-model="selectedStage" aria-label="阶段" @change="loadStage()">
          <option v-for="stage in stageDefinitions" :key="stage.id" :value="stage.id">{{ stage.label }}</option>
        </select>
      </label>
      <button type="button" :disabled="stageLoading" @click="loadStage()">刷新快照</button>
      <span class="runtime-state">运行图：V3.5 独立重构 · 当前切片验收中</span>
    </section>

    <nav class="entry-nav" aria-label="功能入口">
      <button :class="{ active: !taskStatusActive && !researchActive && !closeReviewActive }" type="button" @click="loadStage()">阶段选股</button>
      <button type="button" @click="scrollToPool()">D-1 预选池</button>
      <button :class="{ active: researchActive }" type="button" @click="openResearch()">研报决策台</button>
      <button :class="{ active: taskStatusActive }" type="button" @click="openTaskStatus()">任务状态</button>
      <button :class="{ active: closeReviewActive }" type="button" @click="loadCloseReview()">A股复盘</button>
    </nav>
    <p v-if="navigationStatus" class="navigation-status" role="status">{{ navigationStatus }}</p>

    <TaskStatusView v-if="taskStatusActive" :date="selectedDate" />
    <ResearchView v-else-if="researchActive" :archive-date="selectedDate" />
    <template v-else>

    <section class="status-grid" aria-label="阶段摘要">
      <article><span>阶段状态</span><strong>{{ phaseStatus }}</strong><small>{{ selectedDate }} / {{ currentStageDefinition.label }} 阶段</small></article>
      <article><span>A股候选</span><strong>{{ stageWorkbench?.selected_a_rows ?? 0 }}</strong><small>source rows {{ aSummary.source_rows ?? 0 }}；candidate {{ aSummary.candidate_count ?? 0 }}</small></article>
      <article><span>港股通候选</span><strong>{{ stageWorkbench?.selected_hk_rows ?? 0 }}</strong><small>candidate {{ hkSummary.candidate_count ?? 0 }}；同阶段观察</small></article>
      <article><span>港股通源</span><strong>{{ referenceMode ? "本地参考快照" : "V3.5 原生输入" }}</strong><small>运行时不调用旧 V3 服务</small></article>
      <article><span>统一行数</span><strong>{{ stageWorkbench?.selected_total_rows ?? 0 }}</strong><small>A股与港股通同阶段合并展示</small></article>
      <article><span>数据级别</span><strong>{{ hkSummary.data_level || aSummary.data_level || "CANNOT_CONFIRM" }}</strong><small>阶段产物驱动，非交易接口</small></article>
      <article><span>执行边界</span><strong>只读</strong><small>不下单，不接 broker，不打开 BUY gate</small></article>
    </section>

    <section class="panel timeline-panel" aria-label="七阶段上下文">
      <div class="section-heading">
        <div><span class="eyebrow">阶段分组主视图</span><h2>七阶段上下文 v2</h2></div>
        <p>{{ selectedDate }} · {{ currentStageDefinition.label }} · A股 {{ stageWorkbench?.selected_a_rows ?? 0 }} / 港股 {{ stageWorkbench?.selected_hk_rows ?? 0 }}</p>
      </div>
      <div class="timeline-grid">
        <button
          v-for="stage in stageDefinitions" :key="stage.id" type="button"
          :class="{ current: !closeReviewActive && selectedStage === stage.id }" @click="loadStage(stage.id)"
        >
          <b>{{ stage.timeline }}</b>
          <span>{{ timelineStageStatus(stage.id) }}</span>
          <small>{{ timelineStageCounts(stage.id) }}</small>
        </button>
        <button
          v-for="node in closingTimelineNodes" :key="node.node_id" type="button"
          :class="{ current: node.position === 9 && closeReviewActive }"
          :aria-controls="node.position === 9 ? 'closeReviewPanel' : undefined"
          :aria-expanded="node.position === 9 ? closeReviewActive : undefined"
          @click="node.position === 9 ? loadCloseReview() : showNavigationStatus(`${node.label} · ${timelineStatusText(node)}`)"
        >
          <b>{{ node.label }}</b>
          <span>{{ node.position === 9 && closeReviewActive ? (closeReviewHasValidSnapshot ? "已加载指定日期复盘" : "复盘证据未完成") : timelineStatusText(node) }}</span>
          <small>{{ node.position === 9 ? (closeReviewActive ? `${selectedDate} · 只读` : "点击加载只读收盘复盘") : `${node.planned_slot} 计划 · receipt 状态` }}</small>
        </button>
      </div>
    </section>

    <section v-if="!closeReviewActive" class="panel stage-panel">
      <div class="section-heading">
        <div><span class="eyebrow">当前阶段</span><h2>{{ currentStageDefinition.label }} 阶段</h2></div>
        <p v-if="stageWorkbench">{{ stageWorkbench.stage.status }} · {{ stageWorkbench.stage.window || currentStageDefinition.label }}</p>
      </div>
      <div class="stage-actions">
        <button type="button" :disabled="stageLoading || !selectedDate" @click="ensureStage(false)">运行 / 恢复当前阶段</button>
        <button type="button" :disabled="stageLoading || !selectedDate" @click="ensureStage(true)">强制重新物化</button>
        <span v-if="referenceMode" class="reference-label">参考快照 · WATCH_ONLY</span>
        <span v-if="stageRunStatus">最近运行：{{ stageRunStatus }}</span>
      </div>
      <div v-if="v11OpeningFilter" class="model-contract" aria-label="竞价二筛模型">
        <strong>v1.1 竞价二筛</strong>
        <span>v1.1 A股适配器，不是港股精确公式</span>
        <code>{{ v11OpeningFilter.model_id }}</code>
        <small>
          <span>港股 {{ v11OpeningFilter.markets?.HK?.refresh_time || "09:20" }} 刷新 · A股 {{ v11OpeningFilter.markets?.A?.refresh_time || "09:25" }} 刷新</span>
          · 上游预选 {{ aSummary.requested_rows ?? "不可确认" }} / 同截点证据 {{ aSummary.source_rows ?? "不可确认" }} / 阶段候选 {{ aSummary.candidate_count ?? "不可确认" }} / 入选 {{ stageWorkbench?.selected_a_rows ?? "不可确认" }}
        </small>
      </div>
      <p v-if="v11OpeningFilter && showAStageEvidenceGap" class="evidence-note">A股股票仍保留在独立 D-1 池；没有伪造阶段候选。</p>
      <p v-if="stageLoading" role="status">正在读取 {{ selectedDate }} / {{ selectedStage }}。</p>
      <p v-else-if="stageError" role="alert">{{ stageError }}</p>
      <p v-else-if="stageWorkbench" class="stage-display-status">{{ stageWorkbench.stage.display_status }}</p>
      <p v-if="stage7Explanation" class="evidence-note" data-stage7-explanation>{{ stage7Explanation }}</p>

      <div class="market-columns">
        <section class="market-column" aria-label="A股候选">
          <div class="market-title"><h3>A股</h3><span>{{ stageWorkbench?.selected_a_rows ?? 0 }} 条</span></div>
          <div v-if="!aRows.length" class="empty-card">
            <strong>A股无主表候选</strong>
            <span>{{ currentStageDefinition.label }} 阶段 · source rows {{ aSummary.source_rows ?? 0 }} / requested {{ aSummary.requested_rows ?? aSummary.source_rows ?? 0 }}</span>
            <p>{{ stageWorkbench?.stage.display_status || "该阶段数据尚未进入 V3.5。" }}</p>
          </div>
          <article v-for="row in aRows" :key="rowCode(row)" class="candidate-card">
            <div class="candidate-head"><div><strong>{{ rowName(row) }}</strong><span>{{ rowCode(row) }} · 排名 {{ rowRank(row) }}</span></div><b>{{ row.stage_display_decision || "观察" }}</b></div>
            <dl>
              <div><dt>涨幅</dt><dd>{{ formatPercent(aShareChangePct(row)) }}</dd></div>
              <div><dt>阶段分</dt><dd>{{ rowScore(row) }}</dd></div>
              <div><dt>新闻分</dt><dd>{{ qualityScore(row.news_quality_score) }}</dd></div>
              <div><dt>研报分</dt><dd>{{ qualityScore(row.research_quality_score) }}</dd></div>
              <div><dt>支撑位</dt><dd>{{ evidenceValue(rowSupport(row)) }}</dd></div>
              <div><dt>压力位</dt><dd>{{ evidenceValue(rowPressure(row)) }}</dd></div>
              <div><dt>失效位</dt><dd>{{ evidenceValue(rowInvalidation(row)) }}</dd></div>
              <div><dt>{{ row.next_validation_time ? "下次" : "数据截止" }}</dt><dd>{{ rowNextEvidence(row) || "当前阶段未提供验证时间" }}</dd></div>
            </dl>
          </article>
        </section>
        <section class="market-column" aria-label="港股通候选">
          <div class="market-title"><h3>港股通{{ isPreopenStage ? "09:20二筛" : "二筛" }}</h3><span>{{ hkRows.length }} 条</span></div>
          <div v-if="stageWorkbench && !hkRows.length" class="empty-card">
            <strong>港股通该阶段无可确认候选</strong><p>{{ stageWorkbench?.stage.display_status || "该阶段数据尚未进入 V3.5。" }}</p>
          </div>
          <p v-if="isPreopenStage && hkRows.length" class="evidence-note">09:20阶段只做初筛；支撑/压力/失效位从09:30后阶段生成。</p>
          <article v-for="row in hkRows" :key="rowCode(row)" class="candidate-card">
            <div class="candidate-head"><div><strong>{{ rowName(row) }}</strong><span>{{ rowCode(row) }} · 排名 {{ rowRank(row) }}</span></div><b>{{ row.stage_display_decision || "观察" }}</b></div>
            <dl>
              <div><dt>{{ hkChangeLabel(row) }}</dt><dd>{{ hkChangeValue(row) }}</dd></div>
              <div><dt>{{ hkScoreLabel(row) }}</dt><dd>{{ rowScore(row) }}</dd></div>
              <div v-if="is0920AuctionQuoteRow(row)"><dt>参考价较昨收</dt><dd>{{ formatPercent(row.auction_ref_gap_pct ?? undefined) }}</dd></div>
              <div v-if="!isPreopenStage"><dt>支撑位</dt><dd>{{ evidenceValue(row.support_primary_price) }}</dd></div>
              <div v-if="!isPreopenStage"><dt>压力位</dt><dd>{{ evidenceValue(row.pressure_price) }}</dd></div>
              <div v-if="!isPreopenStage"><dt>失效位</dt><dd>{{ evidenceValue(row.invalidation_price) }}</dd></div>
              <div><dt>下次</dt><dd>{{ row.next_validation_time || "当前阶段未提供验证时间" }}</dd></div>
            </dl>
            <p v-if="!isPreopenStage && rowMissingFields(row).length" class="evidence-gap">待补字段：{{ rowMissingFields(row).join("、") }}</p>
          </article>
        </section>
      </div>
    </section>

    <section v-else id="closeReviewPanel" ref="closeReviewPanel" class="review-panel" tabindex="-1" aria-label="16:08 港股通收盘复盘">
      <div class="section-heading">
        <div><span class="eyebrow">MODEL_REVIEW_CLOSE</span><h2>16:08 港股通模型选股收盘复盘</h2></div>
        <p>{{ closeReview.trade_date || closeReviewPayload?.trade_date || selectedDate }} · 只读，不回填 BUY gate</p>
      </div>
      <p v-if="closeReviewLoading" class="review-loading" role="status">正在读取 {{ selectedDate }} 的收盘 Top20 复盘。</p>
      <p v-else-if="closeReviewError" class="review-loading error" role="alert">{{ closeReviewError }}</p>
      <ReviewView v-else-if="closeReviewPayload" :payload="closeReviewPayload" />
      <template v-else>
        <div class="review-status-line">
          <strong>{{ closeReview.status || "REFERENCE_NOT_IMPORTED" }}</strong>
          <span>{{ closeReview.primary_kpi || "全港股通收盘涨幅Top20覆盖率" }}</span>
          <small>{{ closeReviewEvidenceLabel }} · production_allowed=false · orders_sent=false</small>
        </div>
        <div class="review-metric-grid">
          <article><span>0.2 模型</span><strong>{{ hitTop20(modelMetric) }}</strong><small>入选 {{ modelMetric.selected_count ?? "不可用" }} · 覆盖 {{ modelMetric.coverage_pct ?? "不可用" }}%</small></article>
          <article><span>七阶段并集</span><strong>{{ hitTop20(stageUnionMetric) }}</strong><small>入选 {{ stageUnionMetric.selected_count ?? "不可用" }} · 覆盖 {{ stageUnionMetric.coverage_pct ?? "不可用" }}%</small></article>
          <article><span>收盘 Top20</span><strong>{{ closeReview.row_counts?.close_top20 ?? closeReview.close_top20?.length ?? 0 }}</strong><small>第一 KPI 的真实收盘标签</small></article>
          <article><span>阶段证据行</span><strong>{{ closeReview.row_counts?.stage_rows ?? 0 }}</strong><small>仅同日七阶段，不跨日回填</small></article>
        </div>
        <div v-if="reviewEvidenceGaps.length" class="review-warning">
          <strong>证据边界</strong>
          <span v-for="item in reviewEvidenceGaps" :key="item">{{ item }}</span>
        </div>
        <div class="review-table-wrap">
          <table>
            <thead><tr><th>排名</th><th>代码</th><th>名称</th><th>收盘涨幅</th><th>0.2</th><th>阶段并集</th><th>归因</th></tr></thead>
            <tbody>
              <tr v-for="row in closeReview.top20_attribution ?? []" :key="row.code">
                <td>{{ row.rank ?? "-" }}</td><td>{{ row.code || "-" }}</td><td>{{ row.name?.trim() || UNKNOWN_STOCK_NAME }}</td>
                <td>{{ formatPercent(row.pct_chg_close) }}</td>
                <td>{{ row.model_0_2_hit ? "命中" : "未命中" }}</td>
                <td>{{ row.stage_union_hit ? "命中" : "未命中" }}</td>
                <td>{{ reviewClassification(row.classification) }}</td>
              </tr>
              <tr v-if="!(closeReview.top20_attribution?.length)"><td colspan="7">该交易日没有可展示的收盘 Top20 归因，不把缺失解释为 0 命中。</td></tr>
            </tbody>
          </table>
        </div>
      </template>
    </section>

    <section id="unifiedPreselectPanel" class="panel pool-panel" aria-label="统一预选池">
      <div class="section-heading"><div><span class="eyebrow">D-1 数据</span><h2>D-1 预选池</h2></div><p>{{ pool?.data_status || "等待读取" }}</p></div>
      <p v-if="loading" role="status">正在读取 {{ selectedDate }} 的 D-1 预选池。</p>
      <p v-else-if="loadError" role="alert">{{ loadError }}</p>
      <div v-else id="preselectGroups" class="independent-pool-grid">
        <section v-for="group in preselectionGroups" :id="group.domId" :key="group.pool_id" class="market-column" :aria-label="group.display_name || group.pool_id">
          <div class="market-title">
            <h3>{{ group.display_name || group.pool_id }}</h3>
            <span>{{ poolCountLabel(group) }}</span>
            <button type="button" :aria-expanded="!collapsedPools[group.pool_id]" @click="togglePool(group.pool_id)">
              {{ collapsedPools[group.pool_id] ? "展开" : "收起" }}
            </button>
          </div>
          <p v-if="group.status" class="preview-note"><strong>{{ group.status }}</strong><span v-if="poolEvidenceReason(group)"> · {{ poolEvidenceReason(group) }}</span></p>
          <div v-if="!collapsedPools[group.pool_id]" class="review-table-wrap">
            <table>
              <thead><tr><th>池内排名</th><th>代码</th><th>名称</th><th>来源/状态</th><th>信号日</th><th>池评分</th></tr></thead>
              <tbody>
                <tr v-for="row in poolRows(group)" :key="`${group.pool_id}-${poolRowCode(row)}-${row.pool_rank ?? 0}`">
                  <td>{{ row.pool_rank ?? "-" }}</td><td>{{ poolRowCode(row) }}</td><td>{{ poolRowName(row) }}</td>
                  <td :title="poolRowSourceLane(row)">{{ poolRowSource(row, group) }}</td><td>{{ poolRowSignalDate(row) }}</td><td>{{ row.pool_score ?? "-" }}</td>
                </tr>
                <tr v-if="!poolRows(group).length"><td colspan="6">该池当前无可确认行；保留原池边界，不与其他池合并。</td></tr>
              </tbody>
            </table>
          </div>
        </section>
        <p v-if="!preselectionGroups.length">该交易日没有可确认的独立 D-1 池。</p>
      </div>
    </section>
    </template>
  </main>
</template>
