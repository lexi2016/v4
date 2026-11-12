export const POSITION25_ASOF = "20261023";
export const POSITION25_CODES = [
  "000156.SZ",
  "000690.SZ",
  "000810.SZ",
  "000902.SZ",
  "000999.SZ",
  "002223.SZ",
  "002273.SZ",
  "002568.SZ",
  "002833.SZ",
  "300033.SZ",
  "600000.SH",
  "600019.SH",
  "600028.SH",
  "600114.SH",
  "600398.SH",
  "600499.SH",
  "600566.SH",
  "600571.SH",
  "600785.SH",
  "600814.SH",
  "600863.SH",
  "600886.SH",
  "600887.SH",
  "600987.SH",
  "601225.SH",
] as const;

export interface Position25Source {
  artifact: string;
  sha256: string;
  binding_sha256: string;
  generation: string;
  asof: string;
}

export interface Position25Result {
  schema_version: "v4.research.zero_to_history_high_position.v1";
  status: "READY" | "CANNOT_CONFIRM";
  ts_code: string;
  stock_name?: string;
  asof: string;
  source_asof: string;
  field: "zero_to_history_high_position_pct";
  zero_to_history_high_position_pct: number | null;
  basis: "QFQ_ASOF" | null;
  formula: string;
  metric_kind: string;
  history_scope: string;
  summary: string;
  source: Position25Source;
  cannot_confirm: string[];
  write_policy: "read_only";
  RESEARCH_ONLY: true;
  production_allowed: false;
  buy_gate_updated: false;
  orders_sent: false;
}

const POSITION_CSV_SHA256 = "d8d61cc9583eea726c4c2f3b4d0705b2caf4af62d74ffa59eebec243688944b7";
const SOURCE_BINDINGS_SHA256 = "a5e48f4d933b9ba43b1b33834be08c64c6e49bada24df1efea479b9e1ca273ed";
const SOURCE_GENERATION = "f3c4ce582565e4fb431766fd51c02233654e7d384240b7279154ea32691d7104";
const POSITION_FIELD = "zero_to_history_high_position_pct";

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function invalidResponse(message: string): never {
  throw new Error(`25股位置字段响应不匹配：${message}`);
}

export function validatePosition25Response(
  value: unknown,
  tsCode: string,
  asof: string,
): Position25Result {
  if (!isRecord(value)) invalidResponse("body must be an object");
  if (value.schema_version !== "v4.research.zero_to_history_high_position.v1") {
    invalidResponse("schema_version");
  }
  if (value.status !== "READY" && value.status !== "CANNOT_CONFIRM") invalidResponse("status");
  if (value.ts_code !== tsCode || value.asof !== asof) invalidResponse("request identity");
  if (value.source_asof !== POSITION25_ASOF || value.field !== POSITION_FIELD) {
    invalidResponse("frozen source identity");
  }
  if (value.write_policy !== "read_only" || value.RESEARCH_ONLY !== true) invalidResponse("research boundary");
  for (const flag of ["production_allowed", "buy_gate_updated", "orders_sent"]) {
    if (value[flag] !== false) invalidResponse(flag);
  }
  if (!Array.isArray(value.cannot_confirm) || !value.cannot_confirm.every((item) => typeof item === "string")) {
    invalidResponse("cannot_confirm");
  }
  if (!isRecord(value.source)
    || value.source.artifact !== "25_ZERO_FLOOR_HIGH_POSITION.csv"
    || value.source.sha256 !== POSITION_CSV_SHA256
    || value.source.binding_sha256 !== SOURCE_BINDINGS_SHA256
    || value.source.generation !== SOURCE_GENERATION
    || value.source.asof !== POSITION25_ASOF) {
    invalidResponse("source binding");
  }

  if (value.status === "READY") {
    if (value.basis !== "QFQ_ASOF" || typeof value.zero_to_history_high_position_pct !== "number"
      || !Number.isFinite(value.zero_to_history_high_position_pct)
      || value.zero_to_history_high_position_pct < 0) {
      invalidResponse("position value");
    }
  } else if (value.zero_to_history_high_position_pct !== null) {
    invalidResponse("CANNOT_CONFIRM must not contain a position value");
  }

  return value as unknown as Position25Result;
}

export async function loadPosition25Exact(tsCode: string, asof = POSITION25_ASOF): Promise<Position25Result> {
  const query = new URLSearchParams({ ts_code: tsCode, asof });
  const response = await fetch(`/api/v4/research/zero-to-history-high-position?${query.toString()}`);
  if (!response.ok) {
    throw new Error(`25股位置字段读取失败：HTTP ${response.status}`);
  }
  return validatePosition25Response(await response.json(), tsCode, asof);
}
