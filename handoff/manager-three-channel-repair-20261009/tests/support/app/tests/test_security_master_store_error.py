from __future__ import annotations

from pathlib import Path

import pytest

from v3_shared_data.shared_data.store import StoreError
from v4.manager_research import workspace_plan


PLAN_DATE = "20261008"
AFTER_CLOSE = "2026-10-08T11:46:44+00:00"


def test_screen_context_advances_only_screen_to_completed_selection_day() -> None:
    context = workspace_plan.screen_context(
        {
            "plan_trade_date": PLAN_DATE,
            "market_session": "20261007",
            "research_cutoff": AFTER_CLOSE,
        }
    )

    assert context["planning_market_session"] == "20261007"
    assert context["market_session"] == PLAN_DATE
    assert context["screen_phase"] == "POST_CLOSE_COMPLETED_SESSION"
    assert context["screen_session_policy"] == "COMPLETED_FULL_HK_SECURITIES_SESSION"


@pytest.mark.parametrize(
    ("failure", "expected_gap"),
    [
        (
            StoreError("HK security-master metadata invalid: '20261008'"),
            "SCREEN_SECURITY_MASTER_READ_FAILED:StoreError",
        ),
        (
            ValueError("fixture metadata read failure"),
            "SCREEN_SECURITY_MASTER_READ_FAILED:ValueError",
        ),
    ],
)
def test_security_master_failure_isolated_as_cannot_confirm(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: Exception,
    expected_gap: str,
) -> None:
    prior60 = [f"202608{day:02d}" for day in range(1, 31)] + [
        f"202609{day:02d}" for day in range(1, 31)
    ]
    previous5 = prior60[-5:]
    calls = {"panel": 0, "master": 0}

    monkeypatch.setattr(
        workspace_plan,
        "rebound_history_sessions",
        lambda _day: {"prior60": prior60, "previous5": previous5},
    )

    def read_panel(*_args: object, **_kwargs: object) -> tuple[dict, list[str]]:
        calls["panel"] += 1
        return {}, []

    def read_master(*_args: object, **_kwargs: object) -> tuple[dict, dict]:
        calls["master"] += 1
        raise failure

    monkeypatch.setattr(workspace_plan, "_read_hk02_panel_witness", read_panel)
    monkeypatch.setattr(workspace_plan, "_screen_security_master_witness", read_master)

    screen = workspace_plan.read_rebound_screen(
        tmp_path,
        {
            "plan_trade_date": PLAN_DATE,
            "market_session": "20261007",
            "research_cutoff": AFTER_CLOSE,
        },
    )

    assert screen["status"] == "CANNOT_CONFIRM"
    assert screen["verified_session"] == PLAN_DATE
    assert screen["main_screen_ready"] is False
    assert screen["cards"] == []
    assert screen["gaps"] == [expected_gap]
    assert screen["RESEARCH_ONLY"] is True
    assert screen["production_allowed"] is False
    assert screen["buy_gate_updated"] is False
    assert screen["orders_sent"] is False
    assert calls == {"panel": 1, "master": 1}
