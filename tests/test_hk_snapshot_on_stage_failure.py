"""Frozen HK failure-snapshot acceptance; fake provider, real immutable store."""
from __future__ import annotations

import base64
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from stage_center import runner as runner_module
from stage_center.hk_stage8 import snapshot as snapshot_module
from stage_center.hk_stage8.precapture import prepare_due_snapshot
from stage_center._runner_parts.slot_execution import _StageCenterRunner__run_one_body
from stage_center.acquisition import SourceResult
from stage_center.contracts import SAFETY_FLAGS

DATE = "20261023"
STAGE = "STAGE_0930_0935"
CODES = ("HK.00001", "HK.00002")
POOL_SHA = "a" * 64
NOW = datetime(2026, 10, 23, 9, 34, 10, tzinfo=ZoneInfo("Asia/Shanghai"))


def native_rows(codes=CODES):
    return [{"code": code, "update_time": "2026-10-23 09:34:09", "last_price": 11,
             "prev_close_price": 10, "turnover": 30_000_000, "volume_ratio": 2,
             "native_extra": {"unaltered": "盘口"}, "order_book": {"Bid": [[10.9, 100, 1]], "Ask": [[11, 200, 2]]}}
            for code in codes]


def capture(tmp_path, monkeypatch, *, rows=None, error=None, clock=None):
    rows = native_rows() if rows is None else rows
    original = "FUTU_NATIVE " + json.dumps({"rows": rows}, ensure_ascii=False) + "\n"

    def fetch(python_path, codes, *, process_runner, include_order_book=False):
        assert tuple(codes) == CODES
        assert include_order_book is True
        process_runner([str(python_path), "native-snapshot"])
        return rows, ()

    monkeypatch.setattr(snapshot_module, "_load_shared_module", lambda *_: SimpleNamespace(fetch_futu_snapshot=fetch))

    def process(*args, **kwargs):
        if error:
            raise error
        return subprocess.CompletedProcess(args[0], 0, stdout=original, stderr="")

    result = snapshot_module.prepare_hk_active_snapshot(tmp_path, trade_date=DATE, stage_id=STAGE,
        codes=CODES, python_path=Path("/fake/python"), shared_root=tmp_path / "package",
        evaluated_at=NOW.isoformat(), cutoff_at="09:35:05", pool_artifact_sha256=POOL_SHA,
        process_runner=process, clock=clock or (lambda: NOW), sleeper=lambda _: None)
    return result, original.encode("utf-8")


def config(tmp_path, *, builders=None):
    return runner_module.RunnerConfig(candidate_acquisition_root=tmp_path / "candidate",
        raw_root=tmp_path / "raw", selection_root=tmp_path / "selection", receipt_root=tmp_path / "receipts",
        hk_d1_root=tmp_path / "d1", shared_data_root=tmp_path / "package", python_path=Path("/fake/python"),
        selection_builders=builders)


def assert_transport(result, original):
    event = json.loads(Path(result["native_capture_attempts"][0]["path"]).read_bytes())
    transport = next(ref for ref in event["payload_events"] if ref["event"].startswith("transport-"))
    raw = Path(transport["path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == transport["sha256"]
    stored = json.loads(raw)
    assert base64.b64decode(stored["stdout_base64"]) == original
    assert stored["stdout_sha256"] == hashlib.sha256(original).hexdigest()
    assert stored["codes"] == list(CODES)
    assert stored["pool_artifact_sha256"] == POOL_SHA
    assert stored["provider_started_at"] == NOW.isoformat()
    assert stored["authorizes_selection"] is False
    return event


def test_canary_snapshot_survives_subsequent_local_binding_failure(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    result, original = capture(cfg.raw_root, monkeypatch)
    assert result["status"] == "READY"
    before = Path(result["snapshot_path"]).read_bytes()
    assert_transport(result, original)
    monkeypatch.setattr(runner_module, "read_candidate_input", lambda *_args, **_kwargs: (_ for _ in ()).throw(runner_module.CandidateInputError("A absent")))
    monkeypatch.setattr(runner_module, "_build_hk_stage_binding", lambda *_args, **_kwargs: (_ for _ in ()).throw(runner_module.RunnerError("local D1 absent")))
    monkeypatch.setattr(runner_module, "_resolve_stage_market_scope", lambda *_args, **_kwargs: ("HK_CONNECT",))
    runner = runner_module.StageCenterRunner(cfg)
    receipt = runner._run_one(SimpleNamespace(trade_date=DATE, stage_id=STAGE, status="DUE"))
    assert receipt["status"] == "CANNOT_CONFIRM"
    assert receipt["first_failed_layer"] == "EXACT_SELECTION_INPUT_BINDING"
    assert Path(result["snapshot_path"]).read_bytes() == before
    linked = receipt["hk_snapshot_capture"]
    assert linked["captured_at"] == NOW.isoformat()
    assert linked["snapshot_file_sha256"] == hashlib.sha256(before).hexdigest()
    assert linked["attempts"][0]["sha256"] == result["native_capture_attempts"][0]["sha256"]


@pytest.mark.parametrize("mode", ["partial", "exception", "parse", "late"])
def test_partial_exception_and_late_responses_preserve_diagnostics_only(tmp_path, monkeypatch, mode):
    rows = native_rows(CODES[:1]) if mode == "partial" else native_rows()
    if mode == "parse":
        monkeypatch.setattr(snapshot_module, "_safe_number", lambda *_: (_ for _ in ()).throw(ValueError("bad numeric")))
    ticks = iter([NOW, NOW, NOW, NOW.replace(minute=36)])
    result, original = capture(tmp_path, monkeypatch, rows=rows,
        error=ConnectionError("provider unavailable") if mode == "exception" else None,
        clock=(lambda: next(ticks, NOW.replace(minute=36))) if mode == "late" else None)
    assert result["status"] == "CANNOT_CONFIRM"
    assert not Path(result["snapshot_path"]).exists()
    event = json.loads(Path(result["native_capture_attempts"][0]["path"]).read_bytes())
    assert event["status"] == "CANNOT_CONFIRM"
    assert event["authorizes_selection"] is False
    if mode != "exception":
        assert_transport(result, original)
    else:
        assert "provider unavailable" in str(event["cannot_confirm"])
    assert snapshot_module.load_hk_active_snapshot(tmp_path, trade_date=DATE, stage_id=STAGE,
        codes=CODES, cutoff_at="09:35:05", pool_artifact_sha256=POOL_SHA)["status"] == "CANNOT_CONFIRM"


def test_original_good_snapshot_is_immutable_on_late_failed_retry(tmp_path, monkeypatch):
    first, _ = capture(tmp_path, monkeypatch)
    path = Path(first["snapshot_path"])
    before = path.read_bytes()
    second, _ = capture(tmp_path, monkeypatch, rows=[], error=RuntimeError("must not fetch"), clock=lambda: NOW.replace(hour=11))
    assert second["status"] == "NOOP_ALREADY_VERIFIED"
    assert path.read_bytes() == before


@pytest.mark.parametrize("field,value,reason", [
    ("trade_date", "20261022", "TRADE_DATE_MISMATCH"),
    ("market", "A_SHARE", "MARKET_MISMATCH"),
    ("codes", ["HK.00003"], "CODE_SET_MISMATCH"),
    ("pool_artifact_sha256", "b" * 64, "POOL_ARTIFACT_SHA_MISMATCH"),
])
def test_wrong_date_market_membership_still_rejected(tmp_path, monkeypatch, field, value, reason):
    result, _ = capture(tmp_path, monkeypatch)
    path = Path(result["snapshot_path"])
    payload = json.loads(path.read_bytes()); payload[field] = value
    path.write_text(json.dumps(payload))
    loaded = snapshot_module.load_hk_active_snapshot(tmp_path, trade_date=DATE, stage_id=STAGE,
        codes=CODES, cutoff_at="09:35:05", pool_artifact_sha256=POOL_SHA)
    assert loaded["status"] == "CANNOT_CONFIRM"
    assert any(reason in item for item in loaded["cannot_confirm"])


def test_unknown_universe_records_error_without_querying_arbitrary_codes(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    monkeypatch.setattr("stage_center.hk_stage8.precapture.resolve_market_states", runner_module.resolve_market_states)
    result = prepare_due_snapshot(cfg, DATE, NOW, stage_id=STAGE, historical_backfill=False,
        universe_loader=lambda: (_ for _ in ()).throw(RuntimeError("strict universe absent")),
        snapshot_preparer=lambda *_args, **_kwargs: pytest.fail("unknown universe queried"))
    attempt = json.loads(Path(result[0]["native_capture_attempts"][0]["path"]).read_bytes())
    assert attempt["scope_known"] is False
    assert attempt["requested_rows"] is None
    assert attempt["status"] == "CANNOT_CONFIRM"
    assert not snapshot_module._snapshot_path(cfg.raw_root, DATE, STAGE).exists()


def test_scorer_runtime_error_returns_receipt_with_native_sha(tmp_path, monkeypatch):
    cfg = config(tmp_path, builders={"HK_CONNECT": lambda *_: (_ for _ in ()).throw(RuntimeError("scorer failed"))})
    result, original = capture(cfg.raw_root, monkeypatch)
    before = Path(result["snapshot_path"]).read_bytes()
    candidate = SimpleNamespace(codes=CODES, current_sha256=POOL_SHA, run_id="frozen-input", source_evidence=())
    plan = SimpleNamespace(codes_for=lambda _: CODES)
    source = SourceResult("HK_CONNECT", "READY", rows=({"symbol": CODES[0]},), requested_rows=1)
    runner = runner_module.StageCenterRunner(cfg, collectors={"HK_CONNECT": lambda *_: source})
    monkeypatch.setattr(runner, "_existing_slot", lambda *_: ("MISSING", None))
    scope = dict(vars(runner_module))

    class FakeRawStore:
        def __init__(self, *_): pass
        def publish_bundle(self, **kwargs): return {"bundle_id": "test-bundle"}

    scope.update(
        _resolve_stage_market_scope=lambda *_args, **_kwargs: ("HK_CONNECT",),
        read_candidate_input=lambda *_args, **_kwargs: candidate,
        _validate_exact_selection_inputs=lambda *_args, **_kwargs: (),
        build_plan=lambda *_args, **_kwargs: plan,
        _with_candidate_evidence=lambda value, *_args, **_kwargs: value,
        _selection_source=lambda value, **_kwargs: value,
        _project_raw_rows=lambda rows, **_kwargs: rows,
        publish_raw_artifact=lambda *_args, **_kwargs: {"status": "READY", "artifact_sha256": "b" * 64},
        _attach_stage_research_roots=lambda *_args, **_kwargs: None,
        RawStore=FakeRawStore,
    )
    receipt = _StageCenterRunner__run_one_body(scope, runner,
        SimpleNamespace(trade_date=DATE, stage_id=STAGE, status="DUE"),
        historical_backfill=False, backfill_run_id=None, historical_markets=None)
    assert receipt["error"] == "scorer failed"
    assert receipt["status"] == "PARTIAL_COMMIT_RETRY_REQUIRED"
    assert receipt["hk_snapshot_capture"]["snapshot_file_sha256"] == hashlib.sha256(before).hexdigest()
    assert receipt["hk_snapshot_capture"]["captured_at"] == NOW.isoformat()
    assert Path(result["snapshot_path"]).read_bytes() == before
    assert_transport(result, original)
    persisted = json.loads(runner._receipt_path(DATE, STAGE).read_bytes())
    assert persisted["hk_snapshot_capture"] == receipt["hk_snapshot_capture"]


def test_missing_local_binding_uses_only_explicit_verified_shared_target_for_capture(tmp_path, monkeypatch):
    from dataclasses import replace
    from domains import preselection_materializer
    cfg = replace(config(tmp_path), hk_snapshot_shared_store_root=tmp_path / "existing-shared-store")
    runner = runner_module.StageCenterRunner(cfg)
    monkeypatch.setattr(runner_module, "_build_hk_stage_binding", lambda *_args, **_kwargs: (_ for _ in ()).throw(runner_module.RunnerError("missing local D1")))
    calls = []

    def shared_reader(store, **kwargs):
        calls.append((store, kwargs))
        return {"status": "STRICT_0_2_READY", "source_sha256": POOL_SHA, "source_run_id": "same-target-run",
                "source_path": "runs/exact/artifact.csv", "rows": [{"symbol": f"HK.{i:05d}"} for i in range(1, 101)]}

    monkeypatch.setattr(preselection_materializer, "build_shared_hk_0_2_pool", shared_reader)
    captures = []

    def preparer(*args, **kwargs):
        captures.append(kwargs)
        assert kwargs["capture_only"] is True
        assert kwargs["codes"] == tuple(f"HK.{i:05d}" for i in range(1, 101))
        assert kwargs["pool_artifact_sha256"] == POOL_SHA
        return {"status": "CANNOT_CONFIRM", "strict_active_eligibility": False}

    monkeypatch.setattr("stage_center.hk_stage8.prepare_hk_active_snapshot", preparer)
    result = runner._prepare_hk_active_snapshots(DATE, NOW, stage_id=STAGE)
    assert len(captures) == len(calls) == 1
    assert calls[0][0] == cfg.hk_snapshot_shared_store_root
    assert calls[0][1]["trade_date"] == DATE
    assert calls[0][1]["signal_date"] == "20261022"
    assert result[0]["strict_active_eligibility"] is False
    assert "CAPTURE_ONLY_SHARED_VERIFIED_D1" in str(result[0]["source_evidence"])


def test_capture_only_shared_membership_never_publishes_strict_active_index(tmp_path, monkeypatch):
    # Exercise real serialization/probe rather than the binding-loader seam.
    saved = snapshot_module.prepare_hk_active_snapshot
    def capture_only(*args, **kwargs):
        kwargs["capture_only"] = True
        return saved(*args, **kwargs)
    monkeypatch.setattr(snapshot_module, "prepare_hk_active_snapshot", capture_only)
    result, original = capture(tmp_path, monkeypatch)
    assert result["status"] == "CANNOT_CONFIRM"
    assert result["strict_active_eligibility"] is False
    assert not Path(result["snapshot_path"]).exists()
    event = assert_transport(result, original)
    assert event["status"] == "CAPTURED_DIAGNOSTIC"


def test_timeout_partial_native_bytes_are_retained(tmp_path, monkeypatch):
    partial = b'{"rows":[{"code":"HK.00001"'
    error = subprocess.TimeoutExpired("fake-native", 1, output=partial, stderr=b"timeout")
    result, _ = capture(tmp_path, monkeypatch, error=error)
    assert result["status"] == "CANNOT_CONFIRM"
    event = json.loads(Path(result["native_capture_attempts"][0]["path"]).read_bytes())
    ref = next(x for x in event["payload_events"] if x["event"].startswith("provider-error-"))
    stored = json.loads(Path(ref["path"]).read_bytes())
    assert base64.b64decode(stored["output_base64"]) == partial
    assert stored["output_sha256"] == hashlib.sha256(partial).hexdigest()
    assert not Path(result["snapshot_path"]).exists()


def test_partial_failure_does_not_block_later_valid_attempt(tmp_path, monkeypatch):
    first, _ = capture(tmp_path, monkeypatch, rows=native_rows(CODES[:1]))
    second, _ = capture(tmp_path, monkeypatch)
    assert first["status"] == "CANNOT_CONFIRM"
    assert second["status"] == "READY"
    assert len(list(Path(second["snapshot_path"]).parent.glob("attempts/*/result.json"))) == 2
    assert Path(first["native_capture_attempts"][0]["path"]).is_file()


def test_a_0925_receipt_has_no_hk_snapshot_metadata(tmp_path):
    runner = runner_module.StageCenterRunner(config(tmp_path))
    receipt = runner._write_receipt({"status": "READY", "markets": {"A_SHARE": {"status": "READY"}}}, DATE, "STAGE_0925")
    assert receipt["status"] == "READY"
    assert "hk_snapshot_capture" not in receipt
    assert all(receipt[key] is False for key in SAFETY_FLAGS)
