"""Existing frozen behavior that the narrow date fix must preserve."""
from __future__ import annotations

import pytest

from frozen_fixtures import (
    asof_payload,
    change_source_date,
    historical_payload,
    materialize_and_read,
    original_contract_test,
    split_payload,
)


def test_original_historical_contract_checks_unchanged(tmp_path):
    original_contract_test(tmp_path)


@pytest.mark.parametrize("schema", ["split", "asof"])
def test_source_dates_equal_to_target_remain_accepted(tmp_path, schema):
    payload = historical_payload(schema)
    change_source_date(payload, "eligibility_source_date", payload["trade_date"])
    change_source_date(payload, "price_signal_date", payload["trade_date"])

    result = materialize_and_read(payload, tmp_path / "data")

    assert result == payload


def test_late_recovery_capture_remains_accepted_and_unverified(tmp_path):
    payload = asof_payload()

    result = materialize_and_read(payload, tmp_path / "data")

    assert result["trade_date"] == "20260930"
    assert result["historical_provenance"]["eligibility_asof"]["captured_at"] == "2026-10-02T14:02:56+08:00"
    for key in ("eligibility_asof", "price_recovery"):
        assert result["historical_provenance"][key]["natural_verified"] is False
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False


def test_generic_legacy_pool_without_provenance_remains_accepted(tmp_path):
    payload = split_payload()
    del payload["historical_provenance"]

    result = materialize_and_read(payload, tmp_path / "data")

    assert result == payload


def test_known_optional_nested_consumer_metadata_remains_accepted(tmp_path):
    payload = asof_payload()
    payload["historical_provenance"]["eligibility_asof"].update(
        source_role="FUTU_HKCONNECT_PLATE_MEMBERSHIP",
        validity="OFFICIAL_EFFECTIVE_RECOVERY",
    )
    payload["historical_provenance"]["price_recovery"].update(
        provider="MIXED_PYTDX_HQ_DAILY_AND_FUTU_OPEND_HISTORY_KLINE",
        adjustment="NONE",
        volume_unit_status="APPROXIMATE_NOT_LOSSLESS",
    )

    result = materialize_and_read(payload, tmp_path / "data")

    assert result == payload


def test_input_hash_map_accepts_dynamic_string_labels(tmp_path):
    payload = asof_payload()
    input_hashes = {
        "core": "3" * 64,
        "new-vendor/raw-file-v2": "5" * 64,
        "HK history rows 20260929": "6" * 64,
    }
    payload["historical_provenance"]["price_recovery"]["source_input_sha256"] = input_hashes

    result = materialize_and_read(payload, tmp_path / "data")

    assert result["historical_provenance"]["price_recovery"]["source_input_sha256"] == input_hashes


def test_optional_target_field_remains_optional_for_valid_historical_pool(tmp_path):
    payload = asof_payload()
    del payload["target_date"]

    result = materialize_and_read(payload, tmp_path / "data")

    assert result == payload
