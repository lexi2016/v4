"""Only combination tooling; does not rerun the 14 accepted API tests."""
from pathlib import Path
import hashlib
import importlib.util
import json
import shutil
import subprocess
import pytest
P=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('combo_runner',P/'tools/run_tests.py')
# During development the old-runner failure is recorded separately as a real CLI run.
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def test_new_profile_preserves_full_new_workspace_and_autorun(tmp_path):
    profile=module.load_profile(P)
    expected=profile['after_sha256']
    shutil.copytree(P/'reference_only/r3b_input',tmp_path/'app')
    subprocess.run(['git','apply',str(P/'evidence/integration_actual_diff.patch')],cwd=tmp_path/'app',check=True)
    for filename in ['workspace.py','workspace_plan_autorun.py']:
        raw=(tmp_path/'app/v4/manager_research'/filename).read_bytes()
        assert expected['v4/manager_research/'+filename]==hashlib.sha256(raw).hexdigest()
    assert expected['v4/manager_research/workspace.py'].startswith('35c9292d')
    assert expected['v4/manager_research/workspace_plan_autorun.py'].startswith('e785ae1d')

@pytest.mark.parametrize('filename,wrong',[('workspace.py',b'old-r3b'),('workspace_plan_autorun.py',b'old-autorun')])
def test_known_old_or_unrecognized_bytes_still_rejected(tmp_path,filename,wrong):
    key='v4/manager_research/'+filename
    exact=module.load_profile(P)['after_sha256'][key]
    path=tmp_path/key;path.parent.mkdir(parents=True);path.write_bytes(wrong)
    with pytest.raises(ValueError,match='SOURCE_DRIFT:'+key):module.check_sources(tmp_path,{key:exact})

@pytest.mark.parametrize('surface',['cycle','all'])
def test_b2_cannot_silently_use_snapshot(surface):
    with pytest.raises(ValueError,match='B2_FINAL_CYCLE_BINDING_REQUIRED'):
        module.selected_tests(P,surface)

def test_original_business_and_b2_assertions_are_byte_identical():
    profile=module.load_profile(P)
    for rel,pin in profile['test_sha256'].items():
        assert hashlib.sha256((P/'original_business'/rel).read_bytes()).hexdigest()==pin
    names=[p.name for p in module.selected_tests(P,'business')]
    assert names==['test_b1_history.py','test_us_business.py']

def test_matching_source_accepted_and_symlink_rejected(tmp_path):
    payload=b'fixture'; path=tmp_path/'source.py';path.write_bytes(payload)
    pin=hashlib.sha256(payload).hexdigest()
    assert module.check_sources(tmp_path,{'source.py':pin})=={'source.py':pin}
    (tmp_path/'alias.py').symlink_to(path)
    with pytest.raises(ValueError,match='SOURCE_DRIFT:alias.py'):
        module.check_sources(tmp_path,{'alias.py':pin})
