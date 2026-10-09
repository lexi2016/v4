#!/usr/bin/env python3
"""Apply only exact V4 source preimages, exclusively to a new isolated copy."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

PACKAGE = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def safe_file(root, relative):
    path = root / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("unsafe manifest path")
    for check in (path, *path.parents):
        if check == root:
            break
        if check.is_symlink():
            raise ValueError(f"refusing source symlink: {relative}")
    return path


def inspect(root, role, *, final=False):
    rows = []
    for item in role["files"]:
        try:
            actual = digest(safe_file(root, item["relative_path"]))
            accepted = [item["after_sha256"]] if final else [
                *item["accepted_before_sha256"], item["after_sha256"]]
            okay = actual in accepted
            row = {"relative_path": item["relative_path"], "actual_sha256": actual,
                   "expected_sha256": accepted, "status": "MATCH" if okay else "MISMATCH"}
        except (OSError, ValueError) as error:
            row = {"relative_path": item["relative_path"], "status": "MISMATCH", "error": str(error)}
        rows.append(row)
    return {"root": str(root), "status": "MATCH" if all(r["status"] == "MATCH" for r in rows) else "MISMATCH",
            "files": rows}


def prepare(source, target, role):
    if source == target or source in target.parents or target in source.parents:
        raise ValueError("the new candidate must be separate from its source")
    if target.exists() or target.is_symlink():
        raise ValueError("candidate path must not exist; no in-place application")
    report = inspect(source, role)
    if report["status"] != "MATCH":
        return report
    # All file preimages and all supplied after bytes are checked before copy.
    for item in role["files"]:
        if digest(PACKAGE / item["after_path"]) != item["after_sha256"]:
            raise ValueError(f"package after SHA mismatch: {item['relative_path']}")
    shutil.copytree(source, target, symlinks=True, ignore=shutil.ignore_patterns(
        ".git", "__pycache__", "*.pyc", ".venv", "venv", "node_modules", ".pytest_cache"))
    for item in role["files"]:
        path = safe_file(target, item["relative_path"])
        # A source changed while being copied must never be silently accepted.
        actual = digest(path)
        if actual not in [*item["accepted_before_sha256"], item["after_sha256"]]:
            raise ValueError(f"source changed during copy: {item['relative_path']}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((PACKAGE / item["after_path"]).read_bytes())
    result = inspect(target, role, final=True)
    result.update(source_root=str(source), mode="ISOLATED_CODE_CANDIDATE", active_runtime_updated=False,
                  RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
    (target / "V4_CANARY_IDENTITY.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "prepare", "verify"))
    parser.add_argument("--role", required=True, choices=("actual_stage", "canonical_stage", "actual_api"))
    parser.add_argument("--root", required=True, type=Path, help="complete existing application root")
    parser.add_argument("--candidate", type=Path, help="new isolated application path; prepare only")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    manifest = json.loads((PACKAGE / "SOURCE_MAP.json").read_text())
    role = manifest["roles"][args.role]
    try:
        root = args.root.expanduser().resolve(strict=True)
        if args.action == "prepare":
            if args.candidate is None:
                parser.error("prepare requires --candidate")
            result = prepare(root, args.candidate.expanduser().absolute(), role)
        else:
            result = inspect(root, role, final=args.action == "verify")
    except (OSError, ValueError) as error:
        result = {"status": "ERROR", "error": str(error), "active_runtime_updated": False}
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text)
    print(text, end="")
    return 0 if result["status"] == "MATCH" else 2


if __name__ == "__main__":
    raise SystemExit(main())
