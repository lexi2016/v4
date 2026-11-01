#!/usr/bin/env python3
"""Prepare two isolated, inventory-pinned app copies; never activate a release.

The API runtime has fixes absent from the source branch. Apply only the frozen
reviewed hunks, preserving its namespace calling convention and optional imports.
All output is a new directory under /private/tmp. No service or data writes.
"""
from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from ops.apply_tech_debt_overlay import main as overlay_main

SOURCE_COMMIT = "c06db9db262b9c756d8401dcfc43b70d34c6f3ef"
BASE_MANIFEST_SHA = "8f93397a31986a1871276ee90b7f4d89e2a31d5691eeb6ea529e0cbea67a481b"
REVIEWED_COMMITS = ["97ff8531d", "5419e52dd", "8f39cdf67", "c06db9db2"]
ENTITY_PATHS = (
    "contracts/a_share_code.py", "contracts/a_share_entity_filter.py",
    "contracts/research.py", "domains/preselection_materializer.py",
    "domains/research_hourly.py", "domains/research.py",
    "domains/_preselection_parts/pool_assembly.py",
    "apps/api/v4_api/preselection_service.py",
    "apps/api/v4_api/research_lane_router.py", "apps/api/v4_api/research_router.py",
    "stage_center/consumer.py",
)
TECH_PATHS = (
    "apps/api/v4_api/app.py", "apps/api/v4_api/projection.py",
    "apps/api/v4_api/stage_workbench.py", "apps/api/v4_api/hk_verify.py",
    "apps/api/v4_api/routes.py",
)
PRESERVED_MODULES = (
    "apps/__init__.py", "apps/api/__init__.py",
    "domains/related_pdf_cursor.py", "domains/related_pdf_reports.py",
    "infrastructure/operations_sop_reader.py", "infrastructure/research_classification_view.py",
    "infrastructure/research_workbench_host.py", "infrastructure/research_workbench_skill_r2.py",
    "infrastructure/zsxq_pdf_search_index.py",
    "stage_center/snapshot_recovery.py", "stage_center/snapshot_selection.py",
)
CACHE_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
PACKAGING_PATHS = (
    "ops/apply_tech_debt_overlay.py", "ops/prepare_tech_debt_candidate.py",
    "ops/capture_response_baseline.py", "tests/test_apply_tech_debt_overlay.py",
    "tests/test_prepare_tech_debt_candidate.py", "tests/test_tech_debt_candidate_protocol.py",
    "tests/test_capture_response_baseline.py",
    "docs/handoffs/tech-debt-candidate-20261101/README.md",
)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def validate_source_identity(source: Path) -> dict:
    """Separate packaging HEAD from the exact frozen business-input blobs."""
    def git(*args: str) -> bytes:
        return subprocess.check_output(["git", *args], cwd=source)

    packaging_head = git("rev-parse", "HEAD").decode().strip()
    if git("merge-base", SOURCE_COMMIT, packaging_head).decode().strip() != SOURCE_COMMIT:
        raise ValueError("SOURCE_COMMIT_NOT_ANCESTOR")
    committed_paths = set(git("log", "--format=", "--name-only", f"{SOURCE_COMMIT}..{packaging_head}").decode().splitlines()) - {""}
    if committed_paths - set(PACKAGING_PATHS):
        raise ValueError("NON_PACKAGING_COMMITTED_PATHS:" + repr(sorted(committed_paths - set(PACKAGING_PATHS))))
    prefix = "apps/api/v4_api/evidence"
    frozen_evidence = set(git("ls-tree", "-r", "-z", "--name-only", SOURCE_COMMIT, "--", prefix).decode().strip("\0").split("\0")) - {""}
    actual_evidence = set()
    for path in (source / prefix).rglob("*"):
        if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
            continue
        if path.is_symlink():
            raise ValueError("REVIEWED_SOURCE_SYMLINK:" + str(path.relative_to(source)))
        if path.is_file():
            actual_evidence.add(path.relative_to(source).as_posix())
    if actual_evidence != frozen_evidence:
        raise ValueError("REVIEWED_EVIDENCE_FILE_SET_DRIFT")
    hashes = {}
    for relative in sorted(set(ENTITY_PATHS + TECH_PATHS) | frozen_evidence):
        path = source / relative
        if path.is_symlink() or not path.is_file():
            raise ValueError("REVIEWED_SOURCE_FILE_MISSING_OR_SYMLINK:" + relative)
        raw, frozen = path.read_bytes(), git("show", f"{SOURCE_COMMIT}:{relative}")
        if raw != frozen:
            raise ValueError("REVIEWED_SOURCE_BYTES_DRIFT:" + relative)
        hashes[relative] = sha(raw)
    return {"business_source_commit": SOURCE_COMMIT,
            "packaging_source_commit": packaging_head,
            "reviewed_source_sha256": hashes}


def exact_overlay(before: bytes, after: bytes, inherited: bytes) -> bytes:
    """Reuse the prior repair's exact unique-context hunk application."""
    old, new = before.decode().splitlines(keepends=True), after.decode().splitlines(keepends=True)
    result = inherited.decode()
    cursor = 0
    for group in difflib.SequenceMatcher(None, old, new, autojunk=False).get_grouped_opcodes(3):
        old_text = "".join(old[group[0][1]:group[-1][2]])
        new_text = "".join(new[group[0][3]:group[-1][4]])
        if not old_text or result.count(old_text) != 1:
            raise ValueError("INCOMPATIBLE_OR_AMBIGUOUS_INHERITED_HUNK")
        pos = result.index(old_text)
        if pos < cursor:
            raise ValueError("INHERITED_HUNK_ORDER_MISMATCH")
        result = result[:pos] + new_text + result[pos + len(old_text):]
        cursor = pos + len(new_text)
    return result.encode()


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError("INCOMPATIBLE_OR_AMBIGUOUS_ANCHOR:" + old[:100])
    return text.replace(old, new, 1)


def pool_overlay(inherited: bytes, reviewed: bytes) -> bytes:
    """Transplant the reviewed filter around the inherited scope-based API."""
    text, source = inherited.decode(), reviewed.decode()
    imports = source.split("from __future__ import annotations\n", 1)[1].split("from domains.preselection import", 1)[0]
    text = replace_once(text, "from __future__ import annotations\n", "from __future__ import annotations\n" + imports)
    block = source[source.index("    # Storage is write-once"):source.index('    rows = payload["rows"]')]
    block = block.replace("_project_independent_pools(", "_v4_global(_v4_scope, '_project_independent_pools')(")
    text = replace_once(text, '    rows = payload["rows"]\n', block + '    rows = payload["rows"]\n')
    text = replace_once(text, "    if not rows:\n", "    if not rows:\n        if quarantine:\n            return _all_rows_quarantined(date, quarantine)\n")
    text = replace_once(text, "    return response\n", "    return summarize_pool_quarantine(response)\n")
    helper = source[source.index("def _all_rows_quarantined("):source.index("def __dedupe_by_symbol_body(")]
    text = replace_once(text, "def __dedupe_by_symbol_body(", helper + "def __dedupe_by_symbol_body(")
    return text.encode()


def entity_overlay(source: Path, runtime: Path) -> dict[str, bytes]:
    result = {}
    for relative in ENTITY_PATHS:
        after = (source / relative).read_bytes()
        inherited = runtime / relative
        if relative in ENTITY_PATHS[:2]:
            if inherited.exists():
                raise ValueError("NEW_ENTITY_MODULE_ALREADY_EXISTS:" + relative)
            result[relative] = after
            continue
        before = subprocess.check_output(["git", "show", f"97ff8531d^:{relative}"], cwd=source)
        if relative.endswith("/pool_assembly.py"):
            result[relative] = pool_overlay(inherited.read_bytes(), after)
            continue
        # The runtime has try/except optional imports absent from the branch.
        # Preserve those blocks; add the reviewed import at the future anchor.
        import_text = ""
        if relative.endswith("/research_lane_router.py"):
            import_text = "from contracts.a_share_entity_filter import (\n    FILTER_RULE_VERSION,\n    quarantine_research_stock_rows,\n)\n"
        elif relative.endswith("/research_router.py"):
            import_text = "from contracts.a_share_entity_filter import FILTER_RULE_VERSION, quarantine_research_stock_rows\n"
        if import_text:
            after = replace_once(after.decode(), import_text, "").encode()
        merged = exact_overlay(before, after, inherited.read_bytes())
        if import_text:
            merged = replace_once(merged.decode(), "from __future__ import annotations\n", "from __future__ import annotations\n" + import_text).encode()
        ast.parse(merged)
        result[relative] = merged
    return result


def load_inventory_tools(runtime: Path):
    spec = importlib.util.spec_from_file_location("official_runtime_inventory", runtime / "ops/api_release_integration.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_no_cache(root: Path) -> None:
    bad = [str(p.relative_to(root)) for p in root.rglob("*") if p.name == "__pycache__" or p.suffix in (".pyc", ".pyo")]
    if bad:
        raise ValueError("CANDIDATE_CONTAINS_CACHE:" + repr(bad[:10]))


def assert_delta(baseline, candidate) -> list[dict]:
    before = {row["path"]: row for row in baseline}
    after = {row["path"]: row for row in candidate}
    if set(before) - set(after):
        raise ValueError("CANDIDATE_DELETES_BASELINE_PATHS")
    delta = []
    for path in sorted(after):
        if after[path] == before.get(path):
            continue
        if path not in ENTITY_PATHS + TECH_PATHS and not path.startswith("apps/api/v4_api/evidence/"):
            raise ValueError("NON_ALLOWLIST_DELTA:" + path)
        delta.append({"path": path, "before": before.get(path), "after": after[path]})
    for path in PRESERVED_MODULES:
        if path not in before or after.get(path) != before[path]:
            raise ValueError("RUNTIME_UNIQUE_MODULE_NOT_PRESERVED:" + path)
    return delta


def manifest(root: Path, inventory, tools, provenance: dict, source_commit: str) -> dict:
    return {
        "schema_version": "v4.release_candidate.v1",
        "candidate": {"root": str(root), "app_root": str(root / "app"), "release_id": root.name, "module_role": "api"},
        "release_id": root.name, "app_root": str(root / "app"),
        "source_commit": source_commit, "source_provenance": provenance,
        "activation_status": "PREPARED_NOT_ACTIVATED", "deployment_status": "NOT_DEPLOYED",
        "RESEARCH_ONLY": True, "research_only": True, "production_allowed": False,
        "buy_gate_updated": False, "orders_sent": False,
        "application_inventory": {"entries": inventory, "entry_count": len(inventory), "aggregate_sha256": tools.inventory_digest(inventory)},
        "app_files": inventory, "symlinks": [row for row in inventory if row["kind"] == "symlink"],
    }


def validate_copy(root: Path, tools) -> dict:
    path = root / "release-manifest.json"
    payload = json.loads(path.read_bytes())
    actual = tools.inventory_tree(root / "app")
    if payload["application_inventory"] != {"entries": actual, "entry_count": len(actual), "aggregate_sha256": tools.inventory_digest(actual)} or payload["app_files"] != actual:
        raise ValueError("FULL_INVENTORY_MISMATCH")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": str(root / "app"),
           "V4_APP_ROOT": str(root / "app"), "V4_RELEASE_ID": root.name,
           "V4_RELEASE_MANIFEST_PATH": str(path), "V4_RELEASE_MANIFEST_SHA256": sha(path.read_bytes())}
    result = subprocess.run([sys.executable, "-B", "-c", "import json; from infrastructure.scheduling.dispatcher import validate_release_identity; print(json.dumps(validate_release_identity()))"],
                            cwd=root / "app", env=env, check=True, capture_output=True, text=True)
    assert_no_cache(root / "app")
    return json.loads(result.stdout)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-app", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    runtime, source = args.runtime_app.resolve(strict=True), args.source_root.resolve(strict=True)
    output = args.output.resolve()
    if output.parent != Path("/private/tmp") or output.exists():
        raise ValueError("OUTPUT_MUST_BE_NEW_DIRECTORY_DIRECTLY_UNDER_PRIVATE_TMP")
    source_identity = validate_source_identity(source)
    old_path = runtime.parent / "release-manifest.json"
    if sha(old_path.read_bytes()) != BASE_MANIFEST_SHA:
        raise ValueError("RUNTIME_MANIFEST_CAS_CHANGED")
    old_manifest = json.loads(old_path.read_bytes())
    if old_manifest["candidate"]["module_role"] != "api":
        raise ValueError("RUNTIME_ROLE_IS_NOT_API")
    tools = load_inventory_tools(runtime)
    original = tools.inventory_tree(runtime)
    if old_manifest["application_inventory"] != {"entries": original, "entry_count": len(original), "aggregate_sha256": tools.inventory_digest(original)}:
        raise ValueError("RUNTIME_FULL_INVENTORY_DRIFT")
    merged = entity_overlay(source, runtime)  # Fail before copying on incompatible code.
    if shutil.disk_usage(output.parent).free < 4 * sum(int(row.get("size", 0)) for row in original):
        raise ValueError("INSUFFICIENT_CANDIDATE_DISK_RESERVE")
    output.mkdir()
    evidence = output / "evidence"
    evidence.mkdir()
    baseline, candidate = output / "baseline", output / "candidate"
    shutil.copytree(runtime, baseline / "app", ignore=CACHE_IGNORE, symlinks=True)
    shutil.copytree(baseline / "app", candidate / "app", ignore=CACHE_IGNORE, symlinks=True)
    overlay_main(["--app-root", str(candidate / "app"), "--source-root", str(source), "--stage-workbench", "--hk-verify", "--routes"])
    for relative, raw in merged.items():
        (candidate / "app" / relative).write_bytes(raw)
    baseline_inventory, candidate_inventory = (tools.inventory_tree(root / "app") for root in (baseline, candidate))
    if baseline_inventory != original:
        raise ValueError("BASELINE_COPY_INVENTORY_DRIFT")
    delta = assert_delta(baseline_inventory, candidate_inventory)
    provenance = {**source_identity, "runtime_base_app": str(runtime), "runtime_base_manifest_sha256": BASE_MANIFEST_SHA,
                  "source_root": str(source), "reviewed_commits": REVIEWED_COMMITS,
                  "source_state": "FROZEN_BUSINESS_INPUTS_WITH_PACKAGING_OVERLAY",
                  "overlay_tools_sha256": {name: sha((source / name).read_bytes()) for name in ("ops/apply_tech_debt_overlay.py", "ops/prepare_tech_debt_candidate.py")}}
    write_json(baseline / "release-manifest.json", manifest(baseline, baseline_inventory, tools, {"copied_from_manifest_sha256": BASE_MANIFEST_SHA, "original_source_provenance": old_manifest.get("source_provenance")}, old_manifest["source_commit"]))
    write_json(candidate / "release-manifest.json", manifest(candidate, candidate_inventory, tools, provenance, SOURCE_COMMIT))
    identities = {name: validate_copy(root, tools) for name, root in (("baseline", baseline), ("candidate", candidate))}
    for item in delta:
        relative = item["path"]
        if relative.endswith(".py"):
            ast.parse((candidate / "app" / relative).read_bytes())
    diffs = []
    for item in delta:
        relative = item["path"]
        if not relative.endswith(".py"):
            continue
        old = (baseline / "app" / relative).read_text() if item["before"] else ""
        new = (candidate / "app" / relative).read_text()
        diffs.extend(difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile="baseline/" + relative, tofile="candidate/" + relative))
    (evidence / "candidate-code.diff").write_text("".join(diffs))
    receipt = {"status": "STATIC_PASS_PENDING_INDEPENDENT_REVIEW", "source_commit": SOURCE_COMMIT,
               "output": str(output), "identities": identities, "delta": delta,
               "preserved_unique_modules": list(PRESERVED_MODULES),
               "checks": {"full_inventory": "PASS", "dispatcher_identity": "PASS", "apps_web_unchanged": "PASS", "non_allowlist_unchanged": "PASS", "no_deletions": "PASS", "no_python_cache": "PASS", "python_syntax": "PASS"},
               "not_run": ["HTTP", "UI", "NATURAL_RUN", "DEPLOYMENT"],
               "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    write_json(evidence / "static-receipt.json", receipt)
    print(json.dumps({"output": str(output), "status": receipt["status"], "delta_count": len(delta), "identities": identities}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
