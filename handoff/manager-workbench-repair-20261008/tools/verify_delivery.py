#!/usr/bin/env python3
"""Read-only, stdlib-only delivery/source verifier; Python 3.10+ on POSIX.

Examples (use exact absolute source roots):
  python3 tools/verify_delivery.py --source-root /exact/api/app --profile api
  python3 tools/verify_delivery.py --source-root /exact/new/app --profile api --against after
  python3 tools/verify_delivery.py --source-root /exact/scheduler/app --profile scheduler_prerequisite

Every invocation hashes ALL manifest after-files, then checks the selected
source profile and its optional preserve pins. Before-null means absent.
Payloads live under after/; scheduler_prerequisite alone may also use the
separate prerequisites/scheduler/ directory for unchanged required bytes.
No source, service, binding or network operation is performed. --report may
only create one new file outside source-root; its parent must already exist.
Exit 0 means every requested check passed; any mismatch or report error is 1.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any, Iterator


MANIFEST_SCHEMA = "v4.manager_workbench_repair.delivery.v1"
RESULT_SCHEMA = "v4.manager_workbench_repair.delivery_verification.v1"
PROFILES = ("api", "web", "tests", "scheduler_prerequisite")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_RECORDS = 4096


class VerificationError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


def _absolute(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.anchor != "/" or ".." in path.parts:
        raise VerificationError("ABSOLUTE_PATH_REQUIRED")
    return path


def _relative(value: Any, *, after: bool = False, prerequisite: bool = False) -> str:
    prefixes = ("after/", "prerequisites/scheduler/") if prerequisite else ("after/",)
    if (not isinstance(value, str) or not value or len(value) > 1024
            or "\\" in value or "\x00" in value or value.startswith("/")
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or PurePosixPath(value).as_posix() != value
            or (after and not value.startswith(prefixes))):
        raise ValueError("unsafe or noncanonical relative path")
    return value


def _directory(parent: int, name: str) -> int:
    info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if stat.S_ISLNK(info.st_mode):
        raise VerificationError("SYMLINK_NOT_ALLOWED")
    if not stat.S_ISDIR(info.st_mode):
        raise VerificationError("DIRECTORY_REQUIRED")
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)


@contextmanager
def _root(value: str | Path) -> Iterator[int]:
    path = _absolute(value)
    if not all(hasattr(os, flag) for flag in ("O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")):
        raise VerificationError("POSIX_NOFOLLOW_SUPPORT_REQUIRED")
    current = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in path.parts[1:]:
            child = _directory(current, component)
            os.close(current)
            current = child
        yield current
    finally:
        os.close(current)


@contextmanager
def _parent(root: int, relative: str) -> Iterator[tuple[int, str]]:
    parts = PurePosixPath(relative).parts
    current = os.dup(root)
    try:
        for component in parts[:-1]:
            child = _directory(current, component)
            os.close(current)
            current = child
        yield current, parts[-1]
    finally:
        os.close(current)


@contextmanager
def _regular_file(root: int, relative: str) -> Iterator[Any]:
    with _parent(root, relative) as (parent, name):
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode):
            raise VerificationError("SYMLINK_NOT_ALLOWED")
        if not stat.S_ISREG(info.st_mode):
            raise VerificationError("REGULAR_FILE_REQUIRED")
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise VerificationError("REGULAR_FILE_REQUIRED")
        yield stream


def _identity(root: int, relative: str) -> tuple[str, int]:
    with _regular_file(root, relative) as stream:
        before = os.fstat(stream.fileno())
        digest, size = hashlib.sha256(), 0
        while block := stream.read(1024 * 1024):
            digest.update(block)
            size += len(block)
        after = os.fstat(stream.fileno())
        if (before.st_size != size or after.st_size != size
                or before.st_mtime_ns != after.st_mtime_ns
                or before.st_ctime_ns != after.st_ctime_ns):
            raise VerificationError("FILE_CHANGED_DURING_READ")
        return digest.hexdigest(), size


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _manifest(root: int) -> tuple[dict[str, Any], str]:
    with _regular_file(root, "source_manifest.json") as stream:
        raw = stream.read(MAX_MANIFEST_BYTES + 1)
    try:
        if len(raw) > MAX_MANIFEST_BYTES:
            raise ValueError("manifest exceeds byte bound")
        value = json.loads(raw, object_pairs_hook=_unique_object)
        if (not isinstance(value, dict) or value.get("schema_version") != MANIFEST_SCHEMA
                or re.fullmatch(r"[0-9a-f]{40}", str(value.get("base_commit", ""))) is None):
            raise ValueError("manifest schema or base commit is invalid")
        files, preserve = value.get("files"), value.get("preserve", [])
        if (not isinstance(files, list) or not 1 <= len(files) <= MAX_RECORDS
                or not isinstance(preserve, list) or len(preserve) > MAX_RECORDS):
            raise ValueError("manifest record collection is invalid")
        used, after_paths = set(), set()
        for collection, is_preserve in ((files, False), (preserve, True)):
            for row in collection:
                if not isinstance(row, dict) or row.get("profile") not in PROFILES:
                    raise ValueError("manifest profile is invalid")
                path = _relative(row.get("path"))
                key = (row["profile"], path)
                if key in used:
                    raise ValueError("duplicate or conflicting profile/path")
                used.add(key)
                if is_preserve:
                    if not isinstance(row.get("sha256"), str) or SHA256.fullmatch(row["sha256"]) is None:
                        raise ValueError("preserve SHA is invalid")
                    continue
                after_path = _relative(row.get("after_path"), after=True,
                                       prerequisite=row["profile"] == "scheduler_prerequisite")
                if after_path in after_paths:
                    raise ValueError("duplicate after path")
                after_paths.add(after_path)
                if ("before_sha256" not in row
                        or (row["before_sha256"] is not None and (
                            not isinstance(row["before_sha256"], str)
                            or SHA256.fullmatch(row["before_sha256"]) is None))
                        or not isinstance(row.get("after_sha256"), str)
                        or SHA256.fullmatch(row["after_sha256"]) is None
                        or type(row.get("after_bytes")) is not int or row["after_bytes"] < 0):
                    raise ValueError("file identity is invalid")
        return value, hashlib.sha256(raw).hexdigest()
    except (ValueError, UnicodeDecodeError) as exc:
        raise VerificationError("MANIFEST_INVALID", str(exc)) from exc


def _failure(result: dict[str, Any], scope: str, path: str, code: str, **details: Any) -> None:
    result["status"] = "FAIL"
    result["failures"].append({"scope": scope, "path": path, "code": code, **details})


def _error(result: dict[str, Any], scope: str, path: str, exc: Exception) -> None:
    code = (exc.code if isinstance(exc, VerificationError) else
            "FILE_MISSING" if isinstance(exc, FileNotFoundError) else
            "SYMLINK_NOT_ALLOWED" if isinstance(exc, OSError) and exc.errno == errno.ELOOP else
            "IO_ERROR")
    _failure(result, scope, path, code, detail=str(exc))


def verify(package_root: str | Path, source_root: str | Path, *,
           profile: str = "all", against: str = "before") -> dict[str, Any]:
    """Return a structured result without creating or modifying any file."""
    result: dict[str, Any] = {
        "schema_version": RESULT_SCHEMA, "status": "PASS", "profile": profile,
        "against": against, "package_root": str(package_root), "source_root": str(source_root),
        "base_commit": None, "manifest_sha256": None, "package_files_checked": 0,
        "source_files_checked": 0, "preserve_files_checked": 0, "failures": [],
    }
    if profile not in (*PROFILES, "all") or against not in {"before", "after"}:
        _failure(result, "arguments", "", "INVALID_SELECTION")
        return result
    try:
        with _root(package_root) as package:
            manifest, manifest_sha = _manifest(package)
            result.update(base_commit=manifest["base_commit"], manifest_sha256=manifest_sha)
            for row in manifest["files"]:
                result["package_files_checked"] += 1
                try:
                    actual_sha, size = _identity(package, row["after_path"])
                    if actual_sha != row["after_sha256"]:
                        _failure(result, "package", row["after_path"], "PACKAGE_SHA_MISMATCH",
                                 expected=row["after_sha256"], actual=actual_sha)
                    if size != row["after_bytes"]:
                        _failure(result, "package", row["after_path"], "PACKAGE_SIZE_MISMATCH",
                                 expected=row["after_bytes"], actual=size)
                except (OSError, VerificationError) as exc:
                    _error(result, "package", row["after_path"], exc)
    except (OSError, VerificationError) as exc:
        _error(result, "package", "source_manifest.json", exc)
        return result
    files = [row for row in manifest["files"] if profile in {"all", row["profile"]}]
    preserve = [row for row in manifest.get("preserve", []) if profile in {"all", row["profile"]}]
    if not files and not preserve:
        _failure(result, "manifest", "", "PROFILE_HAS_NO_RECORDS")
        return result
    try:
        with _root(source_root) as source:
            for collection, is_preserve in ((files, False), (preserve, True)):
                for row in collection:
                    scope = "preserve" if is_preserve else "source"
                    result[scope + "_files_checked"] += 1
                    expected = row["sha256"] if is_preserve else row[against + "_sha256"]
                    try:
                        if expected is None:
                            try:
                                with _parent(source, row["path"]) as (parent, name):
                                    info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                                    if stat.S_ISLNK(info.st_mode):
                                        raise VerificationError("SYMLINK_NOT_ALLOWED")
                            except FileNotFoundError:
                                continue
                            _failure(result, scope, row["path"], "SOURCE_EXPECTED_ABSENT")
                        else:
                            actual_sha, _ = _identity(source, row["path"])
                            if actual_sha != expected:
                                _failure(result, scope, row["path"], scope.upper() + "_SHA_MISMATCH",
                                         expected=expected, actual=actual_sha)
                    except (OSError, VerificationError) as exc:
                        _error(result, scope, row["path"], exc)
    except (OSError, VerificationError) as exc:
        _error(result, "source", str(source_root), exc)
    return result


def _assert_report_outside_source(source: int, report_parent: int) -> None:
    """Compare opened directory identities, including case-insensitive aliases."""
    source_info = os.fstat(source)
    source_identity = (source_info.st_dev, source_info.st_ino)
    current = os.dup(report_parent)
    try:
        for _ in range(4096):
            info = os.fstat(current)
            identity = (info.st_dev, info.st_ino)
            if identity == source_identity:
                raise VerificationError("REPORT_INSIDE_SOURCE_ROOT")
            ancestor = os.open("..", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            os.close(current)
            current = ancestor
            parent_info = os.fstat(current)
            if identity == (parent_info.st_dev, parent_info.st_ino):
                return  # The actual filesystem root was reached.
        raise VerificationError("REPORT_ANCESTRY_BOUND_EXCEEDED")
    finally:
        os.close(current)


def _write_report(path: str, source_root: str, raw: bytes) -> None:
    destination, source = _absolute(path), _absolute(source_root)
    # A failed source SHA check may still produce an outside report, but an
    # invalid/symlinked source root must never authorize any report write.
    with _root(source) as source_directory, _root(destination.parent) as parent:
        _assert_report_outside_source(source_directory, parent)
        fd = os.open(destination.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--package-root", default=str(Path(__file__).absolute().parent.parent))
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--profile", choices=(*PROFILES, "all"), default="all")
    parser.add_argument("--against", choices=("before", "after"), default="before")
    parser.add_argument("--report", help="absolute new report filename outside source-root")
    args = parser.parse_args(argv)
    result = verify(args.package_root, args.source_root, profile=args.profile, against=args.against)
    if args.report:
        try:
            _write_report(args.report, args.source_root,
                          (json.dumps(result, sort_keys=True, indent=2) + "\n").encode("utf-8"))
        except (OSError, VerificationError) as exc:
            code = (exc.code if isinstance(exc, VerificationError)
                    and exc.code == "REPORT_INSIDE_SOURCE_ROOT" else "REPORT_WRITE_FAILED")
            _failure(result, "report", args.report, code, detail=str(exc))
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
