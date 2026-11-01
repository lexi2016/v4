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
IMPORT_BLOCK = (
    "from apps.api.v4_api.evidence.loader import (\n"
    "    row_dicts as _evidence_row_dicts,\n"
    "    tagged_value as _evidence_tagged,\n"
    "    tuple_keyed as _evidence_tuple_keyed,\n"
    "    tuple_rows as _evidence_tuple_rows,\n"
    ")\n"
    "from apps.api.v4_api.projection import ProjectionContext, project_shared_selection\n"
)


class OverlayError(RuntimeError):
    pass


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
        text = text.replace("project_shared_selection(", "project_shared_selection(projection_ctx, ")
    import_anchor = "from apps.api.v4_api.baimao_router import"
    index = next((i for i, line in enumerate(text.splitlines()) if line.startswith(import_anchor)), None)
    if index is None:
        raise OverlayError("import anchor not found")
    out = text.splitlines()
    out.insert(index, IMPORT_BLOCK.rstrip("\n"))
    text = "\n".join(out) + "\n"
    ast.parse(text)
    for name in CONSTANTS:
        if not re.search(rf"^{re.escape(name)} = _evidence_", text, re.M):
            raise OverlayError(f"constant not bound to evidence loader: {name}")
    path.write_text(text, encoding="utf-8")
    return {"constants": len(applied), "nested_removed": len(nested_found),
            "lines": len(text.splitlines()),
            "sha256": hashlib.sha256(text.encode()).hexdigest()}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", type=Path, required=True, help="copy of the release app to modify")
    parser.add_argument("--source-root", type=Path, required=True, help="worktree holding evidence/ and projection.py")
    args = parser.parse_args(argv)
    app = args.app_root.resolve()
    source = args.source_root.resolve()
    if not (app / "apps/api/v4_api/app.py").is_file():
        raise OverlayError(f"not an app root: {app}")
    target_evidence = app / "apps/api/v4_api/evidence"
    if target_evidence.exists():
        shutil.rmtree(target_evidence)
    shutil.copytree(source / "apps/api/v4_api/evidence", target_evidence)
    shutil.copy2(source / "apps/api/v4_api/projection.py", app / "apps/api/v4_api/projection.py")
    receipt = _rewrite_app(app / "apps/api/v4_api/app.py")
    receipt["app_root"] = str(app)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
