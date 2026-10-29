import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App.vue";

const blockedPool = { data_status: "DATA_BLOCKED_EMPTY", trade_date: "20260730", rows: [], blocking_reasons: ["missing"] };
const referenceStage = {
  ok: true,
  trade_date: "20260730",
  stage: {
    stage_id: "STAGE_0925",
    label: "09:20/09:25竞价参考",
    window: "09:20-09:25",
    status: "DATA_PARTIAL_OBSERVE_ONLY",
    display_status: "09:25 竞价落盘：候选仅供观察",
  },
  markets: {
    A: { label: "A股", candidate_count: 0, source_rows: 1, requested_rows: 159, data_level: "L1_TREND_ANALYSIS" },
    HK: { label: "港股通", candidate_count: 2, source_rows: 100, data_level: "AUCTION_SECOND_FILTER_READY" },
  },
  unified_rows: [
    {
      market: "HK",
      code: "HK.01357",
      name: "美图公司",
      rank: 1,
      score: 82,
      d1_change_pct: 13.0653,
      stage_display_decision: "09:30初步筛选",
      next_validation_time: "09:35",
      support_primary_price: 4.02,
      pressure_price: 4.18,
      invalidation_price: 3.96,
      cannot_confirm: ["CANNOT_CONFIRM_SUPPORT_INVALIDATION_LINE"],
      data_level: "AUCTION_SECOND_FILTER_READY",
      recommendation_status: "WATCH_ONLY",
    },
    {
      market: "HK",
      code: "HK.09903",
      name: "天数智芯",
      rank: 2,
      score: 80.59,
      d1_change_pct: -13.5029,
      stage_display_decision: "09:30初步筛选",
      next_validation_time: "09:35",
      cannot_confirm: [],
      data_level: "AUCTION_SECOND_FILTER_READY",
      recommendation_status: "WATCH_ONLY",
    },
  ],
  selected_a_rows: 0,
  selected_hk_rows: 2,
  selected_total_rows: 2,
  selection_mode: "MIGRATED_REFERENCE_WORKBENCH",
  response_source: "V3_5_MIGRATED_REFERENCE_SNAPSHOT",
  reference_snapshot: true,
  recommendation_status: "WATCH_ONLY_BACKTEST_GATED",
  production_allowed: false,
  buy_gate_updated: false,
  orders_sent: false,
};
const jsonResponse = (payload: unknown) => {
  if (payload && typeof payload === "object" && !Array.isArray(payload)) {
    const record = payload as Record<string, unknown>;
    if ("stage" in record && typeof record.trade_date === "string") {
      payload = {
        RESEARCH_ONLY: true,
        write_performed: false,
        production_allowed: false,
        buy_gate_updated: false,
        orders_sent: false,
        ...record,
      };
    } else if ("data_status" in record) {
      payload = {
        write_policy: "read_only",
        production_allowed: false,
        buy_gate_updated: false,
        orders_sent: false,
        ...record,
      };
    }
  }
  return { ok: true, json: async () => payload };
};
const poolRequestUrl = (date: string, offset = 0) =>
  `/api/v4/preselection-pools?date=${date}&limit=200&offset=${offset}`;
function expectPoolRequest(date: string, offset = 0) {
  expect(vi.mocked(fetch)).toHaveBeenCalledWith(
    poolRequestUrl(date, offset),
    expect.objectContaining({ signal: expect.anything() }),
  );
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((accept) => { resolve = accept; });
  return { promise, resolve };
}
function exactMissingStageReceipt(date: string, stageId: string) {
  return {
    trade_date: date,
    stage_id: stageId,
    status: "CANNOT_CONFIRM",
    stage: { stage_id: stageId, status: "CANNOT_CONFIRM", display_status: "CANNOT_CONFIRM" },
    markets: {
      A: { status: "CANNOT_CONFIRM", display_mode: "CANNOT_CONFIRM", candidate_count: null },
      HK: { status: "CANNOT_CONFIRM", display_mode: "CANNOT_CONFIRM", candidate_count: null },
    },
    selection_markets: {
      A_SHARE: {
        market: "A_SHARE", status: "CANNOT_CONFIRM", selection_status: "CANNOT_CONFIRM",
        source_status: "CANNOT_CONFIRM", requested_rows: null, source_rows: null, selected_rows: null,
        coverage_ratio: null, rows: null, source_evidence: [],
        cannot_confirm: ["SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID"],
        selection_manifest_receipt_verified: false,
      },
      HK_CONNECT: {
        market: "HK_CONNECT", status: "CANNOT_CONFIRM", selection_status: "CANNOT_CONFIRM",
        source_status: "CANNOT_CONFIRM", requested_rows: null, source_rows: null, selected_rows: null,
        coverage_ratio: null, rows: null, source_evidence: [],
        cannot_confirm: ["SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID"],
        selection_manifest_receipt_verified: false,
      },
    },
    execution_evidence: {
      trade_date: date,
      stage_id: stageId,
      status: "EXECUTION_RECEIPT_MISSING",
      execution_verified: false,
      natural_verified: false,
      write_performed: false,
      cannot_confirm: ["EXACT_DATE_STAGE_RECEIPT_MISSING"],
    },
    cannot_confirm_codes: [
      "A:SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID",
      "HK:SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID",
      "SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID",
    ],
    unified_rows: [],
    selected_a_rows: 0,
    selected_hk_rows: null,
    selected_total_rows: null,
    selection_mode: "SHARED_STAGE_CENTER_READ_ONLY",
  };
}
function missingArtifact0925Stage(date: string) {
  const payload: any = exactMissingStageReceipt(date, "STAGE_0925");
  const unavailable = [
    "SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID",
    "A:SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID",
    "HK:SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID",
  ];
  payload.stage = { ...payload.stage, window: "09:20-09:25", cannot_confirm: unavailable };
  payload.cannot_confirm = unavailable;
  payload.markets = {
    A: {
      market: "A_SHARE", status: "CANNOT_CONFIRM", selection_status: "CANNOT_CONFIRM",
      source_status: "CANNOT_CONFIRM", requested_rows: null, source_rows: null, selected_rows: null,
      candidate_count: 0, rows: [], cannot_confirm: ["SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID"],
    },
    HK: {
      market: "HK_CONNECT", status: "CANNOT_CONFIRM", selection_status: "CANNOT_CONFIRM",
      source_status: "CANNOT_CONFIRM", requested_rows: null, source_rows: null, selected_rows: null,
      candidate_count: null, display_mode: "CANNOT_CONFIRM", observation_count: null, rows: [],
      cannot_confirm: ["SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID"],
    },
  };
  payload.market_summaries = structuredClone(payload.markets);
  payload.selection_markets.A_SHARE.rows = [];
  delete payload.selection_markets.A_SHARE.selection_manifest_receipt_verified;
  payload.selection_markets.HK_CONNECT.rows = [];
  delete payload.selection_markets.HK_CONNECT.selection_manifest_receipt_verified;
  return payload;
}
const taskStatus = {
  logical_workload_count: 3,
  active_owner_count: 1,
  alias_count: 2,
  retired_owner_count: 6,
  task_registration_count: 1,
  groups: {
    logical: [{
      workload_id: "hourly_research", status: "CANNOT_CONFIRM",
      last_run: null, next_due: "07:00", duration_ms: null,
      result_code: "EXECUTION_RECEIPT_MISSING", freshness: "NOT_OBSERVED", receipt_path: null,
    }],
    active_owners: [{ owner_id: "v35_dispatcher.hourly_research", workload_id: "hourly_research", status: "ACTIVE" }],
    aliases: [
      { alias: "hourly_research_delta", workload_id: "hourly_research", status: "ALIAS_ONLY" },
      { alias: "v3_hourly_research_delta_0730_1530", workload_id: "hourly_research", status: "ALIAS_ONLY" },
    ],
    retired: [{ owner_id: "OpeningAdvisorHourlyResearch", replacement_workload_id: "hourly_research", status: "RETIRED_DISABLED" }],
    registrations: [{
      graph_task_spec_id: "task_spec:OpeningAdvisorV3_0755_StartupEnsure",
      legacy_task_id: "OpeningAdvisorV3_0755_StartupEnsure",
      timeline_node_ids: ["v3_ashare_readiness_0755"],
      legacy_launcher_paths: ["launcher.ps1"],
      actual_windows_task_ids: ["OpeningAdvisorV3_0755_StartupEnsure"],
      enabled: false,
      execution_allowed: false,
      status: "CANNOT_CONFIRM",
      disposition: "USER_APPROVED_DISABLED_CANNOT_CONFIRM",
    }],
  },
  cannot_confirm: ["EXECUTION_RECEIPT_MISSING:hourly_research", "GRAPH_TASK_REGISTRATIONS_CANNOT_CONFIRM:1"],
  production_allowed: false,
  buy_gate_updated: false,
  orders_sent: false,
};
const closeReview = {
  trade_date: "20260730",
  reference_snapshot: false,
  market_reviews: {
    A: {
      status: "READY", headline: "A-share review", market_regime: "CANNOT_CONFIRM", risk_tone: "CANNOT_CONFIRM",
      big_picture: [], mainlines: [], core_stocks: [], observation_pool: [], next_day_trigger_tree: [], quality_gate: [],
      cannot_confirm: ["A_REVIEW_GAP"], production_allowed: false, buy_gate_updated: false, orders_sent: false,
    },
    HK: {
      model_selection_review: {
        schema_version: "v3_5.close_review.v1",
        evidence_mode: "V3_5_NATIVE_PRODUCTION",
        status: "MODEL_REVIEW_PARTIAL_STAGE_EVIDENCE",
        trade_date: "20260730",
        primary_kpi: "全港股通收盘涨幅Top20覆盖率",
        models: {
          "0.2_prob_active": { selected_count: 100, hit_count: 3, coverage_pct: 15, precision_pct: 3 },
        },
        stage_union: { selected_count: 17, hit_count: 2, coverage_pct: 10, precision_pct: 11.765 },
        row_counts: { close_top20: 20, model_0_2: 100, stage_rows: 17 },
        top20_attribution: [{
          rank: 1, code: "HK.00325", name: "布鲁可", pct_chg_close: 15.9343,
          model_0_2_hit: true, stage_union_hit: false, classification: "model_only",
        }],
        close_top20: [{ rank: 1, code: "HK.00325", name: "布鲁可", pct_chg_close: 15.9343 }],
        model_rows: [],
        stage_rows: [],
        missing_stages: ["STAGE_0925"],
        cannot_confirm: ["MISSING_STAGE_0925"],
        production_allowed: false,
        buy_gate_updated: false,
        orders_sent: false,
      },
    },
  },
  production_allowed: false,
  buy_gate_updated: false,
  orders_sent: false,
};


import {readFileSync} from 'node:fs';
import {stageMarketStateText} from './app_shell/formatters';
describe("V4 legacy-compatible stage workbench", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/?date=20260730&stage=STAGE_0925");
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/v1/runs/date-list") {
        return jsonResponse({ default_date: "20260730", stage_dates: ["20260730"], future_target_dates: [] });
      }
      if (url.startsWith("/api/v4/tasks/status")) return jsonResponse(taskStatus);
      if (url.startsWith("/api/v4/workbench/stage")) return jsonResponse(referenceStage);
      return jsonResponse(blockedPool);
    }));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });


 it('shows real supplementary10 before input56, scores/clocks/null and keeps formal count0',async()=>{
  const selected=JSON.parse(readFileSync("/Users/lexi/.codex/worktrees/v4-stage-sync-20261028/v4_app/docs/handoffs/v4_a_chain_completion_20261028/online_completion_20261029/natural_repair_20261029/snapshot_selection_r1/evidence/REPRESENTATIVE_CANDIDATE_RESULT.json",'utf8')).result;
  const payload:any={...referenceStage,reference_snapshot:false,response_source:'SHARED_STAGE_CENTER',selected_a_rows:0,snapshot_reselection:{status:'SELECTED_WATCH_ONLY',markets:{A_SHARE:selected}}};
  expect(stageMarketStateText(payload,'A')).toContain('事后补选10条');
  expect(stageMarketStateText({...payload,selected_a_rows:10},'A')).not.toContain('补选');
  const prior=vi.mocked(fetch).getMockImplementation()!;vi.stubGlobal('fetch',vi.fn(async(url:string,...args:any[])=>url.startsWith('/api/v4/workbench/stage')?jsonResponse(payload):prior(url,...args)));
  render(App);await waitFor(()=>expect(document.querySelector('[data-snapshot-reselection] tbody')?.children.length).toBe(10));
  const text=document.querySelector('[data-snapshot-reselection]')?.textContent;
  for(const value of ['A.001318','134.202658','15:19','1400','1500','null','WATCH_ONLY'])expect(text).toContain(value);
  expect(payload.selected_a_rows).toBe(0);expect(screen.getByRole('button',{name:'SOP',exact:true})).toBeTruthy();
 });
});
