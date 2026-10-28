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
