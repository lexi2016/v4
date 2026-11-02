"""Exercise exact source/rule binding before the full-A daily owner can reuse."""
import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ops import research_panel_daily_107_binding as binding
from ops import research_panel_qfq as q


def _ref(path):return {'path':str(path.resolve()),'sha256':q.sha(path)}


def _write(path,value):
    path.write_text(json.dumps(value,sort_keys=True));return _ref(path)


def _fixture(tmp_path,monkeypatch,target=20261030):
    root=Path(q.__file__).resolve().parents[1]
    calendar=_ref(root/'contracts/market_calendar_2026.json')
    adapter=_ref(root/'contracts/trading_calendar.py')
    official=_write(tmp_path/'official.json',{'target_date':target,'calendar':calendar,'calendar_adapter':adapter})
    sync=_write(tmp_path/'sync.json',{'target_date':target,'official_daily_source':{'input_ref':official}})
    config=_write(tmp_path/'config.json',{'prequery_sync_ref':sync})
    codes=['000001.SZ','600000.SH','920201.BJ']
    def item(code):return {'raw_files':[{'path':str(tmp_path/(code+'.day')),'sha256':'d'*64}],
                           'events':[],'event_coverage_complete':True,'history_start_date':20200101}
    old={'asof_date':20261030,'convention':'C','price_basis':'QFQ_ASOF','volume_basis':'QFQ_EVENT_VOLUME',
         'amount_basis':'RAW_TURNOVER','symbols':{code:item(code) for code in codes},
         'original_target_codes':codes,'effective_target_codes':codes,'lifecycle_addition_codes':[],
         'retained_history_codes':[],'legacy_preservation_codes':[],'quarantine_symbols':{}}
    old_ref=_write(tmp_path/'old-snapshot.json',old)
    roles={};hashes={}
    for role in ('selector','backtest'):
        path=tmp_path/(role+'.parquet');path.write_bytes(role.encode());roles[role]=path;hashes[role]=q.sha(path)
    core=_ref(Path(q.__file__).resolve())
    identity={key:'a'*64 for key in binding._KERNEL_KEYS}
    identity['confirmed_gap_helper_sha256']={'helper':'b'*64}
    receipt_path=tmp_path/'receipt.json'
    receipt={'status':'CANDIDATE_READY','target_date':20261030,'research_scope':'ADMITTED_A_SHARE',
        'adjustment_snapshot':old_ref,'snapshot_file_sha256':old_ref['sha256'],'input_sha256':q.canonical_sha(old),
        'adapter_sha256':core['sha256'],'full_research_contract_sha256':identity['full_research_contract_sha256'],
        'generation_id':'c'*64,'candidates':{r:str(p) for r,p in roles.items()},'candidate_sha256':hashes}
    receipt_ref=_write(receipt_path,receipt)
    meta={**identity,'generation_id':receipt['generation_id'],'input_sha256':receipt['input_sha256'],
          'generation_manifest_path':str(receipt_path),'snapshot_file_sha256':old_ref['sha256'],
          'research_scope':'ADMITTED_A_SHARE'}
    monkeypatch.setattr(q,'panel_contract',lambda _:dict(meta))
    monkeypatch.setattr(q,'resolved_raw_history',lambda code,item,asof,driver:
        pd.DataFrame({'trade_date':[20261030,20261102] if code=='000001.SZ' else [20261030]}))
    snapshot={**old,'asof_date':target,'research_cache_configuration':config}
    value={'schema':'a_share_kb_daily_continuation_v1','status':'PREPARED_NOT_CONSUMED','target_date':target,
        'baseline_receipt':receipt_ref,'baseline_snapshot':old_ref,'baseline_adapter':core,
        'baseline_roles':{r:_ref(p) for r,p in roles.items()},'calendar':calendar,'calendar_adapter':adapter,
        'historical_PIT':False,**q.FLAGS}
    descriptor=_write(tmp_path/'descriptor.json',value)
    return descriptor,snapshot,identity,roles,hashes,meta


def test_exact_repeat_and_append_classify_without_reusing_n_state(tmp_path,monkeypatch):
    ref,snapshot,identity,roles,hashes,_=_fixture(tmp_path,monkeypatch)
    result=binding.bind(ref,q=q,snapshot=snapshot,target=20261030,identity=identity,
                        currents=roles,baseline_hashes=hashes,driver=None)
    assert not result['codes'] and set(result['unchanged_codes'])==set(snapshot['symbols'])
    assert result['sidecar_policy']=='PRESERVE_BOUND_PRIOR_IDENTITY_NO_CROSS_GENERATION_N_RESUME'
    root=tmp_path/'next';root.mkdir()
    ref,snapshot,identity,roles,hashes,_=_fixture(root,monkeypatch,target=20261102)
    snapshot['symbols']['600000.SH']['events']=[{'ex_date':20261102,'a':1.,'b':-.1,'volume_a':1.}]
    result=binding.bind(ref,q=q,snapshot=snapshot,target=20261102,identity=identity,
                        currents=roles,baseline_hashes=hashes,driver=None)
    assert result['codes']['000001.SZ']['reason']=='NEW_OBSERVED_BAR_AFTER_BASELINE'
    assert result['codes']['600000.SH']['reason']=='SOURCE_OR_ADJUSTMENT_DEPENDENCIES_CHANGED'
    assert result['unchanged_codes']==['920201.BJ']


def test_identity_calendar_and_membership_drift_fail_closed(tmp_path,monkeypatch):
    ref,snapshot,identity,roles,hashes,meta=_fixture(tmp_path,monkeypatch)
    kwargs=dict(ref=ref,q=q,snapshot=snapshot,target=20261030,identity=identity,currents=roles,
                baseline_hashes=hashes,driver=None)
    meta['single_action_contract_sha256']='e'*64
    with pytest.raises(q.QfqGateError,match='CALCULATION_IDENTITY_CHANGED'):binding.bind(**kwargs)
    meta['single_action_contract_sha256']=identity['single_action_contract_sha256']
    snapshot['effective_target_codes']=['000001.SZ']
    with pytest.raises(q.QfqGateError,match='MEMBERSHIP_CHANGED'):binding.bind(**kwargs)
    snapshot['effective_target_codes']=list(snapshot['original_target_codes'])
    value=json.loads(Path(ref['path']).read_text());value['calendar']={'path':value['calendar']['path'],'sha256':'f'*64}
    bad=_write(tmp_path/'bad-descriptor.json',value)
    with pytest.raises(q.QfqGateError,match='CALENDAR_NOT_BOUND_TO_SOURCE'):binding.bind(**{**kwargs,'ref':bad})


def test_same_input_does_not_reuse_old_action_authority(tmp_path, monkeypatch):
    ref,snapshot,identity,roles,hashes,meta=_fixture(tmp_path,monkeypatch)
    meta['single_action_authority_sha256']='b'*64
    with pytest.raises(q.QfqGateError,match='CALCULATION_IDENTITY_CHANGED'):
        binding.bind(ref,q=q,snapshot=snapshot,target=20261030,identity=identity,
                     currents=roles,baseline_hashes=hashes,driver=None)


def test_qfq_math_change_invalidates_control_only_reuse(tmp_path):
    path=Path(q.__file__).resolve();original=path.read_text()
    changed=tmp_path/'qfq.py';changed.write_text(original.replace('def apply_adjustments(',
        'def apply_adjustments_changed(',1))
    assert binding.computation_semantics_sha(path,q)!=binding.computation_semantics_sha(changed,q)


def _panel(rows):
    schema=pa.schema([('ts_code',pa.string()),('trade_date',pa.string()),
        ('open',pa.float64()),('high',pa.float64()),('low',pa.float64()),('close',pa.float64()),
        ('volume',pa.float64()),('amount',pa.float64()),('pre_close',pa.float64()),('pct_chg',pa.float64()),
        ('kb_label',pa.bool_()),('user_v1_hold_yesterday_keyline_display_asof',pa.int8()),
        ('user_v1_break_yesterday_keyline_display_asof',pa.int8()),('user_v1_sell_signal_display_asof',pa.int8())])
    return pa.Table.from_pylist(rows,schema=schema)


def _bar(day,price,label,display=0):
    return dict(ts_code='000001.SZ',trade_date=day,open=price,high=price+1,low=price-1,close=price,
        volume=100.,amount=1000.,pre_close=price,pct_chg=0.,kb_label=label,
        user_v1_hold_yesterday_keyline_display_asof=display,
        user_v1_break_yesterday_keyline_display_asof=display,
        user_v1_sell_signal_display_asof=display)


def test_append_preserves_old_arrow_values_and_updates_only_old_asof_display():
    old=_panel([_bar('20261029',10.,None),_bar('20261030',11.,True,1)])
    fresh=_panel([_bar('20261029',10.,False),_bar('20261030',11.,False,0),_bar('20261102',12.,True,1)])
    output,proof=binding.reconcile_panel(old,fresh,code='000001.SZ',previous=20261030,target=20261102,q=q)
    assert output['kb_label'].to_pylist()==[None,True,True]
    assert output['user_v1_hold_yesterday_keyline_display_asof'].to_pylist()==[0,0,1]
    assert proof['preserved_rows']==2 and proof['added_dates']==[20261102] and not proof['revised_dates']


def test_revision_recomputes_only_affected_suffix_and_distinguishes_null_nan():
    old=_panel([_bar('20261028',10.,None),_bar('20261029',11.,True),_bar('20261030',12.,False,1)])
    revised=[_bar('20261028',10.,False),_bar('20261029',11.5,False),_bar('20261030',12.,True),_bar('20261102',13.,True)]
    output,proof=binding.reconcile_panel(old,_panel(revised),code='000001.SZ',previous=20261030,target=20261102,q=q)
    assert proof['first_affected_date']==20261029 and proof['preserved_rows']==1
    assert output['kb_label'].to_pylist()==[None,False,True,True]
    missing=_bar('20261029',11.,True);missing['amount']=None
    nan=dict(missing,amount=float('nan'))
    old=_panel([_bar('20261028',10.,None),missing])
    fresh=_panel([_bar('20261028',10.,None),nan])
    _,proof=binding.reconcile_panel(old,fresh,code='000001.SZ',previous=20261030,target=20261030,q=q)
    assert proof['first_affected_date']==20261029


def test_corrected_action_prefix_is_not_replaced_by_stale_f1b_on_append_or_revision():
    def actions(table, statuses, reasons):
        table=table.append_column('user_v1_sell_signal_daily',pa.array([1.0]*len(table)))
        table=table.append_column('kb_action_with_position_status',pa.array(statuses,type=pa.string()))
        return table.append_column('kb_action_reasons',pa.array(reasons,type=pa.string()))
    old=actions(_panel([_bar('20261028',10.,True),_bar('20261029',11.,True),_bar('20261030',12.,True)]),
        ['CONFLICTING_OBSERVATIONS']*3,['已核原式卖点']*3)
    stale=actions(_panel([_bar('20261028',10.,True),_bar('20261029',11.,True),
                          _bar('20261030',12.,True),_bar('20261102',13.,True)]),
        ['OBSERVED_SCORE_HOLD_CONDITIONAL']*3+['CONFLICTING_OBSERVATIONS'],
        ['旧版漏卖点']*3+['新增已核原式卖点'])
    append,proof=binding.reconcile_panel(old,stale,code='000001.SZ',previous=20261030,target=20261102,q=q)
    assert proof['first_affected_date']==20261102
    assert append['kb_action_with_position_status'].to_pylist()==['CONFLICTING_OBSERVATIONS']*4
    assert append['kb_action_reasons'].to_pylist()==['已核原式卖点']*3+['新增已核原式卖点']
    revision=stale.set_column(stale.schema.get_field_index('close'),'close',pa.array([10.,11.,12.5,13.]))
    corrected=revision.set_column(revision.schema.get_field_index('kb_action_reasons'),'kb_action_reasons',
        pa.array(['旧版漏卖点','旧版漏卖点','修订已核原式卖点','新增已核原式卖点']))
    corrected=corrected.set_column(corrected.schema.get_field_index('kb_action_with_position_status'),
        'kb_action_with_position_status',pa.array(['OBSERVED_SCORE_HOLD_CONDITIONAL']*2+['CONFLICTING_OBSERVATIONS']*2))
    output,proof=binding.reconcile_panel(old,corrected,code='000001.SZ',previous=20261030,target=20261102,q=q)
    assert proof['first_affected_date']==20261030
    assert output['kb_action_reasons'].to_pylist()==['已核原式卖点']*2+['修订已核原式卖点','新增已核原式卖点']
    assert output['kb_action_with_position_status'].to_pylist()==['CONFLICTING_OBSERVATIONS']*4


def test_reconcile_rejects_missing_old_key_or_schema_drift():
    old=_panel([_bar('20261029',10.,True),_bar('20261030',11.,True)])
    fresh=_panel([_bar('20261030',11.,True)])
    with pytest.raises(q.QfqGateError,match='OUTPUT_KEYS_CONFLICT'):
        binding.reconcile_panel(old,fresh,code='000001.SZ',previous=20261030,target=20261102,q=q)
    with pytest.raises(q.QfqGateError,match='OUTPUT_SCHEMA_CHANGED'):
        binding.reconcile_panel(old,old.drop(['kb_label']),code='000001.SZ',previous=20261030,target=20261102,q=q)


def test_sidecar_reuses_only_causal_input_identical_prefix(tmp_path):
    def side(path,rows):
        table=pa.Table.from_pylist(rows,schema=pa.schema([('ts_code',pa.string()),('trade_date',pa.string()),
            ('diagnostics_json',pa.string()),('prefix_input_sha256',pa.string())]))
        table=table.replace_schema_metadata({b'v4.a_share.kb_gap_diagnostics.v1':json.dumps({'symbol':'000001.SZ'}).encode()})
        pq.write_table(table,path);return _ref(path)
    def row(date,diagnostic,prefix):return {'ts_code':'000001.SZ','trade_date':date,
        'diagnostics_json':diagnostic,'prefix_input_sha256':prefix}
    old=side(tmp_path/'old.parquet',[row('20261029','old-1','a'*64),row('20261030','old-2','b'*64)])
    fresh=side(tmp_path/'new.parquet',[row('20261029','new-1','a'*64),
        row('20261030','new-2','b'*64),row('20261102','new-3','c'*64)])
    result=binding.reconcile_sidecar(old,fresh,code='000001.SZ',first_affected_date=20261102,
                                    destination=tmp_path/'merged.parquet',q=q)
    table=pq.read_table(result['path']);meta=json.loads(table.schema.metadata[b'v4.a_share.kb_gap_diagnostics.v1'])
    assert table['diagnostics_json'].to_pylist()==['old-1','old-2','new-3']
    assert meta['inherited_prefix']['source']==old and meta['inherited_prefix']['rows']==2
    assert meta['inherited_prefix']['cross_generation_n_checkpoint_reused'] is False
    assert meta['continuation']==result['continuation']=={'fresh_source':fresh,
        'first_affected_date':20261102,'prefix_input_sha256':'b'*64,'prefix_through_date':20261030}
    bad=side(tmp_path/'bad.parquet',[row('20261029','new-1','a'*64),
        row('20261030','new-2','d'*64),row('20261102','new-3','c'*64)])
    with pytest.raises(q.QfqGateError,match='SIDECAR_PREFIX_INPUT_CHANGED'):
        binding.reconcile_sidecar(old,bad,code='000001.SZ',first_affected_date=20261102,
                                 destination=tmp_path/'bad-merged.parquet',q=q)
    same=side(tmp_path/'same.parquet',[row('20261029','other-1','a'*64),row('20261030','other-2','b'*64)])
    unchanged=binding.reconcile_sidecar(old,same,code='000001.SZ',first_affected_date=None,
                                       destination=tmp_path/'whole-merged.parquet',q=q)
    assert pq.read_table(unchanged['path'])['diagnostics_json'].to_pylist()==['old-1','old-2']
    assert unchanged['continuation']['fresh_source']==same and unchanged['inherited_prefix']['rows']==2


def test_idle_asof_changes_only_three_display_fields_and_keeps_unknown():
    table=_panel([_bar('20261029',10.,True),_bar('20261030',11.,True,1)])
    table=table.append_column('user_v1_white_yellow_death_cross',pa.array([0,None],type=pa.int8()))
    table=table.append_column('user_v1_break_prev_low',pa.array([0,0],type=pa.int8()))
    output=binding.advance_unchanged_asof(table,previous=20261030,target=20261102,
                                          unchanged_codes={'000001.SZ'},q=q)
    assert output['user_v1_hold_yesterday_keyline_display_asof'].to_pylist()==[0,0]
    assert output['user_v1_break_yesterday_keyline_display_asof'].to_pylist()==[0,0]
    assert output['user_v1_sell_signal_display_asof'].to_pylist()==[0,None]
    for name in set(table.column_names)-set(binding._ASOF_FIELDS):
        assert table[name].equals(output[name])
    assert binding.advance_unchanged_asof(table,previous=20261030,target=20261030,
                                          unchanged_codes={'000001.SZ'},q=q).equals(table)


def test_original_owner_repeated_same_input_returns_previous_pair_without_recompute(tmp_path,monkeypatch):
    from ops import research_panel_turnover as turnover_module
    root=Path(q.__file__).resolve().parents[1]
    full_ref=_ref(root/'contracts/a_share_kb_full_research_v1.json')
    contract=q.full_research_contract(full_ref)
    data=tmp_path/'data';data.mkdir();runs=tmp_path/'runs';runs.mkdir()
    input_path=q.input_path(data);input_path.parent.mkdir(parents=True)
    calendar=_ref(root/'contracts/market_calendar_2026.json');adapter=_ref(root/'contracts/trading_calendar.py')
    official=_write(tmp_path/'official.json',{'target_date':20261030,'calendar':calendar,'calendar_adapter':adapter})
    sync=_write(tmp_path/'sync.json',{'target_date':20261030,'official_daily_source':{'input_ref':official}})
    config=_write(tmp_path/'config.json',{'prequery_sync_ref':sync})
    item={'raw_files':[{'path':str(tmp_path/'raw.day'),'sha256':'d'*64}],
          'events':[],'event_coverage_complete':True,'history_start_date':20200101}
    snapshot={'asof_date':20261030,'convention':'C','price_basis':'QFQ_ASOF','volume_basis':'QFQ_EVENT_VOLUME',
        'amount_basis':'RAW_TURNOVER','symbols':{'000001.SZ':item},'original_target_codes':['000001.SZ'],
        'effective_target_codes':['000001.SZ'],'lifecycle_addition_codes':[],'retained_history_codes':[],
        'legacy_preservation_codes':[],'quarantine_symbols':{},'research_cache_configuration':config}
    snapshot_ref=_write(input_path,snapshot)
    driver=tmp_path/'driver.py';driver.write_text('driver')
    formula=tmp_path/'formula.py';formula.write_text('formula')
    csv=tmp_path/'contract.csv';csv.write_text('contract')
    source_identity=q.generation_identity(snapshot,driver,formula,csv)
    identity={**source_identity,'turnover_input_sha256':'e'*64,'research_scope':'ADMITTED_A_SHARE',
        'full_research_contract_sha256':full_ref['sha256'],'single_feedback_enabled':True,
        'single_action_enabled':True,'single_yidong_enabled':True,'confirmed_gap_enabled':True,
        'confirmed_gap_contract_sha256':q.gap_rule_sha256(),'confirmed_gap_helper_sha256':q.gap_helper_sha256s(),
        'confirmed_gap_rebuild_contract_sha256':q.sha(root/'contracts/a_share_kb_rebuild_brick_v1.json'),
        'confirmed_gap_components_contract_sha256':q.sha(root/'contracts/a_share_kb_signal_components_v1.json'),
        'confirmed_gap_snapshot_file_sha256':snapshot_ref['sha256'],'n_structure_enabled':True,**q._n_sha256s()}
    base=q._full_research_schema_declaration(pa.schema([pa.field('ts_code',pa.string()),
        pa.field('trade_date',pa.string())]),contract,full_ref['sha256'])
    roles={};pointers={}
    for role in ('selector','backtest'):
        panel=tmp_path/(role+'.parquet');pq.write_table(pa.Table.from_arrays(
            [pa.array([],type=f.type) for f in base],schema=base),panel);roles[role]=panel
        pointer=tmp_path/(role+'.txt');pointer.write_text(str(panel)+'\n');pointers[role]=pointer
    receipt_path=tmp_path/'baseline-receipt.json';generation='c'*64
    receipt={'status':'CANDIDATE_READY','target_date':20261030,'research_scope':'ADMITTED_A_SHARE',
        'adjustment_snapshot':snapshot_ref,'snapshot_file_sha256':snapshot_ref['sha256'],
        'input_sha256':source_identity['input_sha256'],'adapter_sha256':source_identity['adapter_sha256'],
        'full_research_contract_sha256':full_ref['sha256'],'generation_id':generation,
        'candidates':{r:str(p) for r,p in roles.items()},'candidate_sha256':{r:q.sha(p) for r,p in roles.items()},
        'turnover_input_sha256':'e'*64}
    receipt_ref=_write(receipt_path,receipt)
    meta={**identity,'generation_id':generation,'generation_manifest_path':str(receipt_path),
          'snapshot_file_sha256':snapshot_ref['sha256'],'asof_date':20261030}
    monkeypatch.setattr(q,'panel_contract',lambda _:dict(meta))
    monkeypatch.setattr(q,'load_snapshot',lambda *_:snapshot)
    monkeypatch.setattr(q,'authorities',lambda *_:(object(),object()))
    monkeypatch.setattr(q,'accepted_history_retention',lambda *_:None)
    monkeypatch.setattr(q,'_same_asof_repair_reference',lambda *_:None)
    monkeypatch.setattr(q,'rebuild_symbol',lambda *_:pytest.fail('unchanged stock recalculated'))
    monkeypatch.setattr(q,'spool_current',lambda *_:pytest.fail('unchanged panel copied'))
    fake=type('Turnover',(),{'identity':'e'*64,'failure':None,'verify_binding':lambda self:None})()
    monkeypatch.setattr(turnover_module,'load_daily',lambda *_:fake)
    descriptor={'schema':'a_share_kb_daily_continuation_v1','status':'PREPARED_NOT_CONSUMED',
        'target_date':20261030,'baseline_receipt':receipt_ref,'baseline_snapshot':snapshot_ref,
        'baseline_adapter':_ref(Path(q.__file__).resolve()),'baseline_roles':{r:_ref(p) for r,p in roles.items()},
        'calendar':calendar,'calendar_adapter':adapter,'historical_PIT':False,**q.FLAGS}
    descriptor_ref=_write(tmp_path/'continuation.json',descriptor)
    args=dict(driver_path=driver,formula_path=formula,tdx_root=tmp_path/'tdx',data_root=data,
        pointers=pointers,contract_csv=csv,return_root=runs,target=20261030,publish=False,
        full_research_contract_ref=full_ref,full_research_isolation_root=tmp_path,
        full_research_continuation_ref=descriptor_ref)
    first=q.run_daily_rebuild(**args);second=q.run_daily_rebuild(**args)
    assert first==second and first['status']=='CANDIDATE_REUSED_IDENTICAL'
    assert first['generation_id']==generation and first['computed_stock_count']==first['copied_panel_bytes']==0
    assert all(pointers[r].read_text().strip()==str(roles[r]) for r in roles)
    meta['single_action_authority_sha256']='f'*64
    with pytest.raises(q.QfqGateError,match='CALCULATION_IDENTITY_CHANGED'):
        q.run_daily_rebuild(**args)
    meta['single_action_authority_sha256']=identity['single_action_authority_sha256']
    monkeypatch.setattr(binding,'bind',lambda *_args,**_kwargs:{'codes':{'000001.SZ':{}}})
    with pytest.raises(q.QfqGateError,match='FULL_DAILY_INCREMENTAL_STATE_UNAVAILABLE'):
        q.run_daily_rebuild(**args)
