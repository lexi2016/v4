export const MANAGER_WORKBENCH_RESEARCH_SCHEMA = "v4.manager_workbench.research.v1" as const;
export const MANAGER_WORKBENCH_MARKET = "HK_CONNECT" as const;
export const MANAGER_WORKBENCH_SLOT = "1530" as const;

export const MANAGER_WORKBENCH_RESEARCH_STATUSES = [
  "PENDING_SLOT",
  "NOT_RUN",
  "READY",
  "READY_EMPTY",
  "PARTIAL",
  "INPUT_MISSING",
  "STALE",
  "FAILED",
  "NOT_APPLICABLE",
] as const;

export type ManagerWorkbenchResearchStatus = typeof MANAGER_WORKBENCH_RESEARCH_STATUSES[number];
export type PredicateValue = true | false | "unknown";
export type ManagerWorkbenchSourceLane = "STAGE" | "CLOSE_DISCOVERY" | "CONTINUOUS_TRACKING";

export type ManagerWorkbenchSourceRef = Readonly<{
  owner: string | null;
  role: string | null;
  artifact_ref: string | null;
  manifest_ref: string | null;
  receipt_ref: string | null;
  run_id: string | null;
  sha256: string | null;
  source_date: string | null;
  market: typeof MANAGER_WORKBENCH_MARKET;
  lane: ManagerWorkbenchSourceLane | null;
  reason: string | null;
  observed_at: string | null;
  available_at: string | null;
}>;

export type ManagerWorkbenchPredicate = Readonly<{
  predicate_id: string | null;
  value: PredicateValue;
  reason: string | null;
  input_refs: readonly string[];
  rule_version: string | null;
}>;

export type ManagerWorkbenchSummaryItem = Readonly<{
  item_id: string | null;
  candidate_id: string | null;
  name: string;
  occurred_at: string;
  reason: string;
  evidence_status: string;
  kind: string | null;
}>;

export type ManagerWorkbenchTurnoverAmount = Readonly<Record<string, unknown> & {
  value: number | null;
  currency: string;
  unit: string;
  as_of: string;
}>;

export type ManagerWorkbenchVolumeComparison = Readonly<Record<string, unknown> & {
  state: string;
  ratio: number | null;
  baseline_as_of: string | null;
}>;

export type ManagerWorkbenchCandidate = Readonly<{
  candidate_id: string;
  symbol: string;
  name: string;
  source_lanes: readonly ManagerWorkbenchSourceLane[];
  first_seen_at: string;
  last_seen_at: string;
  observed_at: string;
  available_at: string;
  turnover_amount: ManagerWorkbenchTurnoverAmount | null;
  volume_comparison: ManagerWorkbenchVolumeComparison | null;
  position: Record<string, unknown> | null;
  catalyst: Record<string, unknown> | null;
  research_priority: Record<string, unknown> | null;
  data_status: string;
  attention_reason: string | null;
  predicates: readonly ManagerWorkbenchPredicate[];
  sources: readonly ManagerWorkbenchSourceRef[];
  risks: readonly unknown[];
  observation_plan: Record<string, unknown> | null;
  qualified: boolean | null;
  trade_date: string;
}>;

export type ManagerWorkbenchResearchResponse = Readonly<{
  schema_version: typeof MANAGER_WORKBENCH_RESEARCH_SCHEMA;
  market: typeof MANAGER_WORKBENCH_MARKET;
  trade_date: string;
  slot: typeof MANAGER_WORKBENCH_SLOT;
  as_of: string | null;
  generated_at: string | null;
  run_id: string | null;
  status: ManagerWorkbenchResearchStatus;
  rule_version: string;
  cache_key: string;
  universe: ManagerWorkbenchSourceRef | null;
  coverage: Readonly<{
    eligible_count: number | null;
    covered_count: number | null;
    missing_count: number | null;
    missing_reasons: readonly string[];
  }>;
  cannot_confirm: readonly string[];
  priority_summary: Readonly<{
    focus: readonly ManagerWorkbenchSummaryItem[];
    theme_changes: readonly ManagerWorkbenchSummaryItem[];
    risk_upgrades: readonly ManagerWorkbenchSummaryItem[];
  }>;
  candidates: readonly ManagerWorkbenchCandidate[];
  RESEARCH_ONLY: true;
  production_allowed: false;
  buy_gate_updated: false;
  orders_sent: false;
}>;

const STATUS_SET = new Set<string>(MANAGER_WORKBENCH_RESEARCH_STATUSES);
const SOURCE_LANE_SET = new Set<string>(["STAGE", "CLOSE_DISCOVERY", "CONTINUOUS_TRACKING"]);
const HK_SYMBOL = /^HK\.\d{5}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const OFFSET_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
const SENSITIVE_TEXT = /(?:Traceback \(most recent call last\)|Bearer\s+[A-Za-z0-9._~+/-]{8,}|(?:api[_-]?key|access[_-]?token|auth[_-]?token)\s*[:=]\s*\S+|sk-[A-Za-z0-9_-]{8,}|\/Users\/[^\s]+|\/home\/[^\s]+)/i;
const FORBIDDEN_KEYS = new Set(["token", "password", "secret", "traceback", "stack", "stacktrace", "apikey", "accesstoken", "authtoken"]);
const VISIBLE_STATUSES = new Set(["READY", "PARTIAL", "STALE"]);
const NON_DATA_STATUSES = new Set(["PENDING_SLOT", "NOT_RUN", "INPUT_MISSING", "FAILED", "NOT_APPLICABLE"]);
// B1 has no B2 predicate definitions: every declared required predicate must be true.
const QUALIFIED_PREDICATE_POLICY = "ALL_DECLARED_PREDICATES";

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function hasOwn(value: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(value, key);
}

function containsUnsafeDiagnostic(value: unknown): boolean {
  if (typeof value === "string") return SENSITIVE_TEXT.test(value);
  if (Array.isArray(value)) return value.some(containsUnsafeDiagnostic);
  if (!isRecord(value)) return false;
  return Object.entries(value).some(([key, item]) => {
    const normalized = key.toLowerCase().replaceAll("_", "").replaceAll("-", "");
    return FORBIDDEN_KEYS.has(normalized) || containsUnsafeDiagnostic(item);
  });
}

function localPath(value: string): boolean {
  return value.startsWith("/") || value.startsWith("./") || value.startsWith("../") || /^[A-Za-z]:[\\/]/.test(value);
}

function realDate(value: string): boolean {
  if (!/^\d{8}$/.test(value)) return false;
  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(4, 6));
  const day = Number(value.slice(6, 8));
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return parsed.getUTCFullYear() === year && parsed.getUTCMonth() === month - 1 && parsed.getUTCDate() === day;
}

function offsetTime(value: unknown, required: boolean): boolean {
  if (value === null || value === undefined || value === "") return !required;
  return typeof value === "string" && OFFSET_TIME.test(value) && Number.isFinite(Date.parse(value));
}

function notAfter(value: unknown, asOf: unknown): boolean {
  if (value === null || value === undefined || value === "" || asOf === null || asOf === undefined || asOf === "") return true;
  if (typeof value !== "string" || typeof asOf !== "string") return false;
  const valueTime = Date.parse(value);
  const asOfTime = Date.parse(asOf);
  return Number.isFinite(valueTime) && Number.isFinite(asOfTime) && valueTime <= asOfTime;
}

function textOrNull(value: unknown): boolean {
  return value === null || (typeof value === "string" && value.trim().length > 0);
}

function stringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function countOrNull(value: unknown): boolean {
  return value === null || (typeof value === "number" && Number.isInteger(value) && value >= 0);
}

function finiteNumberOrNull(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isFinite(value));
}

function turnoverAmount(value: unknown, asOf: unknown): value is ManagerWorkbenchTurnoverAmount {
  if (!isRecord(value) || !hasOwn(value, "as_of") || !hasOwn(value, "currency") || !hasOwn(value, "unit")) return false;
  return offsetTime(value.as_of, true)
    && notAfter(value.as_of, asOf)
    && typeof value.currency === "string" && Boolean(value.currency.trim())
    && typeof value.unit === "string" && Boolean(value.unit.trim())
    && finiteNumberOrNull(value.value);
}

function volumeComparison(value: unknown, asOf: unknown): value is ManagerWorkbenchVolumeComparison {
  if (!isRecord(value) || !hasOwn(value, "baseline_as_of") || !hasOwn(value, "ratio")) return false;
  if (typeof value.state !== "string" || !value.state.trim()) return false;
  if (!(value.baseline_as_of === null || offsetTime(value.baseline_as_of, true))) return false;
  if (!notAfter(value.baseline_as_of, asOf) || !finiteNumberOrNull(value.ratio)) return false;
  // A missing baseline is only an explicit unknown; a defined ratio must have
  // a timestamp that can be checked against the exact envelope as_of.
  return value.baseline_as_of !== null || (value.state === "unknown" && value.ratio === null);
}

function sourceRef(value: unknown): value is ManagerWorkbenchSourceRef {
  if (!isRecord(value) || value.market !== MANAGER_WORKBENCH_MARKET) return false;
  for (const field of ["owner", "role", "artifact_ref", "manifest_ref", "receipt_ref", "run_id", "source_date", "reason"]) {
    if (!textOrNull(value[field])) return false;
  }
  for (const field of ["artifact_ref", "manifest_ref", "receipt_ref"]) {
    if (typeof value[field] === "string" && localPath(value[field])) return false;
  }
  if (!(value.lane === null || (typeof value.lane === "string" && SOURCE_LANE_SET.has(value.lane)))) return false;
  if (!offsetTime(value.observed_at, false) || !offsetTime(value.available_at, false)) return false;
  if (!(value.sha256 === null || (typeof value.sha256 === "string" && SHA256.test(value.sha256)))) return false;
  if (!(value.source_date === null || (typeof value.source_date === "string" && realDate(value.source_date)))) return false;
  return true;
}

function completeLineage(value: unknown, requireLane: boolean): value is ManagerWorkbenchSourceRef {
  if (!sourceRef(value) || !textOrNull(value.owner) || !textOrNull(value.role)
    || !textOrNull(value.run_id) || !textOrNull(value.source_date)
    || typeof value.sha256 !== "string" || !SHA256.test(value.sha256)) return false;
  if (typeof value.source_date !== "string" || !realDate(value.source_date)) return false;
  if (!value.artifact_ref && !value.manifest_ref && !value.receipt_ref) return false;
  return !requireLane || typeof value.lane === "string";
}

function predicate(value: unknown): value is ManagerWorkbenchPredicate {
  if (!isRecord(value)) return false;
  if (!(value.value === true || value.value === false || value.value === "unknown")) return false;
  if (!textOrNull(value.predicate_id) || !textOrNull(value.reason) || !textOrNull(value.rule_version)) return false;
  return stringArray(value.input_refs);
}

function summaryItem(value: unknown, asOf: unknown): value is ManagerWorkbenchSummaryItem {
  if (!isRecord(value)) return false;
  return textOrNull(value.item_id)
    && textOrNull(value.candidate_id)
    && typeof value.name === "string" && Boolean(value.name.trim())
    && offsetTime(value.occurred_at, true)
    && notAfter(value.occurred_at, asOf)
    && typeof value.reason === "string" && Boolean(value.reason.trim())
    && typeof value.evidence_status === "string" && Boolean(value.evidence_status.trim())
    && textOrNull(value.kind);
}

function candidate(value: unknown, date: string, asOf: unknown, visible: boolean): value is ManagerWorkbenchCandidate {
  if (!isRecord(value)) return false;
  if (typeof value.candidate_id !== "string" || !value.candidate_id.trim()) return false;
  if (typeof value.symbol !== "string" || !HK_SYMBOL.test(value.symbol)) return false;
  if (typeof value.name !== "string" || !value.name.trim()) return false;
  if (!stringArray(value.source_lanes) || value.source_lanes.length === 0) return false;
  if (new Set(value.source_lanes).size !== value.source_lanes.length || value.source_lanes.some((lane) => !SOURCE_LANE_SET.has(lane))) return false;
  if (!offsetTime(value.first_seen_at, true) || !offsetTime(value.last_seen_at, true)
    || !offsetTime(value.observed_at, true) || !offsetTime(value.available_at, true)
    || !notAfter(value.first_seen_at, asOf) || !notAfter(value.last_seen_at, asOf)
    || !notAfter(value.observed_at, asOf) || !notAfter(value.available_at, asOf)) return false;
  if (!(value.turnover_amount === null || turnoverAmount(value.turnover_amount, asOf))) return false;
  if (!(value.volume_comparison === null || volumeComparison(value.volume_comparison, asOf))) return false;
  for (const field of ["position", "catalyst", "research_priority", "observation_plan"]) {
    if (!(value[field] === null || isRecord(value[field]))) return false;
  }
  if (typeof value.data_status !== "string" || !value.data_status.trim()) return false;
  if (!textOrNull(value.attention_reason)) return false;
  if (!Array.isArray(value.predicates) || !value.predicates.every(predicate)) return false;
  if (!Array.isArray(value.sources) || !value.sources.every(sourceRef)) return false;
  const sources = value.sources as ManagerWorkbenchSourceRef[];
  const declaredLanes = new Set(value.source_lanes);
  if (sources.some((source) => source.lane !== null && !declaredLanes.has(source.lane))) return false;
  if (visible && (!sources.every((source) => completeLineage(source, true))
    || value.source_lanes.some((lane) => !sources.some((source) => source.lane === lane)))) return false;
  if (!Array.isArray(value.risks)) return false;
  if (!(value.qualified === true || value.qualified === false || value.qualified === null)) return false;
  if (QUALIFIED_PREDICATE_POLICY === "ALL_DECLARED_PREDICATES" && value.qualified === true && (value.predicates.length === 0
    || value.predicates.some((item) => item.value !== true || !item.predicate_id || !item.rule_version))) return false;
  if (value.trade_date !== date) return false;
  return true;
}

const R2_RULE = "manager-close-rework-r2-v1";
const R2_CONDITIONS = ["turnover_gt_100m_hkd", "verified_volume_expansion", "verified_oversold_or_breakout", "new_direct_pit_catalyst"];
function hongKongDate(value: string): string {
  return new Date(Date.parse(value) + 8 * 3600_000).toISOString().slice(0,10).replaceAll("-", "");
}

function r2EvidenceContract(value: Record<string, unknown>, candidates: readonly ManagerWorkbenchCandidate[], date: string): string | null {
  if (value.rule_version !== R2_RULE || !["READY", "READY_EMPTY", "PARTIAL", "STALE"].includes(String(value.status))) return null;
  const asOf = String(value.as_of), generated = String(value.generated_at);
  const local = new Date(Date.parse(asOf) + 8 * 3600_000);
  if (hongKongDate(asOf) !== date || local.getUTCHours() !== 15 || local.getUTCMinutes() < 30 || local.getUTCMinutes() >= 32
    || Date.parse(generated) < Date.parse(asOf)) return "尾盘观察时点不符";
  const coverage = value.coverage as Record<string, unknown>;
  if ([coverage.eligible_count, coverage.covered_count, coverage.missing_count].some(x=>typeof x !== "number")
    || Number(coverage.covered_count) + Number(coverage.missing_count) !== coverage.eligible_count) return "覆盖数量不一致";
  for (const c of candidates) {
    if (c.predicates.length !== 4 || c.predicates.some((p,i)=>p.predicate_id !== R2_CONDITIONS[i] || p.rule_version !== R2_RULE)) return "四项条件定义不完整";
    // This revision has no approved positive volume/position authority adapter.
    if (c.predicates[1]?.value !== "unknown" || c.predicates[2]?.value !== "unknown") return "放量或历史位置来源未获验证";
    const expected = c.predicates.some(p=>p.value === false) ? false : null;
    if (c.qualified !== expected) return "合格状态与已核条件冲突";
    if (c.predicates[0]?.value !== "unknown") {
      const amount = c.turnover_amount;
      if (!amount || amount.currency !== "HKD" || amount.unit !== "HKD" || amount.status !== "OBSERVED"
        || amount.contract_state !== "VERIFIED_HKD" || typeof amount.value !== "number"
        || c.predicates[0]?.value !== (amount.value > 100_000_000)) return "港元成交额未验证";
    }
    if (c.predicates[3]?.value === true) {
      const catalyst = c.catalyst;
      if (!catalyst || catalyst.status !== "CONFIRMED_PIT" || !Array.isArray(catalyst.evidence) || !catalyst.evidence.length) return "催化时间证据缺失";
      for (const e of catalyst.evidence) {
        if (!isRecord(e) || typeof e.publication_sha256 !== "string" || !SHA256.test(e.publication_sha256)) return "催化文件身份缺失";
        for (const key of ["published_at", "first_seen_at", "available_at"]) {
          if (!offsetTime(e[key], true) || !notAfter(e[key], asOf)) return "催化越过观察时点";
        }
        if (hongKongDate(String(e.first_seen_at)) !== date) return "催化不是当日新增";
      }
    }
    for (const source of c.sources) {
      for (const key of ["source_date", "run_id", "sha256", "reason", "observed_at", "available_at"] as const) {
        if (!source[key]) return "独立来源信息缺失";
      }
      if (!notAfter(source.observed_at, asOf) || !notAfter(source.available_at, asOf)) return "来源越过观察时点";
    }
  }
  return null;
}

const REBOUND_RULE = "20260921_REBOUND_V3_1530_OBSERVATION_V1";
const REBOUND_IDS = ["amount_100m_lt_le_200m_hkd", "oversold_le_80pct_prior60_high",
  "volume_ge_1_5_previous5_full_days", "last_price_ge_1_03_low_so_far", "final_close_confirmation"];
function reboundEvidenceContract(value: Record<string, unknown>, candidates: readonly ManagerWorkbenchCandidate[]): string | null {
  if (value.rule_version !== REBOUND_RULE) return null;
  const screen = value.rebound_screen;
  if (!isRecord(screen) || screen.rule_version !== REBOUND_RULE || screen.phase !== "SNAPSHOT_1530_NOT_FINAL_CLOSE"
      || screen.final_close !== null || screen.confirmed_strict_count !== 0) return "15:30观察不得冒充收盘确认";
  const groups: Record<string, string[]> = { strict_observation: [], near_observation: [], pending: [] };
  for (const c of candidates) {
    const d = c.position?.rebound_v3;
    if (!isRecord(d) || d.phase !== screen.phase || d.final_close !== null || d.close_confirmation !== "unknown"
        || !isRecord(d.metrics) || !isRecord(d.metrics.gates)) return "反弹时点或数值来源缺失";
    const g = d.metrics.gates;
    const gates = [g.amount, g.oversold, g.volume, g.rebound];
    if (gates.some(v => v !== true && v !== false && v !== "unknown")) return "反弹条件值无效";
    const strict = gates.every(v => v === true);
    const near = g.amount === true && g.oversold === true && [g.volume, g.rebound].every(v => v !== "unknown")
      && Number(g.volume === true) + Number(g.rebound === true) === 1;
    const expected = g.amount === false || g.oversold === false ? "EXCLUDED" : gates.includes("unknown")
      ? "PENDING_EVIDENCE" : strict ? "STRICT_ASOF_OBSERVATION" : near ? "NEAR_ASOF_OBSERVATION" : "EXCLUDED";
    if (expected === "EXCLUDED" || c.data_status !== expected || d.classification !== expected
        || d.metrics.strict !== strict || d.metrics.near !== near) return "严格、近条件与待核分组冲突";
    if (c.qualified !== (gates.includes(false) ? false : null)
        || c.predicates.length !== 5 || c.predicates.some((p,i) => p.predicate_id !== REBOUND_IDS[i]
          || p.rule_version !== REBOUND_RULE || p.value !== [...gates,"unknown"][i])) return "反弹条件或最终收盘门禁冲突";
    if (g.amount !== "unknown") {
      const a=c.turnover_amount;
      if (!a || a.currency !== "HKD" || a.unit !== "HKD" || typeof a.value !== "number"
          || g.amount !== (a.value > 100000000 && a.value <= 200000000)) return "反弹金额门槛不一致";
    }
    const group = expected === "STRICT_ASOF_OBSERVATION" ? "strict_observation"
      : expected === "NEAR_ASOF_OBSERVATION" ? "near_observation" : "pending";
    groups[group].push(c.symbol);
  }
  for (const key of Object.keys(groups)) {
    if (!stringArray(screen[key]) || JSON.stringify(screen[key]) !== JSON.stringify(groups[key])) return "反弹分组读回不一致";
  }
  return null;
}

export function validateManagerWorkbenchResearch(
  value: unknown,
  expectedDate: string,
): string | null {
  if (!isRecord(value)) return "workbench research 响应不是对象";
  if (containsUnsafeDiagnostic(value)) return "workbench research 响应含不允许的诊断、凭证或本机路径信息";
  if (value.schema_version !== MANAGER_WORKBENCH_RESEARCH_SCHEMA) return "schema_version 不匹配";
  if (!realDate(expectedDate) || value.trade_date !== expectedDate) return "trade_date 与 exact 请求不一致";
  if (value.market !== MANAGER_WORKBENCH_MARKET) return "market 不是 HK_CONNECT";
  if (value.slot !== MANAGER_WORKBENCH_SLOT) return "slot 不是 1530";
  if (typeof value.status !== "string" || !STATUS_SET.has(value.status)) return "status 不在允许集合";
  if (value.RESEARCH_ONLY !== true) return "RESEARCH_ONLY 必须为布尔 true";
  if (value.production_allowed !== false) return "production_allowed 必须为布尔 false";
  if (value.buy_gate_updated !== false) return "buy_gate_updated 必须为布尔 false";
  if (value.orders_sent !== false) return "orders_sent 必须为布尔 false";
  if (typeof value.rule_version !== "string" || !value.rule_version.trim()) return "rule_version 缺失";
  const expectedKey = `${expectedDate}|${MANAGER_WORKBENCH_MARKET}|${MANAGER_WORKBENCH_SLOT}|${value.rule_version}`;
  if (value.cache_key !== expectedKey) return "cache_key 未绑定 date/market/slot/version";
  const requiresTime = ["READY", "READY_EMPTY", "PARTIAL", "STALE"].includes(value.status);
  if (!offsetTime(value.as_of, requiresTime)) return "as_of 不是带时区 ISO-8601";
  if (!offsetTime(value.generated_at, requiresTime)) return "generated_at 不是带时区 ISO-8601";
  if (!textOrNull(value.run_id)) return "run_id 类型错误";
  if (!stringArray(value.cannot_confirm)) return "cannot_confirm 必须为字符串数组";
  if (!(value.universe === null || sourceRef(value.universe))) return "universe 来源合同无效";
  if (!isRecord(value.coverage)) return "coverage 缺失";
  for (const field of ["eligible_count", "covered_count", "missing_count"]) {
    if (!countOrNull(value.coverage[field])) return `coverage.${field} 无效`;
  }
  if (!stringArray(value.coverage.missing_reasons)) return "coverage.missing_reasons 必须为字符串数组";
  if (typeof value.coverage.eligible_count === "number" && typeof value.coverage.covered_count === "number"
    && value.coverage.covered_count > value.coverage.eligible_count) return "covered_count 超过 eligible_count";
  if (!isRecord(value.priority_summary)) return "priority_summary 缺失";
  const prioritySummary = value.priority_summary as Record<string, unknown>;
  for (const key of ["focus", "theme_changes", "risk_upgrades"] as const) {
    const rows = prioritySummary[key];
    if (!Array.isArray(rows) || !rows.every((item) => summaryItem(item, value.as_of))) return `priority_summary.${key} 无效`;
  }
  const visible = VISIBLE_STATUSES.has(value.status);
  if (!Array.isArray(value.candidates) || !value.candidates.every((item) => candidate(item, expectedDate, value.as_of, visible))) {
    return "candidates 合同无效";
  }
  const candidates = value.candidates as ManagerWorkbenchCandidate[];
  const symbols = candidates.map((item) => item.symbol);
  if (new Set(symbols).size !== symbols.length) return "同一 market+symbol 未合并";
  const candidateIds = candidates.map((item) => item.candidate_id);
  if (new Set(candidateIds).size !== candidateIds.length) return "candidate_id 必须唯一";
  if (value.status === "READY" && candidates.length === 0) return "READY 必须含候选";
  if (value.status === "READY_EMPTY" && candidates.length !== 0) return "READY_EMPTY 不得含候选";
  if (NON_DATA_STATUSES.has(value.status)
    && (candidates.length > 0 || ["focus", "theme_changes", "risk_upgrades"].some((key) => Array.isArray(prioritySummary[key]) && prioritySummary[key].length > 0))) {
    return `${value.status} 不得含候选或 priority_summary`;
  }
  if (visible) {
    if (typeof value.run_id !== "string" || !value.run_id.trim()) return "visible data requires run_id";
    if (!completeLineage(value.universe, false)) return "visible data requires universe lineage";
  }
  for (const key of ["RESEARCH_ONLY", "production_allowed", "buy_gate_updated", "orders_sent"]) {
    if (!hasOwn(value, key)) return `${key} 缺失`;
  }
  return r2EvidenceContract(value, candidates, expectedDate) ?? reboundEvidenceContract(value, candidates);
}
