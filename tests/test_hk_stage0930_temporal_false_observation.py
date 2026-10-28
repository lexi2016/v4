from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from stage_center.acquisition import SourceResult, StageUniverseBinding
from stage_center import raw_store
from stage_center import runner
from stage_center._runner_parts import tick_planning
from stage_center._live_collectors_parts import selection_builder_registry as registry
from stage_center.live_collectors import production_selection_builders


def _case(monkeypatch):
    codes = tuple(f"HK.{10000 + index:05d}" for index in range(100))
    code_sha = hashlib.sha256(
        json.dumps(tuple(sorted(codes)), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    monkeypatch.setattr(raw_store, "HK_0930_TDX_D1_CODE_SET_SHA256", code_sha)

    evidence = tuple(
        dict.fromkeys(
            (
                raw_store.HK_0930_TDX_RESEARCH_MODE_EVIDENCE,
                *raw_store._HK_0930_TDX_RESEARCH_MARKERS,
            )
        )
    )
    selection_evidence = (
        *evidence,
        "hk_d1_sha256=fda1cd4b334699fc4df59658b443a01388f6bb4dfd29470d9c1baabd75ad72fc",
        "hk_d1_binding_sha256=fda1cd4b334699fc4df59658b443a01388f6bb4dfd29470d9c1baabd75ad72fc",
        "hk_d1_json_sha256=fda1cd4b334699fc4df59658b443a01388f6bb4dfd29470d9c1baabd75ad72fc",
        "hk_d1_membership=exact_date_top100",
    )
    cannot_confirm = raw_store._HK_0930_TDX_RESEARCH_CANNOT_CONFIRM
    rows = []
    raw_rows = []
    for index, code in enumerate(codes, start=1):
        rows.append(
            {
                "code": code,
                "name": code,
                "open_price": 1.0,
                "last_price": 1.0,
                "high_price": 1.0,
                "low_price": 1.0,
                "prev_close_price": 1.0,
                "turnover": 1000.0,
                "volume": 100.0,
                "update_time": "2026-09-24 09:35:00",
                "window_start": "2026-09-24 09:31:00",
                "window_end": "2026-09-24 09:35:00",
                "bar_count": 5,
                "temporal_cutoff_safe": False,
                "candidate_lanes": [],
                "d1_rank": index,
                "d1_score": 0.0,
            }
        )
        raw_rows.append(
            {
                "batch_index": index,
                "code": code,
                "name": code,
                "update_time": "2026-09-24 09:35:00",
                "last_price": 1.0,
                "open_price": 1.0,
                "high_price": 1.0,
                "low_price": 1.0,
                "prev_close_price": 1.0,
                "turnover": 1000.0,
                "volume": 100.0,
                "bid_price": None,
                "ask_price": None,
                "bid_vol": None,
                "ask_vol": None,
                "window_start": "2026-09-24 09:31:00",
                "window_end": "2026-09-24 09:35:00",
                "bar_count": 5,
                "temporal_cutoff_safe": False,
            }
        )
    source = SourceResult(
        "pytdx_exhq",
        "PARTIAL_WITH_ROWS",
        rows=tuple(rows),
        requested_rows=100,
        cannot_confirm=cannot_confirm,
        source_evidence=selection_evidence,
    )
    plan = SimpleNamespace(
        trade_date="20260924",
        stage_id="STAGE_0930_0935",
        codes_for=lambda market: codes if market == "HK_CONNECT" else (),
    )
    raw = {
        "trade_date": "20260924",
        "stage_id": "STAGE_0930_0935",
        "market": "HK_CONNECT",
        "source_id": "pytdx_exhq",
        "status": "PARTIAL_WITH_ROWS",
        "requested_rows": 100,
        "missing_symbols": [],
        "cannot_confirm": list(cannot_confirm),
        "artifact_sha256": "a" * 64,
        "source_evidence": list(evidence),
        "temporal_cutoff_safe": False,
    }
    return codes, source, raw_rows, plan, raw


def test_exact_historical_mode_is_scoped_to_20260924_hk_stage(monkeypatch):
    runner_obj = object.__new__(runner.StageCenterRunner)
    monkeypatch.setattr(
        tick_planning,
        "_StageCenterRunner_tick_body",
        lambda _scope, _self, trade_date, _evaluated_at, **_kwargs: runner._HK_TDX_AFTERFACT_RESEARCH_CONTRACT.get(),
    )
    result = runner_obj.tick(
        "20260924",
        datetime(2026, 9, 24, 9, 36),
        stage_id="STAGE_0930_0935",
        historical_backfill=True,
        historical_markets=("HK_CONNECT",),
        historical_observation_contract=raw_store.HK_0930_TDX_RESEARCH_CONTRACT,
        _skip_precapture=True,
    )
    assert result == raw_store.HK_0930_TDX_RESEARCH_CONTRACT
    assert runner._HK_TDX_AFTERFACT_RESEARCH_CONTRACT.get() is None

    with pytest.raises(runner.RunnerError, match="context mismatch"):
        runner_obj.tick(
            "20260925",
            datetime(2026, 9, 25, 9, 36),
            stage_id="STAGE_0930_0935",
            historical_backfill=True,
            historical_markets=("HK_CONNECT",),
            historical_observation_contract=raw_store.HK_0930_TDX_RESEARCH_CONTRACT,
            _skip_precapture=True,
        )


def test_runner_temporal_false_gate_binds_exact_projection_and_rejects_mismatch(tmp_path, monkeypatch):
    codes, source, _raw_rows, plan, _raw = _case(monkeypatch)
    producer = dict(runner._HK_0930_TDX_D1_PRODUCER)
    projection = {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": "20260924",
        "target_date": "20260924",
        "signal_date": "20260923",
        "pool_id": "hkconnect_d1_top100",
        "stage_selection_eligible": True,
        "source_run_id": producer["run_id"],
        "source_artifact_sha256": producer["artifact_sha256"],
        "source_manifest_sha256": producer["manifest_sha256"],
        "source_receipt_sha256": producer["receipt_sha256"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "rows": [{"code": code} for code in codes],
    }
    path = tmp_path / "d1.json"

    def write_projection(signal_date):
        projection["signal_date"] = signal_date
        path.write_text(json.dumps(projection, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        monkeypatch.setattr(runner, "_HK_0930_TDX_D1_PROJECTION_SHA256", digest)
        monkeypatch.setattr(runner, "_HK_0930_TDX_D1_CODE_SET_SHA256", raw_store.HK_0930_TDX_D1_CODE_SET_SHA256)
        marker_values = tuple(
            f"historical_d1_projection_sha256={digest}"
            if marker.startswith("historical_d1_projection_sha256=")
            else marker
            for marker in raw_store._HK_0930_TDX_RESEARCH_MARKERS
        )
        monkeypatch.setattr(raw_store, "_HK_0930_TDX_RESEARCH_MARKERS", marker_values)
        evidence = tuple(
            f"historical_d1_projection_sha256={digest}"
            if marker.startswith("historical_d1_projection_sha256=")
            else marker
            for marker in source.source_evidence
        )
        bound_source = SourceResult(
            source.source_id,
            source.status,
            rows=source.rows,
            requested_rows=source.requested_rows,
            missing_symbols=source.missing_symbols,
            cannot_confirm=source.cannot_confirm,
            source_evidence=evidence,
        )
        binding = StageUniverseBinding.ready(
            market="HK_CONNECT",
            trade_date="20260924",
            role="HK_CONNECT_D1_TOP100",
            codes=codes,
            source_run_id="d1-test",
            sha256=digest,
            evidence=(
                f"hk_d1_json={path}",
                f"hk_d1_sha256={digest}",
                "hk_d1_membership=exact_date_top100",
            ),
        )
        return bound_source, binding

    source_with_binding, binding = write_projection("20260923")
    token = runner._HK_TDX_AFTERFACT_RESEARCH_CONTRACT.set(raw_store.HK_0930_TDX_RESEARCH_CONTRACT)
    try:
        authorized, contract = runner._authorize_hk_0930_tdx_temporal_false_observation(
            source_with_binding,
            plan,
            binding=binding,
            market="HK_CONNECT",
            historical_backfill=True,
        )
        assert contract == raw_store.HK_0930_TDX_RESEARCH_CONTRACT
        assert all(row["temporal_cutoff_safe"] is False for row in authorized.rows)

        wrong_signal_source, wrong_signal_binding = write_projection("20260922")
        with pytest.raises(runner.RunnerError, match="target/signal/producer lineage"):
            runner._authorize_hk_0930_tdx_temporal_false_observation(
                wrong_signal_source,
                plan,
                binding=wrong_signal_binding,
                market="HK_CONNECT",
                historical_backfill=True,
            )
    finally:
        runner._HK_TDX_AFTERFACT_RESEARCH_CONTRACT.reset(token)


def test_temporal_false_raw_rows_publish_and_verify_only_with_exact_contract(tmp_path, monkeypatch):
    _codes, source, raw_rows, _plan, _raw = _case(monkeypatch)
    store = raw_store.RawStore(tmp_path / "raw")
    published = store.publish(
        trade_date="20260924",
        stage_id="STAGE_0930_0935",
        market="HK_CONNECT",
        source_id=source.source_id,
        source_status=source.status,
        rows=raw_rows,
        cannot_confirm=source.cannot_confirm,
        source_evidence=source.source_evidence,
        requested_rows=100,
        missing_symbols=(),
        window="09:31:00-09:35:00",
        cutoff_at="09:35:00",
        research_observation_contract=raw_store.HK_0930_TDX_RESEARCH_CONTRACT,
    )

    verified = store.verify_run("20260924", "STAGE_0930_0935", "HK_CONNECT", published["run_id"])
    with (store.root / verified["artifact_relative"]).open(encoding="utf-8-sig", newline="") as stream:
        persisted = list(csv.DictReader(stream))
    assert verified["status"] == "PARTIAL_WITH_ROWS"
    assert verified["row_count"] == 100
    assert {row["temporal_cutoff_safe"] for row in persisted} == {"False"}
    rehydrated = runner._read_verified_raw_source(store.root, verified)
    assert rehydrated.status == "PARTIAL_WITH_ROWS"
    assert all(row["temporal_cutoff_safe"] is False for row in rehydrated.rows)

    _validated, issues = raw_store.validate_rows(
        raw_rows,
        trade_date="20260924",
        stage_id="STAGE_0930_0935",
        market="HK_CONNECT",
    )
    assert len(_validated) == 0
    assert any("temporal_cutoff_safe must be true" in issue for issue in issues)
    malformed = [dict(row) for row in raw_rows]
    malformed[0]["update_time"] = "2026-09-24 09:36:00"
    malformed[0]["window_end"] = "2026-09-24 09:36:00"
    _validated, issues = raw_store.validate_rows(
        malformed,
        trade_date="20260924",
        stage_id="STAGE_0930_0935",
        market="HK_CONNECT",
        allow_temporal_false_observation=True,
    )
    assert len(_validated) == 99
    assert any("temporal cutoff/window violation" in issue for issue in issues)
    with pytest.raises(raw_store.RawStoreError, match="contract mismatch"):
        raw_store.RawStore(tmp_path / "bad-window").publish(
            trade_date="20260924",
            stage_id="STAGE_0930_0935",
            market="HK_CONNECT",
            source_id=source.source_id,
            source_status=source.status,
            rows=malformed,
            cannot_confirm=source.cannot_confirm,
            source_evidence=source.source_evidence,
            requested_rows=100,
            missing_symbols=(),
            window="09:31:00-09:35:00",
            cutoff_at="09:35:00",
            research_observation_contract=raw_store.HK_0930_TDX_RESEARCH_CONTRACT,
        )

    with pytest.raises(raw_store.RawStoreError, match="contract mismatch"):
        store.publish(
            trade_date="20260924",
            stage_id="STAGE_0930_0935",
            market="HK_CONNECT",
            source_id=source.source_id,
            source_status="READY",
            rows=raw_rows,
            cannot_confirm=source.cannot_confirm,
            source_evidence=source.source_evidence,
            requested_rows=100,
            missing_symbols=(),
            window="09:31:00-09:35:00",
            cutoff_at="09:35:00",
            research_observation_contract=raw_store.HK_0930_TDX_RESEARCH_CONTRACT,
        )

    incomplete_evidence = tuple(
        marker
        for marker in source.source_evidence
        if not marker.startswith("historical_input_minute_page_set_sha256=")
    )
    with pytest.raises(raw_store.RawStoreError, match="contract mismatch"):
        raw_store.RawStore(tmp_path / "bad-contract").publish(
            trade_date="20260924",
            stage_id="STAGE_0930_0935",
            market="HK_CONNECT",
            source_id=source.source_id,
            source_status=source.status,
            rows=raw_rows,
            cannot_confirm=source.cannot_confirm,
            source_evidence=incomplete_evidence,
            requested_rows=100,
            missing_symbols=(),
            window="09:31:00-09:35:00",
            cutoff_at="09:35:00",
            research_observation_contract=raw_store.HK_0930_TDX_RESEARCH_CONTRACT,
        )


def test_exact_afterfact_selector_emits_partial_no_buy_top10_and_gap_evidence(monkeypatch):
    _codes, source, _raw_rows, plan, raw = _case(monkeypatch)
    envelope = production_selection_builders(plan.stage_id)["HK_CONNECT"](source, plan, raw)

    assert envelope["selection_status"] == "PARTIAL_WITH_ROWS"
    assert envelope["requested_rows"] == 100
    assert len(envelope["rows"]) == 10
    assert all(row["action_level"] == "NO_BUY" for row in envelope["rows"])
    assert all(not row["candidate_lanes"] and row["formal_eligible"] is False for row in envelope["rows"])
    assert envelope["production_allowed"] is False
    assert envelope["buy_gate_updated"] is False
    assert envelope["orders_sent"] is False
    assert "hk_selection_mode=HK_STAGE0930_TDX_AFTERFACT_RESEARCH_ONLY" in envelope["source_evidence"]
    assert "historical_observation=AFTERFACT_TDX_OBSERVATION_NO_BUY" in envelope["source_evidence"]
    assert "HISTORICAL_D1_INPUT_GAP_CANNOT_CONFIRM:HK.02915:rank=45" in envelope["cannot_confirm"]

    bad_plan = SimpleNamespace(**{**vars(plan), "trade_date": "20260925"})
    failed = production_selection_builders(plan.stage_id)["HK_CONNECT"](source, bad_plan, raw)
    assert failed["selection_status"] == "CANNOT_CONFIRM"
    assert failed["rows"] == []
    assert "HK_0930_TDX_RESEARCH_DATE_MISMATCH" in failed["cannot_confirm"]


def test_hk_only_temporal_false_backfill_skips_full_bundle_and_publishes_selection(
    tmp_path, monkeypatch
):
    codes = tuple(f"HK.{10000 + index:05d}" for index in range(100))
    code_sha = hashlib.sha256(
        json.dumps(tuple(sorted(codes)), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    monkeypatch.setattr(raw_store, "HK_0930_TDX_D1_CODE_SET_SHA256", code_sha)
    monkeypatch.setattr(runner, "_HK_0930_TDX_D1_CODE_SET_SHA256", code_sha)

    producer = dict(runner._HK_0930_TDX_D1_PRODUCER)
    projection = {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": "20260924",
        "target_date": "20260924",
        "signal_date": "20260923",
        "pool_id": "hkconnect_d1_top100",
        "stage_selection_eligible": True,
        "source_run_id": producer["run_id"],
        "source_artifact_sha256": producer["artifact_sha256"],
        "source_manifest_sha256": producer["manifest_sha256"],
        "source_receipt_sha256": producer["receipt_sha256"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "rows": [{"code": code} for code in codes],
    }
    projection_path = tmp_path / "d1_projection.json"
    projection_path.write_text(
        json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    projection_sha = hashlib.sha256(projection_path.read_bytes()).hexdigest()
    monkeypatch.setattr(runner, "_HK_0930_TDX_D1_PROJECTION_SHA256", projection_sha)
    markers = tuple(
        f"historical_d1_projection_sha256={projection_sha}"
        if marker.startswith("historical_d1_projection_sha256=")
        else marker
        for marker in raw_store._HK_0930_TDX_RESEARCH_MARKERS
    )
    monkeypatch.setattr(raw_store, "_HK_0930_TDX_RESEARCH_MARKERS", markers)

    codes, source, raw_rows, _plan, _raw = _case(monkeypatch)
    selection_rows_by_code = {row["code"]: row for row in source.rows}
    source = SourceResult(
        source.source_id,
        source.status,
        rows=tuple(
            {**raw_row, **selection_rows_by_code[raw_row["code"]]}
            for raw_row in raw_rows
        ),
        requested_rows=source.requested_rows,
        missing_symbols=source.missing_symbols,
        cannot_confirm=source.cannot_confirm,
        source_evidence=source.source_evidence,
    )
    binding = StageUniverseBinding.ready(
        market="HK_CONNECT",
        trade_date="20260924",
        role="HK_CONNECT_D1_TOP100",
        codes=codes,
        source_run_id="d1-test",
        sha256=projection_sha,
        evidence=(
            f"hk_d1_json={projection_path}",
            f"hk_d1_sha256={projection_sha}",
            "hk_d1_membership=exact_date_top100",
        ),
    )
    monkeypatch.setattr(
        runner,
        "_build_hk_stage_binding",
        lambda _root, _date, *, preselection_source_root=None: binding,
    )
    monkeypatch.setattr(
        runner,
        "_validate_exact_selection_inputs",
        lambda *_args, **_kwargs: (),
    )
    monkeypatch.setattr(
        runner,
        "_attach_hk_authority",
        lambda selected_source, **_kwargs: selected_source,
    )

    config = runner.RunnerConfig(
        candidate_acquisition_root=tmp_path / "missing_candidate",
        raw_root=tmp_path / "raw",
        selection_root=tmp_path / "selection",
        receipt_root=tmp_path / "receipts",
        hk_d1_root=tmp_path / "d1_root",
        preselection_source_root=tmp_path / "d1_source_root",
        shared_data_root=tmp_path / "shared",
        python_path=Path(sys.executable),
    )
    stage_runner = runner.StageCenterRunner(
        config,
        collectors={"HK_CONNECT": lambda _plan, _market: source},
    )
    result = stage_runner.tick(
        "20260924",
        datetime.fromisoformat("2026-09-24T09:36:00+08:00"),
        stage_id="STAGE_0930_0935",
        historical_backfill=True,
        historical_markets=("HK_CONNECT",),
        historical_observation_contract=raw_store.HK_0930_TDX_RESEARCH_CONTRACT,
        _skip_precapture=True,
    )

    omission_evidence = "historical_raw_bundle=OMITTED_HK_ONLY_RESEARCH_BACKFILL"
    assert result["status"] == "PARTIAL_WITH_ROWS"
    assert result["raw_bundle_publication_status"] == "OMITTED_HK_ONLY_RESEARCH_BACKFILL"
    assert result["bundle_id"] is None
    assert omission_evidence in result["source_evidence"]
    assert result["markets"]["HK_CONNECT"]["selection_status"] == "PARTIAL_WITH_ROWS"
    assert result["markets"]["HK_CONNECT"]["selected_rows"] == 10
    assert omission_evidence in result["markets"]["HK_CONNECT"]["source_evidence"]
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False

    backfill_raw_root = Path(result["namespace"]["raw_root"])
    backfill_selection_root = Path(result["namespace"]["selection_root"])
    verified_raw = raw_store.RawStore(backfill_raw_root).verify_latest(
        "20260924", "STAGE_0930_0935", "HK_CONNECT"
    )["verified"]
    assert verified_raw["status"] == "PARTIAL_WITH_ROWS"
    assert verified_raw["row_count"] == 100
    selection = runner.SelectionStore(backfill_selection_root).read_verified(
        "20260924", "STAGE_0930_0935", "HK_CONNECT"
    )
    assert len(selection["rows"]) == 10
    assert all(row["action_level"] == "NO_BUY" for row in selection["rows"])
    assert all(row["formal_eligible"] is False for row in selection["rows"])
    assert selection["production_allowed"] is False
    assert selection["buy_gate_updated"] is False
    assert selection["orders_sent"] is False
    assert omission_evidence in selection["source_evidence"]
    assert not (backfill_raw_root / "bundle_latest.json").exists()
    assert not (backfill_raw_root / "bundle_runs").exists()
    assert not (config.raw_root / "latest.json").exists()
    assert not (config.selection_root / "selection_latest.json").exists()
