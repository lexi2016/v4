import {sortHistoryRates,rateLabel,historyRate} from '../../rate-sort.mjs';
import {requestedEntry,resolveCatalogRequest,entryUrl,preferredCatalogEntry,shanghaiToday} from '../../entry-date.mjs';
import {matchesClassification} from '../../classification-local.mjs';
import {renderDailyChart,validateDailyChart} from './formula-daily-chart.mjs';
import {createFormulaF10Cards,isFormulaF10Completion} from './formula-f10.mjs';
const candidateSourceNote=s=>`行情日 ${s?.observation_date??'未知'} · 候选来源日 ${day?.source_date??'未绑定'}`;
const observationHeader=(snapshot,now)=>snapshot?.capture_kind==='OFFICIAL_DAILY_ARCHIVE'?`官方日包收盘行情 · ${candidateSourceNote(snapshot)} · 行情源精确时刻 UNKNOWN · 保存 ${snapshot.recorded_at} · 行情覆盖 ${snapshot.rows.filter(r=>r.status==='DATED_DAILY_ARCHIVE').length}/${snapshot.rows.length}`:originalObservationHeader(snapshot,now);
const archiveMini=s=>{if(s?.capture_kind==='OFFICIAL_DAILY_ARCHIVE')document.getElementById('observationMini').textContent=`官方日包行情 · ${candidateSourceNote(s)} · 行情覆盖 ${s.rows.filter(r=>r.status==='DATED_DAILY_ARCHIVE').length}/${s.rows.length} · 行情源精确时刻未知`};const renderPhase=(...args)=>{originalRenderPhase(...args);archiveMini(args[1])};const renderContext=(...args)=>{originalRenderContext(...args);archiveMini(args[1])};
import {sortDisplayStocks,displayQuote,rowValidity,STATUS_ZH,shanghaiParts,validateSnapshot,volumeLabel,volumeCoverage,priceLabel,amountLabel} from '../../observation-local.mjs';
import {renderContext as originalRenderContext,renderPhase as originalRenderPhase,observationHeader as originalObservationHeader} from './workbench-context.mjs';
import {loadProjection} from '../src/projection-view.mjs';
import {validateDay,loadJson} from '../src/model.mjs';
import {isTop200ForSelection,validateTop200Payload} from '../../top200-group.mjs';
import {GROUPS,configureGroups,stateLabel,displayName,filterStocks,groupLabels,validateChartMatch,validateV192Group,v192Summary,quoteContext} from '../src/workbench-model.mjs';
import {validateCompany,explanationFacts,independentTiming,beginCompanyRequest,isCurrentCompanyRequest,renderCompanyStatus} from '../../company-local.mjs';
const $=id=>document.getElementById(id),node=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n};
const integrationBase=document.querySelector('meta[name=framework-api-base]')?.content??'';const apiBound=integrationBase.startsWith('/')&&!integrationBase.startsWith('//')&&new URL(integrationBase,location.href).origin===location.origin;
const preview=document.querySelector('meta[name=offline-review-fixture]')?.content==='true';$('previewBadge').hidden=!preview;
const formulaGroupLabels={b23_entry:'192选股',pb2_confirm:'回测选股'};
const formulaGroupIds=Object.keys(formulaGroupLabels);
const formulaStates=new Set(['TRUE','FALSE','UNKNOWN']);
function hasFormulaGroupKeys(value){
 return value&&Object.keys(value).length===formulaGroupIds.length&&formulaGroupIds.every(id=>Object.hasOwn(value,id));
}
function validFormulaRows(rows,counts){
 if(!rows.length)return false;
 const totals=Object.fromEntries(formulaGroupIds.map(id=>[id,0]));
 for(const row of rows){
  const states=row.group_states;
  if(row.eligible_candidate!==true||row.v192_member||!hasFormulaGroupKeys(states)||
    !formulaGroupIds.every(id=>formulaStates.has(states[id]))||!formulaGroupIds.some(id=>states[id]==='TRUE'))return false;
  for(const id of formulaGroupIds)if(states[id]==='TRUE')totals[id]++;
 }
 return formulaGroupIds.every(id=>counts[id]===totals[id]);
}
function validateWorkbenchDay(value){
 const bound=validateDay(value);
 if(preview)return bound;
 const {labels,group_counts:counts,status}=bound.formula_groups??{};
 if(hasFormulaGroupKeys(labels)&&formulaGroupIds.every(id=>labels[id]===formulaGroupLabels[id])&&hasFormulaGroupKeys(counts)){
  if(status==='READY'&&validFormulaRows(bound.rows,counts))return bound;
  if(!bound.rows.length&&status==='READY_EMPTY'&&formulaGroupIds.every(id=>counts[id]===0))return bound;
  if(!bound.rows.length&&status==='CANNOT_CONFIRM_NOT_MATERIALIZED'&&formulaGroupIds.every(id=>counts[id]===null))return bound;
 }
 return {...bound,rows:[],scope_count:0,formula_groups:{labels:formulaGroupLabels,
  group_counts:Object.fromEntries(formulaGroupIds.map(id=>[id,null])),
  status:'CANNOT_CONFIRM_NOT_MATERIALIZED'}};
}
function validMarketContextSnapshot(snapshot,currentDay,revision){
 return snapshot?.schema==='OBSERVATION_SNAPSHOT_VIEW_V1'
  &&snapshot.source_date===currentDay.source_date
  &&snapshot.observation_date===currentDay.observation_date
  &&snapshot.source_generation===currentDay.generation
  &&snapshot.input_sha256===currentDay.input_sha256
  &&(!revision||snapshot.parent_admission_sha256===revision)
  &&snapshot.analysis_admission==='NOT_GRANTED'
  &&snapshot.formula_review==='PENDING'
  &&snapshot.RESEARCH_ONLY===true
  &&snapshot.production_allowed===false
  &&snapshot.buy_gate_updated===false
  &&snapshot.orders_sent===false
  &&snapshot.context&&typeof snapshot.context==='object'
  &&!Array.isArray(snapshot.context);
}
const f10Cards=createFormulaF10Cards(document,(url,signal)=>loadJson(url,(target,options)=>fetch(target,{...options,signal})));
const originalTitle=document.title,originalTexts=[['.brand small','原公式研究 · 原图优先'],['.sidebar-title .subtle','四组数值候选 · 风险待核另列'],['label[for="stockSort"]','股票栏排序（不改变四组数值候选 · 风险待核另列）'],['.evidence-intro','海外资料仅解释环境与风险，不改四组数值候选 · 风险待核另列、评分或资格。原式数值命中 ≠ 图审通过 ≠ 买点。'],['.scope-banner','数值命中 ≠ 图审通过 ≠ 监测激活 ≠ 买点确认。完整公式独审仍待完成；仅供研究，不下单。'],['.review-badge','原式待审 · 研究展示']];
function configureDayGroups(currentDay) {
 const formulaGroups=currentDay?.formula_groups;
 f10Cards.configure(Boolean(formulaGroups));
 configureGroups(currentDay);
 if(formulaGroups){
  for(const key of Object.keys(GROUPS))delete GROUPS[key];
  Object.assign(GROUPS,formulaGroups.labels);
  if(group!=='all'&&group!=='top200'&&!Object.hasOwn(GROUPS,group))group='all';
 }
 const scope=$('scope');
 scope.hidden=Boolean(formulaGroups);
 $('originalScreenshot').hidden=Boolean(formulaGroups);
 $('interactivePanel').querySelector('h2').textContent=formulaGroups?'前复权日K':'原式图';
 $('showStockRates').disabled=Boolean(formulaGroups);
 document.querySelector('label[for="scope"]').hidden=Boolean(formulaGroups);
 for(const option of $('stockSort').options){
  if(!/^d[25]_/.test(option.value))continue;
  option.hidden=Boolean(formulaGroups);
  option.disabled=Boolean(formulaGroups);
 }
 for(const header of document.querySelectorAll('[data-stock-sort="d2"], [data-stock-sort="d5"]'))header.disabled=Boolean(formulaGroups);
 if(formulaGroups&&/^d[25]_/.test($('stockSort').value))$('stockSort').value='name_asc';
 setRulePresentation(currentDay);
}
function setRulePresentation(day){const skill=day?.ruleset_id==='ZGE_SKILL_DAILY_CANDIDATES_R2',texts=['Z哥技能R2研究 · 原图优先','九组技能数值候选 · 待核和风险另列','股票栏排序（不改变技能数值分组）','海外资料仅作背景；技能R2数值命中与图审结论分别显示。','数值命中、图审结论和风险待核分别记录；仅供研究，不下单。','技能R2候选 · 研究展示'];const formulaTexts=['用户公式选股','192选股 · 回测选股','股票栏排序','海外资料用于研究背景。','本批展示两份公式的收盘命中。','两组收盘候选'];
 const formula=!day||Boolean(day.formula_groups);
 document.title=formula?'跨市场观察工作台 · 用户公式选股':skill?'跨市场观察工作台 · Z哥技能R2':originalTitle;
 originalTexts.forEach(([selector,old],i)=>{const element=document.querySelector(selector);if(element)element.textContent=formula?formulaTexts[i]:skill?texts[i]:old})}
let day=null,chartSet=null,charts=new Map,names={},selected=null,group='all',page=0,loadToken=0,stockToken=0,filtered=[];const pageSize=40;
let top200Rows=[],top200State='NOT_LOADED',top200Reason='本日 Top200 待读取';
function top200FilterLabel(){if(top200State==='READY')return `Top200 ${top200Rows.length}`;if(top200State==='PARTIAL')return `Top200 ${top200Rows.length}/200 · 部分`;if(top200State==='EMPTY')return 'Top200 尚未物化';if(top200State==='CANNOT_CONFIRM')return 'Top200 待核';return 'Top200 读取中';}
export function requestedSelectionFromSearch(search){const values=new URLSearchParams(search).getAll('symbol');if(!values.length)return {status:'ABSENT',symbol:null};if(values.length!==1||!/^[0-9]{6}\.(SH|SZ|BJ)$/.test(values[0]))return {status:'INVALID',symbol:values[0]??null};return {status:'REQUESTED',symbol:values[0]};}
export function resolveRequestedSelection(rows,request){if(request?.status!=='REQUESTED')return {status:request?.status??'ABSENT',symbol:request?.symbol??null,row:rows[0]??null,index:rows.length?0:-1};const index=rows.findIndex(row=>row.symbol===request.symbol);return index<0?{status:'NOT_FOUND',symbol:request.symbol,row:rows[0]??null,index:rows.length?0:-1}:{status:'MATCHED',symbol:request.symbol,row:rows[index],index};}
let projections=new Map,projectionAbort=null,interactiveLoaded=null,clearDailyChart=null;
const dailyChartHost=node('div','');
dailyChartHost.id='formulaDailyChart';
dailyChartHost.hidden=true;
$('interactiveChart').before(dailyChartHost);
let observationSnapshot=null,marketContextSnapshot=null,observationRows=new Map,observationToken=0,timeContract=null,lastClockSignature=null,observationLoading=false,lastObservationRead=0;
let researchCalendarDays=[],entryIntent=null,entryBinding=null;
const catalogKey=entry=>entry.source_date+(entry.revision?'|'+entry.revision:'');
const preferredDay=preferredCatalogEntry;
function syncResearchCalendar(){const current=entryBinding?.entry,input=$('researchCalendar');input.value=current?.observation_date??entryIntent?.observation_date??entryIntent?.source_date??entryIntent?.legacy_date??'';$('researchDateStatus').textContent=current?`观察 ${current.observation_date} · 来源 ${current.source_date} 收盘`:`${input.value} ${entryBinding?.status??'未物化'} · CANNOT_CONFIRM`;}
function setResolvedEntry(resolution){
 entryBinding=resolution;entryIntent=resolution.intent;
 const entry=resolution.entry,select=$('date'),key=entry?catalogKey(entry):(entryIntent.observation_date??entryIntent.source_date??entryIntent.legacy_date??'');
 let option=Array.from(select.options).find(item=>item.value===key);
 if(!option){option=node('option',key+(entry?'':' · 未物化 / CANNOT_CONFIRM'));option.value=key;select.append(option)}select.value=key;
 history.replaceState(null,'',entryUrl(location.href,entryIntent));syncResearchCalendar();
}
function selectResearchDay(entry,{latest=false}={}){followLatestResearchDay=latest;entryIntent=latest?{mode:'latest'}:{mode:'source',source_date:entry.source_date,observation_date:entry.observation_date};setResolvedEntry(resolveCatalogRequest(entryIntent,researchCalendarDays));return loadDay();}
$('researchCalendar').onchange=()=>{const value=$('researchCalendar').value;if(!value)return;followLatestResearchDay=false;entryIntent={mode:'observation',observation_date:value};setResolvedEntry(resolveCatalogRequest(entryIntent,researchCalendarDays));return loadDay();};
$('researchLatest').onclick=()=>{const entry=preferredDay(researchCalendarDays);if(!entry){$('researchDateStatus').textContent='尚无已物化研究日 · CANNOT_CONFIRM';return}return selectResearchDay(entry,{latest:true});};
const currentButton=node('button','跟随今天');currentButton.type='button';currentButton.id='researchCurrent';$('researchLatest').before(currentButton);
currentButton.onclick=()=>{followLatestResearchDay=true;entryIntent={mode:'current'};setResolvedEntry(resolveCatalogRequest(entryIntent,researchCalendarDays));return loadDay();};
function refreshCurrentDay(){
 if(entryIntent?.mode!=='current'||entryIntent.observation_date===shanghaiToday())return;
 entryIntent={mode:'current'};setResolvedEntry(resolveCatalogRequest(entryIntent,researchCalendarDays));loadDay();window.StockPanelHost.refreshSavedSources();
}

function lockR2Attempts(select,entries){const r2=new Map(entries.filter(e=>e.ruleset_id==='ZGE_SKILL_DAILY_CANDIDATES_R2'&&e.revision).map(e=>[e.source_date,e]));for(const entry of entries){if(entry.revision)continue;const option=Array.from(select.options).find(o=>o.value===entry.source_date);if(option)option.disabled=r2.has(entry.source_date);}return r2}
const selection=()=>{const [date,revision]=$('date').value.split('|');return {date,revision}};
const endpoint=part=>preview?`./preview/${part==='history'?'history.json':part==='charts'?'charts.json':part==='projections'?'projections.json':part.startsWith('company/')?part+'.json':'day.json'}`:`${integrationBase}/${part==='history'?'history':`days/${selection().date}${part==='day'?'':part==='charts'?'/charts':part==='projections'?'/projections':'/'+part}${selection().revision?'?revision='+selection().revision:''}`}`;
const name=r=>displayName(r,names);
function safeLink(label,url){try{const u=new URL(url,location.href);if(!['http:','https:'].includes(u.protocol))return node('span',label);const a=node('a',label);a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';return a}catch{return node('span',label)}}
let v192ReadToken=0;
async function refreshV192Group(render=true){
 const bound=day,mine=++v192ReadToken;if(!bound||bound.formula_groups)return;
 let value;
 try{value=validateV192Group(await loadJson(endpoint('v192')),bound)}
 catch(error){value={schema:'V4_WORKBENCH_V192_GROUP_V1',group_id:'v192',label:'v1.9.2候选',status:'CANNOT_CONFIRM',reason:error.message,rows:[],count:0,source_date:bound.source_date,observation_date:bound.observation_date,generation:bound.generation,input_sha256:bound.input_sha256,selector_sha256:bound.source_selector_sha256,numeric_manifest:bound.numeric_manifest,rank_usage_boundary:'RANK_FOR_REVIEW_ONLY_NOT_BUY_PRIORITY',historical_PIT:false,RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false};}
 if(mine!==v192ReadToken||day!==bound)return;
 day={...bound,v192_group:value};
 if(render){window.StockPanelHost.bindDay(day);renderFilters();renderSecondary();const refreshed=group==='v192'&&value.rows.find(row=>row.symbol===selected?.symbol);if(refreshed)selectStock(refreshed);else renderList(false);}
}
function renderFilters(){
 const counts=day.formula_groups?.group_counts??Object.fromEntries(Object.keys(GROUPS).map(g=>[g,day.rows.filter(r=>r.group_states[g]==='TRUE').length]));
 const groups=Object.entries(GROUPS).map(([id,label])=>[id,`${label} ${counts[id]??'待物化'}`]);
 const top200Option=['top200',top200FilterLabel()];
 const options=day.formula_groups?[...groups,top200Option]:[['all','全部候选'],...groups,top200Option,['v192',`v1.9.2候选 ${!day.v192_group||day.v192_group.status==='CANNOT_CONFIRM'?'待核 · 数量未知':day.v192_group.status==='PARTIAL'?day.v192_group.valid_count+' / 来源 '+day.v192_group.source_count+' · 待核 '+day.v192_group.pending_count:day.v192_group.count}`],['pending',day.ruleset_id==='ZGE_SKILL_DAILY_CANDIDATES_R2'?'数值待核':'有组别待核'],['fifth',day.ruleset_id==='ZGE_SKILL_DAILY_CANDIDATES_R2'?'风险复核':'风险 / 待核披露'],...(day.ruleset_id==='ZGE_SKILL_DAILY_CANDIDATES_R2'?[['review_keep','图审保留'],['review_watch','图审观察'],['review_defer','图审暂缓']]:[])];
 const host=$('groupFilters');
 // A completion refresh may arrive during a click. Keep matching group buttons connected.
 const reuseButtons=Boolean(day.formula_groups)&&host.children.length===options.length&&options.every(([key],index)=>host.children[index].dataset.group===key&&typeof host.children[index].onclick==='function');
 if(!reuseButtons)host.replaceChildren();
 for(const [index,[key,label]] of options.entries()){
  const b=reuseButtons?host.children[index]:node('button',label);
  if(b.textContent!==label)b.textContent=label;
  b.disabled=key!=='top200'&&day.formula_groups?.status==='CANNOT_CONFIRM_NOT_MATERIALIZED';
  b.classList.toggle('active',key===group);b.setAttribute('aria-pressed',String(key===group));
  if(!reuseButtons){b.type='button';b.dataset.group=key;b.onclick=()=>{group=group===key?'all':key;page=0;renderFilters();renderList(true)};host.append(b);}
 }
 $('classificationQuery').disabled=group==='top200';for(const checkbox of document.querySelectorAll('[data-classification-label]'))checkbox.disabled=group==='top200';
 let modelNote=$('v192GroupStatus');if(!modelNote){modelNote=node('p','');modelNote.id='v192GroupStatus';modelNote.className='field-note';$('groupFilters').after(modelNote)}modelNote.hidden=group!=='v192';modelNote.textContent=v192Summary(day.v192_group)}
function renderTop200List(selectFirst=false){
 const query=$('query').value.trim().toLowerCase();
 filtered=query?top200Rows.filter(r=>`${r.symbol} ${r.name}`.toLowerCase().includes(query)):top200Rows;
 page=Math.max(0,Math.min(page,Math.max(0,Math.ceil(filtered.length/pageSize)-1)));
 const list=$('stockList');list.replaceChildren();
 if(!filtered.length){
  const status=top200State==='EMPTY'?`${day.source_date} Top200 尚未物化 · CANNOT_CONFIRM`:top200State==='CANNOT_CONFIRM'?`${day.source_date} Top200 待核 · ${top200Reason}`:top200State==='PARTIAL'?'当前搜索无匹配项':'正在读取本日 Top200…';
  list.append(Object.assign(node('p',status),{className:'stock-list-empty'}));
  $('listCount').textContent=`Top200 · ${top200State==='READY'?'0只匹配':top200State==='PARTIAL'?`${top200Rows.length}/200 部分`:'待确认'} · 排名为D日收盘描述性结果，历史PIT未认证`;
  $('listPage').textContent='';$('prevList').disabled=true;$('nextList').disabled=true;
  selected=null;++stockToken;clearInteractive();f10Cards.cancel();window.StockPanelHost.clearCompany();$('content').hidden=true;$('loadingState').textContent=status;updateSortHeaders();return;
 }
 const pageRows=filtered.slice(page*pageSize,(page+1)*pageSize);
 for(const r of pageRows){
  const b=node('button',''),identity=node('span',''),code=node('small',r.symbol);
  b.className='stock-item stock-grid-row';b.dataset.symbol=r.symbol;b.classList.toggle('active',selected?.symbol===r.symbol);
  identity.className='stock-grid-name';identity.append(node('strong',`${r.rank}. ${r.name}`),code);
  const price=node('span',priceLabel({currency:'CNY',price:r.close})),change=node('span',`${Number(r.change_pct)>0?'+':''}${Number(r.change_pct).toFixed(2)}%`),amount=node('span',amountLabel({currency:'CNY',amount_source:r.amount_cny}));
  price.className='grid-price';change.className=Number(r.change_pct)>=0?'up':'down';amount.className='grid-amount';b.append(identity,price,change,amount);
  for(const horizon of ['D+2','D+5']){const rate=node('span','—');rate.className='grid-rate';rate.title=`Top200独立收盘名单；${horizon}同定义统计未接入`;b.append(rate);}
  b.title=JSON.stringify({rank:r.rank,symbol:r.symbol,source_date:r.source_date,close:r.close,change_pct:r.change_pct,amount_cny:r.amount_cny,eligibility:r.eligibility,history_basis:r.history_basis,visual_review_status:r.visual_review_status});
  b.onclick=()=>selectTop200Stock(r);list.append(b);
 }
 const overlap=filtered.filter(r=>day.rows.some(item=>item.symbol===r.symbol)).length;
 $('listCount').textContent=`Top200 ${top200State==='PARTIAL'?`${top200Rows.length}/200 · 部分`:`${top200Rows.length}只`} · 本日192/PB2交付行重合 ${overlap}/${filtered.length} · 收盘描述性排名，历史PIT未认证\n筛选后 ${filtered.length}只 · 本页 ${pageRows.length}只（${page*pageSize+1}–${page*pageSize+pageRows.length}）`;
 $('listPage').textContent=`第 ${page+1} 页 / 共 ${Math.ceil(filtered.length/pageSize)} 页 · 每页 ${pageSize}只`;
 $('prevList').disabled=page===0;$('nextList').disabled=(page+1)*pageSize>=filtered.length;updateSortHeaders();
 if(selectFirst||!selected||!filtered.some(r=>r.symbol===selected.symbol))selectTop200Stock(pageRows[0]);
}
function renderList(selectFirst=false,requestedSelection=null){
 if(!day)return;if(group==='top200'){renderTop200List(selectFirst);return null;}filtered=filterStocks(day,{scope:$('scope').value,query:$('query').value,group,names});filtered=filtered.filter(r=>matchesClassification(r,{query:$('classificationQuery').value,labels:Array.from(document.querySelectorAll('[data-classification-label]:checked')).map(n=>n.value)}));filtered=/^d[25]_/.test($('stockSort').value)?(group==='v192'?filtered:sortHistoryRates(filtered,group,$('stockSort').value)):sortDisplayStocks(filtered,{day:quoteContext(day,{v192_member:group==='v192'}),snapshot:observationSnapshot,mode:$('stockSort').value,names});page=Math.max(0,Math.min(page,Math.max(0,Math.ceil(filtered.length/pageSize)-1)));$('stockList').replaceChildren();
 const initialSelection=selectFirst?resolveRequestedSelection(filtered,requestedSelection):null;if(initialSelection?.status==='MATCHED')page=Math.floor(initialSelection.index/pageSize);page=Math.max(0,Math.min(page,Math.max(0,Math.ceil(filtered.length/pageSize)-1)));$('stockList').replaceChildren();
 for(const r of filtered.slice(page*pageSize,(page+1)*pageSize)){const b=node('button','');b.className='stock-item stock-grid-row';b.dataset.symbol=r.symbol;b.classList.toggle('active',selected?.symbol===r.symbol);const quote=displayQuote(r,quoteContext(day,r),observationSnapshot),observed=quote.row,rank=quote.validity.percent,identity=node('span',''),code=node('small',r.symbol);identity.className='stock-grid-name';identity.append(node('strong',name(r)),code);if(quote.role==='SOURCE_DATE_CLOSE_REFERENCE')identity.append(node('small',quote.label));const price=node('span',quote.validity.price.valid?priceLabel(observed):'—'),change=node('span',rank.valid?`${Number(observed.change_percent_source)>0?'+':''}${quote.role==='SOURCE_DATE_CLOSE_REFERENCE'?Number(observed.change_percent_source).toFixed(2):observed.change_percent_source}%`:'—'),amount=node('span',quote.validity.amount.valid?amountLabel(observed):'—');price.className='grid-price';change.className=rank.valid?(Number(observed.change_percent_source)>=0?'up':'down'):'stale';amount.className='grid-amount';b.append(identity,price,change,amount);for(const h of ['d2','d5']){const skill=Boolean(day.formula_groups)||day.ruleset_id==='ZGE_SKILL_DAILY_CANDIDATES_R2'||group==='v192',rate=node('span',skill?'—':rateLabel(r,group,h)),value=skill?{}:historyRate(r,group,h);rate.className='grid-rate';if(!skill&&!['nav_smallk','original','nav_pullback','nav_breakout'].includes(group)){const own=node('small',({nav_smallk:'小K',original:'原式',nav_pullback:'回踩',nav_breakout:'突破'})[value.group]??'无命中组');own.style.display='block';rate.append(own);}rate.title=group==='v192'?'v1.9.2同定义D+2/D+5统计未接入':day.formula_groups?'该分组同定义历史统计未物化':skill?'新R2无同定义历史事件，统计未物化':`${value.group??'无命中组'} · ${h} · 正收益/已成熟有效次数；未成熟 ${value.not_matured??'未知'}`;b.append(rate);}b.title=JSON.stringify({symbol:r.symbol,quote_role:quote.role,quote_label:quote.label,source_date:quote.role==='SOURCE_DATE_CLOSE_REFERENCE'?day.source_date:day.observation_date,source_asof:observed?.source_asof,currency:observed?.currency,price_raw:observed?.price,amount_source_yuan:observed?.amount_source,amount_kind:'累计成交额，不是10分钟增量',volume:volumeLabel(observed),state:STATUS_ZH[rank.state],groups:groupLabels(r),official_industry:observationSnapshot?.context?.classification_overlay?.rows?.[r.symbol]?.official_major??null});b.onclick=()=>selectStock(r);$('stockList').append(b);}
 const totalCandidates=day.rows.filter(r=>r.eligible_candidate).length,scopeCount=group==='v192'?(day.v192_group?.count??0):$('scope').value==='all'?day.rows.length:totalCandidates,pageRows=filtered.slice(page*pageSize,(page+1)*pageSize);$('listCount').textContent=`${group==='v192'?(day.v192_group?.status==='CANNOT_CONFIRM'||!day.v192_group?'v1.9.2候选 来源待核 · 数量未知':day.v192_group.status==='PARTIAL'?'v1.9.2候选 来源 '+day.v192_group.source_count+'只 · 有效 '+day.v192_group.valid_count+'只 · 待核 '+day.v192_group.pending_count+'只':'v1.9.2候选 '+scopeCount+'只')+' · 原四组候选 '+totalCandidates+'只':'总候选 '+totalCandidates+'只 · 当前范围 '+scopeCount+'只'}\n筛选后 ${filtered.length}只 · 本页 ${pageRows.length}只${pageRows.length?'（'+(page*pageSize+1)+'–'+(page*pageSize+pageRows.length)+'）':''}`;if(group==='v192'&&(!day.v192_group||day.v192_group.status==='CANNOT_CONFIRM'))$('listCount').textContent='v1.9.2候选 来源待核 · 数量未知 · 原四组候选 '+totalCandidates+'只';$('listPage').textContent=`第 ${filtered.length?page+1:0} 页 / 共 ${Math.ceil(filtered.length/pageSize)} 页 · 每页 ${pageSize}只`;if(group==='v192'&&(!day.v192_group||day.v192_group.status==='CANNOT_CONFIRM'))$('listPage').textContent='待来源核验';$('prevList').disabled=page===0;$('nextList').disabled=(page+1)*pageSize>=filtered.length;updateSortHeaders();
 if(selectFirst||!selected||!filtered.some(r=>r.symbol===selected.symbol)){if(filtered.length)selectStock(initialSelection?.status==='MATCHED'?initialSelection.row:filtered[0]);else{selected=null;++stockToken;clearInteractive();f10Cards.cancel();window.StockPanelHost.clearCompany();$('stockList').append(Object.assign(node('p','没有符合条件的股票，请调整上方范围、分组或搜索。'),{className:'stock-list-empty'}));$('content').hidden=true;$('loadingState').textContent='没有符合条件的股票，请调整上方筛选。'}}return initialSelection;
}
function updateSortHeaders(){for(const b of document.querySelectorAll('[data-stock-sort]')){const key=b.dataset.stockSort,mode=$('stockSort').value,active=mode.startsWith(key+'_');b.disabled=group==='top200'||Boolean(day?.formula_groups&&['d2','d5'].includes(key));b.classList.toggle('active',active);b.textContent=({name:'股票名称',price:'股价',percent_change:'涨幅',amount:'成交额',d2:'D+2',d5:'D+5'})[key]+(active?(mode.endsWith('_asc')?' ↑':' ↓'):'');b.setAttribute?.('aria-label',b.textContent+'，点击切换排序');}}
function applyStockSort(mode){if(group==='top200')return;$('stockSort').value=mode;page=0;$('observationSummary').textContent=observationHeader(observationSnapshot)+(mode.startsWith('cumulative')?' '+volumeCoverage(observationSnapshot):'');renderList(false);}
function selectTop200Stock(r){
 const member=day?.rows.find(row=>row.symbol===r.symbol);
 if(member){selectStock({...member,top200_rank:r.rank});return;}
 selected={...r,top200_only:true,top200_rank:r.rank};++stockToken;clearInteractive();f10Cards.cancel();window.StockPanelHost.clearCompany();
 $('content').hidden=false;$('loadingState').textContent='';$('stockName').textContent=r.name;$('stockCode').textContent=r.symbol;
 $('selectedGroup').textContent=`Top200 第 ${r.rank} 名 · 独立收盘名单`;$('dates').textContent=`源数据 ${day.source_date} · 收盘描述性排名 · 非实时行情`;
 $('selectedPrice').textContent=priceLabel({currency:'CNY',price:r.close})+' 元';$('selectedAmount').textContent='收盘成交额 '+amountLabel({currency:'CNY',amount_source:r.amount_cny});
 $('selectedQuoteTime').textContent='D日收盘字段 · 源时刻精度未知';$('selectedObservation').textContent=`Top200 第 ${r.rank} 名 · 收盘涨幅 ${Number(r.change_pct).toFixed(2)}% · 历史PIT未认证；该股票未收录于本日192/PB2公式交付行。`;
 $('groupChips').replaceChildren(Object.assign(node('span',`Top200 第 ${r.rank} 名`),{className:'chip'}),Object.assign(node('span','未进入本日公式交付行'),{className:'chip pending'}));
 $('stateLabels').replaceChildren(node('p','192选股：该代码未收录于当前D日公式交付行；不据此推断缺失行情的计算结果。'),node('p','回测选股：该代码未收录于当前D日公式交付行；不据此推断公式是否命中。'),node('p','Top200 独立收盘排名不等于图审通过、买点或交易指令。'));
 $('numericDetails').textContent=JSON.stringify({status:'OUTSIDE_CURRENT_FORMULA_DELIVERY_ROWS',source_date:day.source_date,top200:r},null,2);
 $('classificationSummary').replaceChildren(node('p',`Top200来源字段：官方大类 ${r.official_major??'UNKNOWN'}；结构 ${r.structure??'UNKNOWN'}。公司分类身份与行业来源尚未在本日公式Reader绑定。`));
 $('chartEmpty').hidden=false;$('chartEmpty').textContent='本日公式图表资料不可用：该股未绑定到当前D日公式交付行；没有用其他日期图替代。';$('originalChart').hidden=true;$('originalChart').removeAttribute('src');$('openOriginal').hidden=true;$('chartCaption').textContent='';
 $('interactivePanel').hidden=false;$('interactiveChart').hidden=true;$('projectionStatus').textContent='同源日K图不可用：公式 Reader 未绑定该 Top200 行（WORKBENCH_DAILY_K_SYMBOL_NOT_BOUND）。';
 $('chartDetails').textContent=JSON.stringify({status:'NOT_MATERIALIZED',reason:'WORKBENCH_DAILY_K_SYMBOL_NOT_BOUND',source_date:day.source_date,symbol:r.symbol},null,2);
 $('companySummary').replaceChildren(node('p','该代码未进入本日公式逐股资料范围，公司材料暂不可用。'));$('companyMetrics').replaceChildren();$('companyEvidence').replaceChildren();$('kbSingleResearch').hidden=true;
 renderList(false);
}
function selectCurrentStock(r){if(group==='top200')selectTop200Stock(r);else selectStock(r)}
function selectStock(r){selected=r;const token=++stockToken;$('content').hidden=false;$('loadingState').textContent='';$('stockName').textContent=name(r);$('stockCode').textContent=r.symbol;$('selectedGroup').textContent=(Number.isInteger(r.top200_rank)?`Top200 第 ${r.top200_rank} 名 · `:'')+(groupLabels(r).join(' / ')||'全范围研究记录');$('dates').textContent=`源数据 ${day.source_date} · 观察日期 ${day.observation_date} · 非实时行情`;$('groupChips').replaceChildren();if(Number.isInteger(r.top200_rank)){const rankChip=Object.assign(node('span',`Top200 第 ${r.top200_rank} 名`),{className:'chip'});rankChip.dataset.top200Rank='true';$('groupChips').append(rankChip)}for(const label of groupLabels(r)){$('groupChips').append(Object.assign(node('span',label),{className:'chip'}))}if(Object.values(r.group_states).includes('UNKNOWN'))$('groupChips').append(Object.assign(node('span','部分组别待核'),{className:'chip pending'}));if(day.ruleset_id==='ZGE_SKILL_DAILY_CANDIDATES_R2'){const review=r.r2_review??{},label=review.status==='REVIEWED'?({KEEP:'保留',WATCH:'观察',DEFER:'暂缓'})[review.decision]:(review.status==='NOT_REVIEWED'?'未审图':'审图记录待核');$('groupChips').append(Object.assign(node('span','数值 '+r.r2_record_status+' · 图审 '+label),{className:'chip pending'}));}
$('numericDetails').textContent=JSON.stringify(r,null,2);$('stateLabels').replaceChildren(...Object.entries(GROUPS).map(([g,l])=>node('p',`${l}：${stateLabel(r.group_states[g])}`)));selectedObservation(r);renderClassification(r);showChart(r);loadInteractive(r,token);renderList();loadCompany(r,token);if(day.formula_groups)f10Cards.show(day,r.symbol,endpoint('f10/'+r.symbol))}
function showChart(r){if(day.formula_groups){$('chartDetails').textContent='';$('openOriginal').hidden=true;$('originalChart').removeAttribute('src');return}const extension=r.v192_assets?.chart,row=extension??charts.get(r.symbol),img=$('originalChart');img.hidden=true;img.removeAttribute('src');$('openOriginal').hidden=true;$('chartShell').classList.remove('original');$('chartShell').classList.add('focus');$('chartEmpty').hidden=false;$('chartEmpty').textContent='本股同源原图尚未接入，不借用其他日期图。';$('chartCaption').textContent='';$('chartDetails').textContent='';$('chartCoverage').textContent=`${charts.size} / ${day.rows.filter(x=>x.eligible_candidate).length} 张原图`;
if(!row)return;const bound=extension?{...row}:{...row,source_date:chartSet.source_date,source_generation:chartSet.source_generation,source_input_sha256:chartSet.source_input_sha256,chart_review:chartSet.chart_review,full_stock_PASS:chartSet.full_stock_PASS};if(!validateChartMatch(bound,r,day)){$('chartEmpty').textContent='图源日期或批次不一致，已隔离，不展示。';return}if(!row.image_url&&row.html_url){const shared=new URL(row.html_url,location.href);if(shared.origin!==location.origin){$('chartEmpty').textContent='图源不在本私有站点，待接入。';return;}$('chartEmpty').hidden=true;$('openOriginal').href=shared.href;$('openOriginal').hidden=false;$('chartCaption').textContent=`${name(r)} · ${day.source_date} · ${row.rows_declared}根同源原式历史；下方交互图可查看，打开原图后可按需导出PNG。`;$('chartDetails').textContent=JSON.stringify(bound,null,2);return;}const u=new URL(row.image_url,location.href);if(u.origin!==location.origin){$('chartEmpty').textContent='图源不在本私有站点，待接入。';return}const wanted=r.symbol;img.onload=()=>{if(selected?.symbol!==wanted)return;$('chartEmpty').hidden=true;img.hidden=false};img.onerror=()=>{if(selected?.symbol!==wanted)return;img.hidden=true;$('chartEmpty').hidden=false;$('chartEmpty').textContent='原图读取失败，请稍后重试；未替换为其他图。'};img.alt=`${name(r)} ${r.symbol} ${day.source_date} 原式图，图审待完成`;img.src=u.href;$('chartEmpty').textContent='正在读取原式图…';$('openOriginal').href=u.href;$('openOriginal').hidden=false;$('chartCaption').textContent=`${name(r)} · ${day.source_date} · 来源历史 ${row.rows_declared??'未提供'} 根；截图窗口以图内标注为准。静态图，图内控件不可点击。`;$('chartDetails').textContent=JSON.stringify(bound,null,2)}
function selectedObservation(r){
 if(r?.top200_only){$('selectedPrice').textContent=priceLabel({currency:'CNY',price:r.close})+' 元';$('selectedAmount').textContent='收盘成交额 '+amountLabel({currency:'CNY',amount_source:r.amount_cny});$('selectedQuoteTime').textContent='D日收盘字段 · 源时刻精度未知';$('selectedObservation').textContent=`Top200 第 ${r.rank} 名 · 收盘涨幅 ${Number(r.change_pct).toFixed(2)}% · 历史PIT未认证；该股票未收录于本日192/PB2公式交付行。`;return;}
 const quote=displayQuote(r,quoteContext(day,r),observationSnapshot),o=quote.row;
 $('selectedPrice').textContent=(quote.validity.price.valid?priceLabel(o)+' 元':'—')+(quote.role==='SOURCE_DATE_CLOSE_REFERENCE'&&quote.validity.percent.valid?` · ${Number(o.change_percent_source)>0?'+':''}${Number(o.change_percent_source).toFixed(2)}%`:'');
 $('selectedAmount').textContent=(quote.role==='SOURCE_DATE_CLOSE_REFERENCE'?'收盘成交额 ':'累计成交额 ')+(quote.validity.amount.valid?amountLabel(o):'—');
 if(quote.role==='SOURCE_DATE_CLOSE_REFERENCE'){
  $('selectedQuoteTime').textContent=quote.label+' · 源精确时刻 UNKNOWN';
  $('selectedObservation').textContent=`${quote.label} · 涨幅 ${quote.validity.percent.valid?Number(o.change_percent_source).toFixed(2)+'%':'—'} · 前复权口径；${day.observation_date} 观察报价尚未就绪。`;
 }else{
  $('selectedQuoteTime').textContent=o?`源 ${shanghaiParts(o.source_asof)?.clock??'未知'} · ${STATUS_ZH[quote.validity.price.state]??'待核'}`:'源时点待核';
  $('selectedObservation').textContent=o?`当日源快照 ${shanghaiParts(o.source_asof)?.clock??'时间待核'} · 涨幅 ${quote.validity.percent.valid?o.change_percent_source+'%':'—'} · ${volumeLabel(o)} · ${STATUS_ZH[quote.validity.percent.state]??'待核'}；不是下方复权图坐标。`:'该股当日快照未绑定；收盘参考尚未确认。';
 }
}
function tickObservationPresentation(){refreshCurrentDay();if(!day||!observationSnapshot)return;const now=new Date().toISOString(),states=observationSnapshot.rows.map(r=>rowValidity(r,observationSnapshot,'percent',now).state).join('|'),signature=observationSnapshot.snapshot_sha256+'|'+$('stockSort').value+'|'+states;renderPhase(timeContract,observationSnapshot,now);if(signature===lastClockSignature)return;lastClockSignature=signature;const focused=document.activeElement?.dataset?.symbol;$('observationSummary').textContent=observationHeader(observationSnapshot,now)+($('stockSort').value.startsWith('cumulative')?' '+volumeCoverage(observationSnapshot):'');if(selected){selectedObservation(selected);if(!selected.top200_only)renderClassification(selected);}renderList(false);if(focused)$('stockList').querySelector(`[data-symbol="${focused}"]`)?.focus({preventScroll:true});}
setInterval(tickObservationPresentation,30000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)tickObservationPresentation()});
async function refreshObservationData(){const mine=++observationToken,identity=selection().date+'|'+selection().revision,currentDay=day;if(!currentDay)return;try{const url=preview?'./preview/observations.json':`${integrationBase}/days/${currentDay.source_date}/observations?observation_date=${currentDay.observation_date}${selection().revision?'&revision='+selection().revision:''}`;observationLoading=true;lastObservationRead=Date.now();$('refreshObservations').disabled=true;const value=await loadJson(url,(u,o)=>fetch(u,{...o,signal:AbortSignal.timeout(15000)}));if(mine!==observationToken||day!==currentDay||identity!==selection().date+'|'+selection().revision)return;const candidate=value?.latest??null;marketContextSnapshot=validMarketContextSnapshot(candidate,currentDay,selection().revision)?candidate:null;const next=validateSnapshot(candidate,currentDay,selection().revision),contextChanged=next?.context_sha256!==observationSnapshot?.context_sha256;observationSnapshot=next;$('observationMini').dataset.fetchState='ready';observationRows=new Map((observationSnapshot?.rows??[]).map(r=>[r.symbol,r]));$('observationSummary').textContent=observationHeader(observationSnapshot)+($('stockSort').value.startsWith('cumulative')?' '+volumeCoverage(observationSnapshot):'');if(contextChanged)renderContext(timeContract,observationSnapshot);else renderPhase(timeContract,observationSnapshot);if(selected){selectedObservation(selected);if(!selected.top200_only)renderClassification(selected);}renderList(false);}catch{if(mine!==observationToken||day!==currentDay)return;$('observationMini').dataset.fetchState='failed';$('observationSummary').textContent='本次刷新未完成；'+(observationSnapshot?'保留本日最后成功快照，按源时间标记过期。 '+observationHeader(observationSnapshot):'无本日合格快照，不沿用旧日数据。');renderContext(timeContract,observationSnapshot);if(selected){selectedObservation(selected);if(!selected.top200_only)renderClassification(selected);}renderList(false);}finally{if(mine===observationToken){observationLoading=false;$('refreshObservations').disabled=false;}}}
function clearInteractive(){projectionAbort?.abort();projectionAbort=null;interactiveLoaded=null;clearDailyChart?.();clearDailyChart=null;dailyChartHost.hidden=true;window.OriginalFullChart?.clear?.();$('interactiveChart').hidden=true;$('exactValues').textContent='';}
async function loadInteractive(r,token){clearInteractive();$('interactivePanel').hidden=false;
 if(day.formula_groups){
  const bound=day,controller=new AbortController();
  projectionAbort=controller;
  $('projectionStatus').textContent=`${r.symbol} · 正在读取同源日K…`;
  try{
   await window.StockPanelHost.open(bound,r,group,{renderChart:false});
   const value=await loadJson(endpoint('formula-daily-k/'+r.symbol),(url,options)=>fetch(url,{...options,signal:controller.signal}));
   if(token!==stockToken||controller.signal.aborted)return;
   const chart=validateDailyChart(value,bound,r.symbol);
   dailyChartHost.hidden=false;
   clearDailyChart=renderDailyChart(dailyChartHost,chart);
   $('projectionStatus').textContent=`${r.symbol} · ${chart.rows.length}根 · 截至 ${chart.source_date} · 同组历史统计待核`;
  }catch(error){
   if(token!==stockToken||controller.signal.aborted)return;
   dailyChartHost.hidden=true;
   $('projectionStatus').textContent=`${r.symbol} · 本日行情待核：${error.message}`;
  }
  return;
 }
$('projectionStatus').textContent='正在读取同源原图及历史统计…';try{const bundle=await window.StockPanelHost.open(day,r,group);if(token!==stockToken)return;if(bundle?.status==='NOT_MATERIALIZED'){clearInteractive();$('projectionStatus').textContent='v1.9.2候选 · '+bundle.reason+'；同定义D+2/D+5统计未接入。';return}interactiveLoaded=bundle.projection;$('interactiveChart').hidden=false;$('projectionStatus').textContent=`${bundle.projection.data.rows.length}根原式历史 · ${day.ruleset_id?'新R2同定义历史统计未物化':'已物化统计'} · 图审状态见分组` ;}catch(error){if(token!==stockToken)return;clearInteractive();$('projectionStatus').textContent='本股来源或统计暂未闭环：'+error.message;}}
const compactChart=(window.innerHeight??950)<850;for(const [id,h] of [['fullPrice',compactChart?200:360],['fullVolume',100],['fullKdj',100]]){$(id).setAttribute?.('height',String(h));}window.OriginalFullChart?.bind?.();for(const b of document.querySelectorAll('[data-full-window]'))b.onclick=()=>window.OriginalFullChart?.setWindow?.(b.dataset.fullWindow==='all'?'all':Number(b.dataset.fullWindow));$('resetInteractive').onclick=()=>{if(interactiveLoaded)window.OriginalFullChart?.setStock?.(interactiveLoaded)};window.addEventListener('original-chart-date',e=>{if(!interactiveLoaded||e.detail.symbol!==interactiveLoaded.symbol)return;const r=interactiveLoaded.data.rows.find(r=>String(r.trade_date)===String(e.detail.date));$('exactValues').textContent=r?JSON.stringify(r,null,2):'该日期没有精确原值，不就近替代。'});
function factBox(label,f){const box=node('details','');box.append(node('summary',label),node('p',`原证据标签：${f.evidence_status??'未提供'}（非本轮全量人工核准）`),node('p',`截至 ${f.asof_date??'未知'}；披露 ${f.disclosed_at??'未知'}；独立日期边界 ${independentTiming(f)}；PIT未认证`));if(f.source_url)box.append(safeLink(f.source_title??'原始来源',f.source_url));box.append(node('pre',JSON.stringify(f,null,2)));return box}
function amount(f){if(f?.value===null||f?.value===undefined)return '待核';const n=Number(f.value);if(!Number.isFinite(n))return String(f.value);if(f.unit==='元'&&Math.abs(n)>=1e8)return `${(n/1e8).toFixed(2)}亿元`;if(f.unit==='元'&&Math.abs(n)>=1e4)return `${(n/1e4).toFixed(2)}万元`;return `${n.toLocaleString('zh-CN',{maximumFractionDigits:2})}${f.unit??''}`}
async function loadCompany(r,token){const request=beginCompanyRequest({symbol:r.symbol,source_date:day.source_date,observation_date:day.observation_date,generation:day.generation,input_sha256:day.input_sha256});renderCompanyStatus(document,'LOADING',r.symbol);try{const x=await loadJson(endpoint('company/'+r.symbol));if(!isCurrentCompanyRequest(request))return;if(!x){renderCompanyStatus(document,'MISSING',r.symbol);return}validateCompany(x,r.symbol);if(x.status==='NOT_MATERIALIZED'){renderCompanyStatus(document,'MISSING',r.symbol);return}renderCompanyStatus(document,'READY',r.symbol);$('companyMetrics').replaceChildren();$('companySummary').replaceChildren(node('p',x.business?.summary?.value??'主营资料待核'));const controller=x.actual_controller;const line=node('p',`实际控制人：${controller?.value??'待核（保留原件空值或隔离）'}`);$('companySummary').append(line,node('p','公司材料仅作解释；全部历史PIT未认证，不参与选股评分。'));if(x.received_actual_controller){const warning=node('div','');warning.className='notice';warning.append(node('strong','控制人资料有缺漏，已隔离'),node('p',`原回包：${x.received_actual_controller.value}；年报抽查：${x.independent_field_audit?.primary_report_value??'待核'}。展示字段保留待核，不静默覆盖原件。`));$('companySummary').append(warning)}const finance=x.latest_financial;$('companyMetrics').append(node('p',`${finance?.report_period??'期间待核'} · ${finance?.period_kind??''}（不与不同期间混比）`));for(const [label,f] of explanationFacts(x).filter(([label])=>!['主营业务','实际控制人（派生展示字段）'].includes(label))){const p=node('div','');p.className='stat-row';p.append(node('span',label),node('strong',amount(f)));$('companyMetrics').append(p)}$('companyMetrics').append(node('p',`研报公开索引 ${x.reports?.metadata_only_count??0} 条；不是全文逐一核验。订单/业务候选 ${x.order_business_candidate_count??'待核'}，不等同销售订单。`));for(const [label,f]of explanationFacts(x))$('companyEvidence').append(factBox(label,f));window.StockPanelHost.paintCompanyReports(x);if(x.independent_field_audit)$('companyEvidence').append(node('pre',JSON.stringify({received_actual_controller:x.received_actual_controller,independent_field_audit:x.independent_field_audit},null,2)))}catch{if(isCurrentCompanyRequest(request))renderCompanyStatus(document,'ERROR',r.symbol)}}
function renderSecondary(){for(const id of ['workflow','materials'])$(id).replaceChildren();for(const item of day.workflow){const li=node('li','');li.append(node('strong',item.label),node('p',item.status));$('workflow').append(li)}for(const item of [...day.materials,...day.reference_links]){const li=node('li','');li.append(safeLink(item.label,item.url));$('materials').append(li)}$('sourceDetails').textContent=JSON.stringify({source_refs:day.source_refs,v192_source:day.v192_group?{status:day.v192_group.status,reason:day.v192_group.reason,source_count:day.v192_group.source_count,valid_count:day.v192_group.valid_count,pending_count:day.v192_group.pending_count,excluded_rows:day.v192_group.excluded_rows,run_id:day.v192_group.source_run_id,artifact_sha256:day.v192_group.source_artifact_sha256,manifest_sha256:day.v192_group.source_manifest_sha256,receipt_sha256:day.v192_group.source_receipt_sha256,selector_sha256:day.v192_group.selector_sha256,reader:day.v192_group.reader_source,quote_reference:day.v192_group.source_close_reference?{status:day.v192_group.source_close_reference.status,source_date:day.v192_group.source_close_reference.source_date,selector:day.v192_group.source_close_reference.selector,scope_count:day.v192_group.source_close_reference.scope_count,available_count:day.v192_group.source_close_reference.available_count,price_basis:day.v192_group.source_close_reference.price_basis,amount_basis:day.v192_group.source_close_reference.amount_basis}:null}:null,generation:day.generation,input_sha256:day.input_sha256,formula_review:day.formula_review,chart_review:day.chart_review,original_observation_date:day.original_observation_date,observation_status:day.observation_status},null,2)}
function resetDateDependentView(){group='all';page=0;selected=null;top200Rows=[];top200State='NOT_LOADED';top200Reason='本日 Top200 待读取';configureDayGroups(null);const filters=$('groupFilters');if(filters){filters.replaceChildren();for(const [id,label] of Object.entries(formulaGroupLabels)){const empty=node('button',label+' 待物化');empty.type='button';empty.dataset.group=id;empty.disabled=true;filters.append(empty)}}const scope=$('scope');if(scope?.options?.length>=2){scope.options[0].textContent='数值候选 · 待绑定';scope.options[1].textContent='已接入台账 · 待绑定';}if(scope)scope.value='candidates';const query=$('query');if(query)query.value='';const classificationQuery=$('classificationQuery');if(classificationQuery)classificationQuery.value='';}
async function loadDay(onListBound){const routeSelection=requestedSelectionFromSearch(location.search);window.StockPanelHost.unbindDay();observationLoading=false;$('refreshObservations').disabled=false;const token=++loadToken;++stockToken;clearInteractive();++observationToken;observationSnapshot=null;marketContextSnapshot=null;observationRows=new Map;projections=new Map;day=null;selected=null;chartSet=null;charts=new Map;names={};timeContract=null;renderContext(null,null);resetDateDependentView();$('macLegacyStockPage').href='legacy-daily.html?'+new URLSearchParams({date:selection().date});$('observationSummary').textContent='正在读取所选日期快照，不沿用旧日数据。';$('content').hidden=true;$('stockList').replaceChildren();$('loadingState').textContent='正在读取该日资料…';if(!entryBinding?.entry){$('loadingState').textContent=`${entryBinding?.status??'NOT_MATERIALIZED'} · CANNOT_CONFIRM；未采用其他日期。`;return;}try{const data=await loadJson(endpoint('day'));if(token!==loadToken)return;if(!data){$('loadingState').textContent=`${selection().date} 未物化 · CANNOT_CONFIRM；没有沿用其他日期。`;return}day=validateWorkbenchDay(data);await refreshV192Group(false);if(token!==loadToken)return;configureDayGroups(day);if(day.source_date!==selection().date)throw Error('DATE');if(!day.formula_groups)try{const c=await loadJson(endpoint('charts'));if(token!==loadToken)return;if(c){chartSet=c;charts=new Map((c.rows??[]).map(r=>[r.symbol,r]));names=Object.fromEntries((c.name_overlay?.rows??[]).map(r=>[r.symbol,r.name]));}}catch{/* Chart failure cannot silently substitute other date. */}if(token!==loadToken)return;if(!day.formula_groups)try{const p=await loadJson(endpoint('projections'));if(token!==loadToken)return;projections=new Map((p?.rows??[]).map(r=>[r.symbol,r]));}catch{}if(token!==loadToken)return;try{timeContract=await loadJson(integrationBase+'/workflow-contract?source_date='+day.source_date)}catch{timeContract=null}if(token!==loadToken)return;renderContext(timeContract,null);group='all';page=0;$('scope').value='candidates';const count=day.rows.filter(r=>r.eligible_candidate).length;$('scope').options[0].textContent=`数值候选 · ${count}只`;$('scope').options[1].textContent=`已接入台账（仅冻结候选）· ${day.rows.length}只`;window.StockPanelHost.bindDay(day);renderFilters();renderSecondary();const initial=renderList(true,routeSelection);if(day.formula_groups?.status==='CANNOT_CONFIRM_NOT_MATERIALIZED')$('loadingState').textContent='所选日期的两组选股待物化。';else if(initial&&['INVALID','NOT_FOUND'].includes(initial.status))$('loadingState').textContent=initial.status==='INVALID'?`链接指定股票代码无效 · CANNOT_CONFIRM；当前显示 ${selected?.symbol??'无候选'}。`:`链接指定股票 ${initial.symbol} 不在 ${day.source_date} 当前候选中 · CANNOT_CONFIRM；当前显示 ${selected?.symbol??'无候选'}。`;onListBound?.();await refreshObservationData();window.StockPanelHost.paintWorkflow(timeContract)}catch{if(token===loadToken){resetDateDependentView();$('content').hidden=true;$('loadingState').textContent='该日期读取失败，未用旧池替代。'}}}
async function init(onListBound){
 try{
  if(!apiBound){renderContext(null,null);$('loadingState').textContent='公共协作视觉壳：尚未绑定可信同源服务；不加载真实研究数据。';return}
  try{entryIntent=requestedEntry(location.search);}catch{$('loadingState').textContent='请求日期无效或冲突 · CANNOT_CONFIRM；未自动选择其他日期。';return;}
  try{timeContract=await loadJson(integrationBase+'/workflow-contract')}catch{}renderContext(timeContract,null);
  const h=await loadJson(endpoint('history'))??{days:[]};if(!Array.isArray(h.days))throw Error('INVALID_HISTORY_CATALOG');researchCalendarDays=h.days;
  $('date').replaceChildren();
  for(const d of h.days){const o=node('option',`${d.source_date}收盘 → ${d.observation_date}观察${d.ruleset_id==='ZGE_SKILL_DAILY_CANDIDATES_R2'?' · Z哥技能R2':''}`);o.value=catalogKey(d);$('date').append(o);}
  lockR2Attempts($('date'),h.days);setResolvedEntry(resolveCatalogRequest(entryIntent,h.days));await loadDay(onListBound);
 }catch{$('loadingState').textContent='研究目录读取失败，请稍后刷新。'}
 finally{onListBound();}
}

function railTab(which){$('schedulePanel').hidden=which!=='schedule';$('evidencePanel').hidden=which!=='evidence';for(const [id,value]of [['showSchedule','schedule'],['showEvidence','evidence']]){$(id).classList.toggle('active',which===value);$(id).setAttribute?.('aria-pressed',String(which===value));}}$('showSchedule').onclick=()=>railTab('schedule');$('showEvidence').onclick=()=>railTab('evidence');$('openWorkflow').onclick=()=>{railTab('schedule');document.querySelector('.timetable-group.current')?.scrollIntoView({block:'nearest'});};$('closeWorkflow').onclick=()=>railTab('schedule');for(const button of document.querySelectorAll('[data-stage]'))button.onclick=()=>{railTab('schedule');document.getElementById('schedule-stage-'+button.dataset.stage)?.scrollIntoView({block:'nearest'});};$('refreshObservations').onclick=refreshObservationData;$('stockSort').onchange=()=>applyStockSort($('stockSort').value);for(const b of document.querySelectorAll('[data-stock-sort]'))b.onclick=()=>{const k=b.dataset.stockSort,current=$('stockSort').value;applyStockSort(current===k+'_asc'?k+'_desc':current===k+'_desc'?k+'_asc':k+(k==='name'?'_asc':'_desc'));};
$('date').onchange=()=>{followLatestResearchDay=false;const entry=researchCalendarDays.find(item=>catalogKey(item)===$('date').value);entryIntent={mode:'source',source_date:entry?.source_date??selection().date,observation_date:entry?.observation_date??null};setResolvedEntry(resolveCatalogRequest(entryIntent,researchCalendarDays));return loadDay();};for(const id of ['query','scope'])$(id).addEventListener('input',()=>{page=0;renderFilters();renderList(true)});$('prevList').onclick=()=>{page--;renderList()};$('nextList').onclick=()=>{page++;renderList()};function move(n){const i=filtered.findIndex(r=>r.symbol===selected?.symbol),r=filtered[i+n];if(r){page=Math.floor((i+n)/pageSize);selectCurrentStock(r)}}$('prevStock').onclick=()=>move(-1);$('nextStock').onclick=()=>move(1);$('focusChart').onclick=()=>{$('chartShell').classList.remove('original');$('chartShell').classList.add('focus')};$('fitChart').onclick=()=>{$('chartShell').classList.remove('original','focus')};$('nativeChart').onclick=()=>{$('chartShell').classList.remove('focus');$('chartShell').classList.add('original')};
window.addEventListener('v4-workbench-top200-loaded',event=>{const result=event.detail;if(!day||!isTop200ForSelection(result,day.source_date)||!isTop200ForSelection(result,selection().date))return;top200State=result.status;top200Rows=Array.isArray(result.rows)?result.rows:[];top200Reason=result.reason??'';renderFilters();if(group==='top200'){const refreshed=top200Rows.find(row=>row.symbol===selected?.symbol);if(!refreshed)renderList(false);else if(selected?.top200_only)selectTop200Stock(refreshed);else{selected={...selected,top200_rank:refreshed.rank};$('selectedGroup').textContent=`Top200 第 ${refreshed.rank} 名 · ${groupLabels(selected).join(' / ')||'当前公式交付行'}`;const chip=$('groupChips').querySelector('[data-top200-rank="true"]');if(chip)chip.textContent=`Top200 第 ${refreshed.rank} 名`;renderList(false);}}});
const initialListReady=new Promise(resolve=>{void init(resolve);});

function renderClassification(r){window.StockPanelHost.paintClassification(r,day);}



let completionSerial=0,catalogSerial=0;
let followLatestResearchDay=!['date','source_date','observation_date'].some(key=>new URLSearchParams(location.search).has(key));
$('date').addEventListener('change',()=>{followLatestResearchDay=false;});
window.StockPanelHost.installCompletion({
 async catalog(force=false){
  // Startup owns the first list read. Saved completions need not wait for its optional quotes.
  await initialListReady;
  if(!entryIntent)return;
  const mine=++catalogSerial,wantedIntent=entryIntent,wantedValue=$('date').value;
  try{
   const catalog=await loadJson(integrationBase+'/history');
   if(mine!==catalogSerial||entryIntent!==wantedIntent||$('date').value!==wantedValue||!Array.isArray(catalog?.days))return;
   researchCalendarDays=catalog.days;
   const select=$('date'),existing=new Map(Array.from(select.options).map(option=>[option.value,option]));
   for(const entry of catalog.days){const key=catalogKey(entry);let option=existing.get(key);if(!option){option=node('option',entry.source_date);option.value=key;select.append(option);}option.textContent=`${entry.source_date}收盘 → ${entry.observation_date}观察`;}
   lockR2Attempts(select,catalog.days);
   const next=resolveCatalogRequest(wantedIntent,catalog.days),key=next.entry?catalogKey(next.entry):null;
   if(force||key!==wantedValue||!day){setResolvedEntry(next);await loadDay();}
   else{entryBinding=next;syncResearchCalendar();}
  }catch{if(mine===catalogSerial&&entryIntent===wantedIntent)$('loadingState').textContent='研究日期目录更新待核 · CANNOT_CONFIRM；未替换固定日期。';}
 },
 refresh(){this.modules(['list','statistics']);},
 async modules(changed,event){
  if(!day)return;
  if(changed.includes('f10')){
   if(selected&&selection().date===day.source_date&&isFormulaF10Completion(day,event)){
    void f10Cards.refresh(day,selected.symbol,endpoint('f10/'+selected.symbol));
   }
   if(changed.every(key=>key==='f10'))return;
  }
  const mine=++completionSerial,wanted=selection().date,oldDay=day;
  try{
   if(event&&(event.generation!==day.generation||event.input_sha256!==day.input_sha256)){await this.sourceChanged();return;}
   if(changed.some(k=>['list','statistics'].includes(k))){
    const next=validateWorkbenchDay(await loadJson(endpoint('day')));
    if(mine!==completionSerial||selection().date!==wanted||day!==oldDay||next.source_date!==wanted)return;
    if(next.generation!==day.generation||next.input_sha256!==day.input_sha256){await this.sourceChanged();return;}
    const symbol=selected?.symbol;day=next;configureDayGroups(day);await refreshV192Group(false);window.StockPanelHost.bindDay(day);renderFilters();renderSecondary();renderList(false);if(selected)selectedObservation(selected);
    if(next.formula_groups?.status==='CANNOT_CONFIRM_NOT_MATERIALIZED')$('loadingState').textContent='所选日期的两组选股待物化。';
    else if(oldDay.formula_groups?.status==='CANNOT_CONFIRM_NOT_MATERIALIZED')$('loadingState').textContent='';
    if(symbol&&selected?.symbol===symbol){if(group==='top200'){const row=top200Rows.find(r=>r.symbol===symbol);if(row)selectTop200Stock(row);}else{selected=(group==='v192'?day.v192_group?.rows??[]:day.rows).find(r=>r.symbol===symbol)??selected;window.StockPanelHost.preserveChart();loadInteractive(selected,++stockToken);}}
   }
   if(changed.includes('classification')&&!changed.some(k=>['list','statistics'].includes(k))){const next=validateWorkbenchDay(await loadJson(endpoint('day')));if(mine!==completionSerial||selection().date!==wanted||next.source_date!==wanted||next.generation!==day.generation||next.input_sha256!==day.input_sha256)return;const symbol=selected?.symbol;day=next;configureDayGroups(day);await refreshV192Group(false);window.StockPanelHost.paintClassificationCoverage(day);renderFilters();renderList(false);if(next.formula_groups?.status==='CANNOT_CONFIRM_NOT_MATERIALIZED')$('loadingState').textContent='所选日期的两组选股待物化。';if(symbol&&selected?.symbol===symbol){if(group==='top200'){const row=top200Rows.find(r=>r.symbol===symbol);if(row)selectTop200Stock(row);}else{selected=(group==='v192'?day.v192_group?.rows??[]:day.rows).find(r=>r.symbol===symbol)??selected;renderClassification(selected);}}}
   if(changed.includes('v192'))await refreshV192Group();
   if(changed.includes('catalog'))await this.catalog();
   if(changed.includes('top200'))await window.StockPanelHost.paintTop200();
   if(changed.includes('observations'))await refreshObservationData();
   if(mine!==completionSerial||selection().date!==wanted)return;
   if(changed.includes('workflow')){const contract=await loadJson(integrationBase+'/workflow-contract?source_date='+wanted);if(mine!==completionSerial||selection().date!==wanted)return;timeContract=contract;renderContext(timeContract,observationSnapshot);window.StockPanelHost.paintWorkflow(contract);}
   window.StockPanelHost.paintContext();
  }catch(error){if(mine===completionSerial)$('loadingState').textContent='已保存更新尚未确认：'+error.message;}
 },
 async sourceChanged(){
  window.StockPanelHost.unbindDay();++completionSerial;return this.catalog(true);
 }
});
const originalRefresh=refreshObservationData;refreshObservationData=async(...args)=>{const answer=await originalRefresh(...args);window.StockPanelHost.paintContext(marketContextSnapshot);window.StockPanelHost.paintWorkflow(timeContract);return answer};

$('classificationQuery').addEventListener('input',()=>{page=0;renderList(true)});for(const checkbox of document.querySelectorAll('[data-classification-label]'))checkbox.addEventListener('change',()=>{page=0;renderList(true)});const stockGridViewport=$('stockGridViewport');$('showStockNames').onclick=()=>stockGridViewport.scrollTo({left:0,behavior:'smooth'});$('showStockRates').onclick=()=>stockGridViewport.scrollTo({left:stockGridViewport.scrollWidth,behavior:'smooth'});
