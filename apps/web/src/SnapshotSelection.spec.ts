import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App.vue";
import { loadStageSnapshot } from "./api/pool_stage";
import { stageMarketStateText } from "./app_shell/formatters";
import type { StageWorkbench } from "./app_shell/types";

const fixture = vi.hoisted(() => ({ formalEmpty: false, lineage: false, emptyReselection: false, invalidReselection: false, originalARows: false }));
vi.mock("./components/research/GlobalIndustryMap.vue", async () => {
  const { defineComponent, h } = await import("vue");
  return { default: defineComponent({
    props: { targetDate: String },
    setup(props) { return () => h("div", { "data-testid": "industry-map", "data-date": props.targetDate }); },
  }) };
});
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
        : { status: "CANNOT_CONFIRM", source_status: "CANNOT_CONFIRM", selection_status: "CANNOT_CONFIRM",
          requested_rows: null, source_rows: null, selected_rows: null, display_reasons: ["ORIGINAL_INPUT_MISSING"],
          cannot_confirm: ["ORIGINAL_SELECTION_NOT_VERIFIED"] },
      HK: { status: "PARTIAL_WITH_ROWS", source_status: "READY", selected_rows: 1,
        display_mode: "OBSERVATION_UNVERIFIED", observation_count: 1 },
    },
    unified_rows: fixture.originalARows
      ? [{ market: "A", code: "A.600000", name: "原始A样本", rank: 1, stage_display_decision: "原阶段候选" }]
      : [{ market: "HK", code: "HK.00001", name: "合成HK样本", action_level: "NO_BUY" }],
    execution_evidence: { natural_verified: false, execution_verified: false, cannot_confirm: ["ORIGINAL_INPUT_MISSING"], observed_sha256: "e".repeat(64) },
    stage_lineage: fixture.lineage ? {
      natural: { label: "ORIGINAL_NATURAL_RUN", status: "FAILED", receipt_sha256: "d".repeat(64), write_performed: false },
      recovery: { label: "CONTROLLED_RECOVERY", status: "CANNOT_CONFIRM" }, cannot_confirm: ["ORIGINAL_RECEIPT_GAP"],
    } : undefined,
    snapshot_recovery: fixture.formalEmpty ? undefined : { markets: { A_SHARE: {
      mode: "SNAPSHOT_RECOVERY_OBSERVATION", captured_at: "2026-10-29T15:19:00+08:00",
      original_stage_cutoff_at: "2026-10-29T09:35:00+08:00", after_original_cutoff: true,
      observed_rows: 56, requested_rows: 56, missing_symbols: [], gaps: ["SNAPSHOT_AFTER_CUTOFF"],
      rows: Array.from({ length: 56 }, (_, index) => ({ code: `A.${String(index + 1).padStart(6, "0")}`,
        name: `报价样本${index + 1}`, last_price: 10, source_update_time: index === 55 ? null : "2026-10-29 15:00:00",
        captured_at: "2026-10-29T15:19:00+08:00" })),
    } } },
    snapshot_reselection: fixture.invalidReselection
      ? { status: "CANNOT_CONFIRM", markets: { A_SHARE: {
        mode: "AFTERFACT_SNAPSHOT_RESELECTION", selected_rows: 10, rows: [{ code: "A.000001", rank: 1 }],
      } } }
      : fixture.emptyReselection
      ? { status: "SELECTED_WATCH_ONLY", markets: { A_SHARE: {
        mode: "AFTERFACT_SNAPSHOT_RESELECTION", selected_rows: 0, scored_rows: 522, rows: [],
      } } }
      : fixture.formalEmpty
      ? { status: "FORMAL_RESULT_AVAILABLE", markets: {} }
      : { status: "SELECTED_WATCH_ONLY", markets: { A_SHARE: {
        mode: "AFTERFACT_SNAPSHOT_RESELECTION", selected_rows: 10, scored_rows: 522,
        captured_at: "2026-10-30T09:37:58.479577+08:00", scoring_evaluated_at: "2026-10-30T10:29:14.686799+08:00",
        context_status: "NO_VERIFIED_RESEARCH_CONTEXT", context_slot: null, context_reader_as_of: null,
        context_fallback_used: true, context_rejections: [], algorithm_sha256: "b".repeat(64),
        rows: Array.from({ length: 10 }, (_, index) => ({ code: `A.${String(index + 1).padStart(6, "0")}`,
          rank: index + 1, name: `合成A样本${index + 1}`, score: 50, source_last_bar_time: "2026-10-30 09:35:00",
          news_quality_score: null, research_quality_score: null })),
      } } },
  };
}

beforeEach(() => {
  fixture.formalEmpty = false;
  fixture.lineage = false;
  fixture.emptyReselection = false;
  fixture.invalidReselection = false;
  fixture.originalARows = false;
  window.history.replaceState({}, "", "/?date=20261029&stage=STAGE_0930_0935");
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const body = url.includes("/api/v1/runs/date-list")
      ? { default_date: "20261029", navigation_date: "20261029", dates: ["20261028", "20261029"], stage_dates: ["20261028", "20261029"], future_target_dates: [] }
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
    expect(panel.textContent).toContain("09:37:58.479577");
    expect(panel.textContent).toContain("10:29:14.686799");
    expect(panel.textContent).toContain("522 条有效报价");
    expect(panel.textContent).toContain("09:35:00");
    expect(panel.textContent).toContain("非原阶段自然选股、非竞价重演");
    expect(panel.textContent).toContain("null ／ null");
    expect(screen.queryByText("A股选股结果待确认")).toBeNull();
    const aEmptyCard = screen.getByText("本阶段已完成事后补选 10 条").closest(".empty-card")!;
    expect(aEmptyCard.textContent).toContain("WATCH_ONLY");
    expect(aEmptyCard.textContent).toContain("2026-10-30T09:37:58.479577+08:00");
    const top10Link = within(aEmptyCard).getByRole("link", { name: "定位到事后补选 Top10" });
    expect(top10Link.getAttribute("href")).toBe("#snapshot-reselection-top10");
    expect(document.querySelectorAll('[id="snapshot-reselection-top10"]')).toHaveLength(1);
    expect(document.querySelector("#snapshot-reselection-top10")?.tagName).toBe("TABLE");
    const originalDetails = aEmptyCard.querySelector("details")!;
    expect(originalDetails.open).toBe(false);
    const loadCount = vi.mocked(loadStageSnapshot).mock.calls.length;
    const fetchCount = vi.mocked(fetch).mock.calls.length;
    await fireEvent.click(top10Link);
    expect(vi.mocked(loadStageSnapshot).mock.calls).toHaveLength(loadCount);
    expect(vi.mocked(fetch).mock.calls).toHaveLength(fetchCount);
    await fireEvent.click(within(aEmptyCard).getByText("原阶段结果缺失/失败详情"));
    expect(originalDetails.open).toBe(true);
    expect(originalDetails.textContent).toContain("source rows — / requested —");
    expect(originalDetails.textContent).toContain("CANNOT_CONFIRM");
    expect(originalDetails.textContent).toContain("ORIGINAL_INPUT_MISSING");
    expect(originalDetails.textContent).toContain("ORIGINAL_SELECTION_NOT_VERIFIED");
    expect(document.body.textContent).toContain("合成HK样本");
    expect(stageMarketStateText(makeWorkbench() as unknown as StageWorkbench, "A")).toBe("事后补选10条 · 快照09:37 · 非原时点");
    expect(stageMarketStateText(makeWorkbench() as unknown as StageWorkbench, "HK")).toContain("观察行");
    await fireEvent.click(screen.getByRole("button", { name: "SOP" }));
    await waitFor(() => expect(document.querySelector("[data-sop-view]")?.textContent).toContain("SOP既有内容"));
    expect(new URLSearchParams(window.location.search).get("view")).toBe("sop");
  });

  it("mounts the industry map only while expanded and follows the selected date", async () => {
    render(App);
    await screen.findByText("本阶段已完成事后补选 10 条");
    const summary = screen.getByText("全球行业参考地图");
    const details = summary.closest("details")!;
    expect(details.open).toBe(false);
    expect(screen.queryByTestId("industry-map")).toBeNull();
    await fireEvent.click(summary);
    await waitFor(() => expect(screen.getByTestId("industry-map").getAttribute("data-date")).toBe("20261029"));
    await fireEvent.change(screen.getByLabelText("交易日（日历选择）"), { target: { value: "2026-10-28" } });
    await waitFor(() => expect(screen.getByTestId("industry-map").getAttribute("data-date")).toBe("20261028"));
    await fireEvent.click(summary);
    await waitFor(() => expect(screen.queryByTestId("industry-map")).toBeNull());
  });

  it("keeps failure, clocks and Top10 visible while detailed lineage and quotes are closed", async () => {
    fixture.lineage = true;
    render(App);
    const selection = await screen.findByRole("generic", { name: "事后快照补选Top10" });
    const lineage = screen.getByRole("region", { name: "阶段运行血缘" });
    const lineageDetails = within(lineage).getByText("展开运行血缘详情").closest("details")!;
    expect(lineageDetails.open).toBe(false);
    expect(lineage.textContent).toContain("ORIGINAL_NATURAL_RUN · status=FAILED");
    expect(lineage.textContent).toContain("ORIGINAL_RECEIPT_GAP");
    expect(lineageDetails.textContent).toContain("d".repeat(64));
    const observation = screen.getByRole("generic", { name: "当前快照降级观察" });
    const quoteDetails = within(observation).getByText("展开原始报价观察表").closest("details")!;
    expect(quoteDetails.open).toBe(false);
    expect(observation.textContent).toContain("报价源更新时间：2026-10-29 15:00:00、部分源时点缺失");
    expect(observation.textContent).toContain("真实采集：2026-10-29T15:19:00+08:00");
    expect(observation.textContent).toContain("晚于原截止：是");
    expect(selection.closest("details")).toBeNull();
    expect(within(selection).getAllByRole("row")).toHaveLength(11);
    expect(selection.textContent).toContain("WATCH_ONLY");
    expect(selection.textContent).toContain("2026-10-30T10:29:14.686799+08:00");
    await fireEvent.click(within(lineage).getByText("展开运行血缘详情"));
    await fireEvent.click(within(observation).getByText("展开原始报价观察表"));
    expect(lineageDetails.open).toBe(true);
    expect(quoteDetails.open).toBe(true);
    expect(within(quoteDetails).getAllByRole("row")).toHaveLength(57);
    expect(within(quoteDetails).getByText("报价样本56")).toBeTruthy();
  });

  it("shows missing original execution evidence even with lineage details closed", async () => {
    render(App);
    await screen.findByRole("generic", { name: "事后快照补选Top10" });
    const lineage = screen.getByRole("region", { name: "阶段运行血缘" });
    const details = within(lineage).getByText("展开运行血缘详情").closest("details")!;
    expect(details.open).toBe(false);
    expect(Array.from(lineage.children).some((element) => element !== details && element.textContent?.includes("ORIGINAL_INPUT_MISSING"))).toBe(true);
    await fireEvent.click(within(lineage).getByText("展开运行血缘详情"));
    expect(details.open).toBe(true);
    expect(details.textContent).toContain("e".repeat(64));
  });

  it("leaves verified original zero-result precedence intact", async () => {
    fixture.formalEmpty = true;
    render(App);
    await screen.findByText("A股本阶段无入选");
    expect(document.querySelector("[data-snapshot-reselection]")).toBeNull();
    expect(stageMarketStateText(makeWorkbench() as unknown as StageWorkbench, "A")).toBe("成功零结果 · 0 条");
  });

  it("does not promote an empty after-fact snapshot selection", async () => {
    fixture.emptyReselection = true;
    render(App);
    await screen.findByText("A股选股结果待确认");
    expect(screen.queryByText("本阶段已完成事后补选 0 条")).toBeNull();
    expect(screen.queryByRole("link", { name: "定位到事后补选 Top10" })).toBeNull();
  });

  it("does not promote a selection without valid WATCH_ONLY status", async () => {
    fixture.invalidReselection = true;
    render(App);
    await screen.findByText("A股选股结果待确认");
    expect(document.querySelector("[data-snapshot-reselection]")).toBeNull();
    expect(screen.queryByRole("link", { name: "定位到事后补选 Top10" })).toBeNull();
  });

  it("leaves an original A-share result in the existing candidate card", async () => {
    fixture.originalARows = true;
    render(App);
    expect(await screen.findByText("原始A样本")).toBeTruthy();
    expect(screen.queryByText("本阶段已完成事后补选 10 条")).toBeNull();
    expect(screen.queryByText("A股选股结果待确认")).toBeNull();
  });
});
