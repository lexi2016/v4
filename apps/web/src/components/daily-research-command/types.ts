import type {
  ResearchDayProduct,
  ResearchEvidenceRow,
  ResearchHourlyProduct,
  ResearchMentionPair,
  ResearchStockRollup,
} from "../../contracts/research";

export const DAILY_RESEARCH_SLOTS = [
  "1000",
  "1100",
  "1200",
  "1300",
  "1400",
  "1500",
  "1600",
  "1700",
] as const;

export type DailyResearchCommandState =
  | "NO_DATE_SELECTED"
  | "LOADING"
  | "READY"
  | "READY_WITH_DECLARED_GAPS"
  | "NOT_MATERIALIZED"
  | "CANNOT_CONFIRM"
  | "STALE"
  | "REJECTED"
  | "ERROR";

export const DAILY_RESEARCH_ORIGINS = [
  "NATURAL",
  "AUTO_RETRY",
  "MANUAL_RECOVERY",
] as const;

export type DailyResearchOrigin = (typeof DAILY_RESEARCH_ORIGINS)[number];

export const DAILY_RESEARCH_SAFETY_KEYS = [
  "RESEARCH_ONLY",
  "production_allowed",
  "buy_gate_updated",
  "orders_sent",
] as const;

export type DailyResearchSafetyKey = (typeof DAILY_RESEARCH_SAFETY_KEYS)[number];
export type DailyResearchSafetyValues = Partial<Record<DailyResearchSafetyKey, unknown>>;

export type DailyResearchAlert = {
  alert_id?: string;
  severity?: string;
  code?: string;
  status?: string;
  message?: string;
  slot?: string | null;
  blocks_publish?: boolean;
  blocks_consumer?: boolean;
};

export type DailyResearchHourlyDiagnostic = Pick<
  ResearchHourlyProduct,
  "endpoint_mode" | "slot" | "row_count" | "is_full_day"
>;

export type DailyResearchPayload = ResearchDayProduct & {
  execution_origin?: "NATURAL" | "AUTO_RETRY" | "MANUAL_RECOVERY";
  alerts?: DailyResearchAlert[];
  hourly_latest?: DailyResearchHourlyDiagnostic;
  requested_date?: string | null;
  resolved_date?: string | null;
  evidence_rows: ResearchEvidenceRow[];
  mention_pairs: ResearchMentionPair[];
  stock_rollups: ResearchStockRollup[];
};

export type DailyResearchSlotRow = {
  slot: string;
  status: string;
  raw_rows: number;
  exact_rows: number;
  excluded_rows: number;
  artifact_path?: string;
  artifact_sha256?: string;
  receipt_path?: string;
  receipt_sha256?: string;
  source_input_sha256?: string;
};

export type DailyResearchLineageLayer = {
  name: string;
  status: "VALIDATED" | "CANNOT_CONFIRM";
  detail: string;
};
