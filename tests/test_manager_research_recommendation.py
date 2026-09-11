from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import pytest

from v4.manager_research.contracts import FOUR_FLAGS, cutoff_at, normalise_observation_input, validate_safety
from v4.manager_research.event_source import event_is_focus_eligible
from v4.manager_research.recommendation import (
    build_research_recommendation,
    derive_investment_advice,
    extract_financial_evidence,
    recommendation_summary,
)
from v4.manager_research.service import ManagerResearchJobService
from v4.manager_research.store import ManagerResearchStore
import v4.manager_research.service as service_module


SOURCE_SHA = "a" * 64
INPUT_SHA = "b" * 64


def source(*, published_at: str = "2026-09-08T09:30:00+08:00") -> dict[str, str]:
    return {
        "url": "https://www.hkex.com.hk/research/fixture.pdf",
        "sha256": SOURCE_SHA,
        "published_at": published_at,
        "retrieved_at": "2026-09-08T09:35:00+08:00",
    }


def fact(label: str = "Revenue") -> dict[str, Any]:
    return {
        "statement_cn": "财务表：结构化官方事实；期间和数值见原文。",
        "fact_kind": "financial",
        "locator": "PDF page 1",
        "page": 1,
        "source_excerpt": "Revenue 120; prior period 100.",
        "fields": {
            "label": label,
            "label_cn": "收入" if label == "Revenue" else label,
            "currency": "USD",
            "unit": "thousand",
            "values": [
                {"column": "2026", "raw": "120"},
                {"column": "2025", "raw": "100"},
            ],
        },
    }


def period_fact(
    label: str,
    current: str,
    previous: str,
    period: str,
    *,
    label_cn: str | None = None,
    currency: str = "HKD",
    unit: str = "million",
    locator: str = "PDF page 2",
) -> dict[str, Any]:
    """Build one bounded official fact for recommendation edge-case tests."""

    return {
        "statement_cn": "财务表：官方结构化事实；期间和数值见原文。",
        "fact_kind": "financial",
        "locator": locator,
        "page": 2,
        "source_excerpt": f"{label}: {current}; prior period {previous}.",
        "fields": {
            "label": label,
            "label_cn": label_cn or label,
            "period_label": period,
            "currency": currency,
            "unit": unit,
            "values": [
                {"column": "2026", "raw": current},
                {"column": "2025", "raw": previous},
            ],
        },
    }


def observation(target_date: str = "20260908", **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "code": "HK.00001",
        "name": "测试公司",
        "stage_rank": 1,
        "stage_id": "STAGE_0935_0940",
        "source_last_bar_time": f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:]} 09:40:00",
        "last_price": 10.0,
        "support_price": 9.5,
        "pressure_price": 10.5,
        "volume": 100000,
        "volume_ratio": 1.2,
        "formal_eligible": False,
    }
    row.update(overrides)
    return row


def result(*, published_at: str = "2026-09-08T09:30:00+08:00", facts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "status": "READY",
        "issuer": "测试公司",
        "source": source(published_at=published_at),
        "facts": facts if facts is not None else [
            fact("Revenue"),
            fact("Profit for the period"),
            fact("Net cash flows from operating activities"),
        ],
    }


def build_recommendation(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "observation": observation(),
        "result": result(),
        "target_trade_date": "20260908",
        "cutoff_at": cutoff_at("20260908"),
        "generated_at": "2026-09-08T10:00:00+08:00",
        "input_source_sha256": INPUT_SHA,
        "stage_status": "READY",
        "cannot_confirm": [],
    }
    values.update(overrides)
    return build_research_recommendation(**values)


def test_complete_current_day_input_only_generates_research_conditional_buy() -> None:
    recommendation = build_recommendation()

    assert recommendation["status"] == "GENERATED"
    assert recommendation["action"] == "CONDITIONAL_BUY"
    assert recommendation["execution_scope"] == "RESEARCH_ONLY"
    assert recommendation["timing_status"] == "CURRENT_AFTER_CUTOFF"
    assert "probability" not in recommendation


@pytest.mark.parametrize(
    ("target_trade_date", "generated_at", "stage_status", "cannot_confirm", "expected_reason"),
    [
        ("20260907", "2026-09-08T10:00:00+08:00", "READY", [], "HISTORICAL_BACKFILL"),
        ("20260908", "2026-09-08T10:00:00+08:00", "PARTIAL_WITH_ROWS", ["STAGE_GAP"], "STAGE_NOT_READY"),
    ],
)
def test_historical_or_stage_gap_stays_data_insufficient(
    target_trade_date: str,
    generated_at: str,
    stage_status: str,
    cannot_confirm: list[str],
    expected_reason: str,
) -> None:
    recommendation = build_research_recommendation(
        observation=observation(target_trade_date),
        result=result(),
        target_trade_date=target_trade_date,
        cutoff_at=cutoff_at(target_trade_date),
        generated_at=generated_at,
        input_source_sha256=INPUT_SHA,
        stage_status=stage_status,
        cannot_confirm=cannot_confirm,
    )

    assert recommendation["status"] == "GENERATED"
    assert recommendation["action"] == "CONDITIONAL_BUY"
    assert expected_reason in recommendation["blocking_reasons"]
    if cannot_confirm:
        assert "UPSTREAM_CANNOT_CONFIRM" in recommendation["blocking_reasons"]


def test_explicit_no_buy_and_no_trade_are_preserved_before_data_gaps() -> None:
    recommendation = build_recommendation(
        observation=observation(action_level="NO_BUY", trade_status="NO_TRADE"),
        result={"status": "CANNOT_CONFIRM", "source": None, "facts": []},
        stage_status="PARTIAL_WITH_ROWS",
        cannot_confirm=["UNSAFE_STAGE"],
    )

    assert recommendation["status"] == "NOT_GENERATED"
    assert recommendation["action"] == "DATA_INSUFFICIENT"
    assert "ACTION_LEVEL_NO_BUY" in recommendation["execution_gate"]["blocked_reasons"]
    assert "TRADE_STATUS_NO_TRADE" in recommendation["execution_gate"]["blocked_reasons"]
    assert recommendation["upstream_action_level"] == "NO_BUY"
    assert recommendation["upstream_trade_status"] == "NO_TRADE"


def test_missing_market_field_or_source_cutoff_blocks_generation() -> None:
    missing_volume = build_recommendation(observation=observation(volume=None))
    assert missing_volume["action"] == "CONDITIONAL_BUY"
    assert "volume" in missing_volume["missing_fields"]

    late_source = build_recommendation(
        result=result(published_at="2026-09-08T09:41:00+08:00"),
    )
    assert late_source["action"] == "CONDITIONAL_BUY"
    assert "SOURCE_PUBLISHED_AFTER_CUTOFF" in late_source["blocking_reasons"]


def test_summary_is_deterministic_and_execution_buy_is_zero() -> None:
    summary = recommendation_summary([
        {"action": "NO_TRADE"},
        {"action": "DATA_INSUFFICIENT"},
        {"action": "CONDITIONAL_BUY"},
        {"action": "NO_BUY"},
    ])

    assert summary["counts"] == {
        "CONDITIONAL_BUY": 1,
        "NO_BUY": 1,
        "NO_TRADE": 1,
        "DATA_INSUFFICIENT": 1,
    }
    assert [item["action"] for item in summary["actions"]] == [
        "CONDITIONAL_BUY",
        "DATA_INSUFFICIENT",
    ]
    assert summary["execution_buy_count"] == 0


def test_financial_evidence_uses_one_common_period_for_counts() -> None:
    annual = "Year ended December 31, 2026"
    interim = "Six months ended June 30, 2026"
    evidence = extract_financial_evidence(
        [
            period_fact("Revenue", "120", "100", interim, label_cn="收入"),
            period_fact("Gross profit", "60", "50", interim, label_cn="毛利"),
            period_fact("Profit for the period", "-9", "-5", annual, label_cn="期内利润"),
            period_fact(
                "Net cash flows from operating activities",
                "12",
                "8",
                annual,
                label_cn="经营活动现金流量净额",
            ),
        ],
        source=source(),
    )

    assert evidence["period_key"] == ["2026-12-31", "ANNUAL"]
    assert evidence["comparable_dimensions"] == ["profit_loss", "operating_cashflow"]
    assert evidence["positive_dimensions"] == ["operating_cashflow"]
    assert evidence["negative_dimensions"] == ["profit_loss"]
    assert evidence["positive_count"] == 1
    assert evidence["negative_count"] == 1
    assert evidence["period_mismatch_dimensions"] == ["revenue", "gross_profit"]
    assert evidence["dimensions"]["revenue"]["state"] == "MISSING"
    assert evidence["dimensions"]["revenue"]["period_mismatch"] is True

    advice = derive_investment_advice(
        evidence,
        market_snapshot={
            "last_price": 10,
            "support_price": 9,
            "pressure_price": 11,
            "volume": 100,
            "volume_ratio": 1.2,
        },
    )
    assert advice["action"] == "WATCH"
    assert advice["coverage_scope"] == "仅依据已解析官方财报结构化事实；近期重大事件（含合作/公告）覆盖未确认。"
    assert "报告期" in advice["reason"] or any("REVENUE" in item for item in advice["conditions"])
    assert any("REVENUE" in item for item in advice["conditions"])


def test_operating_loss_impairment_and_bank_cash_are_bound_to_advice() -> None:
    period = "Year ended December 31, 2026"
    facts = [
        period_fact("Revenue", "120", "100", period, label_cn="收入"),
        period_fact("Gross profit", "60", "50", period, label_cn="毛利"),
        period_fact("Profit for the period", "20", "10", period, label_cn="期内利润"),
        period_fact(
            "Net cash flows from operating activities",
            "15",
            "10",
            period,
            label_cn="经营活动现金流量净额",
        ),
        period_fact("Operating loss", "-9", "-3", period, label_cn="营业亏损", locator="PDF page 5"),
        period_fact(
            "Impairment loss recognized on trade receivables",
            "4",
            "2",
            period,
            label_cn="贸易应收款减值损失",
            locator="PDF page 6",
        ),
        period_fact("Bank and cash balances", "80", "60", period, label_cn="银行及现金结余", locator="PDF page 7"),
    ]
    evidence = extract_financial_evidence(facts, source=source())

    assert evidence["dimensions"]["operating_loss"]["state"] == "NEGATIVE"
    assert evidence["dimensions"]["receivable_impairment"]["state"] == "NEGATIVE"
    assert evidence["dimensions"]["cash"]["state"] == "POSITIVE"
    assert {"operating_loss", "receivable_impairment"}.issubset(evidence["adverse_dimensions"])
    for dimension in ("operating_loss", "receivable_impairment"):
        gap = next(item for item in evidence["evidence_gaps"] if item["dimension"] == dimension)
        assert gap["fact_refs"]
        assert gap["fact_refs"][0]["source_sha256"] == SOURCE_SHA

    advice = derive_investment_advice(
        evidence,
        market_snapshot={
            "last_price": 10,
            "support_price": 9,
            "pressure_price": 11,
            "volume": 100,
            "volume_ratio": 1.2,
        },
    )
    assert advice["action"] == "WATCH"
    assert any("OPERATING_LOSS" in item for item in advice["conditions"])
    assert any("RECEIVABLE_IMPAIRMENT" in item for item in advice["conditions"])
    basis_by_dimension = {
        item["dimension"]: item for item in advice["basis"] if isinstance(item, dict) and item.get("dimension")
    }
    assert basis_by_dimension["operating_loss"]["fact_refs"][0]["locator"] == "PDF page 5"
    assert basis_by_dimension["receivable_impairment"]["fact_refs"][0]["locator"] == "PDF page 6"


def test_loss_from_operations_variant_keeps_real_pdf_values_and_refs() -> None:
    """The HKEX ``Loss from operations`` row is an operating-loss signal."""

    period = "Year ended December 31, 2026"
    evidence = extract_financial_evidence(
        [
            period_fact("Revenue", "300000", "280000", period, label_cn="收入"),
            period_fact(
                "Loss from operations",
                "-113687",
                "-77181",
                period,
                label_cn="经营亏损",
                locator="PDF page 20",
            ),
        ],
        source={**source(), "sha256": "d6a0cc8c3286a6d1cf0b3d183a911e71bcdd0213be8ae9ee44b62ea480d4912b"},
    )

    operating = evidence["dimensions"]["operating_loss"]
    assert operating["state"] == "NEGATIVE"
    assert operating["current"] in {-113687, "-113687"}
    assert operating["previous"] in {-77181, "-77181"}
    assert operating["fact_refs"][0]["locator"] == "PDF page 20"
    assert operating["fact_refs"][0]["source_sha256"] == "d6a0cc8c3286a6d1cf0b3d183a911e71bcdd0213be8ae9ee44b62ea480d4912b"


def test_cash_aliases_with_different_values_are_a_conflict_and_watch() -> None:
    period = "Year ended December 31, 2026"
    evidence = extract_financial_evidence(
        [
            period_fact("Revenue", "120", "100", period, label_cn="收入"),
            period_fact("Profit for the period", "20", "10", period, label_cn="期内利润"),
            period_fact(
                "Bank and cash balances",
                "80",
                "60",
                period,
                label_cn="银行及现金结余",
                locator="PDF page 8",
            ),
            period_fact(
                "Cash and cash equivalents",
                "70",
                "60",
                period,
                label_cn="现金及现金等价物",
                locator="PDF page 9",
            ),
        ],
        source=source(),
    )

    cash = evidence["dimensions"]["cash"]
    assert cash["state"] == "CONFLICT"
    assert "cash" in evidence["conflict_dimensions"]
    assert len(cash["fact_refs"]) == 2
    assert {ref["locator"] for ref in cash["fact_refs"]} == {"PDF page 8", "PDF page 9"}

    advice = derive_investment_advice(
        evidence,
        market_snapshot={
            "last_price": 10,
            "support_price": 9,
            "pressure_price": 11,
            "volume": 100,
            "volume_ratio": 1.2,
        },
    )
    assert advice["action"] == "WATCH"
    assert any("CASH" in item for item in advice["conditions"])
    assert any("cash" in item.get("dimension", "") for item in evidence["evidence_gaps"])


def test_service_product_embeds_recommendation_and_preserves_legacy_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_module, "_now", lambda: "2026-09-08T10:00:00+08:00")
    input_data = {
        "target_trade_date": "20260908",
        "stage_id": "STAGE_0935_0940",
        "market": "HK_CONNECT",
        "cutoff_at": cutoff_at("20260908"),
        "input_identity": "c" * 64,
        "input_source_sha256": INPUT_SHA,
        "input_row_count": 1,
        "source_status": "READY",
        "stage_status": "READY",
        "cannot_confirm": [],
    }
    product = ManagerResearchJobService._build_product(
        input_data,
        [observation()],
        {"HK.00001": result()},
    )

    row = product["rows"][0]
    recommendation = row["research_recommendation"]
    assert product["status"] == "READY"
    assert row["decision"] == "暂不买入，等待验证"
    assert row["source_status"] == "READY"
    assert row["RESEARCH_ONLY"] is True
    assert recommendation["action"] == "CONDITIONAL_BUY"
    assert recommendation["status"] == "GENERATED"
    assert product["recommendation_summary"]["counts"]["CONDITIONAL_BUY"] == 1
    assert product["historical_system_available"] is False
    assert product["rows"][0]["origin"] == "CURRENT_DAY_RESEARCH"


def test_historical_service_product_keeps_research_facts_visible_but_downgrades_recommendation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_module, "_now", lambda: "2026-09-08T10:00:00+08:00")
    input_data = {
        "target_trade_date": "20260907",
        "stage_id": "STAGE_0935_0940",
        "market": "HK_CONNECT",
        "cutoff_at": cutoff_at("20260907"),
        "input_identity": "d" * 64,
        "input_source_sha256": INPUT_SHA,
        "input_row_count": 1,
        "source_status": "READY",
        "stage_status": "READY",
        "cannot_confirm": [],
    }
    product = ManagerResearchJobService._build_product(
        input_data,
        [observation("20260907")],
        {"HK.00001": result(published_at="2026-09-06T09:30:00+08:00")},
    )

    row = product["rows"][0]
    assert row["facts"]
    assert row["research_recommendation"]["action"] == "CONDITIONAL_BUY"
    assert row["research_recommendation"]["status"] == "GENERATED"
    assert "HISTORICAL_BACKFILL" in row["research_recommendation"]["blocking_reasons"]
    assert product["historical_system_available"] is False


def test_contract_identity_retains_stage_gaps_and_safety_flags() -> None:
    payload = {
        "target_trade_date": "20260908",
        "stage_id": "STAGE_0935_0940",
        "status": "PARTIAL_WITH_ROWS",
        "cannot_confirm": ["HK:SOURCE_TEMPORAL_CUTOFF_UNSAFE"],
        "rows": [
            {
                "code": "HK.00001",
                "name": "测试公司",
                "rank": 1,
                "source_last_bar_time": "2026-09-08 09:40:00",
            }
        ],
    }

    normalized = normalise_observation_input(payload)
    assert normalized["cannot_confirm"] == ["HK:SOURCE_TEMPORAL_CUTOFF_UNSAFE"]
    assert normalized["identity_payload"]["cannot_confirm"] == ["HK:SOURCE_TEMPORAL_CUTOFF_UNSAFE"]
    assert validate_safety(None) == FOUR_FLAGS


def test_old_cached_product_is_reassembled_without_stopping_at_stale(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setattr(service_module, "_now", lambda: "2026-09-08T10:00:00+08:00")
    raw_input = {
        "target_trade_date": "20260908",
        "stage_id": "STAGE_0935_0940",
        "status": "READY",
        "rows": [observation()],
    }
    store = ManagerResearchStore(tmp_path)
    service = ManagerResearchJobService(store, lambda _date: raw_input, None)
    try:
        input_data = service._read_input("20260908")
        old_product = ManagerResearchJobService._build_product(
            input_data,
            [observation()],
            {"HK.00001": result()},
        )
        # Model a product written before the recommendation contract existed,
        # while retaining enough persisted observation fields to migrate it
        # without a new source call.
        old_product["recommendation_summary"] = None
        old_product["rows"][0].pop("research_recommendation", None)
        old_product["rows"][0].pop("observation_timing_status", None)
        old_product["rows"][0]["observation"].update({
            "last_price": 10.0,
            "support_price": 9.5,
            "pressure_price": 10.5,
            "volume": 100000,
            "volume_ratio": 1.2,
        })
        store.write_product(old_product)

        envelope = service.get("20260908")

        assert envelope["status"] == "READY"
        assert envelope["product"] is not None
        migrated = envelope["product"]
        assert migrated["recommendation_summary"]["counts"]["CONDITIONAL_BUY"] == 1
        assert migrated["rows"][0]["research_recommendation"]["action"] == "CONDITIONAL_BUY"
        # GET projects derived recommendations without mutating the frozen cache.
        assert "research_recommendation" not in store.read_product("20260908", input_data["input_identity"])["rows"][0]
    finally:
        service.close()


def test_pre_stage_evidence_cache_is_reused_under_current_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    """A validated old identity reuses facts without starting a provider job."""

    monkeypatch.setattr(service_module, "_now", lambda: "2026-09-08T10:00:00+00:00")
    raw_input = {
        "target_trade_date": "20260908",
        "stage_id": "STAGE_0935_0940",
        "status": "PARTIAL_WITH_ROWS",
        "cannot_confirm": ["HK:UNSAFE_STAGE"],
        "rows": [observation()],
    }
    store = ManagerResearchStore(tmp_path)
    service = ManagerResearchJobService(store, lambda _date: raw_input, None)
    try:
        input_data = service._read_input("20260908")
        current_product = ManagerResearchJobService._build_product(
            input_data,
            [observation()],
            {"HK.00001": result()},
        )
        legacy_identity = service._legacy_input_identity(input_data)
        assert legacy_identity is not None
        legacy_product = dict(current_product)
        legacy_product["input_identity"] = legacy_identity
        legacy_product["product_id"] = f"manager-research-20260908-{legacy_identity[:24]}"
        legacy_product.pop("stage_status", None)
        legacy_product.pop("cannot_confirm", None)
        legacy_product.pop("recommendation_summary", None)
        legacy_product["rows"] = [dict(legacy_product["rows"][0])]
        legacy_product["rows"][0].pop("research_recommendation", None)
        legacy_product["rows"][0].pop("observation_timing_status", None)
        store.write_product(legacy_product)

        envelope = service.get("20260908")

        assert envelope["status"] == "READY"
        migrated = envelope["product"]
        assert migrated is not None
        assert migrated["input_identity"] == input_data["input_identity"]
        assert migrated["stage_status"] == "PARTIAL_WITH_ROWS"
        assert migrated["cannot_confirm"] == ["HK:UNSAFE_STAGE"]
        assert migrated["rows"][0]["research_recommendation"]
        # The legacy alias is an in-memory projection, not an implicit write.
        assert store.read_product("20260908", input_data["input_identity"]) is None
        assert store.read_product("20260908", legacy_identity) is not None
    finally:
        service.close()


@pytest.mark.parametrize("mismatch_location", ["row", "observation"])
def test_legacy_cache_rejects_cross_date_row_material_without_alias_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    mismatch_location: str,
) -> None:
    """A top-level date cannot mask stale nested row evidence."""

    monkeypatch.setattr(service_module, "_now", lambda: "2026-09-08T10:00:00+00:00")
    raw_input = {
        "target_trade_date": "20260908",
        "stage_id": "STAGE_0935_0940",
        "status": "PARTIAL_WITH_ROWS",
        "cannot_confirm": ["HK:UNSAFE_STAGE"],
        "rows": [observation()],
    }

    class ProviderProbe:
        calls = 0

        def collect(self, **_: Any) -> dict[str, Any]:
            self.calls += 1
            raise AssertionError("cross-date legacy cache must not call the provider")

    provider = ProviderProbe()
    store = ManagerResearchStore(tmp_path)
    service = ManagerResearchJobService(store, lambda _date: raw_input, provider)
    try:
        input_data = service._read_input("20260908")
        current_product = ManagerResearchJobService._build_product(
            input_data,
            [observation()],
            {"HK.00001": result()},
        )
        legacy_identity = service._legacy_input_identity(input_data)
        assert legacy_identity is not None
        legacy_product = deepcopy(current_product)
        legacy_product["input_identity"] = legacy_identity
        legacy_product["product_id"] = f"manager-research-20260908-{legacy_identity[:24]}"
        if mismatch_location == "row":
            legacy_product["rows"][0]["target_trade_date"] = "20260907"
        else:
            legacy_product["rows"][0]["observation"]["target_trade_date"] = "20260907"
        store.write_product(legacy_product)

        envelope = service.get("20260908")

        assert envelope["product"] is None
        assert envelope["status"] == "NOT_MATERIALIZED"
        assert provider.calls == 0
        assert store.read_product("20260908", input_data["input_identity"]) is None
        assert store.read_product("20260908", legacy_identity) is not None
    finally:
        service.close()


@pytest.mark.skipif(
    not Path(
        "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/manager_auto_research/products/20260907/446467f767c98abb059fc9fa51ab2aa817596c969fcc2646cafd38b5011d9cfa.json"
    ).is_file(),
    reason="real legacy manager-research fixture is unavailable",
)
def test_real_legacy_ten_row_fixture_remains_compatible(tmp_path: Any) -> None:
    """The original 10-row/219-fact product still passes compatibility checks."""

    product_path = Path(
        "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/manager_auto_research/products/20260907/446467f767c98abb059fc9fa51ab2aa817596c969fcc2646cafd38b5011d9cfa.json"
    )
    product = json.loads(product_path.read_text(encoding="utf-8"))
    assert product["target_trade_date"] == "20260907"
    assert len(product["rows"]) == 10
    assert sum(len(row.get("facts", [])) for row in product["rows"]) == 219

    stage_manifest = json.loads(
        Path(
            "/Users/lexi/Library/Application Support/com.lexi.stage-center.local/state/selection/selection_runs/20260907/HK_CONNECT_SELECTION_STAGE_0935_0940/run-9bfdc71600c2945b32f62910/manifest.json"
        ).read_text(encoding="utf-8")
    )
    envelope = stage_manifest["selection_envelope"]
    raw_input = {
        "target_trade_date": stage_manifest["trade_date"],
        "stage_id": stage_manifest["stage_id"],
        "market": stage_manifest["market"],
        "status": stage_manifest["selection_status"],
        "cannot_confirm": envelope["cannot_confirm"],
        "raw_artifact_sha256": stage_manifest["raw_artifact_sha256"],
        "artifact_id": envelope["artifact_id"],
        "rows": envelope["rows"],
    }
    store = ManagerResearchStore(tmp_path)
    service = ManagerResearchJobService(store, lambda _date: raw_input, None)
    try:
        input_data = service._read_input("20260907")
        # The old product is the fixture under test.  Its historical identity
        # is retained as the compatibility alias while the exact stage rows
        # are supplied by the persisted selection manifest.
        legacy_product = deepcopy(product)
        legacy_identity = service._legacy_input_identity(input_data)
        assert legacy_identity is not None
        legacy_product["input_identity"] = legacy_identity
        legacy_product["product_id"] = f"manager-research-20260907-{legacy_identity[:24]}"
        store.write_product(legacy_product)

        result_envelope = service.get("20260907")

        assert result_envelope["product"] is not None
        migrated = result_envelope["product"]
        assert len(migrated["rows"]) == 10
        assert sum(len(row.get("facts", [])) for row in migrated["rows"]) == 219
        # GET is read-only under the F14 contract: the legacy binding is a
        # in-memory projection; persistence only happens through an explicit
        # replace/commit path, never during a read.
        assert store.read_product("20260907", input_data["input_identity"]) is None
    finally:
        service.close()


@pytest.mark.parametrize("cannot_confirm", [[], ["HK:UNSAFE"]])
def test_legacy_cache_migration_preserves_exact_partial_stage_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    cannot_confirm: list[str],
) -> None:
    """A READY provider row cannot upgrade an exact PARTIAL stage cache."""

    monkeypatch.setattr(service_module, "_now", lambda: "2026-09-08T10:00:00+08:00")
    raw_input = {
        "target_trade_date": "20260908",
        "stage_id": "STAGE_0935_0940",
        "status": "PARTIAL_WITH_ROWS",
        "cannot_confirm": cannot_confirm,
        "rows": [observation()],
    }
    store = ManagerResearchStore(tmp_path)
    service = ManagerResearchJobService(store, lambda _date: raw_input, None)
    try:
        input_data = service._read_input("20260908")
        old_product = ManagerResearchJobService._build_product(
            input_data,
            [observation()],
            {"HK.00001": result()},
        )
        # Simulate a legacy cache that has provider rows but no persisted stage
        # evidence and no recommendation contract yet.
        old_product.pop("stage_status", None)
        old_product.pop("cannot_confirm", None)
        old_product["recommendation_summary"] = None
        old_product["rows"][0].pop("research_recommendation", None)
        old_product["rows"][0].pop("observation_timing_status", None)
        store.write_product(old_product)

        migrated = service.get("20260908")["product"]
        assert migrated is not None
        recommendation = migrated["rows"][0]["research_recommendation"]
        assert recommendation["action"] == "CONDITIONAL_BUY"
        assert recommendation["status"] == "GENERATED"
        assert "STAGE_NOT_READY" in recommendation["blocking_reasons"]
        if cannot_confirm:
            assert "UPSTREAM_CANNOT_CONFIRM" in recommendation["blocking_reasons"]
        assert recommendation["evidence"]["stage_status"] == "PARTIAL_WITH_ROWS"
        assert recommendation["evidence"]["cannot_confirm"] == cannot_confirm
        assert migrated["stage_status"] == "PARTIAL_WITH_ROWS"
        assert migrated["cannot_confirm"] == cannot_confirm
    finally:
        service.close()


def test_cached_boilerplate_event_is_downgraded_in_pure_projection() -> None:
    legal_event = {
        "event_id": "cached-legal-1",
        "event_type": "ORDER_OR_CUSTOMER",
        "source_kind": "OFFICIAL",
        "source_url": "https://www1.hkexnews.hk/listedco/demo.pdf",
        "source_sha256": "c" * 64,
        "source_excerpt": "By order of the Board, the company secretary signs this notice pursuant to the Listing Rules.",
        "why_might_affect_business": "By order of the Board, the company secretary signs this notice pursuant to the Listing Rules.",
        "publisher_timestamp": "2026-09-08T08:30:00+08:00",
        "as_of_bucket": "current",
        "body_parsed": True,
        "event_relevant": True,
        "event_status": "READY",
        "summary_status": "PARSED",
    }
    product = {
        "target_trade_date": "20260908",
        "rows": [{
            "code": "HK.01191",
            "status": "CANNOT_CONFIRM",
            "catalyst_result": {
                "status": "READY",
                "events": [legal_event],
                "source_receipts": [{
                    "url": legal_event["source_url"],
                    "status": "READY",
                    "event_relevant": True,
                }],
                "catalyst_advice": {
                    "status": "OBSERVE",
                    "priority_rank": 1,
                    "focus_eligible": True,
                },
            },
        }],
    }

    projected = service_module._project_cached_catalysts(product)
    event = projected["rows"][0]["catalyst_result"]["events"][0]
    assert event["event_type"] == "OFFICIAL_UNCONFIRMED"
    assert event["original_event_type"] == "ORDER_OR_CUSTOMER"
    assert event["event_relevant"] is False
    assert event["event_status"] == "CANNOT_CONFIRM"
    assert event["summary_status"] == "UNCONFIRMED"
    assert event["source_sha256"] == "c" * 64
    assert "BUSINESS_SUMMARY_UNCONFIRMED" in event["market_confirmation_gap"]
    advice = projected["rows"][0]["catalyst_result"]["catalyst_advice"]
    assert advice["priority_rank"] is None
    assert advice["focus_eligible"] is False
    assert projected["rows"][0]["catalyst_result"]["source_receipts"][0]["status"] == "CANNOT_CONFIRM"
    # GET projection is pure: the stored row retains the original cached label.
    assert product["rows"][0]["catalyst_result"]["events"][0]["event_type"] == "ORDER_OR_CUSTOMER"


def test_cached_official_market_access_clause_uses_fresh_classifier() -> None:
    event = {
        "event_id": "cached-market-access-1",
        "event_type": "MARKET_ACCESS",
        "source_kind": "OFFICIAL",
        "source_url": "https://www1.hkexnews.hk/listedco/market-access.pdf",
        "source_sha256": "d" * 64,
        "source_excerpt": "H Shares have been included in the list of eligible securities for the Stock Connect.",
        "why_might_affect_business": "H Shares have been included in the list of eligible securities for the Stock Connect.",
        "publisher_timestamp": "2026-09-08T08:30:00+08:00",
        "as_of_bucket": "current",
        "body_parsed": True,
        "event_relevant": True,
        "event_status": "READY",
        "summary_status": "INTERPRETABLE",
    }
    product = {
        "target_trade_date": "20260908",
        "rows": [{
            "code": "HK.09637",
            "status": "READY",
            "catalyst_result": {
                "status": "READY",
                "events": [event],
                "source_receipts": [{
                    "url": event["source_url"],
                    "status": "READY",
                    "event_relevant": True,
                }],
                "catalyst_advice": {
                    "status": "OBSERVE",
                    "priority_rank": None,
                    "focus_eligible": False,
                },
            },
        }],
    }

    projected = service_module._project_cached_catalysts(product)
    projected_event = projected["rows"][0]["catalyst_result"]["events"][0]
    assert projected_event["event_type"] == "MARKET_ACCESS"
    assert projected_event["event_status"] == "READY"
    assert projected_event["summary_status"] == "INTERPRETABLE"
    assert projected_event["source_sha256"] == "d" * 64
    advice = projected["rows"][0]["catalyst_result"]["catalyst_advice"]
    assert advice["focus_eligible"] is True
    assert advice["priority_rank"] == 1
    assert projected["rows"][0]["catalyst_result"]["source_receipts"][0]["status"] == "READY"


@pytest.mark.parametrize(
    ("event_type", "excerpt"),
    [
        ("ORDER_OR_CUSTOMER", "The company has customers and contracts."),
        ("REGULATORY", "The company is subject to regulatory approval requirements."),
        (
            "COOPERATION",
            "The company is a developer. Entered into a cooperation agreement with a customer.",
        ),
        (
            "MARKET_ACCESS",
            "The company owns H Shares. Have been included in the list of eligible securities for the Stock Connect.",
        ),
    ],
)
def test_cached_static_and_cross_sentence_events_are_downgraded(
    event_type: str,
    excerpt: str,
) -> None:
    event = {
        "event_id": f"cached-action-gate-{event_type}",
        "event_type": event_type,
        "source_kind": "OFFICIAL",
        "source_url": "https://www1.hkexnews.hk/listedco/action-gate.pdf",
        "source_sha256": "e" * 64,
        "source_excerpt": excerpt,
        "why_might_affect_business": excerpt,
        "publisher_timestamp": "2026-09-08T08:30:00+08:00",
        "as_of_bucket": "current",
        "body_parsed": True,
        "event_relevant": True,
        "event_status": "READY",
        "summary_status": "INTERPRETABLE",
    }
    product = {
        "target_trade_date": "20260908",
        "rows": [{
            "code": "HK.01191",
            "status": "READY",
            "catalyst_result": {
                "status": "READY",
                "events": [event],
                "source_receipts": [{
                    "url": event["source_url"],
                    "status": "READY",
                    "event_relevant": True,
                }],
                "catalyst_advice": {
                    "status": "OBSERVE",
                    "priority_rank": 1,
                    "focus_eligible": True,
                },
            },
        }],
    }

    projected = service_module._project_cached_catalysts(product)
    projected_event = projected["rows"][0]["catalyst_result"]["events"][0]
    projected_advice = projected["rows"][0]["catalyst_result"]["catalyst_advice"]

    assert projected_event["event_type"] == "OFFICIAL_UNCONFIRMED"
    assert projected_event["original_event_type"] == event_type
    assert projected_event["event_relevant"] is False
    assert projected_event["event_status"] == "CANNOT_CONFIRM"
    assert projected_event["summary_status"] == "UNCONFIRMED"
    assert projected_advice["focus_eligible"] is False
    assert projected_advice["priority_rank"] is None
    assert projected["rows"][0]["catalyst_result"]["source_receipts"][0]["status"] == "CANNOT_CONFIRM"


@pytest.mark.parametrize(
    ("event_type", "excerpt", "expected_event_type", "expected_focus"),
    [
        ("COOPERATION", "The company entered into a loan agreement with a bank.", "OFFICIAL_UNCONFIRMED", False),
        ("COOPERATION", "The company signed an employment agreement with its CEO.", "OFFICIAL_UNCONFIRMED", False),
        ("COOPERATION", "The company reached a settlement agreement with a supplier.", "OFFICIAL_UNCONFIRMED", False),
        ("COOPERATION", "The company announced an agreement.", "OFFICIAL_UNCONFIRMED", False),
        ("ORDER_OR_CUSTOMER", "The company received orders worth HK$1.5 billion.", "ORDER_OR_CUSTOMER", True),
        ("PRODUCT_OR_TECHNOLOGY", "The company launched a technology platform version 1.0.", "PRODUCT_OR_TECHNOLOGY", True),
        ("REGULATORY", "The company obtained regulatory approval on 2026.09.08.", "REGULATORY", True),
        ("PRODUCT_OR_TECHNOLOGY", "The company launched a U.S. technology platform.", "PRODUCT_OR_TECHNOLOGY", True),
    ],
)
def test_cached_agreement_and_protected_punctuation_projection_matches_fresh_gate(
    event_type: str,
    excerpt: str,
    expected_event_type: str,
    expected_focus: bool,
) -> None:
    event = {
        "event_id": f"cached-v16-action-gate-{event_type}-{len(excerpt)}",
        "event_type": event_type,
        "source_kind": "OFFICIAL",
        "source_url": "https://www1.hkexnews.hk/listedco/v16-action-gate.pdf",
        "source_sha256": "f" * 64,
        "source_excerpt": excerpt,
        "why_might_affect_business": excerpt,
        "publisher_timestamp": "2026-09-08T08:30:00+08:00",
        "as_of_bucket": "current",
        "body_parsed": True,
        "event_relevant": True,
        "event_status": "READY",
        "summary_status": "INTERPRETABLE",
    }
    product = {
        "target_trade_date": "20260908",
        "rows": [{
            "code": "HK.01191",
            "status": "READY",
            "catalyst_result": {
                "status": "READY",
                "events": [event],
                "source_receipts": [{
                    "url": event["source_url"],
                    "status": "READY",
                    "event_relevant": True,
                }],
                "catalyst_advice": {
                    "status": "OBSERVE",
                    "priority_rank": 1,
                    "focus_eligible": True,
                },
            },
        }],
    }

    projected = service_module._project_cached_catalysts(product)
    projected_event = projected["rows"][0]["catalyst_result"]["events"][0]
    projected_advice = projected["rows"][0]["catalyst_result"]["catalyst_advice"]

    assert projected_event["event_type"] == expected_event_type
    assert projected_advice["focus_eligible"] is expected_focus
    if expected_focus:
        assert projected_event["event_status"] == "READY"
        assert projected_event["summary_status"] == "INTERPRETABLE"
        assert projected_advice["priority_rank"] == 1
        assert projected["rows"][0]["catalyst_result"]["source_receipts"][0]["status"] == "READY"
    else:
        assert projected_event["event_status"] == "CANNOT_CONFIRM"
        assert projected_event["summary_status"] == "UNCONFIRMED"
        assert projected_advice["priority_rank"] is None
        assert projected["rows"][0]["catalyst_result"]["source_receipts"][0]["status"] == "CANNOT_CONFIRM"


@pytest.mark.parametrize(
    ("event_type", "excerpt", "expected_event_type", "expected_focus"),
    [
        (
            "ORDER_OR_CUSTOMER",
            "The company has customers and contracts.” A partner received orders from a customer.",
            "OFFICIAL_UNCONFIRMED",
            False,
        ),
        (
            "PRODUCT_OR_TECHNOLOGY",
            "The company has a business.） A partner launched a technology platform.",
            "OFFICIAL_UNCONFIRMED",
            False,
        ),
        (
            "REGULATORY",
            "The company has requirements.》 A regulator obtained regulatory approval.",
            "OFFICIAL_UNCONFIRMED",
            False,
        ),
        (
            "ORDER_OR_CUSTOMER",
            "The company has background.” The company received orders from a customer.",
            "ORDER_OR_CUSTOMER",
            True,
        ),
        (
            "PRODUCT_OR_TECHNOLOGY",
            "The company has background.） The company launched a technology platform.",
            "PRODUCT_OR_TECHNOLOGY",
            True,
        ),
        (
            "REGULATORY",
            "The company has background.》 The company obtained regulatory approval.",
            "REGULATORY",
            True,
        ),
    ],
)
def test_cached_unicode_closer_projection_matches_fresh_entity_boundary(
    event_type: str,
    excerpt: str,
    expected_event_type: str,
    expected_focus: bool,
) -> None:
    event = {
        "event_id": f"cached-v17-unicode-{event_type}-{len(excerpt)}",
        "event_type": event_type,
        "source_kind": "OFFICIAL",
        "source_url": "https://www1.hkexnews.hk/listedco/v17-unicode-boundary.pdf",
        "source_sha256": "f" * 64,
        "source_title": "Announcement",
        "source_excerpt": excerpt,
        "why_might_affect_business": excerpt,
        "publisher_timestamp": "2026-09-08T08:30:00+08:00",
        "as_of_bucket": "current",
        "body_parsed": True,
        "event_relevant": True,
        "event_status": "READY",
        "summary_status": "INTERPRETABLE",
    }
    product = {
        "target_trade_date": "20260908",
        "rows": [{
            "code": "HK.01191",
            "status": "READY",
            "catalyst_result": {
                "status": "READY",
                "events": [event],
                "source_receipts": [{
                    "url": event["source_url"],
                    "status": "READY",
                    "event_relevant": True,
                }],
                "catalyst_advice": {
                    "status": "OBSERVE",
                    "priority_rank": 1,
                    "focus_eligible": True,
                },
            },
        }],
    }

    projected = service_module._project_cached_catalysts(product)
    projected_event = projected["rows"][0]["catalyst_result"]["events"][0]
    projected_advice = projected["rows"][0]["catalyst_result"]["catalyst_advice"]
    receipt = projected["rows"][0]["catalyst_result"]["source_receipts"][0]

    assert projected_event["event_type"] == expected_event_type
    assert projected_advice["focus_eligible"] is expected_focus
    if expected_focus:
        assert projected_event["event_status"] == "READY"
        assert projected_event["summary_status"] == "INTERPRETABLE"
        assert projected_advice["priority_rank"] == 1
        assert receipt["status"] == "READY"
    else:
        assert projected_event["event_relevant"] is False
        assert projected_event["event_status"] == "CANNOT_CONFIRM"
        assert projected_event["summary_status"] == "UNCONFIRMED"
        assert projected_advice["priority_rank"] is None
        assert receipt["status"] == "CANNOT_CONFIRM"


def test_real_v12_sixteen_event_projection_matches_frozen_semantic_review() -> None:
    """Re-run the actual cached 16-event receipt through the current classifier.

    The semantic review is the frozen oracle for this acceptance delta.  The
    API product is read-only input; projection must preserve every event id,
    source locator and raw source hash while correcting only semantic fields.
    """

    review_path = Path(
        "/Users/lexi/Desktop/学习/agents调试/助手/manager_priority_20260908/review/v12-live16-semantic.json"
    )
    api_path = Path(
        "/Users/lexi/Desktop/学习/agents调试/助手/manager_priority_20260908/catalyst_rebuild/integration-v12/research-20260908.json"
    )
    review = json.loads(review_path.read_text())
    api_product = json.loads(api_path.read_text())["product"]
    projected = service_module._project_cached_catalysts(api_product)

    expected = {item["event_id"]: item for item in review["events"]}
    observed: dict[str, dict[str, Any]] = {}
    for row in projected["rows"]:
        result = row.get("catalyst_result") or {}
        for event in result.get("events", []):
            observed[str(event.get("event_id"))] = event

    assert set(observed) == set(expected)
    for event_id, oracle in expected.items():
        actual = observed[event_id]
        assert actual["semantic_class"] == oracle["expected_class"]
        assert event_is_focus_eligible(actual, target_trade_date="20260908") is oracle["expected_focus_eligible"]
        locator = oracle["source_locator"]
        for field in ("source_url", "publisher_timestamp", "as_of_bucket"):
            assert actual.get(field) == locator[field]
        assert actual.get("source_sha256") == locator["source_sha256"]

    coverage = projected["catalyst_coverage"]
    assert coverage["semantic_class_counts"] == review["expected_class_counts"]
    assert coverage["focus_event_count"] == sum(
        1 for item in review["events"] if item["expected_focus_eligible"]
    )
    assert coverage["classification_basis"] == "CURRENT_EVENT_PROJECTION"
    raw_counts = [
        item for item in coverage["source_counts"]
        if item.get("source_id") == "v4.hkex.official_event_directory.v1"
    ]
    assert raw_counts and raw_counts[0]["substantive_body"] == 13

    ranked = {
        str(row["code"]): row["catalyst_result"]["catalyst_advice"]["priority_rank"]
        for row in projected["rows"]
        if isinstance(row.get("catalyst_result"), dict)
        and row["catalyst_result"].get("catalyst_advice", {}).get("priority_rank") is not None
    }
    expected_ranked = {
        item["code"]: item["observed_projection"]["row_focus_advice"]["priority_rank"]
        for item in review["events"]
        if item["expected_focus_eligible"]
    }
    assert ranked == expected_ranked

    # The pure projection must not mutate the raw cached event payload.
    assert all("semantic_class" not in event for row in api_product["rows"] for event in (row.get("catalyst_result") or {}).get("events", []))


def test_focus_ranks_newest_publication_first_and_ignores_unresolved_bucket() -> None:
    rows = []
    for index, day in enumerate(("08", "07", "06", "05"), start=1):
        rows.append({
            "code": f"HK.09{index:03d}",
            "catalyst_result": {
                "events": [{
                    "event_id": f"focus-{day}",
                    "event_type": "COOPERATION",
                    "source_kind": "MEDIA",
                    "source_excerpt": "The parties will deliver products under a cooperation agreement.",
                    "publisher_timestamp": f"2026-09-{day}T08:30:00+08:00",
                    "body_parsed": True,
                    "event_relevant": True,
                    "event_status": "READY",
                    "summary_status": "INTERPRETABLE",
                    "as_of_bucket": "current",
                }],
                "catalyst_advice": {},
            },
        })

    # A valid publisher timestamp alone cannot promote an event whose date
    # bucket is unresolved.
    rows.append({
        "code": "HK.09999",
        "catalyst_result": {
            "events": [{
                "event_id": "focus-null-bucket",
                "event_type": "COOPERATION",
                "source_kind": "MEDIA",
                "source_excerpt": "The parties will deliver products under a cooperation agreement.",
                "publisher_timestamp": "2026-09-08T08:00:00+08:00",
                "body_parsed": True,
                "event_relevant": True,
                "event_status": "READY",
                "summary_status": "INTERPRETABLE",
                "as_of_bucket": None,
            }],
            "catalyst_advice": {},
        },
    })

    service_module._assign_catalyst_focus_ranks(rows, "20260908")

    ranks = {
        row["code"]: row["catalyst_result"]["catalyst_advice"]["priority_rank"]
        for row in rows
    }
    assert ranks["HK.09001"] == 1
    assert ranks["HK.09002"] == 2
    assert ranks["HK.09003"] == 3
    assert ranks["HK.09004"] is None
    assert ranks["HK.09999"] is None
    assert rows[-1]["catalyst_result"]["catalyst_advice"]["focus_eligible"] is False
