import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/vue";
import Workbench from "../Workbench.vue";
import { readableReason, researchCutoff, researchSections } from "../display";
import { SCHEMA_VERSION } from "../types";

function response(data: unknown): Response {
  return new Response(JSON.stringify({
    schema_version: SCHEMA_VERSION, state: "READY", data,
    RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false,
  }), { status: 200, headers: { "Content-Type": "application/json" } });
}

describe("saved daily US mapping uncertainty", () => {
  beforeEach(() => { window.history.replaceState(null, "", "?date=20261020"); });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("renders the saved reason and basis without inventing empty conditions", () => {
    const row = {
      reason: "US_SESSION_RELATION_OR_CONNECT_UNVERIFIED",
      research_basis: "Lenovo describes ThinkCentre AI PCs powered by AMD Ryzen AI processors.",
      conditions: [],
    };

    expect(readableReason(row)).toBe(
      "美股来源、港股关系或互联互通资格尚未核验，保留待核。 本轮研究分类依据：Lenovo describes ThinkCentre AI PCs powered by AMD Ryzen AI processors.",
    );
    expect(researchSections(row).find((section) => section.key === "confirmation_conditions")?.items).toEqual([]);
  });

  it("shows the admission cutoff and falls back for older snapshots", () => {
    expect(researchCutoff({
      cutoff: "2026-10-18T16:32:18.273364+08:00",
      scope_refs: { source_cutoff: "2026-10-18T16:31:51.391447+08:00" },
    })).toBe("2026-10-18T16:31:51.391447+08:00");
    expect(researchCutoff({ cutoff: "2026-10-12T09:00:00+08:00", scope_refs: {} }))
      .toBe("2026-10-12T09:00:00+08:00");
  });

  it("keeps candidate counts, catalog counts, and the daily input contract distinct", async () => {
    const cutoff = "2026-10-18T16:31:51.391447+08:00";
    const completion = "2026-10-18T16:32:18.273364+08:00";
    const day = {
      snapshot: { run_id: "daily-run", context: { target_date: "20261020", phase: "MANUAL",
        cutoff: completion, scope_refs: { source_cutoff: cutoff } } },
      stocks: [], counts: { selected: 0, watch: 0, unassessed: 19, observation_only: 0, not_selected: 0 },
      pagination: { total: 0, offset: 0, limit: 50 },
      recommendation_projection: { display_only: true, lane: "US_MAPPING", row_count: 60,
        hk_relation_row_count: 36, distinct_hk_count: 19, source_only_row_count: 24,
        coverage: { scope_count: 48, observed_count: 48, assessed_count: 0, unassessed_count: 48 } },
      us_mapping_summary: { display_only: true, plan_run_id: "daily-run", source_symbol_count: 48,
        source_row_count: 60, relation_row_count: 36, mapped_hk_count: 19,
        source_decision_counts: { UNASSESSED: 60 }, mixed_source_count: 0,
        coverage: { scope_count: 48, observed_count: 48, assessed_count: 0, unassessed_count: 48 },
        groups: [],
        catalog_summary: { state: "READY", stock_count: 667, relation_count: 1003, displayed_relation_count: 1003 },
        run_contract: { state: "VERIFIED", mode: "MANUAL", target_hk_date: "20261020",
          us_source_session: "20261016", cutoff, gaps: ["CONNECT_MEMBERSHIP_TARGET_EFFECTIVE_PERIOD_UNCONFIRMED"],
          universe: { version: "US_MAPPING_UNIVERSE_CONTRACT_V3", symbol_count: 48, contract_sha256: "universe-sha" },
          owners: { quote: { owner: "research_peripheral.external_finance", available_at: "2026-10-17T15:35:31Z",
              artifact_sha256: "quote-sha" },
            connect: { source_owner: "FUTU_HKCONNECT_PLATE_MEMBERSHIP", source_date: "20261012",
              observed_symbol_count: 698, target_eligibility: "CANNOT_CONFIRM",
              target_gap: "CONNECT_MEMBERSHIP_TARGET_EFFECTIVE_PERIOD_UNCONFIRMED" } } } },
    };
    vi.stubGlobal("fetch", vi.fn(async () => response(day)));

    render(Workbench);
    await screen.findByText(/候选来源记录 60 条/);
    expect(screen.getByText(/全量关系目录 1003 条 \/ 667 只/)).toBeTruthy();
    expect(screen.getByText(/目录只用于检索，不计入候选、评估计数或合并结论/)).toBeTruthy();
    expect(screen.getByText(/日常输入合同 VERIFIED · 模式 MANUAL · 港股目标日 20261020 · 美股来源会话 20261016/)).toBeTruthy();
    expect(screen.getByText(/目标日资格 CANNOT_CONFIRM/)).toBeTruthy();
    const cutoffLabel = screen.getByText("研究截止").parentElement?.textContent;
    const generatedLabel = screen.getByText("实际生成").parentElement?.textContent;
    expect(cutoffLabel).toBeTruthy();
    expect(cutoffLabel).not.toBe(generatedLabel);
  });
});
