#!/usr/bin/env python3
"""Switch the reviewed supplement candidate under the existing API release lock.

Edan order: bootout -> absent job AND clear socket -> CAS/atomic plist ->
bootstrap -> retry identity. Recovery only touches the exact process/plist
owned by this attempt. This entry point performs a production service switch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

LOCAL = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local")
LIVE_PLIST = Path.home() / "Library/LaunchAgents/com.lexi.v4.api.plist"
LABEL = "com.lexi.v4.api"
UID = os.getuid()
JOB = f"gui/{UID}/{LABEL}"
DOMAIN = f"gui/{UID}"
MARKER = "main-CzmllJyl.js"
LOCK_APP = LOCAL / "candidates/edan-single-20261102-b843699e8d3371ea/app"
LOCK_FILES = {
    "infrastructure/interprocess_lock.py": "9b0cb80a1fe1bcbdebb3936134c8f0bad258c9c9236356022551ff7753351df0",
    "infrastructure/owned_io.py": "9a74731287ca7c9667643557d4ae42f63453a025665ba28f5b65fdbff7d54ee0",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def checked(path: Path, expected_sha: str) -> bytes:
    raw = path.read_bytes()
    if sha256_bytes(raw) != expected_sha:
        raise ValueError("PLIST_OR_INPUT_CAS_CHANGED:" + str(path))
    return raw


def release_lock():
    # Same kernel mutex and legacy-owner protocol as junda_single_release.py.
    for relative, expected in LOCK_FILES.items():
        checked(LOCK_APP / relative, expected)
    sys.path.insert(0, str(LOCK_APP))
    from infrastructure.interprocess_lock import owned_interprocess_lock
    return owned_interprocess_lock(LIVE_PLIST.with_name(".com.lexi.v4.api.release.lock"),
                                   timeout_seconds=2, timeout_message="API_RELEASE_SHARED_LOCK_BUSY")


def launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["/bin/launchctl", *args], text=True, capture_output=True, timeout=15)


def port_listening(port: int = 8873) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def process_info() -> dict:
    out = launchctl("list")
    if out.returncode:
        raise RuntimeError("PROCESS_STATE_UNKNOWN:" + out.stderr)
    for line in out.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[2] == LABEL:
            return {"pid": parts[0], "last_exit": parts[1]}
    return {"pid": "-", "last_exit": "unknown"}


def service_state() -> tuple[str, dict | None]:
    result = launchctl("print", JOB)
    if result.returncode == 0:
        return "running", process_info()
    if "Could not find service" not in result.stderr:
        raise RuntimeError("JOB_STATE_UNKNOWN:" + result.stderr)
    if port_listening():
        raise RuntimeError("UNOWNED_LISTENER")
    return "stopped", None


def verify_release(expected_id: str, expected_marker: str | None = None,
                   expected_manifest_sha: str | None = None) -> dict:
    with urllib.request.urlopen("http://127.0.0.1:8873/api/v1/runs/date-list?date=20261102", timeout=5) as resp:
        identity = (json.loads(resp.read()) or {}).get("runtime_identity") or {}
    with urllib.request.urlopen("http://127.0.0.1:8873/", timeout=5) as resp:
        index = resp.read().decode("utf-8", "replace")
    marker_ok = expected_marker is None or expected_marker in index
    ok = (identity.get("status") == "MANIFEST_EXECUTION_FILES_VERIFIED"
          and identity.get("release_id") == expected_id and marker_ok
          and (expected_manifest_sha is None or identity.get("manifest_sha256") == expected_manifest_sha))
    return {"ok": ok, "identity": identity, "index_marker_ok": marker_ok}


def wait_verified(expected_id: str, expected_marker: str | None = None, seconds: float = 60,
                  expected_manifest_sha: str | None = None) -> dict:
    deadline = time.monotonic() + seconds
    last: dict = {"ok": False, "reason": "no response"}
    while time.monotonic() < deadline:
        try:
            last = verify_release(expected_id, expected_marker, expected_manifest_sha)
            if last["ok"]:
                return last
        except Exception as exc:
            last = {"ok": False, "error": str(exc)}
        time.sleep(min(0.5, max(0, deadline - time.monotonic())))
    return last


def unload() -> None:
    printed = launchctl("print", JOB)
    if printed.returncode == 0:
        result = launchctl("bootout", JOB)
        if result.returncode:
            raise RuntimeError("BOOTOUT_FAILED:" + result.stderr)
    elif "Could not find service" not in printed.stderr:
        raise RuntimeError("JOB_STATE_UNKNOWN:" + printed.stderr)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        result = launchctl("print", JOB)
        if result.returncode and "Could not find service" in result.stderr and not port_listening():
            return
        time.sleep(0.2)
    raise RuntimeError("UNLOAD_OR_LISTENER_TIMEOUT")


def atomic_plist(raw: bytes, *, expected_sha: str) -> None:
    checked(LIVE_PLIST, expected_sha)
    mode = LIVE_PLIST.stat().st_mode & 0o777
    with tempfile.NamedTemporaryFile(dir=LIVE_PLIST.parent, prefix=".v4-supplement-", delete=False) as stream:
        path = Path(stream.name)
        try:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
            path.chmod(mode)
            # Recheck immediately before replace while the shared lock is held.
            checked(LIVE_PLIST, expected_sha)
            os.replace(path, LIVE_PLIST)
        finally:
            path.unlink(missing_ok=True)
    checked(LIVE_PLIST, sha256_bytes(raw))


def plist_identity(raw: bytes) -> dict:
    value = plistlib.loads(raw)
    env = value["EnvironmentVariables"]
    if not env.get("V4_RELEASE_ID") or not env.get("V4_RELEASE_MANIFEST_SHA256"):
        raise ValueError("PLIST_RELEASE_IDENTITY_MISSING")
    return env


def candidate_config(raw: bytes, candidate: Path, manifest: dict, manifest_sha: str) -> None:
    value = plistlib.loads(raw)
    env = plist_identity(raw)
    app = str(candidate / "app")
    if (value.get("Label") != LABEL or value.get("WorkingDirectory") != app
            or env.get("V4_APP_ROOT") != app or env.get("V4_RELEASE_ID") != manifest["release_id"]
            or env.get("V4_RELEASE_MANIFEST_PATH") != str(candidate / "release-manifest.json")
            or env.get("V4_RELEASE_MANIFEST_SHA256") != manifest_sha):
        raise ValueError("CANDIDATE_LAUNCH_CONFIG_MISMATCH")


def bootstrap_and_verify(raw: bytes, expected_marker: str | None, tracking: dict | None = None) -> dict:
    env = plist_identity(raw)
    result = launchctl("bootstrap", DOMAIN, str(LIVE_PLIST))
    if result.returncode:
        raise RuntimeError("BOOTSTRAP_FAILED:" + result.stderr)
    if tracking is not None:
        tracking["bootstrapped_plist_sha256"] = sha256_bytes(raw)
    # Capture only this bootstrap's process, then require it to stay stable.
    deadline = time.monotonic() + 60
    verification: dict = {"ok": False, "reason": "no process"}
    while time.monotonic() < deadline:
        process = process_info()
        if process["pid"].isdigit():
            if tracking is not None:
                if tracking.get("process") is None:
                    tracking["process"] = process
                elif tracking["process"] != process:
                    raise RuntimeError("BOOTSTRAPPED_PROCESS_CHANGED")
            try:
                verification = verify_release(env["V4_RELEASE_ID"], expected_marker,
                                              env["V4_RELEASE_MANIFEST_SHA256"])
                if verification.get("ok"):
                    return verification
            except Exception as exc:
                verification = {"ok": False, "error": str(exc)}
        time.sleep(0.5)
    raise RuntimeError("READINESS_TIMEOUT:" + json.dumps(verification, ensure_ascii=False))


def assert_switch_identity(expected_sha: str, expected_process: dict) -> None:
    checked(LIVE_PLIST, expected_sha)
    if process_info() != expected_process:
        raise ValueError("ACTIVE_PROCESS_CAS_CHANGED")


def assert_owned_loaded_without_pid(desired: bytes, process: dict, tracking: dict) -> None:
    """Prove a crashed loaded job is this attempt's successful bootstrap.

    launchctl list alone cannot establish ownership. Match print's actual
    loaded config, including cwd, argv and every staged environment value;
    inherited/default environment blocks are deliberately not accepted.
    """
    digest = sha256_bytes(desired)
    if (process.get("pid") != "-" or tracking.get("bootstrapped_plist_sha256") != digest):
        raise ValueError("RECOVERY_LOADED_JOB_OWNERSHIP_UNCONFIRMED")
    checked(LIVE_PLIST, digest)
    printed = launchctl("print", JOB)
    lines = printed.stdout.splitlines()
    if printed.returncode or not lines or lines[0] != JOB + " = {":
        raise ValueError("RECOVERY_LOADED_JOB_PRINT_UNCONFIRMED")
    scalars: dict[str, str] = {}
    sections: dict[str, list[str]] = {}
    section = None
    for line in lines[1:]:
        # Actual launchctl print format, sampled read-only from this host.
        # Unknown/nested fields cannot masquerade as top-level properties.
        if line.startswith("\t\t"):
            if section is not None:
                sections[section].append(line[2:])
        elif line.startswith("\t"):
            content = line[1:]
            if content == "}":
                section = None
            elif " = " in content:
                key, value = content.split(" = ", 1)
                if key in scalars or key in sections:
                    raise ValueError("RECOVERY_LOADED_JOB_DUPLICATE_FIELD")
                if value == "{":
                    section = key
                    sections[key] = []
                else:
                    section = None
                    scalars[key] = value
    loaded_env: dict[str, str] = {}
    for line in sections.get("environment", []):
        key, separator, value = line.partition(" =>")
        if not separator or key in loaded_env:
            raise ValueError("RECOVERY_LOADED_JOB_ENV_UNCONFIRMED")
        loaded_env[key] = value[1:] if value.startswith(" ") else value
    value = plistlib.loads(desired)
    arguments = value.get("ProgramArguments") or []
    if (not arguments or scalars.get("path") != str(LIVE_PLIST)
            or scalars.get("type") != "LaunchAgent" or "pid" in scalars
            or scalars.get("program") != arguments[0]
            or sections.get("arguments") != arguments
            or scalars.get("working directory") != value.get("WorkingDirectory")
            or any(loaded_env.get(key) != item for key, item in value["EnvironmentVariables"].items())):
        raise ValueError("RECOVERY_LOADED_JOB_CONFIG_CONFLICT")
    # Refuse a process that appeared while reading print, or a stray listener.
    if process_info() != process or port_listening():
        raise ValueError("RECOVERY_LOADED_JOB_PROCESS_CHANGED")
    checked(LIVE_PLIST, digest)


def recover_previous(previous: bytes, desired: bytes, before_process: dict, tracking: dict) -> dict:
    current = LIVE_PLIST.read_bytes()
    if current not in (previous, desired):
        raise ValueError("RECOVERY_PLIST_CAS_CONFLICT")
    state, process = service_state()
    if state == "running" and current == previous:
        if process != before_process:
            raise ValueError("RECOVERY_PREVIOUS_PROCESS_CHANGED")
        env = plist_identity(previous)
        restored = wait_verified(env["V4_RELEASE_ID"], expected_manifest_sha=env["V4_RELEASE_MANIFEST_SHA256"])
        if not restored.get("ok"):
            raise RuntimeError("RECOVERY_PREVIOUS_IDENTITY_UNVERIFIED")
        return restored
    if state == "running":
        if current != desired:
            raise ValueError("RECOVERY_DESIRED_PROCESS_UNCONFIRMED")
        if process is not None and process.get("pid") == "-":
            assert_owned_loaded_without_pid(desired, process, tracking)
        elif not tracking.get("process") or process != tracking["process"]:
            raise ValueError("RECOVERY_DESIRED_PROCESS_UNCONFIRMED")
        unload()
        if service_state()[0] != "stopped":
            raise ValueError("RECOVERY_UNLOAD_NOT_CONFIRMED")
    checked(LIVE_PLIST, sha256_bytes(current))
    if current != previous:
        atomic_plist(previous, expected_sha=sha256_bytes(current))
    return bootstrap_and_verify(previous, None)


def write_record(path: Path, value: dict, *, exclusive: bool = False) -> None:
    with path.open("x" if exclusive else "w") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def activate(candidate: Path) -> int:
    with release_lock():
        return activate_locked(candidate)


def activate_locked(candidate: Path) -> int:
    preparation_raw = (candidate / "preparation.json").read_bytes()
    preparation = json.loads(preparation_raw)
    candidate_plist = candidate / "config/com.lexi.v4.api.plist"
    manifest_raw = checked(candidate / "release-manifest.json", preparation["candidate_manifest_sha256"])
    manifest = json.loads(manifest_raw)
    desired = checked(candidate_plist, preparation["candidate_plist_sha256"])
    candidate_config(desired, candidate, manifest, sha256_bytes(manifest_raw))
    if preparation.get("activation_status") != "NOT_ACTIVATED" or (candidate / "activation.json").exists():
        raise ValueError("CANDIDATE_ALREADY_ACTIVATED_OR_NOT_PREPARED")
    previous = checked(LIVE_PLIST, preparation["before_plist_sha256"])
    old_env = plist_identity(previous)
    before_process = process_info()
    baseline = wait_verified(old_env["V4_RELEASE_ID"], seconds=15,
                             expected_manifest_sha=old_env["V4_RELEASE_MANIFEST_SHA256"])
    if not baseline.get("ok") or not before_process["pid"].isdigit():
        raise ValueError("LIVE_IDENTITY_UNVERIFIED_BEFORE_SWITCH")
    attempt_id = time.strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:12]
    inverse = candidate / f"config/activation-before-{attempt_id}.plist"
    with inverse.open("xb") as stream:
        stream.write(previous)
    attempt = candidate / f"activation-attempt-{attempt_id}.json"
    record = {"schema_version": "v4.supplement_inline.activation.v2", "status": "BEFORE_UNLOAD",
              "candidate_root": str(candidate), "before_plist_sha256": sha256_bytes(previous),
              "candidate_plist_sha256": sha256_bytes(desired),
              "candidate_manifest_sha256": sha256_bytes(manifest_raw), "before_process": before_process,
              "started_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
              "inverse_plist_path": str(inverse), "inverse_plist_sha256": sha256_bytes(previous)}
    write_record(attempt, record, exclusive=True)
    tracking: dict = {}
    # Last guards are outside recovery: any drift here must not reach bootout.
    checked(candidate / "preparation.json", sha256_bytes(preparation_raw))
    checked(candidate_plist, sha256_bytes(desired))
    checked(candidate / "release-manifest.json", sha256_bytes(manifest_raw))
    assert_switch_identity(sha256_bytes(previous), before_process)
    try:
        unload()
        atomic_plist(desired, expected_sha=sha256_bytes(previous))
        verification = bootstrap_and_verify(desired, MARKER, tracking)
        after_process = process_info()
        checked(LIVE_PLIST, sha256_bytes(desired))
        if after_process["pid"] == before_process["pid"] or after_process != tracking.get("process"):
            raise RuntimeError("BOOTSTRAPPED_PROCESS_UNCHANGED_OR_UNCONFIRMED")
        record.update(status="ACTIVATED", verification=verification, after_process=after_process,
                      activated_at=time.strftime("%Y-%m-%dT%H:%M:%S+08:00"))
        write_record(attempt, record)
        write_record(candidate / "activation.json", record, exclusive=True)
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        record.update(error=str(exc), candidate_process=tracking.get("process"))
        try:
            restored = recover_previous(previous, desired, before_process, tracking)
            record.update(status="ROLLED_BACK_AFTER_FAILED_ACTIVATION", restored_healthy=True,
                          restored_identity=restored, after_process=process_info())
        except Exception as rollback_exc:
            record.update(status="ROLLBACK_FAILED", rollback_error=str(rollback_exc))
        write_record(attempt, record)
        print(json.dumps(record, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


def rollback(candidate: Path) -> int:
    with release_lock():
        activation = json.loads((candidate / "activation.json").read_text())
        if activation.get("status") != "ACTIVATED":
            raise ValueError("NO_SUCCESSFUL_ACTIVATION")
        previous = checked(Path(activation["inverse_plist_path"]), activation["inverse_plist_sha256"])
        current = checked(LIVE_PLIST, activation["candidate_plist_sha256"])
        assert_switch_identity(sha256_bytes(current), activation["after_process"])
        tracking: dict = {}
        try:
            unload()
            atomic_plist(previous, expected_sha=sha256_bytes(current))
            verification = bootstrap_and_verify(previous, None, tracking)
        except Exception:
            # Rollback itself failed: restore the release that was live on entry.
            recover_previous(current, previous, activation["after_process"], tracking)
            raise
        record = {"schema_version": "v4.supplement_inline.rollback.v2", "verification": verification,
                  "restored_plist_sha256": sha256_bytes(previous),
                  "rolled_back_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00")}
        output = candidate / ("rollback-" + uuid4().hex[:12] + ".json")
        write_record(output, record, exclusive=True)
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("activate", "rollback"))
    parser.add_argument("--candidate-root", type=Path, required=True)
    args = parser.parse_args()
    candidate = args.candidate_root.resolve()
    if not candidate.is_relative_to((LOCAL / "candidates").resolve()):
        raise SystemExit("candidate root must live under the local candidates tree")
    return activate(candidate) if args.action == "activate" else rollback(candidate)


if __name__ == "__main__":
    raise SystemExit(main())
