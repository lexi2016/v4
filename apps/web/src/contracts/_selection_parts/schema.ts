// Extracted source declarations; review candidate, not production acceptance.


/**
 * Wire constants mirrored from the producer-owned V3.5 selection contract.
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

export const SELECTION_SCHEMA_VERSION = "v3_5.selection_research_product.v1";
export const SELECTION_WORKFLOW_NAME = "V35_SELECTION_RESEARCH_PRODUCT";
export const SELECTION_PASS_SIGNAL = "V35_SELECTION_RESEARCH_VERTICAL_SLICE_VERIFIED";
export const SELECTION_TIMEZONE = "Asia/Shanghai";
export const RESEARCH_SUPPLY_TYPE = "RESEARCH_SUPPLY_FROZEN_ENVELOPE";
export const RESEARCH_SUPPLY_ACCEPTANCE = "RESEARCH_SUPPLY_ONLY";
export const EARLY_DRAFT_TYPE = "EARLY_DRAFT_FROZEN_ENVELOPE";
export const SHA256_PATTERN = /^[0-9a-f]{64}$/i;
export const RUN_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/;
export const PHASE_SET = new Set<string>(SELECTION_PHASES);
export const PRODUCT_STATUS_SET = new Set<string>(SELECTION_PRODUCT_STATUSES);
export const SNAPSHOT_STATUS_SET = new Set<string>(SELECTION_SNAPSHOT_STATUSES);
export const ORIGIN_SET = new Set<string>(SELECTION_ORIGINS);

export const PRODUCT_REQUIRED_FIELDS = new Set([
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
export const PRODUCT_OPTIONAL_FIELDS = new Set([
  "manager_decision_ref",
  "artifact_sha256",
  "manifest_sha256",
  "receipt_sha256",
  "current_sha256",
]);
export const CANDIDATE_FIELDS = new Set([
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
export const CANDIDATE_OPTIONAL_FIELDS = new Set(["manager_decision"]);
export const MANAGER_DECISION_PROJECTION_FIELDS = new Set([
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
export const MANAGER_DECISION_PROJECTION_ROLES = new Set(["CORE", "CONDITIONAL"]);
export const SNAPSHOT_FIELDS = new Set([
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
export const FORMAL_AUTHORITY_FIELDS = new Set([
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
export const COUNTS_FIELDS = new Set([
  "research_candidates",
  "formal_shortlist",
  "snapshots",
  "intraday_observations",
  "outcomes",
]);
export const LINEAGE_FIELDS = new Set([
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
export const SUPPLY_SOURCE_FIELDS = new Set([
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
export const EARLY_SOURCE_REQUIRED_FIELDS = new Set([
  "type",
  "path",
  "raw_sha256",
  "frozen_payload_sha256",
  "json_pointer",
  "source_date",
  "source_time",
]);