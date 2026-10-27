export const ORIGINAL_FORMULA_VERSION = "ACTIVE_MA_USER_20261021_V1";
export type HistoryRow = Record<string, string | number | boolean | null> & { ts_code: string; trade_date: string };
export interface HistoryRequest { ts_code: string; start_date: string; end_date: string }
export interface AShareHistory {
  schema_version: string; status: "READY" | "EMPTY_EXACT_RANGE" | "CANNOT_CONFIRM";
  ts_code: string; start_date: string; end_date: string; formula_version: string;
  profile_id: string; rows: HistoryRow[]; cannot_confirm: string[];
  identity?: { generation_id: string; input_sha256: string; manifest_sha256: string;
    artifact_sha256: string; formula_source_sha256: string; asof_date: number;
    verification_basis: string; historical_PIT: false; maximum_claim: string };
}

export async function loadAShareHistory(request: HistoryRequest, signal: AbortSignal): Promise<AShareHistory> {
  const query = new URLSearchParams({ ...request, formula_version: ORIGINAL_FORMULA_VERSION });
  const response = await fetch(`/api/v3/research/a-share/history?${query}`, { signal });
  if (!response.ok) throw new Error(`历史读取失败（${response.status}）`);
  const result = await response.json() as AShareHistory;
  if (result.schema_version !== "v4.a_share_original_formula_history.v1"
      || !["READY", "EMPTY_EXACT_RANGE", "CANNOT_CONFIRM"].includes(result.status)
      || result.ts_code !== request.ts_code || result.start_date !== request.start_date
      || result.end_date !== request.end_date || result.formula_version !== ORIGINAL_FORMULA_VERSION
      || result.profile_id !== ORIGINAL_FORMULA_VERSION || !Array.isArray(result.rows)) {
    throw new Error("响应代码、日期或公式身份不一致，已清除旧结果");
  }
  if (result.status !== "CANNOT_CONFIRM") {
    const identity = result.identity;
    if (!identity || ![identity.generation_id, identity.input_sha256, identity.manifest_sha256,
      identity.artifact_sha256, identity.formula_source_sha256].every((v) => /^[a-f0-9]{64}$/.test(v))
      || result.rows.some((row) => row.ts_code !== request.ts_code
        || row.trade_date < request.start_date || row.trade_date > request.end_date)) {
      throw new Error("共享面板来源身份或精确范围不完整，已清除旧结果");
    }
  }
  return result;
}
