import { fireEvent, waitFor } from "@testing-library/vue";
import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";

const workspaceMocks = vi.hoisted(() => ({
  request: vi.fn(),
  refresh: vi.fn(),
}));

vi.mock("../api/managerWorkspace.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/managerWorkspace.js")>()),
  requestManagerWorkspace: workspaceMocks.request,
  refreshManagerWorkspace: workspaceMocks.refresh,
}));

import { groupThemeMappings, mountCatalystObservations } from "./catalystObservationPanel";
import { validateManagerWorkspace, type JsonObject, type ManagerWorkspace, type ReboundScreen } from "../api/managerWorkspace";

const makeLane = (lane: "STAGE" | "CATALYST" | "CLOSE") => ({
  lane, owner: `SIMULATED_${lane}`, state: "NOT_RUN", target_date: "20260921",
  stock_count: null, last_attempt_at: null, last_success_at: null, run_id: null,
  execution_kind: "READ_ONLY", failure_reasons: [], next_plan: null,
  schedule_status: "UNBOUND", input_coverage: {},
});

const workspaceBase = {
  RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false,
  input_identity: "a".repeat(64),
  target_trade_date: "20260921",
  schema_version: "v4.manager_research.workspace.v1",
  semantic_version: "20260921.manager-semantic.r3.v1",
  focus_symbols: [],
  lanes: [makeLane("STAGE"), makeLane("CATALYST"), makeLane("CLOSE")],
  stocks: [],
  themes: [],
  company_events: [],
  rejected_relations: [],
  materials: [],
  gaps: [],
  summary: { stock_count: 0, relation_count: 0, theme_count: 0, reused_material_count: 0, formal_recommendation_count: 0 },
  briefing: { headline: "", ordering_explanation: "" },
  plan_context: { research_cutoff: "", market_session: "", market_data_verified: false },
  plan_product: { status: "CURRENT" },
  workspace_plan_attempt: { state: "SUCCEEDED" },
  owner_chain: {},
} as unknown as ManagerWorkspace;

const strictCard: JsonObject = {
  classification: "STRICT_REBOUND", qualification_status: "RESEARCH_ONLY_CANDIDATE",
  code: "HK.02589", name: "沪上阿姨（合成案例）", target_monday: "20260921",
  history_status: "KNOWN", prior60_session_count: 60, amount_hkd: 15_855_358,
  oversold_flag: true, volume_ratio_5d: 227_090 / 114_216, rebound_close_vs_low_pct: 1.23,
};
const nearCard: JsonObject = {
  classification: "NEAR_CONDITION", qualification_status: "RESEARCH_ONLY_CANDIDATE",
  code: "HK.09998", name: "合成近条件", target_monday: "20260921",
  history_status: "KNOWN", prior60_session_count: 60, amount_hkd: 250_000_000,
  oversold_flag: true, volume_ratio_5d: 1.4, rebound_close_vs_low_pct: 0,
  near_failed_gate: "volume_5d_ratio", near_failed_value: 1.4, near_gate_value: 1.5,
  near_gate_gap_ratio: (1.5 - 1.4) / 1.5,
};
const twoGateScreen: ReboundScreen = {
  schema_version: "v4.manager_research.rebound_v3_screen.v1",
  rule_version: "20260923_REBOUND_TWO_GATE_V1", target_trade_date: "20260921",
  verified_session: "20260918", status: "READY", cards: [strictCard, nearCard],
  strict: [strictCard], near: [nearCard], pending: [], gaps: [],
  coverage: { input_candidate_count: 2, history_complete_count: 2, history_pending_count: 0,
    strict_count: 1, near_candidate_count: 1, near_count: 1, selected_count: 2 },
  input_identity: "b".repeat(64), authority: null,
  RESEARCH_ONLY: true, production_allowed: false, buy_gate_updated: false, orders_sent: false,
  main_screen_ready: true,
};
const workspaceWithScreen = (): ManagerWorkspace => ({
  ...workspaceBase, market_screen: twoGateScreen,
}) as unknown as ManagerWorkspace;

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
  vi.restoreAllMocks();
  document.body.replaceChildren();
});

describe("catalyst workspace runtime boundary", () => {
  it("accepts the two-gate screen and rejects the frozen four-gate rule version", () => {
    const accepted = validateManagerWorkspace(workspaceWithScreen(), "20260921");
    expect(accepted.market_screen?.rule_version).toBe("20260923_REBOUND_TWO_GATE_V1");
    const stale = {
      ...workspaceWithScreen(),
      market_screen: { ...twoGateScreen, rule_version: "20260921_REBOUND_V3" },
    };
    expect(() => validateManagerWorkspace(stale, "20260921")).toThrow("WORKSPACE_SCREEN_RULE_STALE");
  });

  it("labels amount and close-to-low rebound as observations while showing every near candidate", async () => {
    workspaceMocks.request.mockResolvedValue(workspaceWithScreen());
    const host = document.createElement("div");
    document.body.append(host);
    const dispose = mountCatalystObservations(host, "20260921");
    await waitFor(() => expect(host.textContent).toContain("近条件候选（1）"));
    const rendered = host.textContent || "";
    expect(rendered).toContain("成交额 15855358 HKD（观察值）");
    expect(rendered).toContain("收盘较当日低点反弹 1.23%（观察值）");
    expect(rendered).toContain("成交额 250000000 HKD（观察值）");
    expect(rendered).not.toContain(">1亿");
    expect(rendered).not.toContain("≤2亿");
    expect(rendered).not.toContain("反弹≥3%");
    dispose();
  });

  it("shows a persisted MANUAL_REFRESH as a next-session draft, not a frozen plan", async () => {
    workspaceMocks.request.mockResolvedValue({
      ...workspaceWithScreen(),
      plan_product: { status: "CURRENT", run_id: "manual-run" },
      workspace_plan_attempt: { state: "PARTIAL", run_id: "manual-run", execution_kind: "MANUAL_REFRESH" },
    });
    const host = document.createElement("div");
    document.body.append(host);
    const dispose = mountCatalystObservations(host, "20260921");
    await waitFor(() => expect(host.textContent).toContain("次日研究预览（已保存草案；未正式冻结）"));
    expect(host.textContent).toContain("计划：已保存研究草案（未正式冻结）");
    dispose();
  });

  it("shows saved next-session research focus separately from unavailable formal Stage recommendations", async () => {
    const symbol="HK.00001";
    const action={type:"WATCH",text:"核对公司披露的交付节点与实际兑现，不把预期当作已实现。",
      evidence_ids:[],proposition_ids:[],assertion_type:"RESEARCH_CONDITION_NOT_OBSERVED_FACT",
      orders_sent:false,supporting_quotes:[]};
    workspaceMocks.request.mockResolvedValue({
      ...workspaceBase,
      focus_symbols:[symbol],
      stocks:[{symbol,name:"研究标的",is_focus:true,priority_basis:{group:"COMPANY_RESEARCH"},
        why_watch:["原文研究命题：公司披露的交付节点"],evidence:[],material_relations:[],
        plan:{actions:[action,{...action,type:"WAIT",text:"事实未核实前保持观察。"}],trigger_price:null},
        stage_observation:null,close_observation:null}],
      summary:{stock_count:1,relation_count:0,theme_count:0,reused_material_count:0,
        formal_recommendation_count:0,focus_count:1},
      stage_read_timing:{artifact_status:"CANNOT_CONFIRM",execution_state:"NOT_DUE",
        source_reasons:["SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID"]},
      plan_product:{status:"CURRENT",run_id:"manual-run"},
      workspace_plan_attempt:{state:"PARTIAL",run_id:"manual-run",execution_kind:"MANUAL_REFRESH"},
    });
    const host=document.createElement("div");document.body.append(host);
    const dispose=mountCatalystObservations(host,"20260921");
    await waitFor(()=>expect(host.textContent).toContain("次日重点研究名单（1）"));
    const rendered=host.textContent||"";
    expect(rendered).toContain("研究标的 · HK.00001");
    expect(rendered).toContain("原文研究命题：公司披露的交付节点");
    expect(rendered).toContain("WATCH：核对公司披露的交付节点与实际兑现");
    expect(rendered).toContain("WAIT：事实未核实前保持观察。");
    expect(rendered).toContain("正式 Stage 推荐：0只");
    expect(rendered).toContain("选择输入未核实");
    expect(rendered).toContain("0只不表示Stage成功扫描后为空");
    expect(host.querySelectorAll(".manager-research-focus-card")).toHaveLength(1);
    dispose();
  });

  it("shows late close recapture as a separate observation and cutoff-aware plan context", async () => {
    workspaceMocks.request.mockResolvedValue({
      ...workspaceBase,
      close_recapture_evidence: {
        schema_version:"v4.manager_close_recapture.v1",status:"PARTIAL",target_trade_date:"20260928",
        source_trade_date:"20260928",capture_mode:"LATE_OBSERVATION",
        observation_type:"PYTDX_EXHQ_MINUTE_STAGE_OBSERVATION",market:"HK_CONNECT",
        source:{provider:"pytdx_exhq",source_id:"pytdx"},
        pool:{trade_date:"20260928",signal_date:"20260928",source_id:"HK_CONNECT_D1_TOP100_0_2",
          run_id:"20260928-hk-connect-d1-top100-0-2-ef16f451b21c",artifact_sha256:"a".repeat(64),
          manifest_sha256:"b".repeat(64),row_count:100},
        bar_window:{stage_id:"STAGE_1545_1555",start_at:"2026-09-28T15:45:01+08:00",
          max_at:"2026-09-28T15:55:05+08:00",observed_at_min:"2026-09-28T15:45:01+08:00",
          observed_at_max:"2026-09-28T15:55:05+08:00"},
        request:{started_at:"2026-09-28T23:10:00+08:00",captured_at:"2026-09-28T23:10:02+08:00",
          available_at:"2026-09-28T23:10:04+08:00"},
        coverage:{eligible_count:100,requested_count:100,completed_count:100,observed_count:87,no_data_count:13,ratio:0.87},
        snapshot:{artifact_ref:"workbench_research/20260928/close_recapture_snapshot.json",
          sha256:"c".repeat(64),row_count:87},
        candidate_overlay:{artifact_ref:"workbench_research/20260928/close_recapture_candidates.json",
          sha256:"d".repeat(64),count:1,rows:[{symbol:"HK.00001",name:"测试标的",source_trade_date:"20260928",
            observed_at:"2026-09-28T15:55:05+08:00",available_at:"2026-09-28T23:10:04+08:00",
            open_price:119,high_price:124,low_price:118,last_price:123.4,prev_close_price:120,
            turnover:9876,volume:100,turnover_currency:"UNKNOWN",turnover_unit:"UNKNOWN",
            candidate_status:"OBSERVATION_ONLY"}]},
        cannot_confirm: [],
      },
      planning_close_recapture_evidence: {
        plan_trade_date:"20260929",research_cutoff:"2026-09-29T09:20:00+08:00",
        source_trade_date:"20260928",available_at:"2026-09-28T23:10:04+08:00",
        planner_availability:"AVAILABLE_BEFORE_CUTOFF",candidates:[{symbol:"HK.00001",name:"测试标的",
          observed_at:"2026-09-28T15:55:05+08:00",available_at:"2026-09-28T23:10:04+08:00",
          observation_mode:"CLOSE_RECAPTURE"}],
      },
      lanes:[...workspaceBase.lanes,{...makeLane("CLOSE"),lane:"CLOSE_RECAPTURE"}],
    });
    const host=document.createElement("div");document.body.append(host);
    const dispose=mountCatalystObservations(host,"20260928");
    await waitFor(()=>expect(host.textContent).toContain("盘后补采，不代表15:30时点结果；仅研究观察。"));
    const rendered=host.textContent||"";
    expect(rendered).toContain("本次计划关联的前一交易日盘后观察");
    expect(rendered).toContain("计划截止前已可用；是否消费仍按原owner/PIT校验。");
    expect(rendered).toContain("pytdx_exhq（pytdx）");
    expect(rendered).toContain("HK_CONNECT_D1_TOP100_0_2");
    expect(rendered).toContain("20260928-hk-connect-d1-top100-0-2-ef16f451b21c");
    expect(rendered).toContain("STAGE_1545_1555");
    expect(rendered).toContain("eligible/requested/completed/observed/no-data：100/100/100/87/13");
    expect(rendered).toContain("最新 123.4");
    expect(rendered).toContain("bar观察时间 2026-09-28T15:55:05+08:00");
    expect(rendered).toContain("候选观察 workbench_research/20260928/close_recapture_candidates.json");
    expect(rendered).toContain("不是正式收盘价");
    expect(host.querySelectorAll(".decision-stock")).toHaveLength(0);
    dispose();
  });

  it("merges only identical mapping summaries while retaining every raw relation", () => {
    const theme = {
      theme: "AI_DRUG_RND",
      mappings: [
        {
          symbol: "HK.02315",
          relationship_type: "INDUSTRY_INFERENCE",
          reason: "同一关系机制",
          mapping_admission: { mechanism: "同一关系机制", reason_code: "DUAL_EVIDENCE", scope: "COMPANY_THEME" },
          issuer_quote: "同一本股原文",
          theme_quote: "同一主题原文",
          window_status: "CURRENT_WINDOW_RESEARCH",
          source_refs: [{ payload_sha256: "issuer-a" }],
        },
        {
          symbol: "HK.02315",
          relationship_type: "INDUSTRY_INFERENCE",
          reason: "同一关系机制",
          mapping_admission: { mechanism: "同一关系机制", reason_code: "DUAL_EVIDENCE", scope: "COMPANY_THEME" },
          issuer_quote: "同一本股原文",
          theme_quote: "同一主题原文",
          window_status: "CURRENT_WINDOW_RESEARCH",
          source_refs: [{ payload_sha256: "issuer-b" }],
        },
        {
          symbol: "HK.02315",
          relationship_type: "INDUSTRY_INFERENCE",
          reason: "同一关系机制",
          mapping_admission: { mechanism: "同一关系机制", reason_code: "DUAL_EVIDENCE", scope: "COMPANY_THEME" },
          issuer_quote: "另一条实际本股原文",
          theme_quote: "同一主题原文",
          window_status: "CURRENT_WINDOW_RESEARCH",
          source_refs: [{ payload_sha256: "issuer-c" }],
        },
        {
          symbol: "HK.02315",
          relationship_type: "INDUSTRY_INFERENCE",
          reason: "同一关系机制",
          mapping_admission: { mechanism: "同一关系机制", reason_code: "DUAL_EVIDENCE", scope: "COMPANY_THEME" },
          issuer_quote: "同一本股原文",
          theme_quote: "同一主题原文",
          window_status: "BACKGROUND_REFERENCE",
          source_refs: [{ payload_sha256: "issuer-d" }],
        },
      ],
    };
    const groups = groupThemeMappings(theme);
    expect(groups.map(group => group.mappings.length).sort()).toEqual([1, 1, 2]);
    expect(groups.find(group => group.mappings.length === 2)?.mappings.map(row => row.source_refs)).toEqual([
      [{ payload_sha256: "issuer-a" }],
      [{ payload_sha256: "issuer-b" }],
    ]);
    expect(groups.some(group => group.representative.issuer_quote === "另一条实际本股原文")).toBe(true);
    expect(groups.some(group => group.representative.window_status === "BACKGROUND_REFERENCE")).toBe(true);
  });

  it("keeps the workspace read alive through the finite 180-second UI deadline", async () => {
    vi.useFakeTimers();
    const pending = new Promise<ManagerWorkspace>(() => undefined);
    workspaceMocks.request.mockReturnValue(pending);
    const host = document.createElement("div");
    document.body.append(host);
    const dispose = mountCatalystObservations(host, "20260921");
    await vi.advanceTimersByTimeAsync(30_000);
    const signal = workspaceMocks.request.mock.calls[0][1] as AbortSignal;
    expect(signal.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(149_999);
    expect(signal.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(signal.aborted).toBe(true);
    dispose();
  });

  it("reuses the validated refresh response instead of issuing a second same-date GET", async () => {
    workspaceMocks.request.mockResolvedValue(workspaceBase);
    workspaceMocks.refresh.mockResolvedValue(workspaceBase);
    const host = document.createElement("div");
    document.body.append(host);
    const dispose = mountCatalystObservations(host, "20260921");
    await waitFor(() => expect(workspaceMocks.request).toHaveBeenCalledTimes(1));
    workspaceMocks.request.mockClear();
    await fireEvent.click(host.querySelector("button:nth-of-type(2)") as HTMLButtonElement);
    await waitFor(() => expect(workspaceMocks.refresh).toHaveBeenCalledTimes(1));
    expect(workspaceMocks.request).not.toHaveBeenCalled();
    dispose();
  });

  it("renders the actual Eastmoney owner workspace readback instead of reporting a network failure", async () => {
    const raw = JSON.parse(readFileSync(
      "/Users/lexi/Desktop/学习/agents调试/EASTMONEY_HK_ANN_20260929/integration/workspace_after.json",
      "utf8",
    ));
    workspaceMocks.request.mockImplementation(async () => validateManagerWorkspace(raw, "20260929"));
    const host = document.createElement("div");
    document.body.append(host);
    const dispose = mountCatalystObservations(host, "20260929");

    await waitFor(() => expect(host.querySelector(".manager-catalyst-observations")?.getAttribute("data-read-state")).toBe("READY"));
    const rendered = host.textContent || "";
    expect(rendered).toContain("东方财富港股公告");
    expect(rendered).toContain("HK.00700 腾讯控股");
    expect(rendered).toContain("AN202609281829962076");
    expect(rendered).not.toContain("网络连接或响应读取失败");
    const bodyPages = host.querySelectorAll("[data-eastmoney-body-page] pre");
    expect(bodyPages).toHaveLength(4);
    expect([...bodyPages].reduce((total, page) => total + (page.textContent || "").length, 0)).toBeGreaterThan(19000);
    dispose();
  });
});
