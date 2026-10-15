#!/usr/bin/env python3
"""Verify the completed HK morning lanes and prepare a gated resume for only 09:40/09:45."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


WRITER_ROOT = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_HK_ACCEPTANCE_RECOVERY_20261015/writer"
)
ONE_SHOT_PATH = WRITER_ROOT / "run_hk_morning_cached_recovery_once.py"
FAILURE_RECEIPT_PATH = WRITER_ROOT / "actual_run_receipt_20261015.json"
PREFLIGHT_RECEIPT_PATH = WRITER_ROOT / "resume_preflight_canary_receipt_20261015.json"
RESUME_RECEIPT_PATH = WRITER_ROOT / "resume_run_receipt_20261015.json"
FAILURE_RECEIPT_SHA256 = "e7ddf0c19612d17126f2dcd625d0052dc5bc665275c0c5aec3b8a85a2b23c454"

RESUME_STAGES = ("STAGE_0935_0940", "STAGE_0940_0945")
PREVIOUS_STAGE_PINS: dict[str, dict[str, Any]] = {
    "STAGE_0925": {
        "backfill_run_id": "c98cce79aa634665a69fe1146d8e335a",
        "raw_run_id": "20261015-hk_connect_auction_reference_stage_0925-d7a4bf9c19b88543",
        "raw_artifact_sha256": "f2bb1806be78233ecd1587c27abdf36e83266808bd6b4bd702417d331c20b72c",
        "runner_receipt_sha256": "a5af1a56beb99d095834629f8a28b9469b71f56f3ed629d37a6fc40a899443f1",
        "selection_run_id": "run-60b2c780c3904e57f664d58b",
        "selection_artifact_sha256": "db8b5f64f92f4edb63c74f64ebee93fd958fdaa6581386521ba6b4b7303a2193",
        "selection_manifest_sha256": "8de0e8d1f549840fb9dc4a19ecb72ab3271b210cb98cde46e034ec7d0619d115",
        "selection_receipt_sha256": "a45ee5edf12411bd5ec7a1e4b659d91b4f85bc2fa32839d966da74690baad242",
    },
    "STAGE_0930_0935": {
        "backfill_run_id": "e48db9ca382944b3994e6f31efb4f329",
        "raw_run_id": "20261015-hk_connect_1min_stage_0930_0935-b16b4f8e769cc72a",
        "raw_artifact_sha256": "c55c488e617946a92252c0d5e193b0a83ed26e6b4b096df9446d92f4b0c3b987",
        "runner_receipt_sha256": "38f73ed8ff6d2322f473c597074f6034d8bfb141c19a80e131d902c799e917dd",
        "selection_run_id": "run-9a03b73fd509be2260c8981c",
        "selection_artifact_sha256": "0f8cfcc988b87156f10a9006ee0f186264627aad2dc3aa46bab778a4469d7815",
        "selection_manifest_sha256": "0b08f59f5b1b7b7799cedf5eda387b10c9d463b7c7d42131d1eb0eb9c7163a90",
        "selection_receipt_sha256": "4eeda7ff4734271a7229c4ed60903194915f2c0ae4a17347fba6d532fd2c2559",
    },
}


def _load_one_shot():
    spec = importlib.util.spec_from_file_location("hk_morning_one_shot", ONE_SHOT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the frozen one-shot candidate")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ONE = _load_one_shot()
TRADE_DATE = ONE.TRADE_DATE
RESUME_RECEIPT_SCHEMA = "hk_morning_cached_recovery_resume.v1"
PREFLIGHT_RECEIPT_SCHEMA = "hk_morning_cached_recovery_resume_preflight.v1"


def _json_file(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"expected a regular JSON file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected a JSON object: {path}")
    return value


def _assert_failure_receipt(config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    observed_receipt_sha = ONE._file_sha256(FAILURE_RECEIPT_PATH)
    if observed_receipt_sha != FAILURE_RECEIPT_SHA256:
        raise RuntimeError("original failed receipt SHA changed; refusing to resume")
    failed = _json_file(FAILURE_RECEIPT_PATH)
    if (
        failed.get("schema_version") != "hk_morning_cached_recovery_actual_run.v1"
        or failed.get("status") != "FAILED_STOP"
        or failed.get("trade_date") != TRADE_DATE
        or failed.get("failed_stage") != "STAGE_0930_0935"
        or tuple(failed.get("target_stages") or ()) != tuple(ONE.STAGES)
        or failed.get("write_performed") is not True
        or failed.get("protected_live_unchanged") is not True
        or any(failed.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
    ):
        raise RuntimeError("original failed receipt no longer matches the pinned fail-stop boundary")

    source_shas = ONE._check_source_shas()
    input_shas = ONE._check_input_files(config)
    if failed.get("source_sha256") != source_shas:
        raise RuntimeError("candidate source SHAs differ from the original two-stage run")
    if failed.get("input_sha256") != input_shas:
        raise RuntimeError("frozen input SHAs differ from the original two-stage run")
    if failed.get("active_stage_config_sha256") != ONE.ACTIVE_STAGE_CONFIG_SHA256:
        raise RuntimeError("active StageCenter config identity differs from the original run")

    stage_results = failed.get("stage_results")
    if not isinstance(stage_results, list) or len(stage_results) != 2:
        raise RuntimeError("original failed receipt does not contain exactly the two completed stages")
    first, second = stage_results
    if (
        first.get("stage_id") != "STAGE_0925"
        or first.get("backfill_run_id") != PREVIOUS_STAGE_PINS["STAGE_0925"]["backfill_run_id"]
        or first.get("selection_run_id") != PREVIOUS_STAGE_PINS["STAGE_0925"]["selection_run_id"]
        or first.get("raw_artifact_sha256") != PREVIOUS_STAGE_PINS["STAGE_0925"]["raw_artifact_sha256"]
        or first.get("runner_receipt_sha256") != PREVIOUS_STAGE_PINS["STAGE_0925"]["runner_receipt_sha256"]
        or second.get("stage_id") != "STAGE_0930_0935"
        or second.get("backfill_run_id") != PREVIOUS_STAGE_PINS["STAGE_0930_0935"]["backfill_run_id"]
    ):
        raise RuntimeError("original receipt does not bind the exact two prior backfill runs")

    for kind, root_key in (
        ("raw", "raw_root"),
        ("selection", "selection_root"),
        ("receipts", "receipt_root"),
    ):
        diff = (failed.get("backfill_write_diff") or {}).get(kind) or {}
        if diff.get("changed") or diff.get("deleted") or diff.get("unexpected_added"):
            raise RuntimeError(f"original {kind} write diff is no longer clean")
        allowed_ids = {pin["backfill_run_id"] for pin in PREVIOUS_STAGE_PINS.values()}
        for path_text in diff.get("added") or ():
            relative = Path(path_text).relative_to(Path(config[root_key]))
            if len(relative.parts) < 2 or relative.parts[0] != "backfill" or relative.parts[1] not in allowed_ids:
                raise RuntimeError(f"original {kind} write escaped the two pinned namespaces: {path_text}")
    return failed, source_shas


def _verify_completed_stage(config: dict[str, Any], stage_id: str) -> dict[str, Any]:
    from stage_center.raw_store import RawStore
    from stage_center.selection import SelectionStore

    pin = PREVIOUS_STAGE_PINS[stage_id]
    raw_root = Path(config["raw_root"]) / "backfill" / pin["backfill_run_id"]
    selection_root = Path(config["selection_root"]) / "backfill" / pin["backfill_run_id"]
    receipt_root = Path(config["receipt_root"]) / "backfill" / pin["backfill_run_id"]
    for path in (raw_root, selection_root, receipt_root):
        ONE._assert_no_symlink_path(path)
        if not path.is_dir():
            raise RuntimeError(f"pinned prior-stage namespace is missing: {path}")

    raw_role = RawStore._role(stage_id, "HK_CONNECT")
    raw_stage_root = raw_root / "runs" / TRADE_DATE / raw_role
    ONE._assert_no_symlink_path(raw_stage_root)
    raw_runs = [path for path in raw_stage_root.iterdir() if path.is_dir()]
    if len(raw_runs) != 1 or raw_runs[0].name != pin["raw_run_id"]:
        raise RuntimeError(f"{stage_id} raw run identity differs from its pin")
    raw_manifest_path = raw_runs[0] / "manifest.json"
    raw_artifact_path = raw_runs[0] / "artifact.csv"
    raw_manifest = _json_file(raw_manifest_path)
    raw_artifact_sha = ONE._file_sha256(raw_artifact_path)
    if (
        raw_artifact_sha != pin["raw_artifact_sha256"]
        or raw_manifest.get("artifact_sha256") != pin["raw_artifact_sha256"]
        or raw_manifest.get("run_id") != pin["raw_run_id"]
        or raw_manifest.get("stage_id") != stage_id
        or raw_manifest.get("trade_date") != TRADE_DATE
    ):
        raise RuntimeError(f"{stage_id} raw artifact or manifest does not match the fixed pin")
    raw_verified = RawStore(raw_root).verify_latest(TRADE_DATE, stage_id, "HK_CONNECT")["verified"]
    if raw_verified.get("artifact_sha256") != pin["raw_artifact_sha256"]:
        raise RuntimeError(f"{stage_id} RawStore readback failed its fixed artifact SHA")

    selection_role = SelectionStore._role(stage_id, "HK_CONNECT")
    selection_run_root = (
        selection_root
        / "selection_runs"
        / TRADE_DATE
        / selection_role
        / pin["selection_run_id"]
    )
    ONE._assert_no_symlink_path(selection_run_root)
    selection_manifest_path = selection_run_root / "manifest.json"
    selection_receipt_path = selection_run_root / "receipt.json"
    selection_artifact_path = selection_run_root / "artifact.csv"
    selection_manifest = _json_file(selection_manifest_path)
    selection_manifest_sha = ONE._file_sha256(selection_manifest_path)
    selection_receipt_sha = ONE._file_sha256(selection_receipt_path)
    selection_artifact_sha = ONE._file_sha256(selection_artifact_path)
    if (
        selection_manifest_sha != pin["selection_manifest_sha256"]
        or selection_receipt_sha != pin["selection_receipt_sha256"]
        or selection_artifact_sha != pin["selection_artifact_sha256"]
        or selection_manifest.get("run_id") != pin["selection_run_id"]
        or selection_manifest.get("stage_id") != stage_id
        or selection_manifest.get("trade_date") != TRADE_DATE
        or selection_manifest.get("raw_artifact_sha256") != pin["raw_artifact_sha256"]
        or selection_manifest.get("artifact_sha256") != pin["selection_artifact_sha256"]
    ):
        raise RuntimeError(f"{stage_id} selection artifact/manifest/receipt differs from its fixed pin")
    envelope = SelectionStore(selection_root).read_verified(TRADE_DATE, stage_id, "HK_CONNECT")
    rows = list(envelope.get("rows") or ())
    if (
        envelope.get("run_id") != pin["selection_run_id"]
        or envelope.get("raw_artifact_sha256") != pin["raw_artifact_sha256"]
        or envelope.get("market") != "HK_CONNECT"
        or envelope.get("stage_id") != stage_id
        or len(rows) != 10
        or any(row.get("action_level") != "NO_BUY" for row in rows)
        or any(envelope.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
    ):
        raise RuntimeError(f"{stage_id} selection readback fails identity, row, or safety checks")
    if stage_id == "STAGE_0925":
        evidence = set(envelope.get("source_evidence") or ())
        if (
            "second_filter_csv_sha256=" + ONE.SECOND_FILTER_CSV_SHA256 not in evidence
            or "hk_d1_json_sha256=" + ONE.D1_FILE_SHA256 not in evidence
        ):
            raise RuntimeError("09:25 selection readback no longer binds the frozen D1/filter inputs")
    else:
        ONE._assert_afterfact_marker_contract(envelope, stage_id)

    runner_receipt_path = receipt_root / TRADE_DATE / stage_id / "receipt.json"
    runner_receipt_sha = ONE._file_sha256(runner_receipt_path)
    runner_receipt = _json_file(runner_receipt_path)
    markets = runner_receipt.get("markets")
    market = markets.get("HK_CONNECT") if isinstance(markets, dict) else None
    expected_namespace = {
        "raw_root": str(raw_root),
        "selection_root": str(selection_root),
        "receipt_root": str(receipt_root),
    }
    if (
        runner_receipt_sha != pin["runner_receipt_sha256"]
        or runner_receipt.get("trade_date") != TRADE_DATE
        or runner_receipt.get("stage_id") != stage_id
        or runner_receipt.get("status") != "PARTIAL_WITH_ROWS"
        or runner_receipt.get("due_status") != "HISTORICAL_BACKFILL"
        or runner_receipt.get("mode") != "BACKFILL"
        or runner_receipt.get("backfill_run_id") != pin["backfill_run_id"]
        or runner_receipt.get("namespace") != expected_namespace
        or runner_receipt.get("latest_updated") is not False
        or runner_receipt.get("current_updated") is not False
        or runner_receipt.get("write_performed") is not True
        or any(runner_receipt.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
        or not isinstance(markets, dict)
        or set(markets) != {"HK_CONNECT"}
        or not isinstance(market, dict)
        or market.get("run_id") != pin["selection_run_id"]
        or market.get("raw_artifact_sha256") != pin["raw_artifact_sha256"]
        or market.get("selection_status") != "PARTIAL_WITH_ROWS"
    ):
        raise RuntimeError(f"{stage_id} immutable runner receipt fails the fixed identity/safety pin")

    return {
        "stage_id": stage_id,
        "backfill_run_id": pin["backfill_run_id"],
        "raw_run_id": pin["raw_run_id"],
        "raw_artifact_sha256": raw_artifact_sha,
        "runner_receipt_sha256": runner_receipt_sha,
        "selection_run_id": pin["selection_run_id"],
        "selection_artifact_sha256": selection_artifact_sha,
        "selection_manifest_sha256": selection_manifest_sha,
        "selection_receipt_sha256": selection_receipt_sha,
        "selected_rows": len(rows),
        "runner_status": runner_receipt.get("status"),
        "selection_status": envelope.get("selection_status"),
        "formal_eligible": envelope.get("formal_eligible"),
        "selection_mode": envelope.get("selection_mode"),
        "observation_status": envelope.get("observation_status"),
        "cannot_confirm": list(envelope.get("cannot_confirm") or ()),
        "production_allowed": envelope.get("production_allowed"),
        "buy_gate_updated": envelope.get("buy_gate_updated"),
        "orders_sent": envelope.get("orders_sent"),
    }


def _resume_targets_empty(config: dict[str, Any]) -> None:
    from stage_center.raw_store import RawStore
    from stage_center.selection import SelectionStore

    roots = {
        "raw": Path(config["raw_root"]) / "backfill",
        "selection": Path(config["selection_root"]) / "backfill",
        "receipts": Path(config["receipt_root"]) / "backfill",
    }
    for root in roots.values():
        ONE._assert_no_symlink_path(root)
        if root.exists() and not root.is_dir():
            raise RuntimeError(f"backfill root is not a directory: {root}")
        if root.is_dir():
            for path in root.rglob("*"):
                if path.is_symlink():
                    raise RuntimeError(f"backfill root contains a symlink: {path}")

    collisions: list[str] = []
    for stage_id in RESUME_STAGES:
        raw_role = RawStore._role(stage_id, "HK_CONNECT")
        selection_role = SelectionStore._role(stage_id, "HK_CONNECT")
        for run_root in sorted(roots["raw"].iterdir()) if roots["raw"].is_dir() else ():
            if (run_root / "runs" / TRADE_DATE / raw_role).exists():
                collisions.append(str(run_root / "runs" / TRADE_DATE / raw_role))
            if (run_root / "bundle_runs" / TRADE_DATE / stage_id).exists():
                collisions.append(str(run_root / "bundle_runs" / TRADE_DATE / stage_id))
        for run_root in sorted(roots["selection"].iterdir()) if roots["selection"].is_dir() else ():
            if (run_root / "selection_runs" / TRADE_DATE / selection_role).exists():
                collisions.append(str(run_root / "selection_runs" / TRADE_DATE / selection_role))
        for run_root in sorted(roots["receipts"].iterdir()) if roots["receipts"].is_dir() else ():
            if (run_root / TRADE_DATE / stage_id / "receipt.json").exists():
                collisions.append(str(run_root / TRADE_DATE / stage_id / "receipt.json"))
    if collisions:
        raise RuntimeError(f"resume target stages already exist; refusing duplicate runs: {collisions}")


def _load_and_verify_prior() -> tuple[dict[str, Any], dict[str, str], dict[str, Any], list[dict[str, Any]]]:
    if str(ONE.PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(ONE.PROJECT_ROOT))
    source_shas = ONE._check_source_shas()
    config, _kwargs = ONE._load_active_config()
    input_shas = ONE._check_input_files(config)
    failed, _source_shas = _assert_failure_receipt(config)
    completed = [_verify_completed_stage(config, stage) for stage in ("STAGE_0925", "STAGE_0930_0935")]

    protected_before = ONE._protected_live_inventory(config)
    protected_failed_before = failed.get("protected_live_before")
    protected_failed_after = failed.get("protected_live_after")
    if protected_failed_before != protected_failed_after or protected_before != protected_failed_after:
        raise RuntimeError("protected live inventory differs from the immutable failed-run receipt")
    current_backfill = {
        "raw": ONE._backfill_date_inventory(Path(config["raw_root"]), "raw"),
        "selection": ONE._backfill_date_inventory(Path(config["selection_root"]), "selection"),
        "receipts": ONE._backfill_date_inventory(Path(config["receipt_root"]), "receipts"),
    }
    if current_backfill != failed.get("backfill_date_after"):
        raise RuntimeError("current backfill inventory differs from the immutable failed-run receipt")
    _resume_targets_empty(config)
    return config, source_shas, {"inputs": input_shas, "protected_live": protected_before, "backfill": current_backfill}, completed


def verify_existing_only() -> dict[str, Any]:
    config, source_shas, snapshot, completed = _load_and_verify_prior()
    protected_after = ONE._protected_live_inventory(config)
    backfill_after = {
        "raw": ONE._backfill_date_inventory(Path(config["raw_root"]), "raw"),
        "selection": ONE._backfill_date_inventory(Path(config["selection_root"]), "selection"),
        "receipts": ONE._backfill_date_inventory(Path(config["receipt_root"]), "receipts"),
    }
    if protected_after != snapshot["protected_live"] or backfill_after != snapshot["backfill"]:
        raise RuntimeError("read-only resume canary changed runtime inventory during verification")
    return {
        "schema_version": PREFLIGHT_RECEIPT_SCHEMA,
        "status": "PASS",
        "trade_date": TRADE_DATE,
        "failed_receipt_sha256": FAILURE_RECEIPT_SHA256,
        "target_stages": list(RESUME_STAGES),
        "completed_stage_checks": completed,
        "input_sha256": snapshot["inputs"],
        "source_sha256": source_shas,
        "active_stage_config_sha256": ONE.ACTIVE_STAGE_CONFIG_SHA256,
        "protected_live_inventory_sha256": ONE._sha256_json(snapshot["protected_live"]),
        "backfill_inventory_sha256": {
            kind: ONE._sha256_json(value) for kind, value in snapshot["backfill"].items()
        },
        "resume_targets_empty": True,
        "runner_ticks": 0,
        "write_performed": False,
        "runtime_state_modified": False,
        "receipt_captured_at": ONE._now_shanghai().isoformat(),
    }


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise RuntimeError(f"resume evidence receipt already exists; refusing overwrite: {path}")
    ONE._write_receipt_exclusive(path, payload)


def execute_resume_once() -> dict[str, Any]:
    writer_root = ONE._assert_no_symlink_path(WRITER_ROOT)
    runtime_state_root = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/state").resolve(strict=False)
    if writer_root.resolve(strict=False) == runtime_state_root or runtime_state_root in writer_root.resolve(strict=False).parents:
        raise RuntimeError("resume receipt directory is redirected into active runtime state")
    if RESUME_RECEIPT_PATH.exists() or RESUME_RECEIPT_PATH.is_symlink():
        raise RuntimeError(f"resume receipt already exists; refusing another live run: {RESUME_RECEIPT_PATH}")
    started_at = ONE._now_shanghai()
    if started_at.strftime("%Y%m%d") != TRADE_DATE:
        raise RuntimeError("actual Asia/Shanghai execution date is not 20261015")

    receipt: dict[str, Any] = {
        "schema_version": RESUME_RECEIPT_SCHEMA,
        "status": "IN_PROGRESS",
        "trade_date": TRADE_DATE,
        "resumed_from_receipt": str(FAILURE_RECEIPT_PATH),
        "resumed_from_receipt_sha256": FAILURE_RECEIPT_SHA256,
        "completed_prior_stage_pins": PREVIOUS_STAGE_PINS,
        "target_stages": list(RESUME_STAGES),
        "clock_timezone": "Asia/Shanghai",
        "run_started_at": started_at.isoformat(),
        "stage_results": [],
        "input_sha256": {},
        "source_sha256": {},
        "protected_live_before": None,
        "protected_live_after": None,
        "backfill_date_before": None,
        "backfill_date_after": None,
        "write_performed": False,
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    _write_receipt(RESUME_RECEIPT_PATH, receipt)

    old_capture_env = os.environ.get(ONE.CAPTURE_ENV)
    config: dict[str, Any] | None = None
    protected_before: dict[str, Any] | None = None
    backfill_before: dict[str, dict[str, dict[str, Any]]] | None = None
    allowed_run_ids: set[str] = set()
    current_stage: str | None = None
    runner_tick_started = False
    error_text: str | None = None
    try:
        os.environ[ONE.CAPTURE_ENV] = str(ONE.FUTU_CAPTURE)
        config, source_shas, prior_snapshot, completed = _load_and_verify_prior()
        receipt["source_sha256"] = source_shas
        receipt["input_sha256"] = prior_snapshot["inputs"]
        receipt["active_stage_release"] = str(ONE.ACTIVE_STAGE_APP)
        receipt["active_stage_config_sha256"] = ONE.ACTIVE_STAGE_CONFIG_SHA256
        receipt["prior_stage_readback"] = completed
        receipt["prior_protected_live_inventory_sha256"] = ONE._sha256_json(prior_snapshot["protected_live"])
        receipt["prior_backfill_inventory_sha256"] = {
            kind: ONE._sha256_json(value) for kind, value in prior_snapshot["backfill"].items()
        }

        from stage_center.runner import StageCenterRunner, build_production_config

        runner_config = build_production_config(
            **{key: Path(config[key]) for key in ONE.CONFIG_KEYS if config.get(key) is not None}
        )
        _binding, _candidate, prepared = ONE._prepare_sources(
            config, runner_config, stage_ids=RESUME_STAGES
        )
        receipt["preflight_sources"] = {
            stage: {
                "source_id": item["source"].source_id,
                "status": item["source"].status,
                "row_count": item["source_rows"],
                "source_evidence": list(item["source"].source_evidence),
                "observation_contract_present": item["observation_contract"] is not None,
            }
            for stage, item in prepared.items()
        }
        _resume_targets_empty(config)
        protected_before = ONE._protected_live_inventory(config)
        backfill_before = {
            "raw": ONE._backfill_date_inventory(Path(config["raw_root"]), "raw"),
            "selection": ONE._backfill_date_inventory(Path(config["selection_root"]), "selection"),
            "receipts": ONE._backfill_date_inventory(Path(config["receipt_root"]), "receipts"),
        }
        if protected_before != prior_snapshot["protected_live"] or backfill_before != prior_snapshot["backfill"]:
            raise RuntimeError("runtime inventory changed after the exact prior-stage resume preflight")
        receipt["protected_live_before"] = protected_before
        receipt["backfill_date_before"] = backfill_before
        runner = StageCenterRunner(runner_config)

        for stage_id in RESUME_STAGES:
            current_stage = stage_id
            stage_evaluated_at = ONE._now_shanghai()
            if stage_evaluated_at.strftime("%Y%m%d") != TRADE_DATE:
                raise RuntimeError("Asia/Shanghai date crossed during resume; stopping before next stage")
            receipt["current_stage"] = stage_id
            receipt["current_stage_evaluated_at"] = stage_evaluated_at.isoformat()
            receipt["input_sha256"] = ONE._check_input_files(config)
            runner_tick_started = True
            result = runner.tick(
                TRADE_DATE,
                stage_evaluated_at,
                stage_id=stage_id,
                historical_backfill=True,
                historical_markets=("HK_CONNECT",),
                historical_observation_contract=prepared[stage_id]["observation_contract"],
                _skip_precapture=True,
            )
            result_summary = {
                key: result.get(key)
                for key in (
                    "trade_date",
                    "stage_id",
                    "status",
                    "due_status",
                    "mode",
                    "backfill_run_id",
                    "latest_updated",
                    "current_updated",
                    "write_performed",
                )
            }
            run_id = str(result.get("backfill_run_id") or "")
            if run_id:
                allowed_run_ids.add(run_id)
            receipt["stage_results"].append(
                {"stage_id": stage_id, "runner_evaluated_at": stage_evaluated_at.isoformat(), **result_summary}
            )
            if result.get("write_performed") is True:
                receipt["write_performed"] = True
            receipt["stage_results"][-1].update(
                ONE._verify_stage_result(
                    result=result,
                    stage_id=stage_id,
                    evaluated_at=stage_evaluated_at,
                    prepared=prepared[stage_id],
                    config=config,
                )
            )
            if ONE._protected_live_inventory(config) != protected_before:
                raise RuntimeError(f"protected live state changed after {stage_id}")
            current_backfill = {
                "raw": ONE._backfill_date_inventory(Path(config["raw_root"]), "raw"),
                "selection": ONE._backfill_date_inventory(Path(config["selection_root"]), "selection"),
                "receipts": ONE._backfill_date_inventory(Path(config["receipt_root"]), "receipts"),
            }
            for kind, root_key in (("raw", "raw_root"), ("selection", "selection_root"), ("receipts", "receipt_root")):
                diff = ONE._compare_inventory(
                    backfill_before[kind],
                    current_backfill[kind],
                    allowed_backfill_run_ids=allowed_run_ids,
                    backfill_root=Path(config[root_key]),
                )
                if diff["changed"] or diff["deleted"] or diff["unexpected_added"]:
                    raise RuntimeError(f"unexpected {kind} writes after {stage_id}: {diff}")

        receipt["status"] = "PASS"
        receipt["completed_at"] = ONE._now_shanghai().isoformat()
    except Exception as error:
        error_text = f"{type(error).__name__}: {error}"
        receipt["status"] = "FAILED_STOP" if runner_tick_started else "PRECHECK_FAILED"
        receipt["failed_stage"] = current_stage
        receipt["error"] = error_text
        receipt["completed_at"] = ONE._now_shanghai().isoformat()
    finally:
        if old_capture_env is None:
            os.environ.pop(ONE.CAPTURE_ENV, None)
        else:
            os.environ[ONE.CAPTURE_ENV] = old_capture_env
        if config is not None:
            try:
                receipt["protected_live_after"] = ONE._protected_live_inventory(config)
                receipt["protected_live_unchanged"] = (
                    protected_before is not None and receipt["protected_live_after"] == protected_before
                )
                after_backfill = {
                    "raw": ONE._backfill_date_inventory(Path(config["raw_root"]), "raw"),
                    "selection": ONE._backfill_date_inventory(Path(config["selection_root"]), "selection"),
                    "receipts": ONE._backfill_date_inventory(Path(config["receipt_root"]), "receipts"),
                }
                receipt["backfill_date_after"] = after_backfill
                if backfill_before is not None:
                    final_diffs = {}
                    for kind, root_key in (("raw", "raw_root"), ("selection", "selection_root"), ("receipts", "receipt_root")):
                        final_diffs[kind] = ONE._compare_inventory(
                            backfill_before[kind],
                            after_backfill[kind],
                            allowed_backfill_run_ids=allowed_run_ids,
                            backfill_root=Path(config[root_key]),
                        )
                    receipt["backfill_write_diff"] = final_diffs
                    if any(diff["changed"] or diff["deleted"] or diff["unexpected_added"] for diff in final_diffs.values()):
                        receipt["status"] = "POSTCHECK_FAILED"
                        receipt["error"] = "unexpected or non-new resume backfill namespace mutation"
                if receipt.get("protected_live_unchanged") is False:
                    receipt["status"] = "POSTCHECK_FAILED"
                    receipt["error"] = "protected original/A/10:30 state changed during resume"
            except Exception as post_error:
                receipt["status"] = "POSTCHECK_FAILED"
                receipt["postcheck_error"] = f"{type(post_error).__name__}: {post_error}"
        receipt["receipt_captured_at"] = ONE._now_shanghai().isoformat()
        receipt["failed_stage"] = receipt.get("failed_stage") or current_stage
        receipt["execution_error"] = error_text
        receipt["write_performed"] = bool(receipt.get("write_performed"))
        ONE._atomic_update_receipt(RESUME_RECEIPT_PATH, receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--verify-existing-only", action="store_true", help="read-only verification; writes only a writer-side evidence receipt")
    group.add_argument(
        "--execute-after-reviewer-pass-and-parent-authorization",
        action="store_true",
        help="required gate for the exact remaining 09:40 and 09:45 StageCenter backfills",
    )
    args = parser.parse_args(argv)
    if args.verify_existing_only:
        if PREFLIGHT_RECEIPT_PATH.exists() or PREFLIGHT_RECEIPT_PATH.is_symlink():
            parser.error(f"preflight canary receipt already exists: {PREFLIGHT_RECEIPT_PATH}")
        try:
            receipt = verify_existing_only()
            _write_receipt(PREFLIGHT_RECEIPT_PATH, receipt)
        except Exception as error:
            print(json.dumps({"status": "PRECHECK_FAILED", "error_type": type(error).__name__, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
            return 2
        print(json.dumps({"status": receipt["status"], "receipt": str(PREFLIGHT_RECEIPT_PATH)}, ensure_ascii=False, sort_keys=True))
        return 0
    try:
        receipt = execute_resume_once()
    except Exception as error:
        print(json.dumps({"status": "NOT_STARTED", "error_type": type(error).__name__, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"status": receipt["status"], "receipt": str(RESUME_RECEIPT_PATH)}, ensure_ascii=False, sort_keys=True))
    return 0 if receipt.get("status") == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
