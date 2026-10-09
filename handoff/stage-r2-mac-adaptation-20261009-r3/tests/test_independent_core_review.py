"""Independent scenarios against the live lane_core candidate; no source edits."""
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path

from stage_center import runner as runtime
from stage_center.acquisition import SourceResult
from stage_center._runner_parts.runner_receipts import _ExecutionScope

import test_slot_market_isolation as support
DATE,STAGE=support.DATE,support.STAGE


def test_owner_source_identity_does_not_accept_stale_payload_observation(tmp_path,monkeypatch):
    owner,_=support.setup_runner(tmp_path,monkeypatch,{'A_SHARE':support.a_builder,'HK_CONNECT':support.hk_builder})
    stale={'scope':'LOADED_MODULE_PATHS_AND_OBSERVED_FILE_BYTES','status':'OBSERVED',
           'memory_execution_attested':False,'source_set_sha256':'0'*64,
           'files':{'stage_center/runner.py':{'module':'stage_center.runner',
                    'loaded_path':'/previous_owner/stage_center/runner.py','sha256':'0'*64}}}
    result=owner._write_receipt({'trade_date':DATE,'stage_id':STAGE,'status':'CANNOT_CONFIRM',
        'markets':{},'runtime_source_identity':stale},DATE,STAGE)
    observation=result['runtime_source_identity']['files']['stage_center/runner.py']
    assert observation['loaded_path']==str(Path(runtime.__file__).resolve())
    assert observation['sha256']==hashlib.sha256(Path(runtime.__file__).read_bytes()).hexdigest()


def test_hk_invalid_raw_projection_does_not_prevent_valid_a_selection(tmp_path,monkeypatch):
    owner,decision=support.setup_runner(tmp_path,monkeypatch,{'A_SHARE':support.a_builder,'HK_CONNECT':support.hk_builder})
    bad=[dict(row) for row in support.raw_rows('HK_CONNECT')]
    del bad[0]['bid_vol']
    owner.collectors['HK_CONNECT']=lambda plan,market:SourceResult('fixture','READY',tuple(bad),requested_rows=12)
    result=owner._run_one(decision)
    assert result['markets']['A_SHARE'].get('selected_rows')==10,result
    assert result['markets']['A_SHARE']['requested_rows']==216
    assert result['markets']['HK_CONNECT']['status']=='CANNOT_CONFIRM'


def test_scoped_merge_preserves_manual_invocation_origin(tmp_path):
    prior={'trade_date':DATE,'stage_id':STAGE,'markets':{'A_SHARE':{'run_id':'preserved-a','rows':[{'code':'A.000001'}]}},
           'execution_origin':'OWNER_TICK_UNVERIFIED','dispatch_mode':'NATURAL'}
    scope=_ExecutionScope(('HK_CONNECT',),prior,2,'DEPENDENCY_REARM')
    out=scope.merge({'trade_date':DATE,'stage_id':STAGE,'execution_origin':'MANUAL_REPLAY',
                     'markets':{'HK_CONNECT':{'status':'CANNOT_CONFIRM','selected_rows':0}}},DATE,STAGE)
    assert out['markets']['A_SHARE']==prior['markets']['A_SHARE']
    assert out['execution_origin']=='MANUAL_REPLAY'


def test_scoped_merge_never_overwrites_preserved_a_with_hk_error_payload():
    prior={'trade_date':DATE,'stage_id':STAGE,'markets':{'A_SHARE':{'run_id':'a','rows':[{'code':'A.000001'}]}},
           'selection_artifacts':{'A_SHARE':{'run_id':'a','artifact_bytes_sha256':'a'*64}},
           'input_bindings':{'A_SHARE':{'run_id':'a-input','row_count':216}}}
    out=_ExecutionScope(('HK_CONNECT',),prior,2,'DEPENDENCY_REARM').merge(
        {'trade_date':DATE,'stage_id':STAGE,'markets':{'A_SHARE':{'status':'CANNOT_CONFIRM'},'HK_CONNECT':{'status':'CANNOT_CONFIRM'}},
         'selection_artifacts':{'A_SHARE':{}},'input_bindings':{'A_SHARE':{}}},DATE,STAGE)
    for key in ('markets','selection_artifacts','input_bindings'):
        assert out[key]['A_SHARE']==prior[key]['A_SHARE']
