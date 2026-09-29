from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import textwrap
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from domains.preselection_materializer import build_expected_missing_pool, build_hourly_research_pool
from domains.research import build_research_archive
from infrastructure.data_store import _canonical_bytes, _sha256
from infrastructure.preselection_pool_store import PreselectionPoolStore
from infrastructure.research_store import HourlyResearchStore


def _verified_pool(pool_id: str, *, trade_date: str, source_role: str) -> dict:
    display = {
        "a_d1_fupan_watchlist_pool": "A股 D-1 复盘继续观察池",
        "a_d1_stage7_fenshi_review_pool": "A股 D-1 Stage7/分时复盘池",
        "a_share_research_recommendation_pool": "A股研报推荐股票池",
    }[pool_id]
    status = {
        "a_d1_fupan_watchlist_pool": "D1_FUPAN_WATCHLIST_READY",
        "a_d1_stage7_fenshi_review_pool": "D1_STAGE7_REVIEW_READY",
        "a_share_research_recommendation_pool": "RESEARCH_RECOMMENDATION_POOL_READY",
    }[pool_id]
    producer = {
        "a_d1_fupan_watchlist_pool": "v3_5_d1_fupan_review_v1",
        "a_d1_stage7_fenshi_review_pool": "v3_5_d1_stage7_review_v1",
        "a_share_research_recommendation_pool": "v3_5_hourly_research_window_v1",
    }[pool_id]
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": trade_date,
        "pool_id": pool_id,
        "display_name": display,
        "market": "A",
        "status": status,
        "producer_id": producer,
        "source_role": source_role,
        "source_path": f"fixture/{trade_date}/{pool_id}.json",
        "source_sha256": hashlib.sha256(f"{trade_date}:{pool_id}".encode()).hexdigest(),
        "rows": [{
            "symbol": "A.000001",
            "market": "A",
            "pool_id": pool_id,
            "pool_rank": 1,
            "recommendation_status": "RESEARCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }],
        "cannot_confirm": ["RESEARCH_ONLY_NO_BUY_GATE"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _source(date: str, slot: str, code: str, article_id: str) -> dict:
    dashed = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    hour, minute = int(slot[:2]), int(slot[2:])
    hhmm = f"{hour:02d}:{minute:02d}:00"
    return {
        "schema_version": "v3_research_lane.v2",
        "trade_date": date,
        "source_manifest": {"generated_at": f"{dashed}T{hhmm}+08:00", "hourly_slot": slot},
        "stock_research_timeline": [{
            "stock_code": code,
            "stock_name": f"股票{code}",
            "event_time": f"{dashed}T{hour:02d}:{max(minute-1,0):02d}:00+08:00",
            "source_published_at": f"{dashed}T{hour:02d}:{max(minute-2,0):02d}:00+08:00",
            "first_seen_at": f"{dashed}T{hour:02d}:{max(minute-2,0):02d}:30+08:00",
            "last_checked_at": f"{dashed}T{hhmm}+08:00",
            "source_type": "hourly_research",
            "source_name": "fixture",
            "source_title": f"fixture-{article_id}",
            "source_path": f"fixture/{article_id}.json",
            "url": f"https://example.invalid/{article_id}",
            "theme": "fixture",
            "catalyst": "fixture",
            "evidence_sentence": "fixture",
            "evidence_level": "L2_MEDIUM",
            "confidence": "MEDIUM",
            "dedup_key": article_id,
        }],
        "stock_research_daily": [{
            "stock_code": code,
            "stock_name": f"股票{code}",
            "first_seen_time": f"{dashed}T{hour:02d}:{max(minute-2,0):02d}:30+08:00",
            "last_seen_time": f"{dashed}T{hhmm}+08:00",
            "research_score": 80,
            "research_status": "REPEATED",
            "evidence_count": 1,
            "source_count": 1,
            "strong_evidence_count": 0,
            "medium_evidence_count": 1,
            "weak_evidence_count": 0,
            "source_types": ["hourly_research"],
            "themes": ["fixture"],
            "top_catalysts": ["fixture"],
        }],
        "research_pool_bridge": [{"stock_code": code, "formal_overlap": True, "stage_overlap": False}],
        "cannot_confirm": [],
    }


def _publish_hourly(root: Path, date: str, slot: str, code: str, article_id: str) -> None:
    source = _source(date, slot, code, article_id)
    payload = build_research_archive(source, source_input_sha256=hashlib.sha256(article_id.encode()).hexdigest())
    HourlyResearchStore(root).publish(payload, slot=slot, mode="LIVE")


class _ExactStore:
    def __init__(self, delegate: HourlyResearchStore, allowed: dict[str, set[str]]) -> None:
        self.delegate = delegate
        self.allowed = allowed

    def list_slots(self, archive_date: str, *, mode: str) -> list[str]:
        return sorted(self.allowed.get(archive_date, set()))

    def read_exact(self, archive_date: str, slot: str, *, mode: str):
        assert slot in self.allowed.get(archive_date, set())
        return self.delegate.read_exact(archive_date, slot, mode=mode)


def _write_recovery_trio(root: Path, artifact: dict) -> tuple[Path, Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    artifact_path = root / "artifact.json"
    manifest_path = root / "manifest.json"
    receipt_path = root / "receipt.json"
    digest = _sha256(artifact)
    artifact_path.write_bytes(_canonical_bytes(artifact))
    manifest = {artifact["pool_id"]: digest, "other_pool": "f" * 64}
    manifest_path.write_bytes(_canonical_bytes(manifest))
    receipt = PreselectionPoolStore._receipt(
        trade_date=artifact["trade_date"],
        pool_id=artifact["pool_id"],
        artifact_path=f"preselection_pools/{artifact['trade_date']}/{artifact['pool_id']}.json",
        artifact_sha256=digest,
        payload=artifact,
    )
    receipt_path.write_bytes(_canonical_bytes(receipt))
    return artifact_path, manifest_path, receipt_path


def test_store_cas_recovery_requires_expected_old_sha_and_supports_one_step_rollback(tmp_path: Path) -> None:
    trade_date = "20260918"
    pool_id = "a_share_research_recommendation_pool"
    store = PreselectionPoolStore(tmp_path / "data")
    old = build_expected_missing_pool(
        trade_date,
        pool_id=pool_id,
        display_name="A股研报推荐股票池",
        market="A",
        reason="A_RESEARCH_HOURLY_WINDOW_EVIDENCE_MISSING",
    )
    old_pub = store.materialize(old)
    sibling = _verified_pool(
        "a_d1_fupan_watchlist_pool",
        trade_date=trade_date,
        source_role="VERIFIED_D1_FUPAN_REVIEW",
    )
    sibling_pub = store.materialize(sibling)
    sibling_path = tmp_path / "data" / sibling_pub["artifact_path"]
    sibling_before = sibling_path.read_bytes()
    replacement = _verified_pool(pool_id, trade_date=trade_date, source_role="VERIFIED_HOURLY_RESEARCH")

    with pytest.raises(ValueError, match="expected old SHA"):
        store.recover_expected_missing(replacement, expected_old_sha256="0" * 64)

    recovered = store.recover_expected_missing(replacement, expected_old_sha256=old_pub["sha256"])
    assert store.read_pool(trade_date, pool_id) == replacement
    assert recovered["previous_sha256"] == old_pub["sha256"]
    assert recovered["recovery"] is True

    rolled_back = store.rollback_recovery(
        trade_date,
        pool_id,
        expected_current_sha256=recovered["sha256"],
    )
    assert rolled_back["sha256"] == old_pub["sha256"]
    assert store.read_pool(trade_date, pool_id) == old
    assert sibling_path.read_bytes() == sibling_before
    assert store.read_pool(trade_date, "a_d1_fupan_watchlist_pool") == sibling


def test_scheduled_publish_only_self_heals_fupan_and_stage7_placeholders(tmp_path: Path) -> None:
    from ops.materialize_scheduled_preselection import publish_scheduled_artifacts

    trade_date = "20260918"
    store = PreselectionPoolStore(tmp_path / "data")
    pools = [
        ("a_d1_fupan_watchlist_pool", "A股 D-1 复盘继续观察池", "VERIFIED_D1_FUPAN_REVIEW"),
        ("a_d1_stage7_fenshi_review_pool", "A股 D-1 Stage7/分时复盘池", "VERIFIED_D1_STAGE7_REPLAY"),
        ("a_share_research_recommendation_pool", "A股研报推荐股票池", "VERIFIED_HOURLY_RESEARCH"),
    ]
    for pool_id, display, _role in pools:
        store.materialize(build_expected_missing_pool(
            trade_date, pool_id=pool_id, display_name=display, market="A", reason="fixture-missing"
        ))

    artifacts = [_verified_pool(pool_id, trade_date=trade_date, source_role=role) for pool_id, _d, role in pools]
    with pytest.raises(ValueError, match="conflicting preselection-pool materialization"):
        publish_scheduled_artifacts(store, artifacts)

    # fupan/stage7 are promoted before the research conflict; research must stay missing
    assert store.read_pool(trade_date, "a_d1_fupan_watchlist_pool")["source_role"] == "VERIFIED_D1_FUPAN_REVIEW"
    assert store.read_pool(trade_date, "a_d1_stage7_fenshi_review_pool")["source_role"] == "VERIFIED_D1_STAGE7_REPLAY"
    assert store.read_pool(trade_date, "a_share_research_recommendation_pool")["source_role"] == "EXPECTED_MISSING"


def test_exact_research_recovery_uses_only_artifact_source_slots_and_ignores_later_slots(tmp_path: Path, monkeypatch) -> None:
    from ops.refresh_research_preselection import recover_exact_research_preselection

    data_root = tmp_path / "data"
    trade_date = "20260731"
    source_date = "20260730"
    sh = ZoneInfo("Asia/Shanghai")
    monkeypatch.setattr(
        "domains.preselection_materializer._research_window",
        lambda _date: (datetime(2026, 7, 30, 8, 30, tzinfo=sh), datetime(2026, 7, 31, 8, 30, tzinfo=sh)),
    )
    _publish_hourly(data_root, source_date, "0900", "000001", "a")
    _publish_hourly(data_root, source_date, "1000", "000002", "b")
    delegate = HourlyResearchStore(data_root)
    exact = _ExactStore(delegate, {source_date: {"0900", "1000"}})
    candidate = build_hourly_research_pool(data_root, trade_date=trade_date, store=exact)
    artifact_path, manifest_path, receipt_path = _write_recovery_trio(tmp_path / "staging", candidate)

    placeholder = build_expected_missing_pool(
        trade_date, pool_id="a_share_research_recommendation_pool",
        display_name="A股研报推荐股票池", market="A", reason="missing"
    )
    store = PreselectionPoolStore(data_root)
    old_sha = store.materialize(placeholder)["sha256"]

    # This slot exists in the current store but is intentionally absent from the historical artifact lineage.
    _publish_hourly(data_root, source_date, "1100", "000003", "later")
    assert len(build_hourly_research_pool(data_root, trade_date=trade_date)["rows"]) == 3

    result = recover_exact_research_preselection(
        data_root=data_root,
        trade_date=trade_date,
        recovery_artifact=artifact_path,
        recovery_manifest=manifest_path,
        recovery_receipt=receipt_path,
        expected_old_sha256=old_sha,
        expected_recovery_sha256=_sha256(candidate),
    )
    recovered = store.read_pool(trade_date, "a_share_research_recommendation_pool")
    assert result["sha256"] == _sha256(candidate)
    assert recovered == candidate
    assert len(recovered["rows"]) == 2
    assert recovered["source_path"].endswith("0900.json|research/hourly/live/20260730/1000.json")


def test_exact_research_recovery_rejects_bad_trio_before_replacing_placeholder(tmp_path: Path, monkeypatch) -> None:
    from ops.refresh_research_preselection import recover_exact_research_preselection

    data_root = tmp_path / "data"
    trade_date = "20260731"
    sh = ZoneInfo("Asia/Shanghai")
    monkeypatch.setattr(
        "domains.preselection_materializer._research_window",
        lambda _date: (datetime(2026, 7, 30, 8, 30, tzinfo=sh), datetime(2026, 7, 31, 8, 30, tzinfo=sh)),
    )
    _publish_hourly(data_root, "20260730", "0900", "000001", "a")
    candidate = build_hourly_research_pool(
        data_root,
        trade_date=trade_date,
        store=_ExactStore(HourlyResearchStore(data_root), {"20260730": {"0900"}}),
    )
    artifact_path, manifest_path, receipt_path = _write_recovery_trio(tmp_path / "staging", candidate)
    manifest = json.loads(manifest_path.read_text())
    manifest[candidate["pool_id"]] = "0" * 64
    manifest_path.write_bytes(_canonical_bytes(manifest))
    store = PreselectionPoolStore(data_root)
    placeholder = build_expected_missing_pool(
        trade_date, pool_id=candidate["pool_id"], display_name="A股研报推荐股票池", market="A", reason="missing"
    )
    old_sha = store.materialize(placeholder)["sha256"]

    with pytest.raises(ValueError, match="recovery manifest"):
        recover_exact_research_preselection(
            data_root=data_root,
            trade_date=trade_date,
            recovery_artifact=artifact_path,
            recovery_manifest=manifest_path,
            recovery_receipt=receipt_path,
            expected_old_sha256=old_sha,
            expected_recovery_sha256=_sha256(candidate),
        )
    assert store.read_pool(trade_date, candidate["pool_id"]) == placeholder


def test_recovery_commit_failure_restores_old_trio_and_can_retry(tmp_path: Path, monkeypatch) -> None:
    trade_date = "20260918"
    pool_id = "a_share_research_recommendation_pool"
    store = PreselectionPoolStore(tmp_path / "data")
    placeholder = build_expected_missing_pool(
        trade_date,
        pool_id=pool_id,
        display_name="A股研报推荐股票池",
        market="A",
        reason="fixture-missing",
    )
    old_sha = store.materialize(placeholder)["sha256"]
    replacement = _verified_pool(
        pool_id,
        trade_date=trade_date,
        source_role="VERIFIED_HOURLY_RESEARCH",
    )
    original_write = store._write
    failed = False

    def fail_once(relative, value):
        nonlocal failed
        if relative == f"preselection_pools/{trade_date}/manifest.json" and not failed:
            failed = True
            raise OSError("injected manifest commit failure")
        return original_write(relative, value)

    monkeypatch.setattr(store, "_write", fail_once)
    with pytest.raises(OSError, match="injected manifest commit failure"):
        store.recover_expected_missing(replacement, expected_old_sha256=old_sha)

    monkeypatch.setattr(store, "_write", original_write)
    assert store.read_pool(trade_date, pool_id) == placeholder
    recovered = store.recover_expected_missing(
        replacement,
        expected_old_sha256=old_sha,
    )
    assert recovered["sha256"] == _sha256(replacement)
    assert store.read_pool(trade_date, pool_id) == replacement


def test_rollback_commit_failure_restores_recovered_trio_and_can_retry(tmp_path: Path, monkeypatch) -> None:
    trade_date = "20260918"
    pool_id = "a_share_research_recommendation_pool"
    store = PreselectionPoolStore(tmp_path / "data")
    placeholder = build_expected_missing_pool(
        trade_date,
        pool_id=pool_id,
        display_name="A股研报推荐股票池",
        market="A",
        reason="fixture-missing",
    )
    old_sha = store.materialize(placeholder)["sha256"]
    replacement = _verified_pool(
        pool_id,
        trade_date=trade_date,
        source_role="VERIFIED_HOURLY_RESEARCH",
    )
    recovered = store.recover_expected_missing(
        replacement,
        expected_old_sha256=old_sha,
    )
    original_write = store._write
    failed = False

    def fail_once(relative, value):
        nonlocal failed
        if relative == f"preselection_pools/{trade_date}/manifest.json" and not failed:
            failed = True
            raise OSError("injected rollback manifest failure")
        return original_write(relative, value)

    monkeypatch.setattr(store, "_write", fail_once)
    with pytest.raises(OSError, match="injected rollback manifest failure"):
        store.rollback_recovery(
            trade_date,
            pool_id,
            expected_current_sha256=recovered["sha256"],
        )

    monkeypatch.setattr(store, "_write", original_write)
    assert store.read_pool(trade_date, pool_id) == replacement
    rolled_back = store.rollback_recovery(
        trade_date,
        pool_id,
        expected_current_sha256=recovered["sha256"],
    )
    assert rolled_back["sha256"] == old_sha
    assert store.read_pool(trade_date, pool_id) == placeholder


def test_recovery_and_rollback_readers_are_old_or_new_only_during_commit(
    tmp_path: Path, monkeypatch
) -> None:
    trade_date = "20260918"
    pool_id = "a_share_research_recommendation_pool"
    store = PreselectionPoolStore(tmp_path / "data")
    placeholder = build_expected_missing_pool(
        trade_date,
        pool_id=pool_id,
        display_name="A股研报推荐股票池",
        market="A",
        reason="fixture-missing",
    )
    old_sha = store.materialize(placeholder)["sha256"]
    replacement = _verified_pool(
        pool_id,
        trade_date=trade_date,
        source_role="VERIFIED_HOURLY_RESEARCH",
    )
    original_write = store._write

    def slow_write(relative, value):
        original_write(relative, value)
        if relative in {
            f"preselection_pools/{trade_date}/{pool_id}.json",
            f"preselection_pools/{trade_date}/receipts/{pool_id}.json",
        }:
            time.sleep(0.05)

    monkeypatch.setattr(store, "_write", slow_write)
    result: dict[str, object] = {}

    def publish() -> None:
        try:
            result["value"] = store.recover_expected_missing(
                replacement,
                expected_old_sha256=old_sha,
            )
        except Exception as error:  # pragma: no cover - assertion below records unexpected errors
            result["error"] = error

    worker = threading.Thread(target=publish)
    worker.start()
    reads: list[dict] = []
    while worker.is_alive():
        reads.append(store.read_pool_snapshot(trade_date, pool_id))
    worker.join()

    assert "error" not in result
    assert result["value"]["sha256"] == _sha256(replacement)
    assert reads
    assert all(snapshot["artifact_sha256"] in {old_sha, _sha256(replacement)} for snapshot in reads)
    assert all(
        snapshot["artifact"]["producer_id"]
        in {"graph_expected_missing_v1", "v3_5_hourly_research_window_v1"}
        for snapshot in reads
    )

    rollback_result: dict[str, object] = {}

    def rollback() -> None:
        try:
            rollback_result["value"] = store.rollback_recovery(
                trade_date,
                pool_id,
                expected_current_sha256=_sha256(replacement),
            )
        except Exception as error:  # pragma: no cover - assertion below records unexpected errors
            rollback_result["error"] = error

    rollback_worker = threading.Thread(target=rollback)
    rollback_worker.start()
    rollback_reads: list[dict] = []
    while rollback_worker.is_alive():
        rollback_reads.append(store.read_pool_snapshot(trade_date, pool_id))
    rollback_worker.join()

    assert "error" not in rollback_result
    assert rollback_result["value"]["sha256"] == old_sha
    assert rollback_reads
    assert all(
        snapshot["artifact_sha256"] in {old_sha, _sha256(replacement)}
        for snapshot in rollback_reads
    )
    assert all(
        snapshot["artifact"]["producer_id"]
        in {"graph_expected_missing_v1", "v3_5_hourly_research_window_v1"}
        for snapshot in rollback_reads
    )


def test_hard_exit_reconciles_then_retry_and_rollback_work_in_new_process(tmp_path: Path) -> None:
    trade_date = "20260918"
    pool_id = "a_share_research_recommendation_pool"
    data_root = tmp_path / "data"
    store = PreselectionPoolStore(data_root)
    placeholder = build_expected_missing_pool(
        trade_date,
        pool_id=pool_id,
        display_name="A股研报推荐股票池",
        market="A",
        reason="fixture-missing",
    )
    old_sha = store.materialize(placeholder)["sha256"]
    replacement = _verified_pool(
        pool_id,
        trade_date=trade_date,
        source_role="VERIFIED_HOURLY_RESEARCH",
    )
    replacement_json = json.dumps(replacement, ensure_ascii=False, sort_keys=True)
    child = textwrap.dedent(
        """
        import json
        import os
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path.cwd()))
        from infrastructure.preselection_pool_store import PreselectionPoolStore

        root = Path(sys.argv[1])
        replacement = json.loads(sys.argv[2])
        store = PreselectionPoolStore(root)
        original_write = store._write

        def hard_exit(relative, value):
            original_write(relative, value)
            if relative == "preselection_pools/20260918/a_share_research_recommendation_pool.json":
                os._exit(19)

        store._write = hard_exit
        store.recover_expected_missing(replacement, expected_old_sha256=sys.argv[3])
        """
    )
    child_path = tmp_path / "hard_exit_child.py"
    child_path.write_text(child, encoding="utf-8")
    child_process = subprocess.run(
        [sys.executable, str(child_path), str(data_root), replacement_json, old_sha],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
    )
    assert child_process.returncode == 19

    # A fresh process first repairs the mixed trio to the complete old state.
    fresh = PreselectionPoolStore(data_root)
    assert fresh.read_pool(trade_date, pool_id) == placeholder
    pending_root = data_root / "preselection_pending_commits"
    assert not list(pending_root.rglob("*.json")) if pending_root.exists() else True

    recovered = fresh.recover_expected_missing(replacement, expected_old_sha256=old_sha)
    assert recovered["sha256"] == _sha256(replacement)
    rolled_back = fresh.rollback_recovery(
        trade_date,
        pool_id,
        expected_current_sha256=recovered["sha256"],
    )
    assert rolled_back["sha256"] == old_sha
    assert fresh.read_pool_snapshot(trade_date, pool_id)["artifact_sha256"] == old_sha
