from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from stage_center.acquisition import SourceResult
from stage_center.candidate_input import CandidateInput
from stage_center.live_collectors import collect_hk_auction
from stage_center.runner import (
    RunnerConfig,
    StageCenterRunner,
    _validate_hk_d1,
    _validate_hk_second_filter,
)


TRADE_DATE = "20260924"
SIGNAL_DATE = "20260923"
FIXTURE_ROOT = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "stage_20260924_hk_real"
)
SECOND_FILTER_ROOT = FIXTURE_ROOT / "opening_second_filter"
EXPECTED_D1_ARTIFACT_SHA256 = "50a014bb51a66ca5bf56853bcf25bc6dc2dacbda257a03e0bb0db2abd7448564"
EXPECTED_D1_SOURCE_SHA256 = "8ee3a43ebe014f4df7e65beb83271de79978c81e83558c908559c83a7f64291d"
EXPECTED_D1_RUN_ID = "20260924-hk-connect-d1-top100-0-2-6d0e04826549"
EXPECTED_CSV_SHA256 = "61888673037c5dab162c8bba4d9cd1e4c42de7b01be77cd6ba292fc1a4114160"


def _canonical_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _acceptance_path(root: Path) -> Path:
    return (
        root
        / "opening_second_filter"
        / TRADE_DATE
        / f"hkconnect_0920_auction_second_filter_{TRADE_DATE}.acceptance.json"
    )


def _validate_real_pair(root: Path = FIXTURE_ROOT) -> tuple[Path, Path, str]:
    return _validate_hk_second_filter(
        root / "opening_second_filter",
        TRADE_DATE,
        d1_root=root,
        preselection_source_root=root,
    )


def test_real_hk0925_pair_matches_verified_d1_source_identity() -> None:
    d1_path, d1_artifact_sha = _validate_hk_d1(
        FIXTURE_ROOT,
        TRADE_DATE,
        preselection_source_root=FIXTURE_ROOT,
    )
    d1_payload = json.loads(d1_path.read_text(encoding="utf-8"))
    acceptance = json.loads(_acceptance_path(FIXTURE_ROOT).read_text(encoding="utf-8"))

    assert d1_artifact_sha == EXPECTED_D1_ARTIFACT_SHA256
    assert hashlib.sha256(d1_path.read_bytes()).hexdigest() == EXPECTED_D1_ARTIFACT_SHA256
    assert d1_payload["source_sha256"] == EXPECTED_D1_SOURCE_SHA256
    assert acceptance["d1_artifact_sha256"] == EXPECTED_D1_SOURCE_SHA256
    assert acceptance["d1_run_id"] == d1_payload["source_run_id"] == EXPECTED_D1_RUN_ID

    csv_path, acceptance_path, csv_sha = _validate_real_pair()
    assert csv_sha == EXPECTED_CSV_SHA256
    assert hashlib.sha256(csv_path.read_bytes()).hexdigest() == EXPECTED_CSV_SHA256
    assert acceptance_path == _acceptance_path(FIXTURE_ROOT)


def test_canonical_hk0925_input_uses_source_sha_without_secondary_root_hint() -> None:
    csv_path, _acceptance_path_value, csv_sha = _validate_hk_second_filter(
        SECOND_FILTER_ROOT,
        TRADE_DATE,
        d1_root=FIXTURE_ROOT,
    )

    assert hashlib.sha256(csv_path.read_bytes()).hexdigest() == EXPECTED_CSV_SHA256
    assert csv_sha == EXPECTED_CSV_SHA256


def test_canonical_hk0925_input_rejects_local_artifact_sha_as_source_sha(tmp_path: Path) -> None:
    root = tmp_path / "frozen"
    shutil.copytree(FIXTURE_ROOT, root)
    acceptance_path = _acceptance_path(root)
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    acceptance["d1_artifact_sha256"] = EXPECTED_D1_ARTIFACT_SHA256
    _canonical_json(acceptance_path, acceptance)

    with pytest.raises(ValueError):
        _validate_hk_second_filter(
            root / "opening_second_filter",
            TRADE_DATE,
            d1_root=root,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_date",
        "wrong_run",
        "wrong_source_sha",
        "wrong_identity_layer",
        "d1_artifact_tamper",
        "manifest_tamper",
        "receipt_tamper",
    ],
)
def test_real_hk0925_parent_binding_fails_closed(tmp_path: Path, mutation: str) -> None:
    root = tmp_path / "frozen"
    shutil.copytree(FIXTURE_ROOT, root)
    acceptance_path = _acceptance_path(root)
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))

    if mutation == "wrong_date":
        acceptance["target_date"] = "20260925"
        _canonical_json(acceptance_path, acceptance)
    elif mutation == "wrong_run":
        acceptance["d1_run_id"] = "different-run"
        _canonical_json(acceptance_path, acceptance)
    elif mutation == "wrong_source_sha":
        acceptance["d1_artifact_sha256"] = "f" * 64
        _canonical_json(acceptance_path, acceptance)
    elif mutation == "wrong_identity_layer":
        acceptance["d1_artifact_sha256"] = EXPECTED_D1_ARTIFACT_SHA256
        _canonical_json(acceptance_path, acceptance)
    elif mutation == "d1_artifact_tamper":
        d1_path = root / "preselection_pools" / TRADE_DATE / "hkconnect_d1_top100.json"
        d1_payload = json.loads(d1_path.read_text(encoding="utf-8"))
        d1_payload["source_sha256"] = "f" * 64
        _canonical_json(d1_path, d1_payload)
    elif mutation == "manifest_tamper":
        manifest_path = root / "preselection_pools" / TRADE_DATE / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["hkconnect_d1_top100"] = "f" * 64
        _canonical_json(manifest_path, manifest)
    elif mutation == "receipt_tamper":
        receipt_path = (
            root
            / "preselection_pools"
            / TRADE_DATE
            / "receipts"
            / "hkconnect_d1_top100.json"
        )
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["source_sha256"] = "f" * 64
        _canonical_json(receipt_path, receipt)

    with pytest.raises(ValueError):
        _validate_hk_second_filter(
            root / "opening_second_filter",
            TRADE_DATE,
            d1_root=root,
            preselection_source_root=root,
        )


def test_isolated_real_hk0925_runner_recovery_keeps_mixed_lane_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import stage_center.runner as runner_module

    candidate_root = tmp_path / "candidate"
    candidate = CandidateInput(
        root=candidate_root,
        trade_date=TRADE_DATE,
        current_relative="fixture/current.json",
        current_sha256="a" * 64,
        run_id="isolated-candidate-run",
        codes=("A.600000",),
        artifact_sha256="b" * 64,
        manifest_sha256="c" * 64,
        receipt_sha256="d" * 64,
        source_projection_sha256="e" * 64,
        source_evidence=("fixture=isolated_candidate",),
    )
    monkeypatch.setattr(runner_module, "read_candidate_input", lambda *_args, **_kwargs: candidate)

    error = "batch=2/2 ProcessExecutionError exit_code=2 api_key=DO_NOT_LEAK " + "x" * 5000
    a_source = SourceResult(
        source_id="a_share_auction",
        status="CANNOT_CONFIRM",
        cannot_confirm=("PyTDX ExHQ execution failed in batch 2/2 api_token=DO_NOT_LEAK",),
        error=error,
        requested_rows=1,
        source_evidence=(
            "provider=PyTDX ExHQ",
            "batch_index=2/2",
            "error_type=ProcessExecutionError",
            "execution_seconds=30.5",
            "Authorization: Bearer DO_NOT_LEAK",
            "stderr_tail=" + "y" * 5000,
        ),
    )

    def a_collector(_plan, market: str) -> SourceResult:
        assert market == "A_SHARE"
        return a_source

    def hk_collector(plan, market: str) -> SourceResult:
        assert market == "HK_CONNECT"
        return collect_hk_auction(
            plan,
            codes=plan.codes_for(market),
            python_path=sys.executable,
            shared_root=FIXTURE_ROOT,
            auction_root=SECOND_FILTER_ROOT,
        )

    config = RunnerConfig(
        candidate_acquisition_root=candidate_root,
        raw_root=tmp_path / "raw",
        selection_root=tmp_path / "selection",
        receipt_root=tmp_path / "receipts",
        hk_d1_root=FIXTURE_ROOT,
        preselection_source_root=FIXTURE_ROOT,
        hk_second_filter_root=SECOND_FILTER_ROOT,
        hk_auction_root=SECOND_FILTER_ROOT,
        shared_data_root=FIXTURE_ROOT,
        python_path=Path(sys.executable),
    )
    runner = StageCenterRunner(
        config,
        collectors={"A_SHARE": a_collector, "HK_CONNECT": hk_collector},
    )
    at = datetime(2026, 9, 24, 9, 25, 5, tzinfo=ZoneInfo("Asia/Shanghai"))
    result = runner.tick(
        TRADE_DATE,
        at,
        stage_id="STAGE_0925",
        historical_backfill=True,
    )

    assert result["markets"]["HK_CONNECT"]["selection_status"] == "READY"
    assert result["markets"]["HK_CONNECT"]["selected_rows"] == 10
    hk_selection_path = (
        Path(result["namespace"]["selection_root"])
        / "selection_runs"
        / TRADE_DATE
        / "HK_CONNECT_SELECTION_STAGE_0925"
        / result["markets"]["HK_CONNECT"]["run_id"]
        / "artifact.csv"
    )
    with hk_selection_path.open("r", encoding="utf-8-sig", newline="") as stream:
        selected_codes = [row["code"] for row in csv.DictReader(stream)]
    assert selected_codes == [
        "HK.03396",
        "HK.02315",
        "HK.00537",
        "HK.07666",
        "HK.02276",
        "HK.02589",
        "HK.06082",
        "HK.06067",
        "HK.02706",
        "HK.02661",
    ]
    assert result["markets"]["HK_CONNECT"]["source_rows"] == 20
    assert result["markets"]["HK_CONNECT"]["source_status"] == "READY"
    assert result["markets"]["HK_CONNECT"]["trade_date"] == TRADE_DATE
    assert f"hk_d1_source_run_id={EXPECTED_D1_RUN_ID}" in result["markets"]["HK_CONNECT"]["source_evidence"]
    assert f"hk_d1_source_sha256={EXPECTED_D1_SOURCE_SHA256}" in result["markets"]["HK_CONNECT"]["source_evidence"]
    assert all(
        result[flag] is False
        for flag in ("production_allowed", "buy_gate_updated", "orders_sent")
    )

    a_lane = result["markets"]["A_SHARE"]
    assert a_lane["source_status"] == "CANNOT_CONFIRM"
    assert a_lane["requested_rows"] == 1
    assert a_lane["source_error"].startswith("batch=2/2 ProcessExecutionError exit_code=2")
    assert len(a_lane["source_error"]) <= 1024
    assert "DO_NOT_LEAK" not in a_lane["source_error"]
    assert "DO_NOT_LEAK" not in json.dumps(a_lane)
    assert "batch_index=2/2" in a_lane["source_evidence"]
    assert "error_type=ProcessExecutionError" in a_lane["source_evidence"]
    assert not any("DO_NOT_LEAK" in item for item in a_lane["source_evidence"])
    assert sum(len(item) for item in a_lane["source_evidence"]) <= 8192

    receipt_path = Path(result["namespace"]["receipt_root"]) / TRADE_DATE / "STAGE_0925" / "receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["markets"]["HK_CONNECT"]["selected_rows"] == 10
    assert receipt["markets"]["A_SHARE"]["source_error"] == a_lane["source_error"]
    assert receipt["orders_sent"] is False


@pytest.mark.parametrize(
    "diagnostic,secret",
    [
        ('{"api_key":"JSON_SECRET"}', "JSON_SECRET"),
        ("{'authorization': 'PYTHON_MAPPING_SECRET'}", "PYTHON_MAPPING_SECRET"),
    ],
)
def test_exception_receipt_redacts_and_bounds_quoted_secret_forms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    diagnostic: str,
    secret: str,
) -> None:
    import stage_center.runner as runner_module

    candidate_root = tmp_path / "candidate"
    candidate = CandidateInput(
        root=candidate_root,
        trade_date=TRADE_DATE,
        current_relative="fixture/current.json",
        current_sha256="a" * 64,
        run_id="isolated-candidate-run",
        codes=("A.600000",),
        artifact_sha256="b" * 64,
        manifest_sha256="c" * 64,
        receipt_sha256="d" * 64,
        source_projection_sha256="e" * 64,
        source_evidence=("fixture=isolated_candidate",),
    )
    monkeypatch.setattr(runner_module, "read_candidate_input", lambda *_args, **_kwargs: candidate)

    unbounded_error = diagnostic + " " + "x" * 5000

    def fail_binding(_runner: StageCenterRunner, _stage_id: str) -> None:
        raise ValueError(unbounded_error)

    monkeypatch.setattr(StageCenterRunner, "_validate_hk_auction_root_binding", fail_binding)
    config = RunnerConfig(
        candidate_acquisition_root=candidate_root,
        raw_root=tmp_path / "raw",
        selection_root=tmp_path / "selection",
        receipt_root=tmp_path / "receipts",
        selection_builders={},
    )
    runner = StageCenterRunner(config)
    receipt = runner._run_one(
        SimpleNamespace(trade_date=TRADE_DATE, stage_id="STAGE_0925", status="DUE")
    )

    receipt_path = (
        config.receipt_root
        / TRADE_DATE
        / "STAGE_0925"
        / "receipt.json"
    )
    persisted = json.loads(receipt_path.read_text(encoding="utf-8"))
    serialized = json.dumps(persisted, ensure_ascii=False)
    assert secret not in serialized
    assert len(persisted["error"]) <= 1024
    for market in persisted["markets"].values():
        assert len(market["first_error"]) <= 1024
        assert len(market["cannot_confirm"][0]) <= 512
