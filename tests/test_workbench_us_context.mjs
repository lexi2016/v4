import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {usMarketContext,unknownUsContext,renderMarketCard,observationMarketContext} from '../research/stock_panel_collab_20261030/mac-host/workbench-us-context.mjs';
const day={source_date:'2026-11-04',observation_date:'2026-11-05',generation:'a'.repeat(64),input_sha256:'b'.repeat(64)};
const ref=name=>({path:'/saved/'+name,sha256:'c'.repeat(64)});
function foreignSnapshot(){return {schema:'OBSERVATION_SNAPSHOT_VIEW_V1',source_date:day.source_date,observation_date:day.observation_date,source_generation:day.generation,input_sha256:day.input_sha256,RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false,context:{
 japan:{schema:'V4_WORKBENCH_JAPAN_V1',observation_date:'2026-11-05',status:'DATED_INDEX_OBSERVATION',symbol:'JP..N225',timezone:'Asia/Tokyo',source_asof:'2026-11-05T11:30:00+09:00',recorded_at:'2026-11-05T10:44:00+08:00',value:61913.51,previous_close:62188.63,change_pct:-.4424,raw_sha256:'c'.repeat(64),raw_ref:ref('raw'),RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false},
 us_benchmarks:{schema:'V4_WORKBENCH_US_BENCHMARKS_V1',observation_date:'2026-11-05',status:'DATED_US_BENCHMARKS',us_session_date:'20261104',raw_ref:ref('raw'),oracle:{research_date:'20261105',session_date:'20261104',response_sha256:'c'.repeat(64),artifact:ref('api'),manifest:ref('manifest'),receipt:ref('receipt')},RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false,
 rows:[['.DJI',53356.12,51786.72,3.03],['.SPX',7688.62,7568.92,1.58],['.IXIC',25736.513,25371.48,1.44]].map(([symbol,value,previous_close,change_pct])=>({symbol,value,previous_close,change_pct,status:'DATED_CLOSE',session_date:'20261104',timezone:'America/New_York',source_asof:'2026-11-04T16:00:00-05:00',read_at:'2026-11-05T10:44:00+08:00',raw_sha256:'c'.repeat(64),source_url:'https://www.futunn.com/index/'+symbol+'-US'}))}}};}
function fixture(){const manifest=ref('manifest'),receipt=ref('receipt');const value={schema_version:'v3_5.global_industries.v2',status:'PARTIAL',research_date:'20261105',target_date:'20261105',target_trade_date:'20261105',source_date:'20261104',us_session_date:'20261104',capture_session_date:'20261104',provider_session_dates:['20261104'],capture_phase:'POST_CLOSE',captured_at:'2026-11-04T21:15:02Z',available_board_count:13,requested_board_count:24,write_policy:'read_only',recommendation_status:'RESEARCH_ONLY',RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false,artifact:{...ref('artifact'),manifest,receipt},manifest,receipt,cannot_confirm:['FUTU_BOARD_MATCH_UNCONFIRMED'],a_share_relation_status:'NO_REVIEWED_A_SHARE_RELATION_EVIDENCE'};
 value.native_board_snapshot={schema_version:'v3_5.futu_us_native_board_snapshot.v2',status:'READY',market:'US',timezone:'America/New_York',capture_session_date:'20261104',source_response_sha256:'d'.repeat(64),registry_sha256:'e'.repeat(64),available_board_count:6,requested_board_count:6,RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false,rows:[['黄金',8.98378],['云计算服务商',4.288929],['可再生能源',4.136314],['天然气',-4.538001],['稀土概念',-4.826103],['存储概念',-6.304687]].map(([name,pct],i)=>({board_code:'US.LIST'+i,board_id:'US.LIST'+i,board_name:name,expected_board_name:name,status:'READY',plate_valid:true,membership_status:'READY',metric_kind:'OFFICIAL_BOARD',plate_type:'CONCEPT',market:'US',timezone:'America/New_York',session_date:'20261104',update_time:'2026-11-04 16:00:00',change_pct:pct,last:100,previous_close:99,source_response_sha256:'f'.repeat(64),membership_sha256:'f'.repeat(64),breadth_alignment:'ALIGNED',rise_count:10,fall_count:10,equal_count:0,member_count:20}))};return value;}
test('native leaders are readable while original13/24 PARTIAL, capture and provenance stay technical',()=>{
 const payload=process.env.V4_US_CONTEXT_FIXTURE?JSON.parse(fs.readFileSync(process.env.V4_US_CONTEXT_FIXTURE,'utf8')):fixture();
 const view=usMarketContext(payload,day);assert.equal(view.status,'PARTIAL');assert.equal(view.technical.legacy_theme_matching,'13/24');assert.equal(view.technical.overall_api_status,'PARTIAL');assert.equal(view.recorded_at,'2026-11-04T21:15:02Z');assert.equal(view.source.artifact.sha256,payload.artifact.sha256);assert.match(view.limitation,/FUTU_BOARD_MATCH_UNCONFIRMED/);
 assert.deepEqual(view.leaders.map(row=>row.name),['黄金','云计算服务商','可再生能源']);assert.deepEqual(view.laggards.map(row=>row.name),['存储概念','稀土概念','天然气']);assert.equal(view.native.complete,true);
});
test('wrong target, unsafe flags, mismatched receipt/session and invalid coverage fail closed',()=>{
 for(const change of [v=>v.research_date='20261104',v=>v.orders_sent=true,v=>v.artifact.receipt={...ref('wrong')},v=>v.capture_session_date='20261103',v=>v.provider_session_dates=['20261103'],v=>v.available_board_count=25,v=>v.receipt.sha256='bad']){
  const value=fixture();change(value);assert.throws(()=>usMarketContext(value,day),/CONFLICT/);
 }
});
const bootstrap=fs.readFileSync(new URL('../research/stock_panel_collab_20261030/mac-host/bootstrap.mjs',import.meta.url),'utf8');
function sourceHarness(){
 const requests=[],paints=[];
 const ctx={URLSearchParams,Promise,Date,usMarketContext,unknownUsContext,contextSerial:0,contextReply:null,activeDay:day,context:null,
  fetch:url=>new Promise((resolve,reject)=>requests.push({url,resolve:value=>resolve({ok:true,json:async()=>value}),reject})),
  paintContext:()=>paints.push(JSON.parse(JSON.stringify(ctx.contextReply)))};
 vm.createContext(ctx);vm.runInContext(bootstrap.slice(bootstrap.indexOf('function sourceContext('),bootstrap.indexOf('\nfunction paintContext(')),ctx);
 return {ctx,requests,paints};
}
const base=()=>({...day,markets:{US:{status:'UNKNOWN'},JP:{status:'UNKNOWN',summary:'本日无来源'},KR:{status:'PARTIAL',summary:'KR_PRICE_BASELINE_MISSING'}}});
test('actual sourceContext independently applies US and keeps real JP/KR gaps on US failure',async()=>{
 const {ctx,requests}=sourceHarness();const pending=ctx.sourceContext(day,true);
 assert.equal(requests.length,2);assert.match(requests[1].url,/research_date=20261105/);
 requests[0].resolve(base());requests[1].reject(Error('saved API failed'));await pending;
 assert.equal(ctx.contextReply.markets.US.status,'UNKNOWN');assert.match(ctx.contextReply.markets.US.technical.reason,/saved API failed/);assert.equal(ctx.contextReply.markets.JP.summary,'本日无来源');assert.equal(ctx.contextReply.markets.KR.summary,'KR_PRICE_BASELINE_MISSING');
});
test('actual sourceContext accepts US before base response and rejects delayed old-day responses',async()=>{
 const {ctx,requests}=sourceHarness();const pending=ctx.sourceContext(day,true);requests[1].resolve(fixture());requests[0].resolve(base());await pending;assert.equal(ctx.contextReply.markets.US.status,'PARTIAL');assert.equal(ctx.contextReply.markets.JP.status,'UNKNOWN');
 const stale=ctx.sourceContext(day,true);const nextDay={...day,source_date:'2026-11-05',observation_date:'2026-11-06',generation:'d'.repeat(64)};ctx.activeDay=nextDay;
 const latest=ctx.sourceContext(nextDay,true);const nextPayload=fixture();for(const key of ['research_date','target_date','target_trade_date'])nextPayload[key]='20261106';for(const key of ['source_date','us_session_date','capture_session_date'])nextPayload[key]='20261105';nextPayload.provider_session_dates=['20261105'];nextPayload.captured_at='2026-11-05T21:15:02Z';nextPayload.native_board_snapshot.capture_session_date='20261105';for(const row of nextPayload.native_board_snapshot.rows){row.session_date='20261105';row.update_time='2026-11-05 16:00:00';}
 requests[4].resolve({...base(),...nextDay});requests[5].resolve(nextPayload);await latest;requests[2].resolve(base());requests[3].resolve(fixture());await stale;
 assert.equal(ctx.contextReply.observation_date,'2026-11-06');assert.equal(ctx.contextReply.markets.US.research_date,'20261106');
});
test('invalid or missing native rows never count as complete; unsafe envelopes reject',()=>{
 for(const mutate of [r=>r.plate_valid=false,r=>r.session_date='20261103',r=>r.change_pct=NaN,r=>r.source_response_sha256='bad',r=>r.orders_sent=true]){
  const value=fixture();mutate(value.native_board_snapshot.rows[0]);const view=usMarketContext(value,day);assert.equal(view.native.complete,false);assert.equal(view.native.rows.length,5);assert.equal(view.native.quarantined.length,1);
 }
 const missing=fixture();missing.native_board_snapshot.rows.pop();assert.equal(usMarketContext(missing,day).native.complete,false);
 const duplicate=fixture();duplicate.native_board_snapshot.rows.push({...duplicate.native_board_snapshot.rows[0]});assert.equal(usMarketContext(duplicate,day).native.rows.length,5);
 const unsafe=fixture();unsafe.native_board_snapshot.orders_sent=true;assert.throws(()=>usMarketContext(unsafe,day),/UNBOUND/);
});
class Element{constructor(tag='div'){this.tag=tag;this.children=[];this.text='';}set textContent(value){this.text=String(value);this.children=[];}get textContent(){return this.text+this.children.map(child=>child.textContent).join('');}append(...nodes){this.children.push(...nodes);}}
const doc={createElement:tag=>new Element(tag)};
test('main cards show named winners/losers and plain index purpose; codes and failures are folded, never invented0',()=>{
 const payload=process.env.V4_US_CONTEXT_FIXTURE?JSON.parse(fs.readFileSync(process.env.V4_US_CONTEXT_FIXTURE,'utf8')):fixture();
 const host=new Element(),view={...usMarketContext(payload,day),benchmarks:observationMarketContext(foreignSnapshot(),day).benchmarks},card=renderMarketCard(host,'US',view,day,doc);
 const main=card.children.filter(child=>child.tag!=='details').map(child=>child.textContent).join('');
 for(const text of ['昨晚美股：三大指数齐涨','道指 +3.03%｜标普 +1.58%｜纳指 +1.44%（11/04收盘）','黄金 +8.98%','云计算服务商 +4.29%','可再生能源 +4.14%','存储概念 -6.30%','稀土概念 -4.83%','天然气 -4.54%'])assert.ok(main.includes(text),text);
 assert.ok(!main.includes('PARTIAL')&&!main.includes('13/24')&&!main.includes('US.LIST'));assert.ok(card.textContent.includes('PARTIAL')&&card.textContent.includes('13/24'));assert.ok(card.textContent.includes('10涨、10跌'));
 assert.ok(card.children.filter(child=>child.tag==='details').every(details=>!Object.hasOwn(details,'open')));
 const jp=renderMarketCard(new Element(),'JP',{status:'UNKNOWN',summary:'原始错误'},day,doc),kr=renderMarketCard(new Element(),'KR',{status:'PARTIAL',summary:'KR_PRICE_BASELINE_MISSING'},day,doc);
 assert.ok(jp.textContent.includes('日经225'));assert.ok(kr.textContent.includes('KOSPI')&&kr.textContent.includes('KOSDAQ'));assert.ok(kr.textContent.includes('当前富途程序接口不识别韩国代码'));assert.ok(!kr.children.filter(child=>child.tag!=='details').map(child=>child.textContent).join('').includes('KR_PRICE_BASELINE_MISSING'));assert.ok(!jp.textContent.includes('0.00%')&&!kr.textContent.includes('0.00%'));
 const evil=fixture();evil.native_board_snapshot.rows[0].board_name=evil.native_board_snapshot.rows[0].expected_board_name='<script>alert(1)</script>';const safeCard=renderMarketCard(new Element(),'US',usMarketContext(evil,day),day,doc);assert.ok(safeCard.textContent.includes('<script>alert(1)</script>'));
});
test('foreign snapshot shows Japan Tokyo/Beijing times and current successful Korea; partial indexes stay unknown',()=>{
 const foreign=observationMarketContext(foreignSnapshot(),day),jp=renderMarketCard(new Element(),'JP',foreign.japan,day,doc);
 assert.ok(jp.textContent.includes('日本日经225 跌0.44%'));assert.ok(jp.textContent.includes('日本当地 11:30（北京时间 10:30）'));
 const success={status:'DATED_INDEX_OBSERVATION',summary:'^KS11 5499.66 (-3.2397%) / ^KQ11 692.61 (-3.1247%) · 后到留档',source_asof:'2026-11-05T11:30:00+09:00 / 2026-11-05T11:30:00+09:00',recorded_at:'2026-11-05T10:50:01+08:00',source:ref('korea')};
 const kr=renderMarketCard(new Element(),'KR',success,day,doc),main=kr.children.filter(child=>child.tag!=='details').map(child=>child.textContent).join('');assert.ok(main.includes('韩国大盘（KOSPI）跌3.24%'));assert.ok(main.includes('韩国创业板（KOSDAQ）跌3.12%'));assert.ok(main.includes('Yahoo'));assert.ok(!main.includes('读取失败'));
 const partial=foreignSnapshot();partial.context.us_benchmarks.rows[1].value=null;const view=observationMarketContext(partial,day).benchmarks;assert.equal(view.complete,false);assert.equal(view.heading,'昨晚美股：三大指数资料未齐');
 const missing=renderMarketCard(new Element(),'US',{...usMarketContext(fixture(),day),benchmarks:view},day,doc);assert.ok(missing.textContent.includes('标普 暂缺'));assert.ok(!missing.textContent.includes('标普 0.00%'));
 const invalid=foreignSnapshot();invalid.context.japan.previous_close=null;assert.equal(observationMarketContext(invalid,day).japan.status,'UNKNOWN');
 const stale=foreignSnapshot();stale.source_date='2026-11-03';assert.throws(()=>observationMarketContext(stale,day),/IDENTITY_CONFLICT/);
});
test('Korea PARTIAL preserves each successful index while only its failed peer stays missing',()=>{
 for(const good of ['KOSPI','KOSDAQ']){
  const ks=good==='KOSPI'?'^KS11 5499.66 (-3.2397%)':'^KS11 UNKNOWN: HTTPError: HTTP Error 403: Forbidden';
  const kq=good==='KOSDAQ'?'^KQ11 692.61 (-3.1247%)':'^KQ11 UNKNOWN: ValueError: KR_PRICE_BASELINE_MISSING';
  const value={status:'PARTIAL',summary:ks+' / '+kq+' · 后到留档',source_asof:(good==='KOSPI'?'2026-11-05T11:30:00+09:00':'UNKNOWN')+' / '+(good==='KOSDAQ'?'2026-11-05T11:30:00+09:00':'UNKNOWN'),recorded_at:'2026-11-05T10:50:01+08:00',source:ref('korea')};
  const card=renderMarketCard(new Element(),'KR',value,day,doc),main=card.children.filter(child=>child.tag!=='details').map(child=>child.textContent).join('');
  assert.ok(main.includes(good==='KOSPI'?'韩国大盘（KOSPI）跌3.24%':'韩国创业板（KOSDAQ）跌3.12%'),good+' remains visible');
  assert.ok(main.includes(good==='KOSPI'?'韩国创业板（KOSDAQ）暂未取得今日涨跌':'韩国大盘（KOSPI）暂未取得今日涨跌'));
  assert.ok(main.includes('Yahoo')&&main.includes('11:30'));assert.ok(!main.includes('原来源读取失败')&&!main.includes('0.00%')&&!main.includes('KR_PRICE_BASELINE_MISSING'));
 }
});
test('same-day chart selection does not invalidate an in-flight saved-context read',async()=>{
 const {ctx,requests}=sourceHarness();Object.assign(ctx,{cancelOriginalReady:()=>{},r2Serial:0,r2Controller:null,skillReviewCleanup:null,original:{clear:()=>{}},current:null,stat:{replaceChildren:()=>{}},el:()=>({textContent:''})});
 const start=bootstrap.indexOf('clear(){cancelOriginalReady();'),end=bootstrap.indexOf('\n  setWindow(',start);ctx.chart=vm.runInContext('({'+bootstrap.slice(start,end)+'})',ctx);
 const pending=ctx.sourceContext(day,true);ctx.chart.clear();ctx.sourceContext(day);assert.equal(requests.length,2);
 requests[0].resolve(base());requests[1].resolve(fixture());await pending;assert.equal(ctx.contextReply.markets.US.status,'PARTIAL');
});
test('actual foreground callback coalesces focus/visibility, reads saved context and does not cross a newly selected day',async()=>{
 let resolve,reads=0;
 const ctx={document:{hidden:false},foregroundRead:null,activeDay:day,completionCallback:{catalog:()=>new Promise(done=>resolve=done)},sourceContext:(value,force)=>{reads++;assert.equal(value,day);assert.equal(force,true);},Promise};
 vm.createContext(ctx);const start=bootstrap.indexOf('  refreshSavedSources(){'),end=bootstrap.indexOf('\n  },',start)+5;ctx.host=vm.runInContext('({'+bootstrap.slice(start,end)+'})',ctx);
 const first=ctx.host.refreshSavedSources();assert.equal(ctx.host.refreshSavedSources(),first);resolve();await first;assert.equal(reads,1);
 const next=ctx.host.refreshSavedSources();ctx.activeDay={...day,source_date:'2026-11-05'};resolve();await next;assert.equal(reads,1);
 ctx.document.hidden=true;assert.equal(ctx.host.refreshSavedSources(),null);
});
