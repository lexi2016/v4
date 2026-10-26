"""One real copy/verify reproduction; no release, launchd, or business writes."""
from pathlib import Path
import importlib.util
import hashlib
import json

import pytest

CASE=Path(__file__).resolve().parent.parent


def module(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def test_manifest_pytest_cache_is_copied_and_verifiable(tmp_path):
    old=module(CASE/'writer/operator.py','original_frozen_operator')
    fixed=module(Path(__file__).with_name('operator.py'),'cache_copy_operator')
    source=tmp_path/'candidate/app';(source/'.pytest_cache').mkdir(parents=True)
    (source/'.pytest_cache/.gitignore').write_bytes(b'# Manifest-bound fixture cache\n*\n')
    (source/'entry.py').write_bytes(b'# Source fixture; never executed\n')
    manifest={'app_files':[{'path':str(p.relative_to(source)),
                           'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
                           'bytes':p.stat().st_size}
                          for p in sorted(source.rglob('*')) if p.is_file()], 'symlinks':[]}
    manifest_path=tmp_path/'release-manifest.json';manifest_path.write_text(json.dumps(manifest))
    metadata={'candidate_app':str(source),'path':str(manifest_path),
              'sha256':hashlib.sha256(manifest_path.read_bytes()).hexdigest()}
    failed_root=tmp_path/'original_failed_release'
    original_plan={'components':{'stage':{**metadata,'release_root':str(failed_root)}}}
    with pytest.raises(FileNotFoundError,match=r'\.pytest_cache/.gitignore'):
        old.stage(original_plan)
    assert failed_root.exists() and not (failed_root/'app/.pytest_cache/.gitignore').exists()
    target=tmp_path/'new_release'
    corrected_plan={'components':{'stage':{**metadata,'release_root':str(target)}}}
    fixed.stage(corrected_plan)
    fixed.verify_release(corrected_plan,'stage')
    assert (target/'app/.pytest_cache/.gitignore').read_bytes()==(source/'.pytest_cache/.gitignore').read_bytes()
    assert (target/'release-manifest.json').read_bytes()==manifest_path.read_bytes()
    assert failed_root.exists()  # Original failed copy remains as evidence.
