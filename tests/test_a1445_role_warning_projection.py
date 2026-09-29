from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest


APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

SOURCE_SHA = "5af979bc7a00fb48547ce1bf160622a2202885165b833baea35961481a13d34d"
ARCHIVE_BASE_SHA = "c930018edb379e3863619918b97291f97cdfc6546e8222c2aff1039eea2570d1"
SOURCE_DATA_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/research/hourly"
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def a1445_projection_inputs():
    source_path = SOURCE_DATA_ROOT / "source" / f"{SOURCE_SHA}.json"
    archive_path = SOURCE_DATA_ROOT / "live" / "20260928" / "1400.json"
    if not source_path.is_file() or not archive_path.is_file():
        pytest.skip("exact A1445 source/archive witness is not installed on this host")

    source = _read_json(source_path)
    payload = _read_json(archive_path)
    from domains.research import build_research_archive
    from stage_center import research_context as research_context

    projected = build_research_archive(
        copy.deepcopy(source), source_input_sha256=SOURCE_SHA,
    )
    return research_context, source, payload, projected


def test_exact_source_pair_restores_all_27_and_only_those_warnings(a1445_projection_inputs):
    rc, source, payload, projected = a1445_projection_inputs
    compatible, evidence = rc._apply_exact_v35_role_warning_projection(
        projected, source, payload,
        trade_date="20260928", slot="1400", source_input_sha256=SOURCE_SHA,
    )

    assert rc._payload_base_sha(compatible) == ARCHIVE_BASE_SHA
    assert compatible == payload
    assert sum(
        item.startswith("REPORT_ROLE_EVIDENCE_EXCLUDED:")
        for item in compatible["cannot_confirm"]
    ) == 27
    assert len(evidence) == 5
    assert "v4_hourly_archive_projection_compat_warning_count=27" in evidence


def test_other_source_scope_receives_no_compatibility(a1445_projection_inputs):
    rc, source, payload, projected = a1445_projection_inputs
    compatible, evidence = rc._apply_exact_v35_role_warning_projection(
        projected, source, payload,
        trade_date="20260928", slot="1400", source_input_sha256="0" * 64,
    )

    assert compatible == projected
    assert evidence == ()


def test_wrong_report_policy_identity_fails_closed(a1445_projection_inputs):
    rc, source, payload, projected = a1445_projection_inputs
    altered = copy.deepcopy(source)
    altered["source_manifest"]["report_subject_policy_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="SOURCE_IDENTITY_MISMATCH:report_subject_policy_sha256"):
        rc._apply_exact_v35_role_warning_projection(
            projected, altered, payload,
            trade_date="20260928", slot="1400", source_input_sha256=SOURCE_SHA,
        )


def test_inconsistent_audit_codes_fail_closed(a1445_projection_inputs):
    rc, source, payload, projected = a1445_projection_inputs
    altered = copy.deepcopy(source)
    altered["report_entity_audit"]["affected_codes"][0] = "999999"

    with pytest.raises(ValueError, match="AFFECTED_CODE_AUDIT_MISMATCH"):
        rc._apply_exact_v35_role_warning_projection(
            projected, altered, payload,
            trade_date="20260928", slot="1400", source_input_sha256=SOURCE_SHA,
        )


def test_wrong_archive_base_sha_fails_closed(a1445_projection_inputs):
    rc, source, payload, projected = a1445_projection_inputs
    altered = copy.deepcopy(payload)
    altered["cannot_confirm"].append("REPORT_ROLE_EVIDENCE_EXCLUDED:999999")

    with pytest.raises(ValueError, match="ARCHIVE_BASE_SHA_MISMATCH"):
        rc._apply_exact_v35_role_warning_projection(
            projected, source, altered,
            trade_date="20260928", slot="1400", source_input_sha256=SOURCE_SHA,
        )
