"""Bounded offline view and read-only host identity regressions."""
import gzip
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from infrastructure.research_workbench_host import ResearchWorkbenchHost
from infrastructure import research_workbench_host
from ops import materialize_generic_single_view as view


S = lambda char: char * 64


def ref(path):
    return {'path':str(path.resolve()), 'sha256':hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes':path.stat().st_size}


def put_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding='utf-8')
    return ref(path)


def fixture_data(count=3):
    generation, input_sha, n_rule, n_helper = S('a'), S('b'), S('c'), S('d')
    symbol = '600000.SH'
    left, right, diagnostics = [], [], []
    for i in range(count):
        trading_day = int((date(2024,1,1) + timedelta(days=i)).strftime('%Y%m%d'))
        row = {field:None for field in view._fields()}
        row.update(ts_code=symbol,trade_date=trading_day,name='样本',open=10.,high=11.,low=9.,close=10.5,
                   volume=123.,zge_white_line=10.123,zge_yellow_line=9.456,
                   kb_b1=i == 1,kb_hold_trend_up=None,kb_hold_trend_up_reason='INSUFFICIENT_CONFIRMED_SWINGS',
                   kb_action_no_position_status='UNKNOWN',kb_action_with_position_status='UNKNOWN',
                   kb_action_reasons='[]',kb_action_rule_sha256=S('e'),kb_yidong_rule_sha256=S('f'))
        row.update({field:None for field in view.ORIGINAL_FIELDS})
        other = {**row, 'vol':row['volume']}
        other.pop('volume')
        diag = {field:None for field in view.q.SINGLE_GAP_DIAGNOSTICS}
        diag['kb_n_structure'] = dict(state='INSUFFICIENT_CONFIRMED_SWINGS',rule_sha256=n_rule,
                                      helper_sha256=n_helper,input_sha256=input_sha,generation_id=generation)
        left.append(row);right.append(other)
        diagnostics.append(dict(ts_code=symbol,trade_date=trading_day,diagnostics_json=json.dumps(diag),prefix_input_sha256=S('1')))
    target=str(left[-1]['trade_date']);iso=f'{target[:4]}-{target[4:6]}-{target[6:]}'
    identity=dict(symbol=symbol,name='样本',source_date=iso,observation_date=iso,generation=generation,
        candidate_generation=generation,input_sha256=input_sha,candidate_input_sha256=input_sha,numeric_manifest={'sha256':S('2'),'path':'/test'},
        paired_receipt={'sha256':S('3'),'path':'/test'},pair_sha256={'selector':S('4'),'backtest':S('5')},
        diagnostics_sha256=S('6'),n_rule_sha256=n_rule,n_helper_sha256=n_helper,adjustment_convention='SYNTHETIC_TEST',
        historical_PIT=False,**view.FLAGS)
    return pa.Table.from_pylist(left),pa.Table.from_pylist(right),pa.Table.from_pylist(diagnostics),identity


def test_chunks_are_date_bound_and_do_not_fill_unknowns(tmp_path):
    left,right,diag,identity=fixture_data(513)
    result=view.build_from_verified_tables(symbol=identity['symbol'],selector=left,backtest=right,diagnostics=diag,
                                          identity=identity,output_root=tmp_path)
    binding=json.loads(Path(result['path']).read_bytes())
    assert [item['row_count'] for item in binding['chunks']]==[512,1]
    assert binding['chart']['status']=='UNKNOWN'
    assert all(item['decoded_bytes']<=8*1024*1024 and item['bytes']<=2*1024*1024 for item in binding['chunks'])
    chunk=json.loads(gzip.decompress(Path(binding['chunks'][0]['path']).read_bytes()))
    assert chunk['rows'][0][0]==binding['dates'][0]
    assert chunk['rows'][0][1][binding['field_names'].index('kb_hold_trend_up')] is None
    overlay=json.loads(gzip.decompress(Path(binding['overlay']['path']).read_bytes()))
    assert overlay['rows']==[[binding['dates'][1],['kb_b1']]]
    history_input=json.loads(gzip.decompress(Path(binding['history_input']['path']).read_bytes()))
    assert history_input['pair_sha256']==identity['pair_sha256'] and len(history_input['field_names'])==10
    assert history_input['rows'][0][0]==binding['dates'][0] and history_input['rows'][0][1]==10.5
    assert len(history_input['rows'][0][2])==10
    bad=right.set_column(right.schema.get_field_index('close'),'close',pa.array([11.0]*513))
    with pytest.raises(ValueError,match='PAIRED_FIELD_CONFLICT:close'):
        view.build_from_verified_tables(symbol=identity['symbol'],selector=left,backtest=bad,diagnostics=diag,
                                        identity=identity,output_root=tmp_path)
    bad=right.set_column(right.schema.get_field_index('user_v1_B1'),'user_v1_B1',pa.array([True]*513))
    with pytest.raises(ValueError,match='PAIRED_FIELD_CONFLICT:user_v1_B1'):
        view.build_from_verified_tables(symbol=identity['symbol'],selector=left,backtest=bad,diagnostics=diag,
                                        identity=identity,output_root=tmp_path)
    rows=diag.to_pylist(); altered=json.loads(rows[-1]['diagnostics_json']);altered['kb_n_structure']['input_sha256']=S('9')
    rows[-1]['diagnostics_json']=json.dumps(altered)
    with pytest.raises(ValueError,match='N_IDENTITY_CONFLICT'):
        view.build_from_verified_tables(symbol=identity['symbol'],selector=left,backtest=right,
            diagnostics=pa.Table.from_pylist(rows),identity=identity,output_root=tmp_path)


def test_host_binds_panel_and_per_stock_view_and_rejects_drift(tmp_path,monkeypatch):
    left,right,diag,identity=fixture_data()
    stock=view.build_from_verified_tables(symbol=identity['symbol'],selector=left,backtest=right,diagnostics=diag,
                                          identity=identity,output_root=tmp_path)
    index={'schema':'v4.workbench.generic_single_index.v1','source_date':identity['source_date'],
        'observation_date':identity['observation_date'],'source_generation':identity['generation'],
        'input_sha256':identity['input_sha256'],'candidate_generation':identity['candidate_generation'],
        'candidate_input_sha256':identity['candidate_input_sha256'],
        'numeric_manifest':identity['numeric_manifest'],'paired_receipt':identity['paired_receipt'],
        'pair_sha256':identity['pair_sha256'],'symbols':{identity['symbol']:{'status':'READY','binding':stock},
        'HK.00700':{'status':'UNKNOWN','reason':'SOURCE_GAP'}},'historical_PIT':False,**view.FLAGS}
    index_ref=put_json(tmp_path/'index.json',index)
    host=ResearchWorkbenchHost.__new__(ResearchWorkbenchHost);host.binding={'generic_single_index':index_ref}
    host._view=lambda *_:{'source_generation':identity['generation'],'source_identity':{'input_sha256':identity['input_sha256']},'manifest':identity['numeric_manifest']}
    host._observation_date=lambda *_:identity['observation_date']
    meta=host.single_stock_research(identity['source_date'],identity['symbol'],identity['generation'])
    assert meta['panel_generation']==identity['candidate_generation'] and meta['view_generation']==stock['sha256']
    assert meta['chart_status']=='UNKNOWN' and meta['rows']==3 and len(meta['field_names'])==107
    item=meta['assets']['chunk-0']
    raw,content_type=host.single_stock_asset(identity['source_date'],identity['symbol'],'chunk-0',item['sha256'],
        identity['generation'],meta['panel_generation'],meta['view_generation'])
    assert content_type=='application/octet-stream' and hashlib.sha256(raw).hexdigest()==item['sha256']
    with pytest.raises(ValueError,match='PANEL_REVISION_CONFLICT'):
        host.single_stock_research(identity['source_date'],identity['symbol'],identity['generation'],S('9'))
    with pytest.raises(ValueError,match='VIEW_REVISION_CONFLICT'):
        host.single_stock_research(identity['source_date'],identity['symbol'],identity['generation'],meta['panel_generation'],S('9'))
    hk=host.single_stock_research(identity['source_date'],'HK.00700',identity['generation'])
    assert hk['status']=='UNKNOWN_SOURCE_ADMISSION' and hk['reason']=='SOURCE_GAP'
    with pytest.raises(ValueError,match='VIEW_REVISION_CONFLICT'):
        host.single_stock_research(identity['source_date'],'HK.00700',identity['generation'],meta['panel_generation'],S('9'))
    # Exercise the real router in-process; it cannot call a producer.
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    host.classifications=SimpleNamespace(close=lambda:None)
    monkeypatch.setattr(research_workbench_host,'ResearchWorkbenchHost',lambda *_:host)
    config=put_json(tmp_path/'host-config.json',{})
    monkeypatch.setenv('V4_WORKBENCH_HOST_BINDING',config['path']);monkeypatch.setenv('V4_WORKBENCH_HOST_BINDING_SHA256',config['sha256'])
    app=FastAPI();app.include_router(research_workbench_host.create_workbench_router(None),prefix='/api/v4/research')
    with TestClient(app) as client:
        endpoint='/api/v4/research/workbench/days/'+identity['source_date']+'/single-research/'+identity['symbol']
        reply=client.get(endpoint,params={'revision':identity['generation']})
        assert reply.status_code==200 and reply.json()['view_generation']==stock['sha256']
        assert client.get(reply.json()['assets']['chunk-0']['url']).content==raw
        assert client.get(endpoint,params={'revision':identity['generation'],'panel_revision':S('9')}).status_code==409
        assert client.get(endpoint,params={'revision':identity['generation'],'view_revision':S('9')}).status_code==409
    path=Path(json.loads(Path(stock['path']).read_bytes())['chunks'][0]['path']);path.write_bytes(b'altered')
    with pytest.raises(ValueError,match='BOUNDED_SIZE_CONFLICT|SHA_DRIFT'):
        host.single_stock_asset(identity['source_date'],identity['symbol'],'chunk-0',item['sha256'],
            identity['generation'],meta['panel_generation'],meta['view_generation'])


def test_pair_completion_and_single_batch_have_required_identity(tmp_path):
    left,right,diag,identity=fixture_data()
    side_meta=dict(symbol=identity['symbol'],generation_id=identity['generation'],source_input_sha256=identity['input_sha256'],
        n_structure_enabled=True,diagnostic_keys=list(view.q.SINGLE_GAP_DIAGNOSTICS)+['kb_n_structure'],
        n_structure_contract_sha256=identity['n_rule_sha256'],n_structure_helper_sha256=identity['n_helper_sha256'],**view.FLAGS)
    side=tmp_path/'side.parquet'
    diag=diag.replace_schema_metadata({b'v4.a_share.kb_gap_diagnostics.v1':json.dumps(side_meta).encode()});pq.write_table(diag,side)
    target=identity['source_date'].replace('-','')
    footer=dict(generation_id=identity['generation'],input_sha256=identity['input_sha256'],research_scope='ADMITTED_A_SHARE',
        asof_date=target,historical_PIT=False,confirmed_gap_sidecars={identity['symbol']:ref(side)},**view.FLAGS)
    paths={};shas={}
    for role,table in [('selector',left),('backtest',right)]:
        path=tmp_path/(role+'.parquet');pq.write_table(table.replace_schema_metadata({b'a_share_qfq_contract_v1':json.dumps(footer).encode()}),path)
        paths[role]=str(path);shas[role]=ref(path)['sha256']
    baseline={'selector':S('7'),'backtest':S('8')};source_generation=S('9');source_input=S('0')
    old_proof=put_json(tmp_path/'old-proof.json',{'status':'PASS','generation_id':identity['generation'],
        'candidate_sha256':shas,'roles':{'selector':{'rows':3},'backtest':{'rows':3}}})
    lifecycle=put_json(tmp_path/'lifecycle.json',{})
    admission_proof=put_json(tmp_path/'admission.json',{'status':'CANDIDATE_1_ADMISSION_PASS','count':1,
        'generation_id':identity['generation'],'input_sha256':identity['input_sha256'],'lifecycle_resolution':lifecycle})
    receipt=dict(status='CANDIDATE_READY',generation_id=identity['generation'],input_sha256=identity['input_sha256'],
        historical_PIT=False,candidates=paths,candidate_sha256=shas,target_date=target,
        user_formula_sha256=S('2'),kb_field_contract_sha256=S('3'),
        old_arrow_equivalence=old_proof,lifecycle_resolution=lifecycle,
        baseline_panel_sha256=baseline,materialized_reuse_source_input_sha256=source_input,
        kb_initial_upgrade={'source_generation_id':source_generation,'baseline_panel_sha256':baseline},**view.FLAGS)
    receipt_ref=put_json(tmp_path/'receipt.json',receipt)
    numeric_ref=put_json(tmp_path/'numeric.json',dict(source_generation=source_generation,input_sha256=source_input,
        data_date=target,status='PARTIAL_WITH_ROWS',**view.FLAGS))
    out=tmp_path/'output';out.mkdir()
    attestation={'schema':'v4.a_share.paired_candidate_attestation.v1','status':'PASS','generation_id':identity['generation'],
        'input_sha256':identity['input_sha256'],'candidate_receipt':receipt_ref,'candidate_receipt_sha256':receipt_ref['sha256'],
        'old_arrow_equivalence':{'status':'PASS','ref':old_proof},'lifecycle_resolution':lifecycle,
        'lifecycle_admission':{'status':'CANDIDATE_1_ADMISSION_PASS','count':1,'ref':admission_proof},
        'sidecar_coverage':{'count':1,'n_checkpoints':1},'historical_PIT':False,**view.FLAGS,
        'roles':{role:{'path':paths[role],'sha256':shas[role],'stat':view._stat(paths[role]),'rows':3,
                       'columns':len(pq.ParquetFile(paths[role]).schema_arrow)} for role in paths}}
    attestation_ref=put_json(tmp_path/'attestation.json',attestation)
    with pytest.raises(ValueError,match='PAIR_ATTESTATION_REQUIRED'):
        view.materialize_verified_pair(paired_receipt_ref=receipt_ref,numeric_manifest_ref=numeric_ref,
            symbols=[identity['symbol']],output_root=out,observation_date=identity['observation_date'])
    idx,results=view.materialize_verified_pair(paired_receipt_ref=receipt_ref,numeric_manifest_ref=numeric_ref,
        symbols=[identity['symbol'],'000001.SZ'],output_root=out,observation_date=identity['observation_date'],verified_pair_ref=attestation_ref)
    assert results[identity['symbol']]['status']=='READY',results
    assert results['000001.SZ']=={'status':'UNKNOWN','reason':'PAIRED_SYMBOL_NOT_PRESENT'}
    index=json.loads(Path(idx['path']).read_bytes())
    assert index['pair_sha256']==shas and index['source_generation']==source_generation
    assert index['candidate_generation']==identity['generation'] and index['candidate_input_sha256']==identity['input_sha256']
    producer=ref(Path(view.__file__).resolve())
    frozen=index['projection_producer']
    assert frozen['sha256']==frozen['source_sha256']==producer['sha256'] and frozen['source_path']==producer['path']
    assert Path(frozen['path']).read_bytes()==Path(producer['path']).read_bytes()
    old_binding_ref=index['symbols'][identity['symbol']]['binding']
    old_binding=json.loads(Path(old_binding_ref['path']).read_bytes())
    calendar=put_json(tmp_path/'paired-calendar.json',{'schema':'D222_PER_EXCHANGE_SOURCE_CALENDAR_V1',
        'source_generation':source_generation,'input_sha256':source_input,'panel_sha256':baseline['selector'],
        'asof_date':target,'dates':{'SH':[20240101,20240102,20240103]},'historical_PIT':False,**view.FLAGS})
    owner_path=tmp_path/'history_owner.py';owner_path.write_text('# synthetic owner\n');owner=ref(owner_path)
    groups=[]
    for group,namespace,field in view.HISTORY_FIELDS:
        rule=hashlib.sha256(view._canonical({'namespace':namespace,'field':field,'source_view_sha256':old_binding['history_input']['sha256']})).hexdigest()
        groups.append({'group_id':group,'identity_status':'BOUND','rule_sha256':rule,'coverage':{'namespace':namespace,'field':field,
            'known_dates':1,'unknown_dates':2},'source_identity':{'rule_sha256':rule,'generation':source_generation,
            'input':source_input,'market':'SH','calendar_sha256':calendar['sha256'],'asof':identity['source_date'],
            'basis':'QFQ','pit_status':'NONPIT','formula':S('2') if namespace=='original' else S('3')}})
    shard={'schema_version':'v4.a_share.event_cases.paired_research.v1','symbol':identity['symbol'],
        'data_date':target,'observation_date':identity['observation_date'],'source_generation':source_generation,
        'input_sha256':source_input,'source_candidate_generation':identity['generation'],'candidate_input_sha256':identity['input_sha256'],
        'numeric_manifest':numeric_ref,'paired_receipt':receipt_ref,'verified_pair':attestation_ref,'projection_index':idx,
        'projection_binding':old_binding_ref,'history_input':old_binding['history_input'],'producer_sha256':owner['sha256'],
        'market_calendar':calendar,'statistics':{'groups':groups},
        'historical_PIT':False,**view.FLAGS}
    shard_ref=put_json(tmp_path/'history-shard.json',shard)
    amended,outcomes=view.bind_retained_pair_history(index_ref=idx,history_refs={identity['symbol']:shard_ref},
        history_producer_ref=owner,output_root=out)
    assert outcomes[identity['symbol']]['status']=='READY'
    amended_value=json.loads(Path(amended['path']).read_bytes())
    amended_binding=json.loads(Path(amended_value['symbols'][identity['symbol']]['binding']['path']).read_bytes())
    assert amended_binding['chunks']==old_binding['chunks'] and amended_binding['chart']==old_binding['chart']
    assert amended_binding['details']['history']['source_candidate_generation']==identity['generation']
    assert json.loads(Path(idx['path']).read_bytes())['symbols'][identity['symbol']]['binding']==old_binding_ref
    base_value=json.loads(Path(amended['path']).read_bytes());base_value['symbols'][identity['symbol']]={'status':'UNKNOWN','reason':'RETRY'}
    base_ref=put_json(tmp_path/'merge-base.json',base_value)
    repair_value=json.loads(Path(idx['path']).read_bytes());repair_value['symbols']={identity['symbol']:repair_value['symbols'][identity['symbol']]}
    repair_ref=put_json(tmp_path/'merge-repair.json',repair_value)
    merged_ref=view.merge_same_pair_indexes(base_index_ref=base_ref,repair_index_ref=repair_ref,output_root=out)
    merged=json.loads(Path(merged_ref['path']).read_bytes());entry=merged['symbols'][identity['symbol']]
    assert entry['status']=='READY' and entry['projection_source_index']==repair_ref and merged['projection_producer'] is None
    assert json.loads(Path(entry['binding']['path']).read_bytes())['chunks']==old_binding['chunks']
    with pytest.raises(ValueError,match='MERGE_SYMBOL_CONFLICT'):
        view.merge_same_pair_indexes(base_index_ref=amended,repair_index_ref=repair_ref,output_root=out)
    bad_calendar=put_json(tmp_path/'bad-calendar.json',{'schema':'D222_PER_EXCHANGE_SOURCE_CALENDAR_V1',
        'source_generation':source_generation,'input_sha256':source_input,'panel_sha256':baseline['selector'],
        'asof_date':target,'dates':{'SZ':[20240101]},'historical_PIT':False,**view.FLAGS})
    shard['market_calendar']=bad_calendar;bad_shard=put_json(tmp_path/'bad-shard.json',shard)
    _,failed=view.bind_retained_pair_history(index_ref=idx,history_refs={identity['symbol']:bad_shard},
        history_producer_ref=owner,output_root=out)
    assert failed[identity['symbol']]['status']=='UNKNOWN' and 'CALENDAR_CONFLICT' in failed[identity['symbol']]['reason']
    attested,_=view.materialize_verified_pair(paired_receipt_ref=receipt_ref,numeric_manifest_ref=numeric_ref,
        symbols=[identity['symbol']],output_root=out,observation_date=identity['observation_date'],verified_pair_ref=attestation_ref)
    assert json.loads(Path(attested['path']).read_bytes())['verified_pair']==attestation_ref
    attestation['roles']['selector']['stat']['size']+=1
    bad_attestation=put_json(tmp_path/'bad-attestation.json',attestation)
    with pytest.raises(ValueError,match='PAIR_ATTESTATION_ROLE_CONFLICT'):
        view.materialize_verified_pair(paired_receipt_ref=receipt_ref,numeric_manifest_ref=numeric_ref,
            symbols=[identity['symbol']],output_root=out,observation_date=identity['observation_date'],verified_pair_ref=bad_attestation)
    wrong=put_json(tmp_path/'wrong-numeric.json',dict(source_generation=source_generation,input_sha256=S('8'),
        data_date=target,status='PARTIAL_WITH_ROWS',**view.FLAGS))
    with pytest.raises(ValueError,match='BASELINE_LINEAGE_CONFLICT'):
        view.materialize_verified_pair(paired_receipt_ref=receipt_ref,numeric_manifest_ref=wrong,
            symbols=[identity['symbol']],output_root=out,observation_date=identity['observation_date'],verified_pair_ref=attestation_ref)
    receipt['status']='CHECKPOINT_ONLY';bad=put_json(tmp_path/'not-pair.json',receipt)
    with pytest.raises(ValueError,match='PAIR_RECEIPT_IDENTITY_CONFLICT'):
        view.materialize_verified_pair(paired_receipt_ref=bad,numeric_manifest_ref=numeric_ref,
            symbols=[identity['symbol']],output_root=out,observation_date=identity['observation_date'],verified_pair_ref=attestation_ref)


def test_gzip_decoding_is_bounded(tmp_path):
    compressed=tmp_path/'large.gz';compressed.write_bytes(gzip.compress(b'x'*1025,mtime=0))
    with pytest.raises(ValueError,match='DECODED_SIZE_LIMIT'):
        view._bounded_gzip(ref(compressed),maximum=1024,compressed_maximum=2048)


def test_reused_n_keeps_original_identity_and_requires_same_sidecar(tmp_path):
    _,_,side,identity=fixture_data();source_gen,source_input,snapshot=S('9'),S('0'),S('8')
    baseline={'selector':S('7'),'backtest':S('6')};prior_identity={'symbol':identity['symbol'],
        'source_generation':source_gen,'source_input_sha256':source_input,'baseline_panel_sha256':baseline}
    prior_generation=view.q.canonical_sha(prior_identity)
    prior_side_path=tmp_path/'prior-side.parquet';pq.write_table(side,prior_side_path);prior_side=ref(prior_side_path)
    checkpoint=put_json(tmp_path/'n-checkpoint.json',{'symbol':identity['symbol'],'history_bar_count':side.num_rows,
        'identity':{'generation_id':source_gen,'input_sha256':source_input,'rule_sha256':identity['n_rule_sha256'],
          'helper_sha256':identity['n_helper_sha256'],'price_basis':'QFQ_ASOF','calendar_sha256':None,'price_basis_sha256':None}})
    candidate=put_json(tmp_path/'prior-candidate.json',{'candidate_identity':prior_identity,'candidate_generation':prior_generation,
        'confirmed_gap':{'diagnostics':prior_side},'n_structure':{'checkpoint':checkpoint}})
    descriptor=put_json(tmp_path/'reuse.json',{'schema':'a_share_materialized_reuse_v1','stocks':{identity['symbol']:candidate},
        'source_generation':source_gen,'source_input_sha256':source_input,'snapshot_sha256':snapshot,'baseline_panel_sha256':baseline})
    n_ref={**checkpoint,'source_generation':source_gen,'resume_across_generation':False}
    receipt={'generation_id':identity['candidate_generation'],'input_sha256':identity['candidate_input_sha256'],
        'materialized_reuse_refs':{identity['symbol']:candidate},'materialized_reuse_descriptor':descriptor,
        'materialized_reuse_descriptor_sha256':descriptor['sha256'],'materialized_reuse_source_generation':source_gen,
        'materialized_reuse_source_input_sha256':source_input,'materialized_reuse_source_snapshot_sha256':snapshot,
        'baseline_panel_sha256':baseline,'n_structure_checkpoints':{identity['symbol']:n_ref}}
    meta={'materialized_source_candidate_generation':prior_generation,'materialized_source_input_sha256':source_input,
        'materialized_source_snapshot_sha256':snapshot,'source_generation':source_gen,'n_checkpoint_resume_across_generation':False,
        'n_structure_contract_sha256':identity['n_rule_sha256'],'n_structure_helper_sha256':identity['n_helper_sha256']}
    result=view._n_sidecar_identity(receipt,meta,side,identity['symbol'])
    assert result['n_identity_kind']=='MATERIALIZED_REUSE' and result['n_generation_id']==source_gen and result['n_input_sha256']==source_input
    with pytest.raises(ValueError,match='REUSE_SIDECAR_ROWS_CONFLICT'):
        view._n_sidecar_identity(receipt,meta,side.slice(0,2),identity['symbol'])
    receipt['n_structure_checkpoints'][identity['symbol']]['resume_across_generation']=True
    with pytest.raises(ValueError,match='REUSE_CHECKPOINT_CONFLICT'):
        view._n_sidecar_identity(receipt,meta,side,identity['symbol'])


def test_retained_details_keep_old_version_and_check_individual_sources(tmp_path):
    left,right,diag,identity=fixture_data()
    identity.update(kb_authority_sha256=S('7'),kb_field_contract_sha256=S('8'),baseline_panel_sha256={'selector':S('9')})
    old_rows=left.to_pylist();old_generation=S('6')
    old_view={'symbol':identity['symbol'],'candidate_generation':old_generation,'source_generation':identity['generation'],
        'source_input_sha256':identity['input_sha256'],'authority_sha256':S('7'),'field_contract_sha256':S('8'),
        'historical_PIT':False,**view.FLAGS,
        'rows':[{'trade_date':row['trade_date'],**{namespace:{field:row[field] for _,ns,field in view.HISTORY_FIELDS if ns==namespace}
                  for namespace in ('kb','original')}} for row in old_rows]}
    old_view_path=tmp_path/'old-view.gz';old_view_path.write_bytes(gzip.compress(json.dumps(old_view).encode(),mtime=0));old_view_ref=ref(old_view_path)
    old_selector=tmp_path/'old-selector.parquet';pq.write_table(left,old_selector);selector_ref=ref(old_selector)
    old_binding=put_json(tmp_path/'old-binding.json',{'symbol':identity['symbol'],'candidate_generation':old_generation,
        'candidate_identity':{'formula_sha256':view.renderer.FORMULA_SHA,'formula_engine_sha256':view.renderer.ENGINE_SHA},
        'assets':{'kb':old_view_ref}})
    candidate=put_json(tmp_path/'old-candidate.json',{'candidate_generation':old_generation,'binding':old_binding,'outputs':{'selector':selector_ref}})
    calendar=put_json(tmp_path/'calendar.json',{'schema':'v4.single_stock_same_market_calendar.v1','exchange':'SH',
        'asof':identity['source_date'],'source_panel_sha256':S('9')})
    groups=[]
    for group,namespace,field in view.HISTORY_FIELDS:
        rule=hashlib.sha256(view._canonical({'namespace':namespace,'field':field,'source_view_sha256':old_view_ref['sha256']})).hexdigest()
        groups.append({'group_id':group,'identity_status':'BOUND','rule_sha256':rule,'source_identity':{'rule_sha256':rule,
            'generation':identity['generation'],'input':identity['input_sha256'],'market':'SH',
            'formula':view.renderer.FORMULA_SHA if namespace=='original' else S('8')}})
    history={'schema_version':'v4.a_share.event_cases.single_research.v1','symbol':identity['symbol'],
        'data_date':identity['source_date'].replace('-',''),'source_generation':identity['generation'],
        'input_sha256':identity['input_sha256'],'numeric_manifest':identity['numeric_manifest'],'producer_sha256':S('4'),
        'source_candidate_generation':old_generation,'source_candidate':candidate,'source_selector':selector_ref,
        'source_view':old_view_ref,'market_calendar':calendar,'statistics':{'groups':groups},'historical_PIT':False,**view.FLAGS}
    history_path=tmp_path/'history.gz';history_path.write_bytes(gzip.compress(json.dumps(history).encode(),mtime=0));history_ref=ref(history_path)
    received=put_json(tmp_path/'received.json',{});doc=tmp_path/'verified.pdf';doc.write_bytes(b'original')
    missing={'path':str(tmp_path/'missing.pdf'),'sha256':S('1')}
    company={'schema_version':'v4.a_share.company_materials.v1','symbol':identity['symbol'],
        'data_date':identity['source_date'].replace('-',''),'source_generation':identity['generation'],
        'input_sha256':identity['input_sha256'],'numeric_manifest':identity['numeric_manifest'],'producer_sha256':S('5'),
        'source_candidate_generation':old_generation,'source_candidate':candidate,'received_ref':received,
        'source_refs':{'official_quarterly':{'file':ref(doc)},'broker_research':{'file':missing}},
        'historical_PIT':False,**view.FLAGS}
    company_path=tmp_path/'company.gz';company_path.write_bytes(gzip.compress(json.dumps(company).encode(),mtime=0));company_ref=ref(company_path)
    retained=put_json(tmp_path/'retained.json',{'symbol':identity['symbol'],'source_date':identity['source_date'],
        'source_generation':identity['generation'],'source_input_sha256':identity['input_sha256'],
        'numeric_manifest':identity['numeric_manifest'],'assets':{'history':history_ref,'company':company_ref},
        'candidate_identity':{'source_sha256':{'ops/bootstrap_stock_event_history.py':S('4'),'ops/research_panel_daily_product.py':S('5')}},
        'historical_PIT':False,**view.FLAGS})
    result=view.build_from_verified_tables(symbol=identity['symbol'],selector=left,backtest=right,diagnostics=diag,
        identity=identity,output_root=tmp_path,retained_details={'binding':retained})
    details=json.loads(Path(result['path']).read_bytes())['details']
    assert details['history']['status']=='READY' and details['history']['source_candidate_generation']==old_generation
    assert details['company']['source_checks']=={'official_quarterly':'VERIFIED','broker_research':'UNKNOWN'}
    changed=list(old_rows);changed[0]={**changed[0],'kb_b1':not changed[0]['kb_b1']}
    with pytest.raises(ValueError,match='HISTORY_LABEL_CONFLICT'):
        view._retained_history(history_ref,identity,changed,S('4'))


def test_f10_partial_keeps_verified_component_and_rejects_wrong_identity(tmp_path):
    symbol='920001.BJ';generation=S('a');input_sha=S('b');day='2026-10-30';text='◇920001 纬达光电 更新日期：2026-10-30\n已核原文'
    partial={'symbol':symbol,'exchange':'BJ','status':'PARTIAL','captured_at':'2026-11-02T01:02:03+00:00',
        'source_components':{'text':{'status':'OBSERVED','market':0,'source_text':text,
            'source_text_sha256':hashlib.sha256(text.encode()).hexdigest()},'finance':{'status':'UNKNOWN','reason':'SOURCE_GAP'}},
        'historical_PIT':False,**view.FLAGS}
    checkpoint=put_json(tmp_path/'checkpoint.json',{'identity':{'data_date':'20261030','source_generation':generation,'input_sha256':input_sha},'items':{}})
    def bind(value):
        artifact=put_json(tmp_path/'partial.json',value)
        receipt=put_json(tmp_path/'receipt.json',{'schema':'v4.a_share.f10_daily_receipt.v1','data_date':'20261030',
            'source_generation':generation,'input_sha256':input_sha,'status':'PARTIAL','checkpoint':checkpoint,
            'failures':{symbol:{'status':'PARTIAL','artifact':artifact}}})
        put_json(tmp_path/'index.json',{'f10':{'20261030':receipt}})
    bind(partial)
    host=ResearchWorkbenchHost.__new__(ResearchWorkbenchHost)
    host._view=lambda *_:{'source_generation':generation,'source_identity':{'input_sha256':input_sha},'rows':[{'symbol':symbol}]}
    host.source=SimpleNamespace(_a_product_root=lambda:tmp_path,
        _a_product_reference=lambda reference:research_workbench_host.checked_bounded(reference,2*1024*1024))
    answer=host.f10(day,symbol,generation)
    assert answer['status']=='PARTIAL_SOURCE_COMPONENTS' and answer['source_components']['text']['source_text']==text
    assert answer['source_components']['finance']=={'status':'UNKNOWN','reason':'SOURCE_GAP'}
    finance_only=json.loads(json.dumps(partial));finance_only['source_components']={'text':{'status':'UNKNOWN','reason':'TEXT_GAP'},
        'finance':{'status':'OBSERVED','market':2,'finance_native_raw':{'code':'920001','market':2,'gudongrenshu':1234}}}
    bind(finance_only);answer=host.f10(day,symbol,generation)
    assert answer['source_components']['finance']['finance_native_raw']['gudongrenshu']==1234
    assert answer['source_components']['text']=={'status':'UNKNOWN','reason':'TEXT_GAP'}
    invalid=json.loads(json.dumps(finance_only));invalid['source_components']['finance']['finance_native_raw']['code']='920000';bind(invalid)
    with pytest.raises(ValueError,match='PARTIAL_FINANCE_CONFLICT'):host.f10(day,symbol,generation)
    invalid=json.loads(json.dumps(partial));invalid['source_components']['text']['market']=2;bind(invalid)
    with pytest.raises(ValueError,match='COMPONENT_MARKET_CONFLICT'):host.f10(day,symbol,generation)
    invalid=json.loads(json.dumps(partial));invalid['source_components']['text']['source_text']='◇999999 错误 更新日期：2026-10-30';bind(invalid)
    with pytest.raises(ValueError,match='PARTIAL_TEXT_CONFLICT'):host.f10(day,symbol,generation)


def test_hk_raw_observation_keeps_missing_session_and_excluded_day(tmp_path,monkeypatch):
    basic=put_json(tmp_path/'original.json',{})
    source={'schema':'v4.hk_connect.materialized_symbol_index.v2','status':'ISOLATED_READ_ONLY_PARTIAL',
        'identity':{'source_date':'20261030','target_date':'20261102','source_panel':{'sha256':S('a')},
            'input_snapshot':basic,'snapshot':basic,'owner_receipt':basic,'membership_asof_audit':basic,
            'calendar_sha256':S('b'),'guard_sha256':S('c'),'input_batch_sha256':S('d')},
        'rows':[{'symbol':'HK.00001','name':'长和','source_date':'20261030','target_date':'20261102',
            'target_formal_eligibility_status':'CANNOT_CONFIRM','decision_reason':'CONNECT_MEMBERSHIP_NOT_VERIFIED',
            'raw_values_status':'OBSERVED_RAW_FIELDS_ONLY_UNITS_BASIS_PIT_NOT_PROVEN',
            'raw_20261030_ohlc_trade_amount':{'open':1,'high':2,'low':1,'close':2,'trade':None,'amount':None},
            'raw_reconcile_row_sha256':S('e'),'missing_sessions':['20261005']},
          {'symbol':'HK.00853','source_date':'20261030','target_date':'20261102',
            'target_formal_eligibility_status':'CANNOT_CONFIRM','decision_reason':'TARGET_SNAPSHOT_EXCLUDED',
            'raw_20261030_ohlc_trade_amount':None}],**view.FLAGS}
    source_ref=put_json(tmp_path/'hk-index.json',source)
    receipt_ref=put_json(tmp_path/'hk-receipt.json',{'schema':'v4.hk_connect.materialized_symbol_index_receipt.v2',
        'status':'READ_ONLY_DATE_SEMANTICS_VERIFIED','index':source_ref,**view.FLAGS})
    def response(symbol,day,raw):
        row={'date':day,'symbol':symbol,'raw_fields':raw,'source':'B','source_sha256':S('a'),'row_sha256':S('e'),
            'research_only':True,'scoring_allowed':False,'units_status':'UNKNOWN','adjustment_basis_status':'UNKNOWN',
            'currency_basis_status':'UNKNOWN','pit_safety_status':'UNKNOWN'}
        return {'status_code':200,'body':{'state':'READY','data':{'owner_snapshot':{'panel_sha256':S('a')},'rows':[row]},**view.FLAGS}}
    responses={'history_HK.00001':response('HK.00001','20261030',{'code_norm':'HK.00001','open':1,'high':2,'low':1,'close':2,'trade':None,'amount':None}),
               'history_HK.00853':response('HK.00853','20260911',{'code':'HK.00853','open':1,'high':1,'low':1,'close':1,'trade':0,'amount':0})}
    response_ref=put_json(tmp_path/'hk-responses.json',responses)
    index_ref,result=view.materialize_hk_observations(index_ref=source_ref,receipt_ref=receipt_ref,
        history_response_ref=response_ref,symbols=['HK.00001','HK.00853'],output_root=tmp_path)
    assert all(item['status']=='READY' for item in result.values())
    observed=json.loads(gzip.decompress(Path(result['HK.00001']['asset']['path']).read_bytes()))
    excluded=json.loads(gzip.decompress(Path(result['HK.00853']['asset']['path']).read_bytes()))
    assert observed['history'][0]['raw_fields']['trade'] is None and observed['missing_sessions']==['20261005']
    assert excluded['decision_reason']=='TARGET_SNAPSHOT_EXCLUDED' and excluded['raw_source_day'] is None
    assert excluded['history'][0]['date']=='20260911' and excluded['history'][0]['raw_fields']['trade']==0
    assert all(x['target_formal_eligibility_status']=='CANNOT_CONFIRM' and x['chart_status']=='UNKNOWN_NOT_SUPPLIED' for x in (observed,excluded))
    host=ResearchWorkbenchHost.__new__(ResearchWorkbenchHost);host.binding={'hk_single_observation_index':index_ref}
    host._view=lambda *_:{'source_generation':S('1'),'source_identity':{'input_sha256':S('2')},'manifest':{'path':'/test','sha256':S('3')}}
    host._observation_date=lambda *_:'2026-11-02'
    meta=host.single_stock_research('2026-10-30','HK.00853',S('1'))
    item=meta['assets']['observation']
    raw,kind=host.single_stock_asset('2026-10-30','HK.00853','observation',item['sha256'],S('1'),meta['panel_generation'],meta['view_generation'])
    assert kind=='application/octet-stream' and json.loads(gzip.decompress(raw))['raw_source_day'] is None
    assert meta['status']=='READY_RAW_OBSERVATION_ONLY'
    with pytest.raises(ValueError,match='REVISION_CONFLICT'):
        host.single_stock_research('2026-10-30','HK.00853',S('1'),S('9'))
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    host.classifications=SimpleNamespace(close=lambda:None)
    monkeypatch.setattr(research_workbench_host,'ResearchWorkbenchHost',lambda *_:host)
    config=put_json(tmp_path/'hk-host-config.json',{})
    monkeypatch.setenv('V4_WORKBENCH_HOST_BINDING',config['path']);monkeypatch.setenv('V4_WORKBENCH_HOST_BINDING_SHA256',config['sha256'])
    app=FastAPI();app.include_router(research_workbench_host.create_workbench_router(None),prefix='/api/v4/research')
    with TestClient(app) as client:
        endpoint='/api/v4/research/workbench/days/2026-10-30/single-research/HK.00853'
        reply=client.get(endpoint,params={'revision':S('1')})
        assert reply.status_code==200 and reply.json()['status']=='READY_RAW_OBSERVATION_ONLY'
        assert client.get(reply.json()['assets']['observation']['url']).content==raw
        assert client.get(endpoint,params={'revision':S('1'),'view_revision':S('9')}).status_code==409
    responses['history_HK.00001']['body']['data']['rows'][0]['raw_fields']['code_norm']='HK.00700'
    bad_response=put_json(tmp_path/'hk-wrong-symbol.json',responses)
    _,partial=view.materialize_hk_observations(index_ref=source_ref,receipt_ref=receipt_ref,
        history_response_ref=bad_response,symbols=['HK.00001','HK.00853'],output_root=tmp_path)
    assert partial['HK.00001']['status']=='UNKNOWN' and partial['HK.00001']['reason']=='HK_HISTORY_ROW_CONFLICT'
    assert partial['HK.00853']['status']=='READY'


def test_missing_chart_uses_existing_owner_with_paired_symbol_lineage(tmp_path):
    root=Path('/Users/lexi/Desktop/学习/agents调试/Z哥方法论/bot216_prefilter_handoff_20261026/original/source_engine/panel_rebuild_20261023/formula')
    engine,formula=root/'formula_engine.py',root/'USER_MAIN_CHART_FORMULA_MESSAGE_EXACT_UTF8.txt'
    if not all(p.exists() for p in (engine,formula,Path(view.renderer.OWNER_RENDERER['path']))):
        pytest.skip('pinned original owner assets are unavailable')
    config=put_json(tmp_path/'engine.json',{'engine':ref(engine),'formula':ref(formula)})
    left,right,diag,identity=fixture_data(20)
    result=view.build_from_verified_tables(symbol=identity['symbol'],selector=left,backtest=right,diagnostics=diag,
        identity=identity,output_root=tmp_path,engine_config_ref=config)
    binding=json.loads(Path(result['path']).read_bytes());assert binding['chart']['status']=='READY',binding['chart']
    projection=json.loads(gzip.decompress(Path(binding['chart']['projection']['path']).read_bytes()))
    assert (projection['formula_result']['field_count'],projection['formula_result']['drawing_count'])==(51,22)
    assert projection['product_row_ref']['symbol']==identity['symbol']
    assert projection['product_row_ref']['selector_sha256']==identity['pair_sha256']['selector']
    html=Path(binding['chart']['html']['path']).read_text()
    assert 'ORIGINAL_CHART_SIZE_CONFLICT' in html and 'new Response(stream).text()' not in html
    new_close=pa.array([10.6]*len(left))
    changed_left=left.set_column(left.schema.get_field_index('close'),'close',new_close)
    changed_right=right.set_column(right.schema.get_field_index('close'),'close',new_close)
    rebuilt=view.build_from_verified_tables(symbol=identity['symbol'],selector=changed_left,backtest=changed_right,diagnostics=diag,
        identity=identity,output_root=tmp_path,engine_config_ref=config,original_projection_ref=binding['chart']['projection'])
    after=json.loads(Path(rebuilt['path']).read_bytes());assert after['chart']['status']=='READY'
    projection=json.loads(gzip.decompress(Path(after['chart']['projection']['path']).read_bytes()))
    assert 'ORIGINAL_OHLCV_CONFLICT:close' in projection['lineage']['source_projection_rejected']['reason']
    corrupted={**binding['chart']['projection'],'sha256':S('0')}
    rejected=view.build_from_verified_tables(symbol=identity['symbol'],selector=left,backtest=right,diagnostics=diag,
        identity=identity,output_root=tmp_path,engine_config_ref=config,original_projection_ref=corrupted)
    value=json.loads(Path(rejected['path']).read_bytes());assert value['rows']==20 and value['chart']['status']=='UNKNOWN'
    assert 'REFERENCE_SHA_DRIFT' in value['chart']['reason']
