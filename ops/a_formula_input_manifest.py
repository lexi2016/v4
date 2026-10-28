"""Build an explicit, read-only A-formula input manifest from sync output.

The adapter is intentionally a boundary rather than another market-data
producer.  It consumes the exact ``.day`` files named by an A-sync receipt,
decodes them with the canonical V4 codec, and writes parquet copies below a
new caller-owned input root.  No network client, glob/latest fallback, or
formal state path is used here.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from ops.a_share_daily_sync import DAY_STRUCT, read_hq_day_bars, valid_hq_bar
from infrastructure.formula_generation import is_v4_formula_state_path

# Preserve direct-file CLI discovery of the sibling review modules.
if __name__ == "__main__" and not __package__:
    import sys as _v4_import_sys
    from pathlib import Path as _v4_import_Path
    _v4_import_sys.path.insert(0, str(_v4_import_Path(__file__).resolve().parents[1]))



SCHEMA = "v4.a_formula.input_manifest.v1"
ACCEPTED_ONLY_SOURCE_SCHEMA = "v3_5.a_sync.accepted_formula_input.v1"
ACCEPTED_ONLY_COPY_STATUS = "COPIED_VERIFIED_ACCEPTED_SUBSET_ONLY"
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_RUN_ID = re.compile(r"^[A-Za-z0-9_.-]{1,160}$")
_DAY_PATH = re.compile(r"^vipdoc/(sh|sz|bj)/lday/\1\d{6}\.day$")
_MARKET_CODES = {"sh": "SH", "sz": "SZ", "bj": "BJ"}


class InputManifestError(ValueError):
    """Raised when sync output cannot be admitted as an exact input."""


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _date(value: Any, label: str) -> str:
    text = str(value or "").strip().replace("-", "")
    if not re.fullmatch(r"\d{8}", text):
        raise InputManifestError(f"{label} must be an exact YYYYMMDD date")
    try:
        _datetime.datetime.strptime(text, "%Y%m%d")
    except ValueError as error:
        raise InputManifestError(f"{label} is not a calendar date") from error
    return text


def _has_symlink_ancestor(path: Path) -> bool:
    current = Path(path).expanduser()
    if not current.exists() and not current.is_symlink():
        current = current.parent
    while True:
        if current.is_symlink():
            return True
        if current.parent == current:
            return False
        current = current.parent


def _resolved_regular(path: Path, label: str) -> Path:
    raw = Path(path).expanduser()
    if _has_symlink_ancestor(raw):
        raise InputManifestError(f"{label} has symlink ancestry")
    resolved = raw.resolve(strict=False)
    if not resolved.is_file() or resolved.is_symlink():
        raise InputManifestError(f"{label} is missing or not a regular file: {raw}")
    return resolved


def _resolved_root(path: Path, label: str) -> Path:
    raw = Path(path).expanduser()
    if _has_symlink_ancestor(raw):
        raise InputManifestError(f"{label} has symlink ancestry")
    resolved = raw.resolve(strict=False)
    if not resolved.is_absolute():
        raise InputManifestError(f"{label} must be absolute")
    return resolved


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _ensure_distinct_roots(tdx_root: Path, output_root: Path) -> None:
    from ops._a_formula_input_manifest_parts.source_io import __ensure_distinct_roots_body as _v4_impl
    return _v4_impl(globals(), tdx_root, output_root)


def _read_sync_receipt(path: Path, target_date: str) -> tuple[dict[str, Any], bytes, str]:
    from ops._a_formula_input_manifest_parts.source_io import __read_sync_receipt_body as _v4_impl
    return _v4_impl(globals(), path, target_date)


def _receipt_files(
    payload: Mapping[str, Any],
    *,
    tdx_root: Path,
    target_date: str,
) -> list[tuple[str, str, Path]]:
    from ops._a_formula_input_manifest_parts.source_io import __receipt_files_body as _v4_impl
    return _v4_impl(globals(), payload, tdx_root=tdx_root, target_date=target_date)


def _frame_for_day_file(path: Path, relative: str, market: str, target_date: str) -> pd.DataFrame:
    from ops._a_formula_input_manifest_parts.source_io import __frame_for_day_file_body as _v4_impl
    return _v4_impl(globals(), path, relative, market, target_date)


def _write_parquet(frame: pd.DataFrame, destination: Path) -> tuple[int, str]:
    from ops._a_formula_input_manifest_parts.source_io import __write_parquet_body as _v4_impl
    return _v4_impl(globals(), frame, destination)


def _manifest_sha(payload: Mapping[str, Any]) -> str:
    value = dict(payload)
    value.pop("manifest_sha256", None)
    return _sha256_bytes(_canonical_bytes(value))


def build_a_formula_input_manifest(
    *,
    sync_receipt: Path | str,
    tdx_root: Path | str,
    output_root: Path | str,
    target_date: str | int,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Materialize and return one exact-date V4 input manifest."""
    from ops._a_formula_input_manifest_parts.manifest_generation import _build_a_formula_input_manifest_body as _v4_impl
    return _v4_impl(globals(), sync_receipt=sync_receipt, tdx_root=tdx_root, output_root=output_root, target_date=target_date, run_id=run_id)


def _read_json_object(path: Path | str, label: str) -> tuple[dict[str, Any], bytes, str, Path]:
    """Read a receipt through the regular-file boundary and retain its raw SHA."""
    resolved = _resolved_regular(Path(path), label)
    try:
        raw = resolved.read_bytes()
        payload = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise InputManifestError(f"{label} is unreadable") from error
    if not isinstance(payload, dict):
        raise InputManifestError(f"{label} must be an object")
    return payload, raw, _sha256_bytes(raw), resolved


def _accepted_only_entries(
    *,
    accepted_manifest: Path | str,
    copy_receipt: Path | str,
    tdx_root: Path,
    target_date: str,
    selected_relative_paths: list[str] | tuple[str, ...] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str, str, list[dict[str, Any]], int, Path, Path]:
    """Validate the immutable accepted-only .day binding before parquet writes."""
    from ops._a_formula_input_manifest_parts.accepted_entries import __accepted_only_entries_body as _v4_impl
    return _v4_impl(globals(), accepted_manifest=accepted_manifest, copy_receipt=copy_receipt, tdx_root=tdx_root, target_date=target_date, selected_relative_paths=selected_relative_paths)


def build_accepted_only_a_formula_input_manifest(
    *,
    accepted_manifest: Path | str,
    copy_receipt: Path | str,
    tdx_root: Path | str,
    output_root: Path | str,
    target_date: str | int,
    run_id: str | None = None,
    selected_relative_paths: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Materialize an explicit accepted-only .day set without full-authority relabeling."""
    from ops._a_formula_input_manifest_parts.accepted_entries import _build_accepted_only_a_formula_input_manifest_body as _v4_impl
    return _v4_impl(globals(), accepted_manifest=accepted_manifest, copy_receipt=copy_receipt, tdx_root=tdx_root, output_root=output_root, target_date=target_date, run_id=run_id, selected_relative_paths=selected_relative_paths)


def main(argv: list[str] | None = None) -> int:
    from ops._a_formula_input_manifest_parts.source_io import _main_body as _v4_impl
    return _v4_impl(globals(), argv)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ACCEPTED_ONLY_COPY_STATUS",
    "ACCEPTED_ONLY_SOURCE_SCHEMA",
    "InputManifestError",
    "SCHEMA",
    "build_a_formula_input_manifest",
    "build_accepted_only_a_formula_input_manifest",
    "main",
]
