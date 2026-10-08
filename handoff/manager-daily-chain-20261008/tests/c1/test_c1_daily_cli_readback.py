from __future__ import annotations

import sys
from types import SimpleNamespace
from pathlib import Path
import json

import pytest

API_ROOT = Path(__file__).resolve().parents[1] / "release" / "api_app"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from ops import run_manager_daily_announcement as cli
from v4.manager_research.workspace_projection import FLAGS, digest


def _owner_receipt(*, target: str, publication: str, product_sha: str) -> dict:
    receipt = {
        "schema_version": "v4.manager_research.announcement_analysis_owner_import.v1",
        "status": "VERIFIED",
        "target_trade_date": target,
        "publication_date": publication,
        "product_sha256": product_sha,
        "parent_task_id": "offline-test",
        "parent_run_id": "offline-test-run",
        "available_at": "2026-10-08T00:00:00+00:00",
        "owner": "ManagerResearchJobService.import_announcement_analysis",
        **FLAGS,
    }
    receipt["sha256"] = digest(receipt)
    return receipt


def _readback_result(*, target: str, publication: str, receipt_target: str | None = None,
                     receipt_publication: str | None = None) -> dict:
    product_sha = "a" * 64
    return {
        "target_trade_date": target,
        "publication_date": publication,
        "analysis": {"status": "VERIFIED", "product_sha256": product_sha},
        "owner_import_receipt": _owner_receipt(
            target=receipt_target or target,
            publication=receipt_publication or publication,
            product_sha=product_sha,
        ),
    }


def _args() -> SimpleNamespace:
    return SimpleNamespace(target_date="20261007", publication_date="2026-10-06",
                           api_base="http://127.0.0.1:8873")


def test_readback_rejects_returned_wrong_publication_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_request", lambda *_args, **_kwargs: _readback_result(
        target="20261007", publication="2026-10-05"))
    with pytest.raises(ValueError, match="DATE_PAIR_MISMATCH"):
        cli._readback(_args())


def test_readback_rejects_owner_receipt_for_wrong_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_request", lambda *_args, **_kwargs: _readback_result(
        target="20261007", publication="2026-10-06",
        receipt_target="20261006", receipt_publication="2026-10-05"))
    with pytest.raises(ValueError, match="OWNER_IMPORT_RECEIPT_BINDING_INVALID"):
        cli._readback(_args())


def test_readback_accepts_exact_payload_and_receipt_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_request", lambda *_args, **_kwargs: _readback_result(
        target="20261007", publication="2026-10-06"))
    result = cli._readback(_args())
    assert result["status"] == "OWNER_READBACK_VERIFIED"
    assert result["target_trade_date"] == "20261007"
    assert result["publication_date"] == "2026-10-06"


def test_capture_uses_exact_owner_readback_then_writes_body_input_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = {
        "schema_version": "v4.manager_research.announcement_date_catalog.v1",
        "run_id": "capture-fixture-run",
        "sha256": "c" * 64,
        "target_trade_date": "20261007",
        "publication_date": "2026-10-06",
        "status": "COMPLETE",
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    catalog_read = {
        "readback_status": "VERIFIED",
        "target_trade_date": "20261007",
        "publication_date": "2026-10-06",
        "catalog": catalog,
    }
    calls: list[tuple[str, str, str]] = []

    def request(api_base: str, path: str, *, method: str = "GET", payload: bytes | None = None):
        calls.append((api_base, path, method))
        return {"status": "REFRESHED"} if method == "POST" else catalog_read

    monkeypatch.setattr(cli, "_request", request)
    from ops import manager_announcement_body_batch as body_batch

    def capture(catalog_payload, materials_root, output_root, target, publication):
        assert catalog_payload is catalog_read
        assert target == "20261007" and publication == "2026-10-06"
        assert materials_root == state_root / "materials"
        output_root.mkdir(parents=True)
        (output_root / "body_corpus.json").write_text(json.dumps({"article_count": 0, "rows": []}))
        (output_root / "body_corpus_manifest.json").write_text(json.dumps({"catalog_run_id": catalog["run_id"]}))
        (output_root / "batch_receipt.json").write_text(json.dumps({"status": "PASS_COMPLETE"}))
        return {"status": "PASS_COMPLETE_CONTENT_API_BODIES_ALL_ROWS", "body_corpus": "body_corpus.json"}

    monkeypatch.setattr(body_batch, "run_capture", capture)
    state_root = tmp_path / "state"
    state_root.mkdir()
    args = SimpleNamespace(target_date="20261007", publication_date="2026-10-06",
        api_base="http://127.0.0.1:8873", research_state_root=str(state_root))
    result = cli._capture(args)
    evidence = state_root / "announcement_agent_runs" / result["evidence_run_id"] / "evidence"
    assert [call[2] for call in calls] == ["POST", "GET"]
    assert all(call[0] == args.api_base for call in calls)
    assert json.loads((evidence / "catalog_read.json").read_text()) == catalog_read
    assert result["catalog_run_id"] == catalog["run_id"]
    assert result["catalog_product_sha256"] == catalog["sha256"]
    assert result["semantic_status"] == "NOT_REVIEWED"
    assert result["first_hkex_publication_time"] == "CANNOT_CONFIRM"
    assert result["original_point_in_time_availability"] == "CANNOT_CONFIRM"
    assert result["body_corpus_file_sha256"] == cli._file_sha(evidence / "body_corpus.json")
    assert result["body_corpus_manifest_file_sha256"] == cli._file_sha(evidence / "body_corpus_manifest.json")
    assert result["body_batch_receipt_sha256"] == cli._file_sha(evidence / "body_batch_receipt.json")
