import { cleanup, render, screen } from "@testing-library/vue";
import { afterEach, describe, expect, it } from "vitest";

import HkCloseReviewPanel from "./HkCloseReviewPanel.vue";

const review = { model_selection_review: { status: "CANNOT_CONFIRM", cannot_confirm: [] } };

const historical = {
  schema_version: "v4.hk_prefix_research.panel_projection.v1",
  status: "READY",
  requested_date: "20260911",
  asset_id: "ZGE_HISTORY_V4_20260914",
  run_id: "run-fixed",
  scope: { event_date_range: ["2018-05-17", "2025-10-22"], max_event_year: 2025, consumed_2026: false },
  source: { rows: 1014835, symbols: 691, date_range: ["2018-01-02", "2026-09-11"], volume_source_column: "trade", volume_unit: "lots", price_basis_status: "RAW_UNADJUSTED_ACTION_NOT_AUTHENTICATED" },
  calendar: { market_day_count: 2139, certification: "CANNOT_CONFIRM_OFFICIAL_MARKET_CALENDAR" },
  binding: { groups: 24, controls: 72, series_count: 96, rows_per_series: 60 },
  export: {
    series_count: 96,
    rows_per_series: 60,
    total_rows: 5760,
    unknown_series_count: 18,
    unknown_row_count: 130,
    indeterminate_series_count: 96,
    indeterminate_row_count: 246,
    terminal_indeterminate_series_count: 12,
    complete_terminal_pairs: 16,
    required_complete_pairs: 18,
    coverage_status: "NOT_SUPPORTED",
    coverage_fraction: "16/24",
    state_distribution: { NO_ACTIVE_SETUP: 71, WARMUP: 11, BROKEN_PENDING: 6, RECLAIMED: 4, REPAIR_FAILED_TIMEOUT: 3, UNKNOWN: 1 },
    state_distribution_by_event_type: { new_event: { NO_ACTIVE_SETUP: 58, WARMUP: 9 }, continuation_event: { NO_ACTIVE_SETUP: 13, WARMUP: 2 } },
  },
  acceptance: { field_isolation: "PASS", future_isolation: "PASS", past_positive_control: "PASS", csv_replay: "PASS" },
  review: {
    manual_review_status: "NOT_REVIEWED",
    comparison_status: "NOT_SUPPORTED_TERMINAL_COVERAGE",
    conclusion: "冻结历史 prefix 研究的终态可判覆盖为16/24，低于18/24；比较状态为NOT_SUPPORTED。本批不形成 alpha 或交易结论。",
  },
  evidence: [{ label: "output receipt", ref: "receipt.json", sha256: "a".repeat(64) }],
  cannot_confirm: ["Historical source publication/revision/vintage is unknown."],
  research_only: true,
  production_allowed: false,
  buy_gate_updated: false,
  orders_sent: false,
} as const;

describe("HkCloseReviewPanel historical prefix surface", () => {
  afterEach(cleanup);

  it("distinguishes an HK securities calendar skip from missing close evidence", () => {
    render(HkCloseReviewPanel, {
      props: {
        review: { model_selection_review: { status: "NON_TRADING_DAY", close_top20: [], row_counts: {} } },
      },
    });

    expect(screen.getByTestId("hk-close-calendar-skip").textContent).toContain("没有正式收盘 Top20");
    expect(screen.queryByText("HK 收盘证据未物化；不把缺失显示为 0 命中。")).toBeNull();
    expect(screen.queryByText("该交易日没有可展示的收盘 Top20 归因，不把缺失解释为 0 命中。")).toBeNull();
  });

  it("renders coverage, terminal state distribution, evidence and review boundary", () => {
    render(HkCloseReviewPanel, { props: { review, historical } });

    const panel = screen.getByTestId("hk-prefix-research");
    expect(panel.textContent).toContain("96 × 60");
    expect(panel.textContent).toContain("24 组 / 72 对照");
    expect(panel.textContent).toContain("16/24");
    expect(panel.textContent).toContain("NOT_SUPPORTED");
    expect(panel.textContent).toContain("WARMUP");
    expect(panel.textContent).toContain("预热期");
    expect(panel.textContent).toContain("WARMUP 与 UNKNOWN 均不当作已知无活动形态");
    expect(panel.textContent).toContain("NOT_REVIEWED");
    expect(panel.textContent).toContain("不形成 alpha 或交易结论");
    expect(panel.textContent).toContain("receipt.json");
    expect(panel.textContent).not.toContain("positive_lower_rate");
  });

  it("keeps an absent API field as CANNOT_CONFIRM", () => {
    render(HkCloseReviewPanel, { props: { review } });

    const panel = screen.getByTestId("hk-prefix-research");
    expect(panel.textContent).toContain("CANNOT_CONFIRM");
    expect(panel.textContent).toContain("HK_PREFIX_RESEARCH_NOT_IN_RESPONSE");
    expect(panel.textContent).not.toContain("96 × 60");
  });

  it("shows existing formal 0.2 candidates and partial stage counts without inventing research or PIT status", () => {
    const review = {
      market: "HK",
      model_selection_review: {
        status: "MODEL_REVIEW_PARTIAL_STAGE_EVIDENCE",
        models: {
          "0.2_prob_active": {
            evidence_status: "READY",
            selected_count: 100,
            hit_count: 8,
          },
        },
        stage_union: {
          evidence_status: "MISSING",
          selected_count: null,
          hit_count: null,
        },
        observed_stage_union: {
          evidence_status: "PARTIAL_RESEARCH_ONLY",
          selected_codes: Array.from({ length: 24 }, (_, index) => `HK.${String(index + 1).padStart(5, "0")}`),
          selected_count: 24,
          hit_codes: ["HK.00001", "HK.00002", "HK.00003", "HK.00004", "HK.00005", "HK.00006"],
          hit_count: 6,
        },
        row_counts: { close_top20: 20, stage_rows: 50 },
        missing_stages: ["STAGE_1300_1315", "STAGE_1445_1500"],
      },
    } as const;

    render(HkCloseReviewPanel, { props: { review } });

    const model = screen.getByTestId("hk-formal-model-fallback");
    expect(model.textContent).toContain("8/20");
    expect(model.textContent).toContain("正式候选 100 行");
    expect(model.textContent).toContain("研究观察字段 CANNOT_CONFIRM");
    expect(model.textContent).toContain("PIT未验证");
    expect(model.textContent).toContain("NO_BUY");

    const union = screen.getByTestId("hk-observed-stage-union");
    expect(union.textContent).toContain("6/20");
    expect(union.textContent).toContain("50 行 / 24 个去重代码");
    expect(union.textContent).toContain("阶段覆盖元数据缺证");
    expect(screen.getByTestId("hk-observed-stage-boundary").textContent).toContain("不升格为正式七阶段并集");
  });

  it("does not show zero candidates when both the formal and research 0.2 metrics are unavailable", () => {
    render(HkCloseReviewPanel, {
      props: {
        review: {
          model_selection_review: {
            status: "CANNOT_CONFIRM",
            models: {
              "0.2_prob_active": { evidence_status: "CANNOT_CONFIRM", selected_count: null, hit_count: null },
            },
            row_counts: { close_top20: 20 },
          },
        },
      },
    });

    expect(screen.getByTestId("hk-observed-model-unavailable").textContent).toContain("不可用");
    expect(screen.queryByText("0/20")).toBeNull();
  });
});
