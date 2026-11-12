from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from infrastructure.preselection_pool_store import PreselectionPoolStore
from stage_center.acquisition import SourceResult
from stage_center.candidate_input import CandidateInput
from stage_center.scheduler import DueDecision
from stage_center.runner import (
    RunnerConfig,
    RunnerError,
    StageCenterRunner,
    _validate_exact_selection_inputs,
)
from test_hk_observation_calendar_20260925 import _hk_d1_pool


def _verified_prior_pool(root: Path) -> None:
    PreselectionPoolStore(root).materialize(
        _hk_d1_pool("20260924", "20260923")
    )


def _config(tmp_path: Path, d1_root: Path) -> RunnerConfig:
    return RunnerConfig(
        candidate_acquisition_root=tmp_path / "candidate",
        raw_root=tmp_path / "raw",
        selection_root=tmp_path / "selection",
        receipt_root=tmp_path / "receipts",
        hk_d1_root=d1_root,
        shared_data_root=tmp_path / "shared",
        python_path=Path(sys.executable),
    )


def _run_hk_only(monkeypatch, tmp_path: Path, builders: dict[str, object]):
    d1_root = tmp_path / "verified-source"
    _verified_prior_pool(d1_root)
    config = _config(tmp_path, d1_root)
    candidate = CandidateInput(
        root=config.candidate_acquisition_root,
        trade_date="20260925",
        current_relative="current.json",
        current_sha256="a" * 64,
        run_id="fixture-candidate",
        codes=tuple(f"HK.{i:05d}" for i in range(1, 101)),
        artifact_sha256="b" * 64,
        manifest_sha256="c" * 64,
        receipt_sha256="d" * 64,
        source_projection_sha256="e" * 64,
        source_evidence=("fixture=synthetic",),
    )
    monkeypatch.setattr(
        "stage_center.runner.read_candidate_input",
        lambda *_args, **_kwargs: candidate,
    )
    plan = SimpleNamespace(
        codes_for=lambda market: candidate.codes if market == "HK_CONNECT" else (),
    )
    monkeypatch.setattr("stage_center.runner.build_plan", lambda *_args, **_kwargs: plan)
    collector_calls: list[str] = []

    def hk_collector(_plan, market):
        collector_calls.append(market)
        return SourceResult(
            source_id="synthetic-hk",
            status="CANNOT_CONFIRM",
            cannot_confirm=("FIXTURE_STOP_AFTER_COLLECTOR",),
        )

    def a_collector(_plan, market):
        collector_calls.append(market)
        return SourceResult(
            source_id="unexpected-a",
            status="CANNOT_CONFIRM",
            cannot_confirm=("UNEXPECTED_A_LANE",),
        )

    import stage_center.live_collectors as live_collectors

    monkeypatch.setattr(
        live_collectors,
        "production_collectors",
        lambda **_kwargs: {"A_SHARE": a_collector, "HK_CONNECT": hk_collector},
    )
    monkeypatch.setattr(
        live_collectors,
        "production_selection_builders",
        lambda _stage_id: builders,
    )
    monkeypatch.setattr(
        StageCenterRunner,
        "_existing_slot",
        lambda *_args, **_kwargs: ("ABSENT", None),
    )
    result = StageCenterRunner(config)._run_one(
        DueDecision(
            stage_id="STAGE_0930_0935",
            trade_date="20260925",
            status="DUE",
            scheduled_at=None,
            idempotency_key="fixture",
            calendar={},
        )
    )
    return result, collector_calls


def test_exact_input_binding_accepts_verified_prior_hk_pool_and_keeps_0925_filter_exact(tmp_path: Path) -> None:
    d1_root = tmp_path / "verified-source"
    _verified_prior_pool(d1_root)
    config = _config(tmp_path, d1_root)

    evidence = _validate_exact_selection_inputs(
        config, "20260925", "STAGE_0930_0935", market="HK_CONNECT"
    )

    assert "hk_d1_source_trade_date=20260924" in evidence
    assert "hk_d1_source_signal_date=20260923" in evidence
    assert any(item.startswith("hk_d1_sha256=") for item in evidence)
    assert "hk_observation_trade_date=20260925" in evidence
    assert "hk_acquisition_scope=PRIOR_VERIFIED_D1_OBSERVATION" in evidence
    with pytest.raises(RunnerError, match="second-filter root is required"):
        _validate_exact_selection_inputs(
            config, "20260925", "STAGE_0925", market="HK_CONNECT"
        )


def test_run_one_filters_full_stage_builders_to_hk_observation_lane(monkeypatch, tmp_path: Path) -> None:
    builder = lambda *_args, **_kwargs: {}
    result, collector_calls = _run_hk_only(
        monkeypatch,
        tmp_path,
        {"A_SHARE": builder, "HK_CONNECT": builder},
    )

    assert collector_calls == ["HK_CONNECT"]
    assert result["status"] == "CANNOT_CONFIRM"
    assert "selection builders must provide exactly" not in str(result.get("error", ""))
    assert "FIXTURE_STOP_AFTER_COLLECTOR" in str(result)


def test_run_one_still_rejects_a_missing_builder_for_an_open_market(monkeypatch, tmp_path: Path) -> None:
    result, collector_calls = _run_hk_only(
        monkeypatch,
        tmp_path,
        {"A_SHARE": lambda *_args, **_kwargs: {}},
    )

    assert collector_calls == []
    assert result["status"] == "CANNOT_CONFIRM"
    assert "selection builders must provide exactly ('HK_CONNECT',)" in str(result.get("error", ""))
