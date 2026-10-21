/// <reference types="node" />
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/vue";
import AnnouncementCandidates from "../AnnouncementCandidates.vue";
import Workbench from "../Workbench.vue";

function envelope<T>(data: T, state = "READY"): Record<string, unknown> {
  return { schema_version: "v4.manager_workbench.v1", state, data, gaps: [],
    RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false };
}
function response(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}
function captureOrigin(ref: string, productSha: string) {
  return { role: "CAPTURE_WINDOW_PRODUCT_ROW", source_ref: ref, source_product_sha256: productSha,
    row_fingerprint_sha256: "f".repeat(64) };
}
function announcementArticle(articleId: string, title: string, publicationDate: string, origin: ReturnType<typeof captureOrigin>) {
  return { article_id: articleId, title, publication_date: publicationDate, symbol: "HK.00001", name: "Company",
    disposition: "SELECTED_EVENT", direction: "POSITIVE", reason: `${title}复核理由`, impact: [],
    body_sha256: "a".repeat(64), source_sha256: "b".repeat(64), source_origins: [origin],
    review_status: "MODEL_CANDIDATE_UNREVIEWED", reuse_status: null, membership_status: "IN" };
}
function announcementResult(stocks: unknown[], captureSha: string) {
  return {
    state: "PARTIAL", source_date: "2026-10-15", target_trade_date: "20261016",
    updated_at: "2026-10-17T18:35:19+08:00", review_status: "MODEL_CANDIDATE_UNREVIEWED",
    counts: { displayed_stocks: stocks.length, model_succeeded: 1, failed: 0, pending: 0, body_gaps: 0 },
    stocks, failures: [], pending: [], gaps: [],
    incremental: { state: "PARTIAL", target_trade_date: "20261016", updated_at: "2026-10-17T18:35:19+08:00",
      counts: { new_candidate_stocks: 1 }, failures: [], pending: [], gaps: [],
      provenance: { capture_product_sha256: captureSha,
        current_capture_bindings: { "NEWS:CURRENT": {}, "NEWS:OLD_SAME_STOCK": {}, "NEWS:OLD_GROUP": {} } } },
    safety: { RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false }
  };
}

describe("announcement candidate workbench", () => {
  beforeEach(() => { window.history.replaceState(null, "", "?date=20261016"); });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("reads candidates only after opening the panel and starts capture only on explicit click", async () => {
    const day = { snapshot: null, stocks: [], counts: null,
      pagination: { total: 0, offset: 0, limit: 50 }, versions: [] };
    const stocks = Array.from({ length: 20 }, (_, index) => {
      const isFirst = index === 0;
      const symbol = isFirst ? "HK.00001" : `HK.${10000 + index}`;
      const name = isFirst ? "高途" : `候选${index + 1}`;
      const reason = isFirst ? "公告披露订单金额同比增长，构成正向候选。" : `候选公告${index + 1}的复核理由。`;
      return {
        symbol, name, reasons: [isFirst ? "订单规模增长" : reason],
        review_status: "MODEL_CANDIDATE_UNREVIEWED", reuse_status: null, membership_status: "IN",
        articles: [{ article_id: isFirst ? "EASTMONEY:AN1" : `EASTMONEY:TEST${index + 1}`,
          title: isFirst ? "高途公告" : `候选公告${index + 1}`, publication_date: "2026-10-15",
          symbol, name, disposition: "SELECTED_EVENT", direction: "POSITIVE",
          selection_basis: isFirst ? "公告明确新增订单" : "公告披露事项",
          reason, impact: isFirst ? ["订单金额提升"] : [],
          body_sha256: "a".repeat(64), source_sha256: "b".repeat(64), source_origins: [],
          review_status: "MODEL_CANDIDATE_UNREVIEWED", reuse_status: null, membership_status: "IN" }]
      };
    });
    const announcement = {
      state: "PARTIAL", source_date: "2026-10-15", target_trade_date: "CANNOT_CONFIRM",
      updated_at: "2026-10-16T01:00:00Z", review_status: "MODEL_CANDIDATE_UNREVIEWED",
      counts: { source_catalogue_articles: 392, model_succeeded: 367, selected_model_articles: 21,
        model_candidate_stocks: 19, reused_reviewed_stocks: 1, displayed_stocks: 15,
        failed: 18, pending: 5, body_gaps: 1, membership_eligible_stocks: 15,
        membership_excluded_stocks: 5, membership_unknown_stocks: 0 },
      membership: { status: "VERIFIED", target_date: "20261016", cutoff: "2026-10-16T13:02:00+08:00",
        market: "HK_CONNECT", owner: "v35_dispatcher.research_panel_daily_hk", authority_sha256: "e".repeat(64),
        authority_version: "v1", effective_from: "20261001", effective_to: "20261031",
        available_at: "2026-10-12T19:58:59.501065+08:00", member_count: 698 },
      membership_excluded_stocks: ["09963", "08637", "01319", "01799", "02290"].map(code => ({
        symbol: `HK.${code}`, name: `范围外${code}`, reasons: [], articles: [],
        review_status: "NOT_MODEL_ADMITTED", reuse_status: null, membership_status: "OUT",
        membership_reason: "NOT_IN_HK_CONNECT_UNIVERSE_AT_TARGET_DATE"
      })),
      membership_unknown_stocks: [], membership_excluded_articles: [], membership_unknown_articles: [],
      stocks: stocks.slice(0, 15),
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
    expect(screen.getByText("HK.00001")).toBeTruthy();
    expect(screen.getByText("2026-10-15")).toBeTruthy();
    expect(screen.getByText("15", { selector: "strong" })).toBeTruthy();
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(16);
    expect(screen.getByText("目标日港股通资格：权威已核验")).toBeTruthy();
    expect(screen.getByText("展示 IN 15 只 · OUT 5 只 · UNKNOWN 0 只")).toBeTruthy();
    expect(screen.getByText((_, element) => element?.tagName === "SPAN"
      && element.textContent?.includes("冻结基线目标港股日：CANNOT_CONFIRM") === true)).toBeTruthy();
    expect(screen.queryByText("HK.09963")).toBeNull();
    expect(screen.getByText("CANNOT_CONFIRM")).toBeTruthy();
    expect(screen.getAllByText("MODEL_CANDIDATE_UNREVIEWED").length).toBeGreaterThan(0);
    expect(calls.find(call => call.method === "GET" && call.url.includes("/announcement-flash"))?.url)
      .toBe("/api/v4/manager-workbench/announcement-flash");
    expect(calls.filter(call => call.method === "POST")).toHaveLength(0);

    await fireEvent.click(screen.getByText(/港股通范围外与资格未知：股票 5 \/ 0，文章 0 \/ 0/));
    expect(screen.getByText((_, element) => element?.tagName === "LI"
      && element.textContent?.includes("HK.09963") === true)).toBeTruthy();

    await fireEvent.click(screen.getByText(/冻结结果处理明细：失败文章 18、正文分块失败 0、其他保留失败记录 0、待处理文章 5、正文分块待处理 0、正文分块结果无法确认 0、长文综合待处理 0、正文缺口 1/));
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

    await fireEvent.click(screen.getByRole("button", { name: "检查新增公告并预处理" }));
    await waitFor(() => expect(calls.some(call => call.url.includes("/announcement-flash/update") && call.method === "POST")).toBe(true));
    const post = calls.find(call => call.url.includes("/announcement-flash/update"));
    expect(post?.body).toBe(JSON.stringify({ target_date: "20261016" }));
    expect(calls.filter(call => call.method === "POST")).toHaveLength(1);
  });

  it("sorts the exact latest capture ahead of older notices and keeps publication dates visible", async () => {
    const captureSha = "c".repeat(64);
    const oldSha = "d".repeat(64);
    const current = announcementArticle("NEWS:CURRENT", "Captured in latest batch", "2026-10-14",
      captureOrigin("capture-current.json#1", captureSha));
    const olderSameStock = announcementArticle("NEWS:OLD_SAME_STOCK", "Older capture, newer publication date", "2026-10-16",
      captureOrigin("capture-old.json#1", oldSha));
    const olderGroup = { symbol: "HK.00002", name: "Older Company", reasons: ["Older evidence"],
      review_status: "MODEL_CANDIDATE_UNREVIEWED", reuse_status: null, membership_status: "IN",
      articles: [{ ...announcementArticle("NEWS:OLD_GROUP", "Older stock notice", "2026-10-16",
        captureOrigin("capture-old.json#2", oldSha)), symbol: "HK.00002", name: "Older Company" }] };
    const currentGroup = { symbol: "HK.00001", name: "Company", reasons: [current.reason, olderSameStock.reason],
      review_status: "MODEL_CANDIDATE_UNREVIEWED", reuse_status: null, membership_status: "IN",
      articles: [olderSameStock, current] };
    const result = announcementResult([olderGroup, currentGroup], captureSha);
    const calls: { url: string; method: string }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      calls.push({ url: String(input), method: init.method || "GET" });
      return response(envelope(result, "PARTIAL"));
    }));

    render(AnnouncementCandidates, { props: { targetDate: "20261016" } });
    const table = await screen.findByRole("table");
    const rows = Array.from(table.querySelectorAll("tbody tr"));
    expect(rows.map(row => row.querySelector(".mwb-symbol")?.textContent)).toEqual(["HK.00001", "HK.00002"]);
    expect(Array.from(rows[0].querySelectorAll(".mwb-announcement-article > strong")).map(node => node.textContent))
      .toEqual(["Captured in latest batch", "Older capture, newer publication date"]);
    expect(rows[0].textContent).toContain("公告日 2026-10-14");
    expect(table.querySelectorAll(".mwb-announcement-article .mwb-announcement-current-capture")).toHaveLength(1);
    expect(calls.map(call => call.url)).toEqual(["/api/v4/manager-workbench/announcement-flash"]);
    expect(calls.every(call => call.method === "GET")).toBe(true);
    expect(screen.getByText("研究候选，只供人工复核；不进入正式计划或 BUY 门禁，也不发送订单。")).toBeTruthy();
  });

  it("keeps history selection tab-local and refreshes only the latest view on focus or day change", async () => {
    const captureSha = "e".repeat(64);
    const latest = announcementResult([], captureSha);
    const history = { ...announcementResult([], "f".repeat(64)), source_date: "2026-10-14", target_trade_date: "20261015" };
    const calls: { url: string; method: string }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = String(input);
      calls.push({ url, method: init.method || "GET" });
      return response(envelope(url.includes("target_date=20261015") ? history : latest, "PARTIAL"));
    }));

    const { rerender } = render(AnnouncementCandidates, { props: { targetDate: "20261016" } });
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0].url).toBe("/api/v4/manager-workbench/announcement-flash");
    window.dispatchEvent(new Event("focus"));
    expect(calls).toHaveLength(2);
    expect(calls[1].url).toBe("/api/v4/manager-workbench/announcement-flash");

    await fireEvent.update(screen.getByLabelText("历史目标港股日"), "2026-10-15");
    await fireEvent.click(screen.getByRole("button", { name: "按日期查看历史" }));
    await waitFor(() => expect(calls).toHaveLength(3));
    expect(calls[2].url).toBe("/api/v4/manager-workbench/announcement-flash?target_date=20261015");
    expect(window.location.search).toBe("?date=20261016");
    window.dispatchEvent(new Event("focus"));
    expect(calls).toHaveLength(3);

    await fireEvent.click(screen.getByRole("button", { name: "查看最新结果" }));
    await waitFor(() => expect(calls).toHaveLength(4));
    expect(calls[3].url).toBe("/api/v4/manager-workbench/announcement-flash");
    await rerender({ targetDate: "20261017" });
    await waitFor(() => expect(calls).toHaveLength(5));
    expect(calls[4].url).toBe("/api/v4/manager-workbench/announcement-flash");
    expect(calls.every(call => call.method === "GET")).toBe(true);
  });

  it("shows validated partial candidates with separate article, part, and binding statuses", async () => {
    const day = { snapshot: null, stocks: [], counts: null,
      pagination: { total: 0, offset: 0, limit: 50 }, versions: [] };
    const stocks = Array.from({ length: 11 }, (_, index) => ({
      symbol: `HK.${10015 + index}`, name: `本批候选${index + 1}`, reasons: ["已校验的公告候选。"],
      review_status: "MODEL_CANDIDATE_UNREVIEWED", reuse_status: null, membership_status: "IN",
      articles: [{ article_id: `EASTMONEY:CURRENT${index + 1}`, title: `本批公告${index + 1}`,
        publication_date: "2026-10-16", symbol: `HK.${10015 + index}`, name: `本批候选${index + 1}`,
        disposition: "SELECTED_EVENT", direction: "POSITIVE", reason: "已校验的公告候选。",
        impact: [], body_sha256: "a".repeat(64), source_sha256: "b".repeat(64), source_origins: [],
        review_status: "MODEL_CANDIDATE_UNREVIEWED", reuse_status: null, membership_status: "IN" }]
    }));
    const failures = [
      ...Array.from({ length: 8 }, (_, index) => ({ article_id: `EASTMONEY:FAIL${index}`,
        symbol: `HK.${10000 + index}`, title: `失败公告${index + 1}`, failure_code: "VALIDATOR_ERROR" })),
      ...Array.from({ length: 9 }, (_, index) => ({ article_id: `EASTMONEY:PRIOR${index}`,
        symbol: "HK.10000", title: `保留历史失败${index + 1}`, failure_code: "ANNOUNCEMENT_EVIDENCE_INCOMPLETE" })),
      ...Array.from({ length: 17 }, (_, index) => ({ article_id: "EASTMONEY:LONG",
        symbol: "HK.10098", title: "长文", part_index: index + 1, part_count: 22,
        failure_code: "PART_FIXED_FIELDS_MUST_BE_EMPTY", stage: "validator" }))
    ];
    const pending = [
      { article_id: "EASTMONEY:LONG", symbol: "HK.10098", title: "长文", part_index: 1,
        part_count: 22, queue_status: "FAILED", queue_reason: "REPAIR_RESULT_ORCHESTRATION_CANNOT_CONFIRM",
        repair_status: "REPAIR_SUCCESS_ORCHESTRATION_UNVERIFIED" },
      ...Array.from({ length: 16 }, (_, index) => ({ article_id: "EASTMONEY:LONG",
        symbol: "HK.10098", title: "长文", part_index: index + 2, part_count: 22,
        queue_reason: "LONG_BODY_PART_REPAIR_GATED" })),
      ...Array.from({ length: 2 }, (_, index) => ({ article_id: `EASTMONEY:LONG_SYNTH_${index}`,
        symbol: "HK.10098", title: "长文综合", queue_reason: "SAVED_SYNTHESIS_IDENTITY_CONFLICT" }))
    ];
    const stop = { failure_code: "INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT",
      queue_action: "SAVED_RESULTS_ONLY_NO_RETRY" };
    const result = {
      state: "PARTIAL", source_date: "2026-10-16", target_trade_date: "20261016",
      updated_at: "2026-10-16T21:20:00+08:00", review_status: "MODEL_CANDIDATE_UNREVIEWED",
      counts: { source_catalogue_articles: 354, model_succeeded: 129, selected_model_articles: 11,
        displayed_stocks: 26, failed: 8, pending: 0, body_gaps: 0,
        model_failed_articles: 8, model_pending_articles: 0, long_body_part_failed: 17,
        long_body_part_pending: 16, long_body_part_cannot_confirm: 1,
        long_body_synthesis_pending: 2 },
      membership: { status: "VERIFIED", target_date: "20261016", cutoff: "2026-10-16T14:57:00+08:00",
        market: "HK_CONNECT", owner: "v35_dispatcher.research_panel_daily_hk", authority_sha256: "c".repeat(64),
        authority_version: "v1", effective_from: "20261001", effective_to: "20261031", member_count: 698 },
      membership_excluded_stocks: [], membership_unknown_stocks: [], membership_excluded_articles: [],
      membership_unknown_articles: [], stocks, failures, pending, gaps: [], system_stop: stop,
      incremental: { state: "PARTIAL", job_id: "9".repeat(32), target_trade_date: "20261016",
        updated_at: "2026-10-16T21:20:00+08:00", counts: { failed: 8, queue_pending: 0, body_gaps: 0,
          new_candidate_stocks: 11, queue: { new_enqueued: 0, incremental_succeeded_matched: 129,
            long_body_parts_failed: 17, long_body_parts_pending: 16, long_body_parts_cannot_confirm: 1,
            long_body_synthesis_pending: 2 } },
        failures, pending, gaps: [], system_stop: stop },
      incremental_runs: [], job: { job_id: "9".repeat(32), target_date: "20261016", state: "FAILED",
        step: "FLASH_SELECTION", failure_code: "INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT",
        completed_count: 138, total_count: 171 },
      safety: { RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false }
    };
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input); calls.push(url);
      if (url.includes("/days/20261016/recommendations/")) return response(envelope(day));
      if (url.includes("/announcement-flash")) return response(envelope(result, "PARTIAL"));
      throw new Error("unexpected request " + url);
    }));

    render(Workbench);
    await fireEvent.click(await screen.findByRole("tab", { name: "公告选股" }));
    expect(await screen.findByText("本批候选1")).toBeTruthy();
    expect(screen.getByText("129", { selector: "strong" })).toBeTruthy();
    expect(screen.getByText(/最近增量结果：部分完成/)).toBeTruthy();
    expect(screen.getAllByText(/INTERNAL_QUEUE_PAYLOAD_IDEMPOTENCY_CONFLICT/).length).toBeGreaterThan(0);

    const frozenDetailsSummary = screen.getByText(/冻结结果处理明细：失败文章 8、正文分块失败 17、其他保留失败记录 9、待处理文章 0、正文分块待处理 16、正文分块结果无法确认 1、长文综合待处理 2/);
    await fireEvent.click(frozenDetailsSummary);
    const frozenDetails = frozenDetailsSummary.closest("details");
    expect(frozenDetails).not.toBeNull();
    const partRows = within(frozenDetails as HTMLElement).getAllByRole("listitem")
      .filter(item => /正文分块 \d+\/22/.test(item.textContent || ""));
    expect(partRows).toHaveLength(34);
    expect(screen.getAllByText(/REPAIR_RESULT_ORCHESTRATION_CANNOT_CONFIRM/).length).toBeGreaterThan(0);
    expect(calls.every(url => !url.includes("/announcement-flash/update"))).toBe(true);
  });

  it("submits only the hash-bound frozen resume request after an explicit canary click", async () => {
    const eligibility = {
      schema: "v4.manager_workbench.announcement_flash_resume.v1", status: "ELIGIBLE", eligible: true,
      mode: "INITIAL_CANARY", source_job_id: "a".repeat(32), target_date: "20261016",
      source_input_sha256: "1".repeat(64), source_progress_sha256: "2".repeat(64),
      source_queue_state_sha256: "3".repeat(64), resume_action: "CANARY",
      max_model_calls: 1, canary_passed: false,
      transport_recovery: { schema: "v4.manager_workbench.announcement_flash_transport_recovery.v1" },
      queue_status_counts: { SUCCEEDED: 24, FAILED: 15, PENDING: 5, RUNNING: 1 }, orphan_count: 1,
      recoverable_orphan_count: 1,
    };
    const data = {
      state: "PARTIAL", source_date: "2026-10-16", target_trade_date: "20261016",
      updated_at: "2026-10-18T01:00:00Z", review_status: "MODEL_CANDIDATE_UNREVIEWED",
      counts: { displayed_stocks: 0, model_succeeded: 24, failed: 15, pending: 5, body_gaps: 0,
        membership_eligible_stocks: 0, membership_excluded_stocks: 0, membership_unknown_stocks: 0 },
      stocks: [], failures: [], pending: [], gaps: [], incremental: null, incremental_runs: [],
      membership: { status: "CANNOT_CONFIRM", target_date: "20261016" }, job: null,
      resume: eligibility,
      safety: { RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false },
    };
    const accepted = { job_id: "b".repeat(32), source_job_id: eligibility.source_job_id,
      target_date: "20261016", resume_action: "CANARY", step: "QUEUED",
      status_url: "/api/v4/manager-workbench/announcement-flash?target_date=20261016" };
    const calls: { url: string; method: string; body: string | null }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = String(input); const method = init.method || "GET";
      calls.push({ url, method, body: typeof init.body === "string" ? init.body : null });
      if (url.includes("/announcement-flash/resume")) return response(envelope(accepted, "QUEUED"), 202);
      if (url.includes("/announcement-flash")) return response(envelope(data, "PARTIAL"));
      throw new Error("unexpected request " + url);
    }));

    render(AnnouncementCandidates, { props: { targetDate: "20261016" } });
    expect(await screen.findByText(
      "首次续跑仅验证一个绑定到原失败任务的公告任务；成功并通过保存结果复核后，才开放继续入口。",
    )).toBeTruthy();
    const button = await screen.findByRole("button", { name: "运行失败公告任务 canary（1 个模型请求）" });
    expect(calls.filter(call => call.method === "POST")).toHaveLength(0);
    await fireEvent.click(button);
    await waitFor(() => expect(calls.some(call => call.url.endsWith("/announcement-flash/resume")
      && call.method === "POST")).toBe(true));
    const post = calls.find(call => call.url.endsWith("/announcement-flash/resume"));
    expect(post?.body).toBe(JSON.stringify({ target_date: "20261016", source_job_id: eligibility.source_job_id,
      source_input_sha256: eligibility.source_input_sha256,
      source_progress_sha256: eligibility.source_progress_sha256,
      source_queue_state_sha256: eligibility.source_queue_state_sha256,
      resume_action: "CANARY" }));
    expect(calls.filter(call => call.method === "POST")).toHaveLength(1);
    expect(calls.some(call => call.url.endsWith("/announcement-flash/update"))).toBe(false);
    expect((await screen.findByRole("status")).textContent).toMatch(/已提交公告续跑/);
  });
});

describe("daily preprocessing and per-article delivery", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
  function preparedWithHistoricalDelivery() {
    const currentJob = "a".repeat(32), oldJob = "b".repeat(32);
    return { ...announcementResult([], "c".repeat(64)),
      job: { job_id: currentJob, target_date: "20261016", state: "PARTIAL", step: "DONE" },
      preprocessing: { job_id: currentJob, target_date: "20261016", accounting_closed: true,
        counts: {}, rules_explanation: [], first_article_id: "FIRST",
        execution_manifest: [{ article_id: "FIRST", body_sha256: "d".repeat(64) },
          { article_id: "SECOND", body_sha256: "e".repeat(64) }] },
      preprocessing_binding: { sha256: "1".repeat(64) },
      daily_delivery: { job_id: oldJob, target_trade_date: "20261016",
        preprocessing_report_sha256: "2".repeat(64), state: "PARTIAL", counts: { SUCCEEDED: 1, DEFERRED: 1 },
        articles: [
          { article_id: "FIRST", body_sha256: "d".repeat(64), state: "SUCCEEDED", title: "旧任务已保存分析" },
          { article_id: "SECOND", body_sha256: "e".repeat(64), state: "DEFERRED" }
        ] },
      daily_delivery_binding: { job_id: oldJob, sha256: "3".repeat(64) } };
  }

  function mockPreparedExecution(value: ReturnType<typeof preparedWithHistoricalDelivery>) {
    const posts: { url: string; body: unknown }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      if (init.method === "POST") {
        posts.push({ url: String(input), body: JSON.parse(String(init.body)) });
        return response(envelope({ job_id: value.job.job_id }), 202);
      }
      return response(envelope(value));
    }));
    return posts;
  }

  it("allows FIRST for the new prepared job while keeping the old job's results readable", async () => {
    const value = preparedWithHistoricalDelivery();
    const posts = mockPreparedExecution(value);
    render(AnnouncementCandidates, { props: { targetDate: "20261016" } });
    const first = await screen.findByRole("button", { name: "运行首篇新增公告" });
    expect(screen.getByText("旧任务已保存分析")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "首篇已核验，继续其余未尝试部分" })).toBeNull();
    expect(posts).toHaveLength(0);
    await fireEvent.click(first);
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toEqual({
      url: `/api/v4/manager-workbench/announcement-flash/${value.job.job_id}/execute-preprocessed`,
      body: { phase: "FIRST", report_sha256: value.preprocessing_binding.sha256, first_delivery_sha256: null }
    });
    expect(screen.getByText("旧任务已保存分析")).toBeTruthy();
  });

  it.skipIf(!process.env.ANNOUNCEMENT_JOB_BINDING_RESPONSE)("binds a frozen real API readback to its new prepared job", async () => {
    const value = JSON.parse(await (await import("node:fs/promises")).readFile(
      process.env.ANNOUNCEMENT_JOB_BINDING_RESPONSE!, "utf8"));
    expect(value.data.job.job_id).toBe(value.data.preprocessing.job_id);
    expect(value.data.daily_delivery.job_id).not.toBe(value.data.job.job_id);
    const posts = mockPreparedExecution(value.data);
    render(AnnouncementCandidates, { props: { targetDate: value.data.job.target_date } });
    const first = await screen.findByRole("button", { name: "运行首篇新增公告" });
    expect(screen.getByRole("region", { name: "逐篇交付与未完成" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "首篇已核验，继续其余未尝试部分" })).toBeNull();
    await fireEvent.click(first);
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toEqual({
      url: `/api/v4/manager-workbench/announcement-flash/${value.data.job.job_id}/execute-preprocessed`,
      body: { phase: "FIRST", report_sha256: value.data.preprocessing_binding.sha256, first_delivery_sha256: null }
    });
  });

  it.each(["SUCCEEDED", "FAILED", "PENDING"])("never repeats FIRST for a same-job %s delivery", async state => {
    const value = preparedWithHistoricalDelivery();
    value.daily_delivery.job_id = value.job.job_id;
    value.daily_delivery.preprocessing_report_sha256 = value.preprocessing_binding.sha256;
    value.daily_delivery_binding.job_id = value.job.job_id;
    value.daily_delivery.articles[0].state = state;
    const posts = mockPreparedExecution(value);
    render(AnnouncementCandidates, { props: { targetDate: "20261016" } });
    await screen.findByRole("region", { name: "预处理完成报告" });
    expect(screen.queryByRole("button", { name: "运行首篇新增公告" })).toBeNull();
    const remaining = screen.queryByRole("button", { name: "首篇已核验，继续其余未尝试部分" });
    if (state === "SUCCEEDED") {
      expect(remaining).toBeTruthy();
      await fireEvent.click(remaining!);
      await waitFor(() => expect(posts).toHaveLength(1));
      expect(posts[0]).toEqual({
        url: `/api/v4/manager-workbench/announcement-flash/${value.job.job_id}/execute-preprocessed`,
        body: { phase: "CONTINUE", report_sha256: value.preprocessing_binding.sha256,
          first_delivery_sha256: value.daily_delivery_binding.sha256 }
      });
    } else {
      expect(remaining).toBeNull();
      expect(posts).toHaveLength(0);
    }
  });

  it.each(["report_job", "report_sha", "delivery_job", "delivery_binding", "delivery_report", "report_date"])(
    "keeps execution closed when %s identity is unverified", async kind => {
      const value = preparedWithHistoricalDelivery();
      if (kind === "report_job") value.preprocessing.job_id = "f".repeat(32);
      if (kind === "report_sha") value.preprocessing_binding.sha256 = "";
      if (kind === "delivery_job") value.daily_delivery.job_id = "";
      if (kind === "delivery_binding") value.daily_delivery_binding.job_id = "f".repeat(32);
      if (kind === "report_date") value.preprocessing.target_date = "20261015";
      if (kind === "delivery_report") {
        value.daily_delivery.job_id = value.job.job_id;
        value.daily_delivery_binding.job_id = value.job.job_id;
      }
      const posts = mockPreparedExecution(value);
      render(AnnouncementCandidates, { props: { targetDate: "20261016" } });
      await screen.findByRole("region", { name: "预处理完成报告" });
      expect(screen.queryByRole("button", { name: "运行首篇新增公告" })).toBeNull();
      expect(screen.queryByRole("button", { name: "首篇已核验，继续其余未尝试部分" })).toBeNull();
      expect(posts).toHaveLength(0);
    });

  it("renders the actual offline Python API chain with all-model denominator, bounded subset, prior and current results", async () => {
    const path = process.env.ANNOUNCEMENT_DAILY_OFFLINE_RESPONSE;
    const value = path ? JSON.parse(await (await import("node:fs/promises")).readFile(path, "utf8"))
      : envelope({ ...announcementResult([], "c".repeat(64)),
        preprocessing: { source: "EASTMONEY_HK", cutoff: "2026-10-20T13:00:00+08:00",
          counts: { raw_rows: 14, exact_duplicates: 1, unique_articles: 13,
            primary_dispositions: { RULE_ARCHIVED: 1, MODEL_ORDINARY: 11, SOURCE_GAP: 1 },
            model_required_articles: 11, model_ordinary_articles: 11, model_long_articles: 0,
            reader_parts: 0, syntheses: 0, expected_model_requests: 11, bounded_articles: 8,
            bounded_model_requests: 8, deferred_model_articles: 3, workload_unknown_articles: 1 },
          rules_explanation: ["完整正文和来源核对后分流，历史成功不重跑。"], first_article_id: "FIRST", execution_manifest: [] },
        daily_delivery: { state: "PARTIAL", counts: { SUCCEEDED: 1 }, articles: [
          { article_id: "FIRST", state: "SUCCEEDED", disposition: "NOT_SELECTED", title: "首篇完整公告", source_coverage: "COMPLETE_ARTICLE" },
          { article_id: "SECOND", state: "PENDING", title: "另一篇待深读", parts_complete: 1, parts_total: 2 }
        ] } });
    const fetcher = vi.fn(async () => response(value));
    vi.stubGlobal("fetch", fetcher);
    render(AnnouncementCandidates, { props: { targetDate: "20261016" } });
    const report = await screen.findByRole("region", { name: "预处理完成报告" });
    expect(report.textContent).toContain(`原始 ${value.data.preprocessing.counts.raw_rows} 条`);
    expect(report.textContent).toContain(`应进入模型 ${value.data.preprocessing.counts.model_required_articles} 篇`);
    expect(report.textContent).toContain(`测试子集 ${value.data.preprocessing.counts.bounded_articles} 篇`);
    const delivered = screen.getByRole("region", { name: "逐篇交付与未完成" });
    expect(delivered.textContent).toContain("完整分析已保存");
    expect(delivered.textContent).toContain("未入选");
    expect(fetcher).toHaveBeenCalledTimes(1); // Opening/readback never initiates model execution.
    const domPath = process.env.ANNOUNCEMENT_DAILY_OFFLINE_DOM;
    if (domPath) await (await import("node:fs/promises")).writeFile(domPath, document.body.innerHTML);
  });

  it("shows the truthful stopping state and retains the current results", async () => {
    const payload = { ...announcementResult([], "c".repeat(64)), job: {
      job_id: "a".repeat(32), target_date: "20261016", state: "STOP_REQUESTED", step: "ARTICLE_DELIVERED",
      completed_count: 1, total_count: 2 } };
    vi.stubGlobal("fetch", vi.fn(async () => response(envelope(payload))));
    render(AnnouncementCandidates, { props: { targetDate: "20261016" } });
    const button = await screen.findByRole("button", { name: "停止中：在途结果保存后结束" });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/增量任务：停止中（等待在途结果保存）/)).toBeTruthy();
  });
});

describe("saved whole-article analysis reading", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
  function savedAnalysisResponse() {
    const source = "2".repeat(64), body = "3".repeat(64), deliverySha = "4".repeat(64);
    const reader = { disposition: "NOT_SELECTED", direction: "NEUTRAL", selection_basis: "NOT_SELECTED",
      evidence_sufficiency: "VERIFIED_EXISTING_FACTS", reason: "首篇完整保存的判断理由。",
      facts: Array.from({ length: 4 }, (_, i) => ({ claim: `事实${i}`, quote: ` 原文事实${i}。\n`,
        locator: `article_body[codepoint:${i}:${i + 1}]` })),
      changes: [], impact: [], confirmation_conditions: [], counter_evidence: [],
      risk_notes: ["已披露风险一。", "已披露风险二。", "输入元数据：pit_status=CANNOT_CONFIRM；OFFICIAL_FIRST_PUBLICATION_TIME_NOT_BOUND"],
      source_sha256: source, body_sha256: body };
    const data = { ...announcementResult([], "c".repeat(64)),
      daily_delivery: { state: "PARTIAL", counts: { SUCCEEDED: 1, DEFERRED: 1 }, articles: [
        { article_id: "SAVED", source_sha256: source, body_sha256: body, title: "首篇已保存完整公告",
          state: "SUCCEEDED", reason: reader.reason, disposition: "NOT_SELECTED", source_coverage: "COMPLETE_ARTICLE" },
        { article_id: "DEFERRED", title: "未尝试公告", state: "DEFERRED" }
      ] }, daily_delivery_binding: { sha256: deliverySha },
      daily_analysis: { schema: "v4.manager_workbench.announcement_analysis_projection.v1", delivery_sha256: deliverySha,
        articles: [{ article_id: "SAVED", source_sha256: source, body_sha256: body, result_sha256: "5".repeat(64),
          analysis_state: "AVAILABLE", reader_output: reader }] } };
    return { ...envelope(data), data };
  }

  it("opens the saved full result with every exact quote/locator, risks and PIT without execution", async () => {
    const path = process.env.ANNOUNCEMENT_ANALYSIS_OFFLINE_RESPONSE;
    const value = path ? JSON.parse(await (await import("node:fs/promises")).readFile(path, "utf8")) : savedAnalysisResponse();
    const saved = value.data.daily_analysis.articles.find((a: { analysis_state: string }) => a.analysis_state === "AVAILABLE");
    const reader = saved.reader_output;
    const fetcher = vi.fn(async () => response(value)); vi.stubGlobal("fetch", fetcher);
    render(AnnouncementCandidates, { props: { targetDate: "20261020" } });
    const summary = await screen.findByText("阅读完整分析");
    const details = summary.closest("details")!;
    expect(details.open).toBe(false);
    await fireEvent.click(summary);
    const facts = within(details).getByRole("region", { name: "事实" });
    expect(facts.querySelectorAll("ol > li")).toHaveLength(4);
    expect(Array.from(facts.querySelectorAll("pre")).map(node => node.textContent)).toEqual(reader.facts.map((f: { quote: string }) => f.quote));
    for (const fact of reader.facts) expect(facts.textContent).toContain(fact.locator);
    const risks = within(details).getByRole("region", { name: "风险与数据限制" });
    expect(within(risks).getAllByRole("listitem")).toHaveLength(3);
    for (const note of reader.risk_notes) expect(risks.textContent).toContain(note);
    expect(risks.textContent).toContain("CANNOT_CONFIRM");
    expect(risks.textContent).toContain("OFFICIAL_FIRST_PUBLICATION_TIME_NOT_BOUND");
    for (const label of ["变化", "影响", "确认条件", "反面证据"]) {
      expect(within(details).getByRole("region", { name: label }).textContent).toContain("本次保存分析未提供此项");
    }
    expect(details.textContent).toContain(reader.evidence_sufficiency);
    expect(details.textContent).toContain(saved.result_sha256);
    expect(details.textContent).toContain(value.data.daily_delivery_binding.sha256);
    expect(fetcher).toHaveBeenCalledTimes(1);
    const dom = process.env.ANNOUNCEMENT_ANALYSIS_OFFLINE_DOM;
    if (dom) await (await import("node:fs/promises")).writeFile(dom, document.body.innerHTML);
  });

  it.each(["unavailable", "wrong_delivery"])("keeps success and reason while details are %s", async kind => {
    const value = savedAnalysisResponse();
    if (kind === "wrong_delivery") value.data.daily_analysis.delivery_sha256 = "f".repeat(64);
    else Object.assign(value.data.daily_analysis.articles[0], { analysis_state: "UNAVAILABLE", reader_output: undefined,
      failure_code: "ANALYSIS_RESULT_SHA_CHANGED" });
    const fetcher = vi.fn(async () => response(value)); vi.stubGlobal("fetch", fetcher);
    render(AnnouncementCandidates, { props: { targetDate: "20261020" } });
    expect(await screen.findByText(/完整分析暂不可读/)).toBeTruthy();
    expect(screen.queryByText("阅读完整分析")).toBeNull();
    expect(screen.getByRole("region", { name: "逐篇交付与未完成" }).textContent).toContain("完整分析已保存");
    expect(screen.getByText(/首篇完整保存的判断理由/)).toBeTruthy();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
