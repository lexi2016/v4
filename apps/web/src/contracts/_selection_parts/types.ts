// Extracted source declarations; review candidate, not production acceptance.
/**
 * The read-only exact-date selection ledger served by V3.5.
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
export type SelectionRecord = Record<string, unknown>;