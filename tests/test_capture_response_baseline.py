from __future__ import annotations

import json
from pathlib import Path

from ops.capture_response_baseline import _drop_path, _normalize


def test_drop_path_removes_only_the_exact_leaf():
    value = {"a": {"b": 1, "c": 2}, "b": 3}
    _drop_path(value, "a.b")
    assert value == {"a": {"c": 2}, "b": 3}


def test_drop_path_ignores_missing_paths():
    value = {"a": {"c": 2}}
    _drop_path(value, "a.missing.deep")
    assert value == {"a": {"c": 2}}


def test_drop_path_descends_every_list_element():
    value = {"groups": {"logical": [
        {"next_due": "11:00", "name": "a"},
        {"next_due": "12:00", "name": "b"},
    ]}}
    _drop_path(value, "groups.logical[].next_due")
    assert value == {"groups": {"logical": [{"name": "a"}, {"name": "b"}]}}


def test_drop_path_handles_explicit_index():
    value = {"items": [{"x": 1}, {"x": 2}]}
    _drop_path(value, "items.1.x")
    assert value == {"items": [{"x": 1}, {}]}


def test_normalize_does_not_mutate_the_source():
    original = {"a": {"b": 1}}
    normalized = _normalize(original, ["a.b"])
    assert normalized == {"a": {}}
    assert original == {"a": {"b": 1}}


def test_normalize_keeps_unlisted_paths():
    original = {"monitor": {"last_success_at": "x", "status": "ok"}}
    normalized = _normalize(original, ["monitor.last_success_at"])
    assert normalized == {"monitor": {"status": "ok"}}


def test_ignore_spec_lists_exact_paths_with_reasons():
    spec = json.loads(Path("ops/baseline_ignore.json").read_text(encoding="utf-8"))
    paths = spec["paths"]
    assert paths, "ignore spec must not be empty"
    for entry in paths:
        assert set(entry) == {"path", "reason"}, entry
        assert entry["path"] and entry["reason"], entry
        assert "*" not in entry["path"], "ignore paths must be exact, not wildcards"
