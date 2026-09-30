export type ReviewRow = Readonly<Record<string, unknown>> & { readonly code?: string; readonly name?: string; readonly trade_date?: string };

export type AShareCloseMarket = {
  regime?: string;
  up_count?: number;
  down_count?: number;
  flat_count?: number;
  limit_up_count?: number;
  limit_down_count?: number;
  amount_yi?: number;
  market_width?: number;
  external_environment?: string;
  boundary?: string;
};

export type AShareCloseBoard = ReviewRow & {
  board_name?: string;
  canonical_theme?: string;
  board_role?: string;
  median_pct_change?: number;
  up_ratio?: number;
  counterevidence?: string;
  trigger?: string;
  invalidation?: string;
};

export type AShareCloseRole = ReviewRow & {
  stock_code?: string;
  stock_name?: string;
  board_name?: string;
  primary_role?: string;
  pct_change?: number;
  role_explanation?: string;
  invalidation?: string;
  recommendation_status?: string;
};

export type AShareRichRow = ReviewRow & {
  title?: string;
  value?: string | number;
  section?: string;
  board?: string;
  board_name?: string;
  canonical_theme?: string;
  today_role?: string;
  role?: string;
  role_type?: string;
  stock?: string;
  stock_name?: string;
  stock_code?: string;
  theme?: string;
  direction?: string;
  condition?: string;
  mapped_theme?: string;
  planned_anchor?: string;
  close_result?: string;
  open_realization?: string;
  intraday_validation?: string;
  tomorrow_scenario?: string;
  local_evidence?: string;
  evidence?: string;
  confirmed_by?: string;
  why_this_role?: string;
  next_trigger?: string;
  upgrade?: string;
  upgrade_condition?: string;
  invalidation?: string;
  invalidation_condition?: string;
  tomorrow_if_strong?: string;
  tomorrow_if_weak?: string;
  cannot_confirm?: string;
  not_confirmed_by?: string;
  [key: string]: unknown;
};

export type AShareVideoEvidence = Readonly<Record<string, unknown>> & {
  status?: string;
  target_trade_date?: string;
  trade_date?: string;
  date_scope?: string;
  artifact_refs?: readonly (Readonly<Record<string, unknown>> & { path?: string; source_path?: string })[];
};

export type ReviewCoreBundleEvidence = Readonly<Record<string, unknown>> & {
  run_id?: string;
  bundle_sha256?: string;
  manifest_sha256?: string;
  receipt_sha256?: string;
};

export type ReviewSurface = Readonly<Record<string, unknown>> & {
  tier?: "V3_RICH_READY" | "V3_RICH_PARTIAL" | "COMPACT_NATIVE" | "COMPACT_NOT_MATERIALIZED" | string;
  status?: string;
  trade_date?: string;
  source_role?: string;
  source_refs?: readonly Readonly<Record<string, unknown>>[];
  stage_validation_count?: number;
};

export type AShareCloseModel = {
  schema_version?: string;
  status?: string;
  run_id?: string;
  review_date?: string;
  as_of?: string;
  objective?: string;
  producer_type?: string;
  learning_status?: string;
  formal_generalization?: string;
  model_promotion?: string;
  semantic_model_status?: string;
  semantic_model_call_count?: number;
  visibility_stage?: string;
  target_video_review_status?: string;
  previous_plan_realization?: string;
  market_summary?: AShareCloseMarket;
  board_rows?: readonly AShareCloseBoard[];
  anchor_role_rows?: readonly AShareCloseRole[];
  shadow_watch_pool?: {
    boundary?: string;
    abstain?: boolean;
    abstain_reason?: string;
    core?: readonly AShareCloseRole[];
    conditional?: readonly AShareCloseRole[];
    observation_or_risk?: readonly AShareCloseRole[];
  };
  safety?: Readonly<Record<string, unknown>>;
  cannot_confirm?: readonly string[];
};

export type AShareReview = {
  schema_version?: string;
  trade_date?: string;
  status?: string;
  headline?: string;
  market_regime?: string;
  risk_tone?: string;
  big_picture: readonly ReviewRow[];
  mainlines: readonly AShareRichRow[];
  core_stocks: readonly ReviewRow[];
  observation_pool: readonly ReviewRow[];
  next_day_trigger_tree: readonly ReviewRow[];
  quality_gate: readonly ReviewRow[];
  cannot_confirm: readonly string[];
  model_review?: AShareCloseModel;
  source_evidence?: readonly ReviewRow[];
  source_role?: string;
  close_chain?: {
    schema_version?: string;
    trade_date?: string;
    status?: string;
    nodes?: readonly (ReviewRow & { task_id?: string; slot?: string; label?: string; status?: string; reason?: string })[];
    cannot_confirm?: readonly string[];
  } | null;
  source_sha256?: string;
  summary_cards?: readonly AShareRichRow[];
  market_rows?: readonly AShareRichRow[];
  prior_plan_rows?: readonly AShareRichRow[];
  board_rows?: readonly AShareRichRow[];
  anchor_rows?: readonly AShareRichRow[];
  anchor_role_v3_rows?: readonly AShareRichRow[];
  intraday_handoff_rows?: readonly AShareRichRow[];
  catalyst_rows?: readonly AShareRichRow[];
  trigger_rows?: readonly AShareRichRow[];
  scenario_tree_rows?: readonly AShareRichRow[];
  video?: AShareVideoEvidence;
  video_gap_rows?: readonly AShareRichRow[];
  source_status_rows?: readonly AShareRichRow[];
  formal_pool_validation?: Readonly<Record<string, unknown>>;
  rule_adoption_rows?: readonly AShareRichRow[];
  video_learning_rows?: readonly AShareRichRow[];
  cannot_confirm_items?: readonly string[];
  source_run_id?: string;
  artifact_sha256?: string;
  review_core_bundle?: ReviewCoreBundleEvidence;
  review_surface?: ReviewSurface;
  stage_validation_rows?: readonly AShareRichRow[];
  write_policy?: string;
  production_allowed: false;
  buy_gate_updated: false;
  orders_sent: false;
};

export type ReviewMetric = {
  evidence_status?: string;
  selected_count?: number | null;
  hit_count?: number | null;
  coverage_pct?: number | null;
};

export type HkAttributionRow = {
  rank?: number;
  code?: string;
  name?: string;
  pct_chg_close?: number;
  model_0_2_hit?: boolean;
  stage_union_hit?: boolean;
  first_stage?: string | null;
  all_stages?: readonly string[];
  classification?: string;
};

export type HkModelSelectionReview = {
  schema_version?: string;
  status?: string;
  trade_date?: string;
  primary_kpi?: string;
  evidence_mode?: string;
  reference_snapshot?: boolean;
  close_source_sha256?: string;
  models?: Record<string, ReviewMetric>;
  stage_union?: ReviewMetric;
  row_counts?: Record<string, number>;
  close_top20?: readonly HkAttributionRow[];
  top20_attribution?: readonly HkAttributionRow[];
  cannot_confirm?: readonly string[];
  missing_stages?: readonly string[];
};

export type HkReview = { market?: string; model_selection_review?: HkModelSelectionReview };

export type HkPrefixResearchEvidence = {
  label?: string;
  ref?: string;
  sha256?: string;
  verification?: string;
};

export type HkPrefixResearch = {
  schema_version?: string;
  status?: string;
  requested_date?: string;
  asset_id?: string;
  run_id?: string;
  asset_status?: string;
  scope?: {
    historical_prefix_only?: boolean;
    event_date_range?: readonly string[];
    max_event_year?: number;
    consumed_2026?: boolean;
    event_day_included?: boolean;
    available_at_basis?: string;
    window_status?: string;
  } | null;
  source?: {
    rows?: number;
    symbols?: number;
    date_range?: readonly string[];
    schema_columns?: readonly string[];
    sha256?: string;
    manifest_sha256?: string;
    status?: string;
    price_basis?: string;
    price_basis_status?: string;
    volume_source_column?: string;
    volume_unit?: string;
  } | null;
  calendar?: {
    market_day_count?: number;
    row_count?: number;
    date_range?: readonly string[];
    source?: string;
    certification?: string;
    receipt_sha256?: string;
    receipt_verification?: string;
  } | null;
  binding?: {
    groups?: number;
    controls?: number;
    series_count?: number;
    rows_per_series?: number;
    resampled?: boolean;
    event_type_counts?: Record<string, number>;
    sha256?: string;
    matched_verdict_sha256?: string;
  } | null;
  export?: {
    series_count?: number;
    rows_per_series?: number;
    total_rows?: number;
    event_date_range?: readonly string[];
    event_type_counts?: Record<string, number>;
    state_distribution?: Record<string, number>;
    state_distribution_by_event_type?: Record<string, Record<string, number>>;
    quality_distribution?: Record<string, number>;
    source_observed_rows?: number;
    source_missing_rows?: number;
    unknown_series_count?: number;
    unknown_row_count?: number;
    indeterminate_series_count?: number;
    indeterminate_row_count?: number;
    terminal_unknown_series_count?: number;
    terminal_indeterminate_series_count?: number;
    complete_terminal_pairs?: number;
    required_complete_pairs?: number;
    coverage_status?: string;
    coverage_fraction?: string;
    terminal_delta_mean?: number | null;
    terminal_delta_lower_mean?: number | null;
    terminal_delta_upper_mean?: number | null;
    warmup_is_not_no_active_setup?: boolean;
  } | null;
  acceptance?: {
    field_isolation?: string;
    future_isolation?: string;
    past_positive_control?: string;
    csv_replay?: string;
    source_window_replay?: string;
  };
  review?: {
    manual_review_status?: string;
    conclusion_status?: string;
    comparison_status?: string;
    conclusion?: string;
    no_alpha_claim?: boolean;
    main_effect_status?: string;
    daily_selection_separated?: boolean;
  };
  evidence?: readonly HkPrefixResearchEvidence[];
  cannot_confirm?: readonly string[];
  research_only?: true;
  production_allowed?: false;
  buy_gate_updated?: false;
  orders_sent?: false;
};

export type DailyResearchReviewSection = Readonly<Record<string, unknown>>;

export type DailyResearchReview = {
  schema_version?: string;
  status?: string;
  artifact_status?: string;
  trade_date?: string;
  target_date?: string;
  source_role?: string;
  source_path?: string;
  source_artifact_sha256?: string;
  artifact_sha256?: string;
  source_schema_version?: string | number;
  data_as_of?: string;
  generated_at?: string;
  generation_status?: string;
  generation?: {
    status?: string;
    owner?: string;
    producer_reference?: string;
    cannot_confirm?: readonly string[];
  };
  focus?: DailyResearchReviewSection;
  market_breadth?: DailyResearchReviewSection;
  feedback_matrix?: DailyResearchReviewSection;
  money_effect?: DailyResearchReviewSection;
  loss_effect?: DailyResearchReviewSection;
  promotion?: DailyResearchReviewSection;
  ladder_gap?: DailyResearchReviewSection;
  theme_tree?: DailyResearchReviewSection;
  event_ledger?: DailyResearchReviewSection;
  cannot_confirm?: readonly string[];
  write_policy?: string;
  research_only?: true;
  production_allowed?: false;
  buy_gate_updated?: false;
  orders_sent?: false;
};

export type ReviewEnvelope = {
  intraday_research?: IntradayResearchReview;
  hk_prefix_research?: HkPrefixResearch;
  schema_version?: string;
  trade_date: string;
  reference_snapshot?: boolean;
  market_reviews: { A: AShareReview; HK: HkReview };
  research_review?: DailyResearchReview;
  production_allowed: false;
  buy_gate_updated: false;
  orders_sent: false;
};


export type ManualReviewResult = {
  status: "READY_FOR_REVIEW" | "ALREADY_EXISTS";
  trade_date: string;
  artifact_sha256?: string;
  production_allowed: false;
  buy_gate_updated: false;
  orders_sent: false;
};


export type IntradaySnapshot = {
  schema: 3; date: string; slot: string; captured_at: string; drift_minutes: number;
  prev_date: string; sample: number; expected_sample: number; coverage_rate: number | null;
  avg: number; median: number; up_rate: number; up_count: number; down_count: number; deep_loss_5: number;
  by_tier: Record<string, unknown>; top_boards: ReadonlyArray<Readonly<Record<string, unknown>>>;
  top_board_level: number; live: Readonly<Record<string, unknown>> | null;
};
export type IntradayResearchReview = {
  status: "READY" | "CANNOT_CONFIRM"; date?: string; slots: IntradaySnapshot[];
  missing_slots?: string[]; cannot_confirm: string[];
  auction?: Readonly<Record<string, unknown>>; path?: Readonly<Record<string, unknown>>;
  evidence?: ReadonlyArray<Readonly<Record<string, unknown>>>;
};
