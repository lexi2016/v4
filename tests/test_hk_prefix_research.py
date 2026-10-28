from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from domains.hk_prefix_research import (
    EVIDENCE_BASIS,
    PREFIX_FIELDS,
    PREFIX_LENGTH,
    FrozenMarketCalendar,
    HKPrefixResearchError,
    _future_isolation_check,
    _load_scan_function,
    _pair_rows,
    _positive_control_check,
    _scan_artifact,
    _terminal_contract_gate,
    _terminal_endpoint_metrics,
    _validate_scan_input,
    build_prefix_rows,
    sha256_file,
)
from upstreams.v3_shared_data.shared_data.hk_0_2 import (
    load_historical_hk_0_2_research_asset,
)


REFERENCE_EXTRACTOR = (
    Path.home()
    / "Documents/Codex/2026-09-12/referenced-chatgpt-conversation-this-is-an"
    / "work/zge_prefix_route_v1_fixed/prefix_repair.py"
)


def _calendar(periods: int = 90) -> FrozenMarketCalendar:
    dates = tuple(
        pd.date_range("2020-01-02", periods=periods, freq="D").strftime("%Y-%m-%d")
    )
    return FrozenMarketCalendar(
        dates=dates,
        date_to_index={date: index for index, date in enumerate(dates)},
        calendar_path=Path("calendar_sdt.parquet"),
        calendar_sha256="calendar-sha",
        parity_path=Path("calendar_parity_rows.parquet"),
        parity_sha256="parity-sha",
        calendar_source="observed_union_daily_bars_691",
        calendar_certification="CANNOT_CONFIRM_OFFICIAL_MARKET_CALENDAR",
        row_count=periods,
        parity_row_count=periods,
    )


def _source_frame(calendar: FrozenMarketCalendar, *, code: str = "HK.00001") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "code": code,
                "date": date,
                "open": 10.0,
                "high": 10.5,
                "low": 9.5,
                "close": 10.0,
                "trade": 100,
                "amount": 1000.0,
            }
            for date in calendar.dates
        ]
    )


def _synthetic_rows(count: int = 25) -> tuple[dict[str, object], ...]:
    origin = datetime(2020, 1, 1, 16, tzinfo=timezone(timedelta(hours=8)))
    return tuple(
        {
            "series_id": "SYNTHETIC",
            "session_index": index,
            "close_at": (origin + timedelta(days=index)).isoformat(),
            "available_at": (origin + timedelta(days=index)).isoformat(),
            "open": 10.0,
            "high": 10.5,
            "low": 9.5,
            "close": 10.0,
            "volume": 100.0,
            "price_basis": "SYNTHETIC_STABLE",
            "quality": "OK",
        }
        for index in range(count)
    )


def test_historical_owner_reader_verifies_manifest_schema_and_identity(tmp_path: Path) -> None:
    package = tmp_path / "source_package"
    source_path = package / "data" / "daily_bars_full_history.parquet"
    source_path.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "code": "hk.1",
                "date": "2020-01-02",
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.0,
                "trade": 10,
                "amount": 100.0,
            }
        ]
    ).to_parquet(source_path, index=False)
    manifest_path = package / "manifest.json"
    manifest_path.write_text(
        '{"status":"PARTIAL","safety":{"research_only":true,'
        '"production_allowed":false,"buy_gate_updated":false,"orders_sent":false}}',
        encoding="utf-8",
    )

    asset = load_historical_hk_0_2_research_asset(
        source_path,
        source_manifest_path=manifest_path,
        expected_sha256=sha256_file(source_path),
    )

    assert list(asset.frame.columns) == [
        "code",
        "date",
        "open",
        "high",
        "low",
        "close",
        "trade",
        "amount",
    ]
    assert asset.frame.iloc[0]["code"] == "HK.1"
    assert asset.frame.iloc[0]["date"] == "2020-01-02"


def test_prefix_builder_uses_exact_prior_60_frozen_calendar_sessions() -> None:
    calendar = _calendar()
    source = _source_frame(calendar)
    event_date = calendar.dates[70]

    rows, observed, missing = build_prefix_rows(
        source,
        calendar,
        code="HK.00001",
        event_date=event_date,
        series_id="SERIES_001",
    )

    assert len(rows) == PREFIX_LENGTH == 60
    assert rows[0]["session_index"] == 10
    assert rows[-1]["session_index"] == 69
    assert rows[-1]["close_at"].startswith(calendar.dates[69])
    assert all(set(row) == set(PREFIX_FIELDS) for row in rows)
    assert all(event_date not in str(row["close_at"]) for row in rows)
    assert (observed, missing) == (60, 0)


def test_missing_source_bar_remains_explicit_unknown_input() -> None:
    calendar = _calendar()
    source = _source_frame(calendar)
    source = source[source["date"] != calendar.dates[20]].reset_index(drop=True)

    rows, observed, missing = build_prefix_rows(
        source,
        calendar,
        code="HK.00001",
        event_date=calendar.dates[70],
        series_id="SERIES_001",
    )

    missing_rows = [row for row in rows if row["quality"] == "MISSING_SOURCE_ROW"]
    assert len(missing_rows) == 1
    assert missing_rows[0]["open"] is None
    assert missing_rows[0]["price_basis"]
    assert (observed, missing) == (59, 1)


def test_reference_whitelist_rejects_identity_fields() -> None:
    row = dict(_synthetic_rows(1)[0])
    row["event_id"] = "forbidden"
    with pytest.raises(HKPrefixResearchError, match="exact reference whitelist"):
        _validate_scan_input((row,))


def test_reference_positive_control_and_future_suffix_isolation() -> None:
    scan = _load_scan_function(REFERENCE_EXTRACTOR)
    positive = _positive_control_check(scan)
    assert positive["status"] == "PASS"
    assert positive["observed_terminal_state"] == "RETEST_HELD_PROVISIONAL"

    rows = _synthetic_rows()
    baseline, _ = _scan_artifact(rows, scan=scan)
    future = dict(rows[-1])
    future.update(
        {
            "session_index": 25,
            "close_at": "2020-01-27T16:00:00+08:00",
            "available_at": "2020-01-27T16:00:00+08:00",
            "open": 9999.0,
            "high": 10000.0,
            "low": 9998.0,
            "close": 9999.5,
            "volume": 999999.0,
        }
    )
    changed, _ = _scan_artifact(
        rows + (future,),
        scan=scan,
        expected_rows=25,
        asof=rows[-1]["close_at"],
    )
    assert changed == baseline

    # Exercise the production check's loop shape with a minimal artifact-like
    # object while retaining the exact reference rows.
    result = _future_isolation_check(
        (SimpleNamespace(series_id="SYNTHETIC", rows=rows),),
        scan=scan,
    )
    assert result["status"] == "PASS"
    assert result["checked_series"] == 1


def test_evidence_basis_is_explicit() -> None:
    assert EVIDENCE_BASIS == "FROZEN_HISTORY_RECONSTRUCTION"


def test_terminal_metric_ignores_qualifying_path_occupancy_after_terminal_failure() -> None:
    metrics = _terminal_endpoint_metrics(
        ["RETEST_HELD_PROVISIONAL", "NO_ACTIVE_SETUP"]
    )

    assert metrics["terminal_determinable"] is True
    assert metrics["terminal_lower"] == metrics["terminal_upper"] == 0.0
    assert metrics["terminal_qualifies"] is False


def test_warmup_terminal_is_indeterminate_and_not_known_negative() -> None:
    metrics = _terminal_endpoint_metrics(["NO_ACTIVE_SETUP", "WARMUP"])

    assert metrics["terminal_determinable"] is False
    assert metrics["terminal_unknown"] is False
    assert metrics["terminal_lower"] == 0.0
    assert metrics["terminal_upper"] == 1.0
    assert metrics["terminal_qualifies"] is False


def test_pair_unknown_bounds_use_case_low_control_high_and_reverse() -> None:
    def artifact(series_id: str, role: str, lower: float, upper: float) -> SimpleNamespace:
        return SimpleNamespace(
            series_id=series_id,
            pair_group_id="PAIR_TEST",
            role=role,
            terminal_state="UNKNOWN" if lower != upper else "NO_ACTIVE_SETUP",
            terminal_qualifies=lower == upper == 1.0,
            terminal_unknown=False,
            terminal_determinable=lower == upper,
            terminal_lower=lower,
            terminal_upper=upper,
            terminal_indeterminate_reason="" if lower == upper else "UNKNOWN_ENDPOINT_INDETERMINATE",
            occupancy_lower_rate=0.0,
            occupancy_upper_rate=0.0,
        )

    group = SimpleNamespace(
        pair_group_id="PAIR_TEST",
        event_date="2020-01-01",
        event_type="new_event",
    )
    rows = _pair_rows(
        [
            artifact("SERIES_001", "EVENT", 0.0, 1.0),
            artifact("SERIES_002", "CONTROL_1", 1.0, 1.0),
            artifact("SERIES_003", "CONTROL_2", 0.0, 0.0),
            artifact("SERIES_004", "CONTROL_3", 0.0, 1.0),
        ],
        [group],
    )

    assert rows[0]["complete_terminal_pair"] is False
    assert rows[0]["terminal_delta"] is None
    assert rows[0]["terminal_delta_lower"] == pytest.approx(-2 / 3)
    assert rows[0]["terminal_delta_upper"] == pytest.approx(2 / 3)
    assert rows[0]["terminal_delta_lower"] <= rows[0]["terminal_delta_upper"]


def test_terminal_coverage_gate_reports_fixed_16_of_24_without_promoting_occupancy() -> None:
    rows = [
        {
            "event_type": "new_event" if index < 20 else "continuation_event",
            "complete_terminal_pair": index < 14 if index < 20 else index < 22,
        }
        for index in range(24)
    ]
    gate = _terminal_contract_gate(rows)

    assert gate["status"] == "NOT_SUPPORTED"
    assert gate["complete_terminal_pairs"] == 16
    assert gate["required_complete_pairs"] == 18
    assert gate["coverage"] == "16/24"
    assert gate["by_event_type"]["new_event"] == {"complete": 14, "total": 20}
    assert gate["by_event_type"]["continuation_event"] == {"complete": 2, "total": 4}


def test_cli_converts_owner_store_error_to_controlled_cannot_confirm(monkeypatch, capsys) -> None:
    from ops import hk_prefix_research as cli
    from upstreams.v3_shared_data.shared_data.store import StoreError

    def raise_store_error(**_: object) -> None:
        raise StoreError("owner store rejected historical input")

    monkeypatch.setattr(cli, "run_hk_prefix_research", raise_store_error)
    result = cli.main(
        [
            "--source-path", "/tmp/source.parquet",
            "--source-manifest", "/tmp/source.json",
            "--source-sha256", "a" * 64,
            "--calendar-sdt", "/tmp/calendar.parquet",
            "--calendar-parity-rows", "/tmp/parity.parquet",
            "--binding", "/tmp/binding.json",
            "--matched-verdict", "/tmp/matched.csv",
            "--extractor", "/tmp/extractor.py",
            "--output", "/tmp/hk-prefix-cli-test",
        ]
    )

    assert result == 2
    payload = json.loads(capsys.readouterr().err)
    assert payload["status"] == "CANNOT_CONFIRM"
    assert payload["error_type"] == "StoreError"
