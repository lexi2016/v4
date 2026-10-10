#!/usr/bin/env python3
"""Copy the frozen Stage R4 app and overlay only reviewed manager sources."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


E = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_OWNER_INPUT_INTEGRATION_MAC_20261010_R1")
V4 = Path("/Users/lexi/Desktop/学习/v4_app")
S = Path("/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R4_MAC_20261009/candidate/mac_apply_20261010_r4_fix_01")
STAGE_ROOT = S / "integration/candidate/stage-research-r4-20261009"
PLAN_PATH = E / "candidate/stage_r4_manager_r2_owner_input_r1_fusion_preflight/integration_plan.json"
R2_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_THREE_CHANNEL_DEPLOY_20261009/candidate/three_channel_release_r2")
R1_ROOT = E / "candidate/owner_input_r1"
R2_DELTA = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_THREE_CHANNEL_DEPLOY_20261009/evidence/validator_r1/r2_delta_receipt.json")
R1_DELTA = E / "evidence/owner_input_r1/candidate_delta_receipt.json"
STAGE_CHANGESET = S / "integration/reviewed-change-set.json"
STAGE_MANIFEST_SHA = "3a9febc7363554ac11466dca7f13b27e5e43c4eeaf8467e94de03dd31341adfa"
R2_MANIFEST_SHA = "f6385dd23e9fda4d2169f20d6dc68b6e1e519b2b1a35e1ceb0bfd3111a079ad5"
R1_DELTA_SHA = "ade7e1828e4762841dbd80a0b8cbb46a8aa21f21d62552395c7dc04d336d9524"
OUT_ROOT = E / "candidate/stage_r4_manager_r2_owner_input_r1_fused_r1"
RECEIPT = E / "evidence/owner_input_r1/stage_r4_fused_source_receipt.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_sha(path: Path) -> str | None:
    return sha256(path) if path.is_file() and not path.is_symlink() else None


def read_json(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"EXPECTED_JSON_OBJECT:{path}")
    return value, hashlib.sha256(raw).hexdigest()


def require(condition: bool, code: str) -> None:
    if not condition:
        raise RuntimeError(code)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, path)


def set_directory_writable(path: Path, mode: int) -> None:
    path.chmod(stat.S_IMODE(mode) | stat.S_IWUSR)


def main() -> int:
    sys.path.insert(0, str(V4))
    from ops.api_release_integration import inventory_digest, inventory_tree

    require(not OUT_ROOT.exists(), "OUTPUT_CANDIDATE_ALREADY_EXISTS")
    plan, plan_sha = read_json(PLAN_PATH)
    stage_manifest_path = STAGE_ROOT / "release-manifest.json"
    stage_app = STAGE_ROOT / "app"
    stage_manifest, stage_manifest_sha = read_json(stage_manifest_path)
    require(stage_manifest_sha == STAGE_MANIFEST_SHA, "STAGE_RELEASE_MANIFEST_SHA_CHANGED")
    require(stage_manifest.get("candidate", {}).get("app_root") == str(stage_app), "STAGE_MANIFEST_APP_ROOT_MISMATCH")

    stage_inventory = inventory_tree(stage_app)
    stage_inventory_sha = inventory_digest(stage_inventory)
    manifest_inventory = stage_manifest.get("application_inventory", {})
    require(stage_inventory == manifest_inventory.get("entries"), "STAGE_APP_INVENTORY_ENTRIES_MISMATCH")
    require(stage_inventory_sha == manifest_inventory.get("aggregate_sha256"), "STAGE_APP_INVENTORY_SHA_MISMATCH")
    require(all(entry.get("kind") == "file" for entry in stage_inventory), "STAGE_APP_HAS_NONREGULAR_ENTRY")

    r2_manifest_path = R2_ROOT / "release-manifest.json"
    _, r2_manifest_sha = read_json(r2_manifest_path)
    require(r2_manifest_sha == R2_MANIFEST_SHA, "R2_RELEASE_MANIFEST_SHA_CHANGED")
    r2_delta, r2_delta_sha = read_json(R2_DELTA)
    r1_delta, r1_delta_sha = read_json(R1_DELTA)
    require(r2_delta_sha == plan["inputs"]["r2_delta_receipt_sha256"], "R2_DELTA_RECEIPT_SHA_MISMATCH")
    require(r1_delta_sha == R1_DELTA_SHA == plan["inputs"]["r1_source_delta_receipt_sha256"], "R1_DELTA_RECEIPT_SHA_MISMATCH")
    require(plan["inputs"]["r2_release_manifest_sha256"] == R2_MANIFEST_SHA, "PLAN_R2_MANIFEST_SHA_MISMATCH")

    stage_change, stage_change_sha = read_json(STAGE_CHANGESET)
    stage_source_entries = stage_change.get("files")
    require(isinstance(stage_source_entries, list) and len(stage_source_entries) == 9, "STAGE_REVIEWED_SOURCE_SET_NOT_NINE")
    stage_source_paths = {row["path"] for row in stage_source_entries}
    planned_source_paths = {row["path"] for row in plan.get("source_operations", [])}
    r1_source_rows = r1_delta.get("changed_paths", [])
    r1_source_paths = {row["path"] for row in r1_source_rows}
    require(len(planned_source_paths) == 16, "FUSION_SOURCE_SET_NOT_SIXTEEN")
    require(r1_source_paths == {
        "v4/manager_research/connect_selection.py",
        "v4/manager_research/workspace.py",
    }, "R1_SOURCE_SET_UNEXPECTED")
    overlap = sorted(planned_source_paths & stage_source_paths)
    require(not overlap, "STAGE_AND_MANAGER_SOURCE_PATH_CONFLICT:" + ",".join(overlap))

    r2_source_entries = {row["path"]: row for row in r2_delta.get("entries", [])}
    r1_source_entries = {row["path"]: row for row in r1_source_rows}
    source_checks: list[dict[str, Any]] = []
    for operation in plan["source_operations"]:
        rel = operation["path"]
        staged = stage_app / rel
        actual = file_sha(staged)
        if operation["category"] == "R2_SOURCE":
            before = operation.get("r2_before_sha256")
            after = operation["r2_after_sha256"]
            require((rel in r2_source_entries and r2_source_entries[rel].get("after_sha256") == after), f"R2_DELTA_SOURCE_ROW_MISSING:{rel}")
            require(actual in {before, after} or (before is None and actual is None), f"STAGE_SOURCE_DIVERGENCE:{rel}:{actual}")
            source_path = R2_ROOT / "app" / rel
            require(file_sha(source_path) == after, f"R2_SOURCE_CANDIDATE_SHA_MISMATCH:{rel}")
            source_checks.append({"path": rel, "category": "R2_SOURCE", "stage_sha256": actual, "before_sha256": before, "after_sha256": after, "candidate_source_sha256": file_sha(source_path)})
        else:
            before = operation["r1_before_sha256"]
            after = operation["r1_after_sha256"]
            require(rel in r1_source_entries and r1_source_entries[rel].get("after_sha256") == after, f"R1_DELTA_SOURCE_ROW_MISSING:{rel}")
            require(actual in {before, after}, f"STAGE_SOURCE_DIVERGENCE:{rel}:{actual}")
            source_path = R1_ROOT / "app" / rel
            require(file_sha(source_path) == after, f"R1_SOURCE_CANDIDATE_SHA_MISMATCH:{rel}")
            source_checks.append({"path": rel, "category": "OWNER_INPUT_R1_SOURCE", "stage_sha256": actual, "before_sha256": before, "after_sha256": after, "candidate_source_sha256": file_sha(source_path)})

    for rel, row in r1_source_entries.items():
        source_path = R1_ROOT / "app" / rel
        require(file_sha(source_path) == row.get("after_sha256"), f"R1_SOURCE_CANDIDATE_SHA_MISMATCH:{rel}")
        if rel not in planned_source_paths:
            stage_sha = file_sha(stage_app / rel)
            require(stage_sha in {row.get("before_sha256"), row.get("after_sha256")}, f"STAGE_R1_ONLY_SOURCE_DIVERGENCE:{rel}:{stage_sha}")

    for row in stage_source_entries:
        rel = row["path"]
        require(file_sha(stage_app / rel) == row.get("after_sha256"), f"STAGE_REVIEWED_SOURCE_NOT_AT_AFTER_SHA:{rel}")

    out_app = OUT_ROOT / "app"
    out_app.parent.mkdir(parents=True)
    shutil.copytree(stage_app, out_app, copy_function=shutil.copy2)
    copy_inventory = inventory_tree(out_app)
    require(copy_inventory == stage_inventory, "STAGE_COPY_INVENTORY_NOT_EXACT")

    original_directory_modes: dict[Path, int] = {}
    for directory, names, _ in os.walk(out_app, followlinks=False):
        path = Path(directory)
        mode = stat.S_IMODE(path.stat().st_mode)
        original_directory_modes[path] = mode
        set_directory_writable(path, mode)

    newly_created_directory_modes: dict[Path, int] = {}

    def ensure_parent(source_root: Path, target: Path) -> None:
        rel_parent = target.parent.relative_to(out_app)
        current = out_app
        source_current = source_root
        for part in rel_parent.parts:
            current = current / part
            source_current = source_current / part
            if not current.exists():
                require(source_current.is_dir() and not source_current.is_symlink(), f"SOURCE_PARENT_MISSING:{source_current}")
                current.mkdir()
                src_mode = stat.S_IMODE(source_current.stat().st_mode)
                current.chmod(src_mode | stat.S_IWUSR)
                newly_created_directory_modes[current] = src_mode

    def atomic_overlay(source_root: Path, rel: str, expected_sha: str) -> None:
        source = source_root / rel
        target = out_app / rel
        require(file_sha(source) == expected_sha, f"OVERLAY_SOURCE_SHA_CHANGED:{rel}")
        ensure_parent(source_root, target)
        if target.exists():
            require(not target.is_symlink() and target.is_file(), f"OVERLAY_TARGET_NOT_REGULAR:{rel}")
        temp = target.with_name(target.name + f".fusion-tmp-{os.getpid()}")
        require(not temp.exists(), f"OVERLAY_TEMP_ALREADY_EXISTS:{temp}")
        try:
            shutil.copyfile(source, temp)
            shutil.copystat(source, temp, follow_symlinks=False)
            os.replace(temp, target)
        finally:
            if temp.exists():
                temp.unlink()

    for operation in plan["source_operations"]:
        if operation["category"] == "R2_SOURCE":
            atomic_overlay(R2_ROOT / "app", operation["path"], operation["r2_after_sha256"])

    for rel, row in sorted(r1_source_entries.items()):
        atomic_overlay(R1_ROOT / "app", rel, row["after_sha256"])

    for path, mode in newly_created_directory_modes.items():
        path.chmod(mode)
    for path, mode in reversed(list(original_directory_modes.items())):
        path.chmod(mode)

    after_inventory = inventory_tree(out_app)
    after_by_path = {row["path"]: row for row in after_inventory}
    before_by_path = {row["path"]: row for row in stage_inventory}
    changed = []
    for rel in sorted(set(before_by_path) | set(after_by_path)):
        if before_by_path.get(rel) != after_by_path.get(rel):
            changed.append({"path": rel, "before": before_by_path.get(rel), "after": after_by_path.get(rel)})
    require({row["path"] for row in changed} == planned_source_paths, "FUSED_APP_CHANGED_PATH_SET_NOT_EXACT")
    for operation in plan["source_operations"]:
        rel = operation["path"]
        expected_sha = operation.get("r2_after_sha256") or operation.get("r1_after_sha256")
        if rel == "v4/manager_research/workspace.py":
            expected_sha = operation["owner_input_r1_after_sha256"]
        require(file_sha(out_app / rel) == expected_sha, f"FUSED_SOURCE_FINAL_SHA_MISMATCH:{rel}")
    for rel, row in r1_source_entries.items():
        require(file_sha(out_app / rel) == row["after_sha256"], f"FUSED_R1_FINAL_SHA_MISMATCH:{rel}")

    stage_protected = []
    for row in stage_source_entries:
        rel = row["path"]
        source_sha = file_sha(stage_app / rel)
        fused_sha = file_sha(out_app / rel)
        require(source_sha == fused_sha == row["after_sha256"], f"STAGE_REVIEWED_SOURCE_SHA_CHANGED:{rel}")
        stage_protected.append({"path": rel, "sha256": fused_sha, "bytes": (out_app / rel).stat().st_size})

    issue32_paths = []
    for rel in (
        "apps/api/v35_api/app.py",
        "apps/api/v35_api/preselection_router.py",
        "apps/api/v35_api/preselection_service.py",
    ):
        stage_sha = file_sha(stage_app / rel)
        fused_sha = file_sha(out_app / rel)
        require(stage_sha == fused_sha, f"STAGE_ISSUE32_GUARD_SHA_CHANGED:{rel}")
        if rel != "apps/api/v35_api/app.py":
            require(file_sha(R2_ROOT / "app" / rel) == fused_sha, f"ISSUE32_PRESELECTION_SHA_CHANGED:{rel}")
        issue32_paths.append({"path": rel, "stage_sha256": stage_sha, "fused_sha256": fused_sha, "matches_r2_issue32_base": file_sha(R2_ROOT / "app" / rel) == fused_sha})

    receipt = {
        "schema_version": "stage_r4_manager_r2_owner_input_r1_fusion_source_receipt.v1",
        "status": "PASS",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "plan_path": str(PLAN_PATH),
        "plan_sha256": plan_sha,
        "stage_release_root": str(STAGE_ROOT),
        "stage_release_id": stage_manifest.get("candidate", {}).get("release_id"),
        "stage_release_manifest_sha256": stage_manifest_sha,
        "stage_app_inventory_count": len(stage_inventory),
        "stage_app_inventory_sha256": stage_inventory_sha,
        "stage_copy_inventory_exact": True,
        "r2_release_manifest_sha256": r2_manifest_sha,
        "r2_delta_receipt_sha256": r2_delta_sha,
        "r1_delta_receipt_sha256": r1_delta_sha,
        "stage_reviewed_change_set_sha256": stage_change_sha,
        "stage_reviewed_source_count": len(stage_protected),
        "stage_reviewed_source_paths_preserved": stage_protected,
        "stage_manager_source_path_overlap": overlap,
        "fused_candidate_app_root": str(out_app),
        "fused_candidate_inventory_count": len(after_inventory),
        "fused_candidate_inventory_sha256": inventory_digest(after_inventory),
        "manager_source_operation_count": len(planned_source_paths),
        "source_changes_vs_stage_base": changed,
        "source_operations": source_checks,
        "owner_input_final_sources": [
            {"path": rel, "sha256": file_sha(out_app / rel)} for rel in sorted(r1_source_paths)
        ],
        "issue32_guard_paths": issue32_paths,
        "research_only_flags": {
            "RESEARCH_ONLY": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
        "service_or_live_state_changed": False,
    }
    write_json(RECEIPT, receipt)
    print(json.dumps({
        "status": receipt["status"],
        "fused_candidate_app_root": str(out_app),
        "stage_manifest_sha256": stage_manifest_sha,
        "stage_inventory_sha256": stage_inventory_sha,
        "fused_inventory_sha256": receipt["fused_candidate_inventory_sha256"],
        "source_change_count": len(changed),
        "stage_reviewed_source_count": len(stage_protected),
        "source_path_overlap": overlap,
        "receipt": str(RECEIPT),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FUSION_STOP:{type(exc).__name__}:{exc}", file=sys.stderr)
        raise
