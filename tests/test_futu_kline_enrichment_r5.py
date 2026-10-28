from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

import ops.enrich_hk_stage_futu_kline as enrichment_module
import stage_center.selection as selection_module
from ops.enrich_hk_stage_futu_kline import (
    AFTERFACT_CANNOT_CONFIRM,
    ORDERBOOK_CANNOT_CONFIRM,
    _expected_window_keys,
    aggregate_code_window,
    canonical_json_bytes,
    d1_pool_lineage,
    enrich_stage_rows,
)
from stage_center.consumer import StageSelectionConsumer
from stage_center.contracts import SAFETY_FLAGS, SELECTION_ALGORITHM_ID
from stage_center.selection import ALGORITHM_SHA256, SELECTION_SCHEMA_VERSION, SelectionError, SelectionStore


_R5_STAGES = ("STAGE_1300_1315", "STAGE_1445_1500")
_D1_SOURCE_SHA = "c" * 64
_D1_ARTIFACT_SHA = "d" * 64
_D1_POOL_VERSION = "hkconnect_d1_top100_pool.v3_vipdoc_panel"
_INPUT_BASELINE_SHA = "e" * 64


def _publication_fixture(tmp_path: Path):
    store = SelectionStore(tmp_path / "selection")
    envelopes = {}
    identities = {}
    candidates = {}
    for stage_index, stage_id in enumerate(_R5_STAGES):
        first_code = 1 + stage_index
        rows = []
        for rank, numeric_code in enumerate(range(first_code, first_code + 10), start=1):
            rows.append(
                {
                    "code": f"HK.{numeric_code:05d}",
                    "rank": rank,
                    "score": 70.0 - rank,
                    "d1_rank": rank + 20,
                    "d1_score": 0.8 - rank / 100,
                    "action_level": "NO_BUY",
                    "current_change_pct": None,
                    "open_price": None,
                    "last_price": 10.0,
                    "high_price": None,
                    "low_price": None,
                    "support": None,
                    "pressure": None,
                    "invalidation": None,
                    "source_last_bar_time": None,
                    "support_primary_price": None,
                    "pressure_price": None,
                    "invalidation_price": None,
                    "next_validation_time": "13:15:00" if stage_index == 0 else "15:00:00",
                    "d1_source_evidence": [
                        f"hk_d1_pool_version={_D1_POOL_VERSION}",
                        f"hk_d1_source_sha256={_D1_SOURCE_SHA}",
                    ],
                }
            )
        envelope = {
            "schema_version": SELECTION_SCHEMA_VERSION,
            "trade_date": "20261012",
            "stage_id": stage_id,
            "market": "HK_CONNECT",
            "algorithm_id": SELECTION_ALGORITHM_ID,
            "algorithm_sha256": ALGORITHM_SHA256,
            "source_status": "READY",
            "selection_status": "READY",
            "requested_rows": 100,
            "source_rows": 100,
            "selected_rows": 10,
            "coverage_ratio": 0.1,
            "missing_symbols": [],
            "raw_artifact_sha256": ("a" if stage_index == 0 else "b") * 64,
            "rows": rows,
            "source_evidence": [f"hk_d1_json_sha256={_D1_ARTIFACT_SHA}"],
            "cannot_confirm": [],
            **SAFETY_FLAGS,
        }
        store.publish(deepcopy(envelope), market="HK_CONNECT")
        verified = store._verify_run("20261012", stage_id, "HK_CONNECT", store._latest()["entries"][store._key("20261012", stage_id, "HK_CONNECT")]["run_id"])
        run_prefix = f"selection_runs/20261012/{store._role(stage_id, 'HK_CONNECT')}/{verified['run_id']}"
        identities[stage_id] = {
            "run_id": verified["run_id"],
            "artifact_id": verified["envelope"]["artifact_id"],
            "artifact_sha256": verified["artifact_sha256"],
            "manifest_sha256": verified["manifest_sha256"],
            "receipt_sha256": verified["receipt_sha256"],
            "manifest_file_sha256": selection_module._sha_file(store.root / run_prefix / "manifest.json"),
            "receipt_file_sha256": selection_module._sha_file(store.root / run_prefix / "receipt.json"),
            "raw_artifact_sha256": verified["envelope"]["raw_artifact_sha256"],
            "algorithm_sha256": verified["envelope"]["algorithm_sha256"],
        }
        envelopes[stage_id] = verified["envelope"]
        candidate_rows = deepcopy(verified["envelope"]["rows"])
        for row in candidate_rows:
            row.update(
                {
                    "current_change_pct": 1.0,
                    "open_price": 10.0,
                    "last_price": 10.1,
                    "high_price": 10.2,
                    "low_price": 9.9,
                    "support": 9.9,
                    "pressure": 10.2,
                    "invalidation": 9.9,
                    "source_last_bar_time": "2026-10-12 13:14:00" if stage_index == 0 else "2026-10-12 14:59:00",
                    "support_primary_price": 9.9,
                    "pressure_price": 10.2,
                    "invalidation_price": 9.9,
                }
            )
        candidates[stage_id] = {
            "trade_date": "20261012",
            "stage_id": stage_id,
            "market": "HK_CONNECT",
            "source_selection_run_id": verified["run_id"],
            "source_selection_artifact_id": verified["envelope"]["artifact_id"],
            "source_selection_status": verified["envelope"]["selection_status"],
            "source_status": verified["envelope"]["source_status"],
            "source_selection_artifact_sha256": verified["artifact_sha256"],
            "source_selection_manifest_sha256": identities[stage_id]["manifest_file_sha256"],
            "source_selection_receipt_sha256": identities[stage_id]["receipt_file_sha256"],
            "raw_artifact_sha256": verified["envelope"]["raw_artifact_sha256"],
            "algorithm_id": SELECTION_ALGORITHM_ID,
            "algorithm_sha256": ALGORITHM_SHA256,
            "requested_rows": 100,
            "source_rows": 100,
            "selected_rows": 10,
            "coverage_ratio": 0.1,
            "missing_symbols": [],
            "rows": candidate_rows,
            "source_evidence": [
                f"hk_d1_json_sha256={_D1_ARTIFACT_SHA}",
                f"hk_d1_pool_version={_D1_POOL_VERSION}",
            ],
            "cannot_confirm": ["FUTU_KLINE_CAPTURE_AFTER_TARGET_CUTOFF_NOT_PIT"],
            "selection_action_boundary": "NO_BUY",
            "research_only": True,
            "formal_stage_eligibility": "CANNOT_CONFIRM",
            "pit_safe": False,
            "temporal_cutoff_safe": False,
            "historical_orderbook_status": "CANNOT_CONFIRM_NO_CUTOFF_BOUND_SNAPSHOT",
            "current_orderbook_queried": False,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    union = sorted(
        {
            str(row["code"])
            for stage in candidates.values()
            for row in stage["rows"]
        }
    )
    candidate = {
        "schema": "v4_hk_stage_futu_kline_enrichment_overlay_r5_v1",
        "candidate_status": "REVIEW_REQUIRED_NOT_FORMALLY_PUBLISHED",
        "candidate_kind": "DISPLAY_EVIDENCE_OVERLAY_ONLY",
        "trade_date": "20261012",
        "market": "HK_CONNECT",
        "source": {
            "input_baseline_sha256": _INPUT_BASELINE_SHA,
            "fixed_d1_pool_row_count": 100,
            "fixed_d1_pool_source_sha256_by_stage": {stage: _D1_SOURCE_SHA for stage in _R5_STAGES},
            "fixed_d1_pool_artifact_sha256_by_stage": {stage: _D1_ARTIFACT_SHA for stage in _R5_STAGES},
            "fixed_d1_pool_version_by_stage": {stage: _D1_POOL_VERSION for stage in _R5_STAGES},
            "selection_run_ids": {stage: identities[stage]["run_id"] for stage in _R5_STAGES},
            "selection_artifact_sha256_by_stage": {stage: identities[stage]["artifact_sha256"] for stage in _R5_STAGES},
            "stage_raw_artifact_sha256_by_stage": {stage: identities[stage]["raw_artifact_sha256"] for stage in _R5_STAGES},
            "target_code_count": 11,
            "target_code_union": union,
        },
        "provenance": {
            "source_id": "futu_openapi_get_cur_kline",
            "method": "get_cur_kline(code,1000,SubType.K_1M,AuType.NONE)",
            "historical_orderbook_status": "CANNOT_CONFIRM_NO_CUTOFF_BOUND_SNAPSHOT",
            "current_orderbook_queried": False,
            "provider_subscription_release_receipt_status": "CANNOT_CONFIRM",
        },
        "safety": {
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "selection_action_boundary": "NO_BUY",
            "pit_safe": False,
            "temporal_cutoff_safe": False,
            "formal_stage_eligibility": "CANNOT_CONFIRM",
        },
        "stages": candidates,
    }
    return store, envelopes, identities, candidate


def _candidate_bytes(candidate):
    return canonical_json_bytes(candidate)


def _publish_fixture_candidate(store, identities, candidate):
    candidate_bytes = _candidate_bytes(candidate)
    return store.publish_hk_futu_kline_enrichment_pair(
        candidate_bytes,
        expected_candidate_sha256=hashlib.sha256(candidate_bytes).hexdigest(),
        expected_input_baseline_sha256=_INPUT_BASELINE_SHA,
        expected_originals_by_stage=identities,
    )


def _bars(stage_id: str, *, code: str = "HK.00376") -> list[dict[str, object]]:
    expected, _cutoff = _expected_window_keys("20261012", stage_id)
    rows: list[dict[str, object]] = []
    if stage_id == "STAGE_1445_1500":
        # The canonical window starts at window_start + 1 minute. The 14:45
        # K_1M row exists in the provider response but is not aggregated.
        rows.append(
            {
                "code": code,
                "time_key": "2026-10-12 14:45:00",
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "close": 10.0,
                "volume": 1.0,
                "turnover": 10.0,
                "last_close": 500.0,
            }
        )
    for index, time_key in enumerate(expected):
        open_price = 10.0 + index / 100
        close_price = open_price + 0.01
        rows.append(
            {
                "code": code,
                "time_key": time_key,
                "open": open_price,
                "high": close_price + 0.02,
                "low": open_price - 0.02,
                "close": close_price,
                "volume": 100.0,
                "turnover": 1000.0,
                # Futu documents last_close as the preceding K line close;
                # stage return must continue to use stage open instead.
                "last_close": 999.0,
            }
        )
    return rows


def test_canonical_afternoon_aggregation_uses_existing_start_plus_one_contract():
    raw_rows = _bars("STAGE_1445_1500")

    summary, coverage = aggregate_code_window(
        trade_date="20261012",
        stage_id="STAGE_1445_1500",
        code="HK.00376",
        raw_rows=raw_rows,
    )

    assert summary["bar_count"] == 14
    assert summary["window_start"] == "2026-10-12 14:46:00"
    assert summary["window_end"] == "2026-10-12 14:59:00"
    assert summary["temporal_cutoff_safe"] is False
    assert coverage["vendor_bar_boundary_semantics"].startswith("CANNOT_CONFIRM")


def test_enrichment_reuses_card_formula_preserves_rank_pool_and_no_buy():
    raw_rows = _bars("STAGE_1300_1315")
    summary, _coverage = aggregate_code_window(
        trade_date="20261012",
        stage_id="STAGE_1300_1315",
        code="HK.00376",
        raw_rows=raw_rows,
    )
    original_row = {
        "code": "HK.00376",
        "rank": 7,
        "score": 51.0,
        "d1_rank": 8,
        "d1_score": 0.61,
        "action_level": "NO_BUY",
        "current_change_pct": None,
        "open_price": None,
        "last_price": 10.0,
        "high_price": None,
        "low_price": None,
        "support": None,
        "pressure": None,
        "invalidation": None,
        "support_primary_price": None,
        "pressure_price": None,
        "invalidation_price": None,
        "next_validation_time": "13:15:00",
    }
    original = deepcopy(original_row)
    envelope = {
        "trade_date": "20261012",
        "stage_id": "STAGE_1300_1315",
        "market": "HK_CONNECT",
        "run_id": "run-source-1300",
        "artifact_id": "selection-source-1300",
        "selection_status": "PARTIAL_WITH_ROWS",
        "source_status": "READY",
        "raw_artifact_sha256": "a" * 64,
        "algorithm_id": "V3_STAGE_SELECTION_V1",
        "algorithm_sha256": "b" * 64,
        "requested_rows": 100,
        "source_rows": 100,
        "selected_rows": 10,
        "coverage_ratio": 0.1,
        "missing_symbols": [],
        "rows": [original_row],
        "source_evidence": ["source=existing"],
        "cannot_confirm": ["FUTU_RT_DATA_OHLC_AND_ORDERBOOK_UNAVAILABLE"],
    }
    provenance = {
        "HK.00376": {"raw_sha256": "c" * 64, "receipt_sha256": "d" * 64}
    }

    overlay = enrich_stage_rows(
        envelope,
        {"HK.00376": summary},
        kline_provenance=provenance,
    )

    row = overlay["rows"][0]
    assert row["rank"] == original["rank"]
    assert row["score"] == original["score"]
    assert row["d1_rank"] == original["d1_rank"]
    assert row["d1_score"] == original["d1_score"]
    assert row["action_level"] == "NO_BUY"
    assert row["current_change_pct"] == pytest.approx(
        (summary["last_price"] / summary["open_price"] - 1) * 100, abs=0.0001
    )
    assert row["support"] == summary["low_price"]
    assert row["invalidation"] == summary["low_price"]
    assert row["pressure"] == summary["high_price"]
    assert overlay["requested_rows"] == 100
    assert overlay["raw_artifact_sha256"] == "a" * 64
    assert overlay["source_selection_run_id"] == "run-source-1300"
    assert overlay["pit_safe"] is False
    assert overlay["temporal_cutoff_safe"] is False
    assert overlay["formal_stage_eligibility"] == "CANNOT_CONFIRM"
    assert overlay["historical_orderbook_status"] == "CANNOT_CONFIRM_NO_CUTOFF_BOUND_SNAPSHOT"
    assert overlay["current_orderbook_queried"] is False
    assert AFTERFACT_CANNOT_CONFIRM in overlay["cannot_confirm"]
    assert ORDERBOOK_CANNOT_CONFIRM in overlay["cannot_confirm"]
    assert "FUTU_RT_DATA_OHLC_AND_ORDERBOOK_UNAVAILABLE" not in overlay["cannot_confirm"]


def test_incomplete_canonical_window_fails_closed_without_filling_missing_bar():
    raw_rows = _bars("STAGE_1300_1315")
    raw_rows = [row for row in raw_rows if row["time_key"] != "2026-10-12 13:14:00"]

    with pytest.raises(ValueError, match="incomplete canonical K_1M window"):
        aggregate_code_window(
            trade_date="20261012",
            stage_id="STAGE_1300_1315",
            code="HK.00376",
            raw_rows=raw_rows,
        )


def test_d1_pool_lineage_keeps_pool_hashes_separate_from_stage_raw_hash():
    envelope = {
        "raw_artifact_sha256": "a" * 64,
        "source_evidence": ["hk_d1_json_sha256=" + "b" * 64],
        "rows": [
            {
                "d1_source_evidence": [
                    "hk_d1_pool_version=hkconnect_d1_top100_pool.v3_vipdoc_panel",
                    "hk_d1_source_sha256=" + "c" * 64,
                ]
            },
            {
                "d1_source_evidence": [
                    "hk_d1_pool_version=hkconnect_d1_top100_pool.v3_vipdoc_panel",
                    "hk_d1_source_sha256=" + "c" * 64,
                ]
            },
        ],
    }

    assert d1_pool_lineage(envelope) == {
        "pool_version": "hkconnect_d1_top100_pool.v3_vipdoc_panel",
        "pool_source_sha256": "c" * 64,
        "pool_artifact_sha256": "b" * 64,
    }


def test_r5_pair_publication_is_atomic_and_read_back_through_existing_consumer(tmp_path, monkeypatch):
    store, _envelopes, identities, candidate = _publication_fixture(tmp_path)
    before = store._latest()
    original_runs = {
        stage_id: store._verify_run("20261012", stage_id, "HK_CONNECT", identities[stage_id]["run_id"])
        for stage_id in _R5_STAGES
    }
    latest_path_bytes = store.latest_path.read_bytes()
    outside_entries_before = {
        key: value
        for key, value in before["entries"].items()
        if not key.startswith("20261012/")
    }

    latest_writes = []
    atomic_write_json = selection_module._atomic_write_json

    def count_latest_pointer_writes(path, payload):
        if Path(path) == store.latest_path:
            latest_writes.append(payload)
        return atomic_write_json(path, payload)

    monkeypatch.setattr(selection_module, "_atomic_write_json", count_latest_pointer_writes)
    result = _publish_fixture_candidate(store, identities, candidate)

    assert len(latest_writes) == 1
    assert result["latest_updated_stages"] == list(_R5_STAGES)
    after = store._latest()
    assert {
        key: value for key, value in after["entries"].items() if not key.startswith("20261012/")
    } == outside_entries_before
    assert store.latest_path.read_bytes() != latest_path_bytes

    consumer = StageSelectionConsumer(store.root)
    for stage_id in _R5_STAGES:
        stage = candidate["stages"][stage_id]
        latest_key = store._key("20261012", stage_id, "HK_CONNECT")
        new_run_id = after["entries"][latest_key]["run_id"]
        assert new_run_id != identities[stage_id]["run_id"]
        old_run = store._verify_run("20261012", stage_id, "HK_CONNECT", identities[stage_id]["run_id"])
        assert old_run == original_runs[stage_id]

        response = consumer.get("20261012", stage_id, markets=("HK_CONNECT",))
        lane = response["markets"]["HK_CONNECT"]
        assert lane["run_id"] == new_run_id
        assert lane["selected_rows"] == 10
        assert [row["code"] for row in lane["rows"]] == [row["code"] for row in stage["rows"]]
        for actual, expected in zip(lane["rows"], stage["rows"]):
            assert actual["action_level"] == "NO_BUY"
            for field in ("current_change_pct", "support", "pressure", "invalidation"):
                assert actual[field] == expected[field]


@pytest.mark.parametrize("tamper,expected_error", [
    ("rank", "changed a frozen row field"),
    ("raw_sha", "candidate source identity differs"),
])
def test_r5_pair_publication_rejects_frozen_rank_or_raw_identity_tampering(
    tmp_path, tamper, expected_error
):
    store, _envelopes, identities, candidate = _publication_fixture(tmp_path)
    latest_before = store.latest_path.read_bytes()
    run_dirs_before = sorted(
        str(path.relative_to(store.runs_root))
        for path in (store.runs_root / "20261012").rglob("manifest.json")
    )
    changed_candidate = deepcopy(candidate)
    if tamper == "rank":
        changed_candidate["stages"]["STAGE_1300_1315"]["rows"][0]["rank"] += 1
    else:
        changed_candidate["source"]["stage_raw_artifact_sha256_by_stage"]["STAGE_1300_1315"] = "f" * 64
    candidate_bytes = _candidate_bytes(changed_candidate)

    with pytest.raises(SelectionError, match=expected_error):
        store.publish_hk_futu_kline_enrichment_pair(
            candidate_bytes,
            expected_candidate_sha256=hashlib.sha256(candidate_bytes).hexdigest(),
            expected_input_baseline_sha256=_INPUT_BASELINE_SHA,
            expected_originals_by_stage=identities,
        )

    assert store.latest_path.read_bytes() == latest_before
    assert sorted(
        str(path.relative_to(store.runs_root))
        for path in (store.runs_root / "20261012").rglob("manifest.json")
    ) == run_dirs_before


def test_r5_publication_sha_mismatch_fails_before_latest_or_run_changes(tmp_path):
    store, _envelopes, identities, candidate = _publication_fixture(tmp_path)
    latest_before = store.latest_path.read_bytes()
    run_dirs_before = sorted(
        str(path.relative_to(store.runs_root))
        for path in (store.runs_root / "20261012").rglob("manifest.json")
    )
    candidate_bytes = _candidate_bytes(candidate)

    with pytest.raises(SelectionError, match="candidate SHA"):
        store.publish_hk_futu_kline_enrichment_pair(
            candidate_bytes,
            expected_candidate_sha256="0" * 64,
            expected_input_baseline_sha256=_INPUT_BASELINE_SHA,
            expected_originals_by_stage=identities,
        )

    assert store.latest_path.read_bytes() == latest_before
    assert sorted(
        str(path.relative_to(store.runs_root))
        for path in (store.runs_root / "20261012").rglob("manifest.json")
    ) == run_dirs_before


def test_normal_selection_publish_still_fails_closed_on_existing_slot(tmp_path):
    store, envelopes, _identities, _candidate = _publication_fixture(tmp_path)
    latest_before = store.latest_path.read_bytes()
    changed = deepcopy(envelopes["STAGE_1300_1315"])
    changed.pop("run_id", None)
    changed.pop("artifact_id", None)
    changed["rows"][0]["rank"] += 1

    with pytest.raises(SelectionError, match="selection slot conflict"):
        store.publish(changed, market="HK_CONNECT")

    assert store.latest_path.read_bytes() == latest_before


def test_reviewed_cli_mode_does_not_call_provider_loader(tmp_path, monkeypatch, capsys):
    def unexpected_provider_call(*_args, **_kwargs):
        pytest.fail("reviewed publication mode must not load or query provider data")

    monkeypatch.setattr(enrichment_module, "load_provider_universe", unexpected_provider_call)
    monkeypatch.setattr(
        enrichment_module,
        "publish_reviewed_candidate",
        lambda **_kwargs: {"publication_mode": "ISOLATED_CANARY"},
    )

    status = enrichment_module.main(
        [
            "--selection-root", str(tmp_path / "selection"),
            "--input-baseline", str(tmp_path / "baseline.json"),
            "--expected-input-baseline-sha256", _INPUT_BASELINE_SHA,
            "--publish-reviewed-candidate",
            "--reviewed-candidate", str(tmp_path / "candidate.json"),
            "--expected-candidate-sha256", "f" * 64,
            "--expected-original-identities-json", json.dumps({stage: {} for stage in _R5_STAGES}),
            "--canary-only",
            "--canary-output-root", str(tmp_path / "canary"),
        ]
    )
    assert status == 0
    assert json.loads(capsys.readouterr().out)["publication_mode"] == "ISOLATED_CANARY"
