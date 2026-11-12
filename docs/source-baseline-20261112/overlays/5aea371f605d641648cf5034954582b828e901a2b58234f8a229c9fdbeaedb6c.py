from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from stage_center.candidate_input import CandidateInput, CandidateInputError
from stage_center.runner import RunnerConfig, StageCenterRunner
from stage_center.scheduler import DueDecision
from stage_center.scheduler import evaluate_due


SHANGHAI = ZoneInfo("Asia/Shanghai")
TRADE_DATE = "20260902"
CANDIDATE_SHA = "a" * 64


def _candidate(tmp_path: Path, *, current_sha: str = CANDIDATE_SHA) -> CandidateInput:
    return CandidateInput(
        root=tmp_path / "candidate",
        trade_date=TRADE_DATE,
        current_relative="current.json",
        current_sha256=current_sha,
        run_id="candidate-run",
        codes=("A.000001",),
        artifact_sha256="b" * 64,
        manifest_sha256="c" * 64,
        receipt_sha256="d" * 64,
        source_projection_sha256="e" * 64,
        source_evidence=("a_all_pool_rows=exact",),
    )


def _decision(stage_id: str, status: str) -> DueDecision:
    return DueDecision(
        stage_id=stage_id,
        trade_date=TRADE_DATE,
        status=status,
        scheduled_at=None,
        idempotency_key=f"{stage_id}-key",
        calendar={},
    )


def test_new_stage_first_attempt_is_not_starved_by_same_candidate_retry(
    monkeypatch, tmp_path: Path
) -> None:
    """A retryable early partial must yield to a later unattempted stage."""
    receipt_path = (
        tmp_path
        / "receipts"
        / TRADE_DATE
        / "STAGE_0925"
        / "receipt.json"
    )
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(
        json.dumps(
            {
                "schema_version": "stage_center.runner.receipt.v1",
                "runner": "stage_center",
                "status": "PARTIAL_WITH_ROWS",
                "trade_date": TRADE_DATE,
                "stage_id": "STAGE_0925",
                "candidate_current_sha256": CANDIDATE_SHA,
                "attempted_at": "2026-09-02T09:35:30+08:00",
                "retry_after": "2026-09-02T09:36:30+08:00",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        ),
        encoding="utf-8",
    )

    config = RunnerConfig(
        candidate_acquisition_root=tmp_path / "candidate",
        raw_root=tmp_path / "raw",
        selection_root=tmp_path / "selection",
        receipt_root=tmp_path / "receipts",
    )
    runner = StageCenterRunner(config)
    candidate = _candidate(tmp_path)
    monkeypatch.setattr(
        "stage_center.runner.read_candidate_input",
        lambda *_args, **_kwargs: candidate,
    )
    decisions = (
        _decision("STAGE_0925", "LATE_CATCHUP_REPLAY"),
        _decision("STAGE_0930_0935", "LATE_CATCHUP_REPLAY"),
    )
    monkeypatch.setattr(runner, "due_decisions", lambda *_args, **_kwargs: decisions)
    calls: list[str] = []

    def fake_run_one(decision, **_kwargs):
        calls.append(decision.stage_id)
        return {
            "status": "PARTIAL_WITH_ROWS",
            "trade_date": TRADE_DATE,
            "stage_id": decision.stage_id,
            "candidate_current_sha256": CANDIDATE_SHA,
            "candidate_run_id": candidate.run_id,
            "write_performed": True,
        }

    monkeypatch.setattr(runner, "_run_one", fake_run_one)

    result = runner.tick(
        TRADE_DATE,
        datetime(2026, 9, 2, 9, 36, tzinfo=SHANGHAI),
    )

    assert calls == ["STAGE_0930_0935"]
    assert result["status"] == "TICK_COMPLETE"
    assert result["stages"][0]["status"] == "SKIPPED_RETRY_BACKOFF"
    assert result["stages"][1]["stage_id"] == "STAGE_0930_0935"


def test_tick_stdout_is_a_bounded_structured_summary(
    capsys, monkeypatch
) -> None:
    from ops import run_stage_center_tick as wrapper

    huge_rows = [
        {"code": f"HK.{number:05d}", "name": "x" * 200}
        for number in range(100)
    ]
    result = {
        "status": "TICK_COMPLETE",
        "trade_date": TRADE_DATE,
        "stages": [
            {
                "stage_id": "STAGE_0925",
                "status": "PARTIAL_WITH_ROWS",
                "markets": {"HK_CONNECT": {"rows": huge_rows}},
            }
        ],
    }

    wrapper._print_json(result)

    stdout = capsys.readouterr().out
    assert len(stdout.encode("utf-8")) <= 4096
    payload = json.loads(stdout)
    assert payload["status"] == "TICK_COMPLETE"
    assert payload["trade_date"] == TRADE_DATE
    assert payload["stages"][0]["stage_id"] == "STAGE_0925"
    assert payload["stages"][0]["status"] == "PARTIAL_WITH_ROWS"


def test_same_candidate_retry_waits_for_backoff_then_runs(
    monkeypatch, tmp_path: Path
) -> None:
    config = RunnerConfig(
        candidate_acquisition_root=tmp_path / "candidate",
        raw_root=tmp_path / "raw",
        selection_root=tmp_path / "selection",
        receipt_root=tmp_path / "receipts",
    )
    runner = StageCenterRunner(config)
    candidate = _candidate(tmp_path)
    monkeypatch.setattr(
        "stage_center.runner.read_candidate_input",
        lambda *_args, **_kwargs: candidate,
    )
    decision = _decision("STAGE_0930_0935", "LATE_CATCHUP_REPLAY")
    monkeypatch.setattr(
        runner, "due_decisions", lambda *_args, **_kwargs: (decision,)
    )
    calls: list[str] = []

    def fake_run_one(current_decision, **_kwargs):
        calls.append(current_decision.stage_id)
        return {
            "status": "CANNOT_CONFIRM",
            "trade_date": TRADE_DATE,
            "stage_id": current_decision.stage_id,
            "candidate_current_sha256": CANDIDATE_SHA,
            "candidate_run_id": candidate.run_id,
            "write_performed": False,
        }

    monkeypatch.setattr(runner, "_run_one", fake_run_one)
    first = datetime(2026, 9, 2, 9, 36, tzinfo=SHANGHAI)

    runner.tick(TRADE_DATE, first)
    before_retry = runner.tick(TRADE_DATE, first.replace(second=30))
    after_retry = runner.tick(TRADE_DATE, first + timedelta(seconds=61))

    assert calls == ["STAGE_0930_0935", "STAGE_0930_0935"]
    assert before_retry["stages"][0]["status"] == "SKIPPED_RETRY_BACKOFF"
    assert after_retry["stages"][0]["dispatch_kind"] == "RETRY"


def test_changed_candidate_gets_one_first_attempt_then_same_candidate_backs_off(
    monkeypatch, tmp_path: Path
) -> None:
    old_sha = "a" * 64
    new_sha = "f" * 64
    receipt_path = (
        tmp_path / "receipts" / TRADE_DATE / "STAGE_0930_0935" / "receipt.json"
    )
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(
        json.dumps(
            {
                "status": "CANNOT_CONFIRM",
                "trade_date": TRADE_DATE,
                "stage_id": "STAGE_0930_0935",
                "candidate_current_sha256": old_sha,
                "attempted_at": "2026-09-02T09:34:00+08:00",
                "retry_after": "2026-09-02T09:35:00+08:00",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        ),
        encoding="utf-8",
    )
    runner = StageCenterRunner(
        RunnerConfig(
            candidate_acquisition_root=tmp_path / "candidate",
            raw_root=tmp_path / "raw",
            selection_root=tmp_path / "selection",
            receipt_root=tmp_path / "receipts",
        )
    )
    candidate = _candidate(tmp_path, current_sha=new_sha)
    monkeypatch.setattr(
        "stage_center.runner.read_candidate_input",
        lambda *_args, **_kwargs: candidate,
    )
    decision = _decision("STAGE_0930_0935", "LATE_CATCHUP_REPLAY")
    monkeypatch.setattr(runner, "due_decisions", lambda *_args, **_kwargs: (decision,))
    calls: list[str] = []

    def fake_run_one(current_decision, **_kwargs):
        calls.append(current_decision.stage_id)
        return {
            "status": "PARTIAL_WITH_ROWS",
            "trade_date": TRADE_DATE,
            "stage_id": current_decision.stage_id,
            "candidate_current_sha256": new_sha,
            "candidate_run_id": candidate.run_id,
            "write_performed": True,
        }

    monkeypatch.setattr(runner, "_run_one", fake_run_one)
    first = datetime(2026, 9, 2, 9, 36, tzinfo=SHANGHAI)

    first_result = runner.tick(TRADE_DATE, first)
    second_result = runner.tick(TRADE_DATE, first.replace(second=30))

    assert calls == ["STAGE_0930_0935"]
    assert first_result["stages"][0]["dispatch_kind"] == "FIRST_ATTEMPT"
    assert first_result["stages"][0]["candidate_current_sha256"] == new_sha
    assert second_result["stages"][0]["status"] == "SKIPPED_RETRY_BACKOFF"


def test_unverified_candidate_skips_provider_then_verified_candidate_gets_first_attempt(
    monkeypatch, tmp_path: Path
) -> None:
    old_sha = "a" * 64
    new_sha = "f" * 64
    receipt_path = (
        tmp_path / "receipts" / TRADE_DATE / "STAGE_0930_0935" / "receipt.json"
    )
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(
        json.dumps(
            {
                "status": "CANNOT_CONFIRM",
                "trade_date": TRADE_DATE,
                "stage_id": "STAGE_0930_0935",
                "candidate_current_sha256": old_sha,
                "retry_after": "2026-09-02T09:35:00+08:00",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        ),
        encoding="utf-8",
    )
    runner = StageCenterRunner(
        RunnerConfig(
            candidate_acquisition_root=tmp_path / "candidate",
            raw_root=tmp_path / "raw",
            selection_root=tmp_path / "selection",
            receipt_root=tmp_path / "receipts",
        )
    )
    candidate = _candidate(tmp_path, current_sha=new_sha)
    readable = False

    def candidate_reader(*_args, **_kwargs):
        if not readable:
            raise CandidateInputError("candidate current unreadable")
        return candidate

    monkeypatch.setattr("stage_center.runner.read_candidate_input", candidate_reader)
    decision = _decision("STAGE_0930_0935", "LATE_CATCHUP_REPLAY")
    monkeypatch.setattr(runner, "due_decisions", lambda *_args, **_kwargs: (decision,))
    calls: list[str] = []

    def fake_run_one(current_decision, **_kwargs):
        calls.append(current_decision.stage_id)
        return {
            "status": "CANNOT_CONFIRM",
            "trade_date": TRADE_DATE,
            "stage_id": current_decision.stage_id,
            "candidate_current_sha256": new_sha,
            "candidate_run_id": candidate.run_id,
            "write_performed": False,
        }

    monkeypatch.setattr(runner, "_run_one", fake_run_one)
    now = datetime(2026, 9, 2, 9, 36, tzinfo=SHANGHAI)

    missing_result = runner.tick(TRADE_DATE, now)
    readable = True
    verified_result = runner.tick(TRADE_DATE, now)

    assert missing_result["stages"][0]["status"] == "SKIPPED_CANDIDATE_UNVERIFIED"
    assert calls == ["STAGE_0930_0935"]
    assert verified_result["stages"][0]["dispatch_kind"] == "FIRST_ATTEMPT"


def test_stage_cutoff_is_inclusive_only_at_exact_second() -> None:
    before = evaluate_due(
        "STAGE_0930_0935",
        TRADE_DATE,
        datetime(2026, 9, 2, 9, 35, 5, tzinfo=SHANGHAI),
    )
    after = evaluate_due(
        "STAGE_0930_0935",
        TRADE_DATE,
        datetime(2026, 9, 2, 9, 35, 6, tzinfo=SHANGHAI),
    )

    assert before.status == "DUE"
    assert after.status == "LATE_CATCHUP_REPLAY"
