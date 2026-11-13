import {DEFAULT_DATE,apiSymbol,loadReview,loadDailyProduct,loadEventCases,loadHkWorkbench,loadHkReview,maturityGroups,normaliseDate,statusKind} from '../shared/data.js';
import {esc,text,dateInput,pill,card,lines,detail,remember,pageLink,updateNav,setStatus,maturityCard} from '../shared/ui.js';
const $=id=>document.getElementById(id),params=new URLSearchParams(location.search);
let reviewRequest=0,maturityRequest=0;
let planPin = null;
function context(){
  const date=normaliseDate($('date').value);
  const market=$('market').value;
  if (market !== 'HK' || planPin?.date !== date) planPin = null;
  return {date,observationDate:date,sourceDate:normaliseDate($('source-date').value),market,
    symbol:apiSymbol(market,$('symbol').value),group:$('group').value,search:params.get('search'),
    source:params.get('source'),pageNumber:params.get('page'),runId:planPin?.runId ?? null};
}
function updateContext(ctx) {
  updateNav(ctx);
  $('research-link').href=pageLink('research',ctx);
  $('selection-link').href=pageLink('selection',ctx);
  remember({date:ctx.date,sourceDate:ctx.sourceDate,market:ctx.market,symbol:ctx.symbol,group:ctx.group,runId:ctx.runId});
}
function stockTable(rows,market,date){
  if(!Array.isArray(rows)||!rows.length)return '<p>该来源没有可展示行；空结果与模块状态分别保留。</p>';
  return `<div class="v45-table-wrap"><table><thead><tr><th>证券</th><th>原排名 / 表现</th><th>原理由 / 角色</th></tr></thead><tbody>${rows.map(r=>{
    const symbol=r.symbol??r.code??r.stock_code;let link='';
    try{link=pageLink('research',{date,sourceDate:date,observationDate:date,market,symbol:apiSymbol(market,symbol)});}catch{}
    return `<tr><td>${link?`<a href="${link}">${esc(symbol)} ${esc(r.name??r.stock_name??'')}</a>`:esc(symbol??'身份待核')}</td><td>排名 ${esc(text(r.rank))} · ${r.pct_chg_close==null&&r.pct_change==null&&r.pct_chg==null?'涨跌未知':esc(r.pct_chg_close??r.pct_change??r.pct_chg)+'%'}</td><td>${esc(text(r.reason??r.role_explanation??r.primary_role??r.decision??r.strategy))}</td></tr>`;
  }).join('')}</tbody></table></div>`;
}
function renderMarket(market,value,date){
  if(value.trade_date&&value.trade_date!==date)return card(market+' 复盘','CONFLICT','<p>市场子结果日期冲突，已隔离。</p>');
  if(market==='A'){
    const model=value.model_review??{},close=value.close_chain??{},rows=value.observation_pool??[],status=close.status??model.status??value.status??'CANNOT_CONFIRM';
    return card('A股 · '+(value.headline??date),status,lines([`原观察池 ${rows.length} 只（仅此复盘来源分母）`,`原模型复盘 ${text(model.status)} · 收盘链 ${text(close.status)}`,`泛化/晋级：${text(model.formal_generalization)} / ${text(model.model_promotion)}`])+detail('原质量门及缺口',{quality_gate:value.quality_gate,cannot_confirm:value.cannot_confirm,close_chain:close})+stockTable(rows,'A',date));
  }
  const model=value.model_selection_review??{},status=value.status??model.status??'CANNOT_CONFIRM';
  return card('港股 · 原 0.2 与阶段复盘',status,lines([`收盘 Top20 ${text(model.row_counts?.close_top20??model.close_top20?.length)} · 0.2 模型命中 ${text(model.kpi?.model_0_2_close_top20_hits)}`,`阶段并集分母 ${text(model.stage_union?.selected_count)} · 原证据 ${text(model.stage_union?.evidence_status)}`,`原模式 ${text(model.evidence_mode)} · 来源 SHA ${text(value.source_sha256??model.source_sha256)}`])+detail('原分母、阶段与缺口',{models:model.models,stage_union:model.stage_union,observed_stage_union:model.observed_stage_union,row_counts:model.row_counts,cannot_confirm:model.cannot_confirm,unverified_stages:model.unverified_stages})+stockTable(model.close_top20,'HK',date));
}
async function load(){
  const ticket=++reviewRequest;$('markets').innerHTML='';
  try{
    const date=normaliseDate($('date').value);remember({date});setStatus('正在读取精确日期复盘…','RUNNING');
    const payload=await loadReview(date);if(ticket!==reviewRequest)return;
    const a=payload.market_reviews?.A??{},hk=payload.market_reviews?.HK??{};
    $('markets').innerHTML=renderMarket('A',a,date)+renderMarket('HK',hk,date);
    const statuses=[a.close_chain?.status??a.model_review?.status,hk.status??hk.model_selection_review?.status];
    setStatus(`${date} 原复盘已读取；reference_snapshot=${text(payload.reference_snapshot)}。各市场分母、缺失阶段和原模式独立保留。`,payload.reference_snapshot||statuses.some(s=>statusKind(s)!=='good')?'PARTIAL':'READY');
  }catch(error){if(ticket!==reviewRequest)return;setStatus(error.message,'FAILED');$('markets').innerHTML=card('复盘不可确认','FAILED','<p>未使用其他日期结果代替所选日期。</p>');}
}
async function maturity(event){
  event?.preventDefault();const ticket=++maturityRequest;$('maturity').innerHTML='<p>正在核对原分组与成熟度…</p>';
  try{
    const ctx=context(),date=ctx.sourceDate,symbol=ctx.symbol;
    updateContext(ctx);
    if(ctx.market==='HK'){
      const w=await loadHkWorkbench({date:ctx.observationDate,symbol,runId:ctx.runId});
      if(ticket!==maturityRequest)return;
      let body=card('港股证券级 D+2 / D+5','CANNOT_CONFIRM','<p>未取得该市场的证券级成熟度合同，不借用 A 股日历或收益。</p>');
      if(w.snapshot?.run_id){
        planPin={date:ctx.observationDate,runId:w.snapshot.run_id};
        updateContext({...ctx,runId:planPin.runId});
        const review=await loadHkReview({date:ctx.observationDate,planRunId:w.snapshot.run_id});
        if(ticket!==maturityRequest)return;
        body+=card('港股同批原工作台复盘',review.data?.mode==='NOT_EVALUATED'?'NOT_EVALUATED':review.state,
          lines([`产物读取状态 ${text(review.state)} · 原评价模式 ${text(review.data?.mode)}`,`收盘榜日期 ${text(review.data?.ranking_date)}`,
            ...new Set([...(review.gaps??[]),...(review.data?.gaps??[])])])+detail('保存计划及原复盘',{plan_run_id:w.snapshot.run_id,data:review.data,gaps:review.gaps}));
      }else body+=card('原工作台计划',w.status,detail('缺口',w.day?.gaps));
      $('maturity').innerHTML=body;return;
    }
    const product=await loadDailyProduct({symbol,date});if(ticket!==maturityRequest)return;
    const group=maturityGroups(product).find(g=>g.groupId===ctx.group);
    if(!group){$('maturity').innerHTML=card('分组成熟度','CANNOT_CONFIRM',lines([`来源日 ${date} · ${symbol} · ${ctx.group}`,`数值日包状态 ${product.status}`,...(product.cannot_confirm??[])])+'<p>该原日包没有本分组统计，未以其他分组替换。</p>');return;}
    $('maturity').innerHTML=`<p class="v45-group">${esc(symbol)} · ${esc(ctx.group)} · 来源时点 ${date}</p>${maturityCard('D+2',group.d2)}${maturityCard('D+5',group.d5)}`;
    const [d2,d5]=await Promise.all(['d2','d5'].map(horizon=>loadEventCases({symbol,date,group:ctx.group,horizon,product})));
    if(ticket!==maturityRequest)return;
    // The owner daily-product retains valid statistics even if an independent detail read fails.
    $('maturity').innerHTML=`<p class="v45-group">${esc(symbol)} · ${esc(ctx.group)} · 来源时点 ${date}。历史事件与最新信号分别列出。</p>`+
      [d2,d5].map((value,i)=>value.status==='READY'?maturityCard(i?'D+5':'D+2',value):maturityCard(i?'D+5 · 原日包统计':'D+2 · 原日包统计',i?group.d5:group.d2)+card('事件明细读取',value.status,lines(value.cannot_confirm??[]))).join('');
  }catch(error){if(ticket!==maturityRequest)return;$('maturity').innerHTML=card('成熟度 / 同批复盘','CANNOT_CONFIRM',lines([error.message,'缺件保持未知，不填零。']));}
}
$('review-form').onsubmit=e=>{e.preventDefault();load();maturity();};$('maturity-form').onsubmit=maturity;
for(const id of ['date','market','symbol','source-date','group'])$(id).addEventListener('change',()=>{++maturityRequest;$('maturity').innerHTML='<p>上下文已改变，请重新核对成熟度。</p>';try{updateContext(context());}catch{}});
try{$('date').value=dateInput(params.get('date')||DEFAULT_DATE);$('source-date').value=dateInput(params.get('sourceDate')||params.get('date')||DEFAULT_DATE);}catch{$('date').value='';$('source-date').value='';}
if(['A','HK'].includes(params.get('market')))$('market').value=params.get('market');
if ($('market').value === 'HK' && params.get('runId') && $('date').value) {
  planPin={date:normaliseDate($('date').value),runId:params.get('runId')};
}
$('symbol').value=params.get('symbol')||($('market').value==='HK'?'HK.02659':'000159.SZ');
if(['original','nav_smallk','nav_pullback','nav_breakout'].includes(params.get('group')))$('group').value=params.get('group');
load();maturity();
