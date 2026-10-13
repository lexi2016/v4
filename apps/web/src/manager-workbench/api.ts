import { SCHEMA_VERSION } from "./types";
import type {
  DayData, Decision, Envelope, HistoryData, JobCreated, JobRecord, Lane,
  Phase, ReviewSummary, StockDetails
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
  q?: string;
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
    async getStock(symbol: string, date: string, runId: string, signal?: AbortSignal) {
      exactDate(date); assertRunId(runId);
      if (!/^HK\.[0-9]{5}$/.test(symbol)) throw new ApiError("非港股规范代码", 422);
      const params = new URLSearchParams({ date, run_id: runId });
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
