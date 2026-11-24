"""Publish and restore one reviewed macOS API/Main/Stage activation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import signal
import subprocess
from contextlib import ExitStack
from datetime import datetime
from uuid import uuid4

from infrastructure.interprocess_lock import owned_interprocess_lock
from infrastructure.owned_io import SafeRoot


GROUP = ("api", "main", "stage")
ROOT = Path.home() / "Library/Application Support/com.lexi.v4.local"
LABELS = {
    "api": "com.lexi.v4.api",
    "main": "com.lexi.v4.scheduler",
    "stage": "com.lexi.stage-center.scheduler",
}
LAUNCH_AGENTS = Path.home() / "Library/LaunchAgents"
CANDIDATES = ROOT / "candidates"
RELOCATION_KEYS = {"WorkingDirectory", "ProgramArguments", "EnvironmentVariables"}
HEX = r"[0-9a-f]"
ACTIVATION_TARGET = re.compile(rf"transaction-{HEX}{{64}}/published")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def exact_path(value, *, directory=False):
    path = Path(value)
    require(path.is_absolute() and path.resolve(strict=True) == path, f"not an exact path: {path}")
    require(path.is_dir() if directory else path.is_file(), f"invalid path type: {path}")
    return path


def checked(path, expected):
    path = exact_path(path)
    raw = path.read_bytes()
    require(digest(raw) == expected, f"SHA drift: {path}")
    return raw


def link(path):
    try:
        return os.readlink(path)
    except FileNotFoundError:
        return None


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_audited_switch(reference):
    # Execute the exact verified bytes, with the existing helper's original
    # source path for its repository lookup. Its legacy CLI is never invoked.
    path = Path(reference["path"])
    raw = checked(path, reference["sha256"])
    namespace = {"__file__": str(path), "__name__": "audited_v4_switch"}
    exec(compile(raw, str(path), "exec"), namespace)
    require(all(namespace["LABELS"].get(role) == LABELS[role] for role in GROUP), "audited role labels drift")
    require(namespace["LAUNCH_AGENTS"] == LAUNCH_AGENTS and namespace["CANDIDATES"] == CANDIDATES,
            "audited host paths drift")
    return namespace


def startup(cfg, expected, *, candidate):
    env = cfg["EnvironmentVariables"]
    path = Path(env["V4_RELEASE_MANIFEST_PATH"])
    app = exact_path(cfg["WorkingDirectory"], directory=True)
    require(path.parent == app.parent and (not candidate or path.name == "startup-manifest.json"),
            f"startup manifest is outside role release: {path}")
    raw = checked(path, expected)
    data = json.loads(raw)
    require(env["V4_RELEASE_MANIFEST_SHA256"] == expected and env["V4_RELEASE_ID"] == data["release_id"]
            and Path(data["app_root"]) == app, f"invalid startup binding: {path}")
    return app, path, data


def candidate_files(approved, app, startup_manifest):
    inventory = {entry["path"]: entry.get("sha256")
                 for entry in startup_manifest["application_inventory"]["entries"] if entry["kind"] == "file"}
    observed = {}
    for entry in approved:
        path = exact_path(entry["path"])
        relative = path.relative_to(app).as_posix()
        actual = digest(checked(path, entry["sha256"]))
        require(relative not in observed and inventory.get(relative) == actual,
                f"reviewed overlay disagrees with startup inventory: {path}")
        observed[relative] = actual
    require(observed, f"empty reviewed overlay: {app}")
    return observed


def load_role(row, approval, activation_directory, *, rollback):
    name = row["role"]
    label = LABELS[name]
    path = LAUNCH_AGENTS / f"{label}.plist"
    old = checked(row["rollback_plist"], row["current_plist_sha256"])
    new_path = exact_path(row["candidate_plist"])
    new_root = new_path.parent
    new_root.relative_to(CANDIDATES)
    new = checked(new_path, row["candidate_plist_sha256"])
    old_cfg, new_cfg = plistlib.loads(old), plistlib.loads(new)
    require(old_cfg["Label"] == new_cfg["Label"] == label, f"label mismatch: {name}")
    changed_keys = sorted(key for key in (old_cfg.keys() | new_cfg.keys()) - RELOCATION_KEYS
                          if key not in old_cfg or key not in new_cfg
                          or plistlib.dumps({key: old_cfg[key]}) != plistlib.dumps({key: new_cfg[key]}))
    require(not changed_keys, f"non-relocation LaunchAgent keys changed: {name} {', '.join(changed_keys)}")
    old_app, old_manifest, _ = startup(old_cfg, row["current_manifest_sha256"], candidate=False)
    release_id = row["candidate_release_id"]
    new_app = Path(new_cfg["WorkingDirectory"])
    new_manifest = new_app.parent / "startup-manifest.json"
    require(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", release_id) and release_id == new_root.name
            and new_app == new_root / "app" and old_app != new_app,
            f"candidate release identity mismatch: {name}")
    for key in ("candidate_release_id", "candidate_plist_sha256", "candidate_manifest_sha256"):
        require(row[key] == approval[key], f"plan/review mismatch: {name} {key}")
    new_env = new_cfg["EnvironmentVariables"]
    require(new_env.get("V4_APP_ROOT") == str(new_app), f"candidate plist app root mismatch: {name}")
    require(new_env["V4_RELEASE_ID"] == release_id and new_env["V4_RELEASE_MANIFEST_PATH"] == str(new_manifest)
            and new_env["V4_RELEASE_MANIFEST_SHA256"] == row["candidate_manifest_sha256"],
            f"candidate plist startup binding mismatch: {name}")
    alias = new_root / "release-manifest.json"
    identity = {"release_id": release_id, "app_root": str(new_app),
                "startup_manifest": {"path": str(new_manifest), "sha256": row["candidate_manifest_sha256"]},
                "plist_path": str(path), "plist_sha256": digest(new), "role": name}
    if not rollback:
        expected_alias = activation_directory / "active" / release_id / alias.name
        require(link(alias) == str(expected_alias), f"unbound role release-manifest alias: {alias}")
        _, _, new_data = startup(new_cfg, row["candidate_manifest_sha256"], candidate=True)
        source_commit = new_data["source_commit"]
        require(re.fullmatch(rf"{HEX}{{40}}", source_commit) and source_commit == approval["source_commit"],
                f"source commit mismatch: {name}")
        source_root = exact_path(new_data["source_root"], directory=True)
        result = subprocess.run(["git", "-C", str(source_root), "cat-file", "-t", source_commit],
                                check=True, capture_output=True, text=True, timeout=10)
        require(result.stdout.strip() == "commit", f"source identity is not a Git commit: {name}")
        identity["source_commit"] = source_commit
        identity["overlay_files"] = candidate_files(approval["delta_files"], new_app, new_data)
    return {"role": name, "label": label, "path": path, "old": old, "new": new,
            "old_cfg": old_cfg, "new_cfg": new_cfg, "old_cwd": str(old_app), "new_cwd": str(new_app),
            "old_manifest": old_manifest, "old_manifest_sha": row["current_manifest_sha256"],
            "new_manifest": new_manifest, "new_manifest_sha": row["candidate_manifest_sha256"],
            "alias": alias, "identity": identity,
            "approved_files": approval["delta_files"]}


def stage_configuration(stage, side):
    cfg = stage[f"{side}_cfg"]
    arguments = cfg["ProgramArguments"]
    path = Path(arguments[arguments.index("--config") + 1])
    require(path == Path(stage[f"{side}_cwd"]) / "stage_center_tick_config.json", f"unbound Stage config: {side}")
    return path


def confirm_prior_stage(stage, expected):
    path = stage_configuration(stage, "old")
    binding = json.loads(checked(path, expected))["research_owner_binding"]
    manifest_path = Path(binding["manifest_path"])
    manifest = json.loads(checked(manifest_path, binding["manifest_sha256"]))
    require(manifest_path.parent == Path(binding["app_root"]).parent
            and manifest["app_root"] == binding["app_root"] and manifest["release_id"] == binding["release_id"],
            "prior Stage owner identity mismatch")


def release_record(directory, target):
    if target is None:
        return None
    require(ACTIVATION_TARGET.fullmatch(target), "unsafe active release pointer")
    root = directory / target
    manifest = exact_path(root / "group-manifest.json")
    raw = manifest.read_bytes()
    data = json.loads(raw)
    require(data["activation_status"] == "ACTIVE" and data["deployment_status"] == "LIVE"
            and target == f"transaction-{data['plan_sha256']}/published" and set(data["roles"]) == set(GROUP),
            "invalid active group manifest")
    for entry in data["roles"].values():
        release_id = entry["release_id"]
        require(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", release_id), "invalid active release ID")
        checked(root / release_id / "release-manifest.json", entry["sha256"])
    return {"target": target, "sha256": digest(raw)}


def active_record(directory):
    return release_record(directory, link(directory / "active"))


def sync_directory(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def switch_pointer(directory, expected, target):
    pointer = directory / "active"
    require(link(pointer) == expected, "active release pointer drift")
    if target is None:
        if expected is not None:
            pointer.unlink()
    else:
        pending = directory / f".active-{uuid4().hex}"
        pending.symlink_to(target)
        try:
            os.replace(pending, pointer)
        finally:
            pending.unlink(missing_ok=True)
    sync_directory(directory)
    require(link(pointer) == target, "active release pointer readback mismatch")


def state_matches(state, role, side):
    return (state is not None and state["cwd"] == role[f"{side}_cwd"] and state["path"] == str(role["path"])
            and state["loaded_manifest_sha256"] == role[f"{side}_manifest_sha"])


def verify(ops, role, side):
    expected = role[side]
    require(exact_path(role["path"]).read_bytes() == expected, f"live plist drift: {role['role']}")
    checked(role[f"{side}_manifest"], role[f"{side}_manifest_sha"])
    return ops["verify_loaded"](role["role"], role[f"{side}_cwd"], role["path"], role[f"{side}_manifest_sha"])


def install_group(ops, roles, plan):
    # Unload dependency consumers before the Main daemon. Restore/start in forward order.
    for role in reversed(roles):
        ops["role_idle"](role)
        require(state_matches(ops["loaded"](role["label"]), role, "old"), f"loaded preimage drift: {role['role']}")
        ops["unload"](role)
    for role in roles:
        ops["write_atomic"](role["path"], role["new"], role["old"])
        sync_directory(role["path"].parent)
        ops["run_ctl"]("bootstrap", ops["DOMAIN"], str(role["path"]))
        verify(ops, role, "new")
    subprocess.run(plan["verification_command"], check=True, timeout=120)
    return {role["role"]: verify(ops, role, "new") for role in roles}


def publish(io, directory, target, roles, observations, plan_sha):
    manifests = {}
    activated_at = now()
    status = {"activation_status": "ACTIVE", "deployment_status": "LIVE",
              "plan_sha256": plan_sha, "activated_at": activated_at}
    for role in roles:
        identifier = role["identity"]["release_id"]
        # Reconfirm approved bytes after all role probes and before publication.
        startup_manifest = json.loads(checked(role["new_manifest"], role["new_manifest_sha"]))
        files = candidate_files(role["approved_files"], Path(role["new_cwd"]), startup_manifest)
        require(files == role["identity"]["overlay_files"], f"overlay drift at publication: {identifier}")
        raw = encode({**status, **role["identity"], "loaded": observations[role["role"]]})
        entry = f"{target}/{identifier}/release-manifest.json"
        io.write_bytes(entry, raw, require_absent=True)
        manifests[role["role"]] = {"release_id": identifier, "path": str(role["alias"]), "sha256": digest(raw)}
    raw = encode({**status, "roles": manifests})
    io.write_bytes(f"{target}/group-manifest.json", raw, require_absent=True)
    sync_directory((directory / target).parent)
    switch_pointer(directory, None, target)
    observed = active_record(directory)
    require(observed == {"target": target, "sha256": digest(raw)}, "publication readback mismatch")
    for entry in manifests.values():
        require(digest(Path(entry["path"]).read_bytes()) == entry["sha256"], "role alias readback mismatch")
    return observed


def protect_roles(ops, roles, plan, locks, result, *, rollback):
    api, main, stage = roles
    old_env = api["old_cfg"]["EnvironmentVariables"]
    new_env = api["new_cfg"]["EnvironmentVariables"]
    require(old_env["V4_MANAGER_WORKBENCH_CONFIG_PATH"] == new_env["V4_MANAGER_WORKBENCH_CONFIG_PATH"],
            "manager workbench config changed")
    root = ops["manager_root"](old_env, plan["manager_config_sha256"])
    result["announcement_activity"] = locks.enter_context(ops["announcement_flash_cutover_guard"](root))
    result["manager_attempts_checked"] = ops["manager_idle"](root)
    confirm_prior_stage(stage, plan["prior_stage_config_sha256"])
    if rollback:
        return
    # Preserve the actual historical Stage preimage, which may pin an older Main.
    # For the reviewed new pair, both roles must agree on the startup manifest.
    path = stage_configuration(stage, "new")
    config = json.loads(checked(path, stage["identity"]["overlay_files"].get(path.name)))
    binding = {"app_root": main["new_cwd"], "manifest_path": str(main["new_manifest"]),
               "manifest_sha256": main["new_manifest_sha"], "release_id": main["identity"]["release_id"]}
    require(config["research_owner_binding"] == binding, "reviewed Stage does not bind new Main startup")


def restore_group(ops, roles, directory, target, prior):
    current = link(directory / "active")
    prior_target = prior["target"] if prior else None
    require(current in (None, target, prior_target), "a different release owns the active pointer")
    # Preflight each exact pair before making any rollback changes. Unknown jobs
    # or plist bytes are left in place with the recovery journal intact.
    states = {}
    for role in roles:
        state = ops["loaded"](role["label"])
        payload = exact_path(role["path"]).read_bytes()
        require(payload in (role["old"], role["new"]), f"rollback plist drift: {role['role']}")
        if state is not None:
            side = "old" if payload == role["old"] else "new"
            require(state_matches(state, role, side), f"rollback loaded identity drift: {role['role']}")
            if side == "new" and role["role"] == "stage":
                require(not state["pid"], "Stage job is running")
            if side == "new" and role["role"] == "main" and state["pid"]:
                ops["scheduler_idle"](state["pid"], role["new_cfg"])
        states[role["role"]] = (state, payload)
    if current == target:
        switch_pointer(directory, target, None)
    for role in reversed(roles):
        state, payload = states[role["role"]]
        if payload == role["new"]:
            if state is not None:
                ops["unload"](role)
            ops["write_atomic"](role["path"], role["old"], role["new"])
            sync_directory(role["path"].parent)
    observations = {}
    for role in roles:
        if ops["loaded"](role["label"]) is None:
            ops["run_ctl"]("bootstrap", ops["DOMAIN"], str(role["path"]))
        observations[role["role"]] = verify(ops, role, "old")
    if link(directory / "active") != prior_target:
        switch_pointer(directory, None, prior_target)
    require(active_record(directory) == prior, "prior active release readback mismatch")
    return observations


def transact(ops, roles, plan, plan_sha, directory, result, *, rollback):
    io = SafeRoot(directory)
    transaction = f"transaction-{plan_sha}"
    target = f"{transaction}/published"
    intent_path = f"{transaction}/intent.json"
    rolled_back_path = f"{transaction}/rolled-back.json"
    pending_path = "pending.json"
    pending_raw = encode({"plan_sha256": plan_sha})
    try:
        pending = io.read_bytes(pending_path)
    except FileNotFoundError:
        pending = None
    require(pending in (None, pending_raw), "an earlier group activation requires recovery")
    if rollback:
        intent = json.loads(io.read_bytes(intent_path))
        require(intent["plan_sha256"] == plan_sha, "recovery intent does not match plan")
        prior = intent["prior_active"]
        require((prior["sha256"] if prior else None) == plan["prior_active_sha256"]
                and release_record(directory, prior["target"] if prior else None) == prior,
                "recovery prior release does not match the approved preimage")
        require(pending == pending_raw or link(directory / "active") == target,
                "reviewed activation is neither pending nor active")
        result["status"] = "ROLLBACK_INCOMPLETE"
        if pending is None:
            io.write_bytes(pending_path, pending_raw, require_absent=True)
        result["restored"] = restore_group(ops, roles, directory, target, prior)
        io.write_bytes(rolled_back_path, pending_raw)
        require(io.unlink_if_same(pending_path, pending_raw), "rollback journal drift")
        result["status"] = "ROLLED_BACK"
        return

    require(pending is None, "pending activation requires --rollback-reviewed")
    prior = active_record(directory)
    require((prior["sha256"] if prior else None) == plan["prior_active_sha256"], "prior active release drift")
    for role in roles:
        verify(ops, role, "old")
        ops["role_idle"](role)
    intent_raw = encode({"plan_sha256": plan_sha, "prior_active": prior})
    require(not os.path.lexists(directory / rolled_back_path), "rolled-back plan requires a fresh seal")
    try:
        io.write_bytes(intent_path, intent_raw, require_absent=True)
    except FileExistsError:
        require(io.read_bytes(intent_path) == intent_raw, "activation intent changed")
    io.write_bytes(pending_path, pending_raw, require_absent=True)
    try:
        if prior is not None:
            switch_pointer(directory, prior["target"], None)
        observations = install_group(ops, roles, plan)
        result["active_release"] = publish(io, directory, target, roles, observations, plan_sha)
        require(io.unlink_if_same(pending_path, pending_raw), "activation journal drift")
        result["status"] = "DEPLOYED"
    except BaseException as error:
        result["error"] = f"{type(error).__name__}: {error}"
        result["status"] = "ROLLBACK_INCOMPLETE"
        try:
            result["restored"] = restore_group(ops, roles, directory, target, prior)
            io.write_bytes(rolled_back_path, pending_raw)
            require(io.unlink_if_same(pending_path, pending_raw), "rollback journal drift")
            result["status"] = "ROLLED_BACK"
        except BaseException as rollback_error:
            result["rollback_error"] = f"{type(rollback_error).__name__}: {rollback_error}"
        raise


def run(plan, plan_sha, result, *, rollback):
    group = tuple(row["role"] for row in plan["roles"])
    require(group == GROUP, "expected exact API/Main/Stage role group and order")
    if not rollback:
        command = plan.get("verification_command")
        require(isinstance(command, list) and command and command[0]
                and all(isinstance(arg, str) and "\x00" not in arg for arg in command),
                "activation requires a sealed nonempty verification argv")
    reference = plan["review_approval"]
    approval = json.loads(checked(reference["path"], reference["sha256"]))
    require(approval["verdict"] == "PASS" and set(approval["roles"]) == set(GROUP), "group review mismatch")
    directory = exact_path(plan["activation_directory"], directory=True)
    directory.relative_to(ROOT)
    require(directory.stat().st_uid == os.getuid() and not directory.stat().st_mode & 0o077,
            "activation directory is not private")
    ops = load_audited_switch(plan["audited_switch"])
    with ExitStack() as locks:
        for role in GROUP:
            label = LABELS[role]
            prefix = LAUNCH_AGENTS / f".{label}.release.lock"
            exact_path(prefix.with_name(prefix.name + ".mutex"))
            locks.enter_context(owned_interprocess_lock(prefix, timeout_seconds=8,
                                                       timeout_message=f"V4 release lock busy: {role}"))
        roles = [load_role(row, approval["roles"][row["role"]], directory, rollback=rollback)
                 for row in plan["roles"]]
        require(len({role["identity"]["release_id"] for role in roles}) == len(GROUP), "duplicate release ID")
        protect_roles(ops, roles, plan, locks, result, rollback=rollback)
        transact(ops, roles, plan, plan_sha, directory, result, rollback=rollback)


def terminate(_signum, _frame):
    raise KeyboardInterrupt("SIGTERM")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--receipt", required=True, type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--activate-reviewed", action="store_true")
    action.add_argument("--rollback-reviewed", action="store_true")
    args = parser.parse_args()
    receipt_dir = SafeRoot(exact_path(args.receipt.parent, directory=True))
    require(not os.path.lexists(args.receipt), "receipt exists")
    result = {"plan_sha256": args.plan_sha256, "status": "PRECHECK_FAILED", "action": (
        "rollback" if args.rollback_reviewed else "activate")}
    signal.signal(signal.SIGTERM, terminate)
    try:
        plan = json.loads(checked(args.plan, args.plan_sha256))
        run(plan, args.plan_sha256, result, rollback=args.rollback_reviewed)
    except BaseException as error:
        result.setdefault("error", f"{type(error).__name__}: {error}")
        raise
    finally:
        result["recorded_at"] = now()
        receipt_dir.write_bytes(args.receipt.name, encode(result), require_absent=True)


if __name__ == "__main__":
    main()
