from __future__ import annotations

from pathlib import Path

from ops import daily_materialize


def test_daily_owner_calls_exact_day_producer_once(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[tuple[Path, str]] = []

    def fake_materialize(root: Path, archive_date: str) -> dict:
        calls.append((Path(root), archive_date))
        return {
            "schema_version": "v3_5.research_day_materialize.v1",
            "status": "READY_WITH_DECLARED_GAPS",
            "archive_date": archive_date,
            "expected_slots": ["1000", "1100", "1200", "1300", "1400", "1500", "1600", "1700"],
            "coverage": {"expected_slots": 8, "ready_slots": 8, "missing_slots": []},
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    monkeypatch.setattr(daily_materialize, "materialize_research_day", fake_materialize)
    context = daily_materialize.DailyContext(
        business_date="20260907",
        target_date="20260908",
        data_root=tmp_path / "data",
        shared_data_root=None,
        selector_data_root=None,
        stage_selection_root=None,
    )

    result = daily_materialize._materialize_research_day(context)

    assert calls == [(tmp_path / "data", "20260907")]
    assert result["status"] == "SUCCEEDED"
    assert result["product_status"] == "READY_WITH_DECLARED_GAPS"
    assert result["producer_called"] is True
    assert result["write_performed"] is True
    assert result["production_allowed"] is False


def test_daily_owner_keeps_missing_exact_day_typed_and_does_not_claim_write(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        daily_materialize,
        "materialize_research_day",
        lambda root, archive_date: {
            "schema_version": "v3_5.research_day_materialize.v1",
            "status": "NOT_MATERIALIZED",
            "archive_date": archive_date,
            "missing_slots": ["1700"],
            "cannot_confirm": ["MISSING_SLOT:1700"],
        },
    )
    context = daily_materialize.DailyContext(
        business_date="20260907",
        target_date="20260908",
        data_root=tmp_path / "data",
        shared_data_root=None,
        selector_data_root=None,
        stage_selection_root=None,
    )

    result = daily_materialize._materialize_research_day(context)

    assert result["status"] == "NOT_MATERIALIZED"
    assert result["product_status"] == "NOT_MATERIALIZED"
    assert result["producer_called"] is True
    assert result["write_performed"] is False
    assert result["product"]["cannot_confirm"] == ["MISSING_SLOT:1700"]
