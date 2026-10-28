"""Mac-specific checks for native cross-root identity and lock behavior."""
from __future__ import annotations
import os
import sys
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
import infrastructure.stage_source_roots as source_roots
from infrastructure.stage_source_roots import publication_source_lease, resolve_source_root

def _external_lock_holder_script() -> str:
    return """
import sys, time
from pathlib import Path
from infrastructure.interprocess_lock import owned_interprocess_lock
lock_path, ready_path, release_path = map(Path, sys.argv[1:4])
with owned_interprocess_lock(lock_path, timeout_seconds=5, timeout_message='external holder timeout'):
    ready_path.write_text('ready')
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not release_path.exists():
        time.sleep(0.01)
"""

@pytest.mark.skipif(sys.platform != "darwin", reason="Mac filesystem contract")
def test_case_aliased_parent_child_roots_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    source_alias = tmp_path / "SOURCE"
    try:
        aliases_same_directory = source_alias.is_dir() and os.path.samefile(source, source_alias)
    except OSError:
        aliases_same_directory = False
    if not aliases_same_directory:
        pytest.skip("scratch volume is case-sensitive; no case alias can be exercised")
    target = source_alias / "child"
    with pytest.raises(ValueError, match="overlap"):
        resolve_source_root(target, source)

@pytest.mark.skipif(sys.platform != "darwin", reason="Mac filesystem contract")
def test_legacy_prep_expands_tilde_target_without_touching_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ops._run_stage_center_nodes_parts.node_entry import _materialize_candidate_body
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    original_expanduser = Path.expanduser
    def expanduser(path: Path) -> Path:
        if str(path).startswith("~/"):
            return fake_home.joinpath(*Path(str(path)).parts[1:])
        return original_expanduser(path)
    monkeypatch.setattr(Path, "expanduser", expanduser)
    scope = {
        "Path": Path,
        "Mapping": dict,
        "PREP_NODE_ID": "PREP_0915",
        "_calendar_gate": lambda *a, **k: {"status": "ELIGIBLE"},
        "_candidate_current_is_verified": lambda *a, **k: None,
        "_safe_flags": lambda: {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
    }
    calls = []
    def materializer(root, trade_date, **kwargs):
        calls.append((root, trade_date, kwargs))
        return {"status": "READY", "trade_date": trade_date}
    result = _materialize_candidate_body(scope, {"candidate_acquisition_root": "~/candidate"}, "20260928", materializer=materializer)
    assert result["status"] == "READY"
    assert calls[0][0] == fake_home / "candidate"

@pytest.mark.skipif(sys.platform != "darwin", reason="Mac filesystem contract")
def test_explicit_prep_rejects_target_symlink_before_resolution(tmp_path: Path) -> None:
    from ops._run_stage_center_nodes_parts.node_entry import _materialize_candidate_body
    source = tmp_path / "source"
    source.mkdir()
    target_real = tmp_path / "target"
    target_real.mkdir()
    target_alias = tmp_path / "target-alias"
    target_alias.symlink_to(target_real, target_is_directory=True)
    scope = {
        "Path": Path,
        "Mapping": dict,
        "PREP_NODE_ID": "PREP_0915",
        "_calendar_gate": lambda *a, **k: {"status": "ELIGIBLE"},
        "_candidate_current_is_verified": lambda *a, **k: None,
        "_safe_flags": lambda: {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
    }
    calls = []
    def materializer(root, trade_date, **kwargs):
        calls.append((root, trade_date, kwargs))
        return {"status": "READY", "trade_date": trade_date}
    result = _materialize_candidate_body(
        scope,
        {"candidate_acquisition_root": str(target_alias), "preselection_source_root": str(source)},
        "20260928",
        materializer=materializer,
    )
    assert result["status"] == "CANNOT_CONFIRM"
    assert "symlink" in result["error"]
    assert calls == []

@pytest.mark.parametrize("held_side", ["source", "target"])
@pytest.mark.skipif(sys.platform != "darwin", reason="Mac cross-process lock contract")
def test_source_and_target_locks_block_when_held_by_another_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, held_side: str
) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    held_root = source if held_side == "source" else target
    ready = tmp_path / "holder-ready"
    release = tmp_path / "holder-release"
    child_env = dict(os.environ)
    child_env["PYTHONPATH"] = str(Path(__file__).resolve().parents[4] / "v4_bigcode_mac_20260928" / "writer" / "batch05" / "source")
    process = subprocess.Popen(
        [sys.executable, "-B", "-c", _external_lock_holder_script(), str(held_root / ".import.lock"), str(ready), str(release)],
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not ready.exists() and process.poll() is None:
            time.sleep(0.01)
        assert ready.exists(), "second process failed to acquire native lock"
        real_lock = source_roots.owned_interprocess_lock
        def short_timeout(path, **kwargs):
            kwargs["timeout_seconds"] = 0.1
            kwargs["timeout_message"] = "test cross-root lock timeout"
            return real_lock(path, **kwargs)
        monkeypatch.setattr(source_roots, "owned_interprocess_lock", short_timeout)
        with pytest.raises(ValueError, match="test cross-root lock timeout"):
            with publication_source_lease(target, source):
                pytest.fail("publication acquired a root lock held by another process")
    finally:
        release.write_text("release")
        stdout, stderr = process.communicate(timeout=6)
    assert process.returncode == 0, f"lock holder exit={process.returncode}, stdout={stdout!r}, stderr={stderr!r}"

@pytest.mark.skipif(sys.platform != "darwin", reason="Mac opposite-root lock ordering contract")
def test_opposite_source_target_orders_acquire_roots_in_one_global_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_a = tmp_path / "a-root"
    source_b = tmp_path / "b-root"
    source_a.mkdir()
    source_b.mkdir()
    expected = sorted((source_a, source_b), key=str)
    start = threading.Barrier(2)
    local = threading.local()
    observed = {}
    guard = threading.Lock()
    first_attempt = threading.Barrier(2)
    real_lock = source_roots.owned_interprocess_lock
    def synchronized_lock(path, **kwargs):
        label = local.label
        root = Path(path).parent
        with guard:
            observed.setdefault(label, []).append(root)
            is_first = len(observed[label]) == 1
        if is_first:
            first_attempt.wait(timeout=3)
        kwargs["timeout_seconds"] = 2
        kwargs["timeout_message"] = "opposite-root lock ordering deadlock"
        return real_lock(path, **kwargs)
    monkeypatch.setattr(source_roots, "owned_interprocess_lock", synchronized_lock)
    def acquire(label: str, target: Path, source: Path) -> str:
        local.label = label
        start.wait(timeout=3)
        with publication_source_lease(target, source):
            time.sleep(0.03)
        return label
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(acquire, "a-to-b", source_b, source_a)
        second = pool.submit(acquire, "b-to-a", source_a, source_b)
        assert first.result(timeout=5) == "a-to-b"
        assert second.result(timeout=5) == "b-to-a"
    assert observed["a-to-b"] == expected
    assert observed["b-to-a"] == expected

@pytest.mark.skipif(sys.platform != "darwin", reason="Mac filesystem contract")
def test_legacy_resolver_expands_tilde(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_home = tmp_path / "home"
    target = fake_home / "candidate"
    target.mkdir(parents=True)
    original_expanduser = Path.expanduser
    def expanduser(path: Path) -> Path:
        if str(path).startswith("~/"):
            return fake_home.joinpath(*Path(str(path)).parts[1:])
        return original_expanduser(path)
    monkeypatch.setattr(Path, "expanduser", expanduser)
    legacy_target = Path("~/candidate")
    resolved = resolve_source_root(legacy_target, None)
    assert resolved == target.resolve()

@pytest.mark.skipif(sys.platform != "darwin", reason="Mac filesystem contract")
def test_legacy_publication_lease_expands_tilde_before_locking(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_home = tmp_path / "home"
    target = fake_home / "candidate"
    target.mkdir(parents=True)
    original_expanduser = Path.expanduser
    def expanduser(path: Path) -> Path:
        if str(path).startswith("~/"):
            return fake_home.joinpath(*Path(str(path)).parts[1:])
        return original_expanduser(path)
    monkeypatch.setattr(Path, "expanduser", expanduser)
    legacy_target = Path("~/candidate")
    with publication_source_lease(legacy_target, legacy_target) as lease:
        assert lease.path == target / ".import.lock"
