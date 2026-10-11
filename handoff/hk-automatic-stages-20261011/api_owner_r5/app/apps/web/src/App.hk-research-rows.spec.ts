import { cleanup, fireEvent, render, screen, within } from "@testing-library/vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App.vue";

const tradeDate = "20261009";
const stages = [
  "STAGE_0925",
  "STAGE_0930_0935",
  "STAGE_0935_0940",
  "STAGE_0940_0945",
  "STAGE_0945_1030",
  "STAGE_1300_1315",
  "STAGE_1445_1500",
  "STAGE_1545_1555",
];

const jsonResponse = (payload: unknown) => ({ ok: true, json: async () => payload });

function stagePayload(stageId: string, unifiedRows?: Array<Record<string, unknown>>) {
  const row = {
    market: "HK",
    code: "HK.00001",
    name: `研究行-${stageId}`,
    rank: 1,
    trade_date: tradeDate,
    stage_id: stageId,
    source_mode: "HK_CONNECT_RESEARCH_BACKFILL",
    source_temporal_cutoff_safe: false,
    status: "WATCH_ONLY",
    action_level: "NO_BUY",
  };
  return {
    ok: true,
    trade_date: tradeDate,
    stage: {
      stage_id: stageId,
      label: stageId,
      window: "研究回补",
      status: "PARTIAL_WITH_ROWS",
      display_status: "研究观察 · PIT 未验证",
    },
    markets: {
      A: { label: "A股", candidate_count: 0, source_rows: 0, requested_rows: 0, rows: [] },
      HK: {
        label: "港股通",
        status: "PARTIAL_WITH_ROWS",
        selection_mode: "BACKFILL",
        selection_status: "PARTIAL_WITH_ROWS",
        display_mode: "OBSERVATION_UNVERIFIED",
        candidate_count: 1,
        observation_count: 1,
        selected_rows: 1,
        source_rows: 1,
        requested_rows: 2,
        rows: [row],
        cannot_confirm: ["PIT_UNVERIFIED"],
        source_evidence: ["research_only=true"],
      },
    },
    unified_rows: unifiedRows ?? [row],
    selected_a_rows: 0,
    selected_hk_rows: 1,
    selected_total_rows: 1,
    selection_mode: "BACKFILL",
    mode: "BACKFILL",
    RESEARCH_ONLY: true,
    production_allowed: false,
    buy_gate_updated: false,
    orders_sent: false,
    write_performed: false,
  };
}

function stubStageWorkbenchFetch(payloadForStage: (stageId: string) => unknown) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === "/api/v1/runs/date-list") {
      return jsonResponse({ default_date: tradeDate, stage_dates: [tradeDate], future_target_dates: [] });
    }
    if (url === "/api/v3/research/dates") return jsonResponse({ research_dates: [] });
    if (url.startsWith("/api/v3/workbench/stage?")) {
      const query = new URL(url, window.location.origin).searchParams;
      return jsonResponse(payloadForStage(query.get("stage") || stages[0]));
    }
    if (url.startsWith("/api/v3/preselection-pools")) {
      return jsonResponse({ trade_date: tradeDate, data_status: "DATA_BLOCKED_EMPTY", rows: [], pools: [] });
    }
    return jsonResponse({});
  }));
}

describe("HK research rows across the stage timeline", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.history.replaceState({}, "", "/");
  });

  it("labels partial observation rows as nonformal research for all eight HK stages", async () => {
    window.history.replaceState({}, "", `/?date=${tradeDate}&stage=${stages[0]}`);
    stubStageWorkbenchFetch(stagePayload);

    render(App);
    const stagePicker = screen.getByRole("combobox", { name: "阶段" });
    const hkRegion = screen.getByTestId("stage-candidates-HK");

    for (const stageId of stages) {
      if (stageId !== stages[0]) await fireEvent.update(stagePicker, stageId);
      expect(await within(hkRegion).findByText(`研究行-${stageId}`)).toBeTruthy();
      expect(within(hkRegion).getByText("研究候选 · 非正式")).toBeTruthy();
      expect(hkRegion.querySelectorAll(".candidate-card")).toHaveLength(1);
    }
  });

  it("renders only matching research rows when unified_rows also contains invalid HK rows", async () => {
    const stageId = "STAGE_0930_0935";
    const valid = {
      market: "HK",
      code: "HK.00001",
      name: "有效研究行",
      rank: 1,
      trade_date: tradeDate,
      stage_id: stageId,
      source_mode: "HK_CONNECT_RESEARCH_BACKFILL",
      source_temporal_cutoff_safe: false,
      status: "WATCH_ONLY",
      action_level: "NO_BUY",
    };
    const invalidRows = [
      { ...valid, code: "HK.00002", name: "错误日期行", trade_date: "20261008" },
      { ...valid, code: "HK.00003", name: "错误阶段行", stage_id: "STAGE_0935_0940" },
      { ...valid, code: "HK.00004", name: "缺来源行", source_mode: "" },
      { ...valid, code: "", name: "缺代码行" },
    ];
    const rows: Array<Record<string, unknown>> = [valid, ...invalidRows];
    window.history.replaceState({}, "", `/?date=${tradeDate}&stage=${stageId}`);
    stubStageWorkbenchFetch((selectedStage) => stagePayload(selectedStage, rows));

    render(App);
    const hkRegion = screen.getByTestId("stage-candidates-HK");

    expect(await within(hkRegion).findByText("有效研究行")).toBeTruthy();
    expect(within(hkRegion).getByText("研究候选 · 非正式")).toBeTruthy();
    for (const invalid of invalidRows) {
      expect(within(hkRegion).queryByText(String(invalid.name))).toBeNull();
    }
    expect(hkRegion.querySelectorAll(".candidate-card")).toHaveLength(1);
  });

  it("does not enter research mode when no unified HK row passes the research predicate", async () => {
    const stageId = "STAGE_0930_0935";
    const rows: Array<Record<string, unknown>> = [
      {
        market: "HK",
        code: "HK.00002",
        name: "错误日期行",
        trade_date: "20261008",
        stage_id: stageId,
        source_mode: "HK_CONNECT_RESEARCH_BACKFILL",
      },
      {
        market: "HK",
        code: "HK.00003",
        name: "错误阶段行",
        trade_date: tradeDate,
        stage_id: "STAGE_0935_0940",
        source_mode: "HK_CONNECT_RESEARCH_BACKFILL",
      },
    ];
    window.history.replaceState({}, "", `/?date=${tradeDate}&stage=${stageId}`);
    stubStageWorkbenchFetch((selectedStage) => stagePayload(selectedStage, rows));

    render(App);
    const hkRegion = screen.getByTestId("stage-candidates-HK");

    expect(await within(hkRegion).findByText("错误日期行")).toBeTruthy();
    expect(within(hkRegion).getByText("错误阶段行")).toBeTruthy();
    expect(within(hkRegion).queryByText("研究候选 · 非正式")).toBeNull();
    expect(within(hkRegion).getAllByText("观察 · 未验证")).toHaveLength(2);
  });
});
