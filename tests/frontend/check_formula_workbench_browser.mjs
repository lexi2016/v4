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
for (const symbol of [positive.symbol,...(gapSymbol?[gapSymbol]:[]),...(fixture.companyCases??[]).map(item=>item.symbol)]) assert.match(symbol,/^\d{6}\.(SH|SZ|BJ)$/);
assert.ok((!gapSymbol||positive.symbol!==gapSymbol) && Number.isInteger(positive.score) && positive.marker && positive.anchor);
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
const companyPath = symbol => `${dayPath}/company/${symbol}`;
const scorePath = `${dayPath}/single-research/${positive.symbol}`;
const chartPath = `${dayPath}/formula-daily-k/${positive.symbol}`;
const top200Path = `${dayPath}/top200`;
const sha = value => typeof value==='string' && /^[a-f0-9]{64}$/.test(value);
const flags = {RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false};

async function get(path) {
  const response = await fetch(new URL(path,base),{redirect:'error',signal:AbortSignal.timeout(10000)});
  assert.equal(response.status,200,path);
  return response.json();
}
const [day,chart,score,f10,top200] = await Promise.all([get(dayPath),get(chartPath),get(scorePath),get(f10Path(positive.symbol)),get(top200Path)]);
const gap = gapSymbol ? await get(f10Path(gapSymbol)) : null;
const company = fixture.mode==='company-research' ? await get(companyPath(positive.symbol)) : null;
const companyForFault = options['exercise-regressions']&&fixture.mode!=='company-research' ? await get(companyPath(positive.symbol)) : null;
assert.ok(day.formula_groups && day.source_date===sourceDate && day.observation_date===observationDate);
assert.ok(sha(day.generation)&&sha(day.input_sha256)&&sha(day.numeric_manifest?.sha256));
for (const symbol of [positive.symbol,...(gapSymbol?[gapSymbol]:[]),...(fixture.companyCases??[]).map(item=>item.symbol)]) assert.ok(day.rows.some(row=>row.symbol===symbol),symbol);
for (const value of [day,chart,score,f10,top200,company,gap].filter(Boolean)) {
  for (const [key,expected] of Object.entries(flags)) assert.equal(value[key],expected,key);
  assert.equal(value.generation??value.source_generation,day.generation);
  assert.equal(value.input_sha256,day.input_sha256);
}
for (const value of [chart,score,f10,company].filter(Boolean)) assert.equal(value.symbol,positive.symbol);
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
for (const [name,value] of Object.entries(positive.lines??{})) {
  const point=chart.original_marks.lines?.[name]?.at(-1);
  assert.deepEqual(point,{trade_date:dayCode,y:value},`API has no exact ${name} point`);
}
assert.equal(score.status,'MATERIALIZED');
assert.equal(score.row?.hold_score?.kb_hold_score,positive.score);
assert.equal(f10.data_date,dayCode);
assert.equal(top200.schema,'V4_A_SHARE_TOP200_V1');
assert.equal(top200.data_date,dayCode);
assert.equal(top200.status,'PARTIAL_DESCRIPTIVE');
assert.equal(top200.top200_count,200);
assert.equal(top200.top200?.length,200);
assert.deepEqual(top200.numeric_manifest,day.numeric_manifest);
if (fixture.mode==='company-research') {
  assert.equal(f10.status,'NOT_MATERIALIZED');
  assert.equal(f10.symbol,positive.symbol);
  assert.equal(company.company_scope_status,'FORMULA_ROSTER_EXACT_MATCH');
  assert.equal(company.source_date,sourceDate);
  assert.equal(company.observation_date,observationDate);
  assert.deepEqual(company.numeric_manifest,day.numeric_manifest);
  const received=company.received_materials;
  assert.equal(received.business_reported?.value,positive.company[0].replace('研究回传主营：',''));
  assert.equal(received.received_fundamentals?.status,'PARTIAL');
  assert.equal(received.formula_group_scope?.candidate_count,day.rows.length);
  assert.equal(received.received_batch_summary?.package_id,'V4_A_FORMULA_D20261119_O20261120_CHAT_RESEARCH_V2');
  assert.ok(positive.financial.every(value=>typeof value==='string'));
} else {
  assert.equal(f10.status,'OBSERVED');
  assert.ok(sha(f10.receipt?.sha256)&&sha(f10.stock_ref?.sha256));
}
if (gap) {
  assert.equal(gap.symbol,gapSymbol);
  assert.equal(gap.data_date,dayCode);
  assert.equal(gap.status,'CANNOT_CONFIRM_SOURCE_GAP');
  assert.ok(sha(gap.receipt?.sha256)&&!gap.f10);
}

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
      window.__linePaints=[];
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
      const nativeStroke=CanvasRenderingContext2D.prototype.stroke;
      CanvasRenderingContext2D.prototype.stroke=function(...args){
        if(this.canvas.closest('#formulaDailyChart')?.dataset.symbol)window.__linePaints.push(String(this.strokeStyle).toLowerCase());
        return nativeStroke.apply(this,args);
      };
    },{fault,marker:positive.marker});
    if (fault==='omit-score') await page.route(requestUrl=>requestUrl.pathname===scorePath,route=>
      route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({...score,status:'UNKNOWN',reason:'SYMBOL_NOT_MATERIALIZED_FOR_DATE',row:null})}));
    if (fault==='company-instead-of-f10') await page.route(requestUrl=>requestUrl.pathname===f10Path(positive.symbol),async route=>{
      await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(companyForFault)});
    });
    async function expectView(code, condition, args) {
      try { await page.waitForFunction(condition,args,{timeout:15000}); }
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
      if (positive.lines) {
        for (const color of ['#ffffff','#fbcd2d']) {
          await page.waitForFunction(color=>window.__linePaints.includes(color),color,{timeout:10000});
        }
        await expectView('ORIGINAL_LINE_VALUES_NOT_RENDERED',({lines})=>{
          const text=document.getElementById('formulaDailyChart')?.innerText??'';
          return Object.entries(lines).every(([name,value])=>text.includes(`${name} ${value}`));
        },{lines:positive.lines});
      }
      await expectView('EXACT_SCORE_NOT_RENDERED',({symbol,sourceDate,score})=>{
        const get=id=>document.getElementById(id);
        const card=get('kbSingleResearch');
        return card?.getBoundingClientRect().height>0&&get('stockCode')?.textContent===symbol&&
          get('kbSingleCode')?.textContent===symbol&&get('kbSingleStatus')?.innerText.includes(sourceDate)&&
          get('kbSingleScore')?.innerText.includes(`${score}/5`);
      },{symbol:positive.symbol,sourceDate,score:positive.score});
      await expectView(fixture.mode==='company-research'?'COMPANY_RESEARCH_NOT_RENDERED':'EXACT_F10_NOT_RENDERED',({symbol,company,financial})=>{
        const a=document.getElementById('formulaCompanySummary'),b=document.getElementById('formulaCompanyMetrics');
        return a?.getBoundingClientRect().height>0&&b?.getBoundingClientRect().height>0&&a.dataset.companySymbol===symbol&&b.dataset.companySymbol===symbol&&
          company.every(value=>a.innerText.includes(value))&&financial.every(value=>b.innerText.includes(value));
      },positive);
      for (const path of [chartPath,scorePath,f10Path(positive.symbol),top200Path,...(company?[companyPath(positive.symbol)]:[])]) assert.ok(reads.includes(path),`Missing browser response ${path}`);
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
      if (company) {
        for (const item of fixture.companyCases??[]) {
          const path=companyPath(item.symbol),value=await get(path);
          assert.equal(value.symbol,item.symbol);
          assert.equal(value.generation,day.generation);
          assert.equal(value.input_sha256,day.input_sha256);
          assert.equal(value.company_scope_status,'FORMULA_ROSTER_EXACT_MATCH');
          assert.equal(value.received_materials?.business_reported?.value,item.business);
          assert.equal(value.received_materials?.received_fundamentals?.status,'PARTIAL');
          await page.locator('#query').fill(item.symbol);
          await page.locator(`#stockList button[data-symbol="${item.symbol}"]`).click();
          await expectView('COMPANY_RESEARCH_SYMBOL_NOT_UPDATED',({symbol,business})=>{
            const summary=document.getElementById('formulaCompanySummary'),metrics=document.getElementById('formulaCompanyMetrics');
            return document.getElementById('stockCode')?.textContent===symbol&&summary?.dataset.companySymbol===symbol&&
              metrics?.dataset.companySymbol===symbol&&summary.innerText.includes(`研究回传主营：${business}`)&&
              summary.innerText.includes('PARTIAL')&&metrics.innerText.includes('待核');
          },item);
          assert.ok(reads.includes(path),`Missing company research response ${path}`);
        }
      }
      if (gapSymbol) {
        await page.locator('#query').fill(gapSymbol);
        await expectView('F10_GAP_NOT_RENDERED',({symbol,oldRevenue})=>{
          const get=id=>document.getElementById(id),company=get('formulaCompanySummary'),metrics=get('formulaCompanyMetrics');
          return get('stockCode')?.textContent===symbol&&company?.getBoundingClientRect().height>0&&metrics?.getBoundingClientRect().height>0&&
            company.dataset.companySymbol===symbol&&metrics.dataset.companySymbol===symbol&&company.innerText.includes('本股缺少可用快照')&&
            metrics.innerText.includes('本日 F10 财务与股东资料待核')&&oldRevenue.every(value=>!metrics.innerText.includes(value));
        },{symbol:gapSymbol,oldRevenue:positive.financial});
        assert.ok(reads.includes(f10Path(gapSymbol)));
      }
      await page.locator('#query').fill('');
      await page.locator('#groupFilters button[data-group="top200"]').click();
      await expectView('TOP200_GROUP_NOT_RENDERED',()=>{
        const button=document.querySelector('#groupFilters button[data-group="top200"]');
        const rows=document.querySelectorAll('#stockList button[data-symbol]');
        return button?.innerText.includes('Top200 200')&&document.getElementById('listCount')?.innerText.includes('Top200 200只')&&rows.length>0;
      },{});
      assert.deepEqual(errors,[]);
    } finally { await page.close(); }
  }
  await check('none');
  const caught=[];
  if (options['exercise-regressions']) {
    const controls=[['omit-chart-paint','ORIGINAL_MARK_NOT_PAINTED'],['omit-score','EXACT_SCORE_NOT_RENDERED']];
    if (fixture.mode!=='company-research') controls.push(['company-instead-of-f10','EXACT_F10_NOT_RENDERED']);
    for (const [fault,code] of controls) {
      await assert.rejects(()=>check(fault),error=>error.code===code,`${fault} must fail for its own reason`);
      caught.push(code);
    }
  }
  console.log(JSON.stringify({status:'PASS_FORMULA_WORKBENCH_BROWSER',base:base.origin,sourceDate,observationDate,generation:day.generation,
    input_sha256:day.input_sha256,marker:positive.marker,score:positive.score,observed:positive.symbol,gap:gapSymbol,
    company_research_checked:Boolean(company),top200_count:top200.top200_count,white_yellow_lines_checked:Boolean(positive.lines),
    f10_completion_checked:Boolean(completion),negative_controls:caught}));
} finally { await browser.close(); }
