import {installSingleResearch,financialLines,financialDisclosureText,visibleSingleHistoryGroups} from './kb-single-stock.mjs';
import {makeStockBridge} from './stock/stock-bridge.mjs';
import {loadProjection,adaptProjection} from './dot/src/projection-view.mjs';
import {loadSkillProjection} from './dot/src/workbench-model.mjs';
import {setCompanyContext,renderCompanyStatus,explanationFacts,beginCompanyRequest,isCurrentCompanyRequest,validateCompany} from './company-local.mjs';
import {renderReceivedResearch,renderMaterialTiming,createReceivedCompanyRefresh} from './received-research.mjs';
import {usMarketContext,unknownUsContext,renderMarketCard,observationMarketContext} from './workbench-us-context.mjs';
import {completionAction} from './completion-action.mjs';
import {renderClassification} from './classification-local.mjs';
const el=id=>document.getElementById(id),add=(host,tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;host.append(n);return n};
const old=document.querySelector('#interactiveChart .interactive-scroll');if(old)old.hidden=true;
const navigation=document.querySelector('#interactiveChart .chart-nav');if(navigation)navigation.hidden=true;
const container=add(el('interactiveChart'),'div');container.id='macOriginalRenderer';
const stat=add(el('interactivePanel'),'section');stat.className='panel';stat.id='macHistoricalStatistics';
let context=null,current=null,contextSerial=0,completionCallback=null,contextReply=null,activeDay=null,moduleEvents=null,moduleSerial=0,preservedChart=null,foregroundRead=null,marketObservation=null;
let r2Serial=0,r2Controller=null,skillReviewCleanup=null;
let originalReadyObserver=null;
const singleResearch=installSingleResearch({loadDetails:loadSingleDetails});
el('stockList').addEventListener('click',event=>{const symbol=event.target.closest?.('[data-symbol]')?.dataset.symbol;if(symbol&&activeDay?.source_date!=='2026-10-30')return;else if(symbol==='301048.SZ')singleResearch.openSymbol(symbol);else if(symbol)singleResearch.clear()});
const bridge=makeStockBridge({origin:location.origin,basePath:'/api/v4/research/a-share',fetcher:fetch,loadProjection,container,eventTarget:window});
const original=bridge.OriginalFullChart;
window.OriginalFullChart={...original,clear(){cancelOriginalReady();++r2Serial;r2Controller?.abort();r2Controller=null;if(skillReviewCleanup){skillReviewCleanup();skillReviewCleanup=null}original.clear();current=null;context=null;stat.replaceChildren();if(!activeDay){++contextSerial;contextReply=null;el('marketCards').textContent='跨市场来源尚未与所选日期绑定';}else paintContext();},
  setWindow(value){if(!current?.r2)return original.setWindow(value);const w=frame.contentWindow;if(!w?.setOriginalWindow||!w.RESEARCH_PANEL_STATE)throw Error('ORIGINAL_RENDERER_NOT_READY');if(value!=='all'&&(!Number.isSafeInteger(value)||value<1))throw Error('INVALID_RENDERER_WINDOW');w.setOriginalWindow(value==='all'?0:value,w.RESEARCH_PANEL_STATE.rows.length)},
  setStock(value){if(!current?.r2)return original.setStock(value);if(value!==current.projection)throw Error('RENDERER_CONTEXT_UNBOUND');return this.setWindow(120)}};
const frame=original.bind();frame.style.height="460px";
function showSkillReview(row){
  if(skillReviewCleanup)skillReviewCleanup();
  const review=row.r2_review??{},labels={KEEP:'保留',WATCH:'观察',DEFER:'暂缓'};
  const verified=review.status==='REVIEWED'&&review.actual_image_viewed===true&&Object.hasOwn(labels,review.decision);
  const label=verified?labels[review.decision]:(!review.status||review.status==='NOT_REVIEWED'?'未审':'待核');
  const box=document.createElement('section');box.className='panel';box.id='macSkillChartReview';
  el('interactivePanel').insertBefore(box,el('interactiveChart'));
  add(box,'strong',`Luna 图审 · ${label} · ${row.symbol}`);
  if(verified){
    add(box,'p',review.reason||'原因未提供');
    const details=add(box,'details');add(details,'summary','查看图面依据与反证');
    for(const [heading,values] of [['图面依据',review.visible_evidence],['反证',review.counter_evidence]]){
      add(details,'strong',heading);const list=add(details,'ul');
      const entries=Array.isArray(values)?values.filter(value=>typeof value==='string'&&value.trim()):[];
      if(entries.length)for(const value of entries)add(list,'li',value);else add(list,'li','未提供');
    }
  }else add(box,'p',label==='未审'?'该股尚无已核验的图审记录。':'图审记录未通过核验，结论待确认。');
  const note=document.querySelector('#interactiveChart > p.field-note'),before=note?.textContent;
  if(note)note.textContent=before.replace('图审仍待完成。',`本股图审：${label}。`);
  skillReviewCleanup=()=>{box.remove();if(note)note.textContent=before};
}
async function openSkill(day,row,selectedGroup){
  showSkillReview(row);
  const ref=row.r2_chart;if(!ref||row.r2_chart_status!=='READY')throw Error('R2_ORIGINAL_CHART_NOT_MATERIALIZED');
  const own=Object.entries(row.group_states).filter(([,v])=>v==='TRUE').map(([g])=>g),group=own.includes(selectedGroup)?selectedGroup:own[0];
  context={source_date:day.source_date,observation_date:day.observation_date,symbol:row.symbol,generation:day.generation,input_sha256:day.input_sha256,group,horizon:'d2'};
  const mine=++r2Serial;r2Controller?.abort();r2Controller=new AbortController();const signal=r2Controller.signal;
  const html=new URL(ref.html_url,location.href),expected=`/api/v4/research/workbench/days/${day.source_date}/skill-r2/assets/${row.symbol}/html`;
  if(html.origin!==location.origin||html.pathname!==expected||html.searchParams.get('revision')!==day.generation||html.searchParams.get('sha256')!==ref.html_sha256)throw Error('R2_HTML_IDENTITY_CONFLICT');
  setCompanyContext(context);sourceContext(day);
  const projection=await loadSkillProjection(ref.projection,{...context,selector_sha256:day.source_selector_sha256},{adaptProjection,origin:location.origin,signal});
  if(mine!==r2Serial||signal.aborted)throw Error('STALE_STOCK_CONTEXT');
  current={r2:true,context,projection,numeric_manifest:day.numeric_manifest};
  stat.replaceChildren();add(stat,'h3','技能R2 · 同定义历史统计');add(stat,'p','CANNOT_CONFIRM：尚无同定义历史事件，未计算新规则成功率。');
  frame.hidden=false;frame.src=html.href;
  el('fullCoverage').textContent=`${projection.data.rows.length}行原式51变量/22绘图 · 来源日${day.source_date} · 技能R2标签与图内原式标签分开`;
  return current;
}
function sourceContext(day,force=false){
  if(!force&&contextReply?.source_date===day.source_date&&contextReply?.observation_date===day.observation_date&&contextReply?.generation===day.generation&&contextReply?.input_sha256===day.input_sha256){paintContext();return;}
  const mine=++contextSerial;
  const sameIdentity=(a,b)=>a&&b&&['source_date','observation_date','generation','input_sha256'].every(k=>a[k]===b[k]);
  const isCurrent=()=>mine===contextSerial&&sameIdentity(activeDay||context,day);
  const unknown=reason=>({status:'UNKNOWN',summary:reason+' · CANNOT_CONFIRM'});
  contextReply={source_date:day.source_date,observation_date:day.observation_date,generation:day.generation,input_sha256:day.input_sha256,markets:{US:unknownUsContext('正在读取已保存来源'),JP:unknown('日本当日来源未绑定'),KR:unknown('韩国当日基准/来源待核')}};paintContext();
  let usView=null;
  const read=url=>fetch(url,{method:'GET',credentials:'same-origin',redirect:'error',cache:'no-store'}).then(r=>{if(!r.ok)throw Error('CONTEXT_READ_HTTP_'+r.status);return r.json()});
  const base=read('/api/v4/research/workbench/days/'+day.source_date+'/context?'+new URLSearchParams({revision:day.generation})).then(value=>{if(!isCurrent())return;if(!sameIdentity(value,day))throw Error('SOURCE_CONTEXT_IDENTITY_CONFLICT');contextReply={...value,markets:{...value.markets,US:usView??contextReply.markets.US}};paintContext();}).catch(error=>{if(!isCurrent())return;contextReply.markets.JP=unknown('日本当日来源读取失败：'+error.message);contextReply.markets.KR=unknown('韩国当日基准/来源读取失败：'+error.message);paintContext();});
  const us=read('/api/v4/research/us-market?'+new URLSearchParams({research_date:day.observation_date.replaceAll('-','')})).then(value=>{if(!isCurrent())return;usView=usMarketContext(value,day);contextReply.markets.US=usView;paintContext();}).catch(error=>{if(!isCurrent())return;usView=unknownUsContext(error.message);contextReply.markets.US=usView;paintContext();});
  return Promise.allSettled([base,us]);
}
function paintContext(snapshot){
  const identity=activeDay||context;if(!contextReply||!identity||contextReply.source_date!==identity.source_date||contextReply.observation_date!==identity.observation_date||contextReply.generation!==identity.generation||contextReply.input_sha256!==identity.input_sha256)return;const host=el('marketCards');host.replaceChildren();
  if(snapshot!==undefined){try{marketObservation=observationMarketContext(snapshot,identity);}catch{marketObservation=null;}}
  const bound=marketObservation&&['source_date','observation_date','generation','input_sha256'].every(key=>marketObservation.identity[key]===identity[key]);
  for(const [market,originalValue]of Object.entries(contextReply.markets)){
    let value=originalValue;
    if(bound&&market==='JP'&&marketObservation.japan)value=marketObservation.japan;
    if(bound&&market==='US'&&marketObservation.benchmarks){const bench=marketObservation.benchmarks,base=marketObservation.usMarket??originalValue,session=base.native?.rows?.[0]?.session_date;value={...base,benchmarks:session&&bench.us_session_date!==session?null:bench};}
    renderMarketCard(host,market,value,identity,document);
  }
}
function showStatistics(bundle){
  stat.replaceChildren();add(stat,'h3',({original:'原公式',nav_smallk:'小K',nav_pullback:'回踩',nav_breakout:'突破'})[bundle.context.group]+' · 同买点历史统计');
  const coverage=bundle.detail.row.historical_coverage||{};
  add(stat,'p',`已发布历史覆盖 ${coverage.evaluated_count??'未知'}/${coverage.available_prefix_dates??'未知'} 日期；不是有效事件样本数。`);
  if(bundle.detail.history_sync?.status==='IN_PROGRESS'){add(stat,'p','历史统计补齐中；真实完成后自动更新。');return;}
  const group=bundle.detail.row.statistics?.groups?.find(g=>g.group_id===bundle.context.group);
  const grid=add(stat,'div');grid.className='summary-grid';
  for(const key of ['d2','d5']){const v=group?.horizons?.[key],card=add(grid,'div');card.className='panel';add(card,'strong',key==='d2'?'D+2':'D+5');add(card,'p',v?.valid>0&&Number.isFinite(v.positive_fraction)?(v.positive_fraction*100).toFixed(2)+'%':'样本不足');add(card,'p',`总事件 ${v?.total??'未知'} · 有效 ${v?.valid??'未知'} · 未成熟 ${v?.not_matured??'未知'}`);const line=add(card,'p','同分位统计读取中…');
    const apply=a=>{if(current!==bundle||!context)return;if(a.status!=='READY'||a.symbol!==context.symbol||a.group!==context.group||a.horizon!==key||a.data_date!==context.source_date.replaceAll('-','')||a.source_generation!==context.generation||a.source_identity?.input_sha256!==context.input_sha256||a.numeric_manifest?.sha256!==bundle.numeric_manifest.sha256||a.numeric_manifest?.path!==bundle.numeric_manifest.path){line.textContent='同分位统计身份待核';return;}const details=add(card,'details'),summary=add(details,'summary','查看历史事件及图上位置');let shown=0;const list=add(details,'div'),more=add(details,'button','再显示20条');more.type='button';const cases=a.cases??[];const paint=()=>{for(const item of cases.slice(shown,shown+20)){const b=add(list,'button',`${item.event_date} → ${item.target_date??'未成熟'} · ${item.return_pct==null?item.status:item.return_pct.toFixed(2)+'%'} · 分位 ${item.percentile_bucket??'未知'}`);b.type='button';b.style.display='block';b.onclick=()=>{if(current!==bundle)return;const w=frame.contentWindow,s=w?.RESEARCH_PANEL_STATE,i=s?.rows?.findIndex(r=>String(r.trade_date)===item.event_date.replaceAll('-',''));if(!s||i<0){summary.textContent='原图无该事件日期，不就近替代';return;}w.setOriginalWindow(Math.min(120,s.rows.length),Math.min(s.rows.length,i+84));w.choose(i);w.paint();};}shown+=20;more.hidden=shown>=cases.length;};more.onclick=paint;paint();const c=a.conditional;line.textContent=c?`同分位 ${c.bucket_label}：${c.valid>0&&Number.isFinite(c.positive_fraction)?(c.positive_fraction*100).toFixed(2)+'%':'样本不足'} · 有效 ${c.valid} · 未成熟 ${c.not_matured}`:'同分位字段未物化';};
    if(bundle.eventCases.horizon===key)apply(bundle.eventCases);else fetch('/api/v4/research/a-share/event-cases?'+new URLSearchParams({date:context.source_date.replaceAll('-',''),symbol:context.symbol,group:context.group,horizon:key}),{method:'GET',credentials:'same-origin',redirect:'error',cache:'no-store'}).then(r=>r.json()).then(apply).catch(()=>{if(current===bundle)line.textContent='同分位统计读取未确认'});
  }
  add(stat,'small','非历史PIT认证；仅描述已接受事件，不预测未来。');
}
function paintCompanyReports(value,target=el('companyEvidence')){
  if(!renderReceivedResearch(value,document))renderMaterialTiming(value,el('companySummary'),document);
  const box=add(target,'details');add(box,'summary','研报来源与缺口');
  if(!value.reports?.catalog?.length)add(box,'p','研报元数据未接入 · CANNOT_CONFIRM');
  for(const report of value.reports?.catalog??[]){const row=add(box,'p');add(row,'span',`${report.published_at??'日期未知'} · ${report.institution??''} · ${report.title??'标题缺失'} · ${report.full_text_status??report.evidence_status??'全文状态未知'} `);try{const url=new URL(report.report_url||report.metadata_source_url);if(url.protocol==='https:'&&!url.username&&!url.password){const a=add(row,'a',report.report_url?'原始报告入口':'元数据来源');a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';}}catch{add(row,'small','来源链接未接入');}if(report.summary)add(box,'p',report.summary);}
  add(box,'p',value.reports?.stored_report?'有已存研报引用；文件可读性与事实验收需另核。':'未绑定已存研报；不把元数据当全文。');
}
function loadSingleDetails(day,meta,signal,assets){
  if(signal.aborted)return;
  const history=el('kbSingleHistory'),company=el('kbSingleCompany'),finance=el('kbSingleFinancial');
  history.replaceChildren();company.replaceChildren();finance.replaceChildren();
  const groups=visibleSingleHistoryGroups(assets.history.statistics?.groups);
  if(!Array.isArray(groups)||!groups.length)throw Error('单股历史统计缺失');
  add(history,'p',`截至 ${day.source_date} · 已存${meta.rows}日标签；按深市交易日计算。原式一级/二级买点与KB各自统计，历史PIT未认证，不预测未来。`);
  const text=v=>v?.valid>0&&Number.isFinite(v.positive_fraction)?`${v.positive}/${v.valid}（${(v.positive_fraction*100).toFixed(1)}%）`:`有效 ${v?.valid??0}，样本不足`;
  for(const group of groups){
    const h=group.horizons,p=group.same_position?.horizons;
    if(!h||!p||group.identity_status!=='BOUND')throw Error('单股历史统计身份未绑定');
    add(history,'p',`${group.coverage.label} · 命中 ${group.eligible_event_count} · D+2 正收益 ${text(h.d2)}，D+5 ${text(h.d5)} · 同位置 D+2 ${text(p.d2.conditional)}，D+5 ${text(p.d5.conditional)} · 未成熟 ${h.d2.not_matured}/${h.d5.not_matured} · 未知标签 ${group.coverage.unknown_dates}`);
  }
  const position=groups[0].same_position;
  add(history,'p',`同位置：以${day.source_date}的过去250个有效收盘价分位 ${position.current_price_percentile==null?'待核':(position.current_price_percentile*100).toFixed(1)+'%'} 所在20%区间比较；未成熟和缺失价格不计入有效分母。`);
  const cases=add(history,'details');add(cases,'summary','查看同股历史事件并定位图表');const groupChoice=add(cases,'select');groupChoice.setAttribute('aria-label','选择历史信号');
  for(const group of groups){const option=add(groupChoice,'option',group.coverage.label);option.value=group.group_id}
  const list=add(cases,'div');let shown=0;const more=add(cases,'button','再显示20条');more.type='button';
  function appendCases(reset=false){if(reset){shown=0;list.replaceChildren()}const g=groups.find(x=>x.group_id===groupChoice.value);const rows=g.horizons.d2.cases;for(const item of rows.slice(shown,shown+20)){const b=add(list,'button',`${item.event_date} → ${item.target_date??'未成熟'} · ${item.return_pct==null?item.status:item.return_pct.toFixed(2)+'%'}`);b.type='button';b.style.display='block';b.onclick=()=>{el('kbSingleDate').value=item.event_date;el('kbSingleDate').dispatchEvent(new Event('change'))}}shown+=20;more.hidden=shown>=rows.length}
  groupChoice.onchange=()=>appendCases(true);more.onclick=()=>appendCases();appendCases(true);
  const m=assets.company,b=m.business_reported??{},f=m.financials_reported??{},holders=m.shareholders_reported??{};
  add(company,'p',b.value??'主营资料待核');if(b.source_url){const source=add(company,'a','官方三季报原件');source.href=b.source_url;source.target='_blank';source.rel='noopener noreferrer';}
  add(finance,'p',financialDisclosureText(f,m.f10,m.source_refs));
  const financeLines=[add(finance,'p'),add(finance,'p'),add(finance,'p')];
  add(finance,'p',`${holders.holder_asof?'报告期末股东':'股东户数'} ${holders.holder_count??'待核'} 户（${holders.holder_asof??'统计截止日待核'}）${holders.note?'；'+holders.note:''}`);
  const f10Box=add(company,'div');
  const paintF10=(f10,source)=>{f10Box.replaceChildren();financialLines(f,f10).forEach((text,i)=>{financeLines[i].textContent=text});if(!f10)return;
    add(f10Box,'p',`TDX F10 概念（采集时快照）：${f10.concepts?.map(c=>c.name).join('、')||'待核'}`);
    const provenance=add(f10Box,'p',`${source} · 实际采集 ${f10.captured_at??'时间待核'}，来源更新 ${f10.source_updated_date??'待核'}；概念不回填历史。`);
    provenance.title=`TDX行业源代码 ${f10.industry?.tdx_finance_industry_code??'未知'}；映射状态 ${f10.industry?.status??'未知'}`;
  };
  paintF10(m.f10,'单股已绑定快照');
  fetch('/api/v4/research/workbench/days/'+day.source_date+'/f10/'+meta.symbol+'?'+new URLSearchParams({revision:day.generation}),{signal,credentials:'same-origin',redirect:'error',cache:'no-store'})
    .then(response=>response.ok?response.json():null).then(value=>{if(!signal.aborted&&value?.status==='OBSERVED'&&value.symbol===meta.symbol&&value.source_generation===day.generation&&value.input_sha256===day.input_sha256&&value.stock_ref?.sha256===meta.display_projection?.f10_source_sha256)paintF10(value.f10,'日更完成快照')}).catch(()=>{});
  const reports=el('relatedReports');reports.hidden=true;reports.dataset.identityDate=day.source_date.replaceAll('-','');reports.dataset.generation=day.generation;
  window.RelatedReports?.select(meta.symbol,meta.name,true,null);
}

function cancelOriginalReady(){originalReadyObserver?.disconnect();originalReadyObserver=null;}
function whenOriginalReady(callback){
  cancelOriginalReady();if(!current||frame.hidden)return;
  const bound=current,w=frame.contentWindow,child=frame.contentDocument;
  if(!w||!child?.documentElement)return;
  const observer=new MutationObserver(()=>ready());
  const ready=()=>{
    if(current!==bound||frame.hidden||frame.contentDocument!==child){observer.disconnect();if(originalReadyObserver===observer)originalReadyObserver=null;return;}
    const state=w.RESEARCH_PANEL_STATE;
    if(child.documentElement.dataset.loaded!==bound.context.symbol||state?.symbol!==bound.context.symbol||!state.view||state.rows?.length!==bound.projection.data.rows.length||!state.rows.length)return;
    observer.disconnect();if(originalReadyObserver===observer)originalReadyObserver=null;
    callback(w,child);
  };
  originalReadyObserver=observer;observer.observe(child.documentElement,{attributes:true,attributeFilter:['data-loaded']});ready();
}
frame.addEventListener('load',()=>whenOriginalReady((w,child)=>{if(!child.getElementById('mac-original-focus-style')){const style=child.createElement('style');style.id='mac-original-focus-style';style.textContent='body{margin:0!important;background:#07131e!important}header,aside,.toolbar,.charthead .controls,#selected-date,.stats,.tables,details,#status,.foot,#chart-caption{display:none!important}main{display:block!important;max-width:none!important;margin:0!important;min-height:0!important}article{padding:12px!important}.chartbox{border:0!important;padding:0!important}.charthead{margin:0 0 4px!important}canvas{height:405px!important}';child.head.appendChild(style);w.dispatchEvent(new w.Event('resize'));w.paint();}if(preservedChart&&preservedChart.symbol===current.context.symbol&&preservedChart.source_date===current.context.source_date&&preservedChart.generation===current.context.generation){w.setOriginalWindow(preservedChart.count,preservedChart.start+preservedChart.count);w.choose(preservedChart.selected);w.paint();preservedChart=null;}const select=el('fullDateSelect');select.replaceChildren();for(const r of current.projection.data.rows){const option=add(select,'option',String(r.trade_date));option.value=String(r.trade_date)}select.value=String(current.projection.data.rows.at(-1).trade_date);select.onchange=()=>{const s=w.RESEARCH_PANEL_STATE,i=s.rows.findIndex(r=>String(r.trade_date)===select.value);if(i<0)return;w.setOriginalWindow(Math.min(120,s.rows.length),Math.min(s.rows.length,i+84));w.choose(i);w.paint()};}));
window.StockPanelHost={
  clearCompany(){singleResearch.clear();setCompanyContext(null);renderCompanyStatus(document,'IDLE');},
  async open(day,row,selectedGroup){
    if(day.ruleset_id==='ZGE_SKILL_DAILY_CANDIDATES_R2')return openSkill(day,row,selectedGroup);
    const own=Object.entries(row.group_states).filter(([,v])=>v==='TRUE').map(([g])=>g);
    const group=row.v192_assets?'v192':own.includes(selectedGroup)?selectedGroup:own[0];
    context={source_date:day.source_date,observation_date:day.observation_date,symbol:row.symbol,generation:day.generation,input_sha256:day.input_sha256,numeric_manifest:day.numeric_manifest,group,horizon:'d2'};
    setCompanyContext(context);sourceContext(day);if(day.source_date!=='2026-10-30')singleResearch.openSymbol(row.symbol,row.name);
    if(row.v192_member&&row.original_chart_status!=='MATERIALIZED'){
      stat.replaceChildren();add(stat,'h3','v1.9.2候选');add(stat,'p','同日原式图未物化 · 同定义D+2/D+5统计未接入。');
      return {status:'NOT_MATERIALIZED',reason:'同日原式图未物化',context};
    }
    let coverage=el('macScopeCoverage');if(!coverage){coverage=document.createElement('p');coverage.id='macScopeCoverage';coverage.className='counts';document.querySelector('.source-note').append(coverage);}coverage.textContent=`当前已交付候选 ${day.scope_count} 条；原处理 ${day.original_processed_count} 条，未交付台账行不在本页展示。`;
    const bundle=await bridge.open(context,{render:true,...(row.v192_assets?{v192:row.v192_assets}:{})});current=bundle;context=bundle.context;el('fullCoverage').textContent=`${bundle.projection.data.rows.length}行原式51变量/22绘图 · 来源日${context.source_date} · 统计manifest ${bundle.numeric_manifest.sha256.slice(0,12)}`;if(selectedGroup==='v192'){stat.replaceChildren();add(stat,'h3','v1.9.2候选 · 历史统计');add(stat,'p','同定义D+2/D+5统计未接入；原四组统计请切回对应组查看。')}else showStatistics(bundle);return bundle;
  },
  async paintTop200(){
    const bound=activeDay,mine=moduleSerial;if(!bound)return;
    let box=el('macTop200');if(!box){box=document.createElement('details');box.id='macTop200';box.className='evidence-panel';document.querySelector('.source-note').after(box);}
    box.replaceChildren();add(box,'summary','收盘 Top200 · 行业 / 结构分组');
    try{
      const response=await fetch('/api/v4/research/workbench/days/'+bound.source_date+'/top200');
      const value=await response.json();if(mine!==moduleSerial||activeDay!==bound)return;
      if(!response.ok)throw Error('读取失败');
      if(!Array.isArray(value.top200)||!value.top200.length){add(box,'p','本日 Top200 尚未物化 · CANNOT_CONFIRM');return;}
      add(box,'p',`源日 ${bound.source_date} · 目录 ${value.directory_count} · 正价记录 ${value.positive_price_record_count??value.valid_quote_count} · 当日可排名 ${value.valid_daily_gain_rank_record_count??'待确认'} · 无成交或无有效bar ${value.excluded_nontrading_or_invalid_bar_count??'未知'} · 缺报价 ${value.missing_quote_count} · Top200 ${value.top200_count}。数值结构描述；逐股图审未完成。`);
      for(const [key,title]of [['previous_session','前一交易日冻结候选覆盖'],['same_day','同日事后对照']]){const c=value.comparison?.[key];if(c)add(box,'p',`${title} · ${c.source_date} · ${c.hits??'待核'}/${c.candidate_count??'待核'}候选，Top榜 ${c.hits??'待核'}/${c.top_count}。事前可得性待证；图审名单未完成。`);}
      for(const [axis,title] of [['industry','行业'],['structure','结构'],['theme','题材（多标签）']]){const group=add(box,'details');add(group,'summary',title);for(const row of value.statistics?.[axis]??[])add(group,'p',`${row.label} · Top200 ${row.top200_count} · 同范围可计算 ${row.members_with_valid_quote}`);}
      const all=add(box,'details');add(all,'summary',`查看 ${value.top200.length} 只描述性名单`);
      for(const row of value.top200){const button=add(all,'button',`${row.rank} · ${row.symbol} ${row.name??''} · ${Number(row.change_pct).toFixed(2)}% · ${row.official_major??'行业待核'} · ${row.structure??'结构待核'}`);button.type='button';button.style.display='block';button.onclick=()=>singleResearch.openSymbol(row.symbol,row.name)}
    }catch(error){if(mine===moduleSerial&&activeDay===bound)add(box,'p','本日 Top200 待确认：'+error.message);}
  },
  paintContext,
  paintClassificationCoverage(day){let line=el('macClassificationCoverage');if(!line){line=document.createElement('p');line.id='macClassificationCoverage';line.className='counts';document.querySelector('.source-note').append(line);}const counts=day.classification_identity_counts??{};line.textContent='分类代码+名称 '+(counts.BOUND_EXACT_CODE_NAME??0)+'/'+day.scope_count+' · 冲突 '+(counts.IDENTITY_CONFLICT_NAME??0)+' · '+day.classification_status;},
  paintClassification(row,day){renderClassification(el('classificationSummary'),row,day)},
  paintCompanyReports,
  paintWorkflow(contract){
    const labels={DEFERRED_USER:'用户后置',COMPLETED:'已完成（见回执）',PARTIAL:'部分交付',BLOCKED:'上游阻塞',MISSED:'漏过原时点',NOT_DUE:'未来节点',CANNOT_CONFIRM_NO_RECEIPT:'执行回执缺失',CANNOT_CONFIRM_BAD_RECEIPT:'回执校验失败'};
    for(const item of contract?.time_contract?.nodes??[]){const d=document.querySelector(`.timetable-item[data-node-id="${item.id}"]`);if(!d)continue;const host=d.querySelector('.node-materials');if(!host)continue;host.replaceChildren();add(host,'strong',labels[item.execution_status]??item.execution_status);if(item.recorded_at)add(host,'p','实际记录 '+item.recorded_at);if(item.source_asof)add(host,'p','来源时点 '+item.source_asof);for(const reason of item.missing??[])add(host,'p','缺口：'+reason);if(item.error)add(host,'p','错误：'+item.error);for(const material of item.materials??[]){try{const u=new URL(material.url,location.href);if(!['https:','http:'].includes(u.protocol)||u.username||u.password)continue;const a=add(host,'a',material.label??'来源材料');a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';}catch{add(host,'p','材料链接待核');}}}
  },
  preserveChart(){const s=frame.contentWindow?.RESEARCH_PANEL_STATE;if(context&&s?.view)preservedChart={symbol:context.symbol,source_date:context.source_date,generation:context.generation,...s.view,selected:s.selected};},
  unbindDay(){singleResearch.unbindDay();this.clearCompany();moduleEvents?.close();moduleEvents=null;++moduleSerial;activeDay=null;el('macTop200')?.replaceChildren();contextReply=null;marketObservation=null;++contextSerial;el('marketCards').textContent='跨市场来源尚未与所选日期绑定';},
  bindDay(day){
    activeDay=day;singleResearch.bindDay(day);this.paintClassificationCoverage(day);sourceContext(day,true);
    const key=day.source_date;if(moduleEvents?.key===key)return;
    moduleEvents?.close();const mine=++moduleSerial;let previous=null;this.paintTop200();
    moduleEvents=new EventSource('/api/v4/research/workbench/days/'+key+'/events');moduleEvents.key=key;
    moduleEvents.addEventListener('workbench_completed',event=>{try{const e=JSON.parse(event.data);if(mine!==moduleSerial||activeDay?.source_date!==key||e.source_date!==key||e.RESEARCH_ONLY!==true||['production_allowed','buy_gate_updated','orders_sent'].some(k=>e[k]!==false))return;
      const changed=Object.keys(e.modules??{}).filter(k=>previous?.[k]!==e.modules[k]);previous=e.modules;
      // Event payloads are invalidation hints. Only fresh GET responses may
      // replace content, so a delayed/replayed event cannot restore old data.
      if(changed.includes('context')||changed.includes('observations'))sourceContext(activeDay,true);
      completionCallback?.modules?.(changed,e);
      if(changed.includes('score_action'))singleResearch.refresh();
      if(changed.includes('company'))refreshReceivedCompany({...e,data_date:e.source_date.replaceAll('-',''),source_generation:e.generation,company_materials:true});
    }catch{}});
  },
  installCompletion(callback){completionCallback=callback},
  refreshSavedSources(){
    if(document.hidden||foregroundRead)return foregroundRead;
    const before=activeDay;
    foregroundRead=Promise.resolve(completionCallback?.catalog?.()).then(async()=>{if(activeDay&&activeDay===before){await completionCallback?.modules?.(['observations']);if(activeDay===before)return sourceContext(activeDay,true);}}).finally(()=>{foregroundRead=null;});
    return foregroundRead;
  },
};
window.addEventListener('focus',()=>window.StockPanelHost.refreshSavedSources());
document.addEventListener('visibilitychange',()=>{if(!document.hidden)window.StockPanelHost.refreshSavedSources();});
const events=new EventSource('/api/v4/research/events');
const refreshReceivedCompany=createReceivedCompanyRefresh({getContext:()=>context,begin:beginCompanyRequest,isCurrent:isCurrentCompanyRequest,validate:validateCompany,
  fetchCompany:async identity=>{const response=await fetch('/api/v4/research/workbench/days/'+identity.source_date+'/company/'+identity.symbol+'?'+new URLSearchParams({revision:identity.generation}),{credentials:'same-origin',redirect:'error',cache:'no-store'});if(!response.ok)throw Error('RECEIVED_COMPANY_REFRESH_FAILED');return response.json();},
  apply:value=>{renderCompanyStatus(document,'READY',value.symbol);el('companyEvidence').replaceChildren();paintCompanyReports(value);},
  onError:identity=>renderCompanyStatus(document,'ERROR',identity.symbol)});
events.addEventListener('a_share_daily_completed',event=>{try{const e=JSON.parse(event.data),action=completionAction(context,e);if((e.f10||e.score_action)&&activeDay&&e.data_date===activeDay.source_date.replaceAll('-','')&&e.source_generation===activeDay.generation&&e.input_sha256===activeDay.input_sha256)singleResearch.refresh();if(action==='catalog')completionCallback?.catalog?.();else if(action==='refresh'){completionCallback?.refresh?.();if(e.company_materials)refreshReceivedCompany(e);}else if(action==='source_changed'){window.OriginalFullChart.clear();completionCallback?.sourceChanged?.();}else if(action==='gap')el('projectionStatus').textContent='完成事件来源字段待核；当前已绑定版本未替换。';}catch{}});
window.addEventListener('pagehide',()=>{events.close();moduleEvents?.close();++moduleSerial;bridge.clear()},{once:true});
await import('./dot/shell/workbench.local.mjs');
