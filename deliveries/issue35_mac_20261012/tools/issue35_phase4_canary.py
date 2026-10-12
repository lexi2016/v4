#!/usr/bin/env python3
"""Run the single next-HK-session plan-owner canary; execution is opt-in.

The default invocation validates the selected immutable release and current
runtime inputs without HTTP calls or writes. ``--execute`` sends the existing
workspace refresh POST and auto-view GET through an in-process ASGI transport.
Only that explicit mode may write the target date under formal manager state.
"""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import os
import re
import stat
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import issue35_phase4_common as common


def _write_exclusive(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _configure_runtime_environment(environment: dict[str, str], app_root: Path,
                                  release: dict[str, Any], binding_path: Path) -> None:
    for key in tuple(os.environ):
        if key.startswith(("V35_", "V4_MANAGER_")) or key in {
            "PRODUCTION_ALLOWED", "BUY_GATE_UPDATED", "ORDERS_SENT", "RESEARCH_ONLY",
        }:
            os.environ.pop(key, None)
    os.environ.update(environment)
    os.environ.update(
        V35_APP_ROOT=str(app_root),
        V35_RELEASE_ID=str(release["manifest"]["candidate"]["release_id"]),
        V35_RELEASE_MANIFEST_PATH=str(release["manifest_path"]),
        V35_RELEASE_MANIFEST_SHA256=str(release["manifest_sha256"]),
        PYTHONPATH=os.pathsep.join((str(app_root / "upstreams"), str(app_root))),
        V4_MANAGER_PLAN_OWNER_BINDING_PATH=str(binding_path),
        RESEARCH_ONLY="true", PRODUCTION_ALLOWED="false", BUY_GATE_UPDATED="false",
        ORDERS_SENT="false",
    )


def _validate_owner_pair(refresh: dict[str, Any], readback: dict[str, Any],
                         target: str) -> tuple[str, str, str, str]:
    product = refresh.get("plan_product")
    get_product = readback.get("plan_product")
    persisted = refresh.get("persisted_store")
    attempt = refresh.get("workspace_plan_attempt")
    safety = refresh.get("safety")
    if (refresh.get("target_trade_date") != target or readback.get("target_trade_date") != target
            or refresh.get("formal_recommendation_count") != 0
            or refresh.get("store_latest_matches_http_plan_product") is not True
            or not isinstance(product, dict) or not isinstance(get_product, dict)
            or product.get("status") != "CURRENT" or get_product.get("status") != "CURRENT"
            or product.get("consumed") is not True or get_product.get("consumed") is not True
            or product.get("run_id") != get_product.get("run_id")
            or product.get("sha256") != get_product.get("sha256")
            or product.get("original_owner") != common.OWNER
            or get_product.get("original_owner") != common.OWNER
            or not isinstance(persisted, dict) or persisted.get("target_trade_date") != target
            or persisted.get("run_id") != product.get("run_id")
            or persisted.get("product_sha256") != product.get("sha256")
            or persisted.get("execution_kind") != "MANUAL_REFRESH"
            or persisted.get("owner") != common.OWNER
            or not isinstance(attempt, dict)
            or attempt.get("execution_kind") != "MANUAL_REFRESH"
            or attempt.get("state") not in {"SUCCEEDED", "PARTIAL"}
            or refresh.get("input_identity") != readback.get("input_identity")
            or not isinstance(refresh.get("input_identity"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", refresh["input_identity"])
            or safety != common.SAFETY
            or any(persisted.get(key) != value for key, value in common.SAFETY.items())):
        raise ValueError("CANARY_OWNER_READBACK_MISMATCH")
    run_id = str(product.get("run_id") or "")
    product_sha = str(product.get("sha256") or "")
    input_identity = str(refresh.get("input_identity") or "")
    if (not re.fullmatch(r"[0-9a-f]{32}", run_id)
            or not re.fullmatch(r"[0-9a-f]{64}", product_sha)):
        raise ValueError("CANARY_PRODUCT_IDENTITY_INVALID")
    return run_id, product_sha, input_identity, str(attempt["state"])


def _http_record(response: Any, *, method: str, url: str, name: str,
                 output_dir: Path) -> dict[str, str]:
    body = bytes(response.content)
    body_path = output_dir / f"{name}.response.bin"
    _write_exclusive(body_path, body)
    try:
        envelope = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("CANARY_RESPONSE_JSON_INVALID:" + name) from exc
    if not isinstance(envelope, dict):
        raise ValueError("CANARY_RESPONSE_ENVELOPE_INVALID:" + name)
    record = {
        "schema_version": "manager_daily_chain.plan_owner_http_evidence.v1",
        "http_status": response.status_code,
        "content_type": response.headers.get("content-type"),
        "request": {"method": method, "url": url},
        "response": {"path": str(body_path), "sha256": common.sha256_bytes(body),
                     "bytes": len(body)},
        "readback": envelope,
    }
    evidence_path = output_dir / f"{name}.http-evidence.json"
    raw = _json_bytes(record)
    _write_exclusive(evidence_path, raw)
    return {"path": str(evidence_path), "sha256": common.sha256_bytes(raw)}


def _target_preimage(state_root: Path, target: str) -> dict[str, Any]:
    targets = (
        state_root / "workspace_plan_runs" / target,
        state_root / "workspace_plans" / target,
        state_root / ".locks" / f"{target}-workspace-plan-refresh.mutex",
    )
    for path in targets:
        if path.exists() or path.is_symlink():
            raise FileExistsError("TARGET_OWNER_STATE_PREEXISTS:" + str(path))
    return common.protected_state_hashes(state_root)


_RECOVERY_SOURCE_RELATIVE = Path("receipts/plan_canary_runs/20261012/execution-01")
_RECOVERY_PINS = {
    "target_trade_date": "20261012",
    "run_id": "960c3b5f9b974b188f47b9387fc95cba",
    "product_sha256": "c01605b233fb4307e6ee9ede96eae3e7a3a5e7bd3b38580adb775ad63117c330",
    "input_identity": "d723652d58e0cc06ba5341dbdc4cedd02ab1df5a6771760fb68b432fae7d142d",
    "attempt_sha256": "51227b8db8d7078d39feb0a9db2d207a7e82c0175d7161cda49f7c1475dc684d",
    "run_file_sha256": "07370d1164d5791b1ed6d310173a4d45e2c0a9c70163ba8d0405549c5dcb0f88",
    "plan_file_sha256": "36dd70c3106bacee809c82bbf51714c46a05d507f978ce7de70ab4e1b1f070c8",
    "preimage_sha256": "d2c4711fc1c6c036347b498e26a489d964057defb5b5b8ba6587186c8a063f7d",
    "failure_receipt_sha256": "2996420fc9491d50acb72d68ac41201c7e91e5ba8afba0714250e61792f0a7f6",
    "disabled_binding_sha256": "7ea2726070c025d2c6a53850087032796dae4552a9b0402473e8f80aef0e5230",
    "refresh": {
        "method": "POST",
        "url": "http://127.0.0.1:8873/api/v4/manager/research/workspace/refresh?date=20261012",
        "evidence_sha256": "56b6c405c72786e3554a8f9d8cfc8cefc387f45295988d09ba377f9226e4e9d1",
        "response_sha256": "93ae2662f1a639b5ec6f237d7feb4b991e5cd99b4f2cfbad91a202527d13a074",
        "response_bytes": 35812899,
        "response_path": "refresh.response.bin",
        "evidence_path": "refresh.http-evidence.json",
    },
    "readback": {
        "method": "GET",
        "url": "http://127.0.0.1:8873/api/v4/manager/research/workspace?date=20261012",
        "evidence_sha256": "1fc6e166bf71a87d020896e0af72bad78a8b09a19c1cbce04379c16aaf88ad26",
        "response_sha256": "a50123a30ba8a685d4e0643980749a295a095154ba32084348912b657881d8f8",
        "response_bytes": 35813766,
        "response_path": "readback.response.bin",
        "evidence_path": "readback.http-evidence.json",
    },
}

_CURRENT13_ACCEPTANCE = {
    "target_trade_date": "20261013",
    "run_id": "d8a35106712a4387accf214c3ee3772d",
    "product_sha256": "7ba36ad92af7cccaadbcdacca3a2eddc9488a80e28ddd9185ebba2e5afffc49c",
    "input_identity": "3c3f32668945d572af760fdc9b36ad5c577a7167720dc8aaba3fd60ccae9bbd3",
    "root_cause_receipt": common.TASK_ROOT / "receipts/phase3-issue35-target13/root-cause-readonly-01.json",
    "root_cause_receipt_sha256": "4a672771af82f0bcb5fcdfd7af4b552981021d484dc3092da7d9aa2b2574154d",
    "r3_manifest_sha256": "7aa0653999eb1b126c0f0e7420db8a278d7340831653a75ab1286fb292ea7f85",
    "r4_manifest_sha256": "ccf0bbec4b58910f180320e4288f09e0af2a8143c542f2183eab977d01746b9f",
    "run_file_sha256": "9ca32cee34b42727666c6c96e0cc9396a387bc48e332f232621232c6dbd1aee2",
    "run_file_bytes": 356369,
    "product_file_sha256": "777c6496402ea7d2313ed7c09ff7be2ae1e5597659bcbfb6b42fe3fdd051522a",
    "product_file_bytes": 40992670,
}


def _stable_exact_bytes(path: Path, label: str) -> bytes:
    """Read one regular file and reject identity or content changes during readback."""
    if path.is_symlink() or not path.is_file() or path.resolve(strict=True) != path:
        raise ValueError(label + "_NOT_EXACT_FILE")
    before = path.lstat()
    raw = path.read_bytes()
    after = path.lstat()
    if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or len(raw) != after.st_size):
        raise ValueError(label + "_CHANGED_DURING_READ")
    return raw


def _current13_existing_preimage(identity: dict[str, Any], target: str,
                                 now: datetime) -> dict[str, Any]:
    """Read-only exact preimage gate for the one previously written target-13 run."""
    pins = _CURRENT13_ACCEPTANCE
    release = identity["release"]
    state_root = identity["state_root"]
    if target != pins["target_trade_date"]:
        raise ValueError("CURRENT13_ACCEPTANCE_TARGET_NOT_PINNED")
    if (release["manifest_sha256"] != pins["r4_manifest_sha256"]
            or release["manifest"]["candidate"].get("release_id") != "issue35-manager-autocontinue-20261012-r4b"):
        raise ValueError("CURRENT13_ACCEPTANCE_REQUIRES_R4B_RELEASE")
    common.require_next_session(target, release["app_root"], now)

    root_cause_raw = _stable_exact_bytes(pins["root_cause_receipt"], "CURRENT13_ROOT_CAUSE")
    if common.sha256_bytes(root_cause_raw) != pins["root_cause_receipt_sha256"]:
        raise ValueError("CURRENT13_ROOT_CAUSE_SHA_MISMATCH")
    root_cause = json.loads(root_cause_raw)
    actual = root_cause.get("actual_run_identity", {})
    if (root_cause.get("status") != "ROOT_CAUSE_CONFIRMED_BOUNDED_EVIDENCE_SIZE_LIMIT"
            or actual.get("run_id") != pins["run_id"]
            or actual.get("product_sha256") != pins["product_sha256"]
            or actual.get("input_identity") != pins["input_identity"]
            or actual.get("candidate_release_manifest_sha256") != pins["r3_manifest_sha256"]):
        raise ValueError("CURRENT13_ROOT_CAUSE_IDENTITY_MISMATCH")
    if state_root != common.DEFAULT_MANAGER_STATE_ROOT:
        raise ValueError("CURRENT13_MANAGER_STATE_ROOT_MISMATCH")

    run_root = state_root / "workspace_plan_runs" / target
    plan_root = state_root / "workspace_plans" / target
    run_file = run_root / (pins["run_id"] + ".json")
    run_latest = run_root / "latest.json"
    product_file = plan_root / (pins["run_id"] + ".json")
    product_latest = plan_root / "latest.json"
    lock_path = state_root / ".locks" / (target + "-workspace-plan-refresh.mutex")
    before_lock = _kernel_lock_is_free(lock_path)
    if not before_lock:
        raise ValueError("CURRENT13_OWNER_LOCK_BUSY")
    run_raw = _stable_exact_bytes(run_file, "CURRENT13_RUN_FILE")
    run_latest_raw = _stable_exact_bytes(run_latest, "CURRENT13_RUN_LATEST")
    product_raw = _stable_exact_bytes(product_file, "CURRENT13_PRODUCT_FILE")
    product_latest_raw = _stable_exact_bytes(product_latest, "CURRENT13_PRODUCT_LATEST")
    expected_names = {"latest.json", pins["run_id"] + ".json"}
    _directory_write_set(run_root, expected_names, "CURRENT13_RUN_PREIMAGE")
    _directory_write_set(plan_root, expected_names, "CURRENT13_PRODUCT_PREIMAGE")
    hashes = {
        "run_file": common.sha256_bytes(run_raw),
        "run_latest": common.sha256_bytes(run_latest_raw),
        "product_file": common.sha256_bytes(product_raw),
        "product_latest": common.sha256_bytes(product_latest_raw),
    }
    if (len(run_raw) != pins["run_file_bytes"] or len(product_raw) != pins["product_file_bytes"]
            or hashes["run_file"] != pins["run_file_sha256"]
            or hashes["run_latest"] != pins["run_file_sha256"]
            or hashes["product_file"] != pins["product_file_sha256"]
            or hashes["product_latest"] != pins["product_file_sha256"]
            or run_raw != run_latest_raw or product_raw != product_latest_raw):
        raise ValueError("CURRENT13_OWNER_PREIMAGE_SHA_OR_SIZE_MISMATCH")
    run = json.loads(run_raw)
    product = json.loads(product_raw)
    if (run.get("target_trade_date") != target or run.get("run_id") != pins["run_id"]
            or run.get("input_identity") != pins["input_identity"] or run.get("state") != "PARTIAL"
            or run.get("owner") != common.OWNER or run.get("execution_kind") != "MANUAL_REFRESH"
            or any(run.get(k) != v for k, v in common.SAFETY.items())
            or product.get("target_trade_date") != target or product.get("run_id") != pins["run_id"]
            or product.get("sha256") != pins["product_sha256"]
            or product.get("input_identity") != pins["input_identity"]
            or product.get("owner") != common.OWNER or product.get("execution_kind") != "MANUAL_REFRESH"
            or any(product.get(k) != v for k, v in common.SAFETY.items())):
        raise ValueError("CURRENT13_OWNER_PREIMAGE_IDENTITY_MISMATCH")
    raw_evidence_checks = []
    for row in root_cause.get("evidence_files", []):
        rel = Path(str(row.get("path") or ""))
        if rel.is_absolute() or ".." in rel.parts or not rel.parts:
            raise ValueError("CURRENT13_RAW_EVIDENCE_PATH_INVALID")
        path = common.TASK_ROOT.parent / rel
        raw = _stable_exact_bytes(path, "CURRENT13_RAW_EVIDENCE")
        if len(raw) != row.get("bytes") or common.sha256_bytes(raw) != row.get("sha256"):
            raise ValueError("CURRENT13_RAW_EVIDENCE_PIN_MISMATCH:" + rel.name)
        raw_evidence_checks.append({"path": str(path), "bytes": len(raw), "sha256": row["sha256"]})
    if not _kernel_lock_is_free(lock_path):
        raise ValueError("CURRENT13_OWNER_LOCK_CHANGED_DURING_PREFLIGHT")
    protected = common.protected_state_hashes(state_root)
    return {
        "target_trade_date": target,
        "manager_state_root": str(state_root),
        "prior_run_id": pins["run_id"],
        "prior_product_sha256": pins["product_sha256"],
        "prior_input_identity": pins["input_identity"],
        "prior_owner_attempt_state": run["state"],
        "prior_release_manifest_sha256": pins["r3_manifest_sha256"],
        "prior_state_files": {
            "run_file": {"path": str(run_file), "bytes": len(run_raw), "sha256": hashes["run_file"]},
            "run_latest": {"path": str(run_latest), "bytes": len(run_latest_raw), "sha256": hashes["run_latest"]},
            "product_file": {"path": str(product_file), "bytes": len(product_raw), "sha256": hashes["product_file"]},
            "product_latest": {"path": str(product_latest), "bytes": len(product_latest_raw), "sha256": hashes["product_latest"]},
        },
        "prior_raw_http_evidence_unchanged": raw_evidence_checks,
        "protected_dates_sha256": protected,
        "owner_lock_free": True,
        "http_calls": 0,
        "state_writes": 0,
        "safety": common.SAFETY,
    }


def _assert_current13_failure_preserved(state_root: Path, preimage: dict[str, Any]) -> dict[str, Any]:
    """On failed owner calls, require the original latest pointers and files byte-identical."""
    observed = {}
    for label in ("run_file", "run_latest", "product_file", "product_latest"):
        row = preimage["prior_state_files"][label]
        raw = _stable_exact_bytes(Path(row["path"]), "CURRENT13_FAILURE_PREIMAGE_" + label.upper())
        observed[label] = {"bytes": len(raw), "sha256": common.sha256_bytes(raw)}
        if len(raw) != row["bytes"] or observed[label]["sha256"] != row["sha256"]:
            raise ValueError("CURRENT13_FAILURE_CHANGED_PRIOR_LATEST_OR_RUN:" + label)
    target = preimage["target_trade_date"]
    expected = {"latest.json", preimage["prior_run_id"] + ".json"}
    _directory_write_set(state_root / "workspace_plan_runs" / target, expected, "CURRENT13_FAILURE_RUN")
    _directory_write_set(state_root / "workspace_plans" / target, expected, "CURRENT13_FAILURE_PRODUCT")
    if not _kernel_lock_is_free(state_root / ".locks" / (target + "-workspace-plan-refresh.mutex")):
        raise ValueError("CURRENT13_FAILURE_OWNER_LOCK_BUSY")
    return {"status": "PASS_PRIOR_LATEST_PRESERVED", "files": observed,
            "owner_lock_free": True, "writes": 0}


def _assert_current13_preimage_unchanged(state_root: Path, preimage: dict[str, Any]) -> None:
    """Recheck the pinned target-13 state immediately before issuing POST."""
    target = preimage["target_trade_date"]
    for label, row in preimage["prior_state_files"].items():
        raw = _stable_exact_bytes(Path(row["path"]), "CURRENT13_PREPOST_" + label.upper())
        if len(raw) != row["bytes"] or common.sha256_bytes(raw) != row["sha256"]:
            raise ValueError("CURRENT13_PREIMAGE_CHANGED_BEFORE_POST:" + label)
    expected = {"latest.json", preimage["prior_run_id"] + ".json"}
    _directory_write_set(state_root / "workspace_plan_runs" / target, expected, "CURRENT13_PREPOST_RUN")
    _directory_write_set(state_root / "workspace_plans" / target, expected, "CURRENT13_PREPOST_PRODUCT")
    if common.protected_state_hashes(state_root) != preimage["protected_dates_sha256"]:
        raise ValueError("CURRENT13_PROTECTED_STATE_CHANGED_BEFORE_POST")
    if not _kernel_lock_is_free(state_root / ".locks" / (target + "-workspace-plan-refresh.mutex")):
        raise ValueError("CURRENT13_OWNER_LOCK_BUSY_BEFORE_POST")


def _verify_current13_success_write_set(state_root: Path, target: str,
                                       run_id: str, product_sha: str,
                                       preimage: dict[str, Any]) -> dict[str, Any]:
    old_run_id = str(preimage["prior_run_id"])
    run_root = state_root / "workspace_plan_runs" / target
    plan_root = state_root / "workspace_plans" / target
    expected = {"latest.json", old_run_id + ".json", run_id + ".json"}
    if run_id == old_run_id:
        expected.remove(run_id + ".json")
    _directory_write_set(run_root, expected, "CURRENT13_SUCCESS_RUN")
    _directory_write_set(plan_root, expected, "CURRENT13_SUCCESS_PRODUCT")
    prior = preimage["prior_state_files"]
    for label, row in (("run_file", prior["run_file"]), ("product_file", prior["product_file"])):
        raw = _stable_exact_bytes(Path(row["path"]), "CURRENT13_SUCCESS_PRIOR_" + label.upper())
        if len(raw) != row["bytes"] or common.sha256_bytes(raw) != row["sha256"]:
            raise ValueError("CURRENT13_SUCCESS_PRIOR_VERSION_MUTATED:" + label)
    if not _kernel_lock_is_free(state_root / ".locks" / (target + "-workspace-plan-refresh.mutex")):
        raise ValueError("CURRENT13_SUCCESS_OWNER_LOCK_BUSY")
    return {"status": "PASS_PRIOR_VERSION_PRESERVED",
            "prior_run_id": old_run_id,
            "current_run_id": run_id,
            "current_product_sha256": product_sha,
            "prior_version_files_preserved": True,
            "allowed_target_write_set": sorted(expected),
            "owner_lock_free": True}


def _kernel_lock_is_free(path: Path) -> bool:
    """Prove an existing persistent mutex inode is currently unlocked.

    OwnedRoot kernel locks deliberately retain their inode after unlock; file
    existence alone is not evidence that an owner still holds the lock.
    This check never creates, truncates, unlinks or writes the lock file.
    """
    common.exact_directory(path.parent, "CANARY_OWNER_LOCK_PARENT_INVALID")
    try:
        before = path.lstat()
    except OSError as exc:
        raise ValueError("CANARY_OWNER_LOCK_FILE_UNAVAILABLE") from exc
    if not stat.S_ISREG(before.st_mode) or path.is_symlink():
        raise ValueError("CANARY_OWNER_LOCK_FILE_INVALID")
    try:
        fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise ValueError("CANARY_OWNER_LOCK_FILE_UNAVAILABLE") from exc
    locked = False
    try:
        opened = os.fstat(fd)
        after = path.lstat()
        identities = {(item.st_dev, item.st_ino) for item in (before, opened, after)}
        if (not stat.S_ISREG(opened.st_mode) or not stat.S_ISREG(after.st_mode)
                or path.is_symlink() or len(identities) != 1):
            raise ValueError("CANARY_OWNER_LOCK_FILE_CHANGED")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        locked = True
        return True
    except OSError as exc:
        raise ValueError("CANARY_OWNER_LOCK_STATUS_UNAVAILABLE") from exc
    finally:
        try:
            if locked:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _read_pinned_json(path: Path, expected_sha256: str, code: str) -> dict[str, Any]:
    raw = common.exact_file(path, code)
    if common.sha256_bytes(raw) != expected_sha256:
        raise ValueError(code + "_SHA_MISMATCH")
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(code + "_INVALID") from exc
    if not isinstance(value, dict):
        raise ValueError(code + "_INVALID")
    return value


def _owner_response_projection(path: Path, *, expected_sha256: str,
                               expected_bytes: int, label: str) -> dict[str, Any]:
    raw = common.exact_file(path, "CANARY_RECOVERY_" + label + "_BODY_MISSING")
    if len(raw) != expected_bytes or common.sha256_bytes(raw) != expected_sha256:
        raise ValueError("CANARY_RECOVERY_" + label + "_BODY_IDENTITY_MISMATCH")
    try:
        body = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("CANARY_RECOVERY_" + label + "_BODY_INVALID") from exc
    if not isinstance(body, dict):
        raise ValueError("CANARY_RECOVERY_" + label + "_BODY_INVALID")

    def selected(mapping: Any, fields: tuple[str, ...]) -> dict[str, Any] | None:
        if not isinstance(mapping, dict):
            return None
        return {key: mapping[key] for key in fields if key in mapping}

    projection = {
        key: body.get(key) for key in (
            "target_trade_date", "formal_recommendation_count",
            "store_latest_matches_http_plan_product", "input_identity", "safety",
        ) if key in body
    }
    projection["plan_product"] = selected(body.get("plan_product"), (
        "status", "consumed", "run_id", "sha256", "original_owner",
    ))
    projection["persisted_store"] = selected(body.get("persisted_store"), (
        "target_trade_date", "run_id", "product_sha256", "execution_kind", "owner",
        "RESEARCH_ONLY", "production_allowed", "buy_gate_updated", "orders_sent",
    ))
    projection["workspace_plan_attempt"] = selected(body.get("workspace_plan_attempt"), (
        "execution_kind", "state", "run_id", "sha256", "owner", "started_at", "finished_at",
    ))
    projection["execution_context"] = selected(body.get("execution_context"), (
        "trigger_id", "trigger_kind", "timing", "started_at", "finished_at",
        "scheduled_for", "natural_run_verified",
    ))
    product = body.get("plan_product")
    projection["product_last_checked_at"] = (
        product.get("last_checked_at") if isinstance(product, dict) else None
    )
    return projection


def _aware_clock(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("CANARY_RECOVERY_" + label + "_CLOCK_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("CANARY_RECOVERY_" + label + "_CLOCK_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("CANARY_RECOVERY_" + label + "_CLOCK_INVALID")
    return parsed.astimezone(ZoneInfo("Asia/Hong_Kong"))


def _verify_recovery_http_evidence(source_dir: Path, label: str) -> tuple[dict[str, Any], dict[str, str]]:
    pin = _RECOVERY_PINS[label]
    evidence_path = source_dir / pin["evidence_path"]
    body_path = source_dir / pin["response_path"]
    evidence_raw = common.exact_file(evidence_path, "CANARY_RECOVERY_" + label.upper() + "_EVIDENCE_MISSING")
    if common.sha256_bytes(evidence_raw) != pin["evidence_sha256"]:
        raise ValueError("CANARY_RECOVERY_" + label.upper() + "_EVIDENCE_SHA_MISMATCH")
    body = _owner_response_projection(body_path, expected_sha256=pin["response_sha256"],
                                      expected_bytes=pin["response_bytes"], label=label.upper())
    return body, {"path": str(evidence_path), "sha256": pin["evidence_sha256"]}


def _write_contract_projection_evidence(output_dir: Path, label: str,
                                        projection: dict[str, Any],
                                        raw_ref: dict[str, str]) -> dict[str, str]:
    """Write a bounded contract projection after the pinned raw body verifies.

    The raw owner HTTP evidence remains preserved and referenced separately.
    This compact form exists because the frozen binding validator caps each
    receipt and response body at 2 MiB, while the exact owner bodies are >35 MiB.
    """
    pin = _RECOVERY_PINS[label]
    body_path = output_dir / f"{label}-verified-projection.response.bin"
    evidence_path = output_dir / f"{label}-verified-projection.http-evidence.json"
    source_dir = common.TASK_ROOT / _RECOVERY_SOURCE_RELATIVE
    body_raw = _json_bytes(projection)
    if len(body_raw) > 2 * 1024 * 1024:
        raise ValueError("CANARY_RECOVERY_PROJECTION_EXCEEDS_BINDING_LIMIT")
    _write_exclusive(body_path, body_raw)
    evidence = {
        "schema_version": "manager_daily_chain.plan_owner_http_evidence.v1",
        "evidence_kind": "DERIVED_VALIDATED_PROJECTION",
        "http_status": 200,
        "content_type": "application/json",
        "request": {"method": pin["method"], "url": pin["url"]},
        "response": {"path": str(body_path), "sha256": common.sha256_bytes(body_raw),
                     "bytes": len(body_raw)},
        "readback": projection,
        "projection_provenance": {
            "kind": "DERIVED_VALIDATED_PROJECTION",
            "identity_fields_copied_without_transformation": True,
            "raw_http_body": {
                "kind": "RAW_HTTP_BODY",
                "path": str(source_dir / pin["response_path"]),
                "sha256": pin["response_sha256"],
                "bytes": pin["response_bytes"],
            },
            "raw_http_evidence": {
                "kind": "RAW_HTTP_EVIDENCE",
                "path": raw_ref["path"],
                "sha256": raw_ref["sha256"],
            },
        },
    }
    evidence_raw = _json_bytes(evidence)
    if len(evidence_raw) > 2 * 1024 * 1024:
        raise ValueError("CANARY_RECOVERY_PROJECTION_RECEIPT_EXCEEDS_BINDING_LIMIT")
    _write_exclusive(evidence_path, evidence_raw)
    return {"path": str(evidence_path), "sha256": common.sha256_bytes(evidence_raw)}


def _projection_evidence_summary(source_dir: Path, label: str,
                                 projection: dict[str, Any],
                                 raw_ref: dict[str, str]) -> dict[str, Any]:
    """Keep original HTTP identity distinct from the bounded derived contract view."""
    pin = _RECOVERY_PINS[label]
    projection_raw = _json_bytes(projection)
    return {
        "kind": "RAW_HTTP_BODY_PLUS_DERIVED_VALIDATED_PROJECTION",
        "raw_http": {
            "kind": "RAW_HTTP_BODY",
            "method": pin["method"],
            "url": pin["url"],
            "http_status": 200,
            "body_path": str(source_dir / pin["response_path"]),
            "body_sha256": pin["response_sha256"],
            "body_bytes": pin["response_bytes"],
            "evidence_path": raw_ref["path"],
            "evidence_sha256": raw_ref["sha256"],
        },
        "contract_projection": {
            "kind": "DERIVED_VALIDATED_PROJECTION",
            "sha256": common.sha256_bytes(projection_raw),
            "bytes": len(projection_raw),
        },
    }


def _directory_write_set(directory: Path, expected: set[str], code: str) -> None:
    common.exact_directory(directory, code + "_DIRECTORY_INVALID")
    actual: set[str] = set()
    for entry in directory.iterdir():
        if entry.is_symlink() or not entry.is_file():
            raise ValueError(code + "_ENTRY_INVALID")
        actual.add(entry.name)
    if actual != expected:
        raise ValueError(code + "_WRITE_SET_MISMATCH")


def _verify_recovered_owner(identity: dict[str, Any], target: str, now: datetime) -> dict[str, Any]:
    """Validate one pinned completed POST/GET without invoking either route."""
    if target != _RECOVERY_PINS["target_trade_date"]:
        raise ValueError("CANARY_RECOVERY_TARGET_NOT_PINNED")
    release = identity["release"]
    if (identity["active_api_app_root"] != release["app_root"]
            or identity["active_api_manifest_sha256"] != release["manifest_sha256"]
            or identity["active_api_release_id"] != release["manifest"]["candidate"]["release_id"]):
        raise ValueError("CANARY_RECOVERY_ACTIVE_RELEASE_MISMATCH")

    source_dir = common.TASK_ROOT / _RECOVERY_SOURCE_RELATIVE
    common.exact_directory(source_dir, "CANARY_RECOVERY_SOURCE_DIRECTORY_INVALID")
    preimage_path = source_dir / "state-preimage.json"
    preimage = _read_pinned_json(preimage_path, _RECOVERY_PINS["preimage_sha256"],
                                 "CANARY_RECOVERY_STATE_PREIMAGE")
    failure = _read_pinned_json(source_dir / "failure-receipt.json",
                                _RECOVERY_PINS["failure_receipt_sha256"],
                                "CANARY_RECOVERY_FAILURE_RECEIPT")
    if (failure.get("error_code") != "CANARY_DURABLE_OWNER_WRITE_SET_INVALID"
            or failure.get("target_trade_date") != target
            or failure.get("activation_status") != "NOT_ACTIVATED"
            or failure.get("launchctl_called") is not False
            or failure.get("safety") != common.SAFETY):
        raise ValueError("CANARY_RECOVERY_ORIGINAL_FAILURE_MISMATCH")

    preimage_clock = _aware_clock(preimage.get("current_clock_local"), "PREIMAGE")
    current_clock = _aware_clock(now.isoformat(), "CURRENT")
    common.require_next_session(target, release["app_root"], preimage_clock)
    common.require_next_session(target, release["app_root"], current_clock)
    if (current_clock < preimage_clock or current_clock.date() != preimage_clock.date()
            or preimage.get("target_trade_date") != target
            or preimage.get("target_preexisted") is not False
            or preimage.get("manager_state_root") != str(identity["state_root"])
            or preimage.get("api_app_root") != str(release["app_root"])
            or preimage.get("release_manifest_sha256") != release["manifest_sha256"]
            or preimage.get("application_inventory_sha256") != release["application_inventory_sha256"]
            or preimage.get("owner_source_inventory_sha256") != release["owner_inventory_sha256"]
            or preimage.get("safety") != common.SAFETY):
        raise ValueError("CANARY_RECOVERY_PREIMAGE_RELEASE_CLOCK_MISMATCH")
    refresh_url = common.API_BASE_URL + f"/api/v4/manager/research/workspace/refresh?date={target}"
    readback_url = common.API_BASE_URL + f"/api/v4/manager/research/workspace?date={target}"
    expected_calls = ["POST " + refresh_url, "GET " + readback_url]
    if preimage.get("http_calls_expected") != expected_calls:
        raise ValueError("CANARY_RECOVERY_PREIMAGE_HTTP_CALLS_MISMATCH")

    disabled_binding = _read_pinned_json(source_dir / "canary-disabled-binding.json",
                                         _RECOVERY_PINS["disabled_binding_sha256"],
                                         "CANARY_RECOVERY_DISABLED_BINDING")
    expected_disabled = common.build_binding(identity, enabled=False)
    if disabled_binding != expected_disabled:
        raise ValueError("CANARY_RECOVERY_DISABLED_BINDING_MISMATCH")
    release["contract"].validate_binding(disabled_binding, release["app_root"])

    refresh, refresh_ref = _verify_recovery_http_evidence(source_dir, "refresh")
    readback, readback_ref = _verify_recovery_http_evidence(source_dir, "readback")
    run_id, product_sha, input_identity, attempt_state = _validate_owner_pair(
        refresh, readback, target)
    if (run_id != _RECOVERY_PINS["run_id"]
            or product_sha != _RECOVERY_PINS["product_sha256"]
            or input_identity != _RECOVERY_PINS["input_identity"]
            or attempt_state != "PARTIAL"):
        raise ValueError("CANARY_RECOVERY_OWNER_PAIR_NOT_PINNED")

    refresh_context = refresh.get("execution_context")
    readback_context = readback.get("execution_context")
    refresh_attempt = refresh.get("workspace_plan_attempt")
    readback_attempt = readback.get("workspace_plan_attempt")
    if (not isinstance(refresh_context, dict) or not isinstance(readback_context, dict)
            or not isinstance(refresh_attempt, dict) or not isinstance(readback_attempt, dict)
            or refresh_context.get("trigger_kind") != "MANUAL"
            or refresh_context.get("timing") != "UNCLASSIFIED"
            or refresh_context.get("natural_run_verified") is not False
            or refresh_context.get("trigger_id") != readback_context.get("trigger_id")
            or refresh_attempt.get("run_id") != run_id
            or readback_attempt.get("run_id") != run_id
            or refresh_attempt.get("sha256") != _RECOVERY_PINS["attempt_sha256"]
            or readback_attempt.get("sha256") != _RECOVERY_PINS["attempt_sha256"]
            or refresh_attempt.get("started_at") != readback_attempt.get("started_at")
            or refresh_attempt.get("finished_at") != readback_attempt.get("finished_at")):
        raise ValueError("CANARY_RECOVERY_OWNER_CLOCK_BINDING_INVALID")
    request_clock = _aware_clock(refresh_context.get("started_at"), "OWNER_STARTED")
    attempt_started = _aware_clock(refresh_attempt.get("started_at"), "ATTEMPT_STARTED")
    attempt_finished = _aware_clock(refresh_attempt.get("finished_at"), "ATTEMPT_FINISHED")
    refresh_checked = _aware_clock(refresh.get("product_last_checked_at"), "POST_READBACK")
    readback_checked = _aware_clock(readback.get("product_last_checked_at"), "GET_READBACK")
    if not (preimage_clock <= request_clock == attempt_started <= attempt_finished
            <= refresh_checked <= readback_checked <= current_clock):
        raise ValueError("CANARY_RECOVERY_OWNER_CLOCK_ORDER_INVALID")

    state_root = identity["state_root"]
    protected_preimage = preimage.get("protected_dates_sha256")
    if (not isinstance(protected_preimage, dict)
            or common.protected_state_hashes(state_root) != protected_preimage):
        raise ValueError("CANARY_RECOVERY_PROTECTED_STATE_CHANGED")
    lock = state_root / ".locks" / f"{target}-workspace-plan-refresh.mutex"
    if not _kernel_lock_is_free(lock):
        raise ValueError("CANARY_RECOVERY_OWNER_LOCK_BUSY")
    run_root = state_root / "workspace_plan_runs" / target
    plan_root = state_root / "workspace_plans" / target
    expected_names = {"latest.json", run_id + ".json"}
    _directory_write_set(run_root, expected_names, "CANARY_RECOVERY_RUN")
    _directory_write_set(plan_root, expected_names, "CANARY_RECOVERY_PLAN")
    run_latest_raw = common.exact_file(run_root / "latest.json", "CANARY_RECOVERY_RUN_LATEST_MISSING")
    run_record_raw = common.exact_file(run_root / (run_id + ".json"), "CANARY_RECOVERY_RUN_FILE_MISSING")
    plan_latest_raw = common.exact_file(plan_root / "latest.json", "CANARY_RECOVERY_PLAN_LATEST_MISSING")
    plan_record_raw = common.exact_file(plan_root / (run_id + ".json"), "CANARY_RECOVERY_PLAN_FILE_MISSING")
    if (common.sha256_bytes(run_latest_raw) != _RECOVERY_PINS["run_file_sha256"]
            or common.sha256_bytes(run_record_raw) != _RECOVERY_PINS["run_file_sha256"]
            or run_latest_raw != run_record_raw
            or common.sha256_bytes(plan_latest_raw) != _RECOVERY_PINS["plan_file_sha256"]
            or common.sha256_bytes(plan_record_raw) != _RECOVERY_PINS["plan_file_sha256"]
            or plan_latest_raw != plan_record_raw):
        raise ValueError("CANARY_RECOVERY_DURABLE_STATE_BYTES_MISMATCH")
    run_latest = json.loads(run_latest_raw)
    plan_latest = json.loads(plan_latest_raw)
    run_unsigned = {key: value for key, value in run_latest.items() if key != "sha256"}
    plan_unsigned = {key: value for key, value in plan_latest.items() if key != "sha256"}
    if (common.canonical_sha(run_unsigned) != _RECOVERY_PINS["attempt_sha256"]
            or common.canonical_sha(plan_unsigned) != _RECOVERY_PINS["product_sha256"]
            or run_latest.get("run_id") != run_id
            or run_latest.get("target_trade_date") != target
            or run_latest.get("owner") != common.OWNER
            or run_latest.get("execution_kind") != "MANUAL_REFRESH"
            or run_latest.get("state") != attempt_state
            or any(run_latest.get(key) != value for key, value in common.SAFETY.items())
            or plan_latest.get("run_id") != run_id
            or plan_latest.get("target_trade_date") != target
            or plan_latest.get("owner") != common.OWNER
            or plan_latest.get("execution_kind") != "MANUAL_REFRESH"
            or any(plan_latest.get(key) != value for key, value in common.SAFETY.items())):
        raise ValueError("CANARY_RECOVERY_DURABLE_STATE_IDENTITY_MISMATCH")
    if not _kernel_lock_is_free(lock):
        raise ValueError("CANARY_RECOVERY_OWNER_LOCK_CHANGED_DURING_READ")

    owner_evidence_summary = {
        "refresh": _projection_evidence_summary(
            source_dir, "refresh", refresh, refresh_ref),
        "readback": _projection_evidence_summary(
            source_dir, "readback", readback, readback_ref),
    }

    return {
        "target_trade_date": target,
        "run_id": run_id,
        "product_sha256": product_sha,
        "input_identity": input_identity,
        "attempt_sha256": _RECOVERY_PINS["attempt_sha256"],
        "attempt_state": attempt_state,
        "preimage": preimage,
        "preimage_path": str(preimage_path),
        "preimage_sha256": _RECOVERY_PINS["preimage_sha256"],
        "failure_receipt_path": str(source_dir / "failure-receipt.json"),
        "failure_receipt_sha256": _RECOVERY_PINS["failure_receipt_sha256"],
        "raw_owner_evidence": {"refresh": refresh_ref, "readback": readback_ref},
        "owner_response_projections": {"refresh": refresh, "readback": readback},
        "owner_evidence_summary": owner_evidence_summary,
        "owner_trigger_id": refresh_context["trigger_id"],
        "owner_started_at": refresh_context["started_at"],
        "owner_finished_at": refresh_attempt["finished_at"],
        "readback_checked_at": readback.get("product_last_checked_at"),
        "manager_state_root": str(state_root),
        "run_root": run_root,
        "plan_root": plan_root,
        "expected_durable_paths": [str(run_root / "latest.json"), str(run_root / (run_id + ".json")),
                                    str(plan_root / "latest.json"), str(plan_root / (run_id + ".json"))],
        "protected_dates_sha256": protected_preimage,
        "current_clock_local": current_clock.isoformat(),
    }


def _write_recovered_canary(identity: dict[str, Any], output_dir: Path,
                            verified: dict[str, Any]) -> dict[str, Any]:
    release = identity["release"]
    final_path = output_dir / "plan-canary.json"
    contract_evidence = {
        label: _write_contract_projection_evidence(
            output_dir, label, verified["owner_response_projections"][label],
            verified["raw_owner_evidence"][label],
        )
        for label in ("refresh", "readback")
    }
    raw_owner_http = {
        label: {
            "kind": "RAW_HTTP_BODY",
            "method": _RECOVERY_PINS[label]["method"],
            "url": _RECOVERY_PINS[label]["url"],
            "http_status": 200,
            "content_type": "application/json",
            "body_path": str(common.TASK_ROOT / _RECOVERY_SOURCE_RELATIVE /
                              _RECOVERY_PINS[label]["response_path"]),
            "body_sha256": _RECOVERY_PINS[label]["response_sha256"],
            "body_bytes": _RECOVERY_PINS[label]["response_bytes"],
            "http_evidence_path": verified["raw_owner_evidence"][label]["path"],
            "http_evidence_sha256": verified["raw_owner_evidence"][label]["sha256"],
        }
        for label in ("refresh", "readback")
    }
    canary = {
        "schema_version": common.CANARY_SCHEMA,
        "status": common.CANARY_STATUS,
        "app_root": str(release["app_root"]),
        "manager_state_root": verified["manager_state_root"],
        "policy_status": "PROPOSAL_ONLY",
        "scope": common.CANARY_NEXT_SCOPE,
        "plan_material_refresh_only": True,
        "candidate_binding_app_root": str(release["app_root"]),
        "owner_execution_app_root": str(release["app_root"]),
        "owner_source_inventory_sha256": release["owner_inventory_sha256"],
        "api_runtime_stage_mode": verified["runtime_stage_mode"],
        "execution_mode": common.EXECUTION_MODE,
        "hook_executed": False,
        "announcement_collection_enabled": False,
        "announcement_network_requests": 0,
        "owner_http_requests_replayed": False,
        "formal_state_writes_performed": False,
        "recovery_source_failure_receipt": {
            "path": verified["failure_receipt_path"],
            "sha256": verified["failure_receipt_sha256"],
        },
        "recovery_preimage": {
            "path": verified["preimage_path"],
            "sha256": verified["preimage_sha256"],
        },
        "raw_owner_http": raw_owner_http,
        "contract_evidence_kind": "DERIVED_VALIDATED_PROJECTION",
        **common.SAFETY,
        "research_only": True,
        "target_trade_date": verified["target_trade_date"],
        "current_clock_local": verified["current_clock_local"],
        "readback_view": "auto (route default)",
        "run_id": verified["run_id"],
        "product_sha256": verified["product_sha256"],
        "input_identity": verified["input_identity"],
        "execution_kind": "MANUAL_REFRESH",
        "owner": common.OWNER,
        "owner_attempt_state": verified["attempt_state"],
        "formal_recommendation_count": 0,
        "candidate_release_id": release["manifest"]["candidate"]["release_id"],
        "candidate_release_manifest_path": str(release["manifest_path"]),
        "candidate_release_manifest_sha256": release["manifest_sha256"],
        "candidate_application_inventory_sha256": release["application_inventory_sha256"],
        "candidate_manager_source_inventory_sha256": common.canonical_sha(release["binding_files"]),
        "owner_evidence": contract_evidence,
        "state_preimage": {
            "protected_dates_sha256": verified["protected_dates_sha256"],
            "target_preexisted": False,
            "expected_durable_paths": verified["expected_durable_paths"],
        },
        "recovery_provenance": {
            "mode": "RECOVERED_EXACT_EXISTING_OWNER_POST_GET",
            "source_execution_dir": str(common.TASK_ROOT / _RECOVERY_SOURCE_RELATIVE),
            "owner_trigger_id": verified["owner_trigger_id"],
            "owner_started_at": verified["owner_started_at"],
            "owner_finished_at": verified["owner_finished_at"],
            "readback_checked_at": verified["readback_checked_at"],
            "raw_owner_http": raw_owner_http,
            "contract_evidence_kind": "DERIVED_VALIDATED_PROJECTION",
        },
        "safety": common.SAFETY,
    }
    canary_raw = _json_bytes(canary)
    pending_path = output_dir / ".plan-canary-validation.json"
    binding = common.build_binding(identity, enabled=True, canary_path=pending_path,
                                   canary_sha256=common.sha256_bytes(canary_raw))
    _write_exclusive(pending_path, canary_raw)
    release["contract"].validate_binding(binding, release["app_root"],
                                         expected_owner_app=release["app_root"])
    pending_path.rename(final_path)
    binding["plan_activation_receipt"]["path"] = str(final_path)
    release["contract"].validate_binding(binding, release["app_root"],
                                         expected_owner_app=release["app_root"])
    receipt = {
        "schema_version": "manager_daily_chain.plan_canary_operation.v1",
        "status": common.CANARY_STATUS,
        "recovery_mode": "RECOVERED_EXACT_EXISTING_OWNER_POST_GET",
        "canary_path": str(final_path),
        "canary_sha256": common.sha256_bytes(canary_raw),
        "api_app_root": str(release["app_root"]),
        "manager_state_root": verified["manager_state_root"],
        "target_trade_date": verified["target_trade_date"],
        "run_id": verified["run_id"],
        "product_sha256": verified["product_sha256"],
        "input_identity": verified["input_identity"],
        "owner_attempt_state": verified["attempt_state"],
        "candidate_release_manifest_sha256": release["manifest_sha256"],
        "application_inventory_sha256": release["application_inventory_sha256"],
        "manager_source_inventory_sha256": common.canonical_sha(release["binding_files"]),
        "api_runtime_stage_mode": verified["runtime_stage_mode"],
        "source_failure_receipt": {
            "path": verified["failure_receipt_path"],
            "sha256": verified["failure_receipt_sha256"],
        },
        "owner_evidence": contract_evidence,
        "raw_owner_http": raw_owner_http,
        "contract_evidence_kind": "DERIVED_VALIDATED_PROJECTION",
        "activation_status": "NOT_ACTIVATED",
        "launchctl_called": False,
        "owner_post_replayed": False,
        "owner_get_replayed": False,
        "formal_state_writes_performed": False,
        "safety": common.SAFETY,
    }
    receipt_path = output_dir / "operation-receipt.json"
    _write_exclusive(receipt_path, _json_bytes(receipt))
    receipt["operation_receipt_path"] = str(receipt_path)
    receipt["operation_receipt_sha256"] = common.sha256_bytes(
        common.exact_file(receipt_path, "CANARY_RECOVERY_OPERATION_RECEIPT_MISSING"))
    return receipt


def _owner_app(identity: dict[str, Any], runtime_roots: dict[str, Any],
               binding_path: Path):
    app_root = identity["release"]["app_root"]
    _configure_runtime_environment(identity["live"]["api_env"], app_root,
                                   identity["release"], binding_path)
    if str(app_root / "upstreams") not in sys.path:
        sys.path.insert(0, str(app_root / "upstreams"))
    if str(app_root) not in sys.path:
        sys.path.insert(0, str(app_root))
    from apps.api.v35_api.app import create_app
    return create_app(
        data_root=runtime_roots["data_root"],
        preselection_source_root=runtime_roots["preselection_source_root_argument"],
        shared_data_root=runtime_roots["shared_data_root"],
        ledger_root=runtime_roots["ledger_root"],
        stage_center_selection_root=runtime_roots["stage_selection_root"],
        manager_research_state_root=identity["state_root"],
    )


async def _execute_owner_canary(identity: dict[str, Any], target: str,
                                output_dir: Path,
                                protected_before: dict[str, dict[str, str] | None],
                                disabled_binding_path: Path,
                                existing_preimage: dict[str, Any] | None = None) -> dict[str, Any]:
    import httpx

    roots = common.resolve_api_runtime_roots(identity["live"]["api"], identity["live"]["api_env"])
    if roots["stage_mode"] != "shared":
        raise ValueError("CANARY_API_STAGE_MODE_NOT_SHARED")
    app = _owner_app(identity, roots, disabled_binding_path)
    url_refresh = common.API_BASE_URL + f"/api/v4/manager/research/workspace/refresh?date={target}"
    # The endpoint's schema default is view=auto; omitting it preserves the
    # production route contract and avoids selecting a historical projection.
    url_readback = common.API_BASE_URL + f"/api/v4/manager/research/workspace?date={target}"
    try:
        if existing_preimage is not None:
            _assert_current13_preimage_unchanged(identity["state_root"], existing_preimage)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url=common.API_BASE_URL) as client:
            response = await client.post(
                f"/api/v4/manager/research/workspace/refresh?date={target}",
                headers={"Origin": common.API_BASE_URL},
            )
            refresh_ref = _http_record(response, method="POST", url=url_refresh,
                                       name="refresh", output_dir=output_dir)
            if response.status_code != 200:
                raise ValueError("CANARY_REFRESH_HTTP_FAILED")
            refresh_body = response.json()
            if not isinstance(refresh_body, dict):
                raise ValueError("CANARY_REFRESH_ENVELOPE_INVALID")

            response = await client.get(f"/api/v4/manager/research/workspace?date={target}")
            readback_ref = _http_record(response, method="GET", url=url_readback,
                                        name="readback", output_dir=output_dir)
            if response.status_code != 200:
                raise ValueError("CANARY_READBACK_HTTP_FAILED")
            readback_body = response.json()
            if not isinstance(readback_body, dict):
                raise ValueError("CANARY_READBACK_ENVELOPE_INVALID")
            run_id, product_sha, input_identity, attempt_state = _validate_owner_pair(
                refresh_body, readback_body, target)

        state_root = identity["state_root"]
        if common.protected_state_hashes(state_root) != protected_before:
            raise ValueError("CANARY_PROTECTED_STATE_CHANGED")
        run_root = state_root / "workspace_plan_runs" / target
        plan_root = state_root / "workspace_plans" / target
        expected_run = f"{run_id}.json"
        lock = state_root / ".locks" / f"{target}-workspace-plan-refresh.mutex"
        current13_state_check = None
        if existing_preimage is None:
            expected_files = {"latest.json", expected_run}
            run_files = {p.name for p in run_root.iterdir() if p.is_file() and not p.is_symlink()} if run_root.is_dir() else set()
            plan_files = {p.name for p in plan_root.iterdir() if p.is_file() and not p.is_symlink()} if plan_root.is_dir() else set()
            write_set_valid = run_files == expected_files and plan_files == expected_files
        else:
            current13_state_check = _verify_current13_success_write_set(
                state_root, target, run_id, product_sha, existing_preimage
            )
            write_set_valid = True
        if (not write_set_valid or not _kernel_lock_is_free(lock)
                or not (run_root / "latest.json").is_file()
                or not (plan_root / "latest.json").is_file()):
            raise ValueError("CANARY_DURABLE_OWNER_WRITE_SET_INVALID")
        run_latest = json.loads((run_root / "latest.json").read_text(encoding="utf-8"))
        plan_latest = json.loads((plan_root / "latest.json").read_text(encoding="utf-8"))
        plan_run = json.loads((plan_root / expected_run).read_text(encoding="utf-8"))
        if (run_latest.get("run_id") != run_id or run_latest.get("state") != attempt_state
                or run_latest.get("target_trade_date") != target
                or run_latest.get("input_identity") != input_identity
                or run_latest.get("owner") != common.OWNER
                or run_latest.get("execution_kind") != "MANUAL_REFRESH"
                or any(run_latest.get(k) != v for k, v in common.SAFETY.items())
                or plan_latest.get("run_id") != run_id or plan_latest.get("sha256") != product_sha
                or plan_latest.get("target_trade_date") != target
                or plan_latest.get("input_identity") != input_identity
                or plan_run != plan_latest or plan_latest.get("execution_kind") != "MANUAL_REFRESH"
                or plan_latest.get("owner") != common.OWNER
                or any(plan_latest.get(k) != v for k, v in common.SAFETY.items())):
            raise ValueError("CANARY_LOCAL_STORE_READBACK_MISMATCH")

        release = identity["release"]
        now = datetime.now(ZoneInfo("Asia/Hong_Kong"))
        canary = {
            "schema_version": common.CANARY_SCHEMA,
            "status": common.CANARY_STATUS,
            "app_root": str(release["app_root"]),
            "manager_state_root": str(state_root),
            "policy_status": "PROPOSAL_ONLY",
            "scope": common.CANARY_NEXT_SCOPE,
            "plan_material_refresh_only": True,
            "candidate_binding_app_root": str(release["app_root"]),
            "owner_execution_app_root": str(release["app_root"]),
            "owner_source_inventory_sha256": release["owner_inventory_sha256"],
            "execution_mode": common.EXECUTION_MODE,
            "hook_executed": False,
            "announcement_collection_enabled": False,
            "announcement_network_requests": 0,
            **common.SAFETY,
            "research_only": True,
            "target_trade_date": target,
            "current_clock_local": now.isoformat(),
            "readback_view": "auto (route default)",
            "run_id": run_id,
            "product_sha256": product_sha,
            "input_identity": input_identity,
            "execution_kind": "MANUAL_REFRESH",
            "owner": common.OWNER,
            "owner_attempt_state": attempt_state,
            "formal_recommendation_count": 0,
            "candidate_release_id": release["manifest"]["candidate"]["release_id"],
            "candidate_release_manifest_path": str(release["manifest_path"]),
            "candidate_release_manifest_sha256": release["manifest_sha256"],
            "candidate_application_inventory_sha256": release["application_inventory_sha256"],
            "candidate_manager_source_inventory_sha256": common.canonical_sha(release["binding_files"]),
            "owner_evidence": {"refresh": refresh_ref, "readback": readback_ref},
            "state_preimage": ({
                "protected_dates_sha256": protected_before,
                "target_preexisted": False,
                "expected_durable_paths": [str(run_root / "latest.json"), str(run_root / expected_run),
                                           str(plan_root / "latest.json"), str(plan_root / expected_run)],
            } if existing_preimage is None else {
                "protected_dates_sha256": protected_before,
                "target_preexisted": True,
                "prior_run_id": existing_preimage["prior_run_id"],
                "prior_product_sha256": existing_preimage["prior_product_sha256"],
                "prior_input_identity": existing_preimage["prior_input_identity"],
                "prior_state_files": existing_preimage["prior_state_files"],
                "expected_durable_paths": [str(run_root / "latest.json"), str(run_root / (existing_preimage["prior_run_id"] + ".json")),
                                           str(plan_root / "latest.json"), str(plan_root / (existing_preimage["prior_run_id"] + ".json"))]
                    + ([] if run_id == existing_preimage["prior_run_id"] else
                       [str(run_root / expected_run), str(plan_root / expected_run)]),
                "allowed_transition": "preserve prior versioned run/product bytes; latest may advance only to this exact validated POST/GET run",
            }),
            "owner_state_acceptance": ({"mode": "FRESH_TARGET", "prior_target_state": "ABSENT"}
                                        if existing_preimage is None else {
                "mode": "CURRENT13_EXISTING_TARGET_NONDESTRUCTIVE",
                "preimage_verified": True,
                "prior_run_id": existing_preimage["prior_run_id"],
                "prior_product_sha256": existing_preimage["prior_product_sha256"],
                "prior_input_identity": existing_preimage["prior_input_identity"],
                "prior_version_files_preserved": True,
                "post_owner_write_set": current13_state_check,
            }),
            "safety": common.SAFETY,
        }
        contract = release["contract"]
        binding = common.build_binding(identity, enabled=True,
                                       canary_path=output_dir / ".plan-canary-validation.json",
                                       canary_sha256="0" * 64)
        pending_path = output_dir / ".plan-canary-validation.json"
        final_path = output_dir / "plan-canary.json"
        canary_raw = _json_bytes(canary)
        _write_exclusive(pending_path, canary_raw)
        binding["plan_activation_receipt"]["sha256"] = common.sha256_bytes(canary_raw)
        contract.validate_binding(binding, release["app_root"],
                                  expected_owner_app=release["app_root"])
        pending_path.rename(final_path)
        binding["plan_activation_receipt"]["path"] = str(final_path)
        contract.validate_binding(binding, release["app_root"],
                                  expected_owner_app=release["app_root"])
        receipt = {
            "schema_version": "manager_daily_chain.plan_canary_operation.v1",
            "status": common.CANARY_STATUS,
            "canary_path": str(final_path),
            "canary_sha256": common.sha256_bytes(canary_raw),
            "api_app_root": str(release["app_root"]),
            "manager_state_root": str(state_root),
            "target_trade_date": target,
            "run_id": run_id,
            "product_sha256": product_sha,
            "input_identity": input_identity,
            "owner_attempt_state": attempt_state,
            "owner_state_acceptance": ({"mode": "FRESH_TARGET"} if existing_preimage is None else {
                "mode": "CURRENT13_EXISTING_TARGET_NONDESTRUCTIVE",
                "prior_run_id": existing_preimage["prior_run_id"],
                "prior_product_sha256": existing_preimage["prior_product_sha256"],
                "prior_version_files_preserved": True,
                "post_owner_write_set": current13_state_check,
            }),
            "candidate_release_manifest_sha256": release["manifest_sha256"],
            "application_inventory_sha256": release["application_inventory_sha256"],
            "manager_source_inventory_sha256": common.canonical_sha(release["binding_files"]),
            "activation_status": "NOT_ACTIVATED",
            "launchctl_called": False,
            "safety": common.SAFETY,
        }
        _write_exclusive(output_dir / "operation-receipt.json", _json_bytes(receipt))
        return receipt
    finally:
        service = getattr(app.state, "manager_research_service", None)
        close = getattr(service, "close", None)
        if callable(close):
            close()


def _output_path(value: str | None, target: str, *, default_execution: str = "execution-01") -> Path:
    if value:
        path = Path(value)
        if not path.is_absolute() or path.resolve() != path:
            raise ValueError("CANARY_OUTPUT_PATH_NOT_EXACT")
    else:
        path = common.TASK_ROOT / "receipts" / "plan_canary_runs" / target / default_execution
    receipts_root = common.TASK_ROOT / "receipts"
    if path != receipts_root and receipts_root not in path.parents:
        raise ValueError("CANARY_OUTPUT_OUTSIDE_TASK_RECEIPTS")
    return path


def _load_identity(app_root: Path, api_plist: Path, scheduler_plist: Path):
    release = common.load_release(app_root)
    live = common.current_plists(api_plist, scheduler_plist)
    identity = common.current_identity(app_root, release, live=live)
    return release, live, identity


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", type=Path, required=True,
                        help="exact app directory in the prepared integrated release")
    parser.add_argument("--target-date", default=common.TARGET_DEFAULT)
    parser.add_argument("--api-plist", type=Path, default=common.LIVE_API_PLIST)
    parser.add_argument("--scheduler-plist", type=Path, default=common.LIVE_SCHEDULER_PLIST)
    parser.add_argument("--output-dir", type=str,
                        help="new directory below task receipts; defaults to execution-01 or recovery execution-02")
    parser.add_argument("--execute", action="store_true",
                        help="explicitly run the exact owner POST/GET; writes only target-date plan state")
    parser.add_argument("--recover-existing", action="store_true",
                        help="verify the pinned successful execution-01 POST/GET and write fresh receipts; never calls HTTP")
    parser.add_argument("--verify-only", action="store_true",
                        help="with --recover-existing, validate evidence and current state without writing receipts")
    parser.add_argument("--accept-existing-current13", action="store_true",
                        help="target-20261013 only: read-only exact preflight; add --execute only for parent-owned POST/GET")
    args = parser.parse_args(argv)
    if args.execute and args.recover_existing:
        parser.error("--execute and --recover-existing are mutually exclusive")
    if args.verify_only and not args.recover_existing:
        parser.error("--verify-only requires --recover-existing")
    if args.accept_existing_current13 and args.recover_existing:
        parser.error("--accept-existing-current13 cannot combine with --recover-existing")
    if args.accept_existing_current13 and args.target_date != _CURRENT13_ACCEPTANCE["target_trade_date"]:
        parser.error("--accept-existing-current13 is pinned to 20261013")
    app_root = args.app_root
    release, live, identity = _load_identity(app_root, args.api_plist, args.scheduler_plist)
    now = datetime.now(ZoneInfo("Asia/Hong_Kong"))
    common.require_next_session(args.target_date, app_root, now)
    runtime_roots = common.resolve_api_runtime_roots(live["api"], live["api_env"])
    output = _output_path(args.output_dir, args.target_date,
                          default_execution=("execution-02" if args.recover_existing or args.accept_existing_current13
                                             else "execution-01"))
    if args.accept_existing_current13 and not args.execute and not args.recover_existing:
        if runtime_roots["stage_mode"] != "shared":
            raise ValueError("CURRENT13_ACCEPTANCE_API_STAGE_MODE_NOT_SHARED")
        existing_preimage = _current13_existing_preimage(identity, args.target_date, now)
        if output.exists() or output.is_symlink():
            raise FileExistsError("CURRENT13_ACCEPTANCE_OUTPUT_ALREADY_EXISTS:" + str(output))
        result = {
            "status": "READY_FOR_PARENT_OWNED_CURRENT13_POST_GET_ACCEPTANCE",
            "mode": "READ_ONLY_PREFLIGHT_NO_HTTP_NO_STATE_WRITE",
            "target_trade_date": args.target_date,
            "candidate_release_id": release["manifest"]["candidate"]["release_id"],
            "candidate_release_manifest_sha256": release["manifest_sha256"],
            "candidate_application_inventory_sha256": release["application_inventory_sha256"],
            "candidate_owner_source_inventory_sha256": release["owner_inventory_sha256"],
            "active_api_app_root": str(identity["active_api_app_root"]),
            "manager_state_root": str(identity["state_root"]),
            "api_runtime_stage_mode": runtime_roots["stage_mode"],
            "existing_target_preimage": existing_preimage,
            "output_dir_if_parent_executes": str(output),
            "parent_owned_execute_command": [
                sys.executable, "-B", str(Path(__file__).resolve()),
                "--app-root", str(app_root), "--target-date", args.target_date,
                "--output-dir", str(output), "--accept-existing-current13", "--execute",
            ],
            "http_calls": 0,
            "owner_state_writes": 0,
            "launchctl_called": False,
            "activation_status": "NOT_ACTIVATED",
            "safety": common.SAFETY,
        }
    elif args.recover_existing:
        source_dir = common.TASK_ROOT / _RECOVERY_SOURCE_RELATIVE
        if output.parent != source_dir.parent or output == source_dir:
            raise ValueError("CANARY_RECOVERY_OUTPUT_MUST_BE_NEW_SIBLING")
        if output.exists() or output.is_symlink():
            raise FileExistsError("CANARY_RECOVERY_OUTPUT_ALREADY_EXISTS:" + str(output))
        if runtime_roots["stage_mode"] != "shared":
            raise ValueError("CANARY_RECOVERY_API_STAGE_MODE_NOT_SHARED")
        verified = _verify_recovered_owner(identity, args.target_date, now)
        verified["runtime_stage_mode"] = runtime_roots["stage_mode"]
        if args.verify_only:
            result = {
                "status": "RECOVERY_EVIDENCE_VALID_NO_HTTP_NO_WRITE",
                "recovery_source_dir": str(source_dir),
                "output_dir_if_written": str(output),
                "target_trade_date": verified["target_trade_date"],
                "run_id": verified["run_id"],
                "product_sha256": verified["product_sha256"],
                "input_identity": verified["input_identity"],
                "owner_attempt_state": verified["attempt_state"],
                "api_runtime_stage_mode": verified["runtime_stage_mode"],
                "owner_evidence": verified["owner_evidence_summary"],
                "protected_dates_verified": True,
                "durable_write_set_verified": True,
                "owner_mutex_nonblocking_free_proof": True,
                "owner_post_replayed": False,
                "owner_get_replayed": False,
                "formal_state_writes_performed": False,
                "launchctl_called": False,
                "safety": common.SAFETY,
            }
        else:
            output.mkdir(parents=True, exist_ok=False)
            result = _write_recovered_canary(identity, output, verified)
    elif not args.execute:
        target_state_paths = (
            identity["state_root"] / "workspace_plan_runs" / args.target_date,
            identity["state_root"] / "workspace_plans" / args.target_date,
            identity["state_root"] / ".locks" / f"{args.target_date}-workspace-plan-refresh.mutex",
        )
        target_preexisting = [str(path) for path in target_state_paths
                              if path.exists() or path.is_symlink()]
        result = {
            "status": "DRY_RUN_NO_HTTP_NO_WRITE",
            "scope": common.CANARY_NEXT_SCOPE,
            "execution_mode": common.EXECUTION_MODE,
            "current_clock_local": now.isoformat(),
            "target_trade_date": args.target_date,
            "api_app_root_to_execute": str(app_root),
            "active_api_app_root": str(identity["active_api_app_root"]),
            "release_manifest_path": str(release["manifest_path"]),
            "release_manifest_sha256": release["manifest_sha256"],
            "application_inventory_sha256": release["application_inventory_sha256"],
            "owner_source_inventory_sha256": release["owner_inventory_sha256"],
            "manager_state_root": str(identity["state_root"]),
            "target_owner_state_preexisting_paths": target_preexisting,
            "target_state_clear_for_explicit_execute": not target_preexisting,
            "api_runtime_stage_mode": runtime_roots["stage_mode"],
            "api_runtime_roots": {k: str(v) if isinstance(v, Path) else v
                                   for k, v in runtime_roots.items()},
            "output_dir_if_executed": str(output),
            "http_calls": [],
            "durable_owner_write_paths_if_executed": [
                str(identity["state_root"] / "workspace_plan_runs" / args.target_date / "latest.json"),
                str(identity["state_root"] / "workspace_plans" / args.target_date / "latest.json"),
            ],
            "launchctl_called": False,
            "safety": common.SAFETY,
        }
    else:
        execute_clock = datetime.now(ZoneInfo("Asia/Hong_Kong"))
        common.require_next_session(args.target_date, app_root, execute_clock)
        if sys.executable != identity["python"]:
            raise ValueError("CANARY_EXECUTION_PYTHON_IDENTITY_MISMATCH")
        state_root = identity["state_root"]
        existing_preimage = (_current13_existing_preimage(identity, args.target_date, execute_clock)
                             if args.accept_existing_current13 else None)
        protected = (existing_preimage["protected_dates_sha256"] if existing_preimage is not None
                     else _target_preimage(state_root, args.target_date))
        if output.exists() or output.is_symlink():
            raise FileExistsError("CANARY_OUTPUT_ALREADY_EXISTS:" + str(output))
        output.mkdir(parents=True, exist_ok=False)
        disabled_binding = common.build_binding(identity, enabled=False)
        disabled_binding_path = output / "canary-disabled-binding.json"
        _write_exclusive(disabled_binding_path, _json_bytes(disabled_binding))
        release["contract"].validate_binding(disabled_binding, app_root)
        preimage = {
            "schema_version": "manager_daily_chain.plan_canary_preimage.v1",
            "target_trade_date": args.target_date,
            "current_clock_local": execute_clock.isoformat(),
            "manager_state_root": str(state_root),
            "target_preexisted": existing_preimage is not None,
            "protected_dates_sha256": protected,
            "api_app_root": str(app_root),
            "release_manifest_sha256": release["manifest_sha256"],
            "application_inventory_sha256": release["application_inventory_sha256"],
            "owner_source_inventory_sha256": release["owner_inventory_sha256"],
            "http_calls_expected": [
                "POST " + common.API_BASE_URL + f"/api/v4/manager/research/workspace/refresh?date={args.target_date}",
                "GET " + common.API_BASE_URL + f"/api/v4/manager/research/workspace?date={args.target_date}",
            ],
            "prior_target_owner_state": (None if existing_preimage is None else {
                "run_id": existing_preimage["prior_run_id"],
                "product_sha256": existing_preimage["prior_product_sha256"],
                "input_identity": existing_preimage["prior_input_identity"],
                "files": existing_preimage["prior_state_files"],
                "allowed_transition": "preserve prior run/product files; only latest and at most one new run/product version may change after a valid POST/GET",
            }),
            "safety": common.SAFETY,
        }
        _write_exclusive(output / "state-preimage.json", _json_bytes(preimage))
        try:
            result = asyncio.run(_execute_owner_canary(identity, args.target_date, output,
                                                       protected, disabled_binding_path,
                                                       existing_preimage=existing_preimage))
        except Exception as exc:
            failure = {
                "schema_version": "manager_daily_chain.plan_canary_failure.v1",
                "status": "FAIL_CANNOT_BIND_PLAN_ACTIVATION",
                "error_code": str(exc),
                "target_trade_date": args.target_date,
                "manager_state_root": str(state_root),
                "activation_status": "NOT_ACTIVATED",
                "launchctl_called": False,
                "safety": common.SAFETY,
            }
            if existing_preimage is not None:
                try:
                    failure["prior_owner_state_preservation"] = _assert_current13_failure_preserved(
                        state_root, existing_preimage
                    )
                except Exception as preservation_error:
                    failure["prior_owner_state_preservation"] = {
                        "status": "FAIL_CANNOT_CONFIRM_PRIOR_LATEST_PRESERVED",
                        "error": type(preservation_error).__name__ + ":" + str(preservation_error),
                        "writes": "NOT_ATTEMPTED",
                    }
            _write_exclusive(output / "failure-receipt.json", _json_bytes(failure))
            raise
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
