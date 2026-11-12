// A display projection of the existing, receipt-verified same-origin API.
const compact=value=>String(value??'').replaceAll('-','');
const sha=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
const reference=value=>typeof value?.path==='string'&&value.path.startsWith('/')&&sha(value.sha256);
const sameRef=(a,b)=>a?.path===b?.path&&a?.sha256===b?.sha256;
const safe=value=>value?.RESEARCH_ONLY===true&&['production_allowed','buy_gate_updated','orders_sent'].every(key=>value[key]===false);
const finite=value=>typeof value==='number'&&Number.isFinite(value);
const percent=value=>(value>0?'+':'')+value.toFixed(2)+'%';
function nativeBoards(value){
 const native=value.native_board_snapshot,session=value.us_session_date;
 if(native?.schema_version!=='v3_5.futu_us_native_board_snapshot.v2'||!safe(native)
   ||!['READY','PARTIAL'].includes(native.status)||native.market!=='US'||native.timezone!=='America/New_York'
   ||native.capture_session_date!==session||!sha(native.source_response_sha256)||!sha(native.registry_sha256)
   ||!Number.isSafeInteger(native.requested_board_count)||native.requested_board_count<1
   ||!Number.isSafeInteger(native.available_board_count)||native.available_board_count<0
   ||native.available_board_count>native.requested_board_count||!Array.isArray(native.rows))throw Error('US_NATIVE_SNAPSHOT_UNBOUND');
 const counts=new Map;for(const row of native.rows)counts.set(row?.board_code,(counts.get(row?.board_code)??0)+1);
 const rows=[],quarantined=[];
 for(const row of native.rows){
  const flagsWrong=['RESEARCH_ONLY','production_allowed','buy_gate_updated','orders_sent'].some(key=>Object.hasOwn(row??{},key)&&row[key]!==native[key]);
  if(!row||flagsWrong||!/^US\.LIST\d+$/.test(row.board_code??'')||row.board_id!==row.board_code||counts.get(row.board_code)!==1
    ||typeof row.board_name!=='string'||!row.board_name.trim()||row.board_name!==row.expected_board_name
    ||row.plate_valid!==true||row.status!=='READY'||row.membership_status!=='READY'||row.metric_kind!=='OFFICIAL_BOARD'
    ||!['INDUSTRY','CONCEPT'].includes(row.plate_type)||row.market!=='US'||row.timezone!=='America/New_York'
    ||row.session_date!==session||!String(row.update_time??'').startsWith(session.slice(0,4)+'-'+session.slice(4,6)+'-'+session.slice(6)+' ')
    ||!finite(row.change_pct)||!finite(row.last)||row.last<=0||!finite(row.previous_close)||row.previous_close<=0
    ||!sha(row.source_response_sha256)||!sha(row.membership_sha256)){
   quarantined.push({board_code:row?.board_code??null,reason:'ROW_DATE_PRICE_IDENTITY_OR_SOURCE_UNCONFIRMED'});continue;
  }
  const breadthValid=row.breadth_alignment==='ALIGNED'&&[row.rise_count,row.fall_count,row.equal_count,row.member_count].every(n=>Number.isSafeInteger(n)&&n>=0)
    &&row.rise_count+row.fall_count+row.equal_count===row.member_count;
  rows.push({name:row.board_name,change_pct:row.change_pct,kind:row.plate_type==='INDUSTRY'?'行业':'主题',board_code:row.board_code,
    up:breadthValid?row.rise_count:null,down:breadthValid?row.fall_count:null,breadth_status:row.breadth_alignment??'UNKNOWN',
    session_date:row.session_date,source_sha256:row.source_response_sha256,membership_sha256:row.membership_sha256});
 }
 rows.sort((a,b)=>b.change_pct-a.change_pct||a.name.localeCompare(b.name));
 return {rows,requested:native.requested_board_count,reported_available:native.available_board_count,reported_status:native.status,
   complete:rows.length===native.requested_board_count&&rows.length===native.available_board_count&&quarantined.length===0,
   quarantined,registry_sha256:native.registry_sha256,source_sha256:native.source_response_sha256};
}
export function usMarketContext(value,day){
 const target=compact(day.observation_date);
 if(value?.schema_version!=='v3_5.global_industries.v2'||!['READY','PARTIAL'].includes(value.status)
   ||!['research_date','target_date','target_trade_date'].every(key=>compact(value[key])===target)
   ||!safe(value)||value.write_policy!=='read_only'||value.recommendation_status!=='RESEARCH_ONLY'
   ||!reference(value.artifact)||!reference(value.manifest)||!reference(value.receipt)
   ||!sameRef(value.artifact.manifest,value.manifest)||!sameRef(value.artifact.receipt,value.receipt)
   ||!/^\d{8}$/.test(value.us_session_date??'')||value.us_session_date!==value.capture_session_date
   ||compact(value.source_date)!==value.us_session_date||!Array.isArray(value.provider_session_dates)
   ||!value.provider_session_dates.length||!value.provider_session_dates.every(date=>compact(date)===value.us_session_date)
   ||!Number.isFinite(Date.parse(value.captured_at))||value.capture_phase!=='POST_CLOSE'
   ||!Number.isSafeInteger(value.available_board_count)||!Number.isSafeInteger(value.requested_board_count)
   ||value.available_board_count<0||value.requested_board_count<1||value.available_board_count>value.requested_board_count)throw Error('US_CONTEXT_DATE_SAFETY_OR_PROVENANCE_CONFLICT');
 const native=nativeBoards(value),leaders=native.rows.filter(row=>row.change_pct>0).slice(0,3),laggards=native.rows.filter(row=>row.change_pct<0).slice(-3).reverse();
 const divided=leaders.find(row=>row.up!==null&&row.down>0&&row.down>=row.up);
 return {status:value.status,heading:`昨晚美股（纽约${value.us_session_date.slice(4,6)}/${value.us_session_date.slice(6)}收盘）`,
   summary:native.complete?`已核对${native.rows.length}个原生行业 / 主题板块`:`本次可读${native.rows.length}/${native.requested}个原生板块，其余待核`,
   native,leaders,laggards,dispersion:divided?`${divided.name}指数上涨${percent(divided.change_pct)}，成分股${divided.up}涨、${divided.down}跌，表现有分化。`:'板块指数涨跌不代表所有成分股同向，也不等同A股公司直接受益。',
   source_asof:`${value.us_session_date} America/New_York · ${value.capture_phase}`,recorded_at:value.captured_at,recorded_label:'采集',
   limitation:`${(value.cannot_confirm??[]).join('；')||'API未列附加缺口'}；仅作环境参考，公司关联仍 ${value.a_share_relation_status??'CANNOT_CONFIRM'}，不认证全覆盖或买点`,
   source:{artifact:value.artifact,manifest:value.manifest,receipt:value.receipt},research_date:target,
   technical:{overall_api_status:value.status,legacy_theme_matching:`${value.available_board_count}/${value.requested_board_count}`,native_reported_status:native.reported_status,
     native_reported_available:native.reported_available,native_verified:native.rows.length,native_requested:native.requested,quarantined:native.quarantined}};
}
export function unknownUsContext(reason){return {status:'UNKNOWN',heading:'美股板块',summary:'本卡暂未取得对应交易日的板块涨跌，暂不能判断强弱。',technical:{reason},limitation:'CANNOT_CONFIRM；未采用其他日期替代'};}
const changeText=value=>value>0?'涨'+value.toFixed(2)+'%':value<0?'跌'+Math.abs(value).toFixed(2)+'%':'持平';
const beijing=value=>new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value));
export function observationMarketContext(snapshot,day){
 if(!snapshot)return null;
 if(snapshot.schema!=='OBSERVATION_SNAPSHOT_VIEW_V1'||!safe(snapshot)||snapshot.source_date!==day.source_date||snapshot.observation_date!==day.observation_date
   ||snapshot.source_generation!==day.generation||snapshot.input_sha256!==day.input_sha256)throw Error('MARKET_OBSERVATION_IDENTITY_CONFLICT');
 const values=snapshot.context??{},result={identity:day,japan:null,benchmarks:null,usMarket:null};
 const jp=values.japan;
 if(jp){
  const valid=jp.schema==='V4_WORKBENCH_JAPAN_V1'&&safe(jp)&&jp.status==='DATED_INDEX_OBSERVATION'&&jp.observation_date===day.observation_date
   &&jp.symbol==='JP..N225'&&jp.timezone==='Asia/Tokyo'&&jp.source_asof?.startsWith(day.observation_date+'T')&&jp.source_asof.endsWith('+09:00')
   &&Number.isFinite(Date.parse(jp.source_asof))&&Date.parse(jp.source_asof)<=Date.parse(jp.recorded_at)
   &&finite(jp.value)&&jp.value>0&&finite(jp.previous_close)&&jp.previous_close>0&&finite(jp.change_pct)
   &&Math.abs((jp.value/jp.previous_close-1)*100-jp.change_pct)<.001&&sha(jp.raw_sha256)&&reference(jp.raw_ref);
  result.japan=valid?{...jp,summary:'日本日经225 '+changeText(jp.change_pct),source_time_beijing:beijing(jp.source_asof)}:{status:'UNKNOWN',summary:'本卡暂未取得可核对的日本今日涨跌。',technical:jp};
 }
 const us=values.us_benchmarks;
 if(us){
  const required=['.DJI','.SPX','.IXIC'];
  const closeTime=Date.parse(us.session_close_at),closeDate=Number.isFinite(closeTime)?new Date(closeTime):null;
  const closeSession=closeDate?new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(closeDate).replaceAll('-',''):null;
  const closeClock=closeDate?new Intl.DateTimeFormat('en-GB',{timeZone:'America/New_York',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(closeDate):null;
  const calendarBound=reference(us.calendar_ref)&&closeSession===us.us_session_date&&['13:00:00','16:00:00'].includes(closeClock);
  const captureDate=Number.isFinite(closeTime)?new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(closeTime+15*60000)).replaceAll('-',''):compact(day.observation_date);
  const bound=us.schema==='V4_WORKBENCH_US_BENCHMARKS_V1'&&safe(us)&&us.observation_date===day.observation_date&&reference(us.raw_ref)
   &&['DATED_US_BENCHMARKS','PARTIAL'].includes(us.status)&&/^\d{8}$/.test(us.us_session_date??'')&&calendarBound;
  const rows=bound&&Array.isArray(us.rows)?us.rows.filter(row=>required.includes(row.symbol)&&row.status==='DATED_CLOSE'
   &&row.session_date===us.us_session_date&&row.timezone==='America/New_York'&&finite(row.value)&&row.value>0&&finite(row.previous_close)&&row.previous_close>0&&finite(row.change_pct)
   &&Math.abs((row.value/row.previous_close-1)*100-row.change_pct)<.015&&sha(row.raw_sha256)
   &&Number.isFinite(Date.parse(row.source_asof))&&Date.parse(row.source_asof)<=Date.parse(row.read_at)
   &&new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(row.source_asof)).replaceAll('-','')===us.us_session_date
   &&(us.session_close_at?reference(us.calendar_ref)&&row.source_asof===us.session_close_at:new Intl.DateTimeFormat('en-GB',{timeZone:'America/New_York',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date(row.source_asof))==='16:00:00')
   &&row.source_url?.startsWith('https://www.futunn.com/index/'+row.symbol+'-US')):[];
  const complete=bound&&rows.length===3&&new Set(rows.map(row=>row.symbol)).size===3&&us.status==='DATED_US_BENCHMARKS';
  const direction=complete?(rows.every(row=>row.change_pct>0)?'三大指数齐涨':rows.every(row=>row.change_pct<0)?'三大指数齐跌':'三大指数涨跌不一'):'三大指数资料未齐';
  const carried=captureDate!==compact(day.observation_date),label=carried?`最近美股收盘${us.us_session_date.slice(4,6)}/${us.us_session_date.slice(6)} · A观察${day.observation_date.slice(5).replace('-','/')}`:null;
  result.benchmarks={...us,rows,complete,heading:(carried?'最近美股收盘：':'昨晚美股：')+direction,session_label:label};
  if(bound&&us.market_context?.us_session_date===us.us_session_date&&us.oracle
    &&us.oracle.research_date===captureDate&&(!us.oracle.observation_date||us.oracle.observation_date===day.observation_date)
    &&us.oracle.session_date===us.us_session_date&&sha(us.oracle.response_sha256)
    &&['artifact','manifest','receipt'].every(key=>sameRef(us.market_context[key],us.oracle[key]))){
   try{result.usMarket=usMarketContext(us.market_context,{...day,observation_date:captureDate});result.usMarket.artifact_research_date=captureDate;result.usMarket.observation_date=day.observation_date;}catch{ /* Bad native projection cannot erase independently valid benchmarks. */ }
  }
 }
 return result;
}
function koreaLines(value,day){
 if(!['DATED_INDEX_OBSERVATION','PARTIAL'].includes(value.status)||!reference(value.source))return null;
 const summary=value.summary??'',suffix=' · 后到留档',separator=' / ^KQ11 ';
 if(!summary.endsWith(suffix)||!summary.startsWith('^KS11 ')||!summary.includes(separator))return null;
 const split=summary.indexOf(separator),parts=[summary.slice(0,split),'^KQ11 '+summary.slice(split+separator.length,-suffix.length)];
 const stamps=(value.source_asof??'').split(' / ');
 const names=['韩国大盘（KOSPI）','韩国创业板（KOSDAQ）'],codes=['^KS11','^KQ11'];
 const parsed=parts.map((part,index)=>{
  const match=/^(\^KS11|\^KQ11) (\d+(?:\.\d+)?) \(([+-]?\d+(?:\.\d+)?)%\)$/.exec(part),stamp=stamps[index];
  const valid=match&&match[1]===codes[index]&&Number.isFinite(Number(match[2]))&&Number(match[2])>0&&Number.isFinite(Number(match[3]))
    &&typeof stamp==='string'&&stamp.startsWith(day.observation_date+'T')&&stamp.endsWith('+09:00')&&Number.isFinite(Date.parse(stamp))&&Date.parse(stamp)<=Date.parse(value.recorded_at);
  return {line:names[index]+(valid?changeText(Number(match[3])):'暂未取得今日涨跌'),time:valid?stamp.slice(11,16):'暂缺',valid};
 });
 return parsed.some(row=>row.valid)?parsed:null;
}
export function renderMarketCard(host,market,value,day,doc=document){
 const add=(parent,tag,text)=>{const n=doc.createElement(tag);if(text!==undefined)n.textContent=String(text);parent.append(n);return n;};
 const card=add(host,'div');card.className='market-card';
 if(market==='US'){
  const benchmarks=value.benchmarks;
  add(card,'strong',benchmarks?.heading??'昨晚美股：三大指数资料未齐');
  if(benchmarks?.session_label)add(card,'p',benchmarks.session_label);
  if(benchmarks?.rows?.length){const names={'.DJI':'道指','.SPX':'标普','.IXIC':'纳指'};add(card,'p',['.DJI','.SPX','.IXIC'].map(code=>{const row=benchmarks.rows.find(row=>row.symbol===code);return names[code]+' '+(row?percent(row.change_pct):'暂缺');}).join('｜')+`（${benchmarks.us_session_date.slice(4,6)}/${benchmarks.us_session_date.slice(6)}收盘）`);}
  if(value.native?.rows.length){
   const line=rows=>rows.map(row=>row.name+' '+percent(row.change_pct)).join('、');
   add(card,'p','领涨 ↑：'+(value.leaders.length?line(value.leaders):'已取得板块中暂无上涨记录')).className='up';
   add(card,'p','领跌 ↓：'+(value.laggards.length?line(value.laggards):'已取得板块中暂无下跌记录')).className='down';
   add(card,'p',value.dispersion);
   const all=add(card,'details');add(all,'summary',`查看全部${value.native.rows.length}个板块`);const list=add(all,'ul');
   for(const row of value.native.rows)add(list,'li',`${row.name}（${row.kind}） ${percent(row.change_pct)}${row.up!==null?' · '+row.up+'涨 / '+row.down+'跌':' · 成分涨跌家数待核'}`);
  }
 }else{
  const kr=market==='KR'?koreaLines(value,day):null,jp=value.schema==='V4_WORKBENCH_JAPAN_V1'&&value.status==='DATED_INDEX_OBSERVATION'&&finite(value.change_pct)&&finite(value.value)&&typeof value.source_time_beijing==='string';
  add(card,'strong',market==='JP'?(jp?value.summary:'日本大盘（日经225）'):(kr?.[0].line??'韩国大盘（KOSPI / KOSDAQ）'));
  if(market==='JP'&&jp){add(card,'p',`日本当地 ${value.source_asof.slice(11,16)}（北京时间 ${value.source_time_beijing}）· 指数 ${value.value.toFixed(2)}`);add(card,'p','本次读取 '+beijing(value.recorded_at)+' 北京时间；后到观察，不回写08:00原节点。');}
  else if(kr){add(card,'p',kr[1].line);add(card,'p',`来源：Yahoo；韩国时点 KOSPI ${kr[0].time} / KOSDAQ ${kr[1].time}，本次读取 ${beijing(value.recorded_at)} 北京时间。`);}
  else add(card,'p',market==='KR'?'暂未取到今日涨跌；当前富途程序接口不识别韩国代码，原来源读取失败。':'本卡尚未接入今日涨跌，暂不能判断上涨还是下跌。');
  add(card,'p',market==='JP'?'日经225用于观察日本大盘。':'KOSPI观察韩国综合大盘，KOSDAQ观察成长与创业板市场；缺数据不代表市场下跌。');
 }
 const details=add(card,'details');add(details,'summary','来源、时间与技术状态');
 if(value.recorded_at)add(details,'p','原采集时间：'+value.recorded_at);
 if(value.source_asof)add(details,'p','来源时点：'+value.source_asof);
 add(details,'pre',JSON.stringify({selected_source_date:day.source_date,observation_date:day.observation_date,status:value.status,technical:value.technical??null,
   original_summary:market==='US'?undefined:value.summary,limitation:value.limitation,provider:value.provider,source:value.source,raw_ref:value.raw_ref,raw_sha256:value.raw_sha256,source_code_authority:value.source_code_authority,native_rows:value.native?.rows,benchmarks:value.benchmarks},null,2));
 return card;
}
