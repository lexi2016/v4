"""Synthetic lifecycle explanations only; no production panels or providers."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "apps/api/v35_api/a_share_panel_history.py"
spec = importlib.util.spec_from_file_location("lifecycle_history_under_test", SOURCE)
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


@pytest.fixture
def asset(tmp_path, monkeypatch):
    # Both the fact and provenance below are synthetic, never runtime authority.
    value = {
        "schema_version": "a_share_lifecycle_notes.v1",
        "accepted_facts_ref": {"path": "synthetic_acceptance.json", "sha256": "a" * 64},
        "verified_delistings": [{
            "ts_code": "000004.SZ", "delisting_effective_date": "20260101", "verified": True,
            "official_source_refs": [{"url": "https://example.invalid/synthetic", "sha256": None,
                                      "sha256_reason": "SYNTHETIC_FIXTURE"}],
            "accepted_review_ref": {"path": "synthetic_review.json", "sha256": "b" * 64},
        }],
    }
    value["verified_delistings"].append({
        **value["verified_delistings"][0], "ts_code": "600193.SH", "verified": False,
    })
    path = tmp_path / "a_share_lifecycle_notes.json"
    def write(candidate=value):
        raw = json.dumps(candidate, ensure_ascii=False, sort_keys=True).encode()
        path.write_bytes(raw)
        monkeypatch.setattr(h, "LIFECYCLE_NOTES_SHA256", hashlib.sha256(raw).hexdigest())
    write()
    monkeypatch.setattr(h, "__file__", str(tmp_path / "history.py"))
    return path, value, write


def response(**changes):
    result = dict(status="CANNOT_CONFIRM", rows=[], ts_code="000004.SZ",
                  start_date="20261019", end_date="20261023",
                  cannot_confirm=["ORIGINAL_QUARANTINE:FACTOR_SOURCE_ERROR", "SECOND_ORIGINAL_REASON"],
                  identity={"generation_id": "unchanged"}, research_only=True,
                  production_allowed=False, buy_gate_updated=False, orders_sent=False)
    return {**result, **changes}


def test_verified_post_delisting_appends_one_note_preserving_every_original_field(asset):
    original = response()
    before = deepcopy(original)
    result = h._with_lifecycle_note(original)
    assert original == before
    assert {**result, "cannot_confirm": original["cannot_confirm"]} == original
    assert result["cannot_confirm"][:-1] == original["cannot_confirm"]
    assert "官方摘牌日期：2026-01-01" in result["cannot_confirm"][-1]
    assert "无需补上市交易K线" in result["cannot_confirm"][-1]
    assert "存量记录，发生日期未确认" in result["cannot_confirm"][-1]


@pytest.mark.parametrize("changes", [
    {"ts_code": "600193.SH"},
    {"start_date": "20251201", "end_date": "20251231"},
    {"start_date": "20251231", "end_date": "20260102"},
    {"status": "READY", "rows": [{"close": 1}]},
    {"status": "EMPTY_EXACT_RANGE"},
    {"rows": [{"close": 1}]},
])
def test_unknown_pre_delisting_crossing_ready_and_empty_are_unchanged(asset, changes):
    original = response(**changes)
    assert h._with_lifecycle_note(original) is original


def test_effective_date_is_first_delisted_day(asset):
    result = h._with_lifecycle_note(response(start_date="20260101", end_date="20260101"))
    assert len(result["cannot_confirm"]) == 3


@pytest.mark.parametrize("reason", ["PRODUCER_MANIFEST_IDENTITY_CONFLICT", "DEFAULT_ARTIFACT_CHANGED_DURING_READ",
                                  "SHARED_DATA_ROOT_NOT_CONFIGURED", "reader import failed"])
def test_realtime_failures_are_not_called_legacy_errors(asset, reason):
    original = response(cannot_confirm=[reason])
    result = h._with_lifecycle_note(original)
    assert result["cannot_confirm"][0] == reason
    assert result["status"] == "CANNOT_CONFIRM"
    assert "官方摘牌日期" in result["cannot_confirm"][-1]
    assert "存量" not in result["cannot_confirm"][-1]


@pytest.mark.parametrize("failure", ["missing", "bad_sha", "bad_json", "bad_date", "duplicate", "bad_schema"])
def test_bad_explanation_asset_never_hides_original_identity_refusal(asset, failure):
    path, value, write = asset
    if failure == "missing":
        path.unlink()
    elif failure == "bad_sha":
        path.write_bytes(b"changed")
    elif failure == "bad_json":
        path.write_bytes(b"{")
        h.LIFECYCLE_NOTES_SHA256 = hashlib.sha256(b"{").hexdigest()
    else:
        candidate = deepcopy(value)
        if failure == "bad_date":
            candidate["verified_delistings"][0]["delisting_effective_date"] = "20260230"
        elif failure == "duplicate":
            candidate["verified_delistings"] *= 2
        else:
            candidate["schema_version"] = "unknown"
        write(candidate)
    original = response(cannot_confirm=["DEFAULT_POINTER_ACCEPTANCE_CONFLICT"])
    assert h._with_lifecycle_note(original) is original


def test_api_failure_path_appends_without_touching_original_status_or_request_gate(asset, tmp_path, monkeypatch):
    def fail(_cache):
        raise h.Unconfirmed("PRODUCER_MANIFEST_IDENTITY_CONFLICT")
    monkeypatch.setattr(h, "_read_lock", fail)
    result = h.read_history(tmp_path, "000004.SZ", "20261019", "20261023", h.VERSION)
    assert result["status"] == "CANNOT_CONFIRM" and result["rows"] == []
    assert result["cannot_confirm"][0] == "PRODUCER_MANIFEST_IDENTITY_CONFLICT"
    assert len(result["cannot_confirm"]) == 2
    assert "存量" not in result["cannot_confirm"][-1]
    with pytest.raises(ValueError, match="ts_code"):
        h.read_history(None, "unknown", "20261019", "20261023", h.VERSION)


def test_unconfigured_root_api_failure_remains_a_current_technical_refusal(asset):
    result = h.read_history(None, "000004.SZ", "20261019", "20261023", h.VERSION)
    assert result["status"] == "CANNOT_CONFIRM" and result["rows"] == []
    assert result["cannot_confirm"][0] == "SHARED_DATA_ROOT_NOT_CONFIGURED"
    assert "存量" not in result["cannot_confirm"][-1]
