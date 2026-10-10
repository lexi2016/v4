"""Isolated checks of the historical 8873 publisher's guarded callsite.

These tests bind every path to a temporary fixture.  They never invoke a real
launcher or contact the gateway.  Guard/lock algorithms use the actual modules.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import marshal
import os
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import sys
import types

import pytest

from ops import api_release_integration as integration


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = Path(os.environ.get(
    "NATIVE_REFERENCE_PATH", str(ROOT / "publisher_reference" / "api_only_cutover_r2_ready.py")
))


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _reference(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    spec = importlib.util.spec_from_file_location(
        "_native_api_reference_" + tmp_path.name.replace("-", "_"), REFERENCE
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    active = tmp_path / "LaunchAgents" / "com.lexi.v35.api-only.plist"
    active.parent.mkdir()
    monkeypatch.setattr(module, "ACTIVE_API_PLIST", active)
    monkeypatch.setattr(module, "EVIDENCE_ROOT", tmp_path / "evidence")
    # Test-only review pins bind the real code under test. Production pins are
    # frozen in the reference and must never self-refresh at runtime.
    pins = getattr(module, "RELEASE_GUARD_SHA256", {})
    if pins:
        monkeypatch.setattr(module, "RELEASE_GUARD_ROOT", ROOT)
        monkeypatch.setattr(module, "RELEASE_GUARD_SHA256", {
            name: _sha((ROOT / name).read_bytes()) for name in pins
        })
    return module, active


def test_native_lock_is_the_existing_gateway_owned_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reference, active = _reference(monkeypatch, tmp_path)
    with reference._locked() as lease:
        integration.assert_api_release_lock(lease, active, role="gateway")
        with pytest.raises(ValueError, match="API_RELEASE_SHARED_LOCK_BUSY"):
            with integration.shared_api_release_lock(active, timeout_seconds=0.02):
                pytest.fail("a second lock holder must not enter")
    assert not active.exists()


@pytest.mark.parametrize("lease", [None, object()])
def test_direct_native_switch_rejects_unowned_lease_before_preflight(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, lease: object,
) -> None:
    reference, active = _reference(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="OWNER_LOCK_LEASE_NOT_OWNED"):
        reference._run_switch(
            {}, confirmation=reference.CONFIRM_SWITCH,
            expected_current_sha="0" * 64, expected_staged_sha="1" * 64,
            lock_lease=lease,
        )
    assert not active.exists()
    assert not reference.EVIDENCE_ROOT.exists()


def test_direct_native_switch_rejects_expired_real_lease(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reference, active = _reference(monkeypatch, tmp_path)
    with integration.shared_api_release_lock(active) as lease:
        pass
    with pytest.raises(ValueError, match="OWNER_LOCK_LEASE_NOT_ACTIVE"):
        reference._run_switch(
            {}, confirmation=reference.CONFIRM_SWITCH,
            expected_current_sha="0" * 64, expected_staged_sha="1" * 64,
            lock_lease=lease,
        )
    assert not active.exists()
    assert not reference.EVIDENCE_ROOT.exists()


def test_business_rollback_rejects_whole_release_pointer_restore(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reference, active = _reference(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="BUSINESS_MODULE_REVERSE_DELTA_REQUIRED"):
        reference._run_rollback(
            {}, receipt_path=tmp_path / "old-receipt.json",
            confirmation=reference.CONFIRM_ROLLBACK,
            expected_current_sha="0" * 64,
        )
    assert not active.exists()
    assert not reference.EVIDENCE_ROOT.exists()


def test_native_guard_refuses_missing_review_pin_before_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reference, active = _reference(monkeypatch, tmp_path)
    monkeypatch.setattr(reference, "RELEASE_GUARD_SHA256", {}, raising=False)
    with pytest.raises(ValueError, match="API_MODULE_GUARD_PIN_REQUIRED"):
        reference._load_release_guard()
    assert not active.exists()


def test_native_guard_refuses_changed_dependency_before_executing_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    reference, active = _reference(monkeypatch, tmp_path)
    isolated_root = tmp_path / "reviewed-tool-root"
    isolated_root.mkdir()
    marker = tmp_path / "untrusted-code-ran"
    pins = getattr(reference, "RELEASE_GUARD_SHA256", {})
    for relative in pins:
        target = isolated_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    target = isolated_root / "ops" / "api_release_integration.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\n")
    monkeypatch.setattr(reference, "RELEASE_GUARD_ROOT", isolated_root, raising=False)
    with pytest.raises(ValueError, match="API_MODULE_GUARD_CLOSURE_SHA_MISMATCH"):
        reference._load_release_guard()
    assert not marker.exists()
    assert not active.exists()


def test_common_inventory_matches_historical_backend_for_file_modes_and_symlinks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from ops import build_release_candidate as historical_backend

    reference, _active = _reference(monkeypatch, tmp_path)
    tree = tmp_path / "inventory-fixture"
    tree.mkdir()
    plain = tree / "module.py"
    plain.write_bytes(b"VALUE = 1\n")
    plain.chmod(0o444)
    executable = tree / "run.sh"
    executable.write_bytes(b"#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    (tree / "link.py").symlink_to("module.py")
    (tree / "absent.py").symlink_to("missing.py")
    backend = ROOT / "ops/build_release_candidate.py"
    monkeypatch.setattr(reference, "INVENTORY_BACKEND_PATH", backend)
    guard = reference._load_inventory_backend({"source": {
        "inventory_backend_path": str(backend), "inventory_backend_sha256": _sha(backend.read_bytes()),
    }})
    expected = historical_backend.inventory_tree(tree)
    assert guard.inventory_tree(tree) == expected
    assert guard.inventory_digest(expected) == historical_backend.inventory_digest(expected)


def test_historical_inventory_backend_is_evidence_and_is_not_executed(monkeypatch, tmp_path):
    reference, _active = _reference(monkeypatch, tmp_path)
    marker = tmp_path / "historical-dynamic-code-ran"
    backend = tmp_path / "frozen-inventory-backend.py"
    backend.write_text(f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\n")
    monkeypatch.setattr(reference, "INVENTORY_BACKEND_PATH", backend)
    result = reference._load_inventory_backend({"source": {
        "inventory_backend_path": str(backend), "inventory_backend_sha256": _sha(backend.read_bytes()),
    }})
    assert result.inventory_tree is integration.inventory_tree
    assert not marker.exists()


def test_native_guard_rejects_cached_module_from_another_source_root(monkeypatch, tmp_path):
    reference, _active = _reference(monkeypatch, tmp_path)
    monkeypatch.setitem(sys.modules, "ops.api_business_modules", types.SimpleNamespace(
        __file__=str(tmp_path / "unreviewed-module.py")))
    with pytest.raises(ValueError, match="API_MODULE_GUARD_IMPORT_ORIGIN_MISMATCH"):
        reference._load_release_guard()


def test_native_guard_fresh_import_executes_verified_source_not_bytecode_cache(monkeypatch, tmp_path):
    reference, _active = _reference(monkeypatch, tmp_path)
    reviewed = tmp_path / "reviewed-tools"
    for relative in reference.RELEASE_GUARD_SHA256:
        target = reviewed / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    core = reviewed / "ops/api_release_integration.py"
    info = core.stat()
    marker = tmp_path / "unverified-bytecode-ran"
    untrusted_code = compile(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\n"
        "raise RuntimeError('UNVERIFIED_BYTECODE_WAS_EXECUTED')\n", str(core), "exec")
    cached = Path(importlib.util.cache_from_source(str(core)))
    cached.parent.mkdir()
    cached.write_bytes(importlib.util.MAGIC_NUMBER + struct.pack("<III", 0, int(info.st_mtime), info.st_size)
                       + marshal.dumps(untrusted_code))
    script = "\n".join([
        "import importlib.util, pathlib",
        f"spec = importlib.util.spec_from_file_location('native_guard', {str(REFERENCE)!r})",
        "reference = importlib.util.module_from_spec(spec)",
        "spec.loader.exec_module(reference)",
        f"reference.RELEASE_GUARD_ROOT = pathlib.Path({str(reviewed)!r})",
        f"reference.RELEASE_GUARD_SHA256 = {reference.RELEASE_GUARD_SHA256!r}",
        "guard = reference._load_release_guard()",
        "assert callable(guard.verify_api_release_candidate)",
    ])
    process = subprocess.run([sys.executable, "-I", "-c", script], cwd=tmp_path,
                             capture_output=True, text=True, timeout=20)
    assert process.returncode == 0, process.stdout + process.stderr
    assert not marker.exists()


def test_reference_delivery_pins_match_the_actual_reviewed_guard_closure():
    spec = importlib.util.spec_from_file_location("_delivered_reference_pins", REFERENCE)
    assert spec is not None and spec.loader is not None
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    guard = reference._load_release_guard()
    assert guard is integration


def _dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


class _SyntheticClock:
    def __init__(self):
        self.elapsed = 0.0

    def monotonic(self):
        return self.elapsed

    def sleep(self, seconds):
        self.elapsed += seconds


class _SyntheticLauncher:
    """Substitute only the external launchd/HTTP observations and actions."""

    def __init__(self, reference, before, candidate, analyses, extensions):
        self.reference = reference
        self.before = before
        self.candidate = candidate
        self.loaded = dict(before)
        self.actions = []
        self.analyses = analyses
        self.extensions = extensions
        self.candidate_health_failure = False
        self.candidate_nonrunning = False
        self.candidate_bootstrap_error = False
        self.after_bootout = None

    def print_job(self):
        if self.loaded is None:
            raise ValueError("API_ONLY_LAUNCH_AGENT_NOT_LOADED:SYNTHETIC")
        return "\n".join([
            "state = " + self.loaded["state"], "pid = " + self.loaded.get("pid", "101"),
            *[key + "=" + self.loaded[key] for key in (
                "V35_APP_ROOT", "V35_RELEASE_ID", "V35_RELEASE_MANIFEST_SHA256",
            )],
        ])

    def action(self, action):
        self.actions.append(action)
        if action == "bootout":
            self.loaded = None
            if self.after_bootout is not None:
                callback, self.after_bootout = self.after_bootout, None
                callback()
            return
        assert action == "bootstrap"
        identity = self.reference._identity_from_plist(self.reference.ACTIVE_API_PLIST.read_bytes())
        candidate = identity["V35_APP_ROOT"] == str(self.candidate / "app")
        self.loaded = {**identity, "state": "waiting" if candidate and self.candidate_nonrunning else "running", "pid": "102"}
        if candidate and self.candidate_bootstrap_error:
            raise ValueError("LAUNCHCTL_ACTION_FAILED:bootstrap:SYNTHETIC_AFTER_START")

    def get(self, path):
        if self.loaded is None:
            raise ValueError("API_ONLY_HTTP_READBACK_FAILED:SYNTHETIC_NOT_LOADED")
        candidate = self.loaded["V35_APP_ROOT"] == str(self.candidate / "app")
        if candidate and self.candidate_health_failure:
            raise ValueError("API_ONLY_HTTP_READBACK_FAILED:SYNTHETIC_CANDIDATE_HEALTH")
        if path == "/openapi.json":
            return 200, json.dumps({"paths": {self.reference.MANAGER_WORKSPACE_ROUTE: {"get": {}}}}).encode()
        if path in self.analyses:
            payload = dict(self.analyses[path])
            if candidate:
                payload["consumption_validation"] = self.extensions[path]
            return 200, json.dumps(payload, separators=(",", ":")).encode()
        if path.startswith("/api/v4/manager/research/workspace?"):
            return 200, b"{}"
        app = Path(self.loaded["V35_APP_ROOT"])
        relative = "manager-selection/index.html" if path == "/manager-selection/" else path.lstrip("/")
        return 200, (app / "apps/web/dist" / relative).read_bytes()


def _native_fixture(monkeypatch, tmp_path, *, duplicate_release_environment=False):
    from test_api_business_modules import build, setup_active

    reference, _unused = _reference(monkeypatch, tmp_path)
    active = setup_active(tmp_path / "synthetic")
    task = tmp_path / "historical-task"
    evidence = task / "completion_20261008/workspace_failure"
    paths = {
        "TASK_ROOT": task,
        "EVIDENCE_ROOT": evidence,
        "PLAN_PATH": evidence / "staged/api_only_cutover_plan_r2.ready.json",
        "STAGED_API_PLIST_PATH": evidence / "staged/com.lexi.v35.api-only.r2.ready.plist",
        "STAGED_API_PLIST_DIFF_PATH": evidence / "staged/staged_api_plist_r2.ready.diff.json",
        "RELEASE_STAGE_RECEIPT_PATH": evidence / "api_release_r2_stage_receipt.json",
        "PRODUCT_BASELINE_PATH": task / "control/pre_switch_product_baseline.json",
        "P2_REVIEW_PATH": task / "review/p2_delta_independent_review.json",
        "P2_DELTA_RECEIPT_PATH": task / "receipts/p2_delta_receipt.json",
        "API_INVENTORY_RECEIPT_PATH": evidence / "api_candidate_r2_inventory.json",
        "BUSINESS_FIX_REVIEW_PATH": evidence / "review/independent_review.json",
        "BUSINESS_FIX_RECEIPT_PATH": evidence / "workspace_failure_business_fix_receipt.json",
        "ACTIVE_API_PLIST": active["plist"],
        "ACTIVE_SCHEDULER_PLIST": task / "readonly/scheduler.plist",
        "STAGE_CENTER_SCHEDULER_PLIST": task / "readonly/stage-scheduler.plist",
        "DISABLED_BINDING_PATH": task / "readonly/disabled-binding.json",
        "SCREEN_AUTHORITY_ROOT": task / "readonly/screen-data",
        "FORMAL_MANAGER_STATE": active["state"],
        "INVENTORY_BACKEND_PATH": ROOT / "ops/build_release_candidate.py",
        "PINNED_PYTHON": Path("/usr/bin/python3"),
    }
    for key, value in paths.items():
        monkeypatch.setattr(reference, key, value)
    _dump(reference.ACTIVE_SCHEDULER_PLIST, {"unchanged": "scheduler"})
    _dump(reference.STAGE_CENTER_SCHEDULER_PLIST, {"unchanged": "stage"})
    _dump(reference.DISABLED_BINDING_PATH, {"enabled": False,
        "announcement_collection_enabled": False, "plan_material_refresh_only": False,
        "manager_state_root": str(active["state"])})

    payload = plistlib.loads(active["plist"].read_bytes())
    payload["KeepAlive"], payload["RunAtLoad"] = True, False
    payload["ProgramArguments"][1:1] = [
        "PRODUCTION_ALLOWED=false", "BUY_GATE_UPDATED=false", "ORDERS_SENT=false",
        f"V4_MANAGER_PLAN_OWNER_BINDING_PATH={reference.DISABLED_BINDING_PATH}",
        f"V4_MANAGER_SCREEN_AUTHORITY_ROOT={reference.SCREEN_AUTHORITY_ROOT}",
    ]
    html = active["initial_app"] / "apps/web/dist/manager-selection/index.html"
    html.parent.mkdir(parents=True)
    html.write_bytes(b'<script src="/assets/current.js"></script>\n')
    base_manifest_path = active["initial_app"].parent / "release-manifest.json"
    base_manifest = json.loads(base_manifest_path.read_text())
    entries = integration.inventory_tree(active["initial_app"])
    base_manifest["application_inventory"] = {
        "entries": entries, "entry_count": len(entries), "aggregate_sha256": integration.inventory_digest(entries),
    }
    _dump(base_manifest_path, base_manifest)
    payload["ProgramArguments"] = [
        "V35_RELEASE_MANIFEST_SHA256=" + _sha(base_manifest_path.read_bytes())
        if text.startswith("V35_RELEASE_MANIFEST_SHA256=") else text
        for text in payload["ProgramArguments"]
    ]
    if duplicate_release_environment:
        release_keys = {"V35_APP_ROOT", "V35_RELEASE_ID",
                        "V35_RELEASE_MANIFEST_PATH", "V35_RELEASE_MANIFEST_SHA256"}
        payload["EnvironmentVariables"] = {
            key: value for item in payload["ProgramArguments"] if "=" in item
            for key, value in [item.split("=", 1)] if key in release_keys
        }
    active["plist"].write_bytes(plistlib.dumps(payload, sort_keys=True))

    candidate = build(active, "A", "alpha", {"modules/alpha.py": b"ALPHA = 1\n"})
    manifest_path = candidate / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    inventory = manifest["application_inventory"]
    monkeypatch.setattr(reference, "EXPECTED_RELEASE_ROOT", candidate)
    monkeypatch.setattr(reference, "EXPECTED_API_ROOT", candidate / "app")
    monkeypatch.setattr(reference, "EXPECTED_API_INVENTORY_SHA256", inventory["aggregate_sha256"])
    monkeypatch.setattr(reference, "EXPECTED_DIST_TREE_SHA256", _sha(b"SYNTHETIC_SAME_STATIC_TREE"))
    monkeypatch.setattr(reference, "BUSINESS_FIX_CANDIDATE_SHA256", _sha(b"ALPHA = 1\n"))
    shutil.copytree(candidate / "app", task / "candidate/api/app", symlinks=True)
    _dump(reference.P2_REVIEW_PATH, {"status": {"REVIEWED": "PASS", "BEHAVIOR_VERIFIED": "PASS_SYNTHETIC"}})
    _dump(reference.P2_DELTA_RECEIPT_PATH, {"dist_sync": {
        "same_paths_and_bytes": True, "source_tree_sha256": reference.EXPECTED_DIST_TREE_SHA256,
        "target_tree_sha256": reference.EXPECTED_DIST_TREE_SHA256,
    }})
    _dump(reference.API_INVENTORY_RECEIPT_PATH, {"aggregate_sha256": inventory["aggregate_sha256"]})
    _dump(reference.BUSINESS_FIX_REVIEW_PATH, {"review_status": "PASS", "tested_status": "PASS",
        "behavior_verified_status": "PASS_SYNTHETIC", "findings": {"P0": [], "P1": [], "P2": []},
        "frozen_scope": {"candidate_sha256": reference.BUSINESS_FIX_CANDIDATE_SHA256}})
    _dump(reference.BUSINESS_FIX_RECEIPT_PATH, {"change": {
        "candidate_source_sha256": reference.BUSINESS_FIX_CANDIDATE_SHA256}})
    stage = {"status": "STAGED_AND_VERIFIED_NOT_DEPLOYED", "release_root": str(candidate),
        "release_manifest_sha256": _sha(manifest_path.read_bytes()),
        "application_inventory_sha256": inventory["aggregate_sha256"],
        "application_inventory_entries": len(inventory["entries"])}
    _dump(reference.RELEASE_STAGE_RECEIPT_PATH, {**stage, "receipt_sha256": reference._canonical_sha(stage)})
    for key in ("P2_REVIEW", "P2_DELTA_RECEIPT", "API_INVENTORY_RECEIPT", "BUSINESS_FIX_REVIEW", "BUSINESS_FIX_RECEIPT"):
        monkeypatch.setattr(reference, key + "_SHA256", _sha(getattr(reference, key + "_PATH").read_bytes()))

    analyses, extensions, baseline_rows, extension_pins = {}, {}, [], {}
    for name, date, publication in (("current_analysis", "20261008", "2026-10-07"),
                                    ("legacy_analysis", "20261007", "2026-10-06")):
        path = f"/api/v4/manager/research/announcements/analysis?date={date}&publication_date={publication}"
        product = _sha(name.encode())
        selection = {"status": "SYNTHETIC", "product_sha256": product, "gaps": [], "stocks": [], "article_decisions": []}
        analysis = {"status": "SYNTHETIC", "product_sha256": product, "gaps": [], "stock_selection": selection}
        response = {"analysis": analysis, "owner_import_receipt": None}
        analyses[path] = response
        baseline_rows.append({"name": name, "path": path, "http_status": 200,
            "analysis": analysis, "stock_selection": selection, "owner_import_receipt": None,
            "response_sha256": _sha(json.dumps(response, separators=(",", ":")).encode()),
            "stock_selection_list_lengths": {"stocks": 0, "article_decisions": 0, "gaps": 0}})
        legacy = name == "legacy_analysis"
        extension = {key: None for key in sorted(reference.CONSUMPTION_VALIDATION_KEYS)}
        extension.update(schema_version=reference.CONSUMPTION_VALIDATION_SCHEMA,
            target_trade_date=date, publication_date=publication,
            status="NOT_CONSUMED_INVALID" if legacy else "VERIFIED",
            validation_status="CANNOT_CONFIRM" if legacy else "VERIFIED", consumed=False,
            product_sha256=product, failure_stage="JUDGMENT_RECEIPT" if legacy else None,
            gaps=["ANNOUNCEMENT_AGENT_JUDGMENT_RECEIPT_INVALID"] if legacy else [],
            RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
        extensions[path] = extension
        extension_pins[name] = reference._consumption_validation_sha(extension)
    baseline_rows.append({"name": "current_workspace", "http_status": 200,
        "path": "/api/v4/manager/research/workspace?date=20261008&selection_date=20261007&announcement_date=20261007&view=dynamic",
        "response_sha256": _sha(b"{}")})
    _dump(reference.PRODUCT_BASELINE_PATH, {"scope": "ROOT_READ_ONLY_PRE_SWITCH_PRODUCT_BASELINE", "results": baseline_rows})
    monkeypatch.setattr(reference, "PRODUCT_BASELINE_SHA256", _sha(reference.PRODUCT_BASELINE_PATH.read_bytes()))
    monkeypatch.setattr(reference, "CONSUMPTION_VALIDATION_CANONICAL_SHA256", extension_pins)

    before_identity = {**reference._identity_from_plist(active["plist"].read_bytes()), "state": "running", "pid": "101"}
    plan = {"target": {"release_root": str(candidate), "app_root": str(candidate / "app"),
        "release_id": candidate.name, "release_manifest_sha256": _sha(manifest_path.read_bytes()),
        "application_inventory_sha256": inventory["aggregate_sha256"]},
        "source": {"inventory_backend_path": str(reference.INVENTORY_BACKEND_PATH),
            "inventory_backend_sha256": _sha(reference.INVENTORY_BACKEND_PATH.read_bytes()),
            "source_candidate_app_root": str(task / "candidate/api/app"),
            "release_stage_receipt_sha256": _sha(reference.RELEASE_STAGE_RECEIPT_PATH.read_bytes()),
            "p2_independent_review_sha256": reference.P2_REVIEW_SHA256,
            "business_fix_independent_review_sha256": reference.BUSINESS_FIX_REVIEW_SHA256,
            "business_fix_receipt_sha256": reference.BUSINESS_FIX_RECEIPT_SHA256},
        "before": {"active_api_plist_sha256": _sha(active["plist"].read_bytes()),
            "loaded_identity": before_identity, "scheduler_plist_sha256": _sha(reference.ACTIVE_SCHEDULER_PLIST.read_bytes()),
            "stage_center_scheduler_plist_sha256": _sha(reference.STAGE_CENTER_SCHEDULER_PLIST.read_bytes())},
        "guards": {"disabled_binding_path": str(reference.DISABLED_BINDING_PATH),
            "disabled_binding_sha256": _sha(reference.DISABLED_BINDING_PATH.read_bytes())}}
    candidate_info = reference._load_candidate_release(plan)
    staged = reference._candidate_plist_bytes(active["plist"].read_bytes(), plan, candidate_info)
    diff = reference._staged_plist_diff(active["plist"].read_bytes(), staged, candidate_info)
    reference.STAGED_API_PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    reference.STAGED_API_PLIST_PATH.write_bytes(staged)
    _dump(reference.STAGED_API_PLIST_DIFF_PATH, diff)
    plan["target"]["staged_api_plist_sha256"] = _sha(staged)
    plan["target"]["staged_api_plist_diff_sha256"] = _sha(reference.STAGED_API_PLIST_DIFF_PATH.read_bytes())
    launcher = _SyntheticLauncher(reference, before_identity, candidate, analyses, extensions)
    monkeypatch.setattr(reference, "_launchctl_print", launcher.print_job)
    monkeypatch.setattr(reference, "_launchctl_action", launcher.action)
    monkeypatch.setattr(reference, "_http_get", launcher.get)
    monkeypatch.setattr(reference, "time", _SyntheticClock())
    return reference, active, candidate, plan, launcher


def _execute_native(reference, plan):
    with reference._locked() as lease:
        return reference._run_switch(plan, confirmation=reference.CONFIRM_SWITCH,
            expected_current_sha=plan["before"]["active_api_plist_sha256"],
            expected_staged_sha=plan["target"]["staged_api_plist_sha256"], lock_lease=lease)


def test_native_rejects_conflicting_staged_dual_release_identity_before_write(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="API_RELEASE_ACTIVE_PLIST_IDENTITY_CONFLICT"):
        _native_fixture(monkeypatch, tmp_path, duplicate_release_environment=True)
    active = tmp_path / "synthetic/LaunchAgents/com.lexi.v35.api-only.plist"
    assert integration.read_active_release(active)["release_id"] == "G"
    evidence = tmp_path / "historical-task/completion_20261008/workspace_failure"
    assert not (evidence / "staged/com.lexi.v35.api-only.r2.ready.plist").exists()
    assert not (evidence / "api_only_switch_runs").exists()
    assert (tmp_path / "synthetic/synthetic-state/sentinel").read_bytes() == b"NEVER_WRITE\n"


def test_native_switch_runs_real_owner_guard_and_records_candidate_readback(monkeypatch, tmp_path):
    reference, active, candidate, plan, launcher = _native_fixture(monkeypatch, tmp_path)
    state_before = (active["state"] / "sentinel").read_bytes()
    result = _execute_native(reference, plan)
    receipt = json.loads(Path(result["receipt_path"]).read_text())
    assert receipt["business_module"]["module_id"] == "alpha"
    assert receipt["business_module"]["generation"] == 1
    assert receipt["module_verification"]["active_pointer"] == "candidate"
    assert receipt["publisher_binding_status"] == "CANNOT_CONFIRM_CURRENT_MAC_BINDING"
    assert launcher.actions == ["bootout", "bootstrap"]
    assert integration.read_active_release(active["plist"])["app_root"] == str(candidate / "app")
    assert (active["state"] / "sentinel").read_bytes() == state_before


def test_native_rejects_owner_contract_drift_before_service_action(monkeypatch, tmp_path):
    reference, active, _candidate, plan, launcher = _native_fixture(monkeypatch, tmp_path)
    before = active["plist"].read_bytes()
    active["contract"].write_bytes(active["contract"].read_bytes() + b" ")
    with pytest.raises(ValueError, match="API_BUSINESS_OWNER_CONTRACT_SHA_MISMATCH"):
        _execute_native(reference, plan)
    assert launcher.actions == []
    assert launcher.loaded["V35_RELEASE_ID"] == "G"
    assert active["plist"].read_bytes() == before


def test_native_revalidates_after_bootout_before_atomic_replace(monkeypatch, tmp_path):
    reference, active, _candidate, plan, launcher = _native_fixture(monkeypatch, tmp_path)
    before = active["plist"].read_bytes()
    launcher.after_bootout = lambda: active["contract"].write_bytes(active["contract"].read_bytes() + b" ")
    with pytest.raises(ValueError, match="API_ONLY_SWITCH_FAILED_AND_ROLLED_BACK:API_BUSINESS_OWNER_CONTRACT_SHA_MISMATCH"):
        _execute_native(reference, plan)
    assert active["plist"].read_bytes() == before
    assert launcher.loaded["V35_RELEASE_ID"] == "G"
    assert launcher.actions == ["bootout", "bootstrap"]


@pytest.mark.parametrize("failure", ["before_replace", "after_replace", "health", "bootstrap_after_start"])
def test_native_switch_failure_recovers_immediate_preimage(monkeypatch, tmp_path, failure):
    reference, active, _candidate, plan, launcher = _native_fixture(monkeypatch, tmp_path)
    before = active["plist"].read_bytes()
    original_replace = os.replace
    injected = False

    def replace(source, target):
        nonlocal injected
        if Path(target) == active["plist"] and not injected:
            injected = True
            if failure == "before_replace":
                raise OSError("SYNTHETIC_REPLACE_PRE_WRITE_FAILURE")
            if failure == "after_replace":
                original_replace(source, target)
                raise OSError("SYNTHETIC_REPLACE_POST_WRITE_FAILURE")
        return original_replace(source, target)

    if failure in {"before_replace", "after_replace"}:
        monkeypatch.setattr(reference, "os", types.SimpleNamespace(**{
            **vars(os), "replace": replace,
        }))
    if failure == "health":
        launcher.candidate_health_failure = True
    if failure == "bootstrap_after_start":
        launcher.candidate_bootstrap_error = True
    with pytest.raises(ValueError, match="API_ONLY_SWITCH_FAILED_AND_ROLLED_BACK"):
        _execute_native(reference, plan)
    assert active["plist"].read_bytes() == before
    assert launcher.loaded["V35_RELEASE_ID"] == "G"
    assert launcher.loaded["state"] == "running"
    assert (active["state"] / "sentinel").read_bytes() == b"NEVER_WRITE\n"
    receipts = list((reference.EVIDENCE_ROOT / "api_only_switch_runs").glob("*/operation_receipt.json"))
    assert len(receipts) == 1
    assert json.loads(receipts[0].read_text())["status"] == "ROLLED_BACK_TO_PREIMAGE"


def test_native_nonrunning_candidate_reports_incomplete_recovery_honestly(monkeypatch, tmp_path):
    reference, active, candidate, plan, launcher = _native_fixture(monkeypatch, tmp_path)
    launcher.candidate_nonrunning = True
    with pytest.raises(ValueError, match="API_ONLY_SWITCH_FAILED_ROLLBACK_INCOMPLETE"):
        _execute_native(reference, plan)
    assert launcher.loaded["state"] == "waiting"
    assert reference._identity_from_plist(active["plist"].read_bytes())["V35_APP_ROOT"] == str(candidate / "app")
    receipts = list((reference.EVIDENCE_ROOT / "api_only_switch_runs").glob("*/operation_receipt.json"))
    assert json.loads(receipts[0].read_text())["status"] == "ROLLBACK_INCOMPLETE"
