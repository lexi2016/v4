from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest
from pydantic import ValidationError

from v4.manager_workbench.contracts import (
    PlanSnapshot, _model_product_digest, canonical, product_digest, seal_snapshot,
)


def snapshot_data(selection=False):
    context = dict(target_date="20261030", phase="MANUAL", cutoff="2026-10-30T08:00:00+08:00",
                   trigger="MANUAL", rules_version="test", scope_refs={"汉字": [None, 0.25, True]})
    lane = dict(lane="US_MAPPING", state="READY", rows=[{"nested": {"a": [1, 2, 3]}, "name": "测试"}],
                coverage={}, input_sha256="a" * 64, rules_version="test", run_id="run-one")
    if selection:
        lane["selection"] = dict(policy_version="v1", policy_sha256="b" * 64, engine_identity="test",
            target_date="20261030", cutoff=context["cutoff"], candidates=[dict(symbol="HK.00700",
            research_state="pending", paths=[dict(path_id="p1", symbol="HK.00700")])])
    return dict(context=context, run_id="run-one", input_sha256="a" * 64,
        generated_at=context["cutoff"], available_at=context["cutoff"], lanes=[lane], stocks=[],
        counts={}, changes={"nested": [{"中文": "原始JSON", "value": -0.0}]})


@pytest.mark.parametrize("selection", [False, True])
def test_direct_model_digest_equals_original_complete_json_dump(selection):
    model = seal_snapshot(snapshot_data(selection))
    assert _model_product_digest(model) == product_digest(model.model_dump(mode="json")) == model.product_sha256
    reread = PlanSnapshot.model_validate_json(canonical(model.model_dump(mode="json")))
    assert reread.model_dump(mode="json") == model.model_dump(mode="json")
    if selection:
        changed = model.model_copy(deep=True)
        candidate = changed.lanes[0].selection.candidates[0]
        candidate.industry_matches = [{"industry": "科技"}]
        candidate.paths[0].quote_verified = True
        candidate.paths[0].quote_available_at = "2026-10-29T20:00:00+00:00"
        candidate.paths[0].focus_theme = "科技"
        changed.lanes[0].selection.listing_mode = "INDUSTRY_MATCH"
        changed.lanes[0].selection.listing_policy_version = "v2"
        changed.lanes[0].selection.listing_policy_sha256 = "c" * 64
        assert _model_product_digest(changed) == product_digest(changed.model_dump(mode="json"))


def test_json_normalization_of_python_values_remains_equivalent():
    model = seal_snapshot(snapshot_data())
    model.changes["timestamp"] = datetime(2026, 10, 30, tzinfo=timezone.utc)
    model.changes["tuple"] = (1, "二")
    assert _model_product_digest(model) == product_digest(model.model_dump(mode="json"))


@pytest.mark.parametrize("change,reason", [
    ("payload", "PRODUCT_SHA_MISMATCH"), ("run", "LANE_RUN_MISMATCH"),
    ("rules", "RULES_VERSION_MISMATCH"), ("count", "COUNTS_MISMATCH"),
])
def test_original_rejection_semantics_remain(change, reason):
    payload = seal_snapshot(snapshot_data()).model_dump(mode="json")
    if change == "payload":
        payload["lanes"][0]["rows"][0]["name"] = "被修改"
    elif change == "run":
        payload["lanes"][0]["run_id"] = "another-run"
    elif change == "rules":
        payload["lanes"][0]["rules_version"] = "another-rule"
    else:
        payload["counts"]["selected"] = 1
        payload["product_sha256"] = product_digest(payload)
    with pytest.raises(ValidationError, match=reason):
        PlanSnapshot.model_validate(deepcopy(payload))


@pytest.mark.parametrize("raw", [b"[]", b"null", b'"text"', b"42", b"{broken", b'{"bad":"\xff"}'])
def test_read_plan_keeps_original_decoder_and_root_errors(tmp_path, raw):
    from v4.manager_workbench.store import StorageUnavailable, WorkbenchStore

    store = WorkbenchStore(tmp_path)
    path = store.root / "snapshots/run-one.json"
    path.parent.mkdir()
    path.write_bytes(raw)
    try:
        original = json.loads(raw)
        if not isinstance(original, dict):
            raise StorageUnavailable("CORRUPT_RECORD")
        PlanSnapshot.model_validate(original)
    except Exception as original_error:
        with pytest.raises(type(original_error)) as updated_error:
            store.read_plan("run-one")
        assert str(updated_error.value) == str(original_error)
    else:
        pytest.fail("fixture must be rejected by the original reader")


def test_read_plan_retains_full_validation_and_compatible_encodings(tmp_path):
    from v4.manager_workbench.store import StorageConflict, WorkbenchStore

    store = WorkbenchStore(tmp_path)
    path = store.root / "snapshots/run-one.json"
    path.parent.mkdir()
    model = seal_snapshot(snapshot_data(True))
    payload = model.model_dump(mode="json")
    for prefix in (b"", b"\xef\xbb\xbf"):
        path.write_bytes(prefix + canonical(payload))
        assert store.read_plan("run-one").model_dump(mode="json") == payload
    payload["lanes"][0]["rows"][0]["name"] = "changed"
    path.write_bytes(canonical(payload))
    with pytest.raises(ValidationError, match="PRODUCT_SHA_MISMATCH"):
        store.read_plan("run-one")
    payload["run_id"] = payload["lanes"][0]["run_id"] = "different-run"
    payload["product_sha256"] = product_digest(payload)
    path.write_bytes(canonical(payload))
    with pytest.raises(StorageConflict, match="RUN_ID_MISMATCH"):
        store.read_plan("run-one")


def test_python_input_keeps_original_json_key_normalization():
    payload = seal_snapshot(snapshot_data()).model_dump(mode="json")
    payload["changes"] = {"keys": {10: "ten", 2: "two"}}
    normalized = deepcopy(payload)
    normalized["changes"] = {"keys": {"10": "ten", "2": "two"}}
    payload["product_sha256"] = product_digest(normalized)
    assert PlanSnapshot.model_validate(payload).product_sha256 == payload["product_sha256"]


@pytest.mark.parametrize("token", [b"NaN", b"Infinity", b"-Infinity"])
def test_read_plan_keeps_original_nonfinite_to_null_normalization(tmp_path, token):
    from v4.manager_workbench.store import WorkbenchStore

    payload = seal_snapshot(snapshot_data()).model_dump(mode="json")
    payload["changes"]["value"] = None
    payload["product_sha256"] = product_digest(payload)
    raw = canonical(payload).replace(b'"value":null', b'"value":' + token)
    assert raw != canonical(payload)
    original = PlanSnapshot.model_validate(json.loads(raw))
    store = WorkbenchStore(tmp_path)
    path = store.root / "snapshots/run-one.json"
    path.parent.mkdir()
    path.write_bytes(raw)
    updated = store.read_plan("run-one")
    assert updated.model_dump(mode="json") == original.model_dump(mode="json")
    assert updated.product_sha256 == payload["product_sha256"]
    invalid = raw.replace(payload["product_sha256"].encode(), b"0" * 64)
    path.write_bytes(invalid)
    with pytest.raises(ValidationError, match="PRODUCT_SHA_MISMATCH"):
        store.read_plan("run-one")
