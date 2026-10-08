"""Pinned real producer/domain/stores; unused Stage consumer import is isolated.

Every fixture passes stage_selection_root=None, so the exact producer returns
seven missing-stage entries without calling StageSelectionConsumer. Its actual
owner module is absent from this slice; a fail-fast import sentinel documents
that limit instead of importing an unrelated application. All review/snapshot/
preselection schema validation, disk publication and readback are real source.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parent


def checked_sources():
    entries = json.loads((ROOT / "SOURCE_IDENTITIES.json").read_text())["files"]
    for item in entries:
        data = (ROOT / item["path"]).read_bytes()
        assert len(data) == item["bytes"]
        assert hashlib.sha256(data).hexdigest() == item["sha256"], item["path"]
        assert hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest() == item["git_blob_sha1"]


def prepare(phase: str):
    checked_sources()
    sys.path[:0] = [str(ROOT / phase / "canonical"), str(ROOT / "before/canonical"),
                    str(ROOT / "support")]
    package = types.ModuleType("stage_center")
    package.__path__ = []
    consumer = types.ModuleType("stage_center.consumer")

    class StageSelectionConsumerUnavailable:
        def __init__(self, *args, **kwargs):
            raise AssertionError("actual Stage consumer is outside this bounded missing-stage fixture")

    consumer.StageSelectionConsumer = StageSelectionConsumerUnavailable
    sys.modules["stage_center"] = package
    sys.modules["stage_center.consumer"] = consumer


def historical_fixture():
    """Reuse the exact unchanged split-date fixture from the frozen test file."""
    path = ROOT / "before/canonical/tests/test_close_review_producer.py"
    tree = ast.parse(path.read_text(), filename=str(path))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "_historical_split_pool_payload")
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    scope = {}
    exec(compile(module, str(path), "exec"), scope)
    return scope[function.name]()


def before_producer():
    path = ROOT / "before/canonical/ops/build_close_review.py"
    spec = importlib.util.spec_from_file_location("ops._close_pit_baseline", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
