"""Missing source/PIT marker regression; every record is synthetic fixture data."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from harness import before_producer, historical_fixture
from domains.close_review import close_review
from infrastructure.hkconnect_close_store import CloseSnapshotStore
from infrastructure.preselection_pool_store import PreselectionPoolStore
from infrastructure.review_store import ReviewStore, validate_close_review_reference
from ops.build_close_review import build_close_review


REASON = "HK_MODEL_SOURCE_PIT_AVAILABILITY_CANNOT_CONFIRM"
DATE = "20260825"
SOURCE_PAIR = ("source_manifest_sha256", "source_receipt_sha256")


def snapshot_payload(date):
    return {
        "schema_version": "v3_5.hkconnect_close_snapshot.v1", "trade_date": date,
        "status": "READY", "source_mode": "SYNTHETIC_TEST_ONLY",
        "source_input_sha256": "a" * 64, "universe_count": 600,
        "same_date_row_count": 600, "coverage_ratio": 1.0,
        "rows": [{"trade_date": date, "code": f"HK.{index:05d}",
                  "name": f"Fixture {index}", "close": 100 + index,
                  "pre_close": 100, "amount": index}
                 for index in range(1, 601)],
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    }


def pool_payload(date=DATE, *, omit=()):
    pool = {
        "schema_version": "v3_5.preselection_pool.v1", "trade_date": date,
        "pool_id": "hkconnect_d1_top100", "display_name": "Synthetic HK fixture",
        "market": "HK", "status": "STRICT_0_2_READY", "producer_id": "verified.fixture",
        "source_role": "SHARED_VERIFIED_HK_0_2", "source_path": "fixture/hk.json",
        "source_sha256": "b" * 64, "source_manifest_sha256": "c" * 64,
        "source_receipt_sha256": "d" * 64,
        "rows": [{"market": "HK", "symbol": f"HK.{index:05d}",
                  "pool_id": "hkconnect_d1_top100", "pool_rank": index,
                  "target_date": date} for index in range(1, 101)],
        "cannot_confirm": [], "production_allowed": False,
        "buy_gate_updated": False, "orders_sent": False,
    }
    for key in omit:
        del pool[key]
    return pool


def seed(root, pool=None, date=DATE):
    CloseSnapshotStore(root).import_snapshot(snapshot_payload(date))
    if pool is not None:
        PreselectionPoolStore(root).materialize(pool)


def files_under(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file() and not path.name.startswith(".")}


def source_files(root):
    return {name: value for name, value in files_under(root).items()
            if name.startswith(("preselection_pools/", "receipts/preselection_pools/",
                                "hkconnect_close_snapshots/", "receipts/hkconnect_close_snapshots/"))}


def assert_unchanged_review_contract(root, result, date=DATE, *, model_count=100):
    review = result["review"]
    assert ReviewStore(root).read_reference(date) == review
    assert validate_close_review_reference(review) == date
    assert review["schema_version"] == "v3_5.close_review.v1"
    assert review["status"] == ("MODEL_REVIEW_PARTIAL_STAGE_EVIDENCE" if model_count else "MODEL_0_2_SOURCE_MISSING")
    assert review["row_counts"] == {"hkconnect_universe": 600, "close_top20": 20,
                                     "model_0_2": model_count, "stage_rows": 0}
    assert [row["code"] for row in review["model_rows"]] == [f"HK.{index:05d}" for index in range(1, model_count + 1)]
    assert len(review["missing_stages"]) == 7
    assert all(review[flag] is False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
    assert review["reference_snapshot"] is False
    assert "historical_provenance" not in review
    assert "captured_at" not in review


@pytest.mark.parametrize("date", [DATE, "20260826"])
@pytest.mark.parametrize("missing", [SOURCE_PAIR[:1], SOURCE_PAIR[1:], SOURCE_PAIR],
                         ids=["manifest-only", "receipt-only", "both"])
def test_missing_source_pair_retains_pit_uncertainty_in_stored_review(tmp_path, date, missing):
    """Dropping the marker for source-identity gaps recreates the documented P2."""
    pool = pool_payload(date, omit=missing)
    original_pool = copy.deepcopy(pool)
    seed(tmp_path, pool, date)
    input_bytes = source_files(tmp_path)
    result = build_close_review(tmp_path, date)
    assert_unchanged_review_contract(tmp_path, result, date)
    assert source_files(tmp_path) == input_bytes
    assert PreselectionPoolStore(tmp_path).read_pool(date, "hkconnect_d1_top100") == original_pool
    assert result["review"]["cannot_confirm"].count(REASON) == 1


def test_complete_nonhistorical_source_pair_preserves_baseline_output(tmp_path):
    """A complete pair without historical provenance must not gain a new warning."""
    seed(tmp_path / "baseline", pool_payload())
    seed(tmp_path / "candidate", pool_payload())
    original = before_producer().build_close_review(tmp_path / "baseline", DATE)
    candidate = build_close_review(tmp_path / "candidate", DATE)
    assert_unchanged_review_contract(tmp_path / "candidate", candidate)
    assert candidate["review"] == original["review"]
    assert REASON not in candidate["review"]["cannot_confirm"]


def test_exact_absent_pool_sentinel_keeps_missing_model_status_and_adds_pit_reason(tmp_path):
    """Missing source is explicit; no empty model is upgraded to a valid review."""
    seed(tmp_path)
    result = build_close_review(tmp_path, DATE)
    assert_unchanged_review_contract(tmp_path, result, model_count=0)
    assert "MODEL_0_2_TOP100_NOT_READY:0/100" in result["review"]["cannot_confirm"]
    assert result["review"]["cannot_confirm"].count(REASON) == 1


def test_existing_historical_provenance_reason_is_preserved(tmp_path):
    """The original historical warning must survive the new missing-field branch."""
    pool = historical_fixture()
    date = pool["trade_date"]
    seed(tmp_path, pool, date)
    source = source_files(tmp_path)
    result = build_close_review(tmp_path, date)
    assert_unchanged_review_contract(tmp_path, result, date)
    assert result["review"]["cannot_confirm"].count(REASON) == 1
    assert source_files(tmp_path) == source


@pytest.mark.parametrize("damage", ["missing-receipt", "corrupt-receipt", "missing-manifest"])
def test_pool_native_trio_damage_propagates_without_publishing_review(tmp_path, damage):
    """The warning must not turn missing/corrupt native evidence into an empty pool."""
    seed(tmp_path, pool_payload())
    store = PreselectionPoolStore(tmp_path)
    _, receipt = store._relative(DATE, "hkconnect_d1_top100")
    target = tmp_path / (f"preselection_pools/{DATE}/manifest.json" if damage == "missing-manifest" else receipt)
    if damage == "corrupt-receipt":
        target.write_text("not-json")
    else:
        target.unlink()
    damaged_before = files_under(tmp_path)
    with pytest.raises((FileNotFoundError, ValueError)):
        build_close_review(tmp_path, DATE)
    assert not (tmp_path / "close_reviews" / f"{DATE}.json").exists()
    assert files_under(tmp_path) == damaged_before


def test_prior_saved_output_and_receipt_are_unchanged_by_readback(tmp_path):
    """Candidate code must not retrofit newly classified uncertainty into old bytes."""
    seed(tmp_path, pool_payload(omit=SOURCE_PAIR))
    previous = before_producer().build_close_review(tmp_path, DATE)["review"]
    prior_bytes = files_under(tmp_path)
    assert REASON not in previous["cannot_confirm"]
    served = close_review(ReviewStore(tmp_path), DATE)
    assert served["market_reviews"]["HK"]["model_selection_review"] == previous
    assert files_under(tmp_path) == prior_bytes


def test_new_missing_source_output_differs_only_by_existing_warning(tmp_path):
    """Adding the marker must leave model inputs, KPIs, status and schema intact."""
    for name in ("baseline", "candidate"):
        seed(tmp_path / name, pool_payload(omit=SOURCE_PAIR))
    baseline = before_producer().build_close_review(tmp_path / "baseline", DATE)["review"]
    candidate = build_close_review(tmp_path / "candidate", DATE)["review"]
    assert candidate["cannot_confirm"].count(REASON) == 1
    expected = copy.deepcopy(baseline)
    expected["cannot_confirm"].append(REASON)
    assert candidate == expected
