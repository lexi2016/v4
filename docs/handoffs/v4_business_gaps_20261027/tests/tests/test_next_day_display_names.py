"""R3 only: date roles, immutable coverage extension and original-owner mutex."""
from copy import deepcopy
from datetime import datetime
import hashlib
import importlib
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pytest

W=Path(__file__).parents[1]
API=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/ui-pdf-publication-20261027-r2-api/app')
sys.path.insert(0,str(API))

def load(name,rel):
    importlib.import_module(name.rpartition('.')[0])
    spec=importlib.util.spec_from_file_location(name,W/rel);module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module

owner=load('upstreams.v3_shared_data.shared_data.a_share_security_master','upstreams/v3_shared_data/shared_data/a_share_security_master.py')
projection=load('domains._preselection_parts.source_validation','domains/_preselection_parts/source_validation.py')
FLAGS=dict(production_allowed=False,buy_gate_updated=False,orders_sent=False)
TZ=ZoneInfo('Asia/Shanghai')
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()


def evidence(tmp_path,date='20261027'):
    root=tmp_path/date;root.mkdir();page=root/'hq-SZ-00000.json'
    wire=dict(observation_date=date,captured_at=f'{date[:4]}-{date[4:6]}-{date[6:]}T10:00:00+08:00',market=0,exchange='SZ',
              method='get_security_list',provider='PYTDX_HQ',host='original',offset=0,count=2,rows=[{'code':'000995','name':'皇台酒业'},{'code':'000001','name':'平安银行'}])
    page.write_text(json.dumps(wire));(root/'hq-SZ-count.json').write_text(json.dumps({'observation_date':date,'count':2}))
    rows=[dict(ts_code=r['code']+'.SZ',code=r['code'],exchange='SZ',name=r['name'],provider='PYTDX_HQ',method='get_security_list',host='original',
               observed_at=wire['captured_at'],available_at=wire['captured_at'],observation_date=date,evidence_path=str(page),evidence_sha256=sha(page)) for r in wire['rows']]
    obs=dict(schema_version=owner.DISPLAY_SCHEMA,source_kind='DISPLAY_NAME_ONLY',observation_date=date,captured_at=wire['captured_at'],
             requested_codes=[rows[0]['ts_code']],rows=rows[:1],pages=[{'path':str(page),'sha256':sha(page)}],missing_codes=[],conflicted_codes=[],research_only=True,**FLAGS)
    return root,obs,rows


def registry(tmp_path):
    cache,old,rows=evidence(tmp_path);store=tmp_path/'store';receipt=owner.publish_current_display_names(store,old)
    root=store/'assets/a_share_display_names';index=root/'latest.json';before=index.read_bytes();new=deepcopy(old);new.update(requested_codes=[r['ts_code'] for r in rows],rows=rows)
    return cache,store,old,new,receipt,index,before


def extend(store,new,receipt,index):
    return owner.publish_current_display_names(store,new,extend=True,expected_prior_run_id=receipt['run_id'],expected_index_sha256=sha(index))


def test_extension_preserves_old_rows_old_run_bytes_and_other_date_entry(tmp_path):
    cache,store,old,new,receipt,index,before=registry(tmp_path)
    _,other,_=evidence(tmp_path,'20261026');owner.publish_current_display_names(store,other)
    other_entry=json.loads(index.read_bytes())['entries']['20261026'];prior=root=store/'assets/a_share_display_names/runs/20261027'/receipt['run_id']
    frozen={p.name:p.read_bytes() for p in prior.iterdir()};published=extend(store,new,receipt,index)
    assert published['row_count']==2 and published['coverage_extension']['previous_run_id']==receipt['run_id']
    assert json.loads(index.read_bytes())['entries']['20261026']==other_entry
    assert all((prior/name).read_bytes()==raw for name,raw in frozen.items())
    mapping,_=owner.load_current_display_names(store,'20261027');assert mapping['000995']==old['rows'][0]
    assert all(published[k] is False for k in ('production_allowed','buy_gate_updated','orders_sent','pit_certified','selector_certified'))


@pytest.mark.parametrize('defect',['default','drop','old_metadata','date','prior_run','prior_sha','wrong_market'])
def test_bad_or_implicit_extension_cannot_mutate_index(tmp_path,defect):
    cache,store,old,new,receipt,index,before=registry(tmp_path)
    kwargs=dict(extend=True,expected_prior_run_id=receipt['run_id'],expected_index_sha256=sha(index))
    if defect=='default':kwargs={}
    elif defect=='drop':new['rows']=new['rows'][1:];new['requested_codes']=new['requested_codes'][1:]
    elif defect=='old_metadata':new['rows'][0]['host']='changed'
    elif defect=='date':new['observation_date']='20261028'
    elif defect=='prior_run':kwargs['expected_prior_run_id']='wrong'
    elif defect=='prior_sha':kwargs['expected_index_sha256']='0'*64
    else:new['rows'][0]['exchange']='SH';new['rows'][0]['ts_code']='000995.SH';new['requested_codes'][0]='000995.SH'
    with pytest.raises(owner.StoreError):owner.publish_current_display_names(store,new,**kwargs)
    assert index.read_bytes()==before


def test_cache_only_performs_no_connect_or_page_request_and_keeps_success_checkpoint(tmp_path,monkeypatch):
    cache,store,old,new,receipt,index,before=registry(tmp_path)
    import pytdx.hq
    monkeypatch.setattr(pytdx.hq,'TdxHq_API',lambda *a,**k:pytest.fail('cache mode connected'))
    checkpoint=cache/'observation.json';checkpoint.write_bytes(b'original-success');output=tmp_path/'new-observation.json'
    result=owner.acquire_current_display_names(cache,observation_date='20261027',requested_codes=new['requested_codes'],official_rows=old['rows'],
        cache_only=True,cached_page_pins={p['path']:p['sha256'] for p in old['pages']},output_path=output)
    assert result['rows'][0]==old['rows'][0] and len(result['rows'])==2 and not result['missing_codes']
    assert checkpoint.read_bytes()==b'original-success' and json.loads(output.read_bytes())['cache_only'] is True
    with pytest.raises(FileExistsError):owner.acquire_current_display_names(cache,observation_date='20261027',requested_codes=new['requested_codes'],official_rows=old['rows'],cache_only=True,cached_page_pins={p['path']:p['sha256'] for p in old['pages']},output_path=checkpoint)
    assert checkpoint.read_bytes()==b'original-success'


def _competitor(store,new,receipt,index,queue):
    try:extend(store,new,receipt,index)
    except Exception as error:queue.put((type(error).__name__,str(error)))
    else:queue.put(('UNEXPECTED_SUCCESS',''))


def test_competing_process_refuses_original_store_mutex_without_index_write(tmp_path):
    from infrastructure.interprocess_lock import owned_interprocess_lock
    cache,store,old,new,receipt,index,before=registry(tmp_path)
    ctx=multiprocessing.get_context('fork');queue=ctx.Queue()
    with owned_interprocess_lock(index.parent/'.store.lock',timeout_seconds=0,timeout_message='fixture busy'):
        process=ctx.Process(target=_competitor,args=(store,new,receipt,index,queue));process.start();process.join(10)
        assert not process.is_alive();kind,message=queue.get(timeout=2)
        assert kind!='UNEXPECTED_SUCCESS' and 'busy' in message
        assert index.read_bytes()==before
    queue.close();queue.join_thread()


def response(date='20261028',signal='20261027'):
    row=dict(market='A',symbol='A.000995',stock_name='A.000995',display_name='A.000995（选）',trade_date=date,target_date=date,pool_id='a_d1_premarket_pool')
    if signal is not None:row['signal_date']=signal
    return dict(rows=[row],a_all_pool_rows=[row],unified_rows=[row],pools=[dict(pool_id='a_d1_premarket_pool',rows=[row])])


def prepare_projection(monkeypatch,store,*,signal='20261027',pool_signal='20261027',conflict=False):
    import stage_center.consumer as stage
    import infrastructure.preselection_pool_store as pools
    trio=dict(artifact='a'*64,manifest='b'*64,receipt='c'*64)
    authority=dict(mapping={},conflicted_codes=['A.000995'] if conflict else [],pool_audit={'a_d1_premarket_pool':dict(verification_status='VERIFIED',trio_raw_sha256=trio)})
    monkeypatch.setattr(stage,'StageSelectionConsumer',lambda *a,**k:type('Consumer',(),{'_load_a_name_authority':lambda self,date:authority})())
    snapshot=dict(artifact={'target_date':'20261028','signal_date':pool_signal,'rows':[response(signal=signal)['rows'][0]]},artifact_raw_sha256='a'*64,manifest_raw_sha256='b'*64,receipt_raw_sha256='c'*64)
    monkeypatch.setattr(pools,'PreselectionPoolStore',lambda *a:type('Store',(),{'read_pool_snapshot':lambda self,*a:snapshot})())
    monkeypatch.setenv('V4_MANAGER_SECURITY_MASTER_ROOT',str(store))


@pytest.mark.parametrize('clock',['2026-10-27T19:50:00+08:00','2026-10-28T00:01:00+08:00','2026-10-28T09:30:00+08:00'])
def test_evening_midnight_and_opening_keep_real_observation_and_target_separate(tmp_path,monkeypatch,clock):
    _,store,*_=registry(tmp_path);prepare_projection(monkeypatch,store);value=response();before=deepcopy(value)
    result=projection.project_a_display_names(value,'20261028',tmp_path,as_of=datetime.fromisoformat(clock))
    assert value==before
    for row in (result['rows'][0],result['a_all_pool_rows'][0],result['unified_rows'][0],result['pools'][0]['rows'][0]):
        assert row['stock_name']=='皇台酒业' and row['display_name']=='皇台酒业（选）'
        assert row['display_identity']['observation_date']=='20261027' and row['display_identity']['target_date']=='20261028'
        assert row['display_identity']['selector_certified'] is False and row['display_identity']['pit_certified'] is False


@pytest.mark.parametrize('defect',['wrong_signal','missing_signal','history','stale','future_target','conflict','exact_corrupt'])
def test_no_stale_wrong_signal_historical_future_or_corruption_fallback(tmp_path,monkeypatch,defect):
    _,store,*_=registry(tmp_path);signal='20261026' if defect=='wrong_signal' else None if defect=='missing_signal' else '20261027'
    prepare_projection(monkeypatch,store,signal=signal,pool_signal=signal,conflict=defect=='conflict')
    date='20261026' if defect=='history' else '20261029' if defect in ('stale','future_target') else '20261028'
    clock='2026-10-29T09:30:00+08:00' if defect=='stale' else '2026-10-27T19:50:00+08:00' if defect in ('history','future_target') else '2026-10-28T09:30:00+08:00'
    if defect=='exact_corrupt':
        index=store/'assets/a_share_display_names/latest.json';value=json.loads(index.read_bytes());value['entries']['20261028']={'run_id':'broken','run_relative':'runs/20261028/broken'};index.write_text(json.dumps(value))
    result=projection.project_a_display_names(response(date,signal),date,tmp_path,as_of=datetime.fromisoformat(clock))
    assert result['rows'][0]['stock_name']=='A.000995'
    if defect=='exact_corrupt':assert result['display_name_authority']['current_error'] and result['display_name_authority']['date_role']=='EXACT_TARGET_DATE_OBSERVATION'
