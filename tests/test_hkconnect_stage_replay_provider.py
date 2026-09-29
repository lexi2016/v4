from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from infrastructure.hkconnect_stage_replay_provider import HkConnectStageReplayProvider
from infrastructure.stage_store import validate_quote_batch


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "hkconnect_stage_replay"
FIXTURE_MANIFEST = FIXTURE_ROOT / "manifest.json"


@pytest.fixture
def provider() -> HkConnectStageReplayProvider:
    return HkConnectStageReplayProvider(data_root=FIXTURE_ROOT)


def test_hk_replay_fixture_manifest_freezes_sha_and_row_count() -> None:
    manifest = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["trade_date"] == "20260730"
    assert manifest["production_allowed"] is False
    assert manifest["buy_gate_updated"] is False
    assert manifest["orders_sent"] is False
    for stage_id, expected in manifest["stages"].items():
        path = FIXTURE_ROOT / expected["relative_path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected["sha256"]
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            rows = list(csv.DictReader(source))
        assert len(rows) == expected["row_count"]
        assert all(row["stage_id"] == stage_id for row in rows)


def test_hk_replay_reads_aggregated_rows_for_stage(provider: HkConnectStageReplayProvider) -> None:
    payload = provider.snapshot(
        ["HK.09985", "HK.09987"],
        trade_date="20260730",
        stage_id="STAGE_1300_1315",
        cutoff_at="2026-07-30T13:15:00",
    )
    assert payload["schema_version"] == "v3_5.read_only_quote_batch.v1"
    assert payload["trade_date"] == "20260730"
    assert payload["stage_id"] == "STAGE_1300_1315"
    assert payload["temporal_cutoff_safe"] is True
    assert payload["source"] == "V3_5_HKCONNECT_AGGREGATED_STAGE_REPLAY"
    assert payload["production_allowed"] is False
    assert payload["buy_gate_updated"] is False
    assert payload["orders_sent"] is False
    assert validate_quote_batch(payload) == ("20260730", "STAGE_1300_1315")


def test_hk_replay_rows_keep_scoring_fields(provider: HkConnectStageReplayProvider) -> None:
    payload = provider.snapshot(
        ["HK.09985", "HK.09987"],
        trade_date="20260730",
        stage_id="STAGE_1300_1315",
        cutoff_at="2026-07-30T13:15:00",
    )
    by_symbol = {row["symbol"]: row for row in payload["rows"]}
    assert set(by_symbol) == {"HK.09985", "HK.09987"}
    row = by_symbol["HK.09985"]
    assert row["pct_chg"] is not None
    assert row["turnover_hkd_yi"] is not None
    assert row["circular_market_cap_hkd_yi"] is not None
    assert row["stage_close_position"] is not None
    assert row["source_universe"] == "LIVE_HKCONNECT_GAINER"
    assert row["data_level"] == "STAGE_RTDATA_LATE_REPLAY"
    assert row["recommendation_status"] == "WATCH_ONLY"
    assert row["market"] == "HK"
    assert row["stage_id"] == "STAGE_1300_1315"


def test_hk_replay_rows_carry_v3_support_pressure_invalidation(tmp_path) -> None:
    provider = HkConnectStageReplayProvider(data_root=FIXTURE_ROOT)
    payload = provider.snapshot(
        ["HK.02685", "HK.06651"],
        trade_date="20260730",
        stage_id="STAGE_0930_0935",
        cutoff_at="2026-07-30T09:35:05",
    )
    by_symbol = {row["symbol"]: row for row in payload["rows"]}
    assert by_symbol["HK.02685"]["support_primary_price"] is not None
    assert by_symbol["HK.02685"]["pressure_price"] is not None
    assert by_symbol["HK.02685"]["invalidation_price"] == by_symbol["HK.02685"]["support_primary_price"]
    assert by_symbol["HK.02685"]["next_validation_time"] == "09:40"
    assert by_symbol["HK.06651"]["next_validation_time"] == "09:40"
    assert by_symbol["HK.02685"]["current_change_pct"] == by_symbol["HK.02685"]["stage_window_change_pct"]


def test_hk_replay_next_validation_matches_v3_clock(tmp_path) -> None:
    provider = HkConnectStageReplayProvider(data_root=FIXTURE_ROOT)
    payload = provider.snapshot(
        ["HK.02650"],
        trade_date="20260730",
        stage_id="STAGE_1445_1500",
        cutoff_at="2026-07-30T15:00:00",
    )
    assert payload["rows"][0]["next_validation_time"] == "closeout"


def test_hk_replay_filters_to_requested_symbols(provider: HkConnectStageReplayProvider) -> None:
    payload = provider.snapshot(
        ["HK.09987"],
        trade_date="20260730",
        stage_id="STAGE_1300_1315",
        cutoff_at="2026-07-30T13:15:00",
    )
    assert [row["symbol"] for row in payload["rows"]] == ["HK.09987"]


def test_hk_replay_unknown_stage_rejected(provider: HkConnectStageReplayProvider) -> None:
    with pytest.raises(ValueError, match="unknown stage_id"):
        provider.snapshot(
            ["HK.09985"],
            trade_date="20260730",
            stage_id="STAGE_NOPE",
            cutoff_at="2026-07-30T13:15:00",
        )


def test_hk_replay_missing_directory_raises() -> None:
    provider = HkConnectStageReplayProvider(data_root=FIXTURE_ROOT)
    with pytest.raises(FileNotFoundError):
        provider.snapshot(
            ["HK.09985"],
            trade_date="20990101",
            stage_id="STAGE_1300_1315",
            cutoff_at="2099-01-01T13:15:00",
        )
