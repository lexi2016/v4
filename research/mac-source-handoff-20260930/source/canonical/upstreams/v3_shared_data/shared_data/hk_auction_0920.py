"""Shared single-writer HK Connect 09:15-09:20 auction reference capture.

The scoring, ordering and hard caps are a path-neutral port of the frozen V3
``collect_hkconnect_0915_0920_reference_snapshot`` and
``build_hkconnect_0920_auction_second_filter`` contracts.  The shared store is
the only writer; V3 and V3.5 consume the verified artifact read-only.
"""
from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from shared_data.allowlist import AllowlistRegistry, SourceSpec
from shared_data.consumer import read_verified_latest
from shared_data.hashing import sha256_json
from shared_data.hk_0_2 import HK_0_2_ROLE
from shared_data.paths import validate_date
from shared_data.store import SafeRootStore, StoreError


ROLE = "HK_CONNECT_AUCTION_REFERENCE_STAGE_0925"
STAGE_ID = "STAGE_0925"
SOURCE_ID = "futu_hk_0915_0920_snapshot"
WINDOW_START = "09:15:00"
SIGNAL_CUTOFF = "09:19:59"
PUBLICATION_TIME = "09:20:00"
TOP_REFERENCE_N = 50
TOP_FILTER_N = 20
STRICT_FAILURE_PCT = -2.2
MARKER = "__FUTU_HK_AUCTION_JSON__"

REFERENCE_FIELDS = (
    "rank", "code", "ts_code", "name", "target_date", "signal_date",
    "stage_id", "stage1_ref_score", "stage1_ref_label", "reference_scope",
    "auction_ref_gap_pct", "first_to_last_ref_pct", "visible_depth_hkd",
    "bid_ask_imbalance", "spread_pct", "last_price", "prev_close_price",
    "bid_price", "ask_price", "bid_vol", "ask_vol", "turnover", "volume",
    "volume_ratio", "update_time", "collector_wall_time", "collector_loop",
    "source_update_time_status", "preselect_rank", "preselect_lane",
    "preselect_score", "cannot_confirm",
)
ARTIFACT_FIELDS = ("trade_date", "bar_time") + REFERENCE_FIELDS

_FUTU_SNAPSHOT_PROBE = r"""
import json
import socket
import sys
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from importlib.metadata import version, PackageNotFoundError
import futu as ft
import futu.quote.quote_query as native_query
import futu.quote.open_quote_context as native_context

payload = json.loads(sys.stdin.read())
codes = payload["codes"]
socket.setdefaulttimeout(3.0)
ctx = ft.OpenQuoteContext(host="127.0.0.1", port=11111)
def source_sha(module):
    try:
        return hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
    except (AttributeError, OSError, TypeError):
        return None

try:
    sdk_version = version("futu-api")
except PackageNotFoundError:
    sdk_version = None

# This records the running mapper, not an inferred stock/lot or currency unit.
# No subscription, security-info request, conversion or historical backfill.
identity = {"schema_version": "v3_shared_data.futu_snapshot_native_observation.v1",
            "interface": "OpenQuoteContext.get_market_snapshot",
            "sdk_version": sdk_version,
            "quote_query_sha256": source_sha(native_query),
            "open_quote_context_sha256": source_sha(native_context),
            "unit_status": "NOT_ATTESTED_FOR_THIS_INTERFACE",
            "fields": {"volume": "volume", "turnover": "turnover",
                       "last_price": "last_price", "low_price": "low_price"},
            "value_transform": "NONE",
            "date_semantics": "LOCAL_REQUEST_RESPONSE_NOT_EXCHANGE_PUBLICATION"}
rows = []
errors = []
try:
    for start in range(0, len(codes), 300):
        batch = codes[start:start + 300]
        try:
            request_started_at = datetime.now(timezone.utc).isoformat()
            ret, data = ctx.get_market_snapshot(batch)
            response_received_at = datetime.now(timezone.utc).isoformat()
            if ret == ft.RET_OK and hasattr(data, "to_dict"):
                returned = data.to_dict(orient="records")
                observation = {**identity, "request_started_at": request_started_at,
                               "response_received_at": response_received_at}
                if any("native_field_evidence" in row for row in returned):
                    raise ValueError("NATIVE_FIELD_EVIDENCE_KEY_CONFLICT")
                rows.extend({**row, "native_field_evidence": dict(observation)} for row in returned)
            else:
                errors.append(str(data))
        except Exception as exc:
            errors.append(str(exc))
finally:
    try:
        ctx.close()
    except Exception:
        pass
print("__FUTU_HK_AUCTION_JSON__" + json.dumps({"rows": rows, "errors": errors}, ensure_ascii=False, default=str))
"""


def _number(value: Any, default: float | None = None) -> float | None:
    if value in (None, "", "N/A", "nan") or isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _first(row: Mapping[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return default


def _rounded(value: float | None, digits: int = 4) -> float | str:
    return "" if value is None else round(value, digits)


def normalize_hk_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text.startswith("HK."):
        digits = text.split(".", 1)[1]
    elif text.endswith(".HK"):
        digits = text.rsplit(".", 1)[0]
    else:
        digits = "".join(character for character in text if character.isdigit())
    return f"HK.{digits.zfill(5)}" if digits else ""


def _ts_code(code: str) -> str:
    return f"{code.split('.', 1)[1]}.HK_CONNECT"


def _source_update_time_status(update_time: Any, trade_date: str) -> str:
    text = str(update_time or "")
    if trade_date in re.sub(r"\D+", "", text):
        return "UPDATE_TIME_MATCH_TARGET_DATE"
    if text:
        return "UPDATE_TIME_NOT_TARGET_DATE_REVIEW_REQUIRED"
    return "UPDATE_TIME_EMPTY_REVIEW_REQUIRED"


def score_reference_row(row: Mapping[str, Any]) -> float:
    """Exact frozen V3 09:15-09:20 reference score."""
    gap = _number(row.get("auction_ref_gap_pct"))
    trend = _number(row.get("first_to_last_ref_pct"))
    depth = _number(row.get("visible_depth_hkd"), 0.0) or 0.0
    imbalance = _number(row.get("bid_ask_imbalance"), 0.0) or 0.0
    spread = _number(row.get("spread_pct"))
    turnover = _number(row.get("turnover"), 0.0) or 0.0
    score = 25.0
    if gap is not None:
        if 0 <= gap <= 3:
            score += 24
        elif 3 < gap <= 6:
            score += 18
        elif 6 < gap <= 8:
            score += 8
        elif gap > 8:
            score -= 18
        elif -3 <= gap < 0:
            score += 6
        else:
            score -= 8
    if trend is not None:
        score += max(-10.0, min(15.0, trend * 3.0))
    if depth >= 3_000_000:
        score += 16
    elif depth >= 1_000_000:
        score += 11
    elif depth >= 300_000:
        score += 5
    if imbalance > 0.35:
        score += 12
    elif imbalance > 0.15:
        score += 7
    elif imbalance < -0.35:
        score -= 10
    if spread is not None:
        if spread <= 0.5:
            score += 10
        elif spread <= 1.0:
            score += 5
        elif spread > 2.0:
            score -= 12
    if turnover >= 30_000_000:
        score += 10
    elif turnover >= 10_000_000:
        score += 6
    return max(0.0, min(100.0, score))


def _reference_label(score: float, gap: float | None, spread: float | None) -> str:
    if gap is not None and gap > 8:
        return "PREOPEN_REF_HIGH_OPEN_NO_CHASE"
    if spread is not None and spread > 2:
        return "PREOPEN_REF_LIQUIDITY_WARNING"
    if score >= 70:
        return "PREOPEN_REF_PRIORITY"
    if score >= 50:
        return "PREOPEN_REF_WATCH"
    return "PREOPEN_REF_LOW_PRIORITY"


def load_verified_candidates(store_root: Path | str, trade_date: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    trade_date = validate_date(trade_date)
    verified = read_verified_latest(store_root, trade_date, HK_0_2_ROLE)
    signal_date = str(verified.manifest.get("signal_date") or "")
    if not re.fullmatch(r"\d{8}", signal_date) or signal_date >= trade_date:
        raise StoreError("verified HK 0.2 pool has invalid signal_date")
    rows: list[dict[str, Any]] = []
    with open(verified.artifact_path, "r", encoding="utf-8-sig", newline="") as handle:
        for source in csv.DictReader(handle):
            code = normalize_hk_code(_first(source, "code_norm", "code", "ts_code"))
            if not code:
                continue
            rows.append({
                "code": code,
                "name": str(_first(source, "name", default=code)),
                "preselect_rank": str(_first(source, "rank", default="")),
                "preselect_lane": str(_first(source, "lane", default="D1_PRESELECT") or "D1_PRESELECT"),
                "preselect_score": str(_first(source, "hybrid_score", "score_prob_active", default="")),
            })
    if len(rows) != 100 or len({row["code"] for row in rows}) != 100:
        raise StoreError("verified HK 0.2 candidate pool is not unique Top100")
    return rows, {
        "signal_date": signal_date,
        "d1_pool_sha256": str(verified.verification.get("artifact_sha256") or ""),
        "d1_run_id": str(verified.verification.get("run_id") or ""),
    }


def fetch_futu_snapshot(
    python_path: Path | str,
    codes: Sequence[str],
    *,
    process_runner: Callable[..., Any] = subprocess.run,
    timeout_seconds: float = 30,
) -> tuple[list[dict[str, Any]], list[str]]:
    python_path = Path(python_path)
    if not python_path.is_file():
        raise ValueError(f"futu python is not a file: {python_path}")
    normalized = [normalize_hk_code(code) for code in codes]
    if not normalized or any(not re.fullmatch(r"HK\.\d{5}", code) for code in normalized):
        raise ValueError("HK auction codes must be a nonempty HK.##### list")
    if len(set(normalized)) != len(normalized):
        raise ValueError("HK auction codes must be unique")
    completed = process_runner(
        [str(python_path), "-c", _FUTU_SNAPSHOT_PROBE],
        input=json.dumps({"codes": normalized}, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        shell=False,
    )
    if completed.returncode != 0:
        detail = str(completed.stderr or completed.stdout or "")[-1000:]
        raise StoreError(f"Futu HK auction snapshot failed: exit={completed.returncode}: {detail}")
    marker_line = next(
        (line for line in reversed((completed.stdout or "").splitlines()) if line.startswith(MARKER)),
        None,
    )
    if marker_line is None:
        raise StoreError("Futu HK auction snapshot marker missing")
    payload = json.JSONDecoder().raw_decode(marker_line[len(MARKER):].strip())[0]
    if not isinstance(payload, Mapping) or not isinstance(payload.get("rows"), list):
        raise StoreError("Futu HK auction snapshot payload invalid")
    errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []
    return [dict(row) for row in payload["rows"] if isinstance(row, Mapping)], [str(item) for item in errors]


def flatten_snapshot_rows(
    snapshot_rows: Sequence[Mapping[str, Any]],
    candidates: Mapping[str, Mapping[str, Any]],
    *,
    trade_date: str,
    signal_date: str,
    collector_loop: int,
    collector_wall_time: str,
    first_price_by_code: dict[str, float],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for raw in snapshot_rows:
        code = normalize_hk_code(raw.get("code"))
        candidate = candidates.get(code)
        if candidate is None:
            continue
        last = _number(_first(raw, "last_price", "price", "nominal_price"))
        previous_close = _number(_first(raw, "prev_close_price", "last_close"))
        bid = _number(_first(raw, "bid_price", "bid1"))
        ask = _number(_first(raw, "ask_price", "ask1"))
        bid_volume = _number(_first(raw, "bid_vol", "bid_vol1"), 0.0) or 0.0
        ask_volume = _number(_first(raw, "ask_vol", "ask_vol1"), 0.0) or 0.0
        turnover = _number(raw.get("turnover"), 0.0) or 0.0
        volume = _number(raw.get("volume"), 0.0) or 0.0
        volume_ratio = _number(raw.get("volume_ratio"))
        gap = (last / previous_close - 1) * 100 if last is not None and previous_close not in (None, 0) else None
        if last is not None and code not in first_price_by_code:
            first_price_by_code[code] = last
        first_to_last = (
            (last / first_price_by_code[code] - 1) * 100
            if last is not None and first_price_by_code.get(code) not in (None, 0)
            else None
        )
        bid_depth = (bid or 0.0) * bid_volume
        ask_depth = (ask or 0.0) * ask_volume
        depth = bid_depth + ask_depth
        imbalance = (bid_depth - ask_depth) / depth if depth > 0 else None
        spread = ((ask - bid) / ((ask + bid) / 2) * 100) if bid and ask and ask >= bid else None
        update_time = str(raw.get("update_time") or "")
        row: dict[str, Any] = {
            "rank": 0,
            "code": code,
            "ts_code": _ts_code(code),
            "name": str(candidate.get("name") or raw.get("name") or code),
            "target_date": trade_date,
            "signal_date": signal_date,
            "stage_id": "HK_PREOPEN_0920",
            "reference_scope": "SIGNAL_INPUT_CUTOFF_SAFE_091959",
            "auction_ref_gap_pct": _rounded(gap),
            "first_to_last_ref_pct": _rounded(first_to_last),
            "visible_depth_hkd": _rounded(depth, 2),
            "bid_ask_imbalance": _rounded(imbalance),
            "spread_pct": _rounded(spread),
            "last_price": _rounded(last),
            "prev_close_price": _rounded(previous_close),
            "bid_price": _rounded(bid),
            "ask_price": _rounded(ask),
            "bid_vol": _rounded(bid_volume, 2),
            "ask_vol": _rounded(ask_volume, 2),
            "turnover": _rounded(turnover, 2),
            "volume": _rounded(volume, 2),
            "volume_ratio": _rounded(volume_ratio),
            "update_time": update_time,
            "collector_wall_time": collector_wall_time,
            "collector_loop": collector_loop,
            "source_update_time_status": _source_update_time_status(update_time, trade_date),
            "preselect_rank": candidate.get("preselect_rank", ""),
            "preselect_lane": candidate.get("preselect_lane", ""),
            "preselect_score": candidate.get("preselect_score", ""),
            "cannot_confirm": "Post-09:20 execution quote is excluded from ranking; snapshot is not full broker queue/depth/cancel evidence.",
        }
        score = score_reference_row(row)
        row["stage1_ref_score"] = round(score, 4)
        row["stage1_ref_label"] = _reference_label(score, gap, spread)
        output.append(row)
    return output


def latest_reference_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_code = {str(row.get("code") or ""): dict(row) for row in rows}
    latest = list(by_code.values())
    latest.sort(
        key=lambda row: (
            _number(row.get("stage1_ref_score"), 0.0) or 0.0,
            _number(row.get("auction_ref_gap_pct"), -999.0) or -999.0,
            _number(row.get("visible_depth_hkd"), 0.0) or 0.0,
        ),
        reverse=True,
    )
    return [{**row, "rank": index} for index, row in enumerate(latest, start=1)]


def build_second_filter_rows(
    preselect_rows: Sequence[Mapping[str, Any]],
    auction_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Exact frozen V3 Top20 ordering, used to freeze output evidence SHA."""
    preselect_by_code = {
        normalize_hk_code(_first(row, "code", "symbol", "ts_code")): row
        for row in preselect_rows
    }
    output: list[dict[str, Any]] = []
    for auction_rank, auction in enumerate(auction_rows, start=1):
        code = normalize_hk_code(_first(auction, "code", "futu_code", "ts_code"))
        if not code or code not in preselect_by_code:
            continue
        preselect = preselect_by_code[code]
        score = _number(_first(auction, "stage1_ref_score", "auction_entry_score"), 0.0) or 0.0
        gap = _number(_first(auction, "auction_ref_gap_pct", "opening_gap_proxy_pct"))
        if score >= 70 and (gap is None or gap <= 8):
            status = "AUCTION_SECOND_FILTER_PRIORITY"
        elif score >= 50:
            status = "AUCTION_SECOND_FILTER_WATCH"
        else:
            status = "AUCTION_SECOND_FILTER_LOW_PRIORITY"
        if gap is not None and gap > 8:
            status = "AUCTION_HIGH_OPEN_NO_CHASE"
        reference_price = _number(_first(auction, "last_price", "price"))
        output.append({
            "rank": 0,
            "code": code,
            "name": _first(preselect, "name", default=_first(auction, "name", default=code)),
            "auction_rank": auction_rank,
            "auction_score": round(score, 4),
            "second_filter_status": status,
            "auction_ref_gap_pct": _first(auction, "auction_ref_gap_pct", "opening_gap_proxy_pct"),
            "turnover": auction.get("turnover", ""),
            "reference_price_hkd": round(reference_price, 3) if reference_price else None,
            "strict_failure_price_hkd": round(reference_price * (1 + STRICT_FAILURE_PCT / 100), 3) if reference_price else None,
        })
    output.sort(key=lambda row: (
        -(_number(row.get("auction_score"), 0.0) or 0.0),
        -(_number(row.get("turnover"), 0.0) or 0.0),
        str(row.get("code") or ""),
    ))
    return [{**row, "rank": index} for index, row in enumerate(output[:TOP_FILTER_N], start=1)]


def _artifact_bar_time(row: Mapping[str, Any]) -> str:
    stamp = str(row.get("collector_wall_time") or "")
    match = re.search(r"(\d{2}:\d{2}:\d{2})", stamp)
    if match is None:
        raise ValueError("auction reference row lacks collector wall time")
    return match.group(1)


def publish_reference_rows(
    store_root: Path | str,
    trade_date: str,
    rows: Sequence[Mapping[str, Any]],
    *,
    signal_date: str,
    d1_pool_sha256: str,
    source_output_sha256: str,
) -> dict[str, Any]:
    trade_date = validate_date(trade_date)
    if len(rows) != TOP_REFERENCE_N:
        raise StoreError(f"HK 09:20 reference requires Top{TOP_REFERENCE_N}, got {len(rows)}")
    temp_root = Path(tempfile.mkdtemp(prefix="v3_shared_hk_auction_"))
    try:
        source = temp_root / "hk_auction_reference.csv"
        with open(source, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=ARTIFACT_FIELDS, extrasaction="ignore", lineterminator="\n")
            writer.writeheader()
            for row in rows:
                writer.writerow({"trade_date": trade_date, "bar_time": _artifact_bar_time(row), **dict(row)})
        spec = SourceSpec(
            source_id=SOURCE_ID,
            role=ROLE,
            trade_date=trade_date,
            market="HK_CONNECT",
            stages=(STAGE_ID,),
            cutoff_at=SIGNAL_CUTOFF,
            source_path=source,
            required_columns=("trade_date", "bar_time", "rank", "code", "stage1_ref_score"),
            bar_time_column="bar_time",
            expected_row_count=TOP_REFERENCE_N,
            provenance={
                "v3_source_id": SOURCE_ID,
                "v3_display_name": "FUTU_OPEND_HK_PREOPEN_MARKET_SNAPSHOT",
                "v3_fidelity": "FUTU_HK_PREOPEN_REFERENCE_CUTOFF_SAFE",
                "signal_date": signal_date,
                "d1_pool_sha256": d1_pool_sha256,
                "source_output_sha256": source_output_sha256,
                "publication_time": "092000",
            },
        )
        store = SafeRootStore(
            Path(store_root),
            AllowlistRegistry({(trade_date, ROLE): (spec,)}),
        )
        return store.replay_file(
            owner="v3_shared_data",
            trade_date=trade_date,
            role=ROLE,
            source_id=SOURCE_ID,
            stage_id=STAGE_ID,
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def run_capture(
    store_root: Path | str,
    trade_date: str,
    python_path: Path | str,
    *,
    interval_seconds: int = 20,
    now: Callable[[], datetime] = datetime.now,
    sleeper: Callable[[float], None],
    snapshot_reader: Callable[[Path | str, Sequence[str]], tuple[list[dict[str, Any]], list[str]]] | None = None,
) -> dict[str, Any]:
    trade_date = validate_date(trade_date)
    candidates, pool_evidence = load_verified_candidates(store_root, trade_date)
    by_code = {row["code"]: row for row in candidates}
    start_at = datetime.strptime(f"{trade_date} {WINDOW_START}", "%Y%m%d %H:%M:%S")
    cutoff_at = datetime.strptime(f"{trade_date} {SIGNAL_CUTOFF}", "%Y%m%d %H:%M:%S")
    current = now()
    if current > cutoff_at:
        raise StoreError("HK 09:20 collector launched after 09:19:59; later data cannot backfill")
    if current < start_at:
        sleeper((start_at - current).total_seconds())
    reader = snapshot_reader or (lambda executable, codes: fetch_futu_snapshot(executable, codes))
    all_rows: list[dict[str, Any]] = []
    first_price: dict[str, float] = {}
    loop_index = 0
    errors: list[str] = []
    while now() <= cutoff_at:
        loop_index += 1
        snapshot, batch_errors = reader(python_path, list(by_code))
        captured = now()
        if captured > cutoff_at:
            break
        errors.extend(batch_errors)
        all_rows.extend(flatten_snapshot_rows(
            snapshot,
            by_code,
            trade_date=trade_date,
            signal_date=pool_evidence["signal_date"],
            collector_loop=loop_index,
            collector_wall_time=captured.isoformat(sep=" ", timespec="seconds"),
            first_price_by_code=first_price,
        ))
        if captured >= cutoff_at:
            break
        sleeper(min(max(1, int(interval_seconds)), max(0.0, (cutoff_at - captured).total_seconds())))
    timestamps = {_artifact_bar_time(row) for row in all_rows}
    reaches_0919 = any(stamp >= "09:19:00" for stamp in timestamps)
    if not reaches_0919 or len(timestamps) < 2:
        raise StoreError("CANNOT_CONFIRM_0915_0920_CONTINUOUS_COVERAGE")
    reference_rows = latest_reference_rows(all_rows)[:TOP_REFERENCE_N]
    if len(reference_rows) != TOP_REFERENCE_N:
        raise StoreError(f"HK 09:20 reference shortfall: {len(reference_rows)}/{TOP_REFERENCE_N}")
    second_filter = build_second_filter_rows(candidates, reference_rows)
    if len(second_filter) != TOP_FILTER_N:
        raise StoreError(f"HK 09:20 second-filter shortfall: {len(second_filter)}/{TOP_FILTER_N}")
    source_output_sha = sha256_json({
        "contract": "old_v3_rule_guardrail_with_hardcap_and_0920_reference_layer",
        "trade_date": trade_date,
        "rows": second_filter,
    })
    published = publish_reference_rows(
        store_root,
        trade_date,
        reference_rows,
        signal_date=pool_evidence["signal_date"],
        d1_pool_sha256=pool_evidence["d1_pool_sha256"],
        source_output_sha256=source_output_sha,
    )
    return {
        "ok": published.get("status") == "READY",
        "status": published.get("status"),
        "trade_date": trade_date,
        "signal_date": pool_evidence["signal_date"],
        "collector_loop_count": loop_index,
        "reference_row_count": len(reference_rows),
        "second_filter_row_count": len(second_filter),
        "source_output_sha256": source_output_sha,
        "errors": errors[:10],
        "run": published,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


__all__ = [
    "ROLE", "STAGE_ID", "SIGNAL_CUTOFF", "PUBLICATION_TIME",
    "TOP_REFERENCE_N", "TOP_FILTER_N", "build_second_filter_rows",
    "fetch_futu_snapshot", "flatten_snapshot_rows", "latest_reference_rows",
    "load_verified_candidates", "publish_reference_rows", "run_capture",
    "score_reference_row",
]
