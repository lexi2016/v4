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
