import test from "node:test";
import assert from "node:assert/strict";
import * as data from "./data.js";

const pool = (rows = [], extra = {}) => ({pool_id:"research", market:"A", status:"READY", pool_size:rows.length, rows, ...extra});
const page = (pools, extra = {}) => ({trade_date:"20261113", market_totals:{A:1,HK:0}, input_fingerprint:"snapshot-1", source_digests:{research:"sha-1"}, pagination:{offset:0,limit:300,next_offset:null,has_more:false}, pools, ...extra});
const row = {symbol:"000159.SZ",signal_date:"20261112",pool_rank:1,pool_score:0,source_trace:"原判定",source_last_bar_time:"2026-11-12T15:00:00+08:00"};

test("a verified zero market count is complete, an absent denominator stays unknown", () => {
  assert.equal(data.mergePoolPages([page([pool([row])])]).complete,true);
  const unknown=data.mergePoolPages([page([pool([row])],{market_totals:{}})]);
  assert.equal(unknown.complete,false);
  assert.equal(unknown.expected.A,null);
});
test("source date comes from signal evidence, never from pool observation date", () => {
  const result=data.mergePoolPages([page([pool([row],{trade_date:"20261113"})])]);
  assert.equal(result.pools[0].sourceDate,"20261112");
  assert.equal(result.rows[0].sources[0].sourceDate,"20261112");
  assert.equal(result.rows[0].sources[0].score,0);
  assert.equal(result.rows[0].sources[0].reason,"原判定");
  assert.equal(result.rows[0].sources[0].quoteAsOf,"2026-11-12T15:00:00+08:00");
  assert.equal(result.inputSha256,"snapshot-1");
  assert.equal(data.mergePoolPages([page([pool([{symbol:"000159.SZ"}],{trade_date:"20261113"})])]).rows[0].sources[0].sourceDate,null);
});
test("pagination refuses an input revision change even when the date and counts match", () => {
  const first=page([pool([row])],{pagination:{offset:0,limit:300,next_offset:300,has_more:true}});
  const last=page([pool([])],{input_fingerprint:"snapshot-2",pagination:{offset:300,limit:300,next_offset:null,has_more:false}});
  assert.throws(()=>data.mergePoolPages([first,last]),/版本|身份|fingerprint/);
});
test("a page starting after zero cannot be certified complete", () => {
  const result=data.mergePoolPages([page([pool([row])],{pagination:{offset:300,limit:300,has_more:false}})]);
  assert.equal(result.complete,false);
});
test("declared market and security namespace conflicts are isolated", () => {
  const result=data.mergePoolPages([page([pool([row,{symbol:"HK.00159",market:"A"}])])]);
  assert.equal(result.rows.length,1);
  assert.equal(result.isolated.length,1);
  assert.equal(result.complete,false);
  assert.equal(data.securityIdentity("HK","700.HK"),"HK:00700");
});
test("a malformed optional pool cannot erase independent valid source rows",()=>{
  const result=data.mergePoolPages([page([pool([row]),{pool_id:'bad_optional',market:'A',status:'FAILED',pool_size:1,rows:{bad:'shape'}},null])]);
  assert.equal(result.rows.length,1);assert.equal(result.rows[0].identity,'A:000159');
  assert.equal(result.complete,false);assert.equal(result.isolated.length,2);
  assert.equal(result.pools.find(p=>p.poolId==='bad_optional').status,'INVALID_SOURCE_SHAPE');
});
test("losing an overlapping membership is detected even when unique counts still match",()=>{
  const result=data.mergePoolPages([page([pool([row]),pool([],{pool_id:"review",pool_size:1})])]);
  assert.equal(result.counts.A,1);
  assert.equal(result.complete,false);
  assert.match(result.completenessReason,/来源关系/);
  assert.equal(data.apiSymbol("A","A.920670"),"920670.BJ");
});
test("Hong Kong uses the registered owner and pins the selected run for stock reads",async()=>{
  const urls=[];
  const fetcher=async url=>{
    urls.push(url);const u=new URL(url,"http://test");
    if(u.pathname.includes("/days/"))return new Response(JSON.stringify({schema_version:"v4.manager_workbench.v1",state:"PARTIAL",data:{snapshot:{context:{market:"HK_CONNECT",target_date:"20261113"},run_id:"run-1"}},gaps:[]}));
    assert.equal(u.pathname,"/api/v4/manager-workbench/stocks/HK.02659");
    assert.equal(u.searchParams.get("run_id"),"run-1");
    return new Response(JSON.stringify({schema_version:"v4.manager_workbench.v1",state:"READY",data:{plan_run_id:"run-1",stock:{market:"HK_CONNECT",symbol:"HK.02659",name:"样例港股",risks:["材料待核"]}},gaps:[]}));
  };
  const result=await data.loadHkWorkbench({symbol:"02659.HK",date:"20261113"},fetcher);
  assert.equal(result.stock.symbol,"HK.02659");assert.equal(urls.length,2);
});
test("Hong Kong review validates the original target_date and plan_run_id fields",async()=>{
  assert.equal(typeof data.loadHkReview,'function');
  const payload={schema_version:'v4.manager_workbench.v1',state:'READY',data:{target_date:'20261113',plan_run_id:'run-1',ranking_date:'20261113',top20_rows:[{symbol:'HK.02659'}]}};
  const fetcher=async url=>{
    const u=new URL(url,'http://test');
    assert.equal(u.pathname,'/api/v4/manager-workbench/reviews/20261113');
    assert.equal(u.searchParams.get('plan_run_id'),'run-1');
    return new Response(JSON.stringify(payload));
  };
  assert.equal((await data.loadHkReview({date:'20261113',planRunId:'run-1'},fetcher)).data.plan_run_id,'run-1');
  for(const patch of [{target_date:'20261112'},{plan_run_id:'run-old'},{ranking_date:'20261112'}]){
    await assert.rejects(()=>data.loadHkReview({date:'20261113',planRunId:'run-1'},async()=>new Response(JSON.stringify({...payload,data:{...payload.data,...patch}}))),/日期|批次/);
  }
  const missing=await data.loadHkReview({date:'20261113',planRunId:'run-1'},async()=>new Response(JSON.stringify({schema_version:'v4.manager_workbench.v1',state:'NOT_RUN',data:null,gaps:['SAME_DATE_CLOSE_INPUT_UNAVAILABLE']})));
  assert.equal(missing.state,'NOT_RUN');assert.equal(missing.data,null);
});
test("a later page failure preserves already read candidates and declares incomplete",async()=>{
  let calls=0;
  const result=await data.fetchAllPreselection("20261113",async()=>++calls===1
    ?new Response(JSON.stringify(page([pool([row])],{pagination:{offset:0,limit:300,next_offset:300,has_more:true}})))
    :new Response("unavailable",{status:503}));
  assert.equal(result.rows.length,1);
  assert.equal(result.complete,false);
  assert.match(result.completenessReason,/503/);
});
test("a later network or JSON failure preserves the verified earlier page",async()=>{
  for(const failure of ['network','json']){
    let calls=0;
    const result=await data.fetchAllPreselection("20261113",async()=>{
      if(++calls===1)return new Response(JSON.stringify(page([pool([row])],{pagination:{offset:0,limit:300,next_offset:300,has_more:true}})));
      if(failure==='network')throw new TypeError('connection lost');
      return new Response('{');
    });
    assert.equal(result.rows.length,1);
    assert.equal(result.complete,false);
    assert.match(result.completenessReason,/后续候选页/);
  }
});

test("a malformed later body keeps the earlier candidates without claiming completeness", async () => {
  const first = page([pool([row])], {
    pagination: {offset: 0, limit: 300, next_offset: 300, has_more: true},
  });
  const last = page({bad: "shape"}, {
    pagination: {offset: 300, limit: 300, has_more: false},
  });
  for (const malformed of [last, null]) {
    let calls = 0;
    const result = await data.fetchAllPreselection("20261113", async () =>
      new Response(JSON.stringify(++calls === 1 ? first : malformed)));
    assert.equal(result.rows.length, 1);
    assert.equal(result.membershipCount, 1);
    assert.equal(result.complete, false);
  }
});

test("a source pool identity conflict removes only that pool across both pages", () => {
  const independent = pool([row], {pool_id: "independent"});
  const first = page([independent, pool([row], {source_sha256: "old"})], {
    pagination: {offset: 0, limit: 300, next_offset: 300, has_more: true},
  });
  const last = page([pool([{symbol: "000001.SZ"}], {source_sha256: "new"})], {
    pagination: {offset: 300, limit: 300, has_more: false},
  });
  const result = data.mergePoolPages([first, last]);
  assert.equal(result.complete, false);
  assert.equal(result.membershipCount, 1);
  assert.equal(result.rows[0].identity, "A:000159");
  assert.deepEqual(result.rows[0].sources.map(source => source.poolId), ["independent"]);
  assert.equal(result.pools.find(value => value.poolId === "research").status, "CONFLICT");
  assert.deepEqual(result.isolated, [{poolId: "research", reason: "SOURCE_POOL_IDENTITY_CONFLICT"}]);
});

const researchPayloads = {
  "daily-product":{status:"READY",data_date:"20261112",source_generation:"g1",source_identity:{input_sha256:'input-1'},manifest:{sha256:'manifest-1'},row:{symbol:"000159.SZ",groups:"nav_pullback",statistics:{groups:[]}}},
  "original-chart":{status:"READY",symbol:"000159.SZ",data_date:"20261112",source_generation:"g1",input_sha256:'input-1',product_manifest:{sha256:'manifest-1'},assets:{html:{url:"/api/v4/research/a-share/original-chart/html?date=20261112"}}},
  "company-materials":{status:"NOT_MATERIALIZED",symbol:"000159.SZ",data_date:"20261112",missing_reason:"NOT_IMPORTED"},
};
const fetchResearch = (overrides={}) => async url => {
  const u=new URL(url,"http://test");
  assert.equal(u.searchParams.get("symbol"),"000159.SZ");
  const key=u.pathname.split("/").at(-1);
  const value=overrides[key]??researchPayloads[key];
  if(value instanceof Response)return value;
  assert.ok(value,`unexpected endpoint ${key}`);
  return new Response(JSON.stringify(value));
};
test("company endpoint failure leaves the verified numeric product and chart usable",async()=>{
  const bundle=await data.loadResearchBundle({market:"A",symbol:"000159",date:"20261112"},fetchResearch({"company-materials":new Response("down",{status:503})}));
  assert.equal(bundle.product.status,"READY");
  assert.equal(bundle.chart.status,"READY");
  assert.equal(bundle.company.status,"FAILED");
  assert.equal(bundle.status,"PARTIAL");
});
test("wrong stock or generation evidence cannot join a valid daily product",async()=>{
  const bundle=await data.loadResearchBundle({market:"A",symbol:"000159.SZ",date:"20261112"},fetchResearch({"original-chart":{...researchPayloads["original-chart"],symbol:"000001.SZ"}}));
  assert.equal(bundle.product.status,"READY");
  assert.equal(bundle.chart.status,"CONFLICT");
  const other=await data.loadResearchBundle({market:"A",symbol:"000159.SZ",date:"20261112"},fetchResearch({"original-chart":{...researchPayloads["original-chart"],source_generation:"other"}}));
  assert.equal(other.chart.status,"CONFLICT");
});
test("malformed optional evidence identities are isolated without losing numeric data",async()=>{
  const bundle=await data.loadResearchBundle({market:"A",symbol:"000159.SZ",date:"20261112"},fetchResearch({"original-chart":{...researchPayloads["original-chart"],symbol:"HK.00159"}}));
  assert.equal(bundle.product.status,"READY");
  assert.equal(bundle.chart.status,"CONFLICT");
  assert.equal(bundle.company.status,"NOT_MATERIALIZED");
});
test("bare READY without source identity stays unconfirmed instead of joining the numeric generation",async()=>{
  for(const missing of ['source_generation','input_sha256','product_manifest']){
    const unbound={...researchPayloads['original-chart']};delete unbound[missing];
    const bundle=await data.loadResearchBundle({market:'A',symbol:'000159',date:'20261112'},fetchResearch({'original-chart':unbound}));
    assert.equal(bundle.product.status,'READY');assert.equal(bundle.chart.status,'CANNOT_CONFIRM');
    assert.equal(bundle.chart.original_status,'READY');assert.equal(bundle.chart.assets,undefined);
  }
  const unboundProduct={...researchPayloads['daily-product']};delete unboundProduct.source_identity;
  const value=await data.loadDailyProduct({symbol:'000159',date:'20261112'},fetchResearch({'daily-product':unboundProduct}));
  assert.equal(value.status,'CANNOT_CONFIRM');assert.equal(value.row,undefined);
});
test("malformed or unbound received materials stay isolated from numeric and chart evidence",async()=>{
  const incomplete={status:'PARTIAL_RECEIVED',source_generation:'g1',input_sha256:'input-1',numeric_manifest:{sha256:'manifest-1'},materials:['unbound']};
  for(const company of [new Response('null'),incomplete]){
    const bundle=await data.loadResearchBundle({market:'A',symbol:'000159',date:'20261112'},fetchResearch({'company-materials':company}));
    assert.equal(bundle.product.status,'READY');assert.equal(bundle.chart.status,'READY');
    assert.ok(['CANNOT_CONFIRM','CONFLICT'].includes(bundle.company.status));assert.equal(bundle.company.materials,undefined);
  }
  const alternate={...researchPayloads['original-chart'],manifest:{sha256:'wrong'}};delete alternate.product_manifest;
  const value=await data.loadResearchBundle({market:'A',symbol:'000159',date:'20261112'},fetchResearch({'original-chart':alternate}));
  assert.equal(value.chart.status,'CONFLICT');
});

test("received company materials need a ready matching numeric product while the original chart stays available", async () => {
  const company = {
    status: "PARTIAL_RECEIVED", symbol: "000159.SZ", data_date: "20261112",
    source_generation: "g1", input_sha256: "input-1", numeric_manifest: {sha256: "manifest-1"},
    materials: {report: "bound report"},
  };
  const context = {market: "A", symbol: "000159", date: "20261112"};
  const bound = await data.loadResearchBundle(context, fetchResearch({"company-materials": company}));
  assert.deepEqual(bound.company.materials, company.materials);
  const unbound = await data.loadResearchBundle(context, fetchResearch({
    "daily-product": {status: "CANNOT_CONFIRM"},
    "company-materials": {...company, source_generation: "older", input_sha256: "old-input",
      numeric_manifest: {sha256: "old-manifest"}, materials: {report: "unbound report"}},
  }));
  assert.equal(unbound.product.status, "CANNOT_CONFIRM");
  assert.equal(unbound.chart.status, "READY");
  assert.equal(unbound.company.status, "CANNOT_CONFIRM");
  assert.equal(unbound.company.materials, undefined);
});

test("only the numeric owner's canonical manifest and input identity can bind company materials", async () => {
  const product = researchPayloads["daily-product"];
  const company = {
    status: "PARTIAL_RECEIVED", symbol: "000159.SZ", data_date: "20261112",
    source_generation: "g1", input_sha256: "input-1", numeric_manifest: {sha256: "old-manifest"},
    materials: {report: "must remain hidden"},
  };
  const context = {market: "A", symbol: "000159", date: "20261112"};
  const invalidProducts = [
    {...product, manifest: undefined, product_manifest: product.manifest},
    {...product, manifest: undefined, numeric_manifest: product.manifest},
    {...product, source_identity: undefined, input_sha256: "input-1"},
  ];
  for (const invalid of invalidProducts) {
    const bundle = await data.loadResearchBundle(context, fetchResearch({
      "daily-product": invalid, "company-materials": company,
    }));
    assert.equal(bundle.product.status, "CANNOT_CONFIRM");
    assert.equal(bundle.product.row, undefined);
    assert.equal(bundle.chart.status, "READY");
    assert.equal(bundle.company.materials, undefined);
  }
});

test("contradictory input SHA aliases cannot bind numeric or company evidence", async () => {
  const product = researchPayloads["daily-product"];
  const context = {market: "A", symbol: "000159", date: "20261112"};
  const badProduct = await data.loadDailyProduct(context, fetchResearch({
    "daily-product": {...product, input_sha256: "old-input"},
  }));
  assert.equal(badProduct.status, "CONFLICT");
  assert.equal(badProduct.row, undefined);

  const company = {
    status: "PARTIAL_RECEIVED", symbol: "000159.SZ", data_date: "20261112",
    source_generation: "g1", input_sha256: "input-1", source_identity: {input_sha256: "old-input"},
    numeric_manifest: {sha256: "manifest-1"}, materials: {report: "must remain hidden"},
  };
  const bundle = await data.loadResearchBundle(context, fetchResearch({"company-materials": company}));
  assert.equal(bundle.product.status, "READY");
  assert.equal(bundle.chart.status, "READY");
  assert.equal(bundle.company.status, "CONFLICT");
  assert.equal(bundle.company.materials, undefined);
});
test("historical D+2 wins do not mature the latest pullback signal",()=>{
  assert.equal(typeof data.maturityGroups,"function");
  const groups=data.maturityGroups({row:{statistics:{groups:[{group_id:"nav_pullback",horizons:{d2:{total:2,valid:1,not_matured:1,cases:[{event_date:"2026-11-11",target_date:"2026-11-13",status:"not_matured",return_pct:null},{event_date:"2026-11-06",target_date:"2026-11-10",status:"negative",return_pct:-1.47}]},d5:{total:2,valid:0,not_matured:2}}}]}}});
  assert.equal(groups[0].groupId,"nav_pullback");
  assert.equal(groups[0].d2.latest.status,"not_matured");
  assert.equal(groups[0].d2.latest.return_pct,null);
  assert.equal(groups[0].d2.total,2);
});
test("status classification never marks NOT_READY, partial, stale or missing as success",()=>{
  assert.equal(typeof data.statusKind,"function");
  for(const s of ["NOT_READY","CANNOT_CONFIRM","FAILED","NOT_MATERIALIZED"]) assert.notEqual(data.statusKind(s),"good");
  for(const s of ["READY_DATA_PARTIAL","STALE_READY","NOT_MATURED"]) assert.equal(data.statusKind(s),"warn");
  assert.equal(data.statusKind("READY_EMPTY"),"good");
});
