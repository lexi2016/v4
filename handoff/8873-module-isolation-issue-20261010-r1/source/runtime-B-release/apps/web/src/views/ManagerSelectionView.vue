<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";

import { loadSelectionExact } from "../api/selection";
import { loadManagerPreselectionExact } from "../api/managerPreselection";
import { loadManagerStageSelectionExact } from "../api/managerStageSelection";
import { loadManagerWorkbenchResearchExact } from "../api/managerWorkbenchResearch";
import { loadManagerDecisionExact } from "../api/managerDecision";
import {
  ensureManagerResearchExact,
  loadManagerResearchExact,
  loadManagerResearchJobExact,
  loadManagerResearchStatusExact,
  refreshManagerResearchEventsExact,
  type ManagerResearchResponse,
} from "../api/managerResearch";
import { loadResearchLane, type ResearchLane } from "../api/research_lane";
import { validateSelectionProduct } from "../contracts/selection";
import {
  buildManagerResearchQueue,
  getManagerHkPoolRows,
  normalizeManagerHkCode,
  validateManagerPreselection,
} from "../contracts/managerPreselection";
import type {
  FormalAuthority,
  SelectionCandidate,
  SelectionPhase,
  SelectionProduct,
  SelectionSnapshot,
  SelectionSourceRef,
} from "../contracts/selection";
import type {
  ManagerPreselectionResponse,
  ManagerPreselectionRow,
  ManagerResearchQueueEntry,
} from "../contracts/managerPreselection";
import {
  getManagerHkStageMarket,
  getManagerHkStageRows,
  isManagerHkStageRenderable,
  MANAGER_STAGE_ID,
  MANAGER_STAGE_MARKET,
  validateManagerStageSelection,
} from "../contracts/managerStageSelection";
import type {
  ManagerStageSelectionResponse,
  ManagerStageSelectionRow,
} from "../contracts/managerStageSelection";
import type {
  ManagerWorkbenchCandidate,
  ManagerWorkbenchResearchResponse,
  ManagerWorkbenchResearchStatus,
  ManagerWorkbenchSourceRef,
  ManagerWorkbenchSummaryItem,
} from "../contracts/managerWorkbenchResearch";
import {
  STAGE_REASON_CONTRIBUTION_KEYS,
  buildStageReasonContributions,
  type StageReasonContribution,
  type StageReasonContributionDetail,
  type StageReasonEvidenceRef,
} from "../manager-selection/adapters/stageReasonContributions";
import {
  buildManagerPrioritySummary,
  PRIORITY_CATEGORIES,
  PRIORITY_CATEGORY_LABELS,
  RESEARCH_ADVICE_ACTIONS,
  RESEARCH_ADVICE_LABELS,
  type ManagerPriorityRow,
} from "../manager-selection/adapters/priority";
import {
  validateManagerDecisionResponse,
} from "../contracts/managerDecision";
import type {
  ManagerDecisionResponse,
  ManagerDecisionRole,
  ManagerDecisionRow,
} from "../contracts/managerDecision";
import { conditionIndicators, conditionGaps, candidateHeadline, readableStatus } from "../manager-selection/adapters/workbenchPresentation";
import { mountCatalystObservations } from "../manager-selection/catalystObservationPanel";
import "../styles/manager-selection.css";

type ViewState =
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

type AuxiliaryState =
  | "IDLE"
  | "LOADING"
  | "READY"
  | "NOT_MATERIALIZED"
  | "CANNOT_CONFIRM"
  | "QUEUED"
  | "RUNNING"
  | "FAILED"
  | "PARTIAL_WITH_ROWS";

const props = defineProps<{ date?: string }>();

const VALID_PRODUCT_STATUSES = new Set([
  "EARLY_DRAFT_IMPORTED",
  "RESEARCH_SUPPLY_IMPORTED",
  "READY",
  "READY_WITH_DECLARED_GAPS",
  "NOT_MATERIALIZED",
  "CANNOT_CONFIRM",
]);

const MATERIALIZED_PRODUCT_STATUSES = new Set([
  "EARLY_DRAFT_IMPORTED",
  "RESEARCH_SUPPLY_IMPORTED",
  "READY",
  "READY_WITH_DECLARED_GAPS",
]);
const PHASES: ReadonlyArray<{
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

const requestedDate = ref("");
const payload = ref<SelectionProduct | null>(null);
const preselectionPayload = ref<ManagerPreselectionResponse | null>(null);
const stagePayload = ref<ManagerStageSelectionResponse | null>(null);
const state = ref<ViewState>("NO_DATE_SELECTED");
const preselectionState = ref<AuxiliaryState>("IDLE");
const queueState = ref<AuxiliaryState>("IDLE");
const stageState = ref<AuxiliaryState>("IDLE");
const managerDecisionState = ref<AuxiliaryState>("IDLE");
const managerResearchState = ref<AuxiliaryState>("IDLE");
const catalystRefreshState = ref<AuxiliaryState>("IDLE");
const researchLaneState = ref<AuxiliaryState>("IDLE");
const preselectionIssue = ref("");
const queueIssue = ref("");
const stageIssue = ref("");
const managerDecisionIssueText = ref("");
const managerResearchIssue = ref("");
const catalystRefreshIssue = ref("");
const researchLaneIssue = ref("");
const queueEntries = ref<ManagerResearchQueueEntry[]>([]);
const managerDecisionPayload = ref<ManagerDecisionResponse | null>(null);
const managerResearchPayload = ref<ManagerResearchResponse | null>(null);
const researchLanePayload = ref<ResearchLane | null>(null);
const workbenchResearchPayload = ref<ManagerWorkbenchResearchResponse | null>(null);
const workbenchResearchState = ref<ManagerWorkbenchResearchStatus | "IDLE" | "LOADING" | "CANNOT_CONFIRM">("IDLE");
const workbenchResearchIssue = ref("");
const workbenchSourceFilter = ref<"ALL" | "STAGE" | "CLOSE_DISCOVERY" | "CONTINUOUS_TRACKING">("ALL");
const errorMessage = ref("");
const searchQuery = ref("");
const bucketFilter = ref("ALL");
const readingStockFilter = ref("ALL");
const readingDateUpperBound = ref("");
let requestSequence = 0;
let workbenchReadSequence = 0;
let activeRequestController: AbortController | null = null;
const REQUEST_TIMEOUT_MS = 10_000;
// The event/news worker is server-owned and a healthy refresh can take about
// 167 seconds. Keep the browser attached to the existing job long enough to
// consume that result, while retaining a finite four-minute wait budget.
const MANAGER_RESEARCH_POLL_LIMIT = 48;
const MANAGER_RESEARCH_POLL_DELAY_MS = 5_000;
const MANAGER_RESEARCH_POLL_TIMEOUT_MS = 240_000;

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function isRealDate(value: string): boolean {
  if (!/^\d{8}$/.test(value)) return false;
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(4, 6));
  const day = Number(value.slice(6, 8));
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year
    && date.getUTCMonth() === month - 1
    && date.getUTCDate() === day;
}

function compactDate(value: string): string {
  return value.replaceAll("-", "");
}

function dateInputValue(value: string): string {
  return /^\d{8}$/.test(value)
    ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`
    : "";
}

function parseStructuredValue(value: unknown): unknown {
  if (typeof value !== "string") return value;
  const trimmed = value.trim();
  if (!(trimmed.startsWith("{") || trimmed.startsWith("["))) return value;
  try {
    return JSON.parse(trimmed) as unknown;
  } catch {
    return undefined;
  }
}

function isLocalStoragePath(value: string): boolean {
  const trimmed = value.trim();
  return trimmed.startsWith("/") || trimmed.startsWith("./") || trimmed.startsWith("../")
    || /^[A-Za-z]:[\\/]/.test(trimmed);
}

function isPathField(key: string): boolean {
  const normalized = key.trim().toLowerCase();
  return normalized === "path" || normalized.endsWith("_path");
}

/** Render structured research fields without ever turning them into [object Object]. */
function displayValue(value: unknown): string {
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

function primaryValue(value: unknown): string {
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

function candidateField(candidate: SelectionCandidate, key: string): unknown {
  return (candidate as Record<string, unknown>)[key];
}

function candidateCode(candidate: SelectionCandidate): string {
  const code = normalizeManagerHkCode(
    candidate.normalized_code || candidate.entity_id || candidate.candidate_id?.split("|")[0],
  );
  return code ? `HK.${code}` : "CANNOT_CONFIRM";
}

function sourceMetadata(candidate: SelectionCandidate): Record<string, unknown> | null {
  return asRecord(candidate.source_metadata);
}

function supplyCard(candidate: SelectionCandidate): Record<string, unknown> | null {
  return asRecord(sourceMetadata(candidate)?.supply_card);
}

function managerResearch(candidate: SelectionCandidate): Record<string, unknown> | null {
  const candidateRecord = candidate as Record<string, unknown>;
  const supply = supplyCard(candidate);
  const nested = asRecord(supply?.manager_research)
    || asRecord(supply?.primary_fact_review)
    || asRecord(candidateRecord.manager_research)
    || asRecord(candidateRecord.primary_fact_review);
  return nested;
}

function managerReviewValue(candidate: SelectionCandidate, key: string): unknown {
  return managerResearch(candidate)?.[key];
}

function managerReviewStatus(candidate: SelectionCandidate): string {
  const status = managerReviewValue(candidate, "status");
  return typeof status === "string" && status.trim() ? status.trim().toUpperCase() : "INSUFFICIENT_FACTS";
}

function managerReviewBucket(candidate: SelectionCandidate): string {
  const bucket = managerReviewValue(candidate, "priority_bucket");
  return typeof bucket === "string" && bucket.trim() ? bucket.trim().toUpperCase() : "GENERIC";
}

function managerReviewTextList(candidate: SelectionCandidate, key: string): string[] {
  const value = parseStructuredValue(managerReviewValue(candidate, key));
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => typeof item === "string" ? item.trim() : "")
    .filter((item): item is string => Boolean(item));
}

function managerFactItems(candidate: SelectionCandidate): Array<Record<string, unknown>> {
  const value = parseStructuredValue(managerReviewValue(candidate, "official_facts"));
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => asRecord(item))
    .filter((item): item is Record<string, unknown> => Boolean(item))
    .filter((item) => typeof item.statement_cn === "string" && item.statement_cn.trim())
    .slice(0, 4);
}

function managerFactStatement(fact: Record<string, unknown>): string {
  return typeof fact.statement_cn === "string" && fact.statement_cn.trim()
    ? fact.statement_cn.trim()
    : "CANNOT_CONFIRM";
}

function managerThesis(candidate: SelectionCandidate): string {
  const thesis = managerReviewValue(candidate, "investment_thesis_cn");
  if (typeof thesis === "string" && thesis.trim()) return thesis.trim();
  return "当前仅保留 D-1 × 官方公告交集；经营桥接待核实，需结合目标日盘面确认。";
}

function managerCounterevidence(candidate: SelectionCandidate): string[] {
  return managerReviewTextList(candidate, "counterevidence_cn");
}

function managerInvalidations(candidate: SelectionCandidate): string[] {
  return managerReviewTextList(candidate, "invalidation_conditions");
}

function managerConfirmations(candidate: SelectionCandidate): string[] {
  return managerReviewTextList(candidate, "confirmation_conditions");
}

function sourceEntity(candidate: SelectionCandidate): string {
  const supply = supplyCard(candidate);
  const entity = supply?.entity ?? candidateField(candidate, "entity") ?? candidate.entity_id;
  return entity === undefined || entity === null || entity === "" ? "CANNOT_CONFIRM" : String(entity);
}

function candidateName(candidate: SelectionCandidate): string {
  const explicit = candidate.name || candidate.stock_name || candidate.display_name;
  if (explicit) return explicit;
  const priceReaction = asRecord(supplyCard(candidate)?.price_reaction);
  const priceReactionName = priceReaction?.name;
  if (typeof priceReactionName === "string" && priceReactionName) return priceReactionName;
  return sourceEntity(candidate) !== "CANNOT_CONFIRM" ? sourceEntity(candidate) : candidateCode(candidate);
}

function bucketLabel(candidate: SelectionCandidate): string {
  const bucket = String(candidate.bucket || "CANNOT_CONFIRM");
  if (bucket.includes("CONDITIONAL")) return "条件研究";
  if (bucket.includes("CORE")) return "核心研究";
  return bucket;
}

function statusClass(value: unknown): string {
  return String(value || "CANNOT_CONFIRM").toLowerCase().replaceAll(/[^a-z0-9_-]/g, "-");
}

const GAP_COPY: Record<string, string> = {
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

function hasOwn(record: Record<string, unknown> | null, key: string): boolean {
  return Boolean(record) && Object.prototype.hasOwnProperty.call(record, key);
}

function gapToken(value: unknown): string | null {
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

type GapParseResult = { kind: "empty" | "values" | "invalid"; values: string[] };

function parseGapValue(value: unknown): GapParseResult {
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

function gapCodes(candidate: SelectionCandidate): string[] {
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

function gapLabel(code: string): string {
  if (code === "CANNOT_CONFIRM") return "其他风险待核实";
  return GAP_COPY[code] || "其他风险待核实";
}

function typedGaps(candidate: SelectionCandidate): string[] {
  const gaps = new Set(gapCodes(candidate).map(gapLabel));
  if (candidate.eligibility === "ELIGIBILITY_CANNOT_CONFIRM") gaps.add(gapLabel("ELIGIBILITY_CANNOT_CONFIRM"));
  if (candidate.pit_status === "CANNOT_CONFIRM" || candidate.pit_status === "PIT_FAILED") {
    gaps.add(gapLabel(`PIT_${candidate.pit_status}`));
  }
  if (!candidate.source_refs?.length) gaps.add(gapLabel("SOURCE_REFS_CANNOT_CONFIRM"));
  return [...gaps];
}

function sourceRefText(ref: SelectionSourceRef): string {
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

async function contractIssue(result: SelectionProduct, date: string): Promise<string | null> {
  return validateSelectionProduct(result, date);
}

function searchText(candidate: SelectionCandidate): string {
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

const materialized = computed(() =>
  Boolean(payload.value) && MATERIALIZED_PRODUCT_STATUSES.has(state.value),
);

const displayStatus = computed(() => {
  if (state.value === "NO_DATE_SELECTED") return "CANNOT_CONFIRM";
  return state.value;
});

const researchCandidates = computed<SelectionCandidate[]>(() => {
  if (!materialized.value) return [];
  return (payload.value?.research_candidates || []).filter((candidate) =>
    Boolean(candidate && candidate.candidate_id),
  );
});

const researchCount = computed(() => {
  const count = payload.value?.counts?.research_candidates;
  return typeof count === "number" ? count : researchCandidates.value.length;
});

const formalIds = computed(() => payload.value?.formal_shortlist || []);
const formalIdSet = computed(() => new Set(formalIds.value));

const formalCandidates = computed(() => formalIds.value
  .map((id) => researchCandidates.value.find((candidate) => candidate.candidate_id === id))
  .filter((candidate): candidate is SelectionCandidate => Boolean(candidate)));

const bucketOptions = computed(() => [...new Set(
  researchCandidates.value.map((candidate) => String(candidate.bucket || "CANNOT_CONFIRM")),
)].sort());

const filteredCandidates = computed(() => {
  const query = searchQuery.value.trim().toLowerCase();
  return researchCandidates.value.filter((candidate) => {
    const bucketMatches = bucketFilter.value === "ALL" || candidate.bucket === bucketFilter.value;
    return bucketMatches && (!query || searchText(candidate).includes(query));
  });
});

const managerPool = computed(() => preselectionPayload.value?.pools?.find((pool) =>
  pool.pool_id === "hkconnect_d1_top100",
) || null);

const managerStageCanRender = computed(() => stageState.value === "READY"
  && Boolean(stagePayload.value)
  && (
    isManagerHkStageRenderable(stagePayload.value)
    || isEmptyManagerStagePendingEnvelope(stagePayload.value, requestedDate.value)
  ));

const managerStageRows = computed<ManagerStageSelectionRow[]>(() => {
  if (!managerStageCanRender.value || !stagePayload.value) return [];
  return getManagerHkStageRows(stagePayload.value);
});

type ManagerStagePriorityEvidence = Readonly<{
  status: string;
  cannotConfirm: readonly string[];
}>;

function managerStagePriorityEvidence(value: ManagerStageSelectionResponse | null): ManagerStagePriorityEvidence {
  const payload = asRecord(value);
  const market = getManagerHkStageMarket(value);
  const lane = asRecord(market);
  const topStatus = typeof payload?.status === "string" ? payload.status : null;
  const laneStatus = typeof lane?.status === "string" ? lane.status : null;
  const laneSelectionStatus = typeof lane?.selection_status === "string" ? lane.selection_status : null;
  const gaps = new Set<string>();
  const collectGaps = (source: Record<string, unknown> | null) => {
    if (!source) return;
    for (const key of ["cannot_confirm", "gaps", "promotion_missing_fields"]) {
      const parsed = parseGapValue(source[key]);
      if (parsed.kind === "values") parsed.values.forEach((gap) => gaps.add(gap));
      if (parsed.kind === "invalid" && hasOwn(source, key)) gaps.add("CANNOT_CONFIRM");
    }
  };
  collectGaps(payload);
  collectGaps(lane);
  if (!topStatus || !laneStatus || !laneSelectionStatus
    || topStatus !== laneStatus || laneStatus !== laneSelectionStatus) {
    gaps.add("STAGE_STATUS_CONFLICT");
    return { status: "CANNOT_CONFIRM", cannotConfirm: [...gaps] };
  }
  return { status: laneStatus, cannotConfirm: [...gaps] };
}

const managerStagePriorityEvidenceValue = computed(() => managerStagePriorityEvidence(stagePayload.value));

type ShanghaiClockParts = Readonly<{
  date: string;
  minutes: number;
}>;

function shanghaiClockParts(now: Date): ShanghaiClockParts | null {
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
function isBeforeManagerStageSlot(targetDate: string, now = new Date()): boolean {
  const clock = shanghaiClockParts(now);
  return Boolean(clock && clock.date === targetDate && clock.minutes < (9 * 60 + 40));
}

function isEmptyManagerStagePendingEnvelope(value: unknown, targetDate: string): boolean {
  const payload = asRecord(value);
  const markets = asRecord(payload?.markets);
  const hk = asRecord(markets?.HK);
  return Boolean(
    payload
    && payload.trade_date === targetDate
    && isBeforeManagerStageSlot(targetDate)
    && Array.isArray(hk?.rows)
    && hk.rows.length === 0
    && (payload.status === "CANNOT_CONFIRM" || payload.status === "READY_EMPTY")
    && (hk.status === "CANNOT_CONFIRM" || hk.status === "READY_EMPTY")
    && (hk.selection_status === "CANNOT_CONFIRM" || hk.selection_status === "READY_EMPTY")
  );
}

const managerStagePending = computed(() => managerStageCanRender.value
  && managerStageRows.value.length === 0
  && isBeforeManagerStageSlot(requestedDate.value));

function managerBasisValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "CANNOT_CONFIRM";
  return String(value);
}

const MANAGER_RESEARCH_COVERAGE_FALLBACK = "仅依据已解析官方财报结构化事实；近期重大事件（含合作/公告）覆盖未确认。";

function managerInvestmentAdviceCoverage(row: ManagerPriorityRow): string {
  return row.investmentAdvice.coverageScope || MANAGER_RESEARCH_COVERAGE_FALLBACK;
}

function managerInvestmentBasisSummary(row: ManagerPriorityRow): string {
  const basis = row.investmentAdvice.basis;
  if (!basis.length) return "CANNOT_CONFIRM（后端未返回 basis）";
  return basis
    .filter((item) => item.dimension || item.state)
    .map((item) => {
      const dimension = item.dimension || "UNKNOWN";
      const state = item.state || "CANNOT_CONFIRM";
      const currentLabel = item.currentColumn || "当前";
      const previousLabel = item.previousColumn || "前期";
      const period = item.period || "CANNOT_CONFIRM_PERIOD";
      const unit = [item.currency, item.unit].filter(Boolean).join("/") || "CANNOT_CONFIRM_UNIT";
      return `${dimension}=${state}（${currentLabel}=${managerBasisValue(item.current)}；${previousLabel}=${managerBasisValue(item.previous)}；${period}；${unit}）`;
    })
    .join("；") || "CANNOT_CONFIRM（后端 basis 为空）";
}

function managerInvestmentBasisRefText(ref: Record<string, unknown>): string {
  const sha = typeof ref.source_sha256 === "string" && ref.source_sha256.trim()
    ? ref.source_sha256.trim()
    : "CANNOT_CONFIRM_SHA";
  const locator = typeof ref.locator === "string" && ref.locator.trim() ? ref.locator.trim() : "CANNOT_CONFIRM_LOCATOR";
  const page = typeof ref.page === "number" ? ` · page=${ref.page}` : "";
  return `source_sha256=${sha} · locator=${locator}${page}`;
}

const managerResearchRows = computed(() => {
  const product = managerResearchPayload.value?.product;
  if (!product || !["READY", "PARTIAL_WITH_ROWS"].includes(managerResearchState.value)) return [];
  return product.rows;
});

type ManagerCatalystCard = Readonly<{
  code: string;
  name: string;
  status: string;
  advice: Record<string, unknown>;
  events: readonly Record<string, unknown>[];
  sourceCoverage: readonly Record<string, unknown>[];
  currentEventAsOf: string;
  gaps: readonly string[];
}>;

type ManagerReadingMaterial = Readonly<{
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

type ManagerReadingAssociation = Readonly<{
  code: string;
  name: string;
}>;

type ManagerReadingStockStatus = Readonly<{
  code: string;
  name: string;
  status: string;
  materialCount: number;
  gaps: readonly string[];
}>;

function recordList(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.map((item) => asRecord(item)).filter((item): item is Record<string, unknown> => Boolean(item))
    : [];
}

const managerCatalystCards = computed<readonly ManagerCatalystCard[]>(() => {
  const product = managerResearchPayload.value?.product;
  if (!product) return [];
  const cards: ManagerCatalystCard[] = [];
  for (const rawRow of product.rows) {
    const row = asRecord(rawRow);
    const result = asRecord(row?.catalyst_result);
    if (!row || !result) continue;
    const events = recordList(result.events);
    const advice = asRecord(result.catalyst_advice) || {};
    if (!events.length && advice.status !== "OBSERVE") continue;
    const gaps: string[] = [];
    const rawGaps = Array.isArray(result.market_confirmation_gap)
      ? result.market_confirmation_gap.filter((item): item is string => typeof item === "string" && Boolean(item.trim()))
      : [];
    cards.push({
      code: typeof row.code === "string" ? row.code : "CANNOT_CONFIRM",
      name: typeof row.name === "string" ? row.name : "CANNOT_CONFIRM",
      status: typeof result.status === "string" ? result.status : "CANNOT_CONFIRM",
      advice,
      events,
      sourceCoverage: recordList(result.source_coverage),
      currentEventAsOf: typeof result.current_event_as_of === "string" ? result.current_event_as_of : "CANNOT_CONFIRM",
      gaps: [...new Set([...gaps, ...rawGaps])],
    });
  }
  return cards.sort((left, right) => {
    const leftRank = typeof left.advice.priority_rank === "number" ? left.advice.priority_rank : Number.MAX_SAFE_INTEGER;
    const rightRank = typeof right.advice.priority_rank === "number" ? right.advice.priority_rank : Number.MAX_SAFE_INTEGER;
    return leftRank - rightRank || left.code.localeCompare(right.code);
  });
});

const managerCatalystFocusCards = computed<readonly ManagerCatalystCard[]>(() => managerCatalystCards.value
  .filter((card) => card.advice.focus_eligible === true && Number.isSafeInteger(card.advice.priority_rank))
  .sort((left, right) => Number(left.advice.priority_rank) - Number(right.advice.priority_rank))
  .slice(0, 3));

const managerReadingStockOptions = computed(() => managerResearchRows.value.map((rawRow) => {
  const row = asRecord(rawRow) || {};
  return {
    code: typeof row.code === "string" ? row.code : "CANNOT_CONFIRM",
    name: typeof row.name === "string" ? row.name : "CANNOT_CONFIRM",
  };
}));

const managerReadingStockStatuses = computed<readonly ManagerReadingStockStatus[]>(() => managerResearchRows.value.map((rawRow) => {
  const row = asRecord(rawRow) || {};
  const result = asRecord(row.catalyst_result) || {};
  const bundle = asRecord(result.reader_bundle);
  const rawGaps = Array.isArray(result.reader_source_gaps)
    ? result.reader_source_gaps
    : Array.isArray(bundle?.source_gaps) ? bundle.source_gaps : [];
  const gaps = [...new Set(rawGaps.filter((item): item is string => typeof item === "string" && Boolean(item.trim())))];
  const rawMaterials = Array.isArray(result.reader_materials)
    ? result.reader_materials
    : Array.isArray(bundle?.materials) ? bundle.materials : [];
  return {
    code: typeof row.code === "string" ? row.code : "CANNOT_CONFIRM",
    name: typeof row.name === "string" ? row.name : "CANNOT_CONFIRM",
    status: catalystText(result.reader_status || row.reader_status || bundle?.status, "CANNOT_CONFIRM"),
    materialCount: rawMaterials.length,
    gaps,
  };
}));

function readingSourceUrl(value: unknown): string {
  const raw = typeof value === "string" ? value.trim() : "";
  if (!raw || /\s/.test(raw)) return "";
  try {
    const parsed = new URL(raw);
    return (parsed.protocol === "http:" || parsed.protocol === "https:") && parsed.hostname ? parsed.toString() : "";
  } catch {
    return "";
  }
}

const READING_SOURCE_TIME_ZONE_OFFSET_MINUTES = 8 * 60;

/**
 * Normalize source timestamps before sorting.  Eastmoney's public-news
 * timestamps are naive Asia/Shanghai values; ISO timestamps with an explicit
 * offset keep the offset supplied by the source.  A missing or malformed
 * timestamp remains unknown and is deliberately sorted last.
 */
function readingPublishedEpoch(value: string): number | null {
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

function readingUpperBoundEpoch(value: string): number | null {
  if (!isRealDate(value)) return null;
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(4, 6));
  const day = Number(value.slice(6, 8));
  return Date.UTC(year, month - 1, day + 1)
    - READING_SOURCE_TIME_ZONE_OFFSET_MINUTES * 60 * 1000;
}

function readingMaterialIsWithinUpperBound(material: ManagerReadingMaterial, upperBound: string): boolean {
  const published = readingPublishedEpoch(material.publishedAt);
  const bound = readingUpperBoundEpoch(upperBound);
  if (published === null || bound === null) return true;
  return published < bound;
}

function readingAssociation(row: Record<string, unknown>): ManagerReadingAssociation {
  return {
    code: catalystText(row.code),
    name: catalystText(row.name),
  };
}

type ReadingEventSourceKind = "MEDIA" | "OFFICIAL" | "UNKNOWN";

function readingEventSourceKind(event: Record<string, unknown>): ReadingEventSourceKind {
  const rawKind = catalystText(event.source_kind, "").toUpperCase();
  if (rawKind === "MEDIA") return "MEDIA";
  if (rawKind === "OFFICIAL") return "OFFICIAL";
  return "UNKNOWN";
}

function readingEventSourceName(event: Record<string, unknown>, sourceKind: ReadingEventSourceKind): string {
  const sourceName = catalystText(event.source_name, "");
  if (sourceName) return sourceName;
  const sourceId = catalystText(event.source_id, "");
  if (sourceId) return sourceId;
  return sourceKind === "MEDIA" ? "行业媒体" : "来源未标";
}

function readingMaterialFromEvent(row: Record<string, unknown>, event: Record<string, unknown>): ManagerReadingMaterial {
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

function readingMaterialFromPublic(row: Record<string, unknown>, item: Record<string, unknown>): ManagerReadingMaterial {
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

function mergeReadingMaterials(left: ManagerReadingMaterial, right: ManagerReadingMaterial): ManagerReadingMaterial {
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

const managerReadingMaterials = computed<readonly ManagerReadingMaterial[]>(() => {
  const selectedCode = readingStockFilter.value;
  const upperBound = readingDateUpperBound.value || requestedDate.value;
  const byKey = new Map<string, ManagerReadingMaterial>();
  for (const rawRow of managerResearchRows.value) {
    const row = asRecord(rawRow);
    if (!row) continue;
    const code = typeof row.code === "string" ? row.code : "";
    if (selectedCode !== "ALL" && code !== selectedCode) continue;
    const result = asRecord(row.catalyst_result);
    if (!result) continue;
    for (const rawItem of recordList(result.reader_materials)) {
      const material = readingMaterialFromPublic(row, rawItem);
      if (!readingMaterialIsWithinUpperBound(material, upperBound)) continue;
      const key = material.sourceUrl || `${material.title}|${material.publishedAt}|${material.excerpt}`;
      const prior = byKey.get(key);
      if (!prior) byKey.set(key, material);
      else byKey.set(key, mergeReadingMaterials(prior, material));
    }
    for (const event of recordList(result.events)) {
      const material = readingMaterialFromEvent(row, event);
      if (!readingMaterialIsWithinUpperBound(material, upperBound)) continue;
      const key = material.sourceUrl || `${material.title}|${material.publishedAt}|${material.excerpt}`;
      const prior = byKey.get(key);
      if (!prior) byKey.set(key, material);
      else byKey.set(key, mergeReadingMaterials(prior, material));
    }
  }
  return [...byKey.values()].sort((left, right) => {
    const leftEpoch = readingPublishedEpoch(left.publishedAt);
    const rightEpoch = readingPublishedEpoch(right.publishedAt);
    if (leftEpoch === null && rightEpoch !== null) return 1;
    if (leftEpoch !== null && rightEpoch === null) return -1;
    if (leftEpoch !== null && rightEpoch !== null && leftEpoch !== rightEpoch) return rightEpoch - leftEpoch;
    return left.code.localeCompare(right.code) || left.id.localeCompare(right.id);
  });
});

const managerReadingSummary = computed(() => {
  const count = managerReadingMaterials.value.length;
  const candidates = new Set(managerReadingMaterials.value.map((item) => item.code)).size;
  return `资料 ${count} 条 · 覆盖候选 ${candidates} 只 · 按发布时间倒序；资料源为有界公开检索，未声明全日覆盖。`;
});

const managerCatalystAuditRows = computed(() => {
  const product = managerResearchPayload.value?.product;
  if (!product) return [];
  return product.rows.map((rawRow) => {
    const row = asRecord(rawRow) || {};
    const result = asRecord(row.catalyst_result) || {};
    return {
      code: catalystText(row.code),
      name: catalystText(row.name),
      status: catalystText(result.status),
      advice: asRecord(result.catalyst_advice) || {},
      events: recordList(result.events),
      sourceReceipts: recordList(result.source_receipts),
    };
  });
});

const managerCatalystSourceCounts = computed<readonly unknown[]>(() => {
  const product = managerResearchPayload.value?.product as Record<string, unknown> | null | undefined;
  return Array.isArray(product?.catalyst_source_counts) ? product.catalyst_source_counts : [];
});

const managerCatalystCoverage = computed(() => {
  const product = managerResearchPayload.value?.product as Record<string, unknown> | null | undefined;
  const coverage = asRecord(product?.catalyst_coverage);
  if (!coverage) return "CANNOT_CONFIRM（资料阅读源尚未运行）";
  const events = typeof coverage.event_count === "number" ? coverage.event_count : "CANNOT_CONFIRM";
  const current = typeof coverage.current_event_count === "number" ? coverage.current_event_count : "CANNOT_CONFIRM";
  const historical = typeof coverage.historical_event_count === "number" ? coverage.historical_event_count : "CANNOT_CONFIRM";
  const readerCoverage = asRecord(product?.reader_coverage);
  const readerCount = typeof readerCoverage?.material_count === "number"
    ? readerCoverage.material_count
    : typeof coverage.reader_material_count === "number" ? coverage.reader_material_count : "CANNOT_CONFIRM";
  const readerStatus = typeof readerCoverage?.status === "string" ? readerCoverage.status : "CANNOT_CONFIRM";
  const completeness = typeof coverage.completeness === "string" ? coverage.completeness : "CANNOT_CONFIRM";
  return `资料 ${readerCount} 条（reader=${readerStatus}）· 原事件 ${events} 条（当前补充 ${current}；历史 ${historical}）· ${completeness} · 未声明全日覆盖`;
});

function catalystText(value: unknown, fallback = "CANNOT_CONFIRM"): string {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return fallback;
}

function catalystTextList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && Boolean(item.trim())).map((item) => item.trim())
    : [];
}

type CatalystSemanticClass = "ELIGIBLE" | "UNCONFIRMED" | "NON_SUBSTANTIVE";

function catalystSemanticClass(event: Record<string, unknown>): CatalystSemanticClass {
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

function catalystSemanticClassLabel(event: Record<string, unknown>): string {
  return {
    ELIGIBLE: "当前投影：可解释准入",
    UNCONFIRMED: "当前投影：待核实",
    NON_SUBSTANTIVE: "当前投影：非实质材料",
  }[catalystSemanticClass(event)];
}

const CATALYST_SOURCE_KIND_LABELS: Record<string, string> = {
  MEDIA: "行业媒体",
  OFFICIAL: "官方公告",
};

function catalystSourceLabel(event: Record<string, unknown>): string {
  const kind = catalystText(event.source_kind);
  const kindLabel = CATALYST_SOURCE_KIND_LABELS[kind] || kind;
  const sourceId = catalystText(event.source_id);
  return `${kindLabel} · ${sourceId}`;
}

function catalystSourceUrl(event: Record<string, unknown>): string {
  const raw = typeof event.source_url === "string" ? event.source_url.trim() : "";
  if (!raw) return "";
  try {
    const parsed = new URL(raw);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.toString() : "";
  } catch {
    return "";
  }
}

const CATALYST_CONFIRMATION_LABELS: Record<string, string> = {
  PENDING: "待官方确认",
  BODY_NOT_PARSED: "正文未解析",
  OFFICIAL_BODY_PARSED: "官方正文已解析",
  CANNOT_CONFIRM: "不可确认",
};

function catalystConfirmationLabel(event: Record<string, unknown>): string {
  const raw = catalystText(event.official_confirmation_status);
  return CATALYST_CONFIRMATION_LABELS[raw] || raw;
}

const CATALYST_DIMENSION_LABELS: Record<string, string> = {
  PROFIT_LOSS: "法定利润/亏损",
  OPERATING_CASHFLOW: "经营活动现金流",
  CASH: "现金及现金等价物",
  LIABILITIES: "负债",
  OPERATING_LOSS: "经营亏损",
  RECEIVABLE_IMPAIRMENT: "应收账款减值",
  REVENUE: "收入",
  GROSS_PROFIT: "毛利",
};
const CATALYST_STATE_LABELS: Record<string, string> = {
  POSITIVE: "正值",
  NEGATIVE: "负值",
  MIXED: "混合",
  CONFLICT: "冲突",
  MISSING: "缺失",
};
const CATALYST_CURRENCY_LABELS: Record<string, string> = {
  RMB: "人民币",
  CNY: "人民币",
  HKD: "港元",
  USD: "美元",
  S$: "新加坡元",
  SGD: "新加坡元",
};
const CATALYST_UNIT_LABELS: Record<string, string> = {
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

function catalystFinancialRefText(ref: Record<string, unknown>): string {
  const dimensionRaw = catalystText(ref.dimension, "CANNOT_CONFIRM_DIMENSION");
  const dimension = CATALYST_DIMENSION_LABELS[dimensionRaw] || dimensionRaw;
  const stateRaw = catalystText(ref.state, "CANNOT_CONFIRM_STATE");
  const state = CATALYST_STATE_LABELS[stateRaw] || stateRaw;
  const currencyRaw = catalystText(ref.currency, "CANNOT_CONFIRM_CURRENCY");
  const currency = CATALYST_CURRENCY_LABELS[currencyRaw] || currencyRaw;
  const unitRaw = catalystText(ref.unit, "CANNOT_CONFIRM_UNIT");
  const unit = CATALYST_UNIT_LABELS[unitRaw] || unitRaw;
  return `${dimension}：${state}；当前=${managerBasisValue(ref.current)}；前期=${managerBasisValue(ref.previous)}；期间=${catalystText(ref.period, "CANNOT_CONFIRM_PERIOD")}；口径=${currency}/${unit}`;
}

function catalystFinancialEvidence(event: Record<string, unknown>): string[] {
  const refs = recordList(event.financial_counterevidence_refs);
  if (refs.length) return refs.map(catalystFinancialRefText);
  return catalystTextList(event.financial_counterevidence);
}

function catalystRealizationConditions(event: Record<string, unknown>): string[] {
  if (event.event_type === "MARKET_ACCESS") {
    return [
      `官方名单纳入=${catalystText(event.inclusion_status)}；生效日=${catalystText(event.effective_date)}`,
      `实际可交易性/流动性=${catalystText(event.liquidity_confirmation)}；纳入本身不等于订单、收入或生产兑现。`,
    ];
  }
  return catalystTextList(event.realization_conditions);
}

const CATALYST_GAP_LABELS: Record<string, string> = {
  MEDIA_ONLY_OFFICIAL_CONFIRMATION_PENDING: "官方确认待补",
  ORDER_OR_REVENUE_UNCONFIRMED: "订单/收入未确认",
  MARKET_PRICE_VOLUME_UNCONFIRMED: "量价未确认",
  DIRECTORY_ONLY_BODY_NOT_PARSED: "目录线索，正文未解析",
  BUSINESS_SUMMARY_UNCONFIRMED: "业务摘要待核实",
};

function catalystRiskSummary(card: ManagerCatalystCard): string {
  const event = catalystFocusEvents(card)[0] || card.events[0];
  const gaps = event ? catalystTextList(event.market_confirmation_gap) : [];
  const readableGaps = gaps.map((gap) => CATALYST_GAP_LABELS[gap] || gap).slice(0, 2);
  if (event && event.official_confirmation_status === "PENDING") readableGaps.unshift("官方确认待补");
  if (!readableGaps.length) readableGaps.push("兑现条件仍待核验");
  return `风险边界：${[...new Set(readableGaps)].join("；")}`;
}

const managerCatalystProjectionSummary = computed<{
  eligible: number;
  unconfirmed: number;
  nonSubstantive: number;
}>(() => {
  const events = managerCatalystCards.value.flatMap((card) => card.events);
  const summary = { eligible: 0, unconfirmed: 0, nonSubstantive: 0 };
  for (const event of events) {
    const semanticClass = catalystSemanticClass(event);
    if (semanticClass === "ELIGIBLE") summary.eligible += 1;
    if (semanticClass === "UNCONFIRMED") summary.unconfirmed += 1;
    if (semanticClass === "NON_SUBSTANTIVE") summary.nonSubstantive += 1;
  }
  return summary;
});

function catalystSourceCountText(value: unknown): string {
  const count = asRecord(value);
  if (!count) return displayValue(value);
  const source = catalystText(count.source_label || count.source_id);
  const rawSubstantive = typeof count.substantive_body === "number" ? count.substantive_body : null;
  if (rawSubstantive !== null) {
    return `${source}：采集时原始正文计数 ${rawSubstantive}（仅作回执审计；当前准入按事件投影重算）`;
  }
  return displayValue(value);
}

function catalystEvidenceStatus(event: Record<string, unknown>): string {
  if (event.body_parsed === true) return "正文已解析";
  if (event.evidence_level === "OFFICIAL_DIRECTORY_ONLY" || event.body_parsed === false) return "DIRECTORY_ONLY 目录线索（正文未解析）";
  return "CANNOT_CONFIRM";
}

function catalystTimingStatus(event: Record<string, unknown>): string {
  const bucket = event.as_of_bucket;
  if (bucket === "historical") return "历史证据；不等于09:40系统已消费";
  if (bucket === "current") return "当前补充；不回写历史09:40";
  return "CANNOT_CONFIRM（事件时间桶缺失）";
}

function catalystFocusEvents(card: ManagerCatalystCard): readonly Record<string, unknown>[] {
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

function catalystAuditEventLabel(event: Record<string, unknown>): string {
  if (event.summary_status === "UNCONFIRMED" || event.event_status === "CANNOT_CONFIRM") {
    return "摘要待核实，不进入焦点";
  }
  if (event.body_parsed !== true) return "目录线索，正文未解析，不进入焦点";
  return "正文已解析";
}

const managerPrioritySummary = computed(() => buildManagerPrioritySummary({
  stageRows: managerStageRows.value,
  stageStatus: managerStagePriorityEvidenceValue.value.status,
  stageCannotConfirm: managerStagePriorityEvidenceValue.value.cannotConfirm,
  managerResearchRows: managerResearchRows.value,
  managerResearchStatus: managerResearchState.value,
  managerResearchCutoffAt: typeof managerResearchPayload.value?.cutoff_at === "string"
    ? managerResearchPayload.value.cutoff_at
    : null,
  managerResearchRecommendationSummary: managerResearchPayload.value?.product
    ? (managerResearchPayload.value.product as Record<string, unknown>).recommendation_summary
    : null,
  targetDate: requestedDate.value,
}));

const managerPriorityRows = computed<readonly ManagerPriorityRow[]>(() =>
  managerStagePending.value ? [] : managerPrioritySummary.value.rows,
);

const managerResearchPriorityRows = computed<readonly ManagerPriorityRow[]>(() =>
  managerStagePending.value ? [] : managerPrioritySummary.value.researchPriorityRows.slice(0, 2),
);

const workbenchResearchCandidates = computed<readonly ManagerWorkbenchCandidate[]>(() =>
  workbenchResearchState.value === "LOADING"
    ? []
    : workbenchResearchPayload.value?.candidates || [],
);

const WORKBENCH_SOURCE_LABELS: Readonly<Record<string, string>> = {
  STAGE: "原有阶段候选",
  CLOSE_DISCOVERY: "15:30尾盘发现",
  CONTINUOUS_TRACKING: "持续跟踪",
};

function workbenchSymbolKey(value: unknown): string {
  const code = normalizeManagerHkCode(value);
  return code ? `HK.${code}` : "";
}

function workbenchCandidateForStage(row: ManagerPriorityRow): ManagerWorkbenchCandidate | null {
  const key = workbenchSymbolKey(row.code);
  return workbenchResearchCandidates.value.find((candidate) => workbenchSymbolKey(candidate.symbol) === key) || null;
}

function workbenchSourceLabels(candidate: ManagerWorkbenchCandidate | null, includeStage = false): string[] {
  const labels = includeStage ? [WORKBENCH_SOURCE_LABELS.STAGE] : [];
  if (candidate) {
    for (const lane of candidate.source_lanes) {
      labels.push(WORKBENCH_SOURCE_LABELS[lane] || lane);
    }
  }
  return [...new Set(labels)];
}

function workbenchCandidateMatchesFilter(candidate: ManagerWorkbenchCandidate): boolean {
  const filter = workbenchSourceFilter.value;
  if (filter === "ALL") return true;
  if (filter === "STAGE") return false;
  return candidate.source_lanes.includes(filter);
}

const visibleManagerPriorityRows = computed<readonly ManagerPriorityRow[]>(() => {
  const filter = workbenchSourceFilter.value;
  if (filter === "ALL" || filter === "STAGE") {
    return managerPriorityRows.value;
  }
  return managerPriorityRows.value.filter((row) => {
    const candidate = workbenchCandidateForStage(row);
    return candidate?.source_lanes.includes(filter) === true;
  });
});

const discoveryOnlyCandidates = computed<readonly ManagerWorkbenchCandidate[]>(() => {
  if (workbenchSourceFilter.value === "STAGE") return [];
  const stageSymbols = new Set(managerPriorityRows.value.map((row) => workbenchSymbolKey(row.code)).filter(Boolean));
  return workbenchResearchCandidates.value
    .filter((candidate) => !stageSymbols.has(workbenchSymbolKey(candidate.symbol)))
    .filter(workbenchCandidateMatchesFilter);
});

function workbenchCoverageText(payload: ManagerWorkbenchResearchResponse | null): string {
  if (!payload) return "覆盖未知";
  const { eligible_count: eligible, covered_count: covered, missing_count: missing } = payload.coverage;
  if (eligible === null || covered === null || missing === null) return "覆盖范围尚未核实";
  return `覆盖 ${covered}/${eligible} · 缺失 ${missing}`;
}

function workbenchStatusText(status: string): string {
  return readableStatus(status);
}

function workbenchShortReason(candidate: ManagerWorkbenchCandidate | null): string {
  if (candidate?.research_priority?.level === "UPGRADED_WATCH") return "新增直接催化，继续核对交易条件";
  if (candidate?.source_lanes.includes("CONTINUOUS_TRACKING")) return "前日观察延续，仍需核对完整条件";
  return "已记录当前行情，逐项核对研究条件";
}

function workbenchAudit(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function isWorkbenchResearchLoading(): boolean {
  return workbenchResearchState.value === "LOADING";
}

function workbenchRecordText(value: unknown, keys: readonly string[]): string {
  const record = asRecord(value);
  if (!record) return "CANNOT_CONFIRM";
  const parts = keys.flatMap((key) => {
    const item = record[key];
    if (item === undefined || item === null || item === "") return [];
    return [`${key}=${displayValue(item)}`];
  });
  return parts.length ? parts.join(" · ") : "CANNOT_CONFIRM";
}

function workbenchTurnoverText(candidate: ManagerWorkbenchCandidate | null): string {
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

function workbenchPlanList(candidate: ManagerWorkbenchCandidate | null, key: string): string {
  const plan = asRecord(candidate?.observation_plan);
  const value = plan?.[key];
  if (!Array.isArray(value)) return "CANNOT_CONFIRM";
  const rows = value.filter((item): item is string => typeof item === "string" && Boolean(item.trim()));
  return rows.length ? rows.join("；") : "CANNOT_CONFIRM";
}

function workbenchSummaryItems(kind: "focus" | "theme_changes" | "risk_upgrades"): readonly ManagerWorkbenchSummaryItem[] {
  return workbenchResearchPayload.value?.priority_summary[kind] || [];
}

function workbenchCandidateDomId(candidateId: string): string {
  return `workbench-candidate-${candidateId.replace(/[^A-Za-z0-9_-]+/g, "-")}`;
}

function workbenchStageCandidateDomId(row: ManagerPriorityRow): string | undefined {
  const candidate = workbenchCandidateForStage(row);
  return candidate ? workbenchCandidateDomId(candidate.candidate_id) : undefined;
}

function workbenchConfirmedEvidenceText(candidate: ManagerWorkbenchCandidate | null): string {
  if (!candidate) return "CANNOT_CONFIRM";
  const confirmed = candidate.predicates
    .filter((predicate) => predicate.value === true)
    .map((predicate) => `${predicate.predicate_id || "UNKNOWN_PREDICATE"}${predicate.reason ? `：${predicate.reason}` : ""}`);
  return confirmed.length ? confirmed.join("；") : "CANNOT_CONFIRM";
}

function workbenchSourceText(source: ManagerWorkbenchSourceRef): string {
  const lane = source.lane ? (WORKBENCH_SOURCE_LABELS[source.lane] || source.lane) : "UNKNOWN_LANE";
  const date = source.source_date || "CANNOT_CONFIRM_DATE";
  const run = source.run_id || "CANNOT_CONFIRM_RUN";
  const reason = source.reason || "CANNOT_CONFIRM_REASON";
  return `${lane} · date=${date} · run=${run} · ${reason}`;
}

function focusWorkbenchSummaryItem(item: ManagerWorkbenchSummaryItem): void {
  if (!item.candidate_id) return;
  workbenchSourceFilter.value = "ALL";
  globalThis.setTimeout(() => {
    const node = document.getElementById(workbenchCandidateDomId(item.candidate_id || ""));
    node?.scrollIntoView({ behavior: "smooth", block: "center" });
    const summary = node?.querySelector("summary") as HTMLElement | null;
    summary?.focus();
  }, 0);
}

const managerPriorityReady = computed(() => managerStageCanRender.value
  && !managerStagePending.value
  && managerStageRows.value.length > 0);

const managerStageCount = computed<number | null>(() => {
  if (!managerStageCanRender.value) return null;
  return managerStageRows.value.length;
});

const managerStageCountLabel = computed(() => {
  const shownStage = managerStageCanRender.value && !managerStagePending.value ? visibleManagerPriorityRows.value.length : 0;
  const shown = shownStage + discoveryOnlyCandidates.value.length;
  if (workbenchSourceFilter.value === "CLOSE_DISCOVERY" && !["READY", "READY_EMPTY", "PARTIAL"].includes(workbenchResearchState.value))
    return `当前显示 ${shown} 条 · 尾盘无有效结果`;
  if (managerStagePending.value && workbenchSourceFilter.value !== "CLOSE_DISCOVERY")
    return `当前显示 ${shown} 条 · 原Stage尚待生成`;
  return `当前显示 ${shown} 条`;

});

const managerPriorityHeadline = computed(() => {
  if (managerStagePending.value) return "09:40 阶段槽尚未到时；空响应仅表示待生成，不构成投资判断。";
  if (!managerStageCanRender.value) return "HK_CONNECT 阶段证据不可确认；不生成优先级结论。";
  if (!managerStageRows.value.length) return "HK_CONNECT 阶段已返回可验证空集（0 条）。";
  return `保留 ${managerPrioritySummary.value.retainedCount} 条阶段行；行动分类与研究优先级分开显示。`;
});

const managerStageStatus = computed(() => {
  if (stageState.value === "LOADING") return "LOADING";
  if (!managerStageCanRender.value || !stagePayload.value) return "CANNOT_CONFIRM";
  return managerStagePriorityEvidenceValue.value.status;
});

type ManagerStageMetric =
  | "stage_score"
  | "current_change_pct"
  | "pct_chg"
  | "volume_ratio"
  | "turnover";

function managerStageRowValue(row: ManagerStageSelectionRow, field: string): unknown {
  return (row as Record<string, unknown>)[field];
}

function managerStageRawText(value: unknown): string | null {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed && !["NaN", "Infinity", "-Infinity"].includes(trimmed) ? trimmed : null;
  }
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : null;
  if (typeof value === "boolean") return String(value);
  return null;
}

function managerStageName(row: ManagerStageSelectionRow): string {
  for (const field of ["name", "stock_name", "display_name", "symbol", "code"]) {
    const value = managerStageRawText(managerStageRowValue(row, field));
    if (value) return value;
  }
  return "CANNOT_CONFIRM";
}

function managerStageCode(row: ManagerStageSelectionRow): string {
  for (const field of ["code", "symbol"]) {
    const value = managerStageRawText(managerStageRowValue(row, field));
    if (value) return value;
  }
  return "CANNOT_CONFIRM";
}

function managerStageMetricAvailable(row: ManagerStageSelectionRow, field: ManagerStageMetric): boolean {
  const value = managerStageRowValue(row, field);
  return value !== undefined && value !== null && value !== "";
}

function managerStageMetricValue(row: ManagerStageSelectionRow, field: string): string {
  const value = managerStageRowValue(row, field);
  const text = managerStageRawText(value);
  return text || "CANNOT_CONFIRM";
}

function managerStagePercentValue(row: ManagerStageSelectionRow, field: ManagerStageMetric): string {
  const value = managerStageMetricValue(row, field);
  if (value === "CANNOT_CONFIRM" || value.endsWith("%")) return value;
  return `${value}%`;
}

function managerStageContributions(row: ManagerStageSelectionRow) {
  const contributionState = ["IDLE", "LOADING", "READY", "NOT_MATERIALIZED", "CANNOT_CONFIRM"].includes(
    managerResearchState.value,
  )
    ? managerResearchState.value as "IDLE" | "LOADING" | "READY" | "NOT_MATERIALIZED" | "CANNOT_CONFIRM"
    // The existing contribution adapter predates PARTIAL_WITH_ROWS.  A
    // contract-valid partial product still carries exact, joinable rows, so
    // let those rows render through its READY path while the surrounding
    // research banner keeps the PARTIAL_WITH_ROWS status visible.
    : managerResearchState.value === "PARTIAL_WITH_ROWS" && managerResearchPayload.value?.product
      ? "READY"
      : "CANNOT_CONFIRM";
  return buildStageReasonContributions({
    row,
    targetDate: requestedDate.value,
    researchLane: researchLanePayload.value,
    managerResearch: managerResearchPayload.value,
    managerResearchState: contributionState,
    stageSelection: stagePayload.value,
  });
}

function managerStageContribution(
  row: ManagerStageSelectionRow,
  key: (typeof STAGE_REASON_CONTRIBUTION_KEYS)[number],
): StageReasonContribution {
  return managerStageContributions(row)[key];
}

function managerStageContributionRefText(ref: StageReasonEvidenceRef): string {
  if (typeof ref === "string") return ref;
  return displayValue(ref);
}

function managerStageContributionDetails(
  row: ManagerStageSelectionRow,
  key: (typeof STAGE_REASON_CONTRIBUTION_KEYS)[number],
): readonly StageReasonContributionDetail[] {
  return managerStageContribution(row, key).details || [];
}

function managerStageContributionDetailUrl(detail: StageReasonContributionDetail): string {
  return typeof detail.source_url === "string" && /^https?:\/\//i.test(detail.source_url)
    ? detail.source_url
    : "";
}

function managerStageContributionDetailMeta(detail: StageReasonContributionDetail): string {
  const values = [
    detail.source,
    detail.published_at ? `原文=${detail.published_at}` : "",
    detail.fetched_at ? `获取=${detail.fetched_at}` : "",
    detail.stock_code || detail.stock_name ? `资料自带标的=${[detail.stock_code, detail.stock_name].filter(Boolean).join(" ")}` : "",
  ].filter(Boolean);
  return values.join(" · ") || "CANNOT_CONFIRM";
}

function managerStageAuditValue(row: ManagerStageSelectionRow, field: string): string {
  const value = managerStageRowValue(row, field);
  if (Array.isArray(value)) {
    const values = value.map((item) => managerStageRawText(item)).filter((item): item is string => Boolean(item));
    return values.length ? values.join("、") : "CANNOT_CONFIRM";
  }
  return managerStageRawText(value) || "CANNOT_CONFIRM";
}

function managerStageCardKey(row: ManagerStageSelectionRow, index: number): string {
  return `${managerStageCode(row)}-${managerStageMetricValue(row, "rank")}-${index}`;
}

function rawNumericValue(value: unknown): string {
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "CANNOT_CONFIRM";
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed && Number.isFinite(Number(trimmed)) ? trimmed : "CANNOT_CONFIRM";
  }
  return "CANNOT_CONFIRM";
}

function poolDisplayName(): string {
  return typeof managerPool.value?.display_name === "string" && managerPool.value.display_name.trim()
    ? managerPool.value.display_name
    : "CANNOT_CONFIRM";
}

const STRATEGY_LABELS: Record<string, string> = {
  prob_active: "活跃概率（prob_active）",
  prob_memory: "记忆概率（prob_memory）",
  prob_crash_reflow: "崩溃重流概率（prob_crash_reflow）",
};

function strategyLabel(value: unknown): string {
  const raw = typeof value === "string" && value.trim() ? value.trim() : "CANNOT_CONFIRM";
  return STRATEGY_LABELS[raw] || (raw === "CANNOT_CONFIRM" ? raw : `未识别策略（原值：${raw}）`);
}

function preselectionRowName(row: ManagerPreselectionRow): string {
  for (const field of ["stock_name", "name", "display_name"]) {
    const value = row[field];
    if (typeof value === "string" && value.trim()) return value;
  }
  return "CANNOT_CONFIRM";
}

function preselectionScore(row: ManagerPreselectionRow | null | undefined): string {
  return rawNumericValue(row?.pool_score);
}

function preselectionMetric(row: ManagerPreselectionRow | null | undefined, field: string): string {
  return rawNumericValue(row?.[field]);
}

function strategyValue(row: ManagerPreselectionRow | null | undefined): string {
  return strategyLabel(row?.selected_strategy);
}

function eventClassification(candidate: SelectionCandidate): string {
  const source = officialSource(candidate);
  const classification = source?.classification;
  return classification === undefined || classification === null || classification === ""
    ? "CANNOT_CONFIRM"
    : displayValue(classification);
}

const VERIFIED_OFFICIAL_SOURCE_CLASSES = new Set([
  "OFFICIAL_PDF_LEDGER_VERIFIED",
  "OFFICIAL_PDF_MARKDOWN_CONTENT_VERIFIED",
]);

function verifiedOfficialSourceClass(source: Record<string, unknown>): string | null {
  const value = source.source_class;
  return typeof value === "string" && VERIFIED_OFFICIAL_SOURCE_CLASSES.has(value) ? value : null;
}

function officialTextValue(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!trimmed || ["NaN", "Infinity", "-Infinity"].includes(trimmed)) return null;
  const parsed = parseStructuredValue(trimmed);
  return parsed !== undefined && typeof parsed !== "string" ? null : trimmed;
}

function officialSource(candidate: SelectionCandidate): Record<string, unknown> | null {
  const source = asRecord(supplyCard(candidate)?.source);
  if (!source || !verifiedOfficialSourceClass(source)) return null;
  if (!officialTextValue(source.classification) || !officialTextValue(source.evidence)) return null;
  return source;
}

function catalystStatement(value: unknown): string {
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

function officialClassificationRaw(candidate: SelectionCandidate): string {
  const source = officialSource(candidate);
  return source ? displayValue(source.classification) : "CANNOT_CONFIRM";
}

const CLASSIFICATION_LABELS: Record<string, string> = {
  RESULTS_OR_EARNINGS: "业绩/财报",
  BUSINESS_OR_REGULATORY_CATALYST: "业务/监管催化",
  FINANCING_OR_CAPITAL: "融资/资本动作",
};

function officialClassificationLabel(candidate: SelectionCandidate): string {
  const raw = officialClassificationRaw(candidate);
  if (raw === "CANNOT_CONFIRM") return raw;
  return CLASSIFICATION_LABELS[raw] || `未识别枚举（原值：${raw}）`;
}

function officialClassificationCopy(candidate: SelectionCandidate): string {
  const raw = officialClassificationRaw(candidate);
  return CLASSIFICATION_LABELS[raw] || "";
}

function officialEvidenceText(candidate: SelectionCandidate): string {
  const source = officialSource(candidate);
  return source ? displayValue(source.evidence) : "CANNOT_CONFIRM";
}

function officialSourceStatusRaw(candidate: SelectionCandidate): string {
  const source = officialSource(candidate);
  return source ? verifiedOfficialSourceClass(source) || "CANNOT_CONFIRM" : "CANNOT_CONFIRM";
}

function officialSourceStatusLabel(candidate: SelectionCandidate): string {
  const raw = officialSourceStatusRaw(candidate);
  if (raw === "OFFICIAL_PDF_LEDGER_VERIFIED") return "官方 PDF 台账材料已绑定";
  if (raw === "OFFICIAL_PDF_MARKDOWN_CONTENT_VERIFIED") return "本地官方 PDF/Markdown 材料已绑定";
  return raw;
}

function officialSourceRefs(candidate: SelectionCandidate): SelectionSourceRef[] {
  if (!officialSource(candidate)) return [];
  const supply = supplyCard(candidate);
  const values = Array.isArray(candidate.source_refs) && candidate.source_refs.length
    ? candidate.source_refs
    : Array.isArray(supply?.source_refs) ? supply.source_refs : [];
  return values.filter((item): item is SelectionSourceRef => Boolean(asRecord(item)));
}

function candidateSourceRefs(candidate: SelectionCandidate): SelectionSourceRef[] {
  const supply = supplyCard(candidate);
  const values = Array.isArray(candidate.source_refs) && candidate.source_refs.length
    ? candidate.source_refs
    : Array.isArray(supply?.source_refs) ? supply.source_refs : [];
  return values.filter((item): item is SelectionSourceRef => Boolean(asRecord(item)));
}

function modelReasonText(row: ManagerPreselectionRow | null | undefined): string {
  if (!row) {
    return preselectionState.value === "READY"
      ? "模型证据不可确认（目标日同码行缺失）"
      : "模型证据不可确认（D-1 预选池不可确认）";
  }
  return `模型在${poolDisplayName()}第${preselectionMetric(row, "pool_rank")}位、池分数${preselectionScore(row)}（策略${strategyValue(row)}）`;
}

function reasonSummary(candidate: SelectionCandidate, row: ManagerPreselectionRow | null | undefined): string {
  const route = row ? "进入 D-1 × 官方事件交叉研究队列" : "进入经理关注层研究范围";
  const official = officialSource(candidate)
    ? `匹配到官方${officialClassificationCopy(candidate)}材料`
    : "官方材料仍待核实";
  return `${route}；${official}，保持研究观察而不进入 formal。`;
}

function nonformalRiskSummary(candidate: SelectionCandidate): string {
  const gaps = typedGaps(candidate);
  if (!gaps.length || gaps.includes("未声明缺口")) {
    return "关键资格与证据仍需复核，当前保持非formal研究边界。";
  }
  return `仍需核实：${gaps.join("、")}；因此保持非formal研究边界。`;
}

function reasonValue(candidate: SelectionCandidate, field: string): string {
  return displayValue(candidateField(candidate, field));
}

function eligibilityPitSummary(candidate: SelectionCandidate): string {
  const eligibility = reasonValue(candidate, "eligibility");
  const pitStatus = reasonValue(candidate, "pit_status");
  const gap = eligibility !== "ELIGIBLE" || pitStatus !== "READY";
  return `exact eligibility/PIT：eligibility=${eligibility} · pit_status=${pitStatus}${gap ? "（缺失/不可确认）" : ""}`;
}

function openingObservationSummary(): string {
  const status = phaseStatus("0935");
  if (status === "READY") return "09:35：READY";
  if (status === "NOT_MATERIALIZED") return "09:35：NOT_MATERIALIZED（未物化）";
  return "09:35：CANNOT_CONFIRM（不可确认）";
}

function promotionAllowedValue(candidate: SelectionCandidate): string {
  const direct = candidateField(candidate, "promotion_allowed");
  const fallback = supplyCard(candidate)?.promotion_allowed;
  const value = direct !== undefined ? direct : fallback;
  return value === true ? "true" : value === false ? "false" : "CANNOT_CONFIRM";
}

function preselectionRowForCandidate(candidate: SelectionCandidate): ManagerPreselectionRow | null {
  const code = normalizeManagerHkCode(
    candidate.normalized_code || candidate.entity_id || candidate.candidate_id?.split("|")[0],
  );
  return code ? researchQueue.value.find((entry) => entry.normalizedCode === code)?.poolRow || null : null;
}

function selectionCatalyst(candidate: Readonly<Record<string, unknown>>): string {
  return catalystStatement(candidate.catalyst);
}

const queueReady = computed(() => queueState.value === "READY");

function managerQueueSortRank(candidate: SelectionCandidate): number {
  if (managerReviewStatus(candidate) !== "READY") return 2;
  const bucket = managerReviewBucket(candidate);
  if (bucket === "PRIORITY") return 0;
  if (bucket === "CONDITIONAL") return 1;
  if (bucket === "EXCLUDE") return 3;
  return 2;
}

const researchQueue = computed<ManagerResearchQueueEntry[]>(() => {
  return queueReady.value ? queueEntries.value : [];
});

function managerDeltaMembership(candidate: SelectionCandidate): string {
  const ids = managerDeltaIds.value;
  if (!ids) return "不可确认";
  return ids.has(candidate.candidate_id || "") ? "在" : "不在";
}

function researchQueueMembership(candidate: SelectionCandidate): string {
  if (!queueReady.value) return "不可确认";
  return researchQueue.value.some((entry) => entry.selectionCandidate.candidate_id === candidate.candidate_id)
    ? "在"
    : "不在";
}

const preselectionRowCount = computed<number | null>(() => {
  if (!queueReady.value || !preselectionPayload.value) return null;
  return getManagerHkPoolRows(preselectionPayload.value).length;
});

const preselectionRowsLabel = computed(() =>
  preselectionRowCount.value === null ? "数量未知（不可确认）" : `${preselectionRowCount.value} 条`,
);

const queueCountLabel = computed(() =>
  queueReady.value ? `${researchQueue.value.length} 条` : "不可确认（非0）",
);

const queueIssueText = computed(() => {
  if (queueState.value === "READY") return "";
  if (queueIssue.value) return queueIssue.value;
  if (preselectionIssue.value) return preselectionIssue.value;
  if (preselectionState.value === "LOADING") return "D-1 预选池仍在读取；数量未知。";
  return "D-1 预选池不可确认；数量未知。";
});

const formalAuthority = computed<FormalAuthority | null>(() => payload.value?.formal_authority || null);

function sameStringSet(left: string[], right: string[]): boolean {
  return left.length === right.length
    && new Set(left).size === left.length
    && new Set(right).size === right.length
    && left.every((item) => right.includes(item));
}

function managerDecisionValidationIssue(): string | null {
  const current = payload.value;
  if (!current || !materialized.value) return "经理决策证据不可确认";
  if (managerDecisionState.value === "LOADING") return "经理决策证据仍在读取。";
  if (managerDecisionState.value !== "READY" || !managerDecisionPayload.value) {
    return managerDecisionIssueText.value || "经理决策证据不可确认。";
  }

  const candidateIds = researchCandidates.value
    .map((candidate) => candidate.candidate_id)
    .filter((id): id is string => typeof id === "string");
  const dtoIssue = validateManagerDecisionResponse(
    managerDecisionPayload.value,
    requestedDate.value,
    candidateIds,
  );
  if (dtoIssue) return `经理决策 contract 未通过：${dtoIssue}。`;

  const snapshot = current.snapshots?.["2200"];
  if (!snapshot || snapshot.status !== "READY" || !Array.isArray(snapshot.candidate_ids)) {
    return "经理决策证据不可确认：2200 READY snapshot 缺失。";
  }
  const snapshotIds = snapshot.candidate_ids.filter((id): id is string => typeof id === "string");
  if (snapshotIds.length !== snapshot.candidate_ids.length) {
    return "经理决策证据不可确认：2200 candidate_ids 不可确认。";
  }
  const decisionIds = [
    ...managerDecisionPayload.value.core || [],
    ...managerDecisionPayload.value.conditional || [],
  ].map((row) => row.candidate_id);
  if (!sameStringSet(decisionIds, snapshotIds)) {
    return "经理决策证据不可确认：typed 经理决策与 2200 snapshot 不一致。";
  }
  return null;
}

const managerDecisionIssue = computed(() => managerDecisionValidationIssue());
const managerDecisionValid = computed(() => managerDecisionIssue.value === null);

type ManagerDecisionDisplay = ManagerDecisionRow & {
  role: ManagerDecisionRole;
  order: number;
};

const managerDecisionRowsById = computed(() => {
  const rows = new Map<string, ManagerDecisionDisplay>();
  const current = managerDecisionPayload.value;
  if (!current) return rows;
  for (const role of ["CORE", "CONDITIONAL"] as const) {
    const roleRows = Array.isArray(current[role === "CORE" ? "core" : "conditional"])
      ? current[role === "CORE" ? "core" : "conditional"] as ManagerDecisionRow[]
      : [];
    roleRows.forEach((row, index) => {
      rows.set(row.candidate_id, { ...row, role, order: index + 1 });
    });
  }
  return rows;
});

function managerDecision(candidate: SelectionCandidate): ManagerDecisionDisplay | null {
  if (!managerDecisionValid.value) return null;
  const id = candidate.candidate_id;
  return typeof id === "string" ? managerDecisionRowsById.value.get(id) || null : null;
}

const managerDecisionCandidates = computed(() => {
  if (!managerDecisionValid.value) return [];
  const current = managerDecisionPayload.value;
  if (!current) return [];
  const rows = [
    ...(current.core || []).map((row, index) => ({ row, role: "CORE" as const, order: index + 1 })),
    ...(current.conditional || []).map((row, index) => ({ row, role: "CONDITIONAL" as const, order: index + 1 })),
  ];
  return rows
    .map(({ row }) => researchCandidates.value.find((candidate) => candidate.candidate_id === row.candidate_id))
    .filter((candidate): candidate is SelectionCandidate => Boolean(candidate))
    .filter((candidate) => !formalIds.value.includes(candidate.candidate_id || ""))
});

const coreCandidates = computed(() => managerDecisionCandidates.value.filter(
  (candidate) => managerDecision(candidate)?.role === "CORE",
));

const conditionalCandidates = computed(() => managerDecisionCandidates.value.filter(
  (candidate) => managerDecision(candidate)?.role === "CONDITIONAL",
));

const managerDeltaIds = computed<Set<string> | null>(() => {
  const snapshot = payload.value?.snapshots?.["2200"];
  return snapshot?.status === "READY" && Array.isArray(snapshot.candidate_ids)
    ? new Set(snapshot.candidate_ids)
    : null;
});

const managerDeltaLabel = computed(() => {
  const ids = managerDeltaIds.value;
  return ids ? `${ids.size} 条` : "不可确认（非 0）";
});

const formalAuthorityStatus = computed(() => formalAuthority.value?.status || "CANNOT_CONFIRM");

function phaseSnapshot(phase: SelectionPhase): SelectionSnapshot | undefined {
  return payload.value?.snapshots?.[phase];
}

function phaseStatus(phase: SelectionPhase): string {
  if (!payload.value || !materialized.value) return displayStatus.value;
  return phaseSnapshot(phase)?.status || "CANNOT_CONFIRM";
}

function phaseCandidateLabel(phase: SelectionPhase): string {
  const status = phaseStatus(phase);
  const ids = phaseSnapshot(phase)?.candidate_ids || [];
  if (status === "READY") return `${ids.length} 个候选`;
  if (status === "NOT_MATERIALIZED") return phase === "1620" ? "候选/结果未物化（非 0）" : "候选未物化（非 0）";
  if (status === "CANNOT_CONFIRM") return phase === "1620" ? "候选/结果不可确认（非 0）" : "不可确认（非 0）";
  return "候选数量不可确认";
}

function phaseRunText(phase: SelectionPhase): string {
  const snapshot = phaseSnapshot(phase);
  if (!snapshot || snapshot.status !== "READY") return "无可验证 run";
  return [snapshot.run_id, snapshot.event_at].filter(Boolean).join(" · ") || "CANNOT_CONFIRM";
}

function valueOrCannotConfirm(value: unknown): string {
  return value === undefined || value === null || value === "" ? "CANNOT_CONFIRM" : String(value);
}

function lineageSha(part: "artifact" | "manifest" | "receipt" | "current"): string {
  const lineage = payload.value?.lineage as Record<string, unknown> | null | undefined;
  const direct = lineage?.[`${part}_sha256`];
  if (typeof direct === "string" && direct) return direct;
  const nested = asRecord(lineage?.[part]);
  const nestedSha = nested?.sha256 ?? nested?.[`${part}_sha256`];
  if (typeof nestedSha === "string" && nestedSha) return nestedSha;
  const topLevel = payload.value?.[`${part}_sha256`];
  if (typeof topLevel === "string" && topLevel) return topLevel;
  return "CANNOT_CONFIRM";
}

function safetyFlag(key: "RESEARCH_ONLY" | "production_allowed" | "buy_gate_updated" | "orders_sent", expected: boolean): string {
  const actual = payload.value?.[key];
  return actual === expected ? String(actual) : "CANNOT_CONFIRM";
}

function updateBrowserDate(date: string): void {
  window.history.replaceState({}, "", `/manager-selection/?date=${encodeURIComponent(date)}`);
}

function isCurrentRequest(sequence: number, date: string): boolean {
  return sequence === requestSequence && requestedDate.value === date;
}

type RequestContext = {
  sequence: number;
  date: string;
  controller: AbortController;
};

type RequestAttempt = {
  signal: AbortSignal;
  timeout: Promise<never>;
  timedOut: () => boolean;
  dispose: () => void;
};

function requestAttempt(parentSignal: AbortSignal, timeoutMs = REQUEST_TIMEOUT_MS): RequestAttempt {
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

function withRequestTimeout<T>(attempt: RequestAttempt, operation: Promise<T>): Promise<T> {
  return Promise.race([operation, attempt.timeout]);
}

function managerResearchStatus(value: ManagerResearchResponse): string {
  const status = (value as Record<string, unknown>).status;
  return typeof status === "string" && status.trim() ? status.trim().toUpperCase() : "CANNOT_CONFIRM";
}

function managerResearchJobId(value: ManagerResearchResponse): string | null {
  const response = value as Record<string, unknown>;
  const direct = response.job_id;
  if (typeof direct === "string" && direct.trim()) return direct.trim();
  const job = asRecord(response.job);
  const nested = job?.job_id;
  return typeof nested === "string" && nested.trim() ? nested.trim() : null;
}

function managerResearchGapText(value: ManagerResearchResponse): string[] {
  const response = value as Record<string, unknown>;
  const product = asRecord(response.product);
  const values = [product?.cannot_confirm, response.cannot_confirm]
    .flatMap((item) => Array.isArray(item) ? item : [item])
    .filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    .map((item) => item.trim());
  return [...new Set(values)];
}

function managerResearchCoverage(value: ManagerResearchResponse | null): string | null {
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

function managerResearchResultState(value: ManagerResearchResponse): AuxiliaryState {
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

function managerResearchResultIsActive(value: ManagerResearchResponse): boolean {
  if (value.product) return false;
  const status = managerResearchResultState(value);
  return status === "QUEUED" || status === "RUNNING";
}

function applyManagerResearchResult(
  value: ManagerResearchResponse,
  sequence: number,
  date: string,
): boolean {
  if (!isCurrentRequest(sequence, date)) return false;
  if (value.target_trade_date !== date) {
    managerResearchPayload.value = null;
    managerResearchState.value = "CANNOT_CONFIRM";
    managerResearchIssue.value = "V4 manager research 未返回同一 exact target date。";
    return false;
  }
  managerResearchPayload.value = value;
  const nextState = managerResearchResultState(value);
  managerResearchState.value = nextState;
  const gaps = managerResearchGapText(value);
  const coverage = managerResearchCoverage(value);
  if (value.product) {
    managerResearchIssue.value = gaps.length
      ? gaps.join("；")
      : nextState === "PARTIAL_WITH_ROWS"
        ? `V4 manager research PARTIAL_WITH_ROWS${coverage ? ` ${coverage}` : ""}；其余行保留 CANNOT_CONFIRM。`
        : "";
  } else {
    managerResearchIssue.value = gaps.length
      ? gaps.join("；")
      : `V4 manager research=${nextState}；产品尚未物化。`;
  }
  return managerResearchResultIsActive(value);
}

function waitForManagerResearchPoll(signal: AbortSignal): Promise<void> {
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

function failQueue(message: string): void {
  queueEntries.value = [];
  queueState.value = "CANNOT_CONFIRM";
  queueIssue.value = message;
}

function setStale(message = "目标日期证据不匹配，未展示候选。") {
  payload.value = null;
  state.value = "STALE";
  errorMessage.value = message;
  failQueue("selection 日期证据不可确认；未展示交叉研究队列。");
}

function failSelection(nextState: ViewState, message: string): void {
  payload.value = null;
  state.value = nextState;
  errorMessage.value = message;
  failQueue("selection 不可确认；未展示交叉研究队列。");
}

function failPreselection(message: string): void {
  preselectionPayload.value = null;
  preselectionState.value = "CANNOT_CONFIRM";
  preselectionIssue.value = message;
  failQueue(message);
}

function failStage(message: string): void {
  stagePayload.value = null;
  stageState.value = "CANNOT_CONFIRM";
  stageIssue.value = message;
}

function preselectionFailureMessage(reason: unknown): string {
  const message = reason instanceof Error ? reason.message : "响应不可确认";
  return message.startsWith("D-1 预选池读取失败")
    ? message
    : `D-1 预选池读取失败（${message}）。`;
}

function stageFailureMessage(reason: unknown): string {
  const message = reason instanceof Error ? reason.message : "响应不可确认";
  return message.startsWith("今日港股通阶段候选读取失败")
    ? message
    : `今日港股通阶段候选读取失败（${message}）。`;
}

function settleQueue(sequence: number, date: string): void {
  if (!isCurrentRequest(sequence, date)) return;
  if (preselectionState.value !== "READY" || !preselectionPayload.value) return;
  if (!payload.value || !materialized.value) {
    queueEntries.value = [];
    if (state.value === "LOADING") {
      queueState.value = "LOADING";
      queueIssue.value = "";
    } else {
      failQueue("selection 不可确认；未展示交叉研究队列。");
    }
    return;
  }
  const join = buildManagerResearchQueue(
    getManagerHkPoolRows(preselectionPayload.value),
    researchCandidates.value,
  );
  if (!isCurrentRequest(sequence, date)) return;
  if (join.issue) {
    failPreselection(`研究交叉队列 contract 未通过：${join.issue}。`);
    return;
  }
  queueEntries.value = [...join.entries].sort((left, right) => {
    const rankDelta = managerQueueSortRank(left.selectionCandidate)
      - managerQueueSortRank(right.selectionCandidate);
    if (rankDelta !== 0) return rankDelta;
    const leftPoolRank = Number(left.poolRow.pool_rank);
    const rightPoolRank = Number(right.poolRow.pool_rank);
    if (Number.isFinite(leftPoolRank) && Number.isFinite(rightPoolRank) && leftPoolRank !== rightPoolRank) {
      return leftPoolRank - rightPoolRank;
    }
    return left.normalizedCode.localeCompare(right.normalizedCode);
  });
  queueState.value = "READY";
  queueIssue.value = "";
}

async function loadSelectionForDate(context: RequestContext): Promise<void> {
  const { date, sequence } = context;
  const attempt = requestAttempt(context.controller.signal);
  try {
    const result = await withRequestTimeout(attempt, loadSelectionExact(date, attempt.signal));
    if (!isCurrentRequest(sequence, date)) return;
    if (!result || typeof result !== "object") {
      failSelection("CANNOT_CONFIRM", "exact selection 响应不是对象，未展示候选。");
      return;
    }
    if (result.target_trade_date !== date) {
      setStale();
      return;
    }
    if (result.requested_date !== undefined && result.requested_date !== null && result.requested_date !== date) {
      setStale("请求日期与响应日期证据不一致，未展示候选。");
      return;
    }
    if (result.endpoint_mode !== undefined && result.endpoint_mode !== "EXACT") {
      failSelection("CANNOT_CONFIRM", "响应不是 exact-date 模式，未展示候选。");
      return;
    }
    if (!result.status || !VALID_PRODUCT_STATUSES.has(result.status)) {
      failSelection(
        "CANNOT_CONFIRM",
        `响应状态不可识别（${String(result.status || "missing")}），未展示候选。`,
      );
      return;
    }
    const issue = await contractIssue(result, date);
    if (!isCurrentRequest(sequence, date)) return;
    if (issue) {
      failSelection("CANNOT_CONFIRM", `selection contract 未通过：${issue}。未展示候选。`);
      return;
    }
    payload.value = result;
    state.value = result.status as ViewState;
    settleQueue(sequence, date);
  } catch (reason) {
    if (!isCurrentRequest(sequence, date)) return;
    failSelection(
      "ERROR",
      `${reason instanceof Error ? reason.message : "经理选股工作台读取失败；未用其他日期替代。"}${attempt.timedOut() ? "（请求超时）" : ""}`,
    );
  } finally {
    attempt.dispose();
  }
}

async function loadPreselectionForDate(context: RequestContext): Promise<void> {
  const { date, sequence } = context;
  const attempt = requestAttempt(context.controller.signal);
  try {
    const result = await withRequestTimeout(attempt, loadManagerPreselectionExact(date, attempt.signal));
    if (!isCurrentRequest(sequence, date)) return;
    if (!result || typeof result !== "object" || Array.isArray(result)) {
      failPreselection("D-1 预选池读取失败（响应不是对象）。");
      return;
    }
    const issue = validateManagerPreselection(result, date);
    if (!isCurrentRequest(sequence, date)) return;
    if (issue) {
      failPreselection(`D-1 预选池 contract 未通过：${issue}。`);
      return;
    }
    preselectionPayload.value = result;
    preselectionState.value = "READY";
    preselectionIssue.value = "";
    settleQueue(sequence, date);
  } catch (reason) {
    if (!isCurrentRequest(sequence, date)) return;
    failPreselection(`${preselectionFailureMessage(reason)}${attempt.timedOut() ? "（请求超时）" : ""}`);
  } finally {
    attempt.dispose();
  }
}

async function loadStageForDate(context: RequestContext): Promise<void> {
  const { date, sequence } = context;
  const attempt = requestAttempt(context.controller.signal);
  try {
    const result = await withRequestTimeout(attempt, loadManagerStageSelectionExact(date, attempt.signal));
    if (!isCurrentRequest(sequence, date)) return;
    if (!result || typeof result !== "object" || Array.isArray(result)) {
      failStage("stage selection 响应不是对象；数量未知（CANNOT_CONFIRM）。");
      return;
    }
    const issue = validateManagerStageSelection(result, date);
    if (!isCurrentRequest(sequence, date)) return;
    if (issue) {
      failStage(`stage selection contract 未通过：${issue}；数量未知（CANNOT_CONFIRM）。`);
      return;
    }
    if (!isManagerHkStageRenderable(result)
      && !isEmptyManagerStagePendingEnvelope(result, date)) {
      failStage("stage selection 状态或 markets.HK lane 不可渲染；数量未知（CANNOT_CONFIRM）。");
      return;
    }
    stagePayload.value = result;
    stageState.value = "READY";
    stageIssue.value = "";
  } catch (reason) {
    if (!isCurrentRequest(sequence, date)) return;
    failStage(`${stageFailureMessage(reason)}${attempt.timedOut() ? "（请求超时）" : ""} 数量未知（CANNOT_CONFIRM）。`);
  } finally {
    attempt.dispose();
  }
}

async function loadManagerResearchForDate(context: RequestContext): Promise<void> {
  const { date, sequence } = context;
  const attempt = requestAttempt(context.controller.signal);
  try {
    let result = await withRequestTimeout(
      attempt,
      loadManagerResearchExact(date, { signal: attempt.signal }),
    );
    if (context.controller.signal.aborted || !isCurrentRequest(sequence, date)) return;
    let active = applyManagerResearchResult(result, sequence, date);

    // A missing exact-date product may be materialized once by the server-owned
    // ensure endpoint.  The browser never sends symbols, source URLs, or facts;
    // all identity and input binding stays on the V4 service side.
    if (active === false
      && !result.product
      && result.target_trade_date === date
      && managerResearchStatus(result) === "NOT_MATERIALIZED"
      && (result as Record<string, unknown>).can_ensure === true) {
      result = await withRequestTimeout(
        attempt,
        ensureManagerResearchExact(date, { signal: attempt.signal }),
      );
      if (context.controller.signal.aborted || !isCurrentRequest(sequence, date)) return;
      active = applyManagerResearchResult(result, sequence, date);
    }

    // QUEUED/RUNNING is an existing server job.  Poll only that job/status a
    // bounded number of times; FAILED and all other terminal states never
    // trigger another ensure or an unbounded retry loop.
    for (let poll = 0; active && poll < MANAGER_RESEARCH_POLL_LIMIT; poll += 1) {
      if (poll > 0) await waitForManagerResearchPoll(attempt.signal);
      if (context.controller.signal.aborted || !isCurrentRequest(sequence, date)) return;
      const jobId = managerResearchJobId(result);
      result = await withRequestTimeout(
        attempt,
        jobId
          ? loadManagerResearchJobExact(date, jobId, { signal: attempt.signal })
          : loadManagerResearchStatusExact(date, { signal: attempt.signal }),
      );
      if (context.controller.signal.aborted || !isCurrentRequest(sequence, date)) return;
      active = applyManagerResearchResult(result, sequence, date);
    }
    if (active && isCurrentRequest(sequence, date)) {
      managerResearchIssue.value = `V4 manager research=${managerResearchState.value}；已完成 ${MANAGER_RESEARCH_POLL_LIMIT} 次有限轮询，等待下次 exact 刷新。`;
    }
  } catch (reason) {
    if (context.controller.signal.aborted || !isCurrentRequest(sequence, date)) return;
    managerResearchPayload.value = null;
    managerResearchState.value = "CANNOT_CONFIRM";
    managerResearchIssue.value = reason instanceof Error
      ? `V4 manager research 读取失败（${reason.message}${attempt.timedOut() ? "；请求超时" : ""}）。`
      : `V4 manager research 读取失败（响应不可确认${attempt.timedOut() ? "；请求超时" : ""}）。`;
  } finally {
    attempt.dispose();
  }
}

async function refreshCatalystForDate(): Promise<void> {
  const date = requestedDate.value;
  const sequence = requestSequence;
  if (!isRealDate(date) || !managerResearchPayload.value?.product) {
    catalystRefreshState.value = "CANNOT_CONFIRM";
    catalystRefreshIssue.value = "财务研究产品尚未物化；催化刷新需要同一 exact 候选产品。";
    return;
  }
  const parentSignal = activeRequestController?.signal || new AbortController().signal;
  const attempt = requestAttempt(parentSignal, MANAGER_RESEARCH_POLL_TIMEOUT_MS);
  catalystRefreshState.value = "LOADING";
  catalystRefreshIssue.value = "";
  try {
    let result = await withRequestTimeout(
      attempt,
      refreshManagerResearchEventsExact(date, { signal: attempt.signal }),
    );
    if (!isCurrentRequest(sequence, date)) return;
    managerResearchPayload.value = result;
    managerResearchState.value = result.product ? "READY" : managerResearchResultState(result);
    let job = asRecord(result.job);
    let jobStatus = catalystText(job?.status || result.status, "CANNOT_CONFIRM").toUpperCase();
    for (let poll = 0; ["QUEUED", "RUNNING"].includes(jobStatus) && poll < MANAGER_RESEARCH_POLL_LIMIT; poll += 1) {
      await waitForManagerResearchPoll(attempt.signal);
      const jobId = typeof job?.job_id === "string" ? job.job_id : managerResearchJobId(result);
      result = await withRequestTimeout(
        attempt,
        jobId
          ? loadManagerResearchJobExact(date, jobId, { signal: attempt.signal })
          : loadManagerResearchStatusExact(date, { signal: attempt.signal }),
      );
      if (!isCurrentRequest(sequence, date)) return;
      managerResearchPayload.value = result;
      managerResearchState.value = result.product ? "READY" : managerResearchResultState(result);
      job = asRecord(result.job);
      jobStatus = catalystText(job?.status || result.status, "CANNOT_CONFIRM").toUpperCase();
    }
    const productCoverage = asRecord(result.product?.catalyst_coverage);
    const productReaderCoverage = asRecord(result.product?.reader_coverage);
    const progress = asRecord(job?.progress);
    const eventCount = typeof productCoverage?.event_count === "number"
      ? productCoverage.event_count
      : typeof progress?.event_rows === "number"
        ? progress.event_rows
        : 0;
    const refreshHasEvents = eventCount > 0;
    const readerMaterialCount = typeof productReaderCoverage?.material_count === "number"
      ? productReaderCoverage.material_count
      : typeof productCoverage?.reader_material_count === "number"
        ? productCoverage.reader_material_count
        : typeof progress?.reader_materials === "number"
          ? progress.reader_materials
          : 0;
    const refreshHasMaterials = readerMaterialCount > 0;
    const refreshSucceeded = (jobStatus === "READY" || jobStatus === "PARTIAL_WITH_ROWS")
      && (refreshHasEvents || refreshHasMaterials);
    catalystRefreshState.value = refreshSucceeded
      ? "READY"
      : jobStatus === "CANNOT_CONFIRM" || jobStatus === "FAILED" || jobStatus === "PARTIAL_WITH_ROWS"
        ? "CANNOT_CONFIRM"
        : "RUNNING";
    catalystRefreshIssue.value = catalystRefreshState.value === "READY"
      ? "公开资料已更新；页面仍保持 RESEARCH_ONLY，不提交交易。"
      : `资料刷新=${jobStatus}；reader_material_count=${readerMaterialCount}；event_count=${eventCount}；仅显示来源边界。`;
  } catch (reason) {
    if (!isCurrentRequest(sequence, date)) return;
    catalystRefreshState.value = "CANNOT_CONFIRM";
    catalystRefreshIssue.value = reason instanceof Error
      ? `催化刷新失败（${reason.message}${attempt.timedOut() ? "；请求超时" : ""}）。`
      : "催化刷新响应不可确认。";
  } finally {
    attempt.dispose();
  }
}

async function loadWorkbenchResearchForDate(context: RequestContext): Promise<void> {
  const { date, sequence } = context;
  const laneSequence = ++workbenchReadSequence;
  const attempt = requestAttempt(context.controller.signal);
  try {
    const result = await withRequestTimeout(
      attempt,
      loadManagerWorkbenchResearchExact(date, { signal: attempt.signal }),
    );
    if (!isCurrentRequest(sequence, date) || laneSequence !== workbenchReadSequence) return;
    workbenchResearchPayload.value = result;
    workbenchResearchState.value = result.status;
    workbenchResearchIssue.value = result.cannot_confirm.join("；");
  } catch (reason) {
    if (!isCurrentRequest(sequence, date) || laneSequence !== workbenchReadSequence) return;
    workbenchResearchPayload.value = null;
    workbenchResearchState.value = "FAILED";
    workbenchResearchIssue.value = reason instanceof Error
      ? `研究发现读取失败（${reason.message}${attempt.timedOut() ? "；请求超时" : ""}）。`
      : "研究发现读取失败（响应不可确认）。";
  } finally {
    attempt.dispose();
  }
}

async function loadResearchLaneForDate(context: RequestContext): Promise<void> {
  const { date, sequence } = context;
  const attempt = requestAttempt(context.controller.signal);
  try {
    // This is deliberately the exact-date lane.  There is no latest fallback
    // because a different day's research cannot be joined to this card.
    const result = await withRequestTimeout(
      attempt,
      loadResearchLane(date, { signal: attempt.signal }),
    );
    if (!isCurrentRequest(sequence, date)) return;
    if (result.research_date !== date || result.endpoint_mode !== "EXACT") {
      researchLanePayload.value = null;
      researchLaneState.value = "CANNOT_CONFIRM";
      researchLaneIssue.value = "research lane 未返回同一 exact target date。";
      return;
    }
    researchLanePayload.value = result;
    researchLaneState.value = "READY";
    researchLaneIssue.value = "";
  } catch (reason) {
    if (!isCurrentRequest(sequence, date)) return;
    // Lane evidence is auxiliary.  Keep the stage card visible and let the
    // contribution adapter mark the lane-backed sources CANNOT_CONFIRM.
    researchLanePayload.value = null;
    researchLaneState.value = "CANNOT_CONFIRM";
    researchLaneIssue.value = reason instanceof Error
      ? `research lane 读取失败（${reason.message}${attempt.timedOut() ? "；请求超时" : ""}）。`
      : `research lane 读取失败（响应不可确认${attempt.timedOut() ? "；请求超时" : ""}）。`;
  } finally {
    attempt.dispose();
  }
}

async function loadManagerDecisionForDate(context: RequestContext): Promise<void> {
  const { date, sequence } = context;
  const attempt = requestAttempt(context.controller.signal);
  try {
    const result = await withRequestTimeout(attempt, loadManagerDecisionExact(date, attempt.signal));
    if (!isCurrentRequest(sequence, date)) return;
    if (!result || typeof result !== "object" || Array.isArray(result)) {
      managerDecisionPayload.value = null;
      managerDecisionState.value = "CANNOT_CONFIRM";
      managerDecisionIssueText.value = "独立经理决策响应不是对象。";
      return;
    }
    const issue = validateManagerDecisionResponse(result, date);
    if (!isCurrentRequest(sequence, date)) return;
    if (issue) {
      managerDecisionPayload.value = null;
      managerDecisionState.value = "CANNOT_CONFIRM";
      managerDecisionIssueText.value = `独立经理决策 contract 未通过：${issue}。`;
      return;
    }
    managerDecisionPayload.value = result;
    managerDecisionState.value = result.status === "READY" || result.status === "READY_EMPTY"
      ? "READY"
      : result.status === "NOT_MATERIALIZED"
        ? "NOT_MATERIALIZED"
        : "CANNOT_CONFIRM";
    managerDecisionIssueText.value = result.status === "CANNOT_CONFIRM"
      ? `独立经理决策不可确认：${Array.isArray(result.cannot_confirm) ? result.cannot_confirm.join("；") : "CANNOT_CONFIRM"}。`
      : result.status === "NOT_MATERIALIZED"
        ? "独立经理决策尚未物化。"
        : "";
  } catch (reason) {
    if (!isCurrentRequest(sequence, date)) return;
    managerDecisionPayload.value = null;
    managerDecisionState.value = "CANNOT_CONFIRM";
    managerDecisionIssueText.value = `独立经理决策读取失败（${reason instanceof Error ? reason.message : "响应不可确认"}${attempt.timedOut() ? "；请求超时" : ""}）。`;
  } finally {
    attempt.dispose();
  }
}

async function loadDate(date: string): Promise<void> {
  activeRequestController?.abort();
  const sequence = ++requestSequence;
  const controller = new AbortController();
  activeRequestController = controller;
  requestedDate.value = date;
  readingStockFilter.value = "ALL";
  readingDateUpperBound.value = date;
  payload.value = null;
  preselectionPayload.value = null;
  stagePayload.value = null;
  managerDecisionPayload.value = null;
  managerResearchPayload.value = null;
  researchLanePayload.value = null;
  workbenchResearchPayload.value = null;
  preselectionState.value = "LOADING";
  queueState.value = "LOADING";
  stageState.value = "LOADING";
  managerResearchState.value = "LOADING";
  catalystRefreshState.value = "IDLE";
  researchLaneState.value = "LOADING";
  workbenchResearchState.value = "LOADING";
  preselectionIssue.value = "";
  queueIssue.value = "";
  stageIssue.value = "";
  managerDecisionIssueText.value = "";
  managerResearchIssue.value = "";
  catalystRefreshIssue.value = "";
  researchLaneIssue.value = "";
  workbenchResearchIssue.value = "";
  workbenchSourceFilter.value = "ALL";
  queueEntries.value = [];
  errorMessage.value = "";
  state.value = "LOADING";
  const context = { date, sequence, controller };
  void loadSelectionForDate(context);
  void loadPreselectionForDate(context);
  void loadStageForDate(context);
  void loadManagerResearchForDate(context);
  void loadResearchLaneForDate(context);
  void loadWorkbenchResearchForDate(context);
  void loadManagerDecisionForDate(context);
}

function onReadingDateChange(event: Event): void {
  const value = (event.currentTarget as HTMLInputElement).value;
  const compact = compactDate(value);
  if (!isRealDate(compact)) return;
  if (requestedDate.value && compact > requestedDate.value) {
    readingDateUpperBound.value = requestedDate.value;
    return;
  }
  readingDateUpperBound.value = compact;
}

async function loadDefaultDate(): Promise<void> {
  // Without an explicit date the page follows the same canonical default the
  // rest of the app uses (newest verified evidence date); it still loads one
  // exact date and never substitutes another date's product.
  try {
    const response = await fetch("/api/v1/runs/date-list", { cache: "no-store" });
    if (!response.ok) throw new Error("date-list request failed");
    const catalog = (await response.json()) as { default_date?: unknown; dates?: unknown };
    const candidate =
      typeof catalog?.default_date === "string" && catalog.default_date
        ? catalog.default_date
        : Array.isArray(catalog?.dates) && typeof catalog.dates[0] === "string"
          ? catalog.dates[0]
          : "";
    if (!isRealDate(candidate)) {
      state.value = "NO_DATE_SELECTED";
      return;
    }
    updateBrowserDate(candidate);
    void loadDate(candidate);
  } catch {
    state.value = "NO_DATE_SELECTED";
  }
}

function selectInitialDate(): void {
  const queryDate = new URLSearchParams(window.location.search).get("date") || "";
  const initialDate = props.date || queryDate;
  if (!initialDate) {
    void loadDefaultDate();
    return;
  }
  if (!isRealDate(initialDate)) {
    requestedDate.value = initialDate;
    state.value = "REJECTED";
    errorMessage.value = "目标交易日不是有效的 YYYYMMDD 日期。";
    return;
  }
  void loadDate(initialDate);
}

function onDateInputChange(event: Event): void {
  const input = event.currentTarget as HTMLInputElement;
  const date = compactDate(input.value);
  if (!isRealDate(date)) {
    input.setCustomValidity("请选择有效的目标交易日");
    input.reportValidity();
    return;
  }
  input.setCustomValidity("");
  updateBrowserDate(date);
  void loadDate(date);
}

function refreshWorkbenchResearch(): void {
  const date = requestedDate.value;
  if (!isRealDate(date)) return;
  const controller = activeRequestController || new AbortController();
  if (!activeRequestController) activeRequestController = controller;
  // Do not keep showing an older exact-date result while the same-date
  // refresh is in flight.  The status panel remains visible and says LOADING.
  workbenchResearchPayload.value = null;
  workbenchResearchState.value = "LOADING";
  workbenchResearchIssue.value = "";
  void loadWorkbenchResearchForDate({ date, sequence: requestSequence, controller });
}

function refresh(): void {
  if (isRealDate(requestedDate.value)) void loadDate(requestedDate.value);
}

function scrollTo(id: string): void {
  document.querySelector(`#${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

onMounted(selectInitialDate);
onBeforeUnmount(() => {
  activeRequestController?.abort();
  requestSequence += 1;
});
// Independent material-owner lane: neither Stage success nor 15:30 quotes
// controls this host. The child renderer owns only this empty DOM element.
const catalystObservationHost = ref<HTMLElement | null>(null);
let disposeCatalystObservations: (() => void) | undefined;
watch([catalystObservationHost, requestedDate], ([host, date]) => {
  disposeCatalystObservations?.();
  disposeCatalystObservations = host && date ? mountCatalystObservations(host, date) : undefined;
}, { flush: "post" });
onBeforeUnmount(() => disposeCatalystObservations?.());
</script>

<template>
  <main class="manager-selection-page" :data-state="state">
    <header class="manager-hero">
      <div class="manager-hero__copy">
        <p class="manager-kicker">V4 · 股票研究</p>
        <h1>经理选股工作台</h1>
        <p class="manager-hero__description">
          先看股票、理由和数据时间，再逐项核对条件。先核具体变化，再核预期；原Stage与BUY保留在来源详情。
        </p>
      </div>
      <div class="manager-hero__date" aria-label="当前目标交易日">
        <span>原Stage参考日</span>
        <strong>{{ requestedDate || "未选择" }}</strong>
        <small>研究日期 · exact</small>
      </div>
    </header>



    <div ref="catalystObservationHost" class="manager-catalyst-host"></div>

    <details class="manager-original-sources" aria-label="原来源排序与交易门禁">
      <summary>原来源排序、Stage与BUY门禁（各自口径，不是另一份关注榜）</summary>
    <section class="manager-controls" aria-label="原Stage来源控制">
      <label for="manager-selection-date">原Stage来源日期</label>
      <input
        id="manager-selection-date"
        type="date"
        aria-label="目标交易日"
        :value="dateInputValue(requestedDate)"
        @change="onDateInputChange"
      />
      <button type="button" :disabled="state === 'LOADING' || !requestedDate" @click="refresh">刷新当日研究</button>
      <span class="manager-controls__route">此处只切换原来源日期；上方关注区使用独立计划目标日</span>
    </section>

    <section
      v-if="managerStagePending"
      class="manager-priority-pending"
      aria-label="经理决策优先级待生成"
      role="status"
    >
      <p class="manager-eyebrow">DECISION PRIORITY / PENDING SLOT</p>
      <h2>09:40 阶段候选待生成</h2>
      <p>{{ managerPriorityHeadline }}</p>
      <small>当前时间按 Asia/Shanghai 判断；页面不轮询、不把空响应解释为不建议买入。</small>
    </section>

    <section
      v-if="managerPriorityReady || Boolean(workbenchResearchPayload) || (workbenchResearchState !== 'IDLE' && workbenchResearchState !== 'LOADING')"
      id="manager-priority-dashboard"
      class="manager-priority-dashboard"
      aria-label="经理决策优先级摘要"
    >
      <template v-if="managerPriorityReady">
      <header class="manager-priority-dashboard__header">
        <div>
          <p class="manager-eyebrow">EXECUTION GATE + INVESTMENT ADVICE / RESEARCH ONLY</p>
          <h2>原来源的行动分类与财务比较</h2>
          <p>{{ managerPriorityHeadline }}</p>
        </div>
        <span class="status-pill status-pill--research">{{ managerPrioritySummary.retainedCount }} 条阶段行</span>
      </header>

      <div class="manager-priority-counts" aria-label="五类行动计数">
        <article v-for="category in PRIORITY_CATEGORIES" :key="category">
          <span>{{ PRIORITY_CATEGORY_LABELS[category] }}</span>
          <strong>{{ managerPrioritySummary.counts[category] }}</strong>
        </article>
      </div>

      <div class="manager-priority-counts manager-priority-counts--research" aria-label="五类研究意见计数">
        <article v-for="action in RESEARCH_ADVICE_ACTIONS" :key="`research-count-${action}`">
          <span>{{ RESEARCH_ADVICE_LABELS[action] }}</span>
          <strong>{{ managerPrioritySummary.researchAdviceCounts[action] ?? "CANNOT_CONFIRM" }}</strong>
        </article>
      </div>

      <section class="manager-research-priority" aria-label="独立研究优先级">
        <header>
          <div>
            <p class="manager-eyebrow">RESEARCH PRIORITY / ACTION INDEPENDENT</p>
            <h3>研究优先级（独立于行动分类）</h3>
          </div>
          <span>前二条</span>
        </header>
        <p class="manager-research-priority__note">执行门来自 exact 阶段字段；独立投资研究意见只消费 V4 研究产品中的显式 advice。两者都保持 RESEARCH_ONLY，不互相升级或替代。</p>
        <p v-if="!managerResearchPriorityRows.length" class="manager-research-priority__empty" role="status">
          尚无可比较首选：同报告期官方结构化指标尚未物化或无法确认。
        </p>
        <div v-else class="manager-research-priority__list">
          <article v-for="(row, index) in managerResearchPriorityRows" :key="`research-${row.code}-${index}`">
            <header>
              <strong>研究优先级 #{{ index + 1 }} · {{ row.name }}</strong>
              <span>{{ row.code }} · 执行门={{ row.executionGate }} · 研究意见={{ row.investmentAdvice.label || "CANNOT_CONFIRM" }}</span>
            </header>
            <p><strong>后端优先级依据：</strong>{{ row.investmentAdvice.priorityReason || row.investmentAdvice.summary || row.preference.summary }}</p>
            <p><strong>研究覆盖范围：</strong>{{ managerInvestmentAdviceCoverage(row) }}</p>
            <p><strong>数值 basis：</strong>{{ managerInvestmentBasisSummary(row) }}</p>
            <p v-if="row.investmentAdvice.risks.length"><strong>已知风险/反证：</strong>{{ row.investmentAdvice.risks.join("；") }}</p>
            <small>尚未满足行动条件：{{ row.buyConditions.length ? row.buyConditions.join("；") : "等待 exact 阶段与条件证据" }}</small>
            <details v-if="row.investmentAdvice.basis.length" class="manager-research-priority__evidence">
              <summary>展开 basis 来源定位</summary>
              <ul>
                <li v-for="(basis, basisIndex) in row.investmentAdvice.basis" :key="`${row.code}-research-basis-${basisIndex}`">
                  <span>{{ basis.dimension || "UNKNOWN" }}={{ basis.state || "CANNOT_CONFIRM" }} · {{ basis.period || "CANNOT_CONFIRM_PERIOD" }} · {{ basis.currency || "CANNOT_CONFIRM_CURRENCY" }}/{{ basis.unit || "CANNOT_CONFIRM_UNIT" }}</span>
                  <ul v-if="basis.factRefs.length">
                    <li v-for="(ref, refIndex) in basis.factRefs" :key="`${row.code}-research-ref-${basisIndex}-${refIndex}`"><code>{{ managerInvestmentBasisRefText(ref) }}</code></li>
                  </ul>
                </li>
              </ul>
            </details>
          </article>
        </div>
      </section>
      </template>

      <section
        v-if="workbenchResearchState !== 'LOADING' && (managerPriorityReady || Boolean(workbenchResearchPayload) || workbenchResearchState !== 'IDLE')"
        class="manager-workbench-research-summary"
        aria-label="经理工作台研究发现摘要"
      >
      <div class="panel-heading">
        <div>
          <p class="manager-eyebrow">当日研究概览</p>
          <h2>重点关注 · 主题变化 · 风险上升</h2>
        </div>
        <div class="manager-workbench-summary-actions">
          <span class="status-pill" :class="`status-pill--${statusClass(workbenchResearchState)}`">{{ workbenchStatusText(workbenchResearchState) }}</span>
          <button type="button" :disabled="isWorkbenchResearchLoading()" @click="refreshWorkbenchResearch">只读刷新研究发现</button>
        </div>
      </div>
      <div class="manager-workbench-research-meta">
        <strong>{{ workbenchStatusText(workbenchResearchState) }}</strong>
        <span>{{ workbenchCoverageText(workbenchResearchPayload) }}</span>
        <span>15:30尾盘研究 · 刷新不启动扫描</span>
        <span v-if="workbenchResearchPayload?.as_of">数据截至 {{ workbenchResearchPayload.as_of }}</span>
      </div>
      <p v-if="workbenchResearchIssue" class="manager-stage-note manager-stage-note--gap" role="status">{{ workbenchResearchState === 'FAILED' ? '研究发现读取失败：请求或执行未完成，旧结果已清除。' : '部分研究资料待补，已核实的观察单独展示。' }}</p>
      <details class="manager-stage-audit">
        <summary>展开研究运行审计</summary>
        <p>{{ workbenchResearchState }} · {{ workbenchResearchIssue }}</p>
        <p v-if="workbenchResearchPayload">RESEARCH_ONLY={{ workbenchResearchPayload.RESEARCH_ONLY }} · production_allowed={{ workbenchResearchPayload.production_allowed }} · buy_gate_updated={{ workbenchResearchPayload.buy_gate_updated }} · orders_sent={{ workbenchResearchPayload.orders_sent }}</p>
        <pre>{{ workbenchAudit(workbenchResearchPayload) }}</pre>
      </details>
      <div class="manager-workbench-summary-grid">
        <article>
          <header><span>重点关注</span><strong>{{ workbenchSummaryItems("focus").length }}</strong></header>
          <button
            v-for="item in workbenchSummaryItems('focus')"
            :key="item.item_id || `${item.name}-${item.occurred_at}`"
            type="button"
            :disabled="!item.candidate_id"
            @click="focusWorkbenchSummaryItem(item)"
          ><b>{{ item.name }}</b><span>{{ item.reason }}</span><small>{{ item.occurred_at }} · {{ item.evidence_status }}</small></button>
          <p v-if="!workbenchSummaryItems('focus').length">无已确认重点项；不生成占位利好。</p>
        </article>
        <article>
          <header><span>主题变化</span><strong>{{ workbenchSummaryItems("theme_changes").length }}</strong></header>
          <button
            v-for="item in workbenchSummaryItems('theme_changes')"
            :key="item.item_id || `${item.name}-${item.occurred_at}`"
            type="button"
            :disabled="!item.candidate_id"
            @click="focusWorkbenchSummaryItem(item)"
          ><b>{{ item.name }}</b><span>{{ item.reason }}</span><small>{{ item.occurred_at }} · {{ item.evidence_status }}</small></button>
          <p v-if="!workbenchSummaryItems('theme_changes').length">主题变化尚未确认。</p>
        </article>
        <article class="manager-workbench-summary-grid__risk">
          <header><span>风险上升</span><strong>{{ workbenchSummaryItems("risk_upgrades").length }}</strong></header>
          <button
            v-for="item in workbenchSummaryItems('risk_upgrades')"
            :key="item.item_id || `${item.name}-${item.occurred_at}`"
            type="button"
            :disabled="!item.candidate_id"
            @click="focusWorkbenchSummaryItem(item)"
          ><b>{{ item.name }}</b><span>{{ item.reason }}</span><small>{{ item.occurred_at }} · {{ item.evidence_status }}</small></button>
          <p v-if="!workbenchSummaryItems('risk_upgrades').length">没有已验证的风险升级；不等于风险为零。</p>
        </article>
      </div>
      </section>
    </section>

    <details class="manager-meta" aria-label="日期与运行元数据"><summary>展开日期与运行审计</summary>
      <dl>
        <div><dt>target_trade_date</dt><dd>{{ valueOrCannotConfirm(payload?.target_trade_date || requestedDate) }}</dd></div>
        <div><dt>source_date</dt><dd>{{ valueOrCannotConfirm(payload?.source_date) }}</dd></div>
        <div><dt>status</dt><dd><span class="status-pill" :class="`status-pill--${statusClass(displayStatus)}`">{{ displayStatus }}</span></dd></div>
        <div><dt>origin</dt><dd>{{ valueOrCannotConfirm(payload?.origin) }}</dd></div>
        <div><dt>generated_at</dt><dd>{{ valueOrCannotConfirm(payload?.generated_at) }}</dd></div>
        <div><dt>cutoff_at</dt><dd>{{ valueOrCannotConfirm(payload?.cutoff_at) }}</dd></div>
      </dl>
    </details>

    <section v-if="state === 'NO_DATE_SELECTED'" class="manager-state manager-state--neutral" aria-label="未选择日期">
      <p class="manager-eyebrow">NO DATE SELECTED</p>
      <h2>请选择 exact target date</h2>
      <p>此页面不会读取 latest；选择目标交易日后才会发起一条 exact-date GET 请求。</p>
    </section>
    <section v-else-if="state === 'LOADING'" class="manager-state manager-state--loading" aria-busy="true" role="status">
      <p class="manager-eyebrow">READING EXACT LEDGER</p>
      <h2>正在读取 {{ requestedDate }}</h2>
      <p>等待 V3.5 返回同一 target_trade_date 的不可变研究账本。</p>
    </section>
    <section v-else-if="state === 'STALE' || state === 'ERROR' || state === 'REJECTED'" class="manager-state manager-state--error" role="alert">
      <p class="manager-eyebrow">DATE / READ EVIDENCE</p>
      <h2>{{ state === "STALE" ? "日期证据未通过" : "账本读取未通过" }}</h2>
      <p>当日研究账本读取失败；阶段与尾盘观察按各自状态展示。</p><details class="manager-stage-audit"><summary>展开账本错误审计</summary><p>{{ errorMessage }}</p></details>
    </section>
    <section v-else-if="state === 'NOT_MATERIALIZED' || state === 'CANNOT_CONFIRM'" class="manager-state manager-state--gap" role="status">
      <p class="manager-eyebrow">EXACT PRODUCT GAP</p>
      <h2>{{ state === "NOT_MATERIALIZED" ? "研究账本尚未物化" : "关键证据不可确认" }}</h2>
      <p>研究账本暂不可用；不代表没有股票。阶段与尾盘结果在下方独立展示。</p>
      <details class="manager-stage-audit"><summary>展开账本状态审计</summary><p>{{ state }} · {{ errorMessage }}</p></details>
    </section>

    <section
      v-if="isRealDate(requestedDate)"
      id="manager-stage-hk"
      class="manager-panel manager-stage-panel"
      aria-label="今日港股通阶段候选"
    >
      <div class="panel-heading">
        <div>
          <p class="manager-eyebrow">阶段与尾盘 · 独立研究</p>
          <h2>港股通股票 · 阶段与尾盘观察</h2>
        </div>
        <span class="status-pill" :class="`status-pill--${statusClass(managerStageStatus)}`">
          {{ managerStageCountLabel }}
        </span>
      </div>
      <div class="manager-source-filter" role="group" aria-label="候选来源筛选">
        <button type="button" :aria-pressed="workbenchSourceFilter === 'ALL'" @click="workbenchSourceFilter = 'ALL'">全部来源</button>
        <button type="button" :aria-pressed="workbenchSourceFilter === 'STAGE'" @click="workbenchSourceFilter = 'STAGE'">原有阶段候选</button>
        <button type="button" :aria-pressed="workbenchSourceFilter === 'CLOSE_DISCOVERY'" @click="workbenchSourceFilter = 'CLOSE_DISCOVERY'">15:30尾盘发现</button>
        <button type="button" :aria-pressed="workbenchSourceFilter === 'CONTINUOUS_TRACKING'" @click="workbenchSourceFilter = 'CONTINUOUS_TRACKING'">持续跟踪</button>
      </div>
      <p v-if="stageState === 'LOADING'" class="manager-stage-note" role="status">阶段候选正在读取；尾盘观察单独展示。</p>
      <p v-else-if="stageState === 'CANNOT_CONFIRM' || !managerStageCanRender" class="manager-stage-note manager-stage-note--gap" role="status">阶段候选暂不可用：缺少当日阶段结果。尾盘观察单独展示。</p>
      <p v-else-if="managerStagePending" class="manager-stage-note" role="status">阶段时段尚未到达，等待当日结果。</p>
      <p class="manager-stage-note manager-close-independent-state" role="status">尾盘研究：{{ workbenchStatusText(workbenchResearchState) }}。{{ workbenchCoverageText(workbenchResearchPayload) }}</p>
      <details class="manager-stage-audit"><summary>展开阶段运行审计</summary>
      <div class="manager-stage-boundary" aria-label="港股通阶段候选边界">
        <strong>09:40补充确认 / 非09:35替代</strong>
        <span>stage={{ MANAGER_STAGE_ID }}</span>
        <span>market={{ MANAGER_STAGE_MARKET }}</span>
        <span>RESEARCH_ONLY / WATCH_ONLY / 非formal / 非BUY</span>
        <span>v4_manager_research={{ managerResearchState }}<template v-if="managerResearchCoverage(managerResearchPayload)"> {{ managerResearchCoverage(managerResearchPayload) }}</template></span>
        <span v-if="managerResearchPayload">v4_target_trade_date={{ managerResearchPayload.target_trade_date }}</span>
        <span v-if="managerResearchIssue">{{ managerResearchIssue }}</span>
        <span v-if="requestedDate === '20260831' && stageState === 'READY'">09:40 controlled recovery · natural=false · formal=false · NO_TRADE / NO_BUY / 非经理入选</span>
      </div>
      <p v-if="stageState === 'LOADING'" class="manager-stage-note" >
        正在读取 exact stage-center 响应；数量未知（CANNOT_CONFIRM）。独立研究发现若已有有效 exact 产物，仍可在下方按自身状态显示。
      </p>
      <p v-else-if="stageState === 'CANNOT_CONFIRM' || !managerStageCanRender" class="manager-stage-note manager-stage-note--gap" >
        Stage 数量未知（CANNOT_CONFIRM）；{{ stageIssue || "HK stage 证据不可确认" }}。不使用 A 股或 unified_rows fallback，也不阻断独立研究发现按自身状态显示。
      </p>
      <p v-else-if="managerStagePending" class="manager-stage-note manager-stage-note--pending" >
        09:40 阶段槽尚未到时；当前空响应只表示待生成，不是投资判断。数量未知（CANNOT_CONFIRM）。独立研究发现不会把 Stage 升级为 READY。
      </p>
      </details>
      <div class="manager-workbench-candidate-lanes">
      <div v-if="managerStageCanRender && !managerStagePending && visibleManagerPriorityRows.length" class="manager-stage-grid" aria-label="按决策优先级排序的阶段候选">
        <article
          v-for="(priorityRow, index) in visibleManagerPriorityRows"
          :key="managerStageCardKey(priorityRow.stageRow, index)"
          :id="workbenchStageCandidateDomId(priorityRow)"
          class="manager-stage-card"
          :class="`manager-stage-card--${priorityRow.category.toLowerCase()}`"
        >
          <header class="manager-stage-card__header">
            <div>
              <p class="manager-priority-card__rank">优先级 #{{ index + 1 }} · 阶段排名 #{{ priorityRow.stageRank ?? "CANNOT_CONFIRM" }}</p>
              <h3>{{ priorityRow.name }}</h3>
              <code>{{ priorityRow.code }}</code>
            </div>
            <div class="manager-stage-card__badges">
              <span class="manager-stage-card__rank">#{{ managerStageMetricValue(priorityRow.stageRow, "rank") }}</span>
              <span class="status-pill" :class="`status-pill--${statusClass(priorityRow.category)}`">{{ priorityRow.categoryLabel }}</span>
            </div>
          </header>
          <p class="manager-stage-card__boundary">09:40补充确认 / 非09:35替代 · RESEARCH_ONLY / NO_TRADE / NO_BUY / 非经理入选 · 阶段排序分仅用于观察入池</p>
          <div class="manager-candidate-source-tags" aria-label="候选来源标签">
            <span v-for="label in workbenchSourceLabels(workbenchCandidateForStage(priorityRow), true)" :key="`${priorityRow.code}-${label}`">{{ label }}</span>
          </div>
          <p class="manager-priority-card__recommendation"><strong>执行门（stage）：</strong>{{ priorityRow.categoryLabel }}</p>
          <p class="manager-priority-card__recommendation"><strong>独立投资研究意见：</strong>{{ priorityRow.investmentAdvice.label || "CANNOT_CONFIRM" }}<span v-if="priorityRow.investmentAdvice.action"> · action={{ priorityRow.investmentAdvice.action }}</span></p>
          <p v-if="priorityRow.investmentAdvice.summary || priorityRow.investmentAdvice.priorityReason" class="manager-priority-card__reason"><strong>研究意见依据：</strong>{{ priorityRow.investmentAdvice.priorityReason || priorityRow.investmentAdvice.summary }}</p>
          <p class="manager-priority-card__reason"><strong>研究覆盖范围：</strong>{{ managerInvestmentAdviceCoverage(priorityRow) }}</p>
          <p class="manager-priority-card__reason"><strong>数值 basis：</strong>{{ managerInvestmentBasisSummary(priorityRow) }}</p>
          <p v-if="priorityRow.investmentAdvice.conditions.length" class="manager-priority-card__reason"><strong>研究意见条件：</strong>{{ priorityRow.investmentAdvice.conditions.join("；") }}</p>
          <p v-if="priorityRow.investmentAdvice.risks.length" class="manager-priority-card__gap"><strong>研究意见风险/反证：</strong>{{ priorityRow.investmentAdvice.risks.join("；") }}</p>
          <details v-if="priorityRow.investmentAdvice.basis.length" class="manager-priority-card__evidence">
            <summary>展开财务 basis 与来源定位</summary>
            <ul>
              <li v-for="(basis, basisIndex) in priorityRow.investmentAdvice.basis" :key="`${priorityRow.code}-basis-${basisIndex}`">
                <span>{{ basis.dimension || "UNKNOWN" }}={{ basis.state || "CANNOT_CONFIRM" }} · {{ basis.currentColumn || "当前" }}={{ managerBasisValue(basis.current) }} · {{ basis.previousColumn || "前期" }}={{ managerBasisValue(basis.previous) }} · {{ basis.period || "CANNOT_CONFIRM_PERIOD" }} · {{ basis.currency || "CANNOT_CONFIRM_CURRENCY" }}/{{ basis.unit || "CANNOT_CONFIRM_UNIT" }}</span>
                <ul v-if="basis.factRefs.length">
                  <li v-for="(ref, refIndex) in basis.factRefs" :key="`${priorityRow.code}-basis-ref-${basisIndex}-${refIndex}`"><code>{{ managerInvestmentBasisRefText(ref) }}</code></li>
                </ul>
              </li>
            </ul>
          </details>
          <p class="manager-priority-card__reason"><strong>关键理由：</strong>{{ priorityRow.reason }}</p>
          <p v-if="priorityRow.evidenceGap" class="manager-priority-card__gap"><strong>证据缺口：</strong>{{ priorityRow.evidenceGap }}</p>
          <dl class="manager-priority-card__conditions">
            <div>
              <dt>待满足条件</dt>
              <dd>{{ priorityRow.buyConditions.length ? priorityRow.buyConditions.join("；") : "尚未绑定可确认的条件" }}</dd>
            </div>
            <div>
              <dt>失效条件</dt>
              <dd>{{ priorityRow.invalidationConditions.length ? priorityRow.invalidationConditions.join("；") : "CANNOT_CONFIRM" }}</dd>
            </div>
            <div>
              <dt>数据时间</dt>
              <dd>{{ priorityRow.dataTime }}</dd>
            </div>
          </dl>
          <details class="manager-stage-contribution-details">
            <summary>展开五路观察贡献（非经理入选）</summary>
            <section class="manager-stage-contribution-panel" aria-label="观察入榜原因（非经理入选）">
              <h4 class="manager-stage-card__reason">观察入榜原因（非经理入选）</h4>
              <ul class="manager-stage-contributions" aria-label="五路观察贡献">
              <li
                v-for="key in STAGE_REASON_CONTRIBUTION_KEYS"
                :key="`${managerStageCode(priorityRow.stageRow)}-${key}`"
                class="manager-stage-contribution"
                :data-contribution-status="managerStageContribution(priorityRow.stageRow, key).status"
              >
                <header class="manager-stage-contribution__header">
                  <strong>{{ managerStageContribution(priorityRow.stageRow, key).label }}</strong>
                  <span class="status-pill" :class="`status-pill--${statusClass(managerStageContribution(priorityRow.stageRow, key).status)}`">
                    {{ managerStageContribution(priorityRow.stageRow, key).status }}
                  </span>
                </header>
                <p>{{ managerStageContribution(priorityRow.stageRow, key).human_text }}</p>
                <details v-if="managerStageContribution(priorityRow.stageRow, key).refs.length" class="manager-stage-contribution__refs">
                  <summary>精确证据引用</summary>
                  <ul>
                    <li v-for="(ref, refIndex) in managerStageContribution(priorityRow.stageRow, key).refs" :key="`${managerStageCode(priorityRow.stageRow)}-${key}-ref-${refIndex}`">
                      <code>{{ managerStageContributionRefText(ref) }}</code>
                    </li>
                  </ul>
                </details>
                <details v-if="managerStageContributionDetails(priorityRow.stageRow, key).length" class="manager-stage-contribution__background">
                  <summary>背景来源详情（{{ managerStageContributionDetails(priorityRow.stageRow, key).length }} 条明细）</summary>
                  <ul>
                    <li
                      v-for="(detail, detailIndex) in managerStageContributionDetails(priorityRow.stageRow, key)"
                      :key="`${managerStageCode(priorityRow.stageRow)}-${key}-detail-${detailIndex}`"
                    >
                      <a
                        v-if="managerStageContributionDetailUrl(detail)"
                        :href="managerStageContributionDetailUrl(detail)"
                        target="_blank"
                        rel="noreferrer"
                      >{{ detail.title }}</a>
                      <span v-else>{{ detail.title }}</span>
                      <small>{{ managerStageContributionDetailMeta(detail) }}</small>
                      <small v-if="detail.note">{{ detail.note }}</small>
                    </li>
                  </ul>
                </details>
              </li>
              </ul>
            </section>
          </details>
          <section v-if="workbenchCandidateForStage(priorityRow)" class="manager-workbench-candidate-detail">
            <h4>尾盘观察与持续跟踪</h4>
            <p>{{ workbenchShortReason(workbenchCandidateForStage(priorityRow)) }}</p>
            <p>{{ workbenchTurnoverText(workbenchCandidateForStage(priorityRow)) }} · 数据时间 {{ workbenchCandidateForStage(priorityRow)?.observed_at }}</p>
            <dl class="manager-condition-grid" aria-label="四项研究条件">
              <div v-for="condition in conditionIndicators(workbenchCandidateForStage(priorityRow))" :key="condition.id"><dt>{{ condition.label }}</dt><dd>{{ condition.state }}</dd></div>
            </dl>
            <p class="manager-observation-gap">{{ conditionGaps(workbenchCandidateForStage(priorityRow)) }}</p>
          <details v-if="workbenchCandidateForStage(priorityRow)" class="manager-stage-audit">
            <summary>展开 15:30 / 持续跟踪研究详情</summary>
            <dl class="manager-stage-audit__fields">
              <div><dt>发现时间</dt><dd>{{ workbenchCandidateForStage(priorityRow)?.observed_at || "CANNOT_CONFIRM" }}</dd></div>
              <div><dt>累计成交额</dt><dd>{{ workbenchTurnoverText(workbenchCandidateForStage(priorityRow)) }}</dd></div>
              <div><dt>量能比较</dt><dd>{{ workbenchRecordText(workbenchCandidateForStage(priorityRow)?.volume_comparison, ["state", "ratio", "baseline_as_of", "reason"]) }}</dd></div>
              <div><dt>价格位置</dt><dd>{{ workbenchRecordText(workbenchCandidateForStage(priorityRow)?.position, ["state", "label", "reason"]) }}</dd></div>
              <div><dt>催化概述</dt><dd>{{ workbenchRecordText(workbenchCandidateForStage(priorityRow)?.catalyst, ["summary", "status"]) }}</dd></div>
              <div><dt>研究关注</dt><dd>{{ workbenchRecordText(workbenchCandidateForStage(priorityRow)?.research_priority, ["level", "previous_level", "change_reason"]) }}</dd></div>
              <div><dt>为什么关注</dt><dd>{{ workbenchCandidateForStage(priorityRow)?.attention_reason || "CANNOT_CONFIRM" }}</dd></div>
              <div><dt>已确认依据</dt><dd>{{ workbenchConfirmedEvidenceText(workbenchCandidateForStage(priorityRow)) }}</dd></div>
              <div><dt>下一步观察</dt><dd>{{ workbenchPlanList(workbenchCandidateForStage(priorityRow), "triggers") }}</dd></div>
              <div><dt>失效条件</dt><dd>{{ workbenchPlanList(workbenchCandidateForStage(priorityRow), "invalidation_conditions") }}</dd></div>
              <div><dt>还缺什么</dt><dd>{{ workbenchPlanList(workbenchCandidateForStage(priorityRow), "missing_evidence") }}</dd></div>
            </dl>
            <details class="manager-stage-audit">
              <summary>展开研究判定与独立来源</summary>
              <ul class="manager-workbench-predicate-list">
                <li v-for="predicate in workbenchCandidateForStage(priorityRow)?.predicates || []" :key="`${priorityRow.code}-${predicate.predicate_id}`">
                  <code>{{ predicate.predicate_id || "UNKNOWN_PREDICATE" }}</code>
                  <strong>{{ predicate.value }}</strong>
                  <span>{{ predicate.reason || "CANNOT_CONFIRM" }}</span>
                </li>
              </ul>
              <ul class="manager-workbench-source-list">
                <li v-for="(source, sourceIndex) in workbenchCandidateForStage(priorityRow)?.sources || []" :key="`${priorityRow.code}-workbench-source-${sourceIndex}`">
                  <span>{{ workbenchSourceText(source) }}</span>
                  <code>{{ source.role || "UNKNOWN_ROLE" }} · sha={{ source.sha256 || "CANNOT_CONFIRM" }} · observed={{ source.observed_at || "CANNOT_CONFIRM" }} · available={{ source.available_at || "CANNOT_CONFIRM" }}</code>
                </li>
              </ul>
            </details>
          </details>
          </section>
          <dl class="manager-stage-metrics" aria-label="阶段盘面字段">
            <div v-if="managerStageMetricAvailable(priorityRow.stageRow, 'stage_score')"><dt>stage_score</dt><dd>{{ managerStageMetricValue(priorityRow.stageRow, "stage_score") }}</dd></div>
            <div v-if="managerStageMetricAvailable(priorityRow.stageRow, 'current_change_pct')"><dt>current_change_pct</dt><dd>{{ managerStagePercentValue(priorityRow.stageRow, "current_change_pct") }}</dd></div>
            <div v-if="managerStageMetricAvailable(priorityRow.stageRow, 'pct_chg')"><dt>pct_chg</dt><dd>{{ managerStagePercentValue(priorityRow.stageRow, "pct_chg") }}</dd></div>
            <div v-if="managerStageMetricAvailable(priorityRow.stageRow, 'volume_ratio')"><dt>volume_ratio</dt><dd>{{ managerStageMetricValue(priorityRow.stageRow, "volume_ratio") }}</dd></div>
            <div v-if="managerStageMetricAvailable(priorityRow.stageRow, 'turnover')"><dt>turnover</dt><dd>{{ managerStageMetricValue(priorityRow.stageRow, "turnover") }}</dd></div>
          </dl>
          <details class="manager-stage-audit">
            <summary>展开 AI / 血缘审计详情</summary>
            <dl class="manager-stage-audit__fields">
              <div><dt>market</dt><dd>{{ managerStageAuditValue(priorityRow.stageRow, "market") }}</dd></div>
              <div><dt>d1_rank</dt><dd>{{ managerStageAuditValue(priorityRow.stageRow, "d1_rank") }}</dd></div>
              <div><dt>d1_score</dt><dd>{{ managerStageAuditValue(priorityRow.stageRow, "d1_score") }}</dd></div>
              <div><dt>candidate_lanes</dt><dd>{{ managerStageAuditValue(priorityRow.stageRow, "candidate_lanes") }}</dd></div>
              <div><dt>artifact_id</dt><dd>{{ managerStageAuditValue(priorityRow.stageRow, "artifact_id") }}</dd></div>
              <div><dt>run_id</dt><dd>{{ managerStageAuditValue(priorityRow.stageRow, "run_id") }}</dd></div>
              <div><dt>source_status</dt><dd>{{ managerStageAuditValue(priorityRow.stageRow, "source_status") }}</dd></div>
              <div><dt>cannot_confirm</dt><dd>{{ managerStageAuditValue(priorityRow.stageRow, "cannot_confirm") }}</dd></div>
            </dl>
          </details>
        </article>
      </div>
      <div v-if="discoveryOnlyCandidates.length" class="manager-discovery-grid" aria-label="尾盘发现与持续跟踪候选">
        <article v-for="candidate in discoveryOnlyCandidates" :id="workbenchCandidateDomId(candidate.candidate_id)" :key="candidate.candidate_id" class="manager-discovery-card">
          <header class="manager-discovery-card__headline">
            <span><strong>{{ candidate.name }}</strong> <code>{{ candidate.symbol }}</code></span>
            <span class="manager-candidate-source-tags"><b v-for="label in workbenchSourceLabels(candidate)" :key="`${candidate.candidate_id}-${label}`">{{ label }}</b></span>
            <span class="status-pill status-pill--research">{{ candidateHeadline(candidate) }}</span>
          </header>
          <p v-if="candidate.data_status.includes('SIMULATED') || candidate.name.includes('SIMULATED')" class="manager-fixture-warning">SIMULATED · 仅用于隔离合同/界面测试，不是真实扫描结果。</p>
          <p>{{ workbenchShortReason(candidate) }}</p>
          <p>{{ workbenchTurnoverText(candidate) }} · 数据时间 {{ candidate.observed_at }}</p>
          <dl class="manager-condition-grid" aria-label="四项研究条件">
              <div v-for="condition in conditionIndicators(candidate)" :key="condition.id"><dt>{{ condition.label }}</dt><dd>{{ condition.state }}</dd></div>
            </dl>
            <p class="manager-observation-gap">{{ conditionGaps(candidate) }}</p>
          <p class="manager-stage-card__boundary">仅供研究，不改变正式排名，不触发买入。</p>
          <details class="manager-stage-audit">
            <summary>展开判定与来源证据</summary>
            <p>{{ candidate.attention_reason }}</p>
            <p>已确认依据：{{ workbenchConfirmedEvidenceText(candidate) }}</p>
            <p>下一步观察：{{ workbenchPlanList(candidate, "triggers") }}</p>
            <p>失效条件：{{ workbenchPlanList(candidate, "invalidation_conditions") }}</p>
            <ul class="manager-workbench-source-list"><li v-for="(source, sourceIndex) in candidate.sources" :key="`${candidate.candidate_id}-${sourceIndex}`">{{ workbenchSourceText(source) }}</li></ul>
            <pre>{{ workbenchAudit(candidate) }}</pre>
          </details>
        </article>
      </div>
      <p
        v-if="managerStageCanRender && !managerStagePending && workbenchSourceFilter === 'STAGE' && !visibleManagerPriorityRows.length"
        class="manager-stage-note"
        role="status"
      >
        本日阶段结果已返回0条；不会使用其他市场或日期替代。
      </p>
      <p
        v-else-if="workbenchSourceFilter !== 'STAGE' && !discoveryOnlyCandidates.length && !(managerStageCanRender && !managerStagePending && visibleManagerPriorityRows.length)"
        class="manager-stage-note"
        role="status"
      >
        当前来源筛选无可显示候选；查看研究发现状态与覆盖信息。
      </p>
      </div>
    </section>

    <section
      v-if="isRealDate(requestedDate)"
      id="manager-current-research"
      class="manager-panel manager-catalyst-panel"
      aria-label="当前研究与近期催化"
    >
      <div class="panel-heading">
        <div>
          <p class="manager-eyebrow">MATERIAL READER / PUBLIC NEWS + OFFICIAL MATERIAL / RESEARCH ONLY</p>
          <h2>资料阅读台 · 固定候选</h2>
          <p class="manager-catalyst-description">公开新闻与原公告按股票、发布时间和来源展示；页面不自动生成焦点、价值评分或荐股理由。</p>
        </div>
        <button
          type="button"
          :disabled="catalystRefreshState === 'LOADING' || !managerResearchPayload?.product"
          @click="refreshCatalystForDate"
        >
          {{ catalystRefreshState === "LOADING" ? "正在刷新资料…" : "刷新公开资料" }}
        </button>
      </div>
      <div class="manager-catalyst-coverage" aria-label="催化当前投影计数">
        <strong>coverage={{ managerCatalystCoverage }}</strong>
        <span>资料按固定候选绑定；摘要可能不完整，未声明全日覆盖，也不替代财务或交易判断。</span>
      </div>
      <details class="manager-catalyst-boundary">
          <summary>展开来源覆盖、时间状态与研究边界</summary>
        <div class="manager-stage-boundary" aria-label="近期催化边界">
          <span v-if="managerResearchPayload?.product">financial_status={{ managerResearchPayload.product.status || "CANNOT_CONFIRM" }}</span>
          <span v-if="managerResearchPayload?.product">reader_as_of={{ managerResearchPayload.product.reader_current_as_of || "CANNOT_CONFIRM" }}</span>
          <span>MEDIA/OFFICIAL_CONFIRMATION_PENDING 不等于订单、收入或 BUY</span>
          <span>按钮只更新研究材料，不提交交易</span>
        </div>
      </details>
      <p v-if="catalystRefreshIssue" class="manager-stage-note" role="status">{{ catalystRefreshIssue }}</p>
      <p v-if="!managerResearchPayload?.product" class="manager-stage-note manager-stage-note--gap" role="status">
        当前研究产品尚未物化；近期催化数量未知（CANNOT_CONFIRM）。
      </p>
      <p v-else-if="!managerResearchRows.length" class="manager-stage-note manager-stage-note--gap" role="status">
        当前固定候选行尚未返回；资料数量未知（CANNOT_CONFIRM）。
      </p>
      <div v-else class="manager-reading-desk" aria-label="公开资料阅读台">
        <div class="manager-reading-filters">
          <label for="manager-reading-stock">股票</label>
          <select id="manager-reading-stock" v-model="readingStockFilter">
            <option value="ALL">全部固定候选</option>
            <option v-for="option in managerReadingStockOptions" :key="option.code" :value="option.code">{{ option.name }} · {{ option.code }}</option>
          </select>
          <label for="manager-reading-date">资料日期上限</label>
          <input id="manager-reading-date" type="date" :value="dateInputValue(readingDateUpperBound)" :max="dateInputValue(requestedDate)" @change="onReadingDateChange" />
        </div>
        <p class="manager-reading-summary">{{ managerReadingSummary }}</p>
        <div class="manager-reading-stock-statuses" aria-label="固定候选资料状态">
          <p class="manager-reading-stock-statuses__title">每只固定候选的资料状态</p>
          <div v-for="stock in managerReadingStockStatuses" :key="`reader-status-${stock.code}`" class="manager-reading-stock-status">
            <strong>{{ stock.name }} · <code>{{ stock.code }}</code></strong>
            <span>公开新闻抓取状态={{ stock.status }} · 公开新闻={{ stock.materialCount }} 条</span>
            <ul>
              <li v-for="gap in stock.gaps" :key="`${stock.code}-${gap}`">来源缺口：{{ gap }}</li>
              <li v-if="!stock.gaps.length">来源缺口：{{ stock.materialCount > 0 && stock.status === "READY" ? "无" : "未返回（CANNOT_CONFIRM）" }}</li>
            </ul>
          </div>
        </div>
        <p v-if="!managerReadingMaterials.length" class="manager-stage-note manager-stage-note--gap" role="status">当前筛选没有可读资料；这表示来源未返回或筛选范围内缺失，不代表没有候选股票。请查看每只股票的 reader 缺口。</p>
        <article v-for="material in managerReadingMaterials" :key="`${material.code}-${material.id}`" class="manager-reading-card">
          <header>
            <div><h3>{{ material.title }}</h3><p>{{ material.name }} · <code>{{ material.code }}</code></p><p>关联候选：<span v-for="association in material.associations" :key="`${material.id}-${association.code}`">{{ association.name }} · <code>{{ association.code }}</code> </span></p></div>
            <span class="status-pill status-pill--research">{{ material.sourceKind }}</span>
          </header>
          <dl><div><dt>来源</dt><dd>{{ material.sourceName }}<template v-if="material.sourceCount > 1"> · 来源次数={{ material.sourceCount }}</template></dd></div><div><dt>发布时间</dt><dd>{{ material.publishedAt }}</dd></div><div><dt>抓取时间</dt><dd>{{ material.collectedAt }}</dd></div><div><dt>范围</dt><dd>{{ material.scopeLabel }}</dd></div></dl>
          <p><strong>{{ material.excerptLabel }}：</strong>{{ material.excerpt }}</p>
          <a v-if="material.sourceUrl" :href="material.sourceUrl" target="_blank" rel="noreferrer noopener">打开原文</a><span v-else>原文链接不可得（CANNOT_CONFIRM）</span>
        </article>
      </div>
      <details v-if="managerCatalystAuditRows.length" class="manager-catalyst-audit">
        <summary>展开原公告审计（{{ managerCatalystAuditRows.length }} 条候选）</summary>
        <p>原公告正文、目录线索和时间状态仅作为可读材料保留；本阅读台不生成自动焦点、价值评分或荐股理由。</p>
        <article v-for="row in managerCatalystAuditRows" :key="`catalyst-audit-${row.code}`" class="manager-catalyst-audit__row">
          <header>
            <strong>{{ row.name }} · {{ row.code }}</strong>
            <span>{{ row.status }} · 原公告材料</span>
          </header>
          <p>标题、来源定位和原文摘要由来源提供；自动催化理由未生成。</p>
          <ul>
            <li v-for="(event, eventIndex) in row.events" :key="`${row.code}-audit-event-${eventIndex}`">
              {{ catalystText(event.catalyst || event.source_title) }} · {{ catalystAuditEventLabel(event) }} · {{ catalystSemanticClassLabel(event) }} · source_id={{ catalystText(event.source_id) }} · source_sha256={{ catalystText(event.source_sha256) }} · page={{ catalystText(event.evidence_page) }}
            </li>
            <li v-if="!row.events.length">事件未确认；候选行仍保留。</li>
          </ul>
        </article>
      </details>
      <details class="manager-research-priority__evidence">
        <summary>展开催化来源覆盖与回执边界</summary>
        <p>有界目录仅说明接入源的检查范围；正文已解析的官方事件与 DIRECTORY_ONLY 目录线索分开，例行正文会列出排除理由；历史证据不等于09:40系统当时已消费，未发现时保留 NO_MATCH_IS_NOT_COMPLETE。</p>
        <ul>
          <li v-for="(count, index) in managerCatalystSourceCounts" :key="`catalyst-source-${index}`">{{ catalystSourceCountText(count) }}</li>
          <li v-if="!managerCatalystSourceCounts.length">CANNOT_CONFIRM（来源计数尚未返回）</li>
        </ul>
      </details>
    </section>

    <template v-if="payload && materialized">
      <section class="manager-summary" aria-label="经理关注摘要">
        <article><span>research ledger</span><strong>{{ researchCount }} 条 research ledger（研究账本）</strong><small>完整研究账本可搜索；不按页面预览截断</small></article>
        <article><span>22:00 manager delta</span><strong>{{ managerDeltaLabel }} 22:00 manager delta（2200）</strong><small>初始研究供给的经理增量；不等于正式名单</small></article>
        <article><span>D1 × official research queue</span><strong>{{ queueCountLabel }} D1 × official research queue（D1 × 官方研究队列）</strong><small>RESEARCH_ONLY / 非formal / 不替代后续 gate</small></article>
        <article><span>authority / later phases</span><strong>formal authority：{{ formalAuthorityStatus }}</strong><small>09:35：{{ phaseStatus("0935") }} · 16:20：{{ phaseStatus("1620") }}</small></article>
      </section>

      <Teleport defer to="#manager-queue-slot">
      <section id="manager-preselection" class="manager-panel queue-panel" aria-label="D-1模型池 × 官方事件研究队列">
        <div class="panel-heading">
          <div><p class="manager-eyebrow">D-1 MODEL POOL × OFFICIAL EVENT LEDGER</p><h2>D-1模型池 × 官方事件</h2></div>
          <span class="status-pill status-pill--research">{{ queueCountLabel }} 交叉研究队列</span>
        </div>
        <details class="queue-details">
          <summary>展开 D-1 × 官方事件研究队列（{{ queueCountLabel }}；全量保留）</summary>
        <p v-if="queueReady" class="queue-intro">
          将 {{ preselectionRowsLabel }} exact-date HK D-1 Top100 与 {{ researchCount }} 条官方事件账本按 normalized HK code 交叉；这是研究队列，不是正式名单，不替代 08:30 / 09:35 gate。
        </p>
        <p v-else class="queue-intro">
          D-1 预选池不可确认（非0）；数量未知。交叉研究队列不展示未知数量，也不替代 08:30 / 09:35 gate。
        </p>
        <p v-if="queueIssueText" class="queue-issue">D1 / queue：{{ queueIssueText }}</p>
        <div class="queue-meta" aria-label="交叉研究队列边界">
          <span><strong>{{ preselectionRowsLabel }}</strong> HK D-1 pool row</span>
          <span><strong>{{ researchCount }}</strong> 条官方事件研究候选</span>
          <span><strong>{{ queueCountLabel }}</strong> D1 × official 研究队列</span>
          <span><strong>{{ formalIds.length }}</strong> 条 formal_shortlist</span>
          <span class="queue-boundary">WATCH_ONLY / RESEARCH_ONLY / 非formal / D1 × official research queue；仅队列身份不决定经理角色</span>
        </div>
        <div v-if="queueReady && researchQueue.length" class="queue-list">
          <article v-for="entry in researchQueue" :key="entry.normalizedCode" class="queue-entry">
            <div class="queue-entry__body">
              <header>
                <div><strong>{{ preselectionRowName(entry.poolRow) }}</strong><code>HK.{{ entry.normalizedCode }}</code></div>
                <span class="queue-label">WATCH_ONLY / RESEARCH_ONLY / 非formal / D1 × official research queue；仅队列身份不决定经理角色</span>
              </header>
              <section class="reason-card" aria-label="经理研究逻辑（待盘面确认）">
                <h4>经理研究逻辑（待盘面确认）</h4>
                <p class="reason-card__summary">{{ managerThesis(entry.selectionCandidate) }}</p>
                <section class="manager-research-facts" aria-label="已核实官方事实">
                  <h5>已核实官方事实</h5>
                  <ul v-if="managerFactItems(entry.selectionCandidate).length">
                    <li v-for="(fact, index) in managerFactItems(entry.selectionCandidate)" :key="`${entry.normalizedCode}-fact-${index}`">{{ managerFactStatement(fact) }}</li>
                  </ul>
                  <p v-else class="manager-research-empty">暂无可绑定的逐行事实。</p>
                </section>
                <div class="manager-research-conditions">
                  <section aria-label="确认条件">
                    <h5>确认条件</h5>
                    <ul v-if="managerConfirmations(entry.selectionCandidate).length">
                      <li v-for="(condition, index) in managerConfirmations(entry.selectionCandidate)" :key="`${entry.normalizedCode}-condition-${index}`">{{ condition }}</li>
                    </ul>
                    <p v-else class="manager-research-empty">待盘面确认。</p>
                  </section>
                  <section aria-label="关键反证与失效条件">
                    <h5>关键反证 / 失效条件</h5>
                    <ul v-if="managerCounterevidence(entry.selectionCandidate).length || managerInvalidations(entry.selectionCandidate).length">
                      <li v-for="(item, index) in managerCounterevidence(entry.selectionCandidate)" :key="`${entry.normalizedCode}-counter-${index}`">{{ item }}</li>
                      <li v-for="(item, index) in managerInvalidations(entry.selectionCandidate)" :key="`${entry.normalizedCode}-invalid-${index}`">失效：{{ item }}</li>
                    </ul>
                    <p v-else class="manager-research-empty">待补充反证。</p>
                  </section>
                </div>
                <details class="candidate-audit reason-details--evidence">
                  <summary>展开 AI / 审计详情（模型、typed gaps、状态与原始证据）</summary>
                  <section class="nonformal-reason" aria-label="为什么仍非formal">
                    <h5>为什么仍非formal</h5>
                    <p class="nonformal-risk-summary">{{ nonformalRiskSummary(entry.selectionCandidate) }}</p>
                    <div class="gap-list" aria-label="非 formal typed gaps">
                      <span v-for="gap in typedGaps(entry.selectionCandidate)" :key="`${entry.normalizedCode}-reason-gap-${gap}`">{{ gap }}</span>
                      <span v-if="!typedGaps(entry.selectionCandidate).length">未声明缺口</span>
                    </div>
                  </section>
                  <section v-if="managerFactItems(entry.selectionCandidate).length" class="reason-evidence reason-evidence--review" aria-label="经理研究审计绑定">
                    <h5>研究事实绑定</h5>
                    <ul class="reason-refs">
                      <li v-for="(fact, index) in managerFactItems(entry.selectionCandidate)" :key="`${entry.normalizedCode}-fact-ref-${index}`"><code>{{ managerFactStatement(fact) }} · markdown_sha256={{ valueOrCannotConfirm(fact.markdown_sha256) }} · L{{ valueOrCannotConfirm(fact.line_start) }}-L{{ valueOrCannotConfirm(fact.line_end) }} · excerpt_sha256={{ valueOrCannotConfirm(fact.excerpt_sha256) }}</code></li>
                    </ul>
                  </section>
                  <dl class="queue-audit-fields">
                    <div><dt>pool_score</dt><dd>{{ preselectionScore(entry.poolRow) }}</dd></div>
                    <div><dt>event classification</dt><dd>{{ eventClassification(entry.selectionCandidate) }}</dd></div>
                    <div><dt>catalyst</dt><dd :title="selectionCatalyst(entry.selectionCandidate)">{{ selectionCatalyst(entry.selectionCandidate) }}</dd></div>
                    <div><dt>research bucket</dt><dd>{{ entry.selectionCandidate.bucket || "CANNOT_CONFIRM" }}</dd></div>
                  </dl>
                  <p class="reason-audit-summary">{{ modelReasonText(entry.poolRow) }}</p>
                  <div class="reason-evidence-grid">
                  <section class="reason-evidence" aria-label="模型证据">
                    <h5>模型证据</h5>
                    <div class="reason-audit-rank" aria-label="D-1 pool rank">D-1 pool rank：#{{ entry.poolRow.pool_rank }}</div>
                    <dl class="reason-fields">
                      <div><dt>pool</dt><dd>{{ poolDisplayName() }}</dd></div>
                      <div><dt>pool_id</dt><dd>{{ valueOrCannotConfirm(entry.poolRow.pool_id) }}</dd></div>
                      <div><dt>pool_rank</dt><dd>{{ preselectionMetric(entry.poolRow, "pool_rank") }}</dd></div>
                      <div><dt>pool_score</dt><dd>{{ preselectionScore(entry.poolRow) }}</dd></div>
                      <div><dt>selected_strategy</dt><dd>{{ strategyValue(entry.poolRow) }}</dd></div>
                      <div><dt>score_prob_active</dt><dd>{{ preselectionMetric(entry.poolRow, "score_prob_active") }}</dd></div>
                      <div><dt>score_prob_memory</dt><dd>{{ preselectionMetric(entry.poolRow, "score_prob_memory") }}</dd></div>
                      <div><dt>score_prob_crash_reflow</dt><dd>{{ preselectionMetric(entry.poolRow, "score_prob_crash_reflow") }}</dd></div>
                      <div><dt>ret_5d</dt><dd>{{ preselectionMetric(entry.poolRow, "ret_5d") }}</dd></div>
                      <div><dt>ret_20d</dt><dd>{{ preselectionMetric(entry.poolRow, "ret_20d") }}</dd></div>
                      <div><dt>ret_60d</dt><dd>{{ preselectionMetric(entry.poolRow, "ret_60d") }}</dd></div>
                      <div><dt>amount_ratio_20d</dt><dd>{{ preselectionMetric(entry.poolRow, "amount_ratio_20d") }}</dd></div>
                      <div><dt>recent_top20_count_20d</dt><dd>{{ preselectionMetric(entry.poolRow, "recent_top20_count_20d") }}</dd></div>
                    </dl>
                  </section>
                  <section class="reason-evidence" aria-label="官方事件证据">
                    <h5>官方事件证据</h5>
                    <dl class="reason-fields">
                      <div><dt>分类</dt><dd>{{ officialClassificationLabel(entry.selectionCandidate) }}</dd></div>
                      <div><dt>材料标题/证据</dt><dd>{{ officialEvidenceText(entry.selectionCandidate) }}</dd></div>
                      <div><dt>来源状态</dt><dd>{{ officialSourceStatusLabel(entry.selectionCandidate) }}</dd></div>
                      <div><dt>published</dt><dd>{{ reasonValue(entry.selectionCandidate, "published_at") }}</dd></div>
                      <div><dt>source time</dt><dd>{{ reasonValue(entry.selectionCandidate, "source_time") }}</dd></div>
                    </dl>
                    <details class="reason-details">
                      <summary>原始英文标题、enum 与 source refs</summary>
                      <dl class="reason-fields reason-fields--raw">
                        <div><dt>classification enum</dt><dd><code>{{ officialClassificationRaw(entry.selectionCandidate) }}</code></dd></div>
                        <div><dt>evidence raw</dt><dd><code>{{ officialEvidenceText(entry.selectionCandidate) }}</code></dd></div>
                        <div><dt>source status raw</dt><dd><code>{{ officialSourceStatusRaw(entry.selectionCandidate) }}</code></dd></div>
                        <div><dt>source_refs</dt><dd><code>{{ candidateSourceRefs(entry.selectionCandidate).length ? "已保留原始引用" : "CANNOT_CONFIRM" }}</code></dd></div>
                      </dl>
                      <ul class="reason-refs">
                        <li v-for="(ref, index) in candidateSourceRefs(entry.selectionCandidate)" :key="`${entry.normalizedCode}-reason-ref-${index}`"><code>{{ sourceRefText(ref) }}</code></li>
                        <li v-if="!candidateSourceRefs(entry.selectionCandidate).length"><code>CANNOT_CONFIRM</code></li>
                      </ul>
                    </details>
                  </section>
                  </div>
                  <section class="reason-evidence reason-evidence--status" aria-label="非formal状态与边界">
                    <h5>状态与边界</h5>
                    <dl class="nonformal-fields">
                      <div><dt>research_status</dt><dd>research_status={{ reasonValue(entry.selectionCandidate, "research_status") }}</dd></div>
                      <div><dt>recommendation_status</dt><dd>recommendation_status={{ reasonValue(entry.selectionCandidate, "recommendation_status") }}</dd></div>
                      <div><dt>acceptance</dt><dd>acceptance={{ reasonValue(entry.selectionCandidate, "acceptance") }}</dd></div>
                      <div><dt>promotion_allowed</dt><dd>promotion_allowed={{ promotionAllowedValue(entry.selectionCandidate) }}</dd></div>
                      <div><dt>eligibility</dt><dd>eligibility={{ reasonValue(entry.selectionCandidate, "eligibility") }}</dd></div>
                      <div><dt>pit_status</dt><dd>pit_status={{ reasonValue(entry.selectionCandidate, "pit_status") }}</dd></div>
                    </dl>
                    <div class="gap-list" aria-label="原始 typed gap 枚举">
                      <code v-for="gap in gapCodes(entry.selectionCandidate)" :key="`${entry.normalizedCode}-audit-gap-${gap}`">{{ gap }}</code>
                    </div>
                  </section>
                </details>
              </section>
            </div>
          </article>
        </div>
        <p v-else-if="queueReady" class="queue-empty">交叉研究队列已验证为空（0 条）。</p>
        <p v-else class="queue-empty">交叉研究队列不可确认（非0）；数量未知。</p>
        </details>
      </section>
      </Teleport>

      <nav class="manager-section-nav" aria-label="经理选股工作台分区">
        <button type="button" @click="scrollTo('manager-preselection')">交叉研究队列</button>
        <button type="button" @click="scrollTo('manager-focus')">经理关注层</button>
        <button type="button" @click="scrollTo('manager-phases')">阶段航迹</button>
        <button type="button" @click="scrollTo('manager-ledger')">完整研究账本</button>
        <button type="button" @click="scrollTo('manager-lineage')">证据血缘</button>
      </nav>

      <section id="manager-focus" class="manager-panel manager-focus-panel" aria-label="经理关注层">
        <div class="panel-heading">
          <div><p class="manager-eyebrow">MANAGER ATTENTION</p><h2>经理关注层</h2></div>
          <p v-if="managerDecisionValid">角色与顺序只来自 2200 typed manager decision；均保留 RESEARCH_ONLY 语义。</p>
          <p v-else class="manager-decision-gap">经理决策证据不可确认；不按 review priority 回退角色。</p>
        </div>
        <div class="focus-columns">
          <section class="focus-column" aria-label="核心研究候选">
            <div class="focus-column__heading"><h3>核心研究</h3><span>{{ coreCandidates.length }} 条</span></div>
            <article v-for="candidate in coreCandidates" :key="`core-${candidate.candidate_id}`" class="focus-card focus-card--core">
              <div><strong>{{ candidateName(candidate) }}</strong><span>{{ candidateCode(candidate) }}</span></div>
              <span class="focus-boundary">经理研究集 / CORE #{{ managerDecision(candidate)?.order }} / RESEARCH_ONLY / 非formal / 非BUY</span>
              <section class="reason-card" aria-label="经理研究逻辑（待盘面确认）">
                <h4>经理研究逻辑（待盘面确认）</h4>
                <section class="manager-decision-reason" aria-label="为什么进入经理研究集">
                  <h5>为什么进入经理研究集</h5>
                  <p>{{ managerDecision(candidate)?.reason || "CANNOT_CONFIRM" }}</p>
                </section>
                <p class="reason-card__summary">{{ managerThesis(candidate) }}</p>
                <section class="manager-research-facts" aria-label="已核实官方事实">
                  <h5>已核实官方事实</h5>
                  <ul v-if="managerFactItems(candidate).length">
                    <li v-for="(fact, index) in managerFactItems(candidate)" :key="`${candidate.candidate_id}-fact-${index}`">{{ managerFactStatement(fact) }}</li>
                  </ul>
                  <p v-else class="manager-research-empty">暂无可绑定的逐行事实。</p>
                </section>
                <div class="manager-research-conditions">
                  <section aria-label="确认条件">
                    <h5>确认条件</h5>
                    <ul v-if="managerConfirmations(candidate).length">
                      <li v-for="(condition, index) in managerConfirmations(candidate)" :key="`${candidate.candidate_id}-condition-${index}`">{{ condition }}</li>
                    </ul>
                    <p v-else class="manager-research-empty">待盘面确认。</p>
                  </section>
                  <section aria-label="关键反证与失效条件">
                    <h5>关键反证 / 失效条件</h5>
                    <ul v-if="managerCounterevidence(candidate).length || managerInvalidations(candidate).length">
                      <li v-for="(item, index) in managerCounterevidence(candidate)" :key="`${candidate.candidate_id}-counter-${index}`">{{ item }}</li>
                      <li v-for="(item, index) in managerInvalidations(candidate)" :key="`${candidate.candidate_id}-invalid-${index}`">失效：{{ item }}</li>
                    </ul>
                    <p v-else class="manager-research-empty">待补充反证。</p>
                  </section>
                </div>
                <details class="candidate-audit reason-details--evidence">
                  <summary>展开 AI / 审计详情（模型、typed gaps、状态与原始证据）</summary>
                  <section class="nonformal-reason" aria-label="为什么仍非formal">
                    <h5>为什么仍非formal</h5>
                    <p class="nonformal-risk-summary">{{ nonformalRiskSummary(candidate) }}</p>
                    <div class="gap-list" aria-label="非 formal typed gaps">
                      <span v-for="gap in typedGaps(candidate)" :key="`${candidate.candidate_id}-reason-gap-${gap}`">{{ gap }}</span>
                      <span v-if="!typedGaps(candidate).length">未声明缺口</span>
                    </div>
                  </section>
                  <section v-if="managerFactItems(candidate).length" class="reason-evidence reason-evidence--review" aria-label="经理研究审计绑定">
                    <h5>研究事实绑定</h5>
                    <ul class="reason-refs">
                      <li v-for="(fact, index) in managerFactItems(candidate)" :key="`${candidate.candidate_id}-fact-ref-${index}`"><code>{{ managerFactStatement(fact) }} · markdown_sha256={{ valueOrCannotConfirm(fact.markdown_sha256) }} · L{{ valueOrCannotConfirm(fact.line_start) }}-L{{ valueOrCannotConfirm(fact.line_end) }} · excerpt_sha256={{ valueOrCannotConfirm(fact.excerpt_sha256) }}</code></li>
                    </ul>
                  </section>
                  <dl class="focus-entry-audit-fields">
                    <div><dt>source_entity</dt><dd>{{ sourceEntity(candidate) }}</dd></div>
                    <div><dt>catalyst</dt><dd :title="selectionCatalyst(candidate)">{{ selectionCatalyst(candidate) }}</dd></div>
                    <div><dt>bucket</dt><dd>{{ candidate.bucket || "CANNOT_CONFIRM" }}</dd></div>
                    <div><dt>eligibility</dt><dd>{{ candidate.eligibility || "CANNOT_CONFIRM" }}</dd></div>
                    <div><dt>recommendation_status</dt><dd>{{ candidate.recommendation_status || "CANNOT_CONFIRM" }}</dd></div>
                  </dl>
                  <div class="candidate-boundary-summary" aria-label="字段摘要">
                    <strong>字段摘要（仅由当前 API 字段推导，不代表本地 receipt exact 正文）</strong>
                    <span>22:00 manager delta：{{ managerDeltaMembership(candidate) }}</span>
                    <span>D1 × official research queue：{{ researchQueueMembership(candidate) }}</span>
                    <span>{{ eligibilityPitSummary(candidate) }}</span>
                    <span>{{ openingObservationSummary() }}</span>
                    <span>交易授权：无（仅研究）</span>
                  </div>
                  <p class="reason-audit-summary">{{ modelReasonText(preselectionRowForCandidate(candidate)) }}</p>
                  <div class="reason-evidence-grid">
                  <section v-if="preselectionRowForCandidate(candidate)" class="reason-evidence" aria-label="模型证据">
                    <h5>模型证据</h5>
                    <div class="reason-audit-rank" aria-label="D-1 pool rank">D-1 pool rank：#{{ preselectionRowForCandidate(candidate)?.pool_rank }}</div>
                    <dl class="reason-fields">
                      <div><dt>pool</dt><dd>{{ poolDisplayName() }}</dd></div>
                      <div><dt>pool_id</dt><dd>{{ valueOrCannotConfirm(preselectionRowForCandidate(candidate)?.pool_id) }}</dd></div>
                      <div><dt>pool_rank</dt><dd>{{ preselectionMetric(preselectionRowForCandidate(candidate), "pool_rank") }}</dd></div>
                      <div><dt>pool_score</dt><dd>{{ preselectionScore(preselectionRowForCandidate(candidate)) }}</dd></div>
                      <div><dt>selected_strategy</dt><dd>{{ strategyValue(preselectionRowForCandidate(candidate)) }}</dd></div>
                      <div><dt>score_prob_active</dt><dd>{{ preselectionMetric(preselectionRowForCandidate(candidate), "score_prob_active") }}</dd></div>
                      <div><dt>score_prob_memory</dt><dd>{{ preselectionMetric(preselectionRowForCandidate(candidate), "score_prob_memory") }}</dd></div>
                      <div><dt>score_prob_crash_reflow</dt><dd>{{ preselectionMetric(preselectionRowForCandidate(candidate), "score_prob_crash_reflow") }}</dd></div>
                      <div><dt>ret_5d</dt><dd>{{ preselectionMetric(preselectionRowForCandidate(candidate), "ret_5d") }}</dd></div>
                      <div><dt>ret_20d</dt><dd>{{ preselectionMetric(preselectionRowForCandidate(candidate), "ret_20d") }}</dd></div>
                      <div><dt>ret_60d</dt><dd>{{ preselectionMetric(preselectionRowForCandidate(candidate), "ret_60d") }}</dd></div>
                      <div><dt>amount_ratio_20d</dt><dd>{{ preselectionMetric(preselectionRowForCandidate(candidate), "amount_ratio_20d") }}</dd></div>
                      <div><dt>recent_top20_count_20d</dt><dd>{{ preselectionMetric(preselectionRowForCandidate(candidate), "recent_top20_count_20d") }}</dd></div>
                    </dl>
                  </section>
                  <p v-else class="reason-evidence reason-evidence--unavailable">模型证据不可确认（目标日同码行缺失）</p>
                  <section class="reason-evidence" aria-label="官方事件证据">
                    <h5>官方事件证据</h5>
                    <dl class="reason-fields">
                      <div><dt>分类</dt><dd>{{ officialClassificationLabel(candidate) }}</dd></div>
                      <div><dt>材料标题/证据</dt><dd>{{ officialEvidenceText(candidate) }}</dd></div>
                      <div><dt>来源状态</dt><dd>{{ officialSourceStatusLabel(candidate) }}</dd></div>
                      <div><dt>published</dt><dd>{{ reasonValue(candidate, "published_at") }}</dd></div>
                      <div><dt>source time</dt><dd>{{ reasonValue(candidate, "source_time") }}</dd></div>
                    </dl>
                    <details class="reason-details">
                      <summary>原始英文标题、enum 与 source refs</summary>
                      <dl class="reason-fields reason-fields--raw">
                        <div><dt>classification enum</dt><dd><code>{{ officialClassificationRaw(candidate) }}</code></dd></div>
                        <div><dt>evidence raw</dt><dd><code>{{ officialEvidenceText(candidate) }}</code></dd></div>
                        <div><dt>source status raw</dt><dd><code>{{ officialSourceStatusRaw(candidate) }}</code></dd></div>
                        <div><dt>source_refs</dt><dd><code>{{ candidateSourceRefs(candidate).length ? "已保留原始引用" : "CANNOT_CONFIRM" }}</code></dd></div>
                      </dl>
                      <ul class="reason-refs">
                        <li v-for="(ref, index) in candidateSourceRefs(candidate)" :key="`${candidate.candidate_id}-reason-ref-${index}`"><code>{{ sourceRefText(ref) }}</code></li>
                        <li v-if="!candidateSourceRefs(candidate).length"><code>CANNOT_CONFIRM</code></li>
                      </ul>
                    </details>
                  </section>
                  </div>
                  <section class="reason-evidence reason-evidence--status" aria-label="非formal状态与边界">
                    <h5>状态与边界</h5>
                    <dl class="nonformal-fields">
                      <div><dt>research_status</dt><dd>research_status={{ reasonValue(candidate, "research_status") }}</dd></div>
                      <div><dt>recommendation_status</dt><dd>recommendation_status={{ reasonValue(candidate, "recommendation_status") }}</dd></div>
                      <div><dt>acceptance</dt><dd>acceptance={{ reasonValue(candidate, "acceptance") }}</dd></div>
                      <div><dt>promotion_allowed</dt><dd>promotion_allowed={{ promotionAllowedValue(candidate) }}</dd></div>
                      <div><dt>eligibility</dt><dd>eligibility={{ reasonValue(candidate, "eligibility") }}</dd></div>
                      <div><dt>pit_status</dt><dd>pit_status={{ reasonValue(candidate, "pit_status") }}</dd></div>
                    </dl>
                    <div class="gap-list" aria-label="原始 typed gap 枚举">
                      <code v-for="gap in gapCodes(candidate)" :key="`${candidate.candidate_id}-audit-gap-${gap}`">{{ gap }}</code>
                    </div>
                  </section>
                </details>
              </section>
            </article>
            <p v-if="!coreCandidates.length" class="focus-empty">{{ managerDecisionValid ? "当前没有可确认核心研究候选。" : "经理决策证据不可确认。" }}</p>
          </section>
          <section class="focus-column" aria-label="条件研究候选">
            <div class="focus-column__heading"><h3>条件研究</h3><span>{{ conditionalCandidates.length }} 条</span></div>
            <article v-for="candidate in conditionalCandidates" :key="`conditional-${candidate.candidate_id}`" class="focus-card focus-card--conditional">
              <div><strong>{{ candidateName(candidate) }}</strong><span>{{ candidateCode(candidate) }}</span></div>
              <span class="focus-boundary">经理研究集 / CONDITIONAL #{{ managerDecision(candidate)?.order }} / RESEARCH_ONLY / 非formal / 非BUY</span>
              <section class="reason-card" aria-label="经理研究逻辑（待盘面确认）">
                <h4>经理研究逻辑（待盘面确认）</h4>
                <section class="manager-decision-reason" aria-label="为什么进入经理研究集">
                  <h5>为什么进入经理研究集</h5>
                  <p>{{ managerDecision(candidate)?.reason || "CANNOT_CONFIRM" }}</p>
                </section>
                <p class="reason-card__summary">{{ managerThesis(candidate) }}</p>
                <section class="manager-research-facts" aria-label="已核实官方事实">
                  <h5>已核实官方事实</h5>
                  <ul v-if="managerFactItems(candidate).length">
                    <li v-for="(fact, index) in managerFactItems(candidate)" :key="`${candidate.candidate_id}-fact-${index}`">{{ managerFactStatement(fact) }}</li>
                  </ul>
                  <p v-else class="manager-research-empty">暂无可绑定的逐行事实。</p>
                </section>
                <div class="manager-research-conditions">
                  <section aria-label="确认条件">
                    <h5>确认条件</h5>
                    <ul v-if="managerConfirmations(candidate).length">
                      <li v-for="(condition, index) in managerConfirmations(candidate)" :key="`${candidate.candidate_id}-condition-${index}`">{{ condition }}</li>
                    </ul>
                    <p v-else class="manager-research-empty">待盘面确认。</p>
                  </section>
                  <section aria-label="关键反证与失效条件">
                    <h5>关键反证 / 失效条件</h5>
                    <ul v-if="managerCounterevidence(candidate).length || managerInvalidations(candidate).length">
                      <li v-for="(item, index) in managerCounterevidence(candidate)" :key="`${candidate.candidate_id}-counter-${index}`">{{ item }}</li>
                      <li v-for="(item, index) in managerInvalidations(candidate)" :key="`${candidate.candidate_id}-invalid-${index}`">失效：{{ item }}</li>
                    </ul>
                    <p v-else class="manager-research-empty">待补充反证。</p>
                  </section>
                </div>
                <details class="candidate-audit reason-details--evidence">
                  <summary>展开 AI / 审计详情（模型、typed gaps、状态与原始证据）</summary>
                  <section class="nonformal-reason" aria-label="为什么仍非formal">
                    <h5>为什么仍非formal</h5>
                    <p class="nonformal-risk-summary">{{ nonformalRiskSummary(candidate) }}</p>
                    <div class="gap-list" aria-label="非 formal typed gaps">
                      <span v-for="gap in typedGaps(candidate)" :key="`${candidate.candidate_id}-reason-gap-${gap}`">{{ gap }}</span>
                      <span v-if="!typedGaps(candidate).length">未声明缺口</span>
                    </div>
                  </section>
                  <section v-if="managerFactItems(candidate).length" class="reason-evidence reason-evidence--review" aria-label="经理研究审计绑定">
                    <h5>研究事实绑定</h5>
                    <ul class="reason-refs">
                      <li v-for="(fact, index) in managerFactItems(candidate)" :key="`${candidate.candidate_id}-fact-ref-${index}`"><code>{{ managerFactStatement(fact) }} · markdown_sha256={{ valueOrCannotConfirm(fact.markdown_sha256) }} · L{{ valueOrCannotConfirm(fact.line_start) }}-L{{ valueOrCannotConfirm(fact.line_end) }} · excerpt_sha256={{ valueOrCannotConfirm(fact.excerpt_sha256) }}</code></li>
                    </ul>
                  </section>
                  <dl class="focus-entry-audit-fields">
                    <div><dt>source_entity</dt><dd>{{ sourceEntity(candidate) }}</dd></div>
                    <div><dt>catalyst</dt><dd :title="selectionCatalyst(candidate)">{{ selectionCatalyst(candidate) }}</dd></div>
                    <div><dt>bucket</dt><dd>{{ candidate.bucket || "CANNOT_CONFIRM" }}</dd></div>
                    <div><dt>eligibility</dt><dd>{{ candidate.eligibility || "CANNOT_CONFIRM" }}</dd></div>
                    <div><dt>recommendation_status</dt><dd>{{ candidate.recommendation_status || "CANNOT_CONFIRM" }}</dd></div>
                  </dl>
                  <div class="candidate-boundary-summary" aria-label="字段摘要">
                    <strong>字段摘要（仅由当前 API 字段推导，不代表本地 receipt exact 正文）</strong>
                    <span>22:00 manager delta：{{ managerDeltaMembership(candidate) }}</span>
                    <span>D1 × official research queue：{{ researchQueueMembership(candidate) }}</span>
                    <span>{{ eligibilityPitSummary(candidate) }}</span>
                    <span>{{ openingObservationSummary() }}</span>
                    <span>交易授权：无（仅研究）</span>
                  </div>
                  <p class="reason-audit-summary">{{ modelReasonText(preselectionRowForCandidate(candidate)) }}</p>
                  <div class="reason-evidence-grid">
                  <section v-if="preselectionRowForCandidate(candidate)" class="reason-evidence" aria-label="模型证据">
                    <h5>模型证据</h5>
                    <div class="reason-audit-rank" aria-label="D-1 pool rank">D-1 pool rank：#{{ preselectionRowForCandidate(candidate)?.pool_rank }}</div>
                    <dl class="reason-fields">
                      <div><dt>pool</dt><dd>{{ poolDisplayName() }}</dd></div>
                      <div><dt>pool_id</dt><dd>{{ valueOrCannotConfirm(preselectionRowForCandidate(candidate)?.pool_id) }}</dd></div>
                      <div><dt>pool_rank</dt><dd>{{ preselectionMetric(preselectionRowForCandidate(candidate), "pool_rank") }}</dd></div>
                      <div><dt>pool_score</dt><dd>{{ preselectionScore(preselectionRowForCandidate(candidate)) }}</dd></div>
                      <div><dt>selected_strategy</dt><dd>{{ strategyValue(preselectionRowForCandidate(candidate)) }}</dd></div>
                      <div><dt>score_prob_active</dt><dd>{{ preselectionMetric(preselectionRowForCandidate(candidate), "score_prob_active") }}</dd></div>
                      <div><dt>score_prob_memory</dt><dd>{{ preselectionMetric(preselectionRowForCandidate(candidate), "score_prob_memory") }}</dd></div>
                      <div><dt>score_prob_crash_reflow</dt><dd>{{ preselectionMetric(preselectionRowForCandidate(candidate), "score_prob_crash_reflow") }}</dd></div>
                      <div><dt>ret_5d</dt><dd>{{ preselectionMetric(preselectionRowForCandidate(candidate), "ret_5d") }}</dd></div>
                      <div><dt>ret_20d</dt><dd>{{ preselectionMetric(preselectionRowForCandidate(candidate), "ret_20d") }}</dd></div>
                      <div><dt>ret_60d</dt><dd>{{ preselectionMetric(preselectionRowForCandidate(candidate), "ret_60d") }}</dd></div>
                      <div><dt>amount_ratio_20d</dt><dd>{{ preselectionMetric(preselectionRowForCandidate(candidate), "amount_ratio_20d") }}</dd></div>
                      <div><dt>recent_top20_count_20d</dt><dd>{{ preselectionMetric(preselectionRowForCandidate(candidate), "recent_top20_count_20d") }}</dd></div>
                    </dl>
                  </section>
                  <p v-else class="reason-evidence reason-evidence--unavailable">模型证据不可确认（目标日同码行缺失）</p>
                  <section class="reason-evidence" aria-label="官方事件证据">
                    <h5>官方事件证据</h5>
                    <dl class="reason-fields">
                      <div><dt>分类</dt><dd>{{ officialClassificationLabel(candidate) }}</dd></div>
                      <div><dt>材料标题/证据</dt><dd>{{ officialEvidenceText(candidate) }}</dd></div>
                      <div><dt>来源状态</dt><dd>{{ officialSourceStatusLabel(candidate) }}</dd></div>
                      <div><dt>published</dt><dd>{{ reasonValue(candidate, "published_at") }}</dd></div>
                      <div><dt>source time</dt><dd>{{ reasonValue(candidate, "source_time") }}</dd></div>
                    </dl>
                    <details class="reason-details">
                      <summary>原始英文标题、enum 与 source refs</summary>
                      <dl class="reason-fields reason-fields--raw">
                        <div><dt>classification enum</dt><dd><code>{{ officialClassificationRaw(candidate) }}</code></dd></div>
                        <div><dt>evidence raw</dt><dd><code>{{ officialEvidenceText(candidate) }}</code></dd></div>
                        <div><dt>source status raw</dt><dd><code>{{ officialSourceStatusRaw(candidate) }}</code></dd></div>
                        <div><dt>source_refs</dt><dd><code>{{ candidateSourceRefs(candidate).length ? "已保留原始引用" : "CANNOT_CONFIRM" }}</code></dd></div>
                      </dl>
                      <ul class="reason-refs">
                        <li v-for="(ref, index) in candidateSourceRefs(candidate)" :key="`${candidate.candidate_id}-reason-ref-${index}`"><code>{{ sourceRefText(ref) }}</code></li>
                        <li v-if="!candidateSourceRefs(candidate).length"><code>CANNOT_CONFIRM</code></li>
                      </ul>
                    </details>
                  </section>
                  </div>
                  <section class="reason-evidence reason-evidence--status" aria-label="非formal状态与边界">
                    <h5>状态与边界</h5>
                    <dl class="nonformal-fields">
                      <div><dt>research_status</dt><dd>research_status={{ reasonValue(candidate, "research_status") }}</dd></div>
                      <div><dt>recommendation_status</dt><dd>recommendation_status={{ reasonValue(candidate, "recommendation_status") }}</dd></div>
                      <div><dt>acceptance</dt><dd>acceptance={{ reasonValue(candidate, "acceptance") }}</dd></div>
                      <div><dt>promotion_allowed</dt><dd>promotion_allowed={{ promotionAllowedValue(candidate) }}</dd></div>
                      <div><dt>eligibility</dt><dd>eligibility={{ reasonValue(candidate, "eligibility") }}</dd></div>
                      <div><dt>pit_status</dt><dd>pit_status={{ reasonValue(candidate, "pit_status") }}</dd></div>
                    </dl>
                    <div class="gap-list" aria-label="原始 typed gap 枚举">
                      <code v-for="gap in gapCodes(candidate)" :key="`${candidate.candidate_id}-audit-gap-${gap}`">{{ gap }}</code>
                    </div>
                  </section>
                </details>
              </section>
            </article>
            <p v-if="!conditionalCandidates.length" class="focus-empty">{{ managerDecisionValid ? "当前没有可确认条件研究候选。" : "经理决策证据不可确认。" }}</p>
          </section>
        </div>
      </section>

      <section class="manager-panel workflow-panel" aria-label="经理研究工作流">
        <div class="panel-heading">
          <div><p class="manager-eyebrow">EVIDENCE WORKFLOW</p><h2>经理研究流程</h2></div>
          <p>复用 Vibe 团队审议结构；不是第二 producer。</p>
        </div>
        <ol class="workflow-track">
          <li><strong>D-1 模型池</strong><span>{{ preselectionState === "READY" ? "HK Connect D-1 Top100 已读取" : "CANNOT_CONFIRM" }}</span></li>
          <li><strong>官方事实核验</strong><span>{{ researchCount }} 条研究账本；逐行材料按候选保留</span></li>
          <li><strong>typed 经理决策</strong><span>{{ managerDecisionValid ? "2200 READY · 角色/顺序已绑定" : "CANNOT_CONFIRM" }}</span></li>
          <li><strong>08:30 待自然</strong><span>{{ phaseStatus("0830") }}</span></li>
          <li><strong>09:35 待自然</strong><span>{{ phaseStatus("0935") }}</span></li>
        </ol>
      </section>

      <section class="manager-panel formal-panel" aria-label="正式名单">
        <div class="panel-heading">
          <div><p class="manager-eyebrow">FORMAL SHORTLIST</p><h2>正式名单</h2></div>
          <span class="status-pill status-pill--muted">{{ formalIds.length }} 条</span>
        </div>
        <div v-if="formalCandidates.length" class="formal-list">
          <article v-for="candidate in formalCandidates" :key="`formal-${candidate.candidate_id}`" class="formal-card">
            <strong>{{ candidateName(candidate) }}</strong><span>{{ candidateCode(candidate) }} · {{ candidate.bucket }}</span>
          </article>
        </div>
        <p v-else class="panel-note">当前正式名单为空；这不是把条件研究候选升级为正式推荐。</p>
      </section>
      <div id="manager-queue-slot" class="manager-queue-slot"></div>
    </template>

    <section id="manager-phases" class="manager-panel phase-panel" aria-label="阶段航迹">
      <div class="panel-heading">
        <div><p class="manager-eyebrow">DECISION TRAIL</p><h2>阶段航迹</h2></div>
        <p>轨道在证据断点处中止；未物化不等于 0。</p>
      </div>
      <details class="phase-details">
        <summary>展开阶段航迹（2200 → 08:30 → 09:35 → 16:20）</summary>
        <div class="phase-track">
          <article v-for="phase in PHASES" :key="phase.key" class="phase-node" :class="`phase-node--${statusClass(phaseStatus(phase.key))}`">
            <div class="phase-node__top"><span>{{ phase.key }}</span><b>{{ phaseStatus(phase.key) }}</b></div>
            <h3>{{ phase.wireLabel ? `${phase.label}（${phase.wireLabel}）` : phase.label }}</h3>
            <p>{{ phase.description }}</p>
            <strong>{{ phaseCandidateLabel(phase.key) }}</strong>
            <code>{{ phaseRunText(phase.key) }}</code>
            <span v-if="phase.key === '0830'" class="phase-mapping-gap">CANNOT_CONFIRM_PHASE_MAPPING</span>
          </article>
        </div>
      </details>
    </section>

    <section id="manager-ledger" class="manager-panel ledger-panel" aria-label="完整研究账本">
      <div class="panel-heading">
        <div><p class="manager-eyebrow">RESEARCH LEDGER</p><h2>完整研究账本</h2></div>
        <p v-if="materialized"><span class="ledger-count-label">{{ researchCount }} 条研究候选</span> · 全量可搜索</p>
        <p v-else>候选列表不可确认</p>
      </div>
      <details v-if="materialized" class="ledger-details">
        <summary>展开研究账本（{{ researchCount }} 条；可搜索）</summary>
        <div class="ledger-tools">
          <label for="manager-selection-search">搜索研究候选</label>
          <input id="manager-selection-search" v-model="searchQuery" type="search" placeholder="代码、名称、催化剂、证据…" />
          <label for="manager-selection-bucket">筛选 bucket</label>
          <select id="manager-selection-bucket" v-model="bucketFilter">
            <option value="ALL">全部 bucket</option>
            <option v-for="bucket in bucketOptions" :key="bucket" :value="bucket">{{ bucket }}</option>
          </select>
        </div>
        <p class="ledger-count-note">总量：{{ researchCount }} 条研究候选；当前显示 {{ filteredCandidates.length }} 条。</p>
        <div v-if="filteredCandidates.length" class="ledger-list">
          <article v-for="candidate in filteredCandidates" :key="candidate.candidate_id" class="ledger-entry">
            <header class="ledger-entry__header">
              <div><strong>{{ candidateName(candidate) }} · {{ candidateCode(candidate) }}</strong><span>{{ sourceEntity(candidate) }} · {{ bucketLabel(candidate) }} · {{ candidate.bucket || "CANNOT_CONFIRM" }}</span></div>
              <span class="status-pill status-pill--research">{{ candidate.recommendation_status || "CANNOT_CONFIRM" }}</span>
            </header>
            <dl class="candidate-fields">
              <div><dt>bucket</dt><dd>{{ candidate.bucket || "CANNOT_CONFIRM" }}</dd></div>
              <div><dt>催化剂</dt><dd :title="displayValue(candidate.catalyst)">{{ selectionCatalyst(candidate) }}</dd></div>
              <div><dt>证据</dt><dd :title="displayValue(candidate.evidence_level)">{{ primaryValue(candidate.evidence_level) }}</dd></div>
              <div><dt>eligibility</dt><dd>{{ candidate.eligibility || "CANNOT_CONFIRM" }}</dd></div>
              <div><dt>PIT</dt><dd>{{ candidate.pit_status || "CANNOT_CONFIRM" }}</dd></div>
              <div><dt>recommendation</dt><dd>{{ candidate.recommendation_status || "CANNOT_CONFIRM" }}</dd></div>
              <div><dt>published</dt><dd>{{ candidate.published_at || "CANNOT_CONFIRM" }}</dd></div>
              <div><dt>source time</dt><dd>{{ candidate.source_time || "CANNOT_CONFIRM" }}</dd></div>
              <div><dt>counterevidence</dt><dd :title="displayValue(candidate.counterevidence)">{{ primaryValue(candidate.counterevidence) }}</dd></div>
              <div><dt>invalidation</dt><dd :title="displayValue(candidate.invalidation)">{{ primaryValue(candidate.invalidation) }}</dd></div>
            </dl>
            <div class="ledger-entry__notes">
              <div><span>研究状态</span><code>{{ candidate.research_status || "CANNOT_CONFIRM" }} · {{ candidate.acceptance || "CANNOT_CONFIRM" }}</code></div>
              <div><span>来源引用（只显示 ref，不读取本地路径）</span><ul><li v-for="(ref, index) in candidate.source_refs || []" :key="`${candidate.candidate_id}-ref-${index}`"><code>{{ sourceRefText(ref) }}</code></li><li v-if="!candidate.source_refs?.length"><code>CANNOT_CONFIRM</code></li></ul></div>
              <div><span>typed gaps</span><div class="gap-list"><span v-for="gap in typedGaps(candidate)" :key="gap">{{ gap }}</span><span v-if="!typedGaps(candidate).length">无声明缺口</span></div></div>
            </div>
          </article>
        </div>
        <p v-else class="ledger-empty">当前筛选没有可确认候选；总量仍为 {{ researchCount }} 条。</p>
      </details>
      <p v-else class="ledger-empty">完整研究账本不可用：{{ displayStatus }}。不展示候选，也不把缺失转换为 0。</p>
    </section>

    <section id="manager-lineage" class="manager-panel lineage-panel" aria-label="证据血缘">
      <div class="panel-heading">
        <div><p class="manager-eyebrow">EVIDENCE LINEAGE</p><h2>证据血缘</h2></div>
        <p>artifact → manifest → receipt → current；只显示 API 已提供的 ref。</p>
      </div>
      <details class="lineage-details">
        <summary>展开证据血缘（artifact → manifest → receipt → current）</summary>
        <dl class="lineage-grid">
          <div v-for="part in [
            { key: 'artifact', label: 'artifact' },
            { key: 'manifest', label: 'manifest' },
            { key: 'receipt', label: 'receipt' },
            { key: 'current', label: 'current' },
          ]" :key="part.key">
            <dt>{{ part.label }}_sha256</dt>
            <dd><code>{{ lineageSha(part.key as 'artifact' | 'manifest' | 'receipt' | 'current') }}</code></dd>
          </div>
        </dl>
        <div class="manager-ref" aria-label="独立经理决定摘要">
          <strong>typed manager decision · path-free</strong>
          <code v-if="managerDecisionPayload?.lineage">{{ displayValue(managerDecisionPayload.lineage) }}</code>
          <code v-else>CANNOT_CONFIRM</code>
        </div>
        <p v-if="payload?.first_failed_layer" class="first-failure"><span>first_failed_layer</span><strong>{{ payload.first_failed_layer }}</strong></p>
        <p v-if="payload?.cannot_confirm?.length" class="cannot-list"><span>cannot_confirm</span><b v-for="(item, index) in payload.cannot_confirm" :key="`${String(item)}-${index}`">{{ displayValue(item) }}</b></p>
      </details>
    </section>

    <aside class="manager-safety" aria-label="安全边界">
      <div><p class="manager-eyebrow">SAFETY BOUNDARY</p><strong>研究只读边界</strong><span>只更新研究材料，不提交交易。</span></div>
      <ul>
        <li :class="{ confirmed: safetyFlag('RESEARCH_ONLY', true) === 'true' }"><code>RESEARCH_ONLY={{ safetyFlag('RESEARCH_ONLY', true) }}</code></li>
        <li :class="{ confirmed: safetyFlag('production_allowed', false) === 'false' }"><code>production_allowed={{ safetyFlag('production_allowed', false) }}</code></li>
        <li :class="{ confirmed: safetyFlag('buy_gate_updated', false) === 'false' }"><code>buy_gate_updated={{ safetyFlag('buy_gate_updated', false) }}</code></li>
        <li :class="{ confirmed: safetyFlag('orders_sent', false) === 'false' }"><code>orders_sent={{ safetyFlag('orders_sent', false) }}</code></li>
      </ul>
    </aside>
    </details>
  </main>
</template>
