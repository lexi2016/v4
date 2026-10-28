"""Quote-only adjustment metadata cache for the original daily producer.

No historical bar API, subscription, account or trade context is used here.
Immutable response bytes plus separately dated query receipts allow checkpoint
resume; successful empty responses are distinct from unsupported/error states.
"""
from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import json
import math
from pathlib import Path
import struct
import time
from typing import Any, Callable
from zoneinfo import ZoneInfo

import hashlib
import os
import tempfile


class QfqGateError(RuntimeError):
    pass


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _source(ref: dict, *, owner: str) -> Path:
    path = Path(ref["path"])
    if not path.is_absolute() or not path.is_file() or sha(path) != ref["sha256"]:
        raise QfqGateError(f"SOURCE_BINDING_FAILED:{owner}:{path}")
    return path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _capture_date() -> int:
    return int(datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d"))


def _fresh(item: dict, target: int, max_age_seconds: float) -> bool:
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(item["queried_at"])).total_seconds()
        return item.get("asof_date") == target and item.get("capture_date") == _capture_date() and 0 <= age <= max_age_seconds
    except (KeyError, ValueError, TypeError):
        return False


def _records(frame: Any) -> list[dict]:
    # pandas' JSON conversion handles native dates, numpy scalars and NaN
    # without allowing nonstandard NaN bytes into the immutable input cache.
    if hasattr(frame, "to_json"):
        return json.loads(frame.to_json(orient="records", date_format="iso", double_precision=15))
    return [dict(row) for row in frame]


def _event_rows(rows: list[dict], target: int, start: int) -> list[dict]:
    events = []
    for row in rows:
        text = str(row.get("ex_div_date", ""))
        digits = "".join(c for c in text if c.isdigit())
        if len(digits) < 8:
            raise QfqGateError("FUTU_REHAB_EX_DATE_INVALID")
        date = int(digits[:8])
        if date > target or date <= start:
            continue
        try:
            a, b = float(row["forward_adj_factorA"]), float(row["forward_adj_factorB"])
            volume_a = float(row["backward_adj_factorA"])
        except (KeyError, TypeError, ValueError) as exc:
            raise QfqGateError(f"FUTU_REHAB_AFFINE_MISSING:{date}") from exc
        if not all(math.isfinite(v) for v in (a, b, volume_a)) or min(a, volume_a) <= 0:
            raise QfqGateError(f"FUTU_REHAB_AFFINE_INVALID:{date}")
        events.append(dict(ex_date=date, a=a, b=b, volume_a=volume_a))
    events.sort(key=lambda e: e["ex_date"])
    if len({e["ex_date"] for e in events}) != len(events):
        raise QfqGateError("FUTU_REHAB_DUPLICATE_EX_DATE")
    return events


def _collect_metadata_owned(codes: list[str], *, cache_root: Path, target: int,
                     client_factory: Callable[[], Any] | None = None,
                     min_interval: float = 0.2, retries: int = 2,
                     sleep: Callable[[float], None] = time.sleep,
                     monotonic: Callable[[], float] = time.monotonic,
                     force_refresh: bool = False, max_age_seconds: float = 86400) -> dict:
    """Bounded serial metadata I/O; compute stage can independently use workers.

    The default cadence is conservative and configurable. Error details and
    return codes are retained verbatim as data, never interpreted as actions.
    Caller holds the original producer publication/ownership lock.
    """
    if min_interval < 0 or retries not in (0, 1, 2) or not 0 < max_age_seconds <= 86400:
        raise QfqGateError("FACTOR_RATE_OR_RETRY_CONFIG_INVALID")
    root = cache_root / str(target)
    root.mkdir(parents=True, exist_ok=True)
    checkpoint = root / "checkpoint.json"
    state = json.loads(checkpoint.read_text()) if checkpoint.is_file() else dict(asof_date=target, symbols={})
    if state.get("asof_date") != target:
        raise QfqGateError("FACTOR_CHECKPOINT_ASOF_MISMATCH")
    state.update(status="RUNNING", started_at=_now())
    for field in ("completed_at", "finished_at", "counts"):
        state.pop(field, None)
    _json(checkpoint, state)
    if client_factory is None:
        from futu import OpenQuoteContext
        client_factory = lambda: OpenQuoteContext(host="127.0.0.1", port=11111)
    client = None
    last_query = None
    try:
        for code in sorted(set(codes)):
            prior = state["symbols"].get(code, {})
            if not force_refresh and prior.get("status") in ("OK", "EMPTY") and _fresh(prior, target, max_age_seconds):
                _source(prior["response"], owner=code)
                continue
            exchange = code.rsplit(".", 1)[-1]
            if exchange not in ("SH", "SZ", "BJ"):
                state["symbols"][code] = dict(status="UNSUPPORTED_MARKET", market=exchange, queried_at=None, asof_date=target, capture_date=_capture_date(),
                                                   reason="FUTU_REHAB_MARKET_NOT_SUPPORTED_BY_ADAPTER")
                _json(checkpoint, state)
                continue
            if client is None:
                try:
                    client = client_factory()
                    state.pop("context_error", None)
                except Exception as exc:
                    state["context_error"] = dict(observed_at=_now(), error=str(exc))
                    _json(checkpoint, state)
                    raise
            futu_code = exchange + "." + code.split(".", 1)[0]
            for attempt in range(retries + 1):
                if last_query is not None:
                    pause = min_interval - (monotonic() - last_query)
                    if pause > 0:
                        sleep(pause)
                last_query = monotonic()
                queried_at = _now()
                common = dict(queried_at=queried_at, asof_date=target, capture_date=_capture_date())
                state["symbols"][code] = dict(status="QUERYING", attempt=attempt + 1, **common)
                _json(checkpoint, state)
                try:
                    ret, data = client.get_rehab(futu_code)
                    if int(ret) != 0:
                        error_response = dict(source="Futu OpenD get_rehab", code=futu_code, return_code=int(ret), error=str(data))
                        error_path = root / "responses" / (canonical_sha(error_response) + ".json")
                        if not error_path.exists():
                            _json(error_path, error_response)
                        error_ref = dict(path=str(error_path), sha256=sha(error_path))
                        if exchange == "BJ" and "format of code BJ." in str(data) and "is wrong" in str(data):
                            state["symbols"][code] = dict(status="UNSUPPORTED_MARKET", response=error_ref, error=str(data),
                                                               attempts=attempt + 1, return_code=int(ret), **common)
                            break
                        raise QfqGateError(f"FUTU_GET_REHAB_RETURN_{ret}:{data}")
                    rows = _records(data)
                    # Validate the protocol even though full event selection
                    # waits for the bound raw-history start date.
                    _event_rows(rows, target, 19000101)
                    response = dict(source="Futu OpenD get_rehab", code=futu_code, return_code=int(ret), rows=rows)
                    response_path = root / "responses" / (canonical_sha(response) + ".json")
                    if not response_path.exists():
                        _json(response_path, response)
                    elif canonical_sha(json.loads(response_path.read_text())) != canonical_sha(response):
                        raise QfqGateError(f"IMMUTABLE_FACTOR_RESPONSE_CONFLICT:{response_path}")
                    ref = dict(path=str(response_path), sha256=sha(response_path))
                    state["symbols"][code] = dict(status="OK" if rows else "EMPTY", **common,
                                                       attempts=attempt + 1, response=ref, row_count=len(rows))
                    break
                except Exception as exc:
                    state["symbols"][code] = dict(status="ERROR", **common, attempts=attempt + 1, error=str(exc))
                    _json(checkpoint, state)
                    if attempt < retries:
                        sleep(min(30.0, 2.0 ** attempt))
            _json(checkpoint, state)
        counts = {name: sum(state["symbols"].get(code, {}).get("status") == name for code in set(codes))
                  for name in ("OK", "EMPTY", "UNSUPPORTED_MARKET", "ERROR", "QUERYING")}
        state["counts"] = counts
        state["requested_count"] = len(set(codes))
        state["requested_codes_sha256"] = canonical_sha(sorted(set(codes)))
        state["status"] = "FAILED" if counts["ERROR"] or counts["QUERYING"] else ("PARTIAL_EXPECTED_UNSUPPORTED" if counts["UNSUPPORTED_MARKET"] else "READY")
        state["finished_at"] = _now()
        state.pop("completed_at", None)
        if state["status"] == "READY":
            state["completed_at"] = state["finished_at"]
        _json(checkpoint, state)
        return state
    except BaseException as exc:
        state.update(status="INTERRUPTED" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "FAILED",
                     finished_at=_now(), stop_reason=str(exc))
        _json(checkpoint, state)
        raise
    finally:
        if client is not None:
            client.close()


def collect_metadata(codes: list[str], *, cache_root: Path, target: int, **options) -> dict:
    """Unique cache owner; terminal status must be inspected by the caller."""
    cache_root.mkdir(parents=True, exist_ok=True)
    with (cache_root / ".futu_rehab_owner.lock").open("a+b") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise QfqGateError("FACTOR_METADATA_OWNER_ALREADY_ACTIVE") from exc
        try:
            return _collect_metadata_owned(codes, cache_root=cache_root, target=target, **options)
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)

