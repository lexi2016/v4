from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

from apps.api.v35_api.app import create_app
from domains.stages import StageRunner
from infrastructure.stage_store import StageStore


def _reference() -> dict:
    return {
        "schema_version": "v3_stage_workbench.v2",
        "trade_date": "20260730",
        "stage": {
            "stage_id": "STAGE_0925",
            "label": "09:20-09:25 / 09:25 集合竞价确认",
            "window": "09:30初筛",
            "status": "DATA_PARTIAL_OBSERVE_ONLY",
            "display_status": "观察材料已生成，仅观察",
            "same_context_required": True,
        },
        "markets": {
            "A": {"label": "A股", "candidate_count": 0, "source_rows": 1},
            "HK": {"label": "港股通", "candidate_count": 2, "source_rows": 100},
        },
        "stage_groups": [],
        "selected_a_rows": 0,
        "selected_hk_rows": 2,
        "selected_total_rows": 2,
        "unified_rows": [
            {
                "market": "HK",
                "code": "HK.01357",
                "name": "美图公司",
                "rank": "1",
                "score": 82.0,
                "d1_change_pct": 13.065,
                "stage_display_decision": "09:30初步筛选",
                "next_validation_time": "09:35",
                "cannot_confirm": ["CANNOT_CONFIRM_SUPPORT_INVALIDATION_LINE"],
                "recommendation_status": "WATCH_ONLY",
            },
            {
                "market": "HK",
                "code": "HK.09903",
                "name": "天数智芯",
                "rank": "2",
                "score": 80.59,
                "d1_change_pct": -13.503,
                "stage_display_decision": "09:30初步筛选",
                "next_validation_time": "09:35",
                "cannot_confirm": ["CANNOT_CONFIRM_PRESSURE_LINE"],
                "recommendation_status": "WATCH_ONLY",
            },
        ],
        "sidebar": {"timeline": [], "evidence_sources": [], "cannot_confirm_items": []},
        "empty_state": {"A": "当前阶段 A股无可确认候选。", "HK": ""},
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "recommendation_status": "WATCH_ONLY_BACKTEST_GATED",
    }


def test_imported_reference_is_visible_without_becoming_a_native_stage_run(tmp_path) -> None:
    store = StageStore(tmp_path / "data")
    imported = store.import_reference_workbench(_reference())

    assert imported["payload_path"] == "stage_references/20260730/STAGE_0925.json"
    assert store.read_latest("20260730", "STAGE_0925") is None
    workbench = StageRunner(store).read_workbench("20260730", "STAGE_0925", limit=10)
    assert workbench["selected_hk_rows"] == 2
    assert workbench["selection_mode"] == "MIGRATED_REFERENCE_WORKBENCH"
    assert workbench["response_source"] == "V3_5_MIGRATED_REFERENCE_SNAPSHOT"
    assert workbench["production_allowed"] is False


def test_reference_workbench_is_exposed_by_the_compatible_api(tmp_path) -> None:
    store = StageStore(tmp_path / "data")
    reference = deepcopy(_reference())
    reference["unified_rows"].insert(
        0,
        {
            "market": "A",
            "code": "002199",
            "name": "东晶电子",
            "rank": "1",
            "score": 90,
            "recommendation_status": "WATCH_ONLY",
        },
    )
    reference["selected_a_rows"] = 1
    reference["selected_total_rows"] = 3
    reference["markets"]["A"]["candidate_count"] = 1
    store.import_reference_workbench(reference)
    response = TestClient(create_app(data_root=store.root)).get(
        "/api/v3/workbench/stage",
        params={"date": "20260730", "stage": "STAGE_0925", "limit": 1},
    )

    assert response.status_code == 200
    assert [row["name"] for row in response.json()["unified_rows"]] == ["东晶电子", "美图公司"]


def test_reference_import_rejects_unsafe_or_wrong_identity(tmp_path) -> None:
    store = StageStore(tmp_path / "data")
    unsafe = _reference()
    unsafe["unified_rows"][0]["orders_sent"] = True

    try:
        store.import_reference_workbench(unsafe)
    except ValueError as error:
        assert "unsafe" in str(error)
    else:
        raise AssertionError("unsafe reference must be rejected")

    assert not store.root.exists()


def test_reference_repair_requires_expected_sha_and_records_supersession(tmp_path) -> None:
    store = StageStore(tmp_path / "data")
    original = _reference()
    original["markets"]["A"].pop("source_rows")
    imported = store.import_reference_workbench(original)
    corrected = deepcopy(_reference())

    with pytest.raises(ValueError, match="expected SHA"):
        store.replace_reference_workbench(
            corrected,
            expected_sha256="0" * 64,
            reason="restore omitted source_rows from authority export",
        )

    repaired = store.replace_reference_workbench(
        corrected,
        expected_sha256=imported["sha256"],
        reason="restore omitted source_rows from authority export",
    )

    assert repaired["previous_sha256"] == imported["sha256"]
    assert repaired["sha256"] != imported["sha256"]
    assert repaired["supersession_receipt_path"].endswith(f"{imported['sha256']}.json")
    assert store.read_reference_workbench("20260730", "STAGE_0925")["markets"]["A"]["source_rows"] == 1
    receipt = store._read(repaired["supersession_receipt_path"])
    assert receipt["schema_version"] == "v3_5.reference_supersession.v1"
    assert receipt["previous_sha256"] == imported["sha256"]
    assert receipt["replacement_sha256"] == repaired["sha256"]
    assert receipt["reason"] == "restore omitted source_rows from authority export"

    idempotent = store.replace_reference_workbench(
        corrected,
        expected_sha256=imported["sha256"],
        reason="restore omitted source_rows from authority export",
    )
    assert idempotent == repaired
