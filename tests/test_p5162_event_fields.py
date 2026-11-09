import copy
import importlib
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from domains import p5162_event_position_fields as domain
from ops import materialize_p5162_event_fields as adapter


SYMBOL = '000913.SZ'
GEN = 'generation-a'
BASIS = {'price_basis':'QFQ_ASOF','volume_basis':'QFQ_EVENT_VOLUME','asof_date':20261027}
CAL = [20261023,20261026,20261027,20261028]


def source_row(symbol=SYMBOL, target='20261027', generation=GEN):
    return dict(symbol=symbol, data_date=target, groups='nav_smallk', pending_groups='', reasons='',
        qualification=dict(status='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH',symbol=symbol,
                           target_date=target,source_generation=generation),
        evaluation=dict(symbol=symbol,asof=int(target),all_new_key_dates=[20261023,20261026],
            latest_prior_new_key_date=20261026,primary_path_redgreen='TRUE',
            filter_anchor_paths=[
                dict(anchor_date=20261023, role='EARLIER_REFERENCE_RETAINED_NOT_SELECTED',
                     key={'date':20261023,'candidate':'TRUE'},ohlcv={'date':20261023,'h':'10','l':'9','v':'100'},
                     preK={'status':'FALSE','selected':None},same_anchor_support={'D_close':'10.4'}),
                dict(anchor_date=20261026, role='LATEST_PRIOR_NEW_KEY',
                     key={'date':20261026,'candidate':'TRUE','FUNDK':'TRUE'},ohlcv={'date':20261026,'h':'11','l':'10','v':'200'},
                     preK={'status':'TRUE','selected':{'start':20261001,'end':20261023,'n':20,'redgreen':'TRUE'}},
                     same_anchor_support={'D_close':'10.4'})],
            groups={g:{'status':'TRUE' if g=='nav_smallk' else 'FALSE'} for g in ('original','nav_smallk','nav_pullback','nav_breakout')}))


def bar(symbol=SYMBOL, target='20261027', close='10.4', volume='100'):
    return dict(ts_code=symbol,trade_date=target,exchange=symbol[-2:],close=close,volume=volume)


def project(row=None, day=None, basis=None, calendar=None):
    return domain.project(SYMBOL,'20261027',GEN,row or source_row(),{'path':'fixture','sha256':'a'*64},
        bar() if day is None else day,CAL if calendar is None else calendar,BASIS if basis is None else basis)


def test_reference_geometry_roles_and_unbound_model():
    out=project(); ref=out['panel_reference']; f=ref['fields']
    assert ref['event_id']=='PANEL_REFERENCE_K:000913.SZ:20261026'
    assert f['reference_age_sessions']==1
    assert f['reference_high_to_close_pct']==pytest.approx((11-10.4)/11*100)
    assert f['reference_volume_ratio']==.5
    assert out['anchor_paths'][0]['role']=='EARLIER_REFERENCE_RETAINED_NOT_SELECTED'
    assert out['anchor_paths'][1]['preK']['identity']=='ORIGINAL_PANEL_PREK_SEGMENT_NOT_R3_JCB'
    assert out['groups']=='nav_smallk' and out['primary_path_redgreen']=='TRUE'
    assert all(v is None for v in out['r3_model']['fields'].values())
    out['source_generation']=GEN
    with pytest.raises(ValueError,match='R3_MODEL_INPUT_NOT_ADMITTED:SEMANTIC_MAPPING_NOT_CERTIFIED'):
        domain.read_model_fields(out,symbol=SYMBOL,data_date='20261027',generation=GEN)
    out['r3_model']['namespace']='PANEL_REFERENCE_K'
    with pytest.raises(ValueError,match='MODEL_NAMESPACE_CONFLICT'):
        domain.read_model_fields(out,symbol=SYMBOL,data_date='20261027',generation=GEN)


def test_reference_negative_and_missing_components():
    source=source_row()
    for p in source['evaluation']['filter_anchor_paths']: p['same_anchor_support']['D_close']='12'
    result=project(source,bar(close='12',volume=None))['panel_reference']
    assert result['fields']['reference_high_to_close_pct']==pytest.approx(-100/11)
    assert result['fields']['reference_age_sessions']==1
    assert result['fields']['reference_volume_ratio'] is None
    assert 'REFERENCE_OR_TARGET_VOLUME_MISSING' in result['reasons']


@pytest.mark.parametrize('kind', ['future','wrong_stock','mixed_basis','wrong_bar','wrong_role','wrong_calendar'])
def test_reject_conflicting_inputs(kind):
    row=source_row(); day=bar(); basis=copy.deepcopy(BASIS); calendar=CAL
    if kind=='future': row['evaluation']['latest_prior_new_key_date']=20261028
    if kind=='wrong_stock': row['evaluation']['symbol']='000001.SZ'
    if kind=='mixed_basis': basis['price_basis']='RAW'
    if kind=='wrong_bar': day['ts_code']='000001.SZ'
    if kind=='wrong_role': row['evaluation']['filter_anchor_paths'][-1]['role']='EARLIER_REFERENCE_RETAINED_NOT_SELECTED'
    if kind=='wrong_calendar': calendar=[20261027,20261026]
    with pytest.raises(ValueError): project(row,day,basis,calendar)


def test_owner_calls_sidecar_and_cached_numeric_repairs_missing(tmp_path,monkeypatch):
    # The repository lacks this historical module; provide only its decorator
    # boundary while invoking the real materialize_daily_product function body.
    pair=types.ModuleType('ops.research_storage_pair');pair.paired_request=lambda fn:fn
    monkeypatch.setitem(sys.modules,'ops.research_storage_pair',pair)
    sys.modules.pop('ops.research_panel_daily_product',None)
    owner=importlib.import_module('ops.research_panel_daily_product')
    original_save=owner.save; governed_paths=[]
    def governed_save(path,value,**kwargs):
        if '/p5162_event_fields/' in str(path): governed_paths.append(str(path))
        return original_save(path,value,**kwargs)
    monkeypatch.setattr(owner,'save',governed_save)
    prefill=types.ModuleType('ops.research_daily_product_parallel');prefill.prefill_missing=lambda *a,**k:{'chart_gaps':{}}
    monkeypatch.setitem(sys.modules,'ops.research_daily_product_parallel',prefill)
    score=types.ModuleType('ops.materialize_workbench_score_action');score.materialize=lambda *a,**k:{'status':'FIXTURE'}
    monkeypatch.setitem(sys.modules,'ops.materialize_workbench_score_action',score)
    root=tmp_path/'daily'; source=tmp_path/'source';source.mkdir();calls=[]
    syms=[SYMBOL,'000914.SZ']
    def setup(target='20261027',generation=GEN):
        b={**BASIS,'asof_date':int(target)}
        identity=dict(generation=generation,input_sha256='i'*64,asof=int(target),basis=b,selector_artifact_sha256='s'*64,historical_PIT=False)
        path=source/(target+'.parquet')
        pq.write_table(pa.Table.from_pylist([bar(s,target) for s in syms]),path)
        return SimpleNamespace(root=root,target=int(target),generation=generation,identity=identity,
            scope=syms,config_ref={'sha256':'config'},snapshot_ref={'sha256':'snapshot'},panel=path,
            calendars={'SZ':CAL},unchanged=lambda:None)
    current=[setup()]
    monkeypatch.setattr(owner,'SourceContext',lambda *a:current[0])
    def compute(context,symbol,**kwargs):
        calls.append((context.target,symbol))
        row=source_row(symbol,str(context.target),context.generation)
        if symbol=='000914.SZ': row['evaluation']['symbol']='000001.SZ'
        return row,{},root/'history'/symbol/'checkpoint.json'
    monkeypatch.setattr(owner,'compute_stock',compute)
    first=owner.materialize_daily_product(data_root=tmp_path,target=20261027,original_charts=False)
    assert len(calls)==2
    descriptor=first['p5162_event_fields']; idx=adapter.checked(descriptor['index'])
    assert len(governed_paths)==3  # two records and their index used the owner seam
    assert descriptor['counts']['total']==2 and descriptor['counts']['source_isolated']==1
    assert adapter.checked(idx['items'][SYMBOL])['panel_reference']['fields']['reference_age_sessions']==1
    assert json.loads((root/'index.json').read_text())['p5162_event_fields']['20261027']==descriptor
    assert json.loads((root/'events/latest.json').read_text())['p5162_event_fields']==descriptor
    with pytest.raises(ValueError,match='R3_MODEL_INPUT_NOT_ADMITTED'):
        adapter.read_model_fields(descriptor['index'],SYMBOL,data_date='20261027',generation=GEN)
    second=owner.materialize_daily_product(data_root=tmp_path,target=20261027,original_charts=False)
    assert len(calls)==2 and current[0]._p5162_event_fields_last_run=={'computed':0,'reused':2}
    Path(idx['items'][SYMBOL]['path']).unlink()
    def forbidden(*args,**kwargs): raise AssertionError('RECOVERY_MUST_NOT_COMPUTE_NUMERIC_OR_SCORE')
    old_prefill=prefill.prefill_missing;old_score=score.materialize;old_compute=owner.compute_stock
    prefill.prefill_missing=forbidden;score.materialize=forbidden;owner.compute_stock=forbidden
    third=owner.materialize_daily_product(data_root=tmp_path,target=20261027,require_cached_numeric=True)
    prefill.prefill_missing=old_prefill;score.materialize=old_score;owner.compute_stock=old_compute
    assert len(calls)==2 and current[0]._p5162_event_fields_last_run=={'computed':1,'reused':1}
    assert third['p5162_event_fields']==second['p5162_event_fields'] and third['numeric_recomputed'] is False
    product=adapter.checked(adapter.checked(third['manifest'])['artifact'])
    other=setup('20261027','generation-b')
    with pytest.raises(ValueError,match='IDENTITY_CONFLICT'):
        adapter.materialize(other,product,third['manifest'],output_root=tmp_path/'wrong')
    # A later date makes new observations but keeps the original event id.
    current[0]=setup('20261028','generation-b')
    fourth=owner.materialize_daily_product(data_root=tmp_path,target=20261028,original_charts=False)
    idx2=adapter.checked(fourth['p5162_event_fields']['index'])
    assert adapter.checked(idx2['items'][SYMBOL])['panel_reference']['event_id']=='PANEL_REFERENCE_K:000913.SZ:20261026'
    assert len(calls)==4
    # Sample owner calls do not change existing publication state.
    before=(root/'index.json').read_bytes(),(root/'events/latest.json').read_bytes()
    owner.materialize_daily_product(data_root=tmp_path,target=20261028,symbols=[SYMBOL],original_charts=False)
    assert before==((root/'index.json').read_bytes(),(root/'events/latest.json').read_bytes())


def test_late_row_dependency_recomputes_only_affected_symbol_and_checks_cache(tmp_path):
    syms=[SYMBOL,'000914.SZ']; target='20261027'; identity=dict(generation=GEN,input_sha256='a'*64,
        selector_artifact_sha256='b'*64,asof=int(target),basis=BASIS,historical_PIT=False)
    panel=tmp_path/'panel.parquet';pq.write_table(pa.Table.from_pylist([bar(s,target) for s in syms]),panel)
    context=SimpleNamespace(root=tmp_path/'owner',target=int(target),generation=GEN,identity=identity,
        panel=panel,calendars={'SZ':CAL},unchanged=lambda:None)
    a=source_row(); a['evaluation']['filter_anchor_paths'][-1]['ohlcv']['v']=None
    b=source_row(syms[1]); refs={SYMBOL:adapter.save(tmp_path/'sources'/'a-old.json',a),
        syms[1]:adapter.save(tmp_path/'sources'/'b.json',b)}
    def parent(refs, label):
        product=dict(schema_version='v4.a_share.daily_product.v1',data_date=target,source_generation=GEN,
            source_identity=identity,processed_universe=syms,row_refs=copy.deepcopy(refs),source_config={'sha256':'config'})
        artifact=adapter.save(tmp_path/'parents'/(label+'-product.json'),product)
        manifest=adapter.save(tmp_path/'parents'/(label+'-manifest.json'),dict(data_date=target,source_generation=GEN,
            input_sha256=identity['input_sha256'],artifact=artifact))
        return product,manifest
    p1,m1=parent(refs,'before'); first=adapter.materialize(context,p1,m1,output_root=tmp_path/'output')
    old=adapter.checked(adapter.checked(first['index'])['items'][SYMBOL])
    assert old['panel_reference']['fields']['reference_volume_ratio'] is None
    a['evaluation']['filter_anchor_paths'][-1]['ohlcv']['v']='200'
    refs[SYMBOL]=adapter.save(tmp_path/'sources'/'a-late.json',a)
    p2,m2=parent(refs,'after'); second=adapter.materialize(context,p2,m2,output_root=tmp_path/'output')
    index=adapter.checked(second['index']); assert context._p5162_event_fields_last_run=={'computed':1,'reused':1}
    assert adapter.checked(index['items'][SYMBOL])['panel_reference']['fields']['reference_volume_ratio']==.5
    assert adapter.checked(adapter.checked(first['index'])['items'][SYMBOL])==old
    cache=Path(index['items'][SYMBOL]['path']);cache.write_bytes(cache.read_bytes()+b' ')
    with pytest.raises(ValueError,match='EVENT_FIELDS_CACHE_CONTENT_DRIFT'):
        adapter.materialize(context,p2,m2,output_root=tmp_path/'output')
