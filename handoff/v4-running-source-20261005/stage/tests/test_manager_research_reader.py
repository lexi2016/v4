from __future__ import annotations

from typing import Any

from v4.manager_research.reader_source import (
    READER_SOURCE_ID,
    project_public_news,
    read_public_news,
    read_public_news_batch,
)
from v4.manager_research.service import ManagerResearchJobService, _attach_reader_batch
from v4.manager_research.store import ManagerResearchStore


def row(title: str, *, published_at: str = "2026-09-08 15:45:00", url: str = "https://example.test/a", content: str = "HK01191 海光芯正 原文") -> dict[str, str]:
    return {
        "新闻标题": title,
        "新闻内容": content,
        "发布时间": published_at,
        "文章来源": "测试来源",
        "新闻链接": url,
    }


def test_project_public_news_is_company_bound_date_bounded_and_read_only() -> None:
    result = project_public_news(
        [
            row("公司合作报道"),
            row("未来报道", published_at="2026-09-09 09:00:00", url="https://example.test/future"),
            row("行业背景", content="行业指数与多只股票", url="https://example.test/background"),
        ],
        code="HK.01191",
        name="海光芯正",
        target_date="2026-09-08",
        queried_at="2026-09-08T16:00:00+00:00",
    )

    assert result["status"] == "READY"
    assert result["company_record_count"] == 1
    assert result["materials"][0]["canonical_symbol"] == "HK.01191"
    assert result["materials"][0]["content_is_excerpt"] is True
    assert result["materials"][0]["source_url"] == "https://example.test/a"
    assert result["background_record_count"] == 1
    assert all(item["published_date"] <= "2026-09-08" for item in result["materials"] + result["background"])
    assert all("score" not in item and "recommendation" not in item for item in result["materials"])
    assert any(item["reason"] == "PUBLISHED_AFTER_TARGET_DATE" for item in result["excluded"])


def test_project_public_news_dedupes_same_content_across_urls_and_keeps_attribution() -> None:
    result = project_public_news(
        [
            row("相同报道", url="https://example.test/one"),
            row("相同报道", url="https://example.test/two"),
        ],
        code="01191",
        name="海光芯正",
        target_date="2026-09-08",
    )

    assert result["material_count"] == 1
    material = result["materials"][0]
    assert material["source_count"] == 2
    assert {item["url"] for item in material["source_attributions"]} == {
        "https://example.test/one",
        "https://example.test/two",
    }


def test_project_public_news_accepts_eastmoney_jsonp_fields_and_strips_highlight_markup() -> None:
    result = project_public_news(
        [{
            "date": "2026-09-08 15:45:00",
            "title": "CIOE<em>2026</em> 光博会",
            "content": "海光芯正(<em>01191</em>.HK)与合作方推进产品落地。",
            "mediaName": "财联社",
            "url": "http://finance.eastmoney.com/a/fixture.html",
        }],
        code="01191",
        name="海光芯正",
        target_date="2026-09-08",
    )

    assert result["status"] == "READY"
    assert result["materials"][0]["title"] == "CIOE2026 光博会"
    assert "<em>" not in result["materials"][0]["content_excerpt"]
    assert result["materials"][0]["source_name"] == "财联社"


def test_read_public_news_fail_closes_one_candidate_without_affecting_batch() -> None:
    def fetcher(*, code: str, **_: Any) -> list[dict[str, str]]:
        if code == "00002":
            raise TimeoutError("fixture timeout")
        return [row("可读资料", url=f"https://example.test/{code}", content=f"{code} 固定公司资料")]

    observations = [
        {"code": "00001", "name": "甲", "market": "HK_CONNECT"},
        {"code": "00002", "name": "乙", "market": "HK_CONNECT"},
    ]
    batch = read_public_news_batch(observations, target_date="2026-09-08", fetcher=fetcher, max_workers=2)

    assert batch["source_id"] == READER_SOURCE_ID
    assert batch["requested_candidates"] == 2
    assert batch["rows"]["00001"]["status"] == "READY"
    assert batch["rows"]["00002"]["status"] == "ERROR"
    assert batch["rows"]["00002"]["source_gaps"][0].startswith("PUBLIC_NEWS_ERROR:")
    assert batch["status"] == "PARTIAL_WITH_ROWS"
    assert batch["coverage"]["status"] == "PARTIAL_WITH_ROWS"
    assert batch["coverage"]["no_material_is_not_no_candidate"] is True


def test_project_public_news_drops_non_http_source_urls_without_dropping_readable_material() -> None:
    for unsafe in (
        "javascript:alert(1)",
        "data:text/html,payload",
        "http:///missing-host",
        "http://host:bad/path",
        "http://host:99999/path",
    ):
        result = project_public_news(
            [row("来源链接不可确认", url=unsafe, content="HK01191 海光芯正 这段原文仍然可读")],
            code="01191",
            name="海光芯正",
            target_date="2026-09-08",
        )

        assert result["status"] == "READY"
        assert result["materials"][0]["title"] == "来源链接不可确认"
        assert result["materials"][0]["content_excerpt"] == "HK01191 海光芯正 这段原文仍然可读"
        assert result["materials"][0]["source_url"] is None
        assert result["materials"][0]["url"] is None
        assert result["materials"][0]["source_attributions"][0]["url"] is None


def test_project_public_news_keeps_valid_http_and_https_ports() -> None:
    for valid_url in (
        "http://example.test:80/article",
        "https://example.test:443/article",
    ):
        result = project_public_news(
            [row("带端口的有效原文", url=valid_url, content="HK01191 海光芯正 带端口的原文仍然可读")],
            code="01191",
            name="海光芯正",
            target_date="2026-09-08",
        )

        assert result["status"] == "READY"
        assert result["materials"][0]["source_url"] == valid_url
        assert result["materials"][0]["url"] == valid_url
        assert result["materials"][0]["source_attributions"][0]["url"] == valid_url


def test_attach_reader_keeps_event_source_counts_separate() -> None:
    observations = [{"code": "01191", "name": "海光芯正", "market": "HK_CONNECT"}]

    def fetcher(*, code: str, **_: Any) -> list[dict[str, str]]:
        return [row("公开资料", content=f"{code} 海光芯正 原文", url="https://example.test/reader")]

    event_source_counts = [{"source_id": "HKEX", "status": "READY"}]
    attached = _attach_reader_batch(
        {
            "status": "READY",
            "rows": {"01191": {"status": "READY", "source_counts": event_source_counts}},
            "source_counts": event_source_counts,
            "coverage": {"status": "READY"},
        },
        read_public_news_batch(observations, target_date="2026-09-08", fetcher=fetcher),
        observations,
    )

    assert attached["source_counts"] == event_source_counts
    assert attached["reader_source_counts"][0]["source_id"] == READER_SOURCE_ID
    assert attached["reader_coverage"]["ready_candidates"] == 1


def test_service_can_attach_reader_when_event_provider_is_unavailable(tmp_path: Any) -> None:
    observations = [
        {"code": "01191", "name": "海光芯正", "market": "HK_CONNECT"},
        {"code": "06166", "name": "星河公司", "market": "HK_CONNECT"},
    ]

    def fetcher(*, code: str, **_: Any) -> list[dict[str, str]]:
        return [row("公开合作报道", content=f"{code} 海光芯正 公开原文", url="https://example.test/hg")]

    service = ManagerResearchJobService(
        ManagerResearchStore(tmp_path),
        None,
        None,
        reader_fetcher=fetcher,
    )
    try:
        input_data = {
            "target_trade_date": "20260908",
            "cutoff_at": "2026-09-08T09:40:00+08:00",
        }
        result = service._collect_events(input_data, observations)
    finally:
        service.close()

    assert result["reader_coverage"]["ready_candidates"] == 2
    assert result["rows"]["01191"]["reader_status"] == "READY"
    assert result["rows"]["06166"]["reader_status"] == "READY"
    assert result["rows"]["01191"]["reader_materials"][0]["title"] == "公开合作报道"
    assert result["rows"]["06166"]["reader_materials"][0]["title"] == "公开合作报道"
    assert result["status"] == "PARTIAL_WITH_ROWS"
