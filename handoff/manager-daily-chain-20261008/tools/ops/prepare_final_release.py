#!/usr/bin/env python3
"""Create immutable, inactive split-root C1+D1 releases and task-local plists.

The source is the independently accepted C1 final3 package. It receives only
the exact independently reviewed D1 announcement/runtime and plan-refresh
bytes recorded below. This program refuses existing release/config outputs
and never modifies active plists, service state, manager state, or launchd.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import plistlib
import shutil
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

APP_ROOT = Path("/Users/lexi/Desktop/学习/v4_app")
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from ops.build_release_candidate import inventory_digest, inventory_tree
from ops.prepare_api_only_cutover import _replace_assignments, extract_environment, rewrite_api_only_plist
from ops.prepare_manager_daily_chain_release import _file_inventory, _stage_scheduler_plist
from infrastructure.scheduling.manager_announcement_supervisor import BINDING_SCHEMA, binding_inventory, validate_binding


TASK_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_DAILY_CHAIN_20261008/deployment/c1_plan_only")
FINAL3_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_DAILY_CHAIN_20261008/candidate/c1_repair/final3_candidate")
FINAL3_REVIEW = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_DAILY_CHAIN_20261008/review/c1_repair_independent_review_receipt.json")
FINAL3_REVIEW_SHA256 = "b9f06c7447c801e756033d0713e3ee5fe1fb3ab5994a01e0183a0cf80412293d"
D1_CLI_RESUME_REVIEW = TASK_ROOT.parent.parent / "review/d1_cli_resume_independent_receipt.json"
D1_TERMINAL_REVIEW = TASK_ROOT.parent.parent / "review/d1_terminal_runid_p2_independent_receipt.json"
D1_CANARY_REVIEW = TASK_ROOT.parent.parent / "review/d1_plan_canary_p1p2_independent_delta_review_receipt.json"
D1_ROUTER_REVIEW = TASK_ROOT.parent.parent / "review/d1_plan_canary_helper_p2_02_reuse_addendum.json"
API_RELEASE_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/manager-daily-chain-20261008-r2-api")
SCHEDULER_RELEASE_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/manager-daily-chain-20261008-r2-scheduler")
FORMAL_MANAGER_STATE = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research")
API_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist")
SCHEDULER_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist")
ACTIVE_API_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-research-calendar-all-r1-20261007-api/app")
ACTIVE_SCHEDULER_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/hk-research-calendar-all-r1-20261007-scheduler/app")
EXACT_PYTHON = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python")
CONFIG_ROOT = TASK_ROOT / "staged_config"
SOURCE_PLIST_PREIMAGE = TASK_ROOT / "preimage/runtime_plists"
EXCLUDED_NAMES = {"__pycache__", ".pytest_cache"}

# Each full-file overlay is pinned to the latest independently reviewed bytes.
# The router is intentionally different: only its reviewed workspace-refresh
# route is copied onto final3, retaining final3's reference-only import route.
REVIEWED_FULL_FILE_OVERLAYS = {
    "ops/run_manager_daily_announcement.py": {
        "source": APP_ROOT / "ops/run_manager_daily_announcement.py",
        "sha256": "bfb853fb982e0b2da1024fa942ae9dc5d67fa88a8d112f46054608641129c1ee",
        "review": D1_TERMINAL_REVIEW,
        "review_sha256": "7202ff09ba0e3227cdf0f7d0a56528fecee660636f09a370ea83edceb97f2ae1",
        "review_kind": "D1_TERM_P2_01_RUN_BOUND_CAPTURE",
    },
    "ops/manager_announcement_body_batch.py": {
        "source": APP_ROOT / "ops/manager_announcement_body_batch.py",
        "sha256": "7e37ed7e904d80c135a51bdff1aaa95aec02012eecfcfdc8a1770fa31297cbdb",
        "review": D1_CLI_RESUME_REVIEW,
        "review_sha256": "ccad01769a016f58862cf793bad29473ef019a18ad02af801f60c87444ca786f",
        "review_kind": "D1_CLI_RESUME_BODY_BATCH",
    },
    "v4/manager_research/announcement_analysis.py": {
        "source": APP_ROOT / "v4/manager_research/announcement_analysis.py",
        "sha256": "21eb0cf37bfa6f3332f17ca7825a69eaa5bf9082b33d2e3de2d293e8bc3f0685",
        "review": D1_TERMINAL_REVIEW,
        "review_sha256": "7202ff09ba0e3227cdf0f7d0a56528fecee660636f09a370ea83edceb97f2ae1",
        "review_kind": "D1_TERM_P2_01_REUSED_ANALYSIS",
    },
    "v4/manager_research/workspace_announcements.py": {
        "source": APP_ROOT / "v4/manager_research/workspace_announcements.py",
        "sha256": "60839e20df9b61be04629481752ab3072a1088d229c87980e83059b590548e50",
        "review": D1_TERMINAL_REVIEW,
        "review_sha256": "7202ff09ba0e3227cdf0f7d0a56528fecee660636f09a370ea83edceb97f2ae1",
        "review_kind": "D1_TERM_P2_01_REUSED_ANNOUNCEMENT_CONSUMER",
    },
    "infrastructure/scheduling/manager_announcement_supervisor.py": {
        "source": APP_ROOT / "infrastructure/scheduling/manager_announcement_supervisor.py",
        "sha256": "bb7f4d40a5cda21c2deb215c2f51edfaa36da9f14d79d3d01987d13b7161b8ee",
        "review": D1_CANARY_REVIEW,
        "review_sha256": "93fad57a85858f0bac9396913f38afdb989abb4e23f5f3ab06d7deca67180bb8",
        "review_kind": "D1_PLAN_CANARY_P1_P2_VALIDATOR",
    },
    "ops/run_v35_macos_scheduler_daemon.py": {
        "source": APP_ROOT / "ops/run_v35_macos_scheduler_daemon.py",
        "sha256": "7e3ead4e646a599981878e7b5eca66ecde01217de83f0f3039637a411cfa1f5c",
        "review": D1_CANARY_REVIEW,
        "review_sha256": "93fad57a85858f0bac9396913f38afdb989abb4e23f5f3ab06d7deca67180bb8",
        "review_kind": "D1_PLAN_CANARY_P1_P2_RUNTIME_READBACK",
    },
}
ROUTER_BASE_SHA256 = "a4ebb934e949b16ac8d677e2918d1abce6ebd5bcfb68555b07289b1e9b31ead1"
ROUTER_SOURCE_SHA256 = "18b718fa67bb74937f885f47e1ab587bc4bf7be3ce612b3d0731ce05eac7be8c"
ROUTER_BASE_REFRESH_SHA256 = "e8133c74aeeaeacfdfbd6c5c113dc8608d2f67aa88b26b70c31d1ef94638fdbb"
ROUTER_REVIEWED_REFRESH_SHA256 = "3a51f090c61c0840e449a7866d20689a7ff3651f5c2b8a6c15555df6da8ef4f6"
ROUTER_REVIEWED_IMPORT_SHA256 = "64921fce7b05186f1e8b2ec0592c0ca4ed0b640faa85e8e72d5bbed9b29bb36b"
ROUTER_REVIEWED_RESULT_SHA256 = "18b718fa67bb74937f885f47e1ab587bc4bf7be3ce612b3d0731ce05eac7be8c"
RUNBOOK_SOURCE = TASK_ROOT / "integration/docs/manager_daily_research.md"
RUNBOOK_SHA256 = "84763ac3e271d749154a8980b1547231e1ed496fc80d861a7ef6d30ad8482d78"
D1_REVIEW_RECEIPTS = {
    D1_CLI_RESUME_REVIEW: "ccad01769a016f58862cf793bad29473ef019a18ad02af801f60c87444ca786f",
    D1_TERMINAL_REVIEW: "7202ff09ba0e3227cdf0f7d0a56528fecee660636f09a370ea83edceb97f2ae1",
    D1_CANARY_REVIEW: "93fad57a85858f0bac9396913f38afdb989abb4e23f5f3ab06d7deca67180bb8",
    D1_ROUTER_REVIEW: "1e3bb3fa3ba59dc0b49eeb14d4d9e25c5b93389158ac3b9e5bf34454e9b088fb",
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_sha(value: Any) -> str:
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def write_exclusive(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(raw)


def _tree_without_cache(source: Path, destination: Path) -> None:
    if not source.is_dir() or source.is_symlink():
        raise ValueError("FINAL3_SOURCE_APP_NOT_EXACT_DIRECTORY")
    shutil.copytree(
        source,
        destination,
        symlinks=True,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", ".DS_Store"),
    )


def _final3_manifest(root: Path, name: str) -> tuple[Path, dict[str, Any]]:
    app = root / "release" / name
    manifest_path = app / "release-manifest.c1-final3.json"
    value = json.loads(manifest_path.read_text(encoding="utf-8"))
    claimed_sha = value.get("sha256")
    unsigned = {key: item for key, item in value.items() if key != "sha256"}
    if (value.get("schema_version") != "v4.manager_research.split_release_candidate.v1"
            or value.get("app_root") != str(app)
            or value.get("status") != "CANDIDATE_NOT_ACTIVATED"
            or claimed_sha != canonical_sha(unsigned)):
        raise ValueError("FINAL3_SOURCE_MANIFEST_INVALID:" + name)
    current = _file_inventory(app)
    # The C1 stage helper snapshots the closed app inventory immediately
    # before it creates this receipt to avoid a self-referential hash.
    current.pop(manifest_path.name, None)
    if current != value.get("app_file_sha256"):
        raise ValueError("FINAL3_SOURCE_INVENTORY_DRIFT:" + name)
    return manifest_path, value


def _release_manifest(*, source_root: Path, source_manifest_path: Path, source_manifest: Mapping[str, Any],
                      app_root: Path, release_root: Path, release_id: str,
                      overlay: Mapping[str, Any]) -> dict[str, Any]:
    entries = inventory_tree(app_root)
    digest = inventory_digest(entries)
    symlinks = [item for item in entries if item.get("kind") == "symlink"]
    missing = [str(item["path"]) for item in symlinks if not item.get("target_exists")]
    dist_prefix = "web/dist"
    dist = [item for item in entries if str(item["path"]) == dist_prefix or str(item["path"]).startswith(dist_prefix + "/")]
    review_sha = sha(FINAL3_REVIEW.read_bytes())
    return {
        "schema_version": "v4.release_candidate.v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "candidate_status": "READY_FOR_INDEPENDENT_REVIEW",
        "activation_status": "NOT_ACTIVATED",
        "deployment_status": "CANNOT_CONFIRM",
        "source": {
            "root": str(source_root),
            "accepted_final3_manifest": {"path": str(source_manifest_path), "sha256": sha(source_manifest_path.read_bytes())},
            "accepted_final3_stage_receipt_sha256": str(source_manifest.get("sha256")),
            "accepted_final3_independent_review": {"path": str(FINAL3_REVIEW), "sha256": review_sha,
                "verdict": "PASS_FINAL3_REPAIR_DELTA"},
            "copied_full_app_tree": True,
            "excluded_from_copy": sorted(["__pycache__", ".pytest_cache", "*.pyc", ".DS_Store"]),
            "reviewed_file_overlays": dict(overlay),
            "data_copy_performed": False,
        },
        "candidate": {
            "root": str(release_root), "app_root": str(app_root), "release_id": release_id,
            "formal_release_root": str(release_root.parent),
            "overwrite_policy": "refuse an existing target; no activation performed",
            "data_copy_performed": False, "ignored_runtime_data_copied": False,
        },
        "application_inventory": {
            "entry_count": len(entries), "aggregate_sha256": digest, "entries": entries,
            "symlink_entries": symlinks, "missing_symlink_targets": missing,
        },
        "frontend_dist": {"entry_count": len(dist), "aggregate_sha256": inventory_digest(dist), "entries": dist},
        "verification": {
            "c1_final3_reviewer": {"path": str(FINAL3_REVIEW), "sha256": review_sha, "verdict": "PASS_FINAL3_REPAIR_DELTA"},
            "d1_reviewed_overlay_sources": "REVIEWED_PASS_FOR_FROZEN_DELTAS",
            "runtime_api_ui_natural": "CANNOT_CONFIRM",
        },
        "safety": {"RESEARCH_ONLY": True, "production_allowed": False,
                   "buy_gate_updated": False, "orders_sent": False},
    }


def _route_block(raw: bytes, marker: bytes, next_marker: bytes | None = None) -> tuple[bytes, int, int]:
    start = raw.find(marker)
    if start < 0:
        raise ValueError("D1_ROUTER_ROUTE_MARKER_MISSING:" + marker.decode())
    if next_marker is None:
        next_marker = b"\n    @router."
        end = raw.find(next_marker, start + len(marker))
    else:
        end = raw.find(next_marker, start + len(marker))
        if end >= 0 and end > 0 and raw[end - 1:end] == b"\n":
            # The independent receipt hashes the bytes ending immediately
            # before the next route decorator, including no separator newline.
            pass
    if end < 0:
        raise ValueError("D1_ROUTER_NEXT_ROUTE_MARKER_MISSING")
    return raw[start:end], start, end


def _verify_d1_review_receipts() -> dict[str, Any]:
    results: dict[str, Any] = {}
    for path, expected in D1_REVIEW_RECEIPTS.items():
        if path.is_symlink() or not path.is_file() or sha(path.read_bytes()) != expected:
            raise ValueError("D1_REVIEW_RECEIPT_IDENTITY_MISMATCH:" + str(path))
        value = json.loads(path.read_text(encoding="utf-8"))
        if path == D1_CLI_RESUME_REVIEW:
            if value.get("verdict", {}).get("reviewed") != "PASS":
                raise ValueError("D1_CLI_RESUME_REVIEW_NOT_PASS")
        elif path == D1_TERMINAL_REVIEW:
            if value.get("statuses", {}).get("REVIEWED") != "PASS_FOR_D1_TERM_P2_01":
                raise ValueError("D1_TERMINAL_REVIEW_NOT_PASS")
        elif path == D1_CANARY_REVIEW:
            if value.get("statuses", {}).get("REVIEWED") != "PASS_FOR_FROZEN_P1_P2_HELPER_REPAIR_SCOPE.":
                raise ValueError("D1_CANARY_REVIEW_NOT_PASS")
        elif path == D1_ROUTER_REVIEW:
            if value.get("review_status", {}).get("D1-PLAN-P2-02") != "PASS_FOR_FOCUSED_ISOLATED_IMPORT_AND_READBACK_COVERAGE":
                raise ValueError("D1_ROUTER_REVIEW_NOT_PASS")
        results[str(path)] = {"sha256": expected, "review_status": "PASS"}
    return results


def _reviewed_api_overlay_plan(api_source_root: Path, canonical_root: Path) -> tuple[dict[str, bytes], dict[str, Any]]:
    review_receipts = _verify_d1_review_receipts()
    files: dict[str, bytes] = {}
    manifest: dict[str, Any] = {}
    for relative, entry in REVIEWED_FULL_FILE_OVERLAYS.items():
        if relative == "ops/run_v35_macos_scheduler_daemon.py":
            continue
        source = Path(entry["source"])
        if source.is_symlink() or not source.is_file() or sha(source.read_bytes()) != entry["sha256"]:
            raise ValueError("D1_OVERLAY_SOURCE_IDENTITY_MISMATCH:" + str(source))
        review_path = Path(entry["review"])
        receipt = json.loads(review_path.read_text(encoding="utf-8"))
        # Bind the receipt's own frozen source evidence, not just its filename.
        if relative == "ops/manager_announcement_body_batch.py":
            frozen = receipt.get("hashes", {}).get("frozen_artifacts", {}).get("body_batch", {})
            if frozen.get("actual_sha256") != entry["sha256"] or frozen.get("matches_frozen") is not True:
                raise ValueError("D1_BODY_BATCH_REVIEW_SOURCE_MISMATCH")
        elif relative == "ops/run_manager_daily_announcement.py":
            changed = receipt.get("diff_review", {}).get("source_changes", [])
            if not any(item.get("path") == relative and item.get("current_sha256") == entry["sha256"] for item in changed):
                raise ValueError("D1_DAILY_CLI_REVIEW_SOURCE_MISMATCH")
        elif relative.startswith("v4/manager_research/"):
            preserved = receipt.get("diff_review", {}).get("preserved_unchanged_sources", {})
            if preserved.get(relative) != entry["sha256"]:
                raise ValueError("D1_ANNOUNCEMENT_MODULE_REVIEW_SOURCE_MISMATCH:" + relative)
        else:
            changed = receipt.get("source_identity", {}).get("changed_files", [])
            if not any(item.get("path", "").endswith("/" + relative) and item.get("current_sha256") == entry["sha256"] for item in changed):
                raise ValueError("D1_RUNTIME_OVERLAY_REVIEW_SOURCE_MISMATCH:" + relative)
        raw = source.read_bytes()
        files[relative] = raw
        manifest[relative] = {
            "source_path": str(source), "source_sha256": entry["sha256"],
            "result_sha256": entry["sha256"],
            "review_receipt": {"path": str(review_path), "sha256": entry["review_sha256"],
                               "review_kind": entry["review_kind"]},
        }

    base_router_path = api_source_root / "apps/api/v35_api/manager_research_router.py"
    canonical_router_path = canonical_root / "apps/api/v35_api/manager_research_router.py"
    if (sha(base_router_path.read_bytes()) != ROUTER_BASE_SHA256
            or sha(canonical_router_path.read_bytes()) != ROUTER_SOURCE_SHA256):
        raise ValueError("D1_ROUTER_SOURCE_IDENTITY_MISMATCH")
    base_raw = base_router_path.read_bytes()
    canonical_raw = canonical_router_path.read_bytes()
    marker = b'    @router.post("/workspace/refresh")'
    base_block, base_start, base_end = _route_block(base_raw, marker)
    reviewed_block, _, _ = _route_block(canonical_raw, marker)
    if (sha(base_block) != ROUTER_BASE_REFRESH_SHA256
            or sha(reviewed_block) != ROUTER_REVIEWED_REFRESH_SHA256):
        raise ValueError("D1_ROUTER_REFRESH_HUNK_IDENTITY_MISMATCH")
    import_block, _, _ = _route_block(
        base_raw, b'@router.post("/announcements/analysis/import")',
        b'@router.post("/announcements/refresh")',
    )
    if sha(import_block) != ROUTER_REVIEWED_IMPORT_SHA256:
        raise ValueError("C1_REFERENCE_IMPORT_ROUTE_DRIFT")
    composed = base_raw[:base_start] + reviewed_block + base_raw[base_end:]
    if sha(composed) != ROUTER_REVIEWED_RESULT_SHA256:
        raise ValueError("D1_ROUTER_COMPOSED_SOURCE_SHA_MISMATCH")
    files["apps/api/v35_api/manager_research_router.py"] = composed
    manifest["apps/api/v35_api/manager_research_router.py"] = {
        "source_path": str(canonical_router_path), "source_sha256": ROUTER_SOURCE_SHA256,
        "base_path": str(base_router_path), "base_sha256": ROUTER_BASE_SHA256,
        "base_refresh_hunk_sha256": ROUTER_BASE_REFRESH_SHA256,
        "reviewed_refresh_hunk_sha256": ROUTER_REVIEWED_REFRESH_SHA256,
        "preserved_c1_import_route_sha256": ROUTER_REVIEWED_IMPORT_SHA256,
        "result_sha256": sha(composed),
        "review_receipts": [
            {"path": str(D1_ROUTER_REVIEW), "sha256": D1_REVIEW_RECEIPTS[D1_ROUTER_REVIEW],
             "review_kind": "D1_PLAN_P2_02_REFERENCE_IMPORT_READBACK"},
            {"path": str(D1_CANARY_REVIEW), "sha256": D1_REVIEW_RECEIPTS[D1_CANARY_REVIEW],
             "review_kind": "D1_PLAN_CANARY_ROUTE_READBACK_SCOPE"},
        ],
        "method": "reviewed workspace-refresh route hunk only; C1 final3 import route retained byte-for-byte",
    }

    runbook = RUNBOOK_SOURCE
    if runbook.is_symlink() or not runbook.is_file() or sha(runbook.read_bytes()) != RUNBOOK_SHA256:
        raise ValueError("D1_RUNBOOK_SOURCE_IDENTITY_MISMATCH")
    files["docs/manager_daily_research.md"] = runbook.read_bytes()
    manifest["docs/manager_daily_research.md"] = {
        "source_path": str(runbook), "source_sha256": RUNBOOK_SHA256,
        "result_sha256": RUNBOOK_SHA256, "review_receipt": None,
        "review_kind": "PARENT_AUTHORIZED_FINAL_ENTRY_AND_BOUNDARY_RUNBOOK",
    }
    return files, {"files": manifest, "review_receipts": review_receipts}


def prepare_release_roots(*, source_root: Path = FINAL3_ROOT,
                          api_target: Path = API_RELEASE_ROOT,
                          scheduler_target: Path = SCHEDULER_RELEASE_ROOT,
                          canonical_root: Path = APP_ROOT) -> dict[str, Any]:
    """Copy accepted C1 roots and exact reviewed D1 deltas once."""
    if FINAL3_REVIEW.is_symlink() or not FINAL3_REVIEW.is_file():
        raise ValueError("FINAL3_REVIEW_RECEIPT_MISSING")
    if sha(FINAL3_REVIEW.read_bytes()) != FINAL3_REVIEW_SHA256:
        raise ValueError("FINAL3_REVIEW_RECEIPT_IDENTITY_MISMATCH")
    review = json.loads(FINAL3_REVIEW.read_text(encoding="utf-8"))
    if not (review.get("status") == "PASS_FINAL3_REPAIR_DELTA"
            or review.get("verdict") == "PASS_FINAL3_REPAIR_DELTA"):
        raise ValueError("FINAL3_REVIEW_NOT_PASS")
    api_src = source_root / "release/api_app"
    scheduler_src = source_root / "release/scheduler_app"
    api_source_manifest_path, api_source_manifest = _final3_manifest(source_root, "api_app")
    scheduler_source_manifest_path, scheduler_source_manifest = _final3_manifest(source_root, "scheduler_app")
    if canonical_root != APP_ROOT:
        raise ValueError("D1_CANONICAL_SOURCE_ROOT_NOT_AUTHORIZED")
    if api_target != API_RELEASE_ROOT or scheduler_target != SCHEDULER_RELEASE_ROOT:
        raise ValueError("D1_RELEASE_TARGET_NOT_AUTHORIZED")
    for target in (api_target, scheduler_target):
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
        if target.parent.resolve(strict=True) != target.parent:
            raise ValueError("D1_RELEASE_PARENT_NOT_EXACT:" + str(target.parent))
    api_overlays, overlay_source_map = _reviewed_api_overlay_plan(api_src, canonical_root)
    scheduler_daemon_rel = "ops/run_v35_macos_scheduler_daemon.py"
    daemon_spec = REVIEWED_FULL_FILE_OVERLAYS[scheduler_daemon_rel]
    daemon_source = Path(daemon_spec["source"])
    if daemon_source.is_symlink() or not daemon_source.is_file() or sha(daemon_source.read_bytes()) != daemon_spec["sha256"]:
        raise ValueError("D1_SCHEDULER_DAEMON_SOURCE_IDENTITY_MISMATCH")
    canary_review = json.loads(D1_CANARY_REVIEW.read_text(encoding="utf-8"))
    canary_changed = canary_review.get("source_identity", {}).get("changed_files", [])
    if not any(item.get("path", "").endswith("/" + scheduler_daemon_rel)
               and item.get("current_sha256") == daemon_spec["sha256"] for item in canary_changed):
        raise ValueError("D1_SCHEDULER_DAEMON_REVIEW_SOURCE_MISMATCH")
    scheduler_overlay = daemon_source.read_bytes()
    old_daemon_sha = sha((scheduler_src / scheduler_daemon_rel).read_bytes())
    new_daemon_sha = sha(scheduler_overlay)
    if old_daemon_sha == new_daemon_sha or new_daemon_sha != daemon_spec["sha256"]:
        raise ValueError("D1_SAME_ROOT_VALIDATOR_OVERLAY_MISSING_OR_DRIFTED")
    preflight = {
        "api": _final3_manifest(source_root, "api_app")[1]["sha256"],
        "scheduler": _final3_manifest(source_root, "scheduler_app")[1]["sha256"],
        "reviewed_overlay_manifest_sha256": canonical_sha(overlay_source_map),
    }
    if len(preflight) != 3:
        raise ValueError("D1_RELEASE_PREFLIGHT_INVALID")

    api_target.mkdir(parents=True, exist_ok=False)
    scheduler_target.mkdir(parents=True, exist_ok=False)
    _tree_without_cache(api_src, api_target / "app")
    _tree_without_cache(scheduler_src, scheduler_target / "app")
    api_overlay_manifest: dict[str, Any] = {}
    for relative, raw in api_overlays.items():
        destination = api_target / "app" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        item = dict(overlay_source_map["files"][relative])
        item["base_sha256"] = sha((api_src / relative).read_bytes())
        item["result_sha256"] = sha(raw)
        api_overlay_manifest[relative] = item
    scheduler_destination = scheduler_target / "app" / scheduler_daemon_rel
    scheduler_destination.write_bytes(scheduler_overlay)
    scheduler_overlay_manifest = {
        scheduler_daemon_rel: {
            "source_path": str(daemon_source), "source_sha256": daemon_spec["sha256"],
            "review_receipt": {"path": str(D1_CANARY_REVIEW), "sha256": D1_REVIEW_RECEIPTS[D1_CANARY_REVIEW],
                               "review_kind": daemon_spec["review_kind"]},
            "base_sha256": old_daemon_sha, "result_sha256": new_daemon_sha,
        }
    }
    # The immutable inventory binds modes as well as file bytes. Freeze app
    # trees before inventory generation; release manifests live one level up.
    _make_tree_read_only(api_target / "app")
    _make_tree_read_only(scheduler_target / "app")
    api_manifest = _release_manifest(source_root=source_root, source_manifest_path=api_source_manifest_path,
        source_manifest=api_source_manifest, app_root=api_target / "app", release_root=api_target,
        release_id="manager-daily-chain-20261008-r2-api", overlay={
            "files": api_overlay_manifest,
            "review_receipts": overlay_source_map["review_receipts"],
        })
    scheduler_manifest = _release_manifest(source_root=source_root, source_manifest_path=scheduler_source_manifest_path,
        source_manifest=scheduler_source_manifest, app_root=scheduler_target / "app", release_root=scheduler_target,
        release_id="manager-daily-chain-20261008-r2-scheduler", overlay={
            "files": scheduler_overlay_manifest,
            "review_receipts": overlay_source_map["review_receipts"],
        })
    api_manifest_path = api_target / "release-manifest.json"
    scheduler_manifest_path = scheduler_target / "release-manifest.json"
    write_exclusive(api_manifest_path, (json.dumps(api_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
    write_exclusive(scheduler_manifest_path, (json.dumps(scheduler_manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
    api_sha, scheduler_sha = sha(api_manifest_path.read_bytes()), sha(scheduler_manifest_path.read_bytes())
    for release_root in (api_target, scheduler_target):
        _make_tree_read_only(release_root)
    return {
        "status": "INACTIVE_RELEASE_ROOTS_PREPARED",
        "activation_status": "NOT_ACTIVATED", "launchctl_called": False,
        "api": {"root": str(api_target), "app_root": str(api_target / "app"),
                "manifest_path": str(api_manifest_path), "manifest_sha256": api_sha,
                "application_inventory_sha256": api_manifest["application_inventory"]["aggregate_sha256"]},
        "scheduler": {"root": str(scheduler_target), "app_root": str(scheduler_target / "app"),
                "manifest_path": str(scheduler_manifest_path), "manifest_sha256": scheduler_sha,
                "application_inventory_sha256": scheduler_manifest["application_inventory"]["aggregate_sha256"]},
        "reviewed_source_overlays": {"api": api_overlay_manifest, "scheduler": scheduler_overlay_manifest,
                                     "review_receipts": overlay_source_map["review_receipts"]},
        "safety": {"RESEARCH_ONLY": True, "production_allowed": False,
                   "buy_gate_updated": False, "orders_sent": False},
    }


def _make_tree_read_only(root: Path) -> None:
    for current, dirs, files in os.walk(root, topdown=False, followlinks=False):
        base = Path(current)
        for name in files:
            path = base / name
            if path.is_symlink():
                continue
            info = path.stat(follow_symlinks=False)
            if stat.S_ISREG(info.st_mode):
                path.chmod(stat.S_IMODE(info.st_mode) & ~0o222)
        for name in dirs:
            path = base / name
            if path.is_symlink():
                continue
            path.chmod(stat.S_IMODE(path.stat(follow_symlinks=False).st_mode) & ~0o222)
        base.chmod(stat.S_IMODE(base.stat(follow_symlinks=False).st_mode) & ~0o222)


def stage_disabled_configs(*, api_root: Path = API_RELEASE_ROOT / "app",
                           scheduler_root: Path = SCHEDULER_RELEASE_ROOT / "app",
                           api_plist_path: Path = API_PLIST,
                           scheduler_plist_path: Path = SCHEDULER_PLIST,
                           output_root: Path = CONFIG_ROOT) -> dict[str, Any]:
    """Render disabled binding/plists against the formal state path, locally only."""
    if api_root != API_RELEASE_ROOT / "app" or scheduler_root != SCHEDULER_RELEASE_ROOT / "app":
        raise ValueError("D1_STAGE_APP_ROOT_NOT_AUTHORIZED")
    if not api_root.is_dir() or not scheduler_root.is_dir():
        raise ValueError("D1_RELEASE_ROOTS_NOT_READY")
    api_manifest_path = api_root.parent / "release-manifest.json"
    scheduler_manifest_path = scheduler_root.parent / "release-manifest.json"
    api_manifest_sha = sha(api_manifest_path.read_bytes())
    scheduler_manifest_sha = sha(scheduler_manifest_path.read_bytes())
    api_source = plistlib.loads(api_plist_path.read_bytes())
    scheduler_source = plistlib.loads(scheduler_plist_path.read_bytes())
    api_source_env = extract_environment(api_source)
    scheduler_source_env = extract_environment(scheduler_source)
    if (api_source_env.get("V35_APP_ROOT") != str(ACTIVE_API_ROOT)
            or scheduler_source_env.get("V35_APP_ROOT") != str(ACTIVE_SCHEDULER_ROOT)
            or api_source_env.get("V4_MANAGER_RESEARCH_STATE_ROOT") != str(FORMAL_MANAGER_STATE)
            or scheduler_source_env.get("V4_MANAGER_RESEARCH_STATE_ROOT") != str(FORMAL_MANAGER_STATE)
            or scheduler_source_env.get("V4_MANAGER_ANNOUNCEMENT_PYTHON") != str(EXACT_PYTHON)
            or not FORMAL_MANAGER_STATE.is_dir()):
        raise ValueError("D1_ACTIVE_PLIST_OR_FORMAL_STATE_IDENTITY_MISMATCH")
    api_args = api_source.get("ProgramArguments")
    if not isinstance(api_args, list) or "/usr/bin/env" not in api_args:
        raise ValueError("D1_API_PLIST_SOURCE_CONTRACT_INVALID")
    api_python_candidates = [Path(item) for item in api_args if isinstance(item, str) and item.startswith("/") and item.endswith("/bin/python")]
    if api_python_candidates != [EXACT_PYTHON]:
        raise ValueError("D1_API_PYTHON_IDENTITY_MISMATCH")
    if output_root != CONFIG_ROOT:
        raise ValueError("D1_CONFIG_OUTPUT_NOT_AUTHORIZED")
    binding_path = output_root / "manager-plan-binding-c1.disabled.final-d1-r2.json"
    blocked_path = output_root / "manager-plan-binding-c1.proposed-enabled.blocked.final-d1-r2.json"
    api_out = output_root / "com.lexi.v35.api-only.c1-final-d1-r2.plist"
    scheduler_out = output_root / "com.lexi.v35.scheduler.c1-final-d1-r2.plist"
    receipt_path = output_root / "manager_daily_chain_c1_release_receipt.final-d1-r2.json"
    for path in (api_out, scheduler_out, receipt_path):
        if path.exists() or path.is_symlink():
            raise FileExistsError(path)
    for source_path, name in ((api_plist_path, "active-api-only.plist"),
                              (scheduler_plist_path, "active-scheduler.plist")):
        preimage_path = SOURCE_PLIST_PREIMAGE / name
        if preimage_path.exists() or preimage_path.is_symlink():
            if preimage_path.is_symlink() or not preimage_path.is_file() or preimage_path.read_bytes() != source_path.read_bytes():
                raise ValueError("D1_SOURCE_PLIST_PREIMAGE_CONFLICT:" + name)
    py_resolved = EXACT_PYTHON.resolve(strict=True)
    master = Path(api_source_env["V4_MANAGER_SECURITY_MASTER_ROOT"])
    if not master.is_dir() or master.resolve(strict=True) != master:
        raise ValueError("D1_SECURITY_MASTER_ROOT_NOT_EXACT")
    binding = {
        "schema_version": BINDING_SCHEMA, "enabled": False,
        "policy_status": "PROPOSAL_ONLY", "policy": "BALANCED_V1",
        "research_only": True, "production_allowed": False,
        "buy_gate_updated": False, "orders_sent": False,
        "app_root": str(api_root), "manager_state_root": str(FORMAL_MANAGER_STATE),
        "security_master_root": str(master), "python": str(EXACT_PYTHON),
        "python_resolved": str(py_resolved), "python_sha256": sha(py_resolved.read_bytes()),
        "priority_codes": [], "preopen_plan": {"enabled": True, "lead_seconds": 180, "status": "PROPOSAL_ONLY"},
        "plan_material_refresh_only": False, "announcement_collection_enabled": False,
        "announcement_execution_owner": {
            "execution_owner": "HEARTBEAT", "ownership_status": "HEARTBEAT_OWNED",
            "automation_ref": "automation-3", "scheduler_hook_enabled": False,
            "latest_execution_status": "NOT_RUN", "latest_success_status": "CANNOT_CONFIRM",
            "latest_gap_status": "CANNOT_CONFIRM", "latest_receipt_status": "NOT_OBSERVED",
        },
        "files": binding_inventory(api_root),
    }
    validate_binding(binding, api_root)
    binding_raw = (json.dumps(binding, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    if binding_path.exists() or binding_path.is_symlink():
        if binding_path.is_symlink() or not binding_path.is_file() or binding_path.read_bytes() != binding_raw:
            raise ValueError("D1_EXISTING_DISABLED_BINDING_CONFLICT")
    else:
        write_exclusive(binding_path, binding_raw)
    blocked = copy.deepcopy(binding)
    blocked.update({
        "enabled": True,
        "plan_material_refresh_only": True,
        "announcement_collection_enabled": False,
        "plan_material_refresh": {"enabled": True, "start_local": "16:00", "end_local": "23:00",
            "max_attempts_per_target_date": 3, "retry_backoff_seconds": 600, "status": "PROPOSAL_ONLY"},
        "activation_status": "BLOCKED_OWNER_CANARY_REQUIRED",
        "required_activation_evidence": "fresh exact-root MANUAL_REFRESH HTTP owner readback receipt",
    })
    blocked_raw = (json.dumps(blocked, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    if blocked_path.exists() or blocked_path.is_symlink():
        if blocked_path.is_symlink() or not blocked_path.is_file() or blocked_path.read_bytes() != blocked_raw:
            raise ValueError("D1_EXISTING_BLOCKED_BINDING_CONFLICT")
    else:
        write_exclusive(blocked_path, blocked_raw)
    api_staged = rewrite_api_only_plist(api_source, candidate_app_root=api_root,
        release_id="manager-daily-chain-20261008-r2-api",
        manifest_path=api_manifest_path, manifest_sha256=api_manifest_sha,
        candidate_manager_state_root=FORMAL_MANAGER_STATE)
    api_staged["ProgramArguments"] = _replace_assignments(api_staged["ProgramArguments"], {
        "PYTHONPATH": f"{api_root / 'upstreams'}:{api_root}",
        "V35_APP_ROOT": str(api_root),
        "V35_RELEASE_ID": "manager-daily-chain-20261008-r2-api",
        "V35_RELEASE_MANIFEST_PATH": str(api_manifest_path),
        "V35_RELEASE_MANIFEST_SHA256": api_manifest_sha,
        "V4_MANAGER_PLAN_OWNER_BINDING_PATH": str(binding_path),
    })
    api_cycle_sha = sha((api_root / "ops/run_manager_announcement_cycle.py").read_bytes())
    scheduler_staged = _stage_scheduler_plist(scheduler_source, source_path=scheduler_plist_path,
        scheduler_root=scheduler_root, api_root=api_root,
        release_id="manager-daily-chain-20261008-r2-scheduler",
        manifest_path=scheduler_manifest_path, manifest_sha=scheduler_manifest_sha,
        binding_path=binding_path, state_root=FORMAL_MANAGER_STATE,
        api_cycle_sha=api_cycle_sha, python=EXACT_PYTHON)
    write_exclusive(api_out, plistlib.dumps(api_staged, fmt=plistlib.FMT_XML, sort_keys=True))
    write_exclusive(scheduler_out, plistlib.dumps(scheduler_staged, fmt=plistlib.FMT_XML, sort_keys=True))
    # Save the exact source plists only after every input check has passed.
    for source_path, name in ((api_plist_path, "active-api-only.plist"),
                              (scheduler_plist_path, "active-scheduler.plist")):
        preimage_path = SOURCE_PLIST_PREIMAGE / name
        if not preimage_path.exists():
            write_exclusive(preimage_path, source_path.read_bytes())
    receipt = {
        "schema_version": "manager_daily_chain.d1_release_stage.v1",
        "status": "CANDIDATE_STAGED_NOT_ACTIVATED",
        "activation_status": "NOT_ACTIVATED", "launchctl_called": False,
        "source_api_plist": {"path": str(api_plist_path), "sha256": sha(api_plist_path.read_bytes())},
        "source_scheduler_plist": {"path": str(scheduler_plist_path), "sha256": sha(scheduler_plist_path.read_bytes())},
        "candidate_api": {"root": str(api_root), "manifest_path": str(api_manifest_path),
            "manifest_sha256": api_manifest_sha, "staged_plist": str(api_out), "staged_plist_sha256": sha(api_out.read_bytes())},
        "candidate_scheduler": {"root": str(scheduler_root), "manifest_path": str(scheduler_manifest_path),
            "manifest_sha256": scheduler_manifest_sha, "staged_plist": str(scheduler_out), "staged_plist_sha256": sha(scheduler_out.read_bytes())},
        "shared_binding": {"path": str(binding_path), "sha256": sha(binding_path.read_bytes()),
            "enabled": False, "plan_material_refresh_only": False,
            "announcement_collection_enabled": False, "manager_state_root": str(FORMAL_MANAGER_STATE)},
        "blocked_plan_only_proposal": {"path": str(blocked_path), "sha256": sha(blocked_path.read_bytes()),
            "enabled": True, "plan_material_refresh_only": True,
            "activation_status": "BLOCKED_OWNER_CANARY_REQUIRED", "plan_activation_receipt": "MISSING"},
        "rollback": {
            "status": "IDENTITY_ONLY_NO_ACTIVATION",
            "active_api_plist_path": str(api_plist_path), "active_api_plist_sha256": sha(api_plist_path.read_bytes()),
            "active_scheduler_plist_path": str(scheduler_plist_path), "active_scheduler_plist_sha256": sha(scheduler_plist_path.read_bytes()),
            "active_api_root": str(ACTIVE_API_ROOT), "active_scheduler_root": str(ACTIVE_SCHEDULER_ROOT),
            "manager_state_root": str(FORMAL_MANAGER_STATE),
            "guard": "Active plist files and formal state were read only; staged files live under deployment/c1_plan_only.",
        },
        "safety": {"RESEARCH_ONLY": True, "production_allowed": False,
                   "buy_gate_updated": False, "orders_sent": False},
    }
    write_exclusive(receipt_path, (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
    return receipt


def plan_canary_effect(*, target_trade_date: str = "20260925",
                       manager_state_root: Path = FORMAL_MANAGER_STATE) -> dict[str, Any]:
    if target_trade_date != "20260925" or manager_state_root != FORMAL_MANAGER_STATE:
        raise ValueError("D1_PLAN_CANARY_TARGET_OR_STATE_NOT_AUTHORIZED")
    return {
        "status": "DRY_RUN_NO_HTTP_NO_WRITE",
        "target_trade_date": target_trade_date,
        "manager_state_root": str(manager_state_root),
        "durable_owner_write_paths": [
            str(manager_state_root / "workspace_plan_runs" / target_trade_date / "latest.json"),
            str(manager_state_root / "workspace_plan_runs" / target_trade_date / "<owner-run-id>.json"),
            str(manager_state_root / "workspace_plans" / target_trade_date / "latest.json"),
            str(manager_state_root / "workspace_plans" / target_trade_date / "<owner-run-id>.json"),
        ],
        "transient_lock_path": str(manager_state_root / ".locks" / f"{target_trade_date}-workspace-plan-refresh.mutex"),
        "method": "POST then GET",
        "transport": "ASGI in-process to exact immutable API app, base_url http://127.0.0.1:8873",
        "formal_enable_config": "only written after actual owner responses and store readback pass; task-root only",
        "live_api_or_natural_verification": "NOT_PROVEN",
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true", help="create the two exact inactive release roots and staged disabled configs")
    parser.add_argument("--plan-canary-dry-run", action="store_true", help="print the exact historical owner write effect; never calls HTTP")
    args = parser.parse_args()
    if args.prepare == args.plan_canary_dry_run:
        parser.error("select exactly one of --prepare or --plan-canary-dry-run")
    if args.plan_canary_dry_run:
        print(json.dumps(plan_canary_effect(), ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    release = prepare_release_roots()
    staged = stage_disabled_configs()
    print(json.dumps({"release": release, "staged": staged}, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
