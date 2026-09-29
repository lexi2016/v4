from __future__ import annotations

from pathlib import Path

import pytest

from v4.manager_research.pdf_parser import extract_pdf_facts
from v4.manager_research.recommendation import extract_financial_evidence
from v4.manager_research.service import _amount_text, _build_research_sections, _has_researchable_fact_set


EVIDENCE_ROOT = Path(
    "/Users/lexi/Desktop/学习/agents调试/助手/v35_repair_20260907/batch04-manager-facts/sources"
)


def test_five_recovered_financial_sets_stay_researchable() -> None:
    for code in ("06166", "02225", "03268", "01989", "07666"):
        facts, _pages = extract_pdf_facts((EVIDENCE_ROOT / f"{code}.pdf").read_bytes())
        assert facts
        assert _has_researchable_fact_set(facts)


def test_researchability_gate_still_rejects_component_only_revenue() -> None:
    component = {
        "fact_kind": "financial",
        "fields": {"label": "Revenue from collaboration agreements"},
    }
    aggregate = {
        "fact_kind": "financial",
        "fields": {"label": "Revenue from contracts with customers"},
    }
    assert _has_researchable_fact_set([component]) is False
    assert _has_researchable_fact_set([aggregate]) is True


def test_service_maps_singapore_dollar_and_yuan_units() -> None:
    singapore = _amount_text({"fields": {"currency": "S$", "unit": "thousands"}}, "34,021")
    yuan = _amount_text({"fields": {"currency": "RMB", "unit": "yuan"}}, "2,024,526,412.36")
    assert "新加坡元" in singapore
    assert "千元" in singapore
    assert "人民币元" in yuan


def _section_fact(label: str, current: str, previous: str, page: int) -> dict[str, object]:
    return {
        "fact_kind": "financial",
        "statement_cn": f"财务表：{label}；期间=截至六个月 2026年6月30日。",
        "locator": f"PDF page {page}",
        "page": page,
        "source_excerpt": f"{label} {current} {previous}",
        "fields": {
            "label": label,
            "period_label_cn": "截至六个月 2026年6月30日",
            "columns": ["2026", "2025"],
            "currency": "RMB",
            "unit": "thousands",
            "values": [
                {"column": "2026", "raw": current},
                {"column": "2025", "raw": previous},
            ],
        },
    }


@pytest.mark.parametrize(
    ("label", "current", "expected"),
    [
        ("Profit (loss) for the period", "(118,269)", "法定口径仍为亏损"),
        ("INCOME FOR THE PERIOD", "118,269", "法定口径已列示利润"),
    ],
)
def test_statutory_result_label_variants_feed_research_sections(
    label: str,
    current: str,
    expected: str,
) -> None:
    sections = _build_research_sections(
        "测试公司",
        "HK.00001",
        [
            _section_fact("Revenue", "500,000", "450,000", 1),
            _section_fact("Gross profit", "200,000", "180,000", 2),
            _section_fact(label, current, "100,000", 3),
        ],
        {"name": "测试公司"},
    )

    assert expected in sections["thesis_cn"]
    assert "公告没有法定利润/亏损行" not in "；".join(sections["counterevidence_cn"])


def test_hk03696_statutory_thesis_and_recommendation_use_profit_row_not_other_comprehensive() -> None:
    """The stock-facing thesis and evidence basis must point to the same row."""

    source_sha = "7" * 64
    common = {
        "fact_kind": "financial",
        "statement_cn": "财务表：官方综合收益表；期间=截至六个月 2026年6月30日。",
        "locator": "PDF page 57",
        "page": 57,
        "source_excerpt": "Official statement page 57.",
        "fields": {
            "period_label_cn": "截至六个月 2026年6月30日",
            "currency": "USD",
            "unit": "thousands",
            "columns": ["2026", "2025"],
        },
        "source_sha256": source_sha,
    }

    def row(label: str, current: str, previous: str, label_cn: str) -> dict[str, object]:
        item = dict(common)
        item["fields"] = {
            **common["fields"],
            "label": label,
            "label_cn": label_cn,
            "values": [{"column": "2026", "raw": current}, {"column": "2025", "raw": previous}],
        }
        return item

    facts = [
        row("Revenue", "106,303", "27,456", "收入"),
        row("Gross profit", "95,965", "23,019", "毛利"),
        row(
            "Other comprehensive income for the period, net of income tax",
            "1,816",
            "292",
            "其他全面收益",
        ),
        row("Profit (loss) for the period", "35,537", "(19,215)", "利润（亏损）"),
    ]

    sections = _build_research_sections(
        "INSILICO",
        "HK.03696",
        facts,
        {"name": "INSILICO"},
    )
    assert "法定口径利润35,537美元千元" in sections["thesis_cn"]
    assert "1,816美元千元" not in sections["thesis_cn"]

    evidence = extract_financial_evidence(
        facts,
        source={"sha256": source_sha},
    )
    profit_loss = evidence["dimensions"]["profit_loss"]
    assert profit_loss["current"] == "35,537"
    assert profit_loss["fact_refs"] == [{"source_sha256": source_sha, "locator": "PDF page 57", "page": 57}]
