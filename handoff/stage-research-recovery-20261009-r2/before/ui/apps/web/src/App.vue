<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import TaskStatusView from "./views/TaskStatusView.vue";
import StageExecutionEvidencePanel from "./components/review/StageExecutionEvidencePanel.vue";
import type { StageExecutionEvidenceReadback } from "./contracts/runtime";
import ReviewView from "./views/ReviewView.vue";
import ResearchView from "./views/ResearchView.vue";
import GlobalIndustryMap from "./components/research/GlobalIndustryMap.vue";
import WechatMentionPool from "./components/research/WechatMentionPool.vue";
import type { StageSummary } from "./components/review/StageSummaryPanel.vue";
import { loadReview } from "./api/review";
import type { ReviewEnvelope } from "./contracts/review";

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
];
const RAW194_BACKFILL_DATE = "20260928";
const RAW194_BACKFILL_STAGE = "STAGE_0930_0935";
const A_HISTORICAL_BACKFILL_RUN_ID = "a_share_historical_recovery_20260928_20260929_r3";
const A_1445_HISTORICAL_BACKFILL_RUN_ID = "a_share_historical_recovery_20260928_20260929_1445_witnessfix_r3";
const HK_HISTORICAL_BACKFILL_RUN_ID = "hk_connect_historical_recovery_20260928_20260929_r1";
const A_INTRADAY_BACKFILL_REQUIRED_EVIDENCE = [
  "recovery_mode=HISTORICAL_BACKFILL",
  "capture_manifest_sha256=7c09e834b31fa3275921c092c54791adcd1e9dc9b6c587a814df16a00884d9d6",
  "capture_receipt_sha256=843560dcf2dc29dba258a6552dc2141c146fce6310489c8150cc2a24c761386a",
  "actual_request_started_at=2026-09-29T01:55:22.910230+08:00",
  "actual_response_received_at=2026-09-29T01:55:27.982433+08:00",
];
const HK_BACKFILL_REQUIRED_EVIDENCE = [
  "route=shared_pytdx_exhq_hk_exact_d1_top100",
  "hk_selection_mode=TDXPY_EXHQ_D1_TOP100_OBSERVATION",
  "hk_historical_active_snapshot=UNAVAILABLE_NO_ASOF_INTERFACE",
  "live_hkgainer_lane=NOT_ASSERTED",
  "due_status=HISTORICAL_BACKFILL",
  "hk_d1_status=STRICT_0_2_READY",
  "hk_d1_membership=exact_date_top100",
  "selection_contract=V3_TOP10_RECOMMENDATION",
];
const HK_REVIEWED_STAGE_TUPLES = [
  {
    stage: "STAGE_0930_0935", selectionRunId: "run-1f3857be91dbb7b30df2559f",
    rawArtifactSha256: "e35933881cae68b649fa806d7084dd493550044c9fa316158a1b5da904603358",
  },
  {
    stage: "STAGE_0935_0940", selectionRunId: "run-d1274b94a927e0409be97a30",
    rawArtifactSha256: "93fad4a7c3f052ffc0e882238d06a2eb5e664319b18c5d1ab8dcefd0134d363e",
  },
  {
    stage: "STAGE_0940_0945", selectionRunId: "run-87fece4bd8ec0d5d98de8ef8",
    rawArtifactSha256: "97eee6ce875ac128bcd4cba09e944f3b7bae20253f575dbc66fb9ae3bebd7933",
  },
  {
    stage: "STAGE_0945_1030", selectionRunId: "run-099ed20a1b86e53d6ec642a2",
    rawArtifactSha256: "0017cd178e4b403f2b0a6c558e981f0ac1c94e2a49d9407d00a5a489bdb0ff44",
  },
  {
    stage: "STAGE_1300_1315", selectionRunId: "run-559dc431f8b79a7263980f4b",
    rawArtifactSha256: "4e52fc97cc8a98dc87ad492efd5578405eb5529a955ac2831fcb7f3130bf09dc",
  },
  {
    stage: "STAGE_1445_1500", selectionRunId: "run-1e534c14396c0fb19f51d93d",
    rawArtifactSha256: "488d589ba62294d53fecaf91878381a73b9fd4b762ea8cd5eb6acb8371fad191",
  },
] as const;
type ApprovedStageBackfill = {
  date: string; stage: string; market: "A_SHARE" | "HK_CONNECT"; runId: string;
  selectionRunId: string; artifactId: string; rawArtifactSha256: string;
  algorithmId: string; algorithmSha256: string;
  expectedRows: number; selectionStatus: string; sourceStatus: string;
  cannotConfirmCount: number; requiredEvidence: string[];
  requestTimeEvidenceKeys?: string[]; responseTimeEvidenceKeys?: string[];
  timeEvidenceLabels?: Record<string, string>;
};
const approvedStageBackfills: readonly ApprovedStageBackfill[] = [
  {
    date: RAW194_BACKFILL_DATE,
    stage: "STAGE_0925",
    market: "A_SHARE",
    runId: A_HISTORICAL_BACKFILL_RUN_ID,
    selectionRunId: "run-de75da94f0188643abf4529e",
    artifactId: "selection-de75da94f0188643abf4529e",
    rawArtifactSha256: "14b1ab778756a4dd7750abc86bc8a785c3ec7479885b5a0501e6680ee9f0e069",
    algorithmId: "V3_STAGE_SELECTION_V1",
    algorithmSha256: "eee20b08b50a693dd673f93937ef4eedc63e909295820a0141ce5e728a3754d2",
    expectedRows: 10,
    selectionStatus: "PARTIAL_WITH_ROWS",
    sourceStatus: "PARTIAL_WITH_ROWS",
    cannotConfirmCount: 3,
    requiredEvidence: [
      "recovery_mode=HISTORICAL_BACKFILL",
      "actual_canary_request_started_at=2026-09-29T08:11:10.342799+08:00",
      "actual_canary_response_received_at=2026-09-29T08:11:10.518328+08:00",
      "actual_remainder_request_started_at=2026-09-29T08:21:10.608480+08:00",
      "actual_remainder_response_received_at=2026-09-29T08:21:43.357555+08:00",
      "captured_at_semantics=REQUESTED_STAGE_CUTOFF_METADATA_NOT_RETRIEVAL_TIME",
      "historical_recovery_is_not_natural_capture_or_formal_current",
    ],
    requestTimeEvidenceKeys: ["actual_canary_request_started_at", "actual_remainder_request_started_at"],
    responseTimeEvidenceKeys: ["actual_canary_response_received_at", "actual_remainder_response_received_at"],
    timeEvidenceLabels: {
      actual_canary_request_started_at: "竞价 canary 请求",
      actual_remainder_request_started_at: "剩余请求开始",
      actual_canary_response_received_at: "竞价 canary 响应",
      actual_remainder_response_received_at: "剩余响应收到",
    },
  },
  {
    date: RAW194_BACKFILL_DATE,
    stage: "STAGE_0930_0935",
    market: "A_SHARE",
    runId: A_HISTORICAL_BACKFILL_RUN_ID,
    selectionRunId: "run-36f4b1fc50fdd609a7aa46b7",
    artifactId: "selection-36f4b1fc50fdd609a7aa46b7",
    rawArtifactSha256: "470e8e2c9015dbaefc6d5065b8d4cf8226fcd887b4e56b76ef70435ed0bc13b3",
    algorithmId: "V3_STAGE_SELECTION_V1",
    algorithmSha256: "eee20b08b50a693dd673f93937ef4eedc63e909295820a0141ce5e728a3754d2",
    expectedRows: 10,
    selectionStatus: "PARTIAL_WITH_ROWS",
    sourceStatus: "CANNOT_CONFIRM",
    cannotConfirmCount: 222,
    requiredEvidence: A_INTRADAY_BACKFILL_REQUIRED_EVIDENCE,
  },
  {
    date: RAW194_BACKFILL_DATE,
    stage: "STAGE_0935_0940",
    market: "A_SHARE",
    runId: A_HISTORICAL_BACKFILL_RUN_ID,
    selectionRunId: "run-24676823b07b445e607e0720",
    artifactId: "selection-24676823b07b445e607e0720",
    rawArtifactSha256: "4b2cc69d17e25b8a6db08d1d0a42b29cb16ac0577f81617f171f0687f92df8c6",
    algorithmId: "V3_STAGE_SELECTION_V1",
    algorithmSha256: "eee20b08b50a693dd673f93937ef4eedc63e909295820a0141ce5e728a3754d2",
    expectedRows: 10,
    selectionStatus: "PARTIAL_WITH_ROWS",
    sourceStatus: "CANNOT_CONFIRM",
    cannotConfirmCount: 222,
    requiredEvidence: A_INTRADAY_BACKFILL_REQUIRED_EVIDENCE,
  },
  {
    date: RAW194_BACKFILL_DATE,
    stage: "STAGE_0940_0945",
    market: "A_SHARE",
    runId: A_HISTORICAL_BACKFILL_RUN_ID,
    selectionRunId: "run-e0d29786c525aee84f72bfca",
    artifactId: "selection-e0d29786c525aee84f72bfca",
    rawArtifactSha256: "b6977e9228519758a3f971670df0e9874429f2377b99c1006c603bdfb5447595",
    algorithmId: "V3_STAGE_SELECTION_V1",
    algorithmSha256: "eee20b08b50a693dd673f93937ef4eedc63e909295820a0141ce5e728a3754d2",
    expectedRows: 10,
    selectionStatus: "PARTIAL_WITH_ROWS",
    sourceStatus: "CANNOT_CONFIRM",
    cannotConfirmCount: 222,
    requiredEvidence: A_INTRADAY_BACKFILL_REQUIRED_EVIDENCE,
  },
  {
    date: RAW194_BACKFILL_DATE,
    stage: "STAGE_0945_1030",
    market: "A_SHARE",
    runId: A_HISTORICAL_BACKFILL_RUN_ID,
    selectionRunId: "run-004b4e397cc1c46de988143b",
    artifactId: "selection-004b4e397cc1c46de988143b",
    rawArtifactSha256: "ca8a9ead299fd35ab222de64e9f4ad3b205d0ec3d5f1a98b5fac4a71788fd8aa",
    algorithmId: "V3_STAGE_SELECTION_V1",
    algorithmSha256: "eee20b08b50a693dd673f93937ef4eedc63e909295820a0141ce5e728a3754d2",
    expectedRows: 10,
    selectionStatus: "PARTIAL_WITH_ROWS",
    sourceStatus: "CANNOT_CONFIRM",
    cannotConfirmCount: 218,
    requiredEvidence: A_INTRADAY_BACKFILL_REQUIRED_EVIDENCE,
  },
  {
    date: RAW194_BACKFILL_DATE,
    stage: "STAGE_1300_1315",
    market: "A_SHARE",
    runId: A_HISTORICAL_BACKFILL_RUN_ID,
    selectionRunId: "run-3d511c5c72ab8732afeeaf87",
    artifactId: "selection-3d511c5c72ab8732afeeaf87",
    rawArtifactSha256: "c0e52a8ab58c3f9bb47ca203eeacda0fde3e8e0883caf65f0b5ce44f1be32ae4",
    algorithmId: "V3_STAGE_SELECTION_V1",
    algorithmSha256: "eee20b08b50a693dd673f93937ef4eedc63e909295820a0141ce5e728a3754d2",
    expectedRows: 10,
    selectionStatus: "PARTIAL_WITH_ROWS",
    sourceStatus: "CANNOT_CONFIRM",
    cannotConfirmCount: 234,
    requiredEvidence: A_INTRADAY_BACKFILL_REQUIRED_EVIDENCE,
  },
  {
    date: RAW194_BACKFILL_DATE,
    stage: "STAGE_1445_1500",
    market: "A_SHARE",
    runId: A_1445_HISTORICAL_BACKFILL_RUN_ID,
    selectionRunId: "run-62c7de976a7f879cd3615250",
    artifactId: "selection-62c7de976a7f879cd3615250",
    rawArtifactSha256: "c0f2d34bf5d14dfcba325b1b6a61fd82009aa29c1375dbe126ea0fa8cd353ddc",
    algorithmId: "V3_STAGE_SELECTION_V1",
    algorithmSha256: "eee20b08b50a693dd673f93937ef4eedc63e909295820a0141ce5e728a3754d2",
    expectedRows: 10,
    selectionStatus: "PARTIAL_WITH_ROWS",
    sourceStatus: "CANNOT_CONFIRM",
    cannotConfirmCount: 302,
    requiredEvidence: A_INTRADAY_BACKFILL_REQUIRED_EVIDENCE,
  },
  ...HK_REVIEWED_STAGE_TUPLES.map((tuple): ApprovedStageBackfill => ({
    date: RAW194_BACKFILL_DATE,
    stage: tuple.stage,
    market: "HK_CONNECT",
    runId: HK_HISTORICAL_BACKFILL_RUN_ID,
    selectionRunId: tuple.selectionRunId,
    artifactId: `selection-${tuple.selectionRunId.slice("run-".length)}`,
    rawArtifactSha256: tuple.rawArtifactSha256,
    algorithmId: "V3_STAGE_SELECTION_V1",
    algorithmSha256: "fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506",
    expectedRows: 10,
    selectionStatus: "PARTIAL_WITH_ROWS",
    sourceStatus: "PARTIAL_WITH_ROWS",
    cannotConfirmCount: 1,
    requiredEvidence: HK_BACKFILL_REQUIRED_EVIDENCE,
    requestTimeEvidenceKeys: ["native_capture_started_at"],
    responseTimeEvidenceKeys: ["native_capture_finished_at"],
    timeEvidenceLabels: {
      native_capture_started_at: "HK native capture 开始",
      native_capture_finished_at: "HK native capture 完成",
    },
  })),
];

type DateResponse = {
  default_date: string; stage_dates: string[]; review_dates?: string[]; research_dates?: string[]; future_target_dates: string[];
  dates?: string[]; navigation_date?: string; navigation_timezone?: string;
  hk_observation_only_dates?: string[];
  runtime_identity?: { status: string; release_id: string; process_status: string };
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
  status?: string; complete?: boolean; recommendation_status?: string; producer_id?: string; source_path?: string;
  page_offset?: number; page_limit?: number; has_more?: boolean;
  cannot_confirm?: Array<string | { reason?: string; description?: string }>;
};
type ArrayPageInfo = { offset?: number; limit?: number; returned_rows?: number; has_more?: boolean; complete?: boolean };
type PoolResponse = {
  data_status: string; rows: PoolRow[]; a_all_pool_rows?: PoolRow[];
  pools?: PoolGroup[]; market_totals?: { A?: number; HK?: number }; a_all_pool_complete?: boolean;
  hk_pool_version?: string; hk_pool_role?: string; blocking_reasons: string[];
  pagination?: {
    offset: number; limit: number; has_more: boolean; next_offset?: number | null;
    arrays?: Record<string, ArrayPageInfo>; pools?: Record<string, ArrayPageInfo>;
  };
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
  current_change_pct?: number | null; qmt_gap_pct?: number | null; prev_close_price?: number | null;
  open_price?: number; last_price?: number; high_price?: number; low_price?: number;
  source_last_bar_time?: string;
  action_level?: string; trade_status?: string; formal_eligible?: boolean;
};
type MarketSummary = {
  label?: string; candidate_count?: number | null; source_rows?: number | null;
  artifact_id?: string | null; run_id?: string | null; raw_artifact_sha256?: string | null;
  algorithm_id?: string | null; algorithm_sha256?: string | null;
  requested_rows?: number | null; source_status?: string; data_level?: string;
  status?: string; selection_status?: string; selected_rows?: number | null; coverage_ratio?: number | null;
  missing_symbols?: string[]; cannot_confirm?: string[]; source_evidence?: string[];
  display_mode?: "CANNOT_CONFIRM" | "OBSERVATION_UNVERIFIED" | "READY_EMPTY" | "FORMAL" | string;
  display_reasons?: string[]; observation_count?: number | null;
  selection_mode?: string; backfill_run_id?: string | null; backfill_run_ids?: string[];
  selection_manifest_sha256?: string | null; selection_receipt_sha256?: string | null;
  selection_artifact_sha256?: string | null; selection_manifest_receipt_verified?: boolean;
  runner_receipt_verified?: boolean; runner_receipt_status?: string; runner_receipt_sha256?: string | null;
};
type OpeningSecondFilterMarket = {
  refresh_time?: string; strategy?: string; row_count?: number;
};
type OpeningSecondFilter = {
  model_id?: string; model_version?: string; champion_contract?: string;
  markets?: { A?: OpeningSecondFilterMarket; HK?: OpeningSecondFilterMarket };
};
type StageWorkbench = {
  ok?: boolean; trade_date?: string; run_id?: string;
  stage: { stage_id: string; label?: string; window?: string; status: string; display_status: string };
  markets?: { A?: MarketSummary; HK?: MarketSummary };
  unified_rows: StageRow[];
  selected_a_rows: number; selected_hk_rows: number | null; selected_total_rows: number | null;
  selection_mode: string; response_source?: string; reference_snapshot?: boolean;
  mode?: string; backfill_run_id?: string; market?: string; recommendation_status?: string;
  RESEARCH_ONLY?: boolean; production_allowed?: boolean; buy_gate_updated?: boolean; orders_sent?: boolean;
  write_performed?: boolean;
  opening_second_filter?: OpeningSecondFilter;
  stage_lineage?: StageLineage;
  execution_evidence?: StageExecutionEvidenceReadback;
};
type StageLineageBranch = {
  label?: string; status?: string; origin?: string; receipt_sha256?: string | null;
  receipt_raw_sha256?: string | null; due_status?: string;
  receipt_sha256_by_market?: Record<string, string>;
  receipt_raw_sha256_by_market?: Record<string, string>;
  manifest_sha256_by_market?: Record<string, string>;
  manifest_raw_sha256_by_market?: Record<string, string>;
  lineage_by_market?: Record<string, {
    run_id: string; artifact_sha256: string; manifest_sha256: string;
    manifest_raw_sha256: string; receipt_sha256: string; receipt_raw_sha256: string;
  }>;
  write_performed?: boolean; markets?: { A?: { selected_rows?: number }; HK?: { selected_rows?: number } };
};
type StageLineage = {
  natural?: StageLineageBranch;
  recovery?: StageLineageBranch;
  cannot_confirm?: string[];
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
  schema_version?: string; evidence_mode?: string;
  status?: string; trade_date?: string; primary_kpi?: string;
  models?: Record<string, ReviewMetric>; stages?: Record<string, ReviewMetric>;
  stage_union?: ReviewMetric; row_counts?: Record<string, number>;
  top20_attribution?: ReviewAttributionRow[]; close_top20?: ReviewAttributionRow[];
  missing_stages?: string[]; cannot_confirm?: string[];
  production_allowed?: boolean; buy_gate_updated?: boolean; orders_sent?: boolean;
};
type ReviewResponse = {
  trade_date?: string; reference_snapshot?: boolean;
  market_reviews?: { HK?: { model_selection_review?: ModelSelectionReview } };
};

const initialUrlParams = new URLSearchParams(window.location.search);
const initialUrlDate = initialUrlParams.get("date") || "";
// Bind requested identity before I/O; this does not admit a pool or a result.
const selectedDate = ref(isExactCalendarDate(initialUrlDate) ? initialUrlDate : "");
const dateData = ref<DateResponse>({ default_date: "", stage_dates: [], future_target_dates: [] });
const pool = ref<PoolResponse | null>(null);
const poolOffset = ref(0);
const loading = ref(false);
const loadError = ref("");
let requestVersion = 0;
const selectedStage = ref(
  stageDefinitions.find((stage) => stage.id === initialUrlParams.get("stage"))?.id
    ?? stageDefinitions[0].id,
);
const backfillRunId = ref("");
const backfillMarket = ref("");
const isBackfillReadOnly = computed(() => Boolean(backfillRunId.value));
const isHkOnlyStage = computed(() => selectedStage.value === "STAGE_1545_1555");
const stageWorkbench = ref<StageWorkbench | null>(null);
const stageLoading = ref(false);
const stageError = ref("");
const stageSnapshots = ref<Record<string, StageTimelineSnapshot>>({});
const approvedBackfillSnapshots = ref<Record<string, StageTimelineSnapshot>>({});
const stageRunStatus = ref("");
const navigationStatus = ref("");
const taskStatusActive = ref(false);
const researchActive = ref(false);
const researchArchiveEntry = ref(false);
const closeReviewActive = ref(false);
const reviewFocus = ref<"A" | "HK" | "research">("HK");
const reviewTitle = computed(() => ({ A: "A股复盘", HK: "16:08 港股通模型选股收盘复盘", research: "研究复盘" })[reviewFocus.value]);
const runtimeLabel = computed(() => {
  const identity = dateData.value.runtime_identity;
  return identity?.status === "MANIFEST_EXECUTION_FILES_VERIFIED"
    ? `V4 · ${identity.release_id} · manifest/执行文件已核验`
    : "V4 · 运行版本 CANNOT_CONFIRM";
});
const closeReviewLoading = ref(false);
const closeReviewError = ref("");
const closeReviewPayload = ref<ReviewEnvelope | null>(null);
let closeReviewRequestVersion = 0;
let stageRequestVersion = 0;
let stageTimelineRequestVersion = 0;
let stageRequestController: AbortController | null = null;
let stageTimelineRequestController: AbortController | null = null;
const STAGE_REQUEST_TIMEOUT_MS = 12_000;

const dateOptions = computed(() =>
  [...new Set([
    ...(dateData.value.dates ?? []),
    ...dateData.value.future_target_dates,
    ...dateData.value.stage_dates,
    ...(dateData.value.review_dates ?? []),
    ...(dateData.value.research_dates ?? []),
    ...(dateData.value.hk_observation_only_dates ?? []),
    dateData.value.navigation_date,
    dateData.value.default_date,
  ].filter((date): date is string => Boolean(date)))].sort(),
);
const tradingDateOptions = computed(() =>
  [...new Set([
    ...(dateData.value.dates ?? []),
    ...dateData.value.future_target_dates,
    ...dateData.value.stage_dates,
    ...(dateData.value.review_dates ?? []),
    ...(dateData.value.hk_observation_only_dates ?? []),
    dateData.value.navigation_date,
    dateData.value.default_date,
  ].filter((date): date is string => Boolean(date)))].sort(),
);
const researchDateOptions = computed(() =>
  [...new Set((dateData.value.research_dates ?? []).filter((date): date is string => Boolean(date)))].sort(),
);
const activeDateOptions = computed(() => {
  const options = researchActive.value ? researchDateOptions.value : tradingDateOptions.value;
  return options.length ? options : dateOptions.value;
});
const isHkObservationOnlyDate = computed(() =>
  Boolean(dateData.value.hk_observation_only_dates?.includes(selectedDate.value)),
);
const dateInputMin = computed(() => formatDateInput(activeDateOptions.value[0] ?? ""));
const dateInputMax = computed(() => formatDateInput(activeDateOptions.value.at(-1) ?? ""));
const dateInputTitle = computed(() =>
  researchActive.value
    ? "研究自然日（周末材料可用）"
    : dateData.value.future_target_dates.includes(selectedDate.value)
    ? "次日选股池准备（未开盘）"
    : "选择交易日",
);
const nextFutureTargetDate = computed(() => {
  const navigationDate = dateData.value.navigation_date || dateData.value.default_date || "";
  return [...new Set(dateData.value.future_target_dates)]
    .filter((date) => /^\d{8}$/.test(date) && (!navigationDate || date > navigationDate))
    .sort()[0] ?? "";
});
const selectedDateContext = computed(() => {
  if (!selectedDate.value) return "请选择交易日。";
  const formattedDate = formatDateInput(selectedDate.value);
  return dateData.value.future_target_dates.includes(selectedDate.value)
    ? `当前查看次日预选池目标日：${formattedDate}。阶段状态以服务端回执为准，未到时不表示已完成。`
    : `当前查看交易日：${formattedDate}`;
});
const currentStageDefinition = computed(() =>
  stageDefinitions.find((stage) => stage.id === selectedStage.value) ?? stageDefinitions[0],
);
const raw194BackfillHref = computed(() => {
  const query = new URLSearchParams({
    date: RAW194_BACKFILL_DATE,
    stage: RAW194_BACKFILL_STAGE,
    backfill_run_id: A_HISTORICAL_BACKFILL_RUN_ID,
    market: "A_SHARE",
  });
  return `/?${query.toString()}`;
});
const backfillMarketKey = computed(() => backfillMarket.value === "A_SHARE"
  ? "A"
  : backfillMarket.value === "HK_CONNECT"
  ? "HK"
  : "");
const backfillMarketName = computed(() => backfillMarket.value === "A_SHARE"
  ? "A_SHARE"
  : backfillMarket.value === "HK_CONNECT"
  ? "HK_CONNECT"
  : "CANNOT_CONFIRM");
const backfillMarketSummary = computed(() => {
  const marketKey = backfillMarketKey.value;
  return marketKey ? stageWorkbench.value?.markets?.[marketKey] ?? {} : {};
});
const backfillRows = computed(() => {
  const marketKey = backfillMarketKey.value;
  return marketKey ? stageWorkbench.value?.unified_rows?.filter((row) => row.market === marketKey) ?? [] : [];
});
const backfillSourceEvidence = computed(() => backfillMarketSummary.value.source_evidence ?? []);
const backfillCannotConfirm = computed(() => backfillMarketSummary.value.cannot_confirm ?? []);
const backfillMissingSymbols = computed(() => backfillMarketSummary.value.missing_symbols ?? []);
const backfillArtifactRunId = computed(() => stageWorkbench.value?.run_id ?? "CANNOT_CONFIRM");
function backfillEvidenceValue(key: string) {
  const prefix = `${key}=`;
  return backfillSourceEvidence.value.find((item) => item.startsWith(prefix))?.slice(prefix.length) ?? "CANNOT_CONFIRM";
}
function approvedBackfillKey(binding: ApprovedStageBackfill) {
  return `${binding.date}|${binding.stage}|${binding.market}|${binding.runId}`;
}
function approvedMarketKey(market: ApprovedStageBackfill["market"]) {
  return market === "A_SHARE" ? "A" : "HK";
}
function approvedMarketName(market: ApprovedStageBackfill["market"]) {
  return market === "A_SHARE" ? "A股" : "港股通";
}
const currentApprovedBackfills = computed(() => isBackfillReadOnly.value || researchActive.value || closeReviewActive.value
  ? []
  : approvedStageBackfills.filter((binding) =>
    binding.date === selectedDate.value && binding.stage === selectedStage.value,
  ));
function approvedBackfillSnapshot(binding: ApprovedStageBackfill) {
  return approvedBackfillSnapshots.value[approvedBackfillKey(binding)];
}
function approvedBackfillRows(binding: ApprovedStageBackfill) {
  const market = approvedMarketKey(binding.market);
  return approvedBackfillSnapshot(binding)?.payload?.unified_rows?.filter((row) => row.market === market) ?? [];
}
type CandidateMarketKey = "A" | "HK";
function approvedBackfillForCandidate(market: CandidateMarketKey) {
  // The exact ordinary API display contract owns HK rows and missing/empty
  // states. The separate approved-backfill evidence panel remains intact.
  const workbench = stageWorkbench.value;
  if (market === "HK" && !isBackfillReadOnly.value
      && workbench?.trade_date === selectedDate.value
      && workbench?.stage?.stage_id === selectedStage.value
      && ["CANNOT_CONFIRM", "OBSERVATION_UNVERIFIED", "READY_EMPTY", "FORMAL"]
        .includes(workbench?.markets?.HK?.display_mode || "")) return undefined;
  return currentApprovedBackfills.value.find((binding) => approvedMarketKey(binding.market) === market);
}
const approvedACandidateBinding = computed(() => approvedBackfillForCandidate("A"));
const approvedHKCandidateBinding = computed(() => approvedBackfillForCandidate("HK"));
const aCandidateRows = computed(() => {
  if (isBackfillReadOnly.value) return backfillMarketKey.value === "A" ? backfillRows.value : [];
  const binding = approvedACandidateBinding.value;
  return binding ? approvedBackfillRows(binding) : aRows.value;
});
const hkCandidateRows = computed(() => {
  if (isBackfillReadOnly.value) return backfillMarketKey.value === "HK" ? backfillRows.value : [];
  const binding = approvedHKCandidateBinding.value;
  return binding ? approvedBackfillRows(binding) : hkRows.value;
});
function candidateRowsAreHistorical(market: CandidateMarketKey) {
  if (isBackfillReadOnly.value) return backfillMarketKey.value === market;
  return Boolean(market === "A" ? approvedACandidateBinding.value : approvedHKCandidateBinding.value);
}
function candidateColumnCountLabel(market: CandidateMarketKey) {
  if (isBackfillReadOnly.value) {
    if (backfillMarketKey.value !== market) return "未请求";
    return stageWorkbench.value ? `${backfillRows.value.length} 条` : "读取中";
  }
  const binding = market === "A" ? approvedACandidateBinding.value : approvedHKCandidateBinding.value;
  if (binding) {
    const snapshot = approvedBackfillSnapshot(binding);
    if (!snapshot || snapshot.loading) return "读取中";
    if (snapshot.error || !snapshot.payload) return "CANNOT_CONFIRM";
    return `${approvedBackfillRows(binding).length} 条`;
  }
  if (stageLoading.value) return "读取中";
  if (stageError.value) return "CANNOT_CONFIRM";
  if (market === "HK" && hkSummary.value.display_mode === "CANNOT_CONFIRM") return "待确认/缺少正式产物";
  if (market === "HK" && hkSummary.value.display_mode === "OBSERVATION_UNVERIFIED") {
    return `${hkSummary.value.observation_count ?? 0} 条观察行 · 未验证`;
  }
  if (market === "HK" && hkSummary.value.display_mode === "READY_EMPTY") return "0 条 · 正式空结果已验证";
  const rows = market === "A" ? aCandidateRows.value : hkCandidateRows.value;
  return `${rows.length} 条`;
}
function candidateColumnEmptyMessage(market: CandidateMarketKey) {
  if (isBackfillReadOnly.value && backfillMarketKey.value !== market) {
    return "本次历史请求未包含该市场；不代表该市场零候选。";
  }
  const binding = market === "A" ? approvedACandidateBinding.value : approvedHKCandidateBinding.value;
  if (binding) {
    const snapshot = approvedBackfillSnapshot(binding);
    if (!snapshot || snapshot.loading) return "正在读取冻结绑定的历史回补。";
    if (snapshot.error || !snapshot.payload) return "历史回补读取失败 · CANNOT_CONFIRM。";
    return "该历史回补未返回可确认候选。";
  }
  if (isBackfillReadOnly.value) return "本次历史请求未返回可确认候选。";
  if (market === "HK" && hkSummary.value.display_mode === "CANNOT_CONFIRM") {
    const reasons = hkSummary.value.cannot_confirm?.join("、") || "缺少正式 SelectionStore 产物";
    return `待确认/缺少正式产物：${reasons}`;
  }
  if (market === "HK" && hkSummary.value.display_mode === "READY_EMPTY") {
    return "正式结果为空（READY_EMPTY）；正式入选 0 条。";
  }
  if (market === "HK" && hkSummary.value.display_mode === "OBSERVATION_UNVERIFIED") {
    return `观察行未验证：${hkSummary.value.display_reasons?.join("、") || "缺少完整绑定"}`;
  }
  return market === "A" ? "A股无主表候选" : "港股通该阶段无可确认候选";
}
function candidateCodeValue(row: StageRow, market: CandidateMarketKey) {
  if (!candidateRowsAreHistorical(market)) return rowCode(row);
  const value = row.code || row.symbol || row.stock_code;
  return typeof value === "string" && value.trim() ? value : "未知";
}
function candidateNameValue(row: StageRow, market: CandidateMarketKey) {
  if (!candidateRowsAreHistorical(market)) return rowName(row);
  const value = rowName(row);
  return value === "名称未获权威确认" ? "未知" : value;
}
function candidateRankValue(row: StageRow, market: CandidateMarketKey) {
  if (!candidateRowsAreHistorical(market)) return rowRank(row);
  const value = row.rank ?? row.stage_rank ?? row.pool_rank;
  return value === undefined || value === null || value === "" ? "未知" : value;
}
function candidateActionLabel(row: StageRow, market: CandidateMarketKey) {
  if (market === "HK" && hkSummary.value.display_mode === "OBSERVATION_UNVERIFIED") return "观察 · 未验证";
  if (market === "HK" && hkSummary.value.display_mode === "CANNOT_CONFIRM") return "观察 · 未验证";
  return candidateRowsAreHistorical(market) ? backfillRowStatusLabel(row) : market === "A"
    ? aShareActionLabel(row)
    : row.stage_display_decision || "观察";
}
function candidateChangeValue(row: StageRow, market: CandidateMarketKey) {
  if (!candidateRowsAreHistorical(market)) return market === "A" ? aShareChangeDisplay(row) : hkChangeValue(row);
  if (market === "A") {
    if (isA0925UnknownPrevClose(row)) return "昨收缺失，涨幅不可确认";
    const value = aShareChangePct(row);
    return typeof value === "number" && Number.isFinite(value) ? formatPercent(value) : "未知";
  }
  const value = row.d1_change_pct ?? row.current_change_pct;
  return typeof value === "number" && Number.isFinite(value) ? formatPercent(value) : "未知";
}
function candidateScoreValue(row: StageRow, market: CandidateMarketKey) {
  const score = row.score ?? row.stage_score ?? row.stage_rtdata_score;
  if (candidateRowsAreHistorical(market) && (typeof score !== "number" || !Number.isFinite(score))) return "未知";
  return rowScore(row);
}
function candidateQualityValue(value: number | undefined, market: CandidateMarketKey) {
  if (candidateRowsAreHistorical(market) && (typeof value !== "number" || !Number.isFinite(value))) return "未知";
  return qualityScore(value);
}
function candidateEvidenceValue(value: number | string | null | undefined, market: CandidateMarketKey) {
  if (candidateRowsAreHistorical(market) && (value === undefined || value === null || value === "")) return "未知";
  return evidenceValue(value);
}
function candidateValidationValue(row: StageRow, market: CandidateMarketKey) {
  const value = candidateRowsAreHistorical(market) ? row.next_validation_time : rowNextEvidence(row);
  return value || (candidateRowsAreHistorical(market) ? "未知" : "当前阶段未提供验证时间");
}
function approvedBackfillSourceEvidence(binding: ApprovedStageBackfill) {
  const summary = approvedBackfillSnapshot(binding)?.payload?.markets?.[approvedMarketKey(binding.market)];
  return summary?.source_evidence ?? [];
}
function approvedBackfillCannotConfirm(binding: ApprovedStageBackfill) {
  const summary = approvedBackfillSnapshot(binding)?.payload?.markets?.[approvedMarketKey(binding.market)];
  return summary?.cannot_confirm ?? [];
}
function approvedBackfillEvidenceValue(binding: ApprovedStageBackfill, key: string) {
  const prefix = `${key}=`;
  return approvedBackfillSourceEvidence(binding).find((item) => item.startsWith(prefix))?.slice(prefix.length) ?? "CANNOT_CONFIRM";
}
function approvedBackfillTimeEvidence(binding: ApprovedStageBackfill, kind: "request" | "response") {
  const keys = kind === "request"
    ? binding.requestTimeEvidenceKeys ?? ["actual_request_started_at"]
    : binding.responseTimeEvidenceKeys ?? ["actual_response_received_at"];
  const evidence = approvedBackfillSourceEvidence(binding);
  const values = keys.flatMap((key) => {
    const prefix = `${key}=`;
    const matches = evidence.filter((item) => item.startsWith(prefix));
    if (!matches.length) return [];
    const label = binding.timeEvidenceLabels?.[key];
    return matches.map((item, index) => {
      const value = item.slice(prefix.length);
      const ordinal = matches.length > 1 ? ` ${index + 1}` : "";
      return label ? `${label}${ordinal} ${value}` : value;
    });
  });
  return values.length ? values.join("；") : "CANNOT_CONFIRM";
}
function approvedBackfillStatusSummary(binding: ApprovedStageBackfill) {
  const summarize = (key: "trade_status" | "action_level") => {
    const counts = new Map<string, number>();
    for (const row of approvedBackfillRows(binding)) {
      const value = row[key] || "CANNOT_CONFIRM";
      counts.set(value, (counts.get(value) ?? 0) + 1);
    }
    return [...counts.entries()]
      .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
      .map(([value, count]) => `${value} ${count}`)
      .join(" / ") || "CANNOT_CONFIRM";
  };
  return `trade_status ${summarize("trade_status")} · action_level ${summarize("action_level")}`;
}
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
const canLoadWechatMentions = computed(() => Array.isArray(pool.value?.pools));
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
      complete: pool.value?.a_all_pool_complete,
      pool_size: pool.value?.market_totals?.A ?? pool.value?.a_all_pool_rows?.length ?? 0,
      returned_rows: pool.value?.a_all_pool_rows?.length ?? 0,
      page_offset: pool.value?.pagination?.arrays?.a_all_pool_rows?.offset,
      page_limit: pool.value?.pagination?.arrays?.a_all_pool_rows?.limit,
      has_more: pool.value?.pagination?.arrays?.a_all_pool_rows?.has_more,
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
function isWechatPool(group: PoolGroup) {
  return group.pool_id === "wechat_public_account_v3_preselect";
}
function isBaimaoPool(group: PoolGroup) {
  return group.pool_id === "a_share_baimao_research_map";
}
function isCompactResearchPool(group: PoolGroup) {
  return (isWechatPool(group) || isBaimaoPool(group)) && poolRows(group).length === 0;
}
function poolEvidenceReason(group: PoolGroup) {
  const item = group.cannot_confirm?.[0];
  if (typeof item === "string") return item;
  return item?.reason || item?.description || "";
}
function poolEvidenceDetails(group: PoolGroup) {
  const items = group.cannot_confirm ?? [];
  return group.status && poolEvidenceReason(group) ? items.slice(1) : items;
}
function poolRowCode(row: PoolRow) {
  return row.symbol || row.code || "WATCH_ONLY";
}
function poolRowName(row: PoolRow) {
  return row.display_name || row.stock_name || row.name || poolRowCode(row);
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
  const returned = group.returned_rows ?? group.rows?.length ?? 0;
  const sourceBlocked = ["CANNOT_CONFIRM", "NOT_MATERIALIZED", "MISSING", "DATA_BLOCKED_EMPTY", "FAILED", "ERROR"].includes((group.status || "").toUpperCase());
  if (sourceBlocked) return `来源未确认；本页 ${returned} / 来源声明 ${total} 条`;
  if (total === 0 && returned === 0 && group.complete !== true) return "未生成/待补齐";
  // complete=false also means a valid source was paginated. Never turn it into a source failure.
  if (returned < total) {
    const paginationConfirmed = Number.isInteger(group.page_offset)
      && Number.isInteger(group.page_limit)
      && (group.page_limit ?? 0) > 0
      && typeof group.has_more === "boolean";
    if (paginationConfirmed && ((group.page_offset ?? 0) > 0 || group.has_more)) {
      return `本页 ${returned} / 来源共 ${total} 条（分页显示）`;
    }
    return `本页 ${returned} / 来源声明 ${total} 条（分页或来源完整性未确认）`;
  }
  return `完整 ${total} 条`;
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
const stageSummary = computed<StageSummary | null>(() => {
  const workbench = stageWorkbench.value;
  if (!workbench) return null;
  const stage = workbench.stage;
  return {
    trade_date: workbench.trade_date,
    stage_id: stage?.stage_id,
    // Keep the server supplied identity intact.  A missing label must make
    // the summary unverified instead of being silently replaced by the
    // currently selected stage's local label.
    stage_label: stage?.label,
    phase_status: phaseStatus.value,
    selected_a_rows: workbench.selected_a_rows,
    a_source_rows: aSummary.value.source_rows,
    a_candidate_count: aSummary.value.candidate_count,
    selected_hk_rows: workbench.selected_hk_rows,
    hk_candidate_count: hkSummary.value.candidate_count,
    reference_mode: referenceMode.value,
    selected_total_rows: workbench.selected_total_rows,
    data_level: hkSummary.value.data_level || aSummary.value.data_level,
  };
});
const aSummary = computed(() => stageWorkbench.value?.markets?.A ?? {});
const hkSummary = computed(() => stageWorkbench.value?.markets?.HK ?? {});
const showAStageEvidenceGap = computed(() =>
  shouldShowAStageEvidenceGap(aSummary.value, stageWorkbench.value?.selected_a_rows),
);
const closeReview = computed(() =>
  (closeReviewPayload.value?.market_reviews.HK.model_selection_review ?? {}) as ModelSelectionReview,
);
const modelMetric = computed(() => closeReview.value.models?.["0.2_prob_active"] ?? {});
const stageUnionMetric = computed(() => closeReview.value.stage_union ?? {});
const closeReviewEvidenceLabel = computed(() => {
  if (closeReview.value.evidence_mode === "V3_5_NATIVE_PRODUCTION") return "V3.5 原生收盘证据";
  return "收盘证据未导入";
});
const reviewEvidenceGaps = computed(() =>
  [...new Set([...(closeReview.value.missing_stages ?? []), ...(closeReview.value.cannot_confirm ?? [])])],
);

function formatPercent(value?: number | null) {
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

function assertExactStagePayload(payload: unknown, requestedDate: string, stage: string) {
  assertExactResponseDate(payload, requestedDate, ["trade_date"], "阶段工作台");
  if (!payload || typeof payload !== "object") throw new Error("阶段工作台响应不是对象。");
  const record = payload as Record<string, unknown>;
  const stageRecord = record.stage;
  if (!stageRecord || typeof stageRecord !== "object" || (stageRecord as Record<string, unknown>).stage_id !== stage) {
    throw new Error(`阶段工作台阶段证据错误：请求=${stage}。`);
  }
}

function assertBackfillStagePayload(payload: unknown, requestedDate: string, stage: string, runId: string, market: string) {
  assertExactStagePayload(payload, requestedDate, stage);
  const record = payload as Record<string, unknown>;
  const expectedMarket = market === "A_SHARE" ? "A" : market === "HK_CONNECT" ? "HK" : "";
  if (!expectedMarket) throw new Error("历史回补市场不在固定合同中，未展示该响应。");
  if (record.mode !== "BACKFILL" || record.backfill_run_id !== runId || record.market !== market
    || record.selection_mode !== "HISTORICAL_BACKFILL_READ_ONLY") {
    throw new Error("历史回补身份与请求不一致，未展示该响应。");
  }
  if (record.RESEARCH_ONLY !== true || record.production_allowed !== false
    || record.buy_gate_updated !== false || record.orders_sent !== false) {
    throw new Error("历史回补安全标记不可确认，未展示该响应。");
  }
  const rows = Array.isArray(record.unified_rows) ? record.unified_rows : [];
  if (rows.some((row) => !row || typeof row !== "object"
    || (row as Record<string, unknown>).market !== expectedMarket
    || !isSafeBackfillRow(row as StageRow, stage, expectedMarket))) {
    throw new Error("历史回补候选越过 WATCH_ONLY 边界，未展示该响应。");
  }
}

function assertApprovedStageBackfill(payload: unknown, binding: ApprovedStageBackfill) {
  assertExactStagePayload(payload, binding.date, binding.stage);
  const record = payload as Record<string, unknown>;
  if (record.mode !== "BACKFILL" || record.backfill_run_id !== binding.runId
    || record.market !== binding.market || record.selection_mode !== "HISTORICAL_BACKFILL_READ_ONLY"
    || record.run_id !== binding.selectionRunId) {
    throw new Error("历史回补身份与固定日期/阶段/市场绑定不一致，未展示该响应。");
  }
  if (record.RESEARCH_ONLY !== true || record.production_allowed !== false
    || record.buy_gate_updated !== false || record.orders_sent !== false || record.write_performed !== false) {
    throw new Error("历史回补安全标记不可确认，未展示该响应。");
  }
  const expectedMarket = approvedMarketKey(binding.market);
  const summaries = record.markets as Record<string, MarketSummary> | undefined;
  const summary = summaries?.[expectedMarket];
  const rows = Array.isArray(record.unified_rows) ? record.unified_rows : [];
  const stage = record.stage as Record<string, unknown>;
  const selectedRows = expectedMarket === "A" ? record.selected_a_rows : record.selected_hk_rows;
  if (!summary || stage.status !== binding.selectionStatus
    || summary.selection_status !== binding.selectionStatus || summary.source_status !== binding.sourceStatus
    || summary.artifact_id !== binding.artifactId || summary.run_id !== binding.selectionRunId
    || summary.raw_artifact_sha256 !== binding.rawArtifactSha256
    || summary.algorithm_id !== binding.algorithmId || summary.algorithm_sha256 !== binding.algorithmSha256
    || selectedRows !== binding.expectedRows || rows.length !== binding.expectedRows
    || summary.selected_rows !== binding.expectedRows
    || (summary.cannot_confirm?.length ?? 0) !== binding.cannotConfirmCount) {
    throw new Error("历史回补行数、PARTIAL/WATCH_ONLY 状态或缺项数量与冻结证据不一致，未展示该响应。");
  }
  if (rows.some((row) => !row || typeof row !== "object"
    || (row as Record<string, unknown>).market !== expectedMarket
    || !isSafeBackfillRow(row as StageRow, binding.stage, expectedMarket))) {
    throw new Error("历史回补候选越过 WATCH_ONLY 边界，未展示该响应。");
  }
  const evidence = summary.source_evidence ?? [];
  if (binding.requiredEvidence.some((item) => !evidence.includes(item))) {
    throw new Error("历史回补真实取数时点或来源标记与冻结证据不一致，未展示该响应。");
  }
}

async function fetchExactStagePayload(url: string, signal: AbortSignal): Promise<StageWorkbench> {
  if (signal.aborted) throw new DOMException("阶段工作台读取已取消。", "AbortError");
  const controller = new AbortController();
  let timeoutId: number | undefined;
  let onAbort: (() => void) | undefined;
  const interrupted = new Promise<never>((_, reject) => {
    onAbort = () => {
      reject(new DOMException("阶段工作台读取已取消。", "AbortError"));
      controller.abort(signal.reason);
    };
    signal.addEventListener("abort", onAbort, { once: true });
    timeoutId = window.setTimeout(() => {
      reject(new Error("阶段工作台读取超时。"));
      controller.abort();
    }, STAGE_REQUEST_TIMEOUT_MS);
  });
  try {
    const read = async (): Promise<StageWorkbench> => {
      const response = await fetch(url, { cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error("request failed");
      return await response.json() as StageWorkbench;
    };
    return await Promise.race([read(), interrupted]);
  } finally {
    if (timeoutId !== undefined) window.clearTimeout(timeoutId);
    if (onAbort) signal.removeEventListener("abort", onAbort);
  }
}

function abortStageRequests() {
  stageRequestController?.abort();
  stageTimelineRequestController?.abort();
  stageRequestController = null;
  stageTimelineRequestController = null;
}

function formatDateInput(value: string) {
  return /^\d{8}$/.test(value)
    ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`
    : "";
}
function compactDateInput(value: string) {
  return value.replaceAll("-", "");
}
function evidenceValue(value?: number | string | null) {
  if (value === undefined || value === null || value === "") return "该字段未在当前阶段生成";
  const number = typeof value === "number" ? value : /^[-+]?\d+(?:\.\d+)?$/.test(value.trim()) ? Number(value) : NaN;
  return Number.isFinite(number) ? String(Number(number.toFixed(3))) : "该字段未在当前阶段生成";
}
function rowCode(row: StageRow) {
  return row.code || row.symbol || row.stock_code || "WATCH_ONLY";
}
function rowName(row: StageRow) {
  for (const value of [row.name, row.stock_name]) {
    const text = typeof value === "string" ? value.trim() : "";
    if (text && text !== rowCode(row) && !/^(?:(?:A|SH|SZ|BJ|HK)[. ]?)?\d+(?:[. ]?(?:SH|SZ|BJ|HK))?(?:[（(]分[）)])?$/i.test(text)
        && !["UNKNOWN", "CANNOT_CONFIRM", "未命名", "未知"].includes(text.toUpperCase())) return text;
  }
  return "名称未获权威确认";
}
function rowRank(row: StageRow) {
  return row.rank ?? row.stage_rank ?? row.pool_rank ?? "-";
}
function isA0925UnknownPrevClose(row: StageRow) {
  return selectedStage.value === "STAGE_0925"
    && row.source_mode === "A_SHARE_AUCTION_TRANSACTION_STAGE_0925"
    && row.prev_close_price == null;
}
function aShareChangePct(row: StageRow) {
  if (isA0925UnknownPrevClose(row)) return undefined;
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
function aShareChangeDisplay(row: StageRow) {
  if (isA0925UnknownPrevClose(row)) return "昨收缺失，涨幅不可确认";
  return formatPercent(aShareChangePct(row));
}
function aShareActionLabel(row: StageRow) {
  if (isBackfillReadOnly.value) return backfillRowStatusLabel(row);
  if (selectedStage.value === "STAGE_0925" && row.action_level === "NO_BUY") {
    return `NO_BUY · ${row.trade_status || "CANNOT_CONFIRM"}`;
  }
  return row.stage_display_decision || "观察";
}
function isSafeBackfillRow(row: StageRow, stage: string, market: string) {
  if (row.formal_eligible !== false) return false;
  if (market === "A" && stage === "STAGE_0925") {
    return row.trade_status === "WATCH_ONLY"
      && row.action_level === "NO_BUY"
      && row.status === "集合竞价成交代理观察"
      && row.source_mode === "A_SHARE_AUCTION_TRANSACTION_STAGE_0925"
      && row.prev_close_price == null;
  }
  if (market === "A" && [
    "STAGE_0930_0935",
    "STAGE_0935_0940",
    "STAGE_0940_0945",
    "STAGE_0945_1030",
    "STAGE_1300_1315",
    "STAGE_1445_1500",
  ].includes(stage)) {
    return row.trade_status === "WATCH_ONLY"
      && row.action_level === "WATCH_ONLY"
      && row.status === "WATCH_ONLY"
      && row.source_mode === "A_SHARE_WINDOWS_V3_LIVE_STAGE";
  }
  const reviewedHkStages = [
    "STAGE_0930_0935",
    "STAGE_0935_0940",
    "STAGE_0940_0945",
    "STAGE_0945_1030",
    "STAGE_1300_1315",
    "STAGE_1445_1500",
  ];
  return market === "HK"
    && reviewedHkStages.includes(stage)
    && row.action_level === "NO_BUY"
    && ["NO_TRADE", "WATCH_ONLY"].includes(row.trade_status || "")
    && row.status === row.trade_status
    && row.source_mode === "HK_CONNECT_FOUR_LANE";
}
function backfillRowStatusLabel(row: StageRow) {
  const tradeStatus = row.trade_status || "CANNOT_CONFIRM";
  const action = row.action_level === "NO_BUY"
    ? `NO_BUY · ${tradeStatus}`
    : tradeStatus;
  return row.status && row.status !== tradeStatus
    ? `${action} · status ${row.status}`
    : action;
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
  if (value === 0 && row.source_mode === "HK_CONNECT_AUCTION_SECOND_FILTER_STAGE_0925") return "0（原产物；来源字段未核实）";
  return typeof value === "number" && Number.isFinite(value) ? Number(value.toFixed(3)) : "阶段分未在当前阶段生成";
}
function qualityScore(value?: number) {
  return typeof value === "number" ? Number(value.toFixed(3)) : "该时段未提供";
}
function stageCountText(value?: number | null) {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "—";
}
function requestedRowsLabel(value?: number | null) {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "未记录／未绑定";
}
function shouldShowAStageEvidenceGap(summary: MarketSummary, selectedRows?: number) {
  return typeof summary.requested_rows === "number"
    && Number.isFinite(summary.requested_rows)
    && summary.requested_rows > 0
    && summary.source_rows === 0
    && summary.candidate_count === 0
    && selectedRows === 0;
}
function is0920D1ReferenceRow(row: StageRow) {
  return row.source_mode === "HK_CONNECT_D1_PRESELECT_REFERENCE"
    && row.status === "WAITING_0920_SECOND_FILTER";
}
function hkChangeLabel(row: StageRow) {
  return typeof row.d1_change_pct === "number" ? "D-1涨幅" : "阶段涨幅";
}
function hkChangeValue(row: StageRow) {
  if (isPreopenStage.value && is0920D1ReferenceRow(row)) return "D-1参考，待09:20二筛";
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
  navigationStatus.value = `${label}入口保留，业务链路仍在迁移，当前不冒充已完成。`;
}
function isExactCalendarDate(date: string) {
  if (!/^\d{8}$/.test(date)) return false;
  const parsed = new Date(`${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6, 8)}T00:00:00Z`);
  return Number.isFinite(parsed.getTime())
    && parsed.toISOString().slice(0, 10).replaceAll("-", "") === date;
}
function isHistoricalTradingDate(date: string) {
  const anchor = dateData.value.navigation_date || dateData.value.default_date;
  return isExactCalendarDate(date) && Boolean(anchor) && date < anchor;
}
function isAllowedDateForView(date: string) {
  return researchActive.value
    ? isExactCalendarDate(date)
    : tradingDateOptions.value.includes(date) || isHistoricalTradingDate(date);
}
function resolveTradingDate(candidate = selectedDate.value) {
  const options = tradingDateOptions.value;
  return [
    candidate,
    dateData.value.navigation_date,
    dateData.value.default_date,
    ...options,
  ].find((date): date is string =>
    typeof date === "string" && (options.includes(date) || isHistoricalTradingDate(date))
  ) ?? "";
}
function resolveResearchDate(candidate = selectedDate.value) {
  const options = researchDateOptions.value;
  // A requested natural date is not a latest pointer. Missing exact evidence
  // remains visible on that date and is handled by ResearchView's exact mode.
  if (isExactCalendarDate(candidate)) return candidate;
  return [dateData.value.navigation_date, dateData.value.default_date, options.at(-1)]
    .find((date): date is string => typeof date === "string" && isExactCalendarDate(date)) ?? "";
}
type NavigationUrlState = {
  view?: string | null;
  stage?: string | null;
};
function writeNavigationUrl(date: string, state?: NavigationUrlState) {
  if (!/^\d{8}$/.test(date)) return;
  const url = new URL(window.location.href);
  url.searchParams.set("date", date);
  if (state && Object.prototype.hasOwnProperty.call(state, "view")) {
    if (state.view) url.searchParams.set("view", state.view);
    else url.searchParams.delete("view");
  }
  if (state && Object.prototype.hasOwnProperty.call(state, "stage")) {
    if (state.stage) url.searchParams.set("stage", state.stage);
    else url.searchParams.delete("stage");
  }
  const next = `${url.pathname}${url.search}${url.hash}`;
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next === current) return;
  window.history.pushState({}, "", next);
}
function writeSelectedDateToUrl(date: string) {
  writeNavigationUrl(date);
}
function bindSelectedDate(date: string, state?: NavigationUrlState) {
  if (!date) return;
  selectedDate.value = date;
  if (state) writeNavigationUrl(date, state);
  else writeSelectedDateToUrl(date);
}
function openTaskStatus() {
  taskStatusActive.value = true;
  researchActive.value = false;
  researchArchiveEntry.value = false;
  closeReviewActive.value = false;
  navigationStatus.value = "";
}
function openResearch(openWechat = false) {
  taskStatusActive.value = false;
  closeReviewActive.value = false;
  researchActive.value = true;
  researchArchiveEntry.value = openWechat;
  bindSelectedDate(resolveResearchDate(), { view: "research", stage: null });
  navigationStatus.value = "";
}
function openManagerSelection() {
  const suffix = /^\d{8}$/.test(selectedDate.value)
    ? `?date=${encodeURIComponent(selectedDate.value)}`
    : "";
  window.location.assign(`/manager-selection/${suffix}`);
}
function scrollToPool() {
  taskStatusActive.value = false;
  researchActive.value = false;
  bindSelectedDate(resolveTradingDate(), { view: null, stage: selectedStage.value });
  document.querySelector("#unifiedPreselectPanel")?.scrollIntoView({ behavior: "smooth" });
}

async function loadPool(date = selectedDate.value, offset = 0) {
  if (!date) return;
  const version = ++requestVersion;
  const requestedDate = date;
  if (!Number.isInteger(offset) || offset < 0) return;
  poolOffset.value = offset;
  loading.value = true;
  pool.value = null;
  loadError.value = "";
  try {
    const response = await fetch(`/api/v3/preselection-pools?date=${encodeURIComponent(requestedDate)}&limit=200&offset=${offset}`);
    if (!response.ok) throw new Error("request failed");
    const payload = await response.json();
    assertExactResponseDate(payload, requestedDate, ["trade_date", "date", "target_date"], "D-1 预选池");
    if ((offset > 0 && !payload.pagination) || (payload.pagination && payload.pagination.offset !== offset)) throw new Error("分页 offset 与响应不一致，未采用该页");
    if (version === requestVersion && requestedDate === selectedDate.value) pool.value = payload;
  } catch (reason) {
    if (version === requestVersion && requestedDate === selectedDate.value) {
      loadError.value = reason instanceof Error ? reason.message : "D-1 预选池读取失败，请重新选择交易日。";
    }
  } finally {
    if (version === requestVersion && requestedDate === selectedDate.value) loading.value = false;
  }
}

function setStageTimelineSnapshot(stageId: string, snapshot: StageTimelineSnapshot, version?: number) {
  if (snapshot.date !== selectedDate.value) return;
  if (version !== undefined && version !== stageTimelineRequestVersion) return;
  stageSnapshots.value = { ...stageSnapshots.value, [stageId]: snapshot };
}

function timelineStageSnapshot(stageId: string) {
  const snapshot = stageSnapshots.value[stageId];
  return snapshot?.date === selectedDate.value ? snapshot : undefined;
}

function stageBackfillBindings(stageId: string) {
  return approvedStageBackfills.filter((binding) => binding.date === selectedDate.value && binding.stage === stageId);
}

function stageHistoricalDisplayStatus(bindings: readonly ApprovedStageBackfill[]) {
  const snapshots = bindings.map((binding) => approvedBackfillSnapshot(binding));
  if (snapshots.some((snapshot) => !snapshot || snapshot.loading)) return "历史回补读取中（只读）";
  if (snapshots.some((snapshot) => snapshot?.error || !snapshot?.payload)) return "历史回补读取失败 · CANNOT_CONFIRM";
  return "历史回补已恢复（只读）";
}

function stageDisplayStatus(stageId: string) {
  const bindings = stageBackfillBindings(stageId);
  if (bindings.length) return stageHistoricalDisplayStatus(bindings);
  const snapshot = timelineStageSnapshot(stageId);
  if (snapshot?.loading) return "读取中";
  if (snapshot?.error || (snapshot && !snapshot.payload)) return "读取失败/点击重试 · CANNOT_CONFIRM";
  if (snapshot?.payload?.stage?.status || snapshot?.payload?.stage?.display_status) {
    return snapshot.payload.stage.status || snapshot.payload.stage.display_status || "CANNOT_CONFIRM";
  }
  if (stageWorkbench.value?.stage?.stage_id === stageId) {
    return stageWorkbench.value.stage.status || stageWorkbench.value.stage.display_status || "CANNOT_CONFIRM";
  }
  return "读取中";
}

function formalStageDisplayCount(snapshot: StageTimelineSnapshot | undefined, market: CandidateMarketKey) {
  if (!snapshot || snapshot.loading) return "读取中";
  if (snapshot.error || !snapshot.payload) return "读取失败/点击重试";
  const rows = snapshot.payload.unified_rows?.filter((row) => row.market === market) ?? [];
  if (market === "HK") return marketDisplayCount(snapshot.payload.markets?.HK, snapshot.payload.selected_hk_rows, rows.length);
  return String(rows.slice(0, 12).length);
}

function marketDisplayCount(summary: MarketSummary | undefined, selectedRows: number | null | undefined, observedRows: number) {
  if (summary?.display_mode === "CANNOT_CONFIRM") return "待确认/缺少正式产物";
  if (summary?.display_mode === "OBSERVATION_UNVERIFIED") {
    return `${summary.observation_count ?? observedRows} 条观察行 · 未验证`;
  }
  if (summary?.display_mode === "READY_EMPTY") return "0（正式空结果已验证）";
  return stageCountText(selectedRows);
}

function timelineStageMarketCount(stageId: string, market: CandidateMarketKey) {
  if (stageId === "STAGE_1545_1555" && market === "A") return "不适用";
  const binding = stageBackfillBindings(stageId).find((item) => approvedMarketKey(item.market) === market);
  if (binding) {
    const snapshot = approvedBackfillSnapshot(binding);
    if (!snapshot || snapshot.loading) return "读取中";
    if (snapshot.error || !snapshot.payload) return "CANNOT_CONFIRM";
    return String(approvedBackfillRows(binding).length);
  }
  if (stageWorkbench.value?.trade_date === selectedDate.value && stageWorkbench.value.stage.stage_id === stageId) {
    const rows = market === "A" ? aCandidateRows.value : hkCandidateRows.value;
    return market === "HK"
      ? marketDisplayCount(stageWorkbench.value.markets?.HK, stageWorkbench.value.selected_hk_rows, rows.length)
      : String(rows.length);
  }
  return formalStageDisplayCount(timelineStageSnapshot(stageId), market);
}

function timelineStageStatus(stageId: string) {
  const snapshot = timelineStageSnapshot(stageId);
  const bindings = stageBackfillBindings(stageId);
  if (bindings.length) return stageHistoricalDisplayStatus(bindings);
  const formalStatus = !snapshot || snapshot.loading
    ? "读取中"
    : snapshot.error || !snapshot.payload
    ? "读取失败/点击重试"
    : snapshot.payload.stage.status || snapshot.payload.stage.display_status || "CANNOT_CONFIRM";
  return formalStatus;
}

function timelineStageCounts(stageId: string) {
  const snapshot = timelineStageSnapshot(stageId);
  const bindings = stageBackfillBindings(stageId);
  if (bindings.length) {
    const counts = `A股 ${timelineStageMarketCount(stageId, "A")} / 港股通 ${timelineStageMarketCount(stageId, "HK")}`;
    const status = stageHistoricalDisplayStatus(bindings);
    const label = status === "历史回补已恢复（只读）" ? "历史回补·只读" : status;
    return `${counts} · ${label}`;
  }
  if (!snapshot || snapshot.loading) return "读取中";
  if (snapshot.error || !snapshot.payload) return "读取失败/点击重试";
  return `A ${timelineStageMarketCount(stageId, "A")} / HK ${timelineStageMarketCount(stageId, "HK")}`;
}

function stageContextCounts(stageId: string) {
  if (stageBackfillBindings(stageId).length) return timelineStageCounts(stageId);
  return `A股 ${timelineStageMarketCount(stageId, "A")} / 港股 ${timelineStageMarketCount(stageId, "HK")}`;
}

function hasStageTimelineForDate(date: string) {
  return stageDefinitions.every((stage) => stageSnapshots.value[stage.id]?.date === date);
}

async function loadStageTimeline(date: string, currentStage: string, currentPayload: StageWorkbench | null) {
  if (!date || date !== selectedDate.value) return;
  if (backfillRunId.value) {
    stageSnapshots.value = {
      [currentStage]: { date, loading: false, payload: currentPayload ?? undefined },
    };
    return;
  }
  stageTimelineRequestController?.abort();
  const controller = new AbortController();
  stageTimelineRequestController = controller;
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

  const stageLoads = stageDefinitions.map(async (stage) => {
    try {
      const payload = await fetchExactStagePayload(
        stageWorkbenchUrl(date, stage.id),
        controller.signal,
      );
      if (backfillRunId.value) {
        assertBackfillStagePayload(payload, date, stage.id, backfillRunId.value, backfillMarket.value);
      } else {
        assertExactStagePayload(payload, date, stage.id);
      }
      if (version === stageTimelineRequestVersion && date === selectedDate.value) {
        setStageTimelineSnapshot(stage.id, { date, loading: false, payload }, version);
        if (stage.id === selectedStage.value) stageWorkbench.value = payload;
      }
    } catch (reason) {
      if (version === stageTimelineRequestVersion && date === selectedDate.value) {
        const message = reason instanceof Error && reason.message.includes("超时")
          ? "阶段工作台读取超时"
          : "阶段工作台读取失败";
        setStageTimelineSnapshot(stage.id, { date, loading: false, error: message }, version);
      }
    }
  });
  const backfillLoads = approvedStageBackfills
    .filter((binding) => binding.date === date)
    .map(async (binding) => {
      const key = approvedBackfillKey(binding);
      if (approvedBackfillSnapshots.value[key]?.payload) return;
      approvedBackfillSnapshots.value = {
        ...approvedBackfillSnapshots.value,
        [key]: { date, loading: true },
      };
      try {
        const query = new URLSearchParams({
          date: binding.date,
          stage: binding.stage,
          limit: "50",
          backfill_run_id: binding.runId,
          market: binding.market,
        });
        const payload = await fetchExactStagePayload(`/api/v3/workbench/stage?${query.toString()}`, controller.signal);
        assertApprovedStageBackfill(payload, binding);
        if (version === stageTimelineRequestVersion && date === selectedDate.value) {
          approvedBackfillSnapshots.value = {
            ...approvedBackfillSnapshots.value,
            [key]: { date, loading: false, payload },
          };
        }
      } catch {
        if (version === stageTimelineRequestVersion && date === selectedDate.value) {
          approvedBackfillSnapshots.value = {
            ...approvedBackfillSnapshots.value,
            [key]: { date, loading: false, error: "历史回补读取失败" },
          };
        }
      }
    });
  await Promise.all([...stageLoads, ...backfillLoads]);
  if (stageTimelineRequestController === controller) stageTimelineRequestController = null;
}

function stageWorkbenchUrl(date: string, stage: string) {
  const query = new URLSearchParams({ date, stage, limit: "50" });
  if (backfillRunId.value) {
    query.set("backfill_run_id", backfillRunId.value);
    query.set("market", backfillMarket.value);
  }
  return `/api/v3/workbench/stage?${query.toString()}`;
}

async function loadStage(stage = selectedStage.value, preserveRunStatus = false, syncUrl = true) {
  taskStatusActive.value = false;
  researchActive.value = false;
  closeReviewActive.value = false;
  navigationStatus.value = "";
  selectedStage.value = stage;
  const tradingDate = resolveTradingDate();
  if (syncUrl) bindSelectedDate(tradingDate, { view: null, stage });
  else if (tradingDate) selectedDate.value = tradingDate;
  if (!preserveRunStatus) stageRunStatus.value = "";
  if (!selectedDate.value) {
    stageError.value = "请先选择交易日。";
    stageWorkbench.value = null;
    return;
  }
  const requestedDate = selectedDate.value;
  stageRequestController?.abort();
  stageTimelineRequestController?.abort();
  stageTimelineRequestVersion += 1;
  const controller = new AbortController();
  stageRequestController = controller;
  const version = ++stageRequestVersion;
  stageLoading.value = true;
  stageError.value = "";
  stageWorkbench.value = null;
  setStageTimelineSnapshot(stage, { date: requestedDate, loading: true });
  try {
    const url = stageWorkbenchUrl(requestedDate, stage);
    const payload = await fetchExactStagePayload(url, controller.signal);
    if (backfillRunId.value) {
      assertBackfillStagePayload(payload, requestedDate, stage, backfillRunId.value, backfillMarket.value);
    } else {
      assertExactStagePayload(payload, requestedDate, stage);
    }
    if (version === stageRequestVersion && requestedDate === selectedDate.value) {
      stageWorkbench.value = payload;
      setStageTimelineSnapshot(stage, { date: requestedDate, loading: false, payload });
      void loadStageTimeline(requestedDate, stage, payload);
    }
  } catch (reason) {
    if (version === stageRequestVersion && requestedDate === selectedDate.value) {
      stageError.value = reason instanceof Error && reason.message.includes("超时")
        ? "阶段工作台读取超时。"
        : "阶段工作台读取失败。";
      const settled: Record<string, StageTimelineSnapshot> = {};
      for (const definition of stageDefinitions) {
        settled[definition.id] = {
          date: requestedDate,
          loading: false,
          error: definition.id === stage ? stageError.value : "阶段工作台读取失败",
        };
      }
      stageSnapshots.value = settled;
    }
  } finally {
    if (version === stageRequestVersion && requestedDate === selectedDate.value) stageLoading.value = false;
    if (stageRequestController === controller) stageRequestController = null;
  }
}

async function loadCloseReview(
  focus: "A" | "HK" | "research" = reviewFocus.value,
  refresh = false,
  syncUrl = true,
) {
  reviewFocus.value = focus;
  taskStatusActive.value = false;
  researchActive.value = false;
  const tradingDate = resolveTradingDate();
  if (syncUrl) bindSelectedDate(tradingDate);
  else if (tradingDate) selectedDate.value = tradingDate;
  if (!selectedDate.value) return;
  closeReviewActive.value = true;
  // Both views read the same exact envelope, but focus different preserved
  // sections. Switching labels is not a second fetch/generation operation.
  if (!refresh && closeReviewPayload.value?.trade_date === selectedDate.value) return;
  closeReviewLoading.value = true;
  closeReviewError.value = "";
  closeReviewPayload.value = null;
  navigationStatus.value = "";
  const version = ++closeReviewRequestVersion;
  const requestedDate = selectedDate.value;
  const requestedLabel = reviewTitle.value;
  try {
    const payload = await loadReview(requestedDate);
    assertExactResponseDate(payload, requestedDate, ["trade_date"], requestedLabel);
    if (version === closeReviewRequestVersion && requestedDate === selectedDate.value) {
      closeReviewPayload.value = payload;
    }
  } catch (reason) {
    if (version === closeReviewRequestVersion && requestedDate === selectedDate.value) {
      closeReviewError.value = reason instanceof Error ? reason.message : `${requestedLabel}读取失败。`;
    }
  } finally {
    if (version === closeReviewRequestVersion && requestedDate === selectedDate.value) closeReviewLoading.value = false;
  }
}

async function ensureStage(force = false) {
  if (backfillRunId.value) {
    stageError.value = "历史回补只读：不运行或重新物化阶段。";
    return;
  }
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
  abortStageRequests();
  stageRequestVersion += 1;
  stageTimelineRequestVersion += 1;
  stageSnapshots.value = {};
  approvedBackfillSnapshots.value = {};
  stageWorkbench.value = null;
  if (researchActive.value) {
    // Research dates are natural days.  Keep the existing D-1 refresh when
    // browser history changes to a trading date, but never ask the trading
    // pool endpoint to normalize a weekend research date.
    if (tradingDateOptions.value.includes(requestedDate)) {
      await loadPool(requestedDate);
    }
    return;
  } else if (closeReviewActive.value) {
    await Promise.all([loadPool(requestedDate), loadCloseReview()]);
  } else if (backfillRunId.value) {
    pool.value = null;
    await loadStage();
  } else {
    await Promise.all([loadPool(requestedDate), loadStage()]);
  }
}

async function applyNavigationFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const requestedDate = params.get("date") || "";
  const requestedView = params.get("view") || "";
  const requestedStage = params.get("stage") || "";
  const requestedBackfillRunId = params.get("backfill_run_id") || "";
  const requestedBackfillMarket = params.get("market") || "";
  const previousDate = selectedDate.value;
  const previousStage = selectedStage.value;
  const previousBackfillRunId = backfillRunId.value;
  const previousBackfillMarket = backfillMarket.value;
  backfillRunId.value = requestedBackfillRunId;
  backfillMarket.value = requestedBackfillMarket;
  const previousMode = researchActive.value
    ? "research"
    : closeReviewActive.value
    ? "review"
    : "stage";
  const validStage = stageDefinitions.some((stage) => stage.id === requestedStage)
    ? requestedStage
    : selectedStage.value;
  if (stageDefinitions.some((stage) => stage.id === requestedStage)) selectedStage.value = requestedStage;

  if (requestedView === "research") {
    const researchOptionsEmpty = researchDateOptions.value.length === 0;
    const requestedResearchDateAllowed = isExactCalendarDate(requestedDate);
    const resolvedDate = requestedResearchDateAllowed
      ? requestedDate
      : researchOptionsEmpty
      ? resolveTradingDate("")
      : resolveResearchDate("");
    if (!resolvedDate) return;
    const modeChanged = previousMode !== "research";
    const dateChanged = selectedDate.value !== resolvedDate;
    taskStatusActive.value = false;
    closeReviewActive.value = false;
    researchActive.value = true;
    researchArchiveEntry.value = false;
    navigationStatus.value = "";
    selectedDate.value = resolvedDate;
    if (modeChanged || dateChanged) await onDateChange();
    return;
  }

  if (["review", "a-review", "research-review"].includes(requestedView)) {
    const explicitTradingDate = /^\d{8}$/.test(requestedDate)
      && (tradingDateOptions.value.includes(requestedDate) || isHistoricalTradingDate(requestedDate))
      ? requestedDate
      : "";
    selectedDate.value = explicitTradingDate || resolveTradingDate("");
    const focus = requestedView === "research-review" ? "research" : requestedView === "a-review" ? "A" : "HK";
    await Promise.all([loadPool(), loadCloseReview(focus, false, false)]);
    return;
  }

  const explicitTradingDate = /^\d{8}$/.test(requestedDate)
    && (tradingDateOptions.value.includes(requestedDate) || isHistoricalTradingDate(requestedDate))
    ? requestedDate
    : "";
  selectedDate.value = explicitTradingDate || resolveTradingDate("");
  const stageChanged = previousStage !== validStage;
  const dateChanged = previousDate !== selectedDate.value;
  const modeChanged = previousMode !== "stage";
  const backfillChanged = previousBackfillRunId !== backfillRunId.value
    || previousBackfillMarket !== backfillMarket.value;
  if (stageChanged || dateChanged || modeChanged || backfillChanged) {
    taskStatusActive.value = false;
    researchActive.value = false;
    closeReviewActive.value = false;
    navigationStatus.value = "";
    await onDateChange();
  }
}

function onBrowserHistoryChange() {
  void applyNavigationFromUrl();
}

async function selectNextFutureTargetDate() {
  const targetDate = nextFutureTargetDate.value;
  if (!targetDate || !tradingDateOptions.value.includes(targetDate)) return;
  taskStatusActive.value = false;
  researchActive.value = false;
  closeReviewActive.value = false;
  navigationStatus.value = "";
  bindSelectedDate(targetDate, { view: null, stage: selectedStage.value });
  await onDateChange();
}

async function onDateInputChange(event: Event) {
  const input = event.currentTarget as HTMLInputElement;
  const compact = compactDateInput(input.value);
  if (!(researchActive.value ? isExactCalendarDate(compact) : activeDateOptions.value.includes(compact))) {
    input.setCustomValidity(researchActive.value ? "请输入有效自然日；无精确材料时显示未确认" : "请选择日历中的有效交易日");
    input.value = formatDateInput(selectedDate.value);
    input.reportValidity();
    return;
  }
  input.setCustomValidity("");
  selectedDate.value = compact;
  writeSelectedDateToUrl(compact);
  await onDateChange();
}

onMounted(async () => {
  window.addEventListener("popstate", onBrowserHistoryChange);
  try {
    const researchDatesRequest = fetch("/api/v3/research/dates")
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null);
    const [dateList, laneDates] = await Promise.all([
      fetch("/api/v1/runs/date-list").then((r) => (r.ok ? r.json() : Promise.reject(new Error("request failed")))),
      // Ordinary stage navigation must not wait for the optional research lane.
      new URLSearchParams(window.location.search).get("view") === "research"
        ? researchDatesRequest : Promise.resolve(null),
    ]);
    dateData.value = {
      ...dateList,
      // Merge the V3 research-module dates so the date picker can switch to
      // any available research lane date even when the local stage calendar
      // only covers the current day (e.g. a fresh V3.5 data root).
      research_dates: [...new Set([...(dateList.research_dates ?? []), ...((laneDates?.research_dates as string[] | undefined) ?? [])])].sort(),
    };
    void researchDatesRequest.then((extra) => {
      if (!Array.isArray(extra?.research_dates)) return;
      // Late research metadata may extend the picker, never rebind date/stage.
      dateData.value = { ...dateData.value, research_dates: [...new Set([
        ...(dateData.value.research_dates ?? []),
        ...extra.research_dates.filter((date: unknown): date is string => typeof date === "string"),
      ])].sort() };
    });
    const params = new URLSearchParams(window.location.search);
    const requestedDate = params.get("date");
    const requestedStage = params.get("stage");
    const requestedView = params.get("view");
    backfillRunId.value = params.get("backfill_run_id") || "";
    backfillMarket.value = params.get("market") || "";
    if (requestedStage && stageDefinitions.some((stage) => stage.id === requestedStage)) {
      selectedStage.value = requestedStage;
    }
    if (requestedView === "research") {
      const explicitResearchDate = requestedDate
        && isExactCalendarDate(requestedDate)
        ? requestedDate
        : "";
      selectedDate.value = explicitResearchDate || resolveResearchDate(dateData.value.navigation_date || dateData.value.default_date || "");
      openResearch();
    } else if (["review", "a-review", "research-review"].includes(requestedView || "")) {
      const explicitTradingDate = requestedDate
        && /^\d{8}$/.test(requestedDate)
        && (tradingDateOptions.value.includes(requestedDate) || isHistoricalTradingDate(requestedDate))
        ? requestedDate
        : "";
      selectedDate.value = explicitTradingDate || resolveTradingDate(dateData.value.navigation_date || dateData.value.default_date || "");
      await Promise.all([loadPool(), loadCloseReview(requestedView === "research-review" ? "research" : requestedView === "a-review" ? "A" : "HK")]);
    } else {
      const explicitTradingDate = requestedDate
        && /^\d{8}$/.test(requestedDate)
        && (tradingDateOptions.value.includes(requestedDate) || isHistoricalTradingDate(requestedDate))
        ? requestedDate
        : "";
      selectedDate.value = explicitTradingDate || resolveTradingDate(dateData.value.navigation_date || dateData.value.default_date || "");
      if (backfillRunId.value) {
        pool.value = null;
        await loadStage(undefined, false, false);
      } else {
        await Promise.all([loadPool(), loadStage(undefined, false, false)]);
      }
    }
  } catch {
    loadError.value = "交易日目录读取失败。";
    stageError.value = "交易日目录读取失败。";
  }
});

onBeforeUnmount(() => {
  window.removeEventListener("popstate", onBrowserHistoryChange);
});
</script>

<template>
  <main class="dashboard-shell">
    <header class="page-header">
      <div>
        <h1>V4 阶段选股</h1>
        <p>阶段选股只读取同一 date + stage 的 A股与港股通阶段工作台；只读观察，不打开 BUY gate，不接交易接口，不生成 live order。</p>
      </div>
      <span class="runtime-badge">{{ runtimeLabel }}</span>
    </header>

    <section class="control-panel" aria-label="页面控制">
      <label>{{ researchActive ? "研究自然日" : "交易日" }}
        <input
          type="date"
          aria-label="交易日（日历选择）"
          :value="formatDateInput(selectedDate)"
          :min="researchActive ? undefined : dateInputMin"
          :max="researchActive ? undefined : dateInputMax"
          :title="dateInputTitle"
          :disabled="isBackfillReadOnly"
          @change="onDateInputChange"
        />
      </label>
      <button
        v-if="!researchActive && nextFutureTargetDate"
        type="button"
        @click="selectNextFutureTargetDate"
      >查看次日预选池：{{ formatDateInput(nextFutureTargetDate) }}</button>
      <label>阶段
        <select v-model="selectedStage" aria-label="阶段" :disabled="isBackfillReadOnly" @change="loadStage()">
          <option v-for="stage in stageDefinitions" :key="stage.id" :value="stage.id">{{ stage.label }}</option>
        </select>
      </label>
      <button type="button" :disabled="stageLoading || closeReviewLoading" @click="closeReviewActive ? loadCloseReview(reviewFocus, true) : loadStage()">刷新快照</button>
      <span class="runtime-state">{{ researchActive ? "研究入口按自然日导航；阶段入口按A股或港股开市日导航" : "V4 · A/HK按各自市场日历导航；回执不代表进程存活，运行状态见任务页" }}</span>
    </section>

    <p class="date-navigation-identity" role="status">
      当前请求日期：{{ selectedDate || "未指定" }}；
      导航日期：{{ dateData.navigation_date || "未提供" }}；
      证据默认日：{{ dateData.default_date || "未提供" }}。
      研究 latest 仅由研究面板显式选择；缺少所选日材料不表示已更新。
    </p>
    <small class="selected-date-context" data-testid="selected-date-context">{{ selectedDateContext }}</small>
    <a v-if="!isBackfillReadOnly" class="navigation-status" data-testid="raw194-backfill-link" :href="raw194BackfillHref">
      查看历史回补：2026-09-28 · STAGE_0930_0935 · A股 · WATCH_ONLY
    </a>
    <nav v-if="!isBackfillReadOnly" class="entry-nav" aria-label="功能入口">
      <button :class="{ active: !taskStatusActive && !researchActive && !closeReviewActive }" type="button" @click="loadStage()">阶段选股</button>
      <button type="button" @click="scrollToPool()">D-1 预选池</button>
      <button :class="{ active: researchActive }" type="button" @click="openResearch()">研报决策台</button>
      <button type="button" @click="openManagerSelection()">经理选股工作台</button>
      <button :class="{ active: taskStatusActive }" type="button" @click="openTaskStatus()">任务状态</button>
      <button :class="{ active: closeReviewActive && reviewFocus === 'A' }" :aria-pressed="closeReviewActive && reviewFocus === 'A'" type="button" @click="loadCloseReview('A')">A股复盘</button>
      <button class="entry-nav-link" :class="{ active: closeReviewActive && reviewFocus === 'research' }" :aria-pressed="closeReviewActive && reviewFocus === 'research'" type="button" @click="loadCloseReview('research')">研究复盘</button>
      <a class="entry-nav-link" href="http://127.0.0.1:8910/a-share/review" target="_blank" rel="noopener noreferrer">原版 Vibe · 8910</a>
    </nav>
    <p v-if="navigationStatus" class="navigation-status" role="status">{{ navigationStatus }}</p>
    <p v-if="isHkObservationOnlyDate" class="navigation-status hk-observation-status" role="status">
      港股开市 · 港股通/南向暂停，仅作研究观察。若使用最近有效且可追溯的既有标的池，会保留其原始目标日、信号日与 SHA；无有效池则 CANNOT_CONFIRM。A 股仍按 A 股日历独立处理，BUY gate 不变。
    </p>

    <TaskStatusView
      v-if="taskStatusActive"
      :date="selectedDate"
      :stage-summary="stageSummary"
      :current-stage-id="selectedStage"
    />
    <ResearchView
      v-else-if="researchActive"
      :archive-date="selectedDate"
      :initial-feed-filter="researchArchiveEntry ? 'wechat' : 'latest'"
    />
    <template v-else>

    <GlobalIndustryMap v-if="!closeReviewActive && !isBackfillReadOnly" :target-date="selectedDate" />

    <section v-if="!closeReviewActive && !isBackfillReadOnly" class="panel timeline-panel" aria-label="七阶段上下文">
      <div class="section-heading">
        <div><span class="eyebrow">阶段分组主视图</span><h2>七阶段上下文 v2</h2></div>
        <p>{{ selectedDate }} · {{ currentStageDefinition.label }} · {{ stageContextCounts(selectedStage) }}</p>
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
          v-for="(label, index) in closingTimeline" :key="label" type="button"
          :class="{ current: index === 0 && closeReviewActive }"
          @click="index === 0 ? loadCloseReview('HK') : showNavigationStatus(label)"
        >
          <b>{{ label }}</b>
            <span>{{ index === 0 && closeReviewActive ? "已加载指定日期复盘" : (index < 3 ? "复盘入口保留" : "未到验收批次") }}</span>
          <small>{{ index === 0 ? (closeReviewActive ? `${selectedDate} · 只读` : "点击加载只读收盘复盘") : "当前不冒充完成" }}</small>
        </button>
      </div>
    </section>

    <section v-if="!closeReviewActive" class="panel stage-panel">
      <div class="section-heading">
        <div><span class="eyebrow">当前阶段</span><h2>{{ currentStageDefinition.label }} 阶段</h2></div>
        <p v-if="stageWorkbench">{{ stageDisplayStatus(selectedStage) }} · {{ stageWorkbench.stage.window || currentStageDefinition.label }}</p>
      </div>
      <section v-if="isBackfillReadOnly" class="stage-lineage-panel" aria-label="历史回补只读结果" data-testid="backfill-readback">
        <strong>历史回补 · BACKFILL · 只读</strong>
        <p>{{ selectedDate }} · {{ currentStageDefinition.label }} · {{ backfillMarketName }}；本次查询结果填入同一市场的候选卡片栏。</p>
        <details data-testid="backfill-evidence-details">
          <summary>完整来源、run 与缺项证据</summary>
          <p>绑定日期 {{ selectedDate }} · 阶段 {{ selectedStage }} · 市场 {{ backfillMarketName }} · backfill_run_id={{ backfillRunId }}</p>
          <p>SelectionStore run_id={{ backfillArtifactRunId }} · artifact_id={{ backfillMarketSummary.artifact_id || "CANNOT_CONFIRM" }} · raw_artifact_sha256={{ backfillMarketSummary.raw_artifact_sha256 || "CANNOT_CONFIRM" }}</p>
          <p>algorithm_id={{ backfillMarketSummary.algorithm_id || "CANNOT_CONFIRM" }} · algorithm_sha256={{ backfillMarketSummary.algorithm_sha256 || "CANNOT_CONFIRM" }}</p>
          <p>selection={{ backfillMarketSummary.selection_status || "CANNOT_CONFIRM" }} · source={{ backfillMarketSummary.source_status || "CANNOT_CONFIRM" }} · rows={{ backfillMarketSummary.selected_rows ?? 0 }}/{{ backfillMarketSummary.source_rows ?? "CANNOT_CONFIRM" }}</p>
          <p>实际取数开始：{{ backfillEvidenceValue("actual_request_started_at") }}</p>
          <p>实际响应收到：{{ backfillEvidenceValue("actual_response_received_at") }}</p>
          <p>captured_at 语义：{{ backfillEvidenceValue("captured_at_semantics") }}</p>
          <p>RESEARCH_ONLY={{ stageWorkbench?.RESEARCH_ONLY === true }} · production_allowed={{ stageWorkbench?.production_allowed === false ? "false" : "CANNOT_CONFIRM" }} · buy_gate_updated={{ stageWorkbench?.buy_gate_updated === false ? "false" : "CANNOT_CONFIRM" }} · orders_sent={{ stageWorkbench?.orders_sent === false ? "false" : "CANNOT_CONFIRM" }} · write_performed={{ stageWorkbench?.write_performed === false ? "false" : "CANNOT_CONFIRM" }}</p>
          <p>缺少分钟源股票：{{ backfillMissingSymbols.length ? backfillMissingSymbols.join("、") : "CANNOT_CONFIRM" }}</p>
          <details>
            <summary>全部 CANNOT_CONFIRM 缺项（{{ backfillCannotConfirm.length }}）</summary>
            <ol data-testid="backfill-cannot-confirm-list">
              <li v-for="(item, index) in backfillCannotConfirm" :key="`${index}-${item}`" data-testid="backfill-cannot-confirm">{{ item }}</li>
            </ol>
          </details>
          <details>
            <summary>全部 source_evidence（{{ backfillSourceEvidence.length }}）</summary>
            <ul data-testid="backfill-source-evidence-list">
              <li v-for="(item, index) in backfillSourceEvidence" :key="`${index}-${item}`">{{ item }}</li>
            </ul>
          </details>
        </details>
      </section>
      <section
        v-if="!isBackfillReadOnly && currentApprovedBackfills.length"
        class="stage-lineage-panel"
        aria-label="历史回补来源证据"
        data-testid="approved-backfill-readback"
      >
        <strong>已核验历史回补 · BACKFILL · 只读；本区为独立来源证据，普通阶段卡片以各市场栏为准。</strong>
        <details data-testid="approved-backfill-evidence">
          <summary>完整来源、run、取数时间与缺项证据（{{ currentApprovedBackfills.length }} 组）</summary>
          <p>正式阶段状态={{ stageWorkbench?.stage.status || "CANNOT_CONFIRM" }} · 正式显示状态={{ stageWorkbench?.stage.display_status || "CANNOT_CONFIRM" }} · formal run_id={{ stageWorkbench?.run_id || "CANNOT_CONFIRM" }} · selected_rows A/HK={{ stageWorkbench?.selected_a_rows ?? "CANNOT_CONFIRM" }}/{{ stageWorkbench?.selected_hk_rows ?? "CANNOT_CONFIRM" }}。</p>
          <article v-for="binding in currentApprovedBackfills" :key="approvedBackfillKey(binding)" class="stage-lineage-card" :data-testid="`approved-backfill-${binding.market}`">
            <b>{{ approvedMarketName(binding.market) }} · {{ binding.date }} · {{ binding.stage }} · backfill_run_id={{ binding.runId }}</b>
            <template v-if="approvedBackfillSnapshot(binding)?.loading || !approvedBackfillSnapshot(binding)">
              <p role="status">正在读取冻结绑定的历史回补。</p>
            </template>
            <template v-else-if="approvedBackfillSnapshot(binding)?.error || !approvedBackfillSnapshot(binding)?.payload">
              <p role="alert">历史回补读取失败 · CANNOT_CONFIRM。</p>
            </template>
            <template v-else>
              <p>SelectionStore run_id={{ approvedBackfillSnapshot(binding)?.payload?.run_id || "CANNOT_CONFIRM" }} · artifact_id={{ approvedBackfillSnapshot(binding)?.payload?.markets?.[approvedMarketKey(binding.market)]?.artifact_id || "CANNOT_CONFIRM" }} · raw_artifact_sha256={{ approvedBackfillSnapshot(binding)?.payload?.markets?.[approvedMarketKey(binding.market)]?.raw_artifact_sha256 || "CANNOT_CONFIRM" }}</p>
              <p>algorithm_id={{ approvedBackfillSnapshot(binding)?.payload?.markets?.[approvedMarketKey(binding.market)]?.algorithm_id || "CANNOT_CONFIRM" }} · algorithm_sha256={{ approvedBackfillSnapshot(binding)?.payload?.markets?.[approvedMarketKey(binding.market)]?.algorithm_sha256 || "CANNOT_CONFIRM" }}</p>
              <p>selection={{ approvedBackfillSnapshot(binding)?.payload?.markets?.[approvedMarketKey(binding.market)]?.selection_status || "CANNOT_CONFIRM" }} · source={{ approvedBackfillSnapshot(binding)?.payload?.markets?.[approvedMarketKey(binding.market)]?.source_status || "CANNOT_CONFIRM" }} · 历史行数={{ approvedBackfillRows(binding).length }} · {{ approvedBackfillStatusSummary(binding) }}</p>
              <p>实际取数开始：{{ approvedBackfillTimeEvidence(binding, "request") }}</p>
              <p>实际响应收到：{{ approvedBackfillTimeEvidence(binding, "response") }}</p>
              <p>缺项={{ approvedBackfillCannotConfirm(binding).length }} · RESEARCH_ONLY=true · production_allowed=false · buy_gate_updated=false · orders_sent=false。</p>
              <details>
                <summary>全部 CANNOT_CONFIRM 缺项（{{ approvedBackfillCannotConfirm(binding).length }}）</summary>
                <ol :data-testid="`approved-backfill-gaps-${binding.market}`">
                  <li v-for="(item, index) in approvedBackfillCannotConfirm(binding)" :key="`${index}-${item}`">{{ item }}</li>
                </ol>
              </details>
              <details>
                <summary>全部历史来源证据（{{ approvedBackfillSourceEvidence(binding).length }}）</summary>
                <ul>
                  <li v-for="(item, index) in approvedBackfillSourceEvidence(binding)" :key="`${index}-${item}`">{{ item }}</li>
                </ul>
              </details>
            </template>
          </article>
        </details>
      </section>
      <section
        v-if="!isBackfillReadOnly && (stageWorkbench?.markets?.A?.selection_mode === 'BACKFILL' || stageWorkbench?.markets?.HK?.selection_mode === 'BACKFILL')"
        class="stage-lineage-panel"
        aria-label="普通阶段页历史恢复来源"
        data-testid="stage-backfill-consumer-provenance"
      >
        <strong>历史恢复来源 · BACKFILL · 只读</strong>
        <p v-if="stageWorkbench?.markets?.A?.selection_mode === 'BACKFILL'">
          A股 · run={{ stageWorkbench.markets.A.backfill_run_ids?.join("、") || stageWorkbench.markets.A.backfill_run_id || "CANNOT_CONFIRM" }}
          · SelectionStore manifest/receipt={{ stageWorkbench.markets.A.selection_manifest_receipt_verified ? "已验证" : "CANNOT_CONFIRM" }}
          · runner receipt={{ stageWorkbench.markets.A.runner_receipt_status || "CANNOT_CONFIRM" }}
          <template v-if="stageWorkbench.markets.A.runner_receipt_sha256">· SHA={{ stageWorkbench.markets.A.runner_receipt_sha256 }}</template>
        </p>
        <p v-if="stageWorkbench?.markets?.HK?.selection_mode === 'BACKFILL'">
          港股通 · run={{ stageWorkbench.markets.HK.backfill_run_ids?.join("、") || stageWorkbench.markets.HK.backfill_run_id || "CANNOT_CONFIRM" }}
          · SelectionStore manifest/receipt={{ stageWorkbench.markets.HK.selection_manifest_receipt_verified ? "已验证" : "CANNOT_CONFIRM" }}
          · runner receipt={{ stageWorkbench.markets.HK.runner_receipt_status || "CANNOT_CONFIRM" }}
          <template v-if="stageWorkbench.markets.HK.runner_receipt_sha256">· SHA={{ stageWorkbench.markets.HK.runner_receipt_sha256 }}</template>
        </p>
      </section>
      <div class="stage-actions">
        <button type="button" :disabled="isBackfillReadOnly || stageLoading || !selectedDate" @click="ensureStage(false)">运行 / 恢复当前阶段</button>
        <button type="button" :disabled="isBackfillReadOnly || stageLoading || !selectedDate" @click="ensureStage(true)">强制重新物化</button>
        <span v-if="referenceMode" class="reference-label">参考快照 · WATCH_ONLY</span>
        <span v-if="stageRunStatus">最近运行：{{ stageRunStatus }}</span>
      </div>
      <details
        v-if="!isBackfillReadOnly && currentApprovedBackfills.length && stageWorkbench?.execution_evidence"
        data-testid="formal-execution-evidence"
      >
        <summary>正式阶段执行证据（历史回补期间默认折叠）</summary>
        <StageExecutionEvidencePanel :evidence="stageWorkbench.execution_evidence" />
      </details>
      <StageExecutionEvidencePanel v-else-if="!isBackfillReadOnly && stageWorkbench?.execution_evidence" :evidence="stageWorkbench.execution_evidence" />
      <section v-if="!isBackfillReadOnly && (!stageWorkbench?.execution_evidence || stageWorkbench?.stage_lineage)" class="stage-lineage-panel" aria-label="阶段运行血缘">
        <strong>阶段运行血缘</strong>
        <div v-if="stageWorkbench?.stage_lineage" class="stage-lineage-grid">
          <article v-if="stageWorkbench.stage_lineage.natural" class="stage-lineage-card">
            <b>{{ stageWorkbench.stage_lineage.natural.label || "ORIGINAL_NATURAL_RUN" }}</b>
            <span>status={{ stageWorkbench.stage_lineage.natural.status || "CANNOT_CONFIRM" }}</span>
            <span>origin={{ stageWorkbench.stage_lineage.natural.origin || "ORIGINAL_NATURAL_RUN" }}</span>
            <span>receipt_sha256</span><code>{{ stageWorkbench.stage_lineage.natural.receipt_sha256 || "CANNOT_CONFIRM" }}</code>
            <span>write={{ stageWorkbench.stage_lineage.natural.write_performed === true ? "true" : "false" }}</span>
          </article>
          <article v-if="stageWorkbench.stage_lineage.recovery" class="stage-lineage-card">
            <b>{{ stageWorkbench.stage_lineage.recovery.label || "CONTROLLED_RECOVERY" }}</b>
            <span>status={{ stageWorkbench.stage_lineage.recovery.status || "CANNOT_CONFIRM" }}</span>
            <span>origin={{ stageWorkbench.stage_lineage.recovery.origin || "CONTROLLED_RECOVERY" }}</span>
            <span>receipt_sha256</span>
            <code v-if="stageWorkbench.stage_lineage.recovery.receipt_sha256">{{ stageWorkbench.stage_lineage.recovery.receipt_sha256 }}</code>
            <template v-else-if="stageWorkbench.stage_lineage.recovery.receipt_sha256_by_market">
              <code v-for="(sha, market) in stageWorkbench.stage_lineage.recovery.receipt_sha256_by_market" :key="market">{{ market }}={{ sha }}</code>
            </template>
            <code v-else>CANNOT_CONFIRM</code>
            <span>write={{ stageWorkbench.stage_lineage.recovery.write_performed === true ? "true" : "false" }}</span>
          </article>
        </div>
        <p v-else class="evidence-gap">CANNOT_CONFIRM：当前响应未提供可验证的 natural/recovery receipt 血缘。</p>
        <p v-if="stageWorkbench?.stage_lineage?.cannot_confirm?.length" class="evidence-gap">
          {{ stageWorkbench.stage_lineage.cannot_confirm.join("、") }}
        </p>
      </section>
      <div v-if="!isBackfillReadOnly && v11OpeningFilter" class="model-contract" aria-label="竞价二筛模型">
        <strong>v1.1 竞价二筛</strong>
        <span>v1.1 A股适配器，不是港股精确公式</span>
        <code>{{ v11OpeningFilter.model_id }}</code>
        <small>
          <span>港股 {{ v11OpeningFilter.markets?.HK?.refresh_time || "09:20" }} 刷新 · A股 {{ v11OpeningFilter.markets?.A?.refresh_time || "09:25" }} 刷新</span>
          · 上游预选 {{ aSummary.requested_rows ?? "不可确认" }} / 同截点证据 {{ aSummary.source_rows ?? "不可确认" }} / 阶段候选 {{ aSummary.candidate_count ?? "不可确认" }} / 入选 {{ stageWorkbench?.selected_a_rows ?? "不可确认" }}
        </small>
      </div>
      <p v-if="!isBackfillReadOnly && v11OpeningFilter && showAStageEvidenceGap" class="evidence-note">A股股票仍保留在独立 D-1 池；没有伪造阶段候选。</p>
      <p v-if="currentApprovedBackfills.length" class="stage-display-status">
        {{ stageDisplayStatus(selectedStage) }} · 卡片来源以各市场栏标注为准；历史回补证据独立保留，不代表自然采集或正式当前结果。
      </p>
      <p v-else-if="stageLoading" role="status">正在读取 {{ selectedDate }} / {{ selectedStage }}。</p>
      <p v-else-if="stageError" role="alert">{{ stageError }}</p>
      <p v-else-if="stageWorkbench" class="stage-display-status">
        {{ stageWorkbench.stage.display_status }}
      </p>

      <div class="market-columns">
        <section v-if="!isHkOnlyStage" class="market-column" aria-label="A股候选" data-testid="stage-candidates-A">
          <div class="market-title"><h3>A股</h3><span>{{ candidateColumnCountLabel("A") }}<template v-if="candidateRowsAreHistorical('A')"> · 历史回补·只读</template></span></div>
          <div v-if="!aCandidateRows.length" class="empty-card">
            <strong>{{ candidateColumnEmptyMessage("A") }}</strong>
            <template v-if="!candidateRowsAreHistorical('A')">
              <span>{{ currentStageDefinition.label }} 阶段 · source rows {{ stageCountText(aSummary.source_rows) }} / requested {{ requestedRowsLabel(aSummary.requested_rows) }}</span>
              <p>{{ stageWorkbench?.stage.display_status || "该阶段数据尚未进入 V3.5。" }}</p>
            </template>
          </div>
          <article v-for="row in aCandidateRows" :key="`${candidateCodeValue(row, 'A')}-${candidateRankValue(row, 'A')}`" class="candidate-card">
            <div class="candidate-head"><div><strong>{{ candidateNameValue(row, "A") }}</strong><span>{{ candidateCodeValue(row, "A") }} · 排名 {{ candidateRankValue(row, "A") }}</span></div><b>{{ candidateActionLabel(row, "A") }}</b></div>
            <dl>
              <div><dt>涨幅</dt><dd>{{ candidateChangeValue(row, "A") }}</dd></div>
              <div><dt>阶段分</dt><dd>{{ candidateScoreValue(row, "A") }}</dd></div>
              <div><dt>新闻分</dt><dd>{{ candidateQualityValue(row.news_quality_score, "A") }}</dd></div>
              <div><dt>研报分</dt><dd>{{ candidateQualityValue(row.research_quality_score, "A") }}</dd></div>
              <div><dt>支撑位</dt><dd>{{ candidateEvidenceValue(rowSupport(row), "A") }}</dd></div>
              <div><dt>压力位</dt><dd>{{ candidateEvidenceValue(rowPressure(row), "A") }}</dd></div>
              <div><dt>失效位</dt><dd>{{ candidateEvidenceValue(rowInvalidation(row), "A") }}</dd></div>
              <div><dt>{{ candidateRowsAreHistorical("A") || row.next_validation_time ? "所选阶段计划验证" : "数据截止" }}</dt><dd>{{ candidateValidationValue(row, "A") }}</dd></div>
            </dl>
          </article>
        </section>
        <section v-else-if="!isBackfillReadOnly" class="market-column" aria-label="A股不适用"><h3>A股：不适用</h3><p>所选15:45—15:55阶段仅适用于港股通，不代表A股零结果或采集失败。</p></section>
        <section class="market-column" :aria-label="hkSummary.display_mode === 'OBSERVATION_UNVERIFIED' ? '港股通观察行' : '港股通候选'" data-testid="stage-candidates-HK">
          <div class="market-title"><h3>{{ hkSummary.display_mode === "OBSERVATION_UNVERIFIED" ? "港股通观察行" : `港股通${isPreopenStage ? "09:20二筛" : "二筛"}` }}</h3><span>{{ candidateColumnCountLabel("HK") }}<template v-if="candidateRowsAreHistorical('HK')"> · 历史回补·只读</template></span></div>
          <p v-if="hkSummary.display_mode === 'OBSERVATION_UNVERIFIED'" class="evidence-note">未验证原因：{{ hkSummary.display_reasons?.join("、") || "SelectionStore 或执行绑定不足" }}</p>
          <div v-if="!hkCandidateRows.length" class="empty-card">
            <strong>{{ candidateColumnEmptyMessage("HK") }}</strong>
            <p v-if="!candidateRowsAreHistorical('HK')">{{ stageWorkbench?.stage.display_status || "该阶段数据尚未进入 V3.5。" }}</p>
          </div>
          <p v-if="isPreopenStage && hkCandidateRows.length && !candidateRowsAreHistorical('HK')" class="evidence-note">09:20阶段只做初筛；支撑/压力/失效位从09:30后阶段生成。</p>
          <article v-for="row in hkCandidateRows" :key="`${candidateCodeValue(row, 'HK')}-${candidateRankValue(row, 'HK')}`" class="candidate-card">
            <div class="candidate-head"><div><strong>{{ candidateNameValue(row, "HK") }}</strong><span>{{ candidateCodeValue(row, "HK") }} · 排名 {{ candidateRankValue(row, "HK") }}</span></div><b>{{ candidateActionLabel(row, "HK") }}</b></div>
            <dl>
              <div><dt>{{ hkChangeLabel(row) }}</dt><dd>{{ candidateChangeValue(row, "HK") }}</dd></div>
              <div><dt>{{ hkScoreLabel(row) }}</dt><dd>{{ candidateScoreValue(row, "HK") }}</dd></div>
              <div v-if="isPreopenStage"><dt>快照涨幅</dt><dd>{{ typeof row.current_change_pct === "number" && Number.isFinite(row.current_change_pct) ? formatPercent(row.current_change_pct) : "当前阶段未提供快照涨幅" }}</dd></div>
              <div v-if="!isPreopenStage"><dt>支撑位</dt><dd>{{ candidateEvidenceValue(row.support_primary_price, "HK") }}</dd></div>
              <div v-if="!isPreopenStage"><dt>压力位</dt><dd>{{ candidateEvidenceValue(row.pressure_price, "HK") }}</dd></div>
              <div v-if="!isPreopenStage"><dt>失效位</dt><dd>{{ candidateEvidenceValue(row.invalidation_price, "HK") }}</dd></div>
              <div><dt>所选阶段计划验证</dt><dd>{{ selectedDate }} · {{ candidateValidationValue(row, "HK") }}</dd></div>
            </dl>
            <p v-if="!isPreopenStage && !candidateRowsAreHistorical('HK') && rowMissingFields(row).length" class="evidence-gap">待补字段：{{ rowMissingFields(row).join("、") }}</p>
          </article>
        </section>
      </div>
    </section>

    <section v-else class="review-panel" :aria-label="reviewFocus === 'HK' ? '16:08 港股通收盘复盘' : reviewTitle">
      <div class="section-heading">
        <div><span class="eyebrow">EXACT_DATE_REVIEW</span><h2>{{ reviewTitle }}</h2></div>
        <p>{{ closeReview.trade_date || closeReviewPayload?.trade_date || selectedDate }} · 只读，不回填 BUY gate</p>
      </div>
      <p v-if="closeReviewLoading" class="review-loading" role="status">正在读取 {{ selectedDate }} 的{{ reviewTitle }}。</p>
      <p v-else-if="closeReviewError" class="review-loading error" role="alert">{{ closeReviewError }}</p>
      <ReviewView v-else-if="closeReviewPayload" :payload="closeReviewPayload" :focus="reviewFocus" />
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
                <td>{{ row.rank ?? "-" }}</td><td>{{ row.code || "-" }}</td><td>{{ row.name || "-" }}</td>
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

    <section v-if="!isBackfillReadOnly" id="unifiedPreselectPanel" class="panel pool-panel" aria-label="统一预选池">
      <div class="section-heading"><div><span class="eyebrow">D-1 数据</span><h2>D-1 预选池</h2></div><p>{{ pool?.data_status || "等待读取" }}</p></div>
      <nav aria-label="D1名单分页" class="pool-page-controls">
        <button type="button" :disabled="loading || poolOffset === 0" @click="loadPool(selectedDate, Math.max(0, poolOffset - 200))">上一页</button>
        <span>显示第 {{ Math.floor(poolOffset / 200) + 1 }} 页 · 每个池独立分页，每页最多200行；不截断选股输入</span>
        <button v-if="pool?.pagination?.has_more && typeof pool.pagination.next_offset === 'number'" type="button" :disabled="loading" @click="loadPool(selectedDate, pool.pagination.next_offset)">下一页／查看余下名单</button>
      </nav>
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
          <p v-if="group.pool_id === 'a_all_pool_summary'" class="preview-note">只要汇总池有股票即可进行阶段选股，无需所有子池齐全。</p>
          <p v-if="group.status" class="preview-note"><strong>{{ group.status }}</strong><span v-if="poolEvidenceReason(group)"> · {{ poolEvidenceReason(group) }}</span></p>
          <details v-if="group.cannot_confirm?.length || group.source_path" class="preview-note">
            <summary>来源与更新缺口（不阻断其他有效池）</summary>
            <p>所选目标日：{{ selectedDate }} · producer：{{ group.producer_id || "未确认" }}</p>
            <p>来源路径：{{ group.source_path || "未提供可核验来源路径" }}</p>
            <p v-for="(item, index) in poolEvidenceDetails(group)" :key="index">{{ typeof item === "string" ? item : item.reason || item.description || "CANNOT_CONFIRM" }}</p>
            <p v-if="['a_d1_fupan_watchlist_pool', 'a_d1_stage7_fenshi_review_pool'].includes(group.pool_id)">应消费前一交易日收盘/Stage原始证据，经既有17:30/18:00预选池链物化；缺输入不复制旧目标日行，也不手改status。恢复步骤见本机缺口清单。</p>
            <p v-if="group.pool_id === 'wechat_public_account_v3_preselect'">既有公众号同步计划09:01/20:01；须核对文章发布日、effective_date、原始输入与回执，空列表不代表已更新。</p>
            <p v-if="group.pool_id === 'a_share_baimao_research_map'">白毛池依赖已发布observations及精确日期映射；当前更新时刻未取证，不以latest名称代替日期验证。</p>
          </details>
          <p v-if="!collapsedPools[group.pool_id] && isWechatPool(group) && !poolRows(group).length" class="evidence-note">
            公众号旧池未生成/待补齐；报告与全文提及尚未接入阶段候选，不把 mentions 直接当候选或评分。
          </p>
          <p v-if="isWechatPool(group) && poolRows(group).length" class="preview-note">
            公众号旧池行仅供来源核对；报告与全文提及不直接进入阶段候选或评分。
          </p>
          <p v-if="!collapsedPools[group.pool_id] && isBaimaoPool(group) && !poolRows(group).length" class="evidence-note">
            白毛卡点研究映射暂无已核验行；不生成候选或评分，保留原池边界。
          </p>
          <button
            v-if="isWechatPool(group)"
            type="button"
            class="pool-entry-button"
            data-testid="open-wechat-archive"
            @click="openResearch(true)"
          >打开公众号研究归档</button>
          <WechatMentionPool
            v-if="isWechatPool(group) && canLoadWechatMentions && !collapsedPools[group.pool_id]"
            :article-date="selectedDate"
            @open-report="openResearch(true)"
          />
          <div v-if="!collapsedPools[group.pool_id] && !isCompactResearchPool(group)" class="review-table-wrap">
            <table>
              <thead><tr><th>池内排名</th><th>代码</th><th>名称</th><th>来源/状态</th><th>信号日</th><th>池评分</th></tr></thead>
              <tbody>
                <tr v-for="row in poolRows(group)" :key="`${group.pool_id}-${poolRowCode(row)}-${row.pool_rank ?? 0}`">
                  <td>{{ row.pool_rank ?? "-" }}</td><td>{{ poolRowCode(row) }}</td><td>{{ poolRowName(row) }}</td>
                  <td :title="poolRowSourceLane(row)">{{ poolRowSource(row, group) }}</td><td>{{ poolRowSignalDate(row) }}</td><td>{{ row.pool_score ?? "-" }}</td>
                </tr>
                <tr v-if="!poolRows(group).length"><td colspan="6">{{ (group.pool_size ?? 0) > 0 && poolOffset > 0 ? "本页没有该池的行，可返回上一页查看；不代表来源缺失。" : "该池当前无可确认行；保留原池边界，不与其他池合并。" }}</td></tr>
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
