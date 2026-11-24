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
import time
from contextlib import ExitStack
from datetime import datetime
from uuid import uuid4

from infrastructure.interprocess_lock import owned_interprocess_lock
from infrastructure.owned_io import SafeRoot


GROUP = ("api", "main", "stage")
MAIN_POLICY_REBIND = "main_policy_rebind"
MAIN_POLICY_ROLLBACK_DRAIN_SECONDS = 45
POLICY_PATH = "V4_RESEARCH_RETENTION_POLICY"
POLICY_SHA = "V4_RESEARCH_RETENTION_POLICY_SHA256"
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


def policy_binding(cfg, app):
    env = cfg["EnvironmentVariables"]
    policy_ref = {"path": env[POLICY_PATH], "sha256": env[POLICY_SHA]}
    policy = json.loads(checked(policy_ref["path"], policy_ref["sha256"]))
    pins_ref = policy["managed_pin_inventory"]
    pins = json.loads(checked(pins_ref["path"], pins_ref["sha256"]))
    binding = {"schema_version": "v4.main_storage_binding.v1", "app_root": str(app),
               "policy_path": policy_ref["path"], "policy_sha256": policy_ref["sha256"],
               "managed_pin_inventory_path": pins_ref["path"], "managed_pin_inventory_sha256": pins_ref["sha256"]}
    return binding, policy, pins


def load_main_policy_rebind(row, approval, directory, prior_sha):
    name, label = "main", LABELS["main"]
    path = LAUNCH_AGENTS / f"{label}.plist"
    require(all(row[key] == approval[key] for key in (
        "candidate_release_id", "candidate_plist_sha256", "candidate_manifest_sha256",
        "candidate_storage_policy", "candidate_managed_pins",
    )), "Main policy rebind plan/review mismatch")
    old = checked(row["rollback_plist"], row["current_plist_sha256"])
    new_path = exact_path(row["candidate_plist"])
    new_path.parent.relative_to(CANDIDATES)
    new = checked(new_path, row["candidate_plist_sha256"])
    old_cfg, new_cfg = plistlib.loads(old), plistlib.loads(new)
    old_env = old_cfg["EnvironmentVariables"]
    new_env = new_cfg["EnvironmentVariables"]
    rebound = {**old_cfg, "EnvironmentVariables": {
        **old_env, POLICY_PATH: new_env[POLICY_PATH], POLICY_SHA: new_env[POLICY_SHA],
    }}
    require(old_cfg["Label"] == label and new_cfg == rebound and old != new,
            "Main policy rebind may only change policy path and SHA")
    startup_sha = row["current_manifest_sha256"]
    require(row["candidate_manifest_sha256"] == startup_sha, "Main startup identity changed")
    app, manifest, startup_data = startup(old_cfg, startup_sha, candidate=True)
    release_id = row["candidate_release_id"]
    require(release_id == app.parent.name == startup_data["release_id"]
            and startup_data["source_commit"] == approval["source_commit"],
            "Main policy rebind startup identity mismatch")
    old_binding, old_policy, old_pins = policy_binding(old_cfg, app)
    new_binding, new_policy, new_pins = policy_binding(new_cfg, app)
    require(row["candidate_storage_policy"] == {"path": new_env[POLICY_PATH], "sha256": new_env[POLICY_SHA]}
            and row["candidate_managed_pins"] == new_policy["managed_pin_inventory"]
            and Path(new_env[POLICY_PATH]) == new_path.parent / "control/policy.json"
            and Path(new_binding["managed_pin_inventory_path"]) == new_path.parent / "control/managed-pins.json",
            "Main policy rebind detached control references disagree")
    require(new_policy == {**old_policy, "managed_pin_inventory": row["candidate_managed_pins"]}
            and new_policy["governance"]["ordinary_peak_budget_bytes"] == 261 * 2**30
            and new_pins == {**old_pins, "expected_main_app_root": str(app)}
            and old_pins["expected_main_app_root"] != str(app),
            "Main policy rebind changed governance semantics")
    alias = app.parent / "release-manifest.json"
    require(link(alias) == str(directory / "active" / release_id / alias.name),
            "Main policy rebind requires existing active role alias")
    return {"role": name, "label": label, "path": path, "old": old, "new": new,
            "old_cfg": old_cfg, "new_cfg": new_cfg, "old_cwd": str(app), "new_cwd": str(app),
            "old_manifest": manifest, "new_manifest": manifest, "old_manifest_sha": startup_sha,
            "new_manifest_sha": startup_sha, "alias": alias, "prior_active_sha": prior_sha,
            "policy_rebind": {"old": old_binding, "new": new_binding}}


def main_rebind_group(ops, directory, prior, role):
    require(prior is not None and prior["sha256"] == role["prior_active_sha"],
            "Main policy rebind has no matching prior group")
    root = directory / prior["target"]
    group = json.loads(checked(root / "group-manifest.json", prior["sha256"]))
    entries = {}
    for name, entry in group["roles"].items():
        release_id = entry["release_id"]
        raw = checked(root / release_id / "release-manifest.json", entry["sha256"])
        identity = json.loads(raw)
        plist = LAUNCH_AGENTS / f"{LABELS[name]}.plist"
        require(identity["role"] == name and identity["release_id"] == release_id
                and identity["plist_path"] == str(plist),
                f"invalid prior ACTIVE role identity: {name}")
        if name == "main":
            require(identity["plist_sha256"] == digest(role["old"])
                    and identity["startup_manifest"] == {"path": str(role["old_manifest"]),
                                                          "sha256": role["old_manifest_sha"]}
                    and identity["app_root"] == role["old_cwd"]
                    and entry["path"] == str(role["alias"]),
                    "Main policy rebind preimage does not match ACTIVE role")
        else:
            cfg = plistlib.loads(checked(plist, identity["plist_sha256"]))
            app, manifest, data = startup(cfg, identity["startup_manifest"]["sha256"], candidate=True)
            require(identity["app_root"] == str(app)
                    and identity["startup_manifest"]["path"] == str(manifest)
                    and data["release_id"] == release_id
                    and link(Path(entry["path"])) == str(directory / "active" / release_id / "release-manifest.json"),
                    f"companion role identity drift: {name}")
            ops["verify_loaded"](name, str(app), plist, identity["startup_manifest"]["sha256"])
        entries[name] = (entry, raw)
    return entries


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


def loaded_role(ops, role):
    state = ops["loaded"](role["label"])
    if state and "policy_rebind" in role:
        result = ops["ctl"]("print", f"{ops['DOMAIN']}/{role['label']}")
        # A failed bootstrap can leave the exact LaunchAgent registered without
        # a PID. Match the registration and optional PID before trusting its
        # configured policy, so this state can be rolled back.
        registration = {
            "path = ": [state["path"]],
            "working directory = ": [state["cwd"]],
            "V4_RELEASE_MANIFEST_SHA256 => ": [state["loaded_manifest_sha256"]],
            "pid = ": [] if state["pid"] is None else [str(state["pid"])],
        }

        def read_field(prefix):
            return re.findall(rf"^[ \t]*{re.escape(prefix)}([^\r\n]*)$", result.stdout, re.M)

        require(result.returncode == 0 and all(read_field(prefix) == expected
                for prefix, expected in registration.items()), "Main changed during policy readback")
        values = {}
        for key in (POLICY_PATH, POLICY_SHA):
            lines = read_field(f"{key} => ")
            require(len(lines) == 1 and lines[0], f"Main loaded policy identity missing: {key}")
            values[key] = lines[0]
        state = {**state, "policy": values}
    return state


def state_matches(state, role, side):
    if not (state is not None and state["cwd"] == role[f"{side}_cwd"] and state["path"] == str(role["path"])
            and state["loaded_manifest_sha256"] == role[f"{side}_manifest_sha"]):
        return False
    if "policy_rebind" not in role:
        return True
    expected = role["policy_rebind"][side]
    return state["policy"] == {POLICY_PATH: expected["policy_path"], POLICY_SHA: expected["policy_sha256"]}


def verify(ops, role, side):
    expected = role[side]
    require(exact_path(role["path"]).read_bytes() == expected, f"live plist drift: {role['role']}")
    checked(role[f"{side}_manifest"], role[f"{side}_manifest_sha"])
    state = ops["verify_loaded"](role["role"], role[f"{side}_cwd"], role["path"], role[f"{side}_manifest_sha"])
    if "policy_rebind" in role:
        binding, _, _ = policy_binding(role[f"{side}_cfg"], Path(role[f"{side}_cwd"]))
        require(binding == role["policy_rebind"][side], "Main policy binding drift")
        observed = loaded_role(ops, role)
        require(state_matches(observed, role, side) and observed["pid"] is not None
                and observed["pid"] == state["pid"], f"Main loaded policy or ready PID mismatch: {side}")
        return observed
    return state


def install_group(ops, roles, plan):
    # Unload dependency consumers before the Main daemon. Restore/start in forward order.
    for role in reversed(roles):
        ops["role_idle"](role)
        require(state_matches(loaded_role(ops, role), role, "old"), f"loaded preimage drift: {role['role']}")
        ops["unload"](role)
    for role in roles:
        ops["write_atomic"](role["path"], role["new"], role["old"])
        sync_directory(role["path"].parent)
        ops["run_ctl"]("bootstrap", ops["DOMAIN"], str(role["path"]))
        verify(ops, role, "new")
    subprocess.run(plan["verification_command"], check=True, timeout=120)
    return {role["role"]: verify(ops, role, "new") for role in roles}


def publish(io, directory, target, roles, observations, plan_sha, *, prior=None, carried=None):
    manifests = {}
    activated_at = now()
    status = {"activation_status": "ACTIVE", "deployment_status": "LIVE",
              "plan_sha256": plan_sha, "activated_at": activated_at}
    if carried is not None:
        main = roles[0]
        for name, (entry, raw) in carried.items():
            if name == "main":
                identity = json.loads(raw)
                identity.update(status, plist_sha256=digest(main["new"]), loaded=observations["main"],
                                main_storage_binding=main["policy_rebind"]["new"])
                raw = encode(identity)
                entry = {**entry, "sha256": digest(raw)}
            io.write_bytes(f"{target}/{entry['release_id']}/release-manifest.json", raw, require_absent=True)
            manifests[name] = entry
    for role in roles if carried is None else ():
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
    switch_pointer(directory, prior["target"] if carried is not None else None, target)
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


def wait_main_rebind_idle(ops, role):
    deadline = time.monotonic() + MAIN_POLICY_ROLLBACK_DRAIN_SECONDS
    while True:
        require(exact_path(role["path"]).read_bytes() == role["new"], "Main rollback plist changed during drain")
        state = loaded_role(ops, role)
        if state is None:
            return None
        require(state_matches(state, role, "new"), "Main rollback registration changed during drain")
        if state["pid"] is None:
            return state
        try:
            ops["scheduler_idle"](state["pid"], role["new_cfg"])
        except RuntimeError as error:
            reason = str(error)
            if (not reason.startswith("Main has live child processes:")
                    and reason != "Main dispatch cycle has pending work or unavailable state"):
                raise
        else:
            if loaded_role(ops, role) == state:
                return state
            reason = "Main registration changed after the idle check"
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(
                f"Main rollback pending after drain deadline ({reason}). "
                "Retry --rollback-reviewed with the same sealed plan once Main is idle."
            )
        time.sleep(min(1, remaining))


def restore_group(ops, roles, directory, target, prior):
    current = link(directory / "active")
    prior_target = prior["target"] if prior else None
    require(current in (None, target, prior_target), "a different release owns the active pointer")
    # Preflight each exact pair before making any rollback changes. Unknown jobs
    # or plist bytes are left in place with the recovery journal intact.
    states = {}
    for role in roles:
        state = loaded_role(ops, role)
        payload = exact_path(role["path"]).read_bytes()
        require(payload in (role["old"], role["new"]), f"rollback plist drift: {role['role']}")
        if state is not None:
            side = "old" if payload == role["old"] else "new"
            require(state_matches(state, role, side), f"rollback loaded identity drift: {role['role']}")
            if side == "new" and role["role"] == "stage":
                require(not state["pid"], "Stage job is running")
            if side == "new" and role["role"] == "main" and state["pid"]:
                if "policy_rebind" in role:
                    state = wait_main_rebind_idle(ops, role)
                else:
                    ops["scheduler_idle"](state["pid"], role["new_cfg"])
        states[role["role"]] = (state, payload)
    policy_rebind = "policy_rebind" in roles[0]
    if current == target and not policy_rebind:
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
        switch_pointer(directory, target if current == target and policy_rebind else None, prior_target)
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
    policy_rebind = "policy_rebind" in roles[0]
    if policy_rebind:
        main_rebind_group(ops, directory, prior, roles[0])
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
        if prior is not None and not policy_rebind:
            switch_pointer(directory, prior["target"], None)
        observations = install_group(ops, roles, plan)
        if policy_rebind:
            carried = main_rebind_group(ops, directory, prior, roles[0])
            result["active_release"] = publish(io, directory, target, roles, observations, plan_sha,
                                               prior=prior, carried=carried)
        else:
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
    kind = plan.get("transaction_kind")
    policy_rebind = kind == MAIN_POLICY_REBIND
    require((kind is None and group == GROUP) or (policy_rebind and group == ("main",)),
            "expected exact API/Main/Stage role group and order or reviewed Main policy rebind")
    if not rollback:
        command = plan.get("verification_command")
        require(isinstance(command, list) and command and command[0]
                and all(isinstance(arg, str) and "\x00" not in arg for arg in command),
                "activation requires a sealed nonempty verification argv")
    reference = plan["review_approval"]
    approval = json.loads(checked(reference["path"], reference["sha256"]))
    require(approval["verdict"] == "PASS" and set(approval["roles"]) == set(group)
            and approval.get("transaction_kind") == kind, "group review mismatch")
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
        if policy_rebind:
            roles = [load_main_policy_rebind(plan["roles"][0], approval["roles"]["main"], directory,
                                             plan["prior_active_sha256"])]
        else:
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
