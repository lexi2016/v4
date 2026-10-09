"""TEST SUPPORT ONLY: accommodate a mismatched archived facade signature.

The supplied raw_store facade passes allow_temporal_false_observation=False
unconditionally, but its archived helper predates that keyword. This adapter
only strips that exact False value and delegates all rows to the unmodified
strict helper. True/other values are rejected. It is never an application patch.
"""
from __future__ import annotations


def install_strict_false_keyword_adapter(monkeypatch):
    from stage_center._raw_store_parts import receipt_identity
    original = receipt_identity._validate_rows_body

    def compatibility(scope, /, rows, *, trade_date, stage_id, market,
                      allow_temporal_false_observation=False):
        if allow_temporal_false_observation is not False:
            raise ValueError("TEST_SUPPORT_REFUSES_TEMPORAL_FALSE_OBSERVATION")
        return original(scope, rows, trade_date=trade_date, stage_id=stage_id, market=market)

    monkeypatch.setattr(receipt_identity, "_validate_rows_body", compatibility)
    return compatibility
