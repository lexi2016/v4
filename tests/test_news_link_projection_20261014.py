import copy
import json

import pytest

from infrastructure.data_store import _sha256
from infrastructure.shared_morning_news_reader import SharedMorningNewsReader
from stage_center.news_link_projection import project_news_links
from upstreams.v3_shared_data.shared_data.morning_news import materialize_stock_mentions


@pytest.fixture
def source(tmp_path, monkeypatch):
    article = dict(title="盘前纪要", url="https://example.invalid/news", published_at="2026-10-14 08:00:00",
                   body_text="骏亚科技：公告涉及生产经营情况。", body_status="ARTICLE_BODY_READ", category="盘前纪要")
    payload = dict(schema_version="v3_shared_data.morning_news.v1", trade_date="20261014",
                   source_role="JIUYANGONGSHE_MORNING_NEWS", articles=[article], article_count=1,
                   stock_mentions=[], mention_count=0, cannot_confirm=["STOCK_MENTIONS_CANDIDATE_REGISTRY_MISSING"],
                   production_allowed=False, buy_gate_updated=False, orders_sent=False)
    def publish():
        manifest = dict(payload_sha256=_sha256(payload))
        receipt = dict(manifest_sha256=_sha256(manifest), production_allowed=False, buy_gate_updated=False, orders_sent=False)
        pointer = dict(schema_version="v3_shared_data.morning_news_latest.v1", entries={"20261014": dict(
            payload_relative="payload.json", manifest_relative="manifest.json", receipt_relative="receipt.json",
            payload_sha256=_sha256(payload))})
        for path, value in [("payload.json",payload),("manifest.json",manifest),("receipt.json",receipt),("morning_news/latest.json",pointer)]:
            target=tmp_path/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(value))
    monkeypatch.setattr(SharedMorningNewsReader, "_shared_contract", lambda self: (lambda *args: [], materialize_stock_mentions))
    publish()
    return tmp_path, payload, publish


def inputs():
    rows = [dict(code="SH.603386",name="骏亚科技",score=80,rank=1,news_quality_score=None,research_quality_score=None),
            dict(code="SH.600391",name="航发科技",score=79,rank=2,news_quality_score=None,research_quality_score=None)]
    market = dict(selection_manifest_receipt_verified=True, selection_artifact_sha256="a"*64,
                  source_evidence=["v4_stage_cutoff=10:30:00", "v4_hourly_slot=1000"],
                  cannot_confirm=["RESEARCH_CONTEXT_CODE_MISSING:A.603386", "RESEARCH_CONTEXT_CODE_MISSING:A.600391"])
    return rows,market


def test_real_parser_links_verified_body_without_mutating_scores_or_artifacts(source):
    root,_,_=source; rows,market=inputs(); before=copy.deepcopy(rows)
    disk={str(p):p.read_bytes() for p in root.rglob("*.json")}
    out=project_news_links(rows,market,trade_date="20261014",morning_root=root)
    assert out[0]["news_link"]["score"] == 48  # identity, excerpt, category; no invented membership bonus
    assert out[0]["news_link"]["article_count"] == 1
    assert out[0]["news_quality_score"] is None and out[0]["research_quality_score"] is None
    assert out[0]["score"] == 80 and out[0]["rank"] == 1
    assert out[0]["research_missing_reason"] == "10:00 研报归档无该股记录"
    assert "未匹配" in out[1]["news_missing_reason"] and "news_link" not in out[1]
    assert out[0]["news_link"]["pit_capture_verified"] is False
    assert rows == before and disk == {str(p):p.read_bytes() for p in root.rglob("*.json")}


@pytest.mark.parametrize("published", ["2026-10-14 10:30:01", "2026-10-15 08:00:00", "2026-10-13 08:00:00", ""])
def test_future_wrong_day_and_unknown_publication_never_link(source,published):
    root,payload,publish=source;payload["articles"][0]["published_at"]=published;publish()
    rows,market=inputs();out=project_news_links(rows,market,trade_date="20261014",morning_root=root)
    assert "news_link" not in out[0]
    assert "发布时间缺失或晚于阶段截止" in out[0]["news_missing_reason"]


def test_tampered_news_and_unverified_selection_fail_closed(source):
    root,_,_=source;rows,market=inputs()
    market["selection_manifest_receipt_verified"]=False
    out=project_news_links(rows,market,trade_date="20261014",morning_root=root)
    assert "股票来源校验未通过" in out[0]["news_missing_reason"]
    market["selection_manifest_receipt_verified"]=True
    (root/"payload.json").write_text("{}")
    out=project_news_links(rows,market,trade_date="20261014",morning_root=root)
    assert "校验失败" in out[0]["news_missing_reason"] and "news_link" not in out[0]


def test_existing_zero_scores_preserved_and_other_date_missing(source):
    root,_,_=source;rows,market=inputs();rows[0].update(news_quality_score=0,research_quality_score=0)
    out=project_news_links(rows,market,trade_date="20261014",morning_root=root)
    assert "news_link" not in out[0] and "research_missing_reason" not in out[0]
    out=project_news_links(rows,market,trade_date="20261013",morning_root=root)
    assert out[1]["news_missing_reason"] == "当天新闻归档缺失"
