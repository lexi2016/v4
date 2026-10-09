"""V4-owned schema-3 intraday snapshots, replacing only Vibe's six-slot capture.

No scheduler, HTTP server, LLM, ranking, or new transport lives here.  The small
slot adapter delegates all acquisition/retry/raw publication to the existing
VibeDataAuthority.  Readers never acquire data and never trust a `verified` flag.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import date as Date, datetime
import base64
import json
import math
from pathlib import Path
import re
from statistics import mean, median
from typing import Any
from zoneinfo import ZoneInfo

from infrastructure.owned_io import SafeRoot
from infrastructure.trading_safety import assert_safe_tree
from domains.research_review_generation._cache import encoded, digest, explicit_root
from domains.research_review_generation._owned_io import BoundaryError
from domains.research_review_generation.owned_authority import VibeDataAuthority, _plain
from domains.research_review_generation.owned_runtime import verify_owned_sources
from domains.research_review_generation.data_core import market_facts, trade_calendar, emotion_metrics

SLOTS = ("09:25", "09:35", "10:00", "11:30", "14:00", "15:00")
SHANGHAI = ZoneInfo("Asia/Shanghai")
SOURCE_ID = "V4_OWNED_ORIGINAL_VIBE_DATA"
SAFETY = {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
_SNAP_SCHEMA = 3
_LIMIT = 32 * 1024 * 1024
_ATTEMPT_SCHEMA = "v4.intraday_attempt.v2"
_ATTEMPT_STATES = frozenset(
    {
        "PREPARED",
        "REQUEST_IN_FLIGHT",
        "REQUEST_ATTEMPTED",
        "FAILED_NO_REQUEST",
        "ATTEMPT_UNKNOWN",
        "SUCCEEDED",
    }
)


class IntradayAttemptError(BoundaryError):
    """A sanitized capture failure with an explicit request outcome."""

    def __init__(self, error_code: str, attempt_state: str) -> None:
        self.error_code = str(error_code).strip().upper() or "INTRADAY_ATTEMPT_UNKNOWN"
        self.attempt_state = str(attempt_state).strip().upper() or "ATTEMPT_UNKNOWN"
        super().__init__(self.error_code)


def _attempt_error_code(error: BaseException) -> str:
    token = str(error).strip().split(":", 1)[0].strip().upper()
    if re.fullmatch(r"[A-Z0-9_.-]{1,80}", token):
        return token
    return f"INTRADAY_{type(error).__name__.upper()}"[:80]


def _date(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{8}|\d{4}-\d{2}-\d{2}", value):
        raise BoundaryError("INTRADAY_DATE_INVALID")
    token = f"{value[:4]}-{value[4:6]}-{value[6:]}" if len(value) == 8 else value
    return Date.fromisoformat(token).isoformat()


def _slot(value: str) -> str:
    value = value[:2] + ":" + value[2:] if isinstance(value, str) and len(value) == 4 else value
    if value not in SLOTS:
        raise BoundaryError("INTRADAY_SLOT_INVALID")
    return value


def _window(day: str, slot: str, now: datetime) -> int:
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise BoundaryError("INTRADAY_CLOCK_UNBOUND")
    now = now.astimezone(SHANGHAI)
    drift = now.hour * 60 + now.minute - int(slot[:2]) * 60 - int(slot[3:])
    if now.date().isoformat() != day or not 0 <= drift <= 8:
        raise BoundaryError("INTRADAY_CAPTURE_WINDOW_REFUSED")
    return drift


def _json(raw: bytes) -> dict:
    obj = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    if not isinstance(obj, dict):
        raise BoundaryError("INTRADAY_OBJECT_REQUIRED")
    assert_safe_tree(obj, label="intraday research")
    return obj


def _bound(io: SafeRoot, ref: dict, prefix: str) -> tuple[dict, bytes]:
    if (not isinstance(ref, dict) or not isinstance(ref.get("path"), str)
            or not (ref["path"].startswith(prefix) if prefix.endswith("/") else ref["path"] == prefix)
            or not re.fullmatch(r"[0-9a-f]{64}", str(ref.get("sha256", "")))):
        raise BoundaryError("INTRADAY_SOURCE_BINDING_INVALID")
    raw = io.read_bytes(ref["path"], max_bytes=_LIMIT)
    if len(raw) != ref.get("bytes") or digest(raw) != ref["sha256"]:
        raise BoundaryError("INTRADAY_SOURCE_BYTES_DRIFT")
    return _json(raw), raw


def _put(io: SafeRoot, path: str, payload: dict) -> dict:
    assert_safe_tree(payload, label="intraday research")
    raw = encoded(payload)
    io.write_bytes(path, raw, require_absent=True)
    return {"path": path, "bytes": len(raw), "sha256": digest(raw)}


def _write_attempt_state(
    io: SafeRoot,
    day: str,
    slot: str,
    config_sha256: str,
    state: str,
    *,
    error_code: str | None = None,
) -> None:
    """Atomically update the current marker and retain an append-only event."""

    if state not in _ATTEMPT_STATES:
        raise BoundaryError("INTRADAY_ATTEMPT_STATE_INVALID")
    stem = day + "/" + slot.replace(":", "")
    marker_path = "attempts/" + stem + ".json"
    sequence = 0
    try:
        current = _json(io.read_bytes(marker_path, max_bytes=256 * 1024))
    except FileNotFoundError:
        pass
    except (BoundaryError, OSError, ValueError, TypeError):
        # The normal caller has already rejected malformed/legacy markers.
        # Starting a new event sequence here keeps the marker writer from
        # trusting malformed metadata while preserving the existing failure
        # path.
        pass
    else:
        try:
            sequence = max(0, int(current.get("event_sequence") or 0))
        except (TypeError, ValueError):
            sequence = 0
    sequence += 1
    event = {
        "schema": "v4.intraday_attempt_event.v1",
        "date": day,
        "slot": slot,
        "attempt_state": state,
        "config_sha256": config_sha256,
        "error_code": error_code,
        "sequence": sequence,
        **SAFETY,
    }
    event_raw = encoded(event)
    event_path = "attempts/events/" + stem + f"/{sequence:06d}-{digest(event_raw)}.json"
    try:
        io.write_bytes(event_path, event_raw, require_absent=True)
    except FileExistsError:
        if io.read_bytes(event_path, max_bytes=256 * 1024) != event_raw:
            raise BoundaryError("INTRADAY_ATTEMPT_EVENT_COLLISION")
    marker = {
        "schema": _ATTEMPT_SCHEMA,
        "date": day,
        "slot": slot,
        "status": state,
        "attempt_state": state,
        "config_sha256": config_sha256,
        "last_event": {
            "path": event_path,
            "bytes": len(event_raw),
            "sha256": digest(event_raw),
        },
        "event_sequence": sequence,
        "error_code": error_code,
        **SAFETY,
    }
    io.write_bytes(marker_path, encoded(marker), require_absent=False)


def _read_attempt(
    io: SafeRoot,
    day: str,
    slot: str,
    config_sha256: str,
) -> dict[str, Any]:
    """Read a marker, treating legacy and malformed states as uncertain."""

    stem = day + "/" + slot.replace(":", "")
    try:
        payload = _json(io.read_bytes("attempts/" + stem + ".json", max_bytes=256 * 1024))
    except FileNotFoundError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as error:
        raise IntradayAttemptError("INTRADAY_ATTEMPT_UNKNOWN", "ATTEMPT_UNKNOWN") from error
    state = str(payload.get("attempt_state") or "").strip().upper()
    if (
        payload.get("schema") != _ATTEMPT_SCHEMA
        or payload.get("date") != day
        or payload.get("slot") != slot
        or payload.get("config_sha256") != config_sha256
        or payload.get("status") != state
        or state not in _ATTEMPT_STATES
    ):
        raise IntradayAttemptError("INTRADAY_ATTEMPT_UNKNOWN", "ATTEMPT_UNKNOWN")
    return payload


def load_intraday_binding(config_path: Path, config_sha256: str, source_manifest_sha256: str) -> dict:
    """Local caller pins config and code; no HTTP client supplies these paths."""
    path = explicit_root(config_path)
    raw = SafeRoot(path.parent).read_bytes(path.name, max_bytes=256 * 1024)
    if digest(raw) != config_sha256:
        raise BoundaryError("INTRADAY_CONFIG_SHA_MISMATCH")
    cfg = _json(raw)
    required = {"schema", "state_root", "cache_root", "cache_manifest_path", "cache_manifest_sha256",
                "source_id", "source_manifest_sha256", "input_bindings"}
    if (set(cfg) != required or cfg["schema"] != "v4.intraday_bindings.v1"
            or cfg["source_id"] != SOURCE_ID or cfg["source_manifest_sha256"] != source_manifest_sha256
            or not isinstance(cfg["input_bindings"], dict)):
        raise BoundaryError("INTRADAY_CONFIG_CONTRACT_MISMATCH")
    state = explicit_root(cfg["state_root"]); cache = explicit_root(cfg["cache_root"])
    explicit_root(cfg["cache_manifest_path"])
    if state not in cache.parents or cache == state / "intraday" or state / "intraday" in cache.parents:
        raise BoundaryError("INTRADAY_CACHE_ROOT_INVALID")
    verify_owned_sources(source_manifest_sha256)
    # Data identity excludes the map of approved already-collected inputs: no
    # hash cycle when a previously captured exact input is explicitly reused.
    cfg["binding_sha256"] = digest(encoded({k: v for k, v in cfg.items() if k != "input_bindings"}))
    cfg["config_sha256"] = config_sha256
    return cfg


class _SlotAuthority(VibeDataAuthority):
    """Namespace live requests, without changing global state or the provider.

    Daily settled caches have no slot. They must NOT satisfy a 09:25 request,
    including the 15:00+8min edge where the daily reader considers today settled.
    """
    def __init__(self, *, slot: str, **kwargs):
        self._attempt_state_writer = kwargs.pop("attempt_state_writer", None)
        super().__init__(**kwargs)
        self.slot = slot

    def _request(self, provider, endpoint, params, loader, **kwargs):
        session = kwargs.get("session") or params.get("date") or params.get("end_date") or self.target_date
        if str(session).replace("-", "") == self.target_date.replace("-", ""):
            params = {**params, "intraday_slot": self.slot}
        if self._attempt_state_writer is not None:
            self._attempt_state_writer("REQUEST_IN_FLIGHT")
        try:
            result = super()._request(provider, endpoint, params, loader, **kwargs)
        except Exception:
            if self._attempt_state_writer is not None:
                self._attempt_state_writer("REQUEST_ATTEMPTED")
            raise
        if self._attempt_state_writer is not None:
            self._attempt_state_writer("REQUEST_ATTEMPTED")
        return result

    def ak_call(self, endpoint, **params):
        if (endpoint in {"stock_zt_pool_em", "stock_zt_pool_zbgc_em", "stock_zt_pool_dtgc_em"}
                and str(params.get("date", "")).replace("-", "") == self.target_date.replace("-", "")):
            return self._request("akshare", endpoint, params, lambda: self.transport.ak(endpoint, **params))
        return super().ak_call(endpoint, **params)


def _live_pools(ctx: _SlotAuthority) -> dict | None:
    # Same three SDK endpoints and original field projections; no daily cache
    # read/write for a live time-labelled snapshot.
    try:
        day = ctx.target_date.replace("-", "")
        zt_df = ctx.ak_call("stock_zt_pool_em", date=day)
        zt = market_facts._df_rows(zt_df, market_facts._ZT_MAP)
        if not zt:
            return None
        zb_df = ctx.ak_call("stock_zt_pool_zbgc_em", date=day)
        dt_df = ctx.ak_call("stock_zt_pool_dtgc_em", date=day)
        return {"zt": zt, "zb": market_facts._df_rows(zb_df, market_facts._ZB_MAP),
                "dt": market_facts._df_rows(dt_df, market_facts._DT_MAP),
                "raw": {"zt": market_facts._raw_rows(zt_df), "zb": market_facts._raw_rows(zb_df),
                        "dt": market_facts._raw_rows(dt_df)}}
    except Exception:
        # Old schema-3 permits missing live counts, but never turns them into 0.
        # The owner's independent fatal/cache gate is still checked by caller.
        return None


def _validate_input(value: dict, *, state: Path, day: str, slot: str, binding_sha256: str | None = None,
                    source_manifest_sha256: str | None = None, cache_root: str | None = None) -> dict:
    if (value.get("schema") != "v4.intraday_input.v1" or value.get("date") != day
            or value.get("slot") != slot or value.get("source_id") != SOURCE_ID
            or value.get("quote_trade_day") != day
            or (binding_sha256 is not None and value.get("binding_sha256") != binding_sha256)
            or (source_manifest_sha256 is not None and value.get("source_manifest_sha256") != source_manifest_sha256)
            or (cache_root is not None and value.get("cache_root") != cache_root)):
        raise BoundaryError("INTRADAY_INPUT_IDENTITY_MISMATCH")
    start = datetime.fromisoformat(value["acquired_at"]); finish = datetime.fromisoformat(value["finished_at"])
    _window(day, slot, start); _window(day, slot, finish)
    if finish < start or _date(value["prev_date"]) >= day:
        raise BoundaryError("INTRADAY_INPUT_TIME_MISMATCH")
    pct = value["pct"]
    if not isinstance(pct, dict) or not pct or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in pct.values()):
        raise BoundaryError("INTRADAY_QUOTES_UNAVAILABLE")
    previous = value["previous_pool"]
    codes = [row["code"] for row in previous["zt"]]
    if not codes or len(codes) != len(set(codes)) or not set(pct).issubset(codes):
        raise BoundaryError("INTRADAY_COHORT_INVALID")
    source = SafeRoot(state)
    observed = {}; reference_day = None
    live_frames = {}; calendar_dates = []
    raw_refs = value.get("raw_sources")
    if not isinstance(raw_refs, list) or not raw_refs:
        raise BoundaryError("INTRADAY_RAW_PROOF_MISSING")
    for ref in raw_refs:
        obj, _ = _bound(source, ref, "raw/")
        identity = obj.get("identity", {})
        session = identity.get("session")
        if (obj.get("schema") != "v4.vibe_raw.v1" or obj.get("review_target_date") != day
                or session not in {day, value["prev_date"]}):
            raise BoundaryError("INTRADAY_RAW_DATE_MISMATCH")
        if session == day:
            _window(day, slot, datetime.fromisoformat(obj["acquired_at"]))
            if identity.get("params", {}).get("intraday_slot") != slot:
                raise BoundaryError("INTRADAY_RAW_SLOT_MISMATCH")
        result = obj.get("result", {})
        if identity.get("provider") == "akshare" and session == day and result.get("kind") == "SDK_RETURN_FRAME":
            import pandas as pd
            endpoint = identity.get("endpoint")
            if endpoint in {"stock_zt_pool_em", "stock_zt_pool_zbgc_em", "stock_zt_pool_dtgc_em"}:
                if endpoint in live_frames:
                    raise BoundaryError("INTRADAY_AMBIGUOUS_POOL_SOURCE")
                live_frames[endpoint] = pd.DataFrame(result["rows"], columns=result["columns"])
            if (endpoint == "stock_zh_a_hist_tx" and identity.get("params", {}).get("symbol") == trade_calendar._REF_STOCK
                    and "date" in result["columns"]):
                calendar_dates.extend(str(row["date"]) for row in result["rows"] if str(row["date"]) < day)
        if identity.get("provider") == "qt.gtimg.cn" and result.get("kind") == "HTTP_BYTES":
            text = base64.b64decode(result["content_base64"], validate=True).decode("gbk", "ignore")
            for line in text.split(";"):
                fields = line.split("~")
                if len(fields) <= 32:
                    continue
                code = fields[0].split("=")[0].strip().strip('"')[-6:]
                quote_date = fields[30][:8]
                if code == "600000": reference_day = quote_date
                if code in pct:
                    if quote_date != day.replace("-", ""):
                        raise BoundaryError("INTRADAY_QUOTE_DAY_MISMATCH")
                    observed[code] = float(fields[32])
    if reference_day != day.replace("-", "") or any(observed.get(code) != number for code, number in pct.items()):
        raise BoundaryError("INTRADAY_QUOTE_PROOF_MISMATCH")
    if not calendar_dates or sorted(calendar_dates)[-1] != value["prev_date"]:
        raise BoundaryError("INTRADAY_PREVIOUS_SESSION_PROOF_MISMATCH")
    if value.get("live_pool") is not None:
        names = (("zt", "stock_zt_pool_em", market_facts._ZT_MAP),
                 ("zb", "stock_zt_pool_zbgc_em", market_facts._ZB_MAP),
                 ("dt", "stock_zt_pool_dtgc_em", market_facts._DT_MAP))
        if any(endpoint not in live_frames for _, endpoint, _ in names):
            raise BoundaryError("INTRADAY_LIVE_POOL_PROOF_MISSING")
        expected_live = {name: market_facts._df_rows(live_frames[endpoint], mapping) for name, endpoint, mapping in names}
        expected_live["raw"] = {name: market_facts._raw_rows(live_frames[endpoint]) for name, endpoint, _ in names}
        if _plain(expected_live, raw_missing=False) != value["live_pool"]:
            raise BoundaryError("INTRADAY_LIVE_POOL_PROJECTION_MISMATCH")
    cache = SafeRoot(explicit_root(value["cache_root"]))
    if state not in cache.root.parents:
        raise BoundaryError("INTRADAY_CACHE_OUTSIDE_STATE")
    prior_seen = False
    for ref in value.get("cache_sources", []):
        obj, _ = _bound(cache, ref, "cache/market_facts/")
        if obj.get("date") != ref.get("session"):
            raise BoundaryError("INTRADAY_CACHE_DATE_MISMATCH")
        if obj.get("date") == value["prev_date"] and obj.get("pools") == previous:
            prior_seen = True
    if not prior_seen:
        raise BoundaryError("INTRADAY_PREVIOUS_POOL_PROOF_MISSING")
    return {"raw_files_checked": len(raw_refs), "cache_files_checked": len(value["cache_sources"]),
            "quote_day_observed": day, "previous_session_checked_against_raw_calendar": True,
            "live_projection_checked": value.get("live_pool") is not None, "pool_session_evidence": "DECLARED_ONLY_REQUEST_OR_APPROVED_CACHE",
            "sdk_internal_http_calls": "CANNOT_CONFIRM_NOT_INSTRUMENTED"}


def _acquire(
    cfg: dict,
    day: str,
    slot: str,
    now: datetime,
    *,
    transport,
    clock,
    attempt_state_writer=None,
) -> dict:
    ctx = _SlotAuthority(slot=slot, state_root=Path(cfg["state_root"]), cache_root=Path(cfg["cache_root"]),
        cache_manifest_path=Path(cfg["cache_manifest_path"]), cache_manifest_sha256=cfg["cache_manifest_sha256"],
        target_date=day, now=now, transport=transport, attempt_state_writer=attempt_state_writer)
    quote_day = trade_calendar.quote_trade_day(ctx=ctx)
    if now.weekday() >= 5 or quote_day != day:
        raise BoundaryError("INTRADAY_SESSION_NOT_CONFIRMED")
    previous_day = trade_calendar.prev_trade_date(day, ctx=ctx)
    if not previous_day or previous_day >= day:
        raise BoundaryError("INTRADAY_PREVIOUS_SESSION_MISSING")
    previous = market_facts.pools(previous_day, ctx=ctx)
    if previous is None:
        raise BoundaryError("INTRADAY_PREVIOUS_POOL_MISSING")
    # This is the existing cache owner and its generated/migrated inventory,
    # not a second fetch/store. Reading registers the exact evidence reference.
    ctx.cache.read_json("cache/market_facts/" + previous_day + ".json")
    live = _live_pools(ctx)
    pct = emotion_metrics.batch_pct([row["code"] for row in previous["zt"]], ctx=ctx)
    ctx.assert_clean()
    finished = clock().astimezone(SHANGHAI); _window(day, slot, finished)
    result = _plain({"schema": "v4.intraday_input.v1", "date": day, "slot": slot,
        "source_id": SOURCE_ID, "source_manifest_sha256": cfg["source_manifest_sha256"],
        "binding_sha256": cfg["binding_sha256"], "acquired_at": now.isoformat(), "finished_at": finished.isoformat(),
        "quote_trade_day": quote_day, "prev_date": previous_day, "previous_pool": previous, "live_pool": live,
        "pct": pct, "cache_root": cfg["cache_root"], "raw_sources": list(ctx.records.values()),
        "cache_sources": list(ctx.cache.used.values()), "request_counts": ctx.request_counts(), **SAFETY}, raw_missing=False)
    _validate_input(result, state=Path(cfg["state_root"]), day=day, slot=slot, binding_sha256=cfg["binding_sha256"],
                    source_manifest_sha256=cfg["source_manifest_sha256"], cache_root=cfg["cache_root"])
    return result


def aggregate_snapshot(*, date: str, slot: str, now: datetime, prev: str, pp: dict, live: dict | None, pct: dict) -> dict:
    """Original Vibe schema-3 arithmetic/order, extracted without reranking."""
    drift = _window(date, slot, now)
    live_counts = ({"limit_up": len(live["zt"]), "broken": len(live["zb"]),
                    "limit_down": len(live["dt"]),
                    "highest_board": max((int(r.get("boards") or 1) for r in live["zt"]), default=0),
                    "sectors": len({(r.get("sector") or "").strip()
                                    for r in live["zt"] if (r.get("sector") or "").strip()})}
                   if live is not None else None)

    prev_zt = pp["zt"]
    got = [(r, pct[r["code"]]) for r in prev_zt if r["code"] in pct]
    if not got:
        raise BoundaryError("INTRADAY_QUOTES_UNAVAILABLE")

    vals = [v for _, v in got]
    # 按昨日板位分组看强弱 —— 首板和高位板的竞价含义完全不同
    tiers: dict[str, list[float]] = {}
    for r, v in got:
        b = int(r.get("boards") or 1)
        key = "首板" if b == 1 else ("2板" if b == 2 else "3板及以上")
        tiers.setdefault(key, []).append(v)

    # 最高标的客观状态（只列读数，不评价）
    top_board = max((int(r.get("boards") or 1) for r in prev_zt), default=0)
    tops = [{"code": r["code"], "name": r["name"], "boards": int(r.get("boards") or 1),
             "sector": r.get("sector") or "", "pct": round(v, 2)}
            for r, v in got if int(r.get("boards") or 1) == top_board]

    snap = {
        "schema": _SNAP_SCHEMA,
        "date": date,
        "slot": slot,
        "captured_at": now.strftime("%Y-%m-%d %H:%M:%S") + " CST",
        "drift_minutes": drift,      # 真实抓取时刻距标称 slot 差几分钟
        "prev_date": prev,
        "sample": len(vals),
        "avg": round(mean(vals), 2),
        "median": round(median(vals), 2),
        "up_count": sum(1 for v in vals if v > 0),
        "down_count": sum(1 for v in vals if v < 0),
        "up_rate": round(sum(1 for v in vals if v > 0) / len(vals), 3),
        "deep_loss_5": sum(1 for v in vals if v <= -5),
        "by_tier": {
            k: {"sample": len(vs), "avg": round(mean(vs), 2),
                "median": round(median(vs), 2),
                "up_rate": round(sum(1 for v in vs if v > 0) / len(vs), 3)}
            for k, vs in tiers.items()
        },
        "top_boards": tops,
        "top_board_level": top_board,
        # 当时的盘面家数（涨停/炸板/跌停/最高板/题材数）—— 情绪路径靠它
        "live": live_counts,
        # 覆盖率（同 money_effect 口径）：只回来一小半时别拿它当全体读数
        "coverage_rate": round(len(vals) / len(prev_zt), 3) if prev_zt else None,
        "expected_sample": len(prev_zt),
    }
    return snap


def _commit(io: SafeRoot, day: str, slot: str, *, expected_config: str | None = None) -> tuple[dict, dict]:
    prefix = day + "/" + slot.replace(":", "")
    raw = io.read_bytes("receipts/" + prefix + ".json", max_bytes=_LIMIT)
    receipt = _json(raw)
    if (receipt.get("schema") != "v4.intraday_receipt.v1" or receipt.get("status") != "SUCCEEDED"
            or receipt.get("date") != day or receipt.get("slot") != slot
            or (expected_config is not None and receipt.get("config_sha256") != expected_config)):
        raise BoundaryError("INTRADAY_RECEIPT_IDENTITY_MISMATCH")
    manifest, _ = _bound(io, receipt["manifest"], "manifests/" + prefix + ".json")
    snapshot, _ = _bound(io, manifest["artifact"], "artifacts/" + prefix + ".json")
    inputs, _ = _bound(io, manifest["input"], "inputs/")
    if (manifest.get("schema") != "v4.intraday_manifest.v1" or manifest.get("date") != day
            or manifest.get("slot") != slot or manifest.get("config_sha256") != receipt["config_sha256"]
            or manifest.get("binding_sha256") != receipt.get("binding_sha256")
            or manifest.get("source_manifest_sha256") != inputs.get("source_manifest_sha256")):
        raise BoundaryError("INTRADAY_MANIFEST_IDENTITY_MISMATCH")
    proof = _validate_input(inputs, state=io.root.parent, day=day, slot=slot, binding_sha256=manifest["binding_sha256"])
    expected = aggregate_snapshot(date=day, slot=slot, now=datetime.fromisoformat(inputs["acquired_at"]),
        prev=inputs["prev_date"], pp=inputs["previous_pool"], live=inputs["live_pool"], pct=inputs["pct"])
    if snapshot != {**expected, **SAFETY}:
        raise BoundaryError("INTRADAY_AGGREGATE_MISMATCH")
    return snapshot, {"date": day, "slot": slot, "artifact_sha256": manifest["artifact"]["sha256"],
                      "manifest_sha256": receipt["manifest"]["sha256"], "receipt_sha256": digest(raw),
                      "config_sha256": receipt["config_sha256"], "source_id": SOURCE_ID,
                      "verification_scope": "LOCAL_BYTES_RELATIONS_AND_QUOTE_DATES_NOT_VENDOR_TRUTH", **proof}


def capture_intraday(date: str, slot: str, *, config_path: Path, config_sha256: str,
                     source_manifest_sha256: str, transport=None, clock=None) -> dict:
    day = _date(date); slot = _slot(slot)
    clock = clock or (lambda: datetime.now(SHANGHAI))
    cfg = load_intraday_binding(config_path, config_sha256, source_manifest_sha256)
    io = SafeRoot(Path(cfg["state_root"]) / "intraday")
    stem = day + "/" + slot.replace(":", "")
    with io.kernel_lock("locks/" + stem + ".lock", timeout=30):
        try:
            _, proof = _commit(io, day, slot, expected_config=config_sha256)
        except FileNotFoundError:
            pass
        else:
            return {"status": "ALREADY_EXISTS", "date": day, "slot": slot, **proof, **SAFETY}
        try:
            previous_attempt = _read_attempt(io, day, slot, config_sha256)
        except FileNotFoundError:
            previous_attempt = None
        if previous_attempt is not None:
            previous_state = str(previous_attempt["attempt_state"])
            if previous_state != "FAILED_NO_REQUEST":
                raise IntradayAttemptError("INTRADAY_ATTEMPT_NOT_RETRYABLE", previous_state)
        now = clock()
        _window(day, slot, now); now = now.astimezone(SHANGHAI)
        if now.weekday() >= 5:
            raise BoundaryError("INTRADAY_SESSION_NOT_CONFIRMED")
        attempt_state = {"value": "PREPARED"}

        def record_attempt(state: str, error_code: str | None = None) -> None:
            _write_attempt_state(
                io,
                day,
                slot,
                config_sha256,
                state,
                error_code=error_code,
            )
            attempt_state["value"] = state

        try:
            # A failure/crash cannot silently trigger another market acquisition.
            # Reconciliation belongs to the existing local owner, not an HTTP reset.
            record_attempt("PREPARED")
        except Exception as error:
            raise IntradayAttemptError("INTRADAY_ATTEMPT_MARKER_FAILED", "ATTEMPT_UNKNOWN") from error

        try:
            named = cfg["input_bindings"].get(stem)
            if named is not None:
                inputs, _ = _bound(io, named, "inputs/")
                _validate_input(inputs, state=Path(cfg["state_root"]), day=day, slot=slot,
                    binding_sha256=cfg["binding_sha256"], source_manifest_sha256=cfg["source_manifest_sha256"],
                    cache_root=cfg["cache_root"])
                input_ref = named
            else:
                inputs = _acquire(
                    cfg,
                    day,
                    slot,
                    now,
                    transport=transport,
                    clock=clock,
                    attempt_state_writer=record_attempt,
                )
                input_ref = _put(io, "inputs/" + stem + ".json", inputs)
            verify_owned_sources(source_manifest_sha256)
            _validate_input(inputs, state=Path(cfg["state_root"]), day=day, slot=slot,
                binding_sha256=cfg["binding_sha256"], source_manifest_sha256=cfg["source_manifest_sha256"],
                cache_root=cfg["cache_root"])
            snapshot = aggregate_snapshot(date=day, slot=slot, now=datetime.fromisoformat(inputs["acquired_at"]),
                prev=inputs["prev_date"], pp=inputs["previous_pool"], live=inputs["live_pool"], pct=inputs["pct"])
            artifact = _put(io, "artifacts/" + stem + ".json", {**snapshot, **SAFETY})
            manifest = _put(io, "manifests/" + stem + ".json", {"schema": "v4.intraday_manifest.v1", "date": day,
                "slot": slot, "artifact": artifact, "input": input_ref, "source_manifest_sha256": source_manifest_sha256,
                "binding_sha256": cfg["binding_sha256"], "config_sha256": config_sha256, **SAFETY})
            _put(io, "receipts/" + stem + ".json", {"schema": "v4.intraday_receipt.v1", "date": day, "slot": slot,
                "status": "SUCCEEDED", "manifest": manifest, "binding_sha256": cfg["binding_sha256"],
                "config_sha256": config_sha256, **SAFETY})
            _, proof = _commit(io, day, slot, expected_config=config_sha256)
            try:
                record_attempt("SUCCEEDED")
            except Exception as error:
                raise IntradayAttemptError("INTRADAY_ATTEMPT_MARKER_FAILED", "ATTEMPT_UNKNOWN") from error
            return {"status": "SUCCEEDED", "date": day, "slot": slot, **proof, **SAFETY,
                    "attempt_state": "SUCCEEDED"}
        except IntradayAttemptError:
            raise
        except Exception as error:
            current_state = str(attempt_state["value"])
            terminal_state = (
                "REQUEST_ATTEMPTED"
                if current_state in {"REQUEST_IN_FLIGHT", "REQUEST_ATTEMPTED"}
                else "FAILED_NO_REQUEST"
            )
            error_code = _attempt_error_code(error)
            try:
                record_attempt(terminal_state, error_code)
            except Exception:
                terminal_state = "ATTEMPT_UNKNOWN"
            raise IntradayAttemptError(error_code, terminal_state) from error


def _auction(day: str, snapshots: list[dict], review_root: Path | None) -> dict:
    snap = next((row for row in snapshots if row["slot"] == "09:25"), None)
    if snap is None:
        return {"available": False, "date": day, "reason": "09:25 快照缺失；GET 不补抓历史读数"}
    early = []; review_status = "CANNOT_CONFIRM"
    if review_root is not None:
        from domains.daily_research_review import load_daily_research_review
        review = load_daily_research_review(snap["prev_date"].replace("-", ""), review_root=review_root)
        review_status = review["status"]
        for item in review.get("focus", {}).get("verification_items", []):
            key = item.get("metric"); is_early = key == "money_effect_median"
            early.append({"metric": key, "label": "赚钱效应中位数" if is_early else key,
                "expect": item.get("direction"), "early_value": snap["median"] if is_early else None,
                "unit": "%" if is_early else "", "note": "竞价阶段读数（昨日涨停股集合竞价中位涨幅），收盘才定稿" if is_early else "该指标要等盘中/收盘才有读数"})
    return {"available": True, "date": day, "prev_date": snap["prev_date"], "captured_at": snap["captured_at"],
            "overall": {key: snap[key] for key in ("sample", "avg", "median", "up_count", "down_count", "up_rate", "deep_loss_5")},
            "by_tier": snap["by_tier"], "top_boards": snap["top_boards"], "top_board_level": snap["top_board_level"],
            "verification_early": early, "previous_review_status": review_status}


def read_intraday_day(date: str, *, intraday_root: Path | None, review_root: Path | None = None) -> dict:
    """Read only exact committed slots; preserve gaps and never call a provider."""
    day = _date(date)
    result: dict[str, Any] = {"schema": "v4.intraday_view.v1", "date": day, "status": "CANNOT_CONFIRM",
        "slots": [], "evidence": [], "missing_slots": list(SLOTS), "cannot_confirm": [], **SAFETY}
    if intraday_root is None:
        result["cannot_confirm"].append("INTRADAY_ROOT_NOT_BOUND")
    else:
        root = explicit_root(intraday_root)
        if root.name != "intraday":
            raise BoundaryError("INTRADAY_NAMESPACE_REQUIRED")
        io = SafeRoot(root)
        for slot in SLOTS:
            try:
                snap, proof = _commit(io, day, slot)
            except FileNotFoundError:
                result["cannot_confirm"].append("MISSING_SLOT:" + slot)
            except (OSError, ValueError, KeyError, TypeError):
                result["cannot_confirm"].append("INVALID_SLOT_EVIDENCE:" + slot)
            else:
                result["slots"].append(snap); result["evidence"].append(proof)
                result["missing_slots"].remove(slot)
                if snap["live"] is None: result["cannot_confirm"].append("LIVE_POOL_UNAVAILABLE")
                if snap["coverage_rate"] is not None and snap["coverage_rate"] < 1:
                    result["cannot_confirm"].append("QUOTE_COVERAGE_PARTIAL:" + slot)
    result["status"] = "READY" if result["slots"] else "CANNOT_CONFIRM"
    result["cannot_confirm"] = list(dict.fromkeys(result["cannot_confirm"]))
    result["path"] = {"available": bool(result["slots"]), "date": day, "points": [
        {key: snap[key] for key in ("slot", "median", "avg", "up_rate", "deep_loss_5", "live", "coverage_rate")}
        for snap in result["slots"]]}
    result["auction"] = _auction(day, result["slots"], review_root)
    return result
