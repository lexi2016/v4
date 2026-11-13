import { cleanup, render, screen } from "@testing-library/vue";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App.vue";
const state = vi.hoisted(() => ({ stage: null as any }));
vi.mock("./api/pool_stage", async (original) => ({
  ...await original<typeof import("./api/pool_stage")>(),
  loadStageSnapshot: async () => state.stage,
}));

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it("renders traceable preopen news while leaving missing structure and original stage score visible", async () => {
  window.history.replaceState({}, "", "/?date=20261113&stage=STAGE_0925");
  const row = { market: "A", code: "A.002205", name: "国统股份", rank: 1, score: 100,
    stage_score: 100, formal_eligible: false, trade_status: "WATCH_ONLY",
    source_mode: "A_SHARE_NATIVE_QUOTE_SNAPSHOT_STAGE_0925",
    news_link: { score: 48, article_count: 2, mode: "READ_ONLY_SUPPLEMENT_NOT_IN_ORIGINAL_STAGE_SCORE",
      cutoff: "09:25:05", articles: [{ source_title: "11月13日盘前纪要",
        source_url: "https://www.jiuyangongshe.com/a/20dw7p5hnlw", published_at: "2026-11-13 07:06:33",
        logic_excerpt: "国统股份原文证据" }] },
    news_missing_reason: "原阶段未生成新闻分；补关联分未计入原阶段分",
    research_missing_reason: "09:00 研报归档无该股记录（已核验）",
    structure_missing_reason: "支撑位、压力位、失效位：该竞价快照未提供可核验的结构价位" };
  const stage = { trade_date: "20261113", stage_id: "STAGE_0925", response_source: "SHARED_STAGE_CENTER",
    selection_mode: "SHARED_STAGE_CENTER_READ_ONLY", stage: { stage_id: "STAGE_0925", status: "PARTIAL_WITH_ROWS", display_status: "PARTIAL_WITH_ROWS" },
    markets: { A: { candidate_count: 1, rows: [row] }, HK: { candidate_count: 0, rows: [] } },
    unified_rows: [row], selected_a_rows: 1, selected_hk_rows: 0, selected_total_rows: 1,
    RESEARCH_ONLY: true, write_performed: false, production_allowed: false, buy_gate_updated: false, orders_sent: false };
  state.stage = stage;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => ({ ok: true, json: async () =>
    url === "/api/v1/runs/date-list" ? { default_date: "20261113", stage_dates: ["20261113"], future_target_dates: [] } :
      url.startsWith("/api/v3/workbench/stage") ? stage :
        { data_status: "DATA_BLOCKED_EMPTY", rows: [], blocking_reasons: [], groups: {}, write_policy: "read_only",
          production_allowed: false, buy_gate_updated: false, orders_sent: false } })));
  render(App);
  expect(await screen.findByText("国统股份")).toBeTruthy();
  expect(screen.getByText(/48.*补关联/)).toBeTruthy();
  expect(screen.getByText("09:00 研报归档无该股记录（已核验）")).toBeTruthy();
  expect(screen.getByText(/抓取PIT未验证/)).toBeTruthy();
  expect(screen.getByRole("link", { name: "11月13日盘前纪要" }).getAttribute("href")).toContain("20dw7p5hnlw");
  expect(screen.getByText(row.structure_missing_reason)).toBeTruthy();
  expect(screen.getByText("100")).toBeTruthy();
});
