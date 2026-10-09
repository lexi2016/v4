"""Offline imports of pinned native sources; no live provider or Mac claim.

Package shells avoid the unrelated API package initializer. Missing namespace
helpers use the original, SHA-pinned helper from the R1 deliverable; selectors,
collectors, normalizers, acquisition dataclasses and SelectionStore are native.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parents[1]
VARIANT = os.environ.get("V4_COLLECTORS_VARIANT", "actual_stage")
assert VARIANT in {"actual_stage", "canonical"}
COMPONENT_SOURCE_ROOT = ROOT / "canonical" if VARIANT == "canonical" else ROOT
RUNTIME = Path(os.environ.get("V4_TEST_RUNTIME_ROOT", str(PROJECT / "runtime_before" / VARIANT))).resolve()
PHASE = os.environ.get("V4_COLLECTORS_PHASE", "after")
assert PHASE in {"before", "after"}
HK_COMPONENT = PROJECT / "components/hk/after"
HELPER = ROOT / "support/_namespace.py"
HELPER_SHA = "45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1"
helper_bytes = HELPER.read_bytes()
assert hashlib.sha256(helper_bytes).hexdigest() == HELPER_SHA
sys.path[:0] = [str(RUNTIME), str(RUNTIME / "upstreams/v3_shared_data")]

package_paths = {
    "stage_center": [COMPONENT_SOURCE_ROOT / PHASE / "stage_center", *([] if os.environ.get("V4_TEST_RUNTIME_ROOT") else [HK_COMPONENT / "stage_center"]), RUNTIME / "stage_center"],
    "infrastructure": [RUNTIME / "infrastructure"],
}
for part in ("_selection_parts", "_live_collectors_parts", "_runner_parts", "_raw_store_parts"):
    package_paths[f"stage_center.{part}"] = [COMPONENT_SOURCE_ROOT / PHASE / "stage_center" / part, RUNTIME / "stage_center" / part]
for name, paths in package_paths.items():
    module = types.ModuleType(name)
    module.__path__ = [str(path) for path in paths]
    sys.modules[name] = module
    if name.startswith("stage_center."):
        qualified = name + "._namespace"
        spec = importlib.util.spec_from_file_location(qualified, HELPER)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        sys.modules[qualified] = helper
