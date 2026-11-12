"""Read-only research stock clue aggregation, link prior and API contracts."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.v35_api.research_lane_router import create_research_lane_router
from infrastructure.pdf_research_cards import RESEARCH_ROOT_RELATIVE
from infrastructure.research_stock_clues import (
    MAX_CLUE_LIMIT,
    MAX_REPORT_BYTES,
    MAX_TITLES_PER_STOCK,
    SCHEMA_VERSION,
    read_stock_clues,
)

NAME_MAP_RELATIVE = Path("workspace") / "数据" / "data_layer_interface_current" / "CURRENT_SELECTOR_READY_PANEL.txt"


def _document_id(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _data_root(tmp_path: Path) -> Path:
    """Run the layer with a state-style root so the pointer stays inside tmp."""
    return tmp_path / "state" / "data"


def _research_root(data_root: Path) -> Path:
    return data_root / RESEARCH_ROOT_RELATIVE


def _write_card(
    data_root: Path,
    *,
    seed: str,
    report_text: str,
    source_date_cn: str = "2026年10月16日",
    batch: str = "batch-001",
    pdf_filename: str = "示例研报.pdf",
    pad_head: bool = True,
) -> str:
    document_id = _document_id(seed)
    document_dir = _research_root(data_root) / "batches" / batch / "documents" / document_id
    document_dir.mkdir(parents=True, exist_ok=True)
    page_input = document_dir / "page-input.json"
    page_input.write_text(
        json.dumps({"source": {"pdf_path": f"/外置/知识星球/{source_date_cn}/{pdf_filename}"}}),
        encoding="utf-8",
    )
    report = document_dir / "report.md"
    # Real reports start with a title/attribution region that the clue layer
    # deliberately skips; synthetic reports pad that region by default.
    text = ("研究标题与来源署名占位。\n" * 30 + report_text) if pad_head else report_text
    report.write_text(text, encoding="utf-8")
    receipt = {
        "schema": "v4.pdf_research_simple_batch.document_receipt.v1",
        "document_id": document_id,
        "pdf_sha256": document_id,
        "status": "SUCCEEDED",
        "page_input": {"path": str(page_input), "bytes": 1, "sha256": "a" * 64},
        "report": {"path": str(report), "bytes": len(text.encode("utf-8")), "sha256": "b" * 64},
        "report_metadata": {
            "origin_status": "MODEL_GENERATED",
            "source_review_status": "SOURCE_REVIEW_PENDING",
            "user_acceptance_status": "NOT_ACCEPTED",
        },
    }
    (document_dir / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    return document_id


def _name_rows() -> list[dict[str, object]]:
    return [
        # Current date (the newest date that still carries names).
        {"trade_date": "20261016", "ts_code": "600001.SH", "name": "测试股份", "tdx_industry_code": "T0101"},
        {"trade_date": "20261016", "ts_code": "600002.SH", "name": "样本科技", "tdx_industry_code": "T0101"},
        {"trade_date": "20261016", "ts_code": "600003.SZ", "name": "机器人", "tdx_industry_code": "T0201"},
        {"trade_date": "20261016", "ts_code": "600004.SH", "name": "中信建投", "tdx_industry_code": None},
        {"trade_date": "20261016", "ts_code": "600005.SH", "name": "某某证券", "tdx_industry_code": "T0101"},
        {"trade_date": "20261016", "ts_code": "600006.SH", "name": "华泰证券", "tdx_industry_code": "T1002"},
        {"trade_date": "20261016", "ts_code": "000001.SZ", "name": "短名", "tdx_industry_code": "T0101"},
        {"trade_date": "20261016", "ts_code": "000002.SZ", "name": "空格 名称", "tdx_industry_code": "T0101"},
        # Older date must lose to the newest non-null date.
        {"trade_date": "20261015", "ts_code": "999999.SH", "name": "测试股份", "tdx_industry_code": "T0101"},
        # Newest date has no names at all and must not erase the 20261016 map.
        {"trade_date": "20261017", "ts_code": "600001.SH", "name": None, "tdx_industry_code": None},
    ]


def _write_name_table(
    tmp_path: Path,
    data_root: Path,
    *,
    parquet: bool = True,
    rows: list[dict[str, object]] | None = None,
) -> Path:
    pointer = data_root.parent / NAME_MAP_RELATIVE
    pointer.parent.mkdir(parents=True, exist_ok=True)
    parquet_path = tmp_path / "names.parquet"
    if parquet:
        pd.DataFrame(_name_rows() if rows is None else rows).to_parquet(parquet_path, index=False)
    pointer.write_text(f"{parquet_path}\n", encoding="utf-8")
    return parquet_path


def _clues_by_code(result: dict) -> dict[str, dict]:
    return {item["ts_code"]: item for item in result["items"]}


def _weak_by_code(result: dict) -> dict[str, dict]:
    return {item["ts_code"]: item for item in result["weak_items"]}


def _generic_by_name(result: dict) -> dict[str, dict]:
    return {entry["name"]: entry for entry in result["generic_filtered"]}


def test_name_and_code_hits_aggregate_across_cards(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    _write_name_table(tmp_path, data_root)
    _write_card(
        data_root,
        seed="card-a",
        pdf_filename="a.pdf",
        report_text=(
            "正文提到测试股份，也提到测试股份，以及 600001.SH 和 600002.SH。\n\n"
            "行业还提到机器人标的。"
        ),
    )
    _write_card(
        data_root,
        seed="card-b",
        pdf_filename="b.pdf",
        report_text="正文只提代码 600002.SH，不写公司名。",
    )
    _write_card(
        data_root,
        seed="card-c",
        pdf_filename="c.pdf",
        report_text="再次提到测试股份，同时出现 600002.SH。",
    )

    result = read_stock_clues(data_root, "20261016")

    assert result["schema_version"] == SCHEMA_VERSION
    assert result["status"] == "READY"
    assert result["card_count"] == 3
    assert result["scanned_card_count"] == 3
    assert result["stock_count"] == 3
    assert result["confirmed_stock_count"] == 2
    assert result["weak_only_stock_count"] == 1
    assert result["name_map_status"] == "READY"
    assert result["name_map_trade_date"] == "20261016"
    assert result["corpus_report_count"] == 3
    assert result["corpus_cache_status"] == "BUILT"
    assert result["research_only"] is True
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False

    by_code = _clues_by_code(result)
    assert set(by_code) == {"600001.SH", "600002.SH"}
    # 600001 appears in two distinct cards despite two mentions in card-a.
    assert by_code["600001.SH"]["document_count"] == 2
    assert by_code["600001.SH"]["name"] == "测试股份"
    assert by_code["600001.SH"]["matched_by"] == "BOTH"
    assert by_code["600001.SH"]["document_titles"] == ["a", "c"]
    # total=3 and every occurrence carries the "股份" self-marker; raw ratio.
    assert by_code["600001.SH"]["link_probability"] == pytest.approx(1.0)
    # 600002: CODE in card-a, CODE in b, CODE in c -> one count per card.
    assert by_code["600002.SH"]["document_count"] == 3
    assert by_code["600002.SH"]["matched_by"] == "CODE"
    # 600003 is a single weak name hit in a paragraph without a confirmed peer.
    weak = _weak_by_code(result)
    assert set(weak) == {"600003.SZ"}
    assert "600003.SZ" not in by_code
    assert weak["600003.SZ"]["weak_document_count"] == 1
    assert weak["600003.SZ"]["link_probability"] == pytest.approx(1.0)
    for item in by_code.values():
        assert item["first_seen_date"] == "20261016"
        assert item["last_seen_date"] == "20261016"


def test_weak_targets_never_enter_items(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    _write_name_table(tmp_path, data_root)
    _write_card(
        data_root,
        seed="mixed-weak",
        report_text="正文提到测试股份，代码 600001.SH；另提机器人概念。",
    )

    result = read_stock_clues(data_root, "20261016")

    by_code = _clues_by_code(result)
    weak = _weak_by_code(result)
    assert set(by_code) == {"600001.SH"}
    assert set(weak) == {"600003.SZ"}
    assert not (set(by_code) & set(weak))
    assert all(item["document_count"] >= 1 for item in by_code.values())
    assert result["weak_items"][0]["ts_code"] == "600003.SZ"


def test_weak_items_are_capped_and_sorted(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    rows = [
        {
            "trade_date": "20261016",
            "ts_code": f"601{index:03d}.SH",
            "name": f"样本{index:02d}",
            "tdx_industry_code": "T0201",
        }
        for index in range(23)
    ]
    _write_name_table(tmp_path, data_root, rows=rows)
    for index in range(23):
        _write_card(
            data_root,
            seed=f"weak-{index}",
            batch=f"weak-{index}",
            pdf_filename=f"弱-{index}.pdf",
            report_text=f"样本{index:02d}。",
        )
    for index in range(2):
        _write_card(
            data_root,
            seed=f"weak-extra-{index}",
            batch=f"weak-extra-{index}",
            pdf_filename=f"弱-额外-{index}.pdf",
            report_text=f"样本{index:02d}。",
        )

    result = read_stock_clues(data_root, "20261016")

    assert result["items"] == []
    assert result["weak_only_stock_count"] == 23
    assert len(result["weak_items"]) == 20
    assert [entry["ts_code"] for entry in result["weak_items"]] == [
        f"601{index:03d}.SH" for index in range(20)
    ]
    assert [entry["weak_document_count"] for entry in result["weak_items"]] == [2, 2] + [1] * 18
    for entry in result["weak_items"]:
        assert set(entry) == {
            "name",
            "ts_code",
            "weak_document_count",
            "link_probability",
        }


def test_head_signature_region_is_skipped(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    _write_name_table(tmp_path, data_root)
    header = "测试股份 600001.SH 中信建投 某某证券 " + "题头" * 150
    assert len(header) >= 300
    _write_card(
        data_root,
        seed="head-only",
        report_text=header + "\n正文没有可解析标的。",
        pad_head=False,
    )

    result = read_stock_clues(data_root, "20261016")

    assert result["status"] == "READY_EMPTY"
    assert result["items"] == []
    assert result["stock_count"] == 0


def test_broker_entities_are_excluded(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    _write_name_table(tmp_path, data_root)
    _write_card(
        data_root,
        seed="brokers",
        report_text="正文提及中信建投、某某证券与华泰证券，但不涉及上市公司标的。",
    )

    result = read_stock_clues(data_root, "20261016")

    assert result["status"] == "READY_EMPTY"
    assert result["items"] == []


def test_generic_word_without_company_context_is_filtered(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    _write_name_table(tmp_path, data_root)
    _write_card(
        data_root,
        seed="plain-word",
        report_text=("机器人。" * 10),
    )

    result = read_stock_clues(data_root, "20261016")

    assert result["status"] == "READY_EMPTY"
    assert result["confirmed_stock_count"] == 0
    assert result["weak_only_stock_count"] == 0
    assert result["stock_count"] == 0
    assert result["items"] == []
    generic = _generic_by_name(result)["机器人"]
    assert generic["ts_code"] == "600003.SZ"
    assert generic["total"] == 10
    assert generic["link_probability"] == pytest.approx(0.0)
    assert result["corpus_report_count"] == 1


def test_insufficient_sample_is_weak_not_generic(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    _write_name_table(
        tmp_path,
        data_root,
        rows=[
            {"trade_date": "20261016", "ts_code": "002913.SZ", "name": "奥士康", "tdx_industry_code": "T0201"},
        ],
    )
    _write_card(data_root, seed="small-sample", report_text="奥士康。奥士康。")

    result = read_stock_clues(data_root, "20261016")

    assert result["items"] == []
    item = _weak_by_code(result)["002913.SZ"]
    assert item["weak_document_count"] == 1
    assert item["link_probability"] == pytest.approx(0.0)
    assert result["weak_only_stock_count"] == 1
    assert result["generic_filtered"] == []


def test_ratio_one_third_is_weak_not_generic(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    _write_name_table(
        tmp_path,
        data_root,
        rows=[
            {"trade_date": "20261016", "ts_code": "002913.SZ", "name": "奥士康", "tdx_industry_code": "T0201"},
        ],
    )
    _write_card(
        data_root,
        seed="one-third-context",
        batch="one-third-context",
        pdf_filename="上下文.pdf",
        report_text="奥士康公司发布公告。奥士康公司披露订单。奥士康公司再获订单。",
    )
    for index in range(6):
        _write_card(
            data_root,
            seed=f"one-third-plain-{index}",
            batch=f"one-third-plain-{index}",
            pdf_filename=f"平文-{index}.pdf",
            report_text="奥士康。",
        )

    result = read_stock_clues(data_root, "20261016")

    assert result["items"] == []
    item = _weak_by_code(result)["002913.SZ"]
    assert item["weak_document_count"] == 7
    assert item["link_probability"] == pytest.approx(1 / 3)
    assert result["weak_only_stock_count"] == 1
    assert result["generic_filtered"] == []


def test_generic_boundary_includes_exact_twenty_percent(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    _write_name_table(tmp_path, data_root)
    for index in range(2):
        _write_card(
            data_root,
            seed=f"boundary-context-{index}",
            batch=f"boundary-context-{index}",
            pdf_filename=f"上下文-{index}.pdf",
            report_text="标的：机器人。",
        )
    for index in range(8):
        _write_card(
            data_root,
            seed=f"boundary-plain-{index}",
            batch=f"boundary-plain-{index}",
            pdf_filename=f"平文-{index}.pdf",
            report_text="机器人。",
        )

    result = read_stock_clues(data_root, "20261016")

    generic = _generic_by_name(result)["机器人"]
    assert generic["total"] == 10
    assert generic["link_probability"] == pytest.approx(0.2)
    assert result["items"] == []


def test_single_context_hit_is_weak_not_confirmed(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    _write_name_table(tmp_path, data_root)
    _write_card(
        data_root,
        seed="cross-clause",
        report_text="成交额>10亿的公司中，芯片、机器人、AI概念分别有130、85、64家。",
    )

    result = read_stock_clues(data_root, "20261016")

    assert result["status"] == "READY_EMPTY"
    assert result["confirmed_stock_count"] == 0
    assert result["items"] == []
    item = _weak_by_code(result)["600003.SZ"]
    assert item["weak_document_count"] == 1
    assert item["link_probability"] == pytest.approx(1.0)


def test_three_context_hits_confirm_name_hit(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    _write_name_table(
        tmp_path,
        data_root,
        rows=[
            {"trade_date": "20261016", "ts_code": "002913.SZ", "name": "奥士康", "tdx_industry_code": "T0201"},
        ],
    )
    _write_card(
        data_root,
        seed="context",
        report_text="奥士康股份发布公告。奥士康公司披露订单。奥士康股份再获订单。",
    )

    result = read_stock_clues(data_root, "20261016")

    assert result["status"] == "READY"
    assert result["confirmed_stock_count"] == 1
    assert result["weak_only_stock_count"] == 0
    item = _clues_by_code(result)["002913.SZ"]
    assert item["document_count"] == 1
    assert item["weak_document_count"] == 0
    assert item["confirm_reasons"] == ["CONTEXT"]
    assert item["link_probability"] == pytest.approx(1.0)


def test_code_hit_confirms_even_when_name_prior_is_generic(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    _write_name_table(
        tmp_path,
        data_root,
        rows=[
            {"trade_date": "20261016", "ts_code": "300024.SZ", "name": "机器人", "tdx_industry_code": "T0201"},
        ],
    )
    # Ten company-free mentions live in older reports; the requested-day report
    # only carries the explicit code.  The prior stays below the generic line,
    # but CODE has priority and must confirm the target.
    for index in range(10):
        _write_card(
            data_root,
            seed=f"prior-{index}",
            batch=f"prior-batch-{index}",
            source_date_cn="2026年10月15日",
            pdf_filename=f"先验-{index}.pdf",
            report_text="机器人。",
        )
    _write_card(
        data_root,
        seed="code-confirm",
        batch="code-batch",
        pdf_filename="代码.pdf",
        report_text="相关业务 300024.SZ。",
    )

    result = read_stock_clues(data_root, "20261016")

    assert result["status"] == "READY"
    item = _clues_by_code(result)["300024.SZ"]
    assert item["document_count"] == 1
    assert item["weak_document_count"] == 0
    assert item["confirm_reasons"] == ["CODE"]
    assert item["matched_by"] == "CODE"
    assert item["link_probability"] == pytest.approx(0.0)
    assert _generic_by_name(result) == {}


def test_paragraph_coherence_upgrades_weak_name(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    _write_name_table(tmp_path, data_root)
    _write_card(
        data_root,
        seed="coherence",
        report_text="测试股份 600001.SH 与样本科技 600002.SH 均获关注，标的：机器人。",
    )

    result = read_stock_clues(data_root, "20261016")

    assert result["status"] == "READY"
    by_code = _clues_by_code(result)
    assert by_code["600001.SH"]["document_count"] == 1
    assert by_code["600002.SH"]["document_count"] == 1
    upgraded = by_code["600003.SZ"]
    assert upgraded["document_count"] == 1
    assert upgraded["weak_document_count"] == 0
    assert upgraded["confirm_reasons"] == ["COHERENCE"]
    assert upgraded["link_probability"] == pytest.approx(1.0)


def test_weak_mentions_do_not_inflate_confirmed_count(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    _write_name_table(tmp_path, data_root)
    _write_card(
        data_root,
        seed="weak-doc",
        batch="batch-weak",
        pdf_filename="产品词.pdf",
        report_text="充电桩、机器人、5G基站。",
    )
    _write_card(
        data_root,
        seed="context-doc",
        batch="batch-context",
        pdf_filename="上下文.pdf",
        report_text="标的：机器人。",
    )

    result = read_stock_clues(data_root, "20261016")

    assert result["items"] == []
    item = _weak_by_code(result)["600003.SZ"]
    assert item["weak_document_count"] == 2
    assert item["link_probability"] == pytest.approx(0.5)
    assert result["status"] == "READY_EMPTY"
    assert result["confirmed_stock_count"] == 0
    assert result["weak_only_stock_count"] == 1
    assert result["generic_filtered"] == []


def test_full_report_is_read_and_names_with_spaces_match(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    _write_name_table(tmp_path, data_root)
    # The name sits past the 4000-character card preview to prove the loader
    # reads the full bounded report instead of the preview.
    _write_card(
        data_root,
        seed="long",
        report_text=(
            ("填充文本" * 2200)
            + "\n末尾提到空格名称股份有限公司，空格名称股份有限公司，空格名称股份有限公司。"
        ),
    )

    result = read_stock_clues(data_root, "20261016")

    assert result["status"] == "READY"
    assert result["items"][0]["ts_code"] == "000002.SZ"
    assert result["items"][0]["name"] == "空格名称"
    assert result["items"][0]["matched_by"] == "NAME"
    assert result["items"][0]["document_count"] == 1
    assert result["items"][0]["confirm_reasons"] == ["CONTEXT"]


def test_oldest_date_is_ignored_when_newer_names_exist(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    _write_name_table(tmp_path, data_root)
    _write_card(data_root, seed="old-name", report_text="正文只提到测试股份。")

    result = read_stock_clues(data_root, "20261016")

    assert result["status"] == "READY_EMPTY"
    assert result["items"] == []
    assert _weak_by_code(result)["600001.SH"]["name"] == "测试股份"


def test_sorting_by_count_then_code_and_limit_truncation(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    _write_name_table(tmp_path, data_root)
    for index in range(3):
        _write_card(
            data_root,
            seed=f"many-{index}",
            batch=f"batch-{index}",
            pdf_filename=f"报告-{index + 1}.pdf",
            report_text="正文提到测试股份与样本科技。",
        )
    _write_card(
        data_root,
        seed="single-code",
        batch="batch-single-code",
        pdf_filename="代码.pdf",
        report_text="正文只写代码 600010.SH。",
    )
    _write_card(
        data_root,
        seed="single",
        batch="batch-single",
        pdf_filename="单篇.pdf",
        report_text="标的：机器人。",
    )

    full = read_stock_clues(data_root, "20261016")
    assert full["stock_count"] == 4
    assert [item["ts_code"] for item in full["items"]] == [
        "600001.SH",
        "600002.SH",
        "600010.SH",
    ]
    assert [entry["ts_code"] for entry in full["weak_items"]] == ["600003.SZ"]
    assert full["items"][0]["document_count"] == 3
    assert full["items"][0]["document_titles"] == ["报告-1", "报告-2", "报告-3"]

    limited = read_stock_clues(data_root, "20261016", limit=2)
    assert limited["clue_limit"] == 2
    assert limited["stock_count"] == 4
    assert [item["ts_code"] for item in limited["items"]] == ["600001.SH", "600002.SH"]

    clamped = read_stock_clues(data_root, "20261016", limit=10_000)
    assert clamped["clue_limit"] == MAX_CLUE_LIMIT


def test_document_titles_are_capped_and_deduplicated(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    _write_name_table(tmp_path, data_root)
    for index in range(MAX_TITLES_PER_STOCK + 1):
        _write_card(
            data_root,
            seed=f"title-{index}",
            batch=f"batch-{index}",
            pdf_filename=f"报告-{index + 1}.pdf",
            report_text="正文提到测试股份。",
        )

    result = read_stock_clues(data_root, "20261016")

    item = _clues_by_code(result)["600001.SH"]
    assert item["document_count"] == MAX_TITLES_PER_STOCK + 1
    assert len(item["document_titles"]) == MAX_TITLES_PER_STOCK
    assert item["document_titles"] == [f"报告-{index + 1}" for index in range(MAX_TITLES_PER_STOCK)]


def test_corpus_cache_reports_built_then_hit(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    _write_name_table(tmp_path, data_root)
    _write_card(data_root, seed="cached", report_text="正文只出现 600001.SH。")

    first = read_stock_clues(data_root, "20261016")
    second = read_stock_clues(data_root, "20261016")

    assert first["corpus_cache_status"] == "BUILT"
    assert second["corpus_cache_status"] == "HIT"
    assert first["corpus_report_count"] == second["corpus_report_count"] == 1


def test_corpus_cache_invalidates_when_non_newest_report_is_deleted(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    _write_name_table(
        tmp_path,
        data_root,
        rows=[
            {"trade_date": "20261016", "ts_code": "002913.SZ", "name": "奥士康", "tdx_industry_code": "T0201"},
        ],
    )
    a_id = _write_card(
        data_root,
        seed="cache-a",
        batch="batch-a",
        pdf_filename="甲.pdf",
        report_text="奥士康公司发布公告。",
    )
    b_id = _write_card(
        data_root,
        seed="cache-b",
        batch="batch-b",
        pdf_filename="乙.pdf",
        report_text="奥士康。奥士康。",
    )
    research_root = _research_root(data_root)
    a_path = research_root / "batches" / "batch-a" / "documents" / a_id / "report.md"
    b_path = research_root / "batches" / "batch-b" / "documents" / b_id / "report.md"
    newest_ns = 1_700_000_000_000_000_000
    older_ns = newest_ns - 10_000_000_000
    os.utime(a_path, ns=(newest_ns, newest_ns))
    os.utime(b_path, ns=(older_ns, older_ns))
    assert b_path.stat().st_mtime_ns < a_path.stat().st_mtime_ns

    first = read_stock_clues(data_root, "20261016")
    assert first["corpus_cache_status"] == "BUILT"
    assert first["corpus_report_count"] == 2
    assert len(first["corpus_fingerprint"]) == 64
    assert _weak_by_code(first)["002913.SZ"]["link_probability"] == pytest.approx(1 / 3)

    b_path.unlink()
    second = read_stock_clues(data_root, "20261016")

    assert second["corpus_report_count"] == 1
    assert second["corpus_cache_status"] == "BUILT"
    assert second["corpus_fingerprint"] != first["corpus_fingerprint"]
    assert _weak_by_code(second)["002913.SZ"]["link_probability"] == pytest.approx(1.0)


def test_empty_corpus_degrades_to_code_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = _data_root(tmp_path)
    _write_name_table(tmp_path, data_root)
    _write_card(data_root, seed="empty-corpus", report_text="正文提到测试股份 600001.SH。")
    monkeypatch.setattr(
        "infrastructure.research_stock_clues._discover_corpus_reports",
        lambda _root: ([], 0, ""),
    )

    result = read_stock_clues(data_root, "20261016")

    assert result["status"] == "READY"
    assert result["corpus_cache_status"] == "CANNOT_CONFIRM"
    assert result["corpus_report_count"] == 0
    assert "LINK_CORPUS_EMPTY" in result["cannot_confirm"]
    item = _clues_by_code(result)["600001.SH"]
    assert item["document_count"] == 1
    assert item["confirm_reasons"] == ["CODE"]
    assert item["link_probability"] is None
    assert result["generic_filtered"] == []


def test_corpus_stat_failure_degrades_to_code_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = _data_root(tmp_path)
    _write_name_table(tmp_path, data_root)
    _write_card(data_root, seed="stats-fail", report_text="正文提到测试股份 600001.SH。")

    def fail(_paths: list[Path], _name_map: dict) -> dict:
        raise RuntimeError("synthetic corpus failure")

    monkeypatch.setattr(
        "infrastructure.research_stock_clues._build_link_corpus",
        fail,
    )

    result = read_stock_clues(data_root, "20261016")

    assert result["status"] == "READY"
    assert result["corpus_cache_status"] == "CANNOT_CONFIRM"
    assert "LINK_CORPUS_STATS_FAILED:RuntimeError" in result["cannot_confirm"]
    item = _clues_by_code(result)["600001.SH"]
    assert item["document_count"] == 1
    assert item["confirm_reasons"] == ["CODE"]
    assert item["link_probability"] is None


def test_missing_name_map_degrades_to_code_only(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    _write_card(data_root, seed="code-only", report_text="正文只出现 600001.SH。")

    result = read_stock_clues(data_root, "20261016")

    assert result["status"] == "READY"
    assert result["name_map_status"] == "CANNOT_CONFIRM"
    assert result["name_map_trade_date"] == ""
    assert result["corpus_cache_status"] == "CANNOT_CONFIRM"
    assert "NAME_MAP_POINTER_UNAVAILABLE" in result["cannot_confirm"]
    item = result["items"][0]
    assert item["ts_code"] == "600001.SH"
    assert item["name"] is None
    assert item["matched_by"] == "CODE"
    assert item["link_probability"] is None
    assert result["production_allowed"] is False


def test_missing_parquet_degrades_to_code_only(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    _write_name_table(tmp_path, data_root, parquet=False)
    _write_card(data_root, seed="missing-parquet", report_text="正文只出现 600001.SH。")

    result = read_stock_clues(data_root, "20261016")

    assert result["status"] == "READY"
    assert result["name_map_status"] == "CANNOT_CONFIRM"
    assert "NAME_MAP_UNAVAILABLE" in result["cannot_confirm"]
    assert result["items"][0]["matched_by"] == "CODE"


def test_missing_research_root_is_not_materialized(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    data_root.mkdir(parents=True)

    result = read_stock_clues(data_root, "20261016")

    assert result["status"] == "NOT_MATERIALIZED"
    assert result["items"] == []
    assert "MACHINE_CARDS:PDF_RESEARCH_NOT_MATERIALIZED" in result["cannot_confirm"]
    assert result["production_allowed"] is False


def test_corrupt_card_is_structured_cannot_confirm(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    broken_dir = (
        _research_root(data_root) / "batches" / "batch-broken" / "documents" / _document_id("broken")
    )
    broken_dir.mkdir(parents=True)
    (broken_dir / "receipt.json").write_text("{not-json", encoding="utf-8")

    result = read_stock_clues(data_root, "20261016")

    assert result["status"] == "CANNOT_CONFIRM"
    assert result["items"] == []
    assert "MACHINE_CARDS:RECEIPT_UNREADABLE" in result["cannot_confirm"]
    assert result["research_only"] is True


def test_report_path_escape_is_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_root = _data_root(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("正文提到测试股份", encoding="utf-8")
    fake_cards = {
        "status": "READY",
        "card_count": 1,
        "cannot_confirm": [],
        "items": [
            {
                "document_id": "a" * 64,
                "research_date": "20261016",
                "title": "越界",
                "report": {"path": str(outside)},
            }
        ],
    }
    monkeypatch.setattr(
        "infrastructure.research_stock_clues.read_machine_cards",
        lambda _root, _date: fake_cards,
    )

    result = read_stock_clues(data_root, "20261016")

    assert result["status"] == "CANNOT_CONFIRM"
    assert result["items"] == []
    assert "REPORT_PATH_REJECTED" in result["cannot_confirm"]


def test_oversized_report_is_truncated_and_flagged(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    _write_name_table(tmp_path, data_root)
    padding = "填充文本" * (MAX_REPORT_BYTES // 12 + 10)
    assert len(padding.encode("utf-8")) > MAX_REPORT_BYTES
    _write_card(data_root, seed="huge", report_text=padding + "测试股份")

    result = read_stock_clues(data_root, "20261016")

    assert result["truncated_report_count"] == 1
    assert "REPORT_TRUNCATED" in result["cannot_confirm"]
    # The name is beyond the 512 KiB cap and must not be matched.
    assert result["status"] == "READY_EMPTY"


def test_invalid_date_is_structured_not_raised(tmp_path: Path) -> None:
    result = read_stock_clues(_data_root(tmp_path), "20261301")

    assert result["status"] == "CANNOT_CONFIRM"
    assert result["research_date"] == "20261301"
    assert "MACHINE_CARDS:TRADE_DATE_INVALID" in result["cannot_confirm"]


def _make_client(data_root: Path) -> TestClient:
    app = FastAPI()
    app.include_router(create_research_lane_router(data_root))
    return TestClient(app)


def test_stock_clues_endpoint_is_read_only_and_no_store(tmp_path: Path) -> None:
    data_root = _data_root(tmp_path)
    _write_name_table(tmp_path, data_root)
    _write_card(
        data_root,
        seed="api-card",
        report_text="正文提到测试股份与 600001.SH、600002.SH。",
    )

    with _make_client(data_root) as client:
        response = client.get("/api/v3/research/stock-clues", params={"research_date": "20261016"})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["schema_version"] == SCHEMA_VERSION
    assert body["status"] == "READY"
    assert body["stock_count"] == 2
    assert body["corpus_report_count"] == 1
    assert body["corpus_cache_status"] == "BUILT"
    assert body["generic_filtered"] == []
    assert body["weak_items"] == []
    assert body["research_only"] is True
    assert body["production_allowed"] is False
    assert body["buy_gate_updated"] is False
    assert body["orders_sent"] is False


@pytest.mark.parametrize("value", ["2026-10-16", "20261301", "abcd1234", ""])
def test_stock_clues_endpoint_rejects_invalid_dates(tmp_path: Path, value: str) -> None:
    with _make_client(_data_root(tmp_path)) as client:
        response = client.get("/api/v3/research/stock-clues", params={"research_date": value})

    assert response.status_code == 422


@pytest.mark.parametrize("value", ["0", "201", "-1"])
def test_stock_clues_endpoint_rejects_out_of_range_limit(tmp_path: Path, value: str) -> None:
    with _make_client(_data_root(tmp_path)) as client:
        response = client.get(
            "/api/v3/research/stock-clues",
            params={"research_date": "20261016", "limit": value},
        )

    assert response.status_code == 422


def test_stock_clues_endpoint_requires_research_date(tmp_path: Path) -> None:
    with _make_client(_data_root(tmp_path)) as client:
        response = client.get("/api/v3/research/stock-clues")

    assert response.status_code == 422


@pytest.mark.skipif(
    not os.environ.get("V4_STOCK_CLUES_REAL_PARQUET"),
    reason="real name-table parquet is not available in this environment",
)
def test_real_20261016_top_clues_when_parquet_is_explicitly_configured() -> None:
    """Optional integration check; CI never depends on local production data."""
    data_root = Path(os.environ["V4_STOCK_CLUES_REAL_PARQUET"]).expanduser()
    result = read_stock_clues(data_root, "20261016")
    assert result["status"] == "READY"
    assert result["stock_count"] > 100
    assert 4 <= result["items"][0]["document_count"] <= 6
