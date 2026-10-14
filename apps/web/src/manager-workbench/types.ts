/** C consumes MWB_V1_20261013; B owns the authoritative JSON samples/schema. */
export const SCHEMA_VERSION = "v4.manager_workbench.v1" as const;
export const LANES = ["ANNOUNCEMENT", "US_MAPPING", "OVERSOLD", "STAGE_REFERENCE", "CLOSE_REFERENCE"] as const;
export type Lane = (typeof LANES)[number];
export type RecommendationLane = 'US_MAPPING' | 'OVERSOLD';
export type Phase = "PREOPEN" | "INTRADAY" | "NEXT_DAY" | "RETROSPECTIVE" | "MANUAL";
export type Decision = "SELECTED" | "CONDITIONAL_WATCH" | "UNASSESSED" | "NOT_SELECTED" | "OBSERVATION_ONLY";
export type LaneState = "NOT_RUN" | "RUNNING" | "READY" | "READY_EMPTY" | "PARTIAL" | "INPUT_MISSING" | "FAILED" | "NOT_APPLICABLE";
export type JobState = "QUEUED" | "RUNNING" | "SUCCEEDED" | "PARTIAL" | "FAILED" | "CANCELLED" | "INTERRUPTED";
export type EvidenceStatus = "VERIFIED" | "CANNOT_CONFIRM" | "INVALID";

export type Gap = string | { code?: string; message?: string; owner?: string; [key: string]: unknown };
export type NullableCount = number | null;
export interface SafetyFlags {
  RESEARCH_ONLY?: boolean;
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
  source_session?: string | null;
  observed_at?: string | null;
  captured_at?: string | null;
  available_at?: string | null;
  sha256?: string | null;
  artifact_ref?: string | null;
  manifest_ref?: string | null;
  receipt_ref?: string | null;
  source_url?: string | null;
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
  name: string | null;
  decision: Decision;
  lane_decisions: Partial<Record<Lane, LaneDecision[] | LaneDecision | null>>;
  reasons: string[];
  conditions: string[];
  invalidation_conditions: string[];
  risks: string[];
  evidence_ids: string[];
  membership_status?: string | null;
  available_at?: string | null;
  changed?: string | null;
  [key: string]: unknown;
}
export interface LaneResult {
  lane: Lane;
  rows_count?: number | null;
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
export interface USFactorSummary extends SafetyFlags {
  display_only: true;
  rules_version: string;
  target_date: string;
  phase: Phase;
  us_source_symbol_count: number | null;
  proxy_source_count: number | null;
  expected_proxy_source_count: number | null;
  verified_proxy_source_count: number | null;
  unknown_proxy_source_count: number | null;
  eligible_hk_scope_count: number | null;
  unique_factor_stock_count: number | null;
  factor_path_count: number | null;
  unknown_factor_stock_count: number | null;
  registry_fact_count: number | null;
  factor_decision_counts?: Record<string, number>;
  paired_review_available: boolean;
  paired_review_gap?: string | null;
  source_session?: string | null;
  historical_pit_verified: false;
  combined_source_and_stock_count: null;
  industry_summary?: HKIndustrySummary | null;
}
export interface HKIndustrySummary {
  display_only: true;
  mapping_version: string;
  source_status: string;
  source_gap?: string | null;
  target_date: string;
  scope_count: NullableCount;
  classified_count: NullableCount;
  mapping_covered_count: NullableCount;
  industry_unmapped_count: NullableCount;
  classification_missing_count: NullableCount;
  triggered_unique_stock_count: NullableCount;
  candidate_row_count: NullableCount;
  decision_counts: Record<string, NullableCount>;
  unknown_unique_stock_count: NullableCount;
  identity_resolved_count: NullableCount;
  identity_gap_count: NullableCount;
  identity_gap_symbols?: string[];
  identity_gap?: string | null;
  security_master_scope_count: NullableCount;
  security_master_owner?: string | null;
  security_master_source_date?: string | null;
  security_master_available_at?: string | null;
  security_master_artifact_sha256?: string | null;
  security_master_manifest_sha256?: string | null;
  bad_row_count: NullableCount;
  source_asof?: string | null;
  source_asof_status?: string | null;
  captured_at?: string | null;
  temporal_status?: string | null;
  historical_pit_verified: false;
  membership_codes_sha256?: string | null;
  membership_artifact_sha256?: string | null;
  source_artifact_sha256?: string | null;
  source_response_count?: NullableCount;
  out_of_scope_row_count?: NullableCount;
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
  changes?: Record<string, unknown> | null;
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
  recommendation_counts?: Partial<Record<RecommendationLane, DecisionCounts | null>>;
  recommendation_projection?: {
    display_only: true; lane: RecommendationLane;
    row_count: number; hk_relation_row_count: number; distinct_hk_count: number;
    source_only_row_count: number; coverage: Coverage; count_unit?: 'SAVED_LANE_RESEARCH_ROWS';
    factor_stock_count?: number | null; factor_path_count?: number | null;
    industry_candidate_row_count?: number | null; industry_candidate_stock_count?: number | null;
    industry_scope_count?: number | null;
  };
  snapshot: PlanMetadata | null;
  stocks: StockDecision[];
  counts: DecisionCounts | null;
  pagination: { total: number; offset: number; limit: number };
  versions?: PlanVersion[];
  gaps?: Gap[] | null;
  us_mapping_summary?: {
    display_only: true; plan_run_id: string; source_symbol_count: number; source_row_count: number;
    relation_row_count: number; mapped_hk_count: number; source_decision_counts: Record<string, number>;
    mixed_source_count: number; coverage: Coverage; groups: { us_symbol: string; decisions: string[]; rows: Record<string, unknown>[] }[];
    factor_summary?: USFactorSummary | null;
  } | null;
}
export interface StockLaneDetail {
  lane: Lane;
  rows: Record<string, unknown>[];
  evidence_refs: EvidenceRef[];
}
export interface StockDetails {
  recommendation_lane?: RecommendationLane | null;
  plan_run_id: string;
  stock: StockDecision;
  lane_details: StockLaneDetail[];
}
export interface HistoryEntry {
  origin: "NEW" | "LEGACY";
  target_date?: string;
  phase?: Phase | null;
  run_id?: string | null;
  state?: string | null;
  product_sha256?: string | null;
  input_sha256?: string | null;
  original_run_id?: string | null;
  original_schema?: string | null;
  original_sha256?: string | null;
  recorded_at?: string | null;
  generated_at?: string | null;
  verification?: EvidenceStatus | null;
  gaps?: Gap[] | null;
}
export interface HistoryData {
  date: string;
  versions: HistoryEntry[];
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
  stock_decision?: Decision | "NOT_IN_PLAN" | null;
  strict_hit?: boolean | null;
  extended_hit?: boolean | null;
  matched_lanes?: Lane[];
  missed_reason?: string | null;
  [key: string]: unknown;
}
export interface ReviewMetric {
  covered?: number | null;
  denominator?: number | null;
  ratio?: number | null;
}
export interface ReviewSummary {
  target_date: string;
  plan_run_id: string;
  evaluation_scope_ref?: string | null;
  mode?: string | null;
  ranking_date?: string | null;
  top20_rows: ReviewRow[] | null;
  strict_coverage?: ReviewMetric | null;
  extended_coverage?: ReviewMetric | null;
  selected_denominator?: number | null;
  lane_incremental_coverage?: Record<string, unknown> | null;
  uncovered_reasons?: string[] | null;
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
