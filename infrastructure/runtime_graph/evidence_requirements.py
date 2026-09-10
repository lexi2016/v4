"""Validate that node-required evidence matches declared producers."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contracts import EvidenceLayer, required_evidence_layers


_EXECUTION_KINDS = frozenset({"receipt", "v35_receipt", "stage_latest"})
_ARTIFACT_KINDS = frozenset(
    {"json", "text_pointer", "artifact", "manifest", "acceptance", "v35_artifact", "stage_latest"}
)


def validate_required_evidence_declarations(node: Mapping[str, Any]) -> None:
    sources = node.get("status_sources")
    declared = tuple(source for source in (sources or ()) if isinstance(source, Mapping))
    capabilities = {EvidenceLayer.CALENDAR}
    if any(source.get("kind") in _EXECUTION_KINDS for source in declared):
        capabilities.add(EvidenceLayer.EXECUTION)
    if node.get("expected_outputs") or any(
        source.get("kind") in _ARTIFACT_KINDS for source in declared
    ):
        capabilities.add(EvidenceLayer.ARTIFACT)
    if node.get("api_probe"):
        capabilities.add(EvidenceLayer.API)
    if node.get("page_receipt"):
        capabilities.add(EvidenceLayer.PAGE)
    if set(required_evidence_layers(node)) != capabilities:
        raise ValueError("RUNTIME_GRAPH_REQUIRED_EVIDENCE_UNDECLARED")
