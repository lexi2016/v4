from __future__ import annotations
import builtins
import importlib.util
import json
from pathlib import Path
import sys
import types

BASE=Path(__file__).resolve().parents[3]/"input"/"baseline"/"source"

def _load(kind):
    pkg_name="_receipt_baseline_"+kind
    package=types.ModuleType(pkg_name);package.__path__=[];sys.modules[pkg_name]=package
    ns=types.ModuleType(pkg_name+"._namespace")
    ns.read_global=lambda scope,name:scope.get(name,getattr(builtins,name,None))
    sys.modules[ns.__name__]=ns
    spec=importlib.util.spec_from_file_location(pkg_name+".runner_receipts",BASE/kind/"stage_center/_runner_parts/runner_receipts.py")
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

class Deadline:
    def before_receipt(self,payload):return dict(payload)
    def receipt_written(self,path,result):pass

def _write(kind, tmp_path):
    root=tmp_path/kind
    config=types.SimpleNamespace(receipt_root=root,backfill_run_id=None)
    owner=types.SimpleNamespace(config=config,_receipt_path=lambda d,s:root/d/s/"receipt.json")
    def atomic(path,value):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value)+"\n")
    payload={"trade_date":"20261009","stage_id":"STAGE_0940_0945","status":"PARTIAL_WITH_ROWS","dispatch_mode":"NATURAL","due_status":"DUE","markets":{"A_SHARE":{"selected_rows":10}},"write_performed":True}
    scope={"_deadline":Deadline(),"_atomic_json":atomic,"SAFETY_FLAGS":{"production_allowed":False,"buy_gate_updated":False,"orders_sent":False}}
    return _load(kind)._StageCenterRunner__write_receipt_body(scope,owner,payload,"20261009","STAGE_0940_0945"),root

def test_future_receipt_records_real_owner_write_time(tmp_path):
    result,_=_write("actual_stage",tmp_path)
    assert result.get("recorded_at"),"RECEIPT_RECORD_TIME_NOT_RECORDED"

def test_future_receipt_keeps_immutable_owner_history(tmp_path):
    result,root=_write("canonical",tmp_path)
    history=result.get("receipt_history")
    assert isinstance(history,dict),"NO_IMMUTABLE_NATURAL_RECOVERY_HISTORY"
    assert (root/history["relative_path"]).is_file()
