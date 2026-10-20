import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/vue";
import Workbench from "../Workbench.vue";
import { SCHEMA_VERSION } from "../types";
import type { DayData, Envelope } from "../types";

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

function candidateDay(catalogCandidates?: Record<string, unknown>[]): DayData {
  const singleDay: Record<string, unknown> = {
    state: "PARTIAL",
    source_session: "20261020",
    target_date: "20261013",
    formal_target_eligibility: "CANNOT_CONFIRM",
    rows: [],
    catalog_candidates: catalogCandidates
  };
  return {
    snapshot: {
      context: { market: "HK_CONNECT", target_date: "20261013", phase: "PREOPEN", cutoff: null },
      run_id: "synthetic-run-1", generated_at: "2026-10-13T09:25:00+08:00", lanes: []
    },
    stocks: [],
    counts: { selected: 0, watch: 0, unassessed: null, observation_only: 0, not_selected: null },
    pagination: { total: 0, offset: 0, limit: 50 },
    versions: [],
    us_mapping_summary: {
      display_only: true, plan_run_id: "synthetic-run-1", source_symbol_count: 0,
      source_row_count: 0, relation_row_count: 0, mapped_hk_count: 0,
      source_decision_counts: {}, mixed_source_count: 0,
      coverage: { scope_count: 0, observed_count: 0, assessed_count: 0, unassessed_count: 0 },
      groups: [], factor_summary: { single_day_mapping: singleDay }
    }
  } as unknown as DayData;
}

describe("manager workbench saved-date dropdown", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "?date=20261020&phase=INTRADAY&run_id=old-run");
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("switches to a saved date using compact URL and request dates, clears the old version, and follows browser history", async () => {
    const requests: Array<{ url: URL; method: string }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), window.location.origin);
      requests.push({ url, method: init?.method || "GET" });
      if (url.pathname === "/api/v1/runs/date-list") {
        return new Response(JSON.stringify({ dates: ["20261020", "20261021"] }), {
          status: 200, headers: { "Content-Type": "application/json" }
        });
      }
      return response(null);
    }));

    render(Workbench);
    const date = await screen.findByLabelText("目标港股日") as HTMLSelectElement;
    expect(date.tagName).toBe("SELECT");
    expect(date.value).toBe("20261020");
    expect(date.textContent).toContain("2026-10-20");
    await waitFor(() => expect(requests).toHaveLength(1));
    expect(requests[0].url.pathname).toContain("/days/20261020/recommendations/");
    expect(requests[0].url.searchParams.get("phase")).toBe("INTRADAY");
    expect(requests[0].url.searchParams.get("run_id")).toBe("old-run");

    await fireEvent.focus(date);
    await waitFor(() => expect(requests.some(x => x.url.pathname === "/api/v1/runs/date-list")).toBe(true));
    await waitFor(() => expect(date.querySelectorAll("option")).toHaveLength(2));
    expect([...date.options].map(option => option.textContent)).toEqual(["2026-10-20", "2026-10-21"]);
    await fireEvent.update(date, "20261021");
    await waitFor(() => expect(requests).toHaveLength(3));
    expect(date.value).toBe("20261021");
    const selectedRequest = requests.find(x => x.url.pathname.includes("/days/20261021/recommendations/"));
    expect(selectedRequest).toBeTruthy();
    expect(selectedRequest?.url.searchParams.has("phase")).toBe(false);
    expect(selectedRequest?.url.searchParams.has("run_id")).toBe(false);
    expect(new URLSearchParams(window.location.search).get("date")).toBe("20261021");
    expect(new URLSearchParams(window.location.search).has("phase")).toBe(false);
    expect(new URLSearchParams(window.location.search).has("run_id")).toBe(false);

    window.history.replaceState(null, "", "?date=20261022");
    window.dispatchEvent(new PopStateEvent("popstate"));
    await waitFor(() => expect(requests).toHaveLength(4));
    expect(date.value).toBe("20261022");
    window.history.replaceState(null, "", "?date=20261021");
    window.dispatchEvent(new PopStateEvent("popstate"));
    await waitFor(() => expect(requests).toHaveLength(5));
    expect(date.value).toBe("20261021");
    expect(requests.every(x => x.method === "GET")).toBe(true);
    expect(requests.some(x => x.method === "POST")).toBe(false);
  });

  it("labels the table as research candidates and leaves a missing count unknown", async () => {
    window.history.replaceState(null, "", "?date=20261013");
    const candidates = [
      { symbol: "HK.00001", qualification: "CURRENT_SUPPORTED" },
      { symbol: "HK.00002", qualification: "DATED_WEAK_PEER" }
    ];
    vi.stubGlobal("fetch", vi.fn(async () => response(candidateDay(candidates), "READY")));

    render(Workbench);
    expect(await screen.findByRole("table", { name: "港股去重研究候选表" })).toBeTruthy();
    expect(screen.getByText("研究候选 2 只（不等于正式入选）")).toBeTruthy();
  });

  it("does not display an absent candidate count as zero", async () => {
    window.history.replaceState(null, "", "?date=20261013");
    vi.stubGlobal("fetch", vi.fn(async () => response(candidateDay(undefined), "READY")));

    render(Workbench);
    expect(await screen.findByRole("table", { name: "港股去重研究候选表" })).toBeTruthy();
    expect(screen.getByText("研究候选数未知（不等于正式入选）")).toBeTruthy();
  });
});
