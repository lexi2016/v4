export const SINGLE_STOCK_REPAIR_SOP_PATH =
  "/Users/lexi/Desktop/学习/因子工厂/research/a_share_local_panel_completion_20261024/SOP_SINGLE_STOCK_REPAIR.md";

export interface SingleStockRepairSopResult {
  schema_version: "v4.research.single_stock_repair_sop.v1";
  status: "READY" | "CANNOT_CONFIRM";
  content?: string | null;
  content_type?: "text/markdown; charset=utf-8";
  source: { path: string; sha256: string | null; size_bytes?: number };
  cannot_confirm: string[];
  write_policy: "read_only";
  RESEARCH_ONLY: true;
  production_allowed: false;
  buy_gate_updated: false;
  orders_sent: false;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function invalidResponse(reason: string): never {
  throw new Error(`研究面板更新 SOP 响应不匹配：${reason}`);
}

export function validateSingleStockRepairSopResponse(value: unknown): SingleStockRepairSopResult {
  if (!isRecord(value)) invalidResponse("body must be an object");
  if (value.schema_version !== "v4.research.single_stock_repair_sop.v1") invalidResponse("schema_version");
  if (value.status !== "READY" && value.status !== "CANNOT_CONFIRM") invalidResponse("status");
  if (value.write_policy !== "read_only" || value.RESEARCH_ONLY !== true) invalidResponse("research boundary");
  if (value.production_allowed !== false || value.buy_gate_updated !== false || value.orders_sent !== false) {
    invalidResponse("safety flags");
  }
  if (!Array.isArray(value.cannot_confirm) || !value.cannot_confirm.every((item) => typeof item === "string")) {
    invalidResponse("cannot_confirm");
  }
  if (!isRecord(value.source) || value.source.path !== SINGLE_STOCK_REPAIR_SOP_PATH) invalidResponse("source path");
  if (value.source.sha256 !== null
    && (typeof value.source.sha256 !== "string" || !/^[0-9a-f]{64}$/.test(value.source.sha256))) {
    invalidResponse("source sha256");
  }

  if (value.status === "READY") {
    if (typeof value.content !== "string" || value.content_type !== "text/markdown; charset=utf-8"
      || typeof value.source.sha256 !== "string") {
      invalidResponse("ready content");
    }
  } else if (value.content !== null) {
    invalidResponse("CANNOT_CONFIRM must not contain SOP content");
  }

  return value as unknown as SingleStockRepairSopResult;
}

export async function loadSingleStockRepairSop(): Promise<SingleStockRepairSopResult> {
  const response = await fetch("/api/v4/research/single-stock-repair-sop", { cache: "no-store" });
  if (!response.ok) throw new Error(`研究面板更新 SOP 读取失败：HTTP ${response.status}`);
  return validateSingleStockRepairSopResponse(await response.json());
}
