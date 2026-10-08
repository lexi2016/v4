"""Execute unchanged frozen fixture/test definitions without importing Stage.

The complete source file is hash-checked before AST selection. No PoolStore,
validator, I/O dependency, or fixture implementation is replaced with a mock.
"""
from __future__ import annotations

import ast
import copy
import hashlib
from pathlib import Path

import pytest

from infrastructure.preselection_pool_store import PreselectionPoolStore, validate_pool_artifact


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "references/tests/test_close_review_producer.py"
SOURCE_SHA256 = "c2501b342755bfa97064ceae1a8df0c936f912c9a635fc88c059d660d62b655f"
NAMES = {
    "_historical_split_pool_payload",
    "_historical_asof_pool_payload",
    "test_historical_pool_provenance_is_allowlisted_typed_and_bound",
}
raw = SOURCE.read_bytes()
if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
    raise RuntimeError("frozen historical fixture source SHA mismatch")
tree = ast.parse(raw, filename=str(SOURCE))
selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in NAMES]
if {node.name for node in selected} != NAMES:
    raise RuntimeError("missing unchanged historical fixture/test definitions")
namespace = {
    "copy": copy,
    "pytest": pytest,
    "PreselectionPoolStore": PreselectionPoolStore,
    "validate_pool_artifact": validate_pool_artifact,
}
exec(compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), "exec"), namespace)
split_payload = namespace["_historical_split_pool_payload"]
asof_payload = namespace["_historical_asof_pool_payload"]
original_contract_test = namespace["test_historical_pool_provenance_is_allowlisted_typed_and_bound"]


def historical_payload(schema: str) -> dict:
    return {"split": split_payload, "asof": asof_payload}[schema]()


def change_source_date(payload: dict, field: str, value: str) -> None:
    """Keep existing equality bindings intact so probes isolate the upper bound."""
    provenance = payload["historical_provenance"]
    provenance[field] = value
    if field == "price_signal_date":
        payload["signal_date"] = value
        if "price_recovery" in provenance:
            provenance["price_recovery"]["source_date"] = value
    elif "eligibility_asof" in provenance:
        provenance["eligibility_asof"]["source_date"] = value


def materialize_and_read(payload: dict, root: Path) -> dict:
    store = PreselectionPoolStore(root)
    store.materialize(payload)
    return store.read_pool(payload["trade_date"], "hkconnect_d1_top100")
