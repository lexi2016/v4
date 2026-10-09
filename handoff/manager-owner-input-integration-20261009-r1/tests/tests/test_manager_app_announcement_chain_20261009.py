"""Offline source fixtures through the fixed R2 create_app injection.

The existing original-owner test fixture supplies explicitly synthetic catalog,
body, Reader and Reviewer bytes. No real research identity or data is claimed.
Unlike the existing minimal-router parity tests, import and workspace GET below
use create_app's actual private-package service, state root and material store.
"""
from datetime import datetime
import importlib
import socket
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from apps.api.v35_api import app as app_module
from ops import run_manager_daily_announcement as cli
from v4.manager_research.workspace_projection import FLAGS

import test_manager_announcement_handoff_20261009 as existing
from test_manager_announcement_handoff_20261009 import source_lane


TARGET = existing.TARGET
PUBLICATION = existing.PUBLICATION


def _get_workspace(client, publication="20261008"):
    response = client.get("/api/v4/manager/research/workspace", params={
        "date": TARGET, "selection_date": TARGET,
        "announcement_date": publication, "view": "dynamic"})
    assert response.status_code == 200, response.text
    return response.json()


def _announcement(workspace):
    return next(row for row in workspace["daily_channels"]["channels"]
                if row["channel"] == "ANNOUNCEMENT")


def test_existing_registered_product_imports_through_create_app_and_revalidates_bytes(
        source_lane, tmp_path, monkeypatch):
    lane = source_lane
    capture = cli._capture(SimpleNamespace(target_date=TARGET,
        publication_date="20261008", api_base="http://127.0.0.1:8873",
        research_state_root=str(lane.root)))
    registered = existing._register_captured_fixture(lane, capture)

    # Production app roots are deliberately disjoint except for the existing
    # manager owner state. Missing unrelated inputs remain missing.
    for key in ("V4_MANAGER_NEWS_DATA_ROOT", "V4_MANAGER_NEWS_OWNER_ROOT",
                "V4_MANAGER_SECURITY_MASTER_ROOT", "V4_MANAGER_SCREEN_AUTHORITY_ROOT",
                "V4_MANAGER_UNIVERSE_ROOT", "V4_MANAGER_UNIVERSE_OWNER_ROOT",
                "V4_MANAGER_UNIVERSE_OWNER_SHA256", "V4_MANAGER_HK_CAPTURE_RECEIPT_ROOT",
                "V4_MANAGER_HK_DISPATCH_RECEIPT_ROOT"):
        monkeypatch.delenv(key, raising=False)
    app = app_module.create_app(data_root=tmp_path / "native-data",
        shared_data_root=tmp_path / "shared-authority",
        ledger_root=tmp_path / "ledger",
        stage_center_selection_root=tmp_path / "stage",
        manager_research_state_root=lane.root, current_date=TARGET)
    service = app.state.manager_research_service
    assert type(service).__module__ == app_module._MANAGER_RESEARCH_RUNTIME_PACKAGE + ".service"
    assert service.store.root == lane.root
    assert service._material_store.root == lane.root / "materials"
    assert service is not lane.service

    runtime_workspace = importlib.import_module(
        app_module._MANAGER_RESEARCH_RUNTIME_PACKAGE + ".workspace")
    runtime_announcements = importlib.import_module(
        app_module._MANAGER_RESEARCH_RUNTIME_PACKAGE + ".workspace_announcements")

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return existing.NOW.astimezone(tz) if tz else existing.NOW.replace(tzinfo=None)

    monkeypatch.setattr(runtime_workspace, "datetime", Clock)
    monkeypatch.setattr(runtime_announcements, "_now", lambda: existing.NOW.isoformat())

    def forbidden_network(*args, **kwargs):
        pytest.fail("Full-app announcement import/read must not perform source transport")

    # ASGI TestClient uses in-process HTTP. Actual external sockets are forbidden.
    monkeypatch.setattr(socket.socket, "connect", forbidden_network)
    monkeypatch.setattr(socket, "create_connection", forbidden_network)
    source_calls = list(lane.source_calls)
    try:
        with TestClient(app) as client:
            before_import = _get_workspace(client)
            missing = _announcement(before_import)
            assert missing["status"] == "CANNOT_CONFIRM"
            assert missing["candidate_count"] is None
            assert missing["rows"] == []
            assert missing["gaps"] == ["ANNOUNCEMENT_ANALYSIS_NOT_IMPORTED"]

            response = client.post("/api/v4/manager/research/announcements/analysis/import",
                headers={"Origin": "http://testserver"}, json={
                    "schema_version": "v4.manager_research.announcement_analysis_import_ref.v1",
                    "evidence_run_id": registered["evidence_run_id"],
                    "handoff_manifest_sha256": registered["handoff_manifest_sha256"],
                    "product_sha256": registered["product_sha256"]})
            assert response.status_code == 200, response.text
            imported = response.json()
            assert imported["consumption_validation"]["validation_status"] == "VERIFIED"
            snapshot = existing._snapshot(lane.root)

            response = client.get("/api/v4/manager/research/announcements/analysis",
                params={"date": TARGET, "publication_date": "20261008"})
            assert response.status_code == 200, response.text
            analysis_read = response.json()
            workspace = _get_workspace(client)
            channel = _announcement(workspace)
            consumed = workspace["announcement_reviewed_analysis"]["products"][0]
            assert consumed["status"] == "CONSUMED"
            assert consumed["cutoff_status"] == "SATISFIED"
            for field, expected in {
                "product_sha256": registered["product_sha256"],
                "evidence_run_id": registered["evidence_run_id"],
                "handoff_manifest_sha256": registered["handoff_manifest_sha256"],
                "owner_import_receipt_sha256": imported["owner_import_receipt"]["sha256"],
            }.items():
                assert consumed[field] == expected
                assert analysis_read["consumption_validation"][field] == expected
                assert imported["consumption_validation"][field] == expected
            assert channel["status"] == "READY"
            assert channel["candidate_count"] == 1
            assert channel["pending_count"] == 0
            assert [row["symbol"] for row in channel["rows"]] == ["HK.01234"]
            assert channel["rows"][0]["reason"] == "Synthetic fixture disposition only."
            assert workspace["announcement_review"]["status"] == "NOT_RUN"
            assert workspace["input_identity"] != before_import["input_identity"]
            assert all(row["status"] == "CANNOT_CONFIRM"
                for row in workspace["daily_channels"]["channels"]
                if row["channel"] in {"HK_CONNECT", "OVERSOLD"})
            assert all(workspace[key] is expected for key, expected in FLAGS.items())
            assert all(channel[key] is expected for key, expected in FLAGS.items())
            assert channel["natural_run_verified"] is False
            assert existing._snapshot(lane.root) == snapshot

            # A different publication query cannot reuse the complete product.
            other_pair = _announcement(_get_workspace(client, "20261007"))
            assert other_pair["status"] == "CANNOT_CONFIRM"
            assert other_pair["rows"] == []
            assert other_pair["candidate_count"] is None
            assert existing._snapshot(lane.root) == snapshot

            # The already imported product stays on disk, but loss of original
            # Reader bytes must invalidate both API and workspace consumption.
            evidence = lane.root / "announcement_agent_runs" / registered["evidence_run_id"] / "evidence"
            reader = evidence / "reader_output.json"
            reader.write_bytes(reader.read_bytes() + b" ")
            invalid_snapshot = existing._snapshot(lane.root)
            rejected_workspace = _get_workspace(client)
            rejected = _announcement(rejected_workspace)
            assert rejected["status"] == "CANNOT_CONFIRM"
            assert rejected["rows"] == []
            assert rejected["candidate_count"] is None
            check = rejected["product_checks"][0]
            assert check["product_sha256"] == registered["product_sha256"]
            assert check["status"] == "NOT_CONSUMED_INVALID"
            assert check["failure_stage"] == "REGISTERED_HANDOFF"
            assert check["consumed"] is False
            response = client.get("/api/v4/manager/research/announcements/analysis",
                params={"date": TARGET, "publication_date": "20261008"})
            assert response.status_code == 200, response.text
            rejected_read = response.json()["consumption_validation"]
            assert rejected_read["gaps"] == check["gaps"]
            assert rejected_read["validation_status"] == "CANNOT_CONFIRM"
            assert existing._snapshot(lane.root) == invalid_snapshot
            assert lane.source_calls == source_calls
    finally:
        service.close()
