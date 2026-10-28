"""Narrow READY compatibility regression; optional readonly deployed-dependency overlay.

Set HK_READY_RUNTIME_ROOT when the isolated commit lacks the deployed refactor
helpers. HK_READY_FROZEN_SOURCE_ROOT enables the saved real-input canary.
All materialization is restricted to pytest's temporary directory.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest


DATE = "20261021"
POOL = "hkconnect_d1_top100"


@pytest.fixture
def api(monkeypatch):
    runtime = os.environ.get("HK_READY_RUNTIME_ROOT")
    if runtime:
        monkeypatch.syspath_prepend(runtime)
    import stage_center.runner as runner
    from infrastructure.preselection_pool_store import PreselectionPoolStore

    candidate = Path(__file__).resolve().parents[1] / "stage_center/_runner_parts/hk_input_validation.py"
    name = "stage_center._runner_parts.hk_input_validation"
    spec = importlib.util.spec_from_file_location(name, candidate)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return runner, PreselectionPoolStore


def payload(status="READY", count=100):
    flags = dict(production_allowed=False, buy_gate_updated=False, orders_sent=False)
    run = f"{DATE}-hk-connect-d1-top100-0-2-0123456789ab"
    return {
        "schema_version": "v3_5.preselection_pool.v1", "trade_date": DATE,
        "target_date": DATE, "signal_date": "20261020", "pool_id": POOL,
        "display_name": "synthetic HK status regression", "market": "HK",
        "status": status, "producer_id": "v3_shared_hk_0_2_consumer_v1",
        "source_role": "UPSTREAM_PRODUCER_ARTIFACT" if status == "PARTIAL_WITH_ROWS" else "SHARED_VERIFIED_HK_0_2",
        "source_run_id": run,
        "source_path": f"runs/{DATE}/HK_CONNECT_D1_TOP100_0_2/{run}/artifact.csv",
        "source_sha256": "a" * 64, "source_artifact_sha256": "a" * 64,
        "source_manifest_sha256": "b" * 64, "source_receipt_sha256": "c" * 64,
        "source_row_count": count, "stage_selection_eligible": True,
        "cannot_confirm": ["HK_0_2_SYNTHETIC_PARTIAL"] if status == "PARTIAL_WITH_ROWS" else [],
        "rows": [dict(symbol=f"HK.{i:05d}", code=f"HK.{i:05d}", market="HK",
                      signal_date="20261020", target_date=DATE, trade_date=DATE,
                      selected_strategy="prob_active", **flags) for i in range(1, count + 1)],
        **flags,
    }


def bind(api, root, p):
    runner, store = api
    store(root).materialize(p)
    return runner._build_hk_d1_binding(root, DATE, preselection_source_root=root)


@pytest.mark.parametrize("status,count", [("READY", 100), ("STRICT_0_2_READY", 100),
                                         ("PARTIAL_WITH_ROWS", 3)])
def test_supported_status_retains_exact_membership_and_true_status(api, tmp_path, status, count):
    b = bind(api, tmp_path, payload(status, count))
    assert set(b.codes) == {f"HK.{i:05d}" for i in range(1, count + 1)}
    assert f"hk_d1_status={status}" in b.evidence
    assert f"hk_d1_membership={'available_source_rows' if count < 100 else 'exact_date_top100'}" in b.evidence


@pytest.mark.parametrize("field,value", [
    ("status", "READY_WITH_ROWS"), ("producer_id", "other_producer"),
    ("source_role", "RAW_SOURCE"), ("market", "A"),
    ("stage_selection_eligible", False), ("stage_selection_eligible", None),
    ("target_date", "20261020"), ("signal_date", "20261019"),
    ("source_sha256", "invalid"), ("production_allowed", True),
    ("buy_gate_updated", True), ("orders_sent", True),
])
def test_ready_does_not_bypass_provenance_date_eligibility_or_safety(api, tmp_path, field, value):
    p = payload()
    if value is None:
        p.pop(field)
    else:
        p[field] = value
    with pytest.raises(ValueError):
        bind(api, tmp_path, p)


@pytest.mark.parametrize("kind", ["99_rows", "101_rows", "duplicate", "row_market",
                                 "row_date", "model", "symbol_mismatch", "partial_role"])
def test_ready_preserves_top100_row_and_model_constraints(api, tmp_path, kind):
    p = payload(count=99 if kind == "99_rows" else 101 if kind == "101_rows" else 100)
    row = p["rows"][0]
    if kind == "duplicate":
        p["rows"][1] = copy.deepcopy(row)
    elif kind == "row_market":
        row["market"] = "A"
    elif kind == "row_date":
        row["signal_date"] = "20261019"
    elif kind == "model":
        row["selected_strategy"] = "other"
    elif kind == "symbol_mismatch":
        row["symbol"] = "HK.99999"
    elif kind == "partial_role":
        p["source_role"] = "UPSTREAM_PRODUCER_ARTIFACT"
    with pytest.raises(ValueError):
        bind(api, tmp_path, p)


@pytest.mark.parametrize("kind", ["missing_target", "standalone", "tampered_artifact", "tampered_receipt", "tampered_manifest"])
def test_ready_requires_explicit_verified_exact_trio(api, tmp_path, kind):
    from infrastructure.preselection_pool_store import PreselectionPoolIntegrityError

    runner, store = api
    p = payload()
    if kind == "missing_target":
        p.pop("target_date")
    store(tmp_path).materialize(p)
    date = tmp_path / "preselection_pools" / DATE
    if kind.startswith("tampered_"):
        path = {"tampered_artifact": date / f"{POOL}.json",
                "tampered_receipt": date / "receipts" / f"{POOL}.json",
                "tampered_manifest": date / "manifest.json"}[kind]
        path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises((ValueError, RuntimeError, PreselectionPoolIntegrityError)):
        runner._build_hk_d1_binding(tmp_path, DATE,
            preselection_source_root=None if kind == "standalone" else tmp_path)


def test_saved_today_ready_source_binds_all_frozen100(api):
    root = os.environ.get("HK_READY_FROZEN_SOURCE_ROOT")
    baseline = os.environ.get("HK_READY_FROZEN_BASELINE")
    if not root or not baseline:
        pytest.skip("saved real-input canary requires explicit readonly evidence paths")
    root = Path(root)
    p = root / "preselection_pools" / DATE / f"{POOL}.json"
    frozen = json.loads(Path(baseline).read_text())
    expected = {f"HK.{c}" for c in frozen["HK"]["codes"]}
    source = frozen["pool_source_bindings"][POOL]
    assert hashlib.sha256(p.read_bytes()).hexdigest() == source["artifact_raw_sha256"]
    b = api[0]._build_hk_d1_binding(root, DATE, preselection_source_root=root)
    assert len(b.codes) == 100
    assert set(b.codes) == expected
    assert b.sha256 == source["artifact_raw_sha256"]
    assert "hk_d1_status=READY" in b.evidence
