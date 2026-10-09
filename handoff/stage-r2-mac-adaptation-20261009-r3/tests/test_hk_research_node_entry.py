"""Exercise actual config/main/run_nodes orchestration without a quote client."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys

import pytest

from ops import run_stage_center_nodes as nodes
from ops import run_stage_center_tick as tick
from test_hk_current_day_research import DAY, STAGE, bundle, write_json


def node_config(tmp_path, research_root=None):
    config = {key: str(tmp_path / key) for key in nodes.REQUIRED_CONFIG_KEYS}
    config.update(schema_version="stage_center.tick_config.v1", node_max_attempts=3,
                  node_retry_backoff_seconds=60, node_max_nodes_per_run=10)
    if research_root is not None:
        config["hk_current_day_research_root"] = str(research_root)
        for key in ("hk_d1_root", "hk_second_filter_root", "hk_full_universe_root",
                    "hk_auction_root", "hk_stage_replay_root"):
            config.pop(key)
    return config


def dispatch_result(config, trade_date, stage_id, evaluated, *, mode, runner, precaptures):
    # The business boundary is excluded: this test observes the real caller's
    # mode/origin decision, not simulated collector success.
    return {"status": "READY", "trade_date": trade_date, "stage_id": stage_id,
            "dispatch_mode": mode, "execution_origin": config.get("_execution_origin")}


class WallClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 9, 15, 40, tzinfo=nodes.SHANGHAI).astimezone(tz)


def test_research_config_parses_without_any_formal_hk_root(tmp_path):
    root, _, _ = bundle(tmp_path)
    path = tmp_path / "node_config.json"
    write_json(path, node_config(tmp_path, root))
    config = nodes._load_config(path)
    built = nodes._build_runner(config)
    assert built.config.hk_current_day_research_root == root
    assert built.config.hk_d1_root is None
    assert built._execution_origin == "CURRENT_DAY_RESEARCH_REPLAY"
    assert "hk_current_day_research_root" in tick.ALL_ROOTS


def test_default_node_config_still_requires_d1_root(tmp_path):
    config = node_config(tmp_path)
    config.pop("hk_d1_root")
    path = tmp_path / "node_config.json"
    write_json(path, config)
    with pytest.raises(ValueError, match="hk_d1_root"):
        nodes._load_config(path)


@pytest.mark.parametrize("after_wait", [False, True])
@pytest.mark.parametrize("origin", ["MANUAL_REPLAY", "CURRENT_DAY_RESEARCH_REPLAY"])
def test_explicit_origin_stays_recovery_even_at_natural_clock(tmp_path, monkeypatch, after_wait, origin):
    config = node_config(tmp_path)
    config["_execution_origin"] = origin
    when = datetime(2026, 10, 9, 9, 35, 0 if after_wait else 5, tzinfo=nodes.SHANGHAI)
    monkeypatch.setattr(nodes, "_dispatch_stage", dispatch_result)
    monkeypatch.setattr(nodes, "_bounded_wait_until",
                        lambda target, current, **kw: (current + timedelta(seconds=5), True)
                        if after_wait else (current, False))
    result = nodes.run_nodes(config, trade_date=DAY, evaluated_at=when, explicit_node=STAGE)
    assert result["nodes"][0]["dispatch_mode"] == "RECOVERY"
    assert result["recovery"] is True


def test_default_natural_clock_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(nodes, "_dispatch_stage", dispatch_result)
    result = nodes.run_nodes(node_config(tmp_path), trade_date=DAY,
                            evaluated_at=datetime(2026, 10, 9, 9, 35, 5, tzinfo=nodes.SHANGHAI),
                            explicit_node=STAGE)
    assert result["nodes"][0]["dispatch_mode"] == "NATURAL"
    assert result["recovery"] is False


def test_main_explicit_evaluated_at_cannot_report_natural(tmp_path, monkeypatch, capsys):
    path = tmp_path / "node_config.json"
    write_json(path, node_config(tmp_path))
    monkeypatch.setattr(nodes, "datetime", WallClock)
    monkeypatch.setattr(nodes, "_dispatch_stage", dispatch_result)
    assert nodes.main(["--config", str(path), "--node", STAGE, "--trade-date", DAY,
                       "--evaluated-at", "2026-10-09T09:35:05+08:00"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["nodes"][0]["dispatch_mode"] == "RECOVERY"
    assert result["nodes"][0]["execution_origin"] == "MANUAL_REPLAY"


def test_main_research_root_sets_distinct_replay_origin(tmp_path, monkeypatch, capsys):
    root, _, _ = bundle(tmp_path)
    path = tmp_path / "node_config.json"
    write_json(path, node_config(tmp_path, root))
    monkeypatch.setattr(nodes, "datetime", WallClock)
    monkeypatch.setattr(nodes, "_dispatch_stage", dispatch_result)
    assert nodes.main(["--config", str(path), "--node", STAGE, "--trade-date", DAY,
                       "--evaluated-at", "2026-10-09T09:35:05+08:00"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["nodes"][0]["dispatch_mode"] == "RECOVERY"
    assert result["nodes"][0]["execution_origin"] == "CURRENT_DAY_RESEARCH_REPLAY"


@pytest.mark.parametrize("research", [False, True])
def test_tick_config_optional_research_root_and_runtime_root_resolution(tmp_path, research):
    root, _, _ = bundle(tmp_path)
    config = node_config(tmp_path, root if research else None)
    if not research:
        config["hk_auction_root"] = config["hk_second_filter_root"]
    path = tmp_path / "tick_config.json"
    write_json(path, config)
    loaded = tick._load(path)
    resolved = tick.resolve_runtime_roots(loaded, DAY)
    assert resolved.get("hk_current_day_research_root") == (str(root) if research else None)
    assert bool(resolved.get("hk_d1_root")) is not research


@pytest.mark.parametrize("research,explicit_clock,expected", [
    (True, True, "CURRENT_DAY_RESEARCH_REPLAY"),
    (False, True, "MANUAL_REPLAY"), (False, False, None),
])
def test_tick_main_passes_trusted_execution_origin(tmp_path, monkeypatch, capsys, research, explicit_clock, expected):
    from stage_center import runner as runner_module

    root, _, _ = bundle(tmp_path)
    config = node_config(tmp_path, root if research else None)
    if not research:
        config["hk_auction_root"] = config["hk_second_filter_root"]
    Path(config["shared_data_root"]).mkdir()
    config["python_path"] = sys.executable
    path = tmp_path / "tick_config.json"
    write_json(path, config)

    class CapturingRunner:
        def __init__(self, config):
            self.config = config

        def tick(self, *args, **kwargs):
            return {"status": "TICK_COMPLETE", "execution_origin": getattr(self, "_execution_origin", None)}

    monkeypatch.setattr(runner_module, "StageCenterRunner", CapturingRunner)
    monkeypatch.setattr(tick, "datetime", WallClock)
    # The Mac-owned calendar file is outside this restored source package.
    # Its independent admission gate is not the origin behavior under test.
    monkeypatch.setattr(tick, "_calendar_gate", lambda day: {"status": "ELIGIBLE"})
    argv = ["--config", str(path), "--stage-id", STAGE, "--trade-date", DAY]
    if explicit_clock:
        argv += ["--evaluated-at", "2026-10-09T09:35:05+08:00", "--historical-backfill"]
    assert tick.main(argv) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["execution_origin"] == expected
