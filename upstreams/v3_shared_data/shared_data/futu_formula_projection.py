"""Read-only loader for the explicitly requested Futu QFQ chart profile.

The profile is a derived view of the current selector panel. It is deliberately
limited to the captured as-of date and factor-covered symbols; it is not a new
market-data authority and is not certified for historical PIT use.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

PROFILE_ID = "FUTU_QFQ_ASOF"
PROFILE_SCHEMA = "FUTU_QFQ_ASOF_PROFILE_V1"
PROFILE_FILE = "futu_formula_profile.json"
CACHE_FILE = "futu_qfq_derived_cache.parquet"
PINNED_FORMULA_SHA256 = "074a038699eae84d093602ee6df551b5279368c5800ad78067902a496c990258"
PINNED_USER_FORMULA_SHA256 = "924ab78f0adb0ee0705e41d7824282f40ec275a97da532ffee5b61e29d2925e6"
PROFILE_SUPPORTED_COLUMNS = (
    "open", "high", "low", "close", "BBI", "zge_white_line",
    "zge_yellow_line", "ma60",
)
PRICE_COLUMNS = ("open", "high", "low", "close")
_FILE_HASH_CACHE: dict[str, tuple[int, int, str]] = {}


class FutuProfileError(ValueError):
    """A fail-closed profile, identity, or projection error."""


def _normalise_date(value: Any, field: str) -> str:
    text = str(value).replace("-", "")[:8]
    if not re.fullmatch(r"\d{8}", text):
        raise FutuProfileError(f"INVALID_{field.upper()}: {value!r}")
    return text


def _json_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: str | Path) -> str:
    file_path = Path(path).resolve(strict=True)
    stat = file_path.stat()
    cache_key = str(file_path)
    cached = _FILE_HASH_CACHE.get(cache_key)
    fingerprint = (stat.st_size, stat.st_mtime_ns)
    if cached is not None and cached[:2] == fingerprint:
        return cached[2]
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    result = digest.hexdigest()
    _FILE_HASH_CACHE[cache_key] = (stat.st_size, stat.st_mtime_ns, result)
    return result


def apply_forward_factors(
    frame,
    events: Sequence[dict[str, Any]],
    asof: str,
    price_columns: Sequence[str] = PRICE_COLUMNS,
):
    """Apply Futu A*P+B to pre-event bars, in ascending ex-dividend order."""
    import pandas as pd

    asof_date = _normalise_date(asof, "asof")
    if "trade_date" not in frame:
        raise FutuProfileError("MISSING_TRADE_DATE")
    dates = frame["trade_date"].map(lambda value: _normalise_date(value, "trade_date"))
    ordered = sorted(events, key=lambda event: _normalise_date(event.get("ex_div_date"), "ex_div_date"))
    seen: set[str] = set()
    result = frame.loc[dates.le(asof_date)].copy()
    dates = dates.loc[result.index]
    for event in ordered:
        ex_date = _normalise_date(event.get("ex_div_date"), "ex_div_date")
        if ex_date in seen:
            raise FutuProfileError(f"DUPLICATE_FACTOR_EVENT: {ex_date}")
        seen.add(ex_date)
        if ex_date > asof_date:
            continue
        try:
            factor_a = float(event["factor_a"])
            factor_b = float(event["factor_b"])
        except (KeyError, TypeError, ValueError) as exc:
            raise FutuProfileError(f"INVALID_FACTOR_EVENT: {event!r}") from exc
        if not math.isfinite(factor_a) or not math.isfinite(factor_b) or factor_a <= 0:
            raise FutuProfileError(f"INVALID_FACTOR_EVENT: {event!r}")
        mask = dates.lt(ex_date) & dates.le(asof_date)
        for column in price_columns:
            if column not in result:
                raise FutuProfileError(f"MISSING_PRICE_COLUMN: {column}")
            result.loc[mask, column] = (
                pd.to_numeric(result.loc[mask, column], errors="raise") * factor_a + factor_b
            )
    for column in price_columns:
        result[column] = pd.to_numeric(result[column], errors="raise").round(2)
    return result


def _profile_paths(profile_dir: str | Path) -> tuple[Path, Path]:
    directory = Path(profile_dir).resolve()
    profile_path = directory / PROFILE_FILE
    metadata_path = directory / CACHE_FILE
    return profile_path, metadata_path


def _factor_events(profile: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    factor_meta = profile.get("factor_metadata")
    expected = profile.get("factor_metadata_sha256")
    if not isinstance(factor_meta, dict) or not isinstance(expected, str):
        raise FutuProfileError("MISSING_FACTOR_METADATA")
    if _json_sha256(factor_meta) != expected:
        raise FutuProfileError("FACTOR_METADATA_SHA256_MISMATCH")
    symbols = factor_meta.get("symbols")
    if not isinstance(symbols, dict) or not symbols:
        raise FutuProfileError("MISSING_FACTOR_SYMBOLS")
    result: dict[str, list[dict[str, Any]]] = {}
    for code, entry in symbols.items():
        events = entry.get("events") if isinstance(entry, dict) else None
        if not isinstance(events, list) or not events:
            raise FutuProfileError(f"MISSING_FACTOR_EVENTS: {code}")
        dates = [_normalise_date(event.get("ex_div_date"), "ex_div_date") for event in events]
        if dates != sorted(dates) or len(dates) != len(set(dates)):
            raise FutuProfileError(f"UNSORTED_OR_DUPLICATE_FACTOR_EVENTS: {code}")
        result[str(code)] = events
    return result


def validate_profile(
    profile_dir: str | Path,
    panel_path: str | Path,
    asof: Optional[str],
) -> dict[str, Any]:
    """Validate the immutable profile, source identity, factors, and cache."""
    if asof is None:
        raise FutuProfileError("FUTU_PROFILE_REQUIRES_EXPLICIT_ASOF")
    requested_asof = _normalise_date(asof, "asof")
    profile_path, cache_path = _profile_paths(profile_dir)
    if not profile_path.is_file() or not cache_path.is_file():
        raise FutuProfileError("FUTU_PROFILE_MISSING")
    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FutuProfileError("FUTU_PROFILE_INVALID_JSON") from exc
    if profile.get("schema") != PROFILE_SCHEMA or profile.get("profile_id") != PROFILE_ID:
        raise FutuProfileError("FUTU_PROFILE_IDENTITY_MISMATCH")
    manifest_sha = profile.get("manifest_sha256")
    manifest_payload = {key: value for key, value in profile.items() if key != "manifest_sha256"}
    if not isinstance(manifest_sha, str) or _json_sha256(manifest_payload) != manifest_sha:
        raise FutuProfileError("FUTU_PROFILE_MANIFEST_SHA256_MISMATCH")
    if profile.get("formula_source_sha256") != PINNED_FORMULA_SHA256:
        raise FutuProfileError("PINNED_FORMULA_SHA256_MISMATCH")
    if profile.get("user_formula_sha256") != PINNED_USER_FORMULA_SHA256:
        raise FutuProfileError("USER_FORMULA_SHA256_MISMATCH")
    if profile.get("chart_only") is not True or profile.get("historical_pit_certified") is not False:
        raise FutuProfileError("FUTU_PROFILE_SCOPE_MISMATCH")
    profile_asof = _normalise_date(profile.get("asof_date"), "profile_asof")
    if requested_asof > profile_asof:
        raise FutuProfileError("FUTU_PROFILE_FUTURE_ASOF")
    if requested_asof != profile_asof:
        raise FutuProfileError("FUTU_PROFILE_ASOF_UNSUPPORTED")
    if profile.get("source_panel_asof") != profile_asof:
        raise FutuProfileError("SOURCE_PANEL_ASOF_MISMATCH")
    if profile.get("derived_cache_file") != CACHE_FILE:
        raise FutuProfileError("DERIVED_CACHE_FILE_MISMATCH")
    source_path = Path(panel_path).resolve(strict=True)
    if str(source_path) != profile.get("source_panel_path"):
        raise FutuProfileError("SOURCE_PANEL_PATH_MISMATCH")
    expected_panel_sha = profile.get("source_panel_sha256")
    if not isinstance(expected_panel_sha, str) or sha256_file(source_path) != expected_panel_sha:
        raise FutuProfileError("SOURCE_PANEL_SHA256_MISMATCH")
    expected_cache_sha = profile.get("derived_cache_sha256")
    if not isinstance(expected_cache_sha, str) or sha256_file(cache_path) != expected_cache_sha:
        raise FutuProfileError("DERIVED_CACHE_SHA256_MISMATCH")
    supported = profile.get("supported_columns")
    if not isinstance(supported, list) or tuple(supported) != PROFILE_SUPPORTED_COLUMNS:
        raise FutuProfileError("FUTU_PROFILE_SUPPORTED_COLUMNS_MISMATCH")
    events_by_code = _factor_events(profile)
    if profile.get("factor_basis") != "FUTU_GET_REHAB_FORWARD_FACTOR_A_B":
        raise FutuProfileError("FUTU_FACTOR_BASIS_MISMATCH")
    factor_sources = profile.get("factor_source_csv_sha256")
    factor_meta = profile["factor_metadata"]
    if factor_meta.get("asof_cutoff") != profile_asof:
        raise FutuProfileError("FUTU_FACTOR_ASOF_MISMATCH")
    if not isinstance(factor_sources, dict) or set(factor_sources) != set(events_by_code):
        raise FutuProfileError("FUTU_FACTOR_SOURCE_HASH_COVERAGE_MISMATCH")
    capture_sha = factor_meta.get("source_capture_sha256")
    if not isinstance(capture_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", capture_sha):
        raise FutuProfileError("FUTU_FACTOR_CAPTURE_HASH_INVALID")
    for code, entry in factor_meta["symbols"].items():
        expected_csv_sha = entry.get("source_csv_sha256")
        if not isinstance(expected_csv_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_csv_sha):
            raise FutuProfileError(f"FUTU_FACTOR_SOURCE_HASH_INVALID: {code}")
        if not isinstance(entry.get("source_csv_path"), str) or not entry["source_csv_path"]:
            raise FutuProfileError(f"FUTU_FACTOR_SOURCE_PATH_MISSING: {code}")
        if factor_sources.get(code) != expected_csv_sha:
            raise FutuProfileError(f"FUTU_FACTOR_SOURCE_HASH_MISMATCH: {code}")
    if not profile.get("factor_observed_at"):
        raise FutuProfileError("FUTU_FACTOR_PROVENANCE_MISSING")
    return {
        "profile": profile,
        "profile_path": str(profile_path),
        "profile_sha256": sha256_file(profile_path),
        "cache_path": str(cache_path),
        "cache_sha256": expected_cache_sha,
        "source_panel_path": str(source_path),
        "source_panel_sha256": expected_panel_sha,
        "factor_events_by_code": events_by_code,
        "asof_date": profile_asof,
    }


def profile_metadata(profile_data: dict[str, Any]) -> dict[str, Any]:
    profile = profile_data["profile"]
    return {
        "profile_id": PROFILE_ID,
        "profile_kind": "CHART_DERIVATIVE",
        "authoritative_source": False,
        "price_basis": "FUTU_QFQ_ASOF",
        "asof_date": profile_data["asof_date"],
        "factor_basis": profile["factor_basis"],
        "factor_observed_at": profile["factor_observed_at"],
        "factor_metadata_sha256": profile["factor_metadata_sha256"],
        "factor_source_csv_sha256": dict(profile["factor_source_csv_sha256"]),
        "factor_source_csv_paths": {
            code: entry["source_csv_path"]
            for code, entry in profile["factor_metadata"]["symbols"].items()
        },
        "source_panel_path": profile_data["source_panel_path"],
        "source_panel_sha256": profile_data["source_panel_sha256"],
        "derived_cache_path": profile_data["cache_path"],
        "derived_cache_sha256": profile_data["cache_sha256"],
        "formula_source_sha256": profile["formula_source_sha256"],
        "user_formula_sha256": profile["user_formula_sha256"],
        "supported_columns": list(PROFILE_SUPPORTED_COLUMNS),
        "volume_basis": "RAW_SELECTOR_UNADJUSTED",
        "volume_dependent_label_parity": "NOT_CLAIMED",
        "chart_only": True,
        "historical_pit_certified": False,
        "pit_status": "CANNOT_CONFIRM_HISTORICAL_AVAILABILITY",
    }


def _filter_codes(filters: Any) -> Optional[set[str]]:
    if filters is None:
        return None
    if not isinstance(filters, (list, tuple)):
        raise FutuProfileError("UNSUPPORTED_FUTU_PROFILE_FILTERS")
    selected: Optional[set[str]] = None
    for item in filters:
        if not isinstance(item, (list, tuple)) or len(item) != 3:
            raise FutuProfileError("UNSUPPORTED_FUTU_PROFILE_FILTERS")
        column, operation, value = item
        if column != "ts_code":
            if column == "trade_date":
                continue
            raise FutuProfileError(f"UNSUPPORTED_FUTU_PROFILE_FILTER_COLUMN: {column}")
        if operation in ("=", "=="):
            values = {str(value)}
        elif str(operation).lower() in ("in", "is in"):
            values = set(map(str, value))
        else:
            raise FutuProfileError("UNSUPPORTED_FUTU_PROFILE_CODE_FILTER")
        selected = values if selected is None else selected.intersection(values)
    return selected


def load_profile_rows(
    profile_data: dict[str, Any],
    columns: Optional[Sequence[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    ts_codes: Optional[Iterable[str]] = None,
    filters: Any = None,
):
    """Read only cached chart columns; never fall back to RAW or fetch quotes."""
    import pandas as pd

    filter_codes = _filter_codes(filters)
    requested_codes = set(map(str, ts_codes)) if ts_codes is not None else filter_codes
    if requested_codes is None or not requested_codes:
        raise FutuProfileError("FUTU_PROFILE_REQUIRES_EXPLICIT_TSCODE")
    if filter_codes is not None:
        requested_codes.intersection_update(filter_codes)
    if not requested_codes:
        raise FutuProfileError("FUTU_PROFILE_EMPTY_TSCODE_SELECTION")
    events_by_code = profile_data["factor_events_by_code"]
    missing_factors = sorted(requested_codes - set(events_by_code))
    if missing_factors:
        raise FutuProfileError(f"FUTU_PROFILE_MISSING_FACTOR_COVERAGE: {missing_factors}")
    if columns is None:
        read_columns = ["ts_code", "trade_date", *PROFILE_SUPPORTED_COLUMNS]
    else:
        requested_columns = list(dict.fromkeys(map(str, columns)))
        unsupported = sorted(set(requested_columns) - set(PROFILE_SUPPORTED_COLUMNS))
        if unsupported:
            raise FutuProfileError(f"FUTU_PROFILE_UNSUPPORTED_COLUMNS: {unsupported}")
        read_columns = list(dict.fromkeys(["ts_code", "trade_date", *requested_columns]))
    cache_path = Path(profile_data["cache_path"])
    frame = pd.read_parquet(cache_path, columns=read_columns)
    frame["ts_code"] = frame["ts_code"].astype(str)
    frame["trade_date"] = frame["trade_date"].map(lambda value: _normalise_date(value, "trade_date"))
    frame = frame[frame["ts_code"].isin(requested_codes)].copy()
    if frame.duplicated(["ts_code", "trade_date"]).any():
        raise FutuProfileError("FUTU_PROFILE_DUPLICATE_KEY")
    absent_codes = sorted(requested_codes - set(frame["ts_code"]))
    if absent_codes:
        raise FutuProfileError(f"FUTU_PROFILE_MISSING_STOCK_CACHE: {absent_codes}")
    asof_date = profile_data["asof_date"]
    exact_asof = set(frame.loc[frame["trade_date"].eq(asof_date), "ts_code"])
    stale_codes = sorted(requested_codes - exact_asof)
    if stale_codes:
        raise FutuProfileError(f"FUTU_PROFILE_STALE_OR_MISSING_ASOF: {stale_codes}")
    if end_date is not None and _normalise_date(end_date, "end_date") > asof_date:
        raise FutuProfileError("FUTU_PROFILE_FUTURE_END_DATE")
    if start_date is not None:
        frame = frame[frame["trade_date"].ge(_normalise_date(start_date, "start_date"))]
    selected_end = asof_date if end_date is None else _normalise_date(end_date, "end_date")
    frame = frame[frame["trade_date"].le(selected_end)]
    for item in filters or ():
        if item[0] != "trade_date":
            continue
        operation, value = item[1], _normalise_date(item[2], "filter_date")
        if operation in ("=", "=="):
            frame = frame[frame["trade_date"].eq(value)]
        elif operation == ">=":
            frame = frame[frame["trade_date"].ge(value)]
        elif operation == ">":
            frame = frame[frame["trade_date"].gt(value)]
        elif operation == "<=":
            frame = frame[frame["trade_date"].le(value)]
        elif operation == "<":
            frame = frame[frame["trade_date"].lt(value)]
        else:
            raise FutuProfileError("UNSUPPORTED_FUTU_PROFILE_DATE_FILTER")
    frame = frame.sort_values(["ts_code", "trade_date"], kind="stable").reset_index(drop=True)
    frame.attrs["profile_metadata"] = profile_metadata(profile_data)
    return frame


def validate_profile_for_panel(
    profile_dir: str | Path,
    panel_path: str | Path,
    asof: Optional[str],
) -> dict[str, Any]:
    """Public helper used by the selector reader for metadata-only calls."""
    return validate_profile(profile_dir=profile_dir, panel_path=panel_path, asof=asof)
