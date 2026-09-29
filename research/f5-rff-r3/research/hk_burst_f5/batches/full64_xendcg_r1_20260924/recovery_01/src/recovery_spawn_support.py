"""Import the accepted process-tree helper under a spawn-importable name."""
from __future__ import annotations

import hashlib
import importlib
import sys
from pathlib import Path
from types import ModuleType


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def import_resource_tree(resource_tree_path: Path, expected_sha256: str) -> ModuleType:
    """Verify and import as ``resource_tree`` so spawn can unpickle its target.

    The prior dynamic loader registered the file as a synthetic module name
    absent from a fresh spawned interpreter.  This helper keeps the accepted
    file byte identity while using ordinary import semantics and rejects an
    already-loaded module from any other location.
    """
    path = Path(resource_tree_path).resolve()
    if not path.is_file() or sha256_file(path) != expected_sha256:
        raise RuntimeError("RESOURCE_TREE_HELPER_SHA_MISMATCH")

    parent = str(path.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    loaded = sys.modules.get("resource_tree")
    if loaded is not None:
        loaded_path = Path(getattr(loaded, "__file__", "")).resolve()
        if loaded_path != path:
            raise RuntimeError("RESOURCE_TREE_MODULE_NAME_COLLISION")
        module = loaded
    else:
        module = importlib.import_module("resource_tree")

    module_path = Path(getattr(module, "__file__", "")).resolve()
    if module.__name__ != "resource_tree" or module_path != path:
        raise RuntimeError("RESOURCE_TREE_NOT_IMPORTED_BY_CANONICAL_NAME")
    entry = getattr(module, "_worker_process_entry", None)
    if getattr(entry, "__module__", None) != "resource_tree":
        raise RuntimeError("RESOURCE_TREE_SPAWN_TARGET_NOT_IMPORTABLE")
    if not callable(getattr(module, "run_spawn_monitored", None)):
        raise RuntimeError("RESOURCE_TREE_MONITOR_ENTRY_MISSING")
    return module
