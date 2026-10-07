"""Deterministic negative tests for the task-local guarded operators."""
from __future__ import annotations

import copy
import hashlib
import json
import plistlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import guarded_announcement_import as import_ops
import guarded_announcement_release as release_ops
import guarded_announcement_release_transaction as tx
import isolated_announcement_release_lifecycle as isolated


def _catalog_identity() -> tuple[dict, dict]:
    codes = [f"HK.{i:05d}" for i in range(524)]
    product = {
        "target_trade_date": import_ops.TARGET_DATE,
        "publication_date": "2026-10-06",
        "source_scope": "EASTMONEY_HK_DATE_CATALOG",
        "source_identity_basis": "EASTMONEY_116_H_SOURCE_REFERENCE",
        "run_id": import_ops.EXPECTED_CATALOG_RUN_ID,
        "sha256": import_ops.EXPECTED_CATALOG_PRODUCT_SHA256,
        "manager_consumer_row_count": 580,
        "manager_source_identity_count": 584,
        "manager_source_codes": codes,
        "manager_issuer_count": None,
        "connect_eligibility_status": "NOT_ASSESSED",
    }
    observed = {key: value for key, value in product.items() if key != "sha256"}
    observed["product_sha256"] = product["sha256"]
    return product, observed


def test_exact_catalog_identity_accepts_frozen_run_sha_and_source_identity() -> None:
    product, observed = _catalog_identity()
    import_ops.assert_exact_catalog_identity(observed, product, context="TEST")


def test_exact_catalog_identity_rejects_wrong_product_sha_with_same_counts() -> None:
    product, observed = _catalog_identity()
    wrong_sha = copy.deepcopy(observed)
    wrong_sha["product_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="TEST_SOURCE_IDENTITY_MISMATCH:sha256"):
        import_ops.assert_exact_catalog_identity(wrong_sha, product, context="TEST")


def test_staged_release_rejects_nested_path_in_either_direction(tmp_path) -> None:
    active = tmp_path / "release" / "app"
    nested_stage = active / "nested" / "app"
    nested_stage.parent.mkdir(parents=True)
    with pytest.raises(ValueError, match="STAGED_RELEASE_PATH_MUST_BE_DISJOINT_FROM_ACTIVE_RELEASE"):
        release_ops.assert_disjoint_release_paths(active, nested_stage)

    with pytest.raises(ValueError, match="STAGED_RELEASE_PATH_MUST_BE_DISJOINT_FROM_ACTIVE_RELEASE"):
        release_ops.assert_disjoint_release_paths(active / "nested" / "app", active)


def _fake_launchagent(root: Path, plist_path: Path) -> tuple[dict, dict]:
    manager = import_ops.STATE_ROOT
    data = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data")
    stage = root / "stage"
    manifest = root.parent / "release-manifest.json"
    env = {
        "V35_APP_ROOT": str(root), "V35_RELEASE_ID": root.parent.name,
        "V35_RELEASE_MANIFEST_PATH": str(manifest), "V35_RELEASE_MANIFEST_SHA256": "a" * 64,
        "V4_MANAGER_RESEARCH_STATE_ROOT": str(manager), "V35_DATA_ROOT": str(data),
        "V35_STAGE_CENTER_SELECTION_ROOT": str(stage), "PYTHONPATH": str(root / "upstreams") + ":" + str(root),
        "RESEARCH_ONLY": "1", "production_allowed": "false", "PRODUCTION_ALLOWED": "false",
        "buy_gate_updated": "false", "BUY_GATE_UPDATED": "false", "orders_sent": "false", "ORDERS_SENT": "false",
    }
    args = ["/usr/bin/env", *(f"{key}={value}" for key, value in env.items()), "/python", "-B", "-m",
            "apps.api.v35_api.run", "--host", "127.0.0.1", "--port", "8873"]
    payload = {"Label": import_ops.LAUNCHD_LABEL, "KeepAlive": True, "ProgramArguments": args,
               "WorkingDirectory": str(root)}
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_bytes(plistlib.dumps(payload))
    process = {"pid": 772, "command": "/python -B -m apps.api.v35_api.run --host 127.0.0.1 --port 8873",
               "cwd": str(root), "env": {key: env[key] for key in (
                   "V35_APP_ROOT", "V4_MANAGER_RESEARCH_STATE_ROOT", "V35_DATA_ROOT")}}
    owner = {"pid": 772, "service_target": f"gui/{__import__('os').getuid()}/{import_ops.LAUNCHD_LABEL}",
             "label": import_ops.LAUNCHD_LABEL, "plist_path": str(plist_path),
             "plist_sha256": hashlib.sha256(plist_path.read_bytes()).hexdigest(),
             "plist_payload": payload, "program_environment": env,
             "active_root": str(root), "process": process}
    return owner, process


def test_launchd_owner_resolves_live_pid_from_plist_and_rejects_pid_drift(tmp_path, monkeypatch) -> None:
    root = tmp_path / "current" / "app"
    root.mkdir(parents=True)
    plist_path = tmp_path / "api.plist"
    owner, process = _fake_launchagent(root, plist_path)
    monkeypatch.setattr(import_ops, "LAUNCHD_PLIST", plist_path)
    monkeypatch.setattr(import_ops, "process_identity", lambda pid: process if pid == 772 else {})

    def fake_run(argv, **kwargs):
        assert argv[:2] == ["launchctl", "print"]
        output = (f"{argv[2]} = {{\n path = {plist_path}\n state = running\n pid = 772\n}}\n")
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    monkeypatch.setattr(import_ops.subprocess, "run", fake_run)
    resolved = import_ops.launchd_owner_identity(root)
    assert resolved["pid"] == 772
    assert resolved["plist_sha256"] == owner["plist_sha256"]
    with pytest.raises(ValueError, match="LIVE_API_PID_DOES_NOT_MATCH_LAUNCHD_OWNER"):
        import_ops.launchd_owner_identity(root, 10987)


def test_release_overlay_requires_four_backend_and_both_frontend_sources(tmp_path) -> None:
    active = tmp_path / "active" / "app"
    staged = tmp_path / "candidate" / "app"
    paths = set(import_ops.SOURCE_RECORDS) | set(release_ops.FRONTEND_SOURCE_RECORDS)
    for relative in sorted(paths):
        for root, body in ((active, b"old"), (staged, b"new")):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
    (active / "apps/web/dist/index.html").parent.mkdir(parents=True, exist_ok=True)
    (active / "apps/web/dist/index.html").write_text("old", encoding="utf-8")
    (staged / "apps/web/dist/index.html").parent.mkdir(parents=True, exist_ok=True)
    (staged / "apps/web/dist/index.html").write_text("new", encoding="utf-8")
    delta = tx.assert_only_reviewed_overlay(active, staged)
    assert set(delta["changed_backend_files"]) == set(import_ops.SOURCE_RECORDS)
    assert set(delta["changed_frontend_typescript_files"]) == set(release_ops.FRONTEND_SOURCE_RECORDS)
    assert delta["changed_dist_files"] == ["apps/web/dist/index.html"]

    (staged / "apps/web/src/api/managerAnnouncementAnalysis.ts").write_bytes(b"old")
    with pytest.raises(ValueError, match="STAGED_RELEASE_REVIEWED_SOURCE_OVERLAY_INCOMPLETE"):
        tx.assert_only_reviewed_overlay(active, staged)


def test_launchd_plist_stage_preserves_existing_roots_and_safety_flags(tmp_path) -> None:
    old_root = tmp_path / "release-old" / "app"
    old_root.mkdir(parents=True)
    plist_path = tmp_path / "api.plist"
    owner, _ = _fake_launchagent(old_root, plist_path)
    new_root = tmp_path / "release-new" / "app"
    raw = tx._staged_launchagent_bytes(owner, new_root, new_root.parent / "release-manifest.json", "b" * 64)
    staged = plistlib.loads(raw)
    args = {item.split("=", 1)[0]: item.split("=", 1)[1]
            for item in staged["ProgramArguments"] if isinstance(item, str) and "=" in item}
    old_args = {item.split("=", 1)[0]: item.split("=", 1)[1]
            for item in owner["plist_payload"]["ProgramArguments"] if isinstance(item, str) and "=" in item}
    assert staged["WorkingDirectory"] == str(new_root)
    assert args["V35_APP_ROOT"] == str(new_root)
    assert args["V35_RELEASE_ID"] == "release-new"
    assert args["V35_RELEASE_MANIFEST_SHA256"] == "b" * 64
    for key in ("V35_DATA_ROOT", "V4_MANAGER_RESEARCH_STATE_ROOT", "V35_STAGE_CENTER_SELECTION_ROOT",
                "RESEARCH_ONLY", "production_allowed", "PRODUCTION_ALLOWED", "buy_gate_updated", "orders_sent"):
        assert args[key] == old_args[key]


def test_launchd_activate_then_rollback_switches_only_frozen_plist_bytes(tmp_path, monkeypatch) -> None:
    active = tmp_path / "prior" / "app"
    active.mkdir(parents=True)
    plist_path = tmp_path / "api.plist"
    owner, _ = _fake_launchagent(active, plist_path)
    prior = plist_path.read_bytes()
    staged = tx._staged_launchagent_bytes(owner, tmp_path / "candidate" / "app",
        tmp_path / "candidate" / "release-manifest.json", "c" * 64)
    commands = []
    monkeypatch.setattr(tx, "_launchctl", lambda args: commands.append(args) or {"argv": args, "returncode": 0})
    monkeypatch.setattr(tx, "wait_for_service_unloaded", lambda target: {
        "service_target": target, "status": "UNLOADED", "elapsed_seconds": 0.1})

    activate = tx.switch_launchagent(owner, owner["plist_sha256"], staged)
    assert hashlib.sha256(plist_path.read_bytes()).hexdigest() == activate["replacement_plist_sha256"]
    current_owner = {**owner, "plist_sha256": hashlib.sha256(staged).hexdigest()}
    rollback = tx.switch_launchagent(current_owner, current_owner["plist_sha256"], prior)
    assert plist_path.read_bytes() == prior
    assert [item[0] for item in commands] == ["bootout", "bootstrap", "bootout", "bootstrap"]
    assert rollback["replacement_plist_sha256"] == owner["plist_sha256"]

    with pytest.raises(ValueError, match="ACTIVE_LAUNCHAGENT_BYTES_CHANGED_BEFORE_SWITCH"):
        tx.switch_launchagent(owner, "0" * 64, staged)


def test_transaction_prepare_activate_rollback_lifecycle_with_mocked_launchd(tmp_path, monkeypatch) -> None:
    releases = tmp_path / "releases"
    active = releases / "prior-release" / "app"
    staged = releases / "announcement-daily-test" / "app"
    plist_path = tmp_path / "LaunchAgents" / "com.lexi.v35.api-only.plist"
    active.mkdir(parents=True)
    for relative in set(import_ops.SOURCE_RECORDS) | set(release_ops.FRONTEND_SOURCE_RECORDS):
        path = active / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"prior release bytes")
    (active / "apps/web/dist/assets").mkdir(parents=True)
    (active / "apps/web/dist/assets/main.js").write_bytes(b"prior dist")

    active_entries = release_ops.inventory_entries(active)
    dist_entries = release_ops.inventory_entries(active / "apps/web/dist")
    manifest = {
        "schema_version": "v4.release_candidate.v1",
        "candidate_status": "READY_FOR_INDEPENDENT_REVIEW", "activation_status": "NOT_ACTIVATED",
        "deployment_status": "NOT_DEPLOYED", "generated_at": "test",
        "candidate": {"root": str(active.parent), "app_root": str(active), "release_id": active.parent.name},
        "application_inventory": {"entry_count": len(active_entries),
            "aggregate_sha256": release_ops.inventory_digest(active_entries), "entries": active_entries,
            "symlink_entries": [], "missing_symlink_targets": []},
        "frontend_dist": {"entry_count": len(dist_entries),
            "aggregate_sha256": release_ops.inventory_digest(dist_entries), "entries": dist_entries,
            "source_relative_root": "apps/web/dist"},
        "research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    }
    manifest_path = active.parent / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    owner, _ = _fake_launchagent(active, plist_path)
    owner["program_environment"].update({"V35_RELEASE_MANIFEST_PATH": str(manifest_path),
        "V35_RELEASE_MANIFEST_SHA256": manifest_sha})
    payload = owner["plist_payload"]
    payload["ProgramArguments"] = [
        item if not item.startswith("V35_RELEASE_MANIFEST_PATH=") and not item.startswith("V35_RELEASE_MANIFEST_SHA256=")
        else ("V35_RELEASE_MANIFEST_PATH=" + str(manifest_path) if item.startswith("V35_RELEASE_MANIFEST_PATH=")
              else "V35_RELEASE_MANIFEST_SHA256=" + manifest_sha)
        for item in payload["ProgramArguments"]]
    plist_path.write_bytes(plistlib.dumps(payload))
    old_plist = plist_path.read_bytes()

    def resolve_owner(expected_root=None, expected_pid=None):
        current = plistlib.loads(plist_path.read_bytes())
        current_root = Path(current["WorkingDirectory"]).resolve()
        if expected_root is not None and current_root != Path(expected_root).resolve():
            raise ValueError("TEST_OWNER_ROOT_MISMATCH")
        args = current["ProgramArguments"]
        env = {item.split("=", 1)[0]: item.split("=", 1)[1]
               for item in args if isinstance(item, str) and "=" in item}
        pid = 772 if current_root == active.resolve() else 901
        if expected_pid is not None and expected_pid != pid:
            raise ValueError("TEST_OWNER_PID_MISMATCH")
        process = {"pid": pid, "command": "/python -B -m apps.api.v35_api.run --host 127.0.0.1 --port 8873",
                   "cwd": str(current_root), "env": env}
        return {"pid": pid, "service_target": f"gui/{__import__('os').getuid()}/{import_ops.LAUNCHD_LABEL}",
                "label": import_ops.LAUNCHD_LABEL, "plist_path": str(plist_path),
                "plist_sha256": hashlib.sha256(plist_path.read_bytes()).hexdigest(),
                "plist_payload": current, "program_environment": env,
                "active_root": str(current_root), "process": process}

    monkeypatch.setattr(tx, "RELEASES_ROOT", releases)
    monkeypatch.setattr(tx, "TRANSACTION_ROOT", tmp_path / "transactions")
    monkeypatch.setattr(tx, "approval_check", lambda _path: {"status": "REVIEWED_PASS", "review_id": "test"})
    monkeypatch.setattr(tx, "active_baseline_contract", lambda root, pid: {
        "process": resolve_owner(root, pid)["process"], "launchd_owner": resolve_owner(root, pid),
        "source_sha256": tx.LEGACY_SOURCE_SHA, "legacy_20260929": {"stock_count": 140, "selected_stock_count": 23},
        "target_20261007_preimport": {"expected_preimport_state": True},
    })
    monkeypatch.setattr(import_ops, "launchd_owner_identity", resolve_owner)
    monkeypatch.setattr(release_ops, "launchd_owner_identity", resolve_owner)
    real_release_hashes = import_ops.release_source_hashes
    monkeypatch.setattr(import_ops, "release_source_hashes", lambda root: (
        real_release_hashes(root) if Path(root).resolve() == staged.resolve() else tx.LEGACY_SOURCE_SHA))
    monkeypatch.setattr(import_ops, "legacy_readback", lambda: {"stock_count": 140, "selected_stock_count": 23})
    monkeypatch.setattr(import_ops, "target_analysis_baseline", lambda: {"expected_preimport_state": True})
    monkeypatch.setattr(tx, "api_preimport_contract", lambda: {"expected_preimport_state": True})
    launches = []
    monkeypatch.setattr(tx, "_launchctl", lambda args: launches.append(tuple(args)) or {"argv": args, "returncode": 0})
    monkeypatch.setattr(tx, "wait_for_service_unloaded", lambda target: {
        "service_target": target, "status": "UNLOADED", "elapsed_seconds": 0.1})

    plan = tx.prepare_release(active, staged, None, tmp_path / "approval.json")
    assert plan["status"] == "STAGED_RELEASE_VERIFIED_NOT_ACTIVATED"
    assert len(plan["overlay_delta"]["changed_reviewed_source_files"]) == 6
    assert plan["prior_launchagent_plist_sha256"] == hashlib.sha256(old_plist).hexdigest()
    assert tx.verify_transaction(active, staged, None)["status"] == "STAGED_RELEASE_VERIFIED_NOT_ACTIVATED"

    activated = tx.activate_release(active, staged, None, tmp_path / "approval.json", True)
    assert activated["status"] == "PASS_RELEASE_ACTIVE_AND_API_READBACK"
    assert plistlib.loads(plist_path.read_bytes())["WorkingDirectory"] == str(staged)

    rolled_back = tx.rollback_release(active, staged, None, tmp_path / "approval.json", True)
    assert rolled_back["status"] == "PASS_RELEASE_ROLLED_BACK_AND_API_READBACK"
    assert plist_path.read_bytes() == old_plist
    assert [command[0] for command in launches] == ["bootout", "bootstrap", "bootout", "bootstrap"]


def test_launchd_switch_waits_for_label_unload_before_replacing_plist(tmp_path, monkeypatch) -> None:
    root = tmp_path / "prior" / "app"
    root.mkdir(parents=True)
    plist_path = tmp_path / "LaunchAgents" / "api.plist"
    owner, _ = _fake_launchagent(root, plist_path)
    order = []
    monkeypatch.setattr(tx, "_launchctl", lambda args: order.append(args[0]) or {"argv": args, "returncode": 0})
    monkeypatch.setattr(tx, "wait_for_service_unloaded", lambda target: order.append("wait-unloaded") or {
        "service_target": target, "status": "UNLOADED", "elapsed_seconds": 5.1})
    monkeypatch.setattr(tx, "_atomic_replace_bytes", lambda path, raw: (order.append("replace"), path.write_bytes(raw)))

    result = tx.switch_launchagent(owner, owner["plist_sha256"], b"candidate plist bytes")

    assert order == ["bootout", "wait-unloaded", "replace", "bootstrap"]
    assert result["wait_until_unloaded"]["elapsed_seconds"] == 5.1
    assert plist_path.read_bytes() == b"candidate plist bytes"


def test_launchd_unload_timeout_never_replaces_plist_or_bootstraps(tmp_path, monkeypatch) -> None:
    root = tmp_path / "prior" / "app"
    root.mkdir(parents=True)
    plist_path = tmp_path / "LaunchAgents" / "api.plist"
    owner, _ = _fake_launchagent(root, plist_path)
    prior = plist_path.read_bytes()
    commands = []
    monkeypatch.setattr(tx, "_launchctl", lambda args: commands.append(args[0]) or {"argv": args, "returncode": 0})
    monkeypatch.setattr(tx, "wait_for_service_unloaded", lambda _target: (_ for _ in ()).throw(
        ValueError("LAUNCHD_SERVICE_UNLOAD_TIMEOUT")))
    monkeypatch.setattr(tx, "_atomic_replace_bytes", lambda *_args: (_ for _ in ()).throw(
        AssertionError("plist replacement must not happen after unload timeout")))

    with pytest.raises(ValueError, match="LAUNCHD_SERVICE_UNLOAD_TIMEOUT"):
        tx.switch_launchagent(owner, owner["plist_sha256"], b"candidate plist bytes")

    assert commands == ["bootout"]
    assert plist_path.read_bytes() == prior


def test_wait_for_launchd_label_until_print_reports_not_found(monkeypatch) -> None:
    responses = [
        SimpleNamespace(returncode=0, stdout="state = exited\npid = 772\n", stderr=""),
        SimpleNamespace(returncode=113, stdout="Bad request.\n", stderr='Could not find service "gui/501/com.lexi.v35.api-only" in domain for user: 501'),
    ]
    calls = []
    monkeypatch.setattr(tx.subprocess, "run", lambda argv, **_kwargs: calls.append(argv) or responses.pop(0))
    monkeypatch.setattr(tx.time, "sleep", lambda _seconds: None)

    result = tx.wait_for_service_unloaded("gui/501/com.lexi.v35.api-only", timeout_seconds=1, poll_seconds=0.001)

    assert result["status"] == "UNLOADED"
    assert result["last_probe"] == {"loaded": False, "state": "UNLOADED", "pid": None}
    assert len(calls) == 2
    assert all(call[:2] == ["launchctl", "print"] for call in calls)


def test_wait_for_launchd_label_timeout_keeps_transition_state(monkeypatch) -> None:
    now = [0.0]
    monkeypatch.setattr(tx, "_launchd_service_probe", lambda _target: {
        "loaded": True, "state": "SIGTERMed", "pid": 772})
    monkeypatch.setattr(tx.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(tx.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))

    with pytest.raises(ValueError, match="LAUNCHD_SERVICE_UNLOAD_TIMEOUT:gui/501/com.lexi.v35.api-only:state=SIGTERMed:pid=772"):
        tx.wait_for_service_unloaded("gui/501/com.lexi.v35.api-only", timeout_seconds=0.3, poll_seconds=0.1)


def test_new_release_transaction_requires_and_binds_failed_transaction_recovery(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(tx, "TASK_ROOT", tmp_path)
    canonical_recovery_path = tmp_path / "ROOT_ACTIVATION_FAILURE_RECOVERY_RECEIPT.json"
    monkeypatch.setattr(tx, "RECOVERY_RECEIPT_DEFAULT", canonical_recovery_path)
    transaction_root = tmp_path / "transactions"
    monkeypatch.setattr(tx, "TRANSACTION_ROOT", transaction_root)
    prior_root = transaction_root / "announcement-daily-test"
    prior_root.mkdir(parents=True)
    prior_plist = prior_root / "prior_launchagent.plist"
    prior_plist.write_bytes(b"prior launchagent bytes")
    old_staged_root = tmp_path / "release" / "announcement-daily-test" / "app"
    old_plan = {
        "status": "STAGED_RELEASE_VERIFIED_NOT_ACTIVATED",
        "candidate_source_aggregate_sha256": import_ops.EXPECTED_AGGREGATE,
        "active_release_root": str(tmp_path / "release" / "prior" / "app"),
        "staged_release_root": str(old_staged_root),
        "prior_launchagent_plist_sha256": hashlib.sha256(prior_plist.read_bytes()).hexdigest(),
    }
    old_plan_sha = hashlib.sha256(json.dumps(old_plan, sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode("utf-8")).hexdigest()
    old_plan["sha256"] = old_plan_sha
    (prior_root / "release_transaction.json").write_text(json.dumps(old_plan), encoding="utf-8")
    (prior_root / "activation_attempt.json").write_text(json.dumps({"one_attempt_only": True,
        "plan_sha256": old_plan_sha, "active_release_root": old_plan["active_release_root"],
        "staged_release_root": old_plan["staged_release_root"]}), encoding="utf-8")
    (prior_root / "activation_receipt.json").write_text(json.dumps({
        "attempt": str(prior_root / "activation_attempt.json"),
        "status": "ACTIVATION_INDETERMINATE_MANUAL_RECONCILIATION_REQUIRED",
        "error": "ValueError:Bootstrap failed: 5: Input/output error",
    }), encoding="utf-8")
    recovery_path = canonical_recovery_path
    recovery = {
        "status": "FAILED_CANDIDATE_BOOTSTRAP_PRIOR_OWNER_RESTORED",
        "plist_sha256": hashlib.sha256(prior_plist.read_bytes()).hexdigest(),
        "legacy": {"analysis_status": "VERIFIED", "source_status": "COMPLETE", "stock_count": 140,
            "selected_stock_count": 23, "safety": {"RESEARCH_ONLY": True, "production_allowed": False,
                "buy_gate_updated": False, "orders_sent": False}},
        "target": {"expected_preimport_state": True, "target_trade_date": "20261007",
            "publication_date": "2026-10-06", "analysis_status": "NOT_IMPORTED",
            "source_status": "NOT_RUN", "selection_status": "NOT_ASSESSED"},
    }
    recovery_path.write_text(json.dumps(recovery), encoding="utf-8")
    recovery_sha = hashlib.sha256(recovery_path.read_bytes()).hexdigest()
    monkeypatch.setattr(tx, "RECOVERY_RECEIPT_EXPECTED_SHA256", recovery_sha)
    staged_root = tmp_path / "release" / "announcement-daily-test-r2" / "app"

    with pytest.raises(ValueError, match="PRIOR_FAILED_TRANSACTION_RECONCILIATION_REQUIRED"):
        tx._reconciled_failure_lineage(staged_root, None, None)

    lineage = tx._reconciled_failure_lineage(staged_root, prior_root, recovery_path)
    assert lineage["superseded_transaction_root"] == str(prior_root.resolve())
    assert lineage["recovery_status"] == "FAILED_CANDIDATE_BOOTSTRAP_PRIOR_OWNER_RESTORED"
    assert tx.transaction_dir(staged_root) != prior_root
    assert prior_root.joinpath("activation_receipt.json").is_file()

    alternate_recovery_path = tmp_path / "same_claims_recovery.json"
    alternate_recovery_path.write_bytes(recovery_path.read_bytes())
    with pytest.raises(ValueError, match="RECOVERY_RECEIPT_PATH_NOT_CANONICAL"):
        tx._reconciled_failure_lineage(staged_root, prior_root, alternate_recovery_path)

    recovery["plist_sha256"] = "f" * 64
    recovery_path.write_text(json.dumps(recovery), encoding="utf-8")
    with pytest.raises(ValueError, match="RECOVERY_RECEIPT_SHA256_MISMATCH"):
        tx._reconciled_failure_lineage(staged_root, prior_root, recovery_path)


def test_isolated_lifecycle_environment_and_empty_state_contract(tmp_path, monkeypatch) -> None:
    app = tmp_path / "candidate" / "app"
    app.mkdir(parents=True)
    (app.parent / "release-manifest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("V4_MANAGER_RESEARCH_STATE_ROOT", "/shared/manager")
    monkeypatch.setenv("V35_STAGE_CENTER_SELECTION_ROOT", "/shared/stage")
    env = isolated.isolated_environment(app, tmp_path / "sandbox")
    assert env["V4_MANAGER_RESEARCH_STATE_ROOT"].startswith(str(tmp_path / "sandbox"))
    assert env["V35_STAGE_CENTER_SELECTION_ROOT"].startswith(str(tmp_path / "sandbox"))
    assert env["V35_APP_ROOT"] == str(app)
    assert env["RESEARCH_ONLY"] == "1"
    assert env["production_allowed"] == "false"

    body = {"target_trade_date": import_ops.TARGET_DATE,
            "publication_date": import_ops.API_PUBLICATION_DATE,
            "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
            "analysis": {"status": "NOT_IMPORTED", "stock_selection": {"status": "NOT_ASSESSED"}},
            "source_catalog": {"status": "NOT_RUN"}}
    contract = isolated.verify_isolated_response(body)
    assert contract["source_status"] == "NOT_RUN"
    assert contract["selection_status"] == "NOT_ASSESSED"
    body["orders_sent"] = True
    with pytest.raises(ValueError, match="ISOLATED_API_EMPTY_STATE_OR_SAFETY_CONTRACT_FAILED"):
        isolated.verify_isolated_response(body)

    body["orders_sent"] = False
    body["analysis"]["target_trade_date"] = "20261006"
    with pytest.raises(ValueError, match="ISOLATED_API_DATE_BINDING_MISMATCH:target_trade_date"):
        isolated.verify_isolated_response(body)


@pytest.mark.parametrize(("missing", "expected_error"), [
    ("target_trade_date", "ISOLATED_API_DATE_BINDING_MISMATCH:target_trade_date"),
    ("publication_date", "ISOLATED_API_DATE_BINDING_MISMATCH:publication_date"),
    ("both", "ISOLATED_API_DATE_BINDING_MISMATCH:target_trade_date"),
])
def test_isolated_lifecycle_requires_both_exact_api_dates(missing, expected_error) -> None:
    body = {"target_trade_date": import_ops.TARGET_DATE,
            "publication_date": import_ops.API_PUBLICATION_DATE,
            "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
            "analysis": {"status": "NOT_IMPORTED", "stock_selection": {"status": "NOT_ASSESSED"}},
            "source_catalog": {"status": "NOT_RUN"}}
    if missing == "both":
        body.pop("target_trade_date")
        body.pop("publication_date")
    else:
        body.pop(missing)
    with pytest.raises(ValueError, match=expected_error):
        isolated.verify_isolated_response(body)


def test_target_analysis_baseline_accepts_exact_api_date_formats(monkeypatch) -> None:
    body = {
        "target_trade_date": import_ops.API_TARGET_DATE,
        "publication_date": import_ops.API_PUBLICATION_DATE,
        "analysis": {"status": "NOT_IMPORTED", "stock_selection": {
            "status": "NOT_ASSESSED", "stock_count": None, "selected_stock_count": None}},
        "source_catalog": {"status": "NOT_RUN", "catalog_run_id": None, "catalog_product_sha256": None},
    }
    monkeypatch.setattr(import_ops, "api_get", lambda _path: (200, b"{}", body))
    result = import_ops.target_analysis_baseline()
    assert result["date_binding_verified"] is True
    assert result["expected_preimport_state"] is True
    assert result["target_trade_date"] == "20261007"
    assert result["publication_date"] == "2026-10-06"


@pytest.mark.parametrize("missing", ["target_trade_date", "publication_date", "both"])
def test_target_analysis_baseline_rejects_missing_api_dates(monkeypatch, missing) -> None:
    body = {
        "target_trade_date": import_ops.API_TARGET_DATE,
        "publication_date": import_ops.API_PUBLICATION_DATE,
        "analysis": {"status": "NOT_IMPORTED", "stock_selection": {
            "status": "NOT_ASSESSED", "stock_count": None, "selected_stock_count": None}},
        "source_catalog": {"status": "NOT_RUN", "catalog_run_id": None, "catalog_product_sha256": None},
    }
    if missing == "both":
        body.pop("target_trade_date")
        body.pop("publication_date")
    else:
        body.pop(missing)
    monkeypatch.setattr(import_ops, "api_get", lambda _path: (200, b"{}", body))
    result = import_ops.target_analysis_baseline()
    assert result["date_binding_verified"] is False
    assert result["expected_preimport_state"] is False


@pytest.mark.parametrize(("key", "wrong_value"), [
    ("target_trade_date", "2026-10-07"),
    ("publication_date", "20261006"),
])
def test_target_analysis_baseline_rejects_non_contract_date_formats(monkeypatch, key, wrong_value) -> None:
    body = {
        "target_trade_date": import_ops.API_TARGET_DATE,
        "publication_date": import_ops.API_PUBLICATION_DATE,
        "analysis": {"status": "NOT_IMPORTED", "stock_selection": {
            "status": "NOT_ASSESSED", "stock_count": None, "selected_stock_count": None}},
        "source_catalog": {"status": "NOT_RUN", "catalog_run_id": None, "catalog_product_sha256": None},
    }
    body[key] = wrong_value
    monkeypatch.setattr(import_ops, "api_get", lambda _path: (200, b"{}", body))
    result = import_ops.target_analysis_baseline()
    assert result["date_binding_verified"] is False
    assert result["expected_preimport_state"] is False


def test_isolated_lifecycle_refuses_shared_port(tmp_path) -> None:
    with pytest.raises(ValueError, match="ISOLATED_PORT_OUT_OF_ALLOWED_RANGE"):
        isolated.assert_port_free(8873)


def test_isolated_lifecycle_requires_reviewed_staged_release_preflight(tmp_path, monkeypatch) -> None:
    active = tmp_path / "active" / "app"
    staged = tmp_path / "staged" / "app"
    active.mkdir(parents=True)
    staged.mkdir(parents=True)
    monkeypatch.setattr(isolated, "TASK_ROOT", tmp_path / "task")
    monkeypatch.setattr(isolated, "assert_port_free", lambda _port: None)
    preflight = {"status": "STAGED_RELEASE_VERIFIED_NOT_ACTIVATED", "backend": "accepted"}
    calls = []

    def verify_staged(actual_active, actual_staged):
        calls.append(("verify_staged", actual_active, actual_staged))
        return preflight

    owner = {"pid": 1137, "active_root": str(active.resolve()), "plist_sha256": "a" * 64}
    monkeypatch.setattr(isolated.release_ops, "verify_staged", verify_staged)
    monkeypatch.setattr(isolated.import_ops, "launchd_owner_identity", lambda _root: owner)

    def run_child(app_root, sandbox, port):
        calls.append(("run_child", app_root, sandbox, port))
        return {"status": "PASS_ISOLATED_API_READBACK", "child": SimpleNamespace(pid=1, poll=lambda: 0)}

    monkeypatch.setattr(isolated, "run_child", run_child)
    monkeypatch.setattr(isolated, "stop_child", lambda child: {"pid": child.pid, "stopped": True})
    receipt = isolated.run_lifecycle(active, staged, 18873, True)
    assert calls[0] == ("verify_staged", active.resolve(), staged.resolve())
    assert len([call for call in calls if call[0] == "run_child"]) == 3
    assert receipt["staged_release_preflight"] == preflight
    assert receipt["active_8873_before"] == receipt["active_8873_after"]
