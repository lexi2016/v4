/**
 * Read-only contract for the exact-date preselection pool consumed by the
 * manager workbench. The producer owns the wire shape; unknown descriptive
 * fields are retained so the UI does not invent or rewrite evidence.
 */

export type ManagerPreselectionValue =
  | string
  | number
  | boolean
  | null
  | unknown[]
  | { [key: string]: unknown };

export type ManagerPreselectionRow = Readonly<Record<string, unknown>> & {
  market?: string;
  symbol?: string;
  code?: string;
  code_norm?: string;
  ts_code?: string;
  stock_name?: string;
  name?: string;
  display_name?: string;
  pool_id?: string;
  pool_rank?: number | string;
  rank?: number | string;
  pool_score?: number | string;
  signal_date?: string;
  source_date?: string;
  target_date?: string;
  trade_date?: string;
  recommendation_status?: string;
  trade_status_contract?: string;
  research_only?: boolean | string;
  production_allowed?: boolean;
  buy_gate_updated?: boolean;
  orders_sent?: boolean;
};

export type ManagerPreselectionPool = Readonly<Record<string, unknown>> & {
  pool_id?: string;
  display_name?: string;
  market?: string;
  pool_size?: number;
  returned_rows?: number;
  rows?: ManagerPreselectionRow[];
  status?: string;
  recommendation_status?: string;
  producer_id?: string;
  source_path?: string;
  source_role?: string;
  source_row_count?: number;
  source_run_id?: string;
  source_sha256?: string;
  trade_date?: string;
  production_allowed?: boolean;
  buy_gate_updated?: boolean;
  orders_sent?: boolean;
  cannot_confirm?: unknown;
};

export type ManagerPreselectionResponse = Readonly<Record<string, unknown>> & {
  schema_version?: string;
  module_id?: string;
  write_policy?: string;
  ok?: boolean;
  data_status?: string;
  requested_date?: string;
  selected_date?: string;
  trade_date?: string;
  pools?: ManagerPreselectionPool[];
  production_allowed?: boolean;
  buy_gate_updated?: boolean;
  orders_sent?: boolean;
  cannot_confirm?: unknown;
};

export type ManagerResearchQueueEntry = {
  poolRow: ManagerPreselectionRow;
  selectionCandidate: Readonly<Record<string, unknown>>;
  normalizedCode: string;
};

const PRESELECTION_SCHEMA_VERSION = "v3_preselection_pools.v1";
const PRESELECTION_MODULE_ID = "unified_preselection_pools";
const PRESELECTION_POOL_ID = "hkconnect_d1_top100";
const PRESELECTION_POOL_STATUS = "STRICT_0_2_READY";
const DATE_PATTERN = /^\d{8}$/;
const CODE_PATTERN = /^\d{1,5}$/;
const SHA256_PATTERN = /^[0-9a-f]{64}$/i;

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isValidDate(value: unknown): value is string {
  if (typeof value !== "string" || !DATE_PATTERN.test(value)) return false;
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(4, 6));
  const day = Number(value.slice(6, 8));
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year
    && date.getUTCMonth() === month - 1
    && date.getUTCDate() === day;
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function exactDate(value: unknown, date: string, label: string): string | null {
  return value === date ? null : `${label} 与请求日期不一致`;
}

function finiteNumber(value: unknown, label: string): string | null {
  const numeric = typeof value === "number"
    ? value
    : typeof value === "string" && value.trim() ? Number(value) : Number.NaN;
  return Number.isFinite(numeric) ? null : `${label} 不是有限数字`;
}

/** Keep exchange prefixes but compare the canonical numeric HK code. */
export function normalizeManagerHkCode(value: unknown): string | null {
  if (typeof value !== "string" && typeof value !== "number") return null;
  if (typeof value === "number" && !Number.isInteger(value)) return null;
  let code = String(value).trim().toUpperCase();
  if (code.startsWith("HK.")) code = code.slice(3);
  if (code.endsWith(".HK_CONNECT")) code = code.slice(0, -".HK_CONNECT".length);
  else if (code.endsWith(".HK")) code = code.slice(0, -3);
  if (!CODE_PATTERN.test(code)) return null;
  return code.padStart(5, "0");
}

const ROW_CODE_FIELDS = ["code", "symbol", "code_norm", "ts_code"] as const;

function rowCode(row: ManagerPreselectionRow): string | null {
  const aliases = ROW_CODE_FIELDS
    .filter((field) => row[field] !== undefined && row[field] !== null && row[field] !== "")
    .map((field) => normalizeManagerHkCode(row[field]));
  if (!aliases.length || aliases.some((code) => code === null)) return null;
  const first = aliases[0];
  return aliases.every((code) => code === first) ? first : null;
}

function rowName(row: ManagerPreselectionRow): string | null {
  for (const field of ["stock_name", "name", "display_name"]) {
    if (nonEmptyString(row[field])) return String(row[field]);
  }
  return null;
}

function validReadOnlyFlag(value: unknown, expected: boolean, label: string): string | null {
  return value === expected ? null : `${label} 必须是 ${String(expected)}`;
}

function strictRank(value: unknown): number | null {
  if (typeof value === "number") return Number.isInteger(value) ? value : null;
  if (typeof value !== "string" || !/^[1-9]\d*$/.test(value)) return null;
  const rank = Number(value);
  return Number.isSafeInteger(rank) ? rank : null;
}

function optionalDate(value: unknown, targetDate: string, label: string): string | null {
  if (value === undefined) return null;
  if (!isValidDate(value)) return `${label} 不是有效日期`;
  return exactDate(value, targetDate, label);
}

function validateRow(row: unknown, date: string, index: number): string | null {
  if (!isRecord(row)) return `HK D-1 row[${index}] 不是对象`;
  const typed = row as ManagerPreselectionRow;
  if (typed.market !== undefined && typed.market !== "HK") return `HK D-1 row[${index}] market 必须是 HK`;
  if (typed.pool_id !== undefined && typed.pool_id !== PRESELECTION_POOL_ID) return `HK D-1 row[${index}] pool_id 不匹配`;
  const rank = strictRank(typed.pool_rank);
  if (rank === null || rank < 1 || rank > 100) {
    return `HK D-1 row[${index}] pool_rank 必须覆盖 1..100`;
  }
  if (rowCode(typed) === null) return `HK D-1 row[${index}] code 不可确认`;
  const optionalTargetDate = optionalDate(typed.target_date, date, `HK D-1 row[${index}].target_date`);
  if (optionalTargetDate) return optionalTargetDate;
  const optionalTradeDate = optionalDate(typed.trade_date, date, `HK D-1 row[${index}].trade_date`);
  if (optionalTradeDate) return optionalTradeDate;
  if (typed.signal_date !== undefined && !isValidDate(typed.signal_date)) {
    return `HK D-1 row[${index}].signal_date 不是有效日期`;
  }
  if (typed.recommendation_status !== undefined && typed.recommendation_status !== "WATCH_ONLY") {
    return `HK D-1 row[${index}] recommendation_status 必须是 WATCH_ONLY`;
  }
  if (typed.trade_status_contract !== undefined && typed.trade_status_contract !== "WATCH_ONLY") {
    return `HK D-1 row[${index}] trade_status_contract 必须是 WATCH_ONLY`;
  }
  if (typed.research_only !== undefined
    && typed.research_only !== true
    && typed.research_only !== "True"
    && typed.research_only !== "true") {
    return `HK D-1 row[${index}] research_only 必须为 true`;
  }
  if (typed.pool_score !== undefined) {
    const scoreIssue = finiteNumber(typed.pool_score, `HK D-1 row[${index}].pool_score`);
    if (scoreIssue) return scoreIssue;
  }
  if (typed.rank !== undefined) {
    const rowRank = strictRank(typed.rank);
    if (rowRank === null || rowRank !== rank) return `HK D-1 row[${index}] rank 与 pool_rank 不一致`;
  }
  for (const [field, expected] of [
    ["production_allowed", false],
    ["buy_gate_updated", false],
    ["orders_sent", false],
  ] as const) {
    if (typed[field] !== undefined) {
      const issue = validReadOnlyFlag(typed[field], expected, `HK D-1 row[${index}].${field}`);
      if (issue) return issue;
    }
  }
  return null;
}

/**
 * Validate the exact-date HK D-1 pool without narrowing away producer fields.
 * The validator returns an issue instead of throwing, so malformed upstream
 * payloads cannot become an empty or apparently-ready queue.
 */
export function validateManagerPreselection(value: unknown, targetDate: string): string | null {
  if (!isValidDate(targetDate)) return "请求日期不是有效的 YYYYMMDD 日期";
  if (!isRecord(value)) return "preselection 响应不是对象";
  if (value.schema_version !== PRESELECTION_SCHEMA_VERSION) return `schema_version 不是 ${PRESELECTION_SCHEMA_VERSION}`;
  if (value.module_id !== PRESELECTION_MODULE_ID) return "module_id 不匹配 unified_preselection_pools";
  if (value.write_policy !== "read_only") return "write_policy 必须是 read_only";
  if (value.ok !== true) return "preselection 响应 ok 不是 true";
  if (value.data_status !== "READY_WITH_ROWS" && value.data_status !== "PARTIAL_WITH_ROWS") {
    return "preselection data_status 必须是 READY_WITH_ROWS 或 PARTIAL_WITH_ROWS";
  }
  for (const [field, label] of [
    ["requested_date", "requested_date"],
    ["selected_date", "selected_date"],
    ["trade_date", "trade_date"],
  ] as const) {
    if (!isValidDate(value[field])) return `${label} 不是有效日期`;
    const issue = exactDate(value[field], targetDate, label);
    if (issue) return issue;
  }
  for (const [field, expected] of [
    ["production_allowed", false],
    ["buy_gate_updated", false],
    ["orders_sent", false],
  ] as const) {
    const issue = validReadOnlyFlag(value[field], expected, field);
    if (issue) return issue;
  }
  if (!Array.isArray(value.cannot_confirm) || value.cannot_confirm.some((item) => typeof item !== "string")) {
    return "preselection cannot_confirm 必须是字符串数组";
  }
  if (!Array.isArray(value.pools)) return "preselection pools 不是数组";
  if (value.pools.some((pool) => !isRecord(pool))) return "preselection pools 含非对象项";
  const hkPools = value.pools.filter((pool) => isRecord(pool) && pool.pool_id === PRESELECTION_POOL_ID);
  if (hkPools.length !== 1) return "HK D-1 pool 必须恰好存在一个";
  const hk = hkPools[0] as ManagerPreselectionPool;
  if (hk.status !== PRESELECTION_POOL_STATUS) return "HK D-1 pool status 不是 STRICT_0_2_READY";
  if (hk.market !== "HK") return "HK D-1 pool market 必须是 HK";
  if (hk.trade_date !== targetDate) return "HK D-1 pool trade_date 与请求日期不一致";
  if (hk.pool_size !== 100 || hk.returned_rows !== 100) return "HK D-1 pool 必须声明 100 行";
  if (hk.source_row_count !== 100) return "HK D-1 pool source_row_count 必须是 100";
  if (!nonEmptyString(hk.source_role) || hk.source_role !== "SHARED_VERIFIED_HK_0_2") {
    return "HK D-1 pool source_role 不可确认";
  }
  if (!nonEmptyString(hk.source_run_id)) return "HK D-1 pool source_run_id 不可确认";
  if (!nonEmptyString(hk.producer_id)) return "HK D-1 pool producer_id 不可确认";
  if (!nonEmptyString(hk.source_sha256) || !SHA256_PATTERN.test(hk.source_sha256)) {
    return "HK D-1 pool source_sha256 不可确认";
  }
  if (!Array.isArray(hk.cannot_confirm) || hk.cannot_confirm.some((item) => typeof item !== "string")) {
    return "HK D-1 pool cannot_confirm 必须是字符串数组";
  }
  for (const [field, expected] of [
    ["production_allowed", false],
    ["buy_gate_updated", false],
    ["orders_sent", false],
  ] as const) {
    const issue = validReadOnlyFlag(hk[field], expected, `HK D-1 pool.${field}`);
    if (issue) return issue;
  }
  if (!Array.isArray(hk.rows) || hk.rows.length !== 100) return "HK D-1 pool rows 必须是 100 行";
  const declaredRankCounts = new Map<number, number>();
  for (const row of hk.rows) {
    if (!isRecord(row)) continue;
    const rank = strictRank(row.pool_rank);
    if (rank !== null) declaredRankCounts.set(rank, (declaredRankCounts.get(rank) || 0) + 1);
  }
  for (const [rank, count] of declaredRankCounts) {
    if (count > 1) return `HK D-1 pool 含重复 pool_rank=${rank}`;
  }
  const ranks = new Set<number>();
  const codes = new Set<string>();
  for (let index = 0; index < hk.rows.length; index += 1) {
    const issue = validateRow(hk.rows[index], targetDate, index);
    if (issue) return issue;
    const row = hk.rows[index];
    const rank = strictRank(row.pool_rank);
    if (rank === null) return `HK D-1 pool row[${index}] pool_rank 不可确认`;
    if (ranks.has(rank)) return `HK D-1 pool 含重复 pool_rank=${rank}`;
    ranks.add(rank);
    const code = rowCode(row);
    if (!code) return `HK D-1 pool row[${index}] code 不可确认`;
    if (codes.has(code)) return `HK D-1 pool 含重复 code=${code}`;
    codes.add(code);
  }
  for (let rank = 1; rank <= 100; rank += 1) {
    if (!ranks.has(rank)) return `HK D-1 pool 缺少 pool_rank=${rank}`;
  }
  return null;
}

export function getManagerHkPool(value: ManagerPreselectionResponse): ManagerPreselectionPool | null {
  if (!Array.isArray(value.pools)) return null;
  return value.pools.find((pool) => pool?.pool_id === PRESELECTION_POOL_ID) ?? null;
}

export function getManagerHkPoolRows(value: ManagerPreselectionResponse): ManagerPreselectionRow[] {
  return getManagerHkPool(value)?.rows ?? [];
}

export function managerPreselectionCode(row: ManagerPreselectionRow): string | null {
  return rowCode(row);
}

function candidateCode(candidate: Readonly<Record<string, unknown>>): string | null {
  return normalizeManagerHkCode(
    candidate.normalized_code ?? candidate.entity_id ?? candidate.candidate_id,
  );
}

/**
 * Join the validated HK D-1 pool to the validated research ledger by the
 * canonical numeric HK code. A duplicate research identity is ambiguous and
 * therefore blocks the queue instead of silently choosing one event.
 */
export function buildManagerResearchQueue(
  rows: readonly ManagerPreselectionRow[],
  candidates: readonly Readonly<Record<string, unknown>>[],
): { entries: ManagerResearchQueueEntry[]; issue: string | null } {
  const byCode = new Map<string, Readonly<Record<string, unknown>>>();
  for (const candidate of candidates) {
    const code = candidateCode(candidate);
    if (!code) return { entries: [], issue: "selection candidate code 不可确认" };
    if (byCode.has(code)) return { entries: [], issue: `selection candidate code 重复: ${code}` };
    byCode.set(code, candidate);
  }
  const entries: ManagerResearchQueueEntry[] = [];
  for (const row of rows) {
    const code = rowCode(row);
    if (!code) return { entries: [], issue: "HK D-1 row code 不可确认" };
    const selectionCandidate = byCode.get(code);
    if (selectionCandidate) entries.push({ poolRow: row, selectionCandidate, normalizedCode: code });
  }
  entries.sort((left, right) => Number(left.poolRow.pool_rank) - Number(right.poolRow.pool_rank));
  return { entries, issue: null };
}
