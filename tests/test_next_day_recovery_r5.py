from __future__ import annotations

import json
import os
import sys
import subprocess
from pathlib import Path

import pytest

from infrastructure.isolated_package_loader import load_isolated_package_module

ROOT = Path(__file__).resolve().parents[1]
SHARED_ROOT = ROOT / "upstreams" / "v3_shared_data"
NS = "r5_next_day_recovery_test"


def _module(name: str):
    return load_isolated_package_module(
        SHARED_ROOT,
        package_directory="shared_data",
        module_leaf=name,
        namespace_prefix=NS,
    )


def _a_row() -> dict[str, object]:
    return {
        "ts_code": "002631.SZ",
        "stock_code": "002631",
        "stock_name": "德尔未来",
        "candidate_role": "TEST_ONLY_BUY_CANDIDATE",
        "multi_head_final_role": "B2_FRESH_ENTRY",
        "entry_pool": True,
        "rank_usage_boundary": "RANK_FOR_REVIEW_ONLY_NOT_BUY_PRIORITY",
        "formal_recommendation_allowed": False,
        "primary_buy_signal": 1,
        "secondary_buy_signal": 1,
        "gold_brick_context": "none",
        "brick_resonance_context": 1,
        "brick_buy": 1,
        "brick_buy1_low_absorb": 1,
        "brick_buy2_attack": 1,
        "brick_resonance1": 1,
        "brick_resonance2": 1,
        "brick_resonance": 1,
        "formula_source": "computed_main_chart_formula_20260515",
        "ref_hold_score": 3,
        "B1": 0,
        "B2": 0,
        "B3": 0,
        "BG": 0,
        "amount": 1000000,
        "pct_chg": 1.0,
        "route_context": "",
        "brick_context": "buy_low_absorb|buy_attack",
        "field_contract_version": "authoritative_field_contract_v0_2_phase1",
    }


def _publish_a(root: Path):
    mod = _module("v192_selector")
    panel = root.parent / "selector-source.bin"
    panel.write_bytes(b"strict-selector-source")
    mod.publish_v192_rows(
        root,
        panel_path=panel,
        signal_date="20260915",
        target_date="20260916",
        rows=[_a_row()],
        oracle_sha256s=mod.FROZEN_ORACLE_SHA256S,
    )
    return mod


def _hk_rows(*, score_offset: float = 0.0) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for rank in range(1, 101):
        code = f"HK.{rank:05d}"
        rows.append({
            "rank": rank,
            "trade_date": "20260916",
            "bar_time": "17:30",
            "code": code,
            "code_norm": code,
            "ts_code": f"{rank:05d}.HK_CONNECT",
            "name": f"测试港股{rank:03d}",
            "signal_date": "20260915",
            "target_date": "20260916",
            "score_prob_active": 101.0 - rank + score_offset,
            "selected_strategy": "prob_active",
            "weekly_tuning_selected_strategy": "prob_active",
            "production_allowed": False,
            "d1_freshness_status": "PASS",
            "cannot_confirm": "",
        })
    return rows


def _publish_hk(
    root: Path,
    *,
    universe_codes_sha256: str = "a" * 64,
    panel_sha256: str = "b" * 64,
    score_offset: float = 0.0,
):
    sec = _module("hk_security_master")
    hk = _module("hk_0_2")
    sec.publish_hk_security_master(
        root,
        trade_date="20260915",
        rows=[
            {"code": f"HK.{rank:05d}", "name": f"测试港股{rank:03d}"}
            for rank in range(1, 101)
        ],
        universe_codes_sha256=universe_codes_sha256,
        captured_at="2026-09-15T17:20:06+08:00",
    )
    hk.publish_hk_0_2_rows(
        root,
        signal_date="20260915",
        target_date="20260916",
        rows=_hk_rows(score_offset=score_offset),
        panel_sha256=panel_sha256,
    )
    return hk


def test_v192_publisher_binds_local_oracle_source_and_legacy_missing_binding_is_rejected(tmp_path: Path) -> None:
    mod = _publish_a(tmp_path / "current")
    current = mod.read_verified_v192_pool(
        tmp_path / "current", target_date="20260916", expected_signal_date="20260915"
    )
    provenance = current.run.manifest["provenance"]
    assert provenance["oracle_bundle_source_sha256"] == mod.v192_oracle_bundle.local_bundle_sha256()
    assert provenance["oracle_bundle_contract_version"] == mod.v192_oracle_bundle.ORACLE_CONTRACT_VERSION

    # Preserve all store hashes while reproducing the old source contract that
    # did not bind the local oracle bytes.  The current reader must reject it.
    legacy = tmp_path / "legacy"
    import shutil
    shutil.copytree(tmp_path / "current", legacy)
    manifest_path = legacy / current.run.verification["manifest_relative"]
    receipt_path = legacy / current.run.verification["receipt_relative"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["provenance"].pop("oracle_bundle_source_sha256")
    manifest["provenance"].pop("oracle_bundle_contract_version")
    hashing = _module("hashing")
    manifest_path.write_bytes(hashing.canonical_bytes(manifest))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["manifest_sha256"] = hashing.sha256_json(manifest)
    receipt_path.write_bytes(hashing.canonical_bytes(receipt))
    with pytest.raises(mod.StoreError, match="oracle_bundle_source_sha256"):
        mod.read_verified_v192_pool(
            legacy, target_date="20260916", expected_signal_date="20260915"
        )


def test_hk_verified_source_restore_preserves_run_bytes_and_is_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "old-shared"
    target = tmp_path / "v4-shared"
    hk = _publish_hk(source)
    source_pool = hk.read_verified_hk_0_2_pool(
        source, target_date="20260916", expected_signal_date="20260915"
    )

    outcome = hk.restore_verified_hk_0_2_source(
        source, target, signal_date="20260915", target_date="20260916"
    )
    assert outcome["status"] == "READY"
    assert outcome["restored"] is True
    restored = hk.read_verified_hk_0_2_pool(
        target, target_date="20260916", expected_signal_date="20260915"
    )
    assert restored.run.receipt["run_id"] == source_pool.run.receipt["run_id"]
    assert restored.run.verification["artifact_sha256"] == source_pool.run.verification["artifact_sha256"]
    for relative in (
        source_pool.run.verification["artifact_relative"],
        source_pool.run.verification["manifest_relative"],
        source_pool.run.verification["receipt_relative"],
    ):
        assert (target / relative).read_bytes() == (source / relative).read_bytes()

    second = hk.restore_verified_hk_0_2_source(
        source, target, signal_date="20260915", target_date="20260916"
    )
    assert second["status"] == "READY"
    assert second["already_exists"] is True


def test_hk_restore_rejects_tampered_source_before_target_publication(tmp_path: Path) -> None:
    source = tmp_path / "old-shared"
    target = tmp_path / "v4-shared"
    hk = _publish_hk(source)
    source_pool = hk.read_verified_hk_0_2_pool(
        source, target_date="20260916", expected_signal_date="20260915"
    )
    (source / source_pool.run.verification["artifact_relative"]).write_bytes(b"tampered")
    with pytest.raises(hk.StoreError):
        hk.restore_verified_hk_0_2_source(
            source, target, signal_date="20260915", target_date="20260916"
        )
    assert not (target / "latest.json").exists()


def _run_hk_cli(source: Path, target: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(SHARED_ROOT), str(ROOT), environment.get("PYTHONPATH", "")) if value
    )
    return subprocess.run(
        [
            sys.executable,
            str(SHARED_ROOT / "scripts" / "materialize_hk_0_2.py"),
            "--store-root", str(target),
            "--restore-source-root", str(source),
            "--signal-date", "20260915",
            "--target-date", "20260916",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


def test_hk_restore_cli_rejects_different_valid_target_run(tmp_path: Path) -> None:
    source = tmp_path / "old-shared"
    target = tmp_path / "v4-shared"
    _publish_hk(source)
    target_hk = _publish_hk(target, score_offset=0.25)
    target_before = target_hk.read_verified_hk_0_2_pool(
        target, target_date="20260916", expected_signal_date="20260915"
    )

    result = _run_hk_cli(source, target)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["status"] == "FAILED"
    assert "different verified run" in payload["error"]
    target_after = target_hk.read_verified_hk_0_2_pool(
        target, target_date="20260916", expected_signal_date="20260915"
    )
    assert target_after.run.receipt["run_id"] == target_before.run.receipt["run_id"]


def test_hk_restore_conflicts_on_manifest_and_security_master_lineage(tmp_path: Path) -> None:
    source = tmp_path / "old-shared"
    target = tmp_path / "v4-shared"
    source_hk = _publish_hk(source)
    target_hk = _publish_hk(target, universe_codes_sha256="c" * 64)
    source_pool = source_hk.read_verified_hk_0_2_pool(
        source, target_date="20260916", expected_signal_date="20260915"
    )
    target_pool = target_hk.read_verified_hk_0_2_pool(
        target, target_date="20260916", expected_signal_date="20260915"
    )
    assert target_pool.run.verification["run_id"] == source_pool.run.verification["run_id"]
    assert target_pool.run.verification["artifact_sha256"] == source_pool.run.verification["artifact_sha256"]
    assert target_pool.run.verification["manifest_sha256"] != source_pool.run.verification["manifest_sha256"]
    assert target_pool.run.manifest["provenance"]["security_master_run_id"] != source_pool.run.manifest["provenance"]["security_master_run_id"]
    target_latest_before = (target / "latest.json").read_bytes()

    with pytest.raises(target_hk.StoreError, match="different verified run"):
        target_hk.restore_verified_hk_0_2_source(
            source, target, signal_date="20260915", target_date="20260916"
        )
    assert (target / "latest.json").read_bytes() == target_latest_before


def test_hk_restore_rejects_untrusted_latest_relative_metadata(tmp_path: Path) -> None:
    source = tmp_path / "old-shared"
    target = tmp_path / "v4-shared"
    hk = _publish_hk(source)
    source_pool = hk.read_verified_hk_0_2_pool(
        source, target_date="20260916", expected_signal_date="20260915"
    )
    latest_path = source / "latest.json"
    latest = json.loads(latest_path.read_text(encoding="utf-8"))
    key = next(
        key for key, entry in latest["entries"].items()
        if entry.get("run_id") == source_pool.run.verification["run_id"]
    )
    latest["entries"][key]["artifact_relative"] = "../../outside/artifact.csv"
    latest_path.write_bytes(_module("hashing").canonical_bytes(latest))

    with pytest.raises(hk.StoreError, match="latest metadata mismatch"):
        hk.restore_verified_hk_0_2_source(
            source, target, signal_date="20260915", target_date="20260916"
        )
    assert not target.exists()


def test_preselection_registry_reuses_exact_a_and_hk_sources_without_producer_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
    from contracts.runtime_tasks import DispatchMode, DispatchRequest

    shared = tmp_path / "shared"
    _publish_a(shared)
    _publish_hk(shared)
    calls: list[str] = []

    def fake_run(module, _arguments, **_kwargs):
        calls.append(module)
        return {
            "status": "SUCCEEDED", "exit_code": 0, "stdout": "", "stderr": "",
            "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        }

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        shared_data_root=shared,
        hk_universe_root=tmp_path / "hk-universe",
        shared_package_root=SHARED_ROOT,
        selector_data_root=None,
        preselection_input_root=tmp_path / "inputs",
        stage_selection_root=tmp_path / "stage",
        repo_root=ROOT,
        runner=lambda *a, **k: None,
    )
    registry._run = fake_run
    request = DispatchRequest("20260915", "20260915", "20260916", "1730", DispatchMode.LIVE)
    result = registry._preselection_pools(request)
    assert result["status"] == "SUCCEEDED"
    assert result["a_selector_status"] == "READY"
    assert result["hk_lane_status"] == "SUCCEEDED"
    for forbidden in (
        "ops.materialize_shared_v192_preselection",
        "scripts.update_hk_0_2_panel",
        "ops.ensure_hk_security_master",
        "scripts.materialize_hk_0_2",
    ):
        assert forbidden not in calls
    assert "ops.materialize_scheduled_preselection" in calls


def test_dispatcher_failure_of_runtime_evidence_does_not_suppress_preselection_and_writes_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from infrastructure.scheduling import dispatcher as dispatcher_module
    from infrastructure.scheduling.catalog import load_workload_catalog
    from infrastructure.scheduling.dispatcher import WorkloadExecutionError, dispatch_due
    from infrastructure.scheduling.execution_ledger import ExecutionLedger
    from contracts.runtime_tasks import DispatchMode, DispatchRequest

    monkeypatch.setattr(
        dispatcher_module,
        "validate_release_identity",
        lambda: {
            "release_id": "test-r5", "app_root": str(ROOT),
            "release_manifest_path": str(ROOT / "release.json"),
            "release_manifest_sha256": "c" * 64,
        },
    )
    seen: list[str] = []

    def executor(workload, _request, _decision):
        seen.append(workload.workload_id)
        if workload.workload_id == "research_panel_runtime_evidence":
            raise WorkloadExecutionError({
                "status": "FAILED", "workload_id": workload.workload_id,
                "failure_class": "UPSTREAM_NOT_READY", "stderr": "runtime evidence missing",
            })
        return {"status": "SUCCEEDED", "workload_id": workload.workload_id}

    request = DispatchRequest("20260915", "20260915", "20260916", "1730", DispatchMode.LIVE)
    ledger = ExecutionLedger(tmp_path / "ledger")
    receipt = dispatch_due(request, load_workload_catalog(), executor, ledger=ledger)
    assert "research_panel_runtime_evidence" in seen
    assert "preselection_pools" in seen
    assert "preselection_pools" in receipt.started_workload_ids
    assert receipt.status == "FAILED"
    saved = json.loads((ledger.root / receipt.receipt_path).read_text(encoding="utf-8"))
    assert saved["business_date"] == "20260915"
    assert saved["target_date"] == "20260916"
    assert "preselection_pools" in saved["started_workload_ids"]
    assert saved["production_allowed"] is False
    assert saved["buy_gate_updated"] is False
    assert saved["orders_sent"] is False
