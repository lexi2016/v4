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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
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
    refresh_attempt = refresh.get("workspace_plan_attempt")
    readback_attempt = readback.get("workspace_plan_attempt")
    refresh_product_attempt = refresh.get("workspace_plan_product_attempt")
    readback_product_attempt = readback.get("workspace_plan_product_attempt")
    refresh_status = product.get("status") if isinstance(product, dict) else None
    if (refresh.get("target_trade_date") != target or readback.get("target_trade_date") != target
            or refresh.get("formal_recommendation_count") != 0
            or refresh.get("store_latest_matches_http_plan_product") is not True
            or not isinstance(product, dict) or not isinstance(get_product, dict)
            or refresh_status not in {"CURRENT", "ALREADY_MATERIALIZED"}
            or get_product.get("status") != "CURRENT"
            or product.get("consumed") is not True or get_product.get("consumed") is not True
            or product.get("run_id") != get_product.get("run_id")
            or product.get("sha256") != get_product.get("sha256")
            or product.get("original_owner") != common.OWNER
            or get_product.get("original_owner") != common.OWNER
            or refresh.get("input_identity") != readback.get("input_identity")
            or not isinstance(refresh.get("input_identity"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", refresh["input_identity"])
            or refresh.get("execution_kind") != "MANUAL_REFRESH"
            or readback.get("execution_kind") != "MANUAL_REFRESH"
            or refresh.get("safety") != common.SAFETY
            or readback.get("safety") != common.SAFETY
            or not isinstance(refresh_attempt, dict)
            or refresh_attempt != readback_attempt
            or refresh_attempt != refresh_product_attempt
            or refresh_attempt != readback_product_attempt):
        raise ValueError("CANARY_OWNER_READBACK_MISMATCH")
    run_id = str(product.get("run_id") or "")
    product_sha = str(product.get("sha256") or "")
    input_identity = str(refresh.get("input_identity") or "")
    if (not re.fullmatch(r"[0-9a-f]{32}", run_id)
            or not re.fullmatch(r"[0-9a-f]{64}", product_sha)
            or product.get("execution_kind") != "MANUAL_REFRESH"
            or get_product.get("execution_kind") != "MANUAL_REFRESH"):
        raise ValueError("CANARY_PRODUCT_IDENTITY_INVALID")
    attempt = refresh_attempt
    if (attempt.get("target_trade_date") != target or attempt.get("run_id") != run_id
            or attempt.get("sha256") is None
            or not re.fullmatch(r"[0-9a-f]{64}", str(attempt.get("sha256")))
            or attempt.get("input_identity") != input_identity
            or attempt.get("owner") != common.OWNER
            or attempt.get("execution_kind") != "MANUAL_REFRESH"
            or attempt.get("state") not in {"SUCCEEDED", "SUCCEEDED_EMPTY", "PARTIAL"}
            or not isinstance(attempt.get("finished_at"), str) or not attempt.get("finished_at")
            or common.canonical_sha({key: value for key, value in attempt.items() if key != "sha256"})
            != attempt.get("sha256")
            or any(attempt.get(key) != value for key, value in common.SAFETY.items())):
        raise ValueError("CANARY_OWNER_TERMINAL_ATTEMPT_INVALID")
    for body, body_product in ((refresh, product), (readback, get_product)):
        diagnostics = body_product.get("input_identity_diagnostics")
        run_readback = body_product.get("run_readback")
        if (not isinstance(diagnostics, dict) or diagnostics.get("status") != "MATCH"
                or diagnostics.get("current_input_identity") != input_identity
                or diagnostics.get("saved_input_identity") != input_identity
                or not isinstance(run_readback, dict) or run_readback.get("status") != "VERIFIED"
                or run_readback.get("target_trade_date") != target
                or run_readback.get("run_id") != run_id
                or run_readback.get("artifact_sha256") != product_sha
                or run_readback.get("input_identity") != input_identity
                or run_readback.get("owner") != common.OWNER
                or run_readback.get("owner_attempt_run_id") != run_id
                or run_readback.get("owner_attempt_sha256") != attempt.get("sha256")
                or run_readback.get("owner_attempt_state") != attempt.get("state")
                or run_readback.get("owner_finished_at") != attempt.get("finished_at")):
            raise ValueError("CANARY_OWNER_PRODUCT_READBACK_IDENTITY_MISMATCH")
    if persisted is not None and (
            not isinstance(persisted, dict) or persisted.get("target_trade_date") != target
            or persisted.get("run_id") != run_id
            or persisted.get("product_sha256") != product_sha
            or persisted.get("execution_kind") != "MANUAL_REFRESH"
            or persisted.get("owner") != common.OWNER
            or any(persisted.get(key) != value for key, value in common.SAFETY.items())):
        raise ValueError("CANARY_PERSISTED_IDENTITY_MISMATCH")
    if refresh_status == "CURRENT" and not isinstance(persisted, dict):
        raise ValueError("CANARY_FRESH_PERSISTED_STORE_MISSING")
    if refresh_status == "ALREADY_MATERIALIZED" and persisted is not None and not isinstance(persisted, dict):
        raise ValueError("CANARY_REUSE_PERSISTED_STORE_INVALID")
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

_R6_CURRENT13_ACCEPTANCE = {
    "target_trade_date": "20261013",
    "release_id": "issue35-manager-autocontinue-20261012-r6-integrated",
    "release_root": str(common.TASK_ROOT / "integrated_release" / "issue35-manager-autocontinue-20261012-r6-integrated"),
    "app_root": str(common.TASK_ROOT / "integrated_release" / "issue35-manager-autocontinue-20261012-r6-integrated" / "app"),
    "release_manifest_sha256": "a63b80727953068d123f768ab608c5a6cf45758aa3ca234c71a8c8892d7cfaf7",
    "application_inventory_sha256": "5244040fa11b2721a84b92d30d6189f4da83b2d3f8eb99259ba60f3e7d993b5d",
    "state_root": str(common.DEFAULT_MANAGER_STATE_ROOT),
    "r4b_canary_path": common.TASK_ROOT / "receipts/plan_canary_runs/20261013/execution-02/plan-canary.json",
    "r4b_canary_sha256": "4cfe936e7e52611544a95b6bccd692bb1cf47f823d3c5c91f0c9bbc09497ea63",
    "r4b_state_preimage_path": common.TASK_ROOT / "receipts/plan_canary_runs/20261013/execution-02/state-preimage.json",
    "r4b_state_preimage_sha256": "56af33340d7ed7256f287c626aa546acf459f73895ca6cd28bdbfc94df2e9f9c",
    "contract_review_path": common.TASK_ROOT / "review/phase6-publication-contract/independent-review.json",
    "contract_review_sha256": "f996a8fdbf2c22b2cffce756f644a6dc8b8b561f630e12f76b8314b65811b56c",
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
    "current": {
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


def _r6_receipt_pins() -> dict[str, Any]:
    """Bind the two distinct R4b target13 generations to immutable task receipts."""
    pins = _R6_CURRENT13_ACCEPTANCE
    archived = pins["archived"]
    current = pins["current"]
    state_preimage = _read_pinned_json(pins["r4b_state_preimage_path"],
                                       pins["r4b_state_preimage_sha256"],
                                       "R6_R4B_STATE_PREIMAGE")
    accepted = _read_pinned_json(pins["r4b_canary_path"], pins["r4b_canary_sha256"],
                                 "R6_R4B_ACCEPTED_CANARY")
    review = _read_pinned_json(pins["contract_review_path"], pins["contract_review_sha256"],
                               "R6_PUBLICATION_CONTRACT_REVIEW")
    d8 = state_preimage.get("prior_target_owner_state", {})
    d8_files = d8.get("files", {}) if isinstance(d8, dict) else {}
    d8_run = d8_files.get("run_file", {}) if isinstance(d8_files, dict) else {}
    d8_product = d8_files.get("product_file", {}) if isinstance(d8_files, dict) else {}
    report_preimages = review.get("exact_preimages", {})
    report_archived = report_preimages.get("archived_r3_version_still_exact", {})
    report_current = report_preimages.get("read_only_current_state_observed", {})
    report_plan = review.get("reviewed_diff", {})
    accepted_state = accepted.get("state_preimage", {})
    accepted_owner = accepted.get("owner_state_acceptance", {})
    accepted_write = accepted_owner.get("post_owner_write_set", {})
    accepted_prior = accepted_state
    if (state_preimage.get("target_trade_date") != pins["target_trade_date"]
            or state_preimage.get("manager_state_root") != pins["state_root"]
            or state_preimage.get("target_preexisted") is not True
            or d8.get("run_id") != archived["run_id"]
            or d8.get("product_sha256") != archived["product_sha256"]
            or d8.get("input_identity") != archived["input_identity"]
            or d8_run.get("bytes") != archived["run_bytes"]
            or d8_run.get("sha256") != archived["run_sha256"]
            or d8_product.get("bytes") != archived["product_bytes"]
            or d8_product.get("sha256") != archived["product_sha256_file"]
            or accepted_prior.get("prior_run_id") != archived["run_id"]
            or accepted_prior.get("prior_product_sha256") != archived["product_sha256"]
            or accepted_prior.get("prior_input_identity") != archived["input_identity"]
            or accepted_prior.get("prior_state_files", {}).get("run_file", {}).get("sha256") != archived["run_sha256"]
            or accepted_prior.get("prior_state_files", {}).get("product_file", {}).get("sha256") != archived["product_sha256_file"]
            or accepted.get("status") != "PASS_OWNER_READBACK_EVIDENCE_FOR_PLAN_BINDING"
            or accepted.get("target_trade_date") != pins["target_trade_date"]
            or accepted.get("candidate_release_id") != "issue35-manager-autocontinue-20261012-r4b"
            or accepted.get("candidate_release_manifest_sha256") != "ccf0bbec4b58910f180320e4288f09e0af2a8143c542f2183eab977d01746b9f"
            or accepted.get("execution_kind") != "MANUAL_REFRESH"
            or accepted.get("owner") != common.OWNER
            or accepted.get("owner_attempt_state") != current["state"]
            or accepted.get("run_id") != current["run_id"]
            or accepted.get("product_sha256") != current["product_sha256"]
            or accepted.get("input_identity") != current["input_identity"]
            or accepted_owner.get("mode") != "CURRENT13_EXISTING_TARGET_NONDESTRUCTIVE"
            or accepted_owner.get("prior_run_id") != archived["run_id"]
            or accepted_owner.get("prior_product_sha256") != archived["product_sha256"]
            or accepted_owner.get("prior_input_identity") != archived["input_identity"]
            or accepted_owner.get("prior_version_files_preserved") is not True
            or accepted_state.get("target_preexisted") is not True
            or accepted_state.get("prior_run_id") != archived["run_id"]
            or accepted_write.get("prior_run_id") != archived["run_id"]
            or accepted_write.get("current_run_id") != current["run_id"]
            or accepted_write.get("current_product_sha256") != current["product_sha256"]
            or accepted_write.get("prior_version_files_preserved") is not True
            or report_archived.get("run_id") != archived["run_id"]
            or report_archived.get("run_file_sha256") != archived["run_sha256"]
            or report_archived.get("product_file_sha256") != archived["product_sha256_file"]
            or report_archived.get("product_sha256_field") != archived["product_sha256"]
            or report_current.get("current_run_id") != current["run_id"]
            or report_current.get("current_input_identity") != current["input_identity"]
            or report_current.get("current_product_sha256_field") != current["product_sha256"]
            or report_current.get("current_attempt_state") != current["state"]
            or report_current.get("execution_kind") != "MANUAL_REFRESH"
            or report_current.get("owner") != common.OWNER
            or report_current.get("target_date") != pins["target_trade_date"]
            or report_current.get("state_root") != pins["state_root"]
            or report_current.get("current_run_file_and_latest", {}).get("bytes") != current["run_bytes"]
            or report_current.get("current_run_file_and_latest", {}).get("sha256") != current["run_sha256"]
            or report_current.get("current_product_file_and_latest", {}).get("bytes") != current["product_bytes"]
            or report_current.get("current_product_file_and_latest", {}).get("sha256") != current["product_sha256_file"]
            or report_plan.get("candidate_manifest_sha256") != pins["release_manifest_sha256"]
            or report_plan.get("candidate_status") != "PASS_INACTIVE_R6_ORIGINAL_INTEGRATOR_CANDIDATE"):
        raise ValueError("R6_TWO_GENERATION_RECEIPT_CONTRACT_MISMATCH")
    return {"archived": archived, "current": current,
            "protected_dates_sha256": state_preimage.get("protected_dates_sha256"),
            "r4b_state_preimage_path": str(pins["r4b_state_preimage_path"]),
            "r4b_state_preimage_sha256": pins["r4b_state_preimage_sha256"],
            "r4b_canary_path": str(pins["r4b_canary_path"]),
            "r4b_canary_sha256": pins["r4b_canary_sha256"],
            "contract_review_path": str(pins["contract_review_path"]),
            "contract_review_sha256": pins["contract_review_sha256"]}


def _decode_record(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(label + "_INVALID_JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(label + "_INVALID_JSON")
    return value


def _state_file_row(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    raw = _stable_exact_bytes(path, "R6_" + label.upper())
    return raw, {"path": str(path), "bytes": len(raw), "sha256": common.sha256_bytes(raw)}


def _capture_r6_state_preimage(state_root: Path, target: str,
                               receipt_pins: dict[str, Any]) -> dict[str, Any]:
    """Require the exact d8 archive plus the distinct 357 R4b current generation."""
    if target != _R6_CURRENT13_ACCEPTANCE["target_trade_date"]:
        raise ValueError("R6_CURRENT13_TARGET_NOT_PINNED")
    if str(state_root) != _R6_CURRENT13_ACCEPTANCE["state_root"]:
        raise ValueError("R6_MANAGER_STATE_ROOT_MISMATCH")
    archived = receipt_pins["archived"]
    current = receipt_pins["current"]
    run_root = state_root / "workspace_plan_runs" / target
    plan_root = state_root / "workspace_plans" / target
    expected = {"latest.json", archived["run_id"] + ".json", current["run_id"] + ".json"}
    _directory_write_set(run_root, expected, "R6_TWO_GENERATION_RUN_PREIMAGE")
    _directory_write_set(plan_root, expected, "R6_TWO_GENERATION_PRODUCT_PREIMAGE")
    paths = {
        "archived_run": run_root / (archived["run_id"] + ".json"),
        "archived_product": plan_root / (archived["run_id"] + ".json"),
        "current_run": run_root / (current["run_id"] + ".json"),
        "current_run_latest": run_root / "latest.json",
        "current_product": plan_root / (current["run_id"] + ".json"),
        "current_product_latest": plan_root / "latest.json",
    }
    observed: dict[str, dict[str, Any]] = {}
    raw_files: dict[str, bytes] = {}
    for label, path in paths.items():
        raw_files[label], observed[label] = _state_file_row(path, label)
    expected_files = {
        "archived_run": (archived["run_bytes"], archived["run_sha256"]),
        "archived_product": (archived["product_bytes"], archived["product_sha256_file"]),
        "current_run": (current["run_bytes"], current["run_sha256"]),
        "current_run_latest": (current["run_bytes"], current["run_sha256"]),
        "current_product": (current["product_bytes"], current["product_sha256_file"]),
        "current_product_latest": (current["product_bytes"], current["product_sha256_file"]),
    }
    for label, (size, digest) in expected_files.items():
        if observed[label]["bytes"] != size or observed[label]["sha256"] != digest:
            raise ValueError("R6_TWO_GENERATION_PREIMAGE_SHA_OR_SIZE_MISMATCH:" + label)
    if (raw_files["current_run"] != raw_files["current_run_latest"]
            or raw_files["current_product"] != raw_files["current_product_latest"]):
        raise ValueError("R6_CURRENT_LATEST_POINTER_BYTES_MISMATCH")
    archived_run = _decode_record(raw_files["archived_run"], "R6_ARCHIVED_RUN")
    archived_product = _decode_record(raw_files["archived_product"], "R6_ARCHIVED_PRODUCT")
    current_run = _decode_record(raw_files["current_run"], "R6_CURRENT_RUN")
    current_product = _decode_record(raw_files["current_product"], "R6_CURRENT_PRODUCT")
    for record, row, expected_state, label in (
            (archived_run, archived, archived["state"], "ARCHIVED_RUN"),
            (current_run, current, current["state"], "CURRENT_RUN")):
        if (record.get("target_trade_date") != target or record.get("run_id") != row["run_id"]
                or record.get("input_identity") != row["input_identity"]
                or record.get("state") != expected_state or record.get("owner") != common.OWNER
                or record.get("execution_kind") != "MANUAL_REFRESH"
                or not isinstance(record.get("sha256"), str)
                or common.canonical_sha({key: value for key, value in record.items() if key != "sha256"})
                != record.get("sha256")
                or any(record.get(key) != value for key, value in common.SAFETY.items())):
            raise ValueError("R6_TWO_GENERATION_RUN_IDENTITY_MISMATCH:" + label)
    for record, row, label in ((archived_product, archived, "ARCHIVED_PRODUCT"),
                               (current_product, current, "CURRENT_PRODUCT")):
        if (record.get("target_trade_date") != target or record.get("run_id") != row["run_id"]
                or record.get("input_identity") != row["input_identity"]
                or record.get("sha256") != row["product_sha256"]
                or record.get("owner") != common.OWNER
                or record.get("execution_kind") != "MANUAL_REFRESH"
                or any(record.get(key) != value for key, value in common.SAFETY.items())):
            raise ValueError("R6_TWO_GENERATION_PRODUCT_IDENTITY_MISMATCH:" + label)
    lock_path = state_root / ".locks" / (target + "-workspace-plan-refresh.mutex")
    if not _kernel_lock_is_free(lock_path):
        raise ValueError("R6_OWNER_LOCK_BUSY")
    protected = common.protected_state_hashes(state_root)
    if protected != receipt_pins["protected_dates_sha256"]:
        raise ValueError("R6_PROTECTED_DATES_PREIMAGE_MISMATCH")
    if not _kernel_lock_is_free(lock_path):
        raise ValueError("R6_OWNER_LOCK_CHANGED_DURING_PREFLIGHT")
    return {"target_trade_date": target, "manager_state_root": str(state_root),
            "archived": {"run_id": archived["run_id"], "product_sha256": archived["product_sha256"],
                         "input_identity": archived["input_identity"], "state": archived["state"]},
            "current": {"run_id": current["run_id"], "product_sha256": current["product_sha256"],
                        "input_identity": current["input_identity"], "state": current["state"]},
            "state_files": observed, "expected_run_names": sorted(expected),
            "expected_product_names": sorted(expected),
            "protected_dates_sha256": protected, "owner_lock_free": True,
            "receipt_pins": receipt_pins, "http_calls": 0, "state_writes": 0,
            "safety": common.SAFETY}


def _current13_existing_preimage(identity: dict[str, Any], target: str,
                                 now: datetime) -> dict[str, Any]:
    """Read-only R6 gate: preserve d8 as history and pin 357 as current R4b latest."""
    pins = _R6_CURRENT13_ACCEPTANCE
    release = identity["release"]
    state_root = identity["state_root"]
    if target != pins["target_trade_date"]:
        raise ValueError("R6_CURRENT13_TARGET_NOT_PINNED")
    if (release["manifest_sha256"] != pins["release_manifest_sha256"]
            or str(release["release_root"]) != pins["release_root"]
            or str(release["app_root"]) != pins["app_root"]
            or release["application_inventory_sha256"] != pins["application_inventory_sha256"]
            or release["manifest"]["candidate"].get("release_id") != pins["release_id"]):
        raise ValueError("R6_CURRENT13_REQUIRES_VERIFIED_R6_RELEASE")
    common.require_next_session(target, release["app_root"], now)
    if str(state_root) != pins["state_root"]:
        raise ValueError("R6_MANAGER_STATE_ROOT_MISMATCH")
    receipt_pins = _r6_receipt_pins()
    snapshot = _capture_r6_state_preimage(state_root, target, receipt_pins)
    snapshot.update({"prior_run_id": snapshot["current"]["run_id"],
                     "prior_product_sha256": snapshot["current"]["product_sha256"],
                     "prior_input_identity": snapshot["current"]["input_identity"],
                     "prior_owner_attempt_state": snapshot["current"]["state"],
                     "prior_release_manifest_sha256": pins["current"]["release_manifest_sha256"],
                     "r4b_two_generation_receipt_pins": {
                         key: receipt_pins[key] for key in ("r4b_state_preimage_path",
                             "r4b_state_preimage_sha256", "r4b_canary_path", "r4b_canary_sha256",
                             "contract_review_path", "contract_review_sha256")}})
    return snapshot


def _assert_current13_preimage_unchanged(state_root: Path, preimage: dict[str, Any]) -> None:
    """Immediately before POST, recheck both histories, latest, lock and protected dates."""
    observed = _capture_r6_state_preimage(state_root, preimage["target_trade_date"],
                                          preimage["receipt_pins"])
    if observed["state_files"] != preimage["state_files"]:
        raise ValueError("R6_TWO_GENERATION_PREIMAGE_CHANGED_BEFORE_POST")


def _verify_preserved_r6_versions(state_root: Path, target: str,
                                 preimage: dict[str, Any]) -> None:
    run_root = state_root / "workspace_plan_runs" / target
    plan_root = state_root / "workspace_plans" / target
    for label, path in (
            ("archived_run", run_root / (preimage["archived"]["run_id"] + ".json")),
            ("archived_product", plan_root / (preimage["archived"]["run_id"] + ".json")),
            ("current_run", run_root / (preimage["current"]["run_id"] + ".json")),
            ("current_product", plan_root / (preimage["current"]["run_id"] + ".json"))):
        raw = _stable_exact_bytes(path, "R6_PRESERVED_" + label.upper())
        row = preimage["state_files"][label]
        if len(raw) != row["bytes"] or common.sha256_bytes(raw) != row["sha256"]:
            raise ValueError("R6_PRESERVED_HISTORY_MUTATED:" + label)


def _assert_current13_failure_preserved(state_root: Path, preimage: dict[str, Any]) -> dict[str, Any]:
    """Accept only one exact FAILED run journal while old product latest remains 357."""
    target = preimage["target_trade_date"]
    run_root = state_root / "workspace_plan_runs" / target
    plan_root = state_root / "workspace_plans" / target
    archived = preimage["archived"]["run_id"]
    current = preimage["current"]["run_id"]
    run_latest_raw = _stable_exact_bytes(run_root / "latest.json", "R6_FAILURE_RUN_LATEST")
    failed = _decode_record(run_latest_raw, "R6_FAILURE_RUN_LATEST")
    failed_id = failed.get("run_id")
    if (not isinstance(failed_id, str) or not re.fullmatch(r"[0-9a-f]{32}", failed_id)
            or failed_id in {archived, current}):
        raise ValueError("R6_FAILURE_NO_EXACT_NEW_FAILED_ATTEMPT")
    expected_runs = {"latest.json", archived + ".json", current + ".json", failed_id + ".json"}
    expected_products = {"latest.json", archived + ".json", current + ".json"}
    _directory_write_set(run_root, expected_runs, "R6_FAILURE_RUN")
    _directory_write_set(plan_root, expected_products, "R6_FAILURE_PRODUCT")
    failed_raw = _stable_exact_bytes(run_root / (failed_id + ".json"), "R6_FAILURE_RUN_RECORD")
    if failed_raw != run_latest_raw:
        raise ValueError("R6_FAILURE_RUN_LATEST_BYTES_MISMATCH")
    plan_latest_raw = _stable_exact_bytes(plan_root / "latest.json", "R6_FAILURE_PRODUCT_LATEST")
    current_product_raw = _stable_exact_bytes(plan_root / (current + ".json"), "R6_FAILURE_CURRENT_PRODUCT")
    if (plan_latest_raw != current_product_raw
            or common.sha256_bytes(plan_latest_raw) != preimage["state_files"]["current_product_latest"]["sha256"]):
        raise ValueError("R6_FAILURE_PRIOR_PRODUCT_LATEST_CHANGED")
    _verify_preserved_r6_versions(state_root, target, preimage)
    if (failed.get("target_trade_date") != target or failed.get("state") != "FAILED"
            or failed.get("owner") != common.OWNER
            or failed.get("execution_kind") != "MANUAL_REFRESH"
            or not isinstance(failed.get("finished_at"), str) or not failed.get("finished_at")
            or not isinstance(failed.get("failure_reasons"), list) or not failed.get("failure_reasons")
            or "success_scope" in failed
            or common.canonical_sha({key: value for key, value in failed.items() if key != "sha256"})
            != failed.get("sha256")
            or any(failed.get(key) != value for key, value in common.SAFETY.items())):
        raise ValueError("R6_FAILURE_ATTEMPT_IDENTITY_INVALID")
    input_identity = failed.get("input_identity")
    if input_identity is not None and (not isinstance(input_identity, str)
            or not re.fullmatch(r"[0-9a-f]{64}", input_identity)):
        raise ValueError("R6_FAILURE_ATTEMPT_INPUT_IDENTITY_INVALID")
    if common.protected_state_hashes(state_root) != preimage["protected_dates_sha256"]:
        raise ValueError("R6_FAILURE_PROTECTED_DATES_CHANGED")
    if not _kernel_lock_is_free(state_root / ".locks" / (target + "-workspace-plan-refresh.mutex")):
        raise ValueError("R6_FAILURE_OWNER_LOCK_BUSY")
    return {"status": "PASS_EXACT_FAILED_RUN_JOURNAL_PRIOR_PRODUCT_LATEST_PRESERVED",
            "failed_run_id": failed_id, "failed_attempt_sha256": failed.get("sha256"),
            "failed_state": "FAILED", "archived_run_id_preserved": archived,
            "prior_current_run_id_preserved": current,
            "prior_product_latest_sha256": common.sha256_bytes(plan_latest_raw),
            "allowed_run_write_set": sorted(expected_runs),
            "allowed_product_write_set": sorted(expected_products),
            "owner_lock_free": True, "canary_success": False}


def _verify_current13_success_write_set(state_root: Path, target: str,
                                       run_id: str, product_sha: str,
                                       input_identity: str, attempt: dict[str, Any],
                                       outcome: str,
                                       preimage: dict[str, Any]) -> dict[str, Any]:
    archived = preimage["archived"]["run_id"]
    current = preimage["current"]["run_id"]
    run_root = state_root / "workspace_plan_runs" / target
    plan_root = state_root / "workspace_plans" / target
    if outcome == "REUSE":
        if (run_id != current or product_sha != preimage["current"]["product_sha256"]
                or input_identity != preimage["current"]["input_identity"]):
            raise ValueError("R6_REUSE_IDENTITY_NOT_CURRENT_R4B_PRODUCT")
        _directory_write_set(run_root, {"latest.json", archived + ".json", current + ".json"},
                             "R6_REUSE_RUN")
        _directory_write_set(plan_root, {"latest.json", archived + ".json", current + ".json"},
                             "R6_REUSE_PRODUCT")
        observed = _capture_r6_state_preimage(state_root, target, preimage["receipt_pins"])
        if observed["state_files"] != preimage["state_files"]:
            raise ValueError("R6_REUSE_MATERIALIZED_STATE_CHANGED")
        current_attempt_raw = _stable_exact_bytes(run_root / (current + ".json"), "R6_REUSE_CURRENT_ATTEMPT")
        current_attempt = _decode_record(current_attempt_raw, "R6_REUSE_CURRENT_ATTEMPT")
        if (attempt != current_attempt or attempt.get("run_id") != current
                or attempt.get("input_identity") != input_identity):
            raise ValueError("R6_REUSE_ATTEMPT_IDENTITY_MISMATCH")
        allowed = sorted({"latest.json", archived + ".json", current + ".json"})
        return {"status": "PASS_R6_REUSE_NO_NEW_MATERIALIZATION",
                "mode": "REUSE", "current_run_id": current,
                "current_product_sha256": product_sha, "input_identity": input_identity,
                "archived_version_preserved": True, "r4b_current_version_preserved": True,
                "latest_still_357": True, "new_files": [],
                "allowed_run_write_set": allowed, "allowed_product_write_set": allowed,
                "allowed_target_write_set": allowed,
                "expected_durable_paths": [str(run_root / name) for name in allowed]
                    + [str(plan_root / name) for name in allowed],
                "owner_lock_free": True}
    if outcome != "FRESH":
        raise ValueError("R6_OWNER_OUTCOME_UNKNOWN")
    if (not re.fullmatch(r"[0-9a-f]{32}", run_id) or run_id in {archived, current}
            or input_identity == preimage["current"]["input_identity"]):
        raise ValueError("R6_FRESH_RESULT_DID_NOT_CHANGE_INPUT_IDENTITY")
    expected = {"latest.json", archived + ".json", current + ".json", run_id + ".json"}
    _directory_write_set(run_root, expected, "R6_FRESH_RUN")
    _directory_write_set(plan_root, expected, "R6_FRESH_PRODUCT")
    _verify_preserved_r6_versions(state_root, target, preimage)
    run_latest_raw = _stable_exact_bytes(run_root / "latest.json", "R6_FRESH_RUN_LATEST")
    run_file_raw = _stable_exact_bytes(run_root / (run_id + ".json"), "R6_FRESH_RUN_RECORD")
    product_latest_raw = _stable_exact_bytes(plan_root / "latest.json", "R6_FRESH_PRODUCT_LATEST")
    product_file_raw = _stable_exact_bytes(plan_root / (run_id + ".json"), "R6_FRESH_PRODUCT_RECORD")
    if run_latest_raw != run_file_raw or product_latest_raw != product_file_raw:
        raise ValueError("R6_FRESH_LATEST_POINTER_BYTES_MISMATCH")
    run_record = _decode_record(run_file_raw, "R6_FRESH_RUN_RECORD")
    product_record = _decode_record(product_file_raw, "R6_FRESH_PRODUCT_RECORD")
    if (run_record != attempt or run_record.get("run_id") != run_id
            or run_record.get("target_trade_date") != target
            or run_record.get("input_identity") != input_identity
            or run_record.get("state") not in {"SUCCEEDED", "SUCCEEDED_EMPTY", "PARTIAL"}
            or product_record.get("run_id") != run_id
            or product_record.get("target_trade_date") != target
            or product_record.get("input_identity") != input_identity
            or product_record.get("sha256") != product_sha
            or product_record.get("owner") != common.OWNER
            or product_record.get("execution_kind") != "MANUAL_REFRESH"
            or common.canonical_sha({key: value for key, value in product_record.items()
                                     if key != "sha256"}) != product_sha
            or any(product_record.get(key) != value for key, value in common.SAFETY.items())):
        raise ValueError("R6_FRESH_PERSISTED_PRODUCT_ATTEMPT_MISMATCH")
    if common.protected_state_hashes(state_root) != preimage["protected_dates_sha256"]:
        raise ValueError("R6_FRESH_PROTECTED_DATES_CHANGED")
    if not _kernel_lock_is_free(state_root / ".locks" / (target + "-workspace-plan-refresh.mutex")):
        raise ValueError("R6_FRESH_OWNER_LOCK_BUSY")
    allowed = sorted(expected)
    return {"status": "PASS_R6_FRESH_MATERIALIZATION_PRIOR_GENERATIONS_PRESERVED",
            "mode": "FRESH", "archived_run_id": archived,
            "r4b_prior_current_run_id": current, "current_run_id": run_id,
            "current_product_sha256": product_sha, "input_identity": input_identity,
            "archived_version_preserved": True, "r4b_current_version_preserved": True,
            "allowed_run_write_set": allowed, "allowed_product_write_set": allowed,
            "allowed_target_write_set": allowed,
            "expected_durable_paths": [str(run_root / name) for name in allowed]
                + [str(plan_root / name) for name in allowed],
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
        owner_outcome = ("REUSE" if refresh_body["plan_product"].get("status") == "ALREADY_MATERIALIZED"
                         else "FRESH")
        if existing_preimage is None:
            expected_files = {"latest.json", expected_run}
            run_files = {p.name for p in run_root.iterdir() if p.is_file() and not p.is_symlink()} if run_root.is_dir() else set()
            plan_files = {p.name for p in plan_root.iterdir() if p.is_file() and not p.is_symlink()} if plan_root.is_dir() else set()
            write_set_valid = run_files == expected_files and plan_files == expected_files
        else:
            current13_state_check = _verify_current13_success_write_set(
                state_root, target, run_id, product_sha, input_identity,
                refresh_body["workspace_plan_attempt"], owner_outcome, existing_preimage
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
            "owner_terminal_attempt": {
                "run_id": refresh_body["workspace_plan_attempt"]["run_id"],
                "sha256": refresh_body["workspace_plan_attempt"]["sha256"],
                "state": refresh_body["workspace_plan_attempt"]["state"],
                "owner": refresh_body["workspace_plan_attempt"]["owner"],
                "execution_kind": refresh_body["workspace_plan_attempt"]["execution_kind"],
                "input_identity": refresh_body["workspace_plan_attempt"]["input_identity"],
                "finished_at": refresh_body["workspace_plan_attempt"]["finished_at"],
                "post_get_persisted_product_equal": True,
            },
            "owner_materialization_outcome": owner_outcome,
            "state_preimage": ({
                "protected_dates_sha256": protected_before,
                "target_preexisted": False,
                "expected_durable_paths": [str(run_root / "latest.json"), str(run_root / expected_run),
                                           str(plan_root / "latest.json"), str(plan_root / expected_run)],
            } if existing_preimage is None else {
                "protected_dates_sha256": protected_before,
                "target_preexisted": True,
                "archived_generation": existing_preimage["archived"],
                "r4b_current_generation": existing_preimage["current"],
                "two_generation_state_files": existing_preimage["state_files"],
                "r4b_receipt_pins": existing_preimage["r4b_two_generation_receipt_pins"],
                "expected_durable_paths": current13_state_check.get("expected_durable_paths",
                    [str(run_root / name) for name in current13_state_check["allowed_run_write_set"]]
                    + [str(plan_root / name) for name in current13_state_check["allowed_product_write_set"]]),
                "allowed_transition": ("reuse: d8 and 357 version files plus latest remain byte-identical" if owner_outcome == "REUSE"
                    else "fresh: preserve d8 and 357 version files; only the exact validated new run/product and latest pointers may be added or advanced"),
            }),
            "owner_state_acceptance": ({"mode": "FRESH_TARGET", "prior_target_state": "ABSENT"}
                                        if existing_preimage is None else {
                "mode": "R6_CURRENT13_" + owner_outcome,
                "preimage_verified": True,
                "archived_r3_generation_preserved": existing_preimage["archived"],
                "r4b_current_generation_preserved_before_call": existing_preimage["current"],
                "owner_attempt_identity_verified": {
                    "run_id": refresh_body["workspace_plan_attempt"]["run_id"],
                    "sha256": refresh_body["workspace_plan_attempt"]["sha256"],
                    "state": refresh_body["workspace_plan_attempt"]["state"],
                    "owner": refresh_body["workspace_plan_attempt"]["owner"],
                    "execution_kind": refresh_body["workspace_plan_attempt"]["execution_kind"],
                    "input_identity": refresh_body["workspace_plan_attempt"]["input_identity"],
                    "finished_at": refresh_body["workspace_plan_attempt"]["finished_at"],
                },
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
                "mode": "R6_CURRENT13_" + owner_outcome,
                "archived_r3_run_id": existing_preimage["archived"]["run_id"],
                "r4b_prior_current_run_id": existing_preimage["current"]["run_id"],
                "prior_generations_preserved": True,
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
                        help="new directory below task receipts; R6 target13 defaults to execution-03")
    parser.add_argument("--execute", action="store_true",
                        help="explicitly run the exact owner POST/GET; writes only target-date plan state")
    parser.add_argument("--recover-existing", action="store_true",
                        help="verify the pinned successful execution-01 POST/GET and write fresh receipts; never calls HTTP")
    parser.add_argument("--verify-only", action="store_true",
                        help="with --recover-existing, validate evidence and current state without writing receipts")
    parser.add_argument("--accept-existing-current13", action="store_true",
                        help="R6 target-20261013 only: verify exact d8 archive plus 357 current preimage; add --execute only for parent-owned POST/GET")
    args = parser.parse_args(argv)
    if args.execute and args.recover_existing:
        parser.error("--execute and --recover-existing are mutually exclusive")
    if args.verify_only and not args.recover_existing:
        parser.error("--verify-only requires --recover-existing")
    if args.accept_existing_current13 and args.recover_existing:
        parser.error("--accept-existing-current13 cannot combine with --recover-existing")
    if args.accept_existing_current13 and args.target_date != _R6_CURRENT13_ACCEPTANCE["target_trade_date"]:
        parser.error("--accept-existing-current13 is pinned to 20261013")
    app_root = args.app_root
    release, live, identity = _load_identity(app_root, args.api_plist, args.scheduler_plist)
    now = datetime.now(ZoneInfo("Asia/Hong_Kong"))
    common.require_next_session(args.target_date, app_root, now)
    runtime_roots = common.resolve_api_runtime_roots(live["api"], live["api_env"])
    output = _output_path(args.output_dir, args.target_date,
                          default_execution=("execution-03" if args.accept_existing_current13
                                             else "execution-02" if args.recover_existing else "execution-01"))
    if args.accept_existing_current13 and not args.execute and not args.recover_existing:
        if runtime_roots["stage_mode"] != "shared":
            raise ValueError("CURRENT13_ACCEPTANCE_API_STAGE_MODE_NOT_SHARED")
        existing_preimage = _current13_existing_preimage(identity, args.target_date, now)
        if output.exists() or output.is_symlink():
            raise FileExistsError("CURRENT13_ACCEPTANCE_OUTPUT_ALREADY_EXISTS:" + str(output))
        result = {
            "status": "READY_FOR_PARENT_OWNED_R6_CURRENT13_POST_GET_ACCEPTANCE",
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
                "archived_generation": existing_preimage["archived"],
                "r4b_current_generation": existing_preimage["current"],
                "files": existing_preimage["state_files"],
                "r4b_two_generation_receipt_pins": existing_preimage["r4b_two_generation_receipt_pins"],
                "allowed_transition": "preserve d8 and 357 version files; only exact changed-input fresh R6 materialization or verified same-input REUSE is accepted",
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
                        "status": "FAIL_CANNOT_CONFIRM_EXACT_FAILED_JOURNAL_AND_PRIOR_PRODUCT_LATEST_PRESERVED",
                        "error": type(preservation_error).__name__ + ":" + str(preservation_error),
                        "writes": "NOT_ATTEMPTED",
                    }
            _write_exclusive(output / "failure-receipt.json", _json_bytes(failure))
            raise
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
