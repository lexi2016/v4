"""Read-only audit contract, using only explicitly SYNTHETIC authority fixtures."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import pytest
from domains import manager_research_evidence as original
from test_explicit_owner_binding import synthetic_authority

TOOL=Path(__file__).resolve().parents[1]/'tools/audit_connect_authority.py'

def _audit():
    assert TOOL.is_file(), 'bounded original-reader audit tool must be supplied'
    spec=importlib.util.spec_from_file_location('authority_audit_tool_test',TOOL)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_audit_complete_chain_still_not_supply_or_activation(synthetic_authority):
    audit=_audit()
    root,app,sha,owner,chain=synthetic_authority
    before={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    r=audit.inspect_authority(original,root,'20260930',app,sha,'2026-09-30T15:00:00+08:00')
    assert r['status']=='READBACK_VERIFIED'
    assert r['membership_count']==651
    assert len(r['files'])==4
    assert r['source']['observed_at']=='2026-09-30T10:00:00+08:00'
    assert r['source']['available_at']!=r['source']['observed_at']
    assert r['producer_activity_verified'] is False
    assert r['activation_allowed'] is False
    assert r['raw_acquisition_receipt_verified'] is False
    assert before=={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    assert audit.binding_proposal([r],root,app,sha)['activation_allowed'] is False


def test_missing_exact_date_no_recipe_and_native_reason(synthetic_authority):
    audit=_audit()
    root,app,sha,owner,chain=synthetic_authority
    r=audit.inspect_authority(original,root,'20260929',app,sha,'2026-09-29T15:00:00+08:00')
    assert r['status']=='CANNOT_CONFIRM'
    assert r['diagnostic']['code']=='HK_CONNECT_EXACT_UNIVERSE_MISSING'
    assert r['membership_count'] is None
    assert audit.binding_proposal([r],root,app,sha)['environment'] is None


def test_missing_chain_not_automatically_completed(synthetic_authority):
    audit=_audit()
    root,app,sha,owner,chain=synthetic_authority
    p=root/chain['paths']['receipt_relative'];p.unlink()
    r=audit.inspect_authority(original,root,'20260930',app,sha,'2026-09-30T15:00:00+08:00')
    assert not p.exists()
    assert r['diagnostic']['code']=='HK_UNIVERSE_AUTHORITY_CHAIN_MISSING'
    assert r['status']=='CANNOT_CONFIRM'


def test_cutoff_not_backdated_and_no_clock_override(synthetic_authority,monkeypatch):
    audit=_audit()
    root,app,sha,owner,chain=synthetic_authority
    real=original.read_universe_evidence;calls=[]
    def tracked(*args,**kwargs):
        calls.append(kwargs)
        return real(*args,**kwargs)
    monkeypatch.setattr(original,'read_universe_evidence',tracked)
    r=audit.inspect_authority(original,root,'20260930',app,sha,'2026-09-30T09:59:00+08:00')
    assert r['status']=='CANNOT_CONFIRM'
    assert r['diagnostic']['code']=='HK_CONNECT_TARGET_AUTHORITY_AFTER_CUTOFF'
    assert 'clock' not in calls[0] and 'as_of' not in calls[0]


def test_conflicting_roots_never_auto_select(synthetic_authority):
    audit=_audit()
    root,app,sha,owner,chain=synthetic_authority
    good=audit.inspect_authority(original,root,'20260930',app,sha,'2026-09-30T15:00:00+08:00')
    other=json.loads(json.dumps(good));other['data_root']=str(root.parent/'second')
    other['source']['sha256']='d'*64
    r=audit.binding_proposal([good,other],root,app,sha)
    assert r['environment'] is None
    assert r['reason']=='CONFLICTING_AUTHORITY_ROOTS_REQUIRE_ORIGINAL_OWNER_RECONCILIATION'


def test_no_selected_root_no_implicit_fallback(synthetic_authority):
    audit=_audit()
    root,app,sha,owner,chain=synthetic_authority
    good=audit.inspect_authority(original,root,'20260930',app,sha,'2026-09-30T15:00:00+08:00')
    assert audit.binding_proposal([good],root.parent/'uninspected',app,sha)['environment'] is None


def test_symlink_owner_source_refused(synthetic_authority,tmp_path):
    audit=_audit()
    root,app,sha,owner,chain=synthetic_authority
    linked=tmp_path/'link';linked.symlink_to(app,target_is_directory=True)
    with pytest.raises(ValueError,match='EXACT_ABSOLUTE_PATH_REQUIRED'):
        audit.exact_path(str(linked))


def test_evidence_destination_not_under_runtime_or_data(synthetic_authority):
    audit=_audit()
    root,app,sha,owner,chain=synthetic_authority
    with pytest.raises(ValueError,match='EVIDENCE_PATH_OVERLAPS_PROTECTED_ROOT'):
        audit.check_destination(root/'evidence',[root,app])


def test_reject_source_hash_drift_before_loading(synthetic_authority):
    audit=_audit()
    root,app,sha,owner,chain=synthetic_authority
    with pytest.raises(ValueError,match='READER_SOURCE_SHA_MISMATCH'):
        audit.load_reader(app,expected_sha='0'*64)


@pytest.mark.parametrize('target,expected_code',[('20260930',0),('20260929',2)])
def test_real_cli_only_writes_new_evidence_dir(synthetic_authority,tmp_path,target,expected_code):
    import subprocess
    audit=_audit()
    root,app,sha,owner,chain=synthetic_authority
    before={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    out=tmp_path/'audit_evidence'
    date_iso=f'{target[:4]}-{target[4:6]}-{target[6:8]}'
    result=subprocess.run([sys.executable,'-I',str(TOOL),'--app-root',str(app),
        '--owner-root',str(app),'--owner-sha256',sha,'--data-root',str(root),
        '--selected-data-root',str(root),'--date',target,'--cutoff',date_iso+'T15:00:00+08:00',
        '--output-dir',str(out)],capture_output=True,text=True,timeout=20)
    assert result.returncode==expected_code,result.stdout+result.stderr
    receipt=json.loads((out/'authority_readback.json').read_text())
    assert receipt['activation_allowed'] is False
    assert receipt['active_producer_identified'] is False
    assert receipt['real_api_verified'] is False and receipt['real_ui_verified'] is False
    assert before=={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    if expected_code:
        assert receipt['binding_proposal']['environment'] is None
