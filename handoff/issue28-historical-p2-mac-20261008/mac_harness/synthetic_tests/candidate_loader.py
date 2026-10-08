"""Load only the two isolated Issue 28 candidates with canonical dependencies."""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import os
from pathlib import Path
import sys


CANONICAL_ROOT = Path(os.environ["V4_CANONICAL_ROOT"]).resolve()
CANDIDATE_ROOT = Path(os.environ["ISSUE28_CANDIDATE_SOURCE_ROOT"]).resolve()
EXPECTED_POOL_SHA = os.environ["ISSUE28_EXPECTED_POOL_SHA"]
EXPECTED_CLOSE_SHA = os.environ["ISSUE28_EXPECTED_CLOSE_SHA"]
sys.dont_write_bytecode = True
sys.path.insert(0, str(CANONICAL_ROOT))


def _load(module_name: str, path: Path, expected_sha: str):
    raw = path.read_bytes()
    actual_sha = hashlib.sha256(raw).hexdigest()
    if actual_sha != expected_sha:
        raise RuntimeError(f"candidate SHA mismatch for {path}: {actual_sha}")
    parent_name, _, child_name = module_name.rpartition(".")
    parent = importlib.import_module(parent_name)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load candidate module {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    setattr(parent, child_name, module)
    spec.loader.exec_module(module)
    if Path(module.__file__).resolve() != path.resolve():
        raise RuntimeError(f"candidate module path mismatch for {module_name}")
    return module


# These are the live canonical package objects; no handoff support modules are
# inserted into sys.path. The Stage consumer is available and imported from the
# project itself. The test producer receives stage_selection_root=None, so its
# normal missing-stage result does not construct that consumer.
import infrastructure  # noqa: E402
import stage_center.consumer as stage_consumer  # noqa: E402

if not Path(stage_consumer.__file__).resolve().is_relative_to(CANONICAL_ROOT / "stage_center"):
    raise RuntimeError("Stage consumer did not come from the canonical project")

pool_module = _load(
    "infrastructure.preselection_pool_store",
    CANDIDATE_ROOT / "infrastructure/preselection_pool_store.py",
    EXPECTED_POOL_SHA,
)
close_module = _load(
    "ops.build_close_review",
    CANDIDATE_ROOT / "ops/build_close_review.py",
    EXPECTED_CLOSE_SHA,
)
if close_module.PreselectionPoolStore is not pool_module.PreselectionPoolStore:
    raise RuntimeError("candidate close producer did not use the candidate pool store")

