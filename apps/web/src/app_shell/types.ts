// Exact source type declarations.

import type {
  HkAttributionRow,
  HkModelSelectionReview,
  ReviewMetric as ContractReviewMetric,
  ReviewResponse as ContractReviewResponse,
} from "../contracts/review";


export type StageDefinition = { id: string; label: string; timeline: string };

export type DateResponse = {
  default_date: string; stage_dates: string[]; review_dates?: string[]; research_dates?: string[]; future_target_dates: string[];
  dates?: string[]; navigation_date?: string; navigation_timezone?: string;
  hk_observation_only_dates?: string[];
  runtime_identity?: { status: string; release_id: string; process_status: string };
};
export type PoolRow = {
  market?: string; symbol?: string; code?: string; stock_name?: string; name?: string; display_name?: string; pool_rank?: number;
  pool_score?: number; signal_date?: string; source_date?: string; article_publish_date?: string;
  publish_date?: string; effective_trade_date?: string; target_date?: string; trade_date?: string;
  source_tag?: string; source_label?: string; source_tags?: string | string[]; source_lanes?: string | string[];
  source_trace?: string | string[]; pool_id?: string;
};
export type PoolGroup = {
  pool_id: string; display_name?: string; market?: string; pool_size?: number; returned_rows?: number; rows?: PoolRow[];
  page_offset?: number; page_limit?: number; has_more?: boolean;
  status?: string; complete?: boolean; recommendation_status?: string; producer_id?: string; source_path?: string;
  cannot_confirm?: Array<string | { reason?: string; description?: string }>;
};
export type PoolPageEntry = {
  total_rows: number; offset: number; limit: number; returned_rows: number;
  has_more: boolean; next_offset: number | null; complete: boolean;
};
export type PoolPagination = {
  offset: number; limit: number; next_offset: number | null; has_more: boolean; complete?: boolean;
  arrays?: Partial<Record<"a_all_pool_rows" | "a_source_only_rows" | "unified_rows", PoolPageEntry>>;
  pools?: Record<string, PoolPageEntry>;
};
export type PoolResponse = {
  trade_date?: string; requested_date?: string; selected_date?: string;
  data_status: string; rows: PoolRow[]; a_all_pool_rows?: PoolRow[];
  a_all_pool_row_count?: number; a_source_only_row_count?: number; unified_row_count?: number;
  pools?: PoolGroup[]; market_totals?: { A?: number; HK?: number }; a_all_pool_complete?: boolean;
  pagination?: PoolPagination;
  hk_pool_version?: string; hk_pool_role?: string; blocking_reasons: string[];
};
export type StageRow = {
  market?: string; code?: string; symbol?: string; stock_code?: string; name?: string; stock_name?: string;
  rank?: number | string; stage_rank?: number | string; pool_rank?: number | string;
  score?: number; stage_score?: number; stage_rtdata_score?: number;
  d1_change_pct?: number; stage_display_decision?: string; next_validation_time?: string;
  status?: string; source_mode?: string; stage_id?: string; trade_date?: string;
  latest_research_slot?: string; news_quality_score?: number; research_quality_score?: number;
  news_research_reason?: string; source_health?: string;
  cannot_confirm?: string[]; data_level?: string; recommendation_status?: string;
  support_primary_price?: number | string; pressure_price?: number | string;
  invalidation_price?: number | string;
  current_change_pct?: number;
  open_price?: number; last_price?: number; high_price?: number; low_price?: number;
  source_last_bar_time?: string;
};
export type MarketSummary = {
  label?: string; candidate_count?: number | null; source_rows?: number | null;
  requested_rows?: number | null; source_status?: string; data_level?: string;
  status?: string; selection_status?: string; selected_rows?: number | null; coverage_ratio?: number | null;
  source_evidence?: string[];
  cannot_confirm?: string[];
  display_mode?: string; display_reasons?: string[]; observation_count?: number | null;
  selection_mode?: string; backfill_run_id?: string | null; backfill_run_ids?: string[];
  selection_manifest_sha256?: string | null; selection_receipt_sha256?: string | null;
  selection_artifact_sha256?: string | null; selection_manifest_receipt_verified?: boolean;
  runner_receipt_verified?: boolean; runner_receipt_status?: string;
  runner_receipt_sha256?: string | null;
  recovery_provenance?: {
    mode?: string; backfill_run_id?: string | null; backfill_run_ids?: string[];
    selection_manifest_receipt_verified?: boolean;
    runner_receipt_verified?: boolean; runner_receipt_status?: string;
    runner_receipt_sha256?: string | null;
  };
};
export type OpeningSecondFilterMarket = {
  refresh_time?: string; strategy?: string; row_count?: number;
};
export type OpeningSecondFilter = {
  model_id?: string; model_version?: string; champion_contract?: string;
  markets?: { A?: OpeningSecondFilterMarket; HK?: OpeningSecondFilterMarket };
};
export type StageSelectionMarketId = "A_SHARE" | "HK_CONNECT";
export type StageSelectionMarket = Readonly<Record<string, unknown>> & {
  market: StageSelectionMarketId;
  trade_date?: string;
  stage_id?: string;
  status: string;
  selection_status: string;
  source_status?: string;
  research_source_status?: string;
  requested_rows?: number | null;
  source_rows?: number | null;
  selected_rows?: number | null;
  coverage_ratio?: number | null;
  rows?: StageRow[] | null;
  source_evidence?: string[] | null;
  cannot_confirm?: Array<string | { reason?: string; description?: string }> | null;
  selection_manifest_receipt_verified?: boolean;
};
export type StageSelectionMarkets = readonly ("A" | "HK")[]
  | Readonly<Partial<Record<StageSelectionMarketId, StageSelectionMarket>>>;
export type StageExecutionEvidence = {
  trade_date?: string;
  stage_id?: string;
  status?: string;
  execution_verified?: boolean;
  natural_verified?: boolean;
  write_performed?: boolean;
  cannot_confirm?: string[];
};
export type StageWorkbench = {
  ok?: boolean; trade_date?: string; status?: string;
  selection_markets?: StageSelectionMarkets;
  execution_evidence?: StageExecutionEvidence;
  cannot_confirm?: string[];
  cannot_confirm_codes?: string[];
  stage: { stage_id: string; label?: string; window?: string; status: string; display_status: string; cannot_confirm?: string[] };
  markets?: { A?: MarketSummary; HK?: MarketSummary };
  unified_rows: StageRow[];
  selected_a_rows: number; selected_hk_rows: number | null; selected_total_rows: number | null;
  selection_mode: string; response_source?: string; reference_snapshot?: boolean;
  opening_second_filter?: OpeningSecondFilter;
  stage_lineage?: StageLineage;
};
export type StageLineageBranch = {
  label?: string; status?: string; origin?: string; receipt_sha256?: string | null;
  receipt_raw_sha256?: string | null; due_status?: string;
  receipt_sha256_by_market?: Record<string, string>;
  receipt_raw_sha256_by_market?: Record<string, string>;
  manifest_sha256_by_market?: Record<string, string>;
  manifest_raw_sha256_by_market?: Record<string, string>;
  lineage_by_market?: Record<string, {
    run_id: string; artifact_sha256: string; manifest_sha256: string;
    manifest_raw_sha256: string; receipt_sha256: string; receipt_raw_sha256: string;
  }>;
  write_performed?: boolean; markets?: { A?: { selected_rows?: number }; HK?: { selected_rows?: number } };
};
export type StageLineage = {
  natural?: StageLineageBranch;
  recovery?: StageLineageBranch;
  cannot_confirm?: string[];
};
export type StageTimelineSnapshot = {
  date: string;
  loading: boolean;
  payload?: StageWorkbench;
  error?: string;
};
export type ReviewMetric = ContractReviewMetric;
export type ReviewAttributionRow = HkAttributionRow;
export type ModelSelectionReview = HkModelSelectionReview;
export type ReviewResponse = ContractReviewResponse;
export type NavigationUrlState = {
  view?: string | null;
  stage?: string | null;
};
