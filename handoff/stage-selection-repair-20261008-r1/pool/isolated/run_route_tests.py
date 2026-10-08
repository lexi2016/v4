"""Bounded frozen-source route/storage test harness, NOT a full app startup.

The source slice omits package namespace helpers and unrelated application
dependencies. This harness executes the exact preselection route and helper AST,
the unchanged preselection facade/parts, and real immutable pool storage. Only
the omitted global-name lookup helper and date-catalog startup are test seams.
It must not be represented as a complete candidate, Mac, or live API canary.
"""
from __future__ import annotations

import ast
import builtins
from datetime import datetime
import inspect
from pathlib import Path
import sys
import types
from typing import Any, Mapping

from fastapi import FastAPI, HTTPException, Query

ROOT = Path(__file__).resolve().parents[1]
DEPS = ROOT / "isolated/support"
REUSED = ROOT / "isolated/reference"
sys.path.insert(0, str(DEPS))
sys.path.insert(0, str(REUSED / "tests"))


def _package(name: str, path: Path) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module
    return module


def prepare() -> None:
    _package("domains", DEPS / "domains")
    _package("domains._preselection_parts", DEPS / "domains/_preselection_parts")
    namespace = types.ModuleType("domains._preselection_parts._namespace")

    def read_global(scope: dict, name: str) -> Any:
        return scope[name] if name in scope else getattr(builtins, name)

    namespace.read_global = read_global
    sys.modules[namespace.__name__] = namespace
    path = REUSED / "domains/preselection.py"
    tree = ast.parse(path.read_text(), filename=str(path))
    # SelectionStore belongs to date-catalog discovery, outside this route test.
    tree.body = [node for node in tree.body if not (
        isinstance(node, ast.ImportFrom) and node.module == "stage_center.selection"
    )]
    domain = types.ModuleType("domains.preselection")
    domain.__file__ = str(path)
    sys.modules[domain.__name__] = domain
    exec(compile(tree, str(path), "exec"), domain.__dict__)

    from contracts.trading_safety import TRADING_SAFETY_FLAGS
    from infrastructure.data_store import NativeDataStore
    from infrastructure.preselection_pool_store import PreselectionPoolStore

    app_path = REUSED / "apps/api/v35_api/app.py"
    app_tree = ast.parse(app_path.read_text(), filename=str(app_path))
    selected = [node for node in app_tree.body if isinstance(node, ast.FunctionDef)
                and node.name in {"_strict_date", "_is_sha256", "_is_exact_configured_hk_pool", "_preselection_response_from_pools"}]
    create = next(node for node in app_tree.body if isinstance(node, ast.FunctionDef) and node.name == "create_app")
    route = next(node for node in create.body if isinstance(node, ast.FunctionDef) and node.name == "preselection_pools")
    module = types.ModuleType("apps.api.v35_api.app")

    def create_app(*, data_root: Path, preselection_source_root: Path, current_date: str) -> FastAPI:
        app = FastAPI()
        scope = {
            "__builtins__": builtins, "datetime": datetime, "Any": Any,
            "Mapping": Mapping, "Path": Path, "inspect": inspect,
            "HTTPException": HTTPException, "Query": Query,
            "TRADING_SAFETY_FLAGS": TRADING_SAFETY_FLAGS,
            "PreselectionPoolStore": PreselectionPoolStore,
            "preselection_domain": domain, "preselection": domain.preselection,
            "OPTIONAL_DAILY_POOL_IDS": domain.OPTIONAL_DAILY_POOL_IDS,
            "app": app, "store": NativeDataStore(data_root),
            "configured_pool_source": True,
            "resolved_pool_source": Path(preselection_source_root),
            "_catalog": lambda: {"default_date": current_date, "system_date": current_date},
        }
        body = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *selected, route]
        executable = ast.fix_missing_locations(ast.Module(body=body, type_ignores=[]))
        exec(compile(executable, str(app_path), "exec"), scope)
        return app

    module.create_app = create_app
    _package("apps", REUSED / "apps")
    _package("apps.api", REUSED / "apps/api")
    _package("apps.api.v35_api", REUSED / "apps/api/v35_api")
    sys.modules[module.__name__] = module


if __name__ == "__main__":
    prepare()
    import pytest
    print("SCOPE=EXACT_ROUTE_AST_PLUS_REAL_POOL_STORAGE; FULL_CREATE_APP=NOT_RUN; MAC=NOT_RUN", flush=True)
    raise SystemExit(pytest.main(["-q", "-p", "no:cacheprovider", "-W", "error",
        "-W", "default::starlette.exceptions.StarletteDeprecationWarning",
        str(ROOT / "tests/test_issue28_preselection_hk_fallback.py")]))
