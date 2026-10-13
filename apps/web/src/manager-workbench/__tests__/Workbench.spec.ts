import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/vue";
import Workbench from "../Workbench.vue";
import { sampleDay, sampleHistory, sampleJob, sampleReview, sampleStock, wrapped } from "./fixtures/sample";
import type { DayData } from "../types";

function response(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}
function install(handler: (url: string, init: RequestInit) => Promise<Response> | Response) {
  const spy = vi.fn((input: RequestInfo | URL, init: RequestInit = {}) => handler(String(input), init));
  vi.stubGlobal("fetch", spy);
  return spy;
}
async function loadSample(overrides: Partial<DayData> = {}) {
  install(async () => response(wrapped(sampleDay(overrides))));
  render(Workbench);
  await screen.findByText("合成标的");
}

describe("C manager workbench screen", () => {
  beforeEach(() => { window.history.replaceState(null, "", "?date=20261013"); });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("renders the selected lane row, with unknown counts distinct from zero", async () => {
    await loadSample();
    expect(screen.getByText("合成标的")).toBeTruthy();
    expect(screen.getAllByText("严格入选").length).toBeGreaterThan(0);
    expect(screen.getAllByText("条件观察").length).toBeGreaterThan(0);
    expect(screen.getAllByText("未知").length).toBeGreaterThan(0);
    expect(screen.getByText(/服务端筛选后共 1 行/)).toBeTruthy();
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(2);
    expect(screen.queryByText("阶段参考 · 观察")).toBeNull();
    expect(screen.getByText("资格：待核验")).toBeTruthy();
    expect(screen.getByText(/production_allowed=false/)).toBeTruthy();
    expect(screen.getByText(/orders_sent=false/)).toBeTruthy();
  });

  it("renders B-owned membership_status and uppercase RESEARCH_ONLY without inference", async () => {
    const stock = sampleStock();
    stock.membership_status = "VERIFIED";
    await loadSample({ stocks: [stock] });
    expect(screen.getByText("资格：VERIFIED")).toBeTruthy();
    expect(screen.getByText(/RESEARCH_ONLY=true/)).toBeTruthy();
  });

  it("distinguishes valid NOT_RUN and READY_EMPTY without manufacturing counts", async () => {
    install(async () => response(wrapped(null, "NOT_RUN")));
    const { unmount } = render(Workbench);
    await screen.findByText(/当日有效，但尚未运行/);
    expect(screen.getByText(/完整分类计数未知/)).toBeTruthy();
    unmount(); cleanup();
    const empty = sampleDay({ stocks: [], pagination: { total: 0, offset: 0, limit: 50 } });
    empty.snapshot!.lanes = empty.snapshot!.lanes!.map(lane => ({ ...lane, state: "READY_EMPTY" }));
    empty.counts = { selected: 0, watch: 0, unassessed: 0, observation_only: 0, not_selected: 0 };
    install(async () => response(wrapped(empty, "READY_EMPTY")));
    render(Workbench);
    await screen.findByText("研究已完成且有效空集");
  });

  it("keeps complete counts while fetching >200 paginated server rows", async () => {
    const spy = install(async url => {
      const offset = Number(new URL(url, "http://localhost").searchParams.get("offset") || "0");
      return response(wrapped(sampleDay({
        stocks: Array.from({ length: 50 }, (_, i) => sampleStock("HK." + String(offset + i + 1).padStart(5, "0"), "合成#" + (offset + i + 1))),
        counts: { selected: 0, watch: 251, unassessed: 0, observation_only: 0, not_selected: 0 },
        pagination: { total: 251, offset, limit: 50 }
      })));
    });
    render(Workbench);
    await screen.findByText("合成#1");
    expect(screen.getByText("251")).toBeTruthy();
    await fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    await screen.findByText("合成#51");
    expect(screen.getByText("251")).toBeTruthy();
    expect(spy.mock.calls.some(x => String(x[0]).includes("offset=50"))).toBe(true);
  });

  it("invalid date blocks GET and date changes reject late response even if transport ignores abort", async () => {
    const oldDay = sampleDay();
    const newDay = sampleDay({ snapshot: { ...oldDay.snapshot!,
      context: { ...oldDay.snapshot!.context, target_date: "20261014" },
      run_id: "new-run" }, stocks: [sampleStock("HK.00099", "新日标的")] });
    let releaseOld: ((result: Response) => void) | undefined;
    const first = new Promise<Response>(resolve => { releaseOld = resolve; });
    const spy = install(url => url.includes("20261014") ? response(wrapped(newDay)) : first);
    render(Workbench);
    await fireEvent.update(screen.getByLabelText("目标港股日"), "20261014");
    await fireEvent.click(screen.getByRole("button", { name: "切换日期" }));
    await screen.findByText("新日标的");
    releaseOld?.(response(wrapped(oldDay)));
    await waitFor(() => expect(screen.queryByText("合成标的")).toBeNull());
    expect(screen.getByText("new-run")).toBeTruthy();
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("on same-query refresh failure shows previous successful version explicitly, never as current", async () => {
    let requests = 0;
    install(async () => ++requests === 1 ? response(wrapped(sampleDay())) :
      response({ schema_version: "v4.manager_workbench.v1", state: "UNAVAILABLE", data: null, gaps: [] }, 503));
    render(Workbench);
    await screen.findByText("合成标的");
    await fireEvent.click(screen.getByRole("button", { name: "刷新读取" }));
    await screen.findByText(/上次成功读取版（非当前响应）/);
    expect(screen.getByText("合成标的")).toBeTruthy();
    expect(screen.getByText(/接口 503/)).toBeTruthy();
  });

  it("stock detail uses run_id; the native button supports keyboard focus", async () => {
    const spy = install(async url => url.includes("/stocks/") ?
      response(wrapped({ recommendation_lane: "US_MAPPING", plan_run_id: "synthetic-run-1", stock: sampleStock(), lane_details: [{
        lane: "ANNOUNCEMENT", rows: [], evidence_refs: [{
        evidence_id: "synthetic-evidence", owner: "synthetic", sha256: "abc", verification: "VERIFIED",
        source_url: "javascript:alert(1)"
      }] }] })) : response(wrapped(sampleDay())));
    render(Workbench);
    await screen.findByText("合成标的");
    const button = screen.getByRole("button", { name: /查看 HK.01234/ });
    button.focus();
    expect(document.activeElement).toBe(button);
    await fireEvent.click(button);
    await screen.findByText("失效条件");
    expect(spy.mock.calls.some(([url]) => String(url).includes("run_id=synthetic-run-1"))).toBe(true);
    await fireEvent.click(screen.getByText("证据身份、原始引用与校验缺口"));
    expect(screen.queryByRole("link", { name: "打开原文" })).toBeNull();
  });

  it("shows lane states without concealing a valid stock when another lane FAILED", async () => {
    await loadSample();
    await fireEvent.click(screen.getByRole("tab", { name: "研究进度" }));
    for (const state of ["失败", "完成", "有效空集", "不适用", "输入缺失"]) {
      expect(screen.getByText(state)).toBeTruthy();
    }
    expect(screen.getAllByText("未知").length).toBeGreaterThan(0);
  });

  it("defines all eight lane states with distinct human-readable labels", async () => {
    const { LANE_STATE_LABELS } = await import("../types");
    expect(Object.keys(LANE_STATE_LABELS)).toHaveLength(8);
    expect(new Set(Object.values(LANE_STATE_LABELS)).size).toBe(8);
    expect(LANE_STATE_LABELS.NOT_RUN).not.toBe(LANE_STATE_LABELS.READY_EMPTY);
    expect(LANE_STATE_LABELS.PARTIAL).not.toBe(LANE_STATE_LABELS.FAILED);
  });

  it("only POST creates a task; failed retry conflict is visible rather than overwritten", async () => {
    const spy = install(async (url, init) => {
      if (url.endsWith("/runs") && init.method === "POST") {
        return response(wrapped({ job_id: "synthetic-job-1", run_id: "synthetic-run-2", status_url: "/runs/synthetic-job-1" }));
      }
      if (url.endsWith("/retry")) return response(wrapped(null, "CONFLICT"), 409);
      if (url.includes("/runs/")) return response(wrapped(sampleJob()));
      return response(wrapped(sampleDay()));
    });
    render(Workbench);
    await screen.findByText("合成标的");
    await fireEvent.click(screen.getByRole("tab", { name: "研究进度" }));
    await fireEvent.click(screen.getByRole("button", { name: "生成研究计划" }));
    await screen.findByText(/UPSTREAM_MISSING/);
    expect(spy.mock.calls.some(x => x[1]?.method === "POST" && String(x[0]).endsWith("/runs"))).toBe(true);
    await fireEvent.click(screen.getByRole("button", { name: "仅恢复可重试失败步骤" }));
    await screen.findByText(/接口 409/);
    expect(spy.mock.calls.filter(x => x[1]?.method === "POST")).toHaveLength(2);
  });

  it("old history remains labelled LEGACY and retrospective is not preopen evidence", async () => {
    install(async url => url.includes("/history") ? response(wrapped(sampleHistory())) : response(wrapped(sampleDay())));
    render(Workbench);
    await screen.findByText("合成标的");
    await fireEvent.click(screen.getByRole("tab", { name: "计划历史" }));
    await screen.findByText("LEGACY · 原样历史");
    expect(screen.getByText(/RETROSPECTIVE · 事后回看/)).toBeTruthy();
    expect(screen.getByText(/原来源缺失/)).toBeTruthy();
  });

  it("renders 20 supplied review rows and does not calculate missing or zero-denominator coverage", async () => {
    install(async url => url.includes("/reviews/") ? response(wrapped(sampleReview())) : response(wrapped(sampleDay())));
    const { unmount } = render(Workbench);
    await screen.findByText("合成标的");
    await fireEvent.click(screen.getByRole("tab", { name: "收盘复盘" }));
    await screen.findByText("HK.00020");
    expect(screen.getAllByRole("row")).toHaveLength(21);
    unmount(); cleanup();
    install(async url => url.includes("/reviews/") ?
      response(wrapped({ ...sampleReview(null),
        strict_coverage: { covered: 0, denominator: 0, ratio: null },
        extended_coverage: null })) : response(wrapped(sampleDay())));
    render(Workbench);
    await screen.findByText("合成标的");
    await fireEvent.click(screen.getByRole("tab", { name: "收盘复盘" }));
    await screen.findByText(/榜单缺失或不足完整20行/);
    expect(screen.getByText(/不适用（分母为0）/)).toBeTruthy();
    expect(screen.getAllByText("不适用（缺完整Top20）")).toHaveLength(1);
  });
});
