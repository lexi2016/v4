import { cleanup, render, screen } from "@testing-library/vue";
import { afterEach, describe, expect, it } from "vitest";

import DailyResearchReviewPanel from "./DailyResearchReviewPanel.vue";

const review = {
  schema_version: "daily_research_review.v1",
  status: "READY",
  trade_date: "20260911",
  target_date: "2026-09-11",
  source_role: "VIBE_DUANXIAN_DAILY_REVIEW",
  source_artifact_sha256: "a".repeat(64),
  data_as_of: "2026-09-11 17:25 CST",
  generation_status: "EXTERNAL_SOURCE_READ_ONLY",
  generation: { status: "EXTERNAL_SOURCE_READ_ONLY", owner: "CANNOT_CONFIRM" },
  cannot_confirm: ["V4_DAILY_RESEARCH_REVIEW_GENERATOR_NOT_CONNECTED"],
  research_only: true,
  production_allowed: false,
  buy_gate_updated: false,
  orders_sent: false,
  market_breadth: { date: "2026-09-11", up: 619, down: 4619, flat: 46, amount_yi: 19719 },
  feedback_matrix: {
    prev_date: "2026-09-10",
    coverage: 35,
    order: ["晋级涨停", "收红", "跌超5%"],
    matrix: { "首板": { "晋级涨停": 4, "收红": 7, "跌超5%": 3 } },
    details: [{ code: "600318", name: "新力金融", prev_tier: "首板", result: "跌停", ret: -10.01, sector: "多元金融" }],
  },
  money_effect: { avg: 0.57, median: -1.9, positive_rate: 0.457, sample: 35 },
  loss_effect: { deep_loss_5_count: 8, deep_loss_5_rate: 0.229, deep_loss_7_count: 6, limit_down_count: 3, worst: -10.01 },
  promotion: { limit_up_count: 40, overall: { base: 35, promoted: 7, rate: 0.2 }, tiers: { "1进2": { base: 26, promoted: 4, rate: 0.154 } } },
  ladder_gap: { highest: 4, continuous: true, gaps: [] },
  theme_tree: { coverage_rate: 1, themes: [{ tag: "光伏玻璃", limit_up: 3, highest: 2, state: "延续", members: [{ code: "600876" }] }] },
  event_ledger: { count: 1, events: [{ code: "600876", name: "凯盛新能", tag: "光伏玻璃", board: 2, ret: 9.99, note: "fixture" }] },
} as const;

describe("DailyResearchReviewPanel", () => {
  afterEach(cleanup);

  it("renders exact-date fact sections and retains the generation gap", () => {
    render(DailyResearchReviewPanel, { props: { review } });

    expect(screen.getByTestId("daily-research-review-panel")).toBeTruthy();
    expect(screen.getByText("2026-09-11 · READY · 只读")).toBeTruthy();
    expect(screen.getByTestId("daily-research-review-generation-gap")).toBeTruthy();
    expect(screen.getByText("V4_DAILY_RESEARCH_REVIEW_GENERATOR_NOT_CONNECTED")).toBeTruthy();
    expect(screen.getByTestId("daily-research-market-breadth").textContent).toContain("619");
    expect(screen.getByTestId("daily-research-feedback-matrix").textContent).toContain("晋级涨停");
    expect(screen.getByTestId("daily-research-feedback-matrix").textContent).toContain("新力金融");
    expect(screen.getByTestId("daily-research-money-loss-effect").textContent).toContain("-10.01");
    expect(screen.getByTestId("daily-research-promotion-ladder").textContent).toContain("1进2");
    expect(screen.getByTestId("daily-research-theme-event-tree").textContent).toContain("光伏玻璃");
    expect(screen.getByTestId("daily-research-theme-event-tree").textContent).toContain("凯盛新能");
  });

  it("shows CANNOT_CONFIRM when the exact-date artifact is absent", () => {
    render(DailyResearchReviewPanel, { props: { review: { status: "CANNOT_CONFIRM", cannot_confirm: ["DAILY_RESEARCH_REVIEW_DATE_FILE_MISSING"] } } });

    expect(screen.getByTestId("daily-research-review-panel").textContent).toContain("CANNOT_CONFIRM");
    expect(screen.getByTestId("daily-research-review-missing").textContent).toContain("DAILY_RESEARCH_REVIEW_DATE_FILE_MISSING");
    expect(screen.queryByTestId("daily-research-market-breadth")).toBeNull();
  });
});
