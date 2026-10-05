from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from stage_center.acquisition import SourceResult
from stage_center.candidate_input import CandidateInput
from stage_center.raw_store import RawStore
from stage_center.runner import RunnerConfig, StageCenterRunner
from stage_center.selection import (
    SelectionStore,
    select_a_live_stage,
    select_hk_four_lane,
)


TRADE_DATE = "20260924"
STAGE_ID = "STAGE_0945_1030"
SHANGHAI = ZoneInfo("Asia/Shanghai")
ATTEMPT_AT = datetime(2026, 9, 24, 10, 30, 5, tzinfo=SHANGHAI)


def _raw_row(market: str) -> dict[str, object]:
    if market == "A_SHARE":
        code, name = "A.600001", "A retry fixture"
    else:
        code, name = "HK.00001", "HK retry fixture"
    return {
        "batch_index": 1,
        "code": code,
        "name": name,
        "trade_date": TRADE_DATE,
        "update_time": "2026-09-24 10:30:00",
        "last_price": 10.5,
        "open_price": 10.0,
        "high_price": 10.7,
        "low_price": 9.9,
        "prev_close_price": 10.0,
        "turnover": 1_000_000.0,
        "volume": 100_000.0,
        "bid_price": 10.49,
        "ask_price": 10.51,
        "bid_vol": 1000.0,
        "ask_vol": 900.0,
        "window_start": "2026-09-24 09:45:00",
        "window_end": "2026-09-24 10:30:00",
        "bar_count": 1,
        "temporal_cutoff_safe": True,
        "pct_chg": 5.0,
        "volume_ratio": 2.0,
        "qmt": {
            "open": 10.0,
            "lastPrice": 10.5,
            "lastClose": 10.0,
            "high": 10.7,
            "low": 9.9,
            "amount": 1_000_000.0,
            "bidVol": 1000.0,
            "askVol": 900.0,
        },
        "candidate": {"score": 1.0},
    }


def _runner(
    tmp_path: Path,
    monkeypatch,
    *,
    hk_failures: int = 1,
) -> tuple[StageCenterRunner, dict[str, int]]:
    import stage_center.runner as runner_module

    candidate_root = tmp_path / "candidate"
    candidate = CandidateInput(
        root=candidate_root,
        trade_date=TRADE_DATE,
        current_relative="fixture/current.json",
        current_sha256="a" * 64,
        run_id="stage-retry-fixture",
        codes=("A.600001",),
        artifact_sha256="b" * 64,
        manifest_sha256="c" * 64,
        receipt_sha256="d" * 64,
        source_projection_sha256="e" * 64,
        source_evidence=("fixture=bounded_market_retry",),
    )
    monkeypatch.setattr(
        runner_module,
        "read_candidate_input",
        lambda *_args, **_kwargs: candidate,
    )
    collector_calls = {"A_SHARE": 0, "HK_CONNECT": 0}
    builder_calls = {"A_SHARE": 0, "HK_CONNECT": 0}

    def a_collector(_plan, market: str) -> SourceResult:
        assert market == "A_SHARE"
        collector_calls[market] += 1
        return SourceResult(
            source_id="fixture_a",
            status="READY",
            rows=(_raw_row(market),),
            requested_rows=1,
            source_evidence=("fixture=valid_a_stage_rows",),
        )

    def hk_collector(_plan, market: str) -> SourceResult:
        assert market == "HK_CONNECT"
        collector_calls[market] += 1
        if collector_calls[market] <= hk_failures:
            return SourceResult(
                source_id="fixture_hk_exhq",
                status="CANNOT_CONFIRM",
                cannot_confirm=(
                    "PyTDX ExHQ probe execution failed",
                    "PyTDX ExHQ probe returned an error",
                    "PyTDX ExHQ batch coverage incomplete: completed=0/100",
                ),
                error="ProcessExecutionError: isolated retry fixture",
                requested_rows=1,
                source_evidence=("route=fixture_pytdx_exhq",),
            )
        return SourceResult(
            source_id="fixture_hk_exhq",
            status="READY",
            rows=(_raw_row(market),),
            requested_rows=1,
            source_evidence=("fixture=valid_hk_stage_rows",),
        )

    def a_builder(source, plan, raw):
        builder_calls["A_SHARE"] += 1
        return select_a_live_stage(
            source.rows,
            plan.trade_date,
            plan.stage_id,
            raw["artifact_sha256"],
            source_status=source.status,
            requested_rows=source.requested_rows,
            cannot_confirm=source.cannot_confirm,
            source_evidence=source.source_evidence,
        )

    def hk_builder(source, plan, raw):
        builder_calls["HK_CONNECT"] += 1
        return select_hk_four_lane(
            source.rows,
            plan.trade_date,
            plan.stage_id,
            raw["artifact_sha256"],
            source_status=source.status,
            requested_rows=source.requested_rows,
            cannot_confirm=source.cannot_confirm,
            source_evidence=source.source_evidence,
        )

    runner = StageCenterRunner(
        RunnerConfig(
            candidate_acquisition_root=candidate_root,
            raw_root=tmp_path / "raw",
            selection_root=tmp_path / "selection",
            receipt_root=tmp_path / "receipts",
            selection_builders={"A_SHARE": a_builder, "HK_CONNECT": hk_builder},
        ),
        collectors={"A_SHARE": a_collector, "HK_CONNECT": hk_collector},
    )
    return runner, {"collector_calls": collector_calls, "builder_calls": builder_calls}


def _decision(runner: StageCenterRunner):
    return next(
        item
        for item in runner.due_decisions(TRADE_DATE, ATTEMPT_AT)
        if item.stage_id == STAGE_ID
    )


def test_runner_retry_reuses_published_a_and_collects_only_missing_hk(
    tmp_path: Path, monkeypatch
) -> None:
    runner, calls = _runner(tmp_path, monkeypatch)

    first = runner._run_one(_decision(runner))
    assert first["status"] == "PARTIAL_WITH_ROWS"
    assert first["markets"]["A_SHARE"]["selected_rows"] == 1
    assert first["markets"]["HK_CONNECT"]["selected_rows"] == 0
    assert calls["collector_calls"] == {"A_SHARE": 1, "HK_CONNECT": 1}
    assert calls["builder_calls"] == {"A_SHARE": 1, "HK_CONNECT": 0}

    second = runner._run_one(_decision(runner))
    assert second["markets"]["A_SHARE"]["run_id"] == first["markets"]["A_SHARE"]["run_id"]
    assert second["markets"]["HK_CONNECT"]["selection_status"] == "READY"
    assert calls["collector_calls"] == {"A_SHARE": 1, "HK_CONNECT": 2}
    assert calls["builder_calls"] == {"A_SHARE": 1, "HK_CONNECT": 1}

    assert RawStore(runner.config.raw_root).verify_latest(
        TRADE_DATE, STAGE_ID, "A_SHARE"
    )["verified"]["row_count"] == 1
    assert RawStore(runner.config.raw_root).verify_latest(
        TRADE_DATE, STAGE_ID, "HK_CONNECT"
    )["verified"]["row_count"] == 1
    assert SelectionStore(runner.config.selection_root).read_verified(
        TRADE_DATE, STAGE_ID, "A_SHARE"
    )["run_id"] == first["markets"]["A_SHARE"]["run_id"]
    assert SelectionStore(runner.config.selection_root).read_verified(
        TRADE_DATE, STAGE_ID, "HK_CONNECT"
    )["selection_status"] == "READY"


def test_node_outcome_does_not_settle_a_retryable_hk_zero_row_failure() -> None:
    from ops import run_stage_center_nodes as nodes

    receipt = {
        "status": "PARTIAL_WITH_ROWS",
        "write_performed": True,
        "markets": {
            "A_SHARE": {
                "selection_status": "PARTIAL_WITH_ROWS",
                "selected_rows": 10,
                "source_status": "CANNOT_CONFIRM",
                "source_rows": 189,
                "requested_rows": 193,
            },
            "HK_CONNECT": {
                "status": "CANNOT_CONFIRM",
                "selection_status": "CANNOT_CONFIRM",
                "selected_rows": 0,
                "source_status": "CANNOT_CONFIRM",
                # The 2026-09-24 live failure receipt omitted source_rows;
                # exact ExHQ execution markers plus zero selected rows bind
                # this known unmaterialized market lane.
                "source_rows": None,
                "write_performed": False,
                "cannot_confirm": [
                    "PyTDX ExHQ probe execution failed",
                    "PyTDX ExHQ probe returned an error",
                    "PyTDX ExHQ batch coverage incomplete: completed=0/100",
                ],
            },
        },
    }

    outcome = nodes._node_outcome(receipt["status"], receipt)
    assert outcome == "TRANSIENT"
    assert not nodes._stage_settled({**receipt, "node_outcome": outcome})


def _node_config(tmp_path: Path, runner: StageCenterRunner) -> dict[str, object]:
    from ops import run_stage_center_nodes as nodes

    config: dict[str, object] = {
        key: str(tmp_path / f"node-{key}") for key in nodes.REQUIRED_CONFIG_KEYS
    }
    config.update(
        candidate_acquisition_root=str(runner.config.candidate_acquisition_root),
        raw_root=str(runner.config.raw_root),
        selection_root=str(runner.config.selection_root),
        receipt_root=str(runner.config.receipt_root),
        node_max_attempts=3,
        node_retry_backoff_seconds=60,
    )
    return config


def test_dispatch_retries_only_missing_hk_after_backoff(
    tmp_path: Path, monkeypatch
) -> None:
    from ops import run_stage_center_nodes as nodes

    runner, calls = _runner(tmp_path, monkeypatch)
    config = _node_config(tmp_path, runner)
    monkeypatch.setattr(
        nodes,
        "_calendar_gate",
        lambda *_args, **_kwargs: {"status": "ELIGIBLE", "trade_date": TRADE_DATE},
    )

    first = nodes._dispatch_stage(
        config,
        TRADE_DATE,
        STAGE_ID,
        ATTEMPT_AT,
        mode="NATURAL",
        runner=runner,
    )
    assert first["status"] == "PARTIAL_COMMIT_RETRY_REQUIRED"
    assert first["node_outcome"] == "TRANSIENT"
    assert first["node_attempt_count"] == 1
    assert first["retry_after"] == (ATTEMPT_AT + timedelta(seconds=60)).isoformat()
    assert first["retry_scope_markets"] == ["HK_CONNECT"]
    assert calls["collector_calls"] == {"A_SHARE": 1, "HK_CONNECT": 1}

    before_backoff = nodes._dispatch_stage(
        config,
        TRADE_DATE,
        STAGE_ID,
        ATTEMPT_AT + timedelta(seconds=59),
        mode="RECOVERY",
        runner=runner,
    )
    assert before_backoff["status"] == "SKIPPED_RETRY_BACKOFF"
    assert calls["collector_calls"] == {"A_SHARE": 1, "HK_CONNECT": 1}

    recovered = nodes._dispatch_stage(
        config,
        TRADE_DATE,
        STAGE_ID,
        ATTEMPT_AT + timedelta(seconds=60),
        mode="RECOVERY",
        runner=runner,
    )
    assert recovered["status"] == "READY"
    assert recovered["node_outcome"] == "SETTLED"
    assert recovered["node_attempt_count"] == 2
    assert recovered["retry_exhausted"] is False
    assert "retry_after" not in recovered
    assert calls["collector_calls"] == {"A_SHARE": 1, "HK_CONNECT": 2}
    assert calls["builder_calls"] == {"A_SHARE": 1, "HK_CONNECT": 1}


def test_exhq_retry_stops_at_existing_three_attempt_cap(
    tmp_path: Path, monkeypatch
) -> None:
    from ops import run_stage_center_nodes as nodes

    runner, calls = _runner(tmp_path, monkeypatch, hk_failures=99)
    config = _node_config(tmp_path, runner)
    monkeypatch.setattr(
        nodes,
        "_calendar_gate",
        lambda *_args, **_kwargs: {"status": "ELIGIBLE", "trade_date": TRADE_DATE},
    )

    result = None
    for attempt in range(3):
        result = nodes._dispatch_stage(
            config,
            TRADE_DATE,
            STAGE_ID,
            ATTEMPT_AT + timedelta(seconds=60 * attempt),
            mode="NATURAL" if attempt == 0 else "RECOVERY",
            runner=runner,
        )
    assert result is not None
    assert result["status"] == "PARTIAL_COMMIT_RETRY_REQUIRED"
    assert result["node_attempt_count"] == 3
    assert result["retry_exhausted"] is True
    assert "retry_after" not in result
    exhausted = nodes._dispatch_stage(
        config,
        TRADE_DATE,
        STAGE_ID,
        ATTEMPT_AT + timedelta(seconds=180),
        mode="RECOVERY",
        runner=runner,
    )
    assert exhausted["status"] == "SKIPPED_RETRY_EXHAUSTED"
    assert calls["collector_calls"] == {"A_SHARE": 1, "HK_CONNECT": 3}
    assert calls["builder_calls"] == {"A_SHARE": 1, "HK_CONNECT": 0}


def test_legacy_natural_failure_uses_conservative_bounded_backoff() -> None:
    from ops import run_stage_center_nodes as nodes

    old_receipt = {
        "status": "PARTIAL_WITH_ROWS",
        "node_outcome": "SETTLED_PARTIAL",
        "trade_date": TRADE_DATE,
        "stage_id": STAGE_ID,
        "dispatch_mode": "NATURAL",
        "node_attempt_count": 1,
        "retry_exhausted": False,
        "write_performed": True,
        "markets": {
            "A_SHARE": {
                "selection_status": "PARTIAL_WITH_ROWS",
                "selected_rows": 10,
                "source_status": "CANNOT_CONFIRM",
                "source_rows": 189,
                "requested_rows": 193,
            },
            "HK_CONNECT": {
                "status": "CANNOT_CONFIRM",
                "selection_status": "CANNOT_CONFIRM",
                "selected_rows": 0,
                "source_status": "CANNOT_CONFIRM",
                "write_performed": False,
                "cannot_confirm": ["PyTDX ExHQ probe execution failed"],
            },
        },
    }
    scheduled = datetime(2026, 9, 24, 10, 30, 0, tzinfo=SHANGHAI)

    assert not nodes._stage_settled(old_receipt)
    assert not nodes._retry_is_due(
        old_receipt,
        scheduled + timedelta(seconds=64),
        retry_backoff_seconds=60,
    )
    assert nodes._retry_is_due(
        old_receipt,
        scheduled + timedelta(seconds=65),
        retry_backoff_seconds=60,
    )


def test_exact_input_or_ordinary_partial_zero_row_is_not_marked_retryable() -> None:
    from ops import run_stage_center_nodes as nodes

    for reason in (
        "exact-date input missing: hkconnect_d1_top100.json",
        "HK minute window contains no eligible rows",
    ):
        receipt = {
            "status": "PARTIAL_WITH_ROWS",
            "write_performed": True,
            "markets": {
                "HK_CONNECT": {
                    "status": "CANNOT_CONFIRM",
                    "selection_status": "CANNOT_CONFIRM",
                    "selected_rows": 0,
                    "source_status": "CANNOT_CONFIRM",
                    "source_rows": 0,
                    "write_performed": False,
                    "cannot_confirm": [reason],
                },
            },
        }
        assert nodes._node_outcome(receipt["status"], receipt) == "SETTLED_PARTIAL"
        assert nodes._stage_settled(
            {**receipt, "node_outcome": "SETTLED_PARTIAL"}
        )
