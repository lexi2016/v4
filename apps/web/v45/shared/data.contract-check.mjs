import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";
import { mergePoolPages, normaliseDate, securityIdentity, formulaComparisonFor, fetchFormulaComparisonRows } from "./data.js";

function page(offset, hasMore, pools, marketTotals={A:2,HK:1}) {
  return { trade_date:"20261112", data_status:"PARTIAL_WITH_ROWS", market_totals:marketTotals,
    pagination:{offset,limit:300,next_offset:hasMore?300:null,has_more:hasMore,complete:!hasMore}, pools };
}
test("security identity keeps A/HK namespaces separate and normalises source prefixes",()=>{
  assert.equal(securityIdentity("A","A.000159"),"A:000159");
  assert.equal(securityIdentity("A","000159.SZ"),"A:000159");
  assert.equal(securityIdentity("HK","HK.00700"),"HK:00700");
  assert.notEqual(securityIdentity("A","00001"),securityIdentity("HK","00001"));
});
test("multi-page merge deduplicates securities but preserves every source membership",()=>{
  const pages=[
    page(0,true,[
      {pool_id:"a_d1_premarket_pool",market:"A",status:"V192_CANDIDATE_READY",pool_size:1,rows:[{symbol:"A.000001",name:"平安银行",source_date:"20261111",rank:1,score:88,source_sha256:"a"}]},
      {pool_id:"a_d1_fupan_watchlist_pool",market:"A",status:"PARTIAL",pool_size:1,rows:[{symbol:"000001.SZ",name:"平安银行",source_date:"20261111",rank:3,score:77,source_sha256:"b"}]},
      {pool_id:"a_d1_stage7_fenshi_review_pool",market:"A",status:"CANNOT_CONFIRM",pool_size:0,rows:[],cannot_confirm:["STAGE7_MISSING"]}
    ]),
    page(300,false,[
      {pool_id:"a_share_research_recommendation_pool",market:"A",status:"READY",pool_size:1,rows:[{symbol:"A.000002",name:"万科A",source_date:"20261111",rank:2,score:70,source_sha256:"c"}]},
      {pool_id:"hkconnect_d1_top100",market:"HK",status:"STRICT_0_2_READY",pool_size:1,rows:[{symbol:"HK.00700",name:"腾讯控股",source_date:"20261111",rank:1,score:90,source_sha256:"d"}]}
    ])
  ];
  const result=mergePoolPages(pages);
  assert.equal(result.complete,true);
  assert.deepEqual(result.counts,{A:2,HK:1});
  assert.equal(result.rows.length,3);
  const pingan=result.rows.find(x=>x.identity==="A:000001");
  assert.equal(pingan.sources.length,2);
  assert.deepEqual(pingan.sources.map(x=>x.poolId).sort(),["a_d1_fupan_watchlist_pool","a_d1_premarket_pool"]);
  assert.equal(result.membershipCount,4);
  assert.equal(result.pools.find(x=>x.poolId==="a_d1_stage7_fenshi_review_pool").status,"CANNOT_CONFIRM");
});
test("a bad optional pool does not erase valid independent pools",()=>{
  const result=mergePoolPages([page(0,false,[
    {pool_id:"a_d1_premarket_pool",market:"A",status:"READY",pool_size:2,rows:[{symbol:"A.000001"},{symbol:"A.000002"}]},
    {pool_id:"a_d1_stage7_fenshi_review_pool",market:"A",status:"CANNOT_CONFIRM",pool_size:0,rows:[]},
    {pool_id:"hkconnect_d1_top100",market:"HK",status:"STRICT_0_2_READY",pool_size:1,rows:[{symbol:"HK.00700"}]}
  ])]);
  assert.equal(result.rows.length,3);
  assert.equal(result.complete,true);
});
test("pagination gaps and date conflicts cannot be declared complete",()=>{
  const first=page(0,true,[]);
  const last=page(600,false,[]);
  assert.equal(mergePoolPages([first,last]).complete,false);
  assert.throws(()=>mergePoolPages([first,{...last,trade_date:"20261113"}]),/日期不匹配/);
});
test("formula comparison is frozen, date-scoped and not inferred for HK",()=>{
  assert.deepEqual(formulaComparisonFor("20261113"),{
    sourceDate:"20261112",observationDate:"20261113",original:40,v192:10,common:1,originalOnly:39,v192Only:9,status:"FROZEN_COMPARISON"
  });
  assert.equal(formulaComparisonFor("20261114"),null);
  assert.equal(normaliseDate("2026-11-12"),"20261112");
  assert.throws(()=>normaliseDate("2026-02-30"),/日期无效/);
});

test("sanitised frozen formula comparison fixture retains exact per-stock evidence", async () => {
  const compressed = readFileSync(new URL("../../public/v45/shared/formula-comparison.v1.bin", import.meta.url));
  const fixture = JSON.parse(gunzipSync(compressed).toString("utf8"));
  assert.equal(fixture.schema_version,"v45.frozen_formula_comparison.v1");
  assert.equal(fixture.status,"FROZEN_SOURCE_DATA_NOT_RECALCULATED");
  assert.equal(fixture.records.length,118);
  const fetcher = async () => new Response(compressed,{status:200});
  const day12 = await fetchFormulaComparisonRows("20261112",fetcher);
  const day13 = await fetchFormulaComparisonRows("20261113",fetcher);
  assert.equal(day12.length,69);
  assert.equal(day13.length,49);
  assert.equal(day12.filter(x=>x.category==="仅原公式").length,44);
  assert.equal(day12.filter(x=>x.category==="仅v1.9.2").length,25);
  assert.equal(day13.filter(x=>x.category==="仅原公式").length,39);
  assert.equal(day13.filter(x=>x.category==="仅v1.9.2").length,9);
  assert.equal(day13.filter(x=>x.category==="共同入选").length,1);
  assert.ok(fixture.records.every(x=>/^[0-9a-f]{64}$/.test(x.source_checkpoint_sha256)));
  assert.ok(fixture.records.every(x=>!Object.keys(x).some(k=>/local_path|checkpoint_path/i.test(k))));
});
