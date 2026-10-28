from __future__ import annotations

from types import SimpleNamespace

from domains.preselection_materializer import build_shared_hk_0_2_pool
from upstreams.v3_shared_data.shared_data.names import resolve_hk_name_for_date


OLD_NAME = "帝王国际投资"


def test_02915_name_override_is_bounded_to_verified_temporary_counter_window() -> None:
    before, before_resolution = resolve_hk_name_for_date(
        "HK.02915", trade_date="20260922", source_name=OLD_NAME
    )
    start, start_resolution = resolve_hk_name_for_date(
        "HK.02915", trade_date="20260923", source_name=OLD_NAME
    )
    target, target_resolution = resolve_hk_name_for_date(
        "02915.HK_CONNECT", trade_date="20261012", source_name=OLD_NAME
    )
    end, end_resolution = resolve_hk_name_for_date(
        "HK.02915", trade_date="20261029", source_name=OLD_NAME
    )
    after, after_resolution = resolve_hk_name_for_date(
        "HK.02915", trade_date="20261030", source_name=OLD_NAME
    )

    assert before == OLD_NAME
    assert before_resolution["status"] == "SOURCE_NAME_BEFORE_EFFECTIVE_DATE"
    for name, resolution, date in (
        (start, start_resolution, "20260923"),
        (target, target_resolution, "20261012"),
        (end, end_resolution, "20261029"),
    ):
        assert name == "云迹"
        assert resolution["status"] == "EFFECTIVE_DATE_OVERRIDE"
        assert resolution["trade_date"] == date
        assert resolution["effective_from"] == "20260923"
        assert resolution["effective_through"] == "20261029"
        assert resolution["scope"] == "DISPLAY_NAME_ONLY"
        assert resolution["effective_through_source_quality"] == "SECONDARY_CROSS_SOURCE_TIMETABLE"
        assert resolution["production_allowed"] is False
        assert resolution["buy_gate_updated"] is False
        assert resolution["orders_sent"] is False
    assert after == OLD_NAME
    assert after_resolution["status"] == "SOURCE_NAME_AFTER_EFFECTIVE_WINDOW"


def test_hk_pool_projects_dated_name_and_preserves_source_identity() -> None:
    rows = [
        {
            "code_norm": "HK.02915" if rank == 1 else f"HK.{rank:05d}",
            "name": OLD_NAME if rank == 1 else f"Name {rank}",
            "rank": rank,
            "score_prob_active": 1.0 - rank / 1000,
            "signal_date": "20261009",
            "target_date": "20261012",
            "selected_strategy": "prob_active",
            "d1_freshness_status": "PASS",
        }
        for rank in range(1, 101)
    ]
    verification = {
        "run_id": "20261012-hk-connect-d1-top100-0-2-test",
        "artifact_relative": "runs/20261012/pool/artifact.csv",
        "artifact_sha256": "a" * 64,
        "manifest_sha256": "b" * 64,
        "receipt_sha256": "c" * 64,
        "row_count": 100,
    }
    run = SimpleNamespace(
        verification=verification,
        receipt={
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
        manifest={"provenance": {}},
    )

    result = build_shared_hk_0_2_pool(
        "/tmp/read-only-hk-source",
        trade_date="20261012",
        signal_date="20261009",
        reader=lambda _root, **_kwargs: SimpleNamespace(rows=rows, run=run),
    )

    assert len(result["rows"]) == 100
    assert len({row["symbol"] for row in result["rows"]}) == 100
    first = result["rows"][0]
    assert (first["symbol"], first["pool_rank"], first["pool_score"]) == (
        "HK.02915",
        1,
        rows[0]["score_prob_active"],
    )
    assert first["name"] == first["stock_name"] == "云迹"
    assert first["raw_name"] == OLD_NAME
    assert first["name_resolution"]["status"] == "EFFECTIVE_DATE_OVERRIDE"
    assert result["source_run_id"] == verification["run_id"]
    assert result["source_sha256"] == verification["artifact_sha256"]
    assert result["source_manifest_sha256"] == verification["manifest_sha256"]
    assert result["source_receipt_sha256"] == verification["receipt_sha256"]
    assert result["source_row_count"] == 100
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False


def test_other_code_and_invalid_date_keep_source_name() -> None:
    untouched, untouched_resolution = resolve_hk_name_for_date(
        "HK.02914", trade_date="20261012", source_name="其它公司"
    )
    invalid, invalid_resolution = resolve_hk_name_for_date(
        "HK.02915", trade_date="20261340", source_name=OLD_NAME
    )

    assert untouched == "其它公司"
    assert untouched_resolution is None
    assert invalid == OLD_NAME
    assert invalid_resolution["status"] == "CANNOT_CONFIRM_DATE"
