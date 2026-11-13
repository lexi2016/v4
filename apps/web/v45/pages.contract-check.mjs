import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {JSDOM} from "jsdom";
import {gunzipSync} from "node:zlib";

const waitFor=async predicate=>{for(let i=0;i<200;i++){if(predicate())return;await new Promise(r=>setImmediate(r));}assert.fail("page did not settle");};
async function mount(name,query,fetcher,action){
  const html=readFileSync(new URL(`./${name}/index.html`,import.meta.url),"utf8");
  const dom=new JSDOM(html,{url:`http://test/v45/${name}/?${query}`});
  const saved={};
  for(const key of ["window","document","location","history","HTMLElement","CustomEvent"]){saved[key]=globalThis[key];globalThis[key]=dom.window[key];}
  saved.fetch=globalThis.fetch;globalThis.fetch=fetcher;
  try{await import(`./${name}/main.js?test=${Date.now()}-${name}`);await action(dom.window);}
  finally{dom.window.close();for(const [key,value] of Object.entries(saved)){if(value===undefined)delete globalThis[key];else globalThis[key]=value;}}
}
const json=x=>new Response(JSON.stringify(x));
const poolPayload={trade_date:"20261113",input_fingerprint:"sample",source_digests:{},data_status:"PARTIAL_WITH_ROWS",market_totals:{A:1,HK:1},pagination:{offset:0,limit:300,has_more:false},pools:[
  {pool_id:"a_review",market:"A",status:"PARTIAL",pool_size:1,rows:[{symbol:"A.000159",stock_name:"样例A",signal_date:"20261112",pool_rank:1,pool_score:0,source_trace:"回踩待核"}]},
  {pool_id:"hkconnect_d1_top100",market:"HK",status:"STRICT_0_2_READY",pool_size:1,rows:[{symbol:"HK.02659",stock_name:"样例HK",signal_date:"20261112",pool_rank:1,pool_score:2}]}
]};
const product={status:"READY",data_date:"20261112",source_generation:"g1",row:{symbol:"000159.SZ",display_name:"样例A",groups:"nav_pullback",latest_new_anchor:"20261105",statistics:{groups:[{group_id:"nav_pullback",horizons:{d2:{total:2,valid:1,not_matured:1,missing_price:0,cases:[{event_date:"2026-11-12",target_date:"2026-11-16",status:"not_matured",return_pct:null}]},d5:{total:2,valid:0,not_matured:2,missing_price:0,cases:[]}}}]}}};
const chart={status:"READY",symbol:"000159.SZ",data_date:"20261112",source_generation:"g1",rows:20,assets:{html:{url:"/api/v4/research/a-share/original-chart/html?date=20261112&symbol=000159.SZ&generation=g1",sha256:"a".repeat(64)}}};
Object.assign(product,{source_identity:{input_sha256:'input-1'},manifest:{sha256:'manifest-1'}});
Object.assign(chart,{input_sha256:'input-1',product_manifest:{sha256:'manifest-1'}});
async function fetcher(url){
  const u=new URL(url,"http://test");
  if(u.pathname==="/v45/shared/formula-comparison.v1.bin")return new Response(readFileSync(new URL("../public/v45/shared/formula-comparison.v1.bin",import.meta.url)));
  if(u.pathname.endsWith("/preselection-pools"))return json(poolPayload);
  if(u.pathname.endsWith("/daily-product"))return json(product);
  if(u.pathname.endsWith("/original-chart"))return json(chart);
  if(u.pathname.endsWith("/company-materials"))return new Response("offline",{status:503});
  if(u.pathname.endsWith("/event-cases"))return json({status:"READY",symbol:"000159.SZ",data_date:"20261112",source_generation:"g1",source_identity:{input_sha256:'input-1'},numeric_manifest:{sha256:'manifest-1'},group:u.searchParams.get("group"),horizon:u.searchParams.get("horizon"),total:2,valid:0,not_matured:2,cases:[]});
  if(u.pathname.endsWith("/review"))return json({trade_date:"20261113",reference_snapshot:true,market_reviews:{A:{trade_date:"20261113",headline:"A股真实字段复盘",observation_pool:[{stock_code:"000159",stock_name:"样例A",reason:"观察"}],model_review:{status:"PARTIAL"},close_chain:{status:"PARTIAL",nodes:[]},quality_gate:[]},HK:{trade_date:"20261113",status:"PARTIAL",model_selection_review:{status:"PARTIAL",close_top20:[],models:{},stage_union:{}}}}});
  throw new Error("unexpected read "+url);
}
test("selection source filter preserves market/date/search in URL and same-stock navigation",async()=>{
  await mount("selection","date=20261113&market=A&search=000159",fetcher,async w=>{
    await waitFor(()=>document.querySelector("#candidates a"));
    assert.ok(document.querySelector("#source"));
    assert.match(document.querySelector("#candidates").textContent,/回踩待核/);
    const link=new URL(document.querySelector("#candidates a").href);
    assert.equal(link.searchParams.get("observationDate"),"20261113");
    assert.equal(link.searchParams.get("date"),"20261112");
    document.querySelector("#source").value="a_review";
    document.querySelector("#source").dispatchEvent(new w.Event("change"));
    assert.equal(new URLSearchParams(location.search).get("source"),"a_review");
    assert.equal(document.querySelectorAll("#candidates tr").length,1);
    await waitFor(()=>document.querySelector("#formula-rows details"));
  });
});
test("selection carries the selected source date when memberships have different dates",async()=>{
  const mixed=structuredClone(poolPayload);
  mixed.pools[0].rows[0].signal_date='20261111';
  mixed.pools.push({...structuredClone(poolPayload.pools[0]),pool_id:'newer_source'});
  await mount('selection','date=20261113&market=A&source=newer_source',url=>String(url).includes('preselection-pools')?json(mixed):fetcher(url),async()=>{
    await waitFor(()=>document.querySelector('#candidates a'));
    const link=new URL(document.querySelector('#candidates a').href);
    assert.equal(link.searchParams.get('date'),'20261112');
    await waitFor(()=>document.querySelector('#formula-rows details'));
  });
});
test("slower old selection requests cannot replace the newer selected day",async()=>{
  let releaseOld;
  const old=new Promise(resolve=>{releaseOld=resolve;});
  const newer={...structuredClone(poolPayload),trade_date:'20261114'};
  await mount('selection','date=20261113',url=>{
    const u=new URL(url,'http://test');
    if(u.pathname.includes('preselection-pools'))return u.searchParams.get('date')==='20261113'?old:json(newer);
    return fetcher(url);
  },async w=>{
    document.querySelector('#date').value='2026-11-14';
    document.querySelector('#selection-form').dispatchEvent(new w.Event('submit',{cancelable:true}));
    await waitFor(()=>document.querySelector('#status').textContent.includes('20261114'));
    releaseOld(json(poolPayload));
    await new Promise(resolve=>setImmediate(resolve));
    assert.match(document.querySelector('#status').textContent,/20261114/);
    assert.equal(new URLSearchParams(location.search).get('date'),'20261114');
  });
});
test("research preserves usable siblings, original chart and latest unripe pullback with correct return date",async()=>{
  await mount("research","date=20261112&observationDate=20261113&market=A&symbol=000159.SZ",fetcher,async()=>{
    await waitFor(()=>document.querySelector("#evidence").textContent.includes("量价"));
    assert.match(document.querySelector("#evidence").textContent,/nav_pullback/);
    assert.match(document.querySelector("#evidence").textContent,/not_matured|未成熟/);
    assert.match(document.querySelector("#evidence").textContent,/503/);
    assert.ok(document.querySelector('a[href^="/api/v4/research/a-share/original-chart/html"]'));
    assert.equal(new URL(document.querySelector("#selection-link").href).searchParams.get("date"),"20261113");
    assert.equal(new URL(document.querySelector("#review-link").href).searchParams.get("symbol"),"000159.SZ");
  });
});
test("review renders actual A envelope and auto-loads linked group without losing stock context",async()=>{
  await mount("review","date=20261113&sourceDate=20261112&market=A&symbol=000159.SZ&group=nav_pullback",fetcher,async()=>{
    await waitFor(()=>document.querySelector("#markets").textContent.includes("A股"));
    assert.match(document.querySelector("#markets").textContent,/A股真实字段复盘/);
    await waitFor(()=>document.querySelector("#maturity").textContent.includes("D+2"));
    assert.match(document.querySelector("#maturity").textContent,/未成熟/);
    const url=new URL(document.querySelector("#research-link").href);
    assert.equal(url.searchParams.get("symbol"),"000159.SZ");
    assert.equal(url.searchParams.get("date"),"20261112");
    assert.equal(url.searchParams.get("observationDate"),"20261113");
    await waitFor(()=>document.querySelector("#maturity").textContent.includes("历史事件与最新信号分别列出"));
  });
});
test("Hong Kong review releases old pins and links the accepted plan when moving between days",async()=>{
  const dayReads=[];
  const hkFetcher=async url=>{
    const u=new URL(url,'http://test'),p=u.pathname;
    if(p==='/api/v3/review')return json({trade_date:u.searchParams.get('date'),market_reviews:{}});
    if(p.includes('/days/')){
      const date=p.split('/').at(-1);dayReads.push({date,runId:u.searchParams.get('run_id')});
      const runId=u.searchParams.get('run_id') ?? `current-${date}`;
      return json({schema_version:'v4.manager_workbench.v1',state:'READY',data:{snapshot:{context:{market:'HK_CONNECT',target_date:date},run_id:runId}}});
    }
    if(p.includes('/stocks/'))return json({schema_version:'v4.manager_workbench.v1',state:'READY',data:{plan_run_id:u.searchParams.get('run_id'),stock:{market:'HK_CONNECT',symbol:'HK.02659'}}});
    if(p.includes('/reviews/'))return json({schema_version:'v4.manager_workbench.v1',state:'READY',data:{target_date:p.split('/').at(-1),plan_run_id:u.searchParams.get('plan_run_id'),mode:'NOT_EVALUATED',ranking_date:null,top20_rows:[],gaps:['COMPLETE_SAME_SCOPE_CLOSE_RANKING_NOT_VERIFIED']}});
    throw new Error('unexpected HK read '+url);
  };
  await mount('review','date=20261113&sourceDate=20261112&market=HK&symbol=HK.02659&runId=run-20261113',hkFetcher,async w=>{
    await waitFor(()=>document.querySelector('#maturity').textContent.includes('港股同批原工作台复盘'));
    assert.equal(dayReads[0].runId,'run-20261113');
    assert.equal(new URL(document.querySelector('#research-link').href).searchParams.get('runId'),'run-20261113');
    document.querySelector('#date').value='2026-11-14';
    document.querySelector('#review-form').dispatchEvent(new w.Event('submit',{cancelable:true}));
    await waitFor(()=>dayReads.length===2);
    assert.equal(dayReads[1].runId,null);
    await waitFor(()=>document.querySelector('#maturity').textContent.includes('current-20261114'));
    assert.match(document.querySelector('#maturity').textContent,/NOT_EVALUATED/);
    assert.equal(new URLSearchParams(location.search).get('runId'),'current-20261114');
    assert.equal(new URL(document.querySelector('#research-link').href).searchParams.get('runId'),'current-20261114');
    document.querySelector('#date').value='2026-11-13';
    document.querySelector('#review-form').dispatchEvent(new w.Event('submit',{cancelable:true}));
    await waitFor(()=>dayReads.length===3);
    assert.equal(dayReads[2].runId,null);
    await waitFor(()=>document.querySelector('#maturity').textContent.includes('current-20261113'));
    assert.equal(new URL(document.querySelector('#research-link').href).searchParams.get('runId'),'current-20261113');
  });
});

test("Hong Kong research keeps its linked observation day, then discards the pin after an explicit date change", async () => {
  const dayReads = [];
  const hkFetcher = async url => {
    const u = new URL(url, "http://test");
    if (u.pathname.includes("/days/")) {
      const date = u.pathname.split("/").at(-1);
      const runId = u.searchParams.get("run_id");
      dayReads.push({date, runId});
      return json({schema_version: "v4.manager_workbench.v1", state: "READY", data: {
        snapshot: {context: {market: "HK_CONNECT", target_date: date}, run_id: runId ?? `current-${date}`},
      }});
    }
    if (u.pathname.includes("/stocks/")) return json({
      schema_version: "v4.manager_workbench.v1", state: "READY", data: {
        plan_run_id: u.searchParams.get("run_id"), stock: {market: "HK_CONNECT", symbol: "HK.02659"},
      },
    });
    if (u.pathname.includes("/preselection-pools")) return json({...poolPayload, trade_date: u.searchParams.get("date")});
    throw new Error("unexpected HK read " + url);
  };
  await mount("research", "date=20261112&observationDate=20261113&market=HK&symbol=HK.02659&runId=original-20261113", hkFetcher, async w => {
    await waitFor(() => document.querySelector("#lineage").textContent.includes("20261113"));
    assert.deepEqual(dayReads[0], {date: "20261113", runId: "original-20261113"});
    const submitDate = (isoDate) => {
      document.querySelector("#date").value = isoDate;
      document.querySelector("#research-form").dispatchEvent(new w.Event("submit", {cancelable: true}));
    };
    submitDate("2026-11-14");
    await waitFor(() => document.querySelector("#lineage").textContent.includes("20261114"));
    assert.deepEqual(dayReads[1], {date: "20261114", runId: null});
    assert.equal(new URLSearchParams(location.search).get("runId"), "current-20261114");
    const review = new URL(document.querySelector("#review-link").href);
    assert.equal(review.searchParams.get("date"), "20261114");
    assert.equal(review.searchParams.get("runId"), "current-20261114");
    submitDate("2026-11-12");
    await waitFor(() => document.querySelector("#lineage").textContent.includes("20261112"));
    assert.deepEqual(dayReads[2], {date: "20261112", runId: null});
  });
});
