// Actual local received-material validator. Public vendor company.mjs stays disabled.
let expected=null;
export function setCompanyContext(value){expected=value}
export function validateCompany(value,symbol){
  if(!expected||value?.schema!=='V4_RECEIVED_COMPANY_VIEW_V1'||value.symbol!==symbol||symbol!==expected.symbol||value.source_date!==expected.source_date||value.observation_date!==expected.observation_date||value.generation!==expected.generation||value.input_sha256!==expected.input_sha256||value.RESEARCH_ONLY!==true||['production_allowed','buy_gate_updated','orders_sent'].some(k=>value[k]!==false))throw Error('LOCAL_COMPANY_IDENTITY_CONFLICT');
  return value;
}
export function explanationFacts(value){return [['主营业务',value.business.summary],...(value.facts??[])].filter(([,fact])=>fact&&Object.hasOwn(fact,'value'))}
export function independentTiming(fact){return fact?.disclosed_at?'原披露时间保留；首次可用时点/PIT未认证':'DISCLOSURE_TIME_UNKNOWN'}
