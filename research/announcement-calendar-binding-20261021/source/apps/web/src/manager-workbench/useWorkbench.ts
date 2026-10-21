import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { ApiError, createWorkbenchApi } from "./api";
import type { DayQuery, WorkbenchApi } from "./api";
import type {
  DayData, Decision, Envelope, HistoryData, JobRecord, Lane, Phase,
  ReviewSummary, StockDecision, StockDetails, RecommendationLane, USMappingCatalogData, USMappingCatalogRelation
} from "./types";
import { isValidDate, parseWorkbenchRoute, routeSearch } from "./route";
import type { WorkbenchRoute } from "./route";

export type Panel = "stocks" | "announcements" | "detail" | "progress" | "history" | "reviews" | "catalog";
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
  const decisionFilter = ref<Decision | "">("");
  const laneFilter = ref<RecommendationLane>('US_MAPPING');
  const laneViews: Partial<Record<RecommendationLane, { offset: number; decision: Decision | ''; search: string }>> = {};
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
  const catalogResearchUse = ref("");
  const catalogQueryDraft = ref("");
  const catalogQuery = ref("");
  const catalogOffset = ref(0);
  const catalogLimit = 25;
  const catalog = ref<APIData<USMappingCatalogData>>(null);
  const catalogLoading = ref(false);
  const catalogError = ref("");
  const catalogRelationDetails = ref<Record<string, {
    loading: boolean; error: string; data: USMappingCatalogRelation | null;
  }>>({});
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

  let daySeq = 0, detailSeq = 0, historySeq = 0, reviewSeq = 0, catalogSeq = 0, jobSeq = 0, operationSeq = 0;
  let dayAbort: AbortController | null = null;
  let detailAbort: AbortController | null = null;
  let historyAbort: AbortController | null = null;
  let reviewAbort: AbortController | null = null;
  let catalogAbort: AbortController | null = null;
  const catalogRelationAborts = new Map<string, AbortController>();
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
    daySeq++; detailSeq++; historySeq++; reviewSeq++; catalogSeq++;
    dayAbort?.abort(); detailAbort?.abort(); historyAbort?.abort(); reviewAbort?.abort(); catalogAbort?.abort();
    catalogLoading.value = false;
    clearCatalogRelationDetails();
    stopJobReads();
  }
  function resetPage(): void {
    operationSeq++;
    operationLoading.value = false;
    abortAll();
    day.value = null; dayLoading.value = false; dayError.value = ""; stale.value = false;
    lastSuccessfulKey.value = "";
    detail.value = null; detailSymbol.value = ""; detailError.value = ""; detailLoading.value = false;
    history.value = null; historyError.value = ""; historyLoading.value = false;
    review.value = null; reviewError.value = ""; reviewLoading.value = false;
    job.value = null; jobId.value = ""; jobError.value = "";
    panel.value = "stocks"; offset.value = 0; search.value = ""; searchDraft.value = "";
    decisionFilter.value = ""; laneFilter.value = 'US_MAPPING';
    delete laneViews.US_MAPPING; delete laneViews.OVERSOLD;
  }
  function navigate(next: WorkbenchRoute, replace = false): void {
    resetPage();
    route.value = next;
    const previous = new URLSearchParams(window.location.search);
    ["offset", "limit", "decision", "lane", "q"].forEach(key => previous.delete(key));
    const url = window.location.pathname + routeSearch(next, previous.toString()) + window.location.hash;
    if (replace) window.history.replaceState(null, "", url);
    else window.history.pushState(null, "", url);
    if (!next.error) void loadDay();
  }
  function selectDate(date: string): void {
    if (!isValidDate(date) || date === route.value.date) return;
    navigate(parseWorkbenchRoute("?date=" + encodeURIComponent(date)));
  }
  function changeVersion(phase: Phase | "", runId = ""): void {
    navigate({ date: route.value.date, phase, runId, error: null });
  }
  function onPopState(): void {
    resetPage();
    route.value = parseWorkbenchRoute(window.location.search);
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
    const previousRunId = snapshot.value?.run_id;
    const old = preserve && lastSuccessfulKey.value === key ? day.value : null;
    const seq = ++daySeq;
    dayAbort?.abort(); const ctrl = new AbortController(); dayAbort = ctrl;
    if (!old) day.value = null;
    stale.value = false; dayLoading.value = true; dayError.value = "";
    try {
      const response = await api.getRecommendations(query, ctrl.signal);
      if (seq !== daySeq || ctrl.signal.aborted) return;
      if (response.data?.snapshot) {
        const snap = response.data.snapshot;
        if (snap.context.target_date !== query.date ||
            (query.run_id && snap.run_id !== query.run_id) ||
            (query.phase && snap.context.phase !== query.phase) ||
            (response.data?.recommendation_projection && response.data.recommendation_projection.lane !== query.lane)) {
          throw new ApiError("API 返回的日期、阶段或版本与本次请求不一致", 502);
        }
      }
      if (previousRunId && previousRunId !== response.data?.snapshot?.run_id) {
        detailSeq++; reviewSeq++;
        detailAbort?.abort(); reviewAbort?.abort();
        detail.value = null; detailSymbol.value = ""; detailLoading.value = false; detailError.value = "";
        review.value = null; reviewLoading.value = false; reviewError.value = "";
      }
      day.value = response;
      if (response.data?.snapshot) lastSuccessfulKey.value = key;
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
  function switchLane(lane: RecommendationLane): void {
    if (lane === laneFilter.value) return;
    laneViews[laneFilter.value] = { offset: offset.value, decision: decisionFilter.value, search: search.value };
    laneFilter.value = lane;
    const view = laneViews[lane]; offset.value = view?.offset || 0;
    decisionFilter.value = view?.decision || ''; search.value = view?.search || ''; searchDraft.value = search.value;
    detailSeq++; detailAbort?.abort(); detail.value = null; detailLoading.value = false;
    panel.value = 'stocks'; void loadDay();
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
    if (next === "catalog") void loadCatalog();
    else clearCatalogRelationDetails();
  }
  async function loadCatalog(offset = catalogOffset.value): Promise<void> {
    if (!Number.isInteger(offset) || offset < 0) return;
    const query = catalogQuery.value.trim();
    const seq = ++catalogSeq;
    clearCatalogRelationDetails();
    catalogAbort?.abort(); const ctrl = new AbortController(); catalogAbort = ctrl;
    catalogOffset.value = offset; catalog.value = null; catalogError.value = ""; catalogLoading.value = true;
    try {
      const result = await api.getUsMappingCatalog(query, offset, catalogLimit, ctrl.signal, catalogResearchUse.value);
      if (seq !== catalogSeq || ctrl.signal.aborted) return;
      if (!result.data || result.data.catalog_state !== "STRUCTURE_VALID_ONLY" ||
          result.data.query !== query || result.data.offset !== offset ||
          result.data.research_use !== catalogResearchUse.value ||
          result.data.safety?.RESEARCH_ONLY !== true || result.data.safety?.production_allowed !== false ||
          result.data.safety?.buy_gate_updated !== false || result.data.safety?.orders_sent !== false ||
          result.data.safety?.prediction_validation !== "UNTESTED" ||
          result.data.safety?.historical_PIT !== "NOT_VALIDATED") {
        throw new ApiError("美股映射资料库返回的来源或安全状态不一致", 502);
      }
      catalog.value = result;
    } catch (error) {
      if (seq === catalogSeq && !isAbort(error)) catalogError.value = errorMessage(error);
    } finally {
      if (seq === catalogSeq) catalogLoading.value = false;
    }
  }
  function clearCatalogRelationDetails(): void {
    for (const ctrl of catalogRelationAborts.values()) ctrl.abort();
    catalogRelationAborts.clear();
    catalogRelationDetails.value = {};
  }
  async function loadCatalogRelation(relation: USMappingCatalogRelation): Promise<void> {
    const rid = relation.relation_id;
    const base = catalog.value?.data;
    if (!base || !/^R[0-9]{3,4}$/.test(rid)) return;
    const seq = catalogSeq;
    catalogRelationAborts.get(rid)?.abort();
    const ctrl = new AbortController(); catalogRelationAborts.set(rid, ctrl);
    catalogRelationDetails.value[rid] = { loading: true, error: "", data: null };
    try {
      const result = await api.getUsMappingCatalog(rid, 0, 1, ctrl.signal);
      if (seq !== catalogSeq || ctrl.signal.aborted || catalogRelationAborts.get(rid) !== ctrl) return;
      const data = result.data;
      const rows = data?.items.flatMap(item => item.relations) || [];
      const full = rows[0];
      if (!data || data.catalog_state !== "STRUCTURE_VALID_ONLY" || data.query !== rid ||
          data.catalog_integrity_sha256 !== base.catalog_integrity_sha256 ||
          data.review_source?.integrity_sha256 !== base.review_source?.integrity_sha256 ||
          data.total !== 1 || rows.length !== 1 || !full || full.relation_id !== rid ||
          full.hk_code !== relation.hk_code || full.us_symbol !== relation.us_symbol ||
          full.source_row !== relation.source_row || full.review_detail_level !== "FULL" ||
          full.fact_review_status !== "PENDING" || full.independent_verification !== "NOT_RUN" ||
          full.prediction_eligible !== false || full.prediction_validation !== "UNTESTED" ||
          full.historical_PIT !== "NOT_VALIDATED" || data.safety?.RESEARCH_ONLY !== true ||
          data.safety?.production_allowed !== false || data.safety?.buy_gate_updated !== false ||
          data.safety?.orders_sent !== false || data.safety?.prediction_validation !== "UNTESTED" ||
          data.safety?.historical_PIT !== "NOT_VALIDATED") {
        throw new ApiError("完整补证返回的关系身份、来源或安全状态不一致", 502);
      }
      catalogRelationDetails.value[rid] = { loading: false, error: "", data: full };
    } catch (error) {
      if (seq === catalogSeq && !ctrl.signal.aborted && catalogRelationAborts.get(rid) === ctrl) {
        catalogRelationDetails.value[rid] = { loading: false, error: errorMessage(error), data: null };
      }
    } finally {
      if (catalogRelationAborts.get(rid) === ctrl) catalogRelationAborts.delete(rid);
    }
  }
  function searchCatalog(): void {
    catalogQuery.value = catalogQueryDraft.value.trim();
    void loadCatalog(0);
  }
  function changeCatalogPage(direction: -1 | 1): void {
    const total = catalog.value?.data?.total ?? 0;
    const next = catalogOffset.value + direction * catalogLimit;
    if (next < 0 || next >= total || next === catalogOffset.value) return;
    void loadCatalog(next);
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
      const result = await api.getStock(stock.symbol, route.value.date, runId, ctrl.signal,
        { lane: laneFilter.value, row_id: String(stock.row_id || '') });
      if (seq !== detailSeq || ctrl.signal.aborted) return;
      if (result.data?.plan_run_id !== runId || result.data.stock?.symbol !== stock.symbol) {
        throw new ApiError("个股详情与请求的计划 run_id 不一致", 502);
      }
      if (result.data.recommendation_lane !== laneFilter.value || result.data.stock.row_id !== stock.row_id) {
        throw new ApiError('个股详情与请求的独立推荐来源或记录不一致', 502);
      }
      detail.value = result;
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
      if (seq === historySeq && !ctrl.signal.aborted) {
        if (result.data && result.data.date !== route.value.date) throw new ApiError("历史目标日不一致", 502);
        history.value = result;
      }
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
      if (seq === reviewSeq && !ctrl.signal.aborted) {
        if (result.data && (result.data.plan_run_id !== runId || result.data.target_date !== route.value.date)) {
          throw new ApiError("复盘日期或计划版本不一致", 502);
        }
        review.value = result;
      }
    } catch (error) {
      if (seq === reviewSeq && !isAbort(error)) reviewError.value = errorMessage(error);
    } finally {
      if (seq === reviewSeq) reviewLoading.value = false;
    }
  }
  async function pollJob(): Promise<void> {
    if (!jobId.value) return;
    if (jobTimer !== null) clearTimeout(jobTimer);
    jobTimer = null;
    const requestedId = jobId.value;
    const seq = ++jobSeq;
    jobAbort?.abort(); const ctrl = new AbortController(); jobAbort = ctrl;
    jobLoading.value = true;
    try {
      const result = await api.getJob(requestedId, ctrl.signal);
      if (seq !== jobSeq || ctrl.signal.aborted || jobId.value !== requestedId) return;
      if (result.data && (result.data.job_id !== requestedId || result.data.context.target_date !== route.value.date)) {
        throw new ApiError("任务身份或目标日不一致", 502);
      }
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
    const previousJobId = jobId.value;
    operationLoading.value = true; jobError.value = "";
    try {
      const result = await api.retryJob(previousJobId);
      if (ticket !== operationSeq) return;
      // B POST /retry returns JobCreated, not JobRecord; get the authoritative
      // new job state with a separate read. Do not cancel a running server job.
      if (!result.data?.job_id || !result.data?.run_id) {
        throw new ApiError("恢复任务缺 job_id/run_id", 502);
      }
      stopJobReads();
      jobId.value = result.data.job_id;
      job.value = null;
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
  onBeforeUnmount(() => { operationSeq++; window.removeEventListener("popstate", onPopState); abortAll(); });

  return {
    route, panel, selectDate,
    decisionFilter, laneFilter, searchDraft, search, offset, limit,
    day, dayLoading, dayError, stale, hasStale, detail, detailSymbol, detailLoading, detailError,
    history, historyLoading, historyError, review, reviewLoading, reviewError,
    catalogResearchUse, catalogQueryDraft, catalogQuery, catalogOffset, catalogLimit, catalog, catalogLoading, catalogError, catalogRelationDetails,
    job, jobId, jobLoading, jobError, operationLoading, runPhase,
    stocks, snapshot, counts, pagination, versions, lanes, selectedRunId, selectedDate, readMode, valid,
    changeVersion, loadDay, applyFilters, switchLane, setOffset, showPanel, openStock,
    loadHistory, loadReview, loadCatalog, loadCatalogRelation, searchCatalog, changeCatalogPage,
    pollJob, createPlan, retryJob, viewJobVersion
  };
}
