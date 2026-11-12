"""Regression for verified empty V192 and independent scheduled publication.

The same assertions can target the manifest-bound inline runtime delta by
setting V4_PREPOOL_RUNTIME_ROOT and V4_PREPOOL_RUNTIME_DELTA before collection.
"""
from __future__ import annotations

import copy
import importlib.util
import inspect
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_RUNTIME_ROOT = os.environ.get("V4_PREPOOL_RUNTIME_ROOT")
if _RUNTIME_ROOT:
    sys.path.insert(0, _RUNTIME_ROOT)
    delta = json.loads(Path(os.environ["V4_PREPOOL_RUNTIME_DELTA"]).read_text())
    for relative, change in delta["files"].items():
        source = (Path(_RUNTIME_ROOT) / relative).read_text()
        import hashlib
        assert hashlib.sha256(source.encode()).hexdigest() == change["before_sha256"]
        for edit in change["edits"]:
            assert source.count(edit["before"]) == 1
            source = source.replace(edit["before"], edit["after"], 1)
        assert hashlib.sha256(source.encode()).hexdigest() == change["after_sha256"]
        name = relative.removesuffix(".py").replace("/", ".")
        spec = importlib.util.spec_from_file_location(name, Path(_RUNTIME_ROOT) / relative)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        exec(compile(source, str(spec.origin), "exec"), module.__dict__)

from domains import preselection_materializer as materializer
from domains.preselection import preselection
from infrastructure.data_store import NativeDataStore
from infrastructure.preselection_pool_store import PreselectionPoolStore, validate_pool_artifact
from ops import materialize_scheduled_preselection as scheduled

DATE = "20261113"
SIGNAL = "20261112"


def _shared_reader(count=0):
    rows = []
    for rank in range(1, count + 1):
        row = {field: "x" for field in materializer.SHARED_V192_ENTRY_FIELDS}
        row.update(ts_code=f"{rank:06d}.SZ", review_rank_v19=rank,
                   signal_date=SIGNAL, target_date=DATE,
                   rank_usage_boundary=materializer.SHARED_V192_RANK_BOUNDARY,
                   formal_recommendation_allowed="false",
                   formula_source=materializer.SHARED_V192_FORMULA_SOURCE,
                   gold_brick_context="none", premarket_pool_score=0.5)
        rows.append(row)
    return SimpleNamespace(rows=rows, run=SimpleNamespace(
        verification={"run_id": "verified-empty", "artifact_relative":
            f"runs/{DATE}/{materializer.SHARED_V192_ROLE}/verified-empty/artifact.csv",
            "artifact_sha256": "a" * 64, "manifest_sha256": "c" * 64,
            "receipt_sha256": "d" * 64, "row_count": count},
        receipt={"production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
    ))


def _empty():
    return materializer.build_shared_v192_premarket_pool(
        Path("unused"), trade_date=DATE, signal_date=SIGNAL,
        reader=lambda *a, **k: _shared_reader(),
    )


def _pool(pool_id="a_share_research_recommendation_pool", count=1, market="A"):
    return {
        "schema_version": "v3_5.preselection_pool.v1", "trade_date": DATE,
        "pool_id": pool_id, "display_name": pool_id, "market": market,
        "status": "READY", "producer_id": "regression_fixture",
        "source_role": "RAW_SOURCE", "source_path": "fixture/input.csv",
        "source_sha256": "b" * 64, "cannot_confirm": [],
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        "stage_selection_eligible": True,
        "rows": [{"symbol": f"HK.{rank:05d}" if market == "HK" else f"A.{rank:06d}",
                  "market": market, "pool_id": pool_id, "pool_rank": rank,
                  "recommendation_status": "WATCH_ONLY"} for rank in range(1, count+1)],
    }


def _assert_safety(value):
    assert all(value[key] is False for key in
               ("production_allowed", "buy_gate_updated", "orders_sent"))


def test_verified_v192_empty_is_legal_ineligible_and_keeps_siblings(tmp_path):
    empty = _empty()
    assert empty["status"] == "VALID_EMPTY"
    assert "V192_CANDIDATE_READY_EMPTY" in empty["cannot_confirm"]
    assert empty["source_row_count"] == 0 and empty["rows"] == []
    assert empty["source_sha256"] == "a" * 64
    assert empty["stage_selection_eligible"] is False
    assert validate_pool_artifact(empty) == DATE
    store = PreselectionPoolStore(tmp_path)
    research = _pool()
    results = scheduled.publish_scheduled_artifacts(store, [empty, research])
    assert len(results) == 2
    assert store.read_pool(DATE, empty["pool_id"]) == empty
    assert store.read_pool(DATE, research["pool_id"]) == research
    gate_args = {"market_scope": "CROSS_MARKET"} if "market_scope" in inspect.signature(scheduled._formal_pool_gate).parameters else {}
    assert scheduled._formal_pool_gate([empty, research], **gate_args)["required"][empty["pool_id"]]["ready"] is False
    _assert_safety(empty)
    _assert_safety(research)


@pytest.mark.parametrize("status", ["V192_CANDIDATE_READY_EMPTY", "READY_EMPTY", "READY"])
def test_unexpected_empty_status_remains_rejected(status):
    artifact = _empty()
    artifact["status"] = status
    with pytest.raises(ValueError, match="empty pool requires an explicit status"):
        validate_pool_artifact(artifact)


def test_invalid_first_pool_is_rejected_after_valid_siblings_materialize(tmp_path):
    invalid = _empty()
    invalid["status"] = "READY_EMPTY"
    research = _pool(count=241)
    hk = _pool("hkconnect_d1_top100", 2, "HK")
    store = PreselectionPoolStore(tmp_path)
    with pytest.raises(scheduled.ScheduledPoolPublicationError) as caught:
        scheduled.publish_scheduled_artifacts(store, [invalid, research, hk])
    results = caught.value.results
    assert len(results) == 3
    assert results[0]["status"] == "REJECTED"
    assert results[0]["reason_code"] == "POOL_CONTRACT_INVALID"
    assert results[0]["artifact_written"] is False
    assert "empty pool requires an explicit status" in results[0]["detail"]
    with pytest.raises(FileNotFoundError):
        store.read_pool(DATE, invalid["pool_id"])
    assert len(store.read_pool(DATE, research["pool_id"])["rows"]) == 241
    assert len(store.read_pool(DATE, hk["pool_id"])["rows"]) == 2
    body = preselection(NativeDataStore(tmp_path), DATE, limit=1)
    assert body["ok"] is True
    assert body["a_all_pool_row_count"] == 241
    assert len(body["a_all_pool_rows"]) == 1  # display page only
    full = preselection(NativeDataStore(tmp_path), DATE, limit=10000)
    assert len(full["a_all_pool_rows"]) == 241
    assert all(row["market"] == "A" for row in full["a_all_pool_rows"])
    assert body["market_totals"] == {"A": 241, "HK": 2}
    _assert_safety(body)


def test_immutable_conflict_preserves_old_pool_and_later_sibling(tmp_path):
    store = PreselectionPoolStore(tmp_path)
    original = _pool()
    store.materialize(original)
    conflicting = copy.deepcopy(original)
    conflicting["source_sha256"] = "c" * 64
    sibling = _pool("a_share_baimao_research_map")
    with pytest.raises(scheduled.ScheduledPoolPublicationError) as caught:
        scheduled.publish_scheduled_artifacts(store, [conflicting, sibling])
    assert caught.value.results[0]["reason_code"] == "IMMUTABLE_POOL_CONFLICT"
    assert store.read_pool(DATE, original["pool_id"]) == original
    assert store.read_pool(DATE, sibling["pool_id"]) == sibling


def test_nonempty_verified_v192_keeps_original_ready_contract():
    artifact = materializer.build_shared_v192_premarket_pool(
        Path("unused"), trade_date=DATE, signal_date=SIGNAL,
        reader=lambda *a, **k: _shared_reader(1),
    )
    assert artifact["status"] == "V192_CANDIDATE_READY"
    assert artifact["stage_selection_eligible"] is True
    assert artifact["source_row_count"] == 1
    assert "V192_CANDIDATE_READY_EMPTY" not in artifact["cannot_confirm"]
    assert validate_pool_artifact(artifact) == DATE
    _assert_safety(artifact)


def test_hk_missing_reason_stays_deferred_while_a_pool_is_written(tmp_path):
    missing = materializer.build_expected_missing_pool(
        DATE, pool_id="hkconnect_d1_top100", display_name="HK", market="HK",
        reason="HK_LOCAL_POOL_CONTRACT_UNAVAILABLE",
    )
    store = PreselectionPoolStore(tmp_path)
    research = _pool()
    results = scheduled.publish_scheduled_artifacts(store, [missing, research])
    assert results[0]["status"] == "DEFERRED"
    assert results[0]["cannot_confirm"] == ["HK_LOCAL_POOL_CONTRACT_UNAVAILABLE"]
    assert results[0]["artifact_written"] is False
    assert store.read_pool(DATE, research["pool_id"]) == research
    with pytest.raises(FileNotFoundError):
        store.read_pool(DATE, missing["pool_id"])


def test_cli_emits_failed_receipt_with_invalid_pool_and_keeps_valid_pool(tmp_path, monkeypatch, capsys):
    invalid = _empty()
    invalid["status"] = "READY_EMPTY"
    research = _pool()
    monkeypatch.setattr(scheduled, "build_scheduled_artifacts", lambda **kwargs: [invalid, research])
    # Runtime's existing asset completion is outside this publication regression.
    monkeypatch.setitem(sys.modules, "ops.complete_workbench_v192_assets", SimpleNamespace(
        after_preselection=lambda *args: {"status": "NOT_RUN_TEST"}))
    data = tmp_path / "data"
    result = scheduled.main([
        "--trade-date", DATE, "--signal-date", SIGNAL,
        "--input-root", str(tmp_path / "inputs"), "--data-root", str(data),
        "--shared-data-root", str(tmp_path / "shared"),
        "--shared-package-root", str(tmp_path / "package"),
    ])
    assert result == 1
    body = json.loads(capsys.readouterr().out)
    assert body["status"] in {"FAILED", "REJECTED"}
    assert body["artifacts"][0]["status"] == "REJECTED"
    assert body["artifacts"][0]["detail"] == "empty pool requires an explicit status"
    assert PreselectionPoolStore(data).read_pool(DATE, research["pool_id"]) == research
    _assert_safety(body)
