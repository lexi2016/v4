"""Independent review probe: original catch-up path, synthetic bound source only.

No workspace identity/metadata is patched. Only local synthetic archive bytes
and the explicit test clock change. No live service or source is accessed.
"""
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import socket
import sys

import pytest

APP_ROOT = Path(os.environ["PLAN_AUDIT_APP_ROOT"]).resolve()
sys.path.insert(0, str(APP_ROOT))


def test_bound_late_material_advances_plan_with_consistent_identity(tmp_path, monkeypatch):
    for key in tuple(os.environ):
        if key.startswith(("V4_", "V35_")):
            monkeypatch.delenv(key)

    def forbidden(*args, **kwargs):
        raise AssertionError("INDEPENDENT_OFFLINE_REVIEW_NETWORK_FORBIDDEN")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)

    from infrastructure.research_lane_source import ResearchLaneSource
    from tests.test_manager_app_plan_identity_20261009 import _publish_synthetic_archive
    from tests.test_manager_semantic_identity_20261010 import _rewrite_payload_and_receipt
    from v4.manager_research.existing_materials import _read_archive
    from v4.manager_research import workspace
    from v4.manager_research.workspace_projection import HK, FLAGS
    from v4.manager_research.service import ManagerResearchJobService
    from v4.manager_research.store import ManagerResearchStore
    from ops.run_manager_announcement_cycle import run_same_day_catchup_plan

    source = ResearchLaneSource(tmp_path / "synthetic-research", ledger_root=tmp_path / "synthetic-ledger")
    service = ManagerResearchJobService(ManagerResearchStore(tmp_path / "synthetic-manager"),
        None, None, existing_research_source=source)
    try:
        _publish_synthetic_archive(service)
        _rows, _gaps, before_binding = _read_archive(source, "20261008", "")
        assert len(_rows) == 1 and before_binding["status"] == "VERIFIED"
        preopen_at = datetime(2026, 10, 9, 9, 27, tzinfo=HK)
        monkeypatch.setattr(workspace, "_now", lambda: "2026-10-09T01:28:00+00:00")
        preopen = service.refresh_workspace_plan("20261009", execution_kind="SCHEDULED_PREOPEN",
            now=preopen_at, deadline=datetime(2026, 10, 9, 9, 30, tzinfo=HK))
        assert preopen["plan_product"]["consumed"] is True
        old_run = preopen["plan_product"]["run_id"]
        old_path = service.store.root / "workspace_plans" / "20261009" / (old_run + ".json")
        old_bytes = old_path.read_bytes()

        _rewrite_payload_and_receipt(source, "source_title", "独立离线评审：新增已绑定材料约束")
        _rows, _gaps, after_binding = _read_archive(source, "20261008", "")
        assert len(_rows) == 1 and after_binding["status"] == "VERIFIED"
        assert after_binding["payload_sha256"] != before_binding["payload_sha256"]
        assert after_binding["receipt_sha256"] != before_binding["receipt_sha256"]
        late_at = datetime(2026, 10, 9, 18, 30, tzinfo=HK)
        monkeypatch.setattr(workspace, "_now", lambda: "2026-10-09T10:30:01+00:00")
        result = run_same_day_catchup_plan(service, "20261009", now=late_at,
            scheduled_slot="20261009T1830", trigger_id="c" * 64)
        assert result["status"] == "PARTIAL"
        assert result["plan_result"]["run_id"] != old_run
        assert result["plan_result"]["execution_kind"] == "MANUAL_REFRESH"
        assert result["plan_result"]["execution_context"]["timing"] == "LATE_CATCHUP"
        saved = workspace._read_plan(service.store, "20261009")
        assert saved["run_id"] == result["plan_result"]["run_id"]
        assert saved["input_identity"] != preopen["input_identity"]
        current = workspace.get_workspace(service, "20261009", view="dynamic",
            now=late_at + timedelta(seconds=5))
        assert current["plan_product"]["status"] == "CURRENT"
        assert current["plan_product"]["consumed"] is True
        assert current["input_identity"] == saved["input_identity"]
        assert old_path.read_bytes() == old_bytes
        assert all(current[key] is flag for key, flag in FLAGS.items())
        metadata = current.get("input_identity_components")
        if metadata is not None:
            from v4.manager_research.workspace_identity import compare_components
            assert metadata["input_identity"] == current["input_identity"]
            assert compare_components(saved["workspace"], current)["status"] == "MATCH"
        print(json.dumps({"scope": "OFFLINE_SYNTHETIC_BOUND_ARCHIVE_ORIGINAL_CATCHUP_PATH",
            "source_artifacts": 1, "admitted_archive_rows": 1,
            "payload_and_receipt_changed": True,
            "workspace_identity_directly_rewritten": False,
            "old_plan_sha256": hashlib.sha256(old_bytes).hexdigest(),
            "old_plan_bytes_preserved": True, "late_plan_status": result["status"],
            "late_execution_kind": result["plan_result"]["execution_kind"],
            "readback_status": current["plan_product"]["status"],
            "has_component_metadata": metadata is not None,
            "full_pit_or_live_owner_acceptance": "NOT_CLAIMED"}, sort_keys=True))
    finally:
        service.close()
