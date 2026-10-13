import { describe, expect, it } from "vitest";
import { isValidDate, parseWorkbenchRoute, routeSearch, todayHongKong } from "../route";

describe("MWB route identity", () => {
  it("accepts a valid saved deep link", () => {
    const route = parseWorkbenchRoute("?date=20261013&phase=INTRADAY&run_id=abc-001");
    expect(route).toEqual({ date: "20261013", phase: "INTRADAY", runId: "abc-001", error: null });
  });
  it("gives legacy plan_date authority for target date and cleans it from URL", () => {
    const route = parseWorkbenchRoute("?date=20261012&plan_date=20261013&view=dynamic");
    expect(route.date).toBe("20261013");
    expect(routeSearch(route, "?date=20261012&plan_date=20261013&view=dynamic"))
      .toBe("?date=20261013&view=dynamic");
  });
  it("rejects impossible dates, bad phases and path-shaped run ids", () => {
    expect(isValidDate("20260229")).toBe(false);
    expect(isValidDate("20240229")).toBe(true);
    expect(parseWorkbenchRoute("?date=20261301").error).toMatch(/日期/);
    expect(parseWorkbenchRoute("?date=20261013&phase=EARLY").error).toMatch(/阶段/);
    expect(parseWorkbenchRoute("?date=20261013&run_id=../secret").error).toMatch(/版本/);
  });
  it("uses Hong Kong time zone for the default target date without claiming it is a trading day", () => {
    expect(todayHongKong(new Date("2026-10-12T17:00:00Z"))).toBe("20261013");
  });
});
