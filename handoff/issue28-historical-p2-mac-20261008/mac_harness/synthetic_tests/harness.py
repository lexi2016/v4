"""Synthetic helpers that use the canonical project's real dependencies."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import os
from pathlib import Path
import sys


CANONICAL_ROOT = Path(os.environ["V4_CANONICAL_ROOT"]).resolve()
CANDIDATE_ROOT = Path(os.environ["ISSUE28_CANDIDATE_ROOT"]).resolve()
BEFORE_CLOSE_SHA = "a361ae023285392ddf3b0e9674a9c506fae79252cc02c15df221ae09ba28e5aa"


def before_producer():
    path = CANDIDATE_ROOT / "before/ops/build_close_review.py"
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BEFORE_CLOSE_SHA:
        raise RuntimeError("frozen before close producer SHA mismatch")
    name = "ops._issue28_historical_p2_before_close_review"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the frozen before close producer")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    from infrastructure.preselection_pool_store import PreselectionPoolStore

    if module.PreselectionPoolStore is not PreselectionPoolStore:
        raise RuntimeError("before close producer did not use the selected real PoolStore")
    return module


def historical_fixture():
    path = CANONICAL_ROOT / "tests/test_close_review_producer.py"
    tree = ast.parse(path.read_bytes(), filename=str(path))
    name = "_historical_split_pool_payload"
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    if len(selected) != 1:
        raise RuntimeError("canonical historical fixture function is missing")
    module = ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[]))
    namespace = {}
    exec(compile(module, str(path), "exec"), namespace)
    return namespace[name]()

