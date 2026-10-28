"""contracts.research_day_product: market_scope (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _selection_market_scope_body(_v4_scope, /, payload):
    """Infer the market scope from the candidate identities in a product.

    The inferred scope deliberately comes from each candidate's normalized
    market rather than from a caller-provided focus.  This keeps an A-share
    or mixed-source product from passing merely because a consumer requested
    the HK_CONNECT view.
    """

    candidates = payload.get("research_candidates")
    if not _v4_global(_v4_scope, 'isinstance')(candidates, _v4_global(_v4_scope, 'list')) or not candidates:
        return None
    scopes: set[str] = _v4_global(_v4_scope, 'set')()
    for candidate in candidates:
        if not _v4_global(_v4_scope, 'isinstance')(candidate, _v4_global(_v4_scope, 'Mapping')):
            raise _v4_global(_v4_scope, 'ValueError')("selection market scope candidate is invalid")
        market = _v4_global(_v4_scope, '_selection_market_name')(candidate.get("market"))
        if market is None:
            entity_id = candidate.get("entity_id")
            if _v4_global(_v4_scope, 'isinstance')(entity_id, _v4_global(_v4_scope, 'str')) and "." in entity_id:
                market = _v4_global(_v4_scope, '_selection_market_name')(entity_id.rsplit(".", 1)[1])
        if market is None:
            raise _v4_global(_v4_scope, 'ValueError')("selection market scope is unknown")
        scopes.add(market)
    if _v4_global(_v4_scope, 'len')(scopes) > 1:
        return "MIXED"
    return _v4_global(_v4_scope, 'next')(_v4_global(_v4_scope, 'iter')(scopes))


def _validate_selection_market_scope_body(_v4_scope, /, payload, *, market_focus):
    """Validate the declared/inferred market scope and optional HK focus."""

    inferred = _v4_global(_v4_scope, 'selection_market_scope')(payload)
    declared_value = payload.get("market_scope")
    declared: str | None = None
    if declared_value is not None:
        if not _v4_global(_v4_scope, 'isinstance')(declared_value, _v4_global(_v4_scope, 'str')) or declared_value not in _v4_global(_v4_scope, 'SELECTION_MARKET_SCOPES'):
            raise _v4_global(_v4_scope, 'ValueError')("selection market_scope declaration is invalid")
        declared = declared_value
        if inferred is not None and declared != inferred:
            raise _v4_global(_v4_scope, 'ValueError')("selection market_scope declaration does not match candidates")
    effective = declared or inferred
    if effective == "MIXED" and declared is None and payload.get("status") == "READY":
        raise _v4_global(_v4_scope, 'ValueError')("selection market scope must be declared for mixed sources")
    if payload.get("status") == "READY" and effective == "A_SHARE":
        raise _v4_global(_v4_scope, 'ValueError')(f"selection market scope {effective} cannot be READY")
    if market_focus is not None:
        requested = _v4_global(_v4_scope, '_selection_market_name')(market_focus)
        if requested != _v4_global(_v4_scope, 'SELECTION_MARKET_FOCUS'):
            raise _v4_global(_v4_scope, 'ValueError')("selection market focus is forced to HK_CONNECT")
        if effective is not None and effective != _v4_global(_v4_scope, 'SELECTION_MARKET_FOCUS'):
            raise _v4_global(_v4_scope, 'ValueError')(
                f"selection market scope {effective} is incompatible with market focus HK_CONNECT"
            )
    return effective


def _selection_source_scope_invalidation_id_body(_v4_scope, /, value):
    """Return the content id for an append-only source-scope record."""

    if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'ValueError')("selection source-scope invalidation is not an object")
    body = {
        key: item for key, item in value.items() if key != "invalidation_id"
    }
    return _v4_global(_v4_scope, 'hashlib').sha256(
        _v4_global(_v4_scope, 'json').dumps(
            body,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _validate_selection_source_scope_invalidation_body(_v4_scope, /, value, *, expected_target_trade_date):
    """Validate one independent, append-only upstream scope invalidation."""

    if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(value) != _v4_global(_v4_scope, '_SELECTION_SOURCE_SCOPE_INVALIDATION_FIELDS'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection source-scope invalidation fields")
    if value.get("schema_version") != _v4_global(_v4_scope, 'SELECTION_SOURCE_SCOPE_INVALIDATION_SCHEMA_VERSION'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection source-scope invalidation schema")
    if value.get("type") != _v4_global(_v4_scope, 'SELECTION_SOURCE_SCOPE_INVALIDATION_TYPE'):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection source-scope invalidation type")
    invalidation_id = value.get("invalidation_id")
    if not _v4_global(_v4_scope, 'isinstance')(invalidation_id, _v4_global(_v4_scope, 'str')) or not _v4_global(_v4_scope, '_SELECTION_SHA256').fullmatch(invalidation_id.lower()):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection source-scope invalidation id")
    if _v4_global(_v4_scope, 'selection_source_scope_invalidation_id')(value) != invalidation_id.lower():
        raise _v4_global(_v4_scope, 'ValueError')("selection source-scope invalidation id mismatch")
    source_date = _v4_global(_v4_scope, '_selection_date')(value.get("source_date"), "source_date")
    target_trade_date = _v4_global(_v4_scope, '_selection_date')(
        value.get("target_trade_date"), "target_trade_date"
    )
    if (
        expected_target_trade_date is not None
        and target_trade_date != expected_target_trade_date
    ):
        raise _v4_global(_v4_scope, 'ValueError')("selection source-scope invalidation target date mismatch")
    prior_run_id = value.get("prior_run_id")
    if not _v4_global(_v4_scope, 'isinstance')(prior_run_id, _v4_global(_v4_scope, 'str')) or not _v4_global(_v4_scope, '_SELECTION_RUN_ID').fullmatch(prior_run_id):
        raise _v4_global(_v4_scope, 'ValueError')("selection source-scope prior run id is invalid")
    _v4_global(_v4_scope, '_selection_sha')(value.get("prior_product_sha256"), "prior product SHA")
    expected_focus = value.get("expected_market_focus")
    if expected_focus != _v4_global(_v4_scope, 'SELECTION_MARKET_FOCUS'):
        raise _v4_global(_v4_scope, 'ValueError')("selection source-scope expected market focus must be HK_CONNECT")
    observed_scope = value.get("observed_source_scope")
    if observed_scope not in _v4_global(_v4_scope, 'SELECTION_MARKET_SCOPES'):
        raise _v4_global(_v4_scope, 'ValueError')("selection source-scope observed scope is invalid")
    if observed_scope == expected_focus:
        raise _v4_global(_v4_scope, 'ValueError')("selection source-scope invalidation has no scope mismatch")
    evidence_refs = value.get("evidence_refs")
    if not _v4_global(_v4_scope, 'isinstance')(evidence_refs, _v4_global(_v4_scope, 'list')) or _v4_global(_v4_scope, 'len')(evidence_refs) < 2:
        raise _v4_global(_v4_scope, 'ValueError')("selection source-scope evidence refs are incomplete")
    evidence_kinds: set[str] = _v4_global(_v4_scope, 'set')()
    for ref in evidence_refs:
        if not _v4_global(_v4_scope, 'isinstance')(ref, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(ref) != _v4_global(_v4_scope, '_SELECTION_SOURCE_SCOPE_EVIDENCE_FIELDS'):
            raise _v4_global(_v4_scope, 'ValueError')("invalid selection source-scope evidence ref")
        kind = ref.get("kind")
        if not _v4_global(_v4_scope, 'isinstance')(kind, _v4_global(_v4_scope, 'str')) or not kind.strip():
            raise _v4_global(_v4_scope, 'ValueError')("selection source-scope evidence kind is invalid")
        evidence_kinds.add(kind)
        if not _v4_global(_v4_scope, 'isinstance')(ref.get("path"), _v4_global(_v4_scope, 'str')) or not ref["path"]:
            raise _v4_global(_v4_scope, 'ValueError')("selection source-scope evidence path is missing")
        _v4_global(_v4_scope, '_selection_sha')(ref.get("raw_sha256"), "source-scope evidence SHA")
        pointer = ref.get("json_pointer")
        if not _v4_global(_v4_scope, 'isinstance')(pointer, _v4_global(_v4_scope, 'str')) or not pointer.startswith("/"):
            raise _v4_global(_v4_scope, 'ValueError')("selection source-scope evidence JSON pointer is invalid")
        if ref.get("observed_source_scope") != observed_scope:
            raise _v4_global(_v4_scope, 'ValueError')("selection source-scope evidence scope mismatch")
    if not {"DISPATCHER", "HOURLY"}.issubset(evidence_kinds):
        raise _v4_global(_v4_scope, 'ValueError')("selection source-scope evidence lacks dispatcher/hourly refs")
    if not _v4_global(_v4_scope, 'isinstance')(value.get("reason"), _v4_global(_v4_scope, 'str')) or not value["reason"].strip():
        raise _v4_global(_v4_scope, 'ValueError')("selection source-scope invalidation reason is invalid")
    _v4_global(_v4_scope, '_selection_timestamp')(value.get("generated_at"), "source-scope invalidation generated_at")
    safety = value.get("safety")
    if not _v4_global(_v4_scope, 'isinstance')(safety, _v4_global(_v4_scope, 'Mapping')) or _v4_global(_v4_scope, 'set')(safety) != _v4_global(_v4_scope, 'set')(_v4_global(_v4_scope, 'SAFETY_FLAGS')):
        raise _v4_global(_v4_scope, 'ValueError')("invalid selection source-scope invalidation safety")
    for field, expected in _v4_global(_v4_scope, 'SAFETY_FLAGS').items():
        if safety.get(field) is not expected:
            raise _v4_global(_v4_scope, 'ValueError')(f"unsafe selection source-scope invalidation boundary: {field}")
    return target_trade_date
