import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/vue";
import Workbench from "../Workbench.vue";

function envelope<T>(data: T, state = "READY"): Record<string, unknown> {
  return { schema_version: "v4.manager_workbench.v1", state, data, gaps: [],
    RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false };
}
function response(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}

describe("announcement candidate workbench", () => {
  beforeEach(() => { window.history.replaceState(null, "", "?date=20261016"); });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("reads candidates only after opening the panel and starts capture only on explicit click", async () => {
    const day = { snapshot: null, stocks: [], counts: null,
      pagination: { total: 0, offset: 0, limit: 50 }, versions: [] };
    const stocks = Array.from({ length: 20 }, (_, index) => {
      const isFirst = index === 0;
      const symbol = isFirst ? "HK.09963" : `HK.${10000 + index}`;
      const name = isFirst ? "高途" : `候选${index + 1}`;
      const reason = isFirst ? "公告披露订单金额同比增长，构成正向候选。" : `候选公告${index + 1}的复核理由。`;
      return {
        symbol, name, reasons: [isFirst ? "订单规模增长" : reason],
        review_status: "MODEL_CANDIDATE_UNREVIEWED", reuse_status: null,
        articles: [{ article_id: isFirst ? "EASTMONEY:AN1" : `EASTMONEY:TEST${index + 1}`,
          title: isFirst ? "高途公告" : `候选公告${index + 1}`, publication_date: "2026-10-15",
          symbol, name, disposition: "SELECTED_EVENT", direction: "POSITIVE",
          selection_basis: isFirst ? "公告明确新增订单" : "公告披露事项",
          reason, impact: isFirst ? ["订单金额提升"] : [],
          body_sha256: "a".repeat(64), source_sha256: "b".repeat(64), source_origins: [],
          review_status: "MODEL_CANDIDATE_UNREVIEWED", reuse_status: null }]
      };
    });
    const announcement = {
      state: "PARTIAL", source_date: "2026-10-15", target_trade_date: "CANNOT_CONFIRM",
      updated_at: "2026-10-16T01:00:00Z", review_status: "MODEL_CANDIDATE_UNREVIEWED",
      counts: { source_catalogue_articles: 392, model_succeeded: 367, selected_model_articles: 21,
        model_candidate_stocks: 19, reused_reviewed_stocks: 1, displayed_stocks: 20,
        failed: 18, pending: 5, body_gaps: 1 },
      stocks,
      failures: Array.from({ length: 18 }, (_, index) => ({
        article_id: index === 0 ? "EASTMONEY:AN2" : `EASTMONEY:FAILED${index + 1}`,
        symbol: index === 0 ? "HK.00001" : `HK.${20000 + index}`,
        title: index === 0 ? "失败公告" : `失败公告${index + 1}`,
        failure_code: "VALIDATOR_ERROR"
      })),
      pending: [
        { article_id: "EASTMONEY:AN202610151830512065", symbol: "HK.01903", title: "2026 年报",
          queue_status: "PENDING", queue_reason: "STOPPED_AFTER_SYSTEM_FAILURE",
          context_admission: "INPUT_EXCEEDS_CONTEXT", execution_admission: "AWAITING_FULL_BODY_CHUNKING" },
        { article_id: "EASTMONEY:AN202610151830537810", symbol: "HK.00411", title: "2026年环境、社会及管治报告",
          queue_status: "PENDING", queue_reason: "STOPPED_AFTER_SYSTEM_FAILURE",
          context_admission: "INPUT_FITS", execution_admission: "DIRECT_SINGLE_REQUEST" },
        { article_id: "EASTMONEY:AN202610151830523030", symbol: "HK.03908",
          title: "海外监管公告 – 2026年面向专业投资者公开发行永续次级债券(第六期)募集说明书",
          queue_status: "PENDING", queue_reason: "STOPPED_AFTER_SYSTEM_FAILURE",
          context_admission: "INPUT_EXCEEDS_CONTEXT", execution_admission: "AWAITING_FULL_BODY_CHUNKING" },
        { article_id: "EASTMONEY:AN202610151830512764", symbol: "HK.00682", title: "年报 2025/2026",
          queue_status: "PENDING", queue_reason: "STOPPED_AFTER_SYSTEM_FAILURE",
          context_admission: "INPUT_FITS", execution_admission: "DIRECT_SINGLE_REQUEST" },
        { article_id: "EASTMONEY:AN202610151830536700", symbol: "HK.00411", title: "2026年报",
          queue_status: "PENDING", queue_reason: "STOPPED_AFTER_SYSTEM_FAILURE",
          context_admission: "INPUT_EXCEEDS_CONTEXT", execution_admission: "AWAITING_FULL_BODY_CHUNKING" }
      ],
      gaps: [{ code: "CAPTURE_TRANSPORT_NOT_BOUND", count: 1, detail: "正文页数超过采集上限。" }],
      system_stop: { failure_code: "PREFILL_MEMORY_EXCEEDED", queue_action: "STOPPED_NO_AUTOMATIC_RETRY" },
      incremental: null, incremental_runs: [], job: null,
      safety: { RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false }
    };
    const accepted = { job_id: "a".repeat(32), target_date: "20261016", requested_target_date: "20261016",
      step: "QUEUED", status_url: "/api/v4/manager-workbench/announcement-flash?target_date=20261016" };
    const calls: { url: string; method: string; body: string | null }[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = String(input); const method = init.method || "GET";
      calls.push({ url, method, body: typeof init.body === "string" ? init.body : null });
      if (url.includes("/days/20261016/recommendations/")) return response(envelope(day));
      if (url.includes("/announcement-flash/update")) return response(envelope(accepted, "QUEUED"), 202);
      if (url.includes("/announcement-flash")) return response(envelope(announcement, "PARTIAL"));
      throw new Error("unexpected request " + url);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(Workbench);
    await waitFor(() => expect(calls.some(call => call.url.includes("/recommendations/"))).toBe(true));
    expect(calls.some(call => call.url.includes("/announcement-flash"))).toBe(false);

    await fireEvent.click(screen.getByRole("tab", { name: "公告选股" }));
    expect(await screen.findByText("公告披露订单金额同比增长，构成正向候选。")).toBeTruthy();
    expect(screen.getByText("HK.09963")).toBeTruthy();
    expect(screen.getByText("2026-10-15")).toBeTruthy();
    expect(screen.getByText("20", { selector: "strong" })).toBeTruthy();
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(21);
    expect(screen.getByText("CANNOT_CONFIRM")).toBeTruthy();
    expect(screen.getAllByText("MODEL_CANDIDATE_UNREVIEWED").length).toBeGreaterThan(0);
    expect(calls.filter(call => call.method === "POST")).toHaveLength(0);

    await fireEvent.click(screen.getByText(/冻结结果处理明细：失败 18、未运行 5、正文缺口 1/));
    expect(screen.getAllByText("正文超长，待完整分块", { selector: "strong" })).toHaveLength(3);
    expect(screen.getAllByText("系统停队后尚未运行", { selector: "strong" })).toHaveLength(2);
    expect(screen.getAllByText("队列原因：STOPPED_AFTER_SYSTEM_FAILURE", { selector: "small" })).toHaveLength(5);
    expect(screen.getByText(/PREFILL_MEMORY_EXCEEDED/)).toBeTruthy();
    const pendingRowFor = (symbol: string, title: string) => screen.getByText((_, element) =>
      element?.tagName === "LI" && element.textContent?.includes(symbol) === true
      && element.textContent.includes(title));
    for (const [symbol, title] of [
      ["HK.01903", "2026 年报"], ["HK.03908", "海外监管公告"], ["HK.00411", "2026年报"]
    ]) {
      const row = pendingRowFor(symbol, title);
      expect(within(row).getByText("正文超长，待完整分块", { selector: "strong" })).toBeTruthy();
    }
    for (const [symbol, title] of [
      ["HK.00411", "2026年环境"], ["HK.00682", "年报 2025/2026"]
    ]) {
      const row = pendingRowFor(symbol, title);
      expect(within(row).getByText("系统停队后尚未运行", { selector: "strong" })).toBeTruthy();
    }

    await fireEvent.click(screen.getByRole("button", { name: "采集新增公告并增量选股" }));
    await waitFor(() => expect(calls.some(call => call.url.includes("/announcement-flash/update") && call.method === "POST")).toBe(true));
    const post = calls.find(call => call.url.includes("/announcement-flash/update"));
    expect(post?.body).toBe(JSON.stringify({ target_date: "20261016" }));
    expect(calls.filter(call => call.method === "POST")).toHaveLength(1);
  });
});
