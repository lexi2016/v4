"""Controller-only staging / binding CAS / rollback. Never starts or stops jobs.

Invoke only after independent PASS. Writing plist bytes does not reload launchd.
The API candidate remains SOURCE_ONLY until the controller verifies its runtime
dependency closure and performs the separate authorized API lifecycle cutover.
Switch API/graph freshness together at activation. Main scheduler is excluded.
This CLI stages and switches only graph/daily/deadline. The API proposal is
input to the controller's separately reviewed UI/API composition release.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import time
import uuid

from prepare_integration import CASE, inventory


def sha(data):
    return hashlib.sha256(data).hexdigest()


@contextmanager
def owned_lock():
    with (CASE / "integration/switch.lock").open("a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def cas_replace(target, expected_sha256, replacement, backup):
    """SHA CAS under this batch's exclusive lock, atomic replace, exact backup.

    The caller owns the lock. Noncooperating plist editors are detected by a
    second inode/mtime/SHA check immediately before the atomic rename.
    """
    target, backup = Path(target), Path(backup)
    before = target.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ValueError("TARGET_NOT_SINGLE_REGULAR_FILE")
    original = target.read_bytes()
    if sha(original) != expected_sha256:
        raise ValueError("CAS_SHA_MISMATCH:" + str(target))
    with backup.open("xb") as handle:
        handle.write(original)
        handle.flush()
        os.fsync(handle.fileno())
    temp = target.parent / ("." + target.name + ".schedule-" + uuid.uuid4().hex)
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IMODE(before.st_mode))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(replacement)
            handle.flush()
            os.fsync(handle.fileno())
        after = target.lstat()
        if (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_size) != (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_size) or sha(target.read_bytes()) != expected_sha256:
            raise ValueError("CAS_CONCURRENT_CHANGE:" + str(target))
        os.replace(temp, target)
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        if sha(target.read_bytes()) != sha(replacement):
            raise ValueError("POST_REPLACE_SHA_MISMATCH")
    finally:
        if temp.exists():
            temp.unlink()  # only this invocation's own uncommitted temp


def wait_natural_exit(label, timeout_seconds, *, run=subprocess.run, sleep=time.sleep):
    deadline = time.monotonic() + timeout_seconds
    while True:
        check = run(["/bin/launchctl", "print", f"gui/{os.getuid()}/{label}"], text=True, capture_output=True, timeout=10)
        if check.returncode:
            # An unknown launchctl failure must not be treated as an idle job.
            if "Could not find service" in check.stderr or "Could not find service" in check.stdout:
                return {"label": label, "state": "NOT_LOADED"}
            raise RuntimeError("LAUNCHCTL_STATE_UNAVAILABLE:" + label)
        pid = re.search(r"^\s*pid = (\d+)\s*$", check.stdout, re.MULTILINE)
        if pid is None:
            if "state = running" in check.stdout:
                raise RuntimeError("RUNNING_WITHOUT_PID:" + label)
            return {"label": label, "state": "NATURALLY_IDLE"}
        if time.monotonic() >= deadline:
            raise RuntimeError(f"HEALTHY_PROCESS_STILL_RUNNING:{label}:pid={pid.group(1)}")
        sleep(min(1, max(0, deadline - time.monotonic())))


def reviewed_inputs(receipt):
    files = {"scope_sha256": CASE / "BATCH1_SCOPE.json", "binding_plan_sha256": CASE / "integration/BINDING_PLAN.json",
             "source_diff_manifest_sha256": CASE / "SOURCE_DIFF_MANIFEST.json"}
    if receipt.get("verdict") != "PASS" or not receipt.get("reviewer") or receipt.get("writer") == receipt.get("reviewer"):
        raise ValueError("INDEPENDENT_PASS_REQUIRED")
    for key, path in files.items():
        if receipt.get(key) != sha(path.read_bytes()):
            raise ValueError("REVIEWED_INPUT_DRIFT:" + key)
    source_manifest = json.loads(files["source_diff_manifest_sha256"].read_text())
    for support in source_manifest["support_files"]:
        if sha(Path(support["path"]).read_bytes()) != support["sha256"]:
            raise ValueError("REVIEWED_SUPPORT_FILE_DRIFT")
    plan = json.loads(files["binding_plan_sha256"].read_text())
    for release in plan["releases"]:
        manifest = Path(release["manifest"])
        if sha(manifest.read_bytes()) != release["manifest_sha256"]:
            raise ValueError("RELEASE_MANIFEST_DRIFT")
        if inventory(Path(release["source_app"])) != json.loads(manifest.read_text())["app_files"]:
            raise ValueError("CANDIDATE_SOURCE_DRIFT")
        if sha(Path(release["baseline_manifest"]).read_bytes()) != release["baseline_manifest_sha256"]:
            raise ValueError("BASELINE_DEPENDENCY_MANIFEST_DRIFT")
    if sha(Path(plan["stage_config"]).read_bytes()) != plan["stage_config_sha256"]:
        raise ValueError("STAGE_CONFIG_DRIFT")
    for operation in plan["operations"]:
        for key, expected in [("proposed", "proposed_sha256"), ("baseline", "expected_sha256")]:
            if sha(Path(operation[key]).read_bytes()) != operation[expected]:
                raise ValueError("PLIST_PROPOSAL_DRIFT")
    return plan


def stage_releases(plan):
    staged = []
    for release in plan["releases"]:
        target = Path(release["destination"])
        if target.exists():
            manifest = target / 'release-manifest.json'
            expected = json.loads(Path(release['manifest']).read_text())
            if not manifest.is_file() or sha(manifest.read_bytes()) != release['manifest_sha256'] or inventory(target / 'app') != expected['app_files']:
                raise ValueError("EXISTING_IMMUTABLE_RELEASE_DRIFT:" + str(target))
            staged.append(str(target))
            continue  # exact existing immutable stage; no overwrite or copy
        staging = target.with_name(target.name + ".preparing-" + uuid.uuid4().hex)
        staging.mkdir()
        # Keep symlinks as dependencies. Never follow them with a source edit.
        shutil.copytree(release["source_app"], staging / "app", symlinks=True)
        manifest = json.loads(Path(release["manifest"]).read_text())
        if inventory(staging / "app") != manifest["app_files"]:
            raise ValueError("STAGED_COPY_MISMATCH:" + str(staging))
        shutil.copy2(release["manifest"], staging / "release-manifest.json")
        os.rename(staging, target)
        staged.append(str(target))
    return staged


def one_shot_plan(plan):
    return {**plan, "releases":[row for row in plan["releases"] if row["component"] == "graph"],
            "operations":[row for row in plan["operations"] if row["role"] == "graph"]}


def switch_bindings(plan, *, rollback, wait_seconds, journal_root=CASE / "integration"):
    # Preflight every compare before the first mutation. Keep a per-operation
    # journal as multi-plist replacement cannot be one filesystem transaction.
    pending = []
    for operation in plan["operations"]:
        expected = operation["proposed_sha256"] if rollback else operation["expected_sha256"]
        actual = sha(Path(operation["target"]).read_bytes())
        if not rollback and actual == operation['proposed_sha256']:
            continue  # exact plist bytes already CAS-installed; do not rewrite
        if rollback and actual == operation["expected_sha256"]:
            continue  # this member was never applied (or already restored)
        if actual != expected:
            raise ValueError("PREFLIGHT_CAS_MISMATCH:" + operation["label"])
        pending.append(operation)
    waits = [wait_natural_exit(op["label"], wait_seconds) for op in pending if op["wait_for_natural_exit"]]
    if not rollback:
        for release in plan["releases"]:
            target = Path(release["destination"])
            if not (target / "release-manifest.json").is_file() or sha((target / "release-manifest.json").read_bytes()) != release["manifest_sha256"]:
                raise ValueError("STAGED_RELEASE_NOT_VERIFIED")
    run = journal_root / ("rollback-" if rollback else "apply-")
    run = run.with_name(run.name + uuid.uuid4().hex)
    run.mkdir()
    journal = {"status": "IN_PROGRESS", "rollback": rollback, "waits": waits, "operations": [], "service_actions": 0}
    for op in pending:
        expected = op["proposed_sha256"] if rollback else op["expected_sha256"]
        replacement = Path(op["baseline"] if rollback else op["proposed"]).read_bytes()
        backup = run / (op["label"] + ".before.plist")
        cas_replace(op["target"], expected, replacement, backup)
        journal["operations"].append({"label": op["label"], "backup": str(backup), "after_sha256": sha(replacement)})
        (run / "journal.json").write_text(json.dumps(journal, indent=2) + "\n")
    journal.update(status="PLIST_BYTES_INSTALLED_RELOAD_PENDING", main_scheduler_reload=False,
                   api_status="SOURCE_ONLY_CONTROLLER_RUNTIME_ACCEPTANCE_REQUIRED", healthy_tasks_stopped=0)
    (run / "journal.json").write_text(json.dumps(journal, indent=2) + "\n")
    return journal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stage", "apply", "rollback"))
    parser.add_argument("--review-receipt", required=True, type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--wait-seconds", type=float, default=45)
    args = parser.parse_args()
    if not args.execute or not 0 <= args.wait_seconds <= 60:
        raise ValueError("EXPLICIT_EXECUTE_AND_BOUNDED_WAIT_REQUIRED")
    plan = one_shot_plan(reviewed_inputs(json.loads(args.review_receipt.read_text())))
    with owned_lock():
        result = stage_releases(plan) if args.action == "stage" else switch_bindings(plan, rollback=args.action == "rollback", wait_seconds=args.wait_seconds)
    print(json.dumps({"action": args.action, "result": result, "service_actions": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
