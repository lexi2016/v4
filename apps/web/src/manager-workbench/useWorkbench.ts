import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { ApiError, createWorkbenchApi } from "./api";
import type { DayQuery, WorkbenchApi } from "./api";
import type {
  DayData, Decision, Envelope, HistoryData, JobRecord, Lane, Phase,
  ReviewSummary, StockDecision, StockDetails
} from "./types";
import { parseWorkbenchRoute, routeSearch } from "./route";
import type { WorkbenchRoute } from "./route";

export type Panel = "stocks" | "detail" | "progress" | "history" | "reviews";
type APIData<T> = Envelope<T> | null;

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = Array.isArray(error.gaps) ? error.gaps
      .map(x => typeof x === "string" ? x : (x && typeof x === "object" && "code" in x ? String(x.code) : ""))
      .filter(Boolean).join("；") : "";
    return "接口 " + (error.status || "网络") + "：" + error.message + (detail ? " · " + detail : "");
  }
  return error instanceof Error ? error.message : "未知错误";
}
function isAbort(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}
function keyForQuery(q: DayQuery): string {
  return JSON.stringify([q.date, q.phase || "", q.run_id || "", q.offset || 0, q.limit || 50,
    q.decision || "", q.lane || "", q.q || ""]);
}
export function useWorkbench(api: WorkbenchApi = createWorkbenchApi()) {
  const route = ref<WorkbenchRoute>(parseWorkbenchRoute(window.location.search));
  const panel = ref<Panel>("stocks");
  const dateInput = ref(route.value.date);
  const decisionFilter = ref<Decision | "">("");
  const laneFilter = ref<Lane | "">("");
  const searchDraft = ref("");
  const search = ref("");
  const offset = ref(0);
  const limit = 50;
  const day = ref<APIData<DayData>>(null);
  const lastSuccessfulKey = ref("");
  const dayLoading = ref(false);
  const dayError = ref("");
  const stale = ref(false);
  const detailSymbol = ref("");
  const detail = ref<APIData<StockDetails>>(null);
  const detailLoading = ref(false);
  const detailError = ref("");
  const history = ref<APIData<HistoryData>>(null);
  const historyLoading = ref(false);
  const historyError = ref("");
  const review = ref<APIData<ReviewSummary>>(null);
  const reviewLoading = ref(false);
  const reviewError = ref("");
  const job = ref<APIData<JobRecord>>(null);
  const jobId = ref("");
  const jobLoading = ref(false);
  const jobError = ref("");
  const operationLoading = ref(false);
  const runPhase = ref<"MANUAL" | "RETROSPECTIVE">("MANUAL");

  const stocks = computed<StockDecision[]>(() => day.value?.data?.stocks || []);
  const snapshot = computed(() => day.value?.data?.snapshot || null);
  const counts = computed(() => day.value?.data?.counts || null);
  const pagination = computed(() => day.value?.data?.pagination || null);
  const versions = computed(() => day.value?.data?.versions || []);
  const lanes = computed(() => snapshot.value?.lanes || []);
  const selectedRunId = computed(() => snapshot.value?.run_id || route.value.runId || "");
  const selectedDate = computed(() => snapshot.value?.context.target_date || route.value.date);
  const hasStale = computed(() => stale.value && !!day.value);
  const readMode = computed(() => route.value.runId ? "固定 run_id" : route.value.phase ? "按阶段读最新保存版" : "目标日最新保存版");
  const valid = computed(() => route.value.error === null);

  let daySeq = 0, detailSeq = 0, historySeq = 0, reviewSeq = 0, jobSeq = 0, operationSeq = 0;
  let dayAbort: AbortController | null = null;
  let detailAbort: AbortController | null = null;
  let historyAbort: AbortController | null = null;
  let reviewAbort: AbortController | null = null;
  let jobAbort: AbortController | null = null;
  let jobTimer: ReturnType<typeof setTimeout> | null = null;

  function stopJobReads(): void {
    jobSeq++;
    jobAbort?.abort();
    if (jobTimer !== null) clearTimeout(jobTimer);
    jobTimer = null;
    jobLoading.value = false;
  }
  function abortAll(): void {
    daySeq++; detailSeq++; historySeq++; reviewSeq++;
    dayAbort?.abort(); detailAbort?.abort(); historyAbort?.abort(); reviewAbort?.abort();
    stopJobReads();
  }
  function resetPage(): void {
    operationSeq++;
    abortAll();
    day.value = null; dayLoading.value = false; dayError.value = ""; stale.value = false;
    lastSuccessfulKey.value = "";
    detail.value = null; detailSymbol.value = ""; detailError.value = ""; detailLoading.value = false;
    history.value = null; historyError.value = ""; historyLoading.value = false;
    review.value = null; reviewError.value = ""; reviewLoading.value = false;
    job.value = null; jobId.value = ""; jobError.value = "";
    panel.value = "stocks"; offset.value = 0; search.value = ""; searchDraft.value = "";
    decisionFilter.value = ""; laneFilter.value = "";
  }
  function navigate(next: WorkbenchRoute, replace = false): void {
    resetPage();
    route.value = next; dateInput.value = next.date;
    const url = window.location.pathname + routeSearch(next, window.location.search) + window.location.hash;
    if (replace) window.history.replaceState(null, "", url);
    else window.history.pushState(null, "", url);
    if (!next.error) void loadDay();
  }
  function changeDate(): void {
    const candidate = parseWorkbenchRoute("?date=" + encodeURIComponent(dateInput.value));
    navigate(candidate);
  }
  function changeVersion(phase: Phase | "", runId = ""): void {
    navigate({ date: route.value.date, phase, runId, error: null });
  }
  function onPopState(): void {
    resetPage();
    route.value = parseWorkbenchRoute(window.location.search);
    dateInput.value = route.value.date;
    if (!route.value.error) void loadDay();
  }
  function dayQuery(): DayQuery {
    return { date: route.value.date, phase: route.value.phase, run_id: route.value.runId,
      offset: offset.value, limit, decision: decisionFilter.value,
      lane: laneFilter.value, q: search.value };
  }
  async function loadDay(preserve = false): Promise<void> {
    if (!valid.value) return;
    const query = dayQuery(); const key = keyForQuery(query);
    const old = preserve && lastSuccessfulKey.value === key ? day.value : null;
    const seq = ++daySeq;
    dayAbort?.abort(); const ctrl = new AbortController(); dayAbort = ctrl;
    if (!old) day.value = null;
    stale.value = false; dayLoading.value = true; dayError.value = "";
    try {
      const response = await api.getDay(query, ctrl.signal);
      if (seq !== daySeq || ctrl.signal.aborted) return;
      if (response.data?.snapshot) {
        const snap = response.data.snapshot;
        if (snap.context.target_date !== query.date ||
            (query.run_id && snap.run_id !== query.run_id) ||
            (query.phase && snap.context.phase !== query.phase)) {
          throw new ApiError("API 返回的日期、阶段或版本与本次请求不一致", 502);
        }
      }
      day.value = response;
      if (response.data) lastSuccessfulKey.value = key;
      else lastSuccessfulKey.value = "";
    } catch (error) {
      if (seq !== daySeq || isAbort(error)) return;
      dayError.value = errorMessage(error);
      day.value = old;
      stale.value = !!old;
    } finally {
      if (seq === daySeq) dayLoading.value = false;
    }
  }
  function applyFilters(): void {
    offset.value = 0; search.value = searchDraft.value.trim();
    void loadDay();
  }
  function setOffset(next: number): void {
    const maxTotal = pagination.value?.total ?? 0;
    if (!Number.isInteger(next) || next < 0 || next >= maxTotal || next === offset.value) return;
    offset.value = next;
    void loadDay();
  }
  function showPanel(next: Panel): void {
    panel.value = next;
    if (next === "history") void loadHistory();
    if (next === "reviews") void loadReview();
  }
  async function openStock(stock: StockDecision): Promise<void> {
    panel.value = "detail";
    detail.value = null; detailError.value = ""; detailSymbol.value = stock.symbol;
    const runId = selectedRunId.value;
    if (!runId) { detailError.value = "缺少计划 run_id，不能读取跨版本详情"; return; }
    const seq = ++detailSeq;
    detailAbort?.abort(); const ctrl = new AbortController(); detailAbort = ctrl;
    detailLoading.value = true;
    try {
      const result = await api.getStock(stock.symbol, route.value.date, runId, ctrl.signal);
      if (seq === detailSeq && !ctrl.signal.aborted) detail.value = result;
    } catch (error) {
      if (seq === detailSeq && !isAbort(error)) detailError.value = errorMessage(error);
    } finally {
      if (seq === detailSeq) detailLoading.value = false;
    }
  }
  async function loadHistory(): Promise<void> {
    if (!valid.value) return;
    const seq = ++historySeq;
    historyAbort?.abort(); const ctrl = new AbortController(); historyAbort = ctrl;
    history.value = null; historyLoading.value = true; historyError.value = "";
    try {
      const result = await api.getHistory(route.value.date, ctrl.signal);
      if (seq === historySeq && !ctrl.signal.aborted) history.value = result;
    } catch (error) {
      if (seq === historySeq && !isAbort(error)) historyError.value = errorMessage(error);
    } finally {
      if (seq === historySeq) historyLoading.value = false;
    }
  }
  async function loadReview(): Promise<void> {
    if (!valid.value) return;
    const runId = selectedRunId.value;
    review.value = null; reviewError.value = "";
    if (!runId) { reviewError.value = "没有已保存计划版本，无法请求对应收盘复盘"; return; }
    const seq = ++reviewSeq;
    reviewAbort?.abort(); const ctrl = new AbortController(); reviewAbort = ctrl;
    reviewLoading.value = true;
    try {
      const result = await api.getReview(route.value.date, runId, ctrl.signal);
      if (seq === reviewSeq && !ctrl.signal.aborted) review.value = result;
    } catch (error) {
      if (seq === reviewSeq && !isAbort(error)) reviewError.value = errorMessage(error);
    } finally {
      if (seq === reviewSeq) reviewLoading.value = false;
    }
  }
  async function pollJob(): Promise<void> {
    if (!jobId.value) return;
    const requestedId = jobId.value;
    const seq = ++jobSeq;
    jobAbort?.abort(); const ctrl = new AbortController(); jobAbort = ctrl;
    jobLoading.value = true;
    try {
      const result = await api.getJob(requestedId, ctrl.signal);
      if (seq !== jobSeq || ctrl.signal.aborted || jobId.value !== requestedId) return;
      job.value = result; jobError.value = "";
      const state = result.data?.state;
      if (state === "QUEUED" || state === "RUNNING") {
        jobTimer = setTimeout(() => { void pollJob(); }, 2000);
      }
    } catch (error) {
      if (seq === jobSeq && !isAbort(error)) jobError.value = errorMessage(error);
    } finally {
      if (seq === jobSeq) jobLoading.value = false;
    }
  }
  async function createPlan(): Promise<void> {
    if (!valid.value || operationLoading.value) return;
    stopJobReads(); jobId.value = ""; job.value = null; jobError.value = "";
    const ticket = ++operationSeq;
    operationLoading.value = true; panel.value = "progress";
    try {
      const result = await api.createRun(route.value.date, runPhase.value);
      if (ticket !== operationSeq) return;
      if (!result.data?.job_id || !result.data?.run_id) throw new ApiError("创建任务缺 job_id/run_id", 502);
      jobId.value = result.data.job_id;
      void pollJob();
    } catch (error) { if (ticket === operationSeq) jobError.value = errorMessage(error); }
    finally { if (ticket === operationSeq) operationLoading.value = false; }
  }
  async function retryJob(): Promise<void> {
    if (!jobId.value || !job.value?.data?.retryable || operationLoading.value) return;
    const ticket = ++operationSeq;
    operationLoading.value = true; jobError.value = "";
    try {
      const result = await api.retryJob(jobId.value);
      if (ticket !== operationSeq) return;
      if (result.data) job.value = result;
      void pollJob();
    } catch (error) { if (ticket === operationSeq) jobError.value = errorMessage(error); }
    finally { if (ticket === operationSeq) operationLoading.value = false; }
  }
  function viewJobVersion(): void {
    const ctx = job.value?.data?.context;
    const runId = job.value?.data?.run_id;
    if (!ctx || !runId || ctx.target_date !== route.value.date) return;
    navigate({ date: ctx.target_date, phase: ctx.phase, runId, error: null });
  }
  onMounted(() => {
    window.addEventListener("popstate", onPopState);
    if (!route.value.error) void loadDay();
    if (window.location.search.includes("plan_date=")) {
      window.history.replaceState(null, "", window.location.pathname +
        routeSearch(route.value, window.location.search) + window.location.hash);
    }
  });
  onBeforeUnmount(() => { window.removeEventListener("popstate", onPopState); abortAll(); });

  return {
    route, panel, dateInput, decisionFilter, laneFilter, searchDraft, search, offset, limit,
    day, dayLoading, dayError, stale, hasStale, detail, detailSymbol, detailLoading, detailError,
    history, historyLoading, historyError, review, reviewLoading, reviewError,
    job, jobId, jobLoading, jobError, operationLoading, runPhase,
    stocks, snapshot, counts, pagination, versions, lanes, selectedRunId, selectedDate, readMode, valid,
    changeDate, changeVersion, loadDay, applyFilters, setOffset, showPanel, openStock,
    loadHistory, loadReview, pollJob, createPlan, retryJob, viewJobVersion
  };
}
