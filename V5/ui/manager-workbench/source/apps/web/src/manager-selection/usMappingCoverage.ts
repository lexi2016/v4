const object=(value:unknown):Record<string,unknown>=>value!==null&&typeof value==='object'&&!Array.isArray(value)?value as Record<string,unknown>:{};
const count=(value:unknown):string=>typeof value==='number'&&Number.isSafeInteger(value)&&value>=0?String(value):'未知';
const strings=(v:unknown):string[]=>Array.isArray(v)?v.filter((s):s is string=>typeof s==='string'):[];
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
  const audit=el('details','');audit.append(el('summary','覆盖口径、资格限制与原始凭证'));
  audit.append(el('h3','US 关系覆盖范围（研究观察）'),
    el('p',`来源范围：${label(value.scope)}；美股交易日 ${label(value.us_session_date)}；诊断状态 ${label(value.status)}。`),
    el('p',`已审关系键 ${compatible?count(value.reviewed_us_symbol_count):'未知'}；返回的关系键：${symbols.length?symbols.join('、'):'未知'}。仅配置样本内的已审关系，不代表全市场或更广泛 US/HK 关系已评估。`),
    el('p',`配置样本 ${ready?count(value.configured_sample_count):'未知'}；上涨个股 ${ready?count(value.rising_individual_count):'未知'}；已评估上涨个股 ${ready?count(value.assessed_rising_symbol_count):'未知'}；未评估上涨个股 ${ready?count(value.unassessed_rising_symbol_count):'未知'}。`),
    el('p',`目标日资格 CANNOT_CONFIRM（待确认）；natural_verified=${value.natural_verified===false?'false（未自然验证）':'未知（未确认）'}。这些数量不是正式候选数量。`),
    el('p','研究保存不等于正式选股（RESEARCH_SAVED_NOT_FORMAL_SELECTION）；保存是否成功以原计划读回状态为准。'));
  if(!compatible)audit.append(el('p','覆盖诊断缺失或合同不兼容，计数保持未知。'));
  host.append(el('h3','美股映射 · 港股研究线索'),
    el('p',`配置样本 ${ready?count(value.configured_sample_count):'未知'} · 上涨 ${ready?count(value.rising_individual_count):'未知'} · 已审关系范围内已评估 ${ready?count(value.assessed_rising_symbol_count):'未知'} · 范围外未评估 ${ready?count(value.unassessed_rising_symbol_count):'未知'}`),
    el('p',`已审范围：${symbols.length?symbols.join('、'):'未知'}。更广泛的美股—港股关系未评估；目标日资格待确认，未自然验证，仅供研究。`));
  const daily=object(object(mapping).daily_run);
  const matches=ready&&['COMPLETED','VALID_EMPTY'].includes(String(daily.status))&&Array.isArray(daily.matches)?daily.matches:[];
  const groups=new Map<string,Record<string,unknown>[]>();
  for(const raw of matches){const row=object(raw);if(typeof row.hk_symbol!=='string'||!/^HK\.\d{5}$/.test(row.hk_symbol))continue;
    const group=groups.get(row.hk_symbol)||[];group.push(row);groups.set(row.hk_symbol,group);}
  const types:Record<string,string>={PRODUCT_PEER:'产品同业（非供货关系）',DIRECT_NAMED_COMPONENT_SUPPLY:'已披露的具名部件供应',OPTICAL_TRANSPORT_PEER:'光传输同业（非供货关系）'};
  const cards=el('div','');cards.className='manager-us-result-grid';
  for(const [symbol,rows] of groups){
    const card=el('article','');card.dataset.usHkResult=symbol;
    card.append(el('h4',`${label(rows[0].hk_name)} · ${symbol}`));
    const clues=[...new Set(rows.map(row=>`${label(row.us_symbol)}${typeof row.change_pct==='number'&&Number.isFinite(row.change_pct)?` ${row.change_pct>0?'+':''}${row.change_pct.toFixed(2)}%`:' 涨幅未知'}`))];
    card.append(el('p',clues.join(' / ')));
    for(const kind of [...new Set(rows.map(row=>label(row.relationship_type)))])card.append(el('p',types[kind]||`关系性质：${kind}`));
    for(const reason of [...new Set(rows.map(row=>label(row.reason)))])card.append(el('p',reason));
    card.append(el('p','目标日资格待确认 · 非正式选股'));
    const sources=el('p','来源：');const seen=new Set<string>();
    for(const row of rows)for(const raw of Array.isArray(row.official_sources)?row.official_sources:[]){
      const source=object(raw);if(typeof source.url!=='string'||seen.has(source.url))continue;
      try{const url=new URL(source.url);if(!['https:','http:'].includes(url.protocol)||url.username||url.password)continue;
        seen.add(source.url);const link=el('a',typeof source.title==='string'&&source.title?source.title:'官方材料');
        link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';sources.append(link,document.createTextNode(' '));
      }catch{/* Invalid source remains in raw evidence, never an executable link. */}
    }
    if(!seen.size)sources.append(document.createTextNode('未提供可访问来源'));
    card.append(sources);
    const evidence=el('details','');evidence.append(el('summary','完整理由、产品阶段与限制'));
    for(const row of rows){evidence.append(el('p',label(row.maturity)));for(const limitation of strings(row.limitations))evidence.append(el('p',limitation));}
    evidence.append(el('pre',JSON.stringify(rows,null,2)));card.append(evidence);cards.append(card);
  }
  if(groups.size)host.append(cards);
  else host.append(el('p',ready&&daily.status==='VALID_EMPTY'?'本次已审关系范围内无匹配港股；不代表更广泛关系不存在。':'本次没有可展示的已确认匹配结果，数量未知。'));
  audit.append(el('pre',JSON.stringify({coverage_diagnostics:value,daily_run:daily},null,2)));host.append(audit);
  const reasons=Array.isArray(value.reason_codes)?value.reason_codes.filter((s):s is string=>typeof s==='string'):[];
  if(reasons.length)audit.append(el('p',`原拒绝或缺口理由：${reasons.join('；')}`));
}
