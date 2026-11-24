"""Exercise group publication and recovery with inert LaunchAgent doubles."""

from contextlib import nullcontext
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys

import pytest

from ops import switch_reviewed_v4_release as switch


class SimulatedLaunchAgents:
    def __init__(self, roles):
        self.by_label = {role["label"]: role for role in roles}
        self.by_path = {str(role["path"]): role for role in roles}
        self.loaded = {label: self.state(role, "old") for label, role in self.by_label.items()}
        self.before_bootstrap = lambda role, side: None
        self.changes = []

    @staticmethod
    def state(role, side):
        return {"cwd": role[f"{side}_cwd"], "path": str(role["path"]),
                "loaded_manifest_sha256": role[f"{side}_manifest_sha"],
                "pid": None if role["role"] == "stage" else 117}

    def bootstrap(self, action, domain, path):
        assert (action, domain) == ("bootstrap", "test-domain")
        role = self.by_path[path]
        side = "old" if role["path"].read_bytes() == role["old"] else "new"
        self.before_bootstrap(role, side)
        self.loaded[role["label"]] = self.state(role, side)
        self.changes.append(("load", role["role"], side))

    def verify(self, name, cwd, path, manifest_sha):
        role = self.by_path[str(path)]
        state = self.loaded[role["label"]]
        assert role["role"] == name and state["cwd"] == cwd and state["loaded_manifest_sha256"] == manifest_sha
        return state

    def unload(self, role):
        del self.loaded[role["label"]]
        self.changes.append(("unload", role["role"]))

    @staticmethod
    def write(path, raw, prior):
        assert path.read_bytes() == prior
        path.write_bytes(raw)

    def helpers(self):
        return {"DOMAIN": "test-domain", "loaded": self.loaded.get, "verify_loaded": self.verify,
                "role_idle": lambda role: None, "unload": self.unload, "write_atomic": self.write,
                "scheduler_idle": lambda pid, cfg: None, "run_ctl": self.bootstrap,
                "manager_root": lambda env, sha: None, "manager_idle": lambda root: 0,
                "announcement_flash_cutover_guard": lambda root: nullcontext({})}


def put(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return {"path": str(path), "sha256": switch.digest(body)}


@pytest.fixture
def cohort(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    activation = root / "activation"
    activation.mkdir(mode=0o700)
    agents = root / "LaunchAgents"
    candidates = root / "candidates"
    monkeypatch.setattr(switch, "ROOT", root)
    monkeypatch.setattr(switch, "LAUNCH_AGENTS", agents)
    monkeypatch.setattr(switch, "CANDIDATES", candidates)
    repo = Path(__file__).resolve().parents[1]
    source_commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    plan = {"roles": [], "activation_directory": str(activation), "prior_active_sha256": None,
            "manager_config_sha256": "fixture-manager", "audited_switch": {},
            "verification_command": [sys.executable, "-B", "-c", "pass"]}
    approval = {"verdict": "PASS", "roles": {}}
    for name in switch.GROUP:
        prior = candidates / f"prior-{name}"
        next_root = candidates / f"next-{name}"
        prior_app, next_app = prior / "app", next_root / "app"
        prior_app.mkdir(parents=True)
        overlays = [put(next_app / "overlay.py", name.encode())]
        if name == "stage":
            main_row = plan["roles"][1]
            main_root = candidates / main_row["candidate_release_id"]
            overlays.append(put(next_app / "stage_center_tick_config.json", switch.encode({
                "research_owner_binding": {"app_root": str(main_root / "app"), "release_id": main_root.name,
                                           "manifest_path": str(main_root / "startup-manifest.json"),
                                           "manifest_sha256": main_row["candidate_manifest_sha256"]}})))
        prior_id = put(prior / "release-manifest.json", switch.encode({
            "release_id": prior.name, "app_root": str(prior_app)}))
        next_id = put(next_root / "startup-manifest.json", switch.encode({
            "release_id": next_root.name, "app_root": str(next_app),
            "source_root": str(repo), "source_commit": source_commit,
            "application_inventory": {"entries": [{"path": Path(overlay["path"]).name, "kind": "file",
                                                   "sha256": overlay["sha256"]} for overlay in overlays]}}))
        (next_root / "release-manifest.json").symlink_to(activation / "active" / next_root.name / "release-manifest.json")
        label = switch.LABELS[name]
        old_cfg = plistlib.dumps(config(label, prior_app, prior_id))
        new_cfg = plistlib.dumps(config(label, next_app, next_id))
        put(agents / f"{label}.plist", old_cfg)
        put(agents / f".{label}.release.lock.mutex", b"")
        old_ref = put(next_root / "rollback.plist", old_cfg)
        new_ref = put(next_root / "proposed.plist", new_cfg)
        record = {"role": name, "rollback_plist": old_ref["path"], "candidate_plist": new_ref["path"],
                  "current_plist_sha256": old_ref["sha256"], "candidate_plist_sha256": new_ref["sha256"],
                  "current_manifest_sha256": prior_id["sha256"], "candidate_manifest_sha256": next_id["sha256"],
                  "candidate_release_id": next_root.name}
        plan["roles"].append(record)
        approval["roles"][name] = {**record, "delta_files": overlays, "source_commit": source_commit}
    # The historical Stage owner intentionally differs from the prior Main's app.
    legacy_owner = candidates / "historical-main"
    legacy_app = legacy_owner / "app"
    legacy_app.mkdir(parents=True)
    owner_manifest = put(legacy_owner / "release-manifest.json", switch.encode({
        "release_id": legacy_owner.name, "app_root": str(legacy_app)}))
    stage_cfg = put(candidates / "prior-stage/app/stage_center_tick_config.json", switch.encode({
        "research_owner_binding": {"app_root": str(legacy_app), "release_id": legacy_owner.name,
                                   "manifest_path": owner_manifest["path"],
                                   "manifest_sha256": owner_manifest["sha256"]}}))
    plan["prior_stage_config_sha256"] = stage_cfg["sha256"]
    plan["review_approval"] = put(root / "approval.json", switch.encode(approval))
    roles = [switch.load_role(record, approval["roles"][record["role"]], activation, rollback=False)
             for record in plan["roles"]]
    simulated = SimulatedLaunchAgents(roles)
    monkeypatch.setattr(switch, "load_audited_switch", lambda ref: simulated.helpers())
    return plan, simulated, roles, activation


def config(label, app, manifest):
    return {"Label": label, "WorkingDirectory": str(app),
            "ProgramArguments": ["--config", str(app / "stage_center_tick_config.json")],
            "EnvironmentVariables": {"V4_APP_ROOT": str(app), "V4_RELEASE_MANIFEST_PATH": manifest["path"],
                                     "V4_RELEASE_MANIFEST_SHA256": manifest["sha256"],
                                     "V4_RELEASE_ID": app.parent.name,
                                     "V4_MANAGER_WORKBENCH_CONFIG_PATH": "/exact/manager.json"}}


def run(plan, result, *, rollback=False):
    plan_sha = switch.digest(switch.encode(plan))
    switch.run(plan, plan_sha, result, rollback=rollback)
    return plan_sha


def reseal_plist(plan, index, mutate):
    row = plan["roles"][index]
    path = Path(row["candidate_plist"])
    proposed = plistlib.loads(path.read_bytes())
    mutate(proposed)
    row["candidate_plist_sha256"] = put(path, plistlib.dumps(proposed))["sha256"]
    path = Path(plan["review_approval"]["path"])
    approval = json.loads(path.read_bytes())
    approval["roles"][row["role"]]["candidate_plist_sha256"] = row["candidate_plist_sha256"]
    plan["review_approval"] = put(path, switch.encode(approval))


def test_rejects_candidate_app_root_drift_even_with_reviewed_plist(cohort):
    plan, simulated, _, activation = cohort
    reseal_plist(plan, 0, lambda cfg: cfg["EnvironmentVariables"].update(V4_APP_ROOT="/wrong/app"))
    with pytest.raises(RuntimeError, match="candidate plist app root mismatch: api"):
        run(plan, {})
    assert simulated.changes == []
    assert not (activation / "pending.json").exists()


@pytest.mark.parametrize("key,value", [("WatchPaths", ["/tmp/path"]), ("StandardOutPath", "/tmp/out")])
def test_rejects_non_relocation_plist_changes_even_with_reviewed_plist(cohort, key, value):
    plan, simulated, _, activation = cohort
    reseal_plist(plan, 0, lambda cfg: cfg.update({key: value}))
    with pytest.raises(RuntimeError, match=f"non-relocation LaunchAgent keys changed: api {key}"):
        run(plan, {})
    assert simulated.changes == []
    assert not (activation / "pending.json").exists()


@pytest.mark.parametrize("command", [None, [], "echo ok", [""], [42]])
def test_rejects_absent_or_invalid_verification_argv(cohort, command):
    plan, simulated, _, activation = cohort
    plan.pop("verification_command")
    if command is not None:
        plan["verification_command"] = command
    with pytest.raises(RuntimeError, match="sealed nonempty verification argv"):
        run(plan, {})
    assert simulated.changes == []
    assert not (activation / "pending.json").exists()


def test_failing_verification_cannot_publish_live_manifest(cohort):
    plan, _, roles, activation = cohort
    plan["verification_command"] = [sys.executable, "-B", "-c", "raise SystemExit(23)"]
    result = {}
    with pytest.raises(subprocess.CalledProcessError) as error:
        run(plan, result)
    assert error.value.returncode == 23
    assert result["status"] == "ROLLED_BACK"
    assert all(role["path"].read_bytes() == role["old"] and not role["alias"].exists() for role in roles)
    assert not (activation / "active").exists()


def test_syncs_published_parent_before_advancing_pointer(cohort, monkeypatch):
    plan, _, _, activation = cohort
    syncs = []
    sync_directory = switch.sync_directory
    switch_pointer = switch.switch_pointer

    def capture_sync(directory):
        sync_directory(directory)
        syncs.append(directory)

    def check_precondition(directory, expected, target):
        if target:
            assert (directory / target).parent in syncs
        switch_pointer(directory, expected, target)

    monkeypatch.setattr(switch, "sync_directory", capture_sync)
    monkeypatch.setattr(switch, "switch_pointer", check_precondition)
    result = {}
    run(plan, result)
    assert result["status"] == "DEPLOYED"
    assert (activation / "active").exists()


def test_commits_all_role_manifests_then_restores_exact_preimage(cohort):
    plan, simulated, roles, activation = cohort
    startup_bytes = [role["new_manifest"].read_bytes() for role in roles]

    def check_unpublished(role, side):
        assert all(not row["alias"].exists() for row in roles)
        assert not (activation / "active").exists()

    simulated.before_bootstrap = check_unpublished
    result = {}
    plan_sha = run(plan, result)
    assert result["status"] == "DEPLOYED"
    assert not (activation / "pending.json").exists()
    group = json.loads((activation / "active/group-manifest.json").read_bytes())
    assert set(group["roles"]) == set(switch.GROUP)
    for role, startup in zip(roles, startup_bytes):
        raw = role["alias"].read_bytes()
        identity = json.loads(raw)
        assert group["roles"][role["role"]]["sha256"] == switch.digest(raw)
        assert (identity["activation_status"], identity["deployment_status"]) == ("ACTIVE", "LIVE")
        assert identity["plan_sha256"] == plan_sha
        assert identity["source_commit"] == role["identity"]["source_commit"]
        assert identity["overlay_files"]["overlay.py"] == switch.digest(role["role"].encode())
        assert identity["overlay_files"] == role["identity"]["overlay_files"]
        assert identity["plist_sha256"] == switch.digest(role["path"].read_bytes())
        assert identity["startup_manifest"]["sha256"] == switch.digest(startup)
        assert role["new_manifest"].read_bytes() == startup

    # A broken candidate startup file cannot prevent restoration from intact preimages.
    roles[0]["new_manifest"].write_bytes(b"bad candidate")
    restored = {}
    run(plan, restored, rollback=True)
    assert restored["status"] == "ROLLED_BACK"
    assert all(role["path"].read_bytes() == role["old"] and not role["alias"].exists() for role in roles)
    assert not os.path.lexists(activation / "active")
    assert not (activation / "pending.json").exists()


def test_partial_launch_failure_rolls_back_without_publishing(cohort):
    plan, simulated, roles, activation = cohort

    def fail_stage(role, side):
        if role["role"] == "stage" and side == "new":
            raise RuntimeError("stage bootstrap failed")

    simulated.before_bootstrap = fail_stage
    result = {}
    with pytest.raises(RuntimeError, match="stage bootstrap failed"):
        run(plan, result)
    assert result["status"] == "ROLLED_BACK"
    assert set(result["restored"]) == set(switch.GROUP)
    assert all(role["path"].read_bytes() == role["old"] and not role["alias"].exists() for role in roles)
    assert not (activation / "pending.json").exists()


def test_recovers_durable_interruption_with_unloaded_and_mixed_roles(cohort):
    plan, simulated, roles, activation = cohort
    plan_sha = switch.digest(switch.encode(plan))
    io = switch.SafeRoot(activation)
    io.write_bytes(f"transaction-{plan_sha}/intent.json",
                   switch.encode({"plan_sha256": plan_sha, "prior_active": None}))
    io.write_bytes("pending.json", switch.encode({"plan_sha256": plan_sha}))
    api, main, stage = roles
    for role in roles:
        simulated.unload(role)
    api["path"].write_bytes(api["new"])
    simulated.bootstrap("bootstrap", "test-domain", str(api["path"]))
    main["path"].write_bytes(main["new"])

    with pytest.raises(RuntimeError, match="pending activation"):
        run(plan, {})
    result = {}
    run(plan, result, rollback=True)
    assert result["status"] == "ROLLED_BACK"
    assert all(role["path"].read_bytes() == role["old"] for role in (api, main, stage))
    assert not (activation / "pending.json").exists()


def test_rollback_foreign_bytes_retains_journal_and_leaves_jobs_alone(cohort):
    plan, simulated, roles, activation = cohort
    run(plan, {})
    roles[2]["path"].write_bytes(b"foreign update")
    changes_before = simulated.changes[:]
    result = {}
    with pytest.raises(RuntimeError, match="rollback plist drift: stage"):
        run(plan, result, rollback=True)
    assert result["status"] == "ROLLBACK_INCOMPLETE"
    assert (activation / "pending.json").is_file()
    assert simulated.changes == changes_before
    assert roles[2]["path"].read_bytes() == b"foreign update"


def test_rejects_drift_in_reviewed_overlay_before_touching_roles(cohort):
    plan, simulated, roles, activation = cohort
    Path(roles[0]["approved_files"][0]["path"]).write_bytes(b"drift")
    with pytest.raises(RuntimeError, match="SHA drift"):
        run(plan, {})
    assert simulated.changes == []
    assert not (activation / "pending.json").exists()


def test_preserves_exact_prior_group_pointer_on_failure(cohort):
    plan, simulated, roles, activation = cohort
    prior_plan = "e" * 64
    prior_target = f"transaction-{prior_plan}/published"
    io = switch.SafeRoot(activation)
    metadata = {"activation_status": "ACTIVE", "deployment_status": "LIVE", "plan_sha256": prior_plan}
    for role in roles:
        release_id = f"prior-{role['role']}"
        raw = switch.encode({**metadata, "release_id": release_id})
        io.write_bytes(f"{prior_target}/{release_id}/release-manifest.json", raw)
        metadata.setdefault("roles", {})[role["role"]] = {"release_id": release_id, "sha256": switch.digest(raw)}
    previous = switch.encode(metadata)
    pointer_file = f"{prior_target}/group-manifest.json"
    io.write_bytes(pointer_file, previous)
    (activation / "active").symlink_to(prior_target)
    plan["prior_active_sha256"] = switch.digest(previous)

    def fail_main(role, side):
        assert not (activation / "active").exists()
        if role["role"] == "main" and side == "new":
            raise RuntimeError("failed during switch")

    simulated.before_bootstrap = fail_main
    with pytest.raises(RuntimeError, match="failed during switch"):
        run(plan, {})
    assert (activation / "active").readlink() == Path(prior_target)
    assert (activation / "active/group-manifest.json").read_bytes() == previous


def test_intent_only_interruption_allows_identical_seal(cohort):
    plan, _, _, activation = cohort
    plan_sha = switch.digest(switch.encode(plan))
    switch.SafeRoot(activation).write_bytes(
        f"transaction-{plan_sha}/intent.json",
        switch.encode({"plan_sha256": plan_sha, "prior_active": None}),
    )
    result = {}
    run(plan, result)
    assert result["status"] == "DEPLOYED"
