import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "../apps/web/src/App.vue";

const jsonResponse = (payload: unknown) => ({ ok: true, json: async () => payload });
const emptyPool = { data_status: "DATA_BLOCKED_EMPTY", rows: [], blocking_reasons: ["fixture"] };
const researchStagePayload = (date: string, stageId: string) => {
  const rows = Array.from({ length: 10 }, (_, index) => ({
    market: "HK",
    code: `HK.${String(10000 + index).padStart(5, "0")}`,
    name: `历史研究候选${index + 1}`,
    rank: index + 1,
    score: 60 - index,
    stage_id: stageId,
    trade_date: date,
    source_mode: stageId === "STAGE_0925"
      ? "HK_CONNECT_0930_0935_SUBSTITUTE_STAGE_0925"
      : "HK_CONNECT_FOUR_LANE",
    formal_eligible: false,
  }));
  return {
    ok: true,
    trade_date: date,
    stage: { stage_id: stageId, status: "PARTIAL_WITH_ROWS", display_status: "历史研究回补" },
    markets: {
      HK: {
        status: "PARTIAL_WITH_ROWS",
        selection_status: "PARTIAL_WITH_ROWS",
        source_status: "PARTIAL_WITH_ROWS",
        selection_mode: "BACKFILL",
        display_mode: "OBSERVATION_UNVERIFIED",
        selected_rows: null,
        source_rows: 100,
        observation_count: 10,
        display_reasons: ["HK_D1_MEMBERSHIP_PIT_UNVERIFIED"],
        rows,
      },
    },
    unified_rows: rows,
    selected_a_rows: 0,
    selected_hk_rows: null,
    selected_total_rows: null,
    selection_mode: "SHARED_STAGE_CENTER_READ_ONLY",
    RESEARCH_ONLY: true,
    production_allowed: false,
    buy_gate_updated: false,
    orders_sent: false,
  };
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("historical HK research selections", () => {
  it("shows 0925 and 1545 BACKFILL rows without requiring formal/PIT status or a fixed date", async () => {
    for (const [date, stageId] of [
      ["20261009", "STAGE_0925"],
      ["20261008", "STAGE_0925"],
      ["20261009", "STAGE_1545_1555"],
      ["20261008", "STAGE_1545_1555"],
    ]) {
      window.history.replaceState({}, "", `/?date=${date}&stage=${stageId}`);
      const rows = Array.from({ length: 10 }, (_, index) => ({
        market: "HK",
        code: `HK.${String(10000 + index).padStart(5, "0")}`,
        name: `历史研究候选${index + 1}`,
        rank: index + 1,
        score: 60 - index,
        stage_id: stageId,
        source_mode: stageId === "STAGE_0925"
          ? "HK_CONNECT_0930_0935_SUBSTITUTE_STAGE_0925"
          : "HK_CONNECT_FOUR_LANE",
        formal_eligible: false,
      }));
      const payload = {
        ok: true,
        trade_date: date,
        stage: { stage_id: stageId, status: "PARTIAL_WITH_ROWS", display_status: "历史研究回补" },
        markets: {
          HK: {
            status: "PARTIAL_WITH_ROWS",
            selection_status: "PARTIAL_WITH_ROWS",
            source_status: "PARTIAL_WITH_ROWS",
            selection_mode: "BACKFILL",
            display_mode: "OBSERVATION_UNVERIFIED",
            selected_rows: null,
            source_rows: 100,
            observation_count: 10,
            display_reasons: ["HK_D1_MEMBERSHIP_PIT_UNVERIFIED"],
            rows,
          },
        },
        unified_rows: rows,
        selected_a_rows: 0,
        selected_hk_rows: null,
        selected_total_rows: null,
        selection_mode: "SHARED_STAGE_CENTER_READ_ONLY",
        RESEARCH_ONLY: true,
        production_allowed: false,
        buy_gate_updated: false,
        orders_sent: false,
      };
      vi.stubGlobal("fetch", vi.fn(async (url: string) => {
        if (url === "/api/v1/runs/date-list") {
          return jsonResponse({ default_date: date, stage_dates: [date], future_target_dates: [] });
        }
        if (url === "/api/v3/research/dates") return jsonResponse({ research_dates: [] });
        if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(payload);
        return jsonResponse({ ...emptyPool, trade_date: date });
      }));

      render(App);
      const hkRegion = await screen.findByRole("region", { name: "港股通研究回补选股" });
      await waitFor(() => expect(hkRegion.querySelectorAll(".candidate-card")).toHaveLength(10));
      expect(hkRegion.textContent).toContain("10 条研究回补选股 · 非正式");
      expect(hkRegion.textContent).toContain("研究候选 · 非正式");
      expect(hkRegion.textContent).toContain("正式执行、自然采集与 PIT 状态未验证");
      cleanup();
    }
  });

  it("keeps each stage's research result available while switching and exposes the dated close review", async () => {
    const date = "20261009";
    window.history.replaceState({}, "", `/?date=${date}&stage=STAGE_0925`);
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: date, stage_dates: [date], review_dates: [date], future_target_dates: [] });
      }
      if (url === "/api/v3/research/dates") return jsonResponse({ research_dates: [] });
      if (url.startsWith("/api/v3/workbench/stage")) {
        const stageId = new URL(url, window.location.origin).searchParams.get("stage") || "STAGE_0925";
        return jsonResponse(researchStagePayload(date, stageId));
      }
      return jsonResponse({ ...emptyPool, trade_date: date });
    }));

    const { container } = render(App);
    const stageButton = (stageId: string) => {
      const stageText = stageId === "STAGE_0925" ? "1. 港股通09:20" : "8. 15:45-15:55港股";
      const button = Array.from(container.querySelectorAll<HTMLButtonElement>(".timeline-grid > button"))
        .find((item) => item.textContent?.includes(stageText));
      if (!button) throw new Error(`timeline button missing for ${stageId}`);
      return button;
    };
    const expectBothResearchStagesAvailable = () => {
      for (const stageId of ["STAGE_0925", "STAGE_1545_1555"]) {
        expect(stageButton(stageId).textContent).toContain("研究选股可用");
        expect(stageButton(stageId).textContent).toContain("10 条研究选股 · 非正式");
      }
      expect(container.querySelector(".stage-panel .section-heading p")?.textContent).toContain("研究选股可用");
    };

    await waitFor(expectBothResearchStagesAvailable);
    expect(container.querySelector("[data-testid='hk-research-execution-details']")?.hasAttribute("open")).toBe(false);

    const closeButton = Array.from(container.querySelectorAll<HTMLButtonElement>(".timeline-grid > button"))
      .find((item) => item.textContent?.includes("9. 16:10 港股研究复盘"));
    expect(closeButton?.textContent).toContain("研究复盘可用");
    expect(closeButton?.textContent).toContain("点击查看只读研究复盘");

    await fireEvent.click(stageButton("STAGE_1545_1555"));
    await screen.findByRole("heading", { name: "15:45-15:55港股 阶段" });
    await waitFor(expectBothResearchStagesAvailable);

    await fireEvent.click(stageButton("STAGE_0925"));
    await screen.findByRole("heading", { name: "港股通09:20 / A股09:25竞价选股 阶段" });
    await waitFor(expectBothResearchStagesAvailable);
  });
});
