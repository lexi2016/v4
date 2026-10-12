from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from contracts.research import DEDUPE_KEY_FIELDS, SCHEMA_VERSION
from contracts.research_day_product import EXPECTED_RESEARCH_SLOTS
import ops.collect_hourly_research_input as hourly_input_module
from ops.collect_hourly_research_input import build_hourly_research_input
from ops.materialize_research_day import materialize_research_day
from ops.run_hourly_research import run_hourly_research_file
from infrastructure.research_store import HourlyResearchStore
from infrastructure.manager_input_attestation import PublicationError, _source_bindings


DATE = "20261012"
SLOT = "1700"
STATUS_REL = (
    f"research_module/runtime_outputs/zsxq_hourly/{DATE}/{SLOT}/"
    f"v35_zsxq_hourly_status_{DATE}_{SLOT}.json"
)
RUN_ID = f"{DATE}_{SLOT}00_run1700"
RUN_REL = f"external_sources/zsxq_hourly/{RUN_ID}"
REPO_ROOT = Path(__file__).resolve().parents[1]
COLLECTOR_SCRIPT = REPO_ROOT / "ops" / "collect_hourly_research_input.py"


class _FrozenCollectorDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 10, 12, 18, 0)
        return value.replace(tzinfo=tz) if tz is not None else value


@pytest.fixture(autouse=True)
def _freeze_collector_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hourly_input_module, "datetime", _FrozenCollectorDateTime)


def _write_empty_receipt(
    root: Path,
    *,
    status: str = "READY_EMPTY",
    absolute_run_artifact_paths: bool = False,
) -> Path:
    source_cutoff = "2026-10-12T17:00:59+08:00"
    summary_path = f"{RUN_REL}/zsxq_summary.json"
    fetch_result_path = f"{RUN_REL}/zsxq_recent_topics_fetch_result.json"
    if absolute_run_artifact_paths:
        summary_path = str(root / summary_path)
        fetch_result_path = str(root / fetch_result_path)
    status_payload = {
        "schema_version": "v3_5.zsxq_hourly_delta.v1",
        "source": "zsxq",
        "trade_date": DATE,
        "slot": SLOT,
        "status_path": STATUS_REL,
        "status": status,
        "fetch_ok": True,
        "fetched_at": "2026-10-12T17:00:00+08:00",
        "source_cutoff": source_cutoff,
        "latest_run_id": RUN_ID,
        "topic_count": 0,
        "effective_topic_count": 0,
        "page_count": 2,
        "paths": {
            "run_dir": RUN_REL,
            "summary": summary_path,
            "fetch_result": fetch_result_path,
        },
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    status_path = root / STATUS_REL
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(status_payload), encoding="utf-8")
    run_dir = root / RUN_REL
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "zsxq_summary.json").write_text(
        json.dumps({
            "ok": True,
            "raw_topic_count": 0,
            "effective_topic_count": 0,
            "effective_topics": [],
            "stock_lookup_error": "",
        }),
        encoding="utf-8",
    )
    (run_dir / "zsxq_recent_topics_fetch_result.json").write_text(
        json.dumps({"ok": True, "success": True, "count": 0, "page_count": 2}),
        encoding="utf-8",
    )
    return status_path


def _run_collector_cli(root: Path, *, manual_recovery: bool) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(COLLECTOR_SCRIPT),
        "--data-root",
        str(root),
        "--date",
        DATE,
        "--slot",
        SLOT,
    ]
    if manual_recovery:
        command.append("--manual-recovery")
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        check=False,
        capture_output=True,
        text=True,
    )


def _populated_archive(slot: str) -> dict[str, object]:
    published_at = f"2026-10-12T{slot[:2]}:{slot[2:]}:00+08:00"
    article_id = hashlib.sha256(f"article-{slot}".encode()).hexdigest()
    dedupe_key = hashlib.sha256(f"dedupe-{slot}".encode()).hexdigest()
    return {
        "schema_version": SCHEMA_VERSION,
        "archive_date": DATE,
        "status": "READY",
        "timezone": "Asia/Shanghai",
        "source_input_sha256": hashlib.sha256(f"input-{slot}".encode()).hexdigest(),
        "source_schema_version": "v3_research_lane.v2",
        "source_generated_at": published_at,
        "dedupe_key_fields": list(DEDUPE_KEY_FIELDS),
        "article_count": 1,
        "stock_pool_count": 1,
        "source_counts": {"fixture": 1},
        "articles": [{
            "article_id": article_id,
            "dedupe_key": dedupe_key,
            "archive_date": DATE,
            "stock_code": "000001",
            "stock_name": "平安银行",
            "source_type": "hourly_research",
            "source_name": "test fixture",
            "source_title": "exact slot fixture",
            "source_path_sha256": hashlib.sha256(f"path-{slot}".encode()).hexdigest(),
            "url": f"https://example.test/{slot}",
            "theme": "银行",
            "catalyst": "fixture",
            "evidence_sentence": "可追溯的研究证据。",
            "evidence_level": "L2_MEDIUM",
            "confidence": "MEDIUM",
            "published_at": published_at,
            "collected_at": published_at,
            "first_seen_at": published_at,
            "duplicate_evidence_count": 1,
            "source_dedup_keys": [hashlib.sha256(f"source-{slot}".encode()).hexdigest()],
            "recommendation_status": "RESEARCH_ONLY",
        }],
        "stock_pool": [{
            "stock_code": "000001",
            "stock_name": "平安银行",
            "archive_date": DATE,
            "research_score": 1.0,
            "research_status": "OBSERVED",
            "evidence_count": 1,
            "source_count": 1,
            "strong_evidence_count": 0,
            "medium_evidence_count": 1,
            "weak_evidence_count": 0,
            "source_types": ["hourly_research"],
            "themes": ["银行"],
            "top_catalysts": ["fixture"],
            "first_seen_at": published_at,
            "collected_at": published_at,
            "formal_overlap": False,
            "stage_overlap": False,
            "recommendation_status": "RESEARCH_ONLY",
        }],
        "cannot_confirm": [],
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _recover_empty_slot(root: Path) -> None:
    _write_empty_receipt(root)
    collected = build_hourly_research_input(
        data_root=root, business_date=DATE, slot=SLOT, manual_recovery=True
    )
    assert collected["status"] == "READY_EMPTY"
    result = run_hourly_research_file(
        data_root=root, source=None, business_date=DATE, target_date=DATE,
        slot=SLOT, mode="LIVE",
    )
    assert result["status"] == "SUCCEEDED"


def test_exact_ready_empty_manual_recovery_materializes_with_real_times(tmp_path: Path) -> None:
    status_path = _write_empty_receipt(tmp_path)

    collected = build_hourly_research_input(
        data_root=tmp_path, business_date=DATE, slot=SLOT, manual_recovery=True
    )

    assert collected["status"] == "READY_EMPTY"
    assert collected["execution_origin"] == "MANUAL_RECOVERY"
    assert collected["capture_origin"] == "ORIGINAL_SLOT"
    assert collected["natural_execution_verified"] is False
    incoming = tmp_path / "research/incoming/20261012/1700.json"
    source = json.loads(incoming.read_text(encoding="utf-8"))
    manifest = source["source_manifest"]
    assert manifest["source_receipts"] == [STATUS_REL]
    assert manifest["source_receipt_sha256"] == hashlib.sha256(status_path.read_bytes()).hexdigest()
    run_dir = tmp_path / RUN_REL
    summary_sha = hashlib.sha256((run_dir / "zsxq_summary.json").read_bytes()).hexdigest()
    fetch_sha = hashlib.sha256(
        (run_dir / "zsxq_recent_topics_fetch_result.json").read_bytes()
    ).hexdigest()
    proof = manifest["ready_empty_source_proof"]
    assert proof["summary_sha256"] == summary_sha
    assert proof["fetch_result_sha256"] == fetch_sha
    assert manifest["source_cutoff"] == "2026-10-12T17:00:59+08:00"
    assert manifest["fetched_at"] == "2026-10-12T17:00:00+08:00"
    assert manifest["materialized_at"] == manifest["published_at"]
    assert manifest["available_at"] == manifest["materialized_at"]
    assert manifest["natural_execution_verified"] is False
    assert manifest["published_at"] >= "2026-10-12T17:00:59+08:00"

    result = run_hourly_research_file(
        data_root=tmp_path,
        source=None,
        business_date=DATE,
        target_date=DATE,
        slot=SLOT,
        mode="LIVE",
    )

    assert result["status"] == "SUCCEEDED"
    assert result["hourly_artifact_status"] == "READY_EMPTY"
    assert result["execution_origin"] == "MANUAL_RECOVERY"
    assert result["capture_origin"] == "ORIGINAL_SLOT"
    assert result["natural_execution_verified"] is False
    assert result["available_at"] == result["materialized_at"]
    assert result["summary_sha256"] == summary_sha
    assert result["fetch_result_sha256"] == fetch_sha
    assert result["article_count"] == 0
    assert result["stock_pool_count"] == 0
    archive = HourlyResearchStore(tmp_path).read_exact(DATE, SLOT, mode="LIVE")
    assert archive is not None
    assert archive["ready_empty_evidence_v1"]["source_receipt_sha256"] == hashlib.sha256(
        status_path.read_bytes()
    ).hexdigest()
    assert archive["ready_empty_evidence_v1"]["summary_sha256"] == summary_sha
    assert archive["ready_empty_evidence_v1"]["fetch_result_sha256"] == fetch_sha


def test_ready_empty_reader_uses_exact_status_not_collector_latest_picker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _recover_empty_slot(tmp_path)
    monkeypatch.setattr(
        hourly_input_module,
        "_latest_zsxq_status",
        lambda *_args, **_kwargs: pytest.fail("reader must inspect the exact status path"),
    )

    archive = HourlyResearchStore(tmp_path).read_exact(DATE, SLOT, mode="LIVE")

    assert archive is not None
    assert archive["ready_empty_evidence_v1"]["source_input_sha256"] == archive[
        "source_input_sha256"
    ]


def test_collector_cli_returns_zero_for_exact_ready_empty_manual_recovery(tmp_path: Path) -> None:
    _write_empty_receipt(tmp_path)

    completed = _run_collector_cli(tmp_path, manual_recovery=True)

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["status"] == "READY_EMPTY"


def test_collector_cli_returns_nonzero_when_source_is_missing(tmp_path: Path) -> None:
    completed = _run_collector_cli(tmp_path, manual_recovery=True)

    assert completed.returncode != 0
    assert json.loads(completed.stdout)["status"] == "INPUT_MISSING"


def test_absolute_run_artifact_paths_inside_owned_root_are_accepted(tmp_path: Path) -> None:
    _write_empty_receipt(tmp_path, absolute_run_artifact_paths=True)
    collected = build_hourly_research_input(
        data_root=tmp_path, business_date=DATE, slot=SLOT, manual_recovery=True
    )
    result = run_hourly_research_file(
        data_root=tmp_path,
        source=None,
        business_date=DATE,
        target_date=DATE,
        slot=SLOT,
        mode="LIVE",
        expected_source_sha256=collected["source_sha256"],
    )

    assert result["status"] == "SUCCEEDED"
    assert HourlyResearchStore(tmp_path).read_exact(DATE, SLOT, mode="LIVE") is not None


@pytest.mark.parametrize(
    "summary_path",
    [
        "__outside_root__",
        "external_sources/zsxq_hourly/20261012_170000_other/zsxq_summary.json",
        f"{RUN_REL}/../../outside/zsxq_summary.json",
    ],
    ids=("root-outside", "cross-run", "path-traversal"),
)
def test_ready_empty_source_rejects_non_owned_run_artifact_paths(
    tmp_path: Path, summary_path: str
) -> None:
    status_path = _write_empty_receipt(tmp_path)
    collected = build_hourly_research_input(
        data_root=tmp_path, business_date=DATE, slot=SLOT, manual_recovery=True
    )
    run_hourly_research_file(
        data_root=tmp_path,
        source=None,
        business_date=DATE,
        target_date=DATE,
        slot=SLOT,
        mode="LIVE",
        expected_source_sha256=collected["source_sha256"],
    )
    archive = HourlyResearchStore(tmp_path).read_exact(DATE, SLOT, mode="LIVE")
    assert archive is not None

    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["paths"]["summary"] = (
        str(tmp_path.parent / "outside-root" / "zsxq_summary.json")
        if summary_path == "__outside_root__"
        else summary_path
    )
    status_path.write_text(json.dumps(status), encoding="utf-8")
    with pytest.raises(ValueError):
        HourlyResearchStore(tmp_path).read_exact(DATE, SLOT, mode="LIVE")


def test_empty_without_manual_recovery_is_not_materialized(tmp_path: Path) -> None:
    _write_empty_receipt(tmp_path)

    result = build_hourly_research_input(
        data_root=tmp_path, business_date=DATE, slot=SLOT
    )

    assert result["status"] == "INPUT_MISSING"
    assert not (tmp_path / "research/incoming/20261012/1700.json").exists()


@pytest.mark.parametrize("artifact_name", ["zsxq_summary.json", "zsxq_recent_topics_fetch_result.json"])
def test_runner_rejects_changed_run_artifact_sha(tmp_path: Path, artifact_name: str) -> None:
    _write_empty_receipt(tmp_path)
    build_hourly_research_input(
        data_root=tmp_path, business_date=DATE, slot=SLOT, manual_recovery=True
    )
    artifact = tmp_path / RUN_REL / artifact_name
    value = json.loads(artifact.read_text(encoding="utf-8"))
    value["runner_tamper"] = True
    artifact.write_text(json.dumps(value), encoding="utf-8")

    result = run_hourly_research_file(
        data_root=tmp_path, source=None, business_date=DATE, target_date=DATE,
        slot=SLOT, mode="LIVE",
    )

    assert result["status"] == "NOT_MATERIALIZED"
    assert result["hourly_artifact_status"] == "NOT_MATERIALIZED"
    assert not (tmp_path / f"research/hourly/live/{DATE}/{SLOT}.json").exists()


def test_publication_attestation_reconciles_exact_ready_empty_proof(tmp_path: Path) -> None:
    _write_empty_receipt(tmp_path)
    build_hourly_research_input(
        data_root=tmp_path, business_date=DATE, slot=SLOT, manual_recovery=True
    )
    manifest = json.loads(
        (tmp_path / "research/incoming/20261012/1700.json").read_text(encoding="utf-8")
    )["source_manifest"]

    available_at = datetime.now(ZoneInfo("Asia/Shanghai"))
    bindings = _source_bindings(tmp_path, manifest, available_at)

    assert bindings == [{"artifact_ref": STATUS_REL, "sha256": manifest["source_receipt_sha256"]}]
    tampered = {**manifest, "ready_empty_source_proof": {
        **manifest["ready_empty_source_proof"], "page_count": 3,
    }}
    with pytest.raises(PublicationError, match="READY_EMPTY_PROOF_INVALID"):
        _source_bindings(tmp_path, tampered, available_at)

    for artifact_name in ("zsxq_summary.json", "zsxq_recent_topics_fetch_result.json"):
        root = tmp_path / artifact_name.replace(".", "-")
        _write_empty_receipt(root)
        build_hourly_research_input(
            data_root=root, business_date=DATE, slot=SLOT, manual_recovery=True
        )
        artifact = root / RUN_REL / artifact_name
        value = json.loads(artifact.read_text(encoding="utf-8"))
        value["attestation_tamper"] = True
        artifact.write_text(json.dumps(value), encoding="utf-8")
        source_manifest = json.loads(
            (root / "research/incoming/20261012/1700.json").read_text(encoding="utf-8")
        )["source_manifest"]
        with pytest.raises(PublicationError, match="SOURCE_RECEIPT_INVALID|READY_EMPTY_PROOF_INVALID"):
            _source_bindings(root, source_manifest, available_at)


def test_missing_archive_source_proof_and_changed_receipts_are_rejected(tmp_path: Path) -> None:
    _write_empty_receipt(tmp_path)
    build_hourly_research_input(
        data_root=tmp_path, business_date=DATE, slot=SLOT, manual_recovery=True
    )
    incoming = tmp_path / "research/incoming/20261012/1700.json"
    source = json.loads(incoming.read_text(encoding="utf-8"))
    source["source_manifest"].pop("ready_empty_source_proof")
    incoming.write_text(json.dumps(source), encoding="utf-8")

    unverified = run_hourly_research_file(
        data_root=tmp_path, source=None, business_date=DATE, target_date=DATE,
        slot=SLOT, mode="LIVE",
    )
    assert unverified["status"] == "NOT_MATERIALIZED"
    assert not (tmp_path / f"research/hourly/live/{DATE}/{SLOT}.json").exists()

    _recover_empty_slot(tmp_path / "physical-receipt")
    receipt = tmp_path / "physical-receipt" / STATUS_REL
    value = json.loads(receipt.read_text(encoding="utf-8"))
    value["extra_after_materialization"] = True
    receipt.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="ready-empty"):
        HourlyResearchStore(tmp_path / "physical-receipt").read_exact(
            DATE, SLOT, mode="LIVE"
        )

    for artifact_name in ("zsxq_summary.json", "zsxq_recent_topics_fetch_result.json"):
        artifact_root = tmp_path / artifact_name.replace(".", "-")
        _recover_empty_slot(artifact_root)
        artifact = artifact_root / RUN_REL / artifact_name
        value = json.loads(artifact.read_text(encoding="utf-8"))
        value["post_publication_tamper"] = True
        artifact.write_text(json.dumps(value), encoding="utf-8")
        with pytest.raises(ValueError, match="ready-empty"):
            HourlyResearchStore(artifact_root).read_exact(DATE, SLOT, mode="LIVE")


def test_exact_empty_slot_is_usable_in_complete_day_product(tmp_path: Path) -> None:
    store = HourlyResearchStore(tmp_path)
    for slot in EXPECTED_RESEARCH_SLOTS:
        if slot != SLOT:
            store.publish(_populated_archive(slot), slot=slot, mode="LIVE")
    _recover_empty_slot(tmp_path)

    result = materialize_research_day(tmp_path, DATE)

    assert result["coverage"]["ready_slots"] == len(EXPECTED_RESEARCH_SLOTS)
    assert result["coverage"]["missing_slots"] == []
    empty_slot = next(row for row in result["coverage"]["slot_matrix"] if row["slot"] == SLOT)
    assert empty_slot["raw_rows"] == 0
    assert empty_slot["exact_rows"] == 0

    receipt = tmp_path / STATUS_REL
    value = json.loads(receipt.read_text(encoding="utf-8"))
    value["post_day_product_tamper"] = True
    receipt.write_text(json.dumps(value), encoding="utf-8")
    blocked = materialize_research_day(tmp_path, DATE)
    assert blocked["status"] == "NOT_MATERIALIZED"
    assert "HOURLY_SLOT_INVALID:1700" in blocked["cannot_confirm"]


@pytest.mark.parametrize("tamper", ["cross_slot", "bad_summary", "failed_fetch", "cross_day"])
def test_invalid_empty_source_never_admitted(tmp_path: Path, tamper: str) -> None:
    status_path = _write_empty_receipt(tmp_path)
    if tamper == "cross_slot":
        status_path.unlink()
        prior = tmp_path / (
            "research_module/runtime_outputs/zsxq_hourly/20261012/1600/"
            "v35_zsxq_hourly_status_20261012_1600.json"
        )
        prior.parent.mkdir(parents=True, exist_ok=True)
        prior.write_text(json.dumps({"trade_date": DATE, "slot": "1600", "status": "READY", "fetch_ok": True}), encoding="utf-8")
    elif tamper == "bad_summary":
        (tmp_path / RUN_REL / "zsxq_summary.json").write_text(
            json.dumps({"ok": True, "raw_topic_count": 0, "effective_topic_count": 1, "effective_topics": [{"id": "x"}], "stock_lookup_error": ""}),
            encoding="utf-8",
        )
    elif tamper == "failed_fetch":
        (tmp_path / RUN_REL / "zsxq_recent_topics_fetch_result.json").write_text(
            json.dumps({"ok": False, "success": False, "count": 0, "page_count": 2}),
            encoding="utf-8",
        )
    else:
        value = json.loads(status_path.read_text(encoding="utf-8"))
        value["fetched_at"] = "2026-10-13T00:30:00+08:00"
        status_path.write_text(json.dumps(value), encoding="utf-8")

    result = build_hourly_research_input(
        data_root=tmp_path, business_date=DATE, slot=SLOT, manual_recovery=True
    )

    assert result["status"] == "INPUT_MISSING"
    assert not (tmp_path / "research/incoming/20261012/1700.json").exists()
