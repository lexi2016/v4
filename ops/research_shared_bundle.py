"""Build a deterministic path and SHA identity for shared hourly modules."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


DEFAULT_MANIFEST_PATH = "deployment/research_shared_modules.json"
BUNDLE_SCHEMA_VERSION = "v4.research_shared_bundle.v1"
MANIFEST_SCHEMA_VERSION = "v4.research_shared_modules.v1"


def _safe_relative_path(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"invalid research shared bundle {field}")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or windows.root
        or posix.as_posix() != value
        or any(part in {"", ".", ".."} for part in posix.parts)
    ):
        raise ValueError(f"invalid research shared bundle {field}")
    return value


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_owned_file(root: Path, relative: str) -> bytes:
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root.resolve(strict=True))
        if not resolved.is_file():
            raise ValueError("not a file")
        return resolved.read_bytes()
    except (OSError, ValueError) as error:
        raise ValueError(
            f"research shared bundle file is unavailable or outside root: {relative}"
        ) from error


def build_research_shared_bundle(
    root: str | Path | None = None,
    *,
    manifest_path: str = DEFAULT_MANIFEST_PATH,
) -> dict[str, Any]:
    """Return a deterministic identity for every configured shared module.

    The bundle is relative to one application root, so the same bytes produce
    the same identity in isolated API and scheduler candidates.
    """
    source_root = (
        Path(root).resolve(strict=True)
        if root is not None
        else Path(__file__).resolve().parents[1]
    )
    manifest_path = _safe_relative_path(manifest_path, field="manifest path")
    manifest_bytes = _read_owned_file(source_root, manifest_path)
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid research shared modules manifest") from error
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"schema_version", "bundle_id", "module_paths"}
        or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION
        or not isinstance(manifest.get("bundle_id"), str)
        or not manifest["bundle_id"].strip()
        or not isinstance(manifest.get("module_paths"), list)
        or not manifest["module_paths"]
    ):
        raise ValueError("invalid research shared modules manifest")

    paths = [
        _safe_relative_path(value, field="module path")
        for value in manifest["module_paths"]
    ]
    if len(set(paths)) != len(paths):
        raise ValueError("duplicate research shared bundle module path")

    modules = [
        {"path": relative, "sha256": _sha256(_read_owned_file(source_root, relative))}
        for relative in sorted(paths)
    ]
    manifest_sha256 = _sha256(manifest_bytes)
    identity = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "bundle_id": manifest["bundle_id"],
        "manifest_path": manifest_path,
        "manifest_sha256": manifest_sha256,
        "modules": modules,
    }
    bundle_sha256 = _sha256(
        json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    return {**identity, "bundle_sha256": bundle_sha256}


__all__ = ["build_research_shared_bundle"]
