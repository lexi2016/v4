import type { JsonObject } from '../api/managerWorkspace';
const object=(value:unknown):JsonObject=>value!==null&&typeof value==='object'&&!Array.isArray(value)?value as JsonObject:{};
const label=(value:unknown):string=>value===null||value===undefined?'未知':String(value);
const day=(value:unknown):string=>typeof value==='string'&&/^\d{8}$/.test(value)?`${value.slice(0,4)}-${value.slice(4,6)}-${value.slice(6)}`:label(value);
const strings=(value:unknown):string[]=>Array.isArray(value)?value.filter((v):v is string=>typeof v==='string'):[];

/** Full-row aggregate, never a formal screen or candidate count. */
export function renderReboundPanelObservation(host:HTMLElement, input:unknown):void {
  host.replaceChildren();host.hidden=input===undefined||input===null;
  if(host.hidden)return;
  const el=<K extends keyof HTMLElementTagNameMap>(tag:K,text='')=>{const node=document.createElement(tag);node.textContent=text;return node;};
  const value=object(input);
  host.append(el('h3','原面板数值观察（未正式评估）'),
    el('p',`输入行情日期 ${day(value.signal_date)}；计划目标日 ${day(value.target_date)}；实际观察时点 ${label(value.observed_at)}。`),
    el('p',`服务端本次读取时点 ${label(value.observation_read_as_of)}；原计划研究截止 ${label(value.plan_research_cutoff)}。当前观察独立展示，不代表原计划当时已知，未写入保存计划。`),
    el('p','正式资格 CANNOT_CONFIRM；eligible_screen=null。仅当前读取的原生数值，不是正式候选，不代表全市场覆盖。单位、历史尺度、行情终态及目标日资格均未验证。'));
  const reasons=strings(value.reason_codes);
  if(reasons.length)host.append(el('p',`原产物缺口：${reasons.join('；')}`));
  const summary=object(value.row_summary);
  if(value.eligible_screen!==null||value.formal_status!=='CANNOT_CONFIRM'||typeof summary.observed_rows!=='number'||!Number.isInteger(summary.observed_rows)||summary.observed_rows<0){
    host.append(el('p','观察产物未接通或不适用于当前日期、历史视图或服务端读取时点；观察记录数未知，正式筛选保持原状态。'));return;
  }
  host.append(el('p',`观察记录 ${label(summary.observed_rows)} 条；输入不完整 ${label(summary.numeric_input_incomplete)} 条。以上是记录数，不是候选数。`));
  const missing=strings(summary.missing_history_dates);
  host.append(el('p',missing.length?`历史缺失日期：${missing.map(day).join('、')}。`:'未返回历史缺失日期；不据此认定历史尺度或正式资格已验证。'));
  const comparisons=object(summary.native_comparison_counts);
  for(const [key,title] of [['close_le_prior60_high_times_0_8','收盘≤此前60日高点×0.8'],['current_to_previous5_ge_1_5','当日量/此前5日均量≥1.5']]){
    const counts=object(comparisons[key]);
    host.append(el('p',`${title}：未知 ${label(counts.unknown)} 条；数值比较为真 ${label(counts.true)} 条；数值比较为假 ${label(counts.false)} 条。未据此评估正式资格。`));
  }
  host.append(el('p','此处展示全量记录汇总；完整逐行数值保留在绑定的独立观察产物，未截断计算输入，也未加入正式筛选。'));
  const evidence=el('details');evidence.append(el('summary','全量汇总缺口与原产物 SHA 引用'));
  let shown=false;evidence.addEventListener('toggle',()=>{if(evidence.open&&!shown){shown=true;evidence.append(el('pre',JSON.stringify({
    source_run_id:value.source_run_id,binding_reference:value.binding_reference,scope:value.scope,row_summary:summary},null,2)));}});
  host.append(evidence);
}
