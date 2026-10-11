import { cleanup, render, screen, within } from "@testing-library/vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App.vue";

const jsonResponse = (payload: unknown) => ({ ok: true, json: async () => payload });
const rawSha = "a".repeat(64);
const manifestSha = "b".repeat(64);
const receiptSha = "c".repeat(64);
const d1Sha = "d".repeat(64);

function automaticWorkbench(date: string, d1Status = "STRICT_0_2_READY") {
  const timestamp = `${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6, 8)} 09:35:00`;
  const rawRun = `${date}-hk_connect_1min_stage_0930_0935-test`;
  const sourceEvidence = [
    "substitute_kind=HK_0930_0935_FOR_HK_0925",
    "source_stage_id=STAGE_0930_0935",
    "source_window=09:30-09:35",
    `source_trade_date=${date}`,
    `source_last_bar_time=${timestamp}`,
    `source_raw_run_id=${rawRun}`,
    `source_raw_artifact_sha256=${rawSha}`,
    `source_manifest_sha256=${manifestSha}`,
    `source_receipt_sha256=${receiptSha}`,
    "source_manifest_temporal_cutoff_safe=false",
    "target_stage_temporal_cutoff_safe=false",
    `d1_membership_status=${d1Status}`,
    "d1_pool_role=HK_CONNECT_D1_TOP100",
    "d1_pool_count=100",
    `d1_pool_sha256=${d1Sha}`,
  ];
  return {
    ok: true,
    trade_date: date,
    stage: {
      stage_id: "STAGE_0925",
      label: "09:20/09:25竞价参考",
      window: "09:20-09:25",
      status: "PARTIAL_WITH_ROWS",
      display_status: "09:25 研究观察",
    },
    markets: {
      A: { label: "A股", candidate_count: 0, source_rows: 0, requested_rows: 0 },
      HK: {
        label: "港股通",
        status: "PARTIAL_WITH_ROWS",
        selection_status: "PARTIAL_WITH_ROWS",
        selection_mode: "BACKFILL",
        selection_run_id: undefined as string | undefined,
        selection_manifest_receipt_verified: undefined as boolean | undefined,
        runner_receipt_status: undefined as string | undefined,
        display_mode: "OBSERVATION_UNVERIFIED",
        candidate_count: null,
        source_rows: 98,
        requested_rows: 100,
        source_evidence: sourceEvidence,
      },
    },
    unified_rows: [{
      market: "HK",
      code: "HK.00068",
      name: "Test Co",
      rank: 1,
      score: 60,
      trade_date: date,
      stage_id: "STAGE_0925",
      source_mode: "HK_CONNECT_0930_0935_SUBSTITUTE_STAGE_0925",
      lane_evidence: ["09:30-09:35_OPENING_DATA_SUBSTITUTE_FOR_0920"],
      substitute_label: "09:30-09:35开盘数据替代补算；实际数据截止09:35",
      substitute_source_stage_id: "STAGE_0930_0935",
      substitute_source_window: "09:30-09:35",
      source_last_bar_time: timestamp,
      source_temporal_cutoff_safe: false,
      target_stage_temporal_cutoff_safe: false,
      source_raw_run_id: rawRun,
      source_raw_artifact_sha256: rawSha,
      source_manifest_sha256: manifestSha,
      source_receipt_sha256: receiptSha,
      d1_pool_sha256: d1Sha,
      d1_pool_role: "HK_CONNECT_D1_TOP100",
      formal_eligible: false,
      action_level: "NO_BUY",
      next_validation_time: "09:35:05",
    }],
    selected_a_rows: 0,
    selected_hk_rows: null,
    selected_total_rows: null,
    production_allowed: false,
    buy_gate_updated: false,
    orders_sent: false,
  };
}

function stubWorkbench(date: string, stagePayload: unknown) {
  window.history.replaceState({}, "", `/?date=${date}&stage=STAGE_0925`);
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (url === "/api/v1/runs/date-list") {
      return jsonResponse({ default_date: date, stage_dates: [date], future_target_dates: [] });
    }
    if (url.startsWith("/api/v3/workbench/stage")) return jsonResponse(stagePayload);
    return jsonResponse({ trade_date: date, data_status: "CANNOT_CONFIRM", rows: [], pools: [], blocking_reasons: [] });
  }));
}

describe("automatic HK 09:20 substitute evidence", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.history.replaceState({}, "", "/");
  });

  it("shows a later-date substitute only when exact D-1 and source lineage match", async () => {
    const date = "20260924";
    const stage = automaticWorkbench(date);
    stubWorkbench(date, stage);
    render(App);
    expect(await screen.findByText("Test Co")).toBeTruthy();
    const hkRegion = screen.getByRole("region", { name: "港股通研究回补选股" });
    expect(within(hkRegion).getByText("09:30–09:35开盘数据替代补算；实际数据截止09:35")).toBeTruthy();
    expect(within(hkRegion).getByText(`${date} · 2026-09-24 09:35:00`)).toBeTruthy();
  });

  it("shows the verified SelectionStore run while leaving runner receipt unconfirmed", async () => {
    const date = "20260924";
    const stage = automaticWorkbench(date);
    stage.markets.HK.selection_run_id = "run-295ba659a064a50bf8d8f849";
    stage.markets.HK.selection_manifest_receipt_verified = true;
    stage.markets.HK.runner_receipt_status = "CANNOT_CONFIRM";
    stubWorkbench(date, stage);
    render(App);
    const lineage = await screen.findByTestId("stage-backfill-consumer-provenance");
    expect(lineage.textContent).toContain("run=run-295ba659a064a50bf8d8f849");
    expect(lineage.textContent).toContain("SelectionStore manifest/receipt=已验证");
    expect(lineage.textContent).toContain("runner receipt=CANNOT_CONFIRM");
  });

  it("does not label a current automatic row as a substitute when exact D-1 binding is absent", async () => {
    const date = "20260924";
    const stage = automaticWorkbench(date, "RECONSTRUCTED_ASOF_CANDIDATE_PIT_UNVERIFIED");
    stubWorkbench(date, stage);
    render(App);
    expect(await screen.findByText("Test Co")).toBeTruthy();
    const hkRegion = screen.getByRole("region", { name: "港股通研究回补选股" });
    expect(hkRegion.querySelector(".evidence-note")?.textContent ?? "").not.toContain("开盘数据替代补算");
  });

  it("preserves the accepted 2026-10-09 reconstructed-D1 research result", async () => {
    const date = "20261009";
    const stage = automaticWorkbench(date);
    stage.markets.HK.source_evidence = [
      "substitute_kind=HK_0930_0935_FOR_HK_0925",
      "substitute_label=09:30-09:35开盘数据替代补算",
      "source_stage_id=STAGE_0930_0935",
      "source_window=09:30-09:35",
      "source_last_bar_time=2026-10-09 09:35:00",
      "source_manifest_temporal_cutoff_safe=false",
      "target_stage_temporal_cutoff_safe=false",
      "d1_membership_status=RECONSTRUCTED_ASOF_CANDIDATE_PIT_UNVERIFIED",
    ];
    stage.unified_rows[0] = {
      ...stage.unified_rows[0],
      source_mode: "HK_CONNECT_0930_0935_SUBSTITUTE_STAGE_0925",
      lane_evidence: ["09:30-09:35_OPENING_DATA_SUBSTITUTE_FOR_0920"],
      source_last_bar_time: "2026-10-09 09:35:00",
      source_temporal_cutoff_safe: false,
      substitute_label: "09:30-09:35开盘数据替代补算；实际数据截止09:35",
      substitute_source_stage_id: "STAGE_0930_0935",
      substitute_source_window: "09:30-09:35",
      next_validation_time: "09:35:05",
    };
    stubWorkbench(date, stage);
    render(App);
    expect(await screen.findByText("Test Co")).toBeTruthy();
    expect(screen.getByText("09:30–09:35开盘数据替代补算；实际数据截止09:35")).toBeTruthy();
  });
});
