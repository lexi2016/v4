"""The post-close resolver must never return a slot already past its cutoff.

The live r7 Main resolver could return ``1640`` after 16:59:59; the lane
adapter's enqueue guard then observed it EXPIRED without attempting it, and
the next minute resolved the same expired slot again, starving every later
open slot.  These fixtures reproduce that exact ordering with temp ledgers.
"""
from __future__ import annotations

import importlib.util
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = Path(
    os.environ.get(
        "V4_R10_SCHEDULER_ARTIFACT_ROOT",
        "/Users/lexi/Desktop/学习/agents调试/v4_unified_recovery_20261102_terra/"
        "scheduler-r10-writer",
    )
)
ARTIFACT = ARTIFACT_ROOT / (
    "docs/handoffs/unified-release-20261102/run_v4_macos_scheduler_due.r10.py"
)
REPO_ARTIFACT = ROOT / (
    "docs/handoffs/unified-release-20261102/run_v4_macos_scheduler_due.r10.py"
)
SHANGHAI = ZoneInfo("Asia/Shanghai")
DAY = "20261102"


@pytest.fixture(scope="module")
def due():
    path = ARTIFACT if ARTIFACT.is_file() else REPO_ARTIFACT
    if not path.is_file():
        pytest.skip("r10 due-scheduler artifact is not available at " + str(ARTIFACT))
    spec = importlib.util.spec_from_file_location(
        "ops.run_v4_macos_scheduler_due_r10", path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _moment(hhmm: str) -> datetime:
    return datetime(2026, 11, 2, int(hhmm[:2]), int(hhmm[2:]), tzinfo=SHANGHAI)


def _receipt(root: Path, slot: str, *, status: str = "SUCCEEDED", **extra) -> None:
    path = (
        root
        / "receipts"
        / "live"
        / DAY
        / slot
        / "fixture.dispatch-receipt.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"status": status, "finished_at": "2026-11-02T07:30:00Z", **extra}
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.parametrize("hhmm", ("2144", "2244"))
def test_expired_1640_never_wins_after_its_cutoff(due, tmp_path, hhmm):
    # Make 1640 the first never-attempted post-close candidate: every earlier
    # slot is tried, exactly the live ordering that selected expired 1640.
    for slot in ("1500", "1530", "1540", "1555", "1605", "1610"):
        _receipt(tmp_path, slot)

    resolved = due.resolve_due_slot(ledger_root=tmp_path, now=_moment(hhmm))

    assert resolved["slot"] != "1640"
    assert resolved["slot"] == "1700"
    assert resolved["catchup"] is True
    assert _moment(hhmm) <= due._slot_retry_deadline(DAY, resolved["slot"])


def test_expired_retry_candidate_is_not_returned(due, tmp_path):
    # Every other post-close slot succeeded; 1640 is attempted and retryable
    # (NETWORK outside its backoff), so the pre-fix resolver returned it as a
    # retry candidate even though its original cutoff had passed.
    for slot in (
        "1500", "1530", "1540", "1555", "1605", "1610", "1700", "1710",
        "1720", "1730", "1800", "2030", "2040", "2050", "2105", "2108",
        "2110", "2115", "2140",
    ):
        _receipt(tmp_path, slot)
    _receipt(
        tmp_path,
        "1640",
        status="FAILED",
        failure_class="NETWORK",
        finished_at="2026-11-02T12:00:00Z",
    )
    # 21:00 hourly is already settled so only the post-close scan remains.
    _receipt(tmp_path, "2100")

    resolved = due.resolve_due_slot(ledger_root=tmp_path, now=_moment("2144"))

    assert resolved["slot"] != "1640"
    assert resolved["slot"] == "2144"
    assert resolved["catchup"] is False


def test_untried_slot_before_its_cutoff_is_still_selected(due, tmp_path):
    for slot in ("1500", "1530", "1540", "1555", "1605", "1610"):
        _receipt(tmp_path, slot)

    resolved = due.resolve_due_slot(ledger_root=tmp_path, now=_moment("1645"))

    assert resolved["slot"] == "1640"
    assert resolved["catchup"] is True
    assert resolved["lag_minutes"] == 5
    assert _moment("1645") <= due._slot_retry_deadline(DAY, "1640")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))