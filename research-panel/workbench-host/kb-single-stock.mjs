import {loadProjection} from './dot/src/projection-view.mjs';
import {signalSummary,HOLD_ITEMS,HOLD_REASONS} from './kb-signal-view.mjs';
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
  let day=null,active=null,request=null,serial=0,observer=null,overlayCleanup=null;
  const clear=()=>{++serial;request?.abort();request=null;observer?.disconnect();observer=null;overlayCleanup?.();overlayCleanup=null;active=null;frame.src='about:blank';body.hidden=true;document.body.classList.remove('kb-single-focus');};
  const isCurrent=(mine,bound)=>mine===serial&&day===bound;
  function paint(date){
    if(!active)return;const row=active.byDate.get(Number(date));if(!row){$('kbSingleDateStatus').textContent='该日期没有已绑定交易日，不使用临近日替代。';return}
    select.value=iso(row.trade_date);select.removeAttribute('aria-invalid');$('kbSingleDateStatus').textContent='交易日 '+iso(row.trade_date)+' · 单股数据截至 '+day.source_date;$('kbSingleSelected').textContent=iso(row.trade_date);
    const result=signalSummary(active.view.fields,row.kb,row.original,row.supplemental),chips=$('kbSingleChips');chips.replaceChildren();
    for(const item of result.chips){const chip=node('span',item.label);chip.className='kb-chip'+(item.source==='原式'?' kb-old':'');chip.dataset.signal=item.key;chips.append(chip)}
    if(!result.chips.length)chips.append(node('span','当日无已确认命中信号'));
    const unknown=$('kbSingleUnknown');unknown.hidden=!result.unknown.length;$('kbSingleUnknownSummary').textContent=`${result.unknown.length} 项待核`;
    $('kbSingleUnknownItems').replaceChildren(...result.unknown.map(item=>node('p',item.label+'：'+item.reason)));
    const volumeRatio=row.diagnostics?.volume_vs_previous,volume5=row.diagnostics?.volume_vs_previous_5_mean;
    $('kbSingleVolume').textContent=`成交量较昨量：${Number.isFinite(volumeRatio)?volumeRatio.toFixed(2)+' 倍':'待核'} · 较前5日均量：${Number.isFinite(volume5)?volume5.toFixed(2)+' 倍':'待核'}（比较基准不同）`;
    const score=row.hold_score,scoreText=$('kbSingleScore'),scoreItems=$('kbSingleScoreItems');scoreItems.replaceChildren();
    if(!score){scoreText.textContent='持有评分待核 · 评分数据未绑定';}
    else{
      const missing=HOLD_ITEMS.filter(([key])=>score[key]===null).length;
      scoreText.textContent=score.kb_hold_score===null?`持有评分：已确认 ${score.kb_hold_score_min} 分，范围 ${score.kb_hold_score_min}～${score.kb_hold_score_max}/5；另 ${missing} 项待核`:`持有评分：${score.kb_hold_score}/5`;
      for(const [key,title] of HOLD_ITEMS){const value=score[key],reason=score[key+'_reason'];scoreItems.append(node('p',title+'：'+(value===null?'待核 · '+(HOLD_REASONS[reason]??'来源待核'):value?'1分':'0分')))}
      scoreItems.append(node('p',`KB指标：BBI ${label(score.kb_hold_bbi)} · K ${label(score.kb_hold_k)} · D ${label(score.kb_hold_d)} · J ${label(row.kb.kb_b1_j)}；原 ref_hold_score 保留原身份。`));
    }
    const groups=$('kbSingleGroups');groups.replaceChildren();
    for(const group of [...new Set(active.view.fields.map(f=>f.group))]){
      const section=node('details');section.className='kb-group';const fields=active.view.fields.filter(f=>f.group===group);section.append(node('summary',group+' · '+fields.length+'项'));
      const list=node('dl');for(const field of fields){const dt=node('dt',field.description);dt.title=field.name;const value=row.kb[field.name],text=value==null&&field.status==='SOURCE_IMPLEMENTATION_DEFECT'?'待核：'+field.unknown_reason:label(value);const dd=node('dd',text);dd.title=field.name;list.append(dt,dd)}section.append(list);groups.append(section);
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
    const ready=()=>{if(!isCurrent(mine,bound)){observer?.disconnect();return}const state=w.RESEARCH_PANEL_STATE;if(doc.documentElement.dataset.loaded!=='002865.SZ'||state?.symbol!=='002865.SZ'||state.rows?.length!==active?.view.rows.length)return;
      observer?.disconnect();observer=null;
      if(!doc.getElementById('kb-single-chart-focus')){const style=doc.createElement('style');style.id='kb-single-chart-focus';style.textContent='body{margin:0!important;background:#07131e!important}header,aside,.toolbar,.charthead .controls,#selected-date,.stats,.tables,details,#status,.foot,#chart-caption{display:none!important}main{display:block!important;max-width:none!important;margin:0!important;min-height:0!important}article{padding:12px!important}.chartbox{border:0!important;padding:0!important}.charthead{margin:0 0 4px!important}canvas{height:405px!important}';doc.head.appendChild(style);w.dispatchEvent(new w.Event('resize'));}
      overlayCleanup?.();overlayCleanup=installKbOverlay(frame,active.byDate);
      const canvas=doc.getElementById('chart');let down=null;
      canvas.addEventListener('pointerdown',event=>{down={x:event.clientX,y:event.clientY,id:event.pointerId}});
      canvas.addEventListener('pointerup',event=>{if(!down||down.id!==event.pointerId)return;const moved=Math.hypot(event.clientX-down.x,event.clientY-down.y);down=null;if(moved>5)return;const s=w.RESEARCH_PANEL_STATE,g=s.geometry;if(!g||!s.visible.length)return;const x=event.clientX-canvas.getBoundingClientRect().left,i=Math.max(0,Math.min(s.visible.length-1,Math.floor((x-g.L)/g.step)));const index=s.offset+i;w.choose(index);paint(s.rows[index].trade_date);w.paint()});
      w.setOriginalWindow?.(Math.min(120,state.rows.length),state.rows.length);w.choose?.(state.rows.length-1);w.paint?.();paint(state.rows.at(-1).trade_date);
      status.textContent='来源 10/30 · 观察 11/2 · 单股研究，原候选名单未改变';
    };
    observer=new MutationObserver(ready);observer.observe(doc.documentElement,{attributes:true,attributeFilter:['data-loaded']});ready();
  }
  async function open(){
    if(!day)return;clear();const bound=day,mine=serial;request=new AbortController();const signal=request.signal;
    document.body.classList.add('kb-single-focus');body.hidden=false;status.textContent='正在核对单股数据和原式图…';
    try{
      const url='/api/v4/research/workbench/days/'+bound.source_date+'/single-research/002865.SZ?'+new URLSearchParams({revision:bound.generation});
      const response=await fetch(url,{signal,credentials:'same-origin',redirect:'error',cache:'no-store'});if(!response.ok)throw Error('单股候选尚未接入');const meta=await response.json();
      if(!isCurrent(mine,bound))return;
      if(meta.status!=='READY_FOR_RESEARCH_REVIEW'||meta.source_date!==bound.source_date||meta.observation_date!==bound.observation_date||meta.symbol!=='002865.SZ'||meta.generation!==bound.generation||meta.input_sha256!==bound.input_sha256||meta.numeric_manifest?.sha256!==bound.numeric_manifest?.sha256||meta.numeric_manifest?.path!==bound.numeric_manifest?.path||meta.candidate_pool_member!==false||meta.fields_count!==57||meta.historical_PIT!==false||meta.RESEARCH_ONLY!==true||['production_allowed','buy_gate_updated','orders_sent'].some(k=>meta[k]!==false)||!sha64(meta.candidate_generation))throw Error('单股来源身份冲突');
      const projectionRef={...meta.assets.projection,projection_url:meta.assets.projection.url};
      const [view,projection]=await Promise.all([readBoundGzip(meta.assets.kb,signal),loadProjection(projectionRef,{symbol:meta.symbol,source_date:meta.source_date,generation:meta.generation,input_sha256:meta.input_sha256},{origin:location.origin,signal})]);
      if(!isCurrent(mine,bound))return;
      if(view.symbol!==meta.symbol||view.source_date!==meta.source_date||view.observation_date!==meta.observation_date||view.source_generation!==meta.generation||view.source_input_sha256!==meta.input_sha256||view.candidate_generation!==meta.candidate_generation||view.source_gate!=='PASS_RELOCATED_SOURCE_GATE'||view.candidate_pool_member!==false||!sha64(meta.hold_score_contract_sha256)||!sha64(meta.hold_score_engine_sha256)||!sha64(meta.supplemental_contract_sha256)||view.hold_score_contract_sha256!==meta.hold_score_contract_sha256||view.hold_score_engine_sha256!==meta.hold_score_engine_sha256||view.supplemental_contract_sha256!==meta.supplemental_contract_sha256||!view.field_inventory||!meta.field_inventory||JSON.stringify(Object.entries(view.field_inventory).sort())!==JSON.stringify(Object.entries(meta.field_inventory).sort())||!Array.isArray(view.fields)||view.fields.length!==meta.fields_count||!Array.isArray(view.rows)||view.rows.length!==meta.rows||projection.data.rows.length!==meta.rows)throw Error('单股字段或图形身份冲突');
      const byDate=new Map;for(let i=0;i<view.rows.length;i++){const row=view.rows[i];if(!Number.isInteger(row.trade_date)||byDate.has(row.trade_date)||!row.kb||!row.original||!row.hold_score||!row.supplemental||row.trade_date!==projection.data.rows[i].trade_date)throw Error('单股日期或评分数据无效');byDate.set(row.trade_date,row)}
      if(!byDate.has(20261030))throw Error('单股目标日期缺失');
      active={view,projection,byDate};select.min=iso(view.rows[0].trade_date);select.max=iso(view.rows.at(-1).trade_date);paint(view.rows.at(-1).trade_date);
      loadDetails(bound,meta,signal);
      const html=new URL(meta.assets.html.url,location.origin);if(html.origin!==location.origin||html.searchParams.get('sha256')!==meta.assets.html.sha256||!sha64(meta.assets.html.sha256))throw Error('单股原图身份冲突');
      frame.onload=()=>bindFrame(mine,bound);frame.src=html.href;
      status.textContent='原式图载入中 · 来源10/30 / 观察11/2';
    }catch(error){if(isCurrent(mine,bound)&&error.name!=='AbortError'){status.textContent='单股研究暂不可用 · '+error.message;frame.src='about:blank'}}
  }
  $('kbSingleOpen').onclick=open;$('kbSingleBack').onclick=()=>{clear();status.textContent='点击查看钧达单股研究'};
  select.onchange=()=>selectDate(select.value.replaceAll('-',''));
  $('kbSingleLatest').onclick=()=>{if(active)selectDate(active.view.rows.at(-1).trade_date)};
  for(const button of host.querySelectorAll('[data-kb-window]'))button.onclick=()=>{const w=frame.contentWindow,s=w?.RESEARCH_PANEL_STATE;if(!active||!s?.rows?.length)return;const value=button.dataset.kbWindow==='all'?s.rows.length:Number(button.dataset.kbWindow),count=Math.min(value,s.rows.length),chosen=Number(select.value.replaceAll('-','')),i=s.rows.findIndex(row=>row.trade_date===chosen),end=i<0||i===s.rows.length-1?s.rows.length:Math.min(s.rows.length,i+Math.floor(count*.7));w.setOriginalWindow?.(count,end);if(i>=0)w.choose?.(i);w.paint?.()};
  $('stockList').addEventListener('click',()=>{if(document.body.classList.contains('kb-single-focus'))clear()});
  return {bindDay(value){day=value;host.hidden=!(value?.source_date==='2026-10-30'&&value?.observation_date==='2026-11-02');if(!host.hidden)open()},unbindDay(){clear();day=null;host.hidden=true}};
}
