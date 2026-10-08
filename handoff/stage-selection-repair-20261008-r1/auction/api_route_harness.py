"""Execute the exact frozen workbench route through in-process FastAPI HTTP.

This is deliberately not create_app/startup/middleware/full-owner integration.
The full, unmodified ordinary route and its projection helpers are extracted
from the pinned A-pool app.py. Actual imported SelectionStore/consumer source
reads the temporary fixture store. Unrelated routers and external providers
are absent. Tests use the explicit 20261008 date, whose exact frozen binding
tables contain no historical R8/R9 override.
"""
from __future__ import annotations

import ast
from datetime import datetime
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from fastapi import FastAPI, HTTPException, Query

from assemble_support import BUNDLE, checked_read
from contracts.stages import FROZEN_STAGE_IDS, STAGE_DEFINITIONS
from stage_center.consumer import StageSelectionConsumer


@lru_cache(maxsize=1)
def _source_module() -> tuple[ast.Module, Path]:
    supplement = json.loads((BUNDLE / "SUPPLEMENT_MANIFEST.json").read_text())
    entry = next(item for item in supplement["files"] if item["path"] == "deps/api_reference/app.py")
    path = BUNDLE / entry["path"]
    tree = ast.parse(checked_read(path, entry), filename=str(path))
    factory = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "create_app")
    top_functions = {"_hk_r8_required_evidence", "_hk_r9_required_evidence", "_strict_date"}
    # Execute the exact source binding tables and their existing constructors.
    # All calls in these selected module-level statements build constants;
    # no filesystem I/O or external service occurs here.
    constants = [node for node in tree.body[:tree.body.index(factory)] if
                 isinstance(node, (ast.Assign, ast.AnnAssign, ast.For)) or
                 isinstance(node, ast.FunctionDef) and node.name in top_functions]
    names = {"_stage_projection_status", "_hk_display_mode", "project_shared_selection",
             "_quarantine_known_hk_auction_pool_mismatch", "_read_r8_exact_target_hk_override",
             "_read_r9_exact_target_hk_override", "stage_workbench"}
    route_functions = [node for node in factory.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in route_functions} == names
    module = ast.fix_missing_locations(ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        *constants, *route_functions,
    ], type_ignores=[]))
    return module, path


def create_isolated_workbench(selection_root: Path) -> FastAPI:
    app = FastAPI()
    scope = {
        "Any": Any, "Mapping": Mapping, "Path": Path, "datetime": datetime,
        "hashlib": hashlib, "HTTPException": HTTPException, "Query": Query,
        "FROZEN_STAGE_IDS": FROZEN_STAGE_IDS, "STAGE_DEFINITIONS": STAGE_DEFINITIONS,
        "app": app, "configured_selection_root": selection_root,
        "shared_selection_consumer": StageSelectionConsumer(selection_root),
    }
    module, path = _source_module()
    exec(compile(module, str(path), "exec"), scope)
    assert ("20261008", "STAGE_0925") not in scope["_HK_R8_BINDING_BY_DATE_STAGE"]
    assert ("20261008", "STAGE_0925") not in scope["_HK_R9_BINDING_BY_DATE_STAGE"]
    app.state.validation_scope = "EXACT_ROUTE_AST_REAL_CONSUMER_TEMP_STORE; FULL_CREATE_APP_NOT_RUN"
    return app
