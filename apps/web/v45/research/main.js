import {DEFAULT_DATE,loadResearchBundle,normaliseDate,apiSymbol} from '../shared/data.js';
import {esc,text,dateInput,pill,card,lines,detail,remember,pageLink,updateNav,setStatus,safeAssetUrl,maturityCard} from '../shared/ui.js';
const $=id=>document.getElementById(id),params=new URLSearchParams(location.search);
let request=0;
let loadedContext = null;
const gaps=x=>[x?.missing_reason,...(Array.isArray(x?.cannot_confirm)?x.cannot_confirm:[]),...(Array.isArray(x?.availability_gaps)?x.availability_gaps:[])].filter(Boolean);
function renderA(bundle,ctx){
  const p=bundle.product,c=bundle.chart,m=bundle.company,row=p.row??{},stats=row.statistics??{},evaluation=row.evaluation??{};
  const groups=bundle.maturity;
  $('overview').innerHTML=[['数值日包',p.status],['原图描述',c.status],['公司材料',m.status],['来源日期',bundle.date]].map(([label,value])=>`<div class="v45-stat"><strong>${esc(value??'未知')}</strong><span>${label}</span></div>`).join('');
  const chartUrl=safeAssetUrl(c.assets?.html?.url),png=safeAssetUrl(c.assets?.png?.url);
  const assetContent=chartUrl?`<p><a href="${esc(chartUrl)}" target="_blank" rel="noopener noreferrer">打开原图（沿用原日期与 SHA 绑定）</a></p><button id="load-chart" type="button">在本页加载原图</button>`:png?`<img class="v45-chart-image" src="${esc(png)}" alt="原 owner 的个股图形">`:'<p>尚无可读取的图形资产入口。</p>';
  $('evidence').innerHTML=
    card('量价结构 · '+text(row.display_name||bundle.symbol),p.status,lines([`来源日 ${bundle.date} · 原组别 ${text(row.groups)} · 最近关键 K ${text(row.latest_new_anchor)}`,`原数值判定 ${text(evaluation.status)} · 风险清除 ${text(row.risk_clear)}`,`原判定说明 ${text(row.reasons)}`,`当前收盘 ${text(stats.price_distribution?.current_close)} · 近250日历史分位 ${text(stats.price_distribution?.near_250?.percentile??stats.price_distribution?.near_250?.current_price_percentile)}`,...gaps(p)])+detail('原组别结构与风险',{groups:evaluation.groups,risk:evaluation.risk,qualification:{reason:row.qualification?.reason,historical_PIT:row.qualification?.historical_PIT},historical_coverage:row.historical_coverage}))+
    card('原图 / 关键 K',c.status,lines([`图形描述行数 ${text(c.rows)}`,`图形资产：${Object.keys(c.assets??{}).join(' / ')||'未提供'}`,...gaps(c)])+assetContent+'<p class="v45-muted">描述 READY 与图形资产实际加载分开；本页不会重新计算图形。</p>')+
    card('公司材料 · 基本面、产业与风险',m.status,lines(gaps(m).length?gaps(m):['按原材料的公开/可用时点查看；材料收到与已导入分别记录。'])+(m.materials||m.items||m.summary?detail('原材料与证据',m.materials??m.items??m.summary):'<p>尚无绑定公司材料；不由量价判定补写基本面结论。</p>'))+
    card('来源与验证边界',p.status,lines([`generation：${text(p.source_generation)}`,`历史 PIT：${text(p.source_identity?.historical_PIT)}`,`历史覆盖：${text(row.historical_coverage?.status)}；已评估 ${text(row.historical_coverage?.evaluated_count)}`,`原最高结论：${text(row.historical_coverage?.maximum_claim)}`])+'<p>当前页面为原结果投影，原判定不等同于新的买入评级。</p>')+
    groups.map(g=>`<section class="v45-group"><h3>${esc(g.groupId)} · 原事件分母</h3><div class="v45-two">${maturityCard('D+2',g.d2)}${maturityCard('D+5',g.d5)}</div><p><a href="${pageLink('review',{...ctx,group:g.groupId})}">核对此组原事件明细</a></p></section>`).join('');
  if(!groups.length)$('evidence').innerHTML+=card('D+2 / D+5','CANNOT_CONFIRM','<p>日包没有该股分组统计，不使用历史其他股票或其他日期的收益代填。</p>');
  $('lineage').innerHTML=lines([`A股 ${bundle.symbol} · 材料来源日 ${bundle.date} · 观察日 ${ctx.observationDate}`,`input SHA ${text(p.source_identity?.input_sha256)}`,`numeric manifest SHA ${text(p.manifest?.sha256)}`,`chart manifest SHA ${text(c.chart_manifest?.sha256)}`])+'<p>材料日期、事实可用时间、历史案例及最新信号分别保留。研究回包已收到不代表公司材料已导入。</p>';
  if(chartUrl)$('load-chart').onclick=()=>{
    const host=$('chart-host');host.classList.remove('v45-hidden');
    host.innerHTML='<h2 class="v45-title">原图资产</h2><p>已请求原 owner 图形。若原资产不可达，下方会显示其错误；不据描述状态宣称图形已验收。</p>';
    const frame=document.createElement('iframe');frame.className='v45-chart';frame.title='同来源日原图';frame.referrerPolicy='same-origin';frame.src=chartUrl;host.appendChild(frame);
  };
}
function renderHK(bundle,ctx){
  const w=bundle.workbench,stock=w.stock,candidate=bundle.candidate,snapshot=w.snapshot;
  $('overview').innerHTML=[['原工作台',w.status],['0.2池覆盖',candidate?'已覆盖':'未覆盖'],['观察日',bundle.observationDate],['材料来源日',candidate?.sourceDates.join(' / ')||'未知']].map(([k,v])=>`<div class="v45-stat"><strong>${esc(v)}</strong><span>${k}</span></div>`).join('');
  $('evidence').innerHTML=card('港股通 / 0.2 原候选 · '+text(candidate?.name||stock?.name||bundle.symbol),candidate?candidate.sources[0]?.poolStatus:'CANNOT_CONFIRM',
    candidate?lines(candidate.sources.map(s=>`${s.poolId} · 来源日 ${text(s.sourceDate)} · 原排名 ${text(s.rank)} · 原分数 ${text(s.score)} · ${text(s.reason)}`))+detail('候选原来源',candidate.sources):lines([bundle.poolError||'当前池未覆盖该股，不解释为淘汰。']))+
    card('港股原个股研究',w.status,stock?lines([`原判定 ${text(stock.decision)}`,...(stock.reasons??[]),...(stock.conditions??[]).map(x=>'观察条件：'+x),...(stock.invalidation_conditions??[]).map(x=>'失效条件：'+x),...(stock.risks??[]).map(x=>'风险：'+x)])+detail('原分来源证据',w.detail?.data?.lane_details):lines([...gaps(w),...(w.day?.gaps??[]),'本次没有该股可读取的工作台材料，保留候选资料。']))+
    card('港股独立日历与批次',snapshot?'BOUND':'CANNOT_CONFIRM',lines([`run_id ${text(snapshot?.run_id)}`,`原运行阶段 ${text(snapshot?.context?.phase)}`,`真实截止时点 ${text(snapshot?.context?.cutoff)}`,`原输入 SHA ${text(snapshot?.input_sha256)}`])+'<p>不套用 A 股 v1.9.2 或成熟日历；事后/手动结果依原阶段标记展示。</p>')+
    card('港股 D+2 / D+5','CANNOT_CONFIRM','<p>尚无已确认的港股证券级成熟度合同；不填零，也不借用 A 股案例。</p>');
  $('lineage').innerHTML=lines([`港股 ${bundle.symbol} · 观察日 ${bundle.observationDate}`,`现役读取路径：manager-workbench/days → 固定 run_id → stocks`, `材料状态 ${w.status}；候选状态独立保留。`]);
}
function bindContext(ctx) {
  loadedContext=ctx;
  remember({...ctx,sourceDate:null,pageNumber:null});
  updateNav(ctx);
  $('selection-link').href=pageLink('selection',ctx);
  $('review-link').href=pageLink('review',ctx);
}
async function load(){
  const ticket=++request;
  for(const id of ['overview','evidence','lineage','chart-host'])$(id).innerHTML='';$('chart-host').classList.add('v45-hidden');
  try{
    const market=$('market').value,symbol=apiSymbol(market,$('symbol').value),date=normaliseDate($('date').value);
    const sameContext=loadedContext?.date===date && loadedContext.market===market;
    const initial=!loadedContext;
    const observationDate=sameContext ? loadedContext.observationDate : normaliseDate((initial && params.get('observationDate')) || date);
    const runId=market==='HK' ? (sameContext ? loadedContext.runId : initial ? params.get('runId') : null) : null;
    const ctx={date,sourceDate:date,observationDate,market,symbol,group:params.get('group'),search:params.get('search'),source:params.get('source'),pageNumber:params.get('page'),runId};
    bindContext(ctx);setStatus('正在读取原研究材料…','RUNNING');
    const bundle=await loadResearchBundle(ctx);if(ticket!==request)return;
    if(market==='A')renderA(bundle,ctx);else {
      renderHK(bundle,ctx);
      if (bundle.workbench.snapshot?.run_id) bindContext({...ctx,runId:bundle.workbench.snapshot.run_id});
    }
    setStatus(`${market} ${symbol} · 来源日 ${date} · 观察日 ${observationDate}。各模块独立显示状态，当前 ${bundle.status}。`,bundle.status);
  }catch(error){if(ticket!==request)return;setStatus(error.message,'FAILED');$('evidence').innerHTML=card('读取失败 / 待确认','FAILED','<p>请核对市场、证券与来源日。旧材料已撤下。</p>');}
}
$('research-form').onsubmit=e=>{e.preventDefault();load();};
if(['A','HK'].includes(params.get('market')))$('market').value=params.get('market');
$('symbol').value=params.get('symbol')||($('market').value==='HK'?'HK.02659':'000159.SZ');
try{$('date').value=dateInput(params.get('date')||DEFAULT_DATE);}catch{$('date').value='';}
load();
