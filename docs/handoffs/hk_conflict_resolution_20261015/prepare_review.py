"""Prepare staged bindings and rerunnable frozen candidate evidence; no activation."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import plistlib
import subprocess
import sys
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[3];H=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from ops.prepare_api_only_cutover import rewrite_api_only_plist,extract_environment
from ops import api_release_integration as integration
PUB=json.loads((H/'PUBLICATION_RECEIPT.json').read_text())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(name,body):(H/name).write_text(json.dumps(body,sort_keys=True,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

bindings={}
for role,expected in [('api','930eda41c57b43833de7da5e3e13da1658018cb9bf75248aad0a4ccace162057'),
        ('scheduler','2a55f25686b041c2cde833a1eda73d91c96c22d45862603948cb09d0d2ba8fa6')]:
    path=Path('/Users/lexi/Library/LaunchAgents')/('com.lexi.v35.api-only.plist' if role=='api' else 'com.lexi.v35.scheduler.plist')
    raw=path.read_bytes();assert hashlib.sha256(raw).hexdigest()==expected
    before=plistlib.loads(raw)
    if role=='api':
        staged=rewrite_api_only_plist(before,candidate_app_root=Path(PUB[role]['app_root']),
            release_id=Path(PUB[role]['candidate_root']).name,manifest_path=Path(PUB[role]['candidate_root'])/'release-manifest.json',
            manifest_sha256=PUB[role]['manifest_sha256'],candidate_manager_state_root=None)
        changed=sorted(k for k in extract_environment(before)|extract_environment(staged) if extract_environment(before).get(k)!=extract_environment(staged).get(k))
        assert changed==sorted(['V35_APP_ROOT','V35_RELEASE_ID','PYTHONPATH','V35_RELEASE_MANIFEST_PATH','V35_RELEASE_MANIFEST_SHA256'])
    else:
        staged=plistlib.loads(raw);env=staged['EnvironmentVariables'];old=env['V35_APP_ROOT'];new=PUB['scheduler']['app_root']
        staged['ProgramArguments']=[part.replace(old,new) for part in staged['ProgramArguments']]
        staged['WorkingDirectory']=new
        env.update(V35_APP_ROOT=new,V35_RELEASE_ID=Path(PUB[role]['candidate_root']).name,
            PYTHONPATH=env['PYTHONPATH'].replace(old,new),V35_RELEASE_MANIFEST_PATH=str(Path(PUB[role]['candidate_root'])/'release-manifest.json'),
            V35_RELEASE_MANIFEST_SHA256=PUB[role]['manifest_sha256'],V35_SHARED_PACKAGE_ROOT=PUB['shared']['app_root'],
            V4_MANAGER_MATERIALIZER_APP_ROOT=PUB['materializer']['app_root'],
            V4_MANAGER_MATERIALIZER_SHA256=sha(Path(PUB['materializer']['app_root'])/'ops/materialize_manager_close_discovery.py'),
            V35_REVIEW_CORE_PACKAGE_ROOT=PUB['reviewcore']['app_root'])
        changed=sorted(k for k in before['EnvironmentVariables']|env if before['EnvironmentVariables'].get(k)!=env.get(k))
        assert len(changed)==9,changed
        assert env['V35_REVIEW_CORE_SHARED_PACKAGE_ROOT']==before['EnvironmentVariables']['V35_REVIEW_CORE_SHARED_PACKAGE_ROOT']
    (H/f'{role}.plist.before').write_bytes(raw)
    (H/f'{role}.plist.staged').write_bytes(plistlib.dumps(staged,sort_keys=False))
    bindings[role]=dict(active_plist_path=str(path),before_sha256=expected,staged_sha256=sha(H/f'{role}.plist.staged'),
        changed_environment_keys=changed,all_other_environment_values_preserved=True,manager_roots_and_A_data_roots_preserved=True)

env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
    PYTHONPATH=PUB['api']['app_root']+'/upstreams:'+PUB['api']['app_root'],
    V4_HK_TEST_SCHEDULER_APP=PUB['scheduler']['app_root'],V4_HK_TEST_MATERIALIZER_APP=PUB['materializer']['app_root'],
    V4_HK_TEST_REVIEWCORE_APP=PUB['reviewcore']['app_root'],V4_HK_TEST_SHARED_APP=PUB['shared']['app_root'])
env.pop('V4_HK_HISTORY_RESOLUTION_POINTER',None)
code='import v4.hk_research_history, v4.manager_workbench.api, upstreams.v3_shared_data.shared_data.hk_history_resolution; import pytest; raise SystemExit(pytest.main('+repr(['-q','-p','no:cacheprovider','--basetemp=/tmp/hk-resolution-review-r1-fix-candidate','-k','scheduler',str(ROOT/'tests/test_hk_history_resolution_consumers.py')])+'))'
python='/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python'
command=[python,'-c',code]
tested=subprocess.run(command,env=env,cwd='/tmp',text=True,capture_output=True)
write('TARGETED_TEST_RECEIPT.json',dict(command=command,cwd='/tmp',environment={k:env[k] for k in ['PYTHONDONTWRITEBYTECODE','PYTEST_DISABLE_PLUGIN_AUTOLOAD','PYTHONPATH','V4_HK_TEST_SCHEDULER_APP','V4_HK_TEST_MATERIALIZER_APP','V4_HK_TEST_REVIEWCORE_APP','V4_HK_TEST_SHARED_APP']},exit_code=tested.returncode,stdout=tested.stdout,stderr=tested.stderr))
assert tested.returncode==0,(tested.stdout,tested.stderr)
identities=[]
for role in ['api','shared','scheduler','materializer','reviewcore']:
    data=PUB[role];app=Path(data['app_root']);manifest=Path(data['candidate_root'])/'release-manifest.json'
    assert sha(manifest)==data['manifest_sha256']
    source=json.loads(manifest.read_text());entries=source['application_inventory']['entries']
    assert integration.inventory_tree(app)==entries
    for entry in entries:
        if entry['path'].endswith('.py') and entry.get('kind')=='file':
            compile((app/entry['path']).read_bytes(),str(app/entry['path']),'exec')
    identities.append(dict(role=role,app_root=str(app),manifest_sha256=sha(manifest),inventory_sha256=integration.inventory_digest(entries)))
write('PREACTIVATION_BINDINGS.json',dict(observed_at=datetime.now(timezone.utc).isoformat(),bindings=bindings,candidates=identities,
    api_unreachable_old_HK_review_bridge=dict(status='NOT_REACHABLE',bridge_spec=None,_HAS_HK_REVIEW_CORE=False,
        API_REVIEW_CORE_bindings_preserved=True,scheduler_reviewcore_candidate_not_substituted_into_API=True),
    active_pointer_installed=False,service_commands_executed=[]))
print(json.dumps(dict(status='REVIEW_READY',tests=tested.stdout.strip(),bindings=bindings),sort_keys=True))
