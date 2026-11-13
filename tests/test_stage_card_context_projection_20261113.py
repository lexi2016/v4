"""Frozen repair scope: source links only, immutable selection identity."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from infrastructure.data_store import _sha256
from infrastructure.research_store import HourlyResearchStore
from stage_center.news_link_projection import project_news_links
from stage_center.research_context import ResearchContextError, load_research_context
from stage_center.stage_card_context_projection import stage_card_cutoff
from domains.research import build_research_archive
from test_news_link_projection_20261014 import source  # verified morning fixture/parser
from test_stage_research_context_v4 import _source, _write_morning


def native_market(root: Path):
    snapshot = dict(schema_version="stage_center.a_opening_native_snapshot.v1", trade_date="20261014",
                    stage_id="STAGE_0925", market_cutoff_at="2026-10-14T09:25:05+08:00",
                    captured_at="2026-10-14T09:25:00.500000+08:00", temporal_cutoff_safe=True,
                    RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
    raw = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(raw).hexdigest()
    manifest = dict(schema_version="stage_center.a_opening_native_snapshot.v1.manifest",
                    trade_date="20261014",stage_id="STAGE_0925", artifact_sha256=digest,
                    artifact_relative="native_opening/20261014/STAGE_0925/snapshot.json",
                    captured_at=snapshot["captured_at"],production_allowed=False,buy_gate_updated=False,orders_sent=False)
    root.mkdir(parents=True, exist_ok=True)
    (root/"snapshot.json").write_bytes(raw);(root/"manifest.json").write_text(json.dumps(manifest))
    return dict(market="A_SHARE", trade_date="20261014", stage_id="STAGE_0925",
                selection_manifest_receipt_verified=True,selection_artifact_sha256="a"*64,
                source_evidence=["route=a_share_native_quote_snapshot", "native_snapshot_contract=V4_A_OPENING_NATIVE_SNAPSHOT_V1",
                                 f"native_snapshot_manifest={root/'manifest.json'}",f"native_snapshot_sha256={digest}",
                                 f"native_snapshot_captured_at={snapshot['captured_at']}"])


def publish_legacy(root: Path, change=None):
    src = _source("20261014",slot="0900",with_stage_evidence=True)
    timeline=src["stock_research_timeline"][0]
    item=src["research_items"][0]
    item.update({k:timeline.get(k, "") for k in ("source_type","source_name","source_path","url",
                 "event_time","source_published_at","first_seen_at","last_checked_at")})
    item["title"]=timeline["source_title"]
    src["raw_items"]=[dict(raw_id=item["raw_id"],raw_payload={})]
    src["cannot_confirm"] = [{"reason":"ZSXQ_SOURCE_PARTIAL_INCOMPLETE","item_id":"item-000001"}]
    raw=json.dumps(src,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    digest=hashlib.sha256(raw).hexdigest()
    p=root/f"research/hourly/source/{digest}.json";p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
    payload=build_research_archive(src,source_input_sha256=digest)
    payload.pop("stage_evidence_v1",None)
    payload["cannot_confirm"]=["LEGACY_SOURCE_CANNOT_CONFIRM_COUNT:1"]
    if change: change(payload)
    HourlyResearchStore(root).publish(payload,slot="0900",mode="LIVE")
    return p


def test_native_cutoff_links_existing_news_and_preserves_original_rows(source,tmp_path):
    root,_,_=source;market=native_market(tmp_path/"native")
    rows=[dict(code="A.603386",name="骏亚科技",score=100,stage_score=100,rank=1,
               support_primary_price=None,pressure_price=None,invalidation_price=None,formal_eligible=False)]
    before=copy.deepcopy(rows);out=project_news_links(rows,market,trade_date="20261014",morning_root=root)
    assert out[0]["news_link"]["score"]==48
    assert out[0]["news_link"]["cutoff"]=="09:25:05"
    assert out[0]["news_link"]["pit_capture_verified"] is False
    assert out[0]["research_context_check"]["reason"]=="RESEARCH_DATA_ROOT_NOT_CONFIGURED"
    assert out[0]["support_primary_price"] is None
    assert rows==before and all(out[0][k]==v for k,v in before[0].items())


@pytest.mark.parametrize("change",["cutoff_conflict","bad_sha","wrong_date","missing_manifest","future_capture"])
def test_native_unknown_conflicting_or_future_cutoff_fails_closed(tmp_path,change):
    market=native_market(tmp_path)
    if change=="cutoff_conflict":market["source_evidence"].append("v4_stage_cutoff=09:30:00")
    elif change=="bad_sha":market["source_evidence"].append("native_snapshot_sha256="+"b"*64)
    elif change=="wrong_date":market["trade_date"]="20261015"
    elif change=="missing_manifest":(tmp_path/"manifest.json").unlink()
    else:
        p=tmp_path/"snapshot.json";x=json.loads(p.read_text());x["captured_at"]="2026-10-14T09:30:00+08:00";p.write_text(json.dumps(x))
    with pytest.raises((ValueError,OSError)):stage_card_cutoff(market,trade_date="20261014")


def test_exact_legacy_warning_format_accepts_verified_score_without_rewriting_files(tmp_path):
    root=tmp_path/"research";publish_legacy(root);_write_morning(tmp_path/"morning",date="20261014")
    before={p:p.read_bytes() for p in root.rglob("*.json")}
    c=load_research_context(root,trade_date="20261014",stage_cutoff="09:25:05",morning_root=tmp_path/"morning")
    assert c.by_code["A.000001"].research_quality_score==72.5
    assert "v4_hourly_warning_projection_compatibility=EXACT_LEGACY_SOURCE_GAP_COUNT" in c.source_evidence
    assert any("LEGACY_SOURCE_CANNOT_CONFIRM_COUNT:1" in v for v in c.source_evidence)
    assert before=={p:p.read_bytes() for p in root.rglob("*.json")}
    market=native_market(tmp_path/"native")
    rows=[dict(code="A.000001",name="平安银行",score=100,rank=1,research_quality_score=None)]
    out=project_news_links(rows,market,trade_date="20261014",morning_root=tmp_path/"morning",research_root=root)
    assert out[0]["research_link"]["score"]==72.5
    assert out[0]["research_quality_score"] is None and out[0]["score"]==100
    assert out[0]["research_link"]["available_at"]


@pytest.mark.parametrize("field",["warnings","warning_count","title","score","source_time"])
def test_legacy_compatibility_rejects_other_archive_changes(tmp_path,field):
    def change(p):
        if field=="warnings":p["cannot_confirm"].append("UNEXPECTED_WARNING")
        elif field=="warning_count":p["cannot_confirm"]=["LEGACY_SOURCE_CANNOT_CONFIRM_COUNT:2"]
        elif field=="title":p["articles"][0]["source_title"]="forged title"
        elif field=="score":p["stock_pool"][0]["research_score"]=100
        else:p["source_generated_at"]="2026-10-14T09:25:06+08:00"
    publish_legacy(tmp_path,change)
    with pytest.raises(ResearchContextError):load_research_context(tmp_path,trade_date="20261014",stage_cutoff="09:25:05")


def test_changed_witness_and_hk_are_never_promoted(tmp_path):
    p=publish_legacy(tmp_path);witness=json.loads(p.read_text());witness["research_items"][0]["quality_score"]=99
    p.write_text(json.dumps(witness))
    with pytest.raises(ResearchContextError,match="WITNESS_SHA_MISMATCH"):
        load_research_context(tmp_path,trade_date="20261014",stage_cutoff="09:25:05")
    rows=[dict(code="HK.00068",score=88,rank=1)]
    assert project_news_links(rows,dict(market="HK_CONNECT"),trade_date="20261014",morning_root=None)==rows


def test_source_audit_warning_projection_rejects_unknown_policy():
    from stage_center.stage_card_context_projection import _legacy_report_role_warning_reasons
    with pytest.raises(ValueError, match="REPORT_ROLE_AUDIT_POLICY"):
        _legacy_report_role_warning_reasons({"report_entity_audit": {"policy_version": "unknown"}})
