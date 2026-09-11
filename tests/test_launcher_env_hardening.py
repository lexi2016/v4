"""Launcher root-resolution regressions (audit F12).

The live launcher contract configures the stage-centre selection root via
environment; the CLI must still win, and a missing root must stay None
instead of silently falling back.
"""
from __future__ import annotations

import sys
from pathlib import Path

from apps.api.v35_api import run as run_module


def _capture_main(monkeypatch, argv):
    captured = {}

    def fake_create_app(**kwargs):
        captured.update(kwargs)
        return object()

    def fake_uvicorn_run(app, **kwargs):
        captured["uvicorn"] = kwargs

    monkeypatch.setattr(run_module, "create_app", fake_create_app)
    monkeypatch.setattr(run_module.uvicorn, "run", fake_uvicorn_run)
    monkeypatch.setattr(run_module, "setup_json_logging", lambda: None)
    monkeypatch.setattr(sys, "argv", argv)
    run_module.main()
    return captured


def test_stage_selection_root_env_is_honoured(monkeypatch, tmp_path: Path) -> None:
    env_root = tmp_path / "shared-selection"
    monkeypatch.setenv("V35_STAGE_CENTER_SELECTION_ROOT", str(env_root))
    captured = _capture_main(monkeypatch, ["v35-api"])
    assert captured["stage_center_selection_root"] == env_root


def test_cli_stage_selection_root_wins_over_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("V35_STAGE_CENTER_SELECTION_ROOT", str(tmp_path / "env-root"))
    cli_root = tmp_path / "cli-root"
    captured = _capture_main(monkeypatch, ["v35-api", "--stage-selection-root", str(cli_root)])
    assert captured["stage_center_selection_root"] == cli_root


def test_missing_stage_selection_root_stays_none(monkeypatch) -> None:
    monkeypatch.delenv("V35_STAGE_CENTER_SELECTION_ROOT", raising=False)
    captured = _capture_main(monkeypatch, ["v35-api"])
    assert captured["stage_center_selection_root"] is None
