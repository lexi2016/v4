from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

TRADE_DATE = "20260907"


def _project(
    payload: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    *, route_path: str = "/api/v3/workbench/stage",
) -> dict[str, Any]:
    from apps.api.v35_api import app as app_module
    from apps.api.v35_api.app import create_app
    from infrastructure.data_store import NativeDataStore

    class FakeConsumer:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def get(self, _date: str, _stage: str, **_kwargs: Any) -> dict[str, Any]:
            return payload

    monkeypatch.setattr(app_module, "StageSelectionConsumer", FakeConsumer)
    store = NativeDataStore(tmp_path / "data")
    store.import_catalog({
        "schema_version": "v3_trade_calendar.v1",
        "system_date": TRADE_DATE,
        "stage_dates": [],
        "future_target_dates": [],
        "materialized_rows": {},
    })
    app = create_app(data_root=store.root, stage_center_selection_root=tmp_path / "stage")
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", None) == route_path)
    arguments: dict[str, Any] = {"date": TRADE_DATE, "stage": "STAGE_0935_0940", "limit": 50}
    if route_path == "/api/v3/manager/stage-selection":
        arguments["market"] = "HK_CONNECT"
    return endpoint(**arguments)


def _project_real_hk_producer_market(
    *,
    source_status: str,
    input_rows: int,
    requested_rows: int,
    source_evidence: tuple[str, ...],
    missing_symbols: tuple[str, ...] = (),
    cannot_confirm: tuple[str, ...] = (),
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Exercise the real selection envelope and consumer projection before the API route."""
    from stage_center.consumer import _project_market
    from stage_center.selection import _selection_envelope

    envelope = _selection_envelope(
        trade_date=TRADE_DATE,
        stage_id="STAGE_0935_0940",
        market="HK_CONNECT",
        raw_artifact_sha256="a" * 64,
        source_status=source_status,
        input_rows=input_rows,
        rows=(),
        requested_rows=requested_rows,
        missing_symbols=missing_symbols,
        cannot_confirm=cannot_confirm,
        source_evidence=source_evidence,
    )
    market = _project_market("HK_CONNECT", envelope)
    payload = {
        "trade_date": TRADE_DATE,
        "stage_id": "STAGE_0935_0940",
        "status": envelope["selection_status"],
        "markets": {"HK_CONNECT": market},
        "execution_evidence": {"markets": {}},
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    return _project(payload, tmp_path, monkeypatch), market


def test_missing_hk_artifact_has_unknown_counts_and_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from stage_center.consumer import _invalid_market

    invalid = _invalid_market("HK_CONNECT")
    assert {key: invalid[key] for key in ("requested_rows", "source_rows", "selected_rows", "coverage_ratio")} == {
        "requested_rows": None, "source_rows": None, "selected_rows": None, "coverage_ratio": None,
    }
    projected = _project({
        "trade_date": TRADE_DATE, "stage_id": "STAGE_0935_0940", "status": "CANNOT_CONFIRM",
        "markets": {"HK_CONNECT": {
            **invalid, "cannot_confirm": ["SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID"],
        }},
    }, tmp_path, monkeypatch)
    hk = projected["markets"]["HK"]
    assert hk["display_mode"] == "CANNOT_CONFIRM"
    assert hk["candidate_count"] is None
    assert hk["selected_rows"] is None
    assert hk["observation_count"] == 0
    assert projected["status"] == "CANNOT_CONFIRM"
    assert projected["selected_hk_rows"] is None
    assert projected["selected_total_rows"] is None
    assert "SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID" in hk["display_reasons"]


@pytest.mark.parametrize("route_path", [
    "/api/v3/workbench/stage",
    "/api/v3/stage-center/selection",
])
def test_partial_unsafe_hk_rows_are_observations_and_a_count_is_preserved(
    route_path: str,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    hk_rows = [
        {"code": f"HK.{index:05d}", "rank": index, "formal_eligible": False}
        for index in range(1, 11)
    ]
    projected = _project({
        "trade_date": TRADE_DATE, "stage_id": "STAGE_0935_0940", "status": "PARTIAL_WITH_ROWS",
        "markets": {
            "A_SHARE": {
                "market": "A_SHARE", "status": "READY", "selection_status": "READY",
                "artifact_id": "selection-a-ready", "run_id": "run-a-ready",
                "raw_artifact_sha256": "a" * 64, "selected_rows": 1,
                "rows": [{"code": "A.000001", "rank": 1, "formal_eligible": True}],
                "cannot_confirm": [],
            },
            "HK_CONNECT": {
                "market": "HK_CONNECT", "status": "PARTIAL_WITH_ROWS",
                "selection_status": "PARTIAL_WITH_ROWS", "artifact_id": "selection-hk-partial",
                "run_id": "run-hk-partial", "raw_artifact_sha256": "b" * 64,
                "selected_rows": 10, "rows": hk_rows, "cannot_confirm": [],
            },
        },
        "execution_evidence": {"markets": {
            "A_SHARE": {"selection_binding": "BOUND_TO_VERIFIED_SELECTION", "reasons": []},
            "HK_CONNECT": {
                "selection_binding": "NO_VERIFIED_SELECTION_BINDING", "reasons": ["EXECUTION_NOT_BOUND"],
            },
        }},
    }, tmp_path, monkeypatch, route_path=route_path)
    hk = projected["markets"]["HK"]
    assert projected["markets"]["A"]["candidate_count"] == 1
    assert projected["selected_a_rows"] == 1
    assert hk["display_mode"] == "OBSERVATION_UNVERIFIED"
    assert hk["candidate_count"] is None
    assert hk["selected_rows"] is None
    assert hk["observation_count"] == 10
    assert projected["status"] == "PARTIAL_WITH_ROWS"
    assert projected["selected_hk_rows"] is None
    assert projected["selected_total_rows"] is None
    assert "HK_FORMAL_ELIGIBILITY_FALSE" in hk["display_reasons"]
    assert "EXECUTION_NOT_BOUND" in hk["display_reasons"]


def test_ready_hk_rows_without_execution_binding_are_not_formal_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    projected = _project({
        "trade_date": TRADE_DATE, "stage_id": "STAGE_0935_0940", "status": "READY",
        "markets": {"HK_CONNECT": {
            "market": "HK_CONNECT", "status": "READY", "selection_status": "READY",
            "artifact_id": "selection-hk-unbound", "run_id": "run-hk-unbound",
            "raw_artifact_sha256": "c" * 64, "selected_rows": 1,
            "rows": [{"code": "HK.00001", "rank": 1, "formal_eligible": True}],
            "cannot_confirm": [],
        }},
        "execution_evidence": {"markets": {"HK_CONNECT": {
            "selection_binding": "NO_VERIFIED_SELECTION_BINDING",
            "reasons": ["NO_VERIFIED_SELECTION_BINDING"],
        }}},
    }, tmp_path, monkeypatch)
    hk = projected["markets"]["HK"]
    assert hk["display_mode"] == "OBSERVATION_UNVERIFIED"
    assert hk["candidate_count"] is None
    assert hk["selected_rows"] is None
    assert hk["observation_count"] == 1
    assert projected["status"] == "PARTIAL_WITH_ROWS"
    assert projected["selected_hk_rows"] is None
    assert "HK_EXECUTION_SELECTION_BINDING_NO_VERIFIED_SELECTION_BINDING" in hk["display_reasons"]


@pytest.mark.parametrize(("source_status", "requested_rows", "source_rows", "coverage_ratio"), [
    ("READY", 5, 5, 0.0),
    ("READY_EMPTY", 0, 0, 1.0),
    ("READY", 3, 3, None),
])
def test_complete_ready_empty_hk_product_remains_zero(
    source_status: str, requested_rows: int, source_rows: int,
    coverage_ratio: float | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    projected = _project({
        "trade_date": TRADE_DATE, "stage_id": "STAGE_0935_0940", "status": "READY_EMPTY",
        "markets": {"HK_CONNECT": {
            "market": "HK_CONNECT", "status": "READY_EMPTY", "selection_status": "READY_EMPTY",
            "source_status": source_status,
            "artifact_id": "selection-hk-empty", "run_id": "run-hk-empty",
            "raw_artifact_sha256": "d" * 64, "requested_rows": requested_rows, "source_rows": source_rows,
            "selected_rows": 0, "coverage_ratio": coverage_ratio, "source_evidence": ["fixture=verified-empty"],
            "rows": [], "cannot_confirm": [],
        }},
    }, tmp_path, monkeypatch)
    hk = projected["markets"]["HK"]
    assert hk["display_mode"] == "READY_EMPTY"
    assert hk["candidate_count"] == 0
    assert hk["observation_count"] == 0
    assert projected["status"] == "READY_EMPTY"
    assert projected["selected_hk_rows"] == 0
    assert projected["selected_total_rows"] == 0


@pytest.mark.parametrize(("source_status", "input_rows", "requested_rows"), [
    ("READY", 5, 5),
    ("READY_EMPTY", 0, 0),
])
def test_real_producer_consumer_projection_keeps_evidence_for_verified_hk_zero(
    source_status: str, input_rows: int, requested_rows: int,
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = ("exact_date=20260907", "stage_id=STAGE_0935_0940")
    projected, market = _project_real_hk_producer_market(
        source_status=source_status,
        input_rows=input_rows,
        requested_rows=requested_rows,
        source_evidence=evidence,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )

    assert market.get("source_evidence", []) == list(evidence)
    hk = projected["markets"]["HK"]
    assert hk["display_mode"] == "READY_EMPTY"
    assert hk["candidate_count"] == 0
    assert hk["observation_count"] == 0
    assert hk["source_evidence"] == list(evidence)
    assert projected["status"] == "READY_EMPTY"
    assert projected["selected_hk_rows"] == 0
    assert projected["selected_total_rows"] == 0


@pytest.mark.parametrize(("source_status", "input_rows", "requested_rows", "source_evidence", "missing_symbols", "cannot_confirm"), [
    ("READY", 5, 5, (), (), ()),
    ("READY", 5, 5, ("exact_date=20260907",), ("HK.00001",), ()),
    ("CANNOT_CONFIRM", 0, 0, ("exact_date=20260907",), (), ("SOURCE_INCOMPLETE",)),
])
def test_real_producer_consumer_projection_keeps_unproven_hk_zero_unknown(
    source_status: str, input_rows: int, requested_rows: int,
    source_evidence: tuple[str, ...], missing_symbols: tuple[str, ...],
    cannot_confirm: tuple[str, ...],
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    projected, market = _project_real_hk_producer_market(
        source_status=source_status,
        input_rows=input_rows,
        requested_rows=requested_rows,
        source_evidence=source_evidence,
        missing_symbols=missing_symbols,
        cannot_confirm=cannot_confirm,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )

    hk = projected["markets"]["HK"]
    assert market.get("source_evidence", []) == list(source_evidence)
    assert hk["display_mode"] == "CANNOT_CONFIRM"
    assert hk["candidate_count"] is None
    assert hk["selected_rows"] is None
    assert projected["status"] == "CANNOT_CONFIRM"
    assert projected["selected_hk_rows"] is None
    assert projected["selected_total_rows"] is None


@pytest.mark.parametrize("overrides", [
    {"source_status": "CANNOT_CONFIRM"},
    {"requested_rows": None, "source_rows": None},
    {"requested_rows": 2, "source_rows": 1},
    {"source_evidence": []},
    {"missing_symbols": ["HK.00001"]},
    {"cannot_confirm": ["SOURCE_INCOMPLETE"]},
    {"selected_rows": 1},
])
def test_incomplete_ready_empty_hk_product_stays_unknown(
    overrides: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    market = {
        "market": "HK_CONNECT", "status": "READY_EMPTY", "selection_status": "READY_EMPTY",
        "source_status": "READY", "artifact_id": "selection-hk-empty", "run_id": "run-hk-empty",
        "raw_artifact_sha256": "e" * 64, "requested_rows": 0, "source_rows": 0,
        "selected_rows": 0, "coverage_ratio": 1.0, "source_evidence": ["fixture=verified-empty"],
        "rows": [], "cannot_confirm": [],
    }
    market.update(overrides)
    projected = _project({
        "trade_date": TRADE_DATE, "stage_id": "STAGE_0935_0940", "status": "READY_EMPTY",
        "markets": {"HK_CONNECT": market},
    }, tmp_path, monkeypatch)
    hk = projected["markets"]["HK"]
    assert hk["display_mode"] == "CANNOT_CONFIRM"
    assert hk["candidate_count"] is None
    assert hk["selected_rows"] is None
    assert projected["status"] == "CANNOT_CONFIRM"
    assert projected["selected_hk_rows"] is None
    assert projected["selected_total_rows"] is None
    assert "HK_READY_EMPTY_INPUT_OR_SOURCE_EVIDENCE_INCOMPLETE" in hk["display_reasons"]
    assert "HK:HK_READY_EMPTY_INPUT_OR_SOURCE_EVIDENCE_INCOMPLETE" in projected["stage"]["cannot_confirm"]


def test_ready_hk_product_without_rows_is_unknown_not_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    projected = _project({
        "trade_date": TRADE_DATE, "stage_id": "STAGE_0935_0940", "status": "READY",
        "markets": {"HK_CONNECT": {
            "market": "HK_CONNECT", "status": "READY", "selection_status": "READY",
            "artifact_id": "selection-hk-empty-ready", "run_id": "run-hk-empty-ready",
            "raw_artifact_sha256": "f" * 64, "selected_rows": 0, "rows": [], "cannot_confirm": [],
        }},
        "execution_evidence": {"markets": {"HK_CONNECT": {
            "selection_binding": "BOUND_TO_VERIFIED_SELECTION", "reasons": [],
        }}},
    }, tmp_path, monkeypatch)
    hk = projected["markets"]["HK"]
    assert hk["display_mode"] == "CANNOT_CONFIRM"
    assert hk["candidate_count"] is None
    assert hk["selected_rows"] is None
    assert projected["status"] == "CANNOT_CONFIRM"
    assert projected["selected_hk_rows"] is None
    assert projected["selected_total_rows"] is None
    assert "HK_READY_SELECTION_HAS_NO_ROWS" in hk["display_reasons"]
    assert "HK:HK_READY_SELECTION_HAS_NO_ROWS" in projected["stage"]["cannot_confirm"]


def test_manager_route_preserves_selection_contract_for_unbound_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    projected = _project({
        "trade_date": TRADE_DATE, "stage_id": "STAGE_0935_0940", "status": "READY",
        "markets": {"HK_CONNECT": {
            "market": "HK_CONNECT", "status": "READY", "selection_status": "READY",
            "artifact_id": "selection-hk-unbound", "run_id": "run-hk-unbound",
            "raw_artifact_sha256": "g" * 64, "source_status": "READY",
            "requested_rows": 1, "source_rows": 1, "selected_rows": 1, "coverage_ratio": 1.0,
            "source_evidence": ["exact_date=20260907"], "missing_symbols": [],
            "rows": [{"code": "HK.00001", "rank": 1, "formal_eligible": True}], "cannot_confirm": [],
        }},
        "execution_evidence": {"markets": {"HK_CONNECT": {
            "selection_binding": "NO_VERIFIED_SELECTION_BINDING", "reasons": ["EXECUTION_NOT_BOUND"],
        }}},
    }, tmp_path, monkeypatch, route_path="/api/v3/manager/stage-selection")
    hk = projected["markets"]["HK"]
    assert hk["status"] == hk["selection_status"] == "READY"
    assert hk["selected_rows"] == 1
    assert hk["rows"] == [{"code": "HK.00001", "rank": 1, "formal_eligible": True}]
    assert "display_mode" not in hk
    assert projected["selected_hk_rows"] == 1


def test_manager_route_accepts_unknown_consumer_counts_as_null(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from stage_center.consumer import _invalid_market

    projected = _project({
        "trade_date": TRADE_DATE, "stage_id": "STAGE_0935_0940", "status": "CANNOT_CONFIRM",
        "markets": {"HK_CONNECT": {
            **_invalid_market("HK_CONNECT"),
            "cannot_confirm": ["SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID"],
        }},
    }, tmp_path, monkeypatch, route_path="/api/v3/manager/stage-selection")
    hk = projected["markets"]["HK"]
    assert hk["status"] == hk["selection_status"] == "CANNOT_CONFIRM"
    assert hk["selected_rows"] is None
    assert hk["rows"] == []
