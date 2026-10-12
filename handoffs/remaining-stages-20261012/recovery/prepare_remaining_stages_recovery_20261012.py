#!/usr/bin/env python3
"""Prepare isolated validation for the 09:40 and 09:45 V4 stages.

Default ``dry-run`` mode pins the explicit deployed app/config and writes all
store/receipt output below a new evidence directory. It exercises the approved
09:40 HK-only scoped recovery and the normal 09:45 dispatcher using saved raw
only. The explicit ``consume-0940`` mode is a one-shot live command for the
parent after independent PASS; it uses the same receipt/SHA/budget/SlotLock
gates and has no provider-call path. The normal dispatcher remains guarded.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import os
import shlex
import shutil
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from zoneinfo import ZoneInfo

EVIDENCE_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_REMAINING_STAGE_RECOVERY_20261012")
CANDIDATE_REVIEW_ROOT = EVIDENCE_ROOT / "prepared_candidate_20261012_r2"
TDX_ROOT = EVIDENCE_ROOT / "tdx_0940_exhq_remaining99_20261012_r1"
CANARY_ROOT = EVIDENCE_ROOT / "tdx_0940_exhq_canary_20261012_r3"
TRADE_DATE = "20261012"
SHANGHAI = ZoneInfo("Asia/Shanghai")
SAFETY_FALSE = {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}

EXPECTED_RELEASE_MANIFEST_SHA256 = "6bb5592a316e2bb822f2cfb7743074887c46a9894a5ef7b3b975bd05958eda79"
EXPECTED_CONFIG_SHA256 = "4fae43270f368881727c69f916f3cc22fdb74fd1e5bd5d7496c5fcbdd01c71c4"
EXPECTED_CANDIDATE_DOMAIN_SHA256 = "166ea3e10dcb49828226c9f6760a5c4674832574d66297c3cd7ba0bb3fa7d15d"
SOURCE_PINS = {
    "stage_center/runner.py": "1bb6363dfa522cdc05f8d1d1e727bf120f4daadbb2579600fc465a6d12e11663",
    "stage_center/_runner_parts/slot_execution.py": "278085fb1effdc9dcf5c5dc9626d68faea0bc53c44f66be4eb89f9a0415fc07a",
    "stage_center/_runner_parts/slot_idempotency.py": "2f79cdfedd50e047f22beaafe254edff420a7fb28be6379ba9a92a475abfa39c",
    "stage_center/_runner_parts/runner_receipts.py": "d3d9e69230b00a2864eae106f1c5c89ea0d383e20c2e87d655d4cabd273bbc83",
    "stage_center/raw_store.py": "15052b23c62d38b65d65b96bf3b837782ebfa6fca7fe83f7c1d9374400bbdbde",
    "stage_center/selection.py": "8fa7d50a4b51302ddc61479c2a9cd865aedf112d437f8d01a42bbae73e235957",
    "stage_center/live_collectors.py": "82a08c2bbe286184e1a224d0a44e576d0f812f1ec2929ded303ab191a1d554bf",
    "stage_center/_live_collectors_parts/selection_builder_registry.py": "5b315c482723f4bbfb187e36241ea422f2a59518a2056be037d1fdbe2f00eb22",
    "stage_center/_live_collectors_parts/hk_minute.py": "b6c78a4ffd7193d0e1afeee530a1c4c123e72a20ba3bc9f8183727dcca58a179",
    "stage_center/_selection_parts/hk_four_lanes.py": "d44cd657b15b806922dd99317cfe759849a0d59884a0e39a533f0204f530ae71",
    "stage_center/attempt_evidence.py": "f98a9070ade0c26a3cfa0bf60acd4798ec011330ca83bc172c64856bd88dc1bf",
    "stage_center/end_to_end_deadline.py": "f25d91cf1eaf4ea7d1a9a57fc1f8288d14d98536a63dee16467550974b2a812e",
    "ops/run_stage_center_nodes.py": "8e9ca56aca8a21950590abe83ef305e46a022490eb61f48e0c5d19c2493e1772",
    "ops/_run_stage_center_nodes_parts/stage_dispatch.py": "fc3a40dbee0ee438abaa9723bfee3d96acc86e31ed6e9a79239c04f03c18e11a",
}
EXPECTED_RECEIPTS = {
    "STAGE_0940_0945": "bd74ed2a54c8f05dbd3cf1bd6434f1895fae9369f04e041d2ba4f4fa34baee43",
    "STAGE_0945_1030": "4669e0e04635e52559e0463224535582d6679c01fb055232892d8e84b06a2fa4",
}
EXPECTED_RAW = {
    ("STAGE_0940_0945", "A_SHARE"): ("29d83d1977796d63464848ac5daeec1e91db274e34e4e5b0b9a2d6f160fc17e7", "fc61111f4d04a86fa40cd589062b2b7b07fd8ad87552d3f0b1c66915929696d6"),
    ("STAGE_0945_1030", "A_SHARE"): ("f59db74e678cdab9f81baaa70ca4b026cb96cb2731c2e81ed05c75d5b6fa1dcf", "015684ed7d397d5e770088ffa8b30fad0351bcfa107dc4324b482ff24169546c"),
    ("STAGE_0945_1030", "HK_CONNECT"): ("7ca6916c92b89e1748303e072e42fb86bf25a300fe39c2a136d34de3c0aed043", "0610f8a4c510a5048dfb8e38fdad0decf5529f29a13c6d1143614fe7357ad77f"),
}
EXPECTED_TDX_FILES = {
    "run_spec.json": "5f044c3e79d5b5d50feb2812810301d846dfa1b92a6b445e3d2858d6299ddebe",
    "fullbatch_result.json": "09820e3008a7a01bf6632d2ec32ea33ddf96692ebc2338c618ba45d352ef17bc",
    "combined_stage_rows.json": "7801e42878c97e6261a7d0ff5e1ce8615888fdaa9bb9a9b62a7cb242b3d67c6d",
}
EXPECTED_D1_SHA256 = "220fd29bc907a1c4e431c75fb8eccb3204c5857130eb639f1e9b6a62b60cfe3d"
EXPECTED_A_0940_SELECTION_ARTIFACT_SHA256 = "86f12b4fde910d6a629a827a956bad46ae6bd3594a59dd5389e2c95c4c364279"
EXPECTED_0940_HK_FAILURES = (
    "PyTDX ExHQ probe returned an error",
    "PyTDX ExHQ batch coverage incomplete: completed=0/100",
)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    return sha256(path.read_bytes())


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    path.write_bytes(raw)
    return sha256(raw)


def tree_sha_map(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {p.relative_to(root).as_posix(): sha_file(p) for p in sorted(root.rglob("*")) if p.is_file()}


def safe_relative(root: Path, value: Any) -> Path:
    rel = PurePosixPath(str(value or ""))
    if not rel.parts or rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"unsafe store pointer: {value!r}")
    result = root.joinpath(*rel.parts)
    if root.resolve() not in (result.resolve(), *result.resolve().parents):
        raise ValueError("store pointer escaped root")
    return result


def copy_artifact_run(source_root: Path, target_root: Path, entry: Mapping[str, Any], relative_key: str) -> dict[str, Any]:
    artifact = safe_relative(source_root, entry.get(relative_key))
    run_dir = artifact.parent
    relative_run = run_dir.relative_to(source_root)
    target_run = target_root / relative_run
    if target_run.exists():
        raise FileExistsError(target_run)
    if not run_dir.is_dir():
        raise FileNotFoundError(run_dir)
    source_tree = tree_sha_map(run_dir)
    shutil.copytree(run_dir, target_run)
    if tree_sha_map(target_run) != source_tree:
        raise AssertionError(f"immutable run copy mismatch: {relative_run}")
    return {"relative_run": relative_run.as_posix(), "file_count": len(source_tree), "tree_sha256": sha256(json.dumps(source_tree, sort_keys=True).encode())}


def app_identity(app_root: Path, config_path: Path, candidate_domain: Path) -> dict[str, Any]:
    app_root = app_root.resolve(strict=True)
    config_path = config_path.resolve(strict=True)
    candidate_domain = candidate_domain.resolve(strict=True)
    if config_path != (app_root / "stage_center_tick_config.json").resolve():
        raise ValueError("--config must be the explicitly selected app-root stage config")
    if sha_file(app_root.parent / "release-manifest.json") != EXPECTED_RELEASE_MANIFEST_SHA256:
        raise ValueError("prepared release manifest SHA changed")
    if sha_file(config_path) != EXPECTED_CONFIG_SHA256:
        raise ValueError("prepared release config SHA changed")
    if sha_file(candidate_domain) != EXPECTED_CANDIDATE_DOMAIN_SHA256:
        raise ValueError("frozen candidate domains/research.py SHA changed")
    if sha_file(app_root / "domains/research.py") != EXPECTED_CANDIDATE_DOMAIN_SHA256:
        raise ValueError("explicit app root does not contain the frozen candidate domain")
    source_hashes = {}
    for rel, expected in SOURCE_PINS.items():
        path = app_root / rel
        got = sha_file(path)
        if got != expected:
            raise ValueError(f"pinned runtime source changed: {rel}")
        source_hashes[rel] = got
    config = read_json(config_path)
    if config.get("release_id") != "remaining-stages-recovery-20261012-r1":
        raise ValueError("stage config release identity changed")
    if Path(str(config.get("shared_data_root"))).resolve() != (app_root / "upstreams/v3_shared_data").resolve():
        raise ValueError("stage config shared-data root does not resolve under explicit app root")
    if config.get("safety") != SAFETY_FALSE or config.get("node_max_attempts") != 3:
        raise ValueError("research-only flags or original attempt budget changed")
    review_path = CANDIDATE_REVIEW_ROOT / "independent_review_receipt.json"
    validation_path = CANDIDATE_REVIEW_ROOT / "isolated_candidate_validation.json"
    review = read_json(review_path)
    validation = read_json(validation_path)
    if review.get("verdict") != "PASS" or review.get("actual_diff", {}).get("candidate_domain_sha256") != EXPECTED_CANDIDATE_DOMAIN_SHA256:
        raise ValueError("frozen warning-projection candidate has no matching independent PASS")
    if validation.get("candidate_status") != "PASS" or validation.get("candidate_domain_sha256_after") != EXPECTED_CANDIDATE_DOMAIN_SHA256:
        raise ValueError("frozen warning-projection candidate validation changed")

    # Import only after the explicit app root is first on sys.path.
    sys.path.insert(0, str(app_root))
    shared_root = Path(str(config["shared_data_root"]))
    sys.path.insert(1, str(shared_root))
    research = importlib.import_module("domains.research")
    if Path(research.__file__).resolve() != (app_root / "domains/research.py").resolve():
        raise ValueError("runtime imported a research module outside the explicit app root")
    if not callable(getattr(research, "_report_role_warning_reasons", None)):
        raise ValueError("candidate warning projection helper not loaded from release")
    return {
        "app_root": str(app_root),
        "config_path": str(config_path),
        "config_sha256": EXPECTED_CONFIG_SHA256,
        "release_manifest_sha256": EXPECTED_RELEASE_MANIFEST_SHA256,
        "candidate_domain_sha256": EXPECTED_CANDIDATE_DOMAIN_SHA256,
        "candidate_domain_loaded_from": str(Path(research.__file__).resolve()),
        "runtime_source_sha256": source_hashes,
        "warning_projection_review_receipt_sha256": sha_file(review_path),
        "warning_projection_validation_sha256": sha_file(validation_path),
        "warning_projection_validation": {
            "verdict": review.get("verdict"),
            "archive_warning": (review.get("independent_isolated_replay") or {}).get("warning"),
            "loaded_context_warning_provenance_present": validation.get("loaded_context_source_warning_provenance_present"),
            "stage_selection_warning_presentation": "CANNOT_CONFIRM_NOT_IN_FROZEN_STAGE_SCOPE",
        },
    }


def input_receipt(config: Mapping[str, Any], stage_id: str) -> tuple[Path, bytes, dict[str, Any]]:
    path = Path(str(config["receipt_root"])) / TRADE_DATE / stage_id / "receipt.json"
    raw = path.read_bytes()
    if sha256(raw) != EXPECTED_RECEIPTS[stage_id]:
        raise ValueError(f"initial receipt SHA changed: {stage_id}")
    receipt = json.loads(raw)
    if receipt.get("trade_date") != TRADE_DATE or receipt.get("stage_id") != stage_id or receipt.get("node_attempt_count") != 1:
        raise ValueError(f"initial receipt identity/attempt changed: {stage_id}")
    if any(receipt.get(flag) is not False for flag in SAFETY_FALSE):
        raise ValueError(f"unsafe initial receipt flags: {stage_id}")
    return path, raw, receipt


def snapshot_protected_a(config: Mapping[str, Any]) -> dict[str, Any]:
    raw_root = Path(str(config["raw_root"]))
    selection_root = Path(str(config["selection_root"]))
    receipt_root = Path(str(config["receipt_root"]))
    raw_latest_path = raw_root / "latest.json"
    selection_latest_path = selection_root / "selection_latest.json"
    raw_latest = read_json(raw_latest_path)
    selection_latest = read_json(selection_latest_path)
    stages = ("STAGE_0925", "STAGE_0930_0935", "STAGE_0935_0940", "STAGE_0940_0945", "STAGE_0945_1030")
    keys = [f"{TRADE_DATE}/{stage}/A_SHARE" for stage in stages]
    raw_entries = {key: raw_latest.get("entries", {}).get(key) for key in keys}
    selection_entries = {key: selection_latest.get("entries", {}).get(key) for key in keys}
    raw_trees: dict[str, dict[str, str]] = {}
    selection_trees: dict[str, dict[str, str]] = {}
    for key, entry in raw_entries.items():
        if isinstance(entry, Mapping):
            artifact = safe_relative(raw_root, entry.get("artifact_relative"))
            raw_trees[key] = tree_sha_map(artifact.parent)
        else:
            raw_trees[key] = {}
    for key, entry in selection_entries.items():
        if isinstance(entry, Mapping):
            artifact = safe_relative(selection_root, entry.get("artifact_relative"))
            selection_trees[key] = tree_sha_map(artifact.parent)
        else:
            selection_trees[key] = {}
    receipts = {}
    for stage in stages:
        path = receipt_root / TRADE_DATE / stage / "receipt.json"
        receipts[stage] = sha_file(path) if path.is_file() else None
    return {
        "raw_latest_sha256": sha_file(raw_latest_path),
        "selection_latest_sha256": sha_file(selection_latest_path),
        "raw_a_entries": raw_entries,
        "selection_a_entries": selection_entries,
        "raw_a_run_trees": raw_trees,
        "selection_a_run_trees": selection_trees,
        "a_receipt_sha256": receipts,
    }


def seed_isolated_stage(config: dict[str, Any], stage_root: Path, stage_id: str, markets: tuple[str, ...], receipt_raw: bytes) -> dict[str, Any]:
    live_raw = Path(str(config["raw_root"]))
    live_selection = Path(str(config["selection_root"]))
    live_receipts = Path(str(config["receipt_root"]))
    temp_state = stage_root / "stage_state"
    temp_raw = temp_state / "raw"
    temp_selection = temp_state / "selection"
    temp_receipts = temp_state / "receipts"
    for path in (temp_raw, temp_selection, temp_receipts):
        path.mkdir(parents=True, exist_ok=False)

    copied: list[dict[str, Any]] = []
    for live_root, target_root, pointer_names in (
        (live_raw, temp_raw, ("latest.json", "bundle_latest.json")),
        (live_selection, temp_selection, ("selection_latest.json",)),
    ):
        for name in pointer_names:
            source = live_root / name
            if source.is_file():
                (target_root / name).write_bytes(source.read_bytes())

    raw_latest = read_json(temp_raw / "latest.json")
    selection_latest = read_json(temp_selection / "selection_latest.json")
    slot = f"{TRADE_DATE}/{stage_id}"
    raw_store = importlib.import_module("stage_center.raw_store").RawStore(live_raw)
    selection_store_type = importlib.import_module("stage_center.selection").SelectionStore
    live_selection_store = selection_store_type(live_selection)
    for market in markets:
        key = f"{slot}/{market}"
        raw_entry = raw_latest.get("entries", {}).get(key)
        if not isinstance(raw_entry, Mapping):
            raise ValueError(f"required existing raw pointer missing: {key}")
        expected_artifact, expected_manifest_file = EXPECTED_RAW[(stage_id, market)]
        verified = raw_store.verify_latest(TRADE_DATE, stage_id, market)["verified"]
        manifest_path = safe_relative(live_raw, verified.get("manifest_relative"))
        if (
            verified.get("artifact_sha256") != expected_artifact
            or raw_entry.get("manifest_sha256") != verified.get("manifest_sha256")
            or sha_file(manifest_path) != expected_manifest_file
        ):
            raise ValueError(f"raw store source identity changed: {key}")
        copied.append({"store": "raw", "market": market, **copy_artifact_run(live_raw, temp_raw, raw_entry, "artifact_relative")})
        if stage_id == "STAGE_0940_0945" and market == "A_SHARE":
            selection_entry = selection_latest.get("entries", {}).get(key)
            if not isinstance(selection_entry, Mapping):
                raise ValueError("preserved A_SHARE selection pointer missing for 09:40")
            envelope = live_selection_store.read_verified(TRADE_DATE, stage_id, market)
            if envelope.get("raw_artifact_sha256") != expected_artifact or selection_entry.get("artifact_sha256") != EXPECTED_A_0940_SELECTION_ARTIFACT_SHA256:
                raise ValueError("preserved 09:40 A selection does not bind its raw artifact")
            copied.append({"store": "selection", "market": market, **copy_artifact_run(live_selection, temp_selection, selection_entry, "artifact_relative")})

    # STAGE_0945_1030 already has a verified raw bundle; its immutable bundle
    # directory is needed for the original _existing_slot/readback path.
    if stage_id == "STAGE_0945_1030":
        bundle_pointer = temp_raw / "bundle_latest.json"
        if not bundle_pointer.is_file():
            raise ValueError("09:45 raw bundle latest pointer missing")
        bundle_entry = read_json(bundle_pointer).get("entries", {}).get(slot)
        if not isinstance(bundle_entry, Mapping):
            raise ValueError("09:45 existing raw bundle pointer missing")
        bundle_receipt = safe_relative(live_raw, bundle_entry.get("receipt_relative"))
        bundle_dir = bundle_receipt.parent
        relative_bundle = bundle_dir.relative_to(live_raw)
        target_bundle = temp_raw / relative_bundle
        before_tree = tree_sha_map(bundle_dir)
        shutil.copytree(bundle_dir, target_bundle)
        if tree_sha_map(target_bundle) != before_tree:
            raise AssertionError("09:45 bundle copy hash mismatch")
        copied.append({"store": "raw_bundle", "relative_run": relative_bundle.as_posix(), "file_count": len(before_tree), "tree_sha256": sha256(json.dumps(before_tree, sort_keys=True).encode())})

    initial_receipt_path = temp_receipts / TRADE_DATE / stage_id / "receipt.json"
    initial_receipt_path.parent.mkdir(parents=True, exist_ok=False)
    initial_receipt_path.write_bytes(receipt_raw)
    config["raw_root"] = str(temp_raw)
    config["selection_root"] = str(temp_selection)
    config["receipt_root"] = str(temp_receipts)
    return {
        "isolated_root": str(temp_state),
        "initial_receipt_sha256": sha256(receipt_raw),
        "copied_immutable_runs": copied,
        "raw_latest_sha256_before_run": sha_file(temp_raw / "latest.json"),
        "selection_latest_sha256_before_run": sha_file(temp_selection / "selection_latest.json"),
        "initial_bundle_latest_sha256": sha_file(temp_raw / "bundle_latest.json") if (temp_raw / "bundle_latest.json").is_file() else None,
    }


def cache_rows_0940() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    for rel, expected in EXPECTED_TDX_FILES.items():
        if sha_file(TDX_ROOT / rel) != expected:
            raise ValueError(f"pinned 09:40 TDX input changed: {rel}")
    spec = read_json(TDX_ROOT / "run_spec.json")
    summary = read_json(TDX_ROOT / "fullbatch_result.json")
    rows = read_json(TDX_ROOT / "combined_stage_rows.json")
    if not isinstance(rows, list) or len(rows) != 100:
        raise ValueError("09:40 cache is not the frozen 100-row aggregate")
    if (
        spec.get("trade_date") != TRADE_DATE
        or spec.get("stage_id") != "STAGE_0940_0945"
        or spec.get("capture_origin") != "LATE_RECOVERY_OBSERVATION_ONLY"
        or spec.get("pit_safe") is not False
        or spec.get("natural_slot_verified") is not False
        or summary.get("source_status") != "READ_OK"
        or summary.get("requested_code_count") != 99
        or summary.get("completed_code_count") != 99
        or summary.get("raw_provider_row_count_remaining99") != 495
        or summary.get("combined_row_count") != 100
        or summary.get("combined_unique_code_count") != 100
        or summary.get("raw_provider_error_count") != 0
        or summary.get("reused_canary_code") != "HK.02915"
        or spec.get("reused_canary_stdout_sha256") != "e83fc8ce6454d60290a7bab221131e966e4d08dfe8b68b54f6a4ebf4791d2f01"
    ):
        raise ValueError("09:40 cached observation provenance does not match the frozen receipt")
    code_list = [str(row.get("code") or "").upper() for row in rows]
    if len(set(code_list)) != 100 or any(row.get("bar_count") != 5 for row in rows):
        raise ValueError("09:40 cached aggregate violates 100-code/five-bar contract")
    capture_started = str(summary.get("started_at_utc") or "")
    if capture_started != "2026-10-12T03:50:06.065+00:00":
        raise ValueError("09:40 cached capture time changed")
    return rows, {
        "run_spec_sha256": EXPECTED_TDX_FILES["run_spec.json"],
        "fullbatch_result_sha256": EXPECTED_TDX_FILES["fullbatch_result.json"],
        "combined_rows_sha256": EXPECTED_TDX_FILES["combined_stage_rows.json"],
        "requested_remaining_codes": 99,
        "completed_remaining_codes": 99,
        "remaining_raw_bars": 495,
        "combined_codes_with_saved_canary": 100,
        "capture_started_at_utc": capture_started,
        "capture_origin": spec["capture_origin"],
        "pit_safe": False,
        "natural_slot_verified": False,
        "saved_canary_code": spec["reused_canary_code"],
        "saved_canary_stdout_sha256": spec["reused_canary_stdout_sha256"],
        "provider_calls_during_this_script": 0,
    }


def command_for(node: str, app_root: Path, config_path: Path, python_path: Path) -> str:
    script = app_root / "ops/run_stage_center_nodes.py"
    args = [str(python_path), "-B", str(script), "--config", str(config_path), "--node", node, "--trade-date", TRADE_DATE]
    return " ".join(shlex.quote(arg) for arg in args)


def controlled_0940_command(app_root: Path, config_path: Path, candidate_domain: Path,
                            python_path: Path, output_root: Path) -> str:
    script = Path(__file__).resolve()
    args = [
        str(python_path), "-B", str(script), "--mode", "consume-0940",
        "--app-root", str(app_root), "--config", str(config_path),
        "--candidate-domain", str(candidate_domain), "--output-root", str(output_root),
    ]
    return " ".join(shlex.quote(arg) for arg in args)


def protected_a_equal(before: Mapping[str, Any], after: Mapping[str, Any], *, ignore_receipt_stage: str | None = None) -> bool:
    a_fields = ("raw_a_entries", "selection_a_entries", "raw_a_run_trees", "selection_a_run_trees")
    if any(before.get(field) != after.get(field) for field in a_fields):
        return False
    before_receipts = dict(before.get("a_receipt_sha256") or {})
    after_receipts = dict(after.get("a_receipt_sha256") or {})
    if ignore_receipt_stage is not None:
        before_receipts.pop(ignore_receipt_stage, None)
        after_receipts.pop(ignore_receipt_stage, None)
    return before_receipts == after_receipts


def _decision_for_late_observation(node, runner, stage_id: str, evaluated_at: datetime):
    decisions = runner.due_decisions(TRADE_DATE, evaluated_at, historical_backfill=False)
    decision = next((item for item in decisions if item.stage_id == stage_id), None)
    if decision is None or decision.status != "LATE_CATCHUP_REPLAY":
        raise ValueError(f"expected same-day late replay for {stage_id}")
    from ops._run_stage_center_nodes_parts import stage_dispatch
    decision.same_day_late_observation_recovery = stage_dispatch._same_day_late_observation_recovery(
        node.__dict__, mode="RECOVERY", trade_date=TRADE_DATE, evaluated_at=evaluated_at, decision=decision
    )
    if decision.same_day_late_observation_recovery is not True:
        raise ValueError("existing same-day late-observation helper did not authorize the observation mode")
    return decision


def _create_attempt_reservation(scoped_runner, receipt: dict[str, Any], stage_id: str, attempt_count: int,
                                mode: str, max_attempts: int) -> dict[str, Any]:
    return scoped_runner._write_receipt(
        {
            **receipt,
            "status": "CANNOT_CONFIRM",
            "node_outcome": "TRANSIENT",
            "node_attempt_count": attempt_count,
            "retry_exhausted": attempt_count >= max_attempts,
            "dispatch_mode": mode,
            "execution_pending": True,
            "partial_commit_possible": True,
            "write_performed": False,
        },
        TRADE_DATE,
        stage_id,
    )


def _cached_0940_hk_collector(rows: list[dict[str, Any]], provenance: Mapping[str, Any], call_count: dict[str, int]):
    from stage_center.acquisition import SourceResult

    expected_codes = {str(row.get("code") or "").upper() for row in rows}
    source_evidence = (
        f"tdx_combined_rows_sha256={provenance['combined_rows_sha256']}",
        f"tdx_capture_started_at_utc={provenance['capture_started_at_utc']}",
        "capture_origin=LATE_RECOVERY_OBSERVATION_ONLY",
        "same_day_late_observation_recovery=true",
        "active_snapshot_degraded_to_pytdx_observation=true",
        "active_snapshot_status=NOT_COLLECTED_NO_PROVIDER_CALL",
        "active_snapshot_temporal_cutoff_safe=false",
        "observation_verification=UNVERIFIED",
        "pit_safe=false",
        "natural_slot_verified=false",
        "selection_authority=OBSERVATION_ONLY",
    )

    def collector(plan, market):
        call_count["cache_adapter_calls"] += 1
        if market != "HK_CONNECT" or plan.trade_date != TRADE_DATE or plan.stage_id != "STAGE_0940_0945":
            raise ValueError("cached adapter called outside the pinned HK 09:40 slot")
        planned_codes = {str(code).upper() for code in plan.codes_for("HK_CONNECT")}
        if planned_codes != expected_codes or len(planned_codes) != 100:
            raise ValueError("cached rows do not match the exact D-1 Top100 plan")
        return SourceResult(
            source_id="pytdx_exhq",
            status="PARTIAL_WITH_ROWS",
            rows=tuple(dict(row) for row in rows),
            cannot_confirm=("TDX_CACHE_CAPTURE_AFTER_STAGE_CUTOFF", "HK_ACTIVE_SNAPSHOT_NOT_COLLECTED"),
            requested_rows=100,
            source_evidence=source_evidence,
        )

    return collector, source_evidence


def run_0940_isolated(node, base_config: Mapping[str, Any], app_root: Path, config_path: Path, output_root: Path,
                      protected_before: dict[str, Any], cache: tuple[list[dict[str, Any]], dict[str, Any]],
                      candidate_domain: Path, *, consume_live: bool = False) -> dict[str, Any]:
    stage_id = "STAGE_0940_0945"
    live_receipt_path, receipt_raw, receipt = input_receipt(base_config, stage_id)
    hk_prior = (receipt.get("markets") or {}).get("HK_CONNECT") or {}
    if (
        receipt.get("status") != "PARTIAL_WITH_ROWS"
        or receipt.get("node_outcome") != "SETTLED_PARTIAL"
        or receipt.get("node_attempt_count") != 1
        or hk_prior.get("status") != "CANNOT_CONFIRM"
        or hk_prior.get("source_status") != "CANNOT_CONFIRM"
        or hk_prior.get("selection_status") != "CANNOT_CONFIRM"
        or tuple(hk_prior.get("cannot_confirm") or ()) != EXPECTED_0940_HK_FAILURES
    ):
        raise ValueError("09:40 receipt no longer matches the exact frozen HK failure")
    max_attempts = int(base_config.get("node_max_attempts", 0))
    next_attempt = int(receipt.get("node_attempt_count", 0)) + 1
    if max_attempts != 3 or not (0 < next_attempt <= max_attempts):
        raise ValueError("09:40 has no remaining original attempt budget")

    config = deepcopy(dict(base_config))
    stage_root = output_root / stage_id
    stage_root.mkdir(parents=True, exist_ok=False)
    if consume_live:
        isolated_receipt_path = live_receipt_path
        seed = {"mode": "CONTROLLED_LIVE_ONESHOT", "live_receipt_sha256": sha256(receipt_raw), "store_roots": "configured live roots"}
    else:
        seed = seed_isolated_stage(config, stage_root, stage_id, ("A_SHARE",), receipt_raw)
        isolated_receipt_path = Path(str(config["receipt_root"])) / TRADE_DATE / stage_id / "receipt.json"
    runner = node._build_runner(config)
    if runner.config.selection_builders is not None:
        raise AssertionError("production selection builders were replaced in the isolated runner")
    rows, cache_provenance = cache
    from stage_center.runner import _build_hk_stage_binding, SlotLock, _slot_lock_path
    from stage_center._runner_parts.runner_receipts import scoped_recovery_runner
    from stage_center.attempt_evidence import capture_attempt
    from stage_center import end_to_end_deadline as deadline
    binding = _build_hk_stage_binding(
        runner.config.hk_d1_root, TRADE_DATE, preselection_source_root=runner.config.preselection_source_root
    )
    if binding.sha256 != EXPECTED_D1_SHA256 or len(binding.codes) != 100 or set(binding.codes) != {row["code"] for row in rows}:
        raise ValueError("09:40 cache does not match the pinned exact HK D-1 Top100")
    cache_adapter_calls = {"cache_adapter_calls": 0}
    adapter, adapter_evidence = _cached_0940_hk_collector(rows, cache_provenance, cache_adapter_calls)
    runner.collectors = {"HK_CONNECT": adapter}
    evaluated_at = datetime.now(SHANGHAI)
    decision = _decision_for_late_observation(node, runner, stage_id, evaluated_at)
    lock = SlotLock(_slot_lock_path(runner.config, TRADE_DATE, stage_id))
    if not lock.acquire():
        raise RuntimeError("09:40 stage slot lock is already held")
    try:
        locked_raw = isolated_receipt_path.read_bytes()
        if locked_raw != receipt_raw or sha256(locked_raw) != EXPECTED_RECEIPTS[stage_id]:
            raise ValueError("09:40 receipt bytes changed after acquiring SlotLock")
        locked_receipt = json.loads(locked_raw)
        if int(locked_receipt.get("node_attempt_count", 0)) + 1 != next_attempt:
            raise ValueError("09:40 original attempt budget changed under SlotLock")
        scoped = scoped_recovery_runner(
            runner,
            markets=("HK_CONNECT",),
            prior_receipt=locked_receipt,
            attempt_count=next_attempt,
            origin="HK_EXHQ_LATE_OBSERVATION_RECOVERY",
        )
        reservation = _create_attempt_reservation(scoped, locked_receipt, stage_id, next_attempt, "RECOVERY", max_attempts)
        if (
            reservation.get("node_attempt_count") != next_attempt
            or reservation.get("execution_markets") != ["HK_CONNECT"]
            or reservation.get("execution_pending") is not True
            or reservation.get("retry_exhausted") is not False
            or reservation.get("markets", {}).get("A_SHARE") != locked_receipt.get("markets", {}).get("A_SHARE")
        ):
            raise AssertionError("09:40 attempt reservation or A-lane preservation failed")
        deadline.due(decision.scheduled_at, trade_date=TRADE_DATE, stage_id=stage_id,
                     due_status=decision.status, dispatch_mode="RECOVERY")
        deadline.checkpoint("BUSINESS_START", trade_date=TRADE_DATE, stage_id=stage_id)
        with capture_attempt(
            scoped._receipt_path(TRADE_DATE, stage_id).parent,
            trade_date=TRADE_DATE,
            stage_id=stage_id,
            attempt_number=next_attempt,
            evaluated_at=evaluated_at.isoformat(),
            due_status=decision.status,
        ) as journal:
            try:
                result = dict(scoped._run_one(decision))
            except Exception as error:
                result = scoped._write_receipt(
                    {
                        "status": "CANNOT_CONFIRM",
                        "trade_date": TRADE_DATE,
                        "stage_id": stage_id,
                        "error": f"{type(error).__name__}:{error}",
                        "first_failed_layer": "SCOPED_EXECUTION",
                        "markets": {"HK_CONNECT": {
                            "status": "CANNOT_CONFIRM",
                            "selection_status": "CANNOT_CONFIRM",
                            "selected_rows": 0,
                            "cannot_confirm": [f"{type(error).__name__}:{error}"],
                            "write_performed": False,
                        }},
                        "write_performed": False,
                    },
                    TRADE_DATE,
                    stage_id,
                )
            journal.finish(result)
            attempt_summary = journal.summary()
        result["attempt_diagnostic"] = attempt_summary
        result.update({"node_id": stage_id, "dispatch_mode": "RECOVERY", "node_attempt_count": next_attempt, "pre_captures": []})
        final_status = str(result.get("status") or "CANNOT_CONFIRM")
        if final_status == "PARTIAL_WITH_ROWS" and result.get("write_performed") is True:
            result["error"] = None
            result["first_failed_layer"] = None
            result["partial_commit_possible"] = False
        result["node_outcome"] = node._node_outcome(final_status, result)
        result["retry_exhausted"] = bool(result["node_outcome"] == "TRANSIENT" and next_attempt >= max_attempts)
        if result["node_outcome"] == "TRANSIENT" and not result["retry_exhausted"]:
            from datetime import timedelta
            result["retry_after"] = evaluated_at.isoformat()
        else:
            result["retry_after"] = None
        persisted = scoped._write_receipt(result, TRADE_DATE, stage_id)
        deadline.complete_receipt(
            scoped._receipt_path(TRADE_DATE, stage_id),
            persisted,
            rewrite=lambda failed: scoped._write_receipt(failed, TRADE_DATE, stage_id),
        )
    finally:
        lock.release()

    after_run_raw = isolated_receipt_path.read_bytes()
    final_receipt = json.loads(after_run_raw)
    preserved_receipt_path = Path(str(config["receipt_root"])) / TRADE_DATE / stage_id / "attempt_evidence" / f"preserved-{EXPECTED_RECEIPTS[stage_id]}" / "PRIOR_RECEIPT.json"
    if not preserved_receipt_path.is_file() or preserved_receipt_path.read_bytes() != receipt_raw:
        raise AssertionError("09:40 exact original receipt was not archived by scoped recovery")
    if final_receipt.get("node_attempt_count") != next_attempt or final_receipt.get("execution_markets") != ["HK_CONNECT"]:
        raise AssertionError("09:40 final receipt does not preserve the one-shot HK-only reservation")
    if final_receipt.get("markets", {}).get("A_SHARE") != receipt.get("markets", {}).get("A_SHARE"):
        raise AssertionError("09:40 HK recovery changed the preserved A receipt lane")
    if cache_adapter_calls["cache_adapter_calls"] != 1:
        raise AssertionError(f"09:40 cache-only adapter call count changed: {cache_adapter_calls}")

    # Normal re-entry must continue to fail closed; only this exact scoped
    # one-shot used the pre-authorized control path above.
    raw_pointer_path = Path(str(config["raw_root"])) / "latest.json"
    selection_pointer_path = Path(str(config["selection_root"])) / "selection_latest.json"
    raw_pointer_before_reentry = sha_file(raw_pointer_path)
    selection_pointer_before_reentry = sha_file(selection_pointer_path)
    receipt_sha_before_reentry = sha256(after_run_raw)
    reentry = node._dispatch_stage(config, TRADE_DATE, stage_id, evaluated_at, mode="RECOVERY", runner=runner)
    if reentry.get("status") not in {"SKIPPED_ALREADY_SETTLED", "SKIPPED_RETRY_BACKOFF", "SKIPPED_RETRY_EXHAUSTED"}:
        raise AssertionError(f"09:40 standard dispatcher did not reject immediate re-entry: {reentry.get('status')}")
    if (
        sha_file(isolated_receipt_path) != receipt_sha_before_reentry
        or sha_file(raw_pointer_path) != raw_pointer_before_reentry
        or sha_file(selection_pointer_path) != selection_pointer_before_reentry
    ):
        raise AssertionError("09:40 guarded re-entry changed the final receipt or store pointers")

    raw_module = importlib.import_module("stage_center.raw_store")
    raw_store = raw_module.RawStore(Path(str(config["raw_root"])))
    hk_verified = raw_store.verify_latest(TRADE_DATE, stage_id, "HK_CONNECT")["verified"]
    hk_manifest = read_json(safe_relative(Path(str(config["raw_root"])), hk_verified["manifest_relative"]))
    if hk_verified.get("status") != "PARTIAL_WITH_ROWS" or hk_manifest.get("temporal_cutoff_safe") is not False:
        raise AssertionError("09:40 raw store did not preserve the late observation as cutoff-unsafe partial")
    if hk_verified.get("row_count") != 100 or hk_verified.get("requested_rows") != 100:
        raise AssertionError("09:40 isolated raw readback did not cover the pinned 100 code observations")
    selection_module = importlib.import_module("stage_center.selection")
    selection_store = selection_module.SelectionStore(Path(str(config["selection_root"])))
    hk_selection = selection_store.read_verified(TRADE_DATE, stage_id, "HK_CONNECT")
    hk_selection_rows = list(hk_selection.get("rows") or [])
    if (
        hk_selection.get("selection_status") != "PARTIAL_WITH_ROWS"
        or len(hk_selection_rows) != 10
        or any(str(row.get("action_level") or "").upper() != "NO_BUY" for row in hk_selection_rows)
        or "observation_verification=UNVERIFIED" not in (hk_selection.get("source_evidence") or [])
    ):
        raise AssertionError("09:40 original selection builder did not produce the unverified/NO_BUY observation output")

    hk_key = f"{TRADE_DATE}/{stage_id}/HK_CONNECT"
    isolated_raw_latest = read_json(raw_pointer_path)
    isolated_selection_latest = read_json(selection_pointer_path)
    if not isinstance(isolated_raw_latest.get("entries", {}).get(hk_key), Mapping) or not isinstance(isolated_selection_latest.get("entries", {}).get(hk_key), Mapping):
        raise AssertionError("09:40 one-shot did not publish the exact partial observation outputs in isolation")
    a_key = f"{TRADE_DATE}/{stage_id}/A_SHARE"
    if isolated_raw_latest.get("entries", {}).get(a_key) != read_json(Path(str(base_config["raw_root"])) / "latest.json").get("entries", {}).get(a_key):
        raise AssertionError("09:40 isolated preparation changed A raw pointer")
    if isolated_selection_latest.get("entries", {}).get(a_key) != read_json(Path(str(base_config["selection_root"])) / "selection_latest.json").get("entries", {}).get(a_key):
        raise AssertionError("09:40 isolated preparation changed A selection pointer")

    lock = SlotLock(_slot_lock_path(runner.config, TRADE_DATE, stage_id))
    if not lock.acquire():
        raise AssertionError("09:40 stage lock remained held after the one-shot execution")
    lock.release()
    result = {
        "stage_id": stage_id,
        "execution_mode": "CONTROLLED_HK_ONLY_SCOPED_RECOVERY",
        "initial_receipt_sha256": sha256(receipt_raw),
        "final_receipt_sha256": sha256(after_run_raw),
        "preserved_prior_receipt_sha256": sha_file(preserved_receipt_path),
        "attempt_reservation": {
            "attempt_before": receipt.get("node_attempt_count"),
            "attempt_reserved": reservation.get("node_attempt_count"),
            "attempt_after": final_receipt.get("node_attempt_count"),
            "max_attempts": max_attempts,
            "execution_markets": final_receipt.get("execution_markets"),
            "retry_exhausted": final_receipt.get("retry_exhausted"),
        },
        "dispatch_status": final_receipt.get("status"),
        "node_outcome": final_receipt.get("node_outcome"),
        "execution_pending": final_receipt.get("execution_pending"),
        "due_status": decision.status,
        "attempt_before": receipt.get("node_attempt_count"),
        "attempt_after": final_receipt.get("node_attempt_count"),
        "max_attempts": max_attempts,
        "saved_observation": cache_provenance,
        "hk_raw_store_readback": {
            "status": hk_verified.get("status"),
            "row_count": hk_verified.get("row_count"),
            "requested_rows": hk_verified.get("requested_rows"),
            "artifact_sha256": hk_verified.get("artifact_sha256"),
            "manifest_sha256": hk_verified.get("manifest_sha256"),
            "temporal_cutoff_safe": hk_manifest.get("temporal_cutoff_safe"),
            "cannot_confirm": hk_verified.get("cannot_confirm"),
        },
        "hk_selection_store_readback": {
            "selection_status": hk_selection.get("selection_status"),
            "selected_rows": hk_selection.get("selected_rows"),
            "rows_read_back": len(hk_selection_rows),
            "raw_artifact_sha256": hk_selection.get("raw_artifact_sha256"),
            "algorithm_id": hk_selection.get("algorithm_id"),
            "algorithm_sha256": hk_selection.get("algorithm_sha256"),
            "source_evidence": hk_selection.get("source_evidence"),
            "action_levels": sorted({str(row.get("action_level") or "") for row in hk_selection_rows}),
            "all_rows_no_buy": all(str(row.get("action_level") or "").upper() == "NO_BUY" for row in hk_selection_rows),
            "observation_verification": "UNVERIFIED",
        },
        "cache_adapter_calls": cache_adapter_calls["cache_adapter_calls"],
        "reentry_result": reentry,
        "reentry_rejected_without_mutation": True,
        "lock_released": True,
        "live_or_isolated_mode": "LIVE_ONE_SHOT" if consume_live else "ISOLATED_DRY_RUN",
        "a_lane_preserved": True,
        "isolated_store_seed": seed,
        "formal_command": None if consume_live else controlled_0940_command(
            app_root,
            config_path,
            candidate_domain,
            Path(str(base_config["python_path"])),
            output_root.parent / f"{output_root.name}_formal_0940",
        ),
        "formal_command_available": not consume_live,
        "formal_command_status": "REVIEW_AND_PARENT_EXECUTION_PENDING" if not consume_live else "ALREADY_CONSUMED",
        "formal_command_note": "Execute only after independent PASS and parent release. The normal dispatcher remains guarded; this exact one-shot consumes one original attempt under SlotLock.",
    }
    write_json(stage_root / "STAGE_DRY_RUN.json" if not consume_live else stage_root / "STAGE_CONTROLLED_EXECUTION.json", result)
    if not consume_live and sha_file(live_receipt_path) != EXPECTED_RECEIPTS[stage_id]:
        raise AssertionError("09:40 isolated attempt changed live receipt")
    return result


def run_0945_isolated(node, base_config: Mapping[str, Any], app_root: Path, config_path: Path, output_root: Path) -> dict[str, Any]:
    stage_id = "STAGE_0945_1030"
    live_receipt_path, receipt_raw, receipt = input_receipt(base_config, stage_id)
    config = deepcopy(dict(base_config))
    stage_root = output_root / stage_id
    stage_root.mkdir(parents=True, exist_ok=False)
    seed = seed_isolated_stage(config, stage_root, stage_id, ("A_SHARE", "HK_CONNECT"), receipt_raw)
    runner = node._build_runner(config)
    if runner.config.selection_builders is not None:
        raise AssertionError("production selection builders were replaced in the isolated runner")

    # Any missing raw would call this deny-only adapter and fail closed. The
    # two pinned original raw artifacts must satisfy the runner without a new
    # provider call.
    provider_calls = {"count": 0}
    def forbidden_provider(plan, market):
        provider_calls["count"] += 1
        raise RuntimeError(f"offline preparation forbids provider calls: {market}")
    runner.collectors = {"A_SHARE": forbidden_provider, "HK_CONNECT": forbidden_provider}

    stage_dispatch = node._dispatch_stage
    evaluated_at = datetime.now(SHANGHAI)
    if not node._retry_is_due(receipt, evaluated_at, retry_backoff_seconds=float(base_config.get("node_retry_backoff_seconds", 60))):
        raise ValueError("original 09:45 backoff is not due")

    # Save exact source receipt bytes in the isolated attempt evidence tree
    # before the dispatcher takes its own lock and consumes attempt 2.
    preserved = Path(str(config["receipt_root"])) / TRADE_DATE / stage_id / "attempt_evidence" / f"preserved-{sha256(receipt_raw)}" / "PRIOR_RECEIPT.json"
    preserved.parent.mkdir(parents=True, exist_ok=False)
    preserved.write_bytes(receipt_raw)
    dispatch = stage_dispatch(config, TRADE_DATE, stage_id, evaluated_at, mode="RECOVERY", runner=runner)
    isolated_receipt_path = Path(str(config["receipt_root"])) / TRADE_DATE / stage_id / "receipt.json"
    final_raw = isolated_receipt_path.read_bytes()
    final_receipt = json.loads(final_raw)
    if preserved.read_bytes() != receipt_raw or sha_file(preserved) != EXPECTED_RECEIPTS[stage_id]:
        raise AssertionError("09:45 exact prior receipt archive mismatch")
    if provider_calls["count"] != 0:
        raise AssertionError("09:45 isolated replay made or attempted a provider call")
    if final_receipt.get("node_attempt_count") != 2:
        raise AssertionError(f"09:45 original attempt counter did not advance once: {final_receipt.get('node_attempt_count')}")
    if any(final_receipt.get(flag) is not False for flag in SAFETY_FALSE):
        raise AssertionError("09:45 receipt changed safety flags")

    raw_module = importlib.import_module("stage_center.raw_store")
    raw_store = raw_module.RawStore(Path(str(config["raw_root"])))
    raw_readback = {}
    for market in ("A_SHARE", "HK_CONNECT"):
        verified = raw_store.verify_latest(TRADE_DATE, stage_id, market)["verified"]
        expected_artifact, expected_manifest_file = EXPECTED_RAW[(stage_id, market)]
        manifest_path = safe_relative(Path(str(config["raw_root"])), verified.get("manifest_relative"))
        manifest = read_json(manifest_path)
        manifest_file_sha256 = sha_file(manifest_path)
        if verified.get("artifact_sha256") != expected_artifact or manifest_file_sha256 != expected_manifest_file:
            raise AssertionError(f"09:45 raw-store readback changed existing source: {market}")
        raw_readback[market] = {
            "run_id": verified.get("run_id"),
            "status": verified.get("status"),
            "row_count": verified.get("row_count"),
            "requested_rows": verified.get("requested_rows"),
            "missing_symbols": verified.get("missing_symbols"),
            "artifact_sha256": verified.get("artifact_sha256"),
            "manifest_sha256": verified.get("manifest_sha256"),
            "manifest_file_sha256": manifest_file_sha256,
            "temporal_cutoff_safe": manifest.get("temporal_cutoff_safe"),
            "cannot_confirm": verified.get("cannot_confirm"),
            "source_evidence": verified.get("source_evidence"),
        }
    hk_raw = raw_readback["HK_CONNECT"]
    if hk_raw.get("row_count") != 99 or hk_raw.get("requested_rows") != 100 or hk_raw.get("missing_symbols") != ["HK.02632"] or hk_raw.get("temporal_cutoff_safe") is not False:
        raise AssertionError("09:45 HK raw partial/temporal contract changed")
    if raw_readback["A_SHARE"].get("row_count") != 361 or raw_readback["A_SHARE"].get("requested_rows") != 371:
        raise AssertionError("09:45 A raw partial coverage changed")

    selection_module = importlib.import_module("stage_center.selection")
    selection_store = selection_module.SelectionStore(Path(str(config["selection_root"])))
    selections = {}
    for market in ("A_SHARE", "HK_CONNECT"):
        envelope = selection_store.read_verified(TRADE_DATE, stage_id, market)
        entries = read_json(Path(str(config["selection_root"])) / "selection_latest.json").get("entries", {})
        entry = entries.get(f"{TRADE_DATE}/{stage_id}/{market}") or {}
        if envelope.get("raw_artifact_sha256") != EXPECTED_RAW[(stage_id, market)][0]:
            raise AssertionError(f"09:45 {market} SelectionStore does not bind pinned raw artifact")
        rows = list(envelope.get("rows") or [])
        action_levels = sorted({str(row.get("action_level") or "") for row in rows})
        if any(level.upper() in {"BUY", "STRONG_BUY", "BUY_NOW"} for level in action_levels):
            raise AssertionError(f"09:45 {market} selection contains a BUY action")
        selections[market] = {
            "selection_status": envelope.get("selection_status"),
            "selected_rows": envelope.get("selected_rows"),
            "rows_read_back": len(rows),
            "run_id": envelope.get("run_id"),
            "artifact_sha256": entry.get("artifact_sha256"),
            "raw_artifact_sha256": envelope.get("raw_artifact_sha256"),
            "algorithm_id": envelope.get("algorithm_id"),
            "algorithm_sha256": envelope.get("algorithm_sha256"),
            "cannot_confirm": envelope.get("cannot_confirm"),
            "action_levels": action_levels,
            "all_rows_no_buy": all(str(row.get("action_level") or "").upper() not in {"BUY", "STRONG_BUY", "BUY_NOW"} for row in rows),
            "source_evidence": envelope.get("source_evidence"),
        }

    # Re-enter via the same dispatcher after the isolated result. A settled
    # partial is not run again; a transient result is held by its original
    # retry backoff. In either case, the receipt and store pointers must remain
    # byte-identical across this second call.
    raw_pointer_before_reentry = sha_file(Path(str(config["raw_root"])) / "latest.json")
    selection_pointer_before_reentry = sha_file(Path(str(config["selection_root"])) / "selection_latest.json")
    receipt_sha_before_reentry = sha256(final_raw)
    if node._stage_settled(final_receipt):
        reentry = stage_dispatch(config, TRADE_DATE, stage_id, evaluated_at, mode="RECOVERY", runner=runner)
        expected_reentry_statuses = {"SKIPPED_ALREADY_SETTLED"}
    elif final_receipt.get("node_outcome") == "TRANSIENT":
        reentry = stage_dispatch(config, TRADE_DATE, stage_id, evaluated_at, mode="RECOVERY", runner=runner)
        expected_reentry_statuses = {"SKIPPED_RETRY_BACKOFF", "SKIPPED_RETRY_EXHAUSTED"}
    else:
        reentry = {"status": "NOT_RUN_UNCLASSIFIED_FINAL_OUTCOME", "write_performed": False}
        expected_reentry_statuses = {"NOT_RUN_UNCLASSIFIED_FINAL_OUTCOME"}
    if reentry.get("status") not in expected_reentry_statuses:
        raise AssertionError(f"09:45 dispatcher did not reject immediate re-entry: {reentry.get('status')}")
    if (
        sha_file(isolated_receipt_path) != receipt_sha_before_reentry
        or sha_file(Path(str(config["raw_root"])) / "latest.json") != raw_pointer_before_reentry
        or sha_file(Path(str(config["selection_root"])) / "selection_latest.json") != selection_pointer_before_reentry
    ):
        raise AssertionError("09:45 re-entry changed isolated receipt or store pointers")

    from stage_center.runner import SlotLock, _slot_lock_path
    lock_path = _slot_lock_path(runner.config, TRADE_DATE, stage_id)
    lock = SlotLock(lock_path)
    if not lock.acquire():
        raise AssertionError("09:45 stage lock remained held after dispatcher return")
    lock.release()
    attempt_root = Path(str(config["receipt_root"])) / TRADE_DATE / stage_id / "attempt_evidence"
    attempt_files = sorted(str(path.relative_to(attempt_root)) for path in attempt_root.rglob("*.json") if path.is_file())

    result = {
        "stage_id": stage_id,
        "dispatch_status": dispatch.get("status"),
        "final_status": final_receipt.get("status"),
        "node_outcome": final_receipt.get("node_outcome"),
        "due_status": final_receipt.get("due_status"),
        "attempt_before": receipt.get("node_attempt_count"),
        "attempt_after": final_receipt.get("node_attempt_count"),
        "max_attempts": int(base_config.get("node_max_attempts", 0)),
        "retry_exhausted": final_receipt.get("retry_exhausted"),
        "execution_pending": final_receipt.get("execution_pending"),
        "initial_receipt_sha256": sha256(receipt_raw),
        "preserved_prior_receipt_sha256": sha_file(preserved),
        "final_receipt_sha256": sha256(final_raw),
        "attempt_evidence_files": attempt_files,
        "raw_store_readback": raw_readback,
        "selection_store_readback": selections,
        "provider_calls": provider_calls["count"],
        "reentry_result": reentry,
        "reentry_rejected_without_mutation": reentry.get("status") in {"SKIPPED_ALREADY_SETTLED", "SKIPPED_RETRY_BACKOFF", "SKIPPED_RETRY_EXHAUSTED"},
        "lock_path_isolated": str(lock_path).startswith(str(stage_root.resolve())),
        "formal_command": command_for(stage_id, app_root, config_path, Path(str(base_config["python_path"]))),
        "formal_command_available": True,
        "formal_command_status": "REVIEW_AND_PARENT_EXECUTION_PENDING",
        "formal_command_note": "Only run after the parent accepts this isolated receipt and Reviewer verdict; it consumes the current original attempt budget.",
        "safety": {"research_only": True, **SAFETY_FALSE},
    }
    write_json(stage_root / "STAGE_DRY_RUN.json", result)
    if sha_file(live_receipt_path) != EXPECTED_RECEIPTS[stage_id]:
        raise AssertionError("09:45 isolated attempt changed live receipt")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("dry-run", "consume-0940"), default="dry-run")
    parser.add_argument("--app-root", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--candidate-domain", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()

    app_root = args.app_root.resolve(strict=True)
    config_path = args.config.resolve(strict=True)
    candidate_domain = args.candidate_domain.resolve(strict=True)
    output_root = args.output_root.resolve()
    consume_live = args.mode == "consume-0940"
    try:
        output_root.relative_to(EVIDENCE_ROOT.resolve())
    except ValueError as error:
        raise ValueError("--output-root must remain under the frozen recovery evidence root") from error
    if output_root.exists():
        raise FileExistsError(f"one-shot output already exists: {output_root}")
    identity = app_identity(app_root, config_path, candidate_domain)
    base_config = read_json(config_path)
    stages_to_validate = ("STAGE_0940_0945",) if consume_live else tuple(EXPECTED_RECEIPTS)
    for stage_id in stages_to_validate:
        input_receipt(base_config, stage_id)
    configured_python = Path(str(base_config.get("python_path", ""))).resolve(strict=True)
    running_python = Path(sys.executable).resolve(strict=True)
    if running_python != configured_python:
        raise ValueError(
            f"run with the release-configured interpreter: expected {configured_python}, got {running_python}"
        )
    for rel, expected in EXPECTED_TDX_FILES.items():
        if sha_file(TDX_ROOT / rel) != expected:
            raise ValueError(f"pinned TDX input changed before run: {rel}")

    protected_before = snapshot_protected_a(base_config)
    output_root.mkdir(parents=True, exist_ok=False)
    write_json(output_root / "INPUTS_PINNED.json", {
        "mode": args.mode,
        "trade_date": TRADE_DATE,
        "runtime_identity": identity,
        "initial_receipt_sha256": EXPECTED_RECEIPTS,
        "tdx_0940_cache": cache_rows_0940()[1],
        "raw_0945_expected_sha256": {f"{stage}/{market}": values for (stage, market), values in EXPECTED_RAW.items() if stage == "STAGE_0945_1030"},
        "protected_a_before": protected_before,
        "safety": {"research_only": True, **SAFETY_FALSE},
        "provider_calls": 0,
        "formal_execution": consume_live,
    })

    node = importlib.import_module("ops.run_stage_center_nodes")
    loaded_config = node._load_config(config_path)
    if loaded_config != base_config:
        # The loader adds only validated numeric defaults; pin the stage budget
        # and retain all original explicit paths before overriding store roots.
        for key in ("node_max_attempts", "node_retry_backoff_seconds", "node_max_nodes_per_run"):
            if loaded_config.get(key) != base_config.get(key):
                raise ValueError(f"loaded config changed frozen setting {key}")
        base_config = loaded_config

    cache = cache_rows_0940()
    stage_0940 = run_0940_isolated(
        node, base_config, app_root, config_path, output_root, protected_before, cache,
        candidate_domain, consume_live=consume_live,
    )
    stage_0945 = None if consume_live else run_0945_isolated(node, base_config, app_root, config_path, output_root)
    protected_after = snapshot_protected_a(base_config)
    if consume_live:
        a_preserved = protected_a_equal(protected_before, protected_after, ignore_receipt_stage="STAGE_0940_0945")
        if not a_preserved:
            raise AssertionError("controlled 09:40 HK-only execution changed protected A artifacts or sibling receipts")
        receipt_0940_after = sha_file(Path(str(base_config["receipt_root"])) / TRADE_DATE / "STAGE_0940_0945" / "receipt.json")
        if receipt_0940_after == EXPECTED_RECEIPTS["STAGE_0940_0945"]:
            raise AssertionError("controlled 09:40 execution did not consume the pinned original attempt")
    else:
        a_preserved = protected_after == protected_before
        if not a_preserved:
            raise AssertionError("isolated preparation changed live A, receipt, or stage-store pointers")

    live_receipt_changes = {}
    for stage_id in stages_to_validate:
        current = sha_file(Path(str(base_config["receipt_root"])) / TRADE_DATE / stage_id / "receipt.json")
        expected = EXPECTED_RECEIPTS[stage_id]
        live_receipt_changes[stage_id] = {"before_sha256": expected, "after_sha256": current, "unchanged": current == expected}
    if not consume_live:
        live_receipt_changes = {
            stage_id: {
                "before_sha256": EXPECTED_RECEIPTS[stage_id],
                "after_sha256": sha_file(Path(str(base_config["receipt_root"])) / TRADE_DATE / stage_id / "receipt.json"),
                "unchanged": sha_file(Path(str(base_config["receipt_root"])) / TRADE_DATE / stage_id / "receipt.json") == EXPECTED_RECEIPTS[stage_id],
            }
            for stage_id in EXPECTED_RECEIPTS
        }
        if any(not entry["unchanged"] for entry in live_receipt_changes.values()):
            raise AssertionError("isolated dry-run changed a live stage receipt")

    formal_performed = bool(consume_live and stage_0940.get("dispatch_status") == "PARTIAL_WITH_ROWS")

    final = {
        "schema_version": "v4.remaining_stage_recovery_preparation.v1",
        "status": "CONTROLLED_ONE_SHOT_EXECUTED" if consume_live else "PREPARED_ISOLATED_ONLY",
        "mode": args.mode,
        "trade_date": TRADE_DATE,
        "runtime_identity": identity,
        "stage_0940": stage_0940,
        **({"stage_0945": stage_0945} if stage_0945 is not None else {}),
        "protected_a_after": protected_after,
        "protected_a_unchanged": a_preserved,
        "live_receipt_changes": live_receipt_changes,
        "candidate_warning_projection": identity["warning_projection_validation"],
        "formal_execution_performed": formal_performed,
        "provider_calls": 0,
        "safety": {"research_only": True, **SAFETY_FALSE},
        "caveats": [
            "09:40 cached 100-code rows were captured after the stage cutoff; RawStore persists them only as PARTIAL_WITH_ROWS with temporal_cutoff_safe=false, while the original selection builder returns ten unverified NO_BUY observation rows.",
            "The normal dispatcher still rejects 09:40 settled-partial re-entry. The controlled one-shot uses scoped_recovery_runner under SlotLock, archives the exact receipt SHA, reserves attempt 2/3, and preserves A; it does not change the automatic guard.",
            "09:45 reuses only the already-published 361/371 A and 99/100 HK raw artifacts; HK.02632 is missing and the existing raw manifest remains temporal_cutoff_safe=false.",
            "The independent warning-projection PASS covers archive projection and tamper behavior; downstream stage-selection warning presentation remains CANNOT_CONFIRM/out of scope.",
        ],
    }
    write_json(output_root / "RECOVERY_PREPARED.json", final)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"status": "PREPARATION_FAILED", "error": f"{type(error).__name__}: {error}"}, ensure_ascii=False), file=sys.stderr)
        raise
