/// <reference types="node" />
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App.vue";

function resolveCandidateInput(...parts: string[]) {
  let ancestor = resolve(process.cwd());
  while (true) {
    const candidate = resolve(ancestor, ...parts);
    if (existsSync(candidate)) return candidate;
    const parent = resolve(ancestor, "..");
    if (parent === ancestor) break;
    ancestor = parent;
  }
  throw new Error(`Unable to locate candidate input: ${parts.join("/")}`);
}

const aShare0925SelectionManifest = JSON.parse(readFileSync(
  resolveCandidateInput("verification", "fixtures", "a_share_stage_0925_selection_manifest.json"),
  "utf8",
));
const hkConnect0930SelectionManifest = JSON.parse(readFileSync(
  resolveCandidateInput("verification", "fixtures", "hk_connect_stage_0930_selection_manifest.json"),
  "utf8",
));
const aShare1445SelectionEnvelope = JSON.parse(readFileSync(
  resolveCandidateInput("all_stage_recovery_20260928", "A_SHARE", "witness_fix", "stage_result_1445_1500_r3", "selection_envelope.json"),
  "utf8",
));
const hkConnect1445SelectionManifest = JSON.parse(readFileSync(
  resolveCandidateInput("all_stage_recovery_20260928", "HK_CONNECT", "stores", "recovered", "selection", "selection_runs", "20260928", "HK_CONNECT_SELECTION_STAGE_1445_1500", "run-1e534c14396c0fb19f51d93d", "manifest.json"),
  "utf8",
));
const referenceCards20260924 = JSON.parse(readFileSync(
  resolveCandidateInput("resume_20260929", "reference_cards_20260924.json"),
  "utf8",
));

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
    expect(screen.getAllByText(/20260730 · 09:35/).length).toBeGreaterThan(0);
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
    expect(within(hkRegion).getAllByText("D-1参考，待09:20二筛")).toHaveLength(1);
    expect(within(hkRegion).getByText("当前阶段未提供快照涨幅")).toBeTruthy();
    expect(within(hkRegion).getByText("D-1参考分")).toBeTruthy();
    expect(within(hkRegion).getByText("0.836")).toBeTruthy();
    expect(within(hkRegion).queryByText("支撑位")).toBeNull();
    expect(within(hkRegion).queryByText("压力位")).toBeNull();
    expect(within(hkRegion).queryByText("失效位")).toBeNull();
    expect(container.textContent).not.toContain("缺证");
  });

  it("keeps null, zero, and a real 09:20 snapshot change distinct from the D-1 reference", async () => {
    const snapshotStage = structuredClone(referenceStage) as any;
    snapshotStage.unified_rows = [
      { market: "HK", code: "HK.00325", name: "空快照", status: "WAITING_0920_SECOND_FILTER", source_mode: "HK_CONNECT_D1_PRESELECT_REFERENCE", current_change_pct: null },
      { market: "HK", code: "HK.00001", name: "零快照", status: "WAITING_0920_SECOND_FILTER", source_mode: "HK_CONNECT_D1_PRESELECT_REFERENCE", current_change_pct: 0 },
      { market: "HK", code: "HK.00002", name: "有效快照", status: "WAITING_0920_SECOND_FILTER", source_mode: "HK_CONNECT_D1_PRESELECT_REFERENCE", current_change_pct: 0.625 },
    ];
    snapshotStage.selected_hk_rows = 3;
    snapshotStage.selected_total_rows = 3;
    snapshotStage.markets.HK.candidate_count = 3;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(snapshotStage);
      return jsonResponse(blockedPool);
    }));

    render(App);

    const hkRegion = await screen.findByRole("region", { name: "港股通候选" });
    await screen.findByText("有效快照");
    const cards = Array.from(hkRegion.querySelectorAll<HTMLElement>(".candidate-card"));
    expect(cards).toHaveLength(3);
    for (const card of cards) {
      expect(within(card).getAllByText("D-1参考，待09:20二筛")).toHaveLength(1);
    }
    expect(within(cards[0]).getByText("当前阶段未提供快照涨幅")).toBeTruthy();
    expect(within(cards[1]).getByText("0%")).toBeTruthy();
    expect(within(cards[2]).getByText("0.625%")).toBeTruthy();
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
      snapshot.unified_rows = [
        ...Array.from({ length: snapshot.selected_a_rows }, (_, rowIndex) => ({ market: "A", code: `A.${stageId}.${rowIndex + 1}` })),
        ...Array.from({ length: snapshot.selected_hk_rows }, (_, rowIndex) => ({ market: "HK", code: `HK.${stageId}.${rowIndex + 1}` })),
      ];
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
      expect(fetchMock).toHaveBeenCalledWith("/api/v3/preselection-pools?date=20260730&limit=200&offset=0");
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
    expect(screen.getByText("本页 1 / 来源声明 19 条（分页或来源完整性未确认）")).toBeTruthy();
    expect(screen.getByText("本页 0 / 来源声明 64 条（分页或来源完整性未确认）")).toBeTruthy();
    expect(screen.getByText("本页 0 / 来源声明 70 条（分页或来源完整性未确认）")).toBeTruthy();
    expect(screen.getByText("本页 0 / 来源声明 6 条（分页或来源完整性未确认）")).toBeTruthy();
    expect(screen.getByText("本页 0 / 来源声明 147 条（分页或来源完整性未确认）")).toBeTruthy();
    expect(screen.getByText("来源未确认；本页 0 / 来源声明 0 条")).toBeTruthy();
    expect(screen.getByText("本页 1 / 来源声明 100 条（分页或来源完整性未确认）")).toBeTruthy();
    expect(screen.getByText("本页 1 / 来源声明 43 条（分页或来源完整性未确认）")).toBeTruthy();
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
    expect(within(incomplete).getByText("来源未确认；本页 0 / 来源声明 0 条")).toBeTruthy();
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

  it("labels only API-confirmed pages as paginated and retains next-page navigation", async () => {
    const pageRows = (offset: number, count: number) => Array.from({ length: count }, (_, index) => ({
      market: "A", symbol: `A.${String(offset + index).padStart(6, "0")}`, stock_name: `分页候选${offset + index}`,
    }));
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url.startsWith("/api/v3/tasks/status")) return jsonResponse(taskStatus);
      if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(referenceStage);
      if (url.startsWith("/api/v3/preselection-pools")) {
        const offset = Number(new URL(url, window.location.origin).searchParams.get("offset") ?? 0);
        const count = offset === 0 ? 200 : 87;
        const hasMore = offset === 0;
        return jsonResponse({
          data_status: "READY_WITH_ROWS",
          trade_date: "20260730",
          market_totals: { A: 287, HK: 0 },
          a_all_pool_rows: pageRows(offset, count),
          a_all_pool_complete: !hasMore,
          rows: [],
          pools: [],
          pagination: {
            offset, limit: 200, has_more: hasMore, next_offset: hasMore ? 200 : null,
            arrays: { a_all_pool_rows: { offset, limit: 200, returned_rows: count, has_more: hasMore, complete: !hasMore } },
          },
          blocking_reasons: [],
        });
      }
      return jsonResponse(blockedPool);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(App);

    expect(await screen.findByText("分页候选0")).toBeTruthy();
    expect(screen.getByText("本页 200 / 来源共 287 条（分页显示）")).toBeTruthy();
    await fireEvent.click(screen.getByRole("button", { name: "下一页／查看余下名单" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/v3/preselection-pools?date=20260730&limit=200&offset=200"));
    expect(await screen.findByText("分页候选200")).toBeTruthy();
    expect(screen.getByText("本页 87 / 来源共 287 条（分页显示）")).toBeTruthy();
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

    const closeButton = screen.getByText("9. 16:10 港股市场正式收盘：0.2 × 七阶段 Top20").closest("button")!;
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

    await fireEvent.click(screen.getByText("9. 16:10 港股市场正式收盘：0.2 × 七阶段 Top20").closest("button")!);

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

    void fireEvent.click(screen.getByText("9. 16:10 港股市场正式收盘：0.2 × 七阶段 Top20").closest("button")!);
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
      expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/v3/preselection-pools?date=20260729&limit=200&offset=0");
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
      expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/v3/preselection-pools?date=20260731&limit=200&offset=0");
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
    expect(vi.mocked(fetch)).not.toHaveBeenCalledWith("/api/v3/preselection-pools?date=20260728&limit=200&offset=0");
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
    expect(within(summary).getByText("本页 1 / 来源声明 203 条（分页或来源完整性未确认）")).toBeTruthy();
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
    expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/v3/preselection-pools?date=20260914&limit=200&offset=0");

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
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/v3/preselection-pools?date=20260914&limit=200&offset=0"));

    window.history.pushState({}, "", "/?date=20260915");
    window.dispatchEvent(new PopStateEvent("popstate"));
    await waitFor(() => expect(input.value).toBe("2026-09-15"));
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/v3/preselection-pools?date=20260915&limit=200&offset=0"));
  });

  it("restores the navigation date when browser history removes the date parameter", async () => {
    install("20260914", true);
    render(App);
    const input = await screen.findByLabelText("交易日（日历选择）") as HTMLInputElement;
    await waitFor(() => expect(input.value).toBe("2026-09-14"));

    window.history.pushState({}, "", "/");
    window.dispatchEvent(new PopStateEvent("popstate"));

    await waitFor(() => expect(input.value).toBe("2026-09-15"));
    expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/v3/preselection-pools?date=20260915&limit=200&offset=0");
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
    expect(vi.mocked(fetch)).toHaveBeenCalledWith("/api/v3/preselection-pools?date=20260915&limit=200&offset=0");
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
    expect(fetchMock.mock.calls.some(([url]) => String(url) === "/api/v3/preselection-pools?date=20260920&limit=200&offset=0")).toBe(false);

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


describe("r3 next future target navigation", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("loads the exact API-listed next target and leaves a future stage NOT_DUE", async () => {
    window.history.replaceState({}, "", "/?date=20260928&stage=STAGE_0925");
    const requested: string[] = [];
    const fetchMock = vi.fn(async (url: string) => {
      requested.push(url);
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({
          default_date: "20260928", navigation_date: "20260928",
          stage_dates: ["20260928"], future_target_dates: ["20260929"],
        });
      }
      if (url === "/api/v3/research/dates") return jsonResponse({ research_dates: [] });
      if (url.startsWith("/api/v3/workbench/stage")) {
        const query = new URL(url, window.location.origin).searchParams;
        const date = query.get("date") || "20260928";
        const stageId = query.get("stage") || "STAGE_0925";
        return jsonResponse({
          ...referenceStage,
          trade_date: date,
          stage: {
            ...referenceStage.stage,
            stage_id: stageId,
            status: date === "20260929" ? "NOT_DUE" : "DATA_PARTIAL_OBSERVE_ONLY",
            display_status: date === "20260929" ? "未到阶段计划时间，当前保持 NOT_DUE" : "当前阶段观察",
          },
        });
      }
      if (url.startsWith("/api/v3/preselection-pools?")) {
        const date = new URL(url, window.location.origin).searchParams.get("date") || "20260928";
        return jsonResponse({ ...blockedPool, trade_date: date });
      }
      if (url.startsWith("/api/v3/tasks/status")) return jsonResponse(taskStatus);
      return jsonResponse({ ...blockedPool, trade_date: "20260928" });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(App);
    const shortcut = await screen.findByRole("button", { name: "查看次日预选池：2026-09-29" });
    await fireEvent.click(shortcut);

    await waitFor(() => {
      expect((screen.getByLabelText("交易日（日历选择）") as HTMLInputElement).value).toBe("2026-09-29");
      expect(new URLSearchParams(window.location.search).get("date")).toBe("20260929");
    });
    expect(screen.getByTestId("selected-date-context").textContent).toContain("次日预选池目标日：2026-09-29");
    expect(await screen.findByText("NOT_DUE · 09:20-09:25")).toBeTruthy();
    expect(screen.getAllByText("未到阶段计划时间，当前保持 NOT_DUE").length).toBeGreaterThan(0);
    expect(requested.some((url) => url.startsWith("/api/v3/preselection-pools?date=20260929&"))).toBe(true);
    expect(requested.some((url) => url.startsWith("/api/v3/workbench/stage?date=20260929&stage=STAGE_0925"))).toBe(true);
    expect(requested.some((url) => url.includes("date=20260928") && url.includes("date=20260929"))).toBe(false);
  });
});

describe("r3 stage timeout abort", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });

  it("aborts the underlying stage request when the 12-second timeout wins", async () => {
    vi.useFakeTimers();
    window.history.replaceState({}, "", "/?date=20260928&stage=STAGE_0925");
    const stageSignals: AbortSignal[] = [];
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/v1/runs/date-list") {
        return Promise.resolve(jsonResponse({
          default_date: "20260928", navigation_date: "20260928",
          stage_dates: ["20260928"], future_target_dates: [],
        }));
      }
      if (url === "/api/v3/research/dates") return Promise.resolve(jsonResponse({ research_dates: [] }));
      if (url.startsWith("/api/v3/preselection-pools?")) {
        return Promise.resolve(jsonResponse({ ...blockedPool, trade_date: "20260928" }));
      }
      if (url.startsWith("/api/v3/workbench/stage")) {
        if (init?.signal) stageSignals.push(init.signal as AbortSignal);
        return new Promise(() => {});
      }
      return Promise.resolve(jsonResponse({ ...blockedPool, trade_date: "20260928" }));
    });
    vi.stubGlobal("fetch", fetchMock);

    try {
      render(App);
      for (let turn = 0; turn < 12; turn += 1) await Promise.resolve();
      expect(stageSignals.length).toBeGreaterThan(0);
      expect(stageSignals[0].aborted).toBe(false);
      await vi.advanceTimersByTimeAsync(12_000);
      for (let turn = 0; turn < 6; turn += 1) await Promise.resolve();
      expect(stageSignals[0].aborted).toBe(true);
      expect(document.body.textContent).toContain("阶段工作台读取超时。");
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("explicit historical backfill readback", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });

  it("shows only the exact A-share BACKFILL/WATCH_ONLY result and preserves all evidence gaps", async () => {
    const runId = "a_share_historical_recovery_20260928_20260929_r3";
    const evidence = [
      "recovery_mode=HISTORICAL_BACKFILL",
      "actual_request_started_at=2026-09-29T01:55:22.910230+08:00",
      "actual_response_received_at=2026-09-29T01:55:27.982433+08:00",
      "captured_at_semantics=REQUESTED_STAGE_CUTOFF_METADATA_NOT_RETRIEVAL_TIME",
    ];
    const cannotConfirm = Array.from({ length: 222 }, (_, index) => `CANNOT_CONFIRM_FIXTURE_${index + 1}`);
    cannotConfirm[221] = "FINAL_GAP_MUST_REMAIN_VISIBLE";
    const rows = Array.from({ length: 10 }, (_, index) => ({
      market: "A",
      code: `A.${String(index + 1).padStart(6, "0")}`,
      stock_code: `A.${String(index + 1).padStart(6, "0")}`,
      stock_name: `回补候选${index + 1}`,
      stage_rank: index + 1,
      trade_status: "WATCH_ONLY",
      action_level: "WATCH_ONLY",
      status: "WATCH_ONLY",
      source_mode: "A_SHARE_WINDOWS_V3_LIVE_STAGE",
      formal_eligible: false,
    }));
    const backfill = {
      ok: true,
      trade_date: "20260928",
      run_id: "run-36f4b1fc50fdd609a7aa46b7",
      stage: {
        stage_id: "STAGE_0930_0935",
        label: "09:30-09:35",
        window: "09:30-09:35",
        status: "PARTIAL_WITH_ROWS",
        display_status: "历史回补结果，仅供 WATCH_ONLY 研究观察。",
      },
      markets: {
        A: {
          status: "PARTIAL_WITH_ROWS",
          selection_status: "PARTIAL_WITH_ROWS",
          source_status: "CANNOT_CONFIRM",
          selected_rows: 10,
          source_rows: 190,
          missing_symbols: ["A.920015", "A.920571", "A.920748", "A.920961"],
          source_evidence: evidence,
          cannot_confirm: cannotConfirm,
          rows,
        },
      },
      unified_rows: rows,
      selected_a_rows: 10,
      selected_hk_rows: 0,
      selected_total_rows: 10,
      selection_mode: "HISTORICAL_BACKFILL_READ_ONLY",
      mode: "BACKFILL",
      backfill_run_id: runId,
      market: "A_SHARE",
      recommendation_status: "WATCH_ONLY",
      RESEARCH_ONLY: true,
      production_allowed: false,
      buy_gate_updated: false,
      orders_sent: false,
      write_performed: false,
    };
    window.history.replaceState({}, "", `/?date=20260928&stage=STAGE_0930_0935&backfill_run_id=${runId}&market=A_SHARE`);
    const requested: string[] = [];
    const fetchMock = vi.fn(async (url: string) => {
      requested.push(url);
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260928", navigation_date: "20260929", stage_dates: ["20260928"], future_target_dates: [] });
      }
      if (url === "/api/v3/research/dates") return jsonResponse({ research_dates: [] });
      if (url.startsWith("/api/v3/workbench/stage?")) {
        const query = new URL(url, window.location.origin).searchParams;
        expect(query.get("date")).toBe("20260928");
        expect(query.get("stage")).toBe("STAGE_0930_0935");
        expect(query.get("backfill_run_id")).toBe(runId);
        expect(query.get("market")).toBe("A_SHARE");
        return jsonResponse(backfill);
      }
      return jsonResponse(blockedPool);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(App);
    expect(await screen.findByTestId("backfill-readback")).toBeTruthy();
    expect(screen.getByText("历史回补 · BACKFILL · 只读")).toBeTruthy();
    const aColumn = await screen.findByTestId("stage-candidates-A");
    const hkColumn = screen.getByTestId("stage-candidates-HK");
    await waitFor(() => expect(aColumn.querySelectorAll(".candidate-card")).toHaveLength(10));
    expect(aColumn.textContent).toContain("历史回补·只读");
    expect(within(aColumn).getAllByText("WATCH_ONLY").length).toBeGreaterThanOrEqual(10);
    expect(hkColumn.textContent).toContain("本次历史请求未包含该市场；不代表该市场零候选。");
    expect(hkColumn.querySelectorAll(".candidate-card")).toHaveLength(0);
    expect(screen.getByTestId("backfill-evidence-details").hasAttribute("open")).toBe(false);
    await fireEvent.click(screen.getByText("完整来源、run 与缺项证据"));
    expect(screen.getByText(/绑定日期 20260928 · 阶段 STAGE_0930_0935 · 市场 A_SHARE · backfill_run_id=/)).toBeTruthy();
    expect(screen.getByText("实际取数开始：2026-09-29T01:55:22.910230+08:00")).toBeTruthy();
    expect(screen.getByText("实际响应收到：2026-09-29T01:55:27.982433+08:00")).toBeTruthy();
    expect(screen.getByText(/captured_at 语义：REQUESTED_STAGE_CUTOFF_METADATA_NOT_RETRIEVAL_TIME/)).toBeTruthy();
    expect(screen.getByText(/缺少分钟源股票：A\.920015、A\.920571、A\.920748、A\.920961/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "运行 / 恢复当前阶段" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "强制重新物化" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByLabelText("交易日（日历选择）") as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByRole("combobox", { name: "阶段" }) as HTMLSelectElement).disabled).toBe(true);
    expect(screen.getByRole("region", { name: "港股通候选" })).toBeTruthy();
    expect(screen.queryByRole("region", { name: "美股收盘板块涨跌幅" })).toBeNull();
    expect(screen.queryByRole("region", { name: "统一预选池" })).toBeNull();

    await fireEvent.click(screen.getByText("全部 CANNOT_CONFIRM 缺项（222）"));
    expect(screen.getAllByTestId("backfill-cannot-confirm")).toHaveLength(222);
    expect(screen.getByText("FINAL_GAP_MUST_REMAIN_VISIBLE")).toBeTruthy();
    await fireEvent.click(screen.getByText(`全部 source_evidence（${evidence.length}）`));
    expect(screen.getByText("recovery_mode=HISTORICAL_BACKFILL")).toBeTruthy();
    expect(requested.filter((url) => url.startsWith("/api/v3/workbench/stage?"))).toHaveLength(1);
    expect(requested.some((url) => url.startsWith("/api/v3/preselection-pools"))).toBe(false);
    expect(requested.some((url) => url.startsWith("/api/v3/workbench/stage/ensure"))).toBe(false);
  });

  it("offers the exact recovery URL from the ordinary stage page", async () => {
    window.history.replaceState({}, "", "/?date=20260730&stage=STAGE_0925");
    render(App);

    const link = await screen.findByTestId("raw194-backfill-link");
    const href = new URL(link.getAttribute("href") || "", window.location.origin);
    expect(href.searchParams.get("date")).toBe("20260928");
    expect(href.searchParams.get("stage")).toBe("STAGE_0930_0935");
    expect(href.searchParams.get("backfill_run_id")).toBe("a_share_historical_recovery_20260928_20260929_r3");
    expect(href.searchParams.get("market")).toBe("A_SHARE");
  });

  it("renders an explicit HK_CONNECT backfill under the HK contract", async () => {
    const runId = "20260928-hk-fixture-recovery-r1";
    const hkRow = {
      market: "HK",
    code: "HK.00001",
    stock_name: "HK 合同测试行",
    trade_status: "NO_TRADE",
    action_level: "NO_BUY",
    status: "NO_TRADE",
    source_mode: "HK_CONNECT_FOUR_LANE",
    formal_eligible: false,
    };
    const backfill = {
      ok: true,
      trade_date: "20260928",
      run_id: "run-hk-fixture-r1",
      stage: { stage_id: "STAGE_0930_0935", status: "PARTIAL_WITH_ROWS", display_status: "测试只读回补" },
      markets: {
        HK: {
          selection_status: "PARTIAL_WITH_ROWS",
          source_status: "CANNOT_CONFIRM",
          selected_rows: 1,
          source_rows: 10,
          source_evidence: [
            "route=shared_pytdx_exhq_hk_exact_d1_top100",
            "hk_selection_mode=TDXPY_EXHQ_D1_TOP100_OBSERVATION",
            "hk_historical_active_snapshot=UNAVAILABLE_NO_ASOF_INTERFACE",
            "live_hkgainer_lane=NOT_ASSERTED",
            "due_status=HISTORICAL_BACKFILL",
            "hk_d1_status=STRICT_0_2_READY",
            "hk_d1_membership=exact_date_top100",
            "selection_contract=V3_TOP10_RECOMMENDATION",
          ],
          cannot_confirm: ["fixture gap"],
          missing_symbols: [],
        },
      },
      unified_rows: [hkRow],
      selected_a_rows: 0,
      selected_hk_rows: 1,
      selected_total_rows: 1,
      mode: "BACKFILL",
      backfill_run_id: runId,
      market: "HK_CONNECT",
      selection_mode: "HISTORICAL_BACKFILL_READ_ONLY",
      RESEARCH_ONLY: true,
      production_allowed: false,
      buy_gate_updated: false,
      orders_sent: false,
      write_performed: false,
    };
    window.history.replaceState({}, "", `/?date=20260928&stage=STAGE_0930_0935&backfill_run_id=${runId}&market=HK_CONNECT`);
    const requested: string[] = [];
    const fetchMock = vi.fn(async (url: string) => {
      requested.push(url);
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260928", navigation_date: "20260929", stage_dates: ["20260928"], future_target_dates: [] });
      }
      if (url === "/api/v3/research/dates") return jsonResponse({ research_dates: [] });
      if (url.startsWith("/api/v3/workbench/stage?")) return jsonResponse(backfill);
      return jsonResponse(blockedPool);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(App);
    expect(await screen.findByTestId("backfill-readback")).toBeTruthy();
    expect(screen.getByText(/HK_CONNECT；本次查询结果填入同一市场的候选卡片栏/)).toBeTruthy();
    const hkColumn = screen.getByTestId("stage-candidates-HK");
    await waitFor(() => expect(hkColumn.querySelectorAll(".candidate-card")).toHaveLength(1));
    expect(within(hkColumn).getByText("HK 合同测试行")).toBeTruthy();
    expect(screen.queryByTestId("backfill-historical-rows")).toBeNull();
    expect(screen.getByTestId("backfill-evidence-details").hasAttribute("open")).toBe(false);
    await fireEvent.click(screen.getByText("完整来源、run 与缺项证据"));
    expect(screen.getByText(/backfill_run_id=20260928-hk-fixture-recovery-r1/)).toBeTruthy();
    expect(requested.some((url) => url.includes("market=HK_CONNECT"))).toBe(true);
    expect(screen.queryByRole("region", { name: "统一预选池" })).toBeNull();
  });
});

// Exact execution_evidence excerpt from the read-only live response:
// GET /api/v3/workbench/stage?date=20260928&stage=STAGE_0930_0935
// Captured body SHA-256: 5c8f8abe25e60c7ffa751aa3dcc2d932725fa823050e5d1333589a2bb5abac98
const formalStage0930FailureEvidenceFixture = {
  status: "DECLARED_ONLY",
  trade_date: "20260928",
  stage_id: "STAGE_0930_0935",
  execution_verified: false,
  natural_verified: false,
  markets: {
    A_SHARE: {
      requested_rows: null,
      source_rows: null,
      observed_rows: 0,
      accepted_rows: null,
      selected_rows: null,
      status: "CANNOT_CONFIRM",
      reasons: ["strict current is missing or unavailable"],
      selection_binding: "NO_VERIFIED_SELECTION_BINDING",
      failure_layer: "EXACT_SELECTION_INPUT_BINDING",
      declared_identity: { run_id: null, artifact_id: null, algorithm_sha256: null, raw_artifact_sha256: null },
      write_performed: null,
    },
    HK_CONNECT: {
      requested_rows: 100,
      source_rows: null,
      observed_rows: 0,
      accepted_rows: null,
      selected_rows: null,
      status: "CANNOT_CONFIRM",
      reasons: ["HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE"],
      selection_binding: "NO_VERIFIED_SELECTION_BINDING",
      failure_layer: "EXACT_SELECTION_INPUT_BINDING",
      declared_identity: { run_id: null, artifact_id: null, algorithm_sha256: null, raw_artifact_sha256: null },
      write_performed: null,
    },
  },
  historical_bad_row_status: "NOT_RECORDED_OR_NOT_BOUND",
  cannot_confirm: [
    "NO_INDEPENDENT_RUN_RECEIPT_SHA_BINDING",
    "NO_IMMUTABLE_NATURAL_RECOVERY_HISTORY",
    "RECEIPT_RECORD_TIME_NOT_RECORDED",
  ],
  write_performed: false,
  scope: "READ_ONLY_EXECUTION_DECLARATION_SEPARATE_FROM_VERIFIED_SELECTION",
  receipt_path: "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/receipts/20260928/STAGE_0930_0935/receipt.json",
  observed_sha256: "940234713db706bf6d79fc764622090ffd9e58812152ef441b44393ed66d79f3",
  attempt_mode: "RECOVERY",
  due_status: "LATE_CATCHUP_REPLAY",
  declared_status: "CANNOT_CONFIRM",
  recorded_at: null,
  node_id: "STAGE_0930_0935",
  node_attempt_count: 3,
  node_outcome: "TRANSIENT",
  retry_after: null,
  first_failed_layer: "EXACT_SELECTION_INPUT_BINDING",
  error: "all market collectors returned zero-row CANNOT_CONFIRM",
  candidate_run_id: null,
  candidate_current_sha256: "0024b72d7122f2a44ff21483eddc3d1be5b771caa854d915e23ea507e5d1f60d",
  candidate_binding: "REFERENCE_ONLY_CURRENT_TRIO_NOT_BOUND",
};

function ordinaryStageReadback(date: string, stage: string) {
  return {
    ok: true,
    trade_date: date,
    stage: { stage_id: stage, status: "CANNOT_CONFIRM", display_status: "正式阶段证据 CANNOT_CONFIRM" },
    markets: {
      A: { status: "CANNOT_CONFIRM", selection_status: "CANNOT_CONFIRM", source_status: "CANNOT_CONFIRM", selected_rows: 0, rows: [] },
      HK: { status: "CANNOT_CONFIRM", selection_status: "CANNOT_CONFIRM", source_status: "CANNOT_CONFIRM", selected_rows: 0, rows: [] },
    },
    unified_rows: [],
    selected_a_rows: 0,
    selected_hk_rows: 0,
    selected_total_rows: 0,
    execution_evidence: date === "20260928" && stage === "STAGE_0930_0935"
      ? formalStage0930FailureEvidenceFixture
      : undefined,
    selection_mode: "FORMAL_STAGE_READBACK",
    production_allowed: false,
    buy_gate_updated: false,
    orders_sent: false,
  };
}

function rowsFromCapturedCandidateCards(html: string, market: "A" | "HK") {
  const template = document.createElement("template");
  template.innerHTML = html;
  const metric = (card: Element, label: string) => {
    const cell = Array.from(card.querySelectorAll("dl > div"))
      .find((item) => item.querySelector("dt")?.textContent?.trim() === label);
    return cell?.querySelector("dd")?.textContent?.trim() ?? "";
  };
  const numeric = (value: string) => {
    if (!value.trim()) return undefined;
    const parsed = Number(value.replace(/%/g, "").replace(/,/g, ""));
    return Number.isFinite(parsed) ? parsed : undefined;
  };
  return Array.from(template.content.querySelectorAll("article.candidate-card")).map((card) => {
    const identity = card.querySelector(".candidate-head span")?.textContent?.trim() ?? "";
    const [, code = "", rank = ""] = /^(.*?) · 排名 (.+)$/.exec(identity) ?? [];
    const verification = metric(card, "所选阶段计划验证").split(" · ").pop() ?? "";
    const change = numeric(metric(card, market === "A" ? "涨幅" : "阶段涨幅"));
    const score = numeric(metric(card, market === "A" ? "阶段分" : "二筛分"));
    return {
      market,
      code,
      name: card.querySelector(".candidate-head strong")?.textContent?.trim() ?? "",
      stage_rank: Number(rank),
      current_change_pct: change,
      score,
      news_quality_score: numeric(metric(card, "新闻分")),
      research_quality_score: numeric(metric(card, "研报分")),
      support_primary_price: numeric(metric(card, "支撑位")),
      pressure_price: numeric(metric(card, "压力位")),
      invalidation_price: numeric(metric(card, "失效位")),
      next_validation_time: verification,
      stage_display_decision: card.querySelector(".candidate-head b")?.textContent?.trim() ?? "观察",
    };
  });
}

function approvedAStageBackfill() {
  const evidence = [
    "recovery_mode=HISTORICAL_BACKFILL",
    "capture_manifest_sha256=7c09e834b31fa3275921c092c54791adcd1e9dc9b6c587a814df16a00884d9d6",
    "capture_receipt_sha256=843560dcf2dc29dba258a6552dc2141c146fce6310489c8150cc2a24c761386a",
    "actual_request_started_at=2026-09-29T01:55:22.910230+08:00",
    "actual_response_received_at=2026-09-29T01:55:27.982433+08:00",
    "captured_at_semantics=REQUESTED_STAGE_CUTOFF_METADATA_NOT_RETRIEVAL_TIME",
  ];
  const cannotConfirm = Array.from({ length: 222 }, (_, index) => `CANNOT_CONFIRM_APPROVED_FIXTURE_${index + 1}`);
  const rows = Array.from({ length: 10 }, (_, index) => ({
    market: "A",
    code: `A.${String(index + 1).padStart(6, "0")}`,
    stock_name: `普通页回补候选${index + 1}`,
    stage_rank: index + 1,
    trade_status: "WATCH_ONLY",
    action_level: "WATCH_ONLY",
    status: "WATCH_ONLY",
    source_mode: "A_SHARE_WINDOWS_V3_LIVE_STAGE",
    formal_eligible: false,
  }));
  return {
    ok: true,
    trade_date: "20260928",
    run_id: "run-36f4b1fc50fdd609a7aa46b7",
    stage: { stage_id: "STAGE_0930_0935", status: "PARTIAL_WITH_ROWS", display_status: "历史回补 WATCH_ONLY" },
    markets: {
      A: {
        artifact_id: "selection-36f4b1fc50fdd609a7aa46b7",
        run_id: "run-36f4b1fc50fdd609a7aa46b7",
        raw_artifact_sha256: "470e8e2c9015dbaefc6d5065b8d4cf8226fcd887b4e56b76ef70435ed0bc13b3",
        algorithm_id: "V3_STAGE_SELECTION_V1",
        algorithm_sha256: "eee20b08b50a693dd673f93937ef4eedc63e909295820a0141ce5e728a3754d2",
        status: "PARTIAL_WITH_ROWS",
        selection_status: "PARTIAL_WITH_ROWS",
        source_status: "CANNOT_CONFIRM",
        selected_rows: 10,
        source_rows: 190,
        source_evidence: evidence,
        cannot_confirm: cannotConfirm,
        rows,
      },
    },
    unified_rows: rows,
    selected_a_rows: 10,
    selected_hk_rows: 0,
    selected_total_rows: 10,
    selection_mode: "HISTORICAL_BACKFILL_READ_ONLY",
    mode: "BACKFILL",
    backfill_run_id: "a_share_historical_recovery_20260928_20260929_r3",
    market: "A_SHARE",
    recommendation_status: "WATCH_ONLY",
    RESEARCH_ONLY: true,
    production_allowed: false,
    buy_gate_updated: false,
    orders_sent: false,
    write_performed: false,
  };
}

function approvedA0925StageBackfill() {
  const manifest = aShare0925SelectionManifest;
  const envelope = manifest.selection_envelope;
  const rows = envelope.rows.map((row: Record<string, unknown>) => ({
    ...row,
    market: "A",
    current_change_pct: null,
    qmt_gap_pct: null,
  }));
  return {
    ok: true,
    trade_date: manifest.trade_date,
    run_id: envelope.run_id,
    stage: { stage_id: envelope.stage_id, status: envelope.selection_status, display_status: "历史竞价回补，仅供 WATCH_ONLY 研究观察。" },
    markets: {
      A: {
        artifact_id: envelope.artifact_id,
        run_id: envelope.run_id,
        raw_artifact_sha256: envelope.raw_artifact_sha256,
        algorithm_id: envelope.algorithm_id,
        algorithm_sha256: envelope.algorithm_sha256,
        status: envelope.selection_status,
        selection_status: envelope.selection_status,
        source_status: envelope.source_status,
        selected_rows: envelope.selected_rows,
        source_rows: envelope.source_rows,
        source_evidence: envelope.source_evidence,
        cannot_confirm: envelope.cannot_confirm,
        rows,
      },
    },
    unified_rows: rows,
    selected_a_rows: envelope.selected_rows,
    selected_hk_rows: 0,
    selected_total_rows: envelope.selected_rows,
    selection_mode: "HISTORICAL_BACKFILL_READ_ONLY",
    mode: "BACKFILL",
    backfill_run_id: "a_share_historical_recovery_20260928_20260929_r3",
    market: "A_SHARE",
    recommendation_status: "WATCH_ONLY",
    RESEARCH_ONLY: true,
    production_allowed: false,
    buy_gate_updated: false,
    orders_sent: false,
    write_performed: false,
  };
}

function approvedHK0930StageBackfill(stageId = "STAGE_0930_0935") {
  const manifest = stageId === "STAGE_1445_1500" ? hkConnect1445SelectionManifest : hkConnect0930SelectionManifest;
  const envelope = manifest.selection_envelope;
  const bindings: Record<string, { runId: string; rawSha: string }> = {
    STAGE_0930_0935: { runId: "run-1f3857be91dbb7b30df2559f", rawSha: "e35933881cae68b649fa806d7084dd493550044c9fa316158a1b5da904603358" },
    STAGE_0935_0940: { runId: "run-d1274b94a927e0409be97a30", rawSha: "93fad4a7c3f052ffc0e882238d06a2eb5e664319b18c5d1ab8dcefd0134d363e" },
    STAGE_0940_0945: { runId: "run-87fece4bd8ec0d5d98de8ef8", rawSha: "97eee6ce875ac128bcd4cba09e944f3b7bae20253f575dbc66fb9ae3bebd7933" },
    STAGE_0945_1030: { runId: "run-099ed20a1b86e53d6ec642a2", rawSha: "0017cd178e4b403f2b0a6c558e981f0ac1c94e2a49d9407d00a5a489bdb0ff44" },
    STAGE_1300_1315: { runId: "run-559dc431f8b79a7263980f4b", rawSha: "4e52fc97cc8a98dc87ad492efd5578405eb5529a955ac2831fcb7f3130bf09dc" },
    STAGE_1445_1500: { runId: "run-1e534c14396c0fb19f51d93d", rawSha: "488d589ba62294d53fecaf91878381a73b9fd4b762ea8cd5eb6acb8371fad191" },
  };
  const binding = bindings[stageId];
  if (!binding) throw new Error(`No HK test binding for ${stageId}`);
  const rows = envelope.rows.map((row: Record<string, unknown>) => ({ ...row, market: "HK" }));
  return {
    ok: true,
    trade_date: manifest.trade_date,
    run_id: binding.runId,
    stage: { stage_id: stageId, status: envelope.selection_status, display_status: "历史港股通回补，Futu 历史活跃快照未确认。" },
    markets: {
      HK: {
        artifact_id: `selection-${binding.runId.slice("run-".length)}`,
        run_id: binding.runId,
        raw_artifact_sha256: binding.rawSha,
        algorithm_id: envelope.algorithm_id,
        algorithm_sha256: envelope.algorithm_sha256,
        status: envelope.selection_status,
        selection_status: envelope.selection_status,
        source_status: envelope.source_status,
        selected_rows: envelope.selected_rows,
        source_rows: envelope.source_rows,
        source_evidence: envelope.source_evidence,
        cannot_confirm: envelope.cannot_confirm,
        rows,
      },
    },
    unified_rows: rows,
    selected_a_rows: 0,
    selected_hk_rows: envelope.selected_rows,
    selected_total_rows: envelope.selected_rows,
    selection_mode: "HISTORICAL_BACKFILL_READ_ONLY",
    mode: "BACKFILL",
    backfill_run_id: "hk_connect_historical_recovery_20260928_20260929_r1",
    market: "HK_CONNECT",
    recommendation_status: "WATCH_ONLY",
    RESEARCH_ONLY: true,
    production_allowed: false,
    buy_gate_updated: false,
    orders_sent: false,
    write_performed: false,
  };
}

function approvedA1445StageBackfill() {
  const envelope = aShare1445SelectionEnvelope;
  const rows = envelope.rows.map((row: Record<string, unknown>) => ({ ...row, market: "A" }));
  return {
    ok: true,
    trade_date: envelope.trade_date,
    run_id: envelope.run_id,
    stage: { stage_id: envelope.stage_id, status: envelope.selection_status, display_status: "历史 A 股 14:45 witness-fix 回补。" },
    markets: {
      A: {
        artifact_id: envelope.artifact_id,
        run_id: envelope.run_id,
        raw_artifact_sha256: envelope.raw_artifact_sha256,
        algorithm_id: envelope.algorithm_id,
        algorithm_sha256: envelope.algorithm_sha256,
        status: envelope.selection_status,
        selection_status: envelope.selection_status,
        source_status: envelope.source_status,
        selected_rows: envelope.selected_rows,
        source_rows: envelope.source_rows,
        source_evidence: envelope.source_evidence,
        cannot_confirm: envelope.cannot_confirm,
        rows,
      },
    },
    unified_rows: rows,
    selected_a_rows: envelope.selected_rows,
    selected_hk_rows: 0,
    selected_total_rows: envelope.selected_rows,
    selection_mode: "HISTORICAL_BACKFILL_READ_ONLY",
    mode: "BACKFILL",
    backfill_run_id: "a_share_historical_recovery_20260928_20260929_1445_witnessfix_r3",
    market: "A_SHARE",
    recommendation_status: "WATCH_ONLY",
    RESEARCH_ONLY: true,
    production_allowed: false,
    buy_gate_updated: false,
    orders_sent: false,
    write_performed: false,
  };
}

describe("ordinary stage page with exact approved historical backfill mapping", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });

  function installFetch(
    backfillResult: "approved" | "failed" | "none",
    requested: string[],
    corruptA1445SourceSha = false,
    corruptHKRowStatus = false,
    formalHkRowsFor0925: unknown[] = [],
  ) {
    const fetchMock = vi.fn(async (url: string) => {
      requested.push(url);
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260928", navigation_date: "20260929", stage_dates: ["20260928", "20260929"], future_target_dates: [] });
      }
      if (url === "/api/v3/research/dates") return jsonResponse({ research_dates: [] });
      if (url.startsWith("/api/v3/workbench/stage?")) {
        const query = new URL(url, window.location.origin).searchParams;
        if (query.has("backfill_run_id")) {
          expect(query.get("date")).toBe("20260928");
          expect(["STAGE_0925", "STAGE_0930_0935", "STAGE_0935_0940", "STAGE_0940_0945", "STAGE_0945_1030", "STAGE_1300_1315", "STAGE_1445_1500"])
            .toContain(query.get("stage"));
          const market = query.get("market");
          expect(["A_SHARE", "HK_CONNECT"]).toContain(market);
          const stage = query.get("stage");
          const expectedRunId = market === "A_SHARE"
            ? stage === "STAGE_1445_1500"
              ? "a_share_historical_recovery_20260928_20260929_1445_witnessfix_r3"
              : "a_share_historical_recovery_20260928_20260929_r3"
            : "hk_connect_historical_recovery_20260928_20260929_r1";
          expect(query.get("backfill_run_id")).toBe(expectedRunId);
          if (backfillResult !== "approved") return { ok: false, json: async () => ({}) };
          if (market === "A_SHARE" && stage === "STAGE_0930_0935") return jsonResponse(approvedAStageBackfill());
          if (market === "A_SHARE" && stage === "STAGE_0925") return jsonResponse(approvedA0925StageBackfill());
          if (market === "A_SHARE" && stage === "STAGE_1445_1500") {
            const backfill = approvedA1445StageBackfill();
            if (corruptA1445SourceSha) backfill.markets.A.raw_artifact_sha256 = "0".repeat(64);
            return jsonResponse(backfill);
          }
          if (market === "HK_CONNECT" && ["STAGE_0930_0935", "STAGE_1445_1500"].includes(stage || "")) {
            const backfill = approvedHK0930StageBackfill(stage || "STAGE_0930_0935");
            if (corruptHKRowStatus) {
              const row = backfill.markets.HK.rows[0];
              row.status = row.trade_status === "NO_TRADE" ? "WATCH_ONLY" : "NO_TRADE";
            }
            return jsonResponse(backfill);
          }
          return { ok: false, json: async () => ({}) };
        }
        const date = query.get("date") || "";
        const stage = query.get("stage") || "";
        const payload: any = ordinaryStageReadback(date, stage);
        if (date === "20260928" && stage === "STAGE_0925" && formalHkRowsFor0925.length) {
          payload.unified_rows = formalHkRowsFor0925;
          payload.selected_hk_rows = formalHkRowsFor0925.length;
        }
        return jsonResponse(payload);
      }
      if (url.startsWith("/api/v3/preselection-pools?")) return jsonResponse({ ...blockedPool, trade_date: "20260928" });
      return jsonResponse(blockedPool);
    });
    vi.stubGlobal("fetch", fetchMock);
  }

  it("keeps the captured 20260924 two-column candidate cards and their metric cells unchanged", async () => {
    window.history.replaceState({}, "", "/?date=20260924&stage=STAGE_0930_0935");
    const aRows = rowsFromCapturedCandidateCards(referenceCards20260924.a, "A");
    const hkRows = rowsFromCapturedCandidateCards(referenceCards20260924.hk, "HK");
    expect(aRows).toHaveLength(10);
    expect(hkRows).toHaveLength(10);
    const requested: string[] = [];
    const fetchMock = vi.fn(async (url: string) => {
      requested.push(url);
      if (url === "/api/v1/runs/date-list") return jsonResponse({
        default_date: "20260924", navigation_date: "20260924", stage_dates: ["20260924"], future_target_dates: [],
      });
      if (url === "/api/v3/research/dates") return jsonResponse({ research_dates: [] });
      if (url.startsWith("/api/v3/workbench/stage?")) {
        const query = new URL(url, window.location.origin).searchParams;
        const stage = query.get("stage") || "";
        const rows = stage === "STAGE_0930_0935" ? [...aRows, ...hkRows] : [];
        return jsonResponse({
          ...ordinaryStageReadback(query.get("date") || "", stage),
          unified_rows: rows,
          selected_a_rows: stage === "STAGE_0930_0935" ? aRows.length : 0,
          selected_hk_rows: stage === "STAGE_0930_0935" ? hkRows.length : 0,
          selected_total_rows: rows.length,
        });
      }
      return jsonResponse(blockedPool);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(App);
    const aColumn = await screen.findByTestId("stage-candidates-A");
    const hkColumn = await screen.findByTestId("stage-candidates-HK");
    await waitFor(() => {
      expect(aColumn.querySelectorAll(".candidate-card")).toHaveLength(10);
      expect(hkColumn.querySelectorAll(".candidate-card")).toHaveLength(10);
    });
    expect(aColumn.textContent).toContain("SH.600293 · 排名 1");
    expect(aColumn.textContent).toContain("8.219%");
    expect(aColumn.textContent).toContain("148.973");
    expect(aColumn.textContent).toContain("新闻分该时段未提供");
    expect(aColumn.textContent).toContain("支撑位3.65");
    expect(aColumn.textContent).toContain("压力位3.95");
    expect(aColumn.textContent).toContain("失效位3.65");
    expect(hkColumn.textContent).toContain("HK.02586 · 排名 1");
    expect(hkColumn.textContent).toContain("10.539%");
    expect(hkColumn.textContent).toContain("二筛分63");
    expect(hkColumn.textContent).toContain("支撑位6.48");
    expect(hkColumn.textContent).toContain("压力位7.31");
    expect(hkColumn.textContent).toContain("失效位6.48");
    expect(aColumn.textContent).not.toContain("历史回补·只读");
    expect(hkColumn.textContent).not.toContain("历史回补·只读");
    expect(screen.queryByTestId("approved-backfill-readback")).toBeNull();
    expect(requested.some((url) => url.includes("date=20260924") && url.includes("stage=STAGE_0930_0935"))).toBe(true);
  });

  it("folds the real formal 09:30 failure evidence while approved A/HK history fills both cards", async () => {
    window.history.replaceState({}, "", "/?date=20260928&stage=STAGE_0930_0935");
    const requested: string[] = [];
    installFetch("approved", requested);

    render(App);
    expect(await screen.findByTestId("approved-backfill-readback")).toBeTruthy();
    const aColumn = await screen.findByTestId("stage-candidates-A");
    const hkColumn = await screen.findByTestId("stage-candidates-HK");
    await waitFor(() => {
      expect(aColumn.querySelectorAll(".candidate-card")).toHaveLength(10);
      expect(hkColumn.querySelectorAll(".candidate-card")).toHaveLength(10);
    });

    const formalEvidence = screen.getByTestId("formal-execution-evidence") as HTMLDetailsElement;
    expect(formalEvidence.open).toBe(false);
    const summary = within(formalEvidence).getByText("正式阶段执行证据（历史回补期间默认折叠）");
    await fireEvent.click(summary);
    expect(formalEvidence.open).toBe(true);
    expect(within(formalEvidence).getByText("20260928 · STAGE_0930_0935 · DECLARED_ONLY")).toBeTruthy();
    expect(within(formalEvidence).getByText("A_SHARE · CANNOT_CONFIRM")).toBeTruthy();
    expect(within(formalEvidence).getByText("HK_CONNECT · CANNOT_CONFIRM")).toBeTruthy();
    expect(within(formalEvidence).getAllByText("失败层：EXACT_SELECTION_INPUT_BINDING")).toHaveLength(2);
    expect(formalEvidence.textContent).toContain("来源 0");
    expect(formalEvidence.textContent).toContain("首次失败层：EXACT_SELECTION_INPUT_BINDING");
    expect(formalEvidence.textContent).toContain("all market collectors returned zero-row CANNOT_CONFIRM");
  });

  it("places the exact mapped A/HK ten rows in the original candidate cards and folds full evidence", async () => {
    window.history.replaceState({}, "", "/?date=20260928&stage=STAGE_0930_0935");
    const requested: string[] = [];
    installFetch("approved", requested);

    render(App);
    expect(await screen.findByTestId("approved-backfill-readback")).toBeTruthy();
    const aColumn = await screen.findByTestId("stage-candidates-A");
    const hkColumn = await screen.findByTestId("stage-candidates-HK");
    await waitFor(() => {
      expect(aColumn.querySelectorAll(".candidate-card")).toHaveLength(10);
      expect(hkColumn.querySelectorAll(".candidate-card")).toHaveLength(10);
    });
    expect(within(aColumn).getByText("普通页回补候选10")).toBeTruthy();
    expect(aColumn.textContent).toContain("10 条 · 历史回补·只读");
    expect(hkColumn.textContent).toContain("10 条 · 历史回补·只读");
    expect(within(aColumn).getAllByText("未知")).toHaveLength(80);
    expect(within(aColumn).getAllByText("所选阶段计划验证")).toHaveLength(10);
    expect(within(hkColumn).getAllByText("阶段涨幅")).toHaveLength(10);
    expect(within(hkColumn).getAllByText("二筛分")).toHaveLength(10);
    expect(within(hkColumn).getAllByText("所选阶段计划验证")).toHaveLength(10);
    expect(aColumn.querySelectorAll(".candidate-head b")).toHaveLength(10);
    expect(hkColumn.querySelectorAll(".candidate-head b")).toHaveLength(10);
    expect(hkColumn.textContent).toContain("NO_BUY · NO_TRADE");
    expect(hkColumn.textContent).toContain("NO_BUY · WATCH_ONLY");
    const timeline = screen.getByLabelText("七阶段上下文");
    expect(timeline.querySelector(".section-heading p")?.textContent).toContain("A股 10 / 港股通 10 · 历史回补·只读");
    const tile = within(timeline).getByRole("button", { name: /2\. 09:30-09:35/ });
    expect(tile.textContent).toContain("A股 10 / 港股通 10 · 历史回补·只读");
    expect(tile.textContent).toContain("历史回补已恢复（只读）");
    const stagePanel = screen.getByTestId("stage-candidates-A").closest(".stage-panel");
    expect(stagePanel?.querySelector(".section-heading p")?.textContent).toContain("历史回补已恢复（只读）");
    expect(stagePanel?.querySelector(".stage-display-status")?.textContent).toContain("历史回补已恢复（只读）");
    expect(stagePanel?.querySelector(".stage-display-status")?.textContent).not.toContain("CANNOT_CONFIRM");
    expect(screen.queryByTestId("backfill-historical-rows")).toBeNull();
    const evidenceDetails = screen.getByTestId("approved-backfill-evidence") as HTMLDetailsElement;
    expect(evidenceDetails.open).toBe(false);
    expect(evidenceDetails.querySelector("p")?.textContent).toContain("正式阶段状态=CANNOT_CONFIRM");
    expect(evidenceDetails.querySelector("p")?.textContent).toContain("formal run_id=");
    await fireEvent.click(within(evidenceDetails).getByText(/完整来源、run、取数时间与缺项证据/));
    expect(screen.getAllByText(/正式阶段状态=CANNOT_CONFIRM/)).toHaveLength(1);
    expect(screen.getByText(/SelectionStore run_id=run-36f4b1fc50fdd609a7aa46b7 · artifact_id=selection-36f4b1fc50fdd609a7aa46b7 · raw_artifact_sha256=470e8e2c9015dbaefc6d5065b8d4cf8226fcd887b4e56b76ef70435ed0bc13b3/)).toBeTruthy();
    expect(screen.getByText("实际取数开始：2026-09-29T01:55:22.910230+08:00")).toBeTruthy();
    expect(screen.getByText("实际响应收到：2026-09-29T01:55:27.982433+08:00")).toBeTruthy();
    const hkCard = screen.getByTestId("approved-backfill-HK_CONNECT");
    expect(await within(hkCard).findByText(/SelectionStore run_id=run-1f3857be91dbb7b30df2559f · artifact_id=selection-1f3857be91dbb7b30df2559f · raw_artifact_sha256=e35933881cae68b649fa806d7084dd493550044c9fa316158a1b5da904603358/)).toBeTruthy();
    expect(hkColumn.querySelectorAll(".candidate-head b")).toHaveLength(10);
    expect(within(hkColumn).getAllByText("NO_BUY · NO_TRADE")).toHaveLength(9);
    expect(within(hkColumn).getAllByText("NO_BUY · WATCH_ONLY")).toHaveLength(1);
    expect(within(hkCard).getByText(/缺项=1 · RESEARCH_ONLY=true/)).toBeTruthy();
    await fireEvent.click(within(hkCard).getByText("全部 CANNOT_CONFIRM 缺项（1）"));
    expect(within(hkCard).getByText("HK_FUTU_HISTORICAL_ACTIVE_SNAPSHOT_UNAVAILABLE")).toBeTruthy();
    await fireEvent.click(within(hkCard).getByText(/全部历史来源证据/));
    expect(within(hkCard).getByText("live_hkgainer_lane=NOT_ASSERTED")).toBeTruthy();
    expect(screen.getByText("普通页回补候选10")).toBeTruthy();
    expect(tile.textContent).toContain("历史回补已恢复（只读）");

    await fireEvent.click(screen.getByText("全部 CANNOT_CONFIRM 缺项（222）"));
    expect(await screen.findByText("CANNOT_CONFIRM_APPROVED_FIXTURE_222")).toBeTruthy();
    expect(screen.getByTestId("approved-backfill-A_SHARE").querySelectorAll("ol > li")).toHaveLength(222);
    expect(requested.filter((url) => {
      const query = new URL(url, window.location.origin).searchParams;
      return url.startsWith("/api/v3/workbench/stage?")
        && query.has("backfill_run_id")
        && query.get("stage") === "STAGE_0930_0935"
        && query.get("market") === "A_SHARE";
    })).toHaveLength(1);
  });

  it("follows the ordinary history link to the approved A0930 identity and reads ten verified rows", async () => {
    window.history.replaceState({}, "", "/?date=20260730&stage=STAGE_0925");
    const requested: string[] = [];
    installFetch("approved", requested);

    render(App);
    await waitFor(() => expect(requested.some((url) => {
      if (!url.startsWith("/api/v3/workbench/stage?")) return false;
      const query = new URL(url, window.location.origin).searchParams;
      return !query.has("backfill_run_id") && query.get("date") === "20260730";
    })).toBe(true));
    const link = await screen.findByTestId("raw194-backfill-link");
    const href = new URL(link.getAttribute("href") || "", window.location.origin);
    expect(href.searchParams.get("date")).toBe("20260928");
    expect(href.searchParams.get("stage")).toBe("STAGE_0930_0935");
    expect(href.searchParams.get("market")).toBe("A_SHARE");
    expect(href.searchParams.get("backfill_run_id")).toBe("a_share_historical_recovery_20260928_20260929_r3");

    window.history.replaceState({}, "", href.pathname + href.search);
    window.dispatchEvent(new PopStateEvent("popstate"));

    expect(await screen.findByTestId("backfill-readback")).toBeTruthy();
    const aColumn = await screen.findByTestId("stage-candidates-A");
    await waitFor(() => expect(aColumn.querySelectorAll(".candidate-card")).toHaveLength(10));
    expect(aColumn.textContent).toContain("历史回补·只读");
    expect(screen.queryByTestId("backfill-historical-rows")).toBeNull();
    await fireEvent.click(screen.getByText("完整来源、run 与缺项证据"));
    expect(screen.getByText(/绑定日期 20260928 · 阶段 STAGE_0930_0935 · 市场 A_SHARE · backfill_run_id=a_share_historical_recovery_20260928_20260929_r3/)).toBeTruthy();
    expect(screen.getByText(/rows=10\/190/)).toBeTruthy();
    const stageRequests = requested.filter((url) => url.startsWith("/api/v3/workbench/stage?")
      && new URL(url, window.location.origin).searchParams.has("backfill_run_id"));
    expect(stageRequests.length).toBeGreaterThan(0);
    for (const url of stageRequests) {
      const requested = new URL(url, window.location.origin).searchParams;
      expect(requested.get("date")).toBe("20260928");
      expect(requested.get("stage")).toBe("STAGE_0930_0935");
      expect(requested.get("market")).toBe("A_SHARE");
      expect(requested.get("backfill_run_id")).toBe("a_share_historical_recovery_20260928_20260929_r3");
    }
  });

  it("shows the reviewed 09:25 rows with unknown previous-close change instead of the zero sentinel", async () => {
    const rows = aShare0925SelectionManifest.selection_envelope.rows;
    expect(rows).toHaveLength(10);
    expect(rows.every((row: Record<string, unknown>) => row.prev_close_price === null
      && row.current_change_pct === 0 && row.qmt_gap_pct === 0)).toBe(true);
    expect(rows.every((row: Record<string, unknown>) => row.action_level === "NO_BUY"
      && row.trade_status === "WATCH_ONLY" && row.formal_eligible === false)).toBe(true);

    window.history.replaceState({}, "", "/?date=20260928&stage=STAGE_0925");
    const requested: string[] = [];
    // Synthetic formal rows verify that an existing HK side remains counted while A uses its approved backfill.
    const formalHkRows = Array.from({ length: 10 }, (_, index) => ({
      market: "HK",
      code: `HK.0925${String(index + 1).padStart(2, "0")}`,
      name: `测试正式港股候选${index + 1}`,
      rank: index + 1,
      score: 60 - index,
      trade_status: "WATCH_ONLY",
      stage_display_decision: "观察",
    }));
    installFetch("approved", requested, false, false, formalHkRows);

    render(App);
    const aColumn = await screen.findByTestId("stage-candidates-A");
    const hkColumn = await screen.findByTestId("stage-candidates-HK");
    await waitFor(() => expect(aColumn.querySelectorAll(".candidate-card")).toHaveLength(10));
    expect(hkColumn.querySelectorAll(".candidate-card")).toHaveLength(10);
    expect(aColumn.textContent).toContain("10 条 · 历史回补·只读");
    expect(hkColumn.textContent).toContain("10 条");
    expect(hkColumn.textContent).not.toContain("历史回补·只读");
    const timeline = screen.getByLabelText("七阶段上下文");
    expect(timeline.querySelector(".section-heading p")?.textContent).toContain("A股 10 / 港股通 10 · 历史回补·只读");
    const tile = within(timeline).getByRole("button", { name: /1\. 港股通09:20 \/ A股09:25竞价选股/ });
    expect(tile.textContent).toContain("A股 10 / 港股通 10 · 历史回补·只读");
    expect(tile.textContent).toContain("历史回补已恢复（只读）");
    const stagePanel = screen.getByTestId("stage-candidates-A").closest(".stage-panel");
    expect(stagePanel?.querySelector(".section-heading p")?.textContent).toContain("历史回补已恢复（只读）");
    expect(stagePanel?.querySelector(".stage-display-status")?.textContent).not.toContain("CANNOT_CONFIRM");
    expect(within(aColumn).getAllByText("昨收缺失，涨幅不可确认")).toHaveLength(10);
    expect(within(aColumn).getAllByText("NO_BUY · WATCH_ONLY · status 集合竞价成交代理观察")).toHaveLength(10);
    expect(within(aColumn).queryByText(/^0(?:\.0+)?%$/)).toBeNull();
    const evidence = screen.getByTestId("approved-backfill-evidence");
    expect((evidence as HTMLDetailsElement).open).toBe(false);
    expect(evidence.querySelector("p")?.textContent).toContain("正式阶段状态=CANNOT_CONFIRM");
    await fireEvent.click(within(evidence).getByText(/完整来源、run、取数时间与缺项证据/));
    const card = screen.getByTestId("approved-backfill-A_SHARE");
    expect(screen.getAllByText(/正式阶段状态=CANNOT_CONFIRM/)).toHaveLength(1);
    expect(await within(card).findByText(/SelectionStore run_id=run-de75da94f0188643abf4529e · artifact_id=selection-de75da94f0188643abf4529e · raw_artifact_sha256=14b1ab778756a4dd7750abc86bc8a785c3ec7479885b5a0501e6680ee9f0e069/)).toBeTruthy();
    expect(within(card).getByText(/实际取数开始：竞价 canary 请求 2026-09-29T08:11:10.342799\+08:00/)).toBeTruthy();
    expect(within(card).getByText(/实际响应收到：竞价 canary 响应 2026-09-29T08:11:10.518328\+08:00/)).toBeTruthy();
    expect(within(card).getByText(/缺项=3/)).toBeTruthy();
    expect(requested.some((url) => url.includes("backfill_run_id=a_share_historical_recovery_20260928_20260929_r3")
      && url.includes("stage=STAGE_0925"))).toBe(true);
    expect(requested.some((url) => url.includes("backfill_run_id=hk_connect_historical_recovery_20260928_20260929_r1")
      && url.includes("stage=STAGE_0925"))).toBe(false);
  });

  it("maps the reviewed A/HK 14:45 tuples to their exact read-only run namespaces", async () => {
    window.history.replaceState({}, "", "/?date=20260928&stage=STAGE_1445_1500");
    const requested: string[] = [];
    installFetch("approved", requested);

    render(App);
    const aColumn = await screen.findByTestId("stage-candidates-A");
    const hkColumn = await screen.findByTestId("stage-candidates-HK");
    await waitFor(() => {
      expect(aColumn.querySelectorAll(".candidate-card")).toHaveLength(10);
      expect(hkColumn.querySelectorAll(".candidate-card")).toHaveLength(10);
    });
    expect(aColumn.textContent).toContain("10 条 · 历史回补·只读");
    expect(hkColumn.textContent).toContain("10 条 · 历史回补·只读");
    expect(within(hkColumn).getAllByText("NO_BUY · NO_TRADE")).toHaveLength(8);
    expect(within(hkColumn).getAllByText("NO_BUY · WATCH_ONLY")).toHaveLength(2);
    await fireEvent.click(within(screen.getByTestId("approved-backfill-evidence")).getByText(/完整来源、run、取数时间与缺项证据/));
    const aCard = screen.getByTestId("approved-backfill-A_SHARE");
    const hkCard = screen.getByTestId("approved-backfill-HK_CONNECT");
    expect(await within(aCard).findByText(/SelectionStore run_id=run-62c7de976a7f879cd3615250 · artifact_id=selection-62c7de976a7f879cd3615250 · raw_artifact_sha256=c0f2d34bf5d14dfcba325b1b6a61fd82009aa29c1375dbe126ea0fa8cd353ddc/)).toBeTruthy();
    expect(await within(hkCard).findByText(/SelectionStore run_id=run-1e534c14396c0fb19f51d93d/)).toBeTruthy();
    const bindings = requested
      .filter((url) => url.startsWith("/api/v3/workbench/stage?") && url.includes("backfill_run_id="))
      .map((url) => new URL(url, window.location.origin).searchParams);
    expect(bindings.some((query) => query.get("stage") === "STAGE_1445_1500"
      && query.get("market") === "A_SHARE"
      && query.get("backfill_run_id") === "a_share_historical_recovery_20260928_20260929_1445_witnessfix_r3")).toBe(true);
    expect(bindings.some((query) => query.get("stage") === "STAGE_1445_1500"
      && query.get("market") === "HK_CONNECT"
      && query.get("backfill_run_id") === "hk_connect_historical_recovery_20260928_20260929_r1")).toBe(true);
  });

  it("rejects an A 14:45 response with a different source artifact SHA", async () => {
    window.history.replaceState({}, "", "/?date=20260928&stage=STAGE_1445_1500");
    const requested: string[] = [];
    installFetch("approved", requested, true);

    render(App);
    const aColumn = await screen.findByTestId("stage-candidates-A");
    await within(aColumn).findByText(/历史回补读取失败 · CANNOT_CONFIRM/);
    expect(aColumn.querySelectorAll(".candidate-card")).toHaveLength(0);
  });

  it("rejects an HK historical response that rewrites NO_TRADE as WATCH_ONLY", async () => {
    window.history.replaceState({}, "", "/?date=20260928&stage=STAGE_0930_0935");
    const requested: string[] = [];
    installFetch("approved", requested, false, true);

    render(App);
    const hkColumn = await screen.findByTestId("stage-candidates-HK");
    await within(hkColumn).findByText(/历史回补读取失败 · CANNOT_CONFIRM/);
    expect(hkColumn.querySelectorAll(".candidate-card")).toHaveLength(0);
  });

  it("does not request or display a mapped result for another date", async () => {
    window.history.replaceState({}, "", "/?date=20260929&stage=STAGE_0930_0935");
    const requested: string[] = [];
    installFetch("none", requested);

    render(App);
    await waitFor(() => expect(requested.some((url) => {
      const query = new URL(url, window.location.origin).searchParams;
      return url.startsWith("/api/v3/workbench/stage?") && query.get("date") === "20260929";
    })).toBe(true));
    expect(requested.some((url) => url.includes("backfill_run_id="))).toBe(false);
    expect(screen.queryByTestId("approved-backfill-readback")).toBeNull();
    expect(screen.queryByText("普通页回补候选1")).toBeNull();
  });

  it("keeps the exact stage CANNOT_CONFIRM when the mapped read fails", async () => {
    window.history.replaceState({}, "", "/?date=20260928&stage=STAGE_0930_0935");
    const requested: string[] = [];
    installFetch("failed", requested);

    render(App);
    const aColumn = await screen.findByTestId("stage-candidates-A");
    await within(aColumn).findByText(/历史回补读取失败 · CANNOT_CONFIRM/);
    expect(aColumn.querySelectorAll(".candidate-card")).toHaveLength(0);
    expect(screen.queryByText("普通页回补候选1")).toBeNull();
    const timeline = screen.getByLabelText("七阶段上下文");
    const tile = within(timeline).getByRole("button", { name: /2\. 09:30-09:35/ });
    expect(tile.textContent).toContain("A股 CANNOT_CONFIRM / 港股通 CANNOT_CONFIRM");
    expect(tile.textContent).toContain("历史回补读取失败 · CANNOT_CONFIRM");
    expect(tile.textContent).not.toContain("历史回补已恢复");
    expect(tile.textContent).not.toContain("PASS");
    const stagePanel = screen.getByTestId("stage-candidates-A").closest(".stage-panel");
    expect(stagePanel?.querySelector(".stage-display-status")?.textContent).toContain("历史回补读取失败 · CANNOT_CONFIRM");
    expect(requested.some((url) => url.includes("backfill_run_id=a_share_historical_recovery_20260928_20260929_r3")
      && url.includes("stage=STAGE_0930_0935"))).toBe(true);
  });
});

describe("Issue21 exact URL navigation and ordinary HK source regressions", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  function stagePayload(date: string, stageId: string, hkRows: unknown[] = [], hkMode = "CANNOT_CONFIRM") {
    return {
      ok: true,
      trade_date: date,
      stage: { stage_id: stageId, status: "CANNOT_CONFIRM", display_status: "正式阶段证据 CANNOT_CONFIRM" },
      markets: {
        A: { status: "CANNOT_CONFIRM", selection_status: "CANNOT_CONFIRM", source_status: "CANNOT_CONFIRM", selected_rows: 0, rows: [] },
        HK: { status: "CANNOT_CONFIRM", selection_status: "CANNOT_CONFIRM", source_status: "CANNOT_CONFIRM", display_mode: hkMode, selected_rows: 0, rows: [] },
      },
      unified_rows: hkRows,
      selected_a_rows: 0,
      selected_hk_rows: hkRows.length,
      selected_total_rows: hkRows.length,
      selection_mode: "FORMAL_STAGE_READBACK",
      production_allowed: false,
      buy_gate_updated: false,
      orders_sent: false,
    };
  }

  function hk0930Backfill() {
    const requiredEvidence = [
      "route=shared_pytdx_exhq_hk_exact_d1_top100",
      "hk_selection_mode=TDXPY_EXHQ_D1_TOP100_OBSERVATION",
      "hk_historical_active_snapshot=UNAVAILABLE_NO_ASOF_INTERFACE",
      "live_hkgainer_lane=NOT_ASSERTED",
      "due_status=HISTORICAL_BACKFILL",
      "hk_d1_status=STRICT_0_2_READY",
      "hk_d1_membership=exact_date_top100",
      "selection_contract=V3_TOP10_RECOMMENDATION",
    ];
    const rows = Array.from({ length: 10 }, (_, index) => ({
      market: "HK",
      code: `HK.${String(90000 + index).padStart(5, "0")}`,
      name: "隔离历史回补行",
      rank: index + 1,
      status: "WATCH_ONLY",
      trade_status: "WATCH_ONLY",
      action_level: "NO_BUY",
      source_mode: "HK_CONNECT_FOUR_LANE",
      formal_eligible: false,
    }));
    return {
      ok: true,
      trade_date: "20260928",
      run_id: "run-1f3857be91dbb7b30df2559f",
      stage: { stage_id: "STAGE_0930_0935", status: "PARTIAL_WITH_ROWS", display_status: "回补历史港股通观察行" },
      markets: {
        HK: {
          artifact_id: "selection-1f3857be91dbb7b30df2559f",
          run_id: "run-1f3857be91dbb7b30df2559f",
          raw_artifact_sha256: "e35933881cae68b649fa806d7084dd493550044c9fa316158a1b5da904603358",
          algorithm_id: "V3_STAGE_SELECTION_V1",
          algorithm_sha256: "fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506",
          status: "PARTIAL_WITH_ROWS",
          selection_status: "PARTIAL_WITH_ROWS",
          source_status: "PARTIAL_WITH_ROWS",
          selected_rows: 10,
          source_rows: 100,
          source_evidence: requiredEvidence,
          cannot_confirm: ["CANNOT_CONFIRM_HISTORICAL_ACTIVE_SNAPSHOT"],
          rows,
        },
      },
      unified_rows: rows,
      selected_a_rows: 0,
      selected_hk_rows: 10,
      selected_total_rows: 10,
      selection_mode: "HISTORICAL_BACKFILL_READ_ONLY",
      mode: "BACKFILL",
      backfill_run_id: "hk_connect_historical_recovery_20260928_20260929_r1",
      market: "HK_CONNECT",
      recommendation_status: "WATCH_ONLY",
      RESEARCH_ONLY: true,
      production_allowed: false,
      buy_gate_updated: false,
      orders_sent: false,
      write_performed: false,
    };
  }

  it("binds URL date and stage before catalogs, while pending research dates do not block ordinary navigation", async () => {
    window.history.replaceState({}, "", "/?date=20260928&stage=STAGE_0930_0935");
    let resolveDateList!: (response: unknown) => void;
    let resolveResearchDates!: (response: unknown) => void;
    const dateList = new Promise((resolve) => { resolveDateList = resolve; });
    const researchDates = new Promise((resolve) => { resolveResearchDates = resolve; });
    const requestedStages: Array<{ date: string | null; stage: string | null; backfill: boolean }> = [];
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/v1/runs/date-list") return dateList;
      if (url === "/api/v3/research/dates") return researchDates;
      if (url.startsWith("/api/v3/workbench/stage?")) {
        const query = new URL(url, window.location.origin).searchParams;
        requestedStages.push({ date: query.get("date"), stage: query.get("stage"), backfill: query.has("backfill_run_id") });
        return Promise.resolve(jsonResponse(stagePayload(query.get("date") || "", query.get("stage") || "")));
      }
      if (url.startsWith("/api/v3/preselection-pools?")) {
        return Promise.resolve(jsonResponse({ data_status: "CANNOT_CONFIRM", trade_date: "20260928", rows: [], pools: [] }));
      }
      return Promise.resolve(jsonResponse({}));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(App);
    const dateInput = screen.getByLabelText("交易日（日历选择）") as HTMLInputElement;
    const stageInput = screen.getByRole("combobox", { name: "阶段" }) as HTMLSelectElement;
    expect(dateInput.value).toBe("2026-09-28");
    expect(stageInput.value).toBe("STAGE_0930_0935");

    resolveDateList(jsonResponse({
      default_date: "20260929",
      navigation_date: "20260929",
      stage_dates: ["20260928", "20260929"],
      future_target_dates: [],
      research_dates: [],
    }));
    await waitFor(() => expect(requestedStages.some((row) =>
      row.date === "20260928" && row.stage === "STAGE_0930_0935" && !row.backfill,
    )).toBe(true));
    expect(dateInput.value).toBe("2026-09-28");
    expect(stageInput.value).toBe("STAGE_0930_0935");

    resolveResearchDates(jsonResponse({ research_dates: ["20261002"] }));
    await waitFor(() => expect(dateInput.value).toBe("2026-09-28"));
    expect(stageInput.value).toBe("STAGE_0930_0935");
  });

  it("keeps the exact ordinary HK row when a valid mapped backfill also exists", async () => {
    window.history.replaceState({}, "", "/?date=20260928&stage=STAGE_0930_0935");
    const ordinaryRow = {
      market: "HK", code: "HK.00004", name: "普通阶段港股", rank: 1,
      stage_display_decision: "观察", recommendation_status: "WATCH_ONLY", formal_eligible: false,
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/v1/runs/date-list") return jsonResponse({
        default_date: "20260929", navigation_date: "20260929", stage_dates: ["20260928", "20260929"], future_target_dates: [],
      });
      if (url === "/api/v3/research/dates") return jsonResponse({ research_dates: [] });
      if (url.startsWith("/api/v3/workbench/stage?")) {
        const query = new URL(url, window.location.origin).searchParams;
        if (query.has("backfill_run_id")) {
          if (query.get("market") === "HK_CONNECT" && query.get("stage") === "STAGE_0930_0935") {
            return jsonResponse(hk0930Backfill());
          }
          return { ok: false, json: async () => ({}) };
        }
        return jsonResponse(stagePayload(query.get("date") || "", query.get("stage") || "", [ordinaryRow]));
      }
      if (url.startsWith("/api/v3/preselection-pools?")) return jsonResponse({
        data_status: "CANNOT_CONFIRM", trade_date: "20260928", rows: [], pools: [],
      });
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(App);
    const hkColumn = await screen.findByTestId("stage-candidates-HK");
    await waitFor(() => expect(hkColumn.textContent).toContain("HK.00004 · 排名 1"));
    expect(hkColumn.textContent).toContain("普通阶段港股");
    expect(hkColumn.textContent).not.toContain("HK.90000");
    expect(hkColumn.textContent).not.toContain("历史回补·只读");
    expect(vi.mocked(fetch).mock.calls.some(([input]) => {
      const query = new URL(String(input), window.location.origin).searchParams;
      return query.get("backfill_run_id") === "hk_connect_historical_recovery_20260928_20260929_r1"
        && query.get("market") === "HK_CONNECT";
    })).toBe(true);
  });

  it("rejects an impossible URL calendar date instead of binding it as historical", async () => {
    window.history.replaceState({}, "", "/?date=20260931&stage=STAGE_0930_0935");
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/v1/runs/date-list") return jsonResponse({
        default_date: "20261001", navigation_date: "20261001", stage_dates: ["20261001"], future_target_dates: [],
      });
      if (url === "/api/v3/research/dates") return jsonResponse({ research_dates: [] });
      if (url.startsWith("/api/v3/workbench/stage?")) {
        const query = new URL(url, window.location.origin).searchParams;
        return jsonResponse(stagePayload(query.get("date") || "", query.get("stage") || ""));
      }
      return jsonResponse({ data_status: "CANNOT_CONFIRM", trade_date: "20261001", rows: [], pools: [] });
    }));

    render(App);
    const dateInput = await screen.findByLabelText("交易日（日历选择）") as HTMLInputElement;
    await waitFor(() => expect(dateInput.value).toBe("2026-10-01"));
    expect((screen.getByRole("combobox", { name: "阶段" }) as HTMLSelectElement).value).toBe("STAGE_0930_0935");
  });
});
