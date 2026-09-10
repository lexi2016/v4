from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.v35_api.app import create_app
from contracts.research import DEDUPE_KEY_FIELDS, validate_research_archive
from domains.research import build_research_archive
from infrastructure.research_store import ResearchArchiveStore
from ops.import_research_archive import import_research_archive_file


def _source(archive_date: str = "20260730") -> dict:
    dashed = f"{archive_date[:4]}-{archive_date[4:6]}-{archive_date[6:]}"
    timeline = [
        {
            "stock_code": "000001",
            "stock_name": "平安银行",
            "event_time": f"{dashed}T09:00:00",
            "source_published_at": f"{dashed}T08:31:00+08:00",
            "first_seen_at": f"{dashed}T08:32:00+08:00",
            "last_checked_at": f"{dashed}T09:00:00+08:00",
            "source_type": "hourly_research",
            "source_name": "08:30早盘新闻",
            "source_title": "银行板块跟踪",
            "source_path": r"C:\legacy\morning.csv",
            "url": "https://example.test/a",
            "theme": "银行",
            "catalyst": "业绩",
            "evidence_sentence": "短证据",
            "evidence_level": "L2_MEDIUM",
            "confidence": "MEDIUM",
            "dedup_key": "source-a",
        },
        {
            "stock_code": "000001",
            "stock_name": "平安银行",
            "event_time": f"{dashed}T09:01:00+08:00",
            "source_published_at": f"{dashed}T08:31:00+08:00",
            "first_seen_at": f"{dashed}T08:32:00+08:00",
            "last_checked_at": f"{dashed}T09:01:00+08:00",
            "source_type": "hourly_research",
            "source_name": "08:30早盘新闻",
            "source_title": "银行板块跟踪",
            "source_path": r"C:\legacy\morning.csv",
            "url": "https://example.test/a",
            "theme": "银行",
            "catalyst": "业绩",
            "evidence_sentence": "这是保留下来的更长证据句。",
            "evidence_level": "L2_MEDIUM",
            "confidence": "HIGH",
            "dedup_key": "source-b",
        },
        {
            "stock_code": "00700",
            "stock_name": "腾讯控股",
            "event_time": f"{dashed}T10:00:00+08:00",
            "source_published_at": f"{dashed}T09:55:00+08:00",
            "first_seen_at": f"{dashed}T09:56:00+08:00",
            "last_checked_at": f"{dashed}T10:00:00+08:00",
            "source_type": "zsxq",
            "source_name": "知识星球",
            "source_title": "互联网观察",
            "source_path": r"C:\legacy\zsxq.json",
            "url": "https://example.test/b",
            "theme": "互联网",
            "catalyst": "产品",
            "evidence_sentence": "港股研报证据。",
            "evidence_level": "L3_STRONG",
            "confidence": "HIGH",
            "dedup_key": "source-c",
        },
    ]
    daily = []
    bridge = []
    for code, name, score in (("000001", "平安银行", 88), ("00700", "腾讯控股", 76)):
        daily.append(
            {
                "stock_code": code,
                "stock_name": name,
                "first_seen_time": f"{dashed}T08:32:00+08:00",
                "last_seen_time": f"{dashed}T10:00:00+08:00",
                "research_score": score,
                "research_status": "REPEATED",
                "evidence_count": 2,
                "source_count": 1,
                "strong_evidence_count": 1,
                "medium_evidence_count": 1,
                "weak_evidence_count": 0,
                "source_types": ["hourly_research"],
                "themes": ["研究主题"],
                "top_catalysts": ["研究催化"],
            }
        )
        bridge.append(
            {
                "stock_code": code,
                "formal_overlap": code == "000001",
                "stage_overlap": code == "00700",
            }
        )
    return {
        "schema_version": "v3_research_lane.v2",
        "trade_date": archive_date,
        "source_manifest": {"generated_at": f"{dashed}T23:00:00+08:00"},
        "stock_research_timeline": timeline,
        "stock_research_daily": daily,
        "research_pool_bridge": bridge,
        "cannot_confirm": [{"reason": "legacy gap"}],
    }


def _archive(archive_date: str = "20260730", *, marker: str = "a") -> dict:
    return build_research_archive(_source(archive_date), source_input_sha256=marker * 64)


def test_graph_defined_dedupe_preserves_full_pool_and_timezone_contract() -> None:
    source = _source()
    source["stock_research_timeline"][0]["evidence_sentence"] = (
        "输入位于 C:\\Users\\owner\\Desktop\\学习\\v3_system\\30_runtime\\a.csv；"
        "第二份 C:\\Users\\owner\\Desktop\\学习\\v3_system\\40_artifacts\\b.json"
    )
    archive = build_research_archive(source, source_input_sha256="a" * 64)

    assert archive["dedupe_key_fields"] == list(DEDUPE_KEY_FIELDS)
    assert archive["article_count"] == 2
    assert archive["stock_pool_count"] == 2
    assert archive["articles"][0]["duplicate_evidence_count"] == 1
    duplicated = next(row for row in archive["articles"] if row["stock_code"] == "000001")
    assert duplicated["duplicate_evidence_count"] == 2
    assert duplicated["source_dedup_keys"] == ["source-a", "source-b"]
    assert duplicated["evidence_sentence"].count("[LEGACY_PATH_SHA256:") == 2
    serialized = json.dumps(archive, ensure_ascii=False)
    assert "C:\\legacy" not in serialized
    assert "\\v3_system\\" not in serialized
    assert "Users\\owner" not in serialized
    assert any(
        item.startswith("LEGACY_RUNTIME_PATHS_REDACTED:")
        for item in archive["cannot_confirm"]
    )
    for row in archive["articles"]:
        for field in ("published_at", "collected_at", "first_seen_at"):
            parsed = datetime.fromisoformat(row[field])
            assert parsed.utcoffset() is not None
            assert row[field].endswith("+08:00")
    assert validate_research_archive(archive) == "20260730"


def test_naive_legacy_timestamps_are_visible_cannot_confirm_not_silently_hidden() -> None:
    source = _source()
    source["stock_research_timeline"][2]["source_published_at"] = ""
    source["stock_research_timeline"][2]["event_time"] = "2026-07-30T10:00:00"
    archive = build_research_archive(source, source_input_sha256="b" * 64)

    assert "LEGACY_NAIVE_TIMESTAMP_ASSUMED_ASIA_SHANGHAI" in archive["cannot_confirm"]
    assert archive["articles"][0]["published_at"].endswith("+08:00")


def test_backfill_and_replay_never_update_latest_but_live_does(tmp_path: Path) -> None:
    store = ResearchArchiveStore(tmp_path / "data")
    old = _archive("20260725", marker="b")
    current = _archive("20260730", marker="c")

    assert store.publish(old, mode="BACKFILL")["latest_updated"] is False
    assert store.publish(current, mode="REPLAY")["latest_updated"] is False
    assert store.read_exact("20260725") == old
    assert store.read_exact("20260730") == current
    assert store.read_latest() is None

    assert store.publish(current, mode="LIVE")["latest_updated"] is True
    assert store.read_latest() == current
    assert store.publish(old, mode="BACKFILL")["latest_updated"] is False
    assert store.read_latest() == current
    with pytest.raises(ValueError, match="backwards"):
        store.publish(old, mode="LIVE")


def test_importer_reads_explicit_external_bom_file_without_mutating_it(tmp_path: Path) -> None:
    source = tmp_path / "external" / "snapshot.json"
    source.parent.mkdir()
    source.write_text(json.dumps(_source(), ensure_ascii=False), encoding="utf-8-sig")
    before = source.read_bytes()

    result = import_research_archive_file(
        data_root=tmp_path / ".runtime" / "data",
        source=source,
        mode="BACKFILL",
    )

    assert source.read_bytes() == before
    assert result["external_source_unchanged"] is True
    assert result["external_source_sha256"] == hashlib.sha256(before).hexdigest()
    assert result["publication"]["latest_updated"] is False


def test_store_fails_closed_on_manifest_receipt_and_reparse_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ResearchArchiveStore(tmp_path / "data")
    store.publish(_archive(), mode="BACKFILL")
    receipt = tmp_path / "data" / "receipts" / "research" / "archives" / "20260730.json"
    receipt.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest or receipt"):
        store.read_exact("20260730")

    root = tmp_path / "reparse-data"
    ancestor = root / "research"
    ancestor.mkdir(parents=True)
    import infrastructure.owned_path as owned_path

    monkeypatch.setattr(owned_path, "_is_reparse_point", lambda path: path == ancestor)
    with pytest.raises(ValueError, match="reparse"):
        ResearchArchiveStore(root).read_exact("20260730")


def test_publish_rejects_reparse_ancestor_before_creating_missing_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import infrastructure.owned_path as owned_path

    reparse_ancestor = tmp_path / "junction"
    reparse_ancestor.mkdir()
    root = reparse_ancestor / "missing" / "data"
    monkeypatch.setattr(
        owned_path,
        "_is_reparse_point",
        lambda path: path == reparse_ancestor,
    )

    with pytest.raises(ValueError, match="reparse"):
        ResearchArchiveStore(root).publish(_archive(), mode="BACKFILL")

    assert not (reparse_ancestor / "missing").exists()


def test_missing_payload_claimed_by_manifest_fails_closed(tmp_path: Path) -> None:
    store = ResearchArchiveStore(tmp_path / "data")
    store.publish(_archive(), mode="BACKFILL")
    (tmp_path / "data" / "research" / "archives" / "20260730.json").unlink()

    with pytest.raises(ValueError, match="manifest or receipt"):
        store.read_exact("20260730")


def test_exact_and_latest_are_separate_actual_requests_with_typed_missing(tmp_path: Path) -> None:
    store = ResearchArchiveStore(tmp_path / "data")
    store.publish(_archive("20260725", marker="d"), mode="BACKFILL")
    store.publish(_archive("20260730", marker="e"), mode="LIVE")
    client = TestClient(create_app(data_root=store.root))

    exact = client.get("/api/v3/research/articles", params={"archive_date": "20260725"})
    latest = client.get("/api/v3/research/articles/latest")
    missing = client.get("/api/v3/research/articles", params={"archive_date": "20260217"})

    assert exact.status_code == latest.status_code == missing.status_code == 200
    assert exact.json()["endpoint_mode"] == "EXACT"
    assert exact.json()["archive_date"] == "20260725"
    assert latest.json()["endpoint_mode"] == "LATEST"
    assert latest.json()["archive_date"] == "20260730"
    assert missing.json()["status"] == "NOT_MATERIALIZED"
    assert missing.json()["archive_date"] == "20260217"
    assert missing.json()["loading_complete"] is True
    assert missing.json()["cannot_confirm"] == ["RESEARCH_ARCHIVE_NOT_MATERIALIZED:20260217"]
    for body in (exact.json(), latest.json(), missing.json()):
        assert body["production_allowed"] is False
        assert body["buy_gate_updated"] is False
        assert body["orders_sent"] is False


@pytest.mark.parametrize("archive_date", ["20260730", "20260725", "20260217"])
def test_exact_date_matrix_never_falls_back(archive_date: str, tmp_path: Path) -> None:
    store = ResearchArchiveStore(tmp_path / "data")
    store.publish(_archive(archive_date, marker=archive_date[-1]), mode="BACKFILL")
    client = TestClient(create_app(data_root=store.root))

    body = client.get(
        "/api/v3/research/articles", params={"archive_date": archive_date}
    ).json()
    miss = client.get(
        "/api/v3/research/articles", params={"archive_date": "20260701"}
    ).json()

    assert body["archive_date"] == archive_date
    assert body["status"] == "READY"
    assert miss["status"] == "NOT_MATERIALIZED"
    assert miss["archive_date"] == "20260701"


def test_contract_rejects_unknown_fields_wrong_timezones_and_empty_data() -> None:
    archive = _archive()
    unknown = {**archive, "extra": True}
    with pytest.raises(ValueError, match="fields"):
        validate_research_archive(unknown)

    naive = deepcopy(archive)
    naive["articles"][0]["published_at"] = "2026-07-30T10:00:00"
    with pytest.raises(ValueError, match="timezone"):
        validate_research_archive(naive)

    empty = deepcopy(archive)
    empty["articles"] = []
    empty["article_count"] = 0
    with pytest.raises(ValueError, match="requires articles"):
        validate_research_archive(empty)
