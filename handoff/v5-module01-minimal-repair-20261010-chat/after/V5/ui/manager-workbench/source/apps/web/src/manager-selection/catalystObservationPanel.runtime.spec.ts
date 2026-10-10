import { fireEvent, waitFor, within } from "@testing-library/vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const workspaceMocks = vi.hoisted(() => ({
  request: vi.fn(),
  refresh: vi.fn(),
}));
const analysisMocks = vi.hoisted(() => ({ request: vi.fn() }));

vi.mock("../api/managerWorkspace.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/managerWorkspace.js")>()),
  requestManagerWorkspace: workspaceMocks.request,
  refreshManagerWorkspace: workspaceMocks.refresh,
}));
vi.mock("../api/managerAnnouncementAnalysis.js", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/managerAnnouncementAnalysis.js")>()),
  requestManagerAnnouncementAnalysis: analysisMocks.request,
}));

import { groupThemeMappings, mountCatalystObservations } from "./catalystObservationPanel";
import { validateManagerWorkspace, type JsonObject, type ManagerWorkspace, type ReboundScreen } from "../api/managerWorkspace";
import { testFlags, workspaceFixture } from "./dailyChannels.testHelper";

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

const dailyReview=(date:string,count=1)=>({
  RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false,
  schema_version:"v4.manager_research.announcement_review.v1",target_trade_date:date,
  daily_publication_date:date,publication_timezone:"Asia/Hong_Kong",status:"PARTIAL",count_known:true,
  official_documents:Array.from({length:count},(_,index)=>({RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false,
    symbol:`HK.${String(index+1).padStart(5,'0')}`,name:`示例公司${index+1}`,title:`当天公告${index+1}`,
    event_id:`${"c".repeat(56)}${index.toString(16).padStart(8,'0')}`,target_trade_date:date,
    source_url:`https://www1.hkexnews.hk/listedco/listconews/sehk/${date.slice(0,4)}/${date.slice(4,8)}/notice-${index+1}.pdf`,
    published_at:`${date.slice(0,4)}-${date.slice(4,6)}-${date.slice(6,8)}T10:00:00+08:00`,
    available_at:`${date.slice(0,4)}-${date.slice(4,6)}-${date.slice(6,8)}T10:01:00+08:00`,
    retrieved_at:`${date.slice(0,4)}-${date.slice(4,6)}-${date.slice(6,8)}T10:02:00+08:00`,
    query_cutoff:`${date.slice(0,4)}-${date.slice(4,6)}-${date.slice(6,8)}T23:00:00+08:00`,
    body_status:"BODY_UNREAD",document_sha256:"d".repeat(64),source_refs:[]})),
  coverage:{publication_date:date,observed_document_count:count,observed_count_is_not_market_total:true,
    source_coverage_cutoff:`${date.slice(0,4)}-${date.slice(4,6)}-${date.slice(6,8)}T23:00:00+08:00`,
    queried_issuer_count:3,successfully_observed_issuer_count:3,failed_issuers:[],pending_issuers:[],
    directory_exhaustion:"UNVERIFIED",all_official_announcements_captured:false,source_products:[]},
  gaps:["OFFICIAL_DIRECTORY_SERVER_PAGINATION_EXHAUSTION_UNVERIFIED"],capture_runs:[],
  retained_cross_day:{counts_by_publication_date:{"20260930":342},source_products:[]},
});

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

const readPinnedManualObservationFixture = (name: "close_recapture.json" | "close_recapture.candidates.json"): JsonObject => {
  const fixtureRoot = process.env.V5_MANUAL_OBSERVATION_FIXTURES || resolve(dirname(fileURLToPath(import.meta.url)), "../../../../tests/fixtures/manager_current_observation_20261002");
  const bindingBytes = readFileSync(resolve(fixtureRoot, "FIXTURE_BINDING.json"));
  expect(createHash('sha256').update(bindingBytes).digest('hex')).toBe('9e5fd49a35fa70aa8d2a85b4b06547fecaae5af9f9248fbffa99e5aa48b28c0c');
  const binding = JSON.parse(bindingBytes.toString('utf8'));
  const bytes = readFileSync(resolve(fixtureRoot, name));
  expect(createHash("sha256").update(bytes).digest("hex")).toBe(binding.files[name].sha256);
  return JSON.parse(bytes.toString("utf8")) as JsonObject;
};

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  analysisMocks.request.mockReset();
  window.history.replaceState({},"","/");
  document.body.replaceChildren();
});

beforeEach(() => {
  analysisMocks.request.mockImplementation(async(targetDate:string,publicationDate:string|undefined)=>({
    schema_version:"v4.manager_research.eastmoney_hk_announcement_analysis_read.v1",
    target_trade_date:targetDate,publication_date:publicationDate
      ?`${publicationDate.slice(0,4)}-${publicationDate.slice(4,6)}-${publicationDate.slice(6,8)}`
      :targetDate==="20260930"?"2026-09-29":"2026-09-30",
    date_selection_basis:publicationDate?"EXPLICIT":"PREVIOUS_HK_TRADING_SESSION",
    source_catalog:{status:"NOT_RUN",readback_status:"NOT_RUN",directory_record_count:null},
    analysis:{status:"NOT_IMPORTED",summary:null,records:[],gaps:["ANNOUNCEMENT_ANALYSIS_NOT_IMPORTED"]},
  }));
  vi.stubGlobal("fetch",vi.fn(async (input:RequestInfo|URL)=>{
    const url=String(input);const date=new URL(url,"http://localhost").searchParams.get("date")||"20260921";
    return {ok:true,status:200,json:async()=>dailyReview(date)} as Response;
  }));
});

describe("catalyst workspace runtime boundary", () => {
  it("mounts optional panel summary without replacing the formal screen or refreshing a plan", async () => {
    const value={...workspaceWithScreen(),rebound_panel_observation:{eligible_screen:null,formal_status:"CANNOT_CONFIRM",
      signal_date:"20261008",target_date:"20261009",observed_at:"2026-10-09T20:53:19+08:00",reason_codes:[],
      row_summary:{observed_rows:695,numeric_input_incomplete:695,missing_history_dates:["20261005","20261006","20261007"],
        native_comparison_counts:{close_le_prior60_high_times_0_8:{true:0,false:0,unknown:695},current_to_previous5_ge_1_5:{true:0,false:0,unknown:695}}}}};
    workspaceMocks.request.mockResolvedValue(value);
    const host=document.createElement("div");document.body.append(host);
    const dispose=mountCatalystObservations(host,"20260921");
    try {
      await waitFor(()=>expect(host.querySelector('[aria-label="原面板数值观察"]')?.textContent).toContain("观察记录 695 条"));
      expect(host.querySelector('[aria-label="原面板数值观察"]')?.textContent).toContain("不是候选数");
      expect(host.querySelector('[aria-label="REBOUND_V3量价筛选"]')).not.toBeNull();
      expect(workspaceMocks.refresh).not.toHaveBeenCalled();
    } finally {dispose();}
  });

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
    const strategy=host.querySelector('details[data-rebound-strategy]') as HTMLDetailsElement;
    expect(strategy.open).toBe(false);
    expect(strategy.querySelector("summary")?.textContent).toContain("严格1 · 近条件1 · 待核0");
    const rendered = host.textContent || "";
    expect(rendered).toContain("成交额 15855358 HKD（观察值）");
    expect(rendered).toContain("收盘较当日低点反弹 1.23%（观察值）");
    expect(rendered).toContain("成交额 250000000 HKD（观察值）");
    expect(rendered).not.toContain(">1亿");
    expect(rendered).not.toContain("≤2亿");
    expect(rendered).not.toContain("反弹≥3%");
    dispose();
  });

  it("collapses pending history into complete reason counts while keeping every card expandable", async () => {
    const pending=[
      {...strictCard,code:"HK.00001",name:"待核公司一",target_monday:"20260921",
        history_status:"PARTIAL_UNKNOWN",history_unknown_reasons:"REBOUND_PRIOR60_HIGH_INCOMPLETE"},
      {...strictCard,code:"HK.00002",name:"待核公司二",target_monday:"20260921",
        history_status:"PARTIAL_UNKNOWN",history_unknown_reasons:"REBOUND_PRIOR60_HIGH_INCOMPLETE"},
      {...strictCard,code:"HK.00003",name:"待核公司三",target_monday:"20260921",
        history_status:"PARTIAL_UNKNOWN",history_unknown_reasons:"REBOUND_PREVIOUS5_VOLUME_INCOMPLETE"},
    ];
    workspaceMocks.request.mockResolvedValue({
      ...workspaceWithScreen(),
      market_screen:{...twoGateScreen,status:"READY_WITH_GAPS",pending,
        coverage:{...twoGateScreen.coverage,input_candidate_count:5,history_complete_count:2,
          history_pending_count:3}},
    });
    const host=document.createElement("div");document.body.append(host);
    const dispose=mountCatalystObservations(host,"20260921");
    await waitFor(()=>expect(host.querySelector("details.manager-rebound-pending-history")).not.toBeNull());
    const pendingGroup=host.querySelector("details.manager-rebound-pending-history") as HTMLDetailsElement;
    expect(pendingGroup.open).toBe(false);
    expect(pendingGroup.querySelector("summary")?.textContent).toBe(
      "待核历史（3） · REBOUND_PRIOR60_HIGH_INCOMPLETE 2只；REBOUND_PREVIOUS5_VOLUME_INCOMPLETE 1只");
    expect(pendingGroup.querySelectorAll(":scope > .manager-catalyst-card")).toHaveLength(0);
    await fireEvent.click(pendingGroup.querySelector("summary") as HTMLElement);
    expect(pendingGroup.open).toBe(true);
    await waitFor(()=>expect(pendingGroup.querySelectorAll(":scope > .manager-catalyst-card")).toHaveLength(3));
    expect(pendingGroup.textContent).toContain("待核公司一 · HK.00001");
    expect(pendingGroup.textContent).toContain("待核公司三 · HK.00003");
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

  it("loads the page publication date independently from plan_date", async () => {
    workspaceMocks.request.mockResolvedValue(workspaceBase);
    window.history.replaceState({},"","/?date=20261001&plan_date=20261002");
    const host=document.createElement("div");document.body.append(host);
    const fetchMock=globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    const dispose=mountCatalystObservations(host,"20261002");
    await waitFor(()=>expect(host.textContent).toContain("按公告日读取的 HKEX 官方目录"));
    await waitFor(()=>expect(host.textContent).toContain("20261001（Asia/Hong_Kong）"));
    const firstUrl=String(fetchMock.mock.calls[0][0]);
    expect(firstUrl).toBe("/api/v4/manager/research/announcements?date=20261001");
    expect(host.textContent).toContain("1 条已观察公告");
    expect(host.textContent).toContain("来源查询覆盖截止：2026-10-01T23:00:00+08:00");
    expect(host.textContent).toContain("342");

    const planDate=host.querySelector('input[aria-label="计划目标日"]') as HTMLInputElement;
    planDate.value="2026-10-03";
    await fireEvent.change(planDate);
    await waitFor(()=>expect(workspaceMocks.request).toHaveBeenCalledWith("20261003",expect.any(AbortSignal),"auto"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const url=new URL(window.location.href);
    expect(url.searchParams.get("date")).toBe("20261001");
    expect(url.searchParams.get("plan_date")).toBe("20261003");
    expect(host.querySelector("[data-announcement-date]")?.getAttribute("data-announcement-date")).toBe("20261001");
    dispose();
  });

  it("uses the previous-session default and lets the independent announcement date be selected", async()=>{
    workspaceMocks.request.mockResolvedValue(workspaceBase);
    window.history.replaceState({},"","/?date=20260930&plan_date=20260930");
    const host=document.createElement("div");document.body.append(host);
    const dispose=mountCatalystObservations(host,"20260930");
    await waitFor(()=>expect(analysisMocks.request).toHaveBeenCalledWith(
      "20260930",undefined,expect.any(AbortSignal)));
    await waitFor(()=>expect(host.querySelector<HTMLInputElement>('input[aria-label="公告日期"]')?.value)
      .toBe("2026-09-29"));
    const picker=host.querySelector<HTMLInputElement>('input[aria-label="公告日期"]')!;
    picker.value="2026-09-30";await fireEvent.change(picker);
    await waitFor(()=>expect(analysisMocks.request).toHaveBeenLastCalledWith(
      "20260930","20260930",expect.any(AbortSignal)));
    expect(new URL(window.location.href).searchParams.get("announcement_date")).toBe("20260930");
    expect(host.querySelector("[aria-label='历史公告解析成果']")?.textContent).toContain("手动选择");
    dispose();
  });

  it("reloads the official review for a changed analysis date and ignores its late prior-date response", async()=>{
    workspaceMocks.request.mockResolvedValue(workspaceBase);
    window.history.replaceState({},"","/?date=20261001&plan_date=20261002");
    const fetchMock=globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    const replies=new Map<string,(value:ReturnType<typeof dailyReview>)=>void>();
    const signals=new Map<string,AbortSignal|undefined>();
    fetchMock.mockImplementation((input:RequestInfo|URL,init?:RequestInit)=>{
      const url=new URL(String(input),"http://localhost");
      const selectedDate=url.searchParams.get("date")||"20260921";
      signals.set(selectedDate,init?.signal as AbortSignal|undefined);
      return new Promise(resolve=>replies.set(selectedDate,value=>resolve({
        ok:true,status:200,json:async()=>value,
      } as Response)));
    });
    const host=document.createElement("div");document.body.append(host);
    const dispose=mountCatalystObservations(host,"20261002");
    await waitFor(()=>expect(replies.has("20261001")).toBe(true));
    const picker=host.querySelector<HTMLInputElement>('input[aria-label="公告日期"]')!;
    picker.value="2026-10-02";
    await fireEvent.change(picker);

    await waitFor(()=>expect(replies.has("20261002")).toBe(true));
    expect(fetchMock).toHaveBeenCalledWith("/api/v4/manager/research/announcements?date=20261002",
      expect.objectContaining({signal:expect.any(AbortSignal)}));
    expect(signals.get("20261001")?.aborted).toBe(true);
    expect(host.querySelector("[data-announcement-date]")?.getAttribute("data-announcement-date")).toBe("20261002");
    expect(workspaceMocks.request).toHaveBeenLastCalledWith("20261002",expect.any(AbortSignal),"auto",
      { plan_date:"20261002", selection_date:"20261001", announcement_date:"20261002" });
    expect(host.querySelector("[data-daily-bindings]")?.textContent).toContain("公告日 20261002 · 计划日 20261002");
    expect(analysisMocks.request).toHaveBeenLastCalledWith("20261002","20261002",expect.any(AbortSignal));

    replies.get("20261002")?.(dailyReview("20261002",2));
    await waitFor(()=>expect(host.textContent).toContain("2 条已观察公告"));
    replies.get("20261001")?.(dailyReview("20261001",7));
    await Promise.resolve();
    expect(host.querySelector("[data-announcement-date]")?.getAttribute("data-announcement-date")).toBe("20261002");
    expect(host.textContent).toContain("2 条已观察公告");
    expect(host.textContent).not.toContain("7 条已观察公告");
    dispose();
  });

  it("ignores a late analysis response from the previous plan date",async()=>{
    workspaceMocks.request.mockImplementation(()=>new Promise(()=>{}));
    const replies=new Map<string,(value:Record<string,unknown>)=>void>();
    analysisMocks.request.mockImplementation((targetDate:string)=>new Promise(resolve=>
      replies.set(targetDate,value=>resolve(value))));
    window.history.replaceState({},"","/?plan_date=20260921");
    const host=document.createElement("div");document.body.append(host);
    const dispose=mountCatalystObservations(host,"20260921");
    await waitFor(()=>expect(replies.has("20260921")).toBe(true));
    const planDate=host.querySelector<HTMLInputElement>('input[aria-label="计划目标日"]')!;
    planDate.value="2026-09-22";await fireEvent.change(planDate);
    await waitFor(()=>expect(replies.has("20260922")).toBe(true));
    const makeReply=(target:string,pub:string)=>({
      schema_version:"v4.manager_research.eastmoney_hk_announcement_analysis_read.v1",
      target_trade_date:target,publication_date:pub,date_selection_basis:"PREVIOUS_HK_TRADING_SESSION",
      source_catalog:{status:"NOT_RUN",readback_status:"NOT_RUN",directory_record_count:null},
      analysis:{status:"NOT_IMPORTED",summary:null,records:[],gaps:["ANNOUNCEMENT_ANALYSIS_NOT_IMPORTED"]},
    });
    replies.get("20260922")?.(makeReply("20260922","2026-09-21"));
    await waitFor(()=>expect(host.querySelector("[aria-label='历史公告解析成果']")?.textContent)
      .toContain("2026-09-21（计划日前一 HK 交易日）"));
    replies.get("20260921")?.(makeReply("20260921","2026-09-20"));
    await Promise.resolve();
    expect(host.querySelector("[aria-label='历史公告解析成果']")?.textContent)
      .toContain("2026-09-21（计划日前一 HK 交易日）");
    expect(host.querySelector("[aria-label='历史公告解析成果']")?.textContent)
      .not.toContain("2026-09-20（计划日前一 HK 交易日）");
    dispose();
  });

  it("shows the selected HK calendar-day count from the owner review", async () => {
    workspaceMocks.request.mockResolvedValue(workspaceBase);
    const fetchMock=globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockImplementation(async (input:RequestInfo|URL)=>{
      const date=new URL(String(input),"http://localhost").searchParams.get("date")||"20260921";
      return {ok:true,status:200,json:async()=>dailyReview(date,date==="20261002"?243:1)} as Response;
    });
    window.history.replaceState({},"","/?date=20261002&plan_date=20261003");
    const host=document.createElement("div");document.body.append(host);
    const dispose=mountCatalystObservations(host,"20261003");
    await waitFor(()=>expect(host.textContent).toContain("243 条已观察公告"));
    const summary=host.querySelector('details[data-daily-announcement-documents] summary');
    expect(summary?.textContent).toContain("展开 243 条已观察 HKEX 公告");
    expect(host.textContent).not.toContain("797 条已观察公告");
    expect(host.querySelector("[data-announcement-date]")?.getAttribute("data-announcement-date")).toBe("20261002");
    dispose();
  });

  it("submits an incremental announcement update for the selected publication day", async () => {
    workspaceMocks.request.mockResolvedValue(workspaceBase);
    window.history.replaceState({},"","/?date=20261001&plan_date=20261002");
    const host=document.createElement("div");document.body.append(host);
    const fetchMock=globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    const dispose=mountCatalystObservations(host,"20261002");
    await waitFor(()=>expect(fetchMock).toHaveBeenCalledTimes(1));
    const button=host.querySelector('[data-refresh-announcement-date="20261001"]') as HTMLButtonElement;
    expect(button).toBeTruthy();
    await fireEvent.click(button);
    await waitFor(()=>expect(fetchMock).toHaveBeenCalledTimes(2));
    const [url,init]=fetchMock.mock.calls[1] as [string,RequestInit];
    expect(url).toBe("/api/v4/manager/research/announcements/refresh?date=20261001");
    expect(init.method).toBe("POST");
    await waitFor(()=>expect(host.textContent).toContain("20261001（Asia/Hong_Kong）"));
    expect(host.querySelector("[data-announcement-date]")?.getAttribute("data-announcement-date")).toBe("20261001");
    expect(new URL(window.location.href).searchParams.get("plan_date")).toBe("20261002");
    const nextButton=host.querySelector('[data-refresh-announcement-date="20261001"]') as HTMLButtonElement;
    expect(nextButton.disabled).toBe(false);
    dispose();
  });

  it("reports a failed daily update with unknown coverage instead of retaining a stale count", async () => {
    workspaceMocks.request.mockResolvedValue(workspaceBase);
    const fetchMock=globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockImplementation(async (input:RequestInfo|URL)=>{
      if(String(input).includes("/announcements/refresh?"))return {ok:false,status:409} as Response;
      const date=new URL(String(input),"http://localhost").searchParams.get("date")||"20260921";
      return {ok:true,status:200,json:async()=>dailyReview(date)} as Response;
    });
    window.history.replaceState({},"","/?date=20261001&plan_date=20261002");
    const host=document.createElement("div");document.body.append(host);
    const dispose=mountCatalystObservations(host,"20261002");
    await waitFor(()=>expect(host.textContent).toContain("1 条已观察公告"));
    await fireEvent.click(host.querySelector('[data-refresh-announcement-date="20261001"]') as HTMLElement);
    await waitFor(()=>expect(host.textContent).toContain("公告增量更新失败，覆盖数量未知（ANNOUNCEMENT_REFRESH_HTTP_409）"));
    expect(host.textContent).toContain("覆盖数量未知，不是0条");
    expect(host.textContent).not.toContain("1 条已观察公告");
    dispose();
  });

  it("ignores a late prior-day response after the page remounts on a new selected date", async () => {
    workspaceMocks.request.mockResolvedValue(workspaceBase);
    const fetchMock=globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    const replies=new Map<string,(response:Response)=>void>();
    fetchMock.mockImplementation((input:RequestInfo|URL)=>{
      const date=new URL(String(input),"http://localhost").searchParams.get("date")||"20260921";
      return new Promise(resolve=>replies.set(date,response=>resolve(response)));
    });
    const host=document.createElement("div");document.body.append(host);
    window.history.replaceState({},"","/?date=20261001&plan_date=20261002");
    const disposeOld=mountCatalystObservations(host,"20261002");
    await waitFor(()=>expect(replies.has("20261001")).toBe(true));
    disposeOld();
    window.history.replaceState({},"","/?date=20261002&plan_date=20261002");
    const disposeNew=mountCatalystObservations(host,"20261002");
    await waitFor(()=>expect(replies.has("20261002")).toBe(true));
    replies.get("20261002")?.({ok:true,status:200,json:async()=>dailyReview("20261002")} as Response);
    await waitFor(()=>expect(host.textContent).toContain("20261002（Asia/Hong_Kong）"));
    replies.get("20261001")?.({ok:true,status:200,json:async()=>dailyReview("20261001")} as Response);
    await Promise.resolve();
    expect(host.textContent).toContain("20261002（Asia/Hong_Kong）");
    expect(host.textContent).not.toContain("20261001（Asia/Hong_Kong）");
    disposeNew();
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

  it("keeps the requested-day manual HK observation compact until all 100 rows are expanded", async () => {
    const payload = readPinnedManualObservationFixture("close_recapture.json");
    const overlay = readPinnedManualObservationFixture("close_recapture.candidates.json");
    const candidateOverlay = payload.candidate_overlay as JsonObject;
    const observedRows = overlay.rows as JsonObject[];
    expect(observedRows).toHaveLength(100);
    const evidence = {
      ...payload,
      candidate_overlay: { ...candidateOverlay, rows: observedRows },
    } as JsonObject;
    const planningEvidence = {
      plan_trade_date: "20261002", research_cutoff: "2026-10-02T09:20:00+08:00",
      source_trade_date: "20260930", available_at: "2026-09-30T23:10:00+08:00",
      planner_availability: "CANNOT_CONFIRM", candidates: [],
    };
    workspaceMocks.request.mockResolvedValue({
      ...workspaceBase,
      close_recapture_evidence: evidence,
      planning_close_recapture_evidence: planningEvidence,
    });

    const host = document.createElement("div");
    document.body.append(host);
    const dispose = mountCatalystObservations(host, "20261002");
    await waitFor(() => expect(host.textContent).toContain("可展示观察行 100/100"));

    const sections = [...host.querySelectorAll(".manager-close-recapture-evidence")];
    const manual = sections[0] as HTMLElement;
    const priorPlanContext = sections[1] as HTMLElement;
    expect(manual.querySelector("h4")?.textContent).toBe("请求日独立港股证券盘后观察");
    expect(manual.textContent).toContain("状态 READY · 来源日 20261002 · 计划日 20261008");
    expect(manual.textContent).toContain("真实 available_at 2026-10-02T17:55:22.905209+08:00");
    expect(manual.textContent).toContain("HK_SECURITIES_SESSION_MINUTE_OBSERVATION");
    expect(manual.textContent).toContain("来源产物市场标签 HK_CONNECT；实际观察市场 HK_SECURITIES");
    expect(manual.textContent).toContain("不表示港股通可交易资格或官方收盘价");
    expect(priorPlanContext.textContent).toContain("来源日 20260930");

    const rowDetails = manual.querySelector("details[data-observation-rows='true']") as HTMLDetailsElement;
    expect(rowDetails.open).toBe(false);
    expect(rowDetails.querySelectorAll(":scope > .manager-close-recapture-candidate")).toHaveLength(0);
    expect(host.querySelectorAll(".decision-stock")).toHaveLength(0);

    await fireEvent.click(rowDetails.querySelector("summary") as HTMLElement);
    await waitFor(() => expect(rowDetails.querySelectorAll(":scope > .manager-close-recapture-candidate")).toHaveLength(100));
    expect([...rowDetails.querySelectorAll<HTMLElement>(":scope > .manager-close-recapture-candidate")]
      .map(card => card.dataset.symbol)).toEqual(observedRows.map(row => row.symbol));
    expect(rowDetails.textContent).toContain("HK.02723");
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
    window.history.replaceState({}, "", "/?date=20260921&view=dynamic");
    const initial = workspaceFixture({ plan_date: "20260921", selection_date: "20260921", announcement_date: "20260921" }, false);
    // Keep this legacy no-projection caller, with a complete synthetic owner
    // response admitted by the real API client instead of a product mock.
    const saved = structuredClone(initial);
    saved.plan_product = { status: "CURRENT", consumed: true, run_id: "1".repeat(32), sha256: "2".repeat(64),
      generated_at: "2026-10-10T03:04:05+00:00", execution_kind: "MANUAL_REFRESH",
      original_owner: "ManagerResearchJobService.refresh_workspace_plan" };
    saved.workspace_plan_attempt = { ...testFlags, schema_version: "v4.manager_research.workspace_attempt.v1",
      sha256: "5".repeat(64), state: "PARTIAL", target_trade_date: "20260921",
      run_id: "1".repeat(32), input_identity: saved.input_identity, execution_kind: "MANUAL_REFRESH",
      owner: "ManagerResearchJobService.refresh_workspace_plan", failure_reasons: ["SYNTHETIC_SCOPE_GAP"],
      started_at: "2026-10-10T03:04:00+00:00", finished_at: "2026-10-10T03:04:06+00:00" };
    const actualApi = await vi.importActual<typeof import("../api/managerWorkspace.js")>("../api/managerWorkspace.js");
    workspaceMocks.request.mockImplementation(actualApi.requestManagerWorkspace);
    workspaceMocks.refresh.mockImplementation(actualApi.refreshManagerWorkspace);
    const methods: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (!String(input).includes("/workspace")) return { ok: false, status: 503 } as Response;
      methods.push(init?.method ?? "GET");
      return new Response(JSON.stringify(init?.method === "POST" ? saved : initial), { status: 200 });
    }));
    const host = document.createElement("div");
    document.body.append(host);
    const dispose = mountCatalystObservations(host, "20260921");
    await waitFor(() => expect(workspaceMocks.request).toHaveBeenCalledTimes(1));
    workspaceMocks.request.mockClear();
    const planActions = [...host.querySelectorAll<HTMLDetailsElement>("details")]
      .find(node => node.querySelector(":scope > summary")?.textContent === "计划操作")!;
    expect(planActions).toBeDefined();
    planActions.open = true;
    const generate = within(planActions).getByRole("button", { name: "用既有材料生成计划" }) as HTMLButtonElement;
    await waitFor(() => expect(generate.disabled).toBe(false));
    await fireEvent.click(generate);
    await waitFor(() => expect(workspaceMocks.refresh).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(host.querySelector(".manager-catalyst-observations")?.getAttribute("data-generation-state")).toBe("VERIFIED"));
    expect(workspaceMocks.request).not.toHaveBeenCalled();
    expect(methods).toEqual(["GET", "POST"]);
    dispose();
  });

  it("renders Eastmoney evidence from the selected-date daily owner review", async () => {
    const raw = JSON.parse(readFileSync(
      process.env.V5_EASTMONEY_WORKSPACE_FIXTURE || "/Users/lexi/Desktop/学习/agents调试/EASTMONEY_HK_ANN_20260929/integration/workspace_after.json",
      "utf8",
    ));
    workspaceMocks.request.mockImplementation(async () => validateManagerWorkspace(raw, "20260929"));
    const docs=raw.announcement_observation.eastmoney_hk_documents;
    const fetchMock=globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    fetchMock.mockImplementation(async (input:RequestInfo|URL)=>{
      const date=new URL(String(input),"http://localhost").searchParams.get("date")||"20260929";
      return {ok:true,status:200,json:async()=>({...dailyReview(date),eastmoney_hk_status:"PARTIAL",eastmoney_hk_documents:docs})} as Response;
    });
    const host = document.createElement("div");
    document.body.append(host);
    const dispose = mountCatalystObservations(host, "20260929");

    await waitFor(() => expect(host.querySelector(".manager-catalyst-observations")?.getAttribute("data-read-state")).toBe("READY"));
    const eastSummary=[...host.querySelectorAll("summary")].find(node=>node.textContent?.includes("东方财富港股公告"));
    expect(eastSummary).toBeTruthy();
    await fireEvent.click(eastSummary as HTMLElement);
    await waitFor(()=>expect(host.textContent).toContain("HK.00700 腾讯控股"));
    expect(host.textContent).toContain("AN202609281829962076");
    expect(host.textContent).not.toContain("网络连接或响应读取失败");
    const targetArticle=[...host.querySelectorAll('article[data-eastmoney-announcement]')]
      .find(article=>article.textContent?.includes("AN202609281829962076"));
    const body=targetArticle?.querySelector('[data-eastmoney-body]') as HTMLDetailsElement;
    expect(body).toBeTruthy();
    await fireEvent.click(body.querySelector("summary") as HTMLElement);
    const bodyPages = host.querySelectorAll('[data-eastmoney-announcement] [data-eastmoney-body-page] pre');
    expect(bodyPages).toHaveLength(4);
    expect([...bodyPages].reduce((total, page) => total + (page.textContent || "").length, 0)).toBeGreaterThan(19000);
    dispose();
  });
});

 it("wires US diagnostics from workspace and clears them on a failed date read", async () => {
    workspaceMocks.request.mockResolvedValue({...workspaceBase,us_mapping_research:{
      RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false,
      schema_version:"v4.manager_research.us_mapping_research.v1",target_trade_date:"20260921",reviewed_research:null,
      daily_run:{schema_version:"v4.manager_research.us_mapping_daily_run.v1",target_trade_date:"20260921",
        status:"INPUT_MISSING",run_id:null,generated_at:null,us_session_date:null,research_cutoff:null,
        coverage:{configured_us_universe_count:null,matched_relation_count:null,matched_hk_symbol_count:null,full_market_coverage:false},
        matches:[],gaps:["SYNTHETIC_INPUT_MISSING"],source_identity:null},
      coverage_diagnostics:{
      schema_version:"v5.us_mapping_scope.v1",scope:"PINNED_REVIEWED_RELATIONS_WITHIN_CONFIGURED_US_SAMPLE",
      status:"PARTIAL",full_market_coverage:false,formal_eligible:false,natural_verified:false,
      reviewed_us_symbols:["SYN_ONLY"],reviewed_us_symbol_count:1,
      configured_sample_count:37,rising_individual_count:6,assessed_rising_symbol_count:1,unassessed_rising_symbol_count:5}}});
    const host=document.createElement("div");document.body.append(host);
    const dispose=mountCatalystObservations(host,"20260921");
    try {
      await waitFor(()=>expect(host.querySelector('[aria-label="US 关系覆盖范围"]')?.textContent).toContain("配置样本 37"));
      expect(host.querySelector('[aria-label="US 关系覆盖范围"]')?.textContent).toContain("SYN_ONLY");
      const original=host.querySelector<HTMLDetailsElement>('[data-original-research]')!;
      expect(original.open).toBe(false);
      expect(host.querySelector('[aria-label="US 关系覆盖范围"]')?.closest('details')).toBeNull();
      for(const key of ['ANNOUNCEMENT','OVERSOLD']){
        const group=host.querySelector<HTMLDetailsElement>(`[data-strategy-summary="${key}"]`)!;
        expect(group.open).toBe(false);expect(group.querySelector(':scope > summary')?.textContent).toContain('未知');
      }
      original.open=true;expect(original.querySelector('[aria-label="业务闭环状态"]')).not.toBeNull();
      workspaceMocks.request.mockRejectedValue(new Error("SYNTHETIC_READ_FAILURE"));
      const date=host.querySelector<HTMLInputElement>('[aria-label="计划目标日"]')!;
      date.value="2026-09-22";await fireEvent.change(date);
      await waitFor(()=>expect(host.querySelector('[data-read-state]')?.getAttribute('data-read-state')).toBe('FAILED'));
      expect(host.querySelector('[aria-label="US 关系覆盖范围"]')?.textContent).toBe("");
      expect(host.querySelector<HTMLElement>('[aria-label="US 关系覆盖范围"]')?.hidden).toBe(true);
    } finally {dispose();}
  });
