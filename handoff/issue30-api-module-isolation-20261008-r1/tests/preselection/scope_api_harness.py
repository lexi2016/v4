"""Execute the preselection boundary with real imports and synthetic data.

The baseline uses only the exact route/helper AST from the SHA-pinned R2
app.py.  The candidate executes the exact new app registration statement and
imports the complete new router/service modules.  It does not import, replace,
or claim to start the entire R2 create_app dependency graph.  No sys.modules
substitution or omitted import is used by the historical dependency closure.
"""
from __future__ import annotations

import ast
from datetime import datetime
import inspect
import os
from pathlib import Path
from typing import Any, Mapping

from fastapi import FastAPI, HTTPException, Query

from contracts.trading_safety import TRADING_SAFETY_FLAGS
from domains import preselection as preselection_domain
from domains.preselection import OPTIONAL_DAILY_POOL_IDS, preselection
from infrastructure.data_store import NativeDataStore
from infrastructure.preselection_pool_store import PreselectionPoolStore


ROOT = Path(__file__).resolve().parents[1]
BEFORE = ROOT / "source/r2_app_byte_match/apps/api/v35_api/app.py"
TWO_HUNK = ROOT / "source/two_hunk_reference/apps/api/v35_api/app.py"
AFTER = ROOT / "after/apps/api/v35_api/app.py"


def create_app(*, data_root: Path, preselection_source_root: Path | None = None,
               current_date: str = "20261008") -> FastAPI:
    mode = os.environ.get("ISSUE30_ROUTE_MODE", "candidate")
    path = {"baseline": BEFORE, "two_hunk_reference": TWO_HUNK, "candidate": AFTER}[mode]
    assert path.is_file(), f"module candidate has not been implemented: {path}"
    tree = ast.parse(path.read_text(), filename=str(path))
    app = FastAPI()
    scope = {
        "datetime": datetime, "inspect": inspect, "Any": Any,
        "Mapping": Mapping, "Path": Path, "HTTPException": HTTPException,
        "Query": Query, "TRADING_SAFETY_FLAGS": TRADING_SAFETY_FLAGS,
        "PreselectionPoolStore": PreselectionPoolStore,
        "preselection_domain": preselection_domain,
        "preselection": preselection,
        "OPTIONAL_DAILY_POOL_IDS": OPTIONAL_DAILY_POOL_IDS,
        "app": app, "store": NativeDataStore(data_root),
        "configured_pool_source": preselection_source_root is not None,
        "resolved_pool_source": Path(preselection_source_root or data_root),
        "_catalog": lambda: {"default_date": current_date, "system_date": current_date},
    }
    names = {"_strict_date"}
    if mode != "candidate":
        names |= {"_is_sha256", "_is_exact_configured_hk_pool", "_preselection_response_from_pools"}
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                and node.name in names]
    create = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                  and node.name == "create_app")
    if mode != "candidate":
        selected.append(next(node for node in create.body if isinstance(node, ast.FunctionDef)
                             and node.name == "preselection_pools"))
    else:
        selected[:0] = [node for node in tree.body if isinstance(node, ast.ImportFrom)
                        and node.module in {"apps.api.v35_api.preselection_router",
                                            "apps.api.v35_api.preselection_service"}]
        registration = [node for node in create.body if isinstance(node, ast.Expr)
                        and isinstance(node.value, ast.Call)
                        and any(isinstance(child, ast.Name)
                                and child.id == "create_preselection_router"
                                for child in ast.walk(node))]
        assert len(registration) == 1, "shared app must register exactly one preselection router"
        selected.extend(registration)
    code = ast.fix_missing_locations(ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        *selected,
    ], type_ignores=[]))
    exec(compile(code, str(path), "exec"), scope)
    return app
