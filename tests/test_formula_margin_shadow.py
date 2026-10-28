from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

import stage_center.formula_margin_shadow as shadow_module
from stage_center.formula_margin_shadow import (
    COMPARATOR_VERSION,
    ENGINEERING_FIXTURE,
    EXPERIMENT_ID,
    REAL_AUTHORITY,
    ShadowInvalid,
    TRUTH_SCOPE,
    append_labels,
    build_shadow,
    evaluate_run,
    evaluate_runs,
    freeze_snapshot,
    preflight_input,
    verify_frozen_artifacts,
    build_selector_capture_payload,
    capture_selector_snapshot,
    canonical_json,
    sha256_bytes,
    preflight_capture_input,
)
from stage_center.selection import select_hk_four_lane
import stage_center.selection as selection_module


def _metadata() -> dict:
    return {
        "experiment_id": EXPERIMENT_ID,
        "admission_mode": ENGINEERING_FIXTURE,
        "observation_mode": "FORWARD_NATURAL",
        "captured_at": "2026-09-21T09:35:05+08:00",
        "trade_date": "20260921",
        "stage": "STAGE_0930_0935",
        "cutoff_ts": "2026-09-21T09:35:05+08:00",
        "market": "HK_CONNECT",
        "source_version": "v4.hk.production.snapshot.v1",
        "input_sha256": "a" * 64,
        "rule_sha256": "b" * 64,
        "comparator_version": COMPARATOR_VERSION,
        "run_id": "hk-natural-20260921-093505",
        "formula_provenance": {
            "source_version": "hk-formula-state-v1",
            "input_sha256": "c" * 64,
            "rule_sha256": "d" * 64,
            "source_asof": "2026-09-20",
            "frozen_at": "2026-09-20T18:00:00+08:00",
        },
    }


def _rows() -> list[dict]:
    rows = []
    for rank in range(1, 16):
        rows.append(
            {
                "security_id": f"HK.C{rank:02d}",
                "eligible": True,
                "lane": ["LANE_MAIN", "LANE_THEME"],
                "stage_score": 92.0 - (rank - 1) * 0.2,
                "production_rank": rank,
                "candidate_bucket": "FOUR_LANE_OBSERVATION",
                "trade_status_contract": "WATCH_ONLY",
                "pct_chg": 3.0,
                "volume_ratio": 2.0,
                "f1_state": "N",
                "f2_state": "N",
                "f3_state": "N",
                "f4_state": "N",
                "stage_price": 10.0 + rank / 100,
                "price_ts": "2026-09-21T09:35:05+08:00",
                "currency": "HKD",
                "adjustment_mode": "RAW",
                "price_source": "V4_HK_STAGE_SNAPSHOT",
            }
        )
    rows[10]["f1_state"] = "H"  # C11 can enter the boundary.
    rows[11]["f2_state"] = "H"
    rows[12]["f3_state"] = "U"  # U is not a penalty and is not a bonus.
    rows[13]["f4_state"] = "H"
    return rows


def _payload() -> dict:
    return {**_metadata(), "rows": _rows()}


def _persistent_payload(tmp_path: Path, *, stage: str = "STAGE_0930_0935") -> dict:
    payload = _payload()
    rows = []
    for rank in range(1, 101):
        row = dict(payload["rows"][(rank - 1) % len(payload["rows"])])
        row["security_id"] = f"HK.C{rank:02d}"
        row["code"] = row["security_id"]
        row["production_rank"] = rank
        row["stage_score"] = 92.0 - (rank - 1) * 0.2
        row["stage_price"] = 10.0 + rank / 100
        rows.append(row)
    payload["rows"] = rows
    payload["stage"] = stage
    payload["cutoff_ts"] = f"2026-09-21T{ {'STAGE_0930_0935':'09:35:05','STAGE_0945_1030':'10:30:00','STAGE_1445_1500':'15:00:00'}[stage] }+08:00"
    payload["captured_at"] = payload["cutoff_ts"]
    payload["run_id"] = f"hk-natural-20260921-{stage}"

    source_path = tmp_path / f"source-{stage}.json"
    source_path.write_text(json.dumps({"rows": rows}, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    rule_path = tmp_path / f"rule-{stage}.txt"
    rule_path.write_text("formula-margin-shadow-rule-v1", encoding="utf-8")
    rule_sha = hashlib.sha256(rule_path.read_bytes()).hexdigest()
    formula_rows = [
        {
            "security_id": row["security_id"],
            "f1_state": row.get("f1_state", "N"),
            "f2_state": row.get("f2_state", "N"),
            "f3_state": row.get("f3_state", "N"),
            "f4_state": row.get("f4_state", "N"),
        }
        for row in rows
    ]
    formula_path = tmp_path / f"formula-{stage}.json"
    formula_path.write_text(json.dumps({"rows": formula_rows}, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    formula_sha = hashlib.sha256(formula_path.read_bytes()).hexdigest()
    formula_rule_path = tmp_path / f"formula-rule-{stage}.txt"
    formula_rule_path.write_text("verified-formula-rule-v1", encoding="utf-8")
    formula_rule_sha = hashlib.sha256(formula_rule_path.read_bytes()).hexdigest()
    d1_path = tmp_path / f"d1-{stage}.json"
    d1_path.write_text(json.dumps({"rows": rows}, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    d1_sha = hashlib.sha256(d1_path.read_bytes()).hexdigest()
    payload["input_sha256"] = source_sha
    payload["rule_sha256"] = rule_sha
    payload["source_artifact"] = {"path": str(source_path), "sha256": source_sha}
    payload["rule_artifact"] = {"path": str(rule_path), "sha256": rule_sha}
    payload["formula_provenance"] = {
        "source_version": "hk-formula-state-v1",
        "input_sha256": formula_sha,
        "rule_sha256": formula_rule_sha,
        "source_asof": "2026-09-20",
        "frozen_at": "2026-09-20T18:00:00+08:00",
        "artifact": {"path": str(formula_path), "sha256": formula_sha},
        "rule_artifact": {"path": str(formula_rule_path), "sha256": formula_rule_sha},
    }
    payload["d1_manifest"] = {
        "version": "hk-d1-manifest-v1",
        "manifest_sha256": d1_sha,
        "artifact": {"path": str(d1_path), "sha256": d1_sha},
    }
    payload["time_evidence"] = {"source": "test-selector", "captured_at": payload["captured_at"]}
    payload["raw_artifact_sha256"] = source_sha
    return payload


def _truth_universe_rows() -> list[dict]:
    top20 = [f"HK.C{i:02d}" for i in range(1, 10)] + [f"HK.C{i:02d}" for i in range(11, 22)]
    all_codes = [*top20, "HK.C10", *[f"HK.C{i:02d}" for i in range(22, 41)]]
    return [
        {
            "security_id": code,
            "close": 100.0 + (len(all_codes) - index) if code in top20 else 80.0 - index,
            "pre_close": 100.0,
        }
        for index, code in enumerate(all_codes)
    ]


def _labels(tmp_path: Path) -> dict:
    universe_rows = _truth_universe_rows()
    canonical_truth = [
        {
            "security_id": row["security_id"],
            "close_price": float(row["close"]),
            "pre_close_price": float(row["pre_close"]),
            "close_gain": float(row["close"]) / float(row["pre_close"]) - 1.0,
        }
        for row in universe_rows
    ]
    source_path = tmp_path / "truth-source.json"
    source_path.write_text(
        json.dumps({"truth_scope": TRUTH_SCOPE, "rows": universe_rows}, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    rank_by_code = {code: rank for rank, code in enumerate([row["security_id"] for row in sorted(canonical_truth, key=lambda row: (-row["close_gain"], row["security_id"]))[:20]], start=1)}
    top20 = list(rank_by_code)
    return {
        "schema_version": "v4.formula_margin_shadow.labels.v1",
        "experiment_id": EXPERIMENT_ID,
        "admission_mode": ENGINEERING_FIXTURE,
        "trade_date": "20260921",
        "truth_scope": TRUTH_SCOPE,
        "truth_universe_version": "hk-connect-members-20260921-v1",
        "truth_source_version": "hk-close-gain-source-v1",
        "truth_input_sha256": sha256_bytes(canonical_json(canonical_truth)),
        "truth_manifest_sha256": source_sha,
        "truth_source_artifact": {"path": str(source_path), "sha256": source_sha},
        "truth_complete": True,
        "truth_universe_count": len(universe_rows),
        "truth_coverage_ratio": 1.0,
        "truth_top20_codes": top20,
        "truth_tie_break": "gain_desc_then_security_id_asc",
        "gain_definition": "close/pre_close-1_raw",
        "labels_captured_at": "2026-09-21T16:10:00+08:00",
        "rows": [
            {
                "security_id": row["security_id"],
                "close_top20_rank": rank_by_code.get(row["security_id"]),
                "hit_top20": row["security_id"] in rank_by_code,
                "close_price": 11.0,
                "close_price_source": "HK_CONNECT_FULL_CLOSE_V1",
                "currency": "HKD",
                "adjustment_mode": "RAW",
            }
            for row in _rows()
        ],
    }


def test_real_comparator_baseline_and_margin_candidate_are_bounded() -> None:
    built = build_shadow(_payload())

    assert built["baseline"]["codes"] == [f"HK.C{i:02d}" for i in range(1, 11)]
    assert built["candidate"]["codes"] == [
        *[f"HK.C{i:02d}" for i in range(1, 9)],
        "HK.C11",
        "HK.C09",
    ]
    assert built["receipt"]["selection"]["tau"] == pytest.approx(0.2)
    assert built["receipt"]["selection"]["changed_in"] == ["HK.C11"]
    assert built["receipt"]["selection"]["changed_out"] == ["HK.C10"]
    assert built["receipt"]["pre_score_key_order"] == ["bucket_weight", "no_trade_gate"]
    assert all(row["selection_reason"] for row in built["members"]["rows"])


def test_formula_states_are_h_n_u_and_missing_or_future_inputs_fail_closed() -> None:
    bad_state = _payload()
    bad_state["rows"][0]["f1_state"] = "P"
    with pytest.raises(ShadowInvalid, match="H, N, or U"):
        build_shadow(bad_state)

    future_formula = _payload()
    future_formula["formula_provenance"]["source_asof"] = "2026-09-21T09:36:00+08:00"
    with pytest.raises(ShadowInvalid, match="after the stage cutoff"):
        build_shadow(future_formula)


def test_immutable_freeze_labels_and_truth_scope(tmp_path: Path) -> None:
    persistent = _persistent_payload(tmp_path)
    frozen = freeze_snapshot(persistent, tmp_path)
    run_root = Path(frozen["run_root"])
    verified = verify_frozen_artifacts(run_root)
    assert verified["status"] == "PASS"
    receipt = json.loads((run_root / "selection_receipt.json").read_text(encoding="utf-8"))
    assert receipt["capture_origin"] == shadow_module.CAPTURE_ORIGIN_DIRECT
    assert receipt["invocation_verified"] is False
    assert receipt["invocation_status"] == shadow_module.INVOCATION_STATUS_DIRECT
    assert receipt["counts_as_forward_day"] is False
    assert receipt["natural_sample_count"] == 0
    assert frozen["safety"]["production_allowed"] is False

    with pytest.raises(ShadowInvalid, match="refusing to overwrite"):
        freeze_snapshot(persistent, tmp_path)

    labels = append_labels(run_root, _labels(tmp_path))
    assert labels["status"] == "ENGINEERING_ONLY"
    result = evaluate_run(run_root)
    assert result["status"] == "ENGINEERING_ONLY"
    assert result["hit_ready"] is False
    assert result["baseline_hit_count"] == 9
    assert result["candidate_hit_count"] == 10
    assert result["delta_hit_count"] == 1
    assert result["d1_pool_recall"] == pytest.approx(1.0)
    aggregate = evaluate_runs([run_root])
    assert aggregate["fixed_p10_denominator"] is None
    assert aggregate["fixed_recall20_denominator"] is None
    assert aggregate["delta_p_points"] is None
    assert aggregate["engineering_units"] == 1
    assert aggregate["evaluation_status"] == "ENGINEERING_ONLY"
    assert aggregate["changed_in_count"] == 0

    invalid = _labels(tmp_path)
    invalid["truth_scope"] = "CONDITIONAL_POSITIVE_CAP_TOP20_ONLY"
    second_payload = _persistent_payload(tmp_path, stage="STAGE_0945_1030")
    second = freeze_snapshot(second_payload, tmp_path)
    invalid_result = append_labels(Path(second["run_root"]), invalid)
    assert invalid_result["status"] == "CANNOT_CONFIRM"
    assert "labels/invalid_ledger.json" in str(Path(second["run_root"]) / "labels" / "invalid_ledger.json")


def test_preflight_rejects_legacy_archive_and_does_not_count_a_natural_day() -> None:
    payload = _metadata()
    payload.update({"source_mode": "LEGACY_ARCHIVE", "rows": _rows()})
    result = preflight_input(payload)
    assert result["status"] == "REJECTED"
    assert result["forward_eligible"] is False
    assert "LEGACY_OR_PROXY_SOURCE_REJECTED" in result["reasons"]
    assert result["natural_sample_count"] == 0
    assert result["counts_as_forward_day"] is False


def test_tampering_with_frozen_baseline_is_detected(tmp_path: Path) -> None:
    frozen = freeze_snapshot(_persistent_payload(tmp_path), tmp_path)
    path = Path(frozen["run_root"]) / "baseline_top10.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["codes"][0] = "HK.TAMPERED"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ShadowInvalid, match="hash mismatch"):
        verify_frozen_artifacts(Path(frozen["run_root"]))


def test_tampering_with_labels_is_cannot_confirm(tmp_path: Path) -> None:
    frozen = freeze_snapshot(_persistent_payload(tmp_path), tmp_path)
    run_root = Path(frozen["run_root"])
    assert append_labels(run_root, _labels(tmp_path))["status"] == "ENGINEERING_ONLY"
    labels_path = run_root / "labels" / "labels.json"
    payload = json.loads(labels_path.read_text(encoding="utf-8"))
    payload["rows"][0]["hit_top20"] = False
    labels_path.write_text(json.dumps(payload), encoding="utf-8")
    result = evaluate_run(run_root)
    assert result["status"] == "CANNOT_CONFIRM"
    assert result["invalid_reasons"] == ["LABEL_HASH_MISMATCH"]


def _selector_rows() -> list[dict]:
    return [
        {
            "code": f"HK.S{index:03d}",
            "candidate_lanes": ["LIVE_HKCONNECT_GAINER", "LOW_FLOAT_FILTER"],
            "platform_circular_market_cap_hkd_yi": 80.0,
            "offer_float_market_cap_hkd_yi": 15.0,
            "pct_chg": 20.0 - index / 10.0,
            "volume_ratio": 2.0,
            "turnover_hkd_yi": 0.5,
            "turnover_rate": 5.0,
            "last_price": 10.0 + index / 100,
            "update_time": "2026-09-21T09:34:00+08:00",
            "currency": "HKD",
            "adjustment_mode": "RAW",
            "price_source": "HK_SELECTOR_TEST",
            "stage_id": "STAGE_0930_0935",
        }
        for index in range(1, 101)
    ]


def _selector_capture_input(tmp_path: Path) -> dict:
    rows = _selector_rows()
    source_path = tmp_path / "selector-source.json"
    source_path.write_text(json.dumps({"rows": rows}, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    rule_path = tmp_path / "selector-rule.txt"
    rule_path.write_text("selector-rule-v1", encoding="utf-8")
    rule_sha = hashlib.sha256(rule_path.read_bytes()).hexdigest()
    formula_rows = [
        {
            "security_id": row["code"],
            "f1_state": "H" if index == 11 else "N",
            "f2_state": "N",
            "f3_state": "U" if index == 12 else "N",
            "f4_state": "N",
        }
        for index, row in enumerate(rows, start=1)
    ]
    formula_path = tmp_path / "selector-formula.json"
    formula_path.write_text(json.dumps({"rows": formula_rows}, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    formula_sha = hashlib.sha256(formula_path.read_bytes()).hexdigest()
    formula_rule_path = tmp_path / "selector-formula-rule.txt"
    formula_rule_path.write_text("verified-selector-formula-rule-v1", encoding="utf-8")
    formula_rule_sha = hashlib.sha256(formula_rule_path.read_bytes()).hexdigest()
    d1_path = tmp_path / "selector-d1.json"
    d1_path.write_text(json.dumps({"rows": rows}, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    d1_sha = hashlib.sha256(d1_path.read_bytes()).hexdigest()
    return {
        "metadata": {
            "experiment_id": EXPERIMENT_ID,
            "admission_mode": ENGINEERING_FIXTURE,
            "observation_mode": "FORWARD_SHADOW",
            "captured_at": "2026-09-21T09:35:00+08:00",
            "trade_date": "20260921",
            "stage": "STAGE_0930_0935",
            "cutoff_ts": "2026-09-21T09:35:05+08:00",
            "market": "HK_CONNECT",
            "source_version": "v4.hk.production.selector.v1",
            "input_sha256": source_sha,
            "rule_sha256": rule_sha,
            "comparator_version": COMPARATOR_VERSION,
            "raw_artifact_sha256": source_sha,
            "source_artifact": {"path": str(source_path), "sha256": source_sha},
            "rule_artifact": {"path": str(rule_path), "sha256": rule_sha},
            "formula_provenance": {
                "source_version": "hk-formula-state-v1",
                "input_sha256": formula_sha,
                "rule_sha256": formula_rule_sha,
                "source_asof": "2026-09-20",
                "frozen_at": "2026-09-20T18:00:00+08:00",
                "artifact": {"path": str(formula_path), "sha256": formula_sha},
                "rule_artifact": {"path": str(formula_rule_path), "sha256": formula_rule_sha},
            },
            "source_evidence": ["selection_contract=V3_TOP10_RECOMMENDATION"],
            "requested_rows": 100,
        },
        "rows": rows,
        "formula_manifest": {
            "version": "hk-formula-manifest-v1",
            "manifest_sha256": formula_sha,
            "input_sha256": formula_sha,
            "rule_sha256": formula_rule_sha,
            "artifact": {"path": str(formula_path), "sha256": formula_sha},
            "rule_artifact": {"path": str(formula_rule_path), "sha256": formula_rule_sha},
            "rows": formula_rows,
        },
        "time_evidence": {"source": "selector-test", "captured_at": "2026-09-21T09:35:00+08:00"},
        "d1_manifest": {
            "version": "hk-d1-manifest-v1",
            "manifest_sha256": d1_sha,
            "artifact": {"path": str(d1_path), "sha256": d1_sha},
        },
    }


def test_selector_shadow_hook_is_default_off_full_sorted_and_failure_isolated() -> None:
    rows = _selector_rows()
    kwargs = {
        "source_evidence": ("selection_contract=V3_TOP10_RECOMMENDATION",),
    }
    off = select_hk_four_lane(rows, "20260921", "STAGE_0930_0935", "a" * 64, **kwargs)
    captured: list[dict] = []
    on = select_hk_four_lane(
        rows,
        "20260921",
        "STAGE_0930_0935",
        "a" * 64,
        shadow_capture=lambda **value: captured.append(value),
        **kwargs,
    )
    assert on == off
    assert len(captured) == 1
    assert len(captured[0]["raw_rows"]) == 100
    assert len(captured[0]["sorted_rows"]) == 100
    assert all(row["selection_eligible"] is True for row in captured[0]["sorted_rows"])
    assert all(row["formal_eligible"] is False for row in captured[0]["production_rows"])
    assert [row["code"] for row in captured[0]["sorted_rows"][:10]] == [row["code"] for row in off["rows"]]

    def broken(**_: object) -> None:
        raise OSError("shadow disk unavailable")

    assert select_hk_four_lane(rows, "20260921", "STAGE_0930_0935", "a" * 64, shadow_capture=broken, **kwargs) == off


def test_real_selector_capture_assigns_ranks_and_freezes_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _selector_capture_input(tmp_path)
    runtime = shadow_module._parse_timestamp(
        "2026-09-21T09:35:00+08:00", "20260921", "test"
    )
    monkeypatch.setattr(shadow_module, "_runtime_capture_timestamp", lambda: runtime)
    captured: list[dict] = []
    selected = select_hk_four_lane(
        payload["rows"],
        "20260921",
        "STAGE_0930_0935",
        payload["metadata"]["raw_artifact_sha256"],
        source_evidence=tuple(payload["metadata"]["source_evidence"]),
        shadow_capture=lambda **value: captured.append(value),
        shadow_context=payload["metadata"],
    )
    assert selected["rows"]
    shadow_payload = build_selector_capture_payload(
        metadata=payload["metadata"],
        raw_rows=captured[0]["raw_rows"],
        sorted_rows=captured[0]["sorted_rows"],
        production_rows=captured[0]["production_rows"],
        formula_manifest=payload["formula_manifest"],
        time_evidence=payload["time_evidence"],
        d1_manifest=payload["d1_manifest"],
        raw_artifact_sha256=payload["metadata"]["raw_artifact_sha256"],
    )
    # A direct in-memory builder still needs a fixture binding; the runtime
    # capture path below obtains the authoritative ID from the selector return.
    shadow_payload["run_id"] = "fixture-direct-run"
    built = build_shadow(shadow_payload, require_full_pool=True, require_artifacts=True)
    assert built["baseline"]["codes"] == [row["code"] for row in selected["rows"]]
    assert sorted(row["production_rank"] for row in built["members"]["rows"]) == list(range(1, 101))
    payload["metadata"]["captured_at"] = "2026-09-21T09:30:00+08:00"
    payload["time_evidence"]["captured_at"] = "2026-09-21T09:30:00+08:00"
    payload["time_evidence"]["source"] = "operator-forged-source"
    manual = capture_selector_snapshot(payload, tmp_path / "shadow-output")
    assert manual["status"] == "ENGINEERING_ONLY"
    assert manual["capture"]["status"] == "ENGINEERING_ONLY"
    assert manual["capture"]["freeze_status"] == "FROZEN"
    assert manual["capture"]["selector_top10_codes"] == [row["code"] for row in selected["rows"]]
    runtime_receipt = json.loads(
        (Path(manual["capture"]["capture"]["run_root"]) / "capture_time_receipt.json").read_text(
            encoding="utf-8"
        )
    )
    assert runtime_receipt["captured_at"] == runtime.isoformat()
    assert runtime_receipt["source"] == shadow_module.CAPTURE_TIME_SOURCE
    assert runtime_receipt["selector_invocation_status"] == "COMPLETED"
    assert runtime_receipt["invocation_verified"] is True
    assert runtime_receipt["production_run_id"] == manual["selector"]["run_id"]
    assert runtime_receipt["production_artifact_id"] == manual["selector"]["artifact_id"]
    assert runtime_receipt["production_algorithm_sha256"] == manual["selector"]["algorithm_sha256"]
    assert runtime_receipt["shadow_invocation_id"] != runtime_receipt["production_run_id"]
    assert runtime_receipt["raw_artifact_sha256"] == runtime_receipt["source_artifact_sha256"]
    run_root = Path(manual["capture"]["capture"]["run_root"])
    selector_result = json.loads((run_root / "selector_result.json").read_text(encoding="utf-8"))
    assert runtime_receipt["selector_result_sha256"] == hashlib.sha256(
        canonical_json(selector_result)
    ).hexdigest()
    receipt = json.loads((run_root / "selection_receipt.json").read_text(encoding="utf-8"))
    assert set(receipt["provenance"]) == {
        "production_source", "production_rule", "d1_manifest", "formula_state", "formula_rule", "selector_result"
    }
    verified = verify_frozen_artifacts(run_root)
    assert verified["frozen_integrity_status"] == "PASS"
    assert verified["integrity_scope"] == "LOCAL_FROZEN_AND_SEALED_PROVENANCE"


def test_selector_capture_rejects_caller_run_identity_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = _selector_capture_input(tmp_path)
    payload["metadata"]["run_id"] = "caller-forged-run"
    runtime = shadow_module._parse_timestamp("2026-09-21T09:35:00+08:00", "20260921", "test")
    monkeypatch.setattr(shadow_module, "_runtime_capture_timestamp", lambda: runtime)
    result = capture_selector_snapshot(payload, tmp_path / "shadow-output")
    assert result["status"] == "CANNOT_CONFIRM"
    assert any("caller run_id" in reason for reason in result["capture"]["invalid_reasons"])
    assert not (tmp_path / "shadow-output" / "20260921" / "STAGE_0930_0935" / "baseline_top10.json").exists()


def test_selector_capture_rejects_return_top10_that_differs_from_callback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _selector_capture_input(tmp_path)
    runtime = shadow_module._parse_timestamp("2026-09-21T09:35:00+08:00", "20260921", "test")
    monkeypatch.setattr(shadow_module, "_runtime_capture_timestamp", lambda: runtime)
    original = selection_module.select_hk_four_lane

    def altered(*args: object, **kwargs: object) -> dict:
        result = copy.deepcopy(original(*args, **kwargs))
        result["rows"][0], result["rows"][1] = result["rows"][1], result["rows"][0]
        return result

    monkeypatch.setattr(selection_module, "select_hk_four_lane", altered)
    result = capture_selector_snapshot(payload, tmp_path / "shadow-output")
    assert result["status"] == "CANNOT_CONFIRM"
    assert any("Top10" in reason for reason in result["capture"]["invalid_reasons"])
    assert not (tmp_path / "shadow-output" / "20260921" / "STAGE_0930_0935" / "baseline_top10.json").exists()


def test_selector_capture_rejects_baseline_parity_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _selector_capture_input(tmp_path)
    runtime = shadow_module._parse_timestamp("2026-09-21T09:35:00+08:00", "20260921", "test")
    monkeypatch.setattr(shadow_module, "_runtime_capture_timestamp", lambda: runtime)
    original = shadow_module.build_shadow

    def altered(*args: object, **kwargs: object) -> dict:
        built = original(*args, **kwargs)
        if kwargs.get("allow_invocation_verified") is True:
            built["baseline"]["codes"][0] = "HK.PARITY_FAILURE"
        return built

    monkeypatch.setattr(shadow_module, "build_shadow", altered)
    result = capture_selector_snapshot(payload, tmp_path / "shadow-output")
    assert result["status"] == "CANNOT_CONFIRM"
    assert any("baseline" in reason for reason in result["capture"]["invalid_reasons"])


@pytest.mark.parametrize(
    "receipt_field",
    ["production_run_id", "production_artifact_id", "source_artifact_sha256", "raw_artifact_sha256"],
)
def test_verified_receipt_identity_and_source_fields_are_tamper_evident(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, receipt_field: str
) -> None:
    payload = _selector_capture_input(tmp_path)
    runtime = shadow_module._parse_timestamp("2026-09-21T09:35:00+08:00", "20260921", "test")
    monkeypatch.setattr(shadow_module, "_runtime_capture_timestamp", lambda: runtime)
    result = capture_selector_snapshot(payload, tmp_path / "shadow-output")
    run_root = Path(result["capture"]["capture"]["run_root"])
    receipt_path = run_root / "capture_time_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt[receipt_field] = "0" * 64 if receipt_field.endswith("sha256") else "tampered-identity"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ShadowInvalid, match="capture_time_receipt hash mismatch"):
        verify_frozen_artifacts(run_root)


def test_verified_provenance_is_locally_stable_when_external_source_drifts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _selector_capture_input(tmp_path)
    runtime = shadow_module._parse_timestamp("2026-09-21T09:35:00+08:00", "20260921", "test")
    monkeypatch.setattr(shadow_module, "_runtime_capture_timestamp", lambda: runtime)
    result = capture_selector_snapshot(payload, tmp_path / "shadow-output")
    run_root = Path(result["capture"]["capture"]["run_root"])
    source_path = Path(payload["metadata"]["source_artifact"]["path"])
    source_path.write_bytes(source_path.read_bytes() + b"external drift")
    local = verify_frozen_artifacts(run_root)
    assert local["frozen_integrity_status"] == "PASS"
    assert local["external_source_revalidation"] == "NOT_REQUESTED"
    assert verify_frozen_artifacts(run_root, external_revalidate=True)["external_source_revalidation"] == "DRIFTED"
    source_path.unlink()
    assert verify_frozen_artifacts(run_root, external_revalidate=True)["external_source_revalidation"] == "MISSING"


def test_verified_provenance_tamper_and_removal_fail_local_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _selector_capture_input(tmp_path)
    runtime = shadow_module._parse_timestamp("2026-09-21T09:35:00+08:00", "20260921", "test")
    monkeypatch.setattr(shadow_module, "_runtime_capture_timestamp", lambda: runtime)
    result = capture_selector_snapshot(payload, tmp_path / "shadow-output")
    run_root = Path(result["capture"]["capture"]["run_root"])
    sealed = run_root / "provenance" / "production_rule.bin"
    sealed.write_bytes(sealed.read_bytes() + b"tamper")
    with pytest.raises(ShadowInvalid, match="sealed provenance production_rule hash mismatch"):
        verify_frozen_artifacts(run_root)

    second_root = tmp_path / "second"
    second_root.mkdir()
    payload2 = _selector_capture_input(second_root)
    runtime2 = shadow_module._parse_timestamp("2026-09-21T09:35:00+08:00", "20260921", "test")
    monkeypatch.setattr(shadow_module, "_runtime_capture_timestamp", lambda: runtime2)
    result2 = capture_selector_snapshot(payload2, tmp_path / "second-output")
    run_root2 = Path(result2["capture"]["capture"]["run_root"])
    (run_root2 / "provenance" / "d1_manifest.bin").unlink()
    with pytest.raises(ShadowInvalid, match="sealed provenance d1_manifest hash mismatch"):
        verify_frozen_artifacts(run_root2)

    third_root = tmp_path / "third"
    third_root.mkdir()
    payload3 = _selector_capture_input(third_root)
    runtime3 = shadow_module._parse_timestamp("2026-09-21T09:35:00+08:00", "20260921", "test")
    monkeypatch.setattr(shadow_module, "_runtime_capture_timestamp", lambda: runtime3)
    result3 = capture_selector_snapshot(payload3, tmp_path / "third-output")
    run_root3 = Path(result3["capture"]["capture"]["run_root"])
    selector_path = run_root3 / "selector_result.json"
    selector_payload = json.loads(selector_path.read_text(encoding="utf-8"))
    selector_payload["run_id"] = "tampered-run"
    selector_path.write_text(json.dumps(selector_payload), encoding="utf-8")
    with pytest.raises(ShadowInvalid, match="sealed provenance selector_result hash mismatch"):
        verify_frozen_artifacts(run_root3)


def test_r2_capture_static_preflight_and_provenance_bindings(tmp_path: Path) -> None:
    payload = _selector_capture_input(tmp_path)
    ready = preflight_capture_input(payload)
    assert ready["status"] == "READY_FOR_CAPTURE_INVOCATION"
    assert ready["capture_ready"] is True
    assert ready["frozen"] is False
    assert ready["natural_sample_count"] == 0

    bad_raw_sha = copy.deepcopy(payload)
    bad_raw_sha["metadata"]["raw_artifact_sha256"] = "e" * 64
    rejected = preflight_capture_input(bad_raw_sha)
    assert rejected["status"] == "REJECTED"
    assert "raw_artifact_sha256" in rejected["reasons"][0]

    bad_sequence = copy.deepcopy(payload)
    bad_sequence["rows"][0], bad_sequence["rows"][1] = bad_sequence["rows"][1], bad_sequence["rows"][0]
    rejected_sequence = preflight_capture_input(bad_sequence)
    assert rejected_sequence["status"] == "REJECTED"
    assert "canonically match" in rejected_sequence["reasons"][0]

    bad_content = copy.deepcopy(payload)
    bad_content["rows"][0]["name"] = "different-non-comparator-content"
    rejected_content = preflight_capture_input(bad_content)
    assert rejected_content["status"] == "REJECTED"
    assert "canonically match" in rejected_content["reasons"][0]

    bad_formula_rule = copy.deepcopy(payload)
    bad_formula_rule["formula_manifest"].pop("rule_artifact")
    rejected_formula_rule = preflight_capture_input(bad_formula_rule)
    assert rejected_formula_rule["status"] == "REJECTED"
    assert "formula rule artifact" in rejected_formula_rule["reasons"][0]

    bad_formula_state = copy.deepcopy(payload)
    bad_formula_state["formula_manifest"]["rows"][0]["f1_state"] = "H"
    rejected_formula_state = preflight_capture_input(bad_formula_state)
    assert rejected_formula_state["status"] == "REJECTED"
    assert "states do not match" in rejected_formula_state["reasons"][0]

    for count in (99, 101):
        short_or_long = copy.deepcopy(payload)
        if count == 99:
            short_or_long["rows"] = short_or_long["rows"][:count]
        else:
            short_or_long["rows"].append(copy.deepcopy(short_or_long["rows"][0]))
        rejected_size = preflight_capture_input(short_or_long)
        assert rejected_size["status"] == "REJECTED"
        assert "exactly 100" in rejected_size["reasons"][0]

    rejected_empty = preflight_capture_input({"metadata": payload["metadata"], "rows": []})
    assert rejected_empty["status"] == "REJECTED"
    assert rejected_empty["capture_ready"] is False


def test_r2_capture_static_gate_blocks_before_selector_and_no_artifact(tmp_path: Path) -> None:
    payload = _selector_capture_input(tmp_path)
    payload["metadata"]["raw_artifact_sha256"] = "f" * 64
    output_root = tmp_path / "shadow-output"
    result = capture_selector_snapshot(payload, output_root)
    assert result["status"] == "CANNOT_CONFIRM"
    assert result["capture"]["status"] == "CANNOT_CONFIRM"
    run_root = output_root / "20260921" / "STAGE_0930_0935"
    assert (run_root / "invalid_ledger.json").is_file()
    assert not (run_root / "baseline_top10.json").exists()


def test_admission_modes_keep_self_reported_real_truth_blocked(tmp_path: Path) -> None:
    fake_real = _persistent_payload(tmp_path)
    fake_real["admission_mode"] = REAL_AUTHORITY
    with pytest.raises(ShadowInvalid, match="REAL_AUTHORITY_BUILD_BLOCKED_OWNER_CONTRACT_PENDING"):
        build_shadow(fake_real, require_full_pool=True, require_artifacts=True)
    frozen = freeze_snapshot(_persistent_payload(tmp_path), tmp_path)
    real_labels = _labels(tmp_path)
    real_labels["admission_mode"] = REAL_AUTHORITY
    rejected = append_labels(Path(frozen["run_root"]), real_labels)
    assert rejected["status"] == "CANNOT_CONFIRM"
    assert any("REAL_AUTHORITY_TRUTH_BLOCKED" in reason for reason in rejected["invalid_reasons"])

    engineering = _labels(tmp_path)
    accepted = append_labels(Path(freeze_snapshot(_persistent_payload(tmp_path, stage="STAGE_0945_1030"), tmp_path)["run_root"]), engineering)
    assert accepted["status"] == "ENGINEERING_ONLY"
    assert accepted["label_count"] > 0


def test_real_capture_preflight_is_blocked_before_caller_time_evidence(tmp_path: Path) -> None:
    payload = _selector_capture_input(tmp_path)
    payload["metadata"]["admission_mode"] = REAL_AUTHORITY
    payload["metadata"]["captured_at"] = "2026-09-21T09:34:59+08:00"
    payload["time_evidence"]["source"] = "operator-forged-runtime-proof"
    ready = preflight_capture_input(payload)
    assert ready["status"] == "REJECTED"
    assert "REAL_AUTHORITY_CAPTURE_BLOCKED_OWNER_CONTRACT_PENDING" in ready["reasons"]
    captured = capture_selector_snapshot(payload, tmp_path / "blocked-real")
    assert captured["status"] == "CANNOT_CONFIRM"
    assert "REAL_AUTHORITY_CAPTURE_BLOCKED_OWNER_CONTRACT_PENDING" in captured["capture"]["invalid_reasons"]


@pytest.mark.parametrize(
    ("runtime_value", "message"),
    [
        ("2026-09-20T09:35:05+08:00", "date does not match"),
        ("2026-09-22T09:35:05+08:00", "date does not match"),
        ("2026-09-21T09:29:59+08:00", "before"),
        ("2026-09-21T09:35:06+08:00", "after"),
        ("2026-09-19T16:00:00-07:00", "date does not match"),
    ],
)
def test_runtime_capture_clock_rejects_wrong_date_timezone_and_stage_window(
    runtime_value: str,
    message: str,
) -> None:
    with pytest.raises(ShadowInvalid, match=message):
        shadow_module._validate_runtime_capture_timestamp(
            runtime_value,
            "20260921",
            "STAGE_0930_0935",
        )


def test_direct_freeze_rejects_caller_completed_receipt(tmp_path: Path) -> None:
    payload = _persistent_payload(tmp_path)
    payload["capture_time_receipt"] = {
        "schema_version": shadow_module.CAPTURE_TIME_RECEIPT_SCHEMA_VERSION,
        "source": shadow_module.CAPTURE_TIME_SOURCE,
        "experiment_id": EXPERIMENT_ID,
        "admission_mode": ENGINEERING_FIXTURE,
        "invocation_verified": True,
        "selector_invocation_status": "COMPLETED",
    }
    with pytest.raises(ShadowInvalid, match="INVOCATION_VERIFIED_RECEIPT_REQUIRES_SELECTOR_CAPTURE"):
        freeze_snapshot(payload, tmp_path)


def test_persistent_freeze_requires_full_pool_and_real_artifact_binding(tmp_path: Path) -> None:
    with pytest.raises(ShadowInvalid, match="complete 100-row D1 pool"):
        freeze_snapshot(_payload(), tmp_path)
    payload = _persistent_payload(tmp_path)
    payload["input_sha256"] = "a" * 64
    with pytest.raises(ShadowInvalid, match="source_artifact SHA is not bound"):
        freeze_snapshot(payload, tmp_path)


def test_alias_conflict_and_preflight_short_rows_fail_closed() -> None:
    conflict = _payload()
    conflict["rows"][0]["bucket_weight"] = 0
    with pytest.raises(ShadowInvalid, match="bucket_weight conflicts"):
        build_shadow(conflict)
    short = _metadata()
    short["rows"] = []
    result = preflight_input(short)
    assert result["status"] == "REJECTED"
    assert result["forward_eligible"] is False
    assert any(reason.startswith("INPUT_VALIDATION:") for reason in result["reasons"])


def test_no_rank10_same_class_gap_invalidates_stage() -> None:
    payload = _payload()
    for row in payload["rows"]:
        row["lane"] = ["LANE_MAIN"]
    payload["rows"][9]["lane"] = ["LANE_RANK10_ONLY"]
    with pytest.raises(ShadowInvalid, match="no valid rank6..15 score gap"):
        build_shadow(payload)


def test_tau_zero_allows_only_same_score_equivalence_reorder() -> None:
    payload = _payload()
    for row in payload["rows"]:
        row["stage_score"] = 92.0
    built = build_shadow(payload)
    assert built["receipt"]["selection"]["tau"] == 0.0
    assert built["receipt"]["selection"]["tau_zero_tie_only"] is True
    assert all(
        row["stage_score"] == payload["rows"][int(row["production_rank"]) - 1]["stage_score"]
        for row in built["candidate"]["rows"]
    )


def test_truth_is_computed_from_verified_full_universe_and_fake_top20_is_rejected(tmp_path: Path) -> None:
    frozen = freeze_snapshot(_persistent_payload(tmp_path), tmp_path)
    labels = _labels(tmp_path)
    labels["truth_top20_codes"] = [f"HK.C{i:02d}" for i in range(1, 21)]
    result = append_labels(Path(frozen["run_root"]), labels)
    assert result["status"] == "CANNOT_CONFIRM"
    assert any("verified full-universe" in reason for reason in result["invalid_reasons"])


def test_truth_boundary_tie_is_not_resolved_by_caller_tie_break(tmp_path: Path) -> None:
    frozen = freeze_snapshot(_persistent_payload(tmp_path), tmp_path)
    labels = _labels(tmp_path)
    source_path = Path(labels["truth_source_artifact"]["path"])
    source = json.loads(source_path.read_text(encoding="utf-8"))
    for row in source["rows"]:
        if row["security_id"] == "HK.C10":
            row["close"] = 121.0
            break
    source_path.write_text(json.dumps(source, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    labels["truth_manifest_sha256"] = source_sha
    labels["truth_source_artifact"]["sha256"] = source_sha
    canonical_truth = [
        {
            "security_id": row["security_id"],
            "close_price": float(row["close"]),
            "pre_close_price": float(row["pre_close"]),
            "close_gain": float(row["close"]) / float(row["pre_close"]) - 1.0,
        }
        for row in source["rows"]
    ]
    labels["truth_input_sha256"] = sha256_bytes(canonical_json(canonical_truth))
    result = append_labels(Path(frozen["run_root"]), labels)
    assert result["status"] == "CANNOT_CONFIRM"
    assert any("boundary tie" in reason for reason in result["invalid_reasons"])


def test_hit_evaluation_survives_missing_markout_semantics(tmp_path: Path) -> None:
    frozen = freeze_snapshot(_persistent_payload(tmp_path), tmp_path)
    labels = _labels(tmp_path)
    labels["rows"][0].pop("currency")
    labels["rows"][0].pop("adjustment_mode")
    labels["rows"][0].pop("close_price_source")
    result = append_labels(Path(frozen["run_root"]), labels)
    assert result["status"] == "ENGINEERING_ONLY"
    assert result["markout_invalid_reasons"]
    evaluation = evaluate_run(Path(frozen["run_root"]))
    assert evaluation["status"] == "ENGINEERING_ONLY"
    assert evaluation["baseline_hit_count"] == 9
    assert evaluation["candidate_hit_count"] == 10
    assert evaluation["markout"]["status"] == "CANNOT_CONFIRM"


def test_evaluate_runs_reports_planned_valid_invalid_without_zero_filling(tmp_path: Path) -> None:
    first = freeze_snapshot(_persistent_payload(tmp_path), tmp_path)
    assert append_labels(Path(first["run_root"]), _labels(tmp_path))["status"] == "ENGINEERING_ONLY"
    second = freeze_snapshot(_persistent_payload(tmp_path, stage="STAGE_0945_1030"), tmp_path)
    aggregate = evaluate_runs([first["run_root"], second["run_root"]])
    assert aggregate["planned_units"] == 2
    assert aggregate["valid_units"] == 0
    assert aggregate["engineering_units"] == 1
    assert aggregate["invalid_units"] == 1
    assert aggregate["evaluation_status"] == "CANNOT_CONFIRM"
    assert aggregate["fixed_p10_denominator"] is None
    assert aggregate["changed_in_count"] == 0
