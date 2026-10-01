import type { JsonObject, ManagerWorkspace } from '../api/managerWorkspace.js';

export interface BusinessStatusRow {label:string;state:string;detail:string;next:string;}
const object=(value:unknown):JsonObject=>value&&typeof value==='object'&&!Array.isArray(value)?value as JsonObject:{};
const text=(value:unknown,fallback='')=>typeof value==='string'&&value.trim()?value:fallback;

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
  const computed=mapping.status==='COMPUTED_BY_RELATION_LAYER';
  const rawCount=mapping.accepted_hk_mapping_count;
  const mappingCount=computed&&typeof rawCount==='number'&&Number.isSafeInteger(rawCount)&&rawCount>=0?rawCount:null;
  const sourceUsable=usStatus==='READY'||usStatus==='PARTIAL';
  const usState=usStatus==='NOT_READ'?'未读取':!sourceUsable?usStatus:
    mappingCount===null?(usWasRechecked?'来源已回查，关系尚未计算':'关系尚未计算'):
      mappingCount===0?'映射未形成':'映射已生成';
  const industryN=Array.isArray(us.raw_industry_up)?us.raw_industry_up.length:null;
  const individualN=Array.isArray(us.raw_individual_up)?us.raw_individual_up.length:null;
  const recheckDetail=usWasRechecked
    ?`；按保存cutoff ${text(usRecheck.research_cutoff,'未知')} 独立复核 ${text(usRecheck.checked_at,'时间未记录')}；未改原计划或选股`
    :'';
  const usDetail=`来源 ${usStatus}；行业上涨 ${industryN??'未知'}／个股上涨 ${individualN??'未知'}；有效关系 ${mappingCount??'未计算'}；${text(us.coverage_scope,'覆盖范围未知')}；session ${text(us.expected_us_session,'未知')}${recheckDetail}`;
  const usNext=usWasRechecked
    ?'这是按保存cutoff完成的只读owner复核；计划和选股保持原样。关系层未计算时不要把桥接原始信号当成HK映射。'
    :usStatus==='NOT_READ'?'该响应没有读取美股owner；不能用缺失字段报告为输入缺失。'
    :!sourceUsable?'补 exact-session owner/receipt，不放宽 session 或关系校验。'
    :mappingCount===null?'关系层未完成，桥接占位不代表零机会。'
    :mappingCount===0?'逐信号核候选原文、取得时间、主体及拒绝原因；补真实关系源或字段，不按正常零结果结案。'
    :'映射只是研究关系；核对双来源、方向与撤销条件，不升格为买入。';
  const attentionStatus=text(attention.status,'CANNOT_CONFIRM');
  const laneLabels:Record<string,string>={STAGE:'Stage',CATALYST:'材料',CLOSE:'15:30',CLOSE_RECAPTURE:'盘后补采'};
  const laneStates:Record<string,string>={NOT_RUN:'未运行',RUNNING:'运行中',FAILED:'失败',PARTIAL:'部分完成',UNVERIFIED:'未核实',SUCCEEDED:'已完成',SUCCEEDED_EMPTY:'已完成空集',NOT_DUE:'未到执行时点',DUE_NO_ATTEMPT:'到期未尝试',DUE_RECEIPT_UNKNOWN:'到期回执待核',ARTIFACT_INVALID:'产物无效',SOURCE_READ_FAILED:'来源读取失败',SCHEDULE_UNVERIFIED:'时段待核',STAGE_ID_UNBOUND:'阶段身份待核',PRODUCT_AVAILABLE:'已有产物待依原合同读取',SKIPPED_NON_TRADING_DAY:'非交易日'};
  const lanes=Array.isArray(value.lanes)?value.lanes:[];
  const laneRows:BusinessStatusRow[]=lanes.filter(raw=>raw&&typeof raw==='object'&&!Array.isArray(raw)).map(raw=>{
    const lane=raw as JsonObject;const code=text(lane.lane,'UNKNOWN');const timing=object(lane.execution_timing);const rawState=code==='STAGE'?text(timing.execution_state,text(lane.state,'UNVERIFIED')):text(lane.state,'UNVERIFIED');
    const reasons=Array.isArray(lane.failure_reasons)?lane.failure_reasons.filter(v=>typeof v==='string').slice(0,2) as string[]:[];
    const lastSuccess=text(lane.last_success_at,'未记录');const lastAttempt=text(lane.last_attempt_at,'未记录');
    const detail=`${rawState}${code==='STAGE'?`；产物状态 ${text(timing.artifact_status,'未知')}；时段 ${text(timing.schedule_state,'未知')}`:''}；最近成功 ${lastSuccess}；最近尝试 ${lastAttempt}${reasons.length?`；原因 ${reasons.join('；')}`:''}`;
    const next=rawState==='NOT_DUE'?'等待原调度窗口，不要提前ensure或历史补写；当前缺产物不是执行失败。':rawState==='SUCCEEDED'||rawState==='SUCCEEDED_EMPTY'?'保留原owner回执；不要用当前页面时间替代历史成功时间。':'按原owner补齐/复验该lane产物；历史缺件不得用当前输入回填。';
    return {label:laneLabels[code]??code,state:laneStates[rawState]??'需核验',detail,next};
  });
  return [
    {label:'计划',state:planState,detail:planDetail,next:planNext},
    {label:'公告',state:annState,detail:annDetail,next:annNext},
    {label:'美股',state:usState,detail:usDetail,next:usNext},
    {label:'研究关注',state:attentionStatus,detail:`只读研究优先级；原screen/Stage/BUY不变。`,next:'继续核对证据时间、来源与缺口；不把分数当买入排名。'},
    ...laneRows,
  ];
}
