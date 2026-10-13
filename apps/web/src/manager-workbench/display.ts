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
/** These are presentation projections of already persisted source fields.
 * No disposition, eligibility, evidence or selection outcome is calculated. */
export type ResearchLane = "ANNOUNCEMENT" | "US_MAPPING" | "OVERSOLD";
export interface ResearchNote {
  lane: ResearchLane | null;
  text: string;
}
export type SemanticField = "facts" | "changes" | "impact" | "confirmation_conditions" | "counter_evidence";
export interface SemanticCitation {
  claim: string;
  quote: string | null;
  locator: string | null;
}
export interface SemanticSection {
  field: SemanticField;
  title: string;
  citations: SemanticCitation[];
}
const SEMANTIC_TITLES: ReadonlyArray<{ field: SemanticField; title: string }> = [
  { field: "facts", title: "事实与原文" },
  { field: "changes", title: "相对变化" },
  { field: "impact", title: "经营影响" },
  { field: "confirmation_conditions", title: "确认条件" },
  { field: "counter_evidence", title: "反证与限制" }
];
const RESEARCH_LANES: readonly ResearchLane[] = ["ANNOUNCEMENT", "US_MAPPING", "OVERSOLD"];

function savedText(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value : null;
}
function isPlainObject(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}
/** A announcement.py:_analyze_one persists the Reader's business record at
 * lane_decisions.ANNOUNCEMENT[*].semantic. Never parse JSON string payloads
 * or infer missing claims from article titles or status codes. */
export function semanticFor(entry: LaneDecision): Record<string, unknown> | null {
  return isPlainObject(entry.semantic) ? entry.semantic : null;
}
export function semanticSections(entry: LaneDecision): SemanticSection[] {
  const semantic = semanticFor(entry);
  if (!semantic) return [];
  return SEMANTIC_TITLES.flatMap(({field, title}) => {
    const values = semantic[field];
    if (!Array.isArray(values)) return [];
    const citations = values.flatMap((value): SemanticCitation[] => {
      if (!isPlainObject(value)) return [];
      const claim = savedText(value.claim);
      if (!claim) return [];
      return [{ claim, quote: savedText(value.quote), locator: savedText(value.locator) }];
    });
    return citations.length ? [{ field, title, citations }] : [];
  });
}
function savedSemanticNotes(stock: StockDecision, key: "reason" | "risk_notes"): ResearchNote[] {
  const notes: ResearchNote[] = [];
  for (const lane of RESEARCH_LANES) {
    for (const entry of laneEntries(stock, lane)) {
      const semantic = semanticFor(entry);
      if (!semantic) continue;
      if (key === "reason") {
        const text = savedText(semantic.reason);
        if (text) notes.push({ lane, text });
      } else if (Array.isArray(semantic.risk_notes)) {
        for (const value of semantic.risk_notes) {
          const text = savedText(value);
          if (text) notes.push({ lane, text });
        }
      }
    }
  }
  return notes;
}
function isMachineTag(value: string): boolean {
  // Status identifiers such as ANNOUNCEMENT_NOT_SELECTED belong in audit,
  // not in a card labelled "research reason".
  return /^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$/.test(value);
}
export function researchReasons(stock: StockDecision): ResearchNote[] {
  const semantic = savedSemanticNotes(stock, "reason");
  if (semantic.length) return semantic;
  return (stock.reasons || [])
    .filter((x): x is string => typeof x === "string" && !!x.trim() && !isMachineTag(x))
    .map(text => ({ lane: null, text }));
}
export function researchRisks(stock: StockDecision): ResearchNote[] {
  const semantic = savedSemanticNotes(stock, "risk_notes");
  // A's merge takes row.risks; it does not lift semantic.risk_notes.
  // Preserve both sources, without repeating the identical summary text.
  const known = new Set(semantic.map(item => item.text));
  const other = (stock.risks || [])
    .filter((x): x is string => typeof x === "string" && !!x.trim() && !known.has(x))
    .map(text => ({ lane: null, text }));
  return [...semantic, ...other];
}
export function firstReason(stock: StockDecision): string {
  const first = researchReasons(stock)[0];
  if (!first) return "未提供具体研究理由";
  return first.lane ? LANE_LABELS[first.lane] + "：" + first.text : first.text;
}
export function stockAccessibleName(stock: Pick<StockDecision, "symbol" | "name">): string {
  const name = typeof stock.name === "string" ? stock.name.trim() : "";
  return name ? stock.symbol + " " + name : stock.symbol;
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
