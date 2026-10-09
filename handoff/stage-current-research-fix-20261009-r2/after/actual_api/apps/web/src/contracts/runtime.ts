export type LogicalWorkloadStatus = {
  workload_id: string;
  enabled?: boolean;
  status: string;
  last_run?: string | null;
  next_due?: string | null;
  duration_ms?: number | null;
  result_code?: string | null;
  freshness?: string | null;
  receipt_path?: string | null;
  receipt_freshness?: string | null;
  capture_status?: string | null;
  capture_performed?: boolean | null;
  collector_invoked?: boolean | null;
  capture_artifact_verified?: boolean | null;
  new_capture_verified?: boolean | null;
  data_update_status?: string | null;
  business_data_date?: string | null;
  business_evidence_status?: string | null;
  business_message?: string | null;
  business_run_id?: string | null;
  breakpoint?: string | null;
};

export type RuntimeIdentityRow = {
  owner_id?: string;
  alias?: string;
  workload_id?: string;
  replacement_workload_id?: string;
  status: string;
};

export type TaskRegistrationStatus = {
  graph_task_spec_id: string;
  legacy_task_id: string;
  timeline_node_ids: string[];
  legacy_launcher_paths: string[];
  actual_windows_task_ids: string[];
  enabled: false;
  execution_allowed: false;
  status: "CANNOT_CONFIRM";
  disposition: "USER_APPROVED_DISABLED_CANNOT_CONFIRM";
};

export type TaskStatusResponse = {
  scheduler_observation?: { status: string; receipt_count: number; process_status: string; logical_row_evidence: string;
    message: string; last_receipt_status?: string; last_finished_at?: string; receipt_namespace?: string };
  business_date?: string;
  logical_workload_count: number;
  active_owner_count: number;
  alias_count: number;
  retired_owner_count: number;
  task_registration_count: number;
  groups: {
    logical: LogicalWorkloadStatus[];
    active_owners: RuntimeIdentityRow[];
    aliases: RuntimeIdentityRow[];
    retired: RuntimeIdentityRow[];
    registrations: TaskRegistrationStatus[];
  };
  cannot_confirm: string[];
  production_allowed: boolean;
  buy_gate_updated: boolean;
  orders_sent: boolean;
};


export type HkCurrentDayResearchMetadata = {
  input_mode: "CURRENT_DAY_RESEARCH_ONLY"; trade_date: string; stage_id: string;
  universe_as_of: string; captured_at: string; cutoff_at: string; stale_universe: boolean;
  current_connect_eligibility: "CANNOT_CONFIRM"; RESEARCH_ONLY: true;
  production_allowed: false; buy_gate_updated: false; orders_sent: false;
  input_binding_sha256: string;
  source_files: Record<string, { file: string; sha256: string }>;
};

export type StageExecutionEvidenceReadback = {
  status: string; execution_verified: boolean; natural_verified: boolean;
  trade_date: string; stage_id: string; receipt_path?: string; observed_sha256?: string;
  attempt_mode?: string | null; due_status?: string | null; declared_status?: string | null;
  recorded_at?: string | null; first_failed_layer?: string | null; error?: string | null;
  node_attempt_count?: number | null; node_outcome?: string | null; retry_after?: string | null;
  candidate_run_id?: string | null; candidate_current_sha256?: string | null; candidate_binding?: string;
  cannot_confirm: string[]; historical_bad_row_status?: string;
  selection_results?: Record<string, {
    status: string; selected_rows: number | null; requested_rows: number | null;
    source_rows: number | null; missing_quote_rows?: number | null;
    quote_coverage_ratio?: number | null; selection_status?: string | null;
    evidence_scope?: string;
    trade_date?: string | null; stage_id?: string | null; market?: string;
    run_id?: string | null; artifact_id?: string | null;
    algorithm_sha256?: string | null; raw_artifact_sha256?: string | null;
    selection_mode?: string; research_source_status?: string;
    hk_current_day_research?: HkCurrentDayResearchMetadata | null;
    research_source_restrictions?: string[]; quote_data_times?: string[];
    source_restrictions?: string[];
    runtime_source_identity?: Record<string, unknown> | null;
  }>;
  receipt_history_binding?: string; record_time_status?: string;
  selection_artifact_bindings?: Record<string, { status: string }>;
  input_binding_status?: Record<string, { status: string; input_binding_sha256?: string }>;
  runtime_source_binding?: { status: string; sha256?: string; scope?: string };
  selection_source_bindings?: Record<string, { status: string; sha256?: string;
    invocation_sha256?: string; invocation_matches_selection?: boolean | null }>;
  runner_invoked_at?: string | null; invocation_time_source?: string | null;
  markets: Record<string, {
    status?: string | null; selection_binding: string; failure_layer?: string | null;
    requested_rows: number | null; source_rows: number | null; observed_rows: number | null;
    accepted_rows: number | null; selected_rows: number | null; reasons: string[];
    diagnostics?: Record<string, unknown>; declared_identity?: Record<string, unknown>;
  }>;
};
