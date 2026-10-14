"""Regression for the natural 15:00:05.478530 launchd observation."""
from datetime import datetime

import pytest

from ops.run_stage_center_nodes import NODE_BY_ID, _node_mode
from stage_center.scheduler import evaluate_due


@pytest.mark.parametrize("clock,mode,due", [
    ("14:59:59.999999", "RECOVERY", "NOT_DUE"),
    ("15:00:00", "NATURAL", "DUE"),
    ("15:00:05.478530", "NATURAL", "DUE"),
    ("15:00:59.999999", "NATURAL", "DUE"),
    ("15:01:00", "RECOVERY", "LATE_CATCHUP_REPLAY"),
])
def test_node_and_stage_agree_on_launchd_minute(clock, mode, due):
    at = datetime.fromisoformat("2026-10-14T" + clock + "+08:00")
    stage = "STAGE_1445_1500"
    assert _node_mode(NODE_BY_ID[stage], "20261014", at) == mode
    assert evaluate_due(stage, "20261014", at).status == due


def test_historical_date_remains_recovery():
    at = datetime.fromisoformat("2026-10-15T15:00:02+08:00")
    assert _node_mode(NODE_BY_ID["STAGE_1445_1500"], "20261014", at) == "RECOVERY"
