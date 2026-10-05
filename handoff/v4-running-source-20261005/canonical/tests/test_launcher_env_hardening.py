"""Launcher stage-mode contract regressions (audit F12).

``shared`` is the default and requires a configured stage root (CLI or
env); ``local`` must be declared explicitly and may not also carry a shared
root.  A missing shared root fails closed instead of silently enabling the
local producer.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from apps.api.v35_api import run as run_module


def _capture_main(monkeypatch, argv):
    captured = {}

    def fake_create_app(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(run_module, "create_app", fake_create_app)
    monkeypatch.setattr(run_module.uvicorn, "run", lambda app, **kwargs: None)
    monkeypatch.setattr(run_module, "setup_json_logging", lambda: None)
    monkeypatch.setattr(sys, "argv", argv)
    run_module.main()
    return captured


def test_shared_mode_honours_stage_root_environment(monkeypatch, tmp_path: Path) -> None:
    env_root = tmp_path / "shared-selection"
    monkeypatch.setenv("V35_STAGE_CENTER_SELECTION_ROOT", str(env_root))
    captured = _capture_main(monkeypatch, ["v35-api"])
    assert captured["stage_center_selection_root"] == env_root


def test_cli_stage_root_wins_over_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("V35_STAGE_CENTER_SELECTION_ROOT", str(tmp_path / "env-root"))
    cli_root = tmp_path / "cli-root"
    captured = _capture_main(monkeypatch, ["v35-api", "--stage-selection-root", str(cli_root)])
    assert captured["stage_center_selection_root"] == cli_root


def test_shared_mode_without_stage_root_fails_closed(monkeypatch) -> None:
    monkeypatch.delenv("V35_STAGE_CENTER_SELECTION_ROOT", raising=False)
    monkeypatch.delenv("V35_STAGE_MODE", raising=False)
    with pytest.raises(SystemExit):
        _capture_main(monkeypatch, ["v35-api"])


def test_local_mode_is_explicit_and_needs_no_root(monkeypatch) -> None:
    monkeypatch.delenv("V35_STAGE_CENTER_SELECTION_ROOT", raising=False)
    monkeypatch.delenv("V35_STAGE_MODE", raising=False)
    captured = _capture_main(monkeypatch, ["v35-api", "--stage-mode", "local"])
    assert captured["stage_center_selection_root"] is None


def test_local_mode_with_shared_root_fails_closed(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("V35_STAGE_MODE", raising=False)
    with pytest.raises(SystemExit):
        _capture_main(
            monkeypatch,
            ["v35-api", "--stage-mode", "local", "--stage-selection-root", str(tmp_path)],
        )
