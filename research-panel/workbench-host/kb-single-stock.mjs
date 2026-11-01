import {loadProjection} from './dot/src/projection-view.mjs';

const $=id=>document.getElementById(id);
const node=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n};
const sha64=s=>typeof s==='string'&&/^[a-f0-9]{64}$/.test(s);
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

export function installSingleResearch(){
  const host=$('kbSingleResearch'),body=$('kbSingleBody'),status=$('kbSingleStatus'),frame=$('kbSingleChart'),select=$('kbSingleDate');
  let day=null,active=null,request=null,serial=0,observer=null;
  const clear=()=>{++serial;request?.abort();request=null;observer?.disconnect();observer=null;active=null;frame.src='about:blank';body.hidden=true;document.body.classList.remove('kb-single-focus');};
  const isCurrent=(mine,bound)=>mine===serial&&day===bound;
  function paint(date){
    if(!active)return;const row=active.byDate.get(Number(date));if(!row){status.textContent='该日期没有已绑定值，不使用临近日替代。';return}
    select.value=String(row.trade_date);$('kbSingleSelected').textContent=String(row.trade_date);
    const chips=$('kbSingleChips');chips.replaceChildren();
    for(const [field,title] of [['kb_b1','新KB B1'],['kb_b2','新KB B2'],['kb_b3','新KB B3'],['kb_fanbao','新KB反包'],['kb_violence_k','KB暴力K']]){const chip=node('span',title+' · '+label(row.kb[field]));chip.className='kb-chip';chips.append(chip)}
    const legacy=$('kbSingleLegacy');legacy.replaceChildren();
    for(const [field,title] of [['user_v1_level1_buy_signal','原式一级买点'],['user_v1_level2_buy_signal','原式二级买点'],['user_v1_sell_signal_daily','原式卖点（日线）']]){const chip=node('span',title+' · '+label(row.original[field],true));chip.className='kb-chip kb-old';legacy.append(chip)}
    const groups=$('kbSingleGroups');groups.replaceChildren();
    for(const group of [...new Set(active.view.fields.map(f=>f.group))]){
      const section=node('details');section.className='kb-group';const fields=active.view.fields.filter(f=>f.group===group);section.append(node('summary',group+' · '+fields.length+'项'));
      const list=node('dl');for(const field of fields){const dt=node('dt',field.description);dt.title=field.name;const value=row.kb[field.name],text=value==null&&field.status==='SOURCE_IMPLEMENTATION_DEFECT'?'待核：'+field.unknown_reason:label(value);const dd=node('dd',text);dd.title=field.name;list.append(dt,dd)}section.append(list);groups.append(section);
    }
  }
  function bindFrame(mine,bound){
    const w=frame.contentWindow,doc=frame.contentDocument;if(!w||!doc?.documentElement)return;
    observer?.disconnect();
    const ready=()=>{if(!isCurrent(mine,bound)){observer?.disconnect();return}const state=w.RESEARCH_PANEL_STATE;if(doc.documentElement.dataset.loaded!=='002865.SZ'||state?.symbol!=='002865.SZ'||state.rows?.length!==active?.view.rows.length)return;
      observer?.disconnect();observer=null;
      if(!doc.getElementById('kb-single-chart-focus')){const style=doc.createElement('style');style.id='kb-single-chart-focus';style.textContent='body{margin:0!important;background:#07131e!important}header,aside,.toolbar,.charthead .controls,#selected-date,.stats,.tables,details,#status,.foot,#chart-caption{display:none!important}main{display:block!important;max-width:none!important;margin:0!important;min-height:0!important}article{padding:12px!important}.chartbox{border:0!important;padding:0!important}.charthead{margin:0 0 4px!important}canvas{height:405px!important}';doc.head.appendChild(style);w.dispatchEvent(new w.Event('resize'));w.paint?.();}
      if(w.choose&&!w.choose.kbSingleWrapped){const original=w.choose;const wrapped=function(i){const answer=original.apply(this,arguments);const row=w.RESEARCH_PANEL_STATE?.rows?.[i];if(row)paint(row.trade_date);return answer};wrapped.kbSingleWrapped=true;w.choose=wrapped;}
      w.setOriginalWindow?.(Math.min(120,state.rows.length),state.rows.length);w.paint?.();
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
      if(view.symbol!==meta.symbol||view.source_date!==meta.source_date||view.observation_date!==meta.observation_date||view.source_generation!==meta.generation||view.source_input_sha256!==meta.input_sha256||view.candidate_generation!==meta.candidate_generation||view.source_gate!=='PASS_RELOCATED_SOURCE_GATE'||view.candidate_pool_member!==false||!Array.isArray(view.fields)||view.fields.length!==57||!Array.isArray(view.rows)||view.rows.length!==meta.rows||projection.data.rows.length!==meta.rows)throw Error('单股字段或图形身份冲突');
      const byDate=new Map;for(const row of view.rows){if(!Number.isInteger(row.trade_date)||byDate.has(row.trade_date)||!row.kb||!row.original)throw Error('单股日期数据无效');byDate.set(row.trade_date,row)}
      if(!byDate.has(20261030))throw Error('单股目标日期缺失');
      active={view,projection,byDate};select.replaceChildren();for(const row of view.rows){const option=node('option',String(row.trade_date));option.value=String(row.trade_date);select.append(option)}select.value='20261030';paint(20261030);
      const html=new URL(meta.assets.html.url,location.origin);if(html.origin!==location.origin||html.searchParams.get('sha256')!==meta.assets.html.sha256||!sha64(meta.assets.html.sha256))throw Error('单股原图身份冲突');
      frame.onload=()=>bindFrame(mine,bound);frame.src=html.href;
      status.textContent='原式图载入中 · 来源10/30 / 观察11/2';
    }catch(error){if(isCurrent(mine,bound)&&error.name!=='AbortError'){status.textContent='单股研究暂不可用 · '+error.message;frame.src='about:blank'}}
  }
  $('kbSingleOpen').onclick=open;$('kbSingleBack').onclick=()=>{clear();status.textContent='点击查看钧达单股研究'};
  select.onchange=()=>{if(!active)return;paint(select.value);const w=frame.contentWindow,s=w?.RESEARCH_PANEL_STATE,i=s?.rows?.findIndex(r=>String(r.trade_date)===select.value);if(i>=0&&w.choose){w.setOriginalWindow?.(Math.min(120,s.rows.length),Math.min(s.rows.length,i+84));w.choose(i);w.paint?.()}};
  for(const button of host.querySelectorAll('[data-kb-window]'))button.onclick=()=>{const w=frame.contentWindow,s=w?.RESEARCH_PANEL_STATE;if(!active||!s?.rows?.length)return;const count=button.dataset.kbWindow==='all'?s.rows.length:Number(button.dataset.kbWindow);w.setOriginalWindow?.(Math.min(count,s.rows.length),s.rows.length);w.paint?.()};
  $('stockList').addEventListener('click',()=>{if(document.body.classList.contains('kb-single-focus'))clear()});
  return {bindDay(value){day=value;host.hidden=!(value?.source_date==='2026-10-30'&&value?.observation_date==='2026-11-02');if(!host.hidden)open()},unbindDay(){clear();day=null;host.hidden=true}};
}
