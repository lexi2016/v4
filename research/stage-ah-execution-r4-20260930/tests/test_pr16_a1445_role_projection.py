"""Synthetic structural sources: real archive builder, bound reader and store.

4/27 warning lists reproduce evidence shapes, NOT the original 506c/4076
source bytes or the 811b archive. No Stage, provider, or market-data calls.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path

import pytest
from domains.research import build_research_archive
from infrastructure.data_store import _canonical_bytes, _sha256
from infrastructure.research_store import HourlyResearchStore
from stage_center import research_context as rc

IDENTITY = {
    "producer": "ops.collect_hourly_research_input",
    "module_path": "v3.5/domains/research_hourly",
    "producer_oracle_sha256": "850fffdf16b7c0127852cbe9cc374aed353e8d7cb1c2ba73d2eff880c95d022e",
    "collector_identity_sha256": "66b941f5a066250c4fd9830170302b8b1f7041760a37c6e4bf02ea222aa307ab",
    "research_hourly_domain_identity_sha256": "6c67bec8d162ed47d8ebc20ce9ae8da2b8e520399260165cc0bb992baa9c8e22",
    "report_subject_policy_sha256": "0308fe6172e96b32e2ad0c2baa1187247e046d70c55134b329087e77a2297351",
}
OLD = ["002202", "600346", "600875", "601918"]
NEW = ["000166", "000402", "000728", "000750", "000783", "002670", "002736",
       "300059", "600109", "600369", "600909", "600918", "600958", "600999",
       "601066", "601099", "601108", "601162", "601375", "601377", "601555",
       "601688", "601696", "601788", "601878", "601995", "603337"]
PREFIX = "REPORT_ROLE_EVIDENCE_EXCLUDED:"


def fixture_source(date="20260930", codes=None):
    codes = list(NEW if codes is None else codes)
    iso = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    observed = f"{iso}T14:12:03+08:00" if date == "20260930" else f"{iso}T14:00:03+08:00"
    manifest = {**IDENTITY, "trade_date": date, "hourly_slot": "1400",
        "generated_at": observed, "published_at": observed,
        "version": "SYNTHETIC-STRUCTURE-NOT-HISTORICAL-BYTES",
        "pit_cutoff": f"{iso}T14:00:59+08:00",
        "capture_origin": "LATE_RECOVERY" if date == "20260930" else "ORIGINAL_SLOT",
        "original_time_capture": date != "20260930", "natural_execution_verified": False}
    return {"schema_version": "v3_research_lane.v2", "trade_date": date, "slot": "1400",
        "source_manifest": manifest, "cannot_confirm": [f"SYNTHETIC_GAP:{i}" for i in range(88)],
        "report_entity_audit": {"policy_version": "report_subject_scoring.v1",
            "affected_codes": codes,
            "excluded_evidence": [{"stock_code": c, "research_subject_eligible": False} for c in codes]},
        "research_items": [], "research_pool_bridge": [],
        "stock_research_timeline": [{"stock_code": f"{600000+i%47:06d}", "stock_name": "SYNTHETIC",
            "event_time": f"{iso}T13:00:00+08:00", "source_published_at": f"{iso}T13:00:00+08:00",
            "first_seen_at": observed, "last_checked_at": observed,
            "source_type": "research_db", "source_name": "SYNTHETIC", "source_title": f"SYNTHETIC {i}",
            "source_path": f"synthetic/{i}.json"} for i in range(97)],
        "stock_research_daily": [{"stock_code": f"{600000+i:06d}", "stock_name": "SYNTHETIC",
            "first_seen_time": observed, "last_seen_time": observed, "research_score": i} for i in range(47)]}


def seal(root, source, mutate_archive=None):
    raw = json.dumps(source, ensure_ascii=False, indent=2).encode()
    digest = hashlib.sha256(raw).hexdigest()
    source_path = root / "research/hourly/source" / f"{digest}.json"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_bytes(raw)
    payload = build_research_archive(source, source_input_sha256=digest)
    # The archived policy output is sorted; a shuffled SOURCE audit must not
    # be repaired by sorting it in the consumer.
    payload["cannot_confirm"] += [PREFIX + c for c in sorted(source["report_entity_audit"]["affected_codes"])]
    # Only temporary synthetic storage is published, never source/market roots.
    store = HourlyResearchStore(root)
    store.publish(payload, slot="1400", mode="LIVE")
    if mutate_archive:
        mutate_archive(payload)
        # Re-seal synthetic corruption so the reader, not fixture publication,
        # exercises schema/ordered-projection rejection.
        rel = store._relative(source["trade_date"], "1400", "LIVE")
        receipt_path = root / store._receipt_relative(source["trade_date"], "1400", "LIVE")
        receipt = json.loads(receipt_path.read_bytes()); receipt["payload_sha256"] = _sha256(payload)
        manifest = json.loads((root/"manifest.json").read_bytes()); manifest[rel] = _sha256(payload)
        (root/rel).write_bytes(_canonical_bytes(payload))
        receipt_path.write_bytes(_canonical_bytes(receipt))
        (root/"manifest.json").write_bytes(_canonical_bytes(manifest))
    return payload, source_path


def read_bound(root, date="20260930"):
    cutoff = datetime.fromisoformat(f"{date[:4]}-{date[4:6]}-{date[6:]}T15:00:00+08:00")
    slot, payload, paths = rc._verified_hourly_slot(root, trade_date=date, cutoff=cutoff)
    rows, evidence = rc._bound_source_rows(root, payload=payload, paths=paths,
                                         trade_date=date, slot=slot, cutoff=cutoff)
    return rows, evidence, payload, paths


def hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("date,codes", [("20260929", OLD), ("20260930", NEW)])
def test_old_four_and_new_27_are_derived_from_source_not_pinned_date(tmp_path, date, codes):
    source = fixture_source(date, codes)
    payload, _ = seal(tmp_path, source)
    before = hashes(tmp_path)
    rows, evidence, actual, paths = read_bound(tmp_path, date)
    assert rows is not None and actual == payload
    assert actual["cannot_confirm"] == ["LEGACY_SOURCE_CANNOT_CONFIRM_COUNT:88"] + [PREFIX+c for c in codes]
    assert actual["article_count"] == 97 and actual["stock_pool_count"] == 47
    assert all(actual[k] is False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))
    assert paths["actual_source_generated_at"] == source["source_manifest"]["generated_at"]
    assert hashes(tmp_path) == before
    # No conversion of LATE_RECOVERY into ORIGINAL_SLOT; source remains byte-bound.
    assert source["source_manifest"]["capture_origin"] == ("LATE_RECOVERY" if date == "20260930" else "ORIGINAL_SLOT")


@pytest.mark.parametrize("field,value", [
    ("producer", "other.producer"), ("module_path", "other/module"),
    ("producer_oracle_sha256", "a"*64), ("report_subject_policy_sha256", "b"*64),
])
def test_wrong_producer_identity_not_rescued_by_matching_archive(tmp_path, field, value):
    source = fixture_source(); source["source_manifest"][field] = value
    seal(tmp_path, source)
    with pytest.raises(rc.ResearchContextError):
        read_bound(tmp_path)


@pytest.mark.parametrize("mutation", ["policy", "eligible", "coverage", "source_order"])
def test_wrong_audit_or_reordered_source_not_accepted(tmp_path, mutation):
    source = fixture_source(); audit = source["report_entity_audit"]
    if mutation == "policy": audit["policy_version"] = "report_subject_scoring.v2"
    elif mutation == "eligible": audit["excluded_evidence"][0]["research_subject_eligible"] = True
    elif mutation == "coverage": audit["excluded_evidence"].pop()
    else: audit["affected_codes"][0:2] = reversed(audit["affected_codes"][0:2])
    seal(tmp_path, source)
    with pytest.raises(rc.ResearchContextError): read_bound(tmp_path)


@pytest.mark.parametrize("mutation", ["extra_warning", "article", "archive_order"])
def test_final_projection_rejects_extra_or_reordered_archive_fields(tmp_path, mutation):
    def change(payload):
        if mutation == "extra_warning": payload["cannot_confirm"].append("UNPROVEN_EXTRA_WARNING")
        elif mutation == "article": payload["articles"][0]["source_title"] = "TAMPERED_BUT_RESEALED"
        else: payload["cannot_confirm"][1:3] = reversed(payload["cannot_confirm"][1:3])
    seal(tmp_path, fixture_source(), change)
    with pytest.raises(rc.ResearchContextError): read_bound(tmp_path)


@pytest.mark.parametrize("part", ["source", "receipt", "manifest"])
def test_existing_source_receipt_and_manifest_integrity_remains_required(tmp_path, part):
    _, source_path = seal(tmp_path, fixture_source())
    path = source_path if part == "source" else (tmp_path / "manifest.json" if part == "manifest"
           else tmp_path / "receipts/research/hourly/live/20260930/1400.json")
    if part == "source": path.write_bytes(path.read_bytes() + b" ")
    else:
        content = json.loads(path.read_bytes())
        content["payload_sha256" if part == "receipt" else "research/hourly/live/20260930/1400.json"] = "f"*64
        path.write_bytes(_canonical_bytes(content))
    with pytest.raises(rc.ResearchContextError): read_bound(tmp_path)


def test_150002_stays_after_cutoff_14001203_late_recovery_is_not_retimed(tmp_path):
    payload, _ = seal(tmp_path, fixture_source())
    late = deepcopy(payload); late["source_generated_at"] = "2026-09-30T15:00:02+08:00"
    HourlyResearchStore(tmp_path).publish(late, slot="1500", mode="LIVE")
    before = hashes(tmp_path)
    _, _, actual, paths = read_bound(tmp_path)
    assert actual == payload
    assert paths["actual_source_generated_at"] == "2026-09-30T14:12:03+08:00"
    assert paths["pit_rejected_slots"] == "1500:2026-09-30T15:00:02+08:00>2026-09-30T15:00:00+08:00"
    assert hashes(tmp_path) == before
