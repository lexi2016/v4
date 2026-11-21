from __future__ import annotations

from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
import plistlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "main_only_cutover.py"
SPEC = importlib.util.spec_from_file_location("r4_main_only_cutover_tests", SOURCE)
CUTOVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CUTOVER)
GATE_SOURCE = SOURCE.parent / "candidate_qfq_gate.py"
GATE_SPEC = importlib.util.spec_from_file_location("r4_candidate_qfq_gate_tests", GATE_SOURCE)
GATE = importlib.util.module_from_spec(GATE_SPEC)
GATE_SPEC.loader.exec_module(GATE)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, value: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    path.write_bytes(raw)
    return sha(raw)


class FakeController:
    LABELS = {"main": "com.lexi.v4.scheduler"}

    def __init__(self, root: Path, events: list[str]):
        self.LAUNCH_AGENTS = root / "LaunchAgents"
        self.LAUNCH_AGENTS.mkdir()
        self.events = events
        self.activation_result = None
        self.activation_exception = None
        (self.LAUNCH_AGENTS / ".com.lexi.v4.scheduler.release.lock.mutex").touch()
        self.role = {"label": self.LABELS["main"], "path": root / "launchd.plist",
                     "old_cfg": {"EnvironmentVariables": {"V4_DISPATCH_LEDGER_ROOT": str(root)}},
                     "new_cfg": {}, "before": {"pid": 7}}
        self.role["path"].write_bytes(plistlib.dumps({"fixture": "old"}))

    @staticmethod
    @contextmanager
    def owned_interprocess_lock(*args, **kwargs):
        yield

    def load_role(self, row, approved):
        self.events.append("load_role")
        return self.role

    def activate(self, roles, plan, result):
        self.events.append("activate")
        self.asserted_roles = [row["label"] for row in roles]
        result.update(self.activation_result or {"status": "DEPLOYED"})
        if self.activation_exception:
            raise RuntimeError(self.activation_exception)


class FakeRollbackController:
    LABELS = {"main": "com.lexi.v4.scheduler"}
    DOMAIN = "gui/test"

    def __init__(self, launch_agents: Path, live: Path, new_cfg: dict, new_manifest_sha: str,
                 *, fail_bootstrap_count: int = 0):
        self.LAUNCH_AGENTS = launch_agents
        self.live = live
        self.new_cfg = new_cfg
        self.new_manifest_sha = new_manifest_sha
        self.fail_bootstrap_count = fail_bootstrap_count
        self.state = {"cwd": new_cfg["WorkingDirectory"], "path": str(live),
                      "loaded_manifest_sha256": new_manifest_sha, "pid": 27}
        self.scheduler_idle_calls = 0
        self.unload_calls = 0
        self.write_calls = 0
        (launch_agents / ".com.lexi.v4.scheduler.release.lock.mutex").touch()

    @staticmethod
    @contextmanager
    def owned_interprocess_lock(*args, **kwargs):
        yield

    def loaded(self, label):
        return dict(self.state) if self.state is not None else None

    def scheduler_idle(self, pid, cfg):
        self.scheduler_idle_calls += 1

    def unload(self, role):
        self.unload_calls += 1
        self.state = None

    def write_atomic(self, path, raw, previous):
        if path.read_bytes() != previous:
            raise RuntimeError("fixture CAS mismatch")
        path.write_bytes(raw)
        self.write_calls += 1

    def run_ctl(self, action, domain, path):
        if action != "bootstrap":
            raise AssertionError(action)
        if self.fail_bootstrap_count:
            self.fail_bootstrap_count -= 1
            raise RuntimeError("fixture transient bootstrap failure")
        cfg = plistlib.loads(Path(path).read_bytes())
        env = cfg.get("EnvironmentVariables", {})
        self.state = {"cwd": cfg["WorkingDirectory"], "path": path,
                      "loaded_manifest_sha256": env.get("V4_RELEASE_MANIFEST_SHA256"), "pid": 28}

    def verify_loaded(self, role, cwd, path, manifest_sha):
        state = self.loaded(self.LABELS[role])
        if (not state or state["cwd"] != cwd or state["path"] != str(path)
                or state["loaded_manifest_sha256"] != manifest_sha or not state["pid"]):
            raise RuntimeError("fixture loaded identity mismatch")
        return state


class MainOnlyCutoverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="v4-r4-cutover-fixture-")
        # The controller intentionally rejects aliases such as macOS /var -> /private/var.
        self.root = Path(self.tmp.name).resolve(strict=True)

    def tearDown(self):
        self.tmp.cleanup()

    def receipts(self, *, same_date=False, stale=False, category_limit=100_000_000_000):
        old = {"status": "CANNOT_CONFIRM", "migration": "BLOCKED", "reviewer": "CHAT",
               "old_task_key": "a" * 64, "old_target_date": "20261120",
               "old_row_sha256": "b" * 64, "old_category_remaining_bytes": CUTOVER.OLD_CATEGORY_REMAINING,
               "old_physical_peak_remaining_bytes": CUTOVER.OLD_PHYSICAL_REMAINING}
        new = {"status": "PASS", "evidence_closed": True, "reviewer": "CHAT",
               "release_id": "release-r5",
               "target_date": "20261120" if same_date else "20261123", "classification_basis": "DISTINCT_DATE",
               "task_key": "c" * 64, "computation_identity_sha256": "c" * 64,
               "expected_child_environment_sha256": "d" * 64, "expected_child_python_sha256": "e" * 64,
               "old_task_key": old["old_task_key"], "old_row_sha256": old["old_row_sha256"],
               "old_category_remaining_bytes": CUTOVER.OLD_CATEGORY_REMAINING,
               "old_physical_peak_remaining_bytes": CUTOVER.OLD_PHYSICAL_REMAINING,
               "migration": "BLOCKED", "registry_sha256": "f" * 64,
               "predicted_peak_bytes": 10_000_000_000, "category": "ordinary",
               "qfq_kwargs": {"refresh_inputs": False}, "child_python_args": ["-B"],
               "candidate_policy_sha256": "1" * 64, "candidate_classification_sha256": "2" * 64,
               "required_unclassified_task_keys": ["a" * 64, "9" * 64]}
        capacity = {"status": "PASS", "evidence_closed": True, "reviewer": "CHAT",
                    "target_date": new["target_date"], "task_key": new["task_key"],
                    "registry_sha256": new["registry_sha256"], "old_row_sha256": old["old_row_sha256"],
                    "old_category_remaining_bytes": CUTOVER.OLD_CATEGORY_REMAINING,
                    "old_physical_peak_remaining_bytes": CUTOVER.OLD_PHYSICAL_REMAINING,
                    "category_used_bytes": 1_000_000_000,
                    "category_other_remaining_bytes": CUTOVER.OLD_CATEGORY_REMAINING,
                    "measured_at": "2000-01-01T00:00:00+00:00" if stale else CUTOVER.datetime.now().astimezone().isoformat()}
        cache = {"status": "PASS", "evidence_closed": True, "reviewer": "CHAT",
                 "runtime_release_id": "release-r5"}
        refs = {}
        for name, payload in (("old_task_unique_attribution", old),
                              ("new_date_reviewed_classification", new),
                              ("actual_capacity_preflight", capacity),
                              ("final_cache_negative", cache)):
            path = self.root / f"{name}.json"
            refs[name] = {"path": str(path), "sha256": write_json(path, payload)}
        return refs, old, new, capacity

    def test_distinct_date_scope_can_keep_d20_attribution_unknown(self):
        refs, _, _, _ = self.receipts()
        plan = {"target_date": "20261123", "release_id": "release-r5", "admission_evidence": refs}
        result = CUTOVER.check_evidence(plan)
        self.assertEqual(result["old_task_unique_attribution"]["status"], "CANNOT_CONFIRM")
        self.assertEqual(result["new_date_reviewed_classification"]["classification_basis"], "DISTINCT_DATE")

    def test_same_date_does_not_reuse_distinct_date_classification(self):
        refs, _, _, _ = self.receipts(same_date=True)
        plan = {"target_date": "20261120", "release_id": "release-r5", "admission_evidence": refs}
        with self.assertRaisesRegex(CUTOVER.CutoverBlocked, "NEW_DATE_CLASSIFICATION_BINDING_DRIFT"):
            CUTOVER.check_evidence(plan)

    def test_stale_capacity_proof_blocks(self):
        refs, _, _, _ = self.receipts(stale=True)
        plan = {"target_date": "20261123", "release_id": "release-r5", "admission_evidence": refs}
        with self.assertRaisesRegex(CUTOVER.CutoverBlocked, "CAPACITY_PREFLIGHT_STALE_OR_UNDATED"):
            CUTOVER.check_evidence(plan)

    def test_user_authorization_binds_external_plan_chat_and_note_hashes(self):
        refs, _, _, _ = self.receipts()
        package_sha = "8" * 64
        plan = {"release_id": "release-r5", "target_date": "20261123",
                "release_package_sha256": package_sha, "admission_evidence": refs,
                "lock_protocol": CUTOVER.expected_lock_protocol()}
        plan_path = self.root / "plan.json"
        plan_sha = write_json(plan_path, plan)
        chat = {"verdict": "PASS", "package_sha256": package_sha}
        chat_path = self.root / "chat-review.json"
        chat_sha = write_json(chat_path, chat)
        note_path = self.root / "explicit-user-approval.txt"
        note_path.write_text("I approve the exact Main-only activation bound to this plan SHA.")
        note_sha = sha(note_path.read_bytes())
        approval = {"schema": "v4.main_only_explicit_authorization.v1",
                    "action": "ACTIVATE_MAIN_ONLY", "scope": "Main LaunchAgent plist CAS only",
                    "plan_sha256": plan_sha, "release_id": "release-r5", "target_date": "20261123",
                    "migration": "BLOCKED", "stage_reload": False, "api_reload": False,
                    "registry_write": False, "current_pointer_write": False,
                    "reservation_release": False, "lock_protocol": plan["lock_protocol"],
                    "approved_by_user": True,
                    "chat_review_sha256": chat_sha,
                    "admission_evidence_sha256": {key: ref["sha256"] for key, ref in refs.items()},
                    "approved_at": CUTOVER.datetime.now().astimezone().isoformat(),
                    "approval_note_sha256": note_sha,
                    "approval_note": {"path": str(note_path), "sha256": note_sha}}
        CUTOVER.check_activation_authorization(plan, plan_sha, approval, chat, chat_sha)
        wrong_lock_contract = dict(approval)
        wrong_lock_contract["lock_protocol"] = {**plan["lock_protocol"], "owner_record_paths": []}
        with self.assertRaisesRegex(CUTOVER.CutoverBlocked, "EXACT_EXPLICIT_MAIN_ONLY_AUTHORIZATION_REQUIRED"):
            CUTOVER.check_activation_authorization(plan, plan_sha, wrong_lock_contract, chat, chat_sha)
        with self.assertRaisesRegex(CUTOVER.CutoverBlocked, "EXACT_EXPLICIT_MAIN_ONLY_AUTHORIZATION_REQUIRED"):
            CUTOVER.check_activation_authorization(plan, "0" * 64, approval, chat, chat_sha)

    def test_rollback_authorization_also_binds_exact_owner_lock_protocol(self):
        package_sha = "8" * 64
        plan = {"release_id": "release-r5", "target_date": "20261123",
                "release_package_sha256": package_sha,
                "lock_protocol": CUTOVER.expected_lock_protocol(),
                "controller_plan": {"roles": [{"role": "main",
                    "candidate_plist_sha256": "3" * 64, "current_plist_sha256": "4" * 64}]}}
        plan_path = self.root / "rollback-plan.json"
        plan_sha = write_json(plan_path, plan)
        chat = {"verdict": "PASS", "package_sha256": package_sha}
        chat_path = self.root / "rollback-chat.json"
        chat_sha = write_json(chat_path, chat)
        note_path = self.root / "rollback-user-approval.txt"
        note_path.write_text("I approve the exact Main-only rollback and owner-lock protocol.")
        note_sha = sha(note_path.read_bytes())
        approval = {"schema": "v4.main_only_explicit_authorization.v1",
                    "action": "ROLLBACK_MAIN_ONLY", "scope": "Main LaunchAgent plist CAS only",
                    "plan_sha256": plan_sha, "release_id": "release-r5", "target_date": "20261123",
                    "installed_candidate_plist_sha256": "3" * 64, "restore_plist_sha256": "4" * 64,
                    "stage_reload": False, "api_reload": False, "registry_write": False,
                    "current_pointer_write": False, "reservation_release": False,
                    "lock_protocol": plan["lock_protocol"], "approved_by_user": True,
                    "chat_review_sha256": chat_sha,
                    "approved_at": CUTOVER.datetime.now().astimezone().isoformat(),
                    "approval_note_sha256": note_sha,
                    "approval_note": {"path": str(note_path), "sha256": note_sha}}
        CUTOVER.check_rollback_authorization(plan, plan_sha, approval, chat, chat_sha)
        approval["lock_protocol"] = {**plan["lock_protocol"], "persistent_mutex_bytes_or_inode_change": True}
        with self.assertRaisesRegex(CUTOVER.CutoverBlocked, "EXACT_EXPLICIT_MAIN_ONLY_ROLLBACK_AUTHORIZATION_REQUIRED"):
            CUTOVER.check_rollback_authorization(plan, plan_sha, approval, chat, chat_sha)

    def test_controller_and_dependency_bytes_match_frozen_sources(self):
        source, dependencies = CUTOVER.verify_controller_sources()
        self.assertEqual(CUTOVER.digest(source.read_bytes()), CUTOVER.CONTROLLER_SHA256)
        self.assertEqual(len(dependencies), 4)

    def test_evidence_reader_rejects_symlink_alias(self):
        target = self.root / "real-receipt.json"
        target.write_text("{}\n")
        alias = self.root / "alias-receipt.json"
        alias.symlink_to(target)
        with self.assertRaisesRegex(CUTOVER.CutoverBlocked, "EXACT_REGULAR_FILE_REQUIRED"):
            CUTOVER.exact_file(alias, sha(target.read_bytes()))

    def test_unsigned_frozen_candidate_policy_is_rejected(self):
        template_path = SOURCE.parent / "MAIN_ONLY_RELEASE_PLAN_TEMPLATE.json"
        template = json.loads(template_path.read_bytes())
        candidate = Path(os.environ.get("V4_R4_CANDIDATE_ROOT", template["release_root"]))
        self.assertEqual(str(candidate), template["release_root"])
        plist = plistlib.loads((candidate / "launchd.plist").read_bytes())
        env = plist["EnvironmentVariables"]
        proof = {"release_id": env["V4_RELEASE_ID"],
                 "candidate_policy_sha256": env["V4_RESEARCH_RETENTION_POLICY_SHA256"],
                 "candidate_classification_sha256": "0" * 64}
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaisesRegex(RuntimeError, "CANDIDATE_POLICY_CLASSIFICATION_REFERENCE_MISSING"):
                GATE.load_reviewed_candidate_policy(candidate, proof)

    def test_reviewed_policy_classifier_must_be_candidate_bound_and_sha_exact(self):
        candidate = self.root / "candidate"
        control = candidate / "control"
        control.mkdir(parents=True)
        (candidate / "release-manifest.json").write_text(json.dumps({"release_id": "release-r5"}))
        data_root = self.root / "data"
        return_root = self.root / "runs"
        data_root.mkdir()
        return_root.mkdir()
        classification = {"schema": "v4.qfq_legacy_task_scope.v1", "status": "REVIEWED_TASK_SCOPES",
                          "evidence_closed": True, "reviewer": "CHAT"}
        classifier_path = control / "qfq-classification.json"
        classifier_sha = write_json(classifier_path, classification)
        policy = {"data_root": str(data_root), "run_root": str(return_root),
                  "governance": {"qfq_legacy_classification":
                                 {"path": str(classifier_path), "sha256": classifier_sha}}}
        policy_path = control / "policy.json"
        policy_sha = write_json(policy_path, policy)
        proof = {"release_id": "release-r5", "candidate_policy_sha256": policy_sha,
                 "candidate_classification_sha256": classifier_sha}
        env = {"V4_RESEARCH_RETENTION_POLICY": str(policy_path),
               "V4_RESEARCH_RETENTION_POLICY_SHA256": policy_sha,
               "V4_RESEARCH_PANEL_A_DATA_ROOT": str(data_root),
               "V4_RESEARCH_PANEL_A_RETURN_ROOT": str(return_root)}
        with patch.dict(os.environ, env, clear=False):
            loaded = GATE.load_reviewed_candidate_policy(candidate, proof)
            self.assertEqual(loaded, policy)
            policy["governance"]["qfq_legacy_classification"]["sha256"] = "f" * 64
            changed_sha = write_json(policy_path, policy)
            env["V4_RESEARCH_RETENTION_POLICY_SHA256"] = changed_sha
            proof["candidate_policy_sha256"] = changed_sha
            proof["candidate_classification_sha256"] = "f" * 64
            with patch.dict(os.environ, env, clear=False):
                with self.assertRaisesRegex(RuntimeError, "CANDIDATE_POLICY_CLASSIFICATION_SHA_DRIFT"):
                    GATE.load_reviewed_candidate_policy(candidate, proof)

    def test_policy_classifier_outside_control_and_daemon_root_drift_block(self):
        candidate = self.root / "candidate"
        control = candidate / "control"
        control.mkdir(parents=True)
        write_json(candidate / "release-manifest.json", {"release_id": "release-r5"})
        data_root = self.root / "data"
        return_root = self.root / "runs"
        wrong_data_root = self.root / "other-data"
        for path in (data_root, return_root, wrong_data_root):
            path.mkdir()
        classification = {"schema": "v4.qfq_legacy_task_scope.v1", "status": "REVIEWED_TASK_SCOPES",
                          "evidence_closed": True, "reviewer": "CHAT"}
        external_classifier = self.root / "external-classification.json"
        external_sha = write_json(external_classifier, classification)
        policy_path = control / "policy.json"
        policy = {"data_root": str(data_root), "run_root": str(return_root),
                  "governance": {"qfq_legacy_classification":
                                 {"path": str(external_classifier), "sha256": external_sha}}}
        policy_sha = write_json(policy_path, policy)
        proof = {"release_id": "release-r5", "candidate_policy_sha256": policy_sha,
                 "candidate_classification_sha256": external_sha}
        env = {"V4_RESEARCH_RETENTION_POLICY": str(policy_path),
               "V4_RESEARCH_RETENTION_POLICY_SHA256": policy_sha,
               "V4_RESEARCH_PANEL_A_DATA_ROOT": str(data_root),
               "V4_RESEARCH_PANEL_A_RETURN_ROOT": str(return_root)}
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaisesRegex(RuntimeError, "CANDIDATE_POLICY_CLASSIFICATION_PATH_INVALID"):
                GATE.load_reviewed_candidate_policy(candidate, proof)

        inside_classifier = control / "classification.json"
        inside_sha = write_json(inside_classifier, classification)
        policy["governance"]["qfq_legacy_classification"] = {"path": str(inside_classifier), "sha256": inside_sha}
        policy_sha = write_json(policy_path, policy)
        proof.update(candidate_policy_sha256=policy_sha, candidate_classification_sha256=inside_sha)
        env["V4_RESEARCH_RETENTION_POLICY_SHA256"] = policy_sha
        env["V4_RESEARCH_PANEL_A_DATA_ROOT"] = str(wrong_data_root)
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaisesRegex(RuntimeError, "CANDIDATE_POLICY_DAEMON_ROOT_BINDING_DRIFT"):
                GATE.load_reviewed_candidate_policy(candidate, proof)

    def rollback_fixture(self, *, fail_bootstrap_count=0):
        old_release = self.root / "old-release"
        candidate = self.root / "candidate"
        launch_agents = self.root / "LaunchAgents"
        old_app = old_release / "app"
        new_app = candidate / "app"
        for path in (old_app, new_app, old_release / "control", candidate / "control", launch_agents):
            path.mkdir(parents=True, exist_ok=True)

        old_manifest_path = old_release / "release-manifest.json"
        new_manifest_path = candidate / "release-manifest.json"
        old_manifest_sha = write_json(old_manifest_path, {"release_id": "release-old"})
        new_manifest_sha = write_json(new_manifest_path, {"release_id": "release-r5"})
        policy_path = old_release / "control" / "policy.json"
        policy_sha = write_json(policy_path, {"schema": "fixture-old-policy"})
        pin_rows = []
        for index in range(95):
            source = self.root / f"old-source-{index:02d}.bin"
            source.write_bytes(f"old-source-{index}".encode())
            pin_rows.append({"path": str(source), "sha256": sha(source.read_bytes())})
        pins_path = old_release / "control" / "managed-pins.json"
        pins_sha = write_json(pins_path, {"source_bindings": pin_rows})
        old_controls = {
            "manifest": {"sha256": old_manifest_sha, "mode": "0644"},
            "policy": {"sha256": policy_sha, "mode": "0644"},
            "pins": {"sha256": pins_sha, "mode": "0644"},
        }
        old_cfg = {"Label": "com.lexi.v4.scheduler", "WorkingDirectory": str(old_app),
                   "EnvironmentVariables": {"V4_RELEASE_MANIFEST_PATH": str(old_manifest_path),
                                            "V4_RELEASE_MANIFEST_SHA256": old_manifest_sha}}
        new_cfg = {"Label": "com.lexi.v4.scheduler", "WorkingDirectory": str(new_app),
                   "EnvironmentVariables": {"V4_RELEASE_MANIFEST_PATH": str(new_manifest_path),
                                            "V4_RELEASE_MANIFEST_SHA256": new_manifest_sha}}
        old_raw = plistlib.dumps(old_cfg)
        new_raw = plistlib.dumps(new_cfg)
        rollback_plist = old_release / "launchd.plist"
        candidate_plist = candidate / "launchd.plist"
        live = launch_agents / "com.lexi.v4.scheduler.plist"
        for path, raw in ((rollback_plist, old_raw), (candidate_plist, new_raw), (live, new_raw)):
            path.write_bytes(raw)
            path.chmod(0o644)
        row = {"role": "main", "candidate_release_id": "release-r5",
               "rollback_plist": str(rollback_plist), "candidate_plist": str(candidate_plist),
               "current_plist_sha256": sha(old_raw), "candidate_plist_sha256": sha(new_raw),
               "current_manifest_sha256": old_manifest_sha, "candidate_manifest_sha256": new_manifest_sha,
               "current_plist_mode": "0644"}
        plan = {"release_id": "release-r5", "target_date": "20261123",
                "controller_plan": {"roles": [row]}, "old_main_release_controls": old_controls}
        controller = FakeRollbackController(launch_agents, live, new_cfg, new_manifest_sha,
                                            fail_bootstrap_count=fail_bootstrap_count)
        return plan, controller, live, old_raw, new_raw, old_controls, old_release

    def test_rollback_restores_exact_main_preimage_and_preserves_old_controls(self):
        plan, controller, live, old_raw, new_raw, old_controls, old_release = self.rollback_fixture()
        def lock_adapter(selected_controller, role, selected_plan, stack):
            return None
        result = CUTOVER.rollback_main(plan, controller, lock_adapter=lock_adapter)
        self.assertEqual(result["status"], "RESTORED_MAIN_ONLY")
        self.assertEqual(live.read_bytes(), old_raw)
        self.assertEqual(live.stat().st_mode & 0o777, 0o644)
        self.assertEqual(controller.write_calls, 1)
        self.assertEqual(controller.scheduler_idle_calls, 1)
        for name, rel in (("manifest", "release-manifest.json"),
                          ("policy", "control/policy.json"),
                          ("pins", "control/managed-pins.json")):
            path = old_release / rel
            self.assertEqual(sha(path.read_bytes()), old_controls[name]["sha256"])
            self.assertEqual(format(path.stat().st_mode & 0o777, "04o"), "0644")

    def test_rollback_cas_drift_blocks_before_unload_or_write(self):
        plan, controller, live, old_raw, new_raw, _, _ = self.rollback_fixture()
        live.write_bytes(b"third-party-plist-bytes")
        def lock_adapter(selected_controller, role, selected_plan, stack):
            return None
        with self.assertRaisesRegex(CUTOVER.CutoverBlocked, "LIVE_CANDIDATE_PLIST_CAS_MISMATCH"):
            CUTOVER.rollback_main(plan, controller, lock_adapter=lock_adapter)
        self.assertEqual(controller.unload_calls, 0)
        self.assertEqual(controller.write_calls, 0)

    def test_rollback_bootstrap_failure_gets_one_bounded_restore_attempt(self):
        plan, controller, live, old_raw, new_raw, _, _ = self.rollback_fixture(fail_bootstrap_count=1)
        def lock_adapter(selected_controller, role, selected_plan, stack):
            return None
        result = CUTOVER.rollback_main(plan, controller, lock_adapter=lock_adapter)
        self.assertEqual(result["status"], "ROLLBACK_FAILED_CURRENT_CONFIGURATION_RESTORED")
        self.assertEqual(result["recovery_action"], "BOOTSTRAPPED_CURRENT_CAS_BYTES")
        self.assertEqual(live.read_bytes(), old_raw)
        expected_old_cwd = str(Path(plan["controller_plan"]["roles"][0]["rollback_plist"]).parent / "app")
        self.assertEqual(controller.loaded(controller.LABELS["main"])["cwd"],
                         expected_old_cwd)

    def test_plan_allows_candidate_directory_name_to_differ_from_release_id(self):
        release = self.root / "candidate"
        (release / "app").mkdir(parents=True)
        (release / "runtime").mkdir()
        manifest_sha = "3" * 64
        plist_path = release / "launchd.plist"
        env = {"V4_RELEASE_ID": "release-r5", "V4_APP_ROOT": str(release / "app"),
               "V4_RUNTIME_ROOT": str(release / "runtime"),
               "V4_RELEASE_MANIFEST_PATH": str(release / "release-manifest.json"),
               "V4_RELEASE_MANIFEST_SHA256": manifest_sha}
        plist_path.write_bytes(plistlib.dumps({"EnvironmentVariables": env}))
        plan = {"schema": CUTOVER.SCHEMA, "scope": "Main-only", "migration": "BLOCKED",
                "release_root": str(release), "approved_candidate_parent": str(self.root),
                "target_date": "20261123", "release_id": "release-r5",
                "lock_protocol": CUTOVER.expected_lock_protocol(),
                "controller_plan": {"roles": [{"role": "main", "candidate_release_id": "release-r5",
                                                 "candidate_plist": str(plist_path),
                                                 "candidate_manifest_sha256": manifest_sha}],
                                    "verification_command": None}}
        CUTOVER.validate_plan(plan)

    def test_release_plan_template_is_deliberately_non_runnable(self):
        template = SOURCE.parent / "MAIN_ONLY_RELEASE_PLAN_TEMPLATE.json"
        plan = json.loads(template.read_bytes())
        self.assertEqual(plan["status"], "BLOCKED_TEMPLATE_ONLY")
        self.assertTrue(plan["must_not_execute"])
        self.assertNotEqual(plan["schema"], CUTOVER.SCHEMA)
        self.assertTrue(plan["release_id_is_read_from_plist_not_inferred_from_basename"])
        self.assertEqual(plan["lock_protocol"], CUTOVER.expected_lock_protocol())
        candidate = Path(os.environ.get("V4_R4_CANDIDATE_ROOT", plan["release_root"]))
        self.assertEqual(str(candidate), plan["release_root"])
        plist_path = candidate / "launchd.plist"
        manifest_path = candidate / "release-manifest.json"
        self.assertEqual(plan["release_root"], str(candidate))
        self.assertEqual(plan["candidate_identity_from_plist"]["candidate_plist_sha256"],
                         sha(plist_path.read_bytes()))
        self.assertEqual(plan["candidate_identity_from_plist"]["candidate_manifest_sha256"],
                         sha(manifest_path.read_bytes()))
        role = plan["controller_plan"]["roles"][0]
        self.assertEqual(role["candidate_plist_sha256"], sha(plist_path.read_bytes()))
        self.assertEqual(role["candidate_manifest_sha256"], sha(manifest_path.read_bytes()))
        with self.assertRaisesRegex(CUTOVER.CutoverBlocked, "UNREVIEWED_MAIN_ONLY_PLAN"):
            CUTOVER.validate_plan(plan)

    def test_capacity_recomputation_keeps_both_old_reservation_measures(self):
        policy_path = self.root / "candidate-policy.json"
        registry_root = self.root / "registry"
        registry_root.mkdir()
        old = {"state": "FAILED_RECOVERABLE", "reserved_bytes": 51_539_607_552,
               "written_bytes": 203_870_208, "logical_written_bytes": 189_021_812,
               "category": "ordinary", "directory": str(self.root / "old")}
        old_row_sha = sha(json.dumps(old, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())
        registry = {"tasks": {"a" * 64: old}}
        registry_path = registry_root / "registry.json"
        registry_sha = write_json(registry_path, registry)
        policy = {"data_root": str(self.root / "data"), "run_root": str(self.root / "runs"),
                  "governance": {"registry_root": str(registry_root), "reserve_bytes": 1_000_000_000,
                                 "safety_bytes": 1_000_000_000, "minimum_free_ratio": 0.1,
                                 "ordinary_peak_budget_bytes": 100_000_000_000,
                                 "debug_budget_bytes": 10_000_000_000}}
        policy_sha = write_json(policy_path, policy)
        new_plist = {"EnvironmentVariables": {"V4_RESEARCH_RETENTION_POLICY": str(policy_path),
                                                "V4_RESEARCH_RETENTION_POLICY_SHA256": policy_sha,
                                                "V4_RESEARCH_PANEL_A_DATA_ROOT": str(self.root / "data")}}
        old_plist = {"EnvironmentVariables": {"V4_RESEARCH_PANEL_A_DATA_ROOT": str(self.root / "data")}}
        old_path = self.root / "old.plist.json"
        new_path = self.root / "new.plist.json"
        old_path.write_bytes(plistlib.dumps(old_plist))
        new_path.write_bytes(plistlib.dumps(new_plist))
        role = {"rollback_plist": str(old_path), "candidate_plist": str(new_path)}
        refs, old_proof, new_proof, cap = self.receipts()
        old_proof.update(old_row_sha256=old_row_sha)
        new_proof.update(old_row_sha256=old_row_sha)
        cap.update(old_row_sha256=old_row_sha)
        write_json(Path(refs["old_task_unique_attribution"]["path"]), old_proof)
        refs["old_task_unique_attribution"]["sha256"] = sha(Path(refs["old_task_unique_attribution"]["path"]).read_bytes())
        new_proof.update(registry_sha256=registry_sha, task_key="c" * 64, predicted_peak_bytes=1_000_000_000)
        write_json(Path(refs["new_date_reviewed_classification"]["path"]), new_proof)
        refs["new_date_reviewed_classification"]["sha256"] = sha(Path(refs["new_date_reviewed_classification"]["path"]).read_bytes())
        cap.update(registry_sha256=registry_sha, task_key="c" * 64,
                   category_other_remaining_bytes=CUTOVER.OLD_CATEGORY_REMAINING)
        write_json(Path(refs["actual_capacity_preflight"]["path"]), cap)
        refs["actual_capacity_preflight"]["sha256"] = sha(Path(refs["actual_capacity_preflight"]["path"]).read_bytes())
        plan = {"release_id": "release-r5", "target_date": "20261123", "admission_evidence": refs,
                "controller_plan": {"roles": [role]}}
        admission = CUTOVER.check_evidence(plan)
        usage = type("Usage", (), {"free": 200_000_000_000, "total": 500_000_000_000})()
        with patch.object(CUTOVER.shutil, "disk_usage", return_value=usage):
            result = CUTOVER.check_current_capacity(plan, admission, None)
        self.assertEqual(result["old_category_remaining_bytes"], CUTOVER.OLD_CATEGORY_REMAINING)
        self.assertEqual(result["old_physical_peak_remaining_bytes"], CUTOVER.OLD_PHYSICAL_REMAINING)

    def test_activation_uses_injected_lock_and_runtime_probes_and_main_only_controller(self):
        refs, _, new, _ = self.receipts()
        source_rows = []
        pins = self.root / "managed-pins.json"
        for index in range(95):
            path = self.root / f"source-{index:02d}.bin"
            path.write_bytes(f"source-{index}".encode())
            source_rows.append({"path": str(path), "sha256": sha(path.read_bytes())})
        pins_sha = write_json(pins, {"source_bindings": source_rows})
        review = {"verdict": "PASS", "roles": {"main": {"candidate_release_id": "release-r5",
                    "candidate_manifest_sha256": "3" * 64, "candidate_plist_sha256": "4" * 64,
                    "delta_files": []}}}
        review_path = self.root / "review.json"
        review_sha = write_json(review_path, review)
        candidate_root = self.root / "candidate"
        candidate_root.mkdir()
        plan = {"release_id": "release-r5", "target_date": "20261123", "approved_candidate_parent": str(self.root),
                "candidate_pins": {"path": str(pins), "sha256": pins_sha}, "admission_evidence": refs,
                "controller_plan": {"roles": [{"role": "main", "candidate_release_id": "release-r5",
                                                 "candidate_plist": str(candidate_root / "launchd.plist")}],
                                    "review_approval": {"path": str(review_path), "sha256": review_sha}}}
        events = []
        fake = FakeController(self.root, events)

        def lock_adapter(controller, role, selected, stack):
            events.append("locks")

        def qfq_adapter(selected, admission):
            events.append("qfq")
            return {"status": "PASS_READONLY_REVIEWED_DISTINCT_DATE_SCOPE", "task_key": new["task_key"]}

        def preflight_adapter(selected, admission, controller):
            events.append("capacity")
            return {"status": "PASS_CAPACITY_ADMITTED"}

        result = CUTOVER.activate_main(plan, fake, lock_adapter=lock_adapter,
                                       qfq_adapter=qfq_adapter, preflight_adapter=preflight_adapter)
        self.assertEqual(result["status"], "ACTIVATED_MAIN_ONLY")
        self.assertEqual(fake.asserted_roles, ["com.lexi.v4.scheduler"])
        self.assertEqual(events, ["load_role", "locks", "qfq", "capacity", "activate"])
        for status in ("ROLLED_BACK", "ROLLBACK_INCOMPLETE"):
            fake.activation_result = {"status": status, "error": "controller recovery evidence",
                                      "rollback_action": "RESTORED_OLD_MAIN",
                                      "roles": {"main": {"rollback_error": "fixture detail"}}}
            fake.activation_exception = "frozen controller re-raised after recording recovery"
            events.clear()
            result = CUTOVER.activate_main(plan, fake, lock_adapter=lock_adapter,
                                           qfq_adapter=qfq_adapter, preflight_adapter=preflight_adapter)
            self.assertEqual(result["status"], status)
            self.assertEqual(result["error"], "controller recovery evidence")
            self.assertEqual(result["rollback_action"], "RESTORED_OLD_MAIN")
            self.assertEqual(result["roles"]["main"]["rollback_error"], "fixture detail")
            self.assertEqual(result["controller_call_exception"],
                             "RuntimeError: frozen controller re-raised after recording recovery")


if __name__ == "__main__":
    unittest.main()
