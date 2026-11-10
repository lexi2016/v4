"""One-field storage capacity repair; same Main app, Stage and API tuple.

Preparation never changes a live plist or runs a producer. Controller cutover
requires the exact independent packet PASS and reuses existing service helpers.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys

from ops import activate_daily_materials_release as svc
from ops.prepare_top200_scope_release import (
    _service, _inventory, checked, record, assert_main_policy_only,
    loaded_environment_check,
)
from ops.prepare_v192_group_release import save
from ops.prepare_daily_materials_release import sha

GIB = 1024**3
OLD_BUDGET = 160*GIB
NEW_BUDGET = 224*GIB
BASE_PLISTS = {
    'main': 'db82a2953124e4631501af08c4a912a9769cd787538db664e213c005b5753ada',
    'api': 'ae03403a80079c7502eac9d020d9905a50cc4447828e0a3fe07fbc2ec00b6d02',
    'stage': 'b107beee2101c2de27848d08003ba1f7fdb0f4de463e2f7cd39c6c346ada24cb',
}
LABELS = {'main':'com.lexi.v4.scheduler', 'api':'com.lexi.v4.api',
          'stage':'com.lexi.stage-center.scheduler'}
CAPACITY = dict(category_baseline_bytes=132064048368,
    formula_forecast_bytes=51539607552, retained_other_remaining_bytes=34713812416)


def budget_policy(before):
    if before['governance']['ordinary_peak_budget_bytes'] != OLD_BUDGET:
        raise ValueError('EXACT_160_GIB_POLICY_REQUIRED')
    after = deepcopy(before)
    after['governance']['ordinary_peak_budget_bytes'] = NEW_BUDGET
    return after


def assert_policy_delta(before, after):
    if after != budget_policy(before):
        raise ValueError('POLICY_CHANGE_OUTSIDE_ORDINARY_160_TO_224_GIB')


def capacity_check(policy):
    """Read current disk and retained reservations with original gate semantics.

    This is a bounded admission precheck, not a reservation or forecast change.
    Actual formula owner repeats admission with freshly measured residents.
    """
    pins=json.loads(checked(policy['managed_pin_inventory']).read_text())
    app_root=pins['expected_main_app_root']
    program = """import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from ops import research_storage_governance as g
policy=json.loads(sys.stdin.read())
registry=g.Registry(g.configuration(policy),policy['data_root'])
with registry.writer(),registry.transaction():
 state=registry.read()
 sample=registry.space(state,'__budget_precheck__',int(sys.argv[2]),category='ordinary',optional_full=False,category_used=int(sys.argv[3]))
sample['gate_source']=str(Path(g.__file__).resolve())
print(json.dumps(sample))
"""
    result=subprocess.run([sys.executable,'-B','-c',program,app_root,
        str(CAPACITY['formula_forecast_bytes']),str(CAPACITY['category_baseline_bytes'])],
        input=json.dumps(policy),capture_output=True,text=True,timeout=30)
    if result.returncode != 0:
        raise ValueError('ORIGINAL_STORAGE_GATE_PRECHECK_REJECTED:'+result.stderr[-2048:])
    sample=json.loads(result.stdout)
    if sample.get('gate_source') != str(Path(app_root)/'ops/research_storage_governance.py'):
        raise ValueError('ORIGINAL_STORAGE_GATE_SOURCE_DRIFT')
    sample.update(category_baseline_bytes=CAPACITY['category_baseline_bytes'],
        formula_forecast_bytes=CAPACITY['formula_forecast_bytes'],
        ordinary_budget_bytes=policy['governance']['ordinary_peak_budget_bytes'])
    return sample


def prepare(output):
    approved = Path.home()/'Library/Application Support/com.lexi.v4.local/candidates'
    if (output != approved/'v4-daily-storage-recovery-20261110-r2'
            or output.resolve() != output or output.exists()):
        raise ValueError('EXACT_NEW_R2_CANDIDATE_REQUIRED')
    home = Path.home()/'Library/LaunchAgents'
    services = {role:_service(home/(label+'.plist')) for role,label in LABELS.items()}
    if {role:s['before_sha256'] for role,s in services.items()} != BASE_PLISTS:
        raise ValueError('EXACT_INSTALLED_R1_TUPLE_REQUIRED')
    for service in services.values():_inventory(service)
    main = services['main']
    env = main['baseline_payload']['EnvironmentVariables']
    old_policy = checked(dict(path=env['V4_RESEARCH_RETENTION_POLICY'],
        sha256=env['V4_RESEARCH_RETENTION_POLICY_SHA256']))
    before = json.loads(old_policy.read_text())
    pins_path = checked(before['managed_pin_inventory'])
    pins = json.loads(pins_path.read_text())
    if (pins['expected_main_app_root'] != main['app_root']
            or len(pins['source_bindings']) != 24
            or any(r['path'] == main['live_plist'] for r in pins['source_bindings'])):
        raise ValueError('EXACT_24_PINS_WITHOUT_MAIN_REVERSE_CYCLE_REQUIRED')
    for reference in pins['source_bindings']:checked(reference)
    after = budget_policy(before)
    sample = capacity_check(after)  # No new candidate on real low-space failure.
    output.mkdir()
    policy_path = output/'research_storage_policy.json'
    save(policy_path, after)
    payload = deepcopy(main['baseline_payload'])
    payload['EnvironmentVariables'].update(V4_RESEARCH_RETENTION_POLICY=str(policy_path),
        V4_RESEARCH_RETENTION_POLICY_SHA256=sha(policy_path))
    assert_main_policy_only(main['baseline_payload'],payload)
    draft = output/'MAIN_POLICY_CANDIDATE.plist'
    draft.write_bytes(plistlib.dumps(payload,sort_keys=True));draft.chmod(0o600)
    main.update(draft_plist=str(draft),draft_plist_sha256=sha(draft))
    root = Path(__file__).resolve().parents[1]
    tools = [Path(__file__), root/'ops/activate_daily_materials_release.py',
        root/'ops/prepare_top200_scope_release.py', root/'ops/prepare_daily_materials_release.py',
        root/'ops/prepare_v192_group_release.py', root/'ops/api_release_integration.py']
    packet = dict(schema='v4.daily_storage_budget_recovery.v1',status='PREPARED_NOT_ACTIVATED',
        root=str(output),services=services,control_roles=['main'],old_policy=record(old_policy),
        policy=record(policy_path),pins=record(pins_path),tool_source_files=[record(p) for p in tools],
        capacity=CAPACITY,capacity_observation=sample,
        scheduler_lane_lock_root=str(Path.home()/'Library/Application Support/com.lexi.v35.local/state/dispatcher/scheduler_lane_owners'),
        RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
    save(output/'PACKET.json',packet)
    result=validate(packet)
    save(output/'DEPENDENCY_CHECK.json',result)
    return dict(packet=str(output/'PACKET.json'),packet_sha256=sha(output/'PACKET.json'),check=result)


def validate(packet, *, installed=False, restored=False):
    approved = Path.home()/'Library/Application Support/com.lexi.v4.local/candidates/v4-daily-storage-recovery-20261110-r2'
    if packet['root'] != str(approved) or approved.resolve() != approved:
        raise ValueError('EXACT_R2_CANDIDATE_REQUIRED')
    if packet['control_roles'] != ['main'] or packet['capacity'] != CAPACITY:
        raise ValueError('EXACT_MAIN_ONLY_CAPACITY_SCOPE_REQUIRED')
    for reference in packet['tool_source_files']+[packet['old_policy'],packet['policy'],packet['pins']]:checked(reference)
    before = json.loads(checked(packet['old_policy']).read_text())
    after = json.loads(checked(packet['policy']).read_text())
    assert_policy_delta(before,after)
    if before['managed_pin_inventory'] != packet['pins'] or after['managed_pin_inventory'] != packet['pins']:
        raise ValueError('PIN_REFERENCE_MUST_REMAIN_IDENTICAL')
    services=packet['services']
    if set(services) != {'main','api','stage'}:raise ValueError('EXACT_TUPLE_REQUIRED')
    for role,service in services.items():
        _inventory(service)
        if (service['app_root'] != service['old_app_root'] or service['manifest_sha256'] != service['old_manifest_sha256']
                or service['before_sha256'] != BASE_PLISTS[role]):
            raise ValueError('APP_RELEASE_OR_BASELINE_DRIFT:'+role)
        expected = service['before_sha256']
        if role == 'main':
            checked(dict(path=service['draft_plist'],sha256=service['draft_plist_sha256']))
            original=service['baseline_payload']
            draft=plistlib.loads(Path(service['draft_plist']).read_bytes())
            assert_main_policy_only(original,draft)
            wanted=deepcopy(original)
            wanted['EnvironmentVariables'].update(V4_RESEARCH_RETENTION_POLICY=packet['policy']['path'],
                V4_RESEARCH_RETENTION_POLICY_SHA256=packet['policy']['sha256'])
            if draft != wanted:raise ValueError('EXACT_TWO_MAIN_POLICY_FIELDS_REQUIRED')
            if installed and not restored:expected=service['draft_plist_sha256']
        if sha(Path(service['live_plist'])) != expected:raise ValueError('LIVE_PLIST_CAS_DRIFT:'+role)
    pins=json.loads(checked(packet['pins']).read_text())
    if (pins['expected_main_app_root'] != services['main']['app_root'] or len(pins['source_bindings']) != 24
            or any(r['path'] == services['main']['live_plist'] for r in pins['source_bindings'])):
        raise ValueError('PIN_BINDING_DRIFT')
    for reference in pins['source_bindings']:checked(reference)
    return dict(status='PASS_ONE_POLICY_FIELD_MAIN_TWO_ENV_FIELDS_API_STAGE_UNCHANGED',
        source_bindings_checked=24,control_roles=['main'],
        projected_category_peak_bytes=sum(CAPACITY.values()),
        category_headroom_bytes=NEW_BUDGET-sum(CAPACITY.values()),
        mode='RESTORED' if restored else 'INSTALLED' if installed else 'PREPARED')


def cutover(packet_path,review_path, *, rollback=False):
    packet=json.loads(packet_path.read_text());review=json.loads(review_path.read_text())
    if review.get('verdict') not in {'PASS','REVIEWED/PASS'} or review.get('packet_sha256') != sha(packet_path):
        raise ValueError('INDEPENDENT_REVIEW_PACKET_BINDING_REQUIRED')
    validate(packet,installed=rollback)
    main=packet['services']['main'];controlled={'main':main}
    backup=packet_path.parent/'main-policy-backup';backup.mkdir(exist_ok=True)
    held=[];stopped=[]
    state=dict(status='PRECHECK',rollback_requested=rollback,stopped=stopped,
        control_roles=['main'],api_service_operation=False,stage_service_operation=False,business_data_written=False)
    try:
        for name in ('DEFAULT.lock','A_LONG.lock'):
            stream=(Path(packet['scheduler_lane_lock_root'])/name).open('a+')
            held.append(stream);fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        svc.require_idle_main(main)
        loaded_environment_check(main)
        if not rollback:
            capacity_check(json.loads(checked(packet['policy']).read_text()))
        if rollback:svc.require_previous_backups(controlled,backup)
        else:
            destination=backup/'main.plist';live=Path(main['live_plist'])
            if destination.exists() and destination.read_bytes() != live.read_bytes():raise ValueError('BACKUP_DRIFT')
            destination.write_bytes(live.read_bytes());destination.chmod(0o600)
        # Recheck CAS and loaded identity immediately before service control.
        validate(packet,installed=rollback)
        svc.require_idle_main(main)
        _,pid=svc.loaded(main['label']);tracked=svc.descendants(pid)
        svc.run(['launchctl','bootout',f'gui/{os.getuid()}/{main["label"]}']).check_returncode()
        stopped.append('main');svc.wait_drained(main['label'],tracked)
        source=backup/'main.plist' if rollback else Path(main['draft_plist'])
        svc.replace_cas(Path(main['live_plist']),source,main['draft_plist_sha256'] if rollback else main['before_sha256'])
        validate(packet,installed=not rollback,restored=rollback)
        svc.run(['launchctl','bootstrap',f'gui/{os.getuid()}',main['live_plist']]).check_returncode()
        svc.wait_running(main);loaded_environment_check(main)
        validate(packet,installed=not rollback,restored=rollback)
        state['status']='RESTORED_ORIGINAL_MAIN_POLICY' if rollback else 'ACTIVATED_MAIN_POLICY_ONLY'
    except BaseException as error:
        state.update(status='FAILED',error=type(error).__name__+':'+str(error))
        if not rollback and stopped:
            try:
                state['recovery']=svc.restore_services(controlled,backup,stopped)
                validate(packet,restored=True);loaded_environment_check(main)
            except BaseException as recovery:state['recovery']=dict(status='CANNOT_CONFIRM_REQUIRES_CONTROLLER',error=str(recovery))
        raise
    finally:
        save(packet_path.parent/'ACTIVATION_RECEIPT.json',state)
        for stream in reversed(held):fcntl.flock(stream,fcntl.LOCK_UN);stream.close()
    return state


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('operation',choices=['prepare','validate','activate','rollback'])
    parser.add_argument('--output',type=Path);parser.add_argument('--packet',type=Path)
    parser.add_argument('--review',type=Path);parser.add_argument('--installed',action='store_true')
    args=parser.parse_args()
    if args.operation=='prepare':result=prepare(args.output)
    elif args.operation=='validate':result=validate(json.loads(args.packet.read_text()),installed=args.installed)
    else:result=cutover(args.packet,args.review,rollback=args.operation=='rollback')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
