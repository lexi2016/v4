"""Static import policy for trusted isolated package trees."""
from __future__ import annotations

import ast
from pathlib import Path


def _inside(root: Path, path: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{label} escapes trusted package root: {path}") from error
    return resolved


def _alias_names(package_directory: str) -> set[str]:
    return {package_directory, "scripts", "shared_data"}


def _source_module_name(root: Path, source_path: Path) -> str:
    parts = list(source_path.relative_to(root).parts)
    if parts[-1] == "__init__.py":
        parts.pop()
    else:
        parts[-1] = Path(parts[-1]).stem
    return ".".join(parts)


def _source_for_module(
    root: Path, module_name: str, protected: set[str]
) -> Path | None:
    parts = tuple(module_name.split("."))
    if not parts or parts[0] not in protected:
        return None
    module_base = _inside(root, root.joinpath(*parts), "trusted import target")
    module_file = _inside(
        root, module_base.with_suffix(".py"), "trusted import target"
    )
    if module_file.is_file():
        return module_file
    package_init = _inside(
        root, module_base / "__init__.py", "trusted import target"
    )
    if package_init.is_file():
        return package_init
    return None


def _relative_module_name(
    module_name: str, source_path: Path, level: int, imported: str | None
) -> str:
    if source_path.name == "__init__.py":
        package_name = module_name
    else:
        package_name = module_name.rpartition(".")[0]
    for _ in range(max(level - 1, 0)):
        package_name = package_name.rpartition(".")[0]
    if imported:
        return f"{package_name}.{imported}" if package_name else imported
    return package_name


def _import_targets(
    node: ast.Import | ast.ImportFrom,
    *,
    module_name: str,
    source_path: Path,
    protected: set[str],
) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(
            imported.name
            for imported in node.names
            if imported.name.partition(".")[0] in protected
        )
    if node.level == 0:
        if not node.module or node.module.partition(".")[0] not in protected:
            return ()
        targets = [node.module]
        if node.module.partition(".")[0] == node.module:
            targets.extend(
                f"{node.module}.{imported.name}"
                for imported in node.names
                if imported.name != "*"
            )
        return tuple(targets)
    base = _relative_module_name(module_name, source_path, node.level, node.module)
    if not base or base.partition(".")[0] not in protected:
        return ()
    targets = [base]
    if node.module is None:
        targets.extend(
            f"{base}.{imported.name}"
            for imported in node.names
            if imported.name != "*"
        )
    return tuple(targets)


class _ImportVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.scope_depth = 0
        self.imports: list[tuple[ast.Import | ast.ImportFrom, int]] = []
        self.dynamic = False

    def visit_Import(self, node: ast.Import) -> None:
        self.imports.append((node, self.scope_depth))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.imports.append((node, self.scope_depth))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        function = node.func
        if (
            isinstance(function, ast.Name)
            and function.id in {"__import__", "exec", "eval"}
        ) or (
            isinstance(function, ast.Attribute)
            and function.attr == "import_module"
        ):
            self.dynamic = True
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope_depth += 1
        self.generic_visit(node)
        self.scope_depth -= 1

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.scope_depth += 1
        self.generic_visit(node)
        self.scope_depth -= 1

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self.scope_depth += 1
        self.generic_visit(node)
        self.scope_depth -= 1


def _target_paths(
    root: Path,
    protected: set[str],
    source_path: Path,
    module_name: str,
    node: ast.Import | ast.ImportFrom,
) -> tuple[Path, ...]:
    return tuple(
        target
        for target_name in _import_targets(
            node,
            module_name=module_name,
            source_path=source_path,
            protected=protected,
        )
        if (target := _source_for_module(root, target_name, protected)) is not None
    )


def validate_isolated_import_policy(
    root: Path, package_directory: str, entry_path: Path
) -> None:
    """Reject imports that could escape after the temporary aliases are restored."""
    protected = _alias_names(package_directory)
    source_paths: set[Path] = set()
    for alias in protected:
        package_dir = _inside(root, root / alias, "trusted package")
        if not package_dir.is_dir():
            continue
        try:
            for source_path in package_dir.rglob("*.py"):
                source_path = _inside(root, source_path, "trusted package source")
                if source_path.is_file():
                    source_paths.add(source_path)
        except OSError as error:
            raise ValueError(
                f"trusted package source cannot be scanned: {package_dir}"
            ) from error

    analyses: dict[
        Path, tuple[str, list[tuple[ast.Import | ast.ImportFrom, int]], bool]
    ] = {}
    for source_path in sorted(source_paths):
        try:
            source = source_path.read_bytes()
            tree = ast.parse(source, filename=str(source_path))
        except (OSError, SyntaxError) as error:
            raise ValueError(
                f"trusted package source cannot be validated: {source_path}"
            ) from error
        visitor = _ImportVisitor()
        visitor.visit(tree)
        analyses[source_path] = (
            _source_module_name(root, source_path),
            visitor.imports,
            visitor.dynamic,
        )

    for source_path, (_module_name, imports, _dynamic) in analyses.items():
        for node, scope_depth in imports:
            if not scope_depth:
                continue
            if isinstance(node, ast.Import):
                protected_import = any(
                    imported.name.partition(".")[0] in protected
                    for imported in node.names
                )
            else:
                protected_import = (
                    isinstance(node, ast.ImportFrom)
                    and node.level == 0
                    and node.module is not None
                    and node.module.partition(".")[0] in protected
                )
            if protected_import:
                raise ValueError(
                    f"deferred protected absolute import rejected: {source_path}"
                )

    bootstrap: set[Path] = {entry_path}
    for alias in protected:
        alias_init = _source_for_module(root, alias, protected)
        if alias_init is not None and alias_init.name == "__init__.py":
            bootstrap.add(alias_init)
    parent = entry_path.parent
    while parent != root and root in parent.parents:
        parent_init = parent / "__init__.py"
        if parent_init in source_paths:
            bootstrap.add(parent_init)
        parent = parent.parent

    queue = list(bootstrap)
    while queue:
        source_path = queue.pop()
        analysis = analyses.get(source_path)
        if analysis is None:
            continue
        module_name, imports, dynamic = analysis
        if dynamic:
            raise ValueError(f"dynamic import rejected: {source_path}")
        for node, scope_depth in imports:
            if scope_depth:
                continue
            for target_path in _target_paths(
                root, protected, source_path, module_name, node
            ):
                if target_path not in bootstrap:
                    bootstrap.add(target_path)
                    queue.append(target_path)

    lazy = {
        target_path
        for source_path, (module_name, imports, _dynamic) in analyses.items()
        for node, scope_depth in imports
        if source_path in bootstrap
        and scope_depth
        and isinstance(node, ast.ImportFrom)
        and node.level > 0
        for target_path in _target_paths(
            root, protected, source_path, module_name, node
        )
    }
    queue = list(lazy)
    seen_lazy: set[Path] = set()
    while queue:
        source_path = queue.pop()
        if source_path in seen_lazy or source_path in bootstrap:
            continue
        seen_lazy.add(source_path)
        analysis = analyses.get(source_path)
        if analysis is None:
            continue
        module_name, imports, dynamic = analysis
        if dynamic:
            raise ValueError(f"dynamic import rejected: {source_path}")
        for node, scope_depth in imports:
            if scope_depth == 0:
                if isinstance(node, ast.Import):
                    protected_import = any(
                        imported.name.partition(".")[0] in protected
                        for imported in node.names
                    )
                else:
                    protected_import = (
                        isinstance(node, ast.ImportFrom)
                        and node.level == 0
                        and node.module is not None
                        and node.module.partition(".")[0] in protected
                    )
                if protected_import:
                    raise ValueError(
                        "lazy helper top-level protected absolute import "
                        f"rejected: {source_path}"
                    )
            if isinstance(node, ast.ImportFrom) and node.level > 0:
                queue.extend(
                    _target_paths(root, protected, source_path, module_name, node)
                )
