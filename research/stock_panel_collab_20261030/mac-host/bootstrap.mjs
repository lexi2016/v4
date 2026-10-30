import {makeStockBridge} from './stock/stock-bridge.mjs';
import {loadProjection} from './dot/src/projection-view.mjs';
import {setCompanyContext} from './company-local.mjs';
import {completionAction} from './completion-action.mjs';
import {renderClassification} from './classification-local.mjs';
const el=id=>document.getElementById(id),add=(host,tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;host.append(n);return n};
const old=document.querySelector('#interactiveChart .interactive-scroll');if(old)old.hidden=true;
const navigation=document.querySelector('#interactiveChart .chart-nav');if(navigation)navigation.hidden=true;
const container=add(el('interactiveChart'),'div');container.id='macOriginalRenderer';
const stat=add(el('interactivePanel'),'section');stat.className='panel';stat.id='macHistoricalStatistics';
let context=null,current=null,contextSerial=0,completionCallback=null,contextReply=null,activeDay=null,moduleEvents=null,moduleSerial=0,preservedChart=null;
const bridge=makeStockBridge({origin:location.origin,basePath:'/api/v4/research/a-share',fetcher:fetch,loadProjection,container,eventTarget:window});
const original=bridge.OriginalFullChart;
window.OriginalFullChart={...original,clear(){original.clear();current=null;context=null;++contextSerial;setCompanyContext(null);stat.replaceChildren();el('companySummary').replaceChildren();el('companyMetrics').replaceChildren();el('companyEvidence').replaceChildren();el('marketCards').textContent='跨市场来源尚未与所选日期绑定';}};
const frame=original.bind();frame.style.height="460px";
function sourceContext(day,force=false){
  const mine=++contextSerial;
  if(!force&&contextReply?.source_date===day.source_date&&contextReply?.observation_date===day.observation_date&&contextReply?.generation===day.generation&&contextReply?.input_sha256===day.input_sha256){paintContext();return;}
  const sameIdentity=(a,b)=>a&&b&&['source_date','observation_date','generation','input_sha256'].every(k=>a[k]===b[k]);
  const isCurrent=()=>mine===contextSerial&&sameIdentity(activeDay||context,day);
  const invalidate=reason=>{if(!isCurrent())return;contextReply=null;const host=el('marketCards');host.replaceChildren();host.textContent='跨市场来源校验失败 · CANNOT_CONFIRM：'+reason;};
  return fetch('/api/v4/research/workbench/days/'+day.source_date+'/context?'+new URLSearchParams({revision:day.generation}),{method:'GET',credentials:'same-origin',redirect:'error',cache:'no-store'}).then(r=>{if(!r.ok)throw Error('CONTEXT_READ_FAILED_HTTP_'+r.status);return r.json()}).then(v=>{if(!isCurrent())return;if(!sameIdentity(v,day)){invalidate('SOURCE_CONTEXT_IDENTITY_CONFLICT');return;}contextReply=v;paintContext()}).catch(error=>invalidate(error.message));
}
function paintContext(){
  const identity=activeDay||context;if(!contextReply||!identity||contextReply.source_date!==identity.source_date||contextReply.observation_date!==identity.observation_date||contextReply.generation!==identity.generation||contextReply.input_sha256!==identity.input_sha256)return;const host=el('marketCards');host.replaceChildren();
  for(const [market,value]of Object.entries(contextReply.markets)){const card=add(host,'div');card.className='market-card';add(card,'strong',({US:'美国',JP:'日本',KR:'韩国'})[market]);add(card,'span',value.summary);const note=add(card,'small',value.status==='UNKNOWN'?'来源缺口 · UNKNOWN':`源 ${value.source_asof??'未知'} · 实读 ${value.recorded_at??'未知'}；${value.limitation??''}`);note.title=note.textContent;}
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
frame.addEventListener('load',()=>{if(!current||frame.hidden)return;const w=frame.contentWindow;if(!w?.RESEARCH_PANEL_STATE)return;const child=frame.contentDocument;if(!child.getElementById('mac-original-focus-style')){const style=child.createElement('style');style.id='mac-original-focus-style';style.textContent='body{margin:0!important;background:#07131e!important}header,aside,.toolbar,.charthead .controls,#selected-date,.stats,.tables,details,#status,.foot,#chart-caption{display:none!important}main{display:block!important;max-width:none!important;margin:0!important;min-height:0!important}article{padding:12px!important}.chartbox{border:0!important;padding:0!important}.charthead{margin:0 0 4px!important}canvas{height:405px!important}';child.head.appendChild(style);w.dispatchEvent(new w.Event('resize'));w.paint();}if(preservedChart&&preservedChart.symbol===current.context.symbol&&preservedChart.source_date===current.context.source_date&&preservedChart.generation===current.context.generation){w.setOriginalWindow(preservedChart.count,preservedChart.start+preservedChart.count);w.choose(preservedChart.selected);w.paint();preservedChart=null;}const select=el('fullDateSelect');select.replaceChildren();for(const r of current.projection.data.rows){const option=add(select,'option',String(r.trade_date));option.value=String(r.trade_date)}select.value=String(current.projection.data.rows.at(-1).trade_date);select.onchange=()=>{const s=w.RESEARCH_PANEL_STATE,i=s.rows.findIndex(r=>String(r.trade_date)===select.value);if(i<0)return;w.setOriginalWindow(Math.min(120,s.rows.length),Math.min(s.rows.length,i+84));w.choose(i);w.paint()};});
window.StockPanelHost={
  async open(day,row,selectedGroup){
    const own=Object.entries(row.group_states).filter(([,v])=>v==='TRUE').map(([g])=>g);
    const group=own.includes(selectedGroup)?selectedGroup:own[0];
    context={source_date:day.source_date,observation_date:day.observation_date,symbol:row.symbol,generation:day.generation,input_sha256:day.input_sha256,group,horizon:'d2'};
    setCompanyContext(context);sourceContext(day);
    let coverage=el('macScopeCoverage');if(!coverage){coverage=document.createElement('p');coverage.id='macScopeCoverage';coverage.className='counts';document.querySelector('.source-note').append(coverage);}coverage.textContent=`当前已交付候选 ${day.scope_count} 条；原处理 ${day.original_processed_count} 条，未交付台账行不在本页展示。`;
    const bundle=await bridge.open(context,{render:true});current=bundle;context=bundle.context;el('fullCoverage').textContent=`${bundle.projection.data.rows.length}行原式51变量/22绘图 · 来源日${context.source_date} · 统计manifest ${bundle.numeric_manifest.sha256.slice(0,12)}`;showStatistics(bundle);return bundle;
  },
  paintContext,
  paintClassificationCoverage(day){let line=el('macClassificationCoverage');if(!line){line=document.createElement('p');line.id='macClassificationCoverage';line.className='counts';document.querySelector('.source-note').append(line);}const counts=day.classification_identity_counts??{};line.textContent='分类代码+名称 '+(counts.BOUND_EXACT_CODE_NAME??0)+'/'+day.scope_count+' · 冲突 '+(counts.IDENTITY_CONFLICT_NAME??0)+' · '+day.classification_status;},
  paintClassification(row,day){renderClassification(el('classificationSummary'),row,day)},
  paintCompanyReports(value){
    const target=el('companyEvidence'),box=add(target,'details');add(box,'summary','研报来源与缺口');
    if(!value.reports?.catalog?.length)add(box,'p','研报元数据未接入 · CANNOT_CONFIRM');
    for(const report of value.reports?.catalog??[]){const row=add(box,'p');add(row,'span',`${report.published_at??'日期未知'} · ${report.title??'标题缺失'} · ${report.full_text_status??report.evidence_status??'全文状态未知'} `);try{const url=new URL(report.report_url||report.metadata_source_url);if(url.protocol==='https:'&&!url.username&&!url.password){const a=add(row,'a',report.report_url?'原始报告入口':'元数据来源');a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';}}catch{add(row,'small','来源链接未接入');}}
    add(box,'p',value.reports?.stored_report?'有已存研报引用；文件可读性与事实验收需另核。':'未绑定已存研报；不把元数据当全文。');
  },
  paintWorkflow(contract){
    const labels={DEFERRED_USER:'用户后置',COMPLETED:'已完成（见回执）',PARTIAL:'部分交付',BLOCKED:'上游阻塞',MISSED:'漏过原时点',NOT_DUE:'未来节点',CANNOT_CONFIRM_NO_RECEIPT:'执行回执缺失',CANNOT_CONFIRM_BAD_RECEIPT:'回执校验失败'};
    for(const item of contract?.time_contract?.nodes??[]){const d=document.querySelector(`.timetable-item[data-node-id="${item.id}"]`);if(!d)continue;const host=d.querySelector('.node-materials');if(!host)continue;host.replaceChildren();add(host,'strong',labels[item.execution_status]??item.execution_status);if(item.recorded_at)add(host,'p','实际记录 '+item.recorded_at);if(item.source_asof)add(host,'p','来源时点 '+item.source_asof);for(const reason of item.missing??[])add(host,'p','缺口：'+reason);if(item.error)add(host,'p','错误：'+item.error);for(const material of item.materials??[]){try{const u=new URL(material.url,location.href);if(!['https:','http:'].includes(u.protocol)||u.username||u.password)continue;const a=add(host,'a',material.label??'来源材料');a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';}catch{add(host,'p','材料链接待核');}}}
  },
  preserveChart(){const s=frame.contentWindow?.RESEARCH_PANEL_STATE;if(context&&s?.view)preservedChart={symbol:context.symbol,source_date:context.source_date,generation:context.generation,...s.view,selected:s.selected};},
  unbindDay(){moduleEvents?.close();moduleEvents=null;++moduleSerial;activeDay=null;contextReply=null;++contextSerial;},
  bindDay(day){
    activeDay=day;this.paintClassificationCoverage(day);sourceContext(day,true);
    const key=day.source_date;if(moduleEvents?.key===key)return;
    moduleEvents?.close();const mine=++moduleSerial;let previous=null;
    moduleEvents=new EventSource('/api/v4/research/workbench/days/'+key+'/events');moduleEvents.key=key;
    moduleEvents.addEventListener('workbench_completed',event=>{try{const e=JSON.parse(event.data);if(mine!==moduleSerial||activeDay?.source_date!==key||e.source_date!==key||e.RESEARCH_ONLY!==true||['production_allowed','buy_gate_updated','orders_sent'].some(k=>e[k]!==false))return;
      const changed=Object.keys(e.modules??{}).filter(k=>previous?.[k]!==e.modules[k]);previous=e.modules;
      // Event payloads are invalidation hints. Only fresh GET responses may
      // replace content, so a delayed/replayed event cannot restore old data.
      if(changed.includes('context'))sourceContext(activeDay,true);
      completionCallback?.modules?.(changed,e);
    }catch{}});
  },
  installCompletion(callback){completionCallback=callback},
};
const events=new EventSource('/api/v4/research/events');
events.addEventListener('a_share_daily_completed',event=>{try{const e=JSON.parse(event.data),action=completionAction(context,e);if(action==='refresh')completionCallback?.refresh?.();else if(action==='source_changed'){window.OriginalFullChart.clear();completionCallback?.sourceChanged?.();}else if(action==='gap')el('projectionStatus').textContent='完成事件来源字段待核；当前已绑定版本未替换。';}catch{}});
window.addEventListener('pagehide',()=>{events.close();moduleEvents?.close();++moduleSerial;bridge.clear()},{once:true});
await import('./dot/shell/workbench.local.mjs');
