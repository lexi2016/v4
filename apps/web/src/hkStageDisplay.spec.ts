import { cleanup, render, screen, waitFor } from "@testing-library/vue";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App.vue";

const DATE = "20260930";
const jsonResponse = (payload: unknown) => ({ ok: true, json: async () => payload });

function stagePayload(stageId: string, displayMode: "CANNOT_CONFIRM" | "OBSERVATION_UNVERIFIED" | "READY_EMPTY") {
  const row = {
    market: "HK", code: "HK.00001", name: "观察行", rank: 1,
    formal_eligible: false, trade_status: "WATCH_ONLY", stage_display_decision: "WATCH_ONLY",
  };
  const hasObservation = displayMode === "OBSERVATION_UNVERIFIED";
  const readyEmpty = displayMode === "READY_EMPTY";
  return {
    ok: true,
    trade_date: DATE,
    stage: { stage_id: stageId, label: stageId, window: "09:30-09:35", status: readyEmpty ? "READY_EMPTY" : hasObservation ? "PARTIAL_WITH_ROWS" : "CANNOT_CONFIRM", display_status: "display status" },
    markets: {
      A: { status: "READY_EMPTY", candidate_count: 0, rows: [] },
      HK: {
        status: readyEmpty ? "READY_EMPTY" : hasObservation ? "PARTIAL_WITH_ROWS" : "CANNOT_CONFIRM",
        selection_status: readyEmpty ? "READY_EMPTY" : hasObservation ? "PARTIAL_WITH_ROWS" : "CANNOT_CONFIRM",
        display_mode: displayMode,
        display_reasons: displayMode === "CANNOT_CONFIRM" ? ["SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID"] : ["EXECUTION_NOT_BOUND"],
        cannot_confirm: displayMode === "CANNOT_CONFIRM" ? ["SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID"] : [],
        candidate_count: displayMode === "READY_EMPTY" ? 0 : null,
        observation_count: hasObservation ? 10 : 0,
        rows: hasObservation ? Array.from({ length: 10 }, (_, index) => ({ ...row, code: `HK.${String(index + 1).padStart(5, "0")}`, rank: index + 1 })) : [],
      },
    },
    unified_rows: hasObservation ? Array.from({ length: 10 }, (_, index) => ({ ...row, code: `HK.${String(index + 1).padStart(5, "0")}`, rank: index + 1 })) : [],
    selected_a_rows: 0,
    selected_hk_rows: displayMode === "READY_EMPTY" ? 0 : null,
    selected_total_rows: displayMode === "READY_EMPTY" ? 0 : null,
    selection_mode: "SHARED_STAGE_CENTER_READ_ONLY",
    response_source: "SHARED_STAGE_CENTER",
    execution_evidence: {
      markets: { HK_CONNECT: { selection_binding: hasObservation ? "NO_VERIFIED_SELECTION_BINDING" : null, reasons: ["EXECUTION_NOT_BOUND"] } },
    },
    production_allowed: false,
    buy_gate_updated: false,
    orders_sent: false,
  };
}

function installStageResponse(mode: "CANNOT_CONFIRM" | "OBSERVATION_UNVERIFIED" | "READY_EMPTY") {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === "/api/v1/runs/date-list") {
      return jsonResponse({ default_date: DATE, stage_dates: [DATE], future_target_dates: [] });
    }
    if (url.startsWith("/api/v3/workbench/stage")) {
      const parsed = new URL(url, window.location.origin);
      const stage = parsed.searchParams.get("stage") || "STAGE_0930_0935";
      return jsonResponse(stagePayload(stage, mode));
    }
    return jsonResponse({ data_status: "DATA_BLOCKED_EMPTY", trade_date: DATE, rows: [], blocking_reasons: [] });
  }));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ordinary HK stage display evidence", () => {
  it("shows missing formal output as unknown instead of zero", async () => {
    window.history.replaceState({}, "", `/?date=${DATE}&stage=STAGE_0930_0935`);
    installStageResponse("CANNOT_CONFIRM");
    render(App);

    const hkRegion = await screen.findByRole("region", { name: "港股通候选" });
    await waitFor(() => expect(hkRegion.textContent).toContain("待确认/缺少正式产物"));
    expect(hkRegion.textContent).toContain("待确认/缺少正式产物");
    expect(hkRegion.textContent).toContain("SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID");
    expect(hkRegion.textContent).not.toContain("0 条");
  });

  it("labels unsafe or unbound HK rows as observations", async () => {
    window.history.replaceState({}, "", `/?date=${DATE}&stage=STAGE_0930_0935`);
    installStageResponse("OBSERVATION_UNVERIFIED");
    render(App);

    const hkRegion = await screen.findByRole("region", { name: "港股通观察行" });
    expect(hkRegion.textContent).toContain("10 条观察行 · 未验证");
    expect(hkRegion.textContent).toContain("EXECUTION_NOT_BOUND");
    expect(hkRegion.textContent).toContain("观察 · 未验证");
    expect(hkRegion.textContent).not.toContain("10 条候选");
    expect(hkRegion.textContent).not.toContain("10 条入选");
  });

  it("keeps a verified READY_EMPTY result as zero", async () => {
    window.history.replaceState({}, "", `/?date=${DATE}&stage=STAGE_0930_0935`);
    installStageResponse("READY_EMPTY");
    render(App);

    const hkRegion = await screen.findByRole("region", { name: "港股通候选" });
    await waitFor(() => expect(hkRegion.textContent).toContain("正式空结果已验证"));
    expect(hkRegion.textContent).toContain("0 条 · 正式空结果已验证");
    expect(hkRegion.textContent).toContain("正式结果为空（READY_EMPTY）");
  });
});
