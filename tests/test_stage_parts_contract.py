"""Contract tests for the facade -> parts delegation.

The stage-center facades pass their own globals() into a ``*_parts``
implementation. That indirection hides both the target and its signature from
ordinary import checks: a renamed or missing parts module, or a facade passing
a keyword the body never accepted, only surfaces when that exact path runs.

These tests read the same calls statically and exercise the two entry points
that a scheduled tick would use.
"""
from __future__ import annotations

import ast
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FACADES = [
    "apps/api/v4_api/research_lane_router.py",
    "domains/preselection.py",
    "stage_center/raw_store.py",
    "stage_center/runner.py",
]


def _resolve(module: str) -> Path | None:
    relative = module.replace(".", "/")
    for candidate in (ROOT / f"{relative}.py", ROOT / relative / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _delegations() -> list[tuple[str, int, str, Path, str]]:
    """Yield (facade path, line, facade function, parts path, body name)."""
    found = []
    for relative in FACADES:
        path = ROOT / relative
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for func in [n for n in tree.body if isinstance(n, ast.FunctionDef)]:
            imports: dict[int, tuple[str, str]] = {}
            for node in ast.walk(func):
                if isinstance(node, ast.ImportFrom) and node.module:
                    for alias in node.names:
                        if alias.asname == "_v4_impl":
                            imports[node.lineno] = (node.module, alias.name)
            if not imports:
                continue
            for call in [n for n in ast.walk(func) if isinstance(n, ast.Call)
                         and isinstance(n.func, ast.Name) and n.func.id == "_v4_impl"]:
                prior = [line for line in imports if line < call.lineno]
                if not prior:
                    continue
                module, body_name = imports[max(prior)]
                target = _resolve(module)
                found.append((relative, call.lineno, func.name, target, body_name))
    return found


DELEGATIONS = _delegations()


def test_the_delegation_scan_sees_the_expected_surface():
    assert len(DELEGATIONS) >= 50


@pytest.mark.parametrize("facade,line,name,target,body", DELEGATIONS,
                         ids=[f"{d[2]}:{d[1]}" for d in DELEGATIONS])
def test_delegation_target_exists(facade, line, name, target, body):
    assert target is not None, f"{facade}:{line} {name} -> missing parts module"
    tree = ast.parse(target.read_text(encoding="utf-8"))
    assert any(isinstance(node, ast.FunctionDef) and node.name == body for node in tree.body), (
        f"{facade}:{line} {name} -> {target.name}.{body} not found"
    )


@pytest.mark.parametrize("facade,line,name,target,body", DELEGATIONS,
                         ids=[f"{d[2]}:{d[1]}" for d in DELEGATIONS])
def test_delegation_signature_matches(facade, line, name, target, body):
    tree = ast.parse((ROOT / facade).read_text(encoding="utf-8"))
    func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    call = next(n for n in ast.walk(func) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name) and n.func.id == "_v4_impl"
                and n.lineno == line)
    assert target is not None
    body_tree = ast.parse(target.read_text(encoding="utf-8"))
    body_def = next(n for n in body_tree.body if isinstance(n, ast.FunctionDef) and n.name == body)
    args = body_def.args
    params = args.posonlyargs + args.args
    named = {a.arg for a in params + args.kwonlyargs}
    unknown = {kw.arg for kw in call.keywords if kw.arg} - named
    assert not unknown, f"{facade}:{line} {name} passes unknown keyword(s) {sorted(unknown)}"
    assert args.vararg or len(call.args) <= len(params), (
        f"{facade}:{line} {name} passes too many positional arguments"
    )


def test_build_production_config_yields_a_runner_config(tmp_path: Path):
    from stage_center.runner import StageCenterRunner, build_production_config

    config = build_production_config(
        candidate_acquisition_root=tmp_path / "candidate",
        raw_root=tmp_path / "raw",
        selection_root=tmp_path / "selection",
        receipt_root=tmp_path / "receipt",
    )
    assert type(config).__name__ == "RunnerConfig"
    assert config.raw_root == tmp_path / "raw"
    assert type(StageCenterRunner(config)).__name__ == "StageCenterRunner"


def test_raw_store_validates_and_publishes(tmp_path: Path):
    from stage_center.raw_store import publish_raw_artifact, validate_rows

    validated = validate_rows([], trade_date="20261030", stage_id="STAGE_0930_0935", market="A_SHARE")
    assert isinstance(validated, tuple) and len(validated) == 2

    published = publish_raw_artifact(
        tmp_path / "raw",
        trade_date="20261030",
        stage_id="STAGE_0930_0935",
        market="A_SHARE",
        source_id="contract-test",
        source_status="READY",
        rows=[{"symbol": "000001", "price": 1.0}],
    )
    assert isinstance(published, dict)


PARTS_DIRS = [
    "apps/api/v4_api/_research_lane_router_parts",
    "domains/_preselection_parts",
    "ops/_us_market_digest_parts",
    "stage_center/_live_collectors_parts",
    "stage_center/_raw_store_parts",
    "stage_center/_runner_parts",
]


def _parts_files():
    for relative in PARTS_DIRS:
        for path in sorted((ROOT / relative).glob("*.py")):
            yield path


def test_parts_modules_import():
    import importlib

    for path in _parts_files():
        name = ".".join(path.relative_to(ROOT).with_suffix("").parts)
        importlib.import_module(name)


def test_parts_no_longer_read_through_the_facade_namespace():
    offenders = []
    for path in _parts_files():
        if path.name == "_namespace.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "_v4_global" in text or "read_global" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], offenders


FACADE_FOR_PARTS = {
    "apps/api/v4_api/_research_lane_router_parts": "apps/api/v4_api/research_lane_router.py",
    "domains/_preselection_parts": "domains/preselection.py",
    "ops/_us_market_digest_parts": "ops/us_market_digest.py",
    "stage_center/_live_collectors_parts": "stage_center/live_collectors.py",
    "stage_center/_raw_store_parts": "stage_center/raw_store.py",
    "stage_center/_runner_parts": "stage_center/runner.py",
}


def _facade_defined_names(relative: str) -> set[str]:
    """Names the facade defines itself, excluding anything it merely imports."""
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for sub in ast.walk(target):
                    if isinstance(sub, ast.Name):
                        names.add(sub.id)
    return names


def test_no_facade_hands_its_globals_to_an_implementation():
    offenders = []
    for relative in FACADES:
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "_v4_impl"
                    and any(isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name)
                            and arg.func.id == "globals" for arg in node.args)):
                offenders.append(f"{relative}:{node.lineno}")
    assert offenders == [], offenders


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(ROOT).with_suffix("").parts)


def _local_imports(path: Path) -> set[str]:
    """Internal modules imported at module level (imports inside functions do not count)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = _module_name(path).rsplit(".", 1)[0] if path.name != "__init__.py" else _module_name(path)
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            if node.level:
                parts = package.split(".")
                if node.level > 1:
                    parts = parts[: len(parts) - (node.level - 1)]
                base = ".".join(parts)
                target = f"{base}.{node.module}" if node.module else base
            else:
                target = node.module or ""
            if target.startswith(("apps", "domains", "infrastructure", "stage_center", "contracts", "ops")):
                found.add(target)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(("apps", "domains", "infrastructure", "stage_center", "contracts", "ops")):
                    found.add(alias.name)
    return found


def _resolve_module(name: str) -> Path | None:
    relative = name.replace(".", "/")
    for candidate in (ROOT / f"{relative}.py", ROOT / relative / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def test_facades_and_parts_form_no_module_level_cycle():
    seeds = [ROOT / relative for relative in FACADES]
    for relative in FACADE_FOR_PARTS:
        seeds.extend(sorted((ROOT / relative).glob("*.py")))
    graph: dict[str, set[str]] = {}
    for path in seeds:
        name = _module_name(path)
        graph[name] = _local_imports(path)

    def visit(name: str, stack: tuple[str, ...]) -> None:
        if name in stack:
            raise AssertionError("import cycle: " + " -> ".join(stack + (name,)))
        target = _resolve_module(name)
        if target is None or name not in graph:
            return
        for dependency in graph[name]:
            visit(dependency, stack + (name,))

    for name in list(graph):
        visit(name, ())
