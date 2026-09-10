import pytest

from contracts.research_day_product import (
    validate_selection_market_scope,
    validate_selection_research_product,
)
from domains.research_day_product import build_selection_research_product


def _card(entity: str, *, index: int) -> dict:
    return {
        "event_id": f"event-{index}",
        "entities": [entity],
        "source": {
            "status": "VERIFIED_SOURCE_IDENTITY",
            "official_url": f"https://example.test/{index}",
            "published_at": "2026-08-28T10:00:00+08:00",
        },
        "eligibility": "ELIGIBLE",
        "bucket": "CORE",
        "catalyst": "catalyst",
        "counterevidence": "counterevidence",
        "invalidation": "invalidation",
        "evidence_level": "L2",
        "financial_bridge": "bridge",
        "consensus": "consensus",
        "overnight_pending": "none",
    }


def _product(entities: list[str]) -> dict:
    cards = []
    for index, entity in enumerate(entities):
        cards.append(
            {
                "card": _card(entity, index=index),
                "source_ref": {
                    "type": "EARLY_DRAFT_FROZEN_ENVELOPE",
                    "path": "/tmp/selection-source.json",
                    "raw_sha256": "a" * 64,
                    "frozen_payload_sha256": "b" * 64,
                    "json_pointer": f"/frozen_payload/event_cards/{index}",
                    "source_date": "20260828",
                    "source_time": "2026-08-28T21:00:00+08:00",
                },
            }
        )
    return build_selection_research_product(
        "20260828",
        "20260831",
        source_cards=cards,
        generated_at="2026-08-28T22:00:00+08:00",
        cutoff_at="2026-08-28T22:00:00+08:00",
        run_id="selection-market-scope-test",
    )


def test_hk_connect_focus_rejects_a_share_product_before_ready():
    product = _product(["000001.A"])

    with pytest.raises(ValueError, match="market scope"):
        validate_selection_research_product(product, market_focus="HK_CONNECT")


def test_hk_connect_focus_rejects_undeclared_mixed_product():
    product = _product(["000001.A", "00001.HK"])

    with pytest.raises(ValueError, match="market scope"):
        validate_selection_research_product(product, market_focus="HK_CONNECT")


def test_ready_a_share_or_undeclared_mixed_product_cannot_pass_generic_contract():
    for entities in (["000001.A"], ["000001.A", "00001.HK"]):
        product = _product(list(entities))
        product["status"] = "READY"

        with pytest.raises(ValueError, match="market scope"):
            validate_selection_research_product(product)


def test_declared_mixed_scope_is_not_rejected_by_generic_scope_contract():
    product = _product(["000001.A", "00001.HK"])
    product["status"] = "READY"
    product["market_scope"] = "MIXED"

    assert validate_selection_market_scope(product) == "MIXED"


def test_hk_product_remains_valid_for_hk_connect_focus():
    product = _product(["00001.HK"])

    assert validate_selection_research_product(product, market_focus="HK_CONNECT") == "20260831"
