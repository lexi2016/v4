from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

API_ROOT = Path(__file__).resolve().parents[1] / "release" / "api_app"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from ops import manager_announcement_body_batch as body_batch

SOURCE_RUN = Path("/Users/lexi/Desktop/学习/agents调试/V4_ANNOUNCEMENT_DAILY_REPAIR_20261007/daily_runs/20261007_20261006")
TARGET = "20261007"
PUBLICATION = "2026-10-06"


def _catalog_read() -> dict:
    return json.loads((SOURCE_RUN / "evidence/candidate_api_catalog_get.json").read_text(encoding="utf-8"))


def _isolated_materials(tmp_path: Path) -> Path:
    source = SOURCE_RUN / "candidate_state/materials"
    target = tmp_path / "materials"
    shutil.copytree(source, target)
    return target


class _CacheOnlyProvider:
    def __init__(self, *, material_store, timeout: float):
        self._material_store = material_store
        self._timeout = timeout

    def _request_eastmoney_hk(self, url: str, *, timeout: float):
        raise AssertionError(f"network request attempted in offline replay: {url}")


def test_full_580_article_replay_is_complete_and_network_free(tmp_path: Path) -> None:
    materials = _isolated_materials(tmp_path)
    result = body_batch.run_capture(_catalog_read(), materials, tmp_path / "good",
        TARGET, PUBLICATION, api_overrides={"HkexOfficialProvider": _CacheOnlyProvider})
    assert result["status"] == "PASS_COMPLETE_CONTENT_API_BODIES_ALL_ROWS"
    assert result["article_rows"] == result["terminal_article_receipts"] == 580
    assert result["body_status_counts"] == {"COMPLETE_CONTENT_API_BODY": 580}
    assert result["limits"]["physical_requests"] == 0
    corpus = json.loads((tmp_path / "good/body_corpus.json").read_text(encoding="utf-8"))
    assert corpus["schema"] == "v4.manager_research.eastmoney_hk_announcement_body_corpus.v3"
    assert corpus["article_count"] == len(corpus["rows"]) == 580
    assert corpus["transport_complete_body_count"] == 580
    assert sum(len(row["pages"]) for row in corpus["rows"]) == 1385
    assert all(row["body_text"] and row["transport_semantic_status"] == "NOT_REVIEWED"
               for row in corpus["rows"])
    from ops import run_manager_daily_announcement as daily_cli
    catalog_path = tmp_path / "good/catalog_read.json"
    catalog_path.write_text(json.dumps(_catalog_read(), ensure_ascii=False), encoding="utf-8")
    prepared = daily_cli._build(SimpleNamespace(
        target_date=TARGET, publication_date=PUBLICATION,
        catalog_read=str(catalog_path),
        semantic_catalog=str(SOURCE_RUN / "evidence/semantic_catalog_20261007_v3.json"),
        body_corpus=str(tmp_path / "good/body_corpus.json"), out=None,
        decisions=None, review_receipt=None,
    ), reviewed=False)
    assert prepared["status"] == "PREPARED_EXACT_INPUTS"
    assert prepared["decision_status"] == "NOT_ASSESSED"


def test_one_article_failure_does_not_stop_the_remaining_579(tmp_path: Path) -> None:
    materials = _isolated_materials(tmp_path)
    from v4.manager_research import announcement_source
    original_capture = announcement_source.capture_eastmoney
    failed_article = "AN202610061830161427"

    def fail_one(provider, url, *, budget=None, force=False):
        query = parse_qs(urlparse(url).query)
        if query.get("art_code") == [failed_article]:
            raise ValueError("INJECTED_ARTICLE_FAILURE")
        return original_capture(provider, url, budget=budget, force=force)

    result = body_batch.run_capture(_catalog_read(), materials, tmp_path / "partial",
        TARGET, PUBLICATION, api_overrides={
            "HkexOfficialProvider": _CacheOnlyProvider,
            "capture_eastmoney": fail_one,
        })
    assert result["status"] == "PARTIAL_BODY_MATERIAL_CAPTURE_WITH_TERMINAL_GAPS"
    assert result["article_rows"] == result["terminal_article_receipts"] == 580
    assert result["body_status_counts"]["BODY_CAPTURE_FAILED"] == 1
    assert result["body_status_counts"]["COMPLETE_CONTENT_API_BODY"] == 579
    assert result["semantic_status"] == "NOT_REVIEWED"
    corpus = json.loads((tmp_path / "partial/body_corpus.json").read_text(encoding="utf-8"))
    failed = [row for row in corpus["rows"] if row["art_code"] == failed_article]
    assert len(failed) == 1 and failed[0]["body_status"] == "BODY_CAPTURE_FAILED"
