#!/usr/bin/env python3
"""Promote an accepted app unchanged; controller-only activation and rollback.

--prepare never mutates a service or the live plist. --activate and --rollback
hold the existing API release mutex and require the preparation receipt SHA.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import tempfile
import time

from ops.prepare_tech_debt_candidate import assert_no_cache, sha, validate_copy, validate_source_identity

SOURCE = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "d3dfefdf89d6cc5220f428b6656f140afb94ac97"
HOME_ROOT = Path("/Users/lexi")
CANDIDATES = HOME_ROOT / "Library/Application Support/com.lexi.v4.local/candidates"
TARGET = CANDIDATES / "tech-debt-entity-filter-20261101-r1"
PLIST = HOME_ROOT / "Library/LaunchAgents/com.lexi.v4.api.plist"
ACCEPTED = Path("/private/tmp/v4-isolated-acceptance-20261101-writer-r1/candidate")
ACCEPTED_SHA = "12e55bec59a077257ba0a0aa4403fab806ae07a5cfb06b5bacd4d77c85dd9b79"
INVENTORY_SHA = "d685ec81693ce11135704d39096eec6fd694ed0744f5a7e352b32a1c4a5d0839"
REVIEW = Path("/private/tmp/v4-isolated-acceptance-20261101/controller/reviewer-final.json")
REVIEW_SHA = "41c3a91834d7796cb8506ade0522847b794a8328913ec30ff7918f933203f091"
TOOLS_SHA = "35ac1a9b6f3ea885b2788a9476dbc2f4dc21f42f43a359b63a0c22265c1fd154"
PIN_NAMES = ("V4_APP_ROOT", "V4_RELEASE_ID", "V4_RELEASE_MANIFEST_PATH", "V4_RELEASE_MANIFEST_SHA256")
LEGACY = SOURCE / "docs/handoffs/perf-runtime-repair-20261101/release_repair.py"


def write_json(path: Path, value) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_tools(base: Path):
    path = base / "app/ops/api_release_integration.py"
    if sha(path.read_bytes()) != TOOLS_SHA:
        raise ValueError("OFFICIAL_INVENTORY_TOOL_DRIFT")
    return load_module("promotion_official_inventory", path)


def release_files(root: Path, expected_sha: str, tools):
    tools._exact_path(root, kind="directory", label="PROMOTION_ROOT")
    path = tools._exact_path(root / "release-manifest.json", kind="file", label="PROMOTION_MANIFEST")
    raw = path.read_bytes()
    if sha(raw) != expected_sha:
        raise ValueError("MANIFEST_CAS_CHANGED")
    manifest = json.loads(raw)
    expected = {"root": str(root), "app_root": str(root / "app"), "release_id": root.name, "module_role": "api"}
    if manifest.get("schema_version") != "v4.release_candidate.v1" or manifest.get("candidate") != expected:
        raise ValueError("MANIFEST_PATH_IDENTITY_MISMATCH")
    if any(manifest.get(key) is not False for key in ("production_allowed", "buy_gate_updated", "orders_sent")) or manifest.get("RESEARCH_ONLY") is not True:
        raise ValueError("MANIFEST_SAFETY_FLAGS_INVALID")
    inventory = tools.inventory_tree(root / "app")
    if manifest.get("application_inventory") != {"entries": inventory, "entry_count": len(inventory), "aggregate_sha256": tools.inventory_digest(inventory)} or manifest.get("app_files") != inventory:
        raise ValueError("FULL_INVENTORY_MISMATCH")
    return manifest, inventory


def staged_payload(original: dict, target: Path, manifest_sha: str) -> dict:
    payload = copy.deepcopy(original)
    payload["WorkingDirectory"] = str(target / "app")
    payload["EnvironmentVariables"].update(V4_APP_ROOT=str(target / "app"), V4_RELEASE_ID=target.name,
        V4_RELEASE_MANIFEST_PATH=str(target / "release-manifest.json"), V4_RELEASE_MANIFEST_SHA256=manifest_sha)
    return payload


def assert_plist_delta(original: dict, staged: dict, target: Path, manifest_sha: str) -> None:
    if staged != staged_payload(original, target, manifest_sha):
        raise ValueError("STAGED_PLIST_NON_IDENTITY_CHANGE")


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def owned_job_matches(observed, expected) -> bool:
    """An owned loaded job may lose its PID; a replacement PID is refused."""
    return (expected is not None and observed is not None
            and observed["plist_sha256"] == expected["plist_sha256"]
            and (observed["pid"] is None or expected["pid"] is None
                 or observed["pid"] == expected["pid"]))


class Deployment:
    def __init__(self, target: Path, base: Path):
        self.target, self.base = target, base
        self.legacy = load_module("promotion_lifecycle", LEGACY)
        # Only these low-level helpers are reused. Never execute the old
        # helper's preflight/prepare/switch or its stale release/plist pins.
        self.legacy.BASE, self.legacy.PLIST = base, PLIST
        self.legacy.DOMAIN = f"gui/{os.getuid()}"
        self.legacy.JOB = self.legacy.DOMAIN + "/com.lexi.v4.api"
        self.started_job = None

    def job(self, raw: bytes, *, allow_missing=False, allow_no_pid=False):
        result = self.legacy.launchctl("print", self.legacy.JOB)
        if result.returncode:
            if allow_missing and "Could not find service" in result.stderr:
                return None
            raise ValueError("JOB_STATE_UNKNOWN:" + result.stderr)
        payload = plistlib.loads(raw)
        expected = {"path": str(PLIST), "program": payload["ProgramArguments"][0],
                    "working directory": payload["WorkingDirectory"]}
        for name, value in expected.items():
            if not re.search(r"^\s*" + re.escape(name) + r" = " + re.escape(value) + r"\s*$", result.stdout, re.M):
                raise ValueError("JOB_IDENTITY_MISMATCH:" + name)
        for name in PIN_NAMES:
            value = payload["EnvironmentVariables"][name]
            if not re.search(r"^\s*" + name + r" => " + re.escape(value) + r"\s*$", result.stdout, re.M):
                raise ValueError("JOB_ENVIRONMENT_MISMATCH:" + name)
        match = re.search(r"^\s*pid = (\d+)\s*$", result.stdout, re.M)
        if not match and not allow_no_pid:
            raise ValueError("JOB_PID_MISSING")
        return {"pid": int(match.group(1)) if match else None, "plist_sha256": sha(raw)}

    def assert_pointer(self, expected: bytes, mode: int) -> None:
        if PLIST.is_symlink() or PLIST.read_bytes() != expected or PLIST.stat().st_mode & 0o777 != mode:
            raise ValueError("ACTIVE_PLIST_CAS_CHANGED")

    def unload(self, expected_job, raw: bytes) -> None:
        current = self.job(raw, allow_missing=True, allow_no_pid=expected_job is not None)
        if current is not None and not owned_job_matches(current, expected_job):
            raise ValueError("EXTERNAL_JOB_CHANGED_BEFORE_UNLOAD")
        old_pid = (expected_job["pid"] or (current or {}).get("pid")) if expected_job else None
        if current is not None:
            result = self.legacy.launchctl("bootout", self.legacy.JOB)
            if result.returncode:
                raise RuntimeError("BOOTOUT_FAILED:" + result.stderr)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            current = self.job(raw, allow_missing=True, allow_no_pid=expected_job is not None)
            if current is not None and not owned_job_matches(current, expected_job):
                raise ValueError("EXTERNAL_JOB_CHANGED_DURING_UNLOAD")
            if current is None and not self.legacy.listener_present() and (old_pid is None or not pid_alive(old_pid)):
                return
            time.sleep(0.2)
        raise RuntimeError("UNLOAD_JOB_SOCKET_OR_PID_TIMEOUT; no bootstrap attempted")

    def start_and_validate(self, raw: bytes):
        self.started_job = None
        result = self.legacy.launchctl("bootstrap", self.legacy.DOMAIN, str(PLIST))
        if result.returncode:
            raise RuntimeError("BOOTSTRAP_FAILED:" + result.stderr)
        # A successful bootstrap owns this exact loaded job configuration even
        # if launchd never exposes a PID (immediate exit or throttled restart).
        self.started_job = {"pid": None, "plist_sha256": sha(raw)}
        env = plistlib.loads(raw)["EnvironmentVariables"]
        deadline, last = time.monotonic() + 30, None
        while time.monotonic() < deadline:
            try:
                job = self.job(raw, allow_no_pid=True)
                if not owned_job_matches(job, self.started_job):
                    raise RuntimeError("EXTERNAL_JOB_CHANGED_DURING_START")
                if job["pid"] is None:
                    last = "OWNED_LOADED_JOB_WITHOUT_PID"
                    time.sleep(0.3)
                    continue
                self.started_job = job  # Retain the last observed PID on exit.
                # Existing minimal API gates: owned socket PID, healthz 200,
                # safety flags, and MANIFEST_EXECUTION_FILES_VERIFIED identity.
                self.legacy.assert_live(env["V4_RELEASE_ID"], env["V4_RELEASE_MANIFEST_SHA256"], frontend=False)
                return job
            except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
                last = repr(error)
                time.sleep(0.3)
        raise RuntimeError("READINESS_TIMEOUT:" + str(last))


def prepare(target: Path) -> dict:
    if target.parent != CANDIDATES or not target.name.startswith("tech-debt-entity-filter-20261101-") or target.exists() or target.is_symlink():
        raise ValueError("PROMOTION_TARGET_MUST_BE_NEW_OWNED_CANDIDATE")
    source_identity = validate_source_identity(SOURCE)
    if subprocess.check_output(["git", "merge-base", SOURCE_COMMIT, source_identity["packaging_source_commit"]], cwd=SOURCE, text=True).strip() != SOURCE_COMMIT:
        raise ValueError("PREPARATION_SOURCE_NOT_DESCENDANT")
    review_raw = REVIEW.read_bytes()
    if sha(review_raw) != REVIEW_SHA:
        raise ValueError("ACCEPTED_REVIEW_CAS_CHANGED")
    review = json.loads(review_raw)
    if review.get("status") != "REVIEWED/PASS" or review.get("candidate_manifest_sha256") != ACCEPTED_SHA:
        raise ValueError("ACCEPTED_REVIEW_NOT_PASS")
    original = PLIST.read_bytes()
    mode = PLIST.stat().st_mode & 0o777
    payload = plistlib.loads(original)
    env = payload["EnvironmentVariables"]
    base = Path(env["V4_APP_ROOT"]).parent
    if payload["WorkingDirectory"] != str(base / "app") or env["V4_RELEASE_ID"] != base.name or env["V4_RELEASE_MANIFEST_PATH"] != str(base / "release-manifest.json"):
        raise ValueError("LIVE_PLIST_RELEASE_IDENTITY_INVALID")
    tools = load_tools(base)
    _, base_inventory = release_files(base, env["V4_RELEASE_MANIFEST_SHA256"], tools)
    accepted, inventory = release_files(ACCEPTED, ACCEPTED_SHA, tools)
    if len(inventory) != 1324 or tools.inventory_digest(inventory) != INVENTORY_SHA:
        raise ValueError("ACCEPTED_INVENTORY_PIN_MISMATCH")
    assert_no_cache(ACCEPTED / "app")
    deployment = Deployment(target, base)
    deployment.assert_pointer(original, mode)
    old_job = deployment.job(original)
    deployment.legacy.assert_live(env["V4_RELEASE_ID"], env["V4_RELEASE_MANIFEST_SHA256"], frontend=False)
    if shutil.disk_usage(target.parent).free < sum(int(item.get("size", 0)) for item in inventory) * 2 + 1024 ** 3:
        raise ValueError("INSUFFICIENT_PROMOTION_SPACE")
    target.mkdir(mode=0o700)
    (target / "config").mkdir(mode=0o700)
    (target / "evidence").mkdir(mode=0o700)
    shutil.copytree(ACCEPTED / "app", target / "app", symlinks=True)
    if tools.inventory_tree(target / "app") != inventory:
        raise ValueError("PROMOTED_APP_BYTES_DRIFT")
    manifest = copy.deepcopy(accepted)
    manifest["candidate"] = {"root": str(target), "app_root": str(target / "app"), "release_id": target.name, "module_role": "api"}
    manifest.update(release_id=target.name, app_root=str(target / "app"), source_commit=SOURCE_COMMIT,
        source_root=str(SOURCE), activation_status="PREPARED_NOT_ACTIVATED", deployment_status="NOT_DEPLOYED")
    manifest["source_provenance"] = {"packaging_source_commit": source_identity["packaging_source_commit"],
        "accepted_packaging_source_commit": SOURCE_COMMIT,
        "accepted_business_source_commit": accepted["source_commit"], "accepted_manifest_path": str(ACCEPTED / "release-manifest.json"),
        "accepted_manifest_sha256": ACCEPTED_SHA, "accepted_inventory_sha256": INVENTORY_SHA,
        "independent_review_path": str(REVIEW), "independent_review_sha256": REVIEW_SHA,
        "accepted_source_provenance": accepted.get("source_provenance"), "promotion": "IDENTITY_REBIND_ONLY_APP_BYTES_UNCHANGED"}
    manifest_path = target / "release-manifest.json"
    write_json(manifest_path, manifest)
    manifest_sha = sha(manifest_path.read_bytes())
    staged = plistlib.dumps(staged_payload(payload, target, manifest_sha))
    assert_plist_delta(payload, plistlib.loads(staged), target, manifest_sha)
    backup_path, staged_path = target / "config/original-api.plist", target / "config/staged-api.plist"
    for path, raw in ((backup_path, original), (staged_path, staged)):
        path.write_bytes(raw)
        path.chmod(mode)
    identity = validate_copy(target, tools)
    deployment.assert_pointer(original, mode)
    if deployment.job(original) != old_job:
        raise ValueError("LIVE_JOB_CHANGED_DURING_PREPARE")
    receipt = {"schema_version": "v4.tech_debt_promotion.v1", "status": "PREPARED_NOT_ACTIVATED",
        "target": str(target), "base": str(base), "plist_path": str(PLIST), "plist_mode": mode,
        "base_plist_sha256": sha(original), "staged_plist_sha256": sha(staged), "base_job": old_job,
        "base_manifest_sha256": env["V4_RELEASE_MANIFEST_SHA256"], "manifest_sha256": manifest_sha,
        "accepted_manifest_sha256": ACCEPTED_SHA, "review_sha256": REVIEW_SHA,
        "inventory_sha256": INVENTORY_SHA, "base_inventory_sha256": tools.inventory_digest(base_inventory),
        "activation_tool_sha256": sha(Path(__file__).read_bytes()), "lifecycle_tool_sha256": sha(LEGACY.read_bytes()),
        "identity": identity, "source_commit": SOURCE_COMMIT,
        "plist_changed_paths": ["WorkingDirectory"] + ["EnvironmentVariables." + name for name in PIN_NAMES],
        "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    write_json(target / "preparation.json", receipt)
    return {"status": receipt["status"], "target": str(target), "manifest_sha256": manifest_sha,
        "preparation_sha256": sha((target / "preparation.json").read_bytes()), "staged_plist_sha256": sha(staged), "backup_plist_sha256": sha(original)}


def load_prepared(target: Path, receipt_sha: str, *, allow_tool_revision=False):
    path = target / "preparation.json"
    if sha(path.read_bytes()) != receipt_sha:
        raise ValueError("PREPARATION_RECEIPT_CAS_CHANGED")
    receipt = json.loads(path.read_bytes())
    if receipt.get("target") != str(target) or receipt.get("plist_path") != str(PLIST):
        raise ValueError("PREPARATION_PATH_IDENTITY_INVALID")
    if (not allow_tool_revision and sha(Path(__file__).read_bytes()) != receipt["activation_tool_sha256"]) or sha(LEGACY.read_bytes()) != receipt["lifecycle_tool_sha256"]:
        raise ValueError("DEPLOYMENT_TOOL_DRIFT")
    old_path, new_path = target / "config/original-api.plist", target / "config/staged-api.plist"
    old, new = old_path.read_bytes(), new_path.read_bytes()
    if sha(old) != receipt["base_plist_sha256"] or sha(new) != receipt["staged_plist_sha256"] or any(p.stat().st_mode & 0o777 != receipt["plist_mode"] for p in (old_path, new_path)):
        raise ValueError("PREPARED_PLIST_BYTES_OR_MODE_DRIFT")
    assert_plist_delta(plistlib.loads(old), plistlib.loads(new), target, receipt["manifest_sha256"])
    base = Path(receipt["base"])
    tools = load_tools(base)
    release_files(base, receipt["base_manifest_sha256"], tools)
    _, inventory = release_files(target, receipt["manifest_sha256"], tools)
    if tools.inventory_digest(inventory) != receipt["inventory_sha256"]:
        raise ValueError("PROMOTED_INVENTORY_DRIFT")
    assert_no_cache(target / "app")
    validate_copy(target, tools)
    return receipt, old, new


def revise_preparation(target: Path, old_sha: str):
    """CAS-update only the tool pin of a still-inactive prepared candidate."""
    receipt, old, _ = load_prepared(target, old_sha, allow_tool_revision=True)
    if receipt.get("status") != "PREPARED_NOT_ACTIVATED" or list((target / "evidence").glob("activation-*.json")):
        raise ValueError("PREPARATION_REVISION_REQUIRES_UNACTIVATED_CANDIDATE")
    deployment = Deployment(target, Path(receipt["base"]))
    deployment.assert_pointer(old, receipt["plist_mode"])
    if deployment.job(old) != receipt["base_job"]:
        raise ValueError("ACTIVE_JOB_CAS_CHANGED")
    path = target / "preparation.json"
    raw = path.read_bytes()
    if sha(raw) != old_sha:
        raise ValueError("PREPARATION_RECEIPT_CAS_CHANGED")
    backup = target / "evidence" / ("preparation-before-revision-" + old_sha[:16])
    backup.mkdir(mode=0o700)  # Never overwrite a prior revision's evidence.
    for original in (path, target / "release-manifest.json", target / "config/staged-api.plist", target / "config/original-api.plist"):
        shutil.copy2(original, backup / original.name)
    revised = copy.deepcopy(receipt)
    revised["activation_tool_sha256"] = sha(Path(__file__).read_bytes())
    revised["metadata_revision"] = {"previous_preparation_sha256": old_sha,
        "previous_activation_tool_sha256": receipt["activation_tool_sha256"],
        "backup_root": str(backup), "reason": "OWNED_LOADED_NO_PID_ROLLBACK_FIX",
        "application_and_manifest_changed": False}
    new_raw = (json.dumps(revised, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    deployment.assert_pointer(old, receipt["plist_mode"])
    if deployment.job(old) != receipt["base_job"] or path.read_bytes() != raw:
        raise ValueError("PREPARATION_OR_ACTIVE_JOB_CAS_CHANGED")
    with tempfile.NamedTemporaryFile(dir=target, prefix=".preparation-revision-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(new_raw)
            stream.flush()
            os.fsync(stream.fileno())
            temporary.chmod(path.stat().st_mode & 0o777)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return {"status": "PREPARATION_METADATA_REVISED_NOT_ACTIVATED", "target": str(target),
        "preparation_sha256": sha(path.read_bytes()), "previous_preparation_sha256": old_sha,
        "manifest_sha256": receipt["manifest_sha256"], "backup_root": str(backup)}


def switch(target: Path, receipt_sha: str, *, rollback=False, activation_sha=None):
    # Read once to locate the existing release lock; revalidate under the lock.
    raw_receipt = (target / "preparation.json").read_bytes()
    if sha(raw_receipt) != receipt_sha:
        raise ValueError("PREPARATION_RECEIPT_CAS_CHANGED")
    receipt = json.loads(raw_receipt)
    deployment = Deployment(target, Path(receipt["base"]))
    with deployment.legacy.release_lock():
        receipt, old, new = load_prepared(target, receipt_sha)
        previous, desired = (new, old) if rollback else (old, new)
        expected_job = receipt["base_job"]
        if rollback:
            activation_path = target / "evidence/activation-success.json"
            if not activation_sha or sha(activation_path.read_bytes()) != activation_sha:
                raise ValueError("ACTIVATION_RECEIPT_CAS_CHANGED")
            activated = json.loads(activation_path.read_bytes())
            if activated.get("preparation_sha256") != receipt_sha or activated.get("status") != "ACTIVATED_VERIFIED":
                raise ValueError("ACTIVATION_RECEIPT_INVALID")
            expected_job = activated["job"]
        deployment.assert_pointer(previous, receipt["plist_mode"])
        if deployment.job(previous) != expected_job:
            raise ValueError("ACTIVE_JOB_CAS_CHANGED")
        phase = "rollback" if rollback else "activation"
        try:
            deployment.unload(expected_job, previous)
            deployment.assert_pointer(previous, receipt["plist_mode"])
            deployment.legacy.atomic_plist(desired)
            deployment.assert_pointer(desired, receipt["plist_mode"])
            new_job = deployment.start_and_validate(desired)
            result = {"status": "ROLLBACK_VERIFIED" if rollback else "ACTIVATED_VERIFIED",
                      "job": new_job, "preparation_sha256": receipt_sha}
            result_path = target / f"evidence/{phase}-success.json"
            write_json(result_path, result)
            return {**result, "result_path": str(result_path), "result_sha256": sha(result_path.read_bytes())}
        except BaseException as primary:
            try:
                current = PLIST.read_bytes()
                if current not in (previous, desired):
                    raise ValueError("AUTOMATIC_ROLLBACK_PLIST_CAS_CONFLICT")
                deployment.assert_pointer(current, receipt["plist_mode"])
                # Only stop the original job or the exact PID started by this
                # attempt. A foreign replacement is never an owned rollback.
                allowed_job = deployment.started_job if current == desired else expected_job
                observed = deployment.job(current, allow_missing=True, allow_no_pid=allowed_job is not None)
                if observed is not None and not owned_job_matches(observed, allowed_job):
                    raise ValueError("AUTOMATIC_ROLLBACK_JOB_CAS_CONFLICT")
                deployment.unload(allowed_job, current)
                deployment.assert_pointer(current, receipt["plist_mode"])
                deployment.legacy.atomic_plist(previous)
                restored_job = deployment.start_and_validate(previous)
                recovery = {"status": "AUTOMATIC_ROLLBACK_VERIFIED", "job": restored_job}
            except BaseException as secondary:
                recovery = {"status": "AUTOMATIC_ROLLBACK_FAILED", "error": repr(secondary)}
            failure = {"status": "CUTOVER_FAILED", "phase": phase, "error": repr(primary),
                       "recovery": recovery, "preparation_sha256": receipt_sha}
            write_json(target / f"evidence/{phase}-failure-{time.time_ns()}.json", failure)
            raise RuntimeError(f"{primary!r}; {recovery['status']}") from primary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    for name in ("prepare", "revise-preparation", "activate", "rollback"):
        actions.add_argument("--" + name, action="store_true")
    parser.add_argument("--target", type=Path, default=TARGET)
    parser.add_argument("--receipt-sha256")
    parser.add_argument("--activation-sha256")
    args = parser.parse_args(argv)
    target = args.target.expanduser().absolute()
    if args.prepare:
        result = prepare(target)
    elif args.revise_preparation:
        if not args.receipt_sha256:
            parser.error("--receipt-sha256 must pin the old preparation for revision")
        result = revise_preparation(target, args.receipt_sha256)
    else:
        if not args.receipt_sha256:
            parser.error("--receipt-sha256 is required for activate/rollback")
        result = switch(target, args.receipt_sha256, rollback=args.rollback, activation_sha=args.activation_sha256)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
