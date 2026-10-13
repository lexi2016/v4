/** Synthetic contract fixtures only. Not live V4 data or B-owned normative samples. */
import { SCHEMA_VERSION } from "../../types";
import type { DayData, Envelope, JobRecord, ReviewSummary, StockDecision, HistoryData, LaneResult } from "../../types";
export function wrapped<T>(data: T | null, state = "READY", statusFlags = true): Envelope<T> {
  return {
    schema_version: SCHEMA_VERSION, state, data, gaps: [],
    ...(statusFlags ? { RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false } : {})
  };
}
export function sampleStock(symbol = "HK.01234", name = "合成标的"): StockDecision {
  return {
    market: "HK_CONNECT", symbol, name, decision: "CONDITIONAL_WATCH",
    lane_decisions: {
      ANNOUNCEMENT: { decision: "UNASSESSED", reason: "完整正文待核" },
      US_MAPPING: { decision: "CONDITIONAL_WATCH", reason: "已审核映射，仅观察" },
      OVERSOLD: { decision: "NOT_SELECTED", facts: { volume_ratio: null } },
      STAGE_REFERENCE: { status: "OBSERVATION_ONLY" }
    },
    reasons: ["合成映射线索：等待实际业务证据"], conditions: ["待确认订单/关系"],
    invalidation_conditions: ["映射资格失效"], risks: ["不可作为买入建议"],
    evidence_ids: ["synthetic-evidence"], membership_status: null, available_at: "2026-10-13T09:20:00+08:00",
    changed: "新增观察"
  };
}
export function sampleLanes(): LaneResult[] {
  return [
    { lane: "ANNOUNCEMENT", state: "FAILED", coverage: {
      scope_count: null, observed_count: null, assessed_count: null, unassessed_count: null
    }, gaps: ["上游未完成"] },
    { lane: "US_MAPPING", state: "READY", coverage: {
      scope_count: 33, observed_count: 33, assessed_count: 33, unassessed_count: 0
    } },
    { lane: "OVERSOLD", state: "READY_EMPTY", coverage: {
      scope_count: 10, observed_count: 10, assessed_count: 10, unassessed_count: 0
    } },
    { lane: "STAGE_REFERENCE", state: "NOT_APPLICABLE", coverage: {
      scope_count: null, observed_count: null, assessed_count: null, unassessed_count: null
    } },
    { lane: "CLOSE_REFERENCE", state: "INPUT_MISSING", coverage: {
      scope_count: null, observed_count: null, assessed_count: null, unassessed_count: null
    } }
  ];
}
export function sampleDay(overrides: Partial<DayData> = {}): DayData {
  return {
    snapshot: {
      context: { market: "HK_CONNECT", target_date: "20261013",
        phase: "PREOPEN", cutoff: "2026-10-13T09:25:00+08:00" },
      run_id: "synthetic-run-1", generated_at: "2026-10-13T09:25:00+08:00",
      lanes: sampleLanes()
    },
    stocks: [sampleStock()],
    counts: { selected: 0, watch: 1, unassessed: null, observation_only: 0, not_selected: null },
    pagination: { total: 1, offset: 0, limit: 50 },
    versions: [{ run_id: "synthetic-run-1", phase: "PREOPEN" }],
    ...overrides
  };
}
export function sampleHistory(): HistoryData {
  return {
    date: "20261013", versions: [
      { origin: "LEGACY", original_run_id: "old-run",
        original_schema: "legacy.v1", original_sha256: "abc", verification: "CANNOT_CONFIRM",
        gaps: ["原来源缺失"] },
      { origin: "NEW", phase: "RETROSPECTIVE",
        run_id: "retro-1", generated_at: "2026-10-13T18:00:00+08:00", verification: "VERIFIED" }
    ]
  };
}
export function sampleReview(top20: ReviewSummary["top20_rows"] = Array.from({ length: 20 }, (_, i) => ({
  rank: i + 1, symbol: "HK." + String(i + 1).padStart(5, "0"),
  strict_hit: i === 0, extended_hit: i < 3, matched_lanes: i === 0 ? ["ANNOUNCEMENT" as const] : [],
  missed_reason: i === 0 ? null : "未进入合成名单"
}))): ReviewSummary {
  return {
    target_date: "20261013", plan_run_id: "synthetic-run-1", ranking_date: "20261013",
    evaluation_scope_ref: "synthetic-top20", top20_rows: top20,
    strict_coverage: { covered: 1, denominator: 20, ratio: 0.05 },
    extended_coverage: { covered: 3, denominator: 20, ratio: 0.15 },
    selected_denominator: 1, lane_incremental_coverage: { ANNOUNCEMENT: 1 },
    uncovered_reasons: ["no_evidence:17"]
  };
}
export function sampleJob(state: JobRecord["state"] = "FAILED"): JobRecord {
  return {
    job_id: "synthetic-job-1", run_id: "synthetic-run-2",
    context: { market: "HK_CONNECT", target_date: "20261013", phase: "MANUAL",
      cutoff: "2026-10-13T10:00:00+08:00" },
    state, completed_count: 1, total_count: null, retryable: state === "FAILED",
    failure_code: state === "FAILED" ? "UPSTREAM_MISSING" : null
  };
}
