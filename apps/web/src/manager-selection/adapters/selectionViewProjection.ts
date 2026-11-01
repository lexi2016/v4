/**
 * Projection helpers for the manager selection view.
 *
 * Pure functions and constants only: nothing here reads component state or
 * writes a binding, so the view keeps the reactive wiring and this module
 * keeps formatting and projection.
 */

import { ANNOUNCEMENT_PREOPEN_WINDOW } from "../../api/managerAnnouncementAnalysis";
import { ManagerResearchResponse } from "../../api/managerResearch";
import { ManagerDecisionRole, ManagerDecisionRow } from "../../contracts/managerDecision";
import { ManagerPreselectionRow, normalizeManagerHkCode } from "../../contracts/managerPreselection";
import { ManagerStageSelectionRow } from "../../contracts/managerStageSelection";
import { ManagerWorkbenchCandidate, ManagerWorkbenchResearchResponse, ManagerWorkbenchSourceRef } from "../../contracts/managerWorkbenchResearch";
import { SelectionCandidate, SelectionPhase, SelectionProduct, SelectionSourceRef, validateSelectionProduct } from "../../contracts/selection";
import { ManagerPriorityRow } from "./priority";
import { StageReasonContributionDetail, StageReasonEvidenceRef } from "./stageReasonContributions";
import { readableStatus } from "./workbenchPresentation";



export type ViewState =
  | "NO_DATE_SELECTED"
  | "LOADING"
  | "READY"
  | "READY_WITH_DECLARED_GAPS"
  | "RESEARCH_SUPPLY_IMPORTED"
  | "EARLY_DRAFT_IMPORTED"
  | "NOT_MATERIALIZED"
  | "CANNOT_CONFIRM"
  | "STALE"
  | "ERROR"
  | "REJECTED";



export type AuxiliaryState =
  | "IDLE"
  | "LOADING"
  | "READY"
  | "NOT_MATERIALIZED"
  | "CANNOT_CONFIRM"
  | "QUEUED"
  | "RUNNING"
  | "FAILED"
  | "PARTIAL_WITH_ROWS";



export const VALID_PRODUCT_STATUSES = new Set([
  "EARLY_DRAFT_IMPORTED",
  "RESEARCH_SUPPLY_IMPORTED",
  "READY",
  "READY_WITH_DECLARED_GAPS",
  "NOT_MATERIALIZED",
  "CANNOT_CONFIRM",
]);



export const MATERIALIZED_PRODUCT_STATUSES = new Set([
  "EARLY_DRAFT_IMPORTED",
  "RESEARCH_SUPPLY_IMPORTED",
  "READY",
  "READY_WITH_DECLARED_GAPS",
]);


export const PHASES: ReadonlyArray<{
  key: SelectionPhase;
  label: string;
  wireLabel?: string;
  description: string;
}> = [
  { key: "2200", label: "22:00 初始研究供给", description: "前一日晚间的研究供给与经理 delta" },
  {
    key: "0830",
    label: "08:00 第二版",
    wireLabel: "协议槽 08:30",
    description: "盘前第二版冻结；时间映射必须保留不确定性",
  },
  { key: "0935", label: "09:35 开盘后观察", description: "仅追加观察，不改写 08:30 冻结" },
  { key: "1620", label: "16:20 结果参考", description: "收盘后结果引用，不反证盘前逻辑" },
];


export const REQUEST_TIMEOUT_MS = 10_000;


// The event/news worker is server-owned and a healthy refresh can take about
// 167 seconds. Keep the browser attached to the existing job long enough to
// consume that result, while retaining a finite four-minute wait budget.
export const MANAGER_RESEARCH_POLL_LIMIT = 48;


export const MANAGER_RESEARCH_POLL_DELAY_MS = 5_000;


export const MANAGER_RESEARCH_POLL_TIMEOUT_MS = 240_000;



export function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}



export function isRealDate(value: string): boolean {
  if (!/^\d{8}$/.test(value)) return false;
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(4, 6));
  const day = Number(value.slice(6, 8));
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year
    && date.getUTCMonth() === month - 1
    && date.getUTCDate() === day;
}



export function compactDate(value: string): string {
  return value.replaceAll("-", "");
}



export function dateInputValue(value: string): string {
  return /^\d{8}$/.test(value)
    ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`
    : "";
}



export function parseStructuredValue(value: unknown): unknown {
  if (typeof value !== "string") return value;
  const trimmed = value.trim();
  if (!(trimmed.startsWith("{") || trimmed.startsWith("["))) return value;
  try {
    return JSON.parse(trimmed) as unknown;
  } catch {
    return undefined;
  }
}



export function isLocalStoragePath(value: string): boolean {
  const trimmed = value.trim();
  return trimmed.startsWith("/") || trimmed.startsWith("./") || trimmed.startsWith("../")
    || /^[A-Za-z]:[\\/]/.test(trimmed);
}



export function isPathField(key: string): boolean {
  const normalized = key.trim().toLowerCase();
  return normalized === "path" || normalized.endsWith("_path");
}



/** Render structured research fields without ever turning them into [object Object]. */
export function displayValue(value: unknown): string {
  const parsed = parseStructuredValue(value);
  if (parsed === undefined || parsed === null || parsed === "") return "CANNOT_CONFIRM";
  if (typeof parsed === "number" && !Number.isFinite(parsed)) return "CANNOT_CONFIRM";
  if (typeof parsed === "string" && ["NaN", "Infinity", "-Infinity"].includes(parsed.trim())) {
    return "CANNOT_CONFIRM";
  }
  if (typeof parsed === "string") {
    return isLocalStoragePath(parsed) ? "CANNOT_CONFIRM" : parsed;
  }
  if (typeof parsed === "number" || typeof parsed === "boolean") {
    return String(parsed);
  }
  if (Array.isArray(parsed)) {
    return parsed.length ? parsed.map((item) => displayValue(item)).join("；") : "CANNOT_CONFIRM";
  }
  return Object.entries(parsed as Record<string, unknown>)
    .filter(([key]) => !isPathField(key))
    .map(([key, item]) => `${key}: ${displayValue(item)}`)
    .join("；") || "CANNOT_CONFIRM";
}



export function primaryValue(value: unknown): string {
  const parsed = parseStructuredValue(value);
  if (Array.isArray(parsed)) return parsed.length ? primaryValue(parsed[0]) : "CANNOT_CONFIRM";
  const record = asRecord(parsed);
  if (record) {
    for (const key of ["summary", "title", "text", "status", "reason", "value"]) {
      if (record[key] !== undefined && record[key] !== null && record[key] !== "") {
        return displayValue(record[key]);
      }
    }
  }
  return displayValue(parsed);
}



export function candidateField(candidate: SelectionCandidate, key: string): unknown {
  return (candidate as Record<string, unknown>)[key];
}



export function candidateCode(candidate: SelectionCandidate): string {
  const code = normalizeManagerHkCode(
    candidate.normalized_code || candidate.entity_id || candidate.candidate_id?.split("|")[0],
  );
  return code ? `HK.${code}` : "CANNOT_CONFIRM";
}



export function sourceMetadata(candidate: SelectionCandidate): Record<string, unknown> | null {
  return asRecord(candidate.source_metadata);
}



export function supplyCard(candidate: SelectionCandidate): Record<string, unknown> | null {
  return asRecord(sourceMetadata(candidate)?.supply_card);
}



export function managerResearch(candidate: SelectionCandidate): Record<string, unknown> | null {
  const candidateRecord = candidate as Record<string, unknown>;
  const supply = supplyCard(candidate);
  const nested = asRecord(supply?.manager_research)
    || asRecord(supply?.primary_fact_review)
    || asRecord(candidateRecord.manager_research)
    || asRecord(candidateRecord.primary_fact_review);
  return nested;
}



export function managerReviewValue(candidate: SelectionCandidate, key: string): unknown {
  return managerResearch(candidate)?.[key];
}



export function managerReviewStatus(candidate: SelectionCandidate): string {
  const status = managerReviewValue(candidate, "status");
  return typeof status === "string" && status.trim() ? status.trim().toUpperCase() : "INSUFFICIENT_FACTS";
}



export function managerReviewBucket(candidate: SelectionCandidate): string {
  const bucket = managerReviewValue(candidate, "priority_bucket");
  return typeof bucket === "string" && bucket.trim() ? bucket.trim().toUpperCase() : "GENERIC";
}



export function managerReviewTextList(candidate: SelectionCandidate, key: string): string[] {
  const value = parseStructuredValue(managerReviewValue(candidate, key));
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => typeof item === "string" ? item.trim() : "")
    .filter((item): item is string => Boolean(item));
}



export function managerFactItems(candidate: SelectionCandidate): Array<Record<string, unknown>> {
  const value = parseStructuredValue(managerReviewValue(candidate, "official_facts"));
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => asRecord(item))
    .filter((item): item is Record<string, unknown> => Boolean(item))
    .filter((item) => typeof item.statement_cn === "string" && item.statement_cn.trim())
    .slice(0, 4);
}



export function managerFactStatement(fact: Record<string, unknown>): string {
  return typeof fact.statement_cn === "string" && fact.statement_cn.trim()
    ? fact.statement_cn.trim()
    : "CANNOT_CONFIRM";
}



export function managerThesis(candidate: SelectionCandidate): string {
  const thesis = managerReviewValue(candidate, "investment_thesis_cn");
  if (typeof thesis === "string" && thesis.trim()) return thesis.trim();
  return "当前仅保留 D-1 × 官方公告交集；经营桥接待核实，需结合目标日盘面确认。";
}



export function managerCounterevidence(candidate: SelectionCandidate): string[] {
  return managerReviewTextList(candidate, "counterevidence_cn");
}



export function managerInvalidations(candidate: SelectionCandidate): string[] {
  return managerReviewTextList(candidate, "invalidation_conditions");
}



export function managerConfirmations(candidate: SelectionCandidate): string[] {
  return managerReviewTextList(candidate, "confirmation_conditions");
}



export function sourceEntity(candidate: SelectionCandidate): string {
  const supply = supplyCard(candidate);
  const entity = supply?.entity ?? candidateField(candidate, "entity") ?? candidate.entity_id;
  return entity === undefined || entity === null || entity === "" ? "CANNOT_CONFIRM" : String(entity);
}



export function candidateName(candidate: SelectionCandidate): string {
  const explicit = candidate.name || candidate.stock_name || candidate.display_name;
  if (explicit) return explicit;
  const priceReaction = asRecord(supplyCard(candidate)?.price_reaction);
  const priceReactionName = priceReaction?.name;
  if (typeof priceReactionName === "string" && priceReactionName) return priceReactionName;
  return sourceEntity(candidate) !== "CANNOT_CONFIRM" ? sourceEntity(candidate) : candidateCode(candidate);
}



export function bucketLabel(candidate: SelectionCandidate): string {
  const bucket = String(candidate.bucket || "CANNOT_CONFIRM");
  if (bucket.includes("CONDITIONAL")) return "条件研究";
  if (bucket.includes("CORE")) return "核心研究";
  return bucket;
}



export function statusClass(value: unknown): string {
  return String(value || "CANNOT_CONFIRM").toLowerCase().replaceAll(/[^a-z0-9_-]/g, "-");
}



export const GAP_COPY: Record<string, string> = {
  PRIMARY_SOURCE_CONTENT: "公告正文关键事实尚未核实",
  FINANCIAL_BRIDGE: "财务影响桥接尚未完成",
  EXACT_DATE_ELIGIBILITY_PIT: "目标日资格/PIT不可确认",
  ELIGIBILITY_PIT: "目标日资格/PIT不可确认",
  ELIGIBILITY_CANNOT_CONFIRM: "目标日资格/PIT不可确认",
  PIT_CANNOT_CONFIRM: "PIT证据不可确认",
  PIT_PIT_FAILED: "PIT证据未通过",
  SOURCE_REFS_CANNOT_CONFIRM: "来源引用不可确认",
  "REAL_09:25_09:35_MARKET_CONFIRMATION": "09:25/09:35真实盘面确认缺失",
  OPENING_CONFIRMATION: "09:25/09:35真实盘面确认缺失",
};



export function hasOwn(record: Record<string, unknown> | null, key: string): boolean {
  return Boolean(record) && Object.prototype.hasOwnProperty.call(record, key);
}



export function gapToken(value: unknown): string | null {
  if (typeof value === "string") {
    const token = value.trim();
    if (!token || ["NaN", "Infinity", "-Infinity"].includes(token)) return null;
    return token;
  }
  const record = asRecord(value);
  if (!record) return null;
  for (const key of ["type", "code", "name"]) {
    const token = gapToken(record[key]);
    if (token) return token;
  }
  return null;
}



export type GapParseResult = { kind: "empty" | "values" | "invalid"; values: string[] };



export function parseGapValue(value: unknown): GapParseResult {
  if (value === null || value === undefined || value === "") return { kind: "invalid", values: [] };
  const parsed = parseStructuredValue(value);
  if (parsed === undefined || (typeof parsed === "number" && !Number.isFinite(parsed))) {
    return { kind: "invalid", values: [] };
  }
  if (Array.isArray(parsed)) {
    if (!parsed.length) return { kind: "empty", values: [] };
    const values = parsed.map((item) => gapToken(item) || "CANNOT_CONFIRM");
    return { kind: "values", values };
  }
  const token = gapToken(parsed);
  return token ? { kind: "values", values: [token] } : { kind: "invalid", values: [] };
}



export function gapCodes(candidate: SelectionCandidate): string[] {
  const result = new Set<string>();
  const record = candidate as Record<string, unknown>;
  const supply = supplyCard(candidate);
  const sources: Array<{ present: boolean; value: unknown }> = [
    { present: hasOwn(record, "typed_gaps"), value: record.typed_gaps },
    { present: hasOwn(supply, "typed_gaps"), value: supply?.typed_gaps },
    { present: hasOwn(supply, "promotion_missing_fields"), value: supply?.promotion_missing_fields },
  ];
  let sourcePresent = false;
  let allPresentSourcesEmpty = true;
  for (const source of sources) {
    if (!source.present) continue;
    sourcePresent = true;
    const parsed = parseGapValue(source.value);
    if (parsed.kind === "empty") continue;
    if (parsed.kind === "values") {
      parsed.values.forEach((item) => result.add(item));
      allPresentSourcesEmpty = false;
      continue;
    }
    result.add("CANNOT_CONFIRM");
    allPresentSourcesEmpty = false;
  }
  if (sourcePresent) return result.size ? [...result] : allPresentSourcesEmpty ? [] : ["CANNOT_CONFIRM"];

  let fallbackPresent = false;
  let allFallbackSourcesEmpty = true;
  if (!sourcePresent) {
    for (const key of ["cannot_confirm", "gaps", "promotion_missing_fields"]) {
      if (!hasOwn(record, key)) continue;
      fallbackPresent = true;
      const parsed = parseGapValue(record[key]);
      if (parsed.kind === "empty") continue;
      if (parsed.kind === "values") {
        parsed.values.forEach((item) => result.add(item));
        allFallbackSourcesEmpty = false;
      } else {
        result.add("CANNOT_CONFIRM");
        allFallbackSourcesEmpty = false;
      }
    }
  }
  if (fallbackPresent && !result.size && allFallbackSourcesEmpty) return [];
  if (!result.size) result.add("CANNOT_CONFIRM");
  return [...result];
}



export function gapLabel(code: string): string {
  if (code === "CANNOT_CONFIRM") return "其他风险待核实";
  return GAP_COPY[code] || "其他风险待核实";
}



export function typedGaps(candidate: SelectionCandidate): string[] {
  const gaps = new Set(gapCodes(candidate).map(gapLabel));
  if (candidate.eligibility === "ELIGIBILITY_CANNOT_CONFIRM") gaps.add(gapLabel("ELIGIBILITY_CANNOT_CONFIRM"));
  if (candidate.pit_status === "CANNOT_CONFIRM" || candidate.pit_status === "PIT_FAILED") {
    gaps.add(gapLabel(`PIT_${candidate.pit_status}`));
  }
  if (!candidate.source_refs?.length) gaps.add(gapLabel("SOURCE_REFS_CANNOT_CONFIRM"));
  return [...gaps];
}



export function sourceRefText(ref: SelectionSourceRef): string {
  const record = ref as Record<string, unknown>;
  const scalar = (value: unknown): string | undefined => (
    typeof value === "string" && value.trim() ? value.trim() : undefined
  );
  const values = [
    scalar(ref.type),
    scalar(ref.source_date) ? `source_date=${scalar(ref.source_date)}` : undefined,
    scalar(ref.source_time) ? `source_time=${scalar(ref.source_time)}` : undefined,
    scalar(record.run_id) ? `run_id=${scalar(record.run_id)}` : undefined,
    scalar(record.status) ? `status=${scalar(record.status)}` : undefined,
    scalar(ref.raw_sha256) ? `raw_sha256=${scalar(ref.raw_sha256)}` : undefined,
    scalar(ref.frozen_payload_sha256) ? `frozen_payload_sha256=${scalar(ref.frozen_payload_sha256)}` : undefined,
    scalar(ref.supply_receipt_sha256) ? `supply_receipt_sha256=${scalar(ref.supply_receipt_sha256)}` : undefined,
  ].filter(Boolean);
  return values.length ? values.join(" · ") : "CANNOT_CONFIRM";
}



export async function contractIssue(result: SelectionProduct, date: string): Promise<string | null> {
  return validateSelectionProduct(result, date);
}



export function searchText(candidate: SelectionCandidate): string {
  return [
    candidateCode(candidate),
    candidateName(candidate),
    sourceEntity(candidate),
    candidate.bucket,
    candidate.catalyst,
    candidate.counterevidence,
    candidate.invalidation,
    candidate.evidence_level,
    candidate.eligibility,
    candidate.pit_status,
    candidate.recommendation_status,
    candidate.published_at,
    candidate.source_time,
    ...(candidate.source_refs || []).map((ref) => sourceRefText(ref)),
  ].map((item) => displayValue(item)).join(" ").toLowerCase();
}



export type ManagerStagePriorityEvidence = Readonly<{
  status: string;
  cannotConfirm: readonly string[];
}>;



export type ShanghaiClockParts = Readonly<{
  date: string;
  minutes: number;
}>;



export function shanghaiClockParts(now: Date): ShanghaiClockParts | null {
  if (Number.isNaN(now.getTime())) return null;
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(now);
  const values = Object.fromEntries(parts
    .filter((part) => part.type !== "literal")
    .map((part) => [part.type, part.value]));
  if (!values.year || !values.month || !values.day || !values.hour || !values.minute) return null;
  return {
    date: `${values.year}${values.month}${values.day}`,
    minutes: Number(values.hour) * 60 + Number(values.minute),
  };
}



/**
 * The stage endpoint can legitimately expose an empty envelope before its
 * 09:40 Asia/Shanghai slot.  This is evaluated once per render; there is no
 * timer or polling path that can turn the empty response into an investment
 * conclusion while the page is open.
 */
export function isBeforeManagerStageSlot(targetDate: string, now = new Date()): boolean {
  const clock = shanghaiClockParts(now);
  return Boolean(clock && clock.date === targetDate && clock.minutes < (9 * 60 + 40));
}



export function managerBasisValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "CANNOT_CONFIRM";
  return String(value);
}



export const MANAGER_RESEARCH_COVERAGE_FALLBACK = "仅依据已解析官方财报结构化事实；近期重大事件（含合作/公告）覆盖未确认。";



export function managerInvestmentAdviceCoverage(row: ManagerPriorityRow): string {
  return row.investmentAdvice.coverageScope || MANAGER_RESEARCH_COVERAGE_FALLBACK;
}



export function managerInvestmentBasisRefText(ref: Record<string, unknown>): string {
  const sha = typeof ref.source_sha256 === "string" && ref.source_sha256.trim()
    ? ref.source_sha256.trim()
    : "CANNOT_CONFIRM_SHA";
  const locator = typeof ref.locator === "string" && ref.locator.trim() ? ref.locator.trim() : "CANNOT_CONFIRM_LOCATOR";
  const page = typeof ref.page === "number" ? ` · page=${ref.page}` : "";
  return `source_sha256=${sha} · locator=${locator}${page}`;
}



export type ManagerCatalystCard = Readonly<{
  code: string;
  name: string;
  status: string;
  advice: Record<string, unknown>;
  events: readonly Record<string, unknown>[];
  sourceCoverage: readonly Record<string, unknown>[];
  currentEventAsOf: string;
  gaps: readonly string[];
}>;



export type ManagerReadingMaterial = Readonly<{
  id: string;
  code: string;
  name: string;
  title: string;
  sourceName: string;
  sourceUrl: string;
  publishedAt: string;
  collectedAt: string;
  excerpt: string;
  excerptLabel: string;
  scopeLabel: string;
  sourceKind: string;
  sourceCount: number;
  sourceAttributions: readonly Record<string, unknown>[];
  associations: readonly ManagerReadingAssociation[];
}>;



export type ManagerReadingAssociation = Readonly<{
  code: string;
  name: string;
}>;



export type ManagerReadingStockStatus = Readonly<{
  code: string;
  name: string;
  status: string;
  materialCount: number;
  gaps: readonly string[];
}>;



export function recordList(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.map((item) => asRecord(item)).filter((item): item is Record<string, unknown> => Boolean(item))
    : [];
}



export function readingSourceUrl(value: unknown): string {
  const raw = typeof value === "string" ? value.trim() : "";
  if (!raw || /\s/.test(raw)) return "";
  try {
    const parsed = new URL(raw);
    return (parsed.protocol === "http:" || parsed.protocol === "https:") && parsed.hostname ? parsed.toString() : "";
  } catch {
    return "";
  }
}



export const READING_SOURCE_TIME_ZONE_OFFSET_MINUTES = 8 * 60;



/**
 * Normalize source timestamps before sorting.  Eastmoney's public-news
 * timestamps are naive Asia/Shanghai values; ISO timestamps with an explicit
 * offset keep the offset supplied by the source.  A missing or malformed
 * timestamp remains unknown and is deliberately sorted last.
 */
export function readingPublishedEpoch(value: string): number | null {
  const raw = value.trim();
  if (!raw || raw === "CANNOT_CONFIRM") return null;
  if (/(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw)) {
    const parsed = Date.parse(raw);
    return Number.isFinite(parsed) ? parsed : null;
  }
  const match = /^(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?$/.exec(raw);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4] || 0);
  const minute = Number(match[5] || 0);
  const second = Number(match[6] || 0);
  const utc = Date.UTC(year, month - 1, day, hour, minute, second);
  const check = new Date(utc);
  if (check.getUTCFullYear() !== year
    || check.getUTCMonth() !== month - 1
    || check.getUTCDate() !== day
    || check.getUTCHours() !== hour
    || check.getUTCMinutes() !== minute
    || check.getUTCSeconds() !== second) {
    return null;
  }
  return utc - READING_SOURCE_TIME_ZONE_OFFSET_MINUTES * 60 * 1000;
}



export function readingUpperBoundEpoch(value: string): number | null {
  if (!isRealDate(value)) return null;
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(4, 6));
  const day = Number(value.slice(6, 8));
  return Date.UTC(year, month - 1, day + 1)
    - READING_SOURCE_TIME_ZONE_OFFSET_MINUTES * 60 * 1000;
}



export function readingMaterialIsWithinUpperBound(material: ManagerReadingMaterial, upperBound: string): boolean {
  const published = readingPublishedEpoch(material.publishedAt);
  const bound = readingUpperBoundEpoch(upperBound);
  if (published === null || bound === null) return true;
  return published < bound;
}



export function readingAssociation(row: Record<string, unknown>): ManagerReadingAssociation {
  return {
    code: catalystText(row.code),
    name: catalystText(row.name),
  };
}



export type ReadingEventSourceKind = "MEDIA" | "OFFICIAL" | "UNKNOWN";



export function readingEventSourceKind(event: Record<string, unknown>): ReadingEventSourceKind {
  const rawKind = catalystText(event.source_kind, "").toUpperCase();
  if (rawKind === "MEDIA") return "MEDIA";
  if (rawKind === "OFFICIAL") return "OFFICIAL";
  return "UNKNOWN";
}



export function readingEventSourceName(event: Record<string, unknown>, sourceKind: ReadingEventSourceKind): string {
  const sourceName = catalystText(event.source_name, "");
  if (sourceName) return sourceName;
  const sourceId = catalystText(event.source_id, "");
  if (sourceId) return sourceId;
  return sourceKind === "MEDIA" ? "行业媒体" : "来源未标";
}



export function readingMaterialFromEvent(row: Record<string, unknown>, event: Record<string, unknown>): ManagerReadingMaterial {
  const sourceUrl = readingSourceUrl(event.source_url);
  const sourceKind = readingEventSourceKind(event);
  return {
    id: `event-${catalystText(event.event_id || sourceUrl || event.source_title)}`,
    code: catalystText(row.code),
    name: catalystText(row.name),
    title: catalystText(event.catalyst || event.source_title, "CANNOT_CONFIRM（原标题缺失）"),
    sourceName: readingEventSourceName(event, sourceKind),
    sourceUrl,
    publishedAt: catalystText(event.publisher_timestamp || event.publisher_timestamp_text),
    collectedAt: catalystText(event.retrieved_at || event.first_seen_at),
    excerpt: catalystText(event.source_excerpt || event.why_might_affect_business, "CANNOT_CONFIRM（来源摘要缺失）"),
    excerptLabel: "来源摘要",
    scopeLabel: sourceKind === "OFFICIAL" ? "官方原始材料；未生成入选理由" : "原始来源材料；未生成入选理由",
    sourceKind,
    sourceCount: 1,
    sourceAttributions: [],
    associations: [readingAssociation(row)],
  };
}



export function readingMaterialFromPublic(row: Record<string, unknown>, item: Record<string, unknown>): ManagerReadingMaterial {
  const attributions = recordList(item.source_attributions);
  return {
    id: catalystText(item.id || item.source_url || item.title),
    code: catalystText(row.code),
    name: catalystText(row.name),
    title: catalystText(item.title, "CANNOT_CONFIRM（原标题缺失）"),
    sourceName: catalystText(item.source_name, "来源未标"),
    sourceUrl: readingSourceUrl(item.source_url) || readingSourceUrl(item.url),
    publishedAt: catalystText(item.published_at || item.published_date),
    collectedAt: catalystText(item.collected_at || item.queried_at),
    excerpt: catalystText(item.content_excerpt, "CANNOT_CONFIRM（来源摘要缺失）"),
    excerptLabel: item.content_is_excerpt === true ? "来源摘要（可能不完整）" : "来源可得正文",
    scopeLabel: catalystText(item.reading_scope_label || item.evidence_scope, "原文范围待确认"),
    sourceKind: "PUBLIC_NEWS",
    sourceCount: typeof item.source_count === "number" ? item.source_count : Math.max(1, attributions.length),
    sourceAttributions: attributions,
    associations: [readingAssociation(row)],
  };
}



export function mergeReadingMaterials(left: ManagerReadingMaterial, right: ManagerReadingMaterial): ManagerReadingMaterial {
  const associations = [...left.associations, ...right.associations].filter((association, index, items) => (
    items.findIndex((item) => item.code === association.code) === index
  ));
  const sourceAttributions = [...left.sourceAttributions, ...right.sourceAttributions].filter((attribution, index, items) => {
    const key = `${String(attribution.source_name || "")}|${String(attribution.url || "")}|${String(attribution.source_method || "")}`;
    return items.findIndex((item) => `${String(item.source_name || "")}|${String(item.url || "")}|${String(item.source_method || "")}` === key) === index;
  });
  return {
    ...left,
    sourceCount: Math.max(left.sourceCount, right.sourceCount, sourceAttributions.length || 1),
    sourceAttributions,
    associations,
  };
}



export function catalystText(value: unknown, fallback = "CANNOT_CONFIRM"): string {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return fallback;
}



export function catalystTextList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && Boolean(item.trim())).map((item) => item.trim())
    : [];
}



export type CatalystSemanticClass = "ELIGIBLE" | "UNCONFIRMED" | "NON_SUBSTANTIVE";



export function catalystSemanticClass(event: Record<string, unknown>): CatalystSemanticClass {
  const raw = event.semantic_class;
  if (raw === "ELIGIBLE" || raw === "UNCONFIRMED" || raw === "NON_SUBSTANTIVE") return raw;
  if (
    event.body_parsed === true
    && event.event_relevant !== false
    && event.event_status !== "CANNOT_CONFIRM"
    && event.summary_status !== "UNCONFIRMED"
    && typeof event.source_excerpt === "string"
    && Boolean(event.source_excerpt.trim())
  ) return "ELIGIBLE";
  return "UNCONFIRMED";
}



export function catalystSemanticClassLabel(event: Record<string, unknown>): string {
  return {
    ELIGIBLE: "当前投影：可解释准入",
    UNCONFIRMED: "当前投影：待核实",
    NON_SUBSTANTIVE: "当前投影：非实质材料",
  }[catalystSemanticClass(event)];
}



export const CATALYST_SOURCE_KIND_LABELS: Record<string, string> = {
  MEDIA: "行业媒体",
  OFFICIAL: "官方公告",
};



export function catalystSourceLabel(event: Record<string, unknown>): string {
  const kind = catalystText(event.source_kind);
  const kindLabel = CATALYST_SOURCE_KIND_LABELS[kind] || kind;
  const sourceId = catalystText(event.source_id);
  return `${kindLabel} · ${sourceId}`;
}



export function catalystSourceUrl(event: Record<string, unknown>): string {
  const raw = typeof event.source_url === "string" ? event.source_url.trim() : "";
  if (!raw) return "";
  try {
    const parsed = new URL(raw);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.toString() : "";
  } catch {
    return "";
  }
}



export const CATALYST_CONFIRMATION_LABELS: Record<string, string> = {
  PENDING: "待官方确认",
  BODY_NOT_PARSED: "正文未解析",
  OFFICIAL_BODY_PARSED: "官方正文已解析",
  CANNOT_CONFIRM: "不可确认",
};



export function catalystConfirmationLabel(event: Record<string, unknown>): string {
  const raw = catalystText(event.official_confirmation_status);
  return CATALYST_CONFIRMATION_LABELS[raw] || raw;
}



export const CATALYST_DIMENSION_LABELS: Record<string, string> = {
  PROFIT_LOSS: "法定利润/亏损",
  OPERATING_CASHFLOW: "经营活动现金流",
  CASH: "现金及现金等价物",
  LIABILITIES: "负债",
  OPERATING_LOSS: "经营亏损",
  RECEIVABLE_IMPAIRMENT: "应收账款减值",
  REVENUE: "收入",
  GROSS_PROFIT: "毛利",
};


export const CATALYST_STATE_LABELS: Record<string, string> = {
  POSITIVE: "正值",
  NEGATIVE: "负值",
  MIXED: "混合",
  CONFLICT: "冲突",
  MISSING: "缺失",
};


export const CATALYST_CURRENCY_LABELS: Record<string, string> = {
  RMB: "人民币",
  CNY: "人民币",
  HKD: "港元",
  USD: "美元",
  S$: "新加坡元",
  SGD: "新加坡元",
};


export const CATALYST_UNIT_LABELS: Record<string, string> = {
  yuan: "元",
  unit: "元",
  units: "元",
  thousand: "千",
  thousands: "千",
  million: "百万",
  millions: "百万",
  billion: "十亿",
  billions: "十亿",
};



export function catalystRealizationConditions(event: Record<string, unknown>): string[] {
  if (event.event_type === "MARKET_ACCESS") {
    return [
      `官方名单纳入=${catalystText(event.inclusion_status)}；生效日=${catalystText(event.effective_date)}`,
      `实际可交易性/流动性=${catalystText(event.liquidity_confirmation)}；纳入本身不等于订单、收入或生产兑现。`,
    ];
  }
  return catalystTextList(event.realization_conditions);
}



export const CATALYST_GAP_LABELS: Record<string, string> = {
  MEDIA_ONLY_OFFICIAL_CONFIRMATION_PENDING: "官方确认待补",
  ORDER_OR_REVENUE_UNCONFIRMED: "订单/收入未确认",
  MARKET_PRICE_VOLUME_UNCONFIRMED: "量价未确认",
  DIRECTORY_ONLY_BODY_NOT_PARSED: "目录线索，正文未解析",
  BUSINESS_SUMMARY_UNCONFIRMED: "业务摘要待核实",
};



export function catalystRiskSummary(card: ManagerCatalystCard): string {
  const event = catalystFocusEvents(card)[0] || card.events[0];
  const gaps = event ? catalystTextList(event.market_confirmation_gap) : [];
  const readableGaps = gaps.map((gap) => CATALYST_GAP_LABELS[gap] || gap).slice(0, 2);
  if (event && event.official_confirmation_status === "PENDING") readableGaps.unshift("官方确认待补");
  if (!readableGaps.length) readableGaps.push("兑现条件仍待核验");
  return `风险边界：${[...new Set(readableGaps)].join("；")}`;
}



export function catalystSourceCountText(value: unknown): string {
  const count = asRecord(value);
  if (!count) return displayValue(value);
  const source = catalystText(count.source_label || count.source_id);
  const rawSubstantive = typeof count.substantive_body === "number" ? count.substantive_body : null;
  if (rawSubstantive !== null) {
    return `${source}：采集时原始正文计数 ${rawSubstantive}（仅作回执审计；当前准入按事件投影重算）`;
  }
  return displayValue(value);
}



export function catalystEvidenceStatus(event: Record<string, unknown>): string {
  if (event.body_parsed === true) return "正文已解析";
  if (event.evidence_level === "OFFICIAL_DIRECTORY_ONLY" || event.body_parsed === false) return "DIRECTORY_ONLY 目录线索（正文未解析）";
  return "CANNOT_CONFIRM";
}



export function catalystTimingStatus(event: Record<string, unknown>): string {
  const bucket = event.as_of_bucket;
  if (bucket === "historical") return "历史证据；不等于09:40系统已消费";
  if (bucket === "current") return "当前补充；不回写历史09:40";
  return "CANNOT_CONFIRM（事件时间桶缺失）";
}



export function catalystFocusEvents(card: ManagerCatalystCard): readonly Record<string, unknown>[] {
  return card.events.filter((event) =>
    catalystSemanticClass(event) === "ELIGIBLE"
    &&
    event.body_parsed === true
    && event.event_relevant !== false
    && event.event_status !== "CANNOT_CONFIRM"
    && event.summary_status !== "UNCONFIRMED"
    && typeof event.source_excerpt === "string"
    && Boolean(event.source_excerpt.trim()),
  );
}



export function catalystAuditEventLabel(event: Record<string, unknown>): string {
  if (event.summary_status === "UNCONFIRMED" || event.event_status === "CANNOT_CONFIRM") {
    return "摘要待核实，不进入焦点";
  }
  if (event.body_parsed !== true) return "目录线索，正文未解析，不进入焦点";
  return "正文已解析";
}



export const WORKBENCH_SOURCE_LABELS: Readonly<Record<string, string>> = {
  STAGE: "原有阶段候选",
  CLOSE_DISCOVERY: "15:30尾盘发现",
  CONTINUOUS_TRACKING: "持续跟踪",
};



export function workbenchSymbolKey(value: unknown): string {
  const code = normalizeManagerHkCode(value);
  return code ? `HK.${code}` : "";
}



export function workbenchSourceLabels(candidate: ManagerWorkbenchCandidate | null, includeStage = false): string[] {
  const labels = includeStage ? [WORKBENCH_SOURCE_LABELS.STAGE] : [];
  if (candidate) {
    for (const lane of candidate.source_lanes) {
      labels.push(WORKBENCH_SOURCE_LABELS[lane] || lane);
    }
  }
  return [...new Set(labels)];
}



export function workbenchCoverageText(payload: ManagerWorkbenchResearchResponse | null): string {
  if (!payload) return "覆盖未知";
  const { eligible_count: eligible, covered_count: covered, missing_count: missing } = payload.coverage;
  if (eligible === null || covered === null || missing === null) return "覆盖范围尚未核实";
  return `覆盖 ${covered}/${eligible} · 缺失 ${missing}`;
}



export function workbenchStatusText(status: string): string {
  return readableStatus(status);
}



export function workbenchShortReason(candidate: ManagerWorkbenchCandidate | null): string {
  if (candidate?.research_priority?.level === "UPGRADED_WATCH") return "新增直接催化，继续核对交易条件";
  if (candidate?.source_lanes.includes("CONTINUOUS_TRACKING")) return "前日观察延续，仍需核对完整条件";
  return "已记录当前行情，逐项核对研究条件";
}



export function workbenchAudit(value: unknown): string {
  return JSON.stringify(value, null, 2);
}



export function workbenchRecordText(value: unknown, keys: readonly string[]): string {
  const record = asRecord(value);
  if (!record) return "CANNOT_CONFIRM";
  const parts = keys.flatMap((key) => {
    const item = record[key];
    if (item === undefined || item === null || item === "") return [];
    return [`${key}=${displayValue(item)}`];
  });
  return parts.length ? parts.join(" · ") : "CANNOT_CONFIRM";
}



export function workbenchTurnoverText(candidate: ManagerWorkbenchCandidate | null): string {
  const turnover = candidate?.turnover_amount;
  if (!turnover) return "金额资料待补";
  const value = turnover.value;
  const currency = turnover.currency;
  const unit = turnover.unit;
  if (typeof value !== "number" || !Number.isFinite(value) || currency !== "HKD" || unit !== "HKD") {
    return typeof value === "number" && Number.isFinite(value)
      ? `${value.toLocaleString("zh-HK")}（原始金额；币种/单位待核）` : "金额资料待补";
  }
  return `${value.toLocaleString("zh-HK")} 港元`;
}



export function workbenchPlanList(candidate: ManagerWorkbenchCandidate | null, key: string): string {
  const plan = asRecord(candidate?.observation_plan);
  const value = plan?.[key];
  if (!Array.isArray(value)) return "CANNOT_CONFIRM";
  const rows = value.filter((item): item is string => typeof item === "string" && Boolean(item.trim()));
  return rows.length ? rows.join("；") : "CANNOT_CONFIRM";
}



export function workbenchCandidateDomId(candidateId: string): string {
  return `workbench-candidate-${candidateId.replace(/[^A-Za-z0-9_-]+/g, "-")}`;
}



export function workbenchConfirmedEvidenceText(candidate: ManagerWorkbenchCandidate | null): string {
  if (!candidate) return "CANNOT_CONFIRM";
  const confirmed = candidate.predicates
    .filter((predicate) => predicate.value === true)
    .map((predicate) => `${predicate.predicate_id || "UNKNOWN_PREDICATE"}${predicate.reason ? `：${predicate.reason}` : ""}`);
  return confirmed.length ? confirmed.join("；") : "CANNOT_CONFIRM";
}



export function workbenchSourceText(source: ManagerWorkbenchSourceRef): string {
  const lane = source.lane ? (WORKBENCH_SOURCE_LABELS[source.lane] || source.lane) : "UNKNOWN_LANE";
  const date = source.source_date || "CANNOT_CONFIRM_DATE";
  const run = source.run_id || "CANNOT_CONFIRM_RUN";
  const reason = source.reason || "CANNOT_CONFIRM_REASON";
  return `${lane} · date=${date} · run=${run} · ${reason}`;
}



export type ManagerStageMetric =
  | "stage_score"
  | "current_change_pct"
  | "pct_chg"
  | "volume_ratio"
  | "turnover";



export function managerStageRowValue(row: ManagerStageSelectionRow, field: string): unknown {
  return (row as Record<string, unknown>)[field];
}



export function managerStageRawText(value: unknown): string | null {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed && !["NaN", "Infinity", "-Infinity"].includes(trimmed) ? trimmed : null;
  }
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : null;
  if (typeof value === "boolean") return String(value);
  return null;
}



export function managerStageName(row: ManagerStageSelectionRow): string {
  for (const field of ["name", "stock_name", "display_name", "symbol", "code"]) {
    const value = managerStageRawText(managerStageRowValue(row, field));
    if (value) return value;
  }
  return "CANNOT_CONFIRM";
}



export function managerStageCode(row: ManagerStageSelectionRow): string {
  for (const field of ["code", "symbol"]) {
    const value = managerStageRawText(managerStageRowValue(row, field));
    if (value) return value;
  }
  return "CANNOT_CONFIRM";
}



export function managerStageMetricAvailable(row: ManagerStageSelectionRow, field: ManagerStageMetric): boolean {
  const value = managerStageRowValue(row, field);
  return value !== undefined && value !== null && value !== "";
}



export function managerStageMetricValue(row: ManagerStageSelectionRow, field: string): string {
  const value = managerStageRowValue(row, field);
  const text = managerStageRawText(value);
  return text || "CANNOT_CONFIRM";
}



export function managerStagePercentValue(row: ManagerStageSelectionRow, field: ManagerStageMetric): string {
  const value = managerStageMetricValue(row, field);
  if (value === "CANNOT_CONFIRM" || value.endsWith("%")) return value;
  return `${value}%`;
}



export function managerStageContributionRefText(ref: StageReasonEvidenceRef): string {
  if (typeof ref === "string") return ref;
  return displayValue(ref);
}



export function managerStageContributionDetailUrl(detail: StageReasonContributionDetail): string {
  return typeof detail.source_url === "string" && /^https?:\/\//i.test(detail.source_url)
    ? detail.source_url
    : "";
}



export function managerStageContributionDetailMeta(detail: StageReasonContributionDetail): string {
  const values = [
    detail.source,
    detail.published_at ? `原文=${detail.published_at}` : "",
    detail.fetched_at ? `获取=${detail.fetched_at}` : "",
    detail.stock_code || detail.stock_name ? `资料自带标的=${[detail.stock_code, detail.stock_name].filter(Boolean).join(" ")}` : "",
  ].filter(Boolean);
  return values.join(" · ") || "CANNOT_CONFIRM";
}



export function managerStageAuditValue(row: ManagerStageSelectionRow, field: string): string {
  const value = managerStageRowValue(row, field);
  if (Array.isArray(value)) {
    const values = value.map((item) => managerStageRawText(item)).filter((item): item is string => Boolean(item));
    return values.length ? values.join("、") : "CANNOT_CONFIRM";
  }
  return managerStageRawText(value) || "CANNOT_CONFIRM";
}



export function managerStageCardKey(row: ManagerStageSelectionRow, index: number): string {
  return `${managerStageCode(row)}-${managerStageMetricValue(row, "rank")}-${index}`;
}



export function rawNumericValue(value: unknown): string {
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "CANNOT_CONFIRM";
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed && Number.isFinite(Number(trimmed)) ? trimmed : "CANNOT_CONFIRM";
  }
  return "CANNOT_CONFIRM";
}



export const STRATEGY_LABELS: Record<string, string> = {
  prob_active: "活跃概率（prob_active）",
  prob_memory: "记忆概率（prob_memory）",
  prob_crash_reflow: "崩溃重流概率（prob_crash_reflow）",
};



export function strategyLabel(value: unknown): string {
  const raw = typeof value === "string" && value.trim() ? value.trim() : "CANNOT_CONFIRM";
  return STRATEGY_LABELS[raw] || (raw === "CANNOT_CONFIRM" ? raw : `未识别策略（原值：${raw}）`);
}



export function preselectionRowName(row: ManagerPreselectionRow): string {
  for (const field of ["stock_name", "name", "display_name"]) {
    const value = row[field];
    if (typeof value === "string" && value.trim()) return value;
  }
  return "CANNOT_CONFIRM";
}



export function preselectionScore(row: ManagerPreselectionRow | null | undefined): string {
  return rawNumericValue(row?.pool_score);
}



export function preselectionMetric(row: ManagerPreselectionRow | null | undefined, field: string): string {
  return rawNumericValue(row?.[field]);
}



export function strategyValue(row: ManagerPreselectionRow | null | undefined): string {
  return strategyLabel(row?.selected_strategy);
}



export function eventClassification(candidate: SelectionCandidate): string {
  const source = officialSource(candidate);
  const classification = source?.classification;
  return classification === undefined || classification === null || classification === ""
    ? "CANNOT_CONFIRM"
    : displayValue(classification);
}



export const VERIFIED_OFFICIAL_SOURCE_CLASSES = new Set([
  "OFFICIAL_PDF_LEDGER_VERIFIED",
  "OFFICIAL_PDF_MARKDOWN_CONTENT_VERIFIED",
]);



export function verifiedOfficialSourceClass(source: Record<string, unknown>): string | null {
  const value = source.source_class;
  return typeof value === "string" && VERIFIED_OFFICIAL_SOURCE_CLASSES.has(value) ? value : null;
}



export function officialTextValue(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!trimmed || ["NaN", "Infinity", "-Infinity"].includes(trimmed)) return null;
  const parsed = parseStructuredValue(trimmed);
  return parsed !== undefined && typeof parsed !== "string" ? null : trimmed;
}



export function officialSource(candidate: SelectionCandidate): Record<string, unknown> | null {
  const source = asRecord(supplyCard(candidate)?.source);
  if (!source || !verifiedOfficialSourceClass(source)) return null;
  if (!officialTextValue(source.classification) || !officialTextValue(source.evidence)) return null;
  return source;
}



export function catalystStatement(value: unknown): string {
  const parsed = parseStructuredValue(value);
  const record = asRecord(parsed);
  if (!record) return displayValue(parsed);
  for (const key of ["statement", "summary", "title", "text"]) {
    const field = record[key];
    if (field === undefined || field === null || field === "") continue;
    const parsedField = parseStructuredValue(field);
    if (asRecord(parsedField) || Array.isArray(parsedField)) return "CANNOT_CONFIRM";
    return displayValue(parsedField);
  }
  return "CANNOT_CONFIRM";
}



export function officialClassificationRaw(candidate: SelectionCandidate): string {
  const source = officialSource(candidate);
  return source ? displayValue(source.classification) : "CANNOT_CONFIRM";
}



export const CLASSIFICATION_LABELS: Record<string, string> = {
  RESULTS_OR_EARNINGS: "业绩/财报",
  BUSINESS_OR_REGULATORY_CATALYST: "业务/监管催化",
  FINANCING_OR_CAPITAL: "融资/资本动作",
};



export function officialClassificationLabel(candidate: SelectionCandidate): string {
  const raw = officialClassificationRaw(candidate);
  if (raw === "CANNOT_CONFIRM") return raw;
  return CLASSIFICATION_LABELS[raw] || `未识别枚举（原值：${raw}）`;
}



export function officialClassificationCopy(candidate: SelectionCandidate): string {
  const raw = officialClassificationRaw(candidate);
  return CLASSIFICATION_LABELS[raw] || "";
}



export function officialEvidenceText(candidate: SelectionCandidate): string {
  const source = officialSource(candidate);
  return source ? displayValue(source.evidence) : "CANNOT_CONFIRM";
}



export function officialSourceStatusRaw(candidate: SelectionCandidate): string {
  const source = officialSource(candidate);
  return source ? verifiedOfficialSourceClass(source) || "CANNOT_CONFIRM" : "CANNOT_CONFIRM";
}



export function officialSourceStatusLabel(candidate: SelectionCandidate): string {
  const raw = officialSourceStatusRaw(candidate);
  if (raw === "OFFICIAL_PDF_LEDGER_VERIFIED") return "官方 PDF 台账材料已绑定";
  if (raw === "OFFICIAL_PDF_MARKDOWN_CONTENT_VERIFIED") return "本地官方 PDF/Markdown 材料已绑定";
  return raw;
}



export function officialSourceRefs(candidate: SelectionCandidate): SelectionSourceRef[] {
  if (!officialSource(candidate)) return [];
  const supply = supplyCard(candidate);
  const values = Array.isArray(candidate.source_refs) && candidate.source_refs.length
    ? candidate.source_refs
    : Array.isArray(supply?.source_refs) ? supply.source_refs : [];
  return values.filter((item): item is SelectionSourceRef => Boolean(asRecord(item)));
}



export function candidateSourceRefs(candidate: SelectionCandidate): SelectionSourceRef[] {
  const supply = supplyCard(candidate);
  const values = Array.isArray(candidate.source_refs) && candidate.source_refs.length
    ? candidate.source_refs
    : Array.isArray(supply?.source_refs) ? supply.source_refs : [];
  return values.filter((item): item is SelectionSourceRef => Boolean(asRecord(item)));
}



export function reasonSummary(candidate: SelectionCandidate, row: ManagerPreselectionRow | null | undefined): string {
  const route = row ? "进入 D-1 × 官方事件交叉研究队列" : "进入经理关注层研究范围";
  const official = officialSource(candidate)
    ? `匹配到官方${officialClassificationCopy(candidate)}材料`
    : "官方材料仍待核实";
  return `${route}；${official}，保持研究观察而不进入 formal。`;
}



export function nonformalRiskSummary(candidate: SelectionCandidate): string {
  const gaps = typedGaps(candidate);
  if (!gaps.length || gaps.includes("未声明缺口")) {
    return "关键资格与证据仍需复核，当前保持非formal研究边界。";
  }
  return `仍需核实：${gaps.join("、")}；因此保持非formal研究边界。`;
}



export function reasonValue(candidate: SelectionCandidate, field: string): string {
  return displayValue(candidateField(candidate, field));
}



export function eligibilityPitSummary(candidate: SelectionCandidate): string {
  const eligibility = reasonValue(candidate, "eligibility");
  const pitStatus = reasonValue(candidate, "pit_status");
  const gap = eligibility !== "ELIGIBLE" || pitStatus !== "READY";
  return `exact eligibility/PIT：eligibility=${eligibility} · pit_status=${pitStatus}${gap ? "（缺失/不可确认）" : ""}`;
}



export function promotionAllowedValue(candidate: SelectionCandidate): string {
  const direct = candidateField(candidate, "promotion_allowed");
  const fallback = supplyCard(candidate)?.promotion_allowed;
  const value = direct !== undefined ? direct : fallback;
  return value === true ? "true" : value === false ? "false" : "CANNOT_CONFIRM";
}



export function selectionCatalyst(candidate: Readonly<Record<string, unknown>>): string {
  return catalystStatement(candidate.catalyst);
}



export function managerQueueSortRank(candidate: SelectionCandidate): number {
  if (managerReviewStatus(candidate) !== "READY") return 2;
  const bucket = managerReviewBucket(candidate);
  if (bucket === "PRIORITY") return 0;
  if (bucket === "CONDITIONAL") return 1;
  if (bucket === "EXCLUDE") return 3;
  return 2;
}



export function sameStringSet(left: string[], right: string[]): boolean {
  return left.length === right.length
    && new Set(left).size === left.length
    && new Set(right).size === right.length
    && left.every((item) => right.includes(item));
}



export type ManagerDecisionDisplay = ManagerDecisionRow & {
  role: ManagerDecisionRole;
  order: number;
};



export function valueOrCannotConfirm(value: unknown): string {
  return value === undefined || value === null || value === "" ? "CANNOT_CONFIRM" : String(value);
}



export function updateBrowserDate(date: string): void {
  window.history.replaceState({}, "", `/manager-selection/?date=${encodeURIComponent(date)}`);
}



export type RequestContext = {
  sequence: number;
  date: string;
  controller: AbortController;
};



export type RequestAttempt = {
  signal: AbortSignal;
  timeout: Promise<never>;
  timedOut: () => boolean;
  dispose: () => void;
};



export function requestAttempt(parentSignal: AbortSignal, timeoutMs = REQUEST_TIMEOUT_MS): RequestAttempt {
  const controller = new AbortController();
  let timeoutTriggered = false;
  let rejectTimeout: (reason?: unknown) => void = () => undefined;
  const timeout = new Promise<never>((_, reject) => {
    rejectTimeout = reject;
  });
  const timeoutId = globalThis.setTimeout(() => {
    timeoutTriggered = true;
    controller.abort();
    rejectTimeout(new Error("REQUEST_TIMEOUT"));
  }, timeoutMs);
  const abortFromParent = () => controller.abort();
  parentSignal.addEventListener("abort", abortFromParent, { once: true });
  return {
    signal: controller.signal,
    timeout,
    timedOut: () => timeoutTriggered,
    dispose: () => {
      globalThis.clearTimeout(timeoutId);
      parentSignal.removeEventListener("abort", abortFromParent);
    },
  };
}



export function withRequestTimeout<T>(attempt: RequestAttempt, operation: Promise<T>): Promise<T> {
  return Promise.race([operation, attempt.timeout]);
}



export function managerResearchStatus(value: ManagerResearchResponse): string {
  const status = (value as Record<string, unknown>).status;
  return typeof status === "string" && status.trim() ? status.trim().toUpperCase() : "CANNOT_CONFIRM";
}



export function managerResearchJobId(value: ManagerResearchResponse): string | null {
  const response = value as Record<string, unknown>;
  const direct = response.job_id;
  if (typeof direct === "string" && direct.trim()) return direct.trim();
  const job = asRecord(response.job);
  const nested = job?.job_id;
  return typeof nested === "string" && nested.trim() ? nested.trim() : null;
}



export function managerResearchGapText(value: ManagerResearchResponse): string[] {
  const response = value as Record<string, unknown>;
  const product = asRecord(response.product);
  const values = [product?.cannot_confirm, response.cannot_confirm]
    .flatMap((item) => Array.isArray(item) ? item : [item])
    .filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    .map((item) => item.trim());
  return [...new Set(values)];
}



export function managerResearchCoverage(value: ManagerResearchResponse | null): string | null {
  const product = value ? asRecord((value as Record<string, unknown>).product) : null;
  const coverage = asRecord(product?.coverage);
  const ready = coverage?.ready_rows;
  const requested = coverage?.requested_rows;
  if (typeof ready === "number" && Number.isFinite(ready)
    && typeof requested === "number" && Number.isFinite(requested)) {
    return `${ready}/${requested}`;
  }
  return null;
}



export function managerResearchResultState(value: ManagerResearchResponse): AuxiliaryState {
  if (value.product) {
    return managerResearchStatus(value) === "PARTIAL_WITH_ROWS" ? "PARTIAL_WITH_ROWS" : "READY";
  }
  const status = managerResearchStatus(value);
  return [
    "NOT_MATERIALIZED",
    "CANNOT_CONFIRM",
    "QUEUED",
    "RUNNING",
    "FAILED",
  ].includes(status)
    ? status as AuxiliaryState
    : "CANNOT_CONFIRM";
}



export function managerResearchResultIsActive(value: ManagerResearchResponse): boolean {
  if (value.product) return false;
  const status = managerResearchResultState(value);
  return status === "QUEUED" || status === "RUNNING";
}



export function waitForManagerResearchPoll(signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new Error("REQUEST_ABORTED"));
      return;
    }
    const timeoutId = globalThis.setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, MANAGER_RESEARCH_POLL_DELAY_MS);
    const onAbort = () => {
      globalThis.clearTimeout(timeoutId);
      signal.removeEventListener("abort", onAbort);
      reject(new Error("REQUEST_ABORTED"));
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}



export function preselectionFailureMessage(reason: unknown): string {
  const message = reason instanceof Error ? reason.message : "响应不可确认";
  return message.startsWith("D-1 预选池读取失败")
    ? message
    : `D-1 预选池读取失败（${message}）。`;
}



export function stageFailureMessage(reason: unknown): string {
  const message = reason instanceof Error ? reason.message : "响应不可确认";
  return message.startsWith("今日港股通阶段候选读取失败")
    ? message
    : `今日港股通阶段候选读取失败（${message}）。`;
}



export function scrollTo(id: string): void {
  document.querySelector(`#${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
}



export const ANNOUNCEMENT_PREOPEN_TARGET = ANNOUNCEMENT_PREOPEN_WINDOW.targetDate;
