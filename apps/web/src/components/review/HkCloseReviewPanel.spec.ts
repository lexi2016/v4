import { cleanup, render, screen } from "@testing-library/vue";
import { afterEach, describe, expect, it } from "vitest";

import HkCloseReviewPanel from "./HkCloseReviewPanel.vue";

afterEach(cleanup);

describe("HK close partial observation", () => {
  it("distinguishes an HK Connect calendar skip from missing close evidence", () => {
    render(HkCloseReviewPanel, {
      props: {
        review: { model_selection_review: { status: "NON_TRADING_DAY", close_top20: [], row_counts: {} } },
      },
    });

    expect(screen.getByTestId("hk-close-calendar-skip").textContent).toContain("没有正式收盘 Top20");
    expect(screen.queryByText("HK 收盘证据未物化；不把缺失显示为 0 命中。")).toBeNull();
  });

  it("shows existing partial evidence and tri-state Top20 observations separately from the formal union", () => {
    const review = {
      market: "HK",
      model_selection_review: {
        trade_date: "20260923",
        status: "MODEL_REVIEW_PARTIAL_STAGE_EVIDENCE",
        stage_union: {
          evidence_status: "CANNOT_CONFIRM",
          selected_count: null,
          hit_count: null,
        },
        observed_stage_union: {
          evidence_status: "PARTIAL_RESEARCH_ONLY",
          selected_codes: [
            "HK.00001", "HK.00002", "HK.00003", "HK.00005", "HK.00006", "HK.00007",
            "HK.00008", "HK.00009", "HK.00010", "HK.00011", "HK.00012", "HK.00013",
            "HK.00014", "HK.00015", "HK.00016", "HK.00017", "HK.00018", "HK.00019",
            "HK.00020", "HK.00021", "HK.00022", "HK.00023", "HK.00024", "HK.00025",
          ],
          selected_count: 24,
          hit_codes: ["HK.00001", "HK.00002", "HK.00003", "HK.00005", "HK.00006", "HK.00007"],
          hit_count: 6,
        },
        row_counts: { stage_rows: 70 },
        close_top20: [
          { rank: 1, code: "HK.00001", name: "观察到", stage_union_hit: false },
          { rank: 2, code: "HK.00004", name: "部分行未见" },
        ],
        top20_attribution: [],
        missing_stages: ["STAGE_0930_0935"],
        cannot_confirm: ["HK_STAGE_CUTOFF_UNSAFE"],
      },
    } as const;

    const { container } = render(HkCloseReviewPanel, { props: { review } });

    expect(screen.getByText("部分观察并集（不完整）")).toBeTruthy();
    expect(screen.getByText("6/20")).toBeTruthy();
    expect(screen.getByText(/70 条同日观察行/)).toBeTruthy();
    expect(screen.getByText(/24 个去重代码/)).toBeTruthy();
    expect(screen.getByText(/正式七阶段并集仍为缺证/)).toBeTruthy();
    expect(screen.getByText("已在部分行中观察到")).toBeTruthy();
    expect(screen.getByText("未在现有部分行中观察到")).toBeTruthy();
    expect(container.querySelector('[data-state="OBSERVED_PRESENT"]')).toBeTruthy();
    expect(container.querySelector('[data-state="NOT_OBSERVED_IN_PARTIAL_ROWS"]')).toBeTruthy();
    expect(container.querySelector("tbody tr")?.children[5]?.textContent).toBe("缺证");
    expect(screen.getByText("HK_STAGE_CUTOFF_UNSAFE")).toBeTruthy();
  });

  it("keeps Top20 observation at CANNOT_CONFIRM when the partial source is absent", () => {
    const review = {
      market: "HK",
      model_selection_review: {
        trade_date: "20260923",
        status: "MODEL_REVIEW_PARTIAL_STAGE_EVIDENCE",
        stage_union: { evidence_status: "CANNOT_CONFIRM", selected_count: null, hit_count: null },
        row_counts: { stage_rows: 70 },
        close_top20: [{ rank: 1, code: "HK.00001", name: "不可确认" }],
      },
    } as const;

    const { container } = render(HkCloseReviewPanel, { props: { review } });

    expect(screen.getByText("不能确认")).toBeTruthy();
    expect(container.querySelector('[data-state="CANNOT_CONFIRM"]')).toBeTruthy();
  });
});
