"""Record the Stage source bytes observed by this invocation.

These are local file hashes, not an attestation of previously loaded Python
bytecode, a deployment receipt, or proof that a timer invoked the runner.
The original selection manifest and immutable owner receipt bind this record.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


SOURCE_RELATIVES = (
    "ops/run_stage_center_nodes.py",
    "ops/_run_stage_center_nodes_parts/node_entry.py",
    "ops/_run_stage_center_nodes_parts/runtime_arguments.py",
    "ops/_run_stage_center_nodes_parts/deadline_supervision.py",
    "stage_center/runtime_source_identity.py",
    "stage_center/runner.py",
    "stage_center/hk_current_day_research.py",
    "stage_center/acquisition.py",
    "stage_center/candidate_input.py",
    "stage_center/research_context.py",
    "stage_center/live_collectors.py",
    "stage_center/selection.py",
    "stage_center/raw_store.py",
    "stage_center/_runner_parts/configuration.py",
    "stage_center/_runner_parts/selection_input_validation.py",
    "stage_center/_runner_parts/hk_input_validation.py",
    "stage_center/_runner_parts/hk_candidate_authority.py",
    "stage_center/_runner_parts/a_candidate_authority.py",
    "stage_center/_runner_parts/slot_execution.py",
    "stage_center/_runner_parts/slot_idempotency.py",
    "stage_center/_runner_parts/tick_planning.py",
    "stage_center/_runner_parts/runner_receipts.py",
    "stage_center/_live_collectors_parts/collector_registry.py",
    "stage_center/_live_collectors_parts/selection_builder_registry.py",
    "stage_center/_live_collectors_parts/a_auction.py",
    "stage_center/_live_collectors_parts/a_minute.py",
    "stage_center/_live_collectors_parts/hk_minute.py",
    "stage_center/_live_collectors_parts/shared_module_loading.py",
    "stage_center/_selection_parts/a_auction.py",
    "stage_center/_selection_parts/a_live.py",
    "stage_center/_selection_parts/a_stage.py",
    "stage_center/_selection_parts/hk_four_lanes.py",
    "stage_center/_selection_parts/hk_formula_score.py",
    "stage_center/_selection_parts/selection_envelope.py",
    "stage_center/_selection_parts/store_publication.py",
    "stage_center/_selection_parts/store_verification.py",
    "stage_center/_raw_store_parts/transaction_publish.py",
    "stage_center/_raw_store_parts/transaction_read.py",
)
_SCHEMA = "stage_center.runtime_source_identity.v1"


def _digest(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key not in {"sha256", "status"}}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def capture_runtime_source_identity(*, root: Path | None = None) -> dict[str, Any]:
    # root is a test seam, never a runner setting or path from input metadata.
    source_root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    files, missing = {}, []
    for relative in SOURCE_RELATIVES:
        path = source_root / relative
        try:
            if path.is_symlink() or any(parent.is_symlink() for parent in path.parents
                                         if parent != source_root and source_root in parent.parents):
                raise ValueError("source path is a symlink")
            content = path.read_bytes()
            if len(content) > 8 * 1024 * 1024:
                raise ValueError("source file too large")
            files[relative] = {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
        except (OSError, ValueError):
            missing.append(relative)
    result = {
        "schema_version": _SCHEMA,
        "owner": "STAGE_RUNNER",
        "scope": "SOURCE_FILES_AT_RUNNER_ENTRY_NOT_PROCESS_ATTESTATION",
        "files": files,
        "missing_files": missing,
    }
    result["sha256"] = _digest(result)
    result["status"] = "CANNOT_CONFIRM" if missing else "RECORDED"
    return result


def source_stability(entry: Mapping[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    """Compare the declared entry bytes with disk without blocking results."""
    base = {"execution_verified": False, "natural_verified": False}
    try:
        if (entry.get("schema_version") != _SCHEMA or entry.get("sha256") != _digest(entry)
                or not isinstance(entry.get("files"), dict)):
            return {**base, "status": "SOURCE_IDENTITY_INVALID"}
        observed = capture_runtime_source_identity(root=root)
        if entry.get("status") != "RECORDED" or observed["status"] != "RECORDED":
            status = "SOURCE_IDENTITY_INCOMPLETE"
        elif observed["sha256"] == entry["sha256"]:
            status = "SOURCE_FILES_UNCHANGED_SINCE_ENTRY"
        else:
            status = "SOURCE_FILES_CHANGED_DURING_RUN"
        changed = sorted(key for key in set(entry["files"]) | set(observed["files"])
                         if entry["files"].get(key) != observed["files"].get(key))
        return {**base, "status": status, "entry_sha256": entry["sha256"],
                "observed_sha256": observed["sha256"], "changed_files": changed,
                "missing_files": observed["missing_files"]}
    except (ValueError, TypeError, AttributeError, RecursionError):
        return {**base, "status": "SOURCE_IDENTITY_INVALID"}
