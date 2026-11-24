"""Run against the exact Stage candidate with the existing recovery fixtures."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_stage_publication_recovery import (
    DATE, STAGE, envelope, existing, fail_once, raw, raw_kwargs, selection, snapshot,
)

MISSING = {"HK_CONNECT": "HK D1 snapshot integrity invalid: hkconnect_d1_top100"}


def seed_a(tmp_path):
    raw_store = raw.RawStore(tmp_path / "raw")
    selection_store = selection.SelectionStore(tmp_path / "selection")
    lane = raw_store.publish(**raw_kwargs())
    selection_store.publish(envelope("A_SHARE", lane["artifact_sha256"]), market="A_SHARE")
    runner = SimpleNamespace(config=SimpleNamespace(
        raw_root=raw_store.root, selection_root=selection_store.root, backfill_run_id=None,
    ))
    return raw_store, runner, lane


def publish_partial(store, lane):
    return store.publish_bundle(
        trade_date=DATE, stage_id=STAGE, status="PARTIAL_WITH_ROWS",
        markets={"A_SHARE": lane}, missing_markets=MISSING,
    )


def test_partial_bundle_recovers_pointer_without_fabricating_hk(tmp_path, monkeypatch):
    store, runner, a = seed_a(tmp_path)
    writer = fail_once(monkeypatch, raw, "bundle_latest.json")
    with pytest.raises(OSError, match="injected"):
        publish_partial(store, a)
    monkeypatch.setattr(raw, "_atomic_write_json", writer)
    surviving = snapshot(tmp_path)

    state, result = existing(runner)
    assert state == "PARTIAL" and result["recovered_publications"] == ["BUNDLE"]
    receipt = store.read_verified_bundle(DATE, STAGE)["receipt"]
    assert receipt["status"] == "PARTIAL_WITH_ROWS"
    assert receipt["missing_markets"] == MISSING
    assert set(receipt["markets"]) == {"A_SHARE"}
    assert set(store._load_latest()["entries"]) == {f"{DATE}/{STAGE}/A_SHARE"}
    assert all(snapshot(tmp_path)[path] == content for path, content in surviving.items())
    assert publish_partial(store, store.publish(**raw_kwargs()))["already_exists"] is True


def test_partial_to_complete_reconciles_immutable_predecessor(tmp_path, monkeypatch):
    store, runner, a = seed_a(tmp_path)
    partial = publish_partial(store, a)
    old_path = store.root / Path(partial["receipt_relative"])
    old_bytes = old_path.read_bytes()
    hk = store.publish(**raw_kwargs("HK_CONNECT"))
    selection.SelectionStore(runner.config.selection_root).publish(
        envelope("HK_CONNECT", hk["artifact_sha256"]), market="HK_CONNECT",
    )
    writer = fail_once(monkeypatch, raw, "bundle_latest.json")
    bundle = dict(trade_date=DATE, stage_id=STAGE, status="READY", markets={"A_SHARE": a, "HK_CONNECT": hk})
    with pytest.raises(OSError, match="injected"):
        store.publish_bundle(**bundle)
    monkeypatch.setattr(raw, "_atomic_write_json", writer)
    assert existing(runner)[0] == "PARTIAL"
    completed = store.publish_bundle(**bundle)
    assert completed["bundle_id"] != partial["bundle_id"]
    assert old_path.read_bytes() == old_bytes
    (store.root / "bundle_latest.json").unlink()
    assert existing(runner)[0] == "VERIFIED"
    assert store.read_verified_bundle(DATE, STAGE)["receipt"]["bundle_id"] == completed["bundle_id"]
    assert old_path.read_bytes() == old_bytes


def test_partial_bundle_rejects_unverified_a_identity_before_writing(tmp_path):
    store, _runner, a = seed_a(tmp_path)
    before = snapshot(tmp_path)
    with pytest.raises(ValueError, match="bundle market pointer or coverage mismatch"):
        publish_partial(store, {**a, "row_count": a["row_count"] + 1})
    assert snapshot(tmp_path) == before


def test_external_finance_retry_survives_complete_stage_extension(tmp_path, monkeypatch):
    from infrastructure import manager_input_attestation
    from stage_center import research_context

    slot, code = "0900", "A.000001"
    source = json.dumps({
        "trade_date": DATE,
        "source_manifest": {
            "producer": "ops.collect_hourly_research_input",
            "hourly_slot": slot,
            "pit_cutoff": research_context._source_slot_cutoff(DATE, slot).isoformat(timespec="seconds"),
        },
    }).encode()
    sha = hashlib.sha256(source).hexdigest()
    witness_path = tmp_path / "research/hourly/source" / f"{sha}.json"
    witness_path.parent.mkdir(parents=True)
    witness_path.write_bytes(source)

    base = {"stock_pool": [{"stock_code": code}]}
    payload = {**base, "stage_evidence_v1": {
        "trade_date": DATE, "slot": slot, "source_input_sha256": sha,
        "payload_base_sha256": research_context._payload_base_sha(base),
        "payload_sha256_scope": "ARCHIVE_WITHOUT_STAGE_EVIDENCE_V1",
        "items": [{
            "stock_code": code, "item_quality": "OK", "quality_score": 72.5,
            "is_new_since_last_slot": True, "is_recheck_duplicate": False,
        }],
        "evidence": [],
    }}
    paths = dict.fromkeys((
        "payload_path", "payload_sha256", "manifest_path", "manifest_sha256",
        "receipt_path", "receipt_sha256", "actual_source_generated_at", "pit_rejected_slots",
    ), "fixture")
    paths["source_input_sha256"] = sha
    monkeypatch.setattr(research_context, "_verified_hourly_slot", lambda *args, **kwargs: (slot, payload, paths))
    monkeypatch.setattr(research_context, "build_research_archive", lambda *args, **kwargs: base)
    monkeypatch.setattr(research_context, "_morning_scores", lambda *args, **kwargs: ({code: (82, ())}, [], ()))
    monkeypatch.setattr(manager_input_attestation, "read_stage_hourly_attestation", lambda **kwargs: ({
        "source_input_sha256": sha,
        "input_available_at": "2026-11-20T09:00:12+08:00",
        "completion_witness": {
            "finished_at": "2026-11-20T09:00:15+08:00",
            "receipt_sha256": "a" * 64,
            "peripheral_retry_sources": ["external_finance"],
        },
    }, ()))

    def unexpected_merge(*args, **kwargs):
        pytest.fail("complete extension required no source row merge")

    monkeypatch.setattr(research_context, "_merge_source_rows", unexpected_merge)
    context = research_context.load_research_context(tmp_path, trade_date=DATE, stage_cutoff="09:35:05")
    gap = "RESEARCH_PERIPHERAL_SOURCE_RETRY_REQUIRED:external_finance"
    assert context.cannot_confirm == (gap,)
    assert f"v4_research_cannot_confirm={gap}" in context.source_evidence
    assert context.by_code[code].source_health == "READY_WITH_GAPS"
    assert context.by_code[code].research_quality_score == 72.5
