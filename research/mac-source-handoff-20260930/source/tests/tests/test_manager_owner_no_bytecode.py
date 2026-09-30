"""Owner loading must not create .pyc files on scheduler hot paths."""

import hashlib
import importlib.util
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest


APP_ROOT = Path(os.environ.get("V4_TEST_APP_ROOT", Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(APP_ROOT))

from ops import materialize_manager_close_discovery as materializer
from domains.manager_research_evidence import EvidenceError

assert Path(materializer.__file__).resolve().is_relative_to(APP_ROOT)


TRADE_DATE = "20260924"


def _fixture_owner(tmp_path: Path) -> tuple[Path, str, Path]:
    owner_path = tmp_path / "stage_center" / "hk_universe_preflight.py"
    owner_path.parent.mkdir(parents=True)
    owner_path.write_text(
        "def ensure_hk_connect_universe(root, trade_date):\n"
        "    return {'ok': True, 'trade_date': trade_date, "
        "'artifact_sha256': 'a' * 64, 'code_count': 693}\n",
        encoding="utf-8",
    )
    owner_sha256 = hashlib.sha256(owner_path.read_bytes()).hexdigest()
    return owner_path, owner_sha256, owner_path.parent / "__pycache__"


def _call_owner(tmp_path: Path, owner_path: Path, owner_sha256: str):
    universe_root = tmp_path / "universe"
    universe_root.mkdir(exist_ok=True)
    at = datetime(2026, 9, 24, 15, 30, tzinfo=materializer.HK)
    return materializer._invoke_universe_owner(
        universe_root=universe_root,
        trade_date=TRADE_DATE,
        futu_python=Path(sys.executable),
        owner_root=tmp_path,
        owner_sha256=owner_sha256,
        clock=lambda: at,
    )


def test_parent_owner_exec_module_temporarily_disables_bytecode(tmp_path, monkeypatch):
    owner_path, owner_sha256, pycache = _fixture_owner(tmp_path)

    def load_owner(_root, expected_sha256):
        assert expected_sha256 == owner_sha256
        spec = importlib.util.spec_from_file_location("_test_bound_owner", owner_path)
        owner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(owner)
        assert not pycache.exists(), "parent exec_module wrote owner bytecode"
        return owner

    with monkeypatch.context() as patch:
        patch.setattr(sys, "dont_write_bytecode", False)
        patch.setattr(materializer, "load_universe_owner", load_owner)
        patch.setattr(
            materializer.subprocess,
            "run",
            lambda *_args, **_kwargs: SimpleNamespace(
                returncode=0,
                stdout=materializer._OWNER_MARKER
                + json.dumps(
                    {
                        "ok": True,
                        "trade_date": TRADE_DATE,
                        "owner_sha256": owner_sha256,
                    }
                ),
                stderr="",
            ),
        )
        result = _call_owner(tmp_path, owner_path, owner_sha256)
        assert sys.dont_write_bytecode is False

    assert result["ok"] is True
    assert not pycache.exists()


def test_isolated_owner_child_disables_bytecode_despite_ignored_environment(
    tmp_path, monkeypatch
):
    owner_path, owner_sha256, pycache = _fixture_owner(tmp_path)

    with monkeypatch.context() as patch:
        patch.setattr(sys, "dont_write_bytecode", False)
        patch.setattr(
            materializer,
            "load_universe_owner",
            lambda *_args: SimpleNamespace(__file__=str(owner_path)),
        )
        # Python -I ignores this environment setting; _OWNER_CALL must disable
        # bytecode caching itself before exec_module.
        patch.setenv("PYTHONDONTWRITEBYTECODE", "1")
        result = _call_owner(tmp_path, owner_path, owner_sha256)
        assert sys.dont_write_bytecode is False

    assert result["ok"] is True
    assert result["owner_sha256"] == owner_sha256
    assert result["code_count"] == 693
    assert not pycache.exists(), "isolated owner child wrote owner bytecode"


def test_owner_child_argv_preserves_futu_venv_symlink(tmp_path: Path, monkeypatch):
    owner_path, owner_sha256, _pycache = _fixture_owner(tmp_path)
    universe_root = tmp_path / "universe"
    universe_root.mkdir()
    interpreter_link = tmp_path / "futu-venv" / "bin" / "python"
    interpreter_link.parent.mkdir(parents=True)
    interpreter_link.symlink_to(Path(sys.executable))
    at = datetime(2026, 9, 24, 15, 30, tzinfo=materializer.HK)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout=materializer._OWNER_MARKER
            + json.dumps(
                {
                    "ok": True,
                    "trade_date": TRADE_DATE,
                    "owner_sha256": owner_sha256,
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(
        materializer,
        "load_universe_owner",
        lambda *_args: SimpleNamespace(__file__=str(owner_path)),
    )
    monkeypatch.setattr(materializer.subprocess, "run", fake_run)
    result = materializer._invoke_universe_owner(
        universe_root=universe_root,
        trade_date=TRADE_DATE,
        futu_python=interpreter_link,
        owner_root=tmp_path,
        owner_sha256=owner_sha256,
        clock=lambda: at,
    )

    command, kwargs = calls[0]
    assert result["ok"] is True
    assert command[0] == str(interpreter_link)
    assert command[1:3] == ["-I", "-c"]
    assert command[4] == str(owner_path)
    assert command[5] == owner_sha256
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert 0.1 <= kwargs["timeout"] <= 45.0
    assert kwargs["check"] is False


def test_data_root_resolution_still_follows_symlinks(tmp_path: Path):
    target = tmp_path / "data"
    target.mkdir()
    alias = tmp_path / "data-alias"
    alias.symlink_to(target, target_is_directory=True)

    assert materializer._root(alias, "TEST_DATA_ROOT_REQUIRED") == target.resolve()


def test_futu_interpreter_path_must_be_absolute_existing_file_and_executable(
    tmp_path: Path, monkeypatch
):
    owner_path, owner_sha256, _pycache = _fixture_owner(tmp_path / "owner")
    universe_root = tmp_path / "universe"
    universe_root.mkdir()
    at = datetime(2026, 9, 24, 15, 30, tzinfo=materializer.HK)
    monkeypatch.setattr(
        materializer,
        "load_universe_owner",
        lambda *_args: SimpleNamespace(__file__=str(owner_path)),
    )
    monkeypatch.setattr(
        materializer.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("invalid interpreter must not spawn"),
    )

    non_executable = tmp_path / "not-executable"
    non_executable.write_text("placeholder", encoding="utf-8")
    non_executable.chmod(0o600)
    invalid_paths = (
        (Path("relative-python"), "EXISTING_FUTU_PYTHON_REQUIRED"),
        (tmp_path / "missing-python", "EXISTING_FUTU_PYTHON_MISSING"),
        (tmp_path, "EXISTING_FUTU_PYTHON_MISSING"),
        (non_executable, "EXISTING_FUTU_PYTHON_NOT_EXECUTABLE"),
    )

    for executable, reason in invalid_paths:
        with pytest.raises(EvidenceError, match=reason):
            materializer._invoke_universe_owner(
                universe_root=universe_root,
                trade_date=TRADE_DATE,
                futu_python=executable,
                owner_root=tmp_path / "owner",
                owner_sha256=owner_sha256,
                clock=lambda: at,
            )
