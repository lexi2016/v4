/** Decision view of the EXISTING validated workspace. No scores, new stock
 * admission, quote inference, producer calls or Stage/BUY modifications.
 * A reason and all its conditions travel as a single proposition-bound bundle.
 */
import type { JsonObject, ManagerWorkspace, WorkspaceAction, WorkspaceStock } from '../../api/managerWorkspace.js';

export interface DecisionEvent {
  key: string;
  propositionIds: string[];
  evidenceIds: string[];
  reason: string;
  mechanism: string | null;
  kind: string;
  claim: string;
  current: boolean;
  inference: boolean;
  publishedAt: string | null;
  sources: JsonObject[];
  actions: WorkspaceAction[];
  next: string;
  invalidate: string;
}
export interface DecisionCard {
  row: WorkspaceStock;
  group: 'DIRECT' | 'COMPANY_CHANGE' | 'EXPECTATION' | 'INFERENCE' | 'BACKGROUND';
  primary: DecisionEvent | null;
  events: DecisionEvent[];
  market: string;
}
export const DECISION_GROUPS = [
  ['DIRECT','先核公司直接事件','来自原owner的公司直接事件；仍不代表价格或买入条件成立。'],
  ['COMPANY_CHANGE','先核具体公司变化','订单、价格、采购或合作等具体命题；优先核事件是否兑现，不按收益强弱排序。'],
  ['EXPECTATION','再核业绩与产品预期','预测、研究观点或尚缺具体节点的命题；与已发生的公司变化分开。'],
  ['INFERENCE','再核产业适用机制','主题与本股业务双证据映射；不是本公司新增订单。'],
  ['BACKGROUND','背景与原量价观察','不把旧背景或Stage入池当成当前公司催化。'],
] as const;

const records = (value: unknown): JsonObject[] => Array.isArray(value) ? value.filter(v=>v && typeof v==='object') as JsonObject[] : [];
const string = (value: unknown): string => typeof value==='string' ? value : '';
const timestamp = (value: unknown): number | null => {
  const input=string(value);
  if (!/(?:Z|[+-]\d{2}:\d{2})$/.test(input)) return null;
  const n=Date.parse(input);return Number.isFinite(n)?n:null;
};
function availableSource(source: JsonObject, ctx: JsonObject): boolean {
  const cutoff=timestamp(ctx.research_cutoff), published=timestamp(source.published_at);
  if(cutoff===null || published===null || published>cutoff)return false;
  return !['available_at','retrieved_at','collected_at','first_seen_at','archive_recorded_at'].some(k=>{
    const t=timestamp(source[k]);return t!==null && t>cutoff;
  });
}
function currentSource(source: JsonObject, ctx: JsonObject): boolean {
  const cutoff=timestamp(ctx.research_cutoff), start=timestamp(ctx.focus_window_start), published=timestamp(source.published_at);
  if(cutoff===null || start===null || published===null || published<start || published>cutoff)return false;
  return !['available_at','retrieved_at','collected_at','first_seen_at','archive_recorded_at'].some(k=>{
    const t=timestamp(source[k]);return t!==null && t>cutoff;
  });
}
export function conditionText(action: WorkspaceAction | undefined): string {
  if(!action)return '本事件未返回已绑定条件，不能借用其他事件的条件。';
  const marker=action.text.indexOf('）；');
  if(action.text.includes('原文「') && marker>=0)return action.text.slice(marker+2);
  const disclaimer='不宣称本股与主题公司存在新合同或合作。';
  if(action.assertion_type==='INDUSTRY_INFERENCE_NOT_COMPANY_EVENT' && action.text.includes(disclaimer))
    return action.text.slice(action.text.indexOf(disclaimer)+disclaimer.length);
  return action.text;
}
export function decisionEvents(stock: WorkspaceStock, ctx: JsonObject, themes: JsonObject[] = []): DecisionEvent[] {
  const props=new Map<string, {source:JsonObject; prop:JsonObject}>();
  for(const source of stock.evidence)for(const prop of records(source.propositions))
    props.set(string(prop.proposition_id),{source,prop});
  const bundles=new Map<string, WorkspaceAction[]>();
  for(const action of stock.plan.actions){
    if(action.supporting_quotes.some(q=>q.support_kind==='VERIFIED_MARKET_FIELDS'))continue;
    const key=`${action.assertion_type}|${[...action.proposition_ids].sort().join('|')}`;
    const list=bundles.get(key)||[];list.push(action);bundles.set(key,list);
  }
  const events:DecisionEvent[]=[];
  for(const [key,actions] of bundles){
    const watch=actions.find(a=>a.type==='WATCH');
    // A temporal note for another copy must not create a phantom event.
    if(!watch)continue;
    const own=watch.supporting_quotes.filter(q=>q.symbol===stock.symbol && q.support_kind!=='THEME_PROPOSITION');
    if(!own.length)continue;
    const entries=own.map(q=>props.get(string(q.proposition_id))).filter((v):v is {source:JsonObject;prop:JsonObject}=>Boolean(v));
    if(entries.length!==own.length)continue; // contract is still the authority
    const inference=watch.assertion_type==='INDUSTRY_INFERENCE_NOT_COMPANY_EVENT';
    const relation=stock.material_relations.find(m=>watch.proposition_ids.includes(string(m.issuer_proposition_id)) && watch.proposition_ids.includes(string(m.theme_proposition_id)));
    const evidenceIds=[...new Set(actions.flatMap(a=>a.evidence_ids))];
    const dates=entries.map(e=>string(e.source.published_at)).filter(Boolean).sort();
    const themeSources=themes.flatMap(t=>records(t.evidence)).filter(e=>
      watch.proposition_ids.includes(string(e.proposition_id)) && watch.evidence_ids.includes(string(e.evidence_id)));
    const current=inference ? relation?.window_status==='CURRENT_WINDOW_RESEARCH' &&
      entries.every(e=>availableSource(e.source,ctx)) && themeSources.some(e=>currentSource(e,ctx)) :
      entries.every(e=>currentSource(e.source,ctx) &&
        (!e.prop.event_date_claim || string(e.prop.event_date_claim)>=string(ctx.market_session)));
    const prop=entries[0]!.prop;
    events.push({key,propositionIds:[...watch.proposition_ids],evidenceIds,
      reason:own.map(q=>string(q.quote)).join('；'),
      mechanism:inference?string(relation?.reason)||'仅双证据产业推断，不是公司新事件。':null,
      kind:inference?'INDUSTRY_INFERENCE':string(prop.event_type),claim:string(prop.claim_status),
      current,inference,publishedAt:inference?string(relation?.theme_published_at)||null:dates[dates.length-1]||null,
      sources:[...new Set([...entries.map(e=>e.source),...themeSources])],actions,
      next:conditionText(watch),invalidate:conditionText(actions.find(a=>a.type==='INVALIDATE'))});
  }
  function order(e:DecisionEvent): number {
    if(e.inference)return stock.priority_basis.group==='INDUSTRY_INFERENCE' && e.current?0:4;
    const specific=/上调.*价格|mSAP.*订单|达成.*合作|签署.*协议|启动.*招标/i.test(e.reason);
    const headline=['ISSUER_RESEARCH','VALUATION_OPINION'].includes(e.kind)||/细节保密/.test(e.reason);
    return specific?1:headline?3:2;
  }
  return events.sort((a,b)=>Number(b.current)-Number(a.current) || order(a)-order(b) ||
    (timestamp(b.publishedAt)||0)-(timestamp(a.publishedAt)||0) || a.key.localeCompare(b.key));
}
export function decisionCards(value: ManagerWorkspace): DecisionCard[] {
  return value.stocks.map(row=>{
    const events=decisionEvents(row,(value.plan_context || {}) as JsonObject,value.themes),primary=events[0]||null;
    const expectation=primary && (primary.claim==='EXPECTATION_OR_PROPOSAL' || /预计|预期|有望|至少.*增长|能看到|四大新品|细节保密/.test(primary.reason));
    const group:DecisionCard['group']=!row.is_focus || !primary?.current?'BACKGROUND':
      row.priority_basis.group==='DIRECT_COMPANY_EVENT'?'DIRECT':
      row.priority_basis.group==='INDUSTRY_INFERENCE'?'INFERENCE':
      expectation || ['ISSUER_RESEARCH','VALUATION_OPINION'].includes(primary.kind)?'EXPECTATION':'COMPANY_CHANGE';
    return {row,group,primary,events,market:row.plan.trigger_price===null?'行情未核 · 无数值触发位':
      `历史参考收盘 ${row.plan.trigger_price} 港元；目标日承接另验`};
  });
}
export function screeningStatus(value: ManagerWorkspace['market_screen']): {complete:boolean;label:string} {
  if(!value || value.status==='CANNOT_CONFIRM' || !value.main_screen_ready)
    return {complete:false,label:'筛选未完成 · 数量未知（不是扫描后零候选）'};
  return {complete:true,label:`已核筛选：${value.cards.length}只（严格${value.strict.length}、近条件${value.near.length}）；待核历史${value.pending.length}只`};
}
export function scheduleLabel(next: JsonObject | null, cutoff: unknown): string {
  const when=timestamp(next?.next_at),limit=timestamp(cutoff);
  if(next?.verification==='OWNER_VERIFIED' && when!==null && limit!==null && when>limit)
    return `下一待执行：${string(next.next_at)}（原owner计划，不表示保证运行）`;
  return next?.next_at?`原调度参考：${string(next.next_at)}；不是已核未来动作`:'下一待执行时间未获原owner绑定';
}

export function decisionSummaryCounts(value: ManagerWorkspace): {current:number;background:number;total:number} {
  const cards=decisionCards(value);
  const background=cards.filter(card=>card.group==='BACKGROUND').length;
  return {current:cards.length-background,background,total:cards.length};
}
