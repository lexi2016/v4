import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
// @ts-expect-error The app tsconfig intentionally excludes Node globals; Vitest still runs this native read-only test helper in Node.
import { readFileSync } from "node:fs";
// @ts-expect-error The app tsconfig intentionally excludes Node globals; Vitest still runs this native read-only test helper in Node.
import { resolve } from "node:path";

import App from "./App.vue";
declare const process: { cwd(): string };
const styleSource = readFileSync(resolve(process.cwd(), "src/style.css"), "utf8");

const blockedPool = { data_status: "DATA_BLOCKED_EMPTY", trade_date: "20260730", rows: [], blocking_reasons: ["missing"] };
const referenceStage = {
  ok: true,
  trade_date: "20260730",
  stage: {
    stage_id: "STAGE_0925",
    label: "09:20/09:25竞价参考",
    window: "09:20-09:25",
    status: "DATA_PARTIAL_OBSERVE_ONLY",
    display_status: "09:25 竞价落盘：候选仅供观察",
  },
  markets: {
    A: { label: "A股", candidate_count: 0, source_rows: 1, requested_rows: 159, data_level: "L1_TREND_ANALYSIS" },
    HK: { label: "港股通", candidate_count: 2, source_rows: 100, data_level: "AUCTION_SECOND_FILTER_READY" },
  },
  unified_rows: [
    {
      market: "HK",
      code: "HK.01357",
      name: "美图公司",
      rank: 1,
      score: 82,
      d1_change_pct: 13.0653,
      stage_display_decision: "09:30初步筛选",
      next_validation_time: "09:35",
      support_primary_price: 4.02,
      pressure_price: 4.18,
      invalidation_price: 3.96,
      cannot_confirm: ["CANNOT_CONFIRM_SUPPORT_INVALIDATION_LINE"],
      data_level: "AUCTION_SECOND_FILTER_READY",
      recommendation_status: "WATCH_ONLY",
    },
    {
      market: "HK",
      code: "HK.09903",
      name: "天数智芯",
      rank: 2,
      score: 80.59,
      d1_change_pct: -13.5029,
      stage_display_decision: "09:30初步筛选",
      next_validation_time: "09:35",
      cannot_confirm: [],
      data_level: "AUCTION_SECOND_FILTER_READY",
      recommendation_status: "WATCH_ONLY",
    },
  ],
  selected_a_rows: 0,
  selected_hk_rows: 2,
  selected_total_rows: 2,
  selection_mode: "MIGRATED_REFERENCE_WORKBENCH",
  response_source: "V3_5_MIGRATED_REFERENCE_SNAPSHOT",
  reference_snapshot: true,
  recommendation_status: "WATCH_ONLY_BACKTEST_GATED",
  production_allowed: false,
  buy_gate_updated: false,
  orders_sent: false,
};

const jsonResponse = (payload: unknown) => ({ ok: true, json: async () => payload });
const taskStatus = {
  logical_workload_count: 3,
  active_owner_count: 1,
  alias_count: 2,
  retired_owner_count: 6,
  task_registration_count: 1,
  groups: {
    logical: [{
      workload_id: "hourly_research", status: "CANNOT_CONFIRM",
      last_run: null, next_due: "07:00", duration_ms: null,
      result_code: "EXECUTION_RECEIPT_MISSING", freshness: "NOT_OBSERVED", receipt_path: null,
    }],
    active_owners: [{ owner_id: "v35_dispatcher.hourly_research", workload_id: "hourly_research", status: "ACTIVE" }],
    aliases: [
      { alias: "hourly_research_delta", workload_id: "hourly_research", status: "ALIAS_ONLY" },
      { alias: "v3_hourly_research_delta_0730_1530", workload_id: "hourly_research", status: "ALIAS_ONLY" },
    ],
    retired: [{ owner_id: "OpeningAdvisorHourlyResearch", replacement_workload_id: "hourly_research", status: "RETIRED_DISABLED" }],
    registrations: [{
      graph_task_spec_id: "task_spec:OpeningAdvisorV3_0755_StartupEnsure",
      legacy_task_id: "OpeningAdvisorV3_0755_StartupEnsure",
      timeline_node_ids: ["v3_ashare_readiness_0755"],
      legacy_launcher_paths: ["launcher.ps1"],
      actual_windows_task_ids: ["OpeningAdvisorV3_0755_StartupEnsure"],
      enabled: false,
      execution_allowed: false,
      status: "CANNOT_CONFIRM",
      disposition: "USER_APPROVED_DISABLED_CANNOT_CONFIRM",
    }],
  },
  timeline_nodes: [{
    position: 13, node_id: "FUPAN_VIDEO_CHECK", label: "13. 20:30 最新复盘视频检查",
    planned_slot: "2030", owner_id: "v35_dispatcher.fupan_video_check", status: "READY",
    reason: "NODE_RECEIPT_READY", result_code: "SUCCESS", last_run: "2026-07-30T12:30:00Z",
    freshness: "CURRENT", actual_receipt_path: ".runtime/data/runtime_graph/evidence/scheduler_status/20260730/FUPAN_VIDEO_CHECK.json",
    production_allowed: false, buy_gate_updated: false, orders_sent: false,
  }],
  cannot_confirm: ["EXECUTION_RECEIPT_MISSING:hourly_research", "GRAPH_TASK_REGISTRATIONS_CANNOT_CONFIRM:1"],
  production_allowed: false,
  buy_gate_updated: false,
  orders_sent: false,
};
const closeReview = {
  trade_date: "20260730",
  reference_snapshot: false,
  market_reviews: {
    A: {
      status: "READY", headline: "A-share review", market_regime: "CANNOT_CONFIRM", risk_tone: "CANNOT_CONFIRM",
      big_picture: [], mainlines: [], core_stocks: [], observation_pool: [], next_day_trigger_tree: [], quality_gate: [],
      cannot_confirm: ["A_REVIEW_GAP"], production_allowed: false, buy_gate_updated: false, orders_sent: false,
    },
    HK: {
      model_selection_review: {
        schema_version: "v3_5.close_review.v1",
        evidence_mode: "V3_5_NATIVE_PRODUCTION",
        status: "MODEL_REVIEW_PARTIAL_STAGE_EVIDENCE",
        trade_date: "20260730",
        primary_kpi: "全港股通收盘涨幅Top20覆盖率",
        models: {
          "0.2_prob_active": { selected_count: 100, hit_count: 3, coverage_pct: 15, precision_pct: 3 },
        },
        stage_union: { selected_count: 17, hit_count: 2, coverage_pct: 10, precision_pct: 11.765 },
        row_counts: { close_top20: 20, model_0_2: 100, stage_rows: 17 },
        top20_attribution: [{
          rank: 1, code: "HK.00325", name: "布鲁可", pct_chg_close: 15.9343,
          model_0_2_hit: true, stage_union_hit: false, classification: "model_only",
        }],
        close_top20: [{ rank: 1, code: "HK.00325", name: "布鲁可", pct_chg_close: 15.9343 }],
        model_rows: [],
        stage_rows: [],
        missing_stages: ["STAGE_0925"],
        cannot_confirm: ["MISSING_STAGE_0925"],
        production_allowed: false,
        buy_gate_updated: false,
        orders_sent: false,
      },
    },
  },
  production_allowed: false,
  buy_gate_updated: false,
  orders_sent: false,
};

const nativeCloseReview = structuredClone(closeReview) as any;
nativeCloseReview.schema_version = "v3_5.review_envelope.v1";
nativeCloseReview.reference_snapshot = false;
nativeCloseReview.market_reviews.HK.model_selection_review.reference_snapshot = false;
nativeCloseReview.market_reviews.HK.model_selection_review.close_source_sha256 = "a".repeat(64);

describe("V3.5 legacy-compatible stage workbench", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/?date=20260730&stage=STAGE_0925");
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url.startsWith("/api/v3/tasks/status")) return jsonResponse(taskStatus);
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(referenceStage);
      return jsonResponse(blockedPool);
    }));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("defines a 412px overflow contract for stage and review consumers", () => {
    const mobileRules = styleSource.slice(styleSource.lastIndexOf("@media (max-width: 412px)"));

    expect(mobileRules).toMatch(/\.market-columns\s*\{[^}]*grid-template-columns:\s*1fr/);
    expect(mobileRules).toMatch(/\.candidate-card\s*\{[^}]*min-width:\s*0/);
    expect(mobileRules).toMatch(/\.candidate-card dl\s*\{[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/);
    expect(styleSource).toMatch(/\.review-table-wrap\s*\{[^}]*min-width:\s*0[^}]*max-width:\s*100%/);
    expect(mobileRules).toMatch(/\.review-table-wrap\s+table\s*\{[^}]*width:\s*max-content[^}]*min-width:\s*100%/);
    expect(mobileRules).toMatch(/\.review-evidence-panel dd\s*\{[^}]*overflow-wrap:\s*anywhere/);
  });

  it("defines a 412px timeline containment contract for long status text", () => {
    const mobileRules = styleSource.slice(styleSource.lastIndexOf("@media (max-width: 412px)"));

    expect(mobileRules).toMatch(/\.timeline-grid\s*\{[^}]*grid-template-columns:\s*1fr/);
    expect(mobileRules).toMatch(/\.timeline-grid button,\s*\.timeline-grid button > \*\s*\{[^}]*min-width:\s*0[^}]*overflow-wrap:\s*anywhere[^}]*word-break:\s*break-word/);
  });

  it("defines a 412px review status containment contract without changing table scrolling", () => {
    const mobileRules = styleSource.slice(styleSource.lastIndexOf("@media (max-width: 412px)"));

    expect(mobileRules).toMatch(/\.review-view \.review-metric-grid\s*\{[^}]*grid-template-columns:\s*1fr[^}]*min-width:\s*0/);
    expect(mobileRules).toMatch(/\.review-view \.review-metric-grid article\s*\{[^}]*min-width:\s*0/);
    expect(mobileRules).toMatch(/\.review-view p,\s*\.review-view strong,\s*\.review-view summary,/);
    expect(mobileRules).toMatch(/\.review-view \.review-metric-grid span,\s*\.review-view \.review-metric-grid small\s*\{[^}]*overflow-wrap:\s*anywhere[^}]*word-break:\s*break-word/);
  });

  it("restores the old V3 header controls and nineteen-node timeline", async () => {
    render(App);
    expect(await screen.findByRole("heading", { level: 1, name: "v3 阶段选股" })).toBeTruthy();
    const dateInput = screen.getByLabelText("交易日（日历选择）");
    expect(dateInput.getAttribute("type")).toBe("date");
    expect(dateInput.hasAttribute("list")).toBe(false);
    expect(document.querySelector("datalist")).toBeNull();
    expect(screen.getByRole("combobox", { name: "阶段" })).toBeTruthy();
    for (const name of ["刷新快照", "阶段选股", "D-1 预选池", "研报决策台", "任务状态", "A股复盘"]) {
      expect(screen.getByRole("button", { name })).toBeTruthy();
    }
    expect(within(screen.getByRole("region", { name: "七阶段上下文" })).getAllByRole("button")).toHaveLength(19);
    expect(screen.getByText("19. 21:15 8871 刷新与页面验收")).toBeTruthy();
    expect(screen.getByText("13. 20:30 最新复盘视频检查")).toBeTruthy();
    expect(await screen.findByText("READY · NODE_RECEIPT_READY")).toBeTruthy();
  }, 10_000);

  it("opens the research desk on the selected exact date without an implicit latest request", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({
          default_date: "20260730",
          stage_dates: ["20260730"],
          research_dates: ["20260730"],
          future_target_dates: [],
        });
      }
      if (url === "/api/v3/research/lane?research_date=20260730") {
        return jsonResponse({
          schema_version: "v3_5.research_lane.v1",
          status: "NOT_MATERIALIZED",
          endpoint_mode: "EXACT",
          research_date: "20260730",
          reason: "RESEARCH_LANE_SNAPSHOT_NOT_FOUND",
          write_policy: "read_only",
          recommendation_status: "RESEARCH_ONLY",
          production_allowed: false,
          buy_gate_updated: false,
          orders_sent: false,
        });
      }
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(referenceStage);
      return jsonResponse(blockedPool);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(App);
    await screen.findByText("美图公司");

    await fireEvent.click(screen.getByRole("button", { name: "研报决策台" }));

    expect(await screen.findByRole("region", { name: "研报决策台" })).toBeTruthy();
    expect(await screen.findByText("NOT_MATERIALIZED")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith("/api/v3/research/lane?research_date=20260730");
    expect(fetchMock.mock.calls.some(([url]) => url === "/api/v3/research/lane")).toBe(false);
  }, 15_000);

  it("opens the real task status view and returns to the stage workbench", async () => {
    render(App);
    await screen.findByText("美图公司");

    await fireEvent.click(screen.getByRole("button", { name: "任务状态" }));
    expect((await screen.findByRole("alert")).textContent).toContain("EXECUTION_RECEIPT_MISSING:hourly_research");
    expect(screen.getByRole("region", { name: "任务状态" })).toBeTruthy();
    expect(screen.queryByText("美图公司")).toBeNull();

    await fireEvent.click(screen.getByRole("button", { name: "阶段选股" }));

    await waitFor(() => expect(screen.getByText("美图公司")).toBeTruthy());
    expect(screen.queryByRole("region", { name: "任务状态" })).toBeNull();
  }, 10_000);

  it("shows old-style status cards and structured A/HK candidate columns", async () => {
    render(App);
    expect(await screen.findByText("美图公司")).toBeTruthy();
    expect(screen.getByText("HK.01357 · 排名 1")).toBeTruthy();
    expect(screen.getByText("82")).toBeTruthy();
    expect(screen.getByText("13.065%")).toBeTruthy();
    expect(screen.getAllByText("09:30初步筛选").length).toBeGreaterThan(0);
    expect(screen.getAllByText("09:35").length).toBeGreaterThan(0);
    expect(screen.getAllByText("参考快照").length).toBeGreaterThan(0);
    expect(screen.getByText("只读")).toBeTruthy();
    expect(screen.getByText("A股无主表候选")).toBeTruthy();
    expect(screen.getByText("港股通09:20 / A股09:25竞价选股 阶段 · source rows 1 / requested 159")).toBeTruthy();
    expect(screen.getByRole("region", { name: "A股候选" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "港股通候选" })).toBeTruthy();
    expect(screen.queryByText("支撑位")).toBeNull();
    expect(screen.queryByText("压力位")).toBeNull();
    expect(screen.queryByText("失效位")).toBeNull();
  });

  it("renders the exact D-1/09:20 business state without a missing-evidence placeholder", async () => {
    const d1ReferenceStage = structuredClone(referenceStage) as any;
    d1ReferenceStage.unified_rows = [{
      market: "HK",
      code: "HK.00325",
      name: "布鲁可",
      rank: 1,
      score: 0.836328,
      status: "WAITING_0920_SECOND_FILTER",
      source_mode: "HK_CONNECT_D1_PRESELECT_REFERENCE",
      next_validation_time: "09:20:05",
      trade_status: "WATCH_ONLY",
    }];
    d1ReferenceStage.selected_hk_rows = 1;
    d1ReferenceStage.selected_total_rows = 1;
    d1ReferenceStage.markets.HK.candidate_count = 1;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(d1ReferenceStage);
      return jsonResponse(blockedPool);
    }));

    const { container } = render(App);

    await screen.findByText("布鲁可");
    const hkRegion = await screen.findByRole("region", { name: "港股通候选" });
    expect(within(hkRegion).getByText("D-1参考，待09:20二筛")).toBeTruthy();
    expect(within(hkRegion).getByText("D-1参考分")).toBeTruthy();
    expect(within(hkRegion).getByText("0.836")).toBeTruthy();
    expect(within(hkRegion).queryByText("支撑位")).toBeNull();
    expect(within(hkRegion).queryByText("压力位")).toBeNull();
    expect(within(hkRegion).queryByText("失效位")).toBeNull();
    expect(container.textContent).not.toContain("缺证");
  });

  it("renders HK 09:20 reference changes on their distinct quote bases", async () => {
    const exactAuctionStage = structuredClone(referenceStage) as any;
    exactAuctionStage.reference_snapshot = false;
    exactAuctionStage.unified_rows = [{
      market: "HK",
      code: "HK.01548",
      name: "金斯瑞生物科技",
      rank: 1,
      score: 87.0436,
      source_mode: "HK_CONNECT_AUCTION_SECOND_FILTER_STAGE_0925",
      auction_ref_gap_pct: 0.1142,
      first_to_last_ref_pct: 1.6812,
      reference_price_hkd: 35.08,
      current_change_pct: 0.1142,
      next_validation_time: "09:35:05",
      recommendation_status: "WATCH_ONLY",
    }];
    exactAuctionStage.selected_hk_rows = 1;
    exactAuctionStage.selected_total_rows = 1;
    exactAuctionStage.markets.HK.candidate_count = 1;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(exactAuctionStage);
      return jsonResponse(blockedPool);
    }));

    const { container } = render(App);

    await screen.findByText("金斯瑞生物科技");
    const hkRegion = await screen.findByRole("region", { name: "港股通候选" });
    expect(within(hkRegion).getByText("参考价阶段变化")).toBeTruthy();
    expect(within(hkRegion).getByText("1.681%")) .toBeTruthy();
    expect(within(hkRegion).getByText("参考价较昨收")).toBeTruthy();
    expect(within(hkRegion).getByText("0.114%")) .toBeTruthy();
    expect(container.textContent).not.toContain("阶段涨幅");
  });

  it("keeps both HK 09:20 reference displays unavailable when their source fields are null", async () => {
    const missingAuctionQuotes = structuredClone(referenceStage) as any;
    missingAuctionQuotes.reference_snapshot = false;
    missingAuctionQuotes.unified_rows = [{
      market: "HK",
      code: "HK.01548",
      name: "金斯瑞生物科技",
      rank: 1,
      score: 87.0436,
      source_mode: "HK_CONNECT_AUCTION_SECOND_FILTER_STAGE_0925",
      auction_ref_gap_pct: null,
      first_to_last_ref_pct: null,
      current_change_pct: 9.9,
      next_validation_time: "09:35:05",
      recommendation_status: "WATCH_ONLY",
    }];
    missingAuctionQuotes.selected_hk_rows = 1;
    missingAuctionQuotes.selected_total_rows = 1;
    missingAuctionQuotes.markets.HK.candidate_count = 1;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(missingAuctionQuotes);
      return jsonResponse(blockedPool);
    }));

    const { container } = render(App);

    await screen.findByText("金斯瑞生物科技");
    const hkRegion = await screen.findByRole("region", { name: "港股通候选" });
    expect(within(hkRegion).getByText("参考价阶段变化")).toBeTruthy();
    expect(within(hkRegion).getByText("参考价较昨收")).toBeTruthy();
    expect(within(hkRegion).getAllByText("阶段行情未生成")).toHaveLength(2);
    expect(container.textContent).not.toContain("9.9%");
  });

  it("projects exact-date A-share news and research quality scores and D-1 pool provenance", async () => {
    window.history.replaceState({}, "", "/?date=20260730&stage=STAGE_0930_0935");
    const postOpenStage = structuredClone(referenceStage) as any;
    postOpenStage.stage = {
      stage_id: "STAGE_0930_0935",
      label: "09:30-09:35",
      window: "09:30-09:35",
      status: "PARTIAL_WITH_ROWS",
      display_status: "PARTIAL_WITH_ROWS",
    };
    postOpenStage.unified_rows = [{
      market: "A",
      code: "A.002353",
      name: "杰瑞股份",
      rank: 1,
      score: 104.090674,
      current_change_pct: 3.3031,
      news_quality_score: 0,
      research_quality_score: 84,
      latest_research_slot: "0900",
      next_validation_time: "09:35:05",
      support_primary_price: 147.74,
      pressure_price: 153.22,
      invalidation_price: 147.74,
      trade_date: "20260730",
      stage_id: "STAGE_0930_0935",
      trade_status: "WATCH_ONLY",
    }];
    postOpenStage.selected_a_rows = 1;
    postOpenStage.selected_hk_rows = 0;
    postOpenStage.selected_total_rows = 1;
    postOpenStage.markets.A.candidate_count = 1;
    postOpenStage.markets.HK.candidate_count = 0;
    const poolWithProvenance = {
      data_status: "PARTIAL_WITH_ROWS",
      trade_date: "20260730",
      market_totals: { A: 1, HK: 0 },
      pools: [{
        pool_id: "a_share_baimao_research_map",
        display_name: "白毛卡点研究池",
        status: "BAIMAO_RESEARCH_MAP_READY",
        pool_size: 1,
        rows: [{ market: "A", symbol: "A.688025", stock_name: "仕佳光子", source_date: "20260729" }],
      }],
      a_all_pool_rows: [],
      rows: [],
      blocking_reasons: [],
    };
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(postOpenStage);
      return jsonResponse(poolWithProvenance);
    }));

    const { container } = render(App);

    await screen.findByText("杰瑞股份");
    const aRegion = await screen.findByRole("region", { name: "A股候选" });
    expect(within(aRegion).getByText("新闻分")).toBeTruthy();
    expect(within(aRegion).getByText("研报分")).toBeTruthy();
    expect(within(aRegion).getByText("84")).toBeTruthy();
    const baimaoRegion = screen.getByRole("region", { name: "白毛卡点研究池" });
    expect(within(baimaoRegion).getByText("20260729")).toBeTruthy();
    expect(container.textContent).not.toContain("缺证");
  });

  it("loads every stage snapshot into the timeline and explains an empty HK stage", async () => {
    const stageById: Record<string, any> = {};
    const stageIds = [
      "STAGE_0925",
      "STAGE_0930_0935",
      "STAGE_0935_0940",
      "STAGE_0940_0945",
      "STAGE_0945_1030",
      "STAGE_1300_1315",
      "STAGE_1445_1500",
      "STAGE_1545_1555",
    ];
    stageIds.forEach((stageId, index) => {
      const snapshot = structuredClone(referenceStage) as any;
      snapshot.trade_date = "20260730";
      snapshot.stage.stage_id = stageId;
      snapshot.stage.status = index === 0 ? "CANNOT_CONFIRM" : `READY_STAGE_${index + 1}`;
      snapshot.stage.display_status = `真实状态 ${index + 1}`;
      snapshot.selected_a_rows = index === 0 ? 0 : index + 1;
      snapshot.selected_hk_rows = index === 0 ? 0 : index + 2;
      snapshot.selected_total_rows = snapshot.selected_a_rows + snapshot.selected_hk_rows;
      snapshot.markets.A.candidate_count = snapshot.selected_a_rows;
      snapshot.markets.HK.candidate_count = snapshot.selected_hk_rows;
      snapshot.unified_rows = [];
      stageById[stageId] = snapshot;
    });
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url.startsWith("/api/v3/workbench/stage")) {
        const stageId = new URL(url, window.location.origin).searchParams.get("stage") || "STAGE_0925";
        return jsonResponse(stageById[stageId]);
      }
      return jsonResponse(blockedPool);
    }));

    render(App);

    expect(await screen.findByText("港股通该阶段无可确认候选")).toBeTruthy();
    const timeline = screen.getByRole("region", { name: "七阶段上下文" });
    await waitFor(() => {
      expect(within(timeline).getByText("READY_STAGE_2")).toBeTruthy();
      expect(within(timeline).getByText("A 3 / HK 4")).toBeTruthy();
      expect(within(timeline).getByText("READY_STAGE_8")).toBeTruthy();
    });
    const stageButtons = within(timeline).getAllByRole("button").slice(0, 8);
    expect(stageButtons.every((button) => !button.textContent?.includes("未加载"))).toBe(true);
    expect(screen.queryByText("港股通候选未加载")).toBeNull();
  });

  it("uses the task receipt status for the first timeline node before its planned slot", async () => {
    const pendingNodeTaskStatus = structuredClone(taskStatus) as any;
    pendingNodeTaskStatus.timeline_nodes = [{
      position: 1,
      node_id: "STAGE_0925",
      label: "1. 港股通09:20 / A股09:25竞价选股",
      planned_slot: "0925",
      owner_id: "stage_center.STAGE_0925",
      status: "PENDING_NOT_DUE",
      reason: "PLANNED_SLOT_NOT_REACHED",
      result_code: "PENDING_NOT_DUE",
      production_allowed: false,
      buy_gate_updated: false,
      orders_sent: false,
    }];
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url.startsWith("/api/v3/tasks/status")) return jsonResponse(pendingNodeTaskStatus);
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(referenceStage);
      return jsonResponse(blockedPool);
    }));

    render(App);

    const timeline = await screen.findByRole("region", { name: "七阶段上下文" });
    const firstStageButton = within(timeline).getAllByRole("button")[0];
    await waitFor(() => expect(firstStageButton.textContent).toContain("PENDING_NOT_DUE · PLANNED_SLOT_NOT_REACHED"));
  });

  it("shows the frozen v1.1 identity and separate A/HK auction refresh times", async () => {
    const v11Stage = structuredClone(referenceStage) as any;
    v11Stage.selection_mode = "V1_1_CHAMPION_DUAL_MARKET";
    v11Stage.response_source = "V3_5_NATIVE_STAGE_SNAPSHOT_WITH_V1_1_CHAMPION";
    v11Stage.reference_snapshot = false;
    v11Stage.opening_second_filter = {
      model_id: "hkconnect_opening_second_filter_v1_1",
      model_version: "1.1",
      champion_contract: "old_v3_rule_guardrail_with_hardcap_and_0920_reference_layer",
      markets: {
        A: { refresh_time: "09:25", strategy: "a_share_v1_1_price_volume_adapter", row_count: 0 },
        HK: { refresh_time: "09:20", strategy: "v1_1_champion", row_count: 20 },
      },
    };
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(v11Stage);
      return jsonResponse(blockedPool);
    }));

    render(App);

    expect(await screen.findByText("v1.1 竞价二筛")).toBeTruthy();
    expect(screen.getByText("hkconnect_opening_second_filter_v1_1")).toBeTruthy();
    expect(screen.getByText("港股 09:20 刷新 · A股 09:25 刷新")).toBeTruthy();
    expect(screen.getByText(/上游预选 159 \/ 同截点证据 1 \/ 阶段候选 0 \/ 入选 0/)).toBeTruthy();
    expect(screen.queryByText(/上游预选 147 \/ 同截点证据 0/)).toBeNull();
    expect(screen.queryByText("参考快照 · WATCH_ONLY")).toBeNull();
  });

  it("keeps exact same-origin date and stage requests", async () => {
    const fetchMock = vi.mocked(fetch);
    render(App);
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith("/api/v1/runs/date-list");
      expect(fetchMock).toHaveBeenCalledWith("/api/v3/research/dates");
      expect(fetchMock).toHaveBeenCalledWith("/api/v3/preselection-pools?date=20260730&limit=200");
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v3/workbench/stage?date=20260730&stage=STAGE_0925&limit=50",
      );
    });

    await fireEvent.update(screen.getByRole("combobox", { name: "阶段" }), "STAGE_0930_0935");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/v3/workbench/stage?date=20260730&stage=STAGE_0930_0935&limit=50",
    ));
  });

  it("keeps the 50-row A total while rendering the V3 12-card preview", async () => {
    const native0925 = structuredClone(referenceStage) as any;
    native0925.selection_mode = "V3_5_NATIVE_STAGE_SCORE_V1";
    native0925.response_source = "V3_5_NATIVE_STAGE_SNAPSHOT";
    native0925.reference_snapshot = false;
    native0925.markets.A = {
      label: "A股", candidate_count: 50, source_rows: 146, requested_rows: 147,
      source_status: "CANNOT_CONFIRM", data_level: "WATCH_ONLY",
    };
    native0925.unified_rows = Array.from({ length: 50 }, (_unused, index) => ({
      market: "A", symbol: `A.${String(index).padStart(6, "0")}`,
      stock_name: `A-stage-${index + 1}`, stage_rank: String(index + 1),
      stage_score: 200 - index, recommendation_status: "WATCH_ONLY",
    }));
    native0925.selected_a_rows = 50;
    native0925.selected_hk_rows = 0;
    native0925.selected_total_rows = 50;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(native0925);
      return jsonResponse(blockedPool);
    }));

    render(App);

    expect(await screen.findByText("A-stage-1")).toBeTruthy();
    expect(document.querySelectorAll('[aria-label="A股候选"] .candidate-card')).toHaveLength(12);
    expect(screen.queryByText("A-stage-13")).toBeNull();
    expect(screen.queryByText("A股无主表候选")).toBeNull();
    expect(document.querySelectorAll(".status-grid article")[1].textContent).toContain("50");
    expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      "/api/v3/workbench/stage?date=20260730&stage=STAGE_0925&limit=50",
    );
  });

  it("does not present post-open level fields as missing evidence during the 09:20 screen", async () => {
    render(App);
    expect(await screen.findByText("美图公司")).toBeTruthy();
    expect(screen.queryByText("支撑位")).toBeNull();
    expect(screen.queryByText("压力位")).toBeNull();
    expect(screen.queryByText("失效位")).toBeNull();
    expect(screen.queryByText(/缺证 6 项/)).toBeNull();
    expect(screen.getByText("09:20阶段只做初筛；支撑/压力/失效位从09:30后阶段生成。")).toBeTruthy();
  });

  it("does not label replay boundary notes as missing fields after 09:30", async () => {
    const replayStage = structuredClone(referenceStage);
    replayStage.unified_rows.forEach((row: any) => {
      row.cannot_confirm = Array(6).fill("REPLAY_BOUNDARY_NOTE");
    });
    delete (replayStage.unified_rows[1] as any).d1_change_pct;
    Object.assign(replayStage.unified_rows[1] as any, {
      current_change_pct: 0.3431,
      support_primary_price: 116.6,
      pressure_price: 117.1,
      invalidation_price: 116.6,
    });
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(replayStage);
      return jsonResponse(blockedPool);
    }));
    render(App);
    expect(await screen.findByText("美图公司")).toBeTruthy();
    await fireEvent.update(screen.getByRole("combobox", { name: "阶段" }), "STAGE_0930_0935");
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      "/api/v3/workbench/stage?date=20260730&stage=STAGE_0930_0935&limit=50",
    ));
    expect(screen.queryByText(/缺证 6 项/)).toBeNull();
    expect(screen.getAllByText("支撑位").length).toBeGreaterThan(0);
    expect(screen.getAllByText("压力位").length).toBeGreaterThan(0);
    expect(screen.getAllByText("失效位").length).toBeGreaterThan(0);
    expect(screen.getByText("0.343%")).toBeTruthy();
    expect(screen.queryByText(/待补字段/)).toBeNull();
  });

  it("renders the old V3 A-share post-open fields from the migrated workbench", async () => {
    window.history.replaceState({}, "", "/?date=20260730&stage=STAGE_0930_0935");
    const postOpenStage = structuredClone(referenceStage);
    postOpenStage.unified_rows.unshift({
      market: "A",
      code: "A.603137",
      name: "恒尚节能（选）",
      rank: 3,
      score: 140.312345,
      current_change_pct: 4.113,
      stage_display_decision: "A股回踩确认",
      next_validation_time: "09:40",
      support_primary_price: 22.72,
      pressure_price: 24.83,
      invalidation_price: 22.72,
      cannot_confirm: [],
      data_level: "FUTU_A_SHARE_1MIN_CUTOFF_SAFE",
      recommendation_status: "WATCH_ONLY",
    } as any);
    postOpenStage.selected_a_rows = 1;
    postOpenStage.selected_total_rows = 3;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(postOpenStage);
      return jsonResponse(blockedPool);
    }));

    render(App);

    expect(await screen.findByText("恒尚节能（选）")).toBeTruthy();
    expect(screen.getByText("4.113%")).toBeTruthy();
    expect(screen.getByText("140.312")).toBeTruthy();
    expect(screen.getAllByText("22.72")).toHaveLength(2);
    expect(screen.getByText("24.83")).toBeTruthy();
    expect(screen.getByText("09:40")).toBeTruthy();
  });

  it("adapts native replay fields into a complete A-share candidate card", async () => {
    window.history.replaceState({}, "", "/?date=20260730&stage=STAGE_1445_1500");
    const nativeStage = structuredClone(referenceStage);
    nativeStage.stage = {
      stage_id: "STAGE_1445_1500",
      label: "14:45-15:00",
      window: "14:45-15:00",
      status: "PARTIAL_WITH_WATCH_ROWS",
      display_status: "阶段输入部分可确认；仅展示 WATCH_ONLY 观察行。",
    };
    nativeStage.markets.A = {
      label: "A股", candidate_count: 1, source_rows: 147, requested_rows: 147, data_level: "WATCH_ONLY",
    };
    nativeStage.unified_rows = [{
      market: "A",
      symbol: "A.603137",
      stock_name: "Native A",
      stage_rank: "1",
      stage_score: 222.016688,
      open_price: 23.03,
      last_price: 26.21,
      low_price: 23.03,
      high_price: 26.21,
      source_last_bar_time: "15:00:00",
      data_level: "STAGE_RTDATA_LATE_REPLAY",
      recommendation_status: "WATCH_ONLY",
    } as any];
    nativeStage.selected_a_rows = 1;
    nativeStage.selected_hk_rows = 0;
    nativeStage.selected_total_rows = 1;
    nativeStage.selection_mode = "V3_5_NATIVE_STAGE_SCORE_V1";
    nativeStage.response_source = "V3_5_NATIVE_STAGE_SNAPSHOT";
    nativeStage.reference_snapshot = false;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(nativeStage);
      return jsonResponse(blockedPool);
    }));

    render(App);

    expect(await screen.findByText("Native A")).toBeTruthy();
    expect(screen.getByText("A.603137 · 排名 1")).toBeTruthy();
    expect(screen.getByText("13.808%")).toBeTruthy();
    expect(screen.getByText("222.017")).toBeTruthy();
    expect(screen.getAllByText("23.03")).toHaveLength(2);
    expect(screen.getByText("26.21")).toBeTruthy();
    expect(screen.getByText("15:00:00")).toBeTruthy();
    expect(screen.queryByText("缺证")).toBeNull();
  });

  it("restores the V3 D-1 group order, tables, source state, and collapse controls", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(referenceStage);
      return jsonResponse({
        data_status: "PARTIAL_WITH_ROWS",
        trade_date: "20260730",
        market_totals: { A: 147, HK: 100 },
        hk_pool_version: "0.2",
        hk_pool_role: "D_MINUS_1_MODEL_TOP100",
        pools: [
          { pool_id: "a_d1_premarket_pool", display_name: "A股 D-1 主预选池", pool_size: 19, rows: [{
            market: "A", symbol: "A.300347", stock_name: "泰格医药", pool_rank: 1, pool_score: 134, signal_date: "20260729",
          }] },
          { pool_id: "a_d1_fupan_watchlist_pool", display_name: "A股 D-1 复盘继续观察池", pool_size: 64, rows: [] },
          { pool_id: "a_d1_stage7_fenshi_review_pool", display_name: "A股 D-1 Stage7/分时复盘池", pool_size: 70, rows: [] },
          { pool_id: "a_share_research_recommendation_pool", display_name: "A股研究推荐池", pool_size: 6, rows: [] },
          { pool_id: "a_share_baimao_research_map", display_name: "白毛卡点研究池", pool_size: 0, status: "CANNOT_CONFIRM", cannot_confirm: ["BAIMAO_RESEARCH_MAP_NOT_FOUND"], rows: [] },
          { pool_id: "hkconnect_d1_top100", display_name: "港股通 0.2 D-1 Top100", pool_size: 100, rows: [{
            market: "HK", symbol: "HK.02685", stock_name: "量化派", pool_rank: 3, pool_score: 0.91, signal_date: "20260729",
          }] },
          { pool_id: "wechat_public_account_v3_preselect", display_name: "公众号股票池", pool_size: 43, status: "WECHAT_V3_PRESELECT_READY", cannot_confirm: [{ reason: "RESEARCH_ONLY_NO_BUY_GATE" }], rows: [{
            market: "WECHAT", symbol: "A.600298", stock_name: "安琪酵母", pool_rank: 1, pool_score: 5.644, signal_date: "20260730",
          }] },
        ],
        a_all_pool_rows: [], rows: [],
        blocking_reasons: [],
      });
    }));
    const { container } = render(App);
    expect(await screen.findByText("泰格医药")).toBeTruthy();
    const selector = screen.getByRole("region", { name: "A股 D-1 主预选池" });
    expect(within(selector).getByText("A.300347")).toBeTruthy();
    expect(within(selector).getByText("134")).toBeTruthy();
    expect(within(selector).getByText("20260729")).toBeTruthy();
    expect(screen.getByText("完整 19 条")).toBeTruthy();
    expect(screen.getByText("完整 64 条")).toBeTruthy();
    expect(screen.getByText("完整 70 条")).toBeTruthy();
    expect(screen.getByText("完整 6 条")).toBeTruthy();
    expect(screen.getByText("当前显示 0 / 共 147 条")).toBeTruthy();
    expect(screen.getByText("完整 0 条")).toBeTruthy();
    expect(screen.getByText("完整 100 条")).toBeTruthy();
    expect(screen.getByText("完整 43 条")).toBeTruthy();
    expect(screen.getByText("A股研究推荐池")).toBeTruthy();
    expect(screen.getByText("量化派")).toBeTruthy();
    expect(screen.getByText("安琪酵母")).toBeTruthy();
    expect(Array.from(container.querySelectorAll("#preselectGroups > section")).map((node) => node.id)).toEqual([
      "aPreselectGroup", "hkPreselectGroup", "wechatPreselectGroup", "selectorPreselectGroup",
      "fenshiPreselectGroup", "fupanPreselectGroup", "baimaoPreselectGroup", "researchPreselectGroup",
    ]);
    await fireEvent.click(within(selector).getByRole("button", { name: "收起" }));
    expect(within(selector).queryByText("泰格医药")).toBeNull();
    expect(within(selector).getByRole("button", { name: "展开" })).toBeTruthy();
    const baimao = screen.getByRole("region", { name: "白毛卡点研究池" });
    expect(within(baimao).getByText(/CANNOT_CONFIRM/)).toBeTruthy();
    expect(within(baimao).getByText(/BAIMAO_RESEARCH_MAP_NOT_FOUND/)).toBeTruthy();
    const wechat = screen.getByRole("region", { name: "公众号股票池" });
    expect(within(wechat).getAllByText(/WECHAT_V3_PRESELECT_READY/)).toHaveLength(2);
    expect(within(wechat).getByText(/RESEARCH_ONLY_NO_BUY_GATE/)).toBeTruthy();
  });

  it("keeps the V3 pool tables complete instead of merging or truncating groups", async () => {
    const aRows = Array.from({ length: 25 }, (_, index) => ({
      market: "A", symbol: `A.${String(index).padStart(6, "0")}`,
      stock_name: `A候选${index}`, pool_rank: index + 1,
    }));
    const hkRows = Array.from({ length: 25 }, (_, index) => ({
      market: "HK", symbol: `HK.${String(index).padStart(5, "0")}`,
      stock_name: `HK候选${index}`, pool_rank: index + 1,
    }));
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url.startsWith("/api/v3/tasks/status")) return jsonResponse(taskStatus);
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(referenceStage);
      return jsonResponse({
        data_status: "PARTIAL_WITH_ROWS",
        trade_date: "20260730",
        market_totals: { A: 25, HK: 25 },
        pools: [
          { pool_id: "a_d1_premarket_pool", market: "A", pool_size: 25, rows: aRows },
          { pool_id: "hkconnect_d1_top100", market: "HK", pool_size: 25, rows: hkRows },
        ],
        a_all_pool_rows: [], rows: [],
        blocking_reasons: [],
      });
    }));
    const { container } = render(App);
    expect(await screen.findByText("A候选0")).toBeTruthy();
    expect(screen.getByText("A候选24")).toBeTruthy();
    expect(screen.getByText("HK候选24")).toBeTruthy();
    expect(container.querySelectorAll(".pool-card")).toHaveLength(0);
    expect(within(screen.getByRole("region", { name: "A股 D-1 主预选池" })).getAllByRole("row")).toHaveLength(26);
    expect(within(screen.getByRole("region", { name: "港股通 D-1 预选池" })).getAllByRole("row")).toHaveLength(26);
  });

  it("opens one exact-date A/H review without a cross-date request", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url === "/api/v3/review?date=20260730") return jsonResponse(closeReview);
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(referenceStage);
      return jsonResponse(blockedPool);
    }));
    const fetchMock = vi.mocked(fetch);
    const { container } = render(App);
    await screen.findByText("美图公司");

    const closeButton = screen.getByText("9. 16:08 港股通正式收盘：0.2 × 七阶段 Top20").closest("button")!;
    const openingButton = screen.getByText("1. 港股通09:20 / A股09:25竞价选股").closest("button")!;
    const reviewEntry = within(container.querySelector("nav")!).getByRole("button", { name: "A股复盘" });
    await fireEvent.click(reviewEntry);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/v3/review?date=20260730"));
    expect(closeButton.classList.contains("current")).toBe(true);
    expect(reviewEntry.classList.contains("active")).toBe(true);
    expect(openingButton.classList.contains("current")).toBe(false);
    await waitFor(() => expect(container.querySelector(".review-view")).not.toBeNull());
    const reviewPanel = within(container.querySelector(".review-view")!);
    expect(reviewPanel.getByRole("heading", { name: "收盘复盘" })).toBeTruthy();
    expect(reviewPanel.getByRole("heading", { name: "A股复盘" })).toBeTruthy();
    expect(reviewPanel.getByRole("heading", { name: "HK 收盘复盘" })).toBeTruthy();
    expect(reviewPanel.getByText("0.2 模型")).toBeTruthy();
    expect(reviewPanel.getByText("3/20")).toBeTruthy();
    expect(reviewPanel.getByText("七阶段并集")).toBeTruthy();
    expect(reviewPanel.getByText("2/20")).toBeTruthy();
    expect(reviewPanel.getByText("布鲁可")).toBeTruthy();
    expect(reviewPanel.getByText("仅0.2")).toBeTruthy();
    expect(reviewPanel.getByText("A_REVIEW_GAP")).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalledWith("/api/v3/review?date=20260729");
  });

  it("rejects a preselection response whose date evidence is wrong", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(referenceStage);
      return jsonResponse({ ...blockedPool, trade_date: "20260729" });
    }));

    render(App);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("D-1 预选池日期证据错误");
    expect(screen.queryByRole("region", { name: "A股所有预选池汇总" })).toBeNull();
  });

  it("rejects a preselection response with missing date evidence", async () => {
    const missingPool = { ...blockedPool } as { trade_date?: string; data_status: string; rows: unknown[]; blocking_reasons: string[] };
    delete missingPool.trade_date;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(referenceStage);
      return jsonResponse(missingPool);
    }));

    render(App);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("D-1 预选池日期证据错误");
    expect(screen.queryByRole("region", { name: "A股所有预选池汇总" })).toBeNull();
  });

  it("rejects a close review response whose trade date is wrong", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url === "/api/v3/review?date=20260730") return jsonResponse({ ...closeReview, trade_date: "20260729" });
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(referenceStage);
      return jsonResponse(blockedPool);
    }));
    render(App);
    await screen.findByText("美图公司");

    await fireEvent.click(screen.getByRole("button", { name: "A股复盘" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("16:08 港股通收盘复盘日期证据错误");
    expect(screen.queryByText("布鲁可")).toBeNull();
  });

  it("rejects a close review response with missing trade date evidence", async () => {
    const missingDate = structuredClone(closeReview) as Record<string, unknown>;
    delete missingDate.trade_date;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url === "/api/v3/review?date=20260730") return jsonResponse(missingDate);
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(referenceStage);
      return jsonResponse(blockedPool);
    }));
    render(App);
    await screen.findByText("美图公司");

    await fireEvent.click(screen.getByRole("button", { name: "A股复盘" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("16:08 港股通收盘复盘日期证据错误");
    expect(screen.queryByText("布鲁可")).toBeNull();
  });

  it("scrolls to and focuses the review top when the 16:08 node is opened", async () => {
    let scrolledElement: Element | undefined;
    let focusedElement: Element | undefined;
    const scrollIntoView = vi.fn(function (this: Element) {
      scrolledElement = this;
    });
    const focus = vi.fn(function (this: Element) {
      focusedElement = this;
    });
    const scrollDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollIntoView");
    const focusDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "focus");
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: scrollIntoView });
    Object.defineProperty(HTMLElement.prototype, "focus", { configurable: true, value: focus });
    try {
      vi.stubGlobal("fetch", vi.fn(async (url: string) => {
        if (url === "/api/v1/runs/date-list") {
          return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
        }
        if (url === "/api/v3/review?date=20260730") return jsonResponse(closeReview);
        if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(referenceStage);
        return jsonResponse(blockedPool);
      }));
      render(App);
      await screen.findByText("美图公司");

      await fireEvent.click(screen.getByText("9. 16:08 港股通正式收盘：0.2 × 七阶段 Top20").closest("button")!);

      const hkPanel = await waitFor(() => {
        const panel = document.getElementById("hkCloseReviewPanel");
        expect(panel).not.toBeNull();
        return panel!;
      });
      await waitFor(() => expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "start" }));
      expect(focus).toHaveBeenCalledWith({ preventScroll: true });
      expect(hkPanel.id).toBe("hkCloseReviewPanel");
      expect(scrolledElement).toBe(hkPanel);
      expect(focusedElement).toBe(hkPanel);
    } finally {
      if (scrollDescriptor) Object.defineProperty(HTMLElement.prototype, "scrollIntoView", scrollDescriptor);
      else delete (HTMLElement.prototype as unknown as { scrollIntoView?: unknown }).scrollIntoView;
      if (focusDescriptor) Object.defineProperty(HTMLElement.prototype, "focus", focusDescriptor);
      else delete (HTMLElement.prototype as unknown as { focus?: unknown }).focus;
    }
  });

  it("exposes the 16:08 tile as the direct control for the review chart panel", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url === "/api/v3/review?date=20260730") return jsonResponse(closeReview);
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(referenceStage);
      return jsonResponse(blockedPool);
    }));
    render(App);
    await screen.findByText("美图公司");

    const reviewTile = screen.getByRole("button", { name: /9\. 16:08 港股通正式收盘：0\.2 × 七阶段 Top20/ });
    expect(reviewTile.tagName).toBe("BUTTON");
    expect(reviewTile.getAttribute("aria-controls")).toBe("closeReviewPanel");
    expect(reviewTile.getAttribute("aria-expanded")).toBe("false");

    await fireEvent.click(reviewTile);

    const reviewPanel = await screen.findByRole("region", { name: "16:08 港股通收盘复盘" });
    expect(reviewPanel.id).toBe("closeReviewPanel");
    expect(reviewPanel.getAttribute("tabindex")).toBe("-1");
    expect(reviewTile.getAttribute("aria-expanded")).toBe("true");
  });

  it("does not label an incomplete close review as loaded", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url === "/api/v3/review?date=20260730") return jsonResponse(closeReview);
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(referenceStage);
      return jsonResponse(blockedPool);
    }));
    render(App);
    await screen.findByText("美图公司");

    await fireEvent.click(screen.getByRole("button", { name: "A股复盘" }));
    await waitFor(() => expect(screen.getByText("收盘复盘")).toBeTruthy());
    expect(screen.queryByText("已加载指定日期复盘")).toBeNull();
    expect(screen.getByText("复盘证据未完成")).toBeTruthy();
  });

  it("shows an explicit unknown stock name for stage and pool rows without names", async () => {
    const missingStage = structuredClone(referenceStage) as any;
    missingStage.unified_rows = [{
      ...missingStage.unified_rows[0],
      name: "",
      stock_name: "",
    }];
    missingStage.selected_hk_rows = 1;
    missingStage.selected_total_rows = 1;
    const missingPoolRow = { market: "HK", code: "HK.01357", name: "", stock_name: "", pool_rank: 1 };
    const missingPool = {
      data_status: "PARTIAL_WITH_ROWS",
      trade_date: "20260730",
      rows: [missingPoolRow],
      pools: [{
        pool_id: "hkconnect_d1_top100",
        display_name: "港股通 D-1 预选池",
        market: "HK",
        pool_size: 1,
        returned_rows: 1,
        rows: [missingPoolRow],
      }],
      market_totals: { A: 0, HK: 1 },
      blocking_reasons: [],
    };
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(missingStage);
      if (url.startsWith("/api/v3/preselection-pools")) return jsonResponse(missingPool);
      return jsonResponse(taskStatus);
    }));

    render(App);

    expect((await screen.findAllByText("股票名称不可确认")).length).toBeGreaterThanOrEqual(2);
  });

  it("labels an exact-date imported reference close review as loaded", async () => {
    const imported = structuredClone(closeReview) as any;
    imported.reference_snapshot = true;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url === "/api/v3/review?date=20260730") return jsonResponse(imported);
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(referenceStage);
      return jsonResponse(blockedPool);
    }));
    render(App);
    await screen.findByText("美图公司");

    await fireEvent.click(screen.getByRole("button", { name: "A股复盘" }));
    await waitFor(() => expect(screen.getByText("已加载指定日期复盘")).toBeTruthy());
  });

  it("labels an exact-date native close review with a verified source hash as loaded", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url === "/api/v3/review?date=20260730") return jsonResponse(nativeCloseReview);
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(referenceStage);
      return jsonResponse(blockedPool);
    }));
    render(App);
    await screen.findByText("美图公司");

    await fireEvent.click(screen.getByRole("button", { name: "A股复盘" }));
    await waitFor(() => expect(screen.getByText("已加载指定日期复盘")).toBeTruthy());
  });

  it("does not let outer envelope evidence spoof an invalid nested source hash", async () => {
    const invalid = structuredClone(nativeCloseReview) as any;
    invalid.evidence_mode = "V3_5_NATIVE_PRODUCTION";
    invalid.close_source_sha256 = "a".repeat(64);
    invalid.market_reviews.HK.model_selection_review.close_source_sha256 = "A".repeat(64);
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url === "/api/v3/review?date=20260730") return jsonResponse(invalid);
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(referenceStage);
      return jsonResponse(blockedPool);
    }));
    render(App);
    await screen.findByText("美图公司");

    await fireEvent.click(screen.getByRole("button", { name: "A股复盘" }));
    await waitFor(() => expect(screen.getByText("复盘证据未完成")).toBeTruthy());
    expect(screen.queryByText("已加载指定日期复盘")).toBeNull();
  });

  it("explains a Stage7 shortfall with formal HK counts without padding rows", async () => {
    window.history.replaceState({}, "", "/?date=20260730&stage=STAGE_1445_1500");
    const stage7 = structuredClone(referenceStage) as any;
    stage7.stage = {
      stage_id: "STAGE_1445_1500", label: "14:45-15:00", window: "14:45-15:00",
      status: "PARTIAL_WITH_ROWS", display_status: "阶段输入部分可确认；仅展示实际观察行。",
    };
    stage7.markets = {
      A: { label: "A股", candidate_count: 10, source_rows: 10, requested_rows: 10 },
      HK: { label: "港股通", candidate_count: 9, source_rows: 9, requested_rows: 651 },
    };
    stage7.unified_rows = Array.from({ length: 19 }, (_, index) => ({
      market: index < 10 ? "A" : "HK", code: `${index < 10 ? "A" : "HK"}.${String(index + 1).padStart(5, "0")}`,
      name: `候选${index + 1}`, rank: index + 1,
    }));
    stage7.selected_a_rows = 10;
    stage7.selected_hk_rows = 9;
    stage7.selected_total_rows = 19;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(stage7);
      return jsonResponse(blockedPool);
    }));
    render(App);
    expect(await screen.findByText("最多10 / 实际9 · 请求651 / 可确认行9 / 阶段候选9 · PARTIAL_WITH_ROWS")).toBeTruthy();
    expect(screen.getAllByText(/港股通/).length).toBeGreaterThan(0);
    expect(screen.queryByText("HK.00010 · 排名 10")).toBeNull();
  });

  it("keeps a missing selected date local instead of falling back", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({
          default_date: "20260730",
          stage_dates: ["20260730"],
          review_dates: ["20260730", "20260729"],
          future_target_dates: [],
        });
      }
      if (url === "/api/v3/review?date=20260730") {
        return jsonResponse({
          trade_date: "20260730",
          market_reviews: { A: {
            status: "NOT_MATERIALIZED", headline: "A-share review", market_regime: "CANNOT_CONFIRM", risk_tone: "CANNOT_CONFIRM",
            big_picture: [], mainlines: [], core_stocks: [], observation_pool: [], next_day_trigger_tree: [], quality_gate: [],
            cannot_confirm: ["A_SHARE_REVIEW_NOT_MATERIALIZED"], production_allowed: false, buy_gate_updated: false, orders_sent: false,
          }, HK: { model_selection_review: {
            status: "BLOCKED_CLOSE_DATA",
            models: {},
            stage_union: { evidence_status: "MISSING" },
            close_top20: [],
            cannot_confirm: ["HKCONNECT_DAILY_REVIEW_NOT_FOUND"],
          } } }, production_allowed: false, buy_gate_updated: false, orders_sent: false,
        });
      }
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(referenceStage);
      return jsonResponse(blockedPool);
    }));
    render(App);
    await screen.findByText("美图公司");

    await fireEvent.click(screen.getByText("9. 16:08 港股通正式收盘：0.2 × 七阶段 Top20").closest("button")!);

    expect(await screen.findByText("该交易日复盘尚未生成")).toBeTruthy();
    expect(screen.getByText("A_SHARE_REVIEW_NOT_MATERIALIZED")).toBeTruthy();
    expect(vi.mocked(fetch)).not.toHaveBeenCalledWith("/api/v3/review?date=20260729");
  });

  it("does not let a slow prior-date review overwrite the newly selected date", async () => {
    let resolveOldReview!: (response: ReturnType<typeof jsonResponse>) => void;
    const oldReviewResponse = new Promise<ReturnType<typeof jsonResponse>>((resolve) => { resolveOldReview = resolve; });
    const newerReview = structuredClone(closeReview);
    newerReview.trade_date = "20260729";
    newerReview.market_reviews.A.headline = "D29 exact review";
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260729", "20260730"], future_target_dates: [] });
      }
      if (url === "/api/v3/review?date=20260730") return oldReviewResponse;
      if (url === "/api/v3/review?date=20260729") return jsonResponse(newerReview);
      if (url.includes("/api/v3/workbench/stage")) return jsonResponse(referenceStage);
      return jsonResponse(blockedPool);
    }));
    render(App);
    await screen.findByText("美图公司");

    void fireEvent.click(screen.getByText("9. 16:08 港股通正式收盘：0.2 × 七阶段 Top20").closest("button")!);
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/v3/review?date=20260730"));
    await fireEvent.change(screen.getByLabelText("交易日（日历选择）"), { target: { value: "2026-07-29" } });
    expect(await screen.findByText("D29 exact review")).toBeTruthy();

    resolveOldReview(jsonResponse(closeReview));
    await waitFor(() => expect(screen.getByText("D29 exact review")).toBeTruthy());
    expect(screen.queryByText("A-share review")).toBeNull();
  });

  it("matches the old V3 native calendar bounds and keeps all three date classes isolated", async () => {
    const historicalStage = {
      ...structuredClone(referenceStage),
      trade_date: "20260729",
      unified_rows: [{
        ...structuredClone(referenceStage.unified_rows[0]),
        code: "HK.00029",
        name: "仅属于20260729",
      }],
      selected_a_rows: 0,
      selected_hk_rows: 1,
      selected_total_rows: 1,
    };
    const emptyStage = {
      ...structuredClone(referenceStage),
      trade_date: "20260731",
      unified_rows: [],
      selected_a_rows: 0,
      selected_hk_rows: 0,
      selected_total_rows: 0,
      selection_mode: "V3_5_NATIVE_STAGE_SCORE_V1",
      reference_snapshot: false,
    };
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({
          default_date: "20260730",
          stage_dates: ["20260730"],
          review_dates: ["20260729"],
          future_target_dates: ["20260731"],
        });
      }
      if (url.includes("/api/v3/workbench/stage") && url.includes("date=20260730")) {
        return jsonResponse(referenceStage);
      }
      if (url.includes("/api/v3/workbench/stage") && url.includes("date=20260729")) {
        return jsonResponse(historicalStage);
      }
      if (url.includes("/api/v3/workbench/stage")) return jsonResponse(emptyStage);
      return jsonResponse(blockedPool);
    }));
    render(App);

    const dateInput = screen.getByLabelText("交易日（日历选择）") as HTMLInputElement;
    await waitFor(() => expect(dateInput.value).toBe("2026-07-30"));
    expect(dateInput.min).toBe("2026-07-29");
    expect(dateInput.max).toBe("2026-07-31");
    expect(dateInput.hasAttribute("list")).toBe(false);
    expect(document.querySelector("datalist")).toBeNull();

    await fireEvent.change(dateInput, {
      target: { value: "2026-07-29" },
    });
    await waitFor(() => {
      expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/v3/preselection-pools?date=20260729&limit=200");
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        "/api/v3/workbench/stage?date=20260729&stage=STAGE_0925&limit=50",
      );
      expect(screen.getByText("仅属于20260729")).toBeTruthy();
      expect(screen.queryByText("美图公司")).toBeNull();
    });

    await fireEvent.change(dateInput, {
      target: { value: "2026-07-31" },
    });
    await waitFor(() => {
      expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/v3/preselection-pools?date=20260731&limit=200");
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        "/api/v3/workbench/stage?date=20260731&stage=STAGE_0925&limit=50",
      );
      expect(screen.queryByText("仅属于20260729")).toBeNull();
      expect(screen.queryByText("美图公司")).toBeNull();
    });

    await fireEvent.change(dateInput, {
      target: { value: "2026-07-28" },
    });
    expect(dateInput.validationMessage).toBe("请选择日历中的有效交易日");
    expect(dateInput.value).toBe("2026-07-31");
    expect(vi.mocked(fetch)).not.toHaveBeenCalledWith("/api/v3/preselection-pools?date=20260728&limit=200");
  });

  it("keeps the ensure result visible after reloading the stage snapshot", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string, options?: RequestInit) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({
          default_date: "20260730",
          stage_dates: ["20260730"],
          future_target_dates: [],
        });
      }
      if (options?.method === "POST") {
        return jsonResponse({ ok: true, ensure_status: "ALREADY_COMPLETE" });
      }
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(referenceStage);
      return jsonResponse(blockedPool);
    }));
    render(App);
    await screen.findByText("美图公司");

    await fireEvent.click(screen.getByRole("button", { name: "运行 / 恢复当前阶段" }));

    expect(await screen.findByText("最近运行：ALREADY_COMPLETE")).toBeTruthy();
  }, 20_000);

  it("renders V3 source names and truthful truncated A-share summary counts", async () => {
    const sourceRow = {
      market: "A",
      symbol: "A.002446",
      stock_name: "盛路通信",
      display_name: "盛路通信（选）",
      source_tag: "V192_SELECTOR",
      source_tags: "（选）",
      source_lanes: "selector_lane",
      pool_rank: 1,
      pool_score: 10.2,
      signal_date: "20260814",
    };
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260817", stage_dates: ["20260817"], future_target_dates: [] });
      }
      if (url === "/api/v3/research/dates") return jsonResponse({ research_dates: [] });
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(referenceStage);
      return jsonResponse({
        data_status: "PARTIAL_WITH_ROWS",
        trade_date: "20260730",
        market_totals: { A: 203, HK: 0 },
        pools: [{
          pool_id: "a_d1_premarket_pool",
          display_name: "A股 D-1 主预选池",
          market: "A",
          pool_size: 1,
          rows: [sourceRow],
        }],
        a_all_pool_rows: [sourceRow],
        rows: [sourceRow],
        blocking_reasons: [],
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(App);

    expect((await screen.findAllByText("盛路通信（选）")).length).toBeGreaterThan(0);
    const summary = await screen.findByRole("region", { name: "A股所有预选池汇总" });
    expect(within(summary).getByText("当前显示 1 / 共 203 条")).toBeTruthy();
    expect(within(summary).getByText("盛路通信（选）")).toBeTruthy();
    const sourceCell = within(summary).getByText("（选）").closest("td");
    expect(sourceCell?.textContent).toBe("（选）");
  });

  it("keeps an explicit future URL date across the date catalog and every date-scoped view", async () => {
    const targetStage = {
      ...structuredClone(referenceStage),
      trade_date: "20260820",
      unified_rows: [{
        ...structuredClone(referenceStage.unified_rows[0]),
        market: "A",
        code: "A.000001",
        name: "Target A",
      }],
      selected_a_rows: 1,
      selected_hk_rows: 0,
      selected_total_rows: 1,
    };
    const targetPool = {
      data_status: "PARTIAL_WITH_ROWS",
      trade_date: "20260820",
      rows: [],
      a_all_pool_rows: [{
        market: "A",
        symbol: "A.000001",
        stock_name: "Target A",
        pool_rank: 1,
        signal_date: "20260819",
      }],
      pools: [
        {
          pool_id: "a_d1_premarket_pool",
          display_name: "A股 D-1 预选池",
          market: "A",
          pool_size: 1,
          rows: [{
            market: "A",
            symbol: "A.000001",
            stock_name: "Target A",
            pool_rank: 1,
            signal_date: "20260819",
          }],
          status: "READY_WITH_ROWS",
        },
        { pool_id: "hkconnect_d1_top100", display_name: "港股通 D-1 预选池", market: "HK", pool_size: 0, rows: [], status: "CANNOT_CONFIRM" },
      ],
      market_totals: { A: 1, HK: 0 },
      blocking_reasons: [],
      production_allowed: false,
      buy_gate_updated: false,
      orders_sent: false,
    };
    const futureResearch = {
      status: "NOT_MATERIALIZED",
      research_date: "20260820",
      reason: "RESEARCH_LANE_SNAPSHOT_NOT_FOUND",
      production_allowed: false,
      buy_gate_updated: false,
      orders_sent: false,
    };
    const fetchMock = vi.fn(async (url: string, options?: RequestInit) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({
          system_date: "20260820",
          default_date: "20260818",
          dates: ["20260818", "20260820"],
          stage_dates: ["20260818"],
          review_dates: [],
          research_dates: [],
          future_target_dates: [],
        });
      }
      if (url === "/api/v3/research/dates") return jsonResponse({ research_dates: [] });
      if (url === "/api/v3/research/lane?research_date=20260820") return jsonResponse(futureResearch);
      if (url === "/api/v3/tasks/status?date=20260820") return jsonResponse(taskStatus);
      if (url === "/api/v3/preselection-pools?date=20260820&limit=200") return jsonResponse(targetPool);
      if (url === "/api/v3/workbench/stage?date=20260820&stage=STAGE_0925&limit=50") return jsonResponse(targetStage);
      if (options?.method === "POST") return jsonResponse({ ok: true, ensure_status: "ALREADY_COMPLETE" });
      return jsonResponse(blockedPool);
    });
    window.history.replaceState({}, "", "/?date=20260820&date_anchor=20260818");
    vi.stubGlobal("fetch", fetchMock);

    render(App);

    const dateInput = screen.getByLabelText("交易日（日历选择）") as HTMLInputElement;
    await waitFor(() => expect(dateInput.value).toBe("2026-08-20"));
    expect(window.location.search).toBe("?date=20260820&date_anchor=20260818");
    expect((await screen.findAllByText("Target A")).length).toBeGreaterThan(0);
    expect(fetchMock).toHaveBeenCalledWith("/api/v3/preselection-pools?date=20260820&limit=200");
    expect(fetchMock).toHaveBeenCalledWith("/api/v3/workbench/stage?date=20260820&stage=STAGE_0925&limit=50");

    await fireEvent.click(screen.getByRole("button", { name: "研报决策台" }));
    expect(await screen.findByText("NOT_MATERIALIZED")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith("/api/v3/research/lane?research_date=20260820");

    await fireEvent.click(screen.getByRole("button", { name: "任务状态" }));
    expect((await screen.findByRole("alert")).textContent).toContain("EXECUTION_RECEIPT_MISSING:hourly_research");
    expect(fetchMock).toHaveBeenCalledWith("/api/v3/tasks/status?date=20260820", expect.anything());
  }, 20_000);
});
