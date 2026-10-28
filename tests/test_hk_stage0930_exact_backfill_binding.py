from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from stage_center.selection import SelectionStore


TRADE_DATE = "20260925"
STAGE_ID = "STAGE_0930_0935"
MARKET = "HK_CONNECT"
BACKFILL_RUN_ID = "55742332ec504f119a54c42ce9cad3cd"
RAW_SHA256 = "02229d41078a562a3863124dc799c37c1c087759744d4254b640873c1b5adefd"
ALGORITHM_SHA256 = "fa010779e194b06ee9a77799d6b41a8d76a641a047b05b96c4594766e4497506"
DAY24_TRADE_DATE = "20260924"
DAY24_BACKFILL_RUN_ID = "1d3ab9f9bd3a44c3811bf1fed2b74108"
DAY24_RAW_SHA256 = "709a5d00bb4507bd6cc32ad9bf1b4e0e4615fe702262b39088b6fad3505f10c1"
DAY24_SELECTION_ARTIFACT_SHA256 = "6c0d7edba26455714421a4af7b625573679416fc97ed8accea6a939508081c87"
DAY24_RUNNER_RECEIPT_SHA256 = "70a9c5bb6637f14218d99a18c4f02e0cc7c18086f3a89056185c90a589e6bbfa"


def _day24_selection_envelope() -> dict[str, Any]:
    from apps.api.v35_api.app import _APPROVED_EXACT_STAGE_BACKFILLS

    binding = _APPROVED_EXACT_STAGE_BACKFILLS[
        (DAY24_TRADE_DATE, STAGE_ID, MARKET, DAY24_BACKFILL_RUN_ID)
    ]
    rows = [
        {
            "code": f"HK.{index:05d}",
            "rank": index,
            "name": f"Observation {index}",
            "action_level": "NO_BUY",
            "trade_status": "WATCH_ONLY" if index == 1 else "NO_TRADE",
            "status": "WATCH_ONLY" if index == 1 else "NO_TRADE",
            "source_mode": "HK_CONNECT_FOUR_LANE",
            "formal_eligible": False,
        }
        for index in range(1, 11)
    ]
    return {
        "schema_version": "stage_center.selection.v2",
        "trade_date": DAY24_TRADE_DATE,
        "stage_id": STAGE_ID,
        "market": MARKET,
        "algorithm_id": binding["algorithm_id"],
        "algorithm_sha256": binding["algorithm_sha256"],
        "raw_artifact_sha256": DAY24_RAW_SHA256,
        "source_status": "PARTIAL_WITH_ROWS",
        "selection_status": "PARTIAL_WITH_ROWS",
        "requested_rows": 100,
        "source_rows": 100,
        "selected_rows": 10,
        "coverage_ratio": 0.1,
        "missing_symbols": [],
        "rows": rows,
        "source_evidence": list(binding["required_evidence"]),
        "cannot_confirm": [
            "HISTORICAL_CAPTURE_AFTER_TARGET_CUTOFF_NOT_PIT_SAFE",
            "HISTORICAL_FORMAL_STAGE_ELIGIBILITY_CANNOT_CONFIRM",
            "HISTORICAL_NATURAL_TIME_CAPTURE_CANNOT_CONFIRM",
            "HISTORICAL_ACTIVE_SNAPSHOT_AUTHORITY_CANNOT_CONFIRM",
            "HISTORICAL_SOURCE_TIMEZONE_NOT_ATTESTED",
            "HISTORICAL_TDX_PRICE_BASIS_AND_VOLUME_TURNOVER_UNITS_NOT_INDEPENDENTLY_CONFIRMED",
            "HISTORICAL_D1_FORMAL_ELIGIBILITY_CANNOT_CONFIRM",
            "HISTORICAL_D1_INPUT_GAP_CANNOT_CONFIRM:HK.02915:rank=45",
        ],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _write_day24_runner_receipt(
    receipt_root: Path,
    envelope: dict[str, Any],
    published: dict[str, Any],
) -> str:
    receipt_path = (
        receipt_root
        / "backfill"
        / DAY24_BACKFILL_RUN_ID
        / DAY24_TRADE_DATE
        / STAGE_ID
        / "receipt.json"
    )
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(
        json.dumps(
            {
                "schema_version": "stage_center.runner.receipt.v1",
                "runner": "stage_center",
                "mode": "BACKFILL",
                "backfill_run_id": DAY24_BACKFILL_RUN_ID,
                "due_status": "HISTORICAL_BACKFILL",
                "trade_date": DAY24_TRADE_DATE,
                "stage_id": STAGE_ID,
                "latest_updated": False,
                "current_updated": False,
                "write_performed": True,
                "markets": {
                    MARKET: {
                        "run_id": published["run_id"],
                        "artifact_id": published["artifact_id"],
                        "raw_artifact_sha256": envelope["raw_artifact_sha256"],
                        "selection_status": envelope["selection_status"],
                    }
                },
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return hashlib.sha256(receipt_path.read_bytes()).hexdigest()


def _selection_envelope() -> dict[str, Any]:
    from stage_center.contracts import SELECTION_ALGORITHM_ID

    from apps.api.v35_api.app import _APPROVED_EXACT_STAGE_BACKFILLS

    evidence = _APPROVED_EXACT_STAGE_BACKFILLS[
        (TRADE_DATE, STAGE_ID, MARKET, BACKFILL_RUN_ID)
    ]["required_evidence"]
    rows = [
        {
            "code": f"HK.{index:05d}",
            "rank": index,
            "name": f"Observation {index}",
            "action_level": "NO_BUY",
            "trade_status": "WATCH_ONLY",
            "status": "WATCH_ONLY",
            "source_mode": "HK_CONNECT_FOUR_LANE",
            "formal_eligible": False,
        }
        for index in range(1, 11)
    ]
    return {
        "schema_version": "stage_center.selection.v2",
        "trade_date": TRADE_DATE,
        "stage_id": STAGE_ID,
        "market": MARKET,
        "algorithm_id": SELECTION_ALGORITHM_ID,
        "algorithm_sha256": ALGORITHM_SHA256,
        "raw_artifact_sha256": RAW_SHA256,
        "source_status": "PARTIAL_WITH_ROWS",
        "selection_status": "PARTIAL_WITH_ROWS",
        "requested_rows": 100,
        "source_rows": 96,
        "selected_rows": 10,
        "coverage_ratio": 0.1,
        "missing_symbols": [],
        "rows": rows,
        "source_evidence": list(evidence),
        "cannot_confirm": [f"UNKNOWN_{index}" for index in range(12)],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _write_runner_receipt(
    receipt_root: Path,
    envelope: dict[str, Any],
    published: dict[str, Any],
) -> str:
    receipt_path = (
        receipt_root
        / "backfill"
        / BACKFILL_RUN_ID
        / TRADE_DATE
        / STAGE_ID
        / "receipt.json"
    )
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(
        json.dumps(
            {
                "schema_version": "stage_center.runner.receipt.v1",
                "runner": "stage_center",
                "mode": "BACKFILL",
                "backfill_run_id": BACKFILL_RUN_ID,
                "due_status": "HISTORICAL_BACKFILL",
                "trade_date": TRADE_DATE,
                "stage_id": STAGE_ID,
                "latest_updated": False,
                "current_updated": False,
                "write_performed": True,
                "markets": {
                    MARKET: {
                        "run_id": published["run_id"],
                        "artifact_id": published["artifact_id"],
                        "raw_artifact_sha256": envelope["raw_artifact_sha256"],
                        "selection_status": envelope["selection_status"],
                    }
                },
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return hashlib.sha256(receipt_path.read_bytes()).hexdigest()


def _catalog_store(root: Path):
    from infrastructure.data_store import NativeDataStore

    store = NativeDataStore(root / "data")
    store.import_catalog(
        {
            "schema_version": "v3_trade_calendar.v1",
            "system_date": TRADE_DATE,
            "stage_dates": [],
            "future_target_dates": [],
            "materialized_rows": {},
        }
    )
    return store


def _configured_client(
    tmp_path: Path,
    monkeypatch: Any,
    *,
    include_runner_receipt: bool = True,
    wrong_expected_runner_sha: bool = False,
    include_ordinary_selection: bool = False,
) -> tuple[TestClient, dict[str, Any]]:
    from apps.api.v35_api import app as app_module
    from apps.api.v35_api.app import create_app

    selection_root = tmp_path / "stage" / "selection"
    backfill_store = SelectionStore(
        selection_root / "backfill" / BACKFILL_RUN_ID
    )
    envelope = _selection_envelope()
    published = backfill_store.publish(envelope, market=MARKET)
    latest = backfill_store._latest()
    entry = latest["entries"][backfill_store._key(TRADE_DATE, STAGE_ID, MARKET)]
    receipt_root = selection_root.parent / "receipts"
    runner_sha = (
        _write_runner_receipt(receipt_root, envelope, published)
        if include_runner_receipt
        else None
    )
    if include_ordinary_selection:
        ordinary = dict(envelope)
        ordinary["raw_artifact_sha256"] = "b" * 64
        ordinary["source_evidence"] = ["ordinary_selection_fixture"]
        SelectionStore(selection_root).publish(ordinary, market=MARKET)

    binding = {
        "selection_run_id": published["run_id"],
        "artifact_id": published["artifact_id"],
        "raw_artifact_sha256": envelope["raw_artifact_sha256"],
        "algorithm_id": envelope["algorithm_id"],
        "algorithm_sha256": envelope["algorithm_sha256"],
        "selection_status": envelope["selection_status"],
        "source_status": envelope["source_status"],
        "selected_rows": envelope["selected_rows"],
        "source_rows": envelope["source_rows"],
        "cannot_confirm_count": len(envelope["cannot_confirm"]),
        "selection_manifest_sha256": entry["manifest_sha256"],
        "selection_receipt_sha256": entry["receipt_sha256"],
        "selection_artifact_sha256": entry["artifact_sha256"],
        "runner_receipt_sha256": (
            "f" * 64 if wrong_expected_runner_sha else runner_sha or "f" * 64
        ),
        "required_evidence": tuple(envelope["source_evidence"]),
    }
    monkeypatch.setitem(
        app_module._APPROVED_EXACT_STAGE_BACKFILLS,
        (TRADE_DATE, STAGE_ID, MARKET, BACKFILL_RUN_ID),
        binding,
    )
    catalog = _catalog_store(tmp_path)
    client = TestClient(
        create_app(
            data_root=catalog.root,
            stage_center_selection_root=selection_root,
            current_date=TRADE_DATE,
        )
    )
    return client, binding


def _configured_day24_client(
    tmp_path: Path,
    monkeypatch: Any,
    *,
    include_ordinary_selection: bool = False,
) -> tuple[TestClient, dict[str, Any]]:
    from apps.api.v35_api import app as app_module
    from apps.api.v35_api.app import create_app

    selection_root = tmp_path / "stage" / "selection"
    backfill_store = SelectionStore(
        selection_root / "backfill" / DAY24_BACKFILL_RUN_ID
    )
    envelope = _day24_selection_envelope()
    published = backfill_store.publish(envelope, market=MARKET)
    latest = backfill_store._latest()
    entry = latest["entries"][backfill_store._key(DAY24_TRADE_DATE, STAGE_ID, MARKET)]
    receipt_root = selection_root.parent / "receipts"
    runner_sha = _write_day24_runner_receipt(receipt_root, envelope, published)
    binding = {
        "selection_run_id": published["run_id"],
        "artifact_id": published["artifact_id"],
        "raw_artifact_sha256": envelope["raw_artifact_sha256"],
        "algorithm_id": envelope["algorithm_id"],
        "algorithm_sha256": envelope["algorithm_sha256"],
        "selection_status": envelope["selection_status"],
        "source_status": envelope["source_status"],
        "selected_rows": envelope["selected_rows"],
        "source_rows": envelope["source_rows"],
        "cannot_confirm_count": len(envelope["cannot_confirm"]),
        "selection_manifest_sha256": entry["manifest_sha256"],
        "selection_receipt_sha256": entry["receipt_sha256"],
        "selection_artifact_sha256": entry["artifact_sha256"],
        "runner_receipt_sha256": runner_sha,
        "required_evidence": tuple(envelope["source_evidence"]),
    }
    if include_ordinary_selection:
        from stage_center.selection import select_a_stage

        a_rows = [
            {
                "code": f"A.{index:06d}",
                "first_open": 10.0,
                "last_close": 10.2,
                "high": 10.4,
                "low": 9.9,
                "amount": 1_000_000,
                "bar_count": 5,
                "expected_rows": 5,
            }
            for index in range(1, 190)
        ]
        a_envelope = select_a_stage(
            a_rows,
            DAY24_TRADE_DATE,
            STAGE_ID,
            "a" * 64,
            source_status="PARTIAL_WITH_ROWS",
            requested_rows=193,
            missing_symbols=("A.000190", "A.000191", "A.000192", "A.000193"),
            cannot_confirm=("A_CURRENT_SELECTION_PARTIAL",),
            source_evidence=("fixture=current_a_share_selection",),
        )
        a_published = SelectionStore(selection_root).publish(
            a_envelope, market="A_SHARE"
        )
        ordinary_hk = dict(envelope)
        ordinary_hk.update(
            {
                "raw_artifact_sha256": "b" * 64,
                "requested_rows": 100,
                "source_rows": 98,
                "coverage_ratio": 0.98,
                "source_evidence": ["fixture=existing_hk_ordinary_selection"],
                "cannot_confirm": ["ORDINARY_HK_GAP_1", "ORDINARY_HK_GAP_2"],
            }
        )
        hk_published = SelectionStore(selection_root).publish(
            ordinary_hk, market=MARKET
        )
        binding["ordinary_a_run_id"] = a_published["run_id"]
        binding["ordinary_hk_run_id"] = hk_published["run_id"]
    monkeypatch.setitem(
        app_module._APPROVED_EXACT_STAGE_BACKFILLS,
        (DAY24_TRADE_DATE, STAGE_ID, MARKET, DAY24_BACKFILL_RUN_ID),
        binding,
    )
    catalog = _catalog_store(tmp_path)
    client = TestClient(
        create_app(
            data_root=catalog.root,
            stage_center_selection_root=selection_root,
            current_date=DAY24_TRADE_DATE,
        )
    )
    return client, binding


def _exact_params(**overrides: str) -> dict[str, str]:
    params = {
        "date": TRADE_DATE,
        "stage": STAGE_ID,
        "limit": "50",
        "market": MARKET,
        "backfill_run_id": BACKFILL_RUN_ID,
    }
    params.update(overrides)
    return params


def _day24_exact_params(**overrides: str) -> dict[str, str]:
    params = {
        "date": DAY24_TRADE_DATE,
        "stage": STAGE_ID,
        "limit": "50",
        "market": MARKET,
        "backfill_run_id": DAY24_BACKFILL_RUN_ID,
    }
    params.update(overrides)
    return params


def test_day25_binding_pins_the_published_selection_and_runner_receipts() -> None:
    from apps.api.v35_api.app import _APPROVED_EXACT_STAGE_BACKFILLS

    binding = _APPROVED_EXACT_STAGE_BACKFILLS[
        (TRADE_DATE, STAGE_ID, MARKET, BACKFILL_RUN_ID)
    ]
    assert binding["selection_run_id"] == "run-00ed21b8213cc63c7c1bebc3"
    assert binding["artifact_id"] == "selection-00ed21b8213cc63c7c1bebc3"
    assert binding["raw_artifact_sha256"] == RAW_SHA256
    assert binding["selection_manifest_sha256"] == (
        "8f8fa02aa165d53641f546bc64d6d8cfd43150e1aadfe4c95a21205ea58fbc01"
    )
    assert binding["selection_receipt_sha256"] == (
        "00d21a26efa9ff3b960a2765e5a4a4599ff9c7567338f942ffc18676dbbab217"
    )
    assert binding["selection_artifact_sha256"] == (
        "8e32219e33962113527f78f0d0a2bc44276a39345264dd2c968d533bc324ed01"
    )
    assert binding["runner_receipt_sha256"] == (
        "57c0ebadf08e372f2165b624d54b9287737451a9545cc11a9c2015e42c51deae"
    )


def test_day24_binding_pins_the_r4_selection_and_runner_receipts() -> None:
    from apps.api.v35_api.app import _APPROVED_EXACT_STAGE_BACKFILLS

    binding = _APPROVED_EXACT_STAGE_BACKFILLS[
        (DAY24_TRADE_DATE, STAGE_ID, MARKET, DAY24_BACKFILL_RUN_ID)
    ]
    assert binding["selection_run_id"] == "run-1f781dcc3ea56ab3c3e97c70"
    assert binding["artifact_id"] == "selection-1f781dcc3ea56ab3c3e97c70"
    assert binding["raw_artifact_sha256"] == DAY24_RAW_SHA256
    assert binding["source_rows"] == 100
    assert binding["selected_rows"] == 10
    assert binding["cannot_confirm_count"] == 8
    assert binding["selection_manifest_sha256"] == (
        "21040d9758662b43892b2b64b9fd5fe13baf876b5f74bd928179317c5123ab1d"
    )
    assert binding["selection_receipt_sha256"] == (
        "c7abf5f56e6256eac0bb7cfef78422c4f1d9e0ce3cfe0f93f69768bf8f1f916e"
    )
    assert binding["selection_artifact_sha256"] == DAY24_SELECTION_ARTIFACT_SHA256
    assert binding["runner_receipt_sha256"] == DAY24_RUNNER_RECEIPT_SHA256


def test_exact_day24_binding_returns_verified_observation_rows(
    tmp_path: Path, monkeypatch: Any
) -> None:
    client, binding = _configured_day24_client(tmp_path, monkeypatch)

    response = client.get("/api/v3/workbench/stage", params=_day24_exact_params())

    assert response.status_code == 200
    result = response.json()
    hk = result["markets"]["HK"]
    assert result["mode"] == "BACKFILL"
    assert result["backfill_run_id"] == DAY24_BACKFILL_RUN_ID
    assert hk["run_id"] == binding["selection_run_id"]
    assert hk["selection_mode"] == "BACKFILL"
    assert hk["selection_manifest_sha256"] == binding["selection_manifest_sha256"]
    assert hk["selection_receipt_sha256"] == binding["selection_receipt_sha256"]
    assert hk["selection_artifact_sha256"] == binding["selection_artifact_sha256"]
    assert hk["runner_receipt_verified"] is True
    assert hk["runner_receipt_sha256"] == binding["runner_receipt_sha256"]
    assert hk["display_mode"] == "OBSERVATION_UNVERIFIED"
    assert hk["requested_rows"] == 100
    assert hk["source_rows"] == 100
    assert hk["observation_count"] == 10
    assert hk["selected_rows"] is None
    assert len(hk["rows"]) == 10
    assert all(row["action_level"] == "NO_BUY" for row in hk["rows"])
    assert all(row["formal_eligible"] is False for row in hk["rows"])
    assert "HISTORICAL_D1_INPUT_GAP_CANNOT_CONFIRM:HK.02915:rank=45" in hk["cannot_confirm"]
    assert result["RESEARCH_ONLY"] is True
    assert result["write_performed"] is False
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False


def test_day24_default_page_keeps_a_and_uses_exact_hk_backfill(
    tmp_path: Path, monkeypatch: Any
) -> None:
    client, binding = _configured_day24_client(
        tmp_path, monkeypatch, include_ordinary_selection=True
    )

    response = client.get(
        "/api/v3/workbench/stage",
        params={"date": DAY24_TRADE_DATE, "stage": STAGE_ID, "limit": 50},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert "backfill_run_id" not in result
    assert set(result["markets"]) == {"A", "HK"}
    a = result["markets"]["A"]
    hk = result["markets"]["HK"]
    assert a["run_id"] == binding["ordinary_a_run_id"]
    assert a["requested_rows"] == 193
    assert a["source_rows"] == 189
    assert len(a["rows"]) == 10
    assert result["RESEARCH_ONLY"] is True
    assert a["RESEARCH_ONLY"] is True
    assert hk["run_id"] == binding["selection_run_id"]
    assert hk["backfill_run_id"] == DAY24_BACKFILL_RUN_ID
    assert hk["raw_artifact_sha256"] == DAY24_RAW_SHA256
    assert hk["requested_rows"] == 100
    assert hk["source_rows"] == 100
    assert hk["observation_count"] == 10
    assert len(hk["rows"]) == 10
    assert hk["display_mode"] == "OBSERVATION_UNVERIFIED"
    assert hk["RESEARCH_ONLY"] is True
    assert hk["runner_receipt_verified"] is True
    assert hk["selection_mode"] == "BACKFILL"
    assert hk["run_id"] != binding["ordinary_hk_run_id"]
    assert result["market_readback_bindings"]["single_bundle_artifact_id"] is None
    assert result["market_readback_bindings"]["markets"]["A_SHARE"]["run_id"] == a[
        "run_id"
    ]
    assert result["market_readback_bindings"]["markets"]["HK_CONNECT"][
        "backfill_run_id"
    ] == DAY24_BACKFILL_RUN_ID
    assert {row["market"] for row in result["unified_rows"]} == {"A", "HK"}
    assert all(result[flag] is False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
    execution = result["execution_evidence"]
    assert execution["status"] == "SELECTION_REFERENCES_PARTIALLY_BOUND_EXECUTION_UNVERIFIED"
    assert execution["execution_verified"] is False
    assert execution["natural_verified"] is False
    assert execution["cannot_confirm"] == [
        "NO_SINGLE_A_HK_EXECUTION_RECEIPT_FOR_MARKET_SCOPED_READBACK"
    ]
    hk_execution = execution["markets"]["HK_CONNECT"]
    assert hk_execution["selection_binding"] == "BOUND_TO_VERIFIED_SELECTION"
    assert hk_execution["runner_receipt_verified"] is True
    assert hk_execution["runner_receipt_sha256"] == hk["runner_receipt_sha256"]
    assert hk_execution["execution_verified"] is False
    assert hk_execution["natural_verified"] is False
    a_execution = execution["markets"].get("A_SHARE")
    assert not isinstance(a_execution, dict) or a_execution.get(
        "selection_binding"
    ) != "BOUND_TO_VERIFIED_SELECTION"


@pytest.mark.parametrize(
    "overrides",
    [
        {"date": "20260925"},
        {"market": "A_SHARE"},
        {"backfill_run_id": "unapproved-day24-run"},
    ],
)
def test_wrong_day24_date_market_or_run_cannot_use_exact_binding(
    tmp_path: Path, monkeypatch: Any, overrides: dict[str, str]
) -> None:
    client, _ = _configured_day24_client(tmp_path, monkeypatch)

    response = client.get(
        "/api/v3/workbench/stage",
        params=_day24_exact_params(**overrides),
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "backfill selection identity is unavailable"


def test_exact_hk_backfill_binding_returns_verified_observation_rows(
    tmp_path: Path, monkeypatch: Any
) -> None:
    client, binding = _configured_client(tmp_path, monkeypatch)

    response = client.get("/api/v3/workbench/stage", params=_exact_params())

    assert response.status_code == 200
    result = response.json()
    hk = result["markets"]["HK"]
    assert result["mode"] == "BACKFILL"
    assert result["backfill_run_id"] == BACKFILL_RUN_ID
    assert hk["run_id"] == binding["selection_run_id"]
    assert hk["selection_mode"] == "BACKFILL"
    assert hk["selection_manifest_sha256"] == binding["selection_manifest_sha256"]
    assert hk["selection_receipt_sha256"] == binding["selection_receipt_sha256"]
    assert hk["selection_artifact_sha256"] == binding["selection_artifact_sha256"]
    assert hk["runner_receipt_verified"] is True
    assert hk["runner_receipt_sha256"] == binding["runner_receipt_sha256"]
    assert hk["display_mode"] == "OBSERVATION_UNVERIFIED"
    assert hk["observation_count"] == 10
    assert hk["selected_rows"] is None
    assert len(hk["rows"]) == 10
    assert result["RESEARCH_ONLY"] is True
    assert result["write_performed"] is False
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"date": "20260924"},
        {"market": "A_SHARE"},
        {"backfill_run_id": "unapproved-run"},
    ],
)
def test_wrong_date_market_or_run_cannot_use_exact_binding(
    tmp_path: Path, monkeypatch: Any, overrides: dict[str, str]
) -> None:
    client, _ = _configured_client(tmp_path, monkeypatch)

    response = client.get(
        "/api/v3/workbench/stage", params=_exact_params(**overrides)
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "backfill selection identity is unavailable"


def test_exact_binding_requires_market_and_run_id_together(
    tmp_path: Path, monkeypatch: Any
) -> None:
    client, _ = _configured_client(tmp_path, monkeypatch)
    params = _exact_params()
    params.pop("backfill_run_id")

    response = client.get("/api/v3/workbench/stage", params=params)

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("include_runner_receipt", "wrong_expected_runner_sha"),
    [(False, False), (True, True)],
)
def test_missing_or_wrong_sha_runner_receipt_cannot_verify(
    tmp_path: Path,
    monkeypatch: Any,
    include_runner_receipt: bool,
    wrong_expected_runner_sha: bool,
) -> None:
    client, _ = _configured_client(
        tmp_path,
        monkeypatch,
        include_runner_receipt=include_runner_receipt,
        wrong_expected_runner_sha=wrong_expected_runner_sha,
    )

    response = client.get("/api/v3/workbench/stage", params=_exact_params())

    assert response.status_code == 409
    assert response.json()["detail"] == "backfill runner receipt identity is invalid"


def test_ordinary_workbench_request_keeps_default_selection_behavior(
    tmp_path: Path, monkeypatch: Any
) -> None:
    client, _ = _configured_client(
        tmp_path, monkeypatch, include_ordinary_selection=True
    )

    response = client.get(
        "/api/v3/workbench/stage",
        params={"date": TRADE_DATE, "stage": STAGE_ID, "limit": 50},
    )

    assert response.status_code == 200
    hk = response.json()["markets"]["HK"]
    assert "selection_mode" not in hk
    assert hk.get("backfill_run_id") is None
    assert hk["raw_artifact_sha256"] == "b" * 64
    assert hk["display_mode"] == "OBSERVATION_UNVERIFIED"
    assert hk["observation_count"] == 10
    assert hk["selected_rows"] is None
