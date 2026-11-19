"""Fixed-date D18 FINAL_9 inference and D19 review. No training entrypoint."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
from statistics import mean
import struct
import sys
import warnings
import zipfile
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

PROJECT = Path("/Users/lexi/Desktop/学习/v4_app")
ROOT = PROJECT / "artifacts/p515_mac_d18_latest_trained_model_selection_d19_review_v1"
RUN = ROOT / "run"
OLD = PROJECT / "artifacts/p515_d18_anomaly_wave_shrink_research_20261118"
NATIVE = PROJECT / "artifacts/p515_d18_native_archive_preview_20261119/native/run"
RUNTIME = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-panel-throughput-storage-20261118-r3/api/app")
READER = Path("/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据/data_layer_interface_current/DATA_LAYER_INTERFACE.py")
D18, D19 = "20261118", "20261119"
GEN = "54f9474006c480a47303c18e4b2fd9a22132609cf44f229de63c68cb7d8a37a0"
INPUT = "0fe7bd668bcd734491e9526dba0bb42b99b5f4bc47e951b5f88d0954eb82ac3a"
PANEL = Path("/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据/selector_ready_panels/data_layer_daily_formula_increment_update_v1/selector_ready_current_to_20261118_qfq_54f9474006c480a4/selector_ready_current_to_20261118.parquet")
OHLCV = ["open", "high", "low", "close", "volume"]
ZERO = dict(model_fit=0, preprocessing_fit=0, tuning=0, static_new_score=0)
PINS = {
    "reader":"4f096d4995aa862296e0b918ca9dd136bd35dd0b1309efa1239f312be5f25565",
    "r2":"0c5f20e93072701c2c06d9cddcf4b28832888028b67eece2d7fc14be1ccb1381",
    "wiring":"873edeaa5c3d6d751a96cc17a94b48e792b43382b3266301915e10e7081cedbd",
    "model":"af73e2508dddab9a13a35c4113c2f6616a45ed02e25bc9c599a095345dfb89c8",
    "scaler":"e63cbcdff0bda3b67c9c98ef1db1223f3ab68ef3b9d332d6b8bedabdc79f825b",
    "params":"fe8383e3b044d0e89482f31d14091602683f1d4720f32a51e03616ff7562799a",
}
MODEL = "GEMINI_L2_C010_CLIP16/FINAL_9"

def now():
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()

def digest(data):
    return hashlib.sha256(data).hexdigest()

def identity(path):
    data = path.read_bytes()
    return {"bytes":len(data), "sha256":digest(data)}

def save(path, value, exclusive=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "x" if exclusive else "w"
    with path.open(mode, encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())

def event(name, **details):
    RUN.mkdir(parents=True, exist_ok=True)
    with (RUN/"EXECUTION_EVENTS.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at":now(),"event":name,**details}, ensure_ascii=False, allow_nan=False)+"\n")
        f.flush()
        os.fsync(f.fileno())

def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

def reader_for(path):
    assert digest(READER.read_bytes()) == PINS["reader"]
    sys.path.insert(0, str(RUNTIME))
    reader = load_module(READER, "p515_d18_review_reader")
    meta = reader.get_panel_meta(panel_path=path, include_dates=False)
    return reader, meta

def extract_features():
    path=NATIVE/"FROZEN_wiring.py"
    assert digest(path.read_bytes()) == PINS["wiring"]
    tree=ast.parse(path.read_text())
    nodes=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in ("_valid","_r2_features")]
    assert {node.name for node in nodes}=={"_valid","_r2_features"}
    source=ast.unparse(ast.Module(body=nodes,type_ignores=[]))
    namespace={"mean":mean,"_BAR":tuple(OHLCV),"_MATURE":frozenset(("SUCCESS_RESTART","FAILED_SUPPORT","FAILED_RISK","EXPIRED_PULLBACK"))}
    exec(compile(source,str(path), "exec"), namespace)
    return namespace["_r2_features"], source

def normalize(frame):
    frame=frame.copy()
    frame["trade_date"]=frame["trade_date"].astype(str)
    assert not frame.duplicated(["ts_code","trade_date"]).any()
    assert frame.trade_date.le(D18).all()
    return frame

def date_int(value):
    try:
        if pd.isna(value): return None
        text=str(int(float(value)))
        return text if len(text)==8 else None
    except (ValueError,TypeError): return None

def replay_r2(engine, code, rows, sessions, extractor):
    event("R2_START",security=code,rows=len(rows),first=rows[0]["trade_date"] if rows else None,last=rows[-1]["trade_date"] if rows else None)
    obs, _, mothers, pbs=engine.run_symbol(code,rows,sessions)
    current=[o for o in obs if o.get("candidate_date")==D18]
    if len(current)!=1:
        return current,None,pbs,{"reason":"NATIVE_CURRENT_TRACK_COUNT","count":len(current)}
    o=current[0]
    if o.get("stage")!="SAME_EVENT_PULLBACK" or o.get("pullback_sessions")!=3 or o.get("terminal_observed_today"):
        return current,None,pbs,{"reason":"R2_NOT_ACTIVE_K3"}
    if any(p.get("pullback_id")==o["pullback_id"] and p.get("end_date") is not None and p["end_date"]<=D18 for p in pbs):
        return current,None,pbs,{"reason":"CURRENT_PB_ALREADY_TERMINAL"}
    x=extractor(o,{r["trade_date"]:r for r in rows},sessions,pbs)
    if x is None or len(x)!=20 or not all(math.isfinite(v) for v in x):
        return current,None,pbs,{"reason":"FROZEN_FEATURE_INPUT_MISSING"}
    return current,x,pbs,{"reason":"NATIVE_FEATURE_OK"}

def prepare():
    if (RUN/"PREPARED.json").exists():
        return json.loads((RUN/"PREPARED.json").read_text())
    if RUN.exists() and any(RUN.iterdir()):
        raise RuntimeError("PARTIAL_RUN_EXISTS_INSPECT_NO_AUTO_RETRY")
    RUN.mkdir(parents=True, exist_ok=True)
    event("PREPARE_START",source_cutoff=D18,evaluation_day=D19)
    original_receipt=json.loads((OLD/"SCREEN_RECEIPT.json").read_text())
    assert original_receipt["generation"]==GEN and original_receipt["input_sha256"]==INPUT
    original= pd.read_csv(OLD/"00_全范围处置.csv",dtype=str,keep_default_na=False)
    primary =pd.read_csv(OLD/"01_量价初筛.csv",dtype=str,keep_default_na=False)
    assert len(original)==5572 and original["代码"].nunique()==5572
    assert len(primary)==610 and primary["代码"].nunique()==610
    assert set(primary["代码"])==set(original.loc[original["结构初筛"]=="PASS","代码"])
    universe=sorted(original["代码"])
    save(RUN/"UNIVERSE_FREEZE.json",{"at":now(),"date":D18,"codes":universe,"count":len(universe),"source_path":str(OLD/"00_全范围处置.csv"),"source_identity":identity(OLD/"00_全范围处置.csv"),"original_screen_receipt":identity(OLD/"SCREEN_RECEIPT.json"),"screen_source":identity(OLD/"screen.py"),"scope":"original D18 V4 A_SHARE and BJ snapshot universe"},True)
    reader,meta=reader_for(PANEL)
    assert meta["generation_id"]==GEN and meta["input_sha256"]==INPUT
    manifest=Path(meta["manifest_path"])
    assert digest(manifest.read_bytes())==original_receipt["manifest_sha256"]
    today=reader.load_selector_ready(columns=[*OHLCV,"name","market_type"],start_date=D18,end_date=D18,ts_codes=universe,panel_path=PANEL)
    today=normalize(today)
    assert set(today.ts_code)==set(universe) and len(today)==5572
    assert today.attrs["panel_metadata"]["generation_id"]==GEN
    today_by=today.set_index("ts_code")
    r2path=NATIVE/"R2_FROZEN_event_rules.py"
    assert digest(r2path.read_bytes())==PINS["r2"]
    engine=load_module(r2path,"p515_d18_review_r2")
    extractor,source=extract_features()
    (RUN/"FROZEN_FEATURE_AST.py.txt").write_text(source+"\n")
    calpath=NATIVE/"ORIGINAL_EXCHANGE_CALENDARS.json"
    caldoc=json.loads(calpath.read_text())
    base=caldoc["SZ"]
    sessions=tuple(sorted(set(map(str,base))|{d for d in original_receipt["date_scope"] if d>str(base[-1])}))
    assert sessions[0]=="20211021" and sessions[-1]==D18
    save(RUN/"R2_CALENDAR.json",list(sessions),True)
    with zipfile.ZipFile(ROOT/"reference/gemini_c010_zip.zip") as gz, zipfile.ZipFile(ROOT/"reference/codex_clip16_zip.zip") as cz:
        entries={"MODEL.pkl":gz.read("models/FINAL_9/model.pkl"),"SCALER.pkl":cz.read("models/FINAL_9/SCALER.pkl"),"PARAMETERS_AND_SUPPORT.json":gz.read("models/FINAL_9/PARAMETERS_AND_SUPPORT.json")}
        for name,raw in entries.items():
            key={"MODEL.pkl":"model","SCALER.pkl":"scaler","PARAMETERS_AND_SUPPORT.json":"params"}[name]
            assert digest(raw)==PINS[key]
            (RUN/name).write_bytes(raw)
    par=json.loads(entries["PARAMETERS_AND_SUPPORT.json"])
    feature_names=par["feature_names"]
    assert len(feature_names)==20
    # The original frozen K3 applicability and screen-to-R2 identity checks are retained.
    pool=primary[(primary["市场"]=="A_SHARE") & (primary["结构回调日数"].astype(int)==3)]
    codes=sorted(pool["代码"])
    event("READER_HISTORY_START",codes=codes,start=sessions[0],end=D18,columns=OHLCV)
    raw=reader.load_selector_ready(columns=OHLCV,start_date=sessions[0],end_date=D18,ts_codes=codes,panel_path=PANEL)
    raw=normalize(raw)
    assert raw.attrs["panel_metadata"]["generation_id"]==GEN
    assert set(raw.trade_date)<=set(sessions)
    groups={code:g.sort_values("trade_date").to_dict("records") for code,g in raw.groupby("ts_code")}
    records=[]; probes=[]; native=[]
    for _,p in pool.sort_values("代码").iterrows():
        code=p["代码"];h=groups.get(code,[])
        probe={"security":code,"screen_stage_k":3,"reader_rows":len(h),"status":None}
        if not h or h[-1]["trade_date"]!=D18 or not engine._valid(h[-1]):
            probe["status"]="MISSING_OR_INVALID_D18";probes.append(probe);continue
        current,x,pbs,reason=replay_r2(engine,code,h,sessions,extractor)
        if len(current)==1:
            o=current[0];native.append({"security":code,"observations":current,"pullbacks":pbs})
            probe.update(native_parent=o.get("family_id"),native_pb=o.get("pullback_id"),native_stage=o.get("stage"),native_k=o.get("pullback_sessions"))
        if x is None:
            probe["status"]=reason["reason"];probes.append(probe);continue
        if o["wave_end_confirmed_at"]!=p["回调首日"] or not math.isclose(o["frozen_wave_high"],float(p["上涨段高点"]),rel_tol=1e-7,abs_tol=1e-7):
            probe["status"]="SCREEN_R2_WAVE_IDENTITY_MISMATCH";probes.append(probe);continue
        current24,x24,pbs24,reason24=replay_r2(engine,code,[b for b in h if b["trade_date"]>="20240408"],sessions,extractor)
        if len(current24)!=1 or current24[0].get("pullback_id")!=o["pullback_id"] or x24!=x:
            probe["status"]="REPLAY_PREFIX_DISAGREES";probes.append(probe);continue
        packed=struct.pack("<20d",*x)
        assert len(packed)==160
        row={"security":code,"name":str(p["简称"]),"decision_date":D18,"rule_version":engine.RULE,"parent_id":o["family_id"],"pb_id":o["pullback_id"],"pullback_stage_k":3,"wave_start":o["wave_start"],"wave_end_confirmed_at":o["wave_end_confirmed_at"],"origin_date":o["origin_key_k_date"],"frozen_wave_high":o["frozen_wave_high"],"root_low":o["origin_low"],"features":list(x),"input_sha256":digest(packed),"raw_feature_hex":packed.hex(),"d18_close":float(today_by.at[code,"close"]),"model":MODEL,"state_proof":"PREFIX_CONCORDANCE_ONLY_NONPIT","listing_date_reference":date_int(p["可见上市日"])}
        row["row_key"]=[row[k] for k in ("security","decision_date","rule_version","parent_id","pb_id","input_sha256")]
        records.append(row);probe["status"]="MODEL_READY";probes.append(probe)
    byprobe={r["security"]:r for r in probes}
    dispositions=[]
    primary_by=primary.set_index("代码")
    for _,p in original.sort_values("代码").iterrows():
        code=p["代码"];status=p["结构初筛"];screen_k=None
        if status=="PASS":
            q=primary_by.loc[code];screen_k=int(q["结构回调日数"])
            status="MODEL_OUT_OF_DOMAIN_MARKET" if p["市场"]!="A_SHARE" else "MODEL_OUT_OF_DOMAIN_SCREEN_K" if screen_k!=3 else byprobe[code]["status"]
        bar=today_by.loc[code]
        dispositions.append({"security":code,"name":str(p["简称"]),"market":p["市场"],"original_screen_status":p["结构初筛"],"screen_stage_k":screen_k,"disposition":status,"d18_close":float(bar["close"]) if pd.notna(bar["close"]) else None,"d18_volume":float(bar["volume"]) if pd.notna(bar["volume"]) else None,"trading_identity":"UNKNOWN","source_generation":GEN,"source_cutoff":D18,**{k:v for k,v in byprobe.get(code,{}).items() if k.startswith("native_")}})
    pd.DataFrame(dispositions).to_csv(RUN/"D18_FULL_DISPOSITION.csv",index=False,encoding="utf-8-sig")
    pd.DataFrame(probes).to_csv(RUN/"D18_K3_QUALIFICATION.csv",index=False,encoding="utf-8-sig")
    save(RUN/"NATIVE_CONTEXT.json",native,True)
    save(RUN/"D18_INPUT_ROWS.json",records,True)
    (RUN/"MODEL_INPUTS_20_F64LE.bin").write_bytes(b"".join(bytes.fromhex(r["raw_feature_hex"]) for r in records))
    save(RUN/"ORDERED_ROW_KEYS.json",[r["row_key"] for r in records],True)
    pd.DataFrame([{"security":r["security"],**dict(zip(feature_names,r["features"]))} for r in records]).to_csv(RUN/"D18_INPUT_FEATURES.csv",index=False,encoding="utf-8-sig")
    # Exact source witness for eligible inputs is small and allows independent feature recomputation.
    witness={r["security"]:groups[r["security"]] for r in records}
    save(RUN/"ELIGIBLE_READER_WITNESS.json",witness,True)
    prepared={"status":"PREP_READY_AWAITING_REAL_PRELAUNCH_READBACK","at":now(),"U":5572,"screen_pass":610,"screen_k3_a_share":len(pool),"N":len(records),"disposition_counts":dict(Counter(r["disposition"] for r in dispositions)),"model":MODEL,"feature_names":feature_names,"feature_rows":len(records),"source_generation":GEN,"source_manifest":identity(manifest),"source_panel":str(PANEL),"reader":identity(READER),"r2":identity(r2path),"wiring":identity(NATIVE/"FROZEN_wiring.py"),"code":identity(Path(__file__)),"model_file":identity(RUN/"MODEL.pkl"),"scaler_file":identity(RUN/"SCALER.pkl"),"parameters_file":identity(RUN/"PARAMETERS_AND_SUPPORT.json"),"matrix":identity(RUN/"MODEL_INPUTS_20_F64LE.bin"),"ordered_row_keys":identity(RUN/"ORDERED_ROW_KEYS.json"),"budget":{**ZERO,"model_api_attempts_max":int(bool(records)),"new_probability_rows_max":len(records)},"ranking":{"order":"positive class probability descending, exact ties security ascending","threshold":None,"top_k":[5,10,20]},"execution":{"reader_calls":2,"r2_calls":sum(1 for _ in []),"model_deserialization":0,"model_api_attempts":0,"new_probability_rows":0,**ZERO},"research_only":True,"historical_pit":"UNKNOWN","true_unexposed_validation_rows":0}
    events=[json.loads(x) for x in (RUN/"EXECUTION_EVENTS.jsonl").read_text().splitlines()]
    prepared["execution"]["r2_calls"]=sum(x["event"]=="R2_START" for x in events)
    save(RUN/"PREPARED.json",prepared,True)
    event("PREPARED",N=len(records),U=5572)
    return prepared

def verify_prelaunch():
    receipt=json.loads((RUN/"PRELAUNCH_READBACK.json").read_text())
    assert receipt["status"]=="PASS"
    assert receipt["parent_folder_id"]=="1D06HNYnpdm0pIho7RXQDavpHPRKbNtYY"
    assert receipt["drive_id"] and receipt["url"].startswith("https://drive.google.com/")
    required=["PREPARED.json","MODEL.pkl","SCALER.pkl","PARAMETERS_AND_SUPPORT.json","MODEL_INPUTS_20_F64LE.bin","ORDERED_ROW_KEYS.json","D18_INPUT_ROWS.json","D18_FULL_DISPOSITION.csv"]
    for name in required:
        assert receipt["bound_files"][name]==identity(RUN/name)["sha256"],name
    assert receipt["inference_code_sha256"]==identity(Path(__file__))["sha256"]
    return receipt

def infer():
    if (RUN/"PREDICTION_ATTEMPT.json").exists() or (RUN/"INFERENCE_UNIT_STARTED.json").exists():
        raise RuntimeError("PREDICTION_ALREADY_ATTEMPTED_NO_RETRY")
    prepared=json.loads((RUN/"PREPARED.json").read_text()); verify_prelaunch()
    save(RUN/"INFERENCE_UNIT_STARTED.json",{"at":now(),"code_sha256":identity(Path(__file__))["sha256"],"no_automatic_retry":True},True)
    rows=json.loads((RUN/"D18_INPUT_ROWS.json").read_text())
    assert len(rows)==prepared["N"]
    if not rows:
        save(RUN/"RANKING_FREEZE.json",{"N":0,"at":now(),"api_attempts":0,"new_probability_rows":0},True)
        return
    # The only deserialization path is entered after the real prelaunch download check.
    import io
    import pickle
    import sklearn
    import scipy
    import platform
    class FinalOnlyUnpickler(pickle.Unpickler):
        ALLOWED={("sklearn.linear_model._logistic","LogisticRegression"),("sklearn.preprocessing._data","StandardScaler"),("numpy._core.numeric","_frombuffer"),("numpy._core.multiarray","scalar"),("numpy","dtype")}
        def find_class(self,module,name):
            if (module,name) not in self.ALLOWED:
                raise pickle.UnpicklingError(f"UNEXPECTED_PICKLE_GLOBAL:{module}.{name}")
            return super().find_class(module,name)
    counters={**ZERO,"model_deserialization_attempts":0,"model_deserialization_success":0,"scaler_transform_attempts":0,"scaler_transform_success":0,"model_api_attempts":0,"model_api_success":0,"model_api_failed":0,"new_probability_rows":0}
    save(RUN/"INFERENCE_COUNTERS.json",counters)
    par=json.loads((RUN/"PARAMETERS_AND_SUPPORT.json").read_text())
    seen_warnings=[]
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            objects=[]
            for name,key in (("MODEL.pkl","model"),("SCALER.pkl","scaler")):
                assert identity(RUN/name)["sha256"]==PINS[key]
                counters["model_deserialization_attempts"]+=1;save(RUN/"INFERENCE_COUNTERS.json",counters)
                objects.append(FinalOnlyUnpickler(io.BytesIO((RUN/name).read_bytes())).load())
                counters["model_deserialization_success"]+=1;save(RUN/"INFERENCE_COUNTERS.json",counters)
            model,scaler=objects
            seen_warnings=[str(w.message) for w in caught]
        assert list(model.classes_)==[0,1]
        assert np.array_equal(model.coef_.reshape(-1),np.asarray(par["model"]["coefficients"]).reshape(-1))
        assert np.array_equal(model.intercept_.reshape(-1),np.asarray(par["model"]["intercept"]).reshape(-1))
        for attr,key in (("mean_","mean"),("scale_","scale"),("var_","variance")):
            assert np.array_equal(getattr(scaler,attr),par["scaler"][key]),attr
        matrix=np.asarray([r["features"] for r in rows],dtype=np.float64)
        assert matrix.shape==(len(rows),20) and np.isfinite(matrix).all()
        assert matrix.astype("<f8").tobytes()==(RUN/"MODEL_INPUTS_20_F64LE.bin").read_bytes()
        num=par["numeric_indices_0based"];binary=par["binary_indices_0based"]
        assert np.isin(matrix[:,binary],[0,1]).all()
        transformed=matrix.copy()
        counters["scaler_transform_attempts"]+=1;save(RUN/"INFERENCE_COUNTERS.json",counters)
        transformed[:,num]=np.clip(scaler.transform(matrix[:,num]),par["boundary"]["z_min"],par["boundary"]["z_max"])
        counters["scaler_transform_success"]+=1;save(RUN/"INFERENCE_COUNTERS.json",counters)
        (RUN/"TRANSFORMED_MODEL_INPUT_F64LE.bin").write_bytes(transformed.astype("<f8").tobytes())
        save(RUN/"INFERENCE_ENVIRONMENT.json",{"at":now(),"python":platform.python_version(),"numpy":np.__version__,"sklearn":sklearn.__version__,"scipy":scipy.__version__,"warnings":seen_warnings,"classes":model.classes_.tolist(),"model":MODEL,"runtime_comparison":"RUNTIME_NOT_IDENTICAL"},True)
        save(RUN/"PREDICTION_ATTEMPT.json",{"at":now(),"N":len(rows),"U":prepared["U"],"matrix_sha256":digest(transformed.astype("<f8").tobytes()),"model_sha256":PINS["model"],"budget_max_calls":1},True)
        counters["model_api_attempts"]=1;save(RUN/"INFERENCE_COUNTERS.json",counters)
        event("PREDICT_START",N=len(rows),method="predict_proba")
        output=model.predict_proba(transformed)
        counters["model_api_success"]=1
        save(RUN/"INFERENCE_COUNTERS.json",counters)
        # Save every return byte before JSON validity or probability checks.
        returned_array=np.asarray(output,dtype="<f8")
        with (RUN/"RAW_PREDICT_PROBA_F64LE.bin").open("xb") as f:
            f.write(returned_array.tobytes(order="C"))
            f.flush()
            os.fsync(f.fileno())
        save(RUN/"RAW_PREDICT_PROBA_LAYOUT.json",{"at":now(),"shape":list(returned_array.shape),"dtype":"<f8","classes":model.classes_.tolist(),"ordered_row_keys":[r["row_key"] for r in rows],"raw":identity(RUN/"RAW_PREDICT_PROBA_F64LE.bin")},True)
        raw={"at":now(),"classes":model.classes_.tolist(),"ordered_row_keys":[r["row_key"] for r in rows],"probabilities":np.asarray(output).tolist()}
        save(RUN/"RAW_PREDICT_PROBA.json",raw,True)
        assert np.asarray(output).shape==(len(rows),len(model.classes_))
        assert np.isfinite(output).all() and np.all(output>=0) and np.all(output<=1)
        success_col=list(model.classes_).index(1)
        ranked=[{**r,"probability":float(output[i,success_col])} for i,r in enumerate(rows)]
        ranked.sort(key=lambda r:(-r["probability"],r["security"]))
        for i,r in enumerate(ranked,1):
            r["rank"]=i
        save(RUN/"RANKED_ROWS.json",ranked,True)
        pd.DataFrame([{k:v for k,v in r.items() if k not in ("features","raw_feature_hex","row_key")} for r in ranked]).to_csv(RUN/"D18_COMPLETE_RANKING.csv",index=False,encoding="utf-8-sig")
        for k in (5,10,20):
            save(RUN/f"TOP{k}_FROZEN.json",ranked[:k],True)
        counters["new_probability_rows"]=len(rows);save(RUN/"INFERENCE_COUNTERS.json",counters)
        save(RUN/"RANKING_FREEZE.json",{"at":now(),"N":len(rows),"ranking_sha256":identity(RUN/"RANKED_ROWS.json")["sha256"],"raw_probabilities":identity(RUN/"RAW_PREDICT_PROBA.json"),"top_sizes":{str(k):min(k,len(rows)) for k in (5,10,20)},"model":MODEL,"input_sha256":identity(RUN/"MODEL_INPUTS_20_F64LE.bin")["sha256"]},True)
        event("RANKING_FROZEN",N=len(rows))
    except Exception as exc:
        if counters["model_api_attempts"] and not counters["model_api_success"]:
            counters["model_api_failed"]=1
        save(RUN/"INFERENCE_COUNTERS.json",counters)
        save(RUN/"INFERENCE_FAILURE.json",{"at":now(),"type":type(exc).__name__,"error":str(exc),"automatic_retry":False,"warnings":seen_warnings})
        raise

def read_accepted_authority(binding, rows):
    """Consume only accepted frozen .day tails after the ranking has been frozen."""
    import csv
    summary_path=Path(binding["summary_path"])
    manifest_path=Path(binding["accepted_manifest_path"])
    results_path=Path(binding["file_results_path"])
    assert identity(summary_path)["sha256"]==binding["summary_sha256"]
    assert identity(manifest_path)["sha256"]==binding["accepted_manifest_sha256"]
    assert identity(results_path)["sha256"]==binding["file_results_sha256"]
    summary=json.loads(summary_path.read_text())
    manifest=json.loads(manifest_path.read_text())
    assert str(summary["target_date"])==D19
    assert summary["official_daily_source"]["source_kind"]=="TDX_OFFICIAL_G4DAY"
    assert summary["official_daily_source"]["package"]["sha256"]==binding["official_package_sha256"]
    codec_path=PROJECT/"ops/a_share_daily_sync.py"
    codec_dep=PROJECT/"ops/_a_share_daily_sync_parts/day_file_format.py"
    assert identity(codec_path)["sha256"]==binding["codec_sha256"]
    assert identity(codec_dep)["sha256"]==binding["codec_dependency_sha256"]
    sys.path.insert(0,str(PROJECT))
    codec=load_module(codec_path,"p515_bound_authority_codec")
    with results_path.open(encoding="utf-8-sig",newline="") as f:
        results=list(csv.DictReader(f))
    by_filename={Path(item["relative_path"]).name:item for item in manifest["files"]}
    audits=[];returned=[]
    for row in rows:
        code=row["security"];symbol,suffix=code.split(".")
        filename=suffix.lower()+symbol+".day"
        item=by_filename.get(filename)
        if item is None:
            audits.append({"security":code,"status":"NOT_IN_ACCEPTED_MANIFEST"})
            continue
        matching=[r for r in results if r["symbol"]==symbol and Path(r["path"]).name==filename]
        if len(matching)!=1:
            audits.append({"security":code,"status":"FILE_RESULT_NOT_UNIQUE"})
            continue
        result=matching[0]
        if result["target_date_ready"].lower()!="true" or result["last_date_after"]!=D19 or result["source_sha256_after"]!=item["sha256"] or result["source_kind"]!="TDX_OFFICIAL_G4DAY":
            audits.append({"security":code,"status":"NOT_ACCEPTED_READY_OR_SOURCE_SHA_CONFLICT"})
            continue
        local=manifest_path.parent/item["relative_path"]
        if not local.is_file():
            audits.append({"security":code,"status":"ACCEPTED_SNAPSHOT_FILE_MISSING"})
            continue
        actual=identity(local)
        if actual["sha256"]!=item["sha256"]:
            audits.append({"security":code,"status":"ACCEPTED_SNAPSHOT_SHA_CHANGED"})
            continue
        event("AUTHORITY_DAY_READER_START",security=code,tail_records=2,path=str(local),file_sha256=actual["sha256"])
        bars=codec.read_hq_day_bars(local,tail_records=2)
        dates=[]
        for bar in bars:
            date=f'{bar["year"]:04d}{bar["month"]:02d}{bar["day"]:02d}'
            dates.append(date)
            assert date<=D19
            if date in (D18,D19):
                returned.append({"ts_code":code,"trade_date":date,"open":bar["open"],"high":bar["high"],"low":bar["low"],"close":bar["close"],"volume":bar["vol"],"amount":bar["amount"]})
        audits.append({"security":code,"status":"ACCEPTED_FILE_READ","path":str(local),**actual,"tail_dates":dates,"file_result":{k:result[k] for k in ("status","target_date_ready","last_date_after","recorded_at","source_kind")} })
    save(RUN/"D19_AUTHORITY_FILE_AUDIT.json",{"at":now(),"authority_status":summary["authority_status"],"global_status":summary["status"],"global_exit_code":summary["exit_code"],"accepted_count":summary["accepted_count"],"quarantine_count":summary["quarantine_count"],"files":audits},True)
    return pd.DataFrame(returned),{"price_provider":"TDX_OFFICIAL_G4DAY","generation_id":binding["accepted_manifest_sha256"],"price_basis":"RAW_UNADJUSTED","volume_basis":"TDX_DAY_CODEC_VOL_LOTS","global_authority_status":summary["authority_status"],"global_status":summary["status"]}

def evaluate():
    if (RUN/"EVALUATION_SUMMARY.json").exists():
        return json.loads((RUN/"EVALUATION_SUMMARY.json").read_text())
    frozen=json.loads((RUN/"RANKING_FREEZE.json").read_text())
    assert frozen["ranking_sha256"]==identity(RUN/"RANKED_ROWS.json")["sha256"]
    rows=json.loads((RUN/"RANKED_ROWS.json").read_text())
    binding_path=RUN/"EVALUATION_SOURCE_BINDING.json"
    binding=json.loads(binding_path.read_text())
    assert binding["evaluation_date"]==D19
    assert binding["kind"] in ("V4_READER","V4_ACCEPTED_OFFICIAL_DAY","UNAVAILABLE")
    source_meta={}
    returned=pd.DataFrame()
    if binding["kind"]=="V4_READER":
        path=Path(binding["panel_path"])
        reader,source_meta=reader_for(path)
        assert source_meta["generation_id"]==binding["generation_id"]
        assert source_meta["input_sha256"]==binding["input_sha256"]
        manifest_path=Path(source_meta["manifest_path"])
        assert identity(manifest_path)["sha256"]==binding["manifest_sha256"]
        assert str(json.loads(manifest_path.read_text())["target_date"])==D19
        codes=sorted(r["security"] for r in rows)
        if binding.get("index_code"):
            assert binding["index_code"]=="000300.SH"
            codes=sorted(set(codes)|{"000300.SH"})
        available=source_meta.get("column_names",[])
        columns=[*OHLCV,*[c for c in ("pre_close","pct_chg","amount","name") if c in available]]
        event("EVALUATION_READER_START",codes=codes,start=D18,end=D19,panel_path=str(path))
        returned=reader.load_selector_ready(columns=columns,start_date=D18,end_date=D19,ts_codes=codes,panel_path=path)
        returned["trade_date"]=returned["trade_date"].astype(str)
        assert set(returned.trade_date)<={D18,D19}
        assert not returned.duplicated(["ts_code","trade_date"]).any()
        assert set(returned.ts_code)<=set(codes)
        assert returned.attrs["panel_metadata"]["generation_id"]==binding["generation_id"]
        returned.to_csv(RUN/"D19_READER_RETURN.csv",index=False,encoding="utf-8-sig")
        event("EVALUATION_READER_RETURN",rows=len(returned),source_generation=source_meta["generation_id"])
    elif binding["kind"]=="V4_ACCEPTED_OFFICIAL_DAY":
        returned,source_meta=read_accepted_authority(binding,rows)
        if not returned.empty:
            assert not returned.duplicated(["ts_code","trade_date"]).any()
            returned.to_csv(RUN/"D19_READER_RETURN.csv",index=False,encoding="utf-8-sig")
    else:
        event("EVALUATION_SOURCE_UNAVAILABLE",reason=binding["reason"])
    final=binding.get("final_close_confirmed") is True
    authority_files={}
    if binding["kind"]=="V4_ACCEPTED_OFFICIAL_DAY":
        authority_files={r["security"]:r for r in json.loads((RUN/"D19_AUTHORITY_FILE_AUDIT.json").read_text())["files"]}
    by={}
    for _,bar in returned.iterrows():
        by[(str(bar["ts_code"]),str(bar["trade_date"]))]=bar.to_dict()
    def finite_positive(value):
        return value is not None and math.isfinite(float(value)) and float(value)>0
    result=[]
    for row in rows:
        code=row["security"];bar=by.get((code,D19),{});base=by.get((code,D18),{})
        valid=all(finite_positive(bar.get(k)) for k in ("open","high","low","close"))
        volume=bar.get("volume")
        traded=valid and finite_positive(volume)
        cc=None;oc=None;rt=None;refclose=None
        reason=None;price_status="MISSING"
        if not bar:
            reason=binding.get("reason","MISSING_D19_ROW")
        elif not valid:
            reason="INVALID_D19_OHLC"
        elif not traded:
            reason="NO_RECORDED_D19_VOLUME"
        elif not finite_positive(base.get("close")):
            reason="MISSING_SAME_BASIS_D18_REFERENCE"
        else:
            refclose=float(base["close"])
            if final:
                cc=float(bar["close"])/refclose-1
                oc=float(bar["close"])/float(bar["open"])-1
                price_status="FINAL_CLOSE_FROM_VERIFIED_D19_GENERATION"
            else:
                rt=float(bar["close"])/refclose-1
                price_status="INTRADAY_OR_PROVISIONAL"
                reason="FINAL_CLOSE_NOT_VERIFIED"
        oneprice=bool(valid and len({float(bar[k]) for k in ("open","high","low","close")})==1)
        preclose=bar.get("pre_close")
        adjustment="RAW_UNADJUSTED_EX_RIGHTS_TREATMENT_UNKNOWN" if binding["kind"]=="V4_ACCEPTED_OFFICIAL_DAY" else "UNKNOWN"
        if refclose is not None and binding["kind"]!="V4_ACCEPTED_OFFICIAL_DAY":
            if finite_positive(preclose):
                adjustment="REFERENCE_MATCHES_PRE_CLOSE" if math.isclose(float(preclose),refclose,rel_tol=1e-7,abs_tol=1e-7) else "SAME_GENERATION_D18_REFERENCE_WITH_PRE_CLOSE_DIFFERENCE"
            else:
                adjustment="SAME_GENERATION_D18_REFERENCE_PRE_CLOSE_NOT_PROVIDED"
        clean=lambda v:float(v) if v is not None and math.isfinite(float(v)) else None
        result.append({
            "rank":row["rank"],"security":code,"name":row["name"],"model":MODEL,"probability":row["probability"],
            "decision_date":D18,"pullback_stage_k":row["pullback_stage_k"],"parent_id":row["parent_id"],"pb_id":row["pb_id"],
            "input_sha256":row["input_sha256"],"d18_selection_close":row["d18_close"],
            "d18_same_evaluation_basis_close":refclose,"d19_open":clean(bar.get("open")),
            "d19_high":clean(bar.get("high")),"d19_low":clean(bar.get("low")),
            "d19_close":clean(bar.get("close")) if final else None,
            "d19_latest_or_provisional":clean(bar.get("close")) if not final else None,
            "d19_volume":clean(volume),"d19_amount":clean(bar.get("amount")),
            "d19_pre_close":clean(preclose),"return_cc":cc,"return_oc":oc,"return_t":rt,
            "price_status":price_status,"missing_or_provisional_reason":reason,"adjustment_reference":adjustment,
            "all_ohlc_equal":oneprice,"open_execution_feasibility":"UNKNOWN",
            "tradability":"UNKNOWN_ONE_PRICE_BAR" if oneprice else "OBSERVED_VOLUME_OPEN_EXECUTION_UNCONFIRMED" if traded else "UNKNOWN_OR_NO_VOLUME",
            "source_provider":source_meta.get("price_provider",binding.get("provider","UNKNOWN")),
            "source_generation":source_meta.get("generation_id"),"source_observed_at":binding.get("observed_at"),
            "source_data_timestamp":binding.get("data_timestamp"),"source_file_recorded_at":authority_files.get(code,{}).get("file_result",{}).get("recorded_at"),"source_file_sha256":authority_files.get(code,{}).get("sha256"),"final_close_confirmed":final,
        })
    pd.DataFrame(result).to_csv(RUN/"D19_ALL_ELIGIBLE_PERFORMANCE.csv",index=False,encoding="utf-8-sig")
    pd.DataFrame(result[:20]).to_csv(RUN/"D19_TOP20_PERFORMANCE.csv",index=False,encoding="utf-8-sig")
    save(RUN/"D19_ALL_ELIGIBLE_PERFORMANCE.json",result,True)
    summaries=[]
    for label,k in (("Top5",5),("Top10",10),("Top20",20),("ALL_ELIGIBLE",len(result))):
        subset=result[:k]
        s={"group":label,"selected_count":len(subset),"denominator":len(subset)}
        for field,suffix in (("return_cc","cc"),("return_oc","oc"),("return_t","t")):
            validrows=[r for r in subset if r[field] is not None]
            values=[r[field] for r in validrows]
            s.update({f"valid_{suffix}":len(values),f"missing_{suffix}":len(subset)-len(values),f"coverage_{suffix}":len(values)/len(subset) if subset else None,
                      f"mean_{suffix}":float(np.mean(values)) if values else None,f"median_{suffix}":float(np.median(values)) if values else None,
                      f"positive_{suffix}":sum(v>0 for v in values),f"zero_{suffix}":sum(v==0 for v in values),f"negative_{suffix}":sum(v<0 for v in values),
                      f"best_{suffix}":max(validrows,key=lambda r:r[field])["security"] if validrows else None,
                      f"worst_{suffix}":min(validrows,key=lambda r:r[field])["security"] if validrows else None})
        summaries.append(s)
    index={"status":"NOT_AVAILABLE_SAME_SOURCE","security":"000300.SH"}
    if binding.get("index_code")=="000300.SH" and final:
        c18=by.get(("000300.SH",D18),{}).get("close")
        c19=by.get(("000300.SH",D19),{}).get("close")
        if finite_positive(c18) and finite_positive(c19):
            index={"status":"AVAILABLE_SAME_GENERATION","security":"000300.SH","return_cc":float(c19)/float(c18)-1}
            for s in summaries:
                s["relative_to_hs300_cc"]=s["mean_cc"]-index["return_cc"] if s["mean_cc"] is not None else None
    pd.DataFrame(summaries).to_csv(RUN/"D19_TOP_GROUP_SUMMARY.csv",index=False,encoding="utf-8-sig")
    output={"at":now(),"selection_date":D18,"evaluation_date":D19,"source_binding":identity(binding_path),
            "final_close_confirmed":final,"summaries":summaries,"index_baseline":index,
            "ranking_frozen_at":frozen["at"],"ranked_rows":len(rows),"evaluation_reader_calls":int(binding["kind"]=="V4_READER"),"accepted_day_reader_calls":sum(x["status"]=="ACCEPTED_FILE_READ" for x in json.loads((RUN/"D19_AUTHORITY_FILE_AUDIT.json").read_text())["files"]) if binding["kind"]=="V4_ACCEPTED_OFFICIAL_DAY" else 0,
            "model_calls_during_evaluation":0,"historical_pit":"UNKNOWN","true_unexposed_validation_rows":0,
            "prices_are_realized_returns":False,"pb15_labels_updated":False}
    save(RUN/"EVALUATION_SUMMARY.json",output,True)
    event("EVALUATION_COMPLETE",rows=len(rows),final_close_confirmed=final)
    return output

def selftest():
    x=tuple(float(i) for i in range(20))
    packed=struct.pack("<20d",*x)
    assert len(packed)==160 and struct.unpack("<20d",packed)==x
    ranked=[dict(security="000002.SZ",probability=0.0),dict(security="000001.SZ",probability=0.0)]
    ranked.sort(key=lambda r:(-r["probability"],r["security"]))
    assert ranked[0]["security"]=="000001.SZ"
    return {"status":"PASS","model_api":0,"model_deserialization":0,"reader_calls":0,"feature_bytes":160}

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("stage",choices=("prepare","infer","evaluate","selftest"))
    args=parser.parse_args()
    result=globals()[args.stage]()
    if result is not None:
        print(json.dumps(result,ensure_ascii=False,indent=2))
