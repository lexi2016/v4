"""A shared-data launcher must not silently become a local producer."""
from pathlib import Path
import pytest
from apps.api.v35_api import run

def _prepare(monkeypatch, args):
    seen = {}
    monkeypatch.setattr('sys.argv', ['run', *args])
    monkeypatch.setattr(run, 'create_app', lambda **kwargs: seen.update(kwargs) or object())
    monkeypatch.setattr(run, 'setup_json_logging', lambda: None)
    monkeypatch.setattr(run.uvicorn, 'run', lambda *args, **kwargs: None)
    monkeypatch.delenv('V35_STAGE_CENTER_SELECTION_ROOT', raising=False)
    monkeypatch.delenv('V35_STAGE_MODE', raising=False)
    return seen

def test_default_shared_mode_without_root_fails_closed(monkeypatch):
    seen = _prepare(monkeypatch, [])
    with pytest.raises(SystemExit) as exc:
        run.main()
    assert exc.value.code == 2
    assert seen == {}

def test_local_producer_requires_explicit_mode(monkeypatch):
    seen = _prepare(monkeypatch, ['--stage-mode', 'local'])
    run.main()
    assert seen['stage_center_selection_root'] is None

def test_local_mode_rejects_simultaneous_shared_root(monkeypatch, tmp_path):
    seen = _prepare(monkeypatch, ['--stage-mode', 'local', '--stage-selection-root', str(tmp_path)])
    with pytest.raises(SystemExit):
        run.main()
    assert seen == {}

def test_cli_shared_root_overrides_environment(monkeypatch, tmp_path):
    shared = tmp_path / 'shared'
    seen = _prepare(monkeypatch, ['--stage-selection-root', str(shared)])
    monkeypatch.setenv('V35_STAGE_CENTER_SELECTION_ROOT', str(tmp_path / 'other'))
    run.main()
    assert seen['stage_center_selection_root'] == shared

def test_environment_mode_invalid_value_is_rejected(monkeypatch):
    seen = _prepare(monkeypatch, [])
    monkeypatch.setenv('V35_STAGE_MODE', 'auto')
    with pytest.raises(SystemExit):
        run.main()
    assert seen == {}
