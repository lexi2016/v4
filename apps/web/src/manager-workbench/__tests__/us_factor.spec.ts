import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/vue";
import Workbench from "../Workbench.vue";
import { sampleDay, sampleStock, wrapped } from "./fixtures/sample";
import type { StockDecision } from "../types";

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
      recommendation_projection: {
        display_only: true, lane: "US_MAPPING", row_count: 3, hk_relation_row_count: 1,
        distinct_hk_count: 2, source_only_row_count: 0, count_unit: "SAVED_LANE_RESEARCH_ROWS",
        factor_stock_count: 2, factor_path_count: 1,
        coverage: { scope_count: 33, observed_count: 33, assessed_count: 33, unassessed_count: 0 }
      },
      us_mapping_summary: {
        display_only: true, plan_run_id: "synthetic-run-1", source_symbol_count: 33,
        source_row_count: 33, relation_row_count: 1, mapped_hk_count: 1,
        source_decision_counts: { CONDITIONAL_WATCH: 1 }, mixed_source_count: 0,
        coverage: { scope_count: 33, observed_count: 33, assessed_count: 33, unassessed_count: 0 },
        groups: [{ us_symbol: "DRIV", decisions: ["CONDITIONAL_WATCH"], rows: [relation] }],
        factor_summary: summary
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
    expect(screen.getByText(/保存 3 条研究记录（计数单位：研究记录）/)).toBeTruthy();
    expect(screen.getByText(/这些数量属于不同范围，不能相加/)).toBeTruthy();

    await fireEvent.click(screen.getByRole("button", { name: /查看 HK\.09660/ }));
    await screen.findByText("美股代理日收益路径 · 各路径独立判定");
    expect(screen.getByText(/公司关系观察/)).toBeTruthy();
    expect(screen.getByText("自动驾驶 · 条件观察" )).toBeTruthy();
    expect(screen.getByText(/历史有效期间未知/)).toBeTruthy();
    await fireEvent.click(screen.getByText("补充原始出处定位（不代表已接受）"));
    expect(screen.getByText("原文片段：原文位置可追溯")).toBeTruthy();
    expect(spy.mock.calls.every(([, init]) => init?.method !== "POST")).toBe(true);
  });
});
