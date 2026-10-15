from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import plistlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from v4.manager_workbench.contracts import JobState, Lane, LaneState, Phase, digest


SOURCE_DAY = "20261015"
TARGET_DATE = "20261016"
DAILY_KEY = "oversold_daily_20261015_20261016"
LEGACY_KEY = f"nextday_{SOURCE_DAY}_{digest(sorted([Lane.OVERSOLD.value, Lane.US_MAPPING.value]))[:16]}"
HELPER_PATH = Path(__file__).with_name("recover_oversold_20261016.py")
SPEC = importlib.util.spec_from_file_location("recover_oversold_20261016", HELPER_PATH)
HELPER = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(HELPER)


class FakeStore:
    def __init__(self, *, daily_cursor=None, legacy_cursor=None, job=None, plan=None):
        self.cursors = {DAILY_KEY: daily_cursor, LEGACY_KEY: legacy_cursor}
        self.job = job
        self.plan = plan
        self.cursor_reads: list[str] = []
        self.writes = 0

    def cursor(self, key):
        self.cursor_reads.append(key)
        return self.cursors.get(key)

    def set_cursor(self, key, value):
        self.writes += 1
        raise AssertionError("preflight must not fabricate or mutate a cursor")

    def get_job(self, job_id):
        return self.job

    def read_plan(self, run_id):
        return self.plan


def _context(*, source_day=SOURCE_DAY, target_date=TARGET_DATE, phase=Phase.NEXT_DAY,
             trigger="SCHEDULED", requested_lanes=None):
    if requested_lanes is None:
        requested_lanes = [Lane.US_MAPPING, Lane.OVERSOLD]
    return SimpleNamespace(
        target_date=target_date,
        phase=phase,
        trigger=trigger,
        scope_refs={
            "source_hk_session": source_day,
            "requested_lanes": requested_lanes,
        },
    )


def _service(*, daily_cursor=None, legacy_cursor=None, job_state=JobState.PARTIAL,
             finished_at="2026-10-15T16:30:00.458901+08:00", job_context=None,
             plan_context=None, lane_state=LaneState.INPUT_MISSING):
    job_id = "legacy-job"
    run_id = "legacy-run"
    context = job_context or _context()
    plan_ctx = plan_context or _context()
    job = SimpleNamespace(
        job_id=job_id,
        run_id=run_id,
        state=job_state,
        finished_at=finished_at,
        context=context,
    )
    plan = SimpleNamespace(
        run_id=run_id,
        context=plan_ctx,
        lanes=[SimpleNamespace(lane=Lane.OVERSOLD, state=lane_state)],
    )
    if legacy_cursor is None:
        legacy_cursor = {"job_id": job_id, "target_date": TARGET_DATE}
    store = FakeStore(daily_cursor=daily_cursor, legacy_cursor=legacy_cursor, job=job, plan=plan)
    return SimpleNamespace(
        config=SimpleNamespace(scheduled_lanes=[Lane.US_MAPPING, Lane.OVERSOLD]),
        store=store,
    )


def test_missing_daily_cursor_bootstraps_only_from_completed_legacy_partial():
    service = _service()

    initial, bridge = HELPER._recovery_cursor_preflight(service, DAILY_KEY, SOURCE_DAY, TARGET_DATE)

    assert initial is None
    assert bridge == {
        "legacy_cursor_key": LEGACY_KEY,
        "job_id": "legacy-job",
        "run_id": "legacy-run",
        "job_state": "PARTIAL",
        "job_finished_at": "2026-10-15T16:30:00.458901+08:00",
        "source_hk_session": SOURCE_DAY,
        "target_date": TARGET_DATE,
        "phase": "NEXT_DAY",
        "oversold_lane_state": "INPUT_MISSING",
    }
    assert service.store.writes == 0
    assert service.store.cursor_reads == [DAILY_KEY, LEGACY_KEY]


def test_existing_daily_cursor_reuses_its_exact_identity_without_legacy_lookup():
    cursor = {"source_hk_session": SOURCE_DAY, "target_date": TARGET_DATE, "state": "RETRY_WAIT"}
    service = _service(daily_cursor=cursor)

    initial, bridge = HELPER._recovery_cursor_preflight(service, DAILY_KEY, SOURCE_DAY, TARGET_DATE)

    assert initial is cursor
    assert bridge is None
    assert service.store.cursor_reads == [DAILY_KEY]
    assert service.store.writes == 0


def test_missing_legacy_cursor_stays_fail_closed():
    service = _service(legacy_cursor=None)
    service.store.cursors[LEGACY_KEY] = None

    with pytest.raises(RuntimeError, match="LEGACY_NEXTDAY_CURSOR_MISSING"):
        HELPER._recovery_cursor_preflight(service, DAILY_KEY, SOURCE_DAY, TARGET_DATE)


@pytest.mark.parametrize("job_state, finished_at", [
    (JobState.RUNNING, None),
    (JobState.QUEUED, None),
    (JobState.PARTIAL, None),
])
def test_running_or_unfinished_legacy_job_is_rejected(job_state, finished_at):
    service = _service(job_state=job_state, finished_at=finished_at)

    with pytest.raises(RuntimeError, match="LEGACY_NEXTDAY_JOB_(STILL_RUNNING|NOT_COMPLETED)"):
        HELPER._recovery_cursor_preflight(service, DAILY_KEY, SOURCE_DAY, TARGET_DATE)


def test_legacy_cursor_target_mismatch_is_rejected():
    service = _service(legacy_cursor={"job_id": "legacy-job", "target_date": "20261019"})

    with pytest.raises(RuntimeError, match="LEGACY_NEXTDAY_CURSOR_TARGET_MISMATCH"):
        HELPER._recovery_cursor_preflight(service, DAILY_KEY, SOURCE_DAY, TARGET_DATE)


@pytest.mark.parametrize("job_context, plan_context", [
    (_context(source_day="20261014"), _context()),
    (_context(target_date="20261019"), _context()),
    (_context(phase=Phase.INTRADAY), _context()),
    (_context(), _context(source_day="20261014")),
    (_context(), _context(target_date="20261019")),
    (_context(), _context(phase=Phase.INTRADAY)),
])
def test_legacy_job_and_plan_must_match_exact_nextday_pair(job_context, plan_context):
    service = _service(job_context=job_context, plan_context=plan_context)

    with pytest.raises(RuntimeError, match="LEGACY_NEXTDAY_(JOB|PLAN)_CONTEXT_MISMATCH"):
        HELPER._recovery_cursor_preflight(service, DAILY_KEY, SOURCE_DAY, TARGET_DATE)


@pytest.mark.parametrize("lane_state", [LaneState.READY, LaneState.PARTIAL, LaneState.FAILED])
def test_legacy_oversold_lane_must_be_input_missing(lane_state):
    service = _service(lane_state=lane_state)

    with pytest.raises(RuntimeError, match="LEGACY_NEXTDAY_OVERSOLD_NOT_INPUT_MISSING"):
        HELPER._recovery_cursor_preflight(service, DAILY_KEY, SOURCE_DAY, TARGET_DATE)


def _prepare_active_identity_fixture(tmp_path, monkeypatch):
    release_id = "zsxq-pdf-ocr-scheduler-20261016-r4"
    release_root = tmp_path / "releases" / release_id
    app_root = release_root / "app"
    app_root.mkdir(parents=True)
    candidate_root = tmp_path / "releases" / "oversold-daily-auto-20261016-r1"
    runtime_root = tmp_path / "runtime"
    config_path = tmp_path / "manager-workbench-v7.json"
    config_path.write_text("{}\n", encoding="utf-8")
    source_contents = {
        "v4/manager_workbench/scheduler.py": b"scheduler\n",
        "v4/manager_workbench/inputs/source_bindings.py": b"bindings\n",
        "v4/manager_workbench/service.py": b"service\n",
        "v4/manager_workbench/store.py": b"store\n",
        "v4/manager_workbench/oversold_daily.py": b"daily\n",
        "upstreams/v3_shared_data/shared_data/hk_daily_supplement.py": b"owner\n",
    }
    source_hashes = {}
    manifest_entries = []
    for relative_path, raw in source_contents.items():
        path = app_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        source_hashes[relative_path] = hashlib.sha256(raw).hexdigest()
        manifest_entries.append({"path": relative_path, "sha256": source_hashes[relative_path]})

    manifest_path = release_root / "release-manifest.json"
    manifest_path.write_text(json.dumps({
        "role": "scheduler",
        "base": {
            "app_root": str(candidate_root / "app"),
            "manifest_sha256": HELPER.OVERSOLD_CANDIDATE_MANIFEST_SHA256,
            "plist_sha256": HELPER.OVERSOLD_CANDIDATE_PLIST_SHA256,
        },
        "candidate": {
            "app_root": str(app_root),
            "release_id": release_id,
            "root": str(release_root),
        },
        "application_inventory": {"entries": manifest_entries},
    }, sort_keys=True), encoding="utf-8")
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    plist_path = tmp_path / "com.lexi.v35.scheduler.plist"
    pid = 32762
    env = {
        "V35_APP_ROOT": str(app_root),
        "V35_RELEASE_ID": release_id,
        "V35_RUNTIME_ROOT": str(runtime_root),
        "V35_RELEASE_MANIFEST_SHA256": manifest_sha,
        "PYTHONPATH": f"{app_root / 'upstreams'}{os.pathsep}{app_root}",
        "V4_MANAGER_WORKBENCH_CONFIG_PATH": str(config_path),
    }
    plist_path.write_bytes(plistlib.dumps({
        "EnvironmentVariables": env,
        "ProgramArguments": ["/bin/bash", str(app_root / "ops/launch_v35_macos_scheduler.sh")],
        "WorkingDirectory": str(app_root),
    }))
    plist_sha = hashlib.sha256(plist_path.read_bytes()).hexdigest()
    config_sha = hashlib.sha256(config_path.read_bytes()).hexdigest()

    for name, value in {
        "ACTIVE_RELEASE_ROOT": release_root,
        "ACTIVE_APP_ROOT": app_root,
        "OVERSOLD_CANDIDATE": candidate_root,
        "ACTIVE_CONFIG": config_path,
        "ACTIVE_RUNTIME_ROOT": runtime_root,
        "ACTIVE_RELEASE_ID": release_id,
        "ACTIVE_PID": pid,
        "ACTIVE_PLIST": plist_path,
        "ACTIVE_PLIST_SHA256": plist_sha,
        "ACTIVE_MANIFEST_SHA256": manifest_sha,
        "ACTIVE_CONFIG_SHA256": config_sha,
        "ACTIVE_SOURCE_SHA256": source_hashes,
    }.items():
        monkeypatch.setattr(HELPER, name, value)

    observed = {"cwd": str(app_root), "pid": pid}
    python = runtime_root / "venvs/v3.5-mac/bin/python"

    def fake_run(command, **_kwargs):
        if command[0] == "/bin/launchctl":
            stdout = (f"path = {plist_path}\nprogram = /bin/bash\n"
                      f"working directory = {app_root}\nstate = running\npid = {observed['pid']}\n")
            return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
        if command[0] == "/bin/ps":
            stdout = f"{observed['pid']} {python} -S -m ops.run_v35_macos_scheduler_daemon --data-root X\n"
            return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
        if command[0] == "/usr/sbin/lsof":
            stdout = f"p{observed['pid']}\nfcwd\nn{observed['cwd']}\n"
            return SimpleNamespace(returncode=0, stdout=stdout, stderr="")
        raise AssertionError(f"unexpected identity command: {command[0]}")

    monkeypatch.setattr(HELPER.subprocess, "run", fake_run)
    return {
        "app_root": app_root,
        "config_path": config_path,
        "observed": observed,
        "source_contents": source_contents,
    }


def test_active_r4_identity_constants_are_pinned_to_the_reviewed_inheritance():
    assert HELPER.ACTIVE_RELEASE_ID == "zsxq-pdf-ocr-scheduler-20261016-r4"
    assert HELPER.ACTIVE_PID == 32762
    assert HELPER.ACTIVE_PLIST_SHA256 == "e347c7a08037948a1d1a40e392f8ad95ce28a2555306a94dcb17513346a82d72"
    assert HELPER.ACTIVE_MANIFEST_SHA256 == "4710696eb61e60ac5dbd1ea56aa2e7a3762d9c1f9170d206b4dc0beac4769e91"
    assert HELPER.ACTIVE_CONFIG_SHA256 == "65684e5eb7657390747c089db74047d6a2c67d7f5de1bd3fe757a62f120965ca"
    assert HELPER.ACTIVE_SOURCE_SHA256 == {
        "v4/manager_workbench/scheduler.py": "0672296a340ae84d6bfb48b77b8d23566ea32b4fdb27edc505ea3abb4d785990",
        "v4/manager_workbench/inputs/source_bindings.py": "4e9339675d544a5f57e0fe6c5bc5522fba7b9aac6fdc21d6967082cfb7729edb",
        "v4/manager_workbench/service.py": "338544fc7876170e05566b5df90c31058a275fa8076f6474b80ab2bd7e19997e",
        "v4/manager_workbench/store.py": "493df1a72bf4c4a533ae533ce5fc0185c9d9536d01c4e88082270908c8b1aa18",
        "v4/manager_workbench/oversold_daily.py": "1a88ac9c1bb3e1a2d68fff350a69204a65b7ebb782f27512bb4fc1c45f9b0583",
        "upstreams/v3_shared_data/shared_data/hk_daily_supplement.py": "62513b42bcd133d3c447b9b797b81c19f43a306c9544ce97a11447db93b54e9e",
    }


def test_active_scheduler_identity_accepts_only_the_exact_inherited_r4(tmp_path, monkeypatch):
    _prepare_active_identity_fixture(tmp_path, monkeypatch)

    identity = HELPER._validate_active_scheduler_identity()

    assert identity["active_release_identity"] == "VERIFIED_EXACT_INHERITED_R4"
    assert identity["pid"] == 32762
    assert identity["release_id"] == "zsxq-pdf-ocr-scheduler-20261016-r4"
    assert identity["launchd_label_pid_match"] is True
    assert identity["process_interpreter_module_match"] is True
    assert identity["process_cwd"].endswith("/app")


def test_active_scheduler_identity_rejects_a_different_live_pid(tmp_path, monkeypatch):
    fixture = _prepare_active_identity_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(HELPER, "ACTIVE_PID", HELPER.ACTIVE_PID + 1)

    with pytest.raises(RuntimeError, match="ACTIVE_SCHEDULER_LABEL_PID_MISMATCH"):
        HELPER._validate_active_scheduler_identity()


def test_active_scheduler_identity_rejects_changed_source_even_if_manifest_is_pinned(tmp_path, monkeypatch):
    fixture = _prepare_active_identity_fixture(tmp_path, monkeypatch)
    path = fixture["app_root"] / "v4/manager_workbench/oversold_daily.py"
    path.write_text("changed after manifest\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="ACTIVE_SCHEDULER_SOURCE_SHA_MISMATCH"):
        HELPER._validate_active_scheduler_identity()


def test_active_scheduler_identity_rejects_changed_config(tmp_path, monkeypatch):
    fixture = _prepare_active_identity_fixture(tmp_path, monkeypatch)
    fixture["config_path"].write_text("changed config\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="ACTIVE_MANAGER_CONFIG_SHA_MISMATCH"):
        HELPER._validate_active_scheduler_identity()

