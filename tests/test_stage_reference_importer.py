from __future__ import annotations

import json

import pytest

from infrastructure.stage_store import StageStore
from ops.import_stage_reference import import_reference_file, normalize_reference


def _legacy_export() -> dict:
    return {
        "schema_version": "v3_stage_workbench.v2",
        "trade_date": "20260730",
        "stage": {
            "stage_id": "STAGE_0930_0935",
            "label": "09:30-09:35",
            "window": "09:30-09:35",
            "status": "DATA_PARTIAL_OBSERVE_ONLY",
            "display_status": "观察材料已生成",
            "startup_ensure": {"csv_path": r"C:\legacy\stage.csv"},
        },
        "markets": {
            "A": {"label": "A股", "source_rows": 12, "data_level": "CUTOFF_SAFE"},
            "HK": {"label": "港股通", "source_rows": 20, "data_level": "L1"},
        },
        "selected_a_rows": 1,
        "selected_hk_rows": 1,
        "selected_total_rows": 99,
        "unified_rows": [
            {
                "market": "A",
                "code": "002199",
                "name": "东晶电子",
                "rank": "1",
                "score": 174.677546,
                "display_decision": "买入审查",
                "next_validation_time": "09:40",
                "cannot_confirm": ["只读观察"],
                "data_level": "CUTOFF_SAFE",
                "support_primary_price": 13.01,
                "pressure_price": 14.73,
                "invalidation_price": 13.01,
                "current_change_pct": 8.6632,
                "turnover": 133053372.98,
                "buy_reason": "must not migrate",
                "source_path": r"C:\legacy\stage.csv",
            },
            {
                "market": "HK",
                "code": "HK.01357",
                "name": "美图公司",
                "rank": "2",
                "stage_rtdata_score": 82,
                "stage_display_decision": "09:35确认观察",
                "next_validation_time": "09:40",
                "cannot_confirm": [],
                "data_level": "L1",
            },
        ],
        "production_allowed": True,
        "orders_sent": True,
    }


def test_normalizer_whitelists_fields_recomputes_counts_and_downgrades_buy_language() -> None:
    payload = normalize_reference(_legacy_export())

    assert payload["selected_a_rows"] == 1
    assert payload["selected_hk_rows"] == 1
    assert payload["selected_total_rows"] == 2
    assert payload["unified_rows"][0]["stage_display_decision"] == "人工观察"
    assert payload["unified_rows"][0]["support_primary_price"] == 13.01
    assert payload["unified_rows"][0]["recommendation_status"] == "WATCH_ONLY"
    assert "buy_reason" not in payload["unified_rows"][0]
    assert "source_path" not in payload["unified_rows"][0]
    assert "startup_ensure" not in payload["stage"]
    assert payload["production_allowed"] is False
    assert payload["buy_gate_updated"] is False
    assert payload["orders_sent"] is False


def test_offline_file_import_is_idempotent_and_runtime_independent(tmp_path) -> None:
    source = tmp_path / "export.json"
    source.write_text(json.dumps(_legacy_export(), ensure_ascii=False), encoding="utf-8")
    store = StageStore(tmp_path / "data")

    first = import_reference_file(store, source)
    second = import_reference_file(store, source)

    assert second == first
    workbench = store.read_reference_workbench("20260730", "STAGE_0930_0935")
    assert workbench is not None
    assert workbench["selection_mode"] == "MIGRATED_REFERENCE_WORKBENCH"
    assert workbench["response_source"] == "V3_5_MIGRATED_REFERENCE_SNAPSHOT"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(schema_version="wrong"),
        lambda payload: payload.update(unified_rows=[]),
        lambda payload: payload["unified_rows"][0].update(market="US"),
        lambda payload: payload["unified_rows"][0].update(code=""),
    ],
)
def test_malformed_exports_are_rejected_before_data_root_creation(tmp_path, mutation) -> None:
    export = _legacy_export()
    mutation(export)
    store = StageStore(tmp_path / "data")

    with pytest.raises(ValueError):
        normalize_reference(export)

    assert not store.root.exists()
