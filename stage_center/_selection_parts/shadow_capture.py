"""stage_center.selection: shadow_capture (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __invoke_hk_formula_margin_shadow_body(_v4_scope, /, callback, *, raw_rows, sorted_rows, production_rows, trade_date, stage_id, raw_artifact_sha256, source_status, requested_rows, source_evidence, shadow_context, error_callback):
    """Call the opt-in shadow observer with isolated copies of selector data.

    ``sorted_rows`` is copied immediately after the real comparator has run and
    before the public recommendation cap.  ``production_rows`` is the exact
    capped slice which the selector is about to return.  A callback therefore
    gets both the full rank source and the production Top10 without changing
    the selector envelope.  The copies also prevent an observer from mutating
    the rows subsequently returned by the production selector.

    This boundary intentionally swallows observer failures.  A research
    capture or its disk cannot change a production selection result.  Callers
    that want an immutable invalid ledger can provide ``error_callback``;
    errors from that callback are isolated as well.
    """

    if stage_id not in _v4_global(_v4_scope, 'HK_FORMULA_MARGIN_SHADOW_STAGES'):
        return
    context: dict[str, Any] = {}
    if _v4_global(_v4_scope, 'isinstance')(shadow_context, _v4_global(_v4_scope, 'Mapping')):
        try:
            context = _v4_global(_v4_scope, 'copy').deepcopy(_v4_global(_v4_scope, 'dict')(shadow_context))
        except _v4_global(_v4_scope, 'Exception'):
            context = {}
    context.update(
        {
            "trade_date": trade_date,
            "stage": stage_id,
            "raw_artifact_sha256": raw_artifact_sha256,
            "source_status": source_status,
            "requested_rows": requested_rows,
            "source_evidence": _v4_global(_v4_scope, 'list')(source_evidence),
            "selector_hook": "HK_FORMULA_MARGIN_SHADOW_V1",
        }
    )
    try:
        copied_sorted = _v4_global(_v4_scope, 'copy').deepcopy(_v4_global(_v4_scope, 'list')(sorted_rows))
        # Every row passed through the real four-lane selector participates in
        # the selector ranking.  This is an acquisition fact and is kept
        # separate from the public ``formal_eligible`` research overlay.
        for row in copied_sorted:
            if _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'dict')):
                row["selection_eligible"] = True
        callback(
            raw_rows=_v4_global(_v4_scope, 'copy').deepcopy(_v4_global(_v4_scope, 'list')(raw_rows)),
            sorted_rows=copied_sorted,
            production_rows=_v4_global(_v4_scope, 'copy').deepcopy(_v4_global(_v4_scope, 'list')(production_rows)),
            context=context,
        )
    except _v4_global(_v4_scope, 'Exception') as error:  # pragma: no cover - the callback is external
        if error_callback is None:
            return
        try:
            error_callback(error=error, context=context)
        except _v4_global(_v4_scope, 'Exception'):
            return
