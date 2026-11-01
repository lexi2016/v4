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
