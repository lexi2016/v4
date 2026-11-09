import {loadProjection} from './dot/src/projection-view.mjs';
import {actionPresentation,signalSummary,signalExplanations,confirmedGapPresentation,brickCountPresentation,nStructurePresentation,CONFIRMED_GAP_FIELDS,HOLD_ITEMS,HOLD_REASONS} from './kb-signal-view.mjs';
import {installKbOverlay} from './kb-chart-overlay.mjs';

const $=id=>document.getElementById(id);
const node=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n};
const sha64=s=>typeof s==='string'&&/^[a-f0-9]{64}$/.test(s);
const iso=value=>String(value).replace(/^(\d{4})(\d{2})(\d{2})$/,'$1-$2-$3');
const label=(v,flag=false)=>v===null||v===undefined?'待确认':v===true||flag&&v===1?'是':v===false||flag&&v===0?'否':String(v);
export function singleSelectionHref(href,symbol,stockDate=null,version=undefined){
  if(!/^\d{6}\.(SH|SZ|BJ)$/.test(symbol))throw Error('单股证券无效');
  if(stockDate!==null&&!/^\d{4}-\d{2}-\d{2}$/.test(stockDate))throw Error('单股日期无效');
  const url=new URL(href),same=url.searchParams.get('symbol')===symbol;url.searchParams.set('symbol',symbol);
  if(stockDate===null)url.searchParams.delete('stock_date');else url.searchParams.set('stock_date',stockDate);
  if(version===null||!same&&version===undefined){url.searchParams.delete('candidate_generation');url.searchParams.delete('panel_generation')}
  else if(version!==undefined){if(!['candidate_generation','panel_generation'].includes(version?.key)||!sha64(version?.value))throw Error('单股版本无效');
    url.searchParams.delete('candidate_generation');url.searchParams.delete('panel_generation');url.searchParams.set(version.key,version.value)}
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
  const data=new Uint8Array(await response.arrayBuffer());if(data.length!==ref.bytes)throw Error('单股数据长度不符');
  const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',data))].map(v=>v.toString(16).padStart(2,'0')).join('');if(hash!==ref.sha256)throw Error('单股数据校验失败');
  const plain=await decodeBoundGzip(data,ref.decoded_bytes);
  return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(plain));
}

export function installSingleResearch({loadDetails=()=>{}}={}){
  const host=$('kbSingleResearch'),body=$('kbSingleBody'),status=$('kbSingleStatus'),frame=$('kbSingleChart'),select=$('kbSingleDate');
  const stocks={'002865.SZ':'钧达股份','301048.SZ':'金鹰重工','300206.SZ':'理邦仪器'};
  let day=null,active=null,request=null,serial=0,dateSerial=0,observer=null,overlayCleanup=null,symbol='002865.SZ';
  const dailyIds=['kbSingleScore','kbSingleScoreItems','kbSingleActions','kbSingleActionReasons','kbSingleChips','kbSingleGroups','kbSingleSignalReasons','kbSingleUnknownItems'];
  const clearDaily=()=>{for(const id of dailyIds)$(id)?.replaceChildren();$('kbSingleVolume').textContent='';$('kbSingleSelected').textContent='';$('kbSingleUnknown').hidden=true;};
  const clear=()=>{++serial;++dateSerial;request?.abort();request=null;observer?.disconnect();observer=null;overlayCleanup?.();overlayCleanup=null;active=null;frame.src='about:blank';frame.hidden=true;body.hidden=true;clearDaily();for(const id of ['kbSingleHistory','kbSingleCompany','kbSingleFinancial'])$(id)?.replaceChildren();select.value='';$('kbSingleDateStatus').textContent='';$('kbSingleVersionLatest').hidden=true;document.body.classList.remove('kb-single-focus');window.RelatedReports?.clear();if($('relatedReports'))$('relatedReports').hidden=true;};
  const routeDate=()=>new URL(location.href).searchParams.get('stock_date');
  const writeRoute=(code,date=null,version=undefined)=>history.replaceState(history.state,'',singleSelectionHref(location.href,code,date,version));
  function versionAvailable(key,value){
    if(!sha64(value))throw Error('研究版本身份无效');
    const params=new URL(location.href).searchParams,other=key==='candidate_generation'?'panel_generation':'candidate_generation';
    const pinned=params.get(key);if(params.has(other)||pinned!==null&&pinned!==value){
      clearDaily();frame.hidden=true;body.hidden=true;$('kbSingleVersionLatest').hidden=false;
      status.textContent='所选研究版本已变或不可用，请主动查看最新版本。';return false}
    return true;
  }
  function bindVersion(code,key,value){
    const url=new URL(location.href);if(symbol!==code||url.searchParams.get('symbol')&&url.searchParams.get('symbol')!==code)return false;
    if(!versionAvailable(key,value))return false;
    url.searchParams.set('symbol',code);url.searchParams.delete(key==='candidate_generation'?'panel_generation':'candidate_generation');
    url.searchParams.set(key,value);history.replaceState(history.state,'',url.href);return true;
  }
  function unavailable(date){clearDaily();frame.hidden=true;select.setAttribute('aria-invalid','true');
    $('kbSingleDateStatus').textContent=String(date)+' 无已绑定交易数据，不自动替换日期。';}
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
  function selectDate(date,{move=true,latest=false}={}){
    if(!active)return;const chosen=iso(date);if(!/^\d{4}-\d{2}-\d{2}$/.test(chosen)){unavailable(chosen);return}
    writeRoute(symbol,latest?null:chosen);if(active.scoped){paintScopedDate(Number(chosen.replaceAll('-','')));return}const row=active.byDate.get(Number(chosen.replaceAll('-','')));if(!row){unavailable(chosen);return}
    frame.hidden=false;
    const w=frame.contentWindow,s=w?.RESEARCH_PANEL_STATE,i=s?.rows?.findIndex(r=>Number(r.trade_date)===Number(date));
    if(move&&i>=0&&w.setOriginalWindow){const count=Math.min(120,s.rows.length);w.setOriginalWindow(count,i===s.rows.length-1?s.rows.length:Math.min(s.rows.length,i+Math.floor(count*.7)));w.choose(i)}
    paint(row.trade_date);w?.paint?.();
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
      frame.hidden=false;w.setOriginalWindow?.(count,end);w.choose?.(index);w.paint?.();paint(state.rows[index].trade_date);
      status.textContent=`来源 ${day.source_date} · 观察 ${day.observation_date} · ${stocks[symbol]}单股研究`;
    };
    observer=new MutationObserver(ready);observer.observe(doc.documentElement,{attributes:true,attributeFilter:['data-loaded']});ready();
  }
  function dailyMode(enabled){
    for(const child of [...body.children].slice(1))child.hidden=enabled;
    host.querySelector('.kb-single-head > div:last-child').hidden=enabled;
    host.querySelector('.eyebrow').textContent=enabled?'五分评分与持仓研究建议':'单股研究';
    host.querySelector('.kb-single-meta').textContent=`数据截至 ${day.source_date} 收盘 · 不改变原有候选名单`;
    if(enabled)document.body.classList.remove('kb-single-focus');
  }
  function paintDaily(meta,bound){
    if(meta.symbol!==symbol||meta.source_date!==bound.source_date||meta.generation!==bound.generation||meta.input_sha256!==bound.input_sha256||meta.numeric_manifest?.sha256!==bound.numeric_manifest?.sha256||meta.numeric_manifest?.path!==bound.numeric_manifest?.path||meta.historical_PIT!==false||meta.RESEARCH_ONLY!==true||['production_allowed','buy_gate_updated','orders_sent'].some(k=>meta[k]!==false))throw Error('评分来源身份冲突');
    dailyMode(true);body.hidden=false;frame.hidden=true;host.hidden=false;active={daily:true,meta};
    const row=meta.row,score=row?.hold_score;
    $('kbSingleSelected').textContent=bound.source_date;
    if(meta.status!=='MATERIALIZED'||!score){
      $('kbSingleScore').textContent='持股评分：待核';
      $('kbSingleActions').replaceChildren(node('p','无持仓：待核'),node('p','有持仓：待核'));
      $('kbSingleActionReasons').replaceChildren(node('p','本日评分未物化：'+(meta.reason??'来源待核')));
      status.textContent=`${symbol} · ${bound.source_date} · 评分来源待核`;return;
    }
    if(String(row.trade_date)!==bound.source_date.replaceAll('-','')||!sha64(meta.score_row_sha256)||row.cache_identity?.rules?.['a_share_kb_action_v1.json']!==meta.action_contract_sha256)throw Error('评分日期或规则身份冲突');
    const action=actionPresentation(row.action,meta.action_contract_sha256);
    $('kbSingleScore').textContent=score.kb_hold_score===null?`持股评分：已确认${score.kb_hold_score_min}分 / 总分待核（${score.kb_hold_score_min}～${score.kb_hold_score_max}/5）`:`持股评分：${score.kb_hold_score}/5`;
    $('kbSingleActions').replaceChildren(...[['无持仓',action.flat],['有持仓',action.held]].map(([label,value])=>{const p=node('p');p.append(node('span',label+'：'),node('strong',value));return p}));
    $('kbSingleActionReasons').replaceChildren(...action.reasons.map(text=>node('p',text)));
    $('kbSingleScoreItems').replaceChildren(...HOLD_ITEMS.map(([key,title])=>node('p',title+'：'+(score[key]===null?'待核 · '+(HOLD_REASONS[score[key+'_reason']]??score[key+'_reason']??'来源待核'):score[key]?'1分':'0分'))));
    const n=row.n_structure;if(n)$('kbSingleScoreItems').append(node('p',`N形状态：${n.state} · 结构确认 ${n.structure_known_at??'待核'}`));
    $('kbSingleScoreItems').append(node('p',`KB指标：BBI ${label(score.kb_hold_bbi)} · K ${label(score.kb_hold_k)} · D ${label(score.kb_hold_d)} · J ${label(row.kb?.kb_b1_j)}`));
    const chips=Object.entries(row.kb??{}).filter(([key,value])=>['kb_b1','kb_b2','kb_b3','kb_violence_k','kb_fanbao'].includes(key)&&value===true);
    $('kbSingleChips').replaceChildren(...(chips.length?chips.map(([key])=>node('span',key.replace('kb_','').toUpperCase())):[node('span','当日无已确认命中信号')]));
    status.textContent=`${symbol} · ${bound.source_date} · 原五项评分与两种持仓研究建议 · 仅供研究`;
  }
  async function open(){
    if(!day)return;clear();const bound=day,mine=serial,requested=symbol;request=new AbortController();const signal=request.signal;
    $('kbSingleName').textContent=stocks[requested];$('kbSingleCode').textContent=requested;frame.title=stocks[requested]+'原式研究图';
    dailyMode(bound.source_date!=='2026-10-30');if(bound.source_date==='2026-10-30')document.body.classList.add('kb-single-focus');body.hidden=false;status.textContent='正在核对单股数据和原式图…';
    try{
      const url='/api/v4/research/workbench/days/'+bound.source_date+'/single-research/'+requested+'?'+new URLSearchParams({revision:bound.generation});
      const response=await fetch(url,{signal,credentials:'same-origin',redirect:'error',cache:'no-store'});if(!response.ok)throw Error('单股候选尚未接入');const meta=await response.json();
      if(!isCurrent(mine,bound))return;
      if(typeof meta.name==='string'&&meta.name){stocks[requested]=meta.name;$('kbSingleName').textContent=meta.name;frame.title=meta.name+'原式研究图'}
      if(meta.schema==='v4.workbench.daily_kb_research.v1'){paintDaily(meta,bound);return}
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
  const openSymbol=(value,name)=>{if(!/^\d{6}\.(SH|SZ|BJ)$/.test(value)||!day)return;if(name)stocks[value]=name;else if(!stocks[value])stocks[value]=value;const same=new URL(location.href).searchParams.get('symbol')===value;symbol=value;if(!same)writeRoute(value,null,null);open()};
  $('kbSingleOpen').onclick=()=>openSymbol('002865.SZ');$('kbSingleGold').onclick=()=>openSymbol('301048.SZ');$('kbSingleEdan').onclick=()=>openSymbol('300206.SZ');$('kbSingleBack').onclick=()=>{clear();status.textContent='选择股票查看单股研究'};
  $('kbSingleVersionLatest').onclick=()=>{const url=new URL(location.href);url.searchParams.delete('candidate_generation');url.searchParams.delete('panel_generation');history.replaceState(history.state,'',url.href);open()};
  select.onchange=()=>selectDate(select.value.replaceAll('-',''));
  $('kbSingleLatest').onclick=()=>{if(active)selectDate(active.scoped?active.meta.last_date:active.view.rows.at(-1).trade_date,{latest:true})};
  for(const button of host.querySelectorAll('[data-kb-window]'))button.onclick=()=>{const w=frame.contentWindow,s=w?.RESEARCH_PANEL_STATE;if(!active||!s?.rows?.length)return;const value=button.dataset.kbWindow==='all'?s.rows.length:Number(button.dataset.kbWindow),count=Math.min(value,s.rows.length),chosen=Number(select.value.replaceAll('-','')),i=s.rows.findIndex(row=>row.trade_date===chosen),end=i<0||i===s.rows.length-1?s.rows.length:Math.min(s.rows.length,i+Math.floor(count*.7));w.setOriginalWindow?.(count,end);if(i>=0)w.choose?.(i);w.paint?.()};
  return {openSymbol,clear,refresh(){if(active?.daily&&day)open();else if(active&&day&&!request?.signal.aborted)loadDetails(day,active.meta,request.signal,active.assets)},bindDay(value){const same=day?.source_date===value?.source_date&&day?.generation===value?.generation&&day?.input_sha256===value?.input_sha256,focused=document.body.classList.contains('kb-single-focus');day=value;host.hidden=!value?.source_date;if(!same&&value?.source_date!=='2026-10-30'){clear();if(value){host.hidden=false;dailyMode(true);status.textContent='选择股票查看本日五分评分与持仓研究建议'}}if(!host.hidden&&(!same||focused)&&value.source_date==='2026-10-30'){if(!same){const wanted=new URLSearchParams(location.search).get('symbol');symbol=/^\d{6}\.(SH|SZ|BJ)$/.test(wanted??'')?wanted:'002865.SZ';if(!stocks[symbol])stocks[symbol]=symbol}open()}},unbindDay(){clear();day=null;host.hidden=true}};
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
