import {DEFAULT_DATE,apiSymbol,fetchAllPreselection,fetchFormulaComparisonRows,formulaComparisonFor,normaliseDate,statusKind} from '../shared/data.js';
import {esc,text,dateInput,pill,detail,remember,pageLink,updateNav,setStatus,card,lines} from '../shared/ui.js';
const $=id=>document.getElementById(id);
const params=new URLSearchParams(location.search);
let current=null,page=Math.max(1,Number(params.get('page'))||1),request=0,formulaRequest=0;
const pageSize=50,formulaCache=new Map();
function context(row,sourceDate){return {date:current?.date,observationDate:current?.date,sourceDate,market:row?.market??$('market').value,symbol:row?apiSymbol(row.market,row.symbol):undefined,search:$('search').value,source:$('source').value,pageNumber:page};}
function researchLinks(row){
  const selected=$('source').value;
  const dates=[...new Set(row.sources.filter(s=>!selected||s.poolId===selected).map(s=>s.sourceDate).filter(Boolean))].sort();
  return dates.length?dates.map(date=>`<a href="${pageLink('research',context(row,date))}">个股研究${dates.length>1?' · '+esc(date):''}</a>`).join('<br>'):'来源日未知，待核';
}
function renderFormula(date,market){
  const ticket=++formulaRequest;
  if(market==='HK'){$('formula').textContent='港股沿用港股通 / 0.2 原合同，不适用 A 股公式比较。';return;}
  const summary=formulaComparisonFor(date);
  if(!summary){$('formula').textContent='该观察日没有已提供的冻结公式对照，状态 CANNOT_CONFIRM。尚无条件明细时不推断未入选原因。';return;}
  $('formula').innerHTML=`<p>冻结来源日 ${summary.sourceDate} → 观察日 ${summary.observationDate}。原公式 ${summary.original}，v1.9.2 ${summary.v192}，共同 ${summary.common}，仅原公式 ${summary.originalOnly}，仅 v1.9.2 ${summary.v192Only}。</p><p class="v45-status warn">历史对照：已核对同日成员集合。本包缺双方输入版本的独立比较 manifest，当前在线批次可比性 CANNOT_CONFIRM；不据此推断今天为什么漏选。</p><div id="formula-rows">正在读取原逐股比较…</div>`;
  if(!formulaCache.has(date))formulaCache.set(date,fetchFormulaComparisonRows(date));
  formulaCache.get(date).then(rows=>{
    if(ticket!==formulaRequest)return;
    $('formula-rows').innerHTML=`<details><summary>展开 ${rows.length} 条逐股差异（保留 UNKNOWN）</summary><div class="v45-table-wrap"><table><thead><tr><th>证券 / 类别</th><th>原判定</th><th>v1.9.2 原分数</th><th>原始证据</th></tr></thead><tbody>${rows.map(r=>`<tr><td><a href="${pageLink('research',{date:r.source_date,observationDate:r.observation_date,market:'A',symbol:r.symbol})}">${esc(r.symbol)} ${esc(r.display_name)}</a><small>${esc(r.category)}</small></td><td>${pill(r.original_status)}<small>${esc(r.original_raw_hits||'尚无条件明细')}</small></td><td>${esc(r.v192_final_score||'未知')}<small>${esc(r.v192_multi_head_final_role||r.v192_candidate_role||'未知')}</small></td><td>${esc(r.difference_reason||'尚无条件明细')}${detail('原条件及来源 SHA',r)}</td></tr>`).join('')}</tbody></table></div></details>`;
  }).catch(error=>{if(ticket===formulaRequest)$('formula-rows').textContent=error.message+'；逐股对照未通过读取核验。';});
}
function delivery(date){
  $('delivery').innerHTML=card('所选观察日 '+date,'CANNOT_CONFIRM',lines(['富途同步：CANNOT_CONFIRM（尚未取得本批新回执）','研究收到 / 机械校验 / 导入 / 页面可见：逐项 CANNOT_CONFIRM。没有用旧回执代填。']))+
    card('历史四组研究批次 · D11 / O12','PARTIAL_NOT_IMPORTED',lines(['独立四组集合 426 只、541 条组别关系；与本页多来源汇总不同。','历史富途 1112：426 / 426 已验。研究 426 只 PARTIAL；64 个来源范围不兼容；NOT_IMPORTED。'])+'<p><a href="https://drive.google.com/file/d/1SMO8J3MLhdj2hgac1iVUeywofxrE7hqB/view" target="_blank" rel="noopener noreferrer">原批次 manifest</a> · <a href="https://drive.google.com/file/d/1gV6_e4p3J1r_OzyHwblPDysmyH_0-BUN/view" target="_blank" rel="noopener noreferrer">原 426 只清单</a></p>');
}
function render(){
  if(!current)return;
  const data=current,market=$('market').value,q=$('search').value.trim().toLowerCase(),source=$('source').value,state=$('pool-state').value;
  const rows=data.rows.filter(r=>(market==='ALL'||r.market===market)&&(!q||(r.displaySymbol+' '+r.name+' '+r.symbol).toLowerCase().includes(q))&&r.sources.some(s=>(!source||s.poolId===source)&&(!state||statusKind(s.poolStatus)===state)));
  const pages=Math.max(1,Math.ceil(rows.length/pageSize));page=Math.min(pages,Math.max(1,page));
  remember({date:data.date,market,search:q,source,page,state});updateNav(context());
  $('stats').innerHTML=[['A股候选',data.counts.A,`API 分母 ${text(data.expected.A)}`],['港股候选',data.counts.HK,`API 分母 ${text(data.expected.HK)}`],['来源关系',data.membershipCount,'一股多来源分别保留'],['读取完整性',data.complete?'已核对':'未完整',data.dataStatus]].map(([label,value,note])=>`<div class="v45-stat"><strong>${esc(value)}</strong><span>${esc(label)} · ${esc(note)}</span></div>`).join('');
  $('pools').innerHTML=data.pools.map(p=>`<details class="v45-pool"><summary><strong>${esc(p.label)}</strong> ${pill(p.status)} <span>${p.readRows} / ${text(p.totalRows)} 条</span></summary><p>来源日 ${esc(p.sourceDate||'未知')} · 观察日 ${data.date} · 市场 ${esc(p.market)}</p><p class="v45-hash">来源 SHA ${esc(p.sourceSha256||'未知')}</p>${detail(`缺口与影响（${p.cannotConfirm.length}项）`,p.cannotConfirm)}<p>此池缺件只影响本来源；有效独立来源仍展示。自然执行未由本页认证。</p></details>`).join('')+detail('本批 fingerprint 与隔离项',{pool_input_fingerprint:data.inputSha256,source_digests:data.sourceDigests,isolated:data.isolated});
  $('row-count').textContent=`当前筛选 ${rows.length} 只 / 全部 ${data.rows.length} 只 · 第 ${page} / ${pages} 页`;
  $('candidates').innerHTML=rows.slice((page-1)*pageSize,page*pageSize).map(r=>`<tr><td data-label="市场">${r.market}</td><td data-label="证券"><strong>${esc(r.displaySymbol)}</strong><small>${esc(r.name)}</small></td><td data-label="来源">${r.sources.map(s=>`<div>${esc(s.poolId)}</div>`).join('')}</td><td data-label="来源日">${esc(r.sourceDates.join(' / ')||'未知')}</td><td data-label="原判定">${r.sources.map(s=>`<div>${esc(s.poolId)}：排名 ${esc(text(s.rank))} / 分数 ${esc(text(s.score))}<small>${esc(text(s.reason))}</small><small>行情时点：${esc(text(s.quoteAsOf))}</small>${detail('来源身份与资格',s)}</div>`).join('')}</td><td data-label="来源状态">${r.sources.map(s=>pill(s.poolStatus)).join(' ')}</td><td data-label="操作">${researchLinks(r)}</td></tr>`).join('')||'<tr><td colspan="7" class="v45-empty">本筛选 0 只；请同时查看各来源是有效空池、未生成、失败还是过期。</td></tr>';
  $('pagination').innerHTML=`<button id="prev" ${page<=1?'disabled':''}>上一页</button><span>每页 ${pageSize} 只；分页不改变原选股输入</span><button id="next" ${page>=pages?'disabled':''}>下一页</button>`;
  $('prev').onclick=()=>{page--;render();};$('next').onclick=()=>{page++;render();};
  setStatus(`${data.date}：读取 ${data.rows.length} 只 / ${data.membershipCount} 条关系。${data.complete?'名单数量及逐来源关系已核对。':data.completenessReason} 原数据状态 ${data.dataStatus}；不代表自然执行完成。`,data.complete?data.dataStatus:'PARTIAL');
  renderFormula(data.date,market);delivery(data.date);
}
async function load(){
  const ticket=++request;++formulaRequest;current=null;
  for(const id of ['stats','pools','formula','pagination','delivery'])$(id).innerHTML='';
  $('candidates').innerHTML='<tr><td colspan="7">读取中…</td></tr>';$('row-count').textContent='';
  try{
    const date=normaliseDate($('date').value);remember({date});setStatus('正在按原 API 分页读取来源…','RUNNING');
    const result=await fetchAllPreselection(date);if(ticket!==request)return;current=result;
    const prior=$('source').value||params.get('source')||'';
    $('source').innerHTML='<option value="">全部来源</option>'+result.pools.map(p=>`<option value="${esc(p.poolId)}">${esc(p.label)}</option>`).join('');
    $('source').value=result.pools.some(p=>p.poolId===prior)?prior:'';render();
  }catch(error){if(ticket!==request)return;setStatus(error.message,'FAILED');$('candidates').innerHTML='<tr><td colspan="7" class="v45-empty">所选日期数据未读取成功，旧名单已撤下。</td></tr>';}
}
$('selection-form').onsubmit=e=>{e.preventDefault();page=1;load();};
for(const id of ['search','market','source','pool-state'])$(id).addEventListener(id==='search'?'input':'change',()=>{page=1;render();});
try{$('date').value=dateInput(params.get('date')||DEFAULT_DATE);}catch{$('date').value='';}
if(['A','HK','ALL'].includes(params.get('market')))$('market').value=params.get('market');
$('search').value=params.get('search')||'';$('pool-state').value=params.get('state')||'';
load();
