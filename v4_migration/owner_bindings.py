from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path
from typing import Any, Iterable

from .safe_io import read_relative_file

REQUIRED_ACTIONS = ("fence", "drain", "final_delta", "switch", "readback", "rollback")


def _relative_to_allowed(path: str | Path, roots: Iterable[str | Path]) -> tuple[Path, str] | None:
    target = Path(os.path.abspath(os.fspath(path)))
    for root_value in roots:
        root = Path(os.path.abspath(os.fspath(root_value)))
        try:
            relative = os.path.relpath(target, root)
        except ValueError:
            continue
        if relative != os.pardir and not relative.startswith(os.pardir + os.sep) and not os.path.isabs(relative):
            return root, relative.replace(os.sep, "/")
    return None


def collect_candidate(
    specs: dict[str, dict[str, Any]],
    *,
    allowed_roots: Iterable[str | Path] = (),
) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    roots = tuple(allowed_roots)
    for action, spec in specs.items():
        if action not in REQUIRED_ACTIONS or not isinstance(spec, dict):
            rows[str(action)] = {"status": "SPEC_INVALID"}
            continue
        path_value = spec.get("path")
        callable_name = spec.get("callable")
        if not isinstance(path_value, (str, Path)) or not isinstance(callable_name, str):
            rows[action] = {"status": "SPEC_INVALID"}
            continue
        allowed = _relative_to_allowed(path_value, roots)
        if allowed is None:
            rows[action] = {"path": str(path_value), "callable": callable_name, "status": "OWNER_SOURCE_ROOT_UNBOUND"}
            continue
        root, relative = allowed
        try:
            data = read_relative_file(root, relative)
            tree = ast.parse(data.decode("utf-8"), filename=str(path_value))
        except (OSError, ValueError, SyntaxError, UnicodeDecodeError) as exc:
            rows[action] = {"path": str(path_value), "callable": callable_name, "status": "OWNER_SOURCE_UNREADABLE", "error_type": type(exc).__name__}
            continue
        names = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        rows[action] = {
            "path": str(path_value),
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "callable": callable_name,
            "callable_present": callable_name in names,
            "status": "CANDIDATE_REQUIRES_TRUSTED_OWNER_REVIEW",
            "execution_performed": False,
        }
    return {
        "schema": "v4_migration.owner_binding_candidate.v2",
        "status": "CANDIDATE_ONLY_TRUST_ROOT_UNBOUND",
        "actions": rows,
        "execution_performed": False,
    }


def validate_binding_review(review: dict[str, Any]) -> None:
    raise ValueError("OWNER_TRUST_ROOT_UNCONFIGURED")


class BoundModuleAdapter:
    def __init__(self, action: str, binding: dict[str, Any]):
        self.action = action
        self.binding = binding

    def invoke(self, payload: dict[str, Any], authorized: bool = False) -> dict[str, Any]:
        raise PermissionError("OWNER_TRUST_ROOT_UNCONFIGURED")
