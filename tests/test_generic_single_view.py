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


def fixture_action_rebind(tmp_path,*,overlay_dates=(20240101,),affected=None,old_reasons='[]',overlay_symbol=None,selector_non_action=334):
    left,right,diag,identity=fixture_data();origin_root=tmp_path/'origin';origin_root.mkdir()
    output=tmp_path/'output';output.mkdir();symbol=identity['symbol']
    old_pair={};new_pair={};paths={}
    for side,collection in (('old',old_pair),('new',new_pair)):
        paths[side]={}
        for role in ('selector','backtest'):
            path=origin_root/(side+'-'+role+'.parquet');path.write_bytes((side+'-'+role).encode())
            paths[side][role]=str(path);collection[role]=ref(path)['sha256']
    def receipt(generation,input_sha,pair,side):
        return dict(status='CANDIDATE_READY',generation_id=generation,input_sha256=input_sha,
                    candidates=paths[side],candidate_sha256=pair,target_date='20240103',historical_PIT=False,**view.FLAGS)
    old_receipt=put_json(origin_root/'old-receipt.json',receipt(S('a'),S('b'),old_pair,'old'))
    def attestation(generation,input_sha,pair,side,receipt_ref,**extra):
        return dict(schema='v4.a_share.paired_candidate_attestation.v1',status='PASS',generation_id=generation,
                    input_sha256=input_sha,candidate_receipt=receipt_ref,candidate_receipt_sha256=receipt_ref['sha256'],
                    roles={role:dict(path=paths[side][role],sha256=pair[role],stat=view._stat(paths[side][role]),
                                     rows=3,columns=340 if role=='selector' else 192,
                                     footer_generation_id=generation,footer_input_sha256=input_sha) for role in pair},
                    historical_PIT=False,**extra,**view.FLAGS)
    old_att=put_json(origin_root/'old-att.json',attestation(S('a'),S('b'),old_pair,'old',old_receipt))
    identity.update(paired_receipt=old_receipt,pair_sha256=old_pair)
    old_binding=view.build_from_verified_tables(symbol=symbol,selector=left,backtest=right,diagnostics=diag,
                                                 identity=identity,output_root=origin_root)
    old_index={'schema':'v4.workbench.generic_single_index.v1','source_date':identity['source_date'],
        'observation_date':identity['observation_date'],'source_generation':identity['generation'],
        'input_sha256':identity['input_sha256'],'candidate_generation':S('a'),'candidate_input_sha256':S('b'),
        'numeric_manifest':identity['numeric_manifest'],'paired_receipt':old_receipt,'verified_pair':old_att,
        'pair_sha256':old_pair,'symbols':{symbol:{'status':'READY','binding':old_binding}},'historical_PIT':False,**view.FLAGS}
    old_index_ref=put_json(origin_root/'old-index.json',old_index)
    changed=len(overlay_dates) if affected is None else affected
    overlay_ref=None
    if overlay_dates:
        old=[None,'UNKNOWN',None,'UNKNOWN',old_reasons,S('e')]
        new=[None,'UNKNOWN',None,'CONFLICTING_OBSERVATIONS','["冲突"]',S('e')]
        rows=[]
        for date_value in overlay_dates:
            row={'ts_code':overlay_symbol or symbol,'trade_date':date_value}
            for field,before,after in zip(view.ACTION_REBIND_FIELDS,old,new):row['old__'+field]=before;row['new__'+field]=after
            rows.append(row)
        table=pa.Table.from_pylist(rows).replace_schema_metadata({b'scope':b'ACTION_DELTA_NOT_A_PANEL',
            b'old_candidate_generation':S('a').encode(),b'old_action_authority_sha256':S('8').encode(),
            b'new_action_authority_sha256':S('9').encode()})
        path=origin_root/'action.parquet';pq.write_table(table,path);overlay_ref=ref(path)
    changed_fields={field:(changed if field in {'kb_action_reasons','kb_action_with_position_status'} else 0)
                    for field in view.ACTION_REBIND_FIELDS}
    stock_receipt=put_json(origin_root/'stock-receipt.json',{'symbol':symbol,'rows':3,'affected_rows':changed,
                                                            'changed_fields':changed_fields,'overlay':overlay_ref})
    stock_index=put_json(origin_root/'stock-index.json',{symbol:{'rows':3,'first_date':20240101,'last_date':20240103,
        'target_row_present':True,'affected_rows':changed,'changed_fields':changed_fields,
        'stock_receipt':stock_receipt,'overlay':overlay_ref}})
    summary=put_json(origin_root/'summary.json',{'schema':'v4.a_share.action_delta_summary.v1','status':'ACTION_DELTA_READY_NOT_PAIRED',
        'old_candidate_generation':S('a'),'input_sha256':S('b'),'old_pair_sha256':old_pair,'source_candidate':old_receipt,
        'source_attestation':old_att,'action_fields':list(view.ACTION_REBIND_FIELDS),'old_action_authority_sha256':S('8'),
        'action_authority':{'sha256':S('9')},'action_rule_contract_sha256':S('e'),'stock_index':stock_index,'stock_count':1,
        'target_rows':1,'target_date':20240103,'changed_rows':changed,'changed_stock_count':int(changed>0),
        'changed_field_counts':changed_fields,'historical_PIT':False,**view.FLAGS})
    proof=put_json(origin_root/'equivalence.json',{'schema':'v4.a_share.action_correction_equivalence.v1',
        'status':'PASS','generation_id':S('7'),'input_sha256':S('6'),
        'baseline_generation_id':S('a'),'baseline_panel_sha256':old_pair,'candidate_sha256':new_pair,'target_date':'20240103',
        'action_delta_summary':summary,'unchanged_scope':'ALL_NON_ACTION_ARROW_COLUMNS_KEYS_TYPES_NULL_NAN_AND_SIGNED_ZERO',
        'inherited_sidecars_source_generation':S('a'),'cross_generation_n_checkpoint_reused':False,
        'roles':{role:{'status':'PASS','rows':3,'non_action_columns_exact':selector_non_action if role=='selector' else 186,
                       'action_columns_match_bound_delta':6,'applied_rows':changed,'affected_stocks':int(changed>0)} for role in old_pair},
        'historical_PIT':False,**view.FLAGS})
    new=receipt(S('7'),S('6'),new_pair,'new')
    new.update(action_correction={'source_generation':S('a'),'sidecar_source_generation':S('a'),'summary':summary,
        'old_authority_sha256':S('8'),'new_authority_sha256':S('9')},action_correction_equivalence=proof)
    new_receipt=put_json(origin_root/'new-receipt.json',new)
    new_att=put_json(origin_root/'new-att.json',attestation(S('7'),S('6'),new_pair,'new',new_receipt,
        source_attestation=old_att,action_correction_equivalence=proof))
    context=view.prepare_action_rebind(origin_index_ref=old_index_ref,paired_receipt_ref=new_receipt,
                                       verified_pair_ref=new_att,output_root=output)
    return context,identity,old_binding


def test_bulk_disk_gate_and_interrupted_immutable_write_can_resume(tmp_path,monkeypatch):
    monkeypatch.setattr(view.shutil,'disk_usage',lambda _:SimpleNamespace(free=39*1024**3))
    assert view._bulk_resources(tmp_path)['reason']=='DISK_BELOW_40_GIB'
    real_link=view.os.link
    monkeypatch.setattr(view.os,'link',lambda *_:(_ for _ in ()).throw(OSError('injected interruption')))
    with pytest.raises(OSError,match='injected interruption'):
        view._write_immutable(tmp_path,'STOCK_RESULT','.json',b'valid')
    assert not list(tmp_path.glob('STOCK_RESULT_*.json'))
    assert len(list(tmp_path.glob('.STOCK_RESULT_*.pending')))==1
    monkeypatch.setattr(view.os,'link',real_link)
    result=view._write_immutable(tmp_path,'STOCK_RESULT','.json',b'valid')
    assert Path(result['path']).read_bytes()==b'valid'
    assert view._write_immutable(tmp_path,'STOCK_RESULT','.json',b'valid')==result


def test_generic_refresh_keeps_display_exclusions_without_dropping_source_fields(tmp_path):
    policy=json.loads((Path(__file__).resolve().parents[1]/'contracts/a_share_single_display_projection_v1.json').read_text())
    excluded=set(policy['excluded_from_display_projection'])
    assert len(excluded)==25
    assert not excluded.intersection(view._fields())
    # The original B labels remain in the original-formula payload; presentation
    # excludes them while retaining the original formula/chart identity.
    assert excluded.intersection(view.ORIGINAL_FIELDS)=={'B1','B2','B3'}
    left,right,diag,identity=fixture_data()
    for name in excluded:
        if name not in left.column_names:
            left=left.append_column(name,pa.array([True]*left.num_rows))
    selector_columns=list(left.column_names);backtest_columns=list(right.column_names)
    first=view.build_from_verified_tables(symbol=identity['symbol'],selector=left,backtest=right,diagnostics=diag,
                                         identity=identity,output_root=tmp_path)
    refresh=view.build_from_verified_tables(symbol=identity['symbol'],selector=left,backtest=right,diagnostics=diag,
                                           identity=identity,output_root=tmp_path)
    assert first==refresh
    assert left.column_names==selector_columns and right.column_names==backtest_columns
    binding=json.loads(Path(first['path']).read_bytes())
    assert not excluded.intersection(binding['field_names'])
    assert not excluded.intersection(item['name'] for item in binding['base_fields'])
    assert {'B1','B2','B3'}<=set(binding['original_fields'])


def test_action_rebind_preserves_origin_assets_and_serves_new_logical_version(tmp_path):
    context,identity,old_ref=fixture_action_rebind(tmp_path);symbol=identity['symbol']
    result=view.materialize_action_rebind_stock(context,symbol)
    wrapper=json.loads(Path(result['binding']['path']).read_bytes())
    old=json.loads(Path(old_ref['path']).read_bytes())
    assert wrapper['origin_binding']==old_ref and old['candidate_generation']==S('a')
    assert wrapper['candidate_generation']==S('7') and wrapper['action_patch_rows']==1
    patch=json.loads(gzip.decompress(Path(wrapper['action_patch']['path']).read_bytes()))
    assert patch['rows'][0][0]==20240101 and patch['rows'][0][1][4]=='[]'
    assert patch['rows'][0][2][4]=='["冲突"]' and patch['source_overlay_sha256']==wrapper['source_overlay']['sha256']
    index={**context['index'],'symbols':{symbol:{'status':'READY','binding':result['binding']}}}
    index_ref=put_json(tmp_path/'logical-index.json',index)
    host=ResearchWorkbenchHost.__new__(ResearchWorkbenchHost);host.binding={'generic_single_index':index_ref}
    host._view=lambda *_:{'source_generation':identity['generation'],'source_identity':{'input_sha256':identity['input_sha256']},
                          'manifest':identity['numeric_manifest']}
    host._observation_date=lambda *_:identity['observation_date']
    meta=host.single_stock_research(identity['source_date'],symbol,identity['generation'])
    assert meta['panel_generation']==S('7') and meta['asset_candidate_generation']==S('a')
    assert meta['view_generation']==result['binding']['sha256'] and meta['action_patch_rows']==1
    content,_=host.single_stock_asset(identity['source_date'],symbol,'action_patch',wrapper['action_patch']['sha256'],
                                     identity['generation'],S('7'),meta['view_generation'])
    assert json.loads(gzip.decompress(content))==patch
    with pytest.raises(ValueError,match='PANEL_REVISION_CONFLICT'):
        host.single_stock_research(identity['source_date'],symbol,identity['generation'],S('a'))
    with pytest.raises(ValueError,match='VIEW_REVISION_CONFLICT'):
        host.single_stock_research(identity['source_date'],symbol,identity['generation'],S('7'),old_ref['sha256'])
    for bad in ({**wrapper,'candidate_generation':S('9')},
                {**wrapper,'origin_candidate_generation':S('9')},
                {**wrapper,'symbol':'000001.SZ'},
                {**wrapper,'source_overlay':{**wrapper['source_overlay'],'sha256':S('9')}}):
        with pytest.raises(ValueError,match='ACTION_REBIND_STOCK_IDENTITY_CONFLICT|ACTION_REBIND_PATCH_REQUIRED'):
            research_workbench_host.checked_action_rebind_stock(index,context['reuse'],symbol,bad)
    with pytest.raises(ValueError,match='ACTION_REBIND_STOCK_SCOPE_CONFLICT'):
        research_workbench_host.checked_action_rebind_index({**index,'symbols':{}})


def test_validator_compatibility_changes_only_validator_and_keeps_strict_proofs(tmp_path):
    context,identity,_=fixture_action_rebind(tmp_path);symbol=identity['symbol']
    result=view.materialize_action_rebind_stock(context,symbol)
    old_dir=tmp_path/'old-logical';old_dir.mkdir();out=tmp_path/'compat';out.mkdir()
    previous=old_dir/'old-validator.py';previous.write_text('# old frozen validator\n')
    old={**context['index'],'symbols':{symbol:{'status':'READY','binding':result['binding']}},
         'action_rebind':{**context['index']['action_rebind'],'validator':ref(previous)}}
    old_ref=put_json(old_dir/'index.json',old)
    with pytest.raises(ValueError,match='VALIDATOR_VERSION_CONFLICT'):
        research_workbench_host.checked_action_rebind_index(old)
    new_ref,proof_ref=view.rebind_action_validator_for_runtime(index_ref=old_ref,output_root=out)
    new=json.loads(Path(new_ref['path']).read_bytes());proof=json.loads(Path(proof_ref['path']).read_bytes())
    assert proof['ready_bindings']==1 and proof['all_symbol_entries_identical'] is True
    assert new['symbols']==old['symbols'] and new['paired_receipt']==old['paired_receipt']
    assert {k:v for k,v in new['action_rebind'].items() if k!='validator'}=={k:v for k,v in old['action_rebind'].items() if k!='validator'}
    assert research_workbench_host.checked_action_rebind_index(new)['origin']['candidate_generation']==S('a')
    reverted={**new,'action_rebind':{**new['action_rebind'],'validator':ref(previous)}}
    with pytest.raises(ValueError,match='VALIDATOR_VERSION_CONFLICT'):
        research_workbench_host.checked_action_rebind_index(reverted)
    bad={**new,'pair_sha256':{**new['pair_sha256'],'selector':S('0')}}
    with pytest.raises(ValueError,match='EQUIVALENCE_CONFLICT'):
        research_workbench_host.checked_action_rebind_index(bad)


@pytest.mark.parametrize(('kwargs','reason'),[
    ({'old_reasons':'["非原值"]'},'ACTION_REBIND_OLD_VALUE_CONFLICT'),
    ({'overlay_dates':(20240101,20240101)},'ACTION_REBIND_OVERLAY_DATE_CONFLICT'),
    ({'overlay_dates':(20240101,),'affected':2},'ACTION_REBIND_OVERLAY_COUNT_CONFLICT'),
    ({'overlay_dates':(20231231,)},'ACTION_REBIND_OVERLAY_DATE_CONFLICT'),
    ({'overlay_symbol':'000001.SZ'},'ACTION_REBIND_OVERLAY_DATE_CONFLICT'),
])
def test_action_rebind_rejects_bad_source_before_values_and_date_coverage(tmp_path,kwargs,reason):
    context,identity,_=fixture_action_rebind(tmp_path,**kwargs)
    with pytest.raises(ValueError,match=reason):view.materialize_action_rebind_stock(context,identity['symbol'])


def test_action_rebind_unchanged_stock_has_no_patch_and_refuses_wrong_pair(tmp_path):
    context,identity,old_ref=fixture_action_rebind(tmp_path,overlay_dates=())
    result=view.materialize_action_rebind_stock(context,identity['symbol'])
    wrapper=json.loads(Path(result['binding']['path']).read_bytes())
    assert wrapper['origin_binding']==old_ref and wrapper['action_patch_rows']==0 and wrapper['action_patch'] is None
    bad={**context['index'],'candidate_generation':S('0')}
    with pytest.raises(ValueError,match='ACTION_REBIND_EQUIVALENCE_CONFLICT'):
        research_workbench_host.checked_action_rebind_index(bad)


def test_action_rebind_rejects_incomplete_non_action_equivalence(tmp_path):
    with pytest.raises(ValueError,match='ACTION_REBIND_ROLE_PROOF_CONFLICT:selector'):
        fixture_action_rebind(tmp_path,selector_non_action=333)


def test_action_rebind_batch_can_resume_without_rewriting_old_assets(tmp_path,monkeypatch):
    context,identity,old_ref=fixture_action_rebind(tmp_path)
    monkeypatch.setattr(view,'_bulk_resources',lambda *args,**kwargs:{'ok':True,'reason':None})
    first=view.run_action_rebind(context,workers=1,max_new=1)
    assert first['status']=='COMPLETE' and first['ready']==1 and not first['errors']
    index=json.loads(Path(first['index']['path']).read_bytes())
    wrapper=json.loads(Path(index['symbols'][identity['symbol']]['binding']['path']).read_bytes())
    assert wrapper['origin_binding']==old_ref and wrapper['candidate_generation']==S('7')
    assert Path(old_ref['path']).is_file() and ref(Path(old_ref['path']))==old_ref
    resumed=view.run_action_rebind(context,workers=1)
    assert resumed['status']=='COMPLETE' and resumed['submitted_this_run']==0 and resumed['index']==first['index']


def test_action_rebind_stops_before_submitting_at_disk_or_budget_gate(tmp_path,monkeypatch):
    context,_,_=fixture_action_rebind(tmp_path)
    monkeypatch.setattr(view,'_bulk_resources',lambda *args,**kwargs:{'ok':True,'reason':None})
    monkeypatch.setattr(view.shutil,'disk_usage',lambda _:SimpleNamespace(free=24*1024**3+32*1024**2))
    result=view.run_action_rebind(context,workers=1)
    assert result['status']=='PARTIAL' and result['stop_reason']=='ACTION_REBIND_DISK_RESERVE'
    assert result['submitted_this_run']==0 and result['unfinished_count']==1


def test_action_rebind_stops_before_submitting_at_two_gib_budget(tmp_path,monkeypatch):
    context,_,_=fixture_action_rebind(tmp_path)
    monkeypatch.setattr(view,'_bulk_resources',lambda *args,**kwargs:{'ok':True,'reason':None})
    monkeypatch.setattr(view,'_action_output_bytes',lambda _:2*1024**3)
    result=view.run_action_rebind(context,workers=1)
    assert result['status']=='PARTIAL' and result['submitted_this_run']==0
    assert result['stop_reason']=='ACTION_REBIND_2_GIB_BUDGET'


def test_action_rebind_does_not_blindly_retry_a_recorded_failure(tmp_path):
    context,identity,_=fixture_action_rebind(tmp_path);root=Path(context['output_root']);checkpoints=root/'symbol_receipts';checkpoints.mkdir()
    failure={'schema':'v4.workbench.action_rebind_symbol_receipt.v1','symbol':identity['symbol'],
             'run_identity_sha256':context['run_identity']['sha256'],
             'result':{'status':'FAILED','reason':'SOURCE_MISMATCH'},**view.FLAGS}
    view._write_immutable(checkpoints,'600000_SH_ACTION_REBIND_RESULT','.json',view._canonical(failure))
    result=view.run_action_rebind(context,workers=1)
    assert result['status']=='PARTIAL' and result['stop_reason']=='RECORDED_FAILURE_REQUIRES_DIAGNOSIS'
    assert result['errors'][0]['reason']=='SOURCE_MISMATCH'


def test_bulk_reuses_old_n_checkpoint_only_with_frozen_source_and_no_resume(tmp_path):
    code='002865.SZ';checkpoint=tmp_path/(code+'.parquet');checkpoint.write_bytes(b'checkpoint')
    gap={'path':'/gap','sha256':S('a'),'checkpoint_id':S('b')}
    old_n={'path':'/old-n','sha256':S('c'),'source_generation':S('d'),'resume_across_generation':False}
    record={'checkpoint_id':S('b'),'sha256':hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            'confirmed_gap_sidecar':gap,'n_structure_checkpoint':old_n}
    put_json(tmp_path/(code+'.receipt.json'),record)
    receipt={'confirmed_gap_sidecars':{code:gap},'n_structure_checkpoints':{code:old_n},
             'materialized_reuse_refs':{code:{'path':'/old'}},'materialized_reuse_source_generation':S('d')}
    assert view._bulk_checkpoint(code,receipt,tmp_path)[0]['sha256']==record['sha256']
    bad={**old_n,'resume_across_generation':True};record['n_structure_checkpoint']=bad
    put_json(tmp_path/(code+'.receipt.json'),record);receipt['n_structure_checkpoints'][code]=bad
    with pytest.raises(ValueError,match='CHECKPOINT_BINDING_CONFLICT:n_structure_checkpoint'):
        view._bulk_checkpoint(code,receipt,tmp_path)


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
        policy=json.loads((Path(__file__).resolve().parents[1]/'contracts/a_share_single_display_projection_v1.json').read_text())
        excluded=set(policy['excluded_from_display_projection'])
        refresh=client.get(endpoint,params={'revision':identity['generation'],
            'panel_revision':reply.json()['panel_generation'],'view_revision':reply.json()['view_generation']})
        assert refresh.status_code==200 and refresh.json()['view_generation']==stock['sha256']
        assert refresh.json()['field_names']==reply.json()['field_names']
        assert not excluded.intersection(refresh.json()['field_names'])
        assert not excluded.intersection(field['name'] for field in refresh.json()['base_fields'])
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
    raw=Path(shard_ref['path']).read_bytes();gzip_path=tmp_path/'history-shard.json.gz'
    gzip_path.write_bytes(gzip.compress(raw,mtime=0))
    gzip_ref={**ref(gzip_path),'encoding':'gzip','decoded_bytes':len(raw),
              'decoded_sha256':hashlib.sha256(raw).hexdigest()}
    compressed_index,compressed_outcomes=view.bind_retained_pair_history(index_ref=idx,
        history_refs={identity['symbol']:gzip_ref},history_producer_ref=owner,output_root=out)
    assert compressed_outcomes[identity['symbol']]['status']=='READY'
    compressed_value=json.loads(Path(compressed_index['path']).read_bytes())
    compressed_binding=json.loads(Path(compressed_value['symbols'][identity['symbol']]['binding']['path']).read_bytes())
    assert compressed_binding['details']['history']['history_shard']==gzip_ref
    assert compressed_binding['details']['history']['asset']==amended_binding['details']['history']['asset']
    truncated=tmp_path/'truncated.json.gz';truncated.write_bytes(gzip_path.read_bytes()[:-5])
    bad_refs=[({**gzip_ref,'decoded_sha256':S('f')},'HISTORY_DECODED_SHA_CONFLICT'),
        ({k:v for k,v in gzip_ref.items() if k!='decoded_sha256'},'HISTORY_GZIP_REFERENCE_INVALID'),
        ({**gzip_ref,'decoded_bytes':len(raw)+1},'ASSET_DECODED_SIZE_CONFLICT'),
        ({**gzip_ref,'decoded_bytes':view.MAX_HISTORY_SOURCE_DECODED+1},'HISTORY_GZIP_REFERENCE_INVALID'),
        ({**gzip_ref,'bytes':gzip_ref['bytes']+1},'ASSET_COMPRESSED_SIZE_CONFLICT'),
        ({**gzip_ref,**ref(truncated)},'HISTORY_GZIP_INVALID')]
    for bad_ref,reason in bad_refs:
        _,bad_outcomes=view.bind_retained_pair_history(index_ref=idx,history_refs={identity['symbol']:bad_ref},
            history_producer_ref=owner,output_root=out)
        assert bad_outcomes[identity['symbol']]['status']=='UNKNOWN'
        assert reason in bad_outcomes[identity['symbol']]['reason']
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


def test_gzip_rejects_a_file_changed_after_reference_check(tmp_path,monkeypatch):
    compressed=tmp_path/'changing.gz';compressed.write_bytes(gzip.compress(b'first',mtime=0));source=ref(compressed)
    original=view._checked
    def changed_after_check(item,**kwargs):
        path=original(item,**kwargs);path.write_bytes(gzip.compress(b'other',mtime=0));return path
    monkeypatch.setattr(view,'_checked',changed_after_check)
    with pytest.raises(ValueError,match='REFERENCE_SHA_DRIFT'):
        view._bounded_gzip(source,maximum=1024,compressed_maximum=2048)


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


def test_daily_reconciled_sidecar_preserves_n_source_and_rejects_unbound_parts(tmp_path):
    left,right,fresh,identity=fixture_data();symbol=identity['symbol'];out=tmp_path/'out';out.mkdir()
    old_rows=fresh.slice(0,2).to_pylist()
    for row in old_rows:
        diag=json.loads(row['diagnostics_json']);diag['kb_n_structure'].update(generation_id=S('9'),input_sha256=S('8'))
        row['diagnostics_json']=json.dumps(diag)
    old=pa.Table.from_pylist(old_rows,schema=fresh.schema);old_path=tmp_path/'old.parquet';pq.write_table(old,old_path);old_ref=ref(old_path)
    parts=tmp_path/'run'/'symbol_checkpoints';parts.mkdir(parents=True);fresh_path=parts/(symbol+'.gap.parquet');pq.write_table(fresh,fresh_path)
    checkpoint_id=S('5');fresh_ref={**ref(fresh_path),'checkpoint_id':checkpoint_id}
    inherited={'source':old_ref,'rows':2,'through_date':20240102,
        'identity_policy':'ORIGINAL_SOURCE_IDENTITY_RETAINED_IN_DIAGNOSTICS','cross_generation_n_checkpoint_reused':False}
    continuation={'fresh_source':fresh_ref,'first_affected_date':20240103,'prefix_input_sha256':S('1'),'prefix_through_date':20240102}
    meta={'symbol':symbol,'continuation':continuation,'inherited_prefix':inherited,
          'generation_id':identity['candidate_generation'],'source_input_sha256':identity['candidate_input_sha256'],
          'price_basis':'QFQ_ASOF','volume_basis':'QFQ_EVENT_VOLUME',
          'n_structure_enabled':True,'diagnostic_keys':list(view.q.SINGLE_GAP_DIAGNOSTICS)+['kb_n_structure'],
          'n_structure_contract_sha256':identity['n_rule_sha256'],'n_structure_helper_sha256':identity['n_helper_sha256'],**view.FLAGS}
    merged=pa.concat_tables([old,fresh.slice(2)]).replace_schema_metadata({b'v4.a_share.kb_gap_diagnostics.v1':json.dumps(meta).encode()})
    merged_path=parts/(symbol+'.merged.parquet');pq.write_table(merged,merged_path)
    merged_ref={**ref(merged_path),'checkpoint_id':checkpoint_id,'rows':3,'continuation':continuation,'inherited_prefix':inherited}
    baseline=put_json(tmp_path/'baseline.json',{'status':'CANDIDATE_READY','generation_id':S('7'),'input_sha256':S('6'),
        'confirmed_gap_sidecars':{symbol:old_ref},'historical_PIT':False,**view.FLAGS})
    reconciliation=put_json(tmp_path/'reconciliation.json',{'schema':'a_share_kb_daily_reconciliation_v1',
        'generation_id':identity['candidate_generation'],'baseline_generation_id':S('7'),'historical_PIT':False,**view.FLAGS,
        'stocks':{symbol:{role:{'symbol':symbol,'first_affected_date':20240103,'preserved_rows':2,'recomputed_rows':1}
                          for role in ('selector','backtest')}}})
    n_checkpoint={**put_json(parts/(symbol+'.n.json'),{}),'checkpoint_id':checkpoint_id}
    checkpoint_path=parts/(symbol+'.parquet');pq.write_table(left,checkpoint_path)
    put_json(parts/(symbol+'.receipt.json'),{'checkpoint_id':checkpoint_id,'sha256':ref(checkpoint_path)['sha256'],
        'confirmed_gap_sidecar':fresh_ref,'n_structure_checkpoint':n_checkpoint})
    receipt={'status':'CANDIDATE_READY','generation_id':identity['candidate_generation'],'input_sha256':identity['candidate_input_sha256'],
        'price_basis':'QFQ_ASOF','volume_basis':'QFQ_EVENT_VOLUME',
        'confirmed_gap_sidecars':{symbol:merged_ref},'n_structure_checkpoints':{symbol:n_checkpoint},'run_dir':str(parts.parent),
        'n_structure_contract_sha256':identity['n_rule_sha256'],'n_structure_helper_sha256':identity['n_helper_sha256'],
        'full_research_continuation':{'schema':'a_share_kb_daily_continuation_v1',
            'sidecar_policy':'PRESERVE_BOUND_PRIOR_IDENTITY_NO_CROSS_GENERATION_N_RESUME',
            'baseline_receipt':baseline,'baseline_generation_id':S('7'),'baseline_input_sha256':S('6')},
        'full_research_sidecar_inheritance':{'schema':'a_share_kb_sidecar_inheritance_v1',
            'baseline_generation_id':S('7'),'baseline_receipt':baseline,'inherited_whole_codes':[],
            'recomputed_codes':[symbol],'identity_policy':'PRESERVE_PRIOR_SOURCE_IDENTITY_AND_SIDECAR_REFERENCE',
            'cross_generation_n_checkpoint_reused':False},
        'full_research_daily_reconciliation':reconciliation,'historical_PIT':False,**view.FLAGS}
    n=view._n_sidecar_identity(receipt,meta,merged,symbol);assert n['n_identity_kind']=='RECONCILED_DAILY'
    assert [(s['start_index'],s['end_index'],s['generation_id']) for s in n['n_identity_spans']]==[(0,1,S('9')),(2,2,S('a'))]
    view._bulk_checkpoint(symbol,receipt,parts)
    receipt_ref=put_json(tmp_path/'candidate.json',receipt)
    identity.update(**n,paired_receipt=receipt_ref,diagnostics_sha256=merged_ref['sha256'])
    binding_ref=view.build_from_verified_tables(symbol=symbol,selector=left,backtest=right,diagnostics=merged,identity=identity,output_root=out)
    binding=json.loads(Path(binding_ref['path']).read_bytes());index={'candidate_generation':identity['candidate_generation'],
        'candidate_input_sha256':identity['candidate_input_sha256']}
    assert research_workbench_host.checked_daily_n_lineage(index,binding,symbol)==n['n_identity_spans']
    wrong=dict(receipt);wrong['confirmed_gap_sidecars']={symbol:{**merged_ref,'continuation':{**continuation,'fresh_source':{**fresh_ref,'sha256':S('0')}}}}
    with pytest.raises(ValueError,match='CHECKPOINT_BINDING_CONFLICT'):
        view._bulk_checkpoint(symbol,wrong,parts)
    changed=merged.to_pylist();changed[0]['diagnostics_json']=changed[0]['diagnostics_json']+' '
    with pytest.raises(ValueError,match='SIDECAR_ROWS_CONFLICT'):
        view._n_sidecar_identity(receipt,meta,pa.Table.from_pylist(changed,schema=merged.schema),symbol)
    wrong_suffix=merged.to_pylist();diag=json.loads(wrong_suffix[-1]['diagnostics_json']);diag['kb_n_structure']['generation_id']=S('9')
    wrong_suffix[-1]['diagnostics_json']=json.dumps(diag)
    with pytest.raises(ValueError,match='DAILY_N_IDENTITY_CONFLICT'):
        view._daily_n_spans(receipt,meta,pa.Table.from_pylist(wrong_suffix,schema=merged.schema),20240103)
    broken=dict(meta);broken['continuation']={**continuation,'prefix_input_sha256':S('2')}
    bad_receipt={**receipt,'confirmed_gap_sidecars':{symbol:{**merged_ref,'continuation':broken['continuation']}}}
    with pytest.raises(ValueError,match='PREFIX_INPUT_CONFLICT'):
        view._n_sidecar_identity(bad_receipt,broken,merged,symbol)
    bad_binding={**binding,'n_identity_spans':[dict(n['n_identity_spans'][0],end_index=2),n['n_identity_spans'][1]]}
    with pytest.raises(ValueError,match='DAILY_N_SPANS_CONFLICT'):
        research_workbench_host.checked_daily_n_lineage(index,bad_binding,symbol)
    baseline_value=json.loads(Path(baseline['path']).read_bytes());baseline_value.pop('historical_PIT')
    missing_pit=put_json(tmp_path/'baseline-missing-pit.json',baseline_value)
    bad_receipt={**receipt,'full_research_continuation':{**receipt['full_research_continuation'],'baseline_receipt':missing_pit},
        'full_research_sidecar_inheritance':{**receipt['full_research_sidecar_inheritance'],'baseline_receipt':missing_pit}}
    with pytest.raises(ValueError,match='BASELINE_SIDECAR_CONFLICT'):
        view._n_sidecar_identity(bad_receipt,meta,merged,symbol)
    whole_source={'schema':'a_share_kb_daily_continuation_v1','sidecar_policy':'PRESERVE_BOUND_PRIOR_IDENTITY_NO_CROSS_GENERATION_N_RESUME',
        'baseline_receipt':receipt_ref,'baseline_generation_id':receipt['generation_id'],'baseline_input_sha256':receipt['input_sha256']}
    whole={**receipt,'generation_id':S('4'),'input_sha256':S('3'),'full_research_continuation':whole_source,
        'full_research_sidecar_inheritance':{'schema':'a_share_kb_sidecar_inheritance_v1',
            'baseline_generation_id':receipt['generation_id'],'baseline_receipt':receipt_ref,'inherited_whole_codes':[symbol],
            'recomputed_codes':[],'identity_policy':'PRESERVE_PRIOR_SOURCE_IDENTITY_AND_SIDECAR_REFERENCE',
            'cross_generation_n_checkpoint_reused':False}}
    view._require_sidecar_metadata(whole,meta,symbol);whole_n=view._n_sidecar_identity(whole,meta,merged,symbol)
    assert whole_n['n_identity_kind']=='INHERITED_WHOLE' and whole_n['n_generation_id']==S('9')
    assert whole_n['n_identity_spans']==n['n_identity_spans']
    whole_ref=put_json(tmp_path/'whole-candidate.json',whole)
    whole_identity={**identity,**whole_n,'candidate_generation':S('4'),'candidate_input_sha256':S('3'),'paired_receipt':whole_ref}
    whole_binding_ref=view.build_from_verified_tables(symbol=symbol,selector=left,backtest=right,diagnostics=merged,
        identity=whole_identity,output_root=out)
    whole_binding=json.loads(Path(whole_binding_ref['path']).read_bytes())
    assert research_workbench_host.checked_daily_n_whole_lineage({'candidate_generation':S('4'),'candidate_input_sha256':S('3')},
        whole_binding,symbol)==n['n_identity_spans']
    bad_whole={**whole,'n_structure_checkpoints':{symbol:{**n_checkpoint,'sha256':S('0')}}}
    with pytest.raises(ValueError,match='WHOLE_SIDECAR_CONFLICT'):
        view._n_sidecar_identity(bad_whole,meta,merged,symbol)


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


def candidate_f10_fixture(root, *, outside=False, wrong_name=False):
    root.mkdir();product=root/'product';product.mkdir();canonical=root/'canonical';canonical.mkdir()
    symbol='920196.BJ';name='错名' if wrong_name else '南方乳业';source_gen,source_input=S('a'),S('b')
    candidate_gen,candidate_input=S('c'),S('d');selector,backtest,snapshot=S('e'),S('f'),S('1')
    source_manifest=put_json(root/'source_manifest.json',{'source_generation':source_gen,'input_sha256':source_input,'snapshot':{'sha256':snapshot}})
    p={'source_generation':source_gen,'source_identity':{'input_sha256':source_input,'selector_artifact_sha256':S('2')},'manifest':source_manifest,'rows':[]}
    owner=root/'f10_owner.py';owner.write_text('# pinned owner\n');owner_ref=ref(owner)
    daily=root/'daily_owner.py';daily.write_text('# pinned daily\n');daily_ref=ref(daily)
    config=put_json(root/'config.json',{'source':'fixture'})
    names=root/'names.csv';names.write_text('market,symbol,name\nBJ,920196.BJ,南方乳业\n');name_ref=ref(names)
    text=f'◇920196 {name} 更新日期：2026-10-30◇'
    stock={'symbol':symbol,'name':name,'exchange':'BJ','status':'OBSERVED','captured_at':'2026-11-02T01:02:03+00:00',
        'source_updated_date':'2026-10-30','finance_updated_date':'20261030','source_text':text,
        'source_text_sha256':hashlib.sha256(text.encode()).hexdigest(),'endpoint_markets':{'text':0,'finance':2},
        'finance_native_raw':{'code':'920196','market':2},'financials':{},'concepts':[],
        'historical_PIT':False,**view.FLAGS}
    stock_ref=put_json((root if outside else product)/'stock.json',stock)
    item={'name':name,'captured_at':stock['captured_at'],'source_updated_date':stock['source_updated_date'],
          'finance_updated_date':stock['finance_updated_date'],'stock':stock_ref}
    collector={'tdx_f10_fetch_existing.py':S('3')}
    replay=put_json(root/'replay.json',{'schema':'v4.a_share.f10_bj_replay_receipt.v1','status':'FIVE_OBSERVATIONS_REPLAYED',
        'adapter_sha256':owner_ref['sha256'],'collector_sha256':collector,'sample_lock':name_ref,'no_new_network_request':True,
        'items':{symbol:{'artifact':stock_ref}},'historical_PIT':False,**view.FLAGS})
    pair_ref=put_json(root/'pair.json',{'status':'CANDIDATE_READY','generation_id':candidate_gen,'input_sha256':candidate_input,
        'candidate_sha256':{'selector':selector,'backtest':backtest},
        'kb_initial_upgrade':{'source_generation_id':source_gen,'baseline_panel_sha256':{'selector':S('2')}},
        'materialized_reuse_source_input_sha256':source_input,'materialized_reuse_source_snapshot_sha256':snapshot,
        'historical_PIT':False,**view.FLAGS})
    att_ref=put_json(root/'attestation.json',{'status':'PASS','candidate_receipt':pair_ref,'generation_id':candidate_gen,
        'input_sha256':candidate_input,'old_arrow_equivalence':{'status':'PASS'},'historical_PIT':False,**view.FLAGS})
    generic_ref=put_json(root/'generic.json',{'source_date':'2026-10-30','candidate_generation':candidate_gen,
        'candidate_input_sha256':candidate_input,'paired_receipt':pair_ref,'verified_pair':att_ref,
        'pair_sha256':{'selector':selector,'backtest':backtest}})
    numeric_ref=put_json(product/'numeric.json',{'schema_version':'v4.a_share.daily_product.v1','data_date':'20261030',
        'source_generation':candidate_gen,'source_identity':{'input_sha256':candidate_input,'selector_artifact_sha256':selector,
            'historical_PIT':False},'source_config':config,'sample_only':True,'processed_universe':[symbol],**view.FLAGS})
    manifest_ref=put_json(product/'manifest.json',{'schema_version':'v4.a_share.daily_product_manifest.v1','data_date':'20261030',
        'source_generation':candidate_gen,'input_sha256':candidate_input,'sample_only':True,'artifact':numeric_ref,**view.FLAGS})
    scope_sha=hashlib.sha256(json.dumps({symbol:'BJ'},sort_keys=True).encode()).hexdigest()
    identity={'data_date':'20261030','source_generation':candidate_gen,'input_sha256':candidate_input,'selector_sha256':selector,
        'scope_sha256':scope_sha,'adapter_sha256':owner_ref['sha256'],'collector_sha256':collector}
    checkpoint_ref=put_json(product/'checkpoint.json',{'schema':'v4.a_share.f10_checkpoint.v1','identity':identity,
        'upstream_success_receipt':manifest_ref,'items':{symbol:stock_ref},**view.FLAGS})
    receipt_ref=put_json(product/'receipt.json',{'schema':'v4.a_share.f10_daily_receipt.v1',**identity,'status':'COMPLETE',
        'captured_as_current_knowledge':True,'upstream_success_receipt':manifest_ref,'checkpoint':checkpoint_ref,
        'scope':{'kind':'EXPLICIT_SYMBOLS','count':1,'symbols':[symbol]},'requested':1,'observed':1,
        'historical_PIT':False,**view.FLAGS})
    event_ref=put_json(product/'event.json',{'schema_version':'v4.a_share.daily_completion.v1','data_date':'20261030',
        'source_generation':candidate_gen,'input_sha256':candidate_input,'manifest':manifest_ref,'f10':receipt_ref,
        'publication_scope':'ISOLATED_CANDIDATE_SAMPLE_ONLY','sample_only':True,**view.FLAGS})
    index_ref=put_json(product/'index.json',{'schema_version':'v4.a_share.daily_product_index.v1',
        'dates':{'20261030':manifest_ref},'f10':{'20261030':receipt_ref}})
    proof_ref=put_json(root/'proof.json',{'schema':'v4.a_share.isolated_bj_f10_completion_proof.v1',
        'status':'ISOLATED_OWNER_COMPLETION_VERIFIED','lock_scope':'ISOLATED_ONLY','not_global_current':True,
        'product_root':str(product),'source_generation':candidate_gen,'input_sha256':candidate_input,
        'index':index_ref,'event':event_ref,'numeric_manifest':manifest_ref,'numeric_artifact':numeric_ref,
        'f10_receipt':receipt_ref,'f10_checkpoint':checkpoint_ref,'f10_owner':owner_ref,'daily_owner':daily_ref,
        'source_config':config,'raw_replay':replay,'name_table':name_ref,'pair_attestation':att_ref,
        'items':{symbol:item},'historical_PIT':False,**view.FLAGS})
    put_json(canonical/'index.json',{'f10':{}})
    host=ResearchWorkbenchHost.__new__(ResearchWorkbenchHost)
    host.binding={'generic_single_index':generic_ref,'candidate_f10_completion':proof_ref}
    host._view=lambda *_:p;host.single_stock_research=lambda *_:{'status':'READY_FOR_RESEARCH_REVIEW'}
    host._generic_single=lambda *_:{'status':'READY_FOR_RESEARCH_REVIEW','panel_generation':candidate_gen,'candidate_input_sha256':candidate_input}
    host.source=SimpleNamespace(_a_product_root=lambda:canonical,_a_product_reference=lambda r:research_workbench_host.checked_bounded(r,4*1024*1024))
    return host,p,symbol,stock_ref


def test_candidate_f10_keeps_lineage_and_rejects_unregistered_paths_and_names(tmp_path):
    host,p,symbol,stock_ref=candidate_f10_fixture(tmp_path/'ok')
    answer=host.f10('2026-10-30',symbol,p['source_generation'])
    assert answer['status']=='OBSERVED_CANDIDATE' and answer['f10']['name']=='南方乳业'
    assert answer['source_generation']==S('c') and answer['bound_source_generation']==S('a')
    assert answer['input_sha256']==S('d') and answer['bound_source_input_sha256']==S('b')
    assert host.f10('2026-10-29',symbol,S('a'))['status']=='NOT_MATERIALIZED'
    proof_ref=host.binding.pop('candidate_f10_completion');host.binding['candidate_f10_completions']=[proof_ref,proof_ref]
    with pytest.raises(ValueError,match='F10_CANDIDATE_SCOPE_OVERLAP'):host.f10('2026-10-30',symbol,S('a'))
    host.binding.pop('candidate_f10_completions');host.binding['candidate_f10_completion']=proof_ref
    wrong={**p,'source_identity':{**p['source_identity'],'input_sha256':S('9')}};host._view=lambda *_:wrong
    with pytest.raises(ValueError,match='F10_CANDIDATE_LINEAGE_CONFLICT'):host.f10('2026-10-30',symbol,S('a'))
    host._view=lambda *_:p;Path(stock_ref['path']).write_text('{}')
    with pytest.raises(ValueError,match='SHA_DRIFT|SIZE_CONFLICT'):host.f10('2026-10-30',symbol,S('a'))
    host,p,symbol,_=candidate_f10_fixture(tmp_path/'outside',outside=True)
    with pytest.raises(ValueError,match='F10_CANDIDATE_OUTSIDE_REGISTERED_ROOT'):host.f10('2026-10-30',symbol,S('a'))
    host,p,symbol,_=candidate_f10_fixture(tmp_path/'name',wrong_name=True)
    with pytest.raises(ValueError,match='F10_CANDIDATE_STOCK_IDENTITY_CONFLICT'):host.f10('2026-10-30',symbol,S('a'))


def test_rebound_f10_keeps_its_proven_old_candidate_identity(tmp_path,monkeypatch):
    host,p,symbol,_=candidate_f10_fixture(tmp_path/'rebound')
    origin=research_workbench_host.checked_bounded(host.binding['generic_single_index'],8*1024*1024)
    new={'source_date':'2026-10-30','candidate_generation':S('7'),'candidate_input_sha256':S('6'),
         'action_rebind':{'equivalence':{'sha256':S('8')}}}
    host.binding['generic_single_index']=put_json(tmp_path/'logical-f10-index.json',new)
    monkeypatch.setattr(research_workbench_host,'checked_action_rebind_index',lambda _:{'origin':origin})
    meta={'status':'READY_FOR_RESEARCH_REVIEW','panel_generation':S('7'),'candidate_input_sha256':S('6'),
          'asset_candidate_generation':S('c'),'asset_candidate_input_sha256':S('d')}
    host._generic_single=lambda *_:meta
    answer=host.f10('2026-10-30',symbol,S('a'))
    assert answer['lineage']=='REGISTERED_ISOLATED_PAIRED_CANDIDATE_REUSED'
    assert answer['source_generation']==S('c') and answer['logical_candidate_generation']==S('7')
    assert answer['reuse_equivalence_sha256']==S('8') and answer['f10']['name']=='南方乳业'
    host._generic_single=lambda *_:{**meta,'asset_candidate_generation':S('9')}
    with pytest.raises(ValueError,match='F10_CANDIDATE_VIEW_CONFLICT'):host.f10('2026-10-30',symbol,S('a'))


def test_independent_company_does_not_admit_quarantined_price(tmp_path):
    host,p,_,_=candidate_f10_fixture(tmp_path/'independent')
    proof_path=Path(host.binding['candidate_f10_completion']['path']);proof=json.loads(proof_path.read_text())
    product=Path(proof['product_root']);symbol='688496.SH';name='*ST清越'
    names=Path(proof['name_table']['path']);names.write_text('market,symbol,name\nBJ,920196.BJ,南方乳业\nSH,688496.SH,*ST清越\n')
    proof['name_table']=ref(names);text='◇688496 *ST清越 更新日期：2026-11-02◇';captured='2026-11-02T01:02:03+00:00'
    stock={'symbol':symbol,'name':name,'exchange':'SH','status':'OBSERVED','captured_at':captured,'source_updated_date':'2026-11-02',
        'source_text':text,'source_text_sha256':hashlib.sha256(text.encode()).hexdigest(),
        'finance_native_raw':{'code':'688496','market':1},'financials':{},'concepts':[],
        'historical_PIT':False,**view.FLAGS}
    stock_ref=put_json(product/'independent_stock.json',stock)
    replay=put_json(proof_path.parent/'a7_replay.json',{'schema':'v4.a_share.f10_a7_owner_replay.v1',
        'status':'SEVEN_CAPTURED_COMPANY_ITEMS_REPLAYED','adapter_sha256':proof['f10_owner']['sha256'],
        'sample_lock':proof['name_table'],'no_new_network_request':True,'items':{symbol:{'artifact':stock_ref}},
        'historical_PIT':False,**view.FLAGS})
    proof['raw_replay']=replay;proof['schema']='v4.a_share.isolated_a6_f10_completion_proof.v1'
    observation={'schema':'v4.a_share.independent_company_observation.v1','status':'COMPANY_IDENTITY_VERIFIED','symbol':symbol,
        'source_generation':None,'price_panel_admission':'NOT_ASSERTED','data_asof':'CURRENT_CAPTURE_ONLY',
        'name':name,'captured_at':captured,'source_updated_date':'2026-11-02','company_ref':stock_ref,
        'f10_owner':proof['f10_owner'],'raw_replay':replay,'name_table':proof['name_table'],
        'historical_PIT':False,**view.FLAGS}
    proof['independent_company_688496']=put_json(product/'independent_proof.json',observation)
    host.binding['candidate_f10_completion']=put_json(proof_path,proof)
    host._generic_single=lambda *_:{'status':'UNKNOWN_SOURCE_ADMISSION'}
    result=host.f10('2026-10-30',symbol,S('a'))
    assert result['status']=='OBSERVED_INDEPENDENT_COMPANY' and result['f10']['name']==name
    assert result['source_generation'] is None and result['input_sha256'] is None and result['price_panel_admission']=='NOT_ASSERTED'
    host._generic_single=lambda *_:{'status':'READY_FOR_RESEARCH_REVIEW'}
    with pytest.raises(ValueError,match='F10_INDEPENDENT_REGISTRATION_CONFLICT'):host.f10('2026-10-30',symbol,S('a'))


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
