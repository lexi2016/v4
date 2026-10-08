"""Read rejection and trio preservation using the exact before and after stores."""
from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path

import pytest

from frozen_fixtures import change_source_date, historical_payload
from infrastructure import preselection_pool_store as after_store


BEFORE_POOL_SHA = "028298a05ea44e310487c1159acc8147cf652e23ba716989135b178198795a92"


def _before_module():
    root = Path(os.environ["ISSUE28_CANDIDATE_ROOT"]).resolve()
    path = root / "before/infrastructure/preselection_pool_store.py"
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == BEFORE_POOL_SHA
    name = "infrastructure._issue28_historical_p2_before_pool_store"
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


@pytest.mark.parametrize(
    "schema,field,future_date",
    [
        ("asof", "eligibility_source_date", "20261001"),
        ("split", "price_signal_date", "20261008"),
    ],
)
def test_existing_future_artifact_read_rejects_without_changing_trio(
    tmp_path, schema, field, future_date
):
    expected_path = Path(os.environ["ISSUE28_EXPECTED_AFTER_POOL_PATH"]).resolve()
    expected_sha = os.environ["ISSUE28_EXPECTED_POOL_SHA"]
    actual_path = Path(after_store.__file__).resolve()
    assert actual_path == expected_path
    assert hashlib.sha256(actual_path.read_bytes()).hexdigest() == expected_sha

    payload = historical_payload(schema)
    change_source_date(payload, field, future_date)
    original_payload = copy.deepcopy(payload)
    date = payload["trade_date"]
    pool_id = payload["pool_id"]
    store_root = tmp_path / "synthetic_prior_store"

    before = _before_module().PreselectionPoolStore(store_root)
    before.materialize(payload)
    assert before.read_pool(date, pool_id) == original_payload
    artifact_relative, receipt_relative = before._relative(date, pool_id)
    relatives = [
        artifact_relative,
        receipt_relative,
        f"preselection_pools/{date}/manifest.json",
    ]
    old_bytes = {name: (store_root / name).read_bytes() for name in relatives}

    with pytest.raises(ValueError, match="historical pool source date exceeds target date"):
        after_store.PreselectionPoolStore(store_root).read_pool(date, pool_id)

    new_bytes = {name: (store_root / name).read_bytes() for name in relatives}
    assert new_bytes == old_bytes
    assert payload == original_payload

