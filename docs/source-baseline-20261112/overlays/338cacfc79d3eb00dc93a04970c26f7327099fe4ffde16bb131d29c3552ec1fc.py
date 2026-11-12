"""Stage-center SafeRootStore-compatible raw publication.

The deployed shared-data store is deliberately small in this package: an
immutable ``runs/<date>/<role>/<run_id>`` directory contains a CSV artifact,
manifest, and receipt.  A verified ``latest.json`` pointer is advanced under
one lock only after the complete trio has been checked.  The stage center owns
this namespace; V3 and V4 remain read-only consumers.
"""
from __future__ import annotations

import csv
from contextvars import ContextVar
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


# One-day Futu RT_DATA observation contract. It permits preserved after-cutoff
# observations only; it never asserts candle OHLC, PIT safety, or formal eligibility.
HK_FUTU_RTDATA_OBSERVATION_CONTRACT = "HK_FUTU_RTDATA_AFTERFACT_RESEARCH_20261012_R1"
HK_FUTU_RTDATA_SOURCE_ID = "futu_rt_data_afterfact"
HK_FUTU_RTDATA_POOL_ARTIFACT_SHA256 = "220fd29bc907a1c4e431c75fb8eccb3204c5857130eb639f1e9b6a62b60cfe3d"
HK_FUTU_RTDATA_POOL_SOURCE_SHA256 = "738ffa6533bfc1e041a3cd84841d591f0ee6bda53fe8fe420cf608b9a7f3503d"
HK_FUTU_RTDATA_CODE_SET_SHA256 = "5e7ad70ddcd6bcf1ab5007ef8c5f365258e77d6e8d52ade5be2177cb24ae1223"
HK_FUTU_RTDATA_CAPTURE_SHA256_1300 = "63cba10b805b60dc7108ac7d633b0b1c32da2211b04fd976e1cd637ce083afe0"
HK_FUTU_RTDATA_PROVIDER_ROWS_SHA256_1300 = "018175c4cd1e7d2278033da39d79d09e3856468400ea384f104584551e304ad9"
HK_FUTU_RTDATA_RAW_PROJECTION_SHA256_1300 = "54770c58c801f21a61363abee5db5a1eaf015e99a117be75eca758f229ba431b"
HK_FUTU_RTDATA_CAPTURE_SHA256_1445 = "4a310b4920dc5c6ebb7ac8b9f50d1e73d2dcb4d0ef685fef329358c09c2223d0"
HK_FUTU_RTDATA_PROVIDER_ROWS_SHA256_1445 = "0517c61ca85c25e2213a3ff787509d2c7285ec26b473e2a07daa579dab358f05"
HK_FUTU_RTDATA_RAW_PROJECTION_SHA256_1445 = "66e27894b45c5e9b15f25d3e0edf2a3d0a437ac80c12bd228017bc01c9c92132"
_HK_FUTU_RTDATA_STAGE_PROFILES = {
    "STAGE_1300_1315": (
        "13:00-13:15", "13:15:00", "13:00:00", "13:14:00", 14, 1400,
        HK_FUTU_RTDATA_CAPTURE_SHA256_1300,
        HK_FUTU_RTDATA_PROVIDER_ROWS_SHA256_1300,
        HK_FUTU_RTDATA_RAW_PROJECTION_SHA256_1300,
    ),
    "STAGE_1445_1500": (
        "14:45-15:00", "15:00:00", "14:45:00", "14:59:00", 15, 1500,
        HK_FUTU_RTDATA_CAPTURE_SHA256_1445,
        HK_FUTU_RTDATA_PROVIDER_ROWS_SHA256_1445,
        HK_FUTU_RTDATA_RAW_PROJECTION_SHA256_1445,
    ),
}
_HK_FUTU_RTDATA_CANNOT_CONFIRM = (
    "FUTU_RT_DATA_CAPTURE_AFTER_TARGET_CUTOFF_NOT_PIT",
    "FUTU_RT_DATA_FORMAL_STAGE_ELIGIBILITY_CANNOT_CONFIRM",
    "FUTU_RT_DATA_NATURAL_TIME_CAPTURE_CANNOT_CONFIRM",
    "FUTU_RT_DATA_OHLC_AND_ORDERBOOK_UNAVAILABLE",
)


def _futu_rtd_observation_markers(stage_id: str, capture_sha256: str) -> tuple[str, ...]:
    profile = _HK_FUTU_RTDATA_STAGE_PROFILES.get(stage_id)
    if profile is None:
        return ()
    window, cutoff, start, end, observations_per_code, observation_count, _, provider_rows_sha256, projection_sha256 = profile
    return (
        f"futu_observation_contract={HK_FUTU_RTDATA_OBSERVATION_CONTRACT}",
        "futu_afterfact_target_date=20261012",
        f"futu_afterfact_stage_id={stage_id}",
        "futu_afterfact_market=HK_CONNECT",
        f"futu_afterfact_source_id={HK_FUTU_RTDATA_SOURCE_ID}",
        f"futu_afterfact_window={window}",
        f"futu_afterfact_cutoff={cutoff}",
        f"futu_afterfact_row_window_start={start}",
        f"futu_afterfact_row_window_end={end}",
        f"futu_afterfact_pool_artifact_sha256={HK_FUTU_RTDATA_POOL_ARTIFACT_SHA256}",
        f"futu_afterfact_pool_source_sha256={HK_FUTU_RTDATA_POOL_SOURCE_SHA256}",
        f"futu_afterfact_code_set_sha256={HK_FUTU_RTDATA_CODE_SET_SHA256}",
        "futu_afterfact_requested_code_count=100",
        "futu_afterfact_completed_code_count=100",
        f"futu_afterfact_observations_per_code={observations_per_code}",
        f"futu_afterfact_nonblank_observation_count={observation_count}",
        f"futu_afterfact_capture_sha256={capture_sha256}",
        "futu_afterfact_temporal_cutoff_safe=false",
        "futu_afterfact_pit_safe=false",
        "futu_afterfact_formal_stage_eligibility=CANNOT_CONFIRM",
        "futu_afterfact_natural_time_capture=CANNOT_CONFIRM",
        "futu_afterfact_selection_action_boundary=NO_BUY",
        f"futu_afterfact_target_provider_rows_sha256={provider_rows_sha256}",
        f"futu_afterfact_raw_projection_sha256={projection_sha256}",
        "research_only=true",
        "production_allowed=false",
        "buy_gate_updated=false",
        "orders_sent=false",
    )


def _futu_rtd_raw_projection_sha256(rows: Sequence[Mapping[str, Any]]) -> str:
    projected = [
        {
            field: ("" if row.get(field) in (None, "") else str(row.get(field)))
            for field in RAW_FIELDS
        }
        for row in sorted(rows, key=lambda item: str(item.get("code") or "").upper())
    ]
    return hashlib.sha256(
        json.dumps(projected, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _allows_hk_futu_rtd_temporal_false_observation(
    *,
    enabled: bool,
    trade_date: str,
    stage_id: str,
    market: str,
    source_id: str,
    source_status: str,
    rows: Sequence[Mapping[str, Any]],
    requested_rows: int | None,
    missing_symbols: Sequence[str],
    cannot_confirm: Sequence[str],
    source_evidence: Sequence[str],
    window: str | None,
    cutoff_at: str | None,
    manifest_temporal_cutoff_safe: bool | None = False,
) -> bool:
    if enabled is not True or manifest_temporal_cutoff_safe is not False:
        return False
    profile = _HK_FUTU_RTDATA_STAGE_PROFILES.get(stage_id)
    if (
        trade_date != "20261012"
        or market != "HK_CONNECT"
        or source_id != HK_FUTU_RTDATA_SOURCE_ID
        or source_status != "PARTIAL_WITH_ROWS"
        or profile is None
        or (window, cutoff_at) != profile[:2]
        or requested_rows != 100
        or bool(missing_symbols)
        or len(rows) != 100
        or not set(_HK_FUTU_RTDATA_CANNOT_CONFIRM).issubset(set(str(item) for item in cannot_confirm))
    ):
        return False
    evidence = set(str(item) for item in source_evidence)
    capture_sha = next((item.split("=", 1)[1] for item in evidence if item.startswith("futu_afterfact_capture_sha256=")), "")
    if not _SHA_RE.fullmatch(capture_sha):
        return False
    if capture_sha != profile[6]:
        return False
    if not set(_futu_rtd_observation_markers(stage_id, capture_sha)).issubset(evidence):
        return False
    codes = [str(row.get("code") or "").upper() for row in rows]
    if len(set(codes)) != 100 or any(not _MARKET_CODE["HK_CONNECT"].fullmatch(code) for code in codes):
        return False
    code_set_sha = hashlib.sha256(
        json.dumps(tuple(sorted(codes)), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if code_set_sha != HK_FUTU_RTDATA_CODE_SET_SHA256:
        return False
    if _futu_rtd_raw_projection_sha256(rows) != profile[8]:
        return False
    row_start = f"2026-10-12 {profile[2]}"
    row_end = f"2026-10-12 {profile[3]}"
    for row in rows:
        if set(row) != set(RAW_FIELDS):
            return False
        if (
            row.get("temporal_cutoff_safe") is not False
            or row.get("window_start") != row_start
            or row.get("window_end") != row_end
            or row.get("update_time") != row_end
            or row.get("bar_count") not in (profile[4], str(profile[4]))
            or row.get("last_price") in (None, "")
            or row.get("prev_close_price") in (None, "")
            or any(row.get(field) not in (None, "") for field in (
                "open_price", "high_price", "low_price", "bid_price", "ask_price", "bid_vol", "ask_vol"
            ))
        ):
            return False
    return True


_FUTU_RTD_OBSERVATION_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar(
    "stage_center_futu_rtd_observation_context", default=None
)


@contextmanager
def futu_rtd_observation_scope(
    *,
    research_observation_contract: str | None,
    trade_date: str,
    stage_id: str,
    market: str,
    source_id: str,
    source_status: str,
    rows: Sequence[Mapping[str, Any]],
    requested_rows: int | None,
    missing_symbols: Sequence[str],
    cannot_confirm: Sequence[str],
    source_evidence: Sequence[str],
    window: str | None,
    cutoff_at: str | None,
):
    context = {
        "enabled": research_observation_contract == HK_FUTU_RTDATA_OBSERVATION_CONTRACT,
        "trade_date": trade_date,
        "stage_id": stage_id,
        "market": market,
        "source_id": source_id,
        "source_status": source_status,
        "rows": rows,
        "requested_rows": requested_rows,
        "missing_symbols": missing_symbols,
        "cannot_confirm": cannot_confirm,
        "source_evidence": source_evidence,
        "window": window,
        "cutoff_at": cutoff_at,
    }
    if not _allows_hk_futu_rtd_temporal_false_observation(**context):
        raise RawStoreError("Futu after-fact observation contract mismatch")
    token = _FUTU_RTD_OBSERVATION_CONTEXT.set(context)
    try:
        yield
    finally:
        _FUTU_RTD_OBSERVATION_CONTEXT.reset(token)


def _mark_futu_rtd_observation_result(result: Mapping[str, Any]) -> dict[str, Any]:
    marked = dict(result)
    marked["research_observation_contract"] = HK_FUTU_RTDATA_OBSERVATION_CONTRACT
    marked["temporal_cutoff_safe"] = False
    marked["pit_safe"] = False
    marked.update(SAFETY_FLAGS)
    return marked


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
    context = _FUTU_RTD_OBSERVATION_CONTEXT.get()
    if context is not None and _allows_hk_futu_rtd_temporal_false_observation(
        **{**context, "rows": rows}
    ):
        # Validate the frozen shape/window using its existing validator, then
        # restore the provider's explicit false safety value before persistence.
        checked, issues = _v4_impl(
            globals(),
            tuple({**dict(row), "temporal_cutoff_safe": True} for row in rows),
            trade_date=trade_date,
            stage_id=stage_id,
            market=market,
        )
        return [
            {**row, "temporal_cutoff_safe": False}
            for row in checked
        ], issues
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
        verified = self._verify_run_paths(
            trade_date=trade_date,
            stage_id=stage_id,
            market=market,
            run_id=run_id,
        )
        if verified.get("source_id") == HK_FUTU_RTDATA_SOURCE_ID:
            manifest = _read_json(_safe_relative(self.root, verified["manifest_relative"]))
            artifact_path = _safe_relative(self.root, verified["artifact_relative"])
            rows: list[dict[str, Any]] = []
            with artifact_path.open("r", encoding="utf-8-sig", newline="") as stream:
                for raw in csv.DictReader(stream):
                    row = {field: raw.get(field, "") for field in RAW_FIELDS}
                    row["temporal_cutoff_safe"] = (
                        False if str(row["temporal_cutoff_safe"]).strip().lower() == "false" else True
                    )
                    rows.append(row)
            if not _allows_hk_futu_rtd_temporal_false_observation(
                enabled=True,
                trade_date=trade_date,
                stage_id=stage_id,
                market=market,
                source_id=str(verified.get("source_id") or ""),
                source_status=str(verified.get("source_status") or ""),
                rows=rows,
                requested_rows=verified.get("requested_rows"),
                missing_symbols=verified.get("missing_symbols", ()),
                cannot_confirm=verified.get("cannot_confirm", ()),
                source_evidence=verified.get("source_evidence", ()),
                window=verified.get("window"),
                cutoff_at=verified.get("cutoff_at"),
                manifest_temporal_cutoff_safe=manifest.get("temporal_cutoff_safe"),
            ):
                raise RawStoreError("Futu after-fact observation contract mismatch")
            verified = _mark_futu_rtd_observation_result(verified)
        return verified

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
        research_observation_contract: str | None = None,
    ) -> dict[str, Any]:
        from stage_center._raw_store_parts.transaction_publish import _RawStore_publish_body as _v4_impl
        if research_observation_contract is None:
            result = _v4_impl(globals(), self, trade_date=trade_date, stage_id=stage_id, market=market, source_id=source_id, source_status=source_status, rows=rows, cannot_confirm=cannot_confirm, source_evidence=source_evidence, requested_rows=requested_rows, missing_symbols=missing_symbols, window=window, cutoff_at=cutoff_at)
            context = _FUTU_RTD_OBSERVATION_CONTEXT.get()
            return _mark_futu_rtd_observation_result(result) if context and context.get("enabled") is True else result
        with futu_rtd_observation_scope(
            research_observation_contract=research_observation_contract,
            trade_date=trade_date,
            stage_id=stage_id,
            market=market,
            source_id=source_id,
            source_status=source_status,
            rows=rows,
            requested_rows=requested_rows,
            missing_symbols=missing_symbols,
            cannot_confirm=cannot_confirm,
            source_evidence=source_evidence,
            window=window,
            cutoff_at=cutoff_at,
        ):
            result = _v4_impl(globals(), self, trade_date=trade_date, stage_id=stage_id, market=market, source_id=source_id, source_status=source_status, rows=rows, cannot_confirm=cannot_confirm, source_evidence=source_evidence, requested_rows=requested_rows, missing_symbols=missing_symbols, window=window, cutoff_at=cutoff_at)
            return _mark_futu_rtd_observation_result(result)

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
    research_observation_contract: str | None = None,
) -> dict[str, Any]:
    from stage_center._raw_store_parts.transaction_publish import _publish_raw_artifact_body as _v4_impl
    if research_observation_contract is None:
        return _v4_impl(globals(), root, trade_date=trade_date, stage_id=stage_id, market=market, source_id=source_id, source_status=source_status, rows=rows, cannot_confirm=cannot_confirm, source_evidence=source_evidence, requested_rows=requested_rows, missing_symbols=missing_symbols, window=window, cutoff_at=cutoff_at)
    with futu_rtd_observation_scope(
        research_observation_contract=research_observation_contract,
        trade_date=trade_date,
        stage_id=stage_id,
        market=market,
        source_id=source_id,
        source_status=source_status,
        rows=rows,
        requested_rows=requested_rows,
        missing_symbols=missing_symbols,
        cannot_confirm=cannot_confirm,
        source_evidence=source_evidence,
        window=window,
        cutoff_at=cutoff_at,
    ):
        return _v4_impl(globals(), root, trade_date=trade_date, stage_id=stage_id, market=market, source_id=source_id, source_status=source_status, rows=rows, cannot_confirm=cannot_confirm, source_evidence=source_evidence, requested_rows=requested_rows, missing_symbols=missing_symbols, window=window, cutoff_at=cutoff_at)
