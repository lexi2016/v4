import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from v4.manager_workbench.api import create_router
from v4.manager_workbench.contracts import PlanSnapshot
from v4.manager_workbench.display_read import lane_projection, us_summary
from v4.manager_workbench.engines.common import US_FACTOR_RULES_VERSION

DEPLOYED = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_workbench/manager_workbench/snapshots/b9859a3e49aa40929a4db98976a51ae3.json')


def test_factor_projection_keeps_one_stock_and_preserves_relation_path():
    relation = dict(symbol="HK.09660", name=None, us_symbol="DRIV", decision="CONDITIONAL_WATCH",
        reason="US_REVIEWED_RELATION_CONDITIONAL_ONLY", membership={"eligible": True}, evidence_ids=["relation"])
    negative_factor = dict(symbol="HK.09660", name=None, subtype="US_DAILY_RETURN_FACTOR_CANDIDATE",
        decision="NOT_SELECTED", reason="US_FACTOR_ALL_REVIEWED_PATHS_NOT_POSITIVE",
        membership={"eligible": True}, evidence_ids=["factor"], factor_paths=[dict(theme="自动驾驶", return_pct="-1.0")])
    positive_factor = dict(symbol="HK.09926", name=None, subtype="US_DAILY_RETURN_FACTOR_CANDIDATE",
        decision="CONDITIONAL_WATCH", reason="US_FACTOR_AT_LEAST_ONE_REVIEWED_POSITIVE_PATH",
        membership={"eligible": True}, evidence_ids=["factor"], factor_paths=[dict(theme="生物医药", return_pct="2.0")])
    summary = dict(display_only=True, rules_version=US_FACTOR_RULES_VERSION, target_date="20261013", phase="RETROSPECTIVE",
        us_source_symbol_count=33, proxy_source_count=24, expected_proxy_source_count=24,
        verified_proxy_source_count=24, unknown_proxy_source_count=0, eligible_hk_scope_count=692,
        unique_factor_stock_count=2, factor_path_count=2, unknown_factor_stock_count=0,
        factor_decision_counts={"CONDITIONAL_WATCH": 1, "NOT_SELECTED": 1, "UNASSESSED": 0},
        paired_review_available=True, source_session="20261012", historical_pit_verified=False,
        combined_source_and_stock_count=None)
    rows = [relation, negative_factor, positive_factor]
    rows[0]["us_factor_summary"] = summary
    lane = NS(lane=NS(value="US_MAPPING"), rows=rows, gaps=[], state=NS(value="READY"),
        coverage=NS(model_dump=lambda **kwargs: {"scope_count": 33}))
    snapshot = NS(context=NS(rules_version=US_FACTOR_RULES_VERSION), lanes=[lane], stocks=[], run_id="run-factor")

    default = lane_projection(snapshot, "US_MAPPING", {})
    assert [(stock["symbol"], stock.get("subtype")) for stock in default["stocks"]] == [
        ("HK.09660", None), ("HK.09926", "US_DAILY_RETURN_FACTOR_CANDIDATE")]
    assert default["counts"]["watch"] == 2  # One candidate stock decision per HK code.
    assert default["counts"]["not_selected"] == 0
    assert default["recommendation_projection"]["source_decision_counts"] == {
        "selected": 0, "watch": 2, "unassessed": 0, "not_selected": 1, "observation_only": 0,
    }
    assert default["recommendation_projection"]["distinct_hk_count"] == 2
    assert default["recommendation_projection"]["row_count"] == 3
    assert default["recommendation_projection"]["count_unit"] == "SAVED_LANE_RESEARCH_ROWS"
    assert default["recommendation_projection"]["recommendation_count_unit"] == "DEDUPLICATED_HK_CANDIDATE_STOCKS"
    assert default["recommendation_projection"]["candidate_stock_count"] == 2
    assert default["recommendation_projection"]["factor_stock_count"] == 2

    negatives = lane_projection(snapshot, "US_MAPPING", {}, "NOT_SELECTED")
    assert len(negatives["stocks"]) == 1
    assert negatives["stocks"][0]["subtype"] == "US_DAILY_RETURN_FACTOR_CANDIDATE"
    assert negatives["counts"] == default["counts"]
    assert negatives["recommendation_projection"]["source_decision_counts"] == default["recommendation_projection"]["source_decision_counts"]

    summarized = us_summary(snapshot, {})
    assert summarized["source_symbol_count"] == 1
    assert summarized["source_row_count"] == 1
    assert summarized["factor_summary"]["unique_factor_stock_count"] == 2


def test_industry_candidate_projection_keeps_48_legacy_counts_and_all_698_candidates_separate():
    legacy_rows = []
    for index in range(48):
        decision = "CONDITIONAL_WATCH" if index < 3 else "UNASSESSED" if index < 31 else "NOT_SELECTED"
        legacy_rows.append(dict(symbol=f"HK.{index + 1:05d}", name=f"旧来源 {index + 1}", decision=decision,
            reason="SYNTHETIC_LEGACY_ROW", membership={"eligible": True}, evidence_ids=[f"legacy-{index}"]))
    industry_codes = ["HK.00300", *[f"HK.{90000 + index:05d}" for index in range(1, 698)]]
    industry_rows = []
    for index, symbol in enumerate(industry_codes):
        industry_rows.append(dict(symbol=symbol, name=f"合成发行人 {index}",
            subtype="HK_INDUSTRY_PROXY_FACTOR_CANDIDATE",
            decision="CONDITIONAL_WATCH" if index == 0 else "UNASSESSED",
            reason="SYNTHETIC_INDUSTRY_ROW", source_industry="家庭电器及用品" if index == 0 else None,
            theme="消费" if index == 0 else None, return_pct="1.50" if index == 0 else None,
            mapping_type="EXACT_PROVIDER_INDUSTRY" if index == 0 else None,
            identity_status="VERIFIED" if index < 697 else "UNASSESSED_IDENTITY",
            membership={"eligible": True}, evidence_ids=[f"industry-{index}"]))
    industry_summary = dict(scope_count=698, identity_resolved_count=697, identity_gap_count=1,
        identity_gap_symbols=[industry_codes[-1]], identity_gap="HK_SECURITY_MASTER_IDENTITY_SCOPE_GAP",
        security_master_scope_count=697, bad_row_count=0, classified_count=2, mapping_covered_count=1,
        industry_unmapped_count=1, classification_missing_count=696, triggered_unique_stock_count=1,
        unknown_unique_stock_count=697, candidate_row_count=1,
        decision_counts={"CONDITIONAL_WATCH": 1, "NOT_SELECTED": 0, "UNASSESSED": 697})
    factor_summary = dict(display_only=True, rules_version=US_FACTOR_RULES_VERSION,
        unique_factor_stock_count=0, factor_path_count=0, industry_summary=industry_summary)
    legacy_rows[0]["us_factor_summary"] = factor_summary
    lane = NS(lane=NS(value="US_MAPPING"), rows=[*legacy_rows, *industry_rows], gaps=[], state=NS(value="PARTIAL"),
        coverage=NS(model_dump=lambda **kwargs: {"scope_count": 33}))
    snapshot = NS(context=NS(rules_version=US_FACTOR_RULES_VERSION), lanes=[lane], stocks=[], run_id="industry-run")

    result = lane_projection(snapshot, "US_MAPPING", {})
    projection = result["recommendation_projection"]
    assert projection["row_count"] == 48
    assert projection["count_unit"] == "SAVED_LANE_RESEARCH_ROWS"
    assert projection["recommendation_count_unit"] == "DEDUPLICATED_HK_CANDIDATE_STOCKS"
    assert projection["candidate_stock_count"] == 746
    assert projection["industry_candidate_row_count"] == 698
    assert projection["industry_candidate_stock_count"] == 1
    assert projection["industry_scope_count"] == 698
    assert result["counts"]["selected"] == 0 and result["counts"]["watch"] == 4
    assert result["counts"]["unassessed"] == 725 and result["counts"]["not_selected"] == 17
    assert sum(result["counts"].values()) == projection["candidate_stock_count"] == 746
    assert projection["source_decision_counts"] == {
        "selected": 0, "watch": 3, "unassessed": 28, "not_selected": 17, "observation_only": 0,
    }
    assert projection["source_decision_count_unit"] == "SAVED_LANE_RESEARCH_ROWS"
    assert len(result["stocks"]) == 4
    assert sum(row.get("subtype") == "HK_INDUSTRY_PROXY_FACTOR_CANDIDATE" for row in result["stocks"]) == 1
    inspection = lane_projection(snapshot, "US_MAPPING", {}, "UNASSESSED")
    assert len(inspection["stocks"]) == 725
    assert sum(row.get("subtype") == "HK_INDUSTRY_PROXY_FACTOR_CANDIDATE" for row in inspection["stocks"]) == 697
    assert inspection["counts"] == result["counts"]


def test_candidate_counts_preserve_positive_representative_and_prefer_specific_unknown_fallback():
    rows = [
        dict(symbol="HK.00001", decision="CONDITIONAL_WATCH", reason="SAVED_RELATION_WATCH"),
        dict(symbol="HK.00001", subtype="HK_INDUSTRY_PROXY_FACTOR_CANDIDATE",
            decision="UNASSESSED", reason="HIGHER_PRIORITY_UNKNOWN_ROW"),
        dict(symbol="HK.00002", decision="NOT_SELECTED", reason="SAVED_RELATION_NEGATIVE"),
        dict(symbol="HK.00002", subtype="HK_INDUSTRY_PROXY_FACTOR_CANDIDATE",
            decision="UNASSESSED", reason="HIGHER_PRIORITY_UNKNOWN_ROW"),
    ]
    lane = NS(lane=NS(value="US_MAPPING"), rows=rows, gaps=[], state=NS(value="PARTIAL"),
        coverage=NS(model_dump=lambda **kwargs: {"scope_count": 48}))
    snapshot = NS(context=NS(rules_version=US_FACTOR_RULES_VERSION, scope_refs={}),
        lanes=[lane], stocks=[], run_id="candidate-count-priority-run")

    result = lane_projection(snapshot, "US_MAPPING", {})

    assert [(row["symbol"], row["reason"]) for row in result["stocks"]] == [
        ("HK.00001", "SAVED_RELATION_WATCH")
    ]
    assert result["counts"] == {"selected": 0, "watch": 1, "unassessed": 1,
        "not_selected": 0, "observation_only": 0}
    assert result["recommendation_projection"]["source_decision_counts"] == {
        "selected": 0, "watch": 1, "unassessed": 0, "not_selected": 1, "observation_only": 0,
    }


def test_catalog_observations_stay_out_of_candidate_display_counts():
    candidate = dict(symbol="HK.09961", us_symbol="TCOM", decision="UNASSESSED",
        record_role="SOURCE_CANDIDATE", reason="CONNECT_MEMBERSHIP_TARGET_EFFECTIVE_PERIOD_UNCONFIRMED")
    catalog_rows = [
        dict(symbol="HK.09961", us_symbol=None, decision="UNASSESSED", record_role="CATALOG_OBSERVATION",
            catalog_relation_id="catalog-1"),
        dict(symbol="HK.00780", us_symbol=None, decision="UNASSESSED", record_role="CATALOG_OBSERVATION",
            catalog_relation_id="catalog-2"),
    ]
    lane_rows = [candidate, *catalog_rows]
    lane_rows[0]["us_mapping_catalog_summary"] = dict(state="READY", stock_count=2,
        relation_count=2, consumed_relation_count=2)
    lane = NS(lane=NS(value="US_MAPPING"), rows=lane_rows, gaps=[], state=NS(value="PARTIAL"),
        coverage=NS(model_dump=lambda **kwargs: {"scope_count": 48}))
    snapshot = NS(context=NS(rules_version=US_FACTOR_RULES_VERSION, scope_refs={}), lanes=[lane], stocks=[], run_id="catalog-run")

    projection = lane_projection(snapshot, "US_MAPPING", {})
    summary = us_summary(snapshot, {})

    assert projection["recommendation_projection"]["row_count"] == 1
    assert projection["recommendation_projection"]["catalog_relation_row_count"] == 2
    assert projection["recommendation_projection"]["catalog_stock_count"] == 2
    assert projection["recommendation_projection"]["candidate_stock_count"] == 1
    assert projection["counts"] == {"selected": 0, "watch": 0, "unassessed": 1,
        "not_selected": 0, "observation_only": 0}
    assert projection["stocks"] == []
    assert summary["source_row_count"] == 1
    assert summary["relation_row_count"] == 1
    assert summary["mapped_hk_count"] == 1
    assert summary["catalog_summary"]["displayed_relation_count"] == 2
    assert summary["catalog_summary"]["relation_count"] == 2


def test_directional_proxy_lists_use_all_industry_rows_and_never_treat_nonselection_as_downside():
    member = dict(status="VERIFIED_MONTHLY_OBSERVATION", in_monthly_universe=True,
        market="HK_CONNECT", source_date="20261012", source_sha256="a" * 64,
        codes_sha256="b" * 64, target_month="202610")
    def candidate(symbol, decision, paths, *, identity="VERIFIED", industry="药品及生物科技"):
        return dict(symbol=symbol, name=f"样本 {symbol}", subtype="HK_INDUSTRY_PROXY_FACTOR_CANDIDATE",
            decision=decision, reason="SAVED_DECISION_REASON", source_industry=industry,
            identity_status=identity, research_membership=dict(member), target_eligibility={
                "status": "CANNOT_CONFIRM", "eligible": None,
            }, historical_pit_verified=False, proxy_paths=paths)
    def path(theme, direction, change, *, session="20261016", status="VERIFIED"):
        return dict(theme=theme, proxy_symbols=["XBI"], direction=direction,
            return_pct=change, source_session=session, status=status, reason=f"VERIFIED_PROXY_RETURN_{direction}")
    mixed = candidate("HK.00001", "CONDITIONAL_WATCH", [
        path("生物医药", "UPSIDE", "1.2"), path("半导体", "DOWNSIDE", "-0.8")])
    negative = candidate("HK.00002", "NOT_SELECTED", [path("生物医药", "DOWNSIDE", "-2.0")])
    flat = candidate("HK.00003", "NOT_SELECTED", [path("生物医药", "FLAT", "0")])
    unknown = candidate("HK.00004", "UNASSESSED", [path("银行金融", "UNASSESSED", None, status="UNASSESSED")])
    identity_gap = candidate("HK.00005", "UNASSESSED", [path("生物医药", "UPSIDE", "3.0")], identity="UNASSESSED_IDENTITY")
    rows = [mixed, negative, flat, unknown, identity_gap]
    industry_summary = dict(target_date="20261020", mapping_version="HK_ISSUER_INDUSTRY_TO_US_PROXY_THEME_V2",
        scope_count=5, monthly_research_code_count=5, monthly_research_source_date="20261012",
        monthly_research_source_sha256="c" * 64, monthly_research_codes_sha256="d" * 64,
        formal_target_eligibility="CANNOT_CONFIRM")
    rows[0]["us_factor_summary"] = dict(industry_summary=industry_summary)
    lane = NS(lane=NS(value="US_MAPPING"), rows=rows, gaps=[], state=NS(value="PARTIAL"),
        coverage=NS(model_dump=lambda **kwargs: {"scope_count": 48}))
    snapshot = NS(context=NS(rules_version=US_FACTOR_RULES_VERSION, scope_refs={},
        source_sessions={"US": "20261016"}), lanes=[lane], stocks=[], run_id="directional-run")

    data = us_summary(snapshot, {})["directional_proxy_lists"]

    assert data["source_session"] == "20261016"
    assert data["monthly_observed_scope_count"] == 5
    assert data["upside_stock_count"] == 1
    assert data["downside_stock_count"] == 2
    assert data["mixed_stock_count"] == 1
    assert data["flat_stock_count"] == 1
    assert data["unassessed_stock_count"] == 2
    assert [row["symbol"] for row in data["lists"]["upside"]] == ["HK.00001"]
    assert [row["symbol"] for row in data["lists"]["downside"]] == ["HK.00001", "HK.00002"]
    assert [row["symbol"] for row in data["lists"]["flat"]] == ["HK.00003"]
    assert {row["symbol"] for row in data["lists"]["unassessed"]} == {"HK.00004", "HK.00005"}
    assert all(row["target_eligibility"]["status"] == "CANNOT_CONFIRM"
        for key in ("upside", "downside", "flat", "unassessed") for row in data["lists"][key])



def test_deployed_snapshot_counts_all_lane_research_rows():
    if not DEPLOYED.exists():
        pytest.skip("The deployed formal snapshot is local-only; raw data is not uploaded")
    raw = DEPLOYED.read_bytes()
    saved_sha = hashlib.sha256(raw).hexdigest()
    snapshot = PlanSnapshot.model_validate(json.loads(raw))
    store = NS(get_plan=lambda *args, **kwargs: snapshot, list_plans=lambda *args: [snapshot])
    service = NS(store=store, config=NS(shared_root=None))
    app = FastAPI()
    app.include_router(create_router(service))
    client = TestClient(app)

    response = client.get(
        '/api/v4/manager-workbench/days/20261013/recommendations/US_MAPPING',
        params={'run_id': 'b9859a3e49aa40929a4db98976a51ae3'},
    )
    assert response.status_code == 200
    data = response.json()['data']
    assert data['counts']['selected'] == 0
    assert data['counts']['watch'] == 3
    assert data['pagination']['total'] == 3
    assert [(row['symbol'], row['decision'], row.get('subtype')) for row in data['stocks']] == [
        ('HK.09988', 'CONDITIONAL_WATCH', None),
        ('HK.00300', 'CONDITIONAL_WATCH', 'US_DAILY_RETURN_FACTOR_CANDIDATE'),
        ('HK.00668', 'CONDITIONAL_WATCH', 'US_DAILY_RETURN_FACTOR_CANDIDATE'),
    ]
    projection = data['recommendation_projection']
    assert projection['count_unit'] == 'SAVED_LANE_RESEARCH_ROWS'
    assert projection['row_count'] == 48
    assert projection['recommendation_count_unit'] == 'DEDUPLICATED_HK_CANDIDATE_STOCKS'
    assert sum(data['counts'].values()) == projection['candidate_stock_count']
    assert data['recommendation_counts']['US_MAPPING'] == data['counts']
    assert projection['source_decision_counts'] == {
        'selected': 0, 'watch': 3, 'unassessed': 28, 'not_selected': 17, 'observation_only': 0,
    }
    assert projection['hk_relation_row_count'] == 14
    assert projection['factor_stock_count'] == 11
    assert projection['source_only_row_count'] == 23
    assert projection['distinct_hk_count'] == 21
    assert data['us_mapping_summary']['factor_summary']['factor_decision_counts'] == {
        'CONDITIONAL_WATCH': 2, 'NOT_SELECTED': 5, 'SELECTED': 0, 'UNASSESSED': 4,
    }
    assert hashlib.sha256(DEPLOYED.read_bytes()).hexdigest() == saved_sha
