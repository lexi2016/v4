"""Synthetic stage/identity/resource checks; no real bars, events or fits."""
import copy
import json

import pytest

import long_data194 as data
import long_training_adapter as adapter


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True))
    return {"path": str(path), "sha256": adapter.sha256_file(path)}


def test_input_stage_source_review_cannot_authorize_fit(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "HISTORY_EVIDENCE_ROOT", tmp_path)
    abi = _write(tmp_path / "abi.json", {"consumer_abi": "ORIGINAL_TDX_RAW_TARGET_D"})
    receipt = {"status": "SOURCE_BOUND_REVIEW_ONLY", "review_scope": "RAW_EVENT_SCHEMA_CODE_BINDING_ONLY",
               "formula_or_label_values_verified": False, "fit_allowed": False,
               "maximum_claim": "DIRECTION_ONLY", "qfq_manifest": abi,
               "v194_input_abi_verified": True, "consumer_abi": "ORIGINAL_TDX_RAW_TARGET_D"}
    config = {"build_dir": str(tmp_path / "inputs/new"), "history_binding": {
        "schema": "V194_FULL_HISTORY_INPUT_BINDING_V1", "target_date_cap": adapter.HISTORY_TARGET_CAP,
        "exposed_targets_excluded": sorted(adapter.HISTORY_EXPOSED_TARGETS), "qfq_manifest": abi,
        "input_review": _write(tmp_path / "review.json", receipt)}}
    assert adapter.verify_history_input_binding(config, purpose="input_build")["review"]["fit_allowed"] is False
    with pytest.raises(ValueError, match="CURRENT_HISTORY_INPUT_REVIEW_NOT_PASS"):
        adapter.verify_history_input_binding(config)
    receipt.update(status="PASS_RECONSTRUCTED_FULL_HISTORY_INPUT", raw_event_target_d_label_parity=False)
    config["history_binding"]["input_review"] = _write(tmp_path / "review.json", receipt)
    with pytest.raises(ValueError, match="TARGET_D_RAW_EVENT_LABEL_PARITY_UNVERIFIED"):
        adapter.verify_history_input_binding(config)
    receipt["raw_event_target_d_label_parity"] = True
    config["history_binding"]["input_review"] = _write(tmp_path / "review.json", receipt)
    adapter.verify_history_input_binding(config)
    assert not (tmp_path / "inputs").exists()


def test_input_stage_continuity_overlay_exact_identity_and_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "EVIDENCE_ROOT", tmp_path)
    statuses = {code: {"code": code, "status": "CANNOT_CONFIRM", "reason": "OLD_RAW_CONTINUITY_FAILURE",
                       "event_response_path": f"/original/{code}.json", "event_response_sha256": "a" * 64}
                for code in ("301139.SZ", "603007.SH")}
    statuses["000001.SZ"] = {"status": "READY"}
    rows = []
    for code in ("301139.SZ", "603007.SH"):
        base = tmp_path / "raw" / code
        gap = _write(base / "SOURCE_COVERAGE_GAPS.json", [])
        cp = {"code": code, "first_date": 20220708, "last_date": 20261019 if code == "301139.SZ" else 20261023,
              "rows": 1018, "files": {"SOURCE_COVERAGE_GAPS.json": gap["sha256"]},
              "source_receipts": [{"invalid_ohlc_rows": 0}]}
        rows.append({"code": code, "original_status_sha256": data.canonical_sha(statuses[code]),
                     "event_response_path": statuses[code]["event_response_path"],
                     "event_response_sha256": statuses[code]["event_response_sha256"],
                     "raw_checkpoint": _write(base / "STOCK_CHECKPOINT.json", cp),
                     **{key: cp[key] for key in ("first_date", "last_date", "rows")}})
    raw = {"path": "/new/raw.parquet", "sha256": "b" * 64}
    overlay = {"raw_artifact": raw, "rows": rows}
    ref = _write(tmp_path / "overlay.json", overlay)
    binding = {"review": {"continuity_overlay": ref}, "qfq_manifest": {"raw_artifact": raw}}
    revised = data._apply_continuity_overlay(statuses, binding, ref)
    assert revised["301139.SZ"]["prior_source_status"] == statuses["301139.SZ"]
    assert revised["301139.SZ"]["continuity_revalidation"]["last_date"] == 20261019
    assert revised["000001.SZ"] == statuses["000001.SZ"]
    assert statuses["301139.SZ"]["status"] == "CANNOT_CONFIRM"
    for mutate, error in (
        (lambda x: x["rows"][0].update(event_response_sha256="c" * 64), "CONTINUITY_EVENT_BINDING_DRIFT"),
        (lambda x: x["rows"][0].update(code="000001.SZ"), "CONTINUITY_OVERLAY_CODE_SCOPE_DRIFT"),
        (lambda x: x["raw_artifact"].update(sha256="d" * 64), "CONTINUITY_RAW_BINDING_DRIFT"),
    ):
        changed = copy.deepcopy(overlay)
        mutate(changed)
        ref = _write(tmp_path / "overlay.json", changed)
        binding["review"]["continuity_overlay"] = ref
        with pytest.raises(ValueError, match=error):
            data._apply_continuity_overlay(statuses, binding, ref)
    ref = _write(tmp_path / "overlay.json", overlay)
    binding["review"]["continuity_overlay"] = ref
    (tmp_path / "raw/301139.SZ/STOCK_CHECKPOINT.json").write_text("{}")
    with pytest.raises(ValueError, match="CONTINUITY_RAW_CHECKPOINT_SHA_DRIFT"):
        data._apply_continuity_overlay(statuses, binding, ref)


def test_input_stage_resource_selection_uses_formula_peak_and_pending_units():
    budget = {"requested_workers": 12, "threads_per_process": 1, "total_thread_budget": 12,
              "memory_safety_fraction": 0.5}
    plan = data._select_projection_workers(budget, 8, 1024, 24 * 1024)
    assert plan["requested_workers"] == 12 and plan["actual_workers"] == 8
    assert data._select_projection_workers(budget, 3, 1024, 24 * 1024)["actual_workers"] == 3
    assert data._select_projection_workers(budget, 8, 4 * 1024, 24 * 1024)["actual_workers"] == 3
    assert plan["profile_scope"] == "FORMULA_INPUT_PROJECTION_NOT_MODEL_FIT"
    with pytest.raises(ValueError, match="UNMEASURABLE"):
        data._select_projection_workers(budget, 8, 1024, None)
    with pytest.raises(ValueError, match="MEMORY_SAFETY_HEADROOM"):
        data._select_projection_workers(budget, 8, 13 * 1024, 24 * 1024)


def test_continuity_overlay_rejects_empty_source_receipts(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "EVIDENCE_ROOT", tmp_path)
    statuses = {code: {"code": code, "status": "CANNOT_CONFIRM", "reason": "OLD_RAW_CONTINUITY_FAILURE",
                       "event_response_path": f"/original/{code}.json", "event_response_sha256": "a" * 64}
                for code in ("301139.SZ", "603007.SH")}
    rows = []
    checkpoints = {}
    for code in statuses:
        base = tmp_path / code
        gap = _write(base / "SOURCE_COVERAGE_GAPS.json", [])
        cp = {"code": code, "first_date": 20220708, "last_date": 20261019, "rows": 1018,
              "files": {"SOURCE_COVERAGE_GAPS.json": gap["sha256"]},
              "source_receipts": [{"invalid_ohlc_rows": 0}]}
        checkpoints[code] = cp
        rows.append({"code": code, "original_status_sha256": data.canonical_sha(statuses[code]),
                     "event_response_path": statuses[code]["event_response_path"],
                     "event_response_sha256": statuses[code]["event_response_sha256"],
                     "raw_checkpoint": _write(base / "STOCK_CHECKPOINT.json", cp),
                     **{key: cp[key] for key in ("first_date", "last_date", "rows")}})
    raw = {"path": "/new/raw.parquet", "sha256": "b" * 64}
    # Every non-receipt shape must fail after the earlier identity/gap checks.
    for kind, receipts in (("empty", []), ("missing", None), ("null", None),
                           ("mapping", {}), ("string", "receipt"), ("invalid_item", [None])):
        cp = dict(checkpoints["301139.SZ"])
        if kind == "missing":
            cp.pop("source_receipts")
        else:
            cp["source_receipts"] = receipts
        rows[0]["raw_checkpoint"] = _write(tmp_path / "301139.SZ/STOCK_CHECKPOINT.json", cp)
        ref = _write(tmp_path / "overlay.json", {"raw_artifact": raw, "rows": rows})
        binding = {"review": {"continuity_overlay": ref}, "qfq_manifest": {"raw_artifact": raw}}
        with pytest.raises(ValueError, match="CONTINUITY_SOURCE_RECEIPTS_INVALID:301139.SZ"):
            data._apply_continuity_overlay(statuses, binding, ref)
        assert statuses["301139.SZ"]["status"] == "CANNOT_CONFIRM"


def test_continuity_artifact_identity_ignores_review_scope_but_rejects_drift(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "EVIDENCE_ROOT", tmp_path)
    statuses = {code: {"code": code, "status": "CANNOT_CONFIRM", "reason": "OLD_RAW_CONTINUITY_FAILURE",
                       "event_response_path": f"/original/{code}.json", "event_response_sha256": "a" * 64}
                for code in ("301139.SZ", "603007.SH")}
    rows = []
    for code in statuses:
        base = tmp_path / code
        gap = _write(base / "SOURCE_COVERAGE_GAPS.json", [])
        cp = {"code": code, "first_date": 20220708, "last_date": 20261019, "rows": 1018,
              "files": {"SOURCE_COVERAGE_GAPS.json": gap["sha256"]},
              "source_receipts": [{"invalid_ohlc_rows": 0}]}
        rows.append({"code": code, "original_status_sha256": data.canonical_sha(statuses[code]),
                     "event_response_path": statuses[code]["event_response_path"],
                     "event_response_sha256": statuses[code]["event_response_sha256"],
                     "raw_checkpoint": _write(base / "STOCK_CHECKPOINT.json", cp),
                     **{key: cp[key] for key in ("first_date", "last_date", "rows")}})
    expected = {"path": "/new/raw.parquet", "sha256": "b" * 64, "rows": 17001820,
                "stocks": ["ALL_5533"], "content_hash_policy": "PRODUCER_RESULT"}
    observed = {"path": expected["path"], "sha256": expected["sha256"], "rows": 17001820,
                "stocks": ["301139.SZ", "603007.SH"], "content_hash_policy": "TWO_CODE_REVIEW",
                "scope": "CONTINUITY_ONLY"}
    def apply(left, right):
        ref = _write(tmp_path / "overlay.json", {"raw_artifact": left, "rows": rows})
        return data._apply_continuity_overlay(statuses,
            {"review": {"continuity_overlay": ref}, "qfq_manifest": {"raw_artifact": right}}, ref)
    assert apply(observed, expected)["301139.SZ"]["prior_source_status"] == statuses["301139.SZ"]
    without_optional_count = dict(observed)
    without_optional_count.pop("rows")
    apply(without_optional_count, expected)
    for field in ("path", "sha256"):
        for value in (None, "", " ", "/different" if field == "path" else "c" * 64):
            for side in (0, 1):
                pair = [dict(observed), dict(expected)]
                pair[side][field] = value
                with pytest.raises(ValueError, match="CONTINUITY_RAW_BINDING_DRIFT"):
                    apply(*pair)
        for side in (0, 1):
            pair = [dict(observed), dict(expected)]
            pair[side].pop(field)
            with pytest.raises(ValueError, match="CONTINUITY_RAW_BINDING_DRIFT"):
                apply(*pair)
    for value in (17001819, "17001820", None, True):
        changed = {**observed, "rows": value}
        with pytest.raises(ValueError, match="CONTINUITY_RAW_BINDING_DRIFT"):
            apply(changed, expected)
