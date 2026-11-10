import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/vue";
import { afterEach, describe, expect, it, vi } from "vitest";
import payload from "../../../public/top200-hit.json";
import AShareTop200Panel from "./AShareTop200Panel.vue";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function show(date = "20261104") {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({...payload,requested_date:date}) })));
  return render(AShareTop200Panel, { props: { date } });
}

describe("A close review snapshot", () => {
  it("shows frozen counts, readable ratios and all 200 stocks across four pages", async () => {
    show();
    const card = await screen.findByTestId("a-top200-card-pool");
    expect(card.textContent).toContain("24 / 200");
    expect(card.textContent).toContain("379");
    expect(card.textContent).toContain("12.00%");
    expect(card.textContent).toContain("6.33%");
    expect(screen.getByTestId("a-top200-card-seven").textContent).toContain("11 / 200");
    expect(screen.getAllByTestId("a-top200-stock-row")).toHaveLength(50);
    const ranks: number[] = [];
    for (let page = 0; page < 4; page++) {
      ranks.push(...screen.getAllByTestId("a-top200-stock-row").map(row => Number(row.children[0].textContent)));
      if (page < 3) await fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    }
    expect(ranks).toEqual(Array.from({ length: 200 }, (_, i) => i + 1));
  });
  it("filters union membership without adding overlapping pool or stage counts", async () => {
    show();
    await screen.findByTestId("a-top200-card-pool");
    const select = screen.getByLabelText("Top200 显示范围");
    await fireEvent.update(select, "pool");
    expect(screen.getAllByTestId("a-top200-stock-row")).toHaveLength(24);
    expect(screen.getAllByTestId("a-top200-stock-row").every(row => row.textContent?.includes("研报推荐池"))).toBe(true);
    await fireEvent.update(select, "stage");
    expect(screen.getAllByTestId("a-top200-stock-row")).toHaveLength(11);
    await fireEvent.update(select, "all");
    expect(screen.getAllByTestId("a-top200-stock-row").some(row => row.textContent?.includes("未命中已物化阶段"))).toBe(true);
  });
  it("keeps missing stages and partial pools visible while folding technical evidence", async () => {
    show();
    await screen.findByTestId("a-top200-card-seven");
    const gap = screen.getByLabelText("本日数据缺口");
    expect(gap.textContent).toContain("09:25");
    expect(gap.textContent).toContain("尾盘");
    expect(gap.textContent).toContain("后来的补跑未混入");
    expect(gap.textContent).toContain("部分数据");
    const evidence = screen.getByText("来源与核对证据").closest("details")!;
    expect(evidence.hasAttribute("open")).toBe(false);
    expect(within(evidence).getByText(/SAME_SNAPSHOT_RECONCILED/)).toBeTruthy();
    expect(screen.getByText(/分池统计/).closest("details")?.hasAttribute("open")).toBe(false);
    expect(screen.getByText(/七阶段统计/).closest("details")?.hasAttribute("open")).toBe(false);
  });
  it("does not silently substitute latest when requested date is absent", async () => {
    const view = show("20261105");
    expect((await screen.findByTestId("a-top200-empty")).textContent).toContain("2026-11-05");
    expect(screen.queryByTestId("a-top200-card-pool")).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: /查看最近已存日期/ }));
    expect(view.emitted().selectDate).toEqual([["20261104"]]);
  });
  it("keeps aggregate statistics but reports missing same-source detail", async () => {
    show("20261103");
    await screen.findByTestId("a-top200-card-pool");
    expect(screen.getByTestId("a-top200-detail-gap").textContent).toContain("缺少同日同来源");
    expect(screen.queryByTestId("a-top200-stock-row")).toBeNull();
  });
});

function dated(date:string) {
  const old=structuredClone(payload.dates.find(row=>row.date==='20261104')!);
  if(date==='20261105') { old.date=date;old.a_pool.selected_count=382;old.a_pool.hit_count=32;old.a_pool.top200_coverage_pct=16;old.a_pool.selection_hit_rate_pct=8.38; }
  return {...payload,requested_date:date,dates:[...payload.dates.filter(row=>row.date!==date),old]};
}
it('fetches a newly materialized date and rejects a late previous-date response',async()=>{
  let finishOld:(value:unknown)=>void=()=>{};
  vi.stubGlobal('fetch',vi.fn((url:string)=>url.endsWith('20261104')?new Promise(resolve=>{finishOld=resolve;}):Promise.resolve({ok:true,json:async()=>dated('20261105')})));
  const view=render(AShareTop200Panel,{props:{date:'20261104'}});
  await view.rerender({date:'20261105'});
  expect((await screen.findByTestId('a-top200-card-pool')).textContent).toContain('32 / 200');
  expect(screen.getByTestId('a-top200-card-pool').textContent).toContain('382');
  finishOld({ok:true,json:async()=>dated('20261104')});await Promise.resolve();await Promise.resolve();
  expect(screen.getByTestId('a-top200-card-pool').textContent).toContain('32 / 200');
});
it('validates exact requested date before exposing a result',async()=>{
  vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>dated('20261104')})));
  render(AShareTop200Panel,{props:{date:'20261105'}});
  expect((await screen.findByRole('alert')).textContent).toContain('日期或来源不可确认');
  expect(screen.queryByTestId('a-top200-card-pool')).toBeNull();
});
it('uses the existing dated completion event and foreground reads, then closes the stream',async()=>{
  const streams: Array<{url:string;listener?: (event:MessageEvent)=>void;close:ReturnType<typeof vi.fn>}> = [];
  class Events { url:string;listener?: (event:MessageEvent)=>void;close=vi.fn();constructor(url:string){this.url=url;streams.push(this);}addEventListener(name:string,fn:(event:MessageEvent)=>void){expect(name).toBe('workbench_completed');this.listener=fn;} }
  vi.stubGlobal('EventSource',Events);const fetcher=vi.fn(async()=>({ok:true,json:async()=>dated('20261105')}));vi.stubGlobal('fetch',fetcher);
  const view=render(AShareTop200Panel,{props:{date:'20261105'}});await screen.findByTestId('a-top200-card-pool');
  expect(streams[0].url).toContain('/days/2026-11-05/events');
  streams[0].listener?.({data:JSON.stringify({source_date:'2026-11-04',event_id:'wrong'})}as MessageEvent);expect(fetcher).toHaveBeenCalledTimes(1);
  streams[0].listener?.({data:JSON.stringify({source_date:'2026-11-05',event_id:'new'})}as MessageEvent);await waitFor(()=>expect(fetcher).toHaveBeenCalledTimes(2));await screen.findByTestId('a-top200-card-pool');
  window.dispatchEvent(new Event('focus'));document.dispatchEvent(new Event('visibilitychange'));await waitFor(()=>expect(fetcher).toHaveBeenCalledTimes(3));
  view.unmount();expect(streams[0].close).toHaveBeenCalledTimes(1);
});

it('names partial scope, natural failure and formula comparison without changing source-pool totals', async () => {
  const entry = {
    date: '20261109', top200: { top_count: 200 },
    a_pool: { selected_count: 487, hit_count: 36, materialized_pool_count: 2, pool_count: 6 },
    seven_stage: { selected_count: 10, hit_count: 2, stages: {
      STAGE_0925: { status: 'READY', execution_status: 'PARTIAL_ROWS', row_count: 10, unique_codes: 10, hit_count: 2, research_evidence_status: 'CANNOT_CONFIRM', error_counts: { RESEARCH_ITEM_QUALITY_SCORE_MISSING: 400 }, errors: ['RESEARCH_ITEM_QUALITY_SCORE_MISSING'] },
      STAGE_0930_0935: { status: 'NOT_MATERIALIZED', execution_status: 'EXECUTION_FAILED', hit_count: null, errors: ['SELECTION_ERROR:ResearchContextError:RESEARCH_SOURCE_WITNESS_INVALID:HOURLY_COMPLETION_WITNESS_MISSING'] },
      STAGE_0935_0940: { status: 'READY', execution_status: 'VALID_EMPTY', row_count: 0, unique_codes: 0, hit_count: 0 },
      STAGE_0940_0945: { status: 'NOT_MATERIALIZED', execution_status: 'NOT_RUN', hit_count: null }
    } },
    stage_coverage: { available: 1, total: 7 },
    formula_comparison: { status: 'READY', signal_date: '20261106', target_date: '20261109', historical_PIT: false, rows: [
      { group_id: 'four_group_union', signal_date: '20261106', target_date: '20261109', selected_count: 387, hit_count: 10, top200_coverage_pct: 5, selection_hit_rate_pct: 2.58 },
      { group_id: 'v192', signal_date: '20261106', target_date: '20261109', selected_count: 19, hit_count: 2, top200_coverage_pct: 1, selection_hit_rate_pct: 10.53 }
    ] }
  };
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ ...payload, requested_date: entry.date, dates: [entry] }) })));
  render(AShareTop200Panel, { props: { date: entry.date } });
  const pool = await screen.findByTestId('a-top200-card-pool');
  expect(pool.textContent).toContain('已接入来源池汇总（2/6）');
  expect(pool.textContent).toContain('36 / 200');
  expect(pool.textContent).toContain('487');
  expect(screen.getByTestId('a-top200-card-seven').textContent).toContain('已物化阶段（1/7）');
  expect(screen.getByLabelText('本日数据缺口').textContent).toContain('完整七阶段效果不可评价');
  const stages = screen.getAllByTestId('a-top200-stage-row');
  expect(stages[0].textContent).toContain('已生成名单，证据不完整');
  expect(stages[0].textContent).toContain('400 项');
  expect(stages[1].textContent).toContain('行情已到，小时研究完成回执未通过，未生成名单');
  expect(stages[1].textContent).toContain('不可确认');
  expect(stages[1].textContent).not.toContain('HOURLY_COMPLETION_WITNESS_MISSING');
  expect(stages[2].textContent).toContain('有效空名单');
  expect(stages[3].textContent).toContain('未运行');
  const formula = screen.getByTestId('a-top200-formula-comparison');
  expect(formula.textContent).toContain('此表不属于上方已接入来源池汇总');
  expect(formula.textContent).toContain('historical_PIT=false');
  expect(formula.textContent).toContain('2026-11-06');
  expect(screen.getAllByTestId('a-top200-formula-row')).toHaveLength(2);
});
