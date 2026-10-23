"""Registered V2 canary -> cached expanding OOF -> final refit -> batch prediction."""
from __future__ import annotations
import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
import model194 as m
from report194 import BOOTSTRAP, evaluate, write_report


def bound_dataset(cfg, *, prediction=False):
    path=Path(cfg["input_manifest"])
    m.require(m.sha(path)==cfg["input_manifest_sha256"],"MANIFEST_DRIFT")
    manifest=m.load(path);m.validate_manifest(manifest)
    tables={}
    required=("candidates","calendar") if prediction else ("candidates","truth","calendar")
    identities={"manifest_sha256":m.sha(path)}
    for key in required:
        item=manifest["files"][key];p=Path(item["path"])
        if not p.is_absolute():p=path.parent/p
        m.require(m.sha(p)==item["sha256"],"FILE_DRIFT:"+key)
        tables[key]=m.read_csv(p);identities[key+"_sha256"]=item["sha256"]
    config=dict(technical_features=manifest["technical_features"],top_n=50,seed=194)
    m.validate_rows(tables["candidates"],config,manifest,tables["calendar"],labelled=False)
    rows=tables["candidates"] if prediction else eligible_training_view(tables["candidates"],tables["truth"],tables["calendar"])
    m.validate_rows(rows,config,manifest,tables["calendar"],labelled=not prediction)
    identities["model_code_sha256"]=m.sha(Path(__file__).with_name("model194.py"))
    identities["report_code_sha256"]=m.sha(Path(__file__).with_name("report194.py"))
    identities["runner_code_sha256"]=m.sha(__file__)
    return manifest,tables,rows,config,identities


def eligible_training_view(candidates, truth, calendar):
    """Role selection precedes truth join; candidate rows themselves stay intact."""
    roles={r["target_date"]:r["cohort_role"] for r in calendar}
    m.require(len(roles)==len(calendar),"DUPLICATE_CALENDAR_DATE")
    m.require(all(r["target_date"] in roles for r in candidates),"CANDIDATE_ROLE_MISSING")
    labelled=[r for r in candidates if roles[r["target_date"]]=="eligible"]
    return m.join_truth(labelled,truth)


def prepare(cfg):
    manifest,tables,rows,config,identity=bound_dataset(cfg)
    eligible=sorted(set(manifest["eligible_target_dates"])-m.EXPOSED)
    splits=m.make_splits(eligible)
    by_date={r["target_date"]:r for r in tables["calendar"]}
    m.require(set(eligible)<=by_date.keys(),"ELIGIBLE_CALENDAR_MISSING")
    m.require(set(r["target_date"] for r in rows)<=by_date.keys(),"ROW_DATE_OUTSIDE_CALENDAR")
    # An empty candidate day remains eligible; missing prices/truth never becomes zero.
    truth_by_date={d:[r for r in tables["truth"] if r["target_date"]==d] for d in eligible}
    for d in eligible:
        m.require(truth_by_date[d],"TRUTH_MISSING_DATE:"+d)
        m.require(sum(int(m.number(r["label"])) for r in truth_by_date[d])==int(by_date[d]["truth_positive_denominator"]),"TRUTH_DENOMINATOR_DRIFT")
    asof=m.instant(cfg["evaluation_asof"])
    m.require(all(m.instant(r["label_available_at"])<=asof for r in rows if r["target_date"] in eligible),"EVAL_LABEL_IMMATURE")
    for split in splits:m.split_rows(rows,split)
    frozen=dict(schema="V194_RUN_FREEZE_V2",identity=identity,model_config=config,splits=splits,
                eligible_target_dates=eligible,evaluation_asof=cfg["evaluation_asof"],bootstrap=BOOTSTRAP,
                excluded_target_dates=sorted(m.EXPOSED & set(by_date)),**m.FLAGS)
    return manifest,tables,rows,config,frozen


def freeze_file(output, frozen, *, create=False):
    path=output/"RUN_FREEZE.json"
    if create:
        m.require(not path.exists(),"FREEZE_ALREADY_EXISTS");m.save(path,frozen)
    else:m.require(m.load(path)==frozen,"RUN_FREEZE_DRIFT")


def seal_fold(directory, identity):
    directory=Path(directory)
    binding=dict(identity=identity,files={p.name:m.sha(p) for p in sorted(directory.iterdir()) if p.is_file()})
    m.save(directory/"FOLD_MANIFEST.json",binding)


def reuse_fold(directory, identity):
    binding=m.load(directory/"FOLD_MANIFEST.json")
    m.require(binding["identity"]==identity,"CACHED_FOLD_INPUT_CODE_DRIFT")
    for name,h in binding["files"].items():m.require(m.sha(directory/name)==h,"CACHED_FOLD_OUTPUT_DRIFT")
    return m.load(directory/"FOLD_RESULT.json")


def execute_stage(cfg, stage, checkpoint):
    output=Path(cfg["output_dir"])
    if stage=="predict":
        manifest,tables,rows,config,identity=bound_dataset(cfg,prediction=True)
        model_path=Path(cfg["model_path"])
        m.require(m.sha(model_path)==cfg["model_sha256"],"MODEL_DRIFT")
        model=m.load(model_path)
        m.require(model["evidence_level"]!="ENGINEERING_CANARY_ONLY","SYNTHETIC_MODEL_FOR_REAL_PREDICTION")
        m.require(model["config"]==config,"PREDICT_FEATURE_CONFIG_DRIFT")
        predictions=m.predict(model,rows)
        m.save(output/"FUTURE_TOP50.json",m.top50(predictions))
        result=dict(status="RESEARCH_PREDICTION_ONLY",input_identity=identity,prediction_rows=len(predictions),fit_counts=dict(m.FIT_COUNTS),**m.FLAGS)
        m.save(output/"PREDICTION_RESULT.json",result);return result,output/"PREDICTION_RESULT.json"
    manifest,tables,rows,config,frozen=prepare(cfg)
    freeze_file(output,frozen,create=stage=="canary")
    if stage=="canary":
        split=frozen["splits"][0];start=time.monotonic()
        result=m.run_fold(rows,config,split,output/split["id"])
        seal_fold(output/split["id"],frozen["identity"])
        result.update(elapsed_seconds=time.monotonic()-start,role="REAL_FIRST_FOLD_CANARY_REUSABLE")
        m.save(output/"CANARY_RESULT.json",result)
        checkpoint("CANARY_FOLD_COMPLETE",output/"CANARY_RESULT.json")
        return result,output/"CANARY_RESULT.json"
    if stage=="oof":
        predictions={"baseline":[],"candidate":[]};reused=[]
        for split in frozen["splits"]:
            folder=output/split["id"]
            if folder.exists():reuse_fold(folder,frozen["identity"]);reused.append(split["id"])
            else:
                m.run_fold(rows,config,split,folder);seal_fold(folder,frozen["identity"])
                checkpoint(split["id"].upper()+"_COMPLETE",folder/"FOLD_RESULT.json")
            for arm in predictions:predictions[arm]+=m.load(folder/(arm+"_top50.json"))
        dates=[d for s in frozen["splits"] for d in s["evaluation_target_dates"]]
        result=evaluate(dates,predictions["baseline"],predictions["candidate"],tables["truth"],tables["calendar"])
        coverage=dict(eligible_dates=frozen["eligible_target_dates"],excluded_exposed_dates=frozen["excluded_target_dates"],
                      input_exclusions=manifest.get("exclusions",[]),failed_folds=[],reused_folds=reused,
                      empty_candidate_dates=[d for d in dates if not any(r["target_date"]==d for r in rows)])
        write_report(output,result,coverage)
        for arm,picks in predictions.items():m.save(output/(arm+"_OOF_TOP50.json"),picks)
        result["fit_counts"]=dict(m.FIT_COUNTS);m.save(output/"OOF_RESULT.json",result)
        return result,output/"OOF_RESULT.json"
    m.require(stage=="refit","UNKNOWN_STAGE")
    m.require((output/"OOF_RESULT.json").exists(),"OOF_EVALUATION_REQUIRED_BEFORE_REFIT")
    cutoff=m.instant(cfg["refit_asof"])
    m.require(cutoff<=datetime.now(timezone.utc),"REFIT_ASOF_IN_FUTURE")
    train=[r for r in rows if r["target_date"] in frozen["eligible_target_dates"] and m.instant(r["label_available_at"])<cutoff]
    m.require({r["target_date"] for r in train}=={r["target_date"] for r in rows if r["target_date"] in frozen["eligible_target_dates"]},"REFIT_ALL_ELIGIBLE_LABELS_REQUIRED")
    for arm in ("baseline","candidate"):
        model=m.fit_model(train,config,arm,synthetic=False,training_cutoff_at=cfg["refit_asof"])
        path=output/"final"/(arm+"_model.json");m.save(path,model)
        restored=m.load(path)
        m.require(model==restored,"REFIT_JSON_ROUNDTRIP")
        m.require([m.score_features(model,r) for r in train[:32]]==[m.score_features(restored,r) for r in train[:32]],"REFIT_PREDICTION_ROUNDTRIP")
    m.save(output/"final/train_keys.json",[{k:r[k] for k in ("target_date","code","label_available_at")} for r in train])
    result=dict(status="DIRECTION_ONLY",mode=m.MODE,training_rows=len(train),training_target_dates=sorted({r["target_date"] for r in train}),
                fit_counts=dict(m.FIT_COUNTS),future_prediction_status="NOT_RUN_FUTURE_INPUT_NOT_SUPPLIED",**m.FLAGS)
    m.save(output/"FINAL_RESULT.json",result);return result,output/"FINAL_RESULT.json"


def main():
    parser=argparse.ArgumentParser();parser.add_argument("execution_contract");args=parser.parse_args()
    from registry_bridge import register
    cp=Path(args.execution_contract);contract=m.load(cp);stage=contract["run_stage"]
    register(cp,"RUN_STARTED",stage.upper()+"_START",decision="RUNNING_RECONSTRUCTION_"+stage.upper())
    try:
        path=Path(contract["run_config_path"])
        m.require(m.sha(path)==contract["run_config_sha256"],"RUN_CONFIG_DRIFT")
        cfg=m.load(path)
        def checkpoint(name,path):
            register(cp,"CHECKPOINT",name,[path],metrics=dict(m.FIT_COUNTS),decision="DIRECTION_ONLY_CHECKPOINT")
        result,artifact=execute_stage(cfg,stage,checkpoint)
        register(cp,"TERMINAL",stage.upper()+"_COMPLETE",[artifact],metrics=dict(m.FIT_COUNTS),decision=result["status"])
    except Exception as exc:
        register(cp,"TERMINAL",stage.upper()+"_FAILED",metrics=dict(m.FIT_COUNTS),decision="FAILED:"+type(exc).__name__+":"+str(exc)[:250])
        raise


if __name__=="__main__":
    for var in ("OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS"):os.environ[var]="2"
    main()
