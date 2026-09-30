from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable


class GraphStatus(StrEnum):
    NOT_DUE = "NOT_DUE"
    SKIPPED_EXPECTED = "SKIPPED_EXPECTED"
    RUNNING = "RUNNING"
    PASS = "PASS"
    DEGRADED = "DEGRADED"
    FAIL = "FAIL"
    EVIDENCE_GAP = "EVIDENCE_GAP"


class EvidenceLayer(StrEnum):
    CALENDAR = "calendar"
    EXECUTION = "execution"
    ARTIFACT = "artifact"
    API = "api"
    PAGE = "page"


def required_evidence_layers(node: Mapping[str, Any]) -> tuple[EvidenceLayer, ...]:
    raw = node.get("required_evidence_layers")
    if not isinstance(raw, list | tuple) or not raw:
        raise ValueError("RUNTIME_GRAPH_REQUIRED_EVIDENCE_INVALID")
    try:
        layers = tuple(EvidenceLayer(value) for value in raw)
    except (TypeError, ValueError) as error:
        raise ValueError("RUNTIME_GRAPH_REQUIRED_EVIDENCE_INVALID") from error
    expected_order = tuple(layer for layer in EvidenceLayer if layer in layers)
    if (
        layers != expected_order
        or len(layers) != len(set(layers))
        or EvidenceLayer.CALENDAR not in layers
    ):
        raise ValueError("RUNTIME_GRAPH_REQUIRED_EVIDENCE_INVALID")
    return layers


def _freeze_details(value: Any) -> Any:
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("EVIDENCE_DETAILS_KEY_INVALID")
            frozen[key] = _freeze_details(item)
        return MappingProxyType(frozen)
    if isinstance(value, list | tuple):
        return tuple(_freeze_details(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze_details(item) for item in value)
    if value is None or isinstance(value, str | int | bool):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise TypeError("EVIDENCE_DETAILS_VALUE_INVALID")


def _json_sort_key(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        payload: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("EVIDENCE_DETAILS_KEY_INVALID")
            payload[key] = to_jsonable(item)
        return payload
    if isinstance(value, tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, frozenset):
        return sorted((to_jsonable(item) for item in value), key=_json_sort_key)
    if value is None or isinstance(value, str | int | bool):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise TypeError("EVIDENCE_DETAILS_VALUE_INVALID")


@dataclass(frozen=True)
class EvidenceResult:
    layer: EvidenceLayer
    status: GraphStatus
    reason: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        frozen_details = _freeze_details(self.details)
        if not isinstance(frozen_details, Mapping):
            raise TypeError("EVIDENCE_DETAILS_MAPPING_REQUIRED")
        object.__setattr__(self, "details", frozen_details)

    def to_payload(self) -> dict[str, Any]:
        return {
            "layer": self.layer.value,
            "status": self.status.value,
            "reason": self.reason,
            "details": to_jsonable(self.details),
        }


@dataclass(frozen=True)
class RuntimeNode:
    node_id: str
    label: str
    module: str
    scheduled_time: str
    page_sections: tuple[str, ...]
    upstream: tuple[str, ...]
    downstream: tuple[str, ...]
    evidence: tuple[EvidenceResult, ...]
    status: GraphStatus


_STATUS_PRIORITY = {
    GraphStatus.FAIL: 70,
    GraphStatus.EVIDENCE_GAP: 60,
    GraphStatus.DEGRADED: 50,
    GraphStatus.RUNNING: 40,
    GraphStatus.NOT_DUE: 30,
    GraphStatus.SKIPPED_EXPECTED: 20,
    GraphStatus.PASS: 10,
}


def reduce_status(
    results: Iterable[EvidenceResult],
    required_layers: Iterable[EvidenceLayer] | None = None,
) -> GraphStatus:
    values = tuple(results)
    if not values:
        return GraphStatus.EVIDENCE_GAP

    if all(
        item.layer is EvidenceLayer.CALENDAR
        and item.status in {GraphStatus.NOT_DUE, GraphStatus.SKIPPED_EXPECTED}
        for item in values
    ):
        return values[0].status
    required = tuple(required_layers) if required_layers is not None else tuple(EvidenceLayer)
    if set(required) != {item.layer for item in values}:
        return GraphStatus.EVIDENCE_GAP
    return reduce_graph_status(item.status for item in values)


def reduce_graph_status(statuses: Iterable[GraphStatus]) -> GraphStatus:
    values = tuple(statuses)
    if not values:
        return GraphStatus.EVIDENCE_GAP
    return max(values, key=_STATUS_PRIORITY.__getitem__)


def load_runtime_graph_contract(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if payload.get("schema_version") != "v3_runtime_graph_contract.v1":
        raise ValueError("RUNTIME_GRAPH_CONTRACT_VERSION_INVALID")
    return payload
