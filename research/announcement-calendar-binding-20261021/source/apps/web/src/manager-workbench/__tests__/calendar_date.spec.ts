import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/vue";
import Workbench from "../Workbench.vue";

const newJob = "2ee51b0e18814052b324578fe771e258";
const reportSha = "8b2851c2a1658f03e7b2fb939a32eb0aa3595e0de65b40a1b07130b63f1bbaa9";
function envelope(data: unknown) {
  return { schema_version: "v4.manager_workbench.v1", state: "READY", data, gaps: [],
    RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false };
}
function response(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
}
const day = { snapshot: null, stocks: [], counts: null,
  pagination: { total: 0, offset: 0, limit: 50 }, versions: [{ run_id: "new-day-version", phase: "INTRADAY" }] };
function transport(announcement?: unknown) {
  const calls: { url: string; method: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input), method = init.method || "GET";
    calls.push({ url, method, body: init.body ? JSON.parse(String(init.body)) : null });
    if (method === "GET" && url.includes("/recommendations/")) return response(envelope(day));
    if (method === "GET" && url.includes("/announcement-flash")) return response(announcement);
    if (method === "POST" && url.endsWith(`/${newJob}/execute-preprocessed`)) {
      return response(envelope({ job_id: newJob }), 202);
    }
    throw new Error("Unexpected business request " + method + " " + url);
  }));
  return calls;
}
async function mountedCalendar() {
  const input = screen.getByLabelText("目标港股日") as HTMLInputElement;
  expect(input.tagName).toBe("INPUT");
  expect(input.type).toBe("date");
  expect(input.value).toBe("2026-10-13");
  return input;
}

describe("workbench native target-day calendar", () => {
  beforeEach(() => window.history.replaceState(null, "", "?date=20261013&phase=PREOPEN&run_id=old-day-version"));
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("converts calendar dates to compact request/route dates and releases the prior date's fixed version", async () => {
    const calls = transport(); render(Workbench);
    await waitFor(() => expect(calls).toHaveLength(1));
    const input = await mountedCalendar();
    expect(document.querySelectorAll("#mwb-date")).toHaveLength(1);
    expect(document.querySelector("select#mwb-date")).toBeNull();
    await fireEvent.focus(input);
    expect(calls).toHaveLength(1); // Calendar focus has no legacy date-catalog request.
    await fireEvent.change(input, { target: { value: "2026-10-20" } });
    await waitFor(() => expect(calls).toHaveLength(2));
    const request = new URL(calls[1].url, "http://localhost");
    expect(request.pathname).toContain("/days/20261020/recommendations/");
    expect(request.searchParams.has("run_id")).toBe(false);
    expect(request.searchParams.has("phase")).toBe(false); // Existing date selection reads the new day's latest.
    expect(new URLSearchParams(window.location.search).get("date")).toBe("20261020");
    expect(new URLSearchParams(window.location.search).has("run_id")).toBe(false);
    expect(input.value).toBe("2026-10-20");
    expect(calls.every(call => call.method === "GET")).toBe(true);
  });

  it.each(["", "2026-02-30", "2026-10-20oops"])("does not navigate or request on an empty/invalid calendar value %j", async value => {
    const calls = transport(); render(Workbench);
    await waitFor(() => expect(calls).toHaveLength(1));
    const input = await mountedCalendar();
    await fireEvent.change(input, { target: { value } });
    expect(calls).toHaveLength(1);
    expect(new URLSearchParams(window.location.search).get("date")).toBe("20261013");
    expect(new URLSearchParams(window.location.search).get("run_id")).toBe("old-day-version");
    expect(input.validity.customError).toBe(true);
    await fireEvent.change(input, { target: { value: "2026-10-20" } });
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(input.validity.customError).toBe(false);
  });

  it("retains phase/version selection and historical route readback after a calendar change", async () => {
    const calls = transport(); render(Workbench);
    const input = await mountedCalendar();
    await fireEvent.change(input, { target: { value: "2026-10-20" } });
    await waitFor(() => expect(calls).toHaveLength(2));
    await fireEvent.change(screen.getByLabelText("阶段"), { target: { value: "INTRADAY" } });
    await waitFor(() => expect(calls).toHaveLength(3));
    expect(new URL(calls[2].url, "http://localhost").searchParams.get("phase")).toBe("INTRADAY");
    await screen.findByRole("option", { name: /new-day-version/ });
    await fireEvent.change(screen.getByLabelText("计划版本"), { target: { value: "new-day-version" } });
    await waitFor(() => expect(calls).toHaveLength(4));
    expect(new URL(calls[3].url, "http://localhost").searchParams.get("run_id")).toBe("new-day-version");
    window.history.replaceState(null, "", "?date=20261013&phase=PREOPEN&run_id=old-day-version");
    window.dispatchEvent(new PopStateEvent("popstate"));
    await waitFor(() => expect(calls).toHaveLength(5));
    expect(input.value).toBe("2026-10-13");
    expect(new URL(calls[4].url, "http://localhost").searchParams.get("run_id")).toBe("old-day-version");
    expect(calls.every(call => call.method === "GET")).toBe(true);
  });

  it("passes the selected target date to announcements and keeps FIRST bound to the frozen prepared job", async () => {
    const path = process.env.ANNOUNCEMENT_CALENDAR_RESPONSE;
    const announcement = path ? JSON.parse(await (await import("node:fs/promises")).readFile(path, "utf8"))
      : envelope({ state: "PREPROCESSING_COMPLETE", source_date: "2026-10-20", target_trade_date: "20261020",
        counts: {}, stocks: [], failures: [], pending: [], gaps: [],
        job: { job_id: newJob, target_date: "20261020", state: "PARTIAL", step: "DONE" },
        preprocessing: { job_id: newJob, target_date: "20261020", accounting_closed: true, counts: {},
          rules_explanation: [], first_article_id: "FIRST", execution_manifest: [{ article_id: "FIRST", body_sha256: "d".repeat(64) }] },
        preprocessing_binding: { sha256: reportSha },
        daily_delivery: { job_id: "4523cf36ed8944bfa0fc80d5d979524c", state: "PARTIAL", counts: {}, articles: [] },
        daily_delivery_binding: { job_id: "4523cf36ed8944bfa0fc80d5d979524c", sha256: "3".repeat(64) } });
    const calls = transport(announcement); render(Workbench);
    await fireEvent.change(await mountedCalendar(), { target: { value: "2026-10-20" } });
    await waitFor(() => expect(calls.filter(call => call.url.includes("/days/20261020/"))).toHaveLength(1));
    await fireEvent.click(screen.getByRole("tab", { name: "公告选股" }));
    const first = await screen.findByRole("button", { name: "运行首篇新增公告" });
    expect((screen.getByLabelText("历史目标港股日") as HTMLInputElement).value).toBe("2026-10-20");
    expect(calls.every(call => call.method === "GET")).toBe(true);
    await fireEvent.click(first); // Mocked transport only; no live model request.
    await waitFor(() => expect(calls.filter(call => call.method === "POST")).toHaveLength(1));
    expect(calls.find(call => call.method === "POST")).toEqual({
      url: `/api/v4/manager-workbench/announcement-flash/${newJob}/execute-preprocessed`, method: "POST",
      body: { phase: "FIRST", report_sha256: reportSha, first_delivery_sha256: null }
    });
    expect(calls.some(call => call.url.endsWith("/announcement-flash/update"))).toBe(false);
  });
});
