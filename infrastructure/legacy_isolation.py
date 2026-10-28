from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess


TEXT_SUFFIXES = frozenset(
    {".py", ".ts", ".vue", ".js", ".html", ".css", ".json", ".toml", ".yaml", ".yml", ".ps1"}
)
PRODUCTION_DIRECTORIES = frozenset({"apps", "contracts", "domains", "infrastructure", "ops"})

_LEGACY_ROOT = ("c:" + "/users/huang/desktop/" + "学习/" + "v3_" + "system").casefold()
_LEGACY_MODULE = "v3_" + "system"
_LEGACY_PORT = "8" + "771"
_SYS_TOKEN = "sys"
_PATH_TOKEN = "path"
# Read-only migration/development tools that are explicitly authorized to load
# or reference the frozen legacy builder for graph collection. These never run
# on the V4 live trading path and never mutate the legacy root; they are
# excluded so the production-text scan can stay strict for everything else.
_EXEMPT_READONLY_TOOLS = frozenset(
    {"ops/migration/collect_v3_graph_readonly.py"}
)
_LEGACY_URL = re.compile(r"https?://[^\s\"']+:" + _LEGACY_PORT + r"(?:[/?#]|$)", re.IGNORECASE)
_SYS_PATH_INJECTION = re.compile(
    rf"\b{_SYS_TOKEN}\s*\.\s*{_PATH_TOKEN}\s*(?:\.\s*(?:append|extend|insert)\s*\(|(?:\+?=))"
)
_LEGACY_IMPORT = re.compile(rf"\b(?:from|import)\s+{re.escape(_LEGACY_MODULE)}(?:\b|\.)")
_RELATIVE_LEGACY_SOURCE = re.compile(
    r"(?<![A-Za-z0-9_./:-])(?:\.\./)?" + re.escape(_LEGACY_MODULE) + r"/[\S]*"
)


@dataclass(frozen=True)
class LegacyViolation:
    relative_path: Path
    kinds: tuple[str, ...]


def _normalize_path_text(content: str) -> str:
    return content.replace("\\\\", "\\").replace("\\", "/").casefold()


def _is_legacy_module_reference(value: str) -> bool:
    return value == _LEGACY_MODULE or value.startswith(_LEGACY_MODULE + ".")


def _has_python_legacy_dynamic_import(content: str) -> bool:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return False

    importlib_modules: set[str] = set()
    import_module_functions: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "importlib":
                    importlib_modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
            for alias in node.names:
                if alias.name == "import_module":
                    import_module_functions.add(alias.asname or alias.name)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        first_argument = node.args[0]
        if not isinstance(first_argument, ast.Constant) or not isinstance(first_argument.value, str):
            continue
        function = node.func
        is_import_call = (
            isinstance(function, ast.Name)
            and (function.id in import_module_functions or function.id == "__import__")
        ) or (
            isinstance(function, ast.Attribute)
            and function.attr == "import_module"
            and isinstance(function.value, ast.Name)
            and function.value.id in importlib_modules
        )
        if is_import_call and _is_legacy_module_reference(first_argument.value):
            return True
    return False


def _violation_kinds(content: str, suffix: str) -> tuple[str, ...]:
    kinds: list[str] = []
    normalized_content = _normalize_path_text(content)
    if _LEGACY_ROOT in normalized_content:
        kinds.append("absolute_legacy_root")
    if _RELATIVE_LEGACY_SOURCE.search(normalized_content):
        kinds.append("relative_legacy_source_reference")
    if _LEGACY_URL.search(content):
        kinds.append("legacy_8771_proxy")
    if _SYS_PATH_INJECTION.search(content):
        kinds.append("sys_path_injection")
    if _LEGACY_IMPORT.search(content) or (suffix == ".py" and _has_python_legacy_dynamic_import(content)):
        kinds.append("legacy_import_or_execution")
    return tuple(kinds)


def scan_text_tree(root: Path) -> tuple[LegacyViolation, ...]:
    root = root.resolve()
    paths = sorted(
        (path for path in root.rglob("*") if path.is_file() and path.suffix.casefold() in TEXT_SUFFIXES),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    return _scan_paths(root, paths)


def scan_tracked_production_text(root: Path | None = None) -> tuple[LegacyViolation, ...]:
    root = (root or Path(__file__).resolve().parents[1]).resolve()
    tracked_paths = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True
    ).stdout.decode("utf-8").split("\0")
    production_paths = [
        root / relative_path
        for relative_path in tracked_paths
        if relative_path
        and Path(relative_path).parts[0] in PRODUCTION_DIRECTORIES
        and Path(relative_path).suffix.casefold() in TEXT_SUFFIXES
    ]
    return _scan_paths(root, production_paths)


def _scan_paths(root: Path, paths: list[Path]) -> tuple[LegacyViolation, ...]:
    violations: list[LegacyViolation] = []
    for path in paths:
        relative = path.relative_to(root).as_posix()
        if relative in _EXEMPT_READONLY_TOOLS:
            continue
        kinds = _violation_kinds(path.read_text(encoding="utf-8-sig"), path.suffix.casefold())
        if kinds:
            violations.append(LegacyViolation(path.relative_to(root), kinds))
    return tuple(violations)
