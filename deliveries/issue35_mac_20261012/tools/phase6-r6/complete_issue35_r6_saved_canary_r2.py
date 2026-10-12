#!/usr/bin/env python3
"""Atomically package the already-saved target-20261013 R6 owner call.

This command never calls HTTP, constructs an API app, invokes an owner, or writes
manager state. It validates immutable execution-03 artifacts, writes and checks
all derived files in a private sibling directory, then publishes the complete
package with a no-replace atomic directory rename.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SELF_SOURCE_SHA256 = "529db3d81ab08769723568ba325575941dcacd53a39dc96e326c9b311d792c79"
FIXED_VALIDATOR_SHA256 = "a67527a80a9d1399ec2eac076c5b27d538971d588918ea7b2ee1921a9f95be34"
COMMON_SHA256 = "d5e8c8aaf591d10df2343dfe1d870019ee431ad708d6478b0863c9cd53a0fa84"
R2_SCOPE_SHA256 = "e38925839c8f63ac06c84e4e901356a7529368c907d81c8bec606be0b93017f1"
R2_REVIEW_SHA256 = "969c75b7a18593b02a45ef3ab7f6c94451054c933b5826ed1359b34fb6527ef5"
TOOLS_ROOT = Path(__file__).resolve().parents[1]
_COMMON_PATH = TOOLS_ROOT / "issue35_phase4_common.py"
_FIXED_VALIDATOR_PATH = Path(__file__).with_name(
    "issue35_phase6_r6_canary_readback_fix.py"
)


def _preimport_sha256(path: Path, label: str) -> str:
    if path.is_symlink() or not path.is_file() or path.resolve(strict=True) != path:
        raise RuntimeError(label + "_PATH_INVALID")
    before = path.lstat()
    raw = path.read_bytes()
    after = path.lstat()
    if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or len(raw) != after.st_size):
        raise RuntimeError(label + "_CHANGED_DURING_READ")
    return hashlib.sha256(raw).hexdigest()


# Pin the shared support file before importing it: it supplies the date,
# release, protected-state and task-root checks used by the offline verifier.
if _preimport_sha256(_COMMON_PATH, "R6_COMPLETION_COMMON") != COMMON_SHA256:
    raise RuntimeError("R6_COMPLETION_COMMON_SHA256_MISMATCH")
if _preimport_sha256(_FIXED_VALIDATOR_PATH, "R6_FIXED_VALIDATOR") != FIXED_VALIDATOR_SHA256:
    raise RuntimeError("R6_FIXED_VALIDATOR_SOURCE_SHA256_MISMATCH")
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))
import issue35_phase4_common as common

if Path(common.__file__).resolve(strict=True) != _COMMON_PATH:
    raise RuntimeError("R6_COMPLETION_COMMON_IMPORT_PATH_MISMATCH")

_FIXED_VALIDATOR_SPEC = importlib.util.spec_from_file_location(
    "issue35_phase6_r6_canary_readback_fix_runtime", _FIXED_VALIDATOR_PATH
)
if _FIXED_VALIDATOR_SPEC is None or _FIXED_VALIDATOR_SPEC.loader is None:
    raise RuntimeError("R6_FIXED_VALIDATOR_UNAVAILABLE")
CANARY = importlib.util.module_from_spec(_FIXED_VALIDATOR_SPEC)
_FIXED_VALIDATOR_SPEC.loader.exec_module(CANARY)

TASK_ROOT = common.TASK_ROOT
TARGET = "20261013"
RELEASE_ID = "issue35-manager-autocontinue-20261012-r6-integrated"
RELEASE_ROOT = TASK_ROOT / "integrated_release" / RELEASE_ID
APP_ROOT = RELEASE_ROOT / "app"
STATE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research"
)
SOURCE_DIR_REL = Path("receipts/plan_canary_runs/20261013/execution-03")
OUTPUT_DIR_REL = Path("receipts/plan_canary_runs/20261013/execution-03-completed")
PARENT_DIR_REL = Path("receipts/phase6-parent-target13-canary")
PARENT_EXECUTION_REL = PARENT_DIR_REL / "parent-execution.json"
PARENT_STDOUT_REL = PARENT_DIR_REL / "stdout.json"
PARENT_STDERR_REL = PARENT_DIR_REL / "stderr.log"
ORIGINAL_CANARY_PATH = TASK_ROOT / "tools/phase6-r6/issue35_phase6_r6_canary.py"

# Immutable pins supplied by the formal review and checked against the saved
# execution artifacts. Tests may pass an isolated pin mapping to the pure
# verifier; the command-line entry point has no pin or path override.
PINS: dict[str, Any] = {
    "target": TARGET,
    "release_id": RELEASE_ID,
    "release_root": str(RELEASE_ROOT),
    "app_root": str(APP_ROOT),
    "release_manifest_sha256": "a63b80727953068d123f768ab608c5a6cf45758aa3ca234c71a8c8892d7cfaf7",
    "application_inventory_sha256": "5244040fa11b2721a84b92d30d6189f4da83b2d3f8eb99259ba60f3e7d993b5d",
    "owner_source_inventory_sha256": "c99fa01f8b946bae46da2c7982cd9bc564e0085ecdd769f983600b3dee41d52e",
    "state_root": str(STATE_ROOT),
    "scope_rel": "PHASE6_GET_DTO_AND_SAVED_CANARY_COMPLETION_SCOPE.md",
    "scope_sha256": "c2b5048da04b133722826c5e1b859e7ef8cbab8c63502c4864cd893ba519620c",
    "review_rel": "review/phase6-execution03-readback/independent-review.json",
    "review_sha256": "362a8b53ba07a7c5e7159683f5e4c618244bd500d6faa13d43fa2b925e1ffdc2",
    "original_canary_path": str(ORIGINAL_CANARY_PATH),
    "original_canary_sha256": "642b81a3f50b54dd1fa7ac688d87162004a01c08cb494c8a402fe55e168e7c5e",
    "parent_execution_rel": str(PARENT_EXECUTION_REL),
    "parent_execution_sha256": "9b24e6688f0b75ff1d38fee727397e98d392eb8c95a52fe1dab45234935647a7",
    "parent_stdout_rel": str(PARENT_STDOUT_REL),
    "parent_stdout_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "parent_stderr_rel": str(PARENT_STDERR_REL),
    "parent_stderr_sha256": "9022f08b688a9059c9154f4d01843e49ea638498085230355fc3321900c0c4a8",
    "parent_exit_code": 1,
    "parent_finished_utc": "2026-10-11T22:03:31.528580+00:00",
    "parent_interpreter": "/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python",
    "source_dir_rel": str(SOURCE_DIR_REL),
    "output_dir_rel": str(OUTPUT_DIR_REL),
    "preimage": {
        "path": "state-preimage.json",
        "sha256": "1f37c32b04a35821dcce645e580fd85f7c52b19ee749c9d41cfc50d9c0b0bfd9",
        "bytes": 7146,
    },
    "failure": {
        "path": "failure-receipt.json",
        "sha256": "f2db8ef16a9592b6dcf3a4d8330c5b1a94cb2a96b26ad0ba74ad4db0efd3f703",
        "bytes": 750,
    },
    "disabled_binding": {
        "path": "canary-disabled-binding.json",
        "sha256": "7fb32b88c2b8cba2ecbb117e070066536cd16f4d88ff6649fb9b3d345a346a55",
        "bytes": 48088,
    },
    "archived": {
        "run_id": "d8a35106712a4387accf214c3ee3772d",
        "input_identity": "3c3f32668945d572af760fdc9b36ad5c577a7167720dc8aaba3fd60ccae9bbd3",
        "product_sha256": "7ba36ad92af7cccaadbcdacca3a2eddc9488a80e28ddd9185ebba2e5afffc49c",
        "run_bytes": 356369,
        "run_sha256": "9ca32cee34b42727666c6c96e0cc9396a387bc48e332f232621232c6dbd1aee2",
        "product_bytes": 40992670,
        "product_sha256_file": "777c6496402ea7d2313ed7c09ff7be2ae1e5597659bcbfb6b42fe3fdd051522a",
        "state": "PARTIAL",
        "release_manifest_sha256": "7aa0653999eb1b126c0f0e7420db8a278d7340831653a75ab1286fb292ea7f85",
    },
    "current_before": {
        "run_id": "357d984e400541a48c41f65ec0018b62",
        "input_identity": "efbf9d580a587edeb58fb80fa4358b45afe45a5d10236f28ad1d3d9d50daa0c9",
        "product_sha256": "ae8b8cfc4f1e44003aa75d803ca29fa6e1e088766ae98b5c0471884f699f22c3",
        "run_bytes": 356369,
        "run_sha256": "f2b9288197aa94ae101225e8fdb5245ea10c96a838cc77441bbe4ff18224a834",
        "product_bytes": 40992670,
        "product_sha256_file": "99a31d918381320e493bc518cdfa6db91f4ee1e0ed2bbfb5120ca39a18e7aad3",
        "state": "PARTIAL",
        "release_manifest_sha256": "ccf0bbec4b58910f180320e4288f09e0af2a8143c542f2183eab977d01746b9f",
    },
    "fresh": {
        "run_id": "92f257a7a0a841c081d48005f8a3fe3e",
        "input_identity": "1d10c2e881ddda942884e7bc5252b0897eb65a2846f3a98cad97ca237b5c88af",
        "product_sha256": "2ed6871c47825caca03b21a3fe49b6a35b4dd5605f2b5c985f043ce6cbb1d78f",
        "attempt_sha256": "8a057dab3239183db14c06cee13d75644f80d186db8168fe88c48169f4c2fbf7",
        "run_file_sha256": "10a676d659467a1fb45f84b5a4646bd0cd75279c4a4471e1bb5861172d3b61fa",
        "product_file_sha256": "82dd41fac020e8ddaef5854ab33af427480305e27673253ba5de96eef3097a4d",
        "run_bytes": 356369,
        "product_bytes": 40992670,
        "state": "PARTIAL",
    },
    "refresh": {
        "method": "POST",
        "url": "http://127.0.0.1:8873/api/v4/manager/research/workspace/refresh?date=20261013",
        "evidence_path": "refresh.http-evidence.json",
        "evidence_sha256": "4fcb6e3008c853fdb215add9ae03e25d4ff79d52fc11d0b6259940dd43496553",
        "evidence_bytes": 53658359,
        "response_path": "refresh.response.bin",
        "response_sha256": "8a9d367e81cdeaab65e582bb61209aaf894086c9c83995839a1662a6c7c41729",
        "response_bytes": 41768246,
    },
    "readback": {
        "method": "GET",
        "url": "http://127.0.0.1:8873/api/v4/manager/research/workspace?date=20261013",
        "evidence_path": "readback.http-evidence.json",
        "evidence_sha256": "db52eff49454dcf659eef928bbce52ca4222a0949c1f0dbe481b3e7d60a6c9e9",
        "evidence_bytes": 53661632,
        "response_path": "readback.response.bin",
        "response_sha256": "edc9f989cccde5b33372f1e961a0aabfffd4f48ec2b4e504d5f2847450e91bec",
        "response_bytes": 41770154,
    },
}

EXPECTED_SOURCE_FILES = {
    "state-preimage.json", "failure-receipt.json", "canary-disabled-binding.json",
    "refresh.response.bin", "refresh.http-evidence.json",
    "readback.response.bin", "readback.http-evidence.json",
}
EXPECTED_PROTECTED_KEYS = {
    f"{folder}/{date}" for folder in ("workspace_plan_runs", "workspace_plans")
    for date in common.PROTECTED_DATES
}


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _stable_bytes(path: Path, label: str, *, expected_bytes: int | None = None,
                  expected_sha256: str | None = None) -> bytes:
    if path.is_symlink() or not path.is_file() or path.resolve(strict=True) != path:
        raise ValueError(label + "_NOT_EXACT_FILE")
    before = path.lstat()
    if expected_bytes is not None and before.st_size != expected_bytes:
        raise ValueError(label + "_SIZE_MISMATCH")
    raw = path.read_bytes()
    after = path.lstat()
    if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or len(raw) != after.st_size):
        raise ValueError(label + "_CHANGED_DURING_READ")
    digest = common.sha256_bytes(raw)
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError(label + "_SHA256_MISMATCH")
    return raw


def _json_record(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(label + "_INVALID_JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(label + "_INVALID_JSON")
    return value


def _aware_hk(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(label + "_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(label + "_TIME_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(label + "_TIME_INVALID")
    return parsed.astimezone(ZoneInfo("Asia/Hong_Kong"))


def _exact_directory(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_dir() or path.resolve(strict=True) != path:
        raise ValueError(label + "_DIRECTORY_INVALID")


def _verify_source_pins() -> None:
    raw = _stable_bytes(Path(__file__).resolve(), "R6_COMPLETION_SOURCE")
    placeholder = b'SELF_SOURCE_SHA256 = "' + b"0" * 64 + b'"'
    normalized, substitutions = re.subn(
        rb'(?m)^SELF_SOURCE_SHA256 = "[0-9a-f]{64}"$', placeholder, raw
    )
    if substitutions != 1 or common.sha256_bytes(normalized) != SELF_SOURCE_SHA256:
        raise ValueError("R6_COMPLETION_SOURCE_SELF_PIN_MISMATCH")
    _stable_bytes(_FIXED_VALIDATOR_PATH, "R6_FIXED_VALIDATOR_SOURCE",
                  expected_sha256=FIXED_VALIDATOR_SHA256)
    _stable_bytes(_COMMON_PATH, "R6_COMPLETION_COMMON_SOURCE",
                  expected_sha256=COMMON_SHA256)
    if Path(common.__file__).resolve(strict=True) != _COMMON_PATH:
        raise ValueError("R6_COMPLETION_COMMON_IMPORT_PATH_MISMATCH")


def _verify_scope_and_review_pins(task_root: Path, pins: dict[str, Any]) -> None:
    _stable_bytes(task_root / pins["scope_rel"], "R6_COMPLETION_SCOPE",
                  expected_sha256=pins["scope_sha256"])
    report_raw = _stable_bytes(task_root / pins["review_rel"], "R6_FORMAL_REVIEW",
                               expected_sha256=pins["review_sha256"])
    report = _json_record(report_raw, "R6_FORMAL_REVIEW")
    verdict = report.get("verdict")
    if (not isinstance(verdict, dict)
            or verdict.get("REVIEWED") != "PASS_DIAGNOSIS"
            or verdict.get("status") != "FAIL_BOUNDED_VALIDATOR_FALSE_NEGATIVE"):
        raise ValueError("R6_FORMAL_REVIEW_VERDICT_MISMATCH")
    r2_scope = _stable_bytes(task_root / "PHASE6_SAVED_COMPLETION_ATOMIC_R2_SCOPE.md",
                             "R6_ATOMIC_R2_SCOPE", expected_sha256=R2_SCOPE_SHA256)
    del r2_scope
    r2_review_raw = _stable_bytes(
        task_root / "review/phase6-get-dto-saved-completion/independent-review.json",
        "R6_ATOMIC_R2_INPUT_REVIEW", expected_sha256=R2_REVIEW_SHA256,
    )
    r2_review = _json_record(r2_review_raw, "R6_ATOMIC_R2_INPUT_REVIEW")
    r2_verdict = r2_review.get("verdict")
    p1 = r2_verdict.get("P1") if isinstance(r2_verdict, dict) else None
    p2 = r2_verdict.get("P2") if isinstance(r2_verdict, dict) else None
    codes = {
        row.get("code") for row in (p1 if isinstance(p1, list) else [])
        + (p2 if isinstance(p2, list) else []) if isinstance(row, dict)
    }
    if (not isinstance(r2_verdict, dict)
            or r2_verdict.get("REVIEWED") != "FAIL_BOUNDED"
            or r2_verdict.get("status") != "FAIL_BOUNDED_CANARY_PUBLISHED_BEFORE_FINAL_ACCEPTANCE_GATES"
            or codes != {"STAGE_ACCEPTABLE_CANARY_LEFT_ON_COMPLETION_FAILURE",
                         "COMMON_VERIFICATION_SUPPORT_MODULE_NOT_PINNED_BY_COMPLETION_CLI"}):
        raise ValueError("R6_ATOMIC_R2_INPUT_REVIEW_VERDICT_MISMATCH")


def _read_json_pin(path: Path, pin: dict[str, Any], label: str) -> tuple[dict[str, Any], bytes]:
    raw = _stable_bytes(path, label, expected_bytes=pin.get("bytes"),
                        expected_sha256=pin.get("sha256"))
    return _json_record(raw, label), raw


def _release_check(release: dict[str, Any], pins: dict[str, Any]) -> None:
    if (str(release.get("release_root")) != pins["release_root"]
            or str(release.get("app_root")) != pins["app_root"]
            or release.get("manifest_sha256") != pins["release_manifest_sha256"]
            or release.get("application_inventory_sha256") != pins["application_inventory_sha256"]
            or release.get("owner_inventory_sha256") != pins["owner_source_inventory_sha256"]
            or release.get("manifest", {}).get("activation_status") != "NOT_ACTIVATED"
            or release.get("manifest", {}).get("candidate", {}).get("release_id") != pins["release_id"]
            or release.get("manifest", {}).get("candidate", {}).get("app_root") != pins["app_root"]):
        raise ValueError("R6_SAVED_COMPLETION_CANDIDATE_IDENTITY_MISMATCH")
    app_root = Path(pins["app_root"])
    release_root = Path(pins["release_root"])
    if (app_root.is_symlink() or app_root.resolve(strict=True) != app_root
            or release_root.is_symlink() or release_root.resolve(strict=True) != release_root):
        raise ValueError("R6_SAVED_COMPLETION_CANDIDATE_PATH_NOT_EXACT")
    raw = _stable_bytes(Path(release["manifest_path"]), "R6_SAVED_COMPLETION_MANIFEST",
                        expected_sha256=pins["release_manifest_sha256"])
    if json.loads(raw) != release["manifest"]:
        raise ValueError("R6_SAVED_COMPLETION_MANIFEST_CONTENT_MISMATCH")


def _parent_execution_check(task_root: Path, pins: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
    parent, parent_raw = _read_json_pin(task_root / pins["parent_execution_rel"],
                                        {"sha256": pins["parent_execution_sha256"]},
                                        "R6_PARENT_EXECUTION")
    original_output_dir = task_root / pins["source_dir_rel"]
    expected_argv = [
        pins["parent_interpreter"], "-B", pins["original_canary_path"],
        "--app-root", pins["app_root"], "--target-date", pins["target"],
        "--output-dir", str(original_output_dir), "--accept-existing-current13", "--execute",
    ]
    if (parent.get("argv") != expected_argv
            or parent.get("exit_code") != pins["parent_exit_code"]
            or parent.get("finished_utc") != pins["parent_finished_utc"]
            or parent.get("stdout_sha256") != pins["parent_stdout_sha256"]
            or parent.get("stderr_sha256") != pins["parent_stderr_sha256"]
            or parent.get("stdout_path") != str(task_root / pins["parent_stdout_rel"])
            or parent.get("stderr_path") != str(task_root / pins["parent_stderr_rel"])):
        raise ValueError("R6_PARENT_EXECUTION_IDENTITY_MISMATCH")
    _stable_bytes(task_root / pins["parent_stdout_rel"], "R6_PARENT_STDOUT",
                  expected_sha256=pins["parent_stdout_sha256"])
    stderr = _stable_bytes(task_root / pins["parent_stderr_rel"], "R6_PARENT_STDERR",
                           expected_sha256=pins["parent_stderr_sha256"])
    if b"CANARY_OWNER_READBACK_MISMATCH" not in stderr:
        raise ValueError("R6_PARENT_FAILURE_DIAGNOSTIC_MISMATCH")
    original = _stable_bytes(Path(pins["original_canary_path"]), "R6_ORIGINAL_CANARY_SOURCE",
                             expected_sha256=pins["original_canary_sha256"])
    if b"httpx.ASGITransport(app=app)" not in original:
        raise ValueError("R6_PARENT_TRANSPORT_SOURCE_NOT_PINNED")
    return parent, parent_raw


def _r4b_state_snapshot(source_preimage: dict[str, Any], receipt_pins: dict[str, Any],
                        state_root: Path, pins: dict[str, Any]) -> dict[str, Any]:
    prior = source_preimage.get("prior_target_owner_state")
    if not isinstance(prior, dict):
        raise ValueError("R6_SAVED_PREIMAGE_PRIOR_STATE_MISSING")
    archived = prior.get("archived_generation")
    current = prior.get("r4b_current_generation")
    files = prior.get("files")
    if not isinstance(archived, dict) or not isinstance(current, dict) or not isinstance(files, dict):
        raise ValueError("R6_SAVED_PREIMAGE_GENERATIONS_INVALID")
    for name, row, expected in (
        ("archived", archived, pins["archived"]),
        ("current", current, pins["current_before"]),
    ):
        if any(row.get(key) != expected[key] for key in
               ("run_id", "product_sha256", "input_identity", "state")):
            raise ValueError("R6_SAVED_PREIMAGE_GENERATION_MISMATCH:" + name)
    file_expectations = {
        "archived_run": ("archived", "run_bytes", "run_sha256"),
        "archived_product": ("archived", "product_bytes", "product_sha256_file"),
        "current_run": ("current_before", "run_bytes", "run_sha256"),
        "current_run_latest": ("current_before", "run_bytes", "run_sha256"),
        "current_product": ("current_before", "product_bytes", "product_sha256_file"),
        "current_product_latest": ("current_before", "product_bytes", "product_sha256_file"),
    }
    expected_names = {
        "archived_run": f"workspace_plan_runs/{pins['target']}/{pins['archived']['run_id']}.json",
        "archived_product": f"workspace_plans/{pins['target']}/{pins['archived']['run_id']}.json",
        "current_run": f"workspace_plan_runs/{pins['target']}/{pins['current_before']['run_id']}.json",
        "current_run_latest": f"workspace_plan_runs/{pins['target']}/latest.json",
        "current_product": f"workspace_plans/{pins['target']}/{pins['current_before']['run_id']}.json",
        "current_product_latest": f"workspace_plans/{pins['target']}/latest.json",
    }
    for label, (generation, size_key, sha_key) in file_expectations.items():
        row = files.get(label)
        expected = pins[generation]
        if (not isinstance(row, dict) or row.get("bytes") != expected[size_key]
                or row.get("sha256") != expected[sha_key]
                or row.get("path") != str(state_root / expected_names[label])):
            raise ValueError("R6_SAVED_PREIMAGE_FILE_PIN_MISMATCH:" + label)
    saved_refs = source_preimage.get("r4b_two_generation_receipt_pins")
    expected_refs = {
        key: receipt_pins.get(key) for key in (
            "r4b_state_preimage_path", "r4b_state_preimage_sha256",
            "r4b_canary_path", "r4b_canary_sha256", "contract_review_path",
            "contract_review_sha256",
        )
    }
    if (not isinstance(saved_refs, dict)
            or any(saved_refs.get(key) != value for key, value in expected_refs.items())):
        raise ValueError("R6_SAVED_PREIMAGE_R4B_RECEIPT_PINS_MISMATCH")
    if any(receipt_pins.get(name, {}).get(key) != pins[generation].get(key)
           for name, generation, keys in (
               ("archived", "archived", ("run_id", "product_sha256", "input_identity", "state")),
               ("current", "current_before", ("run_id", "product_sha256", "input_identity", "state")),
           ) for key in keys):
        raise ValueError("R6_SAVED_PREIMAGE_RECEIPT_GENERATION_MISMATCH")
    protected = source_preimage.get("protected_dates_sha256")
    if not isinstance(protected, dict) or set(protected) != EXPECTED_PROTECTED_KEYS:
        raise ValueError("R6_SAVED_PREIMAGE_PROTECTED_DATE_MAPS_INVALID")
    if protected != receipt_pins.get("protected_dates_sha256"):
        raise ValueError("R6_SAVED_PREIMAGE_PROTECTED_DATE_PINS_MISMATCH")
    return {
        "target_trade_date": pins["target"],
        "manager_state_root": str(state_root),
        "archived": archived,
        "current": current,
        "state_files": files,
        "protected_dates_sha256": protected,
        "receipt_pins": receipt_pins,
        "r4b_two_generation_receipt_pins": saved_refs,
    }


def _validate_disabled_binding(source_dir: Path, release: dict[str, Any],
                               state_root: Path, pins: dict[str, Any]) -> tuple[dict[str, Any], str]:
    pin = pins["disabled_binding"]
    value, raw = _read_json_pin(source_dir / pin["path"], pin, "R6_DISABLED_BINDING")
    if (value.get("schema_version") != common.BINDING_SCHEMA
            or value.get("enabled") is not False
            or value.get("app_root") != pins["app_root"]
            or value.get("manager_state_root") != str(state_root)
            or value.get("files") != release["binding_files"]
            or value.get("research_only") is not True
            or value.get("production_allowed") is not False
            or value.get("buy_gate_updated") is not False
            or value.get("orders_sent") is not False
            or value.get("announcement_collection_enabled") is not False
            or value.get("plan_material_refresh_only") is not False):
        raise ValueError("R6_DISABLED_BINDING_IDENTITY_MISMATCH")
    release["contract"].validate_binding(value, release["app_root"])
    return value, common.sha256_bytes(raw)


def _read_saved_http_pair(source_dir: Path, label: str, pin: dict[str, Any]
                          ) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    body_path = source_dir / pin["response_path"]
    evidence_path = source_dir / pin["evidence_path"]
    body_raw = _stable_bytes(body_path, "R6_" + label.upper() + "_BODY",
                             expected_bytes=pin["response_bytes"],
                             expected_sha256=pin["response_sha256"])
    evidence_raw = _stable_bytes(evidence_path, "R6_" + label.upper() + "_EVIDENCE",
                                 expected_bytes=pin["evidence_bytes"],
                                 expected_sha256=pin["evidence_sha256"])
    body = _json_record(body_raw, "R6_" + label.upper() + "_BODY")
    evidence = _json_record(evidence_raw, "R6_" + label.upper() + "_EVIDENCE")
    response = evidence.get("response")
    request = evidence.get("request")
    if (evidence.get("schema_version") != "manager_daily_chain.plan_owner_http_evidence.v1"
            or type(evidence.get("http_status")) is not int or evidence.get("http_status") != 200
            or evidence.get("content_type") != "application/json"
            or not isinstance(request, dict) or request.get("method") != pin["method"]
            or request.get("url") != pin["url"]
            or not isinstance(response, dict)
            or response.get("path") != str(body_path)
            or response.get("sha256") != pin["response_sha256"]
            or type(response.get("bytes")) is not int
            or response.get("bytes") != pin["response_bytes"]
            or evidence.get("readback") != body):
        raise ValueError("R6_SAVED_" + label.upper() + "_HTTP_EVIDENCE_MISMATCH")
    return body, evidence, {
        "method": pin["method"], "url": pin["url"], "http_status": 200,
        "response_path": str(body_path), "response_sha256": pin["response_sha256"],
        "response_bytes": pin["response_bytes"],
        "evidence_path": str(evidence_path), "evidence_sha256": pin["evidence_sha256"],
        "evidence_bytes": pin["evidence_bytes"],
    }


def _validate_original_failure(source_dir: Path, pins: dict[str, Any],
                               state_root: Path) -> tuple[dict[str, Any], str]:
    failure, raw = _read_json_pin(source_dir / pins["failure"]["path"],
                                  pins["failure"], "R6_ORIGINAL_FAILURE")
    preservation = failure.get("prior_owner_state_preservation")
    if (failure.get("schema_version") != "manager_daily_chain.plan_canary_failure.v1"
            or failure.get("status") != "FAIL_CANNOT_BIND_PLAN_ACTIVATION"
            or failure.get("error_code") != "CANARY_OWNER_READBACK_MISMATCH"
            or failure.get("target_trade_date") != pins["target"]
            or failure.get("manager_state_root") != str(state_root)
            or failure.get("activation_status") != "NOT_ACTIVATED"
            or failure.get("launchctl_called") is not False
            or failure.get("safety") != common.SAFETY
            or not isinstance(preservation, dict)
            or preservation.get("status") != "FAIL_CANNOT_CONFIRM_EXACT_FAILED_JOURNAL_AND_PRIOR_PRODUCT_LATEST_PRESERVED"
            or preservation.get("error") != "ValueError:R6_FAILURE_PRODUCT_WRITE_SET_MISMATCH"
            or preservation.get("writes") != "NOT_ATTEMPTED"):
        raise ValueError("R6_ORIGINAL_FAILURE_RECEIPT_MISMATCH")
    return failure, common.sha256_bytes(raw)


def _check_original_preimage(source_preimage: dict[str, Any], release: dict[str, Any],
                             state_root: Path, pins: dict[str, Any]) -> datetime:
    preimage_clock = _aware_hk(source_preimage.get("current_clock_local"), "R6_PREIMAGE")
    expected_calls = [
        "POST " + pins["refresh"]["url"],
        "GET " + pins["readback"]["url"],
    ]
    if (source_preimage.get("schema_version") != "manager_daily_chain.plan_canary_preimage.v1"
            or source_preimage.get("target_trade_date") != pins["target"]
            or source_preimage.get("target_preexisted") is not True
            or source_preimage.get("manager_state_root") != str(state_root)
            or source_preimage.get("api_app_root") != pins["app_root"]
            or source_preimage.get("release_manifest_sha256") != pins["release_manifest_sha256"]
            or source_preimage.get("application_inventory_sha256") != pins["application_inventory_sha256"]
            or source_preimage.get("owner_source_inventory_sha256") != pins["owner_source_inventory_sha256"]
            or source_preimage.get("safety") != common.SAFETY
            or source_preimage.get("http_calls_expected") != expected_calls):
        raise ValueError("R6_ORIGINAL_PREIMAGE_RELEASE_OR_CALL_CONTRACT_MISMATCH")
    common.require_next_session(pins["target"], release["app_root"], preimage_clock)
    return preimage_clock


def _check_owner_clock_and_manual_context(refresh: dict[str, Any], readback: dict[str, Any],
                                         attempt: dict[str, Any], parent: dict[str, Any],
                                         preimage_clock: datetime, now: datetime,
                                         pins: dict[str, Any]) -> dict[str, str]:
    refresh_context = refresh.get("execution_context")
    readback_context = readback.get("execution_context")
    if (not isinstance(refresh_context, dict) or refresh_context != readback_context
            or refresh_context.get("trigger_kind") != "MANUAL"
            or refresh_context.get("timing") != "UNCLASSIFIED"
            or refresh_context.get("scheduled_for") is not None
            or refresh_context.get("natural_run_verified") is not False
            or not isinstance(refresh_context.get("trigger_id"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", refresh_context["trigger_id"])):
        raise ValueError("R6_OWNER_MANUAL_CONTEXT_MISMATCH")
    attempt_context = attempt.get("execution_context")
    if (not isinstance(attempt_context, dict)
            or attempt_context.get("trigger_kind") != "MANUAL"
            or attempt_context.get("natural_run_verified") is not False
            or attempt_context.get("scheduled_for") is not None):
        raise ValueError("R6_TERMINAL_ATTEMPT_MANUAL_CONTEXT_MISMATCH")
    request_started = _aware_hk(refresh_context.get("started_at"), "R6_OWNER_REQUEST_START")
    context_finished = _aware_hk(refresh_context.get("finished_at"), "R6_OWNER_CONTEXT_FINISH")
    attempt_started = _aware_hk(attempt.get("started_at"), "R6_ATTEMPT_START")
    attempt_finished = _aware_hk(attempt.get("finished_at"), "R6_ATTEMPT_FINISH")
    post_checked = _aware_hk(refresh.get("plan_product", {}).get("last_checked_at"),
                             "R6_POST_PRODUCT_CHECK")
    get_checked = _aware_hk(readback.get("plan_product", {}).get("last_checked_at"),
                            "R6_GET_PRODUCT_CHECK")
    parent_finished = _aware_hk(parent.get("finished_utc"), "R6_PARENT_FINISH")
    current = now.astimezone(ZoneInfo("Asia/Hong_Kong"))
    if (request_started != attempt_started
            or not (preimage_clock <= request_started <= context_finished
                    <= attempt_finished <= post_checked <= get_checked <= parent_finished <= current)
            or current.date() != preimage_clock.date()):
        raise ValueError("R6_OWNER_EXECUTION_CLOCK_ORDER_INVALID")
    return {
        "preimage_clock_local": preimage_clock.isoformat(),
        "owner_request_started_at_local": request_started.isoformat(),
        "owner_context_finished_at_local": context_finished.isoformat(),
        "terminal_attempt_started_at_local": attempt_started.isoformat(),
        "terminal_attempt_finished_at_local": attempt_finished.isoformat(),
        "post_product_checked_at_local": post_checked.isoformat(),
        "get_product_checked_at_local": get_checked.isoformat(),
        "parent_process_finished_at_utc": parent.get("finished_utc"),
        "offline_acceptance_clock_local": current.isoformat(),
        "http_transport_timestamps": "NOT_CAPTURED; owner-context, product-readback and parent-finish timestamps are preserved separately",
    }


def _verify_current_fresh_state(state_root: Path, snapshot: dict[str, Any],
                                refresh: dict[str, Any], pins: dict[str, Any]
                                ) -> dict[str, Any]:
    attempt = refresh.get("workspace_plan_attempt")
    product = refresh.get("plan_product")
    if (not isinstance(attempt, dict) or not isinstance(product, dict)
            or product.get("status") != "CURRENT"):
        raise ValueError("R6_SAVED_OWNER_RESULT_NOT_FRESH")
    # The pair was already validated against POST and GET by the caller. Validate
    # its durable state through the original current13 write-set checker.
    result = CANARY._verify_current13_success_write_set(
        state_root, pins["target"], product.get("run_id"), product.get("sha256"),
        refresh.get("input_identity"), attempt, "FRESH", snapshot,
    )
    if (product.get("run_id") != pins["fresh"]["run_id"]
            or product.get("sha256") != pins["fresh"]["product_sha256"]
            or refresh.get("input_identity") != pins["fresh"]["input_identity"]
            or attempt.get("sha256") != pins["fresh"]["attempt_sha256"]
            or attempt.get("state") != pins["fresh"]["state"]):
        raise ValueError("R6_SAVED_FRESH_RESULT_PIN_MISMATCH")
    if result.get("status") != "PASS_R6_FRESH_MATERIALIZATION_PRIOR_GENERATIONS_PRESERVED":
        raise ValueError("R6_SAVED_FRESH_STATE_WRITE_SET_NOT_ACCEPTED")
    for path, expected_bytes, expected_sha in (
        (state_root / "workspace_plan_runs" / pins["target"] / "latest.json",
         pins["fresh"]["run_bytes"], pins["fresh"]["run_file_sha256"]),
        (state_root / "workspace_plan_runs" / pins["target"] / (pins["fresh"]["run_id"] + ".json"),
         pins["fresh"]["run_bytes"], pins["fresh"]["run_file_sha256"]),
        (state_root / "workspace_plans" / pins["target"] / "latest.json",
         pins["fresh"]["product_bytes"], pins["fresh"]["product_file_sha256"]),
        (state_root / "workspace_plans" / pins["target"] / (pins["fresh"]["run_id"] + ".json"),
         pins["fresh"]["product_bytes"], pins["fresh"]["product_file_sha256"]),
    ):
        _stable_bytes(path, "R6_CURRENT_FRESH_STATE_FILE", expected_bytes=expected_bytes,
                      expected_sha256=expected_sha)
    return result


def _owner_projection(body: dict[str, Any]) -> dict[str, Any]:
    """Retain validator inputs verbatim while omitting unrelated large workspace data."""
    projection: dict[str, Any] = {}
    for key in (
        "schema_version", "target_trade_date", "formal_recommendation_count",
        "store_latest_matches_http_plan_product", "input_identity", "execution_kind",
        "safety", "RESEARCH_ONLY", "production_allowed", "buy_gate_updated", "orders_sent",
    ):
        if key in body:
            projection[key] = body[key]
    product = body.get("plan_product")
    if isinstance(product, dict):
        selected = {
            key: product[key] for key in (
                "status", "consumed", "run_id", "sha256", "original_owner",
                "execution_kind", "input_identity_diagnostics", "run_readback", "last_checked_at",
            ) if key in product
        }
        projection["plan_product"] = selected
    for key in ("persisted_store", "workspace_plan_attempt", "workspace_plan_product_attempt",
                "execution_context"):
        if key in body:
            projection[key] = body[key]
    return projection


def _write_exclusive(path: Path, raw: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(raw)


def _write_projection(output_dir: Path, label: str, projection: dict[str, Any],
                      raw_ref: dict[str, Any], pins: dict[str, Any]) -> dict[str, str]:
    body_path = output_dir / f"{label}.verified-projection.response.bin"
    evidence_path = output_dir / f"{label}.verified-projection.http-evidence.json"
    body_raw = _json_bytes(projection)
    if len(body_raw) > 2 * 1024 * 1024:
        raise ValueError("R6_DERIVED_PROJECTION_EXCEEDS_BINDING_LIMIT")
    _write_exclusive(body_path, body_raw)
    pin = pins[label]
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
            "selected_identity_and_safety_fields_copied_without_transformation": True,
            "raw_http_body": {
                "kind": "RAW_HTTP_BODY", "path": raw_ref["response_path"],
                "sha256": raw_ref["response_sha256"], "bytes": raw_ref["response_bytes"],
            },
            "raw_http_evidence": {
                "kind": "RAW_HTTP_EVIDENCE", "path": raw_ref["evidence_path"],
                "sha256": raw_ref["evidence_sha256"],
            },
        },
    }
    evidence_raw = _json_bytes(evidence)
    if len(evidence_raw) > 2 * 1024 * 1024:
        raise ValueError("R6_DERIVED_PROJECTION_EVIDENCE_EXCEEDS_BINDING_LIMIT")
    _write_exclusive(evidence_path, evidence_raw)
    return {"path": str(evidence_path), "sha256": common.sha256_bytes(evidence_raw)}


def _research_gap_summary(refresh: dict[str, Any], readback: dict[str, Any],
                          attempt: dict[str, Any]) -> dict[str, Any]:
    coverage = attempt.get("input_coverage")
    if not isinstance(coverage, dict):
        raise ValueError("R6_OWNER_INPUT_COVERAGE_MISSING")
    gaps = refresh.get("gaps")
    readback_gaps = readback.get("gaps")
    runtime_gaps = readback.get("runtime_gaps")
    if (not isinstance(gaps, list) or not isinstance(readback_gaps, list)
            or not isinstance(runtime_gaps, list) or gaps != readback_gaps):
        raise ValueError("R6_OWNER_GAP_READBACK_MISMATCH")
    vibe = coverage.get("vibe_binding")
    if not isinstance(vibe, dict):
        raise ValueError("R6_OWNER_VIBE_COVERAGE_MISSING")
    vibe_gaps = vibe.get("gaps")
    return {
        "owner_attempt_state": attempt.get("state"),
        "formal_recommendation_count": refresh.get("formal_recommendation_count"),
        "attempt_summary": attempt.get("summary"),
        "attempt_failure_reasons": attempt.get("failure_reasons"),
        "input_coverage": coverage,
        "top_level_gap_count": len(gaps),
        "top_level_gap_sha256": common.canonical_sha(gaps),
        "representative_top_level_gaps": gaps[:12],
        "runtime_gaps": runtime_gaps,
        "pit_and_source_coverage": {
            "global_market_coverage": coverage.get("global_market_coverage"),
            "attempted_artifact_count": coverage.get("attempted_artifact_count"),
            "verified_artifact_count": coverage.get("verified_artifact_count"),
            "excluded_after_cutoff_count": coverage.get("excluded_after_cutoff_count"),
            "vibe_status": vibe.get("status"),
            "vibe_owner_verification_status": vibe.get("owner_verification_status"),
            "vibe_exact_input_sha_bound": not any(
                isinstance(item, str) and item.startswith("VIBE_EXACT_INPUT_SHA_NOT_BOUND:")
                for item in (vibe_gaps if isinstance(vibe_gaps, list) else [])
            ),
            "vibe_gaps": vibe_gaps,
            "completeness": "CANNOT_CONFIRM",
            "natural_run_verified": False,
        },
        "raw_owner_http_remains_authoritative": True,
    }


def verify_saved_execution(*, task_root: Path = TASK_ROOT,
                           state_root: Path = STATE_ROOT,
                           release: dict[str, Any] | None = None,
                           now: datetime | None = None,
                           pins: dict[str, Any] = PINS,
                           receipt_pins: dict[str, Any] | None = None) -> dict[str, Any]:
    """Pure verification: read pinned artifacts/state and return a bounded proof."""
    task_root = Path(task_root)
    state_root = Path(state_root)
    _exact_directory(task_root, "R6_TASK_ROOT")
    _exact_directory(state_root, "R6_MANAGER_STATE_ROOT")
    _verify_source_pins()
    _verify_scope_and_review_pins(task_root, pins)
    if str(state_root) != pins["state_root"]:
        raise ValueError("R6_COMPLETION_STATE_ROOT_MISMATCH")
    release = release or common.load_release(Path(pins["app_root"]))
    _release_check(release, pins)
    original = _stable_bytes(Path(pins["original_canary_path"]), "R6_ORIGINAL_CANARY_SOURCE",
                             expected_sha256=pins["original_canary_sha256"])
    del original
    parent, parent_raw = _parent_execution_check(task_root, pins)
    source_dir = task_root / pins["source_dir_rel"]
    _exact_directory(source_dir, "R6_SAVED_EXECUTION")
    if {entry.name for entry in source_dir.iterdir()} != EXPECTED_SOURCE_FILES:
        raise ValueError("R6_SAVED_EXECUTION_FILE_SET_MISMATCH")
    source_preimage, source_preimage_raw = _read_json_pin(
        source_dir / pins["preimage"]["path"], pins["preimage"], "R6_SAVED_PREIMAGE"
    )
    if source_preimage.get("release_manifest_sha256") != pins["release_manifest_sha256"]:
        raise ValueError("R6_SAVED_PREIMAGE_MANIFEST_PIN_MISMATCH")
    preimage_clock = _check_original_preimage(source_preimage, release, state_root, pins)
    if receipt_pins is None:
        receipt_pins = CANARY._r6_receipt_pins()
    snapshot = _r4b_state_snapshot(source_preimage, receipt_pins, state_root, pins)
    failure, failure_sha = _validate_original_failure(source_dir, pins, state_root)
    disabled_binding, disabled_binding_sha = _validate_disabled_binding(
        source_dir, release, state_root, pins
    )
    refresh, _, refresh_ref = _read_saved_http_pair(source_dir, "refresh", pins["refresh"])
    readback, _, readback_ref = _read_saved_http_pair(source_dir, "readback", pins["readback"])
    run_id, product_sha, input_identity, attempt_state = CANARY._validate_owner_pair(
        refresh, readback, pins["target"]
    )
    if (refresh.get("plan_product", {}).get("status") != "CURRENT"
            or run_id != pins["fresh"]["run_id"]
            or product_sha != pins["fresh"]["product_sha256"]
            or input_identity != pins["fresh"]["input_identity"]
            or attempt_state != pins["fresh"]["state"]
            or refresh.get("workspace_plan_attempt", {}).get("sha256")
                != pins["fresh"]["attempt_sha256"]):
        raise ValueError("R6_SAVED_OWNER_PAIR_NOT_PINNED_FRESH_RESULT")
    attempt = refresh["workspace_plan_attempt"]
    now = now or datetime.now(ZoneInfo("Asia/Hong_Kong"))
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("R6_COMPLETION_CLOCK_MUST_BE_AWARE")
    current_clock = now.astimezone(ZoneInfo("Asia/Hong_Kong"))
    common.require_next_session(pins["target"], release["app_root"], current_clock)
    timestamp_proof = _check_owner_clock_and_manual_context(
        refresh, readback, attempt, parent, preimage_clock, current_clock, pins
    )
    current_state = _verify_current_fresh_state(state_root, snapshot, refresh, pins)
    if common.protected_state_hashes(state_root) != source_preimage["protected_dates_sha256"]:
        raise ValueError("R6_COMPLETION_PROTECTED_DATES_CHANGED")
    lock = state_root / ".locks" / f"{pins['target']}-workspace-plan-refresh.mutex"
    if not CANARY._kernel_lock_is_free(lock):
        raise ValueError("R6_COMPLETION_OWNER_LOCK_BUSY")
    return {
        "task_root": task_root,
        "source_dir": source_dir,
        "state_root": state_root,
        "release": release,
        "source_preimage": source_preimage,
        "source_preimage_sha256": common.sha256_bytes(source_preimage_raw),
        "failure": failure,
        "failure_sha256": failure_sha,
        "disabled_binding": disabled_binding,
        "disabled_binding_sha256": disabled_binding_sha,
        "parent_execution": parent,
        "parent_execution_sha256": common.sha256_bytes(parent_raw),
        "refresh": refresh,
        "readback": readback,
        "refresh_raw_ref": refresh_ref,
        "readback_raw_ref": readback_ref,
        "run_id": run_id,
        "product_sha256": product_sha,
        "input_identity": input_identity,
        "attempt": attempt,
        "attempt_state": attempt_state,
        "timestamp_proof": timestamp_proof,
        "state_check": current_state,
        "receipt_pins": receipt_pins,
        "current_clock_local": current_clock.isoformat(),
    }


def _canary_record(verified: dict[str, Any], output_dir: Path,
                   projection_refs: dict[str, dict[str, str]], pins: dict[str, Any]) -> dict[str, Any]:
    release = verified["release"]
    attempt = verified["attempt"]
    source_preimage = verified["source_preimage"]
    prior = source_preimage["prior_target_owner_state"]
    outcome = verified["state_check"]
    raw_refs = {"refresh": verified["refresh_raw_ref"], "readback": verified["readback_raw_ref"]}
    raw_owner_http = {
        label: {
            "kind": "RAW_HTTP_BODY", "method": raw_refs[label]["method"],
            "url": raw_refs[label]["url"], "http_status": 200,
            "content_type": "application/json",
            "body_path": raw_refs[label]["response_path"],
            "body_sha256": raw_refs[label]["response_sha256"],
            "body_bytes": raw_refs[label]["response_bytes"],
            "http_evidence_path": raw_refs[label]["evidence_path"],
            "http_evidence_sha256": raw_refs[label]["evidence_sha256"],
        } for label in ("refresh", "readback")
    }
    return {
        "schema_version": common.CANARY_SCHEMA,
        "status": common.CANARY_STATUS,
        "app_root": str(release["app_root"]),
        "manager_state_root": str(verified["state_root"]),
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
        "owner_http_requests_replayed": False,
        "formal_state_writes_performed": False,
        "recovery_source_failure_receipt": {
            "path": str(verified["source_dir"] / pins["failure"]["path"]),
            "sha256": verified["failure_sha256"],
        },
        "recovery_preimage": {
            "path": str(verified["source_dir"] / pins["preimage"]["path"]),
            "sha256": verified["source_preimage_sha256"],
        },
        "raw_owner_http": raw_owner_http,
        "contract_evidence_kind": "DERIVED_VALIDATED_PROJECTION",
        **common.SAFETY,
        "research_only": True,
        "target_trade_date": pins["target"],
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
        "owner_evidence": projection_refs,
        "owner_terminal_attempt": {
            "run_id": attempt["run_id"], "sha256": attempt["sha256"],
            "state": attempt["state"], "owner": attempt["owner"],
            "execution_kind": attempt["execution_kind"],
            "input_identity": attempt["input_identity"],
            "finished_at": attempt["finished_at"],
            "post_get_persisted_product_equal": True,
        },
        "owner_materialization_outcome": "FRESH",
        "state_preimage": {
            "protected_dates_sha256": source_preimage["protected_dates_sha256"],
            "target_preexisted": True,
            "archived_generation": prior["archived_generation"],
            "r4b_current_generation": prior["r4b_current_generation"],
            "two_generation_state_files": prior["files"],
            "r4b_receipt_pins": source_preimage["r4b_two_generation_receipt_pins"],
            "expected_durable_paths": outcome["expected_durable_paths"],
            "allowed_transition": "fresh: preserve d8 and 357 version files; only the exact validated new run/product and latest pointers may be added or advanced",
        },
        "owner_state_acceptance": {
            "mode": "R6_CURRENT13_FRESH",
            "preimage_verified": True,
            "archived_r3_generation_preserved": prior["archived_generation"],
            "r4b_current_generation_preserved_before_call": prior["r4b_current_generation"],
            "owner_attempt_identity_verified": {
                "run_id": attempt["run_id"], "sha256": attempt["sha256"],
                "state": attempt["state"], "owner": attempt["owner"],
                "execution_kind": attempt["execution_kind"],
                "input_identity": attempt["input_identity"],
                "finished_at": attempt["finished_at"],
            },
            "post_owner_write_set": outcome,
        },
        "safety": common.SAFETY,
    }


def _r2_private_prefix(output_dir: Path) -> str:
    return f".{output_dir.name}.r2-private-"


def _remove_private_workspace(workspace: Path, expected_parent: Path,
                              expected_prefix: str) -> None:
    if not workspace.exists() and not workspace.is_symlink():
        return
    if (workspace.parent != expected_parent or not workspace.name.startswith(expected_prefix)
            or workspace.is_symlink() or workspace.resolve(strict=True) != workspace):
        raise RuntimeError("R6_COMPLETION_PRIVATE_WORKSPACE_CLEANUP_REFUSED")
    shutil.rmtree(workspace)


def _rename_directory_exclusive(source: Path, destination: Path) -> None:
    """Atomically publish a complete sibling directory without replacing a path."""
    if sys.platform != "darwin":
        raise RuntimeError("R6_COMPLETION_ATOMIC_NO_REPLACE_UNAVAILABLE")
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        renameatx_np = libc.renameatx_np
    except AttributeError as exc:
        raise RuntimeError("R6_COMPLETION_ATOMIC_NO_REPLACE_UNAVAILABLE") from exc
    renameatx_np.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                             ctypes.c_char_p, ctypes.c_uint]
    renameatx_np.restype = ctypes.c_int
    at_fdcwd = -2
    rename_excl = 0x00000004
    result = renameatx_np(at_fdcwd, os.fsencode(source), at_fdcwd,
                          os.fsencode(destination), rename_excl)
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), str(destination))


def _late_current_date_gate(verified: dict[str, Any], *, now: datetime | None,
                            pins: dict[str, Any]) -> datetime:
    current = now if now is not None else datetime.now(ZoneInfo("Asia/Hong_Kong"))
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("R6_COMPLETION_CLOCK_MUST_BE_AWARE")
    current = current.astimezone(ZoneInfo("Asia/Hong_Kong"))
    common.require_next_session(pins["target"], verified["release"]["app_root"], current)
    _check_owner_clock_and_manual_context(
        verified["refresh"], verified["readback"], verified["attempt"],
        verified["parent_execution"],
        _aware_hk(verified["source_preimage"].get("current_clock_local"),
                  "R6_PREIMAGE_CLOCK"), current, pins,
    )
    return current


def _late_protected_dates_gate(verified: dict[str, Any]) -> dict[str, Any]:
    protected = common.protected_state_hashes(verified["state_root"])
    if protected != verified["source_preimage"]["protected_dates_sha256"]:
        raise ValueError("R6_COMPLETION_PROTECTED_DATES_CHANGED_DURING_WRITE")
    return protected


def _late_current_state_gate(verified: dict[str, Any], pins: dict[str, Any]
                             ) -> dict[str, Any]:
    snapshot = _r4b_state_snapshot(
        verified["source_preimage"], verified["receipt_pins"], verified["state_root"], pins,
    )
    state_after = _verify_current_fresh_state(
        verified["state_root"], snapshot, verified["refresh"], pins,
    )
    if state_after != verified["state_check"]:
        raise ValueError("R6_COMPLETION_OWNER_STATE_CHANGED_DURING_WRITE")
    return state_after


def _late_owner_mutex_gate(verified: dict[str, Any], pins: dict[str, Any]) -> str:
    lock = verified["state_root"] / ".locks" / f"{pins['target']}-workspace-plan-refresh.mutex"
    if not CANARY._kernel_lock_is_free(lock):
        raise ValueError("R6_COMPLETION_OWNER_LOCK_BUSY_AFTER_WRITE")
    return "FREE_AT_PREPUBLICATION_RECHECK"


def _late_acceptance_gates(verified: dict[str, Any], *, now: datetime | None,
                           pins: dict[str, Any]) -> dict[str, Any]:
    """Repeat mutable acceptance gates after temp outputs exist, before publish."""
    protected = _late_protected_dates_gate(verified)
    state_after = _late_current_state_gate(verified, pins)
    mutex = _late_owner_mutex_gate(verified, pins)
    # Keep the wall-clock/session check last so it is closest to the atomic
    # publish point after the other mutable acceptance gates have completed.
    current = _late_current_date_gate(verified, now=now, pins=pins)
    return {
        "current_clock_local": current.isoformat(),
        "protected_date_maps": "ALL_SIX_MATCH_ORIGINAL_PREIMAGE",
        "protected_state_sha256": common.canonical_sha(protected),
        "current_state_status": state_after.get("status"),
        "owner_mutex": mutex,
    }


def complete_saved_execution(*, task_root: Path = TASK_ROOT,
                              state_root: Path = STATE_ROOT,
                              output_dir: Path | None = None,
                              release: dict[str, Any] | None = None,
                              now: datetime | None = None,
                              pins: dict[str, Any] = PINS,
                              receipt_pins: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build privately and atomically publish only a fully accepted output set."""
    task_root = Path(task_root)
    _exact_directory(task_root, "R6_TASK_ROOT")
    output_dir = Path(output_dir) if output_dir is not None else task_root / pins["output_dir_rel"]
    if not output_dir.is_absolute() or output_dir.resolve() != output_dir:
        raise ValueError("R6_COMPLETION_OUTPUT_PATH_NOT_EXACT")
    receipts_root = task_root / "receipts"
    if output_dir == receipts_root or receipts_root not in output_dir.parents:
        raise ValueError("R6_COMPLETION_OUTPUT_OUTSIDE_TASK_RECEIPTS")
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError("R6_COMPLETION_OUTPUT_ALREADY_EXISTS")
    _exact_directory(output_dir.parent, "R6_COMPLETION_OUTPUT_PARENT")
    prefix = _r2_private_prefix(output_dir)
    stale = sorted(output_dir.parent.glob(prefix + "*"))
    if stale:
        raise FileExistsError("R6_COMPLETION_STALE_PRIVATE_WORKSPACE_REQUIRES_INSPECTION")

    verified = verify_saved_execution(task_root=task_root, state_root=state_root,
                                      release=release, now=now, pins=pins,
                                      receipt_pins=receipt_pins)
    workspace = output_dir.parent / (prefix + uuid.uuid4().hex)
    workspace.mkdir(mode=0o700, exist_ok=False)
    support_dir = workspace / "support"
    publish_dir = workspace / "publish"
    try:
        support_dir.mkdir(mode=0o700, exist_ok=False)
        publish_dir.mkdir(mode=0o700, exist_ok=False)
        projection_refs: dict[str, dict[str, str]] = {}
        projection_names = []
        projection_hashes: dict[str, str] = {}
        for label in ("refresh", "readback"):
            projection_refs[label] = _write_projection(
                support_dir, label, _owner_projection(verified[label]),
                verified[label + "_raw_ref"], pins,
            )
            projection_names.extend((
                f"{label}.verified-projection.response.bin",
                f"{label}.verified-projection.http-evidence.json",
            ))
        for name in projection_names:
            raw = _stable_bytes(support_dir / name, "R6_PRIVATE_PROJECTION")
            _write_exclusive(publish_dir / name, raw)
            projection_hashes[name] = common.sha256_bytes(raw)

        canary = _canary_record(verified, output_dir, projection_refs, pins)
        canary_raw = _json_bytes(canary)
        if len(canary_raw) > 1024 * 1024:
            raise ValueError("R6_COMPLETED_CANARY_EXCEEDS_VALIDATOR_LIMIT")
        temp_canary_path = publish_dir / "plan-canary.json"
        final_canary_path = output_dir / "plan-canary.json"
        _write_exclusive(temp_canary_path, canary_raw)
        release_record = verified["release"]
        owner_identity = {"app_root": release_record["app_root"],
                          "files": release_record["binding_files"]}
        release_record["contract"]._validate_plan_canary(
            {"path": str(temp_canary_path), "sha256": common.sha256_bytes(canary_raw)},
            app=release_record["app_root"], state=verified["state_root"],
            owner_identity=owner_identity,
        )

        attempt = verified["attempt"]
        gaps = _research_gap_summary(verified["refresh"], verified["readback"], attempt)
        parent = verified["parent_execution"]
        completion = {
            "schema_version": "issue35.phase6.execution03.offline_completion.r2.v1",
            "status": "PASS_OFFLINE_SAVED_OWNER_READBACK_COMPLETION",
            "target_trade_date": pins["target"],
            "mode": "OFFLINE_SAVED_EVIDENCE_ONLY_ATOMIC_PUBLICATION",
            "created_at_local": verified["current_clock_local"],
            "candidate": {
                "release_id": release_record["manifest"]["candidate"]["release_id"],
                "app_root": str(release_record["app_root"]),
                "manifest_sha256": release_record["manifest_sha256"],
                "application_inventory_sha256": release_record["application_inventory_sha256"],
                "owner_source_inventory_sha256": release_record["owner_inventory_sha256"],
                "original_canary_source_path": pins["original_canary_path"],
                "original_canary_source_sha256": pins["original_canary_sha256"],
            },
            "original_parent_execution": {
                "path": str(task_root / pins["parent_execution_rel"]),
                "sha256": verified["parent_execution_sha256"],
                "argv": parent["argv"], "exit_code": parent["exit_code"],
                "finished_utc": parent["finished_utc"],
                "stderr_sha256": parent["stderr_sha256"],
                "original_failure_receipt_preserved": True,
            },
            "original_owner_http_call_count": 2,
            "original_owner_http_calls": {
                "refresh": verified["refresh_raw_ref"],
                "readback": verified["readback_raw_ref"],
            },
            "original_transport_identity": {
                "mode": "IN_PROCESS_HTTPX_ASGI_TRANSPORT",
                "source": pins["original_canary_path"],
                "source_sha256": pins["original_canary_sha256"],
                "base_url": common.API_BASE_URL,
                "base_url_is_not_live_process_verification": True,
                "live_process_at_port_8873": "CANNOT_CONFIRM",
            },
            "original_event_timestamps": verified["timestamp_proof"],
            "owner_result": {
                "run_id": verified["run_id"], "product_sha256": verified["product_sha256"],
                "input_identity": verified["input_identity"],
                "terminal_attempt_sha256": attempt["sha256"],
                "state": verified["attempt_state"], "business_completeness": "PARTIAL",
                "research_and_pit_completeness": "CANNOT_CONFIRM",
                "coverage_and_gap_summary": gaps, "natural_run_verified": False,
            },
            "current_state_verification": {
                "status": verified["state_check"]["status"],
                "archived_d8_preserved": True, "prior_357_preserved": True,
                "fresh_92f_is_current": True,
                "latest_pointer_bytes_match_fresh_records": True,
                "target_write_set": verified["state_check"]["allowed_target_write_set"],
                "current_fresh_run_sha256": pins["fresh"]["run_file_sha256"],
                "current_fresh_product_file_sha256": pins["fresh"]["product_file_sha256"],
                "protected_date_maps": "ALL_SIX_MATCH_ORIGINAL_PREIMAGE",
                "owner_mutex_nonblocking_probe": "FREE_AT_READBACK",
            },
            "offline_completion_actions": {
                "http_calls": 0, "owner_calls": 0, "service_calls": 0,
                "manager_state_writes": 0, "plists_written": 0,
                "launchctl_called": False, "activation_status": "NOT_ACTIVATED",
                "original_failure_receipt_modified": False,
                "original_raw_http_artifacts_modified": False,
                "output_publication": "ATOMIC_SIBLING_DIRECTORY_RENAME_EXCL",
            },
            "completed_canary": {
                "path": str(final_canary_path),
                "sha256": common.sha256_bytes(canary_raw),
                "schema_version": common.CANARY_SCHEMA,
                "status": common.CANARY_STATUS,
                "owner_evidence_kind": "DERIVED_VALIDATED_PROJECTION_WITH_RAW_HTTP_PROVENANCE",
                "projection_refs": projection_refs,
            },
            "atomic_publication": {
                "private_workspace_prefix": prefix,
                "final_directory_published_after_all_gates": True,
                "no_replace_flag": "RENAME_EXCL",
                "persistent_projection_support_directory": str(support_dir),
                "interrupted_workspace_policy": "REFUSE_REUSE_OR_AUTOMATIC_DELETION; inspect manually",
            },
            "CANNOT_CONFIRM": [
                "Full research and PIT completeness; persisted owner attempt is PARTIAL and exact input/source gaps are included above.",
                "Live API process identity at port 8873; the original URL is an in-process ASGI base URL.",
                "Stage preparation, pair publication, activation, API/UI readback, and a natural target-date run.",
            ],
            "safety": common.SAFETY,
        }
        completion_path = publish_dir / "completion-receipt.json"
        completion_raw = _json_bytes(completion)
        if len(completion_raw) > 1024 * 1024:
            raise ValueError("R6_COMPLETION_RECEIPT_EXCEEDS_LIMIT")
        _write_exclusive(completion_path, completion_raw)
        expected_output_files = {
            "refresh.verified-projection.response.bin", "refresh.verified-projection.http-evidence.json",
            "readback.verified-projection.response.bin", "readback.verified-projection.http-evidence.json",
            "plan-canary.json", "completion-receipt.json",
        }
        if {entry.name for entry in publish_dir.iterdir()} != expected_output_files:
            raise ValueError("R6_COMPLETION_OUTPUT_FILE_SET_MISMATCH")
        output_hashes = {}
        for name in sorted(expected_output_files):
            raw = _stable_bytes(publish_dir / name, "R6_PRIVATE_PUBLICATION_FILE")
            output_hashes[name] = common.sha256_bytes(raw)
        if (any(output_hashes[name] != expected for name, expected in projection_hashes.items())
                or output_hashes["plan-canary.json"] != common.sha256_bytes(canary_raw)
                or output_hashes["completion-receipt.json"] != common.sha256_bytes(completion_raw)):
            raise ValueError("R6_PRIVATE_PUBLICATION_CONTENT_CHANGED")

        late_proof = _late_acceptance_gates(verified, now=now, pins=pins)
        result = {
            "status": completion["status"], "output_dir": str(output_dir),
            "canary_path": str(final_canary_path),
            "canary_sha256": common.sha256_bytes(canary_raw),
            "completion_receipt_path": str(output_dir / "completion-receipt.json"),
            "completion_receipt_sha256": common.sha256_bytes(completion_raw),
            "support_dir": str(support_dir),
            "prepublication_recheck": late_proof,
            "owner_result_state": verified["attempt_state"],
            "http_calls": 0, "owner_calls": 0, "state_writes": 0,
        }
    except BaseException:
        _remove_private_workspace(workspace, output_dir.parent, prefix)
        raise

    # RENAME_EXCL is the sole publication operation. Do not run verifiers or
    # mutate either directory after this call; on a failed syscall the source
    # remains private and is safely removable.
    try:
        _rename_directory_exclusive(publish_dir, output_dir)
    except (OSError, RuntimeError):
        _remove_private_workspace(workspace, output_dir.parent, prefix)
        raise
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    result = complete_saved_execution()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
