
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import type { StageSummary } from "../components/review/StageSummaryPanel.vue";
import { loadReview } from "../api/review";
import { loadPoolSnapshot, loadStageSnapshot, projectSummaryPoolPage, POOL_PAGE_SIZE } from "../api/pool_stage";
import type { ReviewEnvelope } from "../contracts/review";
import type { DateResponse, ModelSelectionReview, NavigationUrlState, PoolGroup, PoolResponse, StageRow, StageTimelineSnapshot, StageWorkbench } from "./types";

import { poolRows, poolEvidenceReason, poolEvidenceDetails, poolRowCode, poolRowName, poolRowSource, poolRowSourceLane, poolCountLabel, poolRowSignalDate, formatPercent, assertExactResponseDate, formatDateInput, compactDateInput, evidenceValue, rowCode, rowName, rowRank, aShareChangePct, rowSupport, rowPressure, rowInvalidation, rowNextEvidence, rowScore, qualityScore, stageCountText, stageMarketStateText, stageMarketCountText, hasExactMissingStageReceipt, exactMissingStageReceiptMessage, is0920D1ReferenceRow, hkChangeLabel, rowMissingFields, hitTop20, reviewClassification } from "./formatters";
import { createTimeline, projectClosingTimeline, nextClosingStatusDelay } from "./timeline";
import { loadTaskStatus } from "../api/runtime";
import { frontendBuildIdentity, loadedFrontendScript } from './buildIdentity';
import type { TaskStatusResponse } from "../contracts/runtime";

export function useAppShell() {
  const { stageDefinitions, closingTimeline: closingDefinitions } = createTimeline();
  const closingStatus = ref<TaskStatusResponse | null>(null);
  const closingTimeline = computed(() => projectClosingTimeline(closingDefinitions, closingStatus.value, selectedDate.value));
  let closingRequestVersion = 0;
  let closingController: AbortController | null = null;
  let closingRefreshTimer: ReturnType<typeof setTimeout> | null = null;
  async function loadClosingStatus() {
    const version = ++closingRequestVersion;
    closingController?.abort();
    if (closingRefreshTimer !== null) clearTimeout(closingRefreshTimer);
    closingRefreshTimer = null;
    closingStatus.value = null;
    if (!/^\d{8}$/.test(selectedDate.value)) return;
    const date = selectedDate.value;
    closingController = new AbortController();
    try {
      const result = await loadTaskStatus(date, closingController.signal);
      if (version === closingRequestVersion && selectedDate.value === date && result.business_date === date) {
        closingStatus.value = result;
        const delay = nextClosingStatusDelay(result, date);
        if (delay !== null) closingRefreshTimer = setTimeout(() => { void loadClosingStatus(); }, delay);
      }
    } catch {
      // Missing/failed evidence remains CANNOT_CONFIRM for this date.
    }
  }


const selectedDate = ref("");
const dateData = ref<DateResponse>({ default_date: "", stage_dates: [], future_target_dates: [] });
const pool = ref<PoolResponse | null>(null);
const loading = ref(false);
const loadError = ref("");
let requestVersion = 0;
let poolRequestController: AbortController | null = null;
let loadedPoolDate = "";
const poolPageOffset = ref(0);
let firstPoolPage: PoolResponse | null = null;
watch(selectedDate, (date, previousDate) => {
  if (previousDate && date !== previousDate) poolPageOffset.value = 0;
  void loadClosingStatus();
}, { flush: "sync" });
const selectedStage = ref(stageDefinitions[0].id);
const stageWorkbench = ref<StageWorkbench | null>(null);
const stageLoading = ref(false);
const stageError = ref("");
const stageSnapshots = ref<Record<string, StageTimelineSnapshot>>({});
const stageRunStatus = ref("");
const navigationStatus = ref("");
const taskStatusActive = ref(false);
const researchActive = ref(false);
const researchArchiveEntry = ref(false);
const closeReviewActive = ref(false);
const reviewFocus = ref<"A" | "HK" | "research">("HK");
const reviewTitle = computed(() => ({ A: "A股复盘", HK: "16:10 港股通模型选股收盘复盘", research: "研究复盘" })[reviewFocus.value]);
const runtimeLabel = computed(() => {
  const identity = dateData.value.runtime_identity;
  return identity?.status === "MANIFEST_EXECUTION_FILES_VERIFIED"
    ? `V4 · ${identity.release_id} · manifest/执行文件已核验`
    : "V4 · 运行版本 CANNOT_CONFIRM";
});
const frontendIdentity = ref({status:'CANNOT_CONFIRM',message:'前端构建身份待确认'});
async function loadFrontendIdentity() {
  try {
    const response=await fetch('/api/v4/runtime-graph/frontend-build',{cache:'no-store'});
    frontendIdentity.value=frontendBuildIdentity(loadedFrontendScript,response.ok?await response.json():null);
  } catch { frontendIdentity.value=frontendBuildIdentity(loadedFrontendScript,null); }
}
function refreshFrontend() { window.location.reload(); }
const closeReviewLoading = ref(false);
const closeReviewError = ref("");
const closeReviewPayload = ref<ReviewEnvelope | null>(null);
let closeReviewRequestVersion = 0;
let stageRequestVersion = 0;
let stageTimelineRequestVersion = 0;
let stageRequestController: AbortController | null = null;
let stageTimelineRequestController: AbortController | null = null;
let userDateIntentVersion = 0;
let userStageIntentVersion = 0;

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
const nextFutureTargetDate = computed(() => {
  const targets = [...new Set(dateData.value.future_target_dates ?? [])]
    .filter((date): date is string => /^\d{8}$/.test(date))
    .sort();
  const anchor = dateData.value.navigation_date || dateData.value.default_date;
  return targets.find((date) => !anchor || date > anchor) ?? "";
});
const nextHkTargetDate = computed(() => {
  const targets = [...new Set(dateData.value.hk_observation_only_dates ?? [])]
    .filter((date): date is string => /^\d{8}$/.test(date))
    .sort();
  const anchor = dateData.value.navigation_date || dateData.value.default_date;
  return targets.find((date) => !anchor || date > anchor) ?? "";
});
const selectedDateContext = computed(() => {
  if (!selectedDate.value) return "请选择交易日。";
  const formattedDate = formatDateInput(selectedDate.value);
  if (researchActive.value) return `当前查看研究自然日：${formattedDate}`;
  if ((dateData.value.future_target_dates ?? []).includes(selectedDate.value)) {
    const targetLabel = selectedDate.value === nextFutureTargetDate.value
      ? "次日预选池准备（未开盘）"
      : "未来目标日预选池准备（未开盘）";
    return `当前查看目标日：${formattedDate} · ${targetLabel}`;
  }
  return `当前查看交易日：${formattedDate}`;
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
    ? selectedDate.value === nextFutureTargetDate.value
      ? "次日选股池准备（未开盘）"
      : "未来目标日选股池准备（未开盘）"
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
const aPoolTotal = computed(() => pool.value?.a_all_pool_row_count ?? pool.value?.market_totals?.A ?? aPoolRows.value.length);
const hkPoolTotal = computed(() => pool.value?.market_totals?.HK ?? hkPoolRows.value.length);
const aPoolPageNumber = computed(() => Math.floor(poolPageOffset.value / POOL_PAGE_SIZE) + 1);
const aPoolPageCount = computed(() => Math.max(1, Math.ceil(aPoolTotal.value / POOL_PAGE_SIZE)));
const aPoolPageLabel = computed(() =>
  `第 ${aPoolPageNumber.value} / ${aPoolPageCount.value} 页 · 本页 ${aPoolRows.value.length} / 共 ${aPoolTotal.value} 条`,
);
const aPoolPreviousOffset = computed(() => poolPageOffset.value > 0 ? Math.max(0, poolPageOffset.value - POOL_PAGE_SIZE) : null);
const aPoolNextOffset = computed(() => {
  const page = pool.value?.pagination;
  if (page) return page.has_more && page.next_offset !== null ? page.next_offset : null;
  return poolPageOffset.value + aPoolRows.value.length < aPoolTotal.value
    ? poolPageOffset.value + POOL_PAGE_SIZE
    : null;
});
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
      has_more: pool.value?.pagination?.arrays?.a_all_pool_rows?.has_more,
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
function isWechatPool(group: PoolGroup) {
  return group.pool_id === "wechat_public_account_v3_preselect";
}
function isBaimaoPool(group: PoolGroup) {
  return group.pool_id === "a_share_baimao_research_map";
}
function isCompactResearchPool(group: PoolGroup) {
  return (isWechatPool(group) || isBaimaoPool(group)) && poolRows(group).length === 0;
}
const referenceMode = computed(() =>
  stageWorkbench.value?.selection_mode === "MIGRATED_REFERENCE_WORKBENCH",
);
const missingStageReceiptMessage = computed(() =>
  exactMissingStageReceiptMessage(stageWorkbench.value, selectedDate.value, selectedStage.value),
);
const hasMissingStageReceipt = computed(() => Boolean(missingStageReceiptMessage.value));
const v11OpeningFilter = computed(() =>
  isPreopenStage.value
  && stageWorkbench.value?.selection_mode === "V1_1_CHAMPION_DUAL_MARKET"
    ? stageWorkbench.value.opening_second_filter
    : undefined,
);
const phaseStatus = computed(() => {
  if (referenceMode.value) return "参考快照";
  return `A ${stageMarketStateText(stageWorkbench.value, "A")} / HK ${stageMarketStateText(stageWorkbench.value, "HK")}`;
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
    selected_a_rows: hasExactMissingStageReceipt(workbench, selectedDate.value, selectedStage.value)
      ? null
      : workbench.selected_a_rows,
    a_source_rows: aSummary.value.source_rows,
    a_candidate_count: aSummary.value.candidate_count,
    a_market_state_label: stageMarketStateText(workbench, "A"),
    hk_market_state_label: stageMarketStateText(workbench, "HK"),
    selected_hk_rows: workbench.selected_hk_rows,
    hk_candidate_count: hkSummary.value.candidate_count,
    reference_mode: referenceMode.value,
    selected_total_rows: workbench.selected_total_rows,
    data_level: hkSummary.value.data_level || aSummary.value.data_level,
  };
});
const aSummary = computed(() => stageWorkbench.value?.markets?.A ?? {});
const hkSummary = computed(() => stageWorkbench.value?.markets?.HK ?? {});
const aMarketStateText = computed(() => stageMarketStateText(stageWorkbench.value, "A"));
const hkMarketStateText = computed(() => stageMarketStateText(stageWorkbench.value, "HK"));
const showAStageEvidenceGap = computed(() =>
  (aSummary.value.requested_rows ?? 0) > 0
  && aSummary.value.source_rows === 0
  && aSummary.value.candidate_count === 0
  && stageWorkbench.value?.selected_a_rows === 0,
);
const closeReview = computed(() =>
  (closeReviewPayload.value?.market_reviews.HK.model_selection_review ?? {}) as ModelSelectionReview,
);
const modelMetric = computed(() => closeReview.value.models?.["0.2_prob_active"] ?? {});
const stageUnionMetric = computed(() => closeReview.value.stage_union ?? {});
const closeReviewEvidenceLabel = computed(() => {
  if (closeReview.value.evidence_mode === "V3_5_NATIVE_PRODUCTION") return "V4 原生收盘证据";
  return "收盘证据未导入";
});
const reviewEvidenceGaps = computed(() =>
  [...new Set([...(closeReview.value.missing_stages ?? []), ...(closeReview.value.cannot_confirm ?? [])])],
);

function abortStageRequests() {
  stageRequestController?.abort();
  stageTimelineRequestController?.abort();
  stageRequestController = null;
  stageTimelineRequestController = null;
}
function hkChangeValue(row: StageRow) {
  if (isPreopenStage.value && is0920D1ReferenceRow(row)) return "D-1参考，待09:20二筛";
  return formatPercent(row.d1_change_pct ?? row.current_change_pct);
}
function hkScoreLabel(row: StageRow) {
  return isPreopenStage.value && is0920D1ReferenceRow(row) ? "D-1参考分" : "二筛分";
}
function showNavigationStatus(label: string) {
  taskStatusActive.value = false;
  researchActive.value = false;
  navigationStatus.value = `${label}入口保留，业务链路仍在迁移，当前不冒充已完成。`;
}
function isHistoricalTradingDate(date: string) {
  const anchor = dateData.value.navigation_date || dateData.value.default_date;
  return /^\d{8}$/.test(date) && Boolean(anchor) && date < anchor;
}
function isAllowedDateForView(date: string) {
  return researchActive.value
    ? activeDateOptions.value.includes(date)
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
  if (!options.length) return /^\d{8}$/.test(candidate) ? candidate : "";
  return [candidate, options.at(-1), dateData.value.navigation_date, dateData.value.default_date]
    .find((date): date is string => typeof date === "string" && options.includes(date)) ?? options.at(-1) ?? "";
}
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
  document.querySelector("#unifiedPreselectPanel")?.scrollIntoView?.({ behavior: "smooth" });
}

async function loadPool(date = selectedDate.value, offset?: number) {
  if (!date) return;
  const requestedOffset = date === loadedPoolDate ? offset ?? poolPageOffset.value : 0;
  if (date !== loadedPoolDate) { poolPageOffset.value = 0; firstPoolPage = null; }
  const version = ++requestVersion;
  const requestedDate = date;
  poolRequestController?.abort();
  const controller = new AbortController();
  poolRequestController = controller;
  loading.value = true;
  pool.value = null;
  loadError.value = "";
  try {
    let payload = await loadPoolSnapshot(requestedDate, requestedOffset, controller.signal);
    if (version !== requestVersion || requestedDate !== selectedDate.value) return;
    let settledOffset = requestedOffset;
    if (requestedOffset > 0) {
      const projected = projectSummaryPoolPage(firstPoolPage, payload);
      if (projected) payload = projected;
      else {
        firstPoolPage = null;
        payload = await loadPoolSnapshot(requestedDate, 0, controller.signal);
        settledOffset = 0;
      }
    }
    if (version === requestVersion && requestedDate === selectedDate.value) {
      if (settledOffset === 0) firstPoolPage = payload;
      pool.value = payload;
      poolPageOffset.value = settledOffset;
      loadedPoolDate = requestedDate;
    }
  } catch (reason) {
    if (version === requestVersion && requestedDate === selectedDate.value) {
      loadError.value = reason instanceof Error ? reason.message : "D-1 预选池读取失败，请重新选择交易日。";
    }
  } finally {
    if (version === requestVersion && requestedDate === selectedDate.value) loading.value = false;
    if (poolRequestController === controller) poolRequestController = null;
  }
}

function loadPoolPage(offset: number | null) {
  if (offset === null || !Number.isSafeInteger(offset) || offset < 0 || !selectedDate.value) return;
  void loadPool(selectedDate.value, offset);
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

function timelineStageStatus(stageId: string) {
  const snapshot = timelineStageSnapshot(stageId);
  if (!snapshot || snapshot.loading) return "读取中";
  if (snapshot.error || !snapshot.payload) return "读取失败/点击重试";
  return snapshot.payload.stage.status || snapshot.payload.stage.display_status || "CANNOT_CONFIRM";
}

function timelineStageCounts(stageId: string) {
  const snapshot = timelineStageSnapshot(stageId);
  if (!snapshot || snapshot.loading) return "读取中";
  if (snapshot.error || !snapshot.payload) return "读取失败/点击重试";
  return `A ${stageMarketStateText(snapshot.payload, "A")} / HK ${stageMarketStateText(snapshot.payload, "HK")}`;
}

function hasStageTimelineForDate(date: string) {
  return stageDefinitions.every((stage) => stageSnapshots.value[stage.id]?.date === date);
}

async function loadStageTimeline(date: string, currentStage: string, currentPayload: StageWorkbench | null) {
  if (!date || date !== selectedDate.value) return;
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

  await Promise.all(stageDefinitions.map(async (stage) => {
    try {
      const payload = await loadStageSnapshot(date, stage.id, controller.signal);
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
  }));
  if (stageTimelineRequestController === controller) stageTimelineRequestController = null;
}

async function openNextFutureTargetPool() {
  const targetDate = nextFutureTargetDate.value;
  if (!targetDate) return;
  const needsReload = targetDate !== selectedDate.value
    || researchActive.value
    || closeReviewActive.value
    || taskStatusActive.value;
  taskStatusActive.value = false;
  researchActive.value = false;
  researchArchiveEntry.value = false;
  closeReviewActive.value = false;
  navigationStatus.value = "";
  bindSelectedDate(targetDate, { view: null, stage: selectedStage.value });
  if (needsReload) await onDateChange();
  document.querySelector("#unifiedPreselectPanel")?.scrollIntoView?.({ behavior: "smooth" });
}

async function openNextHkTargetPool() {
  const targetDate = nextHkTargetDate.value;
  if (!targetDate) return;
  const needsReload = targetDate !== selectedDate.value
    || researchActive.value
    || closeReviewActive.value
    || taskStatusActive.value;
  taskStatusActive.value = false;
  researchActive.value = false;
  researchArchiveEntry.value = false;
  closeReviewActive.value = false;
  navigationStatus.value = "";
  bindSelectedDate(targetDate, { view: null, stage: selectedStage.value });
  if (needsReload) await onDateChange();
  document.querySelector("#unifiedPreselectPanel")?.scrollIntoView?.({ behavior: "smooth" });
}

async function loadStage(stage = selectedStage.value, preserveRunStatus = false, syncUrl = true) {
  void loadFrontendIdentity();
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
    const payload = await loadStageSnapshot(requestedDate, stage, controller.signal);
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

function loadStageFromUser(stage = selectedStage.value) {
  userStageIntentVersion += 1;
  void loadStage(stage);
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
  if (!selectedDate.value) return;
  stageLoading.value = true;
  stageError.value = "";
  try {
    const query = new URLSearchParams({ date: selectedDate.value, stage: selectedStage.value });
    if (force) query.set("force", "true");
    const response = await fetch(`/api/v4/workbench/stage/ensure?${query.toString()}`, { method: "POST" });
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
  } else {
    await Promise.all([loadPool(requestedDate), loadStage()]);
  }
}

async function applyNavigationFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const requestedDate = params.get("date") || "";
  const requestedView = params.get("view") || "";
  const requestedStage = params.get("stage") || "";
  const previousDate = selectedDate.value;
  const previousStage = selectedStage.value;
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
    const requestedResearchDateAllowed = /^\d{8}$/.test(requestedDate)
      && (researchDateOptions.value.includes(requestedDate)
        || researchOptionsEmpty);
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
  if (stageChanged || dateChanged || modeChanged) {
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

async function onDateInputChange(event: Event) {
  const input = event.currentTarget as HTMLInputElement;
  const compact = compactDateInput(input.value);
  if (!activeDateOptions.value.includes(compact)) {
    input.setCustomValidity(researchActive.value ? "请选择已有研究材料的自然日" : "请选择日历中的有效交易日");
    input.value = formatDateInput(selectedDate.value);
    input.reportValidity();
    return;
  }
  input.setCustomValidity("");
  userDateIntentVersion += 1;
  selectedDate.value = compact;
  writeSelectedDateToUrl(compact);
  await onDateChange();
}

onMounted(async () => {
  void loadFrontendIdentity();
  const dateIntentAtMount = userDateIntentVersion;
  const stageIntentAtMount = userStageIntentVersion;
  window.addEventListener("popstate", onBrowserHistoryChange);
  try {
    const [dateList, laneDates] = await Promise.all([
      fetch("/api/v1/runs/date-list").then((r) => (r.ok ? r.json() : Promise.reject(new Error("request failed")))),
      fetch("/api/v4/research/dates")
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null),
    ]);
    dateData.value = {
      ...dateList,
      // Merge the V3 research-module dates so the date picker can switch to
      // any available research lane date even when the local stage calendar
      // only covers the current day (e.g. a fresh V4 data root).
      research_dates: [...new Set([...(dateList.research_dates ?? []), ...((laneDates?.research_dates as string[] | undefined) ?? [])])].sort(),
    };
    const params = new URLSearchParams(window.location.search);
    const requestedDate = params.get("date");
    const requestedStage = params.get("stage");
    const requestedView = params.get("view");
    const userSelectedDate = userDateIntentVersion !== dateIntentAtMount
      && isAllowedDateForView(selectedDate.value)
      ? selectedDate.value
      : "";
    const userSelectedStage = userStageIntentVersion !== stageIntentAtMount;
    if (!userSelectedStage && requestedStage && stageDefinitions.some((stage) => stage.id === requestedStage)) {
      selectedStage.value = requestedStage;
    }
    if (requestedView === "research") {
      const explicitResearchDate = requestedDate
        && /^\d{8}$/.test(requestedDate)
        && (researchDateOptions.value.includes(requestedDate) || researchDateOptions.value.length === 0)
        ? requestedDate
        : "";
      selectedDate.value = userSelectedDate || explicitResearchDate || resolveResearchDate(dateData.value.navigation_date || dateData.value.default_date || "");
      openResearch();
    } else if (["review", "a-review", "research-review"].includes(requestedView || "")) {
      const explicitTradingDate = requestedDate
        && /^\d{8}$/.test(requestedDate)
        && (tradingDateOptions.value.includes(requestedDate) || isHistoricalTradingDate(requestedDate))
        ? requestedDate
        : "";
      selectedDate.value = userSelectedDate || explicitTradingDate || resolveTradingDate(dateData.value.navigation_date || dateData.value.default_date || "");
      await Promise.all([loadPool(), loadCloseReview(requestedView === "research-review" ? "research" : requestedView === "a-review" ? "A" : "HK")]);
    } else {
      const explicitTradingDate = requestedDate
        && /^\d{8}$/.test(requestedDate)
        && (tradingDateOptions.value.includes(requestedDate) || isHistoricalTradingDate(requestedDate))
        ? requestedDate
        : "";
      selectedDate.value = userSelectedDate || explicitTradingDate || resolveTradingDate(dateData.value.navigation_date || dateData.value.default_date || "");
      if (userSelectedDate || userSelectedStage) {
        bindSelectedDate(selectedDate.value, { view: null, stage: selectedStage.value });
      }
      await Promise.all([loadPool(), loadStage(undefined, false, false)]);
    }
  } catch {
    loadError.value = "交易日目录读取失败。";
    stageError.value = "交易日目录读取失败。";
  }
});

onBeforeUnmount(() => {
  window.removeEventListener("popstate", onBrowserHistoryChange);
  closingRequestVersion += 1;
  closingController?.abort();
  if (closingRefreshTimer !== null) clearTimeout(closingRefreshTimer);
  requestVersion += 1;
  poolRequestController?.abort();
  poolRequestController = null;
  abortStageRequests();
  stageRequestVersion += 1;
  stageTimelineRequestVersion += 1;
});
  return {
    stageDefinitions,
    closingTimeline,
    loadClosingStatus,
    poolRows,
    poolEvidenceReason,
    poolEvidenceDetails,
    poolRowCode,
    poolRowName,
    poolRowSource,
    poolRowSourceLane,
    poolCountLabel,
    poolRowSignalDate,
    formatPercent,
    formatDateInput,
    evidenceValue,
    rowCode,
    rowName,
    rowRank,
    aShareChangePct,
    rowSupport,
    rowPressure,
    rowInvalidation,
    rowNextEvidence,
    rowScore,
    qualityScore,
    stageCountText,
    stageMarketCountText,
    aMarketStateText,
    hkMarketStateText,
    missingStageReceiptMessage,
    hasMissingStageReceipt,
    hkChangeLabel,
    rowMissingFields,
    hitTop20,
    reviewClassification,
    selectedDate,
    pool,
    poolPageOffset,
    aPoolPageLabel,
    aPoolPreviousOffset,
    aPoolNextOffset,
    loading,
    loadError,
    selectedStage,
    stageWorkbench,
    stageLoading,
    stageError,
    stageRunStatus,
    navigationStatus,
    taskStatusActive,
    researchActive,
    researchArchiveEntry,
    closeReviewActive,
    reviewFocus,
    reviewTitle,
    runtimeLabel,
    frontendIdentity,
    refreshFrontend,
    closeReviewLoading,
    closeReviewError,
    closeReviewPayload,
    isHkObservationOnlyDate,
    nextFutureTargetDate,
    nextHkTargetDate,
    selectedDateContext,
    dateInputMin,
    dateInputMax,
    dateInputTitle,
    currentStageDefinition,
    isPreopenStage,
    aRows,
    hkRows,
    canLoadWechatMentions,
    collapsedPools,
    preselectionGroups,
    togglePool,
    isWechatPool,
    isBaimaoPool,
    isCompactResearchPool,
    referenceMode,
    v11OpeningFilter,
    stageSummary,
    aSummary,
    showAStageEvidenceGap,
    closeReview,
    modelMetric,
    stageUnionMetric,
    closeReviewEvidenceLabel,
    reviewEvidenceGaps,
    hkChangeValue,
    hkScoreLabel,
    showNavigationStatus,
    openTaskStatus,
    openResearch,
    openManagerSelection,
    scrollToPool,
    loadPoolPage,
    openNextFutureTargetPool,
    openNextHkTargetPool,
    timelineStageStatus,
    timelineStageCounts,
    loadStage,
    loadStageFromUser,
    loadCloseReview,
    ensureStage,
    onDateInputChange,
  };
}
