import type { MarketSummary, PoolGroup, PoolRow, ReviewMetric, StageRow } from "./types";

export function poolRows(group: PoolGroup) {
  return group.rows ?? [];
}
export function poolEvidenceReason(group: PoolGroup) {
  const item = group.cannot_confirm?.[0];
  if (typeof item === "string") return item;
  return item?.reason || item?.description || "";
}
export function poolEvidenceDetails(group: PoolGroup) {
  const items = group.cannot_confirm ?? [];
  return group.status && poolEvidenceReason(group) ? items.slice(1) : items;
}
export function poolRowCode(row: PoolRow) {
  return row.symbol || row.code || "WATCH_ONLY";
}
export function poolRowName(row: PoolRow) {
  return row.display_name || row.stock_name || row.name || poolRowCode(row);
}
export function poolMetadataText(value?: string | string[]) {
  return Array.isArray(value) ? value.filter(Boolean).join(" / ") : value || "";
}
export function poolRowSource(row: PoolRow, group: PoolGroup) {
  return poolMetadataText(row.source_tags)
    || row.source_label
    || row.source_tag
    || poolMetadataText(row.source_lanes)
    || group.producer_id
    || group.status
    || "来源状态未提供";
}
export function poolRowSourceLane(row: PoolRow) {
  return poolMetadataText(row.source_lanes);
}
export function poolCountLabel(group: PoolGroup) {
  const total = group.pool_size ?? group.rows?.length ?? 0;
  const returned = group.returned_rows
    ?? (group.pool_id === "a_all_pool_summary" ? group.rows?.length ?? 0 : total);
  const status = (group.status || "").trim().toUpperCase();
  const cannotConfirm = group.complete === false
    || ["CANNOT_CONFIRM", "NOT_MATERIALIZED", "MISSING", "DATA_BLOCKED_EMPTY", "FAILED", "ERROR"].includes(status);
  if (cannotConfirm && returned === 0) return "未生成/待补齐";
  if (cannotConfirm) return `当前显示 ${returned} / 共 ${total} 条（待补齐）`;
  // A zero-row pool is complete only when the producer explicitly declares
  // completion.  An empty shape without that evidence is a missing source.
  if (total === 0 && returned === 0 && group.complete !== true) return "未生成/待补齐";
  return returned < total ? `当前显示 ${returned} / 共 ${total} 条` : `完整 ${total} 条`;
}
export function poolRowSignalDate(row: PoolRow) {
  return row.signal_date
    || row.source_date
    || row.article_publish_date
    || row.publish_date
    || row.effective_trade_date
    || row.target_date
    || row.trade_date
    || "该池未提供信号日";
}

export function formatPercent(value?: number) {
  return typeof value === "number" ? `${value.toFixed(3).replace(/\.?0+$/, "")}%` : "阶段行情未生成";
}

export function assertExactResponseDate(
  payload: unknown,
  requestedDate: string,
  fields: readonly string[],
  label: string,
) {
  if (!payload || typeof payload !== "object") {
    throw new Error(`${label}日期证据错误：响应不是对象，未展示该响应。`);
  }
  const record = payload as Record<string, unknown>;
  const presentFields = fields.filter((field) => Object.prototype.hasOwnProperty.call(record, field));
  if (!presentFields.length) {
    throw new Error(`${label}日期证据错误：响应缺少 ${fields.join("/")}，未展示该响应。`);
  }
  const mismatch = presentFields.find((field) => record[field] !== requestedDate);
  if (mismatch) {
    throw new Error(`${label}日期证据错误：响应 ${mismatch}=${String(record[mismatch])}，请求=${requestedDate}，未展示该响应。`);
  }
}

export function assertExactStagePayload(payload: unknown, requestedDate: string, stage: string) {
  assertExactResponseDate(payload, requestedDate, ["trade_date"], "阶段工作台");
  if (!payload || typeof payload !== "object") throw new Error("阶段工作台响应不是对象。");
  const record = payload as Record<string, unknown>;
  const stageRecord = record.stage;
  if (!stageRecord || typeof stageRecord !== "object" || (stageRecord as Record<string, unknown>).stage_id !== stage) {
    throw new Error(`阶段工作台阶段证据错误：请求=${stage}。`);
  }
}

export function formatDateInput(value: string) {
  return /^\d{8}$/.test(value)
    ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`
    : "";
}
export function compactDateInput(value: string) {
  return value.replaceAll("-", "");
}
export function evidenceValue(value?: number | string) {
  return value === undefined || value === null || value === "" ? "该字段未在当前阶段生成" : value;
}
export function rowCode(row: StageRow) {
  return row.code || row.symbol || row.stock_code || "WATCH_ONLY";
}
export function rowName(row: StageRow) {
  return row.name || row.stock_name || rowCode(row);
}
export function rowRank(row: StageRow) {
  return row.rank ?? row.stage_rank ?? row.pool_rank ?? "-";
}
export function aShareChangePct(row: StageRow) {
  if (typeof row.current_change_pct === "number") return row.current_change_pct;
  if (typeof row.d1_change_pct === "number") return row.d1_change_pct;
  if (
    typeof row.open_price === "number"
    && row.open_price !== 0
    && typeof row.last_price === "number"
  ) {
    return (row.last_price / row.open_price - 1) * 100;
  }
  return undefined;
}
export function rowSupport(row: StageRow) {
  return row.support_primary_price ?? row.low_price;
}
export function rowPressure(row: StageRow) {
  return row.pressure_price ?? row.high_price;
}
export function rowInvalidation(row: StageRow) {
  return row.invalidation_price ?? row.low_price;
}
export function rowNextEvidence(row: StageRow) {
  return row.next_validation_time || row.source_last_bar_time || "";
}
export function rowScore(row: StageRow) {
  const value = row.score ?? row.stage_score ?? row.stage_rtdata_score;
  return typeof value === "number" ? Number(value.toFixed(3)) : value ?? "阶段分未在当前阶段生成";
}
export function qualityScore(value?: number) {
  return typeof value === "number" ? Number(value.toFixed(3)) : "该时段未提供";
}
export function stageCountText(value?: number | null) {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "—";
}
export function stageMarketCountText(summary: MarketSummary | undefined, selectedRows?: number | null) {
  if (summary?.display_mode === "CANNOT_CONFIRM") return "待确认/缺少正式产物";
  if (summary?.display_mode === "OBSERVATION_UNVERIFIED") {
    return `${stageCountText(summary.observation_count)} 条观察行 · 未验证`;
  }
  if (summary?.display_mode === "READY_EMPTY") return "0 条 · 正式空结果已验证";
  return stageCountText(selectedRows);
}
export function is0920D1ReferenceRow(row: StageRow) {
  return row.source_mode === "HK_CONNECT_D1_PRESELECT_REFERENCE"
    && row.status === "WAITING_0920_SECOND_FILTER";
}
export function hkChangeLabel(row: StageRow) {
  return typeof row.d1_change_pct === "number" ? "D-1涨幅" : "阶段涨幅";
}
export function rowMissingFields(row: StageRow) {
  const missing: string[] = [];
  if (typeof row.d1_change_pct !== "number" && typeof row.current_change_pct !== "number") missing.push("涨幅");
  if (row.score == null && row.stage_score == null && row.stage_rtdata_score == null) missing.push("二筛分");
  if (row.support_primary_price == null || row.support_primary_price === "") missing.push("支撑位");
  if (row.pressure_price == null || row.pressure_price === "") missing.push("压力位");
  if (row.invalidation_price == null || row.invalidation_price === "") missing.push("失效位");
  if (!row.next_validation_time) missing.push("下次验证");
  return missing;
}
export function hitTop20(metric: ReviewMetric) {
  return typeof metric.hit_count === "number" ? `${metric.hit_count}/20` : "不可用";
}
export function reviewClassification(value?: string) {
  return ({
    shared: "共同命中",
    model_only: "仅0.2",
    stage_only: "仅阶段",
    missed: "漏掉Top20",
  } as Record<string, string>)[value || ""] || value || "不可确认";
}
