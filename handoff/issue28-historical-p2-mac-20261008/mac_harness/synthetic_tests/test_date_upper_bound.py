"""Issue #28 P2: source dates may equal, but must not exceed, the target day."""
from __future__ import annotations

import pytest

from frozen_fixtures import change_source_date, historical_payload
from infrastructure.preselection_pool_store import PreselectionPoolStore


@pytest.mark.parametrize(
    "schema,field,future_date",
    [
        ("split", "eligibility_source_date", "20261008"),
        ("split", "price_signal_date", "20261008"),
        ("asof", "eligibility_source_date", "20261001"),
        ("asof", "price_signal_date", "20261001"),
    ],
)
def test_future_source_date_is_rejected_before_materialization(tmp_path, schema, field, future_date):
    payload = historical_payload(schema)
    change_source_date(payload, field, future_date)
    root = tmp_path / "data"

    with pytest.raises(ValueError):
        PreselectionPoolStore(root).materialize(payload)

    assert not list(root.rglob("*.json"))


def test_optional_target_field_does_not_disable_trade_date_upper_bound(tmp_path):
    payload = historical_payload("asof")
    del payload["target_date"]
    change_source_date(payload, "price_signal_date", "20261001")
    root = tmp_path / "data"

    with pytest.raises(ValueError):
        PreselectionPoolStore(root).materialize(payload)

    assert not list(root.rglob("*.json"))
