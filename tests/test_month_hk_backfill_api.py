from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import pytest
from fastapi.testclient import TestClient

from stage_center.selection import SelectionStore


from apps.api.v35_api import app as _api_module_for_bindings

_R8_CANDIDATE_BATCH_RECEIPT = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_MONTH_BACKFILL_20261007/evidence/"
    "hk_observation_candidates_r8/candidate_batch_receipt_r8.json"
)

_ACTIVE_R5_BINDINGS = tuple(
    item
    for item in _api_module_for_bindings._MONTH_HK_AFTERFACT_R5_BINDINGS
    if (
        item["date"],
        item["stage_id"],
        item["market"],
        item["backfill_run_id"],
    ) not in _api_module_for_bindings._REVOKED_HK_STAGE_BACKFILL_KEYS
)


def _write_catalog(root: Path, trade_date: str) -> Path:
    from infrastructure.data_store import NativeDataStore

    store = NativeDataStore(root / "data")
    store.import_catalog(
        {
            "schema_version": "v3_trade_calendar.v1",
            "system_date": trade_date,
            "stage_dates": [],
            "future_target_dates": [],
            "materialized_rows": {},
        }
    )
    return store.root


def _selection_envelope(binding: dict[str, Any]) -> dict[str, Any]:
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
        "trade_date": binding["date"],
        "stage_id": binding["stage_id"],
        "market": binding["market"],
        "algorithm_id": binding["algorithm_id"],
        "algorithm_sha256": binding["algorithm_sha256"],
        "raw_artifact_sha256": binding["raw_artifact_sha256"],
        "source_status": binding["source_status"],
        "selection_status": binding["selection_status"],
        "requested_rows": 100,
        "source_rows": binding["source_rows"],
        "selected_rows": binding["selected_rows"],
        "coverage_ratio": binding["selected_rows"] / 100,
        "missing_symbols": [],
        "rows": rows,
        "source_evidence": list(binding["required_evidence"]),
        "cannot_confirm": ["FORMAL", "PIT", "NATURAL"],
        "formal_eligible": False,
        "observation_status": "OBSERVATION_UNVERIFIED",
        "formal_stage_eligibility": "CANNOT_CONFIRM",
        "natural_time_capture": "CANNOT_CONFIRM",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _write_runner_receipt(
    receipt_root: Path,
    binding: dict[str, Any],
    envelope: dict[str, Any],
    published: dict[str, Any],
) -> str:
    receipt_path = (
        receipt_root
        / "backfill"
        / binding["backfill_run_id"]
        / binding["date"]
        / binding["stage_id"]
        / "receipt.json"
    )
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(
        json.dumps(
            {
                "schema_version": "stage_center.runner.receipt.v1",
                "runner": "stage_center",
                "mode": "BACKFILL",
                "backfill_run_id": binding["backfill_run_id"],
                "due_status": "HISTORICAL_BACKFILL",
                "trade_date": binding["date"],
                "stage_id": binding["stage_id"],
                "latest_updated": False,
                "current_updated": False,
                "write_performed": True,
                "markets": {
                    binding["market"]: {
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


def _runtime_binding(
    static_binding: dict[str, Any],
    published: dict[str, Any],
    latest_entry: dict[str, Any],
    runner_sha256: str,
) -> dict[str, Any]:
    binding = dict(static_binding)
    binding.update(
        {
            "selection_run_id": published["run_id"],
            "artifact_id": published["artifact_id"],
            "selection_manifest_sha256": latest_entry["manifest_sha256"],
            "selection_receipt_sha256": latest_entry["receipt_sha256"],
            "selection_artifact_sha256": latest_entry["artifact_sha256"],
            "runner_receipt_sha256": runner_sha256,
        }
    )
    return binding


@pytest.mark.parametrize(
    "static_binding",
    _ACTIVE_R5_BINDINGS,
    ids=lambda item: f"{item['date']}-{item['stage_id']}",
)
def test_r5_afterfact_candidate_has_exact_read_only_api_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    static_binding: dict[str, Any],
) -> None:
    from apps.api.v35_api import app as app_module
    from apps.api.v35_api.app import create_app

    key = (
        static_binding["date"],
        static_binding["stage_id"],
        static_binding["market"],
        static_binding["backfill_run_id"],
    )
    registered = app_module._APPROVED_EXACT_STAGE_BACKFILLS[key]
    assert {
        key: value
        for key, value in static_binding.items()
        if key not in {"date", "stage_id", "market", "backfill_run_id"}
    } == registered
    assert static_binding["selected_rows"] == 10
    assert static_binding["source_rows"] in {75, 100}
    assert static_binding["cannot_confirm_count"] == 3
    assert "formal_pit=false" in static_binding["required_evidence"]
    assert "historical_observation_manifest_b64=" not in "\n".join(
        static_binding["required_evidence"]
    )

    selection_root = tmp_path / "stage" / "selection"
    store = SelectionStore(
        selection_root / "backfill" / static_binding["backfill_run_id"]
    )
    envelope = _selection_envelope(static_binding)
    published = store.publish(envelope, market=static_binding["market"])
    latest_entry = store._latest()["entries"][
        store._key(
            static_binding["date"],
            static_binding["stage_id"],
            static_binding["market"],
        )
    ]
    runner_sha256 = _write_runner_receipt(
        selection_root.parent / "receipts",
        static_binding,
        envelope,
        published,
    )
    monkeypatch.setitem(
        app_module._APPROVED_EXACT_STAGE_BACKFILLS,
        key,
        _runtime_binding(static_binding, published, latest_entry, runner_sha256),
    )

    client = TestClient(
        create_app(
            data_root=_write_catalog(tmp_path, static_binding["date"]),
            stage_center_selection_root=selection_root,
            current_date=static_binding["date"],
        )
    )
    response = client.get(
        "/api/v3/workbench/stage",
        params={
            "date": static_binding["date"],
            "stage": static_binding["stage_id"],
            "market": static_binding["market"],
            "backfill_run_id": static_binding["backfill_run_id"],
            "limit": 50,
        },
    )

    assert response.status_code == 200, response.text
    result = response.json()
    market = result["selection_markets"]["HK_CONNECT"]
    assert result["mode"] == "BACKFILL"
    assert result["market"] == "HK_CONNECT"
    assert result["backfill_run_id"] == static_binding["backfill_run_id"]
    assert market["run_id"] == published["run_id"]
    assert market["runner_receipt_verified"] is True
    assert market["selection_manifest_receipt_verified"] is True
    assert len(market["rows"]) == 10
    assert all(
        row["action_level"] == "NO_BUY"
        and row["trade_status"] == "WATCH_ONLY"
        and row["formal_eligible"] is False
        for row in market["rows"]
    )
    assert result["RESEARCH_ONLY"] is True
    assert result["write_performed"] is False
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False


@pytest.mark.parametrize(
    "static_binding",
    _ACTIVE_R5_BINDINGS,
    ids=lambda item: f"{item['date']}-{item['stage_id']}",
)
def test_r5_afterfact_api_rejects_wrong_exact_identity(
    tmp_path: Path,
    static_binding: dict[str, Any],
) -> None:
    from apps.api.v35_api.app import create_app

    client = TestClient(
        create_app(
            data_root=_write_catalog(tmp_path, static_binding["date"]),
            stage_center_selection_root=tmp_path / "stage" / "selection",
            current_date=static_binding["date"],
        )
    )
    response = client.get(
        "/api/v3/workbench/stage",
        params={
            "date": static_binding["date"],
            "stage": static_binding["stage_id"],
            "market": "A_SHARE",
            "backfill_run_id": static_binding["backfill_run_id"],
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "backfill selection identity is unavailable"


def test_daily_r2_candidate_registers_nine_and_serves_1545_read_only(
    tmp_path: Path,
) -> None:
    candidate = Path(
        "/Users/lexi/Desktop/学习/agents调试/V4_MONTH_BACKFILL_20261007/evidence/"
        "month_hk_backfill_api_r1/candidate_r2/apps/api/v35_api/app.py"
    )
    release_app_root = Path(
        "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/"
        "manager-us-mapping-daily-20261006-r2/app"
    )
    inline = r'''
import hashlib, importlib.util, json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, os.environ["RELEASE_APP_ROOT"])
spec = importlib.util.spec_from_file_location("daily_r2_api_candidate_test", os.environ["CANDIDATE_APP"])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
# Keep the candidate source as the executing code, but resolve companion
# runtime packages exactly as the daily-r2 release does.
module.__file__ = str(Path(os.environ["RELEASE_APP_ROOT"]) / "apps/api/v35_api/app.py")
assert len(module._MONTH_HK_AFTERFACT_R5_BINDINGS) == 9
assert "STAGE_1545_1555" in module._HK_CONNECT_BACKFILL_STAGES
for item in module._MONTH_HK_AFTERFACT_R5_BINDINGS:
    key = (item["date"], item["stage_id"], item["market"], item["backfill_run_id"])
    registered = module._APPROVED_STAGE_BACKFILLS[key]
    for field in ("selection_run_id", "raw_artifact_sha256", "selection_manifest_sha256", "selection_receipt_sha256", "selection_artifact_sha256", "runner_receipt_sha256"):
        assert registered[field] == item[field], (key, field)
static = next(item for item in module._MONTH_HK_AFTERFACT_R5_BINDINGS if item["date"] == "20261005" and item["stage_id"] == "STAGE_1545_1555")
from fastapi.testclient import TestClient
from infrastructure.data_store import NativeDataStore
from stage_center.selection import SelectionStore
with tempfile.TemporaryDirectory() as temp:
    root = Path(temp)
    data = NativeDataStore(root / "data")
    data.import_catalog({"schema_version":"v3_trade_calendar.v1", "system_date":static["date"], "stage_dates":[], "future_target_dates":[], "materialized_rows":{}})
    selection_root = root / "stage" / "selection"
    store = SelectionStore(selection_root / "backfill" / static["backfill_run_id"])
    rows = [{"code":f"HK.{i:05d}", "rank":i, "name":f"Observation {i}", "action_level":"NO_BUY", "trade_status":"WATCH_ONLY", "status":"WATCH_ONLY", "source_mode":"HK_CONNECT_FOUR_LANE", "formal_eligible":False} for i in range(1, 11)]
    envelope = {"schema_version":"stage_center.selection.v2", "trade_date":static["date"], "stage_id":static["stage_id"], "market":static["market"], "algorithm_id":static["algorithm_id"], "algorithm_sha256":static["algorithm_sha256"], "raw_artifact_sha256":static["raw_artifact_sha256"], "source_status":static["source_status"], "selection_status":static["selection_status"], "requested_rows":100, "source_rows":static["source_rows"], "selected_rows":10, "coverage_ratio":0.1, "missing_symbols":[], "rows":rows, "source_evidence":list(static["required_evidence"]), "cannot_confirm":["FORMAL","PIT","NATURAL"], "formal_eligible":False, "observation_status":"OBSERVATION_UNVERIFIED", "formal_stage_eligibility":"CANNOT_CONFIRM", "natural_time_capture":"CANNOT_CONFIRM", "production_allowed":False, "buy_gate_updated":False, "orders_sent":False}
    published = store.publish(envelope, market=static["market"])
    entry = store._latest()["entries"][store._key(static["date"], static["stage_id"], static["market"])]
    receipt = selection_root.parent / "receipts" / "backfill" / static["backfill_run_id"] / static["date"] / static["stage_id"] / "receipt.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(json.dumps({"schema_version":"stage_center.runner.receipt.v1", "runner":"stage_center", "mode":"BACKFILL", "backfill_run_id":static["backfill_run_id"], "due_status":"HISTORICAL_BACKFILL", "trade_date":static["date"], "stage_id":static["stage_id"], "latest_updated":False, "current_updated":False, "write_performed":True, "markets":{"HK_CONNECT":{"run_id":published["run_id"], "artifact_id":published["artifact_id"], "algorithm_sha256":envelope["algorithm_sha256"], "raw_artifact_sha256":envelope["raw_artifact_sha256"], "selection_status":envelope["selection_status"], "selected_rows":envelope["selected_rows"]}}, "production_allowed":False, "buy_gate_updated":False, "orders_sent":False}, sort_keys=True), encoding="utf-8")
    binding = dict(static)
    binding.update({"selection_run_id":published["run_id"], "artifact_id":published["artifact_id"], "selection_manifest_sha256":entry["manifest_sha256"], "selection_receipt_sha256":entry["receipt_sha256"], "selection_artifact_sha256":entry["artifact_sha256"], "runner_receipt_sha256":hashlib.sha256(receipt.read_bytes()).hexdigest()})
    key = (static["date"], static["stage_id"], static["market"], static["backfill_run_id"])
    module._APPROVED_STAGE_BACKFILLS[key] = binding
    client = TestClient(module.create_app(data_root=data.root, stage_center_selection_root=selection_root, current_date=static["date"]))
    response = client.get("/api/v3/workbench/stage", params={"date":static["date"], "stage":static["stage_id"], "market":static["market"], "backfill_run_id":static["backfill_run_id"], "limit":50})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["backfill_run_id"] == static["backfill_run_id"]
    assert result["selection_mode"] == "HISTORICAL_BACKFILL_READ_ONLY"
    assert result["RESEARCH_ONLY"] is True and result["write_performed"] is False
    assert all(result[field] is False for field in ("production_allowed", "buy_gate_updated", "orders_sent"))
print("daily-r2 candidate 9 exact bindings and Stage1545 API readback PASS")
'''
    env = dict(__import__("os").environ)
    env["CANDIDATE_APP"] = str(candidate)
    env["RELEASE_APP_ROOT"] = str(release_app_root)
    env["TMPDIR"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, "-c", inline],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "daily-r2 candidate 9 exact bindings and Stage1545 API readback PASS" in result.stdout


@pytest.mark.parametrize(
    "static_binding",
    _api_module_for_bindings._MONTH_HK_AFTERFACT_R8_BINDINGS,
    ids=lambda item: f"r8-{item['date']}-{item['stage_id']}",
)
def test_r8_exact_target_candidate_overrides_nonempty_ordinary_stage_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    static_binding: dict[str, Any],
) -> None:
    from apps.api.v35_api import app as app_module
    from apps.api.v35_api.app import create_app

    assert len(app_module._MONTH_HK_AFTERFACT_R8_BINDINGS) == 15
    key = (
        static_binding["date"],
        static_binding["stage_id"],
        static_binding["market"],
        static_binding["backfill_run_id"],
    )
    registered = app_module._APPROVED_EXACT_STAGE_BACKFILLS[key]
    assert registered["raw_artifact_sha256"] == static_binding["raw_artifact_sha256"]
    assert registered["selection_manifest_sha256"] == static_binding["selection_manifest_sha256"]
    assert registered["selection_receipt_sha256"] == static_binding["selection_receipt_sha256"]
    assert registered["selection_artifact_sha256"] == static_binding["selection_artifact_sha256"]
    assert registered["runner_receipt_sha256"] == static_binding["runner_receipt_sha256"]
    assert all(
        not marker.startswith("historical_observation_manifest_b64=")
        for marker in static_binding["required_evidence"]
    )

    selection_root = tmp_path / "stage" / "selection"
    stale_binding = dict(static_binding)
    stale_binding.update(
        {
            "raw_artifact_sha256": "a" * 64,
            "required_evidence": ("canonical_nonempty_source=true",),
        }
    )
    stale_envelope = _selection_envelope(stale_binding)
    for index, row in enumerate(stale_envelope["rows"], start=1):
        row["code"] = f"HK.{99000 + index:05d}"
        row["name"] = f"Superseded {index}"
    SelectionStore(selection_root).publish(stale_envelope, market="HK_CONNECT")

    candidate_store = SelectionStore(
        selection_root / "backfill" / static_binding["backfill_run_id"]
    )
    candidate_envelope = _selection_envelope(static_binding)
    published = candidate_store.publish(candidate_envelope, market="HK_CONNECT")
    latest_entry = candidate_store._latest()["entries"][
        candidate_store._key(
            static_binding["date"], static_binding["stage_id"], "HK_CONNECT"
        )
    ]
    runner_sha256 = _write_runner_receipt(
        selection_root.parent / "receipts",
        static_binding,
        candidate_envelope,
        published,
    )
    monkeypatch.setitem(
        app_module._APPROVED_EXACT_STAGE_BACKFILLS,
        key,
        _runtime_binding(static_binding, published, latest_entry, runner_sha256),
    )

    client = TestClient(
        create_app(
            data_root=_write_catalog(tmp_path, static_binding["date"]),
            stage_center_selection_root=selection_root,
            current_date=static_binding["date"],
        )
    )
    response = client.get(
        "/api/v3/workbench/stage",
        params={"date": static_binding["date"], "stage": static_binding["stage_id"]},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    hk = result["selection_markets"]["HK_CONNECT"]
    assert hk["backfill_run_id"] == static_binding["backfill_run_id"]
    assert hk["run_id"] == published["run_id"]
    assert hk["raw_artifact_sha256"] == static_binding["raw_artifact_sha256"]
    assert hk["source_rows"] == 100 and hk["selected_rows"] == 10
    pool_sha = next(
        marker.split("=", 1)[1]
        for marker in static_binding["required_evidence"]
        if marker.startswith("historical_pool_artifact_sha256=")
    )
    assert f"historical_pool_artifact_sha256={pool_sha}" in hk["source_evidence"]
    assert hk["superseded_source"]["status"] == "SUPERSEDED_BY_EXACT_TARGET_D1_RESEARCH_CANDIDATE"
    assert hk["superseded_source"]["displayed_as_valid_observation"] is False
    assert all(
        row["code"].startswith("HK.000")
        for row in result["markets"]["HK"]["rows"]
    )
    assert all(result[field] is False for field in ("production_allowed", "buy_gate_updated", "orders_sent"))
    assert result["market_readback_bindings"]["markets"]["HK_CONNECT"]["target_pool_sha256"] == pool_sha


@pytest.mark.parametrize(
    "static_binding",
    _api_module_for_bindings._MONTH_HK_AFTERFACT_R8_BINDINGS,
    ids=lambda item: f"r8-real-{item['date']}-{item['stage_id']}",
)
def test_r8_real_candidate_artifact_has_exact_api_readback(
    tmp_path: Path,
    static_binding: dict[str, Any],
) -> None:
    from apps.api.v35_api import app as app_module
    from apps.api.v35_api.app import create_app

    batch = json.loads(_R8_CANDIDATE_BATCH_RECEIPT.read_text(encoding="utf-8"))
    candidate = next(
        item
        for item in batch["candidates"]
        if item.get("trade_date") == static_binding["date"]
        and item.get("stage_id") == static_binding["stage_id"]
        and item.get("backfill_run_id") == static_binding["backfill_run_id"]
    )
    assert batch["status"] == "PASS_15_TARGET_BOUND_CANDIDATES"
    assert candidate["candidate_verification"] == "PASS"

    source_root = (
        Path(candidate["candidate_root"])
        / "runtime"
        / "selection"
        / "backfill"
        / static_binding["backfill_run_id"]
    )
    source_store = SelectionStore(source_root)
    envelope = source_store.read_verified(
        static_binding["date"], static_binding["stage_id"], "HK_CONNECT"
    )
    source_entry = source_store._latest()["entries"][
        source_store._key(static_binding["date"], static_binding["stage_id"], "HK_CONNECT")
    ]
    expected_evidence = set(static_binding["required_evidence"])
    actual_evidence = set(envelope.get("source_evidence") or ())
    assert expected_evidence <= actual_evidence
    mode_marker = (
        "stage_center_observation_mode=STAGE_CENTER_AFTERFACT_OBSERVATION_R1:"
        + static_binding["observation_mode_sha256"]
    )
    assert mode_marker in actual_evidence
    if static_binding["date"] == "20261005":
        assert (
            "hk_afterfact_contract=STAGE_CENTER_AFTERFACT_OBSERVATION_R1:"
            + static_binding["observation_mode_sha256"]
        ) in actual_evidence
    assert source_entry["run_id"] == static_binding["selection_run_id"]
    assert source_entry["artifact_sha256"] == static_binding["selection_artifact_sha256"]
    assert source_entry["manifest_sha256"] == static_binding["selection_manifest_sha256"]
    assert source_entry["receipt_sha256"] == static_binding["selection_receipt_sha256"]
    assert envelope["raw_artifact_sha256"] == static_binding["raw_artifact_sha256"]
    assert envelope["source_rows"] == static_binding["source_rows"] == 100
    assert len(envelope["rows"]) == static_binding["selected_rows"] == 10

    source_runner_receipt = (
        Path(candidate["candidate_root"])
        / "runtime"
        / "receipts"
        / "backfill"
        / static_binding["backfill_run_id"]
        / static_binding["date"]
        / static_binding["stage_id"]
        / "receipt.json"
    )
    assert hashlib.sha256(source_runner_receipt.read_bytes()).hexdigest() == static_binding[
        "runner_receipt_sha256"
    ]

    # Build a read-only test fixture from the actual immutable candidate tree.
    # No shared-state paths are touched.
    selection_root = tmp_path / "stage" / "selection"
    target_root = selection_root / "backfill" / static_binding["backfill_run_id"]
    shutil.copytree(source_root, target_root)
    receipt_target = (
        selection_root.parent
        / "receipts"
        / "backfill"
        / static_binding["backfill_run_id"]
        / static_binding["date"]
        / static_binding["stage_id"]
        / "receipt.json"
    )
    receipt_target.parent.mkdir(parents=True)
    shutil.copy2(source_runner_receipt, receipt_target)

    client = TestClient(
        create_app(
            data_root=_write_catalog(tmp_path, static_binding["date"]),
            stage_center_selection_root=selection_root,
            current_date=static_binding["date"],
        )
    )
    response = client.get(
        "/api/v3/workbench/stage",
        params={
            "date": static_binding["date"],
            "stage": static_binding["stage_id"],
            "market": "HK_CONNECT",
            "backfill_run_id": static_binding["backfill_run_id"],
            "limit": 50,
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    market = result["selection_markets"]["HK_CONNECT"]
    hk = result["markets"]["HK"]
    assert result["mode"] == "BACKFILL"
    assert result["RESEARCH_ONLY"] is True
    assert result["write_performed"] is False
    assert market["backfill_run_id"] == static_binding["backfill_run_id"]
    assert market["run_id"] == static_binding["selection_run_id"]
    assert market["runner_receipt_verified"] is True
    assert hk["display_mode"] == "OBSERVATION_UNVERIFIED"
    assert market["requested_rows"] == 100
    assert market["source_rows"] == 100
    assert len(hk["rows"]) == 10
    assert all(row["action_level"] == "NO_BUY" for row in hk["rows"])
    assert all(row["formal_eligible"] is False for row in hk["rows"])
    assert all(result[key] is False for key in ("production_allowed", "buy_gate_updated", "orders_sent"))


def test_revoked_20261005_r5_stage_identity_is_not_api_approved(tmp_path: Path) -> None:
    from apps.api.v35_api import app as app_module
    from apps.api.v35_api.app import create_app

    key = ("20261005", "STAGE_1545_1555", "HK_CONNECT", "dd0b08a26ea14cb6ba7423d8b75e09e5")
    assert key in app_module._REVOKED_HK_STAGE_BACKFILL_KEYS
    assert key not in app_module._APPROVED_EXACT_STAGE_BACKFILLS
    client = TestClient(
        create_app(
            data_root=_write_catalog(tmp_path, "20261005"),
            stage_center_selection_root=tmp_path / "stage" / "selection",
            current_date="20261005",
        )
    )
    response = client.get(
        "/api/v3/workbench/stage",
        params={
            "date": "20261005",
            "stage": "STAGE_1545_1555",
            "market": "HK_CONNECT",
            "backfill_run_id": key[-1],
        },
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "backfill selection identity is unavailable"


@pytest.mark.parametrize(
    ("artifact_sha256", "expected_quarantine"),
    [
        ("abea293be53b9114f2835ed94d6e52bdc33a54debe51891f102edcb05102357d", True),
        ("b" * 64, False),
    ],
)
def test_ordinary_20261005_auction_api_quarantines_only_pinned_wrong_pool_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact_sha256: str,
    expected_quarantine: bool,
) -> None:
    from apps.api.v35_api import app as app_module
    from apps.api.v35_api.app import create_app

    run_id = "run-6a45f94febaf762962082e81"
    manifest_sha256 = "25398bdf783d2916aa8aa64c0581071d99d8c7a85ebbdb8b6fbc3b4dbed08177"
    receipt_sha256 = "8bed1cd1e889cea9fa26c107c159018c2b1614aa0d54029ef1c483c8da0e40dc"
    source_evidence = [
        "candidate_current_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901",
        "hk_d1_json_sha256=f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901",
        "hk_d1_source_trade_date=20260930",
        "hk_observation_trade_date=20261005",
    ]
    rows = [
        {
            "code": f"HK.{index:05d}",
            "rank": index,
            "name": f"Auction source {index}",
            "action_level": "NO_BUY",
            "trade_status": "WATCH_ONLY",
            "status": "WATCH_ONLY",
            "source_mode": "HK_CONNECT_AUCTION_SECOND_FILTER_STAGE_0925",
            "formal_eligible": False,
        }
        for index in range(1, 11)
    ]
    market = {
        "market": "HK_CONNECT",
        "status": "PARTIAL_WITH_ROWS",
        "selection_status": "PARTIAL_WITH_ROWS",
        "artifact_id": f"selection-{run_id.removeprefix('run-')}",
        "run_id": run_id,
        "raw_artifact_sha256": "86fbd40b1a4d209ff00b3456b3d47c28f34c0b01a38b65aa76ce15bba2ca7e44",
        "source_status": "READY",
        "requested_rows": 100,
        "source_rows": 16,
        "selected_rows": 10,
        "rows": rows,
        "source_evidence": source_evidence,
        "cannot_confirm": [],
    }
    key = "20261005/STAGE_0925/HK_CONNECT"
    entry = {
        "trade_date": "20261005",
        "stage_id": "STAGE_0925",
        "market": "HK_CONNECT",
        "run_id": run_id,
        "artifact_sha256": artifact_sha256,
        "manifest_sha256": manifest_sha256,
        "receipt_sha256": receipt_sha256,
        "artifact_relative": "selection_runs/20261005/HK_CONNECT_SELECTION_STAGE_0925/run-6a45f94febaf762962082e81/artifact.csv",
    }

    class _Store:
        def _key(self, _date: str, _stage: str, _market: str) -> str:
            return key

        def _latest(self) -> dict[str, Any]:
            return {"entries": {key: entry}}

    class _Consumer:
        def __init__(self, _root: Path, **_kwargs: Any):
            self.store = _Store()

        def get(self, trade_date: str, stage_id: str, **_kwargs: Any) -> dict[str, Any]:
            return {
                "schema_version": "stage_center.selection_consumer.v1",
                "response_source": "SHARED_STAGE_CENTER",
                "trade_date": trade_date,
                "stage_id": stage_id,
                "status": "PARTIAL_WITH_ROWS",
                "markets": {"HK_CONNECT": market},
                "execution_evidence": {},
                "cannot_confirm": [],
                "write_performed": False,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }

    monkeypatch.setattr(app_module, "StageSelectionConsumer", _Consumer)
    client = TestClient(
        create_app(
            data_root=_write_catalog(tmp_path, "20261005"),
            stage_center_selection_root=tmp_path / "stage" / "selection",
            current_date="20261005",
        )
    )
    response = client.get(
        "/api/v3/workbench/stage",
        params={"date": "20261005", "stage": "STAGE_0925", "limit": 50},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    hk = result["markets"]["HK"]
    if expected_quarantine:
        assert hk["display_mode"] == "CANNOT_CONFIRM"
        assert hk["rows"] == []
        assert hk["selected_rows"] is None
        assert "HK:HK_D1_TARGET_POOL_MISMATCH" in result["cannot_confirm"]
        assert result["selection_markets"]["HK_CONNECT"]["requested_rows"] == 100
        assert result["selection_markets"]["HK_CONNECT"]["source_rows"] == 16
        quarantine = result["selection_markets"]["HK_CONNECT"]["quarantined_source"]
        assert quarantine["artifact_sha256"] == artifact_sha256
        assert quarantine["manifest_sha256"] == manifest_sha256
        assert quarantine["receipt_sha256"] == receipt_sha256
        assert quarantine["source_selected_rows"] == 10
        assert quarantine["rows_retained_in_verified_source_artifact"] is True
        assert quarantine["source_pool_sha256"].startswith("f45233")
        assert quarantine["target_pool_sha256"].startswith("8799c7")
    else:
        assert hk["display_mode"] == "OBSERVATION_UNVERIFIED"
        assert len(hk["rows"]) == 10
        assert "quarantined_source" not in result["selection_markets"]["HK_CONNECT"]


def _run_r8_candidates_through_r4_release_tree(
    tmp_path: Path,
    candidate_limit: int,
) -> None:
    release_id = "manager-hk-month-backfill-r8-20261007-api-r4"
    release_app_root = Path(
        "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/"
        f"{release_id}/app"
    )
    candidate_app = release_app_root / "apps/api/v35_api/app.py"
    manifest_path = release_app_root.parent / "release-manifest.json"
    assert candidate_app.is_file()
    assert manifest_path.is_file()
    app_sha256 = hashlib.sha256(candidate_app.read_bytes()).hexdigest()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["candidate"]["release_id"] == release_id
    assert manifest["candidate"]["app_root"] == str(release_app_root)
    app_inventory = next(
        item
        for item in manifest["application_inventory"]["entries"]
        if item.get("path") == "apps/api/v35_api/app.py"
    )
    assert app_inventory["sha256"] == app_sha256
    expected_app_sha256 = "109e850d9c3df9e1dfee7b359a64e1dc01f0c2ca1d51cba82f8778a496e4c464"
    assert app_sha256 == expected_app_sha256
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    inline = r'''
import hashlib, importlib.util, json, os, shutil, sys, tempfile
from pathlib import Path

release_root = Path(os.environ["RELEASE_APP_ROOT"]).resolve()
candidate_app = release_root / "apps/api/v35_api/app.py"
sys.path.insert(0, str(release_root))
from stage_center.consumer import StageSelectionConsumer
from stage_center.selection import SelectionStore
from infrastructure.data_store import NativeDataStore
from fastapi.testclient import TestClient
from infrastructure.scheduling.dispatcher import validate_release_identity

consumer_path = Path(sys.modules[StageSelectionConsumer.__module__].__file__).resolve()
assert consumer_path == release_root / "stage_center/consumer.py", consumer_path
assert hashlib.sha256(consumer_path.read_bytes()).hexdigest() == (
    "61f8a3541aa7a2e698cc4374385e3d20d41b40ffd5a3cd7d87c9494cb8726cf4"
)
assert "execution_receipt_root" in __import__("inspect").signature(
    StageSelectionConsumer
).parameters
runtime_identity = validate_release_identity()
assert runtime_identity["release_id"] == os.environ["V35_RELEASE_ID"]
assert runtime_identity["release_manifest_sha256"] == os.environ["V35_RELEASE_MANIFEST_SHA256"]

spec = importlib.util.spec_from_file_location("r4_release_tree_candidate_api", candidate_app)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
assert Path(module.__file__).resolve() == candidate_app.resolve()
assert hashlib.sha256(candidate_app.read_bytes()).hexdigest() == os.environ["EXPECTED_APP_SHA256"]
assert len(module._MONTH_HK_AFTERFACT_R8_BINDINGS) == 15
assert module.StageSelectionConsumer is StageSelectionConsumer

batch_path = Path(os.environ["R8_BATCH_RECEIPT"])
batch = json.loads(batch_path.read_text(encoding="utf-8"))
assert batch["status"] == "PASS_15_TARGET_BOUND_CANDIDATES"
assert len(batch["candidates"]) == 15
candidate_count = int(os.environ["CANDIDATE_LIMIT"])
assert candidate_count in {1, 15}
selected_candidates = batch["candidates"][:candidate_count]
bindings = {
    (item["date"], item["stage_id"], item["backfill_run_id"]): item
    for item in module._MONTH_HK_AFTERFACT_R8_BINDINGS
}

with tempfile.TemporaryDirectory(dir=os.environ["TEST_TMPDIR"]) as temp:
    root = Path(temp)
    data = NativeDataStore(root / "data")
    data.import_catalog({
        "schema_version": "v3_trade_calendar.v1",
        "system_date": "20261007",
        "stage_dates": [],
        "future_target_dates": [],
        "materialized_rows": {},
    })
    selection_root = root / "stage" / "selection"
    ordinary_store = SelectionStore(selection_root)

    for candidate in selected_candidates:
        date = candidate["trade_date"]
        stage = candidate["stage_id"]
        run_id = candidate["backfill_run_id"]
        key = (date, stage, run_id)
        binding = bindings[key]
        assert candidate["candidate_verification"] == "PASS"
        source_root = (
            Path(candidate["candidate_root"])
            / "runtime/selection/backfill"
            / run_id
        )
        source_store = SelectionStore(source_root)
        envelope = source_store.read_verified(date, stage, "HK_CONNECT")
        source_entry = source_store._latest()["entries"][
            source_store._key(date, stage, "HK_CONNECT")
        ]
        assert source_entry["run_id"] == binding["selection_run_id"]
        assert source_entry["manifest_sha256"] == binding["selection_manifest_sha256"]
        assert source_entry["receipt_sha256"] == binding["selection_receipt_sha256"]
        assert source_entry["artifact_sha256"] == binding["selection_artifact_sha256"]
        assert envelope["raw_artifact_sha256"] == binding["raw_artifact_sha256"]

        target_root = selection_root / "backfill" / run_id
        target_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_root, target_root)
        source_runner = (
            Path(candidate["candidate_root"])
            / "runtime/receipts/backfill"
            / run_id / date / stage / "receipt.json"
        )
        assert hashlib.sha256(source_runner.read_bytes()).hexdigest() == binding[
            "runner_receipt_sha256"
        ]
        target_runner = (
            selection_root.parent / "receipts/backfill"
            / run_id / date / stage / "receipt.json"
        )
        target_runner.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_runner, target_runner)

        stale_rows = [
            {
                "code": f"HK.{99000 + i:05d}",
                "rank": i,
                "name": f"Superseded {i}",
                "action_level": "NO_BUY",
                "trade_status": "WATCH_ONLY",
                "status": "WATCH_ONLY",
                "source_mode": "HK_CONNECT_FOUR_LANE",
                "formal_eligible": False,
            }
            for i in range(1, 11)
        ]
        ordinary_store.publish(
            {
                "schema_version": "stage_center.selection.v2",
                "trade_date": date,
                "stage_id": stage,
                "market": "HK_CONNECT",
                "algorithm_id": binding["algorithm_id"],
                "algorithm_sha256": binding["algorithm_sha256"],
                "raw_artifact_sha256": "a" * 64,
                "source_status": "PARTIAL_WITH_ROWS",
                "selection_status": "PARTIAL_WITH_ROWS",
                "requested_rows": 100,
                "source_rows": 100,
                "selected_rows": 10,
                "coverage_ratio": 0.1,
                "missing_symbols": [],
                "rows": stale_rows,
                "source_evidence": ["canonical_nonempty_source=true"],
                "cannot_confirm": ["FORMAL", "PIT", "NATURAL"],
                "formal_eligible": False,
                "observation_status": "OBSERVATION_UNVERIFIED",
                "formal_stage_eligibility": "CANNOT_CONFIRM",
                "natural_time_capture": "CANNOT_CONFIRM",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            },
            market="HK_CONNECT",
        )

    client = TestClient(module.create_app(
        data_root=data.root,
        stage_center_selection_root=selection_root,
        current_date="20261007",
    ))
    for candidate in selected_candidates:
        date = candidate["trade_date"]
        stage = candidate["stage_id"]
        run_id = candidate["backfill_run_id"]
        exact = client.get("/api/v3/workbench/stage", params={
            "date": date, "stage": stage, "market": "HK_CONNECT",
            "backfill_run_id": run_id, "limit": 50,
        })
        assert exact.status_code == 200, (date, stage, exact.text)
        exact_result = exact.json()
        exact_market = exact_result["selection_markets"]["HK_CONNECT"]
        assert exact_market["backfill_run_id"] == run_id
        assert exact_market["runner_receipt_verified"] is True
        assert len(exact_market["rows"]) == 10
        assert all(exact_result[field] is False for field in (
            "production_allowed", "buy_gate_updated", "orders_sent"
        ))

        ordinary = client.get("/api/v3/workbench/stage", params={
            "date": date, "stage": stage, "limit": 50,
        })
        assert ordinary.status_code == 200, (date, stage, ordinary.text)
        ordinary_result = ordinary.json()
        ordinary_market = ordinary_result["selection_markets"]["HK_CONNECT"]
        assert ordinary_market["backfill_run_id"] == run_id
        assert ordinary_market["run_id"] == exact_market["run_id"]
        assert ordinary_market["superseded_source"][
            "status"
        ] == "SUPERSEDED_BY_EXACT_TARGET_D1_RESEARCH_CANDIDATE"
        assert len(ordinary_result["markets"]["HK"]["rows"]) == 10
        assert all(row["action_level"] == "NO_BUY" for row in ordinary_result["markets"]["HK"]["rows"])
        assert all(ordinary_result[field] is False for field in (
            "production_allowed", "buy_gate_updated", "orders_sent"
        ))

print(f"{candidate_count} exact and {candidate_count} ordinary API reads PASS with R4 release app and daily-r2 consumer")
'''
    env = dict(os.environ)
    env["RELEASE_APP_ROOT"] = str(release_app_root)
    env["R8_BATCH_RECEIPT"] = str(_R8_CANDIDATE_BATCH_RECEIPT)
    env["TEST_TMPDIR"] = str(tmp_path)
    env["CANDIDATE_LIMIT"] = str(candidate_limit)
    env["EXPECTED_APP_SHA256"] = expected_app_sha256
    env["V35_APP_ROOT"] = str(release_app_root)
    env["V35_RELEASE_ID"] = release_id
    env["V35_RELEASE_MANIFEST_PATH"] = str(manifest_path)
    env["V35_RELEASE_MANIFEST_SHA256"] = manifest_sha256
    env["PYTHONPATH"] = f"{release_app_root / 'upstreams'}:{release_app_root}"
    result = subprocess.run(
        [sys.executable, "-B", "-c", inline],
        env=env,
        cwd=release_app_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"{candidate_limit} exact and {candidate_limit} ordinary API reads PASS with R4 release app and daily-r2 consumer" in result.stdout


def test_r8_release_tree_single_candidate_canary(tmp_path: Path) -> None:
    _run_r8_candidates_through_r4_release_tree(tmp_path, candidate_limit=1)


def test_r8_real_candidates_have_15_exact_and_15_ordinary_r4_release_readbacks(
    tmp_path: Path,
) -> None:
    _run_r8_candidates_through_r4_release_tree(tmp_path, candidate_limit=15)


_R9_READBACK_SCRIPT = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_MONTH_BACKFILL_20261007/evidence/"
    "month_hk_backfill_api_r8/r9_p2fix2/run_r9_api_readback_p2fix2.py"
)
_R9_INACTIVE_RELEASE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/"
    "manager-hk-month-backfill-r9-p2fix2-20261007-api-candidate"
)
_R4_BASELINE_RELEASE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/"
    "manager-hk-month-backfill-r8-20261007-api-r4"
)


def _run_r9_inactive_release_readback(
    tmp_path: Path, *, mode: str, limit: int
) -> dict[str, Any]:
    release_root = (
        _R9_INACTIVE_RELEASE_ROOT
        if mode in {"candidate", "preserve"}
        else _R4_BASELINE_RELEASE_ROOT
    )
    release_app_root = release_root / "app"
    manifest_path = release_root / "release-manifest.json"
    app_path = release_app_root / "apps/api/v35_api/app.py"
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    app_sha256 = hashlib.sha256(app_path.read_bytes()).hexdigest()
    env = dict(os.environ)
    env.update(
        {
            "V35_APP_ROOT": str(release_app_root),
            "V35_RELEASE_ID": release_root.name,
            "V35_RELEASE_MANIFEST_PATH": str(manifest_path),
            "V35_RELEASE_MANIFEST_SHA256": manifest_sha256,
            "PYTHONPATH": f"{release_app_root / 'upstreams'}:{release_app_root}",
            "EXPECTED_APP_SHA256": app_sha256,
            "R9_READBACK_TMP_ROOT": str(tmp_path),
            "R9_READBACK_MODE": mode,
            "R9_READBACK_LIMIT": str(limit),
            "R9_CANARY_DATE": "20260908",
            "R9_CANARY_STAGE": "STAGE_0930_0935",
        }
    )
    result = subprocess.run(
        [sys.executable, "-B", str(_R9_READBACK_SCRIPT)],
        env=env,
        cwd=release_app_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_r9_r4_baseline_reproduces_stale_nonempty_ordinary_read(
    tmp_path: Path,
) -> None:
    result = _run_r9_inactive_release_readback(
        tmp_path, mode="baseline", limit=1
    )
    assert result["result"] == "STALE_ORDINARY_REPRODUCED"
    assert result["exact_status"] == 404
    assert result["ordinary_status"] == 200
    assert result["ordinary_rows"] == 10
    assert result["ordinary_first_code"] == "HK.99001"


def test_r9_inactive_release_single_candidate_canary(
    tmp_path: Path,
) -> None:
    result = _run_r9_inactive_release_readback(
        tmp_path, mode="candidate", limit=1
    )
    assert result["result"] == "R9_EXACT_AND_ORDINARY_READBACK_PASS"
    assert result["checked_candidates"] == 1
    assert result["exact_reads"] == result["ordinary_reads"] == 1


def test_r9_inactive_release_preserves_existing_correct_target_pool_result(
    tmp_path: Path,
) -> None:
    result = _run_r9_inactive_release_readback(
        tmp_path, mode="preserve", limit=1
    )
    assert result["result"] == "R9_EXISTING_TARGET_POOL_PRESERVED"
    assert result["exact_reads"] == result["ordinary_reads"] == 1
    assert result["ordinary_first_code"] == "HK.97001"
    assert result["ordinary_pool_sha256"] == (
        "9b11fd7f192801552902e406045ee520a19d5a6b373c60a790f6925a30afa3bb"
    )
    assert result["candidate_run_id"] != result["ordinary_run_id"]


def test_r9_inactive_release_reads_all_87_exact_and_ordinary_candidates(
    tmp_path: Path,
) -> None:
    result = _run_r9_inactive_release_readback(
        tmp_path, mode="candidate", limit=87
    )
    assert result["result"] == "R9_EXACT_AND_ORDINARY_READBACK_PASS"
    assert result["checked_candidates"] == 87
    assert result["exact_reads"] == result["ordinary_reads"] == 87
    assert result["missing_rows_total"] == 80
    assert result["stale_ordinary_replacements"] == [
        ["20261002", "STAGE_1300_1315"],
        ["20261002", "STAGE_1445_1500"],
        ["20261002", "STAGE_1545_1555"],
    ]


_R9_PATH_CONTRACT_ROOT = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_MONTH_BACKFILL_20261007/evidence/"
    "month_hk_backfill_api_r8/r9_p3_path_contract"
)
_R9_PATH_CONTRACT_SCRIPT = (
    _R9_PATH_CONTRACT_ROOT / "run_r9_api_readback_p3_plan_targets.py"
)
_R9_P2FIX2_CAS_PLAN = (
    _R9_PATH_CONTRACT_ROOT.parent
    / "r9_p2fix2/r9_p2fix2_exact_copy_cas_plan_final.json"
)
_R9_P3_CAS_PLAN = _R9_PATH_CONTRACT_ROOT / "r9_p3_exact_copy_cas_plan.json"


def _run_r9_plan_target_readback(
    tmp_path: Path,
    *,
    plan_path: Path,
    mode: str,
    limit: int,
) -> dict[str, Any]:
    """Use the actual inactive release and materialize the exact CAS paths."""
    release_root = _R9_INACTIVE_RELEASE_ROOT
    release_app_root = release_root / "app"
    manifest_path = release_root / "release-manifest.json"
    app_path = release_app_root / "apps/api/v35_api/app.py"
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    app_sha256 = hashlib.sha256(app_path.read_bytes()).hexdigest()
    env = dict(os.environ)
    env.update(
        {
            "V35_APP_ROOT": str(release_app_root),
            "V35_RELEASE_ID": release_root.name,
            "V35_RELEASE_MANIFEST_PATH": str(manifest_path),
            "V35_RELEASE_MANIFEST_SHA256": manifest_sha256,
            "PYTHONPATH": f"{release_app_root / 'upstreams'}:{release_app_root}",
            "EXPECTED_APP_SHA256": app_sha256,
            "R9_READBACK_TMP_ROOT": str(tmp_path),
            "R9_READBACK_MODE": mode,
            "R9_READBACK_LIMIT": str(limit),
            "R9_CANARY_DATE": "20260908",
            "R9_CANARY_STAGE": "STAGE_0930_0935",
            "R9_CAS_PLAN_PATH": str(plan_path),
        }
    )
    result = subprocess.run(
        [sys.executable, "-B", str(_R9_PATH_CONTRACT_SCRIPT)],
        env=env,
        cwd=release_app_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_r9_p2fix2_cas_targets_reproduce_the_live_selection_identity_409(
    tmp_path: Path,
) -> None:
    result = _run_r9_plan_target_readback(
        tmp_path,
        plan_path=_R9_P2FIX2_CAS_PLAN,
        mode="path_failure",
        limit=1,
    )
    assert result["release_id"] == _R9_INACTIVE_RELEASE_ROOT.name
    assert result["result"] == "OLD_PLAN_TARGET_PATH_REPRODUCES_409"
    assert result["direct_exact_status"] == result["ordinary_status"] == 409
    assert result["direct_exact_detail"] == result["ordinary_detail"] == (
        "backfill selection identity is invalid"
    )
    assert result["materialized_file_count"] == 5
    mismatches = result["target_contract_failures"]
    assert {item["role"] for item in mismatches} == {
        "selection_manifest",
        "selection_receipt",
    }
    assert all(
        item["plan_target"] != item["SelectionStore_expected_target"]
        and "SELECTION_STAGE_STAGE_" in item["plan_target"]
        for item in mismatches
    )


def test_r9_p3_selectionstore_paths_pass_all_87_actual_release_readbacks(
    tmp_path: Path,
) -> None:
    result = _run_r9_plan_target_readback(
        tmp_path,
        plan_path=_R9_P3_CAS_PLAN,
        mode="candidate",
        limit=87,
    )
    assert result["release_id"] == _R9_INACTIVE_RELEASE_ROOT.name
    assert result["app_sha256"] == "4eceecb8bd078cdf3a2853ccb8339d5c9fbefb47825f70d1fc6f78a292a48af3"
    assert result["result"] == "R9_EXACT_AND_ORDINARY_READBACK_PASS"
    assert result["checked_candidates"] == 87
    assert result["exact_reads"] == result["ordinary_reads"] == 87
    assert result["source_rows_total"] == 8620
    assert result["missing_rows_total"] == 80
    assert result["materialized_file_count"] == 435
    assert result["target_contract_failure_count"] == 0
    assert result["stale_ordinary_replacements"] == [
        ["20261002", "STAGE_1300_1315"],
        ["20261002", "STAGE_1445_1500"],
        ["20261002", "STAGE_1545_1555"],
    ]


_R9_LEGACY_COMPAT_ROOT = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_MONTH_BACKFILL_20261007/evidence/"
    "month_hk_backfill_api_r8/r9_legacy_pool_compat_r1"
)
_R9_LEGACY_COMPAT_SCRIPT = (
    _R9_LEGACY_COMPAT_ROOT / "run_r9_legacy_lane_fixture_readback.py"
)
_R9_LEGACY_FIXTURE = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_MONTH_BACKFILL_20261007/evidence/"
    "month_hk_backfill_api_r8/r9_p3_path_contract/legacy_lane_fixtures/"
    "legacy_lane_fixtures.json"
)


def test_r9_real_legacy_lane_fixtures_replace_only_the_nine_exact_stale_lanes(
    tmp_path: Path,
) -> None:
    release_root = Path(
        "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/"
        "manager-hk-month-backfill-r9-legacy-pool-compat-20261007-api-candidate/app"
    )
    release_manifest = release_root.parent / "release-manifest.json"
    app_source = release_root / "apps/api/v35_api/app.py"
    assert release_root.is_dir()
    assert release_manifest.is_file()
    assert _R9_LEGACY_COMPAT_SCRIPT.is_file()
    assert _R9_LEGACY_FIXTURE.is_file()
    env = dict(os.environ)
    env.update(
        {
            "V35_APP_ROOT": str(release_root),
            "V35_RELEASE_ID": release_root.parent.name,
            "V35_RELEASE_MANIFEST_PATH": str(release_manifest),
            "V35_RELEASE_MANIFEST_SHA256": hashlib.sha256(
                release_manifest.read_bytes()
            ).hexdigest(),
            "PYTHONPATH": f"{release_root / 'upstreams'}:{release_root}",
            "RELEASE_APP_ROOT": str(release_root),
            "APP_SOURCE_PATH": str(app_source),
            "EXPECTED_APP_SHA256": hashlib.sha256(app_source.read_bytes()).hexdigest(),
            "LEGACY_FIXTURE_PATH": str(_R9_LEGACY_FIXTURE),
            "EXPECTED_FIXTURE_SHA256": hashlib.sha256(
                _R9_LEGACY_FIXTURE.read_bytes()
            ).hexdigest(),
            "TEST_TMPDIR": str(tmp_path),
            "CANDIDATE_BATCH_PATHS_JSON": json.dumps(
                [
                    "/Users/lexi/Desktop/学习/agents调试/V4_MONTH_BACKFILL_20261007/"
                    "evidence/hk_observation_candidates_20260907_r2/"
                    "candidate_batch_receipt_20260907_r2.json",
                    "/Users/lexi/Desktop/学习/agents调试/V4_MONTH_BACKFILL_20261007/"
                    "evidence/hk_observation_candidates_legacy_r2/"
                    "candidate_batch_receipt_legacy_r2.json",
                ]
            ),
            "PREFERENCE_POOL_ROOT": (
                "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data"
            ),
        }
    )
    result = subprocess.run(
        [sys.executable, "-B", str(_R9_LEGACY_COMPAT_SCRIPT)],
        env=env,
        cwd=release_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["status"] == "R9_REAL_LEGACY_LANE_COMPATIBILITY_PASS"
    assert receipt["ordinary_reads"] == 16
    assert len(receipt["replaced_exact_stale_pool_lanes"]) == 9
    assert len(receipt["preserved_exact_matching_pool_lanes"]) == 7
    assert receipt["conflicting_new_identity_preserved"] is True
    assert receipt["safety_flags_false"] is True
