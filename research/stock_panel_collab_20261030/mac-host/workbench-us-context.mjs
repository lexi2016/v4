// A display projection of the existing, receipt-verified same-origin API.
const compact=value=>String(value??'').replaceAll('-','');
const sha=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
const reference=value=>typeof value?.path==='string'&&value.path.startsWith('/')&&sha(value.sha256);
const sameRef=(a,b)=>a?.path===b?.path&&a?.sha256===b?.sha256;
const safe=value=>value?.RESEARCH_ONLY===true&&['production_allowed','buy_gate_updated','orders_sent'].every(key=>value[key]===false);
export function usMarketContext(value,day){
 const target=compact(day.observation_date);
 if(value?.schema_version!=='v3_5.global_industries.v2'||!['READY','PARTIAL'].includes(value.status)
   ||!['research_date','target_date','target_trade_date'].every(key=>compact(value[key])===target)
   ||!safe(value)||value.write_policy!=='read_only'||value.recommendation_status!=='RESEARCH_ONLY'
   ||!reference(value.artifact)||!reference(value.manifest)||!reference(value.receipt)
   ||!sameRef(value.artifact.manifest,value.manifest)||!sameRef(value.artifact.receipt,value.receipt)
   ||!/^\d{8}$/.test(value.us_session_date??'')||value.us_session_date!==value.capture_session_date
   ||compact(value.source_date)!==value.us_session_date||!Array.isArray(value.provider_session_dates)
   ||!value.provider_session_dates.length||!value.provider_session_dates.every(date=>compact(date)===value.us_session_date)
   ||!Number.isFinite(Date.parse(value.captured_at))||value.capture_phase!=='POST_CLOSE'
   ||!Number.isSafeInteger(value.available_board_count)||!Number.isSafeInteger(value.requested_board_count)
   ||value.available_board_count<0||value.requested_board_count<1||value.available_board_count>value.requested_board_count)throw Error('US_CONTEXT_DATE_SAFETY_OR_PROVENANCE_CONFLICT');
 return {status:value.status,summary:`已有当日美股板块 ${value.available_board_count}/${value.requested_board_count} · ${value.status} · 纽约session ${value.us_session_date}`,
   source_asof:`${value.us_session_date} America/New_York · ${value.capture_phase}`,recorded_at:value.captured_at,recorded_label:'采集',
   limitation:`${(value.cannot_confirm??[]).join('；')||'API未列附加缺口'}；仅作环境参考，公司关联仍 ${value.a_share_relation_status??'CANNOT_CONFIRM'}，不认证全覆盖或买点`,
   source:{artifact:value.artifact,manifest:value.manifest,receipt:value.receipt},research_date:target};
}
export function unknownUsContext(reason){return {status:'UNKNOWN',summary:'当日美股保存来源待核 · '+reason,limitation:'CANNOT_CONFIRM；未采用其他日期替代'};}
