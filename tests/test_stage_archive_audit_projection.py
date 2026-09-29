"""Synthetic source witnesses and full-object comparisons, not Mac archive evidence."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json

import pytest

from domains.research import build_research_archive
from stage_center.research_context import _bound_source_rows, ResearchContextError


def source():
    return {"schema_version": "v3_research_lane.v2", "trade_date": "20260928",
        "source_manifest": {"generated_at": "2026-09-28T14:00:00+08:00", "hourly_slot": "1400",
            "manifest_sha256": "b" * 64, "receipt_sha256": "c" * 64},
        "stock_research_timeline": [{"stock_code": "600000", "stock_name": "SYNTHETIC",
            "event_time": "2026-09-28T14:00:00+08:00", "source_type": "synthetic",
            "source_title": "SYNTHETIC CONTRACT ONLY", "source_path": "synthetic/source.json",
            "source_published_at": "2026-09-28T13:00:00+08:00",
            "first_seen_at": "2026-09-28T13:01:00+08:00",
            "last_checked_at": "2026-09-28T14:00:00+08:00"}],
        "stock_research_daily": [{"stock_code": "600000", "stock_name": "SYNTHETIC",
            "first_seen_time": "2026-09-28T13:01:00+08:00",
            "last_seen_time": "2026-09-28T14:00:00+08:00", "research_score": 20}],
        "research_pool_bridge": [],
        "cannot_confirm": []}


def seal(root, data):
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    sha = hashlib.sha256(raw).hexdigest()
    path = root / "research" / "hourly" / "source" / f"{sha}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return sha, path


def test_report_audit_reproduces_full_archive_not_a_sha_specific_exception(tmp_path):
    clean = source()
    expected = build_research_archive(clean, source_input_sha256="a" * 64)
    clean["report_entity_audit"] = {"affected_codes": [f"{i:06d}" for i in range(27)]}
    sha, _ = seal(tmp_path, clean)
    expected["source_input_sha256"] = sha
    expected["cannot_confirm"] = [f"REPORT_ROLE_EVIDENCE_EXCLUDED:{i:06d}" for i in range(27)]
    assert build_research_archive(clean, source_input_sha256=sha) == expected
    _, evidence = _bound_source_rows(tmp_path, payload=expected,
        paths={"source_input_sha256": sha}, trade_date="20260928", slot="1400",
        cutoff=datetime.fromisoformat("2026-09-28T15:00:00+08:00"))
    assert f"v4_hourly_source_witness_sha256={sha}" in evidence


def test_projection_never_ignores_other_cannot_confirm_differences(tmp_path):
    data = source()
    sha, _ = seal(tmp_path, data)
    payload = build_research_archive(data, source_input_sha256=sha)
    payload["cannot_confirm"].append("UNPROVEN_WARNING")
    with pytest.raises(ResearchContextError, match="SOURCE_ARCHIVE_PROJECTION_SHA_MISMATCH"):
        _bound_source_rows(tmp_path, payload=payload, paths={"source_input_sha256": sha},
            trade_date="20260928", slot="1400", cutoff=datetime.fromisoformat("2026-09-28T15:00:00+08:00"))


def test_witness_sha_is_still_required(tmp_path):
    data = source()
    sha, path = seal(tmp_path, data)
    payload = build_research_archive(data, source_input_sha256=sha)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ResearchContextError, match="SHA_MISMATCH"):
        _bound_source_rows(tmp_path, payload=payload, paths={"source_input_sha256": sha},
            trade_date="20260928", slot="1400", cutoff=datetime.fromisoformat("2026-09-28T15:00:00+08:00"))


def test_after_150000_witness_remains_illegal(tmp_path):
    data = source()
    data["source_manifest"].update(generated_at="2026-09-28T15:00:02+08:00", hourly_slot="1500")
    sha, _ = seal(tmp_path, data)
    payload = build_research_archive(data, source_input_sha256=sha)
    with pytest.raises(ResearchContextError):
        _bound_source_rows(tmp_path, payload=payload, paths={"source_input_sha256": sha},
            trade_date="20260928", slot="1500", cutoff=datetime.fromisoformat("2026-09-28T15:00:00+08:00"))


@pytest.mark.parametrize("audit", [None, [], {"affected_codes": None}, {"affected_codes": "600000"},
                                     {"affected_codes": [True]}, {"affected_codes": ["../bad"]}])
def test_malformed_declared_audit_is_not_silently_ignored(audit):
    data = source()
    data["report_entity_audit"] = audit
    with pytest.raises(ValueError):
        build_research_archive(data, source_input_sha256="a" * 64)
