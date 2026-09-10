import { cleanup, render, screen, within } from "@testing-library/vue";
import { afterEach, describe, expect, it } from "vitest";

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
});
