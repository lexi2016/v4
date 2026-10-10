import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cleanup, render, screen } from "@testing-library/vue";
import { afterEach, describe, expect, it } from "vitest";

import HkCloseReviewPanel from "../apps/web/src/components/review/HkCloseReviewPanel.vue";

const e5Root = resolve(__dirname, "../..");
const closeBaseline = JSON.parse(readFileSync(resolve(e5Root, "integration/CLOSE_BEFORE.json"), "utf8"));

afterEach(cleanup);

describe("20261009 HK historical research review", () => {
  it("shows recalculated model and complete seven-stage research coverage while leaving formal metrics unverified", () => {
    const review = closeBaseline.market_reviews.HK;
    render(HkCloseReviewPanel, { props: { review } });

    expect(screen.getByTestId("hk-research-review-status").textContent).toContain("研究回补可用");
    expect(screen.getByText("研究选股 0.2（非正式）")).toBeTruthy();
    expect(screen.getByText("10/20")).toBeTruthy();
    expect(screen.getByText(/100\/100.*50%/)).toBeTruthy();
    expect(screen.getByText("研究回补七阶段并集（非正式）")).toBeTruthy();
    expect(screen.getByText("6/20")).toBeTruthy();
    expect(screen.getByText(/7\/7.*70.*32.*30%/)).toBeTruthy();
    expect(screen.getByText("研究七阶段并集")).toBeTruthy();
    expect(screen.getAllByText("研究模型与阶段均命中").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/09:20阶段（09:30–09:35替代）/).length).toBeGreaterThan(0);
    expect(screen.getByTestId("hk-0925-substitute-note").textContent).toContain("实际数据截止09:35");
    expect(screen.getByText("正式指标、PIT与来源限制（未验证）")).toBeTruthy();
    const formalDetails = screen.getByTestId("hk-formal-review-details").textContent;
    expect(formalDetails).toContain("正式 0.2：MISSING");
    expect(formalDetails).toContain("OBSERVED_0_2_CANDIDATE_IS_NOT_FORMAL_OR_PIT_VERIFIED");
  });

  it("keeps the original 0925 label when no replacement marker is present", () => {
    const review = JSON.parse(JSON.stringify(closeBaseline.market_reviews.HK));
    const marker = "HK_0925_REPLACED_BY_0930_0935_RESEARCH_ONLY";
    review.model_selection_review.cannot_confirm = review.model_selection_review.cannot_confirm
      .filter((item: string) => item !== marker);
    review.model_selection_review.observed_stage_union.cannot_confirm = review.model_selection_review.observed_stage_union.cannot_confirm
      .filter((item: string) => item !== marker);
    render(HkCloseReviewPanel, { props: { review } });

    expect(screen.getAllByText(/港股通09:20 \/ A股09:25竞价选股/).length).toBeGreaterThan(0);
    expect(screen.queryByTestId("hk-0925-substitute-note")).toBeNull();
  });
});
