#!/usr/bin/env python3
"""Capture allowlisted API/scheduler identity and binding gates; never copy full plist/config."""
from __future__ import annotations
import hashlib, json, plistlib, subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

E=Path('/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_DAILY_FAILURE_R3_20261009')
API_PLIST=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist')
SCHED_PLIST=Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist')
API_ROOT=Path('/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/candidate/issue32_preselection_api_actual_r4/app')
API_BINDING=Path('/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_DAILY_CHAIN_20261008/deployment/c1_plan_only/staged_config/manager-plan-binding-c1.disabled.final-d1-r2.json')
SCHEDULER_ROOT=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/issue32-preselection-scheduler-mac-20261009-r1/app')
WORKER_ROOT=Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/manager-us-mapping-daily-20261006-r2/app')
TZ=ZoneInfo('Asia/Shanghai')
API_ALLOW={'V35_APP_ROOT','V35_RELEASE_ID','V35_RELEASE_MANIFEST_SHA256','V4_MANAGER_PLAN_OWNER_BINDING_PATH','RESEARCH_ONLY','production_allowed','buy_gate_updated','orders_sent'}
SCHED_ALLOW={'V35_APP_ROOT','V4_MANAGER_ANNOUNCEMENT_APP_ROOT','V4_MANAGER_ANNOUNCEMENT_BINDING','V4_MANAGER_ANNOUNCEMENT_PYTHON','V4_MANAGER_ANNOUNCEMENT_PYTHON_SHA256','V4_MANAGER_ANNOUNCEMENT_CYCLE_SHA256','V4_MANAGER_ANNOUNCEMENT_PLAN_CANARY_SHA256','V35_RESEARCH_PANEL_HK_CHILD_APP_ROOT','V35_RESEARCH_PANEL_HK_UPDATER_SCRIPT'}
BINDING_FIELDS={'schema_version','enabled','policy_status','policy','app_root','plan_material_refresh_only','announcement_collection_enabled','research_only','production_allowed','buy_gate_updated','orders_sent'}
NESTED_FIELDS={'enabled','status','start_local','end_local','max_attempts_per_target_date','retry_backoff_seconds','lead_seconds'}
CANARY_FIELDS={'schema_version','status','execution_mode','hook_executed','plan_material_refresh_only','announcement_collection_enabled','announcement_network_requests','research_only','production_allowed','buy_gate_updated','orders_sent'}

def now(): return datetime.now(TZ).isoformat(timespec='milliseconds')
def digest(data): return hashlib.sha256(data).hexdigest()
def env_args(args, allow):
    result={}
    for token in args:
        if isinstance(token,str) and '=' in token:
            key,value=token.split('=',1)
            if key in allow: result[key]=value
    return result
def service_rows():
    cp=subprocess.run(['launchctl','list'],capture_output=True,text=True,check=True)
    wanted={'com.lexi.v35.api-only','com.lexi.v35.scheduler'}
    out={}
    for line in cp.stdout.splitlines():
        parts=line.split()
        if len(parts)>=3 and parts[-1] in wanted:
            out[parts[-1]]={'pid':parts[0] if parts[0]!='-' else None,'last_exit_code':parts[1]}
    return out
def read_plist(path, allow):
    raw=path.read_bytes(); doc=plistlib.loads(raw); args=doc.get('ProgramArguments',[]); env=dict(doc.get('EnvironmentVariables',{}))
    selected=env_args(args,allow); selected.update({k:v for k,v in env.items() if k in allow})
    return {'path':str(path),'sha256':digest(raw),'label':doc.get('Label'),'working_directory':doc.get('WorkingDirectory'),'launcher':args[0] if args else None,'launch_policy':{k:doc[k] for k in ('RunAtLoad','KeepAlive','StartCalendarInterval') if k in doc},'allowlisted_runtime_values':selected}
def binding_projection(path):
    raw=path.read_bytes(); value=json.loads(raw.decode('utf-8'))
    result={k:value[k] for k in BINDING_FIELDS if k in value}
    for key in ('plan_material_refresh','preopen_plan'):
        nested=value.get(key)
        if isinstance(nested,dict): result[key]={k:nested[k] for k in NESTED_FIELDS if k in nested}
    canary_ref=value.get('plan_activation_receipt')
    canary=None
    if isinstance(canary_ref,dict) and isinstance(canary_ref.get('path'),str):
        cp=Path(canary_ref['path'])
        if cp.is_file():
            cb=cp.read_bytes(); cj=json.loads(cb.decode('utf-8'))
            canary={'sha256':digest(cb),'bytes':len(cb),'pinned_sha_matches':digest(cb)==canary_ref.get('sha256'),'allowlisted_fields':{k:cj[k] for k in CANARY_FIELDS if k in cj}}
        else: canary={'exists':False,'pinned_sha_matches':False}
    return {'path':str(path),'sha256':digest(raw),'bytes':len(raw),'allowlisted_fields':result,'plan_canary':canary}
def file_identity(root, rel):
    p=root/rel
    if not p.is_file(): return {'path':str(p),'exists':False,'sha256':None,'bytes':None}
    raw=p.read_bytes(); return {'path':str(p),'exists':True,'sha256':digest(raw),'bytes':len(raw)}

api=read_plist(API_PLIST,API_ALLOW)
scheduler=read_plist(SCHED_PLIST,SCHED_ALLOW)
rows=service_rows(); api['launchd_state']=rows.get(api['label'],'CANNOT_CONFIRM'); scheduler['launchd_state']=rows.get(scheduler['label'],'CANNOT_CONFIRM')
api_values=api['allowlisted_runtime_values']; sched_values=scheduler['allowlisted_runtime_values']
api_bind=Path(api_values['V4_MANAGER_PLAN_OWNER_BINDING_PATH'])
sched_bind=Path(sched_values['V4_MANAGER_ANNOUNCEMENT_BINDING'])
api_owner_binding=binding_projection(api_bind); scheduler_binding=binding_projection(sched_bind)
api['plan_owner_binding']=api_owner_binding
scheduler['announcement_plan_binding']=scheduler_binding
scheduler['announcement_worker_source_identity']={
 'cycle':file_identity(WORKER_ROOT,'ops/run_manager_announcement_cycle.py'),
 'supervisor':file_identity(WORKER_ROOT,'infrastructure/scheduling/manager_announcement_supervisor.py'),
 'worker_dispatch_client':file_identity(WORKER_ROOT,'v4/manager_research/plan_owner_dispatch.py'),
}
scheduler['scheduler_dispatch_source_identity']={
 'daemon':file_identity(SCHEDULER_ROOT,'ops/run_v35_macos_scheduler_daemon.py'),
 'launcher':file_identity(SCHEDULER_ROOT,'ops/launch_v35_macos_scheduler.sh'),
}
identity_match={
 'scheduler_binding_sha_equals_api_plan_owner_binding_sha':scheduler_binding['sha256']==api_owner_binding['sha256'],
 'scheduler_binding_app_root_equals_current_api_root':scheduler_binding['allowlisted_fields'].get('app_root')==api_values.get('V35_APP_ROOT'),
 'api_plan_owner_binding_app_root_equals_current_api_root':api_owner_binding['allowlisted_fields'].get('app_root')==api_values.get('V35_APP_ROOT'),
 'scheduler_binding_app_root_equals_bound_worker_root':scheduler_binding['allowlisted_fields'].get('app_root')==sched_values.get('V4_MANAGER_ANNOUNCEMENT_APP_ROOT'),
 'scheduler_cycle_sha_pin_matches_bound_worker_file':sched_values.get('V4_MANAGER_ANNOUNCEMENT_CYCLE_SHA256')==scheduler['announcement_worker_source_identity']['cycle'].get('sha256'),
}
doc={
 'schema_version':'v4.manager_daily_failure_r3.runtime_identity.v2',
 'captured_at_cst':now(),
 'api_8873':api,
 'shared_scheduler':scheduler,
 'binding_identity_comparison':identity_match,
 'static_dispatch_path':{
  'scheduler_daemon':'ops/run_v35_macos_scheduler_daemon.py::_load_announcement_binding validates the current bound scheduler JSON; in plan-only mode it requires enabled=true and plan_material_refresh.enabled=true, then creates the bound cycle child.',
  'bound_cycle':'ops/run_manager_announcement_cycle.py calls request_bound_plan_cycle(args.binding, plan_target) when the plan-only target is due; otherwise it returns NOT_DUE. This task did not invoke the cycle.',
  'api_owner':'v4/manager_research/plan_owner_dispatch.py::execute_bound_plan_cycle loads V4_MANAGER_PLAN_OWNER_BINDING_PATH, compares its SHA with the request binding_sha256, validates it against the running API APP_ROOT, then checks enabled.',
  'predicted_first_gate_if_request_arrives':'PLAN_OWNER_BINDING_SHA_MISMATCH because the current scheduler binding and API owner binding SHA differ. This is a static code/config inference, not an observed dispatch error.',
  'later_config_gates_if_sha_were_aligned':'API owner binding app_root is not the current API root and enabled=false; neither gate was exercised in this read-only package task.'
 },
 'owner_dispatch_observation':{'specific_manager_daily_dispatch_receipt':'CANNOT_CONFIRM','reason':'No owner-specific dispatch receipt was read; launchd state proves only that the scheduler/API processes were running.'},
 'historical_automation_pointer':{'automation_id':'automation-3','current_exact_toml_path':'/Users/lexi/.codex/automations/automation-3/automation.toml','exists':False,'basis':'R2 input audit; current configuration and enabled state remain CANNOT_CONFIRM.'},
 'safety_flags':{'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False},
 'capture_limits':'Only exact plist hashes, selected non-sensitive runtime values, launchd pid/exit codes, selected binding/canary fields, and source identities are included. Full plist, automation prompt, credentials, process environment, and plan/state data are not copied.'
}
out=E/'evidence'/'runtime_identity.json'; out.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(doc,ensure_ascii=False,indent=2))
