"""Independent probes of rejection/preservation for pre-existing future sources."""
from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

from infrastructure import preselection_pool_store as after_store


BEFORE_SHA = "028298a05ea44e310487c1159acc8147cf652e23ba716989135b178198795a92"
AFTER_SHA = "9f1606a977d36c063d9c650e54b9861947eb7b692e779837852e3831b7814bef"
FIXTURE_SHA = "c2501b342755bfa97064ceae1a8df0c936f912c9a635fc88c059d660d62b655f"


def _before_module(root: Path):
    path = root / "before/infrastructure/preselection_pool_store.py"
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == BEFORE_SHA
    name = "infrastructure._issue28_independent_before_pool_store"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    # Execute the exact checked original bytes, with its real store dependencies.
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def _payload(root: Path, schema: str) -> dict:
    path = root / "references/tests/test_close_review_producer.py"
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == FIXTURE_SHA
    names = {"_historical_split_pool_payload", "_historical_asof_pool_payload"}
    tree = ast.parse(raw, filename=str(path))
    selected = [node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in selected} == names
    namespace = {"copy": copy}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    return namespace[f"_historical_{schema}_pool_payload"]()


@pytest.mark.parametrize("schema,field,future_date", [
    ("asof", "eligibility_source_date", "20261001"),
    ("split", "price_signal_date", "20261008"),
])
def test_existing_future_artifact_read_rejects_without_changing_trio(
    tmp_path, schema, field, future_date,
):
    source_root = Path(os.environ["ISSUE28_REVIEW_HISTORICAL_ROOT"])
    output = Path(os.environ["ISSUE28_REVIEW_PROBE_OUTPUT"])
    after_path = source_root / "after/infrastructure/preselection_pool_store.py"
    assert Path(after_store.__file__).resolve() == after_path.resolve()
    assert hashlib.sha256(after_path.read_bytes()).hexdigest() == AFTER_SHA

    payload = _payload(source_root, schema)
    provenance = payload["historical_provenance"]
    provenance[field] = future_date
    if field == "eligibility_source_date":
        provenance["eligibility_asof"]["source_date"] = future_date
    else:
        payload["signal_date"] = future_date
    original_payload = copy.deepcopy(payload)
    date = payload["trade_date"]
    pool_id = payload["pool_id"]
    store_root = tmp_path / "synthetic_prior_store"

    before = _before_module(source_root).PreselectionPoolStore(store_root)
    before.materialize(payload)
    assert before.read_pool(date, pool_id) == original_payload
    artifact_relative, receipt_relative = before._relative(date, pool_id)
    relatives = [artifact_relative, receipt_relative,
                 f"preselection_pools/{date}/manifest.json"]
    old_bytes = {name: (store_root / name).read_bytes() for name in relatives}

    with pytest.raises(ValueError, match="historical pool source date exceeds target date") as error:
        after_store.PreselectionPoolStore(store_root).read_pool(date, pool_id)

    new_bytes = {name: (store_root / name).read_bytes() for name in relatives}
    assert new_bytes == old_bytes
    assert payload == original_payload
    record = {
        "schema": schema, "future_field": field, "future_date": future_date,
        "target_date": date,
        "before_store_materialize_and_read": "PASS",
        "after_store_read": "EXPECTED_VALUE_ERROR",
        "error": str(error.value),
        "artifact_receipt_manifest_bytes_unchanged": True,
        "before_pool_store_sha256": BEFORE_SHA,
        "after_pool_store_sha256": AFTER_SHA,
        "trio": [{"path": name, "before_sha256": hashlib.sha256(raw).hexdigest(),
                  "after_sha256": hashlib.sha256(new_bytes[name]).hexdigest(),
                  "bytes": len(raw)} for name, raw in old_bytes.items()],
        "data_classification": "SYNTHETIC_FIXTURE_ONLY",
    }
    (output / f"read_probe_{schema}_{field}.json").write_text(json.dumps(record, indent=2) + "\n")
