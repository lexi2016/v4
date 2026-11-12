from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from infrastructure.research_store import HourlyResearchStore
from ops import run_hourly_research as hourly_runner
from ops.run_hourly_research import run_hourly_research_file


def _source(archive_date: str = "20260730", *, title: str = "银行板块跟踪") -> dict:
    dashed = f"{archive_date[:4]}-{archive_date[4:6]}-{archive_date[6:]}"
    return {
        "schema_version": "v3_research_lane.v2",
        "trade_date": archive_date,
        "source_manifest": {
            "generated_at": f"{dashed}T12:00:00+08:00",
            "hourly_slot": "1200",
        },
        "stock_research_timeline": [
            {
                "stock_code": "000001",
                "stock_name": "平安银行",
                "event_time": f"{dashed}T11:59:00+08:00",
                "source_published_at": f"{dashed}T11:58:00+08:00",
                "first_seen_at": f"{dashed}T11:58:30+08:00",
                "last_checked_at": f"{dashed}T12:00:00+08:00",
                "source_type": "hourly_research",
                "source_name": "08:30早盘新闻",
                "source_title": title,
                "source_path": r"C:\legacy\morning.csv",
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
                "first_seen_time": f"{dashed}T11:58:30+08:00",
                "last_seen_time": f"{dashed}T12:00:00+08:00",
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
            {
                "stock_code": "000001",
                "formal_overlap": True,
                "stage_overlap": False,
            }
        ],
        "cannot_confirm": [],
    }


def _write_source(path: Path, payload: dict) -> str:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_live_hourly_runner_materializes_immutable_artifact_and_latest(
    tmp_path: Path,
) -> None:
    source = tmp_path / "external-source.json"
    source_sha = _write_source(source, _source())
    data_root = tmp_path / "data"

    result = run_hourly_research_file(
        data_root=data_root,
        source=source,
        business_date="20260730",
        target_date="20260730",
        slot="1200",
        mode="LIVE",
    )

    assert result["status"] == "SUCCEEDED"
    assert result["external_source_sha256"] == source_sha
    assert result["external_source_read_only"] is True
    assert result["latest_updated"] is True
    assert result["production_allowed"] is False
    store = HourlyResearchStore(data_root)
    artifact = store.read_exact("20260730", "1200", mode="LIVE")
    assert artifact is not None
    assert artifact["archive_date"] == "20260730"
    assert artifact["article_count"] == 1
    assert store.read_latest() == artifact
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_sha

    repeated = run_hourly_research_file(
        data_root=data_root,
        source=source,
        business_date="20260730",
        target_date="20260730",
        slot="1200",
        mode="LIVE",
    )
    assert repeated["payload_sha256"] == result["payload_sha256"]
    assert repeated["latest_updated"] is False


def test_verified_matching_retry_skips_archive_rebuild(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "external-source.json"
    _write_source(source, _source())
    data_root = tmp_path / "data"
    first = run_hourly_research_file(
        data_root=data_root,
        source=source,
        business_date="20260730",
        target_date="20260730",
        slot="1200",
        mode="REPLAY",
    )

    def reject_rebuild(*args, **kwargs):
        raise AssertionError("verified idempotent retry rebuilt the archive")

    monkeypatch.setattr(
        hourly_runner,
        "build_research_archive",
        reject_rebuild,
    )
    repeated = run_hourly_research_file(
        data_root=data_root,
        source=source,
        business_date="20260730",
        target_date="20260730",
        slot="1200",
        mode="REPLAY",
    )

    assert repeated["payload_sha256"] == first["payload_sha256"]
    assert repeated["latest_updated"] is False
    assert repeated["production_allowed"] is False


def test_matching_retry_fails_closed_on_receipt_tamper(tmp_path: Path) -> None:
    source = tmp_path / "external-source.json"
    _write_source(source, _source())
    data_root = tmp_path / "data"
    run_hourly_research_file(
        data_root=data_root,
        source=source,
        business_date="20260730",
        target_date="20260730",
        slot="1200",
        mode="REPLAY",
    )
    receipt_path = (
        data_root
        / "receipts"
        / "research"
        / "hourly"
        / "replay"
        / "20260730"
        / "1200.json"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["article_count"] = 999
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(ValueError, match="manifest or receipt"):
        run_hourly_research_file(
            data_root=data_root,
            source=source,
            business_date="20260730",
            target_date="20260730",
            slot="1200",
            mode="REPLAY",
        )


def test_transformer_identity_change_forces_one_rebuild(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "external-source.json"
    _write_source(source, _source())
    data_root = tmp_path / "data"
    first = run_hourly_research_file(
        data_root=data_root,
        source=source,
        business_date="20260730",
        target_date="20260730",
        slot="1200",
        mode="REPLAY",
    )
    original_builder = hourly_runner.build_research_archive
    rebuild_count = 0

    def count_rebuild(*args, **kwargs):
        nonlocal rebuild_count
        rebuild_count += 1
        return original_builder(*args, **kwargs)

    monkeypatch.setattr(
        hourly_runner,
        "_research_transformer_identity_sha256",
        lambda: "f" * 64,
    )
    monkeypatch.setattr(
        hourly_runner,
        "build_research_archive",
        count_rebuild,
    )
    changed_identity = run_hourly_research_file(
        data_root=data_root,
        source=source,
        business_date="20260730",
        target_date="20260730",
        slot="1200",
        mode="REPLAY",
    )
    cached_changed_identity = run_hourly_research_file(
        data_root=data_root,
        source=source,
        business_date="20260730",
        target_date="20260730",
        slot="1200",
        mode="REPLAY",
    )

    assert rebuild_count == 1
    assert changed_identity["payload_sha256"] == first["payload_sha256"]
    assert cached_changed_identity["payload_sha256"] == first["payload_sha256"]


def test_matching_retry_fails_closed_on_transform_validation_tamper(
    tmp_path: Path,
) -> None:
    source = tmp_path / "external-source.json"
    source_sha = _write_source(source, _source())
    data_root = tmp_path / "data"
    run_hourly_research_file(
        data_root=data_root,
        source=source,
        business_date="20260730",
        target_date="20260730",
        slot="1200",
        mode="REPLAY",
    )
    validation_directory = (
        data_root
        / "receipts"
        / "research"
        / "hourly"
        / "transform-validation"
        / "replay"
        / "20260730"
        / "1200"
    )
    validation_paths = list(validation_directory.glob("*.json"))
    assert len(validation_paths) == 1
    validation_path = validation_paths[0]
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    assert validation["source_input_sha256"] == source_sha
    validation["payload_sha256"] = "0" * 64
    validation_path.write_text(json.dumps(validation), encoding="utf-8")

    with pytest.raises(ValueError, match="transform validation mismatch"):
        run_hourly_research_file(
            data_root=data_root,
            source=source,
            business_date="20260730",
            target_date="20260730",
            slot="1200",
            mode="REPLAY",
        )


@pytest.mark.parametrize("mode", ["REPLAY", "BACKFILL"])
def test_non_live_hourly_runner_is_namespaced_and_never_updates_latest(
    tmp_path: Path, mode: str
) -> None:
    source = tmp_path / f"{mode}.json"
    _write_source(source, _source())
    data_root = tmp_path / "data"

    result = run_hourly_research_file(
        data_root=data_root,
        source=source,
        business_date="20260730",
        target_date="20260730",
        slot="1200",
        mode=mode,
    )

    assert f"/hourly/{mode.lower()}/" in result["payload_path"]
    assert result["latest_updated"] is False
    assert HourlyResearchStore(data_root).read_latest() is None


def test_hourly_runner_fails_closed_on_date_slot_or_identity_conflict(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.json"
    _write_source(source, _source())
    data_root = tmp_path / "data"

    with pytest.raises(ValueError, match="target_date"):
        run_hourly_research_file(
            data_root=data_root,
            source=source,
            business_date="20260730",
            target_date="20260731",
            slot="1200",
            mode="LIVE",
        )
    changed = tmp_path / "changed.json"
    changed_payload = _source(title="冲突标题")
    _write_source(changed, changed_payload)
    run_hourly_research_file(
        data_root=data_root,
        source=source,
        business_date="20260730",
        target_date="20260730",
        slot="1200",
        mode="LIVE",
    )
    with pytest.raises(ValueError, match="conflicting hourly research"):
        run_hourly_research_file(
            data_root=data_root,
            source=changed,
            business_date="20260730",
            target_date="20260730",
            slot="1200",
            mode="LIVE",
        )


@pytest.mark.parametrize(
    "mutation",
    ["missing_slot", "future_timestamp", "future_published_at"],
)
def test_hourly_runner_rejects_non_point_in_time_source(
    tmp_path: Path, mutation: str
) -> None:
    payload = _source()
    if mutation == "missing_slot":
        payload["source_manifest"].pop("hourly_slot")
    elif mutation == "future_timestamp":
        payload["stock_research_timeline"][0]["last_checked_at"] = (
            "2026-07-30T12:01:00+08:00"
        )
    else:
        payload["source_manifest"]["generated_at"] = (
            "2026-07-30T11:59:00+08:00"
        )
        payload["source_manifest"]["published_at"] = (
            "2026-07-30T13:00:00+08:00"
        )
    source = tmp_path / f"{mutation}.json"
    _write_source(source, payload)

    with pytest.raises(ValueError, match="point-in-time|slot"):
        run_hourly_research_file(
            data_root=tmp_path / "data",
            source=source,
            business_date="20260730",
            target_date="20260730",
            slot="1200",
            mode="REPLAY",
        )


def test_hourly_runner_uses_the_strict_default_owned_input_path(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    source = data_root / "research" / "incoming" / "20260730" / "1200.json"
    source.parent.mkdir(parents=True)
    _write_source(source, _source())

    result = run_hourly_research_file(
        data_root=data_root,
        source=None,
        business_date="20260730",
        target_date="20260730",
        slot="1200",
        mode="LIVE",
    )

    assert result["status"] == "SUCCEEDED"
    assert result["source_path"] == "research/incoming/20260730/1200.json"


def test_rejected_live_latest_regression_writes_no_older_artifact(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.json"
    _write_source(source, _source())
    data_root = tmp_path / "data"
    run_hourly_research_file(
        data_root=data_root,
        source=source,
        business_date="20260730",
        target_date="20260730",
        slot="1200",
        mode="LIVE",
    )
    store = HourlyResearchStore(data_root)
    artifact = store.read_exact("20260730", "1200", mode="LIVE")
    assert artifact is not None

    with pytest.raises(ValueError, match="backwards"):
        store.publish(artifact, slot="0700", mode="LIVE")

    assert store.read_exact("20260730", "0700", mode="LIVE") is None


def test_source_bytes_are_frozen_before_publication(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.json"
    frozen_sha = _write_source(source, _source(title="冻结标题"))
    changed_payload = _source(title="外部并发修改")
    original_publish = HourlyResearchStore.publish

    def mutate_external_source_then_publish(
        self,
        payload,
        *,
        slot,
        mode,
        transformer_identity_sha256=None,
    ):
        _write_source(source, changed_payload)
        return original_publish(
            self,
            payload,
            slot=slot,
            mode=mode,
            transformer_identity_sha256=transformer_identity_sha256,
        )

    monkeypatch.setattr(
        HourlyResearchStore,
        "publish",
        mutate_external_source_then_publish,
    )
    data_root = tmp_path / "data"
    result = run_hourly_research_file(
        data_root=data_root,
        source=source,
        business_date="20260730",
        target_date="20260730",
        slot="1200",
        mode="LIVE",
    )

    assert result["external_source_sha256"] == frozen_sha
    assert result["external_source_read_only"] is True
    artifact = HourlyResearchStore(data_root).read_exact(
        "20260730", "1200", mode="LIVE"
    )
    assert artifact is not None
    assert artifact["articles"][0]["source_title"] == "冻结标题"
    assert hashlib.sha256(source.read_bytes()).hexdigest() != frozen_sha


def test_interrupted_receipt_write_is_recoverable(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.json"
    _write_source(source, _source())
    data_root = tmp_path / "data"
    original_write = HourlyResearchStore._write
    failed = False

    def fail_first_receipt(self, relative, value):
        nonlocal failed
        if not failed and relative.startswith("receipts/research/hourly/"):
            failed = True
            raise OSError("injected receipt failure")
        return original_write(self, relative, value)

    monkeypatch.setattr(HourlyResearchStore, "_write", fail_first_receipt)
    with pytest.raises(OSError, match="injected receipt failure"):
        run_hourly_research_file(
            data_root=data_root,
            source=source,
            business_date="20260730",
            target_date="20260730",
            slot="1200",
            mode="LIVE",
        )
    assert (data_root / "research/hourly/live/20260730/1200.json").is_file()
    assert not (data_root / "research/hourly/latest.json").exists()

    recovered = run_hourly_research_file(
        data_root=data_root,
        source=source,
        business_date="20260730",
        target_date="20260730",
        slot="1200",
        mode="LIVE",
    )
    assert recovered["status"] == "SUCCEEDED"
    assert recovered["latest_updated"] is True
    assert HourlyResearchStore(data_root).read_latest() is not None


def test_transform_validation_failure_never_commits_live_latest(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.json"
    _write_source(source, _source())
    data_root = tmp_path / "data"
    original_write = HourlyResearchStore._write
    failed = False

    def fail_first_transform_validation(self, relative, value):
        nonlocal failed
        if not failed and "/transform-validation/" in relative:
            failed = True
            raise OSError("injected transform validation failure")
        return original_write(self, relative, value)

    monkeypatch.setattr(
        HourlyResearchStore,
        "_write",
        fail_first_transform_validation,
    )
    with pytest.raises(OSError, match="transform validation failure"):
        run_hourly_research_file(
            data_root=data_root,
            source=source,
            business_date="20260730",
            target_date="20260730",
            slot="1200",
            mode="LIVE",
        )

    assert (data_root / "research/hourly/live/20260730/1200.json").is_file()
    assert not (data_root / "research/hourly/latest.json").exists()
    recovered = run_hourly_research_file(
        data_root=data_root,
        source=source,
        business_date="20260730",
        target_date="20260730",
        slot="1200",
        mode="LIVE",
    )
    assert recovered["latest_updated"] is True
    assert HourlyResearchStore(data_root).read_latest() is not None


def test_historical_interrupted_slot_recovers_without_moving_latest(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.json"
    _write_source(source, _source())
    data_root = tmp_path / "data"
    run_hourly_research_file(
        data_root=data_root,
        source=source,
        business_date="20260730",
        target_date="20260730",
        slot="1200",
        mode="REPLAY",
    )
    store = HourlyResearchStore(data_root)
    artifact = store.read_exact("20260730", "1200", mode="REPLAY")
    assert artifact is not None
    original_write = HourlyResearchStore._write
    failed = False

    def fail_first_receipt(self, relative, value):
        nonlocal failed
        if (
            not failed
            and relative
            == "receipts/research/hourly/live/20260730/0700.json"
        ):
            failed = True
            raise OSError("injected historical receipt failure")
        return original_write(self, relative, value)

    monkeypatch.setattr(HourlyResearchStore, "_write", fail_first_receipt)
    with pytest.raises(OSError, match="historical receipt"):
        store.publish(artifact, slot="0700", mode="LIVE")
    assert not (
        data_root / "receipts/research/hourly/live/20260730/0700.json"
    ).exists()

    assert store.publish(artifact, slot="1200", mode="LIVE")[
        "latest_updated"
    ] is True
    recovered = store.publish(artifact, slot="0700", mode="LIVE")

    assert recovered["latest_updated"] is False
    assert store.read_exact("20260730", "0700", mode="LIVE") == artifact
    latest = json.loads(
        (data_root / "research/hourly/latest.json").read_text(encoding="utf-8")
    )
    assert latest["slot"] == "1200"


def test_hourly_runner_module_cli_is_runnable_and_missing_input_is_typed(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.json"
    _write_source(source, _source())
    base = [
        sys.executable,
        "-m",
        "ops.run_hourly_research",
        "--data-root",
        str(tmp_path / "data"),
        "--date",
        "20260730",
        "--target-date",
        "20260730",
        "--slot",
        "1200",
        "--mode",
        "REPLAY",
    ]
    completed = subprocess.run(
        [*base, "--source", str(source)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["status"] == "SUCCEEDED"

    missing = subprocess.run(
        [*base[:-1], "BACKFILL"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert missing.returncode == 2
    assert json.loads(missing.stdout)["status"] == "NOT_MATERIALIZED"
