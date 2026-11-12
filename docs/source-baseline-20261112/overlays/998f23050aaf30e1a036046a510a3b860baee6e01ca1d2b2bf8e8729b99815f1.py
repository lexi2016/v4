from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from domains.research import build_research_archive
from infrastructure.data_store import _sha256
from infrastructure.research_store import HourlyResearchStore, ResearchArchiveStore
from ops import run_hourly_research as hourly_runner
import ops.collect_hourly_research_input as hourly_input
from ops.collect_hourly_research_input import _atomic_json, build_hourly_research_input
from ops.run_hourly_research import run_hourly_research_file


def _source(title: str = "银行板块跟踪", *, slot: str = "1200") -> dict:
    return {
        "schema_version": "v3_research_lane.v2",
        "trade_date": "20260730",
        "source_manifest": {
            "generated_at": "2026-07-30T12:00:00+08:00",
            "hourly_slot": slot,
            "trade_date": "20260730",
            "source_receipts": ["research_module/hourly/20260730/1200.json"],
        },
        "stock_research_timeline": [
            {
                "stock_code": "000001",
                "stock_name": "平安银行",
                "event_time": "2026-07-30T11:59:00+08:00",
                "source_published_at": "2026-07-30T11:58:00+08:00",
                "first_seen_at": "2026-07-30T11:58:30+08:00",
                "last_checked_at": "2026-07-30T12:00:00+08:00",
                "source_type": "hourly_research",
                "source_name": "08:30早盘新闻",
                "source_title": title,
                "source_path": "research_module/hourly.json",
                "url": "https://example.test/a",
                "theme": "银行",
                "catalyst": "业绩",
                "evidence_sentence": "只读研究证据。",
                "evidence_level": "L2_MEDIUM",
                "confidence": "MEDIUM",
                "dedup_key": "source-a",
            }
        ],
        "stock_research_daily": [
            {
                "stock_code": "000001",
                "stock_name": "平安银行",
                "first_seen_time": "2026-07-30T11:58:30+08:00",
                "last_seen_time": "2026-07-30T12:00:00+08:00",
                "research_score": 88,
                "research_status": "REPEATED",
                "evidence_count": 1,
                "source_count": 1,
                "strong_evidence_count": 0,
                "medium_evidence_count": 1,
                "weak_evidence_count": 0,
                "source_types": ["hourly_research"],
                "themes": ["银行"],
                "top_catalysts": ["业绩"],
            }
        ],
        "research_pool_bridge": [
            {"stock_code": "000001", "formal_overlap": True, "stage_overlap": False}
        ],
        "cannot_confirm": [],
    }


def _write(path: Path, payload: dict) -> str:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _replace_kwargs(
    old_payload: dict,
    new_payload: dict,
    *,
    identity: str,
    data_root: Path,
    recovery_path: Path,
) -> dict:
    old_source = str(old_payload["source_input_sha256"])
    new_source = str(new_payload["source_input_sha256"])
    recovery_payload = json.loads(recovery_path.read_text(encoding="utf-8"))
    recovery_metadata = dict(recovery_payload["recovery_metadata"])
    return {
        "slot": "1200",
        "mode": "LIVE",
        "expected_sha256": "",
        "reason": "VERIFIED_LATE_SOURCE_RECOVERY",
        "transformer_identity_sha256": identity,
        "expected_source_sha256": old_source,
        "source_provenance": {
            "source_path": recovery_path.relative_to(data_root).as_posix(),
            "trade_date": "20260730",
            "slot": "1200",
            "source_input_sha256": new_source,
            "supersedes_source_sha256": old_source,
            "source_manifest": dict(recovery_payload["source_manifest"]),
            "recovery_metadata": recovery_metadata,
            "source_receipts": list(recovery_payload["source_receipts"]),
            "cannot_confirm": list(recovery_payload.get("cannot_confirm") or []),
            "original_source_path": recovery_metadata["original_source_path"],
            "original_source_sha256": recovery_metadata["original_source_sha256"],
            "repair_authorization": recovery_metadata.get("repair_authorization"),
            "capture_origin": "LATE_RECOVERY",
            "natural_execution_verified": False,
        },
        "natural_execution_verified": False,
    }


def _seed_pre_cutoff_recovery(tmp_path: Path, *, title: str = "explicit repair"):
    data_root = tmp_path / "data"
    canonical = data_root / "research/incoming/20260730/1200.json"
    canonical.parent.mkdir(parents=True)
    original = _source()
    original["source_manifest"]["pit_cutoff"] = "2026-07-30T12:00:59+08:00"
    _atomic_json(canonical, original)
    first = run_hourly_research_file(
        data_root=data_root,
        source=None,
        business_date="20260730",
        target_date="20260730",
        slot="1200",
        mode="LIVE",
    )
    old_bytes = canonical.read_bytes()
    old_source_sha = hashlib.sha256(old_bytes).hexdigest()
    changed = _source(title)
    changed["source_manifest"]["pit_cutoff"] = "2026-07-30T12:00:59+08:00"
    recovery = _atomic_json(
        canonical,
        changed,
        repair_expected_old_input_sha256=old_source_sha,
    )
    recovery_payload = json.loads(recovery.read_text(encoding="utf-8"))
    new_source_sha = hashlib.sha256(recovery.read_bytes()).hexdigest()
    new = build_research_archive(recovery_payload, source_input_sha256=new_source_sha)
    return data_root, canonical, first, old_bytes, old_source_sha, recovery, recovery_payload, new


def _rewrite_recovery_variant(recovery: Path, payload: dict) -> Path:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode(
        "utf-8"
    )
    digest = hashlib.sha256(encoded).hexdigest()
    variant = recovery.with_name(f"1200.recovery-{digest[:16]}.json")
    variant.write_bytes(encoded)
    return variant


def _collector_row() -> dict:
    return {
        "raw_id": "collector-raw-1",
        "trade_date": "20260730",
        "source_type": "zsxq",
        "source_name": "知识星球",
        "source_path": (
            "research_module/runtime_outputs/zsxq_hourly/20260730/1200/"
            "v35_zsxq_hourly_status_20260730_1200.json"
        ),
        "url": "https://wx.zsxq.com/dweb2/index/topic_detail/12345678901234567",
        "topic_id": "12345678901234567",
        "group_id": "research-group",
        "title": "银行板块跟踪",
        "raw_text": "平安银行，只读研究证据。" * 40,
        "published_at": "2026-07-30T11:59:00+08:00",
        "crawl_time": "2026-07-30T12:05:00+08:00",
        "source_published_at": "2026-07-30T11:59:00+08:00",
        "first_seen_at": "2026-07-30T12:05:00+08:00",
        "last_checked_at": "2026-07-30T12:05:00+08:00",
        "display_event_time": "2026-07-30T11:59:00+08:00",
        "is_new_since_last_slot": True,
        "is_recheck_duplicate": False,
        "source_evidence_level": "L3_STRONG",
        "source_confidence": "HIGH",
        "source_cannot_confirm": [],
        "themes": ["银行"],
        "mentioned_stock_candidates": ["平安银行", "000001"],
        "stock": "平安银行",
        "stock_code": "000001",
        "stock_name": "平安银行",
        "slot": "1200",
    }


def _seed_collector_canonical(tmp_path: Path) -> tuple[Path, Path, bytes, str]:
    data_root = tmp_path / "data"
    canonical = data_root / "research/incoming/20260730/1200.json"
    canonical.parent.mkdir(parents=True)
    original = _source("original collector input")
    original["source_manifest"]["pit_cutoff"] = "2026-07-30T12:00:59+08:00"
    _atomic_json(canonical, original)
    old_bytes = canonical.read_bytes()
    return data_root, canonical, old_bytes, hashlib.sha256(old_bytes).hexdigest()


def test_collector_repair_declares_complete_context_before_recovery_publication(
    tmp_path: Path, monkeypatch
) -> None:
    data_root, canonical, old_bytes, old_sha = _seed_collector_canonical(tmp_path)
    row = _collector_row()
    monkeypatch.setattr(
        hourly_input,
        "_zsxq_rows",
        lambda _data_root, _business_date, _slot: (
            [row],
            ["ZSXQ_RECOVERY_FETCHED_AFTER_SLOT"],
        ),
    )

    result = build_hourly_research_input(
        data_root=data_root,
        business_date="20260730",
        slot="1200",
        repair_expected_old_input_sha256=old_sha,
    )

    assert result["status"] == "READY_WITH_RESEARCH_POOL"
    assert result["recovery"] is True
    assert result["capture_origin"] == "LATE_RECOVERY"
    assert result["natural_execution_verified"] is False
    assert canonical.read_bytes() == old_bytes
    recovery_path = data_root / result["source_path"]
    recovery = json.loads(recovery_path.read_text(encoding="utf-8"))
    cutoff = "2026-07-30T12:00:59+08:00"
    assert recovery["trade_date"] == "20260730"
    assert recovery["slot"] == "1200"
    assert recovery["pit_cutoff"] == cutoff
    assert recovery["source_manifest"]["trade_date"] == "20260730"
    assert recovery["source_manifest"]["hourly_slot"] == "1200"
    assert recovery["source_manifest"]["pit_cutoff"] == cutoff
    assert recovery["source_manifest"]["source_receipts"] == [row["source_path"]]
    assert recovery["source_receipts"] == [row["source_path"]]
    assert recovery["original_source_sha256"] == old_sha
    assert recovery["supersedes"] == old_sha
    assert recovery["retry_of_sha256"] == old_sha
    assert recovery["capture_origin"] == "LATE_RECOVERY"
    assert recovery["original_time_capture"] is False
    assert recovery["natural_execution_verified"] is False


def test_collector_repair_keeps_nonempty_guard_for_empty_rows(
    tmp_path: Path, monkeypatch
) -> None:
    data_root, canonical, old_bytes, old_sha = _seed_collector_canonical(tmp_path)
    monkeypatch.setattr(
        hourly_input,
        "_zsxq_rows",
        lambda _data_root, _business_date, _slot: (
            [],
            ["ZSXQ_STATUS_NOT_AVAILABLE_BY_SLOT"],
        ),
    )

    with pytest.raises(ValueError, match="explicit repair requires non-empty rows"):
        build_hourly_research_input(
            data_root=data_root,
            business_date="20260730",
            slot="1200",
            repair_expected_old_input_sha256=old_sha,
        )

    assert canonical.read_bytes() == old_bytes
    assert not list(canonical.parent.glob("1200.recovery-*.json"))


def test_replace_preserves_preimage_and_is_idempotent(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    incoming = data_root / "research/incoming/20260730"
    incoming.mkdir(parents=True)
    canonical = incoming / "1200.json"
    _atomic_json(canonical, _source())
    first = run_hourly_research_file(
        data_root=data_root,
        source=None,
        business_date="20260730",
        target_date="20260730",
        slot="1200",
        mode="LIVE",
    )
    old = HourlyResearchStore(data_root).read_exact("20260730", "1200", mode="LIVE")
    assert old is not None
    changed = _source("修复后的实体证据")
    changed["cannot_confirm"] = [{"reason": "ZSXQ_RECOVERY_FETCHED_AFTER_SLOT"}]
    recovery_path = _atomic_json(canonical, changed)
    recovery_payload = json.loads(recovery_path.read_text(encoding="utf-8"))
    new_source_sha = hashlib.sha256(recovery_path.read_bytes()).hexdigest()
    new = build_research_archive(recovery_payload, source_input_sha256=new_source_sha)
    identity = hourly_runner._research_transformer_identity_sha256()
    args = _replace_kwargs(
        old,
        new,
        identity=identity,
        data_root=data_root,
        recovery_path=recovery_path,
    )
    args["expected_sha256"] = first["payload_sha256"]

    store = HourlyResearchStore(data_root)
    result = store.replace(new, **args)
    assert result["replaced"] is True
    assert result["natural_execution_verified"] is False
    assert store.read_latest() == new
    history_path = data_root / result["previous_payload_path"]
    history_receipt_path = data_root / result["previous_receipt_path"]
    assert json.loads(history_path.read_text(encoding="utf-8")) == old
    assert history_receipt_path.is_file()
    supersession = json.loads(
        (data_root / result["supersession_receipt_path"]).read_text(encoding="utf-8")
    )
    assert supersession["previous_payload_sha256"] == first["payload_sha256"]
    assert supersession["previous_source_input_sha256"] == old["source_input_sha256"]
    assert supersession["natural_execution_verified"] is False

    repeated = store.replace(new, **args)
    assert repeated["replaced"] is False
    assert repeated["payload_sha256"] == result["payload_sha256"]


def test_2100_recovery_resumes_after_hourly_only_commit(
    tmp_path: Path, monkeypatch
) -> None:
    data_root = tmp_path / "data"
    canonical = data_root / "research/incoming/20260730/2100.json"
    canonical.parent.mkdir(parents=True)
    original = _source("original 2100", slot="2100")
    _atomic_json(canonical, original)
    first = run_hourly_research_file(
        data_root=data_root,
        source=None,
        business_date="20260730",
        target_date="20260730",
        slot="2100",
        mode="LIVE",
    )
    hourly = HourlyResearchStore(data_root)
    archive = ResearchArchiveStore(data_root)
    old_hourly = hourly.read_exact("20260730", "2100", mode="LIVE")
    old_generic = archive.read_exact("20260730")
    assert old_hourly is not None
    assert old_generic == old_hourly

    recovery_source = _source("recovered 2100", slot="2100")
    recovery_source["cannot_confirm"] = [
        {"reason": "ZSXQ_RECOVERY_FETCHED_AFTER_SLOT"}
    ]
    recovery = _atomic_json(canonical, recovery_source)
    original_replace = ResearchArchiveStore.replace
    failure = {"pending": True}

    def fail_first_archive_replace(self, *args, **kwargs):
        if failure["pending"]:
            failure["pending"] = False
            raise OSError("injected generic archive publication failure")
        return original_replace(self, *args, **kwargs)

    monkeypatch.setattr(ResearchArchiveStore, "replace", fail_first_archive_replace)
    with pytest.raises(OSError, match="generic archive publication"):
        run_hourly_research_file(
            data_root=data_root,
            source=recovery,
            business_date="20260730",
            target_date="20260730",
            slot="2100",
            mode="LIVE",
        )
    monkeypatch.undo()

    partial_hourly = hourly.read_exact("20260730", "2100", mode="LIVE")
    partial_generic = archive.read_exact("20260730")
    assert partial_hourly is not None
    assert partial_generic == old_generic
    assert partial_hourly != old_hourly
    assert (data_root / HourlyResearchStore._history_relative(
        "20260730", "2100", "LIVE", first["payload_sha256"]
    )).read_bytes()

    resumed = run_hourly_research_file(
        data_root=data_root,
        source=recovery,
        business_date="20260730",
        target_date="20260730",
        slot="2100",
        mode="LIVE",
    )
    assert resumed["status"] == "SUCCEEDED"
    assert resumed["execution_origin"] == "LATE_RECOVERY"
    corrected_hourly = hourly.read_exact("20260730", "2100", mode="LIVE")
    corrected_generic = archive.read_exact("20260730")
    assert corrected_hourly is not None
    assert corrected_generic == corrected_hourly
    assert archive.read_latest() == corrected_generic
    assert hourly.read_latest() == corrected_hourly
    generic_history = data_root / ResearchArchiveStore._history_relative(
        "20260730", _sha256(old_generic)
    )
    generic_history_receipt = data_root / ResearchArchiveStore._history_receipt_relative(
        "20260730", _sha256(old_generic)
    )
    assert json.loads(generic_history.read_text(encoding="utf-8")) == old_generic
    assert generic_history_receipt.is_file()
    assert json.loads(
        (data_root / ResearchArchiveStore._supersession_relative(
            "20260730", _sha256(corrected_generic)
        )).read_text(encoding="utf-8")
    )["previous_payload_sha256"] == _sha256(old_generic)

    formal_before = {
        path.relative_to(data_root).as_posix(): path.read_bytes()
        for path in data_root.rglob("*")
        if path.is_file() and ".recovery-" not in path.name
    }
    repeated = run_hourly_research_file(
        data_root=data_root,
        source=recovery,
        business_date="20260730",
        target_date="20260730",
        slot="2100",
        mode="LIVE",
    )
    formal_after = {
        path.relative_to(data_root).as_posix(): path.read_bytes()
        for path in data_root.rglob("*")
        if path.is_file() and ".recovery-" not in path.name
    }
    assert repeated["status"] == "SUCCEEDED"
    assert repeated["exact_archive_latest_updated"] is False
    assert formal_after == formal_before


def test_hourly_current_digest_retry_rejects_unbound_later_latest_pointer(
    tmp_path: Path,
) -> None:
    """A structurally valid later pointer must still belong to the CAS preimage."""

    data_root = tmp_path / "data"
    old = build_research_archive(
        _source("old hourly evidence", slot="2100"),
        source_input_sha256="a" * 64,
    )
    new = build_research_archive(
        _source("new hourly evidence", slot="2100"),
        source_input_sha256="b" * 64,
    )
    store = HourlyResearchStore(data_root)
    store.publish(old, slot="2100", mode="LIVE")
    result = store.replace(
        new,
        slot="2100",
        mode="LIVE",
        expected_sha256=_sha256(old),
        reason="TEST_REPLACEMENT",
        source_provenance={"capture_origin": "TEST_REPLACEMENT"},
    )

    supersession_path = data_root / result["supersession_receipt_path"]
    supersession = json.loads(supersession_path.read_text(encoding="utf-8"))
    tampered_pointer = store._latest_pointer("20260731", "1000", "c" * 64)
    supersession["previous_latest_pointer"] = tampered_pointer
    supersession["previous_latest_pointer_sha256"] = _sha256(tampered_pointer)
    supersession_path.write_text(
        json.dumps(supersession, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    canonical_paths = [
        data_root / result["payload_path"],
        data_root / result["receipt_path"],
        data_root / "manifest.json",
        data_root / "research/hourly/latest.json",
    ]
    before = {path: path.read_bytes() for path in canonical_paths}

    with pytest.raises(ValueError, match="latest pointer"):
        store.replace(
            new,
            slot="2100",
            mode="LIVE",
            expected_sha256=_sha256(new),
            reason="TEST_REPLACEMENT",
            source_provenance={"capture_origin": "TEST_REPLACEMENT"},
        )

    assert {path: path.read_bytes() for path in canonical_paths} == before


def test_hourly_current_digest_retry_rejects_generic_bridge_provenance_tamper(
    tmp_path: Path, monkeypatch
) -> None:
    """Hourly continuation must validate the generic CAS supersession too."""

    data_root = tmp_path / "data"
    canonical = data_root / "research/incoming/20260730/2100.json"
    canonical.parent.mkdir(parents=True)
    _atomic_json(canonical, _source("original 2100", slot="2100"))
    run_hourly_research_file(
        data_root=data_root,
        source=None,
        business_date="20260730",
        target_date="20260730",
        slot="2100",
        mode="LIVE",
    )
    recovery_source = _source("recovered 2100", slot="2100")
    recovery_source["cannot_confirm"] = [
        {"reason": "ZSXQ_RECOVERY_FETCHED_AFTER_SLOT"}
    ]
    recovery = _atomic_json(canonical, recovery_source)
    original_replace = ResearchArchiveStore.replace
    failure = {"pending": True}

    def fail_first_archive_replace(self, *args, **kwargs):
        if failure["pending"]:
            failure["pending"] = False
            raise OSError("injected generic archive publication failure")
        return original_replace(self, *args, **kwargs)

    monkeypatch.setattr(ResearchArchiveStore, "replace", fail_first_archive_replace)
    with pytest.raises(OSError, match="generic archive publication"):
        run_hourly_research_file(
            data_root=data_root,
            source=recovery,
            business_date="20260730",
            target_date="20260730",
            slot="2100",
            mode="LIVE",
        )
    monkeypatch.undo()

    hourly = HourlyResearchStore(data_root)
    partial = hourly.read_exact("20260730", "2100", mode="LIVE")
    assert partial is not None
    resumed = run_hourly_research_file(
        data_root=data_root,
        source=recovery,
        business_date="20260730",
        target_date="20260730",
        slot="2100",
        mode="LIVE",
    )
    assert resumed["status"] == "SUCCEEDED"
    corrected = hourly.read_exact("20260730", "2100", mode="LIVE")
    assert corrected is not None
    generic_path = data_root / ResearchArchiveStore._supersession_relative(
        "20260730", _sha256(corrected)
    )
    generic_supersession = json.loads(generic_path.read_text(encoding="utf-8"))
    generic_supersession["source_provenance"] = {"tampered": True}
    generic_path.write_text(
        json.dumps(generic_supersession, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    before = {
        path.relative_to(data_root).as_posix(): path.read_bytes()
        for path in data_root.rglob("*")
        if path.is_file() and path != generic_path
    }

    with pytest.raises(ValueError, match="generic supersession bridge"):
        run_hourly_research_file(
            data_root=data_root,
            source=recovery,
            business_date="20260730",
            target_date="20260730",
            slot="2100",
            mode="LIVE",
        )

    after = {
        path.relative_to(data_root).as_posix(): path.read_bytes()
        for path in data_root.rglob("*")
        if path.is_file() and path != generic_path
    }
    assert after == before


def test_2100_recovery_keeps_later_hourly_slots_in_current_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    """A later LIVE slot may advance latest while the 2100 retry is pending."""

    data_root = tmp_path / "data"
    canonical = data_root / "research/incoming/20260730/2100.json"
    canonical.parent.mkdir(parents=True)
    _atomic_json(canonical, _source("original 2100", slot="2100"))
    run_hourly_research_file(
        data_root=data_root,
        source=None,
        business_date="20260730",
        target_date="20260730",
        slot="2100",
        mode="LIVE",
    )
    recovery_source = _source("recovered 2100", slot="2100")
    recovery_source["cannot_confirm"] = [
        {"reason": "ZSXQ_RECOVERY_FETCHED_AFTER_SLOT"}
    ]
    recovery = _atomic_json(canonical, recovery_source)
    original_replace = ResearchArchiveStore.replace
    failure = {"pending": True}

    def fail_first_archive_replace(self, *args, **kwargs):
        if failure["pending"]:
            failure["pending"] = False
            raise OSError("injected generic archive publication failure")
        return original_replace(self, *args, **kwargs)

    monkeypatch.setattr(ResearchArchiveStore, "replace", fail_first_archive_replace)
    with pytest.raises(OSError, match="generic archive publication"):
        run_hourly_research_file(
            data_root=data_root,
            source=recovery,
            business_date="20260730",
            target_date="20260730",
            slot="2100",
            mode="LIVE",
        )
    monkeypatch.undo()

    # Publish an actually later slot after the hourly CAS.  Its manifest and
    # latest entries must survive the retry while the pre-CAS hash is rebuilt.
    later_source = _source("later slot", slot="1000")
    later_source["trade_date"] = "20260731"
    later_source["source_manifest"]["trade_date"] = "20260731"
    later_source["source_manifest"]["hourly_slot"] = "1000"
    later = build_research_archive(later_source, source_input_sha256="c" * 64)
    hourly = HourlyResearchStore(data_root)
    hourly.publish(later, slot="1000", mode="LIVE")
    later_path = data_root / hourly._relative("20260731", "1000", "LIVE")
    later_bytes = later_path.read_bytes()

    resumed = run_hourly_research_file(
        data_root=data_root,
        source=recovery,
        business_date="20260730",
        target_date="20260730",
        slot="2100",
        mode="LIVE",
    )

    assert resumed["status"] == "SUCCEEDED"
    assert later_path.read_bytes() == later_bytes
    assert hourly.read_latest() == later


@pytest.mark.parametrize(
    ("field", "tampered"),
    [
        ("schema_version", "tampered.schema.v1"),
        ("source_input_sha256", "0" * 64),
        ("source_provenance", {"tampered": True}),
        ("reason", "TAMPERED_REASON"),
        ("previous_source_input_sha256", "0" * 64),
        ("previous_payload_path", "research/hourly/history/tampered.json"),
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
def test_2100_retry_rejects_hourly_supersession_lineage_tamper(
    tmp_path: Path, monkeypatch, field: str, tampered: object
) -> None:
    data_root = tmp_path / "data"
    canonical = data_root / "research/incoming/20260730/2100.json"
    canonical.parent.mkdir(parents=True)
    _atomic_json(canonical, _source("original 2100", slot="2100"))
    run_hourly_research_file(
        data_root=data_root,
        source=None,
        business_date="20260730",
        target_date="20260730",
        slot="2100",
        mode="LIVE",
    )
    recovery_source = _source("recovered 2100", slot="2100")
    recovery_source["cannot_confirm"] = [
        {"reason": "ZSXQ_RECOVERY_FETCHED_AFTER_SLOT"}
    ]
    recovery = _atomic_json(canonical, recovery_source)
    original_replace = ResearchArchiveStore.replace
    failure = {"pending": True}

    def fail_first_archive_replace(self, *args, **kwargs):
        if failure["pending"]:
            failure["pending"] = False
            raise OSError("injected generic archive publication failure")
        return original_replace(self, *args, **kwargs)

    monkeypatch.setattr(ResearchArchiveStore, "replace", fail_first_archive_replace)
    with pytest.raises(OSError, match="generic archive publication"):
        run_hourly_research_file(
            data_root=data_root,
            source=recovery,
            business_date="20260730",
            target_date="20260730",
            slot="2100",
            mode="LIVE",
        )
    monkeypatch.undo()

    hourly = HourlyResearchStore(data_root)
    partial = hourly.read_exact("20260730", "2100", mode="LIVE")
    assert partial is not None
    supersession_path = data_root / hourly._supersession_relative(
        "20260730", "2100", "LIVE", _sha256(partial)
    )
    supersession = json.loads(supersession_path.read_text(encoding="utf-8"))
    supersession[field] = tampered
    supersession_path.write_text(
        json.dumps(supersession, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    before = {
        path.relative_to(data_root).as_posix(): path.read_bytes()
        for path in data_root.rglob("*")
        if path.is_file()
        and path != supersession_path
        and ".recovery-" not in path.name
    }
    with pytest.raises(ValueError):
        run_hourly_research_file(
            data_root=data_root,
            source=recovery,
            business_date="20260730",
            target_date="20260730",
            slot="2100",
            mode="LIVE",
        )
    after = {
        path.relative_to(data_root).as_posix(): path.read_bytes()
        for path in data_root.rglob("*")
        if path.is_file()
        and path != supersession_path
        and ".recovery-" not in path.name
    }
    assert after == before


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
def test_hourly_current_digest_retry_rejects_supersession_tamper(
    tmp_path: Path, field: str, tampered: object
) -> None:
    """A direct hourly retry with the committed digest must prove its preimage."""

    data_root = tmp_path / "data"
    old = build_research_archive(
        _source("old hourly evidence"),
        source_input_sha256="a" * 64,
    )
    new = build_research_archive(
        _source("new hourly evidence"),
        source_input_sha256="b" * 64,
    )
    store = HourlyResearchStore(data_root)
    store.publish(old, slot="1200", mode="LIVE")
    provenance = {"capture_origin": "TEST_REPLACEMENT"}
    result = store.replace(
        new,
        slot="1200",
        mode="LIVE",
        expected_sha256=_sha256(old),
        reason="TEST_REPLACEMENT",
        source_provenance=provenance,
    )
    supersession_path = data_root / result["supersession_receipt_path"]
    supersession = json.loads(supersession_path.read_text(encoding="utf-8"))
    supersession[field] = tampered
    supersession_path.write_text(
        json.dumps(supersession, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    canonical_paths = [
        data_root / result["payload_path"],
        data_root / result["receipt_path"],
        data_root / "manifest.json",
        data_root / "research/hourly/latest.json",
    ]
    before = {path: path.read_bytes() for path in canonical_paths}
    with pytest.raises(ValueError):
        store.replace(
            new,
            slot="1200",
            mode="LIVE",
            expected_sha256=_sha256(new),
            reason="TEST_REPLACEMENT",
            source_provenance=provenance,
        )
    assert {path: path.read_bytes() for path in canonical_paths} == before


def test_recovery_optional_cannot_confirm_absence_is_preserved_for_direct_cas(
    tmp_path: Path,
) -> None:
    (
        data_root,
        _canonical,
        first,
        _old_bytes,
        _old_source_sha,
        recovery,
        recovery_payload,
        _new,
    ) = _seed_pre_cutoff_recovery(tmp_path, title="optional absent")
    recovery_payload.pop("cannot_confirm")
    variant = _rewrite_recovery_variant(recovery, recovery_payload)
    new_source_sha = hashlib.sha256(variant.read_bytes()).hexdigest()
    new = build_research_archive(recovery_payload, source_input_sha256=new_source_sha)
    old = HourlyResearchStore(data_root).read_exact("20260730", "1200", mode="LIVE")
    assert old is not None
    args = _replace_kwargs(
        old,
        new,
        identity=hourly_runner._research_transformer_identity_sha256(),
        data_root=data_root,
        recovery_path=variant,
    )
    args["expected_sha256"] = first["payload_sha256"]
    args["source_provenance"].pop("cannot_confirm")
    result = HourlyResearchStore(data_root).replace(new, **args)
    assert result["replaced"] is True


def test_recovery_optional_cannot_confirm_explicit_null_is_preserved_for_direct_cas(
    tmp_path: Path,
) -> None:
    (
        data_root,
        _canonical,
        first,
        _old_bytes,
        _old_source_sha,
        recovery,
        recovery_payload,
        _new,
    ) = _seed_pre_cutoff_recovery(tmp_path, title="optional null")
    recovery_payload["cannot_confirm"] = None
    variant = _rewrite_recovery_variant(recovery, recovery_payload)
    new_source_sha = hashlib.sha256(variant.read_bytes()).hexdigest()
    new = build_research_archive(recovery_payload, source_input_sha256=new_source_sha)
    old = HourlyResearchStore(data_root).read_exact("20260730", "1200", mode="LIVE")
    assert old is not None
    args = _replace_kwargs(
        old,
        new,
        identity=hourly_runner._research_transformer_identity_sha256(),
        data_root=data_root,
        recovery_path=variant,
    )
    args["expected_sha256"] = first["payload_sha256"]
    args["source_provenance"]["cannot_confirm"] = None
    result = HourlyResearchStore(data_root).replace(new, **args)
    assert result["replaced"] is True
    supersession = json.loads(
        (data_root / result["supersession_receipt_path"]).read_text(encoding="utf-8")
    )
    assert supersession["source_provenance"]["cannot_confirm"] is None


def test_runner_optional_cannot_confirm_absence_is_preserved_before_store_cas(
    tmp_path: Path,
) -> None:
    (
        data_root,
        _canonical,
        _first,
        _old_bytes,
        _old_source_sha,
        recovery,
        recovery_payload,
        _new,
    ) = _seed_pre_cutoff_recovery(tmp_path, title="runner optional absent")
    recovery_payload.pop("cannot_confirm")
    variant = _rewrite_recovery_variant(recovery, recovery_payload)
    result = run_hourly_research_file(
        data_root=data_root,
        source=variant,
        business_date="20260730",
        target_date="20260730",
        slot="1200",
        mode="LIVE",
    )
    assert result["status"] == "SUCCEEDED"
    assert result["execution_origin"] == "LATE_RECOVERY"


def test_direct_store_recovery_rejects_original_time_capture_mismatch_before_cas(
    tmp_path: Path,
) -> None:
    (
        data_root,
        _canonical,
        first,
        _old_bytes,
        _old_source_sha,
        recovery,
        _recovery_payload,
        new,
    ) = _seed_pre_cutoff_recovery(tmp_path, title="mismatched original time")
    old = HourlyResearchStore(data_root).read_exact("20260730", "1200", mode="LIVE")
    assert old is not None
    args = _replace_kwargs(
        old,
        new,
        identity=hourly_runner._research_transformer_identity_sha256(),
        data_root=data_root,
        recovery_path=recovery,
    )
    args["expected_sha256"] = first["payload_sha256"]
    args["source_provenance"]["original_time_capture"] = True
    formal_before = {
        path.relative_to(data_root).as_posix(): path.read_bytes()
        for path in data_root.rglob("*")
        if path.is_file() and ".recovery-" not in path.name
    }
    with pytest.raises(ValueError, match="recovery provenance"):
        HourlyResearchStore(data_root).replace(new, **args)
    formal_after = {
        path.relative_to(data_root).as_posix(): path.read_bytes()
        for path in data_root.rglob("*")
        if path.is_file() and ".recovery-" not in path.name
    }
    assert formal_after == formal_before


def test_explicit_nonempty_pre_cutoff_recovery_requires_exact_old_sha(
    tmp_path: Path,
) -> None:
    (
        data_root,
        canonical,
        first,
        old_bytes,
        old_source_sha,
        recovery,
        recovery_payload,
        new,
    ) = _seed_pre_cutoff_recovery(tmp_path)
    assert recovery_payload["recovery"] is True
    assert recovery_payload["source_path"] == canonical.resolve().as_posix()
    assert recovery_payload["original_source_path"] == canonical.resolve().as_posix()
    assert recovery_payload["original_source_sha256"] == old_source_sha
    assert recovery_payload["supersedes"] == old_source_sha
    assert recovery_payload["retry_of_sha256"] == old_source_sha
    assert recovery_payload["capture_origin"] == "LATE_RECOVERY"
    assert recovery_payload["original_time_capture"] is False
    assert recovery_payload["natural_execution_verified"] is False
    assert recovery_payload["source_manifest"]["capture_origin"] == "LATE_RECOVERY"
    assert recovery_payload["source_manifest"]["original_time_capture"] is False
    assert recovery_payload["source_manifest"]["natural_execution_verified"] is False
    assert recovery_payload["recovery_metadata"]["repair_authorization"][
        "expected_old_input_sha256"
    ] == old_source_sha
    assert recovery_payload["recovery_metadata"]["natural_execution_verified"] is False
    assert canonical.read_bytes() == old_bytes

    wrong = _source("wrong authorization")
    wrong["source_manifest"]["pit_cutoff"] = "2026-07-30T12:00:59+08:00"
    before_names = sorted(path.name for path in canonical.parent.iterdir())
    with pytest.raises(ValueError, match="expected old input SHA"):
        _atomic_json(
            canonical,
            wrong,
            repair_expected_old_input_sha256="f" * 64,
        )
    assert canonical.read_bytes() == old_bytes
    assert sorted(path.name for path in canonical.parent.iterdir()) == before_names

    result = run_hourly_research_file(
        data_root=data_root,
        source=recovery,
        business_date="20260730",
        target_date="20260730",
        slot="1200",
        mode="LIVE",
    )
    assert result["status"] == "SUCCEEDED"
    assert result["execution_origin"] == "LATE_RECOVERY"
    assert result["natural_execution_verified"] is False
    assert result["payload_sha256"] != first["payload_sha256"]
    assert canonical.read_bytes() == old_bytes


@pytest.mark.parametrize(
    "field, value",
    [
        ("original_source_path", None),
        ("original_source_sha256", "f" * 64),
        ("source_receipts", "wrong-type"),
        ("capture_origin", "ORIGINAL_SLOT"),
        ("original_time_capture", True),
        ("trade_date", None),
        ("slot", None),
        ("pit_cutoff", None),
        ("natural_execution_verified", None),
    ],
)
def test_recovery_provenance_removal_or_wrong_types_fails_before_formal_mutation(
    tmp_path: Path, field: str, value,
) -> None:
    (
        data_root,
        canonical,
        _first,
        old_bytes,
        _old_source_sha,
        recovery,
        recovery_payload,
        new,
    ) = _seed_pre_cutoff_recovery(tmp_path)
    formal_before = {
        path.relative_to(data_root).as_posix(): path.read_bytes()
        for path in data_root.rglob("*")
        if path.is_file() and ".recovery-" not in path.name
    }
    mutated = json.loads(json.dumps(recovery_payload))
    if field == "source_receipts":
        mutated["source_manifest"]["source_receipts"] = value
        mutated["source_receipts"] = value
        mutated["recovery_metadata"]["source_receipts"] = value
    elif field in {"trade_date", "slot", "pit_cutoff", "natural_execution_verified"}:
        mutated.pop(field, None)
        if value is not None:
            mutated[field] = value
    else:
        mutated["recovery_metadata"].pop(field, None)
        if value is not None:
            mutated["recovery_metadata"][field] = value
    variant = _rewrite_recovery_variant(recovery, mutated)
    with pytest.raises(ValueError, match="recovery (provenance|original_source_path)"):
        run_hourly_research_file(
            data_root=data_root,
            source=variant,
            business_date="20260730",
            target_date="20260730",
            slot="1200",
            mode="LIVE",
        )
    assert canonical.read_bytes() == old_bytes
    formal_after = {
        path.relative_to(data_root).as_posix(): path.read_bytes()
        for path in data_root.rglob("*")
        if path.is_file() and ".recovery-" not in path.name
    }
    assert formal_after == formal_before


def test_replace_stale_cas_fails_without_losing_canonical_bytes(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    incoming = data_root / "research/incoming/20260730"
    incoming.mkdir(parents=True)
    canonical = incoming / "1200.json"
    _atomic_json(canonical, _source())
    first = run_hourly_research_file(
        data_root=data_root,
        source=None,
        business_date="20260730",
        target_date="20260730",
        slot="1200",
        mode="LIVE",
    )
    changed = _source("stale CAS")
    changed["cannot_confirm"] = [{"reason": "ZSXQ_RECOVERY_FETCHED_AFTER_SLOT"}]
    recovery_path = _atomic_json(canonical, changed)
    recovery_payload = json.loads(recovery_path.read_text(encoding="utf-8"))
    new_source_sha = hashlib.sha256(recovery_path.read_bytes()).hexdigest()
    new = build_research_archive(recovery_payload, source_input_sha256=new_source_sha)
    store = HourlyResearchStore(data_root)
    payload_path = data_root / first["payload_path"]
    receipt_path = data_root / first["receipt_path"]
    manifest_path = data_root / "manifest.json"
    latest_path = data_root / "research/hourly/latest.json"
    before = {
        "payload": payload_path.read_bytes(),
        "receipt": receipt_path.read_bytes(),
        "manifest": manifest_path.read_bytes(),
        "latest": latest_path.read_bytes(),
    }
    args = _replace_kwargs(
        HourlyResearchStore(data_root).read_exact("20260730", "1200", mode="LIVE"),
        new,
        identity=hourly_runner._research_transformer_identity_sha256(),
        data_root=data_root,
        recovery_path=recovery_path,
    )
    args["expected_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="expected SHA"):
        store.replace(new, **args)
    assert payload_path.read_bytes() == before["payload"]
    assert receipt_path.read_bytes() == before["receipt"]
    assert manifest_path.read_bytes() == before["manifest"]
    assert latest_path.read_bytes() == before["latest"]


def test_direct_store_recovery_requires_complete_provenance_before_cas(
    tmp_path: Path,
) -> None:
    (
        data_root,
        _canonical,
        first,
        _old_bytes,
        _old_source_sha,
        recovery,
        _recovery_payload,
        new,
    ) = _seed_pre_cutoff_recovery(tmp_path, title="direct store")
    old = HourlyResearchStore(data_root).read_exact("20260730", "1200", mode="LIVE")
    assert old is not None
    args = _replace_kwargs(
        old,
        new,
        identity=hourly_runner._research_transformer_identity_sha256(),
        data_root=data_root,
        recovery_path=recovery,
    )
    args["expected_sha256"] = first["payload_sha256"]
    args["source_provenance"]["recovery_metadata"].pop("original_source_path")
    formal_before = {
        path.relative_to(data_root).as_posix(): path.read_bytes()
        for path in data_root.rglob("*")
        if path.is_file() and ".recovery-" not in path.name
    }
    with pytest.raises(ValueError, match="recovery (provenance|original_source_path)"):
        HourlyResearchStore(data_root).replace(new, **args)
    formal_after = {
        path.relative_to(data_root).as_posix(): path.read_bytes()
        for path in data_root.rglob("*")
        if path.is_file() and ".recovery-" not in path.name
    }
    assert formal_after == formal_before


def test_direct_store_recovery_rejects_structured_provenance_mismatch_before_cas(
    tmp_path: Path,
) -> None:
    (
        data_root,
        _canonical,
        first,
        _old_bytes,
        _old_source_sha,
        recovery,
        _recovery_payload,
        new,
    ) = _seed_pre_cutoff_recovery(tmp_path, title="fabricated structured receipt")
    old = HourlyResearchStore(data_root).read_exact("20260730", "1200", mode="LIVE")
    assert old is not None
    args = _replace_kwargs(
        old,
        new,
        identity=hourly_runner._research_transformer_identity_sha256(),
        data_root=data_root,
        recovery_path=recovery,
    )
    args["expected_sha256"] = first["payload_sha256"]
    fabricated_receipts = ["fabricated/receipt.json"]
    args["source_provenance"]["source_manifest"]["source_receipts"] = fabricated_receipts
    args["source_provenance"]["source_receipts"] = fabricated_receipts
    formal_before = {
        path.relative_to(data_root).as_posix(): path.read_bytes()
        for path in data_root.rglob("*")
        if path.is_file() and ".recovery-" not in path.name
    }
    with pytest.raises(ValueError, match="structured provenance mismatch"):
        HourlyResearchStore(data_root).replace(new, **args)
    formal_after = {
        path.relative_to(data_root).as_posix(): path.read_bytes()
        for path in data_root.rglob("*")
        if path.is_file() and ".recovery-" not in path.name
    }
    assert formal_after == formal_before


def test_direct_store_pre_cutoff_recovery_requires_explicit_authorization(
    tmp_path: Path,
) -> None:
    (
        data_root,
        _canonical,
        first,
        _old_bytes,
        _old_source_sha,
        _recovery,
        _recovery_payload,
        new,
    ) = _seed_pre_cutoff_recovery(tmp_path, title="missing direct authorization")
    old = HourlyResearchStore(data_root).read_exact("20260730", "1200", mode="LIVE")
    assert old is not None
    args = _replace_kwargs(
        old,
        new,
        identity=hourly_runner._research_transformer_identity_sha256(),
        data_root=data_root,
        recovery_path=_recovery,
    )
    args["expected_sha256"] = first["payload_sha256"]
    args["source_provenance"]["recovery_metadata"].pop("repair_authorization")
    args["source_provenance"].pop("repair_authorization")
    formal_before = {
        path.relative_to(data_root).as_posix(): path.read_bytes()
        for path in data_root.rglob("*")
        if path.is_file() and ".recovery-" not in path.name
    }
    with pytest.raises(ValueError, match="structured provenance mismatch"):
        HourlyResearchStore(data_root).replace(new, **args)
    formal_after = {
        path.relative_to(data_root).as_posix(): path.read_bytes()
        for path in data_root.rglob("*")
        if path.is_file() and ".recovery-" not in path.name
    }
    assert formal_after == formal_before


def test_direct_store_recovery_sha_is_bound_to_file_bytes(tmp_path: Path) -> None:
    (
        data_root,
        _canonical,
        first,
        _old_bytes,
        _old_source_sha,
        recovery,
        _recovery_payload,
        new,
    ) = _seed_pre_cutoff_recovery(tmp_path, title="wrong recovery bytes SHA")
    old = HourlyResearchStore(data_root).read_exact("20260730", "1200", mode="LIVE")
    assert old is not None
    args = _replace_kwargs(
        old,
        new,
        identity=hourly_runner._research_transformer_identity_sha256(),
        data_root=data_root,
        recovery_path=recovery,
    )
    args["expected_sha256"] = first["payload_sha256"]
    actual = args["source_provenance"]["source_input_sha256"]
    claimed = actual[:16] + ("0" if actual[16] != "0" else "1") + actual[17:]
    args["source_provenance"]["source_input_sha256"] = claimed
    new["source_input_sha256"] = claimed
    formal_before = {
        path.relative_to(data_root).as_posix(): path.read_bytes()
        for path in data_root.rglob("*")
        if path.is_file() and ".recovery-" not in path.name
    }
    with pytest.raises(ValueError, match="source bytes SHA"):
        HourlyResearchStore(data_root).replace(new, **args)
    formal_after = {
        path.relative_to(data_root).as_posix(): path.read_bytes()
        for path in data_root.rglob("*")
        if path.is_file() and ".recovery-" not in path.name
    }
    assert formal_after == formal_before


def test_collector_rejects_conflicting_nested_source_date_before_recovery_write(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    canonical = data_root / "research/incoming/20260730/1200.json"
    canonical.parent.mkdir(parents=True)
    _atomic_json(canonical, _source())
    old_bytes = canonical.read_bytes()
    old_sha = hashlib.sha256(old_bytes).hexdigest()
    changed = _source("conflicting nested date")
    changed["source_manifest"]["trade_date"] = "20260729"
    before_names = sorted(path.name for path in canonical.parent.iterdir())
    with pytest.raises(ValueError, match="date mismatched"):
        _atomic_json(
            canonical,
            changed,
            repair_expected_old_input_sha256=old_sha,
        )
    assert canonical.read_bytes() == old_bytes
    assert sorted(path.name for path in canonical.parent.iterdir()) == before_names


def test_nonempty_recovery_rejects_empty_source_receipts_before_formal_mutation(
    tmp_path: Path,
) -> None:
    (
        data_root,
        canonical,
        _first,
        old_bytes,
        _old_source_sha,
        recovery,
        recovery_payload,
        _new,
    ) = _seed_pre_cutoff_recovery(tmp_path, title="empty receipts")
    mutated = json.loads(json.dumps(recovery_payload))
    mutated["source_manifest"]["source_receipts"] = []
    mutated["source_receipts"] = []
    mutated["recovery_metadata"]["source_receipts"] = []
    variant = _rewrite_recovery_variant(recovery, mutated)
    formal_before = {
        path.relative_to(data_root).as_posix(): path.read_bytes()
        for path in data_root.rglob("*")
        if path.is_file() and ".recovery-" not in path.name
    }
    with pytest.raises(ValueError, match="recovery (provenance|source receipts)"):
        run_hourly_research_file(
            data_root=data_root,
            source=variant,
            business_date="20260730",
            target_date="20260730",
            slot="1200",
            mode="LIVE",
        )
    assert canonical.read_bytes() == old_bytes
    formal_after = {
        path.relative_to(data_root).as_posix(): path.read_bytes()
        for path in data_root.rglob("*")
        if path.is_file() and ".recovery-" not in path.name
    }
    assert formal_after == formal_before


def test_replace_interruption_restores_canonical_state(tmp_path: Path, monkeypatch) -> None:
    data_root = tmp_path / "data"
    incoming = data_root / "research/incoming/20260730"
    incoming.mkdir(parents=True)
    canonical = incoming / "1200.json"
    _atomic_json(canonical, _source())
    first = run_hourly_research_file(
        data_root=data_root,
        source=None,
        business_date="20260730",
        target_date="20260730",
        slot="1200",
        mode="LIVE",
    )
    old = HourlyResearchStore(data_root).read_exact("20260730", "1200", mode="LIVE")
    assert old is not None
    changed = _source("interrupted repair")
    changed["cannot_confirm"] = [{"reason": "ZSXQ_RECOVERY_FETCHED_AFTER_SLOT"}]
    recovery_path = _atomic_json(canonical, changed)
    recovery_payload = json.loads(recovery_path.read_text(encoding="utf-8"))
    new_source_sha = hashlib.sha256(recovery_path.read_bytes()).hexdigest()
    new = build_research_archive(recovery_payload, source_input_sha256=new_source_sha)
    store = HourlyResearchStore(data_root)
    payload_path = data_root / first["payload_path"]
    receipt_path = data_root / first["receipt_path"]
    before_payload = payload_path.read_bytes()
    before_receipt = receipt_path.read_bytes()
    original_write = HourlyResearchStore._write

    def fail_receipt(self, relative, value):
        if relative == first["receipt_path"]:
            raise OSError("injected replacement receipt failure")
        return original_write(self, relative, value)

    monkeypatch.setattr(HourlyResearchStore, "_write", fail_receipt)
    args = _replace_kwargs(
        old,
        new,
        identity=hourly_runner._research_transformer_identity_sha256(),
        data_root=data_root,
        recovery_path=recovery_path,
    )
    args["expected_sha256"] = first["payload_sha256"]
    with pytest.raises(OSError, match="replacement receipt"):
        store.replace(new, **args)
    assert payload_path.read_bytes() == before_payload
    assert receipt_path.read_bytes() == before_receipt
    assert store.read_exact("20260730", "1200", mode="LIVE") == old


def test_late_recovery_keeps_cutoff_and_never_claims_natural_execution(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    incoming = data_root / "research/incoming/20260730"
    incoming.mkdir(parents=True)
    canonical = incoming / "1200.json"
    _atomic_json(canonical, _source())
    first = run_hourly_research_file(
        data_root=data_root,
        source=None,
        business_date="20260730",
        target_date="20260730",
        slot="1200",
        mode="LIVE",
    )
    late = _source("late source")
    late["cannot_confirm"] = [{"reason": "ZSXQ_RECOVERY_FETCHED_AFTER_SLOT"}]
    late["source_manifest"]["generated_at"] = "2026-07-30T12:05:00+08:00"
    late["source_manifest"]["published_at"] = "2026-07-30T12:05:00+08:00"
    for field in ("first_seen_at", "last_checked_at"):
        late["stock_research_timeline"][0][field] = "2026-07-30T12:05:00+08:00"
    for field in ("first_seen_time", "last_seen_time"):
        late["stock_research_daily"][0][field] = "2026-07-30T12:05:00+08:00"
    recovery = _atomic_json(canonical, late)
    result = run_hourly_research_file(
        data_root=data_root,
        source=recovery,
        business_date="20260730",
        target_date="20260730",
        slot="1200",
        mode="LIVE",
    )
    assert result["status"] == "SUCCEEDED"
    assert result["execution_origin"] == "LATE_RECOVERY"
    assert result["natural_execution_verified"] is False
    assert result["latest_updated"] is True
    assert HourlyResearchStore(data_root).read_latest()["articles"][0]["source_title"] == "late source"
    recovery_payload = json.loads(recovery.read_text(encoding="utf-8"))
    assert recovery_payload["source_manifest"]["pit_cutoff"] == "2026-07-30T12:00:59+08:00"
    assert recovery_payload["source_manifest"]["capture_origin"] == "LATE_RECOVERY"
    assert recovery_payload["recovery_metadata"]["original_time_capture"] is False
    assert first["payload_sha256"] != result["payload_sha256"]


def test_late_recovery_wrong_old_source_fails_closed(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    incoming = data_root / "research/incoming/20260730"
    incoming.mkdir(parents=True)
    canonical = incoming / "1200.json"
    _atomic_json(canonical, _source())
    run_hourly_research_file(
        data_root=data_root,
        source=None,
        business_date="20260730",
        target_date="20260730",
        slot="1200",
        mode="LIVE",
    )
    late = _source("wrong old source")
    late["cannot_confirm"] = [{"reason": "ZSXQ_RECOVERY_FETCHED_AFTER_SLOT"}]
    late["source_manifest"]["generated_at"] = "2026-07-30T12:05:00+08:00"
    late["source_manifest"]["published_at"] = "2026-07-30T12:05:00+08:00"
    recovery = _atomic_json(canonical, late)
    recovery_payload = json.loads(recovery.read_text(encoding="utf-8"))
    recovery_payload["supersedes"] = "f" * 64
    recovery.write_text(json.dumps(recovery_payload), encoding="utf-8")
    before = (data_root / "research/hourly/live/20260730/1200.json").read_bytes()
    with pytest.raises(ValueError, match="recovery provenance|source mismatch"):
        run_hourly_research_file(
            data_root=data_root,
            source=recovery,
            business_date="20260730",
            target_date="20260730",
            slot="1200",
            mode="LIVE",
        )
    assert (data_root / "research/hourly/live/20260730/1200.json").read_bytes() == before
