import { SCHEMA_VERSION } from "./types";
import type {
  AnnouncementFlashData, AnnouncementFlashResumeAccepted, AnnouncementFlashResumeEligibility,
  AnnouncementFlashUpdateAccepted, DayData, Decision, Envelope, HistoryData,
  JobCreated, JobRecord, Lane, Phase, ReviewSummary, StockDetails, RecommendationLane,
  USMappingCatalogData, PlanMetadata, USMappingCompactStock, USMappingDiagnosticsData,
  USMappingFocusCounts, USMappingFocusDecision, USMappingFocusPolicy, USMappingProjection,
  USMappingSelectionCounts, USMappingSelectionIdentity
} from "./types";
import { isValidDate } from "./route";

const BASE = "/api/v4/manager-workbench";
type FetchLike = typeof fetch;
export interface DayQuery {
  date: string;
  phase?: Phase | "";
  run_id?: string;
  offset?: number;
  limit?: number;
  decision?: Decision | "";
  lane?: Lane | "";
  projection?: USMappingProjection;
  q?: string;
}
export interface USMappingDiagnosticsQuery {
  date: string;
  phase?: Phase | "";
  run_id: string;
  symbol: string;
  relationship_offset?: number;
  relationship_limit?: number;
}
export class ApiError extends Error {
  constructor(message: string, public readonly status: number, public readonly gaps: unknown = null) {
    super(message); this.name = "ApiError";
  }
}
function exactDate(date: string): void {
  if (!isValidDate(date)) throw new ApiError("无效目标日", 422);
}
function httpErrorDetail(payload: unknown): string | null {
  if (!payload || typeof payload !== "object") return null;
  const body = payload as Record<string, unknown>;
  if (typeof body.detail === "string" && body.detail.trim()) return body.detail.trim().slice(0, 250);
  // FastAPI / Pydantic 422: a list of {type, loc, msg}. Do not render raw
  // JSON, tracebacks, input bodies or local paths in user-facing errors.
  if (Array.isArray(body.detail)) {
    const descriptions = body.detail.flatMap(item => {
      if (!item || typeof item !== "object") return [];
      const fields = item as Record<string, unknown>;
      const loc = Array.isArray(fields.loc) ? fields.loc.filter(x => typeof x === "string" || typeof x === "number")
        .slice(0, 3).join(".") : "";
      const type = typeof fields.type === "string" ? fields.type : "";
      const msg = typeof fields.msg === "string" ? fields.msg : "";
      return [([loc, type, msg].filter(Boolean).join(": ")).slice(0, 250)];
    });
    return descriptions.filter(Boolean).slice(0, 4).join("；") || null;
  }
  return null;
}
function assertRunId(id: string): void {
  if (!id || id.length > 180 || !/^[A-Za-z0-9_.:-]+$/.test(id)) throw new ApiError("版本或任务标识无效", 422);
}
function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function normalizeSelectionSnapshot(value: unknown): PlanMetadata | null {
  if (value === null) return null;
  if (!isRecord(value)) throw new ApiError("US_MAPPING 保存版本身份无效", 502);
  if (isRecord(value.context)) return value as unknown as PlanMetadata;
  const targetDate = typeof value.target_date === "string" ? value.target_date : "";
  const phase = value.phase;
  const runId = typeof value.run_id === "string" ? value.run_id : "";
  const phases: Phase[] = ["PREOPEN", "INTRADAY", "NEXT_DAY", "RETROSPECTIVE", "MANUAL"];
  if (!isValidDate(targetDate) || !phases.includes(phase as Phase) || !runId) {
    throw new ApiError("US_MAPPING 保存版本缺少日期、阶段或 run_id", 502);
  }
  return {
    ...value,
    context: {
      market: "HK_CONNECT",
      target_date: targetDate,
      phase: phase as Phase,
      cutoff: typeof value.cutoff === "string" ? value.cutoff : null,
      ...(value.trigger === "MANUAL" || value.trigger === "SCHEDULED" ? { trigger: value.trigger } : {}),
      ...(isRecord(value.source_sessions) ? { source_sessions: value.source_sessions as Record<string, string | null> } : {})
    },
    run_id: runId
  } as unknown as PlanMetadata;
}
function assertSelectionIdentity(value: unknown): USMappingSelectionIdentity {
  if (!isRecord(value) || value.schema_version !== "v4.us_hk.selection.v1"
    || typeof value.policy_sha256 !== "string" || !/^[a-f0-9]{64}$/i.test(value.policy_sha256)
    || typeof value.engine_identity !== "string" || !value.engine_identity) {
    throw new ApiError("US_MAPPING selection_identity 与冻结合同不符", 502);
  }
  return value as unknown as USMappingSelectionIdentity;
}
function assertSelectionCounts(value: unknown): USMappingSelectionCounts {
  const keys = ["candidate_count", "current_supported", "dated_weak", "pending_research",
    "selected", "qualified_not_selected", "rejected", "pending"] as const;
  if (!isRecord(value) || keys.some(key => value[key] !== null &&
    (typeof value[key] !== "number" || !Number.isFinite(value[key])))) {
    throw new ApiError("US_MAPPING 全量汇总计数无效", 502);
  }
  return value as unknown as USMappingSelectionCounts;
}
function assertFocusCounts(value: unknown): USMappingFocusCounts {
  const keys = ["candidate_count", "industry_match_count", "eligible", "selected", "capped", "not_triggered", "pending"] as const;
  if (!isRecord(value) || keys.some(key => !(key in value) || (value[key] !== null
    && (!Number.isInteger(value[key]) || Number(value[key]) < 0)))) {
    throw new ApiError("US_MAPPING 重点筛选全量计数无效", 502);
  }
  return value as unknown as USMappingFocusCounts;
}
function assertFocusPolicy(value: unknown): USMappingFocusPolicy {
  if (!isRecord(value) || typeof value.policy_version !== "string" || !value.policy_version
    || typeof value.policy_sha256 !== "string" || !/^[a-f0-9]{64}$/i.test(value.policy_sha256)) {
    throw new ApiError("US_MAPPING 重点筛选策略身份无效", 502);
  }
  return value as unknown as USMappingFocusPolicy;
}
function assertFocusDecision(value: unknown): USMappingFocusDecision {
  const decisions = ["SELECTED", "CAPPED", "NOT_TRIGGERED", "PENDING"];
  if (!isRecord(value) || typeof value.symbol !== "string" || !/^HK\.[0-9]{5}$/.test(value.symbol)
    || !decisions.includes(String(value.decision)) || typeof value.eligible !== "boolean"
    || (value.rank !== null && (!Number.isInteger(value.rank) || Number(value.rank) < 1))
    || !["primary_path_id", "primary_us_symbol", "primary_theme", "primary_return_pct", "hk_mean_turnover20_hkd"]
      .every(key => value[key] === null || typeof value[key] === "string")
    || !Array.isArray(value.reasons) || value.reasons.some(reason => typeof reason !== "string")) {
    throw new ApiError("US_MAPPING 重点筛选候选结果无效", 502);
  }
  return value as unknown as USMappingFocusDecision;
}
function hasValidIndustryMatches(value: unknown): boolean {
  if (!isRecord(value) || !Array.isArray(value.industry_matches) || !value.industry_matches.length) return false;
  return value.industry_matches.every(match => isRecord(match)
    && typeof match.us_symbol === "string" && !!match.us_symbol
    && typeof match.industry === "string" && !!match.industry
    && ["INDIVIDUAL", "SECTOR_CONTEXT"].includes(String(match.role))
    && Array.isArray(match.warnings)
    && Array.isArray(match.source_refs) && !!match.source_refs.length);
}
function normalizeCompactSelection(data: unknown, requestedProjection: USMappingProjection = "focus"): import("./types").DayData | null {
  if (data === null) return null;
  if (!isRecord(data)) throw new ApiError("US_MAPPING compact 数据无效", 502);
  const hasIdentity = Object.prototype.hasOwnProperty.call(data, "selection_identity");
  if (data.selection_identity !== null && data.selection_identity !== undefined) {
    const identity = assertSelectionIdentity(data.selection_identity);
    if (!Array.isArray(data.stocks) || data.stocks.some(stock => !isRecord(stock)
      || typeof stock.symbol !== "string" || typeof stock.decision !== "string")) {
      throw new ApiError("US_MAPPING compact 候选列表无效", 502);
    }
    if (!isRecord(data.pagination) || !Number.isInteger(data.pagination.total)
      || !Number.isInteger(data.pagination.offset) || !Number.isInteger(data.pagination.limit)) {
      throw new ApiError("US_MAPPING compact 分页无效", 502);
    }
    const snapshot = normalizeSelectionSnapshot(data.snapshot);
    if (!snapshot) throw new ApiError("US_MAPPING selection 缺少保存版本身份", 502);
    const focusCountsPresent = data.focus_counts !== null && data.focus_counts !== undefined;
    const focusPolicyPresent = data.focus_policy !== null && data.focus_policy !== undefined;
    if (focusCountsPresent !== focusPolicyPresent) throw new ApiError("US_MAPPING 重点筛选计数与策略身份不完整", 502);
    const hasPersistedFocus = focusCountsPresent && focusPolicyPresent;
    const projectionValue = data.projection;
    if (projectionValue !== undefined && projectionValue !== "focus" && projectionValue !== "catalogue") {
      throw new ApiError("US_MAPPING 投影类型无效", 502);
    }
    if (data.listing_mode !== undefined && data.listing_mode !== "INDUSTRY_MATCH" && data.listing_mode !== "TRIGGERED_FOCUS") {
      throw new ApiError("US_MAPPING 保存名单类型无效", 502);
    }
    if (data.listing_mode === "TRIGGERED_FOCUS" && !hasPersistedFocus) {
      throw new ApiError("US_MAPPING 触发重点名单缺少已保存重点结果", 502);
    }
    const projection: USMappingProjection = (projectionValue as USMappingProjection | undefined)
      || (hasPersistedFocus ? requestedProjection : "catalogue");
    if (!hasPersistedFocus && projection === "focus") {
      throw new ApiError("US_MAPPING 缺少已保存重点结果，不能把候选目录当作重点名单", 502);
    }
    if (hasPersistedFocus && projection !== requestedProjection) {
      throw new ApiError("US_MAPPING 返回的保存投影与请求不一致", 502);
    }
    if (hasPersistedFocus) {
      const focusCounts = assertFocusCounts(data.focus_counts);
      assertFocusPolicy(data.focus_policy);
      const focusStocks = data.stocks as Record<string, unknown>[];
      for (const stock of focusStocks) {
        if (stock.focus_decision !== null && stock.focus_decision !== undefined) {
          const decision = assertFocusDecision(stock.focus_decision);
          if (decision.symbol !== stock.symbol || decision.decision !== stock.decision) {
            throw new ApiError("US_MAPPING 行与已保存重点结果身份不一致", 502);
          }
        }
        if (typeof stock.strict_decision !== "string" || typeof stock.strict_state !== "string") {
          throw new ApiError("US_MAPPING 缺少原严格结果参考", 502);
        }
        if (projection === "focus" && (!stock.focus_decision || stock.decision !== "SELECTED")) {
          throw new ApiError("US_MAPPING 重点投影包含非入选或无重点决策候选", 502);
        }
      }
      if (projection === "focus" && focusCounts.selected !== null && data.pagination.total !== focusCounts.selected) {
        throw new ApiError("US_MAPPING 重点名单分页总数与保存入选数不一致", 502);
      }
    }
    if (!hasPersistedFocus && data.listing_mode !== "INDUSTRY_MATCH"
      && data.stocks.some(stock => !isRecord(stock) || typeof stock.research_state !== "string"
        || typeof stock.strict_state !== "string" || typeof stock.decision !== "string")) {
      throw new ApiError("US_MAPPING 历史严格候选列表无效", 502);
    }
    if (data.listing_mode === "INDUSTRY_MATCH" && (
      typeof data.listing_policy_version !== "string" || !data.listing_policy_version
      || typeof data.listing_policy_sha256 !== "string" || !/^[a-f0-9]{64}$/i.test(data.listing_policy_sha256)
      || !isRecord(data.counts) || !Number.isInteger(data.counts.industry_match_count)
      || Number(data.counts.industry_match_count) < 0
      || data.stocks.some(stock => !hasValidIndustryMatches(stock))
    )) throw new ApiError("US_MAPPING 同行业名单缺少行业依据或来源身份", 502);
    if (projection === "catalogue" && data.listing_mode === "TRIGGERED_FOCUS" && hasPersistedFocus
      && data.stocks.some(stock => !hasValidIndustryMatches(stock))) {
      throw new ApiError("US_MAPPING 行业目录页缺少有效保存的同行业依据", 502);
    }
    const selectionStocks = data.stocks as unknown as USMappingCompactStock[];
    return {
      ...data,
      snapshot,
      stocks: [],
      counts: null,
      pagination: data.pagination as { total: number; offset: number; limit: number },
      us_mapping_selection: {
        ...(data.listing_mode === "INDUSTRY_MATCH" || data.listing_mode === "TRIGGERED_FOCUS" ? {
          listing_mode: data.listing_mode,
          ...(data.listing_policy_version ? { listing_policy_version: data.listing_policy_version } : {}),
          ...(data.listing_policy_sha256 ? { listing_policy_sha256: data.listing_policy_sha256 } : {})
        } : {}),
        projection,
        focus_counts: hasPersistedFocus ? assertFocusCounts(data.focus_counts) : null,
        focus_policy: hasPersistedFocus ? assertFocusPolicy(data.focus_policy) : null,
        selection_identity: identity,
        counts: assertSelectionCounts(data.counts),
        pagination: data.pagination as { total: number; offset: number; limit: number },
        stocks: selectionStocks,
        ...(isRecord(data.lane_sources) ? { lane_sources: data.lane_sources } : {})
      }
    } as unknown as import("./types").DayData;
  }
  const normalized = { ...data };
  if (Object.prototype.hasOwnProperty.call(data, "snapshot")) {
    normalized.snapshot = normalizeSelectionSnapshot(data.snapshot);
  }
  if (hasIdentity || data.legacy === true) normalized.us_mapping_legacy = true;
  return normalized as unknown as import("./types").DayData;
}
async function request<T>(
  transport: FetchLike, path: string, init: RequestInit = {}
): Promise<Envelope<T>> {
  let response: Response;
  try {
    response = await transport(BASE + path, {
      credentials: "same-origin",
      cache: "no-store",
      ...init,
      headers: { Accept: "application/json", ...(init.body ? { "Content-Type": "application/json" } : {}), ...init.headers }
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") throw error;
    throw new ApiError("网络读取失败，请核实 API 连接", 0);
  }
  let payload: unknown;
  try { payload = await response.json(); } catch { throw new ApiError("API 响应不是有效 JSON", response.status); }
  const envelope = payload as Partial<Envelope<T>> | null;
  if (!response.ok) {
    // B raises FastAPI HTTPException: actual error wire body is {detail},
    // not a successful manager-workbench envelope.
    const message = httpErrorDetail(payload) ??
      (envelope && typeof envelope.state === "string" ? envelope.state : "HTTP_" + response.status);
    const gaps = Array.isArray(envelope?.gaps) ? envelope.gaps : [];
    const codes = gaps.map(x => typeof x === "string" ? x : x?.code || x?.message || "").filter(Boolean);
    throw new ApiError(codes.length ? codes.join("；") : message, response.status, envelope?.gaps);
  }
  if (!envelope || envelope.schema_version !== SCHEMA_VERSION ||
      typeof envelope.state !== "string" || !("data" in envelope) ||
      envelope.RESEARCH_ONLY !== true || envelope.production_allowed !== false ||
      envelope.buy_gate_updated !== false || envelope.orders_sent !== false) {
    throw new ApiError("API 合同版本或响应外层无效", 502);
  }
  return envelope as Envelope<T>;
}
export function createWorkbenchApi(transport: FetchLike = fetch) {
  return {
    async getRecommendations(query: DayQuery, signal?: AbortSignal) {
      exactDate(query.date);
      if (query.lane !== 'US_MAPPING' && query.lane !== 'OVERSOLD') throw new ApiError('推荐来源无效', 422);
      const params = new URLSearchParams();
      if (query.phase) params.set('phase', query.phase);
      if (query.run_id) { assertRunId(query.run_id); params.set('run_id', query.run_id); }
      const offset = query.offset ?? 0, limit = query.limit ?? 50;
      if (!Number.isInteger(offset) || offset < 0 || !Number.isInteger(limit) || limit < 1 || limit > 200) throw new ApiError('分页参数无效', 422);
      params.set('offset', String(offset)); params.set('limit', String(limit));
      if (query.decision) params.set('decision', query.decision);
      if (query.q?.trim()) params.set('q', query.q.trim());
      if (query.lane === "US_MAPPING") {
        if (query.projection !== undefined && query.projection !== "focus" && query.projection !== "catalogue") {
          throw new ApiError("US_MAPPING 投影类型无效", 422);
        }
        params.set("view", "compact");
        params.set("projection", query.projection || "focus");
      }
      const result = await request<unknown>(transport,
        `/days/${query.date}/recommendations/${query.lane}?${params}`, { signal });
      if (query.lane !== "US_MAPPING") return result as Envelope<DayData>;
      return { ...result, data: normalizeCompactSelection(result.data, query.projection || "focus") } as Envelope<DayData>;
    },
    async getUSMappingDiagnostics(query: USMappingDiagnosticsQuery, signal?: AbortSignal) {
      exactDate(query.date); assertRunId(query.run_id);
      if (!/^HK\.[0-9]{5}$/.test(query.symbol)) throw new ApiError("非港股规范代码", 422);
      const relationshipOffset = query.relationship_offset ?? 0;
      const relationshipLimit = query.relationship_limit ?? 50;
      if (!Number.isInteger(relationshipOffset) || relationshipOffset < 0
        || !Number.isInteger(relationshipLimit) || relationshipLimit < 1 || relationshipLimit > 200) {
        throw new ApiError("关系分页参数无效", 422);
      }
      const params = new URLSearchParams({
        run_id: query.run_id, offset: "0", limit: "1", symbol: query.symbol,
        relationship_offset: String(relationshipOffset), relationship_limit: String(relationshipLimit),
        view: "diagnostics"
      });
      if (query.phase) params.set("phase", query.phase);
      return request<USMappingDiagnosticsData>(transport,
        `/days/${query.date}/recommendations/US_MAPPING?${params}`, { signal });
    },
    async getDay(query: DayQuery, signal?: AbortSignal) {
      exactDate(query.date);
      const params = new URLSearchParams();
      if (query.phase) params.set("phase", query.phase);
      if (query.run_id) { assertRunId(query.run_id); params.set("run_id", query.run_id); }
      const offset = query.offset ?? 0; const limit = query.limit ?? 50;
      if (!Number.isInteger(offset) || offset < 0 || !Number.isInteger(limit) || limit < 1 || limit > 200) {
        throw new ApiError("分页参数必须为 offset>=0、limit=1..200", 422);
      }
      params.set("offset", String(offset)); params.set("limit", String(limit));
      if (query.decision) params.set("decision", query.decision);
      if (query.lane) params.set("lane", query.lane);
      if (query.q?.trim()) params.set("q", query.q.trim());
      return request<DayData>(transport, "/days/" + query.date + "?" + params.toString(), { signal });
    },
    async getStock(symbol: string, date: string, runId: string, signal?: AbortSignal,
      recommendation?: { lane: RecommendationLane; row_id: string }) {
      exactDate(date); assertRunId(runId);
      if (!/^HK\.[0-9]{5}$/.test(symbol)) throw new ApiError("非港股规范代码", 422);
      const params = new URLSearchParams({ date, run_id: runId });
      if (recommendation) { params.set('lane', recommendation.lane); params.set('row_id', recommendation.row_id); }
      return request<StockDetails>(transport, "/stocks/" + encodeURIComponent(symbol) + "?" + params, { signal });
    },
    async getHistory(date: string, signal?: AbortSignal) {
      exactDate(date);
      return request<HistoryData>(transport, "/history?date=" + date, { signal });
    },
    async getReview(date: string, runId: string, signal?: AbortSignal) {
      exactDate(date); assertRunId(runId);
      return request<ReviewSummary>(transport,
        "/reviews/" + date + "?plan_run_id=" + encodeURIComponent(runId), { signal });
    },
    async getUsMappingCatalog(query: string, offset = 0, limit = 25, signal?: AbortSignal, researchUse = "") {
      if (query.length > 128) throw new ApiError("映射资料查询不能超过 128 个字符", 422);
      if (!Number.isInteger(offset) || offset < 0 || !Number.isInteger(limit) || limit < 1 || limit > 200) {
        throw new ApiError("资料分页参数无效", 422);
      }
      const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
      if (query.trim()) params.set("q", query.trim());
      if (researchUse) params.set("research_use", researchUse);
      return request<USMappingCatalogData>(transport, "/mapping-catalog?" + params.toString(), { signal });
    },
    async getAnnouncementFlash(targetDate?: string, signal?: AbortSignal) {
      const params = new URLSearchParams();
      if (targetDate) { exactDate(targetDate); params.set("target_date", targetDate); }
      const suffix = params.toString();
      return request<AnnouncementFlashData>(transport,
        "/announcement-flash" + (suffix ? "?" + suffix : ""), { signal });
    },
    async startAnnouncementFlashUpdate(targetDate: string) {
      exactDate(targetDate);
      return request<AnnouncementFlashUpdateAccepted>(transport, "/announcement-flash/update", {
        method: "POST", body: JSON.stringify({ target_date: targetDate })
      });
    },
    async stopAnnouncementFlash(jobId: string) {
      if (!/^[0-9a-f]{32}$/.test(jobId)) throw new ApiError("公告任务编号无效", 422);
      return request<{ job_id: string; state: string }>(transport, `/announcement-flash/${jobId}/stop`, { method: "POST" });
    },
    async executePreprocessedAnnouncement(jobId: string, reportSha: string, phase: "FIRST" | "CONTINUE" | "RECOVER_FAILED" | "CONTINUE_REMAINING", firstDeliverySha?: string, extensionSha?: string) {
      if (!/^[0-9a-f]{32}$/.test(jobId) || !/^[0-9a-f]{64}$/.test(reportSha)) throw new ApiError("预处理来源绑定无效", 422);
      return request<{ job_id: string; phase: string; report_sha256: string }>(transport,
        `/announcement-flash/${jobId}/execute-preprocessed`, { method: "POST",
          body: JSON.stringify({ report_sha256: reportSha, phase, first_delivery_sha256: firstDeliverySha || null, ...(extensionSha ? { extension_sha256: extensionSha } : {}) }) });
    },
    async resumeAnnouncementFlash(targetDate: string, resume: AnnouncementFlashResumeEligibility,
                                  resumeAction: "CANARY" | "CONTINUE") {
      exactDate(targetDate);
      if (!resume.eligible || resume.target_date !== targetDate || !resume.source_job_id
        || !resume.source_input_sha256 || !resume.source_progress_sha256 || !resume.source_queue_state_sha256
        || resume.resume_action !== resumeAction
        || (resumeAction === "CONTINUE" && (resume.canary_passed !== true
          || resume.canary_validation?.status !== "PASS"))) {
        throw new ApiError("续跑资格或来源 SHA 无效", 409);
      }
      return request<AnnouncementFlashResumeAccepted>(transport, "/announcement-flash/resume", {
        method: "POST",
        body: JSON.stringify({
          target_date: targetDate,
          source_job_id: resume.source_job_id,
          source_input_sha256: resume.source_input_sha256,
          source_progress_sha256: resume.source_progress_sha256,
          source_queue_state_sha256: resume.source_queue_state_sha256,
          resume_action: resumeAction,
        })
      });
    },
    async createRun(date: string, phase: "MANUAL" | "RETROSPECTIVE", lanes?: Lane[]) {
      exactDate(date);
      if (phase !== "MANUAL" && phase !== "RETROSPECTIVE") throw new ApiError("手动阶段无效", 422);
      return request<JobCreated>(transport, "/runs", {
        method: "POST", body: JSON.stringify({ target_date: date, phase, ...(lanes?.length ? { lanes } : {}) })
      });
    },
    async getJob(jobId: string, signal?: AbortSignal) {
      assertRunId(jobId);
      return request<JobRecord>(transport, "/runs/" + encodeURIComponent(jobId), { signal });
    },
    async retryJob(jobId: string) {
      assertRunId(jobId);
      return request<JobCreated>(transport, "/runs/" + encodeURIComponent(jobId) + "/retry", {
        method: "POST", body: "{}"
      });
    }
  };
}
export type WorkbenchApi = ReturnType<typeof createWorkbenchApi>;
