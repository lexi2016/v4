import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {quoteContext} from '../research/stock_panel_collab_20261030/mac-host/dot/src/workbench-model.mjs';
function fixture(){
 const native={scope_count:371,rows:{'001379.SZ':{symbol:'001379.SZ',price:20}}};
 const day={source_date:'2026-11-09',generation:'a'.repeat(64),input_sha256:'b'.repeat(64),source_selector_sha256:'c'.repeat(64),numeric_manifest:{path:'/numeric',sha256:'d'.repeat(64)},source_close_reference:native};
 const rows=Object.fromEntries(Array.from({length:19},(_,i)=>{const symbol=String(600000+i)+'.SH';return [symbol,{symbol,price:10+i,change_percent_source:i-9,amount_source:1000000+i}]}));
 const ref={schema:'V4_WORKBENCH_SOURCE_CLOSE_REFERENCE_V1',status:'BOUND_SOURCE_CLOSE',source_date:day.source_date,generation:day.generation,input_sha256:day.input_sha256,numeric_manifest:day.numeric_manifest,selector:{sha256:day.source_selector_sha256},scope_count:19,rows};
 day.v192_group={source_close_reference:ref};return {day,ref,native};
}
test('all19 model rows receive the independent close map while371 native scope stays unchanged',()=>{
 const {day,ref,native}=fixture(),before=structuredClone(day);
 for(const [symbol,expected]of Object.entries(ref.rows)){
  const view=quoteContext(day,{symbol,v192_member:true});assert.equal(view.source_close_reference,ref);
  assert.equal(view.source_close_reference.rows[symbol].price,expected.price);
  assert.equal(view.source_close_reference.rows[symbol].amount_source,expected.amount_source);
 }
 assert.deepEqual(day,before);assert.equal(day.source_close_reference,native);assert.equal(native.scope_count,371);
 assert.equal(quoteContext(day,{symbol:'001379.SZ'}),day);
 const shell=fs.readFileSync(new URL('../research/stock_panel_collab_20261030/mac-host/dot/shell/workbench.local.mjs',import.meta.url),'utf8');
 assert.ok(shell.includes('displayQuote(r,quoteContext(day,r),observationSnapshot)'));
 assert.ok(shell.includes("day:quoteContext(day,{v192_member:group==='v192'})"));
});
test('wrong date, generation, selector or numeric identity never borrows a canonical old price',()=>{
 for(const changed of [{source_date:'2026-11-06'},{generation:'f'.repeat(64)},{input_sha256:'f'.repeat(64)},{selector:{sha256:'f'.repeat(64)}},{numeric_manifest:{path:'/old',sha256:'d'.repeat(64)}}]){
  const {day,ref}=fixture();day.v192_group.source_close_reference={...ref,...changed};
  assert.equal(quoteContext(day,{symbol:'600000.SH',v192_member:true}).source_close_reference,null);
  assert.equal(day.source_close_reference.scope_count,371);
 }
 const {day}=fixture();delete day.v192_group.source_close_reference;
 assert.equal(quoteContext(day,{symbol:'600000.SH',v192_member:true}).source_close_reference,null);
});
