"""Offline HK owner adapter regression; all source rows/timestamps are synthetic.

The full frozen active-owner application is unavailable. This harness loads the
actual monolithic adapter and CLI, the frozen canonical shared source/store, and
the exact unchanged active Stage validator body. The unavailable split-module
namespace import is supplied by an explicitly test-only globals adapter. No
Stage tick, acquisition, scoring/model, API, scheduler process or Mac is run.
"""
from __future__ import annotations

import ast
import builtins
import copy
from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
from types import ModuleType
from typing import Any, Mapping

import pytest


ROOT = Path(os.environ["HK_ISSUE_ROOT"]).resolve()
OWNER_ROOT = Path(os.environ["HK_OWNER_ROOT"]).resolve()
SUPPORT_ROOT = Path(os.environ["HK_SUPPORT_ROOT"]).resolve()
BASELINE = Path(os.environ.get("HK_BASELINE_ROOT", str(ROOT / "baseline/source"))).resolve()
SAFETY_FLAGS = ("production_allowed", "buy_gate_updated", "orders_sent")
sys.path.insert(0, str(SUPPORT_ROOT))


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _read_global_for_test(scope, name):
    """Test harness only; this is not an invented production namespace file."""
    return scope[name] if name in scope else getattr(builtins, name)


def _load_body_module_for_test(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    tree.body = [
        node for node in tree.body
        if not (
            isinstance(node, ast.ImportFrom)
            and node.level == 1 and node.module == "_namespace"
        )
    ]
    scope = {"_v4_global": _read_global_for_test, "__name__": "hk_test_body"}
    exec(compile(tree, str(path), "exec"), scope)
    return scope


# The independent A fallback import is unavailable in this handoff and never
# executed here. A test fixture replaces it with an explicit synthetic lane.
baimao_import = ModuleType("infrastructure.baimao_preselection_pool_source")


def _unavailable_baimao(*args, **kwargs):
    raise AssertionError("Unrelated A acquisition must not execute in this test")


baimao_import.load_baimao_preselection_pool = _unavailable_baimao
sys.modules[baimao_import.__name__] = baimao_import
adapter = _load_module(
    "domains.preselection_materializer", OWNER_ROOT / "domains/preselection_materializer.py"
)
scheduled = _load_module(
    "hk_test_scheduled", OWNER_ROOT / "ops/materialize_scheduled_preselection.py"
)
from infrastructure.preselection_pool_store import PreselectionPoolStore
from stage_center.calendar import TradingDayState, resolve_market_states

SHARED_PACKAGE_ROOT = SUPPORT_ROOT / "upstreams/v3_shared_data"
shared = adapter._load_isolated_shared_module(SHARED_PACKAGE_ROOT, "hk_0_2")
security_master = adapter._load_isolated_shared_module(SHARED_PACKAGE_ROOT, "hk_security_master")
validator = _load_body_module_for_test(
    BASELINE / "active_stage_reference/stage_center/_runner_parts/hk_input_validation.py"
)["__validate_hk_d1_body"]
canonical_body = _load_body_module_for_test(
    BASELINE / "canonical/domains/_preselection_materializer_parts/hk_pool.py"
)["_build_shared_hk_0_2_pool_body"]


class RunnerError(ValueError):
    """Test exception matching the unchanged active runner's error base."""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate(root: Path, artifact: Mapping[str, Any]):
    store = PreselectionPoolStore(root)
    stored = store.materialize(artifact)
    # Use the real source resolver and stored artifact/manifest/receipt.
    path, digest = validator(
        globals(), root, str(artifact["trade_date"]), preselection_source_root=root
    )
    assert digest == _sha(path)
    assert stored["sha256"] == digest
    return store.read_pool_snapshot(str(artifact["trade_date"]), "hkconnect_d1_top100")


def _synthetic_source(root, *, signal="20261007", eligibility="20260930", target="20261008"):
    """Original shared publisher receives fictional dated fixture rows only."""
    capture = f"{eligibility[:4]}-{eligibility[4:6]}-{eligibility[6:]}T17:20:08.123456+08:00"
    codes = [f"HK.{rank:05d}" for rank in range(1, 101)]
    master = security_master.publish_hk_security_master(
        root,
        trade_date=eligibility,
        rows=[{"code": code, "name": f"SYNTHETIC company {rank}"} for rank, code in enumerate(codes, 1)],
        universe_codes_sha256=hashlib.sha256(json.dumps(codes).encode()).hexdigest(),
        captured_at=capture,
    )
    rows = [
        {
            "trade_date": target, "bar_time": "17:30", "target_date": target,
            "signal_date": signal, "rank": rank, "code": code, "code_norm": code,
            "name": f"SYNTHETIC company {rank}", "selected_strategy": "prob_active",
            "score_prob_active": 1.0 - rank / 1000.0, "d1_freshness_status": "PASS",
            "production_allowed": False, "research_only": True, "cannot_confirm": "",
        }
        for rank, code in enumerate(codes, 1)
    ]
    shared.publish_hk_0_2_rows(
        root, signal_date=signal, eligibility_source_date=eligibility,
        target_date=target, rows=rows,
        panel_sha256=hashlib.sha256(b"explicit synthetic panel identity; no market data").hexdigest(),
    )
    pool = shared.read_verified_hk_0_2_pool(
        root, target_date=target, expected_signal_date=signal,
        expected_eligibility_source_date=eligibility,
    )
    return pool, master, capture


def _build(root: Path, *, signal="20261007", eligibility="20260930", target="20261008", reader=None):
    return adapter.build_shared_hk_0_2_pool(
        root, trade_date=target, signal_date=signal,
        eligibility_source_date=eligibility,
        shared_package_root=SHARED_PACKAGE_ROOT, reader=reader,
    )


def test_actual_materializer_to_unchanged_strict_validator_with_split_dates(tmp_path):
    source = tmp_path / "SYNTHETIC_shared"
    pool, master, capture = _synthetic_source(source)
    before = {str(p.relative_to(source)): _sha(p) for p in source.rglob("*") if p.is_file()}
    artifact = _build(source)
    snapshot = _validate(tmp_path / "SYNTHETIC_stage_input", artifact)
    provenance = artifact["historical_provenance"]
    assert artifact["signal_date"] == provenance["price_signal_date"] == "20261007"
    assert provenance["eligibility_source_date"] == "20260930"
    assert provenance["eligibility_source_captured_at"] == capture
    assert provenance["eligibility_source_run_id"] == master["run_id"]
    assert provenance["eligibility_source_artifact_sha256"] == master["artifact_sha256"]
    for field in ("run_id", "artifact_sha256", "manifest_sha256", "receipt_sha256"):
        assert provenance[f"d1_source_{field}"] == pool.run.verification[field]
    assert snapshot["artifact"]["rows"] == artifact["rows"]
    assert len(artifact["rows"]) == len({r["symbol"] for r in artifact["rows"]}) == 100
    assert {r["signal_date"] for r in artifact["rows"]} == {"20261007"}
    assert all(artifact[flag] is False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
    assert before == {str(p.relative_to(source)): _sha(p) for p in source.rglob("*") if p.is_file()}


def test_canonical_split_date_projection_is_preserved_and_equivalent(tmp_path):
    _synthetic_source(tmp_path / "source")
    candidate = _build(tmp_path / "source")
    canonical = canonical_body(
        adapter.__dict__, tmp_path / "source", trade_date="20261008", signal_date="20261007",
        eligibility_source_date="20260930", shared_package_root=SHARED_PACKAGE_ROOT, reader=None,
    )
    assert candidate == canonical


def test_legacy_equal_dates_keep_the_existing_reader_call_and_pass_strict(tmp_path):
    pool, _, _ = _synthetic_source(
        tmp_path / "source", signal="20260929", eligibility="20260929", target="20260930"
    )
    calls = []

    def equal_date_reader(root, *, target_date, expected_signal_date):
        calls.append((target_date, expected_signal_date))
        return pool

    artifact = adapter.build_shared_hk_0_2_pool(
        tmp_path / "source", trade_date="20260930", signal_date="20260929", reader=equal_date_reader
    )
    assert calls == [("20260930", "20260929")]
    assert "historical_provenance" not in artifact
    _validate(tmp_path / "input", artifact)


def test_old_source_date_is_rejected_in_the_original_shared_reader(tmp_path):
    _synthetic_source(tmp_path / "source", signal="20260930")
    with pytest.raises(Exception, match="provenance mismatch: signal_date"):
        _build(tmp_path / "source")


@pytest.mark.parametrize("piece", ["artifact_path", "manifest_path", "receipt_path"])
def test_original_shared_reader_rejects_tampered_source_trio(tmp_path, piece):
    pool, _, _ = _synthetic_source(tmp_path / "source")
    path = getattr(pool.run, piece)
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(Exception, match="mismatch|invalid|failed closed"):
        _build(tmp_path / "source")


@pytest.mark.parametrize("field", ["signal_date", "eligibility_source_date", "security_master_artifact_sha256", "security_master_captured_at"])
def test_materializer_rejects_missing_verified_provenance_fields(tmp_path, field):
    pool, _, _ = _synthetic_source(tmp_path / "source")
    manifest = copy.deepcopy(pool.run.manifest)
    del manifest["provenance"][field]
    incomplete = replace(pool, run=replace(pool.run, manifest=manifest))
    with pytest.raises(ValueError, match="split-date eligibility provenance is incomplete"):
        _build(tmp_path / "source", reader=lambda root, **args: incomplete)


@pytest.mark.parametrize("field", ["manifest_sha256", "receipt_sha256"])
def test_materializer_requires_verified_source_trio_hashes(tmp_path, field):
    pool, _, _ = _synthetic_source(tmp_path / "source")
    verification = dict(pool.run.verification)
    del verification[field]
    incomplete = replace(pool, run=replace(pool.run, verification=verification))
    with pytest.raises(ValueError, match="split-date eligibility provenance is incomplete"):
        _build(tmp_path / "source", reader=lambda root, **args: incomplete)


@pytest.mark.parametrize("mutation,reason", [
    ("missing_provenance", "HK D1 split-date eligibility provenance missing"),
    ("old_row_date", "HK D1 row market/signal_date mismatch"),
    ("late_capture", "HK D1 eligibility source capture date mismatch"),
])
def test_unchanged_strict_validator_rejects_invalid_stored_input(tmp_path, mutation, reason):
    _synthetic_source(tmp_path / "source")
    artifact = _build(tmp_path / "source")
    if mutation == "missing_provenance":
        del artifact["historical_provenance"]
    elif mutation == "old_row_date":
        for row in artifact["rows"]:
            row["signal_date"] = "20260930"
    else:
        artifact["historical_provenance"]["eligibility_source_captured_at"] = "2026-10-07T17:20:08+08:00"
    with pytest.raises(RunnerError, match=reason):
        _validate(tmp_path / "input", artifact)


@pytest.fixture
def isolated_a_lanes(monkeypatch):
    calls = []

    def a_pool(root, *, trade_date, signal_date, **kwargs):
        calls.append((trade_date, signal_date))
        return adapter._artifact(
            trade_date=trade_date, pool_id="a_d1_premarket_pool", display_name="SYNTHETIC A lane",
            market="A", status="V192_CANDIDATE_READY", producer_id="SYNTHETIC_A_TEST_ONLY",
            source_role="SHARED_VERIFIED_V192", source_path="SYNTHETIC_A_ONLY",
            source_sha256=hashlib.sha256(b"synthetic A fixture").hexdigest(),
            rows=[{"symbol": "A.000001", "signal_date": signal_date, "target_date": trade_date}],
        )

    def missing_research(*args, **kwargs):
        raise FileNotFoundError("SYNTHETIC test excludes unrelated research")

    monkeypatch.setattr(scheduled, "build_shared_v192_premarket_pool", a_pool)
    monkeypatch.setattr(scheduled, "build_hourly_research_pool", missing_research)
    monkeypatch.setattr(scheduled, "load_baimao_preselection_pool", lambda root, package, date: scheduled._missing(
        date, pool_id="a_share_baimao_research_map", display_name="SYNTHETIC absent optional A", market="A", reason="SYNTHETIC_TEST"
    ))
    return calls


def test_actual_cli_forwards_independent_hk_dates_and_persists_bound_trio(tmp_path, isolated_a_lanes, capsys):
    _synthetic_source(tmp_path / "source")
    result = scheduled.main([
        "--trade-date", "20261008", "--signal-date", "20260930",
        "--hk-signal-date", "20261007",
        "--hk-eligibility-source-date", "20260930", "--input-root", str(tmp_path / "inputs"),
        "--shared-data-root", str(tmp_path / "source"), "--shared-package-root", str(SHARED_PACKAGE_ROOT),
        "--data-root", str(tmp_path / "input"),
    ])
    assert result == 0
    assert isolated_a_lanes == [("20261008", "20260930")]
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "READY"
    assert report["formal_pool_gate"]["required"]["hkconnect_d1_top100"]["row_count"] == 100
    pool = PreselectionPoolStore(tmp_path / "input").read_pool("20261008", "hkconnect_d1_top100")
    _validate(tmp_path / "input", pool)


def test_absent_shared_source_stays_explicit_and_does_not_change_a_dates(tmp_path, isolated_a_lanes):
    artifacts = scheduled.build_scheduled_artifacts(
        trade_date="20261008", signal_date="20260930", hk_signal_date="20261007",
        hk_eligibility_source_date="20260930", selector=None, input_root=tmp_path / "inputs",
        shared_data_root=tmp_path / "absent", shared_package_root=SHARED_PACKAGE_ROOT, data_root=tmp_path / "out",
    )
    hk = next(a for a in artifacts if a["market"] == "HK")
    a = next(a for a in artifacts if a["pool_id"] == "a_d1_premarket_pool")
    assert isolated_a_lanes == [("20261008", "20260930")]
    assert a["status"] == "V192_CANDIDATE_READY" and len(a["rows"]) == 1
    assert hk["status"] == "CANNOT_CONFIRM" and hk["rows"] == []
    # Preserve the legacy active error classification. A wrapped ENOENT is
    # currently CONTRACT_INVALID, with the original missing-path reason kept.
    assert "HK_0_2_EXACT_INPUT_CONTRACT_INVALID:" in hk["cannot_confirm"][0]
    assert "No such file or directory" in hk["cannot_confirm"][0]
    assert "historical_provenance" not in hk


def test_frozen_baseline_reproduces_the_observed_missing_provenance_boundary(tmp_path):
    original = _load_module("hk_test_original_adapter", BASELINE / "active_producer_reference/domains/preselection_materializer.py")
    _synthetic_source(tmp_path / "source", signal="20260930")
    artifact = original.build_shared_hk_0_2_pool(
        tmp_path / "source", trade_date="20261008", signal_date="20260930", shared_package_root=SHARED_PACKAGE_ROOT
    )
    assert len(artifact["rows"]) == 100
    assert {row["signal_date"] for row in artifact["rows"]} == {"20260930"}
    assert "historical_provenance" not in artifact
    with pytest.raises(RunnerError, match="HK D1 split-date eligibility provenance missing"):
        _validate(tmp_path / "input", artifact)
