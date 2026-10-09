"""Isolated exact-helper regressions, not current API or real-source acceptance.

The unchanged calendar Python fixture comes from Issue 30's hash-pinned
historical test closure. The unchanged JSON fixture comes from the supplied
Issue 28 calendar and matches the Stage calendar source SHA. Neither fixture
is a claim about the current Mac runtime, and neither belongs in production.
Run with pytest from the Issue 32 root. ISSUE32_API_SERVICE_SOURCE may select
an exact before/after service file for a separate regression run.
"""
from __future__ import annotations

import ast
import hashlib
import importlib
import os
from pathlib import Path
from typing import Any, Mapping

import pytest


FLAGS = ("production_allowed", "buy_gate_updated", "orders_sent")
CALENDAR_SHA = "9e2638b69e25495478cecb6ed551713178fcb989a63ebb4ecfd59689615f0acb"
CALENDAR_PY_SHA = "eca22a1e45271df45fc0a3b7cec28cec4e448d1af97b80371cc5c3c1953ec0f1"


@pytest.fixture
def calendar_authority(monkeypatch):
    support = Path(__file__).resolve().parent / "api_support"
    monkeypatch.syspath_prepend(str(support))
    module = importlib.import_module("contracts.trading_calendar")
    assert hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() == CALENDAR_PY_SHA
    fixture = support / "contracts/market_calendar_2026.json"
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == CALENDAR_SHA
    monkeypatch.setattr(module, "CALENDAR_PATH", fixture)
    return module


@pytest.fixture
def accepts(calendar_authority):
    default = (Path(__file__).resolve().parents[1]
               / "after/source/actual_api/apps/api/v35_api/preselection_service.py")
    source = Path(os.environ.get("ISSUE32_API_SERVICE_SOURCE", str(default)))
    tree = ast.parse(source.read_text(), filename=str(source))
    names = {"_is_sha256", "_is_exact_configured_hk_pool"}
    functions = [node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in functions} == names
    scope = {"Any": Any, "Mapping": Mapping, "TRADING_SAFETY_FLAGS": FLAGS}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), scope)
    return scope["_is_exact_configured_hk_pool"]


def _pool(*, target="20261009", price="20261008", eligibility="20261008"):
    flags = dict.fromkeys(FLAGS, False)
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "pool_id": "hkconnect_d1_top100", "market": "HK",
        "status": "STRICT_0_2_READY",
        "producer_id": "v3_shared_hk_0_2_consumer_v1",
        "source_role": "SHARED_VERIFIED_HK_0_2",
        "trade_date": target, "target_date": target, "signal_date": price,
        "price_signal_date": price, "eligibility_source_date": eligibility,
        "source_sha256": "1" * 64, "source_run_id": "synthetic-upstream-run",
        "source_manifest_sha256": "2" * 64, "source_receipt_sha256": "3" * 64,
        "stage_selection_eligible": True, **flags,
        "rows": [
            {"pool_id": "hkconnect_d1_top100", "market": "HK",
             "symbol": f"HK.{rank:05d}", "code": f"HK.{rank:05d}",
             "pool_rank": rank, "trade_date": target, "target_date": target,
             "signal_date": price, "recommendation_status": "WATCH_ONLY", **flags}
            for rank in range(1, 101)
        ],
    }


def _provenance(pool):
    return {
        "schema_version": "v4.hk_d1_split_date_provenance.v1",
        "price_signal_date": pool["signal_date"],
        "eligibility_source_date": pool["eligibility_source_date"],
        "eligibility_source_run_id": "synthetic-master-run",
        "eligibility_source_artifact_sha256": "4" * 64,
        "eligibility_source_captured_at": "2026-09-30T17:20:08+08:00",
        "d1_source_run_id": pool["source_run_id"],
        "d1_source_artifact_sha256": pool["source_sha256"],
        "d1_source_manifest_sha256": pool["source_manifest_sha256"],
        "d1_source_receipt_sha256": pool["source_receipt_sha256"],
    }


def test_oct9_same_date_pool_without_nested_provenance_is_accepted(accepts):
    assert accepts(_pool(), "20261009") is True


@pytest.mark.parametrize("field", ["price_signal_date", "eligibility_source_date"])
def test_same_date_requires_explicit_price_and_eligibility(accepts, field):
    pool = _pool()
    del pool[field]
    assert accepts(pool, "20261009") is False


@pytest.mark.parametrize("target,price,eligibility", [
    ("20261008", "20261007", "20260930"),
    ("20261008", "20261007", "20261007"),
    ("20261009", "20261007", "20261007"),
    ("20261010", "20261009", "20261009"),
    ("20261099", "20261008", "20261008"),
    ("20271009", "20271008", "20271008"),
])
def test_absent_provenance_cannot_hide_split_stale_or_unknown_calendar_dates(
    accepts, target, price, eligibility,
):
    assert accepts(_pool(target=target, price=price, eligibility=eligibility), target) is False


@pytest.mark.parametrize("failure", ["missing", "malformed"])
@pytest.mark.parametrize("with_provenance", [False, True])
def test_unavailable_calendar_rejects_same_date_exception(
    accepts, calendar_authority, monkeypatch, tmp_path, failure, with_provenance,
):
    fixture = tmp_path / "unavailable-calendar.json"
    if failure == "malformed":
        fixture.write_text('{"year": 2026}')
    monkeypatch.setattr(calendar_authority, "CALENDAR_PATH", fixture)
    pool = _pool()
    if with_provenance:
        pool["historical_provenance"] = _provenance(pool)
        pool["historical_provenance"]["eligibility_source_captured_at"] = "2026-10-08T17:20:08+08:00"
    assert accepts(pool, "20261009") is False


@pytest.mark.parametrize("value", [None, {}, {"schema_version": "wrong"}])
def test_present_malformed_provenance_is_never_treated_as_absent(accepts, value):
    pool = _pool()
    pool["historical_provenance"] = value
    assert accepts(pool, "20261009") is False


@pytest.mark.parametrize("target,price", [("20261008", "20261007"), ("20261007", "20261006")])
def test_split_date_still_requires_bound_upstream_provenance(accepts, target, price):
    pool = _pool(target=target, price=price, eligibility="20260930")
    pool["historical_provenance"] = _provenance(pool)
    assert accepts(pool, target) is True
    pool["historical_provenance"]["d1_source_artifact_sha256"] = "0" * 64
    assert accepts(pool, target) is False


@pytest.mark.parametrize("target,price,captured_at", [
    ("20261009", "20260930", "2026-09-30T17:20:08+08:00"),
    ("20261009", "20261008", "2026-09-30T17:20:08+08:00"),
    ("20261009", "20261008", "not-a-timestamp"),
    ("20261009", "20261008", "2026-10-08T17:20:08"),
    ("20261010", "20261009", "2026-10-09T17:20:08+08:00"),
    ("20271009", "20271008", "2027-10-08T17:20:08+08:00"),
])
def test_present_provenance_cannot_bypass_dates_calendar_or_capture(
    accepts, target, price, captured_at,
):
    pool = _pool(target=target, price=price, eligibility=price)
    pool["historical_provenance"] = _provenance(pool)
    pool["historical_provenance"]["eligibility_source_captured_at"] = captured_at
    assert accepts(pool, target) is False


@pytest.mark.parametrize("captured_at", [
    "2026-10-08T17:20:08+08:00", "2026-10-08T09:20:08Z",
])
def test_oct9_valid_present_provenance_uses_shanghai_capture_date(accepts, captured_at):
    pool = _pool()
    pool["historical_provenance"] = _provenance(pool)
    pool["historical_provenance"]["eligibility_source_captured_at"] = captured_at
    assert accepts(pool, "20261009") is True


@pytest.mark.parametrize("field,value", [
    ("trade_date", "20261008"), ("target_date", "20261008"),
    ("signal_date", "20261007"), ("price_signal_date", "20261007"),
    ("eligibility_source_date", "20260930"), ("market", "A"),
    ("code", "HK.99999"), ("pool_rank", 0),
    ("production_allowed", True), ("buy_gate_updated", True), ("orders_sent", True),
])
def test_same_date_does_not_admit_bad_row_aliases_identity_or_safety(accepts, field, value):
    pool = _pool()
    pool["rows"][0][field] = value
    assert accepts(pool, "20261009") is False


@pytest.mark.parametrize("failure", ["empty", "duplicate", "status", "source_sha", "safety"])
def test_same_date_keeps_existing_pool_count_source_and_safety_guards(accepts, failure):
    pool = _pool()
    if failure == "empty":
        pool["rows"] = []
    elif failure == "duplicate":
        pool["rows"][1] = dict(pool["rows"][0])
    elif failure == "status":
        pool["status"] = "CANNOT_CONFIRM"
    elif failure == "source_sha":
        pool["source_sha256"] = ""
    else:
        pool["orders_sent"] = True
    assert accepts(pool, "20261009") is False
