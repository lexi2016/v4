// Actual local received-material validator. Public vendor company.mjs stays disabled.
let expected=null,requestSerial=0;
const identityKeys=['symbol','source_date','observation_date','generation','input_sha256'];
export function setCompanyContext(value){expected=value;if(value===null)++requestSerial}
export function beginCompanyRequest(value){setCompanyContext({...value});return {serial:++requestSerial,identity:{...value}}}
export function isCurrentCompanyRequest(ticket){return ticket.serial===requestSerial&&expected&&identityKeys.every(key=>ticket.identity[key]===expected[key])}
export function renderCompanyStatus(document,status,symbol=''){
  const labels={LOADING:['正在读取公司材料…','正在读取财务与股东材料…'],MISSING:['公司解释材料尚未收录 · CANNOT_CONFIRM。','财务与股东材料尚未收录 · CANNOT_CONFIRM。'],ERROR:['公司材料读取失败 · CANNOT_CONFIRM，请稍后重新选择本股。','财务与股东材料读取失败 · CANNOT_CONFIRM，请稍后重新选择本股。'],IDLE:['未选择股票。','未选择股票。']};
  for(const [index,id] of ['companySummary','companyMetrics'].entries()){
    const host=document.getElementById(id);host.dataset.companyState=status;host.dataset.companySymbol=symbol;host.setAttribute('aria-busy',String(status==='LOADING'));
    if(status!=='READY'){const line=document.createElement('p');line.setAttribute('role','status');line.textContent=(symbol?symbol+' · ':'')+labels[status][index];host.replaceChildren(line);}
  }
  if(status!=='READY')document.getElementById('companyEvidence').replaceChildren();
}
export function validateCompany(value,symbol){
  if(!expected||value?.schema!=='V4_RECEIVED_COMPANY_VIEW_V1'||value.symbol!==symbol||symbol!==expected.symbol||value.source_date!==expected.source_date||value.observation_date!==expected.observation_date||value.generation!==expected.generation||value.input_sha256!==expected.input_sha256||value.RESEARCH_ONLY!==true||['production_allowed','buy_gate_updated','orders_sent'].some(k=>value[k]!==false))throw Error('LOCAL_COMPANY_IDENTITY_CONFLICT');
  return value;
}
export function explanationFacts(value){return [['主营业务',value.business.summary],...(value.facts??[])].filter(([,fact])=>fact&&Object.hasOwn(fact,'value'))}
export function independentTiming(fact){return fact?.disclosed_at?'原披露时间保留；首次可用时点/PIT未认证':'DISCLOSURE_TIME_UNKNOWN'}
