import { describe, expect, it } from 'vitest';
import { stageMarketStateText } from './formatters';
import { projectSummaryPoolPage } from '../api/pool_stage';
import type { StageWorkbench, PoolResponse } from './types';

const workbench = (changes: object = {}) => ({
  stage:{stage_id:'STAGE_0925',status:'PARTIAL',display_status:'PARTIAL'},
  selected_a_rows:0,selected_hk_rows:10,selected_total_rows:10,unified_rows:[],
  markets:{A:{requested_rows:482,source_rows:0,source_status:'CANNOT_CONFIRM'},HK:{status:'READY'}},
  ...changes,
}) as unknown as StageWorkbench;

describe('same market state semantics for timeline and detail', () => {
  it('keeps failed A separate from successful HK and never calls failed zero successful', () => {
    const value=workbench();
    expect(stageMarketStateText(value,'A')).toBe('采集失败/来源未就绪');
    expect(stageMarketStateText(value,'HK')).toBe('10 条');
  });
  it('distinguishes HK-only, not due, waiting, verified zero and partial observations', () => {
    expect(stageMarketStateText(workbench({stage:{stage_id:'STAGE_1545_1555'}}),'A')).toBe('不适用');
    expect(stageMarketStateText(workbench({execution_evidence:{due_status:'NOT_DUE'}}),'HK')).toBe('未到期/等待执行');
    expect(stageMarketStateText(workbench({markets:{},execution_evidence:{status:'EXECUTION_RECEIPT_MISSING'}}),'A')).toBe('等待执行/待确认');
    expect(stageMarketStateText(workbench({markets:{A:{display_mode:'READY_EMPTY'}}}),'A')).toBe('成功零结果 · 0 条');
    expect(stageMarketStateText(workbench({markets:{HK:{source_status:'PARTIAL_WITH_ROWS',display_mode:'OBSERVATION_UNVERIFIED',observation_count:10}}}),'HK')).toBe('部分完成 · 10 条观察行 · 未验证');
  });
});

describe('summary paging preserves independently owned pool rows', () => {
  const first=()=>({trade_date:'20261027',input_fingerprint:'a'.repeat(64),pools:[{pool_id:'stage7',rows:[{code:'920575'}]}],
    rows:[{code:'920575'}],a_all_pool_rows:[{code:'first'}],pagination:{offset:0,limit:200,next_offset:200,has_more:true,
      arrays:{a_all_pool_rows:{offset:0,total_rows:482}},pools:{stage7:{offset:0,total_rows:10}}}}) as unknown as PoolResponse;
  const page=()=>({...first(),a_all_pool_rows:[{code:'last'}],pools:[{pool_id:'stage7',rows:[]}],
    pagination:{offset:400,limit:200,next_offset:null,has_more:false,arrays:{a_all_pool_rows:{offset:400,total_rows:482}}}}) as unknown as PoolResponse;
  it('changes only summary page and cursor with same date/fingerprint', () => {
    const f=first(),p=page(),before=JSON.stringify(f);const result=projectSummaryPoolPage(f,p)!;
    expect(result.pools).toEqual(f.pools);expect(result.rows).toEqual(f.rows);
    expect(result.a_all_pool_rows).toEqual(p.a_all_pool_rows);expect(result.pagination?.offset).toBe(400);
    expect(result.pagination?.pools).toEqual(f.pagination?.pools);expect(JSON.stringify(f)).toBe(before);
  });
  it.each(['date','fingerprint','absent'] as const)('invalidates whole cache for %s', (defect) => {
    const f=first(),p=page();
    if(defect==='date')p.trade_date='20261028';
    if(defect==='fingerprint')p.input_fingerprint='b'.repeat(64);
    if(defect==='absent')delete p.input_fingerprint;
    expect(projectSummaryPoolPage(f,p)).toBeNull();
  });
});

it('renders the shared market labels in the stage detail summary', async () => {
  const { render } = await import('@testing-library/vue');
  const { default: Panel } = await import('../components/review/StageSummaryPanel.vue');
  const value=workbench();
  const view=render(Panel,{props:{summary:{trade_date:'20261027',stage_id:'STAGE_0925',stage_label:'09:25',
    selected_a_rows:0,selected_hk_rows:10,a_market_state_label:stageMarketStateText(value,'A'),hk_market_state_label:stageMarketStateText(value,'HK')}}});
  expect(view.getByText('采集失败/来源未就绪')).toBeTruthy();
  expect(view.getByText('10 条')).toBeTruthy();
});
