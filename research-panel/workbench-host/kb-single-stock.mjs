import {loadProjection} from './dot/src/projection-view.mjs';
import {actionPresentation,signalSummary,signalExplanations,HOLD_ITEMS,HOLD_REASONS} from './kb-signal-view.mjs';
import {installKbOverlay} from './kb-chart-overlay.mjs';

const $=id=>document.getElementById(id);
const node=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n};
const sha64=s=>typeof s==='string'&&/^[a-f0-9]{64}$/.test(s);
const iso=value=>String(value).replace(/^(\d{4})(\d{2})(\d{2})$/,'$1-$2-$3');
const label=(v,flag=false)=>v===null||v===undefined?'待确认':v===true||flag&&v===1?'是':v===false||flag&&v===0?'否':String(v);
async function readBoundGzip(ref,signal){
  const url=new URL(ref.url,location.origin);
  if(url.origin!==location.origin||!sha64(ref.sha256)||ref.encoding!=='gzip'||!Number.isSafeInteger(ref.bytes)||ref.bytes<1||ref.bytes>8*1024*1024)throw Error('单股数据身份无效');
  const response=await fetch(url,{signal,credentials:'same-origin',redirect:'error',cache:'no-store'});
  if(!response.ok)throw Error('单股数据读取失败');
  const data=new Uint8Array(await response.arrayBuffer());if(data.length!==ref.bytes)throw Error('单股数据长度不符');
  const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',data))].map(v=>v.toString(16).padStart(2,'0')).join('');if(hash!==ref.sha256)throw Error('单股数据校验失败');
  const plain=await new Response(new Blob([data]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer();
  if(plain.byteLength!==ref.decoded_bytes||plain.byteLength>8*1024*1024)throw Error('单股数据解压长度不符');
  return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(plain));
}

export function installSingleResearch({loadDetails=()=>{}}={}){
  const host=$('kbSingleResearch'),body=$('kbSingleBody'),status=$('kbSingleStatus'),frame=$('kbSingleChart'),select=$('kbSingleDate');
  const stocks={'002865.SZ':'钧达股份','301048.SZ':'金鹰重工'};
  let day=null,active=null,request=null,serial=0,observer=null,overlayCleanup=null,symbol='002865.SZ';
  const clear=()=>{++serial;request?.abort();request=null;observer?.disconnect();observer=null;overlayCleanup?.();overlayCleanup=null;active=null;frame.src='about:blank';body.hidden=true;for(const id of ['kbSingleScore','kbSingleActions','kbSingleActionReasons','kbSingleChips','kbSingleGroups','kbSingleHistory','kbSingleCompany','kbSingleFinancial','kbSingleSignalReasons'])$(id)?.replaceChildren();select.value='';document.body.classList.remove('kb-single-focus');window.RelatedReports?.clear();if($('relatedReports'))$('relatedReports').hidden=true;};
  const isCurrent=(mine,bound)=>mine===serial&&day===bound;
  function paint(date){
    if(!active)return;const row=active.byDate.get(Number(date));if(!row){$('kbSingleDateStatus').textContent='该日期没有已绑定交易日，不使用临近日替代。';return}
    select.value=iso(row.trade_date);select.removeAttribute('aria-invalid');$('kbSingleDateStatus').textContent='交易日 '+iso(row.trade_date)+' · 单股数据截至 '+day.source_date;$('kbSingleSelected').textContent=iso(row.trade_date);
    const action=actionPresentation(row.action,active.meta.action_contract_sha256),actions=$('kbSingleActions');actions.replaceChildren();
    for(const [context,value] of [['无持仓',action.flat],['有持仓',action.held]]){const line=node('p');line.append(node('span',context+'：'),node('strong',value));actions.append(line)}
    $('kbSingleActionReasons').replaceChildren(...action.reasons.map(text=>node('p',text)));
    const result=signalSummary(active.view.fields,row.kb,row.original,row.supplemental,row.yidong),chips=$('kbSingleChips');chips.replaceChildren();
    for(const item of result.chips){const chip=node('span',item.label);chip.className='kb-chip'+(item.source==='原式'?' kb-old':'');chip.dataset.signal=item.key;chips.append(chip)}
    if(!result.chips.length)chips.append(node('span','当日无已确认命中信号'));
    const unknown=$('kbSingleUnknown');unknown.hidden=!result.unknown.length;$('kbSingleUnknownSummary').textContent='信号待核';
    $('kbSingleUnknownItems').replaceChildren(...result.unknown.map(item=>node('p',item.label+'：'+item.reason)));
    const volumeRatio=row.diagnostics?.volume_vs_previous,volume5=row.diagnostics?.volume_vs_previous_5_mean;
    $('kbSingleVolume').textContent=`成交量较昨量：${Number.isFinite(volumeRatio)?volumeRatio.toFixed(2)+' 倍':'待核'} · 较前5日均量：${Number.isFinite(volume5)?volume5.toFixed(2)+' 倍':'待核'}（比较基准不同）`;
    $('kbSingleSignalReasons').replaceChildren(...signalExplanations(row,active.view.signal_component_facts).map(text=>node('p',text)));
    const score=row.hold_score,scoreText=$('kbSingleScore'),scoreItems=$('kbSingleScoreItems');scoreItems.replaceChildren();
    if(!score){scoreText.textContent='持股评分：数据待核';}
    else{
      const missing=HOLD_ITEMS.filter(([key])=>score[key]===null).length;
      scoreText.textContent=score.kb_hold_score===null?`持股评分：已确认${score.kb_hold_score_min}分 / 总分待核（${score.kb_hold_score_min}～${score.kb_hold_score_max}/5）`:`持股评分：${score.kb_hold_score}/5`;
      scoreItems.append(node('p',`评分分项 · ${missing} 项待核`));
      for(const [key,title] of HOLD_ITEMS){const value=score[key],reason=score[key+'_reason'];scoreItems.append(node('p',title+'：'+(value===null?'待核 · '+(HOLD_REASONS[reason]??'来源待核'):value?'1分':'0分')))}
      scoreItems.append(node('p',`KB指标：BBI ${label(score.kb_hold_bbi)} · K ${label(score.kb_hold_k)} · D ${label(score.kb_hold_d)} · J ${label(row.kb.kb_b1_j)}；原 ref_hold_score 保留原身份。`));
    }
    const groups=$('kbSingleGroups');groups.replaceChildren();
    for(const group of [...new Set(active.view.fields.map(f=>f.group))]){
      const section=node('section');section.className='kb-group';const fields=active.view.fields.filter(f=>f.group===group);section.append(node('h4',group+' · '+fields.length+'项'));
      const list=node('dl');for(const field of fields){const dt=node('dt',field.name==='kb_macd_veto'?'MACD日线风险条件':field.name==='kb_didi'?'滴滴·日K双阴阶梯':field.description);dt.title=field.name;const value=row.kb[field.name],text=value==null&&field.status==='SOURCE_IMPLEMENTATION_DEFECT'?'待核：'+field.unknown_reason:label(value);const dd=node('dd',text);dd.title=field.name;list.append(dt,dd)}section.append(list);groups.append(section);
    }
  }
  function selectDate(date,{move=true}={}){
    if(!active)return;const row=active.byDate.get(Number(date));if(!row){select.setAttribute('aria-invalid','true');$('kbSingleDateStatus').textContent=iso(date)+' 无已绑定交易数据，不自动替换日期。';return}
    const w=frame.contentWindow,s=w?.RESEARCH_PANEL_STATE,i=s?.rows?.findIndex(r=>Number(r.trade_date)===Number(date));
    if(move&&i>=0&&w.setOriginalWindow){const count=Math.min(120,s.rows.length);w.setOriginalWindow(count,i===s.rows.length-1?s.rows.length:Math.min(s.rows.length,i+Math.floor(count*.7)));w.choose(i)}
    paint(row.trade_date);w?.paint?.();
  }
  function bindFrame(mine,bound){
    const w=frame.contentWindow,doc=frame.contentDocument;if(!w||!doc?.documentElement)return;
    observer?.disconnect();
    const ready=()=>{if(!isCurrent(mine,bound)){observer?.disconnect();return}const state=w.RESEARCH_PANEL_STATE;if(doc.documentElement.dataset.loaded!==symbol||state?.symbol!==symbol||state.rows?.length!==active?.view.rows.length)return;
      observer?.disconnect();observer=null;
      if(!doc.getElementById('kb-single-chart-focus')){const style=doc.createElement('style');style.id='kb-single-chart-focus';style.textContent='body{margin:0!important;background:#07131e!important}header,aside,.toolbar,.charthead .controls,#selected-date,.stats,.tables,details,#status,.foot,#chart-caption{display:none!important}main{display:block!important;max-width:none!important;margin:0!important;min-height:0!important}article{padding:12px!important}.chartbox{border:0!important;padding:0!important}.charthead{margin:0 0 4px!important}canvas{height:405px!important}';doc.head.appendChild(style);w.dispatchEvent(new w.Event('resize'));}
      overlayCleanup?.();overlayCleanup=installKbOverlay(frame,active.byDate);
      const canvas=doc.getElementById('chart');let down=null;
      canvas.addEventListener('pointerdown',event=>{down={x:event.clientX,y:event.clientY,id:event.pointerId}});
      canvas.addEventListener('pointerup',event=>{if(!down||down.id!==event.pointerId)return;const moved=Math.hypot(event.clientX-down.x,event.clientY-down.y);down=null;if(moved>5)return;const s=w.RESEARCH_PANEL_STATE,g=s.geometry;if(!g||!s.visible.length)return;const x=event.clientX-canvas.getBoundingClientRect().left,i=Math.max(0,Math.min(s.visible.length-1,Math.floor((x-g.L)/g.step)));const index=s.offset+i;w.choose(index);paint(s.rows[index].trade_date);w.paint()});
      w.setOriginalWindow?.(Math.min(120,state.rows.length),state.rows.length);w.choose?.(state.rows.length-1);w.paint?.();paint(state.rows.at(-1).trade_date);
      status.textContent=`来源 ${day.source_date} · 观察 ${day.observation_date} · ${stocks[symbol]}单股研究`;
    };
    observer=new MutationObserver(ready);observer.observe(doc.documentElement,{attributes:true,attributeFilter:['data-loaded']});ready();
  }
  async function open(){
    if(!day)return;clear();const bound=day,mine=serial,requested=symbol;request=new AbortController();const signal=request.signal;
    $('kbSingleName').textContent=stocks[requested];$('kbSingleCode').textContent=requested;frame.title=stocks[requested]+'原式研究图';
    document.body.classList.add('kb-single-focus');body.hidden=false;status.textContent='正在核对单股数据和原式图…';
    try{
      const url='/api/v4/research/workbench/days/'+bound.source_date+'/single-research/'+requested+'?'+new URLSearchParams({revision:bound.generation});
      const response=await fetch(url,{signal,credentials:'same-origin',redirect:'error',cache:'no-store'});if(!response.ok)throw Error('单股候选尚未接入');const meta=await response.json();
      if(!isCurrent(mine,bound))return;
      const poolMember=bound.rows.some(row=>row.symbol===requested);
      if(meta.status!=='READY_FOR_RESEARCH_REVIEW'||meta.source_date!==bound.source_date||meta.observation_date!==bound.observation_date||meta.symbol!==requested||meta.generation!==bound.generation||meta.input_sha256!==bound.input_sha256||meta.numeric_manifest?.sha256!==bound.numeric_manifest?.sha256||meta.numeric_manifest?.path!==bound.numeric_manifest?.path||meta.candidate_pool_member!==poolMember||meta.fields_count!==57||meta.historical_PIT!==false||meta.RESEARCH_ONLY!==true||['production_allowed','buy_gate_updated','orders_sent'].some(k=>meta[k]!==false)||!sha64(meta.candidate_generation))throw Error('单股来源身份冲突');
      const projectionRef={...meta.assets.projection,projection_url:meta.assets.projection.url};
      const [view,projection,history,company]=await Promise.all([readBoundGzip(meta.assets.kb,signal),loadProjection(projectionRef,{symbol:meta.symbol,source_date:meta.source_date,generation:meta.generation,input_sha256:meta.input_sha256},{origin:location.origin,signal}),readBoundGzip(meta.assets.history,signal),readBoundGzip(meta.assets.company,signal)]);
      if(!isCurrent(mine,bound))return;
      if(view.symbol!==meta.symbol||view.source_date!==meta.source_date||view.observation_date!==meta.observation_date||view.source_generation!==meta.generation||view.source_input_sha256!==meta.input_sha256||view.candidate_generation!==meta.candidate_generation||view.source_gate!=='PASS_RELOCATED_SOURCE_GATE'||view.candidate_pool_member!==poolMember||!sha64(meta.hold_score_contract_sha256)||!sha64(meta.hold_score_engine_sha256)||!sha64(meta.supplemental_contract_sha256)||!sha64(meta.action_contract_sha256)||!sha64(meta.yidong_contract_sha256)||view.hold_score_contract_sha256!==meta.hold_score_contract_sha256||view.hold_score_engine_sha256!==meta.hold_score_engine_sha256||view.supplemental_contract_sha256!==meta.supplemental_contract_sha256||view.action_contract_sha256!==meta.action_contract_sha256||view.yidong_contract_sha256!==meta.yidong_contract_sha256||!meta.display_projection||view.concept_snapshot?.source_sha256!==meta.display_projection.f10_source_sha256||view.concept_snapshot?.kb_concepts!==meta.display_projection.kb_concepts||view.concept_snapshot?.kb_concept_count!==meta.display_projection.kb_concept_count||!sha64(meta.signal_component_facts_sha256)||view.signal_component_facts_sha256!==meta.signal_component_facts_sha256||!view.field_inventory||!meta.field_inventory||JSON.stringify(Object.entries(view.field_inventory).sort())!==JSON.stringify(Object.entries(meta.field_inventory).sort())||!Array.isArray(view.fields)||view.fields.length!==meta.fields_count||!Array.isArray(view.rows)||view.rows.length!==meta.rows||projection.data.rows.length!==meta.rows)throw Error('单股字段或图形身份冲突');
      for(const value of [history,company])if(value.symbol!==meta.symbol||value.data_date!==bound.source_date.replaceAll('-','')||value.source_generation!==meta.generation||value.input_sha256!==meta.input_sha256||value.numeric_manifest?.sha256!==meta.numeric_manifest.sha256||value.source_candidate?.sha256!==meta.reused_candidate_sha256||value.historical_PIT!==false||value.RESEARCH_ONLY!==true||['production_allowed','buy_gate_updated','orders_sent'].some(k=>value[k]!==false))throw Error('单股研究资料身份冲突');
      if(company.f10?.concepts?.map(c=>c.name).join('、')!==view.concept_snapshot.kb_concepts||company.f10?.captured_at!==view.concept_snapshot.captured_at)throw Error('单股概念来源身份冲突');
      const byDate=new Map;for(let i=0;i<view.rows.length;i++){const row=view.rows[i];if(!Number.isInteger(row.trade_date)||byDate.has(row.trade_date)||!row.kb||!row.original||!row.hold_score||!row.supplemental||row.trade_date!==projection.data.rows[i].trade_date||row.yidong?.kb_yidong_rule_sha256!==meta.yidong_contract_sha256)throw Error('单股日期或评分数据无效');actionPresentation(row.action,meta.action_contract_sha256);byDate.set(row.trade_date,row)}
      if(!byDate.has(20261030))throw Error('单股目标日期缺失');
      active={view,projection,byDate,meta,assets:{history,company}};select.min=iso(view.rows[0].trade_date);select.max=iso(view.rows.at(-1).trade_date);paint(view.rows.at(-1).trade_date);
      loadDetails(bound,meta,signal,{history,company});
      const html=new URL(meta.assets.html.url,location.origin);if(html.origin!==location.origin||html.searchParams.get('sha256')!==meta.assets.html.sha256||!sha64(meta.assets.html.sha256))throw Error('单股原图身份冲突');
      frame.onload=()=>bindFrame(mine,bound);frame.src=html.href;
      status.textContent='原式图载入中 · 来源10/30 / 观察11/2';
    }catch(error){if(isCurrent(mine,bound)&&error.name!=='AbortError'){status.textContent='单股研究暂不可用 · '+error.message;frame.src='about:blank'}}
  }
  const openSymbol=value=>{if(!Object.hasOwn(stocks,value)||!day)return;symbol=value;open()};
  $('kbSingleOpen').onclick=()=>openSymbol('002865.SZ');$('kbSingleGold').onclick=()=>openSymbol('301048.SZ');$('kbSingleBack').onclick=()=>{clear();status.textContent='选择股票查看单股研究'};
  select.onchange=()=>selectDate(select.value.replaceAll('-',''));
  $('kbSingleLatest').onclick=()=>{if(active)selectDate(active.view.rows.at(-1).trade_date)};
  for(const button of host.querySelectorAll('[data-kb-window]'))button.onclick=()=>{const w=frame.contentWindow,s=w?.RESEARCH_PANEL_STATE;if(!active||!s?.rows?.length)return;const value=button.dataset.kbWindow==='all'?s.rows.length:Number(button.dataset.kbWindow),count=Math.min(value,s.rows.length),chosen=Number(select.value.replaceAll('-','')),i=s.rows.findIndex(row=>row.trade_date===chosen),end=i<0||i===s.rows.length-1?s.rows.length:Math.min(s.rows.length,i+Math.floor(count*.7));w.setOriginalWindow?.(count,end);if(i>=0)w.choose?.(i);w.paint?.()};
  return {openSymbol,clear,refresh(){if(active&&day&&!request?.signal.aborted)loadDetails(day,active.meta,request.signal,active.assets)},bindDay(value){const same=day?.source_date===value?.source_date,focused=document.body.classList.contains('kb-single-focus');day=value;host.hidden=!(value?.source_date==='2026-10-30'&&value?.observation_date==='2026-11-02');if(!host.hidden&&(!same||focused)){if(!same){const wanted=new URLSearchParams(location.search).get('symbol');symbol=Object.hasOwn(stocks,wanted)?wanted:'002865.SZ'}open()}},unbindDay(){clear();day=null;host.hidden=true}};
}
export function financialLines(official={},f10={}){
  const report=f10.financials??{},period=report.report_period??'报告期待核';
  const money=value=>typeof value==='string'&&/^-?\d+(?:\.\d+)?(?:亿|万|元)$/.test(value)?(value.endsWith('元')?value:value+'元'):null;
  const value=(number,raw,label,fallback)=>Number.isFinite(number)?`${label}：${(number/100000000).toFixed(2)}亿元`:
    money(raw)?`${fallback}（TDX F10 · 报告期 ${period}）：${money(raw)}`:`${label}：待核`;
  return [value(official.latest_revenue,report.revenue_text,'营业收入','营业总收入'),
    value(official.latest_net_profit_parent,report.net_profit_text,'归母净利润','净利润'),
    value(official.operating_cash_flow,null,'经营现金流净额','经营现金流净额')];
}

export function financialDisclosureText(official={},f10={},sources={}){
  const disclosed=official.evidence_status==='OFFICIAL_FILING'&&sources.official_quarterly?.available_date===official.latest_disclosed_at;
  return `${official.latest_period_kind??'报告资料待核'} · 报告期 ${official.latest_report_period??'待核'} · 披露 ${disclosed?official.latest_disclosed_at:'待核'}${disclosed?'':` · F10更新 ${f10.finance_updated_date??'待核'}`}`;
}

export function visibleSingleHistoryGroups(groups){
  if(!Array.isArray(groups))throw Error('单股历史统计缺失');
  return groups.filter(group=>!['original_b1','original_b2','original_b3'].includes(group.group_id));
}
