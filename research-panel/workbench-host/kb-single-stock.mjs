import {loadProjection} from './dot/src/projection-view.mjs';
import {actionPresentation,signalSummary,signalExplanations,confirmedGapPresentation,brickCountPresentation,nStructurePresentation,CHART_EVENTS,CONFIRMED_GAP_FIELDS,HOLD_ITEMS,HOLD_REASONS} from './kb-signal-view.mjs';
import {installKbOverlay} from './kb-chart-overlay.mjs';

const $=id=>document.getElementById(id);
const node=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n};
const sha64=s=>typeof s==='string'&&/^[a-f0-9]{64}$/.test(s);
export const ACTION_REBIND_FIELDS=['kb_action_no_position','kb_action_no_position_status',
  'kb_action_with_position','kb_action_with_position_status','kb_action_reasons','kb_action_rule_sha256'];
export const validSymbol=s=>typeof s==='string'&&/^(?:\d{6}\.(?:SH|SZ|BJ)|HK\.\d{5})$/.test(s);
export function bindSingleSymbolSearch(input,open){
  input.placeholder='名称或代码；完整代码按 Enter 查看单股';
  input.addEventListener('keydown',event=>{const symbol=event.currentTarget.value.trim().toUpperCase();
    if(event.key==='Enter'&&validSymbol(symbol)){event.preventDefault();open(symbol)}});
}
const iso=value=>String(value).replace(/^(\d{4})(\d{2})(\d{2})$/,'$1-$2-$3');
const label=(v,flag=false)=>v===null||v===undefined?'待确认':v===true||flag&&v===1?'是':v===false||flag&&v===0?'否':String(v);
export function singleSelectionHref(href,symbol,stockDate=null,version=undefined){
  if(!validSymbol(symbol))throw Error('单股证券无效');
  if(stockDate!==null&&!/^\d{4}-\d{2}-\d{2}$/.test(stockDate))throw Error('单股日期无效');
  const url=new URL(href),same=url.searchParams.get('symbol')===symbol;url.searchParams.set('symbol',symbol);
  if(stockDate===null)url.searchParams.delete('stock_date');else url.searchParams.set('stock_date',stockDate);
  if(version===null||!same&&version===undefined){url.searchParams.delete('candidate_generation');url.searchParams.delete('panel_generation');url.searchParams.delete('view_generation')}
  else if(version!==undefined){if(!['candidate_generation','panel_generation'].includes(version?.key)||!sha64(version?.value))throw Error('单股版本无效');
    url.searchParams.delete('candidate_generation');url.searchParams.delete('panel_generation');url.searchParams.delete('view_generation');url.searchParams.set(version.key,version.value)}
  return url.href;
}
export async function decodeBoundGzip(data,expected){
  const limit=32*1024*1024;
  if(!Number.isSafeInteger(expected)||expected<1||expected>limit)throw Error('单股数据解压长度不符');
  const reader=new Blob([data]).stream().pipeThrough(new DecompressionStream('gzip')).getReader();
  const chunks=[];let size=0;
  try{for(;;){const {value,done}=await reader.read();if(done)break;size+=value.byteLength;
    if(size>expected||size>limit){await reader.cancel();throw Error('单股数据解压长度不符')}chunks.push(value)}}
  finally{reader.releaseLock()}
  if(size!==expected)throw Error('单股数据解压长度不符');
  return new Uint8Array(await new Blob(chunks).arrayBuffer());
}
async function readBoundGzip(ref,signal){
  const url=new URL(ref.url,location.origin);
  if(url.origin!==location.origin||!sha64(ref.sha256)||ref.encoding!=='gzip'||!Number.isSafeInteger(ref.bytes)||ref.bytes<1||ref.bytes>8*1024*1024)throw Error('单股数据身份无效');
  const response=await fetch(url,{signal,credentials:'same-origin',redirect:'error',cache:'no-store'});
  if(!response.ok)throw Error('单股数据读取失败');
  const reader=response.body?.getReader();if(!reader)throw Error('单股数据流不可用');
  const chunks=[];let size=0;
  try{for(;;){const {value,done}=await reader.read();if(done)break;size+=value.byteLength;
    if(size>ref.bytes){await reader.cancel();throw Error('单股数据长度不符')}chunks.push(value)}}finally{reader.releaseLock()}
  if(size!==ref.bytes)throw Error('单股数据长度不符');
  const data=new Uint8Array(size);let offset=0;for(const chunk of chunks){data.set(chunk,offset);offset+=chunk.byteLength}
  const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',data))].map(v=>v.toString(16).padStart(2,'0')).join('');if(hash!==ref.sha256)throw Error('单股数据校验失败');
  const plain=await decodeBoundGzip(data,ref.decoded_bytes);
  return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(plain));
}

// The producer has already checked every old/new value against the paired
// correction. The browser verifies identity and consumes those saved values.
export function decodeActionPatch(meta,payload){
  if(![meta.asset_candidate_generation,meta.asset_candidate_input_sha256,meta.panel_generation,meta.candidate_input_sha256,
      meta.origin_binding_sha256,meta.action_source_overlay_sha256,meta.action_rebind_equivalence_sha256].every(sha64)||
    !Array.isArray(meta.dates)||payload?.schema!=='v4.workbench.generic_action_patch.v1'||payload.symbol!==meta.symbol||
    payload.origin_candidate_generation!==meta.asset_candidate_generation||
    payload.origin_candidate_input_sha256!==meta.asset_candidate_input_sha256||
    payload.candidate_generation!==meta.panel_generation||payload.candidate_input_sha256!==meta.candidate_input_sha256||
    payload.origin_binding_sha256!==meta.origin_binding_sha256||payload.source_overlay_sha256!==meta.action_source_overlay_sha256||
    payload.equivalence_sha256!==meta.action_rebind_equivalence_sha256||payload.historical_PIT!==false||payload.RESEARCH_ONLY!==true||
    ['production_allowed','buy_gate_updated','orders_sent'].some(k=>payload[k]!==false)||
    JSON.stringify(payload.field_names)!==JSON.stringify(ACTION_REBIND_FIELDS)||!Array.isArray(payload.rows)||
    payload.rows.length!==meta.action_patch_rows)throw Error('行动修订身份冲突');
  const dates=new Set(meta.dates),patch=new Map;let previous=0;
  for(const item of payload.rows){
    if(!Array.isArray(item)||item.length!==3||!dates.has(item[0])||item[0]<=previous||
      !Array.isArray(item[1])||item[1].length!==6||!Array.isArray(item[2])||item[2].length!==6||
      item[1].every((value,i)=>Object.is(value,item[2][i])))throw Error('行动修订日期或内容冲突');
    for(const values of [item[1],item[2]])actionPresentation(Object.fromEntries(ACTION_REBIND_FIELDS.map((key,i)=>[key,values[i]])),meta.action_contract_sha256);
    previous=item[0];patch.set(item[0],{old:item[1],value:item[2]});
  }
  return patch;
}

// Unpack persisted values only; no KB or score formula runs in the browser.
export function decodeGenericChunk(meta,chunk,ref,patch=null){
  const assetGeneration=meta.asset_candidate_generation??meta.panel_generation;
  const assetInput=meta.asset_candidate_input_sha256??meta.candidate_input_sha256;
  if(chunk?.schema!=='v4.workbench.generic_single_chunk.v1'||chunk.symbol!==meta.symbol||
    chunk.candidate_generation!==assetGeneration||chunk.candidate_input_sha256!==assetInput||
    chunk.source_input_sha256!==meta.input_sha256||
    meta.action_rebound===true&&(!(patch instanceof Map)||patch.size!==meta.action_patch_rows)||
    !Array.isArray(chunk.rows)||chunk.rows.length!==ref.row_count||!Array.isArray(meta.field_names)||meta.field_names.length!==107||
    !Array.isArray(meta.original_fields)||meta.original_fields.length!==13)throw Error('单股数据块身份冲突');
  const start=meta.dates.indexOf(ref.first_date);
  if(start<0||meta.dates[start+ref.row_count-1]!==ref.last_date)throw Error('单股数据块日期冲突');
  const segmented=['RECONCILED_DAILY','INHERITED_WHOLE'].includes(meta.n_identity_kind),spans=meta.n_identity_spans;
  if(segmented){
    if(!Array.isArray(spans)||!spans.length||spans.length>meta.dates.length)throw Error('单股诊断来源分段冲突');
    let next=0;
    for(const span of spans){
      if(!span||!Number.isInteger(span.start_index)||!Number.isInteger(span.end_index)||span.start_index!==next||
        span.end_index<span.start_index||span.end_index>=meta.dates.length||span.first_date!==meta.dates[span.start_index]||
        span.last_date!==meta.dates[span.end_index]||!sha64(span.generation_id)||!sha64(span.input_sha256))throw Error('单股诊断来源分段冲突');
      next=span.end_index+1;
    }
    if(next!==meta.dates.length)throw Error('单股诊断来源分段冲突');
  }else if(spans!==undefined)throw Error('单股诊断来源分段冲突');
  let spanIndex=0;
  if(segmented)while(spans[spanIndex].end_index<start)spanIndex++;
  return chunk.rows.map((item,index)=>{
    if(!Array.isArray(item)||item.length!==5||item[0]!==meta.dates[start+index]||!Array.isArray(item[1])||item[1].length!==107||
      !Array.isArray(item[2])||item[2].length!==13||!item[3]||typeof item[3]!=='object'||Array.isArray(item[3])||
      Object.keys(item[3]).length!==25||!Array.isArray(item[4])||item[4].length!==2)throw Error('单股数据块内容冲突');
    const all=Object.fromEntries(meta.field_names.map((key,i)=>[key,item[1][i]]));
    const change=patch?.get(item[0]);
    if(change){for(let i=0;i<ACTION_REBIND_FIELDS.length;i++){
      const key=ACTION_REBIND_FIELDS[i];if(!Object.is(all[key],change.old[i]))throw Error('行动修订原值冲突');
      all[key]=change.value[i];
    }}
    const group=name=>Object.fromEntries(meta.field_groups[name].map(key=>[key,all[key]]));
    const row={trade_date:item[0],kb:group('kb'),hold_score:group('hold_score'),supplemental:group('supplemental'),
      action:group('action'),yidong:group('yidong'),confirmed_kb_fields:group('confirmed_kb_fields'),
      original:Object.fromEntries(meta.original_fields.map((key,i)=>[key,item[2][i]])),
      confirmed_kb_diagnostics:item[3],confirmed_kb_reused:{bowl_white:item[4][0],bowl_yellow:item[4][1]},
      diagnostics:{volume_vs_previous:null,volume_vs_previous_5_mean:all.kb_yidong_vol_ratio_5}};
    const n=item[3].kb_n_structure;
    if(segmented)while(spans[spanIndex].end_index<start+index)spanIndex++;
    const nGeneration=segmented?spans[spanIndex].generation_id:meta.n_generation_id;
    const nInput=segmented?spans[spanIndex].input_sha256:meta.n_input_sha256;
    if(!n||n.rule_sha256!==meta.n_rule_sha256||n.helper_sha256!==meta.n_helper_sha256||n.input_sha256!==nInput||
      n.generation_id!==nGeneration||n.state!==(row.hold_score.kb_hold_trend_up===true?'TREND_UP':row.hold_score.kb_hold_trend_up_reason)||
      row.yidong.kb_yidong_rule_sha256!==meta.yidong_contract_sha256)throw Error('单股诊断身份冲突');
    actionPresentation(row.action,meta.action_contract_sha256);
    return row;
  });
}

export function actionStatusHint(status){
  if(status==='CONFLICTING_OBSERVATIONS')return '信号冲突，待核';
  if(status==='UNKNOWN'||status.startsWith('UNKNOWN_'))return '状态待核';
  return '';
}

export function installSingleResearch({loadDetails=()=>{}}={}){
  const host=$('kbSingleResearch'),body=$('kbSingleBody'),status=$('kbSingleStatus'),frame=$('kbSingleChart'),select=$('kbSingleDate');
  const stocks={'002865.SZ':'钧达股份','301048.SZ':'金鹰重工','300206.SZ':'理邦仪器'};
  let day=null,active=null,request=null,serial=0,dateSerial=0,observer=null,overlayCleanup=null,symbol='002865.SZ';
  const dailyIds=['kbSingleScore','kbSingleScoreItems','kbSingleActions','kbSingleActionReasons','kbSingleChips','kbSingleGroups','kbSingleSignalReasons','kbSingleUnknownItems'];
  const clearDaily=()=>{for(const id of dailyIds)$(id)?.replaceChildren();$('kbSingleVolume').textContent='';$('kbSingleSelected').textContent='';$('kbSingleUnknown').hidden=true;};
  const clear=()=>{++serial;++dateSerial;request?.abort();request=null;observer?.disconnect();observer=null;overlayCleanup?.();overlayCleanup=null;active=null;frame.src='about:blank';frame.hidden=true;body.hidden=true;clearDaily();for(const id of ['kbSingleHistory','kbSingleCompany','kbSingleFinancial'])$(id)?.replaceChildren();select.value='';$('kbSingleDateStatus').textContent='';$('kbSingleVersionLatest').hidden=true;document.body.classList.remove('kb-single-focus');window.RelatedReports?.clear();if($('relatedReports'))$('relatedReports').hidden=true;};
  function marketChrome(hk){
    const heading=select.closest?.('.section-head')?.querySelector('h3');
    if(heading)heading.textContent=hk?'港股原始逐日观察 · 图待核':'原式图与KB事件';
    const toolbar=frame.previousElementSibling,caption=frame.nextElementSibling;
    if(toolbar?.classList.contains('chart-toolbar'))toolbar.hidden=hk;
    if(caption?.classList.contains('field-note'))caption.hidden=hk;
    const groupHeading=$('kbSingleGroups')?.previousElementSibling;
    if(groupHeading?.tagName==='H4'){
      groupHeading.textContent=hk?'原始逐日观察字段':'57 项 KB 字段及定义';
      const note=groupHeading.previousElementSibling;if(note?.classList.contains('field-note'))note.hidden=hk;
    }
    const hits=$('kbSingleChips')?.previousElementSibling;if(hits?.tagName==='P')hits.hidden=hk;
    const actionNote=$('kbSingleActions')?.nextElementSibling;if(actionNote?.classList.contains('field-note'))actionNote.hidden=hk;
    const historyHeading=$('kbSingleHistory')?.closest?.('section')?.querySelector('h3');
    if(historyHeading)historyHeading.textContent=hk?'原始历史记录':'历史同买点与相同位置研究';
    const summary=$('kbSingleExplain')?.querySelector('summary');
    if(summary?.firstChild?.nodeType===3)summary.firstChild.nodeValue=hk?'观察与来源 · ':'信号与依据 · ';
  }
  const routeDate=()=>new URL(location.href).searchParams.get('stock_date');
  const writeRoute=(code,date=null,version=undefined)=>history.replaceState(history.state,'',singleSelectionHref(location.href,code,date,version));
  function versionAvailable(key,value){
    if(!sha64(value))throw Error('研究版本身份无效');
    const params=new URL(location.href).searchParams,other=key==='candidate_generation'?'panel_generation':'candidate_generation';
    const pinned=params.get(key);if(params.has(other)||params.has('view_generation')||pinned!==null&&pinned!==value){
      clearDaily();frame.hidden=true;body.hidden=true;$('kbSingleVersionLatest').hidden=false;
      status.textContent='所选研究版本已变或不可用，请主动查看最新版本。';return false}
    return true;
  }
  function bindVersion(code,key,value){
    const url=new URL(location.href);if(symbol!==code||url.searchParams.get('symbol')&&url.searchParams.get('symbol')!==code)return false;
    if(!versionAvailable(key,value))return false;
    url.searchParams.set('symbol',code);url.searchParams.delete(key==='candidate_generation'?'panel_generation':'candidate_generation');url.searchParams.delete('view_generation');
    url.searchParams.set(key,value);history.replaceState(history.state,'',url.href);return true;
  }
  function unavailable(date){clearDaily();frame.hidden=true;select.setAttribute('aria-invalid','true');
    $('kbSingleDateStatus').textContent=String(date)+' 无已绑定交易数据，不自动替换日期。';}
  const isCurrent=(mine,bound)=>mine===serial&&day===bound;
  function paint(date){
    if(!active)return;const row=active.byDate.get(Number(date));if(!row){$('kbSingleDateStatus').textContent='该日期没有已绑定交易日，不使用临近日替代。';return}
    select.value=iso(row.trade_date);select.removeAttribute('aria-invalid');$('kbSingleDateStatus').textContent='交易日 '+iso(row.trade_date)+' · 单股数据截至 '+day.source_date;$('kbSingleSelected').textContent=iso(row.trade_date);
    const action=actionPresentation(row.action,active.meta.action_contract_sha256),actions=$('kbSingleActions');actions.replaceChildren();
    for(const [context,value,status] of [['无持仓',action.flat,row.action.kb_action_no_position_status],['有持仓',action.held,row.action.kb_action_with_position_status]]){
      const line=node('p'),hint=actionStatusHint(status);line.append(node('span',context+'：'),node('strong',value));
      if(hint)line.append(node('span','（'+hint+'）'));actions.append(line);
    }
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
      for(const [key,title] of HOLD_ITEMS){const value=score[key],reason=score[key+'_reason'];scoreItems.append(node('p',title+'：'+(value===null?'待核 · '+(HOLD_REASONS[reason]??'来源待核'):value?'1分':'0分'+(HOLD_REASONS[reason]?' · '+HOLD_REASONS[reason]:''))))}
      for(const text of nStructurePresentation(row)??[])scoreItems.append(node('p',text));
      scoreItems.append(node('p',`KB指标：BBI ${label(score.kb_hold_bbi)} · K ${label(score.kb_hold_k)} · D ${label(score.kb_hold_d)} · J ${label(row.kb.kb_b1_j)}；原 ref_hold_score 保留原身份。`));
    }
    const groups=$('kbSingleGroups');groups.replaceChildren();
    for(const group of [...new Set(active.view.fields.map(f=>f.group))]){
      const section=node('section');section.className='kb-group';const fields=active.view.fields.filter(f=>f.group===group);section.append(node('h4',group+' · '+fields.length+'项'));
      const list=node('dl');for(const field of fields){const dt=node('dt',field.name==='kb_macd_veto'?'MACD日线风险条件':field.name==='kb_didi'?'滴滴·日K双阴阶梯':field.description);dt.title=field.name;const value=row.kb[field.name],brickText=field.name==='kb_brick_consecutive'?brickCountPresentation(row):null,text=brickText??(value==null&&field.status==='SOURCE_IMPLEMENTATION_DEFECT'?'待核：'+field.unknown_reason:label(value));const dd=node('dd',text);dd.title=field.name;list.append(dt,dd)}section.append(list);groups.append(section);
    }
    const gap=confirmedGapPresentation(row);if(gap){const section=node('section'),list=node('dl');section.className='kb-group';section.append(node('h4','知识库补充组件'));for(const item of gap){const dt=node('dt',item.title),dd=node('dd',item.text);dt.title=dd.title=item.key;list.append(dt,dd)}section.append(list);groups.append(section)}
  }
  async function selectDate(date,{move=true,latest=false}={}){
    if(!active)return;const chosen=iso(date);if(!/^\d{4}-\d{2}-\d{2}$/.test(chosen)){unavailable(chosen);return}
    writeRoute(symbol,latest?null:chosen);if(active.hk){paintHkDate(chosen);return}if(active.scoped){paintScopedDate(Number(chosen.replaceAll('-','')));return}
    const a=active,target=Number(chosen.replaceAll('-','')),mine=++dateSerial;
    if(a.generic){try{await loadGenericDate(a,target,mine)}catch(error){if(active===a&&mine===dateSerial&&error.name!=='AbortError'){clearDaily();$('kbSingleDateStatus').textContent='研究日期读取失败 · '+error.message}return}if(active!==a||mine!==dateSerial)return}
    const row=a.byDate.get(target);if(!row||a.generic&&!row.hold_score){unavailable(chosen);return}
    frame.hidden=a.generic&&a.meta.chart_status!=='READY';
    const w=frame.contentWindow,s=w?.RESEARCH_PANEL_STATE,i=s?.rows?.findIndex(r=>Number(r.trade_date)===target);
    if(move&&i>=0&&w.setOriginalWindow){const count=Math.min(120,s.rows.length);w.setOriginalWindow(count,i===s.rows.length-1?s.rows.length:Math.min(s.rows.length,i+Math.floor(count*.7)));w.choose(i)}
    paint(row.trade_date);w?.paint?.();
  }
  function paintHkDate(date){
    const a=active;if(!a?.hk)return;clearDaily();frame.hidden=true;
    const compact=Number(date.replaceAll('-','')),row=a.byDate.get(compact),sourceDay=Number(a.data.source_date);
    select.value=date;select.removeAttribute('aria-invalid');$('kbSingleSelected').textContent=date;
    $('kbSingleScore').textContent='港股原始观察 · 评分待核';$('kbSingleActions').replaceChildren(node('p','下一交易日正式资格：待核（未获日期匹配的资格来源）。'));
    const groups=$('kbSingleGroups'),section=node('section'),list=node('dl');section.className='kb-group';section.append(node('h4','原始逐日观察'));
    if(row){
      for(const [key,title] of [['open','开盘'],['high','最高'],['low','最低'],['close','收盘'],['trade','成交量原值'],['amount','成交额原值']]){
        const dt=node('dt',title),value=row.raw_fields?.[key],dd=node('dd',value==null?'待核':String(value)+'（原值；单位/口径待核）');list.append(dt,dd)}
      section.append(list,node('p',`来源 ${row.source??'待核'} · 原始行对账 SHA ${row.reconciliation_row_sha256}；币种、复权、单位与历史PIT均待核。`));
      $('kbSingleDateStatus').textContent=`交易日 ${date} · 原始观察，不代表交易资格。`;
    }else{
      const reason=compact===sourceDay&&a.data.decision_reason==='TARGET_SNAPSHOT_EXCLUDED'?'来源日采样已排除；没有用较早数据替代。':'该日期无已保存原始行；没有用临近日替代。';
      section.append(node('p',reason));$('kbSingleDateStatus').textContent=reason;
    }
    groups.replaceChildren(section);
    const unknown=$('kbSingleUnknown');unknown.hidden=false;$('kbSingleUnknownSummary').textContent='港股来源待核';
    const membership=a.data.source_day_security_master_member;
    const gaps=a.data.missing_sessions,lines=[`${iso(a.data.source_date)} 来源日证券主表：${membership===true?'有记录':membership===false?'无记录':'待核'}（不等于下一交易日资格）`,
      `${iso(a.data.target_date)} 正式资格：CANNOT_CONFIRM`,'来源快照精确采集时刻待核',
      '原图、公司资料未绑定','成交量/成交额单位、币种、复权及 PIT 待核'];
    lines.push(`窗口守卫：价格 ${a.data.price_window?.status??'UNKNOWN'} · 成交量 ${a.data.volume_window?.status??'UNKNOWN'}；CLEAR 不代表单位已认证。`);
    const high=a.data.price_window?.fields?.high,volume=a.data.volume_window?.fields?.trade;
    if(high)lines.push(`价格窗口需前60个会话和来源日；前60会话已检查 ${high.checked_sessions??'待核'} 项，缺失 ${high.missing_sessions?.length??'待核'} 项；多源口径仍待核。`);
    if(volume)lines.push(`成交量窗口需前5会话和来源日；已检查 ${volume.checked_sessions??'待核'} 项，单位仍待核。`);
    if(a.data.original_scheduled_cutoff||a.data.decision_cutoff_manual_run)
      lines.push(`原计划截止 ${a.data.original_scheduled_cutoff??'待核'}；本次人工研究截止 ${a.data.decision_cutoff_manual_run??'待核'}，均非快照精确采集时刻。`);
    if(Array.isArray(gaps)&&gaps.length)lines.push('历史缺少会话：'+gaps.map(iso).join('、'));
    else if(gaps==null)lines.push('历史缺失会话：待核');
    if(a.data.panel_window_gaps?.length)lines.push('窗口问题：'+a.data.panel_window_gaps.join('、'));
    $('kbSingleUnknownItems').replaceChildren(...lines.map(value=>node('p',value)));
    status.textContent=`${a.data.name??a.meta.symbol} · 原始观察 · 下一交易日资格待核`;
  }
  async function openHk(meta,bound,mine,signal,requested){
    if(meta.symbol!==requested||meta.source_date!==bound.source_date||meta.observation_date!==bound.observation_date||
      meta.generation!==bound.generation||meta.input_sha256!==bound.input_sha256||
      meta.numeric_manifest?.sha256!==bound.numeric_manifest?.sha256||meta.numeric_manifest?.path!==bound.numeric_manifest?.path||
      meta.historical_PIT!==false||meta.RESEARCH_ONLY!==true||['production_allowed','buy_gate_updated','orders_sent'].some(k=>meta[k]!==false)||
      !sha64(meta.panel_generation)||!sha64(meta.source_panel_sha256))throw Error('港股观察身份冲突');
    const params=new URL(location.href).searchParams;
    if(params.has('candidate_generation')||params.has('panel_generation')&&params.get('panel_generation')!==meta.panel_generation||
      params.has('view_generation')&&params.get('view_generation')!==meta.view_generation){
      body.hidden=true;frame.hidden=true;$('kbSingleVersionLatest').hidden=false;status.textContent='所选研究版本已变或不可用，请主动查看最新版本。';return;
    }
    if(meta.status==='UNKNOWN_SOURCE_ADMISSION'){status.textContent='港股来源待核 · '+(meta.reason??'UNKNOWN');return}
    if(meta.status!=='READY_RAW_OBSERVATION_ONLY'||!sha64(meta.view_generation)||!meta.assets?.observation)throw Error('港股观察资料缺失');
    const data=await readBoundGzip(meta.assets.observation,signal);if(!isCurrent(mine,bound))return;
    if(data.schema!=='v4.workbench.hk_single_observation.v1'||data.symbol!==requested||
      data.source_date!==bound.source_date.replaceAll('-','')||data.target_date!==bound.observation_date.replaceAll('-','')||
      data.source_panel_sha256!==meta.source_panel_sha256||data.target_formal_eligibility_status!=='CANNOT_CONFIRM'||
      data.chart_status!=='UNKNOWN_NOT_SUPPLIED'||data.company_status!=='UNKNOWN_NOT_BOUND'||data.historical_PIT!==false||
      data.RESEARCH_ONLY!==true||['production_allowed','buy_gate_updated','orders_sent'].some(k=>data[k]!==false)||!Array.isArray(data.history))throw Error('港股观察资料身份冲突');
    const byDate=new Map;let previous=0;for(const row of data.history){const date=Number(row.date);
      if(!Number.isInteger(date)||date<=previous||date>Number(data.source_date)||!sha64(row.reconciliation_row_sha256)||!sha64(row.source_sha256))throw Error('港股历史日期或来源冲突');
      previous=date;byDate.set(date,row)}
    if(!byDate.has(Number(data.source_date))&&data.raw_values_status==='OBSERVED_RAW_FIELDS_ONLY_UNITS_BASIS_PIT_NOT_PROVEN'&&
      data.raw_source_day&&sha64(data.source_day_reconciliation_row_sha256))byDate.set(Number(data.source_date),{
        date:data.source_date,raw_fields:data.raw_source_day,source:data.raw_source_tag,source_sha256:data.source_panel_sha256,
        reconciliation_row_sha256:data.source_day_reconciliation_row_sha256});
    const url=new URL(location.href);url.searchParams.set('symbol',requested);url.searchParams.delete('candidate_generation');
    url.searchParams.set('panel_generation',meta.panel_generation);url.searchParams.set('view_generation',meta.view_generation);history.replaceState(history.state,'',url.href);
    active={hk:true,meta,data,byDate,signal};if(data.name){stocks[requested]=data.name;$('kbSingleName').textContent=data.name}
    select.min=iso(data.history[0]?.date??data.source_date);select.max=iso(data.source_date);
    $('kbSingleHistory').replaceChildren(node('p',`已存原始历史 ${data.history.length} 行；K线图未绑定，缺失日期不填补。`));
    $('kbSingleCompany').replaceChildren(node('p','公司资料待核'));$('kbSingleFinancial').replaceChildren(node('p','财务资料待核'));
    const selected=routeDate();if(selected&&!/^\d{4}-\d{2}-\d{2}$/.test(selected)){unavailable(selected);return}
    paintHkDate(selected??iso(data.source_date));
  }
  async function loadGenericDate(a,date,sequence){
    if(!a.dates.has(date))return;
    if(a.byDate.get(date)?.hold_score)return;
    const refs=Object.entries(a.meta.assets).filter(([key])=>/^chunk-\d+$/.test(key));
    const found=refs.find(([,ref])=>date>=ref.first_date&&date<=ref.last_date);
    if(!found)throw Error('交易日期未绑定数据块');
    const rows=decodeGenericChunk(a.meta,await readBoundGzip(found[1],a.signal),found[1],a.actionPatch);
    if(active!==a||sequence!==dateSerial)return;
    for(const prior of a.loadedDates){const overlay=a.overlays.get(prior);if(overlay)a.byDate.set(prior,overlay);else a.byDate.delete(prior)}
    a.loadedDates=rows.map(row=>row.trade_date);
    for(const row of rows)a.byDate.set(row.trade_date,row);
  }
  async function openGeneric(meta,bound,mine,signal,requested){
    if(meta.symbol!==requested||meta.source_date!==bound.source_date||meta.observation_date!==bound.observation_date||
      meta.generation!==bound.generation||meta.input_sha256!==bound.input_sha256||
      meta.numeric_manifest?.sha256!==bound.numeric_manifest?.sha256||meta.numeric_manifest?.path!==bound.numeric_manifest?.path||
      meta.historical_PIT!==false||meta.RESEARCH_ONLY!==true||['production_allowed','buy_gate_updated','orders_sent'].some(k=>meta[k]!==false)||
      !sha64(meta.panel_generation)||!sha64(meta.candidate_input_sha256))throw Error('研究面板身份冲突');
    const params=new URL(location.href).searchParams;
    if(params.has('candidate_generation')||params.has('panel_generation')&&params.get('panel_generation')!==meta.panel_generation||
      params.has('view_generation')&&params.get('view_generation')!==meta.view_generation){
      body.hidden=true;frame.hidden=true;$('kbSingleVersionLatest').hidden=false;status.textContent='所选研究版本已变或不可用，请主动查看最新版本。';return;
    }
    if(meta.status==='UNKNOWN_SOURCE_ADMISSION'){
      status.textContent='该股票来源或资产待核 · '+(meta.reason??'UNKNOWN');frame.hidden=true;
      $('kbSingleScore').textContent='行情与评分待核';$('kbSingleActions').replaceChildren(node('p','当日行情未准入；信号和持仓提示待核。'));
      const heading=select.closest?.('.section-head')?.querySelector('h3');if(heading)heading.textContent='原式图待核';
      if(frame.previousElementSibling?.classList.contains('chart-toolbar'))frame.previousElementSibling.hidden=true;
      if(frame.nextElementSibling?.classList.contains('field-note'))frame.nextElementSibling.hidden=true;
      $('kbSingleDateStatus').textContent='来源日行情未准入，不替用其他日期。';
      loadDetails(bound,meta,signal,{history:null,company:null});return;
    }
    if(meta.status!=='READY_FOR_RESEARCH_REVIEW'||!sha64(meta.view_generation)||!Array.isArray(meta.dates)||meta.dates.length!==meta.rows||
      !Array.isArray(meta.base_fields)||meta.base_fields.length!==57||!Array.isArray(meta.field_names)||meta.field_names.length!==107||
      !meta.assets?.overlay||!['READY','UNKNOWN'].includes(meta.chart_status))throw Error('研究资产身份冲突');
    let actionPatch=null;
    if(meta.action_rebound===true){
      if(!sha64(meta.asset_candidate_generation)||!sha64(meta.asset_candidate_input_sha256)||
        !sha64(meta.origin_binding_sha256)||!sha64(meta.action_rebind_equivalence_sha256)||
        !Number.isSafeInteger(meta.action_patch_rows)||meta.action_patch_rows<0||
        meta.action_patch_rows>meta.rows)throw Error('行动修订身份冲突');
      if(meta.action_patch_rows){
        if(!meta.assets.action_patch||!sha64(meta.action_source_overlay_sha256))throw Error('行动修订资产缺失');
        actionPatch=decodeActionPatch(meta,await readBoundGzip(meta.assets.action_patch,signal));
      }else{
        if(meta.assets.action_patch||meta.action_source_overlay_sha256!==null)throw Error('行动修订覆盖冲突');
        actionPatch=new Map;
      }
    }else if(meta.action_rebound!==undefined&&meta.action_rebound!==false)throw Error('行动修订身份冲突');
    const overlay=await readBoundGzip(meta.assets.overlay,signal);if(!isCurrent(mine,bound))return;
    if(overlay.schema!=='v4.workbench.generic_single_overlay.v1'||overlay.symbol!==requested||overlay.candidate_generation!==(meta.asset_candidate_generation??meta.panel_generation)||!Array.isArray(overlay.rows))throw Error('图上信号身份冲突');
    const dates=new Set(meta.dates),byDate=new Map;let previous=0;
    for(const item of overlay.rows){if(!Array.isArray(item)||item.length!==2||!dates.has(item[0])||item[0]<=previous||!Array.isArray(item[1])||
      !item[1].length||new Set(item[1]).size!==item[1].length||item[1].some(key=>!CHART_EVENTS.includes(key)))throw Error('图上信号日期冲突');
      previous=item[0];byDate.set(item[0],{trade_date:item[0],kb:Object.fromEntries(item[1].map(key=>[key,true]))});}
    const url=new URL(location.href);url.searchParams.set('symbol',requested);url.searchParams.delete('candidate_generation');
    url.searchParams.set('panel_generation',meta.panel_generation);url.searchParams.set('view_generation',meta.view_generation);history.replaceState(history.state,'',url.href);
    active={generic:true,meta,dates,byDate,overlays:new Map(byDate),loadedDates:[],signal,actionPatch,
      view:{fields:meta.base_fields,rows:meta.dates.map(trade_date=>({trade_date})),signal_component_facts:{}}};
    select.min=iso(meta.first_date);select.max=iso(meta.last_date);
    const assets={history:null,company:null};
    for(const kind of ['history','company']){
      const state=meta.detail_status?.[kind];
      if(state?.status==='READY'){
        if(!meta.assets[kind]||!sha64(state.source_candidate_generation))throw Error('单股资料身份冲突');
        const value=await readBoundGzip(meta.assets[kind],signal);
        if(!isCurrent(mine,bound))return;
        if(value.symbol!==requested||value.data_date!==bound.source_date.replaceAll('-','')||
          value.source_generation!==bound.generation||value.input_sha256!==bound.input_sha256||
          value.source_candidate_generation!==state.source_candidate_generation||value.numeric_manifest?.sha256!==bound.numeric_manifest.sha256||
          value.historical_PIT!==false||value.RESEARCH_ONLY!==true||['production_allowed','buy_gate_updated','orders_sent'].some(k=>value[k]!==false)||
          kind==='history'&&value.market_calendar?.sha256!==state.calendar_sha256)throw Error('单股资料身份冲突');
        assets[kind]=value;
      }else if(state?.status!=='UNKNOWN')throw Error('单股资料状态无效');
    }
    active.assets=assets;loadDetails(bound,meta,signal,assets);
    const selected=routeDate();if(selected&&!/^\d{4}-\d{2}-\d{2}$/.test(selected)){unavailable(selected);return}
    const chosen=selected?Number(selected.replaceAll('-','')):meta.last_date;
    if(selected&&!dates.has(chosen)){unavailable(selected);return}
    const dateMine=++dateSerial;await loadGenericDate(active,chosen,dateMine);if(!isCurrent(mine,bound)||dateMine!==dateSerial)return;paint(chosen);
    if(meta.chart_status!=='READY'){frame.hidden=true;status.textContent=`${meta.name} · 原式图待核 · ${meta.chart_reason??'UNKNOWN'}`;return}
    const projection=await loadProjection({...meta.assets.projection,projection_url:meta.assets.projection.url},
      {symbol:meta.symbol,source_date:meta.source_date,generation:meta.asset_candidate_generation??meta.panel_generation,input_sha256:meta.asset_candidate_input_sha256??meta.candidate_input_sha256},{origin:location.origin,signal});
    if(!isCurrent(mine,bound))return;
    if(projection.data.rows.some((row,i)=>row.trade_date!==meta.dates[i]))throw Error('原式图日期冲突');
    active.projection=projection;
    const html=new URL(meta.assets.html.url,location.origin);
    if(html.origin!==location.origin||html.searchParams.get('sha256')!==meta.assets.html.sha256||!sha64(meta.assets.html.sha256))throw Error('单股原图身份冲突');
    frame.onload=()=>bindFrame(mine,bound);frame.src=html.href;status.textContent='原式图载入中…';
  }
  async function scopedJSON(ref,signal,{verifyBytes=false}={}){
    const url=new URL(ref.url,location.origin);if(url.origin!==location.origin||!sha64(ref.sha256)||url.searchParams.get('sha256')!==ref.sha256)throw Error('研究资料身份无效');
    const response=await fetch(url,{signal,credentials:'same-origin',redirect:'error',cache:'no-store'});if(!response.ok)throw Error('研究资料读取失败');
    const raw=new Uint8Array(await response.arrayBuffer());
    if(verifyBytes){const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',raw))].map(v=>v.toString(16).padStart(2,'0')).join('');if(hash!==ref.sha256||raw.length!==ref.bytes)throw Error('公司资料校验失败')}
    return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw));
  }
  const fmt=v=>v===null||v===undefined?'待核':typeof v==='number'?(Number.isFinite(v)?String(Math.round(v*10000)/10000):'待核'):typeof v==='object'?JSON.stringify(v):String(v);
  function paintScopedCompany(company){
    const box=$('kbSingleCompany'),finance=$('kbSingleFinancial');box.replaceChildren();finance.replaceChildren();
    if(company.f10_status!=='OBSERVED'){box.append(node('p','F10资料待核：'+(company.reason??'来源未就绪')));return}
    box.append(node('p',`F10实际采集 ${company.captured_at??'待核'} · 来源更新 ${company.source_updated_date??'待核'}；不回填历史。`));
    box.append(node('p','当前概念：'+(company.concepts?.map(x=>x.name).join('、')||'待核')));
    const cmp=company.comparison??{};finance.append(node('p',`最新报告期 ${cmp.latest_report_period??'待核'} · 上期 ${cmp.prior_report_period??'待核'}`));
    const show=(title,value)=>{if(!value)return;const delta=value.percentage_point_change!=null?` · 差 ${fmt(value.percentage_point_change)} 个百分点`:` · 差 ${fmt(value.absolute_change)}`;const relative=value.presentation_priority!=='PERCENTAGE_POINTS'&&value.relative_change_pct!=null?` · 变化 ${fmt(value.relative_change_pct)}%`:value.relative_status==='UNKNOWN_ZERO_BASE'?' · 上期为零，变化率待核':'';const periods=value.latest_period||value.prior_period?`（${value.prior_period??'上期待核'} → ${value.latest_period??'最新期待核'}）`:'';finance.append(node('p',`${title}${periods}：上期 ${fmt(value.prior)} → 最新 ${fmt(value.latest)}${delta}${relative}${value.change_class?' · '+value.change_class:''}${value.basis?.includes('CUMULATIVE')?' · 累计口径差':''}`))};
    show('股东人数',cmp.shareholder_count);show('基金持股比例',cmp.holdings?.fund_hold_ratio_pct);show('前十大流通股东持股比例',cmp.holdings?.top10_float_ratio_pct);show('质押比例',cmp.holdings?.pledge_ratio_pct);
    for(const [key,title] of [['eps','每股收益'],['bps','每股净资产'],['roe_pct','净资产收益率'],['total_share','总股本'],['float_a_share','流通A股'],['revenue_yi','营业总收入（亿元）'],['net_profit_yi','净利润（亿元）']])show(title,cmp.financial_metrics?.[key]);
    for(const [key,title] of [['announcements','公告'],['dividends','分红'],['capital_actions','股本事项']]){const item=cmp[key];if(!item)continue;for(const [which,name] of [['latest','最新'],['prior','前一条']]){const v=item[which];finance.append(node('p',`${title}${name}：${v?(v.publication_date??v.report_period??'日期待核')+' · '+(v.text??v.reported_text??JSON.stringify(v)):'待核'}`))}}
    if(cmp.shareholder_count?.source_comparison==='DIFFERENT_VALUES_DIFFERENT_SOURCE_TIMES')finance.append(node('p','股东人数的不同来源时点不一致，已保留各自日期。'));
  }
  async function paintScopedDate(date){
    const a=active,mine=++dateSerial;if(!a?.scoped)return;if(!a.dates.has(date)){unavailable(iso(date));return}
    clearDaily();$('kbSingleDateStatus').textContent='正在核对交易日 '+iso(date)+'…';
    const template=a.meta.assets['row-'+a.meta.last_date],url=new URL(template.url,location.origin);url.pathname=url.pathname.replace(/row-\d{8}$/,'row-'+date);
    try{
      const result=await scopedJSON({...template,url:url.href},a.signal);if(active!==a||mine!==dateSerial)return;
      if(result.symbol!==a.meta.symbol||result.trade_date!==date||result.column_count!==317||result.selector_sha256!==a.meta.assets.selector.sha256||result.panel_generation!==a.meta.panel_generation)throw Error('研究面板身份冲突');
      if(a.meta.assets.diagnostics&&(result.diagnostics_sha256!==a.meta.assets.diagnostics.sha256||result.kb_n_structure?.rule_sha256!==a.meta.n_rule_sha256||result.kb_n_structure?.helper_sha256!==a.meta.n_helper_sha256))throw Error('N形资料身份冲突');
      const fields=result.fields;select.value=iso(date);select.removeAttribute('aria-invalid');$('kbSingleSelected').textContent=iso(date);$('kbSingleDateStatus').textContent=`交易日 ${iso(date)} · 完整历史 ${a.meta.rows} 行`;
      $('kbSingleScore').textContent=fields.kb_hold_score==null?`持股评分：已确认 ${fmt(fields.kb_hold_score_min)}～${fmt(fields.kb_hold_score_max)} / 5`:`持股评分：${fmt(fields.kb_hold_score)} / 5`;
      $('kbSingleActions').replaceChildren();$('kbSingleActionReasons').replaceChildren();
      const details=node('details'),summary=node('summary','查看评分与信号说明');details.append(summary);
      let reasons=[];try{reasons=JSON.parse(fields.kb_action_reasons||'[]')}catch{}for(const text of reasons)details.append(node('p',text));$('kbSingleActionReasons').append(details);
      if(result.kb_n_structure){const n=result.kb_n_structure;details.append(node('p',`N形状态：${fmt(n.state)} · 结构确认 ${fmt(n.structure_known_at)} · 当地规则 V1`));for(const key of ['L1','H1','L2','H2']){const p=n[key]??{};details.append(node('p',`${key}：${fmt(p.price)} · 发生 ${fmt(p.event_date)} · 确认 ${fmt(p.confirmed_at)}`))}}
      $('kbSingleChips').replaceChildren(node('span',`暴力K：${label(fields.kb_violence_k,true)} · 单日异动：${label(fields.kb_yidong_is,true)}`));
      $('kbSingleUnknown').hidden=true;$('kbSingleVolume').textContent='成交量 / 前5日均量：'+fmt(fields.kb_yidong_vol_ratio_5);
      const groups=$('kbSingleGroups');groups.replaceChildren();for(const [group,names] of Object.entries(a.meta.field_inventory)){const section=node('section');section.className='kb-group';section.append(node('h4',group+' · '+names.length+'项'));const list=node('dl');for(const name of names){const display=a.meta.field_labels?.[name];const dt=node('dt',display?`${display}（${name}）`:name),dd=node('dd',fmt(fields[name]));list.append(dt,dd)}section.append(list);groups.append(section)}
      status.textContent=`${a.meta.name} · 研究面板 ${a.meta.display_columns.selector} 列 · KB ${a.meta.fields_count} 项 · 原式图待接入`;
    }catch(error){if(active===a&&mine===dateSerial&&error.name!=='AbortError')$('kbSingleDateStatus').textContent='研究日期读取失败 · '+error.message}
  }
  async function openScoped(meta,bound,mine,signal,requested){
    frame.hidden=true;
    if(meta.symbol!==requested||meta.source_date!==bound.source_date||meta.observation_date!==bound.observation_date||meta.generation!==bound.generation||meta.input_sha256!==bound.input_sha256||meta.numeric_manifest?.sha256!==bound.numeric_manifest?.sha256||meta.numeric_manifest?.path!==bound.numeric_manifest?.path||meta.historical_PIT!==false||meta.RESEARCH_ONLY!==true||['production_allowed','buy_gate_updated','orders_sent'].some(k=>meta[k]!==false)||!sha64(meta.panel_generation))throw Error('研究面板身份冲突');
    if(meta.status==='UNKNOWN_SOURCE_ADMISSION'){status.textContent='该股票历史来源尚未准入 · '+(meta.reason??'待核');return}
    if(meta.status!=='READY_FOR_RESEARCH_REVIEW'||meta.fields_count!==107||meta.display_columns?.selector!==317||meta.display_columns?.backtest!==186)throw Error('研究面板身份冲突');
    if(!versionAvailable('panel_generation',meta.panel_generation))return;
    const [dates,company]=await Promise.all([scopedJSON(meta.assets.dates,signal),scopedJSON(meta.assets.company,signal,{verifyBytes:true})]);if(!isCurrent(mine,bound))return;
    if(dates.symbol!==meta.symbol||dates.rows!==meta.rows||dates.dates.length!==meta.rows||dates.selector_sha256!==meta.assets.selector.sha256||company.symbol!==meta.symbol||company.historical_PIT!==false)throw Error('研究资产身份冲突');
    if(!bindVersion(requested,'panel_generation',meta.panel_generation))return;
    active={scoped:true,meta,dates:new Set(dates.dates),signal};select.min=iso(meta.first_date);select.max=iso(meta.last_date);
    $('kbSingleHistory').replaceChildren(node('p',`完整历史 ${meta.rows} 个交易日，可用日期选择器逐日读取；原式图待接入。`));
    paintScopedCompany(company);const selected=routeDate();
    if(selected&&!/^\d{4}-\d{2}-\d{2}$/.test(selected))unavailable(selected);
    else await paintScopedDate(selected?Number(selected.replaceAll('-','')):meta.last_date);
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
      canvas.addEventListener('pointerup',event=>{if(!down||down.id!==event.pointerId)return;const moved=Math.hypot(event.clientX-down.x,event.clientY-down.y);down=null;if(moved>5)return;const s=w.RESEARCH_PANEL_STATE,g=s.geometry;if(!g||!s.visible.length)return;const x=event.clientX-canvas.getBoundingClientRect().left,i=Math.max(0,Math.min(s.visible.length-1,Math.floor((x-g.L)/g.step)));const index=s.offset+i;w.choose(index);selectDate(s.rows[index].trade_date,{move:false});w.paint()});
      const selected=routeDate(),chosen=selected&&/^\d{4}-\d{2}-\d{2}$/.test(selected)?Number(selected.replaceAll('-','')):null;
      const index=selected?state.rows.findIndex(row=>row.trade_date===chosen):state.rows.length-1;
      if(index<0){unavailable(selected);return}
      const count=Math.min(120,state.rows.length),end=index===state.rows.length-1?state.rows.length:Math.min(state.rows.length,index+Math.floor(count*.7));
      frame.hidden=false;w.setOriginalWindow?.(count,end);w.choose?.(index);w.paint?.();
      selectDate(state.rows[index].trade_date,{move:false,latest:!selected});
      status.textContent=`来源 ${day.source_date} · 观察 ${day.observation_date} · ${stocks[symbol]??symbol}单股研究`;
    };
    observer=new MutationObserver(ready);observer.observe(doc.documentElement,{attributes:true,attributeFilter:['data-loaded']});ready();
  }
  async function open(){
    if(!day)return;clear();const bound=day,mine=serial,requested=symbol;request=new AbortController();const signal=request.signal;
    const hk=requested.startsWith('HK.');marketChrome(hk);
    $('kbSingleName').textContent=stocks[requested];$('kbSingleCode').textContent=requested;frame.title=stocks[requested]+(hk?'原始观察图待核':'原式研究图');
    document.body.classList.add('kb-single-focus');body.hidden=false;status.textContent='正在核对单股数据和原式图…';
    try{
      const params=new URLSearchParams({revision:bound.generation}),pinned=new URL(location.href).searchParams;
      if(pinned.has('panel_generation'))params.set('panel_revision',pinned.get('panel_generation'));
      if(pinned.has('view_generation'))params.set('view_revision',pinned.get('view_generation'));
      const url='/api/v4/research/workbench/days/'+bound.source_date+'/single-research/'+encodeURIComponent(requested)+'?'+params;
      const response=await fetch(url,{signal,credentials:'same-origin',redirect:'error',cache:'no-store'});
      if(response.status===409){body.hidden=true;frame.hidden=true;$('kbSingleVersionLatest').hidden=false;status.textContent='所选研究版本已变或不可用，请主动查看最新版本。';return}
      if(!response.ok)throw Error('数据待核或尚未物化');const meta=await response.json();
      if(!isCurrent(mine,bound))return;
      if(typeof meta.name==='string'&&meta.name){stocks[requested]=meta.name;$('kbSingleName').textContent=meta.name;frame.title=meta.name+(hk?'原始观察图待核':'原式研究图')}
      if(meta.schema==='v4.workbench.hk_single_research.v1'){await openHk(meta,bound,mine,signal,requested);return}
      if(meta.schema==='v4.workbench.generic_single_research.v1'){await openGeneric(meta,bound,mine,signal,requested);return}
      if(meta.schema==='v4.workbench.scoped_kb_research.v1'){await openScoped(meta,bound,mine,signal,requested);return}
      const poolMember=bound.rows.some(row=>row.symbol===requested);
      if(meta.status!=='READY_FOR_RESEARCH_REVIEW'||meta.source_date!==bound.source_date||meta.observation_date!==bound.observation_date||meta.symbol!==requested||meta.generation!==bound.generation||meta.input_sha256!==bound.input_sha256||meta.numeric_manifest?.sha256!==bound.numeric_manifest?.sha256||meta.numeric_manifest?.path!==bound.numeric_manifest?.path||meta.candidate_pool_member!==poolMember||meta.fields_count!==57||meta.historical_PIT!==false||meta.RESEARCH_ONLY!==true||['production_allowed','buy_gate_updated','orders_sent'].some(k=>meta[k]!==false)||!sha64(meta.candidate_generation))throw Error('单股来源身份冲突');
      if(!versionAvailable('candidate_generation',meta.candidate_generation))return;
      const projectionRef={...meta.assets.projection,projection_url:meta.assets.projection.url};
      const [view,projection,history,company]=await Promise.all([readBoundGzip(meta.assets.kb,signal),loadProjection(projectionRef,{symbol:meta.symbol,source_date:meta.source_date,generation:meta.generation,input_sha256:meta.input_sha256},{origin:location.origin,signal}),readBoundGzip(meta.assets.history,signal),readBoundGzip(meta.assets.company,signal)]);
      if(!isCurrent(mine,bound))return;
      if(view.symbol!==meta.symbol||view.source_date!==meta.source_date||view.observation_date!==meta.observation_date||view.source_generation!==meta.generation||view.source_input_sha256!==meta.input_sha256||view.candidate_generation!==meta.candidate_generation||view.source_gate!=='PASS_RELOCATED_SOURCE_GATE'||view.candidate_pool_member!==poolMember||!sha64(meta.hold_score_contract_sha256)||!sha64(meta.hold_score_engine_sha256)||!sha64(meta.supplemental_contract_sha256)||!sha64(meta.action_contract_sha256)||!sha64(meta.yidong_contract_sha256)||view.hold_score_contract_sha256!==meta.hold_score_contract_sha256||view.hold_score_engine_sha256!==meta.hold_score_engine_sha256||view.supplemental_contract_sha256!==meta.supplemental_contract_sha256||view.action_contract_sha256!==meta.action_contract_sha256||view.yidong_contract_sha256!==meta.yidong_contract_sha256||!meta.display_projection||view.concept_snapshot?.source_sha256!==meta.display_projection.f10_source_sha256||view.concept_snapshot?.kb_concepts!==meta.display_projection.kb_concepts||view.concept_snapshot?.kb_concept_count!==meta.display_projection.kb_concept_count||!sha64(meta.signal_component_facts_sha256)||view.signal_component_facts_sha256!==meta.signal_component_facts_sha256||!view.field_inventory||!meta.field_inventory||JSON.stringify(Object.entries(view.field_inventory).sort())!==JSON.stringify(Object.entries(meta.field_inventory).sort())||!Array.isArray(view.fields)||view.fields.length!==meta.fields_count||!Array.isArray(view.rows)||view.rows.length!==meta.rows||projection.data.rows.length!==meta.rows)throw Error('单股字段或图形身份冲突');
      if(meta.confirmed_gap&&(!sha64(meta.confirmed_gap.contract_sha256)||!sha64(meta.confirmed_gap.diagnostics_sha256)||view.confirmed_gap_contract_sha256!==meta.confirmed_gap.contract_sha256||view.confirmed_gap_diagnostics_sha256!==meta.confirmed_gap.diagnostics_sha256||JSON.stringify([...meta.confirmed_gap.fields].sort())!==JSON.stringify(CONFIRMED_GAP_FIELDS.map(x=>x[0]).sort())))throw Error('知识库补充字段身份冲突');
      const nContract=meta.confirmed_gap?.n_structure_contract_sha256??null;
      if(nContract!==null&&(!sha64(nContract)||view.n_structure_contract_sha256!==nContract))throw Error('N型规则身份冲突');
      for(const value of [history,company])if(value.symbol!==meta.symbol||value.data_date!==bound.source_date.replaceAll('-','')||value.source_generation!==meta.generation||value.input_sha256!==meta.input_sha256||value.numeric_manifest?.sha256!==meta.numeric_manifest.sha256||value.source_candidate?.sha256!==meta.reused_candidate_sha256||value.historical_PIT!==false||value.RESEARCH_ONLY!==true||['production_allowed','buy_gate_updated','orders_sent'].some(k=>value[k]!==false))throw Error('单股研究资料身份冲突');
      if(company.f10?.concepts?.map(c=>c.name).join('、')!==view.concept_snapshot.kb_concepts||company.f10?.captured_at!==view.concept_snapshot.captured_at)throw Error('单股概念来源身份冲突');
      const byDate=new Map;for(let i=0;i<view.rows.length;i++){const row=view.rows[i],n=row.confirmed_kb_diagnostics?.kb_n_structure;if(!Number.isInteger(row.trade_date)||byDate.has(row.trade_date)||!row.kb||!row.original||!row.hold_score||!row.supplemental||row.trade_date!==projection.data.rows[i].trade_date||row.yidong?.kb_yidong_rule_sha256!==meta.yidong_contract_sha256||meta.confirmed_gap&&(!row.confirmed_kb_fields||!row.confirmed_kb_diagnostics||Object.keys(row.confirmed_kb_diagnostics).length!==(nContract?25:24)||!row.confirmed_kb_reused||JSON.stringify(Object.keys(row.confirmed_kb_fields).sort())!==JSON.stringify(CONFIRMED_GAP_FIELDS.map(x=>x[0]).sort()))||nContract&&(!n||n.rule_sha256!==nContract||n.state!==(row.hold_score.kb_hold_trend_up===true?'TREND_UP':row.hold_score.kb_hold_trend_up_reason)))throw Error('单股日期或评分数据无效');actionPresentation(row.action,meta.action_contract_sha256);byDate.set(row.trade_date,row)}
      if(!byDate.has(20261030))throw Error('单股目标日期缺失');
      if(!bindVersion(requested,'candidate_generation',meta.candidate_generation))return;
      active={view,projection,byDate,meta,assets:{history,company}};select.min=iso(view.rows[0].trade_date);select.max=iso(view.rows.at(-1).trade_date);
      const selected=routeDate(),chosen=selected&&/^\d{4}-\d{2}-\d{2}$/.test(selected)?Number(selected.replaceAll('-','')):null;
      if(selected&&!byDate.has(chosen))unavailable(selected);else paint(selected?chosen:view.rows.at(-1).trade_date);
      loadDetails(bound,meta,signal,{history,company});
      const html=new URL(meta.assets.html.url,location.origin);if(html.origin!==location.origin||html.searchParams.get('sha256')!==meta.assets.html.sha256||!sha64(meta.assets.html.sha256))throw Error('单股原图身份冲突');
      frame.onload=()=>bindFrame(mine,bound);frame.src=html.href;
      status.textContent='原式图载入中 · 来源10/30 / 观察11/2';
    }catch(error){if(isCurrent(mine,bound)&&error.name!=='AbortError'){status.textContent='单股研究暂不可用 · '+error.message;frame.src='about:blank'}}
  }
  const openSymbol=(value,name)=>{if(!validSymbol(value)||!day)return;if(name)stocks[value]=name;else if(!stocks[value])stocks[value]=value;const same=new URL(location.href).searchParams.get('symbol')===value;symbol=value;if(!same)writeRoute(value,null,null);open()};
  $('kbSingleOpen').onclick=()=>openSymbol('002865.SZ');$('kbSingleGold').onclick=()=>openSymbol('301048.SZ');$('kbSingleEdan').onclick=()=>openSymbol('300206.SZ');$('kbSingleBack').onclick=()=>{clear();status.textContent='选择股票查看单股研究'};
  $('kbSingleVersionLatest').onclick=()=>{const url=new URL(location.href);url.searchParams.delete('candidate_generation');url.searchParams.delete('panel_generation');url.searchParams.delete('view_generation');history.replaceState(history.state,'',url.href);open()};
  select.onchange=()=>selectDate(select.value.replaceAll('-',''));
  $('kbSingleLatest').onclick=()=>{if(active)selectDate(active.hk?active.meta.source_date:active.scoped?active.meta.last_date:active.view.rows.at(-1).trade_date,{latest:true})};
  for(const button of host.querySelectorAll('[data-kb-window]'))button.onclick=()=>{const w=frame.contentWindow,s=w?.RESEARCH_PANEL_STATE;if(!active||!s?.rows?.length)return;const value=button.dataset.kbWindow==='all'?s.rows.length:Number(button.dataset.kbWindow),count=Math.min(value,s.rows.length),chosen=Number(select.value.replaceAll('-','')),i=s.rows.findIndex(row=>row.trade_date===chosen),end=i<0||i===s.rows.length-1?s.rows.length:Math.min(s.rows.length,i+Math.floor(count*.7));w.setOriginalWindow?.(count,end);if(i>=0)w.choose?.(i);w.paint?.()};
  return {openSymbol,clear,refresh(){if(active&&!active.hk&&day&&!request?.signal.aborted)loadDetails(day,active.meta,request.signal,active.assets)},bindDay(value){const same=day?.source_date===value?.source_date,focused=document.body.classList.contains('kb-single-focus');day=value;host.hidden=!value?.source_date;if(!host.hidden&&(!same||focused)){if(!same){const wanted=new URLSearchParams(location.search).get('symbol');symbol=validSymbol(wanted)?wanted:'002865.SZ';if(!stocks[symbol])stocks[symbol]=symbol}open()}},unbindDay(){clear();day=null;host.hidden=true}};
}
export function f10SourceKind(value,day,meta){
  if(!value||value.symbol!==meta.symbol||value.data_date!==day.source_date.replaceAll('-','')||value.historical_PIT!==false||
    value.RESEARCH_ONLY!==true||['production_allowed','buy_gate_updated','orders_sent'].some(k=>value[k]!==false)||!sha64(value.stock_ref?.sha256))return null;
  if(['OBSERVED','PARTIAL_SOURCE_COMPONENTS'].includes(value.status)&&value.source_generation===day.generation&&value.input_sha256===day.input_sha256)return 'CANONICAL';
  if(meta.schema==='v4.workbench.generic_single_research.v1'&&value.status==='OBSERVED_CANDIDATE'&&
    value.lineage==='REGISTERED_ISOLATED_PAIRED_CANDIDATE'&&value.source_generation===meta.panel_generation&&
    value.input_sha256===meta.candidate_input_sha256&&value.bound_source_generation===day.generation&&
    value.bound_source_input_sha256===day.input_sha256)return 'CANDIDATE';
  if(meta.schema==='v4.workbench.generic_single_research.v1'&&meta.action_rebound===true&&value.status==='OBSERVED_CANDIDATE'&&
    value.lineage==='REGISTERED_ISOLATED_PAIRED_CANDIDATE_REUSED'&&value.source_generation===meta.asset_candidate_generation&&
    value.input_sha256===meta.asset_candidate_input_sha256&&value.logical_candidate_generation===meta.panel_generation&&
    sha64(meta.action_rebind_equivalence_sha256)&&value.reuse_equivalence_sha256===meta.action_rebind_equivalence_sha256&&
    value.bound_source_generation===day.generation&&value.bound_source_input_sha256===day.input_sha256)return 'CANDIDATE';
  if(meta.schema==='v4.workbench.generic_single_research.v1'&&meta.status==='UNKNOWN_SOURCE_ADMISSION'&&
    value.status==='OBSERVED_INDEPENDENT_COMPANY'&&value.lineage==='REGISTERED_INDEPENDENT_COMPANY_WITHOUT_PRICE_ADMISSION'&&
    value.source_generation===null&&value.input_sha256===null&&value.price_panel_admission==='NOT_ASSERTED'&&
    value.bound_source_generation===day.generation&&value.bound_source_input_sha256===day.input_sha256)return 'INDEPENDENT';
  return null;
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

export function verifiedCompanyPart(value,checks={},sources={}){
  if(!value||typeof value!=='object')return {};
  if(value.evidence_status==='OFFICIAL_FILING'){
    const url=value.source_url??value.latest_financial_source_url??value.holder_source_url;
    return checks.official_quarterly==='VERIFIED'&&typeof url==='string'&&url===sources.official_quarterly?.url?value:{};
  }
  return checks.tdx_f10==='VERIFIED'?value:{};
}

export function visibleSingleHistoryGroups(groups){
  if(!Array.isArray(groups))throw Error('单股历史统计缺失');
  return groups.filter(group=>!['original_b1','original_b2','original_b3'].includes(group.group_id));
}
