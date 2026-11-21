"""Activate a reviewed exact launch-agent plan, with group rollback on failure."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from infrastructure.interprocess_lock import owned_interprocess_lock
from infrastructure.owned_io import SafeRoot
from ops.api_release_integration import announcement_flash_cutover_guard


LAUNCH_AGENTS = Path.home() / "Library/LaunchAgents"
CANDIDATES = Path.home() / "Library/Application Support/com.lexi.v4.local/candidates"
DOMAIN = f"gui/{os.getuid()}"
LABELS = {
    "api": "com.lexi.v4.api",
    "main": "com.lexi.v4.scheduler",
    "stage": "com.lexi.stage-center.scheduler",
    "observer": "com.lexi.v4.workbench-observation",
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(accepted, reason):
    if not accepted:
        raise RuntimeError(reason)


def checked(path, expected):
    path = Path(path)
    require(path.is_absolute() and path.resolve(strict=True) == path and path.is_file(), f"invalid file {path}")
    raw = path.read_bytes()
    require(sha(raw) == expected, f"SHA drift {path}")
    return raw


def ctl(*args):
    return subprocess.run(["/bin/launchctl", *args], capture_output=True, text=True, timeout=15)


def run_ctl(*args):
    result = ctl(*args)
    if result.returncode:
        first = (result.stderr or result.stdout).strip().splitlines()
        raise RuntimeError(f"launchctl {args[0]} exit {result.returncode}: {first[0] if first else ''}")


def loaded(label):
    result = ctl("print", f"{DOMAIN}/{label}")
    if result.returncode:
        require("could not find service" in result.stderr.lower(), f"launchctl print {label} exit {result.returncode}")
        return None
    body = result.stdout
    workdir = re.search(r"^\s*working directory = (.*)$", body, re.M)
    pid = re.search(r"^\s*pid = (\d+)\s*$", body, re.M)
    config = re.search(r"^\s*path = (.*)$", body, re.M)
    manifest = re.search(r"^\s*V4_RELEASE_MANIFEST_SHA256 => ([0-9a-f]{64})\s*$", body, re.M)
    return {"cwd": workdir[1] if workdir else None, "pid": int(pid[1]) if pid else None,
            "path": config[1] if config else None, "loaded_manifest_sha256": manifest[1] if manifest else None}


def wait_state(label, check, timeout):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        state = loaded(label)
        if check(state):
            return state
        time.sleep(0.25)
    raise RuntimeError(f"launchctl did not reach the expected state for {label}")


def health():
    try:
        with urlopen("http://127.0.0.1:8873/healthz", timeout=1.5) as response:
            return json.load(response).get("status") == "ok"
    except (OSError, ValueError):
        return False


def verify_loaded(role, expected_cwd, plist_path, expected_loaded_manifest):
    label = LABELS[role]
    def ready(state):
        if not state or state["cwd"] != expected_cwd or state["path"] != str(plist_path):
            return False
        if state["loaded_manifest_sha256"] != expected_loaded_manifest:
            return False
        return (bool(state["pid"]) and health()) if role == "api" else (bool(state["pid"]) if role == "main" else True)
    return wait_state(label, ready, 55 if role == "api" else 20)


def write_atomic(path, raw, previous):
    require(path.read_bytes() == previous, f"plist CAS failed: {path}")
    mode = stat.S_IMODE(path.stat().st_mode)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}-audit-", dir=path.parent)
    pending = Path(name)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(raw)
            file.flush()
            os.fchmod(file.fileno(), mode)
            os.fsync(file.fileno())
        require(path.read_bytes() == previous, f"plist drift before replace: {path}")
        os.replace(pending, path)
    finally:
        pending.unlink(missing_ok=True)
    require(path.read_bytes() == raw, f"plist readback failed: {path}")


def load_role(record, approved):
    role = record["role"]
    label = LABELS[role]
    path = LAUNCH_AGENTS / f"{label}.plist"
    old = checked(record["rollback_plist"], record["current_plist_sha256"])
    new_path = Path(record["candidate_plist"])
    new_path.relative_to(CANDIDATES)
    new = checked(new_path, record["candidate_plist_sha256"])
    require(all(record[k] == approved[k] for k in ("candidate_plist_sha256", "candidate_manifest_sha256",
                                                   "candidate_release_id")), f"role differs from review: {role}")
    require(approved["delta_files"], f"recorded review file list missing: {role}")
    for entry in approved["delta_files"]:
        p = Path(entry["path"])
        p.relative_to(CANDIDATES)
        checked(p, entry["sha256"])
    old_cfg, new_cfg = plistlib.loads(old), plistlib.loads(new)
    for cfg in (old_cfg, new_cfg):
        require(cfg["Label"] == label, f"label mismatch {role}")
    old_cwd, new_cwd = old_cfg["WorkingDirectory"], new_cfg["WorkingDirectory"]
    require(old_cwd != new_cwd and Path(new_cwd).is_dir(), f"invalid new WorkingDirectory {role}")
    Path(new_cwd).relative_to(CANDIDATES)
    require(Path(new_cwd).parent == new_path.parent, f"staged plist outside role release {role}")
    old_manifest = Path(old_cwd).parent / "release-manifest.json"
    new_manifest = Path(new_cwd).parent / "release-manifest.json"
    old_meta = json.loads(checked(old_manifest, record["current_manifest_sha256"]))
    new_meta = json.loads(checked(new_manifest, record["candidate_manifest_sha256"]))
    require(new_meta.get("release_id") == record["candidate_release_id"], f"release ID mismatch {role}")
    for cfg, manifest_file, manifest_sha in ((old_cfg, old_manifest, record["current_manifest_sha256"]),
                                             (new_cfg, new_manifest, record["candidate_manifest_sha256"])):
        env = cfg.get("EnvironmentVariables", {})
        if role != "observer" or env.get("V4_RELEASE_MANIFEST_SHA256"):
            require(env.get("V4_RELEASE_MANIFEST_PATH") == str(manifest_file) and
                    env.get("V4_RELEASE_MANIFEST_SHA256") == manifest_sha, f"invalid manifest env {role}")
    require(path.read_bytes() == old, f"live plist drift {role}")
    state = loaded(label)
    require(state and state["cwd"] == old_cwd and state["path"] == str(path), f"loaded source drift {role}")
    require(state["loaded_manifest_sha256"] == old_cfg.get("EnvironmentVariables", {}).get("V4_RELEASE_MANIFEST_SHA256"),
            f"loaded manifest differs from current plist {role}")
    if role == "api":
        require(state["pid"] and health(), "prior API not healthy")
    if role == "main":
        require(state["pid"], "prior scheduler missing")
    if role in {"stage", "observer"}:
        require(not state["pid"], f"active scheduled job {role}")
    return {"role": role, "label": label, "path": path, "old": old, "new": new,
            "old_cwd": old_cwd, "new_cwd": new_cwd, "before": state,
            "old_cfg": old_cfg, "new_cfg": new_cfg,
            "old_meta": old_meta, "new_meta": new_meta,
            "old_manifest": old_manifest, "new_manifest": new_manifest,
            "old_manifest_sha": record["current_manifest_sha256"],
            "new_manifest_sha": record["candidate_manifest_sha256"]}


def check_stage_main_binding(main, stage):
    for side in ("old", "new"):
        arguments = stage[f"{side}_cfg"]["ProgramArguments"]
        config = Path(arguments[arguments.index("--config") + 1])
        require(config == Path(stage[f"{side}_cwd"]) / "stage_center_tick_config.json", f"unbound Stage config: {side}")
        binding = json.loads(config.read_bytes()).get("research_owner_binding")
        require(binding == {"app_root": main[f"{side}_cwd"],
                            "manifest_path": str(main[f"{side}_manifest"]),
                            "manifest_sha256": main[f"{side}_manifest_sha"],
                            "release_id": main[f"{side}_meta"]["release_id"]},
                f"Stage/Main identity mismatch: {side}")


def manager_root(env, expected_config_sha):
    cfg = Path(env["V4_MANAGER_WORKBENCH_CONFIG_PATH"])
    root = Path(json.loads(checked(cfg, expected_config_sha))["state_root"]) / "manager_workbench"
    require(root == root.resolve(strict=True) and root.is_dir(), "manager workbench guard root unavailable")
    return root


def manager_idle(root):
    store = SafeRoot(root)
    with store.directory("attempts"):
        attempts = store.files("attempts")
    for name in attempts:
        record = json.loads(store.read_bytes("attempts/" + name, max_bytes=64 * 1024 * 1024))
        require(isinstance(record, dict) and isinstance(record.get("state"), str), "undecodable manager job state")
        require(record["state"] not in {"QUEUED", "RUNNING"}, "manager workbench has accepted work")
    return len(attempts)


def scheduler_idle(pid, cfg):
    result = subprocess.check_output(["/bin/ps", "-axo", "pid=,ppid="], text=True)
    children = [a for a, b in (line.split() for line in result.splitlines()) if int(b) == pid]
    require(not children, f"Main has live child processes: {', '.join(children)}")
    with Path(cfg["StandardOutPath"]).open("rb") as log:
        log.seek(max(0, os.fstat(log.fileno()).st_size - 65536))
        lines = log.read().splitlines()
    latest = next((json.loads(line) for line in reversed(lines) if b'"status": "DAEMON_DISPATCH_CYCLE"' in line), None)
    require(latest and latest.get("active_children") == latest.get("queued_slots") == 0,
            "Main dispatch cycle has pending work or unavailable state")
    now = datetime.now().astimezone()
    logged = datetime.fromisoformat(latest["minute"]).replace(tzinfo=now.tzinfo)
    require(0 <= (now - logged).total_seconds() <= 130, "Main dispatch cycle evidence stale")


def role_idle(role):
    state = loaded(role["label"])
    require(state and state["cwd"] == role["old_cwd"] and role["path"].read_bytes() == role["old"], f"stale preimage {role['role']}")
    if role["role"] == "main":
        require(state["pid"], "prior scheduler missing")
        scheduler_idle(state["pid"], role["old_cfg"])
    if role["role"] in {"stage", "observer"}:
        require(not state["pid"], f"active scheduled job {role['role']}")


def unload(role):
    run_ctl("bootout", f"{DOMAIN}/{role['label']}")
    wait_state(role["label"], lambda state: state is None, 35)


def activate(roles, plan, result):
    attempted = []
    try:
        for role in roles:
            role_idle(role)
        # On a coupled owner change, unload Stage before Main. Start Main before Stage.
        for role in reversed(roles):
            role_idle(role)
            attempted.append(role)
            unload(role)
        for role in roles:
            write_atomic(role["path"], role["new"], role["old"])
            run_ctl("bootstrap", DOMAIN, str(role["path"]))
            expected = role["new_cfg"].get("EnvironmentVariables", {}).get("V4_RELEASE_MANIFEST_SHA256")
            state = verify_loaded(role["role"], role["new_cwd"], role["path"], expected)
            result["roles"][role["role"]]["after"] = state
        if plan.get("verification_command"):
            subprocess.run(plan["verification_command"], check=True, timeout=120)
        for role in roles:
            require(role["path"].read_bytes() == role["new"], f"final plist drift {role['role']}")
            expected = role["new_cfg"].get("EnvironmentVariables", {}).get("V4_RELEASE_MANIFEST_SHA256")
            result["roles"][role["role"]]["after"] = verify_loaded(role["role"], role["new_cwd"], role["path"], expected)
        result["status"] = "DEPLOYED"
    except BaseException as exc:
        result["status"] = "ROLLED_BACK"
        result["error"] = f"{type(exc).__name__}: {exc}"
        for role in attempted:
            try:
                payload = role["path"].read_bytes()
                require(payload in (role["old"], role["new"]), f"rollback CAS drift {role['role']}")
                state = loaded(role["label"])
                if state and state["cwd"] == role["new_cwd"]:
                    unload(role)
                    state = None
                require(state is None or state["cwd"] == role["old_cwd"], f"rollback loaded role drift {role['role']}")
                if payload == role["new"]:
                    write_atomic(role["path"], role["old"], role["new"])
            except BaseException as error:
                result["status"] = "ROLLBACK_INCOMPLETE"
                result["roles"][role["role"]]["rollback_error"] = f"{type(error).__name__}: {error}"
        for role in reversed(attempted):
            if "rollback_error" in result["roles"][role["role"]]:
                continue
            try:
                if not loaded(role["label"]):
                    run_ctl("bootstrap", DOMAIN, str(role["path"]))
                expected = role["old_cfg"].get("EnvironmentVariables", {}).get("V4_RELEASE_MANIFEST_SHA256")
                result["roles"][role["role"]]["restored"] = verify_loaded(role["role"], role["old_cwd"], role["path"], expected)
            except BaseException as error:
                result["status"] = "ROLLBACK_INCOMPLETE"
                result["roles"][role["role"]]["rollback_error"] = f"{type(error).__name__}: {error}"
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--activate-reviewed", action="store_true", required=True)
    args = parser.parse_args()
    plan = json.loads(checked(args.plan, args.plan_sha256))
    group = tuple(record["role"] for record in plan["roles"])
    require(group in {("api",), ("main", "stage"), ("observer",)}, "unsupported role group")
    require(not args.receipt.exists(), "activation receipt exists")
    result = {"status": "PRECHECK_FAILED", "plan_sha256": args.plan_sha256, "roles": {}}
    try:
        approval_ref = plan["review_approval"]
        approval = json.loads(checked(approval_ref["path"], approval_ref["sha256"]))
        require(approval["verdict"] == "PASS" and set(group) == set(approval["roles"]), "review not matched to role group")
        with ExitStack() as locks:
            for role in group:
                prefix = LAUNCH_AGENTS / f".{LABELS[role]}.release.lock"
                require(prefix.with_name(prefix.name + ".mutex").is_file(), f"existing role mutex missing: {role}")
                locks.enter_context(owned_interprocess_lock(prefix, timeout_seconds=8,
                                                          timeout_message=f"V4 release lock busy: {role}"))
            roles = [load_role(row, approval["roles"][row["role"]]) for row in plan["roles"]]
            if group == ("api",):
                old_env = roles[0]["old_cfg"]["EnvironmentVariables"]
                new_env = roles[0]["new_cfg"]["EnvironmentVariables"]
                root = manager_root(old_env, plan["manager_config_sha256"])
                require(new_env["V4_MANAGER_WORKBENCH_CONFIG_PATH"] == old_env["V4_MANAGER_WORKBENCH_CONFIG_PATH"],
                        "manager workbench config changed")
                flash_receipt = locks.enter_context(announcement_flash_cutover_guard(root))
                result["announcement_activity"] = flash_receipt
                result["manager_attempts_checked"] = manager_idle(root)
            if group == ("main", "stage"):
                check_stage_main_binding(*roles)
            result["roles"] = {r["role"]: {"before": r["before"]} for r in roles}
            activate(roles, plan, result)
    except BaseException as exc:
        result.setdefault("error", f"{type(exc).__name__}: {exc}")
        raise
    finally:
        result["recorded_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        with args.receipt.open("x") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write("\n")


if __name__ == "__main__":
    main()
