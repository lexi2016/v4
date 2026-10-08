"""R6: duplicate keys cannot change meaning across actual JSON input paths."""
import json
from pathlib import Path

import pytest

from test_recovery_continuation import _make_prepared, _resume, _set_state, setup_actual


@pytest.mark.parametrize("raw", [b'{"identity":0,"identity":1}', b'{"outer":{"identity":0,"identity":1}}'])
def test_read_json_rejects_duplicate_keys_at_any_depth(setup_actual, raw):
    harness, _ = setup_actual
    path = harness.root / "ambiguous.json"
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="DUPLICATE|JSON_INVALID"):
        harness.m._read_json(path, "SYNTHETIC_INPUT")


def test_signed_receipt_rejects_nested_duplicates_even_when_canonical_sha_matches(setup_actual):
    harness, _ = setup_actual
    m = harness.m
    raw = m._receipt_bytes({"before": {"identity": "recorded"}})
    ambiguous = raw.replace(b'"before": {', b'"before": {"identity":"unreviewed",', 1)
    path = harness.root / "ambiguous-receipt.json"
    path.write_bytes(ambiguous)
    with pytest.raises(ValueError, match="DUPLICATE|JSON_INVALID"):
        m._signed_receipt(path, "SYNTHETIC_RECEIPT")


def test_prepared_nested_duplicate_is_rejected_even_with_new_raw_sha_reference(setup_actual, monkeypatch):
    harness, fixture = setup_actual
    m = harness.m
    receipt_path = _make_prepared(harness, fixture, monkeypatch)
    token = _set_state(harness, fixture, "candidate", "unloaded")
    receipt = json.loads(receipt_path.read_text())
    prepared_path = Path(receipt["prepared_receipt"]["path"])
    raw = prepared_path.read_bytes()
    ambiguous = raw.replace(b'"base": {', b'"base": {"api_plist_sha256":"unreviewed",', 1)
    assert ambiguous != raw
    prepared_path.chmod(0o600)
    prepared_path.write_bytes(ambiguous)
    receipt["prepared_receipt"]["sha256"] = m._sha(ambiguous)
    m._write_receipt(receipt_path, receipt)
    current = m.ACTIVE_API_PLIST.read_bytes()
    with pytest.raises(ValueError, match="DUPLICATE|JSON_INVALID"):
        _resume(harness, fixture, receipt_path, token)
    assert m.ACTIVE_API_PLIST.read_bytes() == current
    assert fixture["runtime"]["actions"] == []


def test_stage_plan_input_cannot_normalize_away_duplicate_guard_values(setup_actual):
    harness, fixture = setup_actual
    m = harness.m
    original = m.PLAN_PATH.read_bytes()
    ambiguous = b'{"before":{},' + original[1:]
    m.PLAN_PATH.write_bytes(ambiguous)
    with pytest.raises(ValueError, match="DUPLICATE|JSON_INVALID"):
        m._stage_api_plist(fixture["plan"])
    assert m.PLAN_PATH.read_bytes() == ambiguous
    assert m.ACTIVE_API_PLIST.read_bytes() == fixture["original"]


def test_disabled_binding_rejects_duplicates_despite_pinned_raw_sha(setup_actual):
    harness, fixture = setup_actual
    m = harness.m
    original = m.DISABLED_BINDING_PATH.read_bytes()
    ambiguous = b'{"enabled":true,' + original[1:]
    m.DISABLED_BINDING_PATH.write_bytes(ambiguous)
    fixture["plan"]["guards"]["disabled_binding_sha256"] = m._sha(ambiguous)
    with pytest.raises(ValueError, match="DUPLICATE|JSON_INVALID"):
        m._load_disabled_binding(fixture["plan"])


def test_openapi_json_uses_same_duplicate_rejection(setup_actual, monkeypatch):
    harness, _ = setup_actual
    m = harness.m
    original = json.dumps({"paths": {m.MANAGER_WORKSPACE_ROUTE: {"get": {}}}}).encode()
    ambiguous = b'{"paths":{},' + original[1:]
    monkeypatch.setattr(m, "_http_get", lambda path: (200, ambiguous))
    with pytest.raises(ValueError, match="DUPLICATE|JSON_INVALID"):
        m._verify_openapi(require_manager_route=True)


def test_nonstandard_nan_constant_is_rejected_like_core_json(setup_actual):
    harness, _ = setup_actual
    path = harness.root / "nan.json"
    path.write_bytes(b'{"identity":NaN}')
    with pytest.raises(ValueError, match="JSON_CONSTANT_INVALID|JSON_INVALID"):
        harness.m._read_json(path, "SYNTHETIC_INPUT")


def test_raw_json_member_stripping_keeps_order_but_rejects_nested_ambiguity(setup_actual):
    harness, _ = setup_actual
    m = harness.m
    assert m._strip_top_level_json_member(
        b'{"b":2,"consumption_validation":{"x":1},"a":1}', "consumption_validation"
    ) == (b'{"b":2,"a":1}', 1)
    with pytest.raises(ValueError, match="DUPLICATE|JSON_INVALID"):
        m._strip_top_level_json_member(
            b'{"kept":{"k":1,"k":2},"consumption_validation":{}}', "consumption_validation")
