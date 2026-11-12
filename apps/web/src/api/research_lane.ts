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

export interface ResearchPdfDocumentDetail extends Record<string, unknown> {
  schema_version: "v4.zsxq_pdf_document_detail.v1";
  document_id: string;
  research_date: string;
  status: string;
  pages: Array<Record<string, unknown>>;
}

export type MachineCardsStatus = "READY" | "READY_EMPTY" | "NOT_MATERIALIZED" | "CANNOT_CONFIRM";

export interface MachineCardSource {
  source_group_name: string | null;
  source_group_status: string;
  original_filename: string;
  source_directory: string;
  source_relative_path: string;
  source_pdf_path: string;
}

export interface MachineCardReview {
  origin_status: string | null;
  source_review_status: string | null;
  user_acceptance_status: string | null;
  review_status: "REVIEWED" | "NOT_REVIEWED" | "CANNOT_CONFIRM";
  human_reviewed: boolean;
  user_accepted: boolean;
}

export interface MachineCardReport {
  path: string;
  receipt_path: string;
  sha256: string | null;
  bytes: number | null;
  preview: string;
  preview_max_chars: number;
}

/** One displayable machine-generated PDF report; never human-reviewed by default. */
export interface MachineCard {
  document_id: string;
  research_date: string;
  status: string;
  batch_id: string;
  superseded_batch_ids: string[];
  title: string;
  title_source: string;
  source: MachineCardSource;
  review: MachineCardReview;
  report: MachineCardReport;
  machine_generated: true;
  read_only: true;
  research_only: true;
  production_allowed: false;
  buy_gate_updated: false;
  orders_sent: false;
}

export interface MachineCardsPayload {
  schema_version: "v4.pdf_research.machine_cards.v1";
  status: MachineCardsStatus;
  research_date: string;
  card_count: number;
  matched_count: number;
  duplicate_count: number;
  cannot_confirm_count: number;
  cannot_confirm: string[];
  cannot_confirm_document_ids: string[];
  unresolved_document_ids: string[];
  truncated: boolean;
  max_cards_per_date: number;
  preview_max_chars: number;
  source_index_used: boolean;
  items: MachineCard[];
  research_only: true;
  production_allowed: false;
  buy_gate_updated: false;
  orders_sent: false;
}

export type StockClueStatus = "READY" | "READY_EMPTY" | "NOT_MATERIALIZED" | "CANNOT_CONFIRM";

export type StockClueMatchedBy = "NAME" | "CODE" | "BOTH";

export type StockClueConfirmReason = "CODE" | "CONTEXT" | "COHERENCE";

export type StockClueNameMapStatus = "READY" | "CANNOT_CONFIRM";

export type StockClueCorpusCacheStatus = "HIT" | "BUILT" | "CANNOT_CONFIRM";

/** A low-evidence exclusion: a common word or a company without corpus context. */
export interface StockClueGenericFiltered {
  name: string;
  ts_code: string;
  link_probability: number;
  total: number;
}

/** A weak-only name hit exposed separately from the confirmed list. */
export interface StockClueWeakItem {
  name: string;
  ts_code: string;
  weak_document_count: number;
  link_probability: number | null;
}

/** One stock mentioned by at least one machine research report on the exact date. */
export interface StockClue {
  ts_code: string;
  name: string | null;
  /** Confirmed report count; weak-only rows keep this at 0. */
  document_count: number;
  /** Unconfirmed name-only report count. */
  weak_document_count: number;
  /** Corpus-wide raw company-context ratio (evidenced / total), when sampled. */
  link_probability: number | null;
  confirm_reasons: StockClueConfirmReason[];
  document_titles: string[];
  matched_by: StockClueMatchedBy;
  first_seen_date: string;
  last_seen_date: string;
}

export interface StockCluesPayload {
  schema_version: "v4.research.stock_clues.v1";
  status: StockClueStatus;
  research_date: string;
  card_count: number;
  scanned_card_count: number;
  skipped_card_count: number;
  stock_count: number;
  confirmed_stock_count: number;
  weak_only_stock_count: number;
  corpus_report_count: number;
  /** SHA-256 over sorted report paths, mtimes and sizes; empty when unavailable. */
  corpus_fingerprint: string;
  corpus_cache_status: StockClueCorpusCacheStatus;
  generic_filtered: StockClueGenericFiltered[];
  /** Up to 20 weak-only rows; never mixed into `items`. */
  weak_items: StockClueWeakItem[];
  clue_limit: number;
  name_map_status: StockClueNameMapStatus;
  name_map_path: string;
  name_map_trade_date: string;
  truncated_report_count: number;
  cannot_confirm: string[];
  items: StockClue[];
  research_only: true;
  production_allowed: false;
  buy_gate_updated: false;
  orders_sent: false;
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
const MACHINE_CARDS_SCHEMA = "v4.pdf_research.machine_cards.v1";
const MACHINE_CARDS_STATUSES = new Set<MachineCardsStatus>([
  "READY",
  "READY_EMPTY",
  "NOT_MATERIALIZED",
  "CANNOT_CONFIRM",
]);
const STOCK_CLUES_SCHEMA = "v4.research.stock_clues.v1";
const STOCK_CLUES_STATUSES = new Set<StockClueStatus>([
  "READY",
  "READY_EMPTY",
  "NOT_MATERIALIZED",
  "CANNOT_CONFIRM",
]);
const STOCK_CLUE_MATCHED_BY = new Set<StockClueMatchedBy>(["NAME", "CODE", "BOTH"]);
const STOCK_CLUE_CONFIRM_REASONS = new Set<StockClueConfirmReason>(["CODE", "CONTEXT", "COHERENCE"]);
const STOCK_CLUE_NAME_MAP_STATUSES = new Set<StockClueNameMapStatus>(["READY", "CANNOT_CONFIRM"]);
const STOCK_CLUE_CORPUS_CACHE_STATUSES = new Set<StockClueCorpusCacheStatus>([
  "HIT",
  "BUILT",
  "CANNOT_CONFIRM",
]);
const STOCK_CLUE_TITLE_LIMIT = 5;
const STOCK_CLUE_GENERIC_FILTERED_LIMIT = 30;
const STOCK_CLUE_WEAK_ITEMS_LIMIT = 20;
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

function validateNonNegativeInteger(value: unknown, field: string): void {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    invalidResponse(`${field} is invalid`);
  }
}

function validateStringArray(value: unknown, field: string): void {
  if (!Array.isArray(value) || !value.every((item) => typeof item === "string")) {
    invalidResponse(`${field} must be a string array`);
  }
}

function isProbability(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
}

/** Validate the read-only machine-card projection before Vue renders it. */
export function validateMachineCardsResponse(
  value: unknown,
  expectedResearchDate?: string,
): MachineCardsPayload {
  if (!isRecord(value)) invalidResponse("research machine cards response must be an object");
  if (hasOwn(value, "error")) invalidResponse("research machine cards response contains a top-level error");
  if (value.schema_version !== MACHINE_CARDS_SCHEMA) {
    invalidResponse("research machine cards schema_version is invalid");
  }
  if (typeof value.status !== "string" || !MACHINE_CARDS_STATUSES.has(value.status as MachineCardsStatus)) {
    invalidResponse("research machine cards status is invalid");
  }
  if (typeof value.research_date !== "string" || !isGregorianDate(value.research_date)) {
    invalidResponse("research machine cards research_date is invalid");
  }
  if (expectedResearchDate !== undefined) {
    if (!isGregorianDate(expectedResearchDate) || value.research_date !== expectedResearchDate) {
      invalidResponse("research machine cards research_date does not match the request");
    }
  }
  for (const field of [
    "card_count",
    "matched_count",
    "duplicate_count",
    "cannot_confirm_count",
    "max_cards_per_date",
    "preview_max_chars",
  ] as const) {
    validateNonNegativeInteger(value[field], `research machine cards ${field}`);
  }
  validateStringArray(value.cannot_confirm, "research machine cards cannot_confirm");
  validateStringArray(value.cannot_confirm_document_ids, "research machine cards cannot_confirm_document_ids");
  validateStringArray(value.unresolved_document_ids, "research machine cards unresolved_document_ids");
  if (typeof value.truncated !== "boolean") invalidResponse("research machine cards truncated is invalid");
  if (typeof value.source_index_used !== "boolean") {
    invalidResponse("research machine cards source_index_used is invalid");
  }
  if (value.research_only !== true) invalidResponse("research machine cards research_only must be true");
  for (const safetyField of ["production_allowed", "buy_gate_updated", "orders_sent"] as const) {
    if (value[safetyField] !== false) invalidResponse(`research machine cards ${safetyField} must be false`);
  }
  if (!Array.isArray(value.items) || value.items.some((item) => !isRecord(item))) {
    invalidResponse("research machine cards items must be an object array");
  }
  const items = value.items as Array<Record<string, unknown>>;
  if (items.length !== value.card_count) invalidResponse("research machine cards card_count does not match items");
  if (value.status === "READY" && items.length === 0) {
    invalidResponse("research machine cards READY response has no items");
  }
  if (["READY_EMPTY", "NOT_MATERIALIZED"].includes(value.status as string) && items.length !== 0) {
    invalidResponse("research machine cards empty response has items");
  }
  for (const item of items) {
    if (typeof item.document_id !== "string" || !item.document_id) {
      invalidResponse("research machine card document_id is invalid");
    }
    if (item.research_date !== value.research_date) {
      invalidResponse("research machine card research_date does not match the response");
    }
    if (typeof item.status !== "string" || typeof item.title !== "string") {
      invalidResponse("research machine card title or status is invalid");
    }
    validateStringArray(item.superseded_batch_ids, "research machine card superseded_batch_ids");
    if (!isRecord(item.source) || typeof item.source.original_filename !== "string") {
      invalidResponse("research machine card source is invalid");
    }
    if (item.source.source_group_name !== null && typeof item.source.source_group_name !== "string") {
      invalidResponse("research machine card source_group_name is invalid");
    }
    if (!isRecord(item.review) || typeof item.review.human_reviewed !== "boolean") {
      invalidResponse("research machine card review is invalid");
    }
    if (!isRecord(item.report) || typeof item.report.preview !== "string") {
      invalidResponse("research machine card report is invalid");
    }
    if (item.machine_generated !== true || item.read_only !== true) {
      invalidResponse("research machine card flags are invalid");
    }
    for (const safetyField of ["production_allowed", "buy_gate_updated", "orders_sent"] as const) {
      if (item[safetyField] !== false) invalidResponse(`research machine card ${safetyField} must be false`);
    }
  }
  return value as unknown as MachineCardsPayload;
}

/** Validate the read-only stock clue projection before Vue renders it. */
export function validateStockCluesResponse(
  value: unknown,
  expectedResearchDate?: string,
): StockCluesPayload {
  if (!isRecord(value)) invalidResponse("research stock clues response must be an object");
  if (hasOwn(value, "error")) invalidResponse("research stock clues response contains a top-level error");
  if (value.schema_version !== STOCK_CLUES_SCHEMA) {
    invalidResponse("research stock clues schema_version is invalid");
  }
  if (typeof value.status !== "string" || !STOCK_CLUES_STATUSES.has(value.status as StockClueStatus)) {
    invalidResponse("research stock clues status is invalid");
  }
  if (typeof value.research_date !== "string" || !isGregorianDate(value.research_date)) {
    invalidResponse("research stock clues research_date is invalid");
  }
  if (expectedResearchDate !== undefined) {
    if (!isGregorianDate(expectedResearchDate) || value.research_date !== expectedResearchDate) {
      invalidResponse("research stock clues research_date does not match the request");
    }
  }
  for (const field of [
    "card_count",
    "scanned_card_count",
    "skipped_card_count",
    "stock_count",
    "confirmed_stock_count",
    "weak_only_stock_count",
    "corpus_report_count",
    "truncated_report_count",
  ] as const) {
    validateNonNegativeInteger(value[field], `research stock clues ${field}`);
  }
  if (
    (value.confirmed_stock_count as number) + (value.weak_only_stock_count as number)
    !== value.stock_count
  ) {
    invalidResponse("research stock clues confirmed and weak-only counts do not match stock_count");
  }
  if (
    typeof value.clue_limit !== "number"
    || !Number.isInteger(value.clue_limit)
    || value.clue_limit < 1
    || value.clue_limit > 200
  ) {
    invalidResponse("research stock clues clue_limit is invalid");
  }
  if (
    typeof value.name_map_status !== "string"
    || !STOCK_CLUE_NAME_MAP_STATUSES.has(value.name_map_status as StockClueNameMapStatus)
  ) {
    invalidResponse("research stock clues name_map_status is invalid");
  }
  if (typeof value.name_map_path !== "string") {
    invalidResponse("research stock clues name_map_path is invalid");
  }
  if (typeof value.name_map_trade_date !== "string") {
    invalidResponse("research stock clues name_map_trade_date is invalid");
  }
  if (value.name_map_status === "READY" && !isGregorianDate(value.name_map_trade_date)) {
    invalidResponse("research stock clues name_map_trade_date is invalid");
  }
  if (
    typeof value.corpus_cache_status !== "string"
    || !STOCK_CLUE_CORPUS_CACHE_STATUSES.has(value.corpus_cache_status as StockClueCorpusCacheStatus)
  ) {
    invalidResponse("research stock clues corpus_cache_status is invalid");
  }
  if (
    typeof value.corpus_fingerprint !== "string"
    || (value.corpus_fingerprint !== "" && !/^[0-9a-f]{64}$/.test(value.corpus_fingerprint))
  ) {
    invalidResponse("research stock clues corpus_fingerprint is invalid");
  }
  if (!Array.isArray(value.generic_filtered) || value.generic_filtered.some((entry) => !isRecord(entry))) {
    invalidResponse("research stock clues generic_filtered must be an object array");
  }
  const genericFiltered = value.generic_filtered as Array<Record<string, unknown>>;
  if (genericFiltered.length > STOCK_CLUE_GENERIC_FILTERED_LIMIT) {
    invalidResponse("research stock clues generic_filtered is too long");
  }
  for (const entry of genericFiltered) {
    if (typeof entry.name !== "string" || !entry.name) {
      invalidResponse("research stock clue generic_filtered name is invalid");
    }
    if (typeof entry.ts_code !== "string" || !entry.ts_code) {
      invalidResponse("research stock clue generic_filtered ts_code is invalid");
    }
    if (!isProbability(entry.link_probability)) {
      invalidResponse("research stock clue generic_filtered link_probability is invalid");
    }
    validateNonNegativeInteger(entry.total, "research stock clue generic_filtered total");
    if (entry.total === 0) {
      invalidResponse("research stock clue generic_filtered total must be positive");
    }
  }
  if (value.corpus_cache_status === "CANNOT_CONFIRM" && genericFiltered.length !== 0) {
    invalidResponse("research stock clues generic_filtered requires a built corpus");
  }
  validateStringArray(value.cannot_confirm, "research stock clues cannot_confirm");
  if (value.research_only !== true) invalidResponse("research stock clues research_only must be true");
  for (const safetyField of ["production_allowed", "buy_gate_updated", "orders_sent"] as const) {
    if (value[safetyField] !== false) invalidResponse(`research stock clues ${safetyField} must be false`);
  }
  if (!Array.isArray(value.items) || value.items.some((item) => !isRecord(item))) {
    invalidResponse("research stock clues items must be an object array");
  }
  const items = value.items as Array<Record<string, unknown>>;
  for (const item of items) {
    if (typeof item.ts_code !== "string" || !item.ts_code) {
      invalidResponse("research stock clue ts_code is invalid");
    }
    if (item.name !== null && typeof item.name !== "string") {
      invalidResponse("research stock clue name is invalid");
    }
    if (
      typeof item.document_count !== "number"
      || !Number.isInteger(item.document_count)
      || item.document_count < 1
    ) {
      invalidResponse("research stock clue items must be confirmed rows");
    }
    if (
      typeof item.weak_document_count !== "number"
      || !Number.isInteger(item.weak_document_count)
      || item.weak_document_count < 0
    ) {
      invalidResponse("research stock clue weak_document_count is invalid");
    }
    if (item.link_probability !== null && !isProbability(item.link_probability)) {
      invalidResponse("research stock clue link_probability is invalid");
    }
    if (value.corpus_cache_status === "CANNOT_CONFIRM" && item.link_probability !== null) {
      invalidResponse("research stock clue link_probability requires a built corpus");
    }
    if (!Array.isArray(item.confirm_reasons)) {
      invalidResponse("research stock clue confirm_reasons must be a string array");
    }
    const confirmReasons = item.confirm_reasons as unknown[];
    if (
      confirmReasons.some(
        (reason) => typeof reason !== "string" || !STOCK_CLUE_CONFIRM_REASONS.has(reason as StockClueConfirmReason),
      )
      || new Set(confirmReasons).size !== confirmReasons.length
    ) {
      invalidResponse("research stock clue confirm_reasons are invalid");
    }
    if ((item.document_count === 0) !== (confirmReasons.length === 0)) {
      invalidResponse("research stock clue confirm_reasons do not match document_count");
    }
    validateStringArray(item.document_titles, "research stock clue document_titles");
    if ((item.document_titles as string[]).length > STOCK_CLUE_TITLE_LIMIT) {
      invalidResponse("research stock clue document_titles are truncated");
    }
    if (
      typeof item.matched_by !== "string"
      || !STOCK_CLUE_MATCHED_BY.has(item.matched_by as StockClueMatchedBy)
    ) {
      invalidResponse("research stock clue matched_by is invalid");
    }
    for (const field of ["first_seen_date", "last_seen_date"] as const) {
      if (!isGregorianDate(item[field])) invalidResponse(`research stock clue ${field} is invalid`);
    }
  }
  if (!Array.isArray(value.weak_items) || value.weak_items.some((entry) => !isRecord(entry))) {
    invalidResponse("research stock clues weak_items must be an object array");
  }
  const weakItems = value.weak_items as Array<Record<string, unknown>>;
  if (weakItems.length > STOCK_CLUE_WEAK_ITEMS_LIMIT) {
    invalidResponse("research stock clues weak_items is too long");
  }
  if (weakItems.length !== Math.min(value.weak_only_stock_count as number, STOCK_CLUE_WEAK_ITEMS_LIMIT)) {
    invalidResponse("research stock clues weak_items does not match the weak-only count");
  }
  const weakItemCodes = new Set<string>();
  for (const item of weakItems) {
    if (typeof item.name !== "string" || !item.name) {
      invalidResponse("research stock clue weak_items name is invalid");
    }
    if (typeof item.ts_code !== "string" || !item.ts_code) {
      invalidResponse("research stock clue weak_items ts_code is invalid");
    }
    if (
      typeof item.weak_document_count !== "number"
      || !Number.isInteger(item.weak_document_count)
      || item.weak_document_count < 1
    ) {
      invalidResponse("research stock clue weak_items weak_document_count is invalid");
    }
    if (item.link_probability !== null && !isProbability(item.link_probability)) {
      invalidResponse("research stock clue weak_items link_probability is invalid");
    }
    if (value.corpus_cache_status === "CANNOT_CONFIRM" && item.link_probability !== null) {
      invalidResponse("research stock clue weak_items link_probability requires a built corpus");
    }
    const code = item.ts_code as string;
    if (weakItemCodes.has(code)) {
      invalidResponse("research stock clue weak_items contains a duplicate ts_code");
    }
    weakItemCodes.add(code);
  }
  for (let index = 1; index < weakItems.length; index += 1) {
    const previous = weakItems[index - 1];
    const current = weakItems[index];
    const previousCount = previous.weak_document_count as number;
    const currentCount = current.weak_document_count as number;
    if (previousCount < currentCount) {
      invalidResponse("research stock clue weak_items must be sorted by weak count descending");
    }
    if (previousCount === currentCount && String(previous.ts_code) > String(current.ts_code)) {
      invalidResponse("research stock clue weak_items must be sorted by ts_code ascending");
    }
  }
  const itemCodes = new Set(items.map((item) => item.ts_code as string));
  for (const code of weakItemCodes) {
    if (itemCodes.has(code)) {
      invalidResponse("research stock clue weak_items must not appear in items");
    }
  }
  const status = value.status as StockClueStatus;
  const confirmedCount = value.confirmed_stock_count as number;
  const weakOnlyCount = value.weak_only_stock_count as number;
  if (status === "READY") {
    if (confirmedCount < 1) invalidResponse("research stock clues READY response has no confirmed stocks");
  } else if (status === "READY_EMPTY") {
    if (confirmedCount !== 0) invalidResponse("research stock clues READY_EMPTY response has confirmed stocks");
    if (weakOnlyCount !== value.stock_count) {
      invalidResponse("research stock clues READY_EMPTY weak-only count does not match stock_count");
    }
  } else if (value.stock_count !== 0 || confirmedCount !== 0 || weakOnlyCount !== 0) {
    invalidResponse("research stock clues non-ready response has stock counts");
  }
  if (items.length !== Math.min(value.confirmed_stock_count as number, value.clue_limit as number)) {
    invalidResponse("research stock clues items length does not match confirmed_stock_count and clue_limit");
  }
  return value as unknown as StockCluesPayload;
}

type JsonRequestResource = "research lane" | "research day" | "research PDF document" | "research machine cards" | "research stock clues";

/** Shared fetch/JSON transport; endpoint-specific contracts stay in their validators. */
async function requestJson(
  url: string,
  resource: JsonRequestResource,
  options?: ResearchLaneRequestOptions,
  legacyLane = false,
): Promise<unknown> {
  let response: Response;
  try {
    response = options
      ? await fetch(url, { cache: "no-store", signal: options.signal })
      : await fetch(url);
  } catch (reason) {
    if (legacyLane) throw reason;
    throw new ResearchLaneRequestError(
      "NETWORK_REJECTED",
      `${resource} network request rejected`,
      undefined,
      reason,
    );
  }
  if (!response.ok) {
    if (legacyLane) throw new Error("research lane request failed");
    throw new ResearchLaneRequestError(
      "HTTP_NON_2XX",
      `${resource} request failed (HTTP ${response.status})`,
      response.status,
    );
  }
  try {
    return await response.json();
  } catch (reason) {
    if (legacyLane) throw reason;
    throw new ResearchLaneRequestError(
      "INVALID_RESPONSE",
      `${resource} response is not valid JSON`,
      undefined,
      reason,
    );
  }
}

async function load(
  url: string,
  expectedEndpointMode: ResearchLaneEndpointMode,
  expectedResearchDate?: string,
  options?: ResearchLaneRequestOptions,
): Promise<ResearchLane> {
  const payload = await requestJson(url, "research lane", options);
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
  return await requestJson(url, "research lane", undefined, true) as ResearchLane;
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

export async function loadResearchPdfDocumentDetail(
  documentId: string,
  researchDate: string,
): Promise<ResearchPdfDocumentDetail> {
  const url = `/api/v3/research/pdf-documents/${encodeURIComponent(documentId)}?research_date=${encodeURIComponent(researchDate)}`;
  const payload = await requestJson(url, "research PDF document", { });
  if (!isRecord(payload)
      || payload.schema_version !== "v4.zsxq_pdf_document_detail.v1"
      || payload.document_id !== documentId
      || payload.research_date !== researchDate
      || !Array.isArray(payload.pages)
      || payload.pages.some((page) => !isRecord(page))) {
    throw new ResearchLaneRequestError(
      "INVALID_RESPONSE",
      "research PDF document response identity or page shape is invalid",
    );
  }
  return payload as ResearchPdfDocumentDetail;
}

export async function fetchMachineCards(researchDate: string): Promise<MachineCardsPayload> {
  const url = `/api/v3/research/machine-cards?research_date=${encodeURIComponent(researchDate)}`;
  const payload = await requestJson(url, "research machine cards", {});
  try {
    return validateMachineCardsResponse(payload, researchDate);
  } catch (reason) {
    throw new ResearchLaneRequestError(
      "INVALID_RESPONSE",
      reason instanceof Error ? reason.message : "research machine cards response shape is invalid",
      undefined,
      reason,
    );
  }
}

/** Read-only stock clue aggregation; independent of the machine-card renderer. */
export async function fetchStockClues(researchDate: string, limit = 50): Promise<StockCluesPayload> {
  const url = `/api/v3/research/stock-clues?research_date=${encodeURIComponent(researchDate)}&limit=${encodeURIComponent(String(limit))}`;
  const payload = await requestJson(url, "research stock clues", {});
  try {
    return validateStockCluesResponse(payload, researchDate);
  } catch (reason) {
    throw new ResearchLaneRequestError(
      "INVALID_RESPONSE",
      reason instanceof Error ? reason.message : "research stock clues response shape is invalid",
      undefined,
      reason,
    );
  }
}

async function loadDay(
  url: string,
  expectedEndpointMode: ResearchLaneEndpointMode,
  expectedResearchDate?: string,
  options?: ResearchLaneRequestOptions,
): Promise<ResearchDayProduct> {
  const payload = await requestJson(url, "research day", options);
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
