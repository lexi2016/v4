"""Only isolated packaging, exact overlays and preservation guards."""
import ast
from pathlib import Path
import shutil

import pytest

from ops.prepare_tech_debt_candidate import (
    CACHE_IGNORE, PRESERVED_MODULES, assert_delta, assert_no_cache,
    exact_overlay, pool_overlay,
)
from ops import prepare_tech_debt_candidate as prepare


def test_exact_overlay_preserves_runtime_only_bytes_and_rejects_conflicts():
    old = b"one\ntwo\nthree\nfour\nfive\nsix\nseven\neight\nnine\nten\n"
    new = old.replace(b"two\n", b"fixed two\n")
    inherited = old + b"optional runtime imports and recovery\n"
    assert exact_overlay(old, new, inherited) == new + b"optional runtime imports and recovery\n"
    with pytest.raises(ValueError, match="INCOMPATIBLE"):
        exact_overlay(old, new, old.replace(b"three\n", b"conflict\n"))
    with pytest.raises(ValueError, match="AMBIGUOUS"):
        exact_overlay(old, new, old + old)


def test_copy_excludes_all_python_bytecode_but_keeps_source(tmp_path):
    source = tmp_path / "source"
    (source / "nested/__pycache__").mkdir(parents=True)
    (source / "nested/__pycache__/cached.cpython-314.pyc").write_bytes(b"cache")
    (source / "nested/stale.pyc").write_bytes(b"cache")
    (source / "nested/stale.pyo").write_bytes(b"cache")
    (source / "nested/code.py").write_text("# source\n")
    target = tmp_path / "copy"
    shutil.copytree(source, target, ignore=CACHE_IGNORE)
    assert_no_cache(target)
    assert (target / "nested/code.py").read_text() == "# source\n"
    (target / "stale.pyc").write_bytes(b"cache")
    with pytest.raises(ValueError, match="CONTAINS_CACHE"):
        assert_no_cache(target)


def test_delta_guard_rejects_deletions_and_frontend_changes():
    base = [{"path": name, "kind": "file", "sha256": "a" * 64} for name in PRESERVED_MODULES]
    assert assert_delta(base, base) == []
    with pytest.raises(ValueError, match="DELETES"):
        assert_delta(base, base[:-1])
    with pytest.raises(ValueError, match="NON_ALLOWLIST"):
        assert_delta(base, base + [{"path": "apps/web/dist/index.html", "kind": "file", "sha256": "b" * 64}])
    changed = [dict(row) for row in base]
    changed[-1]["sha256"] = "b" * 64
    with pytest.raises(ValueError, match="NON_ALLOWLIST"):
        assert_delta(base, changed)


def test_pool_overlay_keeps_inherited_signature_and_scope_protocol():
    reviewed = (Path(__file__).resolve().parents[1] / "domains/_preselection_parts/pool_assembly.py").read_bytes()
    inherited = b'''"""inherited"""
from __future__ import annotations
from ._namespace import read_global as _v4_global

def _preselection_body(_v4_scope, /, store, date, limit, *, offset, allow_legacy_flat):
    payload = store.read_payload(date)
    rows = payload["rows"]
    if not rows:
        return _v4_global(_v4_scope, '_blocked')(date, "empty")
    response = payload
    return response

def __dedupe_by_symbol_body(_v4_scope, /, rows):
    return _v4_global(_v4_scope, 'list')(rows)
'''
    result = pool_overlay(inherited, reviewed).decode()
    ast.parse(result)
    assert "def _preselection_body(_v4_scope, /, store, date, limit, *, offset, allow_legacy_flat):" in result
    assert "_v4_global(_v4_scope, '_project_independent_pools')(filtered_pools, date)" in result
    assert "return summarize_pool_quarantine(response)" in result
    assert "def _all_rows_quarantined(date, quarantine)" in result
    assert "return _v4_global(_v4_scope, 'list')(rows)" in result


@pytest.fixture
def frozen_business_source(tmp_path, monkeypatch):
    evidence = "apps/api/v4_api/evidence/manifest.json"
    frozen = {name: ("reviewed:" + name).encode() for name in prepare.ENTITY_PATHS + prepare.TECH_PATHS + (evidence,)}
    for name, raw in frozen.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    history = {"head": "f" * 40, "merge_base": prepare.SOURCE_COMMIT,
               "paths": "ops/prepare_tech_debt_candidate.py\ntests/test_prepare_tech_debt_candidate.py\n"}

    def git(argv, *, cwd):
        assert cwd == tmp_path and argv[0] == "git"
        if argv[1] == "rev-parse":
            return (history["head"] + "\n").encode()
        if argv[1] == "merge-base":
            return (history["merge_base"] + "\n").encode()
        if argv[1] == "log":
            return history["paths"].encode()
        if argv[1] == "ls-tree":
            return (evidence + "\0").encode()
        if argv[1] == "show":
            return frozen[argv[2].split(":", 1)[1]]
        raise AssertionError(argv)

    monkeypatch.setattr(prepare.subprocess, "check_output", git)
    return tmp_path, history, frozen


def test_source_identity_accepts_packaging_only_descendant(frozen_business_source):
    source, history, frozen = frozen_business_source
    identity = prepare.validate_source_identity(source)
    assert identity["business_source_commit"] == prepare.SOURCE_COMMIT
    assert identity["packaging_source_commit"] == history["head"] != prepare.SOURCE_COMMIT
    assert identity["reviewed_source_sha256"] == {name: prepare.sha(raw) for name, raw in frozen.items()}


def test_source_identity_rejects_business_commit_even_with_restored_bytes(frozen_business_source):
    source, history, _ = frozen_business_source
    history["paths"] += "domains/research.py\n"
    with pytest.raises(ValueError, match="NON_PACKAGING_COMMITTED_PATHS"):
        prepare.validate_source_identity(source)


@pytest.mark.parametrize("relative", ["domains/research.py", "apps/api/v4_api/evidence/manifest.json"])
def test_source_identity_rejects_working_tree_business_byte_drift(frozen_business_source, relative):
    source, _, _ = frozen_business_source
    (source / relative).write_bytes(b"uncommitted or staged business change")
    with pytest.raises(ValueError, match="REVIEWED_SOURCE_BYTES_DRIFT"):
        prepare.validate_source_identity(source)


def test_source_identity_rejects_untracked_evidence_input(frozen_business_source):
    source, _, _ = frozen_business_source
    (source / "apps/api/v4_api/evidence/unreviewed.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="REVIEWED_EVIDENCE_FILE_SET_DRIFT"):
        prepare.validate_source_identity(source)


def test_source_identity_rejects_unrelated_head(frozen_business_source):
    source, history, _ = frozen_business_source
    history["merge_base"] = "b" * 40
    with pytest.raises(ValueError, match="SOURCE_COMMIT_NOT_ANCESTOR"):
        prepare.validate_source_identity(source)
