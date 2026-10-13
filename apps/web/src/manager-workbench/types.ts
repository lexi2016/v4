/** C consumes MWB_V1_20261013; B owns the authoritative JSON samples/schema. */
export const SCHEMA_VERSION = "v4.manager_workbench.v1" as const;
export const LANES = ["ANNOUNCEMENT", "US_MAPPING", "OVERSOLD", "STAGE_REFERENCE", "CLOSE_REFERENCE"] as const;
export type Lane = (typeof LANES)[number];
export type Phase = "PREOPEN" | "INTRADAY" | "NEXT_DAY" | "RETROSPECTIVE" | "MANUAL";
export type Decision = "SELECTED" | "CONDITIONAL_WATCH" | "UNASSESSED" | "NOT_SELECTED" | "OBSERVATION_ONLY";
export type LaneState = "NOT_RUN" | "RUNNING" | "READY" | "READY_EMPTY" | "PARTIAL" | "INPUT_MISSING" | "FAILED" | "NOT_APPLICABLE";
export type JobState = "QUEUED" | "RUNNING" | "SUCCEEDED" | "PARTIAL" | "FAILED" | "CANCELLED" | "INTERRUPTED";
export type EvidenceStatus = "VERIFIED" | "CANNOT_CONFIRM" | "INVALID";

export type Gap = string | { code?: string; message?: string; owner?: string; [key: string]: unknown };
export type NullableCount = number | null;
export interface SafetyFlags {
  research_only?: boolean;
  production_allowed?: boolean;
  buy_gate_updated?: boolean;
  orders_sent?: boolean;
}
export interface Envelope<T> extends SafetyFlags {
  schema_version: typeof SCHEMA_VERSION;
  state: string;
  data: T | null;
  gaps: Gap[] | null;
}
export interface Coverage {
  scope_count: NullableCount;
  observed_count: NullableCount;
  assessed_count: NullableCount;
  unassessed_count: NullableCount;
  gaps?: Gap[] | null;
}
export interface RunContext {
  market: "HK_CONNECT";
  target_date: string;
  phase: Phase;
  cutoff: string | null;
  trigger?: "SCHEDULED" | "MANUAL";
  source_sessions?: Record<string, string | null>;
  rules_version?: string;
  scope_refs?: unknown;
}
export interface EvidenceRef {
  evidence_id: string;
  owner: string;
  role?: string | null;
  source_date?: string | null;
  session?: string | null;
  observed_at?: string | null;
  captured_at?: string | null;
  available_at?: string | null;
  sha256?: string | null;
  artifact_ref?: string | null;
  manifest_ref?: string | null;
  receipt_ref?: string | null;
  original_url?: string | null;
  verification?: EvidenceStatus | null;
  gaps?: Gap[] | null;
}
export interface LaneDecision {
  decision?: Decision | null;
  status?: string | null;
  reason?: string | null;
  facts?: Record<string, unknown> | null;
  original_text?: string | null;
  available_at?: string | null;
  evidence_ids?: string[];
  [key: string]: unknown;
}
export interface StockDecision {
  market: "HK_CONNECT";
  symbol: string;
  name: string;
  decision: Decision;
  lane_decisions: Partial<Record<Lane, LaneDecision | null>>;
  reasons: string[];
  conditions: string[];
  invalidation_conditions: string[];
  risks: string[];
  evidence_ids: string[];
  connect_eligibility?: string | null;
  eligibility_status?: string | null;
  available_at?: string | null;
  changed?: string | null;
  [key: string]: unknown;
}
export interface LaneResult {
  lane: Lane;
  state: LaneState;
  rows?: unknown[] | null;
  coverage?: Coverage | null;
  input_sha256?: string | null;
  rules_version?: string | null;
  run_id?: string | null;
  evidence_refs?: EvidenceRef[];
  gaps?: Gap[] | null;
}
export interface DecisionCounts {
  selected: NullableCount;
  watch: NullableCount;
  unassessed: NullableCount;
  observation_only: NullableCount;
  not_selected: NullableCount;
  [key: string]: number | null;
}
export interface PlanMetadata extends SafetyFlags {
  schema_version?: typeof SCHEMA_VERSION;
  context: RunContext;
  run_id: string;
  input_sha256?: string | null;
  product_sha256?: string | null;
  generated_at?: string | null;
  available_at?: string | null;
  lanes?: LaneResult[];
  changes?: unknown[] | null;
  gaps?: Gap[] | null;
}
export interface PlanVersion {
  run_id: string;
  phase: Phase;
  target_date?: string;
  generated_at?: string | null;
  available_at?: string | null;
  cutoff?: string | null;
  origin?: "NEW" | "LEGACY";
  [key: string]: unknown;
}
export interface DayData {
  snapshot: PlanMetadata;
  stocks: StockDecision[];
  counts: DecisionCounts;
  pagination: { total: number; offset: number; limit: number };
  versions?: PlanVersion[];
  gaps?: Gap[] | null;
}
export interface StockDetails {
  stock: StockDecision;
  evidence_refs?: EvidenceRef[];
  gaps?: Gap[] | null;
}
export interface HistoryEntry {
  origin: "NEW" | "LEGACY";
  target_date: string;
  phase?: Phase | null;
  run_id?: string | null;
  original_run_id?: string | null;
  original_schema?: string | null;
  original_sha256?: string | null;
  recorded_at?: string | null;
  generated_at?: string | null;
  verification?: EvidenceStatus | null;
  gaps?: Gap[] | null;
}
export interface HistoryData {
  entries: HistoryEntry[];
  gaps?: Gap[] | null;
}
export interface JobRecord {
  job_id: string;
  run_id: string;
  context: RunContext;
  state: JobState;
  step?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  last_progress_at?: string | null;
  completed_count: NullableCount;
  total_count: NullableCount;
  failed_steps?: string[];
  failure_code?: string | null;
  retryable: boolean;
  execution_refs?: unknown[];
}
export interface JobCreated {
  job_id: string;
  run_id: string;
  status_url: string;
}
export interface ReviewRow {
  rank: number;
  symbol: string;
  name?: string | null;
  actual_change?: number | null;
  strict_hit?: boolean | null;
  extended_hit?: boolean | null;
  matched_lanes?: Lane[];
  missed_reason?: string | null;
  [key: string]: unknown;
}
export interface ReviewMetric {
  numerator?: number | null;
  denominator?: number | null;
  rate?: number | null;
  display?: string | null;
}
export interface ReviewSummary {
  target_date: string;
  plan_run_id: string;
  evaluation_scope_ref?: string | null;
  mode?: string | null;
  ranking_date?: string | null;
  top20: ReviewRow[] | null;
  strict_coverage?: ReviewMetric | null;
  extended_coverage?: ReviewMetric | null;
  selection_denominator?: number | null;
  lane_incremental?: Record<string, unknown> | null;
  missed_reasons?: Record<string, unknown> | null;
  gaps?: Gap[] | null;
}
export const DECISION_LABELS: Record<Decision, string> = {
  SELECTED: "严格入选", CONDITIONAL_WATCH: "条件观察", UNASSESSED: "待评估",
  NOT_SELECTED: "未入选", OBSERVATION_ONLY: "仅观察"
};
export const LANE_LABELS: Record<Lane, string> = {
  ANNOUNCEMENT: "公告", US_MAPPING: "美股映射", OVERSOLD: "超跌",
  STAGE_REFERENCE: "阶段参考", CLOSE_REFERENCE: "尾盘参考"
};
export const LANE_STATE_LABELS: Record<LaneState, string> = {
  NOT_RUN: "未运行", RUNNING: "运行中", READY: "完成", READY_EMPTY: "有效空集",
  PARTIAL: "部分完成", INPUT_MISSING: "输入缺失", FAILED: "失败", NOT_APPLICABLE: "不适用"
};
export const JOB_STATE_LABELS: Record<JobState, string> = {
  QUEUED: "排队中", RUNNING: "运行中", SUCCEEDED: "已完成", PARTIAL: "部分完成",
  FAILED: "失败", CANCELLED: "已取消", INTERRUPTED: "已中断"
};
export const PHASE_LABELS: Record<Phase, string> = {
  PREOPEN: "09:25 盘前", INTRADAY: "盘中阶段", NEXT_DAY: "16:30 次日草案",
  RETROSPECTIVE: "事后回看", MANUAL: "手动研究"
};
export function showCount(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "未知";
}
export function showText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "未知";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  const serialized = JSON.stringify(value);
  return typeof serialized === "string" ? serialized : "未知";
}
export function gapText(value: Gap): string {
  return typeof value === "string" ? value : (value.message || value.code || "未说明的缺口");
}
export function isReferenceLane(lane: Lane): boolean {
  return lane === "STAGE_REFERENCE" || lane === "CLOSE_REFERENCE";
}
