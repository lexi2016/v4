import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/vue";
import Workbench from "../Workbench.vue";
import { SCHEMA_VERSION } from "../types";
import type { DayData, Envelope } from "../types";
import { sampleDay } from "./fixtures/sample";

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
  const factorSummary = { single_day_mapping: singleDay };
  return sampleDay({ us_mapping_summary: {
    display_only: true,
    plan_run_id: "synthetic-run-1",
    source_symbol_count: 0,
    source_row_count: 0,
    relation_row_count: 0,
    mapped_hk_count: 0,
    source_decision_counts: {},
    mixed_source_count: 0,
    coverage: { scope_count: 0, observed_count: 0, assessed_count: 0, unassessed_count: 0 },
    groups: [],
    factor_summary: factorSummary
  } as unknown as NonNullable<DayData["us_mapping_summary"]> });
}

describe("manager workbench date calendar", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "?date=20261020&phase=INTRADAY&run_id=old-run");
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("uses a native date picker while keeping URL and request dates compact, clears old version, and ignores empty input", async () => {
    const requests: URL[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      requests.push(new URL(String(input), window.location.origin));
      return response(null);
    }));

    render(Workbench);
    const date = await screen.findByLabelText("目标港股日") as HTMLInputElement;
    expect(date.type).toBe("date");
    expect(date.value).toBe("2026-10-20");
    expect(date.required).toBe(true);
    await waitFor(() => expect(requests).toHaveLength(1));
    expect(requests[0].pathname).toContain("/days/20261020/recommendations/");
    expect(requests[0].searchParams.get("phase")).toBe("INTRADAY");
    expect(requests[0].searchParams.get("run_id")).toBe("old-run");

    const form = date.closest("form");
    if (!form) throw new Error("date picker form missing");
    await fireEvent.update(date, "2026-10-21");
    await fireEvent.submit(form);
    await waitFor(() => expect(requests).toHaveLength(2));
    expect(date.value).toBe("2026-10-21");
    expect(requests[1].pathname).toContain("/days/20261021/recommendations/");
    expect(requests[1].searchParams.has("phase")).toBe(false);
    expect(requests[1].searchParams.has("run_id")).toBe(false);
    expect(new URLSearchParams(window.location.search).get("date")).toBe("20261021");
    expect(new URLSearchParams(window.location.search).has("phase")).toBe(false);
    expect(new URLSearchParams(window.location.search).has("run_id")).toBe(false);

    const requestCount = requests.length;
    const selectedUrl = window.location.href;
    await fireEvent.update(date, "");
    await fireEvent.submit(form);
    await waitFor(() => expect(requests).toHaveLength(requestCount));
    expect(window.location.href).toBe(selectedUrl);

    window.history.replaceState(null, "", "?date=20261022");
    window.dispatchEvent(new PopStateEvent("popstate"));
    await waitFor(() => expect(requests).toHaveLength(requestCount + 1));
    expect(date.value).toBe("2026-10-22");
    window.history.replaceState(null, "", "?date=20261021");
    window.dispatchEvent(new PopStateEvent("popstate"));
    await waitFor(() => expect(requests).toHaveLength(requestCount + 2));
    expect(date.value).toBe("2026-10-21");
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
