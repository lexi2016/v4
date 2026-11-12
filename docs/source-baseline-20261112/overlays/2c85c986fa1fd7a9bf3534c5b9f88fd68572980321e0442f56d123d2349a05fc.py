from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from contracts.research import DEDUPE_KEY_FIELDS, SCHEMA_VERSION
from contracts.research_day_product import (
    EXPECTED_RESEARCH_SLOTS,
    PRODUCT_SCHEMA_VERSION,
    validate_research_day_product,
)
from domains.research_day_product import (
    build_research_day_product,
    normalize_pair_identity,
)
from infrastructure.research_store import HourlyResearchStore, ResearchArchiveStore
from ops.materialize_research_day import materialize_research_day


DATE = "20260824"
RAW_ROWS_BY_SLOT = {
    "1000": 604,
    "1100": 69,
    "1200": 1,
    "1300": 24,
    "1400": 19,
    "1500": 21,
    "1600": 7,
    "1700": 7,
}
EXCLUDED_BY_DATE = {
    "20260820": 13,
    "20260822": 117,
    "20260823": 292,
}
FIXTURE_REGISTRY = {
    "status": "MISSING",
    "jyg_coverage": {
        "articles": 3,
        "expected_articles": 3,
        "stock_mentions": 0,
    },
}


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _row(
    slot: str,
    code: str = "000001",
    url: str = "https://example.test/a?x=1",
    *,
    article_id: str | None = None,
    evidence_level: str = "L2_MEDIUM",
    confidence: str = "MEDIUM",
    sentence: str = "一个 exact-date 研究证据。",
    published_date: str = DATE,
    published_at: str | None = None,
    archive_date: str = DATE,
) -> dict:
    timestamp = published_at or f"{published_date}T{slot[:2]}:{slot[2:]}:00+08:00"
    collected_at = timestamp if published_at else f"{published_date}T{slot[:2]}:{slot[2:]}:30+08:00"
    identity = article_id or f"article-{slot}-{code}-{url}"
    return {
        "article_id": _sha(identity),
        "dedupe_key": _sha(f"dedupe-{identity}"),
        "archive_date": archive_date,
        "stock_code": code,
        "stock_name": "平安银行",
        "source_type": "hourly_research",
        "source_name": "V4 deterministic fixture",
        "source_title": "研究标题",
        "source_path_sha256": _sha(f"source-path-{url}"),
        "url": url,
        "theme": "银行",
        "catalyst": "业绩",
        "evidence_sentence": sentence,
        "evidence_level": evidence_level,
        "confidence": confidence,
        "published_at": timestamp,
        "collected_at": collected_at,
        "first_seen_at": timestamp,
        "duplicate_evidence_count": 1,
        "source_dedup_keys": [_sha(f"source-dedup-{identity}")],
        "recommendation_status": "RESEARCH_ONLY",
    }


def _stock_pool_row(code: str = "000001") -> dict:
    return {
        "stock_code": code,
        "stock_name": "平安银行",
        "archive_date": DATE,
        "research_score": 0,
        "research_status": "OBSERVED",
        "evidence_count": 1,
        "source_count": 1,
        "strong_evidence_count": 0,
        "medium_evidence_count": 1,
        "weak_evidence_count": 0,
        "source_types": ["hourly_research"],
        "themes": ["银行"],
        "top_catalysts": ["业绩"],
        "first_seen_at": "2026-08-24T10:00:00+08:00",
        "collected_at": "2026-08-24T10:00:30+08:00",
        "formal_overlap": False,
        "stage_overlap": False,
        "recommendation_status": "RESEARCH_ONLY",
    }


def _slot_payload(
    slot: str,
    rows: list[dict],
    *,
    source_input_sha256: str | None = None,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "archive_date": DATE,
        "status": "READY",
        "timezone": "Asia/Shanghai",
        "source_input_sha256": source_input_sha256 or _sha(f"input-{slot}"),
        "source_schema_version": "v3_research_lane.v2",
        "source_generated_at": f"2026-08-24T{slot[:2]}:{slot[2:]}:00+08:00",
        "dedupe_key_fields": list(DEDUPE_KEY_FIELDS),
        "article_count": len(rows),
        "stock_pool_count": 1,
        "source_counts": {"fixture": len(rows)},
        "articles": rows,
        "stock_pool": [_stock_pool_row()],
        "cannot_confirm": [],
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _fixture_slots() -> dict[str, dict]:
    slots: dict[str, dict] = {}
    pair_id = 0
    exact_counts = {
        "1000": 182,
        "1100": 69,
        "1200": 1,
        "1300": 24,
        "1400": 19,
        "1500": 21,
    }
    for slot in EXPECTED_RESEARCH_SLOTS[:6]:
        rows: list[dict] = []
        if slot == "1000":
            for old_date, count in EXCLUDED_BY_DATE.items():
                for index in range(count):
                    rows.append(
                        _row(
                            slot,
                            code=f"{(index % 242) + 1:06d}",
                            url=f"https://example.test/old-{old_date}-{index}",
                            article_id=f"old-{old_date}-{index}",
                            published_date=old_date,
                        )
                    )
        for _ in range(exact_counts[slot]):
            url = f"https://example.test/article-{pair_id % 195}"
            code = f"{(pair_id % 242) + 1:06d}"
            rows.append(
                _row(
                    slot,
                    code=code,
                    url=url,
                    article_id=f"pair-{pair_id}-slot-{slot}",
                )
            )
            pair_id += 1
        slots[slot] = _slot_payload(slot, rows)

    duplicate_rows: dict[str, list[dict]] = {"1600": [], "1700": []}
    for duplicate_id in range(316, 323):
        code = f"{(duplicate_id % 242) + 1:06d}"
        url = f"https://example.test/article-{duplicate_id % 195}"
        for slot in ("1600", "1700"):
            sentence = (
                "一个跨槽稳定变体。"
                if duplicate_id < 322 and slot == "1700"
                else "一个跨槽稳定证据。"
            )
            duplicate_rows[slot].append(
                _row(
                    slot,
                    code=code,
                    url=url,
                    article_id=f"pair-{duplicate_id}-slot-{slot}",
                    sentence=sentence,
                )
            )
    slots["1600"] = _slot_payload("1600", duplicate_rows["1600"])
    slots["1700"] = _slot_payload("1700", duplicate_rows["1700"])
    assert {slot: len(payload["articles"]) for slot, payload in slots.items()} == RAW_ROWS_BY_SLOT
    return slots


def _seed(
    root: Path,
    *,
    slots: dict[str, dict] | None = None,
    registry: dict | None = FIXTURE_REGISTRY,
    omit_slots: set[str] | None = None,
) -> dict:
    hourly = HourlyResearchStore(root)
    for slot, payload in (slots or _fixture_slots()).items():
        if omit_slots and slot in omit_slots:
            continue
        hourly.publish(payload, slot=slot, mode="LIVE")
    return materialize_research_day(root, DATE, stock_mentions_registry=registry)


def test_identity_nfkc_keeps_url_path_and_uppercases_stock() -> None:
    identity = normalize_pair_identity("  https://Example.test/路径?q=A  ", " abc123 ")

    assert identity == "https://Example.test/路径?q=A|ABC123"
    assert normalize_pair_identity(123, "abc123") is None


def test_real_live_fixture_reconciles_counts_duplicates_lineage_and_jyg_gap(
    tmp_path: Path,
) -> None:
    result = _seed(tmp_path / "data")

    assert result["schema_version"] == PRODUCT_SCHEMA_VERSION
    assert result["status"] == "READY_WITH_DECLARED_GAPS"
    assert result["coverage"]["expected_slots"] == 8
    assert result["coverage"]["ready_slots"] == 8
    assert result["counts"] == {
        "raw_rows": 752,
        "evidence_rows": 330,
        "excluded_rows": 422,
        "mention_pairs": 323,
        "urls": 195,
        "stock_rollups": 242,
        "high_priority": 0,
        "duplicate_pairs": 7,
    }
    assert result["exclusions"] == {
        "date_mismatch": 422,
        "pit_violation": 0,
        "invalid_row": 0,
    }
    assert result["exclusions"]["pit_violation"] == 0
    assert result["excluded_by_date"] == EXCLUDED_BY_DATE
    assert result["jyg_coverage"] == {
        "status": "CANNOT_CONFIRM",
        "articles": 3,
        "expected_articles": 3,
        "stock_mentions": 0,
        "registry": "MISSING",
        "gap": "JYG_STOCK_MENTIONS_REGISTRY_MISSING",
    }
    assert result["high_priority"] == []
    assert result["high_priority_status"]["status"] == "CANNOT_CONFIRM"
    assert result["authoritative"] is False
    assert result["cannot_confirm"] == ["JYG_STOCK_MENTIONS_REGISTRY_MISSING"]
    duplicates = [
        row for row in result["mention_pairs"] if row["occurrence_count"] > 1
    ]
    assert len(duplicates) == 7
    assert {tuple(row["source_slots"]) for row in duplicates} == {
        ("1600", "1700")
    }
    assert sorted(row["variant_count"] for row in duplicates) == [1, 2, 2, 2, 2, 2, 2]
    assert all(row["duplicate_reason"] == "CROSS_SLOT_REPEAT" for row in duplicates)
    assert tuple(
        result["slot_matrix"][0][field]
        for field in ("raw_rows", "exact_rows", "excluded_rows")
    ) == (604, 182, 422)
    for slot in EXPECTED_RESEARCH_SLOTS:
        ref = result["lineage"]["source_refs"][slot]
        assert ref["artifact_path"] == f"research/hourly/live/{DATE}/{slot}.json"
        assert ref["receipt_path"] == f"receipts/research/hourly/live/{DATE}/{slot}.json"
        assert len(ref["artifact_sha256"]) == 64
        assert len(ref["receipt_sha256"]) == 64
        assert len(ref["source_input_sha256"]) == 64
    core = {
        key: value
        for key, value in result.items()
        if key in {
            "schema_version", "contract_id", "workflow_name", "pass_signal",
            "archive_date", "timezone", "date_mode", "status", "authoritative",
            "write_policy", "recommendation_status", "expected_slots", "coverage",
            "counts", "exclusions", "excluded_by_date", "slot_matrix",
            "evidence_rows", "mention_pairs", "stock_rollups", "high_priority",
            "high_priority_status", "jyg_coverage", "lineage", "cannot_confirm",
            "RESEARCH_ONLY", "production_allowed", "buy_gate_updated", "orders_sent",
        }
    }
    assert validate_research_day_product(core) == DATE


def test_day_product_requires_explicit_research_only_boolean() -> None:
    product = build_research_day_product(
        DATE,
        _fixture_slots(),
        stock_mentions_registry={"status": "VALIDATED", "high_priority": [], "rule_id": "r"},
    )
    for value in (None, False, "true"):
        candidate = deepcopy(product)
        if value is None:
            del candidate["RESEARCH_ONLY"]
        else:
            candidate["RESEARCH_ONLY"] = value
        with pytest.raises(ValueError, match="RESEARCH_ONLY"):
            validate_research_day_product(candidate)


def test_jyg_coverage_without_explicit_registry_metadata_is_unknown() -> None:
    product = build_research_day_product(
        DATE,
        _fixture_slots(),
        stock_mentions_registry={
            "status": "VALIDATED",
            "rule_id": "r",
            "high_priority": [],
        },
    )

    assert product["jyg_coverage"] == {
        "status": "CANNOT_CONFIRM",
        "articles": None,
        "expected_articles": None,
        "stock_mentions": None,
        "registry": "MISSING",
        "gap": "JYG_STOCK_MENTIONS_REGISTRY_MISSING",
    }
    assert product["authoritative"] is False


def test_published_at_is_the_only_exact_date_gate_and_invalid_time_is_typed() -> None:
    slots = _fixture_slots()
    slots["1000"]["articles"][422]["archive_date"] = "20260820"
    exact_from_published = build_research_day_product(
        DATE,
        slots,
        stock_mentions_registry={"status": "VALIDATED", "rule_id": "r", "high_priority": []},
    )
    assert exact_from_published["counts"]["evidence_rows"] == 330
    assert exact_from_published["evidence_rows"][0]["archive_date"] == DATE

    invalid_slots = _fixture_slots()
    invalid_slots["1000"]["articles"][422]["published_at"] = "2026-08-24T10:00:00"
    result = build_research_day_product(
        DATE,
        invalid_slots,
        stock_mentions_registry={"status": "VALIDATED", "rule_id": "r", "high_priority": []},
    )
    assert result["status"] == "READY_WITH_DECLARED_GAPS"
    assert result["counts"]["evidence_rows"] == 329
    assert result["counts"]["excluded_rows"] == 423
    assert result["exclusions"]["invalid_row"] == 1
    assert any(item.startswith("PUBLISHED_AT_INVALID:1000:") for item in result["cannot_confirm"])
    assert result["excluded_by_date"] == EXCLUDED_BY_DATE


def test_exact_date_published_at_ignores_later_slot_and_auxiliary_timestamps() -> None:
    slots = _fixture_slots()
    row = slots["1000"]["articles"][422]
    row["published_at"] = "2026-08-24T23:59:59+08:00"
    row["event_time"] = "2026-08-25T23:59:59+08:00"
    row["source_published_at"] = "2026-08-25T23:59:59+08:00"
    row["collected_at"] = "2026-08-25T23:59:59+08:00"
    row["first_seen_at"] = "2026-08-25T23:59:59+08:00"
    row["last_checked_at"] = "2026-08-25T23:59:59+08:00"

    result = build_research_day_product(
        DATE,
        slots,
        stock_mentions_registry=FIXTURE_REGISTRY,
    )

    assert result["counts"]["evidence_rows"] == 330
    assert result["counts"]["mention_pairs"] == 323
    assert result["counts"]["urls"] == 195
    assert result["counts"]["stock_rollups"] == 242
    assert result["counts"]["duplicate_pairs"] == 7
    assert result["exclusions"]["pit_violation"] == 0


def test_auxiliary_timestamps_do_not_change_variant_sha_or_winner() -> None:
    baseline = build_research_day_product(
        DATE,
        _fixture_slots(),
        stock_mentions_registry=FIXTURE_REGISTRY,
    )
    changed_slots = deepcopy(_fixture_slots())
    changed_row = changed_slots["1700"]["articles"][6]
    changed_row["event_time"] = "2026-08-25T23:59:59+08:00"
    changed_row["source_published_at"] = "2026-08-25T23:59:59+08:00"
    changed_row["last_checked_at"] = "2026-08-25T23:59:59+08:00"
    changed = build_research_day_product(
        DATE,
        changed_slots,
        stock_mentions_registry=FIXTURE_REGISTRY,
    )

    baseline_pair = next(
        pair
        for pair in baseline["mention_pairs"]
        if pair["occurrence_count"] > 1 and pair["variant_count"] == 1
    )
    changed_pair = next(
        pair for pair in changed["mention_pairs"]
        if pair["pair_key"] == baseline_pair["pair_key"]
    )
    assert changed_pair["variant_count"] == baseline_pair["variant_count"] == 1
    assert changed_pair["tiebreaker"]["variant_sha256"] == baseline_pair["tiebreaker"]["variant_sha256"]
    assert changed_pair["winner"]["slot"] == baseline_pair["winner"]["slot"] == "1700"
    assert changed_pair["winner"]["event_time"] == "2026-08-25T23:59:59+08:00"


def test_semantic_evidence_fields_still_distinguish_variants() -> None:
    baseline = build_research_day_product(
        DATE,
        _fixture_slots(),
        stock_mentions_registry=FIXTURE_REGISTRY,
    )
    changed_slots = deepcopy(_fixture_slots())
    changed_row = changed_slots["1700"]["articles"][6]
    changed_row["evidence_level"] = "L3_STRONG"
    changed_row["confidence"] = "HIGH"
    changed = build_research_day_product(
        DATE,
        changed_slots,
        stock_mentions_registry=FIXTURE_REGISTRY,
    )

    baseline_pair = next(
        pair
        for pair in baseline["mention_pairs"]
        if pair["occurrence_count"] > 1 and pair["variant_count"] == 1
    )
    changed_pair = next(
        pair for pair in changed["mention_pairs"]
        if pair["pair_key"] == baseline_pair["pair_key"]
    )
    assert changed_pair["variant_count"] == 2
    assert changed_pair["tiebreaker"]["evidence_level"] == "L3_STRONG"
    assert changed_pair["tiebreaker"]["confidence"] == "HIGH"


def test_materializer_reads_only_real_live_slots_and_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "data"
    first = _seed(root)
    second = materialize_research_day(root, DATE, stock_mentions_registry=FIXTURE_REGISTRY)

    assert first["current_updated"] is True
    assert second["payload_sha256"] == first["payload_sha256"]
    assert second["current_updated"] is False
    store = ResearchArchiveStore(root)
    assert store.read_day_exact(DATE) is not None
    assert store.read_day_latest() == store.read_day_exact(DATE)
    assert store.read_day_current() == store.read_day_exact(DATE)
    assert not (root / "research" / "hourly" / "day").exists()


def test_materializer_missing_slot_is_typed_and_does_not_publish(tmp_path: Path) -> None:
    root = tmp_path / "data"
    result = _seed(root, omit_slots={"1700"})

    assert result["status"] == "NOT_MATERIALIZED"
    assert result["missing_slots"] == list(EXPECTED_RESEARCH_SLOTS)
    assert result["cannot_confirm"] == ["MISSING_SLOT:1700"]
    assert ResearchArchiveStore(root).read_day_exact(DATE) is None


def test_materializer_tampered_live_slot_is_fail_closed(tmp_path: Path) -> None:
    root = tmp_path / "data"
    slots = _fixture_slots()
    hourly = HourlyResearchStore(root)
    for slot, payload in slots.items():
        hourly.publish(payload, slot=slot, mode="LIVE")
    artifact = root / "research" / "hourly" / "live" / DATE / "1700.json"
    tampered = json.loads(artifact.read_text(encoding="utf-8"))
    tampered["articles"][0]["source_title"] = "tampered"
    artifact.write_text(json.dumps(tampered, ensure_ascii=False), encoding="utf-8")

    result = materialize_research_day(root, DATE, stock_mentions_registry=FIXTURE_REGISTRY)

    assert result["status"] == "NOT_MATERIALIZED"
    assert result["missing_slots"] == list(EXPECTED_RESEARCH_SLOTS)
    assert "HOURLY_SLOT_INVALID:1700" in result["cannot_confirm"]
    assert ResearchArchiveStore(root).read_day_exact(DATE) is None


def test_live_slot_conflict_is_rejected_without_replacing_bytes(tmp_path: Path) -> None:
    root = tmp_path / "data"
    store = HourlyResearchStore(root)
    payload = _slot_payload("1000", [_row("1000")])
    first = store.publish(payload, slot="1000", mode="LIVE")
    changed = deepcopy(payload)
    changed["articles"][0]["source_title"] = "conflict"

    with pytest.raises(ValueError, match="conflicting hourly research materialization"):
        store.publish(changed, slot="1000", mode="LIVE")
    assert store.read_exact("20260824", "1000", mode="LIVE")["source_input_sha256"] == payload["source_input_sha256"]
    assert first["payload_sha256"] != _sha(json.dumps(changed, sort_keys=True))
