"""Synthetic-only fixture utilities for independent governance tests."""
from __future__ import annotations

import base64
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from zipfile import ZipFile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .validation import FEATURE_COLUMNS, LR_PARAMS, RUN_A, SYNTHETIC, canonical, digest, identity_digest, rows_digest

ISSUER = "CODEX_MAC_SYNTHETIC_FIXTURE"
SUBJECT = "TEST_P515_R1_RECOVERY"
KEY_ID = "ephemeral-synthetic-ed25519"
CAPS = {"preprocessing_fit": 5, "model_fit": 4, "model_api": 3}
ORIGINAL_CAPS = {"max_model_fit": 4, "max_preprocessing_fit": 4, "max_model_api": 3, "final_dev_predict_api": 0}


def write_json(path, contents):
    Path(path).write_bytes(canonical(contents))


def row(index, parent, when):
    k = index % 8 + 1
    vals = [float(k), -0.01 * index, -0.02 * index, 0.16, 0.71, 0.68, 0.56, 0.04,
            float(k in (1, 2)), float(k >= 4)]
    return {"security": f"FIXTURE_{index:02d}", "decision_date": when, "rule_version": SYNTHETIC,
            "parent_id": parent, "pb_id": f"PB-{index}", "pb15_label": index % 2,
            "pb15_mature_date": when, "stage_bucket": "SYNTHETIC",
            "input_sha256": sha256(struct.pack("<10d", *vals)).hexdigest(), "feature_vector_10": vals}


def create_fixture(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    source = root / "SYNTHETIC_SOURCE.txt"
    source.write_text(SYNTHETIC + "\n", encoding="utf-8")
    train = [row(0, "train-p0", "2000-01-01"), row(1, "train-p1", "2000-01-02")]
    holdout = [row(2, "hold-p0", "2000-03-02"), row(3, "hold-p0", "2000-03-03"), row(4, "hold-p1", "2000-03-04")]
    file_map = {"SYNTHETIC_SOURCE.txt": digest(source.read_bytes())}
    historic_units = {
        "F1": {"state": "FAILED_ERROR", "identity": RUN_A, "failed_stage": "PREPROC_FIT"},
        "F2": {"state": "COMMITTED", "identity": RUN_A, "rows": 9503, "sha256": "a" * 64},
        "F3": {"state": "COMMITTED", "identity": RUN_A, "rows": 5250, "sha256": "b" * 64},
    }
    prepared = {
        "scope": SYNTHETIC, "execution_identity_sha256": RUN_A,
        "baseline": {
            "execution_identity_sha256": RUN_A, "events": 14, "start_tokens": 7,
            "counts": {"preprocessing_fit": 3, "model_fit": 2, "model_api": 2, "failed_attempts": 1},
            "historical_units": historic_units, "historical_files": {"SYNTHETIC_LEDGER": {"sha256": "a" * 64, "bytes": 1}},
            "raw_historic_predictions": 14753, "archive_sha256": "c" * 64, "original_prelaunch_sha256": "d" * 64,
        },
        "identity": {
            "scope": SYNTHETIC, "execution_identity_sha256": RUN_A,
            "entrypoint": "research.p515_recovery_v8.cli",
            "feature_columns": list(FEATURE_COLUMNS), "row_bytes": 80, "matrix_rows": len(train + holdout),
            "matrix_sha256": digest(b"".join(struct.pack("<10d", *r["feature_vector_10"]) for r in train + holdout)),
            "fold_manifest": {"F1": {"train_count": 2, "holdout_count": 3}, "F2": {"historic": True},
                              "F3": {"historic": True}, "FINAL_DEV": {"holdout_count": 0}},
            "lr_params": LR_PARAMS, "historical_budget_caps": ORIGINAL_CAPS,
            "six_zip_sha256": {role: digest((SYNTHETIC + role).encode()) for role in
                               ("zip", "candidate_rows", "native_lifecycle", "native_daily", "screen_bars", "original_recovery")},
        },
        "units": {"F1_RETRY": {"train_rows": train, "train_weights": [1.0, 1.0], "holdout_rows": holdout},
                  "FINAL_DEV": {"train_rows": train + holdout, "train_weights": [1.0, 1.0, 0.5, 0.5, 1.0], "holdout_rows": []}},
        "source_paths": {"SYNTHETIC_SOURCE.txt": str(source.absolute())}, "source_files": file_map,
        "expected_output_rows": {"F1_RETRY": 3}, "expected_output_parents": {"F1_RETRY": 2},
    }
    prepared["identity"]["fold_manifest_sha256"] = digest(canonical(prepared["identity"]["fold_manifest"]))
    prepared["identity"]["v8_source_and_dependency_sha256"] = file_map
    ppath = root / "PREPARED_SYNTHETIC.json"
    write_json(ppath, prepared)
    key = Ed25519PrivateKey.generate()
    trust = {KEY_ID: {"domain": SYNTHETIC, "issuer": ISSUER, "subject": SUBJECT,
                      "public_key_hex": key.public_key().public_bytes_raw().hex()}}
    return ppath, prepared, key, trust


def signed_bundle(prepared_path, prepared, key, authority_id, unit="F1_RETRY", authid="TEST-AUTH-001",
                  caps=None, override=None, corrupt=None, deadline=None):
    clock = datetime.now(timezone.utc)
    deadline = deadline or (clock + timedelta(minutes=30))
    manifest = {
        "schema": "P515_V8_PRELAUNCH_V1", "scope": SYNTHETIC, "execution_identity_sha256": RUN_A,
        "authority_id": authority_id, "authorization_id": authid,
        "prepared_sha256": digest(prepared_path.read_bytes()), "identity_sha256": identity_digest(prepared),
        "rows_sha256": rows_digest(prepared), "source_files": prepared["source_files"],
        "created_at": (clock - timedelta(minutes=3)).isoformat(), "expires_at": deadline.isoformat(),
    }
    z = io.BytesIO()
    with ZipFile(z, "w") as archive:
        archive.writestr("manifest.json", canonical(manifest))
        archive.writestr("IDENTITY.json", canonical(prepared["identity"]) if corrupt != "IDENTITY" else b"{}")
        archive.writestr("FOLDS.json", canonical(prepared["identity"]["fold_manifest"]) if corrupt != "FOLDS" else b"{}")
        for entry, path in prepared["source_paths"].items():
            if corrupt != "MISSING_SOURCE":
                archive.writestr(f"sources/{entry}", Path(path).read_bytes() if corrupt != "SOURCE" else b"SYNTHETIC_CORRUPT")
    caps = CAPS.copy() if caps is None else dict(caps)
    cap = "FINAL_DEV_ONCE" if unit == "FINAL_DEV" else "F1_ONCE"
    payload = {
        "schema": "P515_V8_AUTH_V1", "authorization_id": authid, "issuer": ISSUER, "subject": SUBJECT, "key_id": KEY_ID,
        "domain": SYNTHETIC, "issued_at": (clock - timedelta(seconds=100)).isoformat(),
        "not_before": (clock - timedelta(seconds=90)).isoformat(), "expires_at": (deadline + timedelta(seconds=1)).isoformat(),
        "execution_identity_sha256": RUN_A, "authority_id": authority_id, "unit": unit,
        "capabilities": [cap] + (["PREPROCESSING_CAP_5"] if caps["preprocessing_fit"] > 4 else []),
        "budget_caps": caps, "prepared_sha256": manifest["prepared_sha256"], "identity_sha256": manifest["identity_sha256"],
        "rows_sha256": manifest["rows_sha256"], "source_files": manifest["source_files"],
        "prelaunch_sha256": digest(z.getvalue()), **(override or {}),
    }
    signed = {"payload": payload, "signature": key.sign(canonical(payload)).hex()}
    return signed, z.getvalue()


def reserve_data(auth, package, unit="F1_RETRY", mode="SYNTHETIC_EXECUTION"):
    return {"envelope": auth, "prelaunch_b64": base64.b64encode(package).decode("ascii"), "unit": unit, "mode": mode}


def wait_server(anchor, proc):
    from .authority import AuthorityClient
    from .validation import Rejected
    client = AuthorityClient(anchor)
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        try:
            return client, client.request("check")
        except (OSError, Rejected):
            if proc.poll() is not None:
                raise RuntimeError(f"authority exited {proc.returncode}") from None
            time.sleep(0.03)
    raise TimeoutError("no initial authority response")


def start_server(anchor, stream):
    snippet = ("from pathlib import Path; from research.p515_recovery_v8.authority import serve; "
               "import sys; serve(Path(sys.argv[1]))")
    return subprocess.Popen([sys.executable, "-c", snippet, str(anchor)], stdout=stream, stderr=stream)


def child_process(anchor, data_path, home, gate=None):
    argv = [sys.executable, "-m", "research.p515_recovery_v8.test_v8_fixtures", str(anchor), str(data_path)]
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2]) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    if gate is not None:
        env["P515_V8_CONTEST_GATE"] = str(gate)
        env["P515_V8_WRITE_READY"] = str(gate.parent)
    return subprocess.Popen(argv, cwd=home, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)


def run_worker(anchor, data_path):
    from .authority import AuthorityClient
    client = AuthorityClient(anchor)
    data = json.loads(Path(data_path).read_bytes())
    gate = os.environ.get("P515_V8_CONTEST_GATE")
    ready = os.environ.get("P515_V8_WRITE_READY")
    if ready:
        (Path(ready) / f"ready-{os.getpid()}").write_text(SYNTHETIC)
    if gate:
        print(f"READY {os.getpid()}", file=sys.stderr, flush=True)
        deadline = time.monotonic() + 45
        while not Path(gate).exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("Waiting for fixture concurrency barrier")
            time.sleep(0.03)
    start = datetime.now(timezone.utc).isoformat()
    message = {"pid": os.getpid(), "workdir": os.getcwd(), "started": start, "scope": SYNTHETIC}
    try:
        reserved = client.request("reserve", **data)
        message["reserve"] = {k: v for k, v in reserved.items() if k != "lease_token"}
        message["execute"] = client.request("execute", transaction_id=reserved["transaction_id"], lease_token=reserved["lease_token"])
    except Exception as exc:
        message["error"] = type(exc).__name__ + ": " + str(exc)
    for op in ("start", "commit"):
        try:
            message[op] = client.request(op, transaction_id=message.get("reserve", {}).get("transaction_id", "UNKNOWN"))
        except Exception as exc:
            message[op] = type(exc).__name__ + ": " + str(exc)
    print(json.dumps(message, default=str), flush=True)


if __name__ == "__main__":
    run_worker(Path(sys.argv[1]), Path(sys.argv[2]))
