/**
 * Wire-contract regressions from B create_router at commit
 * 5010f866a993bf8a764c283696b6e2ee9a8ca18b (api.py read_history /
 * read_stock / read_review / retry_run). The literal FastAPI shapes below
 * intentionally do NOT use C fixture constructors or C TypeScript interfaces.
 * Recheck against mounted FastAPI TestClient on Mac; this is not a live capture.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/vue";
import Workbench from "../Workbench.vue";
import { createWorkbenchApi } from "../api";
import { metricLabel, laneResultLabel } from "../display";
import { sampleDay, sampleJob } from "./fixtures/sample";

const envelope = <T>(data: T, state = "READY") => ({
  schema_version: "v4.manager_workbench.v1", state, data, gaps: [],
  RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false
});
function response(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}
const day = (date: string, phase: string = "PREOPEN") => {
  const base = sampleDay();
  return envelope({
    ...base, snapshot: { ...base.snapshot!, context: { ...base.snapshot!.context, target_date: date, phase } }
  });
};
function install(handler: (url: string, init: RequestInit) => Response | Promise<Response>) {
  const spy = vi.fn((input: RequestInfo | URL, init: RequestInit = {}) => handler(String(input), init));
  vi.stubGlobal("fetch", spy);
  return spy;
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(finish => { resolve = finish; });
  return { promise, resolve };
}
describe("B mounted HTTP response shapes / Issue #41 Reviewer", () => {
  beforeEach(() => window.history.replaceState(null, "", "?date=20261013"));
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("history uses data.versions and accepts B NEW/LEGACY items without per-item target_date", async () => {
    const bHistory = {
      date: "20261013",
      versions: [
        { origin: "NEW", run_id: "real-b-run", phase: "PREOPEN",
          generated_at: "2026-10-13T09:25:00+08:00", state: "READY",
          product_sha256: "b".repeat(64), input_sha256: "a".repeat(64) },
        { origin: "LEGACY", original_run_id: "legacy-real", original_schema: "unrecognized",
          original_sha256: null, verification: "CANNOT_CONFIRM", gaps: ["LEGACY_PROVENANCE_UNVERIFIED"] }
      ]
    };
    install(url => response(url.includes("/history") ? envelope(bHistory) : day("20261013")));
    render(Workbench);
    await screen.findByText("合成标的");
    await fireEvent.click(screen.getByRole("tab", { name: "计划历史" }));
    expect(await screen.findByText("LEGACY · 原样历史")).toBeTruthy();
    const newEntry = screen.getByText("NEW · 新计划").closest("article");
    expect(newEntry?.textContent).toContain("real-b-run");
    expect(newEntry?.textContent).toContain("产品 SHA");
    expect(newEntry?.textContent).not.toContain("CANNOT_CONFIRM");
    expect(screen.getByText(/legacy-real/)).toBeTruthy();
    expect(screen.getAllByText(/20261013/).length).toBeGreaterThan(0);
    expect(screen.getByText(/LEGACY_PROVENANCE_UNVERIFIED/)).toBeTruthy();
  });

  it("displays each B lane_decisions array result without turning it into a new classification", async () => {
    const bStock = {
      market: "HK_CONNECT", symbol: "HK.00001", name: "B 服务端股票",
      decision: "SELECTED", membership_status: "VERIFIED_ELIGIBLE",
      lane_decisions: {
        ANNOUNCEMENT: [{ decision: "SELECTED", reason: "原文A" },
                       { decision: "UNASSESSED", reason: "原文B待核" }],
        US_MAPPING: [{ decision: "CONDITIONAL_WATCH", relation: "DIRECT" }],
        OVERSOLD: [{ decision: "NOT_SELECTED", high_ratio: 0.83 }],
        STAGE_REFERENCE: [{ status: "OBSERVATION_ONLY", run_id: "stage-owner" }]
      },
      reasons: ["B 合格原文复核"], conditions: [], invalidation_conditions: [],
      risks: [], evidence_ids: ["evidence-B"]
    };
    const bDetail = {
      plan_run_id: "synthetic-run-1", stock: bStock,
      lane_details: [
        { lane: "ANNOUNCEMENT", rows: [{ symbol: "HK.00001", original_text: "原文A" }],
          evidence_refs: [{ evidence_id: "evidence-B", owner: "b-announcement-owner",
            source_date: "20261013", available_at: "2026-10-13T08:50:00+08:00",
            sha256: "a".repeat(64), source_url: "https://example.org/article/1",
            verification: "VERIFIED" }] },
        { lane: "OVERSOLD", rows: [{ symbol: "HK.00001", volume_ratio: 1.2 }], evidence_refs: [] }
      ]
    };
    // The legacy multi-lane wire is still readable by the old API client,
    // but no longer the default independent recommendation UI contract.
    const api = createWorkbenchApi(vi.fn(async () => response(envelope(bDetail))) as unknown as typeof fetch);
    const detail = await api.getStock("HK.00001", "20261013", "synthetic-run-1");
    expect(laneResultLabel(bStock as never, "ANNOUNCEMENT")).toBe("严格入选、待评估");
    expect(detail.data!.lane_details).toEqual(bDetail.lane_details);
    expect(detail.data!.stock.decision).toBe("SELECTED");

  });

  it("uses B ratio, zero and null exactly, not rate or a locally recomputed numerator", () => {
    expect(metricLabel({ covered: 10, denominator: 20, ratio: 0.5 })).toBe("50%");
    expect(metricLabel({ covered: 0, denominator: 20, ratio: 0 })).toBe("0%");
    expect(metricLabel({ covered: null, denominator: null, ratio: null })).toMatch(/未知/);
    expect(metricLabel({ covered: 0, denominator: 0, ratio: null })).toMatch(/分母为0/);
    expect(metricLabel({ covered: 10, denominator: 20, ratio: 0.5 }, false)).toMatch(/缺完整Top20/);
  });

  it.each([
    [404, "ENTITY_NOT_FOUND"],
    [409, "NOT_RETRYABLE"],
    [422, "DATE_INVALID"],
    [503, "STATE_CHANNEL_UNAVAILABLE"]
  ])("shows FastAPI detail for HTTP %i instead of HTTP_xxx alone", async (status, detail) => {
    const api = createWorkbenchApi(vi.fn(async () => response({ detail }, status)) as unknown as typeof fetch);
    await expect(api.getHistory("20261013")).rejects.toMatchObject({ status,
      message: expect.stringContaining(detail) });
  });

  it("preserves FastAPI 422 structured validation detail", async () => {
    const api = createWorkbenchApi(vi.fn(async () => response({ detail: [{
      type: "less_than_equal", loc: ["query", "limit"], msg: "Input should be less than or equal to 200"
    }] }, 422)) as unknown as typeof fetch);
    await expect(api.getHistory("20261013")).rejects.toMatchObject({
      status: 422, message: expect.stringContaining("200")
    });
  });

  it("shows complete 20-row A/B review and rendered 50% B ratio with frozen classification", async () => {
    const full = Array.from({ length: 20 }, (_, i) => ({
      rank: i + 1, symbol: "HK." + String(i + 1).padStart(5, "0"),
      stock_decision: i < 10 ? "SELECTED" : i < 15 ? "CONDITIONAL_WATCH" : "NOT_IN_PLAN",
      strict_hit: i < 10, extended_hit: i < 15,
      missed_reason: i < 10 ? null : i < 15 ? "CONDITIONAL_ONLY_NOT_STRICT" : "NOT_IN_FROZEN_RESEARCH_PLAN"
    }));
    install(url => response(url.includes("/reviews/")
      ? envelope({
        target_date: "20261013", plan_run_id: "synthetic-run-1",
        mode: "FROZEN_PLAN_VS_COMPLETE_CLOSE", ranking_date: "20261013",
        top20_rows: full,
        strict_coverage: { covered: 10, denominator: 20, ratio: 0.5, intersection: [] },
        extended_coverage: { covered: 15, denominator: 20, ratio: 0.75, intersection: [] },
        selected_denominator: 10, lane_incremental_coverage: { US_MAPPING: { strict_added: 0, extended_added: 1 } },
        uncovered_reasons: ["HK.00002:NOT_IN_FROZEN_RESEARCH_PLAN"], gaps: []
      })
      : day("20261013")));
    render(Workbench);
    await screen.findByText("合成标的");
    await fireEvent.click(screen.getByRole("tab", { name: "收盘复盘" }));
    await screen.findByText("HK.00020");
    expect(screen.getAllByRole("row")).toHaveLength(21);
    expect(screen.getByText("50%")).toBeTruthy();
    expect(screen.getByText("75%")).toBeTruthy();
    expect(screen.getByText(/"extended_added":1/)).toBeTruthy();
    expect(screen.getAllByText("计划未覆盖").length).toBeGreaterThan(0);
  });

  it("keeps B day NOT_RUN with data.snapshot=null distinct from READY_EMPTY", async () => {
    install(() => response(envelope({
      snapshot: null, stocks: [], counts: null, versions: [],
      pagination: { total: 0, offset: 0, limit: 50 }
    }, "NOT_RUN")));
    render(Workbench);
    expect(await screen.findByText(/当日有效，但尚未运行/)).toBeTruthy();
    expect(screen.getByText(/完整分类计数未知/)).toBeTruthy();
    expect(screen.queryByText("研究已完成且有效空集")).toBeNull();
  });

  it("does not label an API NOT_RUN read as a stale successful plan after 503 refresh", async () => {
    let calls = 0;
    install(() => ++calls === 1
      ? response(envelope({ snapshot: null, counts: null, stocks: [], versions: [],
        pagination: { total: 0, offset: 0, limit: 50 } }, "NOT_RUN"))
      : response({ detail: "STATE_CHANNEL_UNAVAILABLE" }, 503));
    render(Workbench);
    await screen.findByText(/当日有效，但尚未运行/);
    await fireEvent.click(screen.getByRole("button", { name: "刷新读取" }));
    await screen.findByText(/STATE_CHANNEL_UNAVAILABLE/);
    expect(screen.queryByText(/上次成功读取版（非当前响应）/)).toBeNull();
  });

  it("shows new B retry job_id (not a JobRecord) and polls the new job", async () => {
    let lastJob = "job-initial";
    const spy = install((url, init) => {
      if (url.endsWith("/runs") && init?.method === "POST") return response(envelope({
        job_id: "job-initial", run_id: "run-initial", status_url: "/api/v4/manager-workbench/runs/job-initial"
      }), 202);
      if (url.endsWith("/retry") && init?.method === "POST") {
        lastJob = "job-retried";
        return response(envelope({
          job_id: lastJob, run_id: "run-retried", status_url: "/api/v4/manager-workbench/runs/job-retried"
        }), 202);
      }
      if (url.includes("/runs/")) {
        const id = url.includes("job-retried") ? "job-retried" : "job-initial";
        return response(envelope({ ...sampleJob(id === "job-retried" ? "SUCCEEDED" : "FAILED"),
          job_id: id, run_id: id === "job-retried" ? "run-retried" : "run-initial" }));
      }
      return response(day("20261013"));
    });
    render(Workbench);
    await screen.findByText("合成标的");
    await fireEvent.click(screen.getByRole("tab", { name: "研究进度" }));
    await fireEvent.click(screen.getByRole("button", { name: "生成研究计划" }));
    await screen.findByText("任务 job-initial");
    await fireEvent.click(screen.getByRole("button", { name: "仅恢复可重试失败步骤" }));
    await screen.findByText("任务 job-retried");
    expect(spy.mock.calls.some(([url]) => String(url).endsWith("/runs/job-retried"))).toBe(true);
  });

  it.each(["date", "phase", "version"] as const)("pending create followed by %s navigation clears busy flag and ignores old POST", async kind => {
    const old = deferred<Response>();
    let created = 0;
    const spy = install((url, init) => {
      if (url.endsWith("/runs") && init?.method === "POST") {
        const parsed = JSON.parse(init.body as string);
        if (++created === 1) return old.promise;
        expect(parsed.target_date).toBe(kind === "date" ? "20261014" : "20261013");
        return response(envelope({ job_id: "job-next", run_id: "run-next", status_url: "/api/v4/manager-workbench/runs/job-next" }), 202);
      }
      if (url.includes("/runs/job-next")) return response(envelope({
        ...sampleJob("SUCCEEDED"), job_id: "job-next", run_id: "run-next",
        context: { ...sampleJob("SUCCEEDED").context, target_date: kind === "date" ? "20261014" : "20261013" }
      }));
      if (url.includes("/days/20261014")) return response(day("20261014"));
      if (url.includes("/days/20261013") && url.includes("run_id=version-next")) {
        const result = day("20261013", "INTRADAY");
        return response({ ...result, data: { ...result.data,
          snapshot: { ...result.data.snapshot, run_id: "version-next" } } });
      }
      if (url.includes("/days/20261013") && url.includes("phase=INTRADAY")) return response(day("20261013", "INTRADAY"));
      const result = day("20261013");
      return response({ ...result, data: { ...result.data,
        versions: [
          { origin: "NEW", run_id: "synthetic-run-1", phase: "PREOPEN" },
          { origin: "NEW", run_id: "version-next", phase: "INTRADAY" }
        ] } });
    });
    render(Workbench);
    await screen.findByText("合成标的");
    await fireEvent.click(screen.getByRole("tab", { name: "研究进度" }));
    await fireEvent.click(screen.getByRole("button", { name: "生成研究计划" }));
    expect(screen.getByRole("button", { name: "正在提交…" }).hasAttribute("disabled")).toBe(true);
    if (kind === "date") {
      await fireEvent.update(screen.getByLabelText("目标港股日"), "20261014");
      await fireEvent.click(screen.getByRole("button", { name: "切换日期" }));
    } else if (kind === "phase") {
      await fireEvent.update(screen.getByLabelText("阶段"), "INTRADAY");
    } else {
      await fireEvent.update(screen.getByLabelText("计划版本"), "version-next");
    }
    await waitFor(() => expect(screen.getByRole("tab", { name: "今日名单" }).getAttribute("aria-selected")).toBe("true"));
    await fireEvent.click(screen.getByRole("tab", { name: "研究进度" }));
    const button = screen.getByRole("button", { name: "生成研究计划" });
    expect(button.hasAttribute("disabled")).toBe(false);
    await fireEvent.click(button);
    await screen.findByText("任务 job-next");
    old.resolve(response(envelope({ job_id: "job-old", run_id: "run-old", status_url: "/api/v4/manager-workbench/runs/job-old" }), 202));
    await waitFor(() => expect(screen.queryByText("任务 job-old")).toBeNull());
    expect(screen.getByText("任务 job-next")).toBeTruthy();
    expect(spy.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(2);
    expect(spy.mock.calls.every(([, init]) => !init?.body || typeof init.body === "string")).toBe(true);
  });

  it("pending retry then version change does not lock new page or adopt the late retry", async () => {
    const oldRetry = deferred<Response>();
    let createCount = 0;
    const spy = install((url, init) => {
      if (url.endsWith("/runs") && init?.method === "POST") {
        ++createCount;
        return response(envelope({ job_id: createCount === 1 ? "job-old" : "job-new",
          run_id: createCount === 1 ? "run-old" : "run-new", status_url: "/api/v4/manager-workbench/runs/job" }), 202);
      }
      if (url.endsWith("/retry") && init?.method === "POST") return oldRetry.promise;
      if (url.includes("/runs/job-")) return response(envelope({
        ...sampleJob(url.includes("job-new") ? "SUCCEEDED" : "FAILED"),
        job_id: url.includes("job-new") ? "job-new" : "job-old"
      }));
      if (url.includes("/days/") && url.includes("run_id=version-next")) {
        const value = day("20261013", "INTRADAY");
        return response({ ...value, data: { ...value.data,
          snapshot: { ...value.data.snapshot, run_id: "version-next" } } });
      }
      const value = day("20261013");
      return response({ ...value, data: { ...value.data,
        versions: [{ run_id: "synthetic-run-1", phase: "PREOPEN" },
          { run_id: "version-next", phase: "INTRADAY" }] } });
    });
    render(Workbench);
    await screen.findByText("合成标的");
    await fireEvent.click(screen.getByRole("tab", { name: "研究进度" }));
    await fireEvent.click(screen.getByRole("button", { name: "生成研究计划" }));
    await screen.findByText("任务 job-old");
    await fireEvent.click(screen.getByRole("button", { name: "仅恢复可重试失败步骤" }));
    await fireEvent.update(screen.getByLabelText("计划版本"), "version-next");
    await fireEvent.click(screen.getByRole("tab", { name: "研究进度" }));
    const newButton = screen.getByRole("button", { name: "生成研究计划" });
    expect(newButton.hasAttribute("disabled")).toBe(false);
    await fireEvent.click(newButton);
    await screen.findByText("任务 job-new");
    oldRetry.resolve(response(envelope({ job_id: "late-retry", run_id: "late-run", status_url: "/api/v4/manager-workbench/runs/late-retry" }), 202));
    await waitFor(() => expect(screen.queryByText("任务 late-retry")).toBeNull());
    expect(screen.getByText("任务 job-new")).toBeTruthy();
    expect(spy.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(3);
  });
});
