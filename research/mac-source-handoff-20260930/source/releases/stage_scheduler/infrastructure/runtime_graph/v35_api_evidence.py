"""V3.5-owned, fail-closed API evidence projections.

The generic collector only dispatches here.  This module owns the fixed 8872
DTO paths and their date, row, market, and safety contracts; it never writes
runtime state or derives a result from an undeclared endpoint.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .contracts import EvidenceLayer, EvidenceResult, GraphStatus


HttpGet = Callable[[str], Any]

_POSITIVE_STATUSES = frozenset(
    {
        "READY",
        "PASS",
        "SUCCESS",
        "COMPLETED",
        "MODEL_REVIEW_READY",
        "V192_CANDIDATE_READY",
        "STRICT_0_2_READY",
        "PARTIAL_WITH_ROWS",
        "PARTIAL_WITH_WATCH_ROWS",
    }
)
_FAILURE_STATUSES = frozenset(
    {"FAIL", "FAILED", "ERROR", "ABORTED", "CANCELLED", "CANNOT_CONFIRM", "NOT_MATERIALIZED"}
)
_RECEIPT_SUCCESS = frozenset({"PASS", "READY", "SUCCESS", "COMPLETED", "ACTION_OK"})
_RECEIPT_FAILURE = frozenset({"FAIL", "FAILED", "ERROR", "ABORTED", "CANCELLED", "ACTION_FAILED"})
_DEFAULT_API_DATE_FIELDS = ("business_date", "trade_date", "current_date", "page_trade_date")
_STAGE_IDS = frozenset(
    {
        "STAGE_0925",
        "STAGE_0930_0935",
        "STAGE_0935_0940",
        "STAGE_0940_0945",
        "STAGE_0945_1030",
        "STAGE_1300_1315",
        "STAGE_1445_1500",
    }
)


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, str | int | bool):
        return value
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    if isinstance(value, Mapping):
        return {str(key): _safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_safe_value(item) for item in value]
    return str(value)


def _safe_mapping(value: Any) -> dict[str, Any]:
    return _safe_value(value) if isinstance(value, Mapping) else {}


def _api_probe_url(probe: Mapping[str, Any], business_date: str, target_date: str | None) -> str | None:
    """Render only the frozen, same-origin 8872 DTO paths."""
    path = probe.get("path")
    if not isinstance(path, str) or not path:
        return None
    if path == "/api/v3/review?date={date}":
        return path.replace("{date}", business_date)
    if path == "/api/v3/preselection-pools?date={target_date}&limit=200":
        return path.replace("{target_date}", target_date) if isinstance(target_date, str) and target_date else None
    if path.startswith("/api/v3/workbench/stage?date={date}&stage=") and path.endswith("&limit=10"):
        stage_id = path.split("stage=", 1)[1].split("&", 1)[0]
        if stage_id not in _STAGE_IDS or probe.get("stage_id") != stage_id:
            return None
        return path.replace("{date}", business_date)
    return None


def _api_probe_safety(payload: Mapping[str, Any]) -> bool:
    return all(payload.get(flag) is False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))


def _api_review_projection(
    payload: Mapping[str, Any], probe: Mapping[str, Any], node_id: str, business_date: str
) -> tuple[bool, str, dict[str, Any], list[Any]]:
    if payload.get("ok") is False or str(payload.get("trade_date") or "") != business_date or not _api_probe_safety(payload):
        return False, "API_MISMATCH", {}, []
    markets = payload.get("market_reviews")
    if not isinstance(markets, Mapping):
        return False, "API_CANNOT_CONFIRM", {}, []
    if probe.get("kind") == "review_close_chain":
        a_review = markets.get("A")
        chain = a_review.get("close_chain") if isinstance(a_review, Mapping) else None
        if not isinstance(chain, Mapping) or str(chain.get("trade_date") or "") != business_date:
            return False, "API_CANNOT_CONFIRM", {}, []
        nodes = chain.get("nodes")
        target = (
            next((item for item in nodes or [] if isinstance(item, Mapping) and item.get("task_id") == node_id), None)
            if isinstance(nodes, list)
            else None
        )
        if not isinstance(target, Mapping):
            return False, "API_CANNOT_CONFIRM", {}, []
        status = str(target.get("status") or "").upper()
        evidence = target.get("evidence")
        if status not in _POSITIVE_STATUSES or str(target.get("business_date") or "") != business_date or not isinstance(evidence, list) or not evidence:
            return False, "API_CANNOT_CONFIRM", {}, []
        dates: list[Any] = [
            value
            for value in (
                payload.get("trade_date"),
                chain.get("trade_date"),
                target.get("business_date"),
                target.get("trade_date"),
            )
            if value is not None
        ]
        row_counts: list[int] = []
        for item in evidence:
            if not isinstance(item, Mapping) or str(item.get("trade_date") or "") != business_date:
                return False, "API_MISMATCH", {}, dates
            dates.append(item.get("trade_date"))
            count = item.get("row_count")
            if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
                row_counts.append(count)
        if not row_counts:
            return False, "API_CANNOT_CONFIRM", {}, dates
        return True, "API_PASS", {
            "trade_date": business_date,
            "close_chain_trade_date": business_date,
            "node": {
                "task_id": node_id,
                "business_date": target.get("business_date"),
                "trade_date": target.get("trade_date"),
                "status": status,
                "evidence_count": len(evidence),
                "row_counts": row_counts,
            },
        }, dates
    hk_review = markets.get("HK")
    model = hk_review.get("model_selection_review") if isinstance(hk_review, Mapping) else None
    if not isinstance(model, Mapping) or str(model.get("trade_date") or "") != business_date:
        return False, "API_CANNOT_CONFIRM", {}, [payload.get("trade_date")]
    dates = [payload.get("trade_date"), model.get("trade_date")]
    status = str(model.get("status") or "").upper()
    model_rows, stage_rows = model.get("model_rows"), model.get("stage_rows")
    if status not in _POSITIVE_STATUSES or not isinstance(model_rows, list) or not model_rows or not isinstance(stage_rows, list) or not stage_rows:
        return False, "API_CANNOT_CONFIRM", {}, dates
    return True, "API_PASS", {
        "trade_date": business_date,
        "model_selection_review": {
            "trade_date": model.get("trade_date"),
            "status": status,
            "model_row_count": len(model_rows),
            "stage_row_count": len(stage_rows),
        },
    }, dates


def _api_pool_projection(
    payload: Mapping[str, Any], probe: Mapping[str, Any], target_date: str
) -> tuple[bool, str, dict[str, Any], list[Any]]:
    dates: list[Any] = [payload.get("trade_date")]
    if payload.get("ok") is False or str(payload.get("trade_date") or "") != target_date or not _api_probe_safety(payload):
        return False, "API_MISMATCH", {}, dates
    status = str(payload.get("data_status") or "").upper()
    pools = payload.get("pools")
    if status not in {"READY_WITH_ROWS", "PARTIAL_WITH_ROWS"} or not isinstance(pools, list):
        return False, "API_CANNOT_CONFIRM", {}, dates
    pool_id = probe.get("pool_id")
    pool = next((item for item in pools if isinstance(item, Mapping) and item.get("pool_id") == pool_id), None)
    if not isinstance(pool, Mapping) or str(pool.get("trade_date") or "") != target_date:
        return False, "API_CANNOT_CONFIRM", {}, dates
    dates.append(pool.get("trade_date"))
    pool_status, rows, returned, size = str(pool.get("status") or "").upper(), pool.get("rows"), pool.get("returned_rows"), pool.get("pool_size")
    if pool_status in _FAILURE_STATUSES or not isinstance(rows, list) or not rows or not isinstance(returned, int) or isinstance(returned, bool) or returned != len(rows) or not isinstance(size, int) or isinstance(size, bool) or size < returned:
        return False, "API_CANNOT_CONFIRM", {}, dates
    expected_market = "HK" if pool_id == "hkconnect_d1_top100" else "A"
    for row in rows:
        if not isinstance(row, Mapping) or row.get("pool_id") != pool_id:
            return False, "API_CANNOT_CONFIRM", {}, dates
        if str(row.get("trade_date") or "") != target_date:
            return False, "API_MISMATCH", {}, dates + [row.get("trade_date")]
        if str(row.get("market") or "").upper() != expected_market:
            return False, "API_CANNOT_CONFIRM", {}, dates
        if "target_date" in row and str(row.get("target_date") or "") != target_date:
            return False, "API_MISMATCH", {}, dates + [row.get("target_date")]
    return True, "API_PASS", {
        "trade_date": target_date,
        "data_status": status,
        "pool": {
            "pool_id": pool_id,
            "trade_date": pool.get("trade_date"),
            "status": pool_status,
            "row_count": len(rows),
            "returned_rows": returned,
            "pool_size": size,
            "market": expected_market,
        },
    }, dates


def _api_stage_projection(
    payload: Mapping[str, Any], probe: Mapping[str, Any], business_date: str
) -> tuple[bool, str, dict[str, Any], list[Any]]:
    dates: list[Any] = [payload.get("trade_date")]
    if payload.get("ok") is False or str(payload.get("trade_date") or "") != business_date or not _api_probe_safety(payload):
        return False, "API_MISMATCH", {}, dates
    stage_id, stage, groups = probe.get("stage_id"), payload.get("stage"), payload.get("stage_groups")
    selected_total, unified = payload.get("selected_total_rows"), payload.get("unified_rows")
    if not isinstance(stage, Mapping) or stage.get("stage_id") != stage_id or str(stage.get("status") or "").upper() not in _POSITIVE_STATUSES or not isinstance(groups, list) or not isinstance(selected_total, int) or isinstance(selected_total, bool) or selected_total < 0 or not isinstance(unified, list):
        return False, "API_CANNOT_CONFIRM", {}, dates
    group_summary: list[dict[str, Any]] = []
    markets: set[str] = set()
    total = 0
    for group in groups:
        market = str(group.get("market") or "").upper() if isinstance(group, Mapping) else ""
        rows = group.get("rows") if isinstance(group, Mapping) else None
        if market not in {"A", "HK"} or market in markets or not isinstance(rows, list):
            return False, "API_CANNOT_CONFIRM", {}, dates
        if any(not isinstance(row, Mapping) or str(row.get("market") or "").upper() != market for row in rows):
            return False, "API_CANNOT_CONFIRM", {}, dates
        markets.add(market)
        total += len(rows)
        group_summary.append({"market": market, "row_count": len(rows)})
    if total != selected_total or len(unified) != selected_total or markets != {"A", "HK"}:
        return False, "API_CANNOT_CONFIRM", {}, dates
    for field in ("selected_a_rows", "selected_hk_rows"):
        if field in payload and (not isinstance(payload[field], int) or isinstance(payload[field], bool)):
            return False, "API_CANNOT_CONFIRM", {}, dates
    if all(field in payload for field in ("selected_a_rows", "selected_hk_rows")) and payload["selected_a_rows"] + payload["selected_hk_rows"] != selected_total:
        return False, "API_CANNOT_CONFIRM", {}, dates
    return True, "API_PASS", {
        "trade_date": business_date,
        "stage": {
            "stage_id": stage_id,
            "status": str(stage.get("status") or "").upper(),
            "group_summary": group_summary,
            "selected_total_rows": selected_total,
            "unified_row_count": len(unified),
        },
    }, dates


def _api_multi_evidence(
    node: Mapping[str, Any], business_date: str, target_date: str | None, http_get: HttpGet, probes: list[Any]
) -> EvidenceResult:
    records: list[dict[str, Any]] = []
    failure_reason: str | None = None
    failure_status = GraphStatus.EVIDENCE_GAP
    for raw_probe in probes:
        if not isinstance(raw_probe, Mapping):
            return EvidenceResult(EvidenceLayer.API, GraphStatus.EVIDENCE_GAP, "API_CANNOT_CONFIRM", {"probes": records})
        url = _api_probe_url(raw_probe, business_date, target_date)
        if url is None:
            return EvidenceResult(EvidenceLayer.API, GraphStatus.EVIDENCE_GAP, "API_PROBE_INVALID", {"probes": records})
        record: dict[str, Any] = {"url": url, "kind": raw_probe.get("kind"), "date_role": raw_probe.get("date_role", "business_date")}
        try:
            raw_payload = http_get(url)
        except Exception:
            record.update({"status": GraphStatus.EVIDENCE_GAP.value, "reason": "API_UNAVAILABLE"})
            records.append(record)
            failure_reason = "API_CANNOT_CONFIRM"
            continue
        if not isinstance(raw_payload, Mapping) or not raw_payload:
            record.update({"status": GraphStatus.EVIDENCE_GAP.value, "reason": "API_CANNOT_CONFIRM"})
            records.append(record)
            failure_reason = "API_CANNOT_CONFIRM"
            continue
        payload = _safe_mapping(raw_payload)
        node_id = str(node.get("node_id") or "")
        if raw_probe.get("kind") in {"review_close_chain", "review_model_selection"}:
            valid, reason, projection, dates = _api_review_projection(payload, raw_probe, node_id, business_date)
        elif raw_probe.get("kind") == "preselection_pool":
            valid, reason, projection, dates = _api_pool_projection(payload, raw_probe, target_date or "")
        elif raw_probe.get("kind") == "workbench_stage":
            valid, reason, projection, dates = _api_stage_projection(payload, raw_probe, business_date)
        else:
            valid, reason, projection, dates = False, "API_PROBE_INVALID", {}, []
        record.update({"status": GraphStatus.PASS.value if valid else GraphStatus.FAIL.value if reason == "API_MISMATCH" else GraphStatus.EVIDENCE_GAP.value, "reason": reason, "payload": projection, "date_values": dates})
        records.append(record)
        if not valid:
            failure_reason = reason if reason in {"API_MISMATCH", "API_PROBE_INVALID"} else "API_CANNOT_CONFIRM"
            if reason == "API_MISMATCH":
                failure_status = GraphStatus.FAIL
    if failure_reason is not None:
        return EvidenceResult(EvidenceLayer.API, failure_status, failure_reason, {"probes": records})
    return EvidenceResult(EvidenceLayer.API, GraphStatus.PASS, "API_PASS", {"probes": records})


def api_evidence(
    node: Mapping[str, Any], business_date: str, http_get: HttpGet, target_date: str | None = None
) -> EvidenceResult:
    """Collect exactly the API probes declared by a V3.5 binding."""
    raw_probe = node.get("api_probe")
    if isinstance(raw_probe, list | tuple):
        return _api_multi_evidence(node, business_date, target_date, http_get, list(raw_probe))
    if not isinstance(raw_probe, str) or not raw_probe:
        return EvidenceResult(EvidenceLayer.API, GraphStatus.EVIDENCE_GAP, "API_PROBE_UNDECLARED", {})
    url = raw_probe.replace("{date}", business_date)
    try:
        raw_payload = http_get(url)
    except Exception:
        return EvidenceResult(EvidenceLayer.API, GraphStatus.EVIDENCE_GAP, "API_UNAVAILABLE", {"url": url})
    if not isinstance(raw_payload, Mapping) or not raw_payload:
        return EvidenceResult(EvidenceLayer.API, GraphStatus.EVIDENCE_GAP, "API_UNAVAILABLE", {"url": url})
    payload = _safe_mapping(raw_payload)
    details = {"url": url, "payload": payload}
    status = str(payload.get("status") or payload.get("effective_status") or "").upper()
    if payload.get("ok") is False or status in _RECEIPT_FAILURE:
        return EvidenceResult(EvidenceLayer.API, GraphStatus.FAIL, "API_MISMATCH", details)
    declared_fields = node.get("api_date_fields")
    fields = tuple(field for field in declared_fields if isinstance(field, str) and field) if isinstance(declared_fields, list | tuple) else _DEFAULT_API_DATE_FIELDS
    dates = [payload[field] for field in fields if field in payload]
    if any(str(value) != business_date for value in dates):
        return EvidenceResult(EvidenceLayer.API, GraphStatus.FAIL, "API_MISMATCH", details)
    if not (payload.get("ok") is True or status in _RECEIPT_SUCCESS) or not dates:
        return EvidenceResult(EvidenceLayer.API, GraphStatus.EVIDENCE_GAP, "API_DATE_UNPROVEN", details)
    return EvidenceResult(EvidenceLayer.API, GraphStatus.PASS, "API_PASS", details)
