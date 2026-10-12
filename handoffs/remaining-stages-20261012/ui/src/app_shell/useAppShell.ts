
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import type { StageSummary } from "../components/review/StageSummaryPanel.vue";
import { loadReview } from "../api/review";
import type { ReviewEnvelope } from "../contracts/review";import type { DateResponse, ModelSelectionReview, NavigationUrlState, PoolGroup, PoolResponse, StageRow, StageTimelineSnapshot, StageWorkbench } from "./types";

import { poolRows, poolEvidenceReason, poolEvidenceDetails, poolRowCode, poolRowName, poolRowSource, poolRowSourceLane, poolCountLabel, poolRowSignalDate, formatPercent, assertExactResponseDate, assertExactStagePayload, formatDateInput, compactDateInput, evidenceValue, rowCode, rowName, rowRank, aShareChangePct, rowSupport, rowPressure, rowInvalidation, rowNextEvidence, rowScore, qualityScore, stageCountText, stageMarketCountText, is0920D1ReferenceRow, hkChangeLabel, rowMissingFields, hitTop20, reviewClassification } from "./formatters";
import { createTimeline } from "./timeline";

export function useAppShell() {
  const { stageDefinitions, closingTimeline } = createTimeline();


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
const STAGE_TIMELINE_MAX_CONCURRENCY = 3;
const STAGE_DEADLINE_MINUTES: Record<string, number> = {
  STAGE_0925: 9 * 60 + 25,
  STAGE_0930_0935: 9 * 60 + 35,
  STAGE_0935_0940: 9 * 60 + 40,
  STAGE_0940_0945: 9 * 60 + 45,
  STAGE_0945_1030: 10 * 60 + 30,
  STAGE_1300_1315: 13 * 60 + 15,
  STAGE_1445_1500: 15 * 60,
  STAGE_1545_1555: 15 * 60 + 55,
};
const SHANGHAI_DATE_FORMATTER = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});
const SHANGHAI_TIME_FORMATTER = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Shanghai",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

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
  if (closeReview.value.evidence_mode === "V3_5_NATIVE_PRODUCTION") return "V3.5 原生收盘证据";
  return "收盘证据未导入";
});
const reviewEvidenceGaps = computed(() =>
  [...new Set([...(closeReview.value.missing_stages ?? []), ...(closeReview.value.cannot_confirm ?? [])])],
);

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

function setStageTimelineSnapshot(stageId: string, snapshot: StageTimelineSnapshot, version?: number) {
  if (snapshot.date !== selectedDate.value) return;
  if (version !== undefined && version !== stageTimelineRequestVersion) return;
  stageSnapshots.value = { ...stageSnapshots.value, [stageId]: snapshot };
}

function beforeStageDeadline(stageId: string, date: string, now = new Date()) {
  const deadlineMinute = STAGE_DEADLINE_MINUTES[stageId];
  if (deadlineMinute === undefined) return false;
  const dateParts = SHANGHAI_DATE_FORMATTER.formatToParts(now);
  const datePart = (type: string) => dateParts.find((part) => part.type === type)?.value ?? "";
  const shanghaiDate = `${datePart("year")}${datePart("month")}${datePart("day")}`;
  if (date !== shanghaiDate) return false;
  const timeParts = SHANGHAI_TIME_FORMATTER.formatToParts(now);
  const timePart = (type: string) => Number(timeParts.find((part) => part.type === type)?.value ?? "0");
  return timePart("hour") * 60 + timePart("minute") < deadlineMinute;
}

function isEmptyNotDueStage(stageId: string, date: string, payload: StageWorkbench) {
  if (!beforeStageDeadline(stageId, date)) return false;
  const status = payload.stage?.status || payload.stage?.display_status;
  if (status !== "CANNOT_CONFIRM") return false;
  const selectedCounts = [
    payload.selected_a_rows,
    payload.selected_hk_rows,
    payload.selected_total_rows,
    payload.markets?.A?.candidate_count,
    payload.markets?.HK?.candidate_count,
  ];
  if (selectedCounts.some((count) => typeof count === "number" && count > 0)) return false;
  if ((payload.unified_rows?.length ?? 0) > 0) return false;
  const reasons = [
    ...(payload.cannot_confirm ?? []),
    ...(payload.markets?.A?.cannot_confirm ?? []),
    ...(payload.markets?.HK?.cannot_confirm ?? []),
  ].map((reason) => String(reason).replace(/^(A|HK):/, ""));
  return reasons.length > 0
    && reasons.every((reason) => reason === "SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID");
}

function timelineStageSnapshot(stageId: string) {
  const snapshot = stageSnapshots.value[stageId];
  return snapshot?.date === selectedDate.value ? snapshot : undefined;
}

function timelineStageStatus(stageId: string) {
  const snapshot = timelineStageSnapshot(stageId);
  if (!snapshot) return "读取中";
  if (snapshot.payload) {
    const status = isEmptyNotDueStage(stageId, snapshot.date, snapshot.payload)
      ? "待运行（未到时间）"
      : snapshot.payload.stage.status || snapshot.payload.stage.display_status || "CANNOT_CONFIRM";
    return snapshot.refreshing ? `${status} · 同日更新中` : status;
  }
  if (snapshot.error) return snapshot.refreshing ? "读取失败/点击重试 · 同日更新中" : "读取失败/点击重试";
  if (snapshot.loading || snapshot.refreshing) return "读取中";
  return "读取失败/点击重试";
}

function timelineStageCounts(stageId: string) {
  const snapshot = timelineStageSnapshot(stageId);
  if (!snapshot) return "读取中";
  if (snapshot.payload) {
    const counts = isEmptyNotDueStage(stageId, snapshot.date, snapshot.payload)
      ? "暂无阶段产物"
      : `A ${stageCountText(snapshot.payload.selected_a_rows)} / HK ${stageMarketCountText(snapshot.payload.markets?.HK, snapshot.payload.selected_hk_rows)}`;
    if (snapshot.refreshError) return `${counts} · 同日更新未成功`;
    return snapshot.refreshing ? `${counts} · 同日更新中` : counts;
  }
  if (snapshot.error) return snapshot.refreshing ? "读取失败/点击重试 · 同日更新中" : "读取失败/点击重试";
  if (snapshot.loading || snapshot.refreshing) return "读取中";
  return "读取失败/点击重试";
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
  const previousSnapshots = stageSnapshots.value;
  const initialSnapshots: Record<string, StageTimelineSnapshot> = {};
  for (const stage of stageDefinitions) {
    const existing = previousSnapshots[stage.id];
    if (existing?.date === date) {
      initialSnapshots[stage.id] = { ...existing, refreshing: true, refreshError: undefined };
    } else if (stage.id === currentStage && currentPayloadMatches) {
      initialSnapshots[stage.id] = { date, loading: false, refreshing: true, payload: currentPayload };
    } else {
      initialSnapshots[stage.id] = { date, loading: true };
    }
  }
  stageSnapshots.value = initialSnapshots;

  const stagesToRead = stageDefinitions;
  let nextStageIndex = 0;
  const readNextStage = async () => {
    while (!controller.signal.aborted) {
      const stage = stagesToRead[nextStageIndex];
      if (!stage) return;
      nextStageIndex += 1;
      try {
        const payload = await fetchExactStagePayload(
          `/api/v3/workbench/stage?date=${encodeURIComponent(date)}&stage=${encodeURIComponent(stage.id)}&limit=50`,
          controller.signal,
        );
        assertExactStagePayload(payload, date, stage.id);
        if (version === stageTimelineRequestVersion && date === selectedDate.value) {
          setStageTimelineSnapshot(stage.id, { date, loading: false, payload }, version);
          if (stage.id === selectedStage.value) stageWorkbench.value = payload;
        }
      } catch (reason) {
        if (version === stageTimelineRequestVersion && date === selectedDate.value) {
          const message = reason instanceof Error && reason.message.includes("超时")
            ? "阶段工作台读取超时"
            : "阶段工作台读取失败";
          const existing = stageSnapshots.value[stage.id];
          if (existing?.date === date && existing.payload) {
            setStageTimelineSnapshot(stage.id, { ...existing, loading: false, refreshing: false, refreshError: message }, version);
          } else {
            setStageTimelineSnapshot(stage.id, { date, loading: false, refreshing: false, error: message }, version);
          }
        }
      }
    }
  };
  await Promise.all(Array.from(
    { length: Math.min(STAGE_TIMELINE_MAX_CONCURRENCY, stagesToRead.length) },
    () => readNextStage(),
  ));
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
  const existingSnapshot = stageSnapshots.value[stage];
  const sameDateSnapshot = existingSnapshot?.date === requestedDate ? existingSnapshot : undefined;
  stageWorkbench.value = sameDateSnapshot?.payload ?? null;
  if (sameDateSnapshot) {
    setStageTimelineSnapshot(stage, { ...sameDateSnapshot, refreshing: true, refreshError: undefined });
  } else {
    setStageTimelineSnapshot(stage, { date: requestedDate, loading: true });
  }
  try {
    const url =
      `/api/v3/workbench/stage?date=${encodeURIComponent(requestedDate)}&stage=${encodeURIComponent(stage)}&limit=50`;
    const payload = await fetchExactStagePayload(url, controller.signal);
    assertExactStagePayload(payload, requestedDate, stage);
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
        const existing = stageSnapshots.value[definition.id];
        if (existing?.date === requestedDate && existing.payload) {
          settled[definition.id] = {
            ...existing,
            loading: false,
            refreshing: false,
            ...(definition.id === stage ? { refreshError: stageError.value } : {}),
          };
        } else {
          settled[definition.id] = {
            ...(existing?.date === requestedDate ? existing : {}),
            date: requestedDate,
            loading: false,
            refreshing: false,
            error: definition.id === stage ? stageError.value : existing?.error || "阶段工作台读取失败",
          };
        }
      }
      stageSnapshots.value = settled;
      const failedStageSnapshot = settled[stage];
      stageWorkbench.value = failedStageSnapshot?.date === requestedDate ? failedStageSnapshot.payload ?? null : null;
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
  selectedDate.value = compact;
  writeSelectedDateToUrl(compact);
  await onDateChange();
}

onMounted(async () => {
  window.addEventListener("popstate", onBrowserHistoryChange);
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
    if (requestedView === "research") {
      const explicitResearchDate = requestedDate
        && /^\d{8}$/.test(requestedDate)
        && (researchDateOptions.value.includes(requestedDate) || researchDateOptions.value.length === 0)
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
      await Promise.all([loadPool(), loadStage(undefined, false, false)]);
    }
  } catch {
    loadError.value = "交易日目录读取失败。";
    stageError.value = "交易日目录读取失败。";
  }
});

onBeforeUnmount(() => {
  window.removeEventListener("popstate", onBrowserHistoryChange);
});
  return {
    stageDefinitions,
    closingTimeline,
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
    hkChangeLabel,
    rowMissingFields,
    hitTop20,
    reviewClassification,
    selectedDate,
    pool,
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
    openNextFutureTargetPool,
    openNextHkTargetPool,
    timelineStageStatus,
    timelineStageCounts,
    loadStage,
    loadCloseReview,
    ensureStage,
    onDateInputChange,
  };
}
