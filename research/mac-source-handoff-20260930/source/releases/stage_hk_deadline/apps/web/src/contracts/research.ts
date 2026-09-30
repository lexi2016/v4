export type ResearchArticle = {
  article_id: string;
  archive_date: string;
  stock_code: string;
  stock_name: string;
  source_type: string;
  source_name: string;
  source_title: string;
  url: string;
  theme: string;
  catalyst: string;
  evidence_sentence: string;
  evidence_level: string;
  confidence: string;
  published_at: string;
  collected_at: string;
  first_seen_at: string;
  duplicate_evidence_count: number;
  recommendation_status: "RESEARCH_ONLY";
};

export type ResearchStock = {
  stock_code: string;
  stock_name: string;
  archive_date: string;
  research_score: number;
  research_status: string;
  evidence_count: number;
  source_count: number;
  source_types: string[];
  themes: string[];
  top_catalysts: string[];
  first_seen_at: string;
  collected_at: string;
  formal_overlap: boolean;
  stage_overlap: boolean;
  recommendation_status: "RESEARCH_ONLY";
};

export type ResearchEnvelope = {
  schema_version: "v3_5.research_articles.v1";
  status: "READY" | "NOT_MATERIALIZED";
  endpoint_mode: "EXACT" | "LATEST";
  archive_date: string | null;
  timezone: "Asia/Shanghai";
  article_count: number;
  stock_pool_count: number;
  source_counts: Record<string, number>;
  dedupe_key_fields: string[];
  articles: ResearchArticle[];
  stock_pool: ResearchStock[];
  cannot_confirm: string[];
  loading_complete: true;
  write_policy: "read_only";
  recommendation_status: "RESEARCH_ONLY";
  production_allowed: false;
  buy_gate_updated: false;
  orders_sent: false;
};

export type ResearchDaySlot = {
  slot: string;
  status: "READY";
  raw_rows: number;
  exact_rows: number;
  excluded_rows: number;
  artifact_path: string;
  artifact_sha256: string;
  receipt_path: string;
  receipt_sha256: string;
  source_input_sha256: string;
};

export type ResearchDayCoverage = {
  expected_slots: number;
  ready_slots: number;
  missing_slots: string[];
  complete: boolean;
  slot_matrix: ResearchDaySlot[];
};

export type ResearchDayCounts = {
  raw_rows: number;
  evidence_rows: number;
  excluded_rows: number;
  mention_pairs: number;
  urls: number;
  stock_rollups: number;
  high_priority: number;
  duplicate_pairs: number;
};

export type ResearchEvidenceRow = Record<string, unknown> & {
  archive_date: string;
  slot: string;
  source_row_ref: string;
  stock_code?: string;
  stock_name?: string;
  url?: string;
  evidence_level?: string;
  evidence_sentence?: string;
};

export type ResearchMentionPair = {
  pair_key: string;
  normalized_url: string;
  stock_code: string;
  stock_name: string;
  winner: ResearchEvidenceRow;
  source_slots: string[];
  occurrence_count: number;
  variant_count: number;
  article_ids: string[];
  dedupe_keys: string[];
  source_refs: Array<Record<string, unknown>>;
  duplicate_reason: string;
  tiebreaker: Record<string, unknown>;
  recommendation_status: "RESEARCH_ONLY";
};

export type ResearchStockRollup = {
  stock_code: string;
  stock_name: string;
  mention_pair_count: number;
  evidence_row_count: number;
  source_slots: string[];
  urls: string[];
  pair_keys: string[];
  duplicate_pair_count: number;
  recommendation_status: "RESEARCH_ONLY";
};

export type ResearchHighPriority = {
  stock_code: string;
  rank: number;
  reason: string;
  rule_id: string;
  recommendation_status: "RESEARCH_ONLY";
};

export type ResearchDayLineage = {
  source_refs: Record<string, Record<string, unknown>>;
  artifact_sha256: string;
  manifest_sha256: string;
  receipt_sha256: string;
  current_sha256: string | null;
  transformer_identity_sha256: string;
};

export type ResearchDayProduct = {
  schema_version: "v3_5.research_day_product.v1";
  contract_id: "v3_5.research_day_product.v1";
  workflow_name: "V35_DAILY_RESEARCH_AUTHORITY_V1";
  pass_signal: "V35_DAILY_RESEARCH_AUTHORITY_PASS_V1";
  archive_date: string | null;
  timezone: "Asia/Shanghai";
  date_mode: "EXACT";
  status: "READY" | "READY_WITH_DECLARED_GAPS" | "NOT_MATERIALIZED" | "CANNOT_CONFIRM";
  authoritative: boolean;
  RESEARCH_ONLY: true;
  endpoint_mode?: "EXACT" | "LATEST";
  requested_date?: string | null;
  resolved_date?: string | null;
  is_full_day?: boolean;
  loading_complete?: true;
  write_policy: "read_only";
  recommendation_status: "RESEARCH_ONLY";
  expected_slots: string[];
  coverage: ResearchDayCoverage;
  counts: ResearchDayCounts;
  exclusions?: Record<string, number>;
  excluded_by_date: Record<string, number>;
  slot_matrix: ResearchDaySlot[];
  evidence_rows: ResearchEvidenceRow[];
  mention_pairs: ResearchMentionPair[];
  stock_rollups: ResearchStockRollup[];
  high_priority: ResearchHighPriority[];
  high_priority_status: {
    status: string;
    rule_id: string | null;
    registry: string;
    cannot_confirm: string | null;
  };
  jyg_coverage: {
    status: "VALIDATED" | "CANNOT_CONFIRM";
    articles: number | null;
    expected_articles: number | null;
    stock_mentions: number | null;
    registry: "VALIDATED" | "MISSING";
    gap: string | null;
  };
  lineage: ResearchDayLineage | null;
  cannot_confirm: string[];
  production_allowed: false;
  buy_gate_updated: false;
  orders_sent: false;
  execution_origin?: "NATURAL" | "AUTO_RETRY" | "MANUAL_RECOVERY";
};

export type ResearchHourlyProduct = {
  schema_version: "v3_5.research_hourly_product.v1";
  status: "READY" | "NOT_MATERIALIZED";
  endpoint_mode: "EXACT_SLOT" | "LATEST_SLOT";
  date_mode: "EXACT";
  archive_date: string | null;
  slot: string | null;
  timezone: "Asia/Shanghai";
  is_full_day: false;
  row_count: number;
  stock_count: number;
  rows: Array<Record<string, unknown>>;
  stock_pool: Array<Record<string, unknown>>;
  cannot_confirm: string[];
  loading_complete: true;
  write_policy: "read_only";
  recommendation_status: "RESEARCH_ONLY";
  production_allowed: false;
  buy_gate_updated: false;
  orders_sent: false;
};

export type ResearchDayEnvelope = ResearchDayProduct;
