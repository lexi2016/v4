"""Regression coverage for the witness-bound 2026-09-30 Stage projection.

The original source and archive stay in the configured research store. This
test reads those files in place and does not copy or rewrite market data.
"""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from domains.research import build_research_archive
from stage_center.research_context import (
    ResearchContextError,
    _apply_exact_v4_20260930_1400_role_warning_projection,
    _payload_base_sha,
    load_research_context,
)


_WITNESS = Path(
    "/Users/lexi/Desktop/学习/agents调试/v4_stage_root_hk_fix_20260928/"
    "line_fix_r1/pr16_unified_20261001/a1445/"
    "a1445_20260930_1400_projection_witness.json"
)
_CONFIG = Path(
    "/Users/lexi/Desktop/学习/agents调试/v4_stage_root_hk_fix_20260928/"
    "line_fix_r1/today_combined_stage_fix_20260930/candidate/app/"
    "stage_center_tick_config.json"
)
_SOURCE_SHA256 = "4076de79920c43cfa57336c23262a491cd77730f29b4e1a530bc5ed9836ef571"
_ARCHIVE_SHA256 = "811b7803b540ec22c8e3f061804229e59fa51179f20a55a56ccc12d946af4af0"


@pytest.fixture(scope="module")
def originals() -> tuple[dict, dict, Path, Path]:
    if not _WITNESS.is_file() or not _CONFIG.is_file():
        pytest.skip("witness-bound 2026-09-30 original research store is unavailable")
    witness = json.loads(_WITNESS.read_text(encoding="utf-8"))
    config = json.loads(_CONFIG.read_text(encoding="utf-8"))
    root = Path(config["v4_research_data_root"])
    news_root = Path(config["v4_morning_news_root"])
    source_path = root / witness["originals"]["source"]["root_relative_path"]
    archive_path = root / witness["originals"]["archive"]["root_relative_path"]
    assert source_path.is_file()
    assert archive_path.is_file()
    source_bytes = source_path.read_bytes()
    archive_bytes = archive_path.read_bytes()
    assert hashlib.sha256(source_bytes).hexdigest() == _SOURCE_SHA256
    assert hashlib.sha256(archive_bytes).hexdigest() == _ARCHIVE_SHA256
    source = json.loads(source_bytes.decode("utf-8-sig"))
    archive = json.loads(archive_bytes.decode("utf-8-sig"))
    return source, archive, root, news_root


def test_exact_projection_reconstructs_archived_role_warnings(originals) -> None:
    source, archive, _root, _news_root = originals
    rebuilt = build_research_archive(source, source_input_sha256=_SOURCE_SHA256)
    assert _payload_base_sha(rebuilt) == _payload_base_sha(archive)
    compatible, evidence = _apply_exact_v4_20260930_1400_role_warning_projection(
        rebuilt,
        source,
        archive,
        trade_date="20260930",
        slot="1400",
        source_input_sha256=_SOURCE_SHA256,
    )
    assert _payload_base_sha(compatible) == _payload_base_sha(archive)
    assert compatible["cannot_confirm"] == archive["cannot_confirm"]
    assert "v4_hourly_archive_projection_compat_warning_count=27" in evidence
    assert "v4_hourly_source_capture_origin=LATE_RECOVERY" in evidence
    assert "v4_hourly_source_natural_execution_verified=false" in evidence


def test_exact_projection_refuses_other_slots_for_pinned_source(originals) -> None:
    source, archive, _root, _news_root = originals
    rebuilt = build_research_archive(source, source_input_sha256=_SOURCE_SHA256)
    with pytest.raises(ValueError, match="SOURCE_DATE_SLOT_MISMATCH"):
        _apply_exact_v4_20260930_1400_role_warning_projection(
            rebuilt,
            source,
            archive,
            trade_date="20260930",
            slot="1500",
            source_input_sha256=_SOURCE_SHA256,
        )


def test_20260930_1500_cutoff_uses_verified_1400_archive_and_marks_late_recovery(
    originals,
) -> None:
    _source, _archive, root, news_root = originals
    try:
        context = load_research_context(
            root,
            trade_date="20260930",
            stage_cutoff="15:00:00",
            morning_root=news_root,
        )
    except ResearchContextError as error:
        pytest.fail(f"witness-bound 1400 projection should load: {error}")
    assert context.selected_slot == "1400"
    assert any(
        item == f"v4_hourly_source_witness_sha256={_SOURCE_SHA256}"
        for item in context.source_evidence
    )
    assert "v4_hourly_archive_projection_compat_warning_count=27" in context.source_evidence
    assert "v4_hourly_source_capture_origin=LATE_RECOVERY" in context.source_evidence
    assert "v4_hourly_source_natural_execution_verified=false" in context.source_evidence
    assert any(
        item.startswith("v4_hourly_pit_rejected_slots=1500:")
        and "15:00:02" in item
        for item in context.source_evidence
    )


def test_report_role_audit_projects_generically_only_when_source_and_receipt_bind() -> None:
    trade_date = "20261010"
    slot = "1300"
    receipt_path = (
        "research_module/runtime_outputs/zsxq_hourly/20261010/1300/"
        "v35_zsxq_hourly_status_20261010_1300.json"
    )
    source = {
        "schema_version": "v3_research_lane.v2",
        "trade_date": trade_date,
        "slot": slot,
        "source_manifest": {
            "trade_date": trade_date,
            "hourly_slot": slot,
            "published_at": "2026-10-10T13:00:02+08:00",
            "source_receipts": [receipt_path],
        },
        "stock_research_timeline": [
            {
                "stock_code": "000001",
                "stock_name": "平安银行",
                "event_time": "2026-10-10T13:00:00+08:00",
                "source_published_at": "2026-10-10T12:55:00+08:00",
                "first_seen_at": "2026-10-10T12:55:00+08:00",
                "last_checked_at": "2026-10-10T13:00:00+08:00",
                "source_type": "hourly_research",
                "source_name": "小时研报",
                "source_title": "测试报告",
                "source_path": receipt_path,
                "url": "https://example.test/report",
                "evidence_level": "L2_MEDIUM",
                "confidence": "MEDIUM",
            }
        ],
        "stock_research_daily": [
            {
                "stock_code": "000001",
                "stock_name": "平安银行",
                "first_seen_time": "2026-10-10T12:55:00+08:00",
                "last_seen_time": "2026-10-10T13:00:00+08:00",
                "research_score": 50,
                "research_status": "REPEATED",
                "evidence_count": 1,
                "source_count": 1,
                "strong_evidence_count": 0,
                "medium_evidence_count": 1,
                "weak_evidence_count": 0,
                "source_types": ["hourly_research"],
                "themes": [],
                "top_catalysts": [],
            }
        ],
        "research_pool_bridge": [],
        "cannot_confirm": [],
        "report_entity_audit": {
            "policy_version": "report_subject_scoring.v1",
            "affected_codes": ["000001"],
            "excluded_evidence_count": 1,
            "excluded_evidence": [
                {
                    "entity_role": "REPORT_PUBLISHER",
                    "evidence_id": "audit-evidence-000001",
                    "research_subject_eligible": False,
                    "source_path": receipt_path,
                    "stock_code": "000001",
                }
            ],
        },
    }
    source_bytes = json.dumps(
        source, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    payload = build_research_archive(source, source_input_sha256=source_sha)
    without_audit = {key: value for key, value in source.items() if key != "report_entity_audit"}
    baseline = build_research_archive(without_audit, source_input_sha256=source_sha)

    warning = "REPORT_ROLE_EVIDENCE_EXCLUDED:000001"
    assert set(payload["cannot_confirm"]) - set(baseline["cannot_confirm"]) == {warning}
    for key in ("articles", "stock_pool", "source_counts", "write_policy", "recommendation_status"):
        assert payload[key] == baseline[key]

    unbound = {**source, "report_entity_audit": {**source["report_entity_audit"]}}
    unbound["report_entity_audit"]["excluded_evidence"] = [
        {**source["report_entity_audit"]["excluded_evidence"][0], "source_path": "other/source.json"}
    ]
    with pytest.raises(ValueError, match="REPORT_ROLE_AUDIT_EXCLUDED_EVIDENCE_INVALID"):
        build_research_archive(unbound, source_input_sha256=source_sha)
