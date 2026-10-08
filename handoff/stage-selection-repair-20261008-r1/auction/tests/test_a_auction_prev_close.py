"""Synthetic regression tests for the real selection adapter and persistence.

In a complete owner tree these imports need no harness. In this handoff run,
the separately logged historic-support harness supplies missing dependencies;
that run is not validation of the complete active Stage application.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from stage_center.acquisition import AcquisitionPlan, SourceResult
from stage_center.candidate_input import CandidateInput
from stage_center.consumer import StageSelectionConsumer
from stage_center.live_collectors import production_selection_builders
from stage_center.selection import (
    SelectionError,
    SelectionStore,
    SELECTION_ARTIFACT_FIELDS_V1,
    SELECTION_ARTIFACT_FIELDS_V2,
    _artifact_rows,
    _decode_artifact_rows,
    select_a_0925_auction,
)


DATE = "20261008"
STAGE = "STAGE_0925"
RAW_SHA = hashlib.sha256(b"synthetic auction fixture; no business data").hexdigest()
OMIT = object()
LEGACY_HEADER = (
    "code", "score", "rank", "status", "formal_eligible", "support",
    "pressure", "invalidation", "source_mode", "lane_evidence",
    "action_level", "trade_status",
)


def auction_row(*, code="A.000101", previous=100, price=105):
    row = {
        "code": code, "name": "Synthetic auction case", "batch_index": 1,
        "open_price": price, "last_price": price,
        "high_price": price, "low_price": price,
        "update_time": "2026-10-08 09:25:00", "turnover": 10_000_000,
        "trade_date": DATE,
    }
    if previous is not OMIT:
        row["prev_close_price"] = previous
    return row


def through_adapter(rows):
    candidate = CandidateInput(
        root=Path("/nonexistent/synthetic-fixture"), trade_date=DATE,
        current_relative="synthetic/current.json", current_sha256=RAW_SHA,
        run_id="synthetic-only", codes=tuple(row["code"] for row in rows),
        artifact_sha256=RAW_SHA, manifest_sha256=RAW_SHA,
        receipt_sha256=RAW_SHA, source_projection_sha256=RAW_SHA,
        source_evidence=("SYNTHETIC_TEST_ONLY",),
    )
    plan = AcquisitionPlan(
        trade_date=DATE, stage_id=STAGE, markets=("A_SHARE",),
        candidate_input=candidate,
        a_share_route="a_share_exact_date_auction_transaction",
        hk_route="hk_connect_0915_0920_auction_second_filter",
    )
    source = SourceResult(
        source_id="synthetic-fixture", status="READY", rows=tuple(rows),
        requested_rows=len(rows), source_evidence=("SYNTHETIC_TEST_ONLY",),
    )
    raw = {
        "artifact_sha256": RAW_SHA, "status": "READY",
        "requested_rows": len(rows), "missing_symbols": [],
        "cannot_confirm": [], "source_evidence": ["SYNTHETIC_TEST_ONLY"],
        "cutoff_at": "2026-10-08 09:25:05",
    }
    return production_selection_builders(STAGE)["A_SHARE"](source, plan, raw)


def publish_and_read(tmp_path, envelope):
    root = tmp_path / "synthetic-selection"
    store = SelectionStore(root)
    published = store.publish(envelope, market="A_SHARE")
    verified = store.read_verified(DATE, STAGE, "A_SHARE")
    assert verified == published
    consumer = StageSelectionConsumer(root)
    response = consumer.get(DATE, STAGE, markets=("A_SHARE",))
    assert response["write_performed"] is False
    for flag in ("production_allowed", "buy_gate_updated", "orders_sent"):
        assert response[flag] is False
        assert verified[flag] is False
    return verified, response, store


def test_auction_previous_close_survives_real_adapter_and_verified_persistence(tmp_path):
    envelope = through_adapter([auction_row(previous=100, price=105)])
    verified, response, store = publish_and_read(tmp_path, envelope)
    for row in (envelope["rows"][0], verified["rows"][0], response["markets"]["A_SHARE"]["rows"][0]):
        assert row["prev_close_price"] == 100
        assert row["current_change_pct"] == 5
        assert row["qmt_gap_pct"] == 5
        assert row.get("current_change_pct_missing_reason") is None
        assert row["score"] == 100
        assert row["action_level"] == "NO_BUY"
        assert row["trade_status"] == "WATCH_ONLY"
    # The persisted CSV remains readable by immutable legacy consumers;
    # the verified manifest/receipt envelope carries the full price evidence.
    artifact = next(store.root.rglob("artifact.csv"))
    with artifact.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        assert tuple(reader.fieldnames) == LEGACY_HEADER
        decoded = _decode_artifact_rows(list(reader), fields=LEGACY_HEADER)
    assert decoded[0]["current_change_pct"] is None


@pytest.mark.parametrize("previous,reason", [
    (OMIT, "PREV_CLOSE_PRICE_MISSING"),
    (None, "PREV_CLOSE_PRICE_MISSING"),
    ("", "PREV_CLOSE_PRICE_MISSING"),
    (0, "PREV_CLOSE_PRICE_INVALID"),
    (-100, "PREV_CLOSE_PRICE_INVALID"),
    ("not-a-price", "PREV_CLOSE_PRICE_INVALID"),
    (float("nan"), "PREV_CLOSE_PRICE_INVALID"),
    (float("inf"), "PREV_CLOSE_PRICE_INVALID"),
    (True, "PREV_CLOSE_PRICE_INVALID"),
], ids=["absent", "null", "empty", "zero", "negative", "text", "nan", "infinity", "boolean"])
def test_missing_or_invalid_baseline_is_null_with_a_specific_reason(tmp_path, previous, reason):
    envelope = through_adapter([auction_row(previous=previous)])
    verified, response, store = publish_and_read(tmp_path, envelope)
    for row in (envelope["rows"][0], verified["rows"][0], response["markets"]["A_SHARE"]["rows"][0]):
        assert row["prev_close_price"] is None
        assert row["current_change_pct"] is None
        assert row["qmt_gap_pct"] is None
        assert row["current_change_pct_missing_reason"] == reason
        assert f"current_change_pct_missing_reason={reason}" in row["lane_evidence"]
        assert row["score"] == 50.25  # Existing neutral gap scoring fallback.
    with next(store.root.rglob("artifact.csv")).open(newline="", encoding="utf-8-sig") as stream:
        decoded = _decode_artifact_rows(list(csv.DictReader(stream)), fields=LEGACY_HEADER)
    assert f"current_change_pct_missing_reason={reason}" in decoded[0]["lane_evidence"]


def test_actual_flat_auction_keeps_an_observed_zero(tmp_path):
    envelope = through_adapter([auction_row(previous=100, price=100)])
    verified, response, _ = publish_and_read(tmp_path, envelope)
    row = response["markets"]["A_SHARE"]["rows"][0]
    assert row["prev_close_price"] == 100
    assert row["current_change_pct"] == row["qmt_gap_pct"] == 0
    assert row.get("current_change_pct_missing_reason") is None
    assert row["score"] == 50.25


def test_auction_change_uses_auction_price_even_when_last_differs():
    row = auction_row(previous=100, price=105)
    row["last_price"] = 106
    selected = select_a_0925_auction([row], DATE, RAW_SHA)["rows"][0]
    assert selected["current_change_pct"] == 5
    assert selected["last_price"] == 106


def test_direct_selector_rejects_nonpositive_baseline_for_price_semantics():
    row = auction_row(previous=-100, price=105)
    selected = select_a_0925_auction([row], DATE, RAW_SHA)["rows"][0]
    assert selected["prev_close_price"] is None
    assert selected["current_change_pct"] is None
    assert selected["current_change_pct_missing_reason"] == "PREV_CLOSE_PRICE_INVALID"


def test_missing_auction_price_is_not_mislabeled_as_missing_previous_close(tmp_path):
    envelope = through_adapter([auction_row(previous=100, price=None)])
    _, response, _ = publish_and_read(tmp_path, envelope)
    row = response["markets"]["A_SHARE"]["rows"][0]
    assert row["prev_close_price"] == 100
    assert row["current_change_pct"] is None
    assert row["current_change_pct_missing_reason"] == "AUCTION_PRICE_MISSING_OR_INVALID"


def test_restored_gap_changes_ranks_under_the_original_bounded_formula():
    rows = [
        auction_row(code="A.000101", previous=100, price=95),
        auction_row(code="A.000102", previous=100, price=105),
        auction_row(code="A.000103", previous=100, price=100),
    ]
    selected = through_adapter(rows)["rows"]
    assert [(row["code"], row["score"], row["rank"]) for row in selected] == [
        ("A.000102", 100, 1), ("A.000103", 50.25, 2), ("A.000101", 0.25, 3),
    ]


def test_score_ties_keep_input_order_and_existing_top_ten_boundary():
    codes = [f"A.{1000-index:06d}" for index in range(12)]
    rows = [auction_row(code=code, previous=100, price=105) for code in codes]
    envelope = through_adapter(rows)
    assert [row["code"] for row in envelope["rows"]] == codes[:10]
    assert [row["rank"] for row in envelope["rows"]] == list(range(1, 11))
    assert [row["score"] for row in envelope["rows"]] == [100] * 10
    assert envelope["requested_rows"] == envelope["source_rows"] == 12


@pytest.mark.parametrize("value", [None, 5.0, 0.0])
def test_existing_v2_csv_codec_keeps_nullable_change_without_header_migration(value):
    row = {"code": "A.000101", "rank": 1, "formal_eligible": False,
           "current_change_pct": value, "lane_evidence": []}
    encoded = _artifact_rows([row], fields=SELECTION_ARTIFACT_FIELDS_V2)
    decoded = _decode_artifact_rows(encoded, fields=SELECTION_ARTIFACT_FIELDS_V2)
    assert decoded[0]["current_change_pct"] == value
    assert SELECTION_ARTIFACT_FIELDS_V1 == LEGACY_HEADER


def test_modified_persisted_previous_close_fails_manifest_verification(tmp_path):
    envelope = through_adapter([auction_row()])
    _, _, store = publish_and_read(tmp_path, envelope)
    manifest_path = next(store.root.rglob("manifest.json"))
    manifest = json.loads(manifest_path.read_text())
    manifest["selection_envelope"]["rows"][0]["prev_close_price"] = 99
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(SelectionError, match="manifest SHA mismatch"):
        store.read_verified(DATE, STAGE, "A_SHARE")


def test_wrong_date_and_nonauction_window_remain_rejected():
    wrong_date = auction_row()
    wrong_date["trade_date"] = "20261007"
    with pytest.raises(SelectionError, match="trade_date drift"):
        select_a_0925_auction([wrong_date], DATE, RAW_SHA)
    outside = auction_row()
    outside["update_time"] = "2026-10-08 09:31:00"
    envelope = select_a_0925_auction([outside], DATE, RAW_SHA)
    assert envelope["rows"] == []
    assert envelope["selection_status"] == "CANNOT_CONFIRM"
    assert "outside 09:20-09:30 auction window" in envelope["cannot_confirm"][0]
