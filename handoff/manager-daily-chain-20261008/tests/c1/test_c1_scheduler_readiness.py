from __future__ import annotations

import sys
import threading
from pathlib import Path

SCHEDULER_ROOT = Path(__file__).resolve().parents[1] / "release" / "scheduler_app"
if str(SCHEDULER_ROOT) not in sys.path:
    sys.path.insert(0, str(SCHEDULER_ROOT))

from ops import run_v35_macos_scheduler_daemon as daemon


def test_daemon_readiness_separates_heartbeat_owner_config_and_latest_result(monkeypatch):
    output = []
    monkeypatch.setattr(daemon, "_emit", output.append)
    monkeypatch.setattr(daemon, "_emit_announcement", lambda _: None)
    monkeypatch.delenv(daemon.ANNOUNCEMENT_BINDING_ENV, raising=False)
    for name in ("PRODUCTION_ALLOWED", "BUY_GATE_UPDATED", "ORDERS_SENT"):
        monkeypatch.setenv(name, "false")
    stop = threading.Event()
    stop.set()
    assert daemon.run_daemon(["--release-id", "offline-readiness"], stop_event=stop,
        install_signals=False) == 0
    ready = next(item for item in output if item.get("status") == "DAEMON_READY")
    state = ready["critical_task_states"]["announcement_collection"]
    assert state["execution_owner"] == "HEARTBEAT"
    assert state["ownership_status"] == "HEARTBEAT_OWNED"
    assert state["scheduler_hook_enabled"] is False
    assert state["configuration_status"] == "UNAVAILABLE"
    assert state["configuration_reason"] == "ANNOUNCEMENT_BINDING_NOT_CONFIGURED"
    assert state["latest_execution_status"] == "NOT_RUN"
    assert state["latest_success_status"] == "CANNOT_CONFIRM"
    assert state["latest_gap_status"] == "CANNOT_CONFIRM"
    assert state["latest_receipt_status"] == "NOT_OBSERVED"
    assert ready["production_allowed"] is False
    assert ready["buy_gate_updated"] is False
    assert ready["orders_sent"] is False

