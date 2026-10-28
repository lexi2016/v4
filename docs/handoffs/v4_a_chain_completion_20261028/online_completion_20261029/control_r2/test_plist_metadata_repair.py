"""Private forward/inverse CAS using actual frozen provenance, never active files."""
from pathlib import Path
import base64
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
import plistlib

import pytest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('metadata_repair_operator',HERE/'publication_operator.py')
operator=importlib.util.module_from_spec(spec);spec.loader.exec_module(operator)


def apply_private(path,expected):
    fd=os.open(path,os.O_RDWR|os.O_NOFOLLOW)
    try:operator.metadata.apply_fd(fd,expected)
    finally:os.close(fd)


def test_private_forward_inverse_preserves_actual_provenance_and_marker(tmp_path,monkeypatch):
    actual=json.loads((HERE/'ACTUAL_METADATA_FEASIBILITY.json').read_text())
    assert actual['status']=='EXACT_ACTUAL_METADATA_COPY_PASS'
    expected=deepcopy(actual['rows'][0]['expected_metadata'])
    provenance=expected['xattrs']['com.apple.provenance']
    assert provenance['bytes']==11
    marker=b'synthetic owned forward/inverse metadata regression'
    expected['xattrs']['user.review_marker']=dict(base64=base64.b64encode(marker).decode(),sha256=hashlib.sha256(marker).hexdigest(),bytes=len(marker))
    before=plistlib.dumps(dict(Label='synthetic.metadata.only',WorkingDirectory='/synthetic/base/app',RunAtLoad=False,EnvironmentVariables={}),sort_keys=True)
    after=plistlib.dumps(dict(Label='synthetic.metadata.only',WorkingDirectory='/synthetic/new/app',RunAtLoad=False,EnvironmentVariables={}),sort_keys=True)
    target=tmp_path/'synthetic.metadata.only.plist';target.write_bytes(before)
    template=tmp_path/'after.template';template.write_bytes(after)
    apply_private(target,expected)
    original_inode=target.stat().st_ino
    row=dict(label='synthetic.metadata.only',plist=str(target),before_sha256=operator.sha(before),after_sha256=operator.sha(after),template_path=str(template),template_sha256=operator.sha(after),replace_prefix='/synthetic/base/app',new_prefix='/synthetic/new/app',env_set={},set={},remove=[],plist_metadata=expected,plist_metadata_sha256=operator.metadata.digest(expected))
    monkeypatch.setattr(operator,'label_state',lambda label:None)
    assert operator.install_plist(row)=='INSTALLED_UNLOADED'
    assert target.read_bytes()==after and target.stat().st_ino!=original_inode
    assert operator.metadata.snapshot(target)==expected
    assert operator.metadata.snapshot(target)['xattrs']['com.apple.provenance']==provenance
    # A real metadata-only drift on our private file must stop inverse CAS.
    drift=deepcopy(expected);changed=b'synthetic metadata drift'
    drift['xattrs']['user.review_marker']=dict(base64=base64.b64encode(changed).decode(),sha256=hashlib.sha256(changed).hexdigest(),bytes=len(changed))
    apply_private(target,drift)
    with pytest.raises(operator.metadata.MetadataError,match='PLIST_METADATA_DRIFT'):
        operator.install_plist(row,rollback=True)
    assert target.read_bytes()==after
    apply_private(target,expected)
    assert operator.install_plist(row,rollback=True)=='ROLLED_BACK'
    assert target.read_bytes()==before
    assert operator.metadata.snapshot(target)==expected
    assert operator.metadata.snapshot(target)['xattrs']['com.apple.provenance']==provenance
