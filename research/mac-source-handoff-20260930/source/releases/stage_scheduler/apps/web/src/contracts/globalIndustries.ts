export type GlobalIndustryStatus = "READY" | "PARTIAL" | "CANNOT_CONFIRM";
export type GlobalIndustryDirection = "UP" | "DOWN" | "FLAT" | "CANNOT_CONFIRM";

export const GLOBAL_INDUSTRY_MAPPING_VERSION = "v3_5.global_industry_proxy_map.v1";
export const GLOBAL_INDUSTRY_GROUP = "GLOBAL_INDUSTRY";
export const GLOBAL_INDUSTRY_MAPPINGS = [
  { label: "AI算力", group: GLOBAL_INDUSTRY_GROUP, mapping_type: "stock_basket_proxy", proxy_symbols: ["NVDA", "AVGO", "AMD"] },
  { label: "CPO", group: GLOBAL_INDUSTRY_GROUP, mapping_type: "stock_basket_proxy", proxy_symbols: ["COHR", "LITE", "CIEN"] },
  { label: "半导体", group: GLOBAL_INDUSTRY_GROUP, mapping_type: "etf_proxy", proxy_symbols: ["SOXX"] },
  { label: "存储", group: GLOBAL_INDUSTRY_GROUP, mapping_type: "stock_basket_proxy", proxy_symbols: ["MU", "WDC", "STX"] },
  { label: "数据中心", group: GLOBAL_INDUSTRY_GROUP, mapping_type: "stock_basket_proxy", proxy_symbols: ["VRT", "DLR", "EQIX"] },
  { label: "云计算", group: GLOBAL_INDUSTRY_GROUP, mapping_type: "etf_proxy", proxy_symbols: ["CLOU"] },
  { label: "商业航天", group: GLOBAL_INDUSTRY_GROUP, mapping_type: "etf_proxy", proxy_symbols: ["ARKX"] },
  { label: "卫星", group: GLOBAL_INDUSTRY_GROUP, mapping_type: "etf_proxy", proxy_symbols: ["UFO"] },
  { label: "机器人", group: GLOBAL_INDUSTRY_GROUP, mapping_type: "etf_proxy", proxy_symbols: ["BOTZ"] },
  { label: "自动驾驶", group: GLOBAL_INDUSTRY_GROUP, mapping_type: "etf_proxy", proxy_symbols: ["DRIV"] },
  { label: "核电", group: GLOBAL_INDUSTRY_GROUP, mapping_type: "etf_proxy", proxy_symbols: ["NLR"] },
  { label: "电网", group: GLOBAL_INDUSTRY_GROUP, mapping_type: "etf_proxy", proxy_symbols: ["GRID"] },
  { label: "军工", group: GLOBAL_INDUSTRY_GROUP, mapping_type: "etf_proxy", proxy_symbols: ["ITA"] },
  { label: "新能源", group: GLOBAL_INDUSTRY_GROUP, mapping_type: "etf_proxy", proxy_symbols: ["ICLN"] },
  { label: "光伏", group: GLOBAL_INDUSTRY_GROUP, mapping_type: "etf_proxy", proxy_symbols: ["TAN"] },
  { label: "锂电池", group: GLOBAL_INDUSTRY_GROUP, mapping_type: "etf_proxy", proxy_symbols: ["LIT"] },
  { label: "石油", group: GLOBAL_INDUSTRY_GROUP, mapping_type: "etf_proxy", proxy_symbols: ["XLE"] },
  { label: "天然气", group: GLOBAL_INDUSTRY_GROUP, mapping_type: "etf_proxy", proxy_symbols: ["FCG"] },
  { label: "铜/有色", group: GLOBAL_INDUSTRY_GROUP, mapping_type: "etf_proxy", proxy_symbols: ["COPX"] },
  { label: "黄金", group: GLOBAL_INDUSTRY_GROUP, mapping_type: "etf_proxy", proxy_symbols: ["GLD"] },
  { label: "银行金融", group: GLOBAL_INDUSTRY_GROUP, mapping_type: "etf_proxy", proxy_symbols: ["KBE"] },
  { label: "生物医药", group: GLOBAL_INDUSTRY_GROUP, mapping_type: "etf_proxy", proxy_symbols: ["XBI"] },
  { label: "消费", group: GLOBAL_INDUSTRY_GROUP, mapping_type: "etf_basket_proxy", proxy_symbols: ["XLY", "XLP"] },
  { label: "稀土", group: GLOBAL_INDUSTRY_GROUP, mapping_type: "etf_proxy", proxy_symbols: ["REMX"] },
] as const;

export type GlobalIndustryRow = {
  label: string;
  group: string;
  mapping_type: string;
  proxy_symbols: string[];
  available_symbols: string[];
  missing_symbols: string[];
  requested_symbol_count: number;
  available_symbol_count: number;
  coverage: { available: number; requested: number };
  coverage_pct: number;
  change_pct: number | null;
  pct_change?: number | null;
  direction: GlobalIndustryDirection;
  status: GlobalIndustryStatus;
  quote_session_dates: string[];
  quote_session_times: string[];
  cannot_confirm: string[];
};

export type GlobalIndustryLineage = {
  path: string;
  sha256: string;
  lineage_status?: string;
  receipt?: { path: string; sha256: string } | null;
  manifest?: { path: string; sha256: string } | null;
};

export type GlobalIndustryQuote = {
  symbol: string;
  exchange: string;
  session_date: string;
  session_time: string;
  last: number | null;
  previous_close: number | null;
  change_pct: number;
  provider: string;
};

export type GlobalIndustryResponse = {
  schema_version: string;
  status: GlobalIndustryStatus;
  target_date: string;
  research_date: string;
  source_date: string;
  provider: string;
  provider_url?: string;
  provider_session_dates: string[];
  provider_session_times: string[];
  source_response_sha256: string;
  quotes: GlobalIndustryQuote[];
  provider_receipt?: Record<string, unknown> | null;
  capture_phase: string;
  captured_at: string;
  generated_at: string;
  mapping_version: string;
  requested_symbol_count: number;
  available_symbol_count: number;
  rows: GlobalIndustryRow[];
  cannot_confirm: string[];
  artifact?: GlobalIndustryLineage | null;
  manifest?: { path: string; sha256: string } | null;
  receipt?: { path: string; sha256: string } | null;
  write_policy: "read_only";
  recommendation_status: "RESEARCH_ONLY";
  RESEARCH_ONLY: true;
  production_allowed: false;
  buy_gate_updated: false;
  orders_sent: false;
};

export type GlobalIndustryDatesResponse = {
  research_dates?: string[];
  external_finance_dates?: string[];
  market_snapshot_dates?: string[];
};
