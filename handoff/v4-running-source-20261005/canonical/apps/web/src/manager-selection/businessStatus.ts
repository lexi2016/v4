import type { JsonObject, ManagerWorkspace } from '../api/managerWorkspace.js';

export interface BusinessStatusRow {label:string;state:string;detail:string;next:string;}
const object=(value:unknown):JsonObject=>value&&typeof value==='object'&&!Array.isArray(value)?value as JsonObject:{};
const text=(value:unknown,fallback='')=>typeof value==='string'&&value.trim()?value:fallback;
const safeCount=(value:unknown):number|null=>typeof value==='number'&&Number.isSafeInteger(value)&&value>=0?value:null;

function usAssessmentState(mapping:JsonObject):'NOT_EVALUATED'|'INSUFFICIENT'|'ASSESSED_ZERO'|'ASSESSED_WITH_RELATIONS'{
  const state=mapping.assessment_state;
  if(state==='NOT_EVALUATED'||state==='INSUFFICIENT'||state==='ASSESSED_ZERO'||state==='ASSESSED_WITH_RELATIONS')return state;
  // Older payloads lack completeness evidence. A legacy zero is therefore
  // unresolved; only a positive, previously admitted mapping stays positive.
  if(mapping.status==='COMPUTED_BY_RELATION_LAYER'&&safeCount(mapping.accepted_hk_mapping_count)!==null){
    return safeCount(mapping.accepted_hk_mapping_count)!>0?'ASSESSED_WITH_RELATIONS':'INSUFFICIENT';
  }
  return 'NOT_EVALUATED';
}

const US_ASSESSMENT_LABELS={
  NOT_EVALUATED:'尚未评估', INSUFFICIENT:'证据不足',
  ASSESSED_ZERO:'已评估，暂无合格关系', ASSESSED_WITH_RELATIONS:'已有合格关系',
} as const;
const US_SOURCE_LABELS:Record<string,string>={
  READY:'已就绪',PARTIAL:'部分可用',CANNOT_CONFIRM:'无法确认',INPUT_MISSING:'缺少输入',
  SOURCE_FAILED:'来源读取失败',NOT_READ:'尚未读取',
};
const US_REASON_LABELS:Record<string,string>={
  US_MARKET_SNAPSHOT_NOT_READY:'美股对应时段快照未就绪',
  US_MARKET_INPUT_NOT_READY:'美股输入尚未就绪',
  US_MARKET_INPUT_PARTIAL:'美股输入不完整',
  US_MAPPING_INPUT_NOT_ELIGIBLE:'美股映射输入尚未通过资格检查',
  FULL_VERIFIED_MATERIAL_CARDS_REQUIRED:'关系材料卡尚未满足完整性要求',
  MATERIAL_INPUT_COMPLETENESS_UNVERIFIED:'关系材料完整性尚未确认',
  TWO_SOURCE_PIT_VERIFIED_REQUIRED:'双来源与可用时间证据尚未同时满足',
  US_MARKET_INPUT_NOT_READ:'美股来源尚未读取',
  NO_QUALIFIED_RELATION_AFTER_COMPLETE_TWO_SOURCE_PIT_EVALUATION:'完整核验后暂无合格关系',
  VERIFIED_RELATIONS_PASSED_TWO_SOURCE_PIT:'已核关系通过双来源与时点核验',
};

function usReason(mapping:JsonObject):string{
  const reasons=Array.isArray(mapping.assessment_reasons)?mapping.assessment_reasons:[];
  const reason=reasons.find(item=>typeof item==='string');
  if(typeof reason!=='string')return '';
  const key=reason.split(':',1)[0];
  return US_REASON_LABELS[key]??'来源、主体或时点证据仍有缺口';
}

export function businessStatusRows(value:ManagerWorkspace):BusinessStatusRow[]{
  const plan=object(value.plan_product), planAttempt=object(value.workspace_plan_attempt), announcement=object(value.announcement_observation);
  const announcementReview=object(value.announcement_review), ownerChain=object(value.owner_chain);
  const announcementOwner=object(ownerChain.announcements), officialOwner=object(announcementOwner.official_hkex);
  const us=object(value.us_market_attention), attention=object(value.research_attention);
  const planStatus=text(plan.status,'NOT_MATERIALIZED');
  const attemptMatches=typeof plan.run_id==='string'&&plan.run_id===planAttempt.run_id;
  const executionKind=attemptMatches?text(planAttempt.execution_kind,''):'';
  const planState=planStatus==='CURRENT'&&executionKind==='SCHEDULED_PREOPEN'?'已冻结':
    planStatus==='CURRENT'&&executionKind==='MANUAL_REFRESH'?'已保存研究草案（未正式冻结）':
    planStatus==='NOT_MATERIALIZED'?'未冻结':planStatus==='STALE_INPUTS_CHANGED'?'冻结产物已陈旧':'需核验';
  const planNext=planState==='已冻结'?'继续只读回放；不要用页面首显时间替代生成时间。':
    planState==='已保存研究草案（未正式冻结）'?'保留为次日研究预览；只在合法盘前窗口由现有 Manager owner 正式冻结。':
    '在合法盘前冻结窗口由现有 Manager owner 物化；晚间不得补成盘前。';
  const planDetail=`${planStatus}；${executionKind||'执行类型或运行身份未匹配'}；读取 ${text(object(value.read_context).status,'CANNOT_CONFIRM')}`;
  const annObserved=value.announcement_observation!==undefined&&value.announcement_observation!==null&&
    typeof value.announcement_observation==='object'&&!Array.isArray(value.announcement_observation);
  const annStatus=text(announcement.status,'UNREAD');
  const reviewGaps=Array.isArray(announcementReview.gaps)?announcementReview.gaps.filter(v=>typeof v==='string') as string[]:[];
  const announcementGaps=Array.isArray(announcement.gaps)?announcement.gaps.filter(v=>typeof v==='string') as string[]:[];
  const historyCoverageUnknown=announcementReview.status==='COVERAGE_UNKNOWN'||reviewGaps.includes('HISTORY_ANNOUNCEMENT_COVERAGE_UNKNOWN');
  const ownerObservedNotRun=announcementOwner.owner==='ManagerResearchJobService.refresh_announcements'&&
    announcementOwner.status==='NOT_RUN'&&officialOwner.source==='HKEX_OFFICIAL'&&officialOwner.status==='NOT_RUN'&&
    Array.isArray(announcementOwner.failure_reasons)&&announcementOwner.failure_reasons.includes('ANNOUNCEMENT_OWNER_NOT_RUN')&&
    officialOwner.attempt===null&&officialOwner.product_identity===null;
  const reviewObservedNotRun=announcementReview.schema_version==='v4.manager_research.announcement_review.v1'&&
    announcementReview.target_trade_date===value.target_trade_date&&announcementReview.status==='NOT_RUN'&&
    reviewGaps.includes('ANNOUNCEMENT_OWNER_NOT_RUN');
  const authoritativeNotRun=annObserved&&announcement.schema_version==='v4.manager_research.announcement_observation.v1'&&
    announcement.target_trade_date===value.target_trade_date&&annStatus==='NOT_RUN'&&ownerObservedNotRun&&reviewObservedNotRun&&!historyCoverageUnknown;
  const annCoverageUnknown=(historyCoverageUnknown&&(!annObserved||annStatus==='UNREAD'||annStatus==='NOT_RUN'))||annStatus==='COVERAGE_UNKNOWN'||
    (annStatus==='NOT_RUN'&&annObserved&&!authoritativeNotRun);
  const annUnread=!annObserved||annStatus==='UNREAD';
  const annAttempt=object(announcement.latest_attempt||announcement.attempt);
  const eastAttempt=object(announcement.eastmoney_hk_attempt);
  const eastStatus=text(announcement.eastmoney_hk_status,'NOT_RUN');
  const eastDocuments=Array.isArray(announcement.eastmoney_hk_documents)?announcement.eastmoney_hk_documents:null;
  const eastDocumentCount=eastDocuments===null?'未知':String(eastDocuments.length);
  const eastOnlyRun=authoritativeNotRun&&!Object.keys(annAttempt).length&&eastStatus!=='NOT_RUN';
  const annState=annCoverageUnknown?'无法确认':annUnread?'未读取':eastOnlyRun
    ?eastStatus==='PARTIAL'?'部分完成（Eastmoney 港股镜像）':
      eastStatus==='FAILED'||eastStatus==='READBACK_FAILED'?'Eastmoney 镜像失败（HKEX目录未运行）':'Eastmoney owner 已运行（HKEX目录未运行）'
    :annStatus==='NOT_RUN'&&authoritativeNotRun?'未运行':annStatus==='FAILED'||annStatus==='READBACK_FAILED'?'失败':annStatus.includes('PARTIAL')?'部分完成':annStatus==='SUCCEEDED_EMPTY'?'已完成空结果':annStatus==='SUCCEEDED'||annStatus==='READY'?'已运行':'待核验';
  const annWhen=text(annAttempt.finished_at,text(annAttempt.started_at,''));
  const eastWhen=text(eastAttempt.finished_at,text(eastAttempt.started_at,''));
  const annUnknownGap=historyCoverageUnknown?'HISTORY_ANNOUNCEMENT_COVERAGE_UNKNOWN':announcementGaps[0]||'ANNOUNCEMENT_COVERAGE_NOT_VERIFIED';
  const annDetail=annState==='未读取'
    ?'当前历史响应未提供 HKEX 公告 owner observation；不能解释为未运行或 0 条公告。'
    :annState==='无法确认'?`公告覆盖无法确认；原因 ${annUnknownGap}；不能归为未运行或 0 条公告。`
    :eastOnlyRun
    ?`HKEX目录未运行；Eastmoney港股镜像 ${eastStatus}；本次 cutoff 前已读回 ${eastDocumentCount} 条${eastWhen?`；最近尝试 ${eastWhen}`:''}；不是HKEX官方目录结果。`
    :annState==='未运行'?'没有 owner attempt；不是0公告。':`${annState}${annWhen?`；最近尝试 ${annWhen}`:''}`;
  const annNext=annState==='未读取'?'读取同一目标日期的 HKEX 官方 owner observation/receipt；缺字段不能推断未运行。'
    :annState==='无法确认'?'按同一目标日期与保存 cutoff 核对 HKEX 官方 owner 回执；Vibe RSS 与 Eastmoney 镜像不能替代。'
    :eastOnlyRun?'保留Eastmoney完整来源与状态；HKEX官方目录仍未运行、首次发布时间仍未确认。'
    :annState==='未运行'?'核对 binding/dispatch；获授权先经原API执行受限手动批次，自动启用另验，不等同采集已完成。'
    :annState==='失败'?'按 failure_reasons 修复后重试原 owner，不新建抓取器。':'继续保留覆盖、失败和原件引用。';
  const usStatus=text(us.status,'NOT_READ');
  const usRecheck=object(us.historical_source_recheck);
  const usWasRechecked=usRecheck.state==='COMPLETED_READ_ONLY_RECHECK';
  const mapping=object(attention.us_mapping_diagnostics||us.mapping_diagnostics);
  const assessment=usAssessmentState(mapping);
  const mappingCount=safeCount(mapping.accepted_hk_mapping_count);
  const materialInput=object(mapping.material_input||us.research_material_input);
  const sourceLabel=US_SOURCE_LABELS[usStatus]??'状态待核';
  const reason=usReason(mapping);
  const industryN=Array.isArray(us.raw_industry_up)?us.raw_industry_up.length:null;
  const individualN=Array.isArray(us.raw_individual_up)?us.raw_individual_up.length:null;
  const recheckDetail=usWasRechecked
    ?`；按保存cutoff ${text(usRecheck.research_cutoff,'未知')} 独立复核 ${text(usRecheck.checked_at,'时间未记录')}；未改原计划或选股`
    :'';
  const relationCountText=assessment==='ASSESSED_ZERO'?'合格关系 0 条（已完成评估）'
    :assessment==='ASSESSED_WITH_RELATIONS'?`合格关系 ${mappingCount??'已确认'} 条`
      :assessment==='INSUFFICIENT'?'合格关系数量暂不能确认':'合格关系尚未计算';
  const sourceCounts=typeof materialInput.source_material_record_count==='number'
    ?`；读取材料 ${materialInput.source_material_record_count} 条` : '';
  const connectCounts=typeof materialInput.pre_connect_material_card_count==='number'&&
      typeof materialInput.post_connect_material_card_count==='number'
    ?`；Connect资格核验前候选 ${materialInput.pre_connect_material_card_count} 张、核验后 ${materialInput.post_connect_material_card_count} 张` : '';
  const relationInputCount=typeof materialInput.research_relation_material_card_count==='number'
    ?`；关系评估输入 ${materialInput.research_relation_material_card_count} 张` : '';
  const reasonDetail=reason?`；${reason}`:'';
  const usDetail=`美股来源${sourceLabel}；行业上涨 ${industryN??'未知'} 个／个股上涨 ${individualN??'未知'} 个；${relationCountText}${sourceCounts}${connectCounts}${relationInputCount}${reasonDetail}${recheckDetail}`;
  const usNext=assessment==='NOT_EVALUATED'
    ?'等待同一目标日期的完整美股时段快照与关系材料输入，再开始评估；缺失输入不代表合格关系为零。'
    :assessment==='INSUFFICIENT'
      ?'补齐来源、主体和发布时间证据后重新评估；证据不足时不报告零关系。'
      :assessment==='ASSESSED_ZERO'
        ?'当前完整输入已完成双来源与发布时间核验，暂无合格关系；仅在新证据到达后重评。'
        :'保留已核关系及来源时点证据；该研究关系不改变Stage、正式选股或BUY。';
  const attentionStatus=text(attention.status,'CANNOT_CONFIRM');
  const laneLabels:Record<string,string>={STAGE:'Stage',CATALYST:'材料',CLOSE:'15:30',CLOSE_RECAPTURE:'盘后补采'};
  const laneStates:Record<string,string>={NOT_RUN:'未运行',RUNNING:'运行中',FAILED:'失败',PARTIAL:'部分完成',UNVERIFIED:'未核实',SUCCEEDED:'已完成',SUCCEEDED_EMPTY:'已完成空集',NOT_DUE:'未到执行时点',DUE_NO_ATTEMPT:'到期未尝试',DUE_RECEIPT_UNKNOWN:'到期回执待核',ARTIFACT_INVALID:'产物无效',SOURCE_READ_FAILED:'来源读取失败',SCHEDULE_UNVERIFIED:'时段待核',STAGE_ID_UNBOUND:'阶段身份待核',PRODUCT_AVAILABLE:'已有产物待依原合同读取',SKIPPED_NON_TRADING_DAY:'非交易日'};
  const lanes=Array.isArray(value.lanes)?value.lanes:[];
  const laneRows:BusinessStatusRow[]=lanes.filter(raw=>raw&&typeof raw==='object'&&!Array.isArray(raw)).map(raw=>{
    const lane=raw as JsonObject;const code=text(lane.lane,'UNKNOWN');const timing=object(lane.execution_timing);const rawState=code==='STAGE'?text(timing.execution_state,text(lane.state,'UNVERIFIED')):text(lane.state,'UNVERIFIED');
    const connectCalendarClosed=code==='STAGE'&&Array.isArray(timing.schedule_overview)&&timing.schedule_overview.some(rawSchedule=>{
      const schedule=object(rawSchedule);return object(schedule.calendar).hk_connect==='NON_TRADING_DAY';
    });
    const connectHolidayReceiptUnknown=connectCalendarClosed&&rawState==='DUE_RECEIPT_UNKNOWN';
    const reasons=Array.isArray(lane.failure_reasons)?lane.failure_reasons.filter(v=>typeof v==='string').slice(0,2) as string[]:[];
    const lastSuccess=text(lane.last_success_at,'未记录');const lastAttempt=text(lane.last_attempt_at,'未记录');
    const detail=`${rawState}${code==='STAGE'?`；产物状态 ${text(timing.artifact_status,'未知')}；时段 ${text(timing.schedule_state,'未知')}${connectHolidayReceiptUnknown?'；HK_CONNECT 日历 NON_TRADING_DAY；无需自然Connect阶段回执': ''}`:''}；最近成功 ${lastSuccess}；最近尝试 ${lastAttempt}${reasons.length?`；原因 ${reasons.join('；')}`:''}`;
    const next=connectHolidayReceiptUnknown?'当日港股通休市，无需自然Connect阶段回执；这不表示Stage已成功执行或正式选股为空。港股证券研究仍按独立来源展示，不作历史补写。':rawState==='NOT_DUE'?'等待原调度窗口，不要提前ensure或历史补写；当前缺产物不是执行失败。':rawState==='SUCCEEDED'||rawState==='SUCCEEDED_EMPTY'?'保留原owner回执；不要用当前页面时间替代历史成功时间。':'按原owner补齐/复验该lane产物；历史缺件不得用当前输入回填。';
    return {label:laneLabels[code]??code,state:connectHolidayReceiptUnknown?'港股通非交易日（无需自然阶段回执）':laneStates[rawState]??'需核验',detail,next};
  });
  return [
    {label:'计划',state:planState,detail:planDetail,next:planNext},
    {label:'公告',state:annState,detail:annDetail,next:annNext},
    {label:'美股',state:US_ASSESSMENT_LABELS[assessment],detail:usDetail,next:usNext},
    {label:'研究关注',state:attentionStatus,detail:`只读研究优先级；原screen/Stage/BUY不变。`,next:'继续核对证据时间、来源与缺口；不把分数当买入排名。'},
    ...laneRows,
  ];
}
