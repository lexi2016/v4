"""Pure verification of V8 identities, signed grants, PRELAUNCH and persisted output."""
from __future__ import annotations

import base64
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path, PurePosixPath
import struct
from typing import Any
import zipfile

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

RUN_A = "aa4de242906913e5a369b93bc304bdde64ded10de77f2d3fe67bdf20203f5fa2"
SYNTHETIC = "SYNTHETIC_TEST_ONLY"
OFFICIAL = "OFFICIAL"
KEY_FIELDS = ("security", "decision_date", "rule_version", "parent_id", "pb_id", "input_sha256")
FEATURE_COLUMNS = (
    "pullback_stage_k", "d_close_to_wave_high_pct", "d_low_to_wave_high_pct",
    "max_close_dd_so_far_pct", "d_vol_over_upwave_mean",
    "pb_mean_vol_over_upwave_mean", "pb_min_vol_over_upwave_mean",
    "d_close_to_anchor_low_pct", "stage_is_early", "stage_is_extended",
)
LR_PARAMS = {"C": 0.1, "class_weight": None, "fit_intercept": True, "max_iter": 1000,
             "random_state": 0, "solver": "lbfgs", "tol": 1e-8, "warm_start": False}
BASELINE_COUNTS = {"preprocessing_fit": 3, "model_fit": 2, "model_api": 2, "failed_attempts": 1}
UNIT_REQUIREMENTS = {
    "F1_RETRY": {"preprocessing_fit": 1, "model_fit": 1, "model_api": 1},
    "FINAL_DEV": {"preprocessing_fit": 1, "model_fit": 1, "model_api": 0},
}


class Rejected(RuntimeError):
    """A request is rejected before advancing protected state."""


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def object_digest(value: Any) -> str:
    return digest(canonical(value))


def identity_digest(prepared: dict) -> str:
    return object_digest(prepared["identity"])


def rows_digest(prepared: dict) -> str:
    return object_digest(prepared["units"])


def read_json(path: Path) -> dict:
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Rejected("DUPLICATE_JSON_KEY")
            result[key] = value
        return result
    value = json.loads(path.read_bytes(), object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise Rejected("JSON_OBJECT_REQUIRED")
    return value


def timestamp(value: str) -> datetime:
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if instant.tzinfo is None:
            raise ValueError("Timezone missing")
        return instant.astimezone(timezone.utc)
    except (ValueError, AttributeError) as exc:
        raise Rejected("INVALID_TIMESTAMP") from exc


def now() -> datetime:
    return datetime.now(timezone.utc)


def require(condition: bool, code: str):
    if not condition:
        raise Rejected(code)


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts and str(path) == name


def validate_row(row: dict):
    require(all(isinstance(row.get(key), str) and row[key] for key in KEY_FIELDS), "ROW_IDENTITY_INCOMPLETE")
    values = row.get("feature_vector_10")
    require(isinstance(values, list) and len(values) == 10 and
            all(type(x) in (int, float) and math.isfinite(x) for x in values), "INVALID_80B_FEATURE_ROW")
    require(digest(struct.pack("<10d", *values)) == row["input_sha256"], "ROW_80B_SHA_MISMATCH")
    require(type(row.get("pb15_label")) is int and row["pb15_label"] in (0, 1), "ROW_LABEL_INVALID")
    k = values[0]
    require(k == int(k) and 1 <= k <= 8 and
            values[8] == int(k in (1, 2)) and values[9] == int(4 <= k <= 8), "STAGE_DUMMY_MISMATCH")


def verify_prepared(path: Path, domain: str) -> tuple[dict, str]:
    require(path.is_file() and not path.is_symlink(), "PREPARED_FILE_UNAVAILABLE")
    raw = path.read_bytes()
    prepared = read_json(path)
    require(prepared.get("scope") == domain and domain in (SYNTHETIC, OFFICIAL), "INPUT_TRUST_DOMAIN_MISMATCH")
    require(prepared.get("execution_identity_sha256") == RUN_A, "RUN_A_IDENTITY_REQUIRED")
    require(prepared.get("baseline", {}).get("counts") == BASELINE_COUNTS, "HISTORICAL_BUDGET_MISMATCH")
    units = prepared.get("units", {})
    require(set(units) == set(UNIT_REQUIREMENTS), "UNIT_INPUT_SET_MISMATCH")
    identity = prepared.get("identity", {})
    require(identity.get("feature_columns") == list(FEATURE_COLUMNS) and identity.get("row_bytes") == 80,
            "FEATURE_CONTRACT_MISMATCH")
    require(identity.get("lr_params") == LR_PARAMS and isinstance(identity.get("fold_manifest"), dict),
            "FOLD_OR_LR_CONTRACT_MISSING")
    require(identity.get("historical_budget_caps") == {
        "max_preprocessing_fit": 4, "max_model_fit": 4, "max_model_api": 3, "final_dev_predict_api": 0
    }, "HISTORICAL_CAPS_MISMATCH")
    files = prepared.get("source_files", {})
    paths = prepared.get("source_paths", {})
    require(bool(files) and set(files) == set(paths), "SOURCE_FILE_MANIFEST_REQUIRED")
    for key, expected in files.items():
        require(_safe_member(key), "SOURCE_PATH_NOT_RELATIVE")
        src = Path(paths[key])
        require(src.is_file() and digest(src.read_bytes()) == expected, "LIVE_SOURCE_SHA_MISMATCH")
    for unit, data in units.items():
        training = data.get("train_rows", [])
        holdout = data.get("holdout_rows", [])
        weights = data.get("train_weights", [])
        require(bool(training) and len(training) == len(weights), "TRAIN_ROWS_OR_WEIGHTS_MISSING")
        for row in training + holdout:
            validate_row(row)
        train_parents = {r["parent_id"] for r in training}
        require(not train_parents.intersection(r["parent_id"] for r in holdout), "PARENT_LEAKAGE")
        sums = defaultdict(float)
        for row, weight in zip(training, weights):
            require(type(weight) in (float, int) and math.isfinite(weight) and weight > 0, "TRAIN_WEIGHT_INVALID")
            sums[row["parent_id"]] += weight
        require(all(math.isclose(x, 1.0, abs_tol=1e-12) for x in sums.values()), "TRAIN_MOTHER_WEIGHT_MISMATCH")
        keys = [tuple(r[k] for k in KEY_FIELDS) for r in holdout]
        require(len(set(keys)) == len(keys), "DUPLICATE_HOLDOUT_ROW")
        if unit == "F1_RETRY":
            require(len(holdout) == prepared.get("expected_output_rows", {}).get(unit), "HOLDOUT_ROW_COUNT_MISMATCH")
            require(len({r["parent_id"] for r in holdout}) ==
                    prepared.get("expected_output_parents", {}).get(unit), "HOLDOUT_PARENT_COUNT_MISMATCH")
            if domain == OFFICIAL:
                require(len(holdout) == 9055 and len({r["parent_id"] for r in holdout}) == 1912,
                        "OFFICIAL_F1_SCALE_MISMATCH")
        else:
            require(not holdout, "FINAL_DEV_HOLDOUT_FORBIDDEN")
    return prepared, digest(raw)


def verify_authorization(envelope: dict, trust: dict, prepared: dict, prepared_sha: str,
                         authority_id: str, unit: str, prelaunch: bytes, domain: str) -> dict:
    require(set(envelope) == {"payload", "signature"}, "SIGNED_ENVELOPE_REQUIRED")
    payload = envelope["payload"]
    require(isinstance(payload, dict), "AUTH_PAYLOAD_REQUIRED")
    key = trust.get(payload.get("key_id"))
    require(isinstance(key, dict), "UNTRUSTED_SIGNING_KEY")
    require(key.get("domain") == domain and payload.get("domain") == domain, "AUTH_TRUST_DOMAIN_MISMATCH")
    require(key.get("issuer") == payload.get("issuer") and bool(key.get("issuer")) and
            key.get("subject") == payload.get("subject") and bool(key.get("subject")), "UNAUTHORIZED_SUBJECT")
    try:
        public = Ed25519PublicKey.from_public_bytes(bytes.fromhex(key["public_key_hex"]))
        public.verify(bytes.fromhex(envelope["signature"]), canonical(payload))
    except (InvalidSignature, ValueError, KeyError, TypeError) as exc:
        raise Rejected("INVALID_AUTH_SIGNATURE") from exc
    require(payload.get("schema") == "P515_V8_AUTH_V1", "AUTH_SCHEMA_MISMATCH")
    grant_id = payload.get("authorization_id")
    require(isinstance(grant_id, str) and bool(grant_id.strip()) and len(grant_id) <= 160, "EMPTY_AUTHORIZATION_ID")
    require(timestamp(payload["issued_at"]) <= timestamp(payload["not_before"]) <= now() <
            timestamp(payload["expires_at"]), "AUTH_EXPIRED_OR_NOT_EFFECTIVE")
    require(payload.get("execution_identity_sha256") == RUN_A and payload.get("authority_id") == authority_id,
            "AUTHORITY_OR_RUN_IDENTITY_MISMATCH")
    require(unit in UNIT_REQUIREMENTS and payload.get("unit") == unit, "UNIT_NOT_AUTHORIZED")
    require(payload.get("prepared_sha256") == prepared_sha and
            payload.get("identity_sha256") == identity_digest(prepared) and
            payload.get("rows_sha256") == rows_digest(prepared) and
            payload.get("source_files") == prepared["source_files"], "AUTH_INPUT_OR_SOURCE_MISMATCH")
    capabilities = payload.get("capabilities", [])
    require(("F1_ONCE" if unit == "F1_RETRY" else "FINAL_DEV_ONCE") in capabilities, "UNIT_CAPABILITY_REQUIRED")
    caps = payload.get("budget_caps", {})
    require(set(caps) == {"preprocessing_fit", "model_fit", "model_api"} and
            all(type(x) is int and 0 <= x for x in caps.values()) and
            caps["preprocessing_fit"] <= 5 and caps["model_fit"] <= 4 and caps["model_api"] <= 3,
            "AUTHORIZED_CAPS_INVALID")
    if caps["preprocessing_fit"] > 4:
        require("PREPROCESSING_CAP_5" in capabilities, "AUTH_02_CAPABILITY_REQUIRED")
    if domain == OFFICIAL:
        require(key.get("issuer") == payload.get("issuer") == "CHATGPT_MASTER", "MASTER_ISSUER_REQUIRED")
        require(unit == "F1_RETRY" and payload.get("approval_id") == "AUTH-01", "AUTH_01_F1_ONLY")
        require(payload.get("approval_contract") == "P515_CODEX_MAC_R1_SINGLE_MAC_RUN_A_RECOVERY_AUTHORITY_V1",
                "SINGLE_MAC_RECOVERY_CONTRACT_REQUIRED")
        require(caps == {"preprocessing_fit": 4, "model_fit": 4, "model_api": 3}, "AUTH_01_FIXED_CAPS_4_4_3_REQUIRED")
        require(set(capabilities) == {"F1_ONCE"}, "AUTH_02_NOT_APPROVED")
    require(digest(prelaunch) == payload.get("prelaunch_sha256"), "PRELAUNCH_ZIP_SHA_MISMATCH")
    verify_prelaunch(prelaunch, payload, prepared, prepared_sha, authority_id, domain)
    return payload


def verify_prelaunch(raw: bytes, payload: dict, prepared: dict, prepared_sha: str,
                     authority_id: str, domain: str):
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            names = package.namelist()
            required = {"manifest.json", "IDENTITY.json", "FOLDS.json"}
            required.update("sources/" + name for name in prepared["source_files"])
            require(set(names) == required and len(names) == len(required), "PRELAUNCH_FILES_MISSING_OR_DUPLICATED")
            require(all(_safe_member(name) for name in names), "UNSAFE_PRELAUNCH_MEMBER")
            require(sum(i.file_size for i in package.infolist()) <= 64 * 1024 * 1024, "PRELAUNCH_TOO_LARGE")
            require(package.testzip() is None, "PRELAUNCH_CRC_FAILED")
            manifest = json.loads(package.read("manifest.json"))
            expected = {
                "schema": "P515_V8_PRELAUNCH_V1", "scope": domain, "execution_identity_sha256": RUN_A,
                "authority_id": authority_id, "authorization_id": payload["authorization_id"],
                "prepared_sha256": prepared_sha, "identity_sha256": identity_digest(prepared),
                "rows_sha256": rows_digest(prepared), "source_files": prepared["source_files"],
            }
            require(all(manifest.get(k) == v for k, v in expected.items()), "PRELAUNCH_IDENTITY_MISMATCH")
            require(timestamp(manifest["created_at"]) <= timestamp(payload["issued_at"]) and
                    timestamp(manifest["created_at"]) < now() < timestamp(manifest["expires_at"]) <=
                    timestamp(payload["expires_at"]), "PRELAUNCH_TIME_INVALID")
            require(package.read("IDENTITY.json") == canonical(prepared["identity"]), "PRELAUNCH_IDENTITY_CONTENT_MISMATCH")
            require(package.read("FOLDS.json") == canonical(prepared["identity"]["fold_manifest"]), "PRELAUNCH_FOLD_CONTENT_MISMATCH")
            for name, expected_sha in prepared["source_files"].items():
                require(digest(package.read("sources/" + name)) == expected_sha, "PRELAUNCH_SOURCE_CONTENT_MISMATCH")
    except (zipfile.BadZipFile, UnicodeError, json.JSONDecodeError, KeyError) as exc:
        raise Rejected("PRELAUNCH_INVALID") from exc


def metrics(rows: list[dict]) -> dict:
    grouped = defaultdict(list)
    for row in rows:
        probability = max(1e-15, min(1 - 1e-15, row["p_pred"]))
        label = row["y_true"]
        grouped[row["parent_id"]].append(((row["p_pred"] - label) ** 2,
                                           -(label * math.log(probability) + (1 - label) * math.log(1 - probability))))
    per_parent = {
        key: {"rows": len(values), "brier": sum(x[0] for x in values) / len(values),
              "log_loss": sum(x[1] for x in values) / len(values)}
        for key, values in sorted(grouped.items())
    }
    require(bool(per_parent), "EMPTY_PREDICTION_METRICS")
    return {"rows": len(rows), "parents": len(per_parent), "per_parent": per_parent,
            "brier": sum(x["brier"] for x in per_parent.values()) / len(per_parent),
            "log_loss": sum(x["log_loss"] for x in per_parent.values()) / len(per_parent)}


def model_identity(model: dict) -> str:
    return object_digest({k: v for k, v in model.items() if k != "model_identity_sha256"})


def verify_outputs(directory: Path, prepared: dict, unit: str, transaction_id: str,
                   authority_id: str) -> dict:
    require(directory.is_dir() and not directory.is_symlink(), "OUTPUT_DIRECTORY_MISSING")
    required = {"model.json"} if unit == "FINAL_DEV" else {"model.json", "predictions.jsonl", "metrics.json"}
    require({p.name for p in directory.iterdir()} == required, "OUTPUT_FILE_SET_MISMATCH")
    identities = {}
    for name in required:
        path = directory / name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size > 0, "OUTPUT_MISSING_OR_EMPTY")
        raw = path.read_bytes()
        identities[name] = {"bytes": len(raw), "sha256": digest(raw)}
    model = read_json(directory / "model.json")
    expected = {
        "scope": prepared["scope"], "unit": unit, "execution_identity_sha256": RUN_A,
        "authority_id": authority_id, "transaction_id": transaction_id,
        "identity_sha256": identity_digest(prepared), "rows_sha256": rows_digest(prepared),
        "source_files": prepared["source_files"], "feature_columns": list(FEATURE_COLUMNS),
        "lr_params": LR_PARAMS, "prediction_api_calls": 0 if unit == "FINAL_DEV" else 1,
    }
    require(all(model.get(k) == v for k, v in expected.items()), "MODEL_CONTENT_IDENTITY_MISMATCH")
    require(model.get("classes") == [0, 1] and len(model.get("coefficients", [])) == 10 and
            all(type(x) in (int, float) and math.isfinite(x) for x in model["coefficients"]) and
            type(model.get("intercept")) in (int, float) and math.isfinite(model["intercept"]),
            "MODEL_WEIGHTS_MISSING_OR_INVALID")
    scaler = model.get("preprocessor", {})
    require(scaler.get("n_features") == 8, "PREPROCESSOR_DIMENSION_INVALID")
    for field in ("mean", "scale", "z_min", "z_max"):
        arr = scaler.get(field)
        require(isinstance(arr, list) and len(arr) == 8 and
                all(type(x) in (int, float) and math.isfinite(x) for x in arr), "PREPROCESSOR_CONTENT_INVALID")
    require(all(x > 0 for x in scaler["scale"]) and
            all(lo <= hi for lo, hi in zip(scaler["z_min"], scaler["z_max"])), "PREPROCESSOR_RANGE_INVALID")
    require(model.get("model_identity_sha256") == model_identity(model), "MODEL_IDENTITY_SHA_MISMATCH")
    if unit == "F1_RETRY":
        rows = [json.loads(line) for line in (directory / "predictions.jsonl").read_bytes().splitlines()]
        expected_rows = prepared["units"][unit]["holdout_rows"]
        require(len(rows) == len(expected_rows), "PREDICTION_COUNT_MISMATCH")
        seen = set()
        for row, truth in zip(rows, expected_rows):
            key = tuple(row.get(name) for name in KEY_FIELDS)
            require(key == tuple(truth[name] for name in KEY_FIELDS) and key not in seen,
                    "PREDICTION_ROW_IDENTITY_MISMATCH")
            seen.add(key)
            require(row.get("y_true") == truth["pb15_label"] and type(row.get("y_true")) is int,
                    "PREDICTION_LABEL_MISMATCH")
            require(row.get("scope") == prepared["scope"] and row.get("transaction_id") == transaction_id and
                    row.get("model_identity_sha256") == model["model_identity_sha256"], "PREDICTION_MODEL_IDENTITY_MISMATCH")
            probability = row.get("p_pred")
            require(type(probability) in (int, float) and math.isfinite(probability) and 0 <= probability <= 1,
                    "PREDICTION_PROBABILITY_INVALID")
        require(read_json(directory / "metrics.json") == metrics(rows), "PARENT_METRICS_MISMATCH")
    return {"unit": unit, "scope": prepared["scope"], "authority_id": authority_id,
            "execution_identity_sha256": RUN_A, "transaction_id": transaction_id,
            "identity_sha256": identity_digest(prepared), "rows_sha256": rows_digest(prepared),
            "model_identity_sha256": model["model_identity_sha256"], "files": identities}
