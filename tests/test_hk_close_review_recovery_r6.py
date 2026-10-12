from __future__ import annotations

from domains.close_review import _REVIEW_STAGE_IDS, build_native_close_review
from apps.api.v35_api.review_router import _project_hk_review


def test_same_date_formal_model_stays_formal_while_partial_stage_rows_stay_research_only() -> None:
    trade_date = "20261012"
    close_rows = [
        {
            "trade_date": trade_date,
            "code": f"HK.{index:05d}",
            "name": f"Close {index}",
            "close": 100 + index,
            "pre_close": 100,
            "amount": 1_000 + index,
        }
        for index in range(1, 21)
    ]
    model_codes = list(range(1, 9)) + list(range(21, 113))
    model_rows = [
        {
            "target_date": trade_date,
            "market": "HK",
            "symbol": f"HK.{code:05d}",
            "pool_rank": rank,
            "stock_name": f"Model {code}",
        }
        for rank, code in enumerate(model_codes, start=1)
    ]
    observed_codes = list(range(1, 7)) + list(range(21, 39))
    stage_rows = {
        stage_id: [
            {
                "market": "HK",
                "code": f"HK.{observed_codes[(stage_index * 3 + row_index) % len(observed_codes)]:05d}",
                "name": f"Stage {stage_index}-{row_index}",
            }
            for row_index in range(10)
        ]
        for stage_index, stage_id in enumerate(_REVIEW_STAGE_IDS)
    }
    stage_evidence = {
        stage_id: {
            "status": "PARTIAL_WITH_ROWS",
            "run_id": f"run-{stage_index}",
            "cannot_confirm": (
                ["HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE"]
                if stage_index
                else []
            ),
        }
        for stage_index, stage_id in enumerate(_REVIEW_STAGE_IDS)
    }

    result = build_native_close_review(
        trade_date,
        close_rows=close_rows,
        model_rows=model_rows,
        stage_rows=stage_rows,
        close_source_sha256="a" * 64,
        stage_evidence=stage_evidence,
    )

    assert result["RESEARCH_ONLY"] is True
    formal_model = result["models"]["0.2_prob_active"]
    assert formal_model["evidence_status"] == "READY"
    assert formal_model["selected_count"] == 100
    assert formal_model["hit_count"] == 8
    assert "observed_0.2_prob_active" not in result["models"]

    assert result["status"] == "MODEL_REVIEW_PARTIAL_STAGE_EVIDENCE"
    assert result["missing_stages"] == []
    assert result["unverified_stages"] == list(_REVIEW_STAGE_IDS)
    assert result["row_counts"]["close_top20"] == 20
    assert result["row_counts"]["model_0_2"] == 100
    assert result["row_counts"]["stage_rows"] == 70
    assert result["stage_union"]["evidence_status"] == "MISSING"
    assert result["stage_union"]["selected_count"] is None
    assert result["stage_union"]["hit_count"] is None

    observed = result["observed_stage_union"]
    assert observed["evidence_status"] == "PARTIAL_RESEARCH_ONLY"
    assert observed["RESEARCH_ONLY"] is True
    assert observed["research_only"] is True
    assert observed["selected_count"] == 24
    assert observed["hit_count"] == 6
    assert observed["stage_ids"] == list(_REVIEW_STAGE_IDS)
    assert observed["expected_stage_count"] == 7
    assert observed["recommendation_status"] == "NO_BUY"
    assert observed["pit_status"] == "UNVERIFIED"
    assert "UNVERIFIED_STAGE:STAGE_1300_1315" in observed["cannot_confirm"]
    assert "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE" in observed["cannot_confirm"]

    first_top20 = next(
        row for row in result["top20_attribution"] if row["code"] == "HK.00001"
    )
    assert first_top20["model_0_2_hit"] is True
    assert first_top20["stage_union_hit"] is None
    assert first_top20["classification"] is None
    assert first_top20["observed_stage_union_hit"] is True
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False


def test_partial_stage_union_keeps_research_only_safety_fields() -> None:
    trade_date = "20261012"
    stage_id = _REVIEW_STAGE_IDS[0]
    result = build_native_close_review(
        trade_date,
        close_rows=[
            {
                "trade_date": trade_date,
                "code": f"HK.{index:05d}",
                "close": 100 + index,
                "pre_close": 100,
                "amount": index,
            }
            for index in range(1, 21)
        ],
        model_rows=[
            {
                "target_date": trade_date,
                "market": "HK",
                "symbol": f"HK.{index:05d}",
                "pool_rank": index,
            }
            for index in range(1, 101)
        ],
        stage_rows={
            item: ([{"market": "HK", "code": "HK.00001"}] if item == stage_id else None)
            for item in _REVIEW_STAGE_IDS
        },
        close_source_sha256="b" * 64,
        stage_evidence={stage_id: {"status": "READY", "cannot_confirm": []}},
    )

    assert result["stage_union"]["evidence_status"] == "MISSING"
    observed = result["observed_stage_union"]
    assert observed["evidence_status"] == "PARTIAL_RESEARCH_ONLY"
    assert observed["RESEARCH_ONLY"] is True
    assert observed["research_only"] is True
    assert observed["recommendation_status"] == "NO_BUY"
    assert observed["pit_status"] == "UNVERIFIED"
    assert observed["production_allowed"] is False
    assert observed["buy_gate_updated"] is False
    assert observed["orders_sent"] is False


def test_hk_review_projection_preserves_partial_observation_contract_fields() -> None:
    observed = {
        "evidence_status": "PARTIAL_RESEARCH_ONLY",
        "selected_count": 24,
        "selected_codes": [f"HK.{index:05d}" for index in range(1, 25)],
        "hit_count": 6,
        "hit_codes": [f"HK.{index:05d}" for index in range(1, 7)],
        "stage_ids": list(_REVIEW_STAGE_IDS),
        "expected_stage_count": 7,
        "RESEARCH_ONLY": True,
        "recommendation_status": "NO_BUY",
        "pit_status": "UNVERIFIED",
        "research_only": True,
        "cannot_confirm": ["UNVERIFIED_STAGE:STAGE_1300_1315"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    artifact = {
        "schema_version": "v3_5.close_review.v1",
        "trade_date": "20261012",
        "status": "PARTIAL",
        "models": {
            "0.2_prob_active": {
                "evidence_status": "READY",
                "selected_count": 100,
                "hit_count": 8,
            },
        },
        "stage_union": {"evidence_status": "MISSING", "selected_count": None, "hit_count": None},
        "observed_stage_union": observed,
        "row_counts": {"close_top20": 20, "model_0_2": 100, "stage_rows": 70},
        "missing_stages": [],
        "unverified_stages": list(_REVIEW_STAGE_IDS),
        "stage_input_evidence": {"STAGE_1300_1315": {"status": "PARTIAL_WITH_ROWS"}},
        "close_top20": [],
        "top20_attribution": [],
        "cannot_confirm": ["UNVERIFIED_STAGE:STAGE_1300_1315"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }

    projected = _project_hk_review(
        "20261012",
        {
            "trade_date": "20261012",
            "role": "HK_CLOSE_REVIEW_V1",
            "status": "PARTIAL",
            "artifact": artifact,
            "artifact_sha256": "b" * 64,
            "cannot_confirm": [],
        },
    )

    assert projected["models"]["0.2_prob_active"]["selected_count"] == 100
    assert projected["models"]["0.2_prob_active"]["hit_count"] == 8
    assert projected["stage_union"]["evidence_status"] == "MISSING"
    assert projected["observed_stage_union"] == observed
    assert projected["row_counts"]["stage_rows"] == 70
    assert projected["unverified_stages"] == list(_REVIEW_STAGE_IDS)
    assert projected["stage_input_evidence"]["STAGE_1300_1315"]["status"] == "PARTIAL_WITH_ROWS"
