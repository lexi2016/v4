import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {parseArgs} from 'node:util';

const {values: options} = parseArgs({options:{
  base:{type:'string',default:'http://127.0.0.1:18973'}, fixture:{type:'string'},
  playwright:{type:'string'}, chrome:{type:'string'},
  'exercise-regressions':{type:'boolean'}, 'require-f10-completion':{type:'boolean'},
  'exercise-observation-coverage':{type:'boolean'}, 'observation-coverage-shell':{type:'string'},
  'top200-group-module':{type:'string'},
  'observation-coverage-only':{type:'boolean'},
}});
const observationCoverageOnly=options['observation-coverage-only']===true;
if(observationCoverageOnly)assert.ok(options['exercise-observation-coverage'],'Coverage-only browser mode requires the observation-coverage fixture');
const golden = {
  sourceDate:'2026-11-13',observationDate:'2026-11-16',
  positive:{symbol:'603658.SH',score:3,marker:'B1',anchor:'36.89400',
    company:['体外诊断试剂和仪器的研发、制造、整合及服务。','通达信 F10'],
    financial:['报告期 2026-09-30','营业总收入：32.3953亿','净利润：8.4709亿','34,932']},
  gapSymbol:'300015.SZ',
};
const fixture = options.fixture ? JSON.parse(await readFile(options.fixture,'utf8')) : golden;
const {sourceDate,observationDate,positive,gapSymbol} = fixture;
assert.match(sourceDate,/^\d{4}-\d{2}-\d{2}$/);
assert.match(observationDate,/^\d{4}-\d{2}-\d{2}$/);
for (const symbol of [positive.symbol,gapSymbol]) assert.match(symbol,/^\d{6}\.(SH|SZ|BJ)$/);
assert.ok(positive.symbol!==gapSymbol && Number.isInteger(positive.score) && positive.marker && positive.anchor);
assert.ok(positive.company.length && positive.financial.length);
const base = new URL(options.base);
assert.ok(base.protocol==='http:'&&['localhost','127.0.0.1','[::1]'].includes(base.hostname)&&
  base.pathname==='/'&&!base.search&&!base.hash&&!base.username&&!base.password,'A loopback preview origin is required');
const modulePath = options.playwright ?? process.env.WORKBENCH_PLAYWRIGHT;
const {chromium} = await import(modulePath ? pathToFileURL(modulePath) : 'playwright');
const chrome = options.chrome ?? process.env.WORKBENCH_CHROME;
const dayPath = `/api/v4/research/workbench/days/${sourceDate}`;
const dayCode = sourceDate.replaceAll('-','');
const url = new URL('/research-panel/workbench.html',base);
url.search = new URLSearchParams({source_date:sourceDate,observation_date:observationDate,symbol:positive.symbol});
const f10Path = symbol => `${dayPath}/f10/${symbol}`;
const scorePath = `${dayPath}/single-research/${positive.symbol}`;
const chartPath = `${dayPath}/formula-daily-k/${positive.symbol}`;
const sha = value => typeof value==='string' && /^[a-f0-9]{64}$/.test(value);
const flags = {RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false};

async function get(path) {
  const response = await fetch(new URL(path,base),{redirect:'error',signal:AbortSignal.timeout(10000)});
  assert.equal(response.status,200,path);
  return response.json();
}
const [day,chart,score,f10,gap] = observationCoverageOnly
  ? [await get(dayPath),null,null,null,null]
  : await Promise.all([get(dayPath),get(chartPath),get(scorePath),get(f10Path(positive.symbol)),get(f10Path(gapSymbol))]);
assert.ok(day.formula_groups && day.source_date===sourceDate && day.observation_date===observationDate);
assert.ok(sha(day.generation)&&sha(day.input_sha256)&&sha(day.numeric_manifest?.sha256));
if(observationCoverageOnly){
  for(const [key,expected]of Object.entries(flags))assert.equal(day[key],expected,key);
  assert.ok(day.rows.some(row=>row.symbol===positive.symbol&&row.eligible_candidate===true),positive.symbol);
}else{
  for (const symbol of [positive.symbol,gapSymbol]) assert.ok(day.rows.some(row=>row.symbol===symbol),symbol);
  for (const value of [day,chart,score,f10,gap]) {
    for (const [key,expected] of Object.entries(flags)) assert.equal(value[key],expected,key);
    assert.equal(value.generation??value.source_generation,day.generation);
    assert.equal(value.input_sha256,day.input_sha256);
  }
  for (const value of [chart,score,f10]) assert.equal(value.symbol,positive.symbol);
  for (const value of [chart,score]) {
    assert.equal(value.source_date,sourceDate);
    assert.deepEqual(value.numeric_manifest,day.numeric_manifest);
  }
  assert.equal(chart.rows.at(-1).trade_date,dayCode);
  assert.equal(chart.original_marks?.status,'READY');
  assert.equal(chart.original_marks.symbol,positive.symbol);
  assert.equal(chart.original_marks.generation,day.generation);
  assert.equal(chart.original_marks.input_sha256,day.input_sha256);
  assert.ok(chart.original_marks.marks.some(mark=>mark.trade_date===dayCode&&mark.payload===positive.marker&&mark.y===positive.anchor),'API has no golden original mark');
  assert.equal(score.status,'MATERIALIZED');
  assert.equal(score.row?.hold_score?.kb_hold_score,positive.score);
  assert.equal(f10.status,'OBSERVED');
  assert.equal(f10.data_date,dayCode);
  assert.ok(sha(f10.receipt?.sha256)&&sha(f10.stock_ref?.sha256));
  assert.equal(gap.symbol,gapSymbol);
  assert.equal(gap.data_date,dayCode);
  assert.equal(gap.status,'CANNOT_CONFIRM_SOURCE_GAP');
  assert.ok(sha(gap.receipt?.sha256)&&!gap.f10);
}

const completion = options['require-f10-completion']&&!observationCoverageOnly ? await get(`${dayPath}/versions`) : null;
if (completion) {
  assert.equal(completion.source_date,sourceDate);
  assert.equal(completion.observation_date,observationDate);
  assert.equal(completion.generation,day.generation);
  assert.equal(completion.input_sha256,day.input_sha256);
  assert.deepEqual(completion.numeric_manifest,day.numeric_manifest);
  assert.ok(sha(completion.modules?.f10),'No validated F10 completion fingerprint');
}

const observationPath=`${dayPath}/observations`;
const observationCoverageShell=options['observation-coverage-shell']
  ? await readFile(options['observation-coverage-shell'],'utf8') : null;
const top200GroupModule=options['top200-group-module']
  ? await readFile(options['top200-group-module'],'utf8') : null;
if(options['exercise-observation-coverage'])assert.ok(observationCoverageShell,'Coverage exercise requires the exact scoped workbench shell source');
const observationCoverageProbe=(()=>{
  const expected=day.rows.filter(row=>row.eligible_candidate===true).map(row=>row.symbol).sort();
  assert.ok(expected.includes(positive.symbol),'Coverage probe stock is not an eligible candidate');
  const invalidSymbol=expected.find(symbol=>symbol!==positive.symbol);
  const outsideSymbol=day.rows.find(row=>!expected.includes(row.symbol))?.symbol??'999999.BJ';
  const absentSourceSymbol=['999998.SH','999997.SZ','999996.BJ','999995.SZ']
    .find(symbol=>!expected.includes(symbol)&&symbol!==outsideSymbol);
  assert.ok(absentSourceSymbol,'Coverage probe needs an absent source symbol');
  const sourceExpected=[...expected,outsideSymbol,absentSourceSymbol].sort();
  const observed=[positive.symbol,...(invalidSymbol?[invalidSymbol]:[]),outsideSymbol];
  const validCount=observed.length-(invalidSymbol?1:0);
  const sourceError='FUTU_API_RATE_LIMIT: 429 rate limit';
  const status=sourceExpected.length===0?'EMPTY':validCount===0?'ZERO_VALID':validCount<sourceExpected.length?'PARTIAL':'COMPLETE';
  const reasons=status==='PARTIAL'?['MISSING_CANDIDATE_OBSERVATION_ROWS',sourceError]:
    status==='EMPTY'?['EMPTY_EXPECTED_CANDIDATE_SCOPE']:
    status==='ZERO_VALID'?['ZERO_VALID_OBSERVATION_ROWS']:[];
  const row=(symbol,change,rankEligible,error=null)=>({symbol,error,source_asof:`${observationDate}T10:00:00+08:00`,
    observed_at_upper_bound:`${observationDate}T10:00:30+08:00`,status:'CURRENT_VISIBLE_FIELDS_CHECKED',
    currency:'CNY',price:10,amount_source:100000,change_percent_source:change,
    percent_change_rank_eligible:rankEligible,volume_rank_eligible:false,comparable_volume_shares:null});
  const snapshot={schema:'OBSERVATION_SNAPSHOT_VIEW_V1',source_date:sourceDate,observation_date:observationDate,
    source_generation:day.generation,input_sha256:day.input_sha256,parent_admission_sha256:day.generation,
    daily_contract_sha256:createHash('sha256').update(JSON.stringify(sourceExpected)).digest('hex'),
    rows:[row(positive.symbol,1,true),...(invalidSymbol?[row(invalidSymbol,99,false,sourceError)]:[]),row(outsideSymbol,999,true)],
    analysis_admission:'NOT_GRANTED',formula_review:'PENDING',context:{},context_sha256:'0'.repeat(64),
    snapshot_sha256:'1'.repeat(64),slot:'1000',source_asof_min:`${observationDate}T10:00:00+08:00`,
    source_asof_max:`${observationDate}T10:00:00+08:00`,observed_upper_bound_max:`${observationDate}T10:00:30+08:00`,
    RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false};
  return {invalidSymbol,outsideSymbol,sourceError,sourceExpected,snapshot,response:{latest:snapshot,status:'STORED_ONLY',
    coverage:{schema:'V4_WORKBENCH_OBSERVATION_COVERAGE_V1',scope_kind:'SOURCE_PRODUCT',status,
      source_date:sourceDate,observation_date:observationDate,generation:day.generation,input_sha256:day.input_sha256,
      numeric_manifest:day.numeric_manifest,expected_count:sourceExpected.length,observed_count:observed.length,
      valid_count:validCount,missing_count:sourceExpected.length-validCount,reasons,
      RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false},
    RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false}};
})();
const observationCoverageDay=observationCoverageOnly?{
  ...day,
  formula_groups:{...day.formula_groups,labels:{b23_entry:'192选股',pb2_confirm:'回测选股'},status:'READY'},
}:day;

const browser = await chromium.launch({headless:true,...(chrome?{executablePath:chrome}:{})});
try {
  async function check(fault) {
    const page = await browser.newPage({viewport:{width:1440,height:960}});
    const reads=[], requests=[], errors=[];
    const routeHits={shell:0,top200:0,day:0,observations:0};
    page.on('request',request=>{
      if (request.method()==='GET') requests.push(new URL(request.url()).pathname);
    });
    page.on('response',response=>{
      if (response.request().method()==='GET' && response.ok()) reads.push(new URL(response.url()).pathname);
    });
    page.on('pageerror',error=>errors.push(error.message));
    if(observationCoverageShell)await page.route(url=>url.pathname==='/research-panel/workbench-host/dot/shell/workbench.local.mjs',route=>{
      routeHits.shell++;return route.fulfill({status:200,contentType:'text/javascript',body:observationCoverageShell});
    });
    if(top200GroupModule)await page.route(url=>url.pathname==='/research-panel/workbench-host/top200-group.mjs',route=>{
      routeHits.top200++;return route.fulfill({status:200,contentType:'text/javascript',body:top200GroupModule});
    });
    if(observationCoverageOnly)await page.route(requestUrl=>requestUrl.pathname===dayPath,route=>{
      routeHits.day++;return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(observationCoverageDay)});
    });
    if(options['exercise-observation-coverage']&&fault==='none')await page.route(url=>url.pathname===observationPath,route=>{
      routeHits.observations++;return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(observationCoverageProbe.response)});
    });
    await page.addInitScript(({fault,marker})=>{
      window.__acceptedDraws=new Set();
      window.__completionStreams=new Map();
      const nativeEventSource=window.EventSource;
      window.EventSource=class extends nativeEventSource {
        constructor(path,...args){
          super(path,...args);
          const channel={stream:this,latest:null};
          window.__completionStreams.set(new URL(path,location.origin).pathname,channel);
          this.addEventListener('workbench_completed',event=>{channel.latest=JSON.parse(event.data);});
        }
      };
      for (const method of ['fillText','strokeText']) {
        const native=CanvasRenderingContext2D.prototype[method];
        CanvasRenderingContext2D.prototype[method]=function(text,x,y,...rest){
          const symbol=this.canvas.closest('#formulaDailyChart')?.dataset.symbol;
          const inChart=symbol&&text===marker;
          if (inChart&&fault==='omit-chart-paint') return;
          const result=native.call(this,text,x,y,...rest);
          if (inChart&&method==='fillText'&&x>=0&&y>=0&&x<this.canvas.clientWidth&&y<this.canvas.clientHeight) window.__acceptedDraws.add(symbol);
          return result;
        };
      }
    },{fault,marker:positive.marker});
    if (fault==='omit-score') await page.route(requestUrl=>requestUrl.pathname===scorePath,async route=>{
      const actual=await route.fetch();
      await route.fulfill({response:actual,json:{...await actual.json(),status:'UNKNOWN',reason:'SYMBOL_NOT_MATERIALIZED_FOR_DATE',row:null}});
    });
    if (fault==='company-instead-of-f10') await page.route(requestUrl=>requestUrl.pathname===f10Path(positive.symbol),async route=>{
      const legacy=new URL(route.request().url());
      legacy.pathname=`${dayPath}/company/${positive.symbol}`;
      await route.fulfill({response:await route.fetch({url:legacy.href})});
    });
    async function expectView(code, condition, args) {
      try { await page.waitForFunction(condition,args,{timeout:fault==='none'?15000:4500}); }
      catch (cause) {
        const state=await page.evaluate(()=>Object.fromEntries(['stockCode','dates','kbSingleScore','formulaCompanySummary','formulaCompanyMetrics','loadingState','observationSummary','observationMini','listCount']
          .map(id=>[id,document.getElementById(id)?.innerText]))).catch(()=>({}));
        const relevant=requests.filter(path=>path.includes('/observations')||path.includes('/days/'));
        throw Object.assign(new Error(`${code}: ${JSON.stringify({fault,state,errors,routeHits,relevant})}`,{cause}),{code});
      }
    }
    try {
      await page.goto(url.href,{waitUntil:'domcontentloaded'});
      if(observationCoverageOnly){
        await expectView('COVERAGE_WORKBENCH_NOT_READY',({symbol})=>{
          return !document.getElementById('content')?.hidden&&document.getElementById('stockCode')?.textContent===symbol&&
            Boolean(document.querySelector(`#stockList [data-symbol="${symbol}"]`));
        },{symbol:positive.symbol});
        await expectView('OBSERVATION_COVERAGE_NOT_RENDERED',({expected,valid})=>{
          const summary=document.getElementById('observationSummary')?.textContent??'';
          const mini=document.getElementById('observationMini')?.innerText??'';
          const state=`源产品观察范围覆盖 部分，有效 ${valid} / 应有 ${expected}`;
          return mini.includes(state)&&summary.includes(state)&&
            summary.includes('源产品观察范围未全覆盖');
        },{expected:observationCoverageProbe.response.coverage.expected_count,
          valid:observationCoverageProbe.response.coverage.valid_count});
        assert.ok(reads.includes(observationPath),'The browser did not read its bound observation fixture');
        await page.locator('#stockSort').evaluate(select=>{select.value='percent_change_desc';select.dispatchEvent(new Event('change',{bubbles:true}));});
        const visibleSymbols=await page.locator('#stockList [data-symbol]').evaluateAll(nodes=>nodes.map(node=>node.dataset.symbol));
        const rows=await page.locator('#stockList [data-symbol]').evaluateAll(nodes=>nodes.slice(0,5).map(node=>({symbol:node.dataset.symbol,title:node.title})));
        assert.equal(visibleSymbols[0],positive.symbol,`A row without valid percent-rank eligibility displaced the valid row; mode=${await page.locator('#stockSort').inputValue()} rows=${JSON.stringify(rows)}`);
        if(observationCoverageProbe.invalidSymbol&&visibleSymbols.includes(observationCoverageProbe.invalidSymbol))
          assert.ok(visibleSymbols.indexOf(positive.symbol)<visibleSymbols.indexOf(observationCoverageProbe.invalidSymbol));
        assert.ok(!visibleSymbols.includes(observationCoverageProbe.outsideSymbol),'A source-only symbol leaked into the visible formula roster');
        const missingVisible=day.rows.find(row=>row.eligible_candidate===true&&
          !observationCoverageProbe.snapshot.rows.some(observed=>observed.symbol===row.symbol));
        if(missingVisible){
          assert.ok(visibleSymbols.includes(missingVisible.symbol),'The missing visible row should stay on the first page');
          const price=await page.locator(`#stockList [data-symbol="${missingVisible.symbol}"] .grid-price`).innerText();
          assert.equal(price,'—','A visible symbol absent from the saved observation set must stay unavailable');
          await page.locator(`#stockList [data-symbol="${missingVisible.symbol}"]`).click();
          await page.waitForFunction(symbol=>document.getElementById('stockCode')?.textContent===symbol&&
            document.getElementById('selectedObservation')?.innerText.includes('本股未出现在已保存的源产品观察集'),
          missingVisible.symbol,{timeout:5000});
        }
        assert.deepEqual(errors,[]);
        return;
      }
      await expectView('ORIGINAL_MARK_NOT_PAINTED',({symbol,dayCode,marker,anchor})=>{
        const host=document.getElementById('formulaDailyChart');
        const canvas=host?.querySelector('canvas');
        return document.getElementById('stockCode')?.textContent===symbol&&host?.dataset.symbol===symbol&&
          !host.hidden&&canvas?.getBoundingClientRect().width>100&&canvas.getBoundingClientRect().height>100&&
          host.querySelector('select')?.value===dayCode&&host.innerText.includes(`${marker} @${anchor}`)&&window.__acceptedDraws.has(symbol);
      },{symbol:positive.symbol,dayCode,marker:positive.marker,anchor:positive.anchor});
      await expectView('EXACT_SCORE_NOT_RENDERED',({symbol,sourceDate,score})=>{
        const get=id=>document.getElementById(id);
        const card=get('kbSingleResearch');
        return card?.getBoundingClientRect().height>0&&get('stockCode')?.textContent===symbol&&
          get('kbSingleCode')?.textContent===symbol&&get('kbSingleStatus')?.innerText.includes(sourceDate)&&
          get('kbSingleScore')?.innerText.includes(`${score}/5`);
      },{symbol:positive.symbol,sourceDate,score:positive.score});
      await expectView('EXACT_F10_NOT_RENDERED',({symbol,company,financial})=>{
        const a=document.getElementById('formulaCompanySummary'),b=document.getElementById('formulaCompanyMetrics');
        return a?.getBoundingClientRect().height>0&&b?.getBoundingClientRect().height>0&&a.dataset.companySymbol===symbol&&b.dataset.companySymbol===symbol&&
          company.every(value=>a.innerText.includes(value))&&financial.every(value=>b.innerText.includes(value));
      },positive);
      if(options['exercise-observation-coverage']&&fault==='none'){
        await expectView('OBSERVATION_COVERAGE_NOT_RENDERED',({expected,valid,partial})=>{
          const summary=document.getElementById('observationSummary')?.textContent??'';
          const mini=document.getElementById('observationMini')?.innerText??'';
          const state=partial?`部分，有效 ${valid} / 应有 ${expected}`:`完整，有效 ${valid} / 应有 ${expected}`;
          const coverage=`源产品观察范围覆盖 ${state}`;
          return mini.includes(coverage)&&summary.includes(coverage)&&(!partial||summary.includes('源产品观察范围未全覆盖'));
        },{expected:observationCoverageProbe.response.coverage.expected_count,
          valid:observationCoverageProbe.response.coverage.valid_count,
          partial:observationCoverageProbe.response.coverage.status==='PARTIAL'});
        await page.locator('#stockSort').evaluate(select=>{select.value='percent_change_desc';select.dispatchEvent(new Event('change',{bubbles:true}));});
        const visibleSymbols=await page.locator('#stockList [data-symbol]').evaluateAll(nodes=>nodes.map(node=>node.dataset.symbol));
        const rows=await page.locator('#stockList [data-symbol]').evaluateAll(nodes=>nodes.slice(0,5).map(node=>({symbol:node.dataset.symbol,title:node.title})));
        assert.equal(visibleSymbols[0],positive.symbol,`A row without valid percent-rank eligibility displaced the valid row; mode=${await page.locator('#stockSort').inputValue()} rows=${JSON.stringify(rows)}`);
        if(observationCoverageProbe.invalidSymbol&&visibleSymbols.includes(observationCoverageProbe.invalidSymbol))
          assert.ok(visibleSymbols.indexOf(positive.symbol)<visibleSymbols.indexOf(observationCoverageProbe.invalidSymbol));
        assert.ok(!visibleSymbols.includes(observationCoverageProbe.outsideSymbol),'A source-only symbol leaked into the visible formula roster');
        const missingVisible=day.rows.find(row=>row.eligible_candidate===true&&
          !observationCoverageProbe.snapshot.rows.some(observed=>observed.symbol===row.symbol));
        if(missingVisible){
          const price=await page.locator(`#stockList [data-symbol="${missingVisible.symbol}"] .grid-price`).innerText();
          assert.equal(price,'—','A visible symbol absent from the saved observation set must stay unavailable');
        }
      }
      for (const path of [chartPath,scorePath,f10Path(positive.symbol)]) assert.ok(reads.includes(path),`Missing browser response ${path}`);
      if(options['exercise-observation-coverage']&&fault==='none')assert.ok(reads.includes(observationPath));
      if (fault==='none'&&completion) {
        const streamPath=`${dayPath}/events`;
        const handle=await page.waitForFunction(({path,marker})=>window.__completionStreams.get(path)?.latest?.modules?.f10 &&
          document.getElementById('formulaCompanySummary')?.innerText.includes(marker) && window.__completionStreams.get(path).latest,{path:streamPath,marker:positive.company[0]});
        const latest=await handle.jsonValue();
        assert.equal(latest.generation,completion.generation);
        assert.equal(latest.input_sha256,completion.input_sha256);
        const corrupt={...latest,generation:'0'.repeat(64)};
        const inject=event=>page.evaluate(({path,event})=>{
          const channel=window.__completionStreams.get(path);
          channel.stream.dispatchEvent(new MessageEvent('workbench_completed',{data:JSON.stringify(event)}));
        },{path:streamPath,event});
        const count = () => requests.filter(path=>path===f10Path(positive.symbol)).length;
        const nextEvent=(baseValue,byte)=>({...baseValue,modules:{...baseValue.modules,f10:byte.repeat(64)}});
        const initial=count();
        await inject(nextEvent(corrupt,'1'));
        await page.waitForTimeout(350);
        assert.equal(count(),initial,'An unrelated generation refreshed the chart stock F10');
        const fresh=page.waitForResponse(response=>new URL(response.url()).pathname===f10Path(positive.symbol)&&response.ok(),{timeout:8500});
        await inject(nextEvent(latest,'2'));
        const refreshed=await (await fresh).json();
        assert.equal(refreshed.symbol,positive.symbol);
        assert.equal(refreshed.data_date,dayCode);
        assert.equal(refreshed.source_generation,day.generation);
        assert.equal(refreshed.input_sha256,day.input_sha256);
      }
      await page.locator('#query').fill(gapSymbol);
      await expectView('F10_GAP_NOT_RENDERED',({symbol,oldRevenue})=>{
        const get=id=>document.getElementById(id),company=get('formulaCompanySummary'),metrics=get('formulaCompanyMetrics');
        return get('stockCode')?.textContent===symbol&&company?.getBoundingClientRect().height>0&&metrics?.getBoundingClientRect().height>0&&
          company.dataset.companySymbol===symbol&&metrics.dataset.companySymbol===symbol&&company.innerText.includes('本股缺少可用快照')&&
          metrics.innerText.includes('本日 F10 财务与股东资料待核')&&oldRevenue.every(value=>!metrics.innerText.includes(value));
      },{symbol:gapSymbol,oldRevenue:positive.financial});
      assert.ok(reads.includes(f10Path(gapSymbol)));
      assert.deepEqual(errors,[]);
    } finally { await page.close(); }
  }
  await check('none');
  const caught=[];
  if (options['exercise-regressions']) {
    for (const [fault,code] of [['omit-chart-paint','ORIGINAL_MARK_NOT_PAINTED'],['omit-score','EXACT_SCORE_NOT_RENDERED'],['company-instead-of-f10','EXACT_F10_NOT_RENDERED']]) {
      await assert.rejects(()=>check(fault),error=>error.code===code,`${fault} must fail for its own reason`);
      caught.push(code);
    }
  }
  console.log(JSON.stringify({status:observationCoverageOnly?'PASS_FORMULA_WORKBENCH_COVERAGE_BROWSER':'PASS_FORMULA_WORKBENCH_BROWSER',base:base.origin,sourceDate,observationDate,generation:day.generation,
    input_sha256:day.input_sha256,marker:positive.marker,score:positive.score,observed:positive.symbol,gap:gapSymbol,
    f10_completion_checked:Boolean(completion),observation_coverage:options['exercise-observation-coverage']?observationCoverageProbe.response.coverage.status:'NOT_RUN',
    fixture_mode:observationCoverageOnly?'ISOLATED_COVERAGE_FIXTURE':'FULL_BROWSER_FLOW',negative_controls:caught}));
} finally { await browser.close(); }
