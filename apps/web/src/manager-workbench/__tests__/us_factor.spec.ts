import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/vue";
import Workbench from "../Workbench.vue";
import { SCHEMA_VERSION } from "../types";
import type { DayData, Envelope, StockDecision } from "../types";

function sampleStock(symbol: string, name: string): StockDecision {
  return {
    market: "HK_CONNECT", symbol, name, decision: "CONDITIONAL_WATCH",
    lane_decisions: {}, reasons: [], conditions: [], invalidation_conditions: [], risks: [], evidence_ids: []
  };
}

function sampleDay(overrides: Partial<DayData>): DayData {
  return {
    snapshot: {
      context: { market: "HK_CONNECT", target_date: "20261013", phase: "RETROSPECTIVE", cutoff: null },
      run_id: "synthetic-run-1"
    },
    stocks: [], counts: null, pagination: { total: 1, offset: 0, limit: 50 },
    ...overrides
  };
}

function wrapped<T>(data: T): Envelope<T> {
  return {
    schema_version: SCHEMA_VERSION, state: "READY", data, gaps: null,
    RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false
  };
}

function response(data: unknown): Response {
  return new Response(JSON.stringify(data), { status: 200, headers: { "Content-Type": "application/json" } });
}

describe("US daily-return factor fixture", () => {
  beforeEach(() => { window.history.replaceState(null, "", "?date=20261013"); });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("shows distinct scope counts and keeps the saved relation and factor evidence in details", async () => {
    const relation = {
      symbol: "HK.09660", us_symbol: "DRIV", decision: "CONDITIONAL_WATCH",
      reason: "US_REVIEWED_RELATION_CONDITIONAL_ONLY", research_basis: "独立审核的公司关系观察",
      membership: { eligible: true }, evidence_ids: ["relation-evidence"]
    };
    const path = {
      theme: "自动驾驶", decision: "CONDITIONAL_WATCH", return_pct: "1.25",
      proxy_symbols: ["DRIV"], source_session: "20261012", statement: "已审核的暴露说明",
      review_decision: "ACCEPT", fact_effective_from: null, fact_effective_through: null,
      supplemental_evidence: [{ document_title: "行业说明", source_owner: "发布方",
        published_date: "2026-10-12", body_excerpt: "原文位置可追溯", product_available_at: "2026-10-12T10:00:00+08:00" }]
    };
    const factor = {
      symbol: "HK.09660", subtype: "US_DAILY_RETURN_FACTOR_CANDIDATE",
      decision: "CONDITIONAL_WATCH" as const, reason: "US_FACTOR_AT_LEAST_ONE_REVIEWED_POSITIVE_PATH",
      membership: { eligible: true }, evidence_ids: ["factor-evidence"], factor_paths: [path],
      conditions: ["研究效果未验证"], invalidation_conditions: [], risks: ["PIT 未验证"]
    };
    const stock: StockDecision = { ...sampleStock("HK.09660", "因子样本港股"), ...factor };
    const summary = {
      display_only: true as const, rules_version: "POSITIVE_OPERATING_RESEARCH_V1_US_DAILY_RETURN_FACTOR_V1",
      target_date: "20261013", phase: "RETROSPECTIVE" as const,
      us_source_symbol_count: 33, proxy_source_count: 24, expected_proxy_source_count: 24,
      verified_proxy_source_count: 24, unknown_proxy_source_count: 0, eligible_hk_scope_count: 692,
      unique_factor_stock_count: 1, factor_path_count: 1, unknown_factor_stock_count: 0,
      registry_fact_count: 1, factor_decision_counts: { CONDITIONAL_WATCH: 1, NOT_SELECTED: 0, UNASSESSED: 0 },
      paired_review_available: true, source_session: "20261012", historical_pit_verified: false as const,
      combined_source_and_stock_count: null as null, RESEARCH_ONLY: true, production_allowed: false,
      buy_gate_updated: false, orders_sent: false
    };
    const day = sampleDay({
      stocks: [stock],
      counts: { selected: 0, watch: 1, unassessed: 0, observation_only: 0, not_selected: 0 },
      recommendation_counts: { US_MAPPING: { selected: 0, watch: 1, unassessed: 0,
        observation_only: 0, not_selected: 0 } },
      recommendation_projection: {
        display_only: true, lane: "US_MAPPING", row_count: 3, hk_relation_row_count: 1,
        distinct_hk_count: 2, source_only_row_count: 0, count_unit: "SAVED_LANE_RESEARCH_ROWS",
        recommendation_count_unit: "DEDUPLICATED_HK_CANDIDATE_STOCKS", candidate_stock_count: 2,
        source_decision_counts: { selected: 0, watch: 1, unassessed: 1, observation_only: 0, not_selected: 1 },
        source_decision_count_unit: "SAVED_LANE_RESEARCH_ROWS",
        factor_stock_count: 2, factor_path_count: 1,
        coverage: { scope_count: 33, observed_count: 33, assessed_count: 33, unassessed_count: 0 }
      },
      us_mapping_summary: {
        display_only: true, plan_run_id: "synthetic-run-1", source_symbol_count: 33,
        source_row_count: 33, relation_row_count: 1, mapped_hk_count: 1,
        source_decision_counts: { CONDITIONAL_WATCH: 1 }, mixed_source_count: 0,
        coverage: { scope_count: 33, observed_count: 33, assessed_count: 33, unassessed_count: 0 },
        groups: [{ us_symbol: "DRIV", decisions: ["CONDITIONAL_WATCH"], rows: [relation] }],
        factor_summary: summary,
        catalog_summary: { state: "READY", stock_count: 667, relation_count: 1003,
          consumed_relation_count: 1003, displayed_relation_count: 1003 },
        run_contract: { state: "VERIFIED", mode: "MANUAL", target_hk_date: "20261020",
          us_source_session: "20261016", cutoff: "2026-10-18T14:50:00+08:00",
          contract_sha256: "a".repeat(64),
          universe: { version: "US_MAPPING_UNIVERSE_CONTRACT_V3", symbol_count: 48,
            contract_sha256: "b".repeat(64), symbols_sha256: "c".repeat(64) },
          owners: { quote: { owner: "research_peripheral.external_finance", artifact_sha256: "d".repeat(64),
              receipt_sha256: "e".repeat(64), manifest_sha256: "f".repeat(64), available_at: "2026-10-16T20:18:00+00:00" },
            connect: { source_owner: "FUTU_HKCONNECT_PLATE_MEMBERSHIP", source_date: "20261012",
              observed_symbol_count: 698, source_sha256: "1".repeat(64), source_available_at: "2026-10-12T12:05:00+00:00",
              target_eligibility: "CANNOT_CONFIRM", target_gap: "CONNECT_MEMBERSHIP_TARGET_EFFECTIVE_PERIOD_UNCONFIRMED" } } }
      }
    });
    const spy = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      if (String(input).includes("/stocks/")) {
        return response(wrapped({ recommendation_lane: "US_MAPPING", plan_run_id: "synthetic-run-1",
          stock, lane_details: [{ lane: "US_MAPPING", rows: [relation, factor], evidence_refs: [] }] }));
      }
      return response(wrapped(day));
    });
    vi.stubGlobal("fetch", spy);

    render(Workbench);
    await screen.findByText(/固定美股来源 33 个/);
    expect(screen.getByText(/因子唯一港股 1 只，路径 1 条，未知港股 0 只/)).toBeTruthy();
    expect(screen.getByText(/保存 3 条来源研究记录（计数单位：研究记录）/)).toBeTruthy();
    expect(screen.getByText(/当前保存版本没有单日映射结果/)).toBeTruthy();
    expect(screen.getByText(/美股映射来源记录分类（按行计.*待评估 1.*未入选 1/)).toBeTruthy();
    expect(screen.getByText(/这些数量属于不同范围，不能相加/)).toBeTruthy();
    expect(screen.getByText(/全量关系目录 1003 条 \/ 667 只/)).toBeTruthy();
    expect(screen.getByText(/日常输入合同 VERIFIED · 模式 MANUAL · 港股目标日 20261020 · 美股来源会话 20261016/)).toBeTruthy();
    expect(screen.getByText(/目标日资格 CANNOT_CONFIRM/)).toBeTruthy();

    await fireEvent.click(screen.getByRole("button", { name: /查看 HK\.09660/ }));
    await screen.findByText("美股代理日收益路径 · 各路径独立判定");
    expect(screen.getByText("已有审核关系，列为条件观察，不能据此严格入选。 本轮研究分类依据：独立审核的公司关系观察")).toBeTruthy();
    expect(screen.getByText("自动驾驶 · 条件观察" )).toBeTruthy();
    expect(screen.getByText(/历史有效期间未知/)).toBeTruthy();
    await fireEvent.click(screen.getByText("补充原始出处定位（不代表已接受）"));
    expect(screen.getByText("原文片段：原文位置可追溯")).toBeTruthy();
    expect(spy.mock.calls.every(([, init]) => init?.method !== "POST")).toBe(true);
  });

  it("shows the full fixed single-day mapping categories, reasons, paths, and deferred gates", async () => {
    window.history.replaceState(null, "", "?date=20261020");
    const path = (grade: "A" | "B" | "C", signed: string, relation_type: string, proxy: string) => ({
      grade, relation_type, source_industry: grade === "B" ? "半导体" : null,
      us_symbol: grade === "A" ? proxy : null, proxy_symbol: proxy, sign: 1,
      signed_return_pct: signed, status: "VERIFIED", reason: null,
      gaps: [], research_basis: "审核关系或固定行业传导依据 " + proxy
    });
    const row = (symbol: string, decision: "BENEFIT" | "RISK" | "CONFLICT" | "OBSERVATION" | "UNMAPPED" | "UNASSESSED", mapping_grade: "A" | "B" | "C" | null,
      primary_signed_return_pct: string | null, mapping_paths: ReturnType<typeof path>[], reason: string) => ({
        symbol, name: symbol + "样本", in_monthly_pool: true, decision, mapping_grade,
        primary_proxy: mapping_paths[0]?.proxy_symbol || null, primary_us_symbol: mapping_paths[0]?.us_symbol || null,
        primary_signed_return_pct, primary_status: mapping_paths[0]?.status || null,
        mapping_paths, conflict_paths: decision === "CONFLICT" ? mapping_paths.slice(1) : [],
        reason, reasons: [reason], formal_target_eligibility: "CANNOT_CONFIRM" as const
      });
    const rows = [
      row("HK.00001", "BENEFIT", "A", "1.5", [path("A", "1.5", "NAMED_TECHNOLOGY_INTEGRATION_CUSTOMER", "NVDA")], "PRIMARY_AB_SIGNED_RETURN_AT_LEAST_1_PERCENT"),
      row("HK.00002", "RISK", "B", "-1.2", [path("B", "-1.2", "FROZEN_SUBINDUSTRY", "SOXX")], "PRIMARY_AB_SIGNED_RETURN_AT_MOST_MINUS_1_PERCENT"),
      row("HK.00003", "CONFLICT", "A", "1.1", [path("A", "1.1", "NAMED_COMPONENT_OPTION", "NVDA"), path("B", "-1.3", "FROZEN_SUBINDUSTRY", "SOXX")], "FIXED_PRIMARY_AND_SECONDARY_A_B_PATHS_OPPOSE"),
      row("HK.00004", "OBSERVATION", "A", "0.4", [path("A", "0.4", "CO_DESIGNED_PRODUCT_PARTNERSHIP", "AMD")], "PRIMARY_AB_MOVE_WITHIN_PLUS_OR_MINUS_1_PERCENT"),
      row("HK.00005", "OBSERVATION", "C", null, [path("C", "0.8", "BROAD_CONSUMPTION_OBSERVATION", "XLY+XLP")], "C_MAPPING_OBSERVE_ONLY"),
      row("HK.00006", "UNMAPPED", null, null, [], "INDUSTRY_LABEL_NOT_IN_FIXED_A_B_C_MAP"),
      row("HK.00007", "UNASSESSED", "A", null, [path("A", "0.7", "NAMED_CLOUD_CONNECTIVITY_PARTNERSHIP", "VRT")], "US_QUOTE_RETURN_UNVERIFIED")
    ];
    const singleDay = {
      display_only: true as const, state: "PARTIAL", rules_version: "US_HK_SINGLE_DAY_MAPPING_V1_20261019",
      mapping_policy_version: "STRICT_US_SELECTION_MAPPING_V1_20261019", mapping_policy_sha256: "a".repeat(64),
      target_date: "20261020", price_session: "20261016", source_session: "20261016",
      monthly_observed_scope_count: 698, monthly_source_date: "20261012", monthly_source_sha256: "b".repeat(64),
      monthly_codes_sha256: "c".repeat(64), formal_target_eligibility: "CANNOT_CONFIRM" as const,
      counts: { BENEFIT: 1, RISK: 1, CONFLICT: 1, OBSERVATION: 2, SMALL_MOVE_WATCH: 1, C_WATCH: 1, UNMAPPED: 1, UNASSESSED: 1 },
      rows, outside_pool_observations: [{ symbol: "HK.09999", name: "池外样本",
        reason: "OUTSIDE_MONTHLY_RESEARCH_POOL", mapping_paths: [path("A", "1.2", "NAMED_COMPONENT_OPTION", "AMD")] }],
      benefit_rows: ["HK.00001"], risk_rows: ["HK.00002"], conflict_rows: ["HK.00003"],
      observation_rows: ["HK.00004", "HK.00005"], unmapped_rows: ["HK.00006"], unassessed_rows: ["HK.00007"],
      industry_source_status: "PARTIAL", industry_source_date: "20261012", industry_source_sha256: "d".repeat(64),
      gaps: ["SINGLE_DAY_MAPPING_ROWS_UNASSESSED"], strict_v1_status: "PAUSED_NOT_EXECUTED" as const,
      deferred_gates: ["HK_MA20", "HK_RETURN5", "HK_TURNOVER20", "TOP10", "THEME3"],
      historical_pit_verified: false as const, research_effectiveness: "UNVERIFIED" as const,
      RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false
    };
    const day = sampleDay({
      snapshot: { context: { market: "HK_CONNECT", target_date: "20261020", phase: "MANUAL",
        cutoff: "2026-10-19T03:00:00+00:00" }, run_id: "single-day-run" },
      stocks: [], counts: { selected: 0, watch: 0, unassessed: 0, observation_only: 0, not_selected: 0 },
      recommendation_counts: { US_MAPPING: { selected: 0, watch: 0, unassessed: 0,
        observation_only: 0, not_selected: 0 } },
      us_mapping_summary: {
        display_only: true, plan_run_id: "single-day-run", source_symbol_count: 33,
        source_row_count: 33, relation_row_count: 1, mapped_hk_count: 1,
        source_decision_counts: {}, mixed_source_count: 0,
        coverage: { scope_count: 33, observed_count: 33, assessed_count: 33, unassessed_count: 0 },
        groups: [], factor_summary: {
          display_only: true, rules_version: "POSITIVE_OPERATING_RESEARCH_V1_US_DAILY_RETURN_FACTOR_V1",
          target_date: "20261020", phase: "MANUAL" as const, us_source_symbol_count: 33,
          proxy_source_count: 24, expected_proxy_source_count: 24, verified_proxy_source_count: 24,
          unknown_proxy_source_count: 0, eligible_hk_scope_count: 698, unique_factor_stock_count: 0,
          factor_path_count: 0, unknown_factor_stock_count: 0, registry_fact_count: 0,
          factor_decision_counts: {}, paired_review_available: true, source_session: "20261016",
          historical_pit_verified: false as const, combined_source_and_stock_count: null as null,
          single_day_mapping: singleDay
        }
      }
    });
    vi.stubGlobal("fetch", vi.fn(async () => response(wrapped(day))));

    render(Workbench);
    await screen.findByRole("region", { name: "单日映射推荐与下跌风险" });
    expect(screen.getByRole("heading", { name: /US 20261016 → HK 20261020/ })).toBeTruthy();
    expect(screen.getByText(/全量月度观察池/)).toBeTruthy();
    expect(screen.getByText(/严格 V1 门槛暂缓，未执行/)).toBeTruthy();
    expect(screen.getByText("HK.00001 HK.00001样本 · A")).toBeTruthy();
    expect(screen.getByText(/HK.00003 HK.00003样本 · 主路径 NVDA 1.1%/)).toBeTruthy();
    const dailyCounts = screen.getByLabelText("单日映射推荐与风险分类计数");
    expect(dailyCounts.textContent).toContain("A/B 小幅观察");
    expect(dailyCounts.textContent).toContain("C 级观察");
    expect(screen.getByText(/待核 · 1 只/)).toBeTruthy();
    expect(screen.getByText(/未映射 · 1 只/)).toBeTruthy();
    expect(screen.getByText(/审核关系或固定行业传导依据 XLY\+XLP/)).toBeTruthy();
    expect(screen.getByText(/月度观察池外关系/)).toBeTruthy();
    expect(screen.getAllByText(/正式港股通资格 CANNOT_CONFIRM/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/严格精选V1结果/)).toBeNull();
  });

  it("puts the unique-stock industry funnel before candidate counts and exposes source-row counts", async () => {
    const candidate: StockDecision = {
      ...sampleStock("HK.00300", "合成美的样本"), row_id: "US_MAPPING:1",
      subtype: "HK_INDUSTRY_PROXY_FACTOR_CANDIDATE", source_industry: "家庭电器及用品",
      theme: "消费", return_pct: "1.50", mapping_type: "EXACT_PROVIDER_INDUSTRY",
      identity_status: "VERIFIED", decision: "CONDITIONAL_WATCH"
    };
    const factorSummary = {
      display_only: true as const, rules_version: "POSITIVE_OPERATING_RESEARCH_V1_US_DAILY_RETURN_FACTOR_V1",
      target_date: "20261013", phase: "RETROSPECTIVE" as const,
      us_source_symbol_count: 33, proxy_source_count: 24, expected_proxy_source_count: 24,
      verified_proxy_source_count: 24, unknown_proxy_source_count: 0, eligible_hk_scope_count: 698,
      unique_factor_stock_count: 0, factor_path_count: 0, unknown_factor_stock_count: null,
      registry_fact_count: 0, paired_review_available: true, source_session: "20261012",
      historical_pit_verified: false as const, combined_source_and_stock_count: null as null,
      RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false,
      industry_summary: {
        display_only: true as const, mapping_version: "HK_ISSUER_INDUSTRY_TO_US_PROXY_THEME_V1",
        source_status: "RETROSPECTIVE_PIT_UNKNOWN", target_date: "20261013",
        scope_count: 698, identity_resolved_count: 697, identity_gap_count: 1,
        identity_gap_symbols: ["HK.90697"], identity_gap: "HK_SECURITY_MASTER_IDENTITY_SCOPE_GAP",
        security_master_scope_count: 697, security_master_owner: "v3_shared_data",
        security_master_source_date: "20261012", security_master_available_at: "2026-10-12T17:30:15+08:00",
        security_master_artifact_sha256: "c".repeat(64), security_master_manifest_sha256: "d".repeat(64),
        bad_row_count: 0, classified_count: 2, mapping_covered_count: 1,
        industry_unmapped_count: 1, classification_missing_count: 696,
        triggered_unique_stock_count: 1, unknown_unique_stock_count: 697,
        candidate_row_count: 1,
        decision_counts: { CONDITIONAL_WATCH: 1, NOT_SELECTED: 0, UNASSESSED: 697 },
        source_asof: null, source_asof_status: "UNKNOWN", captured_at: "2026-10-14T09:30:00+08:00",
        temporal_status: "RETROSPECTIVE_PIT_UNKNOWN", historical_pit_verified: false as const
      }
    };
    const day = sampleDay({
      stocks: [candidate],
      counts: { selected: 0, watch: 1, unassessed: 0, observation_only: 0, not_selected: 0 },
      recommendation_counts: { US_MAPPING: { selected: 0, watch: 1, unassessed: 0,
        observation_only: 0, not_selected: 0 } },
      recommendation_projection: {
        display_only: true, lane: "US_MAPPING", row_count: 48, hk_relation_row_count: 1,
        distinct_hk_count: 1, source_only_row_count: 0, count_unit: "SAVED_LANE_RESEARCH_ROWS",
        recommendation_count_unit: "DEDUPLICATED_HK_CANDIDATE_STOCKS", candidate_stock_count: 1,
        source_decision_counts: { selected: 0, watch: 3, unassessed: 28, observation_only: 0, not_selected: 17 },
        source_decision_count_unit: "SAVED_LANE_RESEARCH_ROWS",
        industry_candidate_row_count: 698, industry_candidate_stock_count: 1, industry_scope_count: 698,
        coverage: { scope_count: 33, observed_count: 33, assessed_count: 33, unassessed_count: 0 }
      },
      us_mapping_summary: {
        display_only: true, plan_run_id: "synthetic-run-1", source_symbol_count: 33,
        source_row_count: 48, relation_row_count: 1, mapped_hk_count: 1, mixed_source_count: 0,
        source_decision_counts: { CONDITIONAL_WATCH: 1 },
        coverage: { scope_count: 33, observed_count: 33, assessed_count: 33, unassessed_count: 0 },
        groups: [], factor_summary: factorSummary
      }
    });
    const spy = vi.fn(async (input: RequestInfo | URL, _init: RequestInit = {}) => {
      if (String(input).includes("/stocks/")) {
        return response(wrapped({ recommendation_lane: "US_MAPPING", plan_run_id: "synthetic-run-1",
          stock: candidate, lane_details: [{ lane: "US_MAPPING", rows: [candidate], evidence_refs: [] }] }));
      }
      return response(wrapped(day));
    });
    vi.stubGlobal("fetch", spy);

    render(Workbench);
    await screen.findByRole("region", { name: "港股行业宽召回股票漏斗" });
    expect(screen.getByText(/范围 698 只；身份核验 697 只，身份缺口 1 只；有行业分类 2 只，已映射到冻结美股主题 1 只/)).toBeTruthy();
    expect(screen.getByText(/待核（UNASSESSED）697 只；.*去重候选 1 只/)).toBeTruthy();
    const funnel = screen.getByRole("region", { name: "港股行业宽召回股票漏斗" });
    const recordCounts = screen.getByLabelText("去重港股候选股票分类计数");
    expect(Boolean(funnel.compareDocumentPosition(recordCounts) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
    expect(screen.getByText(/保存 48 条来源研究记录（计数单位：研究记录）/)).toBeTruthy();
    expect(screen.getByText(/美股映射来源记录分类（按行计.*待评估 28.*未入选 17/)).toBeTruthy();
    expect(screen.getByText(/行业 家庭电器及用品 → 主题 消费；代理日收益 1\.50% · EXACT_PROVIDER_INDUSTRY/)).toBeTruthy();
    await fireEvent.click(screen.getByRole("button", { name: /查看 HK\.00300/ }));
    await screen.findByText(/来源行业 家庭电器及用品；方向路径 行业或代理映射待核；路径状态 UNASSESSED。/);
    expect(spy.mock.calls.every(([, init]) => init?.method !== "POST")).toBe(true);
  });

  it("shows full de-duplicated US_MAPPING candidate counts separately from the saved 60 source rows", async () => {
    const stockCounts = { selected: 0, watch: 153, unassessed: 437, observation_only: 0, not_selected: 111 };
    const day = sampleDay({
      counts: stockCounts,
      recommendation_counts: { US_MAPPING: stockCounts },
      us_mapping_summary: {
        display_only: true, plan_run_id: "saved-r3-run", source_symbol_count: 48,
        source_row_count: 60, relation_row_count: 36, mapped_hk_count: 19,
        source_decision_counts: {}, mixed_source_count: 0,
        coverage: { scope_count: 48, observed_count: 48, assessed_count: 22, unassessed_count: 26 },
        groups: []
      },
      recommendation_projection: {
        display_only: true, lane: "US_MAPPING", row_count: 60, hk_relation_row_count: 36,
        distinct_hk_count: 701, source_only_row_count: 24, count_unit: "SAVED_LANE_RESEARCH_ROWS",
        recommendation_count_unit: "DEDUPLICATED_HK_CANDIDATE_STOCKS", candidate_stock_count: 701,
        source_decision_counts: { selected: 0, watch: 0, unassessed: 27, observation_only: 0, not_selected: 33 },
        source_decision_count_unit: "SAVED_LANE_RESEARCH_ROWS",
        coverage: { scope_count: 48, observed_count: 48, assessed_count: 22, unassessed_count: 26 }
      }
    });
    vi.stubGlobal("fetch", vi.fn(async () => response(wrapped(day))));

    render(Workbench);

    const button = await screen.findByRole("button", { name: /严格入选 0 \/ 条件观察 153/ });
    expect(button.textContent).toContain("条件观察 153");
    expect(screen.getByText(/当前保存版本没有单日映射结果/)).toBeTruthy();
    expect(screen.getByLabelText("去重港股候选股票分类计数").textContent).toContain("153");
    expect(screen.getByText(/保存 60 条来源研究记录/)).toBeTruthy();
    const sourceSummary = screen.getByText((_, element) =>
      element?.tagName === "P" && (element.textContent || "").includes("全路径去重港股候选池共")
    );
    const sourceSummaryText = (sourceSummary.textContent || "").replace(/\s+/g, " ");
    expect(sourceSummaryText).toContain("36 条含港股关系记录，涉及 19 只港股；");
    expect(sourceSummaryText).toContain("全路径去重港股候选池共 701 只。");
    expect(screen.getByText(/来源记录分类.*待评估 27.*未入选 33/)).toBeTruthy();
  });

  it("shows full saved-lane proxy directions with negative, flat, unknown, and mixed paths separated", async () => {
    const path = (theme: string, symbols: string[], direction: string, change: string | null) => ({
      theme, proxy_symbols: symbols, direction, return_pct: change, source_session: "20261016",
      status: direction === "UNASSESSED" ? "UNASSESSED" : "VERIFIED",
      conditions: direction === "UNASSESSED" ? ["THEME_PROXY_OWNER_ROW_MISSING"] : []
    });
    const stock = sampleStock("HK.00005", "分页内样本");
    const summary = {
      display_only: true as const, plan_run_id: "directional-run", source_symbol_count: 48,
      source_row_count: 48, relation_row_count: 0, mapped_hk_count: 0, source_decision_counts: {},
      mixed_source_count: 0, coverage: { scope_count: 48, observed_count: 48, assessed_count: 48, unassessed_count: 0 },
      groups: [], factor_summary: null,
      directional_proxy_lists: {
        display_only: true as const, source_session: "20261016", monthly_observed_scope_count: 698,
        monthly_research_source_date: "20261012", formal_target_eligibility: "CANNOT_CONFIRM",
        historical_pit_verified: false as const, mixed_stock_count: 1, upside_stock_count: 1,
        downside_stock_count: 2, flat_stock_count: 1, unassessed_stock_count: 1,
        lists: {
          upside: [{ symbol: "HK.00001", name: "油服样本", source_industry: "石油及天然气",
            direction_state: "MIXED_UPSIDE_DOWNSIDE", proxy_paths: [
              path("石油", ["XLE"], "UPSIDE", "2.0"), path("天然气", ["FCG"], "DOWNSIDE", "-1.5")
            ] }],
          downside: [
            { symbol: "HK.00001", name: "油服样本", source_industry: "石油及天然气",
              direction_state: "MIXED_UPSIDE_DOWNSIDE", proxy_paths: [
                path("石油", ["XLE"], "UPSIDE", "2.0"), path("天然气", ["FCG"], "DOWNSIDE", "-1.5")
              ] },
            { symbol: "HK.00002", name: "半导体样本", source_industry: "半导体",
              direction_state: "DOWNSIDE", proxy_paths: [path("半导体", ["SOXX"], "DOWNSIDE", "-0.6")] }
          ],
          flat: [{ symbol: "HK.00003", name: "医药样本", source_industry: "药品及生物科技",
            direction_state: "FLAT", proxy_paths: [path("生物医药", ["XBI"], "FLAT", "0")] }],
          unassessed: [{ symbol: "HK.00004", name: "待核样本", source_industry: "银行",
            direction_state: "UNASSESSED", proxy_paths: [path("银行金融", ["KBE"], "UNASSESSED", null)] }]
        }
      }
    };
    const day = sampleDay({
      stocks: [stock], counts: { selected: 0, watch: 0, unassessed: 1, observation_only: 0, not_selected: 0 },
      us_mapping_summary: summary
    });
    const spy = vi.fn(async (_input: RequestInfo | URL, _init: RequestInit = {}) => response(wrapped(day)));
    vi.stubGlobal("fetch", spy);

    render(Workbench);
    const lists = await screen.findByRole("region", { name: "港股行业代理方向观察名单" });
    expect(lists.textContent).toContain("月度观察港股 × 美股收盘代理方向");
    expect(lists.textContent).toContain("月度成员来源日 20261012");
    expect(lists.textContent).toContain("目标日资格 CANNOT_CONFIRM");
    expect(lists.textContent).toContain("上行代理观察 · 已核验收益 > 0 · 1 只");
    expect(lists.textContent).toContain("HK.00001 油服样本");
    expect(lists.textContent).toContain("石油（XLE）· 20261016 收盘 +2%");
    expect(lists.textContent).toContain("天然气（FCG）· 20261016 收盘 -1.5%");
    expect(lists.textContent).toContain("HK.00002 半导体样本");
    expect(lists.textContent).toContain("下行风险观察 · 已核验收益 < 0 · 2 只");
    expect(lists.textContent).toContain("零变动代理路径 · 1 只");
    expect(lists.textContent).toContain("行业/代理/身份待核 · 1 只");
    expect(lists.textContent).toContain("缺少代理收益来源行（THEME_PROXY_OWNER_ROW_MISSING）");
    expect(lists.textContent).not.toContain("未入选代表下行");
    expect(spy.mock.calls.every(([, init]) => init?.method !== "POST")).toBe(true);
  });
});
