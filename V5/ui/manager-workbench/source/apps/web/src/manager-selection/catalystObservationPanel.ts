import { beijingTime, strategySummary } from './managerStrategySummary';
import { renderUsMappingCoverage } from './usMappingCoverage';
import { renderReboundPanelObservation } from './reboundPanelObservation';
import { renderAnnouncementReview } from './announcementObservation.js';
import { renderResearchAttention } from './researchAttention.js';
import type { ResearchAttention, SelectionDiagnostics, UsMappingResearch, UsMarketAttention } from '../api/managerWorkspace.js';
import { businessStatusRows } from './businessStatus.js';
import { normalizedWorkspaceDay, readDailyDateBindings, renderDailyChannels, sameDailyDateBindings,
  type WorkspaceDateBindings } from './dailyChannels.js';
/** Stock-keyed panel inside the EXISTING ManagerSelectionView host.
 * The original Stage table/rank/BUY gate remain outside this DOM boundary.
 * Cross-date/view and source failures clear cards. Same-view re-read may retain
 * an explicitly labelled previous qualified result; it is never relabelled current.
 */
import { requestManagerAnnouncements, refreshManagerAnnouncements, requestManagerWorkspace, refreshManagerWorkspace, isManagerWorkspaceReadOnly, type ManagerWorkspace, type WorkspaceLane, type JsonObject, type ReboundScreen } from '../api/managerWorkspace.js';
import { requestManagerAnnouncementAnalysis } from '../api/managerAnnouncementAnalysis.js';
import { renderAnnouncementAnalysis } from './announcementAnalysis.js';

import { decisionCards, decisionSummaryCounts, DECISION_GROUPS, screeningStatus, scheduleLabel, conditionText, type DecisionCard, type DecisionEvent } from './adapters/workspaceDecision.js';

const states: Record<string, string> = {NOT_RUN:'未运行', RUNNING:'运行中', FAILED:'运行失败', PARTIAL:'部分成功',
  UNVERIFIED:'运行证据不足', SUCCEEDED:'运行成功', SUCCEEDED_EMPTY:'运行成功 · 零候选'};
// Preserve the existing finite GET/POST UI deadline. Backend cancellation is
// cooperative between original-owner calls, not a guarantee of thread preemption.
const WORKSPACE_REQUEST_TIMEOUT_MS = 180_000;
const laneNames: Record<string, string> = {STAGE:'阶段固定池', CATALYST:'补充催化产物', CLOSE:'尾盘量价', CLOSE_RECAPTURE:'盘后补采（研究观察）', MATERIAL:'既有材料发现'};
const short=(value:string,limit=240)=>value.length>limit?value.slice(0,limit)+'…':value;
const text = (value: unknown, absent = '未提供') => typeof value === 'string' && value ? value : absent;
const timeText = beijingTime;
const numberText = (value: unknown, digits = 4) => typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '未知';
const scalarText = (value: unknown, absent = '未提供') => typeof value === 'number' && Number.isFinite(value) ? String(value) : text(value, absent);

const historyReason=(reason:unknown):string=>({
  HISTORY_QUALIFIED_SAVED_PLAN_MISSING:'缺少截止前合格保存计划；历史读取不会用后续材料补写。',
  HISTORY_SOURCE_INPUTS_CHANGED:'保存计划对应的来源已变化，不能沿用旧结论。',
  HISTORY_FROZEN_PROJECTION_CHANGED:'冻结内容与原来源重验结果不一致，拒绝展示旧结论。',
  HISTORY_READER_VERSION_CHANGED:'原读取或校验源码版本已变化，旧计划不能直接沿用。',
  HISTORY_MATERIAL_PIT_UNVERIFIED:'原材料缺当时可用时间，或包含截止后的信息。',
  HISTORY_SOURCE_VALIDATION_FAILED:'原来源校验未通过，请核对原owner证据。',
} as Record<string,string>)[String(reason)] || '历史计划未通过完整性或时点校验；具体拒绝原因保留在审计详情。';

export interface ThemeMappingGroup {
  key: string;
  representative: JsonObject;
  mappings: JsonObject[];
}

function mappingAdmission(mapping: JsonObject): JsonObject {
  return mapping.mapping_admission && typeof mapping.mapping_admission === 'object' && !Array.isArray(mapping.mapping_admission)
    ? mapping.mapping_admission as JsonObject
    : {};
}

function mappingMechanism(mapping: JsonObject): string {
  const admission = mappingAdmission(mapping);
  return text(mapping.reason, text(admission.mechanism, ''));
}

/**
 * Group only identical display propositions. Raw mapping objects stay attached
 * to each group so relation and provenance can be inspected from the panel.
 * Publication timestamps are deliberately omitted from the key: the semantic
 * time role is window_status, while exact timestamps remain in the raw rows.
 */
export function groupThemeMappings(theme: JsonObject): ThemeMappingGroup[] {
  const groups = new Map<string, ThemeMappingGroup>();
  for (const mapping of (theme.mappings || []) as JsonObject[]) {
    const admission = mappingAdmission(mapping);
    const key = JSON.stringify([
      text(theme.theme, ''),
      text(mapping.symbol, ''),
      text(mapping.relationship_type, ''),
      mappingMechanism(mapping),
      text(admission.reason_code, ''),
      text(admission.scope, ''),
      text(mapping.issuer_quote, ''),
      text(mapping.theme_quote, ''),
      text(mapping.window_status, ''),
    ]);
    const group = groups.get(key);
    if (group) group.mappings.push(mapping);
    else groups.set(key, { key, representative: mapping, mappings: [mapping] });
  }
  return [...groups.values()];
}

export function mountCatalystObservations(host: HTMLElement, initialDate: string): () => void {
  // Source/selection display, publication evidence and plan target are separate bindings.
  const params=new URLSearchParams(window.location.search);
  const selectedDates=readDailyDateBindings(params,initialDate);
  let fallbackAnnouncementDate=normalizedWorkspaceDay(params.get('publication_date'))
    ?? normalizedWorkspaceDay(params.get('date')) ?? normalizedWorkspaceDay(initialDate)!;
  let publicationDate=selectedDates.bindings.announcement_date;
  let selectionDate=selectedDates.bindings.selection_date;
  let explicitDates=selectedDates.explicit;
  let date=selectedDates.bindings.plan_date;
  const displayBindings=():WorkspaceDateBindings=>({plan_date:date,selection_date:selectionDate,announcement_date:publicationDate});
  const requestedAnalysisDate=params.get('announcement_date');
  let analysisPublicationDate=requestedAnalysisDate && /^\d{8}$/.test(requestedAnalysisDate)
    ? requestedAnalysisDate : undefined;
  let analysisSequence=0;let analysisController:AbortController|null=null;
  let disposed = false; let sequence = 0; let controller: AbortController | null = null;
  let announcementController:AbortController|null=null;let announcementSequence=0;
  let announcementRefreshController:AbortController|null=null;
  let announcementRefreshTimer:ReturnType<typeof setTimeout>|undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let currentValue: ManagerWorkspace | null = null;
  let generationUnconfirmed = false;
  const readView=(value:string|null):'auto'|'dynamic'=>value==='dynamic'?'dynamic':'auto';
  let view = readView(params.get('view'));
  let loadedView: 'auto'|'dynamic' | null = null;
  let sourceFilter: 'ALL'|'STAGE'|'MATERIAL'|'CLOSE' = 'ALL';
  const el = <K extends keyof HTMLElementTagNameMap>(tag: K, content = '', className = '') => {
    const node = document.createElement(tag); node.textContent = content; node.className = className; return node;
  };
  const details = (title: string, value: unknown) => {
    const node = el('details'); node.append(el('summary',title));
    let loaded=false;node.addEventListener('toggle',()=>{if(node.open && !loaded){loaded=true;node.append(el('pre',JSON.stringify(value,null,2)));}});
    return node;
  };
  const paragraph = (label: string, values: string[]) => el('p',`${label}：${values.join('；')}`);
  const panel = el('section','','manager-catalyst-observations'); panel.setAttribute('aria-label','本计划研究关注');
  const header = el('header'); header.append(el('h2','本计划研究关注'));
  const style=el('style',`.manager-catalyst-observations{min-width:0;overflow-wrap:anywhere}.manager-catalyst-observations header{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.manager-catalyst-observations h2{flex-basis:100%}.manager-catalyst-observations article{min-width:0;border:1px solid #d4dde4;border-radius:8px;padding:14px;margin:12px 0}.manager-catalyst-observations pre{white-space:pre-wrap;overflow-wrap:anywhere}.manager-catalyst-observations blockquote{margin:8px 0;padding:8px 12px;border-left:3px solid #8098a9}.manager-us-result-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,260px),1fr));gap:12px}.manager-us-result-grid article{margin:0}.manager-us-result-grid a{display:inline-block;max-width:100%;margin-right:8px}.manager-catalyst-observations select{max-width:100%}.manager-catalyst-observations details{margin:8px 0}.manager-catalyst-observations summary{cursor:pointer}.manager-catalyst-observations button,.manager-catalyst-observations input{min-height:36px}`);
  const readButton = el('button','读取更新'); readButton.type='button';
  const refreshButton = el('button','用既有材料生成计划'); refreshButton.type='button'; refreshButton.disabled=true;
  const dateLabel=el('label','计划目标日：');const planDate=el('input');planDate.type='date';planDate.setAttribute('aria-label','计划目标日');
  planDate.value=`${date.slice(0,4)}-${date.slice(4,6)}-${date.slice(6,8)}`;
  dateLabel.append(planDate);
  const viewLabel=el('label','读取口径：');const viewSelect=el('select');viewSelect.setAttribute('aria-label','历史或现在回看');
  for(const [key,label] of [['auto','当时历史 / 当日预览'],['dynamic','现在回看（可能含后续消息）']]) {
    const option=el('option',label);option.value=key;viewSelect.append(option);
  }
  viewSelect.value=view;
  viewLabel.append(viewSelect);
  const cancelButton=el('button','取消本次读取');cancelButton.type='button';cancelButton.hidden=true;
  const planActions=el('details');planActions.append(el('summary','计划操作'),refreshButton,el('p','计划日独立于原Stage来源日期；生成计划不代表正式选股。'));
  header.append(dateLabel,readButton,viewLabel,cancelButton,planActions);
  const status = el('p'); status.setAttribute('role','status'); status.setAttribute('aria-live','polite');
  const dailyChannels=el('section');renderDailyChannels(dailyChannels,undefined,displayBindings());
  const runs = el('div','','manager-catalyst-cards'); runs.setAttribute('aria-label','三路运行状态');
  const runSummary=el('p');runSummary.setAttribute('aria-label','三路状态摘要');
  const decisionSummary=el('p','','decision-summary');decisionSummary.setAttribute('aria-label','当前候选摘要');
  const businessStatus=el('section','','business-status');businessStatus.setAttribute('aria-label','业务闭环状态');
  const researchFocus=el('section','','manager-research-focus');researchFocus.setAttribute('aria-label','次日重点研究名单');
  const closeRecapture=el('section','','manager-close-recapture');closeRecapture.setAttribute('aria-label','盘后补采研究观察');
  const filters=el('div','','decision-filters');filters.setAttribute('aria-label','关注来源筛选');
  const filterCount=el('span');filterCount.setAttribute('aria-live','polite');
  for(const [key,label] of [['ALL','全部关注'],['STAGE','Stage来源'],['MATERIAL','材料来源'],['CLOSE','15:30尾盘来源']] as const){
    const button=el('button',label);button.type='button';button.dataset.decisionFilter=key;button.setAttribute('aria-pressed',String(key===sourceFilter));
    button.addEventListener('click',()=>{sourceFilter=key;
      for(const b of filters.querySelectorAll<HTMLButtonElement>('button[data-decision-filter]')) b.setAttribute('aria-pressed',String(b.dataset.decisionFilter===sourceFilter));
      if(currentValue)renderStocks(currentValue);
      if(panel.dataset.readState==='UPDATING' || panel.dataset.readState==='STALE') filterCount.textContent='上次结果 · '+filterCount.textContent;
    });filters.append(button);
  }
  filters.append(filterCount);
  const runDetails=el('details');runDetails.dataset.runtimeDetails='true';runDetails.append(el('summary','三路原owner运行详情'),runs);
  const stocks = el('div','','manager-catalyst-cards'); stocks.setAttribute('aria-label','去重股票');
  const panelObservation=el('section');panelObservation.setAttribute('aria-label','原面板数值观察');panelObservation.hidden=true;
  const screen = el('section'); screen.setAttribute('aria-label','REBOUND_V3量价筛选');
  const background=el('details');background.dataset.background='true';const backgroundSummary=el('summary','其余背景与量价观察');const backgroundBody=el('div');background.append(backgroundSummary,backgroundBody);
  const reboundStrategySummaryNode=el('summary','超跌反弹选股（独立策略；与15:30尾盘来源分开）');
  const strategy=el('details');strategy.dataset.reboundStrategy='true';strategy.open=false;strategy.append(reboundStrategySummaryNode,screen);
  const usMappingCoverage=el('section');usMappingCoverage.setAttribute('aria-label','US 关系覆盖范围');usMappingCoverage.hidden=true;
  const researchAttentionSection=el('section');
  renderResearchAttention(researchAttentionSection,undefined,undefined);
  const announcementSection=el('section');
  renderAnnouncementReview(announcementSection,undefined,publicationDate,undefined,updateAnnouncementReview);
  const announcementAnalysisSection=el('section');
  renderAnnouncementAnalysis(announcementAnalysisSection,undefined,analysisPublicationDate,undefined,selectAnalysisDate);
  const companyEvents=el('section');companyEvents.setAttribute('aria-label','重要公司事件摘要');
  const themes = el('section'); themes.setAttribute('aria-label','主题与待映射材料');
  const audit = el('details'); audit.append(el('summary','来源覆盖、运行身份与缺件'));
  const auditBody = el('div'); audit.append(auditBody);
  const themeDetails=el('details');themeDetails.dataset.policyDetails='true';themeDetails.append(el('summary','政策与产业线索：适用公司、原文及缺口'),themes);
  const provenance=el('details');provenance.append(el('summary','原owner状态与公司原始分类'),runSummary,runDetails,companyEvents);
  const resultDates=el('p');resultDates.setAttribute('aria-label','研究数据日期');
  const announcementGroup=el('details');announcementGroup.dataset.strategySummary='ANNOUNCEMENT';
  const announcementSummary=el('summary',strategySummary(undefined,'ANNOUNCEMENT'));
  let analysisReadFailed=false;
  const updateAnnouncementSummary=()=>{announcementSummary.textContent=strategySummary(currentValue,'ANNOUNCEMENT')+(analysisReadFailed?' · 解析服务读取失败，详情内保留原因':'');};
  announcementGroup.append(announcementSummary,announcementAnalysisSection);
  const legacyAnnouncement=el('details');legacyAnnouncement.append(el('summary','原始公告目录与有限范围补采操作'),announcementSection);
  announcementGroup.append(legacyAnnouncement);
  const oversoldGroup=el('details');oversoldGroup.dataset.strategySummary='OVERSOLD';
  const oversoldSummary=el('summary',strategySummary(undefined,'OVERSOLD'));
  oversoldGroup.append(oversoldSummary,strategy,panelObservation);
  const originalDetails=el('details');originalDetails.dataset.originalResearch='true';
  originalDetails.append(el('summary','其他研究材料与分路状态（各自口径，非 US 映射结论）'),
    el('p','以下旧研究关注、HK_CONNECT与材料诊断各有独立口径；本次已审 US 关系的评估结果以上方美股映射区为准，不能用其他分路的未评估状态替代。'),dailyChannels,businessStatus,researchFocus,closeRecapture,decisionSummary,filters,stocks,background,researchAttentionSection,themeDetails,provenance,audit,el('p','仅研究：事件成立与行情承接、BUY准入分开。未核同口径量价不报触发价；不因高开远离可靠参考位追入，也不预设一定回踩。未读取仓位、未发订单。'));
  panel.append(style,header,status,resultDates,announcementGroup,oversoldGroup,usMappingCoverage,
    el('p','研究结果不等于正式选股；目标日资格与自然运行尚待验证。未发出交易指令。','decision-safety'),originalDetails);
  host.replaceChildren(panel);

  function lane(row: WorkspaceLane): HTMLElement {
    const node = el('article','','manager-catalyst-card'); node.dataset.lane=row.lane; node.dataset.state=row.state;
    node.append(el('h3',`${laneNames[row.lane] || row.lane} · ${states[row.state]}`),
      el('p',`原owner目标日：${row.target_date} ｜ ${row.stock_count === null ? '覆盖尚不可计数' : `${row.stock_count}只股票`}`),
      el('p',`原owner：${row.owner}`),el('p',`最近尝试：${text(row.last_attempt_at,'无可验证开始记录')}；最近成功产物：${text(row.last_success_at,'无可验证成功记录')}`));
    if (row.state === 'RUNNING') node.append(el('p','已有开始回执，尚无结束回执；进程是否仍存活未核验。'));
    if (row.previous_product_retained === true) node.append(el('p','本次运行未成功结束；下方保留的仅是此前已核验产物。'));
    node.append(el('p',scheduleLabel(row.next_plan,(currentValue?.plan_context as JsonObject | undefined)?.research_cutoff)));
    if (row.failure_reasons.length) node.append(el('p',`缺项或失败 ${row.failure_reasons.length}项；展开运行详情定位。`));
    node.append(details('运行详情：输入覆盖、run_id与失败原因',row));
    return node;
  }
  function sourceLink(url: unknown): HTMLElement | null {
    if (typeof url !== 'string') return null;
    try {
      const u=new URL(url);
      if (!['https:','http:'].includes(u.protocol) || u.username || u.password) return null;
      const a=el('a','原始来源'); a.href=u.href; a.target='_blank'; a.rel='noopener noreferrer'; return a;
    } catch { return null; }
  }
  function evidence(row: JsonObject): HTMLElement {
    const node=el('section'); node.append(el('h4',text(row.source_title,text(row.title,'归档原文'))),el('p',text(row.mapping_reason,'')));
    const timing=row.temporal_role === 'NEW_PLAN_PUBLICATION' ? '重点窗口新增发布（非目标日实时捕获）' :
      row.temporal_role === 'BACKGROUND' ? '窗口前背景（不计新增）' :
      row.temporal_role === 'PUBLICATION_UNKNOWN' ? '发布时间未知（不计新增）' :
      row.temporal_classification === 'CAPTURED_AT_TARGET' ? '目标时段已归档' :
      row.temporal_classification === 'AFTER_CLOSE_RESEARCH' ? '盘后材料，不回填当日早盘' : '补充背景／事后研究，不当作当时捕获';
    node.append(el('p',timing),el('p',`发布时间：${text(row.published_at,text(row.published_date,'未验证'))}；本机取得：${text(row.retrieved_at,'未验证')}；系统可用：${text(row.available_at,'未验证')}`));
    if(row.collected_at || row.first_seen_at)node.append(el('p',`原owner collected_at：${text(row.collected_at)}；first_seen_at：${text(row.first_seen_at)}。与retrieved_at/available_at分列，不推定历史可用。`));
    const a=sourceLink(row.source_url); if(a)node.append(a);
    if(row.evidence_quote)node.append(el('blockquote',text(row.evidence_quote)));
    node.append(details('本关系原始时间、来源与SHA',row)); return node;
  }
  function eventView(event: DecisionEvent): HTMLElement {
    const block=el('section','','decision-event');block.dataset.eventKey=event.key;
    block.dataset.propositionIds=JSON.stringify(event.propositionIds);
    block.append(el('h4',event.inference?'产业机制（非公司新事件）':'本事件的理由与条件'),el('blockquote',event.reason));
    if(event.mechanism)block.append(el('p',event.mechanism));
    block.append(el('p',`${event.inference?'主题发布（业务原文时间见来源）：':''}${event.current?'计划窗口内发布':'历史背景／未确认在计划窗口内'} · ${text(event.publishedAt)} · ${event.claim==='EXPECTATION_OR_PROPOSAL'||/预计|预期|有望|能看到|至少.*增长|潜在/.test(event.reason)?'研究预期，非已实现':event.inference?'行业推断':'原文陈述，未等同正式公告'}`));
    for(const type of ['WATCH','WAIT','INVALIDATE']){
      const matching=event.actions.filter(a=>a.type===type);
      for(const action of matching)block.append(el('p',`${type==='WATCH'?'等待确认':type==='WAIT'?'本事件限制':'撤销依据'}：${conditionText(action)}`));
      if(!matching.length && type!=='WAIT')block.append(el('p',`${type==='WATCH'?'等待确认':'撤销依据'}：本事件缺已绑定条件，不借其他事件补齐。`));
    }
    // Readable original prose and actual URLs first; raw JSON is a second step.
    const readable=el('details');readable.dataset.readableSources='true';readable.append(el('summary','来源原文与时间'));
    for(const source of event.sources)readable.append(evidence(source));
    const themes=event.actions.find(a=>a.type==='WATCH')?.supporting_quotes.filter(q=>q.support_kind==='THEME_PROPOSITION') || [];
    for(const quote of themes)readable.append(el('p','对应主题原文（不是本公司事件）'),el('blockquote',text(quote.quote)));
    readable.append(details('技术定位：该事件全部条件、evidence_id与命题范围',event.actions));block.append(readable);return block;
  }
  function stock(card: DecisionCard): HTMLElement {
    const row=card.row, primary=card.primary;
    const node=el('details','','decision-stock');node.dataset.stockKey=row.stock_key;node.dataset.decisionGroup=card.group;
    const summary=el('summary');summary.append(el('strong',`${row.name} · ${row.symbol}`,'decision-name'),
      el('span',primary?primary.reason:'只有原Stage／量价记录；未提供公司催化','decision-reason'),
      el('span',primary?primary.next:'等待本股公司原文或原Stage下一份正式产物；不把入池当催化。','decision-next'),
      el('span',`${primary?.current?'窗口内发布':'背景/量价来源'} · ${primary?.publishedAt?primary.publishedAt.slice(5,16).replace('T',' '):'时点缺失'} ｜ ${card.market}`,'decision-state'));
    node.append(summary);
    let loaded=false;node.addEventListener('toggle',()=>{
      if(!node.open || loaded)return;loaded=true;
      const body=el('div','','decision-stock-body');
      body.append(el('p',`比较依据：${DECISION_GROUPS.find(g=>g[0]===card.group)?.[2] || '证据不足'} 同组未做收益排序。`));
      if(primary)body.append(eventView(primary));
      else body.append(el('p','本股没有已准入公司命题；原Stage记录只提供量价来源，不生成虚构公司行动条件。'));
      for(const event of card.events.slice(1)){
        const extra=el('details');extra.dataset.otherEvent='true';extra.append(el('summary',`${event.current?'另一窗口内事件':'背景事件'}：${short(event.reason,100)}`));
        let opened=false;extra.addEventListener('toggle',()=>{if(extra.open&&!opened){opened=true;extra.append(eventView(event));}});body.append(extra);
      }
      body.append(el('p',card.market));
      if(row.plan.trigger_price!==null){
        body.append(el('p',`失效参考低点：${row.plan.invalidation_price===null?'数据缺失':row.plan.invalidation_price+'港元'}。历史参考，不表示目标日已触发。`));
        body.append(details('独立行情依据与口径',row.plan.price_provenance));
      }
      const missing=el('details');missing.append(el('summary',`本股尚缺资料（${row.plan.missing.length}项）`),paragraph('缺项',row.plan.missing));body.append(missing);
      const all=el('details');all.append(el('summary',`全部关系原文（${row.evidence.length}条；不按转载数升档）`));
      let sourcesLoaded=false;all.addEventListener('toggle',()=>{if(all.open&&!sourcesLoaded){sourcesLoaded=true;all.append(...row.evidence.map(evidence));}});body.append(all);
      if(row.stage_observation)body.append(details('原Stage：rank、score及BUY未改',row.stage_observation));
      if(row.close_observation)body.append(details('原尾盘观察；不等于收盘确认',row.close_observation));
      body.append(details('本股完整可追溯预案与来源分类',row));node.append(body);
    });return node;
  }
  function renderStocks(value: ManagerWorkspace): void {
    const all=decisionCards(value);
    const matching=all.filter(c=>sourceFilter==='ALL' || sourceFilter==='STAGE'&&c.row.stage_observation!==null ||
      sourceFilter==='MATERIAL'&&c.row.evidence.length>0 || sourceFilter==='CLOSE'&&c.row.close_observation!==null);
    const front=sourceFilter==='ALL'?matching.filter(c=>c.group!=='BACKGROUND'):matching;
    const other=sourceFilter==='ALL'?matching.filter(c=>c.group==='BACKGROUND'):[];
    stocks.replaceChildren();backgroundBody.replaceChildren();background.open=false;background.hidden=!other.length;
    for(const [group,label,why] of DECISION_GROUPS){
      const members=front.filter(c=>c.group===group);if(!members.length)continue;
      const section=el('section','','decision-group');section.dataset.group=group;
      section.append(el('h3',`${label}（${members.length}）`),el('p',why,'decision-group-note'),...members.map(stock));stocks.append(section);
    }
    backgroundSummary.textContent=`背景与原量价观察（${other.length}；不升为公司催化）`;
    backgroundBody.replaceChildren(...other.map(stock));
    const countKnown=((value.read_context || {}) as JsonObject).candidate_count_known!==false;
    filterCount.textContent=countKnown?`当前列表 ${front.length}只${other.length?' · 另有背景'+other.length+'只':''}`:'覆盖未知 · 不是0候选';
    for(const button of filters.querySelectorAll<HTMLButtonElement>('button[data-decision-filter]'))
      button.setAttribute('aria-pressed',String(button.dataset.decisionFilter===sourceFilter));
    if(!front.length){
      const close=value.lanes.find(l=>l.lane==='CLOSE');
      stocks.append(el('p',!countKnown?'该日期的来源尚未验证或计划缺件，候选数量未知。':sourceFilter==='CLOSE' && close?.state!=='SUCCEEDED_EMPTY'?
        '当日15:30尾盘无有效结果；缺精确快照或原owner闭包，不是扫描完成后零候选。'+(close?.failure_reasons.includes('EXACT_1530_SNAPSHOT_WINDOW_MISSED')?' 已错过精确15:30快照窗口，不补造历史数据。':''):
        sourceFilter==='CLOSE'?'原owner已验证成功空集；本筛选显示0只。':'当前来源没有可显示的窗口内公司关注；背景记录单列，不凑名单。','decision-empty'));
    }
  }
  function renderCloseRecapture(value: ManagerWorkspace): void {
    const root=value as JsonObject;
    const asRecord=(raw:unknown):JsonObject=>raw&&typeof raw==='object'&&!Array.isArray(raw)?raw as JsonObject:{};
    const rows=(raw:unknown):JsonObject[]=>Array.isArray(raw)?raw.filter(item=>item&&typeof item==='object'&&!Array.isArray(item)) as JsonObject[]:[];
    closeRecapture.replaceChildren(el('h3','盘后补采（研究观察）'),
      el('p','盘后补采，不代表15:30时点结果；仅研究观察。15:45–15:55分钟行情是收盘前观察，不是正式收盘价。次日计划是否消费，以真实 available_at、research_cutoff 和原owner/PIT校验为准。'));
    const renderEvidence=(title:string,raw:unknown,planning:boolean):void=>{
      const evidence=asRecord(raw);const candidates=rows(evidence.candidates);
      const pool=asRecord(evidence.pool),source=asRecord(evidence.source),bar=asRecord(evidence.bar_window);
      const request=asRecord(evidence.request),coverage=asRecord(evidence.coverage);
      const snapshot=asRecord(evidence.snapshot),overlay=asRecord(evidence.candidate_overlay);
      const candidateRows=candidates.length?candidates:rows(overlay.rows);
      const manualSecurityObservation=evidence.observation_type==='HK_SECURITIES_SESSION_MINUTE_OBSERVATION';
      const section=el('article','','manager-close-recapture-evidence');
      section.append(el('h4',title));
      const planDate=text(evidence.plan_trade_date,text(evidence.target_trade_date,'未提供'));
      const sourceDate=text(evidence.source_trade_date,text(evidence.target_trade_date,'未提供'));
      const timing=text(request.available_at,text(evidence.available_at,text(evidence.generated_at,'未提供')));
      if(manualSecurityObservation){
        section.append(el('p',`手工港股证券盘后研究观察 · 状态 ${text(evidence.status,'未核实')} · 来源日 ${sourceDate} · 计划日 ${planDate}。`),
          el('p',`真实 available_at ${timing} · 观察类型 ${text(evidence.observation_type)} · 可展示观察行 ${candidateRows.length}/${scalarText(overlay.count,'未知')}。`),
          el('p',`来源产物市场标签 ${text(evidence.market,'未提供')}；实际观察市场 ${text(evidence.observation_market,'未提供')}。仅研究观察，不表示港股通可交易资格或官方收盘价。`));
      }else{
        section.append(el('p',`状态 ${text(evidence.status,'未核实')}；计划日 ${planDate}；来源日 ${sourceDate}；真实可用时间 ${timing}。`));
      }
      if(!manualSecurityObservation && (Object.keys(source).length || Object.keys(pool).length || Object.keys(bar).length)){
        const poolIdentity=`交易日 ${text(pool.trade_date,sourceDate)}；信号日 ${text(pool.signal_date,'未提供')}；来源 ${text(pool.source_id,'未提供')}；run_id ${text(pool.run_id,'未提供')}；池行数 ${scalarText(pool.row_count)}`;
        section.append(el('p',`采集类型 ${text(evidence.capture_mode,'未提供')}／${text(evidence.observation_type,'未提供')}；市场 ${text(evidence.market,'未提供')}；行情来源 ${text(source.provider,'未提供')}（${text(source.source_id,'未提供')}）；权威池 ${poolIdentity}。`));
        if(pool.artifact_sha256 || pool.manifest_sha256) section.append(el('p',`池产物 SHA-256 ${text(pool.artifact_sha256,'未提供')}；manifest SHA-256 ${text(pool.manifest_sha256,'未提供')}。`));
        section.append(el('p',`观察阶段 ${text(bar.stage_id,text(evidence.observation_type,'未提供'))}；窗口 ${text(bar.start_at,'未提供')}—${text(bar.max_at,text(bar.end_before,'未提供'))}；bar实际时间 ${text(bar.observed_at_min,'未提供')}—${text(bar.observed_at_max,'未提供')}。`));
        section.append(el('p',`请求开始 ${text(request.started_at,'未提供')}；采集完成 ${text(request.captured_at,'未提供')}；可用时间 ${text(request.available_at,'未提供')}。`));
        section.append(el('p',`覆盖 eligible/requested/completed/observed/no-data：${scalarText(coverage.eligible_count)}/${scalarText(coverage.requested_count)}/${scalarText(coverage.completed_count)}/${scalarText(coverage.observed_count)}/${scalarText(coverage.no_data_count)}；比例 ${scalarText(coverage.ratio)}。`));
        if(snapshot.artifact_ref || overlay.artifact_ref) section.append(el('p',`原始快照 ${text(snapshot.artifact_ref,'未提供')}（SHA ${text(snapshot.sha256,'未提供')}，${scalarText(snapshot.row_count)}行）；候选观察 ${text(overlay.artifact_ref,'未提供')}（SHA ${text(overlay.sha256,'未提供')}，${scalarText(overlay.count)}只）。`));
      }
      if(planning){
        const availability=text(evidence.planner_availability,'CANNOT_CONFIRM');
        const availabilityText=availability==='AVAILABLE_BEFORE_CUTOFF'?'计划截止前已可用；是否消费仍按原owner/PIT校验。':
          availability==='AFTER_CUTOFF'?'晚于本次研究截止，本次计划不消费该观察。':'可用时点未核实，本次计划不将其作为已可用输入。';
        section.append(el('p',`研究截止 ${text(evidence.research_cutoff,'未提供')}；来源可用性 ${availability}。${availabilityText}`));
      }else if(!manualSecurityObservation){
        section.append(el('p',`观察模式 ${text(evidence.mode,'CLOSE_RECAPTURE')}；采集开始 ${text(evidence.started_at,'未提供')}；最近可用 ${text(evidence.available_at,'未提供')}。`));
      }
      const candidateCard=(row:JsonObject):HTMLElement=>{
          const card=el('div','','manager-close-recapture-candidate');
          const symbol=text(row.symbol,'标的未知');
          card.dataset.symbol=symbol;
          card.append(el('strong',`${text(row.name,symbol)} · ${symbol}`),
            el('p',`交易日 ${text(row.source_trade_date,text(row.trade_date,sourceDate))}；bar观察时间 ${text(row.observed_at,text(row.quote_update_time,'未提供'))}；本条可用时间 ${text(row.available_at,text(row.captured_at,'未提供'))}。`),
            el('p',`尾盘分钟观察字段：开 ${scalarText(row.open_price)}；高 ${scalarText(row.high_price)}；低 ${scalarText(row.low_price)}；最新 ${scalarText(row.last_price)}；昨收 ${scalarText(row.prev_close_price)}；成交额 ${scalarText(row.turnover)} ${text(row.turnover_currency,'')} ${text(row.turnover_unit,'')}；成交量 ${scalarText(row.volume)}。`),
            el('p',`资格状态 ${text(row.qualification_state,'NOT_EVALUATED')}；观察状态 ${text(row.candidate_status,text(row.data_status,'LATE_OBSERVATION_ONLY'))}；观察模式 ${text(row.observation_mode,text(evidence.capture_mode,'CLOSE_RECAPTURE'))}。`));
          const missing=Array.isArray(row.missing_evidence)?row.missing_evidence.map(item=>typeof item==='string'?item:
            item&&typeof item==='object'&&!Array.isArray(item)?text((item as JsonObject).code,text((item as JsonObject).reason,JSON.stringify(item))):'未识别缺项'):[];
          if(missing.length)card.append(el('p',`缺失证据：${missing.join('；')||'详见原始记录'}`));
          card.append(details('原始行情与来源引用',row));
          return card;
      };
      if(candidateRows.length){
        if(manualSecurityObservation){
          const rowDetails=el('details','','manager-close-recapture-rows');
          rowDetails.dataset.observationRows='true';
          rowDetails.append(el('summary',`展开全部 ${candidateRows.length} 条观察行`));
          let rowsLoaded=false;
          rowDetails.addEventListener('toggle',()=>{
            if(!rowDetails.open || rowsLoaded)return;
            rowsLoaded=true;
            for(const row of candidateRows)rowDetails.append(candidateCard(row));
          });
          section.append(rowDetails);
        }else{
          for(const row of candidateRows)section.append(candidateCard(row));
        }
      }else{
        const reasons=Array.isArray(evidence.cannot_confirm)?evidence.cannot_confirm.filter(x=>typeof x==='string').join('；'):'未提供候选行';
        section.append(el('p',`当前没有可显示的补采候选；状态/缺项：${reasons||'未提供'}`));
      }
      section.append(details(manualSecurityObservation?'原始产物、来源路径、SHA与完整覆盖证据':'补采产物、覆盖与原owner证据',evidence));
      closeRecapture.append(section);
    };
    const current=root.close_recapture_evidence;
    const planned=root.planning_close_recapture_evidence;
    if(current&&typeof current==='object'&&!Array.isArray(current)){
      const manual=asRecord(current).observation_type==='HK_SECURITIES_SESSION_MINUTE_OBSERVATION';
      renderEvidence(manual?'请求日独立港股证券盘后观察':'请求日独立盘后补采产物',current,false);
    }
    else closeRecapture.append(el('p','请求日没有独立盘后补采产物读回；这不改变原15:30尾盘记录。'));
    if(planned&&typeof planned==='object'&&!Array.isArray(planned))renderEvidence('本次计划关联的前一交易日盘后观察',planned,true);
    else closeRecapture.append(el('p','本次计划没有返回前一交易日盘后观察；不以当前页面时间补造历史数据。'));
  }
  function renderResearchFocus(value:ManagerWorkspace, savedDraft:boolean, savedFreeze:boolean, historical:boolean):void {
    const rows=(value.stocks||[]) as unknown as JsonObject[];
    const bySymbol=new Map(rows.map(row=>[String(row.symbol),row]));
    const focus=(value.focus_symbols||[]).filter((item):item is string=>typeof item==='string');
    const summary=(value.summary||{}) as JsonObject;
    const stage=(value.stage_read_timing||{}) as JsonObject;
    const formal=typeof summary.formal_recommendation_count==='number'&&Number.isSafeInteger(summary.formal_recommendation_count)
      ? summary.formal_recommendation_count : null;
    const title=savedDraft?'次日重点研究名单':savedFreeze?'盘前计划重点研究名单':'研究重点名单';
    researchFocus.replaceChildren(el('h3',`${title}（${focus.length}）`),
      el('p',savedDraft?'这是一份已保存的 MANUAL_REFRESH 次日研究草案；名单沿用原 focus_symbols 顺序，不按页面重新评分。':
        savedFreeze?'以下名单来自已保存的正式盘前计划；正式Stage门禁状态单独显示。':
        historical?'以下是历史读取返回的研究关注；不等同正式推荐。':'以下是当前读取返回的研究关注；保存/冻结状态以原owner计划回执为准。'));
    const stageArtifact=text(stage.artifact_status,'CANNOT_CONFIRM');
    const stageExecution=text(stage.execution_state,'未提供');
    const reasons=Array.isArray(stage.source_reasons)?stage.source_reasons.filter(item=>typeof item==='string') as string[]:[];
    const formalText=formal===null?'数量未提供':`${formal}只`;
    const stageState=stageArtifact==='CANNOT_CONFIRM'?'选择输入未核实':stageArtifact==='READY'?'选择输入已核':`选择输入 ${stageArtifact}`;
    researchFocus.append(el('p',`正式 Stage 推荐：${formalText}；Stage ${stageState}，执行状态 ${stageExecution}。正式Stage结果与研究计划名单分列；0只不表示Stage成功扫描后为空。${reasons.length?`缺口：${reasons.slice(0,3).join('；')}`:''}`));
    if(!focus.length){researchFocus.append(el('p','原owner没有返回重点研究名单；不以候选总数代替。'));return;}
    for(const symbol of focus){
      const row=bySymbol.get(symbol);const card=el('article','','manager-research-focus-card');card.dataset.symbol=symbol;
      if(!row){card.append(el('h4',symbol),el('p','该重点项没有对应股票详情，保留缺件，不补造理由或条件。'));researchFocus.append(card);continue;}
      card.append(el('h4',`${text(row.name,'未提供名称')} · ${symbol}`));
      const why=Array.isArray(row.why_watch)?row.why_watch.filter(item=>typeof item==='string') as string[]:[];
      if(why.length)card.append(...why.slice(0,3).map(item=>el('p',`研究依据：${item}`)));
      else card.append(el('p','原owner未返回可展示的重点理由。'));
      const plan=(row.plan||{}) as JsonObject;
      const actions=Array.isArray(plan.actions)?plan.actions.filter(item=>item&&typeof item==='object'&&!Array.isArray(item)) as JsonObject[]:[];
      if(actions.length){
        const conditions=el('ul');
        for(const action of actions){
          const kind=text(action.type,'观察条件');
          conditions.append(el('li',`${kind}：${text(action.text,'原owner未提供条件文本')}`));
        }
        card.append(el('h5','原计划观察条件'),conditions);
      }else{
        const next=Array.isArray(plan.next_observation)?plan.next_observation.filter(item=>typeof item==='string') as string[]:[];
        card.append(el('p',next.length?`下一观察：${next.join('；')}`:'原owner未返回可展示的观察条件。'));
      }
      researchFocus.append(card);
    }
    researchFocus.append(el('p','重点研究名单及 WATCH / WAIT / NO_CHASE / INVALIDATE 条件来自已保存研究计划；不改变 Stage rank、资格、正式推荐或 BUY。'));
  }
  function screenCard(row: JsonObject, pending = false): HTMLElement {
    const node=el('article','','manager-catalyst-card');
    const classification=pending?'待核数据/历史':String(row.classification)==='STRICT_REBOUND'?'严格候选':'近条件候选';
    node.dataset.screenCode=text(row.code,'UNKNOWN');
    node.dataset.screenStatus=pending?'PARTIAL_UNKNOWN':String(row.history_status || 'KNOWN');
    node.append(el('h4',`${text(row.name)} · ${text(row.code)} · ${classification}`),
      el('p',`成交额 ${numberText(row.amount_hkd,0)} HKD（观察值）；60日历史 ${text(row.history_status)}（${scalarText(row.prior60_session_count,'?')}个交易日）`),
      el('p',`超跌 ${row.oversold_flag===true?'通过':row.oversold_flag===false?'未通过':'待核'}；5日量比 ${numberText(row.volume_ratio_5d)} / 1.5；收盘较当日低点反弹 ${numberText(row.rebound_close_vs_low_pct,2)}%（观察值）`));
    if(row.near_failed_gate)node.append(el('p',`剩余条件差项：${text(row.near_failed_gate)} = ${numberText(row.near_failed_value)}，门槛 ${numberText(row.near_gate_value)}，相对差距 ${numberText(row.near_gate_gap_ratio)}`));
    if(pending)node.append(el('p',`待核原因：${text(row.history_unknown_reasons,'60日历史不足，不能完成严格或近条件判定。')}`));
    node.append(el('p','仅由已核验共享HK 0.2面板重算；研究筛选结果，不是买卖、下单或Stage门禁。'),details('该股筛选数值、差项与来源',row));
    return node;
  }
  function pendingReasonSummary(rows: JsonObject[]): string {
    const counts=new Map<string,number>();
    for(const row of rows){
      const reason=text(row.history_unknown_reasons,'原owner未返回具体待核原因');
      counts.set(reason,(counts.get(reason)||0)+1);
    }
    return [...counts.entries()].sort((a,b)=>b[1]-a[1] || a[0].localeCompare(b[0]))
      .map(([reason,count])=>`${reason} ${count}只`).join('；');
  }
  function renderScreen(value: ReboundScreen | undefined): void {
    screen.replaceChildren(el('h3','REBOUND_V3 量价研究筛选'));
    if(!value){
      reboundStrategySummaryNode.textContent='超跌反弹选股（独立策略；与15:30尾盘来源分开） · 当前无独立筛选读回';
      screen.append(el('p','当前工作台未返回独立量价筛选；既有材料卡仍按原合同展示。'));return;
    }
    const screening=screeningStatus(value);
    screen.append(el('p',`${screening.label}；计划参考行情日 ${text(value.verified_session)}。`));
    screen.append(el('p','独立筛选准入：收盘≤此前60个完整港股交易日最高价的80%；当日完整成交量/此前5个完整港股交易日平均成交量≥1.5。成交额与收盘较当日低点的反弹幅度仅作观察。15:30观察与收盘确认分开；准入数据未知不计为近条件。'));
    if(!screening.complete){
      reboundStrategySummaryNode.textContent='超跌反弹选股（独立策略；与15:30尾盘来源分开） · 当前无法完整判定';
      screen.append(el('p',`原owner缺项：${value.gaps.map(g=>g==='HISTORY_EXACT_DATE_MARKET_NOT_VERIFIED'?'尚未验证本历史计划的exact-date行情；没有用最新行情代替。':g).join('；')}`),details('未完成筛选的原始计数与拒绝凭证（0不表示已扫描）',value));return;
    }
    if(value.gaps.length)screen.append(el('p',`筛选缺项：${value.gaps.join('；')}`));
    const strictCards=value.cards.filter(row=>String(row.classification)==='STRICT_REBOUND');
    const nearCards=value.cards.filter(row=>String(row.classification)==='NEAR_CONDITION');
    reboundStrategySummaryNode.textContent=`超跌反弹选股（独立策略；与15:30尾盘来源分开） · 严格${strictCards.length} · 近条件${nearCards.length} · 待核${value.pending.length}`;
    screen.append(el('h4',`严格候选（${strictCards.length}）`),...strictCards.map(row=>screenCard(row)));
    screen.append(el('h4',`近条件候选（${nearCards.length}）`),...nearCards.map(row=>screenCard(row)));
    const pendingGroup=el('details','','manager-rebound-pending-history');
    pendingGroup.dataset.pendingHistory='true';
    const reasons=pendingReasonSummary(value.pending);
    let pendingLoaded=false;
    pendingGroup.addEventListener('toggle',()=>{
      if(pendingGroup.open && !pendingLoaded){
        pendingLoaded=true;
        pendingGroup.append(...value.pending.map(row=>screenCard(row,true)));
      }
    });
    pendingGroup.append(el('summary',`待核历史（${value.pending.length}） · ${reasons || '当前没有待核代码'}`));
    screen.append(pendingGroup);
    if(!value.cards.length)screen.append(el('p','已完成全量筛选，当前没有通过或近条件候选；待核数据不会升格。'));
    screen.append(details('筛选覆盖、权威面板与研究边界',value));
  }
  function render(value: ManagerWorkspace): void {
    // Input identity is retained for audit; it is not a stock ranking.
    currentValue=value;loadedView=view;
    updateAnnouncementSummary();
    oversoldSummary.textContent=strategySummary(value,'OVERSOLD');
    const bindings=displayBindings();
    const usMarket=(value.us_market_attention||{}) as JsonObject;
    resultDates.textContent=`计划目标日 ${value.target_trade_date} · 港股来源日 ${bindings.selection_date} · 公告日 ${bindings.announcement_date} · 美股交易日 ${text(usMarket.expected_us_session,'未知')}`;
    renderDailyChannels(dailyChannels,value.daily_channels,displayBindings());
    renderResearchAttention(researchAttentionSection,value.research_attention as ResearchAttention|undefined,value.us_market_attention as UsMarketAttention|undefined,value.selection_diagnostics as SelectionDiagnostics|undefined,value.us_mapping_research as UsMappingResearch|undefined);
    panel.dataset.inputIdentity=value.input_identity; panel.dataset.targetDate=value.target_trade_date;panel.dataset.readState='READY';
    renderCloseRecapture(value);
    renderReboundPanelObservation(panelObservation,value.rebound_panel_observation);
    renderUsMappingCoverage(usMappingCoverage,value.us_mapping_research ?? {});
    const ctx=(value.plan_context || {}) as JsonObject;const product=(value.plan_product || {}) as JsonObject;
    const read=(value.read_context || {}) as JsonObject;
    const planAttempt=(value.workspace_plan_attempt || {}) as JsonObject;
    const historical=read.mode==='HISTORICAL_AS_OF';
    const missing=read.status==='NOT_MATERIALIZED';const sourceFailed=read.status==='SOURCE_FAILED';
    const attemptMatches=typeof product.run_id==='string'&&product.run_id===planAttempt.run_id;
    const savedDraft=!historical&&view!=='dynamic'&&product.status==='CURRENT'&&attemptMatches&&planAttempt.execution_kind==='MANUAL_REFRESH';
    const savedFreeze=!historical&&product.status==='CURRENT'&&attemptMatches&&planAttempt.execution_kind==='SCHEDULED_PREOPEN';
    renderResearchFocus(value,savedDraft,savedFreeze,historical);
    const label=historical ? (missing?'当时历史：缺少合格保存计划':sourceFailed?'当时历史：来源校验失败，拒绝旧计划':'当时历史：保存计划已重验') :
      (read.mode==='CURRENT_RECOVERY'?'跨日恢复研究计划（现在回看，非当时可用）':view==='dynamic'?'现在回看（含后续信息，非当时已知）':savedDraft?'次日研究预览（已保存草案；未正式冻结）':
        savedFreeze?'盘前计划已冻结（原owner产物）':'当日动态预览（非历史冻结计划）');
    status.textContent=`计划 ${date} · ${label} ｜ 材料截至 ${timeText(ctx.research_cutoff)} ｜ 行情基准 ${text(ctx.market_session)}，${ctx.market_data_verified===true?'原行情已核':'原行情未核'}（非晚间实时行情）。`;
    businessStatus.replaceChildren(...businessStatusRows(value).map(row=>{const item=el('article','','business-status-row');item.append(el('strong',`${row.label}：${row.state}`),el('p',row.detail),el('p',`下一步：${row.next}`));return item;}));
    const decisionCounts=decisionSummaryCounts(value);
    decisionSummary.textContent=`研究窗口 ${timeText(ctx.focus_window_start)}—${timeText(ctx.research_cutoff)}；按当前最终展示分类 ${decisionCounts.current}只公司/产业研究，${decisionCounts.background}只背景/原量价（原focus ${value.focus_symbols.length}只，保持不变）。先核具体变化，再核预期；同组未比较收益，不是Top排名。`;
    if(read.candidate_count_known===false) decisionSummary.textContent=`研究窗口 ${timeText(ctx.focus_window_start)}—${timeText(ctx.research_cutoff)}；候选、风险和覆盖未知，不是已成功扫描后的零候选。${read.reason?historyReason(read.reason):'须补齐原owner证据。'}`;
    runSummary.textContent=historical?'来源/运行检查是本次读回状态，不冒充当时运行：':'';
    if(planAttempt.state)runSummary.textContent+=` 最近计划生成：${states[String(planAttempt.state)] || String(planAttempt.state)}；已保存产物与本次生成状态分别记录。`;
    runSummary.textContent+=value.lanes.map(row=>`${laneNames[row.lane] || row.lane}：${states[row.state]}`).join(' ｜ ');
    const chain=(value.owner_chain || {}) as JsonObject;const consumed=(chain.materials || {}) as JsonObject;const announcements=(chain.announcements || {}) as JsonObject;
    runSummary.textContent+=` ｜ 材料消费：${text(consumed.status,'原reader投影回放，未重验原store')}；公告独立查询：${states[String(announcements.status)] || text(announcements.status,'未提供原owner执行记录')}。主题研究状态与补充催化运行分列，不据材料数量推定抓取成功。`;
    const announcementAttempt=(announcements.latest_attempt || {}) as JsonObject;
    if(announcementAttempt.started_at)runSummary.textContent+=` 公告最近尝试 ${text(announcementAttempt.started_at)} · ${states[String(announcementAttempt.state)] || text(announcementAttempt.state)}。`;
    runs.replaceChildren(...value.lanes.map(lane));renderScreen(value.market_screen);
    renderStocks(value);
    if(read.candidate_count_known===false)filterCount.textContent='覆盖未知 · 不是0候选';
    themes.replaceChildren(el('h3','今日主题研究线索'),el('p',text(value.briefing.headline)),el('p',text(value.briefing.ordering_explanation)));
    const currentThemes=value.themes; // Background policy remains visible here, never promoted into today's stock attention.
    for(const theme of currentThemes){
      const card=el('article');card.dataset.theme=String(theme.theme);const market=(theme.market_confirmation || {}) as JsonObject;
      card.append(el('h4',text(theme.label,text(theme.theme))),el('p',`${theme.display_group==='CURRENT_RESEARCH'?'窗口内主题':'窗口前背景主题'} · ${text(theme.priority_reason)}`));
      const refs=(theme.evidence || []) as JsonObject[];const representative=refs.find(e=>e.temporal_role==='NEW_PLAN_PUBLICATION') || refs[0];
      if(representative)card.append(el('blockquote',short(text(representative.quote),320)),el('p',`该片段发布：${text(representative.published_at)}；取得：${text(representative.retrieved_at)}。仅按原reader陈述，不推定完整原store准入。`));
      const symbols=(theme.mapped_symbols || []) as string[];
      card.append(el('p',symbols.length?'双证据映射（产业推断）：'+symbols.map(code=>value.stocks.find(s=>s.symbol===code)?.name+' '+code).join('、'):'暂无可核本股业务关联，保留主题线索，不凑候选。'));
      for(const group of groupThemeMappings(theme)){
        const mapping=group.representative;
        const merged=group.mappings.length>1;
        const mappingBlock=el('section','','theme-mapping-summary');
        mappingBlock.dataset.mappingGroupKey=group.key;
        mappingBlock.dataset.mappingRawCount=String(group.mappings.length);
        mappingBlock.append(el('p',`${text(mapping.symbol)} · ${mapping.window_status==='BACKGROUND_REFERENCE'?'历史背景关联':'窗口内产业关联'}：${text(mapping.reason)}${merged?`（${group.mappings.length}条相同关系摘要已合并）`:''}`),
          el('blockquote',`本股：${text(mapping.issuer_quote)}\n主题：${text(mapping.theme_quote)}`),
          details(merged?'已合并关系的完整 relation/provenance':'关系的完整 relation/provenance',group.mappings));
        card.append(mappingBlock);
      }
      for(const gap of (theme.company_mapping_gaps || []) as JsonObject[]){
        card.append(el('p',`${text(gap.name)} ${text(gap.symbol)}：尚不能建立关联。${text(gap.missing)}`));
        const repair=el('details');repair.append(el('summary','该股缺件与原owner补齐办法'),el('p',text(gap.remedy)),el('p',text(gap.owner)),details('诊断引用（非股票映射）',gap));card.append(repair);
      }
      const prose=el('details');prose.append(el('summary','主题主要原文与来源'));
      for(const source of refs.slice(0,8)){
        prose.append(el('p',`${text(source.title,'归档原文')} · ${text(source.published_at)}`),el('blockquote',text(source.quote)));
        const a=sourceLink(source.source_url);if(a)prose.append(a);
      }
      prose.append(details('全部主题证据与技术定位',theme));card.append(el('p',text(market.reason,'行情强弱尚未验证。')),prose);themes.append(card);
    }
    if(!currentThemes.length)themes.append(el('p','当前窗口没有通过正文校验的主题；旧背景不当成今日主线。'));

    companyEvents.replaceChildren(el('h3','公司直接事件与研究陈述（分列）'));
    const direct=value.company_events.filter(e=>e.group==='DIRECT_COMPANY_EVENT');
    for(const e of direct)companyEvents.append(el('p',`${text(e.name)} · ${text(e.symbol)}：${short(text(e.quote),260)}。发布时间 ${text(e.published_at)}；尚非行情确认。`));
    if(!direct.length)companyEvents.append(el('p','当前输入未带已核原owner直接事件闭包；下方公司研究陈述不能替代正式公告。'));
    const companyResearch=value.company_events.filter(e=>e.group!=='DIRECT_COMPANY_EVENT');
    companyEvents.append(details('其他公司研究命题及支撑原文',companyResearch));
    auditBody.replaceChildren(el('p','本页面已消费此输入版本；只证明本次页面读取，不证明自然时段执行、历史实时捕获或今日选股成功。'),details('原owner→材料消费→主题股票→计划→API路径',value.owner_chain || {status:'READBACK_ONLY_NOT_OWNER_RUN'}),details(`逐条剔除原因（${value.rejected_relations.length}个片段，不等于股票数）`,value.rejected_relations),details(`全部材料记录（${value.materials.length}，不等于独立报告数）`,value.materials),details('计划日期与冻结/预览的精确时点',{plan_context:ctx,plan_product:product}),details('覆盖与版本证据',{
      input_identity:value.input_identity,gaps:value.gaps,runtime_gaps:value.runtime_gaps,coverage:value.existing_material_coverage,
      bindings:value.existing_material_bindings,run_accounting:value.run_accounting,continuity_gap:value.continuity_gap,
    }));
  }
  function clearResults(): void {
    currentValue=null;loadedView=null;decisionSummary.textContent='候选和风险数量未知';
    resultDates.textContent='正在读取数据日期';
    updateAnnouncementSummary();
    oversoldSummary.textContent=strategySummary(undefined,'OVERSOLD');
    filterCount.textContent='读取中 · 数量未知';background.hidden=true;runSummary.textContent='';
    for(const node of [stocks,backgroundBody,companyEvents,runs,themes,auditBody,businessStatus,researchFocus,closeRecapture])node.replaceChildren();
    renderDailyChannels(dailyChannels,undefined,displayBindings());
    renderScreen(undefined);
    renderReboundPanelObservation(panelObservation,undefined);
    renderUsMappingCoverage(usMappingCoverage,undefined);
    renderResearchAttention(researchAttentionSection,undefined,undefined);
    delete panel.dataset.inputIdentity;delete panel.dataset.targetDate;panel.dataset.readState='LOADING';
  }
  async function loadAnnouncementReview(): Promise<void> {
    const id=++announcementSequence;
    announcementController?.abort();
    announcementRefreshController?.abort();clearTimeout(announcementRefreshTimer);
    announcementRefreshController=null;
    const requestedDate=publicationDate;
    const current=new AbortController();announcementController=current;
    renderAnnouncementReview(announcementSection,undefined,requestedDate,'正在读取所选公告日期',updateAnnouncementReview);
    try {
      const value=await requestManagerAnnouncements(requestedDate,current.signal);
      if(!disposed&&id===announcementSequence&&announcementController===current
          &&publicationDate===requestedDate&&!current.signal.aborted)
        renderAnnouncementReview(announcementSection,value,requestedDate,undefined,updateAnnouncementReview);
    } catch(error) {
      if(!disposed&&id===announcementSequence&&announcementController===current
          &&publicationDate===requestedDate&&!current.signal.aborted){
        const message=error instanceof Error?error.message:'ANNOUNCEMENT_READ_FAILED';
        renderAnnouncementReview(announcementSection,undefined,requestedDate,`公告读取失败，覆盖数量未知（${message}）`,updateAnnouncementReview);
      }
    }finally{
      if(announcementController===current)announcementController=null;
    }
  }
  function selectAnalysisDate(next:string|undefined):void{
    analysisPublicationDate=next;
    const nextPublicationDate=next ?? fallbackAnnouncementDate;
    const publicationBindingChanged=nextPublicationDate!==publicationDate;
    publicationDate=nextPublicationDate;
    const url=new URL(window.location.href);
    if(next)url.searchParams.set('announcement_date',next);
    else url.searchParams.delete('announcement_date');
    window.history.replaceState(window.history.state,'',`${url.pathname}${url.search}${url.hash}`);
    const intentChanged=explicitDates!==readDailyDateBindings(url.searchParams,date).explicit;
    explicitDates=readDailyDateBindings(url.searchParams,date).explicit;
    if(publicationBindingChanged || intentChanged){void load(false);void loadAnnouncementReview();}
    void loadAnnouncementAnalysis(date);
  }
  async function loadAnnouncementAnalysis(targetDate:string):Promise<void>{
    const id=++analysisSequence;analysisController?.abort();
    analysisReadFailed=false;updateAnnouncementSummary();
    const current=new AbortController();analysisController=current;
    renderAnnouncementAnalysis(announcementAnalysisSection,undefined,analysisPublicationDate,'正在读取公告解析结果',selectAnalysisDate);
    try{
      const value=await requestManagerAnnouncementAnalysis(targetDate,analysisPublicationDate,current.signal);
      if(!disposed&&id===analysisSequence&&date===targetDate)
        renderAnnouncementAnalysis(announcementAnalysisSection,value,analysisPublicationDate,undefined,selectAnalysisDate);
    }catch(error){
      if(disposed||id!==analysisSequence||date!==targetDate||current.signal.aborted)return;
      const message=error instanceof Error?error.message:'ANNOUNCEMENT_ANALYSIS_READ_FAILED';
      renderAnnouncementAnalysis(announcementAnalysisSection,undefined,analysisPublicationDate,message,selectAnalysisDate);
      analysisReadFailed=true;updateAnnouncementSummary();
    }
  }
  async function updateAnnouncementReview():Promise<void>{
    ++announcementSequence;announcementController?.abort();announcementController=null;
    announcementRefreshController?.abort();clearTimeout(announcementRefreshTimer);
    const current=new AbortController();announcementRefreshController=current;
    const requestedDate=publicationDate;
    let timedOut=false;
    announcementRefreshTimer=setTimeout(()=>{timedOut=true;current.abort();},WORKSPACE_REQUEST_TIMEOUT_MS);
    try{
      const value=await refreshManagerAnnouncements(requestedDate,current.signal);
      if(!disposed&&announcementRefreshController===current&&publicationDate===requestedDate){
        renderAnnouncementReview(announcementSection,value,requestedDate,undefined,updateAnnouncementReview);
        // Read the current plan/publication binding after this explicit owner update.
        void load(false);
      }
    }catch(error){
      if(disposed||announcementRefreshController!==current)return;
      if(timedOut)
        renderAnnouncementReview(announcementSection,undefined,requestedDate,'公告增量更新达到180秒上限；覆盖数量未知，可在确认原owner状态后重试。',updateAnnouncementReview);
      else if(!current.signal.aborted){
        const message=error instanceof Error?error.message:'ANNOUNCEMENT_REFRESH_FAILED';
        renderAnnouncementReview(announcementSection,undefined,requestedDate,`公告增量更新失败，覆盖数量未知（${message}）`,updateAnnouncementReview);
      }
    }finally{
      clearTimeout(announcementRefreshTimer);
      if(announcementRefreshController===current)announcementRefreshController=null;
    }
  }
  function failureKind(error:unknown, timedOut:boolean, cancelled:boolean): [string,boolean] {
    if(timedOut)return ['本次读取达到180秒上限；可重读或切换日期。后台仅在原owner边界合作取消。',false];
    if(cancelled)return ['已取消本次读取；可重新读取。',false];
    const message=error instanceof Error?error.message:'';
    if(/HTTP_504$/.test(message))return ['服务端读取超时；可重读，未延长原等待上限。',false];
    const reasons=error instanceof Error ? (error as Error & { reasonCodes?: string[] }).reasonCodes : undefined;
    if((/HTTP_503$/.test(message) || /HTTP_429$/.test(message)) && reasons?.includes('MODULE_BUSY'))
      return ['当前读取已达并发上限；未新增排队计算，可稍后点击读取。',false];
    if(/HTTP_503$/.test(message))return [reasons?.includes('MODULE_RESULT_NOT_AVAILABLE')
      ? '所选日期与视图的已发布结果尚未就绪；可稍后重新读取。'
      : '服务暂不可用；具体原因尚未确认，可稍后重新读取。',false];
    if(/HTTP_429$/.test(message))return ['请求暂被限流；可稍后重新读取。',false];
    if(/HTTP_499$/.test(message))return ['本次读取已取消；可重新读取。',false];
    if(/HTTP_5\d\d$/.test(message))return ['服务暂不可用；可重新读取。',false];
    if(/WORKSPACE_/.test(message))return ['来源、日期或工作台合同校验失败；已清除旧结果，须核查原owner证据后重读。',true];
    return ['网络连接或响应读取失败；可检查连接后重新读取。',false];
  }
  function refreshBlockReason(): string {
    if(generationUnconfirmed)return '上一次生成结果待原run终态核验；重新读取不会自动重试生成。';
    if(!currentValue || currentValue.target_trade_date!==date || loadedView!==view || panel.dataset.readState!=='READY')
      return '须先成功读取本计划日与口径的完整结果，才能确认生成入口。';
    if(isManagerWorkspaceReadOnly(currentValue))return '此V5入口只读消费已发布结果；计划生成由原owner执行。';
    const read=(currentValue.read_context || {}) as JsonObject;
    const parts=new Intl.DateTimeFormat('en',{timeZone:'Asia/Hong_Kong',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts();
    const today=['year','month','day'].map(type=>parts.find(part=>part.type===type)?.value).join('');
    if(read.mode==='HISTORICAL_AS_OF' || view!=='dynamic' && date<today)
      return '当时历史只读；生成现在回看计划须先显式切换口径。';
    if(read.mode!=='CURRENT_DYNAMIC_PREVIEW' || read.contract!=='20260923.workspace-history-read.r1' ||
        !['VERIFIED','VERIFIED_WITH_GAPS'].includes(String(read.status)))
      return '读取上下文尚未完整核验，不能开放生成。';
    return '';
  }
  async function load(refresh: boolean): Promise<void> {
    if(refresh && refreshBlockReason())return;
    const id=++sequence;controller?.abort();clearTimeout(timer);controller=new AbortController();const current=controller;
    const requestedDate=date;const requestedView=view;let timedOut=false;
    const requestedBindings:WorkspaceDateBindings={plan_date:requestedDate,selection_date:selectionDate,announcement_date:publicationDate};
    const bindFirstRead=explicitDates;
    timer=setTimeout(()=>{timedOut=true;current.abort();},WORKSPACE_REQUEST_TIMEOUT_MS);
    const priorRead=(currentValue?.read_context || {}) as JsonObject;
    const keep=!!currentValue && currentValue.target_trade_date===date && loadedView===view &&
      ['VERIFIED','VERIFIED_WITH_GAPS'].includes(String(priorRead.status));
    if(!keep)clearResults();
    panel.dataset.readState=keep?'UPDATING':'LOADING';
    if(keep)filterCount.textContent='上次结果 · 正在更新';
    readButton.disabled=true;refreshButton.disabled=true;cancelButton.hidden=false;
    status.textContent=(keep?`计划 ${date}：以下为上次合格结果（非本次新结果）；正在更新。 `:`计划 ${date}：正在核对历史计划/来源，数量未知。 `)+
      (refresh?'原经理owner仅用既有材料生成计划，不抓取。':'本次为只读，不生成、不采集。');
    if(!refresh && generationUnconfirmed)panel.dataset.generationState='CANNOT_CONFIRM';
    try {
      let value: ManagerWorkspace;
      if(refresh){
        generationUnconfirmed=true;panel.dataset.generationState='RUNNING';
        value=bindFirstRead
          ? await refreshManagerWorkspace(requestedDate,current.signal,requestedBindings)
          : await refreshManagerWorkspace(requestedDate,current.signal);
      } else {
        value=bindFirstRead
          ? await requestManagerWorkspace(requestedDate,current.signal,requestedView,requestedBindings)
          : await requestManagerWorkspace(requestedDate,current.signal,requestedView);
      }
      if(disposed || id!==sequence)return;
      if(current.signal.aborted)throw new DOMException('Workspace read aborted','AbortError');
      if(value.daily_channels!==undefined){
        if(bindFirstRead && !sameDailyDateBindings(value.date_bindings,requestedBindings))
          throw new Error('WORKSPACE_DAILY_DATE_BINDING_MISMATCH');
        if(!bindFirstRead){
          // Validated server defaults are display dates, not new user intent.
          // Keep future default reads unbound, including after manual refresh.
          const bindings=value.date_bindings;
          if(!bindings)throw new Error('WORKSPACE_DAILY_DATE_BINDING_INVALID');
          const publicationChanged=publicationDate!==bindings.announcement_date;
          selectionDate=bindings.selection_date;
          publicationDate=bindings.announcement_date;
          if(publicationChanged)void loadAnnouncementReview();
        }
      }
      if(current.signal.aborted)throw new DOMException('Workspace read aborted','AbortError');
      if(!disposed && id===sequence && date===requestedDate && view===requestedView){
        render(value);
        if(refresh){generationUnconfirmed=false;panel.dataset.generationState='VERIFIED';}
        else if(generationUnconfirmed)status.textContent+=' 上一次生成结果仍待原run终态核验；本次只读不判定该次生成成败。';
      }
    } catch(error){
      if(!disposed && id===sequence && date===requestedDate && view===requestedView){
        const [message,sourceFailure]=failureKind(error,timedOut,current.signal.aborted);
        if(refresh){
          if(sourceFailure || !keep)clearResults();
          panel.dataset.readState='CANNOT_CONFIRM';panel.dataset.generationState='CANNOT_CONFIRM';
          filterCount.textContent=keep&&!sourceFailure?'上次结果 · 本次生成终态待核':'本次生成终态待核 · 数量未知';
          status.textContent=`计划 ${date}：本次生成结果未知；${timedOut?'已达180秒并停止等待。':current.signal.aborted?'已取消等待。':'未收到可核验的成功响应。'} 请先由原owner按本次run核验保存产品与同run终态，再读取；未自动重试生成。`+
            (keep&&!sourceFailure?' 以下仅保留上次合格结果。':' 未显示未核验结果。');
        } else {
          if(sourceFailure || !keep){clearResults();panel.dataset.readState='FAILED';filterCount.textContent='读取未完成 · 数量未知';}
          else {panel.dataset.readState='STALE';filterCount.textContent='上次结果 · 本次读取未完成';}
          status.textContent=`计划 ${date}：${message}`+(keep&&!sourceFailure?' 以下保留上次合格结果，不代表本次成功。':' 未显示旧日或未核验股票。');
        }
      }
    } finally {
      if(!disposed && id===sequence){
        clearTimeout(timer);readButton.disabled=false;cancelButton.hidden=true;
        const blocked=refreshBlockReason();refreshButton.disabled=!!blocked;refreshButton.title=blocked;
      }
    }
  }
  const dateChange=()=>{
    const next=planDate.value.replace(/-/g,'');
    if(normalizedWorkspaceDay(next)===next){
      date=next;
      const url=new URL(window.location.href);
      if(url.searchParams.get('plan_date')!==next){
        url.searchParams.set('plan_date',next);
        window.history.replaceState(window.history.state,'',`${url.pathname}${url.search}${url.hash}`);
      }
      void loadAnnouncementAnalysis(next);
      void load(false);
    }
  };
  const viewChange=()=>{
    view=readView(viewSelect.value);
    const url=new URL(window.location.href);
    if(url.searchParams.get('view')!==view){
      url.searchParams.set('view',view);
      window.history.pushState(window.history.state,'',`${url.pathname}${url.search}${url.hash}`);
    }
    void load(false);
  };
  const navigationChange=()=>{
    announcementRefreshController?.abort();clearTimeout(announcementRefreshTimer);
    clearResults();
    const query=new URLSearchParams(window.location.search);
    const restored=readDailyDateBindings(query,initialDate);
    date=restored.bindings.plan_date;
    selectionDate=restored.bindings.selection_date;
    publicationDate=restored.bindings.announcement_date;
    explicitDates=restored.explicit;
    fallbackAnnouncementDate=normalizedWorkspaceDay(query.get('publication_date'))
      ?? normalizedWorkspaceDay(query.get('date')) ?? normalizedWorkspaceDay(initialDate)!;
    const requested=query.get('announcement_date');
    analysisPublicationDate=requested && /^\d{8}$/.test(requested)?requested:undefined;
    view=readView(query.get('view'));viewSelect.value=view;
    planDate.value=`${date.slice(0,4)}-${date.slice(4,6)}-${date.slice(6,8)}`;
    void loadAnnouncementReview();
    void loadAnnouncementAnalysis(date);
    void load(false);
  };
  window.addEventListener('popstate',navigationChange);
  const cancelClick=()=>{controller?.abort();};
  planDate.addEventListener('change',dateChange);viewSelect.addEventListener('change',viewChange);cancelButton.addEventListener('click',cancelClick);
  const readClick=()=>{void load(false);};const refreshClick=()=>{void load(true);};
  readButton.addEventListener('click',readClick);refreshButton.addEventListener('click',refreshClick);
  void loadAnnouncementReview();
  void loadAnnouncementAnalysis(date);
  void load(false);
  return ()=>{disposed=true;window.removeEventListener('popstate',navigationChange);++sequence;++analysisSequence;++announcementSequence;controller?.abort();analysisController?.abort();announcementController?.abort();announcementRefreshController?.abort();clearTimeout(announcementRefreshTimer);clearTimeout(timer);planDate.removeEventListener('change',dateChange);viewSelect.removeEventListener('change',viewChange);cancelButton.removeEventListener('click',cancelClick);readButton.removeEventListener('click',readClick);refreshButton.removeEventListener('click',refreshClick);host.replaceChildren();};
}
