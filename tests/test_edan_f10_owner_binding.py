"""Exercise the installed Main publisher and its real lock helper on an isolated index."""
import hashlib
import importlib.util
import json
from pathlib import Path
import runpy
import shutil

import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('edan_f10_owner_binding_test',ROOT/'ops/edan_f10_owner_binding.py')
owner=importlib.util.module_from_spec(spec);spec.loader.exec_module(owner)


def test_running_main_and_imported_lock_owner_are_exact(monkeypatch):
    owner.verify_entrypoint(hashlib.sha256(Path(owner.__file__).read_bytes()).hexdigest())
    with pytest.raises(ValueError,match='F10_BINDING_ENTRYPOINT_DRIFT'):
        owner.verify_entrypoint('f'*64)
    assert owner.verify_running_owner(owner.PIN['plan'])['pid']==owner.MAIN_PID
    modules=owner._load_bound_modules()
    assert Path(modules['ops.sync_stock_history_completion'].__file__).resolve()==owner.MAIN/'ops/sync_stock_history_completion.py'
    assert callable(modules['ops.sync_stock_history_completion']._inherited_owner_duplicate)
    with pytest.raises(ValueError,match='F10_OWNER_PLAN_OR_SCRIPT_DRIFT'):
        owner.verify_running_owner('f'*64)
    with monkeypatch.context() as changed:
        changed.setitem(owner.PIN,'ops.sync_stock_history_completion','f'*64)
        with pytest.raises(ValueError,match='F10_MAIN_MODULE_DRIFT:ops.sync_stock_history_completion'):
            owner.verify_running_owner(owner.PIN['plan'])


def test_actual_publisher_updates_only_isolated_index_event_and_rejects_stale_cas(tmp_path,monkeypatch):
    modules=owner._load_bound_modules();f10=modules['ops.research_panel_f10'];sync=modules['ops.sync_stock_history_completion']
    scope=runpy.run_path(str(owner.SCRIPT),run_name='f10_owner_test_only')
    ctx,plan=scope['check'](owner.PIN['plan'])
    root=tmp_path/'a_share';(root/'events').mkdir(parents=True)
    ip=root/'index.json';ep=root/'events/latest.json'
    shutil.copyfile(plan['index_before']['path'],ip);shutil.copyfile(plan['event_before']['path'],ep)
    before_i=json.loads(ip.read_text());before_e=json.loads(ep.read_text())
    expected_i=hashlib.sha256(ip.read_bytes()).hexdigest();expected_e=hashlib.sha256(ep.read_bytes()).hexdigest()
    assert (expected_i,expected_e)==(plan['index_before']['sha256'],plan['event_before']['sha256'])
    lock=tmp_path/'A_LONG.lock';lock.touch();monkeypatch.setattr(sync,'DEFAULT_OWNER_LOCK',lock)
    for key in ('V4_SCHEDULER_LANE_FD','V4_SCHEDULER_LANE_NAME','V4_SCHEDULER_RESOLVED_DATE','V4_SCHEDULER_RESOLVED_SLOT'):
        monkeypatch.delenv(key,raising=False)
    result=f10.publish_f10_completion(ctx,root,plan['new_receipt'],expected_index_sha256=expected_i,expected_event_sha256=expected_e)
    assert result['status']=='PUBLISHED_F10_COMPLETION'
    after_i=json.loads(ip.read_text());after_e=json.loads(ep.read_text())
    assert after_i['f10']['20261030']==after_e['f10']==plan['new_receipt']
    assert {k:v for k,v in before_i.items() if k!='f10'}=={k:v for k,v in after_i.items() if k!='f10'}
    assert {k:v for k,v in before_e.items() if k not in ('f10','event_id')}=={k:v for k,v in after_e.items() if k not in ('f10','event_id')}
    checkpoint=scope['read'](scope['read'](plan['new_receipt'])['checkpoint'])
    assert {k:checkpoint['items'][k]['sha256'] for k in plan['prior_items']}=={k:v['sha256'] for k,v in plan['prior_items'].items()}
    assert checkpoint['items']['300206.SZ']['sha256']==plan['third_source']['sha256']
    final=(ip.read_bytes(),ep.read_bytes())
    with pytest.raises(ValueError,match='F10_EXPECTED_INDEX_EVENT_CAS_MOVED'):
        f10.publish_f10_completion(ctx,root,plan['new_receipt'],expected_index_sha256=expected_i,expected_event_sha256=expected_e)
    assert final==(ip.read_bytes(),ep.read_bytes())
