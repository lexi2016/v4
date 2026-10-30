"""Deterministic fixed-Dot copy and checked, local-only integration seams."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil

COMMIT='0ae4a66d90c12a0d0335b5f7f65b528879c5e9cf'
SOURCE=Path(__file__).resolve().parents[1]/'research/stock_panel_collab_20261030'
HOST_FILES=('bootstrap.mjs','company-local.mjs','completion-action.mjs','rate-sort.mjs','observation-local.mjs','entry-date.mjs','classification-local.mjs')
RUNTIME_ASSETS=('workbench.html',*(f'workbench-host/{p}' for p in HOST_FILES),'workbench-host/stock/stock-bridge.mjs','workbench-host/dot/shell/workbench.local.mjs','workbench-host/dot/shell/workbench.css','workbench-host/dot/shell/workbench-context.mjs','workbench-host/dot/shell/market-archive.mjs','workbench-host/dot/shell/workflow-materials.mjs','workbench-host/dot/src/observation-view.mjs','workbench-host/dot/src/projection-view.mjs','workbench-host/dot/src/model.mjs','workbench-host/dot/src/workbench-model.mjs','workbench-host/dot/src/workflow-time.mjs')


def replace_once(text,old,new):
    count=text.count(old)
    if count!=1:raise ValueError(f'WORKBENCH_ANCHOR_COUNT:{old[:80]}:{count}')
    return text.replace(old,new,1)


def replace_block(text,start,end,new):
    if text.count(start)!=1 or text.count(end)!=1:raise ValueError('WORKBENCH_BLOCK_ANCHOR_COUNT:'+start)
    left=text.index(start);right=text.index(end)
    if right<=left:raise ValueError('WORKBENCH_BLOCK_ANCHOR_ORDER:'+start)
    return text[:left]+new+text[right:]


CALLBACKS=r'''
let completionSerial=0;
window.StockPanelHost.installCompletion({
 refresh(){this.modules(['list','statistics']);},
 async modules(changed,event){
  if(!day)return;const mine=++completionSerial,wanted=selection().date,oldDay=day;
  try{
   if(event&&(event.generation!==day.generation||event.input_sha256!==day.input_sha256)){await this.sourceChanged();return;}
   if(changed.some(k=>['list','statistics'].includes(k))){
    const next=validateDay(await loadJson(endpoint('day')));
    if(mine!==completionSerial||selection().date!==wanted||day!==oldDay||next.source_date!==wanted)return;
    if(next.generation!==day.generation||next.input_sha256!==day.input_sha256){await this.sourceChanged();return;}
    const symbol=selected?.symbol;day=next;window.StockPanelHost.bindDay(day);renderFilters();renderSecondary();renderList(false);
    if(symbol&&selected?.symbol===symbol){selected=day.rows.find(r=>r.symbol===symbol)??selected;window.StockPanelHost.preserveChart();loadInteractive(selected,++stockToken);}
   }
   if(changed.includes('classification')&&!changed.some(k=>['list','statistics'].includes(k))){const next=validateDay(await loadJson(endpoint('day')));if(mine!==completionSerial||selection().date!==wanted||next.source_date!==wanted||next.generation!==day.generation||next.input_sha256!==day.input_sha256)return;const symbol=selected?.symbol;day=next;window.StockPanelHost.paintClassificationCoverage(day);renderList(false);if(symbol&&selected?.symbol===symbol){selected=day.rows.find(r=>r.symbol===symbol)??selected;renderClassification(selected);}}
   if(changed.includes('observations'))await refreshObservationData();
   if(mine!==completionSerial||selection().date!==wanted)return;
   if(changed.includes('workflow')){const contract=await loadJson(integrationBase+'/workflow-contract?source_date='+wanted);if(mine!==completionSerial||selection().date!==wanted)return;timeContract=contract;renderContext(timeContract,observationSnapshot);window.StockPanelHost.paintWorkflow(contract);}
   window.StockPanelHost.paintContext();
  }catch(error){if(mine===completionSerial)$('loadingState').textContent='已保存更新尚未确认：'+error.message;}
 },
 async sourceChanged(){
  window.StockPanelHost.clearCompany();
  const wanted=selection().date,mine=++completionSerial;
  try{const catalog=await loadJson(integrationBase+'/history');if(mine!==completionSerial||selection().date!==wanted)return;const entry=catalog.days.find(d=>d.source_date===wanted),option=Array.from($('date').options).find(o=>o.value.split('|')[0]===wanted);if(!entry||!option)throw Error('SOURCE_DATE_MISSING');option.value=wanted+'|'+entry.revision;$('date').value=option.value;await loadDay();}catch(error){if(mine===completionSerial)$('loadingState').textContent='来源重新绑定未确认：'+error.message;}
 }
});
const originalRefresh=refreshObservationData;refreshObservationData=async(...args)=>{const answer=await originalRefresh(...args);window.StockPanelHost.paintContext();window.StockPanelHost.paintWorkflow(timeContract);return answer};
'''


def build(dot_root,output,receipt):
    entries=json.loads(receipt.read_text())['entries']
    if len(entries)!=46 or len({e['path'] for e in entries})!=46:raise ValueError('EXACT46_FIXED_FILES_REQUIRED')
    for entry in entries:
        relative=Path(entry['path']).relative_to('research/dashboard_framework_collab_20261030');p=dot_root/relative
        if p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('DOT_SOURCE_DRIFT:'+str(relative))
    original=(dot_root/'shell/workbench.mjs').read_text();patched=original
    patched=replace_once(patched,"from './company.mjs'","from '../../company-local.mjs'")
    patched=replace_once(patched,"from '../src/observation-view.mjs'","from '../../observation-local.mjs'")
    patched=replace_once(patched,"renderContext,renderPhase,observationHeader}","renderContext as originalRenderContext,renderPhase as originalRenderPhase,observationHeader as originalObservationHeader}")
    patched="const archiveMini=s=>{if(s?.capture_kind==='OFFICIAL_DAILY_ARCHIVE')document.getElementById('observationMini').textContent=`官方日包收盘归档 · 源日${s.observation_date} · 数值${s.rows.filter(r=>r.status==='DATED_DAILY_ARCHIVE').length}/${s.rows.length} · 精确源时刻未知`};const renderPhase=(...args)=>{originalRenderPhase(...args);archiveMini(args[1])};const renderContext=(...args)=>{originalRenderContext(...args);archiveMini(args[1])};\n"+patched
    patched="const observationHeader=(snapshot,now)=>snapshot?.capture_kind==='OFFICIAL_DAILY_ARCHIVE'?`官方日包收盘归档 · 源日 ${snapshot.observation_date} · 源精确时刻 UNKNOWN · 保存 ${snapshot.recorded_at} · 数值覆盖 ${snapshot.rows.filter(r=>r.status==='DATED_DAILY_ARCHIVE').length}/${snapshot.rows.length}`:originalObservationHeader(snapshot,now);\n"+patched
    patched="import {sortHistoryRates,rateLabel,historyRate} from '../../rate-sort.mjs';\nimport {requestedSourceDate} from '../../entry-date.mjs';\nimport {matchesClassification} from '../../classification-local.mjs';\n"+patched
    patched=replace_block(patched,'async function loadInteractive(','\nconst compactChart=',r'''async function loadInteractive(r,token){clearInteractive();$('interactivePanel').hidden=false;$('projectionStatus').textContent='正在读取同源原图及历史统计…';try{const bundle=await window.StockPanelHost.open(day,r,group);if(token!==stockToken)return;interactiveLoaded=bundle.projection;$('interactiveChart').hidden=false;$('projectionStatus').textContent=`${bundle.projection.data.rows.length}根原式历史 · 已物化统计 · 图审待完成`;}catch(error){if(token!==stockToken)return;clearInteractive();$('projectionStatus').textContent='本股来源或统计暂未闭环：'+error.message;}}''')
    patched=replace_once(patched,"filtered=sortStocks(filtered,{", "filtered=filtered.filter(r=>matchesClassification(r,{query:$('classificationQuery').value,labels:Array.from(document.querySelectorAll('[data-classification-label]:checked')).map(n=>n.value)}));filtered=sortStocks(filtered,{")
    patched=replace_block(patched,'function renderClassification(r){','\nfunction pollStoredObservations()',"function renderClassification(r){window.StockPanelHost.paintClassification(r,day);}")
    patched=replace_once(patched,"filtered=sortStocks(filtered,{snapshot:observationSnapshot,mode:$('stockSort').value,names});","filtered=/^d[25]_/.test($('stockSort').value)?sortHistoryRates(filtered,group,$('stockSort').value):sortStocks(filtered,{snapshot:observationSnapshot,mode:$('stockSort').value,names});")
    patched=replace_once(patched,'b.append(identity,price,change,amount);',r'''b.append(identity,price,change,amount);for(const h of ['d2','d5']){const rate=node('span',rateLabel(r,group,h)),value=historyRate(r,group,h);rate.className='grid-rate';if(!['nav_smallk','original','nav_pullback','nav_breakout'].includes(group)){const own=node('small',({nav_smallk:'小K',original:'原式',nav_pullback:'回踩',nav_breakout:'突破'})[value.group]??'无命中组');own.style.display='block';rate.append(own);}rate.title=`${value.group??'无命中组'} · ${h} · 正收益/已成熟有效次数；未成熟 ${value.not_matured??'未知'}`;b.append(rate);}''')
    patched=replace_once(patched,"amount:'成交额'})[key]","amount:'成交额',d2:'D+2',d5:'D+5'})[key]")
    patched=replace_once(patched,"if(x.independent_field_audit)$('companyEvidence').append", "window.StockPanelHost.paintCompanyReports(x);if(x.independent_field_audit)$('companyEvidence').append")
    patched=replace_once(patched,"全范围台账 · ${day.rows.length}只","已接入台账（仅冻结候选）· ${day.rows.length}只")
    patched=replace_once(patched,"async function loadDay(){observationLoading=false;", "async function loadDay(){window.StockPanelHost.unbindDay();observationLoading=false;")
    patched=replace_once(patched,"names={};renderContext(timeContract,null);", "names={};timeContract=null;renderContext(null,null);$('macLegacyStockPage').href='legacy-daily.html?'+new URLSearchParams({date:selection().date});")
    patched=replace_once(patched,"该日期尚无研究数据，不沿用旧池。", "${selection().date} 未物化 · CANNOT_CONFIRM；没有沿用其他日期。")
    patched=replace_once(patched,"$('loadingState').textContent='${selection().date} 未物化 · CANNOT_CONFIRM；没有沿用其他日期。'", "$('loadingState').textContent=`${selection().date} 未物化 · CANNOT_CONFIRM；没有沿用其他日期。`")
    patched=replace_once(patched,"const h=await loadJson(endpoint('history'));if(!h?.days?.length){$('loadingState').textContent='尚无已提交研究日期。';return}", "let requested;try{requested=requestedSourceDate(location.search)}catch(error){$('loadingState').textContent='请求日期无效 · CANNOT_CONFIRM；未自动选择其他日期。';return;}const h=await loadJson(endpoint('history'))??{days:[]};if(!Array.isArray(h.days))throw Error('INVALID_HISTORY_CATALOG');if(!h.days.length&&!requested){$('loadingState').textContent='尚无已提交研究日期 · CANNOT_CONFIRM。';return}")
    patched=replace_once(patched,"$('date').append(o)}await loadDay()", "$('date').append(o)}if(requested){let option=Array.from($('date').options).find(o=>o.value.split('|')[0]===requested);if(!option){option=node('option',requested+' · 未物化 / CANNOT_CONFIRM');option.value=requested;$('date').prepend(option);}$('date').value=option.value;}await loadDay()")
    patched=replace_once(patched,"if(token!==loadToken)return;group='all';page=0;","if(token!==loadToken)return;try{timeContract=await loadJson(integrationBase+'/workflow-contract?source_date='+day.source_date)}catch{timeContract=null}if(token!==loadToken)return;renderContext(timeContract,null);group='all';page=0;")
    patched=replace_once(patched,"renderFilters();renderSecondary();renderList(true);await refreshObservationData()","window.StockPanelHost.bindDay(day);renderFilters();renderSecondary();renderList(true);await refreshObservationData();window.StockPanelHost.paintWorkflow(timeContract)")
    # The existing source timer repeatedly reads the same snapshot. Completion
    # events now invalidate specific saved modules; the clock-only UI stays.
    patched=replace_block(patched,'function pollStoredObservations()',"setInterval(pollStoredObservations,60000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)pollStoredObservations();});",'')
    patched=replace_once(patched,"setInterval(pollStoredObservations,60000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)pollStoredObservations();});",'')
    patched+='\n'+CALLBACKS
    patched+="\n$('classificationQuery').addEventListener('input',()=>{page=0;renderList(true)});for(const checkbox of document.querySelectorAll('[data-classification-label]'))checkbox.addEventListener('change',()=>{page=0;renderList(true)});const stockGridViewport=$('stockGridViewport');$('showStockNames').onclick=()=>stockGridViewport.scrollTo({left:0,behavior:'smooth'});$('showStockRates').onclick=()=>stockGridViewport.scrollTo({left:stockGridViewport.scrollWidth,behavior:'smooth'});\n"
    # Keep the fixed vendor untouched; change only its existing list seams.
    patched=replace_once(patched,"b.classList.toggle('active',key===group);b.onclick", "b.classList.toggle('active',key===group);b.setAttribute('aria-pressed',String(key===group));b.type='button';b.onclick")
    patched=replace_once(patched,"page=Math.min(page,Math.max(0,Math.ceil(filtered.length/pageSize)-1));", "page=Math.max(0,Math.min(page,Math.max(0,Math.ceil(filtered.length/pageSize)-1)));")
    patched=replace_once(patched,"$('listCount').textContent=`${filtered.length}只 · 原图${charts.size} · 真交互${projections.size} · 股价/金额为人民币`;$('listPage').textContent=`${page+1} / ${Math.max(1,Math.ceil(filtered.length/pageSize))}`;", "const totalCandidates=day.rows.filter(r=>r.eligible_candidate).length,scopeCount=$('scope').value==='all'?day.rows.length:totalCandidates,pageRows=filtered.slice(page*pageSize,(page+1)*pageSize);$('listCount').textContent=`总候选 ${totalCandidates}只 · 当前范围 ${scopeCount}只\\n筛选后 ${filtered.length}只 · 本页 ${pageRows.length}只${pageRows.length?'（'+(page*pageSize+1)+'–'+(page*pageSize+pageRows.length)+'）':''}`;$('listPage').textContent=`第 ${filtered.length?page+1:0} 页 / 共 ${Math.ceil(filtered.length/pageSize)} 页 · 每页 ${pageSize}只`;")
    patched=replace_once(patched,"else{$('content').hidden=true;$('loadingState').textContent='没有符合条件的股票。'}", "else{selected=null;++stockToken;clearInteractive();window.StockPanelHost.clearCompany();$('stockList').append(Object.assign(node('p','没有符合条件的股票，请调整上方范围、分组或搜索。'),{className:'stock-list-empty'}));$('content').hidden=true;$('loadingState').textContent='没有符合条件的股票，请调整上方筛选。'}")
    patched=replace_once(patched,'validateCompany,explanationFacts,independentTiming}', 'validateCompany,explanationFacts,independentTiming,beginCompanyRequest,isCurrentCompanyRequest,renderCompanyStatus}')
    start=patched.index('async function loadCompany(');end=patched.index('\nfunction renderSecondary()',start)
    company=patched[start:end]
    company=replace_once(company,"$('companySummary').replaceChildren(node('p','正在按需读取公司材料…'));$('companyMetrics').replaceChildren();$('companyEvidence').replaceChildren();", "const request=beginCompanyRequest({symbol:r.symbol,source_date:day.source_date,observation_date:day.observation_date,generation:day.generation,input_sha256:day.input_sha256});renderCompanyStatus(document,'LOADING',r.symbol);")
    company=replace_once(company,'if(token!==stockToken)return;', 'if(!isCurrentCompanyRequest(request))return;')
    company=replace_once(company,"if(!x){$('companySummary').replaceChildren(node('p','本股解释材料尚未收录。'));return}", "if(!x){renderCompanyStatus(document,'MISSING',r.symbol);return}")
    company=replace_once(company,'validateCompany(x,r.symbol);', "validateCompany(x,r.symbol);renderCompanyStatus(document,'READY',r.symbol);$('companyMetrics').replaceChildren();")
    company=replace_once(company,"if(token===stockToken)$('companySummary').replaceChildren(node('p','公司材料读取失败；图和分组未受影响。'))", "if(isCurrentCompanyRequest(request))renderCompanyStatus(document,'ERROR',r.symbol)")
    patched=patched[:start]+company+patched[end:]
    html=(dot_root/'shell/index.html').read_text()
    for old,new in [('<title>','<meta name="framework-api-base" content="/api/v4/research/workbench"><title>'),('href="./workbench.css"','href="workbench-host/dot/shell/workbench.css"'),('src="./workbench.mjs"','src="workbench-host/bootstrap.mjs"'),('<a href="../demo/index.html">合成联调示例</a>','<a id="macLegacyStockPage" href="legacy-daily.html">旧版单股归档</a>'),('外部个股模块待绑定','原式个股模块已接入'),('公共源码联调 · 未绑定服务','Mac本地 · 同源只读'),('昨日冻结候选','冻结数值候选')]:html=replace_once(html,old,new)
    html=html.replace('原五组','四组数值候选 · 风险待核另列')
    html=replace_once(html,'<select id="stockSort">','<select id="stockSort" hidden aria-hidden="true" tabindex="-1">'+''.join(f'<option value="{h}_{direction}">{h}</option>' for h in ('d2','d5') for direction in ('asc','desc')))
    html=replace_once(html,'<button data-stock-sort="amount">成交额</button>','<button data-stock-sort="amount">成交额</button><button data-stock-sort="d2">D+2</button><button data-stock-sort="d5">D+5</button>')
    html=replace_once(html,'股票四列排序','股票六列排序')
    html=replace_once(html,'<p id="listCount"','<details class="classification-filter"><summary>行业 / 多标签筛选</summary><input id="classificationQuery" type="search" placeholder="主营 / 官方大类 / 题材 / 催化剂" aria-label="分类检索"><div>'+''.join('<label><input type="checkbox" data-classification-label value="'+label+'">'+label+'</label>' for label in ('机器人','芯片','商业航天'))+'</div><small>多选取并集；每股只显示一次，来源UNKNOWN不推断。</small></details><p id="listCount"')
    html=replace_once(html,'官方行业大类 / 原库题材（分层来源）','主营行业 / 官方大类 / 交易题材 / 催化剂')
    html=replace_once(html,'<div class="stock-grid-head" aria-label="股票六列排序">','<div class="stock-grid-controls" aria-label="股票横向浏览"><button id="showStockNames" type="button" aria-controls="stockGridViewport">← 名称</button><span>横向查看</span><button id="showStockRates" type="button" aria-controls="stockGridViewport">D+2 / D+5 →</button></div><div id="stockGridViewport" tabindex="0" role="region" aria-label="股票六列，可横向滚动；表头与列表同步"><div id="stockGridTable"><div class="stock-grid-head" aria-label="股票六列排序">')
    html=replace_once(html,'<nav id="stockList" aria-label="股票列表"></nav>','<nav id="stockList" aria-label="股票列表"></nav></div></div>')
    scope_start=html.index('<details class="scope-options">');scope_end=html.index('</details>',scope_start)+len('</details>')
    scope=html[scope_start:scope_end].replace('<details class="scope-options"><summary>范围 / 分组</summary>','<section class="scope-options" aria-label="范围与研究分组"><strong class="scope-heading">范围 / 分组</strong>').replace('</details>','</section>')
    html=html[:scope_start]+html[scope_end:]
    html=replace_once(html,'<label for="query"',scope+'<label for="query"')
    html=replace_once(html,'</head>','''<style>#interactiveChart .interactive-scroll,#interactiveChart .chart-nav{display:none}#macHistoricalStatistics{margin-top:8px}#macOriginalRenderer iframe{display:block}.stock-grid-head,.stock-grid-row{grid-template-columns:minmax(110px,1.4fr) 58px 62px 66px 104px 104px!important;min-width:540px}.sidebar{min-width:0;overflow:hidden}#stockGridViewport{flex:1;min-height:150px;overflow:auto;scrollbar-width:thin;scrollbar-color:var(--cyan) var(--panel)}#stockGridTable{width:540px;min-width:100%}#stockGridViewport #stockList{overflow:visible;min-height:0;max-height:none;white-space:normal;flex:none}.stock-grid-head{position:sticky;top:0;z-index:2;background:var(--panel);padding-left:3px;padding-right:3px;border-left:1px solid transparent;border-right:1px solid transparent;width:100%}.stock-grid-controls{display:flex;align-items:center;justify-content:space-between;gap:4px;margin:4px 0;font-size:9px;color:var(--muted)}.stock-grid-controls button{font-size:10px;padding:4px 6px}@media(max-width:650px){#stockGridViewport{min-height:100px;max-height:155px}}.classification-filter{font-size:10px;margin:5px 0;max-height:115px;overflow:auto}.classification-filter label{display:inline-flex;align-items:center;font-size:10px;margin-right:4px}.classification-filter input[type=search]{font-size:10px}.grid-rate{font-size:11px;text-align:right}.stock-grid-head button{white-space:nowrap}.stock-item{width:100%}@media(min-width:651px) and (max-width:950px){.layout{grid-template-columns:250px minmax(0,1fr)}}</style></head>''')
    html=replace_once(html,'</head>','''<style id="workbench-filter-layout-r1">.sidebar{height:auto;min-height:calc(100vh - 240px);max-height:none;overflow:visible}.sidebar>*{flex-shrink:0}.sidebar-title .subtle{display:none}.sidebar>.scope-options{display:block;margin:6px 0 0;padding:6px 0 0}.scope-heading{display:block;color:var(--text);font-size:11px}.scope-options>label{font-size:10px}.scope-options select{margin:3px 0}.group-tabs{margin:3px 0 5px}.group-tabs button{line-height:1.3}.sidebar #listCount{display:block;white-space:pre-line;overflow:visible;line-height:1.5;margin:4px 0}.sidebar #stockGridViewport{flex:none;height:clamp(240px,calc(100vh - 610px),540px);min-height:240px;max-height:none}.sidebar .list-pager{display:flex;gap:5px;flex-wrap:wrap}.list-pager #listPage{flex:1;min-width:105px;text-align:center;line-height:1.5}.sidebar .source-note .counts{display:block;white-space:normal;line-height:1.5}.sidebar .source-note[open]{max-height:160px;overflow:auto}.stock-list-empty{padding:12px;color:var(--muted);white-space:normal;max-width:220px;font-size:12px}@media(max-width:650px){.sidebar{height:auto;min-height:0;max-height:none}.sidebar #stockGridViewport{height:260px;min-height:260px}.sidebar>.source-note{display:block}}</style></head>''')
    # Validate every source/anchor before creating or replacing output bytes.
    host=output/'workbench-host';host.mkdir(parents=True,exist_ok=True)
    if not (host/'dot').exists():shutil.copytree(dot_root,host/'dot')
    else:
        for entry in entries:
            relative=Path(entry['path']).relative_to('research/dashboard_framework_collab_20261030')
            if hashlib.sha256((host/'dot'/relative).read_bytes()).hexdigest()!=entry['sha256']:raise ValueError('EXISTING_VENDOR_DRIFT:'+str(relative))
    for name in HOST_FILES:shutil.copyfile(SOURCE/'mac-host'/name,host/name)
    (host/'stock').mkdir(exist_ok=True)
    for name in ['stock-bridge.mjs','host-context.mjs']:shutil.copyfile(SOURCE/name,host/'stock'/name)
    (host/'dot/shell/workbench.local.mjs').write_text(patched);(output/'workbench.html').write_text(html)
    exported=[dict(path=name,sha256=hashlib.sha256((output/name).read_bytes()).hexdigest()) for name in RUNTIME_ASSETS]
    (output/'MAC_RUNTIME_ASSETS.json').write_text(json.dumps(dict(schema_version='research_panel.assets.v1',files=exported),indent=2)+'\n')
    result=dict(status='BUILT_NOT_DEPLOYED',dot_commit=COMMIT,vendor_files=46,vendor_bytes_unchanged=True,seams=['checked unique import/function/HTML anchors','original stock renderer','versioned completion modules','header rates sorting'],runtime_assets_sha256=hashlib.sha256((output/'MAC_RUNTIME_ASSETS.json').read_bytes()).hexdigest())
    (output/'MAC_FRAMEWORK_BUILD.json').write_text(json.dumps(result,indent=2)+'\n');return result


HOMEPAGE_BUNDLE_SHA='247c3fca0afacda9681b434715e5fa8c7752b9a2b630a797f1ac8088ae28cf2b'
def build_homepage_entry(bundle,index,index_sha256,output):
    """Patch only the accepted injected navigation seam, without rebuilding Stage."""
    raw=bundle.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=HOMEPAGE_BUNDLE_SHA:raise ValueError('HOMEPAGE_NAV_BASELINE_SHA_DRIFT')
    entry=index.read_bytes()
    if hashlib.sha256(entry).hexdigest()!=index_sha256:raise ValueError('HOMEPAGE_INDEX_SHA_DRIFT')
    source=raw.decode()
    helper="function researchWorkbenchHref(){const d=new URLSearchParams(window.location.search).get('date');return '/research-panel/workbench.html'+(d===null?'':'?'+new URLSearchParams({date:d}));}\n"
    if 'researchWorkbenchHref' in source:raise ValueError('HOMEPAGE_HELPER_COLLISION')
    source=replace_once(source,'href:"/research-panel/daily.html?date=2026-10-28"',"href:researchWorkbenchHref(),onClick:t=>{t.currentTarget.href=researchWorkbenchHref()},onFocus:t=>{t.currentTarget.href=researchWorkbenchHref()},onPointerenter:t=>{t.currentTarget.href=researchWorkbenchHref()}")
    raw=(helper+source).encode();name='main-workbench-entry-'+hashlib.sha256(raw).hexdigest()[:12]+'.js'
    html=replace_once(entry.decode(),'/assets/'+bundle.name,'/assets/'+name)
    output.mkdir(parents=True,exist_ok=True);(output/'assets').mkdir(exist_ok=True)
    (output/'assets'/name).write_bytes(raw);(output/'index.html').write_text(html)
    result=dict(status='BUILT_NOT_INSTALLED',baseline_bundle_sha256=HOMEPAGE_BUNDLE_SHA,files=[dict(path='assets/'+name,sha256=hashlib.sha256(raw).hexdigest()),dict(path='index.html',sha256=hashlib.sha256((output/'index.html').read_bytes()).hexdigest())],move_after_reference_check=dict(source='assets/'+bundle.name,target='待删除/legacy-homepage/'+bundle.name,sha256=HOMEPAGE_BUNDLE_SHA),scope='ONLY_RESEARCH_NAV_HREF_CURRENT_URL_DATE_NO_STAGE_LOGIC_CHANGE')
    (output/'HOMEPAGE_ENTRY_BUILD.json').write_text(json.dumps(result,indent=2)+'\n');return result


def materialize_statistics(product_root,output):
    """One saved-row projection, no label/return producer and no full rereads."""
    from ops.research_panel_daily_product import FLAGS,checked,save as put
    def read(ref):return json.loads(checked(ref).read_bytes())
    index=json.loads((product_root/'index.json').read_text());day=index['latest_date'];manifest_ref=index['dates'][day]
    manifest=read(manifest_ref);product=read(manifest['artifact']);identity=product['source_identity'];config=read(product['source_config'])
    if (manifest.get('schema_version')!='v4.a_share.daily_product_manifest.v1' or product.get('schema_version')!='v4.a_share.daily_product.v1'
            or manifest.get('data_date')!=day or product.get('data_date')!=day or str(identity.get('asof'))!=day
            or product.get('source_generation')!=identity.get('generation') or manifest.get('source_generation')!=product.get('source_generation')
            or manifest.get('input_sha256')!=identity.get('input_sha256') or product.get('sample_only') is not False
            or any(product.get(k)!=v or manifest.get(k)!=v for k,v in FLAGS.items())):raise ValueError('WORKBENCH_STATISTICS_PRODUCT_IDENTITY_CONFLICT')
    product={**product,'manifest':manifest_ref};rows={}
    for row in product['rows']:
        detail=read(product['row_refs'][row['symbol']]);statistics=detail.get('statistics') or {};qualification=detail.get('qualification') or {}
        asof=f'{day[:4]}-{day[4:6]}-{day[6:]}'
        expected=dict(generation=product['source_generation'],input=identity['input_sha256'],asof=asof,market=row['symbol'][-2:],formula=config['formula']['sha256'],basis=identity.get('basis',{}).get('price_basis','QFQ_ASOF'))
        if (detail.get('symbol')!=row['symbol'] or detail.get('data_date')!=day or statistics.get('asof')!=asof
                or qualification.get('symbol')!=row['symbol'] or qualification.get('target_date')!=day or qualification.get('source_generation')!=product['source_generation']
                or not statistics.get('groups') or any(detail.get(k)!=v for k,v in FLAGS.items())):raise ValueError('WORKBENCH_STATISTICS_ROW_IDENTITY_CONFLICT')
        for group in statistics['groups']:
            binding=group.get('source_identity') or {}
            if group.get('identity_status')!='BOUND' or any(binding.get(k)!=v for k,v in expected.items()) or binding.get('rule_sha256')!=group.get('rule_sha256'):raise ValueError('WORKBENCH_STATISTICS_GROUP_IDENTITY_CONFLICT')
        rows[row['symbol']]={g['group_id']:{h:{k:v for k,v in values.items() if k in ('valid','positive','positive_fraction','not_matured','total')} for h,values in g['horizons'].items() if h in ('d2','d5')} for g in statistics['groups']}
    iso=f'{day[:4]}-{day[4:6]}-{day[6:]}'
    value=dict(schema='V4_WORKBENCH_STATISTICS_V1',source_date=iso,generation=product['source_generation'],input_sha256=product['source_identity']['input_sha256'],numeric_manifest=product['manifest'],rows=rows,**FLAGS)
    key=hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest();root=output/iso
    artifact=put(root/key/'statistics.json',value);receipt=put(root/key/'receipt.json',dict(status='COMMITTED',artifact=artifact,**FLAGS))
    # The index must still point at the product whose rows were projected.
    if json.loads((product_root/'index.json').read_text())['dates'][day]!=product['manifest']:raise ValueError('WORKBENCH_STATISTICS_SOURCE_MOVED')
    return put(root/'latest.json',dict(schema='V4_WORKBENCH_MODULE_COMMIT_V1',module='statistics',date=iso,artifact=artifact,receipt=receipt,**FLAGS))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--dot-root',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--receipt',type=Path);p.add_argument('--statistics-product-root',type=Path);p.add_argument('--homepage-bundle',type=Path);p.add_argument('--homepage-index',type=Path);p.add_argument('--homepage-index-sha256');a=p.parse_args()
    if a.homepage_bundle:
        if not a.homepage_index or not a.homepage_index_sha256:p.error('homepage index and exact SHA are required')
        result=build_homepage_entry(a.homepage_bundle,a.homepage_index,a.homepage_index_sha256,a.output)
    elif a.statistics_product_root:result=materialize_statistics(a.statistics_product_root,a.output)
    else:
        if not a.dot_root or not a.receipt:p.error('--dot-root and --receipt are required for a shell build')
        result=build(a.dot_root,a.output,a.receipt)
    print(json.dumps(result))
