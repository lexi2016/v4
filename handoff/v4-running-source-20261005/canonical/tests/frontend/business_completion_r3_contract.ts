import { acquiredTime } from '../../apps/web/src/manager-selection/researchAttention.js';
import { decisionSummaryCounts } from '../../apps/web/src/manager-selection/adapters/workspaceDecision.js';
import { businessStatusRows } from '../../apps/web/src/manager-selection/businessStatus.js';

const assert=(value:boolean,message:string)=>{if(!value)throw new Error(message);};

export function runBusinessCompletionR3Contract():void{
  assert(acquiredTime({first_seen_at:'2026-09-24T10:00:00+08:00'})==='2026-09-24T10:00:00+08:00','first_seen fallback');
  assert(acquiredTime({collected_at:'2026-09-24T10:01:00+08:00'})==='2026-09-24T10:01:00+08:00','collected fallback');
  assert(acquiredTime({})===null,'missing acquisition stays null');

  const value:any={stocks:[
    {symbol:'HK.1',is_focus:true,priority_basis:{group:'DIRECT_COMPANY_EVENT'},evidence:[],material_relations:[],plan:{actions:[],trigger_price:null}},
    {symbol:'HK.2',is_focus:false,priority_basis:{group:'DIRECT_COMPANY_EVENT'},evidence:[],material_relations:[],plan:{actions:[],trigger_price:null}},
  ],themes:[],plan_context:{research_cutoff:'2026-09-25T08:59:00+08:00'}};
  const counts=decisionSummaryCounts(value);
  assert(counts.current===0&&counts.background===2,'summary must use rendered decision classification');

  const targetDate='20260925';
  const notRunObservation={
    schema_version:'v4.manager_research.announcement_observation.v1',target_trade_date:targetDate,
    status:'NOT_RUN',count_known:false,latest_attempt:null,observations:[],pending_observations:[],
    official_documents:[],coverage:{},gaps:['ANNOUNCEMENT_OWNER_NOT_RUN'],capture_runs:[],
  };
  const notRunReview={
    schema_version:'v4.manager_research.announcement_review.v1',target_trade_date:targetDate,
    status:'NOT_RUN',gaps:['ANNOUNCEMENT_OWNER_NOT_RUN'],coverage:{},attempt:null,product_identity:null,
  };
  const notRunOwnerChain={announcements:{
    owner:'ManagerResearchJobService.refresh_announcements',status:'NOT_RUN',
    failure_reasons:['ANNOUNCEMENT_OWNER_NOT_RUN'],
    official_hkex:{source:'HKEX_OFFICIAL',status:'NOT_RUN',attempt:null,product_identity:null},
  }};
  const status=businessStatusRows({
    target_trade_date:targetDate,plan_product:{status:'NOT_MATERIALIZED'},
    announcement_observation:notRunObservation,announcement_review:notRunReview,owner_chain:notRunOwnerChain,
    us_market_attention:{status:'READY',coverage_scope:'FIXED_SCOPE'},
    research_attention:{status:'READY_WITH_GAPS'},read_context:{status:'VERIFIED_WITH_GAPS'},
    lanes:[
      {lane:'STAGE',state:'UNVERIFIED',last_success_at:null,last_attempt_at:null,failure_reasons:['SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID']},
      {lane:'CATALYST',state:'NOT_RUN',last_success_at:null,last_attempt_at:null,failure_reasons:['INPUT_MISSING']},
      {lane:'CLOSE',state:'UNVERIFIED',last_success_at:null,last_attempt_at:'2026-09-25T15:30:00+08:00',failure_reasons:['NO_HK_CONNECT_1530_SESSION']},
    ],
  } as any);
  assert(status.some((row)=>row.label==='公告'&&row.state==='未运行'),'announcement NOT_RUN visible');
  assert(status.some((row)=>row.label==='计划'&&row.state==='未冻结'),'plan not materialized visible');
  assert(status.some((row)=>row.label==='Stage'&&row.detail.includes('最近成功 未记录')),'Stage latest success visible');
  assert(status.some((row)=>row.label==='15:30'&&row.detail.includes('NO_HK_CONNECT_1530_SESSION')),'close failure visible');
  assert(status.every(row=>!row.detail.includes('{')),'main business status must not dump JSON');

  const incompleteNotRun=businessStatusRows({
    target_trade_date:targetDate,plan_product:{status:'NOT_MATERIALIZED'},
    announcement_observation:{status:'NOT_RUN'},us_market_attention:{status:'READY',coverage_scope:'FIXED_SCOPE'},
    research_attention:{status:'READY_WITH_GAPS'},read_context:{status:'VERIFIED_WITH_GAPS'},lanes:[],
  } as any).find((row)=>row.label==='公告');
  assert(incompleteNotRun?.state==='无法确认','incomplete NOT_RUN must remain unconfirmed');
  assert(incompleteNotRun.detail.includes('不能归为未运行'),'incomplete NOT_RUN must not claim no attempt');
}

runBusinessCompletionR3Contract();
