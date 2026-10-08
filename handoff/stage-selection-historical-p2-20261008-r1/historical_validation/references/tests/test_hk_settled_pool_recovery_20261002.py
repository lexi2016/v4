from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

import ops.run_stage_center_nodes as nodes
import stage_center.runner as stage_runner


TRADE_DATE = "20261002"
STAGE_ID = "STAGE_1445_1500"
SHANGHAI = timezone(timedelta(hours=8))
WALL_NOW = datetime(2026, 10, 2, 16, 10, tzinfo=SHANGHAI)
FLAGS = {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
AUTH_ID = "hk-stage-20261002-1445-1500-r2"


def _evidence_root() -> Path:
    return Path(os.environ["STAGE_RECOVERY_EVIDENCE_ROOT"])


def _assert_expected_import_root() -> None:
    expected = Path(os.environ["STAGE_RECOVERY_EXPECTED_APP_ROOT"]).resolve()
    assert Path(nodes.__file__).resolve().parents[1] == expected


def _copy_pool(tmp_path: Path) -> Path:
    source = _evidence_root() / "pool_fixture" / "data"
    target = tmp_path / "pool-data"
    shutil.copytree(source, target)
    return target


def _old_receipt() -> bytes:
    raw = (_evidence_root() / "original_settled_receipt.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "b2f4e758f7480c668904e40b6a71181ebc8e19a3916e76f215c4c812fe303a23"
    )
    return raw


def _authorization(tmp_path: Path, **changes) -> Path:
    payload = json.loads(
        (_evidence_root() / "settled_recovery_authorization_request.json").read_text()
    )
    payload.update(
        authorization_status="AUTHORIZED",
        review_status="APPROVED",
        approval_id="OFFLINE-TEST-APPROVAL",
        authorized_by="offline-test-operator",
        authorized_at="2026-10-02T16:00:00+08:00",
        independent_reviewer_id="offline-test-reviewer",
        independently_reviewed_at="2026-10-02T15:59:00+08:00",
    )
    payload.update(changes)
    path = tmp_path / "approved-test-authorization.json"
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


def _write_receipt(receipt_root: Path, raw: bytes) -> Path:
    path = receipt_root / TRADE_DATE / STAGE_ID / "receipt.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


class FakeRunner:
    def __init__(self, receipt_root: Path, pool_root: Path, *, decision_status="LATE_CATCHUP_REPLAY"):
        self.config = SimpleNamespace(
            receipt_root=receipt_root,
            hk_d1_root=pool_root,
            preselection_source_root=pool_root,
        )
        self.call_count = 0
        self.reservation_seen_before_runner = False
        self.decision_status = decision_status
        self.decision = SimpleNamespace(
            stage_id=STAGE_ID,
            trade_date=TRADE_DATE,
            status=decision_status,
            scheduled_at=datetime(2026, 10, 2, 15, 0, tzinfo=SHANGHAI),
            same_day_late_observation_recovery=False,
        )

    def due_decisions(self, trade_date, evaluated_at, *, historical_backfill=False):
        return [self.decision] if trade_date == TRADE_DATE else []

    def _receipt_path(self, trade_date, stage_id):
        return self.config.receipt_root / trade_date / stage_id / "receipt.json"

    def _run_one(self, decision):
        self.call_count += 1
        history = self._receipt_path(TRADE_DATE, STAGE_ID).parent / "settled_hk_recovery_r2" / AUTH_ID
        self.reservation_seen_before_runner = (history / "reservation.json").is_file()
        if self.reservation_seen_before_runner:
            assert decision.same_day_late_observation_recovery is True
        return {
            "status": "READY",
            "trade_date": TRADE_DATE,
            "stage_id": STAGE_ID,
            "write_performed": True,
            "markets": {"HK_CONNECT": {"status": "READY", "selected_rows": 1, **FLAGS}},
            **FLAGS,
        }

    def _write_receipt(self, payload, trade_date, stage_id):
        path = self._receipt_path(trade_date, stage_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return dict(payload)


@pytest.fixture
def isolated_dispatch(monkeypatch, tmp_path):
    _assert_expected_import_root()
    pool_root = _copy_pool(tmp_path)
    receipt_root = tmp_path / "receipts"
    runner = FakeRunner(receipt_root, pool_root)
    monkeypatch.setattr(nodes, "_calendar_gate", lambda *_args, **_kwargs: {"status": "ELIGIBLE", **FLAGS})
    monkeypatch.setattr(nodes, "_rearm_wall_now", lambda: WALL_NOW)
    monkeypatch.setattr(nodes._deadline, "checkpoint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(nodes._deadline, "due", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(nodes._deadline, "event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(nodes._deadline, "complete_receipt", lambda _path, payload, **_kwargs: payload)
    config = {
        "receipt_root": str(receipt_root),
        "hk_d1_root": str(pool_root),
        "preselection_source_root": str(pool_root),
        "node_max_attempts": 3,
        "node_retry_backoff_seconds": 0,
        "safety": dict(FLAGS),
    }
    old_raw = _old_receipt()
    receipt_path = _write_receipt(receipt_root, old_raw)
    evaluated_at = datetime(2026, 10, 2, 16, 2, tzinfo=SHANGHAI)
    return config, runner, receipt_path, old_raw, evaluated_at, tmp_path


def _dispatch(config, runner, evaluated_at, authorization_path=None, *, trade_date=TRADE_DATE):
    config = dict(config)
    if authorization_path is not None:
        config["_settled_hk_recovery_authorization_path"] = str(authorization_path)
    return nodes._dispatch_stage(
        config,
        trade_date,
        STAGE_ID,
        evaluated_at,
        mode="RECOVERY",
        runner=runner,
        precaptures=None,
    )


def test_correct_binding_reserves_attempt_three_then_runs_once(isolated_dispatch):
    config, runner, receipt_path, old_raw, evaluated_at, tmp_path = isolated_dispatch
    authorization = _authorization(tmp_path)

    binding = stage_runner._build_hk_stage_binding(
        Path(config["hk_d1_root"]), TRADE_DATE,
        preselection_source_root=Path(config["preselection_source_root"]),
    )
    assert binding.status == "READY"
    assert binding.sha256 == "9486b32cd8290994e1bf82cd15863fb7d0c00100bd52f1f6eb5d03af80b72077"
    result = _dispatch(config, runner, evaluated_at, authorization)

    history = receipt_path.parent / "settled_hk_recovery_r2" / AUTH_ID
    reservation = json.loads((history / "reservation.json").read_text())
    assert runner.call_count == 1
    assert runner.reservation_seen_before_runner is True
    assert reservation["status"] == "RESERVED_BEFORE_PROVIDER"
    assert reservation["original_node_attempt_count"] == 2
    assert reservation["reserved_node_attempt_count"] == 3
    assert (history / "prior_receipt.json").read_bytes() == old_raw
    assert (history / "prior_receipt.json").stat().st_mode & 0o777 == 0o400
    assert (history / "reservation.json").stat().st_mode & 0o777 == 0o400
    assert result["node_attempt_count"] == 3
    assert result["settled_hk_recovery"]["corrected_pool_sha256"] == binding.sha256
    assert result["settled_hk_recovery"]["prior_receipt_sha256"] == hashlib.sha256(old_raw).hexdigest()
    assert all(result[key] is False for key in FLAGS)


@pytest.mark.parametrize(
    "changes",
    (
        {"trade_date": "20261003"},
        {"prior_receipt_sha256": "0" * 64},
        {"corrected_candidate_artifact_sha256": "1" * 64},
        {"safety_flags": {"production_allowed": True, "buy_gate_updated": False, "orders_sent": False}},
    ),
)
def test_mismatched_authorization_fails_before_runner_and_preserves_receipt(isolated_dispatch, changes):
    config, runner, receipt_path, old_raw, evaluated_at, tmp_path = isolated_dispatch
    authorization = _authorization(tmp_path, **changes)

    result = _dispatch(config, runner, evaluated_at, authorization)

    assert result["status"] == "CANNOT_CONFIRM"
    assert runner.call_count == 0
    assert receipt_path.read_bytes() == old_raw
    assert not (receipt_path.parent / "settled_hk_recovery_r2").exists()


def test_bad_pool_fails_closed_without_overwriting_prior_receipt(isolated_dispatch):
    config, runner, receipt_path, old_raw, evaluated_at, tmp_path = isolated_dispatch
    artifact = Path(config["hk_d1_root"]) / "preselection_pools" / TRADE_DATE / "hkconnect_d1_top100.json"
    payload = json.loads(artifact.read_text())
    payload["rows"][0]["name"] = "tampered"
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    authorization = _authorization(tmp_path)

    result = _dispatch(config, runner, evaluated_at, authorization)

    assert result["status"] == "CANNOT_CONFIRM"
    assert runner.call_count == 0
    assert receipt_path.read_bytes() == old_raw
    assert not (receipt_path.parent / "settled_hk_recovery_r2").exists()


def test_pending_authorization_request_cannot_run(isolated_dispatch):
    config, runner, receipt_path, old_raw, evaluated_at, _tmp_path = isolated_dispatch
    pending = _evidence_root() / "settled_recovery_authorization_request.json"

    result = _dispatch(config, runner, evaluated_at, pending)

    assert result["status"] == "CANNOT_CONFIRM"
    assert runner.call_count == 0
    assert receipt_path.read_bytes() == old_raw
    assert not (receipt_path.parent / "settled_hk_recovery_r2").exists()


def test_repeated_authorization_does_not_run_or_overwrite(isolated_dispatch):
    config, runner, receipt_path, old_raw, evaluated_at, tmp_path = isolated_dispatch
    authorization = _authorization(tmp_path)
    first = _dispatch(config, runner, evaluated_at, authorization)
    post_first = receipt_path.read_bytes()
    repeated = _dispatch(config, runner, evaluated_at, authorization)

    assert first["node_attempt_count"] == 3
    assert repeated["status"] == "SKIPPED_SETTLED_RECOVERY_ALREADY_CONSUMED"
    assert runner.call_count == 1
    assert receipt_path.read_bytes() == post_first
    history = receipt_path.parent / "settled_hk_recovery_r2" / AUTH_ID
    assert (history / "prior_receipt.json").read_bytes() == old_raw


def test_concurrent_slot_lock_preserves_original_receipt_without_provider(isolated_dispatch):
    config, runner, receipt_path, old_raw, evaluated_at, tmp_path = isolated_dispatch
    authorization = _authorization(tmp_path)
    lock = stage_runner.SlotLock(stage_runner._slot_lock_path(runner.config, TRADE_DATE, STAGE_ID))
    assert lock.acquire()
    try:
        locked = _dispatch(config, runner, evaluated_at, authorization)
        assert locked["status"] == "SKIPPED_SLOT_LOCKED"
        assert runner.call_count == 0
        assert receipt_path.read_bytes() == old_raw
        assert not (receipt_path.parent / "settled_hk_recovery_r2").exists()
    finally:
        lock.release()


def test_settled_receipt_and_generic_transient_retry_keep_existing_behavior(isolated_dispatch):
    config, runner, receipt_path, old_raw, evaluated_at, _tmp_path = isolated_dispatch
    settled = _dispatch(config, runner, evaluated_at)
    assert settled["status"] == "SKIPPED_ALREADY_SETTLED"
    assert runner.call_count == 0
    assert receipt_path.read_bytes() == old_raw

    transient = {
        "schema_version": "stage_center.runner.receipt.v1",
        "trade_date": TRADE_DATE,
        "stage_id": STAGE_ID,
        "node_id": STAGE_ID,
        "dispatch_mode": "RECOVERY",
        "status": "CANNOT_CONFIRM",
        "node_outcome": "TRANSIENT",
        "node_attempt_count": 2,
        "retry_exhausted": False,
        "retry_after": "2026-10-02T15:01:00+08:00",
        **FLAGS,
    }
    receipt_path.write_text(json.dumps(transient), encoding="utf-8")
    result = _dispatch(config, runner, evaluated_at)
    assert runner.call_count == 1
    assert result["node_attempt_count"] == 3
    assert not (receipt_path.parent / "settled_hk_recovery_r2").exists()


def test_recovery_noop_summary_is_skipped(monkeypatch):
    _assert_expected_import_root()
    monkeypatch.setattr(nodes, "_bounded_wait_until", lambda target, now, **_kwargs: (now, 0.0))
    monkeypatch.setattr(
        nodes,
        "_dispatch_stage",
        lambda *_args, **_kwargs: {
            "status": "SKIPPED_ALREADY_SETTLED",
            "dispatch_mode": "RECOVERY",
            "write_performed": False,
            **FLAGS,
        },
    )
    result = nodes.run_nodes(
        {},
        trade_date=TRADE_DATE,
        evaluated_at=datetime(2026, 10, 2, 16, 2, tzinfo=SHANGHAI),
        explicit_node=STAGE_ID,
        runner=object(),
    )
    assert result["status"] == "RECOVERY_SKIPPED"
    assert nodes._exit_code(result["status"]) == 0


def test_cli_rejects_authorization_outside_frozen_incident_scope(monkeypatch, tmp_path):
    _assert_expected_import_root()
    authorization = _authorization(tmp_path)
    printed = {}

    class Trace:
        def close(self):
            self.closed = True

    trace = Trace()
    monkeypatch.setattr(nodes._deadline, "install", lambda *_args, **_kwargs: trace)
    monkeypatch.setattr(nodes._deadline, "summary", lambda: None)
    monkeypatch.setattr(nodes._deadline, "checkpoint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(nodes, "_load_config", lambda _path: {})
    monkeypatch.setattr(nodes, "_print_json", lambda payload: printed.update(payload))

    exit_code = nodes.main([
        "--config", str(tmp_path / "unused-config.json"),
        "--node", STAGE_ID,
        "--trade-date", "20261003",
        "--evaluated-at", "2026-10-03T16:02:00+08:00",
        "--settled-hk-recovery-authorization", str(authorization),
    ])

    assert exit_code == 3
    assert printed["status"] == "CANNOT_CONFIRM"
    assert printed["write_performed"] is False
    assert all(printed[key] is False for key in FLAGS)
    assert trace.closed is True
