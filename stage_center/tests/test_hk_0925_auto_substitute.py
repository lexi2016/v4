from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import stage_center.hk_0925_auto_substitute as substitute
import stage_center.selection as selection


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _event(date: str = "20260924", at: str = "09:35:05"):
    return datetime.fromisoformat(f"{date}T{at}:00+08:00") if len(at) == 5 else datetime.fromisoformat(f"{date}T{at}+08:00")


def test_scheduled_entry_before_source_cutoff_does_not_publish(tmp_path):
    outcome = substitute.maybe_publish_0925_substitute(
        {"raw_root": str(tmp_path / "raw"), "selection_root": str(tmp_path / "selection"), "receipt_root": str(tmp_path / "receipts")},
        "20260924",
        datetime(2026, 9, 24, 9, 35, 4, tzinfo=SHANGHAI),
        {"trade_date": "20260924", "stage_id": "STAGE_0930_0935"},
    )
    assert outcome["status"] == "SKIPPED"
    assert outcome["first_failed_layer"] == "AUTOMATIC_0930_ENTRY_BEFORE_SOURCE_CUTOFF"
    assert outcome["write_performed"] is False


def test_missing_minute_raw_returns_specific_wait_without_writing(tmp_path, monkeypatch):
    codes = tuple(f"HK.{number:05d}" for number in range(100))
    binding = SimpleNamespace(status="READY", market="HK_CONNECT", trade_date="20260924", role="HK_CONNECT_D1_TOP100", codes=codes, sha256="a" * 64)
    monkeypatch.setattr(substitute, "_build_hk_stage_binding", lambda *_args, **_kwargs: binding)
    monkeypatch.setattr(substitute, "_latest_entry", lambda _root, _file, key: None)
    outcome = substitute.maybe_publish_0925_substitute(
        {"raw_root": str(tmp_path / "raw"), "selection_root": str(tmp_path / "selection"), "receipt_root": str(tmp_path / "receipts"), "hk_d1_root": str(tmp_path / "d1")},
        "20260924",
        _event(),
        {"trade_date": "20260924", "stage_id": "STAGE_0930_0935"},
    )
    assert outcome["status"] == "WAITING_MINUTE_DATA"
    assert outcome["first_failed_layer"] == "HK_0930_0935_MINUTE_RAW_MISSING"
    assert outcome["write_performed"] is False


def test_existing_verified_auction_raw_wins_without_selection_write(tmp_path, monkeypatch):
    class VerifiedRawStore:
        def __init__(self, _root):
            pass

        def verify_run(self, *_args):
            return {"run_id": "auction-run"}

    monkeypatch.setattr(substitute, "RawStore", VerifiedRawStore)
    monkeypatch.setattr(substitute, "_latest_entry", lambda *_args: {"run_id": "auction-run"})
    outcome = substitute.maybe_publish_0925_substitute(
        {"raw_root": str(tmp_path / "raw"), "selection_root": str(tmp_path / "selection"), "receipt_root": str(tmp_path / "receipts")},
        "20260924",
        _event(),
        {"trade_date": "20260924", "stage_id": "STAGE_0930_0935"},
    )
    assert outcome["status"] == "SKIPPED_AUCTION_PRESENT"
    assert outcome["source_raw_run_id"] == "auction-run"
    assert outcome["write_performed"] is False


def test_minute_validator_preserves_mixed_missing_codes_and_rejects_late_bar():
    membership = {f"HK.{number:05d}" for number in range(100)}
    rows = (
        {"code": "HK.00000", "update_time": "2026-09-24 09:35:00", "temporal_cutoff_safe": True},
        {"code": "HK.00001", "update_time": "2026-09-24 09:35:00", "temporal_cutoff_safe": True},
    )
    verified = {"trade_date": "20260924", "stage_id": "STAGE_0930_0935", "market": "HK_CONNECT", "window": "09:30-09:35", "cutoff_at": "09:35:05", "status": "PARTIAL_WITH_ROWS"}
    valid, failure, last_bar = substitute._validate_minute_rows("20260924", verified, SimpleNamespace(rows=rows, requested_rows=100), membership)
    assert valid is True
    assert failure is None
    assert last_bar == "2026-09-24 09:35:00"
    too_late = ({**rows[0], "update_time": "2026-09-24 09:35:06"}, *rows[1:])
    valid, failure, _ = substitute._validate_minute_rows("20260924", verified, SimpleNamespace(rows=too_late, requested_rows=100), membership)
    assert valid is False
    assert failure == "HK_0930_RAW_BAR_OUTSIDE_SOURCE_CUTOFF"


def test_missing_receipt_is_eligible_but_open_receipt_is_not(tmp_path):
    root = Path(tmp_path)
    assert substitute._receipt_expired(root, "20260924") == (True, "MISSING")
    receipt = root / "20260924" / "STAGE_0925" / "receipt.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text('{"trade_date":"20260924","stage_id":"STAGE_0925","status":"READY"}', encoding="utf-8")
    assert substitute._receipt_expired(root, "20260924") == (False, "NOT_EXPIRED")


def _publish_selection(root: Path, *, source_status: str, rows: list[dict], input_rows: int | None = None, cannot_confirm: tuple[str, ...] = (), source_evidence: tuple[str, ...] = ()):
    store = selection.SelectionStore(root)
    envelope = selection._selection_envelope(
        trade_date="20260924",
        stage_id="STAGE_0925",
        market="HK_CONNECT",
        raw_artifact_sha256="a" * 64,
        source_status=source_status,
        input_rows=len(rows) if input_rows is None else input_rows,
        rows=rows,
        requested_rows=100,
        missing_symbols=(),
        cannot_confirm=cannot_confirm,
        source_evidence=source_evidence,
        algorithm_sha256=selection.ALGORITHM_SHA256,
    )
    store.publish(envelope, market="HK_CONNECT")
    return store.read_verified("20260924", "STAGE_0925", "HK_CONNECT")


def test_verified_healthy_auction_selection_is_preserved_without_raw(tmp_path):
    selection_root = tmp_path / "selection"
    original = _publish_selection(
        selection_root,
        source_status="READY",
        rows=[{"code": "HK.00068", "source_mode": "HK_CONNECT_AUCTION_SECOND_FILTER_STAGE_0925"}],
        input_rows=100,
        source_evidence=("route=hk_connect_0915_0920_auction_second_filter",),
    )
    latest_path = selection_root / "selection_latest.json"
    before = latest_path.read_bytes()
    outcome = substitute.maybe_publish_0925_substitute(
        {"raw_root": str(tmp_path / "raw"), "selection_root": str(selection_root), "receipt_root": str(tmp_path / "receipts")},
        "20260924",
        _event(),
        {"trade_date": "20260924", "stage_id": "STAGE_0930_0935"},
    )
    after = selection.SelectionStore(selection_root).read_verified("20260924", "STAGE_0925", "HK_CONNECT")
    assert outcome["status"] == "SKIPPED_AUCTION_PRESENT"
    assert outcome["source_selection_run_id"] == original["run_id"]
    assert after["run_id"] == original["run_id"]
    assert latest_path.read_bytes() == before


def test_verified_ready_empty_auction_selection_is_preserved_without_raw(tmp_path):
    selection_root = tmp_path / "selection"
    original = _publish_selection(
        selection_root,
        source_status="READY",
        rows=[],
        input_rows=100,
        source_evidence=("route=hk_connect_0915_0920_auction_second_filter", "auction_capture_status=READY"),
    )
    assert original["selection_status"] == "READY_EMPTY"
    latest_path = selection_root / "selection_latest.json"
    before = latest_path.read_bytes()
    outcome = substitute.maybe_publish_0925_substitute(
        {"raw_root": str(tmp_path / "raw"), "selection_root": str(selection_root), "receipt_root": str(tmp_path / "receipts")},
        "20260924",
        _event(),
        {"trade_date": "20260924", "stage_id": "STAGE_0930_0935"},
    )
    after = selection.SelectionStore(selection_root).read_verified("20260924", "STAGE_0925", "HK_CONNECT")
    assert outcome["status"] == "SKIPPED_AUCTION_PRESENT"
    assert outcome["source_selection_run_id"] == original["run_id"]
    assert after["run_id"] == original["run_id"]
    assert latest_path.read_bytes() == before


def test_expired_verified_zero_row_cannot_confirm_slot_is_substituted_with_prior_provenance(tmp_path, monkeypatch):
    date = "20260924"
    raw_root = tmp_path / "raw"
    selection_root = tmp_path / "selection"
    receipt_root = tmp_path / "receipts"
    original = _publish_selection(
        selection_root,
        source_status="CANNOT_CONFIRM",
        rows=[],
        cannot_confirm=("HK_0920_AUCTION_RAW_MISSING",),
        source_evidence=("route=hk_connect_0915_0920_auction_second_filter", "auction_capture_status=CANNOT_CONFIRM"),
    )
    receipt = receipt_root / date / "STAGE_0925" / "receipt.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({"trade_date": date, "stage_id": "STAGE_0925", "status": "CANNOT_CONFIRM", "retry_exhausted": True}), encoding="utf-8")

    codes = tuple(f"HK.{number:05d}" for number in range(100))
    d1_sha = "a" * 64
    binding = SimpleNamespace(status="READY", market="HK_CONNECT", trade_date=date, role="HK_CONNECT_D1_TOP100", codes=codes, sha256=d1_sha)
    missing = tuple(code for code in codes if code != codes[0])
    source = SimpleNamespace(
        rows=({"code": codes[0], "update_time": "2026-09-24 09:35:00", "temporal_cutoff_safe": False},),
        requested_rows=100,
        missing_symbols=missing,
        cannot_confirm=(),
    )
    algorithm_sha = selection.ALGORITHM_SHA256
    verified = {
        "trade_date": date,
        "stage_id": "STAGE_0930_0935",
        "market": "HK_CONNECT",
        "window": "09:30-09:35",
        "cutoff_at": "09:35:05",
        "status": "PARTIAL_WITH_ROWS",
        "run_id": "minute-run",
        "artifact_sha256": "b" * 64,
        "manifest_sha256": "c" * 64,
        "receipt_sha256": "d" * 64,
        "source_evidence": [f"candidate_current_sha256={d1_sha}", "active_snapshot_temporal_cutoff_safe=false"],
    }

    class VerifiedRawStore:
        def __init__(self, _root):
            pass

        def verify_run(self, *_args):
            return verified

    monkeypatch.setattr(substitute, "RawStore", VerifiedRawStore)
    monkeypatch.setattr(substitute, "_build_hk_stage_binding", lambda *_args, **_kwargs: binding)
    monkeypatch.setattr(
        substitute,
        "_latest_entry",
        lambda _root, _file, key: None if key == f"{date}/STAGE_0925/HK_CONNECT" else {"run_id": "minute-run"},
    )
    monkeypatch.setattr(substitute, "_read_verified_raw_source", lambda *_args: source)
    monkeypatch.setattr(substitute, "_attach_hk_authority", lambda value, **_kwargs: value)
    monkeypatch.setattr(substitute, "_selection_source", lambda value, **_kwargs: value)

    def build_rows(_source, _context, _manifest):
        return {
            "selection_status": "PARTIAL_WITH_ROWS",
            "rows": [{"code": codes[0], "rank": 1, "score": 60}],
            "cannot_confirm": [],
            "source_evidence": ["route=existing_0930_selector"],
            "algorithm_sha256": algorithm_sha,
        }

    monkeypatch.setattr(substitute, "production_selection_builders", lambda _stage: {"HK_CONNECT": build_rows})
    outcome = substitute.maybe_publish_0925_substitute(
        {"raw_root": str(raw_root), "selection_root": str(selection_root), "receipt_root": str(receipt_root), "hk_d1_root": str(tmp_path / "d1")},
        date,
        _event(),
        {"trade_date": date, "stage_id": "STAGE_0930_0935"},
    )
    after = selection.SelectionStore(selection_root).read_verified(date, "STAGE_0925", "HK_CONNECT")
    evidence = set(after["source_evidence"])
    assert outcome["status"] == "PARTIAL_WITH_ROWS", outcome
    assert outcome["write_performed"] is True
    assert after["run_id"] != original["run_id"]
    assert f"prior_0925_selection_run_id={original['run_id']}" in evidence
    assert "prior_0925_selection_selection_status=CANNOT_CONFIRM" in evidence
    assert "prior_0925_selection_cannot_confirm=HK_0920_AUCTION_RAW_MISSING" in evidence
    assert "prior_0925_selection_source_evidence=auction_capture_status=CANNOT_CONFIRM" in evidence
    assert (selection_root / "selection_runs" / date / "HK_CONNECT_SELECTION_STAGE_0925" / original["run_id"]).is_dir()
