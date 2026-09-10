// Research decision-desk lane API (aligned to the V3 research lane).
export interface ResearchLane {
  research_date: string;
  endpoint_mode: string;
  status?: string;
  reason?: string;
  schema_version: string;
  stock_research_daily?: Array<Record<string, unknown>>;
  stock_research_timeline?: Array<Record<string, unknown>>;
  research_pool_bridge?: Array<Record<string, unknown>>;
  morning_news?: Record<string, unknown>;
  news_workbench?: Record<string, unknown>;
  zsxq_hourly?: Record<string, unknown>;
  ocr_ingestion?: Record<string, unknown>;
  external_finance?: Record<string, unknown>;
  ai_news?: Record<string, unknown>;
  research_quality_summary?: Record<string, unknown>;
  key_investment_messages?: Array<Record<string, unknown>>;
  research_intelligence_timeline?: Record<string, unknown>;
  hourly_research?: Record<string, unknown>;
  cannot_confirm?: Array<unknown>;
  production_allowed?: boolean;
  [key: string]: unknown;
}

/** Exact-date daily product projected beside the hourly lane. */
export interface ResearchDayCoverage {
  complete?: boolean;
  expected_slots?: number;
  ready_slots?: number;
  missing_slots?: Array<unknown>;
  slot_matrix?: Array<Record<string, unknown>>;
  [key: string]: unknown;
}

export interface ResearchDayProduct {
  schema_version: string;
  contract_id?: string;
  workflow_name?: string;
  pass_signal?: string;
  status: string;
  authoritative: boolean;
  endpoint_mode: ResearchLaneEndpointMode;
  date_mode?: string;
  archive_date?: string | null;
  requested_date?: string | null;
  resolved_date?: string | null;
  timezone?: string;
  is_full_day?: boolean;
  coverage?: ResearchDayCoverage;
  counts?: Record<string, unknown>;
  jyg_coverage?: Record<string, unknown>;
  cannot_confirm?: Array<unknown>;
  loading_complete?: boolean;
  write_policy?: string;
  recommendation_status?: string;
  RESEARCH_ONLY?: boolean;
  production_allowed?: boolean;
  buy_gate_updated?: boolean;
  orders_sent?: boolean;
  [key: string]: unknown;
}

export type ResearchLaneStatus =
  | "READY"
  | "LIVE_HOURLY"
  | "LIVE_PERIPHERAL_ONLY"
  | "NOT_MATERIALIZED";

export type ResearchLaneEndpointMode = "EXACT" | "LATEST";

export type ResearchLaneErrorKind =
  | "NETWORK_REJECTED"
  | "HTTP_NON_2XX"
  | "INVALID_RESPONSE";

export type ResearchLaneRequestOptions = Readonly<{
  signal?: AbortSignal;
}>;

export class ResearchLaneRequestError extends Error {
  readonly kind: ResearchLaneErrorKind;
  readonly status?: number;

  constructor(kind: ResearchLaneErrorKind, message: string, status?: number, cause?: unknown) {
    super(message, { cause });
    this.name = "ResearchLaneRequestError";
    this.kind = kind;
    this.status = status;
  }
}

const RESEARCH_LANE_SCHEMA = "v3_5.research_lane.v1";
const RESEARCH_DAY_SCHEMA = "v3_5.research_day_product.v1";
const MATERIALIZED_STATUSES = new Set<ResearchLaneStatus>(["READY", "LIVE_HOURLY"]);
const LANE_STATUSES = new Set<ResearchLaneStatus>([
  "READY",
  "LIVE_HOURLY",
  "LIVE_PERIPHERAL_ONLY",
  "NOT_MATERIALIZED",
]);
const MATERIALIZED_ARRAY_FIELDS = [
  "stock_research_daily",
  "stock_research_timeline",
  "research_pool_bridge",
  "key_investment_messages",
] as const;
const MATERIALIZED_OBJECT_FIELDS = [
  "research_quality_summary",
  "morning_news",
  "zsxq_hourly",
  "external_finance",
  "ai_news",
  "news_workbench",
  "hourly_research",
] as const;
const OPTIONAL_ARRAY_FIELDS = ["cannot_confirm"] as const;
const OPTIONAL_OBJECT_FIELDS = ["ocr_ingestion", "research_intelligence_timeline"] as const;
const RESEARCH_DAY_STATUSES = new Set(["READY", "READY_WITH_DECLARED_GAPS", "NOT_MATERIALIZED"]);
const RESEARCH_DAY_COUNT_FIELDS = [
  "raw_rows",
  "evidence_rows",
  "excluded_rows",
  "mention_pairs",
  "urls",
  "stock_rollups",
  "high_priority",
  "duplicate_pairs",
] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isGregorianDate(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{8}$/.test(value)) return false;
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(4, 6));
  const day = Number(value.slice(6, 8));
  if (month < 1 || month > 12 || day < 1) return false;
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = month === 2 ? (leap ? 29 : 28) : [4, 6, 9, 11].includes(month) ? 30 : 31;
  return day <= days;
}

function hasOwn(value: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function invalidResponse(message: string): never {
  throw new Error(message);
}

function validateFieldTypes(
  payload: Record<string, unknown>,
  fields: readonly string[],
  expected: "array" | "object",
): void {
  for (const field of fields) {
    if (!hasOwn(payload, field) || payload[field] === undefined) continue;
    const value = payload[field];
    if (expected === "array" && !Array.isArray(value)) invalidResponse(`${field} must be an array`);
    if (expected === "object" && !isRecord(value)) invalidResponse(`${field} must be an object`);
  }
}

/** Validate the complete, mode-bound wire contract before exposing a lane to Vue. */
export function validateResearchLaneResponse(
  value: unknown,
  expectedEndpointMode?: ResearchLaneEndpointMode,
  expectedResearchDate?: string,
): ResearchLane {
  if (!isRecord(value)) invalidResponse("research lane response must be an object");
  // Older exact-date callers returned a deliberately status-only
  // NOT_MATERIALIZED object. Keep that non-materialized shape readable while
  // materialized lanes remain fully strict and mode/date bound.
  const statusOnly = value.status === "NOT_MATERIALIZED" && expectedEndpointMode
    && ["RESEARCH_LANE_SNAPSHOT_NOT_FOUND", "NO_RESEARCH_ARCHIVE_LATEST"].includes(String(value.reason || ""));
  const payload = statusOnly
    ? {
      ...value,
      schema_version: value.schema_version === undefined ? RESEARCH_LANE_SCHEMA : value.schema_version,
      endpoint_mode: value.endpoint_mode === undefined ? expectedEndpointMode : value.endpoint_mode,
      cannot_confirm: value.cannot_confirm === undefined ? [] : value.cannot_confirm,
      write_policy: value.write_policy === undefined ? "read_only" : value.write_policy,
      recommendation_status: value.recommendation_status === undefined ? "RESEARCH_ONLY" : value.recommendation_status,
    }
    : value;
  if (hasOwn(payload, "error")) invalidResponse("research lane response contains a top-level error");
  if (payload.schema_version !== RESEARCH_LANE_SCHEMA) invalidResponse("research lane schema_version is invalid");
  if (typeof payload.status !== "string" || !LANE_STATUSES.has(payload.status as ResearchLaneStatus)) {
    invalidResponse("research lane status is invalid");
  }
  if (payload.endpoint_mode !== "EXACT" && payload.endpoint_mode !== "LATEST") {
    invalidResponse("research lane endpoint_mode is invalid");
  }
  const endpointMode = payload.endpoint_mode as ResearchLaneEndpointMode;
  if (expectedEndpointMode && endpointMode !== expectedEndpointMode) {
    invalidResponse("research lane endpoint_mode does not match the request");
  }
  if (typeof payload.research_date !== "string") invalidResponse("research lane research_date is missing");
  const status = payload.status as ResearchLaneStatus;
  const emptyLatestDate = endpointMode === "LATEST" && status === "NOT_MATERIALIZED" && payload.research_date === "";
  if (!emptyLatestDate && !isGregorianDate(payload.research_date)) {
    invalidResponse("research lane research_date is invalid");
  }
  if (expectedResearchDate !== undefined) {
    if (!isGregorianDate(expectedResearchDate) || payload.research_date !== expectedResearchDate) {
      invalidResponse("research lane research_date does not match the request");
    }
  }
  if (!Array.isArray(payload.cannot_confirm) || !payload.cannot_confirm.every((item) => typeof item === "string")) {
    invalidResponse("research lane cannot_confirm must be a string array");
  }
  if (payload.write_policy !== "read_only") invalidResponse("research lane write_policy is invalid");
  if (payload.recommendation_status !== "RESEARCH_ONLY") invalidResponse("research lane recommendation_status is invalid");
  for (const safetyField of ["production_allowed", "buy_gate_updated", "orders_sent"]) {
    if (payload[safetyField] !== false) invalidResponse(`research lane ${safetyField} must be false`);
  }
  if (hasOwn(payload, "reason") && payload.reason !== undefined && typeof payload.reason !== "string") {
    invalidResponse("research lane reason must be a string");
  }
  validateFieldTypes(payload, OPTIONAL_ARRAY_FIELDS, "array");
  validateFieldTypes(payload, OPTIONAL_OBJECT_FIELDS, "object");
  validateFieldTypes(payload, MATERIALIZED_ARRAY_FIELDS, "array");
  validateFieldTypes(payload, MATERIALIZED_OBJECT_FIELDS, "object");
  if (MATERIALIZED_STATUSES.has(status)) {
    if (typeof payload.lane_status !== "string" || !payload.lane_status) invalidResponse("research lane lane_status is missing");
    if (typeof payload.daily_archive_status !== "string" || !payload.daily_archive_status) invalidResponse("research lane daily_archive_status is missing");
    for (const field of [...MATERIALIZED_ARRAY_FIELDS, ...MATERIALIZED_OBJECT_FIELDS]) {
      if (!hasOwn(payload, field) || payload[field] === undefined) invalidResponse(`research lane ${field} is missing`);
    }
  }
  return payload as ResearchLane;
}

function validateResearchDayCounts(payload: Record<string, unknown>): void {
  if (!isRecord(payload.counts)) invalidResponse("research day counts are missing");
  for (const field of RESEARCH_DAY_COUNT_FIELDS) {
    const value = payload.counts[field];
    if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
      invalidResponse(`research day counts.${field} is invalid`);
    }
  }
}

function validateResearchDayCoverage(payload: Record<string, unknown>): void {
  if (!isRecord(payload.coverage)) invalidResponse("research day coverage is missing");
  const coverage = payload.coverage;
  if (typeof coverage.complete !== "boolean") invalidResponse("research day coverage.complete is invalid");
  for (const field of ["expected_slots", "ready_slots"] as const) {
    const value = coverage[field];
    if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
      invalidResponse(`research day coverage.${field} is invalid`);
    }
  }
  if (!Array.isArray(coverage.missing_slots) || !coverage.missing_slots.every((item) => typeof item === "string")) {
    invalidResponse("research day coverage.missing_slots must be a string array");
  }
  if (!Array.isArray(coverage.slot_matrix) || !coverage.slot_matrix.every(isRecord)) {
    invalidResponse("research day coverage.slot_matrix must be an object array");
  }
}

function researchDayDate(payload: Record<string, unknown>): string {
  for (const field of ["resolved_date", "archive_date", "requested_date"] as const) {
    const value = payload[field];
    if (value === undefined || value === null || value === "") continue;
    if (typeof value !== "string") invalidResponse(`research day ${field} is invalid`);
    return value;
  }
  return "";
}

/** Validate the exact-date day product before it is rendered beside hourly data. */
export function validateResearchDayResponse(
  value: unknown,
  expectedEndpointMode: ResearchLaneEndpointMode = "EXACT",
  expectedResearchDate?: string,
): ResearchDayProduct {
  if (!isRecord(value)) invalidResponse("research day response must be an object");
  if (hasOwn(value, "error")) invalidResponse("research day response contains a top-level error");
  if (value.schema_version !== RESEARCH_DAY_SCHEMA) invalidResponse("research day schema_version is invalid");
  if (typeof value.status !== "string" || !RESEARCH_DAY_STATUSES.has(value.status)) {
    invalidResponse("research day status is invalid");
  }
  if (value.endpoint_mode !== "EXACT" && value.endpoint_mode !== "LATEST") {
    invalidResponse("research day endpoint_mode is invalid");
  }
  if (value.endpoint_mode !== expectedEndpointMode) {
    invalidResponse("research day endpoint_mode does not match the request");
  }
  if (typeof value.authoritative !== "boolean") invalidResponse("research day authoritative is invalid");
  const actualDate = researchDayDate(value);
  const emptyLatestDate = value.endpoint_mode === "LATEST" && value.status === "NOT_MATERIALIZED" && !actualDate;
  if (!emptyLatestDate && actualDate && !isGregorianDate(actualDate)) {
    invalidResponse("research day date is invalid");
  }
  if (expectedResearchDate !== undefined) {
    if (!isGregorianDate(expectedResearchDate) || actualDate !== expectedResearchDate) {
      invalidResponse("research day date does not match the request");
    }
  }
  if (!Array.isArray(value.cannot_confirm) || !value.cannot_confirm.every((item) => typeof item === "string")) {
    invalidResponse("research day cannot_confirm must be a string array");
  }
  if (value.write_policy !== "read_only") invalidResponse("research day write_policy is invalid");
  if (value.recommendation_status !== "RESEARCH_ONLY") {
    invalidResponse("research day recommendation_status is invalid");
  }
  for (const safetyField of ["production_allowed", "buy_gate_updated", "orders_sent"]) {
    if (value[safetyField] !== false) invalidResponse(`research day ${safetyField} must be false`);
  }
  if (value.status !== "NOT_MATERIALIZED") {
    if (value.is_full_day !== true) invalidResponse("research day is_full_day is invalid");
    validateResearchDayCounts(value);
    validateResearchDayCoverage(value);
  }
  return value as ResearchDayProduct;
}

async function load(
  url: string,
  expectedEndpointMode: ResearchLaneEndpointMode,
  expectedResearchDate?: string,
  options?: ResearchLaneRequestOptions,
): Promise<ResearchLane> {
  let response: Response;
  try {
    response = options
      ? await fetch(url, { cache: "no-store", signal: options.signal })
      : await fetch(url);
  } catch (reason) {
    throw new ResearchLaneRequestError(
      "NETWORK_REJECTED",
      "research lane network request rejected",
      undefined,
      reason,
    );
  }
  if (!response.ok) {
    throw new ResearchLaneRequestError(
      "HTTP_NON_2XX",
      `research lane request failed (HTTP ${response.status})`,
      response.status,
    );
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch (reason) {
    throw new ResearchLaneRequestError(
      "INVALID_RESPONSE",
      "research lane response is not valid JSON",
      undefined,
      reason,
    );
  }
  try {
    return validateResearchLaneResponse(payload, expectedEndpointMode, expectedResearchDate);
  } catch (reason) {
    throw new ResearchLaneRequestError(
      "INVALID_RESPONSE",
      reason instanceof Error ? reason.message : "research lane response shape is invalid",
      undefined,
      reason,
    );
  }
}

// Preserve the original v7 consumer contract for the one-argument research
// view path: it owns the Chinese date-evidence error and may render the
// producer's older READY payload shape.  The manager passes request options
// and therefore opts into the strict, date-bound contract above.
async function loadLegacy(url: string): Promise<ResearchLane> {
  const response = await fetch(url);
  if (!response.ok) throw new Error("research lane request failed");
  return response.json() as Promise<ResearchLane>;
}

export function loadResearchLane(
  researchDate: string,
  options?: ResearchLaneRequestOptions,
): Promise<ResearchLane> {
  const url = `/api/v3/research/lane?research_date=${encodeURIComponent(researchDate)}`;
  return options
    ? load(url, "EXACT", researchDate, options)
    : loadLegacy(url);
}

export function loadResearchLaneLatest(): Promise<ResearchLane> {
  return loadLegacy("/api/v3/research/lane");
}

async function loadDay(
  url: string,
  expectedEndpointMode: ResearchLaneEndpointMode,
  expectedResearchDate?: string,
  options?: ResearchLaneRequestOptions,
): Promise<ResearchDayProduct> {
  let response: Response;
  try {
    response = options
      ? await fetch(url, { cache: "no-store", signal: options.signal })
      : await fetch(url);
  } catch (reason) {
    throw new ResearchLaneRequestError(
      "NETWORK_REJECTED",
      "research day network request rejected",
      undefined,
      reason,
    );
  }
  if (!response.ok) {
    throw new ResearchLaneRequestError(
      "HTTP_NON_2XX",
      `research day request failed (HTTP ${response.status})`,
      response.status,
    );
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch (reason) {
    throw new ResearchLaneRequestError(
      "INVALID_RESPONSE",
      "research day response is not valid JSON",
      undefined,
      reason,
    );
  }
  try {
    return validateResearchDayResponse(payload, expectedEndpointMode, expectedResearchDate);
  } catch (reason) {
    throw new ResearchLaneRequestError(
      "INVALID_RESPONSE",
      reason instanceof Error ? reason.message : "research day response shape is invalid",
      undefined,
      reason,
    );
  }
}

export function loadResearchDay(
  researchDate: string,
  options?: ResearchLaneRequestOptions,
): Promise<ResearchDayProduct> {
  return loadDay(
    `/api/v3/research/day?archive_date=${encodeURIComponent(researchDate)}`,
    "EXACT",
    researchDate,
    options,
  );
}
