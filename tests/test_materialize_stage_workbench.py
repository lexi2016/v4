"""Ops-level tests for the stage_workbench materialize CLI.

These validate the CLI wiring and fail-closed behavior, not the eight-stage
scoring itself (covered by test_stage_eight_runs / test_stage_runs). An empty
data root must yield a blocked receipt, never a crash or a partial artifact.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ops.materialize_stage_workbench import build_stage_runner, materialize


def test_empty_root_materialize_fails_closed(tmp_path: Path) -> None:
    payload = materialize(tmp_path, "20260730", "STAGE_0925", force=False)

    assert payload["ok"] is False
    assert payload["trade_date"] == "20260730"
    assert payload["stage_id"] == "STAGE_0925"
    assert payload["data_root"] == str(tmp_path.resolve())
    assert payload["ensure_status"] == "STAGE_INPUT_PRODUCTION_BLOCKED"
    assert payload["production_allowed"] is False
    assert payload["buy_gate_updated"] is False
    assert payload["orders_sent"] is False
    assert any("STAGE_INPUT" in item for item in payload["receipt"].get("cannot_confirm", []))


def test_materialize_rejects_unknown_stage(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown stage_id"):
        materialize(tmp_path, "20260730", "STAGE_9999", force=False)


def test_build_runner_uses_data_root(tmp_path: Path) -> None:
    runner = build_stage_runner(tmp_path)
    assert runner.store is not None
    # The store resolves inside the given data root, not the repo default.
    assert str(tmp_path.resolve()) in str(runner.store.root)
