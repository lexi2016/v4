"""Frozen exact301314 failures; call the actual unchanged admission helper."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from ops import repair_301314_admission as repair


def fixture_context(tmp_path):
    helper_ref=repair.load(repair.owner.reference(repair.SOURCE_CONFIG))['admission_helper']
    helper=repair.owner.module(helper_ref,'test_actual_301314_admission')
    raw=tmp_path/'raw.day';raw.write_bytes(b'actual-bound-input')
    accepted=tmp_path/'native-admission.json';accepted.write_text('{"symbol":"301314","classification":"ACCEPTED"}')
    snapshot=dict(asof_date=repair.TARGET,original_target_codes=[repair.SYMBOL],symbols={repair.SYMBOL:dict(
        history_start_date=20230328,event_coverage_complete=True,publish_roles=['selector','backtest'],raw_files=[repair.owner.reference(raw)])})
    path=tmp_path/'snapshot.json';path.write_text(json.dumps(snapshot));snapshot_ref=repair.owner.reference(path)
    qp=tmp_path/'quarantine.json';qp.write_text(json.dumps(dict(generation_id=repair.GENERATION,reasons={})))
    receipt_path=tmp_path/'receipt.json';receipt_path.write_text('{}')
    receipt=dict(adjustment_snapshot=snapshot_ref,snapshot_file_sha256=snapshot_ref['sha256'],generation_id=repair.GENERATION,
        generation_manifest_path=str(receipt_path),quarantine_manifest_path=str(qp),quarantine_manifest=repair.owner.reference(qp),target_date=repair.TARGET)
    ctx=SimpleNamespace(helper=helper,snapshot=snapshot,snapshot_ref=snapshot_ref,footer=dict(adjustment_snapshot=snapshot_ref),
        receipt=receipt,quarantine=json.loads(qp.read_text()),quarantine_ref=repair.owner.reference(qp),generation=repair.GENERATION)
    proof=dict(effective_history_end_date=repair.TARGET,accepted_evidence=[repair.owner.reference(accepted)],
        original_missing_fields=['history_end_date','accepted_evidence'],helper=helper_ref)
    return ctx,proof,raw,path


def test_real_validator_requires_both_typed_fields_and_keeps_sources(tmp_path,monkeypatch):
    ctx,proof,raw,path=fixture_context(tmp_path);before=path.read_bytes();read=ctx.helper.read_json
    monkeypatch.setattr(repair,'verified_fact',lambda *_:proof)
    result=repair.qualify(ctx,dict(path='proof',sha256='bound'))
    assert result['status']=='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH'
    assert result['history_end_metadata']['date_only_admission']['reason']=='CURRENT_SYMBOL_ACCEPTANCE_REFERENCES_MISSING'
    assert path.read_bytes()==before and 'history_end_date'not in ctx.snapshot['symbols'][repair.SYMBOL]
    assert ctx.helper.read_json is read


def test_no_acceptance_reference_cannot_clear_pending(tmp_path,monkeypatch):
    ctx,proof,_,_=fixture_context(tmp_path);proof['accepted_evidence']=[]
    monkeypatch.setattr(repair,'verified_fact',lambda *_:proof)
    with pytest.raises(ValueError,match='ORIGINAL_VALIDATOR_REJECTED'):repair.qualify(ctx,{})


def test_raw_mismatch_fails_and_restores_original_reader(tmp_path,monkeypatch):
    ctx,proof,raw,_=fixture_context(tmp_path);raw.write_bytes(b'changed');previous=ctx.helper.read_json
    monkeypatch.setattr(repair,'verified_fact',lambda *_:proof)
    with pytest.raises(ValueError,match='DATE_ONLY_ORACLE_CONFLICT'):repair.qualify(ctx,{})
    assert ctx.helper.read_json is previous


def test_fact_drift_and_wrong_scope_are_rejected(monkeypatch):
    monkeypatch.setattr(repair,'load',lambda _:dict(schema=repair.SCHEMA,paired_roles={'selector':'forged'}))
    monkeypatch.setattr(repair,'collect_source_fact',lambda _:dict(schema=repair.SCHEMA,paired_roles={'selector':'actual'}))
    with pytest.raises(ValueError,match='TYPED_FACT_DRIFT'):repair.verified_fact(None,{})
    with pytest.raises(ValueError,match='SOURCE_SCOPE_CONFLICT'):
        repair.scope(SimpleNamespace(target=repair.TARGET,generation=repair.GENERATION,snapshot_ref={'sha256':repair.SNAPSHOT_SHA},config={'admission_helper':{'sha256':repair.HELPER_SHA}}),'002731.SZ')


def test_fresh_publisher_import_shadowing_preserves_exact_preparation_path_and_sha():
    import subprocess
    import sys
    code = '''
from ops import repair_301314_admission as repair
from pathlib import Path
import importlib,json
expected=Path(repair.__file__).resolve().with_name('research_panel_top200.py')
ref=repair.owner.reference(expected)
from ops.sync_stock_history_completion import publish as unused_publisher
shadow=importlib.import_module('ops.research_panel_top200')
assert Path(shadow.__file__).resolve()!=expected
assert repair.verify_preparation_owner(ref)==expected
for changed in ({**ref,'sha256':'0'*64},repair.owner.reference(Path(shadow.__file__))):
    try:repair.verify_preparation_owner(changed)
    except ValueError:pass
    else:raise AssertionError('Preparation hash/path substitution accepted')
print(json.dumps(dict(status='PASS',planned=ref,shadow=repair.owner.reference(Path(shadow.__file__)),publish_called=False)))
'''
    completed=subprocess.run([sys.executable,'-c',code],cwd=Path(repair.__file__).resolve().parents[1],capture_output=True,text=True)
    assert completed.returncode==0,completed.stdout+completed.stderr
    result=json.loads(completed.stdout)
    assert result['status']=='PASS'and result['publish_called']is False
