import type { Decision, Lane, LaneDecision, ReviewMetric, StockDecision } from "./types";
import { DECISION_LABELS, LANE_LABELS, showText } from "./types";

export function humanTime(value: string | null | undefined): string {
  if (!value) return "未知";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Hong_Kong", year: "numeric", month: "2-digit",
    day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false
  }).format(date) + " 香港时间";
}
export function decisionLabel(value: Decision | string | null | undefined): string {
  return value && value in DECISION_LABELS ? DECISION_LABELS[value as Decision] : (value || "未知");
}
export function laneDecision(stock: StockDecision, lane: Lane): LaneDecision | null {
  return stock.lane_decisions?.[lane] || null;
}
export function laneResultLabel(stock: StockDecision, lane: Lane): string {
  const raw = laneDecision(stock, lane);
  if (!raw) return "待核 / 未提供";
  return decisionLabel(raw.decision || raw.status || "");
}
export function firstReason(stock: StockDecision): string {
  return stock.reasons?.find(x => typeof x === "string" && x.trim().length > 0) || "暂无可核验理由";
}
export function metricLabel(metric: ReviewMetric | null | undefined, completeTop20 = true): string {
  if (!completeTop20) return "不适用（缺完整Top20）";
  if (!metric) return "缺数据";
  if (metric.denominator === 0) return "不适用（分母为0）";
  if (metric.display) return metric.display;
  if (metric.rate === null || metric.rate === undefined) return "未知（未提供覆盖率）";
  if (typeof metric.rate !== "number" || !Number.isFinite(metric.rate)) return "未知";
  // B owns the rate. Display its value as sent; never recompute numerator/denominator.
  return showText(metric.rate);
}
export function labelForLane(value: string): string {
  return value in LANE_LABELS ? LANE_LABELS[value as Lane] : value;
}
export function evidenceLink(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.toString() : null;
  } catch { return null; }
}
