import { describe, expect, it } from 'vitest';
import { acquiredTime } from '../researchAttention';
import { decisionSummaryCounts } from '../adapters/workspaceDecision';
import { businessStatusRows } from '../businessStatus';

describe('manager business completion R3',()=>{
  it('uses persisted acquisition fields without inventing the current time',()=>{
    expect(acquiredTime({first_seen_at:'2026-09-24T10:00:00+08:00'})).toBe('2026-09-24T10:00:00+08:00');
    expect(acquiredTime({collected_at:'2026-09-24T10:01:00+08:00'})).toBe('2026-09-24T10:01:00+08:00');
    expect(acquiredTime({})).toBeNull();
  });

  it('derives headline counts from the exact final decision-card projection',()=>{
    const value:any={stocks:[
      {symbol:'HK.1',is_focus:true,priority_basis:{group:'DIRECT_COMPANY_EVENT'},evidence:[],material_relations:[],plan:{actions:[],trigger_price:null}},
      {symbol:'HK.2',is_focus:false,priority_basis:{group:'DIRECT_COMPANY_EVENT'},evidence:[],material_relations:[],plan:{actions:[],trigger_price:null}},
    ],themes:[],plan_context:{research_cutoff:'2026-09-25T09:29:00+08:00'}};
    expect(decisionSummaryCounts(value)).toEqual({current:0,background:2,total:2});
  });

  it('shows NOT_RUN and NOT_MATERIALIZED as business states rather than zero success',()=>{
    const rows=businessStatusRows({
      target_trade_date:'20260925',plan_product:{status:'NOT_MATERIALIZED'},
      announcement_observation:{status:'NOT_RUN'},us_market_attention:{status:'READY',coverage_scope:'FIXED_SCOPE'},
      research_attention:{status:'READY_WITH_GAPS'},read_context:{status:'VERIFIED_WITH_GAPS'},
      lanes:[
        {lane:'STAGE',state:'UNVERIFIED',last_success_at:null,last_attempt_at:null,failure_reasons:['SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID']},
        {lane:'CATALYST',state:'NOT_RUN',last_success_at:null,last_attempt_at:null,failure_reasons:['INPUT_MISSING']},
        {lane:'CLOSE',state:'UNVERIFIED',last_success_at:null,last_attempt_at:'2026-09-25T15:30:00+08:00',failure_reasons:['NO_HK_CONNECT_1530_SESSION']},
      ],
    } as any);
    expect(rows).toEqual(expect.arrayContaining([
      expect.objectContaining({label:'公告',state:'未运行'}),
      expect.objectContaining({label:'计划',state:'未冻结'}),
    ]));
    expect(rows).toEqual(expect.arrayContaining([
      expect.objectContaining({label:'Stage',detail:expect.stringContaining('最近成功 未记录')}),
      expect.objectContaining({label:'15:30',detail:expect.stringContaining('NO_HK_CONNECT_1530_SESSION')}),
    ]));
    expect(rows.every(row=>!row.detail.includes('{'))).toBe(true);
  });

  it('shows SUCCEEDED_EMPTY as a completed empty result, distinct from not run or failure',()=>{
    const makeRows=(status:string)=>businessStatusRows({
      target_trade_date:'20260925',plan_product:{status:'NOT_MATERIALIZED'},
      announcement_observation:{status},us_market_attention:{status:'READY',coverage_scope:'FIXED_SCOPE'},
      research_attention:{status:'READY_WITH_GAPS'},read_context:{status:'VERIFIED_WITH_GAPS'},lanes:[],
    } as any);
    const row=(status:string)=>makeRows(status).find(item=>item.label==='公告')!;
    expect(row('SUCCEEDED_EMPTY').state).toContain('空');
    expect(row('SUCCEEDED_EMPTY').state).not.toBe(row('NOT_RUN').state);
    expect(row('SUCCEEDED_EMPTY').state).not.toBe(row('FAILED').state);
  });

  it('surfaces an Eastmoney owner run in the top announcement status without claiming HKEX ran',()=>{
    const rows=businessStatusRows({
      target_trade_date:'20260929',plan_product:{status:'NOT_MATERIALIZED'},
      announcement_observation:{status:'NOT_RUN',latest_attempt:null,eastmoney_hk_status:'PARTIAL',
        eastmoney_hk_documents:[{event_id:'a'.repeat(64)}],
        eastmoney_hk_attempt:{state:'PARTIAL',started_at:'2026-09-29T13:09:00+08:00',finished_at:'2026-09-29T13:10:41+08:00'}},
      us_market_attention:{status:'READY',coverage_scope:'FIXED_SCOPE'},research_attention:{status:'READY_WITH_GAPS'},
      read_context:{status:'VERIFIED_WITH_GAPS'},lanes:[],
    } as any);
    const row=rows.find(item=>item.label==='公告')!;
    expect(row.state).toBe('部分完成（Eastmoney 港股镜像）');
    expect(row.detail).toContain('HKEX目录未运行');
    expect(row.detail).toContain('已读回 1 条');
    expect(row.detail).toContain('2026-09-29T13:10:41+08:00');
    expect(row.next).toContain('首次发布时间仍未确认');
  });

  it('labels a saved manual refresh as a draft and freezes only a matching pre-open attempt',()=>{
    const make=(execution_kind:string,attemptRun='run-1')=>businessStatusRows({
      plan_product:{status:'CURRENT',run_id:'run-1'},
      workspace_plan_attempt:{run_id:attemptRun,execution_kind,state:'PARTIAL'},
      read_context:{status:'VERIFIED_WITH_GAPS'},lanes:[],
    } as any).find(row=>row.label==='计划')!;
    expect(make('MANUAL_REFRESH')).toMatchObject({state:'已保存研究草案（未正式冻结）'});
    expect(make('SCHEDULED_PREOPEN')).toMatchObject({state:'已冻结'});
    expect(make('SCHEDULED_PREOPEN','other')).toMatchObject({state:'需核验'});
  });
});
