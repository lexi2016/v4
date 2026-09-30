"""infrastructure.stage_acquisition_universe_contracts: primitives (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __canonical_code_body(_v4_scope, /, row, pool_id, index):
    value = row.get("symbol")
    if value in (None, ""):
        value = row.get("normalized_code")
    if value in (None, ""):
        value = row.get("code")
    if value in (None, ""):
        value = row.get("stock_code")
    if value in (None, ""):
        value = row.get("ts_code")
    text = _v4_global(_v4_scope, 'str')(value or "").strip().upper()
    if text.endswith((".SH", ".SZ", ".BJ")):
        text = text[:-3]
    if _v4_global(_v4_scope, 're').fullmatch(r"\d{6}", text):
        text = f"A.{text}"
    if not _v4_global(_v4_scope, '_A_CODE').fullmatch(text):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            f"required A pool {pool_id} row {index} has invalid code"
        )
    market = _v4_global(_v4_scope, 'str')(row.get("market") or "").strip().upper()
    if market and market not in _v4_global(_v4_scope, '_MARKET_ALIASES'):
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            f"required A pool {pool_id} row {index} is not market A"
        )
    return text


def __parse_date_field_body(_v4_scope, /, key, value, trade_date, location):
    """Reject malformed or post-trade-date signal/target metadata."""

    if value in (None, ""):
        return
    text = _v4_global(_v4_scope, 'str')(value).strip()
    try:
        parsed = _v4_global(_v4_scope, '_date')(text)
    except _v4_global(_v4_scope, 'ValueError') as error:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            f"{location} {key} is not an exact date"
        ) from error
    if parsed > trade_date:
        raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
            f"{location} {key} is a future date"
        )


def __walk_forbidden_outcomes_body(_v4_scope, /, value, location):
    if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')):
        for key, nested in value.items():
            folded = _v4_global(_v4_scope, 'str')(key).casefold()
            if (
                folded in _v4_global(_v4_scope, '_FORBIDDEN_OUTCOME_FIELDS')
                or _v4_global(_v4_scope, 'any')(token in folded for token in ("future_", "label_", "post_event_"))
            ):
                raise _v4_global(_v4_scope, 'StageAcquisitionContractError')(
                    f"{location}.{key} is a forbidden future outcome field"
                )
            _v4_global(_v4_scope, '_walk_forbidden_outcomes')(nested, f"{location}.{key}")
    elif _v4_global(_v4_scope, 'isinstance')(value, (_v4_global(_v4_scope, 'list'), _v4_global(_v4_scope, 'tuple'))):
        for index, nested in _v4_global(_v4_scope, 'enumerate')(value):
            _v4_global(_v4_scope, '_walk_forbidden_outcomes')(nested, f"{location}[{index}]")


def _split_cannot_confirm_body(_v4_scope, /, reasons):
    """Split source reasons into ``(blocking, policy_notes)`` in source order."""

    blocking: list[str] = []
    notes: list[str] = []
    for raw in reasons:
        reason = _v4_global(_v4_scope, 'str')(raw or "").strip()
        if not reason:
            continue
        target = notes if _v4_global(_v4_scope, 'is_non_blocking_policy_note')(reason) else blocking
        if reason not in target:
            target.append(reason)
    return _v4_global(_v4_scope, 'tuple')(blocking), _v4_global(_v4_scope, 'tuple')(notes)
