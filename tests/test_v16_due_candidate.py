"""No new slots/calendars: retries must not starve unattempted existing slots."""
from datetime import datetime
import json
from zoneinfo import ZoneInfo
from ops import run_v35_macos_scheduler as scheduler


def test_postclose_unattempted_precedes_eligible_retry(tmp_path):
    path = tmp_path / "receipts/live/20260911/1500/one.dispatch-receipt.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"status": "FAILED", "failure_class": "UPSTREAM_NOT_READY",
                               "finished_at": "2026-09-11T15:01:00+08:00"}))
    result = scheduler.resolve_due_slot(ledger_root=tmp_path,
        now=datetime(2026, 9, 11, 17, 21, tzinfo=ZoneInfo("Asia/Shanghai")))
    assert result["slot"] == "1555"


def test_no_new_slot_or_calendar_is_introduced():
    assert "0415" not in scheduler.ALL_SLOTS
    assert "0515" not in scheduler.ALL_SLOTS
    assert scheduler.POST_CLOSE_CATCHUP_SLOTS[:7] == ("1500", "1555", "1605", "1608", "1700", "1710", "1720")
