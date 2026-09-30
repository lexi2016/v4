import { normalizeManagerHkCode } from "./managerPreselection";

/**
 * Read-only projection used by the manager's HK stage panel.
 *
 * The producer response may contain both A-share and Hong Kong lanes.  This
 * consumer deliberately binds to the aliased ``markets.HK`` lane whose market
 * identity is ``HK_CONNECT``.  It never reads ``unified_rows`` because that
 * projection is allowed to contain both lanes.  Some stage-center responses
 * carry the market identity on the market envelope rather than repeating it
 * on every row, so an absent row-level market is accepted only inside that
 * already-validated HK_CONNECT envelope.
 */

export const MANAGER_STAGE_ID = "STAGE_0935_0940" as const;
export const MANAGER_STAGE_MARKET_KEY = "HK" as const;
export const MANAGER_STAGE_MARKET = "HK_CONNECT" as const;
export const MANAGER_STAGE_STATUS_VALUES = [
  "READY",
  "PARTIAL_WITH_ROWS",
  "READY_EMPTY",
  "CANNOT_CONFIRM",
] as const;

export type ManagerStageStatus = typeof MANAGER_STAGE_STATUS_VALUES[number];

export type ManagerStageSelectionRow = Readonly<Record<string, unknown>> & {
  market?: string;
  code?: string;
  symbol?: string;
  name?: string;
  stock_name?: string;
  display_name?: string;
  rank?: number | string;
  score?: number | string;
  stage_score?: number | string;
  stage_rank_score?: number | string;
  stage_rtdata_score?: number | string;
  stage_window_change_pct?: number | string | null;
  stage_change_pct?: number | string | null;
  stage_gain_pct?: number | string | null;
  daily_change_pct?: number | string | null;
  daily_gain_pct?: number | string | null;
  relative_prev_close_pct?: number | string | null;
  d1_prob_active?: number | string | null;
  prob_active?: number | string | null;
  d1_rank?: number | string;
  d1_score?: number | string;
  score_prob_active?: number | string | null;
  pool_rank?: number | string;
  pool_score?: number | string | null;
  selected_strategy?: string;
  candidate_lanes?: unknown;
  action_level?: string;
  trade_status?: string;
  trade_status_contract?: string;
  source_refs?: unknown;
  source_ref?: unknown;
  d1_source_refs?: unknown;
  d1_source_ref?: unknown;
  d1_source_evidence?: unknown;
  stage_source_refs?: unknown;
  stage_source_ref?: unknown;
  stage_source_evidence?: unknown;
  current_change_pct?: number | string | null;
  pct_chg?: number | string | null;
  volume_ratio?: number | string | null;
  turnover?: number | string | null;
};

export type ManagerStageMarket = Readonly<Record<string, unknown>> & {
  market?: string;
  status?: string;
  selection_status?: string;
  rows?: unknown;
  selected_rows?: number | null;
  candidate_count?: number | null;
};

export type ManagerStageSelectionResponse = Readonly<Record<string, unknown>> & {
  schema_version?: string;
  response_source?: string;
  trade_date?: string;
  stage_id?: string;
  status?: string;
  markets?: Readonly<Record<string, unknown>>;
  selection_markets?: Readonly<Record<string, unknown>>;
  market_summaries?: Readonly<Record<string, unknown>>;
  unified_rows?: unknown;
  run_id?: string | null;
  artifact_id?: string | null;
  bundle_artifact_id?: string | null;
  cannot_confirm?: unknown;
  RESEARCH_ONLY?: boolean;
  write_performed?: boolean;
  production_allowed?: boolean;
  buy_gate_updated?: boolean;
  orders_sent?: boolean;
};

const DATE_PATTERN = /^\d{8}$/;

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

function nonEmpty(value: unknown): boolean {
  return typeof value === "string" ? value.trim().length > 0 : value !== undefined && value !== null;
}

function strictRank(value: unknown): number | null {
  if (typeof value === "number") return Number.isInteger(value) ? value : null;
  if (typeof value !== "string" || !/^[1-9]\d*$/.test(value)) return null;
  const rank = Number(value);
  return Number.isSafeInteger(rank) ? rank : null;
}

function canonicalStageCode(row: ManagerStageSelectionRow): string | null {
  const aliases = ["code", "symbol"]
    .filter((field) => {
      const value = row[field as "code" | "symbol"];
      return value !== undefined && value !== null && value !== "";
    })
    .map((field) => normalizeManagerHkCode(row[field as "code" | "symbol"]));
  if (!aliases.length || aliases.some((code) => code === null)) return null;
  const first = aliases[0];
  return aliases.every((code) => code === first) ? first : null;
}

export function isManagerStageStatus(value: unknown): value is ManagerStageStatus {
  return typeof value === "string"
    && (MANAGER_STAGE_STATUS_VALUES as readonly string[]).includes(value);
}

function stageMarket(value: unknown): ManagerStageMarket | null {
  if (!isRecord(value)) return null;
  return value as ManagerStageMarket;
}

function projectedHkRows(market: ManagerStageMarket | null): ManagerStageSelectionRow[] {
  if (!market || !Array.isArray(market.rows)) return [];
  if (market.rows.some((row) => !isRecord(row))) return [];
  return market.rows.map((row) => row as ManagerStageSelectionRow);
}

function hasSelectedRows(market: ManagerStageMarket): boolean {
  return Object.prototype.hasOwnProperty.call(market, "selected_rows");
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function isRenderableHkMarket(market: ManagerStageMarket | null): boolean {
  if (!market
    || market.market !== MANAGER_STAGE_MARKET
    || !isManagerStageStatus(market.status)
    || !isManagerStageStatus(market.selection_status)
    || market.status !== market.selection_status
    || market.status === "CANNOT_CONFIRM"
    || !Array.isArray(market.rows)
    || !hasSelectedRows(market)
    || !isNonNegativeInteger(market.selected_rows)) {
    return false;
  }
  const rows = projectedHkRows(market);
  if (rows.length !== market.rows.length) return false;
  const codes = new Set<string>();
  const ranks = new Set<number>();
  for (const row of rows) {
    if (row.market !== undefined && row.market !== MANAGER_STAGE_MARKET) return false;
    const code = canonicalStageCode(row);
    const rank = strictRank(row.rank);
    if (!code || codes.has(code) || rank === null || rank < 1 || rank > rows.length || ranks.has(rank)) return false;
    codes.add(code);
    ranks.add(rank);
  }
  if ([...ranks].some((rank, index) => rank !== index + 1)) return false;
  if (market.selected_rows !== rows.length) return false;
  return market.status === "READY_EMPTY"
    ? rows.length === 0
    : rows.length > 0;
}

/** Return only the aliased HK lane; there is intentionally no A fallback. */
export function getManagerHkStageMarket(value: unknown): ManagerStageMarket | null {
  if (!isRecord(value)) return null;
  return stageMarket(value.markets && isRecord(value.markets)
    ? value.markets[MANAGER_STAGE_MARKET_KEY]
    : undefined);
}

/**
 * Project the HK lane without consulting ``unified_rows`` or the A-share lane.
 * The validator treats the lane atomically; malformed rows never get filtered
 * into a smaller, apparently valid result.
 */
export function getManagerHkStageRows(value: unknown): ManagerStageSelectionRow[] {
  if (!isRecord(value) || !isManagerStageStatus(value.status) || value.status === "CANNOT_CONFIRM") return [];
  const market = getManagerHkStageMarket(value);
  if (!isRenderableHkMarket(market)) return [];
  return projectedHkRows(market);
}

/** A defensive view guard: only a fully consistent, non-CANNOT_CONFIRM HK lane can render. */
export function isManagerHkStageRenderable(value: unknown): boolean {
  if (!isRecord(value) || !isManagerStageStatus(value.status) || value.status === "CANNOT_CONFIRM") return false;
  return isRenderableHkMarket(getManagerHkStageMarket(value));
}

/**
 * Validate the minimum exact-date/market boundary required for presentation.
 * Any mismatch is rendered as CANNOT_CONFIRM by the caller; no lane is
 * substituted when the HK lane is missing.
 */
export function validateManagerStageSelection(value: unknown, targetDate: string): string | null {
  if (!isValidDate(targetDate)) return "请求日期不是有效的 YYYYMMDD 日期";
  if (!isRecord(value)) return "stage selection 响应不是对象";
  if (value.trade_date !== targetDate) return "stage selection trade_date 与请求日期不一致";
  if (value.stage_id !== MANAGER_STAGE_ID) return `stage selection stage_id 必须是 ${MANAGER_STAGE_ID}`;
  if (!isManagerStageStatus(value.status)) {
    return "stage selection status 必须是 READY/PARTIAL_WITH_ROWS/READY_EMPTY/CANNOT_CONFIRM";
  }
  if (value.RESEARCH_ONLY !== undefined && value.RESEARCH_ONLY !== true) {
    return "RESEARCH_ONLY 必须是 true";
  }
  for (const [field, expected] of [
    ["production_allowed", false],
    ["buy_gate_updated", false],
    ["orders_sent", false],
    ["write_performed", false],
  ] as const) {
    if (value[field] !== undefined && value[field] !== expected) {
      return `${field} 必须是 ${String(expected)}`;
    }
  }
  if (!isRecord(value.markets)) return "stage selection markets 不可确认";
  const hk = stageMarket(value.markets[MANAGER_STAGE_MARKET_KEY]);
  if (!hk) return "stage selection markets.HK 缺失";
  if (hk.market !== MANAGER_STAGE_MARKET) {
    return `stage selection markets.HK.market 必须是 ${MANAGER_STAGE_MARKET}`;
  }
  if (!isManagerStageStatus(hk.status)) {
    return "stage selection markets.HK.status 必须是 READY/PARTIAL_WITH_ROWS/READY_EMPTY/CANNOT_CONFIRM";
  }
  if (!isManagerStageStatus(hk.selection_status)) {
    return "stage selection markets.HK.selection_status 必须是 READY/PARTIAL_WITH_ROWS/READY_EMPTY/CANNOT_CONFIRM";
  }
  if (hk.status !== hk.selection_status) {
    return "stage selection markets.HK.status 与 selection_status 不一致";
  }
  if (!Array.isArray(hk.rows)) return "stage selection markets.HK.rows 不是数组";
  const ranks = new Set<number>();
  const codes = new Set<string>();
  for (let index = 0; index < hk.rows.length; index += 1) {
    const row = hk.rows[index];
    if (!isRecord(row)) return `stage selection markets.HK.rows[${index}] 不是对象`;
    if (row.market !== undefined && row.market !== MANAGER_STAGE_MARKET) {
      return `stage selection markets.HK.rows[${index}] market 必须是 ${MANAGER_STAGE_MARKET}`;
    }
    const typedRow = row as ManagerStageSelectionRow;
    const code = canonicalStageCode(typedRow);
    if (!code) {
      return `stage selection markets.HK.rows[${index}] code 不可确认`;
    }
    if (codes.has(code)) return `stage selection markets.HK.rows[${index}] code 重复`;
    codes.add(code);
    const rank = strictRank(typedRow.rank);
    if (rank === null || rank < 1 || rank > hk.rows.length) {
      return `stage selection markets.HK.rows[${index}] rank 必须是 1..N 正整数`;
    }
    if (ranks.has(rank)) return `stage selection markets.HK.rows[${index}] rank 重复`;
    ranks.add(rank);
  }
  for (let rank = 1; rank <= hk.rows.length; rank += 1) {
    if (!ranks.has(rank)) return `stage selection markets.HK.rows 缺少 rank=${rank}`;
  }
  if (!hasSelectedRows(hk)) return "stage selection markets.HK.selected_rows 缺失";
  if (hk.status === "CANNOT_CONFIRM") {
    if (hk.rows.length > 0) return "stage selection markets.HK.status=CANNOT_CONFIRM 必须保持空 rows";
    if (hk.selected_rows !== null && hk.selected_rows !== 0) {
      return "stage selection markets.HK.selected_rows 在 CANNOT_CONFIRM 时必须是 0 或 null";
    }
    return null;
  }
  if (!isNonNegativeInteger(hk.selected_rows)) {
    return "stage selection markets.HK.selected_rows 必须是非负整数";
  }
  const projectedRows = projectedHkRows(hk);
  if (hk.selected_rows !== projectedRows.length) {
    return "stage selection markets.HK.selected_rows 与 rows 不一致";
  }
  if (hk.status === "READY_EMPTY" && projectedRows.length !== 0) {
    return "stage selection markets.HK READY_EMPTY 必须没有 rows";
  }
  if (hk.status !== "READY_EMPTY" && projectedRows.length === 0) {
    return "stage selection markets.HK READY/PARTIAL_WITH_ROWS 必须带 rows";
  }
  return null;
}
