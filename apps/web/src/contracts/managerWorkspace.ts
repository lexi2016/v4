/**
 * Workspace response contracts.
 *
 * Types only; the runtime validators stay in api/managerWorkspace.
 */

import type { DailyChannels, WorkspaceDateBindings } from "../manager-selection/dailyChannels";


export type JsonObject = Record<string, unknown>;


export interface WorkspaceLane extends JsonObject {
  lane: 'STAGE' | 'CATALYST' | 'CLOSE'; owner: string; state: string; target_date: string;
  stock_count: number | null; last_attempt_at: string | null; last_success_at: string | null;
  run_id: string | null; execution_kind: string; failure_reasons: string[];
  next_plan: JsonObject | null; schedule_status: string; input_coverage: JsonObject;
}


export interface WorkspaceAction extends JsonObject {
  action_id: string; type: string; text: string; evidence_ids: string[];
  proposition_ids: string[]; supporting_quotes: JsonObject[]; assertion_type: string;
}


export interface WorkspaceStock extends JsonObject {
  is_focus: boolean; priority_basis: JsonObject;
  stock_key: string; market: 'HK'; symbol: string; name: string; target_date: string;
  lanes: string[]; themes: string[]; why_watch: string[]; attention_priority: string;
  event_group_count: number; new_catalyst_count: number; evidence: JsonObject[]; material_relations: JsonObject[];
  stage_observation: JsonObject | null; close_observation: JsonObject | null;
  change: {status: string; previous_date: string | null; reasons: string[]};
  plan: {next_observation: string[]; invalidation_conditions: string[]; missing: string[];
         trigger_price: number | null; invalidation_price: number | null;
         price_provenance?: JsonObject | null; key_risks?: string[]; wait_conditions?: string[];
         evidence_ids?: string[]; criteria?: JsonObject; actions: WorkspaceAction[]};
}


export interface ReboundScreen extends JsonObject {
  schema_version: 'v4.manager_research.rebound_v3_screen.v1'; rule_version: string;
  target_trade_date: string; verified_session: string; status: 'READY' | 'READY_WITH_GAPS' | 'CANNOT_CONFIRM';
  cards: JsonObject[]; strict: JsonObject[]; near: JsonObject[]; pending: JsonObject[];
  excluded?: JsonObject[]; screen_unresolved?: JsonObject[]; decision_identity?: string;
  gaps: string[]; coverage: JsonObject; input_identity: string | null; authority: JsonObject | null;
  main_screen_ready: boolean; longlist_target?: number;
}


export interface UsMarketAttention extends JsonObject {
  schema_version: 'v4.manager_research.us_market_bridge.v1'; target_trade_date: string;
  research_cutoff: string; status: string; expected_us_session: string | null;
  coverage_scope: string; selection_semantics?: string; selection_threshold_pct?: number; raw_industry_up: JsonObject[]; raw_individual_up: JsonObject[];
  coverage: JsonObject; source_identity: JsonObject | null; gaps: string[];
  research_material_input?: UsRelationMaterialInput; mapping_diagnostics?: UsMappingDiagnostics;
  symbol_assessments?: UsSymbolAssessment[]; relation_evidence?: JsonObject;
}


export interface UsSymbolRelation extends JsonObject {
  hk_symbol: string; hk_code: string; hk_name: string; us_symbol: string;
  relationship_type: string; direction: string; evidence_timing: string;
  target_date_eligibility: 'CANNOT_CONFIRM'; sources: JsonObject[];
  relation_source?: string; available_at?: string; source_captured_available_at?: string;
  reviewed_at?: string; reviewer_identity?: string; review_receipt_sha256?: string;
  http_body_rehash_status?: string; provenance?: JsonObject; evidence_provenance?: JsonObject[];
}


export interface UsSymbolAssessment extends ResearchReadOnlyFlags {
  symbol: string; instrument_classification: string; quote_status: string; direction: string;
  quote_evidence: JsonObject | null; relation_assessment_status: string;
  relation_count: number | null; relations: UsSymbolRelation[]; relation_gaps: string[];
  relation_assessment_evidence?: JsonObject;
  target_date_eligibility: 'CANNOT_CONFIRM';
}


export interface UsMappingSource extends JsonObject {
  title: string; url: string; published_at?: string;
}


export interface UsMappingCard extends JsonObject {
  hk_symbol: string; hk_code: string; hk_name: string; research_priority: 'PRIORITY' | 'WATCH'; us_symbols: string[]; daily_match_symbols: string[];
  us_moves: JsonObject[]; theme_label?: string; relationship_type: string; reason: string;
  maturity: string; limitations: string[]; published_at: string; official_sources: UsMappingSource[];
}


export interface UsReviewedMapping extends JsonObject {
  target_trade_date: string; us_session_date: string; status: string; reviewed_at: string | null; artifact_sha256?: string;
  report?: JsonObject; source_scope?: JsonObject; cards: UsMappingCard[]; gaps?: string[];
}


export interface UsDailyMappingRun extends ResearchReadOnlyFlags {
  schema_version: 'v4.manager_research.us_mapping_daily_run.v1';
  target_trade_date: string; status: 'NOT_RUN' | 'FAILED' | 'INPUT_MISSING' | 'CANNOT_CONFIRM' | 'PARTIAL' | 'COMPLETED' | 'VALID_EMPTY';
  run_id: string | null; generated_at: string | null; us_session_date: string | null; research_cutoff: string | null;
  coverage: JsonObject; matches: JsonObject[]; gaps: string[]; source_identity: JsonObject | null;
  artifact_sha256?: string | null; input_identity?: string | null;
  symbol_assessments?: UsSymbolAssessment[]; relation_evidence?: JsonObject;
  relation_assessment_identity?: string | null; relation_source_identities?: JsonObject[];
  execution_context?: ResearchExecutionContext; run_readback?: ResearchRunReadback;
}


export type ResearchTriggerKind = 'SCHEDULED' | 'MANUAL' | 'UNKNOWN';


export type ResearchExecutionTiming = 'ON_TIME' | 'LATE_CATCHUP' | 'RETROSPECTIVE' | 'UNCLASSIFIED';


export interface ResearchExecutionContext extends JsonObject {
  trigger_kind: ResearchTriggerKind; timing: ResearchExecutionTiming;
  scheduled_for: string | null; started_at: string | null; finished_at: string | null;
  natural_run_verified: false;
}


export interface ResearchRunReadback extends JsonObject {
  status: 'VERIFIED' | 'CANNOT_CONFIRM'; target_trade_date: string | null;
  run_id: string | null; artifact_sha256: string | null; owner: string; read_at: string | null;
  input_identity?: string | null; owner_attempt_run_id?: string | null; owner_attempt_sha256?: string | null;
  owner_attempt_state?: string | null; owner_finished_at?: string | null;
}


export interface UsMappingResearch extends ResearchReadOnlyFlags {
  schema_version: 'v4.manager_research.us_mapping_research.v1'; target_trade_date: string;
  daily_run: UsDailyMappingRun; reviewed_research: UsReviewedMapping | null;
}


export type UsMappingAssessmentState = 'NOT_EVALUATED' | 'INSUFFICIENT' | 'ASSESSED_ZERO' | 'ASSESSED_WITH_RELATIONS';


export interface UsRelationMaterialInput extends JsonObject {
  status: 'READY' | 'PARTIAL' | 'CANNOT_CONFIRM'; complete: boolean;
  source_material_record_count: number; pre_connect_material_card_count: number;
  post_connect_material_card_count: number; research_relation_material_card_count: number;
  connect_rejection_count: number; input_identity: string; gaps: string[];
}


export interface UsMappingDiagnostics extends JsonObject {
  status: string; accepted_hk_mapping_count?: number | null;
  assessment_state?: UsMappingAssessmentState; assessment_reasons?: string[];
  material_input?: UsRelationMaterialInput;
}


export type ResearchAttentionState =
  | 'COMPANY_EVIDENCE_AND_MARKET_CONFIRMATION'
  | 'COMPANY_EVIDENCE_WAIT_MARKET'
  | 'MARKET_STRUCTURE_NEEDS_COMPANY_CAUSE'
  | 'CONTEXT_ONLY'
  | 'INSUFFICIENT';


export interface ResearchAttentionDecision extends JsonObject {
  schema_version: 'v4.manager_research.attention_decision.v1';
  version: '20260927.evidence-state-triage.proposal-v1';
  status: 'PROPOSAL_ONLY'; state: ResearchAttentionState; group_label: string; group_order: number;
  summary: string; next_check: string; invalidation: string; why_now_readable: string[];
  company_evidence_strength: number; market_confirmation_strength: number; context_strength: number;
  research_priority_key: [number, number, number, number, number, number];
  formal_rank_writeback: false; stage_writeback: false; buy_gate_writeback: false;
}


export interface ResearchAttentionCard extends JsonObject {
  symbol: string; name: string; research_attention_score: number; research_attention_band: string;
  qualified_lane_count: number; qualified_lanes: string[]; why_now: string[]; score_components?: JsonObject[]; missing: string[];
  screen_classification: string | null; original_screen_rank: number | null; evidence: JsonObject[];
  decision?: ResearchAttentionDecision; freshest_published_at?: string | null; freshest_acquired_at?: string | null;
}


export interface ResearchReadOnlyFlags extends JsonObject {
  RESEARCH_ONLY: true; production_allowed: false; buy_gate_updated: false; orders_sent: false;
}


export interface FormalConnectSelection extends ResearchReadOnlyFlags {
  status: 'NOT_APPLICABLE' | 'CANNOT_CONFIRM' | 'READY' | 'READY_EMPTY'; reason: string;
  target_trade_date: string; candidate_count: number | null; membership_status: string;
  calendar: JsonObject; qualified: false; buy_allowed: false;
}


export interface SelectionDiagnostics extends ResearchReadOnlyFlags {
  schema_version: 'v4.manager_research.selection_diagnostics.v1'; target_trade_date: string;
  formal_selection?: FormalConnectSelection; membership: JsonObject; gaps: string[];
}


export type ResearchSelectionDecisionStatus = 'SELECTED' | 'NEAR_WATCH' | 'EXCLUDED' | 'UNRESOLVED';


export interface ResearchSelectionDecision extends JsonObject {
  symbol: string | null; name: string; decision_status: ResearchSelectionDecisionStatus;
  source_group: 'strict' | 'near' | 'pending' | 'excluded' | 'screen_unresolved' | 'duplicate';
  source_row_count: number; source_row_indexes: number[]; target_trade_date: string; source_date: string | null;
  source_input_identity: string | null; source_rule_version: string | null;
  decision_reason_code: string; decision_reason: string; source_metrics: JsonObject;
  source_refs: JsonObject[]; research_priority: JsonObject | null;
}


export interface ResearchSelectionLedger extends ResearchReadOnlyFlags {
  schema_version: 'v4.manager_research.selection_ledger.v1';
  status: 'READY' | 'READY_WITH_GAPS' | 'CANNOT_CONFIRM'; target_trade_date: string;
  source_date: string | null; source_input_identity: string | null; source_rule_version: string | null;
  source_status?: string; decision_identity: string; decisions: ResearchSelectionDecision[];
  coverage: JsonObject; gaps: string[]; universe_exhaustive: false; formal_selection_input: false;
  target_connect_eligibility: 'UNCHANGED_SEPARATE_FORMAL_SELECTION';
  as_of_claim: 'NONE_RETROSPECTIVE_RESEARCH';
}


export interface IndependentAnnouncementCard extends ResearchReadOnlyFlags {
  symbol: string; name?: string; title?: string; event_id: string; proposition_id?: string;
  document_sha256: string; published_at: string; retrieved_at: string; available_at: string;
  disposition: 'POSITIVE_OBSERVATION'; support: JsonObject; evidence: JsonObject[];
  observation_role: 'EXISTING_OFFICIAL_STATEMENT_NOT_CONNECT_SELECTION';
  assertion: 'SOURCE_STATEMENT_NOT_PRICE_PREDICTION_OR_BUY';
  focus_eligible: false; qualified: false; buy_allowed: false;
  target_connect_membership: JsonObject;
}


export interface IndependentAnnouncementObservations extends ResearchReadOnlyFlags {
  status: 'OBSERVED_WITH_RESTRICTIONS' | 'CANNOT_CONFIRM'; cards: IndependentAnnouncementCard[];
  rejections: JsonObject[]; card_count: number; symbol_count: number;
  scored_attention_input: false; formal_selection_input: false; universe_exhaustive: false;
}


export interface ResearchScopeDiagnostics extends JsonObject {
  status: 'OWNER_VERIFIED' | 'CANNOT_CONFIRM'; target_trade_date: string;
  membership_identity: string | null; counts: Record<string, {input: number; admitted: number; rejected: number}>;
  rejection_reasons: Record<string, number>; gaps: string[];
  count_basis: 'PER_INPUT_LIST_NOT_UNIQUE_SECURITIES'; formal_selection: FormalConnectSelection;
}


export interface ResearchInputDiagnostics extends JsonObject {
  scope: Record<string, ResearchScopeDiagnostics>;
  official_announcements: {status: string; coverage: JsonObject; gaps: string[]};
  eastmoney_selection: {status: string; document_count: number; exhaustive: false; gaps: string[]};
  us_relations: {status: string; assessment_state: UsMappingAssessmentState; acquisition_field_location: string;
    material_complete: boolean; gaps: string[]};
}



export interface ResearchAttention extends JsonObject {
  schema_version: 'v4.manager_research.research_attention.v1'; target_trade_date: string;
  research_cutoff: string; status: string; priority_name: string; config: JsonObject;
  cards: ResearchAttentionCard[]; coverage: JsonObject; gaps: string[]; input_identity: string; ordering_basis?: string;
  us_mapping_diagnostics?: UsMappingDiagnostics;
  observation_only?: IndependentAnnouncementObservations; input_diagnostics?: ResearchInputDiagnostics;
  research_selection?: ResearchSelectionLedger;
}


export interface ManagerWorkspace extends JsonObject {
  semantic_version: '20260921.manager-semantic.r3.v1'; focus_symbols: string[];
  briefing: JsonObject; company_events: JsonObject[]; rejected_relations: JsonObject[];
  schema_version: 'v4.manager_research.workspace.v1'; target_trade_date: string;
  input_identity: string; stocks: WorkspaceStock[]; lanes: WorkspaceLane[];
  themes: JsonObject[]; materials: JsonObject[]; gaps: string[];
  summary: {stock_count: number; relation_count: number; theme_count: number; reused_material_count: number; formal_recommendation_count: 0};
  market_screen?: ReboundScreen; market_screen_evidence?: JsonObject;
  us_market_attention?: UsMarketAttention; research_attention?: ResearchAttention;
  us_mapping_research?: UsMappingResearch;
  plan_product?: JsonObject; workspace_plan_attempt?: JsonObject; plan_context?: JsonObject;
  selection_diagnostics?: SelectionDiagnostics;
  date_bindings?: WorkspaceDateBindings; daily_channels?: DailyChannels;
}


export type WorkspaceView = 'auto' | 'historical' | 'dynamic';


export interface AnnouncementObservation extends JsonObject {
  schema_version: 'v4.manager_research.announcement_observation.v1'; target_trade_date: string;
  research_cutoff: string; prior_session: string; status: string; count_known: boolean;
  latest_attempt: JsonObject | null; observations: JsonObject[]; pending_observations: JsonObject[];
  official_documents: JsonObject[]; coverage: JsonObject; gaps: string[]; capture_runs: JsonObject[];
  eastmoney_hk_status?: string; eastmoney_hk_documents?: JsonObject[];
  eastmoney_hk_capture?: JsonObject | null; eastmoney_hk_attempt?: JsonObject | null; eastmoney_hk_gaps?: string[];
}


/** Read-only exact publication-day review returned by the existing owner GET. */
export interface AnnouncementReview extends JsonObject {
  schema_version: 'v4.manager_research.announcement_review.v1'; target_trade_date: string;
  daily_publication_date: string; publication_timezone: 'Asia/Hong_Kong'; status: string;
  count_known: boolean; official_documents: JsonObject[]; coverage: JsonObject; gaps: string[];
  capture_runs: JsonObject[]; retained_cross_day: JsonObject;
}
