#!/usr/bin/env python3
"""Apply the reviewed tech-debt phases 1-2 deltas to a release app copy.

The live release carries deltas that are not in the git branch, so a canary or
candidate cannot be assembled by checking out the branch. This tool takes a
copy of the release app and applies exactly the reviewed changes, failing loudly
when an expected anchor is missing.

It never touches a live release, plist or service.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Sequence

CONSTANTS = {
    "_HK_R8_OBSERVATION_MODE_SHA256_BY_DATE_STAGE": '_evidence_tuple_keyed("hk_r8_observation_mode")',
    "_MONTH_HK_AFTERFACT_R9_STAGE_ROWS": '_evidence_row_dicts("hk_afterfact_r9_stage_rows")',
    "_MONTH_HK_AFTERFACT_R5_BINDINGS": '_evidence_row_dicts("hk_afterfact_r5_bindings")',
    "_MONTH_HK_AFTERFACT_R8_BINDING_ROWS": '_evidence_tuple_rows("hk_afterfact_r8_binding_rows")',
    "_HK_R9_POOL_EVIDENCE": '_evidence_tagged("hk_r9_pool_evidence")',
    "_HK_R9_LEGACY_STALE_LANE_IDENTITIES": '_evidence_tagged("hk_r9_legacy_stale_lane_identities")',
    "_HK_MORNING_HISTORY_20261023": '_evidence_tagged("hk_morning_history_20261023")',
    "_HK_MORNING_SELECTION_RECOVERY_ROWS": '_evidence_tagged("hk_morning_selection_recovery_rows")',
    "_HK_MORNING_HISTORY_SAFE_PACKETS": '_evidence_tagged("hk_morning_history_safe_packets")',
    "_HK_R8_COMMON_REQUIRED_EVIDENCE": '_evidence_tagged("hk_r8_common_required_evidence")',
    "_HK_R8_POOL_EVIDENCE": '_evidence_tagged("hk_r8_pool_evidence")',
    "_HK_MORNING_SELECTION_RECOVERY_REQUIRED_EVIDENCE": '_evidence_tagged("hk_morning_selection_recovery_required_evidence")',
    "_HK_R9_LEGACY_STALE_POOL_CONTRACTS": '_evidence_tagged("hk_r9_legacy_stale_pool_contracts")',
    "_REVOKED_HK_STAGE_BACKFILL_KEYS": '_evidence_tagged("revoked_hk_stage_backfill_keys")',
    "_APPROVED_EXACT_STAGE_BACKFILLS": '_evidence_tagged("approved_exact_stage_backfills")',
}
NESTED = [
    "_stage_projection_status", "_legacy_hk_consumer_rows_match", "_legacy_hk_pit_observation",
    "_hk_morning_selection_recovery_observation", "_hk_display_mode", "project_shared_selection",
]
CTX_ANCHOR = "    configured_selection_root = stage_center_selection_root"
CTX_BLOCK = [
    "    projection_ctx = ProjectionContext(",
    "        store=store,",
    "        configured_selection_root=configured_selection_root,",
    "        configured_pool_source=configured_pool_source,",
    "        resolved_pool_source=resolved_pool_source,",
    "        configured_morning_news_root=configured_morning_news_root,",
    "        morning_history_observation=_hk_morning_history_observation,",
    "        morning_selection_recovery_bindings=_HK_MORNING_SELECTION_RECOVERY_BINDING_BY_DATE_STAGE,",
    "    )",
]
EVIDENCE_IMPORT = (
    "from apps.api.v4_api.evidence.loader import (\n"
    "    row_dicts as _evidence_row_dicts,\n"
    "    tagged_value as _evidence_tagged,\n"
    "    tuple_keyed as _evidence_tuple_keyed,\n"
    "    tuple_rows as _evidence_tuple_rows,\n"
    ")"
)
PROJECTION_IMPORT = "from apps.api.v4_api.projection import ProjectionContext, project_shared_selection"

SW_ROUTE_ANCHOR = '    @app.get("/api/v4/workbench/stage")'
SW_BLOCK1 = "        morning_binding = _HK_MORNING_SELECTION_RECOVERY_BINDING_BY_DATE_STAGE.get("
SW_GUARD2 = "        if market is not None or backfill_run_id is not None:"
SW_BLOCK3 = "        if shared_selection_consumer is not None:"
SW_FALLBACK = "        return stage_runner.read_workbench(selected, stage, limit)"
SW_CTX_MAP = [
    (r"\b_APPROVED_EXACT_STAGE_BACKFILLS\b", "ctx.approved_exact_stage_backfills"),
    (r"\b_HK_MORNING_SELECTION_RECOVERY_BINDING_BY_DATE_STAGE\b", "ctx.morning_binding_by_date_stage"),
    (r"\b_quarantine_known_hk_auction_pool_mismatch\b", "ctx.quarantine_hk_auction_pool_mismatch"),
    (r"\b_read_hk_morning_selection_recovery_override\b", "ctx.hk_morning_override"),
    (r"\b_read_r8_exact_target_hk_override\b", "ctx.r8_override"),
    (r"\b_read_r9_exact_target_hk_override\b", "ctx.r9_override"),
    (r"\b_resolve_exact_backfill_selection_root\b", "ctx.scoped_selection_root"),
    (r"\b_new_scoped_stage_selection_consumer\b", "ctx.new_scoped_consumer"),
    (r"\bprojection_ctx\b", "ctx.projection"),
    (r"\bconfigured_selection_root\b", "ctx.configured_selection_root"),
    (r"\bapproved_research_reader\b", "ctx.approved_research_reader"),
    (r"\bshared_selection_consumer\b", "ctx.shared_selection_consumer"),
    (r"\bstage_runner\b", "ctx.stage_runner"),
]
SW_SELF_CALL = re.compile(
    r"(?P<ind>[ ]*)exact_hk = stage_workbench\(\s*"
    r"date=selected,\s*stage=stage,\s*limit=limit,\s*"
    r'market="HK_CONNECT",\s*backfill_run_id=day24_run_id,\s*\)'
)
SW_CTX_BLOCK = [
    "    stage_workbench_ctx = StageWorkbenchContext(",
    "        approved_research_reader=approved_research_reader,",
    "        shared_selection_consumer=shared_selection_consumer,",
    "        configured_selection_root=configured_selection_root,",
    "        stage_runner=stage_runner,",
    "        projection=projection_ctx,",
    "        approved_exact_stage_backfills=_APPROVED_EXACT_STAGE_BACKFILLS,",
    "        morning_binding_by_date_stage=_HK_MORNING_SELECTION_RECOVERY_BINDING_BY_DATE_STAGE,",
    "        quarantine_hk_auction_pool_mismatch=_quarantine_known_hk_auction_pool_mismatch,",
    "        hk_morning_override=_read_hk_morning_selection_recovery_override,",
    "        r8_override=_read_r8_exact_target_hk_override,",
    "        r9_override=_read_r9_exact_target_hk_override,",
    "        scoped_selection_root=_resolve_exact_backfill_selection_root,",
    "        new_scoped_consumer=_new_scoped_stage_selection_consumer,",
    "    )",
]
SW_IMPORT = "from apps.api.v4_api.stage_workbench import StageWorkbenchContext, read_stage_workbench"


class OverlayError(RuntimeError):
    pass


def _already_imported(lines: Sequence[str], module: str) -> bool:
    """True when the app already imports this module, so passes stay idempotent."""
    prefix = f"from {module} import"
    return any(line.startswith(prefix) for line in lines)


def _assignment_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id
    return None


def _rewrite_app(path: Path) -> dict[str, int]:
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    tree = ast.parse(src)
    create = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_app"), None)
    if create is None:
        raise OverlayError("create_app not found")
    edits: list[tuple[int, int, list[str]]] = []
    applied: set[str] = set()
    for node in tree.body:
        name = _assignment_name(node)
        if name in CONSTANTS:
            edits.append((node.lineno, node.end_lineno, [f"{name} = {CONSTANTS[name]}"]))
            applied.add(name)
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Subscript):
            if ast.unparse(node.targets[0].value).startswith("_APPROVED_EXACT_STAGE_BACKFILLS"):
                edits.append((node.lineno, node.end_lineno, []))
        if isinstance(node, ast.For):
            body = "\n".join(lines[node.lineno - 1:node.end_lineno])
            if "_APPROVED_EXACT_STAGE_BACKFILLS" in body:
                edits.append((node.lineno, node.end_lineno, []))
    missing = set(CONSTANTS) - applied
    if missing:
        raise OverlayError(f"constant anchors missing: {sorted(missing)}")
    nested_found: set[str] = set()
    for node in ast.walk(create):
        if isinstance(node, ast.FunctionDef) and node.name in NESTED and node is not create:
            edits.append((node.lineno, node.end_lineno, []))
            nested_found.add(node.name)
    if nested_found != set(NESTED):
        raise OverlayError(f"nested function anchors missing: {sorted(set(NESTED) - nested_found)}")
    anchor = next((i for i, line in enumerate(lines) if line == CTX_ANCHOR), None)
    if anchor is None:
        raise OverlayError("projection context anchor not found")
    edits.append((anchor + 2, anchor + 1, CTX_BLOCK))  # insert after the anchor line
    edits.sort(key=lambda item: item[0], reverse=True)
    for start, end, replacement in edits:
        lines[start - 1:end] = replacement
    text = "\n".join(lines)
    if "project_shared_selection(" in text:
        text = re.sub(
            r"project_shared_selection\((?!projection_ctx)",
            "project_shared_selection(projection_ctx, ",
            text,
        )
    if "project_shared_selection(projection_ctx, projection_ctx" in text:
        raise OverlayError("projection_ctx passed twice")
    import_anchor = "from apps.api.v4_api.baimao_router import"
    index = next((i for i, line in enumerate(text.splitlines()) if line.startswith(import_anchor)), None)
    if index is None:
        raise OverlayError("import anchor not found")
    out = text.splitlines()
    missing = [
        import_text
        for module, import_text in (
            ("apps.api.v4_api.evidence.loader", EVIDENCE_IMPORT),
            ("apps.api.v4_api.projection", PROJECTION_IMPORT),
        )
        if not _already_imported(out, module)
    ]
    if missing:
        out.insert(index, "\n".join(missing))
    text = "\n".join(out) + "\n"
    ast.parse(text)
    for name in CONSTANTS:
        if not re.search(rf"^{re.escape(name)} = _evidence_", text, re.M):
            raise OverlayError(f"constant not bound to evidence loader: {name}")
    path.write_text(text, encoding="utf-8")
    return {"constants": len(applied), "nested_removed": len(nested_found),
            "lines": len(text.splitlines()),
            "sha256": hashlib.sha256(text.encode()).hexdigest()}


SW_MODULE_HEAD = '''"""Read, verify and project one stage-workbench response.

Split out of ``create_app``: the branches below were closures over the
configured roots and the consumer; they now take an explicit
``StageWorkbenchContext`` so the runtime dependency is visible.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from fastapi import HTTPException

from apps.api.v4_api.projection import ProjectionContext, project_shared_selection
from contracts.trading_safety import TRADING_SAFETY_FLAGS
from stage_center.research_read_binding import ResearchReadError


@dataclass(frozen=True)
class StageWorkbenchContext:
    approved_research_reader: Any
    shared_selection_consumer: Any
    configured_selection_root: Any
    stage_runner: Any
    projection: ProjectionContext
    approved_exact_stage_backfills: Mapping[Any, Any]
    morning_binding_by_date_stage: Mapping[Any, Any]
    quarantine_hk_auction_pool_mismatch: Callable[..., Any]
    hk_morning_override: Callable[..., Any]
    r8_override: Callable[..., Any]
    r9_override: Callable[..., Any]
    scoped_selection_root: Callable[..., Any]
    new_scoped_consumer: Callable[..., Any]


def read_stage_workbench(
    ctx: StageWorkbenchContext,
    selected: str,
    stage: str,
    limit: int,
    market: str | None,
    backfill_run_id: str | None,
) -> dict:
    response = _research_binding_response(ctx, selected, stage, limit, market, backfill_run_id)
    if response is not None:
        return response
    if market is not None or backfill_run_id is not None:
        return _exact_backfill_response(ctx, selected, stage, limit, market, backfill_run_id)
    response = _ordinary_selection_response(ctx, selected, stage, limit, market, backfill_run_id)
    if response is not None:
        return response
    return ctx.stage_runner.read_workbench(selected, stage, limit)


'''

SW_SIGNATURE = (
    "def {name}(\n"
    "    ctx: StageWorkbenchContext,\n"
    "    selected: str,\n"
    "    stage: str,\n"
    "    limit: int,\n"
    "    market: str | None,\n"
    "    backfill_run_id: str | None,\n"
    ") -> dict | None:\n"
)


def _index(lines: Sequence[str], anchor: str, start: int = 0) -> int:
    for index in range(start, len(lines)):
        if lines[index] == anchor:
            return index
    raise OverlayError(f"stage_workbench anchor not found: {anchor.strip()}")


def _transform_block(body: Sequence[str], *, self_call: bool) -> str:
    text = "\n".join(line[4:] if line.startswith("    ") else line for line in body)
    if self_call:
        text, count = SW_SELF_CALL.subn(
            lambda m: (
                f'{m["ind"]}# The route validated this date and stage before reaching\n'
                f'{m["ind"]}# here, so the module read is called without re-entering it.\n'
                f'{m["ind"]}exact_hk = read_stage_workbench(\n'
                f'{m["ind"]}    ctx, selected, stage, limit, "HK_CONNECT", day24_run_id,\n'
                f'{m["ind"]})'
            ),
            text,
        )
        if count != 1:
            raise OverlayError(f"expected one recursive self-call, got {count}")
    for pattern, replacement in SW_CTX_MAP:
        text = re.sub(pattern, replacement, text)
    return "\n".join(line.rstrip() for line in text.splitlines())


def _stage_workbench_module(bodies: Mapping[str, str]) -> str:
    module = SW_MODULE_HEAD
    module += SW_SIGNATURE.format(name="_research_binding_response") + bodies["_research_binding_response"]
    module += "\n    return None\n\n\n"
    module += SW_SIGNATURE.format(name="_exact_backfill_response") + bodies["_exact_backfill_response"]
    module += "\n\n\n"
    module += SW_SIGNATURE.format(name="_ordinary_selection_response") + bodies["_ordinary_selection_response"]
    return module + "\n    return None\n"


def _split_stage_workbench(
    path: Path, reviewed_module: Path | None, out_module: Path
) -> dict[str, int]:
    """Move stage_workbench's three branches into a module and delegate."""
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    route = _index(lines, SW_ROUTE_ANCHOR)
    block1 = _index(lines, SW_BLOCK1, start=route)
    while block1 > route and lines[block1 - 1].strip().startswith("#"):
        block1 -= 1
    guard2 = _index(lines, SW_GUARD2, start=block1)
    block3 = _index(lines, SW_BLOCK3, start=guard2)
    fallback = _index(lines, SW_FALLBACK, start=block3)
    bodies = {
        "_research_binding_response": _transform_block(lines[block1:guard2], self_call=False),
        "_exact_backfill_response": _transform_block(lines[guard2 + 1:block3], self_call=False),
        "_ordinary_selection_response": _transform_block(lines[block3:fallback], self_call=True),
    }
    module = _stage_workbench_module(bodies)
    ast.parse(module)
    if reviewed_module is not None:
        if module != reviewed_module.read_text(encoding="utf-8"):
            raise OverlayError("generated stage_workbench module differs from the reviewed file")

    delegation = [
        "        return read_stage_workbench(",
        "            stage_workbench_ctx, selected, stage, limit, market, backfill_run_id",
        "        )",
    ]
    new_lines = lines[:block1] + delegation + lines[fallback + 1:]
    route = _index(new_lines, SW_ROUTE_ANCHOR)
    new_lines[route:route] = SW_CTX_BLOCK
    projection_import = _index(new_lines, "from apps.api.v4_api.projection import ProjectionContext, project_shared_selection")
    if not _already_imported(new_lines, "apps.api.v4_api.stage_workbench"):
        new_lines.insert(projection_import + 1, SW_IMPORT)
    text = "\n".join(new_lines) + "\n"
    ast.parse(text)
    path.write_text(text, encoding="utf-8")
    out_module.write_text(module, encoding="utf-8")
    return {"module_lines": len(module.splitlines()), "app_lines": len(new_lines)}


HV_NAMES = [
    ("_quarantine_known_hk_auction_pool_mismatch", "quarantine_known_hk_auction_pool_mismatch"),
    ("_read_exact_target_hk_override", "read_exact_target_hk_override"),
    ("_read_r8_exact_target_hk_override", "read_r8_exact_target_hk_override"),
    ("_read_r9_exact_target_hk_override", "read_r9_exact_target_hk_override"),
    ("_read_hk_morning_selection_recovery_override", "read_hk_morning_selection_recovery_override"),
]
HV_CTX_MAP = [
    (r"\bconfigured_selection_root\b", "ctx.configured_selection_root"),
    (r"\bshared_selection_consumer\b", "ctx.shared_selection_consumer"),
    (r"\bstage_workbench\(", "ctx.read_workbench("),
    (r"\b_HK_MORNING_SELECTION_RECOVERY_BINDING_BY_DATE_STAGE\b", "ctx.morning_binding_by_date_stage"),
    (r"\b_HK_R8_BINDING_BY_DATE_STAGE\b", "ctx.r8_binding_by_date_stage"),
    (r"\b_HK_R8_POOL_EVIDENCE\b", "ctx.r8_pool_evidence"),
    (r"\b_HK_R9_BINDING_BY_DATE_STAGE\b", "ctx.r9_binding_by_date_stage"),
    (r"\b_HK_R9_LEGACY_STALE_LANE_IDENTITIES\b", "ctx.r9_legacy_stale_lane_identities"),
    (r"\b_HK_R9_LEGACY_STALE_POOL_CONTRACTS\b", "ctx.r9_legacy_stale_pool_contracts"),
    (r"\b_HK_R9_POOL_EVIDENCE\b", "ctx.r9_pool_evidence"),
]
HV_MODULE_HEAD = '''"""Exact HK override and observation reads.

These five readers were closures inside ``create_app``. They now take an
explicit ``HkVerifyContext`` so their store, consumer and evidence
dependencies are visible at the call site.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from fastapi import HTTPException


@dataclass(frozen=True)
class HkVerifyContext:
    configured_selection_root: Any
    shared_selection_consumer: Any
    read_workbench: Callable[..., dict]
    morning_binding_by_date_stage: Mapping[Any, Any]
    r8_binding_by_date_stage: Mapping[Any, Any]
    r8_pool_evidence: Any
    r9_binding_by_date_stage: Mapping[Any, Any]
    r9_legacy_stale_lane_identities: Any
    r9_legacy_stale_pool_contracts: Any
    r9_pool_evidence: Any


'''

HV_IMPORT = (
    "from apps.api.v4_api.hk_verify import (\n"
    "    HkVerifyContext,\n"
    "    quarantine_known_hk_auction_pool_mismatch,\n"
    "    read_exact_target_hk_override,\n"
    "    read_hk_morning_selection_recovery_override,\n"
    "    read_r8_exact_target_hk_override,\n"
    "    read_r9_exact_target_hk_override,\n"
    ")\n"
)
HV_CTX_BLOCK = [
    "    hk_verify_ctx = HkVerifyContext(",
    "        configured_selection_root=configured_selection_root,",
    "        shared_selection_consumer=shared_selection_consumer,",
    "        read_workbench=stage_workbench,",
    "        morning_binding_by_date_stage=_HK_MORNING_SELECTION_RECOVERY_BINDING_BY_DATE_STAGE,",
    "        r8_binding_by_date_stage=_HK_R8_BINDING_BY_DATE_STAGE,",
    "        r8_pool_evidence=_HK_R8_POOL_EVIDENCE,",
    "        r9_binding_by_date_stage=_HK_R9_BINDING_BY_DATE_STAGE,",
    "        r9_legacy_stale_lane_identities=_HK_R9_LEGACY_STALE_LANE_IDENTITIES,",
    "        r9_legacy_stale_pool_contracts=_HK_R9_LEGACY_STALE_POOL_CONTRACTS,",
    "        r9_pool_evidence=_HK_R9_POOL_EVIDENCE,",
    "    )",
]
HV_REWIRE = [
    ("        quarantine_hk_auction_pool_mismatch=_quarantine_known_hk_auction_pool_mismatch,",
     "        quarantine_hk_auction_pool_mismatch=partial(quarantine_known_hk_auction_pool_mismatch, hk_verify_ctx),"),
    ("        hk_morning_override=_read_hk_morning_selection_recovery_override,",
     "        hk_morning_override=partial(read_hk_morning_selection_recovery_override, hk_verify_ctx),"),
    ("        r8_override=_read_r8_exact_target_hk_override,",
     "        r8_override=partial(read_r8_exact_target_hk_override, hk_verify_ctx),"),
    ("        r9_override=_read_r9_exact_target_hk_override,",
     "        r9_override=partial(read_r9_exact_target_hk_override, hk_verify_ctx),"),
]
HV_ROUTE_DELEGATION = [
    "        return read_stage_workbench(",
    "            stage_workbench_ctx, selected, stage, limit, market, backfill_run_id",
    "        )",
]


def _insert_ctx_parameter(text: str, name: str) -> str:
    """Put ``ctx: HkVerifyContext`` in front of the function's first parameter."""
    head = f"def {name}("
    index = text.index(head) + len(head)
    gap_start = index
    while index < len(text) and text[index] in " \t\n":
        index += 1
    multiline = "\n" in text[gap_start:index]
    separator = "\n    " if multiline else ""
    return (
        text[:gap_start] + separator + "ctx: HkVerifyContext,"
        + ("\n    " if multiline else " ") + text[index:]
    )


def _split_hk_verify(path: Path, reviewed_module: Path | None, out_module: Path) -> dict[str, int]:
    """Move the five HK override readers into hk_verify.py."""
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    tree = ast.parse(src)
    create = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_app"), None)
    if create is None:
        raise OverlayError("create_app not found")
    old_names = dict(HV_NAMES)
    found = {n.name: n for n in ast.walk(create) if isinstance(n, ast.FunctionDef) and n.name in old_names}
    missing = set(old_names) - set(found)
    if missing:
        raise OverlayError(f"hk verify anchors missing: {sorted(missing)}")

    ranges: list[tuple[int, int]] = []
    bodies: dict[str, str] = {}
    for old, new in HV_NAMES:
        node = found[old]
        start = node.lineno - 1
        while start > 0 and lines[start - 1].strip().startswith("#"):
            start -= 1
        end = node.end_lineno
        while end < len(lines) and lines[end].strip() == "":
            end += 1
        ranges.append((start, end))
        text = "\n".join(line[4:] if line.startswith("    ") else line for line in lines[start:end])
        text = text.replace(f"def {old}(", f"def {new}(")
        text = _insert_ctx_parameter(text, new)
        for other_old, other_new in HV_NAMES:
            text = re.sub(rf"\b{re.escape(other_old)}\(", f"{other_new}(ctx, ", text)
        for pattern, replacement in HV_CTX_MAP:
            text = re.sub(pattern, replacement, text)
        bodies[new] = "\n".join(line.rstrip() for line in text.splitlines()).rstrip("\n")

    module = HV_MODULE_HEAD + "\n\n\n".join(bodies[new] for _, new in HV_NAMES) + "\n"
    ast.parse(module)
    if reviewed_module is not None and module != reviewed_module.read_text(encoding="utf-8"):
        raise OverlayError("generated hk_verify module differs from the reviewed file")

    new_lines = list(lines)
    for start, end in sorted(ranges, reverse=True):
        del new_lines[start:end]

    ctx_start = new_lines.index("    stage_workbench_ctx = StageWorkbenchContext(")
    ctx_end = new_lines.index("    )", ctx_start)
    stage_block = new_lines[ctx_start:ctx_end + 1]
    del new_lines[ctx_start:ctx_end + 1]
    for index, line in enumerate(stage_block):
        for before, after in HV_REWIRE:
            if line == before:
                stage_block[index] = after
    if sum(1 for line in stage_block if line.startswith("        ") and "partial(" in line) != len(HV_REWIRE):
        raise OverlayError("stage_workbench context rewiring incomplete")

    delegation = next(
        (i for i in range(len(new_lines) - 2) if new_lines[i:i + 3] == HV_ROUTE_DELEGATION), None
    )
    if delegation is None:
        raise OverlayError("stage_workbench route delegation not found")
    insert_at = delegation + 3
    new_lines[insert_at:insert_at] = [""] + HV_CTX_BLOCK + [""] + stage_block + [""]

    typing_import = new_lines.index("from typing import Any, Mapping")
    new_lines.insert(typing_import + 1, "from functools import partial")
    stage_import = next(i for i, line in enumerate(new_lines)
                        if line.startswith("from apps.api.v4_api.stage_workbench import"))
    if not _already_imported(new_lines, "apps.api.v4_api.hk_verify"):
        new_lines.insert(stage_import + 1, HV_IMPORT.rstrip("\n"))

    text = "\n".join(new_lines) + "\n"
    ast.parse(text)
    path.write_text(text, encoding="utf-8")
    out_module.write_text(module, encoding="utf-8")
    return {"hk_module_lines": len(module.splitlines()), "hk_app_lines": len(new_lines)}


RT_ROUTES = [
    "healthz", "readyz", "stage_metadata", "run_date_list",
    "stage_workbench_ensure", "stage_workbench_batch", "shared_stage_selection",
    "manager_stage_selection", "shared_stage_selection_ensure",
]
RT_HELPER = "shared_selection_unconfigured"
RT_HELPER_NEW = "unconfigured_selection"
RT_CTX_MAP = [
    (r"\b_catalog\(", "ctx.catalog("),
    (r"\b_strict_date\(", "ctx.strict_date("),
    (r"\breview_store\.", "ctx.review_store."),
    (r"\bresearch_source\.", "ctx.research_source."),
    (r"\bprojection_ctx\b", "ctx.projection"),
    (r"\bshared_selection_consumer\b", "ctx.shared_selection_consumer"),
    (r"\bstage_runner\b", "ctx.stage_runner"),
    (r"\bstage_workbench\(", "ctx.read_stage_workbench("),
    (rf"\b{RT_HELPER}\(", f"{RT_HELPER_NEW}("),
    (r"\b_project_stage_timeline_summary\(", "ctx.stage_timeline_summary("),
    (r"\b_bounded_stage_summaries\(", "ctx.bounded_summaries("),
    (r"\b_STAGE_BATCH_CAPACITY\b", "ctx.batch_capacity"),
]
RT_MODULE_HEAD = '''"""HTTP routes moved out of ``create_app``.

Each route reads its stores and the projection context through an explicit
``RouteContext``. ``stage_workbench`` itself stays beside the three
contexts it assembles.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Query

from apps.api.v4_api.projection import ProjectionContext, project_shared_selection
from contracts.stages import FROZEN_STAGE_IDS, STAGE_DEFINITIONS
from contracts.trading_safety import TRADING_SAFETY_FLAGS


@dataclass(frozen=True)
class RouteContext:
    app: FastAPI
    catalog: Callable[[], dict]
    strict_date: Callable[[str], str]
    review_store: Any
    research_source: Any
    projection: ProjectionContext
    shared_selection_consumer: Any
    stage_runner: Any
    read_stage_workbench: Callable[..., dict]
    stage_timeline_summary: Callable[[Any], dict]
    bounded_summaries: Callable[..., dict]
    batch_capacity: int

'''

RT_REGISTER_HEAD = '''def register_routes(ctx: RouteContext) -> None:
    app = ctx.app

'''

RT_WIRING = [
    "    route_ctx = RouteContext(",
    "        app=app,",
    "        catalog=_catalog,",
    "        strict_date=_strict_date,",
    "        review_store=review_store,",
    "        research_source=research_source,",
    "        projection=projection_ctx,",
    "        shared_selection_consumer=shared_selection_consumer,",
    "        stage_runner=stage_runner,",
    "        read_stage_workbench=stage_workbench,",
    "        stage_timeline_summary=_project_stage_timeline_summary,",
    "        bounded_summaries=_bounded_stage_summaries,",
    "        batch_capacity=_STAGE_BATCH_CAPACITY,",
    "    )",
    "    register_routes(route_ctx)",
]
RT_IMPORT = "from apps.api.v4_api.routes import RouteContext, register_routes"


def _dedent_block(lines: Sequence[str], start: int, end: int) -> str:
    text = "\n".join(line[4:] if line.startswith("    ") else line for line in lines[start:end])
    return "\n".join(line.rstrip() for line in text.splitlines()).rstrip("\n")


def _split_routes(path: Path, reviewed_module: Path | None, out_module: Path) -> dict[str, int]:
    """Move the HTTP route closures out of create_app into routes.py."""
    src = path.read_text(encoding="utf-8")
    lines = src.splitlines()
    tree = ast.parse(src)
    create = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_app"), None)
    if create is None:
        raise OverlayError("create_app not found")
    wanted = set(RT_ROUTES) | {RT_HELPER}
    found = {n.name: n for n in ast.walk(create) if isinstance(n, ast.FunctionDef) and n.name in wanted}
    missing = wanted - set(found)
    if missing:
        raise OverlayError(f"route anchors missing: {sorted(missing)}")

    bodies: dict[str, str] = {}
    ranges: list[tuple[int, int]] = []
    for name in [RT_HELPER] + RT_ROUTES:
        node = found[name]
        start = min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1
        end = node.end_lineno
        while end < len(lines) and lines[end].strip() == "":
            end += 1
        ranges.append((start, end))
        text = _dedent_block(lines, start, end)
        if name == RT_HELPER:
            text = text.replace(f"def {RT_HELPER}(", f"def {RT_HELPER_NEW}(")
        for pattern, replacement in RT_CTX_MAP:
            text = re.sub(pattern, replacement, text)
        bodies[name] = text

    routed = [
        "\n".join(("    " + line) if line.strip() else "" for line in bodies[name].splitlines())
        for name in RT_ROUTES
    ]
    module = (
        RT_MODULE_HEAD
        + bodies[RT_HELPER] + "\n\n\n"
        + RT_REGISTER_HEAD
        + "\n\n".join(routed) + "\n"
    )
    ast.parse(module)
    if reviewed_module is not None and module != reviewed_module.read_text(encoding="utf-8"):
        raise OverlayError("generated routes module differs from the reviewed file")

    new_lines = list(lines)
    for start, end in sorted(ranges, reverse=True):
        del new_lines[start:end]

    stage_ctx = new_lines.index("    stage_workbench_ctx = StageWorkbenchContext(")
    close = new_lines.index("    )", stage_ctx)
    new_lines[close + 1:close + 1] = [""] + RT_WIRING

    import_anchor = next(
        (i for i, line in enumerate(new_lines) if line.startswith("from apps.api.v4_api.hk_verify import")),
        None,
    )
    if import_anchor is not None:
        while new_lines[import_anchor] != ")":
            import_anchor += 1
    else:
        import_anchor = max(i for i, line in enumerate(new_lines[:20])
                            if line.startswith(("import ", "from ")))
    if not _already_imported(new_lines, "apps.api.v4_api.routes"):
        new_lines.insert(import_anchor + 1, RT_IMPORT)

    text = "\n".join(new_lines) + "\n"
    ast.parse(text)
    path.write_text(text, encoding="utf-8")
    out_module.write_text(module, encoding="utf-8")
    return {"routes_module_lines": len(module.splitlines()), "routes_app_lines": len(new_lines)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", type=Path, required=True, help="copy of the release app to modify")
    parser.add_argument("--source-root", type=Path, required=True, help="worktree holding evidence/ and projection.py")
    parser.add_argument(
        "--stage-workbench", action="store_true",
        help="also move stage_workbench's three branches into stage_workbench.py",
    )
    parser.add_argument(
        "--hk-verify", action="store_true",
        help="also move the five HK override readers into hk_verify.py (needs --stage-workbench)",
    )
    parser.add_argument(
        "--routes", action="store_true",
        help="also move the HTTP route closures into routes.py (needs --stage-workbench --hk-verify)",
    )
    args = parser.parse_args(argv)
    app = args.app_root.resolve()
    source = args.source_root.resolve()
    if not (app / "apps/api/v4_api/app.py").is_file():
        raise OverlayError(f"not an app root: {app}")
    target_evidence = app / "apps/api/v4_api/evidence"
    if target_evidence.exists():
        shutil.rmtree(target_evidence)
    shutil.copytree(
        source / "apps/api/v4_api/evidence", target_evidence,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    shutil.copy2(source / "apps/api/v4_api/projection.py", app / "apps/api/v4_api/projection.py")
    receipt = _rewrite_app(app / "apps/api/v4_api/app.py")
    if args.stage_workbench:
        receipt.update(
            _split_stage_workbench(
                app / "apps/api/v4_api/app.py",
                source / "apps/api/v4_api/stage_workbench.py",
                app / "apps/api/v4_api/stage_workbench.py",
            )
        )
    if args.hk_verify:
        if not args.stage_workbench:
            raise OverlayError("--hk-verify needs --stage-workbench")
        receipt.update(
            _split_hk_verify(
                app / "apps/api/v4_api/app.py",
                source / "apps/api/v4_api/hk_verify.py",
                app / "apps/api/v4_api/hk_verify.py",
            )
        )
    if args.routes:
        if not (args.stage_workbench and args.hk_verify):
            raise OverlayError("--routes needs --stage-workbench and --hk-verify")
        receipt.update(
            _split_routes(
                app / "apps/api/v4_api/app.py",
                source / "apps/api/v4_api/routes.py",
                app / "apps/api/v4_api/routes.py",
            )
        )
    receipt["app_root"] = str(app)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
