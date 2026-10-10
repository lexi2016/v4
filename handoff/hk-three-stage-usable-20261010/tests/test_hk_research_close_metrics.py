from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


E5_ROOT = Path(__file__).resolve().parents[2]
ACTIVE_APP = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_HK_0920_ACTUAL_BACKFILL_20261010/"
    "integrated_release/hk-0920-open-substitute-20261010-r1/app"
)
DOMAIN_PATH = E5_ROOT / "candidate/domains/close_review.py"
BASELINE_PATH = E5_ROOT / "integration/CLOSE_BEFORE.json"

sys.path.insert(0, str(ACTIVE_APP))
_spec = importlib.util.spec_from_file_location("e5_candidate_close_review", DOMAIN_PATH)
assert _spec is not None and _spec.loader is not None
_domain = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_domain)


def test_actual_20261009_research_rows_recompute_coverage_without_formal_upgrade():
    response = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    source = response["market_reviews"]["HK"]["model_selection_review"]
    observed_model = source["models"]["observed_0.2_prob_active"]
    close_rows = [
        {
            "code": row["code"],
            "name": row.get("name", ""),
            "trade_date": "20261009",
            "close": row["close"],
            "pre_close": row["pre_close"],
            "amount": row.get("amount", 0),
        }
        for row in source["close_top20"]
    ]
    model_rows = [
        {"market": "HK", "code": code, "target_date": "20261009", "rank": rank}
        for rank, code in enumerate(observed_model["selected_codes"], start=1)
    ]
    stage_rows = {stage_id: [] for stage_id in _domain._REVIEW_STAGE_IDS}
    for row in source["stage_rows"]:
        stage_rows[row["stage_id"]].append(
            {
                "market": "HK",
                "code": row["code"],
                "name": row.get("name", ""),
                "trade_date": "20261009",
            }
        )
    run_ids = source["observed_stage_union"]["backfill_run_ids"]
    stage_evidence = {
        stage_id: {
            "selection_mode": "BACKFILL",
            "backfill_run_id": run_ids[index],
            "cannot_confirm": [f"BACKFILL_STAGE_RESEARCH_ONLY:{stage_id}"],
        }
        for index, stage_id in enumerate(_domain._REVIEW_STAGE_IDS)
    }

    result = _domain.build_native_close_review(
        "20261009",
        close_rows=close_rows,
        model_rows=[],
        stage_rows=stage_rows,
        stage_evidence=stage_evidence,
        observed_model_rows=model_rows,
        observed_model_evidence={
            "score_rows": observed_model["score_rows"],
            "unique_score_codes": observed_model["unique_score_codes"],
            "candidate_status": observed_model["candidate_status"],
            "cannot_confirm": observed_model["cannot_confirm"],
        },
        close_source_sha256=source["close_source_sha256"],
    )

    observed_model_result = result["models"]["observed_0.2_prob_active"]
    observed_stage_result = result["observed_stage_union"]
    assert observed_model_result["selected_count"] == 100
    assert observed_model_result["hit_count"] == 10
    assert observed_model_result["evidence_status"] == "PARTIAL_RESEARCH_ONLY"
    assert observed_model_result["hit_count"] / 20 * 100 == 50.0
    assert observed_stage_result["stage_ids"] == list(_domain._REVIEW_STAGE_IDS)
    assert observed_stage_result["expected_stage_count"] == 7
    assert observed_stage_result["selected_count"] == 32
    assert observed_stage_result["hit_count"] == 6
    assert observed_stage_result["evidence_status"] == "PARTIAL_RESEARCH_ONLY"
    assert observed_stage_result["hit_count"] / 20 * 100 == 30.0
    assert result["row_counts"]["stage_rows"] == 70
    assert result["models"]["0.2_prob_active"]["evidence_status"] == "MISSING"
    assert result["stage_union"]["evidence_status"] == "MISSING"
    assert result["status"] == "MODEL_REVIEW_RESEARCH_AVAILABLE_FORMAL_UNVERIFIED"
    assert not any("MODEL_0_2_TOP100_NOT_READY" in item for item in result["cannot_confirm"])
    assert any("FORMAL_MODEL_0_2_UNVERIFIED" in item for item in result["cannot_confirm"])
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False
