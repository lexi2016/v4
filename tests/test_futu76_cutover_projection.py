"""Read-only tests of the Root cutover's manifest/plist projection only."""
import importlib.util
import plistlib
from pathlib import Path

import pytest

B=Path('/Users/lexi/Desktop/学习/因子工厂/research/futu_qfq76_mac_integration_20261026_r1')


def module():
    s=importlib.util.spec_from_file_location('root_cutover_projection',B/'root_cutover.py')
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def test_projection_changes_only_candidate_root_and_app_root():
    m=module();before,after=m.project_manifest()
    import json
    a,b=json.loads(before),json.loads(after)
    a['candidate']['root']=str(m.TARGET);a['candidate']['app_root']=str(m.TARGET/'app')
    assert a==b


def test_plist_preserves_all_unrelated_reviewcore_values():
    m=module();before=plistlib.loads(m.P.read_bytes())
    before.setdefault('EnvironmentVariables',{})['UNRELATED_TEST_MARKER']='preserve exact bytes'
    raw=plistlib.dumps(before,sort_keys=False);new=plistlib.loads(m.candidate_plist(raw,'f'*64))
    assert new['EnvironmentVariables']['UNRELATED_TEST_MARKER']=='preserve exact bytes'
    for key,value in before['EnvironmentVariables'].items():
        if key not in {'V35_APP_ROOT','V35_RELEASE_ID','V35_RELEASE_MANIFEST_PATH','V35_RELEASE_MANIFEST_SHA256','PYTHONPATH'}:
            assert new['EnvironmentVariables'][key]==value
    assert new['WorkingDirectory']==str(m.TARGET/'app')


def test_plist_rejects_unexpected_current_working_directory():
    m=module();before=plistlib.loads(m.P.read_bytes());before['WorkingDirectory']='/wrong/app'
    with pytest.raises(AssertionError):m.candidate_plist(plistlib.dumps(before),'f'*64)
