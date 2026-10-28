from __future__ import annotations

import difflib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib

import pytest

from ops import api_release_integration as integration
from ops.prepare_api_only_cutover import render_cutover, sha256_file


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_active_release(
    root: Path, api_plist: Path, *, release_id: str = "active-release",
    files: dict[str, bytes] | None = None,
) -> dict[str, Path | str]:
    release_root = root / release_id
    app_root = release_root / "app"
    app_root.mkdir(parents=True)
    for relative, raw in (files or {
        "apps/api/v35_api/app.py": b"VALUE = 1\n",
        "stable-module.py": b"STABLE = True\n",
    }).items():
        target = app_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    entries = integration.inventory_tree(app_root)
    manifest = {
        "schema_version": "v4.release_candidate.v1",
        "activation_status": "NOT_ACTIVATED",
        "candidate": {
            "root": str(release_root),
            "app_root": str(app_root),
            "release_id": release_id,
        },
        "application_inventory": {
            "entry_count": len(entries),
            "aggregate_sha256": integration.inventory_digest(entries),
            "entries": entries,
        },
    }
    manifest_path = release_root / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    manifest_sha = sha256_file(manifest_path)
    manager_root = root / "current-manager"
    manager_root.mkdir(exist_ok=True)
    api_plist.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": "com.lexi.v35.api-only",
        "ProgramArguments": [
            "/usr/bin/env",
            "RESEARCH_ONLY=1",
            "production_allowed=false",
            "PRODUCTION_ALLOWED=false",
            "buy_gate_updated=false",
            "BUY_GATE_UPDATED=false",
            "orders_sent=false",
            "ORDERS_SENT=false",
            f"V35_APP_ROOT={app_root}",
            f"V35_RELEASE_ID={release_id}",
            f"V35_RELEASE_MANIFEST_PATH={manifest_path}",
            f"V35_RELEASE_MANIFEST_SHA256={manifest_sha}",
            f"V4_MANAGER_RESEARCH_STATE_ROOT={manager_root}",
            f"PYTHONPATH={app_root / 'upstreams'}:{app_root}",
            "/usr/bin/python3",
            "-B",
            "-m",
            "apps.api.v35_api.run",
        ],
        "WorkingDirectory": str(app_root),
    }
    api_plist.write_bytes(plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True))
    return {
        "release_root": release_root,
        "app_root": app_root,
        "manifest_path": manifest_path,
        "manifest_sha256": manifest_sha,
        "api_plist": api_plist,
        "manager_root": manager_root,
    }


def _delta_receipt(
    active: dict[str, Path | str], source_root: Path, *,
    relative: str = "apps/api/v35_api/app.py", before_override: str | None = None,
) -> Path:
    base_identity = integration.read_active_release(Path(str(active["api_plist"])))
    base_path = Path(str(active["app_root"])) / relative
    source_path = source_root / relative
    before = base_path.read_bytes()
    after = source_path.read_bytes()
    diff_lines = list(difflib.unified_diff(
        before.decode("utf-8").splitlines(), after.decode("utf-8").splitlines(),
        fromfile="before", tofile="after", n=0, lineterm="",
    ))
    diff_raw = ("\n".join(diff_lines) + ("\n" if diff_lines else "")).encode("utf-8")
    entry = {
        "path": relative,
        "before_sha256": before_override or _sha(before),
        "after_sha256": _sha(after),
        "unified_diff_sha256": _sha(diff_raw),
        "unified_diff_hunk_count": sum(line.startswith("@@") for line in diff_lines),
    }
    value = {
        "schema_version": integration.DELTA_SCHEMA_VERSION,
        "base": integration._base_binding(base_identity),
        "entries": [entry],
    }
    path = source_root.parent / "delta-receipt.json"
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def _integrated_candidate(
    tmp_path: Path, *, wrong_before: bool = False,
) -> tuple[dict[str, Path | str], Path, dict[str, object]]:
    active = _write_active_release(
        tmp_path,
        tmp_path / "LaunchAgents" / "com.lexi.v35.api-only.plist",
        files={
            "apps/api/v35_api/app.py": b"VALUE = 1\n",
            "stable-module.py": b"STABLE = True\n",
        },
    )
    source_root = tmp_path / "source"
    changed = source_root / "apps/api/v35_api/app.py"
    changed.parent.mkdir(parents=True)
    changed.write_bytes(b"VALUE = 2\n")
    receipt = _delta_receipt(
        active, source_root,
        before_override=("f" * 64 if wrong_before else None),
    )
    candidate_root = tmp_path / "candidate"
    candidate_root.mkdir()
    details = integration.build_integrated_app(
        active_api_plist_path=Path(str(active["api_plist"])),
        source_root=source_root,
        candidate_root=candidate_root,
        delta_receipt_path=receipt,
    )
    entries = integration.inventory_tree(candidate_root / "app")
    manifest = {
        "schema_version": "v4.release_candidate.v1",
        "activation_status": "NOT_ACTIVATED",
        "candidate": {
            "root": str(candidate_root),
            "app_root": str(candidate_root / "app"),
            "release_id": candidate_root.name,
        },
        "application_inventory": {
            "entry_count": len(entries),
            "aggregate_sha256": integration.inventory_digest(entries),
            "entries": entries,
        },
        "api_integration": details,
    }
    manifest_path = candidate_root / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return active, candidate_root, manifest


def test_prepare_refuses_legacy_api_candidate_without_integration_lineage(tmp_path: Path) -> None:
    active = _write_active_release(
        tmp_path,
        tmp_path / "LaunchAgents" / "com.lexi.v35.api-only.plist",
    )
    candidate_root = tmp_path / "legacy-candidate"
    (candidate_root / "app").mkdir(parents=True)
    candidate_manifest = candidate_root / "release-manifest.json"
    candidate_manifest.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="API_RELEASE_INTEGRATION"):
        render_cutover(
            source_plist_path=Path(str(active["api_plist"])),
            candidate_root=candidate_root,
            release_id="legacy-candidate",
            manifest_path=candidate_manifest,
            manifest_sha256=sha256_file(candidate_manifest),
            current_manager_state_root=Path(str(active["manager_root"])),
            source_root=tmp_path / "source",
        )

    assert not (candidate_root / "config" / "com.lexi.v35.api-only.plist").exists()


def test_candidate_is_active_base_plus_exact_delta_and_prepare_pins_it(tmp_path: Path) -> None:
    active, candidate_root, _manifest = _integrated_candidate(tmp_path)
    candidate_manifest = candidate_root / "release-manifest.json"
    before = Path(str(active["api_plist"])).read_bytes()
    receipt = integration.verify_api_release_candidate(
        candidate_root=candidate_root,
        active_api_plist_path=Path(str(active["api_plist"])),
        expected_manifest_sha256=sha256_file(candidate_manifest),
    )
    assert receipt["status"] == "PASS"
    assert receipt["delta_paths"] == ["apps/api/v35_api/app.py"]
    assert receipt["non_delta_entry_count"] == 1
    plan = render_cutover(
        source_plist_path=Path(str(active["api_plist"])),
        candidate_root=candidate_root,
        release_id=candidate_root.name,
        manifest_path=candidate_manifest,
        manifest_sha256=sha256_file(candidate_manifest),
        current_manager_state_root=Path(str(active["manager_root"])),
        source_root=tmp_path / "source",
    )
    assert plan["api_release_integration"]["preflight_revalidation_required_under_shared_lock"] is True
    assert Path(str(active["api_plist"])).read_bytes() == before


def test_wrong_before_sha_and_active_base_drift_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "wrong-before"
    root.mkdir()
    active = _write_active_release(root, root / "LaunchAgents" / "com.lexi.v35.api-only.plist")
    source_root = root / "source"
    source = source_root / "apps/api/v35_api/app.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"VALUE = 2\n")
    receipt_path = _delta_receipt(active, source_root, before_override="f" * 64)
    candidate_root = root / "candidate"
    candidate_root.mkdir()
    with pytest.raises(ValueError, match="API_RELEASE_DELTA_BEFORE_SHA_MISMATCH"):
        integration.build_integrated_app(
            active_api_plist_path=Path(str(active["api_plist"])),
            source_root=source_root,
            candidate_root=candidate_root,
            delta_receipt_path=receipt_path,
        )

    good_root = tmp_path / "base-drift"
    good_root.mkdir()
    good_active, candidate_root, _manifest = _integrated_candidate(good_root)
    _write_active_release(
        good_root,
        Path(str(good_active["api_plist"])),
        release_id="replacement-release",
        files={"apps/api/v35_api/app.py": b"VALUE = 9\n", "stable-module.py": b"STABLE = True\n"},
    )
    with pytest.raises(ValueError, match="API_RELEASE_INTEGRATION_ACTIVE_BASE_CHANGED"):
        integration.verify_api_release_candidate(
            candidate_root=candidate_root,
            active_api_plist_path=Path(str(good_active["api_plist"])),
        )


def test_active_readback_ignores_and_reports_only_regular_cpython314_cache_files(tmp_path: Path) -> None:
    active = _write_active_release(
        tmp_path,
        tmp_path / "LaunchAgents" / "com.lexi.v35.api-only.plist",
    )
    cache_path = Path(str(active["app_root"])) / "__pycache__" / "stable_module.cpython-314.pyc"
    cache_path.parent.mkdir()
    cache_bytes = b"generated-bytecode-fixture"
    cache_path.write_bytes(cache_bytes)

    identity = integration.read_active_release(Path(str(active["api_plist"])), role="gateway")

    assert identity["application_inventory_entry_count"] == 2
    assert identity["generated_bytecode_cache_exclusions"] == [{
        "path": "__pycache__/stable_module.cpython-314.pyc",
        "kind": "generated_python_bytecode_cache",
        "sha256": _sha(cache_bytes),
        "mode": f"{cache_path.stat().st_mode & 0o7777:04o}",
        "size": len(cache_bytes),
    }]
    assert identity["generated_bytecode_cache_exclusion_sha256"] == integration.inventory_digest(
        identity["generated_bytecode_cache_exclusions"]
    )


@pytest.mark.parametrize(
    "relative",
    [
        "stable-module.py",
        "__pycache__/unexpected.py",
        "__pycache__/settings.toml",
        "__pycache__/module.cpython-313.pyc",
    ],
)
def test_active_readback_rejects_source_drift_and_unrecognized_cache_files(
    tmp_path: Path, relative: str
) -> None:
    active = _write_active_release(
        tmp_path,
        tmp_path / "LaunchAgents" / "com.lexi.v35.api-only.plist",
    )
    target = Path(str(active["app_root"])) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"changed-after-manifest\n")

    with pytest.raises(ValueError, match="API_RELEASE_ACTIVE_APPLICATION_INVENTORY_DRIFT"):
        integration.read_active_release(Path(str(active["api_plist"])), role="gateway")


def test_active_readback_does_not_ignore_symlink_named_like_generated_bytecode(tmp_path: Path) -> None:
    active = _write_active_release(
        tmp_path,
        tmp_path / "LaunchAgents" / "com.lexi.v35.api-only.plist",
    )
    app_root = Path(str(active["app_root"]))
    cache_path = app_root / "__pycache__" / "stable_module.cpython-314.pyc"
    cache_path.parent.mkdir()
    cache_path.symlink_to(app_root / "stable-module.py")

    with pytest.raises(ValueError, match="API_RELEASE_ACTIVE_APPLICATION_INVENTORY_DRIFT"):
        integration.read_active_release(Path(str(active["api_plist"])), role="gateway")


@pytest.mark.parametrize("damage", ["unlisted_change", "delete_file"])
def test_candidate_rejects_unlisted_changes_and_deletions(tmp_path: Path, damage: str) -> None:
    active, candidate_root, manifest = _integrated_candidate(tmp_path)
    app_root = candidate_root / "app"
    if damage == "unlisted_change":
        (app_root / "stable-module.py").write_bytes(b"STABLE = False\n")
    else:
        (app_root / "stable-module.py").unlink()
    entries = integration.inventory_tree(app_root)
    manifest["application_inventory"] = {
        "entry_count": len(entries),
        "aggregate_sha256": integration.inventory_digest(entries),
        "entries": entries,
    }
    (candidate_root / "release-manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    expected = "API_RELEASE_INTEGRATION_UNLISTED_FILE_CHANGED" if damage == "unlisted_change" else "API_RELEASE_INTEGRATION_FILE_REMOVED"
    with pytest.raises(ValueError, match=expected):
        integration.verify_api_release_candidate(
            candidate_root=candidate_root,
            active_api_plist_path=Path(str(active["api_plist"])),
        )


def test_shared_lock_is_required_and_blocks_a_second_publisher(tmp_path: Path) -> None:
    active, candidate_root, _manifest = _integrated_candidate(tmp_path)
    api_plist = Path(str(active["api_plist"]))
    with pytest.raises(ValueError, match="API_RELEASE_SHARED_LOCK_REQUIRED"):
        integration.verify_api_release_candidate(
            candidate_root=candidate_root,
            active_api_plist_path=api_plist,
            require_shared_lock=True,
        )

    with integration.shared_api_release_lock(api_plist, timeout_seconds=0.2) as lease:
        verified = integration.verify_api_release_candidate(
            candidate_root=candidate_root,
            active_api_plist_path=api_plist,
            lock_lease=lease,
            require_shared_lock=True,
        )
        assert verified["status"] == "PASS"
        with pytest.raises(ValueError, match="API_RELEASE_SHARED_LOCK_BUSY"):
            with integration.shared_api_release_lock(api_plist, timeout_seconds=0.05):
                pass


def test_announcement_cutover_guard_holds_submission_gate_and_scans_all_dates(tmp_path: Path) -> None:
    root = tmp_path / "workbench"
    (root / "attempts").mkdir(parents=True)
    (root / "announcement_flash" / "queue").mkdir(parents=True)
    queue_state = {"schema": "v4.announcement-engine-queue/v1", "jobs": {}}
    (root / "announcement_flash" / "queue" / "queue-state.json").write_text(
        json.dumps(queue_state), encoding="utf-8")

    with integration.announcement_flash_cutover_guard(root, timeout_seconds=0.2) as receipt:
        assert receipt == {"schema": integration.ANNOUNCEMENT_CUTOVER_GUARD_SCHEMA,
                           "status": "PASS", "active_attempts": [],
                           "running_queue_items": [], "all_target_dates_checked": True}

    (root / "attempts" / "old-date.json").write_text(json.dumps({
        "job_id": "a" * 32, "state": "RUNNING",
        "context": {"target_date": "20261015",
                    "scope_refs": {"capture_operation": "ANNOUNCEMENT_FLASH_RESUME"}},
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="API_RELEASE_ANNOUNCEMENT_ACTIVITY_BUSY"):
        with integration.announcement_flash_cutover_guard(root, timeout_seconds=0.2):
            pass


def test_announcement_cutover_guard_scans_large_unrelated_terminal_attempt(tmp_path: Path) -> None:
    root = tmp_path / "workbench"
    attempts = root / "attempts"
    attempts.mkdir(parents=True)
    projection = [{"symbol": f"US{i:04d}", "name": "x" * 6600} for i in range(1003)]
    record = {
        "job_id": "d" * 32,
        "state": "PARTIAL",
        "step": "DONE",
        "retryable": False,
        "context": {
            "target_date": "20261020",
            "scope_refs": {
                "capture_operation": None,
                "requested_lanes": ["ANNOUNCEMENT", "US_MAPPING"],
                "US_MAPPING": {"full_overlay_projection": projection},
            },
            "owner_bindings": {"us_mapping": {"full_overlay_projection": projection}},
        },
    }
    raw = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert len(raw) > 8 * 1024 * 1024
    (attempts / f"{record['job_id']}.json").write_bytes(raw)

    with integration.announcement_flash_cutover_guard(root, timeout_seconds=0.2) as receipt:
        assert receipt["status"] == "PASS"
        assert receipt["active_attempts"] == []
        assert receipt["all_target_dates_checked"] is True


def test_announcement_cutover_guard_still_blocks_active_flash_capture(tmp_path: Path) -> None:
    root = tmp_path / "workbench"
    attempts = root / "attempts"
    attempts.mkdir(parents=True)
    (attempts / "active.json").write_text(json.dumps({
        "job_id": "e" * 32,
        "state": "RUNNING",
        "context": {
            "target_date": "20261016",
            "scope_refs": {"capture_operation": "ANNOUNCEMENT_FLASH_RESUME"},
        },
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="API_RELEASE_ANNOUNCEMENT_ACTIVITY_BUSY"):
        with integration.announcement_flash_cutover_guard(root, timeout_seconds=0.2):
            pass


def test_announcement_cutover_guard_fails_closed_on_attempt_over_store_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infrastructure.owned_io import OwnedIOError, SafeRoot

    root = tmp_path / "workbench"
    attempts = root / "attempts"
    attempts.mkdir(parents=True)
    (attempts / "oversized.json").write_text("{}", encoding="utf-8")
    original_read_bytes = SafeRoot.read_bytes

    def reject_over_limit(self, relative: str, *, max_bytes: int = 64 * 1024 * 1024) -> bytes:
        if relative == "attempts/oversized.json":
            assert max_bytes == 64 * 1024 * 1024
            raise OwnedIOError("OWNED_FILE_TOO_LARGE")
        return original_read_bytes(self, relative, max_bytes=max_bytes)

    monkeypatch.setattr(SafeRoot, "read_bytes", reject_over_limit)
    with pytest.raises(ValueError, match="API_RELEASE_ANNOUNCEMENT_ATTEMPT_READ_FAILED"):
        with integration.announcement_flash_cutover_guard(root, timeout_seconds=0.2):
            pass


def test_announcement_cutover_guard_fails_closed_on_invalid_attempt_json(tmp_path: Path) -> None:
    root = tmp_path / "workbench"
    attempts = root / "attempts"
    attempts.mkdir(parents=True)
    (attempts / "invalid.json").write_bytes(b"{not-json")

    with pytest.raises(ValueError, match="API_RELEASE_ANNOUNCEMENT_ATTEMPT_READ_FAILED"):
        with integration.announcement_flash_cutover_guard(root, timeout_seconds=0.2):
            pass


def test_announcement_cutover_guard_rejects_any_running_queue_date(tmp_path: Path) -> None:
    root = tmp_path / "workbench"
    (root / "attempts").mkdir(parents=True)
    queue_root = root / "announcement_flash" / "queue"
    queue_root.mkdir(parents=True)
    (queue_root / "queue-state.json").write_text(json.dumps({
        "schema": "v4.announcement-engine-queue/v1",
        "jobs": {"c" * 64: {"queue_id": "v4-manager-flash-incremental", "status": "RUNNING",
                              "identity": {"date": "2026-10-12", "article_id": "NEWS:OLD"}}},
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="API_RELEASE_ANNOUNCEMENT_ACTIVITY_BUSY"):
        with integration.announcement_flash_cutover_guard(root, timeout_seconds=0.2):
            pass


def _write_frozen_cutover_orphan(root: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    source_job_id = "a" * 32
    idempotency_key = "b" * 64
    target_date = "20261016"
    model_id = "qwen3_8_flash_next"
    source_input = json.dumps({
        "schema": "v4.manager_workbench.announcement_flash_input.v1",
        "job_id": source_job_id,
        "target_date": target_date,
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    source_input_sha = _sha(source_input)
    payload = {
        "date": "2026-10-14", "market": "HK", "article_id": "EASTMONEY:TEST",
        "source_sha256": "1" * 64, "body_sha256": "2" * 64, "prompt_sha256": "3" * 64,
        "model_id": model_id, "configuration_sha256": "4" * 64, "rules": "test-rules",
        "role": "announcement_reader_part", "stage": "v4_manager_announcement_flash_long_body_part_v1",
    }
    payload_raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload_sha = _sha(payload_raw)
    expected = {
        "source_job_id": source_job_id,
        "source_input_sha256": source_input_sha,
        "target_date": target_date,
        "idempotency_key": idempotency_key,
        "payload_sha256": payload_sha,
        "model_id": model_id,
    }
    monkeypatch.setattr(integration, "ANNOUNCEMENT_CUTOVER_FROZEN_ORPHAN", expected)

    attempts_root = root / "attempts"
    queue_root = root / "announcement_flash" / "queue"
    source_root = root / "announcement_flash" / "jobs" / source_job_id
    payload_path = queue_root / "jobs" / idempotency_key / "input.json"
    lock_root = queue_root / "locks"
    for path in (attempts_root, source_root, payload_path.parent, lock_root):
        path.mkdir(parents=True, exist_ok=True)
    (source_root / "input.json").write_bytes(source_input)
    (attempts_root / f"{source_job_id}.json").write_text(json.dumps({
        "job_id": source_job_id,
        "state": "INTERRUPTED",
        "context": {
            "target_date": target_date,
            "scope_refs": {"capture_operation": "ANNOUNCEMENT_FLASH_INCREMENTAL"},
        },
    }), encoding="utf-8")
    payload_path.write_bytes(payload_raw)
    model_lock = lock_root / ("model-" + _sha(model_id.encode("utf-8")) + ".lock")
    model_lock.write_bytes(b"")
    identity = dict(payload)
    queue_item = {
        "idempotency_key": idempotency_key,
        "queue_id": "v4-manager-flash-incremental",
        "status": "RUNNING",
        "attempt_count": 1,
        "attempts": [{
            "number": 1,
            "status": "RUNNING",
            "raw_path": None,
            "raw_sha256": None,
            "raw_length_bytes": None,
            "validated_path": None,
            "validated_sha256": None,
        }],
        "model_id": model_id,
        "input_path": f"jobs/{idempotency_key}/input.json",
        "payload_sha256": payload_sha,
        "validated_path": None,
        "validated_sha256": None,
        "identity": identity,
    }
    (queue_root / "queue-state.json").write_text(json.dumps({
        "schema": "v4.announcement-engine-queue/v1",
        "jobs": {idempotency_key: queue_item},
    }), encoding="utf-8")
    return {
        "source_job_id": source_job_id,
        "idempotency_key": idempotency_key,
        "payload_sha256": payload_sha,
        "model_lock": model_lock,
        "expected": expected,
    }


def test_announcement_cutover_guard_allows_only_bound_ownerless_orphan_and_holds_model_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workbench"
    bound = _write_frozen_cutover_orphan(root, monkeypatch)
    with integration.announcement_flash_cutover_guard(
        root,
        timeout_seconds=0.2,
        allow_orphan_source_job_id=bound["source_job_id"],
        allow_orphan_idempotency_key=bound["idempotency_key"],
        allow_orphan_payload_sha256=bound["payload_sha256"],
    ) as receipt:
        assert receipt["status"] == "PASS"
        assert receipt["allowed_running_orphan"] == {
            "source_job_id": bound["source_job_id"],
            "target_date": "20261016",
            "idempotency_key": bound["idempotency_key"],
            "payload_sha256": bound["payload_sha256"],
            "owner_clear": True,
            "model_lock_held": True,
            "source_result_absent": True,
            "validated_result_absent": True,
        }
        fd = os.open(bound["model_lock"], os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)

    fd = os.open(bound["model_lock"], os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def test_announcement_cutover_guard_orphan_exception_rechecks_result_and_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workbench"
    bound = _write_frozen_cutover_orphan(root, monkeypatch)
    queue_path = root / "announcement_flash" / "queue" / "queue-state.json"
    queue_state = json.loads(queue_path.read_text(encoding="utf-8"))
    item = queue_state["jobs"][bound["idempotency_key"]]
    item["owner_pid"] = 12345
    queue_path.write_text(json.dumps(queue_state), encoding="utf-8")
    with pytest.raises(ValueError, match="API_RELEASE_ANNOUNCEMENT_ORPHAN_OWNER_PRESENT"):
        with integration.announcement_flash_cutover_guard(
            root,
            timeout_seconds=0.2,
            allow_orphan_source_job_id=bound["source_job_id"],
            allow_orphan_idempotency_key=bound["idempotency_key"],
            allow_orphan_payload_sha256=bound["payload_sha256"],
        ):
            pass

    item.pop("owner_pid")
    item["attempts"][0]["raw_path"] = "jobs/result.json"
    item["attempts"][0]["raw_sha256"] = "5" * 64
    queue_path.write_text(json.dumps(queue_state), encoding="utf-8")
    with pytest.raises(ValueError, match="API_RELEASE_ANNOUNCEMENT_ORPHAN_RESULT_PRESENT"):
        with integration.announcement_flash_cutover_guard(
            root,
            timeout_seconds=0.2,
            allow_orphan_source_job_id=bound["source_job_id"],
            allow_orphan_idempotency_key=bound["idempotency_key"],
            allow_orphan_payload_sha256=bound["payload_sha256"],
        ):
            pass

    item["attempts"][0]["raw_path"] = None
    item["attempts"][0]["raw_sha256"] = None
    queue_path.write_text(json.dumps(queue_state), encoding="utf-8")
    source_root = root / "announcement_flash" / "jobs" / bound["source_job_id"]
    (source_root / "result.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="API_RELEASE_ANNOUNCEMENT_ORPHAN_SOURCE_RESULT_PRESENT"):
        with integration.announcement_flash_cutover_guard(
            root,
            timeout_seconds=0.2,
            allow_orphan_source_job_id=bound["source_job_id"],
            allow_orphan_idempotency_key=bound["idempotency_key"],
            allow_orphan_payload_sha256=bound["payload_sha256"],
        ):
            pass


def test_announcement_cutover_guard_rejects_modified_orphan_binding_and_cli_help(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "workbench"
    bound = _write_frozen_cutover_orphan(root, monkeypatch)
    with pytest.raises(ValueError, match="API_RELEASE_ANNOUNCEMENT_ORPHAN_BINDING_INVALID"):
        with integration.announcement_flash_cutover_guard(
            root,
            timeout_seconds=0.2,
            allow_orphan_source_job_id=bound["source_job_id"],
            allow_orphan_idempotency_key="c" * 64,
            allow_orphan_payload_sha256=bound["payload_sha256"],
        ):
            pass
    with pytest.raises(SystemExit) as raised:
        integration.main(["hold-announcement-cutover", "--help"])
    assert raised.value.code == 0
    assert "--allow-orphan-payload-sha256" in capsys.readouterr().out


def test_announcement_cutover_orphan_exception_still_blocks_busy_model_lock_and_extra_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workbench"
    bound = _write_frozen_cutover_orphan(root, monkeypatch)
    fd = os.open(bound["model_lock"], os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="API_RELEASE_ANNOUNCEMENT_MODEL_LOCK_BUSY"):
            with integration.announcement_flash_cutover_guard(
                root,
                timeout_seconds=0.2,
                allow_orphan_source_job_id=bound["source_job_id"],
                allow_orphan_idempotency_key=bound["idempotency_key"],
                allow_orphan_payload_sha256=bound["payload_sha256"],
            ):
                pass
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    queue_path = root / "announcement_flash" / "queue" / "queue-state.json"
    queue_state = json.loads(queue_path.read_text(encoding="utf-8"))
    queue_state["jobs"]["c" * 64] = {
        "idempotency_key": "c" * 64,
        "queue_id": "v4-manager-flash-incremental",
        "status": "RUNNING",
    }
    queue_path.write_text(json.dumps(queue_state), encoding="utf-8")
    with pytest.raises(ValueError, match="API_RELEASE_ANNOUNCEMENT_ORPHAN_NOT_UNIQUE_OR_LOCKED"):
        with integration.announcement_flash_cutover_guard(
            root,
            timeout_seconds=0.2,
            allow_orphan_source_job_id=bound["source_job_id"],
            allow_orphan_idempotency_key=bound["idempotency_key"],
            allow_orphan_payload_sha256=bound["payload_sha256"],
        ):
            pass


def _write_user_stopped_cutover_orphan(root: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    old = _write_frozen_cutover_orphan(root, monkeypatch)
    root_id, child_id = old["source_job_id"], "d" * 32
    root_base = root / "announcement_flash" / "jobs" / root_id
    child_base = root_base.parent / child_id
    child_base.mkdir()
    root_input = json.loads((root_base / "input.json").read_bytes())
    root_input["target_date"] = "20261020"
    (root_base / "input.json").write_text(json.dumps(root_input), encoding="utf-8")
    root_ref = {"source_job_id": root_id, "source_input_sha256": _sha((root_base / "input.json").read_bytes())}
    (root_base / "result.json").write_text("{}", encoding="utf-8")
    root_attempt = root / "attempts" / f"{root_id}.json"
    attempt = json.loads(root_attempt.read_bytes())
    attempt.update(state="PARTIAL", finished_at="2026-10-19T22:21:08+08:00")
    attempt["context"]["target_date"] = "20261020"
    root_attempt.write_text(json.dumps(attempt), encoding="utf-8")
    child_input = {**root_input, "job_id": child_id, "resume_root": root_ref,
                   "resume_source": {"source_job_id": "e" * 32}}
    (child_base / "input.json").write_text(json.dumps(child_input), encoding="utf-8")
    child_attempt = root / "attempts" / f"{child_id}.json"
    child_attempt.write_text(json.dumps({
        "job_id": child_id, "state": "FAILED", "finished_at": "2026-10-20T12:47:22+08:00",
        "context": {"target_date": "20261020", "scope_refs": {
            "capture_operation": "ANNOUNCEMENT_FLASH_RESUME",
            "announcement_flash_resume": {"resume_root": root_ref},
        }},
    }), encoding="utf-8")
    key = old["idempotency_key"]
    queue_root = root / "announcement_flash" / "queue"
    payload_path = queue_root / "jobs" / key / "input.json"
    payload = json.loads(payload_path.read_bytes())
    payload["rules"] += "+frozen-resume-contract:v1+root:" + root_id + ":" + root_ref["source_input_sha256"]
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    queue_path = queue_root / "queue-state.json"
    queue = json.loads(queue_path.read_bytes())
    item = queue["jobs"][key]
    item["identity"] = dict(payload)
    item["payload_sha256"] = _sha(payload_path.read_bytes())
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    expected = {**old["expected"], "source_job_id": child_id, "target_date": "20261020",
                "payload_sha256": item["payload_sha256"], "root_job_id": root_id,
                "queue_record_sha256": _sha(json.dumps(item, ensure_ascii=False, sort_keys=True,
                                                       separators=(",", ":")).encode("utf-8"))}
    for label, path in {
        "source_input": child_base / "input.json", "source_attempt": child_attempt,
        "root_input": root_base / "input.json", "root_attempt": root_attempt,
        "root_result": root_base / "result.json",
    }.items():
        expected[label + "_sha256"] = _sha(path.read_bytes())
    monkeypatch.setattr(integration, "ANNOUNCEMENT_CUTOVER_USER_STOPPED_ORPHAN", expected)
    return {**expected, "model_lock": old["model_lock"]}


def _stopped_guard(root: Path, bound: dict[str, object]):
    return integration.announcement_flash_cutover_guard(
        root, timeout_seconds=0.05, allow_orphan_source_job_id=bound["source_job_id"],
        allow_orphan_idempotency_key=bound["idempotency_key"],
        allow_orphan_payload_sha256=bound["payload_sha256"],
    )


def test_user_stopped_orphan_preserves_partial_root_result_and_all_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workbench"
    bound = _write_user_stopped_cutover_orphan(root, monkeypatch)
    before = {str(p): p.read_bytes() for p in root.rglob("*.json")}
    with _stopped_guard(root, bound) as receipt:
        orphan = receipt["allowed_running_orphan"]
        assert orphan["source_job_id"] == bound["source_job_id"]
        assert orphan["root_job_id"] == bound["root_job_id"]
        assert orphan["source_state"] == "FAILED"
        assert orphan["root_state"] == "PARTIAL"
        assert orphan["root_result_sha256"] == bound["root_result_sha256"]
        assert orphan["source_result_absent"] is True
        assert orphan["frozen_stopped_lineage_verified"] is True
        fd = os.open(bound["model_lock"], os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)
    assert {str(p): p.read_bytes() for p in root.rglob("*.json")} == before


@pytest.mark.parametrize("damage", [
    "child_binding", "key_binding", "hash_binding", "root_input", "child_input", "root_attempt",
    "child_attempt", "root_result", "missing_root_result", "child_result", "queue_key", "queue_hash",
    "attempt_count", "attempt_number", "attempt_result", "attempt_owner", "owner", "model", "identity",
    "payload", "unreferenced_result", "additional_running", "additional_active_attempt",
])
def test_user_stopped_orphan_rejects_identity_history_owner_and_activity_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str,
) -> None:
    root = tmp_path / "workbench"
    bound = _write_user_stopped_cutover_orphan(root, monkeypatch)
    queue_root = root / "announcement_flash" / "queue"
    key = bound["idempotency_key"]
    queue_path = queue_root / "queue-state.json"
    queue = json.loads(queue_path.read_bytes())
    item = queue["jobs"][key]
    files = {
        "root_input": root / "announcement_flash" / "jobs" / bound["root_job_id"] / "input.json",
        "child_input": root / "announcement_flash" / "jobs" / bound["source_job_id"] / "input.json",
        "root_attempt": root / "attempts" / f"{bound['root_job_id']}.json",
        "child_attempt": root / "attempts" / f"{bound['source_job_id']}.json",
        "root_result": root / "announcement_flash" / "jobs" / bound["root_job_id"] / "result.json",
    }
    if damage in files:
        files[damage].write_bytes(files[damage].read_bytes() + b" ")
    elif damage == "missing_root_result":
        files["root_result"].unlink()
    elif damage == "child_result":
        (files["child_input"].parent / "result.json").write_text("{}", encoding="utf-8")
    elif damage == "child_binding":
        bound["source_job_id"] = bound["root_job_id"]
    elif damage == "key_binding":
        bound["idempotency_key"] = "f" * 64
    elif damage == "hash_binding":
        bound["payload_sha256"] = "f" * 64
    elif damage == "queue_key":
        queue["jobs"]["f" * 64] = queue["jobs"].pop(key)
    elif damage == "queue_hash":
        item["payload_sha256"] = "f" * 64
    elif damage == "attempt_count":
        item["attempt_count"] = 2
    elif damage == "attempt_number":
        item["attempts"][0]["number"] = 2
    elif damage == "attempt_result":
        item["attempts"][0]["raw_path"] = "result.json"
    elif damage == "attempt_owner":
        item["attempts"][0]["owner_pid"] = 12345
    elif damage == "owner":
        item["owner_pid"] = 12345
    elif damage == "model":
        item["model_id"] = "different-model"
    elif damage == "identity":
        item["identity"]["article_id"] = "OTHER"
    elif damage == "payload":
        path = queue_root / "jobs" / key / "input.json"
        path.write_bytes(path.read_bytes() + b" ")
    elif damage == "unreferenced_result":
        (queue_root / "jobs" / key / "attempt-0001.raw.txt").write_text("{}", encoding="utf-8")
    elif damage == "additional_running":
        queue["jobs"]["f" * 64] = {"status": "RUNNING", "queue_id": "other-business"}
    elif damage == "additional_active_attempt":
        (root / "attempts" / "active.json").write_text(json.dumps({
            "job_id": "f" * 32, "state": "RUNNING", "context": {"target_date": "20261021",
                "scope_refs": {"capture_operation": "ANNOUNCEMENT_FLASH_RESUME"}},
        }), encoding="utf-8")
    else:
        raise AssertionError(damage)
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    with pytest.raises(ValueError, match="API_RELEASE_ANNOUNCEMENT_"):
        with _stopped_guard(root, bound):
            pass


def test_user_stopped_orphan_still_blocks_busy_model_and_submission_locks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from infrastructure.owned_io import SafeRoot

    root = tmp_path / "workbench"
    bound = _write_user_stopped_cutover_orphan(root, monkeypatch)
    fd = os.open(bound["model_lock"], os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match="API_RELEASE_ANNOUNCEMENT_MODEL_LOCK_BUSY"):
            with _stopped_guard(root, bound):
                pass
    finally:
        os.close(fd)
    lock_name = _sha(integration.ANNOUNCEMENT_SUBMIT_LOCK_KEY.encode("utf-8"))
    with SafeRoot(root).kernel_lock(f"locks/{lock_name}.lock", timeout=0.05):
        with pytest.raises(ValueError, match="API_RELEASE_ANNOUNCEMENT_SUBMIT_LOCK_BUSY"):
            with _stopped_guard(root, bound):
                pass
