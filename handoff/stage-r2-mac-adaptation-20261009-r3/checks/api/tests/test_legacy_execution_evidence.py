"""Actual API reader tests; only SelectionStore verification is an explicit test boundary."""
from __future__ import annotations
import copy
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import uuid
import pytest

ROOT = Path(__file__).resolve().parents[1]
DATE, STAGE = "20261009", "STAGE_0925"
IDENTITY = dict(run_id="run-stage-test", artifact_id="selection-stage-test",
                algorithm_sha256="a"*64, raw_artifact_sha256="b"*64, selected_rows=10)

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def _load(name, path, monkeypatch):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module

@pytest.fixture
def reader(monkeypatch):
    infra = ModuleType("infrastructure")
    infra.__path__ = [str(ROOT/"legacy_support")]
    monkeypatch.setitem(sys.modules, "infrastructure", infra)
    _load("infrastructure.owned_io", ROOT/"legacy_support/owned_io.py", monkeypatch)
    name = "stage_reader_" + uuid.uuid4().hex
    package = ModuleType(name)
    package.__path__ = []
    monkeypatch.setitem(sys.modules, name, package)
    _load(name+".contracts", ROOT/"legacy_support/contracts.py", monkeypatch)
    path = Path(os.environ.get("STAGE_MINIMAL_READER_FILE",
        str(ROOT/"after/source/actual_api/stage_center/execution_evidence.py")))
    return _load(name+".execution_evidence", path, monkeypatch)

def verified():
    return {
        "A_SHARE": {**IDENTITY, "status": "PARTIAL_WITH_ROWS",
                    "requested_rows":216, "source_rows":205,
                    "missing_symbols":[f"A.92{i:04d}" for i in range(11)]},
        "HK_CONNECT":{"status":"CANNOT_CONFIRM", "selected_rows":0},
    }

def receipt():
    return dict(schema_version="stage_center.runner.receipt.v1", runner="stage_center",
        trade_date=DATE,stage_id=STAGE,dispatch_mode="NATURAL",due_status="DUE",
        status="PARTIAL_WITH_ROWS",production_allowed=False,buy_gate_updated=False,orders_sent=False,
        markets={
            "A_SHARE":{**IDENTITY,"requested_rows":216,"source_rows":205},
            "HK_CONNECT":{"status":"CANNOT_CONFIRM","selected_rows":0,"write_performed":False,
                          "cannot_confirm":["HK D1 status must be STRICT_0_2_READY"]},
        })

def publish(root, payload, archive=False):
    value=copy.deepcopy(payload)
    if archive:
        value["recorded_at"]="2026-10-09T01:26:34.123456+00:00"
        value["record_time_source"]="OWNER_WRITE_CLOCK_UTC"
        raw=canonical(value)+b"\n"
        sha=digest(raw)
        relative=f"{DATE}/{STAGE}/attempt_evidence/recorded-{sha}/RECEIPT.json"
        p=root/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        value["receipt_history"]={"schema_version":"stage_center.runner.history_ref.v1",
                                  "relative_path":relative,"sha256":sha}
    p=root/DATE/STAGE/"receipt.json";p.parent.mkdir(parents=True,exist_ok=True)
    p.write_bytes(json.dumps(value,ensure_ascii=False,indent=2).encode()+b"\n")
    return value,p

def test_verified_result_remains_visible_when_receipt_root_is_unbound(reader):
    r=reader.read_stage_execution(None,DATE,STAGE,verified())
    a=r["selection_results"]["A_SHARE"]
    assert a["status"]=="RESULT_AVAILABLE" and a["selected_rows"]==10
    assert a["requested_rows"]==216 and a["source_rows"]==205 and a["missing_quote_rows"]==11
    assert a["quote_coverage_ratio"]==pytest.approx(205/216,abs=1e-6)
    assert r["selection_results"]["HK_CONNECT"]["status"]=="NO_VERIFIED_RESULT"
    assert r["execution_verified"] is r["natural_verified"] is False

def test_legacy_receipt_reports_result_and_hk_input_block_separately(reader,tmp_path):
    original,p=publish(tmp_path,receipt())
    before=p.read_bytes()
    r=reader.read_stage_execution(tmp_path,DATE,STAGE,verified())
    assert r["selection_results"]["A_SHARE"]["selected_rows"]==10
    assert r["markets"]["A_SHARE"]["selection_binding"]=="BOUND_TO_VERIFIED_SELECTION"
    assert r["markets"]["HK_CONNECT"]["failure_layer"]=="PRESELECTION_INPUT"
    assert r["receipt_history_binding"]=="OWNER_HISTORY_NOT_RECORDED"
    assert r["recorded_at"] is None and r["natural_verified"] is False
    assert p.read_bytes()==before
    assert list((tmp_path/DATE/STAGE).iterdir())==[p]

def test_owner_history_is_bound_but_does_not_certify_natural_execution(reader,tmp_path):
    value,p=publish(tmp_path,receipt(),archive=True)
    before={str(f):f.read_bytes() for f in tmp_path.rglob("*") if f.is_file()}
    r=reader.read_stage_execution(tmp_path,DATE,STAGE,verified())
    assert r["receipt_history_binding"]=="OWNER_HISTORY_SHA_BOUND"
    assert r["record_time_status"]=="OWNER_WRITE_CLOCK_RECORDED"
    assert r["recorded_at"]==value["recorded_at"]
    assert "NO_IMMUTABLE_NATURAL_RECOVERY_HISTORY" not in r["cannot_confirm"]
    assert "NO_INDEPENDENT_RUN_RECEIPT_SHA_BINDING" in r["cannot_confirm"]
    assert r["execution_verified"] is r["natural_verified"] is False
    assert {str(f):f.read_bytes() for f in tmp_path.rglob("*") if f.is_file()}==before

@pytest.mark.parametrize("fault",["bytes","pointer_sha","wrong_slot","payload_change","naive_clock","false_clock_source","symlink"])
def test_owner_history_conflicts_cannot_be_promoted(reader,tmp_path,fault):
    value,p=publish(tmp_path,receipt(),archive=True)
    history=tmp_path/value["receipt_history"]["relative_path"]
    if fault=="bytes":history.write_bytes(history.read_bytes()+b" ")
    elif fault=="pointer_sha":value["receipt_history"]["sha256"]="c"*64
    elif fault=="wrong_slot":value["receipt_history"]["relative_path"]=value["receipt_history"]["relative_path"].replace(DATE,"20261008")
    elif fault=="payload_change":value["node_attempt_count"]=99
    elif fault in {"naive_clock","false_clock_source"}:
        body=copy.deepcopy(value);body.pop("receipt_history")
        body["recorded_at"]="2026-10-09T01:26:34" if fault=="naive_clock" else body["recorded_at"]
        if fault=="false_clock_source":body["record_time_source"]="PLANNED_CUTOFF"
        raw=canonical(body)+b"\n";sha=digest(raw)
        rel=f"{DATE}/{STAGE}/attempt_evidence/recorded-{sha}/RECEIPT.json"
        hp=tmp_path/rel;hp.parent.mkdir(parents=True,exist_ok=True);hp.write_bytes(raw)
        value={**body,"receipt_history":{"schema_version":"stage_center.runner.history_ref.v1","sha256":sha,"relative_path":rel}}
    elif fault=="symlink":
        saved=history.read_bytes();history.unlink()
        target=tmp_path/"outside.json";target.write_bytes(saved);history.symlink_to(target)
    p.write_bytes(canonical(value)+b"\n")
    r=reader.read_stage_execution(tmp_path,DATE,STAGE,verified())
    assert r["receipt_history_binding"]=="OWNER_HISTORY_CONFLICT"
    assert r["natural_verified"] is r["execution_verified"] is False
    assert r["selection_results"]["A_SHARE"]["selected_rows"]==10

def store_fixture(root):
    relative=f"runs/{DATE}/{STAGE}/A_SHARE/{IDENTITY['run_id']}/artifact.csv"
    art=root/relative;art.parent.mkdir(parents=True,exist_ok=True)
    rows=[{"code":f"A.{i+1:06d}","rank":i+1,"score":75.5} for i in range(IDENTITY["selected_rows"])]
    artifact=("code,rank,score\n"+"".join(f"{r['code']},{r['rank']},75.5\n" for r in rows)).encode()
    # Complete the original unit-test seam with the scope and row fields
    # returned by the real store. The production verifier is not mocked in
    # the separate full-consumer integration suite.
    envelope={**verified()["A_SHARE"],"trade_date":DATE,"stage_id":STAGE,"market":"A_SHARE",
              "selection_status":"PARTIAL_WITH_ROWS","rows":rows}
    manifest={"selection_envelope":envelope, "artifact_sha256":digest(artifact)}
    rec={"status":"VERIFIED","artifact_sha256":digest(artifact)}
    art.write_bytes(artifact)
    mr=str(Path(relative).parent/"manifest.json");rr=str(Path(relative).parent/"receipt.json")
    (root/mr).write_bytes(json.dumps(manifest,indent=2).encode()+b"\n")
    (root/rr).write_bytes(json.dumps(rec,indent=4).encode()+b"\n")
    meta={"envelope":envelope,"trade_date":DATE,"stage_id":STAGE,"market":"A_SHARE",
          "artifact_relative":relative,"artifact_sha256":digest(artifact),
          "manifest_sha256":digest(canonical(manifest)),"receipt_sha256":digest(canonical(rec))}
    def verify(date,stage,market,run):
        assert (date,stage,market,run)==(DATE,STAGE,"A_SHARE",IDENTITY["run_id"])
        return copy.deepcopy(meta)
    store=SimpleNamespace(root=root,_verify_run=verify)
    binding={"schema_version":"stage_center.runner.selection_binding.v1",**IDENTITY,
             "artifact_relative":relative,"manifest_relative":mr,"receipt_relative":rr,
             "artifact_bytes_sha256":digest(artifact),
             "manifest_bytes_sha256":digest((root/mr).read_bytes()),
             "receipt_bytes_sha256":digest((root/rr).read_bytes()),
             "manifest_canonical_sha256":meta["manifest_sha256"],"receipt_canonical_sha256":meta["receipt_sha256"]}
    return store,binding

def test_selection_trio_uses_both_canonical_and_file_byte_hashes(reader,tmp_path):
    store,binding=store_fixture(tmp_path/"selection")
    assert binding["receipt_bytes_sha256"]!=binding["receipt_canonical_sha256"]
    payload=receipt();payload["selection_artifacts"]={"A_SHARE":binding}
    publish(tmp_path/"receipts",payload,archive=True)
    r=reader.read_stage_execution(tmp_path/"receipts",DATE,STAGE,verified(),selection_store=store)
    assert r["selection_artifact_bindings"]["A_SHARE"]["status"]=="BOUND_TO_VERIFIED_SELECTION_TRIO"
    assert r["natural_verified"] is r["execution_verified"] is False

def test_declared_trio_without_bound_store_is_not_independent_verification(reader,tmp_path):
    store,binding=store_fixture(tmp_path/"selection")
    payload=receipt();payload["selection_artifacts"]={"A_SHARE":binding}
    publish(tmp_path/"receipts",payload,archive=True)
    r=reader.read_stage_execution(tmp_path/"receipts",DATE,STAGE,verified())
    assert r["selection_artifact_bindings"]["A_SHARE"]["status"]=="SELECTION_STORE_NOT_BOUND"
    assert r["execution_verified"] is r["natural_verified"] is False

@pytest.mark.parametrize("fault",["canonical_used_as_bytes","artifact_after_verify","declared_path","wrong_identity","wrong_count","manifest_format_change"])
def test_selection_trio_conflicts_preserve_result_but_refuse_binding(reader,tmp_path,fault):
    store,binding=store_fixture(tmp_path/"selection")
    if fault=="canonical_used_as_bytes":binding["receipt_bytes_sha256"]=binding["receipt_canonical_sha256"]
    elif fault=="artifact_after_verify":(store.root/binding["artifact_relative"]).write_bytes(b"changed\n")
    elif fault=="declared_path":binding["manifest_relative"]="../external/manifest.json"
    elif fault=="wrong_identity":binding["run_id"]="run-other"
    elif fault=="wrong_count":binding["selected_rows"]=9
    elif fault=="manifest_format_change":
        p=store.root/binding["manifest_relative"];p.write_bytes(canonical(json.loads(p.read_bytes()))+b"\n")
    payload=receipt();payload["selection_artifacts"]={"A_SHARE":binding}
    publish(tmp_path/"receipts",payload,archive=True)
    r=reader.read_stage_execution(tmp_path/"receipts",DATE,STAGE,verified(),selection_store=store)
    assert r["selection_artifact_bindings"]["A_SHARE"]["status"]=="SELECTION_TRIO_CONFLICT"
    assert r["selection_results"]["A_SHARE"]["selected_rows"]==10
    assert r["natural_verified"] is r["execution_verified"] is False

def test_receipt_replaced_during_store_verification_is_not_history_bound(reader,tmp_path):
    store,binding=store_fixture(tmp_path/"selection")
    payload=receipt();payload["selection_artifacts"]={"A_SHARE":binding}
    value,p=publish(tmp_path/"receipts",payload,archive=True)
    original=store._verify_run
    def changed(*args):
        ret=original(*args);replacement=copy.deepcopy(value)
        replacement["node_attempt_count"]=json.loads(p.read_bytes()).get("node_attempt_count",0)+1
        p.write_bytes(canonical(replacement)+b"\n");return ret
    store._verify_run=changed
    r=reader.read_stage_execution(tmp_path/"receipts",DATE,STAGE,verified(),selection_store=store)
    assert r["receipt_history_binding"]=="OWNER_HISTORY_CONFLICT"
    assert "RECEIPT_CHANGED_DURING_READ" in r["cannot_confirm"]
    assert r["selection_artifact_bindings"]["A_SHARE"]["status"]!="BOUND_TO_VERIFIED_SELECTION_TRIO"

@pytest.mark.parametrize("bad",[None,True,-1,"10"])
def test_invalid_selection_counts_are_not_reported_as_computed(reader,bad):
    lanes=verified();lanes["A_SHARE"]["selected_rows"]=bad
    r=reader.read_stage_execution(None,DATE,STAGE,lanes)
    assert r["selection_results"]["A_SHARE"]["status"]=="NO_VERIFIED_RESULT"

@pytest.mark.parametrize("status",[None,"UNRECOGNIZED_READY"])
def test_unknown_selection_status_is_not_a_verified_result(reader,status):
    lanes=verified();lanes["A_SHARE"]["status"]=status
    r=reader.read_stage_execution(None,DATE,STAGE,lanes)
    assert r["selection_results"]["A_SHARE"]["status"]=="NO_VERIFIED_RESULT"

@pytest.mark.parametrize("where",["binding","original"])
def test_boolean_one_is_not_a_selected_row_count(reader,tmp_path,monkeypatch,where):
    monkeypatch.setitem(IDENTITY,"selected_rows",1)
    store,binding=store_fixture(tmp_path/"selection")
    payload=receipt()
    if where=="binding":binding["selected_rows"]=True
    else:payload["markets"]["A_SHARE"]["selected_rows"]=True
    payload["selection_artifacts"]={"A_SHARE":binding}
    publish(tmp_path/"receipts",payload,archive=True)
    r=reader.read_stage_execution(tmp_path/"receipts",DATE,STAGE,verified(),selection_store=store)
    assert r["selection_artifact_bindings"]["A_SHARE"]["status"]=="SELECTION_TRIO_CONFLICT"

def test_original_consumer_call_binds_its_existing_store(reader,tmp_path):
    """Execute the unchanged consumer call boundary, not the full historical API."""
    source=Path(os.environ.get("STAGE_CONSUMER_FILE",str(ROOT/"after/conditional_api/stage_center/consumer.py")))
    tree=ast.parse(source.read_text())
    calls=[node for node in ast.walk(tree) if isinstance(node,ast.Assign)
           and isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name)
           and node.value.func.id=="read_stage_execution"]
    assert len(calls)==1
    store,binding=store_fixture(tmp_path/"selection")
    payload=receipt();payload["selection_artifacts"]={"A_SHARE":binding}
    publish(tmp_path/"receipts",payload,archive=True)
    response={"markets":verified()}
    scope=dict(self=SimpleNamespace(store=store,execution_receipt_root=tmp_path/"receipts"),
               trade_date=DATE,stage_id=STAGE,response=response,selection_stores={"A_SHARE":store},
               read_stage_execution=reader.read_stage_execution)
    exec(compile(ast.fix_missing_locations(ast.Module(body=calls,type_ignores=[])),str(source),"exec"),scope)
    evidence=response["execution_evidence"]
    assert evidence["selection_artifact_bindings"]["A_SHARE"]["status"]=="BOUND_TO_VERIFIED_SELECTION_TRIO"
    assert evidence["selection_results"]["A_SHARE"]["selected_rows"]==10
    assert evidence["natural_verified"] is evidence["execution_verified"] is False
