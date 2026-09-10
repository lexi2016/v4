import type { ResearchLane } from "../../api/research_lane";
import type {
  ManagerResearchProduct,
  ManagerResearchResponse,
  ManagerResearchRow,
} from "../../api/managerResearch";
import { normalizeManagerHkCode } from "../../contracts/managerPreselection";
import {
  MANAGER_STAGE_ID,
  MANAGER_STAGE_MARKET,
  type ManagerStageSelectionRow,
} from "../../contracts/managerStageSelection";

/**
 * Browser-only projection for the 09:40 HK observation card.
 *
 * This adapter deliberately separates "the source exists" from "the source
 * is joined to this stock".  A title, issuer name, or a thematic sentence is
 * never an identity join.  A contribution can become JOINED only when a
 * target-date reference is present (and, for lane rows, an explicit stock
 * code is present as well).
 */

export const STAGE_REASON_CONTRIBUTION_KEYS = [
  "d1",
  "stage_market",
  "us_finance",
  "hkex_notice",
  "sentiment",
] as const;

export type StageReasonContributionKey = typeof STAGE_REASON_CONTRIBUTION_KEYS[number];

export const STAGE_REASON_CONTRIBUTION_STATUSES = [
  "JOINED",
  "AVAILABLE_NOT_JOINED",
  "UPSTREAM_MISSING",
  "CANNOT_CONFIRM",
] as const;

export type StageReasonContributionStatus = typeof STAGE_REASON_CONTRIBUTION_STATUSES[number];

export type StageReasonEvidenceRef = Readonly<Record<string, unknown>> | string;

export type StageReasonContributionDetail = Readonly<{
  title: string;
  source: string;
  published_at?: string;
  fetched_at?: string;
  source_url?: string;
  stock_code?: string;
  stock_name?: string;
  note?: string;
}>;

export type StageReasonContribution = Readonly<{
  key: StageReasonContributionKey;
  label: string;
  status: StageReasonContributionStatus;
  human_text: string;
  refs: readonly StageReasonEvidenceRef[];
  details?: readonly StageReasonContributionDetail[];
  metadata?: Readonly<Record<string, unknown>>;
}>;

export type StageReasonContributions = Readonly<
  Record<StageReasonContributionKey, StageReasonContribution>
>;

export type StageReasonContributionsInput = Readonly<{
  row: ManagerStageSelectionRow | Readonly<Record<string, unknown>>;
  targetDate: string;
  researchLane?: ResearchLane | Readonly<Record<string, unknown>> | null;
  /** Exact V4 manager-research response used for authoritative HKEX facts. */
  managerResearch?: ManagerResearchResponse | ManagerResearchProduct | Readonly<Record<string, unknown>> | null;
  /** When provided by the view, keep a failed/loading V4 request distinct from an absent legacy lane. */
  managerResearchState?: "IDLE" | "LOADING" | "READY" | "NOT_MATERIALIZED" | "CANNOT_CONFIRM";
  /** Optional envelope used for stage-level source evidence. */
  stageSelection?: Readonly<Record<string, unknown>> | null;
}>;

const CONTRIBUTION_LABELS: Record<StageReasonContributionKey, string> = {
  d1: "D1 模型池",
  stage_market: "09:40 阶段盘面",
  us_finance: "US / finance",
  hkex_notice: "HKEX 公告",
  sentiment: "舆情",
};

const D1_REFERENCE_KEYS = [
  "d1_source_refs",
  "d1_source_ref",
  "d1_evidence_refs",
  "d1_evidence_ref",
  "d1_source_evidence",
  "d1_evidence",
] as const;

const STAGE_REFERENCE_KEYS = [
  "stage_source_refs",
  "stage_source_ref",
  "stage_market_refs",
  "stage_market_ref",
  "stage_evidence_refs",
  "stage_evidence_ref",
  "stage_source_evidence",
  "stage_evidence",
] as const;

const GENERIC_REFERENCE_KEYS = [
  "source_refs",
  "source_ref",
  "evidence_refs",
  "evidence_ref",
  "refs",
  "ref",
  "source_evidence",
] as const;

const DATE_KEYS = [
  "target_trade_date",
  "target_date",
  "trade_date",
  "research_date",
  "as_of_date",
  "asof_date",
  "date",
  "source_date",
] as const;

const TARGET_DATE_KEYS = new Set<string>([
  "target_trade_date",
  "target_date",
  "trade_date",
  "research_date",
  "as_of_date",
  "asof_date",
  "date",
]);

const REFERENCE_LOCATOR_KEYS = new Set([
  "path",
  "source_path",
  "url",
  "source_url",
  "uri",
  "ref",
  "reference",
  "locator",
  "source_ref",
  "source_id",
  "sha",
  "sha256",
  "raw_sha256",
  "source_sha256",
  "artifact_sha256",
  "manifest_sha256",
  "receipt_sha256",
  "frozen_payload_sha256",
  "excerpt_sha256",
  "supply_receipt_path",
  "supply_receipt_sha256",
  "receipt_path",
  "receipt_id",
  "markdown_path",
  "markdown_sha256",
]);

const REFERENCE_HASH_KEYS = new Set([
  "sha",
  "sha256",
  "raw_sha256",
  "source_sha256",
  "artifact_sha256",
  "manifest_sha256",
  "receipt_sha256",
  "frozen_payload_sha256",
  "excerpt_sha256",
  "supply_receipt_sha256",
  "markdown_sha256",
]);

const REFERENCE_PATH_KEYS = new Set([
  "path",
  "source_path",
  "supply_receipt_path",
  "receipt_path",
  "markdown_path",
]);

const REFERENCE_URL_KEYS = new Set(["url", "source_url", "uri"]);

const FAILED_STATUSES = new Set([
  "FAILED",
  "FAIL",
  "ERROR",
  "INVALID",
  "FAILURE",
  "REJECTED",
  "ABORTED",
  "TIMEOUT",
  "CANNOT_CONFIRM",
]);

const MISSING_STATUSES = new Set([
  "MISSING",
  "UPSTREAM_MISSING",
  "NOT_MATERIALIZED",
  "UNAVAILABLE",
  "NOT_READY",
]);

const CODE_KEYS = [
  "normalized_code",
  "stock_code",
  "stock_code_norm",
  "stockCode",
  "code",
  "symbol",
  "ts_code",
  "tsCode",
  "candidate_id",
  "entity_id",
  "ticker",
] as const;

const ROW_CONTAINER_KEYS = [
  "rows",
  "items",
  "details",
  "articles",
  "action_rows",
  "records",
  "entries",
  "messages",
  "events",
  "captures",
  "data",
] as const;

const US_FINANCE_KEYS = [
  "us_finance",
  "external_finance",
  "finance",
  "us_market",
  "us_session_captures",
] as const;

const HKEX_NOTICE_KEYS = [
  "hkex_notice",
  "hkex_notices",
  "hkex_notice_ledger",
  "hkex_announcements",
  "official_hkex",
  "hkex",
] as const;

const SENTIMENT_KEYS = [
  "zsxq_hourly",
  "sentiment",
  "sentiment_feed",
  "market_sentiment",
  "morning_news",
  "ai_news",
  "news_workbench",
  "key_investment_messages",
] as const;

const NON_DATA_KEYS = new Set([
  "status",
  "reason",
  "lane_status",
  "endpoint_mode",
  "research_date",
  "target_trade_date",
  "target_date",
  "trade_date",
  "source_date",
  "intelligence_date",
  "page_trade_date",
  "schema_version",
  "source",
  "source_url",
  "fetched_at",
  "generated_at",
  "data_status",
  "materialization_status",
  "availability",
  "error",
  "errors",
  "missing",
  "not_materialized",
  "url",
  "path",
  "uri",
  "ref",
  "locator",
  "source_id",
  "write_policy",
  "recommendation_status",
  "production_allowed",
  "buy_gate_updated",
  "orders_sent",
  "cannot_confirm",
  "cannot_confirm_items",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function own(record: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(record, key);
}

function text(value: unknown): string | null {
  if (typeof value !== "string" && typeof value !== "number") return null;
  const result = String(value).trim();
  return result && !["NaN", "Infinity", "-Infinity"].includes(result) ? result : null;
}

function compactDate(value: unknown): string | null {
  const raw = text(value);
  if (!raw) return null;
  if (/^\d{8}$/.test(raw)) return raw;
  const match = /^(\d{4})[-/]?(\d{2})[-/]?(\d{2})/.exec(raw);
  return match ? `${match[1]}${match[2]}${match[3]}` : null;
}

function finiteNumber(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string" || !value.trim()) return null;
  const result = Number(value);
  return Number.isFinite(result) ? result : null;
}

function formatNumber(value: unknown, digits: number): string | null {
  const numeric = finiteNumber(value);
  if (numeric === null) return null;
  if (digits === 0) return numeric.toFixed(0);
  return numeric.toFixed(digits)
    .replace(/(\.\d*?[1-9])0+$/, "$1")
    .replace(/\.0+$/, "");
}

function signedPercent(value: unknown): string | null {
  const formatted = formatNumber(value, 2);
  if (formatted === null) return null;
  return `${Number(formatted) >= 0 ? "+" : ""}${formatted}%`;
}

function normalizedCode(value: unknown): string | null {
  const raw = text(value);
  if (!raw) return null;
  return normalizeManagerHkCode(raw);
}

function marketIsHk(value: unknown): boolean {
  const normalized = text(value)?.toUpperCase().replaceAll("-", "_");
  return typeof normalized === "string" && ["HK", "HK_CONNECT", "HKEX", "HKG"].includes(normalized);
}

function hasExplicitHkNamespace(value: unknown): boolean {
  const raw = text(value)?.toUpperCase();
  if (!raw) return false;
  return /(?:^|[^A-Z0-9])HK(?:_CONNECT)?[.:/_-]\d{1,5}(?=$|[^0-9])/.test(raw)
    || /(?:^|[^0-9])\d{1,5}[._/-]HK(?:_CONNECT)?(?=$|[^A-Z0-9])/.test(raw);
}

type CodeIdentity = Readonly<{
  code: string | null;
  codes: readonly string[];
  present: boolean;
  consistent: boolean;
  joinable: boolean;
}>;

function codeParts(key: string, value: unknown): { codes: string[]; explicit: boolean; invalid: boolean } {
  const raw = text(value);
  if (!raw) return { codes: [], explicit: false, invalid: true };
  const parts = key === "candidate_id" ? raw.split("|") : [raw];
  const codes: string[] = [];
  let explicit = false;
  let invalid = false;
  for (const part of parts) {
    const code = normalizedCode(part);
    if (code) {
      codes.push(code);
      explicit ||= hasExplicitHkNamespace(part);
    } else if (key !== "candidate_id") {
      invalid = true;
    }
  }
  if (!codes.length) invalid = true;
  return { codes, explicit, invalid };
}

function recordIdentity(
  record: Readonly<Record<string, unknown>>,
  allowBareHkMarket = false,
): CodeIdentity {
  const aliases = CODE_KEYS.filter((key) => own(record, key));
  const codes: string[] = [];
  const marketKeys = ["market", "exchange", "market_code", "market_id", "venue"];
  const marketFields = marketKeys.filter((key) => own(record, key));
  const hasNonHkMarket = marketFields.some((key) => !marketIsHk(record[key]));
  let invalid = hasNonHkMarket;
  let explicit = allowBareHkMarket || ["market", "exchange", "market_code", "market_id", "venue"]
    .some((key) => marketIsHk(record[key]));
  for (const key of aliases) {
    const parsed = codeParts(key, record[key]);
    codes.push(...parsed.codes);
    explicit ||= parsed.explicit;
    invalid ||= parsed.invalid;
  }
  const uniqueCodes = [...new Set(codes)];
  const consistent = aliases.length > 0 && !invalid && uniqueCodes.length === 1;
  return {
    code: uniqueCodes.length === 1 ? uniqueCodes[0] : null,
    codes: uniqueCodes,
    present: aliases.length > 0,
    consistent,
    joinable: consistent && explicit,
  };
}

function recordCode(
  record: Readonly<Record<string, unknown>>,
  allowBareHkMarket = false,
): string | null {
  const identity = recordIdentity(record, allowBareHkMarket);
  return identity.joinable ? identity.code : null;
}

function rowCode(
  row: Readonly<Record<string, unknown>>,
  allowBareHkMarket = false,
): string | null {
  return recordCode(row, allowBareHkMarket);
}

function referenceValues(
  source: unknown,
  keys: readonly string[],
): StageReasonEvidenceRef[] {
  if (!isRecord(source)) return [];
  const result: StageReasonEvidenceRef[] = [];
  for (const key of keys) {
    if (!own(source, key)) continue;
    const value = source[key];
    const values = Array.isArray(value) ? value : [value];
    for (const item of values) {
      if (typeof item === "string" && item.trim()) result.push(item.trim());
      else if (isRecord(item)) result.push(item);
    }
  }
  return result;
}

function referenceLocator(ref: StageReasonEvidenceRef): boolean {
  if (typeof ref === "string") return false;
  return [...REFERENCE_LOCATOR_KEYS].some((key) => {
    if (!own(ref, key)) return false;
    const value = ref[key];
    const raw = text(value);
    if (!raw) return false;
    if (REFERENCE_HASH_KEYS.has(key)) return /^[0-9a-f]{32,128}$/i.test(raw);
    if (REFERENCE_PATH_KEYS.has(key)) {
      return raw.startsWith("/") || raw.startsWith("./") || raw.startsWith("../")
        || /^[A-Za-z]:[\\/]/.test(raw)
        || raw.includes("/") || raw.includes("\\");
    }
    if (REFERENCE_URL_KEYS.has(key)) {
      try {
        const url = new URL(raw);
        return url.protocol === "http:" || url.protocol === "https:";
      } catch {
        return false;
      }
    }
    if (key === "receipt_id") return /^[A-Za-z0-9][A-Za-z0-9_.:-]*$/.test(raw);
    if (key === "source_id") return /^[A-Za-z][A-Za-z0-9_-]*[:/#][^\s]+$/.test(raw);
    return /^[A-Za-z][A-Za-z0-9_-]*[:/#][^\s]+$/.test(raw);
  });
}

function statusKind(value: unknown): "FAILED" | "MISSING" | null {
  const status = text(value)?.toUpperCase();
  if (!status) return null;
  if (FAILED_STATUSES.has(status)) return "FAILED";
  if (MISSING_STATUSES.has(status)) return "MISSING";
  return null;
}

function firstFailedStatus(...values: readonly unknown[]): string | null {
  const pending = [...values];
  while (pending.length) {
    const value = pending.shift();
    if (isRecord(value)) {
      for (const key of ["status", "source_status", "lane_status", "materialization_status"] as const) {
        const status = text(value[key])?.toUpperCase() || null;
        if (statusKind(status) === "FAILED") return status;
      }
      if (own(value, "source")) pending.push(value.source);
    } else {
      const status = text(value)?.toUpperCase() || null;
      if (statusKind(status) === "FAILED") return status;
    }
  }
  return null;
}

function referenceStatusAllowsJoin(ref: StageReasonEvidenceRef): boolean {
  return typeof ref === "string" || statusKind(ref.status) === null;
}

function referenceDateIsExact(ref: StageReasonEvidenceRef, targetDate: string): boolean {
  if (!referenceLocator(ref)) return false;
  if (typeof ref === "string") {
    const dates = ref.match(/\d{4}[-/]?\d{2}[-/]?\d{2}/g) || [];
    return dates.some((value) => compactDate(value) === targetDate);
  }

  const dateEntries = DATE_KEYS
    .filter((key) => own(ref, key))
    .map((key) => [key, compactDate(ref[key])] as const)
    .filter((entry): entry is readonly [(typeof DATE_KEYS)[number], string] => Boolean(entry[1]));
  if (!dateEntries.length) return false;
  const targetEntries = dateEntries.filter(([key]) => TARGET_DATE_KEYS.has(key));
  if (targetEntries.length) return targetEntries.every(([, value]) => value === targetDate);
  return dateEntries.some(([, value]) => value === targetDate);
}

function referenceCodeMatches(ref: StageReasonEvidenceRef, expectedCode: string): boolean {
  if (typeof ref === "string") return false;
  const identity = recordIdentity(ref);
  return identity.joinable && identity.code === expectedCode;
}

function exactReferences(
  values: readonly StageReasonEvidenceRef[],
  targetDate: string,
  expectedCode: string,
): StageReasonEvidenceRef[] {
  const result: StageReasonEvidenceRef[] = [];
  for (const ref of values) {
    if (!referenceStatusAllowsJoin(ref)
      || !referenceDateIsExact(ref, targetDate)
      || !referenceCodeMatches(ref, expectedCode)) continue;
    if (!result.some((existing) => JSON.stringify(existing) === JSON.stringify(ref))) result.push(ref);
  }
  return result;
}

function firstNumber(source: Readonly<Record<string, unknown>>, keys: readonly string[]): number | null {
  for (const key of keys) {
    if (!own(source, key)) continue;
    const result = finiteNumber(source[key]);
    if (result !== null) return result;
  }
  return null;
}

function d1Rank(row: Readonly<Record<string, unknown>>): number | null {
  return firstNumber(row, ["d1_rank", "d1_pool_rank", "pool_rank"]);
}

function d1ActiveScore(row: Readonly<Record<string, unknown>>): { value: number | null; conflict: boolean } {
  const values: number[] = [];
  let invalid = false;
  for (const key of ["d1_prob_active", "prob_active"] as const) {
    if (!own(row, key)) continue;
    const value = finiteNumber(row[key]);
    if (value === null) invalid = true;
    else values.push(value);
  }
  const unique = [...new Set(values)];
  return {
    value: invalid || unique.length > 1 ? null : unique[0] ?? null,
    conflict: invalid || unique.length > 1,
  };
}

function stageDailyChange(row: Readonly<Record<string, unknown>>): number | null {
  return firstNumber(row, [
    "daily_change_pct",
    "daily_gain_pct",
    "relative_prev_close_pct",
    "current_change_from_prev_close_pct",
    "pct_chg",
    "d1_change_pct",
  ]);
}

function stageWindowChange(row: Readonly<Record<string, unknown>>): number | null {
  return firstNumber(row, [
    "stage_window_change_pct",
    "stage_change_pct",
    "stage_gain_pct",
    "window_change_pct",
    "stage_cumulative_pct_chg",
    "current_change_pct",
  ]);
}

function stageRankScore(row: Readonly<Record<string, unknown>>): number | null {
  return firstNumber(row, ["stage_rank_score", "stage_score", "stage_rtdata_score", "score"]);
}

function stageEnvelopeIsHk(stageSelection: Readonly<Record<string, unknown>> | null | undefined): boolean {
  if (!isRecord(stageSelection)) return false;
  const markets = stageSelection.markets;
  if (isRecord(markets) && isRecord(markets.HK) && marketIsHk(markets.HK.market)) return true;
  const selectionMarkets = stageSelection.selection_markets;
  return isRecord(selectionMarkets)
    && isRecord(selectionMarkets.HK_CONNECT)
    && marketIsHk(selectionMarkets.HK_CONNECT.market);
}

function sourceReferences(
  sources: readonly unknown[],
  specificKeys: readonly string[],
): StageReasonEvidenceRef[] {
  const result: StageReasonEvidenceRef[] = [];
  for (const source of sources) {
    result.push(...referenceValues(source, specificKeys));
    result.push(...referenceValues(source, GENERIC_REFERENCE_KEYS));
  }
  return result;
}

function upstreamMissingRowContribution(
  key: "d1" | "stage_market",
): StageReasonContribution {
  return {
    key,
    label: CONTRIBUTION_LABELS[key],
    status: "UPSTREAM_MISSING",
    human_text: `${CONTRIBUTION_LABELS[key]}行未物化（UPSTREAM_MISSING）。`,
    refs: [],
  };
}

function stageContribution(
  row: Readonly<Record<string, unknown>>,
  targetDate: string,
  stageSelection?: Readonly<Record<string, unknown>> | null,
): StageReasonContribution {
  const code = rowCode(row, stageEnvelopeIsHk(stageSelection));
  const rank = d1Rank(row);
  const daily = stageDailyChange(row);
  const window = stageWindowChange(row);
  const score = stageRankScore(row);
  const rowDate = rowDateStatus(row, targetDate);
  const rowStatus = statusKind(row.status);
  if (rowStatus === "MISSING") return upstreamMissingRowContribution("stage_market");
  const refs = code
    ? exactReferences(
      sourceReferences([row], STAGE_REFERENCE_KEYS),
      targetDate,
      code,
    )
    : [];
  const dailyText = signedPercent(daily);
  const windowText = signedPercent(window);
  const scoreText = formatNumber(score, 2);
  const valuesText = [
    dailyText ? `09:40相对前收日涨幅${dailyText}` : "09:40相对前收日涨幅=CANNOT_CONFIRM",
    windowText
      ? `阶段窗口（09:35-09:40）涨幅${windowText}（阶段涨幅基准：窗口首价→09:40价）`
      : "阶段窗口（09:35-09:40）涨幅=CANNOT_CONFIRM（阶段涨幅基准不可确认）",
    scoreText ? `阶段排序分${scoreText}` : "阶段排序分=CANNOT_CONFIRM",
  ];
  const valuesReady = daily !== null
    && window !== null
    && score !== null
    && rowDate === "EXACT"
    && rowStatus === null;
  const bindingText = rowStatus === "FAILED"
    ? "阶段行状态标记为失败，证据不可确认。"
    : rowStatus === "MISSING"
      ? "阶段行状态标记为未物化，证据不可确认。"
      : rowDate === "CONFLICT"
        ? "阶段行日期与目标日不一致，证据不可确认。"
        : refs.length && valuesReady
          ? "09:40盘面证据已按代码绑定。"
          : "09:40盘面证据不可确认。";
  return {
    key: "stage_market",
    label: CONTRIBUTION_LABELS.stage_market,
    status: refs.length && valuesReady ? "JOINED" : "CANNOT_CONFIRM",
    human_text: `${valuesText.join("；")}。${bindingText}`,
    refs,
  };
}

function d1Contribution(
  row: Readonly<Record<string, unknown>>,
  targetDate: string,
  stageSelection?: Readonly<Record<string, unknown>> | null,
): StageReasonContribution {
  const code = rowCode(row, stageEnvelopeIsHk(stageSelection));
  const rank = d1Rank(row);
  const activeScore = d1ActiveScore(row);
  const neutralScore = activeScore.value === null ? firstNumber(row, ["d1_score"]) : null;
  const rowDate = rowDateStatus(row, targetDate);
  const rowStatus = statusKind(row.status);
  if (rowStatus === "MISSING") return upstreamMissingRowContribution("d1");
  const refs = code
    ? exactReferences(
      sourceReferences([row], D1_REFERENCE_KEYS),
      targetDate,
      code,
    )
    : [];
  const rankText = rank === null ? "D1排名=CANNOT_CONFIRM" : `D1第${formatNumber(rank, 0)}位`;
  const scoreText = activeScore.conflict
    ? "prob_active 排序分=CANNOT_CONFIRM（d1_prob_active 与 prob_active 不一致）"
    : activeScore.value !== null
      ? `prob_active 排序分约${formatNumber(activeScore.value, 3)}`
      : neutralScore !== null
        ? `D1排序分约${formatNumber(neutralScore, 3)}（prob_active 排序分=CANNOT_CONFIRM）`
        : "prob_active 排序分=CANNOT_CONFIRM";
  const valuesReady = rank !== null
    && activeScore.value !== null
    && !activeScore.conflict
    && rowDate === "EXACT"
    && rowStatus === null;
  const bindingText = rowStatus === "FAILED"
    ? "D1行状态标记为失败，证据不可确认。"
    : rowStatus === "MISSING"
      ? "D1行状态标记为未物化，证据不可确认。"
      : rowDate === "CONFLICT"
        ? "D1行日期与目标日不一致，证据不可确认。"
        : refs.length && valuesReady
          ? "D1证据已按代码绑定。"
          : "D1证据不可确认。";
  return {
    key: "d1",
    label: CONTRIBUTION_LABELS.d1,
    status: refs.length && valuesReady ? "JOINED" : "CANNOT_CONFIRM",
    human_text: `${rankText}；${scoreText}，仅用于入池排序。${bindingText}`,
    refs,
  };
}

function laneDateIsExact(lane: Readonly<Record<string, unknown>>, targetDate: string): boolean {
  if (lane.endpoint_mode !== undefined && lane.endpoint_mode !== "EXACT") return false;
  const date = compactDate(lane.research_date ?? lane.trade_date);
  if (date !== targetDate) return false;
  for (const key of ["trade_date", "intelligence_date", "page_trade_date"] as const) {
    if (lane[key] === undefined || lane[key] === null || lane[key] === "") continue;
    const value = compactDate(lane[key]);
    if (value !== targetDate) return false;
  }
  return true;
}

function hasData(value: unknown): boolean {
  if (Array.isArray(value)) return value.some((item) => hasData(item));
  if (value === undefined || value === null || value === "") return false;
  if (typeof value === "string") return value.trim().length > 0;
  if (typeof value === "number") return Number.isFinite(value) && value > 0;
  if (typeof value === "boolean") return value;
  if (!isRecord(value)) return false;
  for (const key of ROW_CONTAINER_KEYS) {
    if (own(value, key) && hasData(value[key])) return true;
  }
  for (const key of ["item_count", "raw_item_count", "articles_count", "stock_mentions_count", "count"] as const) {
    const count = finiteNumber(value[key]);
    if (count !== null && count > 0) return true;
  }
  return Object.entries(value).some(([key, item]) => !NON_DATA_KEYS.has(key) && hasData(item));
}

function findSource(
  lane: Readonly<Record<string, unknown>>,
  keys: readonly string[],
): { present: boolean; value: unknown } {
  for (const key of keys) {
    if (own(lane, key)) return { present: true, value: lane[key] };
  }
  return { present: false, value: undefined };
}

function safeHttpUrl(value: unknown): string | undefined {
  if (typeof value !== "string" || !/^https?:\/\//i.test(value.trim())) return undefined;
  try {
    const url = new URL(value.trim());
    if ((url.protocol !== "https:" && url.protocol !== "http:") || url.username || url.password) return undefined;
    return url.href;
  } catch {
    return undefined;
  }
}

function sourceRows(value: unknown): Record<string, unknown>[] {
  if (!isRecord(value)) return [];
  const rows: Record<string, unknown>[] = [];
  for (const key of ["details", "items", "articles", "overview", "us_session_captures"] as const) {
    const nested = value[key];
    if (Array.isArray(nested)) rows.push(...nested.filter(isRecord));
  }
  const seen = new Set<string>();
  return rows.filter((row, index) => {
    const identity = text(
      row.id
      || row.article_id
      || row.evidence_id
      || row.dedupe_key
      || row.url
      || row.source_url
      || row.original_url,
    ) || [
      text(row.title_zh || row.title || row.headline_zh || row.headline),
      text(row.source_name || row.source),
      text(row.published_at || row.fetched_at || row.first_seen_at),
      String(index),
    ].join("|");
    if (seen.has(identity)) return false;
    seen.add(identity);
    return true;
  });
}

function sourceDetailRows(value: unknown): StageReasonContributionDetail[] {
  return sourceRows(value).map((row) => {
    const url = safeHttpUrl(row.original_url) || safeHttpUrl(row.source_url) || safeHttpUrl(row.url);
    const title = text(row.title_zh || row.translated_title || row.headline_zh)
      || text(row.title || row.headline || row.source_title || row.summary_zh || row.summary)
      || "CANNOT_CONFIRM";
    const source = text(row.source_name || row.source || row.source_type)
      || "CANNOT_CONFIRM";
    const published = text(row.published_at || row.source_published_at || row.publication_time);
    const fetched = text(row.fetched_at || row.collected_at || row.first_seen_at);
    const stockCode = text(row.stock_code || row.code || row.ticker);
    const stockName = text(row.stock_name || row.name);
    return {
      title,
      source,
      ...(published ? { published_at: published } : {}),
      ...(fetched ? { fetched_at: fetched } : {}),
      ...(url ? { source_url: url } : {}),
      ...(stockCode ? { stock_code: stockCode } : {}),
      ...(stockName ? { stock_name: stockName } : {}),
      ...(text(row.summary_zh || row.summary) ? { note: text(row.summary_zh || row.summary) || undefined } : {}),
    };
  });
}

function sourceCount(value: unknown, details: readonly StageReasonContributionDetail[]): number {
  if (isRecord(value)) {
    const count = finiteNumber(value.item_count);
    if (count !== null && count >= 0) return count;
    const topicCount = finiteNumber(value.topic_count);
    if (topicCount !== null && topicCount >= 0) return topicCount;
  }
  return details.length;
}

function sourceRawCount(value: unknown): number | null {
  if (!isRecord(value)) return null;
  const count = finiteNumber(value.raw_item_count);
  return count !== null && count >= 0 ? count : null;
}

function backgroundSource(
  lane: Readonly<Record<string, unknown>>,
  key: Exclude<StageReasonContributionKey, "d1" | "stage_market" | "hkex_notice">,
): { present: boolean; value: unknown } {
  const keys = key === "us_finance" ? US_FINANCE_KEYS : SENTIMENT_KEYS;
  return findSource(lane, keys);
}

function laneBackgroundContribution(
  contribution: StageReasonContribution,
  key: Exclude<StageReasonContributionKey, "d1" | "stage_market" | "hkex_notice">,
  lane: Readonly<Record<string, unknown>> | null,
  targetDate: string,
): StageReasonContribution {
  if (!lane) return contribution;
  const source = backgroundSource(lane, key);
  if (!source.present || !isRecord(source.value)) return contribution;
  const details = sourceDetailRows(source.value);
  if (!details.length && !hasData(source.value)) return contribution;
  const count = sourceCount(source.value, details);
  const rawCount = sourceRawCount(source.value);
  const countText = rawCount !== null && rawCount !== count
    ? `采集${count}条（原始${rawCount}条，去重后明细${details.length}条）`
    : `采集${count}条（去重后明细${details.length}条）`;
  const status = text(source.value.status)?.toUpperCase();
  if (statusKind(status) === "FAILED") return contribution;
  if (key === "us_finance") {
    return {
      ...contribution,
      details,
      metadata: { target_date: targetDate, item_count: count, raw_item_count: rawCount, detail_count: details.length },
      human_text: `${contribution.label}背景${countText}；来源为外部文章/RSS背景，不是实时美股报价，未绑定 ${contribution.key === "us_finance" ? "本卡" : "目标个股"}。`,
    };
  }
  const latestSlot = text(source.value.latest_slot);
  const generatedAt = text(source.value.source_generated_at || source.value.fetched_at);
  const later = [parseClockSeconds(latestSlot), parseTimestampClockSeconds(generatedAt)]
    .filter((value): value is number => value !== null)
    .some((value) => value > STAGE_CUTOFF_SECONDS);
  const timingText = later
    ? `latest_slot=${latestSlot || "CANNOT_CONFIRM"}、source_generated_at=${generatedAt || "CANNOT_CONFIRM"}晚于09:40`
    : `latest_slot=${latestSlot || "CANNOT_CONFIRM"}、source_generated_at=${generatedAt || "CANNOT_CONFIRM"}`;
  return {
    ...contribution,
    details,
    metadata: {
      target_date: targetDate,
      item_count: count,
      raw_item_count: rawCount,
      detail_count: details.length,
      latest_slot: latestSlot,
      source_generated_at: generatedAt,
      later_than_stage: later,
    },
    human_text: `${contribution.label}补充${countText}；${timingText}。${later ? "这是09:40之后的后续补充，不构成09:40阶段贡献，不强制绑定本卡。" : "仅保留为研究背景，未形成本卡JOINED证据。"}`,
  };
}

const STAGE_CUTOFF_SECONDS = 9 * 60 * 60 + 40 * 60;

function parseClockSeconds(value: string | null): number | null {
  if (!value) return null;
  const raw = value.trim();
  let hour: number;
  let minute: number;
  let second = 0;
  let match = /^(\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(raw);
  if (match) {
    hour = Number(match[1]);
    minute = Number(match[2]);
    second = Number(match[3] || 0);
  } else if (/^\d{4}$/.test(raw)) {
    hour = Number(raw.slice(0, 2));
    minute = Number(raw.slice(2, 4));
  } else if (/^\d{3}$/.test(raw)) {
    hour = Number(raw.slice(0, 1));
    minute = Number(raw.slice(1, 3));
  } else {
    return null;
  }
  if (hour > 23 || minute > 59 || second > 59) return null;
  return hour * 60 * 60 + minute * 60 + second;
}

function parseTimestampClockSeconds(value: string | null): number | null {
  if (!value) return null;
  const match = /(?:T|\s)(\d{1,2}):(\d{2})(?::(\d{2}))?/.exec(value.trim());
  return match ? parseClockSeconds(`${match[1]}:${match[2]}:${match[3] || "00"}`) : null;
}

function managerResearchProduct(value: StageReasonContributionsInput["managerResearch"]): ManagerResearchProduct | null {
  if (!isRecord(value)) return null;
  const product = isRecord(value.product) ? value.product : value;
  return Array.isArray(product.rows) ? product as ManagerResearchProduct : null;
}

function managerResearchScopeIsExact(
  value: StageReasonContributionsInput["managerResearch"],
  product: ManagerResearchProduct,
): boolean {
  if (product.stage_id !== MANAGER_STAGE_ID || product.market !== MANAGER_STAGE_MARKET) return false;
  if (!isRecord(value) || !isRecord(value.product)) return true;
  return value.stage_id === MANAGER_STAGE_ID
    && value.market === MANAGER_STAGE_MARKET
    && product.stage_id === value.stage_id
    && product.market === value.market;
}

type ManagerResearchRowLookup = Readonly<{
  row: ManagerResearchRow | null;
  duplicate: boolean;
}>;

function managerResearchRowForCode(
  value: StageReasonContributionsInput["managerResearch"],
  targetDate: string,
  code: string,
): ManagerResearchRowLookup {
  const product = managerResearchProduct(value);
  if (!product || !managerResearchScopeIsExact(value, product) || compactDate(product.target_trade_date) !== targetDate) {
    return { row: null, duplicate: false };
  }
  const matches = product.rows.filter((row) => {
    const identity = recordIdentity(row, marketIsHk(row.market));
    return identity.joinable
      && identity.code === code
      && compactDate(row.target_trade_date) === targetDate;
  });
  return {
    row: matches.length === 1 ? matches[0] : null,
    duplicate: matches.length > 1,
  };
}

function managerResearchContribution(
  value: StageReasonContributionsInput["managerResearch"],
  state: StageReasonContributionsInput["managerResearchState"],
  targetDate: string,
  code: string | null,
): StageReasonContribution {
  const label = CONTRIBUTION_LABELS.hkex_notice;
  if (state && state !== "READY") {
    return {
      key: "hkex_notice",
      label,
      status: "CANNOT_CONFIRM",
      human_text: `V4 ${label} exact-date 请求/响应不可确认（${state}）；未回退旧 research lane。`,
      refs: [],
    };
  }
  if (!code) {
    return { key: "hkex_notice", label, status: "CANNOT_CONFIRM", human_text: "V4 HKEX 公告无法确认目标个股代码。", refs: [] };
  }
  const product = managerResearchProduct(value);
  if (!product || !managerResearchScopeIsExact(value, product)) {
    return { key: "hkex_notice", label, status: "CANNOT_CONFIRM", human_text: "V4 HKEX 公告 exact stage/market 不可确认。", refs: [] };
  }
  if (compactDate(product.target_trade_date) !== targetDate) {
    return { key: "hkex_notice", label, status: "CANNOT_CONFIRM", human_text: "V4 HKEX 公告 exact target date 不可确认。", refs: [] };
  }
  const lookup = managerResearchRowForCode(value, targetDate, code);
  if (lookup.duplicate) {
    return { key: "hkex_notice", label, status: "CANNOT_CONFIRM", human_text: `V4 ${label}存在多个 HK.${code} 的目标日研究行，无法确认唯一来源。`, refs: [] };
  }
  const row = lookup.row;
  if (!row) {
    return { key: "hkex_notice", label, status: "UPSTREAM_MISSING", human_text: `V4 ${label}未物化 ${code} 的目标日研究行。`, refs: [] };
  }
  const source = isRecord(row.source) ? row.source : {};
  const facts = Array.isArray(row.facts) ? row.facts.filter(isRecord) : [];
  const failedStatus = firstFailedStatus(row, source);
  const sourceStatus = failedStatus
    || text(row.source_status || source.source_status || source.status || row.status)?.toUpperCase();
  const sourceReason = text(row.source_reason || source.source_reason || row.source_failure_detail);
  const documentTitle = text(source.document_title || source.headline || row.name || code) || "CANNOT_CONFIRM";
  const sourceUrl = safeHttpUrl(row.source_url) || safeHttpUrl(source.source_url) || safeHttpUrl(source.url);
  const published = text(source.published_at || row.published_at);
  const retrieved = text(source.retrieved_at || row.retrieved_at);
  const historical = row.historical_system_available === false || product.historical_system_available === false;
  const refs = [{
    type: "V4_HKEX_RESEARCH",
    code,
    target_trade_date: targetDate,
    source_url: sourceUrl,
    directory_url: safeHttpUrl(source.directory_url),
    source_sha256: text(source.sha256 || source.source_sha256),
    document_title: documentTitle,
    source_status: sourceStatus || "CANNOT_CONFIRM",
    source_reason: sourceReason,
    historical_system_available: historical,
  }];
  const factDetails = facts.map((fact) => {
    const locator = text(fact.locator || (fact.page !== undefined ? `PDF page ${String(fact.page)}` : undefined)) || "CANNOT_CONFIRM";
    const statement = text(fact.statement_cn || fact.source_excerpt || fact.label_cn || fact.label) || "CANNOT_CONFIRM";
    return {
      title: statement || "CANNOT_CONFIRM",
      source: locator,
      ...(published ? { published_at: published } : {}),
      ...(retrieved ? { fetched_at: retrieved } : {}),
      ...(safeHttpUrl(fact.source_url) || sourceUrl ? { source_url: safeHttpUrl(fact.source_url) || sourceUrl } : {}),
      ...(text(fact.source_excerpt) ? { note: text(fact.source_excerpt) || undefined } : {}),
    };
  });
  const details: StageReasonContributionDetail[] = facts.length
    ? factDetails
    : [{
      title: documentTitle,
      source: text(source.provider_id || source.source_kind || product.provider_id) || "V4 HKEX",
      ...(published ? { published_at: published } : {}),
      ...(retrieved ? { fetched_at: retrieved } : {}),
      ...(sourceUrl ? { source_url: sourceUrl } : {}),
      ...(sourceReason ? { note: sourceReason } : {}),
    }];
  const acquiredText = `V4 HKEX官方材料已采集：${documentTitle}；published=${published || "CANNOT_CONFIRM"}；retrieved=${retrieved || "CANNOT_CONFIRM"}`;
  const factsText = facts.length
    ? `已解析${facts.length}条官方事实`
    : `官方事实=0，解析状态=${sourceReason || sourceStatus || "CANNOT_CONFIRM"}`;
  const historyText = historical
    ? "这是目标日请求后的历史回溯，不证明09:40系统当时已消费，不能标记JOINED。"
    : "研究材料已采集，但未提供09:40阶段消费回执，不能标记JOINED。";
  const status = facts.length && !failedStatus
    ? "AVAILABLE_NOT_JOINED"
    : "CANNOT_CONFIRM";
  return {
    key: "hkex_notice",
    label,
    status,
    human_text: `${acquiredText}；${factsText}。${historyText}`,
    refs,
    details,
    metadata: {
      target_date: targetDate,
      code,
      fact_count: facts.length,
      source_status: sourceStatus || "CANNOT_CONFIRM",
      source_reason: sourceReason,
      historical_system_available: historical,
    },
  };
}

function directRows(value: unknown): Record<string, unknown>[] {
  if (Array.isArray(value)) return value.filter(isRecord);
  if (!isRecord(value)) return [];
  const rows: Record<string, unknown>[] = [];
  if (recordIdentity(value).present) rows.push(value);
  for (const key of ROW_CONTAINER_KEYS) {
    if (!own(value, key)) continue;
    const nested = value[key];
    if (Array.isArray(nested)) rows.push(...nested.filter(isRecord));
    else if (isRecord(nested) && recordIdentity(nested).present) rows.push(nested);
  }
  return rows;
}

function rowDateStatus(row: Record<string, unknown>, targetDate: string): "EXACT" | "MISSING" | "CONFLICT" {
  const targetKeysPresent = DATE_KEYS
    .filter((key) => TARGET_DATE_KEYS.has(key) && own(row, key));
  if (targetKeysPresent.some((key) => compactDate(row[key]) === null)) return "CONFLICT";
  const entries = DATE_KEYS
    .filter((key) => own(row, key))
    .map((key) => [key, compactDate(row[key])] as const)
    .filter((entry): entry is readonly [(typeof DATE_KEYS)[number], string] => Boolean(entry[1]));
  if (!entries.length) return "MISSING";
  const targetEntries = entries.filter(([key]) => TARGET_DATE_KEYS.has(key));
  if (targetEntries.length) {
    return targetEntries.every(([, value]) => value === targetDate) ? "EXACT" : "CONFLICT";
  }
  // source_date is commonly the publication/capture date immediately before
  // the target trade date.  The outer exact lane supplies the target binding;
  // a source-only date therefore remains unresolved rather than being called
  // a stale conflicting target row.
  return "MISSING";
}

function laneContribution(
  key: Exclude<StageReasonContributionKey, "d1" | "stage_market">,
  lane: Readonly<Record<string, unknown>> | null,
  targetDate: string,
  code: string | null,
): StageReasonContribution {
  const labels: Record<typeof key, string> = {
    us_finance: CONTRIBUTION_LABELS.us_finance,
    hkex_notice: CONTRIBUTION_LABELS.hkex_notice,
    sentiment: CONTRIBUTION_LABELS.sentiment,
  };
  const sourceKeys: Record<typeof key, readonly string[]> = {
    us_finance: US_FINANCE_KEYS,
    hkex_notice: HKEX_NOTICE_KEYS,
    sentiment: SENTIMENT_KEYS,
  };
  if (!lane || !laneDateIsExact(lane, targetDate)) {
    return {
      key,
      label: labels[key],
      status: "CANNOT_CONFIRM",
      human_text: `${labels[key]} exact-date 请求/响应不可确认。`,
      refs: [],
    };
  }
  const laneStatus = statusKind(lane.status);
  if (laneStatus === "FAILED") {
    return {
      key,
      label: labels[key],
      status: "CANNOT_CONFIRM",
      human_text: `${labels[key]} exact-date 响应标记为失败，个股绑定不可确认。`,
      refs: [],
    };
  }
  if (laneStatus === "MISSING") {
    return {
      key,
      label: labels[key],
      status: "UPSTREAM_MISSING",
      human_text: `目标日${labels[key]}资料未物化（UPSTREAM_MISSING）。`,
      refs: [],
    };
  }
  const source = findSource(lane, sourceKeys[key]);
  if (!source.present) {
    return {
      key,
      label: labels[key],
      status: "UPSTREAM_MISSING",
      human_text: `目标日${labels[key]}资料未物化（UPSTREAM_MISSING）。`,
      refs: [],
    };
  }
  const sourceStatus = isRecord(source.value) ? statusKind(source.value.status) : null;
  if (sourceStatus === "FAILED") {
    return {
      key,
      label: labels[key],
      status: "CANNOT_CONFIRM",
      human_text: `${labels[key]}来源响应标记为失败，个股绑定不可确认。`,
      refs: [],
    };
  }
  if (!hasData(source.value)) {
    return {
      key,
      label: labels[key],
      status: "UPSTREAM_MISSING",
      human_text: `目标日${labels[key]}资料未物化（UPSTREAM_MISSING）。`,
      refs: [],
    };
  }
  if (sourceStatus === "MISSING") {
    return {
      key,
      label: labels[key],
      status: "UPSTREAM_MISSING",
      human_text: `目标日${labels[key]}资料未物化（UPSTREAM_MISSING）。`,
      refs: [],
    };
  }
  const rows = directRows(source.value);
  if (!code) {
    return {
      key,
      label: labels[key],
      status: "CANNOT_CONFIRM",
      human_text: `目标日${labels[key]}无法确认目标个股代码绑定。`,
      refs: [],
    };
  }
  const candidateRows = rows.filter((row) => recordIdentity(row).codes.includes(code));
  const failedRows = candidateRows.filter((row) => statusKind(row.status) === "FAILED");
  if (failedRows.length) {
    return {
      key,
      label: labels[key],
      status: "CANNOT_CONFIRM",
      human_text: `${labels[key]}个股行状态标记为失败，个股绑定不可确认。`,
      refs: [],
    };
  }
  const missingRows = candidateRows.filter((row) => statusKind(row.status) === "MISSING");
  if (missingRows.length) {
    return {
      key,
      label: labels[key],
      status: "UPSTREAM_MISSING",
      human_text: `目标日${labels[key]}个股行未物化（UPSTREAM_MISSING）。`,
      refs: [],
    };
  }
  const conflictingRows = candidateRows.filter((row) => {
    const identity = recordIdentity(row);
    return !identity.joinable || rowDateStatus(row, targetDate) === "CONFLICT";
  });
  if (conflictingRows.length) {
    return {
      key,
      label: labels[key],
      status: "CANNOT_CONFIRM",
      human_text: `${labels[key]}出现同码但非目标日记录，个股绑定不可确认。`,
      refs: [],
    };
  }
  const matchingRows = candidateRows.filter((row) => {
    const identity = recordIdentity(row);
    return identity.joinable && identity.code === code;
  });
  if (!matchingRows.length) {
    return {
      key,
      label: labels[key],
      status: "AVAILABLE_NOT_JOINED",
      human_text: `目标日${labels[key]}资料可用，但仅为市场背景，未绑定 ${code ? `HK.${code}` : "目标个股"}。`,
      refs: [],
    };
  }
  const refs = matchingRows.flatMap((row) => exactReferences(
    referenceValues(row, GENERIC_REFERENCE_KEYS),
    targetDate,
    code || "",
  ));
  if (!refs.length) {
    return {
      key,
      label: labels[key],
      status: "CANNOT_CONFIRM",
      human_text: `目标日${labels[key]}存在同码记录，但缺少精确证据引用，不能确认 JOINED。`,
      refs: [],
    };
  }
  return {
    key,
    label: labels[key],
    status: "JOINED",
    human_text: `目标日${labels[key]}个股证据已按 ${code ? `HK.${code}` : "代码"} 绑定。`,
    refs,
  };
}

function unknownContribution(key: StageReasonContributionKey): StageReasonContribution {
  return {
    key,
    label: CONTRIBUTION_LABELS[key],
    status: "CANNOT_CONFIRM",
    human_text: `${CONTRIBUTION_LABELS[key]}证据不可确认。`,
    refs: [],
  };
}

/** Build all five card contributions in a fixed, stable order. */
export function buildStageReasonContributions(
  input: StageReasonContributionsInput,
): StageReasonContributions {
  const row = isRecord(input.row) ? input.row : {};
  const code = rowCode(row, stageEnvelopeIsHk(input.stageSelection));
  const lane = isRecord(input.researchLane) ? input.researchLane : null;
  const hkex = input.managerResearchState !== undefined || input.managerResearch !== undefined
    ? managerResearchContribution(input.managerResearch, input.managerResearchState, input.targetDate, code)
    : laneContribution("hkex_notice", lane, input.targetDate, code);
  const contributions: Record<StageReasonContributionKey, StageReasonContribution> = {
    d1: d1Contribution(row, input.targetDate, input.stageSelection),
    stage_market: stageContribution(row, input.targetDate, input.stageSelection),
    us_finance: laneBackgroundContribution(
      laneContribution("us_finance", lane, input.targetDate, code),
      "us_finance",
      lane,
      input.targetDate,
    ),
    hkex_notice: hkex,
    sentiment: laneBackgroundContribution(
      laneContribution("sentiment", lane, input.targetDate, code),
      "sentiment",
      lane,
      input.targetDate,
    ),
  };
  return Object.fromEntries(
    STAGE_REASON_CONTRIBUTION_KEYS.map((key) => [key, contributions[key] || unknownContribution(key)]),
  ) as StageReasonContributions;
}

export const adaptStageReasonContributions = buildStageReasonContributions;
export const projectStageReasonContributions = buildStageReasonContributions;
