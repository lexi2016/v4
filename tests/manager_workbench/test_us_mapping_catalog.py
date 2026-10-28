from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import v4.manager_workbench.api as workbench_api
from v4.manager_workbench.us_mapping_catalog import (
    CatalogValidationError,
    load_catalog,
    search_catalog,
)


ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "v4/manager_workbench/research_data/us_hk_667_catalog_20261015.json"
MEMBERSHIP_PATH = ROOT / "docs/handoffs/hk_connect_list_20261014/港股通股票名单_667只_20261014.csv"
REBUILD_SCRIPT = ROOT / "docs/handoffs/us_hk_667_catalog_20261015/rebuild_catalog.py"


def _load_rebuild_module():
    spec = importlib.util.spec_from_file_location("us_hk_catalog_rebuild", REBUILD_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_source_bound_catalog_preserves_roster_order_and_every_relation_row():
    catalog = load_catalog(CATALOG_PATH)
    assert catalog["source"]["package_sha256"] == "dac3c820fcd6919fabdccc9c37ee9055b729b200fcde5e48f0dcf527de81bc6d"
    assert catalog["source"]["membership_sha256"] == "9b799c0b74ac5047f4e44a1b3dfd1dfa5ca9ce978fa3b8e7877913c423424c9c"
    assert len(catalog["stocks"]) == 667
    assert len(catalog["relations"]) == 1003
    assert catalog["coverage"]["report_sections"] == 667
    assert catalog["coverage"]["stocks_with_relations"] == 649
    assert catalog["coverage"]["stocks_without_relations"] == [
        "01528", "01811", "01963", "01988", "02202", "02357", "02526", "02635",
        "02922", "03311", "03774", "06049", "06066", "06658", "06666", "06681", "06963", "06979",
    ]
    assert catalog["safety"] == {
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "prediction_validation": "UNTESTED",
        "historical_PIT": "NOT_VALIDATED",
    }

    import csv

    with MEMBERSHIP_PATH.open(encoding="utf-8-sig", newline="") as stream:
        roster = list(csv.DictReader(stream))
    assert [stock["hk_code"] for stock in catalog["stocks"]] == [row["港股代码"] for row in roster]
    assert [stock["name"] or "" for stock in catalog["stocks"]] == [row["中文简称"] for row in roster]
    assert all(row["prediction_eligible"] is False for row in catalog["relations"])
    assert all(row["prediction_validation"] == "UNTESTED" for row in catalog["relations"])
    assert all(row["fact_review_status"] == "PENDING" for row in catalog["relations"])
    assert {row["source_record"]["type"] for row in catalog["relations"]} >= {"OWNERSHIP", "SAME_ISSUER", "SUPPLY_CHAIN"}


def test_search_keeps_historical_weak_and_audit_only_rows_without_promotion():
    catalog = load_catalog(CATALOG_PATH)
    exact_hk = search_catalog(catalog, "HK.00001")
    assert exact_hk["total"] == 1
    assert exact_hk["items"][0]["hk_code"] == "00001"
    assert exact_hk["items"][0]["relations"]
    assert any(row["us_symbol"] == "CVE" for row in exact_hk["items"][0]["relations"])

    asset = search_catalog(catalog, "CVE")
    assert any(item["hk_code"] == "00001" for item in asset["items"])
    assert all(relation["prediction_eligible"] is False
               for item in asset["items"] for relation in item["relations"])

    historical_source = next(row for row in catalog["relations"]
                             if row["source_record"].get("status") in {"HISTORICAL_ONLY", "DELISTED_EXCLUDE_PRICE"})
    weak_source = next(row for row in catalog["relations"]
                       if row["source_record"].get("mapping_status") == "REVIEWED_WEAK_MAPPING")
    audit_source = next(row for row in catalog["relations"]
                        if row["source_record"].get("audit_only") == "True")
    for source in [historical_source, weak_source, audit_source]:
        result = search_catalog(catalog, source["hk_code"])
        matches = [row for row in result["items"][0]["relations"]
                   if row["source_row"] == source["source_row"]]
        assert len(matches) == 1
        assert matches[0]["source_record"] == source["source_record"]
        assert matches[0]["fact_review_status"] == "PENDING"
        assert matches[0]["prediction_eligible"] is False
        assert matches[0]["prediction_validation"] == "UNTESTED"


def test_api_returns_read_only_asset_search_with_source_and_safety_flags():
    app = FastAPI()
    app.include_router(workbench_api.create_router(None))
    response = TestClient(app).get("/api/v4/manager-workbench/mapping-catalog", params={"q": "CVE"})
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "STRUCTURE_VALID"
    assert body["gaps"] == [
        "SOURCE_FACTS_NOT_INDEPENDENTLY_VERIFIED",
        "PREDICTION_UNTESTED",
        "HISTORICAL_PIT_NOT_VALIDATED",
    ]
    assert body["data"]["source"]["membership_snapshot"] == "2026-10-14"
    assert body["data"]["safety"]["RESEARCH_ONLY"] is True
    assert body["data"]["safety"]["production_allowed"] is False
    assert body["data"]["safety"]["buy_gate_updated"] is False
    assert body["data"]["safety"]["orders_sent"] is False
    assert any(
        relation["us_symbol"] == "CVE"
        and relation["prediction_eligible"] is False
        and relation["fact_review_status"] == "PENDING"
        for item in body["data"]["items"]
        for relation in item["relations"]
    )


def test_catalog_and_api_fail_closed_on_corrupt_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    catalog["relations"][0]["source_record"]["status"] = "REVIEWED"
    corrupted_catalog = tmp_path / "corrupted-catalog.json"
    corrupted_catalog.write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(CatalogValidationError, match="integrity check failed"):
        load_catalog(corrupted_catalog)

    monkeypatch.setattr(workbench_api, "US_MAPPING_CATALOG_PATH", corrupted_catalog)
    app = FastAPI()
    app.include_router(workbench_api.create_router(None))
    response = TestClient(app).get("/api/v4/manager-workbench/mapping-catalog?q=CVE")
    assert response.status_code == 503
    body = response.json()
    assert body["state"] == "FAILED"
    assert body["data"] is None
    assert body["gaps"] == ["US_HK_MAPPING_CATALOG_INVALID"]


def test_rebuilder_rejects_changed_or_truncated_zip_before_producing_catalog(tmp_path: Path):
    rebuild = _load_rebuild_module()
    broken = tmp_path / "broken-source.zip"
    with zipfile.ZipFile(broken, "w") as archive:
        archive.writestr("README.md", "not the supplied package")
    with pytest.raises(ValueError, match="source ZIP SHA mismatch"):
        rebuild.build_catalog(broken, MEMBERSHIP_PATH)


OVERLAY_PATH = ROOT / 'v4/manager_workbench/research_data/us_hk_667_review_overlay_20261015.json'
RECOVERY_OVERLAY_PATH = ROOT / 'v4/manager_workbench/research_data/us_hk_667_recovery_overlay_20261016.json'


def test_overlay_keeps_all_original_rows_and_accurate_processing_counts():
    from v4.manager_workbench.us_mapping_catalog import CatalogStore
    store = CatalogStore()
    result = store.search(CATALOG_PATH, OVERLAY_PATH)
    assert result['total'] == 667
    assert len(result['items']) == 25
    progress = result['review_progress']
    assert progress['source_reviewed_relations'] == 700
    assert progress['unprocessed_relations'] == 303
    assert progress['source_reviewed_stocks'] == 378
    assert progress['all_original_relations_processed_stocks'] == 378
    assert progress['independently_verified_relations'] == 0
    assert progress['research_use_counts'] == {
        'PENDING_REVIEW': 985,
        'BACKGROUND_HISTORICAL': 10,
        'EXCLUDED_CURRENT': 5,
        'CONDITIONAL_OBSERVATION': 3,
    }
    assert sum(progress['research_use_counts'].values()) == 1003
    all_items=[]
    for offset in range(0, 667, 200):
        page = store.search(CATALOG_PATH, OVERLAY_PATH, offset=offset, limit=200)
        assert page['total'] == 667 and page['review_progress'] == progress
        all_items.extend(page['items'])
    original=load_catalog(CATALOG_PATH)
    assert [s['source_record'] for s in all_items] == [s['source_record'] for s in original['stocks']]
    assert [r['source_record'] for r in sorted([r for s in all_items for r in s['relations']], key=lambda r:r['source_row'])] == [r['source_record'] for r in original['relations']]
    revisions=[r for s in all_items for r in s['relations'] if r['review_revision']]
    assert len(revisions) == 700
    assert all(r['fact_review_status']=='PENDING' and r['independent_verification']=='NOT_RUN' and not r['prediction_eligible'] for r in revisions)
    exact = store.search(CATALOG_PATH, OVERLAY_PATH, 'R001')
    assert [r['relation_id'] for s in exact['items'] for r in s['relations']] == ['R001']
    assert exact['items'][0]['relations'][0]['review_revision']['revision']['revision_research_fact_state'] == 'VERIFIED_DATED_ASSOCIATE_FACT'
    excluded = store.search(CATALOG_PATH, OVERLAY_PATH, 'R003')
    assert excluded['items'][0]['relations'][0]['research_use'] == 'EXCLUDED_CURRENT'
    pending = store.search(CATALOG_PATH, OVERLAY_PATH, research_use='PENDING_REVIEW', limit=200)
    assert pending['review_progress'] == progress
    assert all(r['research_use']=='PENDING_REVIEW' for s in pending['items'] for r in s['relations'])
    assert store.search(CATALOG_PATH, OVERLAY_PATH, 'HK.00001')['total'] == 1
    assert store.search(CATALOG_PATH, OVERLAY_PATH, 'CVE')['items']
    # Returned mutable rows cannot contaminate cached source data.
    exact['items'][0]['source_record']['主营']='MUTATED'
    assert store.search(CATALOG_PATH, OVERLAY_PATH, 'R001')['items'][0]['source_record']['主营'] != 'MUTATED'


def test_cache_validates_once_and_invalidates_even_if_mtime_is_restored(tmp_path, monkeypatch):
    import os
    import shutil
    import v4.manager_workbench.us_mapping_catalog as module
    base=tmp_path/'base.json';overlay=tmp_path/'overlay.json'
    shutil.copyfile(CATALOG_PATH,base);shutil.copyfile(OVERLAY_PATH,overlay)
    shutil.copyfile(RECOVERY_OVERLAY_PATH,tmp_path/'us_hk_667_recovery_overlay_20261016.json')
    load_count=[];original_load=module.load_catalog
    def count(path):
        load_count.append(path)
        return original_load(path)
    monkeypatch.setattr(module,'load_catalog',count)
    store=module.CatalogStore()
    store.search(base,overlay);store.search(base,overlay,'R001')
    assert len(load_count)==1
    stat=overlay.stat();raw=overlay.read_bytes()
    overlay.write_bytes(raw.replace(b'SOURCE_REVIEWED',b'SOURCE_TAMPERED',1))
    os.utime(overlay,ns=(stat.st_atime_ns,stat.st_mtime_ns))
    with pytest.raises(CatalogValidationError):store.search(base,overlay)
    # A stale success cannot be reused after failed reload.
    with pytest.raises(CatalogValidationError):store.search(base,overlay)
    shutil.copyfile(OVERLAY_PATH,overlay)
    assert store.search(base,overlay)['total']==667
    value=json.loads(base.read_bytes());value['relations'][0]['source_record']['status']='REVIEWED'
    value['integrity_sha256']=module.integrity_sha256(value)
    base.write_text(json.dumps(value,ensure_ascii=False))
    with pytest.raises(CatalogValidationError):store.search(base,overlay)


def test_api_filters_and_overlay_corruption_fail_closed(tmp_path,monkeypatch):
    app=FastAPI();app.include_router(workbench_api.create_router(None));client=TestClient(app)
    body=client.get('/api/v4/manager-workbench/mapping-catalog').json()['data']
    assert body['total']==667 and body['review_progress']['source_reviewed_relations']==700
    assert body['recovery_v2r1']['counts']['processed_relations']==1003
    assert body['recovery_v2r1']['counts']['research_scope_closed']==757
    assert body['recovery_v2r1']['counts']['excluded_scope_closed']==25
    result=client.get('/api/v4/manager-workbench/mapping-catalog',params={'q':'R003','research_use':'EXCLUDED_CURRENT'}).json()['data']
    assert result['items'][0]['relations'][0]['relation_id']=='R003'
    assert client.get('/api/v4/manager-workbench/mapping-catalog?research_use=VERIFIED').status_code==422
    broken=tmp_path/'bad.json';broken.write_text('{}')
    monkeypatch.setattr(workbench_api,'US_MAPPING_REVIEW_OVERLAY_PATH',broken)
    response=client.get('/api/v4/manager-workbench/mapping-catalog')
    assert response.status_code==503 and response.json()['data'] is None


def test_700_overlay_builder_is_reproducible_and_rejects_unbound_supplement(tmp_path):
    path=ROOT/'docs/handoffs/us_hk_700_supplement_20261016/build_overlay.py'
    spec=importlib.util.spec_from_file_location('us_hk_finish_builder',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    zip_path=Path('/Users/lexi/Downloads/US_HK_560_700_完整补件_20261015.zip')
    if zip_path.exists():
        assert module.build(zip_path)==json.loads(OVERLAY_PATH.read_bytes())
    broken=tmp_path/'wrong.zip';broken.write_bytes(b'bad')
    with pytest.raises(ValueError,match='source supplement SHA mismatch'):module.build(broken)


def test_700_overlay_provenance_raw_parse_issues_and_full_evidence_contract():
    from v4.manager_workbench.us_mapping_catalog import CatalogStore

    overlay=json.loads(OVERLAY_PATH.read_bytes())
    assert overlay['source_package_sha256']=='2894b3bca475965aa3553977a654b10fa4c6750bbcb80f70f1bea17bdde649b0'
    assert overlay['source_package_kind']=='combined_560_700_supplement'
    assert overlay['source_subtree']=='700/deliverable_batch35'
    assert overlay['manifest_sha256']=='8ba8ea7ef7c351bcd5a1b72ad8f449b7acf555a54a172ea66084248f28e26ab9'
    assert overlay['upstream_original_700_package']=={
        'claimed_sha256':'589dd772...',
        'received_locally':False,
        'local_sha256_verified':False,
    }
    assert len(overlay['records'])==700
    assert overlay['research_safety']=={
        'RESEARCH_ONLY':True,
        'production_allowed':False,
        'buy_gate_updated':False,
        'orders_sent':False,
        'prediction_validation':'UNTESTED',
        'historical_PIT':'NOT_VALIDATED',
        'event_validation':'NOT_RUN',
        'independent_local_review':'NOT_RUN',
    }
    assert sum(len(r['revision_json_parse_issues']) for r in overlay['records'])==60
    for record in overlay['records']:
        revision=record['revision']
        assert revision['revision_event_validation_state']=='NOT_RUN'
        assert revision['revision_prediction_validation_state']=='UNTESTED'
        assert revision['revision_historical_PIT_state']=='NOT_VALIDATED'
        assert revision['revision_independent_local_review_state']=='NOT_RUN'
        if record['revision_json_parse_issues']:
            assert len(record['revision_json_parse_issues'])==1
            issue=record['revision_json_parse_issues'][0]
            assert issue['field']=='revision_failure_checks_json'
            assert issue['issue']=='INVALID_JSON_PRESERVED_AS_SOURCE_TEXT'
            assert isinstance(revision['revision_failure_checks_json'],str)
            assert hashlib.sha256(revision['revision_failure_checks_json'].encode()).hexdigest()==issue['raw_sha256']
            with pytest.raises(json.JSONDecodeError):
                json.loads(revision['revision_failure_checks_json'])
        for evidence in record['evidence']:
            assert isinstance(evidence['declared_unresolved_navigation_reference_json'],str)
            assert isinstance(evidence['evidence_wording_clarifications_json'],str)
            assert evidence['declared_unresolved_navigation_reference_json']
            assert evidence['evidence_wording_clarifications_json']

    store=CatalogStore()
    default=store.search(CATALOG_PATH,OVERLAY_PATH)
    assert default['review_source']['source_package_sha256']==overlay['source_package_sha256']
    assert default['review_source']['manifest_sha256']==overlay['manifest_sha256']
    assert default['review_source']['source_subtree']=='700/deliverable_batch35'
    assert len(json.dumps(default,ensure_ascii=False).encode())<1_000_000
    assert all('evidence' not in row['review_revision'] for item in default['items'] for row in item['relations'])

    summary=store.search(CATALOG_PATH,OVERLAY_PATH,'00001')
    summary_rows=[row for item in summary['items'] for row in item['relations']]
    assert summary_rows and all(row['review_detail_level']=='SUMMARY' for row in summary_rows)
    assert all('evidence' not in row['review_revision'] for row in summary_rows)
    summary_review=next(row['review_revision'] for row in summary_rows if row['relation_id']=='R001')
    assert 'usage_limits_json' in summary_review['source_summary']
    assert 'current_usage_limits_with_addenda_json' in summary_review['source_summary']
    assert 'current_applicability_gaps_json' in summary_review['source_summary']

    full=store.search(CATALOG_PATH,OVERLAY_PATH,'R001')
    full_row=full['items'][0]['relations'][0]
    expected={r['relation_id']:r for r in overlay['records']}['R001']
    assert full_row['review_detail_level']=='FULL'
    assert full_row['review_revision']==expected
    assert full_row['review_revision']['evidence']
    assert 'declared_unresolved_navigation_reference_json' in full_row['review_revision']['evidence'][0]
    assert 'evidence_wording_clarifications_json' in full_row['review_revision']['evidence'][0]


def test_700_preserves_prior40_history_and_r021_addendum_with_current_source_summary():
    from v4.manager_workbench.us_mapping_catalog import CatalogStore
    old_path=ROOT/'docs/handoffs/us_hk_667_finish_20261015/post220/preimage/v4/manager_workbench/research_data/us_hk_667_review_overlay_20261015.json'
    old={r['relation_id']:r for r in json.loads(old_path.read_bytes())['records']}
    current={r['relation_id']:r for r in json.loads(OVERLAY_PATH.read_bytes())['records']}
    assert set(old)<=set(current) and len(set(current)-set(old))==660
    for rid,before in old.items():
        after=current[rid]
        assert before['revision']['revision_research_fact_state']==after['revision']['revision_research_fact_state']
        assert before['revision']['revision_current_applicability_state']==after['revision']['revision_current_applicability_state']
        assert before['revision']['revision_field_assessments_json']==after['revision']['revision_field_assessments_json']
    result=CatalogStore().search(CATALOG_PATH,OVERLAY_PATH,'R021')
    row=result['items'][0]['relations'][0]
    review=row['review_revision'];summary=review['source_summary']
    addenda=review['revision']['revision_subsequent_research_addenda_json']
    assert addenda and 'Delaware' in json.dumps(addenda,ensure_ascii=False)
    assert 'IL' in json.dumps(summary['current_usage_limits_with_addenda_json'])
    assert 'IL' in json.dumps(summary['current_next_key_evidence_with_addenda_json'])
    assert row['independent_verification']=='NOT_RUN' and not row['prediction_eligible']
    assert any(e['evidence_id']=='B5L3-R073-I01' for e in review['evidence'])
    r004=current['R004']['source_summary']
    assert 'next_key_evidence_json' in r004['source_plain_text_json_fields']
    assert isinstance(r004['next_key_evidence_json'],str) and r004['next_key_evidence_json']


def test_list_payload_is_bounded_and_rid_detail_preserves_complete_source_revision():
    from v4.manager_workbench.us_mapping_catalog import CatalogStore
    store=CatalogStore()
    overlay=json.loads(OVERLAY_PATH.read_bytes())
    expected={r['relation_id']:r for r in overlay['records']}
    default=store.search(CATALOG_PATH,OVERLAY_PATH)
    assert len(json.dumps(default,ensure_ascii=False).encode())<1_000_000
    for query in ['', '00001', 'CVE']:
        data=store.search(CATALOG_PATH,OVERLAY_PATH,query)
        assert data['review_progress']==default['review_progress']
        for item in data['items']:
            for row in item['relations']:
                assert row['review_detail_level']=='SUMMARY'
                review=row['review_revision']
                if review:
                    assert 'evidence' not in review
                    assert 'revision_complete_research_record_json' not in review['revision']
                    assert 'revision_field_assessments_json' not in review['revision']
                    assert review['revision']['revision_subsequent_research_addenda_json']==expected[row['relation_id']]['revision']['revision_subsequent_research_addenda_json']
    # Exhaustively preserve all700 complete revisions through explicit RID requests.
    for rid,review in expected.items():
        detail=store.search(CATALOG_PATH,OVERLAY_PATH,rid)
        rows=[row for item in detail['items'] for row in item['relations']]
        assert len(rows)==1 and rows[0]['relation_id']==rid
        assert rows[0]['review_detail_level']=='FULL' and rows[0]['review_revision']==review
        assert rows[0]['fact_review_status']=='PENDING' and rows[0]['prediction_eligible'] is False
        assert detail['review_progress']==default['review_progress']


def test_exact_rid_not_in_legacy_overlay_still_exposes_v2r1_full_record():
    from v4.manager_workbench.us_mapping_catalog import CatalogStore
    result=CatalogStore().search(CATALOG_PATH,OVERLAY_PATH,'R700')
    rows=[row for item in result['items'] for row in item['relations']]
    assert len(rows)==1
    assert rows[0]['relation_id']=='R700'
    assert rows[0]['source_review_status']=='NOT_PROCESSED'
    assert rows[0]['review_detail_level']=='FULL'
    assert rows[0]['review_revision'] is None
    assert rows[0]['recovery_v2r1']['detail_level']=='FULL'
    assert rows[0]['recovery_v2r1']['full_record']['relation_id']=='R700'


def test_v2r1_reconciles_current_closure_exclusion_open_and_no_edge_boundaries():
    from v4.manager_workbench.us_mapping_catalog import CatalogStore
    store=CatalogStore()
    default=store.search(CATALOG_PATH,OVERLAY_PATH)
    current=default['recovery_v2r1']
    counts=current['counts']
    assert counts['snapshot_stocks']==667 and counts['original_relations']==1003
    assert counts['processed_relations']==1003
    assert counts['closure_status_counts']=={
        'CLOSED_RESEARCH_SCOPE':757,'CLOSED_EXCLUDED_SCOPE':25,'OPEN':221,
    }
    assert counts['research_scope_closed']==757
    assert counts['excluded_scope_closed']==25
    assert counts['closed_total_including_exclusions']==782
    assert counts['open_relations']==221
    assert counts['stocks_with_relations']==649 and counts['stocks_without_relations']==18
    assert counts['company_independent_acceptance']==0
    assert current['research_safety']['semantic_mapping_validity']=='CANNOT_CONFIRM'
    assert current['research_safety']['prediction_validation']=='UNTESTED'
    assert current['research_safety']['historical_PIT']=='NOT_VALIDATED'
    assert current['research_safety']['event_and_data_tests']=='NOT_RUN'
    assert current['evidence_limits']['historical_path_gap_occurrences']==227
    assert current['evidence_limits']['historical_path_gap_unique_paths']==218
    assert current['evidence_limits']['separate_restored740_missing_path_sha_pairs']==404
    assert current['evidence_limits']['separate_restored740_missing_hashes']==388
    assert current['evidence_limits']['gap_scopes_additive'] is False
    assert current['evidence_limits']['A_url_occurrences_unattempted']==62
    assert current['evidence_limits']['available_at']=='ABSENT'
    assert current['prior_700_history']['record_count']==700
    assert current['prior_700_history']['status_crosswalk']=='NOT_ESTABLISHED'

    for relation_id,status in [('R006','CLOSED_RESEARCH_SCOPE'),('R003','CLOSED_EXCLUDED_SCOPE'),('R001','OPEN')]:
        exact=store.search(CATALOG_PATH,OVERLAY_PATH,relation_id)
        row=exact['items'][0]['relations'][0]
        assert exact['total']==1 and row['relation_id']==relation_id
        assert row['recovery_v2r1']['closure_status']==status
        assert row['recovery_v2r1']['detail_level']=='FULL'
        assert row['recovery_v2r1']['full_record']['relation_id']==relation_id
        assert row['recovery_v2r1']['full_record']['six_layers']
        assert row['recovery_v2r1']['full_record']['field_assessments']

    no_edge_code=load_catalog(CATALOG_PATH)['coverage']['stocks_without_relations'][0]
    no_edge=store.search(CATALOG_PATH,OVERLAY_PATH,no_edge_code)
    assert no_edge['total']==1 and no_edge['items'][0]['hk_code']==no_edge_code
    assert no_edge['items'][0]['relation_count']==0 and no_edge['items'][0]['relations']==[]


def test_v2r1_default_is_summary_and_exact_rid_keeps_old700_full_evidence():
    from v4.manager_workbench.us_mapping_catalog import CatalogStore
    store=CatalogStore()
    default=store.search(CATALOG_PATH,OVERLAY_PATH)
    assert len(json.dumps(default,ensure_ascii=False).encode())<1_000_000
    row=next(row for item in default['items'] for row in item['relations'] if row['relation_id']=='R001')
    assert row['recovery_v2r1']['detail_level']=='SUMMARY'
    assert 'full_record' not in row['recovery_v2r1']
    assert 'effective_research' not in row['recovery_v2r1']
    assert row['review_revision'] is not None and 'evidence' not in row['review_revision']
    catalog=load_catalog(CATALOG_PATH)
    with pytest.raises(CatalogValidationError,match='query is too long'):
        search_catalog(catalog,'X'*129)
    with pytest.raises(CatalogValidationError,match='limit must be between 1 and 200'):
        search_catalog(catalog,limit=201)

    exact=store.search(CATALOG_PATH,OVERLAY_PATH,'R001')
    full=exact['items'][0]['relations'][0]
    assert len(json.dumps(exact,ensure_ascii=False).encode())<1_000_000
    assert full['recovery_v2r1']['detail_level']=='FULL'
    current_record=full['recovery_v2r1']['full_record']
    assert current_record['effective_research']['relation_id']=='R001'
    assert len(current_record['six_layers'])==6 and len(current_record['field_assessments'])==7
    assert full['review_revision']['evidence']
    assert exact['recovery_v2r1']['prior_700_history']['sha256']==hashlib.sha256(OVERLAY_PATH.read_bytes()).hexdigest()


def test_v2r1_overlay_rejects_tampering_and_builder_is_reproducible(tmp_path):
    from v4.manager_workbench.us_mapping_catalog import CatalogStore
    import shutil
    import v4.manager_workbench.us_mapping_catalog as catalog_module

    base=tmp_path/'us_hk_667_catalog_20261015.json'
    old=tmp_path/'us_hk_667_review_overlay_20261015.json'
    current=tmp_path/catalog_module.RECOVERY_OVERLAY_NAME
    shutil.copyfile(CATALOG_PATH,base)
    shutil.copyfile(OVERLAY_PATH,old)
    shutil.copyfile(RECOVERY_OVERLAY_PATH,current)
    original=current.read_bytes()
    current.write_bytes(original[:-2]+b'{}')
    with pytest.raises(CatalogValidationError):
        CatalogStore().search(base,old)

    builder_path=ROOT/'docs/handoffs/us_hk_recovery_v2r1_20261016/builders/build_recovery_overlay.py'
    spec=importlib.util.spec_from_file_location('us_hk_recovery_builder',builder_path)
    assert spec and spec.loader
    builder=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=builder
    spec.loader.exec_module(builder)
    archive=Path('/Users/lexi/Downloads/US_HK_667_1003_recovery_v2r1_20261016.zip')
    if archive.exists():
        rebuilt=builder.build_recovery_overlay(archive)
        assert builder.canonical_bytes(rebuilt)+b'\n'==RECOVERY_OVERLAY_PATH.read_bytes()
    broken=tmp_path/'wrong.zip';broken.write_bytes(b'not the supplied archive')
    with pytest.raises(ValueError,match='source ZIP SHA mismatch'):
        builder.build_recovery_overlay(broken)


def test_api_summary_and_exact_rid_detail_have_same_identity_safety_and_progress():
    app=FastAPI();app.include_router(workbench_api.create_router(None));client=TestClient(app)
    listing=client.get('/api/v4/manager-workbench/mapping-catalog')
    assert len(listing.content)<1_000_000
    listed=listing.json()['data']
    detail=client.get('/api/v4/manager-workbench/mapping-catalog?q=R021&limit=1').json()['data']
    row=detail['items'][0]['relations'][0]
    assert row['relation_id']=='R021' and row['review_detail_level']=='FULL'
    assert row['review_revision']['evidence']
    assert detail['review_progress']==listed['review_progress'] and detail['safety']==listed['safety']
    assert detail['review_source']==listed['review_source']
