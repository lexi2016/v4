import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {parseArgs} from 'node:util';

const {values: options} = parseArgs({options:{
  base:{type:'string',default:'http://127.0.0.1:18973'}, fixture:{type:'string'},
  playwright:{type:'string'}, chrome:{type:'string'},
  'exercise-regressions':{type:'boolean'}, 'require-f10-completion':{type:'boolean'},
}});
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
const [day,chart,score,f10,gap] = await Promise.all([get(dayPath),get(chartPath),get(scorePath),get(f10Path(positive.symbol)),get(f10Path(gapSymbol))]);
assert.ok(day.formula_groups && day.source_date===sourceDate && day.observation_date===observationDate);
assert.ok(sha(day.generation)&&sha(day.input_sha256)&&sha(day.numeric_manifest?.sha256));
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

const completion = options['require-f10-completion'] ? await get(`${dayPath}/versions`) : null;
if (completion) {
  assert.equal(completion.source_date,sourceDate);
  assert.equal(completion.observation_date,observationDate);
  assert.equal(completion.generation,day.generation);
  assert.equal(completion.input_sha256,day.input_sha256);
  assert.deepEqual(completion.numeric_manifest,day.numeric_manifest);
  assert.ok(sha(completion.modules?.f10),'No validated F10 completion fingerprint');
}

const browser = await chromium.launch({headless:true,...(chrome?{executablePath:chrome}:{})});
try {
  async function check(fault) {
    const page = await browser.newPage({viewport:{width:1440,height:960}});
    const reads=[], requests=[], errors=[];
    page.on('request',request=>{
      if (request.method()==='GET') requests.push(new URL(request.url()).pathname);
    });
    page.on('response',response=>{
      if (response.request().method()==='GET' && response.ok()) reads.push(new URL(response.url()).pathname);
    });
    page.on('pageerror',error=>errors.push(error.message));
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
        const state=await page.evaluate(()=>Object.fromEntries(['stockCode','dates','kbSingleScore','formulaCompanySummary','formulaCompanyMetrics']
          .map(id=>[id,document.getElementById(id)?.innerText]))).catch(()=>({}));
        throw Object.assign(new Error(`${code}: ${JSON.stringify({fault,state,errors})}`,{cause}),{code});
      }
    }
    try {
      await page.goto(url.href,{waitUntil:'domcontentloaded'});
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
      for (const path of [chartPath,scorePath,f10Path(positive.symbol)]) assert.ok(reads.includes(path),`Missing browser response ${path}`);
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
  console.log(JSON.stringify({status:'PASS_FORMULA_WORKBENCH_BROWSER',base:base.origin,sourceDate,observationDate,generation:day.generation,
    input_sha256:day.input_sha256,marker:positive.marker,score:positive.score,observed:positive.symbol,gap:gapSymbol,
    f10_completion_checked:Boolean(completion),negative_controls:caught}));
} finally { await browser.close(); }
