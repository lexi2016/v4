"""V3.5-owned A-share TDX daily synchronizer.

The seed implementation is imported from the read-only research-panel runtime
source ``tdxpy_daily_vipdoc_sync_v1.py``.  This release-owned module keeps the
binary ``.day`` codec but routes execution through the bounded reconnect core;
all run artifacts are written below the caller-provided state/runtime root.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import struct
import sys
import time
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

_HISTORY_BACKFILL_CLI = any(value == "--history-backfill-config" or value.startswith("--history-backfill-config=")
                            for value in sys.argv[1:])
if _HISTORY_BACKFILL_CLI:
    # The isolated CLI must reach its existing native-thread initializer
    # before any optional provider dependency can import numerical libraries.
    hq_hosts = ()
    TdxHq_API = None
else:
    try:  # Keep the validation/sync core importable in tests without pytdx.
        from pytdx.config.hosts import hq_hosts
        from pytdx.hq import TdxHq_API
    except ImportError:  # pragma: no cover - production installs pytdx.
        hq_hosts = ()
        TdxHq_API = None


TASK_NAME = "tdxpy_daily_vipdoc_sync_v1"
TDX_ROOT = Path(r"C:\new_tdx_mock")
DATA_ROOT = Path(__file__).resolve().parents[3]
RUN_TS = datetime.now().strftime("%Y%m%d_%H%M%S")
# Runtime output must be supplied by the state root, never written beside an
# immutable release module.  The macOS adapter overrides ``RUN_DIR`` with its
# receipt-root-owned path; the CLI uses this explicit environment override.
_RUN_ROOT = Path(os.environ.get("V35_A_SYNC_RUN_ROOT", "/tmp/v35-a-sync-runtime"))
RUN_DIR = _RUN_ROOT / RUN_TS

DAY_STRUCT = struct.Struct("<IIIIIfII")
MAX_CROSS_DAY_CLOSE_RATIO = 1.5
MARKET_BY_PREFIX = {
    "sh": 1,
    "sz": 0,
    "bj": 2,
}
EQUITY_CODE_PREFIXES_BY_MARKET = {
    "sh": ("600", "601", "603", "605", "688", "689"),
    "sz": ("000", "001", "002", "003", "300", "301", "302"),
    "bj": ("8", "9"),
}
DIR_BY_MARKET = {
    "a": [("sh", TDX_ROOT / "vipdoc" / "sh" / "lday"), ("sz", TDX_ROOT / "vipdoc" / "sz" / "lday")],
    "bj": [("bj", TDX_ROOT / "vipdoc" / "bj" / "lday")],
}


@dataclass(frozen=True)
class DailyTarget:
    """One immutable local A-share daily-file target."""

    code: str
    market: int
    path: Path


def _host_label(host: str, port: int) -> str:
    return f"{host}:{int(port)}"


def _connect_session(api: Any, host: str, port: int, timeout: float) -> None:
    connect = getattr(api, "connect", None)
    if not callable(connect):
        raise RuntimeError("TDX provider has no connect method")
    try:
        connected = connect(host, int(port), time_out=float(timeout))
    except TypeError:
        connected = connect(host, int(port), timeout=float(timeout))
    if connected is False:
        raise RuntimeError("connect returned false")


def _disconnect_session(api: Any) -> None:
    disconnect = getattr(api, "disconnect", None)
    if callable(disconnect):
        try:
            disconnect()
        except Exception:
            pass


def _fetch_valid_target_bars(
    api: Any,
    target: DailyTarget,
    target_date: int,
    previous_close: float | None,
    count: int,
) -> tuple[list[dict[str, Any]], str]:
    """Fetch one symbol and fail closed on empty, wrong-date, or continuity data."""

    bars = api.get_security_bars(9, target.market, target.code, 0, max(1, int(count)))
    if not bars:
        return [], "empty_response"
    normalized: list[dict[str, Any]] = []
    for raw in bars:
        ok, reason = valid_hq_bar(raw)
        if not ok:
            return [], f"invalid_bar:{reason}"
        normalized.append(dict(raw))
    normalized.sort(key=day_int)
    dates = [day_int(bar) for bar in normalized]
    if len(set(dates)) != len(dates) or any(right <= left for left, right in zip(dates, dates[1:])):
        return [], "continuity_non_monotonic"
    exact = [bar for bar in normalized if day_int(bar) == target_date]
    if not exact:
        return [], "target_date_missing"
    prior = float(previous_close) if previous_close and previous_close > 0 else None
    for bar in exact:
        close = float(bar["close"])
        if prior is not None:
            ratio = close / prior
            if ratio > MAX_CROSS_DAY_CLOSE_RATIO or ratio < 1.0 / MAX_CROSS_DAY_CLOSE_RATIO:
                return [], "continuity_close_ratio"
        prior = close
    # Only append records after the existing file's last date and never append
    # a future bar when the exact target-date gate is being evaluated.
    return [bar for bar in exact], "ok"


def run_sync(
    targets: Iterable[DailyTarget],
    *,
    target_date: str,
    api_factory: Any,
    host_candidates: Iterable[tuple[str, int]],
    count: int = 20,
    timeout: float = 1.5,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Synchronize A daily files with bounded host failover.

    A malformed response invalidates only the symbol currently being fetched.
    The connection is dropped, the next host is opened, and that symbol is
    retried once per remaining host.  Previously successful symbols are never
    replayed and a failed symbol never mutates its original file.
    """

    target_text = str(target_date).replace("-", "").replace("/", "")
    if len(target_text) != 8 or not target_text.isdigit():
        raise ValueError(f"invalid target date: {target_date!r}")
    try:
        datetime.strptime(target_text, "%Y%m%d")
    except ValueError as error:
        raise ValueError(f"invalid target date: {target_date!r}") from error
    target_int = int(target_text)
    target_list = list(targets)
    hosts = [(str(host), int(port)) for host, port in host_candidates]
    if not hosts:
        raise ValueError("TDX host candidates are empty")
    by_symbol: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    api: Any | None = None
    host_position = -1
    host_info: tuple[str, int] | None = None
    last_host_attempted: tuple[str, int] | None = None

    def open_next_host() -> tuple[Any, tuple[str, int]]:
        nonlocal host_position, last_host_attempted
        last_error: Exception | None = None
        while host_position + 1 < len(hosts):
            host_position += 1
            candidate = hosts[host_position]
            last_host_attempted = candidate
            candidate_api = api_factory(candidate[0], candidate[1])
            try:
                _connect_session(candidate_api, candidate[0], candidate[1], timeout)
                return candidate_api, candidate
            except Exception as error:
                last_error = error
                _disconnect_session(candidate_api)
        raise RuntimeError(f"no usable TDX host remains: {last_error!r}")

    for item in target_list:
        symbol = str(item.code)
        existing = read_hq_day_bars(item.path, tail_records=1)
        last_date = day_int(existing[-1]) if existing else None
        previous_close = float(existing[-1]["close"]) if existing else None
        if last_date == target_int:
            by_symbol[symbol] = {
                "symbol": symbol,
                "status": "ALREADY_CURRENT",
                "target_date_ready": True,
                "last_date_before": last_date,
                "last_date_after": last_date,
            }
            continue
        final_failure: dict[str, Any] | None = None
        while True:
            if api is None:
                try:
                    api, host_info = open_next_host()
                except Exception as error:
                    final_failure = {
                        "symbol": symbol,
                        "host": _host_label(*(last_host_attempted or host_info))
                        if (last_host_attempted or host_info)
                        else "unavailable",
                        "failure_type": "host_unavailable",
                        "error": repr(error),
                    }
                    break
            assert host_info is not None
            try:
                bars, failure_type = _fetch_valid_target_bars(
                    api, item, target_int, previous_close, count
                )
                if failure_type == "ok":
                    if not dry_run:
                        append_bars(item.path, bars)
                    last_after = day_int(bars[-1])
                    by_symbol[symbol] = {
                        "symbol": symbol,
                        "status": "UPDATED",
                        "target_date_ready": last_after == target_int,
                        "last_date_before": last_date,
                        "last_date_after": last_after,
                        "host": _host_label(*host_info),
                        "records_written": len(bars),
                    }
                    final_failure = None
                    break
                final_failure = {
                    "symbol": symbol,
                    "host": _host_label(*host_info),
                    "failure_type": failure_type,
                }
            except Exception as error:
                final_failure = {
                    "symbol": symbol,
                    "host": _host_label(*host_info),
                    "failure_type": "request_error",
                    "error": repr(error),
                }
            _disconnect_session(api)
            api = None
            # The next iteration retries this symbol on the next host only.
            if host_position + 1 >= len(hosts):
                break
        if final_failure is not None:
            by_symbol[symbol] = {
                "symbol": symbol,
                "status": "FAILED",
                "target_date_ready": False,
                "last_date_before": last_date,
                "last_date_after": last_date,
                **final_failure,
            }
            failures.append(final_failure)
            # A symbol may exhaust the host list.  That exhaustion is local to
            # this symbol; the next symbol must be allowed to establish a new
            # session from the first candidate rather than inheriting a dead
            # global cursor.
            _disconnect_session(api)
            api = None
            host_position = -1
            host_info = None
            last_host_attempted = None

    _disconnect_session(api)
    status = "PASS" if not failures else "FAILED"
    return {
        "task_name": TASK_NAME,
        "status": status,
        "exit_code": 0 if status == "PASS" else 2,
        "target_date": str(target_int),
        "target_count": len(target_list),
        "updated_count": sum(item.get("status") == "UPDATED" for item in by_symbol.values()),
        "failures": failures,
        "by_symbol": by_symbol,
        "host": _host_label(*host_info) if host_info else None,
    }


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, obj: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8", newline="\n")


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    ensure_dir(path.parent)
    keys: List[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in keys})


def day_int(bar: Dict[str, Any]) -> int:
    return int(bar["year"]) * 10000 + int(bar["month"]) * 100 + int(bar["day"])


def read_last_date(path: Path) -> Optional[int]:
    if not path.exists() or path.stat().st_size < DAY_STRUCT.size:
        return None
    with path.open("rb") as f:
        f.seek(-DAY_STRUCT.size, os.SEEK_END)
        return int(DAY_STRUCT.unpack(f.read(DAY_STRUCT.size))[0])


def pack_hq_bar(bar: Dict[str, Any]) -> bytes:
    return DAY_STRUCT.pack(
        day_int(bar),
        int(round(float(bar["open"]) * 100)),
        int(round(float(bar["high"]) * 100)),
        int(round(float(bar["low"]) * 100)),
        int(round(float(bar["close"]) * 100)),
        float(bar.get("amount") or 0.0),
        int(round(float(bar.get("vol") or 0.0) * 100)),
        0,
    )


def valid_hq_bar(bar: Dict[str, Any]) -> Tuple[bool, str]:
    try:
        date_value = day_int(bar)
        open_v = float(bar["open"])
        high_v = float(bar["high"])
        low_v = float(bar["low"])
        close_v = float(bar["close"])
    except Exception as exc:
        return False, f"parse_error:{exc!r}"
    if not (19900101 <= date_value <= 21000101):
        return False, f"bad_date:{date_value}"
    if min(open_v, high_v, low_v, close_v) <= 0:
        return False, "non_positive_ohlc"
    if high_v < low_v:
        return False, "high_lt_low"
    if close_v > high_v or close_v < low_v:
        return False, "close_outside_high_low"
    return True, "ok"


def partition_bars_by_cross_day_continuity(
    bars: List[Dict[str, Any]], previous_close: Optional[float], max_close_ratio: float = MAX_CROSS_DAY_CLOSE_RATIO,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Keep a contiguous append chain; leave suspicious bars for an offline rebuild candidate."""
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    prior = float(previous_close) if previous_close and previous_close > 0 else None
    for bar in sorted(bars, key=day_int):
        close = float(bar["close"])
        ratio = close / prior if prior else None
        if ratio is not None and (ratio > max_close_ratio or ratio < 1.0 / max_close_ratio):
            rejected.append({"bar": dict(bar), "reason": "cross_day_close_ratio", "close_ratio": ratio})
            continue
        accepted.append(dict(bar))
        prior = close
    return accepted, rejected


def read_hq_day_bars(path: Path, tail_records: Optional[int] = None) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    size = path.stat().st_size
    count = size // DAY_STRUCT.size
    start = max(0, count - tail_records) if tail_records else 0
    rows: List[Dict[str, Any]] = []
    with path.open("rb") as f:
        f.seek(start * DAY_STRUCT.size)
        data = f.read((count - start) * DAY_STRUCT.size)
    for offset in range(0, len(data), DAY_STRUCT.size):
        date_i, open_i, high_i, low_i, close_i, amount_f, vol_u, _reserved = DAY_STRUCT.unpack_from(data, offset)
        rows.append({
            "year": date_i // 10000, "month": date_i // 100 % 100, "day": date_i % 100,
            "open": open_i / 100.0, "high": high_i / 100.0, "low": low_i / 100.0,
            "close": close_i / 100.0, "amount": amount_f, "vol": vol_u / 100.0,
        })
    return rows


def build_rebuild_candidate(source_path: Path, replacements: List[Dict[str, Any]], candidate_path: Path) -> Dict[str, Any]:
    """Write a side-by-side corrected .day candidate; never mutate the source history."""
    existing = {day_int(bar): bar for bar in read_hq_day_bars(source_path)}
    replacement_dates = sorted({day_int(bar) for bar in replacements})
    existing.update({day_int(bar): dict(bar) for bar in replacements})
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    with candidate_path.open("wb") as handle:
        for date_value in sorted(existing):
            handle.write(pack_hq_bar(existing[date_value]))
    return {"source_path": str(source_path), "candidate_path": str(candidate_path), "replaced_dates": replacement_dates}


def discover_targets(markets: Iterable[str], tdx_root: Path) -> List[Tuple[str, int, str, Path, Optional[int]]]:
    targets: List[Tuple[str, int, str, Path, Optional[int]]] = []
    for market_name in markets:
        for prefix, template_dir in DIR_BY_MARKET.get(market_name, []):
            directory = Path(str(template_dir).replace(str(TDX_ROOT), str(tdx_root)))
            if not directory.exists():
                continue
            for path in directory.glob(f"{prefix}*.day"):
                code = path.stem[len(prefix):]
                if len(code) != 6 or not code.isdigit():
                    continue
                if not code.startswith(EQUITY_CODE_PREFIXES_BY_MARKET[prefix]):
                    continue
                targets.append((prefix, MARKET_BY_PREFIX[prefix], code, path, read_last_date(path)))
    return targets


def connect_hq(preferred_host: Optional[str], timeout: float) -> Tuple[TdxHq_API, Dict[str, Any]]:
    candidates = []
    if preferred_host:
        host, _, port_text = preferred_host.partition(":")
        candidates.append(("preferred", host, int(port_text or 7709)))
    candidates.extend(hq_hosts)

    for name, host, port in candidates:
        api = TdxHq_API()
        try:
            ok = api.connect(host, int(port), time_out=timeout)
            if ok:
                probe = api.get_security_bars(9, 1, "600000", 0, 1)
                if probe:
                    return api, {"name": name, "host": host, "port": int(port), "probe_latest": probe[-1]}
        except Exception:
            try:
                api.disconnect()
            except Exception:
                pass
            continue
    raise RuntimeError("No usable pytdx HQ host found")


def fetch_new_bars(api: TdxHq_API, market: int, code: str, after_date: Optional[int], count: int) -> Tuple[List[Dict[str, Any]], str, int]:
    bars = api.get_security_bars(9, market, code, 0, count)
    if not bars:
        return [], "empty_response", 0
    new_bars = []
    skipped_invalid = 0
    for bar in bars:
        ok, reason = valid_hq_bar(bar)
        if not ok:
            skipped_invalid += 1
            continue
        if after_date is None or day_int(bar) > int(after_date):
            new_bars.append(dict(bar))
    status = "ok" if skipped_invalid == 0 else "ok_with_skipped_invalid"
    return new_bars, status, skipped_invalid


def append_bars(path: Path, bars: List[Dict[str, Any]]) -> None:
    with path.open("ab") as f:
        for bar in bars:
            f.write(pack_hq_bar(bar))


def _runtime_host_candidates(preferred_host: Optional[str]) -> list[tuple[str, int]]:
    candidates: list[tuple[str, int]] = []
    if preferred_host:
        host, _, port_text = str(preferred_host).partition(":")
        candidates.append((host, int(port_text or 7709)))
    for item in hq_hosts:
        if len(item) >= 3:
            _name, host, port = item[:3]
            candidates.append((str(host), int(port)))
        elif len(item) == 2:
            host, port = item
            candidates.append((str(host), int(port)))
    return list(dict.fromkeys(candidates))


def _runtime_api_factory(host: str, _port: int) -> Any:
    if TdxHq_API is None:
        raise RuntimeError("pytdx is not installed")
    return TdxHq_API()


def run(args: argparse.Namespace) -> Dict[str, Any]:
    """Run the bounded sync and persist a truthful summary."""

    ensure_dir(RUN_DIR)
    markets = [x.strip().lower() for x in args.markets.split(",") if x.strip()]
    discovered = discover_targets(markets, args.tdx_root)
    if args.limit:
        discovered = discovered[: args.limit]
    targets = [
        DailyTarget(code=code, market=market, path=path)
        for _prefix, market, code, path, _last_date in discovered
    ]
    target_date = getattr(args, "target_date", None)
    if not target_date:
        raise ValueError("tdx daily sync requires an exact target_date")
    result = run_sync(
        targets,
        target_date=str(target_date),
        api_factory=_runtime_api_factory,
        host_candidates=_runtime_host_candidates(getattr(args, "host", None)),
        count=args.count,
        timeout=args.timeout,
        dry_run=bool(args.dry_run),
    )
    result.update(
        {
            "run_dir": str(RUN_DIR),
            "tdx_root": str(args.tdx_root),
            "markets": markets,
            "dry_run": bool(args.dry_run),
            "count": args.count,
            "note": "This sync updates SH/SZ/BJ vipdoc daily files only. HK extended market ExHQ is not written by this script.",
        }
    )
    write_csv(RUN_DIR / "file_results.csv", list(result["by_symbol"].values()))
    write_json(RUN_DIR / "summary.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str), flush=True)
    return result


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync latest SH/SZ/BJ daily bars from pytdx into local TDX vipdoc .day files.")
    parser.add_argument("--tdx-root", type=Path, default=TDX_ROOT)
    parser.add_argument("--target-date", help="Exact YYYYMMDD target required for a truthful sync.")
    parser.add_argument("--history-backfill-config", type=Path, help="Frozen isolated history candidate configuration; no network sync or promotion.")
    parser.add_argument("--history-backfill-config-sha256", help="Exact SHA-256 of the isolated history configuration.")
    parser.add_argument("--markets", default="a,bj", help="Comma separated: a,bj. HK extended market is intentionally not supported here.")
    parser.add_argument("--count", type=int, default=20, help="Latest bars to request per symbol.")
    parser.add_argument("--host", default=None, help="Optional host:port override.")
    parser.add_argument("--timeout", type=float, default=1.5)
    parser.add_argument("--sleep", type=float, default=0.0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--progress-every", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.history_backfill_config:
        if not args.history_backfill_config_sha256:
            parser.error("--history-backfill-config requires --history-backfill-config-sha256")
        if args.target_date or args.dry_run or args.limit or args.host:
            parser.error("history backfill cannot be combined with network-sync execution options")
    elif not args.target_date:
        parser.error("--target-date is required for daily sync")
    return args


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    if args.history_backfill_config:
        if __package__:
            from .a_share_history_backfill import run_config
        else:
            from a_share_history_backfill import run_config
        result = run_config(args.history_backfill_config, args.history_backfill_config_sha256)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
        return 0
    result = run(args)
    return int(result.get("exit_code", 1))


if __name__ == "__main__":
    raise SystemExit(main())
