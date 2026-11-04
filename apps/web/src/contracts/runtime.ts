export type ClosingTimelineNode = { node_id: string; label: string; owner_id: string };
export type TaskTimelineNode = ClosingTimelineNode & {
  position: number;
  business_date: string;
  planned_time?: string;
  status: string;
  task_state?: string;
  reason?: string;
  run_id?: string | null;
  binding_status?: string;
  business_run_id?: string | null;
  actual_receipt_path?: string | null;
};

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
  timeline_nodes?: TaskTimelineNode[];
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


export type StageResearchSource = {
  schema_version: "HK_CURRENT_DAY_RESEARCH_V1"; mode: "CURRENT_DAY_RESEARCH_ONLY";
  market: "HK_CONNECT"; trade_date: string; universe_as_of: string; captured_at: string;
  stale_universe: boolean; hk_connect_membership_status: "CANNOT_CONFIRM";
  formal_d1_eligible: false; source_sha256: string;
  security_master_sha256?: string; reference_codes_sha256?: string;
  receipt_sha256?: string; final_receipt_sha256?: string;
};

export type StageExecutionEvidenceReadback = {
  status: string; execution_verified: boolean; natural_verified: boolean;
  trade_date: string; stage_id: string; receipt_path?: string; observed_sha256?: string;
  attempt_mode?: string | null; due_status?: string | null; declared_status?: string | null;
  declared_attempt_mode?: string | null; execution_origin?: string | null;
  attempt_mode_status?: string; same_day_late_observation_recovery?: boolean;
  runtime_source_identity?: Record<string, unknown> | null; runtime_source_identity_scope?: string;
  recorded_at?: string | null; first_failed_layer?: string | null; error?: string | null;
  node_attempt_count?: number | null; node_outcome?: string | null; retry_after?: string | null;
  candidate_run_id?: string | null; candidate_current_sha256?: string | null; candidate_binding?: string;
  cannot_confirm: string[]; historical_bad_row_status?: string;
  selection_results?: Record<string, {
    status: string; selected_rows: number | null; requested_rows: number | null;
    source_rows: number | null; missing_quote_rows?: number | null;
    quote_coverage_ratio?: number | null; selection_status?: string | null;
    selection_mode?: string | null;
    trade_date?: string; stage_id?: string; market?: string;
    run_id?: string | null; artifact_id?: string | null;
    algorithm_sha256?: string | null; raw_artifact_sha256?: string | null;
    source_evidence?: string[]; research_source?: StageResearchSource | null;
    research_source_status?: string;
    evidence_scope?: string;
  }>;
  receipt_history_binding?: string; record_time_status?: string;
  selection_artifact_bindings?: Record<string, { status: string }>;
  runner_invoked_at?: string | null; invocation_time_source?: string | null;
  RESEARCH_ONLY?: boolean; production_allowed?: boolean; buy_gate_updated?: boolean; orders_sent?: boolean;
  markets: Record<string, {
    status?: string | null; selection_binding: string; failure_layer?: string | null;
    requested_rows: number | null; source_rows: number | null; observed_rows: number | null;
    accepted_rows: number | null; selected_rows: number | null; reasons: string[];
    diagnostics?: Record<string, unknown>; declared_identity?: Record<string, unknown>;
  }>;
};
