import actualWire from "./fixtures/real-announcement-http.local.json";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/vue";
import Workbench from "../Workbench.vue";
import { detailRisks, readableReason, researchRows, researchSections, stockTitle } from "../display";
import type { Envelope, DayData, StockDetails } from "../types";
import { sampleStock } from "./fixtures/sample";

// Actual frozen R10 TestClient + immutable real r2. Generate locally via
// fixtures/capture_real_detail.py before this suite; never upload its JSON.
const actual = actualWire as unknown as {
  day: Envelope<DayData>; detail: Envelope<StockDetails>;
};
const detail = actual.detail.data!;
const row = detail.lane_details.find(x => x.lane === "ANNOUNCEMENT")!.rows[0];
const semantic = row.semantic as { reason: string; risk_notes: string[]; facts: { claim: string; quote: string }[] };

describe("saved real announcement research display", () => {
  beforeEach(() => window.history.replaceState(null, "", "?date=20261012&phase=RETROSPECTIVE&run_id=" + detail.plan_run_id));
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("keeps historical announcement evidence readable without treating it as a default recommendation entry", () => {
    // Announcement selection is paused; the independent US/oversold entry
    // deliberately does not load this historical aggregate as a new lane row.
    const before = JSON.stringify(detail);
    expect(detail.stock.name).toBeNull();
    expect(semantic.risk_notes).toHaveLength(2);
    expect(readableReason(row)).toBe(semantic.reason);
    const sections = researchSections(row);
    expect(sections.find(x => x.key === "facts")!.items[0].claim).toBe(semantic.facts[0].claim);
    expect(sections.find(x => x.key === "facts")!.items[0].quote).toBe(semantic.facts[0].quote);
    expect(detailRisks(detail)).toEqual(semantic.risk_notes.map(x => "公告：" + x));
    expect(JSON.stringify(detail)).toBe(before);
  });

  it("reads exact fields without inventing claims or spilling unknown objects into prose", () => {
    const missing = { semantic: { facts: [{ unexpected: "must stay in audit" }], changes: null,
      impact: [{ claim: "recorded impact", quote: "recorded quote", locator: "p1" }] },
      conditions: ["recorded condition"], risks: [] };
    const sections = researchSections(missing);
    expect(sections.find(x => x.key === "facts")!.items).toEqual([]);
    expect(sections.find(x => x.key === "changes")!.items).toEqual([]);
    expect(sections.find(x => x.key === "confirmation_conditions")!.items[0].claim).toBe("recorded condition");
    expect(readableReason({ reason: "ANNOUNCEMENT_NOT_SELECTED" })).toBe("未提供可读研究理由");
    expect(stockTitle({ ...sampleStock(), name: null })).toBe("HK.01234");
  });

  it("uses source rows once, keeps multiple records and never promotes across lanes", () => {
    expect(researchRows(detail.stock, "ANNOUNCEMENT", detail.lane_details[0])).toEqual(detail.lane_details[0].rows);
    const stock = sampleStock();
    stock.lane_decisions.ANNOUNCEMENT = [{ reason: "first" }, { reason: "second" }];
    expect(researchRows(stock, "ANNOUNCEMENT")).toHaveLength(2);
    expect(detailRisks(detail)).toEqual(semantic.risk_notes.map(x => "公告：" + x));
    expect(stock.decision).toBe("CONDITIONAL_WATCH");
  });
});
