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
