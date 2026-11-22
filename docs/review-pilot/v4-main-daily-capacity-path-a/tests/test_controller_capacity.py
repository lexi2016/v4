import importlib.util
import json
from pathlib import Path
from datetime import datetime, timezone

import pytest

SOURCE=Path(__file__).resolve().parents[1]/'cutover/main_only_cutover.py'
SPEC=importlib.util.spec_from_file_location('path_a_controller',SOURCE)
controller=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(controller)


def receipts(tmp_path,*,dynamic=False):
    old=dict(status='CANNOT_CONFIRM',migration='BLOCKED',reviewer='CHAT',old_task_key='a'*64,
        old_target_date='20261120',old_row_sha256='b'*64,
        old_category_remaining_bytes=controller.OLD_CATEGORY_REMAINING,
        old_physical_peak_remaining_bytes=controller.OLD_PHYSICAL_REMAINING)
    new=dict(status='PASS',evidence_closed=True,reviewer='CHAT',release_id='isolated',
        target_date='20261123',classification_basis='DISTINCT_DATE',task_key='c'*64,
        computation_identity_sha256='c'*64,old_task_key=old['old_task_key'],old_row_sha256=old['old_row_sha256'],
        category='ordinary',required_unclassified_task_keys=['a'*64,'d'*64],qfq_kwargs={},child_python_args=[],
        registry_sha256='e'*64,migration='BLOCKED',old_category_remaining_bytes=controller.OLD_CATEGORY_REMAINING,
        old_physical_peak_remaining_bytes=controller.OLD_PHYSICAL_REMAINING)
    new.update(expected_child_environment_sha256='2'*64,expected_child_python_sha256='3'*64,
        candidate_policy_sha256='4'*64,candidate_classification_sha256='5'*64,
        child_identity_receipt_path=str(tmp_path/'child.json'),child_identity_receipt_sha256='6'*64)
    cap=dict(status='PASS',evidence_closed=True,reviewer='CHAT',target_date='20261123',task_key='c'*64,
        registry_sha256='e'*64,old_row_sha256='b'*64,old_category_remaining_bytes=controller.OLD_CATEGORY_REMAINING,
        old_physical_peak_remaining_bytes=controller.OLD_PHYSICAL_REMAINING,
        measured_at='2000-01-01T00:00:00+00:00')
    if dynamic:
        cap.update(schema='v4.daily_capacity_runtime_contract.v1',measurement='LOCKED_AT_EXECUTION',
            live_recheck_required=True,controller_sha256=controller.digest(SOURCE.read_bytes()),
            policy_sha256='f'*64,helper_sha256='1'*64)
        del cap['measured_at']
    cache=dict(status='PASS',evidence_closed=True,reviewer='CHAT',runtime_release_id='isolated')
    rows=dict(old_task_unique_attribution=old,new_date_reviewed_classification=new,
        actual_capacity_preflight=cap,final_cache_negative=cache)
    plan=dict(target_date='20261123',release_id='isolated',admission_evidence={})
    for name,row in rows.items():
        p=tmp_path/name;p.write_text(json.dumps(row))
        plan['admission_evidence'][name]={'path':str(p),'sha256':controller.digest(p.read_bytes())}
    return plan,rows


def test_legacy_undated_capacity_still_rejected(tmp_path):
    plan,_=receipts(tmp_path)
    with pytest.raises(controller.CutoverBlocked,match='STALE_OR_UNDATED'):
        controller.check_evidence(plan)


def test_locked_contract_has_no_five_minute_expiry_but_exact_controller(tmp_path):
    plan,rows=receipts(tmp_path,dynamic=True)
    assert controller.check_evidence(plan)['actual_capacity_preflight']['measurement']=='LOCKED_AT_EXECUTION'
    cap=rows['actual_capacity_preflight'];cap['controller_sha256']='0'*64
    p=Path(plan['admission_evidence']['actual_capacity_preflight']['path']);p.write_text(json.dumps(cap))
    plan['admission_evidence']['actual_capacity_preflight']['sha256']=controller.digest(p.read_bytes())
    with pytest.raises(controller.CutoverBlocked,match='CONTRACT_INVALID'):
        controller.check_evidence(plan)


def test_lock_sequence_preserved_and_includes_pool_then_registry():
    import ast
    source=SOURCE.read_text();tree=ast.parse(source)
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='acquire_switch_locks')
    literal=ast.get_source_segment(source,node)
    assert 'for name in ("pool-writer.lock", "registry.lock")' in literal
    assert literal.index('scheduler_lane_owners')<literal.index('other_label')<literal.index('pool-writer.lock')


def test_dynamic_probe_cannot_run_outside_full_switch_lock_scope(tmp_path):
    policy=tmp_path/'policy.json';policy.write_text(json.dumps({'governance':{'registry_root':str(tmp_path/'registry')}}))
    environment={'V4_RESEARCH_RETENTION_POLICY':str(policy)}
    with pytest.raises(controller.CutoverBlocked,match='REQUIRES_ALL_SWITCH_LOCKS'):
        controller.locked_capacity_probe({},environment,controller.digest(policy.read_bytes()),'0'*64,
            tdx_root=str(tmp_path),helper_sha='1'*64)
