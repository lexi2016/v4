import { cleanup, render, screen, within, fireEvent, waitFor } from "@testing-library/vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import ReviewView from "./ReviewView.vue";

const rows = (count: number, kind: string) => Array.from({ length: count }, (_, index) => ({
  trade_date: "20260730", code: `${kind}-${index + 1}`, name: `${kind} ${index + 1}`,
}));

const payload = {
  trade_date: "20260730",
  market_reviews: {
    A: {
      schema_version: "v3_5.a_share_review.v1", trade_date: "20260730", status: "READY", headline: "A-share review", market_regime: "CANNOT_CONFIRM", risk_tone: "CANNOT_CONFIRM",
      big_picture: rows(9, "picture"), mainlines: [{ trade_date: "20260730", name: "AI mainline" }],
      core_stocks: [], observation_pool: rows(12, "observation"), next_day_trigger_tree: rows(4, "trigger"),
      quality_gate: rows(7, "gap"), cannot_confirm: ["SOURCE_GAP"],
      source_role: "V3_5_NATIVE_CLOSE_MODEL", source_evidence: [{ id: "panel", name: "selector close panel" }],
      close_chain: { schema_version: "v3_5.close_review_chain.v1", trade_date: "20260730", status: "PARTIAL_REVIEW", cannot_confirm: ["FUPAN_VIDEO_CHECK"], nodes: Array.from({ length: 10 }, (_, index) => ({ task_id: `task-${index}`, slot: `${15 + index}:00`, label: `node ${index}`, status: index < 3 ? "READY" : "NOT_MATERIALIZED", reason: "fixture" })) },
      model_review: {
        schema_version: "replay_model_v1", status: "INDEPENDENT_CLOSE_REVIEW_READY", run_id: "task7-test",
        review_date: "20260730", as_of: "2026-07-30T15:30:00+08:00", objective: "D0 independent review",
        producer_type: "DETERMINISTIC_PYTHON", learning_status: "LEARNING_HYPOTHESIS_FAIL",
        formal_generalization: "FORMAL_GENERALIZATION_PENDING", model_promotion: "NO_MODEL_PROMOTED",
        semantic_model_status: "DISABLED_BY_V3_5_NO_LLM_PRODUCTION_RULE", semantic_model_call_count: 0,
        visibility_stage: "POST_CLOSE_REVIEW_ONLY", target_video_review_status: "CANNOT_CONFIRM_TARGET_VIDEO_NOT_CONSUMED",
        previous_plan_realization: "CANNOT_CONFIRM_PREVIOUS_PLAN_REALIZATION_WITHOUT_BOUND_PRIOR_PLAN",
        market_summary: { regime: "repair_or_positive_breadth", up_count: 3200, down_count: 2200, flat_count: 136, limit_up_count: 41, limit_down_count: 8, amount_yi: 15555, market_width: 0.578, external_environment: "CANNOT_CONFIRM_EXTERNAL_MARKET_DETAIL", boundary: "close evidence only" },
        board_rows: [{ board_name: "通信", board_role: "strong_branch", median_pct_change: 1.2, up_ratio: 0.7, counterevidence: "rotation risk", trigger: "breadth improves" }],
        anchor_role_rows: [{ stock_code: "600000", stock_name: "浦发银行", board_name: "银行", primary_role: "capacity_anchor", pct_change: 1.3, role_explanation: "capacity evidence", invalidation: "volume fails", recommendation_status: "WATCH_ONLY" }],
        shadow_watch_pool: { boundary: "SHADOW_ONLY", abstain: true, abstain_reason: "WEAK_MARKET_WIDTH_ALLOW_ABSTENTION", core: [], conditional: [{ stock_code: "600000", stock_name: "浦发银行", primary_role: "capacity_anchor", recommendation_status: "WATCH_ONLY" }], observation_or_risk: [] },
        safety: { SHADOW_ONLY: true, NOT_BUY_ADVICE: true, NO_BUY_GATE: true },
      },
      source_sha256: "a".repeat(64), write_policy: "review_only_read_only",
      production_allowed: false, buy_gate_updated: false, orders_sent: false,
    },
    HK: { market: "HK", model_selection_review: {
      status: "MODEL_REVIEW_READY", primary_kpi: "全港股通收盘涨幅Top20覆盖率",
      models: { "0.2_prob_active": { selected_count: 100, hit_count: 3 } },
      stage_union: { selected_count: 17, hit_count: 2 }, row_counts: { close_top20: 20, stage_rows: 17 },
      top20_attribution: [{ rank: 1, code: "HK.00325", name: "布鲁可", pct_chg_close: 15.9343, model_0_2_hit: true, stage_union_hit: false, classification: "model_only" }],
      cannot_confirm: ["HK_GAP"],
    } },
  },
  production_allowed: false, buy_gate_updated: false, orders_sent: false,
} as const;

const researchRows = (count: number, kind: string, extra: Record<string, unknown> = {}) =>
  Array.from({ length: count }, (_, index) => ({
    code: `${kind}-${index + 1}`,
    name: `${kind} ${index + 1}`,
    tag: `${kind}-tag-${index + 1}`,
    ...extra,
  }));

const actualShapeResearchReview = {
  schema_version: "daily_research_review.v1",
  status: "READY",
  artifact_status: "READY",
  trade_date: "20260911",
  target_date: "2026-09-11",
  source_role: "VIBE_DUANXIAN_DAILY_REVIEW",
  source_artifact_sha256: "b".repeat(64),
  data_as_of: "2026-09-11 17:25 CST",
  generation_status: "EXTERNAL_SOURCE_READ_ONLY",
  generation: { status: "EXTERNAL_SOURCE_READ_ONLY", owner: "CANNOT_CONFIRM" },
  cannot_confirm: ["V4_DAILY_RESEARCH_REVIEW_GENERATOR_NOT_CONNECTED"],
  research_only: true,
  production_allowed: false,
  buy_gate_updated: false,
  orders_sent: false,
  focus: {
    emotion_phase: "修复",
    market_oneliner: "广度承压，局部题材保持活跃。",
    focus_directions: ["观察反馈", "跟踪题材"],
    risk_alerts: ["亏钱效应"],
    verification_items: ["次日验证"],
  },
  market_breadth: {
    available: true, date: "2026-09-11", up: 619, down: 4619, flat: 46,
    up_down_scope: "A股全市场", amount_yi: 19719, universe: 5284,
    deep_up_5_incl: 18, deep_down_5: 125, dist_scope: "全市场", dist_available: true,
    dist_partial: false, requests: [{ provider: "fixture", status: "READY" }],
  },
  feedback_matrix: {
    available: true, prev_date: "2026-09-10", source: "fixture", sample: 35, coverage: 35,
    coverage_rate: 1, partial: false, order: ["晋级涨停", "收红", "跌超5%", "平盘", "跌停"],
    matrix: { "首板": { "晋级涨停": 4, "收红": 7, "跌超5%": 3 } },
    details: researchRows(35, "反馈", { board: 1, prev_tier: "首板", result: "收红", ret: 1.2, sector: "fixture" }),
    note: "fixture preserves the 35 detail rows",
  },
  money_effect: {
    available: true, sample: 35, coverage: 35, coverage_rate: 1, partial: false,
    avg: 0.57, median: -1.9, positive_rate: 0.457, limit_up_again_rate: 0.2, source: "fixture", prev_date: "2026-09-10",
  },
  loss_effect: {
    available: true, deep_loss_5_count: 8, deep_loss_5_rate: 0.229, deep_loss_7_count: 6,
    limit_down_count: 3, worst: -10.01, market_limit_down: 8, coverage_rate: 1, note: "fixture",
  },
  promotion: {
    available: true, prev_date: "2026-09-10", tiers: { "1进2": { base: 26, promoted: 4, rate: 0.154 }, "2进3": { base: 5, promoted: 2, rate: 0.4 }, "3板以上晋级": { base: 4, promoted: 1, rate: 0.25 } },
    overall: { base: 35, promoted: 7, rate: 0.2 }, limit_up_count: 40, prev_limit_up_count: 42,
  },
  ladder_gap: { available: true, highest: 4, tiers: { "4": 1, "3": 2, "2": 4 }, gaps: [], continuous: true, note: "fixture" },
  theme_tree: {
    available: true, date: "2026-09-11", prev_date: "2026-09-10", tag_count: 109,
    themes: Array.from({ length: 10 }, (_, index) => ({
      tag: `题材-${index + 1}`, limit_up: 3, first_boards: 2, consec_boards: 1, highest: 2, broken: 0,
      members: [{ code: `member-${index + 1}`, name: `成员 ${index + 1}`, boards: 2, broken_times: 0, label: "2板" }],
      prev_members: 1, prev_still_up: 1, prev_broken_or_down: 0, first_seal: "093130", last_seal: "130212",
      broken_rate: 0, continuation_rate: 1, state: "延续",
    })),
    concentration: 0.2, covered: 30, total_limit_up: 40, coverage_rate: 0.75,
  },
  event_ledger: {
    available: true, count: 19,
    events: researchRows(19, "事件", { board: "10cm", boards: 2, first_seal: "092500", last_seal: "130212", broken_times: 0, turnover: 4.08, prev_boards: 1, ret: 9.99, sector: "fixture", note: "事件说明" }),
    loss_events: researchRows(11, "亏损", { board: "10cm", boards: 0, broken_times: 3, note: "亏损事件" }),
    gain_events: researchRows(5, "赚钱", { board: "10cm", boards: 4, note: "赚钱事件" }),
    split_events: researchRows(3, "反复", { board: "10cm", boards: 1, broken_times: 7, note: "反复开板" }),
  },
} as const;

const payloadWithActualResearchReview = {
  ...payload,
  research_review: actualShapeResearchReview,
} as const;

describe("ReviewView", () => {
  afterEach(cleanup);

  it("renders the V3 close-model hierarchy without promoting shadow rows to formal core", () => {
    const { container } = render(ReviewView, { props: { payload } });

    expect(screen.getByTestId("a-close-model")).toBeTruthy();
    expect(screen.getAllByTestId("close-chain-row")).toHaveLength(10);
    expect(screen.getByText("收盘自动链 · V3 图谱顺序")).toBeTruthy();
    expect(screen.getByText("本地复盘引擎 · 独立结论")).toBeTruthy();
    expect(screen.getByText("本地复盘引擎 · 板块判断")).toBeTruthy();
    expect(screen.getByText("本地复盘引擎 · 个股角色判断")).toBeTruthy();
    expect(screen.getByText("视频差距审计")).toBeTruthy();
    expect(screen.getByText("产品层 · 市场总览")).toBeTruthy();
    expect(screen.getByText("产品层 · 前计划兑现")).toBeTruthy();
    expect(screen.getByText("产品层 · 影子观察池（弱市弃权）")).toBeTruthy();
    expect(screen.getAllByTestId("model-board-row")).toHaveLength(1);
    expect(screen.getAllByTestId("model-role-row")).toHaveLength(1);
    expect(screen.getAllByTestId("shadow-watch-row")).toHaveLength(1);
    expect(screen.getAllByTestId("quality-gap-row")).toHaveLength(7);
    expect(screen.getByText("正式核心票未建立")).toBeTruthy();
    expect(screen.getAllByText(/V3_5_NATIVE_CLOSE_MODEL/)).toHaveLength(2);
    expect(screen.getByText("selector close panel")).toBeTruthy();
    expect(screen.getByText("SOURCE_GAP")).toBeTruthy();
    expect(screen.getByText("HK 收盘复盘")).toBeTruthy();
    expect(screen.getByText("3/20")).toBeTruthy();
    expect(screen.getByText("2/20")).toBeTruthy();
    expect(screen.getByText("布鲁可")).toBeTruthy();
    expect(screen.getByText("仅0.2")).toBeTruthy();
    expect(screen.queryByText("AI mainline")).toBeNull();
    expect(within(container as HTMLElement).getByText(/production_allowed=false/)).toBeTruthy();
    expect(screen.getByText("a".repeat(64))).toBeTruthy();
  });

  it("does not turn unavailable HK evidence into zero hits", () => {
    const blocked = {
      ...payload,
      market_reviews: {
        ...payload.market_reviews,
        HK: { market: "HK", model_selection_review: {
          status: "REFERENCE_NOT_IMPORTED", models: {}, stage_union: {}, row_counts: {}, close_top20: [], top20_attribution: [], cannot_confirm: ["HK_GAP"],
        } },
      },
    } as const;
    render(ReviewView, { props: { payload: blocked } });

    expect(screen.getByText("HK 收盘证据未物化；不把缺失显示为 0 命中。")).toBeTruthy();
    expect(screen.queryByText("0.2 模型")).toBeNull();
    expect(screen.queryByText("收盘 Top20")).toBeNull();
    expect(screen.queryByText("未命中")).toBeNull();
  });

  it("puts the 16:08 HK close review before the secondary A review", () => {
    const { container } = render(ReviewView, { props: { payload } });
    const labels = Array.from(container.querySelectorAll("section[aria-label]"))
      .map((node) => node.getAttribute("aria-label"));
    expect(screen.getByText("16:08 港股通正式收盘复盘")).toBeTruthy();
    expect(labels.indexOf("HK close review")).toBeGreaterThanOrEqual(0);
    expect(labels.indexOf("A-share review")).toBeGreaterThanOrEqual(0);
    expect(labels.indexOf("HK close review")).toBeLessThan(labels.indexOf("A-share review"));
  });

  it("shows the exact first failure in the shared evidence panel", () => {
    const partialPayload = {
      ...payload,
      trade_date: "20260824",
      market_reviews: {
        ...payload.market_reviews,
        A: {
          ...payload.market_reviews.A,
          trade_date: "20260824",
          status: "PARTIAL_STAGE_EVIDENCE",
          review_surface: { tier: "V3_RICH_PARTIAL", status: "PARTIAL_STAGE_EVIDENCE", trade_date: "20260824" },
          first_failed_layer: {
            layer: "selector", owner: "PANEL", status: "FAILED/CONTRACT", slot: "16:05",
            expected_date: "20260824", observed_date: "20260821", failure_class: "SELECTOR_NOT_READY",
            receipt_path: "data_layer/data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt",
            receipt_sha256: "", next_due: "16:05",
          },
          failure_summary: "selector/PANEL · 期望日期20260824 · 观测日期20260821 · 16:05 FAILED/CONTRACT · ReviewBundle未物化 · receipt/path review_bundle/20260824/receipt.json · review_bundle/20260824/current.json",
          failure_chain: [
            { layer: "selector", owner: "PANEL", status: "FAILED/CONTRACT", expected_date: "20260824", observed_date: "20260821", failure_class: "SELECTOR_NOT_READY", receipt_path: "data_layer/data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt", receipt_sha256: "", next_due: "16:05" },
            { layer: "16:05", owner: "A_SHARE_REVIEW", status: "BLOCKED/CONTRACT", expected_date: "20260824", observed_date: "20260821", failure_class: "SELECTOR_NOT_READY", receipt_path: "", receipt_sha256: "", next_due: "ReviewBundle" },
            { layer: "ReviewBundle", owner: "REVIEW_CORE", status: "NOT_MATERIALIZED", expected_date: "20260824", observed_date: "", failure_class: "UPSTREAM_SELECTOR_BLOCKED", receipt_path: "review_bundle/20260824/receipt.json", receipt_sha256: "", path: "review_bundle/20260824/current.json", next_due: "API/UI" },
            { layer: "API/UI", owner: "V3.5_REVIEW", status: "EVIDENCE_GAP", expected_date: "20260824", observed_date: "", failure_class: "REVIEW_BUNDLE_NOT_MATERIALIZED", receipt_path: "review_bundle/20260824/receipt.json", receipt_sha256: "", path: "/api/v3/review?date=20260824", next_due: "NATURAL_SLOT" },
          ],
        },
      },
    } as any;

    render(ReviewView, { props: { payload: partialPayload } });

    const evidence = screen.getByTestId("review-first-failure-evidence");
    expect(evidence.textContent).toContain("selector/PANEL");
    expect(evidence.textContent).toContain("期望日期20260824");
    expect(evidence.textContent).toContain("观测日期20260821");
    expect(evidence.textContent).toContain("16:05 FAILED/CONTRACT");
    expect(evidence.textContent).toContain("ReviewBundle未物化");
    expect(evidence.textContent).toContain("review_bundle/20260824/current.json");
    expect(screen.getAllByTestId("review-first-failure-row")).toHaveLength(4);
  });

  it("keeps the complete research artifact shape reachable through ReviewView", () => {
    const { container } = render(ReviewView, { props: { payload: payloadWithActualResearchReview } });
    const panel = within(container as HTMLElement).getByTestId("daily-research-review-panel");

    expect(within(panel).getByTestId("daily-research-review-focus").textContent).toContain("risk_alerts");
    expect(within(panel).getByTestId("daily-research-market-breadth").textContent).toContain("deep_up_5_incl");
    expect(within(panel).getByTestId("daily-research-market-breadth").textContent).toContain("requests");
    expect(within(panel).getByTestId("daily-research-feedback-matrix").textContent).toContain("反馈 35");
    expect(within(panel).getByTestId("daily-research-feedback-matrix").textContent).toContain("板位");
    expect(within(panel).getByTestId("daily-research-theme-event-tree").textContent).toContain("题材-10");
    expect(within(panel).getByTestId("daily-research-theme-event-tree").textContent).toContain("成员 10");
    expect(within(panel).getByTestId("daily-research-theme-event-tree").textContent).toContain("broken_times");
    expect(within(panel).getByTestId("daily-research-theme-event-tree").textContent).toContain("事件 19 条");
    expect(within(panel).getByTestId("daily-research-event-categories").textContent).toContain("亏损事件 · 11 条");
    expect(within(panel).getByTestId("daily-research-event-categories").textContent).toContain("赚钱事件 · 5 条");
    expect(within(panel).getByTestId("daily-research-event-categories").textContent).toContain("反复开板事件 · 3 条");
    expect(within(panel).getByText("查看复盘重点完整 JSON")).toBeTruthy();
  });
});


describe("manual exact-date research generation", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals() });

  it("posts only the selected date, blocks repeated clicks and refreshes original GET", async () => {
    let release!: (value: unknown) => void;
    const pending = new Promise(resolve => { release = resolve; });
    const request = vi.fn().mockImplementationOnce(() => pending).mockResolvedValueOnce({
      ok: true, json: async () => ({ ...payload, research_review: { ...actualShapeResearchReview,
        trade_date: payload.trade_date, target_date: "2026-07-30" } }),
    });
    vi.stubGlobal("fetch", request);
    render(ReviewView, { props: { payload } });
    const button = screen.getByRole("button", { name: "生成所选日期复盘" });
    await fireEvent.click(button);
    await fireEvent.click(button);
    expect(request).toHaveBeenCalledTimes(1);
    expect(request.mock.calls[0][0]).toBe("/api/v3/review/generate");
    expect(JSON.parse(request.mock.calls[0][1].body)).toEqual({ date: "20260730" });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    release({ ok: true, json: async () => ({ status: "READY_FOR_REVIEW", trade_date: "20260730" }) });
    await waitFor(() => expect(request).toHaveBeenCalledTimes(2));
    expect(request.mock.calls[1][0]).toBe("/api/v3/review?date=20260730");
    await waitFor(() => expect(screen.getByText("所选日期复盘已刷新。" )).toBeTruthy());
  });

  it("shows a bounded failure and never echoes arbitrary response detail", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false,
      json: async () => ({ detail: { code: "GENERATION_FAILED", message: "secret /private/key" } }),
    }));
    render(ReviewView, { props: { payload } });
    await fireEvent.click(screen.getByRole("button", { name: "生成所选日期复盘" }));
    await waitFor(() => expect(screen.getByText("生成未完成，请核对本地记录；未自动重试。" )).toBeTruthy());
    expect(screen.queryByText(/secret \/private/)).toBeNull();
  });

  it("does not replace a newly selected date with a late generation response", async () => {
    let release!: (value: unknown) => void;
    vi.stubGlobal("fetch", vi.fn().mockImplementationOnce(() => new Promise(resolve => { release = resolve; }))
      .mockResolvedValueOnce({ok:true,json:async()=>payload}));
    const view = render(ReviewView, {props:{payload}});
    await fireEvent.click(screen.getByRole("button", {name:"生成所选日期复盘"}));
    await view.rerender({payload:{...payload,trade_date:"20260731"}});
    release({ok:true,json:async()=>({status:"READY_FOR_REVIEW",trade_date:"20260730"})});
    await waitFor(() => expect((screen.getByRole("button", {name:"生成所选日期复盘"}) as HTMLButtonElement).disabled).toBe(false));
    expect(screen.queryByText("所选日期复盘已刷新。" )).toBeNull();
  });
});


describe("intraday snapshots in the same research workbench", () => {
  afterEach(cleanup);
  it("preserves missing slots, coverage and objective details without issuing GET-time fetches", () => {
    const request = vi.fn(); vi.stubGlobal("fetch", request);
    const intraday = { date: "2026-07-30", status: "READY", missing_slots: ["09:35", "10:00", "11:30", "14:00", "15:00"],
      cannot_confirm: ["QUOTE_COVERAGE_PARTIAL:09:25"], evidence: [{ verification_scope: "LOCAL_BYTES_RELATIONS_AND_QUOTE_DATES_NOT_VENDOR_TRUTH" }],
      auction: { available: true, verification_early: [{ metric: "money_effect_median", early_value: 2 }] },
      slots: [{ slot: "09:25", sample: 3, expected_sample: 4, coverage_rate: .75, avg: 1, median: 2,
        up_rate: 2/3, deep_loss_5: 1, captured_at: "2026-07-30 09:25:30 CST", drift_minutes: 0,
        live: { highest_board: 6 }, by_tier: { "2板": { median: 2 } },
        top_boards: [{ name: "合成客观样本", pct: 2 }], top_board_level: 6 }] };
    render(ReviewView, { props: { payload: { ...payload, intraday_research: intraday } as any } });
    const panel = screen.getByTestId("intraday-research");
    expect(panel.textContent).toContain("75.0%");
    expect(panel.textContent).toContain("高开率");
    expect(panel.textContent).toContain("合成客观样本");
    expect(panel.textContent).toContain("QUOTE_COVERAGE_PARTIAL:09:25");
    expect(panel.textContent).toContain("缺失：09:35、10:00、11:30、14:00、15:00");
    expect(request).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});

describe("0915 separate focus with complete preserved review", () => {
  afterEach(cleanup);
  it("puts A first without dropping HK/research sections", () => {
    const {container} = render(ReviewView, {props:{payload, focus:"A"}});
    expect(container.querySelector("[data-review-section]")?.getAttribute("data-review-section")).toBe("A");
    expect(container.querySelectorAll("[data-review-section]")).toHaveLength(3);
    expect(screen.getByText("HK 收盘复盘")).toBeTruthy();
  });
  it("puts research first and keeps all other review content", () => {
    const {container} = render(ReviewView, {props:{payload, focus:"research"}});
    expect(container.querySelector("[data-review-section]")?.getAttribute("data-review-section")).toBe("research");
    expect(container.querySelectorAll("[data-review-section]")).toHaveLength(3);
    expect(screen.getByText("HK 收盘复盘")).toBeTruthy();
  });
});
