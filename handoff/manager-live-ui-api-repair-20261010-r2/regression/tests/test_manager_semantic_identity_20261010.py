"""Consumed-archive identity and immutable owner/GET transitions, offline only.

The archive validator, material projection, saved-plan owner and registered
manager router are real. The host is an isolated FastAPI test app: the frozen
full create_app is unavailable because Stage support is missing. Fixtures
create invented artifacts in pytest tmp roots. Mutations are isolated fault
injection, never owner imports or changes to a live research root.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import socket
import sys
from types import SimpleNamespace

import pytest

APP_ROOT = Path(os.environ.get("PLAN_AUDIT_APP_ROOT", Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(APP_ROOT))

from infrastructure.data_store import _sha256
from infrastructure.research_lane_source import ResearchLaneSource
from v4.manager_research.existing_materials import _read_archive
from v4.manager_research.workspace_projection import build_workspace, digest
from tests.test_manager_app_plan_identity_20261009 import (
    DATE, PUBLICATION, CLOCK, FLAGS, material_owner,
    _get, _publish_synthetic_archive, _refresh_material_plan, _snapshot,
)


@pytest.fixture
def app_owner(tmp_path, monkeypatch):
    """Real service/router; no Stage stub and no claim to full create_app."""
    for key in tuple(os.environ):
        if key.startswith(("V4_", "V35_")):
            monkeypatch.delenv(key)

    def forbidden_network(*args, **kwargs):
        raise AssertionError("OFFLINE_AUDIT_NETWORK_FORBIDDEN")

    monkeypatch.setattr(socket, "create_connection", forbidden_network)
    monkeypatch.setattr(socket.socket, "connect", forbidden_network)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden_network)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from apps.api.v35_api.manager_research_router import create_manager_research_router
    from apps.api.v35_api.manager_workbench_router import ManagerWorkbenchResearchReader
    from v4.manager_research.service import ManagerResearchJobService
    from v4.manager_research.store import ManagerResearchStore
    from v4.manager_research.us_market_bridge import ResearchPeripheralUsMarketReader
    from v4.manager_research import workspace

    roots = {key: tmp_path / key for key in ("data", "shared", "manager", "research", "ledger")}
    for root in roots.values():
        root.mkdir()
    service = ManagerResearchJobService(ManagerResearchStore(roots["manager"]), None, None,
        existing_research_source=ResearchLaneSource(roots["research"], ledger_root=roots["ledger"]),
        close_observation_reader=ManagerWorkbenchResearchReader(roots["manager"]),
        workspace_ledger_root=roots["ledger"], workspace_security_master_root=roots["shared"],
        workspace_screen_authority_root=roots["shared"], catalyst_data_root=roots["data"],
        workspace_us_market_reader=ResearchPeripheralUsMarketReader(roots["data"]))
    monkeypatch.setattr(workspace, "_now", lambda: CLOCK.isoformat())
    app = FastAPI()
    app.include_router(create_manager_research_router(service))
    try:
        with TestClient(app) as client:
            yield service, client, workspace, roots
    finally:
        service.close()


@pytest.fixture
def archive_source(tmp_path):
    source = ResearchLaneSource(tmp_path / "research", ledger_root=tmp_path / "ledger")
    _publish_synthetic_archive(SimpleNamespace(_existing_research_source=source))
    return source


def _materials(source):
    rows, _gaps, binding = _read_archive(source, PUBLICATION, "")
    assert rows and binding["status"] == "VERIFIED"
    return rows, binding


def _projection(rows):
    return build_workspace(DATE, catalyst={}, materials=rows, stage=None, close=None)


def _add_unconsumed_entry(source):
    manifest = source.store._manifest()
    manifest["synthetic-unconsumed/registry-only.json"] = "9" * 64
    source.store._write_manifest(manifest)


def _export_workspace(name, value):
    root = os.environ.get("TASK1_BACKEND_FIXTURE_ROOT")
    if root:
        path = Path(root)
        path.mkdir(parents=True, exist_ok=True)
        (path / (name + ".json")).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _replace_saved_fixture(service, saved):
    saved["sha256"] = digest({key: value for key, value in saved.items() if key != "sha256"})
    plan_root = service.store.root / "workspace_plans" / DATE
    for name in ("latest.json", saved["run_id"] + ".json"):
        # Fault injection models an already sealed legacy/corrupt product.
        # The real owner forbids overwriting an immutable run file.
        (plan_root / name).write_text(json.dumps(saved, ensure_ascii=False))


def _rewrite_payload_and_receipt(source, field, value):
    """Reseal a synthetic change; the original schema still decides admission."""
    relative = source.store._relative(PUBLICATION)
    payload = source.store._read(relative)
    payload["articles"][0][field] = value
    payload_sha = _sha256(payload)
    source.store._write(relative, payload)
    source.store._write(source.store._receipt_relative(PUBLICATION), source.store._receipt(payload, payload_sha))
    manifest = source.store._manifest()
    manifest[relative] = payload_sha
    source.store._write_manifest(manifest)


def test_unconsumed_manifest_entry_does_not_change_identity(archive_source):
    """Catches the whole registry SHA entering a consumed-material identity."""
    before, old_binding = _materials(archive_source)
    preserved = deepcopy(before)
    _add_unconsumed_entry(archive_source)
    after, new_binding = _materials(archive_source)
    assert old_binding["manifest_sha256"] != new_binding["manifest_sha256"]
    assert old_binding["payload_sha256"] == new_binding["payload_sha256"]
    assert old_binding["receipt_sha256"] == new_binding["receipt_sha256"]
    old_view, new_view = _projection(before), _projection(after)
    assert old_view["input_identity"] == new_view["input_identity"]
    assert before == preserved
    assert new_view["materials"][0]["source_refs"][0]["manifest_sha256"] == new_binding["manifest_sha256"]
    assert all(new_view[key] is flag for key, flag in FLAGS.items())


@pytest.mark.parametrize("part", ["payload", "receipt", "manifest_entry", "archive_date"])
def test_real_reader_rejects_changed_or_unverified_artifact(archive_source, part):
    """Catches an identity repair weakening payload/receipt/date verification."""
    rows, binding = _materials(archive_source)
    assert rows
    if part == "payload":
        payload = archive_source.store._read(binding["payload_path"])
        payload["articles"][0]["source_title"] = "未经封存的正文改动"
        archive_source.store._write(binding["payload_path"], payload)
    elif part == "receipt":
        receipt = archive_source.store._read(binding["receipt_path"])
        receipt["payload_sha256"] = "8" * 64
        archive_source.store._write(binding["receipt_path"], receipt)
    elif part == "manifest_entry":
        manifest = archive_source.store._manifest()
        manifest[binding["payload_path"]] = "7" * 64
        archive_source.store._write_manifest(manifest)
    else:
        payload = archive_source.store._read(binding["payload_path"])
        payload["archive_date"] = "20261007"
        payload_sha = _sha256(payload)
        archive_source.store._write(binding["payload_path"], payload)
        archive_source.store._write(binding["receipt_path"], archive_source.store._receipt(payload, payload_sha))
        manifest = archive_source.store._manifest()
        manifest[binding["payload_path"]] = payload_sha
        archive_source.store._write_manifest(manifest)
    with pytest.raises(ValueError):
        _read_archive(archive_source, PUBLICATION, "")


@pytest.mark.parametrize(("field", "value", "reader_rejects"), [
    ("source_title", "星海科技业务记录：新增约束", False),
    ("available_at", "2026-10-08T17:02:00+08:00", True),
    ("market", "A_SHARE", True),
    ("manifest_sha256", "c" * 64, True),
])
def test_consumed_content_changes_identity_or_is_rejected(archive_source, field, value, reader_rejects):
    """Catches dropping source content or availability when excluding provenance."""
    before, _ = _materials(archive_source)
    _rewrite_payload_and_receipt(archive_source, field, value)
    if reader_rejects:
        # The exact frozen archive contract does not admit these extra fields.
        # The repair must keep that rejection; projection semantics are tested
        # separately for owner contracts which do support availability.
        with pytest.raises(ValueError, match="invalid research article fields"):
            _materials(archive_source)
        return
    after, _ = _materials(archive_source)
    assert _projection(before)["input_identity"] != _projection(after)["input_identity"]


def test_projected_availability_change_remains_semantic(archive_source):
    before, _ = _materials(archive_source)
    after = deepcopy(before)
    after[0]["available_at"] = "2026-10-08T17:02:00+08:00"
    assert _projection(before)["input_identity"] != _projection(after)["input_identity"]


@pytest.mark.parametrize(("field", "value"), [
    ("payload_sha256", "1" * 64), ("receipt_sha256", "2" * 64),
    ("source_date", "20261007"), ("payload_path", "research/archives/20261007.json"),
    ("receipt_path", "receipts/research/archives/20261007.json"),
    ("source_root", "/isolated/other-owner"), ("mode", "REPLAY"),
])
def test_consumed_binding_changes_remain_semantic(archive_source, field, value):
    before, _ = _materials(archive_source)
    after = deepcopy(before)
    after[0]["source_refs"][0][field] = value
    assert _projection(before)["input_identity"] != _projection(after)["input_identity"]


@pytest.mark.parametrize("content_path", ["source_row", "original_source_row", "other_content"])
def test_same_named_manifest_field_inside_semantic_content_is_preserved(archive_source, content_path):
    before, _ = _materials(archive_source)
    before[0][content_path] = {"manifest_sha256": "a" * 64,
        "source_refs": [deepcopy(before[0]["source_refs"][0])]}
    after = deepcopy(before)
    after[0][content_path]["manifest_sha256"] = "b" * 64
    assert _projection(before)["input_identity"] != _projection(after)["input_identity"]
    if content_path in {"source_row", "original_source_row"}:
        after = deepcopy(before)
        after[0][content_path]["source_refs"][0]["manifest_sha256"] = "d" * 64
        assert _projection(before)["input_identity"] != _projection(after)["input_identity"]


def test_unrecognized_source_reference_is_not_normalized(archive_source):
    before, _ = _materials(archive_source)
    before[0]["source_refs"][0]["source_id"] = "ANOTHER_OWNER"
    after = deepcopy(before)
    after[0]["source_refs"][0]["manifest_sha256"] = "3" * 64
    assert _projection(before)["input_identity"] != _projection(after)["input_identity"]


def test_owner_saved_plan_stays_current_after_global_only_update(material_owner):
    """Catches recoupling in discovery IDs, research attention, or outer plan hash."""
    service, client, roots, _witness, _owner, _published = material_owner
    refreshed = _refresh_material_plan(service)
    saved = service.get_workspace_plan(DATE)
    assert _get(client)["plan_product"]["status"] == "CURRENT"
    _add_unconsumed_entry(service._existing_research_source)
    before = {key: _snapshot(root) for key, root in roots.items()}
    current = _get(client)
    assert current["plan_product"]["status"] == "CURRENT"
    assert current["plan_product"]["consumed"] is True
    assert current["input_identity"] == refreshed["input_identity"] == saved["input_identity"]
    assert current["plan_product"]["run_id"] == saved["run_id"]
    assert current["plan_product"]["sha256"] == saved["sha256"]
    diagnostic = current["plan_product"]["input_identity_diagnostic"]
    assert diagnostic["status"] == "MATCH"
    assert diagnostic["changed_components"] == []
    assert diagnostic["provenance_changes"]
    _export_workspace("manifest_only_match", current)
    assert service.get_workspace_plan(DATE) == saved
    assert {key: _snapshot(root) for key, root in roots.items()} == before
    assert all(current[key] is flag for key, flag in FLAGS.items())


def test_scheduled_plan_global_only_update_does_not_republish(material_owner):
    service, client, roots, _witness, _owner, _published = material_owner
    from v4.manager_research.workspace_plan_autorun import morning_window
    _, freeze = morning_window(DATE)
    first = service.refresh_workspace_plan(DATE, execution_kind="SCHEDULED_MORNING", now=CLOCK,
        deadline=freeze, workspace_date_bindings={"selection_date": DATE, "announcement_date": PUBLICATION})
    _add_unconsumed_entry(service._existing_research_source)
    before = _snapshot(roots["manager"])
    repeated = service.refresh_workspace_plan(DATE, execution_kind="SCHEDULED_MORNING", now=CLOCK,
        deadline=freeze, workspace_date_bindings={"selection_date": DATE, "announcement_date": PUBLICATION})
    assert repeated["plan_product"]["status"] == "ALREADY_MATERIALIZED"
    assert repeated["plan_product"]["run_id"] == first["plan_product"]["run_id"]
    assert _get(client)["plan_product"]["status"] == "CURRENT"
    assert _snapshot(roots["manager"]) == before


@pytest.mark.parametrize(("field", "value"), [
    ("source_title", "星海科技业务记录：新增约束"),
    ("available_at", "2026-10-08T17:02:00+08:00"),
])
def test_true_stale_readback_locates_consumed_source_without_raw_payload(material_owner, field, value):
    service, client, roots, _witness, _owner, _published = material_owner
    _refresh_material_plan(service)
    saved = service.get_workspace_plan(DATE)
    assert saved["workspace"]["input_identity_components"]["input_identity"] == saved["input_identity"]
    _rewrite_payload_and_receipt(service._existing_research_source, field, value)
    before = {key: _snapshot(root) for key, root in roots.items()}
    current = _get(client)
    assert current["plan_product"]["status"] == "STALE_INPUTS_CHANGED"
    assert current["plan_product"]["consumed"] is False
    diagnostic = current["plan_product"]["input_identity_diagnostic"]
    assert diagnostic["status"] == "CHANGED"
    sources = [row for row in diagnostic["changed_components"] if row.get("source")]
    assert any(row["source"].get("payload_path") == "research/archives/20261008.json" for row in sources)
    assert all(row["saved_sha256"] != row["current_sha256"] for row in sources)
    assert "星海科技" not in json.dumps(diagnostic, ensure_ascii=False)
    assert "source_row" not in json.dumps(diagnostic)
    _export_workspace("consumed_content_changed" if field == "source_title" else "consumed_availability_rejected", current)
    assert service.get_workspace_plan(DATE) == saved
    assert {key: _snapshot(root) for key, root in roots.items()} == before
    assert all(current[key] is flag for key, flag in FLAGS.items())


def test_legacy_plan_without_component_metadata_is_not_forced_current(material_owner):
    service, client, roots, _witness, _owner, _published = material_owner
    _refresh_material_plan(service)
    saved = service.get_workspace_plan(DATE)
    saved["workspace"].pop("input_identity_components", None)
    _replace_saved_fixture(service, saved)
    before = _snapshot(roots["manager"])
    current = _get(client)
    assert current["plan_product"]["consumed"] is False
    assert current["plan_product"]["status"] != "CURRENT"
    diagnostic = current["plan_product"]["input_identity_diagnostic"]
    assert diagnostic["status"] == "CANNOT_CONFIRM"
    assert "SAVED_COMPONENT_METADATA_MISSING" in diagnostic["reason_codes"]
    _export_workspace("legacy_missing_components", current)
    assert _snapshot(roots["manager"]) == before
    replacement = _refresh_material_plan(service)
    assert replacement["plan_product"]["status"] == "CURRENT"
    assert replacement["plan_product"]["run_id"] != saved["run_id"]
    assert _get(client)["plan_product"]["status"] == "CURRENT"


def test_both_legacy_dtos_keep_optional_diagnostic_absent(material_owner):
    """An old internal DTO caller retains its exact-equality/owner guard."""
    service, _client, _roots, _witness, _owner, _published = material_owner
    from v4.manager_research import workspace
    _refresh_material_plan(service)
    saved = service.get_workspace_plan(DATE)
    saved["workspace"].pop("input_identity_components", None)
    _replace_saved_fixture(service, saved)
    legacy_current = deepcopy(saved["workspace"])
    current = workspace._readback_plan(service.store, DATE, legacy_current, read_at=CLOCK)
    assert current["plan_product"]["status"] == "CURRENT"
    assert current["plan_product"]["consumed"] is True
    assert "input_identity_diagnostic" not in current["plan_product"]


@pytest.mark.parametrize("part", ["checksum", "identity", "component_hash", "source_extra_field", "provenance_shape"])
def test_invalid_saved_component_metadata_cannot_authorize_reuse(material_owner, part):
    service, client, roots, _witness, _owner, _published = material_owner
    _refresh_material_plan(service)
    saved = service.get_workspace_plan(DATE)
    metadata = saved["workspace"]["input_identity_components"]
    if part == "checksum":
        metadata["sha256"] = "f" * 64
    elif part == "identity":
        metadata["input_identity"] = "f" * 64
    elif part == "component_hash":
        metadata["components"][0]["sha256"] = "not-a-sha"
    else:
        source_component = next(row for row in metadata["components"] if row.get("source"))
        if part == "source_extra_field":
            source_component["source"]["raw_payload"] = "SOURCE_CONTENT_MUST_NOT_ENTER_DIAGNOSTIC"
        else:
            source_component["provenance"] = "invalid-shape"
    if part != "checksum":
        metadata["sha256"] = digest({key: value for key, value in metadata.items() if key != "sha256"})
    _replace_saved_fixture(service, saved)
    before = _snapshot(roots["manager"])
    current = _get(client)
    assert current["plan_product"]["consumed"] is False
    diagnostic = current["plan_product"]["input_identity_diagnostic"]
    assert diagnostic["status"] == "CANNOT_CONFIRM"
    assert "SAVED_COMPONENT_METADATA_INVALID" in diagnostic["reason_codes"]
    assert _snapshot(roots["manager"]) == before


def test_date_binding_stale_diagnostic_remains_explicit(material_owner):
    service, client, _roots, _witness, _owner, _published = material_owner
    _refresh_material_plan(service)
    changed = _get(client, selection="20261008")
    assert changed["plan_product"]["status"] == "STALE_INPUTS_CHANGED"
    assert changed["plan_product"]["consumed"] is False
    diagnostic = changed["plan_product"]["input_identity_diagnostic"]
    assert diagnostic["status"] == "CHANGED"
    assert any(row["component_id"] == "date_bindings" for row in diagnostic["changed_components"])
    _export_workspace("date_bindings_changed", changed)


@pytest.fixture
def materialized_archive_catalyst(material_owner, monkeypatch):
    """Real fixed archive validator/owner. Missing acquisition clocks stay out."""
    service, client, roots, *_ = material_owner
    from v4.manager_research import catalyst_observations
    monkeypatch.setattr(catalyst_observations, "_now", lambda: CLOCK)
    captured = service.refresh_catalyst_observations(DATE)
    coverage = captured["archive_projection"]["coverage"]
    assert coverage["archive_artifact_count"] == 1
    assert coverage["clock_admitted_material_count"] == 0
    assert captured["archive_projection"]["rejected_materials"][0]["reason"] == "ARCHIVE_EXPLICIT_ACQUISITION_TIME_REQUIRED"
    assert service.get_catalyst_observations(DATE) == captured
    return service, client, roots, captured


def test_materialized_archive_catalyst_global_only_keeps_full_replay_and_plan_current(materialized_archive_catalyst):
    """The real materialized catalyst must survive both original equality guards."""
    service, client, roots, captured = materialized_archive_catalyst
    source = service._existing_research_source
    before_binding = source.artifact_binding(PUBLICATION)
    first = _refresh_material_plan(service)
    saved = service.get_workspace_plan(DATE)
    assert _get(client)["plan_product"]["status"] == "CURRENT"
    _add_unconsumed_entry(source)
    after_binding = source.artifact_binding(PUBLICATION)
    assert before_binding["manifest_sha256"] != after_binding["manifest_sha256"]
    for field in ("payload_sha256", "receipt_sha256"):
        assert before_binding[field] == after_binding[field]
    before_read = {key: _snapshot(root) for key, root in roots.items()}
    # This exact comparison also covers rejected-row provenance and the sealed
    # snapshot, not just the first selected-source comparison.
    assert service.get_catalyst_observations(DATE) == captured
    response = client.get(f"/api/v4/manager/research/catalyst-observations?date={DATE}")
    assert response.status_code == 200
    assert response.json() == captured
    current = _get(client)
    assert current["plan_product"]["status"] == "CURRENT"
    assert current["plan_product"]["consumed"] is True
    assert current["input_identity"] == first["input_identity"] == saved["input_identity"]
    assert current["plan_product"]["run_id"] == saved["run_id"]
    assert current["plan_product"]["sha256"] == saved["sha256"]
    diagnostic = current["plan_product"]["input_identity_diagnostic"]
    assert diagnostic["status"] == "MATCH" and diagnostic["changed_components"] == []
    assert diagnostic["provenance_changes"]
    _export_workspace("materialized_catalyst_manifest_only_match", current)
    assert service.get_workspace_plan(DATE) == saved
    assert {key: _snapshot(root) for key, root in roots.items()} == before_read
    assert all(current[key] is flag for key, flag in FLAGS.items())


def test_materialized_archive_catalyst_frozen_replay_never_enumerates_new_slots(materialized_archive_catalyst, monkeypatch):
    service, _client, roots, captured = materialized_archive_catalyst
    source = service._existing_research_source
    payload = source.store.read_exact(PUBLICATION)
    source.hourly_store.publish(payload, slot="1800", mode="LIVE")
    assert source.hourly_store.list_slots(PUBLICATION, mode="LIVE") == ["1800"]

    def enumeration_forbidden(*args, **kwargs):
        raise AssertionError("FROZEN_REPLAY_MUST_NOT_ENUMERATE_NEW_SOURCES")

    monkeypatch.setattr(source.hourly_store, "list_slots", enumeration_forbidden)
    before = {key: _snapshot(root) for key, root in roots.items()}
    assert service.get_catalyst_observations(DATE) == captured
    assert all(row["slot"] != "1800" for row in captured["archive_projection"]["snapshot"]["selections"])
    assert {key: _snapshot(root) for key, root in roots.items()} == before


@pytest.mark.parametrize("part", ["resealed_content", "unsealed_payload", "receipt", "manifest_entry", "availability", "artifact_removed", "source_lost"])
def test_materialized_archive_catalyst_rejects_consumed_source_changes(materialized_archive_catalyst, part):
    service, client, roots, _captured = materialized_archive_catalyst
    source = service._existing_research_source
    _refresh_material_plan(service)
    saved = service.get_workspace_plan(DATE)
    binding = source.artifact_binding(PUBLICATION)
    _add_unconsumed_entry(source)
    if part == "resealed_content":
        _rewrite_payload_and_receipt(source, "source_title", "星海科技业务记录：来源已变化")
    elif part == "availability":
        # The fixed daily/hourly schema does not admit these clocks. Preserve
        # that rejection rather than fabricate a newly supported owner row.
        _rewrite_payload_and_receipt(source, "available_at", "2026-10-08T17:02:00+08:00")
    elif part == "unsealed_payload":
        payload = source.store._read(binding["payload_path"])
        payload["articles"][0]["source_title"] = "未经封存的正文"
        source.store._write(binding["payload_path"], payload)
    elif part == "receipt":
        receipt = source.store._read(binding["receipt_path"])
        receipt["payload_sha256"] = "8" * 64
        source.store._write(binding["receipt_path"], receipt)
    elif part == "manifest_entry":
        manifest = source.store._manifest()
        manifest[binding["payload_path"]] = "7" * 64
        source.store._write_manifest(manifest)
    elif part == "artifact_removed":
        for field in ("payload_path", "receipt_path"):
            (roots["research"] / binding[field]).unlink()
        manifest = source.store._manifest()
        manifest.pop(binding["payload_path"])
        source.store._write_manifest(manifest)
    else:
        service._existing_research_source = None
    before_read = {key: _snapshot(root) for key, root in roots.items()}
    with pytest.raises(ValueError, match="ARCHIVE_CATALYST_SOURCE"):
        service.get_catalyst_observations(DATE)
    rejected = client.get(f"/api/v4/manager/research/catalyst-observations?date={DATE}")
    assert rejected.status_code == 409 and "cards" not in rejected.json()
    current = _get(client)
    assert current["plan_product"]["status"] == "STALE_INPUTS_CHANGED"
    assert current["plan_product"]["consumed"] is False
    assert service.get_workspace_plan(DATE) == saved
    assert {key: _snapshot(root) for key, root in roots.items()} == before_read
    assert all(current[key] is flag for key, flag in FLAGS.items())


@pytest.mark.parametrize(("field", "value"), [
    ("payload_sha256", "1" * 64), ("receipt_sha256", "2" * 64),
    ("source_date", "20261007"), ("payload_path", "research/archives/20261007.json"),
    ("receipt_path", "receipts/research/archives/20261007.json"),
    ("source_root", "/isolated/rebound-owner"), ("mode", "REPLAY"),
    ("source_id", "ANOTHER_OWNER"), ("status", "CANNOT_CONFIRM"),
    ("manifest_sha256", "not-a-sha"),
])
def test_materialized_archive_catalyst_rejects_resealed_frozen_binding_changes(materialized_archive_catalyst, field, value):
    """A registry-only update cannot hide a forged consumed-source binding."""
    service, _client, roots, captured = materialized_archive_catalyst
    source = service._existing_research_source
    _add_unconsumed_entry(source)
    forged = deepcopy(captured)
    selected = next(row for row in forged["archive_projection"]["snapshot"]["selections"] if row["binding"])
    selected["binding"][field] = value
    from v4.manager_research.contracts import sha256_json
    forged["content_sha256"] = sha256_json({key: item for key, item in forged.items() if key != "content_sha256"})
    path = roots["manager"] / "catalyst_observations" / (DATE + ".json")
    path.write_text(json.dumps(forged, ensure_ascii=False))
    before = {key: _snapshot(root) for key, root in roots.items()}
    with pytest.raises(ValueError, match="ARCHIVE_CATALYST_SOURCE_CHANGED"):
        service.get_catalyst_observations(DATE)
    assert {key: _snapshot(root) for key, root in roots.items()} == before


@pytest.fixture
def explicit_clock_archive_projection_boundary(material_owner, monkeypatch):
    """Projection-boundary fixture, NOT an extended ResearchArchiveStore schema.

    The fixed store cannot supply available_at/retrieved_at. This substitutes
    only its output boundary with invented coherent payload/binding values so
    the unmodified clock, native master, card projector and full owner replay
    can be checked for the already supported explicit-clock projection shape.
    Real fixed-store coverage is in materialized_archive_catalyst above.
    """
    service, client, roots, *_ = material_owner
    from v4.manager_research import archive_catalyst_inputs, catalyst_observations
    from v4.manager_research.existing_materials import project_archive
    source = service._existing_research_source
    payload = deepcopy(source.store.read_exact(PUBLICATION))
    payload["articles"][0].update(available_at="2026-10-08T17:02:00+08:00", retrieved_at="2026-10-08T17:01:00+08:00")
    state = {"payload": payload}

    def read_projection_boundary(bound_source, day, slot):
        assert bound_source is source
        if day != PUBLICATION or slot:
            return [], [], None
        content = state["payload"]
        binding = source.artifact_binding(day)
        binding["payload_sha256"] = _sha256(content)
        binding["receipt_sha256"] = _sha256(source.store._receipt(content, binding["payload_sha256"]))
        rows, gaps = project_archive(content, binding, day)
        return rows, gaps, binding

    monkeypatch.setattr(archive_catalyst_inputs, "_read_archive", read_projection_boundary)
    monkeypatch.setattr(catalyst_observations, "_now", lambda: CLOCK)
    return service, client, roots, state


def test_archive_projection_boundary_nonempty_cards_keep_frozen_provenance(explicit_clock_archive_projection_boundary):
    service, _client, roots, _state = explicit_clock_archive_projection_boundary
    captured = service.refresh_catalyst_observations(DATE)
    archive = captured["archive_projection"]
    assert archive["coverage"]["clock_admitted_material_count"] == 1
    assert len(archive["cards"]) == 1 and archive["cards"][0]["symbol"] == "HK.90001"
    assert archive["snapshot"]["identity_witness"]["status"] == "OWNER_VERIFIED"
    assert service.get_catalyst_observations(DATE) == captured
    _add_unconsumed_entry(service._existing_research_source)
    before = {key: _snapshot(root) for key, root in roots.items()}
    # The unmodified owner compares the full archive projection and its final
    # cards. Preserving only the snapshot selection is insufficient here.
    assert service.get_catalyst_observations(DATE) == captured
    assert {key: _snapshot(root) for key, root in roots.items()} == before
    assert all(archive["cards"][0][key] is flag for key, flag in FLAGS.items())


def test_archive_projection_boundary_native_identity_loss_still_fails_closed(explicit_clock_archive_projection_boundary):
    service, _client, roots, _state = explicit_clock_archive_projection_boundary
    captured = service.refresh_catalyst_observations(DATE)
    witness = captured["archive_projection"]["snapshot"]["identity_witness"]
    assert captured["archive_projection"]["cards"]
    (roots["shared"] / "assets" / "hk_security_master" / witness["artifact_relative"]).unlink()
    _add_unconsumed_entry(service._existing_research_source)
    before = {key: _snapshot(root) for key, root in roots.items()}
    with pytest.raises(ValueError, match="ARCHIVE_CATALYST_IDENTITY_CHANGED"):
        service.get_catalyst_observations(DATE)
    assert {key: _snapshot(root) for key, root in roots.items()} == before


@pytest.mark.parametrize("clock_field", ["available_at", "retrieved_at"])
def test_archive_projection_boundary_acquisition_change_is_not_provenance(explicit_clock_archive_projection_boundary, clock_field):
    service, _client, _roots, state = explicit_clock_archive_projection_boundary
    captured = service.refresh_catalyst_observations(DATE)
    assert captured["archive_projection"]["cards"]
    state["payload"]["articles"][0][clock_field] = "2026-10-09T09:00:00+08:00"
    _add_unconsumed_entry(service._existing_research_source)
    with pytest.raises(ValueError, match="ARCHIVE_CATALYST_SOURCE_CHANGED"):
        service.get_catalyst_observations(DATE)
    replacement = service.refresh_catalyst_observations(DATE)
    assert replacement["archive_projection"]["cards"] == []
    assert replacement["archive_projection"]["rejected_materials"][0]["reason"] == "ARCHIVE_ACQUISITION_TIME_OUTSIDE_FROZEN_WINDOW"
