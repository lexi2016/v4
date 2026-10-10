const object=(value:unknown):Record<string,unknown>=>value!==null&&typeof value==='object'&&!Array.isArray(value)?value as Record<string,unknown>:{};
const count=(value:unknown):string=>typeof value==='number'&&Number.isSafeInteger(value)&&value>=0?String(value):'未知';
const label=(value:unknown):string=>typeof value==='string'&&value.length>0?value:'未知';

/** Read-only scope diagnostics; never infers selection, market coverage or saved status. */
export function renderUsMappingCoverage(host:HTMLElement, mapping:unknown):void {
  host.replaceChildren();host.hidden=mapping===undefined||mapping===null;
  if(host.hidden)return;
  const value=object(object(mapping).coverage_diagnostics);
  const el=<K extends keyof HTMLElementTagNameMap>(tag:K,text:string)=>{const node=document.createElement(tag);node.textContent=text;return node;};
  const compatible=value.schema_version==='v5.us_mapping_scope.v1'
    &&value.scope==='PINNED_REVIEWED_RELATIONS_WITHIN_CONFIGURED_US_SAMPLE'
    &&value.full_market_coverage===false&&value.formal_eligible===false&&value.natural_verified===false;
  const ready=compatible&&value.status==='PARTIAL';
  const symbols=compatible&&Array.isArray(value.reviewed_us_symbols)?value.reviewed_us_symbols.filter((s):s is string=>typeof s==='string'):[];
  host.append(el('h3','US 关系覆盖范围（研究观察）'),
    el('p',`来源范围：${label(value.scope)}；美股交易日 ${label(value.us_session_date)}；诊断状态 ${label(value.status)}。`),
    el('p',`已审关系键 ${compatible?count(value.reviewed_us_symbol_count):'未知'}；返回的关系键：${symbols.length?symbols.join('、'):'未知'}。仅配置样本内的已审关系，不代表全市场或更广泛 US/HK 关系已评估。`),
    el('p',`配置样本 ${ready?count(value.configured_sample_count):'未知'}；上涨个股 ${ready?count(value.rising_individual_count):'未知'}；已评估上涨个股 ${ready?count(value.assessed_rising_symbol_count):'未知'}；未评估上涨个股 ${ready?count(value.unassessed_rising_symbol_count):'未知'}。`),
    el('p',`目标日资格 CANNOT_CONFIRM（待确认）；natural_verified=${value.natural_verified===false?'false（未自然验证）':'未知（未确认）'}。这些数量不是正式候选数量。`),
    el('p','研究保存不等于正式选股（RESEARCH_SAVED_NOT_FORMAL_SELECTION）；保存是否成功以原计划读回状态为准。'));
  if(!compatible)host.append(el('p','覆盖诊断缺失或合同不兼容，计数保持未知。'));
  const reasons=Array.isArray(value.reason_codes)?value.reason_codes.filter((s):s is string=>typeof s==='string'):[];
  if(reasons.length)host.append(el('p',`原拒绝或缺口理由：${reasons.join('；')}`));
}
