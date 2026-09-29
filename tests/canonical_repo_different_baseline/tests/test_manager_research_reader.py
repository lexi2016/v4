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


def _vibe_reader_context(trade_date: str, source_dates: list[str]) -> dict[str, Any]:
    return {
        "plan_trade_date": trade_date,
        "source_dates": source_dates,
        "research_cutoff": "2026-09-26T16:00:00+08:00",
        "focus_window_start": "2026-09-01T15:00:00+08:00",
        "market_session": "20260924",
    }


def _vibe_reader_binding(dates: list[str]) -> dict[str, Any]:
    return {
        "schema_version": "v4.manager_existing_vibe_binding.v1",
        "implementation_manifest_sha256": "a" * 64,
        "input_sha256_by_date": {day: "b" * 64 for day in dates},
    }


def _vibe_reader_material(day: str, *, archive_recorded_at: str | None = None) -> dict[str, Any]:
    return {
        "material_id": f"vibe:{day}",
        "title": "Vibe题材复盘：算力",
        "themes": ["算力"],
        "claim_type": "AGGREGATED_REVIEW_CONTEXT",
        "source_kind": "VIBE_VERIFIED_INPUT",
        "source_market": "A_SHARE",
        "published_at": None,
        "available_at": None,
        "retrieved_at": None,
        "archive_date": day,
        "archive_recorded_at": archive_recorded_at or "2026-09-24T15:05:00+08:00",
        "verification": "OWNER_VERIFIED",
        "source_refs": [{"status": "VERIFIED", "payload_sha256": "c" * 64}],
        "source_row": {"tag": "算力"},
        "fresh_catalyst_eligible": False,
        "identity_status": "A_SHARE_CONTEXT_ONLY_NOT_HK_CANDIDATES",
    }


def test_vibe_fanout_requires_only_a_share_sessions_and_preserves_hk_window(monkeypatch: Any) -> None:
    from v4.manager_research import existing_materials

    source_dates = ["20260924", "20260925", "20260926"]
    read_dates: list[str] = []
    archive_dates: list[str] = []

    class MissingArchiveStore:
        hourly_store = None
        store = None

        def __init__(self) -> None:
            self.hourly_store = self
            self.store = self

        def list_slots(self, day: str, *, mode: str) -> list[str]:
            assert mode == "LIVE"
            archive_dates.append(day)
            return []

        def read_exact(self, _day: str, **_kwargs: Any) -> None:
            return None

    def fake_read(_binding: Any, day: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        read_dates.append(day)
        return [_vibe_reader_material(day)], {"status": "VERIFIED", "payload_sha256": "c" * 64}

    monkeypatch.setattr(existing_materials, "_read_vibe", fake_read)
    result = existing_materials.read_existing_materials(
        "20260926",
        research_source=MissingArchiveStore(),
        vibe_binding=_vibe_reader_binding(["20260924"]),
        context=_vibe_reader_context("20260926", source_dates),
    )

    vibe = result["coverage"]["vibe_binding"]
    assert result["coverage"]["window_dates"] == source_dates
    assert result["plan_context"]["source_dates"] == source_dates
    assert archive_dates == source_dates
    assert read_dates == ["20260924"]
    assert [item.rsplit(":", 1)[-1] for item in vibe["required_inputs"] if item.startswith("input_sha256_by_date:")] == ["20260924"]
    assert vibe["market_scope"] == "A_SHARE_ONLY"
    assert vibe["calendar_status"] == "VERIFIED"
    assert vibe["excluded_dates"] == ["20260925", "20260926"]
    assert vibe["unknown_calendar_dates"] == []
    assert vibe["status"] == "READY_A_SHARE_CONTEXT_ONLY"
    assert vibe["owner_verification_status"] == "VERIFIED"
    assert vibe["projected_material_count"] == vibe["material_count"] == 1
    assert vibe["context_dates"] == ["20260924"]
    assert vibe["empty_dates"] == []


def test_vibe_with_no_legal_a_share_date_cannot_be_ready(monkeypatch: Any) -> None:
    from v4.manager_research import existing_materials

    source_dates = ["20260925", "20260926", "20260927"]
    read_dates: list[str] = []

    def unexpected_read(_binding: Any, day: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        read_dates.append(day)
        raise AssertionError("non-trading dates must not reach the Vibe owner reader")

    monkeypatch.setattr(existing_materials, "_read_vibe", unexpected_read)
    result = existing_materials.read_existing_materials(
        "20260926",
        research_source=None,
        vibe_binding=_vibe_reader_binding(source_dates),
        context=_vibe_reader_context("20260926", source_dates),
    )

    vibe = result["coverage"]["vibe_binding"]
    assert read_dates == []
    assert vibe["a_share_session_dates"] == []
    assert vibe["excluded_dates"] == source_dates
    assert vibe["status"] == "CANNOT_CONFIRM"
    assert vibe["owner_verification_status"] == "NOT_RUN"
    assert vibe["material_count"] == 0
    assert "VIBE_A_SHARE_SESSION_WINDOW_EMPTY" in vibe["gaps"]
    assert "VIBE_A_SHARE_SESSION_WINDOW_EMPTY" in result["gaps"]


def test_vibe_unknown_calendar_date_is_not_read_and_blocks_ready(monkeypatch: Any) -> None:
    from v4.manager_research import existing_materials

    source_dates = ["20260924", "20270104"]
    read_dates: list[str] = []

    def fake_read(_binding: Any, day: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        read_dates.append(day)
        return [_vibe_reader_material(day)], {"status": "VERIFIED", "payload_sha256": "c" * 64}

    monkeypatch.setattr(existing_materials, "_read_vibe", fake_read)
    result = existing_materials.read_existing_materials(
        "20260926",
        research_source=None,
        vibe_binding=_vibe_reader_binding(["20260924"]),
        context=_vibe_reader_context("20260926", source_dates),
    )

    vibe = result["coverage"]["vibe_binding"]
    assert read_dates == ["20260924"]
    assert vibe["market_scope"] == "A_SHARE_ONLY"
    assert vibe["unknown_calendar_dates"] == ["20270104"]
    assert vibe["status"] == "PARTIAL_A_SHARE_CONTEXT_ONLY"
    assert vibe["owner_verification_status"] == "VERIFIED"
    assert vibe["material_count"] == 1
    assert "VIBE_A_SHARE_CALENDAR_UNKNOWN:20270104" in vibe["gaps"]
    assert "VIBE_A_SHARE_CALENDAR_UNKNOWN:20270104" in result["gaps"]


def test_real_vibe_unavailable_theme_tree_has_verified_source_but_no_context(monkeypatch: Any) -> None:
    from v4.manager_research import existing_materials

    payload = {
        "trade_date": "2026-09-24",
        "data_as_of": "2026-09-24T15:05:00+08:00",
        "sources": {"market_facts.theme_tree": {"status": "CANNOT_CONFIRM"}},
        "functions": {
            "get_market_facts": [
                {"status": "READY"},
                {"theme_tree": {"available": False, "themes": []}},
            ]
        },
    }
    verified_binding = {
        "status": "VERIFIED",
        "payload_sha256": "c" * 64,
        "payload_path": "inputs/2026-09-24.json",
    }
    projected = existing_materials.project_vibe_snapshot(payload, verified_binding)
    assert projected == []

    monkeypatch.setattr(
        existing_materials,
        "_read_vibe",
        lambda _binding, _day: (projected, verified_binding),
    )
    result = existing_materials.read_existing_materials(
        "20260926",
        research_source=None,
        vibe_binding=_vibe_reader_binding(["20260924"]),
        context=_vibe_reader_context("20260926", ["20260924"]),
    )

    vibe = result["coverage"]["vibe_binding"]
    assert vibe["verified_dates"] == ["20260924"]
    assert vibe["owner_verification_status"] == "VERIFIED"
    assert vibe["status"] == "CANNOT_CONFIRM"
    assert vibe["projected_material_count"] == 0
    assert vibe["material_count"] == 0
    assert vibe["usable_context_available"] is False
    assert vibe["projection_counts_by_date"] == {
        "20260924": {"projected": 0, "usable_after_temporal_filter": 0}
    }
    assert vibe["empty_dates"] == ["20260924"]
    assert vibe["projection_empty_dates"] == ["20260924"]
    assert vibe["availability_reason"] == "来源已校验，但暂无可用的主题资料"
    gap = "VIBE_VERIFIED_INPUT_HAS_NO_USABLE_THEME_ROWS:20260924"
    assert gap in vibe["gaps"]
    assert gap in result["gaps"]


def test_empty_vibe_context_does_not_remove_verified_archive_material(monkeypatch: Any) -> None:
    from v4.manager_research import existing_materials
    from infrastructure.data_store import _sha256

    class ArchiveSource:
        def __init__(self) -> None:
            self.hourly_store = self
            self.store = self
            self.payload = {
                "archive_date": "20260924",
                "source_generated_at": "2026-09-24T10:07:00+08:00",
                "articles": [{
                    "article_id": "news-1",
                    "title": "已验证的公司新闻",
                    "published_at": "2026-09-24T10:00:00+08:00",
                    "available_at": "2026-09-24T10:05:00+08:00",
                    "retrieved_at": "2026-09-24T10:06:00+08:00",
                    "themes": ["算力"],
                    "market": "HK_CONNECT",
                    "source_type": "NEWS",
                    "source_url": "https://example.test/news-1",
                }],
            }
            self.binding = {
                "status": "VERIFIED",
                "payload_path": "archive/20260924.json",
                "payload_sha256": _sha256(self.payload),
            }

        def list_slots(self, _day: str, *, mode: str) -> list[str]:
            assert mode == "LIVE"
            return []

        def read_exact(self, day: str, **_kwargs: Any) -> dict[str, Any]:
            assert day == "20260924"
            return self.payload

        def artifact_binding(self, date: str, *, slot: str, mode: str) -> dict[str, Any]:
            assert date == "20260924"
            assert slot == ""
            assert mode == "LIVE"
            return self.binding

    monkeypatch.setattr(
        existing_materials,
        "_read_vibe",
        lambda _binding, _day: ([], {"status": "VERIFIED", "payload_sha256": "c" * 64}),
    )

    result = existing_materials.read_existing_materials(
        "20260926",
        research_source=ArchiveSource(),
        vibe_binding=_vibe_reader_binding(["20260924"]),
        context=_vibe_reader_context("20260926", ["20260924"]),
    )

    assert [item["original_article_id"] for item in result["materials"]] == ["news-1"]
    assert result["materials"][0]["verification"] == "OWNER_VERIFIED"
    assert result["materials"][0]["source_market"] == "HK_CONNECT"
    assert result["coverage"]["material_count"] == 1
    assert result["coverage"]["vibe_binding"]["status"] == "CANNOT_CONFIRM"
    assert result["coverage"]["vibe_binding"]["owner_verification_status"] == "VERIFIED"


def test_mixed_vibe_dates_are_partial_and_keep_usable_context(monkeypatch: Any) -> None:
    from v4.manager_research import existing_materials

    dates = ["20260923", "20260924"]
    monkeypatch.setattr(
        existing_materials,
        "_read_vibe",
        lambda _binding, day: (
            ([_vibe_reader_material(day)] if day == "20260924" else []),
            {"status": "VERIFIED", "payload_sha256": "c" * 64},
        ),
    )
    result = existing_materials.read_existing_materials(
        "20260926",
        research_source=None,
        vibe_binding=_vibe_reader_binding(dates),
        context=_vibe_reader_context("20260926", dates),
    )

    vibe = result["coverage"]["vibe_binding"]
    assert vibe["verified_dates"] == dates
    assert vibe["owner_verification_status"] == "VERIFIED"
    assert vibe["status"] == "PARTIAL_A_SHARE_CONTEXT_ONLY"
    assert vibe["usable_context_available"] is True
    assert vibe["projected_material_count"] == 1
    assert vibe["material_count"] == 1
    assert vibe["projection_counts_by_date"] == {
        "20260923": {"projected": 0, "usable_after_temporal_filter": 0},
        "20260924": {"projected": 1, "usable_after_temporal_filter": 1},
    }
    assert vibe["context_dates"] == ["20260924"]
    assert vibe["empty_dates"] == ["20260923"]
    assert "VIBE_VERIFIED_INPUT_HAS_NO_USABLE_THEME_ROWS:20260923" in vibe["gaps"]


def test_vibe_context_count_uses_rows_after_temporal_filter(monkeypatch: Any) -> None:
    from v4.manager_research import existing_materials

    day = "20260924"
    too_late = _vibe_reader_material(day, archive_recorded_at="2026-09-27T10:00:00+08:00")
    monkeypatch.setattr(
        existing_materials,
        "_read_vibe",
        lambda _binding, _day: ([too_late], {"status": "VERIFIED", "payload_sha256": "c" * 64}),
    )
    result = existing_materials.read_existing_materials(
        "20260926",
        research_source=None,
        vibe_binding=_vibe_reader_binding([day]),
        context=_vibe_reader_context("20260926", [day]),
    )

    vibe = result["coverage"]["vibe_binding"]
    assert vibe["owner_verification_status"] == "VERIFIED"
    assert vibe["status"] == "CANNOT_CONFIRM"
    assert vibe["projected_material_count"] == 1
    assert vibe["material_count"] == 0
    assert vibe["projection_counts_by_date"] == {
        day: {"projected": 1, "usable_after_temporal_filter": 0}
    }
    assert vibe["empty_dates"] == [day]
    assert "VIBE_CONTEXT_EMPTY_AFTER_TEMPORAL_FILTER:20260924" in vibe["gaps"]
    assert result["coverage"]["excluded_after_cutoff_count"] == 1
