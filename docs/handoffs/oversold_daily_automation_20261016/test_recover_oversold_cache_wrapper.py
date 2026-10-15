from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest


WRAPPER_PATH = Path(__file__).with_name("recover_oversold_cache_20261016.py")
SPEC = importlib.util.spec_from_file_location("recover_oversold_cache_20261016", WRAPPER_PATH)
WRAPPER = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(WRAPPER)


def test_inventory_helper_load_is_bound_to_exact_source_even_with_candidate_shadow(tmp_path, monkeypatch):
    candidate_app = tmp_path / "candidate" / "app"
    shadow = candidate_app / "ops" / "api_release_integration.py"
    shadow.parent.mkdir(parents=True)
    shadow.write_text("raise RuntimeError('candidate shadow must not load')\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(candidate_app))

    helper = WRAPPER._load_pinned_inventory_helper()
    expected = (WRAPPER.REPO_ROOT / "ops/api_release_integration.py").resolve(strict=True)

    assert Path(helper.__file__).resolve(strict=True) == expected
    assert hashlib.sha256(expected.read_bytes()).hexdigest() == WRAPPER.INVENTORY_HELPER_SHA256
    assert callable(helper.inventory_tree)
    assert callable(helper.inventory_digest)


def test_inventory_helper_refuses_changed_source_sha(tmp_path, monkeypatch):
    source = tmp_path / "ops" / "api_release_integration.py"
    source.parent.mkdir()
    source.write_text("def inventory_tree(_root): return []\n", encoding="utf-8")
    monkeypatch.setattr(WRAPPER, "REPO_ROOT", tmp_path)

    with pytest.raises(RuntimeError, match="CACHE_INVENTORY_HELPER_SHA_MISMATCH"):
        WRAPPER._load_pinned_inventory_helper()
