#!/usr/bin/env python3
"""Prepare a new isolated code copy only after exact SOURCE_MAP SHA checks.

This tool never starts the application or modifies the supplied source/package.
It never patches unknown versions. Missing files require an explicit add entry.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys

sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location("_prepare_canary_sources", Path(__file__).with_name("canary_sources.py"))
sources = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sources)

IGNORED = sources.IGNORED
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
    return sources.read_regular(path)


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


def _same_source(before, after):
    return all(before[key] == after[key] for key in ("entries", "links", "root_device", "root_inode"))


def _observed_source(source_root, entry):
    target = source_root / entry["relative_path"]
    _no_symlink_components(target)
    if entry.get("operation", "modify") == "add" and not os.path.lexists(target):
        return None
    return _digest(_read_regular(target))


def prepare(package, group, source_root, destination=None, *, inspect_only=False):
    result = {
        "schema_version": "V4_EXACT_SHA_CANARY_PREPARATION_V1",
        "status": "PREFLIGHT_FAILED", "group": group,
        "package": str(package), "source_root": str(source_root),
        "destination": str(destination) if destination is not None else None,
        "inspect_only": bool(inspect_only), "write_performed": False,
        "files": [], "package_files": [], "errors": [],
        "source_files_changed": [], "source_verification_scope": "MAPPED_FILES",
        "permissions_restored": None, "source_bytes_and_permissions_unchanged": None,
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
        policy = sources.load_policy(package, source_map, group, IGNORED)
        result.update(canary_source_policy_sha256=policy["sha256"],
                      copy_roots=policy["copy_roots"], optional_roots=policy["optional_roots"],
                      source_verification_scope="DECLARED_SOURCE_SET_BYTES_MODES_AND_LINK_IDENTITIES")

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
                operation = entry.get("operation", "modify")
                if operation not in {"modify", "add"}:
                    raise ValueError("INVALID_OPERATION")
                if operation == "add" and (entry.get("before_path", "missing") is not None
                                           or entry.get("before_sha256", "missing") is not None or accepted):
                    raise ValueError("ADD_REQUIRES_EXPLICIT_NULL_BEFORE_AND_EMPTY_ACCEPTED_SHA")
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
                    if not sources.in_scope(str(relative), policy, ancestor=False):
                        raise ValueError("MAPPED_FILE_OUTSIDE_DECLARED_SOURCE_SET")
                    selected.append(entry)
            except (KeyError, TypeError, ValueError) as error:
                result["errors"].append(f"SOURCE_MAP_ENTRY_INVALID:{index}:{error}")

        if not selected:
            result["errors"].append(f"SOURCE_MAP_GROUP_EMPTY:{group}")
        for entry in selected:
            row = {"relative_path": entry["relative_path"],
                   "operation": entry.get("operation", "modify"),
                   "accepted_before_sha256": entry["accepted_before_sha256"],
                   "after_sha256": entry["after_sha256"],
                   "observed_sha256": None, "status": "SOURCE_MISSING"}
            result["files"].append(row)
            try:
                observed = _observed_source(source_root, entry)
                row["observed_sha256"] = observed
                row["status"] = ("ADD_ABSENT" if observed is None else
                                 "ALREADY_AFTER" if observed == entry["after_sha256"] else
                                 "BEFORE_MATCH" if observed in entry["accepted_before_sha256"] else
                                 "SOURCE_SHA_MISMATCH")
            except (OSError, ValueError) as error:
                row["error"] = str(error)
        source_before = sources.snapshot(source_root, policy)
        prior_manifest = sources.verify_manifest(source_root, policy, result["source_map_sha256"], source_before)
        result.update(source_tree_sha256=sources.tree_id(source_before["entries"]),
                      source_links=source_before["links"], excluded_roots=source_before["excluded_roots"])
        if _digest(_read_regular(source_map_path)) != result["source_map_sha256"]:
            result["errors"].append("SOURCE_MAP_CHANGED_DURING_PREFLIGHT")
        if (result["errors"] or any(row["status"] != "AFTER_SHA_MATCH" for row in result["package_files"])
                or any(row["status"] not in {"BEFORE_MATCH", "ALREADY_AFTER", "ADD_ABSENT"} for row in result["files"])):
            return result

        if inspect_only:
            result["status"] = ("ALREADY_AFTER" if all(row["status"] == "ALREADY_AFTER" for row in result["files"])
                                else "PREFLIGHT_OK")
            return result

        # Recheck the selected source set, including modes and exact link identities.
        if not _same_source(source_before, sources.snapshot(source_root, policy)):
            result["errors"].append("SOURCE_CHANGED_DURING_PREFLIGHT")
        guarded = {source_map_path: result["source_map_sha256"],
                   **{package / row["after_path"]: row["after_sha256"] for row in result["package_files"]}}
        if policy["sha256"] is not None:
            guarded[package / sources.POLICY] = policy["sha256"]
        if not all(_digest(_read_regular(path)) == expected for path, expected in guarded.items()):
            result["errors"].append("PACKAGE_CHANGED_DURING_PREFLIGHT")
        _destination(destination, source_root, package)
        if result["errors"]:
            return result
        result["write_performed"] = True
        result["status"] = "COPY_FAILED"
        sources.copy_tree(source_root, destination, policy)
        expected_entries = sources.copy_entries(source_before)
        copied = sources.snapshot(destination, policy, candidate=True)
        if copied["entries"] != expected_entries:
            raise ValueError("DESTINATION_BYTES_OR_MODES_CHANGED_DURING_COPY")
        if not _same_source(source_before, sources.snapshot(source_root, policy)):
            raise ValueError("SOURCE_CHANGED_DURING_COPY")
        for row in result["files"]:
            target = destination / row["relative_path"]
            _no_symlink_components(target)
            if row["status"] != "ALREADY_AFTER":
                mode = expected_entries.get(row["relative_path"], {}).get("mode", 0o644)
                sources.write_candidate(destination, row["relative_path"], after_bytes[(group, row["relative_path"])],
                                        expected_sha256=row["observed_sha256"], mode=mode)
                expected_entries[row["relative_path"]] = {"type": "file", "mode": mode, "sha256": row["after_sha256"]}
                for parent in target.parent.parents:
                    if parent == destination or destination in parent.parents:
                        expected_entries.setdefault(parent.relative_to(destination).as_posix(), {"type": "directory", "mode": 0o755})
                expected_entries.setdefault(target.parent.relative_to(destination).as_posix(), {"type": "directory", "mode": 0o755})
        # Read back the whole group only after every replacement has finished.
        for row in result["files"]:
            row["destination_sha256"] = _digest(_read_regular(destination / row["relative_path"]))
            if row["destination_sha256"] != row["after_sha256"]:
                result["errors"].append(f"DESTINATION_AFTER_SHA_MISMATCH:{row['relative_path']}")
        source_after = sources.snapshot(source_root, policy)
        result["source_bytes_and_permissions_unchanged"] = _same_source(source_before, source_after)
        if not result["source_bytes_and_permissions_unchanged"]:
            result["source_files_changed"] = [name for name in set(source_before["entries"]) | set(source_after["entries"])
                                              if source_before["entries"].get(name) != source_after["entries"].get(name)]
            result["errors"].append("SOURCE_CHANGED_DURING_COPY")
        destination_after = sources.snapshot(destination, policy, candidate=True)
        result["permissions_restored"] = (destination_after["entries"] == expected_entries)
        if not result["permissions_restored"]:
            result["errors"].append("DESTINATION_BYTES_OR_MODES_MISMATCH")
        if not all(_digest(_read_regular(path)) == expected for path, expected in guarded.items()):
            result["errors"].append("PACKAGE_CHANGED_DURING_COPY")
        if not result["errors"]:
            manifest = {"schema_version": "V4_CANARY_SOURCE_MANIFEST_V1", "source_root": str(source_root),
                        "destination": str(destination), "source_map_sha256": result["source_map_sha256"],
                        "canary_source_policy_sha256": policy["sha256"],
                        "source_tree_sha256": result["source_tree_sha256"],
                        "candidate_tree_sha256": sources.tree_id(destination_after["entries"]),
                        "copy_roots": policy["copy_roots"], "optional_roots": policy["optional_roots"],
                        "excluded_roots": source_before["excluded_roots"], "source_links": source_before["links"],
                        "quarantined_links": [row for row in source_before["links"] if row["action"] == "quarantine"],
                        "source_verification_scope": result["source_verification_scope"],
                        "source_bytes_and_permissions_unchanged": True, "permissions_restored": True,
                        "runtime_dependency_status": "CANNOT_CONFIRM_UNTIL_RUNTIME_CONFIG_AND_DYNAMIC_DEPENDENCIES_CHECKED",
                        "prior_source_manifest_sha256": prior_manifest["sha256"] if prior_manifest else None}
            raw = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
            sources.write_candidate(destination, sources.MANIFEST, raw, expected_sha256=None, mode=0o600)
            if sources.snapshot(destination, policy, candidate=True)["entries"] != expected_entries:
                raise ValueError("DESTINATION_CHANGED_DURING_MANIFEST_WRITE")
            result.update(candidate_source_manifest=str(destination / sources.MANIFEST),
                          candidate_source_manifest_sha256=_digest(_read_regular(destination / sources.MANIFEST)))
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
