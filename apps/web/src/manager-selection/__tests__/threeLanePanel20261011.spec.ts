import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, waitFor } from '@testing-library/vue';

const calls=vi.hoisted(()=>({request:vi.fn(),refresh:vi.fn(),analysis:vi.fn()}));
vi.mock('../../api/managerWorkspace.js',async(importOriginal)=>({
  ...(await importOriginal<typeof import('../../api/managerWorkspace.js')>()),
  requestManagerWorkspace:calls.request,refreshManagerWorkspace:calls.refresh,
  requestManagerAnnouncements:vi.fn().mockRejectedValue(new Error('SYNTHETIC_NOT_RUN')),
}));
vi.mock('../../api/managerAnnouncementAnalysis.js',()=>({requestManagerAnnouncementAnalysis:calls.analysis}));
import { mountCatalystObservations } from '../catalystObservationPanel';

function result(date='20261009',identity='a'.repeat(64)): any {
  return {schema_version:'v4.manager_research.workspace.v1',semantic_version:'20260921.manager-semantic.r3.v1',
    target_trade_date:date,input_identity:identity,stocks:[],focus_symbols:[],company_events:[],
    rejected_relations:[],briefing:{},themes:[],materials:[],gaps:[],lanes:[],owner_chain:{},
    plan_product:{status:'NOT_MATERIALIZED'},plan_context:{research_cutoff:'2026-10-11T09:00:00+08:00'},
    read_context:{mode:'CURRENT_DYNAMIC_PREVIEW',status:'VERIFIED_WITH_GAPS'},
    summary:{stock_count:0,relation_count:0,theme_count:0,reused_material_count:0,formal_recommendation_count:0},
    RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false};
}
let dispose:(()=>void)|undefined;
function mount(query:string) {
  window.history.replaceState(null,'','/manager-selection/?'+query);
  const host=document.createElement('div');document.body.append(host);
  calls.analysis.mockRejectedValue(new Error('SYNTHETIC_NO_ANALYSIS'));
  dispose=mountCatalystObservations(host,'20261009');return host;
}
afterEach(()=>{dispose?.();dispose=undefined;vi.resetAllMocks();window.history.replaceState(null,'','/');document.body.replaceChildren();});

describe('three-lane source dates and explicit review survive reload',()=>{
  it('leaves calendar default publication with the backend',async()=>{
    calls.request.mockResolvedValue(result());mount('date=20261009&plan_date=20261009');
    await waitFor(()=>expect(calls.request).toHaveBeenCalledOnce());
    expect(calls.request.mock.calls[0][0]).toBe('20261009');
    expect(calls.request.mock.calls[0][2]).toBe('auto');
    expect(calls.request.mock.calls[0][3]).toEqual({});
  });
  it('normalizes explicit aliases and restores dynamic view from the URL',async()=>{
    calls.request.mockResolvedValue(result());
    const query='date=20261009&plan_date=2026-10-09&selection_date=2026-10-08&publication_date=2026-10-07&view=dynamic';
    const host=mount(query);
    await waitFor(()=>expect(calls.request).toHaveBeenCalledOnce());
    expect(calls.request.mock.calls[0].slice(2)).toEqual(['dynamic',{selection_date:'20261008',announcement_date:'20261007'}]);
    expect((host.querySelector('[aria-label="历史或现在回看"]') as HTMLSelectElement).value).toBe('dynamic');
    expect(calls.analysis.mock.calls[0][1]).toBe('20261007');
    dispose?.();dispose=undefined;calls.request.mockClear();mount(query);
    await waitFor(()=>expect(calls.request).toHaveBeenCalledOnce());
    expect(calls.request.mock.calls[0].slice(2)).toEqual(['dynamic',{selection_date:'20261008',announcement_date:'20261007'}]);
  });
  it('persists view changes and forwards the same bindings to explicit owner refresh',async()=>{
    calls.request.mockResolvedValue(result());calls.refresh.mockResolvedValue(result());
    const host=mount('date=20261009&plan_date=20261009&selection_date=20261008&announcement_date=20261007');
    await waitFor(()=>expect(host.querySelector('[data-read-state="READY"]')).not.toBeNull());
    const select=host.querySelector('[aria-label="历史或现在回看"]') as HTMLSelectElement;
    select.value='dynamic';await fireEvent.change(select);
    await waitFor(()=>expect(calls.request).toHaveBeenCalledTimes(2));
    expect(new URLSearchParams(window.location.search).get('view')).toBe('dynamic');
    await waitFor(()=>expect(host.querySelector('[data-read-state="READY"]')).not.toBeNull());
    const button=[...host.querySelectorAll('button')].find(node=>node.textContent==='用既有材料生成计划')!;
    await fireEvent.click(button);
    await waitFor(()=>expect(calls.refresh).toHaveBeenCalledOnce());
    expect(calls.refresh.mock.calls[0][2]).toEqual({selection_date:'20261008',announcement_date:'20261007'});
  });
  it('re-reads all channels on publication change and discards the late old response',async()=>{
    let finishOld:(value:any)=>void=()=>{};
    calls.request.mockImplementationOnce(()=>new Promise(resolve=>{finishOld=resolve;})).mockResolvedValue(result('20261009','b'.repeat(64)));
    const host=mount('date=20261009&plan_date=20261009&publication_date=20261008&view=dynamic');
    const input=host.querySelector('[aria-label="公告日期"]') as HTMLInputElement;
    input.value='2026-10-07';await fireEvent.change(input);
    await waitFor(()=>expect(calls.request).toHaveBeenCalledTimes(2));
    expect(calls.request.mock.calls[1][3]).toEqual({announcement_date:'20261007'});
    expect(new URLSearchParams(window.location.search).has('publication_date')).toBe(false);
    await waitFor(()=>expect(host.querySelector('[data-input-identity]')?.getAttribute('data-input-identity')).toBe('b'.repeat(64)));
    finishOld(result());await Promise.resolve();
    expect(host.querySelector('[data-input-identity]')?.getAttribute('data-input-identity')).toBe('b'.repeat(64));
  });
});
