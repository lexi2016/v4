from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit

import pytest


HANDOFF_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(HANDOFF_DIR))
import activate_runtime_candidate as activation  # noqa: E402


MANIFEST_SHA = "105a17529f35595a34b52a7589df23e6bafb1099de3e6072aeaddab1508094ba"


def test_require_review_accepts_bound_runtime_review_with_independent_identity(tmp_path: Path) -> None:
    receipt = tmp_path / "runtime-review.md"
    receipt.write_text(
        "# Runtime independent review\n"
        "Reviewer: `mapping700_review` (independent from `mapping700_writer`)\n"
        f"Candidate manifest SHA256: `{MANIFEST_SHA}`\n\n"
        "REVIEWED=PASS — focused review passed\n"
        "BEHAVIOR_VERIFIED=PASS — candidate target behavior passed\n",
        encoding="utf-8",
    )

    assert activation.require_review(receipt, MANIFEST_SHA) == hashlib.sha256(
        receipt.read_bytes()
    ).hexdigest()


@pytest.mark.parametrize(
    "contents, expected_error",
    [
        (f"{MANIFEST_SHA}\nREVIEWED=PASS\nBEHAVIOR_VERIFIED=PASS\n", "REVIEW_RECEIPT_FORMAT_INVALID"),
        (json.dumps({"candidate_manifest_sha256": MANIFEST_SHA, "reviewed": "PASS"}),
         "REVIEW_RECEIPT_FORMAT_INVALID"),
        (
            "# Runtime independent review\n"
            "Reviewer: `mapping700_writer` (independent from `mapping700_writer`)\n"
            f"Candidate manifest SHA256: `{MANIFEST_SHA}`\n"
            "REVIEWED=PASS\nBEHAVIOR_VERIFIED=PASS\n",
            "REVIEWER_IDENTITY_NOT_INDEPENDENT",
        ),
        (
            "# Runtime independent review\n"
            "Reviewer: `mapping700_review` (independent from `mapping700_writer`)\n"
            f"Candidate manifest SHA256: `{'0' * 64}`\n"
            "REVIEWED=PASS\nBEHAVIOR_VERIFIED=PASS\n",
            "REVIEW_RECEIPT_CANDIDATE_SHA_MISMATCH",
        ),
        (
            "# Runtime independent review\n"
            "Reviewer: `mapping700_review` (independent from `mapping700_writer`)\n"
            f"Candidate manifest SHA256: `{MANIFEST_SHA}`\n"
            "REVIEWED=FAIL — findings remain\nBEHAVIOR_VERIFIED=PASS\n",
            "REVIEWED_PASS_REQUIRED",
        ),
        (
            "# Runtime independent review\n"
            "Reviewer: `mapping700_review` (independent from `mapping700_writer`)\n"
            f"Candidate manifest SHA256: `{MANIFEST_SHA}`\n"
            "REVIEWED=PASS\nREVIEWED=UNKNOWN\nBEHAVIOR_VERIFIED=PASS\n",
            "REVIEWED_PASS_REQUIRED",
        ),
        (
            "# Runtime independent review\n"
            "Reviewer: `mapping700_review` (independent from `mapping700_writer`)\n"
            f"Candidate manifest SHA256: `{MANIFEST_SHA}`\n"
            "REVIEWED=PASS\nBEHAVIOR_VERIFIED=FAIL — unresolved target behavior\n",
            "BEHAVIOR_VERIFIED_PASS_REQUIRED",
        ),
    ],
)
def test_require_review_rejects_incomplete_or_nonpassing_receipts(
    tmp_path: Path, contents: str, expected_error: str
) -> None:
    receipt = tmp_path / "runtime-review.md"
    receipt.write_text(contents, encoding="utf-8")

    with pytest.raises(RuntimeError, match=expected_error):
        activation.require_review(receipt, MANIFEST_SHA)


def _reviewed_relation() -> dict[str, object]:
    return {
        "relation_id": "R001",
        "source_review_status": "SOURCE_REVIEWED",
        "review_detail_level": "FULL",
        "review_revision": {
            "evidence": [{
                "declared_unresolved_navigation_reference_json": [],
                "evidence_wording_clarifications_json": [],
            }]
        },
    }


def _unprocessed_relation() -> dict[str, object]:
    return {
        "relation_id": "R700",
        "source_review_status": "NOT_PROCESSED",
        "review_detail_level": "SUMMARY",
        "review_revision": None,
    }


def _aggregate_catalog() -> dict[str, object]:
    return {
        "coverage": {"membership_count": 667, "relation_row_count": 1003},
        "review_progress": {
            "source_reviewed_relations": 700,
            "unprocessed_relations": 303,
            "independently_verified_relations": 0,
        },
        "safety": {
            "RESEARCH_ONLY": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    }


class _FakeResponse:
    def __init__(self, data: dict[str, object]):
        self.raw = json.dumps({"data": data}).encode("utf-8")

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.raw


def _install_api_responses(monkeypatch: pytest.MonkeyPatch, *, reviewed: dict[str, object] | None = None,
                           unprocessed: dict[str, object] | None = None) -> None:
    reviewed = _reviewed_relation() if reviewed is None else reviewed
    unprocessed = _unprocessed_relation() if unprocessed is None else unprocessed

    def fake_urlopen(url: str, timeout: int) -> _FakeResponse:
        assert timeout == 3
        query = parse_qs(urlsplit(url).query).get("q", [None])[0]
        if query == "R001":
            data = {"items": [{"relations": [reviewed]}]}
        elif query == "R700":
            data = {"items": [{"relations": [unprocessed]}]}
        else:
            data = _aggregate_catalog()
        return _FakeResponse(data)

    monkeypatch.setattr(activation.urllib.request, "urlopen", fake_urlopen)


def test_check_live_api_checks_aggregate_and_both_exact_target_relations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_api_responses(monkeypatch)

    result = activation.check_live_api()

    assert result["exact_reviewed_rid"] == "R001/FULL/two evidence fields"
    assert result["exact_unprocessed_rid"] == "R700/NOT_PROCESSED/SUMMARY/null"


def test_check_live_api_rejects_r001_without_both_new_evidence_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed = _reviewed_relation()
    reviewed["review_revision"] = {"evidence": [{"declared_unresolved_navigation_reference_json": []}]}
    _install_api_responses(monkeypatch, reviewed=reviewed)

    with pytest.raises(RuntimeError, match="LIVE_R001_REVIEWED_READBACK_MISMATCH"):
        activation.check_live_api()


def test_check_live_api_rejects_r700_if_it_is_not_unprocessed_summary_null(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unprocessed = _unprocessed_relation()
    unprocessed["review_detail_level"] = "FULL"
    _install_api_responses(monkeypatch, unprocessed=unprocessed)

    with pytest.raises(RuntimeError, match="LIVE_R700_UNPROCESSED_READBACK_MISMATCH"):
        activation.check_live_api()
