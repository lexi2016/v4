import { cleanup, render, screen, waitFor } from "@testing-library/vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App.vue";

const jsonResponse = (payload: unknown) => ({ ok: true, json: async () => payload });

describe("HK open / Southbound closed navigation", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.history.replaceState({}, "", "/");
  });

  it("retains an explicit HK observation date and labels the closed Connect lane", async () => {
    window.history.replaceState({}, "", "/?date=20260925");
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({
          default_date: "20260924",
          navigation_date: "20260925",
          system_date: "20260925",
          dates: ["20260924", "20260925"],
          stage_dates: ["20260924"],
          future_target_dates: [],
          hk_observation_only_dates: ["20260925"],
        });
      }
      if (url.startsWith("/api/v3/workbench/stage")) {
        return jsonResponse({ trade_date: "20260925" });
      }
      return jsonResponse({
        trade_date: "20260925",
        data_status: "CANNOT_CONFIRM",
        rows: [],
        pools: [],
      });
    }));

    render(App);

    await waitFor(() => {
      expect((screen.getByLabelText("交易日（日历选择）") as HTMLInputElement).value)
        .toBe("2026-09-25");
    });
    const notice = await screen.findByText(/港股开市 · 港股通\/南向暂停，仅作研究观察/);
    expect(notice.textContent).toContain("无有效池则 CANNOT_CONFIRM");
  });
});
