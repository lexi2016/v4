from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from infrastructure.research_source_evidence import read_zsxq_slot_evidence


DATE = "20261012"
SLOT = "1700"
STATUS_REL = (
    f"research_module/runtime_outputs/zsxq_hourly/{DATE}/{SLOT}/"
    f"v35_zsxq_hourly_status_{DATE}_{SLOT}.json"
)
RUN_ID = f"{DATE}_{SLOT}00_run1700"
RUN_REL = f"external_sources/zsxq_hourly/{RUN_ID}"


def _write_ready_empty(root: Path, *, absolute_paths: bool = False) -> dict[Path, bytes]:
    summary_relative = f"{RUN_REL}/zsxq_summary.json"
    fetch_relative = f"{RUN_REL}/zsxq_recent_topics_fetch_result.json"
    summary_path = str(root / summary_relative) if absolute_paths else summary_relative
    fetch_path = str(root / fetch_relative) if absolute_paths else fetch_relative
    status = {
        "schema_version": "v3_5.zsxq_hourly_delta.v1",
        "source": "zsxq",
        "trade_date": DATE,
        "slot": SLOT,
        "status_path": STATUS_REL,
        "status": "READY_EMPTY",
        "fetch_ok": True,
        "fetched_at": "2026-10-12T17:00:00+08:00",
        "source_cutoff": "2026-10-12T17:00:59+08:00",
        "latest_run_id": RUN_ID,
        "topic_count": 0,
        "effective_topic_count": 0,
        "page_count": 2,
        "paths": {
            "run_dir": RUN_REL,
            "summary": summary_path,
            "fetch_result": fetch_path,
        },
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    summary = {
        "ok": True,
        "raw_topic_count": 0,
        "effective_topic_count": 0,
        "effective_topics": [],
        "stock_lookup_error": "",
    }
    fetch = {"ok": True, "success": True, "count": 0, "page_count": 2}
    files = {
        root / STATUS_REL: json.dumps(status, sort_keys=True).encode(),
        root / summary_relative: json.dumps(summary, sort_keys=True).encode(),
        root / fetch_relative: json.dumps(fetch, sort_keys=True).encode(),
    }
    for path, raw in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return files


def test_reader_hashes_the_exact_three_single_read_byte_sequences(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = _write_ready_empty(tmp_path, absolute_paths=True)
    original_read_bytes = Path.read_bytes
    reads: dict[Path, int] = {}

    def count_reads(path: Path) -> bytes:
        if path in files:
            reads[path] = reads.get(path, 0) + 1
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", count_reads)
    evidence = read_zsxq_slot_evidence(tmp_path, DATE, SLOT)

    assert evidence is not None
    assert evidence.status_path == tmp_path / STATUS_REL
    assert evidence.status["status"] == "READY_EMPTY"
    assert evidence.summary["effective_topics"] == []
    assert evidence.fetch_result["success"] is True
    assert evidence.status_sha256 == hashlib.sha256(files[tmp_path / STATUS_REL]).hexdigest()
    assert evidence.summary_sha256 == hashlib.sha256(files[tmp_path / f"{RUN_REL}/zsxq_summary.json"]).hexdigest()
    assert evidence.fetch_result_sha256 == hashlib.sha256(files[tmp_path / f"{RUN_REL}/zsxq_recent_topics_fetch_result.json"]).hexdigest()
    assert reads == {path: 1 for path in files}


@pytest.mark.parametrize(
    "field,value",
    [
        ("summary", "external_sources/zsxq_hourly/other/zsxq_summary.json"),
        ("summary", f"{RUN_REL}/../../outside/zsxq_summary.json"),
        ("run_dir", f"external_sources/zsxq_hourly/{DATE}_{SLOT}00_other"),
    ],
)
def test_reader_rejects_outside_traversal_and_cross_run_paths(
    tmp_path: Path, field: str, value: str
) -> None:
    files = _write_ready_empty(tmp_path)
    status_path = tmp_path / STATUS_REL
    status = json.loads(files[status_path])
    status["paths"][field] = value
    status_path.write_text(json.dumps(status), encoding="utf-8")

    assert read_zsxq_slot_evidence(tmp_path, DATE, SLOT) is None


def test_reader_rejects_status_date_mismatch(tmp_path: Path) -> None:
    files = _write_ready_empty(tmp_path)
    status_path = tmp_path / STATUS_REL
    status = json.loads(files[status_path])
    status["trade_date"] = "20261013"
    status_path.write_text(json.dumps(status), encoding="utf-8")

    assert read_zsxq_slot_evidence(tmp_path, DATE, SLOT) is None


def test_reader_accepts_a_complete_ready_status_with_matching_counts(
    tmp_path: Path,
) -> None:
    files = _write_ready_empty(tmp_path)
    status_path = tmp_path / STATUS_REL
    status = json.loads(files[status_path])
    status.update(status="READY", topic_count=1, effective_topic_count=1)
    status_path.write_text(json.dumps(status), encoding="utf-8")
    summary_path = tmp_path / f"{RUN_REL}/zsxq_summary.json"
    summary = json.loads(files[summary_path])
    summary.update(
        raw_topic_count=1,
        effective_topic_count=1,
        effective_topics=[{"topic_id": "12345678901234567"}],
    )
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    fetch_path = tmp_path / f"{RUN_REL}/zsxq_recent_topics_fetch_result.json"
    fetch = json.loads(files[fetch_path])
    fetch.update(count=1)
    fetch_path.write_text(json.dumps(fetch), encoding="utf-8")

    evidence = read_zsxq_slot_evidence(tmp_path, DATE, SLOT)

    assert evidence is not None
    assert evidence.status["status"] == "READY"
    assert evidence.status["topic_count"] == evidence.summary["raw_topic_count"] == 1
    assert evidence.fetch_result["count"] == 1
