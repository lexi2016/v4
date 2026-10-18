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
export interface USMappingRunContract {
  schema_version?: string;
  state?: string;
  mode?: Phase;
  target_hk_date?: string;
  us_source_session?: string | null;
  cutoff?: string;
  contract_sha256?: string;
  gaps?: string[];
  universe?: { version?: string; symbol_count?: number | null; contract_sha256?: string | null; symbols_sha256?: string | null };
  owners?: {
    quote?: { owner?: string | null; artifact_sha256?: string | null; receipt_sha256?: string | null;
      manifest_sha256?: string | null; available_at?: string | null };
    connect?: { source_owner?: string | null; source_date?: string | null; source_sha256?: string | null;
      source_available_at?: string | null; observed_symbol_count?: number | null; target_eligibility?: string | null;
      target_gap?: string | null };
  };
}
export interface HKDirectionalProxyPath {
  theme?: string | null;
  proxy_symbols?: string[];
  status?: string;
  direction?: "UPSIDE" | "DOWNSIDE" | "FLAT" | "UNASSESSED" | string;
  return_pct?: string | null;
  source_session?: string | null;
  reason?: string | null;
  conditions?: string[];
  [key: string]: unknown;
}
export interface HKDirectionalProxyStock {
  symbol: string;
  name?: string | null;
  source_industry?: string | null;
  source_session?: string | null;
  direction_state?: string;
  reason?: string | null;
  conditions?: string[];
  proxy_paths?: HKDirectionalProxyPath[];
  [key: string]: unknown;
}
export interface HKDirectionalProxyLists {
  display_only: true;
  source_session?: string | null;
  monthly_observed_scope_count?: number | null;
  monthly_research_source_date?: string | null;
  formal_target_eligibility?: string;
  historical_pit_verified: false;
  mixed_stock_count?: number | null;
  upside_stock_count?: number | null;
  downside_stock_count?: number | null;
  flat_stock_count?: number | null;
  unassessed_stock_count?: number | null;
  lists: {
    upside: HKDirectionalProxyStock[];
    downside: HKDirectionalProxyStock[];
    flat: HKDirectionalProxyStock[];
    unassessed: HKDirectionalProxyStock[];
  };
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
    catalog_summary?: { state?: string | null; stock_count?: number | null; relation_count?: number | null;
      consumed_relation_count?: number | null; displayed_relation_count?: number | null };
    run_contract?: USMappingRunContract | null;
    directional_proxy_lists?: HKDirectionalProxyLists | null;
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
export interface AnnouncementSourceOrigin {
  role: string;
  source_ref: string;
  source_product_sha256: string;
  row_fingerprint_sha256: string;
}
export interface AnnouncementArticle {
  article_id: string;
  title: string;
  publication_date?: string | null;
  symbol: string;
  name: string;
  disposition?: string | null;
  direction?: string | null;
  selection_basis?: string | null;
  reason: string;
  impact: string[];
  body_sha256: string;
  source_sha256: string;
  source_origins: AnnouncementSourceOrigin[];
  review_status: string;
  reuse_status?: string | null;
  membership_status?: "IN" | "OUT" | "UNKNOWN";
  membership_reason?: string;
}
export interface AnnouncementStock {
  symbol: string;
  name: string;
  reasons: string[];
  articles: AnnouncementArticle[];
  review_status: string;
  reuse_status?: string | null;
  membership_status?: "IN" | "OUT" | "UNKNOWN";
  membership_reason?: string;
}
export interface AnnouncementMembershipGate {
  status: "VERIFIED" | "CANNOT_CONFIRM";
  target_date?: string;
  cutoff?: string;
  market?: "HK_CONNECT";
  owner?: string | null;
  authority_sha256?: string | null;
  authority_version?: string | null;
  effective_from?: string | null;
  effective_to?: string | null;
  available_at?: string | null;
  member_count?: number | null;
  failure_code?: string | null;
}
export interface AnnouncementFailure {
  article_id?: string | null;
  symbol?: string | null;
  title?: string | null;
  failure_code: string;
  attempt_count?: number | null;
  stage?: string | null;
  part_index?: number | null;
  part_count?: number | null;
}
export interface AnnouncementPending {
  article_id?: string | null;
  symbol?: string | null;
  title?: string | null;
  queue_status?: string | null;
  queue_reason?: string | null;
  context_admission?: unknown;
  execution_admission?: unknown;
  failure_code?: string | null;
  prompt_tokens?: number | null;
  context_limit_tokens?: number | null;
  part_index?: number | null;
  part_count?: number | null;
  repair_status?: string | null;
}
export interface AnnouncementCounts {
  source_catalogue_articles?: number | null;
  model_succeeded?: number | null;
  selected_model_articles?: number | null;
  model_candidate_stocks?: number | null;
  reused_reviewed_stocks?: number | null;
  failed?: number | null;
  pending?: number | null;
  body_gaps?: number | null;
  displayed_stocks?: number | null;
  capture_rows?: number | null;
  excluded_outside_window?: number | null;
  new_candidate_stocks?: number | null;
  membership_eligible_stocks?: number | null;
  membership_excluded_stocks?: number | null;
  membership_unknown_stocks?: number | null;
  membership_excluded_articles?: number | null;
  membership_unknown_articles?: number | null;
  membership_articles?: Record<string, number>;
  membership_stocks?: Record<string, number>;
  model_failed_articles?: number | null;
  model_pending_articles?: number | null;
  long_body_part_failed?: number | null;
  long_body_part_pending?: number | null;
  long_body_part_cannot_confirm?: number | null;
  long_body_synthesis_pending?: number | null;
  current_batch_candidate_stocks?: number | null;
  context_pending?: number | null;
  queue_pending?: number | null;
  queue?: Record<string, number>;
}
export interface AnnouncementFlashResult extends SafetyFlags {
  schema?: string;
  job_id?: string;
  state: string;
  source_date?: string | null;
  target_trade_date?: string | null;
  updated_at?: string | null;
  candidate_id?: string | null;
  model_id?: string;
  profile?: string;
  citation_protocol?: string;
  review_status?: string;
  counts: AnnouncementCounts;
  stocks?: AnnouncementStock[];
  failures?: AnnouncementFailure[];
  pending?: AnnouncementPending[];
  gaps?: { code?: string; count?: number; detail?: string }[];
  membership_gate?: AnnouncementMembershipGate;
  membership?: AnnouncementMembershipGate;
  membership_exclusions?: Record<string, unknown>[];
  membership_excluded_stocks?: AnnouncementStock[];
  membership_unknown_stocks?: AnnouncementStock[];
  membership_excluded_articles?: Record<string, unknown>[];
  membership_unknown_articles?: Record<string, unknown>[];
  system_stop?: { failure_code?: string; attempt?: number; queue_action?: string } | null;
  provenance?: Record<string, unknown>;
}
export interface AnnouncementJobStatus {
  job_id: string;
  target_date: string;
  state: JobState;
  step?: string | null;
  completed_count?: NullableCount;
  total_count?: NullableCount;
  failure_code?: string | null;
  last_progress_at?: string | null;
  progress?: {
    queue_counts?: Record<string, number>;
    pending_body_gaps?: number;
    pending_context?: number;
    membership?: { status?: string; articles?: Record<string, number> };
    result_state?: string;
  } | null;
  result_state?: string;
  counts?: AnnouncementCounts;
}
export interface AnnouncementFlashData extends SafetyFlags {
  state: string;
  source_date: string;
  target_trade_date: string;
  updated_at?: string | null;
  candidate_id?: string | null;
  model_id?: string;
  profile?: string;
  citation_protocol?: string;
  review_status?: string;
  counts: AnnouncementCounts;
  stocks: AnnouncementStock[];
  failures: AnnouncementFailure[];
  pending: AnnouncementPending[];
  gaps: { code?: string; count?: number; detail?: string }[];
  system_stop?: { failure_code?: string; attempt?: number; queue_action?: string } | null;
  provenance?: Record<string, string>;
  membership?: AnnouncementMembershipGate;
  membership_excluded_stocks?: AnnouncementStock[];
  membership_unknown_stocks?: AnnouncementStock[];
  membership_excluded_articles?: Record<string, unknown>[];
  membership_unknown_articles?: Record<string, unknown>[];
  incremental?: AnnouncementFlashResult | null;
  incremental_runs?: { job_id: string; target_trade_date?: string | null; state: string;
    updated_at?: string | null; counts?: AnnouncementCounts }[];
  job?: AnnouncementJobStatus | null;
  resume?: AnnouncementFlashResumeEligibility;
  requested_target_date?: string | null;
}
export interface AnnouncementFlashResumeEligibility {
  schema: string;
  status: string;
  eligible: boolean;
  reason?: string | null;
  mode?: string | null;
  source_job_id?: string | null;
  target_date?: string | null;
  source_input_sha256?: string | null;
  source_progress_sha256?: string | null;
  source_queue_state_sha256?: string | null;
  capture_product_sha256?: string | null;
  source_result_sha256?: string | null;
  queue_status_counts?: Record<string, number>;
  target_date_queue_observed_counts?: Record<string, number>;
  orphan_count?: number;
  recoverable_orphan_count?: number;
  canary_passed?: boolean;
  resume_action?: "CANARY" | "CONTINUE" | null;
  canary_key?: string | null;
  canary_status?: string | null;
  canary_model_calls?: number | null;
  canary_validation?: Record<string, unknown> | null;
  max_model_calls?: number | null;
}
export interface AnnouncementFlashUpdateAccepted {
  job_id: string;
  target_date: string;
  requested_target_date: string;
  step?: string | null;
  status_url: string;
}
export interface AnnouncementFlashResumeAccepted {
  job_id: string;
  source_job_id: string;
  resume_action: "CANARY" | "CONTINUE";
  target_date: string;
  step?: string | null;
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
export interface USMappingReviewRevision {
  source_review_status: "SOURCE_REVIEWED";
  independent_verification: "NOT_RUN";
  research_use: string;
  revision: Record<string, unknown>;
  evidence?: Record<string, string>[];
  revision_json_parse_issues?: {
    field: string;
    issue: string;
    error_type: string;
    raw_sha256: string;
    raw_characters: number;
  }[];
  source_summary?: Record<string, unknown>;
}
export interface USMappingRecoveryRelation {
  detail_level: "SUMMARY" | "FULL";
  relation_id: string;
  closure_status: "CLOSED_RESEARCH_SCOPE" | "CLOSED_EXCLUDED_SCOPE" | "OPEN";
  primary_research_use: string;
  primary_use_reason: string;
  verified_fact_scope: unknown;
  applicable_period: string;
  closure_scope: string;
  closure_basis: string;
  remaining_gaps: unknown;
  next_key_evidence: unknown;
  research_access_date_and_version: string;
  effective_research_file: string;
  effective_research_sha256: string;
  evidence_ids: string[];
  delivery_acceptance: string;
  prediction: "UNTESTED";
  historical_PIT: "NOT_VALIDATED";
  event_and_data_tests: "NOT_RUN";
  company_independent_acceptance: 0;
  full_record?: Record<string, unknown>;
}
export interface USMappingRecoveryProgress {
  source_package_sha256: string;
  source_manifest_sha256: string;
  overlay_integrity_sha256: string;
  counts: {
    snapshot_stocks: 667;
    original_relations: 1003;
    processed_relations: 1003;
    closure_status_counts: {
      CLOSED_RESEARCH_SCOPE: 757;
      CLOSED_EXCLUDED_SCOPE: 25;
      OPEN: 221;
    };
    research_scope_closed: 757;
    excluded_scope_closed: 25;
    closed_total_including_exclusions: 782;
    open_relations: 221;
    stocks_with_relations: 649;
    stocks_without_relations: 18;
    company_independent_acceptance: 0;
  };
  research_safety: Record<string, boolean | number | string>;
  evidence_limits: Record<string, boolean | number | string>;
  prior_700_history: {
    sha256: string;
    record_count: 700;
    source_package_sha256: string;
    retained_as_separate_history: true;
    status_crosswalk: "NOT_ESTABLISHED";
  };
  version_precedence: Record<string, unknown>;
  projection_rule: string;
}
export interface USMappingCatalogRelation {
  review_detail_level: "SUMMARY" | "FULL";
  relation_id: string;
  source_review_status: "SOURCE_REVIEWED" | "NOT_PROCESSED";
  independent_verification: "NOT_RUN";
  research_use: string;
  review_revision: USMappingReviewRevision | null;
  recovery_v2r1: USMappingRecoveryRelation | null;
  source_row: number;
  hk_code: string;
  us_symbol: string;
  source_record: Record<string, string>;
  fact_review_status: "PENDING";
  prediction_eligible: false;
  prediction_validation: "UNTESTED";
  historical_PIT: "NOT_VALIDATED";
}
export interface USMappingCatalogStock {
  ordinal: number;
  hk_code: string;
  name: string | null;
  english_name: string | null;
  source_record: Record<string, string>;
  relation_count: number;
  source_reviewed_relation_count: number;
  unprocessed_relation_count: number;
  relations: USMappingCatalogRelation[];
}
export interface USMappingCatalogData {
  catalog_id: string;
  catalog_state: "STRUCTURE_VALID_ONLY";
  catalog_integrity_sha256: string;
  research_use: string;
  review_progress: {
    source_reviewed_relations: number; unprocessed_relations: number; source_reviewed_stocks: number;
    all_original_relations_processed_stocks: number; independently_verified_relations: number;
    independent_verification: "NOT_RUN"; research_use_counts: Record<string, number>;
  };
  review_source: { source_package_sha256: string; source_generated_at_utc: string; integrity_sha256: string } | null;
  recovery_v2r1: USMappingRecoveryProgress;
  source: Record<string, unknown> & {
    package_name: string;
    package_sha256: string;
    membership_snapshot: string;
    membership_sha256: string;
  };
  coverage: Record<string, unknown> & {
    membership_count: number;
    relation_row_count: number;
    stocks_with_relations: number;
  };
  source_claims: Record<string, unknown>;
  safety: Required<SafetyFlags> & {
    prediction_validation: "UNTESTED";
    historical_PIT: "NOT_VALIDATED";
  };
  query: string;
  total: number;
  offset: number;
  limit: number;
  items: USMappingCatalogStock[];
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
