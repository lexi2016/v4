"""HK source/window regression: preserve field-specific UNKNOWN, never infer a vendor."""
import copy

import pytest

from upstreams.v3_shared_data.shared_data.hk_panel_audit import inspect_source_window


class Policy:
    def __init__(self, holds=(), corrections=()):
        self.holds = set(holds)
        self.corrections = set(corrections)

    def held_fields(self, code, date, required_fields):
        return [field for field in required_fields if (code, date, field) in self.holds]

    def field_admission(self, code, date, field):
        return ('CORRECTED_TDX_RETROSPECTIVE_CHANNEL'
                if (code, date, field) in self.corrections
                else 'UNDISPUTED_KEEP_C_EXISTING_POLICY')

    def effective_values(self, code, date, values, *, source='C'):
        return dict(values)


def bar(date, *, code='HK.00001', source='tdx_vipdoc_71_day', history_source=None,
        high=10.0, close=9.0, trade=100, status=None, scale=None):
    return dict(code_norm=code, trade_date_compact=date, source=source,
                history_source=history_source, high=high, close=close, trade=trade,
                volume_unit_status=status, native_fields={'scale_applied': scale})


def evaluate(rows, requirements, policy=None):
    return inspect_source_window(rows, code='HK.00001', field_sessions=requirements,
                                 policy=policy or Policy())


def test_null_history_source_falls_back_to_recorded_source_without_claiming_vendor_or_unit():
    rows=[bar('20261028'),bar('20261029'),bar('20261030')]
    evidence=evaluate(rows, {'trade':['20261028','20261029','20261030']})
    assert evidence['status']=='CLEAR'
    assert evidence['fields']['trade']['recorded_sources']==['tdx_vipdoc_71_day']
    assert evidence['unit_status']=='NOT_ATTESTED_BY_THIS_CHECK'
    assert evidence['source_status']=='RECORDED_TAGS_ONLY_NOT_VENDOR_PROOF'


def test_mixed_source_and_approximate_scale_are_rejected_only_in_their_dependency_window():
    rows=[bar('20260929',source='pytdx_exhq_history_recovery', history_source='PYTDX_HQ_DAILY',
              status='APPROXIMATE_SCALE_ONLY; NOT_LOSSLESS; SDK_UNIT_UNSPECIFIED'),
          bar('20261028'),bar('20261029'),bar('20261030')]
    price=evaluate(rows, {'high':['20260929','20261028'], 'close':['20261030']})
    assert price['status']=='UNKNOWN'
    assert 'MIXED_RECORDED_SOURCES' in price['reasons']
    vol=evaluate(rows, {'trade':['20261028','20261029','20261030']})
    assert vol['status']=='CLEAR'
    assert evaluate(rows, {'trade':['20260929']})['fields']['trade']['reasons']==['APPROXIMATE_OR_LOSSY_SCALE']


def test_absent_source_is_unknown_not_a_value_and_not_a_different_code_global_hold():
    rows=[bar('20261029',source=None),bar('20261030'),bar('20261029',code='HK.00700')]
    ev=evaluate(rows, {'high':['20261029'],'trade':['20261030']})
    assert ev['status']=='UNKNOWN'
    assert ev['fields']['high']['reasons']==['SOURCE_TAG_UNKNOWN']
    assert ev['fields']['trade']['status']=='CLEAR'
    explicitly_unknown=bar('20261029',source='tdx_vipdoc_71_day',history_source='UNKNOWN')
    assert evaluate([explicitly_unknown],{'high':['20261029']})['status']=='UNKNOWN'
    invalid=inspect_source_window(rows,code='BAD-CODE',field_sessions={'high':['20261029']},policy=Policy())
    assert invalid['reasons']==['SOURCE_CODE_INVALID']


def test_old_held_field_remains_unknown_without_polluting_other_field_or_dates():
    held={('HK.00001','20260805','trade')}
    rows=[bar('20260805'),bar('20260806')]
    evidence=evaluate(rows, {'high':['20260805','20260806'], 'trade':['20260805']},Policy(held))
    assert evidence['fields']['high']['status']=='CLEAR'
    assert evidence['fields']['trade']['reasons']==['HISTORY_FIELD_QUARANTINED']
    assert evaluate(rows, {'trade':['20260806']},Policy(held))['status']=='CLEAR'


def test_true_hk_calendar_missing_sessions_are_not_replaced_by_old_rows():
    rows=[bar('20261002'),bar('20261008'),bar('20261009'),bar('20261012')]
    dates=['20261005','20261006','20261007','20261008','20261009']
    ev=evaluate(rows, {'high':dates})
    assert ev['status']=='UNKNOWN'
    assert ev['fields']['high']['missing_sessions']==dates[:3]


def test_duplicate_conflicting_scale_and_missing_policy_fail_closed():
    rows=[bar('20261029',scale=1),bar('20261030',scale=100)]
    assert 'SCALE_MISMATCH' in evaluate(rows,{'trade':['20261029','20261030']})['reasons']
    duplicate=copy.deepcopy(rows)+[copy.deepcopy(rows[0])]
    assert 'DUPLICATE_SESSION_ROW' in evaluate(duplicate,{'trade':['20261029','20261030']})['reasons']
    ev=inspect_source_window(rows, code='HK.00001',field_sessions={'trade':['20261030']},policy=None)
    assert 'HISTORY_POLICY_UNAVAILABLE' in ev['reasons']


def test_sparse_corrected_price_cannot_impersonate_its_native_source():
    correction={('HK.00001','20261029','high')}
    rows=[bar('20261029'),bar('20261030')]
    evidence=evaluate(rows,{'high':['20261029','20261030']},Policy(corrections=correction))
    assert evidence['status']=='UNKNOWN'
    assert 'MIXED_RECORDED_SOURCES' in evidence['reasons']
    assert evaluate(rows,{'trade':['20261029','20261030']},Policy(corrections=correction))['status']=='CLEAR'


def test_rebound_consumer_preserves_independent_volume_when_price_source_is_mixed():
    import pandas as pd
    from v4.manager_research.workspace_plan import rebound_history_rows
    dates=[f'202608{day:02d}' for day in range(1,31)]+[f'202609{day:02d}' for day in range(1,31)]
    rows=[bar(date) for date in dates]
    rows[10].update(source='pytdx_exhq_history_recovery',history_source='PYTDX_HQ_DAILY',
                    volume_unit_status='APPROXIMATE_SCALE_ONLY; NOT_LOSSLESS')
    frame=pd.DataFrame(rows)
    result=rebound_history_rows(frame,['HK.00001'],{'prior60':dates,'previous5':dates[-5:]},
                                source_frame=frame,source_policy=Policy())['HK.00001']
    assert result['prior60_high'] is None
    assert result['previous5_mean']==100
    assert 'REBOUND_HIGH_SOURCE_WINDOW_UNVERIFIED' in result['gaps']
    assert result['source_field_window_evidence']['volume']['status']=='CLEAR'


def test_rebound_consumer_does_not_bridge_three_hk_exchange_days():
    import pandas as pd
    from v4.manager_research.workspace_plan import rebound_history_rows, rebound_history_sessions
    sessions=rebound_history_sessions('20261102')
    assert {'20261005','20261006','20261007'}.issubset(sessions['prior60'])
    rows=[bar(date) for date in sessions['prior60'] if date not in {'20261005','20261006','20261007'}]
    frame=pd.DataFrame(rows)
    result=rebound_history_rows(frame,['HK.00001'],sessions,source_frame=frame,source_policy=Policy())['HK.00001']
    assert result['prior60_high'] is None
    assert result['prior60_count']==57
    assert result['previous5_mean']==100
    assert result['source_field_window_evidence']['price']['fields']['high']['missing_sessions']==[
        '20261005','20261006','20261007']


@pytest.mark.parametrize('all_held',[False,True,None],ids=['one-held','all-held','unexplained-removal'])
def test_actual_rebound_consumer_keeps_good_code_and_does_not_bridge_mixed_missing_history(monkeypatch,all_held):
    import pandas as pd
    from pathlib import Path
    from v4.manager_research import workspace_plan
    from upstreams.v3_shared_data.shared_data import hk_history_resolution as resolution_module
    from upstreams.v3_shared_data.shared_data import hk_security_master

    day='20261030'
    sessions=workspace_plan.rebound_history_sessions(day)
    history=sessions['prior60']
    assert {'20261005','20261006','20261007'}.issubset(history)
    rows=[]
    for code in ('HK.00001','HK.00700','HK.00941','HK.02318'):
        for date in [*history,day]:
            if code=='HK.00700' and date in {'20261005','20261006','20261007'}:
                continue
            if code=='HK.00941' and date==history[-3]:
                continue
            row=bar(date,code=code,source='FUTU',history_source='FUTU',high=100,close=75,trade=100)
            row.update(name=code,open=75.0,low=70.0,amount=12_000_000.0,pre_close=76.0)
            if date==day:row['trade']=200
            if code=='HK.00700' and date=='20260929':
                row.update(source='pytdx_exhq_history_recovery',history_source='PYTDX_HQ_DAILY',
                           volume_unit_status='APPROXIMATE_SCALE_ONLY; NOT_LOSSLESS')
            rows.append(row)
    frame=pd.DataFrame(rows)
    panel={'owner':'TEST','panel_path':'/test/panel.parquet','panel_sha256':'a'*64,
           'panel_manifest_path':'/test/manifest.json','panel_manifest_sha256':'b'*64,
           'panel_max_date':day,'panel_rows':len(frame),'panel_code_count':4,'source_contract':'TEST'}
    master={'owner':'TEST','manifest_path':'/test/master.json','manifest_sha256':'c'*64,
            'artifact_path':'/test/master.csv','artifact_sha256':'d'*64,
            'captured_at':'2026-10-30T17:00:00+08:00',
            'names':{code:{'name':code} for code in ('HK.00001','HK.00700','HK.00941','HK.02318')}}
    monkeypatch.setattr(workspace_plan,'screen_context',lambda context:context)
    monkeypatch.setattr(workspace_plan,'_read_hk02_panel_witness',lambda *a,**k:(panel,[]))
    monkeypatch.setattr(workspace_plan,'_screen_security_master_witness',lambda *a,**k:(master,{}))
    monkeypatch.setattr(workspace_plan,'_screen_panel_volume_evidence',lambda *a,**k:{
        'status':'OWNER_VERIFIED','unit_status':'TEST_UNIT','scale_applied':1,'gaps':[]})
    monkeypatch.setattr(workspace_plan,'_read_hk02_daily_supplement_witness',lambda *a,**k:None)
    monkeypatch.setattr(pd,'read_parquet',lambda *a,**k:frame.copy())
    monkeypatch.setattr(hk_security_master,'HKSecurityMasterReadError',type('TestMasterError',(ValueError,),{}),raising=False)
    held_day=sessions['previous5'][-1]
    blocked={'HK.00001','HK.00700','HK.00941','HK.02318'} if all_held else {'HK.02318'}
    fake=Policy({(code,held_day,'trade') for code in blocked} if all_held is not None else set());fake.check_panel=lambda sha:None
    monkeypatch.setattr(resolution_module,'policy_for_shared',lambda root:fake)
    def guard(frame,*a,**kw):
        out=frame.loc[~frame.code_norm.isin(blocked)].copy()
        out.attrs['history_resolution_proofs']=['fixture-proof']
        out.attrs['history_resolution_holds']=({code:[{'date':held_day,'fields':['trade'],'reason':'HK_HISTORY_FIELD_QUARANTINED'}] for code in blocked} if all_held is not None else {})
        return out
    monkeypatch.setattr(resolution_module,'guard_rebound_frame',guard)
    result=workspace_plan.read_rebound_screen(Path('/test'),{
        'market_session':day,'plan_trade_date':'20261102','research_cutoff':'2026-10-30T18:00:00+08:00',
        'screen_phase':'TEST','screen_session_policy':'TEST'})
    cards={r['code']:r for r in [*result['cards'],*result['pending']]}
    assert cards, result['gaps']
    if all_held:
        assert result['coverage']['input_candidate_count']==4
        assert result['coverage']['history_pending_count']==4
        assert set(result['coverage']['pending_codes'])==blocked
        assert all(row['strict_two_gate_oversold_5dvolume'] is None for row in cards.values())
        return
    if all_held is None:
        assert result['coverage']['input_candidate_count']==4
        assert result['coverage']['unexplained_guard_target_code_count']==1
        assert cards['HK.02318']['history_raw_status']=='HK_HISTORY_GUARD_TARGET_ROW_UNEXPLAINED'
        assert cards['HK.02318']['history_resolution_holds']==[]
        return
    assert cards['HK.00001']['oversold_flag'] is True
    assert cards['HK.00001']['volume_ratio_5d']==2
    assert cards['HK.00001']['amount_hkd'] is None
    assert cards['HK.00001']['amount_native']==12_000_000
    assert cards['HK.00700']['oversold_flag'] is None
    assert cards['HK.00700']['volume_ratio_5d']==2
    assert cards['HK.00700']['previous20_mean_volume_background'] is None
    assert cards['HK.00700']['volume_ratio_20d_background'] is None
    assert cards['HK.00700']['history_status']=='PARTIAL_UNKNOWN'
    assert cards['HK.00700']['strict_two_gate_oversold_5dvolume'] is None
    assert cards['HK.00941']['recent_3_session_return_pct'] is None
    assert cards['HK.00941']['recent_5_session_return_pct'] is None
    assert cards['HK.00941']['volume_ratio_5d'] is None
    assert cards['HK.02318']['history_status']=='PARTIAL_UNKNOWN'
    assert cards['HK.02318']['strict_two_gate_oversold_5dvolume'] is None
    assert cards['HK.02318']['close']==75
    assert cards['HK.02318']['volume_ratio_5d'] is None
    assert cards['HK.02318']['history_resolution_holds'][0]['date']==held_day
    assert cards['HK.02318']['source_field_window_evidence']['price']['status']=='CLEAR'
    assert cards['HK.02318']['source_field_window_evidence']['volume5']['status']=='UNKNOWN'
    assert result['coverage']['input_candidate_count']==4
    assert 'HK.02318' in result['coverage']['pending_codes']


def test_native_oversold_uses_null_fallback_and_preserves_unit_metadata(monkeypatch,tmp_path):
    import hashlib
    from types import SimpleNamespace
    import pandas as pd
    from contracts.trading_calendar import load_market_calendar,previous_session
    from v4.manager_workbench.inputs import native
    from v4.manager_workbench.engines import oversold as engine
    from upstreams.v3_shared_data.shared_data import hk_history_resolution as resolution_module

    date='20261030';cal=load_market_calendar();wanted=[];cursor=date
    for _ in range(61):
        wanted.append(cursor);cursor=previous_session(cal,cursor,market='hk_securities')
    wanted.reverse();assert '20260929' in wanted
    rows=[]
    for code in ('HK.00001','HK.00700'):
        for day in wanted:
            row=bar(day,code=code,high=100,close=75,trade=100)
            if code=='HK.00700' and day=='20260929':
                row.update(source='pytdx_exhq_history_recovery',history_source='PYTDX_HQ_DAILY',
                           volume_unit_status='APPROXIMATE_SCALE_ONLY; NOT_LOSSLESS')
            rows.append(row)
    panel_file=tmp_path/'panel.parquet';pd.DataFrame(rows).to_parquet(panel_file,index=False)
    master_file=tmp_path/'master.csv';master_file.write_text('code\nHK.00001\nHK.00700\n')
    panel_sha=hashlib.sha256(panel_file.read_bytes()).hexdigest()
    master_sha=hashlib.sha256(master_file.read_bytes()).hexdigest()
    stamp='2026-10-30T18:00:00+08:00'
    manifest={'panel_max_date':date,'panel_relative':'panel.parquet','research_only':True,'production_allowed':False,
              'manifest_prepared_at':stamp,'panel_sha256':panel_sha}
    master={'artifact_relative':'master.csv','artifact_sha256':master_sha,'row_count':2,'captured_at':stamp}
    pin={'manifest_relative':'panel-manifest.json','manifest_sha256':'a'*64,
         'panel_relative':'panel.parquet','available_at':stamp}
    context=SimpleNamespace(source_sessions={'hk_price':date},target_date='20261102',
        cutoff='2026-11-02T08:00:00+08:00',phase=SimpleNamespace(value='NEXT_DAY'),
        model_dump=lambda **kwargs:{})
    adapter=native.NativeAdapters(SimpleNamespace(shared_root=tmp_path))
    monkeypatch.setattr(adapter,'_binding',lambda *a,**k:pin)
    monkeypatch.setattr(adapter,'_json',lambda *a,**k:(manifest,'a'*64))
    monkeypatch.setattr(adapter,'_manifest',lambda *a,**k:({'artifact_relative':'master.csv','manifest_relative':'master.json'},master,'b'*64))
    monkeypatch.setattr(adapter,'_ref',lambda *a,**k:SimpleNamespace(evidence_id='fixture'))
    monkeypatch.setattr(adapter,'membership',lambda context:(set(),None,[]))
    monkeypatch.setattr(adapter,'_member',lambda record,*a:record)
    monkeypatch.setattr(adapter,'_engine_shape',lambda value:value)
    monkeypatch.setattr(native,'batch',lambda context,lane,records,refs,scope,*a,**k:SimpleNamespace(records=records))
    class TestPolicy(Policy):
        def check_panel(self,sha): assert sha==panel_sha
        def encode_proof(self,proof): return 'fixture-proof'
        def guard_frame(self,frame,**kwargs):
            out=frame.copy();out.attrs['history_resolution_proof']={};out.attrs['history_resolution_holds']={};return out
    monkeypatch.setattr(resolution_module,'policy_for_shared',lambda root:TestPolicy())
    def metrics(context,row):
        if row.get('window_gap'):raise ValueError(row['window_gap'])
    monkeypatch.setattr(engine,'window_metrics',metrics)
    result=adapter.oversold(context,panel_only=True)
    actual={r['symbol']:r for r in result.records}
    assert not actual['HK.00001'].get('window_gap')
    assert actual['HK.00700']['window_gap']=='PANEL_MIXED_SOURCE_COMPARISON_UNVERIFIED'
    assert actual['HK.00700']['panel_field_window_evidence']['volume']['status']=='CLEAR'
    old=next(r for r in actual['HK.00700']['bars'] if r['date']=='20260929')
    assert 'NOT_LOSSLESS' in old['source_metadata']['volume_unit_status']


def test_hk_history_reread_verifies_same_sources_and_unchanged_guard_sha(monkeypatch,tmp_path):
    import hashlib,json
    import pandas as pd
    from pathlib import Path
    from domains import manager_close_rebound as consumer
    from v4.manager_research import workspace_plan
    from upstreams.v3_shared_data.shared_data import hk_history_resolution as resolution_module, hk_panel_audit
    sessions=workspace_plan.rebound_history_sessions('20261102')
    rows=[bar(date,source='FUTU',history_source='FUTU') for date in sessions['prior60']]
    frame=pd.DataFrame(rows)
    root=tmp_path/'root';asset=root/'assets/hk_0_2';(asset/'panels/test').mkdir(parents=True)
    panel=asset/'panels/test/panel.parquet';frame.to_parquet(panel,index=False)
    def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
    manifest=asset/'panels/test/manifest.json'
    manifest.write_text(json.dumps(dict(asset_schema_version='v3_shared_data.hk_0_2_panel_asset.v2',
        source_contract='tdx_vipdoc_71_day+verified_zero_trade_repairs',panel_max_date=sessions['panel_session'],
        panel_relative='panels/test/panel.parquet',panel_sha256=sha(panel),research_only=True,
        production_allowed=False,buy_gate_updated=False,orders_sent=False)))
    master_manifest=root/'master.json';master_manifest.write_text('{}')
    master_artifact=root/'master.csv';master_artifact.write_text('code\nHK.00001\n')
    refs=[{'artifact_ref':p.relative_to(root).as_posix(),'sha256':sha(p)}
          for p in (manifest,panel,master_manifest,master_artifact)]
    master={'manifest_sha256':sha(master_manifest),'artifact_sha256':sha(master_artifact),
            'captured_at':'2026-10-30T17:00:00+08:00','names':{'HK.00001':{'name':'test'}}}
    monkeypatch.setattr(consumer,'require_authority_root',lambda root:root)
    monkeypatch.setattr(consumer,'authority_root',lambda root:root)
    monkeypatch.setattr(consumer,'authority_binding',lambda root:{'fixture':True})
    monkeypatch.setattr(workspace_plan,'_screen_security_master_witness',lambda *a,**k:(master,{}))
    monkeypatch.setattr(workspace_plan,'rebound_native_evidence',lambda *a,**k:{})
    policy=Policy();policy.check_panel=lambda value:None
    monkeypatch.setattr(resolution_module,'policy_for_shared',lambda root:policy)
    def guard(frame,*a,**k):
        out=frame.copy();out.attrs['history_resolution_proofs']=['fixture-proof'];out.attrs['history_resolution_holds']={};return out
    monkeypatch.setattr(resolution_module,'guard_rebound_frame',guard)
    symbols=workspace_plan.rebound_history_rows(frame,['HK.00001'],sessions,source_frame=frame,source_policy=policy)
    body={'authority_binding':{'fixture':True},'source_files':refs,'trade_date':'20261102',
          'sessions':sessions,'available_at':'2026-11-02T15:31:00+08:00',
          'read_started_at':'2026-11-02T15:30:00+08:00',
          'history_resolution_proofs':['fixture-proof'],'symbols':symbols,
          'source_window_guard_sha256':sha(Path(hk_panel_audit.__file__))}
    consumer._verify_history_sources(body,root)
    tampered=dict(body,source_window_guard_sha256='0'*64)
    with pytest.raises(ValueError,match='REBOUND_HISTORY_SOURCE_GUARD_SHA_MISMATCH'):
        consumer._verify_history_sources(tampered,root)
    bad_proof=dict(body,history_resolution_proofs=[])
    with pytest.raises(ValueError,match='REBOUND_HISTORY_RESOLUTION_PROOF_MISMATCH'):
        consumer._verify_history_sources(bad_proof,root)
    panel.write_bytes(panel.read_bytes()+b'tampered')
    with pytest.raises(ValueError,match='REBOUND_HISTORY_SOURCE_SHA_MISMATCH'):
        consumer._verify_history_sources(body,root)
