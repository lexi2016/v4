"""AST-aware forbidden-behavior scanner for acceptance (DS1-fix4).

Replaces the acceptance runner's naive substring scan: executable forbidden
behavior is detected from the parsed tree (imports, attribute calls, keyword
arguments, string constants). Comments never appear in the AST and genuine
module/class/function docstrings are skipped, so neither can produce a hit.

Token contract used by the acceptance runner:
  - "subprocess" -> ``import subprocess`` / ``from subprocess import ...``
  - "os.system"  -> calls of the form ``os.system(...)``
  - "shell=True" -> any call with the keyword ``shell=True``
  - anything else -> the literal text occurring as an executable string (or,
    for numeric tokens, integer) constant; docstrings/comments excluded
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable

_ROOT = Path(__file__).resolve().parent.parent


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(_ROOT))
    except ValueError:
        return str(path)


def _is_docstring_stmt(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _walk_no_docstrings(tree: ast.AST) -> Iterable[ast.AST]:
    """Yield nodes but never a docstring expression nor anything inside one."""
    stack = [tree]
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = list(node.body)
            if body and _is_docstring_stmt(body[0]):
                stack.extend(child for child in ast.iter_child_nodes(node) if child is not body[0])
                continue
        stack.extend(ast.iter_child_nodes(node))


def _check_imports(tree: ast.AST, token: str, path: Path) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == token or alias.name.startswith(token + "."):
                    hits.append({"file": _relative(path), "token": token})
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "") == token or (node.module or "").startswith(token + "."):
                hits.append({"file": _relative(path), "token": token})
    return hits


def _check_os_system(tree: ast.AST, token: str, path: Path) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "system"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "os"
        ):
            hits.append({"file": _relative(path), "token": token})
    return hits


def _check_shell_kwarg(tree: ast.AST, token: str, path: Path) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                hits.append({"file": _relative(path), "token": token})
    return hits


def _check_literals(tree: ast.AST, token: str, path: Path) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    for node in _walk_no_docstrings(tree):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, str):
                if token in node.value:
                    hits.append({"file": _relative(path), "token": token})
            elif isinstance(node.value, int) and token.isdigit() and token in str(node.value):
                hits.append({"file": _relative(path), "token": token})
    return hits


def scan_tokens(dirs: Iterable[Path], tokens: Iterable[str]) -> list[dict[str, str]]:
    """Scan every ``*.py`` under ``dirs`` for executable forbidden behavior.

    Returns ``[{"file": <root-relative path>, "token": <matched token>}]``.
    """
    hits: list[dict[str, str]] = []
    for base in dirs:
        for path in sorted(Path(base).rglob("*.py")):
            try:
                text = path.read_text(encoding="utf-8")
                tree = ast.parse(text)
            except (OSError, UnicodeDecodeError, SyntaxError):
                continue
            for token in tokens:
                if token == "subprocess":
                    hits.extend(_check_imports(tree, token, path))
                elif token == "os.system":
                    hits.extend(_check_os_system(tree, token, path))
                elif token == "shell=True":
                    hits.extend(_check_shell_kwarg(tree, token, path))
                else:
                    hits.extend(_check_literals(tree, token, path))
    return hits
