import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {GROUPS,configureGroups,filterStocks,groupLabels,loadSkillProjection} from '../research-panel/workbench-host/dot/src/workbench-model.mjs';

test('R2 groups keep numeric, pending, risk and chart verdict separate',()=>{
  const day={ruleset_id:'ZGE_SKILL_DAILY_CANDIDATES_R2',rows:[
    {symbol:'002959.SZ',eligible_candidate:true,group_states:{skill_r2_b1:'TRUE',skill_r2_sb1:'UNKNOWN'},r2_pending:true,in_fifth:true,r2_review:{status:'REVIEWED',decision:'KEEP'}},
    {symbol:'920873.BJ',eligible_candidate:true,group_states:{skill_r2_nana:'TRUE'},r2_pending:false,in_fifth:false,r2_review:{status:'NOT_REVIEWED',decision:null}},
  ]};
  configureGroups(day);
  assert.equal(Object.keys(GROUPS).length,9);
  assert.deepEqual(groupLabels(day.rows[0]),['B1回调']);
  for(const group of ['skill_r2_b1','pending','fifth','review_keep'])assert.deepEqual(filterStocks(day,{group}).map(r=>r.symbol),['002959.SZ']);
  assert.deepEqual(filterStocks(day,{group:'review_watch'}),[]);
  assert.equal(filterStocks(day,{group:'all'}).length,2);
});

test('switching back restores legacy four-group labels and filtering',()=>{
  const day={rows:[{symbol:'000001.SZ',eligible_candidate:true,group_states:{original:'TRUE',nav_pullback:'UNKNOWN'},in_fifth:false}]};
  configureGroups(day);
  assert.deepEqual(Object.keys(GROUPS),['nav_smallk','original','nav_pullback','nav_breakout']);
  assert.deepEqual(groupLabels(day.rows[0]),['原公式']);
  assert.equal(filterStocks(day,{group:'pending'}).length,1);
});

test('projection checks original bytes and maps source names only in memory',async()=>{
  const expected={source_date:'2026-10-28',symbol:'002959.SZ',generation:'a'.repeat(64),input_sha256:'b'.repeat(64),selector_sha256:'c'.repeat(64)};
  const value={source:{generation:expected.generation,input_sha256:expected.input_sha256,asof:'20261028',selector_artifact:{sha256:expected.selector_sha256}}};
  const raw=new TextEncoder().encode(JSON.stringify(value)),sha=createHash('sha256').update(raw).digest('hex');
  const url=`/api/v4/research/workbench/days/2026-10-28/skill-r2/assets/002959.SZ/projection?revision=${expected.generation}&sha256=${sha}`;
  const ref={projection_url:url,sha256:sha,bytes:raw.length,encoding:'identity',row_count:1,formula_sha256:'d'.repeat(64)};
  const options={origin:'http://localhost',fetcher:async()=>new Response(raw),adaptProjection:(p)=>p};
  const mapped=await loadSkillProjection(ref,expected,options);
  assert.equal(mapped.source.generation_id,expected.generation);
  assert.equal(mapped.source.source_input_sha256,expected.input_sha256);
  assert.equal(value.source.generation_id,undefined);
  await assert.rejects(()=>loadSkillProjection(ref,{...expected,selector_sha256:'e'.repeat(64)},options),/R2_PROJECTION_SOURCE/);
  await assert.rejects(()=>loadSkillProjection(ref,expected,{...options,fetcher:async()=>new Response(new Uint8Array(raw.length))}),/R2_PROJECTION_HASH/);
});

function shellParts(){
  const source=readFileSync(new URL('../research-panel/workbench-host/dot/shell/workbench.local.mjs',import.meta.url),'utf8');
  const extract=(start,end)=>{const a=source.indexOf(start),b=source.indexOf(end,a);assert(a>=0&&b>a);return source.slice(a,b)};
  return {lock:extract('function lockR2Attempts(', 'const selection='),catalog:extract(' async catalog(){',' refresh(){'),init:extract('async function init(){','function railTab(')};
}

test('catalog keeps R2 identity and disables only its same-day failed attempt',async()=>{
  const {lock,catalog}=shellParts();
  function create(entries,selected,{follow=false,currentDay={}}={}){
    const select={options:entries.map(value=>({value,textContent:'',disabled:false})),value:selected,append(o){this.options.push(o)},userSelect(value){const option=this.options.find(o=>o.value===value);if(option&&!option.disabled)this.value=value}};
    const env={select,loading:{textContent:''},data:{days:[]},loads:[],loadJson:async()=>env.data,loadDay:async()=>{env.loads.push(select.value)},currentDay};
    const factory=new Function('env',`let catalogSerial=0,followLatestResearchDay=${follow},day=env.currentDay;const integrationBase='/api';const $=id=>id==='date'?env.select:env.loading;const selection=()=>({date:env.select.value.split('|')[0]});const loadJson=(...x)=>env.loadJson(...x);const loadDay=()=>env.loadDay();const node=(tag,text)=>({value:'',textContent:text,disabled:false});${lock}return {${catalog}};`);
    env.host=factory(env);return env;
  }
  const revision='a'.repeat(64),date='2026-10-28',r2=date+'|'+revision,other='2026-10-29';
  const snapshot={days:[{source_date:date,revision:null,status:'FAILED'},{source_date:date,revision,ruleset_id:'ZGE_SKILL_DAILY_CANDIDATES_R2'},{source_date:other,revision:null,status:'PARTIAL'}]};
  const env=create([r2,date,other],r2);env.data=snapshot;
  await env.host.catalog();await env.host.catalog();
  assert.equal(env.select.value,r2);assert.equal(env.select.options.length,3);
  assert.equal(env.select.options.find(o=>o.value===r2).textContent,date+' · Z哥技能R2');
  assert.equal(env.select.options.find(o=>o.value===date).textContent,date+' · FAILED');
  assert.equal(env.select.options.find(o=>o.value===date).disabled,true);
  assert.equal(env.select.options.find(o=>o.value===other).disabled,false);
  env.select.userSelect(date);assert.equal(env.select.value,r2); // mouse selection
  env.select.userSelect(date);assert.equal(env.select.value,r2); // keyboard selection
  const stale=create([date],date);stale.data=snapshot;await stale.host.catalog();
  assert.equal(stale.select.value,r2);assert.deepEqual(stale.loads,[r2]);
  let release;const waiting=create([r2,date],r2);waiting.loadJson=()=>new Promise(resolve=>release=resolve);
  const pending=waiting.host.catalog();waiting.select.value=date;release(snapshot);await pending;
  assert.equal(waiting.select.value,r2);assert.deepEqual(waiting.loads,[r2]);
  let releaseOther;const changed=create([r2,other],r2);changed.loadJson=()=>new Promise(resolve=>releaseOther=resolve);
  const pendingOther=changed.host.catalog();changed.select.value=other;releaseOther(snapshot);await pendingOther;
  assert.equal(changed.select.value,other);assert.deepEqual(changed.loads,[]);
  const old='2026-10-30|'+'b'.repeat(64),latest='2026-10-31|'+'c'.repeat(64);
  const follow=create([old],old,{follow:true});follow.data={days:[{source_date:'2026-10-30',revision:'b'.repeat(64)},{source_date:'2026-10-31',revision:'c'.repeat(64)}]};
  await follow.host.catalog();assert.equal(follow.select.value,latest);assert.deepEqual(follow.loads,[latest]);
});

test('initial URL date selects committed R2 and retains disabled attempt status',async()=>{
  const {lock,init}=shellParts(),revision='a'.repeat(64),date='2026-10-28',other='2026-10-29';
  const env={loads:[],requested:date,select:{value:'',options:[],replaceChildren(){this.options=[]},append(o){this.options.push(o)}},loading:{textContent:''}};
  const days=[{source_date:date,observation_date:other,revision:null,status:'FAILED'},
              {source_date:date,observation_date:other,revision,ruleset_id:'ZGE_SKILL_DAILY_CANDIDATES_R2'},
              {source_date:other,observation_date:'2026-10-30',revision:null,status:'PARTIAL'}];
  const factory=new Function('env','days',`let timeContract;const apiBound=true,integrationBase='/api',location={search:'?date=20261028'};const $=id=>id==='date'?env.select:env.loading;const node=(tag,text)=>({value:'',textContent:text,disabled:false});const requestedSourceDate=()=>env.requested;const renderContext=()=>{};const endpoint=()=>'/history';const loadJson=async url=>url==='/history'?{days}:{};const loadDay=async()=>{env.loads.push(env.select.value)};${lock}${init}return {init};`);
  await factory(env,days).init();
  assert.equal(env.select.value,date+'|'+revision);assert.deepEqual(env.loads,[date+'|'+revision]);
  assert.equal(env.select.options.find(o=>o.value===date+'|'+revision).textContent,date+' · Z哥技能R2');
  assert.equal(env.select.options.find(o=>o.value===date).disabled,true);
  assert.equal(env.select.options.find(o=>o.value===date).textContent,date+' · FAILED');
  assert.equal(env.select.options.find(o=>o.value===other).disabled,false);
  env.requested=null;env.loads=[];await factory(env,days).init();
  assert.equal(env.select.value,date+'|'+revision);assert.deepEqual(env.loads,[date+'|'+revision]);
});

function lunaReviewFixture(){
  const source=readFileSync(new URL('../research-panel/workbench-host/bootstrap.mjs',import.meta.url),'utf8');
  const start=source.indexOf('function showSkillReview('),end=source.indexOf('async function openSkill(',start);
  assert(start>=0&&end>start);
  class Element{
    constructor(tag){this.tag=tag;this.children=[];this.parent=null;this.textContent='';this.id='';this.className='';}
    append(child){child.parent=this;this.children.push(child);}
    insertBefore(child,before){child.parent=this;const index=this.children.indexOf(before);assert(index>=0);this.children.splice(index,0,child);}
    remove(){if(this.parent){this.parent.children=this.parent.children.filter(x=>x!==this);this.parent=null;}}
  }
  const panel=new Element('section'),chart=new Element('div'),note=new Element('p');panel.append(chart);
  note.textContent='滚轮缩放 · 复用既有绘图函数；图审仍待完成。';
  const env={panel,chart,note,Element};
  const factory=new Function('env',`let skillReviewCleanup=null;const document={createElement:tag=>new env.Element(tag),querySelector:()=>env.note};const el=id=>id==='interactivePanel'?env.panel:env.chart;const add=(host,tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;host.append(n);return n};${source.slice(start,end)}return {showSkillReview,clear(){if(skillReviewCleanup){skillReviewCleanup();skillReviewCleanup=null}}};`);
  env.view=factory(env);return env;
}
const lunaText=element=>[element.textContent,...element.children.map(lunaText)].join(' ');

test('Luna reviewed stock shows reason and collapsible evidence with factual note',()=>{
  const env=lunaReviewFixture();env.view.showSkillReview({symbol:'000429.SZ',r2_review:{status:'REVIEWED',actual_image_viewed:true,decision:'KEEP',reason:'保留原因',visible_evidence:['图面依据'],counter_evidence:['图面反证']}});
  const box=env.panel.children[0];assert.equal(box.id,'macSkillChartReview');assert.match(lunaText(box),/Luna 图审 · 保留 · 000429\.SZ/);
  assert.match(lunaText(box),/保留原因/);assert.match(lunaText(box),/图面依据/);assert.match(lunaText(box),/图面反证/);
  assert.equal(box.children.some(x=>x.tag==='details'),true);assert.match(env.note.textContent,/本股图审：保留/);assert.doesNotMatch(env.note.textContent,/图审仍待完成/);
});

test('Luna stock switches keep unreviewed and error states separate',()=>{
  const env=lunaReviewFixture();env.view.showSkillReview({symbol:'000429.SZ',r2_review:{status:'REVIEWED',actual_image_viewed:true,decision:'KEEP',reason:'上一只证据',visible_evidence:['旧证据'],counter_evidence:[]}});
  env.view.showSkillReview({symbol:'920873.BJ',r2_review:{status:'NOT_REVIEWED'}});let box=env.panel.children[0];
  assert.match(lunaText(box),/未审 · 920873\.BJ/);assert.doesNotMatch(lunaText(box),/上一只证据|旧证据/);assert.match(env.note.textContent,/本股图审：未审/);
  env.view.showSkillReview({symbol:'600000.SH',r2_review:{status:'ERROR_REVIEW_RECORD',reason:'未经核验原因'}});box=env.panel.children[0];
  assert.match(lunaText(box),/待核 · 600000\.SH/);assert.doesNotMatch(lunaText(box),/未经核验原因/);assert.match(env.note.textContent,/本股图审：待核/);
  env.view.clear();assert.equal(env.panel.children.length,1);assert.equal(env.panel.children[0],env.chart);assert.equal(env.note.textContent,'滚轮缩放 · 复用既有绘图函数；图审仍待完成。');
});

test('Luna unviewed claim cannot appear as reviewed',()=>{
  const env=lunaReviewFixture();env.view.showSkillReview({symbol:'002959.SZ',r2_review:{status:'REVIEWED',actual_image_viewed:false,decision:'KEEP',reason:'未实际查看'}});
  assert.match(lunaText(env.panel.children[0]),/待核/);assert.doesNotMatch(lunaText(env.panel.children[0]),/未实际查看/);
});

test('Luna verified keep watch defer use their own labels',()=>{
  for(const [decision,label] of [['KEEP','保留'],['WATCH','观察'],['DEFER','暂缓']]){
    const env=lunaReviewFixture();env.view.showSkillReview({symbol:'000001.SZ',r2_review:{status:'REVIEWED',actual_image_viewed:true,decision,reason:'理由',visible_evidence:['依据'],counter_evidence:[]}});
    assert.match(lunaText(env.panel.children[0]),new RegExp('Luna 图审 · '+label));assert.match(env.note.textContent,new RegExp('本股图审：'+label));
  }
});
