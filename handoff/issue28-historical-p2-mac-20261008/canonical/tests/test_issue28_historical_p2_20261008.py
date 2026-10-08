"""Focused regressions for the two accepted Issue 28 historical P2 repairs."""
from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path

import pytest

from infrastructure.hkconnect_close_store import CloseSnapshotStore
from infrastructure.preselection_pool_store import PreselectionPoolStore
from ops.build_close_review import build_close_review


REASON = "HK_MODEL_SOURCE_PIT_AVAILABILITY_CANNOT_CONFIRM"
_FIXTURE_SOURCE = Path(__file__).with_name("test_close_review_producer.py")
_FIXTURE_TREE = ast.parse(_FIXTURE_SOURCE.read_text(encoding="utf-8"))
_FIXTURE_NAMES = {"_historical_split_pool_payload", "_historical_asof_pool_payload"}
_FIXTURE_NODES = [
    node for node in _FIXTURE_TREE.body
    if isinstance(node, ast.FunctionDef) and node.name in _FIXTURE_NAMES
]
if {node.name for node in _FIXTURE_NODES} != _FIXTURE_NAMES:
    raise RuntimeError("canonical historical pool fixture definitions are missing")
_FIXTURES: dict[str, object] = {}
exec(
    compile(ast.fix_missing_locations(ast.Module(body=_FIXTURE_NODES, type_ignores=[])),
            str(_FIXTURE_SOURCE), "exec"),
    _FIXTURES,
)


def _historical_payload(schema: str) -> dict:
    function = _FIXTURES[f"_historical_{schema}_pool_payload"]
    return function()


def _change_source_date(payload: dict, field: str, value: str) -> None:
    provenance = payload["historical_provenance"]
    provenance[field] = value
    if field == "price_signal_date":
        payload["signal_date"] = value
        if "price_recovery" in provenance:
            provenance["price_recovery"]["source_date"] = value
    elif "eligibility_asof" in provenance:
        provenance["eligibility_asof"]["source_date"] = value


@pytest.mark.parametrize(
    "schema,field,future_date",
    [
        ("split", "eligibility_source_date", "20261008"),
        ("split", "price_signal_date", "20261008"),
        ("asof", "eligibility_source_date", "20261001"),
        ("asof", "price_signal_date", "20261001"),
    ],
)
def test_future_historical_source_date_is_rejected_before_materialization(
    tmp_path, schema, field, future_date
):
    payload = _historical_payload(schema)
    _change_source_date(payload, field, future_date)
    root = tmp_path / "data"

    with pytest.raises(ValueError, match="historical pool source date exceeds target date"):
        PreselectionPoolStore(root).materialize(payload)

    assert not list(root.rglob("*.json"))


@pytest.mark.parametrize("schema", ["split", "asof"])
def test_equal_source_dates_and_late_observation_contract_remain_valid(tmp_path, schema):
    payload = _historical_payload(schema)
    _change_source_date(payload, "eligibility_source_date", payload["trade_date"])
    _change_source_date(payload, "price_signal_date", payload["trade_date"])
    root = tmp_path / "data"

    store = PreselectionPoolStore(root)
    store.materialize(payload)
    assert store.read_pool(payload["trade_date"], "hkconnect_d1_top100") == payload
    if schema == "asof":
        provenance = payload["historical_provenance"]
        assert provenance["eligibility_asof"]["captured_at"] == "2026-10-02T14:02:56+08:00"
        for key in ("eligibility_asof", "price_recovery"):
            record = provenance[key]
            assert record["natural_verified"] is False
            assert record["production_allowed"] is False
            assert record["buy_gate_updated"] is False
            assert record["orders_sent"] is False


def _snapshot_payload(date: str) -> dict:
    return {
        "schema_version": "v3_5.hkconnect_close_snapshot.v1",
        "trade_date": date,
        "status": "READY",
        "source_mode": "SYNTHETIC_TEST_ONLY",
        "source_input_sha256": "a" * 64,
        "universe_count": 600,
        "same_date_row_count": 600,
        "coverage_ratio": 1.0,
        "rows": [
            {
                "trade_date": date,
                "code": f"HK.{index:05d}",
                "name": f"Fixture {index}",
                "close": 100 + index,
                "pre_close": 100,
                "amount": index,
            }
            for index in range(1, 601)
        ],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _model_pool_payload(date: str, *, omit: tuple[str, ...] = ()) -> dict:
    payload = {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": date,
        "pool_id": "hkconnect_d1_top100",
        "display_name": "Synthetic HK fixture",
        "market": "HK",
        "status": "STRICT_0_2_READY",
        "producer_id": "verified.fixture",
        "source_role": "SHARED_VERIFIED_HK_0_2",
        "source_path": "fixture/hk.json",
        "source_sha256": "b" * 64,
        "source_manifest_sha256": "c" * 64,
        "source_receipt_sha256": "d" * 64,
        "rows": [
            {
                "market": "HK",
                "symbol": f"HK.{index:05d}",
                "pool_id": "hkconnect_d1_top100",
                "pool_rank": index,
                "target_date": date,
            }
            for index in range(1, 101)
        ],
        "cannot_confirm": [],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    for field in omit:
        del payload[field]
    return payload


def _seed_close_inputs(root: Path, date: str, pool: dict) -> dict[str, bytes]:
    CloseSnapshotStore(root).import_snapshot(_snapshot_payload(date))
    PreselectionPoolStore(root).materialize(pool)
    prefixes = (
        "preselection_pools/",
        "receipts/preselection_pools/",
        "hkconnect_close_snapshots/",
        "receipts/hkconnect_close_snapshots/",
    )
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and str(path.relative_to(root)).startswith(prefixes)
    }


@pytest.mark.parametrize("missing_sha", ["source_manifest_sha256", "source_receipt_sha256"])
def test_missing_source_sha_adds_one_existing_pit_reason_and_preserves_inputs(tmp_path, missing_sha):
    date = "20260825"
    root = tmp_path / "data"
    pool = _model_pool_payload(date, omit=(missing_sha,))
    original_pool = deepcopy(pool)
    source_bytes = _seed_close_inputs(root, date, pool)

    result = build_close_review(root, date)
    review = result["review"]

    assert review["cannot_confirm"].count(REASON) == 1
    assert review["row_counts"]["model_0_2"] == 100
    assert all(review[flag] is False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
    assert PreselectionPoolStore(root).read_pool(date, "hkconnect_d1_top100") == original_pool
    assert {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and str(path.relative_to(root)).startswith((
            "preselection_pools/",
            "receipts/preselection_pools/",
            "hkconnect_close_snapshots/",
            "receipts/hkconnect_close_snapshots/",
        ))
    } == source_bytes


def test_complete_source_sha_pair_does_not_gain_pit_reason(tmp_path):
    date = "20260825"
    root = tmp_path / "data"
    _seed_close_inputs(root, date, _model_pool_payload(date))

    result = build_close_review(root, date)

    assert REASON not in result["review"]["cannot_confirm"]
    assert result["review"]["row_counts"]["model_0_2"] == 100
    assert all(result["review"][flag] is False for flag in (
        "production_allowed", "buy_gate_updated", "orders_sent",
    ))

