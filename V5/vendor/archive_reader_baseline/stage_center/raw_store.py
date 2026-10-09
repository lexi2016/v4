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
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.{uuid4().hex}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _atomic_write_bytes(
        path,
        (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8"),
    )


def _atomic_write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.{uuid4().hex}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=ARTIFACT_FIELDS,
                extrasaction="raise",
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise RawStoreError(f"invalid JSON: {path}") from error
    if not isinstance(payload, dict):
        raise RawStoreError(f"JSON object required: {path}")
    return payload


def _safe_relative(root: Path, relative: str) -> Path:
    if (
        not isinstance(relative, str)
        or not relative
        or "\\" in relative
        or relative.startswith("/")
        or (len(relative) > 1 and relative[1] == ":")
    ):
        raise RawStoreError("path must be normalized and relative")
    parsed = PurePosixPath(relative)
    if parsed.as_posix() != relative or any(part in {"", ".", ".."} for part in parsed.parts):
        raise RawStoreError("path must be normalized and relative")
    current = root
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise RawStoreError("symlink component is forbidden")
    resolved_root = root.resolve()
    resolved_candidate = current.resolve()
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as error:
        raise RawStoreError("path escapes store root") from error
    return current


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
        expected = eligible_stage_markets(stage.markets, trade_date)
    except ValueError as error:
        raise RawStoreError(str(error)) from error
    if not expected:
        raise RawStoreError("no securities market is open for this stage date")
    return expected


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
    stage = _stage(stage_id)
    if market not in stage.markets:
        raise RawStoreError(f"market {market!r} is not scheduled for {stage_id!r}")
    if stage_id == "STAGE_0925":
        start, cutoff = (
            ("09:20:00", "09:25:05")
            if market == "A_SHARE"
            else ("09:15:00", "09:20:05")
        )
    else:
        start, cutoff = stage.window.split("-")[0], stage.cutoff
        start = start if len(start) == 8 else f"{start}:00"
        cutoff = cutoff if len(cutoff) == 8 else f"{cutoff}:00"
    day = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
    return (
        _parse_timestamp(f"{day} {start}", "window start"),
        _parse_timestamp(f"{day} {cutoff}", "window cutoff"),
    )


def validate_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    trade_date: str,
    stage_id: str,
    market: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate the frozen 19-field raw shape without dropping evidence."""
    _validate_date(trade_date)
    expected_market = _MARKET_CODE.get(market)
    if expected_market is None:
        raise RawStoreError(f"unknown market {market!r}")
    lower, upper = _window_bounds(trade_date, stage_id, market)
    validated: list[dict[str, Any]] = []
    issues: list[str] = []
    for index, source in enumerate(rows):
        if not isinstance(source, Mapping) or set(source) != set(RAW_FIELDS):
            issues.append(f"row {index}: raw row must contain exactly 19 fields")
            continue
        row = dict(source)
        code = str(row.get("code") or "").upper()
        if not expected_market.fullmatch(code):
            issues.append(f"row {index}: invalid {market} code")
            continue
        try:
            update = _parse_timestamp(row.get("update_time"), "update_time")
            window_start = _parse_timestamp(row.get("window_start"), "window_start")
            window_end = _parse_timestamp(row.get("window_end"), "window_end")
        except RawStoreError as error:
            issues.append(f"row {index}: {error}")
            continue
        if any(
            timestamp.strftime("%Y%m%d") != trade_date
            for timestamp in (update, window_start, window_end)
        ):
            issues.append(f"row {index}: date mismatch")
            continue
        if not lower <= window_start <= window_end <= upper or update != window_end:
            issues.append(f"row {index}: temporal cutoff/window violation")
            continue
        if row.get("temporal_cutoff_safe") is not True:
            issues.append(f"row {index}: temporal_cutoff_safe must be true")
            continue
        validated.append(row)
    return validated, issues


def _status(
    source_status: str,
    rows: Sequence[Mapping[str, Any]],
    issues: Sequence[str],
    cannot_confirm: Sequence[str],
) -> str:
    if source_status == "READ_OK":
        source_status = "READY"
    elif source_status == "READ_FAILED":
        source_status = "CANNOT_CONFIRM"
    if source_status not in RAW_STATUSES:
        raise RawStoreError(f"unknown source status {source_status!r}")
    if not rows:
        return "READY_EMPTY" if source_status == "READY" and not issues and not cannot_confirm else "CANNOT_CONFIRM"
    # Invalid rows are never silently downgraded to an apparently healthy
    # partial result.  Missing symbols supplied by an adapter are explicit
    # partial evidence; malformed rows are fail-closed CANNOT_CONFIRM.
    if issues or source_status == "CANNOT_CONFIRM":
        return "CANNOT_CONFIRM"
    if source_status == "READY":
        return "READY" if not cannot_confirm else "CANNOT_CONFIRM"
    return "PARTIAL_WITH_ROWS"


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
        if not self.latest_path.exists():
            return {
                "schema_version": RAW_LATEST_SCHEMA_VERSION,
                "owner": "stage_center",
                "entries": {},
                **SAFETY_FLAGS,
            }
        latest = _read_json(self.latest_path)
        if latest.get("schema_version") != RAW_LATEST_SCHEMA_VERSION or latest.get("owner") != "stage_center":
            raise RawStoreError("latest.json schema/owner mismatch")
        if not isinstance(latest.get("entries"), Mapping):
            raise RawStoreError("latest.json entries missing")
        for key in SAFETY_FLAGS:
            if latest.get(key) is not False:
                raise RawStoreError(f"latest safety flag {key!r} must be false")
        return latest

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
        _validate_date(trade_date)
        _stage(stage_id)
        role = self._role(stage_id, market)
        _validate_slug(run_id, "run_id")
        prefix = f"runs/{trade_date}/{role}/{run_id}"
        run_dir = _safe_relative(self.root, prefix)
        artifact = _safe_relative(self.root, f"{prefix}/artifact.csv")
        manifest_path = _safe_relative(self.root, f"{prefix}/manifest.json")
        receipt_path = _safe_relative(self.root, f"{prefix}/receipt.json")
        if not run_dir.is_dir() or not all(path.is_file() for path in (artifact, manifest_path, receipt_path)):
            raise RawStoreError("run trio incomplete")
        manifest = _read_json(manifest_path)
        receipt = _read_json(receipt_path)
        if manifest.get("schema_version") != RAW_MANIFEST_SCHEMA_VERSION:
            raise RawStoreError("manifest schema mismatch")
        if receipt.get("schema_version") != RAW_RECEIPT_SCHEMA_VERSION:
            raise RawStoreError("receipt schema mismatch")
        for payload, label in ((manifest, "manifest"), (receipt, "receipt")):
            if payload.get("owner") != expected_owner:
                raise RawStoreError(f"{label} owner mismatch")
            if payload.get("trade_date") != trade_date or payload.get("stage_id") != stage_id or payload.get("market") != market:
                raise RawStoreError(f"{label} identity mismatch")
            if payload.get("run_id") != run_id:
                raise RawStoreError(f"{label} run_id mismatch")
            for key in SAFETY_FLAGS:
                if payload.get(key) is not False:
                    raise RawStoreError(f"{label} safety flag {key!r} must be false")
        expected_artifact = f"{prefix}/artifact.csv"
        if manifest.get("artifact_relative") != expected_artifact:
            raise RawStoreError("manifest artifact path mismatch")
        if receipt.get("artifact_relative") != expected_artifact:
            raise RawStoreError("receipt artifact path mismatch")
        actual_artifact_sha = _sha_file(artifact)
        if manifest.get("artifact_sha256") != actual_artifact_sha or receipt.get("artifact_sha256") != actual_artifact_sha:
            raise RawStoreError("artifact sha mismatch")
        with artifact.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != ARTIFACT_FIELDS:
                raise RawStoreError("raw artifact fields mismatch")
            rows = list(reader)
        row_count = len(rows)
        if manifest.get("row_count") != row_count or receipt.get("row_count") != row_count:
            raise RawStoreError("row_count mismatch")
        canonical_manifest_sha = canonical_sha(manifest)
        if receipt.get("manifest_sha256") != canonical_manifest_sha:
            raise RawStoreError("manifest sha mismatch")
        status = receipt.get("status")
        if status not in RAW_STATUSES or manifest.get("status") != status:
            raise RawStoreError("raw status mismatch")
        if status == "READY" and (row_count <= 0 or manifest.get("temporal_cutoff_safe") is not True):
            raise RawStoreError("READY lacks rows or temporal proof")
        if status == "READY_EMPTY" and row_count != 0:
            raise RawStoreError("READY_EMPTY contains rows")
        if status == "PARTIAL_WITH_ROWS" and row_count <= 0:
            raise RawStoreError("PARTIAL_WITH_ROWS lacks rows")
        return {
            "owner": expected_owner,
            "trade_date": trade_date,
            "stage_id": stage_id,
            "market": market,
            "role": role,
            "run_id": run_id,
            "status": status,
            "artifact_relative": expected_artifact,
            "manifest_relative": f"{prefix}/manifest.json",
            "receipt_relative": f"{prefix}/receipt.json",
            "artifact_sha256": actual_artifact_sha,
            "manifest_sha256": canonical_manifest_sha,
            "receipt_sha256": canonical_sha(receipt),
            "receipt_file_sha256": _sha_file(receipt_path),
            "row_count": row_count,
            "requested_rows": manifest.get("requested_rows", row_count),
            "source_rows": manifest.get("source_rows", row_count),
            "coverage_ratio": manifest.get("coverage_ratio", 1.0),
            "missing_symbols": list(manifest.get("missing_symbols", [])),
            "source_evidence": list(manifest.get("source_evidence", [])),
            "cannot_confirm": list(manifest.get("cannot_confirm", [])),
            "calendar": dict(manifest.get("calendar", calendar_provenance())),
            "source_id": receipt.get("source_id"),
            "source_status": receipt.get("source_status"),
            "idempotency_key": receipt.get("idempotency_key"),
            "window": receipt.get("window"),
            "cutoff_at": receipt.get("cutoff_at"),
        }

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
        _validate_date(trade_date)
        _stage(stage_id)
        if market not in _stage(stage_id).markets:
            raise RawStoreError(f"market {market!r} is not scheduled for {stage_id!r}")
        if not isinstance(source_id, str) or not source_id or "/" in source_id or "\\" in source_id:
            raise RawStoreError("source_id is unsafe")
        validated, issues = validate_rows(rows, trade_date=trade_date, stage_id=stage_id, market=market)
        status = _status(source_status, validated, issues, cannot_confirm)
        normalized_source_status = {"READ_OK": "READY", "READ_FAILED": "CANNOT_CONFIRM"}.get(source_status, source_status)
        requested = len(rows) if requested_rows is None else int(requested_rows)
        if requested < 0:
            raise RawStoreError("requested_rows must be non-negative")
        missing = list(dict.fromkeys(str(item) for item in missing_symbols))
        evidence = list(dict.fromkeys(str(item) for item in (*source_evidence, *cannot_confirm, *issues)))
        cannot = list(dict.fromkeys(str(item) for item in (*cannot_confirm, *issues)))
        source_rows = len(validated)
        coverage = _coverage(requested, source_rows)
        input_sha = canonical_sha(
            {
                "source_id": source_id,
                "source_status": normalized_source_status,
                "rows": validated,
                "cannot_confirm": cannot,
                "source_evidence": evidence,
                "requested_rows": requested,
                "missing_symbols": missing,
            }
        )
        idem_key = canonical_sha(
            {
                "owner": "stage_center",
                "trade_date": trade_date,
                "stage_id": stage_id,
                "market": market,
                "source_id": source_id,
                "input_sha256": input_sha,
            }
        )
        role = self._role(stage_id, market)
        run_id = f"{trade_date}-{role.lower()}-{idem_key[:16]}"
        prefix = f"runs/{trade_date}/{role}/{run_id}"
        artifact_relative = f"{prefix}/artifact.csv"
        manifest_relative = f"{prefix}/manifest.json"
        receipt_relative = f"{prefix}/receipt.json"
        manifest: dict[str, Any]
        receipt: dict[str, Any]
        with self._lock():
            latest = self._load_latest()
            key = self._entry_key(trade_date, stage_id, market)
            existing = latest["entries"].get(key)
            if isinstance(existing, Mapping):
                if existing.get("idempotency_key") != idem_key:
                    raise RawStoreError(f"raw slot conflict: {key}")
                verified = self.verify_run(trade_date, stage_id, market, str(existing.get("run_id")))
                for field in ("owner", "status", "run_id", "artifact_sha256", "manifest_sha256", "receipt_sha256"):
                    if existing.get(field) != verified.get(field):
                        raise RawStoreError(f"latest pointer {field} mismatch")
                return {"ok": True, "already_exists": True, **verified}
            run_dir = _safe_relative(self.root, prefix)
            if run_dir.exists():
                raise RawStoreError("immutable run path already exists without latest pointer")
            run_dir.mkdir(parents=True, exist_ok=False)
            artifact_path = _safe_relative(self.root, artifact_relative)
            _atomic_write_csv(
                artifact_path,
                [_artifact_row(trade_date, row) for row in validated],
            )
            artifact_sha = _sha_file(artifact_path)
            manifest = {
                "schema_version": RAW_MANIFEST_SCHEMA_VERSION,
                "owner": "stage_center",
                "trade_date": trade_date,
                "stage_id": stage_id,
                "market": market,
                "role": role,
                "run_id": run_id,
                "status": status,
                "source_id": source_id,
                "source_status": normalized_source_status,
                "artifact_relative": artifact_relative,
                "artifact_sha256": artifact_sha,
                "row_count": source_rows,
                "temporal_cutoff_safe": status == "READY",
                "requested_rows": requested,
                "source_rows": source_rows,
                "coverage_ratio": coverage,
                "missing_symbols": missing,
                "source_evidence": evidence,
                "cannot_confirm": cannot,
                "input_sha256": input_sha,
                "calendar": calendar_provenance(),
                **SAFETY_FLAGS,
            }
            receipt = {
                "schema_version": RAW_RECEIPT_SCHEMA_VERSION,
                "owner": "stage_center",
                "trade_date": trade_date,
                "stage_id": stage_id,
                "market": market,
                "role": role,
                "run_id": run_id,
                "status": status,
                "source_id": source_id,
                "source_status": normalized_source_status,
                "artifact_relative": artifact_relative,
                "artifact_sha256": artifact_sha,
                "manifest_sha256": canonical_sha(manifest),
                "row_count": source_rows,
                "temporal_cutoff_safe": status == "READY",
                "requested_rows": requested,
                "source_rows": source_rows,
                "coverage_ratio": coverage,
                "missing_symbols": missing,
                "source_evidence": evidence,
                "cannot_confirm": cannot,
                "input_sha256": input_sha,
                "idempotency_key": idem_key,
                "window": window,
                "cutoff_at": cutoff_at,
                "calendar": calendar_provenance(),
                **SAFETY_FLAGS,
            }
            _atomic_write_json(_safe_relative(self.root, manifest_relative), manifest)
            _atomic_write_json(_safe_relative(self.root, receipt_relative), receipt)
            verified = self._verify_run_paths(
                trade_date=trade_date,
                stage_id=stage_id,
                market=market,
                run_id=run_id,
            )
            entry = {
                "owner": "stage_center",
                "trade_date": trade_date,
                "stage_id": stage_id,
                "market": market,
                "role": role,
                "run_id": run_id,
                "status": status,
                "idempotency_key": idem_key,
                "artifact_relative": artifact_relative,
                "manifest_relative": manifest_relative,
                "receipt_relative": receipt_relative,
                "artifact_sha256": verified["artifact_sha256"],
                "manifest_sha256": verified["manifest_sha256"],
                "receipt_sha256": verified["receipt_sha256"],
                "row_count": source_rows,
                **SAFETY_FLAGS,
            }
            self._merge_latest(latest, key, entry)
            _atomic_write_json(self.latest_path, latest)
            return {"ok": True, **verified}

    def _load_bundle_latest(self) -> dict[str, Any]:
        path = self.root / "bundle_latest.json"
        if not path.exists():
            return {
                "schema_version": RAW_BUNDLE_LATEST_SCHEMA_VERSION,
                "owner": "stage_center",
                "entries": {},
                **SAFETY_FLAGS,
            }
        latest = _read_json(path)
        if latest.get("schema_version") != RAW_BUNDLE_LATEST_SCHEMA_VERSION or latest.get("owner") != "stage_center":
            raise RawStoreError("bundle_latest schema/owner mismatch")
        if not isinstance(latest.get("entries"), Mapping):
            raise RawStoreError("bundle_latest entries missing")
        for key in SAFETY_FLAGS:
            if latest.get(key) is not False:
                raise RawStoreError(f"bundle_latest safety flag {key!r} must be false")
        return latest

    def _verify_bundle(self, trade_date: str, stage_id: str, bundle_id: str) -> dict[str, Any]:
        prefix = f"bundle_runs/{trade_date}/{stage_id}/{bundle_id}"
        receipt_relative = f"{prefix}/receipt.json"
        receipt_path = _safe_relative(self.root, receipt_relative)
        if not receipt_path.is_file():
            raise RawStoreError("bundle receipt missing")
        receipt = _read_json(receipt_path)
        if receipt.get("schema_version") != RAW_BUNDLE_SCHEMA_VERSION or receipt.get("owner") != "stage_center":
            raise RawStoreError("bundle receipt schema/owner mismatch")
        if receipt.get("trade_date") != trade_date or receipt.get("stage_id") != stage_id or receipt.get("bundle_id") != bundle_id:
            raise RawStoreError("bundle receipt identity mismatch")
        if receipt.get("receipt_relative") != receipt_relative:
            raise RawStoreError("bundle receipt path mismatch")
        for key in SAFETY_FLAGS:
            if receipt.get(key) is not False:
                raise RawStoreError(f"bundle receipt safety flag {key!r} must be false")
        markets = receipt.get("markets")
        if not isinstance(markets, Mapping):
            raise RawStoreError("bundle markets missing")
        expected_markets = set(_expected_bundle_markets(stage_id, trade_date))
        if set(markets) != expected_markets:
            raise RawStoreError("bundle market set mismatch")
        observed_statuses: set[str] = set()
        for market, entry in markets.items():
            if not isinstance(entry, Mapping):
                raise RawStoreError("bundle market entry malformed")
            verified = self.verify_run(trade_date, stage_id, market, str(entry.get("run_id")))
            if entry.get("receipt_sha256") != verified["receipt_sha256"] or entry.get("manifest_sha256") != verified["manifest_sha256"]:
                raise RawStoreError("bundle market SHA mismatch")
            observed_statuses.add(verified["status"])
        if observed_statuses == {"READY"}:
            expected_status = "READY"
        elif observed_statuses == {"READY_EMPTY"}:
            expected_status = "READY_EMPTY"
        elif observed_statuses == {"CANNOT_CONFIRM"} and all(
            self.verify_run(trade_date, stage_id, market, str(markets[market].get("run_id")))["row_count"] == 0
            for market in markets
        ):
            expected_status = "CANNOT_CONFIRM"
        else:
            expected_status = "PARTIAL_WITH_ROWS"
        if receipt.get("status") != expected_status:
            raise RawStoreError("bundle status summary mismatch")
        if receipt.get("calendar") != calendar_provenance():
            raise RawStoreError("bundle calendar provenance mismatch")
        return {
            "receipt": receipt,
            "receipt_sha256": canonical_sha(receipt),
            "receipt_file_sha256": _sha_file(receipt_path),
            "receipt_relative": receipt_relative,
        }

    def publish_bundle(
        self,
        *,
        trade_date: str,
        stage_id: str,
        status: str,
        markets: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]:
        _validate_date(trade_date)
        _stage(stage_id)
        if status not in RAW_STATUSES:
            raise RawStoreError(f"unknown bundle status {status!r}")
        expected_markets = set(_expected_bundle_markets(stage_id, trade_date))
        if set(markets) != expected_markets:
            raise RawStoreError("bundle market set mismatch")
        summary_seed = {
            "schema_version": RAW_BUNDLE_SCHEMA_VERSION,
            "owner": "stage_center",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "status": status,
            "markets": {key: dict(value) for key, value in sorted(markets.items())},
            "calendar": calendar_provenance(),
            **SAFETY_FLAGS,
        }
        bundle_id = f"{trade_date}-{stage_id.lower()}-{canonical_sha(summary_seed)[:16]}"
        receipt_relative = f"bundle_runs/{trade_date}/{stage_id}/{bundle_id}/receipt.json"
        key = f"{trade_date}/{stage_id}"
        receipt = {**summary_seed, "bundle_id": bundle_id, "receipt_relative": receipt_relative}
        with self._lock():
            latest = self._load_bundle_latest()
            existing = latest["entries"].get(key)
            if isinstance(existing, Mapping):
                if existing.get("bundle_id") != bundle_id:
                    raise RawStoreError(f"bundle slot conflict: {key}")
                verified = self._verify_bundle(trade_date, stage_id, bundle_id)
                if existing.get("receipt_sha256") != verified["receipt_sha256"]:
                    raise RawStoreError("bundle latest SHA mismatch")
                return {
                    "ok": True,
                    "already_exists": True,
                    "status": status,
                    "bundle_id": bundle_id,
                    "receipt_relative": receipt_relative,
                    "receipt_sha256": verified["receipt_sha256"],
                    "markets": {key: dict(value) for key, value in markets.items()},
                    **SAFETY_FLAGS,
                }
            receipt_path = _safe_relative(self.root, receipt_relative)
            if receipt_path.exists():
                raise RawStoreError("immutable bundle path already exists without latest pointer")
            _atomic_write_json(receipt_path, receipt)
            verified = self._verify_bundle(trade_date, stage_id, bundle_id)
            entries = dict(latest.get("entries", {}))
            entries[key] = {
                "owner": "stage_center",
                "trade_date": trade_date,
                "stage_id": stage_id,
                "bundle_id": bundle_id,
                "status": status,
                "receipt_relative": receipt_relative,
                "receipt_sha256": verified["receipt_sha256"],
                **SAFETY_FLAGS,
            }
            latest["entries"] = entries
            _atomic_write_json(self.root / "bundle_latest.json", latest)
            return {
                "ok": status in {"READY", "PARTIAL_WITH_ROWS", "READY_EMPTY"},
                "status": status,
                "bundle_id": bundle_id,
                "receipt_relative": receipt_relative,
                "receipt_sha256": verified["receipt_sha256"],
                "markets": {key: dict(value) for key, value in markets.items()},
                **SAFETY_FLAGS,
            }

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
    return RawStore(root).publish(
        trade_date=trade_date,
        stage_id=stage_id,
        market=market,
        source_id=source_id,
        source_status=source_status,
        rows=rows,
        cannot_confirm=cannot_confirm,
        source_evidence=source_evidence,
        requested_rows=requested_rows,
        missing_symbols=missing_symbols,
        window=window,
        cutoff_at=cutoff_at,
    )
