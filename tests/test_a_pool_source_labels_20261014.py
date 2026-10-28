from copy import deepcopy

from domains.preselection import _dedupe_by_symbol


def test_research_overlap_keeps_both_sources_without_changing_ranking():
    rows = [
        {"symbol": "A.000679", "market": "A", "stock_name": "大连友谊",
         "pool_id": "a_d1_premarket_pool", "pool_rank": 2, "pool_score": 112},
        {"symbol": "A.000679", "market": "A", "stock_name": "大连友谊",
         "pool_id": "a_share_research_recommendation_pool", "pool_rank": 8, "pool_score": 7},
        {"symbol": "A.603992", "market": "A", "stock_name": "松霖科技",
         "pool_id": "a_d1_stage7_fenshi_review_pool"},
    ]
    before = deepcopy(rows)
    result = _dedupe_by_symbol(rows)
    assert len(result) == 2
    assert result[0]["source_tags"] == "（选） / （研）"
    assert result[0]["source_lanes"] == "selector_lane / research_lane"
    assert result[0]["pool_rank"] == 2 and result[0]["pool_score"] == 112
    assert result[1]["source_tags"] == "（分）"
    assert rows == before


def test_research_only_stock_remains_identifiable_beyond_first_page():
    rows = [{"symbol": f"A.{i:06d}", "market": "A", "stock_name": str(i),
             "pool_id": "a_share_research_recommendation_pool"} for i in range(1, 251)]
    result = _dedupe_by_symbol(rows)
    assert len(result) == 250
    assert result[249]["source_tags"] == "（研）"
    assert result[249]["display_name"] == "250（研）"
