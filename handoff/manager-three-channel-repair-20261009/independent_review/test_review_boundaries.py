"""Independent malformed-boundary probes. Every receipt and value is synthetic."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from ops import run_manager_daily_announcement as cli
from v4.manager_research import workspace_announcements as announcement
from v4.manager_research.workspace_projection import FLAGS, digest

from test_manager_us_mapping_three_channel_20261009 import owner
from test_manager_announcement_handoff_20261009 import imported_lane


def _synthetic_null_source_projection():
    manifest = {"target_trade_date": "20261009", "publication_date": "2026-10-08"}
    receipt = {
        "schema_version": announcement._OWNER_ANALYSIS_IMPORT_SCHEMA,
        "status": "VERIFIED", "owner": "ManagerResearchJobService.import_announcement_analysis",
        "target_trade_date": "20261009", "publication_date": "2026-10-08",
        "product_sha256": "a" * 64, "parent_task_id": "synthetic-parent",
        "parent_run_id": "synthetic-parent-run", "available_at": "2026-10-09T00:00:00+00:00",
        **FLAGS,
    }
    receipt["sha256"] = digest(receipt)
    chain = {
        "target_trade_date": "20261009", "publication_date": "2026-10-08",
        "product_sha256": "a" * 64, "source_manifest_sha256": digest(manifest),
        "owner_import_receipt_sha256": receipt["sha256"],
        "owner_available_at": receipt["available_at"],
        "validation_status": "VERIFIED", "status": "VERIFIED", "failure_stage": None,
        "gaps": [], "owner_handoff_binding_status": "LEGACY_PRODUCT_PARENT_ONLY_CURRENT_HANDOFF_VERIFIED",
        "catalog_product_sha256": None, "source_run_id": None, **FLAGS,
    }
    return {
        "target_trade_date": "20261009", "publication_date": "2026-10-08",
        "analysis": {"status": "VERIFIED", "source_manifest": manifest,
                     "product_sha256": "a" * 64, "source_manifest_sha256": digest(manifest)},
        "owner_import_receipt": receipt, "consumption_validation": chain,
        "source_catalog": {"readback_status": "VERIFIED", "catalog_product_sha256": None,
                           "catalog_run_id": None}, **FLAGS,
    }


def test_cli_rejects_verified_projection_without_catalog_run_and_digest(monkeypatch):
    value = _synthetic_null_source_projection()
    monkeypatch.setattr(cli, "_request", lambda *_args, **_kwargs: deepcopy(value))
    with pytest.raises(ValueError, match="ANNOUNCEMENT_ANALYSIS_OWNER_READBACK_CHAIN_INVALID"):
        cli._readback(SimpleNamespace(target_date="20261009", publication_date="20261008",
                                     api_base="http://127.0.0.1:8873"))


def test_manual_preparation_rejects_artifact_text_without_persisted_run(owner, monkeypatch):
    service, _source, client, _clock = owner
    monkeypatch.setattr(service, "refresh_us_mapping_research", lambda *_args, **_kwargs: {
        "schema_version": "v4.manager_research.us_mapping_daily_run.v1",
        "target_trade_date": "20261009", "status": "FAILED", "run_id": None,
        "artifact_sha256": "SYNTHETIC_PRIVATE_TEXT_NOT_A_DIGEST",
        "execution_status": "US_MAPPING_OWNER_BUILD_FAILED", "gaps": [], **FLAGS,
    })
    response = client.post("/api/v4/manager/research/workspace/refresh",
                          params={"date": "20261009"}, content=b"")
    assert response.status_code == 200
    assert "SYNTHETIC_PRIVATE_TEXT_NOT_A_DIGEST" not in response.text
    assert response.json()["us_mapping_preparation"]["artifact_sha256"] is None
    assert response.json()["plan_product"]["status"] == "CURRENT"


def test_legacy_readback_rejects_numeric_catalog_identity(imported_lane, monkeypatch):
    readback = imported_lane.client.get("/api/v4/manager/research/announcements/analysis",
        params={"date": "20261009", "publication_date": "20261008"}).json()
    receipt = readback["owner_import_receipt"]
    for key in ("source_manifest_sha256", "evidence_run_id", "handoff_manifest_sha256",
                "agent_judgment_receipt_sha256"):
        receipt.pop(key)
    receipt["sha256"] = digest({key: value for key, value in receipt.items() if key != "sha256"})
    chain = readback["consumption_validation"]
    chain["owner_import_receipt_sha256"] = receipt["sha256"]
    chain["owner_handoff_binding_status"] = "LEGACY_PRODUCT_PARENT_ONLY_CURRENT_HANDOFF_VERIFIED"
    number = int("1" * 64)
    manifest = readback["analysis"]["source_manifest"]
    manifest["catalog_product_sha256"] = number
    readback["analysis"]["source_manifest_sha256"] = digest(manifest)
    chain["source_manifest_sha256"] = digest(manifest)
    chain["catalog_product_sha256"] = number
    readback["source_catalog"]["catalog_product_sha256"] = number
    monkeypatch.setattr(cli, "_request", lambda *_args, **_kwargs: deepcopy(readback))
    with pytest.raises(ValueError, match="ANNOUNCEMENT_ANALYSIS_OWNER_READBACK_CHAIN_INVALID"):
        cli._readback(SimpleNamespace(target_date="20261009", publication_date="20261008",
                                     api_base="http://127.0.0.1:8873"))
