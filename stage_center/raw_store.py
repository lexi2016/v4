"""Stage-center SafeRootStore-compatible raw publication.

The deployed shared-data store is deliberately small in this package: an
immutable ``runs/<date>/<role>/<run_id>`` directory contains a CSV artifact,
manifest, and receipt.  A verified ``latest.json`` pointer is advanced under
one lock only after the complete trio has been checked.  The stage center owns
this namespace; V3 and V3.5 remain read-only consumers.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import tempfile
import time
from infrastructure.interprocess_lock import owned_interprocess_lock
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping, Sequence
from uuid import uuid4

from .calendar import calendar_provenance, eligible_stage_markets
from .contracts import EIGHT_STAGES, SAFETY_FLAGS

RAW_FIELDS = (
    "batch_index",
    "code",
    "name",
    "update_time",
    "last_price",
    "open_price",
    "high_price",
    "low_price",
    "prev_close_price",
    "turnover",
    "volume",
    "bid_price",
    "ask_price",
    "bid_vol",
    "ask_vol",
    "window_start",
    "window_end",
    "bar_count",
    "temporal_cutoff_safe",
)
ARTIFACT_FIELDS = ("trade_date", "bar_time", *RAW_FIELDS)

# Keep the deployed SafeRootStore schema identifiers.  ``PARTIAL_WITH_ROWS``
# is an explicit stage-center extension: it never implies temporal proof.
RAW_SCHEMA_VERSION = "v3_shared_data.artifact.csv.v1"
RAW_MANIFEST_SCHEMA_VERSION = "v3_shared_data.manifest.v1"
RAW_RECEIPT_SCHEMA_VERSION = "v3_shared_data.receipt.v1"
RAW_LATEST_SCHEMA_VERSION = "v3_shared_data.latest.v1"
RAW_BUNDLE_SCHEMA_VERSION = "stage_center.raw_bundle.v1"
RAW_BUNDLE_LATEST_SCHEMA_VERSION = "stage_center.raw_bundle_latest.v1"
RAW_STATUSES = frozenset(("READY", "PARTIAL_WITH_ROWS", "READY_EMPTY", "CANNOT_CONFIRM"))
_TIME_FMT = "%Y-%m-%d %H:%M:%S"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_LOCK_TIMEOUT_SECONDS = 10.0
_LOCK_STALE_SECONDS = 30.0
_ROLE_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?$")
_MARKET_CODE = {
    "A_SHARE": re.compile(r"^(?:A|SH|SZ|BJ)\.\d{6}$"),
    "HK_CONNECT": re.compile(r"^HK\.\d{5}$"),
}


class RawStoreError(ValueError):
    """Fail-closed raw artifact validation, conflict, or integrity error."""


def canonical_sha(payload: Any) -> str:
    """SHA256 of the deployed canonical JSON representation."""
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    from stage_center._raw_store_parts.filesystem_io import __atomic_write_bytes_body as _v4_impl
    return _v4_impl(globals(), path, data)


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    from stage_center._raw_store_parts.filesystem_io import __atomic_write_json_body as _v4_impl
    return _v4_impl(globals(), path, payload)


def _atomic_write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    from stage_center._raw_store_parts.filesystem_io import __atomic_write_csv_body as _v4_impl
    return _v4_impl(globals(), path, rows)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise RawStoreError(f"invalid JSON: {path}") from error
    if not isinstance(payload, dict):
        raise RawStoreError(f"JSON object required: {path}")
    return payload


def _safe_relative(root: Path, relative: str) -> Path:
    from stage_center._raw_store_parts.filesystem_io import __safe_relative_body as _v4_impl
    return _v4_impl(globals(), root, relative)


def _validate_date(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{8}", value):
        raise RawStoreError("trade_date must use YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise RawStoreError("trade_date is not a real date") from error
    return value


def _validate_slug(value: str, label: str) -> str:
    if not isinstance(value, str) or not _ROLE_RE.fullmatch(value):
        raise RawStoreError(f"{label} is not a safe slug")
    return value


def _stage(stage_id: str):
    for stage in EIGHT_STAGES:
        if stage.stage_id == stage_id:
            return stage
    raise RawStoreError(f"unknown stage {stage_id!r}")


def _expected_bundle_markets(stage_id: str, trade_date: str) -> tuple[str, ...]:
    stage = _stage(stage_id)
    try:
        eligible = eligible_stage_markets(stage.markets, trade_date)
    except ValueError as error:
        raise RawStoreError(str(error)) from error
    if not eligible:
        raise RawStoreError("no securities market is open for this stage date")
    return eligible


def _role_for(stage_id: str, market: str) -> str:
    _stage(stage_id)
    if market not in {item for stage in EIGHT_STAGES for item in stage.markets}:
        raise RawStoreError(f"unknown market {market!r}")
    if stage_id == "STAGE_0925":
        if market == "A_SHARE":
            return "A_SHARE_AUCTION_TRANSACTION_STAGE_0925"
        if market == "HK_CONNECT":
            return "HK_CONNECT_AUCTION_REFERENCE_STAGE_0925"
    return f"{market}_1MIN_{stage_id}"


def _artifact_row(trade_date: str, row: Mapping[str, Any]) -> dict[str, Any]:
    update_time = str(row.get("update_time") or "")
    bar_time = update_time.split(" ", 1)[1] if " " in update_time else update_time
    return {"trade_date": trade_date, "bar_time": bar_time, **dict(row)}


def _parse_timestamp(value: Any, label: str) -> datetime:
    try:
        return datetime.strptime(str(value), _TIME_FMT)
    except (TypeError, ValueError) as error:
        raise RawStoreError(f"{label} must use YYYY-MM-DD HH:MM:SS") from error


def _window_bounds(trade_date: str, stage_id: str, market: str) -> tuple[datetime, datetime]:
    from stage_center._raw_store_parts.codec import __window_bounds_body as _v4_impl
    return _v4_impl(globals(), trade_date, stage_id, market)


def validate_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    trade_date: str,
    stage_id: str,
    market: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate the frozen 19-field raw shape without dropping evidence."""
    from stage_center._raw_store_parts.receipt_identity import _validate_rows_body as _v4_impl
    return _v4_impl(globals(), rows, trade_date=trade_date, stage_id=stage_id, market=market)


def _status(
    source_status: str,
    rows: Sequence[Mapping[str, Any]],
    issues: Sequence[str],
    cannot_confirm: Sequence[str],
) -> str:
    from stage_center._raw_store_parts.codec import __status_body as _v4_impl
    return _v4_impl(globals(), source_status, rows, issues, cannot_confirm)


def _coverage(requested_rows: int, source_rows: int) -> float:
    if requested_rows <= 0:
        return 1.0 if source_rows == 0 else 0.0
    return round(min(source_rows / requested_rows, 1.0), 6)


class RawStore:
    """Safe-root store with immutable runs and merged latest pointers."""

    def __init__(self, root: Path | str):
        root_path = Path(root).expanduser()
        if root_path.exists() and root_path.is_symlink():
            raise RawStoreError("store root symlink is forbidden")
        self.root = root_path.resolve()
        self.runs_root = self.root / "runs"
        self.latest_path = self.root / "latest.json"
        self.lock_path = self.root / ".store.lock"

    @contextmanager
    def _lock(self):
        with owned_interprocess_lock(self.lock_path, timeout_seconds=_LOCK_TIMEOUT_SECONDS, timeout_message='store lock timeout', timeout_error=RawStoreError):
            yield

    def _load_latest(self) -> dict[str, Any]:
        from stage_center._raw_store_parts.codec import _RawStore__load_latest_body as _v4_impl
        return _v4_impl(globals(), self)

    @staticmethod
    def _role(stage_id: str, market: str) -> str:
        _validate_slug(market, "market")
        return _role_for(stage_id, market)

    @staticmethod
    def _entry_key(trade_date: str, stage_id: str, market: str) -> str:
        return f"{_validate_date(trade_date)}/{stage_id}/{market}"

    def _verify_run_paths(
        self,
        *,
        trade_date: str,
        stage_id: str,
        market: str,
        run_id: str,
        expected_owner: str = "stage_center",
    ) -> dict[str, Any]:
        from stage_center._raw_store_parts.transaction_read import _RawStore__verify_run_paths_body as _v4_impl
        return _v4_impl(globals(), self, trade_date=trade_date, stage_id=stage_id, market=market, run_id=run_id, expected_owner=expected_owner)

    def verify_run(self, trade_date: str, stage_id: str, market: str, run_id: str) -> dict[str, Any]:
        return self._verify_run_paths(
            trade_date=trade_date,
            stage_id=stage_id,
            market=market,
            run_id=run_id,
        )

    def verify_latest(self, trade_date: str, stage_id: str, market: str) -> dict[str, Any]:
        latest = self._load_latest()
        key = self._entry_key(trade_date, stage_id, market)
        entry = latest["entries"].get(key)
        if not isinstance(entry, Mapping):
            raise RawStoreError(f"no latest run for {key}")
        verified = self.verify_run(trade_date, stage_id, market, str(entry.get("run_id")))
        if entry.get("receipt_sha256") != verified["receipt_sha256"] or entry.get("manifest_sha256") != verified["manifest_sha256"]:
            raise RawStoreError("latest pointer SHA mismatch")
        return {"latest": dict(entry), "verified": verified}

    def _merge_latest(self, latest: dict[str, Any], key: str, entry: Mapping[str, Any]) -> None:
        entries = dict(latest.get("entries", {}))
        entries[key] = dict(entry)
        latest["entries"] = entries

    def publish(
        self,
        *,
        trade_date: str,
        stage_id: str,
        market: str,
        source_id: str,
        source_status: str,
        rows: Sequence[Mapping[str, Any]],
        cannot_confirm: Sequence[str] = (),
        source_evidence: Sequence[str] = (),
        requested_rows: int | None = None,
        missing_symbols: Sequence[str] = (),
        window: str | None = None,
        cutoff_at: str | None = None,
    ) -> dict[str, Any]:
        from stage_center._raw_store_parts.transaction_publish import _RawStore_publish_body as _v4_impl
        return _v4_impl(globals(), self, trade_date=trade_date, stage_id=stage_id, market=market, source_id=source_id, source_status=source_status, rows=rows, cannot_confirm=cannot_confirm, source_evidence=source_evidence, requested_rows=requested_rows, missing_symbols=missing_symbols, window=window, cutoff_at=cutoff_at)

    def _load_bundle_latest(self) -> dict[str, Any]:
        from stage_center._raw_store_parts.codec import _RawStore__load_bundle_latest_body as _v4_impl
        return _v4_impl(globals(), self)

    def _verify_bundle(self, trade_date: str, stage_id: str, bundle_id: str) -> dict[str, Any]:
        from stage_center._raw_store_parts.transaction_read import _RawStore__verify_bundle_body as _v4_impl
        return _v4_impl(globals(), self, trade_date, stage_id, bundle_id)

    def publish_bundle(
        self,
        *,
        trade_date: str,
        stage_id: str,
        status: str,
        markets: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]:
        from stage_center._raw_store_parts.transaction_publish import _RawStore_publish_bundle_body as _v4_impl
        return _v4_impl(globals(), self, trade_date=trade_date, stage_id=stage_id, status=status, markets=markets)

    def read_verified_bundle(self, trade_date: str, stage_id: str) -> dict[str, Any]:
        latest = self._load_bundle_latest()
        key = f"{_validate_date(trade_date)}/{stage_id}"
        entry = latest["entries"].get(key)
        if not isinstance(entry, Mapping):
            raise RawStoreError(f"no latest bundle for {key}")
        verified = self._verify_bundle(trade_date, stage_id, str(entry.get("bundle_id")))
        if entry.get("receipt_sha256") != verified["receipt_sha256"]:
            raise RawStoreError("bundle latest pointer SHA mismatch")
        return {"latest": dict(entry), **verified}


def publish_raw_artifact(
    root: Path | str,
    *,
    trade_date: str,
    stage_id: str,
    market: str,
    source_id: str,
    source_status: str,
    rows: Sequence[Mapping[str, Any]],
    cannot_confirm: Sequence[str] = (),
    source_evidence: Sequence[str] = (),
    requested_rows: int | None = None,
    missing_symbols: Sequence[str] = (),
    window: str | None = None,
    cutoff_at: str | None = None,
) -> dict[str, Any]:
    from stage_center._raw_store_parts.transaction_publish import _publish_raw_artifact_body as _v4_impl
    return _v4_impl(globals(), root, trade_date=trade_date, stage_id=stage_id, market=market, source_id=source_id, source_status=source_status, rows=rows, cannot_confirm=cannot_confirm, source_evidence=source_evidence, requested_rows=requested_rows, missing_symbols=missing_symbols, window=window, cutoff_at=cutoff_at)
