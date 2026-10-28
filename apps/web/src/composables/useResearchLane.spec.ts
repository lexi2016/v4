import { computed, ref } from "vue";
import { describe, expect, it } from "vitest";

import type { ResearchLane } from "../api/research_lane";
import { researchStatusPresentation } from "./useResearchLane";

const counts = {
  wechatArticleCount: 3,
  stockMainlineLength: 2,
  stockTimelineLength: 4,
};

const lane = (overrides: Record<string, unknown> = {}) => ({
  research_date: "20260804",
  endpoint_mode: "EXACT",
  schema_version: "v3_5.research_lane.v1",
  research_quality_summary: {},
  zsxq_hourly: {},
  external_finance: {},
  ai_news: {},
  key_investment_messages: [],
  hourly_research: {},
  ...overrides,
}) as ResearchLane;

describe("research status presentation", () => {
  it.each([
    ["missing", undefined],
    ["null", null],
    ["string", "2"],
    ["negative", -1],
    ["fractional", 1.5],
    ["NaN", Number.NaN],
    ["infinite", Number.POSITIVE_INFINITY],
  ])("keeps %s new-item count unassessed and does not use legacy totals", (_name, newItemCount) => {
    const payload = lane({
      research_quality_summary: {
        ...(newItemCount === undefined ? {} : { new_item_count: newItemCount }),
        raw_item_count: 80,
        research_item_count: 70,
      },
    });

    expect(researchStatusPresentation(payload, counts).newItemCount).toBe("未评估");
  });

  it("distinguishes valid zero from missing finance and AI counts without substitute fields", () => {
    const missing = researchStatusPresentation(lane({
      external_finance: { item_count: 6, overview: [{ title: "finance" }] },
      ai_news: { raw_item_count: 7, items: [{ title: "AI" }] },
    }), counts);
    expect(missing.externalFinanceCount).toBe("未评估");
    expect(missing.aiNewsCount).toBe("未评估");

    const zero = researchStatusPresentation(lane({
      research_quality_summary: { new_item_count: 0 },
      external_finance: { raw_item_count: 0 },
      ai_news: { item_count: 0 },
    }), counts);
    expect(zero.newItemCount).toBe(0);
    expect(zero.externalFinanceCount).toBe(0);
    expect(zero.aiNewsCount).toBe(0);
  });

  it("preserves the existing explicit ZSXQ alias and OCR status labels", () => {
    const payload = lane({
      zsxq_hourly: { zsxq_topic_count_0800_0900: 5 },
      ocr_ingestion: { status: "PARTIAL", done_count: 2, failed_count: 1 },
    });
    const display = researchStatusPresentation(payload, counts);
    expect(display.zsxqTopicCount).toBe(5);
    expect(display.ocr).toBe("部分完成 · 2/1");

    payload.zsxq_hourly = { topic_count: 0, zsxq_topic_count_0800_0900: 9 };
    expect(researchStatusPresentation(payload, counts).zsxqTopicCount).toBe(0);
  });

  it("recomputes the typed presentation when the reactive lane payload changes", () => {
    const payload = ref(lane({
      research_quality_summary: { new_item_count: 1 },
      external_finance: { raw_item_count: 1 },
      ai_news: { item_count: 1 },
    }));
    const presentation = computed(() => researchStatusPresentation(payload.value, counts));
    expect(presentation.value.newItemCount).toBe(1);
    expect(presentation.value.externalFinanceCount).toBe(1);
    expect(presentation.value.aiNewsCount).toBe(1);

    payload.value = lane({
      research_quality_summary: { new_item_count: 0 },
      external_finance: { raw_item_count: 0 },
      ai_news: { item_count: 0 },
    });
    expect(presentation.value.newItemCount).toBe(0);
    expect(presentation.value.externalFinanceCount).toBe(0);
    expect(presentation.value.aiNewsCount).toBe(0);
  });
});
