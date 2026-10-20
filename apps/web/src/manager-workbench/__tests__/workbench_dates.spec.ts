import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/vue";
import Workbench from "../Workbench.vue";
import { SCHEMA_VERSION } from "../types";
import type { Envelope } from "../types";

function response(data: unknown, state = "NOT_RUN"): Response {
  const payload: Envelope<unknown> = {
    schema_version: SCHEMA_VERSION,
    state,
    data,
    gaps: [],
    RESEARCH_ONLY: true,
    production_allowed: false,
    buy_gate_updated: false,
    orders_sent: false
  };
  return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
}

describe("manager workbench saved-date selector", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "?date=20261020&phase=INTRADAY&run_id=old-run&offset=50");
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("loads saved choices on demand and switches the target with a clean read-only route", async () => {
    const calls: { url: URL; method: string }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = new URL(String(input), window.location.origin);
      calls.push({ url, method: init.method || "GET" });
      if (url.pathname === "/api/v1/runs/date-list") {
        return new Response(JSON.stringify({
          dates: ["20261018", "20261018", "invalid"],
          future_target_dates: ["20261021"],
          stage_dates: ["20261019"],
          review_dates: ["bad-date"]
        }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return response(null);
    }));

    render(Workbench);
    await waitFor(() => expect(calls.filter(call => call.url.pathname.includes("/recommendations/")).length).toBe(1));
    expect(calls.some(call => call.url.pathname === "/api/v1/runs/date-list")).toBe(false);

    const selector = screen.getByLabelText("目标港股日") as HTMLSelectElement;
    await fireEvent.focus(selector);
    await screen.findByRole("option", { name: "2026-10-18" });
    expect(Array.from(selector.options).map(option => option.textContent)).toEqual([
      "2026-10-18", "2026-10-19", "2026-10-20", "2026-10-21"
    ]);

    await fireEvent.update(selector, "20261018");
    await waitFor(() => expect(calls.filter(call => call.url.pathname.includes("/recommendations/")).length).toBe(2));
    const switched = calls.filter(call => call.url.pathname.includes("/recommendations/"))[1].url;
    expect(switched.pathname).toContain("/days/20261018/recommendations/");
    expect(switched.searchParams.has("phase")).toBe(false);
    expect(switched.searchParams.has("run_id")).toBe(false);
    expect(switched.searchParams.get("offset")).toBe("0");
    expect(switched.searchParams.get("limit")).toBe("50");
    expect(new URLSearchParams(window.location.search).get("date")).toBe("20261018");
    expect(new URLSearchParams(window.location.search).has("phase")).toBe(false);
    expect(new URLSearchParams(window.location.search).has("run_id")).toBe(false);
    expect(new URLSearchParams(window.location.search).has("offset")).toBe(false);
    expect(calls.every(call => call.method === "GET")).toBe(true);
  });
});
