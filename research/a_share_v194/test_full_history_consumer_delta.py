"""Bounded consumer fixtures: no real panel, event body, label, or model fit."""
import json
from pathlib import Path

import pytest

import data194
import long_data194 as data
import long_run194 as runner
import long_training_adapter as adapter


def test_history_target_cap_and_exposed_dates():
    sessions = ["20261015", "20261016", "20261019", "20261020", "20261021", "20261022", "20261023"]
    pairs = data.calendar_pairs_from_receipt({"calendar_sessions": sessions})
    assert [target for _, target in pairs] == sessions[1:-1]
    calendar = [{"target_date": data.iso_day(day), "cohort_role": "eligible",
                 "technical_complete_rows": 1, "truth_rankable_research_rows": 1} for day in sessions]
    keys = [(row["target_date"], "000001.SZ") for row in calendar]
    rows, policy = data._finalize_date_policy(calendar, [{"target_date": day, "code": code} for day, code in keys], set(keys), data194)
    assert policy["eligible_target_dates"] == ["2026-10-15"]
    assert policy["diagnostic_target_dates"] == sorted(adapter.HISTORY_EXPOSED_TARGETS)
    assert rows[-1]["eligibility_exclusion_reason"] == "AFTER_FROZEN_TARGET_DATE_CAP"
    assert not rows[-1]["training_eligible"]


def test_history_early_rankable_exact_keys_and_min100():
    codes = ["000001.SZ", "000002.SZ", "600519.SH"]
    day = "2001-08-28"
    truth = [{"target_date": day, "code": code, "label": 1} for code in codes]
    calendar = [{"target_date": day, "truth_rankable_research_rows": 3, "truth_positive_denominator": 3,
                 "truth_rankable_code_keys_sha256": adapter.canonical_json_sha256(codes)}]
    kwargs = dict(oof_dates=[day], truth_rows=truth, raw_natural_rows=[{"target_date": day, "code": codes[0], "tech_192": 1}],
                  technical_rows=[{"target_date": day, "code": codes[0]}], v194_rows=[{"target_date": day, "code": codes[1]}],
                  calendar_rows=calendar, universe_codes=set(codes + ["600602.SH"]), fold_for_date={}, fold_source_audit={})
    daily, top, _ = runner._selection_comparison(**kwargs)
    assert len(top) == daily[0]["truth_positive_denominator"] == 3
    assert daily[0]["technical11_l2_selected"] == daily[0]["v194_selected"] == 1
    assert daily[0]["technical11_l2_vs_v194_new_hits"] == daily[0]["technical11_l2_vs_v194_lost_hits"] == 1
    changed = [dict(row) for row in truth]
    changed[-1]["code"] = "600602.SH"
    with pytest.raises(ValueError, match="MANIFEST_RANKABLE_KEYSET_DRIFT"):
        runner._selection_comparison(**{**kwargs, "truth_rows": changed})
    with pytest.raises(ValueError, match="RANKABLE_KEYSET_DRIFT"):
        runner._selection_comparison(**{**kwargs, "truth_rows": [truth[0], truth[0], truth[2]]})


def test_history_output_isolation_and_no_implicit_old_build(tmp_path, monkeypatch):
    root = tmp_path / "new"
    root.mkdir()
    monkeypatch.setattr(adapter, "HISTORY_EVIDENCE_ROOT", root)
    destination = root / "runs" / "fresh"
    assert adapter.history_output_path(destination) == destination
    old = tmp_path / "a_share_v194_long_history_20261024"
    old.mkdir()
    with pytest.raises(ValueError, match="OUTSIDE_NEW_EVIDENCE_ROOT"):
        adapter.history_output_path(old / "run")
    (root / "runs").mkdir()
    (root / "runs" / "escape").symlink_to(old, target_is_directory=True)
    with pytest.raises(ValueError, match="OUTSIDE_NEW_EVIDENCE_ROOT"):
        adapter.history_output_path(root / "runs/escape/run")
    monkeypatch.setattr(data, "BUILD_CONFIG", None)
    with pytest.raises(ValueError, match="EXPLICIT_NEW_HISTORY_BUILD_CONFIG_REQUIRED"):
        data.load_context(require_checkpoint=True)
    assert not destination.exists()
    assert list(old.iterdir()) == []


def test_history_current_review_and_qfq_binding_required(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "HISTORY_EVIDENCE_ROOT", tmp_path)
    config = {"output_dir": str(tmp_path / "runs/new"), "history_binding": {
        "schema": "V194_FULL_HISTORY_INPUT_BINDING_V1", "target_date_cap": "2026-10-22",
        "exposed_targets_excluded": sorted(adapter.HISTORY_EXPOSED_TARGETS), "qfq_manifest": None}}
    with pytest.raises(ValueError, match="QFQ_INPUT_BINDING_REQUIRED"):
        adapter.verify_history_input_binding(config)
    qfq = tmp_path / "qfq.json"
    qfq.write_text(json.dumps({"consumer_abi": "FIXTURE_EXPLICITLY_REVIEWED_ABI"}))
    qfq_ref = {"path": str(qfq), "sha256": adapter.sha256_file(qfq)}
    config["history_binding"]["qfq_manifest"] = qfq_ref
    review = tmp_path / "review.json"
    receipt = {"status": "PASS_INPUT_PASSPORT", "maximum_claim": "DIRECTION_ONLY", "qfq_manifest": qfq_ref,
               "v194_input_abi_verified": True, "consumer_abi": "FIXTURE_EXPLICITLY_REVIEWED_ABI",
               "raw_event_target_d_label_parity": True}
    def bind_review():
        review.write_text(json.dumps(receipt))
        config["history_binding"]["input_review"] = {"path": str(review), "sha256": adapter.sha256_file(review)}
    bind_review()
    with pytest.raises(ValueError, match="CURRENT_HISTORY_INPUT_REVIEW_NOT_PASS"):
        adapter.verify_history_input_binding(config)
    receipt["status"] = "PASS_RECONSTRUCTED_FULL_HISTORY_INPUT"
    bind_review()
    assert adapter.verify_history_input_binding(config)["review"]["maximum_claim"] == "DIRECTION_ONLY"
    receipt["raw_event_target_d_label_parity"] = False
    bind_review()
    with pytest.raises(ValueError, match="TARGET_D_RAW_EVENT_LABEL_PARITY_UNVERIFIED"):
        adapter.verify_history_input_binding(config)
    assert not (tmp_path / "runs").exists()
