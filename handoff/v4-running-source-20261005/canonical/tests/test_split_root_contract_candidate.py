from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import sys
import types

import pytest


def _load():
    # Load only the two leaf modules.  Importing the package __init__ also
    # loads unrelated manager service dependencies and obscures this contract.
    prefix = "v4.manager_research"
    saved = {key: sys.modules[key] for key in tuple(sys.modules) if key == prefix or key.startswith(prefix + ".")}
    for key in saved:
        del sys.modules[key]
    package = types.ModuleType(prefix)
    package.__path__ = [str(Path(__file__).resolve().parents[1] / "v4" / "manager_research")]
    package.__package__ = prefix
    sys.modules[prefix] = package
    try:
        ac = importlib.import_module(prefix + ".activation_canary")
        mr = importlib.import_module(prefix + ".materializer_replay")
    finally:
        for key in tuple(sys.modules):
            if key == prefix or key.startswith(prefix + "."):
                del sys.modules[key]
        sys.modules.update(saved)
    return ac, mr


def _populate(root: Path, rels):
    for index, rel in enumerate(rels):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"source-{index}-{rel}\n", encoding="utf-8")


def test_worker_and_replayed_writer_inventory_are_explicitly_separate():
    ac, _ = _load()
    worker = set(ac._MATERIALIZER_REPLAY_WORKER_FILES)
    runtime = set(ac._MATERIALIZER_RUNTIME_FILES)
    assert worker
    assert runtime
    assert worker.isdisjoint(runtime)
    assert tuple(ac._MATERIALIZER_APP_FILES) == tuple(ac._MATERIALIZER_REPLAY_WORKER_FILES) + tuple(ac._MATERIALIZER_RUNTIME_FILES)
    assert len(ac._MATERIALIZER_REPLAY_WORKER_FILES) == 3
    assert len(ac._MATERIALIZER_RUNTIME_FILES) == 27
    assert len(ac._MATERIALIZER_APP_FILES) == 30
    assert {
        "upstreams/v3_shared_data/shared_data/hk_auction_0920.py",
        "upstreams/v3_shared_data/shared_data/__init__.py",
        "upstreams/v3_shared_data/shared_data/allowlist.py",
        "upstreams/v3_shared_data/shared_data/collectors.py",
        "upstreams/v3_shared_data/shared_data/constants.py",
        "upstreams/v3_shared_data/shared_data/consumer.py",
        "upstreams/v3_shared_data/shared_data/hashing.py",
        "upstreams/v3_shared_data/shared_data/hk_0_2.py",
        "upstreams/v3_shared_data/shared_data/hk_security_master.py",
        "upstreams/v3_shared_data/shared_data/paths.py",
        "upstreams/v3_shared_data/shared_data/store.py",
        "apps/__init__.py",
        "apps/api/__init__.py",
        "apps/api/v35_api/__init__.py",
        "contracts/__init__.py",
        "infrastructure/__init__.py",
    } <= runtime


def test_writer_root_need_not_contain_replay_worker_files(tmp_path):
    ac, _ = _load()
    root = tmp_path.resolve() / "writer"
    root.mkdir()
    _populate(root, ac._MATERIALIZER_RUNTIME_FILES)

    inventory = ac._materializer_app_inventory(root, include_worker_files=False)
    assert set(inventory) == set(ac._MATERIALIZER_RUNTIME_FILES)
    assert all(len(v) == 64 for v in inventory.values())

    with pytest.raises(ValueError, match="MATERIALIZER_APP_SOURCE_MISSING"):
        ac._materializer_app_inventory(root)


def test_materializer_input_identity_requires_every_actual_runtime_source(tmp_path):
    ac, _ = _load()
    root = tmp_path.resolve() / "writer"
    root.mkdir()
    _populate(root, ac._MATERIALIZER_RUNTIME_FILES)
    sources = ac._materializer_app_inventory(root, include_worker_files=False)
    before = {
        "state_inputs": {},
        "universe_date_tree": {},
        "rebound_inputs": {},
        "news_inputs": {"files": {}},
        "materializer_app_sources": sources,
        "universe_owner_source_sha256": "a" * 64,
        "news_owner_source_sha256": "b" * 64,
        "materializer_source_sha256": "c" * 64,
    }
    payload = {
        "input_unchanged": True,
        "input_identity_before": before,
        "input_identity_after": before,
        "input_identity_sha256": hashlib.sha256(json.dumps(before, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
    }
    assert ac._materializer_input_identity_valid(payload) is True

    bad = json.loads(json.dumps(payload))
    bad_before = bad["input_identity_before"]
    bad_before["materializer_app_sources"].pop(ac._MATERIALIZER_RUNTIME_FILES[-1])
    bad["input_identity_after"] = bad_before
    bad["input_identity_sha256"] = hashlib.sha256(json.dumps(bad_before, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert ac._materializer_input_identity_valid(bad) is False

    dependency = "upstreams/v3_shared_data/shared_data/allowlist.py"
    stable_changed = json.loads(json.dumps(payload))
    stable_changed["input_identity_before"]["materializer_app_sources"][dependency] = "e" * 64
    stable_changed["input_identity_after"]["materializer_app_sources"][dependency] = "e" * 64
    stable_changed["input_identity_sha256"] = hashlib.sha256(json.dumps(
        stable_changed["input_identity_before"], sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    assert ac._materializer_input_identity_valid(stable_changed) is True

    changed_during_run = json.loads(json.dumps(stable_changed))
    changed_during_run["input_identity_after"]["materializer_app_sources"][dependency] = "f" * 64
    assert ac._materializer_input_identity_valid(changed_during_run) is False


def test_replay_input_identity_selects_runtime_only_writer_inventory():
    _, mr = _load()
    import inspect
    source = inspect.getsource(mr._input_identity)
    assert "include_worker_files=False" in source
