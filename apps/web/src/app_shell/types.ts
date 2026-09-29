// Exact source type declarations.


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
  status?: string; complete?: boolean; recommendation_status?: string; producer_id?: string; source_path?: string;
  cannot_confirm?: Array<string | { reason?: string; description?: string }>;
};
export type PoolResponse = {
  data_status: string; rows: PoolRow[]; a_all_pool_rows?: PoolRow[];
  pools?: PoolGroup[]; market_totals?: { A?: number; HK?: number }; a_all_pool_complete?: boolean;
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
  current_change_pct?: number | null;
  open_price?: number; last_price?: number; high_price?: number; low_price?: number;
  source_last_bar_time?: string;
};
export type MarketSummary = {
  label?: string; candidate_count?: number; source_rows?: number;
  requested_rows?: number; source_status?: string; data_level?: string;
};
export type OpeningSecondFilterMarket = {
  refresh_time?: string; strategy?: string; row_count?: number;
};
export type OpeningSecondFilter = {
  model_id?: string; model_version?: string; champion_contract?: string;
  markets?: { A?: OpeningSecondFilterMarket; HK?: OpeningSecondFilterMarket };
};
export type StageWorkbench = {
  ok?: boolean; trade_date?: string;
  stage: { stage_id: string; label?: string; window?: string; status: string; display_status: string };
  markets?: { A?: MarketSummary; HK?: MarketSummary };
  unified_rows: StageRow[];
  selected_a_rows: number; selected_hk_rows: number; selected_total_rows: number;
  selection_mode: string; response_source?: string; reference_snapshot?: boolean;
  opening_second_filter?: OpeningSecondFilter;
  stage_lineage?: StageLineage;
  historical_readbacks?: Array<{
    market: string; backfill_run_id: string; selection_run_id: string;
    artifact_sha256: string; binding_sha256: string; real_time_success: false;
    original_formal: { status: string; run_id?: string | null; cannot_confirm?: string[] };
  }>;
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
export type ReviewMetric = {
  evidence_status?: string; selected_count?: number | null; hit_count?: number | null;
  coverage_pct?: number | null; precision_pct?: number | null;
};
export type ReviewAttributionRow = {
  rank?: number; code?: string; name?: string; pct_chg_close?: number;
  model_0_2_hit?: boolean; stage_union_hit?: boolean; classification?: string;
};
export type ModelSelectionReview = {
  schema_version?: string; evidence_mode?: string;
  status?: string; trade_date?: string; primary_kpi?: string;
  models?: Record<string, ReviewMetric>; stages?: Record<string, ReviewMetric>;
  stage_union?: ReviewMetric; row_counts?: Record<string, number>;
  top20_attribution?: ReviewAttributionRow[]; close_top20?: ReviewAttributionRow[];
  missing_stages?: string[]; cannot_confirm?: string[];
  production_allowed?: boolean; buy_gate_updated?: boolean; orders_sent?: boolean;
};
export type ReviewResponse = {
  trade_date?: string; reference_snapshot?: boolean;
  market_reviews?: { HK?: { model_selection_review?: ModelSelectionReview } };
};
export type NavigationUrlState = {
  view?: string | null;
  stage?: string | null;
};