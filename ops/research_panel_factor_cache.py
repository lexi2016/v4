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


# Accepted original lifecycle projection; changing it requires a new source contract.
_LIFECYCLE_ASSET_SHA = "7403a9954d9ae915dcb99cbba03a5dd19d6b85152396c5ff0634e286cdd9357b"
_LIFECYCLE_REASON = "VERIFIED_DELISTED_NO_CURRENT_BARS"


def _sync_prequery_rows(ref: dict | None, target: int) -> dict[str, dict]:
    if ref is None:
        return {}
    summary = json.loads(_source(ref, owner="original sync prequery authority").read_text())
    if (str(summary.get("target_date")) != str(target) or not summary.get("target_keys")
            or summary.get("RESEARCH_ONLY") is not True
            or any(summary.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))):
        raise QfqGateError("SOP_PREQUERY_SYNC_TARGET_OR_SAFETY_INVALID")
    markets = {0: "SZ", 1: "SH", 2: "BJ"}
    def identity(row):
        suffix = markets.get(row.get("market")) if type(row.get("market")) is int else None
        symbol = str(row.get("symbol", ""))
        return symbol.zfill(6) + "." + suffix if suffix and symbol.isdigit() and len(symbol) <= 6 else None
    keys = {identity(row) for row in summary["target_keys"] if isinstance(row, dict)}
    result = {}
    for row in summary.get("symbol_reconciliation", []):
        if not isinstance(row, dict):
            continue
        code = identity(row)
        if code in keys and code is not None:
            if code in result:
                raise QfqGateError("SOP_PREQUERY_DUPLICATE_IDENTITY")
            result[code] = row
    return result


def _verified_sop_skip(code: str, row: dict | None, target: int, sync_ref: dict | None) -> dict | None:
    if not row or (row.get("classification"), row.get("quarantine"), row.get("target_date_ready"),
                   row.get("lifecycle_skip"), row.get("reason_code")) != (
                       "QUARANTINED", True, False, True, _LIFECYCLE_REASON):
        return None
    fact = row.get("lifecycle_fact")
    if (not isinstance(fact, dict) or fact.get("ts_code") != code or fact.get("verified") is not True
            or fact.get("requires_recent_listed_A_share_bars") is not False
            or row.get("lifecycle_asset_sha256") != _LIFECYCLE_ASSET_SHA
            or fact.get("accepted_review_literal") != "PASS_SINGLE_STOCK_TARGET_WINDOW_LIFECYCLE_CLASSIFICATION"
            or row.get("records_written") != 0):
        return None
    try:
        effective = fact["delisting_effective_date"]
        datetime.strptime(effective, "%Y%m%d")
        if int(effective) > target:
            return None
        raw = dict(path=row["path"], sha256=row["source_sha256_after"])
        _source(raw, owner="original lifecycle raw identity")
        for name in ("accepted_review_ref", "accepted_case_result_ref"):
            _source(fact[name], owner="accepted original lifecycle SOP")
    except (KeyError, TypeError, ValueError, OSError, QfqGateError):
        return None
    return dict(status="SOP_SKIPPED", reason=_LIFECYCLE_REASON, asof_date=target,
                queried_at=None, capture_date=None, provider_invoked=False,
                source_sync=sync_ref, original_sync_row=row,
                lifecycle_effective_date=effective, classification="QUARANTINED")


def _prior_bj_capabilities(cache_root: Path, target: int) -> tuple[dict, dict | None]:
    # Exactly one prior checkpoint, loaded once. Never audit every past day.
    candidates = [p / "checkpoint.json" for p in cache_root.iterdir()
                  if p.is_dir() and len(p.name) == 8 and p.name.isdigit()
                  and int(p.name) < target and (p / "checkpoint.json").is_file()] if cache_root.exists() else []
    if not candidates:
        return {}, None
    path = max(candidates, key=lambda p: p.parent.name)
    try:
        raw = path.read_bytes()
        state = json.loads(raw)
        if state.get("asof_date") != int(path.parent.name) or not isinstance(state.get("symbols"), dict):
            return {}, None
        return state["symbols"], dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest())
    except (OSError, ValueError, TypeError):
        return {}, None


def _known_prior_bj_route(code: str, prior: dict, checkpoint_ref: dict | None, target: int) -> dict | None:
    if (not code.endswith(".BJ") or not checkpoint_ref or prior.get("status") != "UNSUPPORTED_MARKET"):
        return None
    try:
        evidence = prior.get("capability_evidence")
        original = evidence.get("original") if isinstance(evidence, dict) else prior
        if not isinstance(original, dict):
            return None
        if isinstance(evidence, dict):
            protocol = dict(provider="Futu OpenD get_rehab", code_format="BJ.SIX_DIGITS",
                            return_code=-1, error_class="BJ_CODE_FORMAT_IS_WRONG")
            if evidence.get("protocol") != protocol or evidence.get("protocol_sha256") != canonical_sha(protocol):
                return None
        response_ref = original["response"]
        response = json.loads(_source(response_ref, owner="known prior BJ capability").read_text())
        error = response.get("error")
        if (response.get("source") != "Futu OpenD get_rehab" or response.get("code") != "BJ." + code[:6]
                or response.get("return_code") != -1 or not isinstance(error, str)
                or "format of code BJ." not in error or "is wrong" not in error
                or original.get("error") != error):
            return None
    except (KeyError, OSError, ValueError, TypeError, QfqGateError):
        return None
    original = {k: original.get(k) for k in ("queried_at", "capture_date", "asof_date", "response", "error")}
    protocol = dict(provider="Futu OpenD get_rehab", code_format="BJ.SIX_DIGITS",
                    return_code=-1, error_class="BJ_CODE_FORMAT_IS_WRONG")
    return dict(status="UNSUPPORTED_MARKET", reason="KNOWN_PRIOR_CAPABILITY_ROUTE_TO_EXISTING_TDX_FALLBACK",
                asof_date=target, queried_at=None, capture_date=None, provider_invoked=False,
                capability_evidence=dict(checkpoint=checkpoint_ref, original=original,
                                         protocol=protocol, protocol_sha256=canonical_sha(protocol)))


def _collect_metadata_owned(codes: list[str], *, cache_root: Path, target: int,
                     client_factory: Callable[[], Any] | None = None,
                     min_interval: float = 0.2, retries: int = 2,
                     sleep: Callable[[float], None] = time.sleep,
                     monotonic: Callable[[], float] = time.monotonic,
                     force_refresh: bool = False, max_age_seconds: float = 86400,
                     prequery_sync_ref: dict | None = None) -> dict:
    """Bounded serial metadata I/O; compute stage can independently use workers.

    The default cadence is conservative and configurable. Error details and
    return codes are retained verbatim as data, never interpreted as actions.
    Caller holds the original producer publication/ownership lock.
    """
    if min_interval < 0 or retries not in (0, 1, 2) or not 0 < max_age_seconds <= 86400:
        raise QfqGateError("FACTOR_RATE_OR_RETRY_CONFIG_INVALID")
    sync_rows = _sync_prequery_rows(prequery_sync_ref, target)
    prior_bj, prior_bj_ref = (_prior_bj_capabilities(cache_root, target)
                              if any(code.endswith(".BJ") and code in sync_rows for code in codes) else ({}, None))
    root = cache_root / str(target)
    root.mkdir(parents=True, exist_ok=True)
    checkpoint = root / "checkpoint.json"
    state = json.loads(checkpoint.read_text()) if checkpoint.is_file() else dict(asof_date=target, symbols={})
    if state.get("asof_date") != target:
        raise QfqGateError("FACTOR_CHECKPOINT_ASOF_MISMATCH")
    state.update(status="RUNNING", started_at=_now(), provider_call_count=0, provider_identity_count=0,
                 sop_skipped_count=0, known_prior_capability_count=0)
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
            decision = _verified_sop_skip(code, sync_rows.get(code), target, prequery_sync_ref)
            if decision is not None:
                state["symbols"][code] = decision
                state["sop_skipped_count"] += 1
                _json(checkpoint, state)
                continue
            if code.endswith(".BJ") and code in sync_rows:
                try:
                    row = sync_rows[code]
                    _source(dict(path=row["path"], sha256=row["source_sha256_after"]), owner="original BJ raw identity")
                    bj_raw_valid = True
                except (KeyError, TypeError, ValueError, OSError, QfqGateError):
                    bj_raw_valid = False
                decision = _known_prior_bj_route(code, prior_bj.get(code, {}), prior_bj_ref, target) if bj_raw_valid else None
                if decision is not None:
                    state["symbols"][code] = decision
                    state["known_prior_capability_count"] += 1
                    _json(checkpoint, state)
                    continue
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
            state["provider_identity_count"] += 1
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
                    state["provider_call_count"] += 1
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
                  for name in ("OK", "EMPTY", "UNSUPPORTED_MARKET", "SOP_SKIPPED", "ERROR", "QUERYING")}
        state["counts"] = counts
        state["requested_count"] = len(set(codes))
        state["requested_codes_sha256"] = canonical_sha(sorted(set(codes)))
        state["status"] = "FAILED" if counts["ERROR"] or counts["QUERYING"] else ("PARTIAL_EXPECTED_EXCLUSIONS" if counts["SOP_SKIPPED"] else ("PARTIAL_EXPECTED_UNSUPPORTED" if counts["UNSUPPORTED_MARKET"] else "READY"))
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

