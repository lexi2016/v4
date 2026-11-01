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


# --- the three gaps reproduced in review -------------------------------------

import pytest

from ops.capture_response_baseline import BaselineError, _assert_read_only, compare
from ops import capture_response_baseline as baseline_tool

READ_ONLY_FLAGS = ("write_performed", "production_allowed", "buy_gate_updated", "orders_sent")


@pytest.mark.parametrize("flag", READ_ONLY_FLAGS)
def test_any_true_read_only_flag_refuses_capture(flag):
    with pytest.raises(BaselineError, match=flag):
        _assert_read_only("date_list", {flag: True})


def test_a_flat_healthy_response_is_accepted():
    _assert_read_only("healthz", {"status": "ok"})
    _assert_read_only("date_list", {flag: False for flag in READ_ONLY_FLAGS})


def _sample(sample_id="date_list", path="/api/v1/runs/date-list", params=None, digest="sha-a", error=None):
    if error:
        return {"id": sample_id, "path": path, "params": params or {}, "status": None,
                "content_type": "", "error": error}
    return {"id": sample_id, "path": path, "params": params or {}, "status": 200,
            "content_type": "application/json", "body_sha256": digest}


def _write_baseline(tmp_path: Path, samples=None, frozen=None, ignored=None) -> Path:
    payload = {
        "schema_version": "v4.response_baseline.v1",
        "ignored_paths": ignored if ignored is not None else ["a.b"],
        "frozen": frozen if frozen is not None else {
            "system_date": "20261101", "date_catalog_sha256": "cat-1",
            "selection_latest_sha256": "sel-1", "captured_at": "t0"},
        "samples": samples if samples is not None else [_sample()],
    }
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _candidate(samples=None, frozen=None, ignored=None) -> dict:
    return {
        "ignored_paths": ignored if ignored is not None else ["a.b"],
        "frozen": frozen if frozen is not None else {
            "system_date": "20261101", "date_catalog_sha256": "cat-1",
            "selection_latest_sha256": "sel-1", "captured_at": "t1"},
        "samples": samples if samples is not None else [_sample()],
    }


def test_identical_capture_reports_no_problem(tmp_path):
    assert compare(_write_baseline(tmp_path), _candidate()) == []


def test_changed_request_path_is_not_comparable(tmp_path):
    problems = compare(_write_baseline(tmp_path), _candidate(samples=[_sample(path="/api/v1/other")]))
    assert any(p.startswith("NOT_COMPARABLE") and "request changed" in p for p in problems)


def test_changed_request_params_are_not_comparable(tmp_path):
    problems = compare(_write_baseline(tmp_path),
                       _candidate(samples=[_sample(params={"date": "20261030"})]))
    assert any(p.startswith("NOT_COMPARABLE") for p in problems)


def test_changed_data_generation_is_not_comparable(tmp_path):
    frozen = {"system_date": "20261101", "date_catalog_sha256": "cat-2",
              "selection_latest_sha256": "sel-1", "captured_at": "t1"}
    problems = compare(_write_baseline(tmp_path), _candidate(frozen=frozen))
    assert any("NOT_COMPARABLE frozen.date_catalog_sha256" in p for p in problems)


def test_missing_data_generation_is_not_comparable(tmp_path):
    problems = compare(_write_baseline(tmp_path),
                       _candidate(frozen={"system_date": "20261101", "captured_at": "t1"}))
    assert any("NOT_COMPARABLE frozen.selection_latest_sha256" in p for p in problems)


def test_changed_ignore_rules_are_not_comparable(tmp_path):
    problems = compare(_write_baseline(tmp_path), _candidate(ignored=["a.b", "c.d"]))
    assert any("ignored_paths" in p for p in problems)


def test_two_failing_captures_are_not_a_pass(tmp_path):
    problems = compare(_write_baseline(tmp_path), _candidate(samples=[_sample(error="URLError")]))
    assert problems
    assert any(p.startswith("NOT_VERIFIED") for p in problems)


def test_one_sided_failure_is_flagged(tmp_path):
    problems = compare(_write_baseline(tmp_path, samples=[_sample(error="URLError")]), _candidate())
    assert any(p.startswith("NOT_VERIFIED") for p in problems)


def test_body_change_on_a_matching_request_is_still_caught(tmp_path):
    problems = compare(_write_baseline(tmp_path), _candidate(samples=[_sample(digest="sha-b")]))
    assert any("normalized body changed" in p for p in problems)


@pytest.fixture
def missing_native_catalog(tmp_path, monkeypatch):
    for name in baseline_tool.ROOT_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    native, source = tmp_path / "native", tmp_path / "source"
    native.mkdir()
    source.mkdir()
    (native / "manifest.json").write_text('{"native":1}')
    (source / "manifest.json").write_text('{"source":1}')
    (source / "date_catalog.json").write_text('{"system_date":"20261101"}')
    monkeypatch.setenv("V4_DATA_ROOT", str(native))
    monkeypatch.setenv("V4_PRESELECTION_SOURCE_ROOT", str(source))
    return native, source


def test_missing_native_catalog_has_a_typed_input_generation(missing_native_catalog):
    native, source = missing_native_catalog
    left = baseline_tool._frozen_context("unused", {"system_date": "20261101"})
    right = baseline_tool._frozen_context("unused", {"system_date": "20261101"})
    descriptor = left["date_catalog_input_generation"]
    assert descriptor["schema_version"] == baseline_tool.CATALOG_GENERATION_SCHEMA
    assert descriptor["native_catalog"] == {"state": "MISSING", "file_sha256": None}
    assert descriptor["native_fallback_system_date"] == "20261101"
    assert descriptor["explicit_preselection_catalog"]["state"] == "PRESENT"
    assert left["date_catalog_hash_kind"] == baseline_tool.CATALOG_HASH_KIND
    assert left["date_catalog_sha256"] == right["date_catalog_sha256"] == baseline_tool._digest(descriptor)
    assert left["native_date_catalog_file_sha256"] is None
    assert left["preselection_date_catalog_file_sha256"] == baseline_tool._file_sha256(source / "date_catalog.json")
    assert descriptor["root_manifests"]["V4_DATA_ROOT"]["file_sha256"] == baseline_tool._file_sha256(native / "manifest.json")
    assert not (native / "date_catalog.json").exists()


@pytest.mark.parametrize("change", ["fallback_date", "source_catalog", "native_manifest"])
def test_catalog_generation_changes_are_not_comparable(missing_native_catalog, change):
    native, source = missing_native_catalog
    before = baseline_tool._frozen_context("unused", {"system_date": "20261101"})
    if change == "source_catalog":
        (source / "date_catalog.json").write_text('{"system_date":"20261102"}')
    elif change == "native_manifest":
        (native / "manifest.json").write_text('{"native":2}')
    after = baseline_tool._frozen_context("unused", {"system_date": "20261102" if change == "fallback_date" else "20261101"})
    before["selection_latest_sha256"] = after["selection_latest_sha256"] = "same"
    problems = baseline_tool._compare_frozen({"frozen": before}, {"frozen": after})
    assert any("NOT_COMPARABLE frozen.date_catalog_sha256" in problem for problem in problems)


def test_persisted_native_catalog_keeps_its_actual_file_hash(missing_native_catalog):
    native, _ = missing_native_catalog
    path = native / "date_catalog.json"
    path.write_text('{"system_date":"20261030"}')
    context = baseline_tool._frozen_context("unused", {"system_date": "20261101"})
    assert context["native_date_catalog_file_sha256"] == baseline_tool._file_sha256(path)
    assert context["date_catalog_input_generation"]["native_fallback_system_date"] is None
    assert context["date_catalog_sha256"] != context["native_date_catalog_file_sha256"]


def test_read_lock_lifecycle_does_not_change_content_stamp(missing_native_catalog):
    from infrastructure.interprocess_lock import owned_interprocess_lock

    native, source = missing_native_catalog
    before = baseline_tool._root_stamp([native, source])
    with owned_interprocess_lock(native / ".import.lock", timeout_seconds=1, timeout_message="test"):
        assert baseline_tool._root_stamp([native, source]) == before
        temp = native / ("..import.lock." + "a" * 32 + ".tmp")
        temp.write_bytes(b"temporary lock owner")
        assert baseline_tool._root_stamp([native, source]) == before
        temp.unlink()
    assert baseline_tool._root_stamp([native, source]) == before


def test_content_stamp_detects_nested_changes_even_with_restored_mtime(missing_native_catalog):
    import os

    native, source = missing_native_catalog
    folder = native / "nested"
    folder.mkdir()
    path = folder / "payload.json"
    path.write_bytes(b"old")
    metadata = path.stat()
    before = baseline_tool._root_stamp([native, source])
    path.write_bytes(b"new")
    os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    assert baseline_tool._root_stamp([native, source]) != before


def test_lock_exclusion_does_not_hide_other_files(missing_native_catalog):
    native, _ = missing_native_catalog
    before = baseline_tool._root_stamp([native])
    (native / ".import.lock.backup").write_bytes(b"not an excluded lock")
    assert baseline_tool._root_stamp([native]) != before


@pytest.mark.parametrize("change", ["payload", "source_catalog", "fallback_date"])
def test_capture_rejects_real_changes(missing_native_catalog, tmp_path, monkeypatch, change):
    native, source = missing_native_catalog
    samples = tmp_path / "samples.json"
    samples.write_text(json.dumps({"samples": [{"id": "healthz", "path": "/healthz"}]}))
    date = "20261101"

    def get_json(base_url, path, params=None):
        nonlocal date
        if path == "/healthz":
            if change == "payload":
                (native / "new_payload.json").write_text("{}")
            elif change == "source_catalog":
                (source / "date_catalog.json").write_text('{"changed":true}')
            else:
                date = "20261102"
            return 200, "application/json", {"status": "ok"}
        return 200, "application/json", {"system_date": date}

    monkeypatch.setattr(baseline_tool, "_get_json", get_json)
    with pytest.raises(BaselineError, match="changed during capture"):
        baseline_tool.capture("unused", samples, [])


def test_capture_accepts_missing_native_catalog_and_normal_read_lock(missing_native_catalog, tmp_path, monkeypatch):
    from infrastructure.interprocess_lock import owned_interprocess_lock

    native, _ = missing_native_catalog
    samples = tmp_path / "samples.json"
    samples.write_text(json.dumps({"samples": [{"id": "healthz", "path": "/healthz"}]}))

    def get_json(base_url, path, params=None):
        with owned_interprocess_lock(native / ".import.lock", timeout_seconds=1, timeout_message="test"):
            return 200, "application/json", {"system_date": "20261101", "status": "ok"}

    monkeypatch.setattr(baseline_tool, "_get_json", get_json)
    captured = baseline_tool.capture("unused", samples, [])
    assert captured["frozen"]["date_catalog_input_generation"]["native_catalog"]["state"] == "MISSING"
    assert captured["samples"][0]["status"] == 200


def test_typed_catalog_digest_cannot_be_compared_as_a_file_hash(missing_native_catalog):
    context = baseline_tool._frozen_context("unused", {"system_date": "20261101"})
    old = {key: value for key, value in context.items() if key not in ("date_catalog_hash_kind", "date_catalog_input_generation")}
    assert any("date_catalog_hash_kind" in problem for problem in baseline_tool._compare_frozen({"frozen": old}, {"frozen": context}))


def test_unbound_native_root_cannot_prove_catalog_generation(missing_native_catalog, monkeypatch):
    monkeypatch.delenv("V4_DATA_ROOT")
    context = baseline_tool._frozen_context("unused", {"system_date": "20261101"})
    context["selection_latest_sha256"] = "same"
    assert any("catalog input descriptor invalid" in problem for problem in baseline_tool._compare_frozen({"frozen": context}, {"frozen": context}))
