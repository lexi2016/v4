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
    if output_root == tdx_root or _inside(tdx_root, output_root) or _inside(output_root, tdx_root):
        raise InputManifestError("input output root must be separate from the TDX source root")
    # A V4 candidate must never write into an immutable release or formal
    # Application Support tree.  This is a path guard, not an assertion that
    # the caller's entire environment has been inventoried.
    output_text = str(output_root)
    if (
        ("/Library/Application Support/" in output_text or "/releases/" in output_text)
        and not (
            is_v4_formula_state_path(tdx_root)
            and is_v4_formula_state_path(output_root)
        )
    ):
        raise InputManifestError("input output root cannot target formal release/Application Support")


def _read_sync_receipt(path: Path, target_date: str) -> tuple[dict[str, Any], bytes, str]:
    receipt_path = _resolved_regular(path, "sync receipt")
    try:
        raw = receipt_path.read_bytes()
        payload = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise InputManifestError("sync receipt is unreadable") from error
    if not isinstance(payload, dict):
        raise InputManifestError("sync receipt must be an object")
    if str(payload.get("status", "")).upper() not in {"READY", "PASS"}:
        raise InputManifestError("sync receipt is not READY")
    if _date(payload.get("target_date"), "sync receipt target_date") != target_date:
        raise InputManifestError("sync receipt target_date mismatch")
    for flag in ("production_allowed", "buy_gate_updated", "orders_sent"):
        if payload.get(flag) is not False:
            raise InputManifestError(f"sync receipt safety flag is not false: {flag}")
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise InputManifestError("sync receipt has no explicit files")
    return payload, raw, _sha256_bytes(raw)


def _receipt_files(
    payload: Mapping[str, Any],
    *,
    tdx_root: Path,
    target_date: str,
) -> list[tuple[str, str, Path]]:
    seen: set[str] = set()
    admitted: list[tuple[str, str, Path]] = []
    for raw_value in payload.get("files", []):
        if not isinstance(raw_value, str) or "\x00" in raw_value or "\\" in raw_value:
            raise InputManifestError("sync receipt file path is unsafe")
        raw_path = Path(raw_value).expanduser()
        path = _resolved_regular(raw_path, "sync source file")
        if not _inside(tdx_root, path):
            raise InputManifestError(f"sync source file escapes TDX root: {path}")
        relative = path.relative_to(tdx_root).as_posix()
        if not _DAY_PATH.fullmatch(relative):
            raise InputManifestError(f"sync source path is not a canonical vipdoc day file: {relative}")
        if relative in seen:
            raise InputManifestError(f"sync source file is duplicated: {relative}")
        seen.add(relative)
        rows = read_hq_day_bars(path)
        if path.stat().st_size == 0 or path.stat().st_size % DAY_STRUCT.size:
            raise InputManifestError(f"sync source file has invalid .day byte size: {relative}")
        if not rows:
            raise InputManifestError(f"sync source file is empty: {relative}")
        previous = 0
        target_seen = False
        for row in rows:
            ok, reason = valid_hq_bar(row)
            if not ok:
                raise InputManifestError(f"sync source bar invalid ({relative}): {reason}")
            row_date = int(row["year"]) * 10000 + int(row["month"]) * 100 + int(row["day"])
            _date(row_date, f"sync source {relative} bar")
            if row_date <= previous:
                raise InputManifestError(f"sync source dates are not strictly increasing: {relative}")
            if row_date > int(target_date):
                raise InputManifestError(f"sync source contains future bar: {relative}:{row_date}")
            previous = row_date
            target_seen = target_seen or row_date == int(target_date)
        if not target_seen:
            raise InputManifestError(f"sync source has no exact target-date row: {relative}")
        market = relative.split("/", 2)[1]
        code = Path(relative).stem[len(market):]
        admitted.append((relative, market, path))
    if not admitted:
        raise InputManifestError("sync receipt admitted no source files")
    return sorted(admitted)


def _frame_for_day_file(path: Path, relative: str, market: str, target_date: str) -> pd.DataFrame:
    code = Path(relative).stem[len(market):]
    exchange = _MARKET_CODES[market]
    records: list[dict[str, Any]] = []
    for row in read_hq_day_bars(path):
        row_date = int(row["year"]) * 10000 + int(row["month"]) * 100 + int(row["day"])
        records.append(
            {
                "ts_code": f"{code}.{exchange}",
                "trade_date": row_date,
                "raw_code": code,
                "exchange": exchange,
                "market_type": "A",
                "name": "tdx-day",
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["vol"]),
                "amount": float(row["amount"]),
            }
        )
    frame = pd.DataFrame.from_records(records)
    if frame.empty or not (frame["trade_date"] == int(target_date)).any():
        raise InputManifestError(f"decoded source has no target row: {relative}")
    return frame


def _write_parquet(frame: pd.DataFrame, destination: Path) -> tuple[int, str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise InputManifestError(f"refusing to overwrite input artifact: {destination}")
    with tempfile.NamedTemporaryFile(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        frame.to_parquet(temporary, index=False, engine="pyarrow")
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return len(frame), _sha256_file(destination)


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

    target = _date(target_date, "target_date")
    tdx = _resolved_root(Path(tdx_root), "TDX root")
    output = _resolved_root(Path(output_root), "input output root")
    _ensure_distinct_roots(tdx, output)
    if output.exists() and any(output.iterdir()):
        raise InputManifestError("input output root must be empty; refusing mixed-generation writes")
    output.mkdir(parents=True, exist_ok=True)
    if _has_symlink_ancestor(output):
        raise InputManifestError("input output root has symlink ancestry")
    receipt, receipt_raw, receipt_sha = _read_sync_receipt(Path(sync_receipt), target)
    admitted = _receipt_files(receipt, tdx_root=tdx, target_date=target)
    chosen_run_id = run_id or f"a-sync-{target}"
    if not _RUN_ID.fullmatch(chosen_run_id):
        raise InputManifestError("run_id is missing or unsafe")

    file_entries: list[dict[str, Any]] = []
    source_day_entries: list[dict[str, Any]] = []
    all_keys: set[tuple[str, int]] = set()
    total_rows = 0
    target_rows = 0
    for relative, market, source_path in admitted:
        frame = _frame_for_day_file(source_path, relative, market, target)
        keys = set(zip(frame["ts_code"].astype(str), frame["trade_date"].astype(int)))
        if all_keys.intersection(keys):
            raise InputManifestError(f"duplicate source keys across files: {relative}")
        all_keys.update(keys)
        parquet_relative = Path("files") / f"{Path(relative).stem}.parquet"
        destination = output / parquet_relative
        rows, parquet_sha = _write_parquet(frame, destination)
        source_sha = _sha256_file(source_path)
        source_bytes = source_path.stat().st_size
        file_entries.append(
            {
                "path": parquet_relative.as_posix(),
                "sha256": parquet_sha,
                "rows": rows,
                "source_day_path": relative,
                "source_day_sha256": source_sha,
                "source_day_bytes": source_bytes,
                "target_date_rows": int((frame["trade_date"] == int(target)).sum()),
            }
        )
        source_day_entries.append(
            {
                "path": relative,
                "sha256": source_sha,
                "bytes": source_bytes,
                "rows": rows,
                "target_date_rows": int((frame["trade_date"] == int(target)).sum()),
            }
        )
        total_rows += rows
        target_rows += int((frame["trade_date"] == int(target)).sum())

    parquet_shas = [str(item["sha256"]) for item in file_entries]
    source_sha = parquet_shas[0] if len(parquet_shas) == 1 else _sha256_bytes("\n".join(sorted(parquet_shas)).encode("ascii"))
    manifest: dict[str, Any] = {
        "schema": SCHEMA,
        "market": "A",
        "target_date": target,
        "run_id": chosen_run_id,
        "source": {
            "name": "a_sync_day_files",
            "version": "v1",
            "sync_receipt_path": str(Path(sync_receipt).expanduser().resolve()),
            "sync_receipt_sha256": receipt_sha,
            "tdx_root": str(tdx),
            "network": "NOT_USED",
        },
        "source_sha256": source_sha,
        "source_day_files": source_day_entries,
        "files": file_entries,
        "coverage": {
            "status": "PASS",
            "rows": total_rows,
            "symbols": len(admitted),
            "files": len(admitted),
            "target_date_rows": target_rows,
        },
        "duplicate_key_audit": {"status": "PASS", "duplicate_rows": 0},
        "future_check": {"status": "PASS", "future_rows": 0},
        "safety": {"network": "NOT_USED", "formal_data_write": False},
    }
    manifest["manifest_sha256"] = _manifest_sha(manifest)
    manifest_path = output / "manifest.json"
    if manifest_path.exists() or manifest_path.is_symlink():
        raise InputManifestError("refusing to overwrite input manifest")
    manifest_path.write_bytes((json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))
    return {
        "status": "READY",
        "schema": SCHEMA,
        "target_date": target,
        "run_id": chosen_run_id,
        "path": str(manifest_path),
        "bytes": manifest_path.stat().st_size,
        "sha256": _sha256_file(manifest_path),
        "manifest_sha256": manifest["manifest_sha256"],
        "source_sha256": source_sha,
        "files": len(file_entries),
        "rows": total_rows,
        "target_date_rows": target_rows,
        "sync_receipt_sha256": receipt_sha,
        "sync_receipt_bytes": len(receipt_raw),
        "network": "NOT_USED",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


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
    accepted, accepted_raw, accepted_sha, accepted_path = _read_json_object(
        accepted_manifest, "accepted-only manifest"
    )
    copy, _copy_raw, copy_sha, copy_path = _read_json_object(
        copy_receipt, "accepted-only copy receipt"
    )
    if accepted.get("schema_version") != ACCEPTED_ONLY_SOURCE_SCHEMA:
        raise InputManifestError("accepted-only manifest schema mismatch")
    if _date(accepted.get("target_date"), "accepted-only target_date") != target_date:
        raise InputManifestError("accepted-only manifest target_date mismatch")
    if str(accepted.get("authority_status") or "").upper() != "REBUILD_REQUIRED":
        raise InputManifestError("accepted-only manifest must retain authority_status=REBUILD_REQUIRED")
    excluded = accepted.get("excluded_rebuild_candidate_count")
    if not isinstance(excluded, int) or isinstance(excluded, bool) or excluded <= 0:
        raise InputManifestError("accepted-only manifest excluded count is invalid")
    for flag in ("production_allowed", "buy_gate_updated", "orders_sent"):
        if accepted.get(flag) is not False:
            raise InputManifestError(f"accepted-only manifest safety flag is not false: {flag}")
    accepted_files = accepted.get("files")
    if not isinstance(accepted_files, list) or not accepted_files:
        raise InputManifestError("accepted-only manifest has no explicit files")
    if (
        ("/Library/Application Support/" in str(tdx_root) or "/releases/" in str(tdx_root))
        and not is_v4_formula_state_path(tdx_root)
    ):
        raise InputManifestError("accepted-only TDX root cannot target formal Application Support/release")

    accepted_by_relative: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(accepted_files):
        if not isinstance(item, Mapping):
            raise InputManifestError(f"accepted-only manifest file {index} is not an object")
        relative = item.get("relative_path")
        if (
            not isinstance(relative, str)
            or "\x00" in relative
            or "\\" in relative
            or not _DAY_PATH.fullmatch(relative)
        ):
            raise InputManifestError(f"accepted-only manifest path is unsafe: {relative!r}")
        if relative in accepted_by_relative:
            raise InputManifestError(f"accepted-only manifest path is duplicated: {relative}")
        source_path = item.get("path")
        if not isinstance(source_path, str) or not source_path or not Path(source_path).is_absolute():
            raise InputManifestError(f"accepted-only manifest source path is not absolute: {relative}")
        source_posix = Path(source_path).as_posix()
        if Path(source_path).name != Path(relative).name or not source_posix.endswith("/" + relative):
            raise InputManifestError(f"accepted-only manifest source basename mismatch: {relative}")
        digest = str(item.get("sha256") or "").lower()
        if not _SHA256.fullmatch(digest):
            raise InputManifestError(f"accepted-only manifest SHA is invalid: {relative}")
        fetch_status = str(item.get("fetch_status") or "").upper()
        if not fetch_status or any(token in fetch_status for token in ("FAILED", "QUARANTINE", "CANNOT_CONFIRM")):
            raise InputManifestError(f"accepted-only manifest file is not accepted: {relative}")
        accepted_by_relative[relative] = {
            "relative_path": relative,
            "source_path": source_path,
            "sha256": digest,
            "fetch_status": fetch_status,
        }

    if copy.get("schema_version") not in (None, "v3_5.a_sync.accepted_formula_input.copy_receipt.v1"):
        # The historical copy receipt predates a schema key.  If a future
        # receipt adds one, accept only the known binding rather than guessing.
        raise InputManifestError("accepted-only copy receipt schema mismatch")
    if copy.get("status") != ACCEPTED_ONLY_COPY_STATUS:
        raise InputManifestError("accepted-only copy receipt status is not accepted-only")
    if _date(copy.get("target_date"), "accepted-only copy target_date") != target_date:
        raise InputManifestError("accepted-only copy target_date mismatch")
    if str(copy.get("source_authority_status") or "").upper() != "REBUILD_REQUIRED":
        raise InputManifestError("accepted-only copy must retain source authority status")
    if copy.get("manifest_sha256") != accepted_sha:
        raise InputManifestError("accepted-only copy receipt is not bound to manifest bytes")
    if copy.get("excluded_rebuild_candidate_count") != excluded:
        raise InputManifestError("accepted-only excluded count mismatch")
    if copy.get("formal_data_changed") is not False or copy.get("full_5800_authority_pass") is not False:
        raise InputManifestError("accepted-only copy receipt claims formal/full authority")
    if copy.get("no_source_status_rewrite") is not True:
        raise InputManifestError("accepted-only copy receipt does not preserve source status")
    source_receipt_sha = str(copy.get("source_receipt_sha256") or "").lower()
    if not _SHA256.fullmatch(source_receipt_sha):
        raise InputManifestError("accepted-only source receipt SHA is invalid")
    source_receipt_raw = copy.get("source_receipt")
    if not isinstance(source_receipt_raw, str) or not source_receipt_raw:
        raise InputManifestError("accepted-only source receipt path is missing")
    source_receipt_path = _resolved_regular(Path(source_receipt_raw), "accepted-only source receipt")
    if _sha256_file(source_receipt_path) != source_receipt_sha:
        raise InputManifestError("accepted-only source receipt SHA mismatch")
    copy_files = copy.get("files")
    if not isinstance(copy_files, list) or len(copy_files) != len(accepted_by_relative):
        raise InputManifestError("accepted-only copy file count does not match accepted manifest")
    copy_by_relative: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(copy_files):
        if not isinstance(item, Mapping):
            raise InputManifestError(f"accepted-only copy file {index} is not an object")
        relative = item.get("relative_path")
        if not isinstance(relative, str) or not _DAY_PATH.fullmatch(relative) or relative in copy_by_relative:
            raise InputManifestError(f"accepted-only copy path is invalid or duplicated: {relative!r}")
        digest = str(item.get("sha256") or "").lower()
        byte_count = item.get("bytes")
        if not _SHA256.fullmatch(digest) or not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count <= 0:
            raise InputManifestError(f"accepted-only copy identity is invalid: {relative}")
        copy_by_relative[relative] = {"sha256": digest, "bytes": byte_count}
    if set(copy_by_relative) != set(accepted_by_relative):
        raise InputManifestError("accepted-only copy path scope differs from accepted manifest")
    for relative, entry in accepted_by_relative.items():
        copied = copy_by_relative[relative]
        if copied["sha256"] != entry["sha256"]:
            raise InputManifestError(f"accepted-only copy SHA differs from manifest: {relative}")

    # Validate the requested subset only after both complete metadata sets have
    # been compared.  This preserves the full manifest/copy-receipt identity
    # gate while keeping unselected source members out of the read/hash/decode
    # loop below.
    if selected_relative_paths is None:
        selected = None
        relatives_to_check = sorted(accepted_by_relative)
    else:
        selected = list(selected_relative_paths)
        if not selected:
            raise InputManifestError("accepted-only selected scope cannot be empty")
        for relative in selected:
            if not isinstance(relative, str) or not _DAY_PATH.fullmatch(relative):
                raise InputManifestError(f"accepted-only selected path is invalid: {relative!r}")
        if len(selected) != len(set(selected)):
            raise InputManifestError("accepted-only selected scope contains duplicates")
        for relative in selected:
            if relative not in accepted_by_relative:
                raise InputManifestError(f"accepted-only selected path is outside accepted set: {relative}")
        relatives_to_check = selected

    copied_count = copy.get("copied_count")
    if copied_count != len(accepted_by_relative):
        raise InputManifestError("accepted-only copied_count does not match explicit files")
    receipt_root_raw = copy.get("target_root")
    if not isinstance(receipt_root_raw, str) or not receipt_root_raw:
        raise InputManifestError("accepted-only copy target_root is missing")
    receipt_root = _resolved_root(Path(receipt_root_raw), "accepted-only copy target root")
    if receipt_root != tdx_root:
        raise InputManifestError("accepted-only copy target_root differs from supplied TDX root")

    checked: list[dict[str, Any]] = []
    for relative in relatives_to_check:
        entry = accepted_by_relative[relative]
        source = _resolved_regular(tdx_root / relative, "accepted-only source file")
        if not _inside(tdx_root, source):
            raise InputManifestError(f"accepted-only source escapes TDX root: {relative}")
        actual_sha = _sha256_file(source)
        if actual_sha != entry["sha256"]:
            raise InputManifestError(
                f"accepted-only source SHA mismatch: {relative}: expected={entry['sha256']}:actual={actual_sha}"
            )
        actual_bytes = source.stat().st_size
        if actual_bytes != copy_by_relative[relative]["bytes"]:
            raise InputManifestError(f"accepted-only source byte count mismatch: {relative}")
        if actual_bytes == 0 or actual_bytes % DAY_STRUCT.size:
            raise InputManifestError(f"accepted-only source .day shape is invalid: {relative}")
        rows = read_hq_day_bars(source)
        if not rows:
            raise InputManifestError(f"accepted-only source is empty: {relative}")
        previous = 0
        target_seen = False
        for row in rows:
            valid, reason = valid_hq_bar(row)
            if not valid:
                raise InputManifestError(f"accepted-only source bar invalid ({relative}): {reason}")
            row_date = int(row["year"]) * 10000 + int(row["month"]) * 100 + int(row["day"])
            _date(row_date, f"accepted-only source {relative} bar")
            if row_date <= previous:
                raise InputManifestError(f"accepted-only source dates are not strictly increasing: {relative}")
            if row_date > int(target_date):
                raise InputManifestError(f"accepted-only source contains future bar: {relative}:{row_date}")
            previous = row_date
            target_seen = target_seen or row_date == int(target_date)
        if not target_seen:
            raise InputManifestError(f"accepted-only source has no exact target-date row: {relative}")
        checked.append({"relative": relative, "market": relative.split("/", 2)[1], "path": source, "source_entry": entry})
    return accepted, copy, accepted_sha, copy_sha, checked, len(accepted_by_relative), accepted_path, copy_path


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
    target = _date(target_date, "target_date")
    tdx = _resolved_root(Path(tdx_root), "TDX root")
    output = _resolved_root(Path(output_root), "input output root")
    _ensure_distinct_roots(tdx, output)
    if output.exists() and any(output.iterdir()):
        raise InputManifestError("input output root must be empty; refusing mixed-generation writes")
    output.mkdir(parents=True, exist_ok=True)
    if _has_symlink_ancestor(output):
        raise InputManifestError("input output root has symlink ancestry")
    accepted, copy, accepted_sha, copy_sha, admitted, accepted_count, accepted_path, copy_path = _accepted_only_entries(
        accepted_manifest=accepted_manifest,
        copy_receipt=copy_receipt,
        tdx_root=tdx,
        target_date=target,
        selected_relative_paths=selected_relative_paths,
    )
    if selected_relative_paths is None:
        scope = "ACCEPTED_ONLY_FULL"
    else:
        scope = "ACCEPTED_ONLY_SUBSET"
    chosen_run_id = run_id or f"a-sync-{target}-accepted-only"
    if not _RUN_ID.fullmatch(chosen_run_id):
        raise InputManifestError("run_id is missing or unsafe")

    file_entries: list[dict[str, Any]] = []
    source_day_entries: list[dict[str, Any]] = []
    all_keys: set[tuple[str, int]] = set()
    total_rows = 0
    target_rows = 0
    for item in admitted:
        relative, market, source_path = item["relative"], item["market"], item["path"]
        frame = _frame_for_day_file(source_path, relative, market, target)
        keys = set(zip(frame["ts_code"].astype(str), frame["trade_date"].astype(int)))
        if all_keys.intersection(keys):
            raise InputManifestError(f"duplicate source keys across files: {relative}")
        all_keys.update(keys)
        parquet_relative = Path("files") / f"{Path(relative).stem}.parquet"
        destination = output / parquet_relative
        rows, parquet_sha = _write_parquet(frame, destination)
        source_sha = _sha256_file(source_path)
        source_bytes = source_path.stat().st_size
        file_entries.append(
            {
                "path": parquet_relative.as_posix(),
                "sha256": parquet_sha,
                "rows": rows,
                "source_day_path": relative,
                "source_day_sha256": source_sha,
                "source_day_bytes": source_bytes,
                "target_date_rows": int((frame["trade_date"] == int(target)).sum()),
            }
        )
        source_day_entries.append(
            {
                "path": relative,
                "sha256": source_sha,
                "bytes": source_bytes,
                "rows": rows,
                "target_date_rows": int((frame["trade_date"] == int(target)).sum()),
                "accepted_fetch_status": item["source_entry"]["fetch_status"],
            }
        )
        total_rows += rows
        target_rows += int((frame["trade_date"] == int(target)).sum())

    parquet_shas = [str(item["sha256"]) for item in file_entries]
    source_sha = parquet_shas[0] if len(parquet_shas) == 1 else _sha256_bytes("\n".join(sorted(parquet_shas)).encode("ascii"))
    excluded = int(accepted["excluded_rebuild_candidate_count"])
    selected_count = len(file_entries)
    source_receipt_sha = str(copy["source_receipt_sha256"]).lower()
    manifest: dict[str, Any] = {
        "schema": SCHEMA,
        "market": "A",
        "target_date": target,
        "run_id": chosen_run_id,
        "authority_status": "REBUILD_REQUIRED",
        "full_authority_pass": False,
        "scope": scope,
        "source": {
            "name": "a_sync_accepted_only_day_files",
            "version": "v1",
            "scope": scope,
            "accepted_manifest_path": str(accepted_path),
            "accepted_manifest_sha256": accepted_sha,
            "accepted_manifest_file_count": accepted_count,
            "selected_file_count": selected_count,
            "copy_receipt_path": str(copy_path),
            "copy_receipt_sha256": copy_sha,
            "source_receipt_path": str(copy["source_receipt"]),
            "source_receipt_sha256": source_receipt_sha,
            "authority_status": "REBUILD_REQUIRED",
            "excluded_rebuild_candidate_count": excluded,
            "tdx_root": str(tdx),
            "network": "NOT_USED",
        },
        "source_sha256": source_sha,
        "source_day_files": source_day_entries,
        "files": file_entries,
        "coverage": {
            "status": "PASS",
            "scope": scope,
            "authority_status": "REBUILD_REQUIRED",
            "full_authority_pass": False,
            "accepted_manifest_files": accepted_count,
            "excluded_rebuild_candidate_count": excluded,
            "rows": total_rows,
            "symbols": selected_count,
            "files": selected_count,
            "target_date_rows": target_rows,
        },
        "duplicate_key_audit": {"status": "PASS", "duplicate_rows": 0},
        "future_check": {"status": "PASS", "future_rows": 0},
        "safety": {"network": "NOT_USED", "formal_data_write": False},
    }
    manifest["manifest_sha256"] = _manifest_sha(manifest)
    manifest_path = output / "manifest.json"
    if manifest_path.exists() or manifest_path.is_symlink():
        raise InputManifestError("refusing to overwrite input manifest")
    manifest_path.write_bytes((json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))
    return {
        "status": "READY_ACCEPTED_ONLY",
        "schema": SCHEMA,
        "target_date": target,
        "run_id": chosen_run_id,
        "path": str(manifest_path),
        "bytes": manifest_path.stat().st_size,
        "sha256": _sha256_file(manifest_path),
        "manifest_sha256": manifest["manifest_sha256"],
        "source_sha256": source_sha,
        "scope": scope,
        "accepted_manifest_sha256": accepted_sha,
        "copy_receipt_sha256": copy_sha,
        "source_receipt_sha256": source_receipt_sha,
        "accepted_manifest_file_count": accepted_count,
        "selected_file_count": selected_count,
        "excluded_rebuild_candidate_count": excluded,
        "authority_status": "REBUILD_REQUIRED",
        "full_authority_pass": False,
        "files": selected_count,
        "rows": total_rows,
        "target_date_rows": target_rows,
        "network": "NOT_USED",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sync-receipt", required=False, type=Path)
    parser.add_argument(
        "--accepted-only-manifest",
        required=False,
        type=Path,
        help="Explicit v3.5 accepted-only .day manifest; preserves REBUILD_REQUIRED provenance.",
    )
    parser.add_argument(
        "--accepted-only-copy-receipt",
        required=False,
        type=Path,
        help="Receipt binding the accepted-only manifest to its isolated copied root.",
    )
    parser.add_argument(
        "--accepted-only-path",
        action="append",
        default=None,
        help="Canonical accepted-only relative path to include; repeat for a bounded subset canary.",
    )
    parser.add_argument("--tdx-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args(argv)
    try:
        accepted_mode = args.accepted_only_manifest is not None or args.accepted_only_copy_receipt is not None
        if accepted_mode:
            if args.sync_receipt is not None:
                raise InputManifestError("sync and accepted-only input modes are mutually exclusive")
            if args.accepted_only_manifest is None or args.accepted_only_copy_receipt is None:
                raise InputManifestError("accepted-only manifest and copy receipt are both required")
            result = build_accepted_only_a_formula_input_manifest(
                accepted_manifest=args.accepted_only_manifest,
                copy_receipt=args.accepted_only_copy_receipt,
                tdx_root=args.tdx_root,
                output_root=args.output_root,
                target_date=args.target_date,
                run_id=args.run_id,
                selected_relative_paths=args.accepted_only_path,
            )
        else:
            if args.accepted_only_path:
                raise InputManifestError("accepted-only paths require accepted-only input mode")
            if args.sync_receipt is None:
                raise InputManifestError("one input mode is required")
            result = build_a_formula_input_manifest(
                sync_receipt=args.sync_receipt,
                tdx_root=args.tdx_root,
                output_root=args.output_root,
                target_date=args.target_date,
                run_id=args.run_id,
            )
    except Exception as error:
        result = {
            "status": "FAILED",
            "error_type": type(error).__name__,
            "error": str(error),
            "network": "NOT_USED",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


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
