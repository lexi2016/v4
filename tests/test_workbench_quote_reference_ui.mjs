import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {pathToFileURL} from 'node:url';

// The fixed framework lives in the deployed static inventory, outside this Git
// baseline. Point to that unchanged inventory; no installation or fixture copy.
const staticRoot=process.env.WORKBENCH_STATIC_ROOT;
if(!staticRoot)throw Error('WORKBENCH_STATIC_ROOT required (directory containing workbench-host)');
const original=pathToFileURL(staticRoot+'/workbench-host/dot/src/observation-view.mjs').href;
const local=fs.readFileSync(new URL('../research/stock_panel_collab_20261030/mac-host/observation-local.mjs',import.meta.url),'utf8').replaceAll("'./dot/src/observation-view.mjs'",JSON.stringify(original));
const {displayQuote,sortDisplayStocks,rowValidity}=await import('data:text/javascript;base64,'+Buffer.from(local).toString('base64'));
const now='2026-11-06T02:00:30Z',sha='a'.repeat(64),stock={symbol:'000410.SZ'};
function fixture(){return {source_date:'2026-11-05',observation_date:'2026-11-06',generation:'g',input_sha256:'i',numeric_manifest:{sha256:sha},source_close_reference:{schema:'V4_WORKBENCH_SOURCE_CLOSE_REFERENCE_V1',status:'BOUND_SOURCE_CLOSE',quote_role:'SOURCE_DATE_CLOSE_REFERENCE',source_date:'2026-11-05',generation:'g',input_sha256:'i',numeric_manifest:{sha256:sha},selector:{sha256:sha},currency:'CNY',source_asof:null,source_asof_precision:'DATE_ONLY',price_basis:'QFQ_ASOF_20261105',amount_basis:'RAW_TURNOVER',RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false,rows:{'000410.SZ':{symbol:'000410.SZ',price:5.46,change_percent_source:0.1834862385,amount_source:529314656}}}};}
function snapshot(){return {source_date:'2026-11-05',observation_date:'2026-11-06',slot:'1000',daily_contract_sha256:sha,rows:[{symbol:'000410.SZ',currency:'CNY',price:5.5,change_percent_source:1,amount_source:1e8,source_asof:'2026-11-06T02:00:00Z',observed_at_upper_bound:'2026-11-06T02:00:20Z',percent_change_rank_eligible:true,status:'CURRENT_VISIBLE_FIELDS_CHECKED'}]};}
test('future observation missing uses separately dated close; never grants intraday validity',()=>{
 const day=fixture(),q=displayQuote(stock,day,null,now);assert.equal(q.role,'SOURCE_DATE_CLOSE_REFERENCE');assert.equal(q.row.price,5.46);assert.equal(q.label,'2026-11-05 收盘参考');assert.equal(rowValidity(q.row,snapshot(),'price',now).valid,false);assert.equal(q.row.source_asof,null);
});
test('real same-day observation retains priority and original validity',()=>{
 const day=fixture(),s=snapshot(),q=displayQuote(stock,day,s,now);assert.equal(q.role,'OBSERVATION');assert.equal(q.row.price,5.5);assert.equal(q.validity.percent.valid,true);
 const partial=snapshot();partial.rows[0].amount_source=null;assert.equal(displayQuote(stock,day,partial,now).validity.amount.valid,false);
 s.rows[0].source_asof='2026-11-05T02:00:00Z';assert.equal(displayQuote(stock,day,s,now).role,'SOURCE_DATE_CLOSE_REFERENCE');
});
test('date, generation, input, manifest, role and future conflicts stay unknown',()=>{
 for(const [key,value]of [['source_date','2026-11-04'],['generation','other'],['input_sha256','other'],['numeric_manifest',{sha256:'b'.repeat(64)}],['quote_role','OBSERVATION'],['currency','HKD'],['source_asof','2026-11-05T07:00:00Z'],['production_allowed',true]]){const day=fixture();day.source_close_reference[key]=value;assert.equal(displayQuote(stock,day,null,now).role,'UNKNOWN',key);}
 const day=fixture();day.source_date='2026-11-06';assert.equal(displayQuote(stock,day,null,now).role,'UNKNOWN');assert.equal(displayQuote(stock,fixture(),null,'2026-11-04T10:00:00Z').role,'UNKNOWN');
});
test('null stays null and sorting separates observed from reference roles',()=>{
 const day=fixture();day.source_close_reference.rows['000410.SZ'].price=null;assert.equal(displayQuote(stock,day,null,now).validity.price.valid,false);
 const other={symbol:'603007.SH'};day.source_close_reference.rows[other.symbol]={...day.source_close_reference.rows[stock.symbol],symbol:other.symbol,price:99};
 const rows=[other,stock],s=snapshot();assert.deepEqual(sortDisplayStocks(rows,{day,snapshot:s,mode:'price_desc',now}).map(r=>r.symbol),[stock.symbol,other.symbol]);
 s.rows[0].source_asof=null;assert.deepEqual(sortDisplayStocks(rows,{day,snapshot:s,mode:'price_desc',now}).map(r=>r.symbol),[other.symbol,stock.symbol]);assert.deepEqual(sortDisplayStocks(rows,{day,snapshot:s,mode:'original_groups',now}),rows);
});
// Execute the actual selected-header function rather than mirroring its labels.
const shell=fs.readFileSync(new URL('../research/stock_panel_collab_20261030/mac-host/dot/shell/workbench.local.mjs',import.meta.url),'utf8');
test('actual shell selected header renders price, percent, amount and source role',()=>{
 const source=shell.slice(shell.indexOf('function selectedObservation(r){'),shell.indexOf('\nfunction tickObservationPresentation'));
 const elements=new Map(),ctx={day:fixture(),observationSnapshot:null,displayQuote,Number,$:id=>{if(!elements.has(id))elements.set(id,{});return elements.get(id)},priceLabel:r=>r.price.toFixed(2),amountLabel:r=>(r.amount_source/1e8).toFixed(2)+'亿'};
 vm.runInNewContext(source+';selectedObservation({symbol:"000410.SZ"});',ctx);assert.equal(elements.get('selectedPrice').textContent,'5.46 元 · +0.18%');assert.equal(elements.get('selectedAmount').textContent,'收盘成交额 5.29亿');assert.match(elements.get('selectedQuoteTime').textContent,/2026-11-05 收盘参考/);assert.match(elements.get('selectedObservation').textContent,/0.18%/);assert.match(elements.get('selectedObservation').textContent,/2026-11-06 观察报价尚未就绪/);
});
