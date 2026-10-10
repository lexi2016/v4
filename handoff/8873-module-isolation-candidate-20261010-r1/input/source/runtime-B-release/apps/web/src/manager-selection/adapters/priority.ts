import { normalizeManagerHkCode } from "../../contracts/managerPreselection";
import type { ManagerResearchRow } from "../../api/managerResearch";
import type { ManagerStageSelectionRow } from "../../contracts/managerStageSelection";

/**
 * A presentation-only recommendation category.  The category is deliberately
 * separate from the trading gate: the manager page remains research-only.
 */
export const PRIORITY_CATEGORIES = [
  "BUY",
  "CONDITIONAL",
  "WATCH",
  "NO_BUY",
  "CANNOT_CONFIRM",
] as const;

export type PriorityCategory = typeof PRIORITY_CATEGORIES[number];

export const PRIORITY_CATEGORY_LABELS: Record<PriorityCategory, string> = {
  BUY: "BUY（执行门）",
  CONDITIONAL: "CONDITIONAL（执行门）",
  WATCH: "WATCH（执行门）",
  NO_BUY: "NO_BUY（执行门）",
  CANNOT_CONFIRM: "CANNOT_CONFIRM（执行门）",
};

export type FundamentalSignalState = "POSITIVE" | "NEGATIVE" | "UNKNOWN" | "CONFLICT" | "MIXED" | "MISSING";

export type FundamentalSignal = Readonly<{
  state: FundamentalSignalState;
  current: number | null;
  previous: number | null;
  growthPct: number | null;
  label: string | null;
}>;

export type FundamentalPreference = Readonly<{
  period: string | null;
  sourceSha256: string | null;
  statutoryProfit: FundamentalSignal;
  operatingCashFlow: FundamentalSignal;
  revenue: FundamentalSignal;
  completeness: number;
  summary: string;
}>;

export type InvestmentBasis = Readonly<{
  dimension: string | null;
  state: string | null;
  current: string | number | null;
  previous: string | number | null;
  currentColumn: string | null;
  previousColumn: string | null;
  period: string | null;
  periodKey: readonly unknown[] | null;
  currency: string | null;
  unit: string | null;
  factRefs: readonly Record<string, unknown>[];
  text: string | null;
}>;

/** An explicit research opinion; it is never inferred from stage rank or gate state. */
export type InvestmentAdvice = Readonly<{
  action: string | null;
  label: string | null;
  status: string | null;
  summary: string | null;
  coverageScope: string | null;
  conditions: readonly string[];
  risks: readonly string[];
  priorityRank: number | null;
  priorityReason: string | null;
  basis: readonly InvestmentBasis[];
}>;

export type ManagerPriorityRow = Readonly<{
  code: string;
  name: string;
  category: PriorityCategory;
  categoryLabel: string;
  stageRow: ManagerStageSelectionRow;
  researchRow: ManagerResearchRow | null;
  stageRank: number | null;
  researchRank: number | null;
  reason: string;
  buyConditions: readonly string[];
  invalidationConditions: readonly string[];
  dataTime: string;
  preference: FundamentalPreference;
  executionGate: string;
  investmentAdvice: InvestmentAdvice;
  evidenceGap: string | null;
}>;

export type ManagerPrioritySummary = Readonly<{
  rows: readonly ManagerPriorityRow[];
  researchPriorityRows: readonly ManagerPriorityRow[];
  counts: Readonly<Record<PriorityCategory, number>>;
  researchAdviceCounts: Readonly<Record<ResearchAdviceAction, number | null>>;
  retainedCount: number;
  stageStatus: string;
  stageGap: string | null;
}>;

export type BuildPriorityInput = Readonly<{
  stageRows: readonly ManagerStageSelectionRow[];
  stageStatus?: string | null;
  stageCannotConfirm?: readonly unknown[] | null;
  managerResearchRows?: readonly ManagerResearchRow[] | null;
  managerResearchStatus?: string | null;
  managerResearchCutoffAt?: string | null;
  managerResearchRecommendationSummary?: unknown;
  targetDate: string;
}>;

export const RESEARCH_ADVICE_ACTIONS = [
  "BUY",
  "CONDITIONAL_BUY",
  "WATCH",
  "AVOID",
  "DATA_INSUFFICIENT",
] as const;

export type ResearchAdviceAction = typeof RESEARCH_ADVICE_ACTIONS[number];

export const RESEARCH_ADVICE_LABELS: Record<ResearchAdviceAction, string> = {
  BUY: "BUY（研究意见）",
  CONDITIONAL_BUY: "CONDITIONAL_BUY（研究意见）",
  WATCH: "WATCH（研究意见）",
  AVOID: "AVOID（研究意见）",
  DATA_INSUFFICIENT: "DATA_INSUFFICIENT（研究意见）",
};

type MetricKind = "profit" | "cash" | "revenue";

type FactObservation = Readonly<{
  metric: MetricKind;
  current: number | null;
  previous: number | null;
  growthPct: number | null;
  period: string;
  sourceSha256: string | null;
  label: string;
  lossLabel: boolean;
  ambiguousLabel: boolean;
}>;

const CATEGORY_ORDER: Readonly<Record<PriorityCategory, number>> = {
  BUY: 0,
  CONDITIONAL: 1,
  WATCH: 2,
  NO_BUY: 3,
  CANNOT_CONFIRM: 4,
};

const UNKNOWN_GAP = "缺少可确认的建议字段或同报告期官方结构化指标";

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function text(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function numberValue(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string") return null;
  let raw = value.trim();
  if (!raw || /^(?:n\/?a|na|--|–|—)$/i.test(raw)) return null;
  const negative = /^\(.*\)$/.test(raw);
  raw = raw.replace(/^\(|\)$/g, "").replaceAll(",", "").replace(/[％%]$/, "").replace(/[−–—]/g, "-").trim();
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) return null;
  return negative ? -Math.abs(parsed) : parsed;
}

function normalizedCode(value: unknown): string | null {
  const code = normalizeManagerHkCode(value);
  return code ? code : null;
}

function displayCode(value: unknown): string {
  const code = normalizedCode(value);
  return code ? `HK.${code}` : "CANNOT_CONFIRM";
}

function rowName(row: ManagerStageSelectionRow): string {
  for (const key of ["name", "stock_name", "display_name", "symbol", "code"]) {
    const value = text(row[key]);
    if (value) return value;
  }
  return "CANNOT_CONFIRM";
}

function strictRank(value: unknown): number | null {
  if (typeof value === "number" && Number.isSafeInteger(value) && value >= 1) return value;
  if (typeof value === "string" && /^[1-9]\d*$/.test(value)) {
    const parsed = Number(value);
    return Number.isSafeInteger(parsed) ? parsed : null;
  }
  return null;
}

function normalizedRecommendation(value: unknown): string | null {
  const raw = text(value);
  return raw ? raw.toUpperCase().replace(/[\s-]+/g, "_") : null;
}

function rowField(row: ManagerStageSelectionRow, key: string): unknown {
  return (row as Record<string, unknown>)[key];
}

function researchField(row: ManagerResearchRow | null, key: string): unknown {
  return row ? (row as Record<string, unknown>)[key] : undefined;
}

function arrayOfText(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map(text).filter((item): item is string => Boolean(item));
}

function basisItems(value: unknown): InvestmentBasis[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    const record = asRecord(item) || {};
    const refs = Array.isArray(record.fact_refs)
      ? record.fact_refs.map(asRecord).filter((ref): ref is Record<string, unknown> => Boolean(ref))
      : [];
    return {
      dimension: text(record.dimension),
      state: text(record.state)?.toUpperCase() || null,
      current: typeof record.current === "string" || typeof record.current === "number" ? record.current : null,
      previous: typeof record.previous === "string" || typeof record.previous === "number" ? record.previous : null,
      currentColumn: text(record.current_column),
      previousColumn: text(record.previous_column),
      period: text(record.period),
      periodKey: Array.isArray(record.period_key) ? record.period_key : null,
      currency: text(record.currency),
      unit: text(record.unit),
      factRefs: refs,
      text: text(record.text),
    } satisfies InvestmentBasis;
  }).filter((item) => item.dimension || item.state || item.current !== null || item.previous !== null);
}

function exactAction(row: ManagerStageSelectionRow, researchRow: ManagerResearchRow | null): string | null {
  // action_level is the stage contract's explicit recommendation.  It has
  // precedence over display/status fields and is the execution gate input.
  // Research-row advice is intentionally excluded: it is displayed as a
  // separate dimension and cannot upgrade or downgrade the stage gate.
  return normalizedRecommendation(rowField(row, "action_level"))
    || normalizedRecommendation(rowField(row, "trade_status_contract"))
    || normalizedRecommendation(rowField(row, "trade_status"))
    || normalizedRecommendation(rowField(row, "status"));
}

function executionGate(row: ManagerStageSelectionRow, researchRow: ManagerResearchRow | null): string {
  const recommendation = asRecord(researchField(researchRow, "research_recommendation"));
  const nestedGate = asRecord(researchField(researchRow, "execution_gate"))
    || asRecord(recommendation?.execution_gate);
  // The server's nested gate is the authoritative research-product projection.
  // A stage row remains the compatibility fallback for older responses.
  return normalizedRecommendation(nestedGate?.action_level)
    || normalizedRecommendation(nestedGate?.trade_status)
    || normalizedRecommendation(nestedGate?.action)
    || normalizedRecommendation(nestedGate?.status)
    || normalizedRecommendation(rowField(row, "action_level"))
    || normalizedRecommendation(rowField(row, "trade_status_contract"))
    || normalizedRecommendation(rowField(row, "trade_status"))
    || normalizedRecommendation(rowField(row, "status"))
    || "CANNOT_CONFIRM";
}

function investmentAdvice(researchRow: ManagerResearchRow | null): InvestmentAdvice {
  const recommendation = asRecord(researchField(researchRow, "research_recommendation"));
  const nested = asRecord(researchField(researchRow, "investment_advice"))
    || asRecord(recommendation?.investment_advice)
    || recommendation
    || asRecord(researchField(researchRow, "research_advice"));
  const action = normalizedRecommendation(nested?.action ?? nested?.recommendation ?? nested?.stance);
  const label = text(nested?.label_cn ?? nested?.label ?? nested?.direction)
    || text(researchField(researchRow, "direction"));
  const summary = text(nested?.summary ?? nested?.thesis_cn ?? nested?.reason)
    || text(researchField(researchRow, "decision"))
    || text(researchField(researchRow, "thesis_cn"));
  const coverageScope = text(nested?.coverage_scope ?? nested?.advice_scope_note);
  const status = normalizedRecommendation(nested?.status)
    || normalizedRecommendation(researchField(researchRow, "advice_status"));
  const conditions = [
    ...arrayOfText(nested?.conditions),
    ...arrayOfText(nested?.confirmation_conditions),
    ...arrayOfText(researchField(researchRow, "confirmation_conditions")),
  ];
  const risks = [
    ...arrayOfText(nested?.blocking_reasons),
    ...arrayOfText(nested?.risks),
    ...arrayOfText(nested?.invalidation_conditions),
    ...arrayOfText(researchField(researchRow, "counterevidence_cn")),
    ...arrayOfText(researchField(researchRow, "invalidation_conditions")),
  ];
  const priorityRank = strictRank(nested?.priority_rank);
  const priorityReason = text(nested?.priority_reason);
  return {
    action,
    label,
    status,
    summary,
    coverageScope,
    conditions: [...new Set(conditions)],
    risks: [...new Set(risks)],
    priorityRank,
    priorityReason,
    basis: basisItems(nested?.basis),
  };
}

function actionCategory(
  row: ManagerStageSelectionRow,
  researchRow: ManagerResearchRow | null,
  stageStatus: string,
  stageHasGap: boolean,
): { category: PriorityCategory; reason: string; gap: string | null } {
  const action = exactAction(row, researchRow);
  const formalEligible = rowField(row, "formal_eligible");
  const status = normalizedRecommendation(rowField(row, "status"));
  const tradeStatus = normalizedRecommendation(rowField(row, "trade_status"));
  const decision = text(researchField(researchRow, "decision"));

  if (action === "BUY" || action === "BUY_REVIEW" || action === "BUY_CANDIDATE") {
    if (formalEligible !== true || stageStatus !== "READY" || stageHasGap) {
      return {
        category: "CANNOT_CONFIRM",
        reason: "发现买入建议值，但 exact 阶段资格/证据不满足；保留原值并禁止升级为买入。",
        gap: "买入建议与 formal/阶段证据不一致",
      };
    }
    return { category: "BUY", reason: "阶段接口明确给出买入建议值；当前页面仍仅作研究展示。", gap: null };
  }

  if (action === "NO_BUY" || action === "NO_TRADE") {
    const source = action === "NO_TRADE" ? "trade_status=NO_TRADE" : "stage action_level=NO_BUY";
    return {
      category: "NO_BUY",
      reason: `执行门为 ${action}（当前阶段未准入）；原始 ${source}。独立研究意见单独展示。`,
      gap: stageHasGap ? "阶段返回包含历史/时点缺口，仍保留原始不买边界" : null,
    };
  }

  if (action === "CONDITIONAL" || action === "CONDITIONAL_BUY" || action === "WAIT" || action === "WAIT_FOR_CONFIRMATION") {
    return { category: "CONDITIONAL", reason: decision || "建议先完成条件核验；当前不构成买入授权。", gap: stageHasGap ? "阶段证据存在缺口" : null };
  }

  if (action === "WATCH" || action === "WATCH_ONLY" || action === "OBSERVE"
    || status === "WATCH_ONLY" || tradeStatus === "WATCH_ONLY") {
    return { category: "WATCH", reason: decision || "当前仅观察，等待后续验证。", gap: stageHasGap ? "阶段证据存在缺口" : null };
  }

  if (action === "CANNOT_CONFIRM" || action === "UNKNOWN" || action === "UNAVAILABLE"
    || action === "DATA_INSUFFICIENT" || action === "NOT_GENERATED") {
    return { category: "CANNOT_CONFIRM", reason: "建议字段明确不可确认；不使用其他字段推断买入。", gap: UNKNOWN_GAP };
  }

  return { category: "CANNOT_CONFIRM", reason: "未发现可靠建议字段；等待同报告期官方指标或下一阶段证据。", gap: UNKNOWN_GAP };
}

function factText(fact: Record<string, unknown>): string {
  const fields = asRecord(fact.fields);
  return [
    text(fact.fact_type),
    text(fact.label),
    text(fact.label_cn),
    text(fields?.label),
    text(fields?.label_cn),
    text(fact.statement_cn),
  ].filter(Boolean).join(" ").toLowerCase();
}

function metricForFact(fact: Record<string, unknown>): { metric: MetricKind; lossLabel: boolean; ambiguousLabel: boolean } | null {
  const fields = asRecord(fact.fields);
  const primaryLabel = text(fields?.label)
    || text(fact.label)
    || text(fields?.label_cn)
    || text(fact.label_cn)
    || text(fact.statement_cn);
  const label = (primaryLabel || factText(fact)).replace(/\s+/g, " ").trim().toLowerCase();
  if (!label) return null;
  const normalized = label.replace(/[.。、:：]/g, "").replace(/\s+/g, " ");
  const cash = (/(?:net\s+cash|net\s+cash\s+flows|净额\s*现金|现金\s*流量\s*净额)/i.test(normalized)
    && /(?:operating activities|经营(?:活动| activities))/i.test(normalized))
    && !/(subtotal|cash received|现金 received|cash generated|产生.*现金|现金及现金等价物|cash equivalents)/i.test(normalized);
  if (cash) return { metric: "cash", lossLabel: false, ambiguousLabel: false };
  const revenue = /^(?:(?:[ivx]+\s*)?\s*)?(?:total\s+)?(?:operating\s+)?revenues?(?:\s+from\s+contracts\s+with\s+customers)?$/i.test(normalized)
    || /^(?:[ivx]+\s*[.、])?\s*(?:总\s*)?(?:经营|营业)?收入(?:总额|合计)?$/u.test(normalized.replace(/\s+/g, ""));
  if (revenue) return { metric: "revenue", lossLabel: false, ambiguousLabel: false };
  const ambiguousLabel = /^(?:(?:net\s+)?(?:profit|loss)\s*[/\\-]?\s*\(?loss\)?|(?:net\s+)?profit\s+or\s+loss|利润\s*[/／]?[（(]?亏损|盈利\s*[/／]?[（(]?亏损)/i.test(normalized);
  const englishProfit = /^(?:net\s+)?(?:profit|loss)(?:\s+for\s+(?:the\s+)?(?:period|year)\b|\s+attributable\b|$)/i.test(normalized)
    && !/^(?:gross|operating)\s+(?:profit|loss)\b|\b(?:before|after)\s+tax\b|comprehensive|profit\s+or\s+loss\s+of/i.test(normalized);
  const chineseProfit = /(?:净利润|净亏损|期内利润|期内亏损|本期利润|本期亏损|年度利润|年度亏损)/u.test(normalized);
  const profit = (englishProfit || chineseProfit || ambiguousLabel)
    && !/(adjusted|excluding|non-recurring|非经常|调整后|一次性)/i.test(normalized);
  if (profit) {
    const hasProfitWord = /(profit|盈利|利润)/i.test(normalized);
    const hasLossWord = /(loss|亏损)/i.test(normalized);
    return {
      metric: "profit",
      // A line explicitly labelled only as loss is signed negative.  A raw
      // negative value remains negative through the -abs normalization below.
      lossLabel: hasLossWord && !hasProfitWord,
      // Labels such as "profit/(loss)" do not identify which side the raw
      // value represents.  They must not be guessed into a preference.
      ambiguousLabel: ambiguousLabel || (hasProfitWord && hasLossWord),
    };
  }
  return null;
}

function periodText(fact: Record<string, unknown>): string {
  const fields = asRecord(fact.fields);
  const columns = Array.isArray(fields?.columns)
    ? fields.columns.map(text).filter((value): value is string => Boolean(value)).join("|")
    : null;
  return [
    text(fact.reporting_period),
    text(fact.period),
    text(fact.period_label),
    text(fields?.reporting_period),
    text(fields?.period),
    text(fields?.period_label),
    text(fields?.period_label_cn),
    columns,
  ].filter(Boolean).join("|") || "CANNOT_CONFIRM_PERIOD";
}

type ParsedReportPeriod = Readonly<{
  identity: string;
  endDate: string;
}>;

const REPORT_MONTHS: Readonly<Record<string, number>> = {
  january: 1,
  february: 2,
  march: 3,
  april: 4,
  may: 5,
  june: 6,
  july: 7,
  august: 8,
  september: 9,
  october: 10,
  november: 11,
  december: 12,
  jan: 1,
  feb: 2,
  mar: 3,
  apr: 4,
  jun: 6,
  jul: 7,
  aug: 8,
  sep: 9,
  sept: 9,
  oct: 10,
  nov: 11,
  dec: 12,
};

function validReportDate(year: number, month: number, day: number): string | null {
  if (!Number.isInteger(year) || !Number.isInteger(month) || !Number.isInteger(day)) return null;
  const date = new Date(Date.UTC(year, month - 1, day));
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return null;
  return `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function reportDuration(value: string): string {
  const lower = value.toLowerCase();
  if (/(?:12\s*months?|twelve\s+months?|annual|full\s+year|year\s+ended|年度|全年)/i.test(lower)) return "ANNUAL";
  if (/(?:nine\s+months?|9\s*months?|九个月|前三季度|first\s+three\s+quarters?)/i.test(lower)) return "INTERIM_9M";
  if (/(?:six\s+months?|6\s*months?|half[\s-]*year|半年|六个月|上半年|\bh1\b)/i.test(lower)
    || /(?:january|jan\.?)[\s-]*(?:to|through|至|-|–|—)[\s-]*(?:june|jun\.?)/i.test(lower)) {
    return "INTERIM_H1";
  }
  if (/(?:three\s+months?|3\s*months?|季度|三个月|\bq[1-4]\b)/i.test(lower)) return "INTERIM_QUARTER";
  return "UNSPECIFIED";
}

/** Parse only an explicit, complete report period; never rank an opaque label. */
function parseReportPeriod(value: string): ParsedReportPeriod | null {
  const raw = value.replace(/\s+/g, " ").trim();
  if (!raw || raw === "CANNOT_CONFIRM_PERIOD") return null;
  const dates = new Set<string>();
  const years = new Set<number>();
  for (const match of raw.matchAll(/\b(20\d{2})\b/g)) years.add(Number(match[1]));
  const addDate = (year: number, month: number, day: number) => {
    const parsed = validReportDate(year, month, day);
    if (parsed) dates.add(parsed);
  };
  for (const match of raw.matchAll(/\b(20\d{2})\s*(?:年|[-/.])\s*(\d{1,2})\s*(?:月|[-/.])\s*(\d{1,2})\s*日?/g)) {
    addDate(Number(match[1]), Number(match[2]), Number(match[3]));
  }
  for (const match of raw.matchAll(/\b(20\d{2})(\d{2})(\d{2})\b/g)) {
    addDate(Number(match[1]), Number(match[2]), Number(match[3]));
  }
  for (const match of raw.matchAll(/\b(\d{1,2})\s+([A-Za-z]{3,9})\s*,?\s*(20\d{2})\b/gi)) {
    const month = REPORT_MONTHS[match[2].toLowerCase()];
    if (month) addDate(Number(match[3]), month, Number(match[1]));
  }
  for (const match of raw.matchAll(/\b([A-Za-z]{3,9})\s+(\d{1,2}),?\s*(20\d{2})\b/gi)) {
    const month = REPORT_MONTHS[match[1].toLowerCase()];
    if (month) addDate(Number(match[3]), month, Number(match[2]));
  }
  // Some HKEX tables keep the report year in the value columns while the
  // period label only says "Six months ended June 30," or "6月30日".
  // Collect month/day separately, but do not treat an opaque month name as a
  // date unless one unambiguous report year is available below.
  const monthDays = new Set<string>();
  for (const match of raw.matchAll(/\b([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(?!20\d{2})/gi)) {
    const month = REPORT_MONTHS[match[1].toLowerCase()];
    if (month) monthDays.add(`${month}-${Number(match[2])}`);
  }
  for (const match of raw.matchAll(/\b(\d{1,2})\s+([A-Za-z]{3,9})\s*,?\s*(?!20\d{2})/gi)) {
    const month = REPORT_MONTHS[match[2].toLowerCase()];
    if (month) monthDays.add(`${month}-${Number(match[1])}`);
  }
  for (const match of raw.matchAll(/(?:\b|^)(\d{1,2})\s*月\s*(\d{1,2})\s*日?/g)) {
    monthDays.add(`${Number(match[1])}-${Number(match[2])}`);
  }
  if (monthDays.size === 1 && years.size) {
    const [monthDay] = [...monthDays];
    const [month, day] = monthDay.split("-").map(Number);
    const reportYear = Math.max(...years);
    addDate(reportYear, month, day);
  }
  const duration = reportDuration(raw);
  if (!dates.size) {
    const quarter = raw.match(/\b(20\d{2})\s*[- ]?Q([1-4])\b/i);
    const half = raw.match(/\b(20\d{2})\s*[- ]?H([12])\b/i);
    const chineseHalf = raw.match(/\b(20\d{2})\s*年\s*(上半年|下半年)/i);
    const annual = raw.match(/(?:FY|annual|full\s+year|year\s+ended|年度|全年)[^0-9]*(20\d{2})\b/i);
    if (quarter) {
      const year = Number(quarter[1]);
      const month = Number(quarter[2]) * 3;
      addDate(year, month, new Date(Date.UTC(year, month, 0)).getUTCDate());
    } else if (half || chineseHalf) {
      const year = Number((half || chineseHalf)?.[1]);
      const secondHalf = (half?.[2] || chineseHalf?.[2]) === "2" || chineseHalf?.[2] === "下半年";
      addDate(year, secondHalf ? 12 : 6, secondHalf ? 31 : 30);
    } else if (annual) {
      const year = Number(annual[1]);
      addDate(year, 12, 31);
    }
  }
  // A duration and a report year are enough to bind standard interim/final
  // periods when the table omitted the day.  This is still a bounded rule:
  // opaque "Reporting Period" labels without a duration remain unknown.
  if (!dates.size && years.size && duration !== "UNSPECIFIED") {
    const reportYear = Math.max(...years);
    if (duration === "ANNUAL") addDate(reportYear, 12, 31);
    if (duration === "INTERIM_9M") addDate(reportYear, 9, 30);
    if (duration === "INTERIM_H1") addDate(reportYear, 6, 30);
    if (duration === "INTERIM_QUARTER") {
      const quarter = raw.match(/\bq([1-4])\b/i);
      const quarterNumber = quarter ? Number(quarter[1]) : 2;
      const month = quarterNumber * 3;
      addDate(reportYear, month, new Date(Date.UTC(reportYear, month, 0)).getUTCDate());
    }
  }
  if (dates.size > 1) {
    // Narrative excerpts can mention both the current and prior report date.
    // If the value columns identify one current year, retain only that date;
    // otherwise the period is genuinely ambiguous.
    const reportYear = years.size ? Math.max(...years) : null;
    const currentYearDates = reportYear === null
      ? []
      : [...dates].filter((date) => Number(date.slice(0, 4)) === reportYear);
    if (currentYearDates.length === 1) dates.clear(), dates.add(currentYearDates[0]);
  }
  if (dates.size !== 1) return null;
  const endDate = [...dates][0];
  return { identity: `${endDate}|${duration}`, endDate };
}

function periodGapPreference(reason: string): FundamentalPreference {
  const summary = `${reason}；${UNKNOWN_GAP}；不使用输入顺序推断同报告期指标。`;
  return {
    period: null,
    sourceSha256: null,
    statutoryProfit: emptySignal(),
    operatingCashFlow: emptySignal(),
    revenue: emptySignal(),
    completeness: 0,
    summary,
  };
}

function yearFrom(value: unknown): number | null {
  const match = text(value)?.match(/20\d{2}/);
  return match ? Number(match[0]) : null;
}

function extractCurrentPrevious(values: unknown): { current: number | null; previous: number | null; growthPct: number | null } {
  if (!Array.isArray(values)) return { current: null, previous: null, growthPct: null };
  const parsed = values.map((item) => {
    const record = asRecord(item);
    return {
      year: yearFrom(record?.column),
      column: text(record?.column),
      value: numberValue(record?.raw ?? record?.value),
    };
  }).filter((item) => item.value !== null);
  if (!parsed.length) return { current: null, previous: null, growthPct: null };
  const yearValues = parsed.filter((item) => item.year !== null);
  let current = parsed[0]?.value ?? null;
  let previous = parsed[1]?.value ?? null;
  if (yearValues.length >= 2) {
    const sorted = [...yearValues].sort((left, right) => (right.year || 0) - (left.year || 0));
    current = sorted[0].value;
    previous = sorted[1].value;
  }
  const explicitGrowth = parsed.find((item) => /%|growth|同比|percent|percentage/i.test(item.column || ""));
  const growthPct = explicitGrowth?.value ?? (
    current !== null && previous !== null && previous !== 0
      ? ((current - previous) / Math.abs(previous)) * 100
      : null
  );
  return { current, previous, growthPct };
}

function sourceShaForFact(fact: Record<string, unknown>, researchRow: ManagerResearchRow): string | null {
  const source = asRecord(researchRow.source);
  return text(fact.source_sha256) || text(asRecord(fact.fields)?.source_sha256) || text(source?.sha256);
}

function collectObservations(researchRow: ManagerResearchRow | null): FactObservation[] {
  if (!researchRow || !Array.isArray(researchRow.facts)) return [];
  const observations: FactObservation[] = [];
  for (const item of researchRow.facts) {
    const fact = asRecord(item);
    if (!fact) continue;
    const metricInfo = metricForFact(fact);
    if (!metricInfo) continue;
    const fields = asRecord(fact.fields);
    const values = fields?.values ?? fact.values;
    const extracted = extractCurrentPrevious(values);
    const label = factText(fact) || "official structured fact";
    observations.push({
      ...metricInfo,
      ...extracted,
      period: periodText(fact),
      sourceSha256: sourceShaForFact(fact, researchRow),
      label,
    });
  }
  return observations;
}

function emptySignal(): FundamentalSignal {
  return { state: "UNKNOWN", current: null, previous: null, growthPct: null, label: null };
}

function preferredObservations(observations: FactObservation[], metric: MetricKind): FactObservation[] {
  const values = observations.filter((item) => item.metric === metric && item.current !== null);
  if (metric === "revenue") {
    // Prefer a company-level aggregate over a contract/revenue component when
    // both are present in the same report.  A component remains usable when
    // it is the only structured revenue row, but it is never combined with an
    // aggregate to manufacture a conflict.
    const aggregate = values.filter((item) =>
      /(?:official_fact\s+)?(?:i\.?\s+)?total\s+operating\s+revenue|(?:official_fact\s+)?total\s+revenue\b|official_fact\s+revenue(?:\s|$)/i.test(item.label)
      && !/revenue\s+from\s+contracts\s+with\s+customers/i.test(item.label));
    if (aggregate.length) return aggregate;
  }
  if (metric === "profit") {
    // One report can expose tax profit, period profit and attributable profit
    // rows.  They are alternative presentations of one earnings dimension;
    // use the attributable row when available, otherwise the period row, and
    // never count pre-tax/gross rows as a second independent signal.
    const attributable = values.filter((item) => /profit|loss\s+for\s+the\s+period\s+attributable|net\s+profit\s+attributable/i.test(item.label)
      && /attributable/i.test(item.label));
    if (attributable.length) return attributable;
    const period = values.filter((item) => /(?:net\s+)?(?:profit|loss)\s+for\s+(?:the\s+)?period\b|(?:期内|本期)(?:利润|亏损)/i.test(item.label));
    if (period.length) return period;
  }
  return values;
}

function signalFromObservations(observations: FactObservation[], metric: MetricKind): FundamentalSignal {
  const values = preferredObservations(observations, metric);
  if (!values.length) return emptySignal();
  if (values.some((item) => item.ambiguousLabel)) {
    return { state: "CONFLICT", current: null, previous: null, growthPct: null, label: values[0].label };
  }
  const signedValue = (item: FactObservation): number | null =>
    item.current === null ? null : item.lossLabel ? -Math.abs(item.current) : item.current;
  // Different tables may provide a rounded percentage column while another
  // table only provides current/prior values.  Same current/prior values are
  // the stable identity; do not turn harmless percentage rounding into a
  // false factual conflict.
  const distinct = new Set(values.map((item) => `${signedValue(item)}|${item.previous}`));
  if (distinct.size > 1) {
    return { state: "CONFLICT", current: null, previous: null, growthPct: null, label: values[0].label };
  }
  const item = values[0];
  const signedCurrent = metric === "profit" ? signedValue(item) : item.current;
  const state = signedCurrent === null ? "UNKNOWN" : signedCurrent > 0 ? "POSITIVE" : "NEGATIVE";
  return {
    state,
    current: signedCurrent,
    previous: item.previous,
    growthPct: item.growthPct,
    label: item.label,
  };
}

function fundamentalPreference(researchRow: ManagerResearchRow | null): FundamentalPreference {
  const observations = collectObservations(researchRow);
  if (!observations.length) {
    return {
      period: null,
      sourceSha256: null,
      statutoryProfit: emptySignal(),
      operatingCashFlow: emptySignal(),
      revenue: emptySignal(),
      completeness: 0,
      summary: UNKNOWN_GAP,
    };
  }
  const grouped = new Map<string, FactObservation[]>();
  for (const observation of observations) {
    const parsed = parseReportPeriod(observation.period);
    // A single PDF may contain balance-sheet notes or narrative excerpts that
    // carry no report-period label.  Keep those facts in the raw row, but do
    // not let them erase a complete, explicitly bound income/cash-flow group.
    // If every usable observation is opaque, the row remains CANNOT_CONFIRM.
    if (!parsed) continue;
    // The end date is the binding identity.  Income-statement tables and
    // as-of balance-sheet notes can use different duration words while still
    // belonging to the same official report date.
    const key = parsed.endDate;
    const bucket = grouped.get(key) || [];
    bucket.push(observation);
    grouped.set(key, bucket);
  }
  if (!grouped.size) return periodGapPreference("报告期文本不可解析");
  const groups = [...grouped.entries()].map(([identity, values]) => ({
    identity,
    values,
    parsed: parseReportPeriod(values[0]?.period || ""),
  }));
  if (groups.some((group) => !group.parsed)) return periodGapPreference("报告期存在不可解析分组");
  const latestDate = groups.reduce<string | null>((latest, group) => {
    const endDate = group.parsed?.endDate || null;
    return !latest || (endDate && endDate > latest) ? endDate : latest;
  }, null);
  const latest = groups.filter((group) => group.parsed?.endDate === latestDate);
  if (latest.length !== 1) {
    return periodGapPreference("报告期存在同日但口径冲突");
  }
  const selected = latest[0].values;
  const statutoryProfit = signalFromObservations(selected, "profit");
  const operatingCashFlow = signalFromObservations(selected, "cash");
  const revenue = signalFromObservations(selected, "revenue");
  const completeness = [statutoryProfit, operatingCashFlow, revenue]
    .filter((signal) => signal.state !== "UNKNOWN" && signal.state !== "CONFLICT").length;
  const hasConflict = [statutoryProfit, operatingCashFlow, revenue].some((signal) => signal.state === "CONFLICT");
  const sourceSha256 = selected.find((item) => item.sourceSha256)?.sourceSha256 || null;
  const period = selected[0]?.period || null;
  const pieces = [
    statutoryProfit.state === "POSITIVE" ? "法定盈利为正" : statutoryProfit.state === "NEGATIVE" ? "法定盈利为负/亏损" : statutoryProfit.state === "CONFLICT" ? "法定盈利字段冲突" : "法定盈利缺口",
    operatingCashFlow.state === "POSITIVE" ? "经营现金流净额为正" : operatingCashFlow.state === "NEGATIVE" ? "经营现金流净额为负" : operatingCashFlow.state === "CONFLICT" ? "经营现金流字段冲突" : "经营现金流缺口",
    revenue.growthPct !== null && Number.isFinite(revenue.growthPct) ? `营收同比${revenue.growthPct.toFixed(2)}%` : "营收同比缺口",
  ];
  return {
    period,
    sourceSha256,
    statutoryProfit,
    operatingCashFlow,
    revenue,
    completeness: hasConflict ? Math.max(0, completeness - 1) : completeness,
    summary: `${pieces.join("；")}；仅作同报告期研究优先级${hasConflict ? "，冲突已降级" : ""}。`,
  };
}

function preferenceFromBackendAdvice(
  advice: InvestmentAdvice,
  researchRow: ManagerResearchRow | null,
): FundamentalPreference | null {
  if (!advice.basis.length) return null;
  const signalFor = (dimension: string): FundamentalSignal => {
    const item = advice.basis.find((candidate) => candidate.dimension === dimension);
    if (!item) return emptySignal();
    const state = (item.state || "MISSING") as FundamentalSignalState;
    const current = numberValue(item.current);
    const previous = numberValue(item.previous);
    const growthPct = current !== null && previous !== null && previous !== 0
      ? ((current - previous) / Math.abs(previous)) * 100
      : null;
    return {
      state: ["POSITIVE", "NEGATIVE", "UNKNOWN", "CONFLICT", "MIXED", "MISSING"].includes(state) ? state : "UNKNOWN",
      current,
      previous,
      growthPct,
      label: item.dimension,
    };
  };
  const statutoryProfit = signalFor("profit_loss");
  const operatingCashFlow = signalFor("operating_cashflow");
  const revenue = signalFor("revenue");
  const source = asRecord(researchRow?.source);
  const firstRef = advice.basis.flatMap((item) => item.factRefs).find((ref) => text(ref.source_sha256));
  const period = advice.basis.find((item) => item.period)?.period || null;
  const completeness = [statutoryProfit, operatingCashFlow, revenue]
    .filter((signal) => !["UNKNOWN", "MISSING", "CONFLICT"].includes(signal.state)).length;
  return {
    period,
    sourceSha256: text(firstRef?.source_sha256) || text(source?.sha256),
    statutoryProfit,
    operatingCashFlow,
    revenue,
    completeness,
    summary: advice.priorityReason || advice.summary || "CANNOT_CONFIRM",
  };
}

function researchRowMap(rows: readonly ManagerResearchRow[] | null | undefined): Map<string, ManagerResearchRow> {
  const result = new Map<string, ManagerResearchRow>();
  for (const row of rows || []) {
    const code = normalizedCode(row.code);
    if (code && !result.has(code)) result.set(code, row);
  }
  return result;
}

function dataTime(
  targetDate: string,
  stageRow: ManagerStageSelectionRow,
  researchRow: ManagerResearchRow | null,
  cutoffAt: string | null | undefined,
): string {
  const source = asRecord(researchRow?.source);
  const pieces = [
    targetDate ? `目标日=${targetDate}` : "",
    text(rowField(stageRow, "source_last_bar_time")) ? `阶段=${text(rowField(stageRow, "source_last_bar_time"))}` : "",
    text(source?.published_at) ? `官方发布=${text(source?.published_at)}` : "",
    text(source?.retrieved_at) ? `官方获取=${text(source?.retrieved_at)}` : "",
    text(cutoffAt) ? `研究截止=${text(cutoffAt)}` : "",
  ].filter(Boolean);
  return pieces.length ? pieces.join(" · ") : "CANNOT_CONFIRM";
}

function buyConditions(stageRow: ManagerStageSelectionRow, researchRow: ManagerResearchRow | null): string[] {
  const values = arrayOfText(researchField(researchRow, "confirmation_conditions"));
  const next = text(rowField(stageRow, "next_validation_time"));
  if (next) values.push(`原阶段验证参考：${next}（历史记录，不是已核未来计划）`);
  return [...new Set(values)];
}

function invalidationConditions(stageRow: ManagerStageSelectionRow, researchRow: ManagerResearchRow | null): string[] {
  const values = [
    ...arrayOfText(researchField(researchRow, "invalidation_conditions")),
    ...arrayOfText(researchField(researchRow, "counterevidence_cn")),
  ];
  const invalidationPrice = rowField(stageRow, "invalidation_price") ?? rowField(stageRow, "invalidation");
  if (invalidationPrice !== undefined && invalidationPrice !== null && invalidationPrice !== "") {
    values.push(`阶段失效价位：${String(invalidationPrice)}`);
  }
  return [...new Set(values)];
}

function compareSignals(left: FundamentalSignal, right: FundamentalSignal): number {
  const rank = (signal: FundamentalSignal): number => {
    if (signal.state === "POSITIVE") return 3;
    if (signal.state === "NEGATIVE") return 2;
    if (signal.state === "CONFLICT") return 0;
    return 1;
  };
  return rank(right) - rank(left);
}

function comparePreference(left: FundamentalPreference, right: FundamentalPreference): number {
  if ([left.statutoryProfit, left.operatingCashFlow, left.revenue]
    .some((signal) => signal.state === "CONFLICT")
    || [right.statutoryProfit, right.operatingCashFlow, right.revenue]
      .some((signal) => signal.state === "CONFLICT")) {
    return 0;
  }
  const leftBothPositive = left.statutoryProfit.state === "POSITIVE" && left.operatingCashFlow.state === "POSITIVE";
  const rightBothPositive = right.statutoryProfit.state === "POSITIVE" && right.operatingCashFlow.state === "POSITIVE";
  if (leftBothPositive !== rightBothPositive) return rightBothPositive ? 1 : -1;
  // Completeness is compared before any numeric value.  A missing field is
  // never converted to zero, and therefore cannot outrank a known negative
  // field merely because it is unknown.
  const leftComplete = left.completeness;
  const rightComplete = right.completeness;
  if (leftComplete !== rightComplete) return rightComplete - leftComplete;
  const cashComparison = compareSignals(left.operatingCashFlow, right.operatingCashFlow);
  if (cashComparison) return cashComparison;
  const profitComparison = compareSignals(left.statutoryProfit, right.statutoryProfit);
  if (profitComparison) return profitComparison;
  const leftGrowth = left.revenue.growthPct;
  const rightGrowth = right.revenue.growthPct;
  if (leftGrowth !== null && rightGrowth !== null && leftGrowth !== rightGrowth) return rightGrowth - leftGrowth;
  return 0;
}

function compareDecisionRows(left: ManagerPriorityRow, right: ManagerPriorityRow): number {
  const category = CATEGORY_ORDER[left.category] - CATEGORY_ORDER[right.category];
  if (category) return category;
  const leftRank = left.stageRank ?? Number.MAX_SAFE_INTEGER;
  const rightRank = right.stageRank ?? Number.MAX_SAFE_INTEGER;
  if (leftRank !== rightRank) return leftRank - rightRank;
  return left.code.localeCompare(right.code);
}

function compareResearchRows(left: ManagerPriorityRow, right: ManagerPriorityRow): number {
  // The service owns research priority.  A missing/invalid backend rank is
  // kept after ranked rows and is never replaced with local completeness,
  // financial recomputation, or stage rank.
  const leftRank = left.researchRank ?? Number.MAX_SAFE_INTEGER;
  const rightRank = right.researchRank ?? Number.MAX_SAFE_INTEGER;
  if (leftRank !== rightRank) return leftRank - rightRank;
  return left.code.localeCompare(right.code);
}

function stageGapText(stageCannotConfirm: readonly unknown[] | null | undefined): string | null {
  const values = (stageCannotConfirm || []).map(text).filter((item): item is string => Boolean(item));
  return values.length ? values.join("；") : null;
}

function backendResearchAdviceCounts(value: unknown): Record<ResearchAdviceAction, number | null> {
  const summary = asRecord(value);
  const raw = asRecord(summary?.investment_advice_counts)
    || (asRecord(summary?.counts) && RESEARCH_ADVICE_ACTIONS.every((action) =>
      Object.prototype.hasOwnProperty.call(asRecord(summary?.counts), action)
    ) ? asRecord(summary?.counts) : null);
  return Object.fromEntries(RESEARCH_ADVICE_ACTIONS.map((action) => {
    const candidate = raw?.[action];
    return [action, typeof candidate === "number" && Number.isSafeInteger(candidate) && candidate >= 0 ? candidate : null];
  })) as Record<ResearchAdviceAction, number | null>;
}

/** Build the deterministic, research-only priority projection for stage rows. */
export function buildManagerPrioritySummary(input: BuildPriorityInput): ManagerPrioritySummary {
  const stageStatus = text(input.stageStatus) || "CANNOT_CONFIRM";
  const stageGap = stageGapText(input.stageCannotConfirm);
  const stageHasGap = Boolean(stageGap) || stageStatus === "PARTIAL_WITH_ROWS" || stageStatus === "CANNOT_CONFIRM";
  const researchByCode = researchRowMap(input.managerResearchRows);
  const rows = input.stageRows.map((stageRow) => {
    const codeValue = normalizedCode(rowField(stageRow, "code") ?? rowField(stageRow, "symbol"));
    const code = displayCode(rowField(stageRow, "code") ?? rowField(stageRow, "symbol"));
    const researchRow = codeValue ? researchByCode.get(codeValue) || null : null;
    const advice = investmentAdvice(researchRow);
    const preference = preferenceFromBackendAdvice(advice, researchRow) || fundamentalPreference(researchRow);
    let action = actionCategory(stageRow, researchRow, stageStatus, stageHasGap);
    const explicitAction = exactAction(stageRow, researchRow);
    if (!explicitAction && action.category === "CANNOT_CONFIRM" && preference.completeness > 0) {
      action = {
        category: "WATCH",
        reason: `未发现可靠建议值；${preference.summary}不代表买入建议。`,
        gap: stageHasGap ? "阶段证据存在缺口" : null,
      };
    }
    const fallbackReason = action.category === "CANNOT_CONFIRM"
      ? `${action.reason} ${preference.summary}`
      : action.reason;
    const researchRank = advice.priorityRank;
    return {
      code,
      name: rowName(stageRow),
      category: action.category,
      categoryLabel: PRIORITY_CATEGORY_LABELS[action.category],
      stageRow,
      researchRow,
      stageRank: strictRank(rowField(stageRow, "rank")),
      researchRank,
      reason: fallbackReason,
      buyConditions: buyConditions(stageRow, researchRow),
      invalidationConditions: invalidationConditions(stageRow, researchRow),
      dataTime: dataTime(input.targetDate, stageRow, researchRow, input.managerResearchCutoffAt),
      preference,
      executionGate: executionGate(stageRow, researchRow),
      investmentAdvice: advice,
      evidenceGap: action.gap,
    } satisfies ManagerPriorityRow;
  });
  const decisionRows = [...rows].sort(compareDecisionRows);
  // Stage cards remain complete even when the research product is absent.
  // A research priority row needs at least one parsed, same-period metric;
  // otherwise stage order would be presented as a research preference.
  const researchPriorityRows = rows
    .filter((row) => row.researchRank !== null)
    .sort(compareResearchRows);
  const counts = Object.fromEntries(PRIORITY_CATEGORIES.map((category) => [
    category,
    rows.filter((row) => row.category === category).length,
  ])) as Record<PriorityCategory, number>;
  return {
    rows: decisionRows,
    researchPriorityRows,
    researchAdviceCounts: backendResearchAdviceCounts(input.managerResearchRecommendationSummary),
    counts,
    retainedCount: rows.length,
    stageStatus,
    stageGap,
  };
}
