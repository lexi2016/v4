#!/usr/bin/env python3
"""Prepare a new isolated code copy only after exact SOURCE_MAP SHA checks.

This tool never starts the application or modifies the supplied source/package.
It does not patch unknown versions, create missing source files, or deploy.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile

sys.dont_write_bytecode = True

IGNORED = frozenset({".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"})
GROUPS = frozenset({"stage", "api", "ui"})
SHA = re.compile(r"^[0-9a-f]{64}$")


def _digest(data):
    return sha256(data).hexdigest()


def _no_symlink_components(path):
    for component in reversed((path, *path.parents)):
        if component.is_symlink():
            raise ValueError(f"SYMLINK_PATH_COMPONENT:{component}")


def _root(value, *, absolute_required=True):
    path = Path(value)
    if (absolute_required and not path.is_absolute()) or ".." in path.parts:
        raise ValueError(f"ABSOLUTE_PATH_REQUIRED:{value}")
    path = path.absolute()
    _no_symlink_components(path)
    if not path.is_dir():
        raise ValueError(f"DIRECTORY_MISSING:{path}")
    return path


def _relative(value):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError(f"INVALID_RELATIVE_PATH:{value!r}")
    path = PurePosixPath(value)
    if not path.parts or path.is_absolute() or str(path) != value or any(part in {".", ".."} for part in path.parts):
        raise ValueError(f"INVALID_RELATIVE_PATH:{value!r}")
    if any(part in IGNORED for part in path.parts):
        raise ValueError(f"MAPPED_PATH_IS_IGNORED:{value}")
    return path


def _read_regular(path):
    _no_symlink_components(path)
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError(f"NOT_REGULAR_FILE:{path}")
    return path.read_bytes()


def _inside(path, root):
    # samefile also catches aliases on case-insensitive filesystems.
    for parent in (path, *path.parents):
        if parent == root or (parent.exists() and parent.samefile(root)):
            return True
    return False


def _destination(value, source, package):
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError(f"ABSOLUTE_DESTINATION_REQUIRED:{value}")
    _no_symlink_components(path)
    if os.path.lexists(path):
        raise ValueError(f"DESTINATION_ALREADY_EXISTS:{path}")
    if not path.parent.is_dir():
        raise ValueError(f"DESTINATION_PARENT_MISSING:{path.parent}")
    if _inside(path, source) or _inside(path, package):
        raise ValueError(f"DESTINATION_INSIDE_SOURCE_OR_PACKAGE:{path}")
    return path


def _inspect_tree(root):
    errors = []

    def walk_error(error):
        errors.append(str(error))

    for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        dirs[:] = [name for name in dirs if name not in IGNORED]
        for name in (*dirs, *(name for name in files if name not in IGNORED)):
            path = Path(directory) / name
            if path.is_symlink():
                errors.append(f"SOURCE_TREE_SYMLINK:{path}")
            elif not (path.is_file() or path.is_dir()):
                errors.append(f"SOURCE_TREE_SPECIAL_FILE:{path}")
    return errors


def prepare(package, group, source_root, destination=None, *, inspect_only=False):
    result = {
        "schema_version": "V4_EXACT_SHA_CANARY_PREPARATION_V1",
        "status": "PREFLIGHT_FAILED", "group": group,
        "package": str(package), "source_root": str(source_root),
        "destination": str(destination) if destination is not None else None,
        "inspect_only": bool(inspect_only), "write_performed": False,
        "files": [], "package_files": [], "errors": [],
        "source_files_changed": [], "source_verification_scope": "MAPPED_FILES",
        "ignored_names": sorted(IGNORED),
        "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    }
    try:
        if group not in GROUPS:
            raise ValueError(f"UNSUPPORTED_GROUP:{group}")
        package = _root(package, absolute_required=False)
        source_root = _root(source_root)
        result.update(package=str(package), source_root=str(source_root))
        if inspect_only and destination is not None:
            raise ValueError("INSPECT_ONLY_DOES_NOT_ACCEPT_DESTINATION")
        if not inspect_only and destination is None:
            raise ValueError("DESTINATION_REQUIRED")
        if destination is not None:
            destination = _destination(destination, source_root, package)
        source_map_path = package / "SOURCE_MAP.json"
        map_bytes = _read_regular(source_map_path)
        result["source_map_sha256"] = _digest(map_bytes)
        source_map = json.loads(map_bytes)
        entries = source_map.get("files") if isinstance(source_map, dict) else None
        if not isinstance(entries, list) or not entries:
            raise ValueError("SOURCE_MAP_FILES_REQUIRED")

        selected = []
        after_bytes = {}
        seen = set()
        for index, entry in enumerate(entries):
            try:
                if not isinstance(entry, dict) or entry.get("group") not in GROUPS:
                    raise ValueError("INVALID_GROUP_OR_ENTRY")
                entry_group = entry["group"]
                relative = _relative(entry["relative_path"])
                after_path = _relative(entry["after_path"])
                if after_path.parts[:2] != ("after", entry_group) or len(after_path.parts) < 3:
                    raise ValueError("AFTER_PATH_GROUP_MISMATCH")
                accepted = entry["accepted_before_sha256"]
                if not isinstance(accepted, list) or any(not isinstance(h, str) or not SHA.fullmatch(h) for h in accepted):
                    raise ValueError("INVALID_ACCEPTED_BEFORE_SHA256")
                if not isinstance(entry["after_sha256"], str) or not SHA.fullmatch(entry["after_sha256"]):
                    raise ValueError("INVALID_AFTER_SHA256")
                key = (entry_group, str(relative))
                if key in seen:
                    raise ValueError("DUPLICATE_GROUP_RELATIVE_PATH")
                seen.add(key)
                package_row = {"group": entry_group, "relative_path": str(relative),
                               "after_path": str(after_path), "after_sha256": entry["after_sha256"],
                               "observed_sha256": None, "status": "PACKAGE_AFTER_MISSING"}
                result["package_files"].append(package_row)
                try:
                    content = _read_regular(package / after_path)
                    package_row["observed_sha256"] = _digest(content)
                    if package_row["observed_sha256"] != entry["after_sha256"]:
                        package_row["status"] = "PACKAGE_AFTER_SHA_MISMATCH"
                    else:
                        package_row["status"] = "AFTER_SHA_MATCH"
                        after_bytes[key] = content
                except (OSError, ValueError) as error:
                    package_row["error"] = str(error)
                if entry_group == group:
                    selected.append(entry)
            except (KeyError, TypeError, ValueError) as error:
                result["errors"].append(f"SOURCE_MAP_ENTRY_INVALID:{index}:{error}")

        if not selected:
            result["errors"].append(f"SOURCE_MAP_GROUP_EMPTY:{group}")
        for entry in selected:
            row = {"relative_path": entry["relative_path"],
                   "accepted_before_sha256": entry["accepted_before_sha256"],
                   "after_sha256": entry["after_sha256"],
                   "observed_sha256": None, "status": "SOURCE_MISSING"}
            result["files"].append(row)
            try:
                observed = _digest(_read_regular(source_root / entry["relative_path"]))
                row["observed_sha256"] = observed
                row["status"] = ("ALREADY_AFTER" if observed == entry["after_sha256"] else
                                 "BEFORE_MATCH" if observed in entry["accepted_before_sha256"] else
                                 "SOURCE_SHA_MISMATCH")
            except (OSError, ValueError) as error:
                row["error"] = str(error)
        result["errors"].extend(_inspect_tree(source_root))
        if _digest(_read_regular(source_map_path)) != result["source_map_sha256"]:
            result["errors"].append("SOURCE_MAP_CHANGED_DURING_PREFLIGHT")
        if (result["errors"] or any(row["status"] != "AFTER_SHA_MATCH" for row in result["package_files"])
                or any(row["status"] not in {"BEFORE_MATCH", "ALREADY_AFTER"} for row in result["files"])):
            return result

        if inspect_only:
            result["status"] = ("ALREADY_AFTER" if all(row["status"] == "ALREADY_AFTER" for row in result["files"])
                                else "PREFLIGHT_OK")
            return result

        # Recheck mapped sources and output immediately before starting the copy.
        for row in result["files"]:
            if _digest(_read_regular(source_root / row["relative_path"])) != row["observed_sha256"]:
                result["errors"].append(f"SOURCE_CHANGED_DURING_PREFLIGHT:{row['relative_path']}")
        _destination(destination, source_root, package)
        if result["errors"]:
            return result
        result["write_performed"] = True
        result["status"] = "COPY_FAILED"
        # Preflight rejects links; preserving any link introduced by a concurrent
        # edit lets us reject it without following it outside the copied tree.
        shutil.copytree(source_root, destination, symlinks=True,
                        ignore=shutil.ignore_patterns(*IGNORED))
        result["errors"].extend(error.replace("SOURCE_TREE_", "DESTINATION_TREE_", 1)
                                for error in _inspect_tree(destination))
        if result["errors"]:
            return result
        for row in result["files"]:
            target = destination / row["relative_path"]
            _no_symlink_components(target)
            if row["status"] != "ALREADY_AFTER":
                # A fresh temp inode also works when copy2 preserved a read-only file mode.
                with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
                    temporary = Path(output.name)
                    output.write(after_bytes[(group, row["relative_path"])])
                try:
                    temporary.chmod(stat.S_IMODE(target.stat().st_mode))
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
        # Read back the whole group only after every replacement has finished.
        for row in result["files"]:
            row["destination_sha256"] = _digest(_read_regular(destination / row["relative_path"]))
            if row["destination_sha256"] != row["after_sha256"]:
                result["errors"].append(f"DESTINATION_AFTER_SHA_MISMATCH:{row['relative_path']}")
        for row in result["files"]:
            current_sha = _digest(_read_regular(source_root / row["relative_path"]))
            if current_sha != row["observed_sha256"]:
                result["source_files_changed"].append({"relative_path": row["relative_path"],
                                                       "before_sha256": row["observed_sha256"],
                                                       "observed_sha256": current_sha})
        if result["source_files_changed"]:
            result["errors"].append("SOURCE_CHANGED_DURING_COPY")
        if not result["errors"]:
            result["status"] = "CANARY_PREPARED"
    except (OSError, ValueError, TypeError, shutil.Error) as error:
        result["errors"].append(str(error))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True)
    parser.add_argument("--group", required=True, choices=sorted(GROUPS))
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--destination")
    parser.add_argument("--inspect-only", action="store_true")
    args = parser.parse_args(argv)
    result = prepare(args.package, args.group, args.source_root, args.destination,
                     inspect_only=args.inspect_only)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["status"] in {"CANARY_PREPARED", "PREFLIGHT_OK", "ALREADY_AFTER"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
