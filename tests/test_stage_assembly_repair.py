"""Regression checks for the stage deadline calendar boundary."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ops import run_stage_center_nodes as nodes


def _config(tmp_path: Path) -> Path:
    payload = {key: str(tmp_path / key) for key in nodes.REQUIRED_CONFIG_KEYS}
    payload["python_path"] = sys.executable
    payload["shared_data_root"] = str(
        Path(__file__).resolve().parents[1] / "upstreams" / "v3_shared_data"
    )
    payload.update(
        node_max_attempts=1,
        node_retry_backoff_seconds=0,
        node_max_nodes_per_run=10,
    )
    path = tmp_path / "stage_center_tick_config.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_deadline_only_skips_non_trading_day_before_chain_check(tmp_path, capsys):
    path = _config(tmp_path)
    before = {
        str(file.relative_to(tmp_path)): file.read_bytes()
        for file in tmp_path.rglob("*")
        if file.is_file()
    }

    sunday_rc = nodes.main(
        [
            "--config",
            str(path),
            "--deadline-only",
            "--trade-date",
            "20260920",
            "--evaluated-at",
            "2026-09-20T09:27:00+08:00",
        ]
    )
    sunday = json.loads(capsys.readouterr().out)

    assert sunday_rc == 0, sunday
    assert sunday["status"] == "SKIPPED_NON_TRADING_DAY", sunday
    assert sunday["stage_id"] == "STAGE_0925", sunday
    assert sunday["provider_invocations"] == 0, sunday
    assert sunday["business_writes"] == 0, sunday
    assert "lanes" not in sunday

    monday_rc = nodes.main(
        [
            "--config",
            str(path),
            "--deadline-only",
            "--trade-date",
            "20260921",
            "--evaluated-at",
            "2026-09-21T09:27:00+08:00",
        ]
    )
    monday = json.loads(capsys.readouterr().out)

    assert monday_rc == 3, monday
    assert monday["status"] == "DEADLINE_CHAIN_ALERT", monday
    assert monday["first_failed_layer"] == "RAW_LATEST", monday
    assert set(monday["lanes"]) == {"A_SHARE", "HK_CONNECT"}, monday
    after = {
        str(file.relative_to(tmp_path)): file.read_bytes()
        for file in tmp_path.rglob("*")
        if file.is_file()
    }
    assert after == before
