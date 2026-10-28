export type GlobalIndustryStatus = "READY" | "PARTIAL" | "CANNOT_CONFIRM";
export type GlobalIndustryDirection = "UP" | "DOWN" | "FLAT" | "CANNOT_CONFIRM";

export const GLOBAL_INDUSTRY_MAPPING_VERSION = "v3_5.global_industry_proxy_map.v1";
export const GLOBAL_INDUSTRY_GROUP = "GLOBAL_INDUSTRY";
export const GLOBAL_INDUSTRY_OFFICIAL_BOARD_MAP = [
  { label: "AI算力", plate_type: null, board_name: null },
  { label: "CPO", plate_type: null, board_name: null },
  { label: "半导体", plate_type: "INDUSTRY", board_name: "半导体" },
  { label: "存储", plate_type: "CONCEPT", board_name: "存储概念" },
  { label: "数据中心", plate_type: "CONCEPT", board_name: "IDC概念" },
  { label: "云计算", plate_type: "CONCEPT", board_name: "云计算服务商" },
  { label: "商业航天", plate_type: null, board_name: null },
  { label: "卫星", plate_type: null, board_name: null },
  { label: "机器人", plate_type: "CONCEPT", board_name: "机器人概念股" },
  { label: "自动驾驶", plate_type: "CONCEPT", board_name: "智能驾驶概念股" },
  { label: "核电", plate_type: "CONCEPT", board_name: "核电" },
  { label: "电网", plate_type: null, board_name: null },
  { label: "军工", plate_type: null, board_name: null },
  { label: "新能源", plate_type: null, board_name: null },
  { label: "光伏", plate_type: "CONCEPT", board_name: "光伏太阳能" },
  { label: "锂电池", plate_type: "CONCEPT", board_name: "锂电池" },
  { label: "石油", plate_type: null, board_name: null },
  { label: "天然气", plate_type: "CONCEPT", board_name: "天然气" },
  { label: "铜/有色", plate_type: null, board_name: null },
  { label: "黄金", plate_type: "INDUSTRY", board_name: "黄金" },
  { label: "银行金融", plate_type: null, board_name: null },
  { label: "生物医药", plate_type: null, board_name: null },
  { label: "消费", plate_type: null, board_name: null },
  { label: "稀土", plate_type: "CONCEPT", board_name: "稀土概念" },
] as const;

export const FUTU_US_NATIVE_BOARD_REGISTRY_VERSION = "futu_us_native_board_registry.v1";
export const FUTU_US_NATIVE_BOARD_REGISTRY_SHA256 = "5507b325b090329cbbdedb9dcf3ee0a7c8115fe9d7f2704f8ae81527b1276c9d";
export const FUTU_US_NATIVE_BOARD_REGISTRY = [
  { board_id: "US.LIST2015", plate_type: "INDUSTRY", board_name: "半导体", board_code: "US.LIST2015" },
  { board_id: "US.LIST23925", plate_type: "CONCEPT", board_name: "存储概念", board_code: "US.LIST23925" },
  { board_id: "US.LIST2521", plate_type: "CONCEPT", board_name: "IDC概念", board_code: "US.LIST2521" },
  { board_id: "US.LIST2540", plate_type: "CONCEPT", board_name: "云计算服务商", board_code: "US.LIST2540" },
  { board_id: "US.LIST2653", plate_type: "CONCEPT", board_name: "机器人概念股", board_code: "US.LIST2653" },
  { board_id: "US.LIST23590", plate_type: "CONCEPT", board_name: "智能驾驶概念股", board_code: "US.LIST23590" },
  { board_id: "US.LIST2583", plate_type: "CONCEPT", board_name: "核电", board_code: "US.LIST2583" },
  { board_id: "US.LIST2089", plate_type: "INDUSTRY", board_name: "航空航天与国防", board_code: "US.LIST2089" },
  { board_id: "US.LIST2450", plate_type: "CONCEPT", board_name: "光伏太阳能", board_code: "US.LIST2450" },
  { board_id: "US.LIST2552", plate_type: "CONCEPT", board_name: "锂电池", board_code: "US.LIST2552" },
  { board_id: "US.LIST2582", plate_type: "CONCEPT", board_name: "天然气", board_code: "US.LIST2582" },
  { board_id: "US.LIST2110", plate_type: "INDUSTRY", board_name: "黄金", board_code: "US.LIST2110" },
  { board_id: "US.LIST23700", plate_type: "CONCEPT", board_name: "稀土概念", board_code: "US.LIST23700" },
  { board_id: "US.LIST2136", plate_type: "CONCEPT", board_name: "人工智能", board_code: "US.LIST2136" },
  { board_id: "US.LIST2548", plate_type: "CONCEPT", board_name: "AI芯片", board_code: "US.LIST2548" },
  { board_id: "US.LIST23979", plate_type: "CONCEPT", board_name: "光通信", board_code: "US.LIST23979" },
  { board_id: "US.LIST2556", plate_type: "CONCEPT", board_name: "太空概念", board_code: "US.LIST2556" },
  { board_id: "US.LIST2472", plate_type: "INDUSTRY", board_name: "受监管电力", board_code: "US.LIST2472" },
  { board_id: "US.LIST2572", plate_type: "CONCEPT", board_name: "可再生能源", board_code: "US.LIST2572" },
  { board_id: "US.LIST2224", plate_type: "INDUSTRY", board_name: "综合油气", board_code: "US.LIST2224" },
  { board_id: "US.LIST2510", plate_type: "INDUSTRY", board_name: "铜", board_code: "US.LIST2510" },
  { board_id: "US.LIST2481", plate_type: "INDUSTRY", board_name: "多元化银行", board_code: "US.LIST2481" },
  { board_id: "US.LIST2069", plate_type: "INDUSTRY", board_name: "生物技术", board_code: "US.LIST2069" },
  { board_id: "US.LIST2003", plate_type: "INDUSTRY", board_name: "家庭和个人用品", board_code: "US.LIST2003" },
] as const;

export type FutuNativeBoardRow = {
  board_id: string;
  plate_type: "INDUSTRY" | "CONCEPT";
  board_name: string;
  board_code: string;
  metric_kind: "OFFICIAL_BOARD";
  market: "US";
  expected_board_name: string;
  update_time: string | null;
  session_date: string | null;
  timezone: string;
  last: number | null;
  previous_close: number | null;
  change_pct: number | null;
  plate_valid: boolean | null;
  rise_count: number | null;
  fall_count: number | null;
  equal_count: number | null;
  membership_status: "READY" | "CANNOT_CONFIRM";
  member_count: number | null;
  membership_sha256: string;
  membership_cannot_confirm: string[];
  source_response_sha256: string;
  status: "READY" | "CANNOT_CONFIRM";
  cannot_confirm: string[];
};

export type FutuNativeBoardSnapshot = {
  schema_version: "v3_5.futu_us_native_board_snapshot.v2";
  registry_version: string;
  registry_sha256: string;
  provider: string;
  market: "US";
  timezone: string;
  capture_session_date: string;
  source_response_sha256: string;
  requested_board_count: number;
  available_board_count: number;
  status: GlobalIndustryStatus;
  rows: FutuNativeBoardRow[];
  cannot_confirm: string[];
  membership_cannot_confirm: string[];
  RESEARCH_ONLY: true;
  production_allowed: false;
  buy_gate_updated: false;
  orders_sent: false;
};
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
  metric_kind: "OFFICIAL_BOARD";
  official_board: {
    metric_kind: "OFFICIAL_BOARD";
    market?: "US";
    plate_type?: string | null;
    board_name: string | null;
    expected_board_name?: string | null;
    board_code: string | null;
    update_time: string | null;
    session_date: string | null;
    timezone: string;
    last: number | null;
    previous_close: number | null;
    change_pct: number | null;
    plate_valid: boolean | null;
    rise_count: number | null;
    fall_count: number | null;
    equal_count: number | null;
    member_count?: number | null;
    membership_cannot_confirm?: string[];
    relation_constituents?: string[];
    membership_status?: string;
    relations: Array<{
      us_symbol: string;
      hk_symbol: string;
      relationship_type: string;
      direction: string;
      reason?: string;
      maturity?: string;
      available_at?: string;
      sources: Array<{ role?: string; title?: string; url: string; published_at?: string; retrieved_at?: string }>;
      limitations: string[];
    }>;
    relation_status: string;
    relation_cannot_confirm?: string[];
    target_date_eligibility?: string;
    cannot_confirm: string[];
  };
  proxy_reference: {
    metric_kind: "ETF_REFERENCE" | "STOCK_BASKET_REFERENCE";
    provider: string;
    mapping_type: string;
    proxy_symbols: string[];
    available_symbols: string[];
    missing_symbols: string[];
    requested_symbol_count: number;
    available_symbol_count: number;
    coverage: { available: number; requested: number };
    coverage_pct: number | null;
    change_pct: number | null;
    direction: GlobalIndustryDirection;
    status: GlobalIndustryStatus;
    quote_session_dates: string[];
    quote_session_times: string[];
    cannot_confirm: string[];
  };
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
  capture_session_date: string;
  provider: string;
  provider_url?: string;
  provider_session_dates: string[];
  provider_session_times: string[];
  source_response_sha256: string;
  quotes: GlobalIndustryQuote[];
  proxy_quotes?: GlobalIndustryQuote[];
  proxy_source_response_sha256?: string;
  legacy_proxy_status?: GlobalIndustryStatus;
  legacy_proxy_provider?: string;
  futu_board_snapshot: {
    schema_version?: string;
    status: GlobalIndustryStatus;
    provider?: string;
    market?: "US";
    timezone?: string;
    capture_session_date?: string;
    source_response_sha256: string;
    cannot_confirm: string[];
  };
  native_board_snapshot?: FutuNativeBoardSnapshot | null;
  native_display_status?: GlobalIndustryStatus | "STALE" | null;
  native_freshness?: {
    state?: string;
    cannot_confirm?: string[];
  };
  relation_evidence: {
    status: string;
    evidence_path?: string;
    evidence_sha256?: string;
    review_path?: string;
    review_sha256?: string;
    reviewed_at?: string;
    reviewer_identity?: string;
    limitations: string[];
    cannot_confirm: string[];
    target_date_eligibility: "CANNOT_CONFIRM";
  };
  hk_relation_status: string;
  a_share_relation_status: string;
  a_share_relations: unknown[];
  target_date_eligibility: "CANNOT_CONFIRM";
  requested_board_count: number;
  available_board_count: number;
  proxy_requested_symbol_count: number;
  proxy_available_symbol_count: number;
  proxy_provider_session_dates: string[];
  proxy_provider_session_times: string[];
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
