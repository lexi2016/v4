import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {GROUPS,filterStocks,groupLabels,validateV192Group,v192Summary} from '../research/stock_panel_collab_20261030/mac-host/dot/src/workbench-model.mjs';
const path='../research/stock_panel_collab_20261030/mac-host/';
const shell=fs.readFileSync(new URL(path+'dot/shell/workbench.local.mjs',import.meta.url),'utf8');
const bootstrap=fs.readFileSync(new URL(path+'bootstrap.mjs',import.meta.url),'utf8');
const states={nav_smallk:'FALSE',original:'FALSE',nav_pullback:'FALSE',nav_breakout:'FALSE'};
const row=(symbol,hits=[],model=false)=>({symbol,enriched_display_name:symbol,group_states:{...states,...Object.fromEntries(hits.map(k=>[k,'TRUE']))},eligible_candidate:!!hits.length,v192_member:model,in_fifth:false,history_rates:{}});
function fixtures(){
 const canonical=[row('301199.SZ',['original','nav_pullback']),row('001379.SZ',['nav_pullback'])];
 const day={source_date:'2026-11-09',observation_date:'2026-11-10',generation:'a'.repeat(64),input_sha256:'b'.repeat(64),source_selector_sha256:'c'.repeat(64),numeric_manifest:{path:'/numeric',sha256:'d'.repeat(64)},rows:canonical};
 const model={schema:'V4_WORKBENCH_V192_GROUP_V1',group_id:'v192',status:'READY',source_date:day.source_date,observation_date:day.observation_date,generation:day.generation,input_sha256:day.input_sha256,selector_sha256:day.source_selector_sha256,numeric_manifest:day.numeric_manifest,count:3,rows:[{...canonical[0],v192_member:true},{...canonical[1],v192_member:true},row('301361.SZ',[],true)],source_artifact_sha256:'e'.repeat(64),rank_usage_boundary:'RANK_FOR_REVIEW_ONLY_NOT_BUY_PRIORITY',historical_PIT:false,RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false};
 return {day,model};
}
test('independent filter includes model-only rows and leaves original groups and totals unchanged',()=>{
 const {day,model}=fixtures(),before=structuredClone(day);day.v192_group=validateV192Group(model,day);
 assert.equal(filterStocks(day,{group:'v192'}).length,3);
 assert.equal(filterStocks(day,{group:'original'}).length,1);
 assert.equal(filterStocks(day,{group:'all'}).length,2);
 assert.deepEqual(day.rows,before.rows);assert.equal(Object.keys(GROUPS).length,4);
 assert.ok(groupLabels(model.rows[2]).includes('v1.9.2候选'));
 assert.equal(filterStocks(day,{group:'v192',query:'301361'}).length,1);
 assert.equal(filterStocks({...day,v192_group:null},{group:'v192'}).length,0);
});
test('exact identity and empty/unknown models cannot leak from an old date or selector',()=>{
 const {day,model}=fixtures();
 for(const change of [{source_date:'2026-11-06'},{observation_date:'2026-11-11'},{generation:'f'.repeat(64)},{selector_sha256:'f'.repeat(64)}])assert.throws(()=>validateV192Group({...model,...change},day),/IDENTITY/);
 assert.throws(()=>validateV192Group({...model,status:'CANNOT_CONFIRM'},day),/UNKNOWN_WITH_ROWS/);
 const empty=validateV192Group({...model,status:'READY_EMPTY',count:0,rows:[]},day);assert.match(v192Summary(empty),/本日无候选/);
 assert.match(v192Summary(model),/信号日 2026-11-09.*观察日 2026-11-10.*已就绪/);
 assert.ok(!v192Summary(model).includes(model.source_artifact_sha256.slice(0,12)));
});
test('actual host open clears old view, starts score read, and returns an explicit gap for missing model chart',async()=>{
 const calls=[],node=()=>({replaceChildren(){calls.push('clear-stat')}}),stat=node();
 const ctx={context:null,current:null,stat,day:null,setCompanyContext:x=>calls.push(['company',x.symbol]),sourceContext:()=>{},singleResearch:{openSymbol:s=>calls.push(['score',s])},add:()=>{},el:()=>{},bridge:{open:()=>{throw Error('must not load old chart')}},openSkill:()=>{}};
 vm.createContext(ctx);const start=bootstrap.indexOf('  async open(day,row,selectedGroup){'),end=bootstrap.indexOf('  async paintTop200()',start);
 const host=vm.runInContext('({'+bootstrap.slice(start,end)+'})',ctx);
 const {day}=fixtures(),model=row('301361.SZ',[],true);model.original_chart_status='NOT_MATERIALIZED';
 const result=await host.open(day,model,'v192');assert.equal(result.status,'NOT_MATERIALIZED');assert.match(result.reason,/原式图未物化/);
 assert.ok(calls.some(x=>Array.isArray(x)&&x[0]==='score'&&x[1]==='301361.SZ'));
});
test('actual interactive loader clears previous chart and keeps model statistics unbound',async()=>{
 const nodes=new Map(),el=id=>{if(!nodes.has(id))nodes.set(id,{hidden:false,textContent:''});return nodes.get(id)};
 let cleared=0;const ctx={$:el,stockToken:4,group:'v192',day:{},interactiveLoaded:{old:true},clearInteractive:()=>{cleared++;ctx.interactiveLoaded=null;el('interactiveChart').hidden=true},window:{StockPanelHost:{open:async()=>({status:'NOT_MATERIALIZED',reason:'同日原式图未物化'})}}};
 vm.createContext(ctx);vm.runInContext(shell.slice(shell.indexOf('async function loadInteractive('),shell.indexOf('\nconst compactChart=')),ctx);
 await ctx.loadInteractive({symbol:'301361.SZ'},4);assert.equal(cleared,2);assert.equal(ctx.interactiveLoaded,null);assert.equal(el('interactiveChart').hidden,true);assert.match(el('projectionStatus').textContent,/原式图未物化.*同定义D\+2\/D\+5统计未接入/);
 assert.ok(shell.includes("if(changed.includes('v192'))await refreshV192Group()"));
});

function partial(){
 const {day,model}=fixtures();
 return {day,model:{...model,status:'PARTIAL',source_count:4,valid_count:3,pending_count:1,excluded_count:1,excluded_rows:[{symbol:'301314.SZ',status:'CANNOT_CONFIRM',reason:'A_DAILY_SYMBOL_DETAIL_SOURCE_IDENTITY_CONFLICT',qualification_reason:'CURRENT_SYMBOL_HISTORY_END_MISMATCH',source_checkpoint:{path:'/checkpoint/301314.SZ.json',sha256:'f'.repeat(64)}}]}};
}
test('partial owns reconciled valid/source/pending counts and isolates blocked identity',()=>{
 const {day,model}=partial();day.v192_group=validateV192Group(model,day);
 assert.equal(filterStocks(day,{group:'v192'}).length,3);
 assert.equal(filterStocks(day,{group:'v192',query:'301314'}).length,0);
 assert.match(v192Summary(model),/部分就绪.*来源 4只.*有效 3只.*待核 1只.*301314.SZ.*CURRENT_SYMBOL_HISTORY_END_MISMATCH/);
 for(const change of [{source_count:5},{pending_count:0},{valid_count:4},{excluded_rows:[]},{excluded_rows:[{...model.excluded_rows[0],symbol:model.rows[0].symbol}]},{excluded_rows:[{...model.excluded_rows[0],source_checkpoint:{path:'/unbound'}}]}])assert.throws(()=>validateV192Group({...model,...change},day),/PARTIAL/);
 const blocked=validateV192Group({...model,rows:[],count:0,valid_count:0,source_count:1},day);
 assert.match(v192Summary(blocked),/部分就绪.*有效 0只.*待核 1只/);
 assert.doesNotMatch(v192Summary(blocked),/本日无候选/);
 assert.throws(()=>validateV192Group({...blocked,status:'READY_EMPTY'},day),/EMPTY/);
});
test('actual filter controls show unknown instead of zero and partial counts with reason',()=>{
 const {day,model}=partial(),nodes=new Map();
 function node(tag,text=''){return {textContent:text,classList:{toggle(){}},setAttribute(){},dataset:{},append(){},replaceChildren(){this.children=[]},children:[],after(){}}}
 const ctx={day:{...day,v192_group:model},GROUPS,group:'v192',v192Summary,node,$:id=>{if(!nodes.has(id))nodes.set(id,node('p'));return nodes.get(id)}};
 ctx.$('groupFilters').append=x=>ctx.$('groupFilters').children.push(x);
 vm.createContext(ctx);const start=shell.indexOf('function renderFilters()'),end=shell.indexOf('function renderList(',start);
 vm.runInContext(shell.slice(start,end),ctx);ctx.renderFilters();
 assert.ok(ctx.$('groupFilters').children.some(x=>/有效|3 \/ 来源 4 · 待核 1/.test(x.textContent)));
 assert.match(ctx.$('v192GroupStatus').textContent,/301314.SZ.*CURRENT_SYMBOL_HISTORY_END_MISMATCH/);
 ctx.day={...day,v192_group:{...model,status:'CANNOT_CONFIRM',rows:[],count:0,reason:'V192_READER_SHA_CONFLICT'}};ctx.renderFilters();
 assert.ok(ctx.$('groupFilters').children.some(x=>/v1.9.2候选 待核 · 数量未知/.test(x.textContent)));
 assert.match(ctx.$('v192GroupStatus').textContent,/来源待核 · 数量未知.*V192_READER_SHA_CONFLICT/);
 assert.doesNotMatch(ctx.$('v192GroupStatus').textContent,/本日无候选/);
});
