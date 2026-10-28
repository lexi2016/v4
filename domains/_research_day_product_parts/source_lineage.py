"""domains.research_day_product: source_lineage (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __lineage_ref_body(_v4_scope, /, slot, payload, source_ref):
    ref = _v4_global(_v4_scope, 'dict')(source_ref or {})
    artifact_sha = _v4_global(_v4_scope, '_text')(ref.get("artifact_sha256") or payload.get("artifact_sha256"))
    receipt_sha = _v4_global(_v4_scope, '_text')(ref.get("receipt_sha256") or payload.get("receipt_sha256"))
    source_input_sha = _v4_global(_v4_scope, '_text')(
        ref.get("source_input_sha256") or payload.get("source_input_sha256")
    )
    if not artifact_sha:
        artifact_sha = _v4_global(_v4_scope, '_sha256')({"slot": slot, "payload": payload})
    if not receipt_sha:
        receipt_sha = _v4_global(_v4_scope, '_sha256')({"slot": slot, "artifact_sha256": artifact_sha})
    if not source_input_sha:
        source_input_sha = _v4_global(_v4_scope, '_sha256')(payload)
    return {
        "artifact_path": _v4_global(_v4_scope, '_text')(
            ref.get("artifact_path")
            or f"research/hourly/live/{{date}}/{slot}.json"
        ),
        "artifact_sha256": artifact_sha.lower(),
        "receipt_path": _v4_global(_v4_scope, '_text')(
            ref.get("receipt_path")
            or f"receipts/research/hourly/live/{{date}}/{slot}.json"
        ),
        "receipt_sha256": receipt_sha.lower(),
        "source_input_sha256": source_input_sha.lower(),
    }


def __registry_projection_body(_v4_scope, /, registry):
    if not _v4_global(_v4_scope, 'isinstance')(registry, _v4_global(_v4_scope, 'Mapping')) or registry.get("status") != "VALIDATED":
        return (
            [],
            {
                "status": "CANNOT_CONFIRM",
                "rule_id": None,
                "registry": "MISSING",
                "cannot_confirm": _v4_global(_v4_scope, '_MISSING_REGISTRY_GAP'),
            },
            [_v4_global(_v4_scope, '_MISSING_REGISTRY_GAP')],
        )
    rule_id = _v4_global(_v4_scope, '_text')(registry.get("rule_id"))
    rows = registry.get("high_priority")
    if not _v4_global(_v4_scope, 'isinstance')(rows, _v4_global(_v4_scope, 'list')) or not rule_id:
        return (
            [],
            {
                "status": "CANNOT_CONFIRM",
                "rule_id": rule_id or None,
                "registry": "MISSING",
                "cannot_confirm": _v4_global(_v4_scope, '_MISSING_REGISTRY_GAP'),
            },
            [_v4_global(_v4_scope, '_MISSING_REGISTRY_GAP')],
        )
    projected: list[dict[str, Any]] = []
    for row in rows:
        if not _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'Mapping')) or row.get("rule_id") != rule_id:
            raise _v4_global(_v4_scope, 'ValueError')("high priority must carry the producer frozen rule_id")
        if "rank" not in row or "reason" not in row:
            raise _v4_global(_v4_scope, 'ValueError')("high priority requires producer rank and reason")
        projected.append(
            {
                "stock_code": _v4_global(_v4_scope, '_text')(row.get("stock_code")),
                "rank": row["rank"],
                "reason": _v4_global(_v4_scope, '_text')(row.get("reason")),
                "rule_id": rule_id,
                "recommendation_status": "RESEARCH_ONLY",
            }
        )
    return (
        _v4_global(_v4_scope, 'sorted')(projected, key=lambda row: (row["rank"], row["stock_code"])),
        {
            "status": "READY",
            "rule_id": rule_id,
            "registry": "VALIDATED",
            "cannot_confirm": None,
        },
        [],
    )


def __jyg_coverage_body(_v4_scope, /, registry):
    """Project only explicitly supplied JYG observations; never infer them."""

    if not _v4_global(_v4_scope, 'isinstance')(registry, _v4_global(_v4_scope, 'Mapping')):
        observed: Mapping[str, Any] = {}
        status = "CANNOT_CONFIRM"
        registry_status = "MISSING"
    else:
        candidate = registry.get("jyg_coverage") or registry.get("observed")
        if _v4_global(_v4_scope, 'isinstance')(candidate, _v4_global(_v4_scope, 'Mapping')):
            observed = candidate
            status = "VALIDATED" if registry.get("status") == "VALIDATED" else "CANNOT_CONFIRM"
            registry_status = "VALIDATED" if status == "VALIDATED" else "MISSING"
        else:
            observed = {}
            status = "CANNOT_CONFIRM"
            registry_status = "MISSING"
    result = {
        "status": status,
        "articles": observed.get("articles") if _v4_global(_v4_scope, 'type')(observed.get("articles")) is _v4_global(_v4_scope, 'int') else None,
        "expected_articles": observed.get("expected_articles") if _v4_global(_v4_scope, 'type')(observed.get("expected_articles")) is _v4_global(_v4_scope, 'int') else None,
        "stock_mentions": observed.get("stock_mentions") if _v4_global(_v4_scope, 'type')(observed.get("stock_mentions")) is _v4_global(_v4_scope, 'int') else None,
        "registry": registry_status,
        "gap": None if status == "VALIDATED" else _v4_global(_v4_scope, '_MISSING_REGISTRY_GAP'),
    }
    return result


def __selection_source_ref_body(_v4_scope, /, card, source_ref, *, source_date):
    if not _v4_global(_v4_scope, 'isinstance')(source_ref, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("selection card source reference is required")
    result = _v4_global(_v4_scope, 'dict')(source_ref)
    source_type = result.get("type", "EARLY_DRAFT_FROZEN_ENVELOPE")
    result.setdefault("type", source_type)
    result.setdefault("source_date", source_date)
    if source_type == _v4_global(_v4_scope, 'RESEARCH_SUPPLY_TYPE'):
        # New supply refs are a closed locator contract.  Do not add the
        # legacy denormalized source fields: the selected card and its raw
        # envelope are the source of truth and are verified by the store.
        if _v4_global(_v4_scope, 'set')(result) != {
            "type",
            "path",
            "raw_sha256",
            "frozen_payload_sha256",
            "json_pointer",
            "source_date",
            "source_time",
            "supply_receipt_path",
            "supply_receipt_sha256",
        }:
            raise _v4_global(_v4_scope, 'ValueError')("research supply source reference fields are invalid")
        return result
    else:
        source = card.get("source") if _v4_global(_v4_scope, 'isinstance')(card.get("source"), _v4_global(_v4_scope, 'Mapping')) else {}
        result.setdefault("official_url", source.get("official_url", ""))
        result.setdefault("published_at", source.get("published_at", ""))
        result.setdefault("source_status", source.get("status", ""))
    if not result.get("source_time"):
        raise _v4_global(_v4_scope, 'ValueError')("selection card source_time is required")
    return result
