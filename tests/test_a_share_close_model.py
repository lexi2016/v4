from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from domains.a_share_close_model import build_close_model
from domains.a_share_review import validate_a_share_review
from infrastructure.a_share_review_store import AShareReviewStore
from ops.build_a_share_close_review import build_review_from_panel


def _rows(trade_date: str = "20260731") -> pd.DataFrame:
    rows = []
    specs = [
        ("强势板块", 12, 2.5),
        ("风险板块", 12, -7.0),
        ("中性板块", 12, 0.2),
    ]
    serial = 1
    for board, count, pct in specs:
        for offset in range(count):
            code = f"{serial:06d}.SZ"
            rows.append({
                "trade_date": trade_date,
                "ts_code": code,
                "name": f"样本{serial}",
                "pct_chg": pct + offset / 100,
                "amount": 100_000_000 + offset * 1_000_000,
                "bar_close_pos": 0.8,
                "tdx_industry_code": board,
                "tdx_industry_name": board,
            })
            serial += 1
    return pd.DataFrame(rows)


def test_deterministic_close_model_preserves_shadow_and_no_llm_boundaries() -> None:
    model = build_close_model(
        _rows(), "20260731", "REPLAY_RESEARCH_V1_20260731_001"
    )

    assert model["status"] == "INDEPENDENT_CLOSE_REVIEW_READY"
    assert model["producer_type"] == "DETERMINISTIC_PYTHON"
    assert model["semantic_model_call_count"] == 0
    assert model["semantic_model_status"] == "DISABLED_BY_V3_5_NO_LLM_PRODUCTION_RULE"
    assert model["board_rows"]
    assert model["anchor_role_rows"]
    assert model["shadow_watch_pool"]["core"] == []
    assert model["safety"]["SHADOW_ONLY"] is True
    assert model["safety"]["NO_BUY_GATE"] is True


def test_exact_date_panel_builds_native_review_and_keeps_external_input_read_only(
    tmp_path: Path,
) -> None:
    panel = tmp_path / "selector.parquet"
    _rows().to_parquet(panel, index=False)
    pointer = tmp_path / "CURRENT_SELECTOR_READY_PANEL.txt"
    pointer.write_text(str(panel), encoding="utf-8-sig")
    before = (pointer.read_bytes(), panel.read_bytes(), pointer.stat().st_mtime_ns, panel.stat().st_mtime_ns)

    result = build_review_from_panel(
        tmp_path / ".runtime" / "data",
        "20260731",
        panel_pointer=pointer,
    )
    review = result["review"]

    assert review["source_role"] == "V3_5_NATIVE_CLOSE_MODEL"
    assert review["model_review"]["review_date"] == "20260731"
    assert review["model_review"]["producer_type"] == "DETERMINISTIC_PYTHON"
    assert review["core_stocks"] == []
    assert review["mainlines"]
    assert review["observation_pool"]
    assert [row["task_id"] for row in review["close_chain"]["nodes"][:3]] == [
        "FUPAN_CLOSE_MATERIALS", "FUPAN_REVIEW_START", "FUPAN_A_SHARE_STRUCTURE"
    ]
    assert review["close_chain"]["nodes"][3]["status"] == "NOT_MATERIALIZED"
    assert review["close_chain"]["status"] == "PARTIAL_REVIEW"
    assert review["cannot_confirm"] == [
        "CANNOT_CONFIRM_TARGET_VIDEO_NOT_CONSUMED",
        "CANNOT_CONFIRM_STRICT_D0_1500_PANEL",
        "FORMAL_GENERALIZATION_PENDING",
    ]
    assert AShareReviewStore(tmp_path / ".runtime" / "data").read_review("20260731") == review
    assert before == (
        pointer.read_bytes(), panel.read_bytes(), pointer.stat().st_mtime_ns, panel.stat().st_mtime_ns
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda model: model.update(producer_type="LLM"),
        lambda model: model.update(semantic_model_call_count=1),
        lambda model: model["safety"].update(NO_BUY_GATE=False),
    ],
)
def test_a_share_review_rejects_llm_or_unsafe_model_as_production_data(
    tmp_path: Path, mutation,
) -> None:
    panel = tmp_path / "selector.parquet"
    _rows().to_parquet(panel, index=False)
    pointer = tmp_path / "pointer.txt"
    pointer.write_text(str(panel), encoding="utf-8")
    review = build_review_from_panel(
        tmp_path / "data", "20260731", panel_pointer=pointer
    )["review"]
    mutation(review["model_review"])

    with pytest.raises(ValueError, match="model"):
        validate_a_share_review(review)
