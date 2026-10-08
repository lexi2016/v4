"""Unresolved P2 reproducer; no nested allowlist is proposed without its producer schema.

The synthetic extension below mirrors the original top-level unknown-field
regression. It demonstrates that nested schema objects are currently open;
these probes must remain explicitly RED until the original nested v1 schema
and its real producer outputs define a compatible allowlist.
"""
from __future__ import annotations

import pytest

from frozen_fixtures import asof_payload
from infrastructure.preselection_pool_store import PreselectionPoolStore


@pytest.mark.parametrize("nested_field", ["eligibility_asof", "price_recovery"])
def test_unregistered_nested_object_extension_is_rejected(tmp_path, nested_field):
    payload = asof_payload()
    payload["historical_provenance"][nested_field]["unregistered_extension"] = "value"
    root = tmp_path / "data"

    with pytest.raises(ValueError):
        PreselectionPoolStore(root).materialize(payload)

    assert not list(root.rglob("*.json"))
