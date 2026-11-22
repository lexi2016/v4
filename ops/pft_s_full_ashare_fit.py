"""Fixed PFT-S full-A-share fit, prediction lock, and post-lock scoring.

`fit` never opens OOS labels. It writes and seals raw OOS/external predictions.
`score` verifies that seal before it opens any evaluation labels.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sys
import gzip
from typing import Any, Iterable

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from ops.pft_s_full_ashare_features import FEATURES  # noqa: E402

BATCH = "PFT_S_FULL_ASHARE_SCALEUP_20261122_V1"
FLAGS = {"RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
THRESHOLD = 0.5
MODEL_CONFIGS = {
    "GEMINI_R2_FIXED_LR": {"kind": "logistic_regression", "C": 1.0, "class_weight": "balanced", "random_state": 42, "max_iter": 1000,
                           "imputation": "median", "scaling": "StandardScaler"},
    "GEMINI_R2_SHALLOW_RF": {"kind": "random_forest", "n_estimators": 100, "max_depth": 3, "min_samples_leaf": 2,
                             "class_weight": "balanced", "random_state": 42, "n_jobs": 1, "imputation": "median"},
}
EXTERNAL_FILES = {
    "JOINT54_VAL18": "external_joint54_val18_frozen.csv",
    "KB11_FROZEN_ORIGINAL_D": "external_kb11_frozen.csv",
}


class FitError(RuntimeError):
    """A fail-closed fit, prediction-lock, or scoring error."""


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_text(path: Path, value: str) -> None:
    temp = path.with_name(path.name + ".tmp")
    with temp.open("x", encoding="utf-8", newline="") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FitError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return value


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file() or path.is_symlink():
        raise FitError(f"CSV_REQUIRED:{path}")
    raw = path.read_bytes()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig", errors="strict"), newline=""))
    if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise FitError(f"CSV_HEADER_INVALID:{path.name}")
    rows = list(reader)
    if any(None in row for row in rows):
        raise FitError(f"CSV_ROW_WIDTH_INVALID:{path.name}")
    return rows


def _metrics(labels: list[int], probabilities: list[float], decisions: list[int]) -> dict[str, Any]:
    if not (len(labels) == len(probabilities) == len(decisions)):
        raise FitError("METRIC_INPUT_LENGTH_MISMATCH")
    tp = sum(y == 1 and p == 1 for y, p in zip(labels, decisions))
    fp = sum(y == 0 and p == 1 for y, p in zip(labels, decisions))
    tn = sum(y == 0 and p == 0 for y, p in zip(labels, decisions))
    fn = sum(y == 1 and p == 0 for y, p in zip(labels, decisions))
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    specificity = tn / (tn + fp) if tn + fp else None
    f1_denominator = 2 * tp + fp + fn
    f1 = (2 * tp / f1_denominator) if f1_denominator else None
    balanced_accuracy = (recall + specificity) / 2.0 if recall is not None and specificity is not None else None
    auc = _auc(labels, probabilities)
    return {"rows": len(labels), "TP": tp, "FP": fp, "TN": tn, "FN": fn,
            "precision": precision, "recall": recall, "specificity": specificity,
            "F1": f1, "balanced_accuracy": balanced_accuracy, "AUC": auc,
            "threshold": THRESHOLD}


def _auc(labels: list[int], scores: list[float]) -> float | None:
    positives = sum(label == 1 for label in labels)
    negatives = sum(label == 0 for label in labels)
    if positives == 0 or negatives == 0:
        return None
    ordered = sorted(zip(scores, labels), key=lambda row: row[0])
    rank_sum = 0.0
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][0] == ordered[index][0]:
            end += 1
        average_rank = (index + 1 + end) / 2.0
        rank_sum += average_rank * sum(label == 1 for _, label in ordered[index:end])
        index = end
    return (rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)


def _grouped_metrics(rows: list[dict[str, Any]], group_field: str) -> dict[str, Any]:
    values = sorted({str(row.get(group_field) or "UNKNOWN") for row in rows})
    result: dict[str, Any] = {}
    for value in values:
        subset = [row for row in rows if str(row.get(group_field) or "UNKNOWN") == value and row.get("truth") in (0, 1)]
        if not subset:
            result[value] = {"rows": 0, "raw": None, "gated": None}
            continue
        labels = [int(row["truth"]) for row in subset]
        raw_p = [float(row["probability"]) for row in subset]
        raw_d = [int(row["decision_raw"]) for row in subset]
        gated_p = [float(row["probability_gated"]) for row in subset]
        gated_d = [int(row["decision_gated"]) for row in subset]
        result[value] = {"rows": len(subset), "raw": _metrics(labels, raw_p, raw_d),
                         "gated": _metrics(labels, gated_p, gated_d)}
    return result


def _fixed_models() -> dict[str, Any]:
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.ensemble import RandomForestClassifier

    lr = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
        ("classifier", LogisticRegression(C=1.0, class_weight="balanced", random_state=42, max_iter=1000)),
    ])
    rf = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("classifier", RandomForestClassifier(n_estimators=100, max_depth=3, min_samples_leaf=2,
                                               class_weight="balanced", random_state=42, n_jobs=1)),
    ])
    return {"GEMINI_R2_FIXED_LR": lr, "GEMINI_R2_SHALLOW_RF": rf}


def _matrix(path: Path, *, pandas: Any) -> Any:
    frame = pandas.read_csv(path)
    if list(frame.columns) != list(FEATURES):
        raise FitError(f"FEATURE_MATRIX_SCHEMA_MISMATCH:{path.name}")
    if frame.empty:
        raise FitError(f"FEATURE_MATRIX_EMPTY:{path.name}")
    if any(not pandas.api.types.is_numeric_dtype(frame[name]) for name in FEATURES):
        raise FitError(f"FEATURE_MATRIX_NON_NUMERIC:{path.name}")
    values = frame.to_numpy(dtype=float)
    if __import__("numpy").isinf(values).any():
        raise FitError(f"FEATURE_MATRIX_INFINITY:{path.name}")
    return frame


def _probabilities(model: Any, matrix: Any) -> list[float]:
    classes = list(model.classes_)
    if 1 not in classes:
        raise FitError("FITTED_MODEL_POSITIVE_CLASS_MISSING")
    index = classes.index(1)
    return [float(value) for value in model.predict_proba(matrix)[:, index]]


def _read_external_identities(artifact_root: Path) -> tuple[dict[str, list[dict[str, str]]], dict[str, str]]:
    cases: dict[str, list[dict[str, str]]] = {}
    hashes: dict[str, str] = {}
    for exam, filename in EXTERNAL_FILES.items():
        path = artifact_root / filename
        rows = _read_csv(path)
        if not rows or not {"security_id", "D"}.issubset(rows[0]):
            raise FitError(f"EXTERNAL_IDENTITY_COLUMNS_MISSING:{filename}")
        # The fit stage accesses only case identity. Label, stage, tactic,
        # source narrative and ruling columns stay unopened by model code.
        cases[exam] = [{"case_id": row.get("case_id", f"{exam}-{index:04d}"),
                        "security_id": row["security_id"].strip().upper(), "D": row["D"].strip()}
                       for index, row in enumerate(rows)]
        hashes[filename] = _sha_file(path)
    return cases, hashes


def _oos_gate_decisions(prepared_dir: Path, expected_rows: int) -> list[dict[str, Any]]:
    """Recompute the fixed inference gate from case OHLCV only, without labels."""
    import pandas as pd
    from ops.pft_s_full_ashare_features import feature_frame

    path = prepared_dir / "oos_case_ohlcv.csv.gz"
    histories: dict[str, list[dict[str, Any]]] = {}
    case_order: list[str] = []
    case_days: dict[str, str] = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"episode_id", "D", "trade_date", "open", "high", "low", "close", "vol", "bbi", "zge_white_line", "zge_yellow_line"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise FitError("OOS_CASE_OHLCV_COLUMNS_MISSING")
        for row in reader:
            episode = row["episode_id"]
            if episode not in histories:
                histories[episode] = []
                case_order.append(episode)
                case_days[episode] = row["D"]
            elif case_days[episode] != row["D"]:
                raise FitError(f"OOS_CASE_D_CONFLICT:{episode}")
            if row["trade_date"] > row["D"]:
                raise FitError(f"OOS_POST_D_BAR:{episode}:{row['trade_date']}")
            histories[episode].append({key: row[key] for key in required if key not in {"episode_id", "D"}})
    if len(case_order) != expected_rows:
        raise FitError(f"OOS_CASE_OHLCV_EPISODE_COUNT_MISMATCH:{len(case_order)}!={expected_rows}")
    result: list[dict[str, Any]] = []
    for index, episode in enumerate(case_order):
        rows = sorted(histories[episode], key=lambda row: row["trade_date"])
        if not rows or rows[-1]["trade_date"] != case_days[episode]:
            raise FitError(f"OOS_CASE_EXACT_D_MISSING:{episode}")
        frame = feature_frame(pd.DataFrame(rows[-30:]))
        final = frame.iloc[-1]
        if str(final["trade_date"]) != case_days[episode]:
            raise FitError(f"OOS_GATE_FEATURE_D_MISMATCH:{episode}")
        result.append({"feature_row": index, "episode_id": episode, "D": case_days[episode],
                       "g1_wy_pass": final.get("g1_wy_pass"),
                       "g2_s26_reject": final.get("g2_s26_reject"),
                       "gate_pass": final.get("gate_pass"),
                       "gate_reasons": final.get("gate_reasons")})
    return result


def _external_features(artifact_root: Path, data_root: Path, cases: dict[str, list[dict[str, str]]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    from ops import pft_s_first_baseline as baseline
    from ops import research_panel_logical as logical_reader
    from ops.pft_s_full_ashare import (
        ASOF_DATE, START_DATE, _code, _date_value, _deduplicate_alias_history,
        _normalize_panel_rows, _validate_inputs, _valid_d,
    )

    inputs = _validate_inputs(artifact_root)
    canonical_codes: dict[str, set[str]] = {}
    normalized_cases: dict[str, list[dict[str, str]]] = {}
    for exam, rows in cases.items():
        normalized_cases[exam] = []
        for row in rows:
            code = _code(row["security_id"])
            canonical = inputs["raw_to_canonical"].get(code, inputs["aliases"].get(code, code))
            day = row["D"].strip().replace("-", "")
            if len(day) != 8 or not day.isdigit() or day < START_DATE or day > ASOF_DATE:
                raise FitError(f"EXTERNAL_D_INVALID:{row['case_id']}:{row['D']}")
            date(int(day[:4]), int(day[4:6]), int(day[6:8]))
            normalized_cases[exam].append({**row, "security_id": code, "canonical_security_id": canonical, "D": day})
            canonical_codes.setdefault(canonical, set()).update(
                code_value for code_value, canonical_value in inputs["raw_to_canonical"].items()
                if canonical_value == canonical
            )
    max_day_by_canonical = {canonical: max(row["D"] for rows in normalized_cases.values() for row in rows
                                           if row["canonical_security_id"] == canonical)
                            for canonical in canonical_codes}
    history_by_canonical: dict[str, dict[str, list[dict[str, Any]]]] = {}
    with baseline.bind_current_panels(data_root) as (panel_path, source, recheck):
        frozen_source = inputs["scope"]["authoritative_v4"]
        identity = source["identity"]
        a_basis = identity.get("a_market_basis") or {}
        if (identity.get("generation_id") != frozen_source.get("generation")
                or str(identity.get("asof_date", "")).replace("-", "")[:8] != str(frozen_source.get("asof"))
                or a_basis.get("price_basis") != frozen_source.get("price_basis")
                or a_basis.get("volume_basis") != frozen_source.get("volume_basis")
                or (source.get("backtest") or {}).get("panel_sha256") != frozen_source.get("backtest_sha256")):
            raise FitError("EXTERNAL_SOURCE_IDENTITY_MISMATCH")
        schema = logical_reader.parquet.read_schema(panel_path)
        from ops.pft_s_full_ashare import _panel_columns
        mapping, columns = _panel_columns(schema)
        date_field, code_field = mapping["trade_date"], mapping["ts_code"]
        for canonical, codes in canonical_codes.items():
            code_list = sorted(codes)
            # Case count is tiny; per-security exact-D upper bounds avoid
            # reading any rows later than that security's final frozen case.
            filters = [[
                (date_field, ">=", _date_value(schema, date_field, START_DATE)),
                (date_field, "<=", _date_value(schema, date_field, max_day_by_canonical[canonical])),
                (code_field, "in", code_list),
            ]]
            table = logical_reader.parquet.read_table(panel_path, columns=columns, filters=filters, use_threads=True)
            history_by_canonical[canonical] = _normalize_panel_rows(table, mapping, inputs["raw_to_canonical"]).get(canonical, {})
        recheck()
    features: dict[str, list[dict[str, Any]]] = {}
    for exam, rows in normalized_cases.items():
        features[exam] = []
        for row in rows:
            by_code = history_by_canonical.get(row["canonical_security_id"], {})
            history = _deduplicate_alias_history(by_code, inputs["crosswalk_aliases"])
            prefix = [item for item in history if item["trade_date"] <= row["D"]]
            if not prefix or prefix[-1]["trade_date"] != row["D"]:
                raise FitError(f"EXTERNAL_EXACT_D_ROW_MISSING:{row['case_id']}:{row['D']}")
            if not _valid_d(prefix[-1]):
                raise FitError(f"EXTERNAL_D_ROW_INVALID:{row['case_id']}:{row['D']}")
            frame = __import__("pandas").DataFrame(prefix)
            features_frame = __import__("ops.pft_s_full_ashare_features", fromlist=["feature_frame"]).feature_frame(frame)
            feature_row = features_frame.iloc[-1]
            if str(feature_row["trade_date"]) != row["D"]:
                raise FitError(f"EXTERNAL_FEATURE_D_MISMATCH:{row['case_id']}")
            features[exam].append({"feature_row": len(features[exam]), **row,
                                   **{name: feature_row.get(name) for name in FEATURES},
                                   "g1_wy_pass": feature_row.get("g1_wy_pass"),
                                   "g2_s26_reject": feature_row.get("g2_s26_reject"),
                                   "gate_pass": feature_row.get("gate_pass"),
                                   "gate_reasons": feature_row.get("gate_reasons")})
    return features, source


def _save_prediction_outputs(stage: Path, oos_probabilities: dict[str, list[float]],
                             external: dict[str, list[dict[str, Any]]],
                             external_probs: dict[str, dict[str, list[float]]],
                             oos_gates: list[dict[str, Any]]) -> dict[str, str]:
    files: dict[str, str] = {}
    oos_len = len(next(iter(oos_probabilities.values())))
    oos_columns = ["feature_row", "episode_id", "D", "g1_wy_pass", "g2_s26_reject", "gate_pass", "gate_reasons"]
    for name in MODEL_CONFIGS:
        slug = "lr" if name == "GEMINI_R2_FIXED_LR" else "rf"
        oos_columns.extend([f"p_{slug}", f"decision_{slug}_raw",
                            f"p_{slug}_gated", f"decision_{slug}_gated"])
    with (stage / "oos_predictions.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=oos_columns, lineterminator="\n")
        writer.writeheader()
        for index in range(oos_len):
            row = {"feature_row": index, **oos_gates[index]}
            for name in MODEL_CONFIGS:
                slug = "lr" if name == "GEMINI_R2_FIXED_LR" else "rf"
                probability = oos_probabilities[name][index]
                gate_value = _nullable_float(oos_gates[index].get("gate_pass"))
                gated_probability = probability if gate_value == 1.0 else 0.0
                row[f"p_{slug}"] = probability
                row[f"decision_{slug}_raw"] = int(probability >= THRESHOLD)
                row[f"p_{slug}_gated"] = gated_probability
                row[f"decision_{slug}_gated"] = int(gated_probability >= THRESHOLD)
            writer.writerow(row)
    files["oos_predictions.csv"] = _sha_file(stage / "oos_predictions.csv")
    gate_path = stage / "oos_gate_decisions.csv"
    with gate_path.open("w", encoding="utf-8", newline="") as stream:
        gate_columns = ["feature_row", "episode_id", "D", "g1_wy_pass", "g2_s26_reject", "gate_pass", "gate_reasons"]
        writer = csv.DictWriter(stream, fieldnames=gate_columns, lineterminator="\n")
        writer.writeheader()
        for index, gate in enumerate(oos_gates):
            writer.writerow({"feature_row": index, **{key: gate.get(key, "") for key in gate_columns if key != "feature_row"}})
    files["oos_gate_decisions.csv"] = _sha_file(gate_path)

    for exam, rows in external.items():
        slug_name = "joint54" if exam == "JOINT54_VAL18" else "kb11"
        key_path = stage / f"{slug_name}_identity.csv"
        key_columns = ["feature_row", "case_id", "security_id", "canonical_security_id", "D",
                       "g1_wy_pass", "g2_s26_reject", "gate_pass", "gate_reasons"]
        with key_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=key_columns, lineterminator="\n")
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key, "") for key in key_columns})
        matrix_path = stage / f"{slug_name}_features.csv"
        with matrix_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(FEATURES), lineterminator="\n")
            writer.writeheader()
            for row in rows:
                writer.writerow({name: _csv_value(row.get(name)) for name in FEATURES})
        files[key_path.name] = _sha_file(key_path)
        files[matrix_path.name] = _sha_file(matrix_path)

    external_prediction_rows: list[dict[str, Any]] = []
    for exam, rows in external.items():
        for index, case in enumerate(rows):
            record: dict[str, Any] = {"exam": exam, "feature_row": index, "case_id": case["case_id"]}
            for name in MODEL_CONFIGS:
                slug = "lr" if name == "GEMINI_R2_FIXED_LR" else "rf"
                probability = external_probs[name][exam][index]
                gate_value = _nullable_float(case.get("gate_pass"))
                gated_probability = probability if gate_value == 1.0 else 0.0
                record[f"p_{slug}"] = probability
                record[f"decision_{slug}_raw"] = int(probability >= THRESHOLD)
                record[f"p_{slug}_gated"] = gated_probability
                record[f"decision_{slug}_gated"] = int(gated_probability >= THRESHOLD)
                record[f"gate_pass"] = _csv_value(case.get("gate_pass"))
                record[f"gate_reasons"] = str(case.get("gate_reasons") or "")
            external_prediction_rows.append(record)
    external_prediction_path = stage / "external_predictions.csv"
    ext_columns = ["exam", "feature_row", "case_id", "p_lr", "decision_lr_raw", "p_lr_gated", "decision_lr_gated",
                   "p_rf", "decision_rf_raw", "p_rf_gated", "decision_rf_gated", "gate_pass", "gate_reasons"]
    with external_prediction_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=ext_columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(external_prediction_rows)
    files[external_prediction_path.name] = _sha_file(external_prediction_path)
    return files


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    try:
        if not math.isfinite(float(value)):
            return ""
    except (TypeError, ValueError, OverflowError):
        pass
    if hasattr(value, "item"):
        value = value.item()
    return value


def fit_and_lock(*, prepared_dir: Path, artifact_root: Path, data_root: Path, output_dir: Path) -> dict[str, Any]:
    import numpy as np
    import pandas as pd
    import joblib

    prepared_dir = prepared_dir.expanduser().resolve(strict=True)
    artifact_root = artifact_root.expanduser().resolve(strict=True)
    data_root = data_root.expanduser().resolve(strict=True)
    output_dir = output_dir.expanduser().absolute()
    if output_dir.exists() or output_dir.is_symlink():
        raise FitError(f"FIT_OUTPUT_ALREADY_EXISTS:{output_dir}")
    if output_dir.parent.resolve(strict=True) != prepared_dir.parent.resolve(strict=True):
        raise FitError("FIT_OUTPUT_MUST_BE_PREPARED_SIBLING")
    stage = output_dir.with_name(output_dir.name + ".partial")
    if stage.exists() or stage.is_symlink():
        raise FitError(f"FIT_PARTIAL_ALREADY_EXISTS:{stage}")
    prepared_identity = _read_json(prepared_dir / "manifest.json")
    if prepared_identity.get("batch") != BATCH or prepared_identity.get("feature_columns") != list(FEATURES):
        raise FitError("PREPARED_IDENTITY_OR_FEATURE_SCHEMA_MISMATCH")
    train_manifest_path = prepared_dir / "train_manifest.csv"
    train_matrix_path = prepared_dir / "train_features.csv"
    oos_matrix_path = prepared_dir / "oos_features.csv"
    prepared_output_hashes = prepared_identity.get("outputs_sha256") or {}
    for filename in ("train_manifest.csv", "train_features.csv", "oos_features.csv", "oos_case_ohlcv.csv.gz"):
        expected = prepared_output_hashes.get(filename)
        path = prepared_dir / filename
        if not expected or not path.is_file() or _sha_file(path) != expected:
            raise FitError(f"PREPARED_INPUT_SHA_MISMATCH:{filename}")
    train_manifest = pd.DataFrame(_read_csv(train_manifest_path))
    train_matrix = _matrix(train_matrix_path, pandas=pd)
    oos_matrix = _matrix(oos_matrix_path, pandas=pd)
    if len(train_manifest) != len(train_matrix) or len(train_manifest) != 450:
        raise FitError("TRAIN_ROW_COUNT_MISMATCH")
    if len(oos_matrix) < 100 or len(oos_matrix) > 150:
        raise FitError("OOS_FEATURE_ROW_COUNT_OUTSIDE_FROZEN_RANGE")
    if list(train_manifest["split"].unique()) != ["TRAIN"]:
        raise FitError("TRAIN_MANIFEST_SPLIT_MISMATCH")
    labels = train_manifest["label"].str.upper().map({"TRUE": 1, "FALSE": 0})
    if labels.isna().any() or labels.value_counts().to_dict() != {0: 270, 1: 180}:
        raise FitError("TRAIN_LABEL_COUNTS_MISMATCH")
    if train_manifest["canonical_security_id"].duplicated().any() or train_manifest["episode_id"].duplicated().any():
        raise FitError("TRAIN_CANONICAL_OR_EPISODE_DUPLICATE")
    for filename, expected in (("train_manifest.csv", prepared_output_hashes["train_manifest.csv"]),
                               ("train_features.csv", prepared_output_hashes["train_features.csv"]),
                               ("oos_features.csv", prepared_output_hashes["oos_features.csv"])):
        if _sha_file(prepared_dir / filename) != expected:
            raise FitError(f"PREPARED_INPUT_CHANGED_DURING_READ:{filename}")

    # Read only external case identifiers here; external labels are opened by
    # `score` only after the OOS prediction lock is written.
    external_cases, external_identity_hashes = _read_external_identities(artifact_root)
    external_features, external_source = _external_features(artifact_root, data_root, external_cases)
    external_matrices = {exam: pd.DataFrame(rows, columns=None).loc[:, list(FEATURES)] for exam, rows in external_features.items()}
    if sum(len(rows) for rows in external_features.values()) != 29:
        raise FitError("EXTERNAL_IDENTITY_ROW_COUNT_MISMATCH")
    oos_gates = _oos_gate_decisions(prepared_dir, len(oos_matrix))

    stage.mkdir(parents=False, exist_ok=False)
    fit_progress = {"schema": "pft_s_full_ashare_fit_progress.v1", "status": "RUNNING",
                    "requested_fit_count": 2, "successful_fit_count": 0,
                    "completed_models": [], "flags": FLAGS}
    _write_text(stage / "fit_progress.json", json.dumps(fit_progress, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    model_defs = _fixed_models()
    model_artifacts: dict[str, str] = {}
    oos_probs: dict[str, list[float]] = {}
    external_probs: dict[str, dict[str, list[float]]] = {}
    actual_fit_count = 0
    for name, model in model_defs.items():
        model.fit(train_matrix, labels.to_numpy(dtype=int))
        actual_fit_count += 1
        fit_progress.update(successful_fit_count=actual_fit_count,
                            completed_models=[*fit_progress["completed_models"], name],
                            last_completed_model=name)
        _write_text(stage / "fit_progress.json", json.dumps(fit_progress, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        oos_probs[name] = _probabilities(model, oos_matrix)
        for exam, matrix in external_matrices.items():
            external_probs.setdefault(name, {})[exam] = _probabilities(model, matrix)
        model_path = stage / ("model_lr.joblib" if name == "GEMINI_R2_FIXED_LR" else "model_rf.joblib")
        joblib.dump(model, model_path, compress=3)
        model_artifacts[name] = _sha_file(model_path)

    # One reload per model verifies serialized artifacts against the original
    # locked probabilities; this does not fit or alter either estimator.
    for name, model_path_name in (("GEMINI_R2_FIXED_LR", "model_lr.joblib"), ("GEMINI_R2_SHALLOW_RF", "model_rf.joblib")):
        reloaded = joblib.load(stage / model_path_name)
        if not np.allclose(_probabilities(reloaded, oos_matrix), oos_probs[name], rtol=0.0, atol=1e-15):
            raise FitError(f"MODEL_RELOAD_PROBABILITY_MISMATCH:{name}")

    prediction_hashes = _save_prediction_outputs(stage, oos_probs, external_features, external_probs, oos_gates)
    lock = {
        "schema": "pft_s_full_ashare_prediction_lock.v1",
        "batch": BATCH,
        "locked_at_utc": datetime.now(timezone.utc).isoformat(),
        "prepared_manifest_sha256": _sha_file(prepared_dir / "manifest.json"),
        "train_manifest_sha256": _sha_file(train_manifest_path),
        "train_features_sha256": _sha_file(train_matrix_path),
        "oos_features_sha256": _sha_file(oos_matrix_path),
        "oos_case_ohlcv_sha256": _sha_file(prepared_dir / "oos_case_ohlcv.csv.gz"),
        "external_identity_sha256": external_identity_hashes,
        "external_source": external_source,
        "external_prediction_inputs_sha256": prediction_hashes,
        "model_configs": MODEL_CONFIGS,
        "model_artifact_sha256": model_artifacts,
        "oos_label_file_read": False,
        "threshold": THRESHOLD,
        "feature_columns": list(FEATURES),
        "actual_fit_counts": {"S": actual_fit_count, "B": 0},
        "flags": FLAGS,
    }
    _write_text(stage / "prediction_lock.json", json.dumps(lock, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    receipt = {"schema": "pft_s_full_ashare_fit_receipt.v1", "batch": BATCH,
               "actual_fit_counts": {"S": actual_fit_count, "B": 0},
               "train_rows": len(train_matrix), "oos_prediction_rows": len(oos_matrix),
               "external_prediction_rows": {exam: len(rows) for exam, rows in external_features.items()},
               "prediction_lock_sha256": _sha_file(stage / "prediction_lock.json"),
               "predictions_sha256": prediction_hashes,
               "model_artifact_sha256": model_artifacts, "flags": FLAGS}
    fit_progress.update(status="FIT_COMPLETE", successful_fit_count=actual_fit_count,
                        completed_models=list(model_defs), prediction_lock_sha256=receipt["prediction_lock_sha256"])
    _write_text(stage / "fit_progress.json", json.dumps(fit_progress, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    _write_text(stage / "fit_receipt.json", json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    stage.replace(output_dir)
    return receipt


def _verify_lock(prepared_dir: Path, fit_dir: Path) -> tuple[dict[str, Any], dict[str, list[dict[str, str]]]]:
    lock = _read_json(fit_dir / "prediction_lock.json")
    if lock.get("schema") != "pft_s_full_ashare_prediction_lock.v1" or lock.get("batch") != BATCH:
        raise FitError("PREDICTION_LOCK_SCHEMA_MISMATCH")
    if lock.get("oos_label_file_read") is not False or lock.get("actual_fit_counts") != {"S": 2, "B": 0}:
        raise FitError("PREDICTION_LOCK_FIT_BOUNDARY_INVALID")
    if _sha_file(prepared_dir / "manifest.json") != lock.get("prepared_manifest_sha256"):
        raise FitError("PREPARED_MANIFEST_CHANGED_AFTER_FIT")
    if _sha_file(prepared_dir / "oos_features.csv") != lock.get("oos_features_sha256"):
        raise FitError("OOS_FEATURES_CHANGED_AFTER_FIT")
    if _sha_file(prepared_dir / "oos_case_ohlcv.csv.gz") != lock.get("oos_case_ohlcv_sha256"):
        raise FitError("OOS_CASE_OHLCV_CHANGED_AFTER_FIT")
    prediction_files = lock.get("external_prediction_inputs_sha256") or {}
    for filename, digest in prediction_files.items():
        path = fit_dir / filename
        if not path.is_file() or _sha_file(path) != digest:
            raise FitError(f"LOCKED_PREDICTION_FILE_CHANGED:{filename}")
    model_paths = {"GEMINI_R2_FIXED_LR": "model_lr.joblib", "GEMINI_R2_SHALLOW_RF": "model_rf.joblib"}
    for model, filename in model_paths.items():
        path = fit_dir / filename
        if not path.is_file() or _sha_file(path) != (lock.get("model_artifact_sha256") or {}).get(model):
            raise FitError(f"LOCKED_MODEL_ARTIFACT_CHANGED:{model}")
    return lock, {}


def score_locked(*, prepared_dir: Path, artifact_root: Path, fit_dir: Path, output_dir: Path) -> dict[str, Any]:
    import pandas as pd

    prepared_dir = prepared_dir.expanduser().resolve(strict=True)
    artifact_root = artifact_root.expanduser().resolve(strict=True)
    fit_dir = fit_dir.expanduser().resolve(strict=True)
    output_dir = output_dir.expanduser().absolute()
    if output_dir.exists() or output_dir.is_symlink():
        raise FitError(f"SCORE_OUTPUT_ALREADY_EXISTS:{output_dir}")
    if output_dir.parent.resolve(strict=True) != prepared_dir.parent.resolve(strict=True):
        raise FitError("SCORE_OUTPUT_MUST_BE_PREPARED_SIBLING")
    lock, _ = _verify_lock(prepared_dir, fit_dir)

    # The label read occurs only after _verify_lock confirms the persisted OOS
    # feature SHA and the prediction artifacts are unchanged.
    prepared_identity = _read_json(prepared_dir / "manifest.json")
    oos_label_path = prepared_dir / "oos_labels_and_evidence.csv"
    expected_oos_label_sha = (prepared_identity.get("outputs_sha256") or {}).get(oos_label_path.name)
    if not expected_oos_label_sha or _sha_file(oos_label_path) != expected_oos_label_sha:
        raise FitError("OOS_LABEL_FILE_SHA_MISMATCH_AFTER_LOCK")
    oos_rows = _read_csv(oos_label_path)
    oos_pred = pd.DataFrame(_read_csv(fit_dir / "oos_predictions.csv"))
    if len(oos_rows) != len(oos_pred) or [int(row["feature_row"]) for row in oos_rows] != list(range(len(oos_rows))):
        raise FitError("OOS_CASE_PREDICTION_ALIGNMENT_MISMATCH")
    gate_rows = _read_csv(fit_dir / "oos_gate_decisions.csv")
    if len(gate_rows) != len(oos_rows) or [int(row["feature_row"]) for row in gate_rows] != list(range(len(gate_rows))):
        raise FitError("OOS_GATE_PREDICTION_ALIGNMENT_MISMATCH")
    records: list[dict[str, Any]] = []
    for index, (case, prediction) in enumerate(zip(oos_rows, oos_pred.to_dict("records"))):
        try:
            truth = {"TRUE": 1, "FALSE": 0}[case["label"].strip().upper()]
        except KeyError as exc:
            raise FitError(f"OOS_LABEL_NOT_BINARY:{index}") from exc
        gate_row = gate_rows[index]
        if (gate_row.get("episode_id") != prediction.get("episode_id")
                or gate_row.get("D") != prediction.get("D")
                or gate_row.get("gate_pass") != prediction.get("gate_pass")
                or gate_row.get("gate_reasons") != prediction.get("gate_reasons")):
            raise FitError(f"OOS_GATE_SIDECAR_PREDICTION_MISMATCH:{index}")
        gate_value = _nullable_float(prediction.get("gate_pass"))
        gate = None if gate_value is None else gate_value == 1.0
        for model_name, slug in (("GEMINI_R2_FIXED_LR", "lr"), ("GEMINI_R2_SHALLOW_RF", "rf")):
            probability = float(prediction[f"p_{slug}"])
            raw_decision = int(probability >= THRESHOLD)
            gated_probability = float(prediction[f"p_{slug}_gated"])
            gated_decision = int(prediction[f"decision_{slug}_gated"])
            if raw_decision != int(prediction[f"decision_{slug}_raw"]) or gated_decision != int(gated_probability >= THRESHOLD):
                raise FitError(f"OOS_LOCKED_DECISION_THRESHOLD_MISMATCH:{model_name}:{index}")
            records.append({**case, "model": model_name, "truth": truth, "probability": probability,
                            "decision_raw": raw_decision, "probability_gated": gated_probability,
                            "decision_gated": gated_decision, "gate_admit": gate,
                            "gate_reasons": prediction.get("gate_reasons") or ""})
    reports = _exam_report(records)

    external_labels: dict[str, list[dict[str, str]]] = {}
    expected_identity_sha = lock.get("external_identity_sha256") or {}
    for exam, filename in EXTERNAL_FILES.items():
        path = artifact_root / filename
        if _sha_file(path) != expected_identity_sha.get(filename):
            raise FitError(f"EXTERNAL_LABEL_INPUT_CHANGED:{filename}")
        external_labels[exam] = _read_csv(path)
    external_predictions = _read_csv(fit_dir / "external_predictions.csv")
    external_identity = {exam: _read_csv(fit_dir / ("joint54_identity.csv" if exam == "JOINT54_VAL18" else "kb11_identity.csv")) for exam in EXTERNAL_FILES}
    external_report_rows: list[dict[str, Any]] = []
    for exam in EXTERNAL_FILES:
        labels = external_labels[exam]
        identities = external_identity[exam]
        predictions = [row for row in external_predictions if row["exam"] == exam]
        if not (len(labels) == len(identities) == len(predictions)):
            raise FitError(f"EXTERNAL_CASE_PREDICTION_ALIGNMENT_MISMATCH:{exam}")
        for index, (label_row, identity_row, pred_row) in enumerate(zip(labels, identities, predictions)):
            if (identity_row.get("case_id") != label_row.get("case_id")
                    or identity_row.get("security_id") != label_row.get("security_id", "").upper()
                    or identity_row.get("D", "").replace("-", "") != label_row.get("D", "").replace("-", "")):
                raise FitError(f"EXTERNAL_CASE_IDENTITY_CHANGED:{exam}:{index}")
            raw_label = (label_row.get("overall_s_label") or "").strip().upper()
            truth = {"TRUE": 1, "FALSE": 0}.get(raw_label)
            if (identity_row.get("gate_pass") != pred_row.get("gate_pass")
                    or identity_row.get("gate_reasons") != pred_row.get("gate_reasons")):
                raise FitError(f"EXTERNAL_GATE_PREDICTION_MISMATCH:{exam}:{index}")
            gate_value = _nullable_float(pred_row.get("gate_pass"))
            gate = None if gate_value is None else gate_value == 1.0
            for slug, model in (("lr", "GEMINI_R2_FIXED_LR"), ("rf", "GEMINI_R2_SHALLOW_RF")):
                probability = float(pred_row[f"p_{slug}"])
                gated_probability = float(pred_row[f"p_{slug}_gated"])
                raw_decision = int(pred_row[f"decision_{slug}_raw"])
                gated_decision = int(pred_row[f"decision_{slug}_gated"])
                if raw_decision != int(probability >= THRESHOLD) or gated_decision != int(gated_probability >= THRESHOLD):
                    raise FitError(f"EXTERNAL_LOCKED_DECISION_THRESHOLD_MISMATCH:{exam}:{model}:{index}")
                external_report_rows.append({"exam": exam, "case_id": identity_row["case_id"],
                    "security_id": identity_row["security_id"], "D": identity_row["D"],
                    "label": raw_label, "truth": truth,
                    "tactic": label_row.get("tactic") or label_row.get("main_tactic_ref") or "",
                    "subtype": label_row.get("finding") or label_row.get("main_tactic_ref") or label_row.get("tactic") or "",
                    "stage": label_row.get("phase") or label_row.get("stage_ref") or "",
                    "model": model, "probability": probability,
                    "decision_raw": raw_decision,
                    "probability_gated": gated_probability,
                    "decision_gated": gated_decision,
                    "gate_admit": gate, "gate_reasons": pred_row.get("gate_reasons") or ""})
    external_reports = {}
    for exam in EXTERNAL_FILES:
        exam_rows = [row for row in external_report_rows if row["exam"] == exam]
        known_count = len({row["case_id"] for row in exam_rows if row.get("truth") in (0, 1)})
        expected_known = 16 if exam == "JOINT54_VAL18" else 11
        if known_count != expected_known:
            raise FitError(f"EXTERNAL_DECIDED_CASE_COUNT_MISMATCH:{exam}:{known_count}!={expected_known}")
        external_reports[exam] = _exam_report(exam_rows)

    output_dir.mkdir(parents=False, exist_ok=False)
    casewise_path = output_dir / "casewise_predictions_and_errors.csv"
    columns = list(dict.fromkeys(key for row in [*records, *external_report_rows] for key in row))
    _write_rows(casewise_path, columns, [*records, *external_report_rows])
    casewise_sha = _sha_file(casewise_path)
    result = {"schema": "pft_s_full_ashare_evaluation.v1", "batch": BATCH,
              "prediction_lock_sha256": _sha_file(fit_dir / "prediction_lock.json"),
              "threshold": THRESHOLD, "oos": reports, "external": external_reports,
              "flags": FLAGS,
              "notes": ["Raw and gated results are reported separately.",
                        "Gated probability is zero when G1/G2 rejects; unknown gates are not admitted.",
                        "This report reads OOS labels only after matching the sealed prediction lock."],
              "casewise_sha256": casewise_sha}
    _write_text(output_dir / "evaluation.json", json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return result


def _nullable_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _exam_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {"models": {}}
    for model in MODEL_CONFIGS:
        subset = [row for row in rows if row.get("model") == model and row.get("truth") in (0, 1)]
        labels = [int(row["truth"]) for row in subset]
        result["models"][model] = {
            "known_labels": len(subset),
            "unknown_label_rows": sum(row.get("truth") is None for row in rows if row.get("model") == model),
            "gate_unknown_rows": sum(row.get("gate_admit") is None for row in rows if row.get("model") == model),
            "raw": _metrics(labels, [float(row["probability"]) for row in subset], [int(row["decision_raw"]) for row in subset]),
            "gated": _metrics(labels, [float(row["probability_gated"]) for row in subset], [int(row["decision_gated"]) for row in subset]),
            "by_stage": _grouped_metrics(subset, "stage"),
            "by_tactic_family": _grouped_metrics(subset, "tactic"),
            "by_subtype": _grouped_metrics(subset, "subtype"),
            "error_cases": [{"case_id": row.get("episode_id", row.get("case_id")),
                             "security_id": row.get("canonical_security_id", row.get("security_id")),
                             "D": row.get("D"), "truth": row.get("truth"),
                             "raw_decision": row.get("decision_raw"), "gated_decision": row.get("decision_gated"),
                             "gate_reasons": row.get("gate_reasons")}
                            for row in subset if row["decision_raw"] != row["truth"] or row["decision_gated"] != row["truth"]],
        }
    return result


def _write_rows(path: Path, columns: list[str], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows([{key: _csv_value(value) for key, value in row.items()} for row in rows])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run fixed PFT-S fits and score only after a prediction lock")
    subs = parser.add_subparsers(dest="command", required=True)
    fit_parser = subs.add_parser("fit")
    fit_parser.add_argument("--prepared-dir", type=Path, required=True)
    fit_parser.add_argument("--artifact-root", type=Path, required=True)
    fit_parser.add_argument("--data-root", type=Path, required=True)
    fit_parser.add_argument("--output-dir", type=Path, required=True)
    score_parser = subs.add_parser("score")
    score_parser.add_argument("--prepared-dir", type=Path, required=True)
    score_parser.add_argument("--artifact-root", type=Path, required=True)
    score_parser.add_argument("--fit-dir", type=Path, required=True)
    score_parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "fit":
            result = fit_and_lock(prepared_dir=args.prepared_dir, artifact_root=args.artifact_root,
                                  data_root=args.data_root, output_dir=args.output_dir)
        else:
            result = score_locked(prepared_dir=args.prepared_dir, artifact_root=args.artifact_root,
                                  fit_dir=args.fit_dir, output_dir=args.output_dir)
    except Exception as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps({"status": "FIT_LOCKED" if args.command == "fit" else "SCORED", **result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
