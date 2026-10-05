from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).with_name("run_stage0930_research_only.py")
SPEC = importlib.util.spec_from_file_location("hk_stage0930_candidate_adapter", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
ADAPTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPTER)


def _rows_and_evidence():
    pool = json.loads(
        (ADAPTER.D1_ROOT / "preselection_pools" / "20260925" / "hkconnect_d1_top100.json").read_text()
    )["rows"]
    codes = tuple(sorted(row["code"] for row in pool))
    plan = SimpleNamespace(
        trade_date=ADAPTER.TARGET_DATE,
        stage_id=ADAPTER.STAGE_ID,
        codes_for=lambda market: codes if market == ADAPTER.MARKET else (),
    )
    return ADAPTER._load_inputs(plan)


def test_historical_adapter_keeps_observation_window_and_price_bar_time_distinct():
    rows, missing, evidence = _rows_and_evidence()
    by_code = {row["code"]: row for row in rows}
    yahoo = by_code["HK.02922"]
    eastmoney = by_code["HK.00668"]

    assert yahoo["source_last_bar_time"] == "2026-09-25 09:32:00"
    assert yahoo["update_time"] == yahoo["window_end"] == "2026-09-25 09:35:00"
    assert yahoo["window_start"] == "2026-09-25 09:31:00"
    assert yahoo["volume"] is None
    assert yahoo["turnover"] is None
    assert yahoo["bar_count"] == 5
    assert set(missing) == {
        "HISTORICAL_MINUTE_LABEL_BOUNDARY_NOT_FULLY_CONFIRMED",
        "HISTORICAL_ACTIVE_LANE_AUTHORITY_UNVERIFIED",
        "HISTORICAL_VOLUME_RATIO_MISSING",
        "HISTORICAL_TURNOVER_RATE_MISSING",
        "HISTORICAL_PLATFORM_CAP_MAPPING_UNVERIFIED",
        "HISTORICAL_FREE_FLOAT_CAP_UNVERIFIED",
        "HISTORICAL_AMOUNT_02402_UNIT_UNVERIFIED",
        "HISTORICAL_YAHOO_AMOUNT_UNAVAILABLE",
        *(f"HISTORICAL_NO_VALID_LAST_PRICE:{code}" for code in ADAPTER.MISSING_LAST),
    }
    assert "source_last_bar_time" not in ADAPTER.RAW_FIELDS
    assert "historical_supplement_last_positive_label=HK.02922:09:32:00" in evidence
    assert eastmoney["source_last_bar_time"] == "2026-09-25 09:31:00"
    assert eastmoney["update_time"] == eastmoney["window_end"] == "2026-09-25 09:35:00"
    assert eastmoney["bar_count"] == 5
    assert eastmoney["volume"] == 200.0
    assert eastmoney["turnover"] == 23860.0

    for code in sorted(ADAPTER.ZERO_VOLUME_REFERENCES):
        row = by_code[code]
        assert row["source_last_bar_time"] is None
        assert row["last_price"] is None
        assert row["update_time"] == row["window_end"] == "2026-09-25 09:35:00"
        assert f"historical_zero_volume_reference_only={code}" in evidence
        assert not any(
            marker.startswith(f"historical_supplement_last_positive_label={code}:")
            for marker in evidence
        )

    labels = next(marker.split("=", 1)[1] for marker in evidence if marker.startswith("historical_observed_last_price_labels="))
    observed = json.loads(labels)
    assert observed["HK.02922"] == "09:32:00"
    assert not ADAPTER.ZERO_VOLUME_REFERENCES.intersection(observed)
