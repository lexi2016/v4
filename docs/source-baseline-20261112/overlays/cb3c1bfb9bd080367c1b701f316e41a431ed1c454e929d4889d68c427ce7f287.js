'use strict';

const research28LayerSpec=[
 {title:'来源名单',note:'两套来源名单分别过滤；保留原始成员。',ids:['original94','initial429']},
 {title:'结构观察',note:'突破关键K观察是429内的重分类，不新增股票。',ids:['breakout112']},
 {title:'结构阶段与突破子组',note:'原始阶段标签和突破子组保持独立筛选。',ids:['stage0','stage1','stage2','stage3','stage4','stage5','breakout_FIRST_CLOSE_CROSS_SINCE_ANCHOR','breakout_ABOVE_CONTINUATION','breakout_RECROSS_AFTER_PRIOR_BREAK'],details:true},
 {title:'图审、身份待核与扩展状态',note:'这是复核/身份状态或扩展来源，不等于新的选股模型。',ids:['research18','original_unknown36','extended2'],details:true}
];
function research28GroupButton(g){return `<button type="button" data-group="${esc(g.id)}"><span>${esc(g.title)}</span><small>${esc(g.count)}只</small></button>`}
function renderResearch28Groups(){
 const byId=new Map(manifest.groups.map(g=>[g.id,g])),used=new Set();
 const button=(g)=>{if(!g)return '';used.add(g.id);return research28GroupButton(g)};
 const buckets=research28LayerSpec.map(layer=>{const pills=layer.ids.map(id=>button(byId.get(id))).filter(Boolean).join('');const note=`<p>${esc(layer.note)}</p>`;return layer.details?`<details class="group-details"><summary>${esc(layer.title)} · ${layer.ids.filter(id=>byId.has(id)).length}组</summary>${note}<div class="group-pills">${pills}</div></details>`:`<section class="group-tier"><h2>${esc(layer.title)}</h2>${note}<div class="group-pills">${pills}</div></section>`});
 const extra=manifest.groups.filter(g=>!used.has(g.id));
 const all=`<button type="button" data-group="all"><span>全部去重来源身份</span><small>${esc(manifest.stocks.length)}只</small></button>`;
 const extras=extra.length?`<details class="group-details"><summary>其他原始分组 · ${extra.length}组</summary><div class="group-pills">${extra.map(button).join('')}</div></details>`:'';
 $('groups').className='group-layers';$('groups').innerHTML=`<section class="group-tier"><h2>来源入口</h2><p>先选来源范围；名单可能重叠，左侧按股票身份去重。</p><div class="group-pills">${all}${research28LayerSpec[0].ids.map(id=>button(byId.get(id))).filter(Boolean).join('')}</div></section>${buckets.slice(1).join('')}${extras}<p class="group-overlap-note">各组保持冻结原ID与原成员；组数不可相加为选股总数。阶段、复核和UNKNOWN标签只描述原数据状态。</p>`;
}
function setResearch28Group(next){
 if(next!=='all'&&!manifest.groups.some(g=>g.id===next))return;
 group=next;limit=100;clear();clearRelatedReports();
 for(const b of $('groups').querySelectorAll('[data-group]'))b.classList.toggle('active',b.dataset.group===group);
 $('selection').textContent='请选择本组股票；初筛不等买点';render();
}
window.initResearch28=async function(){
 try{
  const rev=new URLSearchParams(location.search).get('revision')||'r3';if(!['r1','r2','r3'].includes(rev))throw Error('未知28日修订，不回退到27日');
  const paths={r1:'research-2026-10-28.json',r2:'research-2026-10-28-r2.json',r3:'research-2026-10-28-r3.json'},hashes={"r1":"caa350f4ba5cd37bbf0dbf48cab1de19e11e6c49889c6c21e5a1c72216c07e94","r2":"caa350f4ba5cd37bbf0dbf48cab1de19e11e6c49889c6c21e5a1c72216c07e94","r3":"d4bf2aa2b05311dd44be5ef62ce7997af922cad59b400f63c91f318f082b65bf"};const res=await fetch(paths[rev],{cache:'no-store'});if(!res.ok)throw Error('28日观察资料尚未冻结');const bytes=await res.arrayBuffer();const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');if(digest!==hashes[rev])throw Error('28日冻结清单SHA不匹配，已阻止显示');
  manifest=JSON.parse(new TextDecoder().decode(bytes));if(manifest.research_date!=='2026-10-28'||manifest.chart_source_date!=='2026-10-27')throw Error('观察/行情日期合同不符');
  $('content').hidden=false;$('withCharts').checked=false;if($('scopeDisclosure'))$('scopeDisclosure').open=false;document.body?.classList.add('plan28');if($('balanceObservation'))$('balanceObservation').hidden=rev!=='r3';const requestedGroup=new URLSearchParams(location.search).get('group');if(requestedGroup){const requestedMeta=manifest.groups.find(g=>g.id===requestedGroup);if(!requestedMeta||!manifest.stocks.some(s=>Array.isArray(s.sources)&&s.sources.includes(requestedGroup)))throw Error('请求的28日原始分组不在冻结清单中；未显示错误分组')}group=requestedGroup||(rev==='r3'?'original94':'all');
  const batchDetail='观察计划日2026-10-28；全部行情与指标截至2026-10-27收盘，不是28日实时。5073正常域已计算，489域外未准入；原公式94只完整保留（低额10只不删），另429只仅金额/阳线初筛，18只图审样本：17只查看D26 180根图并核对D27当日数据；1只仅核近7根与D27、完整图未审；0完美确认，4失守关键K低、13二次恢复、1近似但有反证，并非买单。';
  let fullBatchDetail=batchDetail;if(rev==='r3')fullBatchDetail+=' 本页是局部补审，不是最终全A选股；5073只目前仅原式和基础扫描完成，完整结构普查进行中。域外151待修、338归档未准入，不当作未选。 本版纠正：突破关键K可能是启动观察，不一律当追高；112为429内重分类，6图实审、0完美确认。来源组可重叠，左侧按股票身份去重，分组人数不相加。';
  $('batchNoticeDetail').textContent=fullBatchDetail;$('batchNoticeDetail').hidden=false;
  document.querySelector('.notice').textContent='研究日 2026-10-28；行情与指标截至 2026-10-27 收盘（不是28日实时）。原公式94与金额/阳线初筛429分开；突破112是429内重分类。分组可能重叠，股票按身份去重。';
  $('status').textContent=`${manifest.stocks.length}个去重原式/结构来源身份；${manifest.stocks.filter(s=>s.details.length).length}只已绑定图。完整结构、公司事件和成交可得性仍需复核。`;
  $('revisions').innerHTML='<a href="daily.html?date=2026-10-28&revision=r3">r3 突破结构更新</a> · <a href="daily.html?date=2026-10-28&revision=r2">r2 原发布历史</a> · <a href="archive/2026-10-28/breakout-r3/breakout112-local.html">112突破观察 · 6真实图审</a> · <a href="daily.html?date=2026-10-27">27日历史归档</a> · <a href="perfect10.html">十张完美图 · 常驻学习检查</a> · <a href="archive/2026-10-28/r3/UNKNOWN_OUTSIDE489.json" target="_blank" rel="noopener">489域外未准入清单</a>';
  $('scopes').innerHTML=manifest.groups.map(g=>`<article class="card"><h2>${esc(g.title)} · ${g.count}</h2><p>${esc(g.scope)}</p><p class="muted">${esc(g.batch)}</p></article>`).join('');
  renderResearch28Groups();for(const b of $('groups').querySelectorAll('[data-group]'))b.onclick=()=>setResearch28Group(b.dataset.group);for(const b of $('groups').querySelectorAll('[data-group]'))b.classList.toggle('active',b.dataset.group===group);
  $('search').oninput=()=>{limit=100;clear();clearRelatedReports();$('selection').textContent='请选择搜索结果';render()};$('withCharts').onchange=()=>{limit=100;clear();clearRelatedReports();$('selection').textContent='请选择股票';render()};$('more').onclick=()=>{limit+=100;render()};render();
  if(location.hash)select(decodeURIComponent(location.hash.slice(1)));else if(rev==='r3'&&!requestedGroup){const first=manifest.stocks.find(s=>s.sources.includes('original94')&&s.details.length);if(first)select(first.symbol);$('status').textContent+=' 默认展示原式有图股（代码顺序，不是推荐排名）；点左侧股票即可同页看图。';}else if(requestedGroup){const meta=manifest.groups.find(g=>g.id===requestedGroup);$('status').textContent+=` 直达原始分组：${esc(meta.title)}；左侧显示组内名单（包含无图记录）。`; }
 }catch(e){window.OpeningObservation?.clear('观察清单不可用，未请求开盘观察。');clearRelatedReports('观察清单不可用，未请求相关研报。');$('content').hidden=true;$('error').textContent=e.message}
};

window.research28Summary=s=>{const q=s.screening||{},v=s.visual_review,o=s.original_formula;return `${s.breakout_review?`<div class="notice"><strong>${esc(s.breakout_stage_label)}</strong><p>${esc(s.breakout_visual?.conclusion||'完整图未审，仅阶段事实；不是买点确认')}</p><p>${esc(s.breakout_visual?.support||'')}</p><p>反证：${esc(s.breakout_visual?.counter_evidence||'回撤/承接完整路径、公司事件和可成交性待核')}</p><p>关键K ${esc(s.breakout_review.key_date)} · 高 ${esc(s.breakout_review.key_high)} / 实体底 ${esc(s.breakout_review.key_body_bottom)} / 低 ${esc(s.breakout_review.key_low)}；D27收 ${esc(s.breakout_review.D27_close)}；仅同源研究坐标。</p><a href="archive/2026-10-28/breakout-r3/breakout112-local.html#${encodeURIComponent(s.symbol)}">查看本股突破阶段与真实图证据</a></div>`:''}<div class="notice"><strong>${esc(v?.classification||(s.breakout_review?'旧批次标签仅供追溯；当前请看上方突破研究':q.structure_stage)||'原式名单；结构待核')}</strong><p>${esc(v?.reason||'尚无本轮逐图结论，不把门初筛当完整结构。')}</p><p>27日收盘 ${esc(q.raw_close)} · 开盘 ${esc(q.raw_open)} · 成交额 ${esc(q.raw_amount_yuan)}元；28日无实时数据。</p>${o?`<p><strong>原公式 ${esc(o.level)}</strong> · ${esc(o.trigger_branches.join(' / '))} · 金额≥1亿 ${esc(o.amount_ge_1e8)} · 买卖同现 ${esc(o.buy_sell_same)} · ST ${esc(o.ST_current_name)}；金额门不删原触发。</p>`:''}<p>原式一级 ${esc(q.original_primary)} / 二级 ${esc(q.original_secondary)} · ${esc(q.original_true_branches||'无已标触发分支')}；金额筛选与原公式独立。</p><p>关键K锚 ${esc(q.main_anchor_date)} · 实体底 ${esc(q.key_body_low)} / 最低 ${esc(q.key_low)} / 高点 ${esc(q.key_high)}；仅研究坐标，非可执行价认证。</p>${v?`<p>图审证据：${esc(v.chart_review)}，图源截至 ${esc(v.chart_through)}；完美结构确认：${esc(v.perfect_pattern_confirmed)}</p>`:''}</div>`};
