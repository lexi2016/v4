from copy import deepcopy

import pytest

from ops import prepare_a925_mainclosure_release as release


def main_service():
    return dict(old_app_root='/old/main/app', app_root='/new/main/app', release_id='new-main',
        old_manifest_sha256='old-sha', manifest='/new/main/release-manifest.json',
        manifest_sha256='new-sha', live_plist='/main.plist', draft_plist_sha256='main-new',
        baseline_payload=dict(WorkingDirectory='/old/main/app',
            ProgramArguments=['/bin/bash', '/old/main/app/ops/launch_v4_macos_scheduler.sh'],
            EnvironmentVariables=dict(V4_APP_ROOT='/old/main/app', V4_RELEASE_ID='old-main',
                V4_RELEASE_MANIFEST_PATH='/old/main/release-manifest.json',
                V4_RELEASE_MANIFEST_SHA256='old-sha', SHARED_DEPENDENCY='/fixed/source',
                V4_RESEARCH_RETENTION_POLICY='/old/policy', V4_RESEARCH_RETENTION_POLICY_SHA256='old-policy-sha')))


def old_config():
    return dict(release_id='old-stage', safety={'orders_sent':False},
        research_owner_binding=dict(app_root='/old/main/app', release_id='old-main',
            manifest_path='/old/main/release-manifest.json', manifest_sha256='old-sha'),
        research_historical_owner_bindings=[dict(app_root=f'/history/{i}/app',release_id=f'history-{i}',
            manifest_sha256=f'history-sha-{i}')for i in range(6)],
        research_transition_owner_binding=dict(app_root='/transition/app',release_id='transition',
            manifest_sha256='transition-sha',trade_date='20261106'))


def test_owner_repin_preserves_six_history_transition_and_adds_exact_old_current():
    before=old_config(); original=deepcopy(before)
    result=release.stage_config_for_main(before,main_service(),'new-stage')
    assert before==original
    assert result['research_historical_owner_bindings'][:6]==before['research_historical_owner_bindings']
    assert result['research_historical_owner_bindings'][6]==before['research_owner_binding']
    assert result['research_transition_owner_binding']==before['research_transition_owner_binding']
    assert result['research_owner_binding']==dict(app_root='/new/main/app',release_id='new-main',
        manifest_path='/new/main/release-manifest.json',manifest_sha256='new-sha')
    assert result['safety']==before['safety']
    before['research_owner_binding']['manifest_sha256']='different'
    with pytest.raises(ValueError,match='EXACT_PREVIOUS_MAIN_AND_SIX_HISTORY_REQUIRED'):
        release.stage_config_for_main(before,main_service(),'new-stage')


def test_main_compat_release_migrates_only_identity_and_own_script_locator():
    main=main_service();before=deepcopy(main['baseline_payload'])
    result=release.expected_plist(main,'main')
    assert main['baseline_payload']==before
    assert result['ProgramArguments']==['/bin/bash','/new/main/app/ops/launch_v4_macos_scheduler.sh']
    assert result['WorkingDirectory']=='/new/main/app'
    assert result['EnvironmentVariables']==dict(before['EnvironmentVariables'],V4_APP_ROOT='/new/main/app',
        V4_RELEASE_ID='new-main',V4_RELEASE_MANIFEST_PATH='/new/main/release-manifest.json',V4_RELEASE_MANIFEST_SHA256='new-sha')


def test_new_main_root_and_source_pins_migrate_without_policy_cycle(tmp_path):
    main=main_service();old=tmp_path/'old-main';new=tmp_path/'new-main';old.mkdir();new.mkdir()
    (old/'reader.py').write_text('same');(new/'reader.py').write_text('same')
    main.update(old_app_root=str(old),app_root=str(new))
    services=dict(main=main,api=dict(live_plist='/api.plist',draft_plist_sha256='api-new',
        old_app_root='/old/api',app_root='/new/api'),stage=dict(live_plist='/stage.plist',
        draft_plist_sha256='stage-new',old_app_root='/old/stage',app_root='/new/stage'))
    pins=dict(expected_main_app_root=str(old),pins=[dict(path='/preserved/history')],source_bindings=[
        dict(path=str(old/'reader.py'),sha256=release.sha(old/'reader.py')),
        dict(path='/stage.plist',sha256='stage-old')])
    result=release.migrated_pins(pins,services)
    assert result['expected_main_app_root']==str(new)
    assert result['source_bindings']==[dict(path=str(new/'reader.py'),sha256=release.sha(new/'reader.py')),
        dict(path='/stage.plist',sha256='stage-new')]
    assert result['pins']==pins['pins']
    pins['source_bindings'].append(dict(path='/main.plist',sha256='cycle'))
    with pytest.raises(ValueError,match='MAIN_PLIST_REVERSE_PIN_CYCLE'):
        release.migrated_pins(pins,services)
