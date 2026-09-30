"""Validated, JSON-safe runtime graph snapshot composition."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from .contracts import EvidenceLayer, EvidenceResult, GraphStatus, reduce_graph_status, reduce_status, required_evidence_layers, to_jsonable
from .topology import topology_version_sha, validate_topology


_SHANGHAI = timezone(timedelta(hours=8))
_DATE_RE = re.compile(r"^\d{8}$")
_RUNTIME_KEYS = frozenset({"status", "reason", "evidence"})
SAFETY_FLAGS = ('production_allowed', 'buy_gate_updated', 'orders_sent')


def _business_date(value: Any) -> str:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise ValueError("RUNTIME_GRAPH_SNAPSHOT_DATE_INVALID")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise ValueError("RUNTIME_GRAPH_SNAPSHOT_DATE_INVALID") from exc
    return value


def _time(value: Any, *, required: bool) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            if required:
                raise ValueError("RUNTIME_GRAPH_SNAPSHOT_TIME_INVALID") from None
            return None
    else:
        if required:
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_TIME_INVALID")
        return None
    return parsed.replace(tzinfo=_SHANGHAI) if parsed.tzinfo is None else parsed.astimezone(_SHANGHAI)


def _time_payload(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _json_input(value: Any) -> Any:
    """Adapt JSON-like static topology values to the contract projection."""
    if isinstance(value, Mapping):
        return {key: _json_input(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return tuple(_json_input(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_json_input(item) for item in value)
    return value


def _project(value: Any) -> Any:
    return to_jsonable(_json_input(value))


def _freshness(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or value < 0:
        raise ValueError("RUNTIME_GRAPH_SNAPSHOT_FRESHNESS_INVALID")
    return float(value)


def _topology_time_reason(topology: Mapping[str, Any], generated_at: datetime, freshness: float) -> str | None:
    topology_at = _time(topology.get("generated_at"), required=False)
    if topology_at is None:
        return "TOPOLOGY_TIME_UNAVAILABLE"
    age = (generated_at - topology_at).total_seconds()
    if age < 0:
        return "TOPOLOGY_FUTURE"
    if age > freshness:
        return "TOPOLOGY_STALE"
    return None


def _trusted_evidence_result(value: Any) -> bool:
    if (
        type(value) is not EvidenceResult
        or not isinstance(value.layer, EvidenceLayer)
        or not isinstance(value.status, GraphStatus)
        or not isinstance(value.reason, str)
    ):
        return False
    try:
        value.to_payload()
    except (AttributeError, TypeError, ValueError):
        return False
    return True


def _valid_evidence(
    value: Any,
    required: tuple[EvidenceLayer, ...],
) -> tuple[EvidenceResult, ...] | None:
    if not isinstance(value, tuple | list) or not value:
        return None
    results = tuple(value)
    if (
        len(results) == 1
        and _trusted_evidence_result(results[0])
        and results[0].layer is EvidenceLayer.CALENDAR
        and results[0].status in {GraphStatus.NOT_DUE, GraphStatus.SKIPPED_EXPECTED}
    ):
        return results
    if len(results) != len(required) or not all(_trusted_evidence_result(item) for item in results):
        return None
    if any(item.status in {GraphStatus.NOT_DUE, GraphStatus.SKIPPED_EXPECTED} for item in results):
        return None
    by_layer = {item.layer: item for item in results}
    if len(by_layer) != len(required) or set(by_layer) != set(required):
        return None
    return tuple(by_layer[layer] for layer in required)


def _node_runtime(
    evidence: Any,
    required: tuple[EvidenceLayer, ...],
) -> tuple[GraphStatus, str, list[dict[str, Any]]]:
    results = _valid_evidence(evidence, required)
    if results is None:
        return GraphStatus.EVIDENCE_GAP, "EVIDENCE_INVALID", []
    status = reduce_status(results, required)
    reason = next(item.reason for item in results if item.status is status)
    return status, reason, [item.to_payload() for item in results]


def build_snapshot(
    *,
    topology: dict[str, Any],
    evidence_by_node: Any,
    business_date: str,
    generated_at: Any,
    topology_freshness_seconds: Any,
) -> dict[str, Any]:
    """Compose a trusted runtime snapshot without mutating topology or evidence."""
    validate_topology(topology)
    date = _business_date(business_date)
    now = _time(generated_at, required=True)
    assert now is not None
    freshness = _freshness(topology_freshness_seconds)
    version_sha = topology_version_sha(_project(topology))
    stale_reason = _topology_time_reason(topology, now, freshness)
    evidence_map = evidence_by_node if isinstance(evidence_by_node, Mapping) else {}
    nodes: list[dict[str, Any]] = []
    statuses: list[GraphStatus] = []
    reasons: list[str] = []
    for descriptor in topology["nodes"]:
        static = _project({key: value for key, value in descriptor.items() if key not in _RUNTIME_KEYS})
        node_id = str(descriptor["node_id"])
        if stale_reason is not None:
            status, reason, evidence = GraphStatus.EVIDENCE_GAP, stale_reason, []
        elif node_id not in evidence_map:
            status, reason, evidence = GraphStatus.EVIDENCE_GAP, "NO_EVIDENCE", []
        else:
            status, reason, evidence = _node_runtime(
                evidence_map[node_id],
                required_evidence_layers(descriptor),
            )
        static.update(status=status.value, reason=reason, evidence=evidence)
        static.update({flag: False for flag in SAFETY_FLAGS})
        nodes.append(static)
        statuses.append(status)
        reasons.append(reason)
    graph_status = reduce_graph_status(statuses)
    graph_reason = stale_reason or next(reason for status, reason in zip(statuses, reasons) if status is graph_status)
    return {
        "schema_version": "v3_runtime_snapshot.v1",
        "business_date": date,
        "generated_at": _time_payload(now),
        "topology_schema_version": topology["schema_version"],
        "topology_authority_root": topology["authority_root"],
        "topology_version_sha": version_sha,
        "nodes": nodes,
        "edges": _project(topology["edges"]),
        "status": graph_status.value,
        "reason": graph_reason,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
