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
MARKER = "V4_CANARY_IDENTITY.json"
FLAGS = {"RESEARCH_ONLY": True, "production_allowed": False,
         "buy_gate_updated": False, "orders_sent": False}


def digest(path):
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError(f"expected a regular file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_file(root, relative):
    if not isinstance(relative, str) or not relative or relative == ".":
        raise ValueError("unsafe manifest path")
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("unsafe manifest path")
    path = root / relative_path
    for check in (path, *path.parents):
        if check == root:
            break
        if check.is_symlink():
            raise ValueError(f"refusing source symlink: {relative}")
    return path


def require_separate(first, second):
    """Resolve existing ancestors too, so a parent symlink cannot hide overlap."""
    first, second = Path(first).resolve(), Path(second).resolve()
    if first == second or first in second.parents or second in first.parents:
        raise ValueError(f"paths must remain separate: {first} ; {second}")


def read_source_map():
    content = (PACKAGE / "SOURCE_MAP.json").read_bytes()
    manifest = json.loads(content)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("roles"), dict):
        raise ValueError("invalid SOURCE_MAP roles")
    return manifest, hashlib.sha256(content).hexdigest()


def new_report_path(path, *, forbidden_roots=()):
    path = Path(path).expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise ValueError("report must be a new file; refusing to overwrite existing evidence")
    path = path.resolve()
    for root in forbidden_roots:
        root = Path(root).resolve()
        if path == root or root in path.parents:
            raise ValueError("report must remain separate from application and input roots")
    return path


def write_new_report(path, text, *, forbidden_roots=()):
    path = new_report_path(path, forbidden_roots=forbidden_roots)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(text)
    except FileExistsError as error:
        raise ValueError("report must be a new file") from error


def role_files(role):
    files = role.get("files") if isinstance(role, dict) else None
    if not isinstance(files, list) or not files:
        raise ValueError("SOURCE_MAP role must contain files")
    seen = set()
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("invalid SOURCE_MAP file entry")
        relative = item.get("relative_path")
        safe_file(PACKAGE, relative)
        if relative == MARKER or str(Path(relative)) in seen:
            raise ValueError("duplicate or reserved SOURCE_MAP path")
        seen.add(str(Path(relative)))
        safe_file(PACKAGE, item.get("after_path"))
        before, after = item.get("accepted_before_sha256"), item.get("after_sha256")
        if not isinstance(before, list) or not before:
            raise ValueError("missing accepted preimage SHAs")
        # None is accepted only as a preimage for a newly added file.
        for value in (*[value for value in before if value is not None], after):
            if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ValueError("invalid source SHA256")
    return files


def inspect(root, role, *, final=False):
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("application root must be a directory")
    rows = []
    for item in role_files(role):
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


def prepare(source, target, role, *, role_id=None):
    source = Path(source).expanduser().resolve(strict=True)
    target = Path(target).expanduser().absolute()
    require_separate(source, target)
    if target.exists() or target.is_symlink():
        raise ValueError("candidate path must not exist; no in-place application")
    target = target.resolve()
    manifest, manifest_sha = read_source_map()
    if role_id is None:
        matches = [name for name, value in manifest["roles"].items() if value == role]
        if len(matches) != 1:
            raise ValueError("an unambiguous SOURCE_MAP role is required")
        role_id = matches[0]
    if manifest["roles"].get(role_id) != role:
        raise ValueError("role differs from packaged SOURCE_MAP")
    # The copied marker must never redirect a write to original/external data.
    safe_file(source, MARKER)
    report = inspect(source, role)
    if report["status"] != "MATCH":
        return report
    # All file preimages and all supplied after bytes are checked before copy.
    after_bytes = {}
    for item in role["files"]:
        content = safe_file(PACKAGE, item["after_path"]).read_bytes()
        if hashlib.sha256(content).hexdigest() != item["after_sha256"]:
            raise ValueError(f"package after SHA mismatch: {item['relative_path']}")
        after_bytes[item["relative_path"]] = content
    shutil.copytree(source, target, symlinks=True, ignore=shutil.ignore_patterns(
        ".git", "__pycache__", "*.pyc", ".venv", "venv", "node_modules", ".pytest_cache"))
    # Check the entire copied set before writing even the first after file.
    safe_file(target, MARKER)
    copied = inspect(target, role)
    if copied["status"] != "MATCH":
        mismatches = [row["relative_path"] for row in copied["files"] if row["status"] != "MATCH"]
        raise ValueError(f"source changed during copy: {', '.join(mismatches)}")
    for item in role["files"]:
        path = safe_file(target, item["relative_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(after_bytes[item["relative_path"]])
    result = inspect(target, role, final=True)
    if result["status"] != "MATCH":
        raise ValueError("candidate after SHA mismatch; no candidate identity issued")
    result.update(source_root=str(source), role=role_id, source_map_sha256=manifest_sha,
                  mode="ISOLATED_CODE_CANDIDATE", active_runtime_updated=False, **FLAGS)
    safe_file(target, MARKER).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def verify_candidate(candidate, *, allowed_roles=("actual_stage", "canonical_stage")):
    candidate = Path(candidate).expanduser().resolve(strict=True)
    marker = json.loads(safe_file(candidate, MARKER).read_text(encoding="utf-8"))
    if not isinstance(marker, dict) or marker.get("role") not in allowed_roles:
        raise ValueError("candidate identity must name an accepted Stage application role")
    manifest, manifest_sha = read_source_map()
    if (marker.get("source_map_sha256") != manifest_sha or marker.get("root") != str(candidate)
            or marker.get("status") != "MATCH" or marker.get("mode") != "ISOLATED_CODE_CANDIDATE"
            or marker.get("active_runtime_updated") is not False
            or any(marker.get(key) is not value for key, value in FLAGS.items())):
        raise ValueError("candidate identity or package SHA differs; prepare a fresh isolated candidate")
    source_root = marker.get("source_root")
    if not isinstance(source_root, str) or not Path(source_root).is_absolute():
        raise ValueError("candidate identity lacks its original application root")
    require_separate(candidate, source_root)
    role = manifest["roles"].get(marker["role"])
    if inspect(candidate, role, final=True)["status"] != "MATCH":
        raise ValueError("candidate after SHA mismatch; do not run modified source")
    return marker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "prepare", "verify"))
    parser.add_argument("--role", required=True, choices=("actual_stage", "canonical_stage", "actual_api"))
    parser.add_argument("--root", required=True, type=Path, help="complete existing application root")
    parser.add_argument("--candidate", type=Path, help="new isolated application path; prepare only")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report_path = None
    try:
        manifest, _ = read_source_map()
        role = manifest["roles"][args.role]
        root = args.root.expanduser().resolve(strict=True)
        report_path = new_report_path(args.report, forbidden_roots=(root,)) if args.report else None
        if args.action == "prepare":
            if args.candidate is None:
                parser.error("prepare requires --candidate")
            result = prepare(root, args.candidate, role, role_id=args.role)
        else:
            result = inspect(root, role, final=args.action == "verify")
    except (OSError, ValueError, KeyError, TypeError) as error:
        result = {"status": "ERROR", "error": str(error), "active_runtime_updated": False}
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if report_path:
        try:
            write_new_report(report_path, text, forbidden_roots=(root,))
        except (OSError, ValueError) as error:
            print(json.dumps({"status": "ERROR", "error": str(error)}), file=sys.stderr)
            return 2
    print(text, end="")
    return 0 if result["status"] == "MATCH" else 2


if __name__ == "__main__":
    raise SystemExit(main())
