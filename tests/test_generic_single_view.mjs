import test from 'node:test';
import assert from 'node:assert/strict';
import {decodeGenericChunk,singleSelectionHref,verifiedCompanyPart,bindSingleSymbolSearch,f10SourceKind} from '../research-panel/workbench-host/kb-single-stock.mjs';

const sha=char=>char.repeat(64);

test('F10 canonical and registered candidate retain distinct identities',()=>{
  const day={source_date:'2026-10-30',generation:sha('a'),input_sha256:sha('b')};
  const meta={schema:'v4.workbench.generic_single_research.v1',symbol:'920196.BJ',panel_generation:sha('c'),candidate_input_sha256:sha('d')};
  const common={symbol:meta.symbol,data_date:'20261030',historical_PIT:false,RESEARCH_ONLY:true,
    production_allowed:false,buy_gate_updated:false,orders_sent:false,stock_ref:{sha256:sha('e')}};
  const canonical={...common,status:'OBSERVED',source_generation:day.generation,input_sha256:day.input_sha256};
  const candidate={...common,status:'OBSERVED_CANDIDATE',source_generation:meta.panel_generation,input_sha256:meta.candidate_input_sha256,
    bound_source_generation:day.generation,bound_source_input_sha256:day.input_sha256,lineage:'REGISTERED_ISOLATED_PAIRED_CANDIDATE'};
  assert.equal(f10SourceKind(canonical,day,meta),'CANONICAL');assert.equal(f10SourceKind(candidate,day,meta),'CANDIDATE');
  for(const altered of [{...candidate,bound_source_input_sha256:sha('9')},{...candidate,input_sha256:sha('9')},
    {...candidate,symbol:'920201.BJ'},{...candidate,lineage:'UNREGISTERED'}, {...candidate,historical_PIT:true}])
    assert.equal(f10SourceKind(altered,day,meta),null);
  const quarantine={...meta,symbol:'688496.SH',status:'UNKNOWN_SOURCE_ADMISSION'};
  const independent={...common,symbol:quarantine.symbol,status:'OBSERVED_INDEPENDENT_COMPANY',source_generation:null,input_sha256:null,
    bound_source_generation:day.generation,bound_source_input_sha256:day.input_sha256,price_panel_admission:'NOT_ASSERTED',
    lineage:'REGISTERED_INDEPENDENT_COMPANY_WITHOUT_PRICE_ADMISSION'};
  assert.equal(f10SourceKind(independent,day,quarantine),'INDEPENDENT');
  assert.equal(f10SourceKind(independent,day,{...quarantine,status:'READY_FOR_RESEARCH_REVIEW'}),null);
  assert.equal(f10SourceKind({...independent,price_panel_admission:'PASS'},day,quarantine),null);
});

function sample(){
  const groups={kb:['kb_b1'],hold_score:['kb_hold_trend_up','kb_hold_trend_up_reason'],supplemental:[],
    action:['kb_action_no_position','kb_action_no_position_status','kb_action_with_position','kb_action_with_position_status','kb_action_reasons','kb_action_rule_sha256'],
    yidong:['kb_yidong_rule_sha256','kb_yidong_vol_ratio_5'],confirmed_kb_fields:[]};
  while(Object.values(groups).flat().length<107)groups.kb.push('padding_'+groups.kb.length);
  const field_names=Object.values(groups).flat(),original_fields=Array.from({length:13},(_,i)=>'original_'+i);
  const meta={symbol:'600000.SH',panel_generation:sha('a'),generation:sha('9'),input_sha256:sha('8'),candidate_input_sha256:sha('b'),
    n_generation_id:sha('a'),n_input_sha256:sha('b'),
    n_rule_sha256:sha('c'),n_helper_sha256:sha('d'),action_contract_sha256:sha('e'),yidong_contract_sha256:sha('f'),
    dates:[20261029,20261030],field_names,field_groups:groups,original_fields};
  const values={kb_b1:true,kb_hold_trend_up:null,kb_hold_trend_up_reason:'INSUFFICIENT_CONFIRMED_SWINGS',
    kb_action_no_position:null,kb_action_no_position_status:'UNKNOWN',kb_action_with_position:null,
    kb_action_with_position_status:'UNKNOWN',kb_action_reasons:'[]',kb_action_rule_sha256:sha('e'),
    kb_yidong_rule_sha256:sha('f'),kb_yidong_vol_ratio_5:null};
  const n={state:'INSUFFICIENT_CONFIRMED_SWINGS',rule_sha256:sha('c'),helper_sha256:sha('d'),input_sha256:sha('b'),generation_id:sha('a')};
  const diagnostics=Object.fromEntries(Array.from({length:24},(_,i)=>['diagnostic_'+i,null]));diagnostics.kb_n_structure=n;
  const row=date=>[date,field_names.map(key=>values[key]??null),original_fields.map(()=>null),diagnostics,[10.123,9.456]];
  const chunk={schema:'v4.workbench.generic_single_chunk.v1',symbol:meta.symbol,candidate_generation:meta.panel_generation,
    source_input_sha256:meta.input_sha256,candidate_input_sha256:meta.candidate_input_sha256,rows:meta.dates.map(row)};
  return {meta,chunk,ref:{first_date:20261029,last_date:20261030,row_count:2}};
}

test('generic chunk restores persisted data and keeps null separate from false',()=>{
  const {meta,chunk,ref}=sample(),rows=decodeGenericChunk(meta,chunk,ref);
  assert.equal(rows.length,2);assert.equal(rows[0].trade_date,20261029);assert.equal(rows[0].kb.kb_b1,true);
  assert.equal(rows[0].hold_score.kb_hold_trend_up,null);assert.equal(rows[0].confirmed_kb_reused.bowl_white,10.123);
  assert.equal(rows[1].action.kb_action_no_position,null);
});

test('generic chunk rejects wrong source, day and N rule identity',()=>{
  const {meta,chunk,ref}=sample();
  assert.throws(()=>decodeGenericChunk(meta,{...chunk,symbol:'000001.SZ'},ref),/身份冲突/);
  assert.throws(()=>decodeGenericChunk(meta,{...chunk,rows:[chunk.rows[1],chunk.rows[0]]},ref),/内容冲突/);
  const bad=structuredClone(chunk);bad.rows[1][3].kb_n_structure.rule_sha256=sha('9');
  assert.throws(()=>decodeGenericChunk(meta,bad,ref),/诊断身份冲突/);
});

test('N source identity can remain a verified earlier generation',()=>{
  const {meta,chunk,ref}=sample();meta.n_generation_id=sha('9');meta.n_input_sha256=sha('8');
  for(const row of chunk.rows){row[3].kb_n_structure.generation_id=sha('9');row[3].kb_n_structure.input_sha256=sha('8')}
  assert.equal(decodeGenericChunk(meta,chunk,ref)[0].hold_score.kb_hold_trend_up,null);
  meta.n_generation_id=sha('a');assert.throws(()=>decodeGenericChunk(meta,chunk,ref),/诊断身份冲突/);
});

test('symbol changes clear both versions and same symbol keeps date/version',()=>{
  const url='http://localhost/?symbol=600000.SH&panel_generation='+sha('a')+'&view_generation='+sha('b');
  const same=new URL(singleSelectionHref(url,'600000.SH','2025-01-03'));
  assert.equal(same.searchParams.get('panel_generation'),sha('a'));assert.equal(same.searchParams.get('view_generation'),sha('b'));
  const other=new URL(singleSelectionHref(same.href,'HK.00700'));
  assert.equal(other.searchParams.get('symbol'),'HK.00700');assert.equal(other.searchParams.has('panel_generation'),false);
  assert.equal(other.searchParams.has('view_generation'),false);assert.equal(other.searchParams.has('stock_date'),false);
  assert.throws(()=>singleSelectionHref(url,'HK.700'),/证券无效/);
});

test('verified company fields survive an unrelated missing document',()=>{
  const official={evidence_status:'OFFICIAL_FILING',source_url:'https://example.test/report.pdf',value:'已披露'},
    refs={official_quarterly:{url:official.source_url}},checks={official_quarterly:'VERIFIED',broker_research:'UNKNOWN'};
  assert.equal(verifiedCompanyPart(official,checks,refs),official);
  assert.deepEqual(verifiedCompanyPart({...official,source_url:'https://other.test/report.pdf'},checks,refs),{});
  assert.deepEqual(verifiedCompanyPart(official,{...checks,official_quarterly:'UNKNOWN'},refs),{});
  const f10={value:'采集时记录'};
  assert.equal(verifiedCompanyPart(f10,{tdx_f10:'VERIFIED'},{}),f10);
  assert.deepEqual(verifiedCompanyPart(f10,{},{}),{});
});

test('exact symbol search opens any materialized stock and keeps partial search as filtering',()=>{
  let handler,opened=[],prevented=0;
  const input={value:' 600000.sh ',addEventListener:(kind,fn)=>{assert.equal(kind,'keydown');handler=fn}};
  bindSingleSymbolSearch(input,symbol=>opened.push(symbol));
  handler({key:'Enter',currentTarget:input,preventDefault:()=>prevented++});assert.deepEqual(opened,['600000.SH']);
  input.value='HK.00700';handler({key:'Enter',currentTarget:input,preventDefault:()=>prevented++});assert.deepEqual(opened,['600000.SH','HK.00700']);
  input.value='600';handler({key:'Enter',currentTarget:input,preventDefault:()=>prevented++});
  assert.equal(prevented,2);assert.equal(opened.length,2);
});
