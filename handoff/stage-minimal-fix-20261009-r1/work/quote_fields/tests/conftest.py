"""Isolated selector slice imports; this is not a current-owner app import."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parents[1]
PHASE = os.environ.get("STAGE_QUOTE_PHASE", "after")
assert PHASE in {"before", "after"}
for entry in json.loads((ROOT / "SUPPORT_MANIFEST.json").read_text())["files"]:
    data = (ROOT / entry["path"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == entry["sha256"], entry["path"]
    assert len(data) == entry["bytes"], entry["path"]

# The actual Stage package initializer and namespace module were not supplied.
# These package shells prevent importing another application from the ambient
# path. The namespace helper is separately pinned and identified as a seam.
for name, paths in (
    ("stage_center", [ROOT / "support/stage_center"]),
    ("stage_center._selection_parts", [
        ROOT / PHASE / "stage_center/_selection_parts",
        ROOT / "support/stage_center/_selection_parts",
    ]),
    ("infrastructure", [ROOT / "support/infrastructure"]),
):
    package = types.ModuleType(name)
    package.__path__ = [str(path) for path in paths]
    sys.modules[name] = package


def load_before(name):
    qualified = "stage_center._selection_parts.frozen_before_" + name
    spec = importlib.util.spec_from_file_location(
        qualified, ROOT / "before/stage_center/_selection_parts" / (name + ".py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    spec.loader.exec_module(module)
    return module


BEFORE_AUCTION = load_before("a_auction")
BEFORE_LIVE = load_before("a_live")
