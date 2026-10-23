"""V2 publication-time reconstruction; candidate features never consume truth."""
from __future__ import annotations
import csv
import hashlib
import json
import math
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

FLAGS = dict(research_only=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
MODE = "PUBLICATION_TIME_RECONSTRUCTION"
SCHEMA = "V194_LOGISTIC_JSON_V2"
TZ = timezone(timedelta(hours=8))
EXPOSED = {"2026-10-16", "2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22"}
SOURCES = ["source_fupan", "source_stage7", "source_research"]
TECHNICAL = ["tech_192", "B1", "B2", "B3", "BREAKOUT", "BREAKOUT_DOJI", "M2_MINUS", "M2_PLUS", "SINGLE_NEEDLE", "THREE_QUARTER_YIN", "BRICK_FANBAO"]
STATES = ("hit", "confirmed_absent", "unknown")
FIT_COUNTS = {"synthetic_fit_entered":0, "synthetic_fit_returned":0,
              "real_fit_entered":0, "real_fit_returned":0}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def save(path, obj):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as f:
        json.dump(obj, f, ensure_ascii=False, sort_keys=True, allow_nan=False, indent=2)
        f.write("\n")


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def day(value):
    parsed = date.fromisoformat(value)
    require(parsed.isoformat() == value, "DATE_NOT_ISO")
    return parsed


def instant(value):
    parsed = datetime.fromisoformat(value)
    require(parsed.tzinfo is not None, "TIMEZONE_REQUIRED")
    return parsed


def decision(target):
    return datetime.combine(day(target), datetime.min.time(), TZ).replace(hour=9, minute=25)


def number(value):
    require(value is not None and value != "", "UNKNOWN_TECHNICAL_FEATURE")
    x = float(value)
    require(math.isfinite(x), "NONFINITE_FEATURE")
    return x


def validate_manifest(manifest, synthetic=False):
    require(all(manifest.get(k) is v for k,v in FLAGS.items()), "UNSAFE_FLAGS")
    if manifest.get("schema") != "V194_DATASET_MANIFEST_V2":
        require(manifest.get("historical_availability_bound") is True, "V1_CERTIFIED_PIT_REQUIRED")
        raise ValueError("V2_SCHEMA_REQUIRED")
    require(manifest.get("mode") == MODE, "RECONSTRUCTION_MODE_REQUIRED")
    require(manifest.get("historical_availability_bound") is False, "NO_FALSE_PIT_CERTIFICATION")
    require(manifest.get("semantic_ready") is True, "CANNOT_CONFIRM:semantic_ready")
    require(manifest.get("complete_ten_buy_points") is True, "COMPLETE_TEN_BUY_POINTS_REQUIRED")
    require(manifest.get("synthetic_fixture", False) is synthetic, "SYNTHETIC_MODE_MISMATCH")
    technical = manifest["technical_features"]
    require(technical == TECHNICAL, "TECHNICAL_192_PLUS_TEN_REQUIRED")
    require(manifest["source_state_columns"] == SOURCES, "SOURCE_ORDER_DRIFT")
    if not synthetic:
        require(manifest.get("label_definition") and manifest.get("universe_scope"), "LABEL_UNIVERSE_REQUIRED")


def feature_names(config, arm):
    require(arm in ("baseline", "candidate"), "UNKNOWN_ARM")
    names = list(config["technical_features"])
    require(names == TECHNICAL, "TECHNICAL_192_PLUS_TEN_REQUIRED")
    if arm == "candidate":
        names += [s+"__"+v for s in SOURCES for v in STATES]
        names += [s+"__technical_resonance" for s in SOURCES]
    require(len(set(names)) == len(names), "FEATURE_COLLISION")
    return names


def feature_values(row, config, arm):
    technical = [number(row.get(k)) for k in config["technical_features"]]
    require(all(v in (0,1) for v in technical), "TECHNICAL_TRIGGER_NOT_BINARY")
    states = [row.get(s) for s in SOURCES]
    require(all(s in STATES for s in states), "SOURCE_STATE_UNKNOWN_FORMAT")
    source = [float(s == v) for s in states for v in STATES]
    resonance = [float(s == "hit" and any(technical)) for s in states]
    return technical if arm == "baseline" else technical+source+resonance


def validate_rows(rows, config, manifest, calendar, *, synthetic=False, labelled=True):
    validate_manifest(manifest, synthetic)
    require(config == {"technical_features":manifest["technical_features"], "top_n":50, "seed":194}, "FROZEN_CONFIG_DRIFT")
    by_date = {r["target_date"]:r for r in calendar}
    require(len(by_date) == len(calendar), "DUPLICATE_CALENDAR_DATE")
    seen = set()
    for row in rows:
        key = (row["target_date"],row["code"])
        require(key not in seen, "DUPLICATE_TARGET_CODE"); seen.add(key)
        require(key[0] in by_date and row["signal_date"] == by_date[key[0]]["signal_date"], "SIGNAL_PREVIOUS_TRADE_DATE")
        require(day(row["signal_date"]) < day(key[0]), "SIGNAL_NOT_BEFORE_TARGET")
        require(bool(key[1]) and (not synthetic or key[1].startswith("SYNTH")), "CODE_INVALID")
        require(instant(row["decision_at"]) == decision(key[0]), "DECISION_NOT_TARGET_0925")
        require(instant(row["available_at"]) <= decision(key[0]), "FEATURE_AFTER_DECISION")
        feature_values(row, config, "candidate")
        require(any(number(row[k]) for k in config["technical_features"]) or any(row[s]=="hit" for s in SOURCES), "ROW_OUTSIDE_OR_UNION")
        if labelled:
            end, available = instant(row["label_end_at"]), instant(row["label_available_at"])
            require(end == decision(key[0]).replace(hour=15, minute=0), "LABEL_NOT_TARGET_CLOSE")
            require(available >= end, "LABEL_AVAILABLE_BEFORE_END")
            require(number(row["label"]) in (0,1), "BINARY_LABEL_REQUIRED")
    require(bool(rows), "EMPTY_DATASET")


def join_truth(candidates, truth):
    by_key = {(r["target_date"],r["code"]):r for r in truth}
    require(len(by_key) == len(truth), "DUPLICATE_TRUTH_KEY")
    result = []
    for row in candidates:
        key = (row["target_date"],row["code"])
        require(key in by_key, "MISSING_CANDIDATE_TRUTH")
        require(not {"label","label_end_at","label_available_at","return"} & row.keys(), "TRUTH_IN_FEATURE_VIEW")
        result.append({**row, **{k:by_key[key][k] for k in ("label","label_end_at","label_available_at")}})
    return result


def make_splits(eligible_dates):
    dates = sorted(set(eligible_dates)-EXPOSED)
    require(len(dates) >= 20, "MINIMUM_20_ELIGIBLE_TARGET_DATES")
    initial = len(dates)//2
    return [dict(id=f"fold_{i//5+1:02}", train_target_dates=dates[:initial+i], evaluation_target_dates=dates[initial+i:initial+i+5]) for i in range(0,len(dates)-initial,5)]


def split_rows(rows, split):
    td, ed = set(split["train_target_dates"]), set(split["evaluation_target_dates"])
    require(td and ed and max(td) < min(ed), "CHRONOLOGICAL_SPLIT_REQUIRED")
    require(not (td|ed)&EXPOSED, "EXPOSED_TARGET_DATE_FORBIDDEN")
    cutoff = decision(min(ed))
    train = [r for r in rows if r["target_date"] in td and instant(r["label_available_at"]) < cutoff]
    evaluation = [r for r in rows if r["target_date"] in ed]
    require(train and {int(float(r["label"])) for r in train} == {0,1}, "TRAIN_REQUIRES_TWO_CLASSES")
    return train, evaluation


def fit_model(train, config, arm, *, synthetic, training_cutoff_at):
    import numpy as np
    import sklearn
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    require(train and not {r["target_date"] for r in train}&EXPOSED, "EXPOSED_IN_FIT")
    require(all(instant(r["label_available_at"]) < instant(training_cutoff_at) for r in train), "TRAIN_LABEL_NOT_AVAILABLE")
    x = np.asarray([feature_values(r,config,arm) for r in train], dtype=float)
    y = np.asarray([int(float(r["label"])) for r in train])
    scaler = StandardScaler().fit(x)
    estimator = LogisticRegression(C=1.0, penalty="l2", solver="lbfgs", random_state=194, max_iter=1000, tol=1e-8)
    prefix = "synthetic" if synthetic else "real"
    FIT_COUNTS[prefix+"_fit_entered"] += 1
    estimator.fit(scaler.transform(x),y)
    FIT_COUNTS[prefix+"_fit_returned"] += 1
    require(int(estimator.n_iter_[0]) < 1000, "FIT_NOT_CONVERGED")
    return dict(schema=SCHEMA,mode=MODE,arm=arm,features=feature_names(config,arm),mean=scaler.mean_.tolist(),scale=scaler.scale_.tolist(),coef=estimator.coef_[0].tolist(),intercept=float(estimator.intercept_[0]),config=config,training_target_dates=sorted({r["target_date"] for r in train}),training_label_available_at_max=max(instant(r["label_available_at"]) for r in train).isoformat(),training_information_cutoff=training_cutoff_at,trained_asof=datetime.now(timezone.utc).isoformat(),versions={"numpy":np.__version__,"sklearn":sklearn.__version__},evidence_level="ENGINEERING_CANARY_ONLY" if synthetic else "DIRECTION_ONLY",**FLAGS)


def predict(model, rows, *, historical_oof=False):
    require(model.get("schema")==SCHEMA and model.get("mode")==MODE, "MODEL_SCHEMA_MODE")
    require(all(model.get(k) is v for k,v in FLAGS.items()), "UNSAFE_MODEL")
    config, arm = model["config"],model["arm"]
    require(model["features"]==feature_names(config,arm), "MODEL_FEATURE_ORDER_DRIFT")
    n=len(model["features"])
    require(all(len(model[k])==n for k in ("mean","scale","coef")), "MODEL_SHAPE")
    require(all(number(s)>0 for s in model["scale"]), "MODEL_SCALE")
    result=[]
    for row in rows:
        if not historical_oof:
            at=instant(row["decision_at"])
            require(at>instant(model["trained_asof"]) and at>instant(model["training_label_available_at_max"]), "PREDICTION_BEFORE_TRAINING_CUTOFF")
        else:
            require(instant(row["decision_at"]) >= instant(model["training_information_cutoff"])
                    and instant(row["decision_at"]) > instant(model["training_label_available_at_max"]), "OOF_BEFORE_TRAIN_LABEL_CUTOFF")
        p=score_features(model,row)
        result.append(dict(target_date=row["target_date"],code=row["code"],score=p))
    return result


def score_features(model,row):
    """Pure numerical kernel; caller supplies the explicit prediction-time gate."""
    x=feature_values(row,model["config"],model["arm"])
    z=number(model["intercept"])+sum((v-number(m))/number(s)*number(c) for v,m,s,c in zip(x,model["mean"],model["scale"],model["coef"]))
    return 1/(1+math.exp(-z)) if z>=0 else math.exp(z)/(1+math.exp(z))


def top50(predictions):
    from collections import defaultdict
    grouped=defaultdict(list);seen=set()
    for row in predictions:
        key=(row["target_date"],row["code"])
        require(key not in seen,"DUPLICATE_PREDICTION_KEY");seen.add(key)
        grouped[row["target_date"]].append(row)
    return [{**r,"rank":i} for d in sorted(grouped) for i,r in enumerate(sorted(grouped[d],key=lambda r:(-r["score"],r["code"]))[:50],1)]


def run_fold(rows, config, split, directory, *, synthetic=False):
    train,evaluation=split_rows(rows,split)
    directory=Path(directory);require(not directory.exists(),"OUTPUT_ALREADY_EXISTS")
    training_cutoff_at=decision(min(split["evaluation_target_dates"])).isoformat()
    save(directory/"split.json",split)
    save(directory/"train_keys.json",[{k:r[k] for k in ("target_date","code","label_available_at")} for r in train])
    for arm in ("baseline","candidate"):
        model=fit_model(train,config,arm,synthetic=synthetic,training_cutoff_at=training_cutoff_at)
        save(directory/(arm+"_model.json"),model)
        predictions=predict(model,evaluation,historical_oof=True)
        require(predictions==predict(load(directory/(arm+"_model.json")),evaluation,historical_oof=True),"SERIALIZATION_PARITY")
        save(directory/(arm+"_predictions.json"),predictions)
        save(directory/(arm+"_top50.json"),top50(predictions))
    receipt=dict(split=split,fit_counts=dict(FIT_COUNTS),training_rows=len(train),evaluation_rows=len(evaluation),status="ENGINEERING_CANARY_ONLY" if synthetic else "DIRECTION_ONLY",**FLAGS)
    save(directory/"FOLD_RESULT.json",receipt)
    return receipt
