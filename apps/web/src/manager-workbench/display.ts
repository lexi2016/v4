import type { Decision, Lane, LaneDecision, ReviewMetric, StockDecision, StockDetails, StockLaneDetail } from "./types";
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
  if (value === "NOT_IN_PLAN") return "计划未覆盖";
  return value && value in DECISION_LABELS ? DECISION_LABELS[value as Decision] : (value || "未知");
}
/** B's lane_decisions is a per-lane array; preserve its recorded order and
 * each decision independently. Do not rank, collapse or derive a stock decision. */
export function laneEntries(stock: StockDecision, lane: Lane): LaneDecision[] {
  const raw = stock.lane_decisions?.[lane];
  if (Array.isArray(raw)) {
    return raw.filter((entry): entry is LaneDecision =>
      entry !== null && typeof entry === "object" && !Array.isArray(entry));
  }
  return raw !== null && typeof raw === "object" && !Array.isArray(raw) ? [raw] : [];
}
export function laneResultLabel(stock: StockDecision, lane: Lane): string {
  const entries = laneEntries(stock, lane);
  if (!entries.length) return "待核 / 未提供";
  return entries.map(x => decisionLabel(x.decision || x.status || null)).join("、");
}
export function firstReason(stock: StockDecision): string {
  return stock.reasons?.find(x => typeof x === "string" && x.trim().length > 0) || "暂无可核验理由";
}
export function metricLabel(metric: ReviewMetric | null | undefined, completeTop20 = true): string {
  if (!metric) return completeTop20 ? "缺数据" : "不适用（缺完整Top20）";
  if (metric.denominator === 0) return "不适用（分母为0）";
  if (!completeTop20) return "不适用（缺完整Top20）";
  const ratio = metric.ratio;
  if (typeof ratio !== "number" || !Number.isFinite(ratio) || ratio < 0 || ratio > 1) {
    return "未知（未提供有效覆盖率）";
  }
  // Render B's recorded ratio only; never infer it from covered / denominator.
  const percent = (ratio * 100).toFixed(2).replace(/\.?0+$/, "");
  return percent + "%";
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


function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
}
function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}
function texts(value: unknown): string[] {
  return Array.isArray(value) ? value.map(text).filter(Boolean) : [];
}
export function stockTitle(stock: StockDecision): string {
  return [stock.symbol, text(stock.name)].filter(Boolean).join(" ");
}
/** Prefer the actual saved source rows; do not display their mirrored decisions twice. */
export function researchRows(stock: StockDecision, lane: Lane, detail?: StockLaneDetail): Record<string, unknown>[] {
  return detail?.rows?.length ? detail.rows : laneEntries(stock, lane);
}
export function readableReason(row: Record<string, unknown>): string {
  const reason = text(record(row.semantic).reason) || text(row.reason);
  return /^[A-Z][A-Z0-9_]+$/.test(reason) ? "未提供可读研究理由" : reason || "未提供可读研究理由";
}
export function researchSections(row: Record<string, unknown>) {
  const semantic = record(row.semantic);
  return ([['facts', '已核事实'], ['changes', '变化'], ['impact', '影响'],
    ['confirmation_conditions', '待确认条件'], ['counter_evidence', '反证']] as const).map(([key, label]) => {
      const raw = semantic[key];
      const items = Array.isArray(raw) ? raw.map(part => {
        const value = record(part);
        return { claim: text(value.claim) || text(part), quote: text(value.quote), locator: text(value.locator) };
      }).filter(part => part.claim || part.quote) : [];
      if (key === 'confirmation_conditions' && !items.length) {
        items.push(...texts(row.conditions).map(claim => ({ claim, quote: '', locator: '' })));
      }
      return { key, label, items };
    });
}
export function researchRisks(row: Record<string, unknown>): string[] {
  return [...new Set([...texts(record(row.semantic).risk_notes), ...texts(row.risks)])];
}
export function detailReasons(detail: StockDetails): string[] {
  const recorded = detail.lane_details.flatMap(source => researchRows(detail.stock, source.lane, source)
    .filter(row => text(record(row.semantic).reason))
    .map(row => `${LANE_LABELS[source.lane]}：${readableReason(row)}`));
  return recorded.length ? [...new Set(recorded)] : texts(detail.stock.reasons);
}
export function detailRisks(detail: StockDetails): string[] {
  return [...new Set([...texts(detail.stock.risks), ...detail.lane_details.flatMap(source =>
    researchRows(detail.stock, source.lane, source).flatMap(row => researchRisks(row)
      .map(risk => `${LANE_LABELS[source.lane]}：${risk}`)))])];
}
