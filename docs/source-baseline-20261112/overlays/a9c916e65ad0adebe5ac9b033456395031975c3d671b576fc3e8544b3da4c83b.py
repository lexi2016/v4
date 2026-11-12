from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from infrastructure.data_store import _sha256
from infrastructure.research_store import HourlyResearchStore, ResearchArchiveStore
from test_research_day_product import DATE, FIXTURE_REGISTRY, _fixture_slots
from ops.materialize_research_day import materialize_research_day


def _seed_hourly(root: Path) -> dict[str, dict]:
    slots = _fixture_slots()
    store = HourlyResearchStore(root)
    for slot, payload in slots.items():
        store.publish(payload, slot=slot, mode="LIVE")
    return slots


def test_day_namespace_preserves_legacy_archive_bytes_and_manifest_entry(tmp_path: Path) -> None:
    root = tmp_path / "data"
    slots = _seed_hourly(root)
    archive = ResearchArchiveStore(root)
    legacy_before = archive.publish(slots["1000"], mode="LIVE")
    generic_path = root / legacy_before["payload_path"]
    generic_receipt_path = root / legacy_before["receipt_path"]
    generic_latest_path = root / "research/latest.json"
    generic_bytes = generic_path.read_bytes()
    generic_receipt_bytes = generic_receipt_path.read_bytes()
    generic_latest_bytes = generic_latest_path.read_bytes()
    manifest_before = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    generic_manifest_sha = manifest_before[legacy_before["payload_path"]]

    result = materialize_research_day(
        root,
        DATE,
        stock_mentions_registry=FIXTURE_REGISTRY,
    )

    assert result["status"] == "READY_WITH_DECLARED_GAPS"
    assert result["payload_path"] == f"research/day/archives/{DATE}.json"
    assert result["receipt_path"] == f"receipts/research/day/archives/{DATE}.json"
    assert generic_path.read_bytes() == generic_bytes
    assert generic_receipt_path.read_bytes() == generic_receipt_bytes
    assert generic_latest_path.read_bytes() == generic_latest_bytes
    manifest_after = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_after[legacy_before["payload_path"]] == generic_manifest_sha
    assert archive.read_exact(DATE) == slots["1000"]
    assert archive.read_day_exact(DATE)["archive_date"] == DATE
    assert archive.read_latest() == slots["1000"]
    assert archive.read_day_latest()["archive_date"] == DATE
    assert archive.read_day_current()["archive_date"] == DATE


def test_generic_and_day_reimports_are_independently_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "data"
    slots = _seed_hourly(root)
    archive = ResearchArchiveStore(root)
    legacy = archive.publish(slots["1000"], mode="LIVE")
    first = materialize_research_day(root, DATE, stock_mentions_registry=FIXTURE_REGISTRY)
    second = materialize_research_day(root, DATE, stock_mentions_registry=FIXTURE_REGISTRY)
    legacy_again = archive.publish(slots["1000"], mode="LIVE")

    assert second["payload_sha256"] == first["payload_sha256"]
    assert second["latest_updated"] is False
    assert second["current_updated"] is False
    assert legacy_again["payload_sha256"] == legacy["payload_sha256"]
    assert legacy_again["latest_updated"] is False
    assert archive.read_exact(DATE)["schema_version"] == "v3_5.research_archive.v1"
    assert archive.read_day_exact(DATE)["schema_version"] == "v3_5.research_day_product.v1"


def test_generic_archive_expected_old_cas_preserves_preimage_and_fails_closed(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    slots = _seed_hourly(root)
    archive = ResearchArchiveStore(root)
    old = copy.deepcopy(slots["1000"])
    archive.publish(old, mode="LIVE")
    new = copy.deepcopy(old)
    new["source_input_sha256"] = "f" * 64

    generic_path = root / archive._relative(DATE)
    generic_receipt_path = root / archive._receipt_relative(DATE)
    latest_path = root / "research/latest.json"
    manifest_path = root / "manifest.json"
    before = {
        "payload": generic_path.read_bytes(),
        "receipt": generic_receipt_path.read_bytes(),
        "latest": latest_path.read_bytes(),
        "manifest": manifest_path.read_bytes(),
    }
    with pytest.raises(ValueError, match="expected SHA"):
        archive.replace(
            new,
            mode="LIVE",
            expected_sha256="0" * 64,
            reason="VERIFIED_LATE_SOURCE_RECOVERY",
        )
    assert {
        "payload": generic_path.read_bytes(),
        "receipt": generic_receipt_path.read_bytes(),
        "latest": latest_path.read_bytes(),
        "manifest": manifest_path.read_bytes(),
    } == before

    result = archive.replace(
        new,
        mode="LIVE",
        expected_sha256=_sha256(old),
        reason="VERIFIED_LATE_SOURCE_RECOVERY",
    )
    assert result["replaced"] is True
    assert result["latest_updated"] is True
    assert archive.read_exact(DATE) == new
    assert archive.read_latest() == new
    history_path = root / result["previous_payload_path"]
    history_receipt_path = root / result["previous_receipt_path"]
    assert json.loads(history_path.read_text(encoding="utf-8")) == old
    assert history_receipt_path.is_file()
    supersession = json.loads(
        (root / result["supersession_receipt_path"]).read_text(encoding="utf-8")
    )
    assert supersession["previous_payload_sha256"] == _sha256(old)
    assert supersession["payload_sha256"] == _sha256(new)

    repeated = archive.replace(
        new,
        mode="LIVE",
        expected_sha256=_sha256(old),
        reason="VERIFIED_LATE_SOURCE_RECOVERY",
    )
    assert repeated["replaced"] is False
    assert repeated["latest_updated"] is False

    # The ordinary import path remains immutable and does not become a
    # generic replacement API by virtue of the recovery CAS.
    root2 = tmp_path / "data2"
    slots2 = _seed_hourly(root2)
    archive2 = ResearchArchiveStore(root2)
    archive2.publish(slots2["1000"], mode="LIVE")
    with pytest.raises(ValueError, match="conflicting research archive re-import"):
        archive2.publish(new, mode="LIVE")


@pytest.mark.parametrize(
    ("field", "tampered"),
    [
        ("schema_version", "tampered.schema.v1"),
        ("source_input_sha256", "0" * 64),
        ("source_provenance", {"tampered": True}),
        ("reason", "TAMPERED_REASON"),
        ("previous_source_input_sha256", "0" * 64),
        ("previous_payload_path", "research/archives/tampered.json"),
        ("previous_receipt_sha256", "0" * 64),
        ("previous_manifest_sha256", "1" * 64),
        ("previous_latest_pointer", {"tampered": True}),
        ("previous_latest_pointer_sha256", "0" * 64),
        ("write_policy", "writable"),
        ("production_allowed", True),
        ("buy_gate_updated", True),
        ("orders_sent", True),
    ],
)
def test_generic_retry_rejects_supersession_lineage_tamper(
    tmp_path: Path, field: str, tampered: object
) -> None:
    root = tmp_path / "data"
    slots = _seed_hourly(root)
    archive = ResearchArchiveStore(root)
    old = copy.deepcopy(slots["1000"])
    archive.publish(old, mode="LIVE")
    new = copy.deepcopy(old)
    new["source_input_sha256"] = "f" * 64
    provenance = {
        "source_path": "recovery/1000.json",
        "capture_origin": "LATE_RECOVERY",
    }
    result = archive.replace(
        new,
        mode="LIVE",
        expected_sha256=_sha256(old),
        reason="VERIFIED_LATE_SOURCE_RECOVERY",
        source_provenance=provenance,
    )
    supersession_path = root / result["supersession_receipt_path"]
    supersession = json.loads(supersession_path.read_text(encoding="utf-8"))
    supersession[field] = tampered
    supersession_path.write_text(
        json.dumps(supersession, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    canonical_paths = [
        root / result["payload_path"],
        root / result["receipt_path"],
        root / "manifest.json",
        root / "research/latest.json",
    ]
    before = {path: path.read_bytes() for path in canonical_paths}
    with pytest.raises(ValueError):
        archive.replace(
            new,
            mode="LIVE",
            expected_sha256=_sha256(old),
            reason="VERIFIED_LATE_SOURCE_RECOVERY",
            source_provenance=provenance,
        )
    assert {path: path.read_bytes() for path in canonical_paths} == before


@pytest.mark.parametrize(
    ("field", "tampered"),
    [
        ("source_provenance", {"tampered": True}),
        ("reason", "TAMPERED_REASON"),
        ("previous_source_input_sha256", "0" * 64),
        ("previous_manifest_sha256", "1" * 64),
        ("previous_latest_pointer", {"tampered": True}),
        ("production_allowed", True),
        ("buy_gate_updated", True),
        ("orders_sent", True),
    ],
)
def test_generic_current_digest_retry_rejects_supersession_tamper(
    tmp_path: Path, field: str, tampered: object
) -> None:
    """A retry that knows only the committed digest still proves its preimage."""

    root = tmp_path / "data"
    slots = _seed_hourly(root)
    archive = ResearchArchiveStore(root)
    old = copy.deepcopy(slots["1000"])
    archive.publish(old, mode="LIVE")
    new = copy.deepcopy(old)
    new["source_input_sha256"] = "f" * 64
    provenance = {
        "source_path": "recovery/1000.json",
        "capture_origin": "LATE_RECOVERY",
    }
    result = archive.replace(
        new,
        mode="LIVE",
        expected_sha256=_sha256(old),
        reason="VERIFIED_LATE_SOURCE_RECOVERY",
        source_provenance=provenance,
    )
    supersession_path = root / result["supersession_receipt_path"]
    supersession = json.loads(supersession_path.read_text(encoding="utf-8"))
    supersession[field] = tampered
    supersession_path.write_text(
        json.dumps(supersession, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    canonical_paths = [
        root / result["payload_path"],
        root / result["receipt_path"],
        root / "manifest.json",
        root / "research/latest.json",
    ]
    before = {path: path.read_bytes() for path in canonical_paths}
    with pytest.raises(ValueError):
        archive.replace(
            new,
            mode="LIVE",
            expected_sha256=_sha256(new),
            reason="VERIFIED_LATE_SOURCE_RECOVERY",
            source_provenance=provenance,
        )
    assert {path: path.read_bytes() for path in canonical_paths} == before


def test_day_only_product_is_not_listed_until_generic_archive_exists(tmp_path: Path) -> None:
    root = tmp_path / "data"
    slots = _seed_hourly(root)
    archive = ResearchArchiveStore(root)

    materialized = materialize_research_day(
        root,
        DATE,
        stock_mentions_registry=FIXTURE_REGISTRY,
    )

    assert materialized["status"] == "READY_WITH_DECLARED_GAPS"
    assert archive.list_dates() == []
    assert archive.read_day_exact(DATE)["archive_date"] == DATE

    legacy = archive.publish(slots["1000"], mode="LIVE")
    assert archive.list_dates() == [DATE]
    assert archive.read_exact(DATE) == slots["1000"]
    assert legacy["payload_path"] == f"research/archives/{DATE}.json"


def test_day_namespace_rejects_tampered_payload_or_pointer(tmp_path: Path) -> None:
    root = tmp_path / "data"
    _seed_hourly(root)
    materialize_research_day(root, DATE, stock_mentions_registry=FIXTURE_REGISTRY)
    day_path = root / f"research/day/archives/{DATE}.json"
    tampered = json.loads(day_path.read_text(encoding="utf-8"))
    tampered["status"] = "READY"
    day_path.write_text(json.dumps(tampered, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="research day product manifest or receipt mismatch"):
        ResearchArchiveStore(root).read_day_exact(DATE)

    # Restore the canonical day artifact through a fresh fixture, then corrupt
    # only the day pointer. Generic latest remains independently readable.
    root2 = tmp_path / "data2"
    slots = _seed_hourly(root2)
    ResearchArchiveStore(root2).publish(slots["1000"], mode="LIVE")
    materialize_research_day(root2, DATE, stock_mentions_registry=FIXTURE_REGISTRY)
    pointer = root2 / "research/day/latest.json"
    pointer_payload = json.loads(pointer.read_text(encoding="utf-8"))
    pointer_payload["payload_sha256"] = "0" * 64
    pointer.write_text(json.dumps(pointer_payload), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid research day latest pointer"):
        ResearchArchiveStore(root2).read_day_latest()
    assert ResearchArchiveStore(root2).read_latest()["schema_version"] == "v3_5.research_archive.v1"


def test_stale_hourly_slot_fails_closed_without_day_publication(tmp_path: Path) -> None:
    root = tmp_path / "data"
    _seed_hourly(root)
    stale_path = root / f"research/hourly/live/{DATE}/1700.json"
    stale = json.loads(stale_path.read_text(encoding="utf-8"))
    stale["archive_date"] = "20260823"
    stale_path.write_text(json.dumps(stale, ensure_ascii=False), encoding="utf-8")

    result = materialize_research_day(root, DATE, stock_mentions_registry=FIXTURE_REGISTRY)

    assert result["status"] == "NOT_MATERIALIZED"
    assert "HOURLY_SLOT_INVALID:1700" in result["cannot_confirm"]
    assert ResearchArchiveStore(root).read_day_exact(DATE) is None
