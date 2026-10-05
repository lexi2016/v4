import { describe, expect, it } from 'vitest';
import { acquiredTime } from '../researchAttention';
import { decisionSummaryCounts } from '../adapters/workspaceDecision';
import { businessStatusRows } from '../businessStatus';

const observedNotRun=(date='20260925')=>({
  schema_version:'v4.manager_research.announcement_observation.v1',target_trade_date:date,
  status:'NOT_RUN',count_known:false,latest_attempt:null,observations:[],pending_observations:[],
  official_documents:[],coverage:{},gaps:['ANNOUNCEMENT_OWNER_NOT_RUN'],capture_runs:[],
});
const observedNotRunReview=(date='20260925')=>({
  schema_version:'v4.manager_research.announcement_review.v1',target_trade_date:date,
  status:'NOT_RUN',gaps:['ANNOUNCEMENT_OWNER_NOT_RUN'],coverage:{},attempt:null,product_identity:null,
});
const observedNotRunOwnerChain=()=>({announcements:{
  owner:'ManagerResearchJobService.refresh_announcements',status:'NOT_RUN',
  failure_reasons:['ANNOUNCEMENT_OWNER_NOT_RUN'],
  official_hkex:{source:'HKEX_OFFICIAL',status:'NOT_RUN',attempt:null,product_identity:null},
}});

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

  it('shows explicit owner-read NOT_RUN and NOT_MATERIALIZED as business states rather than zero success',()=>{
    const rows=businessStatusRows({
      target_trade_date:'20260925',plan_product:{status:'NOT_MATERIALIZED'},
      announcement_review:observedNotRunReview(),announcement_observation:observedNotRun(),
      owner_chain:observedNotRunOwnerChain(),us_market_attention:{status:'READY',coverage_scope:'FIXED_SCOPE'},
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

  it('keeps historical announcement coverage unknown when its observation and owner chain are absent',()=>{
    const row=businessStatusRows({
      target_trade_date:'20260930',plan_product:{status:'SOURCE_FAILED'},
      announcement_review:{schema_version:'v4.manager_research.announcement_review.v1',target_trade_date:'20260930',
        status:'NOT_RUN',coverage:{},gaps:['HISTORY_ANNOUNCEMENT_COVERAGE_UNKNOWN'],attempt:null,product_identity:null},
      us_market_attention:{status:'READY',coverage_scope:'FIXED_SCOPE'},research_attention:{status:'READY_WITH_GAPS'},
      read_context:{status:'SOURCE_FAILED'},lanes:[],
    } as any).find(item=>item.label==='公告')!;
    expect(row.state).toBe('无法确认');
    expect(row.detail).toContain('HISTORY_ANNOUNCEMENT_COVERAGE_UNKNOWN');
    expect(row.detail).not.toContain('没有 owner attempt');
    expect(row.detail).not.toContain('HKEX目录未运行');
    expect(row.next).toContain('Vibe RSS');
    expect(row.next).toContain('不能替代');
  });

  it('labels an absent announcement observation as unread, not as a confirmed no-attempt result',()=>{
    const row=businessStatusRows({target_trade_date:'20260930',plan_product:{status:'SOURCE_FAILED'},
      us_market_attention:{status:'READY',coverage_scope:'FIXED_SCOPE'},
      research_attention:{status:'READY_WITH_GAPS'},read_context:{status:'SOURCE_FAILED'},lanes:[]} as any)
      .find(item=>item.label==='公告')!;
    expect(row.state).toBe('未读取');
    expect(row.detail).toContain('不能解释为未运行');
    expect(row.detail).not.toContain('没有 owner attempt');
  });

  it('keeps an unbound NOT_RUN observation unknown until its same-date official owner read is present',()=>{
    const row=businessStatusRows({target_trade_date:'20260930',plan_product:{status:'SOURCE_FAILED'},
      announcement_review:observedNotRunReview('20260930'),announcement_observation:observedNotRun('20260930'),
      us_market_attention:{status:'READY',coverage_scope:'FIXED_SCOPE'},
      research_attention:{status:'READY_WITH_GAPS'},read_context:{status:'SOURCE_FAILED'},lanes:[]} as any)
      .find(item=>item.label==='公告')!;
    expect(row.state).toBe('无法确认');
    expect(row.detail).not.toContain('没有 owner attempt');
    expect(row.detail).not.toContain('HKEX目录未运行');
  });

  it('shows SUCCEEDED_EMPTY as a completed empty result, distinct from not run or failure',()=>{
    const makeRows=(status:string)=>businessStatusRows({
      target_trade_date:'20260925',plan_product:{status:'NOT_MATERIALIZED'},
      announcement_review:status==='NOT_RUN'?observedNotRunReview():undefined,
      announcement_observation:status==='NOT_RUN'?observedNotRun():{status},
      owner_chain:status==='NOT_RUN'?observedNotRunOwnerChain():undefined,
      us_market_attention:{status:'READY',coverage_scope:'FIXED_SCOPE'},
      research_attention:{status:'READY_WITH_GAPS'},read_context:{status:'VERIFIED_WITH_GAPS'},lanes:[],
    } as any);
    const row=(status:string)=>makeRows(status).find(item=>item.label==='公告')!;
    expect(row('SUCCEEDED_EMPTY').state).toContain('空');
    expect(row('SUCCEEDED_EMPTY').state).not.toBe(row('NOT_RUN').state);
    expect(row('SUCCEEDED_EMPTY').state).not.toBe(row('FAILED').state);
  });

  it('renders the four US relation assessment states in plain Chinese without turning unevaluated into zero',()=>{
    const make=(assessment_state:string,count:number|null,reason:string)=>businessStatusRows({
      target_trade_date:'20261002',plan_product:{status:'NOT_MATERIALIZED'},
      us_market_attention:{status:'CANNOT_CONFIRM',raw_industry_up:[{},{}],raw_individual_up:[{}],
        research_material_input:{source_material_record_count:2592,pre_connect_material_card_count:80,
          post_connect_material_card_count:0,research_relation_material_card_count:80}},
      research_attention:{status:'READY_WITH_GAPS',us_mapping_diagnostics:{status:'COMPUTED_BY_RELATION_LAYER',
        assessment_state,accepted_hk_mapping_count:count,assessment_reasons:reason?[reason]:[]}},
      lanes:[],
    } as any).find(row=>row.label==='美股')!;
    const unevaluated=make('NOT_EVALUATED',null,'US_MARKET_SNAPSHOT_NOT_READY');
    expect(unevaluated.state).toBe('尚未评估');
    expect(unevaluated.detail).toContain('Connect资格核验前候选 80 张、核验后 0 张');
    expect(unevaluated.detail).toContain('关系评估输入 80 张');
    expect(unevaluated.detail).toContain('合格关系尚未计算');
    expect(unevaluated.detail).not.toContain('合格关系 0 条');

    expect(make('INSUFFICIENT',null,'TWO_SOURCE_PIT_VERIFIED_REQUIRED').state).toBe('证据不足');
    expect(make('ASSESSED_ZERO',0,'NO_QUALIFIED_RELATION_AFTER_COMPLETE_TWO_SOURCE_PIT_EVALUATION'))
      .toMatchObject({state:'已评估，暂无合格关系'});
    expect(make('ASSESSED_WITH_RELATIONS',2,'VERIFIED_RELATIONS_PASSED_TWO_SOURCE_PIT'))
      .toMatchObject({state:'已有合格关系'});
  });

  it('treats a legacy computed zero as insufficient because its evaluation completeness is unknown',()=>{
    const row=businessStatusRows({target_trade_date:'20261002',plan_product:{status:'NOT_MATERIALIZED'},
      us_market_attention:{status:'READY',raw_industry_up:[],raw_individual_up:[]},
      research_attention:{status:'READY',us_mapping_diagnostics:{status:'COMPUTED_BY_RELATION_LAYER',accepted_hk_mapping_count:0}},
      lanes:[]} as any).find(item=>item.label==='美股')!;
    expect(row.state).toBe('证据不足');
    expect(row.detail).toContain('合格关系数量暂不能确认');
    expect(row.detail).not.toContain('合格关系 0 条');
  });

  it('labels a Connect holiday without treating a missing natural Stage receipt as execution success',()=>{
    const value:any={target_trade_date:'20261002',plan_product:{status:'NOT_MATERIALIZED'},
      us_market_attention:{status:'NOT_READ'},research_attention:{status:'CANNOT_CONFIRM'},
      lanes:[{lane:'STAGE',state:'DUE_RECEIPT_UNKNOWN',last_success_at:null,last_attempt_at:null,failure_reasons:[],
        execution_timing:{execution_state:'DUE_RECEIPT_UNKNOWN',artifact_status:'CANNOT_CONFIRM',schedule_state:'DUE',
          schedule_overview:[{stage_id:'STAGE_0930_0935',status:'DUE',calendar:{
            a_share:'NON_TRADING_DAY',hk_securities:'FULL_TRADING_DAY',hk_connect:'NON_TRADING_DAY'}}]}}]};
    const stage=businessStatusRows(value).find(item=>item.label==='Stage')!;
    expect(stage.state).toBe('港股通非交易日（无需自然阶段回执）');
    expect(stage.detail).toContain('DUE_RECEIPT_UNKNOWN');
    expect(stage.next).toContain('不表示Stage已成功执行');
    expect(stage.next).toContain('港股证券研究仍按独立来源展示');
  });

  it('keeps DUE_RECEIPT_UNKNOWN when an explicit Connect holiday calendar is absent',()=>{
    const value:any={target_trade_date:'20261002',plan_product:{status:'NOT_MATERIALIZED'},
      us_market_attention:{status:'NOT_READ'},research_attention:{status:'CANNOT_CONFIRM'},
      lanes:[{lane:'STAGE',state:'DUE_RECEIPT_UNKNOWN',last_success_at:null,last_attempt_at:null,failure_reasons:[],
        execution_timing:{execution_state:'DUE_RECEIPT_UNKNOWN',schedule_overview:[]}}]};
    const stage=businessStatusRows(value).find(item=>item.label==='Stage')!;
    expect(stage.state).toBe('到期回执待核');
  });

  it('surfaces an Eastmoney owner run in the top announcement status without claiming HKEX ran',()=>{
    const rows=businessStatusRows({
      target_trade_date:'20260929',plan_product:{status:'NOT_MATERIALIZED'},
      announcement_review:observedNotRunReview('20260929'),
      announcement_observation:{...observedNotRun('20260929'),eastmoney_hk_status:'PARTIAL',
        eastmoney_hk_documents:[{event_id:'a'.repeat(64)}],
        eastmoney_hk_attempt:{state:'PARTIAL',started_at:'2026-09-29T13:09:00+08:00',finished_at:'2026-09-29T13:10:41+08:00'}},
      owner_chain:observedNotRunOwnerChain(),
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
