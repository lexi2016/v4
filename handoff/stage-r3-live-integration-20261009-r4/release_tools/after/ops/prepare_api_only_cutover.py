#!/usr/bin/env python3
"""Prepare (but never activate) an api-only LaunchAgent cutover.

This module deliberately has a narrow write surface.  It reads the existing
api-only plist, renders a candidate plist below a candidate release directory,
and writes a rollback plan.  It does not call ``launchctl`` and it refuses
paths in the source checkout or the formal release directory.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
import plistlib
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

try:
    from .api_release_integration import verify_api_release_candidate
except ImportError:
    try:
        from api_release_integration import verify_api_release_candidate
    except ImportError:
        _integration_path = Path(__file__).with_name("api_release_integration.py")
        _integration_spec = importlib.util.spec_from_file_location(
            "_v4_api_release_integration", _integration_path
        )
        if _integration_spec is None or _integration_spec.loader is None:
            raise ImportError("cannot load adjacent API release integration guard")
        _integration_module = importlib.util.module_from_spec(_integration_spec)
        sys.modules[_integration_spec.name] = _integration_module
        _integration_spec.loader.exec_module(_integration_module)
        verify_api_release_candidate = _integration_module.verify_api_release_candidate


SCHEMA_VERSION = "v4.api_only_cutover_plan.v1"
DEFAULT_FORMAL_RELEASE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases"
)
DEFAULT_MANAGER_STATE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/manager_auto_research"
)
SENSITIVE_KEY_RE = re.compile(
    r"(?:TOKEN|KEY|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|PROXY)", re.IGNORECASE
)
REWRITE_KEYS = {
    "V35_APP_ROOT",
    "V35_RELEASE_ID",
    "PYTHONPATH",
    "V35_RELEASE_MANIFEST_PATH",
    "V35_RELEASE_MANIFEST_SHA256",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _unaliased(path: Path, *, kind: str | None = None) -> Path:
    """Do not erase a supplied symlink before validating a write boundary."""
    result = Path(os.path.abspath(Path(path).expanduser()))
    if result.is_symlink() or result.resolve(strict=False) != result:
        raise ValueError("API_PREPARE_PATH_SYMLINK_OR_ALIAS")
    if kind == "file" and not result.is_file():
        raise FileNotFoundError(result)
    if kind == "directory" and not result.is_dir():
        raise FileNotFoundError(result)
    return result


def _identity(path: Path) -> tuple[int, int]:
    info = path.lstat()
    return info.st_dev, info.st_ino


def _read_exact_file(path: Path) -> tuple[bytes, tuple[int, int]]:
    path = _unaliased(path, kind="file")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("API_PREPARE_NOT_REGULAR_FILE")
        with os.fdopen(os.dup(fd), "rb") as handle:
            raw = handle.read()
        after = os.fstat(fd)
        token = before.st_dev, before.st_ino
        if (token != _identity(path) or
                (before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError("API_PREPARE_FILE_CHANGED_DURING_READ")
        return raw, token
    finally:
        os.close(fd)


@contextmanager
def _candidate_directory(root: Path, directory: Path):
    """Create/open only descendant directories, never following links."""
    root = _unaliased(root, kind="directory")
    directory = _unaliased(directory)
    try:
        parts = directory.relative_to(root).parts
    except ValueError as exc:
        raise ValueError("API_PREPARE_DIRECTORY_OUTSIDE_CANDIDATE") from exc
    fds: list[int] = []
    identities: list[tuple[Path, tuple[int, int]]] = []
    current = root
    try:
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        fds.append(fd)
        info = os.fstat(fd)
        identities.append((root, (info.st_dev, info.st_ino)))
        for part in parts:
            try:
                os.mkdir(part, mode=0o700, dir_fd=fd)
            except FileExistsError:
                pass
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            fds.append(fd)
            current = current / part
            info = os.fstat(fd)
            identities.append((current, (info.st_dev, info.st_ino)))
        def assert_current() -> None:
            for path, token in identities:
                if _unaliased(path, kind="directory") != path or _identity(path) != token:
                    raise ValueError("API_PREPARE_DIRECTORY_CHANGED")
        assert_current()
        yield fd, assert_current
        assert_current()
    except OSError as exc:
        raise ValueError("API_PREPARE_DIRECTORY_UNSAFE") from exc
    finally:
        for fd in reversed(fds):
            os.close(fd)


def _write_exclusive_at(directory_fd: int, name: str, raw: bytes) -> None:
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600, dir_fd=directory_fd)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.fsync(directory_fd)


def _is_within(path: Path, root: Path) -> bool:
    try:
        _resolved(path).relative_to(_resolved(root))
    except ValueError:
        return False
    return True


def assert_safe_candidate_path(
    candidate_root: Path,
    *,
    source_root: Path | None = None,
    formal_release_root: Path = DEFAULT_FORMAL_RELEASE_ROOT,
) -> None:
    """Reject a candidate path that could overwrite an app or formal release."""

    candidate = _unaliased(candidate_root)
    if source_root is not None and (
        _is_within(candidate, source_root) or _is_within(source_root, candidate)
    ):
        raise ValueError("candidate root must be separate from the source checkout")
    if _is_within(candidate, formal_release_root):
        raise ValueError("candidate root must not be inside the formal release root")


def _parse_assignment(value: object) -> tuple[str, str] | None:
    if not isinstance(value, str) or "=" not in value:
        return None
    key, item = value.split("=", 1)
    if not key or any(char.isspace() for char in key):
        return None
    return key, item


def extract_environment(plist: Mapping[str, Any]) -> dict[str, str]:
    """Collect env assignments from both plist forms without importing them."""

    values: dict[str, str] = {}
    arguments = plist.get("ProgramArguments", [])
    if isinstance(arguments, list):
        for item in arguments:
            parsed = _parse_assignment(item)
            if parsed is not None:
                values[parsed[0]] = parsed[1]
    environment = plist.get("EnvironmentVariables", {})
    if isinstance(environment, Mapping):
        for key, value in environment.items():
            if isinstance(key, str) and isinstance(value, (str, int, float, bool)):
                values[key] = str(value)
    return values


def _replace_assignments(arguments: Sequence[Any], replacements: Mapping[str, str]) -> list[Any]:
    if not arguments or _parse_assignment(arguments[0]) is not None:
        raise ValueError("api-only ProgramArguments must start with an executable")
    result: list[Any] = []
    seen: set[str] = set()
    for item in arguments:
        parsed = _parse_assignment(item)
        if parsed is None or parsed[0] not in replacements:
            result.append(item)
            continue
        key = parsed[0]
        result.append(f"{key}={replacements[key]}")
        seen.add(key)
    # The five release identity values are part of the existing plist
    # contract.  A manager state override is intentionally additive: the
    # current api-only plist has no such variable.  For the current
    # ``/usr/bin/env`` wrapper contract, insert it after argv0 and the
    # existing assignments, immediately before the wrapped executable.  An
    # assignment before argv0 would make launchd try to execute the variable
    # string itself.
    missing = set(REWRITE_KEYS) - seen
    if missing:
        raise ValueError(
            "api-only plist is missing required ProgramArguments keys: "
            + ", ".join(sorted(missing))
        )
    additional = [
        f"{key}={replacements[key]}"
        for key in sorted(set(replacements) - seen)
    ]
    if additional:
        first_assignment_after_argv0 = next(
            (
                index
                for index in range(1, len(result))
                if _parse_assignment(result[index]) is None
            ),
            len(result),
        )
        result[first_assignment_after_argv0:first_assignment_after_argv0] = additional
    return result


def rewrite_api_only_plist(
    plist: MutableMapping[str, Any],
    *,
    candidate_app_root: Path,
    release_id: str,
    manifest_path: Path,
    manifest_sha256: str,
    candidate_manager_state_root: Path | None = None,
) -> MutableMapping[str, Any]:
    """Return a staged plist preserving runtime roots and safety flags."""

    app_root = _resolved(candidate_app_root)
    manifest = _resolved(manifest_path)
    replacements = {
        "V35_APP_ROOT": str(app_root),
        "V35_RELEASE_ID": release_id,
        "PYTHONPATH": f"{app_root / 'upstreams'}:{app_root}",
        "V35_RELEASE_MANIFEST_PATH": str(manifest),
        "V35_RELEASE_MANIFEST_SHA256": manifest_sha256,
    }
    if candidate_manager_state_root is not None:
        replacements["V4_MANAGER_RESEARCH_STATE_ROOT"] = str(
            _resolved(candidate_manager_state_root)
        )
    staged: MutableMapping[str, Any] = dict(plist)
    arguments = plist.get("ProgramArguments")
    if not isinstance(arguments, list):
        raise ValueError("api-only plist must contain ProgramArguments")
    staged["ProgramArguments"] = _replace_assignments(arguments, replacements)

    environment = plist.get("EnvironmentVariables")
    if isinstance(environment, Mapping):
        updated_environment = dict(environment)
        # A variable may be represented in ProgramArguments, as in the
        # current api-only plist.  Only rewrite EnvironmentVariables keys that
        # are present; never invent a second environment producer.
        for key in replacements:
            if key in updated_environment:
                updated_environment[key] = replacements[key]
        if candidate_manager_state_root is not None:
            updated_environment.setdefault(
                "V4_MANAGER_RESEARCH_STATE_ROOT",
                replacements["V4_MANAGER_RESEARCH_STATE_ROOT"],
            )
        staged["EnvironmentVariables"] = updated_environment

    if "WorkingDirectory" not in plist:
        raise ValueError("api-only plist must contain WorkingDirectory")
    staged["WorkingDirectory"] = str(app_root)
    return staged


def _safe_json_value(key: str, value: str) -> str:
    if SENSITIVE_KEY_RE.search(key):
        return "<redacted>"
    return value


def _path_probe(value: str) -> dict[str, object] | None:
    """Describe a path-like env value without reading directory contents."""

    candidate = value
    if ":" in value and not value.startswith("/"):
        return None
    if ":" in value and value.startswith("/"):
        # PYTHONPATH-like values are handled as individual roots.
        return None
    if not (value.startswith("/") or value.startswith("~")):
        return None
    path = Path(value).expanduser()
    result: dict[str, object] = {
        "path": value,
        "exists": path.exists() or path.is_symlink(),
        "is_symlink": path.is_symlink(),
    }
    if path.is_symlink():
        result["link_target"] = os.readlink(path)
    resolved = _resolved(path)
    result["resolved_target"] = str(resolved)
    result["resolved_exists"] = resolved.exists()
    if resolved.exists():
        if resolved.is_dir():
            result["kind"] = "directory"
        elif resolved.is_file():
            result["kind"] = "file"
            result["code_sha256"] = sha256_file(resolved)
        else:
            result["kind"] = "other"
    else:
        result["kind"] = "missing"
    return result


def describe_preserved_environment(plist: Mapping[str, Any]) -> dict[str, object]:
    values = extract_environment(plist)
    records: dict[str, object] = {}
    for key in sorted(values):
        value = _safe_json_value(key, values[key])
        record: dict[str, object] = {"value": value}
        probe = _path_probe(values[key])
        if probe is not None:
            record["path_probe"] = probe
        records[key] = record
    safety = {
        key: values.get(key)
        for key in sorted(values)
        if key.lower() in {
            "research_only",
            "production_allowed",
            "buy_gate_updated",
            "orders_sent",
        }
        or key in {"RESEARCH_ONLY", "PRODUCTION_ALLOWED", "BUY_GATE_UPDATED", "ORDERS_SENT"}
    }
    return {"variables": records, "safety_flags": safety}


def render_cutover(
    *,
    source_plist_path: Path,
    candidate_root: Path,
    release_id: str,
    manifest_path: Path,
    manifest_sha256: str,
    backup_plist_path: Path | None = None,
    current_manager_state_root: Path = DEFAULT_MANAGER_STATE_ROOT,
    candidate_manager_state_root: Path | None = None,
    formal_release_root: Path = DEFAULT_FORMAL_RELEASE_ROOT,
    source_root: Path,
) -> dict[str, object]:
    """Write staged plist and rollback plan below ``candidate_root`` only."""

    source_plist_path = _unaliased(source_plist_path, kind="file")
    candidate_root = _unaliased(candidate_root, kind="directory")
    assert_safe_candidate_path(
        candidate_root, source_root=source_root, formal_release_root=formal_release_root
    )
    root_identity = _identity(candidate_root)
    source_raw, source_identity = _read_exact_file(source_plist_path)
    source_sha = hashlib.sha256(source_raw).hexdigest()
    manifest_path = _unaliased(manifest_path, kind="file")
    if manifest_path != candidate_root / "release-manifest.json":
        raise ValueError("API_PREPARE_MANIFEST_ROOT_MISMATCH")
    if sha256_file(manifest_path) != manifest_sha256:
        raise ValueError("API_RELEASE_INTEGRATION_MANIFEST_SHA_MISMATCH")
    api_integration = verify_api_release_candidate(
        candidate_root=candidate_root,
        active_api_plist_path=source_plist_path,
        expected_manifest_sha256=manifest_sha256,
        active_pointer="base",
    )
    if api_integration["candidate"]["release_id"] != release_id:
        raise ValueError("API_PREPARE_RELEASE_ID_MISMATCH")
    if api_integration["active_api_plist_sha256"] != source_sha:
        raise ValueError("API_PREPARE_SOURCE_CHANGED")

    def assert_inputs_current() -> None:
        current_raw, current_identity = _read_exact_file(source_plist_path)
        if current_raw != source_raw or current_identity != source_identity:
            raise ValueError("API_PREPARE_SOURCE_CHANGED")
        if (_unaliased(candidate_root, kind="directory") != candidate_root
                or _identity(candidate_root) != root_identity):
            raise ValueError("API_PREPARE_CANDIDATE_ROOT_CHANGED")

    assert_inputs_current()
    current_manager_state_root = _unaliased(current_manager_state_root, kind="directory")
    candidate_manager_state_root = _unaliased(
        candidate_manager_state_root or (candidate_root / "state" / "manager_auto_research")
    )
    if _is_within(candidate_manager_state_root, current_manager_state_root) or _is_within(
        current_manager_state_root, candidate_manager_state_root
    ):
        raise ValueError("candidate manager state root must be isolated from the current root")
    if candidate_manager_state_root == candidate_root or not _is_within(
        candidate_manager_state_root, candidate_root
    ):
        raise ValueError("candidate manager state root must be below candidate root")

    source_plist = plistlib.loads(source_raw)
    staged = rewrite_api_only_plist(
        source_plist,
        candidate_app_root=candidate_root / "app",
        release_id=release_id,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        candidate_manager_state_root=candidate_manager_state_root,
    )
    staged_raw = plistlib.dumps(staged, fmt=plistlib.FMT_XML, sort_keys=True)
    staged_sha = hashlib.sha256(staged_raw).hexdigest()
    config_dir = _unaliased(candidate_root / "config")
    staged_path = config_dir / "com.lexi.v35.api-only.plist"
    plan_path = config_dir / "api-only-cutover-plan.json"
    if staged_path.exists() or staged_path.is_symlink() or plan_path.exists() or plan_path.is_symlink():
        raise FileExistsError("refusing to overwrite staged api-only configuration")

    backup_sha = None
    backup = None
    if backup_plist_path is not None:
        backup_path = _unaliased(backup_plist_path)
        if backup_path.is_file():
            backup_raw, _ = _read_exact_file(backup_path)
            backup_sha = hashlib.sha256(backup_raw).hexdigest()
            backup = backup_path
    label = str(source_plist.get("Label", "com.lexi.v35.api-only"))
    plan: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "activation_status": "NOT_ACTIVATED",
        "launchctl_called": False,
        "source_plist": {"path": str(source_plist_path), "sha256": source_sha, "label": label},
        "candidate_plist": {"path": str(staged_path), "sha256": staged_sha},
        "candidate_manifest": {"path": str(manifest_path), "sha256": manifest_sha256},
        "api_release_integration": {
            **api_integration,
            "preflight_revalidation_required_under_shared_lock": True,
            "shared_lock_protocol": "persistent flock adjacent to active API plist; never unlink",
        },
        "manager_state": {
            "current_root": str(current_manager_state_root),
            "candidate_root": str(candidate_manager_state_root),
            "roots_are_distinct": True,
            "authority_layout": ".commits/<YYYYMMDD>/<input_identity>.json",
            "candidate_state_copied": False,
            "shared_writer_guard": "Old and new writers must never run concurrently against one manager root.",
        },
        "rollback_backup": (
            {"path": str(backup), "sha256": backup_sha}
            if backup is not None
            else {"path": str(source_plist_path), "sha256": source_sha, "kind": "current_source_fallback"}
        ),
        "preserved_environment": describe_preserved_environment(source_plist),
        "activation_protocol": {
            "shared_lock_required": True,
            "integration_revalidation_required": True,
            "automatic_activation": False,
            "publisher": "reviewed actual API publisher with pinned api_release_integration.py",
            "required_action": "Generate and review the current release adapter; direct launchctl/cp commands are not a protected publication path.",
        },
        "guard": "Staged plan only; actual API publisher must revalidate under its shared lock before any service or pointer change.",
    }
    # Revalidate after all rendering work and before any output file is written.
    final_integration = verify_api_release_candidate(
        candidate_root=candidate_root, active_api_plist_path=source_plist_path,
        expected_manifest_sha256=manifest_sha256, active_pointer="base",
    )
    if final_integration != api_integration:
        raise ValueError("API_PREPARE_INTEGRATION_CHANGED")
    assert_inputs_current()
    with _candidate_directory(candidate_root, candidate_manager_state_root / ".commits"):
        pass
    with _candidate_directory(candidate_root, config_dir) as (directory_fd, assert_directory):
        assert_inputs_current()
        assert_directory()
        _write_exclusive_at(directory_fd, staged_path.name, staged_raw)
        assert_inputs_current()
        assert_directory()
        _write_exclusive_at(directory_fd, plan_path.name,
            (json.dumps(plan, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
        assert_inputs_current()
    return plan


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-plist", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--manifest-path", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--backup-plist", type=Path)
    parser.add_argument("--current-manager-state-root", type=Path, default=DEFAULT_MANAGER_STATE_ROOT)
    parser.add_argument("--candidate-manager-state-root", type=Path)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--formal-release-root", type=Path, default=DEFAULT_FORMAL_RELEASE_ROOT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        plan = render_cutover(
            source_plist_path=args.source_plist,
            candidate_root=args.candidate_root,
            release_id=args.release_id,
            manifest_path=args.manifest_path,
            manifest_sha256=args.manifest_sha256,
            backup_plist_path=args.backup_plist,
            current_manager_state_root=args.current_manager_state_root,
            candidate_manager_state_root=args.candidate_manager_state_root,
            source_root=args.source_root,
            formal_release_root=args.formal_release_root,
        )
    except (FileExistsError, FileNotFoundError, ValueError, OSError) as exc:
        print(f"cutover preparation refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(plan, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
