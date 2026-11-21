"""Prepare the isolated R4 runtime candidate from frozen, hash-bound inputs."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil


TASK = Path(__file__).resolve().parent
BASE_TASK = TASK.parents[1] / "v4_main_r4_review_remediation_20261121" / "runtime"
BASE = BASE_TASK / "v4-main-r4-review-remediation-20261121"
RELEASE = TASK / "v4-main-r4-incremental-closure-20261122"
READBACK = TASK.parent / "private" / "DEPLOYED_MAIN_API_SOURCE_READBACK.json"
CARRYFORWARD = TASK.parent / "private" / "current_preimage" / "carryforward_app"
RUNTIME_INVENTORY_BASE = BASE_TASK / "FINAL_RUNTIME_INVENTORY.json"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def mode(path: Path) -> str:
    return format(path.stat().st_mode & 0o777, "04o")


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def rebase_runtime() -> dict:
    baseline = json.loads(RUNTIME_INVENTORY_BASE.read_bytes())
    base_entries = {row["path"]: row for row in baseline["entries"]}
    runtime = RELEASE / "runtime"
    changed = []
    for name in ("v4-mac", "v4-hk02"):
        relative = f"venvs/{name}/pyvenv.cfg"
        path = runtime / relative
        raw = path.read_bytes()
        old_root = str(BASE / "runtime").encode()
        new_root = str(runtime.resolve()).encode()
        if raw.count(old_root) < 1:
            raise RuntimeError("VENV_OLD_RUNTIME_ROOT_NOT_PRESENT:" + relative)
        updated = raw.replace(old_root, new_root)
        if updated == raw or old_root in updated:
            raise RuntimeError("VENV_RUNTIME_ROOT_REBASE_FAILED:" + relative)
        path.write_bytes(updated)
        changed.append({"path": relative, "before_sha256": hashlib.sha256(raw).hexdigest(),
                        "after_sha256": sha(path), "old_root_replacements": raw.count(old_root),
                        "candidate_runtime_root": str(runtime.resolve())})

    rows = []
    for directory, dirs, names in os.walk(runtime, followlinks=False):
        dirs.sort()
        for name in list(dirs):
            path = Path(directory) / name
            if path.is_symlink():
                rows.append({"path": path.relative_to(runtime).as_posix(), "kind": "symlink",
                             "target": os.readlink(path)})
                dirs.remove(name)
        for name in sorted(names):
            path = Path(directory) / name
            relative = path.relative_to(runtime).as_posix()
            info = path.lstat()
            if path.is_symlink():
                rows.append({"path": relative, "kind": "symlink", "target": os.readlink(path)})
            else:
                rows.append({"path": relative, "kind": "file", "sha256": sha(path),
                             "size": info.st_size, "mode": format(info.st_mode & 0o777, "04o")})
    rows.sort(key=lambda row: row["path"])
    old_paths, new_paths = set(base_entries), {row["path"] for row in rows}
    if old_paths != new_paths:
        raise RuntimeError("RUNTIME_PATH_SET_CHANGED")
    deltas = [{"path": key, "before": base_entries[key], "after": row}
              for key, row in ((row["path"], row) for row in rows)
              if base_entries[key] != row]
    if {row["path"] for row in deltas} != {"venvs/v4-mac/pyvenv.cfg", "venvs/v4-hk02/pyvenv.cfg"}:
        raise RuntimeError("RUNTIME_DELTA_OUTSIDE_VENV_REBASE")
    aggregate = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True,
                                          separators=(",", ":")).encode()).hexdigest()
    inventory = {"schema": "v4.r4_incremental_runtime_inventory.v1",
                 "root": str(runtime.resolve()), "entry_count": len(rows),
                 "aggregate_sha256": aggregate, "entries": rows}
    write_json(TASK / "FINAL_RUNTIME_INVENTORY.json", inventory)
    receipt = {"schema": "v4.r4_incremental_runtime_rebase.v1",
               "status": "PASS_COPIED_RUNTIME_REBASED_AND_FROZEN",
               "source_runtime": str((BASE / "runtime").resolve()),
               "candidate_runtime": str(runtime.resolve()),
               "source_runtime_inventory_sha256": baseline["aggregate_sha256"],
               "final_runtime_inventory_sha256": aggregate,
               "runtime_entry_count": len(rows), "exact_runtime_delta": deltas,
               "venv_metadata_rebases": changed,
               "candidate_python_sha256": sha(runtime / "venvs/v4-mac/bin/python"),
               "cpython_3_14_parent_site": "-S",
               "daemon_child_site": "enabled",
               "launcher_or_scheduler_started": False,
               "external_hk_python_invoked": False}
    write_json(TASK / "RUNTIME_REBASE_RECEIPT.json", receipt)
    return receipt


def carry_forward_authorized_sources() -> list[dict]:
    readback = json.loads(READBACK.read_bytes())
    changes = readback.get("current_app_delta_carryforward")
    if not isinstance(changes, list) or len(changes) != 2:
        raise RuntimeError("CARRYFORWARD_REVIEW_SCOPE_INVALID")
    output = []
    for item in changes:
        relative = item["path"]
        frozen_source = CARRYFORWARD / relative
        previous_candidate = BASE / "app" / relative
        target = RELEASE / "app" / relative
        if (sha(previous_candidate) != item["old_sha256"]
                or sha(frozen_source) != item["actual_new_sha256"]
                or mode(frozen_source) != "0400"):
            raise RuntimeError("CARRYFORWARD_PREIMAGE_OR_SOURCE_MISMATCH:" + relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(frozen_source, target)
        os.chmod(target, int(item["new_mode"], 8))
        if sha(target) != item["actual_new_sha256"] or mode(target) != item["new_mode"]:
            raise RuntimeError("CARRYFORWARD_COPY_MISMATCH:" + relative)
        output.append({"path": relative, "historical_candidate_sha256": item["old_sha256"],
                       "active_preimage_sha256": item["actual_new_sha256"],
                       "candidate_sha256": sha(target), "mode": mode(target)})
    return output


def bind_user_site_before_child() -> dict:
    path = RELEASE / "app/ops/run_v4_macos_scheduler_daemon.py"
    original = path.read_bytes()
    builder_old = (
        b'        PYTHONPYCACHEPREFIX=SOURCE_ONLY_PYCACHE_PREFIX,\n'
        b'        PYTHONDONTWRITEBYTECODE="1",\n'
        b'        V4_SOURCE_ONLY_PYCACHE_REQUIRED="1",\n'
    )
    builder_new = (
        b'        PYTHONPYCACHEPREFIX=SOURCE_ONLY_PYCACHE_PREFIX,\n'
        b'        PYTHONDONTWRITEBYTECODE="1",\n'
        b'        PYTHONNOUSERSITE="1",\n'
        b'        V4_SOURCE_ONLY_PYCACHE_REQUIRED="1",\n'
    )
    late_assignment = b'                    PYTHONNOUSERSITE="1",\n'
    if original.count(builder_old) != 1 or original.count(late_assignment) != 1:
        raise RuntimeError("DAEMON_CHILD_ENV_SOURCE_SHAPE_CHANGED")
    updated = original.replace(builder_old, builder_new).replace(late_assignment, b"")
    if updated == original:
        raise RuntimeError("DAEMON_CHILD_ENV_PATCH_EMPTY")
    path.write_bytes(updated)
    if mode(path) != "0644":
        raise RuntimeError("DAEMON_CHILD_ENV_MODE_CHANGED")
    return {"path": "ops/run_v4_macos_scheduler_daemon.py",
            "before_sha256": hashlib.sha256(original).hexdigest(),
            "after_sha256": sha(path), "mode": mode(path),
            "behavior": "_scheduler_child_invocation emits PYTHONNOUSERSITE=1 before Popen; duplicate late assignment removed"}


def main() -> None:
    if not BASE.is_dir() or not RELEASE.is_dir():
        raise RuntimeError("FROZEN_BASE_OR_APFS_CLONE_MISSING")
    freeze = json.loads((BASE_TASK / "CANDIDATE_FREEZE_RECEIPT.json").read_bytes())
    if (freeze.get("status") != "PASS_ISOLATED_CANDIDATE_CONTROLS"
            or freeze.get("release_id") != BASE.name):
        raise RuntimeError("FROZEN_BASE_RECEIPT_MISMATCH")
    carry = carry_forward_authorized_sources()
    daemon = bind_user_site_before_child()
    runtime = rebase_runtime()
    receipt = {"schema": "v4.r4_incremental_runtime_prepare_receipt.v1",
               "status": "PASS_ISOLATED_RUNTIME_CANDIDATE_PREPARED",
               "base_release_root": str(BASE), "candidate_release_root": str(RELEASE),
               "base_freeze_receipt_sha256": sha(BASE_TASK / "CANDIDATE_FREEZE_RECEIPT.json"),
               "base_release_manifest_sha256": sha(BASE / "release-manifest.json"),
               "authorized_active_preimage_carryforward": carry,
               "daemon_child_environment_change": daemon,
               "runtime_rebase_receipt_sha256": sha(TASK / "RUNTIME_REBASE_RECEIPT.json"),
               "runtime_inventory_sha256": runtime["final_runtime_inventory_sha256"],
               "production_write": False, "launchctl_called": False,
               "scheduler_or_provider_started": False,
               "registry_or_CURRENT_mutated": False, "old_reservations_changed": False}
    write_json(TASK / "RUNTIME_PREPARATION_RECEIPT.json", receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
