#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import sys
from pathlib import Path

_SCRIPT_PATH = Path(os.path.abspath(__file__))
_PROJECT_ROOT = next(
    (parent for parent in _SCRIPT_PATH.parents if (parent / "v4_migration").is_dir() and not (parent / "v4_migration").is_symlink()),
    None,
)
if _PROJECT_ROOT is None:
    raise RuntimeError("V4_PROJECT_ROOT_NOT_FOUND")
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from v4_migration.contracts import immutable_write_json
from v4_migration.safe_io import read_relative_file


def scan(path: Path, allowed_roots: list[Path]) -> dict:
    target = Path(os.path.abspath(os.fspath(path)))
    for root_value in allowed_roots:
        root = Path(os.path.abspath(os.fspath(root_value)))
        try:
            relative = os.path.relpath(target, root)
        except ValueError:
            continue
        if relative == os.pardir or relative.startswith(os.pardir + os.sep) or os.path.isabs(relative):
            continue
        relative = relative.replace(os.sep, "/")
        try:
            data = read_relative_file(root, relative)
        except (OSError, ValueError) as exc:
            return {"path": str(target), "status": "UNREADABLE_OR_UNSAFE", "error_type": type(exc).__name__}
        row = {"path": str(target), "status": "CANDIDATE_ONLY_NOT_OWNER_BOUND", "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "trusted_owner_binding": False}
        if target.suffix == ".py":
            try:
                tree = ast.parse(data.decode("utf-8"), filename=str(target))
                row["functions"] = sorted({node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))})
            except (SyntaxError, UnicodeDecodeError) as exc:
                row["ast_error"] = f"{type(exc).__name__}:{exc}"
        return row
    return {"path": str(target), "status": "SOURCE_ROOT_UNBOUND", "trusted_owner_binding": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only scoped source collector; never loads candidate modules")
    parser.add_argument("--path", action="append", default=[])
    parser.add_argument("--allowed-root", action="append", default=[], type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    result = {
        "schema": "v4_migration.missing_binding_collection.v2",
        "status": "READ_ONLY_CANDIDATE_COLLECTION",
        "items": [scan(Path(value), args.allowed_root) for value in args.path],
        "process_or_service_changed": False,
        "module_imported": False,
        "owner_binding_established": False,
    }
    immutable_write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
