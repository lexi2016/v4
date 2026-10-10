"""Independent review probe for the materialized original catalyst path.

Scratch-only synthetic fault injection; no production source edits or network.
"""
from __future__ import annotations

import json

from tests.test_manager_semantic_identity_20261010 import (
    app_owner, material_owner, DATE, PUBLICATION, CLOCK,
    _add_unconsumed_entry, _get, _refresh_material_plan, _snapshot,
)


def test_registry_only_update_with_materialized_catalyst_is_current(material_owner, monkeypatch):
    service, client, roots, _witness, _owner, _published = material_owner
    from v4.manager_research import catalyst_observations
    monkeypatch.setattr(catalyst_observations, "_now", lambda: CLOCK)

    catalyst = service.refresh_catalyst_observations(DATE)
    assert catalyst["archive_projection"]["coverage"]["archive_artifact_count"] == 1
    first = _refresh_material_plan(service)
    current = _get(client)
    assert current["plan_product"]["status"] == "CURRENT"
    source = service._existing_research_source
    binding_before = source.artifact_binding(PUBLICATION)
    _add_unconsumed_entry(source)
    binding_after = source.artifact_binding(PUBLICATION)
    assert binding_before["manifest_sha256"] != binding_after["manifest_sha256"]
    assert binding_before["payload_sha256"] == binding_after["payload_sha256"]
    assert binding_before["receipt_sha256"] == binding_after["receipt_sha256"]
    before_read = {name: _snapshot(root) for name, root in roots.items()}
    later = _get(client)
    assert {name: _snapshot(root) for name, root in roots.items()} == before_read
    diagnostic = later["plan_product"].get("input_identity_diagnostic", {})
    print(json.dumps({"case": "registry_only_materialized_catalyst",
        "before_status": current["plan_product"]["status"],
        "after_status": later["plan_product"]["status"],
        "after_consumed": later["plan_product"]["consumed"],
        "identity_changed": first["input_identity"] != later["input_identity"],
        "payload_receipt_unchanged": True,
        "catalyst_gaps": [gap for gap in later["gaps"] if "CATALYST" in gap],
        "changed_component_ids": [row["component_id"] for row in diagnostic.get("changed_components", [])],
        "provenance_changes": len(diagnostic.get("provenance_changes", [])),
        "get_side_effects": "NONE"}, sort_keys=True))
    assert later["plan_product"]["status"] == "CURRENT"
