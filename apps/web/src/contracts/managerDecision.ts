/**
 * Path-free read DTO for the independent 22:00 manager decision document.
 *
 * The document itself is validated by the server against the exact selection
 * artifact.  This second boundary deliberately contains only the evidence a
 * browser can render: candidate identities, reasons, hashes, and typed
 * statuses.  It never carries a filesystem path or a client-supplied ref.
 */

export const MANAGER_DECISION_READ_SCHEMA = "v3_5.manager_research_decision_read.v1" as const;
export const MANAGER_DECISION_DOCUMENT_SCHEMA = "v3_5.manager_research_decision.v1" as const;
export const MANAGER_DECISION_PHASE = "2200" as const;
export const MANAGER_DECISION_STATE = "INITIAL_RESEARCH_DELTA" as const;
export const MANAGER_DECISION_NOT_MATERIALIZED_REASON = "SELECTION_PRODUCT_NOT_MATERIALIZED" as const;

export const MANAGER_DECISION_STATUSES = [
  "READY",
  "READY_EMPTY",
  "NOT_MATERIALIZED",
  "CANNOT_CONFIRM",
] as const;

export type ManagerDecisionStatus = typeof MANAGER_DECISION_STATUSES[number];
export type ManagerDecisionRole = "CORE" | "CONDITIONAL";

export type ManagerDecisionRow = Readonly<{
  candidate_id: string;
  reason: string;
}>;

export type ManagerQualificationRef = Readonly<{
  candidate_id: string;
  status: string;
  raw_sha256: string | null;
}>;

export type ManagerDecisionSafety = Readonly<{
  RESEARCH_ONLY: true;
  WATCH_ONLY: true;
  production_allowed: false;
  buy_gate_updated: false;
  orders_sent: false;
}>;

export type ManagerDecisionLineage = Readonly<Record<string, unknown>> & {
  selection_artifact_sha256?: string | null;
  selection_run_id?: string | null;
  manager_decision_raw_sha256?: string | null;
  source_date?: string | null;
  target_trade_date?: string | null;
};

export type ManagerDecisionResponse = Readonly<Record<string, unknown>> & {
  schema_version?: string;
  document_schema_version?: string;
  endpoint_mode?: string;
  requested_date?: string;
  target_trade_date?: string;
  status?: string;
  source_date?: string | null;
  phase?: string | null;
  decision_state?: string | null;
  run_id?: string | null;
  generated_at?: string | null;
  cutoff_at?: string | null;
  core?: ManagerDecisionRow[];
  conditional?: ManagerDecisionRow[];
  KEEP?: ManagerDecisionRow[];
  ADD?: ManagerDecisionRow[];
  REMOVE?: ManagerDecisionRow[];
  qualification_refs?: ManagerQualificationRef[];
  safety?: ManagerDecisionSafety;
  lineage?: ManagerDecisionLineage | null;
  reason?: string | null;
  cannot_confirm?: unknown;
};

const DATE_PATTERN = /^\d{8}$/;
const SHA256_PATTERN = /^[0-9a-f]{64}$/i;
const RUN_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/;
const REQUIRED_FIELDS = new Set([
  "schema_version",
  "document_schema_version",
  "endpoint_mode",
  "requested_date",
  "target_trade_date",
  "status",
  "source_date",
  "phase",
  "decision_state",
  "run_id",
  "generated_at",
  "cutoff_at",
  "core",
  "conditional",
  "KEEP",
  "ADD",
  "REMOVE",
  "qualification_refs",
  "safety",
  "lineage",
  "reason",
  "cannot_confirm",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function hasOwn(value: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key);
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

function isIsoTimestamp(value: unknown): value is string {
  if (typeof value !== "string" || !value.trim()) return false;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$/.exec(value);
  if (!match) return false;
  const [, yearText, monthText, dayText, hourText, minuteText, secondText, , offset] = match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const hour = Number(hourText);
  const minute = Number(minuteText);
  const second = Number(secondText);
  if (month < 1 || month > 12 || hour > 23 || minute > 59 || second > 59) return false;
  if (offset !== "Z") {
    const offsetHour = Number(offset.slice(1, 3));
    const offsetMinute = Number(offset.slice(4, 6));
    if (offsetHour > 23 || offsetMinute > 59) return false;
  }
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year
    && date.getUTCMonth() === month - 1
    && date.getUTCDate() === day;
}

function isSha(value: unknown): value is string {
  return typeof value === "string" && SHA256_PATTERN.test(value);
}

function rowIssue(value: unknown, label: string, knownIds?: ReadonlySet<string>): string | null {
  if (!isRecord(value) || Object.keys(value).length !== 2 || !hasOwn(value, "candidate_id") || !hasOwn(value, "reason")) {
    return `${label} 必须只含 candidate_id/reason`;
  }
  if (typeof value.candidate_id !== "string" || !value.candidate_id.trim()) return `${label}.candidate_id 不可确认`;
  if (knownIds && !knownIds.has(value.candidate_id)) return `${label}.candidate_id 不在 selection candidates`;
  if (typeof value.reason !== "string" || !value.reason.trim()) return `${label}.reason 不可确认`;
  return null;
}

function validateRows(value: unknown, label: string, knownIds?: ReadonlySet<string>): string | null {
  if (!Array.isArray(value)) return `${label} 必须是数组`;
  if (value.length > 5 && (label === "core" || label === "conditional")) return `${label} 不得超过5条`;
  const seen = new Set<string>();
  for (let index = 0; index < value.length; index += 1) {
    const issue = rowIssue(value[index], `${label}[${index}]`, knownIds);
    if (issue) return issue;
    const id = (value[index] as ManagerDecisionRow).candidate_id;
    if (seen.has(id)) return `${label} candidate_id 重复`;
    seen.add(id);
  }
  return null;
}

function validateActionRows(value: unknown, label: string, knownIds?: ReadonlySet<string>): string | null {
  return validateRows(value, label, knownIds);
}

function validateSafety(value: unknown): string | null {
  if (!isRecord(value)) return "manager decision safety 不可确认";
  const expected = {
    RESEARCH_ONLY: true,
    WATCH_ONLY: true,
    production_allowed: false,
    buy_gate_updated: false,
    orders_sent: false,
  } as const;
  if (Object.keys(value).length !== Object.keys(expected).length) return "manager decision safety 字段不完整";
  for (const [field, expectedValue] of Object.entries(expected)) {
    if (value[field] !== expectedValue) return `manager decision safety.${field} 不安全`;
  }
  return null;
}

function validateLineage(value: unknown, targetDate: string, status: ManagerDecisionStatus): string | null {
  if (status === "NOT_MATERIALIZED" || status === "CANNOT_CONFIRM") {
    return value === null ? null : "非 materialized manager decision lineage 必须为 null";
  }
  if (!isRecord(value)) return "manager decision lineage 不可确认";
  if (Object.keys(value).some((key) => key.toLowerCase().includes("path"))) return "manager decision lineage 不得携带 path";
  for (const field of ["selection_artifact_sha256", "manager_decision_raw_sha256"] as const) {
    if (!isSha(value[field])) return `manager decision lineage.${field} 不可确认`;
  }
  if (value.selection_run_id !== undefined && value.selection_run_id !== null
    && (typeof value.selection_run_id !== "string" || !RUN_ID_PATTERN.test(value.selection_run_id))) {
    return "manager decision lineage.selection_run_id 不可确认";
  }
  if (value.source_date !== undefined && value.source_date !== null && !isValidDate(value.source_date)) {
    return "manager decision lineage.source_date 不可确认";
  }
  if (value.target_trade_date !== undefined && value.target_trade_date !== null && value.target_trade_date !== targetDate) {
    return "manager decision lineage.target_trade_date 不一致";
  }
  return null;
}

function validateQualificationRefs(value: unknown, knownIds?: ReadonlySet<string>): string | null {
  if (!Array.isArray(value)) return "qualification_refs 必须是数组";
  const seen = new Set<string>();
  for (let index = 0; index < value.length; index += 1) {
    const ref = value[index];
    if (!isRecord(ref) || Object.keys(ref).some((key) => key === "path" || key.endsWith("_path"))
      || Object.keys(ref).length !== 3
      || !hasOwn(ref, "candidate_id") || !hasOwn(ref, "status") || !hasOwn(ref, "raw_sha256")) {
      return `qualification_refs[${index}] 字段不可确认`;
    }
    if (typeof ref.candidate_id !== "string" || !ref.candidate_id.trim()
      || (knownIds && !knownIds.has(ref.candidate_id))) return `qualification_refs[${index}] candidate_id 不可确认`;
    if (seen.has(ref.candidate_id)) return "qualification_refs candidate_id 重复";
    seen.add(ref.candidate_id);
    if (typeof ref.status !== "string" || !ref.status.trim()) return `qualification_refs[${index}].status 不可确认`;
    if (ref.status === "ELIGIBILITY_CANNOT_CONFIRM") {
      if (ref.raw_sha256 !== null) return `qualification_refs[${index}] 未确认资格不得携带 SHA`;
    } else if (!isSha(ref.raw_sha256)) {
      return `qualification_refs[${index}].raw_sha256 不可确认`;
    }
  }
  return null;
}

/** Validate the exact, path-free manager decision read DTO. */
export function validateManagerDecisionResponse(
  value: unknown,
  targetDate: string,
  candidateIds?: readonly string[],
): string | null {
  if (!isValidDate(targetDate)) return "请求日期不是有效的 YYYYMMDD 日期";
  if (!isRecord(value)) return "manager decision 响应不是对象";
  for (const field of REQUIRED_FIELDS) if (!hasOwn(value, field)) return `manager decision 缺少 ${field}`;
  if (value.schema_version !== MANAGER_DECISION_READ_SCHEMA) return "manager decision read schema 不可确认";
  if (value.document_schema_version !== MANAGER_DECISION_DOCUMENT_SCHEMA) return "manager decision document schema 不可确认";
  if (value.endpoint_mode !== "EXACT") return "manager decision endpoint_mode 必须是 EXACT";
  if (value.requested_date !== targetDate || value.target_trade_date !== targetDate) return "manager decision 日期与请求不一致";
  if (!isValidDate(value.requested_date) || !isValidDate(value.target_trade_date)) return "manager decision 日期不可确认";
  if (typeof value.status !== "string" || !(MANAGER_DECISION_STATUSES as readonly string[]).includes(value.status)) return "manager decision status 不可确认";
  const status = value.status as ManagerDecisionStatus;
  if (status === "NOT_MATERIALIZED") {
    if (value.reason !== MANAGER_DECISION_NOT_MATERIALIZED_REASON) {
      return "NOT_MATERIALIZED manager decision reason 不可确认";
    }
  } else if (value.reason !== null) {
    return `${status} manager decision reason 必须为 null`;
  }
  const knownIds = candidateIds ? new Set(candidateIds) : undefined;
  const arrays = ["core", "conditional", "KEEP", "ADD", "REMOVE"] as const;
  for (const field of arrays) {
    const issue = field === "core" || field === "conditional"
      ? validateRows(value[field], field, knownIds)
      : validateActionRows(value[field], field, knownIds);
    if (issue) return issue;
  }
  const coreRows = value.core as ManagerDecisionRow[];
  const conditionalRows = value.conditional as ManagerDecisionRow[];
  const coreIds = new Set(coreRows.map((row) => row.candidate_id));
  const conditionalIds = new Set(conditionalRows.map((row) => row.candidate_id));
  if ([...coreIds].some((id) => conditionalIds.has(id))) return "manager decision core/conditional candidate 重复";
  const actionIds = new Set<string>();
  for (const field of ["KEEP", "ADD", "REMOVE"] as const) {
    for (const row of value[field] as ManagerDecisionRow[]) {
      if (actionIds.has(row.candidate_id)) return "manager decision action candidate 重复";
      actionIds.add(row.candidate_id);
    }
  }
  const allDecisionRows = arrays.flatMap((field) => value[field] as unknown[]);
  if (status === "READY" && !allDecisionRows.length) return "READY manager decision 不得为空";
  if (status === "READY_EMPTY" && allDecisionRows.length) return "READY_EMPTY manager decision 必须为空";
  if (status === "READY_EMPTY" && (value.qualification_refs as unknown[]).length) return "READY_EMPTY qualification_refs 必须为空";
  if (status === "NOT_MATERIALIZED" || status === "CANNOT_CONFIRM") {
    if (allDecisionRows.length || (value.qualification_refs as unknown[]).length) return `${status} manager decision 必须为空`;
  }
  if (status === "READY" || status === "READY_EMPTY") {
    if (!isValidDate(value.source_date)) return "manager decision source_date 不可确认";
    if (value.phase !== MANAGER_DECISION_PHASE) return "manager decision phase 不可确认";
    if (value.decision_state !== MANAGER_DECISION_STATE) return "manager decision state 不可确认";
    if (typeof value.run_id !== "string" || !RUN_ID_PATTERN.test(value.run_id)) return "manager decision run_id 不可确认";
    if (!isIsoTimestamp(value.generated_at) || !isIsoTimestamp(value.cutoff_at)) return "manager decision 时间不可确认";
    if (new Date(value.cutoff_at).getTime() > new Date(value.generated_at).getTime()) return "manager decision cutoff 晚于 generated_at";
  } else if (value.source_date !== null || value.phase !== null || value.decision_state !== null || value.run_id !== null || value.generated_at !== null || value.cutoff_at !== null) {
    return `${status} manager decision identity 必须为空`;
  }
  const safetyIssue = validateSafety(value.safety);
  if (safetyIssue) return safetyIssue;
  const qualificationIssue = validateQualificationRefs(value.qualification_refs, knownIds);
  if (qualificationIssue) return qualificationIssue;
  const lineageIssue = validateLineage(value.lineage, targetDate, status);
  if (lineageIssue) return lineageIssue;
  if (!Array.isArray(value.cannot_confirm) || value.cannot_confirm.some((item) => typeof item !== "string")) return "manager decision cannot_confirm 必须是字符串数组";
  if (status === "CANNOT_CONFIRM" && value.cannot_confirm.length === 0) return "CANNOT_CONFIRM manager decision 必须声明原因";
  if ((status === "READY" || status === "READY_EMPTY" || status === "NOT_MATERIALIZED") && value.cannot_confirm.length > 0) return `${status} manager decision cannot_confirm 不可带失败原因`;
  return null;
}

export const validateManagerDecision = validateManagerDecisionResponse;
