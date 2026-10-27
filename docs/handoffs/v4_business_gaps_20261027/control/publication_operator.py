"""Reviewed controller utility; writer only prepares it, never invokes actions.

API/main quiescence and one-shot natural drain remain the controller's
existing guarded lifecycle. This utility refuses to install a loaded label.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo
import plistlib
import re
import shutil
import subprocess

CASE=Path(__file__).resolve().parent.parent
def sha(raw): return hashlib.sha256(raw).hexdigest()
def load(path): return json.loads(Path(path).read_bytes())
def op(plan, component): return next(row for row in plan['operations'] if row['component']==component)


def require_review(plan_path, receipt_path, expected_sha):
    raw=Path(receipt_path).read_bytes()
    if sha(raw)!=expected_sha: raise ValueError('REVIEW_RECEIPT_SHA_MISMATCH')
    receipt=json.loads(raw)
    if receipt.get('verdict')!='PASS' or receipt.get('deployment_plan_sha256')!=sha(Path(plan_path).read_bytes()):
        raise ValueError('SCOPED_REVIEW_PASS_NOT_BOUND_TO_PLAN')


def verify_release(plan,component):
    meta=plan['components'][component]; root=Path(meta['release_root']);p=root/'release-manifest.json'
    raw=p.read_bytes()
    if sha(raw)!=meta['sha256']:raise ValueError('RELEASE_MANIFEST_DRIFT:'+component)
    manifest=json.loads(raw)
    for file in manifest['app_files']:
        path=root/'app'/file['path']
        if path.is_symlink() or path.resolve()!=path or sha(path.read_bytes())!=file['sha256']:
            raise ValueError('RELEASE_SOURCE_DRIFT:'+component+'/'+file['path'])
    for link in manifest['symlinks']:
        if os.readlink(root/'app'/link['path'])!=link['target']:raise ValueError('RELEASE_LINK_DRIFT')


def stage(plan):
    for component,meta in plan['components'].items():
        root=Path(meta['release_root'])
        if root.exists():verify_release(plan,component);continue
        tmp=root.with_name('.'+root.name+'.staging-'+str(os.getpid()))
        tmp.mkdir()  # Never overwrite or delete an unknown directory.
        shutil.copytree(meta['candidate_app'],tmp/'app',symlinks=True,
                        ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        raw=Path(meta['path']).read_bytes()
        if sha(raw)!=meta['sha256']:raise ValueError('CANDIDATE_MANIFEST_DRIFT')
        (tmp/'release-manifest.json').write_bytes(raw)
        if component=='collector':
            config=Path(plan['config_path']).read_bytes()
            if sha(config)!=plan['config_sha256']:raise ValueError('CONFIG_DRIFT')
            (tmp/'runtime-graph-config.json').write_bytes(config)
        if root.exists():raise ValueError('RELEASE_APPEARED_DURING_STAGE')
        tmp.rename(root)
        verify_release(plan,component)


def run(args):
    return subprocess.run(['/bin/launchctl',*args],stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)


def label_state(label):
    result=run(['print',f'gui/{os.getuid()}/'+label])
    if result.returncode==113:return None
    if result.returncode!=0:raise ValueError('LAUNCHD_READ_UNCONFIRMED')
    match=re.search(rb'(?m)^\s*pid = (\d+)\s*$',result.stdout)
    return int(match.group(1)) if match else 0


def proposed_bytes(row,raw):
    if row.get('template_path'):
        raw=Path(row['template_path']).read_bytes()
        if sha(raw)!=row['template_sha256']:raise ValueError('PARENT_INTENT_TEMPLATE_DRIFT')
    value=plistlib.loads(raw)
    def replace(item):
        if isinstance(item,str):return row['new_prefix']+item[len(row['replace_prefix']):] if item.startswith(row['replace_prefix']) else item
        if isinstance(item,list):return [replace(i) for i in item]
        if isinstance(item,dict):return {k:replace(v) for k,v in item.items()}
        return item
    value=replace(value);value.setdefault('EnvironmentVariables',{}).update(row['env_set'])
    value.update(row['set'])
    for key in row['remove']:value.pop(key,None)
    new=plistlib.dumps(value,fmt=plistlib.FMT_XML,sort_keys=True)
    if sha(new)!=row['after_sha256']:raise ValueError('PROPOSED_PLIST_DRIFT')
    return new


def install_plist(row, *, rollback=False):
    if label_state(row['label']) is not None:
        raise ValueError('CONTROLLER_MUST_FIRST_QUIESCE_AND_UNLOAD_WITHOUT_KILL:'+row['label'])
    path=Path(row['plist'])
    if path.is_symlink() or path.resolve()!=path:raise ValueError('PLIST_PATH_UNSAFE')
    raw=path.read_bytes();expected=row['after_sha256'] if rollback else row['before_sha256']
    if sha(raw)==(row['before_sha256'] if rollback else row['after_sha256']):return 'ALREADY_APPLIED'
    if sha(raw)!=expected:raise ValueError('PLIST_CAS_MISMATCH')
    backups=path.parent/'.runtime-graph-repair-20261026-backups';backups.mkdir(mode=0o700,exist_ok=True)
    backup=backups/(row['label']+'.'+row['before_sha256']+'.plist')
    if rollback:
        new=backup.read_bytes()
        if sha(new)!=row['before_sha256']:raise ValueError('ROLLBACK_BACKUP_DRIFT')
    else:
        if not backup.exists():
            with backup.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
            backup.chmod(0o600)
        if sha(backup.read_bytes())!=row['before_sha256']:raise ValueError('BACKUP_DRIFT')
        new=proposed_bytes(row,raw)
    tmp=path.with_name('.'+path.name+'.graph-repair-'+str(os.getpid()))
    with tmp.open('xb') as stream:stream.write(new);stream.flush();os.fsync(stream.fileno())
    tmp.chmod(0o600)
    if sha(path.read_bytes())!=expected:raise ValueError('PLIST_CAS_CHANGED_BEFORE_REPLACE')
    os.replace(tmp,path)
    return 'ROLLED_BACK' if rollback else 'INSTALLED_UNLOADED'


def validate_api_observation(plan, observed, *, now=None):
    """No self-declared readiness: bind fresh response to current local state."""
    now=now or datetime.now(timezone.utc)
    api=op(plan,'api');main=op(plan,'main');proof=observed['proof']
    config=load(plan['config_path']);manifest=load(plan['components']['api']['path'])
    module=next(f for f in manifest['app_files'] if f['path']=='domains/runtime_graph_evidence.py')
    timestamp=datetime.fromisoformat(proof['observed_at'])
    if proof.get('schema_version')!='v4.runtime_graph_authority.v1' or proof.get('business_date')!=now.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d'):
        raise ValueError('API_PROOF_SCHEMA_OR_DATE_MISMATCH')
    if timestamp.tzinfo is None or not -5<=(now-timestamp).total_seconds()<=30:raise ValueError('API_OBSERVATION_EXPIRED')
    required={
        'api_plist_sha256':api['after_sha256'],
        'main_plist_sha256':main['after_sha256'],
        'api_manifest_sha256':plan['components']['api']['sha256'],
        'config_sha256':plan['config_sha256'],
    }
    if any(observed.get(k)!=v for k,v in required.items()):raise ValueError('CURRENT_DEPLOYMENT_DRIFT')
    runtime=proof['proof_runtime']
    if (type(observed.get('api_pid')) is not int or observed['api_pid']<=0
            or runtime.get('pid')!=observed['api_pid']
            or runtime.get('module_file')!=str(Path(plan['components']['api']['release_root'])/'app/domains/runtime_graph_evidence.py')
            or runtime.get('module_sha256')!=module['sha256']):raise ValueError('API_LOADED_IDENTITY_MISMATCH')
    main_runtime=proof['runtime_binding']
    if (main_runtime.get('status')!='VERIFIED' or main_runtime.get('current_runtime_verified') is not True
            or type(observed.get('main_pid')) is not int or observed['main_pid']<=0
            or main_runtime.get('pid')!=observed.get('main_pid') or not observed.get('main_pid')
            or main_runtime.get('launcher')!=str(Path(config['main']['app_root'])/'ops/launch_v35_macos_scheduler.sh')):
        raise ValueError('MAIN_ACTUAL_RUNTIME_UNCONFIRMED')
    if proof.get('authority_identity')!=config['main'] or proof.get('config_sha256')!=plan['config_sha256']:
        raise ValueError('API_AUTHORITY_BINDING_DRIFT')
    expected_readers={k:config[k] for k in ('graph_root','ledger_root','opening_root','stage_selection_root','stage_receipt_root','daily_receipt_root')}
    if 'native_reader_roots' in config:expected_readers['native_reader_roots']=config['native_reader_roots']
    if proof.get('reader_bindings')!=expected_readers:
        raise ValueError('API_READER_ROOT_DRIFT')
    if any(proof.get(k) is not False for k in ('production_allowed','buy_gate_updated','orders_sent')):
        raise ValueError('API_UNSAFE_FLAGS')
    return True


def observe_api(plan):
    http=Path(plan['components']['collector']['release_root'])/'app/infrastructure/runtime_graph/http_client.py'
    spec=importlib.util.spec_from_file_location('reviewed_graph_http',http);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    get=mod.make_http_get('http://127.0.0.1:8873')
    date=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d')
    proof=get('/api/v3/runtime-graph/authorities?date='+date+'&node_ids=hk_auction_0920,review_core_daily,research_panel_daily_a')
    api=op(plan,'api');main=op(plan,'main')
    return {'proof':proof,'api_pid':label_state(api['label']),'main_pid':label_state(main['label']),
            'api_plist_sha256':sha(Path(api['plist']).read_bytes()),'main_plist_sha256':sha(Path(main['plist']).read_bytes()),
            'api_manifest_sha256':sha((Path(plan['components']['api']['release_root'])/'release-manifest.json').read_bytes()),
            'config_sha256':sha(Path(plan['config_target']).read_bytes())}


def activate_graph(plan, observe=observe_api, command=run, state=label_state):
    graph=op(plan,'collector')
    if state(graph['label']) is not None:raise ValueError('GRAPH_MUST_REMAIN_UNLOADED_UNTIL_GATE')
    if sha(Path(graph['plist']).read_bytes())!=graph['after_sha256']:raise ValueError('GRAPH_PLIST_DRIFT')
    for component in plan['components']:verify_release(plan,component)
    first=observe(plan);validate_api_observation(plan,first)
    target=f'gui/{os.getuid()}/'+graph['label']
    result=command(['enable',target])
    if result.returncode:raise ValueError('GRAPH_ENABLE_FAILED')
    try:
        second=observe(plan);validate_api_observation(plan,second)
        if sha(Path(graph['plist']).read_bytes())!=graph['after_sha256']:raise ValueError('GRAPH_PLIST_DRIFT')
        result=command(['bootstrap',f'gui/{os.getuid()}',graph['plist']])
        if result.returncode:raise ValueError('GRAPH_BOOTSTRAP_FAILED')
    except Exception:
        command(['disable',target])
        raise
    # A launchctl success is not natural/API acceptance.
    return {'status':'GRAPH_BOOTSTRAPPED_PENDING_ACTUAL_READBACK','first_api':first,'second_api':second}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['stage','install-plist','rollback-plist','activate-graph'])
    parser.add_argument('--plan',type=Path,default=CASE/'delivery/DEPLOYMENT_PLAN.json')
    parser.add_argument('--review',type=Path,required=True);parser.add_argument('--review-sha',required=True)
    parser.add_argument('--label')
    args=parser.parse_args();require_review(args.plan,args.review,args.review_sha);plan=load(args.plan)
    if args.action=='stage':stage(plan);result={'status':'IMMUTABLE_STAGED_NOT_ACTIVATED'}
    elif args.action=='activate-graph':result=activate_graph(plan)
    else:
        row=next(r for r in plan['operations'] if r['label']==args.label)
        result={'status':install_plist(row,rollback=args.action=='rollback-plist'),'label':args.label}
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':raise SystemExit('HELPER_ONLY_USE_REVIEWED_CONTROLLER')
