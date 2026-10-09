"""Offline R2 create_app owner/GET evidence, with empty isolated source roots.

The application factory, injected readers, workspace reducer, owner persistence,
and FastAPI GET are real. Only the clock and an explicit reader-binding change
are controlled. No original securities data or network is used.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import importlib
import json
import os
from pathlib import Path
import socket
import sys

import pytest


APP_ROOT = Path(os.environ.get("PLAN_AUDIT_APP_ROOT", Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(APP_ROOT))

DATE = "20261009"
PUBLICATION = "20261008"
CLOCK = datetime.fromisoformat("2026-10-09T08:00:00+08:00")
FLAGS = {"RESEARCH_ONLY": True, "production_allowed": False,
         "buy_gate_updated": False, "orders_sent": False}


def _snapshot(root):
    # Executor transport may briefly stage mirror copies under .rsync-tmp;
    # they are not application-owned files and have no project code writer.
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if ".rsync-tmp" not in p.parts and p.is_file()}


def _projection(value):
    product = value.get("plan_product", {})
    return {"input_identity": value.get("input_identity"),
            "date_bindings": value.get("date_bindings"),
            "plan_status": product.get("status"),
            "consumed": product.get("consumed"),
            "run_id": product.get("run_id"),
            "run_readback": product.get("run_readback", {}).get("status"),
            "stock_count": len(value.get("stocks", [])),
            "gaps": value.get("gaps")}


@pytest.fixture
def app_owner(tmp_path, monkeypatch):
    # Only this process's project configuration is cleared. All owned I/O is
    # confined to synthetic roots beneath pytest's explicitly set --basetemp.
    for key in tuple(os.environ):
        if key.startswith(("V4_", "V35_")):
            monkeypatch.delenv(key)

    def forbidden_network(*args, **kwargs):
        raise AssertionError("OFFLINE_AUDIT_NETWORK_FORBIDDEN")

    monkeypatch.setattr(socket, "create_connection", forbidden_network)
    monkeypatch.setattr(socket.socket, "connect", forbidden_network)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden_network)
    from apps.api.v35_api.app import create_app
    from fastapi.testclient import TestClient

    roots = {key: tmp_path / key for key in ("data", "shared", "manager", "stage", "research", "ledger")}
    for root in roots.values():
        root.mkdir()
    app = create_app(data_root=roots["data"], shared_data_root=roots["shared"],
        ledger_root=roots["ledger"], stage_center_selection_root=roots["stage"],
        current_date=DATE, manager_research_state_root=roots["manager"],
        research_data_root=roots["research"])
    service = app.state.manager_research_service
    package = service.__class__.__module__.rsplit(".", 1)[0]
    workspace = importlib.import_module(package + ".workspace")
    monkeypatch.setattr(workspace, "_now", lambda: CLOCK.isoformat())
    assert service._existing_research_source is not None
    assert service._close_observation_reader is not None
    assert service._workspace_us_market_reader is not None
    assert service._workspace_security_master_root == roots["shared"]
    try:
        with TestClient(app) as client:
            yield service, client, workspace, roots
    finally:
        service.close()


def _get(client, *, selection=DATE, announcement=PUBLICATION):
    response = client.get("/api/v4/manager/research/workspace", params={
        "date": DATE, "view": "dynamic", "selection_date": selection,
        "announcement_date": announcement})
    assert response.status_code == 200, response.text
    return response.json()


def test_app_injected_owner_same_binding_is_current_and_changed_reader_is_stale(app_owner, monkeypatch):
    service, client, workspace, roots = app_owner
    refreshed = service.refresh_workspace_plan(DATE, now=CLOCK,
        workspace_date_bindings={"selection_date": DATE, "announcement_date": PUBLICATION})
    stored = service.get_workspace_plan(DATE)
    attempt = workspace.verified_plan_attempt(service.store, stored)
    before = _snapshot(roots["manager"])
    current = _get(client)
    assert current["plan_product"]["status"] == "CURRENT"
    assert current["plan_product"]["consumed"] is True
    assert current["plan_product"]["run_readback"]["status"] == "VERIFIED"
    assert current["input_identity"] == stored["input_identity"] == refreshed["input_identity"]
    assert current["plan_product"]["run_id"] == stored["run_id"] == attempt["run_id"]
    assert current["plan_product"]["sha256"] == stored["sha256"]
    assert current["stocks"] == [] and current["gaps"]
    assert attempt["state"] == "PARTIAL"
    assert _snapshot(roots["manager"]) == before
    assert all(current[key] is flag for key, flag in FLAGS.items())

    # Detaching the archive reader changes admitted inputs; no producer or
    # reducer is replaced. This reproduces a real difference from the isolated
    # original-owner runner's configuration.
    monkeypatch.setattr(service, "_existing_research_source", None)
    changed = _get(client)
    assert changed["input_identity"] != stored["input_identity"]
    assert changed["plan_product"]["status"] == "STALE_INPUTS_CHANGED"
    assert changed["plan_product"]["consumed"] is False
    assert changed["plan_product"]["run_readback"]["status"] == "CANNOT_CONFIRM"
    assert _snapshot(roots["manager"]) == before
    assert all(changed[key] is flag for key, flag in FLAGS.items())
    print(json.dumps({"case": "create_app_same_then_changed_reader", "current": _projection(current),
                      "changed": _projection(changed)}, sort_keys=True))


def test_app_get_keeps_different_selection_binding_stale(app_owner):
    service, client, _workspace, roots = app_owner
    service.refresh_workspace_plan(DATE, now=CLOCK,
        workspace_date_bindings={"selection_date": DATE, "announcement_date": PUBLICATION})
    before = _snapshot(roots["manager"])
    changed = _get(client, selection="20261008")
    assert changed["plan_product"]["status"] == "STALE_INPUTS_CHANGED"
    assert changed["plan_product"]["consumed"] is False
    assert _snapshot(roots["manager"]) == before


def test_scheduled_dispatch_cannot_reuse_saved_other_selection_binding(app_owner, monkeypatch):
    service, client, _workspace, _roots = app_owner
    from v4.manager_research import plan_owner_dispatch as dispatch
    from v4.manager_research.workspace_plan_autorun import morning_window
    _, freeze = morning_window(DATE)
    old = service.refresh_workspace_plan(DATE, execution_kind="SCHEDULED_MORNING",
        now=CLOCK, deadline=freeze,
        workspace_date_bindings={"selection_date": "20261008"})
    # The admitted dispatch branch calls the real existing ops autorun wrapper
    # and the create_app-owned service. Binding admission itself is not claimed
    # as tested; there is no mock owner or mock workspace computation.
    monkeypatch.setattr(dispatch, "clock_now", lambda: CLOCK)
    binding = {"morning_plan": {"enabled": True, "interval_seconds": 300, "status": "PROPOSAL_ONLY"},
        "preopen_plan": {"enabled": True, "lead_seconds": 180, "status": "PROPOSAL_ONLY"},
        "plan_material_refresh": {"enabled": True, "status": "PROPOSAL_ONLY"}}
    identity = {"source_trade_date": DATE, "target_trade_date": DATE, "branch": "MORNING",
                "trigger_id": "d" * 64}
    dispatched = dispatch._run_owner_branches(service, binding, identity)
    stored = service.get_workspace_plan(DATE)
    current = _get(client)
    print(json.dumps({"case": "scheduled_dispatch_different_selection_binding",
        "prior": _projection(old), "dispatch_plan": dispatched.get("plan_result"),
        "stored_bindings": stored["workspace"].get("date_bindings"),
        "get": _projection(current)}, sort_keys=True))
    assert current["plan_product"]["status"] == "CURRENT"
    assert stored["workspace"]["date_bindings"] == {
        "plan_date": DATE, "selection_date": DATE, "announcement_date": PUBLICATION}
    assert stored["run_id"] != old["plan_product"]["run_id"]
    assert all(current[key] is flag for key, flag in FLAGS.items())


@pytest.mark.parametrize("kind", ["SCHEDULED_MORNING", "SCHEDULED_PREOPEN"])
def test_scheduled_same_date_binding_keeps_run_without_rewriting(app_owner, monkeypatch, kind):
    service, client, workspace, roots = app_owner
    from v4.manager_research.workspace_plan_autorun import morning_window, preopen_window
    clock = CLOCK if kind == "SCHEDULED_MORNING" else datetime.fromisoformat("2026-10-09T09:28:00+08:00")
    _, deadline = morning_window(DATE) if kind == "SCHEDULED_MORNING" else preopen_window(DATE)
    monkeypatch.setattr(workspace, "_now", lambda: clock.isoformat())
    first = service.refresh_workspace_plan(DATE, execution_kind=kind, now=clock, deadline=deadline)
    before = _snapshot(roots["manager"])
    repeated = service.refresh_workspace_plan(DATE, execution_kind=kind, now=clock, deadline=deadline)
    assert repeated["plan_product"]["status"] == "ALREADY_MATERIALIZED"
    assert repeated["plan_product"]["consumed"] is True
    assert repeated["plan_product"]["run_id"] == first["plan_product"]["run_id"]
    assert repeated["plan_product"]["sha256"] == first["plan_product"]["sha256"]
    assert repeated["date_bindings"] == first["date_bindings"]
    current = _get(client)
    assert current["plan_product"]["status"] == "CURRENT"
    assert current["plan_product"]["run_id"] == first["plan_product"]["run_id"]
    assert _snapshot(roots["manager"]) == before


def _publish_synthetic_archive(service):
    from domains.research import build_research_archive
    from infrastructure.data_store import _sha256
    source = {"trade_date": PUBLICATION, "schema_version": "SYNTHETIC_OFFLINE_ONLY",
        "source_manifest": {"generated_at": "2026-10-08T17:05:00+08:00"},
        "stock_research_timeline": [{"stock_code": "HK.90001", "stock_name": "星海科技",
            "source_title": "星海科技业务记录", "source_type": "SYNTHETIC_OFFLINE_ONLY",
            "source_name": "SYNTHETIC_OFFLINE_ONLY", "source_path": "synthetic-offline-source",
            "url": "https://fixture.invalid/research", "theme": "DATA_CENTER",
            "catalyst": "星海科技签署数据中心设备供货协议。",
            "evidence_sentence": "星海科技签署数据中心设备供货协议。",
            "source_published_at": "2026-10-08T17:00:00+08:00",
            "last_checked_at": "2026-10-08T17:01:00+08:00",
            "first_seen_at": "2026-10-08T17:01:00+08:00",
            "evidence_level": "RESEARCH_OPINION", "confidence": "UNKNOWN"}],
        "stock_research_daily": [{"stock_code": "HK.90001", "stock_name": "星海科技"}]}
    payload = build_research_archive(source, source_input_sha256=_sha256(source))
    return service._existing_research_source.store.publish(payload, mode="BACKFILL")


def _publish_synthetic_v2(root):
    """Use the existing pure owner to serialize six invented V2 contract files."""
    owner_path = APP_ROOT / "stage_center/hk_universe_preflight.py"
    spec = importlib.util.spec_from_file_location("_plan_identity_pure_hk_owner", owner_path)
    owner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(owner)
    codes = ["HK.90001", "HK.90002"]
    acquired = "2026-10-09T07:01:00+08:00"
    forward = {key: "1" * 64 for key in (
        "forward_receipt_sha256", "candidate_manifest_sha256", "candidate_build_receipt_sha256",
        "api_writer_receipt_sha256", "api_reviewer_receipt_sha256", "api_source_mapping_sha256")}
    forward["source_head"] = "1" * 40
    producer = {"workload_id": "v35_dispatcher.research_panel_daily_hk",
        "code_ref": "ops/_macos_research_panel_daily_parts/hk_market_capture.py", "code_sha256": "2" * 64,
        "forward_source_set": forward, "forward_source_set_sha256": owner._sha256(forward)}
    responses = {}
    for plate in owner.HKCONNECT_PLATE_CODES:
        material = {"requested_plate": plate,
            "serialization_version": "futu.dataframe.records.canonical-json.v1",
            "columns": ["code"], "rows": [{"code": code} for code in codes]}
        responses[plate] = {**material, "return_code": 0, "row_count": len(codes),
            "requested_at": "2026-10-09T07:00:00+08:00", "completed_at": acquired,
            "response_sha256": owner._sha256(material)}
    plate_codes = {plate: codes for plate in owner.HKCONNECT_PLATE_CODES}
    response_shas = {plate: value["response_sha256"] for plate, value in responses.items()}
    source = {"target_date": DATE, "plate_codes": plate_codes, "plate_response_sha256": response_shas,
        "capture_run_id": "synthetic-offline-hk-contract-run", "acquired_at": acquired}
    capture = {"schema_version": owner.HK_CONNECT_CAPTURE_SCHEMA_V2, "status": "READY",
        "target_date": DATE, "capture_run_id": source["capture_run_id"], "acquired_at": acquired,
        "producer_owner": producer, "plate_responses": responses, "plate_codes": plate_codes,
        "plate_response_counts": {plate: len(codes) for plate in responses},
        "plate_response_sha256": response_shas, "codes": codes, "code_count": len(codes),
        "overlap_count": len(codes), "membership_source_payload": source,
        "membership_source_sha256": owner._sha256(source), **owner.SAFETY_FLAGS}
    capture["capture_sha256"] = owner._sha256(capture)
    contract = {"code_ref": "stage_center/hk_universe_preflight.py",
        "code_sha256": hashlib.sha256(owner_path.read_bytes()).hexdigest(),
        "role": "PURE_CAPTURED_HK_CONNECT_CONTRACT_V2"}
    built = owner.build_captured_hk_connect_authority_v2(capture, trade_date=DATE,
        producer_owner=producer, contract_owner=contract)
    paths = built["paths"]
    publication = {"schema_version": owner.HK_CONNECT_PUBLICATION_SCHEMA_V2,
        "status": "READY", "target_date": DATE, "effective_date": DATE, "trade_date": DATE,
        "source_date": DATE, "market": "HK_CONNECT", "scope": "FULL_MARKET", "run_id": built["run_id"],
        "publication_relative": built["publication_relative"], "acquired_at": acquired,
        "available_at": "2026-10-09T07:02:00+08:00", "capture_run_id": capture["capture_run_id"],
        "capture_sha256": capture["capture_sha256"], "artifact_relative": paths["artifact_relative"],
        "artifact_sha256": built["artifact_sha256"], "manifest_relative": paths["manifest_relative"],
        "receipt_relative": paths["receipt_relative"], "current_relative": paths["current_relative"],
        "current_sha256": built["current_sha256"], "workload_id": producer["workload_id"],
        "producer_owner": producer, "contract_owner": contract, "forward_source_set": forward,
        "forward_source_set_sha256": producer["forward_source_set_sha256"], **owner.SAFETY_FLAGS}
    publication["publication_sha256"] = owner._sha256(publication)
    payloads = {paths[f"{kind}_relative"]: built[f"{kind}_bytes"]
                for kind in ("artifact", "manifest", "receipt", "current")}
    payloads[built["capture_relative"]] = built["capture_bytes"]
    payloads[built["publication_relative"]] = owner._canonical_json_line(publication)
    for relative, raw in payloads.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return owner, built


@pytest.fixture
def material_owner(app_owner, monkeypatch):
    service, client, workspace, roots = app_owner
    owner, published = _publish_synthetic_v2(roots["shared"])
    from upstreams.v3_shared_data.shared_data.hk_security_master import publish_hk_security_master
    from upstreams.v3_shared_data.shared_data.hashing import sha256_json
    publish_hk_security_master(roots["shared"], trade_date=PUBLICATION,
        rows=[{"code": "HK.90001", "name": "星海科技", "outstanding_shares": 1000,
            "circular_market_val": 100000, "listing_date": "2010-01-01", "lot_size": 100,
            "sec_status": "NORMAL"}], universe_codes_sha256=sha256_json(["HK.90001"]),
        captured_at="2026-10-08T18:01:00+08:00")
    monkeypatch.setenv("V4_MANAGER_UNIVERSE_ROOT", str(roots["shared"]))
    monkeypatch.setenv("V4_MANAGER_UNIVERSE_OWNER_ROOT", str(APP_ROOT))
    monkeypatch.setenv("V4_MANAGER_UNIVERSE_OWNER_SHA256",
        hashlib.sha256((APP_ROOT / "stage_center/hk_universe_preflight.py").read_bytes()).hexdigest())
    _publish_synthetic_archive(service)

    from domains import manager_research_evidence as evidence
    real_read = evidence.read_universe_evidence
    witness = [CLOCK]

    def read_with_witness(*args, **kwargs):
        assert "clock" not in kwargs
        return real_read(*args, clock=lambda: witness[0], **kwargs)

    monkeypatch.setattr(evidence, "read_universe_evidence", read_with_witness)
    return service, client, roots, witness, owner, published


def _refresh_material_plan(service):
    value = service.refresh_workspace_plan(DATE, now=CLOCK,
        workspace_date_bindings={"selection_date": DATE, "announcement_date": PUBLICATION})
    cards = value["material_discovery_evidence"]["cards"]
    assert len(cards) == 1, value["material_discovery_evidence"]
    assert cards[0]["symbol"] == "HK.90001"
    assert cards[0]["connect_eligibility"] == "VERIFIED_TARGET_UNIVERSE"
    return value


def test_app_immutable_authority_read_clock_does_not_stale_plan(material_owner):
    service, client, roots, witness, _owner, _published = material_owner
    before_sources = {key: _snapshot(roots[key]) for key in ("shared", "research")}
    refreshed = _refresh_material_plan(service)
    same_clock = _get(client)
    assert same_clock["plan_product"]["status"] == "CURRENT"
    witness[0] = datetime.fromisoformat("2026-10-09T08:01:00+08:00")
    later_read = _get(client)
    later_scope = later_read["selection_diagnostics"]["membership"]
    first_scope = refreshed["selection_diagnostics"]["membership"]
    assert later_scope["identity"] == first_scope["identity"]
    assert later_scope["source"]["read_at"] != first_scope["source"]["read_at"]
    assert {key: _snapshot(roots[key]) for key in ("shared", "research")} == before_sources
    for value in (refreshed, same_clock, later_read):
        assert all(value[key] is flag for key, flag in FLAGS.items())
        assert all(channel["natural_run_verified"] is False
                   for channel in value["daily_channels"]["channels"])
    print(json.dumps({"case": "immutable_authority_read_clock", "first": _projection(refreshed),
        "later": _projection(later_read), "first_read_at": first_scope["source"]["read_at"],
        "later_read_at": later_scope["source"]["read_at"],
        "authority_identity_unchanged": later_scope["identity"] == first_scope["identity"]}, sort_keys=True))
    assert later_read["plan_product"]["status"] == "CURRENT"
    assert later_read["plan_product"]["consumed"] is True
    assert later_read["input_identity"] == refreshed["input_identity"]


def test_app_persisted_availability_change_stales_plan_with_same_read_clock(material_owner):
    service, client, roots, _witness, owner, published = material_owner
    refreshed = _refresh_material_plan(service)
    first_scope = refreshed["selection_diagnostics"]["membership"]
    assert _get(client)["plan_product"]["status"] == "CURRENT"
    # Persisted availability is actual source provenance, unlike read_at. A
    # changed, still valid publication receipt must not be normalized away.
    publication_path = roots["shared"] / published["publication_relative"]
    publication = json.loads(publication_path.read_bytes())
    publication["available_at"] = "2026-10-09T07:03:00+08:00"
    publication.pop("publication_sha256")
    publication["publication_sha256"] = owner._sha256(publication)
    publication_path.write_bytes(owner._canonical_json_line(publication))
    after_publication = {key: _snapshot(roots[key]) for key in ("shared", "research", "manager")}
    changed_source = _get(client)
    changed_scope = changed_source["selection_diagnostics"]["membership"]
    assert changed_scope["status"] == "OWNER_VERIFIED"
    assert changed_scope["source"]["read_at"] == first_scope["source"]["read_at"]
    assert changed_scope["source"]["available_at"] != first_scope["source"]["available_at"]
    assert {key: _snapshot(roots[key]) for key in ("shared", "research", "manager")} == after_publication
    print(json.dumps({"case": "persisted_availability_change_same_clock", "first": _projection(refreshed),
        "changed": _projection(changed_source), "read_at": changed_scope["source"]["read_at"],
        "before_available_at": first_scope["source"]["available_at"],
        "after_available_at": changed_scope["source"]["available_at"]}, sort_keys=True))
    assert changed_source["input_identity"] != refreshed["input_identity"]
    assert changed_source["plan_product"]["status"] == "STALE_INPUTS_CHANGED"
    assert changed_source["plan_product"]["consumed"] is False
    assert all(changed_source[key] is flag for key, flag in FLAGS.items())
