'use strict';
/** Isolated, synthetic gate tests (not a browser/real Mac run). */
const {test} = require('node:test');
const assert = require('node:assert/strict');
if (!process.env.ANNOUNCEMENT_OWNER_DETAIL_JS || !process.env.ANNOUNCEMENT_SHARED_DAILY_JS)
  throw new Error('Compile both TypeScript sources and supply their absolute JS paths');
const {verifiedAnnouncementOwnerSelection} = require(process.env.ANNOUNCEMENT_OWNER_DETAIL_JS);
const {verifiedAnnouncementResearchResult} = require(process.env.ANNOUNCEMENT_SHARED_DAILY_JS);
const clone = obj => JSON.parse(JSON.stringify(obj));
const target='20261009', pub='2026-10-08', dates={plan_date:target,selection_date:target,announcement_date:'20261008'};
const H = 'a'.repeat(64), S = 'b'.repeat(64), O = 'c'.repeat(64), C = 'd'.repeat(64), R = 'e'.repeat(32), CR = 'f'.repeat(32), E='1'.repeat(64), J='2'.repeat(64);
const kinds=['SELECTED','CONDITIONAL_WATCH','NOT_SELECTED','NOT_ASSESSED'];
const stocks=kinds.map((status,i)=>({stock_code:`HK.${String(i+1).padStart(5,'0')}`,stock_name:`发行人${i+1}`,status,
  target_trade_date:target,publication_date:pub,evidence_run_id:R,product_sha256:H,selection_sha256:S,owner_import_receipt_sha256:O,
  selection_reasons: status==='SELECTED'||status==='CONDITIONAL_WATCH'?[{reason:'逐篇事件依据'}]:[],
  not_selected_reasons: status==='NOT_SELECTED'?[{reason:'本次不入选'}]:[],
  articles:[{disposition:status==='NOT_ASSESSED'?'NOT_ASSESSED':'SELECTED_EVENT', reason:'原始理由'}],risk_notes:[]}));
const research={schema_version:'v4.manager_research.announcement_research_result.v1',status:'RETROSPECTIVE_RESEARCH_ONLY',
  validation_status:'VERIFIED', owner:'ManagerResearchJobService.import_announcement_analysis',
  historical_pit_verified:false,natural_run_verified:false,consumed_at_cutoff:false,
  plan_cutoff:'2026-10-09T09:20:00+08:00',cutoff_status:'AFTER_CUTOFF',
  owner_available_at:'2026-10-09T09:21:00+08:00',latest_source_or_review_at:'2026-10-09T09:21:00+08:00',
  RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false,
  target_trade_date:target,publication_date:pub,product_sha256:H,selection_sha256:S,
  source_manifest_sha256:C,catalog_product_sha256:C,owner_import_receipt_sha256:O,handoff_manifest_sha256:E,
  evidence_run_id:R,catalog_run_id:CR,stock_count:4,
  selected_stock_count:1,conditional_watch_count:1,not_selected_stock_count:1,not_assessed_stock_count:1,
  stocks};
const receipt={status:'VERIFIED',owner:'ManagerResearchJobService.import_announcement_analysis',
  target_trade_date:target,publication_date:pub,sha256:O,product_sha256:H,source_manifest_sha256:C,
  evidence_run_id:R,handoff_manifest_sha256:E,agent_judgment_receipt_sha256:J};
const chain={status:'VERIFIED',validation_status:'VERIFIED',consumed:false,
  target_trade_date:target,publication_date:pub,owner_import_receipt_sha256:O,product_sha256:H,
  source_manifest_sha256:C,evidence_run_id:R,handoff_manifest_sha256:E,
  agent_judgment_receipt_sha256:J,selected_stock_count:1,conditional_watch_count:1,
  not_selected_stock_count:1,not_assessed_stock_count:1};
const detail={target_trade_date:target,publication_date:pub,owner_import_receipt:receipt,consumption_validation:chain,
  analysis:{status:'VERIFIED',product_sha256:H,source_manifest_sha256:C,
    stock_selection:{status:'VERIFIED',product_sha256:H,source_manifest_sha256:C,selection_sha256:S,
      source_binding:{target_trade_date:target,publication_date:pub},stock_count:4,
      selected_stock_count:1,conditional_watch_count:1,not_selected_stock_count:1,
      not_assessed_stock_count:1,stocks}}};
test('four classes bind to same product/run/SHA and correct public day',()=>{
  assert.equal(verifiedAnnouncementResearchResult(research,dates),true);
  assert.equal(verifiedAnnouncementOwnerSelection(detail).verified,true);
  assert.equal(verifiedAnnouncementOwnerSelection(detail).retrospective,true);
});
test('historical PIT claim is not admitted by display validator',()=>{
  const x=clone(research); x.historical_pit_verified=true;
  assert.equal(verifiedAnnouncementResearchResult(x,dates),false);
});
test('after-cutoff result never enters plan candidate rows',()=>{
  const x=clone(research);x.status='CONSUMED_AT_CUTOFF';x.consumed_at_cutoff=false;
  assert.equal(verifiedAnnouncementResearchResult(x,dates),false);
  x.consumed_at_cutoff=true;x.cutoff_status='SATISFIED';
  assert.equal(verifiedAnnouncementResearchResult(x,dates),true);
});
test('date or stock SHA substitution rejected',()=>{
  for(const mutation of [x=>x.publication_date='2026-10-09',x=>x.stocks[0].product_sha256='9'.repeat(64),x=>x.stocks[3].status='SELECTED',x=>x.stocks.pop(),x=>x.stocks[0].stock_code=x.stocks[1].stock_code]){
    const x=clone(research);mutation(x);assert.equal(verifiedAnnouncementResearchResult(x,dates),false);
  }
});
test('inconsistent row count and unverified safety gates rejected',()=>{
  for(const mutation of [x=>x.selected_stock_count=3,x=>x.production_allowed=true,x=>x.catalog_run_id=null]){
    const x=clone(research);mutation(x);assert.equal(verifiedAnnouncementResearchResult(x,dates),false);
  }
});
test('detail refuses product with missing receipt even when selection exists',()=>{
  const x=clone(detail);delete x.owner_import_receipt;
  assert.equal(verifiedAnnouncementOwnerSelection(x).verified,false);
});
test('detail refuses owner run/receipt/date/source/count mismatch',()=>{
  for(const mutation of [x=>x.owner_import_receipt.product_sha256=S,x=>x.consumption_validation.evidence_run_id=CR,
      x=>x.analysis.stock_selection.selected_stock_count=2,x=>x.publication_date='2026-10-09',
      x=>x.consumption_validation.validation_status='CANNOT_CONFIRM']){
    const x=clone(detail);mutation(x);assert.equal(verifiedAnnouncementOwnerSelection(x).verified,false);
  }
});
