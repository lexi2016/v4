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
    assert default["counts"]["watch"] == 2  # Counts include the factor candidate row.
    assert default["counts"]["not_selected"] == 0  # same HK stock has a positive saved representative
    assert default["recommendation_projection"]["distinct_hk_count"] == 2
    assert default["recommendation_projection"]["row_count"] == 3
    assert default["recommendation_projection"]["count_unit"] == "SAVED_LANE_RESEARCH_ROWS"
    assert default["recommendation_projection"]["factor_stock_count"] == 2

    negatives = lane_projection(snapshot, "US_MAPPING", {}, "NOT_SELECTED")
    assert len(negatives["stocks"]) == 1
    assert negatives["stocks"][0]["subtype"] == "US_DAILY_RETURN_FACTOR_CANDIDATE"

    summarized = us_summary(snapshot, {})
    assert summarized["source_symbol_count"] == 1
    assert summarized["source_row_count"] == 1
    assert summarized["factor_summary"]["unique_factor_stock_count"] == 2


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
    snapshot = NS(context=NS(rules_version="TEST_RULES", scope_refs={}), lanes=[lane], stocks=[], run_id="catalog-run")

    projection = lane_projection(snapshot, "US_MAPPING", {})
    summary = us_summary(snapshot, {})

    assert projection["recommendation_projection"]["row_count"] == 1
    assert projection["recommendation_projection"]["catalog_relation_row_count"] == 2
    assert projection["recommendation_projection"]["catalog_stock_count"] == 2
    assert projection["stocks"] == []
    assert summary["source_row_count"] == 1
    assert summary["relation_row_count"] == 1
    assert summary["mapped_hk_count"] == 1
    assert summary["catalog_summary"]["displayed_relation_count"] == 2
    assert summary["catalog_summary"]["relation_count"] == 2


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
    assert data['counts'] == {
        'selected': 0, 'watch': 3, 'unassessed': 5, 'not_selected': 13, 'observation_only': 0,
    }
    assert data['pagination']['total'] == 3
    assert [(row['symbol'], row['decision'], row.get('subtype')) for row in data['stocks']] == [
        ('HK.09988', 'CONDITIONAL_WATCH', None),
        ('HK.00300', 'CONDITIONAL_WATCH', 'US_DAILY_RETURN_FACTOR_CANDIDATE'),
        ('HK.00668', 'CONDITIONAL_WATCH', 'US_DAILY_RETURN_FACTOR_CANDIDATE'),
    ]
    projection = data['recommendation_projection']
    assert projection['count_unit'] == 'SAVED_LANE_RESEARCH_ROWS'
    assert projection['row_count'] == 48
    assert sum(data['counts'].values()) == projection['candidate_stock_count']  # deduplicated HK stocks, source rows retained below
    assert projection['hk_relation_row_count'] == 14
    assert projection['factor_stock_count'] == 11
    assert projection['source_only_row_count'] == 23
    assert projection['distinct_hk_count'] == 21
    assert data['us_mapping_summary']['factor_summary']['factor_decision_counts'] == {
        'CONDITIONAL_WATCH': 2, 'NOT_SELECTED': 5, 'SELECTED': 0, 'UNASSESSED': 4,
    }
    assert hashlib.sha256(DEPLOYED.read_bytes()).hexdigest() == saved_sha
