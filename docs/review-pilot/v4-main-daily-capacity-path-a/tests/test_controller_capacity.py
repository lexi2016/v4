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


@pytest.mark.parametrize('kind',['valid','omitted','reused_daily','shifted_decomposition','api_rebound'])
def test_root_probe_validates_six_consumer_decomposition(tmp_path,monkeypatch,kind):
    from types import SimpleNamespace
    release=tmp_path/'release';app=release/'app';helper=app/'ops/research_daily_capacity.py'
    helper.parent.mkdir(parents=True);helper.write_text('# isolated approved helper')
    python=release/'runtime/venvs/v4-mac/bin/python';python.parent.mkdir(parents=True);python.touch()
    (release/'runtime/venvs/v4-mac/lib/python3.14/site-packages').mkdir(parents=True)
    policy={'governance':{'registry_root':str(tmp_path/'registry'),'incremental_capacity':{'consumers':{
        'adjustment_snapshot':{'peak_bytes':536870912},
        'formula_supplements':{'peak_bytes':1260912640,'mode':'ENABLED'}}}}}
    path=tmp_path/'policy.json';path.write_text(json.dumps(policy))
    agents=tmp_path/'agents';agents.mkdir()
    api=agents/'com.lexi.v4.api.plist'
    host_path=str(tmp_path/('other-host-binding.json' if kind=='api_rebound' else 'host-binding.json'))
    api.write_bytes(controller.plistlib.dumps({'Label':'com.lexi.v4.api','EnvironmentVariables':{
        'V4_WORKBENCH_HOST_BINDING':host_path,'V4_WORKBENCH_HOST_BINDING_SHA256':'b'*64}}))
    pins=tmp_path/'pins.json'
    pins.write_text(json.dumps({'source_bindings':[{'path':str(api),'sha256':controller.digest(api.read_bytes())}]}))
    plan={'release_root':str(release),'candidate_pins':{'path':str(pins),'sha256':controller.digest(pins.read_bytes())}}
    approved_controller=SimpleNamespace(LAUNCH_AGENTS=agents,LABELS={'api':'com.lexi.v4.api'})
    parts={'native_input':64,'adjustment_snapshot':536870912,'qfq':1024,'daily_product':2048,
           'formula_supplements':1260912640,'top200':4096}
    peaks={'input':parts['native_input']+parts['adjustment_snapshot'],'qfq':parts['qfq'],
           'daily_product':parts['daily_product']+parts['formula_supplements'],'top200':parts['top200']}
    payload=dict(schema='v4.daily_capacity_locked_probe.v1',registry_sha256='a'*64,
        policy_sha256=controller.digest(json.dumps(policy,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()),
        reservation_write=False,reservation_release=False,evidence_scope='PRODUCTION_REVIEWED',eligibility='PASS',
        runtime_inputs=dict(tdx_root=str(tmp_path),receipt_root=str(tmp_path/'receipts'),daily_product_root=str(tmp_path/'products'),
            api_host_binding=dict(path=str(tmp_path/'host-binding.json'),sha256='b'*64)),
        phase_peak_bytes=peaks,consumer_peak_bytes=parts,predicted_peak_bytes=sum(peaks.values()))
    if kind=='omitted':del payload['consumer_peak_bytes']
    elif kind=='reused_daily':parts['formula_supplements']=parts['daily_product']
    elif kind=='shifted_decomposition':parts['qfq']+=1;parts['top200']-=1
    def run_helper(*_args,**_kwargs):
        assert kind!='api_rebound','rebound API must reject before spawning helper'
        return SimpleNamespace(returncode=0,stdout=json.dumps(payload),stderr='')
    monkeypatch.setattr(controller.subprocess,'run',run_helper)
    token=controller._LOCKED_CAPACITY_ROOT.set(policy['governance']['registry_root'])
    try:
        invoke=lambda:controller.locked_capacity_probe(plan,
            {'V4_RESEARCH_RETENTION_POLICY':str(path),'V4_RESEARCH_PANEL_RECEIPT_ROOT':str(tmp_path/'receipts'),
             'V4_A_SHARE_DAILY_PRODUCT_ROOT':str(tmp_path/'products'),'V4_WORKBENCH_HOST_BINDING':str(tmp_path/'host-binding.json'),
             'V4_WORKBENCH_HOST_BINDING_SHA256':'b'*64},controller.digest(path.read_bytes()),'a'*64,
            tdx_root=str(tmp_path),helper_sha=controller.digest(helper.read_bytes()),controller=approved_controller)
        if kind=='valid':
            result=invoke()
            parity=result.pop('api_host_binding_parity')
            assert parity==dict(status='MATCH',api_plist=dict(path=str(api),sha256=controller.digest(api.read_bytes())),
                host_binding=dict(path=str(tmp_path/'host-binding.json'),sha256='b'*64))
            assert result==payload
        elif kind=='api_rebound':
            with pytest.raises(controller.CutoverBlocked,match='MAIN_API_HOST_BINDING_DRIFT'):invoke()
            # Exercise the actual Main transaction orchestration with isolated
            # controller/lock adapters; an admission failure must precede activate.
            from contextlib import nullcontext
            review=tmp_path/'review.json'
            review.write_text(json.dumps({'verdict':'PASS','roles':{'main':{}}}))
            plan.update(approved_candidate_parent=str(tmp_path),controller_plan={
                'roles':[{'role':'main'}],
                'review_approval':{'path':str(review),'sha256':controller.digest(review.read_bytes())}})
            approved_controller.LABELS['main']='com.lexi.v4.scheduler'
            (agents/'.com.lexi.v4.scheduler.release.lock.mutex').touch()
            approved_controller.owned_interprocess_lock=lambda *_a,**_kw:nullcontext()
            approved_controller.load_role=lambda *_:{'before':{}}
            approved_controller.activate=lambda *_:pytest.fail('rebound API reached Main activation')
            monkeypatch.setattr(controller,'check_candidate_source_bindings',lambda *_:{})
            monkeypatch.setattr(controller,'check_evidence',lambda *_:{})
            def isolated_lock(_owner,_role,_plan,stack):
                held=controller._LOCKED_CAPACITY_ROOT.set(policy['governance']['registry_root'])
                stack.callback(controller._LOCKED_CAPACITY_ROOT.reset,held)
            with pytest.raises(controller.CutoverBlocked,match='MAIN_API_HOST_BINDING_DRIFT'):
                controller.activate_main(plan,approved_controller,lock_adapter=isolated_lock,
                    qfq_adapter=lambda *_:{},preflight_adapter=lambda *_:invoke())
        else:
            with pytest.raises(controller.CutoverBlocked,match='CONSUMER_BOUNDS_INVALID'):invoke()
    finally:controller._LOCKED_CAPACITY_ROOT.reset(token)
