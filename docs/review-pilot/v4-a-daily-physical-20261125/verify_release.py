"""Read back installed A-daily policy scope and its paired Stage launch binding."""
import hashlib
import json
from pathlib import Path
import plistlib
import subprocess
import sys
from urllib.request import urlopen

from ops import switch_reviewed_v4_release as release


def endpoint(path):
    with urlopen('http://127.0.0.1:8873' + path, timeout=12) as result:
        assert result.status == 200
        return json.load(result)


def main(plan_path):
    plan = json.loads(plan_path.read_bytes())
    draft = json.loads(plan_path.with_name('RELEASE_DRAFT.json').read_bytes())
    assert {k: v for k, v in plan.items() if k != 'review_approval'} == draft['plan']
    helpers = release.load_audited_switch(plan['audited_switch'])
    observed = {}
    environments = {}
    for row in plan['roles']:
        role = row['role']
        live = release.LAUNCH_AGENTS / (release.LABELS[role] + '.plist')
        cfg = plistlib.loads(release.checked(live, row['candidate_plist_sha256']))
        old = plistlib.loads(release.checked(row['rollback_plist'], row['current_plist_sha256']))
        app, manifest, _ = release.startup(cfg, row['candidate_manifest_sha256'], candidate=True)
        env = cfg['EnvironmentVariables']
        observed[role] = helpers['verify_loaded'](role, str(app), live, row['candidate_manifest_sha256'])
        environments[role] = env
        assert all(cfg[key] == old[key] for key in cfg.keys() - release.RELOCATION_KEYS)
        assert cfg.keys() == old.keys()
        if role == 'main':
            assert env['V4_RESEARCH_PANEL_A_SYNC_SCRIPT'] == str(app / release.A_SYNC_ENTRY)
            policy_change = {release.POLICY_PATH, release.POLICY_SHA, release.A_SYNC_SCRIPT,
                             'V4_APP_ROOT','V4_RELEASE_ID','V4_RELEASE_MANIFEST_PATH','V4_RELEASE_MANIFEST_SHA256'}
            assert ({k:v for k,v in env.items() if k not in policy_change}
                    == {k:v for k,v in old['EnvironmentVariables'].items() if k not in policy_change})
            runtime = Path(env['V4_RUNTIME_ROOT']) / 'venvs/v4-mac'
            cache = '/dev/null/v4-main-r4-source-only-pycache'
            check_env = {**env, 'HOME': str(Path.home()), 'PYTHONPATH':
                         f"{app}:{runtime}/lib/python3.14/site-packages:{env.get('PYTHONPATH', '')}"}
            check = """
import os
from ops.research_a_daily_physical import physical_mode, require_configured_space, scheduled_storage
from ops.research_storage_governance import configured_policy
from infrastructure.scheduling.executor_registry_review import _resolve_hk_child_binding
old = configured_policy()
assert old is not None
assert not physical_mode()
require_configured_space()
with scheduled_storage():
    assert physical_mode() and configured_policy() is None
    require_configured_space()
assert configured_policy() == old and not physical_mode()
assert _resolve_hk_child_binding(os.environ)
"""
            subprocess.run([str(runtime/'bin/python'),'-B','-S','-X',f'pycache_prefix={cache}','-c',check],
                           env=check_env,cwd=app,check=True,timeout=25)
        else:
            main_env = environments['main']
            config = json.loads(Path(env['STAGE_CENTER_CONFIG']).read_bytes())
            assert config['research_owner_binding'] == {
                k: main_env[key] for k,key in {'app_root':'V4_APP_ROOT','release_id':'V4_RELEASE_ID',
                    'manifest_path':'V4_RELEASE_MANIFEST_PATH','manifest_sha256':'V4_RELEASE_MANIFEST_SHA256'}.items()}
            old_config = json.loads(Path(old['EnvironmentVariables']['STAGE_CENTER_CONFIG']).read_bytes())
            assert config['research_historical_owner_bindings'] == [
                *old_config['research_historical_owner_bindings'],old_config['research_owner_binding']]
            assert config == {**old_config,
                **{k:config[k] for k in ('research_historical_owner_bindings','research_owner_binding','release_id')}}
    ready = Path(plan['audited_switch']['path']).with_name('check_scheduler_ready.py')
    assert hashlib.sha256(ready.read_bytes()).hexdigest() == '167d57d4adb51c9814a20a593144c6e994d8f5b37050817bf73928b07876cef6'
    subprocess.run([sys.executable,'-B',str(ready),str(plan_path),
                    str(plan_path.with_name('MAIN_DAEMON_READY.json'))],check=True,timeout=35)
    identity = draft['carried_api_identity']
    api = helpers['verify_loaded']('api',identity['app_root'],Path(identity['plist_path']),
                                   identity['startup_manifest']['sha256'])
    assert api['pid'] == plan['carried_api_pid'] and endpoint('/healthz')['status'] == 'ok'
    day = endpoint('/api/v4/research/workbench/days/2026-11-24')
    assert day['source_date'] == '2026-11-24' and len(day['rows']) == 110
    assert day['generation'] == '660df6bf22e9069e56d6017911f61ed685ab3e1cb1cc78773ff37b10a71e0247'
    for key in ('production_allowed','buy_gate_updated','orders_sent'):
        assert day[key] is False
    print(json.dumps({"status":"LOADED_CONFIGURATION_VERIFIED","roles":observed,"api_pid":api['pid'],
                      "d24_rows":len(day['rows']),"providers_called":0},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main(Path(sys.argv[1]))
