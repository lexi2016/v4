import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {usMarketContext,unknownUsContext} from '../research/stock_panel_collab_20261030/mac-host/workbench-us-context.mjs';
const day={source_date:'2026-11-04',observation_date:'2026-11-05',generation:'a'.repeat(64),input_sha256:'b'.repeat(64)};
const ref=name=>({path:'/saved/'+name,sha256:'c'.repeat(64)});
function fixture(){const manifest=ref('manifest'),receipt=ref('receipt');return {schema_version:'v3_5.global_industries.v2',status:'PARTIAL',research_date:'20261105',target_date:'20261105',target_trade_date:'20261105',source_date:'20261104',us_session_date:'20261104',capture_session_date:'20261104',provider_session_dates:['20261104'],capture_phase:'POST_CLOSE',captured_at:'2026-11-04T21:15:02Z',available_board_count:13,requested_board_count:24,write_policy:'read_only',recommendation_status:'RESEARCH_ONLY',RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false,artifact:{...ref('artifact'),manifest,receipt},manifest,receipt,cannot_confirm:['FUTU_BOARD_MATCH_UNCONFIRMED'],a_share_relation_status:'NO_REVIEWED_A_SHARE_RELATION_EVIDENCE'};}
test('existing exact-target stage API projection preserves13/24 PARTIAL, capture time and provenance',()=>{
 const payload=process.env.V4_US_CONTEXT_FIXTURE?JSON.parse(fs.readFileSync(process.env.V4_US_CONTEXT_FIXTURE,'utf8')):fixture();
 const view=usMarketContext(payload,day);assert.equal(view.status,'PARTIAL');assert.match(view.summary,/13\/24/);assert.equal(view.recorded_at,'2026-11-04T21:15:02Z');assert.equal(view.source.artifact.sha256,payload.artifact.sha256);assert.match(view.limitation,/FUTU_BOARD_MATCH_UNCONFIRMED/);
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
 assert.equal(ctx.contextReply.markets.US.status,'UNKNOWN');assert.match(ctx.contextReply.markets.US.summary,/saved API failed/);assert.equal(ctx.contextReply.markets.JP.summary,'本日无来源');assert.equal(ctx.contextReply.markets.KR.summary,'KR_PRICE_BASELINE_MISSING');
});
test('actual sourceContext accepts US before base response and rejects delayed old-day responses',async()=>{
 const {ctx,requests}=sourceHarness();const pending=ctx.sourceContext(day,true);requests[1].resolve(fixture());requests[0].resolve(base());await pending;assert.equal(ctx.contextReply.markets.US.status,'PARTIAL');assert.equal(ctx.contextReply.markets.JP.status,'UNKNOWN');
 const stale=ctx.sourceContext(day,true);const nextDay={...day,source_date:'2026-11-05',observation_date:'2026-11-06',generation:'d'.repeat(64)};ctx.activeDay=nextDay;
 const latest=ctx.sourceContext(nextDay,true);const nextPayload=fixture();for(const key of ['research_date','target_date','target_trade_date'])nextPayload[key]='20261106';for(const key of ['source_date','us_session_date','capture_session_date'])nextPayload[key]='20261105';nextPayload.provider_session_dates=['20261105'];nextPayload.captured_at='2026-11-05T21:15:02Z';
 requests[4].resolve({...base(),...nextDay});requests[5].resolve(nextPayload);await latest;requests[2].resolve(base());requests[3].resolve(fixture());await stale;
 assert.equal(ctx.contextReply.observation_date,'2026-11-06');assert.equal(ctx.contextReply.markets.US.research_date,'20261106');
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
