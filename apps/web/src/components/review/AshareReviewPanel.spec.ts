import { cleanup, render, screen } from "@testing-library/vue";
import { afterEach, describe, expect, it } from "vitest";

import AshareReviewPanel from "./AshareReviewPanel.vue";

const row = (id: string, extra: Record<string, unknown> = {}) => ({ trade_date: "20260821", id, ...extra });

const richReview = {
  trade_date: "20260821",
  headline: "市场分歧，主线需要前排承接",
  market_regime: "分歧或弱广度",
  risk_tone: "保持观察",
  big_picture: [row("summary")],
  mainlines: [row("mainline")],
  core_stocks: [row("core", { name: "正式核心票" })],
  observation_pool: [],
  next_day_trigger_tree: [row("trigger")],
  quality_gate: [],
  cannot_confirm: ["DAILY_VIDEO_NOT_LOCKED"],
  source_role: "REVIEW_CORE_BUNDLE_V1",
  source_sha256: "a".repeat(64),
  production_allowed: false,
  buy_gate_updated: false,
  orders_sent: false,
  summary_cards: [row("card", { title: "市场阶段", value: "分歧或弱广度" })],
  market_rows: [row("market-1"), row("market-2")],
  prior_plan_rows: [row("plan-1", { mapped_theme: "医药", close_result: "部分兑现" }), row("plan-2")],
  board_rows: [row("board-1", { section: "医药", today_role: "strong_branch", local_evidence: "前排承接" }), row("board-2", { section: "消费电子", today_role: "rotation" })],
  anchor_rows: [row("anchor-1", { theme: "医药", stocks: ["汉森制药"] })],
  anchor_role_v3_rows: [
    row("anchor-role-1", { stock: "汉森制药", theme: "医药", role_type: "leader", why_this_role: "前排证据" }),
    row("anchor-role-2", { stock: "北陆药业", theme: "医药", role_type: "capacity_anchor", why_this_role: "容量证据" }),
  ],
  intraday_handoff_rows: [row("handoff-1", { theme: "医药", morning_status: "承接", afternoon_handoff: "待验证" })],
  catalyst_rows: [row("catalyst-1", { direction: "医药", catalyst: "研报命中" })],
  trigger_rows: [row("trigger-rich-1", { direction: "医药", upgrade: "前排继续承接", invalidation: "容量锚负反馈" })],
  scenario_tree_rows: [row("scenario-1", { scenario: "符合预期" })],
  video: { status: "DAILY_VIDEO_NOT_LOCKED", target_trade_date: "20260821" },
  video_gap_rows: [],
  source_status_rows: [row("source-1", { source: "TDX", status: "READY" })],
  formal_pool_validation: { status: "FORMAL_POOL_WEAK_REALIZATION" },
  rule_adoption_rows: [],
  video_learning_rows: [],
  review_surface: { tier: "V3_RICH_READY", status: "READY", trade_date: "20260821" },
} as const;

describe("AshareReviewPanel rich V3 product contract", () => {
  afterEach(cleanup);

  it("puts the product layer before the close chain and keeps rich row counts", () => {
    const { container } = render(AshareReviewPanel, { props: { review: richReview } });
    const product = screen.getByTestId("a-product-first");
    const chain = screen.getByTestId("a-audit-appendix");
    expect(product).toBeTruthy();
    expect(product.compareDocumentPosition(chain) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getAllByTestId("rich-board-row")).toHaveLength(2);
    expect(screen.getAllByTestId("rich-anchor-row")).toHaveLength(2);
    expect(screen.getAllByTestId("rich-plan-row")).toHaveLength(2);
    expect(screen.getAllByTestId("rich-trigger-row")).toHaveLength(1);
    expect(screen.getAllByText("强分支").length).toBeGreaterThan(0);
    expect(screen.getAllByText("轮动支线").length).toBeGreaterThan(0);
    expect(screen.getByText("龙头候选")).toBeTruthy();
    expect(screen.getByText("容量锚")).toBeTruthy();
    expect(screen.queryByText("strong_branch")).toBeNull();
  });

  it("shows exact-date video empty state and proxy boundary in the product", () => {
    render(AshareReviewPanel, { props: { review: richReview } });
    expect(screen.getByText("当天视频未锁定")).toBeTruthy();
    expect(screen.getByText(/日线\/分钟\/开盘代理，未验证盘口队列与封单稳定性/)).toBeTruthy();
  });

  it("keeps the six red frames when only exact-date stage evidence exists", () => {
    const partial = {
      ...richReview,
      trade_date: "20260824",
      headline: "阶段候选仅作 WATCH_ONLY 验证锚",
      mainlines: [],
      core_stocks: [],
      prior_plan_rows: [],
      board_rows: [],
      anchor_role_v3_rows: [],
      intraday_handoff_rows: [],
      catalyst_rows: [],
      trigger_rows: [],
      next_day_trigger_tree: [],
      stage_validation_rows: [
        row("stage-1", {
          trade_date: "20260824",
          name: "阶段观察",
          symbol: "A.600001",
          role_type: "stage_validation_anchor",
          recommendation_status: "WATCH_ONLY",
        }),
      ],
      review_surface: {
        tier: "V3_RICH_PARTIAL",
        status: "PARTIAL_STAGE_EVIDENCE",
        source_refs: [{ trade_date: "20260824", stage_id: "STAGE_0925" }],
      },
      review_core_bundle: { status: "NOT_MATERIALIZED" },
    } as any;

    render(AshareReviewPanel, { props: { review: partial } });
    const surface = screen.getByTestId("a-review-rich-surface");
    expect(surface.getAttribute("data-surface-tier")).toBe("V3_RICH_PARTIAL");
    expect(surface.getAttribute("data-surface-status")).toBe("PARTIAL_STAGE_EVIDENCE");
    expect(surface.getAttribute("data-surface-trade-date")).toBe("20260824");
    expect(screen.getByTestId("a-product-first")).toBeTruthy();
    expect(screen.getByTestId("a-rich-section-prior-plan")).toBeTruthy();
    expect(screen.getByTestId("a-rich-section-board-coverage")).toBeTruthy();
    expect(screen.getByTestId("a-rich-section-mainlines")).toBeTruthy();
    expect(screen.getByTestId("a-rich-section-anchors")).toBeTruthy();
    expect(screen.getByTestId("a-rich-section-handoff")).toBeTruthy();
    expect(screen.getByTestId("a-rich-section-triggers")).toBeTruthy();
    expect(screen.getByText(/阶段验证锚（WATCH_ONLY）/)).toBeTruthy();
    expect(screen.getAllByText("阶段观察 A.600001").length).toBeGreaterThan(0);
    expect(screen.getByText(/CANNOT_CONFIRM · 昨日正式预案未物化/)).toBeTruthy();
    expect(screen.getByText(/CANNOT_CONFIRM · 全板块正式覆盖表未物化/)).toBeTruthy();
    expect(screen.getByText(/CANNOT_CONFIRM · 正式主线\/支线\/失败方向尚未物化/)).toBeTruthy();
    expect(screen.getByText(/阶段候选只用于 WATCH_ONLY 验证锚/)).toBeTruthy();
    expect(screen.getByTestId("a-rich-section-handoff").textContent).toContain("CANNOT_CONFIRM");
    expect(screen.getByTestId("a-rich-section-triggers").textContent).toContain("CANNOT_CONFIRM");
  });

  it.each([
    ["missing tier", undefined],
    ["compact tier", { tier: "COMPACT_NATIVE", status: "MODEL_REVIEW_READY" }],
    ["partial status without tier", { status: "PARTIAL_STAGE_EVIDENCE" }],
  ])("fails closed for rich rows with %s", (_label, surface) => {
    const review = {
      ...richReview,
      review_surface: surface,
      review_core_bundle: { run_id: "bundle-run-without-rich-tier" },
    } as any;

    render(AshareReviewPanel, { props: { review } });

    expect(screen.queryByTestId("a-product-first")).toBeNull();
    expect(screen.queryByTestId("a-rich-section-board-coverage")).toBeNull();
  });

  it("keeps compact-model fallback available for older payloads", () => {
    const compact = {
      ...richReview,
      board_rows: [], anchor_role_v3_rows: [], prior_plan_rows: [],
      review_surface: { tier: "COMPACT_NATIVE", status: "MODEL_REVIEW_READY", trade_date: "20260821" },
      model_review: { status: "INDEPENDENT_CLOSE_REVIEW_READY", market_summary: {}, board_rows: [], anchor_role_rows: [] },
    } as any;
    render(AshareReviewPanel, { props: { review: compact } });
    expect(screen.getByText("本地复盘引擎 · 板块判断")).toBeTruthy();
    expect(screen.queryByTestId("a-product-first")).toBeNull();
  });

  it("uses canonical mainlines for the layered product and localizes composite roles", () => {
    const review = {
      ...richReview,
      mainlines: [
        row("main", { section: "主线候选方向", today_role: "MAINLINE" }),
        row("rotation", { section: "轮动方向", today_role: "ROTATION_BRANCH" }),
        row("strong", { section: "强分支方向", today_role: "STRONG_BRANCH" }),
        row("watch", { section: "观察方向", today_role: "WATCH_ONLY" }),
      ],
      board_rows: [row("board-only", { section: "仅覆盖表方向", today_role: "MAINLINE" })],
      video: { status: "READY" },
      review_core_bundle: {
        bundle_sha256: "a".repeat(64),
        manifest_sha256: "b".repeat(64),
        receipt_sha256: "c".repeat(64),
      },
    } as const;
    render(AshareReviewPanel, { props: { review } });

    expect(screen.getAllByTestId("rich-mainline-row")).toHaveLength(4);
    expect(screen.getAllByText("主线候选").length).toBeGreaterThan(0);
    expect(screen.getAllByText("轮动分支").length).toBeGreaterThan(0);
    expect(screen.getAllByText("强分支").length).toBeGreaterThan(0);
    expect(screen.getAllByText("观察分支").length).toBeGreaterThan(0);
    expect(screen.queryByText("MAINLINE")).toBeNull();
    expect(screen.queryByText("ROTATION_BRANCH")).toBeNull();
    expect(screen.queryByText("WATCH_ONLY")).toBeNull();
    expect(screen.getByText("当天视频未锁定")).toBeTruthy();
    expect(screen.getByText(/manifest SHA/)).toBeTruthy();
    expect(screen.getByText(/receipt SHA/)).toBeTruthy();
  });

  it("localizes audit source and catalyst statuses", () => {
    const review = {
      ...richReview,
      source_status_rows: [row("source-status", { source: "DXX", status: "success" })],
      catalyst_rows: [
        row("public-catalyst", { direction: "医药", quality: "PUBLIC_DXX_CATALYST" }),
        row("metadata-catalyst", { direction: "韭研公社", quality: "METADATA_ONLY_NO_USABLE_ROWS" }),
      ],
    } as const;
    render(AshareReviewPanel, { props: { review } });
    const appendix = screen.getByTestId("a-audit-appendix");
    expect(appendix.textContent).toContain("成功");
    expect(appendix.textContent).toContain("公开催化线索");
    expect(appendix.textContent).toContain("仅元数据，无可用正文");
    expect(appendix.textContent).not.toContain("PUBLIC_DXX_CATALYST");
    expect(appendix.textContent).not.toContain("METADATA_ONLY_NO_USABLE_ROWS");
  });

  it("renders the exact first failure and downstream chain without promoting empty formal layers", () => {
    const review = {
      ...richReview,
      trade_date: "20260824",
      headline: "阶段候选仅作 WATCH_ONLY 验证锚",
      mainlines: [],
      board_rows: [],
      prior_plan_rows: [],
      anchor_role_v3_rows: [],
      intraday_handoff_rows: [],
      trigger_rows: [],
      stage_validation_rows: [row("stage-1", { symbol: "A.600001", recommendation_status: "WATCH_ONLY" })],
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
    } as any;

    render(AshareReviewPanel, { props: { review } });

    const failure = screen.getByTestId("a-first-failure");
    expect(failure.textContent).toContain("selector/PANEL");
    expect(failure.textContent).toContain("期望日期20260824");
    expect(failure.textContent).toContain("观测日期20260821");
    expect(failure.textContent).toContain("16:05 FAILED/CONTRACT");
    expect(failure.textContent).toContain("ReviewBundle未物化");
    expect(failure.textContent).toContain("review_bundle/20260824/receipt.json");
    expect(failure.textContent).toContain("review_bundle/20260824/current.json");
    expect(screen.getAllByTestId("review-failure-row")).toHaveLength(4);
    expect(screen.queryByTestId("rich-mainline-row")).toBeNull();
    expect(screen.queryByTestId("rich-board-row")).toBeNull();
  });
});
