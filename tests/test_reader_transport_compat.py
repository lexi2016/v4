import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import pandas as pd
import pyarrow as pa
import pytest
from ops import research_panel_logical as logical
from ops import research_panel_reader_compat as compat

ROOT=Path(__file__).resolve().parents[1]

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def bind(path,table):
    receipt=path.with_suffix('.receipt.json')
    value=dict(schema='a_share_qfq_panel_v1',generation_id='fixture',input_sha256='input',snapshot_file_sha256='snapshot',asof_date=20261111,
        price_basis='MIXED_BY_MARKET',volume_basis='MIXED_BY_MARKET',convention='fixture',field_basis={},
        market_basis={'A':dict(price_basis='QFQ_ASOF',volume_basis='QFQ_EVENT_VOLUME',asof_date=20261111),'HK':dict(price_basis='UNKNOWN_NATIVE',volume_basis='UNKNOWN_NATIVE',asof_date=None)},
        generation_manifest_path=str(receipt),candidates=dict(selector=str(path)))
    receipt.write_text(json.dumps(value));return table.replace_schema_metadata({logical.META:json.dumps(value).encode()})


def test_three_representative_readers_same_values_and_exact_group_pruning(tmp_path,monkeypatch):
    before=load(ROOT/'ops/vendor/selector_reader_transport_before.py','before_selector_transport')
    after=load(ROOT/'ops/vendor/DATA_LAYER_INTERFACE.py','after_selector_transport')
    codes=['000001.SZ','600000.SH','00005.HK']
    schema=pa.schema([('ts_code',pa.string()),('trade_date',pa.int64()),('close',pa.float64()),('name',pa.string()),('future_unsafe',pa.float64())])
    table=pa.Table.from_pylist([dict(ts_code=c,trade_date=d,close=None if c.endswith('.HK')else float(d),name=None,future_unsafe=None)for c in codes for d in [20261110,20261111]],schema=schema)
    oracle=tmp_path/'oracle.parquet';logical.physical.write_table(bind(oracle,table),oracle,row_group_size=2)
    base=tmp_path/'base.parquet';logical.physical.write_table(table,base,row_group_size=2)
    anchor=tmp_path/'anchor.parquet';anchored=bind(anchor,table)
    anchor.write_bytes(logical.anchor_bytes(anchored.schema,[logical.descriptor(base,key_rows={c:[i]for i,c in enumerate(codes)})],rows=6))
    calls=[];original=logical.physical.ParquetFile
    class Spy:
        def __init__(self,*a,**k):self.inner=original(*a,**k)
        def __getattr__(self,n):return getattr(self.inner,n)
        def read_row_groups(self,groups,*a,**k):calls.append(groups);return self.inner.read_row_groups(groups,*a,**k)
        def read(self,*a,**k):raise AssertionError('POINT_READ_MUST_PRUNE_GROUPS')
    monkeypatch.setattr(logical.physical,'ParquetFile',Spy)
    for i,code in enumerate(codes):
        expected=before.load_selector_ready(panel_path=oracle,columns=['close','name'],ts_codes=[code],start_date='20261111',end_date='20261111')
        actual=after.load_selector_ready(panel_path=anchor,columns=['close','name'],ts_codes=[code],start_date='20261111',end_date='20261111')
        assert actual.attrs['panel_metadata']['historical_pit_certified'] is False
        left=actual.copy();right=expected.copy();left.attrs={};right.attrs={}
        pd.testing.assert_frame_equal(left,right,check_exact=True)
        assert calls[-1]==[i]
    assert len(calls)==3
    with pytest.raises(ValueError,match='RAW_PROFILE_NOT_AVAILABLE'):after.load_selector_ready(panel_path=anchor,profile='RAW')
    # Existing future-column reporting is unchanged; no implicit certification.
    assert after.get_panel_meta(panel_path=anchor,include_dates=False)['future_like_columns']==['future_unsafe']


def proof(tmp_path):
    current=ROOT/'ops/vendor/DATA_LAYER_INTERFACE.py';old=ROOT/'ops/vendor/selector_reader_transport_before.py'
    before=hashlib.sha256(old.read_bytes()).hexdigest();after=hashlib.sha256(current.read_bytes()).hexdigest()
    snapshot=tmp_path/'before.py';snapshot.write_bytes(old.read_bytes())
    historical=dict(path=str(current),sha256=before);actual=dict(path=str(current),sha256=after);config=dict(path='bound.config',sha256='config')
    oracle=tmp_path/'oracle.json';oracle.write_text(json.dumps(dict(status='PASS',before_sha256=before,after_sha256=after)))
    p=tmp_path/'proof.json';p.write_text(json.dumps(dict(schema='v4.reader.transport_equivalence.v1',scope='EXACT_ARROW_BLOCK_TRANSPORT_ONLY',before_sha256=before,after_sha256=after,
        historical_reader=historical,config=config,before_source='before.py',oracle=dict(file='oracle.json',sha256=hashlib.sha256(oracle.read_bytes()).hexdigest()))))
    return p,actual,historical,config


def test_exact_cache_semantics_ref_preserves_actual_provenance_and_rejects_future(tmp_path):
    p,actual,historical,config=proof(tmp_path)
    identity,provenance=compat.semantic_reader_identity(actual,config,proof_path=p)
    assert identity==historical and provenance['actual_reader']==actual and actual!=historical
    with pytest.raises(ValueError,match='IDENTITY_CONFLICT'):compat.semantic_reader_identity({**actual,'sha256':'future'},config,proof_path=p)
    with pytest.raises(ValueError,match='IDENTITY_CONFLICT'):compat.semantic_reader_identity(actual,{**config,'sha256':'revision'},proof_path=p)
    source=Path(provenance['before_source_snapshot']['path']);source.write_bytes(source.read_bytes()+b'x')
    with pytest.raises(ValueError,match='SOURCE_DRIFT'):compat.semantic_reader_identity(actual,config,proof_path=p)


def test_existing_mathcache_hits_and_real_price_rule_revision_invalidates(tmp_path):
    import sys,types
    active=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-single-generation-20261111-r1/app/domains')
    # Read exact existing cache/statistics source; no production db is opened.
    stats=load(active/'research_daily_statistics.py','transport_cache_statistics')
    import domains
    prior=getattr(domains,'research_daily_statistics',None);domains.research_daily_statistics=stats
    try:module=load(active/'research_event_case_cache.py','transport_cache_original')
    finally:
        if prior is not None:domains.research_daily_statistics=prior
    p,actual,historical,config=proof(tmp_path);semantic,provenance=compat.semantic_reader_identity(actual,config,proof_path=p)
    identity=dict(symbol='000001.SZ',market='SZ',source_authority=dict(reader=historical),basis='QFQ_ASOF',rule_sha256='rule',formula_sha256='formula')
    calendar=pd.bdate_range('2026-11-02',periods=8).strftime('%Y-%m-%d').tolist()
    prices=[dict(date=d,close=10.+i)for i,d in enumerate(calendar)]
    cache=module.EventCaseCache(tmp_path/'events.sqlite')
    args=dict(identity=identity,event_dates=[calendar[0]],close_rows=prices,calendar=calendar,asof=calendar[-1])
    try:
        first=cache.build(**args);assert first['cache']['return_evaluations']>0
        after=cache.build(**{**args,'identity':{**identity,'source_authority':dict(reader=semantic)}})
        assert after['cache']['return_evaluations']==0 and after['cache']['return_hits']>0
        revised=copy.deepcopy(prices);revised[2]['close']+=1
        assert cache.build(**{**args,'close_rows':revised})['cache']['return_evaluations']>0
        assert cache.build(**{**args,'identity':{**identity,'rule_sha256':'actual_revision'}})['cache']['return_evaluations']>0
    finally:cache.close()
