"""Real early tick receipt must retain the invocation's explicit replay label."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from stage_center.runner import StageCenterRunner, build_production_config


@pytest.mark.parametrize("origin", ["MANUAL_REPLAY", "CURRENT_DAY_RESEARCH_REPLAY"])
def test_not_due_tick_retains_explicit_origin_in_owner_archive(tmp_path, origin):
    extra = ({"hk_current_day_research_root": tmp_path / "research"}
             if origin == "CURRENT_DAY_RESEARCH_REPLAY" else {})
    config = build_production_config(
        candidate_acquisition_root=tmp_path / "candidate", raw_root=tmp_path / "raw",
        selection_root=tmp_path / "selection", receipt_root=tmp_path / "receipt", **extra,
    )
    owner = StageCenterRunner(config)
    owner._execution_origin = origin
    result = owner.tick(
        "20261009", datetime(2026, 10, 9, 9, 20, tzinfo=ZoneInfo("Asia/Shanghai")),
        stage_id="STAGE_0930_0935", _skip_precapture=True,
    )
    assert result["status"] == "NOT_DUE"
    assert result.get("execution_origin") == origin
    assert result.get("dispatch_mode") == "RECOVERY"
    assert result.get("natural_verified") is False
    history = result["receipt_history"]
    raw = (config.receipt_root / history["relative_path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == history["sha256"]
    archived = json.loads(raw)
    assert archived["execution_origin"] == origin
    assert archived["dispatch_mode"] == "RECOVERY"
    assert archived["natural_verified"] is False
    assert archived["RESEARCH_ONLY"] is True
    assert all(archived[key] is False for key in ("production_allowed", "buy_gate_updated", "orders_sent"))
