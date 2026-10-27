"""Bounded replay of the actual partial Stage7 source into an isolated store."""
import base64
import csv
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

W=Path(__file__).parents[1]
API=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/business-gaps-20261027-r4-api/app')
sys.path.insert(0,str(API));sys.path.insert(0,str(W/'upstreams/v3_shared_data'))
from scripts.live_acquisition.orchestrator import recover_partial_stage_minutes
from stage_center.candidate_input import read_candidate_input
from shared_data.consumer import read_verified_latest
from shared_data.allowlist import AllowlistRegistry, SourceSpec
from shared_data.store import SafeRootStore, ConflictError

CASE=Path('/Users/lexi/Desktop/学习/agents调试/V4_BUSINESS_GAPS_20261027/operations/two_pool_upstream_r5')
RAW=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/raw')
CANDIDATE=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data')
KW=dict(trade_date='20261027',stage_id='STAGE_1445_1500',raw_root=RAW,
 raw_run_id='20261027-a_share_1min_stage_1445_1500-158cd558b9bb85b2',
 raw_artifact_sha256='25f3df3065ea36c3fa00e25d81c03579050f36b33e0501d5da5fbe38253d5413',
 raw_manifest_sha256='e4add4585620c99a7c98a951c1f0e785f447b23f01c32c15ddd0f3a4fe8f1a56',
 raw_receipt_sha256='1bd66a3eead849df864f9fc081cf73b03a7753aecedd42602e7e5fc471623c34',candidate_root=CANDIDATE,
 candidate_current_sha256='6351a0dd36a3d29598e6ae89fad13c861dd853bae47e5a9671fcf3bbdecfcff7',
 canary_result=CASE/'canary_603727/RESULT.json',canary_result_sha256='1dd9a892645ad4d1d42c20fdfc45a60e5e873ecc91e034b9b250444dc4b55262',
 canary_stdout=CASE/'canary_603727/00_stdout.bin')

def test_original_owner_recovers_one_late_row_with_provenance(tmp_path):
    result=recover_partial_stage_minutes(tmp_path,**KW)
    assert result['status']=='READY' and result['row_count']==482
    actual=read_verified_latest(tmp_path,'20261027','A_SHARE_1MIN_STAGE_1445_1500')
    manifest=actual.manifest;receipt=actual.receipt
    for doc in (manifest,receipt):
        assert doc['historical_backfill'] is True
        assert doc['pre_cutoff_capture_verified'] is False and doc['pit_certified'] is False
        assert doc['source_merge_role']=='SOURCE_ONLY' and doc['stage_selection_eligible'] is False
    prov=manifest['provenance'];prior=json.loads(base64.urlsafe_b64decode(prov['prior_diagnostics_base64url']))
    resolved=json.loads(base64.urlsafe_b64decode(prov['resolved_coverage_diagnostics_base64url']))
    assert len(prior)==1859 and len(resolved)==2 and prov['unresolved_prior_diagnostic_count']=='1857'
    original=RAW/'runs/20261027/A_SHARE_1MIN_STAGE_1445_1500'/KW['raw_run_id']/'artifact.csv'
    before_original=original.read_bytes()
    assert prov['prior_artifact_sha256']==hashlib.sha256(original.read_bytes()).hexdigest()
    with actual.artifact_path.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
    with original.open(encoding='utf-8-sig',newline='') as f: prior_rows=list(csv.DictReader(f))
    candidate=read_candidate_input(CANDIDATE,'20261027',expected_current_sha256=KW['candidate_current_sha256'])
    assert [r['code'].split('.',1)[-1] for r in rows]==[code.split('.',1)[-1] for code in candidate.codes]
    assert len(rows)==482 and rows[409]['code']=='SH.603727'
    lookup={r['code']:r for r in rows};assert all(lookup[row['code']]==row for row in prior_rows)
    assert original.read_bytes()==before_original
    before=(tmp_path/'latest.json').read_bytes()
    with pytest.raises(ConflictError,match='expected absent'):
        recover_partial_stage_minutes(tmp_path,**KW)
    assert (tmp_path/'latest.json').read_bytes()==before

@pytest.mark.parametrize('field,value',[
 ('raw_artifact_sha256','0'*64),('raw_manifest_sha256','0'*64),('raw_receipt_sha256','0'*64),
 ('candidate_current_sha256','0'*64),('canary_result_sha256','0'*64),('stage_id','STAGE_1300_1315')])
def test_drift_fails_before_store_write(tmp_path,field,value):
    args={**KW,field:value}
    with pytest.raises((ValueError,RuntimeError)):recover_partial_stage_minutes(tmp_path,**args)
    assert not (tmp_path/'latest.json').exists()

def test_mutated_canary_stdout_fails_before_store_write(tmp_path):
    stdout=tmp_path/'bad_stdout';stdout.write_bytes(b'bad')
    with pytest.raises(ValueError,match='RECOVERY_SOURCE_SHA_MISMATCH'):
        recover_partial_stage_minutes(tmp_path,**{**KW,'canary_stdout':stdout})
    assert not (tmp_path/'latest.json').exists()


@pytest.mark.parametrize('change', ['clock','safety','aggregate'])
def test_canary_evidence_mismatch_fails_closed(tmp_path,change):
    report=json.loads(KW['canary_result'].read_text())
    if change=='clock':report['started_at']='2026-10-27T06:00:00+00:00'
    elif change=='safety':report['orders_sent']=True
    else:report['result']['rows'][0]['last_price']+=1
    path=tmp_path/'changed.json';path.write_text(json.dumps(report,ensure_ascii=False))
    with pytest.raises(ValueError,match='RECOVERY_CANARY_'):
        recover_partial_stage_minutes(tmp_path,**{**KW,'canary_result':path,'canary_result_sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    assert not (tmp_path/'latest.json').exists()


def test_existing_ready_historical_supersession_preserves_prior_bytes(tmp_path):
    first=recover_partial_stage_minutes(tmp_path/'store',**KW)
    original=tmp_path/'store'/first['artifact_relative'];before=original.read_bytes()
    replacement=tmp_path/'replacement.csv';replacement.write_bytes(before+b'\n')
    role='A_SHARE_1MIN_STAGE_1445_1500'
    spec=SourceSpec(source_id='pytdx_hq',role=role,trade_date='20261027',market='A_SHARE',stages=('STAGE_1445_1500',),cutoff_at='15:00:00',source_path=replacement,required_columns=('trade_date','bar_time'),bar_time_column='bar_time')
    store=SafeRootStore(root=tmp_path/'store',allowlist=AllowlistRegistry(entries={('20261027',role):(spec,)}))
    second=store.replay_file(owner='v3_shared_data',trade_date='20261027',role=role,source_id='pytdx_hq',stage_id='STAGE_1445_1500',historical_backfill=True)
    assert second['status']=='READY' and original.read_bytes()==before
    receipt=json.loads((tmp_path/'store'/second['receipt_relative']).read_text())
    assert receipt['historical_backfill'] is True and receipt['pit_certified'] is False
    assert receipt['supersedes']['run_id']==first['run_id']


def test_original_pool_and_api_projection_keep_history_boundary(tmp_path,monkeypatch):
    shared=tmp_path/'shared';recover_partial_stage_minutes(shared,**KW)
    monkeypatch.setenv('V3_SHARED_DATA_PACKAGE_ROOT',str(W/'upstreams/v3_shared_data'))
    root=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-history-adjudication-reviewcore-20261015-r1/app')
    monkeypatch.syspath_prepend(str(root))
    from review_core.stage7_pool import publish_stage7_replay_pool, read_stage7_replay_pool
    out=tmp_path/'pool';published=publish_stage7_replay_pool(out,'20261027','20261028',shared)
    assert published['status']=='READY'
    result=read_stage7_replay_pool('20261028',out)
    spec=importlib.util.spec_from_file_location('r5_stage7_projection',W/'infrastructure/review_core_stage7_pool_source.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    projected=module._project('20261028',out,result)
    assert projected['historical_backfill'] is True
    assert projected['pre_cutoff_capture_verified'] is False and projected['pit_certified'] is False
    assert projected['source_merge_role']=='SOURCE_ONLY' and projected['stage_selection_eligible'] is False
    audit=projected['prior_source_audit'];assert audit['unresolved_prior_diagnostic_count']=='1857'
    assert len(json.loads(base64.urlsafe_b64decode(audit['prior_diagnostics_base64url'])))==1859
    assert len(projected['rows'])==482
    candidate=read_candidate_input(CANDIDATE,'20261027',expected_current_sha256=KW['candidate_current_sha256'])
    assert [row['code'] for row in projected['rows']]==[code.split('.',1)[-1] for code in candidate.codes]
    assert projected['rows'][409]['code']=='603727' and projected['rows'][409]['rank']==410
    provenance=result['artifact']['provenance'];provenance['receipt']['pit_certified']=True
    with pytest.raises(ValueError,match='history flags conflict'):module._project('20261028',out,result)
    assert module._history_evidence({})=={'historical_backfill':None,'pre_cutoff_capture_verified':None,'pit_certified':None}
