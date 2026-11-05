import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {requestedEntry,requestedSourceDate,resolveCatalogRequest,entryUrl,preferredCatalogEntry,catalogEntryKey,shanghaiToday} from '../research/stock_panel_collab_20261030/mac-host/entry-date.mjs';
const a={source_date:'2026-11-04',observation_date:'2026-11-05',revision:'a'.repeat(64)};
const b={source_date:'2026-11-05',observation_date:'2026-11-06',revision:'b'.repeat(64)};
const prior={source_date:'2026-11-03',observation_date:'2026-11-04',revision:'c'.repeat(64)};
test('legacy source priority, exact observation fallback and explicit normalized pair never drift',()=>{
 const initial=resolveCatalogRequest(requestedEntry('?date=2026-11-05'),[a,prior]);assert.equal(initial.entry,a);
 const canonical=entryUrl('http://localhost/workbench.html?date=2026-11-05&other=kept',initial.intent);
 assert.equal(new URL(canonical).searchParams.get('source_date'),'2026-11-04');assert.equal(new URL(canonical).searchParams.get('observation_date'),'2026-11-05');assert.equal(new URL(canonical).searchParams.get('date'),null);
 assert.equal(resolveCatalogRequest(requestedEntry(new URL(canonical).search),[b,a,prior]).entry,a);
 assert.equal(resolveCatalogRequest(requestedEntry('?date=2026-11-04'),[a,prior]).entry,a);
 assert.equal(requestedSourceDate('?date=20261104'),'2026-11-04');
});
test('unknown, conflicting or ambiguous dates never choose latest or infer a previous session',()=>{
 for(const search of ['?source_date=2026-11-05','?observation_date=2026-11-07','?source_date=2026-11-04&observation_date=2026-11-06'])assert.equal(resolveCatalogRequest(requestedEntry(search),[a,prior]).entry,null,search);
 const other={...prior,observation_date:a.observation_date};assert.equal(resolveCatalogRequest(requestedEntry('?observation_date=2026-11-05'),[a,other]).status,'AMBIGUOUS_OBSERVATION_DATE');
 for(const search of ['?date=2026-02-30','?observation_date=bad','?date=2026-11-04&source_date=2026-11-05','?source_date=2026-11-04&source_date=2026-11-04'])assert.throws(()=>requestedEntry(search));
 const r2={...a,revision:'d'.repeat(64),ruleset_id:'ZGE_SKILL_DAILY_CANDIDATES_R2'};assert.equal(resolveCatalogRequest(requestedEntry('?date=2026-11-04'),[a,r2]).entry,r2);
 const friday={...a,source_date:'2026-10-30',observation_date:'2026-11-02'};assert.equal(resolveCatalogRequest(requestedEntry('?observation_date=2026-11-02'),[friday]).entry,friday);
});

// Execute the actual shell's entry, controls and catalog callback with only
// DOM/network surfaces substituted. No mirrored date-selection implementation.
const shell=fs.readFileSync(new URL('../research/stock_panel_collab_20261030/mac-host/dot/shell/workbench.local.mjs',import.meta.url),'utf8');
function harness(search,entries=[a,prior]){
 let now=new Date('2026-11-05T12:00:00+08:00');
 const elements=new Map();const element=id=>{if(!elements.has(id))elements.set(id,{value:'',textContent:'',options:[],append(item){this.options.push(item)},before(item){elements.set(item.id,item)},replaceChildren(){this.options=[]}});return elements.get(id);};
 const ctx={URL,URLSearchParams,Array,Map,Set,Promise,requestedEntry,resolveCatalogRequest:(intent,rows)=>resolveCatalogRequest(intent,rows,now),shanghaiToday:()=>shanghaiToday(now),entryUrl,preferredDay:preferredCatalogEntry,catalogKey:catalogEntryKey,
  entryIntent:null,entryBinding:null,researchCalendarDays:[],catalogSerial:0,day:null,apiBound:true,integrationBase:'/api/v4/research/workbench',timeContract:null,followLatestResearchDay:!search,
  location:{href:'http://localhost/workbench.html'+search,search},$:element,node:(tag,text)=>({value:'',textContent:text}),lockR2Attempts:()=>{},renderContext:()=>{},calls:[],
  loadJson:async url=>url.endsWith('/history')?{days:entries}:null,endpoint:part=>'/api/v4/research/workbench/'+part};
 ctx.history={replaceState:(state,title,href)=>{const url=new URL(href);ctx.location={href:url.href,search:url.search};}};
 ctx.loadDay=async()=>{ctx.day=ctx.entryBinding?.entry??null;if(ctx.day)ctx.calls.push('/days/'+ctx.day.source_date);};
 vm.createContext(ctx);
 vm.runInContext(shell.slice(shell.indexOf('function syncResearchCalendar(){'),shell.indexOf('\nfunction lockR2Attempts')),ctx);
 vm.runInContext(shell.slice(shell.indexOf('async function init(){'),shell.indexOf('\nfunction railTab')),ctx);
 const start=shell.indexOf(' async catalog('),end=shell.indexOf('\n refresh(){',start);
 ctx.completion=vm.runInContext('({'+shell.slice(start,end)+'})',ctx);
 const sourceHandler=shell.slice(shell.indexOf("$('date').onchange="),shell.indexOf("for(const id of ['query','scope'])"));vm.runInContext(sourceHandler,ctx);
 ctx.window={StockPanelHost:{refreshSavedSources:()=>{}}};return {ctx,element,setNow:value=>{now=new Date(value)}};
}
test('actual init normalizes observation legacy entry before source GET; old source entry stays fixed',async()=>{
 for(const search of ['?date=2026-11-05','?date=2026-11-04']){
  const {ctx}=harness(search);await ctx.init();assert.deepEqual(ctx.calls,['/days/2026-11-04']);assert.equal(new URL(ctx.location.href).searchParams.get('observation_date'),'2026-11-05');
 }
 const {ctx}=harness('?source_date=2026-11-04&observation_date=2026-11-06');await ctx.init();assert.equal(ctx.calls.length,0);assert.equal(ctx.entryBinding.status,'SOURCE_OBSERVATION_CONFLICT');
});
test('actual calendar, source dropdown and Latest keep URL and follow intent consistent',async()=>{
 const {ctx,element}=harness('?date=2026-11-04',[b,a,prior]);await ctx.init();
 element('researchCalendar').value='2026-11-05';await element('researchCalendar').onchange();assert.equal(ctx.entryIntent.mode,'source');assert.equal(ctx.followLatestResearchDay,false);assert.equal(new URL(ctx.location.href).searchParams.get('source_date'),'2026-11-04');
 await element('researchLatest').onclick();assert.equal(ctx.entryIntent.mode,'latest');assert.equal(ctx.followLatestResearchDay,true);assert.equal(new URL(ctx.location.href).search,'?mode=latest');assert.equal(ctx.day.source_date,'2026-11-05');
 element('date').value=catalogEntryKey(a);await element('date').onchange();assert.equal(ctx.followLatestResearchDay,false);assert.equal(ctx.entryIntent.observation_date,'2026-11-05');
});
test('current entry stays on Shanghai today, rolls once at midnight and preserves pinned history',async()=>{
 const monday={source_date:'2026-11-06',observation_date:'2026-11-09',revision:'e'.repeat(64)};
 const {ctx,element,setNow}=harness('',[monday,b,a]);await ctx.init();assert.equal(ctx.day.source_date,'2026-11-04');assert.equal(ctx.entryIntent.mode,'current');assert.equal(new URL(ctx.location.href).search,'?mode=current');
 setNow('2026-11-06T00:00:05+08:00');ctx.refreshCurrentDay();assert.equal(ctx.day.source_date,'2026-11-05');const reads=ctx.calls.length;ctx.refreshCurrentDay();assert.equal(ctx.calls.length,reads);
 setNow('2026-11-07T08:00:00+08:00');ctx.refreshCurrentDay();assert.equal(ctx.day,null);assert.equal(ctx.entryBinding.status,'CURRENT_DAY_NOT_MATERIALIZED');
 setNow('2026-11-09T08:00:00+08:00');ctx.refreshCurrentDay();assert.equal(ctx.day.source_date,'2026-11-06');
 element('researchCalendar').value='2026-11-05';await element('researchCalendar').onchange();setNow('2026-11-10T00:00:01+08:00');ctx.refreshCurrentDay();assert.equal(ctx.day.source_date,'2026-11-04');assert.equal(ctx.entryIntent.mode,'source');
 await element('researchCurrent').onclick();assert.equal(ctx.entryIntent.mode,'current');assert.equal(ctx.day,null);
 assert.equal(shanghaiToday(new Date('2026-11-05T16:00:01Z')),'2026-11-06');
 assert.throws(()=>requestedEntry('?mode=current&source_date=2026-11-04'));
});
test('actual completion binds a pending exact observation and rejects a stale catalog after manual date change',async()=>{
 const {ctx,element}=harness('?observation_date=2026-11-07');await ctx.init();assert.equal(ctx.day,null);
 const future={source_date:'2026-11-06',observation_date:'2026-11-07',revision:'e'.repeat(64)};
 ctx.loadJson=async()=>({days:[future,b,a]});await ctx.completion.catalog();assert.equal(ctx.day.source_date,'2026-11-06');assert.equal(new URL(ctx.location.href).searchParams.get('observation_date'),'2026-11-07');
 let resolve;ctx.loadJson=()=>new Promise(done=>resolve=done);const pending=ctx.completion.catalog();
 element('researchCalendar').value='2026-11-05';await element('researchCalendar').onchange();resolve({days:[future,b,a]});await pending;
 assert.equal(ctx.day.source_date,'2026-11-04');assert.equal(ctx.entryIntent.observation_date,'2026-11-05');
});
