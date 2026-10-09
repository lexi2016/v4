import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { createRequire, stripTypeScriptTypes } from 'node:module';
import { base, market, primary, render, text, root, phase, vue } from './ssr_harness.mjs';

const runtime = createRequire(resolve(process.env.STAGE_UI_RUNTIME, 'package.json'));
const compiler = runtime('@vue/compiler-sfc');
const parser = runtime('@babel/parser');
const appPath = resolve(root, phase, 'apps/web/src/App.vue');
const appSource = readFileSync(appPath, 'utf8');
const app = compiler.parse(appSource, { filename: appPath });
assert.deepEqual(app.errors, []);
const appCompiled = compiler.compileScript(app.descriptor, { id:'app-readback-regression', inlineTemplate:true,
  templateOptions:{ssr:true} });
assert.ok(appCompiled.content.length > 10000);

function appFunctions(names, state) {
  const source = app.descriptor.scriptSetup.content;
  const ast = parser.parse(source, {sourceType:'module',plugins:['typescript']});
  const functions = ast.program.body.filter(node=>node.type==='FunctionDeclaration' && names.includes(node.id.name));
  const code = functions.map(node=>source.slice(node.start,node.end)).join('\n');
  const js = stripTypeScriptTypes(code,{mode:'strip'});
  return new Function(...Object.keys(state), js+'\nreturn {'+names.filter(name=>functions.some(f=>f.id.name===name)).join(',')+'};')(...Object.values(state));
}

function research() {
  return {schema_version:'HK_CURRENT_DAY_RESEARCH_V1',mode:'CURRENT_DAY_RESEARCH_ONLY',market:'HK_CONNECT',
    trade_date:'20261009',universe_as_of:'20261008',captured_at:'2026-10-09T15:38:41+08:00',
    stale_universe:true,hk_connect_membership_status:'CANNOT_CONFIRM',formal_d1_eligible:false,source_sha256:'c'.repeat(64)};
}
function hkResult() {
  return {status:'RESULT_AVAILABLE',selection_status:'CANNOT_CONFIRM',selected_rows:10,requested_rows:216,
    source_rows:206,missing_quote_rows:10,quote_coverage_ratio:206/216,
    trade_date:'20261009',stage_id:'STAGE_0930_0935',market:'HK_CONNECT',
    run_id:'run-hk-readback',artifact_id:'selection-hk-readback',algorithm_sha256:'a'.repeat(64),
    raw_artifact_sha256:'b'.repeat(64),research_source:research(),research_source_status:'RECORDED_IN_VERIFIED_SELECTION'};
}

test('calculated HK research result keeps count, quote coverage and source limitations visible independently',async()=>{
  const evidence=base();evidence.stage_id='STAGE_0930_0935';evidence.selection_results.HK_CONNECT=hkResult();
  const visible=market(primary(await render(evidence)),'HK_CONNECT');
  assert.match(visible,/已计算 10 只/);
  assert.match(visible,/行情 206 \/ 216 只，缺 10 只/);
  assert.match(visible,/研究来源限制/);
  assert.match(visible,/名单日期 20261008/);
  assert.match(visible,/采集时间 2026-10-09T15:38:41\+08:00/);
  assert.match(visible,/沿用较早名单/);
  assert.match(visible,/港股通资格待确认/);
  assert.match(visible,/非正式 D1/);
});

test('research source conflict stays separate from ten calculated rows',async()=>{
  const evidence=base();evidence.stage_id='STAGE_0930_0935';evidence.selection_results.HK_CONNECT={...hkResult(),research_source:null,research_source_status:'CANNOT_CONFIRM'};
  const visible=market(primary(await render(evidence)),'HK_CONNECT');
  assert.match(visible,/已计算 10 只/);
  assert.match(visible,/研究来源记录待核对/);
});

for (const [field,value] of [['trade_date','20261008'],['stage_id','STAGE_0925'],['market','A_SHARE']]) {
  test(`evidence panel refuses summary scope mismatch in ${field}`,async()=>{
    const evidence=base();evidence.stage_id='STAGE_0930_0935';
    evidence.selection_results.HK_CONNECT={...hkResult(),[field]:value};
    const visible=market(primary(await render(evidence)),'HK_CONNECT');
    assert.doesNotMatch(visible,/已计算 10 只/);
    assert.match(visible,/结果身份待核对/);
  });
}

for(const update of [{execution_origin:'MANUAL_REPLAY'}, {execution_origin:'HISTORICAL_BACKFILL'},
  {execution_origin:'LATE_CATCHUP_REPLAY'},{due_status:'HISTORICAL_BACKFILL'},
  {due_status:'LATE_CATCHUP_REPLAY'},{same_day_late_observation_recovery:true},
  {attempt_mode_status:'NATURAL_DECLARATION_CONFLICT'}]) {
  test(`explicit replay evidence never renders a natural trigger: ${JSON.stringify(update)}`,async()=>{
    const evidence=base();Object.assign(evidence,{attempt_mode:'NATURAL',due_status:'DUE'},update);
    const visible=text(primary(await render(evidence)));
    assert.doesNotMatch(visible,/自然触发（NATURAL）/);
    assert.match(visible,/补验|回放|回看/);
    assert.match(visible,/自然时段验收 尚未验证/);
  });
}

function workbench() {
  const result=hkResult();
  return {trade_date:'20261009',stage:{stage_id:'STAGE_0930_0935'},selected_hk_rows:10,
    markets:{HK:{display_mode:'CANNOT_CONFIRM',selected_rows:10,run_id:result.run_id,artifact_id:result.artifact_id,
      algorithm_sha256:result.algorithm_sha256,raw_artifact_sha256:result.raw_artifact_sha256}},
    unified_rows:Array.from({length:10},(_,i)=>({market:'HK',code:`HK.${String(i+1).padStart(5,'0')}`,rank:i+1})),
    execution_evidence:{trade_date:'20261009',stage_id:'STAGE_0930_0935',selection_results:{HK_CONNECT:result}}};
}

function appState(payload) {
  return {stageWorkbench:vue.ref(payload),selectedDate:vue.ref('20261009'),selectedStage:vue.ref('STAGE_0930_0935'),
    isBackfillReadOnly:vue.ref(false),stageLoading:vue.ref(false),stageError:vue.ref(''),
    approvedACandidateBinding:vue.ref(undefined),approvedHKCandidateBinding:vue.ref(undefined),
    hkSummary:vue.ref(payload.markets.HK),aCandidateRows:vue.ref([]),hkCandidateRows:vue.ref(payload.unified_rows),
    stageCountText:v=>v==null?'未知':String(v)};
}

test('existing App HK count function displays ten verified research rows despite CANNOT_CONFIRM',()=>{
  const payload=workbench();
  const methods=appFunctions(['verifiedResearchResult','candidateColumnCountLabel','marketDisplayCount'],appState(payload));
  assert.match(methods.candidateColumnCountLabel('HK'),/已计算 10 只/);
  assert.match(methods.marketDisplayCount(payload.markets.HK,10,10,payload,'HK'),/已计算 10 只/);
});

for(const fault of ['date','stage','run','sha','market','no_evidence']) {
  test(`existing App count does not borrow a research summary with conflicting ${fault}`,()=>{
    const payload=workbench();
    const result=payload.execution_evidence.selection_results.HK_CONNECT;
    if(fault==='date')payload.execution_evidence.trade_date='20261008';
    if(fault==='stage')payload.execution_evidence.stage_id='STAGE_0925';
    if(fault==='run')result.run_id='other';
    if(fault==='sha')result.raw_artifact_sha256='e'.repeat(64);
    if(fault==='market')result.market='A_SHARE';
    if(fault==='no_evidence')delete payload.execution_evidence;
    const methods=appFunctions(['verifiedResearchResult','candidateColumnCountLabel','marketDisplayCount'],appState(payload));
    assert.doesNotMatch(methods.candidateColumnCountLabel('HK'),/已计算 10 只/);
  });
}

test('SFC runtime can render the consumer JSON fixture through the actual evidence panel',async(t)=>{
  const fixture=process.env.STAGE_UI_CONSUMER_FIXTURE;
  if(!fixture)return t.skip('generated consumer fixture is exercised after API green');
  const payload=JSON.parse(readFileSync(fixture,'utf8'));
  const visible=market(primary(await render(payload.execution_evidence)),'HK_CONNECT');
  assert.equal(payload.markets.HK_CONNECT.rows.length,10);
  assert.match(visible,/已计算 10 只/);
  assert.match(visible,/研究来源限制/);
  assert.doesNotMatch(text(primary(await render(payload.execution_evidence))),/自然触发（NATURAL）/);
});

test('original API projection preserves same-run research identity through the actual App count functions',(t)=>{
  const fixture=process.env.STAGE_UI_CONSUMER_FIXTURE;
  if(!fixture)return t.skip('generated API projection fixture is exercised after API green');
  const payload=JSON.parse(readFileSync(resolve(dirname(fixture),'workbench_response.json'),'utf8'));
  const methods=appFunctions(['verifiedResearchResult','candidateColumnCountLabel','marketDisplayCount'],appState(payload));
  const summary=payload.execution_evidence.selection_results.HK_CONNECT;
  assert.equal(payload.markets.HK.display_mode,'OBSERVATION_UNVERIFIED');
  assert.equal(payload.markets.HK.selected_rows,null);
  for(const key of ['run_id','artifact_id','algorithm_sha256','raw_artifact_sha256'])
    assert.equal(payload.markets.HK[key],summary[key]);
  assert.equal(summary.requested_rows,695);
  assert.equal(summary.source_rows,695);
  assert.equal(payload.markets.HK.rows.length,10);
  assert.match(methods.candidateColumnCountLabel('HK'),/已计算 10 只/);
  assert.match(methods.marketDisplayCount(payload.markets.HK,10,10,payload,'HK'),/已计算 10 只/);
});

test('backfill result is never labeled natural by a different namespace receipt',async()=>{
  const evidence=base();evidence.stage_id='STAGE_0930_0935';evidence.attempt_mode='NATURAL';evidence.due_status='DUE';
  evidence.selection_results.HK_CONNECT={...hkResult(),selection_mode:'BACKFILL'};
  evidence.selection_artifact_bindings.HK_CONNECT={status:'EXECUTION_RECEIPT_NAMESPACE_NOT_BOUND'};
  const html=primary(await render(evidence));
  assert.match(market(html,'HK_CONNECT'),/已计算 10 只/);
  assert.doesNotMatch(text(html),/自然触发（NATURAL）/);
  assert.match(text(html),/历史回补/);
});
