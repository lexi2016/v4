"""Focused regressions for coordinator restart, byte evidence, and live read timing."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from research.p515_prospective_readiness import coordinator as c
from research.p515_prospective_readiness.coordinator import (
    AuthorizationBundle, ReadinessCoordinator, RuntimePins,
)
from research.p515_prospective_readiness.drive_store import (
    GoogleDriveReadbackStore, VerifiedDriveReceipt, sha256_bytes,
)


def test_default_real_coordinator_stays_no_go_without_writes(tmp_path):
    from test_p515_readiness_wiring import make_case

    _, daily, _, _, _ = make_case()
    daily = replace(daily, synthetic_fixture=False)
    root = tmp_path / "real-no-go"
    runner = ReadinessCoordinator(root)

    with pytest.raises(c.NoGoError, match="no externally hash-pinned"):
        runner.prepare_day(daily)

    assert not root.exists()
    assert runner.execution_counts() == {
        "daily_reservations": 0,
        "paired_output_rows_reserved": 0,
        "unique_pb_reserved": 0,
        "model_api_predict_calls": 0,
        "fixture_callbacks": 0,
        "input_seal_intents": 0,
        "seal_missed": 0,
    }


def test_eligible_r2_evidence_is_persisted_losslessly_and_bound_in_manifest(tmp_path):
    from test_p515_readiness_wiring import make_case
    from research.p515_prospective_readiness import wiring

    bound, daily, row, _, _ = make_case()
    source_verifier = wiring.BoundSourceVerifier(bound)
    state_verifier = wiring.BoundStateVerifier(bound)
    runner = ReadinessCoordinator(
        tmp_path,
        source_verifier=source_verifier,
        state_verifier=state_verifier,
        fixture_only=True,
        clock=lambda: daily.captured_at,
    )
    prepared = runner.prepare_day(daily)

    manifest = __import__("json").loads(prepared.input_manifest_bytes)
    evidence = manifest["eligible_state_evidence"]
    assert len(evidence) == 1
    assert evidence[0]["ts_code"] == row.ts_code
    proofs, raw_evidence = state_verifier.verify(daily, daily.rows, None)
    expected = raw_evidence[row.ts_code]
    import base64

    assert base64.b64decode(evidence[0]["anchor_receipt_bytes_b64"]) == expected.anchor_receipt_bytes
    assert base64.b64decode(evidence[0]["checkpoint_bytes_b64"]) == expected.checkpoint_bytes
    assert evidence[0]["anchor_receipt_sha256"] == proofs[row.ts_code].anchor_receipt_sha256
    assert evidence[0]["checkpoint_sha256"] == proofs[row.ts_code].checkpoint_sha256

    sidecar = Path(prepared.reservation_path) / "ELIGIBLE_R2_STATE_EVIDENCE.json"
    sidecar_bytes = sidecar.read_bytes()
    assert sha256_bytes(sidecar_bytes) == manifest["eligible_state_evidence_sha256"]
    assert len(sidecar_bytes) == manifest["eligible_state_evidence_size_bytes"]
    assert __import__("json").loads(sidecar_bytes)["evidence"] == evidence


def test_pre_study_authorization_receipt_survives_restart_for_late_restore(tmp_path):
    """Synthetic unit seam: only a persisted pre-cutoff receipt allows restore."""

    original_verified = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)
    late_now = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)
    created = datetime(2026, 11, 19, 9, 0, tzinfo=timezone.utc)
    raw_grant, raw_pre = b"fixture-grant", b"fixture-pre-study"
    grant_receipt = VerifiedDriveReceipt(
        "grant-id", "grant.json", ("parent",), "application/json", "v1", "files.get.version",
        len(raw_grant), sha256_bytes(raw_grant), created, created, original_verified,
    )
    pre_receipt = VerifiedDriveReceipt(
        "pre-id", "pre.json", ("parent",), "application/json", "v2", "files.get.version",
        len(raw_pre), sha256_bytes(raw_pre), created, created, original_verified,
    )

    first = ReadinessCoordinator(tmp_path, fixture_only=True, clock=lambda: original_verified)
    first.store.append_event("STUDY_AUTHORIZATION_VERIFIED", None, {
        "grant": first._receipt_payload(grant_receipt),
        "pre_study": first._receipt_payload(pre_receipt),
    }, created_at=original_verified)

    # Opening the same fixed root represents a new process. The persisted event
    # is required before the restored process can get past the late-start gate.
    restored = ReadinessCoordinator(tmp_path, fixture_only=True, clock=lambda: late_now)
    identity = {key: "a" * 64 for key in c.REQUIRED_IDENTITY_KEYS}
    pins = RuntimePins(
        grant_sha256=sha256_bytes(raw_grant),
        pre_study_sha256=sha256_bytes(raw_pre),
        grant_file_id="grant-id",
        pre_study_file_id="pre-id",
        parent_id="parent",
        identity_sha256=identity,
        grant_name="grant.json",
        pre_study_name="pre.json",
        output_root=str((tmp_path).resolve()),
        grant_version="v1",
        pre_study_version="v2",
    )
    restored.pins = pins
    restored._validate_identity_lock = lambda: None
    restored._validate_authorization_payload = lambda bundle: ({}, {}, late_now + timedelta(days=10))

    def verify(*, file_id, **_kwargs):
        return grant_receipt if file_id == "grant-id" else pre_receipt

    restored._verify_pinned_drive_file = verify
    gate = restored.authorize_study(AuthorizationBundle(raw_grant, raw_pre))
    assert gate.verified_at == late_now
    assert restored.store.original_authorization_event() is not None
    assert any(event["event"] == "STUDY_AUTHORIZATION_RESTORED"
               for event in restored.store.day_events("20261127")) is False
    # Study-level events have D=NULL; the audit log confirms the restore path.
    assert '"event":"STUDY_AUTHORIZATION_RESTORED"' in restored.store.log_path.read_text()


def test_drive_readback_clock_is_sampled_after_network_round_trip(tmp_path):
    from datetime import datetime, timezone

    state = {"now": datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc)}
    body = b"raw"

    class Transport:
        def _advance(self):
            state["now"] += timedelta(minutes=1)

        def get_file_metadata(self, file_id):
            self._advance()
            return {
                "id": file_id,
                "name": "pinned.json",
                "mimeType": "application/json",
                "parents": ["parent"],
                "size": str(len(body)),
                "createdTime": "2026-11-18T09:00:00Z",
                "modifiedTime": "2026-11-18T09:00:00Z",
                "version": "7",
                "headRevisionId": "rev7",
            }

        def list_revisions(self, _file_id):
            self._advance()
            return [{"id": "rev7", "modifiedTime": "2026-11-18T09:00:00Z"}]

        def download_media(self, _file_id):
            self._advance()
            return body

    drive = GoogleDriveReadbackStore(Transport(), clock=lambda: state["now"])
    runner = object.__new__(ReadinessCoordinator)
    runner.pins = SimpleNamespace(parent_id="parent", evidence_mime_type="application/json")
    runner.drive_store = drive
    runner.clock = lambda: state["now"]

    receipt = runner._verify_pinned_drive_file(
        file_id="f1", name="pinned.json", raw=body, sha256=sha256_bytes(body),
        expected_version="7",
    )
    assert receipt.observed_at == state["now"]
    assert receipt.observed_at > datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc)


def test_output_phase_uses_2330_deadline_and_input_phase_stays_2130(tmp_path):
    from test_p515_readiness_wiring import make_case

    _, daily, _, _, _ = make_case()
    now = datetime(2026, 11, 27, 22, 0, tzinfo=timezone.utc)  # 06:00 next day Beijing, adjusted below
    now = datetime(2026, 11, 27, 14, 0, tzinfo=timezone.utc)  # 22:00 Asia/Shanghai
    runner = ReadinessCoordinator(tmp_path, fixture_only=True, clock=lambda: now)

    _, _, output_deadline = runner._validate_day_clock(daily, phase="output")
    assert output_deadline == datetime(2026, 11, 27, 23, 30, tzinfo=c.BEIJING).astimezone(timezone.utc)
    with pytest.raises(c.NoGoError, match="21:30 input deadline passed"):
        runner._validate_day_clock(daily, phase="input")
