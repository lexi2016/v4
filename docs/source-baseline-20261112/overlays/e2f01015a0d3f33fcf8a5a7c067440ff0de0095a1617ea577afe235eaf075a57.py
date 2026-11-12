from __future__ import annotations

from pathlib import Path

import pytest

from ops import run_stage_center_milestone


def test_milestone_retries_selection_gap_until_exact_stage_is_materialized(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, str, tuple[str, ...]]] = []
    clock = [0.0]

    class FakeConsumer:
        def __init__(self, root: Path) -> None:
            assert Path(root) == tmp_path / "selection"

        def get(self, trade_date: str, stage_id: str, *, markets=None) -> dict:
            calls.append((trade_date, stage_id, tuple(markets or ())))
            if len(calls) == 1:
                return {
                    "status": "CANNOT_CONFIRM",
                    "cannot_confirm": ["SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID"],
                }
            return {
                "status": "PARTIAL_WITH_ROWS",
                "trade_date": trade_date,
                "stage_id": stage_id,
                "markets": {"A_SHARE": {"rows": [{"code": "000001"}]}},
                "artifact_id": "artifact-a",
                "run_id": "run-a",
                "cannot_confirm": [],
            }

    def fake_sleep(seconds: float) -> None:
        clock[0] += seconds

    monkeypatch.setattr(run_stage_center_milestone, "StageSelectionConsumer", FakeConsumer)
    monkeypatch.setattr(run_stage_center_milestone.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(run_stage_center_milestone.time, "sleep", fake_sleep)

    result = run_stage_center_milestone.run_milestone(
        node="FUPAN_CLOSE_MATERIALS",
        date="20260827",
        data_root=tmp_path / "data",
        selection_root=tmp_path / "selection",
        retry_wait_seconds=1.0,
        retry_interval_seconds=1.0,
    )

    assert calls == [
        ("20260827", "STAGE_1445_1500", ("A_SHARE",)),
        ("20260827", "STAGE_1445_1500", ("A_SHARE",)),
    ]
    assert result["status"] == "PARTIAL_WITH_ROWS"
    assert result["selection_retry_count"] == 1


def test_permanent_selection_gap_stays_fail_closed_and_retryable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FakeConsumer:
        def __init__(self, root: Path) -> None:
            assert Path(root) == tmp_path / "selection"

        def get(self, trade_date: str, stage_id: str, *, markets=None) -> dict:
            return {
                "status": "CANNOT_CONFIRM",
                "cannot_confirm": ["SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID"],
            }

    monkeypatch.setattr(run_stage_center_milestone, "StageSelectionConsumer", FakeConsumer)
    result = run_stage_center_milestone.run_milestone(
        node="FUPAN_REVIEW_START",
        date="20260827",
        data_root=tmp_path / "data",
        selection_root=tmp_path / "selection",
        retry_wait_seconds=0,
    )

    assert result["status"] == "CANNOT_CONFIRM"
    assert result["failure_class"] == "UPSTREAM_NOT_READY"
    assert result["selection_retry_count"] == 0


def test_cli_returns_failure_for_unresolved_selection_gap(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(
        run_stage_center_milestone,
        "run_milestone",
        lambda **_: {"status": "CANNOT_CONFIRM", "reason": "SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID"},
    )

    exit_code = run_stage_center_milestone.main(
        [
            "--node",
            "FUPAN_CLOSE_MATERIALS",
            "--data-root",
            str(tmp_path / "data"),
            "--date",
            "20260827",
            "--stage-id",
            "STAGE_1445_1500",
            "--selection-root",
            str(tmp_path / "selection"),
        ]
    )

    assert exit_code == 1
    assert "CANNOT_CONFIRM" in capsys.readouterr().out
