"""Read-only, current-process proof required before 300-second graph activation.

Overall runtime_identity and graph business status may remain CANNOT_CONFIRM or
FAIL. Only the deployment and graph-reader bindings below are acceptance gates.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import subprocess
import urllib.request

CASE=Path(__file__).resolve().parent
API_LABEL='com.lexi.v35.api-only'
API_PLIST=Path.home()/'Library/LaunchAgents'/f'{API_LABEL}.plist'
RELEASE_ROOT=Path.home()/'Library/Application Support/com.lexi.v4.local/releases'
STATUS_URL='http://127.0.0.1:8873/api/v3/runtime-graph/status'
SCHEMA='v4.schedule_remediation.api_ready.v2'
MAX_AGE_SECONDS=120
MAX_FUTURE_SECONDS=5
MAX_HTTP_BYTES=1024*1024
MODULES={'apps.api.v35_api.runtime_graph_router':'apps/api/v35_api/runtime_graph_router.py',
         'infrastructure.runtime_graph.service':'infrastructure/runtime_graph/service.py'}
CONTRACT='contracts/v3_runtime_graph_contract.json'


def digest(raw):return hashlib.sha256(raw).hexdigest()


def regular_bytes(path):
    path=Path(path)
    if not path.is_absolute() or path.resolve()!=path or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('API_GATE_PATH_UNSAFE')
    raw=path.read_bytes()
    if len(raw)>16*1024*1024:raise ValueError('API_GATE_METADATA_TOO_LARGE')
    return raw


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def status_read():
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    with opener.open(STATUS_URL,timeout=3) as response:
        if response.geturl()!=STATUS_URL:raise ValueError('API_GATE_REDIRECT')
        raw=response.read(MAX_HTTP_BYTES+1)
    if len(raw)>MAX_HTTP_BYTES:raise ValueError('API_GATE_RESPONSE_TOO_LARGE')
    value=json.loads(raw)
    if not isinstance(value,dict):raise ValueError('API_GATE_RESPONSE_INVALID')
    return value


def launch_pid(run):
    target=f'gui/{os.getuid()}/{API_LABEL}'
    result=run(['/bin/launchctl','print',target],capture_output=True,text=True,timeout=10)
    if result.returncode:raise ValueError('API_GATE_SERVICE_UNAVAILABLE')
    found=re.search(r'^\s*pid = (\d+)\s*$',result.stdout,re.MULTILINE)
    if found is None or int(found.group(1))<=0:raise ValueError('API_GATE_PID_MISSING')
    return int(found.group(1)),result.stdout


def effective_environment(plist):
    environment=dict(plist.get('EnvironmentVariables',{}))
    arguments=plist.get('ProgramArguments',[])
    if arguments[:1]==['/usr/bin/env']:
        for value in arguments[1:]:
            if not isinstance(value,str) or not re.match(r'^[A-Za-z_][A-Za-z_0-9]*=',value):break
            key,text=value.split('=',1);environment[key]=text
    return environment


def loaded_binding_values(text,key):
    values=[]
    for line in text.splitlines():
        line=line.strip().strip('"')
        match=re.match(re.escape(key)+r'(?:\s*=>\s*|=)(.*)$',line)
        if match:values.append(match.group(1).strip().strip('"'))
    return values


def expected_core(plan):
    release=next((r for r in plan['releases'] if r['component']=='api'),None)
    if release is None:raise ValueError('API_GATE_EXPECTATION_MISSING')
    raw=regular_bytes(release['manifest'])
    if digest(raw)!=release['manifest_sha256']:raise ValueError('API_GATE_EXPECTATION_DRIFT')
    files={r['path']:r.get('sha256') for r in json.loads(raw)['app_files']}
    needed={name:files.get(relative) for name,relative in {**MODULES,'contract':CONTRACT}.items()}
    if any(not isinstance(value,str) or re.fullmatch('[0-9a-f]{64}',value) is None for value in needed.values()):
        raise ValueError('API_GATE_CORE_HASH_MISSING')
    reviewed=json.loads(regular_bytes(CASE/'SOURCE_DIFF_MANIFEST.json'))
    approved={r['relative_path']:r['after_sha256'] for r in reviewed['changed_files'] if r['component']=='api'}
    if any(needed[name]!=approved.get(relative) for name,relative in {**MODULES,'contract':CONTRACT}.items()):
        raise ValueError('API_GATE_COMPOSITION_CORE_HASH_DRIFT')
    return needed


def observe_current(plan,*,run=subprocess.run,http_read=status_read):
    core=expected_core(plan)
    plist_raw=regular_bytes(API_PLIST);plist=plistlib.loads(plist_raw)
    if plist.get('Label')!=API_LABEL:raise ValueError('API_GATE_SERVICE_LABEL_DRIFT')
    environment=effective_environment(plist)
    app=Path(environment.get('V35_APP_ROOT',''))
    if not app.is_absolute() or app.resolve()!=app or app.name!='app' or not app.is_relative_to(RELEASE_ROOT):
        raise ValueError('API_GATE_RELEASE_ROOT_INVALID')
    manifest_path=app.parent/'release-manifest.json'
    if environment.get('V35_RELEASE_MANIFEST_PATH')!=str(manifest_path):raise ValueError('API_GATE_MANIFEST_PATH_DRIFT')
    manifest_raw=regular_bytes(manifest_path);manifest=json.loads(manifest_raw)
    manifest_sha=digest(manifest_raw)
    release_id=app.parent.name
    expected_release=next(row for row in plan['releases'] if row['component']=='api')
    expected_plist=next((row for row in plan['operations'] if row['role']=='api'),None)
    if app!=Path(expected_release['destination'])/'app' or manifest_sha!=expected_release['manifest_sha256'] or expected_plist is None or digest(plist_raw)!=expected_plist['proposed_sha256']:
        raise ValueError('API_GATE_FINAL_DEPLOYMENT_CONTRACT_DRIFT')
    if environment.get('V35_RELEASE_ID')!=release_id or manifest.get('release_id')!=release_id or environment.get('V35_RELEASE_MANIFEST_SHA256')!=manifest_sha:
        raise ValueError('API_GATE_RELEASE_DECLARATION_DRIFT')
    root=plan['graph_data_root']
    if environment.get('V35_RUNTIME_GRAPH_DATA_ROOT')!=root:raise ValueError('API_GATE_GRAPH_ROOT_DRIFT')
    contract_raw=regular_bytes(app/CONTRACT)
    if digest(contract_raw)!=core['contract'] or json.loads(contract_raw).get('freshness_seconds',{}).get('runtime_snapshot')!=360:
        raise ValueError('API_GATE_CONTRACT_DRIFT')
    manifest_files={row['path']:row.get('sha256') for row in manifest.get('app_files',[])}
    for name,relative in {**MODULES,'contract':CONTRACT}.items():
        if manifest_files.get(relative)!=core[name] or digest(regular_bytes(app/relative))!=core[name]:
            raise ValueError('API_GATE_REVIEWED_MODULE_DRIFT:'+name)
    pid,loaded=launch_pid(run)
    for key,wanted in {'V35_APP_ROOT':str(app),'V35_RELEASE_ID':release_id,
                       'V35_RELEASE_MANIFEST_PATH':str(manifest_path),'V35_RELEASE_MANIFEST_SHA256':manifest_sha,
                       'V35_RUNTIME_GRAPH_DATA_ROOT':root}.items():
        values=loaded_binding_values(loaded,key)
        if not values or any(value!=wanted for value in values):raise ValueError('API_GATE_LOADED_BINDING_DRIFT:'+key)
    listener=run(['/usr/sbin/lsof','-nP','-iTCP:8873','-sTCP:LISTEN','-Fp'],capture_output=True,text=True,timeout=10)
    listeners={int(value) for value in re.findall(r'^p(\d+)\s*$',listener.stdout,re.MULTILINE)}
    if listener.returncode or listeners!={pid}:raise ValueError('API_GATE_LISTENER_PID_DRIFT')
    body=http_read();identity=body.get('runtime_identity')
    if not isinstance(identity,dict):raise ValueError('API_GATE_RUNTIME_IDENTITY_MISSING')
    for key,wanted in {'pid':pid,'app_root':str(app),'declared_app_root':str(app),
                       'release_id':release_id,'release_manifest_path':str(manifest_path),
                       'release_manifest_sha256':manifest_sha,'plist_path':str(API_PLIST),
                       'plist_sha256':digest(plist_raw)}.items():
        if identity.get(key)!=wanted:raise ValueError('API_GATE_READBACK_DRIFT:'+key)
    records=identity.get('selected_imported_modules',[])
    if not isinstance(records,list):raise ValueError('API_GATE_LOADED_MODULES_MISSING')
    loaded_modules={}
    for name,relative in MODULES.items():
        records_for_name=[row for row in records if isinstance(row,dict) and row.get('module')==name]
        if len(records_for_name)!=1:raise ValueError('API_GATE_LOADED_MODULE_MISSING:'+name)
        row=records_for_name[0];path=str(app/relative)
        if row.get('path')!=path or row.get('sha256')!=core[name]:raise ValueError('API_GATE_LOADED_MODULE_DRIFT:'+name)
        loaded_modules[name]={'path':path,'sha256':core[name]}
    # Detect replacement during the read-only observation itself.
    if launch_pid(run)[0]!=pid or digest(regular_bytes(API_PLIST))!=digest(plist_raw) or digest(regular_bytes(manifest_path))!=manifest_sha:
        raise ValueError('API_GATE_CHANGED_DURING_OBSERVATION')
    return {'api_service_label':API_LABEL,'api_service_target':f'gui/{os.getuid()}/{API_LABEL}',
            'api_pid':pid,'api_plist_path':str(API_PLIST),'api_plist_sha256':digest(plist_raw),
            'api_app_root':str(app),'api_release_id':release_id,'api_release_manifest_path':str(manifest_path),
            'api_release_manifest_sha256':manifest_sha,'runtime_graph_data_root':root,
            'runtime_snapshot_freshness_seconds':360,'runtime_graph_contract_sha256':core['contract'],
            'loaded_modules':loaded_modules,'readback_url':STATUS_URL,
            'runtime_identity_status':identity.get('status'),'business_status':body.get('status')}


def verify_api_ready(receipt,plan,*,run=subprocess.run,http_read=status_read,now=None):
    if not isinstance(receipt,dict) or receipt.get('schema_version')!=SCHEMA or receipt.get('status')!='API_VERIFIED':
        raise ValueError('API_GATE_RECEIPT_SCHEMA_INVALID')
    if receipt.get('binding_plan_sha256')!=digest((CASE/'integration/BINDING_PLAN.json').read_bytes()):
        raise ValueError('API_GATE_RECEIPT_PLAN_DRIFT')
    try:
        observed=datetime.fromisoformat(receipt['observed_at'])
        if observed.tzinfo is None:raise ValueError('timezone required')
        clock=now or datetime.now(timezone.utc)
        age=(clock-observed).total_seconds()
    except (KeyError,TypeError,ValueError):raise ValueError('API_GATE_RECEIPT_TIME_INVALID') from None
    if not -MAX_FUTURE_SECONDS<=age<=MAX_AGE_SECONDS:raise ValueError('API_GATE_RECEIPT_STALE_OR_FUTURE')
    required=['api_service_label','api_service_target','api_pid','api_plist_path','api_plist_sha256','api_app_root',
              'api_release_id','api_release_manifest_path','api_release_manifest_sha256','runtime_graph_data_root',
              'runtime_snapshot_freshness_seconds','runtime_graph_contract_sha256','loaded_modules','readback_url']
    if any(name not in receipt for name in required):raise ValueError('API_GATE_RECEIPT_BINDING_MISSING')
    current=observe_current(plan,run=run,http_read=http_read)
    for name in required:
        if receipt[name]!=current[name]:raise ValueError('API_GATE_RECEIPT_CURRENT_DRIFT:'+name)
    finished=now or datetime.now(timezone.utc)
    if not -MAX_FUTURE_SECONDS<=(finished-observed).total_seconds()<=MAX_AGE_SECONDS:
        raise ValueError('API_GATE_RECEIPT_EXPIRED_DURING_OBSERVATION')
    return {'checked_at':finished.isoformat(),'observed_at':receipt['observed_at'],
            'api_pid':current['api_pid'],'api_plist_sha256':current['api_plist_sha256'],
            'api_release_manifest_sha256':current['api_release_manifest_sha256'],
            'runtime_identity_status':current['runtime_identity_status'],'business_status':current['business_status']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binding-plan',type=Path,default=CASE/'integration/BINDING_PLAN.json')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.binding_plan.resolve()!=(CASE/'integration/BINDING_PLAN.json').resolve():raise ValueError('CURRENT_REVIEWED_PLAN_REQUIRED')
    output=args.output.absolute()
    if not output.parent.resolve().is_relative_to(CASE.parent.resolve()):raise ValueError('RECEIPT_OUTPUT_OUTSIDE_CASE')
    plan=json.loads(args.binding_plan.read_text())
    observed=observe_current(plan)
    receipt={'schema_version':SCHEMA,'status':'API_VERIFIED','observed_at':datetime.now(timezone.utc).isoformat(),
             'binding_plan_sha256':digest(args.binding_plan.read_bytes()),**observed}
    with output.open('x') as handle:json.dump(receipt,handle,ensure_ascii=False,indent=2);handle.write('\n')
    print(json.dumps({'receipt':str(output),'api_pid':receipt['api_pid'],'service_actions':0}))


if __name__=='__main__':main()
