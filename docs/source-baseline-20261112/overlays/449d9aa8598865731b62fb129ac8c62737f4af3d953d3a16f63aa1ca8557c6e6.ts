/**
 * The read-only exact-date selection ledger served by V4.
 *
 * The producer owns the wire contract.  The UI keeps the descriptive fields
 * intentionally permissive because research evidence may be a scalar, a
 * structured JSON value, or a typed unknown.  Rendering must preserve that
 * distinction instead of treating an unknown value as an empty result.
 */

export type SelectionPhase = "2200" | "0830" | "0935" | "1620";

/** A JSON-like research field; nested values remain intentionally unknown. */
export type SelectionValue =
  | string
  | number
  | boolean
  | null
  | unknown[]
  | { [key: string]: unknown };

export type SelectionSourceRef = Readonly<Record<string, unknown>> & {
  type?: string;
  path?: string;
  raw_sha256?: string | null;
  frozen_payload_sha256?: string | null;
  supply_receipt_path?: string;
  supply_receipt_sha256?: string | null;
  source_date?: string;
  source_time?: string;
  json_pointer?: string;
};

export type SelectionCandidate = Readonly<Record<string, unknown>> & {
  candidate_id?: string;
  event_stock_link_id?: string;
  market?: string;
  normalized_code?: string;
  entity_id?: string;
  event_id?: string;
  name?: string;
  stock_name?: string;
  display_name?: string;
  bucket?: string;
  catalyst?: SelectionValue;
  counterevidence?: SelectionValue;
  invalidation?: SelectionValue;
  evidence_level?: SelectionValue;
  financial_bridge?: SelectionValue;
  consensus?: SelectionValue;
  overnight_pending?: SelectionValue;
  source_metadata?: Record<string, unknown> | null;
  source_status?: string;
  published_at?: string | null;
  published_at_aware?: string | null;
  source_time?: string | null;
  acceptance?: string;
  eligibility?: string;
  pit_status?: string;
  research_status?: string;
  recommendation_status?: string;
  route_status?: Record<string, unknown>;
  gemini_status?: string;
  source_refs?: SelectionSourceRef[];
  /** Optional typed manager projection; role/order are never inferred from review fields. */
  manager_decision?: Readonly<Record<string, unknown>>;
};

export type SelectionSnapshot = Readonly<Record<string, unknown>> & {
  phase?: string;
  status?: string;
  run_id?: string | null;
  event_at?: string | null;
  artifact_sha256?: string | null;
  candidate_ids?: string[];
  changes?: Array<Record<string, unknown>>;
  freeze_run_id?: string | null;
  freeze_snapshot_sha256?: string | null;
  snapshot_sha256?: string | null;
};

export type SelectionLineage = Readonly<Record<string, unknown>> & {
  artifact_path?: string | null;
  artifact_sha256?: string | null;
  manifest_path?: string | null;
  manifest_sha256?: string | null;
  receipt_path?: string | null;
  receipt_sha256?: string | null;
  current_path?: string | null;
  current_sha256?: string | null;
  run_id?: string | null;
  target_trade_date?: string | null;
};

export type SelectionCounts = Readonly<Record<string, unknown>> & {
  research_candidates?: number | null;
  formal_shortlist?: number | null;
  snapshots?: number | null;
  intraday_observations?: number | null;
  outcomes?: number | null;
};

export type FormalAuthority = Readonly<Record<string, unknown>> & {
  status?: string;
  target_trade_date?: string;
  pit_status?: string;
  selector_status?: string;
  research_evidence?: boolean;
  manager_decision?: boolean;
  source_sha256?: string | null;
  evidence_refs?: SelectionSourceRef[];
  manager_decision_ref?: Readonly<Record<string, unknown>> | null;
};

export type SelectionProduct = Readonly<Record<string, unknown>> & {
  schema_version?: string;
  contract_id?: string;
  workflow_name?: string;
  pass_signal?: string;
  source_date?: string | null;
  target_trade_date?: string | null;
  requested_date?: string | null;
  endpoint_mode?: string;
  timezone?: string;
  cutoff_at?: string | null;
  generated_at?: string | null;
  run_id?: string | null;
  origin?: string | null;
  status?: string;
  acceptance?: string;
  research_candidates?: SelectionCandidate[];
  formal_shortlist?: string[];
  snapshots?: Partial<Record<SelectionPhase, SelectionSnapshot>>;
  intraday_observations?: Array<Record<string, unknown>>;
  outcomes?: Array<Record<string, unknown>>;
  counts?: SelectionCounts;
  route_status?: Record<string, unknown>;
  gemini_status?: string;
  formal_authority?: FormalAuthority;
  source_refs?: SelectionSourceRef[];
  first_failed_layer?: string | null;
  cannot_confirm?: unknown[];
  manager_decision_ref?: Readonly<Record<string, unknown>> | null;
  lineage?: SelectionLineage | null;
  artifact_sha256?: string;
  manifest_sha256?: string;
  receipt_sha256?: string;
  current_sha256?: string;
  RESEARCH_ONLY?: boolean;
  production_allowed?: boolean;
  buy_gate_updated?: boolean;
  orders_sent?: boolean;
};

/**
 * Wire constants mirrored from the producer-owned V4 selection contract.
 * They are intentionally kept local to the read-only consumer: the browser
 * never repairs, normalizes, or promotes a response that fails these checks.
 */
export const SELECTION_PHASES = ["2200", "0830", "0935", "1620"] as const;
export const SELECTION_PRODUCT_STATUSES = [
  "EARLY_DRAFT_IMPORTED",
  "RESEARCH_SUPPLY_IMPORTED",
  "READY",
  "READY_WITH_DECLARED_GAPS",
  "NOT_MATERIALIZED",
  "CANNOT_CONFIRM",
] as const;
export const SELECTION_SNAPSHOT_STATUSES = [
  "READY",
  "NOT_MATERIALIZED",
  "CANNOT_CONFIRM",
] as const;
export const SELECTION_ORIGINS = [
  "NATURAL",
  "AUTO_RETRY",
  "MANUAL_RECOVERY",
  "HISTORICAL_RECONSTRUCTION",
] as const;

const SELECTION_SCHEMA_VERSION = "v3_5.selection_research_product.v1";
const SELECTION_WORKFLOW_NAME = "V4_SELECTION_RESEARCH_PRODUCT";
const SELECTION_PASS_SIGNAL = "V4_SELECTION_RESEARCH_VERTICAL_SLICE_VERIFIED";
const SELECTION_TIMEZONE = "Asia/Shanghai";
const RESEARCH_SUPPLY_TYPE = "RESEARCH_SUPPLY_FROZEN_ENVELOPE";
const RESEARCH_SUPPLY_ACCEPTANCE = "RESEARCH_SUPPLY_ONLY";
const EARLY_DRAFT_TYPE = "EARLY_DRAFT_FROZEN_ENVELOPE";
const SHA256_PATTERN = /^[0-9a-f]{64}$/i;
const RUN_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/;
const PHASE_SET = new Set<string>(SELECTION_PHASES);
const PRODUCT_STATUS_SET = new Set<string>(SELECTION_PRODUCT_STATUSES);
const SNAPSHOT_STATUS_SET = new Set<string>(SELECTION_SNAPSHOT_STATUSES);
const ORIGIN_SET = new Set<string>(SELECTION_ORIGINS);

const PRODUCT_REQUIRED_FIELDS = new Set([
  "schema_version",
  "contract_id",
  "workflow_name",
  "pass_signal",
  "source_date",
  "target_trade_date",
  "timezone",
  "cutoff_at",
  "generated_at",
  "run_id",
  "origin",
  "status",
  "acceptance",
  "research_candidates",
  "formal_shortlist",
  "snapshots",
  "intraday_observations",
  "outcomes",
  "counts",
  "route_status",
  "gemini_status",
  "formal_authority",
  "source_refs",
  "first_failed_layer",
  "cannot_confirm",
  "endpoint_mode",
  "requested_date",
  "lineage",
  "RESEARCH_ONLY",
  "production_allowed",
  "buy_gate_updated",
  "orders_sent",
]);
const PRODUCT_OPTIONAL_FIELDS = new Set([
  "manager_decision_ref",
  "artifact_sha256",
  "manifest_sha256",
  "receipt_sha256",
  "current_sha256",
]);
const CANDIDATE_FIELDS = new Set([
  "candidate_id",
  "event_stock_link_id",
  "market",
  "normalized_code",
  "entity_id",
  "event_id",
  "bucket",
  "catalyst",
  "counterevidence",
  "invalidation",
  "evidence_level",
  "financial_bridge",
  "consensus",
  "overnight_pending",
  "source_metadata",
  "source_status",
  "published_at",
  "published_at_aware",
  "source_time",
  "acceptance",
  "eligibility",
  "pit_status",
  "research_status",
  "recommendation_status",
  "route_status",
  "gemini_status",
  "source_refs",
]);
const CANDIDATE_OPTIONAL_FIELDS = new Set(["manager_decision"]);
const MANAGER_DECISION_PROJECTION_FIELDS = new Set([
  "schema_version",
  "phase",
  "decision_state",
  "source_date",
  "target_trade_date",
  "run_id",
  "generated_at",
  "cutoff_at",
  "role",
  "order",
  "reason",
]);
const MANAGER_DECISION_PROJECTION_ROLES = new Set(["CORE", "CONDITIONAL"]);
const SNAPSHOT_FIELDS = new Set([
  "phase",
  "status",
  "run_id",
  "event_at",
  "artifact_sha256",
  "candidate_ids",
  "changes",
  "freeze_run_id",
  "freeze_snapshot_sha256",
  "snapshot_sha256",
]);
const FORMAL_AUTHORITY_FIELDS = new Set([
  "status",
  "target_trade_date",
  "pit_status",
  "selector_status",
  "research_evidence",
  "manager_decision",
  "source_sha256",
  "evidence_refs",
  "manager_decision_ref",
]);
const COUNTS_FIELDS = new Set([
  "research_candidates",
  "formal_shortlist",
  "snapshots",
  "intraday_observations",
  "outcomes",
]);
const LINEAGE_FIELDS = new Set([
  "artifact_path",
  "artifact_sha256",
  "receipt_path",
  "receipt_sha256",
  "manifest_path",
  "manifest_sha256",
  "current_path",
  "current_sha256",
  "run_id",
  "target_trade_date",
]);
const SUPPLY_SOURCE_FIELDS = new Set([
  "type",
  "path",
  "raw_sha256",
  "frozen_payload_sha256",
  "json_pointer",
  "source_date",
  "source_time",
  "supply_receipt_path",
  "supply_receipt_sha256",
]);
const EARLY_SOURCE_REQUIRED_FIELDS = new Set([
  "type",
  "path",
  "raw_sha256",
  "frozen_payload_sha256",
  "json_pointer",
  "source_date",
  "source_time",
]);
type SelectionRecord = Record<string, unknown>;

function isSelectionRecord(value: unknown): value is SelectionRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function hasOwn(value: SelectionRecord, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function validSelectionDate(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{8}$/.test(value)) return false;
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(4, 6));
  const day = Number(value.slice(6, 8));
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year
    && date.getUTCMonth() === month - 1
    && date.getUTCDate() === day;
}

function validSha(value: unknown): value is string {
  return typeof value === "string" && SHA256_PATTERN.test(value);
}

function validRunId(value: unknown): value is string {
  return typeof value === "string" && RUN_ID_PATTERN.test(value);
}

function parsedTimestamp(value: unknown): Date | null {
  if (typeof value !== "string" || !value) return null;
  if (!/(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return null;
  const milliseconds = Date.parse(value);
  return Number.isFinite(milliseconds) ? new Date(milliseconds) : null;
}

function canonicalValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map((item) => canonicalValue(item));
  if (!isSelectionRecord(value)) return value;
  return Object.fromEntries(
    Object.keys(value)
      .sort()
      .map((key) => [key, canonicalValue(value[key])]),
  );
}

function sameWireValue(left: unknown, right: unknown): boolean {
  try {
    return JSON.stringify(canonicalValue(left)) === JSON.stringify(canonicalValue(right));
  } catch {
    return false;
  }
}

function canonicalJson(value: unknown): string | null {
  try {
    const serialized = JSON.stringify(canonicalValue(value));
    return typeof serialized === "string" ? serialized : null;
  } catch {
    return null;
  }
}

async function canonicalSha256(value: unknown): Promise<string | null> {
  const serialized = canonicalJson(value);
  const cryptoApi = globalThis.crypto;
  if (!serialized || !cryptoApi?.subtle || typeof TextEncoder === "undefined") return null;
  try {
    const digest = await cryptoApi.subtle.digest(
      "SHA-256",
      new TextEncoder().encode(serialized),
    );
    return [...new Uint8Array(digest)]
      .map((byte) => byte.toString(16).padStart(2, "0"))
      .join("");
  } catch {
    return null;
  }
}

function missingOrExtraFields(
  value: SelectionRecord,
  required: Set<string>,
  allowed: Set<string>,
  label: string,
): string | null {
  const missing = [...required].filter((key) => !hasOwn(value, key));
  if (missing.length) return `${label} 字段不完整，缺少 ${missing.join(", ")}`;
  const extra = Object.keys(value).filter((key) => !allowed.has(key));
  if (extra.length) return `${label} 包含未允许 wire 字段: ${extra.join(", ")}`;
  return null;
}

function validStringList(value: unknown, label: string): string | null {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    return `${label} 必须是字符串数组`;
  }
  const values = value as string[];
  if (values.some((item) => !item)) return `${label} 含空字符串`;
  if (JSON.stringify(values) !== JSON.stringify([...new Set(values)].sort())) {
    return `${label} 必须排序且唯一`;
  }
  return null;
}

function validateSelectionSourceRef(value: unknown, sourceDate: string): string | null {
  if (!isSelectionRecord(value)) return "source_ref 不是对象";
  const type = value.type;
  if (type === RESEARCH_SUPPLY_TYPE) {
    const issue = missingOrExtraFields(value, SUPPLY_SOURCE_FIELDS, SUPPLY_SOURCE_FIELDS, "research supply source_ref");
    if (issue) return issue;
    if (!isNonEmptyString(value.path) || !isNonEmptyString(value.supply_receipt_path)) {
      return "research supply source_ref path 不可为空";
    }
    if (!validSha(value.raw_sha256) || !validSha(value.frozen_payload_sha256) || !validSha(value.supply_receipt_sha256)) {
      return "research supply source_ref SHA 不可确认";
    }
    if (typeof value.json_pointer !== "string" || !/^\/frozen_payload\/event_cards\/(?:0|[1-9][0-9]*)$/.test(value.json_pointer)) {
      return "research supply source_ref JSON pointer 不可确认";
    }
    if (value.source_date !== sourceDate) return "research supply source_ref 日期不一致";
    if (!parsedTimestamp(value.source_time)) return "research supply source_ref source_time 不可确认";
    return null;
  }
  if (type !== EARLY_DRAFT_TYPE) return "source_ref type 不是受支持的冻结来源";
  const missing = [...EARLY_SOURCE_REQUIRED_FIELDS].filter((key) => !hasOwn(value, key));
  if (missing.length) return `early draft source_ref 字段不完整，缺少 ${missing.join(", ")}`;
  if (!isNonEmptyString(value.path) || !validSha(value.raw_sha256) || !validSha(value.frozen_payload_sha256)) {
    return "early draft source_ref path 或 SHA 不可确认";
  }
  if (typeof value.json_pointer !== "string" || !/^\/frozen_payload\/event_cards\/(?:0|[1-9][0-9]*)$/.test(value.json_pointer)) {
    return "early draft source_ref JSON pointer 不可确认";
  }
  if (value.source_date !== sourceDate) return "early draft source_ref 日期不一致";
  if (!parsedTimestamp(value.source_time)) return "early draft source_ref source_time 不可确认";
  return null;
}

function validateManagerDecisionProjection(
  value: unknown,
  sourceDate: string,
  targetDate: string,
  cutoff: Date,
  expectedRunId?: string,
  expectedGeneratedAt?: string,
): string | null {
  if (!isSelectionRecord(value)) return "manager_decision 必须是对象";
  const fieldIssue = missingOrExtraFields(
    value,
    MANAGER_DECISION_PROJECTION_FIELDS,
    MANAGER_DECISION_PROJECTION_FIELDS,
    "manager_decision",
  );
  if (fieldIssue) return fieldIssue;
  if (value.schema_version !== "v3_5.manager_research_decision.v1") {
    return "manager_decision schema_version 不可确认";
  }
  if (value.phase !== "2200") return "manager_decision phase 不可确认";
  if (value.decision_state !== "INITIAL_RESEARCH_DELTA") {
    return "manager_decision decision_state 不可确认";
  }
  if (value.source_date !== sourceDate) return "manager_decision source_date 不一致";
  if (value.target_trade_date !== targetDate) return "manager_decision target_trade_date 不一致";
  if (!validRunId(value.run_id)) return "manager_decision run_id 不可确认";
  if (expectedRunId !== undefined && value.run_id !== expectedRunId) {
    return "manager_decision run_id 与 2200 snapshot 不一致";
  }
  const generated = parsedTimestamp(value.generated_at);
  const projectionCutoff = parsedTimestamp(value.cutoff_at);
  if (!generated || !projectionCutoff) return "manager_decision 时间不可确认";
  if (projectionCutoff.getTime() > generated.getTime()) {
    return "manager_decision cutoff_at 不得晚于 generated_at";
  }
  if (projectionCutoff.getTime() !== cutoff.getTime()) {
    return "manager_decision cutoff_at 与 selection 不一致";
  }
  if (expectedGeneratedAt !== undefined && value.generated_at !== expectedGeneratedAt) {
    return "manager_decision generated_at 与 2200 snapshot 不一致";
  }
  if (!MANAGER_DECISION_PROJECTION_ROLES.has(String(value.role))) {
    return "manager_decision role 不可确认";
  }
  if (!Number.isInteger(value.order) || (value.order as number) < 1 || (value.order as number) > 5) {
    return "manager_decision order 不可确认";
  }
  if (typeof value.reason !== "string" || !value.reason.trim()) return "manager_decision reason 不可确认";
  return null;
}

function validateSelectionCandidate(
  value: unknown,
  sourceDate: string,
  cutoff: Date,
  targetDate: string,
): string | null {
  if (!isSelectionRecord(value)) return "research candidate 不是对象";
  const fieldIssue = missingOrExtraFields(
    value,
    CANDIDATE_FIELDS,
    new Set([...CANDIDATE_FIELDS, ...CANDIDATE_OPTIONAL_FIELDS]),
    "research candidate",
  );
  if (fieldIssue) return fieldIssue;
  const candidateId = value.candidate_id;
  if (!isNonEmptyString(candidateId)) return "candidate_id 不可为空";
  for (const field of [
    "event_stock_link_id",
    "market",
    "normalized_code",
    "entity_id",
    "event_id",
    "acceptance",
    "eligibility",
    "pit_status",
    "research_status",
    "recommendation_status",
  ]) {
    if (!isNonEmptyString(value[field])) return `candidate ${candidateId} 的 ${field} 不可为空`;
  }
  if (value.research_status !== "RESEARCH_ONLY") return `candidate ${candidateId} research_status 必须是 RESEARCH_ONLY`;
  if (value.recommendation_status !== "RESEARCH_ONLY") return `candidate ${candidateId} recommendation_status 必须是 RESEARCH_ONLY`;
  if (value.eligibility !== "ELIGIBILITY_CANNOT_CONFIRM" && value.eligibility !== "ELIGIBLE") {
    return `candidate ${candidateId} eligibility 不可确认`;
  }
  if (value.pit_status !== "READY" && value.pit_status !== "PIT_FAILED" && value.pit_status !== "CANNOT_CONFIRM") {
    return `candidate ${candidateId} pit_status 不可确认`;
  }
  for (const field of [
    "bucket",
    "catalyst",
    "counterevidence",
    "invalidation",
    "evidence_level",
    "financial_bridge",
    "consensus",
    "overnight_pending",
    "source_status",
    "published_at",
    "source_time",
  ]) {
    if (typeof value[field] !== "string") return `candidate ${candidateId} 的 ${field} 必须是字符串`;
  }
  if (!isSelectionRecord(value.source_metadata)) return `candidate ${candidateId} 缺少 source_metadata`;
  if (value.published_at_aware !== null && !parsedTimestamp(value.published_at_aware)) {
    return `candidate ${candidateId} published_at_aware 不可确认`;
  }
  const sourceTime = parsedTimestamp(value.source_time);
  if (!sourceTime) return `candidate ${candidateId} source_time 不可确认`;
  const refs = value.source_refs;
  if (!Array.isArray(refs) || refs.length === 0) return `candidate ${candidateId} 缺少 source_refs`;
  const sourceTypes = new Set<string>();
  for (const ref of refs) {
    const issue = validateSelectionSourceRef(ref, sourceDate);
    if (issue) return `candidate ${candidateId}: ${issue}`;
    if (isSelectionRecord(ref) && typeof ref.type === "string") sourceTypes.add(ref.type);
  }
  if (sourceTypes.size !== 1) return `candidate ${candidateId} source_ref 类型混用`;
  const expectedAcceptance = sourceTypes.has(RESEARCH_SUPPLY_TYPE)
    ? RESEARCH_SUPPLY_ACCEPTANCE
    : "EARLY_DRAFT_FROZEN_ONLY";
  if (value.acceptance !== expectedAcceptance) return `candidate ${candidateId} acceptance 不是冻结研究来源`;
  const entityId = value.entity_id as string;
  const entityDot = entityId.lastIndexOf(".");
  if (entityDot <= 0 || entityDot === entityId.length - 1) return `candidate ${candidateId} entity_id 不可确认`;
  const entityCode = entityId.slice(0, entityDot);
  const entityMarket = entityId.slice(entityDot + 1);
  if ((value.market as string).toUpperCase() !== entityMarket.toUpperCase()
    || (value.normalized_code as string).toUpperCase() !== entityCode.toUpperCase()) {
    return `candidate ${candidateId} identity 字段不一致`;
  }
  const expectedCandidateId = `${entityMarket.toUpperCase()}.${entityCode.toUpperCase()}|${entityId}`;
  if (candidateId !== expectedCandidateId) return `candidate ${candidateId} identity 不可重建`;
  if (value.event_stock_link_id !== `${value.event_id}|${expectedCandidateId}`) {
    return `candidate ${candidateId} event_stock_link_id 不一致`;
  }
  const routeStatus = value.route_status;
  if (!isSelectionRecord(routeStatus) || Object.keys(routeStatus).length !== 2 || !hasOwn(routeStatus, "R1") || !hasOwn(routeStatus, "R6")) {
    return `candidate ${candidateId} route_status 必须严格分离 R1/R6`;
  }
  if (!isNonEmptyString(routeStatus.R1) || !isNonEmptyString(routeStatus.R6)) return `candidate ${candidateId} route_status 不可确认`;
  if (routeStatus.R6 === "GEMINI_DISCOVERY_UNVERIFIED") return `candidate ${candidateId} R6 不得冒充 Gemini`;
  if (value.gemini_status !== "UNVERIFIED" && value.gemini_status !== "NOT_MATERIALIZED") {
    return `candidate ${candidateId} gemini_status 不可确认`;
  }
  if (value.pit_status === "READY") {
    const publishedAware = parsedTimestamp(value.published_at_aware);
    if (!publishedAware) return `candidate ${candidateId} PIT READY 缺少 published_at_aware`;
    if (publishedAware.getTime() > cutoff.getTime() && sourceTypes.has(EARLY_DRAFT_TYPE)) {
      return `candidate ${candidateId} PIT READY 超过 cutoff`;
    }
  }
  if (hasOwn(value, "manager_decision")) {
    const projectionIssue = validateManagerDecisionProjection(
      value.manager_decision,
      sourceDate,
      targetDate,
      cutoff,
    );
    if (projectionIssue) return `candidate ${candidateId}: ${projectionIssue}`;
  }
  return null;
}

function validateSelectionFormalAuthority(value: unknown, targetDate: string): string | null {
  if (!isSelectionRecord(value)) return "formal_authority 不是对象";
  const fieldIssue = missingOrExtraFields(value, FORMAL_AUTHORITY_FIELDS, FORMAL_AUTHORITY_FIELDS, "formal_authority");
  if (fieldIssue) return fieldIssue;
  if (value.status !== "READY" && value.status !== "NOT_MATERIALIZED" && value.status !== "STALE" && value.status !== "CANNOT_CONFIRM") {
    return "formal_authority status 不可确认";
  }
  if (value.target_trade_date !== targetDate) return "formal_authority 日期证据不一致";
  if (typeof value.pit_status !== "string" || typeof value.selector_status !== "string") return "formal_authority gates 缺失";
  if (typeof value.research_evidence !== "boolean" || typeof value.manager_decision !== "boolean") return "formal_authority gates 必须是 boolean";
  if (!Array.isArray(value.evidence_refs) || value.evidence_refs.some((ref) => !isSelectionRecord(ref))) return "formal_authority evidence_refs 不可确认";
  if (value.manager_decision_ref !== null && !isSelectionRecord(value.manager_decision_ref)) return "formal_authority manager_decision_ref 不可确认";
  if (value.status === "READY") {
    if (value.pit_status !== "READY" || value.selector_status !== "READY" || value.research_evidence !== true || value.manager_decision !== true) {
      return "formal_authority READY gates 不完整";
    }
    if (!value.evidence_refs.length || !isSelectionRecord(value.manager_decision_ref)) return "formal_authority READY references 不完整";
    if (!validSha(value.source_sha256)) return "formal_authority READY source_sha256 不可确认";
    for (const ref of value.evidence_refs) {
      if (!isNonEmptyString(ref.path) || !validSha(ref.sha256)) return "formal_authority evidence ref path/SHA 不可确认";
    }
    const decisionRef = value.manager_decision_ref;
    if (!isNonEmptyString(decisionRef.path) || !validSha(decisionRef.sha256)) return "formal_authority manager decision ref path/SHA 不可确认";
  } else {
    if (value.source_sha256 !== null && !validSha(value.source_sha256)) return "formal_authority source_sha256 不可确认";
  }
  return null;
}

function validateSelectionFormalRefs(
  authority: SelectionRecord,
  formalIds: string[],
  sourceDate: string,
  targetDate: string,
): string | null {
  const expectedSourceSha = authority.source_sha256;
  if (!validSha(expectedSourceSha)) return "formal_authority READY source_sha256 不可确认";
  const evidenceRefs = authority.evidence_refs;
  const decisionRef = authority.manager_decision_ref;
  if (!Array.isArray(evidenceRefs) || !evidenceRefs.length || !isSelectionRecord(decisionRef)) {
    return "formal_authority READY references 不完整";
  }
  const authorityRunIds = new Set<string>();
  const validateBindingList = (value: unknown, label: string): string | null => {
    if (!Array.isArray(value) || value.length !== formalIds.length) return `${label} candidate_bindings 不完整`;
    const seen: string[] = [];
    for (const binding of value) {
      if (!isSelectionRecord(binding)
        || !hasOwn(binding, "candidate_id")
        || !hasOwn(binding, "eligibility")
        || !hasOwn(binding, "pit_status")
        || !hasOwn(binding, "source_refs")) return `${label} candidate binding 字段不完整`;
      const candidateId = binding.candidate_id;
      if (typeof candidateId !== "string" || !formalIds.includes(candidateId) || seen.includes(candidateId)) {
        return `${label} candidate binding identity 不一致`;
      }
      if (binding.eligibility !== "ELIGIBLE" || binding.pit_status !== "READY") return `${label} candidate source proof status 不完整`;
      if (!Array.isArray(binding.source_refs) || !binding.source_refs.length) return `${label} candidate source binding refs 缺失`;
      for (const ref of binding.source_refs) {
        const issue = validateSelectionSourceRef(ref, sourceDate);
        if (issue) return `${label}: ${issue}`;
      }
      seen.push(candidateId);
    }
    if (JSON.stringify(seen) !== JSON.stringify(formalIds)) return `${label} candidate binding order 不一致`;
    return null;
  };
  for (const ref of evidenceRefs) {
    if (!isSelectionRecord(ref)) return "formal_authority evidence ref 不是对象";
    for (const field of [
      "schema_version",
      "type",
      "path",
      "sha256",
      "source_sha256",
      "source_date",
      "target_trade_date",
      "run_id",
      "candidate_ids",
      "status",
      "pit_status",
      "candidate_bindings",
    ]) {
      if (!hasOwn(ref, field)) return "formal_authority evidence ref 字段不完整";
    }
    if (ref.schema_version !== "v3_5.selection_formal_evidence.v1" || ref.type !== "EXACT_DATE_PIT") return "formal_authority evidence ref schema/type 不可确认";
    if (!isNonEmptyString(ref.path) || !validSha(ref.sha256) || ref.source_sha256 !== expectedSourceSha) return "formal_authority evidence ref SHA/source binding 不一致";
    if (ref.source_date !== sourceDate || ref.target_trade_date !== targetDate || !validRunId(ref.run_id)) return "formal_authority evidence ref date/run binding 不一致";
    if (!Array.isArray(ref.candidate_ids) || JSON.stringify(ref.candidate_ids) !== JSON.stringify(formalIds) || ref.status !== "READY" || ref.pit_status !== "READY") return "formal_authority evidence ref candidate binding 不一致";
    const bindingIssue = validateBindingList(ref.candidate_bindings, "formal_authority evidence");
    if (bindingIssue) return bindingIssue;
    authorityRunIds.add(ref.run_id);
  }
  const ref = decisionRef;
  for (const field of [
    "schema_version",
    "type",
    "path",
    "sha256",
    "source_sha256",
    "source_date",
    "target_trade_date",
    "run_id",
    "candidate_ids",
    "decision",
    "candidate_bindings",
  ]) {
    if (!hasOwn(ref, field)) return "formal_authority manager decision ref 字段不完整";
  }
  if (ref.schema_version !== "v3_5.selection_manager_decision.v1" || ref.type !== "MANAGER_DECISION") return "formal_authority manager decision ref schema/type 不可确认";
  if (!isNonEmptyString(ref.path) || !validSha(ref.sha256) || ref.source_sha256 !== expectedSourceSha) return "formal_authority manager decision ref SHA/source binding 不一致";
  if (ref.source_date !== sourceDate || ref.target_trade_date !== targetDate || !validRunId(ref.run_id)) return "formal_authority manager decision ref date/run binding 不一致";
  if (!Array.isArray(ref.candidate_ids) || JSON.stringify(ref.candidate_ids) !== JSON.stringify(formalIds) || ref.decision !== true) return "formal_authority manager decision ref candidate binding 不一致";
  const decisionBindingIssue = validateBindingList(ref.candidate_bindings, "formal_authority manager decision");
  if (decisionBindingIssue) return decisionBindingIssue;
  authorityRunIds.add(ref.run_id);
  if (authorityRunIds.size !== 1) return "formal_authority refs 使用冲突的 authority run";
  return null;
}

function applySelectionChanges(
  changes: unknown[],
  currentIds: Set<string>,
  candidateIds: Set<string>,
  phase: string,
): { ids: Set<string>; issue: string | null } {
  const next = new Set(currentIds);
  const seen = new Set<string>();
  for (const change of changes) {
    if (!isSelectionRecord(change) || Object.keys(change).length !== 2 || !hasOwn(change, "action") || !hasOwn(change, "candidate_id")) {
      return { ids: next, issue: `${phase} changes 字段不可确认` };
    }
    const action = change.action;
    const candidateId = change.candidate_id;
    if ((action !== "KEEP" && action !== "ADD" && action !== "REMOVE") || !isNonEmptyString(candidateId)) {
      return { ids: next, issue: `${phase} changes 操作不可确认` };
    }
    if (!candidateIds.has(candidateId)) return { ids: next, issue: `${phase} changes 含未知 candidate_id` };
    if (seen.has(candidateId)) return { ids: next, issue: `${phase} changes candidate 重复` };
    seen.add(candidateId);
    if (action === "KEEP" && !next.has(candidateId)) return { ids: next, issue: `${phase} KEEP candidate 不在当前集合` };
    if (action === "ADD") {
      if (next.has(candidateId)) return { ids: next, issue: `${phase} ADD candidate 已在当前集合` };
      next.add(candidateId);
    }
    if (action === "REMOVE") {
      if (!next.has(candidateId)) return { ids: next, issue: `${phase} REMOVE candidate 不在当前集合` };
      next.delete(candidateId);
    }
  }
  return { ids: next, issue: null };
}

async function validateSelectionSnapshot(
  value: unknown,
  phase: string,
  candidateIds: Set<string>,
): Promise<string | null> {
  if (!isSelectionRecord(value)) return `${phase} snapshot 不是对象`;
  const fieldIssue = missingOrExtraFields(value, SNAPSHOT_FIELDS, SNAPSHOT_FIELDS, `${phase} snapshot`);
  if (fieldIssue) {
    const missing = [...SNAPSHOT_FIELDS].filter((key) => !hasOwn(value, key));
    return missing.length ? `${phase} snapshot 缺少必需字段 ${missing.join(", ")}` : fieldIssue;
  }
  if (value.phase !== phase || typeof value.status !== "string" || !SNAPSHOT_STATUS_SET.has(value.status)) return `${phase} snapshot identity 不可确认`;
  const listIssue = validStringList(value.candidate_ids, `${phase} snapshot candidate_ids`);
  if (listIssue) return listIssue;
  const ids = value.candidate_ids as string[];
  if (ids.some((id) => !candidateIds.has(id))) return `${phase} snapshot 含未知 candidate_id`;
  if (!Array.isArray(value.changes)) return `${phase} snapshot changes 不是数组`;
  const seenChanges = new Set<string>();
  for (const change of value.changes) {
    if (!isSelectionRecord(change) || Object.keys(change).length !== 2 || !isNonEmptyString(change.candidate_id) || (change.action !== "KEEP" && change.action !== "ADD" && change.action !== "REMOVE")) {
      return `${phase} snapshot changes 字段不可确认`;
    }
    if (!candidateIds.has(change.candidate_id) || seenChanges.has(change.candidate_id)) return `${phase} snapshot changes candidate 不可确认`;
    seenChanges.add(change.candidate_id);
  }
  if (value.status !== "READY") {
    if (value.run_id !== null || value.event_at !== null || value.artifact_sha256 !== null || value.freeze_run_id !== null || value.freeze_snapshot_sha256 !== null || value.snapshot_sha256 !== null) {
      return `${phase} 未物化 snapshot 不得携带 identity`;
    }
    if (ids.length || value.changes.length) return `${phase} 未物化 snapshot 不得携带候选或 changes`;
    return null;
  }
  if (!validRunId(value.run_id)) return `${phase} snapshot 缺少有效 run_id`;
  if (!parsedTimestamp(value.event_at)) return `${phase} snapshot 缺少有效 event_at`;
  if (!validSha(value.artifact_sha256)) return `${phase} snapshot 缺少有效 artifact_sha256`;
  if (!validSha(value.snapshot_sha256)) return `${phase} snapshot 缺少有效 snapshot_sha256`;
  const snapshotBody = Object.fromEntries(
    Object.entries(value).filter(([key]) => key !== "snapshot_sha256"),
  );
  const calculatedSnapshotSha = await canonicalSha256(snapshotBody);
  if (!calculatedSnapshotSha) return `${phase} snapshot SHA 无法验证`;
  if (value.snapshot_sha256 !== calculatedSnapshotSha) return `${phase} snapshot SHA mismatch`;
  if (phase === "2200" || phase === "0830") {
    if (value.freeze_run_id !== null || value.freeze_snapshot_sha256 !== null) return `${phase} snapshot 不得携带 freeze binding`;
  } else {
    if (!validRunId(value.freeze_run_id) || !validSha(value.freeze_snapshot_sha256)) return `${phase} snapshot 缺少适用 freeze binding`;
  }
  return null;
}

function validateSelectionLineage(
  value: unknown,
  product: SelectionRecord,
  targetDate: string,
): string | null {
  if (!isSelectionRecord(value)) return "materialized selection 缺少 lineage";
  const fieldIssue = missingOrExtraFields(value, LINEAGE_FIELDS, LINEAGE_FIELDS, "lineage");
  if (fieldIssue) return fieldIssue;
  const runId = product.run_id;
  if (!validRunId(runId) || value.run_id !== runId || value.target_trade_date !== targetDate) return "lineage run/date binding 不一致";
  for (const field of ["artifact_path", "manifest_path", "receipt_path", "current_path"]) {
    if (!isNonEmptyString(value[field]) || !value[field].includes(targetDate)) return `lineage ${field} 不含 target_trade_date`;
  }
  for (const part of ["artifact", "manifest", "receipt"] as const) {
    if (!String(value[`${part}_path`]).includes(runId)) return `lineage ${part}_path 不含 run_id`;
  }
  for (const field of ["artifact_sha256", "manifest_sha256", "receipt_sha256", "current_sha256"]) {
    if (!validSha(value[field])) return `lineage 字段不完整，${field} 不可确认`;
    const alias = product[field];
    if (!validSha(alias) || alias !== value[field]) return `lineage ${field} 与 top-level SHA alias 不一致`;
  }
  return null;
}

function validateSelectionObservations(value: unknown, field: "intraday_observations" | "outcomes"): string | null {
  if (!Array.isArray(value) || value.some((item) => !isSelectionRecord(item))) return `${field} 必须是对象数组`;
  for (const item of value) {
    if (field === "intraday_observations" && item.kind !== "APPEND_ONLY") return "intraday observation 必须是 APPEND_ONLY";
    if (field === "outcomes" && item.kind !== "OUTCOME_REFERENCE") return "outcome 必须是 OUTCOME_REFERENCE";
    if (hasOwn(item, "observed_at") && !parsedTimestamp(item.observed_at)) return `${field}.observed_at 不可确认`;
  }
  return null;
}

/**
 * Validate a response from the exact-date selection API.
 *
 * This is a consumer-side fail-closed check.  It returns a human-readable
 * issue for the UI instead of throwing, and never changes the response.
 */
export async function validateSelectionProduct(value: unknown, targetDate: string): Promise<string | null> {
  if (!isSelectionRecord(value)) return "selection response 不是对象";
  const fieldIssue = missingOrExtraFields(value, PRODUCT_REQUIRED_FIELDS, new Set([...PRODUCT_REQUIRED_FIELDS, ...PRODUCT_OPTIONAL_FIELDS]), "selection response");
  if (fieldIssue) return fieldIssue;
  if (value.schema_version !== SELECTION_SCHEMA_VERSION) return `schema_version 不是 ${SELECTION_SCHEMA_VERSION}`;
  if (value.contract_id !== SELECTION_SCHEMA_VERSION) return "contract_id 不匹配 selection research product";
  if (value.workflow_name !== SELECTION_WORKFLOW_NAME) return "workflow_name 不匹配 selection research product";
  if (value.pass_signal !== SELECTION_PASS_SIGNAL) return "pass_signal 不匹配 selection research product";
  if (value.endpoint_mode !== "EXACT") return "endpoint_mode 不是 EXACT";
  if (value.timezone !== SELECTION_TIMEZONE) return "timezone 不是 Asia/Shanghai";
  if (value.target_trade_date !== targetDate || !validSelectionDate(value.target_trade_date)) return "target_trade_date 与请求不一致";
  if (value.requested_date !== targetDate || !validSelectionDate(value.requested_date)) return "requested_date 与请求不一致";
  if (typeof value.status !== "string" || !PRODUCT_STATUS_SET.has(value.status)) return "status 不在 selection contract 中";
  if (value.RESEARCH_ONLY !== true || value.production_allowed !== false || value.buy_gate_updated !== false || value.orders_sent !== false) {
    return "安全四旗未满足只读边界";
  }
  const candidates = value.research_candidates;
  if (!Array.isArray(candidates)) return "research_candidates 不是数组";
  const status = value.status as string;
  const materialized = status !== "NOT_MATERIALIZED" && status !== "CANNOT_CONFIRM";
  if (materialized) {
    if (!validSelectionDate(value.source_date)) return "materialized 产品必须提供有效 source_date";
    if (!validRunId(value.run_id)) return "materialized 产品必须提供 run_id";
    if (!ORIGIN_SET.has(String(value.origin))) return "materialized 产品 origin 不可确认";
    const generated = parsedTimestamp(value.generated_at);
    const cutoff = parsedTimestamp(value.cutoff_at);
    if (!generated || !cutoff) return "materialized 产品必须提供 generated_at/cutoff_at";
    if (cutoff.getTime() > generated.getTime()) return "materialized 产品 cutoff_at 不得晚于 generated_at";
    if (value.acceptance !== RESEARCH_SUPPLY_ACCEPTANCE && value.acceptance !== "EARLY_DRAFT_FROZEN_ONLY") return "materialized 产品 acceptance 不可确认";
    if (status === "READY" && !candidates.length) return "READY 产品必须包含研究候选";
  } else if (value.source_date !== null || value.run_id !== null || value.origin !== null || value.generated_at !== null || value.cutoff_at !== null) {
    return `${status} 响应不得携带 materialized identity`;
  }
  const formal = value.formal_shortlist;
  if (!Array.isArray(formal) || formal.some((id) => typeof id !== "string" || !id) || JSON.stringify(formal) !== JSON.stringify([...new Set(formal)].sort())) {
    return "formal_shortlist 不是排序且唯一的字符串数组";
  }
  const candidateIds: string[] = [];
  for (const candidate of candidates) {
    const issue = validateSelectionCandidate(
      candidate,
      String(value.source_date || ""),
      parsedTimestamp(value.cutoff_at) || new Date(0),
      targetDate,
    );
    if (issue) return issue;
    if (!isSelectionRecord(candidate) || typeof candidate.candidate_id !== "string") return "research_candidates 含无效 candidate_id";
    if (candidateIds.includes(candidate.candidate_id)) return "research_candidates 含重复 candidate_id";
    candidateIds.push(candidate.candidate_id);
  }
  if (JSON.stringify(candidateIds) !== JSON.stringify([...candidateIds].sort())) return "research_candidates 必须按 candidate_id 排序";
  const candidateIdSet = new Set(candidateIds);
  if (formal.some((id) => !candidateIdSet.has(id))) return "formal_shortlist 含未知 candidate_id";
  if (!validSelectionDate(value.source_date) && value.status !== "NOT_MATERIALIZED" && value.status !== "CANNOT_CONFIRM") return "source_date 不是有效日期";
  const counts = value.counts;
  if (!isSelectionRecord(counts)) return "counts 不是对象";
  const countsIssue = missingOrExtraFields(counts, COUNTS_FIELDS, COUNTS_FIELDS, "counts");
  if (countsIssue) return countsIssue;
  const expectedCounts = {
    research_candidates: candidates.length,
    formal_shortlist: formal.length,
    snapshots: SELECTION_PHASES.length,
    intraday_observations: Array.isArray(value.intraday_observations) ? value.intraday_observations.length : -1,
    outcomes: Array.isArray(value.outcomes) ? value.outcomes.length : -1,
  };
  for (const key of Object.keys(expectedCounts) as Array<keyof typeof expectedCounts>) {
    if (typeof counts[key] !== "number" || !Number.isInteger(counts[key]) || counts[key] < 0 || counts[key] !== expectedCounts[key]) {
      return key === "research_candidates" ? "counts.research_candidates 与数组长度不一致" : `counts.${key} 与数组长度不一致`;
    }
  }
  const observationIssue = validateSelectionObservations(value.intraday_observations, "intraday_observations");
  if (observationIssue) return observationIssue;
  const outcomeIssue = validateSelectionObservations(value.outcomes, "outcomes");
  if (outcomeIssue) return outcomeIssue;
  const formalAuthorityIssue = validateSelectionFormalAuthority(value.formal_authority, targetDate);
  if (formalAuthorityIssue) return formalAuthorityIssue;
  const formalAuthority = value.formal_authority as SelectionRecord;
  const snapshots = value.snapshots;
  if (!isSelectionRecord(snapshots) || Object.keys(snapshots).length !== SELECTION_PHASES.length || Object.keys(snapshots).some((phase) => !PHASE_SET.has(phase))) {
    return "snapshots 未完整覆盖 2200/0830/0935/1620";
  }
  for (const phase of SELECTION_PHASES) {
    const issue = await validateSelectionSnapshot(snapshots[phase], phase, candidateIdSet);
    if (issue) return issue;
  }
  const snapshotsByPhase = snapshots as SelectionRecord;
  const snapshot2200 = snapshotsByPhase["2200"] as SelectionRecord;
  const snapshot0830 = snapshotsByPhase["0830"] as SelectionRecord;
  const snapshot0935 = snapshotsByPhase["0935"] as SelectionRecord;
  const snapshot1620 = snapshotsByPhase["1620"] as SelectionRecord;
  if (snapshot2200.status === "READY" && (snapshot2200.changes as unknown[]).length) return "2200 READY snapshot 初始阶段不得携带 changes";
  const sourceTypes = new Set<string>();
  for (const candidate of candidates) {
    for (const ref of (candidate as SelectionRecord).source_refs as unknown[]) {
      if (isSelectionRecord(ref) && typeof ref.type === "string") sourceTypes.add(ref.type);
    }
  }
  if (sourceTypes.size > 1) return "selection product source_ref 类型混用";
  const supplyProduct = sourceTypes.has(RESEARCH_SUPPLY_TYPE);
  if (candidates.length && value.acceptance !== (supplyProduct ? RESEARCH_SUPPLY_ACCEPTANCE : "EARLY_DRAFT_FROZEN_ONLY")) return "selection product acceptance 与来源类型不一致";
  const managerDecisionRef = value.manager_decision_ref;
  if (managerDecisionRef !== null && managerDecisionRef !== undefined) {
    if (!supplyProduct || !isSelectionRecord(managerDecisionRef) || Object.keys(managerDecisionRef).length !== 2 || !isNonEmptyString(managerDecisionRef.path) || !validSha(managerDecisionRef.raw_sha256)) {
      return "manager_decision_ref 不是严格的 ref";
    }
  }
  if (supplyProduct && snapshot2200.status === "READY" && managerDecisionRef === null || supplyProduct && snapshot2200.status === "READY" && managerDecisionRef === undefined) return "research supply 2200 缺少 manager_decision_ref";
  if (supplyProduct && snapshot2200.status !== "READY" && managerDecisionRef !== null && managerDecisionRef !== undefined) return "research supply manager_decision_ref 没有 2200 snapshot 依据";
  const projectedCandidates = candidates.filter((candidate) =>
    isSelectionRecord(candidate) && hasOwn(candidate, "manager_decision"));
  if (projectedCandidates.length) {
    if (managerDecisionRef === null || managerDecisionRef === undefined) {
      return "manager_decision projection 缺少严格 ref";
    }
    if (snapshot2200.status !== "READY") {
      return "manager_decision projection 需要 READY 的 2200 snapshot";
    }
    if (!isSelectionRecord(managerDecisionRef)
      || snapshot2200.artifact_sha256 !== managerDecisionRef.raw_sha256) {
      return "manager_decision projection ref 与 2200 snapshot 不一致";
    }
    const projectedIds = projectedCandidates
      .map((candidate) => (candidate as SelectionRecord).candidate_id)
      .filter((id): id is string => typeof id === "string");
    if (!sameWireValue(projectedIds.sort(), [...(snapshot2200.candidate_ids as string[])].sort())) {
      return "manager_decision projection 与 2200 snapshot 候选集合不一致";
    }
    const selectionCutoff = parsedTimestamp(value.cutoff_at);
    if (!selectionCutoff) return "manager_decision projection cutoff 不可确认";
    const roleOrders: Record<"CORE" | "CONDITIONAL", number[]> = {
      CORE: [],
      CONDITIONAL: [],
    };
    for (const candidate of projectedCandidates) {
      const projection = (candidate as SelectionRecord).manager_decision;
      const issue = validateManagerDecisionProjection(
        projection,
        String(value.source_date),
        targetDate,
        selectionCutoff,
        String(snapshot2200.run_id),
        String(snapshot2200.event_at),
      );
      if (issue) return `manager_decision projection 不可确认：${issue}`;
      const typedProjection = projection as SelectionRecord;
      roleOrders[typedProjection.role as "CORE" | "CONDITIONAL"].push(
        typedProjection.order as number,
      );
    }
    for (const role of ["CORE", "CONDITIONAL"] as const) {
      const orders = roleOrders[role].sort((left, right) => left - right);
      if (orders.length > 5 || orders.some((order, index) => order !== index + 1)) {
        return `manager_decision projection ${role} role/order 不连续或超过上限`;
      }
    }
  }
  if (snapshot0830.status === "READY") {
    if (snapshot2200.status !== "READY") return "0830 READY 依赖 READY 的 2200";
    const applied = applySelectionChanges(snapshot0830.changes as unknown[], new Set(snapshot2200.candidate_ids as string[]), candidateIdSet, "0830");
    if (applied.issue) return applied.issue;
    if (JSON.stringify([...applied.ids].sort()) !== JSON.stringify(snapshot0830.candidate_ids)) return "0830 changes 与候选集合不一致";
  }
  for (const [phase, snapshot] of [["0935", snapshot0935], ["1620", snapshot1620]] as Array<[string, SelectionRecord]>) {
    if (snapshot.status !== "READY") continue;
    if (snapshot0830.status !== "READY") return `${phase} READY 依赖 READY 的 0830`;
    if (snapshot.freeze_run_id !== snapshot0830.run_id || snapshot.freeze_snapshot_sha256 !== snapshot0830.snapshot_sha256) return `${phase} freeze binding 与 0830 不一致`;
    const applied = applySelectionChanges(snapshot.changes as unknown[], new Set(snapshot0830.candidate_ids as string[]), candidateIdSet, phase);
    if (applied.issue) return applied.issue;
    if ([...applied.ids].sort().join("\n") !== (snapshot.candidate_ids as string[]).join("\n")) return `${phase} changes 与候选集合不一致`;
    if ((snapshot.changes as Array<SelectionRecord>).some((change) => change.action === "REMOVE" || (change.action === "KEEP" && !(snapshot0830.candidate_ids as string[]).includes(change.candidate_id as string)) || (change.action === "ADD" && (snapshot0830.candidate_ids as string[]).includes(change.candidate_id as string)))) return `${phase} changes 改写 0830 freeze`;
    if ([...(new Set(snapshot.candidate_ids as string[]))].sort().join("\n") !== [...(new Set(snapshot0830.candidate_ids as string[]))].sort().join("\n")) return `${phase} 改变 0830 frozen membership`;
  }
  if (snapshot0935.status === "READY" && !(value.intraday_observations as SelectionRecord[]).some((item) => item.kind === "APPEND_ONLY" && item.freeze_run_id === snapshot0830.run_id && item.freeze_snapshot_sha256 === snapshot0830.snapshot_sha256)) return "0935 READY 缺少绑定 0830 的 append-only observation";
  if (snapshot1620.status === "READY" && !(value.outcomes as SelectionRecord[]).some((item) => item.kind === "OUTCOME_REFERENCE" && item.freeze_run_id === snapshot0830.run_id && item.freeze_snapshot_sha256 === snapshot0830.snapshot_sha256)) return "1620 READY 缺少绑定 0830 的 outcome";
  const refs = value.source_refs;
  if (!Array.isArray(refs)) return "source_refs 不是数组";
  for (const ref of refs) {
    const issue = validateSelectionSourceRef(ref, validSelectionDate(value.source_date) ? value.source_date : "");
    if (issue) return issue;
  }
  const flattenedRefs = candidates.flatMap((candidate) => (candidate as SelectionRecord).source_refs as unknown[]);
  if (!sameWireValue(refs, flattenedRefs)) return "source_refs 与 candidates 不一致";
  if (materialized) {
    if (!candidates.length) return "READY 产品必须包含研究候选";
    const lineageIssue = validateSelectionLineage(value.lineage, value, targetDate);
    if (lineageIssue) return lineageIssue;
    for (const alias of ["artifact_sha256", "manifest_sha256", "receipt_sha256", "current_sha256"]) {
      if (!validSha(value[alias])) return `lineage 字段不完整，缺少 ${alias}`;
    }
  } else {
    if (value.source_date !== null || value.run_id !== null || value.origin !== null || value.generated_at !== null || value.cutoff_at !== null) return `${status} 响应不得携带 materialized identity`;
    if (value.acceptance !== "NOT_MATERIALIZED" || candidates.length || formal.length || refs.length) return `${status} 响应必须保持空研究账本`;
    if (value.lineage !== null) return `${status} 响应不得携带 lineage`;
    for (const alias of ["artifact_sha256", "manifest_sha256", "receipt_sha256", "current_sha256"]) if (hasOwn(value, alias)) return `${status} 响应不得携带 ${alias}`;
    if (managerDecisionRef !== null && managerDecisionRef !== undefined) return `${status} 响应不得携带 manager_decision_ref`;
    if (!["2200", "0830", "0935", "1620"].every((phase) => (snapshotsByPhase[phase] as SelectionRecord).status !== "READY")) return `${status} 响应不得声明 READY snapshot`;
    if (status === "CANNOT_CONFIRM" && !isNonEmptyString(value.first_failed_layer)) return "CANNOT_CONFIRM 响应必须声明 first_failed_layer";
    if (!isNonEmptyString(value.first_failed_layer)) return `${status} 响应必须声明 first_failed_layer`;
  }
  const routeStatus = value.route_status;
  if (!isSelectionRecord(routeStatus) || Object.keys(routeStatus).length !== 4 || !["R1", "R2", "R6", "GEMINI"].every((key) => isNonEmptyString(routeStatus[key]))) return "route_status 必须严格分离 R1/R2/R6/GEMINI";
  if (routeStatus.R6 === "GEMINI_DISCOVERY_UNVERIFIED") return "selection R6 不得冒充 Gemini";
  if (value.gemini_status !== "UNVERIFIED" && value.gemini_status !== "NOT_MATERIALIZED") return "Gemini status 不可确认";
  if (routeStatus.GEMINI !== value.gemini_status) return "Gemini route/status 不一致";
  const cannotIssue = validStringList(value.cannot_confirm, "cannot_confirm");
  if (cannotIssue) return cannotIssue;
  const cannotConfirm = value.cannot_confirm as string[];
  if (!isNonEmptyString(value.first_failed_layer) && cannotConfirm.length) return "cannot_confirm 缺少 first_failed_layer";
  const gaps = new Set<string>();
  for (const phase of SELECTION_PHASES) {
    if ((snapshotsByPhase[phase] as SelectionRecord).status !== "READY") gaps.add(supplyProduct && phase === "2200" ? "SUPPLY_2200_DECISION_NOT_MATERIALIZED" : `SNAPSHOT_${phase}_NOT_MATERIALIZED`);
  }
  if (!formal.length || formalAuthority.status !== "READY") gaps.add("FORMAL_AUTHORITY_NOT_MATERIALIZED");
  if (candidates.some((candidate) => (candidate as SelectionRecord).pit_status !== "READY")) gaps.add("CANDIDATE_PIT_NOT_CONFIRMED");
  if (materialized) {
    const actualGaps = cannotConfirm;
    const expectedGaps = [...gaps].sort();
    if (JSON.stringify(actualGaps) !== JSON.stringify(expectedGaps)) return "selection cannot_confirm gaps 不一致";
    const expectedFirst = expectedGaps[0] || null;
    if (value.first_failed_layer !== expectedFirst) return "selection first_failed_layer 不一致";
    const anyReady = SELECTION_PHASES.some((phase) => (snapshotsByPhase[phase] as SelectionRecord).status === "READY");
    const expectedStatus = anyReady ? (expectedGaps.length ? "READY_WITH_DECLARED_GAPS" : "READY") : (supplyProduct ? "RESEARCH_SUPPLY_IMPORTED" : "EARLY_DRAFT_IMPORTED");
    if (status !== expectedStatus) return `status 与 materialized phases 不一致，期望 ${expectedStatus}`;
    if (status === "READY" && (formalAuthority.status !== "READY" || !formal.length || expectedGaps.length)) return "READY 产品必须完成 formal authority 与全部阶段";
  } else {
    if (status !== "NOT_MATERIALIZED" && status !== "CANNOT_CONFIRM") return "空研究账本必须是 NOT_MATERIALIZED 或 CANNOT_CONFIRM";
  }
  if (formal.length) {
    if (formalAuthority.status !== "READY") return "formal_shortlist 缺少 READY authority";
    const byId = new Map(candidates.map((candidate) => [String((candidate as SelectionRecord).candidate_id), candidate as SelectionRecord]));
    for (const id of formal) {
      const candidate = byId.get(id);
      if (!candidate || candidate.eligibility !== "ELIGIBLE" || candidate.pit_status !== "READY") return "formal_shortlist candidate gate 不完整";
    }
    const formalRefsIssue = validateSelectionFormalRefs(formalAuthority, formal, String(value.source_date), targetDate);
    if (formalRefsIssue) return formalRefsIssue;
  }
  return null;
}
