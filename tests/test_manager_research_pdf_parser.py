from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from v4.manager_research.pdf_parser import extract_pdf_facts


EVIDENCE_ROOT = Path(
    "/Users/lexi/Desktop/学习/agents调试/助手/v35_repair_20260907/batch04-manager-facts/sources"
)

EXPECTED_SHA256 = {
    "06166": "a4e7a4b25f4b8234c5d5b1f97c02373d548af5cb4e18ff911d6cef087cf6dd46",
    "02225": "c4cbbeaf2796361d5d36b292ba5255e75d14f86336cbce9784165ad88e82c5ce",
    "03268": "98c3cbf1be3d7703fa15b112cf024dae5a3338bfc39d024abc082b2207b398ac",
    "01989": "470892b5e19a7da789c7ba7419f3f8b73a12f3f258216da93859a600a025e196",
    "07666": "3e406c488b6899537caf7b679cba42be3c8a001181d396c4005daf209a7ffaa8",
}


def _facts(code: str) -> list[dict]:
    body = (EVIDENCE_ROOT / f"{code}.pdf").read_bytes()
    assert sha256(body).hexdigest() == EXPECTED_SHA256[code]
    facts, _pages = extract_pdf_facts(body)
    return facts


def _fact(facts: list[dict], *, page: int, label: str) -> dict:
    matches = [
        fact
        for fact in facts
        if fact.get("page") == page and fact.get("fields", {}).get("label") == label
    ]
    assert matches, f"missing {label!r} on PDF page {page}"
    return matches[0]


def test_exact_five_hkex_fixtures_recover_documented_financial_rows() -> None:
    expected = {
        "06166": (14, "Operating revenue", "RMB", "yuan", ["2,705,007,720.63", "2,035,126,267.94", "32.92"]),
        "02225": (1, "Revenue", "S$", "thousands", ["34,021", "14,529"]),
        "03268": (8, "Operating revenue", "RMB", "yuan", ["2,024,526,412.36", "1,886,475,312.32", "7.32%"]),
        "01989": (4, "Revenue", "RMB", "yuan", ["4,388,260,234.74", "2,424,753,430.89", "1,963,506,803.85"]),
        "07666": (1, "Revenue from contracts with customers", "RMB", "thousands", ["154,292", "1,143", "13,399%"]),
    }
    for code, (page, label, currency, unit, raw_values) in expected.items():
        fact = _fact(_facts(code), page=page, label=label)
        fields = fact["fields"]
        assert fields["currency"] == currency
        assert fields["unit"] == unit
        assert [item["raw"] for item in fields["values"]] == raw_values
        assert fact["locator"] == f"PDF page {page}"
        assert all(raw in fact["source_excerpt"] for raw in raw_values)


def test_07666_aggregate_row_does_not_promote_note_number_as_revenue() -> None:
    fact = _fact(_facts("07666"), page=1, label="Revenue from contracts with customers")
    values = [item["raw"] for item in fact["fields"]["values"]]
    assert values[:2] == ["154,292", "1,143"]
    assert "3" not in values

