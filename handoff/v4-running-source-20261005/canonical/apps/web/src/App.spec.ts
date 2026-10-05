import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App.vue";

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

  it("restores the old V3 header controls and nineteen-node timeline", async () => {
    render(App);
    expect(await screen.findByRole("heading", { level: 1, name: "V4 阶段选股" })).toBeTruthy();
    const dateInput = screen.getByLabelText("交易日（日历选择）");
    expect(dateInput.getAttribute("type")).toBe("date");
    expect(dateInput.hasAttribute("list")).toBe(false);
    expect(document.querySelector("datalist")).toBeNull();
    expect(screen.getByRole("combobox", { name: "阶段" })).toBeTruthy();
    for (const name of ["刷新快照", "阶段选股", "D-1 预选池", "研报决策台", "经理选股工作台", "任务状态", "A股复盘"]) {
      expect(screen.getByRole("button", { name })).toBeTruthy();
    }
    expect(within(screen.getByRole("region", { name: "七阶段上下文" })).getAllByRole("button")).toHaveLength(19);
    expect(screen.getByText("19. 21:15 8871 刷新与页面验收")).toBeTruthy();
  }, 10_000);

  it("shows verified Stage backfill provenance and keeps missing runner receipt explicit", async () => {
    const recovered = {
      ...referenceStage,
      reference_snapshot: false,
      response_source: "SHARED_STAGE_CENTER",
      selected_a_rows: 1,
      selected_total_rows: 3,
      unified_rows: [
        ...referenceStage.unified_rows,
        { market: "A", code: "A.000001", name: "回补候选", rank: 1 },
      ],
      markets: {
        ...referenceStage.markets,
        A: {
          ...referenceStage.markets.A,
          selection_mode: "BACKFILL",
          backfill_run_id: "recovery-r3",
          backfill_run_ids: ["recovery-r3", "recovery-r3-copy"],
          selection_manifest_receipt_verified: true,
          runner_receipt_verified: false,
          runner_receipt_status: "CANNOT_CONFIRM",
          cannot_confirm: ["BACKFILL_NAMESPACE_CONFLICT"],
        },
      },
    };
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url.startsWith("/api/v3/tasks/status")) return jsonResponse(taskStatus);
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(recovered);
      return jsonResponse(blockedPool);
    }));

    render(App);

    expect(await screen.findByText(/历史回补 BACKFILL · recovery-r3/)).toBeTruthy();
    expect(screen.getByText(/selection manifest\/receipt 已验证/)).toBeTruthy();
    expect(screen.getByText(/runner receipt CANNOT_CONFIRM/)).toBeTruthy();
    expect(screen.getByText("回补候选")).toBeTruthy();
    expect(screen.getByText(/BACKFILL_NAMESPACE_CONFLICT/)).toBeTruthy();
  });

  it("routes the selected date to the internal research review entry", async () => {
    render(App);

    const entry = await screen.findByRole("button", { name: "研究复盘" });
    expect(entry.classList.contains("entry-nav-link")).toBe(true);
    const original = screen.getByRole("link", { name: "原版 Vibe · 8910" });
    expect(original.getAttribute("href")).toBe("http://127.0.0.1:8910/a-share/review");
    expect(original.getAttribute("rel")).toBe("noopener noreferrer");
  });

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
    expect(screen.getByRole("button", { name: "公众号" }).getAttribute("aria-pressed")).toBe("false");
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

  it("shows the first-screen global industry map and structured A/HK candidate columns", async () => {
    render(App);
    expect(await screen.findByText("美图公司")).toBeTruthy();
    expect(screen.getByRole("region", { name: "美股收盘板块涨跌幅" })).toBeTruthy();
    expect(document.querySelectorAll("[data-theme-row]")).toHaveLength(24);
    expect(screen.getByText("HK.01357 · 排名 1")).toBeTruthy();
    expect(screen.getByText("82")).toBeTruthy();
    expect(screen.getByText("13.065%")).toBeTruthy();
    expect(screen.getAllByText("09:30初步筛选").length).toBeGreaterThan(0);
    expect(screen.getAllByText("09:35").length).toBeGreaterThan(0);
    expect(screen.getByText("参考快照 · WATCH_ONLY")).toBeTruthy();
    // The static safety note is rendered only after the API payload passes
    // its exact-date, canonical-map and safety-flag validation.  This
    // workbench fixture has no US snapshot directory, so the map must keep
    // its CANNOT_CONFIRM state without presenting a validated guarantee.
    expect(screen.queryByText(/RESEARCH_ONLY=true/)).toBeNull();
    expect(screen.getByText(/只读观察，不打开 BUY gate/)).toBeTruthy();
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
        expect.objectContaining({ cache: "no-store" }),
      );
    });

    await fireEvent.update(screen.getByRole("combobox", { name: "阶段" }), "STAGE_0930_0935");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/v3/workbench/stage?date=20260730&stage=STAGE_0930_0935&limit=50",
      expect.objectContaining({ cache: "no-store" }),
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
    expect(within(screen.getByRole("region", { name: "A股候选" })).getByText("50 条")).toBeTruthy();
    expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      "/api/v3/workbench/stage?date=20260730&stage=STAGE_0925&limit=50",
      expect.objectContaining({ cache: "no-store" }),
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
    replayStage.stage.stage_id = "STAGE_0930_0935";
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
      if (url.startsWith("/api/v3/workbench/stage")) {
        const stage = structuredClone(replayStage);
        stage.stage.stage_id = new URL(url, window.location.origin).searchParams.get("stage") || "STAGE_0925";
        return jsonResponse(stage);
      }
      return jsonResponse(blockedPool);
    }));
    render(App);
    expect(await screen.findByText("美图公司")).toBeTruthy();
    await fireEvent.update(screen.getByRole("combobox", { name: "阶段" }), "STAGE_0930_0935");
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      "/api/v3/workbench/stage?date=20260730&stage=STAGE_0930_0935&limit=50",
      expect.objectContaining({ cache: "no-store" }),
    ));
    expect(screen.queryByText(/缺证 6 项/)).toBeNull();
    await waitFor(() => expect(screen.getAllByText("支撑位").length).toBeGreaterThan(0));
    expect(screen.getAllByText("压力位").length).toBeGreaterThan(0);
    expect(screen.getAllByText("失效位").length).toBeGreaterThan(0);
    expect(screen.getByText("0.343%")).toBeTruthy();
    expect(screen.queryByText(/待补字段/)).toBeNull();
  });

  it("renders the old V3 A-share post-open fields from the migrated workbench", async () => {
    window.history.replaceState({}, "", "/?date=20260730&stage=STAGE_0930_0935");
    const postOpenStage = structuredClone(referenceStage);
    postOpenStage.stage.stage_id = "STAGE_0930_0935";
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
    expect(screen.getByText("未生成/待补齐")).toBeTruthy();
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
    expect(within(wechat).getByText(/全文提及不直接进入阶段候选或评分/)).toBeTruthy();
    expect(within(wechat).getByRole("button", { name: "打开公众号研究归档" })).toBeTruthy();
  });

  it("does not turn an incomplete zero-row pool into a verified empty pool", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(referenceStage);
      return jsonResponse({
        data_status: "PARTIAL_WITH_ROWS",
        trade_date: "20260730",
        market_totals: { A: 0, HK: 0 },
        pools: [
          {
            pool_id: "a_d1_premarket_pool",
            display_name: "A股 D-1 主预选池",
            market: "A",
            pool_size: 0,
            returned_rows: 0,
            complete: false,
            status: "CANNOT_CONFIRM",
            cannot_confirm: ["A_SHARE_V192_PREMARKET_POOL_V3_NOT_MATERIALIZED"],
            rows: [],
          },
          {
            pool_id: "a_d1_stage7_fenshi_review_pool",
            display_name: "A股 D-1 Stage7/分时复盘池",
            market: "A",
            pool_size: 0,
            returned_rows: 0,
            complete: true,
            status: "READY_EMPTY",
            rows: [],
          },
          {
            pool_id: "hkconnect_d1_top100",
            display_name: "港股通 D-1 预选池",
            market: "HK",
            pool_size: 1,
            returned_rows: 1,
            complete: true,
            status: "READY_WITH_ROWS",
            rows: [{ market: "HK", symbol: "HK.00001", stock_name: "保留的已验证行", pool_rank: 1 }],
          },
        ],
        a_all_pool_rows: [],
        rows: [],
        blocking_reasons: [],
      });
    }));

    render(App);

    const incomplete = await screen.findByRole("region", { name: "A股 D-1 主预选池" });
    expect(within(incomplete).getByText("未生成/待补齐")).toBeTruthy();
    expect(within(incomplete).queryByText("完整 0 条")).toBeNull();

    await waitFor(() => {
      const verifiedEmpty = screen.getByRole("region", { name: "A股 D-1 Stage7/分时复盘池" });
      expect(within(verifiedEmpty).getByText("完整 0 条")).toBeTruthy();
    });

    const retainedRows = screen.getByRole("region", { name: "港股通 D-1 预选池" });
    expect(within(retainedRows).getByText("保留的已验证行")).toBeTruthy();
    expect(within(retainedRows).getByText("完整 1 条")).toBeTruthy();

    const emptyWechat = screen.getByRole("region", { name: "公众号股票池" });
    expect(within(emptyWechat).getByText(/报告与全文提及尚未接入阶段候选/)).toBeTruthy();
    expect(within(emptyWechat).queryByRole("table")).toBeNull();
    expect(within(emptyWechat).getByRole("button", { name: "打开公众号研究归档" })).toBeTruthy();
    const emptyBaimao = screen.getByRole("region", { name: "白毛卡点研究池" });
    expect(within(emptyBaimao).getByText(/暂无已核验行/)).toBeTruthy();
    expect(within(emptyBaimao).queryByRole("table")).toBeNull();
  });

  it("opens the exact-date research archive from an unmaterialized公众号 pool", async () => {
    window.history.replaceState({}, "", "/?date=20260917&stage=STAGE_0925");
    const archiveLane = {
      schema_version: "v3_5.research_lane.v1",
      status: "NOT_MATERIALIZED",
      endpoint_mode: "EXACT",
      research_date: "20260917",
      reason: "RESEARCH_LANE_SNAPSHOT_NOT_FOUND",
      write_policy: "read_only",
      recommendation_status: "RESEARCH_ONLY",
      production_allowed: false,
      buy_gate_updated: false,
      orders_sent: false,
    };
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260917", navigation_date: "20260917", stage_dates: ["20260917"], research_dates: ["20260917"], future_target_dates: [] });
      }
      if (url === "/api/v3/research/dates") return jsonResponse({ research_dates: ["20260917"] });
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse({ ...referenceStage, trade_date: "20260917" });
      if (url === "/api/v3/research/lane?research_date=20260917") return jsonResponse(archiveLane);
      if (url.startsWith("/api/v3/research/wechat/materials?")) {
        return jsonResponse({
          schema_version: "v4.wechat_materials.stage_a.v1",
          status: "NOT_INDEXED",
          query: { date: "20260917", date_basis: "article", q: "", limit: 20 },
          timezone: "Asia/Shanghai",
          items: [], total: 0, returned: 0, next_cursor: null, index_revision: null,
          RESEARCH_ONLY: true, WATCH_ONLY: true, NO_BUY_GATE: true,
          production_allowed: false, buy_gate_updated: false, orders_sent: false,
        });
      }
      return jsonResponse({
        data_status: "PARTIAL_WITH_ROWS",
        trade_date: "20260917",
        market_totals: { A: 0, HK: 0 },
        pools: [
          { pool_id: "wechat_public_account_v3_preselect", status: "CANNOT_CONFIRM", pool_size: 0, returned_rows: 0, rows: [] },
          { pool_id: "a_share_baimao_research_map", status: "CANNOT_CONFIRM", pool_size: 0, returned_rows: 0, rows: [] },
        ],
        a_all_pool_rows: [], rows: [], blocking_reasons: [],
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(App);
    await screen.findByText("美图公司");
    const wechat = await screen.findByRole("region", { name: "公众号股票池" });
    await fireEvent.click(within(wechat).getByRole("button", { name: "打开公众号研究归档" }));

    await screen.findByRole("region", { name: "研报决策台" });
    await waitFor(() => expect((screen.getByLabelText("交易日（日历选择）") as HTMLInputElement).value).toBe("2026-09-17"));
    expect(fetchMock).toHaveBeenCalledWith("/api/v3/research/lane?research_date=20260917");
    expect(screen.getByTestId("research-date-identity").textContent).toContain("20260917");
    const archive = await screen.findByRole("region", { name: "公众号研究归档" });
    expect(archive).toBeTruthy();
    expect(screen.getByRole("button", { name: "公众号" }).getAttribute("aria-pressed")).toBe("true");
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/api/v3/research/wechat/materials?") && String(url).includes("date=20260917"))).toBe(true);

    await fireEvent.click(screen.getByRole("button", { name: "研报决策台" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "公众号" }).getAttribute("aria-pressed")).toBe("false"));
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
    expect(container.contains(closeButton)).toBe(false); // Review owns the first screen, not the stage timeline.
    expect(reviewEntry.classList.contains("active")).toBe(true);
    expect(container.contains(openingButton)).toBe(false);
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
        expect.objectContaining({ cache: "no-store" }),
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
        expect.objectContaining({ cache: "no-store" }),
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
    window.history.replaceState({}, "", "/?date=20260817&stage=STAGE_0925");
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
        trade_date: "20260817",
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
    expect(alert.textContent).toContain("日期证据错误");
    expect(screen.queryByRole("region", { name: "A股所有预选池汇总" })).toBeNull();
  });

  it("rejects a preselection response with missing date evidence", async () => {
    const missingPool = { ...blockedPool } as Record<string, unknown>;
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
    expect(alert.textContent).toContain("日期证据错误");
    expect(screen.queryByRole("region", { name: "A股所有预选池汇总" })).toBeNull();
  });

  it("rejects a close review response whose trade date is wrong", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url === "/api/v3/review?date=20260730") return jsonResponse({ ...closeReview, trade_date: "20260729" });
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(referenceStage);
      return jsonResponse({ ...blockedPool, trade_date: "20260730" });
    }));

    render(App);
    await screen.findByText("美图公司");
    await fireEvent.click(screen.getByRole("button", { name: "A股复盘" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("日期证据错误");
    expect(screen.queryByText("A-share review")).toBeNull();
  });

  it("rejects a close review response with missing trade date", async () => {
    const missingDate = { ...closeReview } as Record<string, unknown>;
    delete missingDate.trade_date;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url === "/api/v3/review?date=20260730") return jsonResponse(missingDate);
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(referenceStage);
      return jsonResponse({ ...blockedPool, trade_date: "20260730" });
    }));

    render(App);
    await screen.findByText("美图公司");
    await fireEvent.click(screen.getByRole("button", { name: "A股复盘" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("日期证据错误");
    expect(screen.queryByText("A-share review")).toBeNull();
  });

  it("keeps an explicit historical date ahead of date_anchor and bypasses the HTTP cache", async () => {
    window.history.replaceState({}, "", "/?date=20260825&stage=STAGE_0925&date_anchor=20260826");
    const exactStage = structuredClone(referenceStage) as any;
    exactStage.trade_date = "20260825";
    exactStage.stage.stage_id = "STAGE_0925";
    exactStage.stage.status = "PARTIAL_WITH_ROWS";
    const fetchMock = vi.fn(async (url: string, _options?: RequestInit) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260826", stage_dates: ["20260826"], future_target_dates: [] });
      }
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(exactStage);
      return jsonResponse({ ...blockedPool, trade_date: "20260825" });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(App);

    const dateInput = screen.getByLabelText("交易日（日历选择）") as HTMLInputElement;
    await waitFor(() => expect(dateInput.value).toBe("2026-08-25"));
    const stageCalls = fetchMock.mock.calls.filter(([url]) => url.startsWith("/api/v3/workbench/stage"));
    expect(stageCalls.length).toBeGreaterThan(0);
    expect(stageCalls.every(([url, options]) => {
      const requestUrl = new URL(url, window.location.origin);
      return requestUrl.searchParams.get("date") === "20260825"
        && requestUrl.searchParams.get("stage") !== "20260826"
        && (options as RequestInit | undefined)?.cache === "no-store";
    })).toBe(true);
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("date_anchor=20260826"))).toBe(false);
  });

  it("lets one same-date revalidation replace an accepted but stale primary snapshot", async () => {
    window.history.replaceState({}, "", "/?date=20260825&stage=STAGE_0925");
    const oldStage = structuredClone(referenceStage) as any;
    oldStage.trade_date = "20260825";
    oldStage.unified_rows = [{ ...oldStage.unified_rows[0], code: "HK.OLD", name: "旧阶段快照" }];
    oldStage.selected_hk_rows = 1;
    oldStage.selected_total_rows = 1;
    oldStage.markets.HK.candidate_count = 1;
    const refreshedStage = structuredClone(oldStage) as any;
    refreshedStage.unified_rows = [{ ...oldStage.unified_rows[0], code: "HK.NEW", name: "同日重验证快照" }];
    let primaryStageCalls = 0;
    let resolveRefresh!: (response: ReturnType<typeof jsonResponse>) => void;
    const refreshResponse = new Promise<ReturnType<typeof jsonResponse>>((resolve) => { resolveRefresh = resolve; });
    const fetchMock = vi.fn(async (url: string, options?: RequestInit) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260825", stage_dates: ["20260825"], future_target_dates: [] });
      }
      if (url.startsWith("/api/v3/workbench/stage")) {
        const stageId = new URL(url, window.location.origin).searchParams.get("stage");
        if (stageId === "STAGE_0925") {
          primaryStageCalls += 1;
          if (primaryStageCalls === 1) return jsonResponse(oldStage);
          return refreshResponse;
        }
        const stage = structuredClone(oldStage) as any;
        stage.stage.stage_id = stageId;
        return jsonResponse(stage);
      }
      return jsonResponse({ ...blockedPool, trade_date: "20260825" });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(App);

    expect(await screen.findByText("旧阶段快照")).toBeTruthy();
    await waitFor(() => expect(primaryStageCalls).toBe(2));
    resolveRefresh(jsonResponse(refreshedStage));
    expect(await screen.findByText("同日重验证快照")).toBeTruthy();
    expect(screen.queryByText("旧阶段快照")).toBeNull();
  });

  it("settles every timeline cell when the selected stage request fails", async () => {
    window.history.replaceState({}, "", "/?date=20260825&stage=STAGE_0925");
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260825", stage_dates: ["20260825"], future_target_dates: [] });
      }
      if (url.startsWith("/api/v3/workbench/stage")) return { ok: false, json: async () => ({}) };
      return jsonResponse({ ...blockedPool, trade_date: "20260825" });
    }));

    render(App);

    const timeline = await screen.findByRole("region", { name: "七阶段上下文" });
    await screen.findByRole("alert");
    await waitFor(() => {
      const stageButtons = within(timeline).getAllByRole("button").slice(0, 8);
      expect(stageButtons.every((button) => !button.textContent?.includes("读取中"))).toBe(true);
    });
  });

  it("keeps natural and controlled recovery evidence visibly separate", async () => {
    window.history.replaceState({}, "", "/?date=20260825&stage=STAGE_0925");
    const lineageStage = structuredClone(referenceStage) as any;
    lineageStage.trade_date = "20260825";
    lineageStage.stage.stage_id = "STAGE_0925";
    lineageStage.stage_lineage = {
      natural: {
        label: "ORIGINAL_NATURAL_RUN",
        status: "CANNOT_CONFIRM",
        origin: "ORIGINAL_NATURAL_RUN",
        receipt_sha256: "feb1c1c61b0c0608b5ddf73ccaf7a54137994c9d78921d086f9d80ef7042f530",
        write_performed: false,
      },
      recovery: {
        label: "CONTROLLED_RECOVERY",
        status: "PARTIAL_WITH_ROWS",
        origin: "CONTROLLED_RECOVERY",
        receipt_sha256: "recovery-receipt-sha-0925",
        write_performed: false,
        markets: { A: { selected_rows: 10 }, HK: { selected_rows: 10 } },
      },
      cannot_confirm: ["NATURAL_RECEIPT_CANNOT_CONFIRM"],
    };
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260825", stage_dates: ["20260825"], future_target_dates: [] });
      }
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(lineageStage);
      return jsonResponse({ ...blockedPool, trade_date: "20260825" });
    }));

    render(App);

    expect(await screen.findByText("ORIGINAL_NATURAL_RUN")).toBeTruthy();
    expect(screen.getByText("CONTROLLED_RECOVERY")).toBeTruthy();
    expect(screen.getByText("feb1c1c61b0c0608b5ddf73ccaf7a54137994c9d78921d086f9d80ef7042f530")).toBeTruthy();
    expect(screen.getByText("recovery-receipt-sha-0925")).toBeTruthy();
    expect(within(screen.getByRole("region", { name: "阶段运行血缘" })).getByText("status=CANNOT_CONFIRM")).toBeTruthy();
    expect(within(screen.getByRole("region", { name: "阶段运行血缘" })).getAllByText("write=false")).toHaveLength(2);
  });
});

// 0915 policy: original 8910 stays independent; V4 navigation is not a replacement.
describe("r3 preserved Vibe and explicit review focus", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
  function install(date = "20260915", explicit = false) {
    window.history.replaceState({}, "", explicit ? `/?date=${date}` : "/");
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") return jsonResponse({ default_date: "20260914", navigation_date: "20260915",
        navigation_timezone: "Asia/Shanghai", dates: ["20260915", "20260914"], stage_dates: ["20260914"], future_target_dates: [] });
      if (url.startsWith("/api/v3/review?")) return jsonResponse({ ...closeReview, trade_date: date });
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse({ ...referenceStage, trade_date: date });
      if (url === "/api/v3/research/dates") return jsonResponse({ research_dates: [], market_snapshot_dates: [] });
      return jsonResponse({ ...blockedPool, trade_date: date });
    }));
  }
  it("uses server Shanghai navigation day without upgrading evidence default", async () => {
    install(); render(App);
    await waitFor(() => expect((screen.getByLabelText("交易日（日历选择）") as HTMLInputElement).value).toBe("2026-09-15"));
    expect(screen.getByRole("heading", {level: 1}).textContent).toBe("V4 阶段选股");
    expect(document.body.textContent).not.toContain("8872");
    const link = screen.getByRole("link", {name: "原版 Vibe · 8910"});
    expect(link.getAttribute("href")).toBe("http://127.0.0.1:8910/a-share/review");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(vi.mocked(fetch).mock.calls.every(([url]) => !String(url).includes(":8910"))).toBe(true);
  });

  it("keeps date input, URL and date-bound requests on one exact date", async () => {
    install();
    render(App);
    const input = await screen.findByLabelText("交易日（日历选择）") as HTMLInputElement;
    await waitFor(() => expect(input.value).toBe("2026-09-15"));

    await fireEvent.change(input, { target: { value: "2026-09-14" } });
    await waitFor(() => expect(new URLSearchParams(window.location.search).get("date")).toBe("20260914"));
    expect(new URLSearchParams(window.location.search).get("stage")).toBe("STAGE_0925");
    expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/v3/preselection-pools?date=20260914&limit=200");

    cleanup();
    render(App);
    const reloaded = await screen.findByLabelText("交易日（日历选择）") as HTMLInputElement;
    await waitFor(() => expect(reloaded.value).toBe("2026-09-14"));
  });

  it("follows browser history date changes and issues only the new exact-date requests", async () => {
    install("20260915", true);
    render(App);
    const input = await screen.findByLabelText("交易日（日历选择）") as HTMLInputElement;
    await waitFor(() => expect(input.value).toBe("2026-09-15"));

    window.history.pushState({}, "", "/?date=20260914");
    window.dispatchEvent(new PopStateEvent("popstate"));
    await waitFor(() => expect(input.value).toBe("2026-09-14"));
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/v3/preselection-pools?date=20260914&limit=200"));

    window.history.pushState({}, "", "/?date=20260915");
    window.dispatchEvent(new PopStateEvent("popstate"));
    await waitFor(() => expect(input.value).toBe("2026-09-15"));
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/v3/preselection-pools?date=20260915&limit=200"));
  });

  it("restores the navigation date when browser history removes the date parameter", async () => {
    install("20260914", true);
    render(App);
    const input = await screen.findByLabelText("交易日（日历选择）") as HTMLInputElement;
    await waitFor(() => expect(input.value).toBe("2026-09-14"));

    window.history.pushState({}, "", "/");
    window.dispatchEvent(new PopStateEvent("popstate"));

    await waitFor(() => expect(input.value).toBe("2026-09-15"));
    expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/v3/preselection-pools?date=20260915&limit=200");
  });

  it("refreshes the exact-date D-1 pool when research view follows browser history", async () => {
    install("20260914", true);
    render(App);
    const input = await screen.findByLabelText("交易日（日历选择）") as HTMLInputElement;
    await waitFor(() => expect(input.value).toBe("2026-09-14"));
    await fireEvent.click(screen.getByRole("button", { name: "研报决策台" }));
    await waitFor(() => expect(screen.getByRole("region", { name: "研报决策台" })).toBeTruthy());

    window.history.pushState({}, "", "/?date=20260915");
    window.dispatchEvent(new PopStateEvent("popstate"));

    await waitFor(() => expect(input.value).toBe("2026-09-15"));
    expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/v3/preselection-pools?date=20260915&limit=200");
  });

  it("preserves explicit earlier date and highlights only the selected review focus", async () => {
    install("20260914", true); render(App);
    await waitFor(() => expect((screen.getByLabelText("交易日（日历选择）") as HTMLInputElement).value).toBe("2026-09-14"));
    const a = screen.getByRole("button", {name:"A股复盘"});
    const research = screen.getByRole("button", {name:"研究复盘"});
    await fireEvent.click(a);
    await waitFor(() => expect(document.querySelector("[data-review-focus='A']")).toBeTruthy());
    expect(a.classList.contains("active")).toBe(true); expect(research.classList.contains("active")).toBe(false);
    expect(screen.queryByRole("region", {name:"美股收盘板块涨跌幅"})).toBeNull();
    await fireEvent.click(research);
    await waitFor(() => expect(document.querySelector("[data-review-focus='research']")).toBeTruthy());
    expect(a.classList.contains("active")).toBe(false); expect(research.classList.contains("active")).toBe(true);
    expect(document.querySelector("[data-review-focus] [data-review-section]")?.getAttribute("data-review-section")).toBe("research");
    expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).startsWith("/api/v3/review?"))).toHaveLength(1);
  });
});

describe("weekend research natural-day navigation", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("keeps 0920 research exact while stage navigation returns to 0918", async () => {
    window.history.replaceState({}, "", "/?date=20260918");
    const dateList = {
      default_date: "20260918",
      navigation_date: "20260918",
      navigation_timezone: "Asia/Shanghai",
      dates: ["20260921", "20260918"],
      stage_dates: ["20260918"],
      research_dates: ["20260920", "20260918"],
      future_target_dates: ["20260921"],
    };
    const missingWeekendLane = {
      schema_version: "v3_5.research_lane.v1",
      status: "NOT_MATERIALIZED",
      endpoint_mode: "EXACT",
      research_date: "20260920",
      reason: "RESEARCH_LANE_SNAPSHOT_NOT_FOUND",
      write_policy: "read_only",
      recommendation_status: "RESEARCH_ONLY",
      production_allowed: false,
      buy_gate_updated: false,
      orders_sent: false,
    };
    const fetchMock = vi.fn(async (url: string, _options?: RequestInit) => {
      if (url === "/api/v1/runs/date-list") return jsonResponse(dateList);
      if (url === "/api/v3/research/dates") return jsonResponse({ research_dates: dateList.research_dates });
      if (url === "/api/v3/research/lane?research_date=20260920") return jsonResponse(missingWeekendLane);
      if (url.startsWith("/api/v3/workbench/stage")) {
        return jsonResponse({ ...referenceStage, trade_date: "20260918" });
      }
      return jsonResponse({ ...blockedPool, trade_date: "20260918" });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(App);
    await screen.findByText("美图公司");
    const input = screen.getByLabelText("交易日（日历选择）") as HTMLInputElement;

    await fireEvent.click(screen.getByRole("button", { name: "研报决策台" }));
    await screen.findByRole("region", { name: "研报决策台" });
    expect(new URLSearchParams(window.location.search).get("date")).toBe("20260918");
    expect(new URLSearchParams(window.location.search).get("view")).toBe("research");
    expect(new URLSearchParams(window.location.search).get("stage")).toBe(null);

    await fireEvent.change(input, { target: { value: "2026-09-20" } });

    await waitFor(() => expect(input.value).toBe("2026-09-20"));
    expect(screen.getByText("研究自然日")).toBeTruthy();
    expect(new URLSearchParams(window.location.search).get("date")).toBe("20260920");
    expect(new URLSearchParams(window.location.search).get("view")).toBe("research");
    expect(new URLSearchParams(window.location.search).get("stage")).toBe(null);
    expect(fetchMock).toHaveBeenCalledWith("/api/v3/research/lane?research_date=20260920");
    expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/v3/preselection-pools?date=20260920&limit=200")).toBe(false);

    cleanup();
    render(App);
    const reloadedInput = await screen.findByLabelText("交易日（日历选择）") as HTMLInputElement;
    await screen.findByRole("region", { name: "研报决策台" });
    await waitFor(() => expect(reloadedInput.value).toBe("2026-09-20"));
    expect(new URLSearchParams(window.location.search).get("date")).toBe("20260920");
    expect(new URLSearchParams(window.location.search).get("view")).toBe("research");
    expect(fetchMock).toHaveBeenCalledWith("/api/v3/research/lane?research_date=20260920");

    await fireEvent.click(screen.getByRole("button", { name: "阶段选股" }));
    await waitFor(() => expect(reloadedInput.value).toBe("2026-09-18"));
    expect(new URLSearchParams(window.location.search).get("date")).toBe("20260918");
    expect(new URLSearchParams(window.location.search).get("view")).toBe(null);
    expect(new URLSearchParams(window.location.search).get("stage")).toBe("STAGE_0925");
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/api/v3/workbench/stage?date=20260920"))).toBe(false);
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/api/v3/workbench/stage?date=20260918"))).toBe(true);
  });

  it("synchronizes research and stage modes in both browser history directions", async () => {
    const dateList = {
      default_date: "20260918",
      navigation_date: "20260918",
      navigation_timezone: "Asia/Shanghai",
      dates: ["20260921", "20260918"],
      stage_dates: ["20260918"],
      research_dates: ["20260920", "20260918"],
      future_target_dates: ["20260921"],
    };
    const missingWeekendLane = {
      schema_version: "v3_5.research_lane.v1",
      status: "NOT_MATERIALIZED",
      endpoint_mode: "EXACT",
      research_date: "20260920",
      reason: "RESEARCH_LANE_SNAPSHOT_NOT_FOUND",
      write_policy: "read_only",
      recommendation_status: "RESEARCH_ONLY",
      production_allowed: false,
      buy_gate_updated: false,
      orders_sent: false,
    };
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") return jsonResponse(dateList);
      if (url === "/api/v3/research/dates") return jsonResponse({ research_dates: dateList.research_dates });
      if (url === "/api/v3/research/lane?research_date=20260920") return jsonResponse(missingWeekendLane);
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse({ ...referenceStage, trade_date: "20260918" });
      return jsonResponse({ ...blockedPool, trade_date: "20260918" });
    });
    vi.stubGlobal("fetch", fetchMock);

    window.history.replaceState({}, "", "/?date=20260918&stage=STAGE_0925");
    render(App);
    const input = await screen.findByLabelText("交易日（日历选择）") as HTMLInputElement;
    await waitFor(() => expect(input.value).toBe("2026-09-18"));
    expect(screen.queryByRole("region", { name: "研报决策台" })).toBeNull();

    window.history.pushState({}, "", "/?date=20260920&view=research");
    window.dispatchEvent(new PopStateEvent("popstate"));
    await screen.findByRole("region", { name: "研报决策台" });
    await waitFor(() => expect(input.value).toBe("2026-09-20"));
    expect(new URLSearchParams(window.location.search).get("view")).toBe("research");
    expect(new URLSearchParams(window.location.search).get("stage")).toBe(null);

    window.history.pushState({}, "", "/?date=20260918&stage=STAGE_0925");
    window.dispatchEvent(new PopStateEvent("popstate"));
    await waitFor(() => expect(screen.queryByRole("region", { name: "研报决策台" })).toBeNull());
    await waitFor(() => expect(input.value).toBe("2026-09-18"));
    expect((screen.getByLabelText("阶段") as HTMLSelectElement).value).toBe("STAGE_0925");

    window.history.pushState({}, "", "/?date=20260920&view=research");
    window.dispatchEvent(new PopStateEvent("popstate"));
    await screen.findByRole("region", { name: "研报决策台" });
    await waitFor(() => expect(input.value).toBe("2026-09-20"));

    cleanup();
    window.history.replaceState({}, "", "/?date=20260920&view=research");
    render(App);
    const reloadedInput = await screen.findByLabelText("交易日（日历选择）") as HTMLInputElement;
    await screen.findByRole("region", { name: "研报决策台" });
    await waitFor(() => expect(reloadedInput.value).toBe("2026-09-20"));
    expect(new URLSearchParams(window.location.search).get("view")).toBe("research");
  });
});

describe("empty research catalogs preserve an explicit URL date", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("keeps the requested date and reaches the archive toolbar when both catalogs are empty", async () => {
    window.history.replaceState({}, "", "/?date=20260917&view=research");
    const lane = {
      schema_version: "v3_5.research_lane.v1",
      status: "NOT_MATERIALIZED",
      endpoint_mode: "EXACT",
      research_date: "20260917",
      reason: "RESEARCH_LANE_SNAPSHOT_NOT_FOUND",
      write_policy: "read_only",
      recommendation_status: "RESEARCH_ONLY",
      production_allowed: false,
      buy_gate_updated: false,
      orders_sent: false,
    };
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "", navigation_date: "", stage_dates: [], research_dates: [], future_target_dates: [] });
      }
      if (url === "/api/v3/research/dates") return jsonResponse({ research_dates: [] });
      if (url === "/api/v3/research/lane?research_date=20260917") return jsonResponse(lane);
      if (url.startsWith("/api/v3/research/wechat/materials?")) {
        return {
          ok: true,
          headers: new Headers({ "content-type": "application/json" }),
          json: async () => ({
            schema_version: "v4.wechat_materials.stage_a.v1",
            status: "NOT_INDEXED",
            query: { date: "20260917", date_basis: "article", q: "", limit: 20 },
            timezone: "Asia/Shanghai",
            items: [], total: 0, returned: 0, next_cursor: null, index_revision: null,
            RESEARCH_ONLY: true, WATCH_ONLY: true, NO_BUY_GATE: true,
            production_allowed: false, buy_gate_updated: false, orders_sent: false,
          }),
        };
      }
      return jsonResponse(blockedPool);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(App);
    const input = await screen.findByLabelText("交易日（日历选择）");
    await waitFor(() => expect((input as HTMLInputElement).value).toBe("2026-09-17"));
    expect(await screen.findByRole("region", { name: "研报决策台" })).toBeTruthy();
    expect(await screen.findByText("NOT_MATERIALIZED")).toBeTruthy();
    expect(new URLSearchParams(window.location.search).get("date")).toBe("20260917");

    await fireEvent.click(screen.getByRole("button", { name: "公众号" }));
    expect(await screen.findByTestId("wechat-not-indexed")).toBeTruthy();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/api/v3/research/wechat/materials?") && String(url).includes("date=20260917"))).toBe(true);
  }, 15_000);
});

describe("future target date navigation", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  const dateList = {
    default_date: "20260928",
    navigation_date: "20260928",
    navigation_timezone: "Asia/Shanghai",
    dates: ["20260928"],
    stage_dates: ["20260928"],
    future_target_dates: ["20260929"],
  };

  function installFutureDateApi() {
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") return jsonResponse(dateList);
      if (url === "/api/v3/research/dates") return jsonResponse({ research_dates: [] });
      if (url.startsWith("/api/v3/workbench/stage?")) {
        const requestUrl = new URL(url, "http://localhost");
        const requestedDate = requestUrl.searchParams.get("date") || "";
        const requestedStage = requestUrl.searchParams.get("stage") || "STAGE_0925";
        return jsonResponse({
          ...structuredClone(referenceStage),
          trade_date: requestedDate,
          stage: {
            ...referenceStage.stage,
            stage_id: requestedStage,
            status: requestedDate === "20260929" ? "NOT_DUE" : "READY",
            display_status: requestedDate === "20260929" ? "未到执行时点" : "阶段材料已读取",
          },
        });
      }
      if (url.startsWith("/api/v3/preselection-pools?")) {
        const requestUrl = new URL(url, "http://localhost");
        const requestedDate = requestUrl.searchParams.get("date") || "";
        const futureRow = {
          market: "A",
          code: "A.600001",
          stock_name: requestedDate === "20260929" ? "次日预选候选" : "当日预选候选",
          signal_date: "20260928",
        };
        return jsonResponse({
          data_status: "READY",
          trade_date: requestedDate,
          rows: [futureRow],
          a_all_pool_rows: [futureRow],
          a_all_pool_complete: true,
          market_totals: { A: 1, HK: 0 },
          pools: [],
        });
      }
      if (url.startsWith("/api/v3/review?")) {
        const requestUrl = new URL(url, "http://localhost");
        return jsonResponse({ ...closeReview, trade_date: requestUrl.searchParams.get("date") });
      }
      return jsonResponse(blockedPool);
    });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("selects the exact future date, loads only that date, and preserves it across review tabs", async () => {
    const fetchMock = installFutureDateApi();
    window.history.replaceState({}, "", "/?date=20260928&stage=STAGE_0925");
    render(App);

    const input = await screen.findByLabelText("交易日（日历选择）") as HTMLInputElement;
    await waitFor(() => expect(input.value).toBe("2026-09-28"));
    expect(input.min).toBe("2026-09-28");
    expect(input.max).toBe("2026-09-29");

    const beforeSelection = fetchMock.mock.calls.length;
    await fireEvent.change(input, { target: { value: "2026-09-29" } });
    await waitFor(() => expect(input.value).toBe("2026-09-29"));
    expect(new URLSearchParams(window.location.search).get("date")).toBe("20260929");
    expect(await screen.findByText("次日预选候选")).toBeTruthy();
    expect(screen.getByTestId("selected-date-context").textContent)
      .toContain("当前查看目标日：2026-09-29 · 次日预选池准备（未开盘）");
    await waitFor(() => expect(screen.getAllByText(/NOT_DUE/).length).toBeGreaterThan(0));
    expect(fetchMock).toHaveBeenCalledWith("/api/v3/preselection-pools?date=20260929&limit=200");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v3/workbench/stage?date=20260929&stage=STAGE_0925&limit=50",
      expect.objectContaining({ cache: "no-store" }),
    );
    const selectedDateRequests = fetchMock.mock.calls.slice(beforeSelection)
      .map(([url]) => String(url))
      .filter((url) => url.startsWith("/api/v3/preselection-pools?") || url.startsWith("/api/v3/workbench/stage?"));
    expect(selectedDateRequests.length).toBeGreaterThan(1);
    expect(selectedDateRequests.every((url) => url.includes("date=20260929"))).toBe(true);

    await fireEvent.click(screen.getByRole("button", { name: "A股复盘" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/v3/review?date=20260929"));
    expect(input.value).toBe("2026-09-29");

    await fireEvent.click(screen.getByRole("button", { name: "阶段选股" }));
    await waitFor(() => expect(input.value).toBe("2026-09-29"));
    await waitFor(() => expect(screen.getAllByText(/NOT_DUE/).length).toBeGreaterThan(0));
    expect(new URLSearchParams(window.location.search).get("date")).toBe("20260929");
  });

  it("opens the API-listed next target through the same exact-date path", async () => {
    const fetchMock = installFutureDateApi();
    window.history.replaceState({}, "", "/?date=20260928&stage=STAGE_0925");
    render(App);

    const input = await screen.findByLabelText("交易日（日历选择）") as HTMLInputElement;
    await waitFor(() => expect(input.value).toBe("2026-09-28"));
    await fireEvent.click(screen.getByRole("button", { name: "查看次日预选池：2026-09-29" }));

    await waitFor(() => expect(input.value).toBe("2026-09-29"));
    expect(new URLSearchParams(window.location.search).get("date")).toBe("20260929");
    expect(new URLSearchParams(window.location.search).get("stage")).toBe("STAGE_0925");
    expect(screen.getByTestId("selected-date-context").textContent)
      .toContain("当前查看目标日：2026-09-29");
    expect(await screen.findByText("次日预选候选")).toBeTruthy();
    await waitFor(() => expect(screen.getAllByText(/NOT_DUE/).length).toBeGreaterThan(0));
    expect(fetchMock).toHaveBeenCalledWith("/api/v3/preselection-pools?date=20260929&limit=200");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v3/workbench/stage?date=20260929&stage=STAGE_0925&limit=50",
      expect.objectContaining({ cache: "no-store" }),
    );
  });
});
