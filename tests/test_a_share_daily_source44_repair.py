"""Frozen Mac source44 evidence and exact boundary regressions."""
import copy
import hashlib
import json
from pathlib import Path
import pytest
from ops import a_share_daily_sync as owner
from ops._a_share_daily_sync_parts import progress

B=Path('/Users/lexi/Desktop/学习/因子工厂/research/workbench_daily_chain_completion_20261031_r1')

@pytest.fixture
def source44():
    path=B/'execution/source44/followup-r5/PREPARE_RECEIPT.json'
    if not path.exists():pytest.skip('Frozen Mac source44 evidence not present')
    value=json.loads(path.read_bytes());reference=value['seed_descriptor']
    context=dict(path=reference['path'],expected_sha256=reference['sha256'],records=[])
    return value,context,progress._seed_evidence_bundle(context,20261030)


def test_bj_current_capture_exact_terms_are_separate_from_old_adoption(source44):
    value,context,bundle=source44
    for symbol in ('920029.BJ','920100.BJ','920187.BJ','920208.BJ','920003.BJ','920699.BJ'):
        evidence=progress._supplemental_tdx_seed_evidence(owner.__dict__,bundle,symbol)
        spec=evidence['supplemental_source'];a,b=spec['pair_dates']
        assert progress._explain_seed_pair(owner.__dict__,context,symbol,20261030,a,b,evidence['selected'][a]['close'],evidence['selected'][b]['close'])
        assert context['records'][-1]['supplemental_source']['historical_PIT'] is False
        assert 'NOT_OLD_ADOPTION' in context['records'][-1]['source_kind']
    corrupted=copy.deepcopy(bundle);corrupted['descriptor']['supplemental_tdx_seed_pairs']['920029.BJ']['parser_receipt']['sha256']='0'*64
    with pytest.raises(ValueError,match='sha256'):progress._supplemental_tdx_seed_evidence(owner.__dict__,corrupted,'920029.BJ')


def boundary(scope,bundle,previous=20260831,current=20261023,symbol='002731.SZ'):
    spec=bundle['descriptor']['delisting_first_session_boundaries']['002731.SZ']
    raw=Path(spec['raw_source']['path']).read_bytes();rows={owner.DAY_STRUCT.unpack(raw[o:o+32])[0]:owner.DAY_STRUCT.unpack(raw[o:o+32])[4]/100 for o in range(0,len(raw),32)}
    context={'records':[]}
    ok=progress._explain_delisting_first_session(scope,context,bundle,symbol,previous,current,rows.get(previous,rows[20260831]),rows.get(current,rows[20261023]))
    return ok,context['records'][-1]


def test_official_delisting_first_session_exact_pair_passes(source44):
    _,_,bundle=source44
    ok,record=boundary(owner.__dict__,bundle)
    assert ok and record['status']=='EXPLAINED_DELISTING_FIRST_SESSION_NO_PRICE_LIMIT'
    assert record['historical_PIT'] is False


@pytest.mark.parametrize('previous,current,symbol',[(20260831,20261022,'002731.SZ'),(20260831,20261026,'002731.SZ'),(20260828,20260831,'002731.SZ'),(20260831,20261023,'002732.SZ')])
def test_delisting_boundary_does_not_accept_wrong_date_stock_or_ordinary_session(source44,previous,current,symbol):
    _,_,bundle=source44
    assert not boundary(owner.__dict__,bundle,previous,current,symbol)[0]


def test_delisting_boundary_wrong_pdf_and_whole_row_are_rejected(source44):
    _,_,bundle=source44
    bad=copy.deepcopy(bundle);bad['descriptor']['delisting_first_session_boundaries']['002731.SZ']['official_notice']['sha256']='0'*64
    assert not boundary(owner.__dict__,bad)[0]
    bad=copy.deepcopy(bundle);bad['descriptor']['delisting_first_session_boundaries']['002731.SZ']['pair_row_sha256']['20261023']='0'*64
    assert not boundary(owner.__dict__,bad)[0]


def test_delisting_lifecycle_is_persistent_only_at_effective_date(source44):
    facts=owner._load_verified_lifecycle_facts()
    assert owner._lifecycle_fact_for_target(facts,'301139',0,20261027) is None
    assert owner._lifecycle_fact_for_target(facts,'301139',0,20261028)['verified']
    assert owner._lifecycle_fact_for_target(facts,'301139',0,20261102)['delisting_effective_date']=='20261028'
    assert owner._lifecycle_fact_for_target(facts,'301139',1,20261030) is None


def test_no_current_bar_is_exact_date_stock_and_entire_input_hash(source44):
    policy=owner._daily_source_policy_additions();fact=policy['exact_no_current_bar_dispositions'][0];symbol,suffix=fact['symbol'].split('.');market={'SZ':0,'SH':1}[suffix]
    assert owner._exact_no_current_bar_for_target(symbol,market,20261030,fact['expected_native_sha256'])
    assert owner._exact_no_current_bar_for_target(symbol,market,20261029,fact['expected_native_sha256']) is None
    assert owner._exact_no_current_bar_for_target(symbol,market,20261030,'0'*64) is None
    assert owner._exact_no_current_bar_for_target('000001',market,20261030,fact['expected_native_sha256']) is None


def test_source_policy_preserves_actual_main_owner_1540_contract(monkeypatch,tmp_path):
    """Exercise the actual serving Main source owner, not the older snapshot."""
    import importlib.util
    main=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/workbench-daily-chain-20261031-r1-main/app')
    source=main/'ops/research_panel_daily_source.py'
    if not source.exists():pytest.skip('Installed Mac Main owner unavailable')
    spec=importlib.util.spec_from_file_location('actual_daily_source_policy_owner',source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    candidate=Path(owner.__file__).resolve().parents[1]/'contracts/a_share_daily_source_policy.json'
    monkeypatch.setattr(module,'POLICY_PATH',candidate)
    policy=module.source_policy()
    assert policy['earliest_slot']=='1540' and len(policy['exact_no_current_bar_dispositions'])==5
    assert policy['verified_delisting_additions'][0]['ts_code']=='301139.SZ'
    bad=tmp_path/'old_snapshot_policy.json';bad.write_text(json.dumps({**policy,'earliest_slot':'1610'}))
    monkeypatch.setattr(module,'POLICY_PATH',bad)
    with pytest.raises(Exception,match='A_DAILY_SOURCE_POLICY_UNBOUND'):module.source_policy()


@pytest.fixture(scope='module')
def actual_delisting_source_row(tmp_path_factory):
    """One original producer call on a copy; no provider and no canonical write."""
    from ops import research_panel_factor_cache as cache
    temp=tmp_path_factory.mktemp('delisting_source_owner')
    raw=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/research_panel_daily/tdx/vipdoc/sz/lday/sz301139.day')
    if not raw.exists():pytest.skip('Frozen Mac native301139 unavailable')
    copied=temp/'sz301139.day';copied.write_bytes(raw.read_bytes())
    before=hashlib.sha256(copied.read_bytes()).hexdigest()
    def forbidden_provider():raise AssertionError('delisting must never invoke provider')
    result=owner.run_sync([owner.DailyTarget(code='301139',market=0,path=copied)],target_date='20261030',api_factory=forbidden_provider,host_candidates=[('unused',7709)],progress_path=temp/'progress.json')
    row=result['symbol_reconciliation'][0]
    assert row['source_sha256_after']==before==hashlib.sha256(copied.read_bytes()).hexdigest()
    assert row['records_written']==0 and row['lifecycle_asset_sha256']!=owner.LIFECYCLE_NOTES_SHA256
    assert row['lifecycle_policy_ref']==row['lifecycle_fact']['source_policy_ref']
    assert cache._verified_sop_skip('301139.SZ',row,20261030,None)['proof_route']=='REVIEWED_SOURCE_POLICY_OFFICIAL_DELISTING'
    return row


def test_original_producer_to_factor_cache_policy_proof(actual_delisting_source_row):
    from ops import research_panel_factor_cache as cache
    row=actual_delisting_source_row
    assert cache._verified_sop_skip('301139.SZ',row,20261028,None)
    assert cache._verified_sop_skip('301139.SZ',row,20261102,None)
    assert cache._verified_sop_skip('301139.SZ',row,20261027,None) is None


@pytest.mark.parametrize('mutation',['symbol','market','code','pdf','policy_sha','policy_path','policy_fact','raw_sha','records','old_asset','missing_policy','effective_date'])
def test_exact_delisting_proof_rejects_changed_identity(actual_delisting_source_row,mutation,tmp_path):
    from ops import research_panel_factor_cache as cache
    row=copy.deepcopy(actual_delisting_source_row);code='301139.SZ'
    if mutation=='symbol':row['symbol']='301138'
    elif mutation=='market':row['market']=1
    elif mutation=='code':code='301138.SZ'
    elif mutation=='pdf':row['lifecycle_fact']['official_notice']['sha256']='0'*64
    elif mutation=='policy_sha':row['lifecycle_policy_ref']['sha256']='0'*64
    elif mutation=='policy_path':row['lifecycle_policy_ref']['path']=str(tmp_path/'absent.json')
    elif mutation=='policy_fact':row['lifecycle_fact']['verified']=False
    elif mutation=='raw_sha':row['source_sha256_after']='0'*64
    elif mutation=='records':row['records_written']=1
    elif mutation=='old_asset':row['lifecycle_asset_sha256']=owner.LIFECYCLE_NOTES_SHA256
    elif mutation=='missing_policy':row.pop('lifecycle_policy_ref')
    elif mutation=='effective_date':row['lifecycle_fact']['delisting_effective_date']='20261027'
    assert cache._verified_sop_skip(code,row,20261030,None) is None


def test_previous_29_lifecycle_rows_match_active_factor_owner():
    import importlib.util
    from ops import research_panel_factor_cache as candidate
    source=B/'execution/factor_skip/ACTIVE_R2_factor_cache.py'
    spec=importlib.util.spec_from_file_location('accepted_factor_skip_baseline',source)
    baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
    baseline._LIFECYCLE_ASSET_PATH=candidate._LIFECYCLE_ASSET_PATH
    path=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/research_panel_daily/receipts/a_sync_authority/20261030/summary.json')
    rows=[r for r in json.loads(path.read_bytes())['symbol_reconciliation'] if r.get('lifecycle_skip') and r['symbol']!='301139']
    assert len(rows)==29
    for row in rows:
        code=row['symbol']+'.'+{0:'SZ',1:'SH',2:'BJ'}[row['market']]
        assert candidate._verified_sop_skip(code,row,20261030,None)==baseline._verified_sop_skip(code,row,20261030,None)


@pytest.mark.parametrize('dependency',['raw_sha','floor','event','history','resolution','market'])
def test_same_asof_stock_price_dependencies_reject_actual_changes(dependency):
    from ops import research_panel_qfq as q
    item=dict(history_start_date=20200102,compute_start_date=20200102,events=[dict(ex_date=20260102,a=.5,b=-.1,volume_a=2.)],raw_files=[dict(path='/one/native.day',sha256='a'*64,from_date_exclusive=20200101,source_role='native')],raw_resolution=q.HISTORY_RESOLUTION,history_extension=True,publish_roles=['selector','backtest'])
    changed=copy.deepcopy(item)
    if dependency=='raw_sha':changed['raw_files'][0]['sha256']='b'*64
    elif dependency=='floor':changed['raw_files'][0]['from_date_exclusive']=20200102
    elif dependency=='event':changed['events'][0]['b']=-.2
    elif dependency=='history':changed['compute_start_date']=20200201
    elif dependency=='resolution':changed['raw_resolution']='different'
    elif dependency=='market':changed['raw_files'][0]['source_role']='archive'
    assert q._same_asof_stock_dependencies(item)!=q._same_asof_stock_dependencies(changed)


def test_same_asof_all_byte_identical_paths_and_observation_proofs_do_not_reprice():
    from ops import research_panel_qfq as q
    before=dict(history_start_date=20200102,events=[],raw_files=[dict(path='/one',sha256='a'*64,source_role='native',native_update_receipt={'path':'/proof1','sha256':'c'*64})],source_method='old',source_config={'path':'/config1'},accepted_evidence=[],provider_response_scope='observed old')
    after=copy.deepcopy(before);after['raw_files'][0].update(path='/same-bytes-new-path',native_update_receipt={'path':'/proof2','sha256':'d'*64});after.update(source_method='new bound observation',provider_response_scope='observed now',source_config={'path':'/config2'})
    assert q._same_asof_stock_dependencies(before)==q._same_asof_stock_dependencies(after)


def test_same_asof_explicit_scope_is_inactive_on_another_date(monkeypatch):
    from ops import research_panel_qfq as q
    monkeypatch.setenv('V4_A_QFQ_SOURCE_REPAIR_DATE','20261030')
    monkeypatch.delenv('V4_A_QFQ_SOURCE_REPAIR_INPUT',raising=False)
    assert q._same_asof_repair_reference(20261102) is None


@pytest.mark.parametrize('chunked_arrow_context',[False,True])
def test_same_asof_retained_price_arrays_and_missing_only_turnover(chunked_arrow_context):
    import importlib.util,sys
    import pandas as pd
    import pyarrow as pa
    from ops import research_panel_qfq as q
    source=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/workbench-daily-chain-20261031-r3-main/app/ops/research_panel_turnover.py')
    spec=importlib.util.spec_from_file_location('accepted_original_turnover_context_r7',source);helper=importlib.util.module_from_spec(spec);sys.modules[spec.name]=helper;spec.loader.exec_module(helper)
    capital=helper.CapitalIndex.from_frame(pd.DataFrame([dict(market=m,code=c,datetime=20261029,category=5,hongli_panqianliutong=100.,peigujia_qianzongguben=100.,songgu_qianzongguben=100.,peigu_houzongguben=200.)for m,c in [(0,'000001'),(1,'600000'),(2,'920002')]]),20261030)
    turnover=helper.DailyTurnover(20261030,capital,{(0,'000001'):10000,(1,'600000'):10000,(2,'920002'):10000},{})
    table=pa.table(dict(ts_code=['000001.SZ','000001.SZ','600000.SH','920002.BJ','00005.HK'],trade_date=['20261029','20261030','20261030','20261030','20261030'],close=[10.,11.,12.,13.,99.],B3=[0,1,0,1,0],future_return=[None,.2,.3,-.1,None],turnover_rate_pct=[None,None,3.75,None,7.25]))
    schema=pa.schema(list(table.schema)+[pa.field('float_share_10k',pa.float64()),pa.field('turnover_rate_status',pa.string()),pa.field('turnover_rate_volume_source',pa.string()),pa.field('turnover_rate_denominator_10k',pa.float64())])
    if chunked_arrow_context:
        frame=table.to_pandas()
        frame['turnover_rate_volume_source']=pd.Series(pd.arrays.ArrowExtensionArray(pa.chunked_array([[None,None],[None,None,None]],type=pa.string())))
        table=pa.Table.from_pandas(frame,preserve_index=False)
        schema=pa.schema(list(table.schema)+[field for field in schema if field.name not in table.column_names])
        assert table['turnover_rate_volume_source'].num_chunks==2
    result,counts=q._retained_turnover_context(table,turnover,schema)
    for name in ('ts_code','trade_date','close','B3','future_return'):assert result[name].equals(table[name])
    rates=result['turnover_rate_pct'].to_pylist();assert rates==[None,1.,3.75,1.,7.25]
    assert counts['target_filled']==2 and counts['old_nonnull_preserved']==2 and counts['target_rows']==3
    assert result['float_share_10k'].to_pylist()[0]is None


@pytest.fixture
def same_asof_metadata_fixture():
    from ops import research_panel_factor_cache as factor
    descriptor=B/'execution/same_asof/SAME_ASOF_REPAIR_INPUT_R2.json'
    prepared=B/'execution/same_asof/canary_data/runtime/cache/data_layer_daily_formula_increment_update_v1/qfq_adjustment_input.json'
    if not prepared.exists():pytest.skip('Frozen private D30 input absent')
    snapshot=json.loads(prepared.read_bytes());config=snapshot['research_cache_configuration']
    value=json.loads(descriptor.read_bytes());evidence=json.loads(Path(value['metadata30_evidence']['path']).read_bytes());sdk=json.loads(Path(value['sdk_capability']['path']).read_bytes())
    codes=[r['symbol']for r in evidence['captures']]+[r['symbol']for r in sdk['rows']]
    return factor,dict(path=str(descriptor),sha256=hashlib.sha256(descriptor.read_bytes()).hexdigest()),config,codes


def test_same_asof_metadata_original30_local_sdk6_and_idempotence(same_asof_metadata_fixture,tmp_path):
    factor,ref,config,codes=same_asof_metadata_fixture
    records,provenance=factor._same_asof_metadata_records(ref,codes,20261030,config)
    assert len(records)==36
    assert sum(r['status']=='OK'for r in records.values())==30
    assert sum(r['status']=='UNSUPPORTED_MARKET'for r in records.values())==6
    for code,r in records.items():
        if not code.endswith('.BJ'):assert r['asof_date']==r['capture_date']==20261030
        else:assert r['provider_invoked']is False and r['capture_date']is None and r['sdk_validation_capture_date']==20261031
    def forbidden():raise AssertionError('No new provider capture permitted')
    first=factor.collect_research_metadata(codes,cache_root=tmp_path/'cache',target=20261030,config_ref=config,same_asof_metadata_ref=ref,client_factory=forbidden)
    second=factor.collect_research_metadata(codes,cache_root=tmp_path/'cache',target=20261030,config_ref=config,same_asof_metadata_ref=ref,client_factory=forbidden)
    assert first['symbols']==second['symbols']==records
    assert first['provider_call_count']==second['invocation_provider_call_count']==0
    assert first['same_asof_metadata_reuse']==provenance
    assert second['reused_completed_proof']is True


@pytest.mark.parametrize('mutation',['schema','code','response','capture','provider','sdk_bytes','sdk_code','sdk_source','sdk_time','missing_sdk','detector','identity','closed_parent'])
def test_same_asof_metadata_changed_proof_is_rejected(same_asof_metadata_fixture,tmp_path,mutation):
    factor,ref,config,codes=same_asof_metadata_fixture
    value=json.loads(Path(ref['path']).read_bytes());current=json.loads(Path(config['path']).read_bytes());evidence=json.loads(Path(value['metadata30_evidence']['path']).read_bytes());sdk=json.loads(Path(value['sdk_capability']['path']).read_bytes())
    def bound(name,v):
        path=tmp_path/name;path.write_text(json.dumps(v,ensure_ascii=False,sort_keys=True));return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    if mutation=='schema':value['schema']='wrong_source_schema'
    elif mutation=='code':evidence['captures'][0]['symbol']='999999.SH'
    elif mutation=='response':evidence['captures'][0]['response']['sha256']='0'*64
    elif mutation=='capture':evidence['captures'][0]['capture_date']=20261031
    elif mutation=='provider':sdk['source_api_family']='not_the_original_SDK'
    elif mutation=='sdk_bytes':sdk['rows'][0]['packed_request_is_none']=False
    elif mutation=='sdk_code':sdk['rows'][0]['request_code']='BJ.920004'
    elif mutation=='sdk_source':sdk['sdk_sources'][0]['sha256']='0'*64
    elif mutation=='sdk_time':sdk['capture_date']=20261030
    elif mutation=='missing_sdk':value['sdk_capability']={'path':str(tmp_path/'missing'),'sha256':'0'*64}
    elif mutation=='detector':current['current_detector']['coverage_end_date']=20261031
    elif mutation=='identity':
        ids=json.loads(Path(current['current_identities']['path']).read_bytes());ids['symbols'][codes[0]]['market']='SH';current['current_identities']=bound('ids.json',ids)
    elif mutation=='closed_parent':value['baseline_snapshot']=bound('uncommitted.json',{'asof_date':20261030,'research_factor_receipts':{}})
    if mutation in {'code','response','capture'}:value['metadata30_evidence']=bound('evidence.json',evidence)
    if mutation in {'provider','sdk_bytes','sdk_code','sdk_source','sdk_time'}:value['sdk_capability']=bound('sdk.json',sdk)
    if mutation in {'detector','identity'}:config=bound('config.json',current)
    ref=bound('descriptor.json',value)
    with pytest.raises((factor.QfqGateError,KeyError,ValueError)):
        factor._same_asof_metadata_records(ref,codes,20261030,config)


def test_same_asof_valid_nan_prices_require_identical_arrow_buffers():
    import pyarrow as pa
    from ops import research_panel_qfq as q
    original=pa.chunked_array([pa.array([float('nan'),None,1.],from_pandas=False)])
    assert q._same_asof_arrow_unchanged(original,original)
    changed=pa.chunked_array([pa.array([float('nan'),None,2.],from_pandas=False)])
    assert not q._same_asof_arrow_unchanged(original,changed)


@pytest.mark.parametrize('mutation',['formula','calendar','basis','schema'])
def test_same_asof_global_dependency_change_stops_before_price_reuse(tmp_path,mutation):
    import plistlib
    from ops import research_panel_qfq as q
    descriptor=B/'execution/same_asof/SAME_ASOF_REPAIR_INPUT_R2.json'
    prepared=B/'execution/same_asof/canary_data/runtime/cache/data_layer_daily_formula_increment_update_v1/qfq_adjustment_input.json'
    if not prepared.exists():pytest.skip('Frozen private D30 input absent')
    value=json.loads(descriptor.read_bytes());snapshot=json.loads(prepared.read_bytes())
    env=plistlib.loads((Path.home()/'Library/LaunchAgents/com.lexi.v4.scheduler.plist').read_bytes())['EnvironmentVariables']
    main=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/workbench-daily-chain-20261031-r3-main/app')
    driver,_=q.authorities(main/'ops/vendor/data_layer_daily_formula_increment_update_v1.py',Path(env['V4_RESEARCH_PANEL_A_CANONICAL_FORMULA']))
    identity=q.generation_identity(snapshot,main/'ops/vendor/data_layer_daily_formula_increment_update_v1.py',Path(env['V4_RESEARCH_PANEL_A_CANONICAL_FORMULA']),Path(env['V4_RESEARCH_PANEL_A_CONTRACT_CSV']))
    currents={r:Path(v['path'])for r,v in value['baseline_roles'].items()};contracts={r:q.panel_contract(p)for r,p in currents.items()};basis=q.field_basis_contract(driver)
    if mutation=='formula':identity['formula_sha256']='0'*64
    elif mutation=='basis':snapshot['volume_basis']='wrong unit'
    elif mutation=='schema':snapshot['schema']='not the bound source schema'
    elif mutation=='calendar':
        policy=json.loads(Path(value['baseline_source_policy']['path']).read_bytes());policy['calendar']['sha256']='0'*64;p=tmp_path/'wrong_calendar.json';p.write_text(json.dumps(policy));value['baseline_source_policy']=dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    p=tmp_path/'descriptor.json';p.write_text(json.dumps(value));ref=dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest());data=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据')
    with pytest.raises(q.QfqGateError,match='SAME_ASOF_REPAIR_(BASELINE_OR_FORMULA_UNBOUND|CALENDAR_CHANGED|BASIS_CHANGED)'):
        q._same_asof_price_reuse(ref,snapshot=snapshot,contracts=contracts,currents=currents,baseline_hashes={r:v['sha256']for r,v in value['baseline_roles'].items()},identity=identity,target=20261030,journal=q.input_path(data).with_name('qfq_publication.json'),price_field_basis=basis)

@pytest.fixture(scope='module')
def actual_same_asof_recovery38():
    from ops import research_panel_qfq as q
    path=B/'execution/arrow_context_repair/CHECKPOINT_RECOVERY_CANDIDATE.json'
    if not path.exists():pytest.skip('Actual formal38 failure checkpoints not available')
    recovery=json.loads(path.read_bytes());snapshot=json.loads(q._source(recovery['original_snapshot'],owner='actual formal input').read_bytes())
    identity={**recovery['source_identity'],'adapter_sha256':q.sha(Path(q.__file__))}
    descriptor_ref=recovery['same_asof_source_repair'];descriptor=json.loads(q._source(descriptor_ref,owner='exact same-asof descriptor').read_bytes())
    currents={role:Path(value['path'])for role,value in descriptor['baseline_roles'].items()}
    contracts={role:q.panel_contract(path)for role,path in currents.items()}
    data=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据')
    journal=data/'runtime/cache/data_layer_daily_formula_increment_update_v1/qfq_publication.json'
    scope=q._same_asof_price_reuse(descriptor_ref,snapshot=snapshot,contracts=contracts,currents=currents,baseline_hashes=recovery['baseline_panel_sha256'],identity=identity,target=20261030,journal=journal,price_field_basis=next(iter(contracts.values()))['field_basis'])
    assert len(scope['codes'])==38 and len(scope['reused_codes'])==5737
    return q,path,recovery,snapshot,identity,data,scope


def test_exact38_formal_recovery_passes_real_current_dependency_binding(actual_same_asof_recovery38,tmp_path,monkeypatch):
    q,path,recovery,snapshot,identity,data,scope=actual_same_asof_recovery38
    ref=dict(path=str(path),sha256=q.sha(path))
    chunks=q.checkpoint_recovery(ref,snapshot,identity,recovery['baseline_panel_sha256'],data,same_asof=scope)
    assert set(chunks)==set(scope['codes']) and len(chunks)==38
    monkeypatch.setattr(q,'rebuild_symbol',lambda *a,**k:pytest.fail('Actual completed price checkpoint must not rebuild'))
    import pyarrow.parquet as pq
    for code in chunks:
        _,out=q._symbol_checkpoint(code,snapshot['symbols'][code],20261030,identity,tmp_path,chunks,None)
        before=pq.read_table(chunks[code]['artifact']['path']);after=pq.read_table(out)
        # Existing recovery uses a pandas round trip; pandas3 may widen string
        # offsets. Require lossless text conversion and exact valid numeric bits.
        import pyarrow as pa
        import pyarrow.compute as pc
        assert before.column_names==after.column_names
        for name in before.column_names:
            left=before[name].combine_chunks();right=after[name].combine_chunks()
            if pa.types.is_string(left.type) and pa.types.is_large_string(right.type):right=pc.cast(right,left.type,safe=True)
            assert left.type==right.type and len(left)==len(right)
            assert left.is_null().equals(right.is_null())
            if pa.types.is_floating(left.type) or pa.types.is_integer(left.type):
                assert pc.filter(left,pc.is_valid(left)).to_numpy().tobytes()==pc.filter(right,pc.is_valid(right)).to_numpy().tobytes()
            else:assert left.equals(right)
        assert q.panel_contract(out)['checkpoint_id']==q.canonical_sha(dict(code=code,item=snapshot['symbols'][code],**identity))


@pytest.mark.parametrize('mutation',['missing_code','extra_code','retry','binding','snapshot','identity','factor','kernel','artifact','fingerprint','unbound_same_asof'])
def test_exact38_formal_recovery_rejects_changed_evidence(actual_same_asof_recovery38,tmp_path,monkeypatch,mutation):
    q,_,original,snapshot,identity,data,scope=actual_same_asof_recovery38
    recovery=copy.deepcopy(original);scope=copy.deepcopy(scope)
    first=next(iter(recovery['chunks']))
    if mutation=='missing_code':recovery['chunks'].pop(first)
    elif mutation=='extra_code':recovery['chunks']['000000.SZ']=recovery['chunks'][first]
    elif mutation=='retry':recovery['retry_original_quarantined']=[first]
    elif mutation=='binding':recovery['same_asof_source_repair']['sha256']='0'*64
    elif mutation=='snapshot':recovery['original_snapshot']['sha256']='0'*64
    elif mutation=='identity':recovery['source_identity']['formula_sha256']='0'*64
    elif mutation=='factor':recovery['factor_cache_identity']='0'*64
    elif mutation=='kernel':recovery['source_core']=dict(path=str(Path(q.__file__)),sha256=q.sha(Path(q.__file__)))
    elif mutation=='artifact':recovery['chunks'][first]['artifact']['sha256']='0'*64
    elif mutation=='fingerprint':
        raw=q.panel_contract
        monkeypatch.setattr(q,'panel_contract',lambda p:{**raw(p),'checkpoint_id':'0'*64})
    elif mutation=='unbound_same_asof':scope=None
    path=tmp_path/'RECOVERY.json';path.write_text(json.dumps(recovery));ref=dict(path=str(path),sha256=q.sha(path))
    with pytest.raises((q.QfqGateError,ValueError)):
        q.checkpoint_recovery(ref,snapshot,identity,recovery['baseline_panel_sha256'],data,same_asof=scope)
