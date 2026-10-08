"""Load an isolated exact owner and record all imported V4 file identities."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
BUNDLE = ROOT.parent
OWNER = os.environ["ISSUE28_TEST_OWNER"]
if OWNER not in {"actual_stage_owner", "canonical"}:
    raise RuntimeError("invalid isolated owner")
OWNER_ROOT = Path(os.environ["ISSUE28_TEST_APP"]).resolve()
SUPPORT = ROOT / "support"
sys.dont_write_bytecode = True
sys.path.insert(0, str(SUPPORT))
sys.path.insert(0, str(OWNER_ROOT))


def pytest_sessionfinish(session, exitstatus):
    loaded = []
    expected = json.loads(Path(os.environ["ISSUE28_TEST_IMPORT_EXPECTATIONS"]).read_text())
    for name, module in sorted(sys.modules.items()):
        filename = getattr(module, "__file__", None)
        if not filename or not (name in {"stage_center", "infrastructure"}
                                or name.startswith(("stage_center.", "infrastructure."))):
            continue
        path = Path(filename).resolve()
        if path.is_relative_to(OWNER_ROOT):
            relative = "app/" + str(path.relative_to(OWNER_ROOT))
            role = "EXACT_OWNER_SOURCE_SLICE"
        elif path.is_relative_to(SUPPORT):
            relative = "support/" + str(path.relative_to(SUPPORT))
            role = "PINNED_SUPPLEMENT_NOT_CURRENT_RUNTIME_IDENTITY"
        else:
            raise RuntimeError(f"V4 module escaped the isolated source roots: {name}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if expected.get(relative) != digest:
            raise RuntimeError(f"loaded source SHA mismatch: {relative}")
        loaded.append({"module": name, "path": relative, "absolute_path": str(path),
                       "sha256": digest, "role": role})
    if not exitstatus:
        required = {"stage_center.runner", "stage_center.calendar",
                    "stage_center._runner_parts.hk_input_validation",
                    "infrastructure.preselection_pool_store",
                    "infrastructure.preselection_pool_readers",
                    "infrastructure.preselection_pool_sources"}
        if not required.issubset({item["module"] for item in loaded}):
            raise RuntimeError("required exact owner modules were not loaded")
    Path(os.environ["ISSUE28_TEST_IMPORT_LOG"]).write_text(json.dumps({
        "owner": OWNER, "phase": os.environ["ISSUE28_TEST_PHASE"],
        "pytest_exitstatus": int(exitstatus), "loaded": loaded,
        "scope": "SOURCE_SLICES_WITH_PINNED_SUPPLEMENTS_NOT_FULL_MAC_RUNTIME",
    }, indent=2) + "\n")
