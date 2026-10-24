"""Versioned user formula and full-response binding deltas only."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import pyarrow as pa
import pytest
from ops import research_panel_qfq as q
from ops import research_panel_adjustment_inputs as inputs


def feature_frame(dea, dif):
    n=len(dea)
    data={column:np.zeros(n,dtype='int8') for column in set(q.USER_FORMULA_COMPONENTS.values())|{'hold_yesterday_keyline','break_yesterday_keyline'}}
    data.update(trade_date=list(range(20260101,20260101+n)),macd_dea=dea,macd_dif=dif,
                primary_buy_signal=np.ones(n,dtype='int8'),macd_above_zero_second_gold=np.ones(n,dtype='int8'))
    return pd.DataFrame(data)


def test_user_level1_requires_second_gold_and_preserves_legacy():
    f=feature_frame([0,1,1,1,1,1,0,1,1],[0,.5,1.5,.5,1.5,1.5,0,.5,1.5])
    f.loc[1,'B3']=1
    got=q.append_user_formula_v1(f,20260109)
    assert got.user_v1_macd_above_zero_second_gold.tolist()==[0,0,0,0,1,0,0,0,0]
    assert got.user_v1_level1_buy_signal.tolist()==[0,1,0,0,1,0,0,0,0]
    assert got.primary_buy_signal.equals(f.primary_buy_signal)
    assert got.macd_above_zero_second_gold.equals(f.macd_above_zero_second_gold)


def test_dynamic_count_zero_window_and_below_gold_literal_oracle():
    # COUNT(X,0) is whole prefix; positive N excludes the reset bar.
    gold=pd.Series([False,True,False,True,False,True,False,True])
    reset=pd.Series([True,False,False,False,True,False,False,False])
    assert q._user_count_since_reset(gold,reset).tolist()==[0,1,1,2,2,1,1,2]
    f=feature_frame([0,-1,-1,-1,-1,-1,-1,-1],[0,-2,0,-2,0,-2,0,-2])
    got=q.append_user_formula_v1(f,20260108)
    # Crosses 2,4,6; count==2 occurs at4 and5, so only the first is M2-.
    assert got.user_v1_macd_below_zero_second_gold.tolist()==[0,0,0,0,1,0,0,0]


def test_today_only_chart_labels_are_separate_from_historical_daily():
    f=feature_frame([0,1,1],[0,0,0]);f['break_yesterday_keyline']=1
    got=q.append_user_formula_v1(f,20260103)
    assert got.user_v1_sell_signal_daily.tolist()==[1,1,1]
    assert got.user_v1_sell_signal_display_asof.tolist()==[0,0,1]
    assert got.user_v1_break_yesterday_keyline_display_asof.tolist()==[0,0,1]
    # All daily label fields are causal under a prefix, independent of display asof.
    prefix=q.append_user_formula_v1(f.iloc[:2],20260102)
    for name in q.USER_FORMULA_SIGNAL_FIELDS:
        if 'display_asof' not in name:assert prefix[name].equals(got[name].iloc[:2])


def test_versioned_schema_adds_nullable_fields_without_retyping_legacy():
    old=pa.schema([pa.field('primary_buy_signal',pa.int16(),nullable=False)])
    new=q.user_formula_schema(old)
    assert new.field('primary_buy_signal')==old.field('primary_buy_signal')
    for name in q.USER_FORMULA_SIGNAL_FIELDS:
        assert new.field(name)==pa.field(name,pa.int8(),nullable=True)
    assert q.user_formula_schema(new)==new


def write_ref(path,value):
    path.write_text(json.dumps(value));return dict(path=str(path),sha256=q.sha(path))


def test_original_nonempty_response_binds_full_prefix_without_collecting(tmp_path):
    code='000156.SZ';response=write_ref(tmp_path/'response.json',dict(code='SZ.000156',return_code=0,rows=[dict(ex_div_date='2001-06-28',forward_adj_factorA=1,forward_adj_factorB=-.05,backward_adj_factorA=1)]))
    metadata=write_ref(tmp_path/'metadata.json',dict(asof_date=20261023,finished_at='2026-10-24T00:00:00Z',symbols={code:dict(status='OK',response=response,row_count=1)}))
    result=inputs.bind_full_response_history_metadata(metadata,{code:dict(history_start_date=20000906)},20261023,tmp_path/'bound.json')
    assert result['gaps']==[] and result['historical_PIT'] is False
    assert result['symbols'][code]['response']==response
    assert inputs.history_event_coverage_bound(result['symbols'][code],20000906,20261023)
    assert 'INFERENCE' in result['symbols'][code]['coverage_basis']


def test_empty_error_and_unsupported_do_not_become_no_event_history(tmp_path):
    symbols={code:dict(status=status) for code,status in [('000001.SZ','EMPTY'),('000002.SZ','ERROR'),('920000.BJ','UNSUPPORTED_MARKET')]}
    metadata=write_ref(tmp_path/'metadata.json',dict(asof_date=20261023,symbols=symbols))
    result=inputs.bind_full_response_history_metadata(metadata,{c:dict(history_start_date=19900101) for c in symbols},20261023,tmp_path/'bound.json')
    assert len(result['gaps'])==3
    assert all(not inputs.history_event_coverage_bound(x,19900101,20261023) for x in result['symbols'].values())


def daily_history_fixture(tmp_path,monkeypatch):
    import struct
    driver,_=q.authorities(Path(__file__).resolve().parents[1]/'ops/vendor/data_layer_daily_formula_increment_update_v1.py',Path(__file__).resolve().parents[1]/'ops/vendor/build_canonical_formula_research_panel.py')
    dates=pd.bdate_range('2024-01-02',periods=280).strftime('%Y%m%d').astype(int).tolist()
    def day(path,ds,base=12):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(b''.join(struct.pack('<IIIIIfII',d,round((base+i/100)*100),round((base+i/100+.2)*100),round((base+i/100-.2)*100),round((base+i/100)*100),1000000.,10000+i,0) for i,d in enumerate(ds)))
        return dict(path=str(path),sha256=q.sha(path))
    active='001283.SZ';retired='000999.SZ';target=dates[-1];old_target=dates[-2]
    archive=day(tmp_path/'frozen_active.day',dates[:-1]);inactive=day(tmp_path/'frozen_retired.day',dates[:230])
    tdx=tmp_path/'tdx';day(tdx/'vipdoc/sz/lday/sz001283.day',dates[-2:],base=30)
    source=write_ref(tmp_path/'source.json',dict(source_resolution=inputs.HISTORY_RESOLUTION,stocks=[dict(code=active,sources=[dict(name='archive',kind='day_bytes',**archive)]),dict(code=retired,sources=[dict(name='archive',kind='day_bytes',**inactive)])]))
    policy=write_ref(tmp_path/'policy.json',dict(name=inputs.HISTORY_RESOLUTION,selection_unit='COMPLETE_SOURCE_BAR',price_or_volume_conversion='NONE'))
    retention=dict(source_config=source,source_policy=policy,archive_refs=[],accepted_evidence=[])
    summary=write_ref(tmp_path/'sync.json',dict(target_keys=[dict(symbol='001283',market=0)],symbol_reconciliation=[]))
    monkeypatch.setattr(inputs,'original_sync_contract',lambda *_:(summary,{},1))
    response=write_ref(tmp_path/'response.json',dict(code='SZ.001283',return_code=0,rows=[dict(ex_div_date=str(dates[1]),forward_adj_factorA=1.,forward_adj_factorB=-.1,backward_adj_factorA=1.)]))
    called=[]
    def metadata(codes,**kw):
        called.extend(codes)
        return dict(asof_date=target,finished_at='2026-10-24T00:00:00Z',symbols={active:dict(status='OK',response=response,row_count=1)})
    monkeypatch.setattr(inputs,'collect_metadata',metadata)
    return driver,dates,tdx,retention,called


def test_daily_binding_keeps_archive_only_inactive_and_appends_native_whole_row(tmp_path,monkeypatch):
    driver,dates,tdx,retention,called=daily_history_fixture(tmp_path,monkeypatch)
    root=tmp_path/'inputs';root.mkdir()
    bindings=inputs.raw_bindings(tdx,driver,root/'raw.json',target=dates[-1],retained_history=retention)
    assert set(bindings)=={'001283.SZ','000999.SZ'}
    raw=q.resolved_raw_history('001283.SZ',bindings['001283.SZ'],dates[-1],driver)
    assert raw.trade_date.tolist()==dates
    assert raw.iloc[-2].raw_source_role=='archive' and raw.iloc[-1].raw_source_role=='native'
    snapshot=inputs.prepare_snapshot(tdx_root=tdx,data_root=tmp_path/'data',target=dates[-1],driver=driver,retained_history=retention,required_start={'001283.SZ':dates[0],'000999.SZ':dates[0]})
    assert called==['001283.SZ']
    assert snapshot['retained_history_codes']==['000999.SZ']
    assert snapshot['history_retention_binding']==retention
    assert set(q.load_snapshot(q.input_path(tmp_path/'data'),dates[-1])['symbols'])=={'001283.SZ'}


def test_daily_original_producer_preserves_accepted_history_namespace_and_inactive_rows(tmp_path,monkeypatch):
    driver,dates,tdx,retention,called=daily_history_fixture(tmp_path,monkeypatch)
    root=tmp_path/'old_input';root.mkdir()
    bindings=inputs.history_raw_bindings(retention,root/'raw.json',driver,dates[-2])
    frames=[]
    for code,item in bindings.items():
        item['events']=[];frames.append(q.rebuild_symbol(code,item,dates[-2],driver))
    old=pd.concat(frames,ignore_index=True)
    # Use explicit nullable historic context, with real old user labels.
    core=['ts_code','trade_date','open','high','low','close','volume','amount','pre_close','BBI','J','zge_white_line','zge_yellow_line','B1','B2','B3','formula_source',*q.USER_FORMULA_SIGNAL_FIELDS]
    core=list(dict.fromkeys(core+[c for c in driver.CRITICAL_SELECTOR_FORMULA_COLUMNS if c in old]))
    old=old[core];pointers={};old_keys={};old_inactive={}
    for role in ['selector','backtest']:
        path=tmp_path/(role+'.old.parquet');table=pa.Table.from_pandas(old,preserve_index=False).replace_schema_metadata({q.META_KEY:json.dumps(dict(generation_id='accepted_history',asof_date=dates[-2],history_retention_binding=retention)).encode()})
        import pyarrow.parquet as pq
        pq.write_table(table,path);pointer=tmp_path/'data'/role/'CURRENT.txt';pointer.parent.mkdir(parents=True);pointer.write_text(str(path));pointers[role]=pointer
        old_keys[role]=set(zip(old.ts_code,old.trade_date));old_inactive[role]=table.filter(pa.array(old.ts_code.eq('000999.SZ')))
    contract=tmp_path/'fields.csv';contract.write_text('fixture\n')
    result=q.run_daily_rebuild(driver_path=Path(driver.__file__),formula_path=Path(driver.__file__).with_name("build_canonical_formula_research_panel.py"),tdx_root=tdx,data_root=tmp_path/'data',pointers=pointers,contract_csv=contract,return_root=tmp_path/'runs',target=dates[-1],workers=1,refresh_inputs=True,publish=False)
    assert result['status']=='CANDIDATE_READY'
    assert result['retained_history_codes']==['000999.SZ']
    assert result['retained_history_asof']=={'000999.SZ':dates[-2]}
    for role,path in result['candidates'].items():
        table=pq.read_table(path);actual=table.to_pandas()
        assert old_keys[role]<=set(zip(actual.ts_code,actual.trade_date))
        assert ('001283.SZ',dates[-1]) in set(zip(actual.ts_code,actual.trade_date))
        assert set(q.USER_FORMULA_SIGNAL_FIELDS)<=set(table.schema.names)
        inactive=table.filter(pa.array(actual.ts_code.eq('000999.SZ'))).select(old_inactive[role].schema.names)
        assert inactive.equals(old_inactive[role],check_metadata=False)
        assert result['counts'][role]['retained_a_history_rows']==230
        assert Path(pointers[role].read_text()).name==role+'.old.parquet'


def cached_tdx_capture_fixture(tmp_path,monkeypatch):
    import struct,io,zipfile
    from ops import research_panel_tdx_adjustment_inputs as tdx
    parser=tmp_path/'original_parser.py';parser.write_text('# synthetic parser identity; parser_factory supplies rows\n')
    parser_ref=dict(path=str(parser),sha256=q.sha(parser));monkeypatch.setattr(tdx,'PARSER_SHA',parser_ref['sha256'])
    def archive(payload):
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as z:z.writestr('gbbq',payload)
        return buffer.getvalue()
    raw=tmp_path/'original.gbbq';raw.write_bytes(struct.pack('<I',0))
    zipped=tmp_path/'original.zip';zipped.write_bytes(archive(raw.read_bytes()))
    capture=write_ref(tmp_path/'original.capture.json',dict(source_url=tdx.OFFICIAL_URL,observed_at='2026-10-24T08:37:51+00:00',raw=dict(path=str(raw),sha256=q.sha(raw)),archive=dict(path=str(zipped),sha256=q.sha(zipped)),parser=parser_ref))
    policy=write_ref(tmp_path/'policy.json',dict(policy_id='TDX_GBBQ_CATEGORY1_AFFINE_BJ_V1',controller='synthetic-test-only',category_policy={'1':'PRICE_ACTION_PER10_CASH_RIGHTS_BONUS_AFFINE'}))
    config=dict(source_url=tdx.OFFICIAL_URL,parser=parser_ref,cached_capture=capture,category_policy_receipt=policy)
    write_ref(tmp_path/'qfq_tdx_official_source.json',config)
    return tdx,config,archive(struct.pack('<I',1)+bytes(29))


def test_cached_tdx_capture_rejects_target_after_actual_capture_without_fetch(tmp_path,monkeypatch):
    tdx,config,_=cached_tdx_capture_fixture(tmp_path,monkeypatch)
    def forbidden():raise AssertionError('offline replay must not fetch')
    monkeypatch.setattr(tdx,'_fetch',forbidden)
    with pytest.raises(q.QfqGateError,match='CACHED_TDX_CAPTURE_COVERAGE_INSUFFICIENT:20261024<20261026'):
        tdx.build_fallback(tmp_path,{'920000.BJ':dict(history_start_date=20200101)},20261026)
    assert not (tmp_path/'tdx_official_adjustment_fallback.json').exists()


def test_original_daily_can_refresh_stale_capture_and_binds_new_receipt(tmp_path,monkeypatch):
    from datetime import datetime,timezone
    tdx,config,new_payload=cached_tdx_capture_fixture(tmp_path,monkeypatch)
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return cls(2026,10,26,8,0,0,tzinfo=timezone.utc)
    monkeypatch.setattr(tdx,'datetime',Clock)
    calls=[]
    def fetch():calls.append(1);return new_payload
    class Parser:
        def get_df(self,path):
            return pd.DataFrame([dict(market=2,code='920000',datetime=20261026,category=1,hongli_panqianliutong=1.,peigujia_qianzongguben=0.,songgu_qianzongguben=0.,peigu_houzongguben=0.)])
    result=tdx.build_fallback(tmp_path,{'920000.BJ':dict(history_start_date=20200101)},20261026,fetch=fetch,parser_factory=Parser,refresh_stale_capture=True)
    assert calls==[1]
    item=result['symbols']['920000.BJ'];assert item['event_coverage_complete'] is True
    assert item['history_coverage_end_date']==20261026 and item['events'][0]['ex_date']==20261026
    captures=[x for x in item['source_files'] if '/capture_receipts/' in x['path']]
    assert len(captures)==1
    capture=json.loads(Path(captures[0]['path']).read_text())
    assert capture['coverage_end_date']==20261026 and capture['observed_at'].startswith('2026-10-26')
    original=json.loads(Path(config['cached_capture']['path']).read_text())
    assert capture['raw']['sha256']!=original['raw']['sha256']
    assert q.sha(Path(captures[0]['path']))==captures[0]['sha256']


def test_existing_daily_input_caller_opts_into_original_stale_refresh(tmp_path,monkeypatch):
    from ops import research_panel_tdx_adjustment_inputs as tdx
    summary=write_ref(tmp_path/'sync.json',dict(target_keys=[dict(symbol='920000',market=2)]))
    monkeypatch.setattr(inputs,'original_sync_contract',lambda *_:(summary,{},1))
    monkeypatch.setattr(inputs,'raw_bindings',lambda *a,**kw:{'920000.BJ':dict(history_start_date=20200101)})
    monkeypatch.setattr(inputs,'collect_metadata',lambda *a,**kw:dict(symbols={'920000.BJ':dict(status='UNSUPPORTED_MARKET')},finished_at='2026-10-26T00:00:00Z'))
    def reached(*args,**kwargs):
        assert kwargs.get('refresh_stale_capture') is True
        raise RuntimeError('ORIGINAL_DAILY_REFRESH_ROUTE_REACHED')
    monkeypatch.setattr(tdx,'build_fallback',reached)
    with pytest.raises(RuntimeError,match='ORIGINAL_DAILY_REFRESH_ROUTE_REACHED'):
        inputs.prepare_snapshot(tdx_root=tmp_path/'tdx',data_root=tmp_path/'data',target=20261026,driver=None)


def successful_empty_fixture(tmp_path,*,response_override=None,receipt_override=None):
    response=dict(code='SZ.001283',return_code=0,rows=[]);response.update(response_override or {})
    response_ref=write_ref(tmp_path/'empty.response.json',response)
    receipt=dict(status='EMPTY',response=response_ref,row_count=0,asof_date=20261023,capture_date=20261024)
    receipt.update(receipt_override or {})
    metadata=write_ref(tmp_path/'empty.metadata.json',dict(asof_date=20261023,finished_at='2026-10-24T00:00:00Z',symbols={'001283.SZ':receipt}))
    return metadata,response_ref


def test_successful_identified_empty_is_full_response_zero_event_chart_asof(tmp_path):
    metadata,response=successful_empty_fixture(tmp_path)
    result=inputs.bind_full_response_history_metadata(metadata,{'001283.SZ':dict(history_start_date=20220905)},20261023,tmp_path/'bound.json')
    receipt=result['symbols']['001283.SZ']
    assert result['gaps']==[] and result['historical_PIT'] is False
    assert receipt['provider_response_scope']=='provider_full_response_zero_events/chart-asof'
    assert receipt['provider_event_count']==0 and receipt['response']==response
    assert inputs.history_event_coverage_bound(receipt,20220905,20261023)


@pytest.mark.parametrize('response_override,receipt_override',[({'return_code':-1},{}),({'code':'SZ.001248'},{}),({}, {'row_count':1}),({'rows':[{}]},{}),({}, {'capture_date':20261022}),({}, {'asof_date':20261022})])
def test_empty_identity_status_security_count_and_cutoff_conflicts_reject(tmp_path,response_override,receipt_override):
    metadata,_=successful_empty_fixture(tmp_path,response_override=response_override,receipt_override=receipt_override)
    with pytest.raises(q.QfqGateError):
        inputs.bind_full_response_history_metadata(metadata,{'001283.SZ':dict(history_start_date=20220905)},20261023,tmp_path/'bound.json')


def test_original_history_prepare_snapshot_accepts_bound_successful_empty_without_collection(tmp_path,monkeypatch):
    metadata,response=successful_empty_fixture(tmp_path)
    bound=tmp_path/'bound.json';inputs.bind_full_response_history_metadata(metadata,{'001283.SZ':dict(history_start_date=20220905)},20261023,bound)
    evidence=write_ref(tmp_path/'evidence.json',dict(test=True))
    summary=write_ref(tmp_path/'sync.json',dict(target_keys=[dict(symbol='001283',market=0)],symbol_reconciliation=[]))
    monkeypatch.setattr(inputs,'original_sync_contract',lambda *_:(summary,{},1))
    monkeypatch.setattr(inputs,'raw_bindings',lambda *a,**kw:{'001283.SZ':dict(history_start_date=20220905,compute_start_date=20220905,raw_files=[],history_extension=True)})
    def forbidden(*a,**kw):raise AssertionError('history input binding must remain offline')
    monkeypatch.setattr(inputs,'collect_metadata',forbidden)
    history=dict(binding_ref=evidence,source_config=evidence,source_policy=evidence,adjustment_metadata=dict(path=str(bound),sha256=q.sha(bound)),archive_refs=[],accepted_evidence=[])
    result=inputs.prepare_snapshot(tdx_root=tmp_path/'tdx',data_root=tmp_path/'data',target=20261023,driver=None,history_extension=history)
    item=result['symbols']['001283.SZ']
    assert item['events']==[] and item['event_coverage_complete'] is True
    assert item['provider_response_scope']=='provider_full_response_zero_events/chart-asof'
    assert result['historical_PIT'] is False
