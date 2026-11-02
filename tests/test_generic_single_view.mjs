import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {decodeGenericChunk,decodeActionPatch,ACTION_REBIND_FIELDS,singleSelectionHref,verifiedCompanyPart,verifiedInitialCompanyF10,bindSingleSymbolSearch,f10SourceKind,actionStatusHint,holdUnknownSummary,holderLines,financialLines,financialDisclosureText,companyBusinessText,observedCompanyNameState,historyGapText,selectCompanyFinancials,officialSourceDates,registeredDispositionNotice} from '../research-panel/workbench-host/kb-single-stock.mjs';
import {signalSummary} from '../research-panel/workbench-host/kb-signal-view.mjs';

const sha=char=>char.repeat(64);

test('registered exceptions distinguish aliases, delistings and unconfirmed trading status',()=>{
  const date='2026-10-30',base={observation_date:date,registry_sha256:sha('a')};
  const notice=d=>registeredDispositionNotice({sop_disposition:{...base,...d}},date);
  assert.equal(notice({kind:'alias_skips',replacement_symbol:'920779.BJ',replacement_status:'READY'}).replacement,'920779.BJ');
  assert.match(notice({kind:'alias_skips',replacement_symbol:'920305.BJ',replacement_status:'UNKNOWN',replacement_disposition:'VERIFIED_DELISTED'}).text,/已登记退市/);
  assert.match(notice({kind:'lifecycle_skips',effective_date:'20260714'}).text,/2026-07-14/);
  assert.match(notice({kind:'expected_no_current_bar'}).text,/观察日期.*状态待核/);
  assert.match(notice({kind:'status_verification_skips',effective_date:'20260911',status_verified_through:'20261027'}).text,/2026-09-11.*2026-10-27.*待核/);
  assert.equal(registeredDispositionNotice({sop_disposition:{...base,observation_date:'2026-10-29',kind:'expected_no_current_bar'}},date),null);
});

test('persisted action status makes conflicts and unknown filters visible without changing an observed action',()=>{
  assert.equal(actionStatusHint('CONFLICTING_OBSERVATIONS'),'信号冲突，待核');
  assert.equal(actionStatusHint('UNKNOWN_BUY_FILTERS'),'状态待核');
  assert.equal(actionStatusHint('UNKNOWN_SCORE_OR_RISK'),'状态待核');
  assert.equal(actionStatusHint('OBSERVED_SCORE_HOLD_CONDITIONAL'),'');
});

test('F10 canonical and registered candidate retain distinct identities',()=>{
  const day={source_date:'2026-10-30',generation:sha('a'),input_sha256:sha('b')};
  const meta={schema:'v4.workbench.generic_single_research.v1',symbol:'920196.BJ',panel_generation:sha('c'),candidate_input_sha256:sha('d')};
  const common={symbol:meta.symbol,data_date:'20261030',historical_PIT:false,RESEARCH_ONLY:true,
    production_allowed:false,buy_gate_updated:false,orders_sent:false,stock_ref:{sha256:sha('e')}};
  const canonical={...common,status:'OBSERVED',source_generation:day.generation,input_sha256:day.input_sha256};
  const research={...common,status:'OBSERVED_RESEARCH_SCOPE',lineage:'BOUND_F10_OWNER_CURRENT_OBSERVATION',
    source_generation:day.generation,input_sha256:day.input_sha256,receipt:{sha256:sha('f')}};
  assert.equal(f10SourceKind(research,day,{...meta,status:'READY_FOR_RESEARCH_REVIEW'}),'RESEARCH');
  assert.equal(f10SourceKind({...research,input_sha256:sha('9')},day,{...meta,status:'READY_FOR_RESEARCH_REVIEW'}),null);
  assert.equal(f10SourceKind(research,day,{...meta,status:'UNKNOWN_SOURCE_ADMISSION'}),null);
  const candidate={...common,status:'OBSERVED_CANDIDATE',source_generation:meta.panel_generation,input_sha256:meta.candidate_input_sha256,
    bound_source_generation:day.generation,bound_source_input_sha256:day.input_sha256,lineage:'REGISTERED_ISOLATED_PAIRED_CANDIDATE'};
  assert.equal(f10SourceKind(canonical,day,meta),'CANONICAL');assert.equal(f10SourceKind(candidate,day,meta),'CANDIDATE');
  for(const altered of [{...candidate,bound_source_input_sha256:sha('9')},{...candidate,input_sha256:sha('9')},
    {...candidate,symbol:'920201.BJ'},{...candidate,lineage:'UNREGISTERED'}, {...candidate,historical_PIT:true}])
    assert.equal(f10SourceKind(altered,day,meta),null);
  const rebound={...meta,action_rebound:true,panel_generation:sha('7'),asset_candidate_generation:meta.panel_generation,
    asset_candidate_input_sha256:meta.candidate_input_sha256,action_rebind_equivalence_sha256:sha('8')};
  const reused={...candidate,lineage:'REGISTERED_ISOLATED_PAIRED_CANDIDATE_REUSED',
    logical_candidate_generation:rebound.panel_generation,reuse_equivalence_sha256:rebound.action_rebind_equivalence_sha256};
  assert.equal(f10SourceKind(reused,day,rebound),'CANDIDATE');
  assert.equal(f10SourceKind({...reused,reuse_equivalence_sha256:sha('9')},day,rebound),null);
  assert.equal(f10SourceKind({...reused,source_generation:rebound.panel_generation},day,rebound),null);
  const child={...rebound,symbol:'600000.SH',action_rebound:false,score_candidate_generation:sha('4'),chunk_candidate_generation:sha('4')};
  const childReused={...reused,symbol:'600000.SH'};
  assert.equal(f10SourceKind(childReused,day,child),'CANDIDATE');
  assert.equal(f10SourceKind(childReused,day,{...child,chunk_candidate_generation:sha('5')}),null);
  const quarantine={...meta,symbol:'688496.SH',status:'UNKNOWN_SOURCE_ADMISSION'};
  const independent={...common,symbol:quarantine.symbol,status:'OBSERVED_INDEPENDENT_COMPANY',source_generation:null,input_sha256:null,
    bound_source_generation:day.generation,bound_source_input_sha256:day.input_sha256,price_panel_admission:'NOT_ASSERTED',
    lineage:'REGISTERED_INDEPENDENT_COMPANY_WITHOUT_PRICE_ADMISSION'};
  assert.equal(f10SourceKind(independent,day,quarantine),'INDEPENDENT');
  assert.equal(f10SourceKind(independent,day,{...quarantine,status:'READY_FOR_RESEARCH_REVIEW'}),null);
  assert.equal(f10SourceKind({...independent,price_panel_admission:'PASS'},day,quarantine),null);
  const scopedMeta={...meta,symbol:'600036.SH',status:'READY_FOR_RESEARCH_REVIEW'};
  const scoped={...common,symbol:scopedMeta.symbol,status:'OBSERVED_SCOPED_A20',source_generation:null,input_sha256:null,
    bound_source_generation:day.generation,bound_source_input_sha256:day.input_sha256,capture_receipt:{sha256:sha('f')},
    lineage:'A20_EXPLICIT_SCOPED_CAPTURE_NO_PUBLICATION'};
  assert.equal(f10SourceKind(scoped,day,scopedMeta),'SCOPED_A20');
  assert.equal(f10SourceKind({...scoped,symbol:'600000.SH'},day,{...scopedMeta,symbol:'600000.SH'}),null);
  assert.equal(f10SourceKind({...scoped,capture_receipt:{sha256:'bad'}},day,scopedMeta),null);
  assert.equal(f10SourceKind({...scoped,bound_source_input_sha256:sha('9')},day,scopedMeta),null);
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

test('verified A-share score children keep symbol and chunk generation bound',()=>{
  const {meta,chunk,ref}=sample();
  meta.asset_candidate_generation=meta.panel_generation;meta.asset_candidate_input_sha256=meta.candidate_input_sha256;
  meta.score_candidate_generation=sha('7');meta.chunk_candidate_generation=sha('7');meta.action_rebound=false;
  chunk.candidate_generation=sha('7');
  assert.equal(decodeGenericChunk(meta,chunk,ref).length,2);
  assert.throws(()=>decodeGenericChunk({...meta,symbol:'000002.SZ'},chunk,ref),/身份冲突/);
  assert.equal(decodeGenericChunk({...meta,symbol:'000002.SZ'},{...chunk,symbol:'000002.SZ'},ref).length,2);
  assert.throws(()=>decodeGenericChunk({...meta,score_candidate_generation:sha('6')},chunk,ref),/评分修订身份冲突/);
  assert.throws(()=>decodeGenericChunk(meta,{...chunk,candidate_generation:sha('9')},ref),/身份冲突/);
  assert.throws(()=>decodeGenericChunk({...meta,action_rebound:true},chunk,ref),/评分修订身份冲突/);
});

test('unknown score reasons are visible without inventing values',()=>{
  const score={kb_hold_close_up:true,kb_hold_above_bbi:null,kb_hold_above_bbi_reason:'INSUFFICIENT_BBI_HISTORY',
    kb_hold_volume_ok:null,kb_hold_volume_ok_reason:'RULE_NOT_QUANTIFIED',kb_hold_trend_up:null,
    kb_hold_trend_up_reason:'AMBIGUOUS_SAME_BAR_PIVOT',kb_hold_j_not_dead:null,kb_hold_j_not_dead_reason:'BOUND_KB_J_UNAVAILABLE'};
  assert.deepEqual(holdUnknownSummary(score),['BBI：BBI预热不足','阳线得分：旧版结果待按现规则更新',
    'N型：同一日同时出现高低转折，先后次序待核','J：原 J 未生成，上游行情或规则门待核']);
  score.kb_hold_volume_ok_reason='INVALID_OPEN_CLOSE_INPUT';
  assert.equal(holdUnknownSummary(score)[1],'阳线得分：开盘或收盘缺失或无效');
  score.kb_hold_above_bbi_reason='BBI_EQUALITY_UNRESOLVED';
  assert.equal(holdUnknownSummary(score)[0],'BBI：收盘等于保留两位小数的BBI，等号规则待核');
});

test('dated F10 holder observations preserve native dates and uncertain net cash flow',()=>{
  const f10={captured_at:'2026-11-02T06:57:52+08:00',finance_updated_date:'20260828',
    financials:{holder_count:163327},reported_holders:{count:151330,asof_date:'2026-09-30'}};
  const lines=holderLines({},f10);
  assert.match(lines[0],/151330.*2026-09-30/);assert.match(lines[1],/163327.*统计截止日未绑定/);
  assert.match(financialLines({operating_cash_flow:4043040000000},f10)[2],/待核.*口径.*单位.*报告期/);
});

test('F10 business and period update when the verified snapshot arrives',()=>{
  const f10={captured_at:'2026-11-01T22:57:52Z',finance_updated_date:'20260828',
    financials:{report_period:'2026-09-30'},reported_business:'商业银行业务及资产管理业务。'};
  assert.equal(companyBusinessText({},null),'主营资料待核');
  assert.match(companyBusinessText({},f10),/TDX F10.*商业银行业务.*2026-11-01T22:57:52Z.*非历史PIT/);
  assert.equal(companyBusinessText({value:'已核官方主营'},f10),'已核官方主营');
  assert.match(financialDisclosureText({},f10),/TDX F10财务快照.*报告期 2026-09-30（TDX F10）.*披露日期待核.*财务接口更新 20260828/);
  assert.match(financialDisclosureText({},{}),/报告期 待核/);
  assert.match(financialDisclosureText({latest_report_period:'2026-06-30'},f10),/报告期 2026-06-30/);
});

test('history shows saved excluded price reasons and unknown positions without filling gaps with zero',()=>{
  const h={not_matured:0,missing_price:1,nonfinite_price:0,nonpositive_price:12,nonfinite_return:0};
  assert.match(historyGapText(h,{conditional:{unknown_percentile_events:76}}),/未成熟 0.*缺价 1.*非有限价格 0.*非正价格 12.*收益非有限 0.*位置待核事件 76/);
  assert.match(historyGapText({},{}),/缺价 待核.*位置待核事件 待核/);
  assert.match(historyGapText({missing_price:-1},{conditional:{unknown_percentile_events:null}}),/缺价 待核.*位置待核事件 待核/);
});

test('generic initial company F10 must pass its source check before rendering',()=>{
  const f10={reported_business:'UNVERIFIED_EXAMPLE',financials:{report_period:'2026-09-30'}};
  const missing=verifiedInitialCompanyF10(f10,true,{tdx_f10:'UNKNOWN'});
  assert.equal(missing,null);assert.equal(companyBusinessText({},missing),'主营资料待核');
  assert.match(financialDisclosureText({},missing),/报告期 待核/);
  assert.equal(verifiedInitialCompanyF10(f10,true,{tdx_f10:'VERIFIED'}),f10);
  assert.equal(verifiedInitialCompanyF10(f10,true,{}),null);
  assert.equal(verifiedInitialCompanyF10(f10,false,{}),f10);
});

test('verified F10 name updates same active code and ready status, never stale responses',()=>{
  const signal={aborted:false},input={requested:'301686.SZ',current:'301686.SZ',name:'中塑股份',knownName:'301686.SZ',signal,currentSignal:signal,
    status:'来源 2026-10-30 · 观察 2026-11-02 · 301686.SZ单股研究 · 单股评分修订 123',sourceDate:'2026-10-30',observationDate:'2026-11-02'};
  assert.deepEqual(observedCompanyNameState(input),{name:'中塑股份',status:'来源 2026-10-30 · 观察 2026-11-02 · 中塑股份单股研究 · 单股评分修订 123'});
  assert.equal(observedCompanyNameState({...input,current:'600000.SH'}),null);
  assert.equal(observedCompanyNameState({...input,currentSignal:{aborted:false}}),null);
  assert.equal(observedCompanyNameState({...input,signal:{aborted:true}}),null);
  assert.equal(observedCompanyNameState({...input,knownName:'已核名称'}),null);
  assert.equal(observedCompanyNameState({...input,status:'原式图载入中…'}).status,'原式图载入中…');
});

test('verified official operating cash flow is retained while unbound native values remain unknown',()=>{
  const source={evidence_status:'OFFICIAL_FILING',latest_report_period:'2026-09-30',monetary_unit:'元',
    operating_cash_flow:-141711300.48,latest_financial_source_url:'https://example.test/report.pdf'};
  const checks={official_quarterly:'VERIFIED'},refs={official_quarterly:{url:'https://example.test/report.pdf',file:{sha256:'93465671bf989f73f201d7838d4cda9651786d622ee20d1bff0eddcf69b29a02'}}};
  assert.match(financialLines(verifiedCompanyPart(source,checks,refs),{})[2],/经营现金流净额.*官方财报.*-1\.42亿元/);
  assert.match(financialLines(verifiedCompanyPart(source,{official_quarterly:'UNKNOWN'},refs),{})[2],/待核/);
  assert.match(financialLines(verifiedCompanyPart(source,checks,{official_quarterly:{...refs.official_quarterly,file:{sha256:'a'.repeat(64)}}}),{})[2],/待核/);
  assert.match(financialLines(verifiedCompanyPart({...source,operating_cash_flow:-141711300.49},checks,refs),{})[2],/待核/);
  assert.match(financialLines(verifiedCompanyPart({...source,latest_report_period:'2026-06-30'},checks,refs),{})[2],/待核/);
  assert.match(financialLines({...source,evidence_status:'TDX'},{} )[2],/待核/);
  assert.match(financialLines(verifiedCompanyPart({...source,monetary_unit:null},checks,refs),{} )[2],/待核/);
});

test('scoped official quarterly data stays source-bound and dates remain distinct',()=>{
  const financials={evidence_status:'OFFICIAL_FILING',latest_report_period:'2026-09-30',monetary_unit:'元',
    operating_cash_flow_basis:'NET_CASH_FLOW_FROM_OPERATING_ACTIVITIES',operating_cash_flow:268604000000};
  const f10={official_observation:{financials,issuer_index_date:'2026-10-30',sse_notice_date:'2026-10-31',
    availability_asof_20261030_market_close:'CANNOT_CONFIRM'}};
  assert.match(financialLines(selectCompanyFinancials({},f10,false),{})[2],/待核/);
  assert.match(financialLines(selectCompanyFinancials({},f10,true),{})[2],/经营现金流净额.*官方财报.*2686\.04亿元/);
  assert.match(officialSourceDates(f10,true),/发行人官网列表.*2026-10-30.*上交所披露.*2026-10-31.*盘中可得性待核/);
  assert.equal(officialSourceDates(f10,false),'');
  assert.match(financialDisclosureText(financials,{},{}),/披露日期待核/);
});

test('secondary cash values retain provider period and unverified legacy raw scope',()=>{
  const fresh={evidence_status:'SECONDARY_REPORTED',latest_report_period:'2026-09-30',monetary_unit:'元',currency:'CNY',
    latest_financial_source_url:'https://example.test/source',source_captured_at:'2026-11-02T00:00:00Z',
    operating_cash_flow:'-2222350971.84',operating_cash_flow_basis:'NET_CASH_FLOW_FROM_OPERATING_ACTIVITIES'};
  const refs={secondary_finance:{url:fresh.latest_financial_source_url},secondary_card:{url:fresh.latest_financial_source_url}};
  assert.match(financialLines(verifiedCompanyPart(fresh,{secondary_finance:'VERIFIED'},refs),{})[2],/二级来源.*合并口径待核.*-22\.22亿元/);
  assert.match(financialDisclosureText(fresh,{},{}),/二级.*2026-09-30.*实际采集.*非历史PIT/);
  const old={...fresh,source_raw_status:'NOT_AVAILABLE_IN_BOUND_MATERIAL',operating_cash_flow_basis:'PROVIDER_REPORTED_UNCONFIRMED_SCOPE'};
  assert.match(financialLines(verifiedCompanyPart(old,{secondary_card:'VERIFIED'},refs),{})[2],/已报值.*原响应及合并口径待核.*-22\.22亿元/);
  assert.match(financialLines(verifiedCompanyPart(old,{secondary_card:'UNKNOWN'},refs),{})[2],/待核/);
});

test('generic chunk rejects wrong source, day and N rule identity',()=>{
  const {meta,chunk,ref}=sample();
  assert.throws(()=>decodeGenericChunk(meta,{...chunk,symbol:'000001.SZ'},ref),/身份冲突/);
  assert.throws(()=>decodeGenericChunk(meta,{...chunk,rows:[chunk.rows[1],chunk.rows[0]]},ref),/内容冲突/);
  const bad=structuredClone(chunk);bad.rows[1][3].kb_n_structure.rule_sha256=sha('9');
  assert.throws(()=>decodeGenericChunk(meta,bad,ref),/诊断身份冲突/);
});

function reboundSample(){
  const s=sample(),meta=s.meta;
  meta.asset_candidate_generation=meta.panel_generation;meta.asset_candidate_input_sha256=meta.candidate_input_sha256;
  meta.panel_generation=sha('7');meta.candidate_input_sha256=sha('6');meta.action_rebound=true;
  meta.origin_binding_sha256=sha('3');meta.action_source_overlay_sha256=sha('4');
  meta.action_rebind_equivalence_sha256=sha('5');meta.action_patch_rows=1;
  const old=[null,'UNKNOWN',null,'UNKNOWN','[]',sha('e')],next=[null,'UNKNOWN',null,'CONFLICTING_OBSERVATIONS','["冲突"]',sha('e')];
  const payload={schema:'v4.workbench.generic_action_patch.v1',symbol:meta.symbol,
    origin_candidate_generation:meta.asset_candidate_generation,origin_candidate_input_sha256:meta.asset_candidate_input_sha256,
    candidate_generation:meta.panel_generation,candidate_input_sha256:meta.candidate_input_sha256,
    origin_binding_sha256:meta.origin_binding_sha256,source_overlay_sha256:meta.action_source_overlay_sha256,
    equivalence_sha256:meta.action_rebind_equivalence_sha256,field_names:ACTION_REBIND_FIELDS,
    rows:[[20261029,old,next]],historical_PIT:false,RESEARCH_ONLY:true,production_allowed:false,buy_gate_updated:false,orders_sent:false};
  return {...s,payload};
}

test('rebound action reads persisted correction while retaining old source asset identity',()=>{
  const {meta,chunk,ref,payload}=reboundSample(),patch=decodeActionPatch(meta,payload);
  const rows=decodeGenericChunk(meta,chunk,ref,patch);
  assert.equal(rows[0].action.kb_action_with_position_status,'CONFLICTING_OBSERVATIONS');
  assert.equal(rows[0].action.kb_action_reasons,'["冲突"]');
  assert.equal(rows[1].action.kb_action_reasons,'[]');
  assert.equal(chunk.candidate_generation,meta.asset_candidate_generation);
  assert.notEqual(chunk.candidate_generation,meta.panel_generation);
  const unchanged={...meta,action_patch_rows:0};assert.equal(decodeGenericChunk(unchanged,chunk,ref,new Map())[0].action.kb_action_reasons,'[]');
  assert.throws(()=>decodeGenericChunk(meta,chunk,ref),/身份冲突/);
});

test('rebound action rejects missing, duplicated, wrong-date, source or before values',()=>{
  const {meta,chunk,ref,payload}=reboundSample();
  for(const altered of [{...payload,rows:[]},{...payload,symbol:'000001.SZ'},
    {...payload,candidate_generation:sha('8')},{...payload,origin_candidate_generation:sha('9')},
    {...payload,source_overlay_sha256:sha('9')},{...payload,equivalence_sha256:sha('9')},
    {...payload,rows:[[20261028,payload.rows[0][1],payload.rows[0][2]]]},
    {...payload,rows:[[20261029,payload.rows[0][1],payload.rows[0][1]]]}])
    assert.throws(()=>decodeActionPatch(meta,altered),/行动修订/);
  assert.throws(()=>decodeActionPatch({...meta,action_patch_rows:2},{...payload,rows:[payload.rows[0],payload.rows[0]]}),/行动修订/);
  const bad=structuredClone(payload);bad.rows[0][1][4]='["非原值"]';
  assert.throws(()=>decodeGenericChunk(meta,chunk,ref,decodeActionPatch(meta,bad)),/原值冲突/);
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

test('refresh does not revive excluded display fields while original and KB signals remain distinct',()=>{
  const policy=JSON.parse(readFileSync(new URL('../contracts/a_share_single_display_projection_v1.json',import.meta.url),'utf8'));
  const excluded=new Set(policy.excluded_from_display_projection);
  assert.equal(excluded.size,25);
  const original=Object.fromEntries([...excluded].map(name=>[name,true]));
  original.user_v1_level1_buy_signal=true;
  const fields=[...excluded].map(name=>({name,arrow_type:'bool',group:'信号'}));
  fields.push({name:'kb_b1',arrow_type:'bool',group:'信号'});
  const values=Object.fromEntries(fields.map(({name})=>[name,true]));
  const first=signalSummary(fields,values,original),refresh=signalSummary(fields,values,original);
  assert.deepEqual(refresh,first);
  assert.ok(first.chips.every(({key})=>!excluded.has(key)));
  assert.ok(first.chips.some(({key})=>key==='user_v1_level1_buy_signal'));
  assert.ok(first.chips.some(({key})=>key==='kb_b1'));
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
