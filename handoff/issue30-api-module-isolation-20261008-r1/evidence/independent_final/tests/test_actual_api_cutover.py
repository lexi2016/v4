"""Synthetic regression tests for the R2 executable cutover boundary."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock
import uuid


WORK = Path(__file__).resolve().parents[1]
BASELINE = WORK.parents[1] / "input/baseline/source/actual_cutover_reference/api_only_cutover_r2_ready.py"
DEFAULT_CANDIDATE = WORK / "candidate/api_only_cutover_r2_ready.py"
SOURCE = Path(os.environ.get("CUTOVER_SOURCE", str(DEFAULT_CANDIDATE if DEFAULT_CANDIDATE.is_file() else BASELINE)))
CORE = Path(os.environ.get("INTEGRATION_SOURCE", str(WORK.parent / "integration_core/candidate/ops/api_release_integration.py")))


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def load(path):
    name = "_test_cutover_" + uuid.uuid4().hex
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module


def forbidden(*args, **kwargs):
    raise AssertionError("REAL_SERVICE_OR_HTTP_CALL_FORBIDDEN")


def write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def write_json(path, value):
    raw = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    write(path, raw)
    return digest(raw)


class ActualCutoverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cutover-test-", dir=WORK)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.m = load(SOURCE)
        self.m.ACTIVE_API_PLIST = self.root / "LaunchAgents/com.lexi.v35.api-only.plist"
        self.m.ACTIVE_API_PLIST.parent.mkdir()
        self.m.EVIDENCE_ROOT = self.root / "task/evidence"
        self.m._launchctl_action = forbidden
        self.m._launchctl_print = forbidden
        self.m._http_get = forbidden
        if CORE.is_file():
            self.m.INTEGRATION_GUARD_PATH = CORE.resolve()
            self.m.INTEGRATION_GUARD_SHA256 = digest(CORE.read_bytes())

    def guard(self):
        self.assertTrue(CORE.is_file(), "integration core candidate required for this integration test")
        self.assertTrue(hasattr(self.m, "_load_integration_guard"), "actual executable must pin and load the shared guard")
        return self.m._load_integration_guard()

    def install_tiny_guard(self, marker="trusted"):
        raw = ("SCHEMA_VERSION = 'v4.api_release_integration.v2'\n"
               f"MARKER = {marker!r}\n"
               "def inventory_tree(*a, **k): return []\n"
               "def inventory_digest(*a, **k): return 'digest'\n"
               "def verify_api_release_candidate(*a, **k): return {}\n"
               "def verify_recorded_base(*a, **k): return {}\n"
               "def shared_api_release_lock(*a, **k): return None\n"
               "def assert_api_release_lock(*a, **k): return None\n").encode()
        path = self.root / "pinned_guard.py"
        path.write_bytes(raw)
        self.m.INTEGRATION_GUARD_PATH = path
        self.m.INTEGRATION_GUARD_SHA256 = digest(raw)
        return path, raw

    def integrated_fixture(self):
        """Real v2 package/metadata logic, synthetic release bytes, simulated launchd/HTTP."""
        m, core = self.m, self.guard()
        m.TASK_ROOT = self.root / "task"
        m.EVIDENCE_ROOT = m.TASK_ROOT / "evidence"
        m.PLAN_PATH = m.EVIDENCE_ROOT / "staged/plan.json"
        m.STAGED_API_PLIST_PATH = m.EVIDENCE_ROOT / "staged/api.plist"
        m.STAGED_API_PLIST_DIFF_PATH = m.EVIDENCE_ROOT / "staged/api.diff.json"
        m.API_INVENTORY_RECEIPT_PATH = m.EVIDENCE_ROOT / "inventory.json"
        m.RELEASE_STAGE_RECEIPT_PATH = m.EVIDENCE_ROOT / "stage.json"
        m.DISABLED_BINDING_PATH = self.root / "disabled-binding.json"
        m.ACTIVE_SCHEDULER_PLIST = self.root / "scheduler.plist"
        m.STAGE_CENTER_SCHEDULER_PLIST = self.root / "stage-center.plist"
        m.P2_REVIEW_PATH = m.TASK_ROOT / "p2-review.json"
        m.BUSINESS_FIX_REVIEW_PATH = m.TASK_ROOT / "business-review.json"
        m.BUSINESS_FIX_RECEIPT_PATH = m.TASK_ROOT / "business-receipt.json"
        write(m.ACTIVE_SCHEDULER_PLIST, b"synthetic scheduler\n")
        write(m.STAGE_CENTER_SCHEDULER_PLIST, b"synthetic stage\n")
        binding_sha = write_json(m.DISABLED_BINDING_PATH, {
            "enabled": False, "announcement_collection_enabled": False,
            "plan_material_refresh_only": False, "manager_state_root": str(m.FORMAL_MANAGER_STATE)})
        base = self.root / "releases/base-accepted"
        changed = "domains/preselection_pools.py"
        before, after = b"value = 'base'\n", b"value = 'delta'\n"
        write(base / "app" / changed, before)
        write(base / "app/domains/manager_research/current.py", b"accepted_manager_fix = True\n")
        write(base / "app/apps/web/dist/manager-selection/index.html", b'<script src="/assets/probe.js"></script>')
        write(base / "app/apps/web/dist/assets/probe.js", b"/* byte fixture only */\n")
        legacy_backend = WORK.parents[1] / "input/baseline/source/unreviewed_draft/ops/api_release_integration.py"
        write(base / "app/ops/build_release_candidate.py", legacy_backend.read_bytes())
        base_entries = core.inventory_tree(base / "app")
        base_digest = core.inventory_digest(base_entries)
        base_manifest_sha = write_json(base / "release-manifest.json", {
            "schema_version": "v4.release_candidate.v1", "activation_status": "NOT_ACTIVATED",
            "candidate": {"root": str(base), "app_root": str(base / "app"), "release_id": base.name},
            "application_inventory": {"aggregate_sha256": base_digest, "entries": base_entries,
                                      "entry_count": len(base_entries)},
        })
        env = {"V35_APP_ROOT": str(base / "app"), "V35_RELEASE_ID": base.name,
               "V35_RELEASE_MANIFEST_PATH": str(base / "release-manifest.json"),
               "V35_RELEASE_MANIFEST_SHA256": base_manifest_sha, "PYTHONPATH": str(base / "app"),
               "V4_MANAGER_PLAN_OWNER_BINDING_PATH": str(m.DISABLED_BINDING_PATH),
               "V4_MANAGER_SCREEN_AUTHORITY_ROOT": str(m.SCREEN_AUTHORITY_ROOT), **m.SAFETY_EXPECTED}
        original = plistlib.dumps({"Label": m.LABEL, "KeepAlive": True, "RunAtLoad": False,
                                  "WorkingDirectory": env["V35_APP_ROOT"],
                                  "ProgramArguments": ["/usr/bin/env", *[f"{k}={v}" for k, v in env.items()],
                                                       str(m.PINNED_PYTHON), "-m", "synthetic_api"]})
        write(m.ACTIVE_API_PLIST, original)
        base_record = {"release_root": str(base), "app_root": str(base / "app"), "release_id": base.name,
                       "release_manifest_path": str(base / "release-manifest.json"),
                       "release_manifest_sha256": base_manifest_sha,
                       "application_inventory_sha256": base_digest,
                       "application_inventory_entry_count": len(base_entries),
                       "api_plist_path": str(m.ACTIVE_API_PLIST), "api_plist_sha256": digest(original)}
        delta_source = self.root / "delta-source"
        write(delta_source / changed, after)
        proof = b"--- before\n+++ after\n@@ -1 +1 @@\n-value = 'base'\n+value = 'delta'\n"
        delta_path = self.root / "module-delta.json"
        write_json(delta_path, {"schema_version": "v4.api_release_delta_receipt.v2", "base": base_record,
                               "module_scope": {"module": "preselection", "shared_paths": [],
                                                "policy_sha256": core.POLICY_SHA256},
                               "entries": [{"path": changed, "before_sha256": digest(before),
                                            "after_sha256": digest(after), "before_mode": "0644",
                                            "after_mode": "0644", "unified_diff_sha256": digest(proof),
                                            "unified_diff_hunk_count": 1}]})
        release = self.root / "releases/integrated-candidate"
        release.mkdir()
        integration = core.build_integrated_app(active_api_plist_path=m.ACTIVE_API_PLIST,
                                                source_root=delta_source, candidate_root=release,
                                                delta_receipt_path=delta_path)
        entries = core.inventory_tree(release / "app")
        inventory_sha = core.inventory_digest(entries)
        m.EXPECTED_API_INVENTORY_SHA256 = inventory_sha
        manifest_sha = write_json(release / "release-manifest.json", {
            "schema_version": "v4.release_candidate.v1", "activation_status": "NOT_ACTIVATED",
            "candidate": {"root": str(release), "app_root": str(release / "app"), "release_id": release.name},
            "application_inventory": {"aggregate_sha256": inventory_sha, "entries": entries, "entry_count": len(entries)},
            "api_integration": integration})
        source_app = m.TASK_ROOT / "candidate/api/app"
        shutil.copytree(release / "app", source_app)
        m.INVENTORY_BACKEND_PATH = source_app / "ops/build_release_candidate.py"
        m.API_INVENTORY_RECEIPT_SHA256 = write_json(m.API_INVENTORY_RECEIPT_PATH, {"aggregate_sha256": inventory_sha})
        m.P2_DELTA_RECEIPT_SHA256 = write_json(m.TASK_ROOT / "receipts/p2_delta_receipt.json", {
            "dist_sync": {"same_paths_and_bytes": True, "source_tree_sha256": m.EXPECTED_DIST_TREE_SHA256,
                          "target_tree_sha256": m.EXPECTED_DIST_TREE_SHA256}})
        stage = {"status": "STAGED_AND_VERIFIED_NOT_DEPLOYED", "release_root": str(release),
                 "release_manifest_sha256": manifest_sha, "application_inventory_sha256": inventory_sha,
                 "application_inventory_entries": len(entries)}
        stage_sha = write_json(m.RELEASE_STAGE_RECEIPT_PATH, {**stage, "receipt_sha256": m._canonical_sha(stage)})
        m.P2_REVIEW_SHA256 = write_json(m.P2_REVIEW_PATH, {"status": {"REVIEWED": "PASS", "BEHAVIOR_VERIFIED": "PASS"}})
        m.BUSINESS_FIX_REVIEW_SHA256 = write_json(m.BUSINESS_FIX_REVIEW_PATH, {
            "review_status": "PASS", "tested_status": "PASS", "behavior_verified_status": "PASS",
            "findings": {"P0": [], "P1": [], "P2": []},
            "frozen_scope": {"candidate_sha256": m.BUSINESS_FIX_CANDIDATE_SHA256}})
        m.BUSINESS_FIX_RECEIPT_SHA256 = write_json(m.BUSINESS_FIX_RECEIPT_PATH, {
            "change": {"candidate_source_sha256": m.BUSINESS_FIX_CANDIDATE_SHA256}})
        old_identity = {"state": "running", "pid": "1001", **m._identity_from_plist(original)}
        plan = {"target": {"release_root": str(release), "app_root": str(release / "app"),
                           "release_id": release.name, "release_manifest_sha256": manifest_sha,
                           "application_inventory_sha256": inventory_sha},
                "source": {"inventory_backend_path": str(m.INVENTORY_BACKEND_PATH),
                           "inventory_backend_sha256": digest(m.INVENTORY_BACKEND_PATH.read_bytes()),
                           "source_candidate_app_root": str(source_app), "release_stage_receipt_sha256": stage_sha,
                           "p2_independent_review_sha256": m.P2_REVIEW_SHA256,
                           "business_fix_independent_review_sha256": m.BUSINESS_FIX_REVIEW_SHA256,
                           "business_fix_receipt_sha256": m.BUSINESS_FIX_RECEIPT_SHA256},
                "before": {"active_api_plist_sha256": digest(original), "loaded_identity": old_identity,
                           "scheduler_plist_sha256": digest(m.ACTIVE_SCHEDULER_PLIST.read_bytes()),
                           "stage_center_scheduler_plist_sha256": digest(m.STAGE_CENTER_SCHEDULER_PLIST.read_bytes())},
                "guards": {"disabled_binding_path": str(m.DISABLED_BINDING_PATH), "disabled_binding_sha256": binding_sha}}
        plan["allowed_paths"] = [str(m.ACTIVE_API_PLIST),
                                 str(m.ACTIVE_API_PLIST.with_name(".com.lexi.v35.api-only.release.lock"))]
        runtime = {"identity": old_identity, "actions": [], "hook": None}

        def launch_print():
            identity = runtime["identity"]
            if identity is None:
                raise ValueError("API_ONLY_LAUNCH_AGENT_NOT_LOADED:synthetic")
            return "\n".join(["state = running", "pid = " + identity["pid"],
                              *[f"{k}={identity[k]}" for k in ("V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_SHA256")]])

        def launch_action(action):
            runtime["actions"].append(action)
            if action == "bootout":
                runtime["identity"] = None
            elif action == "bootstrap":
                runtime["identity"] = {"state": "running", "pid": "2002",
                                       **m._identity_from_plist(m.ACTIVE_API_PLIST.read_bytes())}
            else:
                raise AssertionError("unexpected simulated service action")
            if runtime["hook"] is not None:
                runtime["hook"](action)

        def http_get(path):
            if path == "/openapi.json":
                return 200, json.dumps({"paths": {m.MANAGER_WORKSPACE_ROUTE: {"get": {}}}}).encode()
            dist = Path(runtime["identity"]["V35_APP_ROOT"]) / "apps/web/dist"
            if path == m.MANAGER_SELECTION_HTML:
                return 200, (dist / "manager-selection/index.html").read_bytes()
            if path == "/assets/probe.js":
                return 200, (dist / "assets/probe.js").read_bytes()
            raise AssertionError("unexpected simulated HTTP path: " + path)

        m._launchctl_print = launch_print
        m._launchctl_action = launch_action
        m._http_get = http_get
        m._verify_historical_product_readback = lambda **kwargs: {"status": "SYNTHETIC_NOT_PRODUCT_ACCEPTANCE"}
        write_json(m.PLAN_PATH, plan)
        m._stage_api_plist(plan)
        plan = json.loads(m.PLAN_PATH.read_text())
        return {"plan": plan, "base": base, "release": release, "original": original,
                "base_record": base_record, "runtime": runtime, "core": core}

    def test_active_replace_without_lease_refuses_before_writing(self):
        pointer = self.m.ACTIVE_API_PLIST
        pointer.write_bytes(b"original\n")
        with self.assertRaisesRegex(ValueError, "SHARED_LOCK_REQUIRED"):
            self.m._atomic_replace_bytes(pointer, b"replacement\n", pointer,
                                         expected_current_sha=digest(b"original\n"))
        self.assertEqual(pointer.read_bytes(), b"original\n")

    def test_missing_active_restore_without_lease_refuses_before_writing(self):
        backup = self.root / "backup.plist"
        backup.write_bytes(b"old\n")
        with self.assertRaisesRegex(ValueError, "SHARED_LOCK_REQUIRED"):
            self.m._create_preimage_exclusive(self.m.ACTIVE_API_PLIST, b"old\n", backup)
        self.assertFalse(self.m.ACTIVE_API_PLIST.exists())

    def test_automatic_recovery_without_lease_refuses_before_runtime_observation(self):
        backup = self.root / "backup.plist"
        backup.write_bytes(b"old\n")
        plan = {"before": {"active_api_plist_sha256": digest(b"old\n"), "loaded_identity": {}},
                "target": {}}
        self.m._observe_loaded = forbidden
        with self.assertRaisesRegex(ValueError, "SHARED_LOCK_REQUIRED"):
            self.m._restore_after_failure(plan, backup, b"old\n", "a" * 64,
                                          self.root / "operation", "synthetic failure")

    def test_guard_hash_mismatch_refuses_before_executing(self):
        self.assertTrue(hasattr(self.m, "_load_integration_guard"), "actual executable lacks a pinned integration guard")
        path, _ = self.install_tiny_guard()
        path.write_text("raise AssertionError('UNPINNED_CODE_EXECUTED')\n")
        with self.assertRaisesRegex(ValueError, "INTEGRATION_GUARD_SHA_MISMATCH"):
            self.m._load_integration_guard()

    def test_guard_executes_exact_bytes_checked_even_if_path_replaced(self):
        self.assertTrue(hasattr(self.m, "_load_integration_guard"), "actual executable lacks a pinned integration guard")
        path, original = self.install_tiny_guard()
        real_read = self.m._regular_file

        def replace_after_read(target, label):
            raw = real_read(target, label)
            if target == path:
                path.write_bytes(original.replace(b"'trusted'", b"'untrusted'"))
            return raw

        with mock.patch.object(self.m, "_regular_file", side_effect=replace_after_read):
            guard = self.m._load_integration_guard()
        self.assertEqual(guard.MARKER, "trusted")

    def test_guard_ignores_import_path_and_module_shadow(self):
        self.assertTrue(hasattr(self.m, "_load_integration_guard"), "actual executable lacks a pinned integration guard")
        self.install_tiny_guard()
        shadow = types.ModuleType("api_release_integration")
        shadow.MARKER = "shadow"
        with mock.patch.dict(sys.modules, {"api_release_integration": shadow,
                                           "ops.api_release_integration": shadow}):
            self.assertEqual(self.m._load_integration_guard().MARKER, "trusted")

    def test_task_private_roots_still_contend_on_one_pointer_lock(self):
        guard = self.guard()
        other = load(SOURCE)
        other.ACTIVE_API_PLIST = self.m.ACTIVE_API_PLIST
        other.EVIDENCE_ROOT = self.root / "other-task/evidence"
        other.INTEGRATION_GUARD_PATH = self.m.INTEGRATION_GUARD_PATH
        other.INTEGRATION_GUARD_SHA256 = self.m.INTEGRATION_GUARD_SHA256
        with guard.shared_api_release_lock(self.m.ACTIVE_API_PLIST):
            with self.assertRaisesRegex((ValueError, TimeoutError, BlockingIOError), "LOCK_BUSY|LOCK.*BUSY"):
                with other._switch_lock():
                    self.fail("a second task acquired the same API pointer lock")

    def test_direct_run_switch_acquires_shared_lock_before_preflight(self):
        guard = self.guard()
        self.m._preflight = forbidden
        with guard.shared_api_release_lock(self.m.ACTIVE_API_PLIST):
            with self.assertRaisesRegex((ValueError, TimeoutError, BlockingIOError), "LOCK_BUSY|LOCK.*BUSY"):
                self.m._run_switch({"allowed_paths": [str(self.m.ACTIVE_API_PLIST),
                    str(self.m.ACTIVE_API_PLIST.with_name(".com.lexi.v35.api-only.release.lock"))]},
                    confirmation=self.m.CONFIRM_SWITCH,
                                   expected_current_sha="a" * 64, expected_staged_sha="b" * 64)

    def test_direct_run_rollback_acquires_shared_lock_before_receipt_reads(self):
        guard = self.guard()
        with guard.shared_api_release_lock(self.m.ACTIVE_API_PLIST):
            with self.assertRaisesRegex((ValueError, TimeoutError, BlockingIOError), "LOCK_BUSY|LOCK.*BUSY"):
                self.m._run_rollback({"allowed_paths": [str(self.m.ACTIVE_API_PLIST),
                    str(self.m.ACTIVE_API_PLIST.with_name(".com.lexi.v35.api-only.release.lock"))]},
                    receipt_path=self.root / "missing.json",
                                     confirmation=self.m.CONFIRM_ROLLBACK, expected_current_sha="a" * 64)

    def test_legacy_candidate_is_refused_by_actual_preflight(self):
        self.guard()
        probe = load(WORK / "probe_cutover_boundaries.py")
        with self.assertRaisesRegex(ValueError, "BASE_AND_DELTA_REQUIRED|LEGACY_PACKAGE_REJECTED"):
            probe.probe_stale_package_preflight(self.root / "legacy", self.m)

    def test_inventory_provenance_backend_is_not_executed(self):
        self.assertTrue(hasattr(self.m, "_load_integration_guard"), "actual executable lacks a pinned integration guard")
        self.install_tiny_guard()
        backend = self.root / "task-builder.py"
        backend.write_text("raise AssertionError('TASK_BUILDER_MUST_NOT_EXECUTE')\n")
        self.m.INVENTORY_BACKEND_PATH = backend
        observed = self.m._load_inventory_backend({"source": {
            "inventory_backend_path": str(backend), "inventory_backend_sha256": digest(backend.read_bytes())}})
        self.assertEqual(observed.MARKER, "trusted")

    def test_apply_switches_exact_integrated_package_and_preserves_other_module(self):
        fixture = self.integrated_fixture()
        plan = fixture["plan"]
        result = self.m._run_switch(plan, confirmation=self.m.CONFIRM_SWITCH,
                                    expected_current_sha=digest(fixture["original"]),
                                    expected_staged_sha=plan["target"]["staged_api_plist_sha256"])
        self.assertEqual(result["status"], "API_ONLY_R2_SWITCHED_AND_READBACK_VERIFIED")
        self.assertEqual(self.m.ACTIVE_API_PLIST.read_bytes(), self.m.STAGED_API_PLIST_PATH.read_bytes())
        self.assertEqual((fixture["release"] / "app/domains/manager_research/current.py").read_bytes(),
                         b"accepted_manager_fix = True\n")
        receipt = json.loads(Path(result["receipt_path"]).read_text())
        self.assertEqual(receipt["api_release_integration"]["base"], fixture["base_record"])

    def test_apply_refuses_active_inventory_drift_before_bootout(self):
        fixture = self.integrated_fixture()
        plan = fixture["plan"]
        (fixture["base"] / "app/domains/manager_research/current.py").write_bytes(b"newer_accepted_fix = True\n")
        with self.assertRaisesRegex(ValueError, "ACTIVE_APPLICATION_INVENTORY_DRIFT"):
            self.m._run_switch(plan, confirmation=self.m.CONFIRM_SWITCH,
                               expected_current_sha=digest(fixture["original"]),
                               expected_staged_sha=plan["target"]["staged_api_plist_sha256"])
        self.assertEqual(self.m.ACTIVE_API_PLIST.read_bytes(), fixture["original"])
        self.assertEqual(fixture["runtime"]["actions"], [])

    def test_apply_rechecks_active_base_after_bootout_before_pointer_write(self):
        fixture = self.integrated_fixture()
        plan = fixture["plan"]

        def drift_after_bootout(action):
            if action == "bootout":
                (fixture["base"] / "app/domains/manager_research/current.py").write_bytes(b"in_place_drift = True\n")

        fixture["runtime"]["hook"] = drift_after_bootout
        with self.assertRaisesRegex(ValueError, "ROLLBACK_INCOMPLETE"):
            self.m._run_switch(plan, confirmation=self.m.CONFIRM_SWITCH,
                               expected_current_sha=digest(fixture["original"]),
                               expected_staged_sha=plan["target"]["staged_api_plist_sha256"])
        self.assertEqual(self.m.ACTIVE_API_PLIST.read_bytes(), fixture["original"])
        self.assertEqual(fixture["runtime"]["actions"], ["bootout"])

    def test_operator_rollback_restores_recorded_legacy_base_from_candidate(self):
        fixture = self.integrated_fixture()
        plan = fixture["plan"]
        applied = self.m._run_switch(plan, confirmation=self.m.CONFIRM_SWITCH,
                                     expected_current_sha=digest(fixture["original"]),
                                     expected_staged_sha=plan["target"]["staged_api_plist_sha256"])
        self.assertNotIn("api_integration", json.loads((fixture["base"] / "release-manifest.json").read_text()))
        result = self.m._run_rollback(plan, receipt_path=Path(applied["receipt_path"]),
                                      confirmation=self.m.CONFIRM_ROLLBACK,
                                      expected_current_sha=plan["target"]["staged_api_plist_sha256"])
        self.assertEqual(result["status"], "ROLLED_BACK_TO_PREIMAGE")
        self.assertEqual(self.m.ACTIVE_API_PLIST.read_bytes(), fixture["original"])
        self.assertEqual(fixture["runtime"]["identity"]["V35_RELEASE_ID"], "base-accepted")

    def test_failed_bootstrap_recovers_using_same_lock_and_exact_base(self):
        fixture = self.integrated_fixture()
        plan, core = fixture["plan"], fixture["core"]
        failed_once = False

        def fail_candidate_bootstrap(action):
            nonlocal failed_once
            if action == "bootstrap" and not failed_once:
                failed_once = True
                fixture["runtime"]["identity"] = None
                with self.assertRaisesRegex((ValueError, TimeoutError, BlockingIOError), "LOCK_BUSY|LOCK.*BUSY"):
                    with core.shared_api_release_lock(self.m.ACTIVE_API_PLIST, timeout_seconds=0):
                        self.fail("automatic recovery released the shared pointer lock")
                raise ValueError("SYNTHETIC_BOOTSTRAP_FAILURE")

        fixture["runtime"]["hook"] = fail_candidate_bootstrap
        with self.assertRaisesRegex(ValueError, "FAILED_AND_ROLLED_BACK"):
            self.m._run_switch(plan, confirmation=self.m.CONFIRM_SWITCH,
                               expected_current_sha=digest(fixture["original"]),
                               expected_staged_sha=plan["target"]["staged_api_plist_sha256"])
        self.assertEqual(self.m.ACTIVE_API_PLIST.read_bytes(), fixture["original"])
        self.assertEqual(fixture["runtime"]["identity"]["V35_RELEASE_ID"], "base-accepted")

    def test_recovery_keeps_verified_guard_if_helper_changes_during_transaction(self):
        pinned_copy = self.root / "trusted_core.py"
        pinned_copy.write_bytes(CORE.read_bytes())
        self.m.INTEGRATION_GUARD_PATH = pinned_copy
        self.m.INTEGRATION_GUARD_SHA256 = digest(pinned_copy.read_bytes())
        fixture = self.integrated_fixture()
        plan = fixture["plan"]
        failed_once = False

        def replace_helper_and_fail_bootstrap(action):
            nonlocal failed_once
            if action == "bootstrap" and not failed_once:
                failed_once = True
                pinned_copy.write_text("raise AssertionError('REPLACED_HELPER_MUST_NEVER_EXECUTE')\n")
                fixture["runtime"]["identity"] = None
                raise ValueError("SYNTHETIC_BOOTSTRAP_FAILURE")

        fixture["runtime"]["hook"] = replace_helper_and_fail_bootstrap
        with self.assertRaisesRegex(ValueError, "FAILED_AND_ROLLED_BACK"):
            self.m._run_switch(plan, confirmation=self.m.CONFIRM_SWITCH,
                               expected_current_sha=digest(fixture["original"]),
                               expected_staged_sha=plan["target"]["staged_api_plist_sha256"])
        self.assertEqual(self.m.ACTIVE_API_PLIST.read_bytes(), fixture["original"])
        self.assertEqual(fixture["runtime"]["identity"]["V35_RELEASE_ID"], "base-accepted")
        with self.assertRaisesRegex(ValueError, "INTEGRATION_GUARD_SHA_MISMATCH"):
            with self.m._switch_lock():
                self.fail("a new transaction accepted the replaced helper")

    def test_missing_pointer_recovery_uses_recorded_base_without_forward_check(self):
        fixture = self.integrated_fixture()
        backup = self.root / "backup.plist"
        write(backup, fixture["original"])
        fixture["runtime"]["identity"] = None
        self.m.ACTIVE_API_PLIST.unlink()
        with self.m._switch_lock() as lease:
            result = self.m._restore_after_failure(
                fixture["plan"], backup, fixture["original"],
                fixture["plan"]["target"]["staged_api_plist_sha256"], self.root / "recovery",
                "SYNTHETIC_MISSING_POINTER", self.m._file_metadata(backup),
                lock_lease=lease, base_record=fixture["base_record"])
        self.assertEqual(result["status"], "ROLLED_BACK_TO_PREIMAGE")
        self.assertEqual(self.m.ACTIVE_API_PLIST.read_bytes(), fixture["original"])

    def test_recovery_refuses_unknown_pointer_before_service_mutation(self):
        fixture = self.integrated_fixture()
        backup = self.root / "backup.plist"
        write(backup, fixture["original"])
        self.m.ACTIVE_API_PLIST.write_bytes(b"unknown publisher pointer\n")
        with self.m._switch_lock() as lease:
            result = self.m._restore_after_failure(
                fixture["plan"], backup, fixture["original"],
                fixture["plan"]["target"]["staged_api_plist_sha256"], self.root / "recovery",
                "SYNTHETIC_UNKNOWN_POINTER", self.m._file_metadata(backup),
                lock_lease=lease, base_record=fixture["base_record"])
        self.assertEqual(result["status"], "ROLLBACK_INCOMPLETE")
        self.assertIn("ACTIVE_PLIST_UNEXPECTED_SHA", result["reason"])
        self.assertEqual(self.m.ACTIVE_API_PLIST.read_bytes(), b"unknown publisher pointer\n")
        self.assertEqual(fixture["runtime"]["actions"], [])

    def test_guard_cache_does_not_mask_changed_file(self):
        self.assertTrue(hasattr(self.m, "_load_integration_guard"))
        path, _ = self.install_tiny_guard()
        self.assertEqual(self.m._load_integration_guard().MARKER, "trusted")
        path.write_text("raise AssertionError('changed helper executed')\n")
        with self.assertRaisesRegex(ValueError, "INTEGRATION_GUARD_SHA_MISMATCH"):
            self.m._load_integration_guard()

    def test_execute_requires_shared_lock_path_in_frozen_allowlist_before_create(self):
        self.guard()
        self.m._preflight = forbidden
        error = None
        try:
            self.m._run_switch({"allowed_paths": [str(self.m.ACTIVE_API_PLIST)]},
                               confirmation=self.m.CONFIRM_SWITCH,
                               expected_current_sha="a" * 64, expected_staged_sha="b" * 64)
        except Exception as exc:
            error = exc
        lock_path = self.m.ACTIVE_API_PLIST.with_name(".com.lexi.v35.api-only.release.lock")
        self.assertFalse(lock_path.exists(), "an undeclared publication lock was created")
        self.assertIsInstance(error, ValueError)
        self.assertIn("SHARED_LOCK_PATH_NOT_AUTHORIZED", str(error))


if __name__ == "__main__":
    unittest.main(verbosity=2)
