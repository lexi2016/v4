import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App.vue";
import { stageMarketStateText } from "./app_shell/formatters";
import type { StageWorkbench } from "./app_shell/types";

const fixture = vi.hoisted(() => ({ formalEmpty: false }));
vi.mock("./api/review", () => ({ loadReview: vi.fn() }));
vi.mock("./api/runtime", () => ({
  loadTaskStatus: vi.fn(async (date: string) => ({ business_date: date, timeline_nodes: [] })),
}));
vi.mock("./api/pool_stage", () => ({
  loadPoolSnapshot: vi.fn(async () => null),
  loadStageSnapshot: vi.fn(async (date: string, stage: string) => makeWorkbench(date, stage)),
  projectSummaryPoolPage: vi.fn(() => null), POOL_PAGE_SIZE: 200,
}));

// Synthetic integration response: no raw market fixture or engine recomputation.
function makeWorkbench(date = "20261029", stage = "STAGE_0930_0935") {
  return {
    trade_date: date, status: "CANNOT_CONFIRM",
    stage: { stage_id: stage, display_status: "原始输入缺失，回执保留" },
    selected_a_rows: fixture.formalEmpty ? 0 : null, selected_hk_rows: 1,
    markets: {
      A: fixture.formalEmpty
        ? { status: "READY", source_status: "READY", selection_status: "READY", requested_rows: 1,
          source_rows: 1, selected_rows: 0, display_mode: "READY_EMPTY", selection_manifest_receipt_verified: true,
          selection_artifact_sha256: "a".repeat(64) }
        : { status: "CANNOT_CONFIRM", source_status: "CANNOT_CONFIRM", source_rows: null, selected_rows: null },
      HK: { status: "PARTIAL_WITH_ROWS", source_status: "READY", selected_rows: 1,
        display_mode: "OBSERVATION_UNVERIFIED", observation_count: 1 },
    },
    unified_rows: [{ market: "HK", code: "HK.00001", name: "合成HK样本", action_level: "NO_BUY" }],
    execution_evidence: { natural_verified: false, execution_verified: false, cannot_confirm: ["ORIGINAL_INPUT_MISSING"] },
    snapshot_reselection: fixture.formalEmpty
      ? { status: "FORMAL_RESULT_AVAILABLE", markets: {} }
      : { status: "SELECTED_WATCH_ONLY", markets: { A_SHARE: {
        mode: "AFTERFACT_SNAPSHOT_RESELECTION", selected_rows: 10, scored_rows: 56,
        captured_at: "2026-10-29T15:19:00+08:00", scoring_evaluated_at: "2026-10-29T17:41:00+08:00",
        context_status: "NO_VERIFIED_RESEARCH_CONTEXT", context_slot: null, context_reader_as_of: null,
        context_fallback_used: true, context_rejections: [], algorithm_sha256: "b".repeat(64),
        rows: Array.from({ length: 10 }, (_, index) => ({ code: `A.${String(index + 1).padStart(6, "0")}`,
          rank: index + 1, name: `合成A样本${index + 1}`, score: 50, source_last_bar_time: "2026-10-29 15:00:00",
          news_quality_score: null, research_quality_score: null })),
      } } },
  };
}

beforeEach(() => {
  fixture.formalEmpty = false;
  window.history.replaceState({}, "", "/?date=20261029&stage=STAGE_0930_0935");
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const body = url.includes("/api/v1/runs/date-list")
      ? { default_date: "20261029", navigation_date: "20261029", dates: ["20261029"], stage_dates: ["20261029"], future_target_dates: [] }
      : url.includes("/api/v4/operations/sop")
        ? { id: "overview", title: "合成SOP", content: "SOP既有内容", sha256: "c".repeat(64), updated_at: "2026-10-29", relative_path: "docs/SOP.md" }
        : {};
    return { ok: true, json: async () => body } as Response;
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("current stage supplementary selection integration", () => {
  it("renders actual supplementary rows, truthful clocks and null scores while preserving SOP navigation", async () => {
    render(App);
    const panel = await screen.findByRole("generic", { name: "事后快照补选Top10" });
    expect(within(panel).getAllByRole("row")).toHaveLength(11);
    expect(panel.textContent).toContain("15:19:00");
    expect(panel.textContent).toContain("17:41:00");
    expect(panel.textContent).toContain("15:00:00");
    expect(panel.textContent).toContain("非原阶段自然选股、非竞价重演");
    expect(panel.textContent).toContain("null ／ null");
    expect(screen.getByText("A股选股结果待确认")).toBeTruthy();
    expect(document.body.textContent).toContain("合成HK样本");
    expect(stageMarketStateText(makeWorkbench() as unknown as StageWorkbench, "A")).toBe("事后补选10条 · 快照15:19 · 非原时点");
    expect(stageMarketStateText(makeWorkbench() as unknown as StageWorkbench, "HK")).toContain("观察行");
    await fireEvent.click(screen.getByRole("button", { name: "SOP" }));
    await waitFor(() => expect(document.querySelector("[data-sop-view]")?.textContent).toContain("SOP既有内容"));
    expect(new URLSearchParams(window.location.search).get("view")).toBe("sop");
  });

  it("leaves verified original zero-result precedence intact", async () => {
    fixture.formalEmpty = true;
    render(App);
    await screen.findByText("A股本阶段无入选");
    expect(document.querySelector("[data-snapshot-reselection]")).toBeNull();
    expect(stageMarketStateText(makeWorkbench() as unknown as StageWorkbench, "A")).toBe("成功零结果 · 0 条");
  });
});
