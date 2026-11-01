import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/vue";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App.vue";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("keeps the research panel link bound to the selected day, including an unmaterialized future day", async () => {
  window.history.replaceState({}, "", "/?date=20261029&stage=STAGE_0925");
  vi.stubGlobal("fetch", vi.fn(async (input: string) => {
    const url = String(input);
    const date = new URL(url, "http://localhost").searchParams.get("date") || "20261029";
    const body = url === "/api/v1/runs/date-list"
      ? { default_date: "20261029", stage_dates: ["20261029", "20261030"], future_target_dates: ["20261102"] }
      : { ok: true, trade_date: date, data_status: "DATA_BLOCKED_EMPTY", rows: [], pools: [],
          blocking_reasons: ["test fixture unavailable"], write_policy: "read_only", RESEARCH_ONLY: true,
          production_allowed: false, buy_gate_updated: false, orders_sent: false };
    return { ok: true, json: async () => body };
  }));
  render(App);
  const link = screen.getByRole("link", { name: "研究看板" });
  await waitFor(() => expect(link.getAttribute("href")).toBe("/research-panel/daily.html?date=2026-10-29"));
  const picker = screen.getByLabelText("交易日（日历选择）");
  await fireEvent.change(picker, { target: { value: "2026-10-30" } });
  await waitFor(() => expect(link.getAttribute("href")).toBe("/research-panel/daily.html?date=2026-10-30"));
  await fireEvent.change(picker, { target: { value: "2026-11-02" } });
  await waitFor(() => expect(link.getAttribute("href")).toBe("/research-panel/daily.html?date=2026-11-02"));
});
