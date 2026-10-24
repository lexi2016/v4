import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/vue";
import Workbench from "../Workbench.vue";
import { createWorkbenchApi } from "../api";
import { SCHEMA_VERSION } from "../types";
import type { USMappingCompactStock, USMappingMappingPath } from "../types";

const identity = {
  schema_version: "v4.us_hk.selection.v1" as const,
  policy_sha256: "a".repeat(64),
  engine_identity: "us-mapping-engine-fixture-v1"
};
function response(data: unknown, state = "READY"): Response {
  return new Response(JSON.stringify({ schema_version: SCHEMA_VERSION, state, data, gaps: [],
    RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false }),
  { status: 200, headers: { "Content-Type": "application/json" } });
}
function compactStock(index: number, patch: Partial<USMappingCompactStock> = {}): USMappingCompactStock {
  const states: Pick<USMappingCompactStock, "research_state" | "direction" | "strict_state" | "decision" | "qualified">[] = [
    { research_state: "current_supported", direction: "POSITIVE", strict_state: "PASS", decision: "SELECTED", qualified: true },
    { research_state: "pending", direction: "CONFLICT", strict_state: "PENDING", decision: "PENDING", qualified: false },
    { research_state: "dated_weak", direction: "NEGATIVE", strict_state: "REJECT", decision: "REJECTED", qualified: false },
    { research_state: "current_supported", direction: "POSITIVE", strict_state: "PASS", decision: "QUALIFIED_NOT_SELECTED", qualified: true }
  ];
  return {
    symbol: `HK.${String(index).padStart(5, "0")}`, name: `候选${index}`,
    ...states[(index - 1) % states.length],
    primary_path_id: `PATH-${index}`, rank: index === 1 ? 1 : null,
    reasons: index === 4 ? ["QUALIFIED_BUT_TOP10_CAP"] : [`COMPACT_REASON_${index}`],
    gates: [{ gate: "history", state: states[(index - 1) % states.length].strict_state,
      reasons: [`GATE_REASON_${index}`] }],
    path_count: 2,
    source_refs: [{ owner: "fixture-owner", ref: `source-${index}`, sha256: "b".repeat(64) }],
    ...patch
  };
}
function compactData(runId = "run-old", targetDate = "20261023", offset = 0) {
  const stocks = offset === 0 ? [compactStock(1), compactStock(2), compactStock(3), compactStock(4)] : [compactStock(5)];
  return {
    snapshot: { run_id: runId, target_date: targetDate, phase: "NEXT_DAY", product_sha256: "c".repeat(64),
      cutoff: `${targetDate.slice(0, 4)}-${targetDate.slice(4, 6)}-${targetDate.slice(6, 8)}T09:25:00+08:00`,
      source_sessions: { us_quote: "20261022", hk_price: "20261022" } },
    stocks,
    counts: { candidate_count: 317, current_supported: 100, dated_weak: 20, pending_research: 30,
      selected: 10, qualified_not_selected: 4, rejected: 50, pending: 60 },
    pagination: { total: 317, offset, limit: 50 },
    selection_identity: identity,
    versions: [
      { run_id: runId, phase: "NEXT_DAY", target_date: targetDate },
      { run_id: "run-new", phase: "NEXT_DAY", target_date: targetDate }
    ],
    lane_sources: { source_session: "20261022", cutoff: "fixture-cutoff" }
  };
}
function legacyCompactData() {
  const symbols = ["HK.00992", "HK.01211", "HK.01810", "HK.02015", "HK.09868"];
  const benefitRows = symbols.map((symbol, index) => ({
    symbol, name: `历史受益${index + 1}`, decision: "BENEFIT", mapping_grade: "A",
    primary_proxy: "NVDA", primary_us_symbol: "NVDA", primary_relation_type: "NAMED_COMPONENT_OPTION",
    primary_signed_return_pct: "1.25", reason: "SAVED_BENEFIT", reasons: ["SAVED_BENEFIT"],
    formal_target_eligibility: "CANNOT_CONFIRM", row_id: `US_MAPPING:${1063 + index}`,
    recommendation_lane: "US_MAPPING", display_only: true,
    mapping_paths: [{ grade: "A", us_symbol: "NVDA", proxy_symbol: "NVDA", relation_type: "NAMED_COMPONENT_OPTION",
      status: "PASS", reason: "SAVED_PATH", signed_return_pct: "1.25", source_sha256: "a".repeat(64), source_session: "20261022" }]
  }));
  const oldCounts = { selected: 2, watch: 3, unassessed: 4, observation_only: 1, not_selected: 5 };
  return {
    snapshot: { run_id: "legacy-compact-run", target_date: "20261023", phase: "NEXT_DAY", cutoff: null,
      source_sessions: { us_quote: "20261022", hk_price: "20261022" } },
    stocks: [{ market: "HK_CONNECT", symbol: symbols[0], name: "历史受益1", decision: "CONDITIONAL_WATCH",
      lane_decisions: {}, reasons: ["SAVED_BENEFIT"], conditions: [], invalidation_conditions: [], risks: [], evidence_ids: [],
      row_id: "US_MAPPING:1063", recommendation_lane: "US_MAPPING", display_only: true }],
    counts: oldCounts, recommendation_counts: { US_MAPPING: oldCounts },
    pagination: { total: 1, offset: 0, limit: 50 }, selection_identity: null, legacy: true,
    us_mapping_summary: {
      display_only: true, plan_run_id: "legacy-compact-run", source_symbol_count: 20, source_row_count: 20,
      relation_row_count: 5, mapped_hk_count: 5,
      source_decision_counts: { SELECTED: 2, CONDITIONAL_WATCH: 3, NOT_SELECTED: 5, UNASSESSED: 4 },
      mixed_source_count: 0, coverage: { scope_count: 5, observed_count: 5, assessed_count: 5, unassessed_count: 0 }, groups: [],
      factor_summary: {
        display_only: true, rules_version: "legacy-factor-v1", target_date: "20261023", phase: "NEXT_DAY",
        us_source_symbol_count: 20, proxy_source_count: 5, expected_proxy_source_count: 5, verified_proxy_source_count: 5,
        unknown_proxy_source_count: 0, eligible_hk_scope_count: 698, unique_factor_stock_count: 5, factor_path_count: 5,
        unknown_factor_stock_count: 0, registry_fact_count: 5, factor_decision_counts: {}, paired_review_available: false,
        source_session: "20261022", historical_pit_verified: false, combined_source_and_stock_count: null,
        single_day_mapping: {
          display_only: true, state: "SAVED_LEGACY", rules_version: "legacy-factor-v1",
          mapping_policy_version: "fixed-mapping-v1", mapping_policy_sha256: "b".repeat(64), target_date: "20261023",
          price_session: "20261023", source_session: "20261022", monthly_observed_scope_count: 698,
          formal_target_eligibility: "CANNOT_CONFIRM",
          counts: { BENEFIT: 5, RISK: 0, CONFLICT: 0, OBSERVATION: 0, UNMAPPED: 0, UNASSESSED: 0, SMALL_MOVE_WATCH: 0, C_WATCH: 0 },
          rows: benefitRows, benefit_rows: benefitRows, risk_rows: [], conflict_rows: [], observation_rows: [],
          unmapped_rows: [], unassessed_rows: [], outside_pool_observations: [], gaps: [], strict_v1_status: "PAUSED_NOT_EXECUTED",
          deferred_gates: [], historical_pit_verified: false, research_effectiveness: "UNVERIFIED"
        }
      }
    }
  };
}
// Portable short-wire fixture: synthetic values, no archive-only fields.
function shortLegacyCompactData() {
  const full = legacyCompactData();
  const saved = full.us_mapping_summary.factor_summary.single_day_mapping;
  const rows = saved.rows.map((row, index) => ({ ...row, row_id: `US_MAPPING:${[0, 24, 23, 25, 22][index]}` }));
  return {
    ...full, stocks: [], pagination: { total: 0, offset: 0, limit: 50 },
    us_mapping_summary: {
      groups: [], display_only: true, gaps: [],
      factor_summary: {
        single_day_mapping: {
          state: saved.state, rules_version: saved.rules_version,
          mapping_policy_version: saved.mapping_policy_version, mapping_policy_sha256: saved.mapping_policy_sha256,
          target_date: saved.target_date, source_session: saved.source_session, price_session: saved.price_session,
          monthly_observed_scope_count: saved.monthly_observed_scope_count,
          formal_target_eligibility: saved.formal_target_eligibility, historical_pit_verified: false,
          strict_v1_status: saved.strict_v1_status, counts: saved.counts, gaps: [],
          rows, benefit_rows: rows, risk_rows: [], pagination: { total: 5, offset: 0, limit: 50 }, display_only: true
        }
      }
    }
  };
}
function legacyStockDetails() {
  return {
    recommendation_lane: "US_MAPPING", plan_run_id: "legacy-compact-run",
    stock: { market: "HK_CONNECT", symbol: "HK.00992", name: "历史受益1", decision: "CONDITIONAL_WATCH",
      lane_decisions: {}, reasons: ["SAVED_BENEFIT"], conditions: [], invalidation_conditions: [], risks: [], evidence_ids: [],
      row_id: "US_MAPPING:1063", recommendation_lane: "US_MAPPING", display_only: true },
    lane_details: [{ lane: "US_MAPPING", rows: [{ row_id: "US_MAPPING:1063", symbol: "HK.00992", decision: "CONDITIONAL_WATCH" }], evidence_refs: [] }]
  };
}
function fullPath(index: number): USMappingMappingPath {
  return {
    path_id: `PATH-${index}`, symbol: "HK.00001", us_symbol: "NVDA", relation_type: "NAMED_COMPONENT_OPTION",
    role: "INDIVIDUAL", scope: "current_supported", status: "PASS", direction: "POSITIVE",
    strict_supported: true, primary_theme: "AI_NETWORKING", return_pct: "1.25", source_session: "20261022",
    available_at: "2026-10-22T16:05:00-04:00", source_refs: [{ owner: "fixture-owner", ref: `path-${index}`, sha256: "d".repeat(64) }],
    evidence_ids: [`evidence-${index}`], reasons: [`PATH_REASON_${index}`]
  };
}
function diagnosticData(runId: string, targetDate: string, offset: number) {
  const pageIndexes = offset === 0 ? Array.from({ length: 50 }, (_, index) => index + 1) : [51];
  return {
    snapshot: { run_id: runId, target_date: targetDate, phase: "NEXT_DAY", product_sha256: "c".repeat(64),
      cutoff: `${targetDate.slice(0, 4)}-${targetDate.slice(4, 6)}-${targetDate.slice(6, 8)}T09:25:00+08:00`,
      source_sessions: { us_quote: "20261022", hk_price: "20261022" } },
    selection_identity: identity,
    counts: { candidate_count: 317, current_supported: 100, dated_weak: 20, pending_research: 30,
      selected: 10, qualified_not_selected: 4, rejected: 50, pending: 60 },
    pagination: { total: 1, offset: 0, limit: 1 },
    stocks: [{
      symbol: "HK.00001",
      candidate: { symbol: "HK.00001", name: "候选1", research_state: "current_supported", direction: "POSITIVE",
        primary_path_id: "PATH-1", paths: [fullPath(1)], reasons: ["FULL_CANDIDATE_REASON"],
        source_refs: [{ owner: "fixture-owner", ref: "full-source", sha256: "e".repeat(64) }] },
      strict: { symbol: "HK.00001", state: "PASS", decision: "SELECTED", qualified: true, rank: 1,
        primary_path_id: "PATH-1", primary_theme: "AI_NETWORKING", primary_return_pct: "1.25",
        gates: [{ gate: "history", state: "PASS", actual: 21, threshold: 21, reasons: ["FULL_GATE_REASON"], source_refs: [] }],
        metrics: { turnover20: "known" }, reasons: ["FULL_STRICT_REASON"], evidence_ids: ["evidence-1"] },
      relationships: pageIndexes.map(fullPath),
      relationship_pagination: { total: 51, offset, limit: 50 }
    }],
    lane_sources: { source_session: "20261022" }
  };
}
function install(handler: (url: URL, init: RequestInit) => Promise<Response> | Response) {
  const spy = vi.fn((input: RequestInfo | URL, init: RequestInit = {}) => handler(new URL(String(input), window.location.origin), init));
  vi.stubGlobal("fetch", spy);
  return spy;
}
function requestedUrls(spy: ReturnType<typeof install>): URL[] {
  return spy.mock.calls.map(([input]) => new URL(String(input), window.location.origin));
}

describe("US_MAPPING compact persisted results", () => {
  beforeEach(() => { window.history.replaceState(null, "", "?date=20261023&phase=NEXT_DAY&run_id=run-old"); });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("defaults to evidenced industry peers despite strict rejection or pending eligibility", async () => {
    const data = { ...compactData(), listing_mode: "INDUSTRY_MATCH",
      listing_policy_version: "US_HK_INDUSTRY_LISTING_V1_20261024", listing_policy_sha256: "d".repeat(64),
      counts: { ...compactData().counts, industry_match_count: 317 },
      stocks: [compactStock(3, { industry_matches: [{ us_symbol: "AMD", industry: "半导体制造",
        segment: "晶圆制造", association: "BUSINESS_PEER", role: "INDIVIDUAL", relation_id: "R003",
        return_pct: "-0.5", source_session: "20261022", current_applicability: "DATED_SCOPE_ONLY",
        warnings: ["CURRENT_APPLICABILITY_UNVERIFIED", "HISTORICAL_PIT_UNVERIFIED"],
        source_refs: [{ owner: "saved_catalog", ref: "R003", sha256: "b".repeat(64) }] }] }),
        compactStock(2, { industry_matches: [{ us_symbol: "SOXX", industry: "半导体制造", segment: "半导体",
          association: "CLASSIFIED_INDUSTRY_PROXY", role: "SECTOR_CONTEXT", relation_id: null,
          return_pct: null, source_session: "20261022", current_applicability: null,
          warnings: ["PROXY_CONTEXT_NOT_COMPANY_TRANSMISSION"], source_refs: [{ owner: "saved_classification", sha256: "c".repeat(64) }] }] })] };
    const spy = install(url => {
      if (url.searchParams.get("view") !== "diagnostics") return response(data);
      const diagnostic = diagnosticData("run-old", "20261023", 0);
      diagnostic.stocks[0].symbol = url.searchParams.get("symbol") || "";
      return response(diagnostic);
    });
    render(Workbench);
    const table = await screen.findByRole("table", { name: "同行业港股名单" });
    expect(within(table).getByText("HK.00003")).toBeTruthy();
    expect(within(table).getByText("HK.00002")).toBeTruthy();
    expect(within(table).getByText(/AMD/)).toBeTruthy();
    expect(within(table).getByText(/SOXX/)).toBeTruthy();
    expect(within(table).getByText(/ETF\/行业背景/)).toBeTruthy();
    expect(screen.getByText(/只按已保存的同行业依据列出/)).toBeTruthy();
    expect(screen.getByText(/历史适用性与 PIT 未验证/)).toBeTruthy();
    expect(screen.queryByText("GATE_REASON_3")).toBeNull();
    expect(requestedUrls(spy)[0].searchParams.get("view")).toBe("compact");
    await fireEvent.click(within(table).getAllByRole("button", { name: "查看完整诊断" })[0]);
    await screen.findByText(/FULL_STRICT_REASON/);
  });

  it("normalizes the compact envelope without changing saved stock order or full counts", async () => {
    const transport = vi.fn(async () => response(compactData())) as unknown as typeof fetch;
    const result = await createWorkbenchApi(transport).getRecommendations({ date: "20261023", lane: "US_MAPPING" });
    expect(new URL((transport as ReturnType<typeof vi.fn>).mock.calls[0][0] as string, "http://localhost").searchParams.get("view")).toBe("compact");
    expect(result.data?.us_mapping_selection?.stocks.map(stock => stock.symbol)).toEqual([
      "HK.00001", "HK.00002", "HK.00003", "HK.00004"
    ]);
    expect(result.data?.us_mapping_selection?.counts.candidate_count).toBe(317);
    expect(result.data?.snapshot?.context.target_date).toBe("20261023");
  });

  it("requests compact by default, preserves backend order/full counts, and pages diagnostics on demand in the same run", async () => {
    const spy = install(url => {
      if (url.searchParams.get("view") === "diagnostics") {
        return response(diagnosticData(url.searchParams.get("run_id") || "", url.pathname.split("/")[5],
          Number(url.searchParams.get("relationship_offset") || 0)));
      }
      return response(compactData(url.searchParams.get("run_id") || "run-old", url.pathname.split("/")[5],
        Number(url.searchParams.get("offset") || 0)));
    });
    render(Workbench);
    const table = await screen.findByRole("table", { name: "后端保存的 US_MAPPING 候选与严格状态" });
    const rows = within(table).getAllByRole("row");
    expect(rows.slice(1).map(row => within(row).getAllByRole("cell")[0].textContent?.match(/HK\.\d+/)?.[0]))
      .toEqual(["HK.00001", "HK.00002", "HK.00003", "HK.00004"]);
    expect(screen.getByText("严格筛选入选")).toBeTruthy();
    expect(screen.getByText("严格条件待核")).toBeTruthy();
    expect(screen.getByText("严格筛选拒绝")).toBeTruthy();
    expect(screen.getByText("严格合格，未进入限额名单")).toBeTruthy();
    expect(screen.getByText("QUALIFIED_BUT_TOP10_CAP")).toBeTruthy();
    expect(screen.getAllByText("317").length).toBeGreaterThan(0);
    expect(requestedUrls(spy)[0].searchParams.get("view")).toBe("compact");
    expect(requestedUrls(spy)[0].searchParams.get("limit")).toBe("50");
    expect(spy).toHaveBeenCalledTimes(1);

    await fireEvent.click(within(rows[1]).getByRole("button", { name: "查看完整诊断" }));
    await screen.findByText(/FULL_CANDIDATE_REASON/);
    expect(screen.getByText(/FULL_STRICT_REASON/)).toBeTruthy();
    await screen.findByText(/^PATH_REASON_1 ·/);
    const diagnosticsCalls = requestedUrls(spy).filter(url => url.searchParams.get("view") === "diagnostics");
    expect(diagnosticsCalls[0].searchParams.get("run_id")).toBe("run-old");
    expect(diagnosticsCalls[0].searchParams.get("symbol")).toBe("HK.00001");
    expect(diagnosticsCalls[0].searchParams.get("relationship_offset")).toBe("0");

    await fireEvent.click(screen.getByRole("button", { name: "下一页关系" }));
    await screen.findByText(/PATH_REASON_51/);
    const afterRelationshipPage = requestedUrls(spy).filter(url => url.searchParams.get("view") === "diagnostics");
    expect(afterRelationshipPage[1].searchParams.get("relationship_offset")).toBe("50");
    expect(afterRelationshipPage[1].searchParams.get("run_id")).toBe("run-old");

    await fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    await screen.findByText("候选5");
    const compactCalls = requestedUrls(spy).filter(url => url.searchParams.get("view") === "compact");
    expect(compactCalls[1].searchParams.get("offset")).toBe("50");
    expect(screen.getByText("317")).toBeTruthy();
  });

  it("does not show the legacy unknown-count warning beside canonical full selection counts", async () => {
    install(() => response(compactData()));
    render(Workbench);
    await screen.findByText("候选1");
    expect(screen.getByText("317")).toBeTruthy();
    expect(screen.queryByText("完整分类计数未知（无已保存计数，不能当作 0）。")).toBeNull();
  });

  it("ignores a late diagnostics response after phase/run navigation", async () => {
    let releaseDiagnostics: ((value: Response) => void) | undefined;
    const spy = install(url => {
      if (url.searchParams.get("view") === "diagnostics") {
        return new Promise<Response>(resolve => { releaseDiagnostics = resolve; });
      }
      const runId = url.searchParams.get("run_id") || "run-old";
      return response(compactData(runId, "20261023", 0));
    });
    render(Workbench);
    await screen.findByText("候选1");
    await fireEvent.click(screen.getAllByRole("button", { name: "查看完整诊断" })[0]);
    await waitFor(() => expect(releaseDiagnostics).toBeTypeOf("function"));
    await fireEvent.update(screen.getByLabelText("计划版本"), "run-new");
    await waitFor(() => expect(requestedUrls(spy).some(url => url.searchParams.get("run_id") === "run-new")).toBe(true));
    await screen.findByText("候选1");
    await screen.findByText("run-new");
    releaseDiagnostics?.(response(diagnosticData("run-old", "20261023", 0)));
    await waitFor(() => expect(screen.queryByText("FULL_CANDIDATE_REASON")).toBeNull());
    expect(screen.getByText("run-new")).toBeTruthy();
    expect(requestedUrls(spy).some(url => url.searchParams.get("run_id") === "run-new")).toBe(true);
  });

  it("ignores a late diagnostics response after date navigation", async () => {
    let releaseDiagnostics: ((value: Response) => void) | undefined;
    const spy = install(url => {
      if (url.searchParams.get("view") === "diagnostics") {
        return new Promise<Response>(resolve => { releaseDiagnostics = resolve; });
      }
      const date = url.pathname.split("/")[5];
      const runId = date === "20261024" ? "run-new-date" : "run-old";
      return response(compactData(runId, date, 0));
    });
    render(Workbench);
    await screen.findByText("候选1");
    await fireEvent.click(screen.getAllByRole("button", { name: "查看完整诊断" })[0]);
    await waitFor(() => expect(releaseDiagnostics).toBeTypeOf("function"));
    const targetDate = screen.getByLabelText("目标港股日") as HTMLInputElement;
    targetDate.value = "2026-10-24";
    await fireEvent.change(targetDate);
    await waitFor(() => expect(requestedUrls(spy).some(url => url.pathname.includes("/days/20261024/"))).toBe(true));
    await screen.findByText("20261024");
    releaseDiagnostics?.(response(diagnosticData("run-old", "20261023", 0)));
    await waitFor(() => expect(screen.queryByText("FULL_CANDIDATE_REASON")).toBeNull());
    await screen.findByText("候选1");
    expect(requestedUrls(spy).some(url => url.pathname.includes("/days/20261024/"))).toBe(true);
  });

  it("keeps old saved runs readable as historical and does not add strict states", async () => {
    const oldData = {
      snapshot: { run_id: "legacy-run", target_date: "20261023", phase: "NEXT_DAY", cutoff: null },
      stocks: [{ market: "HK_CONNECT", symbol: "HK.00077", name: "历史保存标的", decision: "CONDITIONAL_WATCH",
        lane_decisions: {}, reasons: ["LEGACY_REASON"], conditions: [], invalidation_conditions: [], risks: [], evidence_ids: [] }],
      counts: { selected: 0, watch: 1, unassessed: 0, observation_only: 0, not_selected: 0 },
      pagination: { total: 1, offset: 0, limit: 50 }, selection_identity: null, legacy: true
    };
    install(() => response(oldData));
    window.history.replaceState(null, "", "?date=20261023&phase=NEXT_DAY&run_id=legacy-run");
    render(Workbench);
    await screen.findByText("历史保存标的");
    expect(screen.getByText(/历史保存版 · selection_identity 为空/)).toBeTruthy();
    expect(screen.queryByText(/严格条件待核|严格筛选拒绝|严格筛选入选/)).toBeNull();
  });

  it("keeps the full legacy summary and stock-table details readable", async () => {
    const spy = install(url => url.pathname.includes("/stocks/")
      ? response(legacyStockDetails()) : response(legacyCompactData()));
    window.history.replaceState(null, "", "?date=20261023&phase=NEXT_DAY&run_id=legacy-compact-run");
    render(Workbench);

    expect(await screen.findByText(/历史保存版 · selection_identity 为空/)).toBeTruthy();
    expect(screen.getByRole("heading", { name: /SAVED_LEGACY/ })).toBeTruthy();
    expect(screen.getByText(/US 来源会话 20261022.*HK 行情信号会话 20261023.*HK 目标日 20261023/)).toBeTruthy();
    const benefits = screen.getByLabelText("当前版本潜在受益观察名单");
    for (const symbol of ["HK.00992", "HK.01211", "HK.01810", "HK.02015", "HK.09868"]) {
      expect(within(benefits).getByText(new RegExp(symbol))).toBeTruthy();
    }
    expect(screen.getByText("HK.00992 历史受益1")).toBeTruthy();
    expect(screen.getByText(/正式入选 2 只/)).toBeTruthy();
    expect(screen.getByText("旧版美股映射汇总与关系档案")).toBeTruthy();
    expect(screen.getByText(/按美股来源标的计：严格入选 2/)).toBeTruthy();
    expect(within(benefits).getAllByText(/SAVED_PATH/)).toHaveLength(5);
    expect(screen.getByText("固定映射受益判定").parentElement?.textContent).toContain("5");
    expect(screen.getByText("固定映射风险判定").parentElement?.textContent).toContain("0");
    expect(screen.queryByText(/严格筛选入选|严格条件待核|严格筛选拒绝/)).toBeNull();

    await fireEvent.click(within(document.querySelector(".mwb-stock-table") as HTMLElement).getByRole("button", { name: "查看 HK.00992 历史受益1 详情" }));
    await screen.findByText(/个股研究详情/);
    const detailUrl = requestedUrls(spy).find(url => url.pathname.includes("/stocks/"));
    expect(detailUrl?.searchParams.get("date")).toBe("20261023");
    expect(detailUrl?.searchParams.get("run_id")).toBe("legacy-compact-run");
    expect(detailUrl?.searchParams.get("lane")).toBe("US_MAPPING");
    expect(detailUrl?.searchParams.get("row_id")).toBe("US_MAPPING:1063");
  });

  it("renders short legacy compact data without archive fields and opens saved benefit details", async () => {
    const data = shortLegacyCompactData();
    const errors: unknown[] = [];
    const spy = install(url => url.pathname.includes("/stocks/")
      ? response({ ...legacyStockDetails(), stock: { ...legacyStockDetails().stock, row_id: "US_MAPPING:0" } })
      : response(data));
    window.history.replaceState(null, "", "?date=20261023&phase=NEXT_DAY&run_id=legacy-compact-run");
    render(Workbench, { global: { config: { errorHandler: error => { errors.push(error); } } } });
    const benefits = await screen.findByLabelText("当前版本潜在受益观察名单");
    expect(errors).toEqual([]);
    expect(within(benefits).getByRole("heading", { name: "潜在受益观察 · 5 只" })).toBeTruthy();
    for (const symbol of ["HK.00992", "HK.01211", "HK.01810", "HK.02015", "HK.09868"]) {
      expect(within(benefits).getByText(new RegExp(symbol))).toBeTruthy();
    }
    expect(screen.getByRole("heading", { name: "下跌风险观察 · 0 只" })).toBeTruthy();
    expect(screen.queryByText("旧版美股映射汇总与关系档案")).toBeNull();
    expect(screen.queryByText(/按美股来源标的计|固定美股来源/)).toBeNull();
    expect(screen.queryByText(/严格筛选入选|严格条件待核|严格筛选拒绝/)).toBeNull();
    await fireEvent.click(within(benefits).getByRole("button", { name: "查看 HK.00992 历史受益1 详情" }));
    await screen.findByText(/个股研究详情/);
    const detailUrl = requestedUrls(spy).find(url => url.pathname.includes("/stocks/"));
    expect(detailUrl?.searchParams.get("date")).toBe("20261023");
    expect(detailUrl?.searchParams.get("run_id")).toBe("legacy-compact-run");
    expect(detailUrl?.searchParams.get("lane")).toBe("US_MAPPING");
    expect(detailUrl?.searchParams.get("row_id")).toBe("US_MAPPING:0");
    expect(errors).toEqual([]);
  });

  it.each(["missing row", "missing lane"])("disables short saved-card details for %s without guessing identity", async missing => {
    const data = shortLegacyCompactData();
    const first = data.us_mapping_summary.factor_summary.single_day_mapping.rows[0];
    if (missing === "missing row") first.row_id = "";
    else first.recommendation_lane = "";
    const spy = install(() => response(data));
    window.history.replaceState(null, "", "?date=20261023&phase=NEXT_DAY&run_id=legacy-compact-run");
    render(Workbench);
    const benefits = await screen.findByLabelText("当前版本潜在受益观察名单");
    const button = within(benefits).getByRole("button", { name: "查看 HK.00992 历史受益1 详情" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    expect(within(benefits).getByText("保存版本缺少可用详情身份，详情不可用。")).toBeTruthy();
    await fireEvent.click(button);
    expect(requestedUrls(spy).filter(url => url.pathname.includes("/stocks/"))).toEqual([]);
  });

  it("requires the explicit diagnostics method to send a bounded same-run query", async () => {
    const transport = vi.fn(async () => response(diagnosticData("run-old", "20261023", 0))) as unknown as typeof fetch;
    const api = createWorkbenchApi(transport);
    await api.getUSMappingDiagnostics({ date: "20261023", phase: "NEXT_DAY", run_id: "run-old",
      symbol: "HK.00001", relationship_offset: 50, relationship_limit: 50 });
    const url = new URL((transport as ReturnType<typeof vi.fn>).mock.calls[0][0] as string, "http://localhost");
    expect(url.searchParams.get("view")).toBe("diagnostics");
    expect(url.searchParams.get("run_id")).toBe("run-old");
    expect(url.searchParams.get("symbol")).toBe("HK.00001");
    expect(url.searchParams.get("relationship_offset")).toBe("50");
    expect(url.searchParams.get("relationship_limit")).toBe("50");
  });
});
