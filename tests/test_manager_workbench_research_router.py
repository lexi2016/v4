"""B1 read-only exact-date contract checks for the existing manager workbench."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from apps.api.v35_api import manager_workbench_router as module
from apps.api.v35_api.manager_workbench_router import create_manager_workbench_router


FIXTURE = Path(__file__).parent / "fixtures" / "manager_workbench_b1_simulated.json"


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _app(root: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(create_manager_workbench_router(root))
    return app


async def _get(app: FastAPI, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


def _write(root: Path, payload: dict[str, object], date: str = "20260918") -> Path:
    path = root / "workbench_research" / date / "1530.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path


def _fingerprint_tree(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_b1_valid_simulated_payload_is_projected_read_only(tmp_path: Path) -> None:
    root = tmp_path / "manager-state"
    fixture = _fixture()
    _write(root, fixture)
    before = _fingerprint_tree(root)

    response = asyncio.run(_get(_app(root), "/api/v4/manager/workbench-research?date=20260918&market=HK_CONNECT&slot=1530"))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PARTIAL"
    assert body["RESEARCH_ONLY"] is True
    assert body["production_allowed"] is False
    assert body["buy_gate_updated"] is False
    assert body["orders_sent"] is False
    assert body["coverage"] == fixture["coverage"]
    assert body["candidates"][0]["symbol"] == "HK.01234"
    assert body["candidates"][0]["source_lanes"] == ["CLOSE_DISCOVERY", "CONTINUOUS_TRACKING"]
    assert [source["run_id"] for source in body["candidates"][0]["sources"]] == [
        "SIM-CLOSE-20260918",
        "SIM-WATCH-20260918",
    ]
    assert _fingerprint_tree(root) == before


def test_b1_route_requires_exact_date_market_and_slot(tmp_path: Path) -> None:
    app = _app(tmp_path)
    assert asyncio.run(_get(app, "/api/v4/manager/workbench-research")).status_code == 422
    assert asyncio.run(_get(app, "/api/v4/manager/workbench-research?date=20260230")).status_code == 422
    assert asyncio.run(_get(app, "/api/v4/manager/workbench-research?date=20260918&market=A_SHARE")).status_code == 422
    assert asyncio.run(_get(app, "/api/v4/manager/workbench-research?date=20260918&slot=1600")).status_code == 422


def test_b1_missing_artifact_distinguishes_pending_not_run_and_input_missing(tmp_path: Path, monkeypatch) -> None:
    app = _app(tmp_path)
    monkeypatch.setattr(module, "_now_hk", lambda: datetime.fromisoformat("2026-09-18T15:00:00+08:00"))
    pending = asyncio.run(_get(app, "/api/v4/manager/workbench-research?date=20260918"))
    assert pending.json()["status"] == "PENDING_SLOT"
    assert pending.json()["as_of"] is None

    monkeypatch.setattr(module, "_now_hk", lambda: datetime.fromisoformat("2026-09-18T15:31:00+08:00"))
    missing = asyncio.run(_get(app, "/api/v4/manager/workbench-research?date=20260918"))
    assert missing.json()["status"] == "NOT_RUN"
    from infrastructure.manager_close_attempt import write_attempt
    write_attempt(tmp_path, "20260918", "INPUT_MISSING", "EXACT_INPUT_MISSING",
                  datetime.fromisoformat("2026-09-18T15:30:00+08:00"))
    declared = asyncio.run(_get(app, "/api/v4/manager/workbench-research?date=20260918"))
    assert declared.json()["status"] == "INPUT_MISSING"
    assert missing.json()["status"] != "READY_EMPTY"


def test_b1_existing_artifact_still_waits_for_current_day_slot(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "manager-state"
    _write(root, _fixture())
    monkeypatch.setattr(module, "_now_hk", lambda: datetime.fromisoformat("2026-09-18T15:00:00+08:00"))
    body = asyncio.run(_get(_app(root), "/api/v4/manager/workbench-research?date=20260918")).json()
    assert body["status"] == "PENDING_SLOT"
    assert body["candidates"] == []
    assert body["priority_summary"] == {"focus": [], "theme_changes": [], "risk_upgrades": []}


def test_b1_rejects_future_pit_timestamps(tmp_path: Path) -> None:
    root = tmp_path / "manager-state"
    payload = _fixture()
    payload["candidates"][0]["available_at"] = "2026-09-18T15:30:01+08:00"
    _write(root, payload)
    body = asyncio.run(_get(_app(root), "/api/v4/manager/workbench-research?date=20260918")).json()
    assert body["status"] == "FAILED"
    assert body["candidates"] == []


@pytest.mark.parametrize(
    ("field", "nested_field", "value"),
    [
        ("turnover_amount", "as_of", "2026-09-18T16:00:00+08:00"),
        ("volume_comparison", "baseline_as_of", "2026-09-18T16:00:00+08:00"),
    ],
)
def test_b1_rejects_future_nested_evidence_timestamps(
    tmp_path: Path, field: str, nested_field: str, value: str
) -> None:
    root = tmp_path / "manager-state"
    payload = _fixture()
    payload["candidates"][0][field][nested_field] = value
    _write(root, payload)
    body = asyncio.run(_get(_app(root), "/api/v4/manager/workbench-research?date=20260918")).json()
    assert body["status"] == "FAILED"
    assert body["candidates"] == []


@pytest.mark.parametrize(
    ("field", "nested_field"),
    [("turnover_amount", "as_of"), ("volume_comparison", "baseline_as_of")],
)
def test_b1_rejects_undefined_nested_evidence_schema(
    tmp_path: Path, field: str, nested_field: str
) -> None:
    root = tmp_path / "manager-state"
    payload = _fixture()
    payload["candidates"][0][field].pop(nested_field)
    _write(root, payload)
    body = asyncio.run(_get(_app(root), "/api/v4/manager/workbench-research?date=20260918")).json()
    assert body["status"] == "FAILED"
    assert body["candidates"] == []


def test_b1_rejects_missing_nested_metric_value_and_ratio_keys(tmp_path: Path) -> None:
    root = tmp_path / "manager-state"
    for field, nested_field in (("turnover_amount", "value"), ("volume_comparison", "ratio")):
        payload = _fixture()
        payload["candidates"][0][field].pop(nested_field)
        _write(root, payload)
        body = asyncio.run(_get(_app(root), "/api/v4/manager/workbench-research?date=20260918")).json()
        assert body["status"] == "FAILED"
        assert body["candidates"] == []


def test_b1_accepts_explicit_null_nested_metric_value_and_ratio(tmp_path: Path) -> None:
    root = tmp_path / "manager-state"
    for field, nested_field in (("turnover_amount", "value"), ("volume_comparison", "ratio")):
        payload = _fixture()
        payload["candidates"][0][field][nested_field] = None
        _write(root, payload)
        body = asyncio.run(_get(_app(root), "/api/v4/manager/workbench-research?date=20260918")).json()
        assert body["status"] == "PARTIAL"
        assert body["candidates"][0][field][nested_field] is None


def test_b1_qualified_requires_explicit_all_true_predicates(tmp_path: Path) -> None:
    root = tmp_path / "manager-state"
    payload = _fixture()
    payload["candidates"][0]["qualified"] = True
    payload["candidates"][0]["predicates"] = [
        {
            "predicate_id": "B1_REQUIRED_FIXTURE",
            "value": True,
            "reason": "SIMULATED",
            "input_refs": ["simulated/fixture"],
            "rule_version": "manager-workbench-b1-simulated-v1",
        }
    ]
    _write(root, payload)
    assert asyncio.run(_get(_app(root), "/api/v4/manager/workbench-research?date=20260918")).json()["status"] == "PARTIAL"

    for predicate_value in ("unknown", False):
        invalid = deepcopy(payload)
        invalid["candidates"][0]["predicates"][0]["value"] = predicate_value
        _write(root, invalid)
        body = asyncio.run(_get(_app(root), "/api/v4/manager/workbench-research?date=20260918")).json()
        assert body["status"] == "FAILED"

    no_definition = deepcopy(payload)
    no_definition["candidates"][0]["predicates"] = []
    _write(root, no_definition)
    assert asyncio.run(_get(_app(root), "/api/v4/manager/workbench-research?date=20260918")).json()["status"] == "FAILED"


@pytest.mark.parametrize("status", ["PENDING_SLOT", "INPUT_MISSING", "FAILED", "NOT_APPLICABLE"])
def test_b1_non_data_statuses_cannot_project_candidates_or_summary(tmp_path: Path, status: str) -> None:
    root = tmp_path / "manager-state"
    payload = _fixture()
    payload["status"] = status
    _write(root, payload)
    body = asyncio.run(_get(_app(root), "/api/v4/manager/workbench-research?date=20260918")).json()
    assert body["status"] == "FAILED"
    assert body["candidates"] == []

    payload = _fixture()
    payload["status"] = status
    payload["candidates"] = []
    _write(root, payload)
    body = asyncio.run(_get(_app(root), "/api/v4/manager/workbench-research?date=20260918")).json()
    assert body["status"] == "FAILED"
    assert body["priority_summary"] == {"focus": [], "theme_changes": [], "risk_upgrades": []}


def test_b1_contract_preserves_distinct_terminal_statuses(tmp_path: Path) -> None:
    root = tmp_path / "manager-state"
    app = _app(root)
    fixture = _fixture()
    cases = {
        "READY_EMPTY": [],
        "PARTIAL": fixture["candidates"],
        "STALE": fixture["candidates"],
        "NOT_APPLICABLE": [],
    }
    for status, candidates in cases.items():
        payload = deepcopy(fixture)
        payload["status"] = status
        payload["candidates"] = candidates
        if status == "READY_EMPTY":
            payload["priority_summary"] = {"focus": [], "theme_changes": [], "risk_upgrades": []}
        if status == "NOT_APPLICABLE":
            payload["as_of"] = None
            payload["generated_at"] = None
            payload["priority_summary"] = {"focus": [], "theme_changes": [], "risk_upgrades": []}
        _write(root, payload)
        body = asyncio.run(_get(app, "/api/v4/manager/workbench-research?date=20260918")).json()
        assert body["status"] == status


@pytest.mark.parametrize(
    ("field", "value", "remove"),
    [
        ("RESEARCH_ONLY", None, True),
        ("RESEARCH_ONLY", None, False),
        ("RESEARCH_ONLY", "true", False),
        ("RESEARCH_ONLY", False, False),
        ("production_allowed", None, True),
        ("production_allowed", None, False),
        ("production_allowed", "false", False),
        ("production_allowed", True, False),
        ("buy_gate_updated", "false", False),
        ("buy_gate_updated", True, False),
        ("orders_sent", "false", False),
        ("orders_sent", True, False),
    ],
)
def test_b1_invalid_safety_boolean_fails_closed(
    tmp_path: Path, field: str, value: object, remove: bool
) -> None:
    root = tmp_path / "manager-state"
    payload = _fixture()
    if remove:
        payload.pop(field, None)
    else:
        payload[field] = value
    _write(root, payload)
    body = asyncio.run(_get(_app(root), "/api/v4/manager/workbench-research?date=20260918")).json()
    assert body["status"] == "FAILED"
    assert body["candidates"] == []
    assert body["RESEARCH_ONLY"] is True
    assert body["production_allowed"] is False
    assert body["buy_gate_updated"] is False
    assert body["orders_sent"] is False
    assert body["cannot_confirm"] == ["WORKBENCH_RESEARCH_ARTIFACT_INVALID"]


def test_b1_invalid_payload_never_exposes_stack_token_or_local_path(tmp_path: Path) -> None:
    root = tmp_path / "manager-state"
    payload = _fixture()
    payload["cannot_confirm"] = [
        "Traceback (most recent call last): File /Users/example/private.py sk-FAKESECRET123456"
    ]
    _write(root, payload)
    response = asyncio.run(_get(_app(root), "/api/v4/manager/workbench-research?date=20260918"))
    text = response.text
    assert response.json()["status"] == "FAILED"
    assert "Traceback" not in text
    assert "sk-FAKESECRET" not in text
    assert "/Users/example" not in text


def test_b1_offset_aware_times_accept_z_and_plus8_but_reject_naive(tmp_path: Path) -> None:
    root = tmp_path / "manager-state"
    app = _app(root)
    payload = _fixture()
    payload["as_of"] = "2026-09-18T07:30:00Z"
    payload["generated_at"] = "2026-09-18T15:31:00+08:00"
    _write(root, payload)
    assert asyncio.run(_get(app, "/api/v4/manager/workbench-research?date=20260918")).json()["status"] == "PARTIAL"

    payload["as_of"] = "2026-09-18T15:30:00"
    _write(root, payload)
    assert asyncio.run(_get(app, "/api/v4/manager/workbench-research?date=20260918")).json()["status"] == "FAILED"


def test_b1_duplicate_symbol_or_cross_lane_source_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "manager-state"
    app = _app(root)
    payload = _fixture()
    payload["candidates"] = [payload["candidates"][0], deepcopy(payload["candidates"][0])]
    payload["candidates"][1]["candidate_id"] = "sim-hk-01234-second-source"
    _write(root, payload)
    assert asyncio.run(_get(app, "/api/v4/manager/workbench-research?date=20260918")).json()["status"] == "FAILED"

    payload = _fixture()
    payload["candidates"] = [payload["candidates"][0], deepcopy(payload["candidates"][0])]
    payload["candidates"][1]["symbol"] = "HK.05678"
    _write(root, payload)
    assert asyncio.run(_get(_app(root), "/api/v4/manager/workbench-research?date=20260918")).json()["status"] == "FAILED"

    payload = _fixture()
    payload["candidates"][0]["sources"][0]["lane"] = "STAGE"
    _write(root, payload)
    assert asyncio.run(_get(app, "/api/v4/manager/workbench-research?date=20260918")).json()["status"] == "FAILED"
