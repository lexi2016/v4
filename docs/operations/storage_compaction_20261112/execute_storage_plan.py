"""Explicit original-owner D12 maintenance runner; read-only preflight by default.

Pin actual Main imports and reviewed bytes before using the existing writer
locks. No collector/model/asset completion, source acquisition or service action.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import sys

sys.dont_write_bytecode=True


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def require(condition,message):
    if not condition:raise RuntimeError(message)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--expected-plan-sha256',required=True)
    parser.add_argument('--expected-main-manifest-sha256',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    packet=Path(__file__).resolve().parent
    binding=json.loads((packet/'SOURCE_BINDING.json').read_bytes())
    plist_path=Path.home()/'Library/LaunchAgents/com.lexi.v4.scheduler.plist'
    plist_raw=plist_path.read_bytes();env=plistlib.loads(plist_raw)['EnvironmentVariables']
    app=Path(env['V4_APP_ROOT']);seal=Path(env['V4_RELEASE_MANIFEST_PATH'])
    require(sha(seal)==env['V4_RELEASE_MANIFEST_SHA256']==args.expected_main_manifest_sha256,'ACTIVE_MAIN_MANIFEST_DRIFT')
    manifest=json.loads(seal.read_bytes());pins={e['path']:e['sha256'] for e in manifest['app_files']}
    require(app==Path(manifest['app_root']),'ACTIVE_MAIN_APP_ROOT_DRIFT')
    require(sha(args.plan)==args.expected_plan_sha256==binding['dry_run']['sha256'],'REVIEWED_PLAN_SHA_DRIFT')
    plan=json.loads(args.plan.read_bytes())
    require(plan['status']=='DRY_RUN_NO_DATA_WRITES','DRY_RUN_PLAN_REQUIRED')
    # Match Main's own environment, while putting the actual active app first.
    # Never echo environment values or trust the shell's old source aliases.
    os.environ.update(env)
    paths=[str(app),*env.get('PYTHONPATH','').split(os.pathsep)]
    os.environ['PYTHONPATH']=os.pathsep.join(dict.fromkeys(x for x in paths if x))
    sys.path.insert(0,str(app))
    from ops import research_storage_governance as governance
    from ops import research_storage_retention as retention
    module_refs={}
    for name,module in [('ops/research_storage_governance.py',governance),('ops/research_storage_retention.py',retention)]:
        require(Path(module.__file__).resolve()==app/name,'ACTIVE_MAIN_IMPORTED_ALIAS:'+name)
        require(sha(module.__file__)==pins[name],'ACTIVE_MAIN_IMPORTED_SOURCE_DRIFT:'+name)
        module_refs[name]=dict(path=module.__file__,sha256=sha(module.__file__))
    source=Path(binding['source_root'])/'ops/research_storage_compaction.py'
    expected=binding['main_delta']['ops/research_storage_compaction.py']['after_sha256']
    require(sha(source)==expected,'REVIEWED_COMPACTION_SOURCE_DRIFT')
    spec=importlib.util.spec_from_file_location('ops.research_storage_compaction',source)
    compaction=importlib.util.module_from_spec(spec);sys.modules[spec.name]=compaction;spec.loader.exec_module(compaction)
    policy_path=Path(env['V4_RESEARCH_RETENTION_POLICY'])
    require(sha(policy_path)==env['V4_RESEARCH_RETENTION_POLICY_SHA256'],'ACTIVE_MAIN_POLICY_DRIFT')
    policy=governance.configured_policy()
    require(policy==json.loads(policy_path.read_bytes()),'ACTIVE_MAIN_POLICY_RESOLUTION_DRIFT')
    require(args.output.is_absolute() and not args.output.exists(),'NEW_ABSOLUTE_RECEIPT_REQUIRED')
    retention.safe_path(args.output,exists=False)
    resource=compaction.resources()
    registry=governance.Registry(governance.configuration(policy),policy['data_root'])
    # Check readiness without creating a business artifact or copying data.
    with registry.writer(),compaction.closed_owner_locks(plan['job']):
        require(compaction.stamp_digest(compaction.inventory(plan['job']['roots']))==plan['scope_stamp_sha256'],'PLAN_SCOPE_STAMP_DRIFT')
    require(plist_path.read_bytes()==plist_raw,'MAIN_PLIST_MOVED_DURING_PREFLIGHT')
    if args.execute:
        result=compaction.execute_plan(plan,policy=policy,output=args.output)
        status=result['status']
    else:
        result=dict(status='PREFLIGHT_READY_NO_DATA_WRITES',plan_sha256=args.expected_plan_sha256,
            main_manifest_sha256=args.expected_main_manifest_sha256,module_refs=module_refs,
            compaction_source=dict(path=str(source),sha256=expected),resources=resource,
            RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
        retention.atomic_json(args.output,result);status=result['status']
    print(json.dumps(dict(status=status,receipt=dict(path=str(args.output),sha256=sha(args.output)))))


if __name__=='__main__':main()
