#!/usr/bin/env python3
"""One-shot live HK morning recovery; execution is gated and must be authorized."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path("/Users/lexi/Desktop/学习/v4_app")
WRITER_ROOT = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_HK_ACCEPTANCE_RECOVERY_20261015/writer"
)
TRADE_DATE = "20261015"
STAGES = (
    "STAGE_0925",
    "STAGE_0930_0935",
    "STAGE_0935_0940",
    "STAGE_0940_0945",
)
MINUTE_STAGES = frozenset(STAGES[1:])
SHANGHAI = ZoneInfo("Asia/Shanghai")
CAPTURE_ENV = "V4_HK_MORNING_CACHED_CAPTURE"

ACTIVE_STAGE_APP = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/"
    "node-minute-stage-20261014-r1/app"
)
ACTIVE_STAGE_CONFIG = ACTIVE_STAGE_APP / "stage_center_tick_config.json"
ACTIVE_STAGE_CONFIG_SHA256 = "dd02f230420d62709571f1542d60eaf95d8a1ee7af2f4088ba5f761c1df43246"

D1_PATH = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/"
    "preselection_pools/20261015/hkconnect_d1_top100.json"
)
D1_FILE_SHA256 = "66225363e4dd1b9da4f316d75a8dcc5f249bc0968128c646e9632a1a8b1b1c67"
D1_ARTIFACT_SHA256 = "e25b4a1c3a35632ceeb4edaaea2b128ae47c98020fceae58fd8a395ad801f685"
D1_RUN_ID = "20261015-hk-connect-d1-top100-0-2-1d08535262fd"
SECOND_FILTER_CSV = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data/"
    "opening_second_filter/20261015/hkconnect_0920_auction_second_filter_20261015.csv"
)
SECOND_FILTER_CSV_SHA256 = "c3daa0dc36c9e4319cd87c4639ec0fb37cf3c4ccb7d44f9e3c2ea99616fdf31f"
SECOND_FILTER_ACCEPTANCE = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data/"
    "opening_second_filter/20261015/hkconnect_0920_auction_second_filter_20261015.acceptance.json"
)
SECOND_FILTER_ACCEPTANCE_SHA256 = "7cdf5abde712094a6a32fd7a5a8a56effd4403951b98e6c9bbd5b2d84eaa2d6e"
FUTU_CAPTURE = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/raw/"
    ".futu_minute_captures/20261015/STAGE_0945_1030/"
    "45fdc5d16d1dec2e7f087dfdb802f3c5b92e67d4e380aa6c49ddea15881ab455.json"
)
FUTU_CAPTURE_SHA256 = "45fdc5d16d1dec2e7f087dfdb802f3c5b92e67d4e380aa6c49ddea15881ab455"

EXPECTED_SOURCE_SHAS = {
    "stage_center/acquisition.py": "51da5204448ed75197735281e578edeb7becb8281903bbac68070e42cc06523f",
    "stage_center/live_collectors.py": "b5bb9332565c4fa861d2a825b113a254755172e4b8e629703d05a947ab66527e",
    "stage_center/selection.py": "48c12de4fb10892d28bdbe58ef9e30e9dcf56aeee506a86a1428f4cdd0a74d26",
    "stage_center/runner.py": "72ffbfa62daefe44158882c5f90e0c657741d3de0c85e18bad8d9f0b7aa5691e",
    "stage_center/_runner_parts/slot_execution.py": "6a0728117ff11478bab3a46eb2fb9ec3586863937392c64bfa504bc36c6bcefd",
    "stage_center/_live_collectors_parts/hk_minute.py": "2ec08e3fea63f31a05b447ce6a947f47d5e391d4dcc47b60220d6f7f49944f32",
    "stage_center/_live_collectors_parts/selection_builder_registry.py": "5109145e773b3c3cb1d2bef17d4430d48f73efaa2479ac14b9d16adbf19a9942",
    "stage_center/raw_store.py": "4cefe12c2f2ec8dc43a444c17e84b03f79fcd76607702fc5333ab5a956c7ec96",
}

RECEIPT_PATH = WRITER_ROOT / "actual_run_receipt_20261015.json"
CONFIG_KEYS = (
    "candidate_acquisition_root",
    "raw_root",
    "selection_root",
    "receipt_root",
    "v3_formal_root",
    "v3_research_root",
    "v4_research_data_root",
    "v4_morning_news_root",
    "hk_d1_root",
    "preselection_source_root",
    "hk_second_filter_root",
    "hk_full_universe_root",
    "a_auction_root",
    "hk_auction_root",
    "hk_stage_replay_root",
    "a_research_panel_receipt_root",
    "shared_data_root",
    "python_path",
)


def _now_shanghai() -> datetime:
    return datetime.now(SHANGHAI)


def _file_sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"expected a regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _assert_no_symlink_path(path: Path) -> Path:
    """Resolve no components; reject a symlink at any level before file access."""
    absolute = path.absolute()
    cursor = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        cursor = cursor / part
        if cursor.is_symlink():
            raise RuntimeError(f"refusing symlink path component: {cursor}")
    return absolute


def _record_tree(path: Path, entries: dict[str, dict[str, Any]]) -> None:
    path = _assert_no_symlink_path(path)
    key = str(path)
    if not path.exists():
        entries[key] = {"kind": "absent"}
        return
    if path.is_file():
        entries[key] = {
            "kind": "file",
            "size": path.stat().st_size,
            "sha256": _file_sha256(path),
        }
        return
    entries[key] = {"kind": "directory"}
    for base, dirs, files in os.walk(path, followlinks=False):
        base_path = Path(base)
        for name in sorted(list(dirs)):
            child = base_path / name
            child_key = str(child)
            if child.is_symlink():
                raise RuntimeError(f"refusing to traverse symlink while inventorying: {child}")
            else:
                entries[child_key] = {"kind": "directory"}
        for name in sorted(files):
            child = base_path / name
            child_key = str(child)
            if child.is_symlink():
                raise RuntimeError(f"refusing to inventory symlink file: {child}")
            elif child.is_file():
                entries[child_key] = {
                    "kind": "file",
                    "size": child.stat().st_size,
                    "sha256": _file_sha256(child),
                }


def _record_tree_under_root(
    root: Path,
    path: Path,
    entries: dict[str, dict[str, Any]],
) -> None:
    """Check each path component before walking so a symlink parent is never followed."""
    root = _assert_no_symlink_path(root)
    path = _assert_no_symlink_path(path)
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise RuntimeError(f"inventory path escaped its root: {path}") from error
    cursor = root
    if cursor.is_symlink():
        raise RuntimeError(f"inventory root is a symlink: {cursor}")
    for index, part in enumerate(relative.parts):
        cursor = cursor / part
        if cursor.is_symlink():
            raise RuntimeError(f"refusing to traverse symlink parent during inventory: {cursor}")
        if not cursor.exists():
            entries[str(path)] = {"kind": "absent"}
            return
        if index < len(relative.parts) - 1 and not cursor.is_dir():
            raise RuntimeError(f"inventory parent is not a directory: {cursor}")
    resolved_root = root.resolve(strict=False)
    resolved_path = path.resolve(strict=False)
    if resolved_root != root or not resolved_path.is_relative_to(resolved_root):
        raise RuntimeError(f"inventory realpath escaped its root: {path}")
    _record_tree(path, entries)


def _assert_new_path_inside_backfill_namespace(
    path: Path,
    *,
    backfill_root: Path,
    run_id: str,
) -> None:
    """Require lexical and resolved containment under one new run namespace."""
    root = backfill_root.absolute()
    namespace = root / "backfill" / run_id
    candidate = path.absolute()
    try:
        relative = candidate.relative_to(namespace)
    except ValueError as error:
        raise RuntimeError(f"new inventory path is outside its run namespace: {path}") from error
    cursor = root
    if cursor.is_symlink():
        raise RuntimeError(f"backfill root is a symlink: {cursor}")
    for part in ("backfill", run_id, *relative.parts):
        cursor = cursor / part
        if cursor.is_symlink():
            raise RuntimeError(f"new backfill path contains a symlink: {cursor}")
    resolved_root = root.resolve(strict=False)
    resolved_namespace = namespace.resolve(strict=False)
    resolved_candidate = candidate.resolve(strict=False)
    if (
        resolved_root != root
        or resolved_namespace != namespace
        or not resolved_candidate.is_relative_to(resolved_namespace)
    ):
        raise RuntimeError(f"new inventory path realpath escaped its run namespace: {path}")


def _protected_live_inventory(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = Path(config["raw_root"])
    selection = Path(config["selection_root"])
    receipts = Path(config["receipt_root"])
    protected = (
        raw / "runs" / TRADE_DATE,
        raw / "bundle_runs" / TRADE_DATE,
        selection / "selection_runs" / TRADE_DATE,
        receipts / TRADE_DATE,
        raw / "latest.json",
        raw / "bundle_latest.json",
        selection / "selection_latest.json",
    )
    entries: dict[str, dict[str, Any]] = {}
    for path in protected:
        _record_tree(path, entries)
    symlinks = sorted(
        path for path, value in entries.items() if value.get("kind") == "symlink"
    )
    if symlinks:
        raise RuntimeError(f"protected live state contains symlinks: {symlinks[:10]}")
    return dict(sorted(entries.items()))


def _backfill_date_inventory(root: Path, kind: str) -> dict[str, dict[str, Any]]:
    """Inventory only the target date's backfill data and per-run pointers."""
    backfill = _assert_no_symlink_path(root / "backfill")
    entries: dict[str, dict[str, Any]] = {}
    if not backfill.exists():
        return {str(backfill): {"kind": "absent"}}
    if backfill.is_symlink() or not backfill.is_dir():
        raise RuntimeError(f"backfill root is not a regular directory: {backfill}")
    entries[str(backfill)] = {"kind": "directory"}
    for run_root in sorted(backfill.iterdir()):
        if run_root.is_symlink():
            raise RuntimeError(f"backfill run directory is a symlink: {run_root}")
        if not run_root.is_dir():
            entries[str(run_root)] = {
                "kind": "file",
                "size": run_root.stat().st_size,
                "sha256": _file_sha256(run_root),
            }
            continue
        entries[str(run_root)] = {"kind": "directory"}
        if kind == "raw":
            relative_roots = (
                run_root / "latest.json",
                run_root / "bundle_latest.json",
                run_root / "runs" / TRADE_DATE,
                run_root / "bundle_runs" / TRADE_DATE,
            )
        elif kind == "selection":
            relative_roots = (
                run_root / "selection_latest.json",
                run_root / "selection_runs" / TRADE_DATE,
            )
        elif kind == "receipts":
            relative_roots = (run_root / TRADE_DATE,)
        else:
            raise ValueError(f"unknown backfill inventory kind: {kind}")
        for path in relative_roots:
            _record_tree_under_root(run_root, path, entries)
    return dict(sorted(entries.items()))


def _compare_inventory(
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
    *,
    allowed_backfill_run_ids: set[str] | None = None,
    backfill_root: Path | None = None,
) -> dict[str, list[str]]:
    allowed_backfill_run_ids = allowed_backfill_run_ids or set()
    before_keys, after_keys = set(before), set(after)
    changed = sorted(key for key in before_keys & after_keys if before[key] != after[key])
    deleted = sorted(before_keys - after_keys)
    added = sorted(after_keys - before_keys)
    unexpected_added: list[str] = []
    if backfill_root is not None:
        allowed_root_transition = str(backfill_root / "backfill")
        if (
            allowed_root_transition in changed
            and before[allowed_root_transition].get("kind") == "absent"
            and after[allowed_root_transition].get("kind") == "directory"
        ):
            changed.remove(allowed_root_transition)
        for key in added:
            relative = Path(key).relative_to(backfill_root)
            parts = relative.parts
            if not parts or parts[0] != "backfill":
                unexpected_added.append(key)
            elif len(parts) > 1 and parts[1] not in allowed_backfill_run_ids:
                unexpected_added.append(key)
            elif len(parts) > 1:
                _assert_new_path_inside_backfill_namespace(
                    Path(key),
                    backfill_root=backfill_root,
                    run_id=parts[1],
                )
    return {
        "changed": changed,
        "deleted": deleted,
        "added": added,
        "unexpected_added": unexpected_added,
    }


def _assert_target_backfill_empty(config: dict[str, Any]) -> None:
    from stage_center.raw_store import RawStore
    from stage_center.selection import SelectionStore

    raw_root = Path(config["raw_root"]) / "backfill"
    selection_root = Path(config["selection_root"]) / "backfill"
    receipt_root = Path(config["receipt_root"]) / "backfill"
    collisions: list[str] = []
    for backfill_root in (raw_root, selection_root, receipt_root):
        if backfill_root.is_symlink():
            raise RuntimeError(f"backfill root symlink is forbidden: {backfill_root}")
        if backfill_root.exists():
            if not backfill_root.is_dir():
                raise RuntimeError(f"backfill root is not a directory: {backfill_root}")
            nested_symlinks = sorted(
                str(path) for path in backfill_root.rglob("*") if path.is_symlink()
            )
            if nested_symlinks:
                raise RuntimeError(
                    f"backfill root contains symlinks: {nested_symlinks[:10]}"
                )
    for stage_id in STAGES:
        raw_role = RawStore._role(stage_id, "HK_CONNECT")
        selection_role = SelectionStore._role(stage_id, "HK_CONNECT")
        for run_root in sorted(raw_root.iterdir()) if raw_root.is_dir() else ():
            if (run_root / "runs" / TRADE_DATE / raw_role).exists():
                collisions.append(str(run_root / "runs" / TRADE_DATE / raw_role))
            if (run_root / "bundle_runs" / TRADE_DATE / stage_id).exists():
                collisions.append(str(run_root / "bundle_runs" / TRADE_DATE / stage_id))
        for run_root in sorted(selection_root.iterdir()) if selection_root.is_dir() else ():
            if (run_root / "selection_runs" / TRADE_DATE / selection_role).exists():
                collisions.append(str(run_root / "selection_runs" / TRADE_DATE / selection_role))
        for run_root in sorted(receipt_root.iterdir()) if receipt_root.is_dir() else ():
            if (run_root / TRADE_DATE / stage_id / "receipt.json").exists():
                collisions.append(str(run_root / TRADE_DATE / stage_id / "receipt.json"))
    if collisions:
        raise RuntimeError(f"target backfill lanes already exist; refusing duplicate run: {collisions}")


def _check_source_shas() -> dict[str, str]:
    actual: dict[str, str] = {}
    for relative, expected in EXPECTED_SOURCE_SHAS.items():
        path = PROJECT_ROOT / relative
        observed = _file_sha256(path)
        actual[relative] = observed
        if observed != expected:
            raise RuntimeError(f"candidate source SHA changed for {relative}")
    return actual


def _load_active_config() -> tuple[dict[str, Any], dict[str, Any]]:
    config_sha = _file_sha256(ACTIVE_STAGE_CONFIG)
    if config_sha != ACTIVE_STAGE_CONFIG_SHA256:
        raise RuntimeError("active stage config SHA differs from the reviewed bridge")
    config = json.loads(ACTIVE_STAGE_CONFIG.read_text(encoding="utf-8"))
    safety = config.get("safety")
    if not isinstance(safety, dict) or any(
        safety.get(key) is not False
        for key in ("production_allowed", "buy_gate_updated", "orders_sent")
    ):
        raise RuntimeError("active stage config safety flags are not all false")
    required = (
        "candidate_acquisition_root",
        "raw_root",
        "selection_root",
        "receipt_root",
        "hk_d1_root",
        "preselection_source_root",
        "hk_second_filter_root",
        "hk_auction_root",
        "shared_data_root",
        "python_path",
    )
    if any(not config.get(key) for key in required):
        raise RuntimeError("active stage config is missing a required runner bridge root")
    runtime_stage = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage")
    if any(
        Path(config[key]).expanduser().resolve(strict=False) != runtime_stage / child
        for key, child in (
            ("raw_root", "raw"),
            ("selection_root", "selection"),
            ("receipt_root", "receipts"),
        )
    ):
        raise RuntimeError("active stage config points outside the expected StageCenter state roots")
    expected_source_roots = {
        "preselection_source_root": D1_PATH.parents[2],
        "hk_second_filter_root": SECOND_FILTER_CSV.parents[1],
        "hk_auction_root": SECOND_FILTER_CSV.parents[1],
    }
    for key, expected_root in expected_source_roots.items():
        if Path(config[key]).expanduser().resolve(strict=False) != expected_root.resolve(strict=False):
            raise RuntimeError(f"active stage config changed its frozen input root: {key}")
    config["_config_sha256"] = config_sha
    kwargs = {
        key: Path(config[key])
        for key in CONFIG_KEYS
        if config.get(key) is not None
    }
    return config, kwargs


def _check_input_files(config: dict[str, Any]) -> dict[str, str]:
    expected = {
        str(D1_PATH): D1_FILE_SHA256,
        str(SECOND_FILTER_CSV): SECOND_FILTER_CSV_SHA256,
        str(SECOND_FILTER_ACCEPTANCE): SECOND_FILTER_ACCEPTANCE_SHA256,
        str(FUTU_CAPTURE): FUTU_CAPTURE_SHA256,
    }
    actual: dict[str, str] = {}
    for path_text, expected_sha in expected.items():
        observed = _file_sha256(Path(path_text))
        actual[path_text] = observed
        if observed != expected_sha:
            raise RuntimeError(f"frozen input SHA changed: {path_text}")

    d1 = json.loads(D1_PATH.read_text(encoding="utf-8"))
    if (
        d1.get("trade_date") != TRADE_DATE
        or d1.get("target_date") != TRADE_DATE
        or d1.get("signal_date") != "20261014"
        or d1.get("source_run_id") != D1_RUN_ID
        or d1.get("source_sha256") != D1_ARTIFACT_SHA256
        or len(d1.get("rows") or ()) != 100
        or any(d1.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
    ):
        raise RuntimeError("canonical D1 artifact identity or safety contract changed")

    acceptance = json.loads(SECOND_FILTER_ACCEPTANCE.read_text(encoding="utf-8"))
    if (
        acceptance.get("target_date") != TRADE_DATE
        or acceptance.get("signal_date") != "20261014"
        or acceptance.get("status") != "AUCTION_SECOND_FILTER_READY"
        or acceptance.get("csv_sha256") != SECOND_FILTER_CSV_SHA256
        or acceptance.get("d1_artifact_sha256") != D1_ARTIFACT_SHA256
        or acceptance.get("d1_run_id") != D1_RUN_ID
        or acceptance.get("reference_only") is not True
        or acceptance.get("action_level") != "NO_BUY"
        or acceptance.get("publication_time") != "09:20:00"
        or acceptance.get("signal_cutoff") != "09:19:59"
        or acceptance.get("row_count") != 20
        or acceptance.get("required_row_count") != 20
        or any(acceptance.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
    ):
        raise RuntimeError("09:20 acceptance artifact identity or safety contract changed")
    return actual


def _prepare_sources(
    config: dict[str, Any],
    runner_config: Any,
    *,
    stage_ids: tuple[str, ...] | None = None,
) -> tuple[Any, Any, dict[str, dict[str, Any]]]:
    from stage_center.acquisition import build_plan
    from stage_center._live_collectors_parts.hk_minute import _hk_morning_cached_d1_provenance
    from stage_center.live_collectors import collect_hk_auction, collect_hk_minute
    from stage_center.runner import _build_hk_stage_binding, _candidate_from_hk_binding

    binding = _build_hk_stage_binding(
        runner_config.hk_d1_root,
        TRADE_DATE,
        preselection_source_root=runner_config.preselection_source_root,
    )
    if (
        binding.sha256 != D1_FILE_SHA256
        or binding.trade_date != TRADE_DATE
        or binding.market != "HK_CONNECT"
        or len(binding.codes) != 100
        or len(set(binding.codes)) != 100
        or _hk_morning_cached_d1_provenance(binding, binding.codes) is None
    ):
        raise RuntimeError("production HK D1 binding differs from the frozen Top100")
    candidate = _candidate_from_hk_binding(
        root=runner_config.candidate_acquisition_root,
        trade_date=TRADE_DATE,
        binding=binding,
    )
    shared_root = runner_config.shared_data_root
    requested_stages = STAGES if stage_ids is None else tuple(stage_ids)
    if not requested_stages or not set(requested_stages).issubset(STAGES):
        raise RuntimeError("source preflight stages must be a non-empty subset of the frozen sequence")
    prepared: dict[str, dict[str, Any]] = {}
    for stage_id in requested_stages:
        plan = build_plan(
            runner_config.candidate_acquisition_root,
            TRADE_DATE,
            stage_id,
            candidate=candidate,
            universe_bindings={"HK_CONNECT": binding},
            historical_backfill=True,
        )
        if stage_id == "STAGE_0925":
            source = collect_hk_auction(
                plan,
                codes=plan.codes_for("HK_CONNECT"),
                python_path=runner_config.python_path,
                shared_root=shared_root,
                auction_root=runner_config.hk_auction_root,
                replay_provider=None,
            )
            if (
                source.status != "READY"
                or len(source.rows) != 20
                or f"second_filter_csv_sha256={SECOND_FILTER_CSV_SHA256}" not in source.source_evidence
            ):
                raise RuntimeError(f"{stage_id} exact 09:20 collector preflight failed: {source.cannot_confirm}")
            token = None
        else:
            source = collect_hk_minute(
                plan,
                codes=plan.codes_for("HK_CONNECT"),
                python_path=runner_config.python_path,
                shared_root=shared_root,
                snapshot_root=None,
                replay_provider=None,
            )
            if source.status != "PARTIAL_WITH_ROWS" or len(source.rows) != 100:
                raise RuntimeError(f"{stage_id} cached Futu collector preflight failed: {source.cannot_confirm}")
            tokens = [
                item.split("=", 1)[1]
                for item in source.source_evidence
                if item.startswith("stage_center_observation_mode=")
            ]
            if len(tokens) != 1:
                raise RuntimeError(f"{stage_id} has no unique manifest-bound after-fact token")
            token = tokens[0]
        prepared[stage_id] = {
            "plan": plan,
            "source": source,
            "observation_contract": token,
            "source_rows": len(source.rows),
        }
    return binding, candidate, prepared


def _assert_afterfact_marker_contract(envelope: dict[str, Any], stage_id: str) -> None:
    """Validate the published StageCenter schema fields, keeping each marker in its own field."""
    required_cannot_confirm = {
        "HISTORICAL_CAPTURE_AFTER_TARGET_CUTOFF_NOT_PIT_SAFE",
        "HISTORICAL_FORMAL_STAGE_ELIGIBILITY_CANNOT_CONFIRM",
        "HISTORICAL_NATURAL_TIME_CAPTURE_CANNOT_CONFIRM",
        "HK_HISTORICAL_ORDERBOOK_UNAVAILABLE",
    }
    cannot_confirm = set(envelope.get("cannot_confirm") or ())
    evidence = set(envelope.get("source_evidence") or ())
    required_source_evidence = {
        "formal_pit=false",
        "formal_stage_eligibility=CANNOT_CONFIRM",
        "natural_time_capture=CANNOT_CONFIRM",
        "historical_capture_after_target_cutoff=true",
        "futu_afterfact_pit_safe=false",
        "futu_afterfact_orderbook_unavailable=true",
        f"futu_afterfact_stage_id={stage_id}",
        f"futu_capture_sha256={FUTU_CAPTURE_SHA256}",
    }
    missing_uncertainty = sorted(required_cannot_confirm - cannot_confirm)
    missing_evidence = sorted(required_source_evidence - evidence)
    if (
        envelope.get("formal_eligible") is not False
        or envelope.get("formal_stage_eligibility") != "CANNOT_CONFIRM"
        or envelope.get("natural_time_capture") != "CANNOT_CONFIRM"
        or envelope.get("selection_mode") != "RESEARCH_ONLY"
        or envelope.get("observation_status") != "OBSERVATION_UNVERIFIED"
        or missing_uncertainty
        or missing_evidence
    ):
        raise RuntimeError(
            f"{stage_id} after-fact marker contract failed: "
            f"missing_cannot_confirm={missing_uncertainty}, "
            f"missing_source_evidence={missing_evidence}"
        )


def _verify_stage_result(
    *,
    result: dict[str, Any],
    stage_id: str,
    evaluated_at: datetime,
    prepared: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    from stage_center.raw_store import RawStore
    from stage_center.selection import SelectionStore

    if result.get("trade_date") != TRADE_DATE or result.get("stage_id") != stage_id:
        raise RuntimeError(f"runner returned the wrong target stage: {stage_id}")
    if (
        result.get("mode") != "BACKFILL"
        or result.get("due_status") != "HISTORICAL_BACKFILL"
        or result.get("latest_updated") is not False
        or result.get("current_updated") is not False
        or result.get("write_performed") is not True
    ):
        raise RuntimeError(f"{stage_id} runner receipt is not a written historical backfill")
    if any(result.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent")):
        raise RuntimeError(f"{stage_id} runner receipt safety flags changed")
    markets = result.get("markets")
    if not isinstance(markets, dict) or set(markets) != {"HK_CONNECT"}:
        raise RuntimeError(f"{stage_id} runner result is not isolated to HK_CONNECT")
    backfill_run_id = str(result.get("backfill_run_id") or "")
    if not backfill_run_id or not backfill_run_id.isalnum():
        raise RuntimeError(f"{stage_id} runner returned an unsafe backfill run id")
    expected_roots = {
        "raw_root": str(Path(config["raw_root"]) / "backfill" / backfill_run_id),
        "selection_root": str(Path(config["selection_root"]) / "backfill" / backfill_run_id),
        "receipt_root": str(Path(config["receipt_root"]) / "backfill" / backfill_run_id),
    }
    if result.get("namespace") != expected_roots:
        raise RuntimeError(f"{stage_id} runner wrote outside its new backfill namespace")

    market = markets["HK_CONNECT"]
    market_evidence = set(market.get("source_evidence") or ())
    if stage_id == "STAGE_0925" and (
        prepared["source_rows"] != 20
        or f"second_filter_csv_sha256={SECOND_FILTER_CSV_SHA256}" not in market_evidence
    ):
        raise RuntimeError("09:25 runner evidence no longer binds the exact 09:20 reference input")
    selection_run_id = str(market.get("run_id") or "")
    if not selection_run_id:
        raise RuntimeError(f"{stage_id} selection run id is missing")
    raw_store = RawStore(Path(expected_roots["raw_root"]))
    raw_verified = raw_store.verify_latest(TRADE_DATE, stage_id, "HK_CONNECT")["verified"]
    raw_sha = str(raw_verified.get("artifact_sha256") or "")
    if raw_sha != market.get("raw_artifact_sha256"):
        raise RuntimeError(f"{stage_id} raw artifact readback mismatch")
    selection_store = SelectionStore(Path(expected_roots["selection_root"]))
    envelope = selection_store.read_verified(TRADE_DATE, stage_id, "HK_CONNECT")
    rows = list(envelope.get("rows") or ())
    if (
        envelope.get("run_id") != selection_run_id
        or envelope.get("raw_artifact_sha256") != raw_sha
        or len(rows) > 10
        or any(row.get("action_level") != "NO_BUY" for row in rows)
        or any(envelope.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
    ):
        raise RuntimeError(f"{stage_id} immutable selection readback violated its identity or safety boundary")
    if stage_id in MINUTE_STAGES:
        _assert_afterfact_marker_contract(envelope, stage_id)
    receipt_path = Path(expected_roots["receipt_root"]) / TRADE_DATE / stage_id / "receipt.json"
    receipt_sha = _file_sha256(receipt_path)
    return {
        "stage_id": stage_id,
        "trade_date": TRADE_DATE,
        "runner_evaluated_at": evaluated_at.isoformat(),
        "prepared_source_rows": prepared["source_rows"],
        "runner_status": result.get("status"),
        "selection_status": market.get("selection_status"),
        "source_status": market.get("source_status"),
        "selected_rows": len(rows),
        "selection_run_id": selection_run_id,
        "raw_artifact_sha256": raw_sha,
        "runner_receipt_path": str(receipt_path),
        "runner_receipt_sha256": receipt_sha,
        "backfill_run_id": backfill_run_id,
        "backfill_roots": expected_roots,
        "formal_eligible": envelope.get("formal_eligible"),
        "selection_mode": envelope.get("selection_mode"),
        "observation_status": envelope.get("observation_status"),
        "cannot_confirm": list(envelope.get("cannot_confirm") or ()),
        "source_evidence": list(envelope.get("source_evidence") or ()),
    }


def _atomic_update_receipt(path: Path, payload: dict[str, Any]) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _write_receipt_exclusive(path: Path, payload: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise RuntimeError(f"one-shot receipt already exists; refusing another run: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def execute_once() -> dict[str, Any]:
    resolved_writer_root = WRITER_ROOT.resolve(strict=False)
    runtime_state_root = Path(
        "/Users/lexi/Library/Application Support/com.lexi.v4.local/state"
    ).resolve(strict=False)
    if (
        resolved_writer_root != WRITER_ROOT.absolute()
        or resolved_writer_root == runtime_state_root
        or runtime_state_root in resolved_writer_root.parents
    ):
        raise RuntimeError("writer receipt directory is redirected into active runtime state")
    if RECEIPT_PATH.exists() or RECEIPT_PATH.is_symlink():
        raise RuntimeError(f"one-shot receipt already exists; refusing live execution: {RECEIPT_PATH}")
    started_at = _now_shanghai()
    receipt: dict[str, Any] = {
        "schema_version": "hk_morning_cached_recovery_actual_run.v1",
        "status": "IN_PROGRESS",
        "trade_date": TRADE_DATE,
        "target_stages": list(STAGES),
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
    _write_receipt_exclusive(RECEIPT_PATH, receipt)

    config: dict[str, Any] | None = None
    protected_before: dict[str, dict[str, Any]] | None = None
    backfill_before: dict[str, dict[str, dict[str, Any]]] | None = None
    allowed_run_ids: set[str] = set()
    old_capture_env = os.environ.get(CAPTURE_ENV)
    current_stage: str | None = None
    live_tick_started = False
    error_text: str | None = None
    try:
        if started_at.strftime("%Y%m%d") != TRADE_DATE:
            raise RuntimeError("actual Asia/Shanghai execution date is not 20261015")
        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))
        os.environ[CAPTURE_ENV] = str(FUTU_CAPTURE)
        source_shas = _check_source_shas()
        config, config_kwargs = _load_active_config()
        receipt["active_stage_release"] = str(ACTIVE_STAGE_APP)
        receipt["active_stage_config_sha256"] = config["_config_sha256"]
        receipt["source_sha256"] = source_shas
        input_shas = _check_input_files(config)
        receipt["input_sha256"] = input_shas

        from stage_center.acquisition import build_plan
        from stage_center._live_collectors_parts.hk_minute import _hk_morning_cached_d1_provenance
        from stage_center.live_collectors import collect_hk_auction, collect_hk_minute
        from stage_center.raw_store import RawStore
        from stage_center.runner import (
            StageCenterRunner,
            _build_hk_stage_binding,
            _candidate_from_hk_binding,
            build_production_config,
        )

        runner_config = build_production_config(**config_kwargs)
        binding, candidate, prepared = _prepare_sources(config, runner_config)
        d1_provenance = _hk_morning_cached_d1_provenance(binding, binding.codes)
        if d1_provenance is None:
            raise RuntimeError("verified canonical D1 producer lineage disappeared during preflight")
        receipt["d1_source_run_id"] = d1_provenance[2]
        receipt["d1_binding_sha256"] = binding.sha256
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
        _assert_target_backfill_empty(config)
        protected_before = _protected_live_inventory(config)
        backfill_before = {
            "raw": _backfill_date_inventory(Path(config["raw_root"]), "raw"),
            "selection": _backfill_date_inventory(Path(config["selection_root"]), "selection"),
            "receipts": _backfill_date_inventory(Path(config["receipt_root"]), "receipts"),
        }
        receipt["protected_live_before"] = protected_before
        receipt["backfill_date_before"] = backfill_before
        runner = StageCenterRunner(runner_config)

        for stage_id in STAGES:
            current_stage = stage_id
            stage_evaluated_at = _now_shanghai()
            if stage_evaluated_at.strftime("%Y%m%d") != TRADE_DATE:
                raise RuntimeError("Asia/Shanghai date crossed during recovery; stopping before next stage")
            receipt["current_stage"] = stage_id
            receipt["current_stage_evaluated_at"] = stage_evaluated_at.isoformat()
            receipt["input_sha256"] = _check_input_files(config)
            current_binding = _build_hk_stage_binding(
                runner_config.hk_d1_root,
                TRADE_DATE,
                preselection_source_root=runner_config.preselection_source_root,
            )
            if current_binding.sha256 != binding.sha256 or current_binding.codes != binding.codes:
                raise RuntimeError("canonical HK D1 binding changed between stages")
            live_tick_started = True
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
            stage_evidence = _verify_stage_result(
                result=result,
                stage_id=stage_id,
                evaluated_at=stage_evaluated_at,
                prepared=prepared[stage_id],
                config=config,
            )
            receipt["stage_results"][-1].update(stage_evidence)
            protected_after_stage = _protected_live_inventory(config)
            if protected_after_stage != protected_before:
                raise RuntimeError(f"protected original/A/10:30 bytes changed after {stage_id}")
            after_backfill_stage = {
                "raw": _backfill_date_inventory(Path(config["raw_root"]), "raw"),
                "selection": _backfill_date_inventory(Path(config["selection_root"]), "selection"),
                "receipts": _backfill_date_inventory(Path(config["receipt_root"]), "receipts"),
            }
            for kind, root_key in (
                ("raw", "raw_root"),
                ("selection", "selection_root"),
                ("receipts", "receipt_root"),
            ):
                diff = _compare_inventory(
                    backfill_before[kind],
                    after_backfill_stage[kind],
                    allowed_backfill_run_ids=allowed_run_ids,
                    backfill_root=Path(config[root_key]),
                )
                if diff["changed"] or diff["deleted"] or diff["unexpected_added"]:
                    raise RuntimeError(f"unexpected {kind} backfill writes after {stage_id}: {diff}")

        receipt["status"] = "PASS"
        receipt["completed_at"] = _now_shanghai().isoformat()
    except Exception as error:
        error_text = f"{type(error).__name__}: {error}"
        receipt["status"] = "FAILED_STOP" if live_tick_started else "PRECHECK_FAILED"
        receipt["failed_stage"] = current_stage
        receipt["error"] = error_text
        receipt["completed_at"] = _now_shanghai().isoformat()
    finally:
        if old_capture_env is None:
            os.environ.pop(CAPTURE_ENV, None)
        else:
            os.environ[CAPTURE_ENV] = old_capture_env
        if config is not None:
            try:
                protected_after = _protected_live_inventory(config)
                receipt["protected_live_after"] = protected_after
                receipt["protected_live_unchanged"] = (
                    protected_before is not None and protected_after == protected_before
                )
                after_backfill = {
                    "raw": _backfill_date_inventory(Path(config["raw_root"]), "raw"),
                    "selection": _backfill_date_inventory(Path(config["selection_root"]), "selection"),
                    "receipts": _backfill_date_inventory(Path(config["receipt_root"]), "receipts"),
                }
                receipt["backfill_date_after"] = after_backfill
                if backfill_before is not None:
                    final_diffs = {}
                    for kind, root_key in (
                        ("raw", "raw_root"),
                        ("selection", "selection_root"),
                        ("receipts", "receipt_root"),
                    ):
                        final_diffs[kind] = _compare_inventory(
                            backfill_before[kind],
                            after_backfill[kind],
                            allowed_backfill_run_ids=allowed_run_ids,
                            backfill_root=Path(config[root_key]),
                        )
                    receipt["backfill_write_diff"] = final_diffs
                    if any(
                        diff["changed"] or diff["deleted"] or diff["unexpected_added"]
                        for diff in final_diffs.values()
                    ):
                        receipt["status"] = "POSTCHECK_FAILED"
                        receipt["error"] = "unexpected or non-new backfill namespace mutation"
                if receipt.get("protected_live_unchanged") is False:
                    receipt["status"] = "POSTCHECK_FAILED"
                    receipt["error"] = "protected original/A/10:30 state changed"
            except Exception as post_error:
                receipt["status"] = "POSTCHECK_FAILED"
                receipt["postcheck_error"] = f"{type(post_error).__name__}: {post_error}"
        receipt["receipt_captured_at"] = _now_shanghai().isoformat()
        receipt["failed_stage"] = receipt.get("failed_stage") or current_stage
        receipt["execution_error"] = error_text
        receipt["write_performed"] = bool(receipt.get("write_performed"))
        _atomic_update_receipt(RECEIPT_PATH, receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute-after-reviewer-pass-and-parent-authorization",
        action="store_true",
        help="required guard; invoke only after independent PASS and parent authorization",
    )
    args = parser.parse_args(argv)
    if not args.execute_after_reviewer_pass_and_parent_authorization:
        parser.error("live state writes are gated until independent Reviewer PASS and parent authorization")
    try:
        receipt = execute_once()
    except Exception as error:
        print(json.dumps({"status": "NOT_STARTED", "error_type": type(error).__name__, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"status": receipt["status"], "receipt": str(RECEIPT_PATH)}, ensure_ascii=False, sort_keys=True))
    return 0 if receipt.get("status") == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
