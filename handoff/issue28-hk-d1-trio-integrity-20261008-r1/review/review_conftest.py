"""Independent isolated loader; asserts actual owner and helper module identities."""
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "support"))
sys.path.insert(0, str(ROOT / "owner"))


def pytest_sessionfinish(session, exitstatus):
    expected = json.loads((ROOT / "expected_modules.json").read_text())
    loaded = []
    for name, module in sorted(sys.modules.items()):
        filename = getattr(module, "__file__", None)
        if not filename:
            continue
        path = Path(filename).resolve()
        if path.is_relative_to(ROOT):
            loaded.append({"module": name, "path": str(path.relative_to(ROOT)),
                           "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    for name, identity in expected.items():
        module = sys.modules.get(name)
        assert module is not None, f"missing exercised module: {name}"
        path = Path(module.__file__).resolve()
        assert path == ROOT / identity["path"], f"wrong owner loaded: {name}"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == identity["sha256"], name
    Path(os.environ["REVIEW_IMPORT_LOG"]).write_text(json.dumps({
        "exitstatus": int(exitstatus), "expected_modules": expected,
        "asserted_exact_loaded_modules": True, "loaded": loaded,
    }, indent=2) + "\n")
