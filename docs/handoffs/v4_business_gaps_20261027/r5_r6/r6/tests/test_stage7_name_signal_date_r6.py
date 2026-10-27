from copy import deepcopy
from datetime import datetime
import importlib
import importlib.util
from pathlib import Path
import sys

import pytest

WORK=Path(__file__).parents[1]
API=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/business-gaps-20261027-r5-api/app')
sys.path.insert(0,str(API))
importlib.import_module('domains._preselection_parts')
spec=importlib.util.spec_from_file_location('domains._preselection_parts.source_validation',WORK/'domains/_preselection_parts/source_validation.py')
projection=importlib.util.module_from_spec(spec);spec.loader.exec_module(projection)
import stage_center.consumer as stage
import infrastructure.preselection_pool_store as pools
import upstreams.v3_shared_data.shared_data.a_share_security_master as master
import infrastructure.review_core_stage7_pool_source as stage_source

POOL='a_d1_stage7_fenshi_review_pool'

def row(**changes):
    value={'market':'A','symbol':'A.000995','code':'SZ.000995','name':'SZ.000995','stock_name':'SZ.000995','display_name':'SZ.000995（观察）','trade_date':'20261027','signal_date':'20261027','target_date':'20261028','pool_id':POOL,'rank':7,'stage_score':3.5,'pit_certified':False,'stage_selection_eligible':False}
    value.update(changes);return value

def setup(monkeypatch, *, defect=None):
    trio={'artifact':'a'*64,'manifest':'b'*64,'receipt':'c'*64}; snapshot={'artifact_raw_sha256':'a'*64,'manifest_raw_sha256':'b'*64,'receipt_raw_sha256':'c'*64,'artifact':{'signal_date':'20261027','target_date':'20261028','rows':[row()]}}
    if defect=='sha':snapshot['receipt_raw_sha256']='f'*64
    if defect=='no_sha':trio.pop('receipt');snapshot['receipt_raw_sha256']=None
    if defect=='pool_signal':snapshot['artifact']['signal_date']='20261026'
    if defect=='pool_target':snapshot['artifact']['target_date']='20261029'
    if defect=='member':snapshot['artifact']['rows']=[row(symbol='A.000001',code='SZ.000001')]
    audit={POOL:{'verification_status':'VERIFIED','trio_raw_sha256':trio}}
    authority={'mapping':{},'conflicted_codes':['A.000995'] if defect=='conflict' else [],'pool_audit':audit}
    monkeypatch.setattr(stage,'StageSelectionConsumer',lambda *a,**k:type('Consumer',(),{'_load_a_name_authority':lambda self,date:authority})())
    monkeypatch.setattr(pools,'PreselectionPoolStore',lambda *a:type('Store',(),{'read_pool_snapshot':lambda self,*a:snapshot})())
    source={'status':'READY','signal_date':'20261027','target_date':'20261028','source_merge_role':'SOURCE_ONLY','stage_selection_eligible':False,'consumer_artifact_sha256':'a'*64,'consumer_manifest_sha256':'b'*64,'consumer_receipt_sha256':'c'*64,'rows':[row()]}
    if defect=='sha':source['status']='CANNOT_CONFIRM'
    if defect=='no_sha':source['consumer_receipt_sha256']=None
    if defect=='pool_signal':source['signal_date']='20261026'
    if defect=='pool_target':source['target_date']='20261029'
    if defect=='member':source['rows']=[row(symbol='A.000001',code='SZ.000001')]
    monkeypatch.setattr(stage_source,'load_review_core_stage7_pool',lambda *args:source)
    observation={'ts_code':'000995.SZ','name':'皇台酒业','observed_at':'2026-10-27T10:00:00+08:00','available_at':'2026-10-27T10:00:00+08:00','evidence_sha256':'e'*64}
    if defect=='future':observation['available_at']='2026-10-27T22:00:00+08:00'
    def load(root,date):
        if date=='20261028':raise master.DisplayNameObservationMissing('missing current target observation')
        return {'000995':observation},{'run_id':'master','observation_date':'20261027'}
    monkeypatch.setattr(master,'load_current_display_names',load);monkeypatch.setenv('V4_MANAGER_SECURITY_MASTER_ROOT','/fixture')

def apply(tmp_path,clock,value):
    return projection.project_a_display_names({'rows':[value], 'pools':[{'pool_id':POOL,'rows':[value]}]},'20261028',tmp_path,as_of=datetime.fromisoformat(clock))

@pytest.mark.parametrize('clock',['2026-10-27T20:00:00+08:00','2026-10-28T00:01:00+08:00'])
def test_verified_signal_source_date_is_named_without_changing_row_dates(tmp_path,monkeypatch,clock):
    setup(monkeypatch);original=row();before=deepcopy(original);result=apply(tmp_path,clock,original)
    assert original==before
    for item in (result['rows'][0],result['pools'][0]['rows'][0]):
        assert (item['name'],item['stock_name'],item['display_name'])==('皇台酒业','皇台酒业','皇台酒业（观察）')
        assert (item['trade_date'],item['signal_date'],item['target_date'])==('20261027','20261027','20261028')
        assert item['rank']==7 and item['stage_score']==3.5 and item['pit_certified'] is False and item['stage_selection_eligible'] is False

@pytest.mark.parametrize('defect',['sha','no_sha','pool_signal','pool_target','member','conflict','future','wrong_signal','wrong_target','conflicting_code'])
def test_reject_unverified_or_inconsistent_source_rows(tmp_path,monkeypatch,defect):
    setup(monkeypatch,defect=defect);item=row()
    if defect=='wrong_signal':item['signal_date']='20261026'
    if defect=='wrong_target':item['target_date']='20261029'
    if defect=='conflicting_code':item['stock_code']='SH.600000'
    result=apply(tmp_path,'2026-10-27T20:00:00+08:00',item)
    assert result['rows'][0]['name']=='SZ.000995'

def test_original_target_date_rows_still_project(tmp_path,monkeypatch):
    setup(monkeypatch);item=row(trade_date='20261028')
    assert apply(tmp_path,'2026-10-27T20:00:00+08:00',item)['rows'][0]['name']=='皇台酒业'

def test_target_day_name_observation_keeps_verified_prior_signal_date(tmp_path,monkeypatch):
    setup(monkeypatch)
    observed={'ts_code':'000995.SZ','name':'皇台酒业','observed_at':'2026-10-28T00:00:00+08:00','available_at':'2026-10-28T00:00:00+08:00','evidence_sha256':'e'*64}
    monkeypatch.setattr(master,'load_current_display_names',lambda *args:({'000995':observed},{'run_id':'master-target','observation_date':'20261028'}))
    result=apply(tmp_path,'2026-10-28T00:01:00+08:00',row())
    assert result['rows'][0]['name']=='皇台酒业' and result['rows'][0]['trade_date']=='20261027'
    assert result['display_name_authority']['date_role']=='EXACT_TARGET_DATE_OBSERVATION'

def test_conflicting_row_and_container_pool_ids_rejected(tmp_path,monkeypatch):
    setup(monkeypatch);result=apply(tmp_path,'2026-10-27T20:00:00+08:00',row(pool_id='another_pool'))
    assert result['pools'][0]['rows'][0]['name']=='SZ.000995'

def test_non_stage_preselection_verified_signal_cannot_authorize_old_trade_date(tmp_path,monkeypatch):
    setup(monkeypatch)
    other='a_d1_premarket_pool';item=row(pool_id=other)
    trio={'artifact':'a'*64,'manifest':'b'*64,'receipt':'c'*64}
    authority={'mapping':{},'conflicted_codes':[],'pool_audit':{other:{'verification_status':'VERIFIED','trio_raw_sha256':trio}}}
    snapshot={'artifact_raw_sha256':'a'*64,'manifest_raw_sha256':'b'*64,'receipt_raw_sha256':'c'*64,'artifact':{'signal_date':'20261027','target_date':'20261028','rows':[item]}}
    monkeypatch.setattr(stage,'StageSelectionConsumer',lambda *a,**k:type('Consumer',(),{'_load_a_name_authority':lambda self,date:authority})())
    monkeypatch.setattr(pools,'PreselectionPoolStore',lambda *a:type('Store',(),{'read_pool_snapshot':lambda self,*a:snapshot})())
    value={'rows':[item],'pools':[{'pool_id':other,'rows':[item]}]}
    result=projection.project_a_display_names(value,'20261028',tmp_path,as_of=datetime.fromisoformat('2026-10-27T20:00:00+08:00'))
    assert result['rows'][0]['name']=='SZ.000995' and result['pools'][0]['rows'][0]['name']=='SZ.000995'

def test_verified_stage_stale_but_internally_consistent_signal_is_rejected(tmp_path,monkeypatch):
    setup(monkeypatch);item=row(trade_date='20261026',signal_date='20261026')
    source={'status':'READY','signal_date':'20261026','target_date':'20261028','source_merge_role':'SOURCE_ONLY','stage_selection_eligible':False,'consumer_artifact_sha256':'a'*64,'consumer_manifest_sha256':'b'*64,'consumer_receipt_sha256':'c'*64,'rows':[item]}
    monkeypatch.setattr(stage_source,'load_review_core_stage7_pool',lambda *args:source)
    assert apply(tmp_path,'2026-10-27T20:00:00+08:00',item)['rows'][0]['name']=='SZ.000995'
