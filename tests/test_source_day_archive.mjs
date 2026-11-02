import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {rowValidity,validateSourceDayArchive,archiveRowValidity,listQuoteSource,sortSourceDayArchive,hasBoundTargetDayStock}
  from '../research-panel/workbench-host/observation-local.mjs';

const sha=x=>x.repeat(64),day={source_date:'2026-10-30',observation_date:'2026-11-02',generation:sha('a'),
  input_sha256:sha('b'),numeric_manifest:{path:'/source',sha256:sha('c')},
  rows:[{symbol:'000035.SZ',enriched_display_name:'中国天楹'},{symbol:'000528.SZ',enriched_display_name:'柳    工'},
        {symbol:'000001.SZ',enriched_display_name:'平安银行'}]};
const archive={schema:'V4_WORKBENCH_SOURCE_DAY_ARCHIVE_V1',source_date:day.source_date,source_time:'UNKNOWN_DATE_ONLY',
  generation:day.generation,input_sha256:day.input_sha256,numeric_manifest:day.numeric_manifest,artifact:{path:'/top200',sha256:sha('d')},
  historical_PIT:false,RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false,rows:[
    {symbol:'000035.SZ',candidate_name:'中国天楹',archive_name:'中国天楹',directory_name:'中国天楹',archive_identity_status:'EXACT_CODE_NAME',source_date:day.source_date,status:'READY',reason:null,currency:'CNY',price:4.39,change_percent_source:-2.44,amount_source:152743652.86},
    {symbol:'000528.SZ',candidate_name:'柳    工',source_date:day.source_date,status:'UNKNOWN',reason:'ARCHIVE_IDENTITY_CONFLICT',currency:'CNY',price:null,change_percent_source:null,amount_source:null},
    {symbol:'000001.SZ',candidate_name:'平安银行',archive_name:'平安银行',directory_name:'平安银行',archive_identity_status:'EXACT_CODE_NAME',source_date:day.source_date,status:'READY',reason:null,currency:'CNY',price:10,change_percent_source:0,amount_source:0},
  ]};

test('archive is separately bound to source date, generation, manifest and the exact candidate identities',()=>{
  assert.equal(validateSourceDayArchive(archive,day,archive.artifact),archive);
  for(const changed of [{...archive,source_date:'2026-11-02'},{...archive,generation:sha('e')},
    {...archive,input_sha256:sha('f')},{...archive,numeric_manifest:{path:'/other',sha256:sha('c')}},
    {...archive,historical_PIT:true},{...archive,production_allowed:true},
    {...archive,rows:[archive.rows[0],archive.rows[0],archive.rows[2]]},
    {...archive,rows:[{...archive.rows[0],archive_name:'不同名称'},...archive.rows.slice(1)]},
    {...archive,rows:[{...archive.rows[0],amount_source:NaN},...archive.rows.slice(1)]}])
    assert.throws(()=>validateSourceDayArchive(changed,day,archive.artifact),/SOURCE_DAY_ARCHIVE/);
  assert.throws(()=>validateSourceDayArchive(archive,day,{...archive.artifact,sha256:sha('f')}),/SOURCE_DAY_ARCHIVE_BINDING/);
  assert.equal(archiveRowValidity(archive.rows[2],archive,'amount').value,0);
  assert.equal(archiveRowValidity(archive.rows[1],archive,'price').valid,false);
  assert.deepEqual(sortSourceDayArchive(day.rows,{archive,mode:'price_asc'}).map(x=>x.symbol),['000035.SZ','000001.SZ','000528.SZ']);
  assert.deepEqual(sortSourceDayArchive(day.rows,{archive,mode:'amount_desc'}).map(x=>x.symbol),['000035.SZ','000001.SZ','000528.SZ']);
});

test('actual source errors precede date labels and archive never mixes with a valid observation',()=>{
  const snapshot={daily_contract_sha256:sha('e'),observation_date:'2026-11-02',slot:'1530',rows:[{symbol:'000035.SZ',status:'SOURCE_ERROR',source_asof:null}]};
  assert.equal(rowValidity(snapshot.rows[0],snapshot,'price','2026-11-02T07:40:00Z').state,'SOURCE_ERROR');
  assert.equal(listQuoteSource(snapshot,archive,'2026-11-02T07:40:00Z'),'SOURCE_DAY_ARCHIVE');
  const live={symbol:'000035.SZ',status:'CURRENT_VISIBLE_FIELDS_CHECKED',source_asof:'2026-11-02T07:30:00Z',
    observed_at_upper_bound:'2026-11-02T07:30:30Z',currency:'CNY',price:5,change_percent_source:0,amount_source:0,percent_change_rank_eligible:true};
  assert.equal(listQuoteSource({...snapshot,rows:[live]},archive,'2026-11-02T07:40:00Z'),'OBSERVATION');
  assert.equal(listQuoteSource(snapshot,null,'2026-11-02T07:40:00Z'),'OBSERVATION');
});

test('a missing archive row can mention existing target-day stock only with matching metadata identity',()=>{
  const meta={symbol:'689009.SH',status:'READY_FOR_RESEARCH_REVIEW',source_date:day.source_date,generation:day.generation,
    input_sha256:day.input_sha256,numeric_manifest:day.numeric_manifest,last_date:20261030,chart_status:'READY',historical_PIT:false,RESEARCH_ONLY:true,
    production_allowed:false,buy_gate_updated:false,orders_sent:false,assets:{html:{sha256:sha('d')}}};
  assert.equal(hasBoundTargetDayStock(meta,day,'689009.SH'),true);
  for(const changed of [{...meta,symbol:'000001.SZ'},{...meta,last_date:20261029},{...meta,input_sha256:sha('f')},
    {...meta,generation:sha('f')},{...meta,historical_PIT:true},{...meta,assets:{html:{sha256:'bad'}}},
    {...meta,numeric_manifest:undefined},{...meta,numeric_manifest:{path:'/other',sha256:sha('c')}},
    {...meta,numeric_manifest:{path:'/source',sha256:sha('f')}}])
    assert.equal(hasBoundTargetDayStock(changed,day,'689009.SH'),false);
  assert.equal(hasBoundTargetDayStock(meta,{...day,numeric_manifest:undefined},'689009.SH'),false);
});

const shellSource=readFileSync(new URL('../research-panel/workbench-host/dot/shell/workbench.local.mjs',import.meta.url),'utf8');
const bootstrapSource=readFileSync(new URL('../research-panel/workbench-host/bootstrap.mjs',import.meta.url),'utf8');
const between=(source,start,end)=>{const at=source.indexOf(start),stop=source.indexOf(end,at);assert.ok(at>=0&&stop>at);return source.slice(at,stop)};

test('stable clock ticks and context repaint keep the archive source-day label',()=>{
  const box={textContent:''},snapshot={snapshot_sha256:'same',rows:[{}]};let listRenders=0;
  const context={document:{getElementById:()=>box,activeElement:null},originalRenderPhase:()=>{box.textContent='11/2 observation'},
    originalRenderContext:()=>{box.textContent='11/2 observation'},updateListQuoteLabel:()=>{box.textContent='10/30 archive'},
    day:{},observationSnapshot:snapshot,rowValidity:()=>({state:'SOURCE_ERROR'}),$:(id)=>id==='stockSort'?{value:'original_groups'}:box,
    lastClockSignature:'same|original_groups|SOURCE_ERROR',timeContract:null,renderList:()=>{listRenders++},selected:null,Date};
  vm.createContext(context);
  const wrappers=between(shellSource,'const archiveMini=','\n');
  const tick=between(shellSource,'function tickObservationPresentation()','\nsetInterval(tickObservationPresentation');
  vm.runInContext(wrappers+'\n'+tick+'\nglobalThis.tick=tickObservationPresentation;globalThis.repaint=renderContext;',context);
  context.tick();context.tick();assert.equal(box.textContent,'10/30 archive');assert.equal(listRenders,0);
  context.repaint(null,snapshot);assert.equal(box.textContent,'10/30 archive');
});

test('classification-only refresh discards the old in-flight archive and binds a fresh one',async()=>{
  const oldDay={...day},nextDay={...day,classification_status:'UPDATED'},pending=[],box={replaceChildren(){}};
  const context={activeDay:oldDay,day:oldDay,moduleSerial:1,completionSerial:0,completionCallback:null,
    sourceDayArchive:null,archiveRows:new Map(),archiveMissingChecked:new Set(),archiveMissingResults:new Map(),selected:null,
    fetch:()=>new Promise(resolve=>pending.push(resolve)),URLSearchParams,el:()=>box,add:()=>({}),document:{querySelector:()=>({after(){}})},
    selection:()=>({date:day.source_date}),endpoint:()=>'',loadJson:async()=>nextDay,validateDay:value=>value,
    validateSourceDayArchive,paintArchiveGaps(){},renderList(){},renderClassification(){},$:()=>({textContent:''}),
    window:{},Map,Set};
  vm.createContext(context);
  const method=between(bootstrapSource,'  async paintTop200(){','\n  paintContext,');
  const refresh=between(bootstrapSource,'  refreshClassificationDay(day){','\n  paintClassification(row,day)');
  const host=vm.runInContext('({'+method+refresh+'})',context);
  host.paintClassificationCoverage=()=>{};host.paintContext=()=>{};context.window.StockPanelHost=host;
  const completion=between(shellSource,'window.StockPanelHost.installCompletion({','\n});')
    .replace('window.StockPanelHost.installCompletion(','');
  const callbacks=vm.runInContext('('+completion+'})',context);context.completionCallback=callbacks;
  const first=host.paintTop200();assert.equal(pending.length,1);
  await callbacks.modules(['classification']);assert.equal(context.day,nextDay);assert.equal(context.activeDay,nextDay);assert.equal(pending.length,2);
  const response={ok:true,json:async()=>({source_day_archive:archive,artifact:archive.artifact,top200:[]})};
  pending[0](response);await first;assert.equal(context.sourceDayArchive,null);
  pending[1](response);await new Promise(resolve=>setImmediate(resolve));
  assert.equal(context.sourceDayArchive,archive);assert.equal(context.archiveRows.size,3);
});
