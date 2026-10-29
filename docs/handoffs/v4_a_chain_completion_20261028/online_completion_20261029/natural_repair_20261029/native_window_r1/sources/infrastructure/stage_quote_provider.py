"""Cutoff-safe stage quote routing owned entirely by V4."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Protocol, Sequence


# The native A opening phase is separate from the historical replay adapter
# above. It uses the existing Stage owner/root and never publishes selections.
NATIVE_A_SCHEMA = "stage_center.a_opening_native_snapshot.v1"


def _opening_clock(value):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    zone = ZoneInfo("Asia/Shanghai")
    return value.replace(tzinfo=zone) if value.tzinfo is None else value.astimezone(zone)


def _opening_now():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def _opening_json(value):
    """Serialize SDK scalars without silently inventing finite market values."""
    import math
    if isinstance(value, dict):
        return {str(k): _opening_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_opening_json(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return {"non_finite_sdk_value": str(value)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "item"):
        return _opening_json(value.item())
    return str(value)


class TdxOpeningQuoteProvider:
    """Original quote RPC fallback; no transaction/history RPC or saved bars."""
    def __init__(self, *, now=_opening_now):
        self.now = now
        self._api = None
        self._host = ""
        self._prepared_day = ""
        self._connection_errors = []

    def prepare(self):
        """Connect in the existing09:24 prephase, without any quote RPC.

        Use the same maintained80-host registry as the existing minute lane.
        A monotonic45-second admission budget and the real09:25 edge bound
        setup; a connection finishing after either deadline is discarded.
        The native quote window uses only an already-connected socket.
        """
        import time
        from pytdx.config.hosts import hq_hosts
        from pytdx.hq import TdxHq_API
        wall = _opening_clock(self.now())
        if self._api is not None and self._prepared_day == wall.strftime("%Y%m%d"):
            return
        self.close()
        edge = wall.replace(hour=9, minute=25, second=0, microsecond=0)
        budget = 45.0
        if wall.hour == 9 and wall.minute in (24, 25):
            budget = min(budget, max(0.0, (edge - wall).total_seconds()))
        deadline = time.monotonic() + budget
        self._connection_errors = []
        for name, host, port in hq_hosts[:80]:
            remaining = deadline - time.monotonic()
            if wall.hour == 9 and wall.minute in (24, 25):
                remaining = min(remaining, (edge - _opening_clock(self.now())).total_seconds())
            if remaining <= 0:
                break
            api = TdxHq_API(heartbeat=False)
            retained = False
            try:
                if not api.connect(host, port, time_out=min(0.5, remaining)):
                    self._connection_errors.append(f"{name}@{host}:{port}:connect returned false")
                    continue
                if time.monotonic() > deadline or (
                    wall.hour == 9 and wall.minute in (24, 25)
                    and _opening_clock(self.now()) >= edge
                ):
                    self._connection_errors.append(f"{name}@{host}:{port}:preparation deadline exceeded")
                    break
                self._api, self._host = api, f"{host}:{port}"
                self._prepared_day = wall.strftime("%Y%m%d")
                retained = True
                return
            except Exception as error:
                self._connection_errors.append(f"{name}@{host}:{port}:{type(error).__name__}:{error}")
            finally:
                if not retained:
                    try:
                        api.disconnect()
                    except Exception:
                        pass
        raise ConnectionError("TDX_NATIVE_PREPARE_UNAVAILABLE:" + ";".join(self._connection_errors))

    def close(self):
        api, self._api = self._api, None
        self._prepared_day = ""
        if api is not None:
            try:
                api.disconnect()
            except Exception:
                pass

    def snapshot(self, symbols, *, trade_date, stage_id, cutoff_at):
        from infrastructure.tdx_minute_replay_provider import _market_and_code
        cutoff = _opening_clock(cutoff_at)
        edge = cutoff.replace(second=0, microsecond=0)
        started = _opening_clock(self.now())
        if (stage_id != "STAGE_0925" or cutoff.strftime("%Y%m%d%H%M%S") != trade_date+"092505"
                or cutoff.microsecond or started.strftime("%Y%m%d") != trade_date
                or not edge <= started <= cutoff):
            raise ValueError("TDX native quote outside exact real09:25 window")
        if self._api is None or self._prepared_day != trade_date:
            raise ValueError("TDX_NATIVE_CONNECTION_NOT_PREPARED")
        rows, raw = [], []
        try:
            for offset in range(0, len(symbols), 80):
                query_started = _opening_clock(self.now())
                if not edge <= query_started <= cutoff:
                    break
                batch = self._api.get_security_quotes([_market_and_code(s) for s in symbols[offset:offset+80]]) or []
                captured = _opening_clock(self.now())
                raw.extend(batch)
                for row in batch:
                    stamp = str(row.get("servertime") or "")
                    if ":" not in stamp and stamp.replace(".", "", 1).isdigit():
                        stamp = stamp.split(".")[0].zfill(6)
                        stamp = f"{stamp[:2]}:{stamp[2:4]}:{stamp[4:6]}"
                    rows.append({"symbol": "A."+str(row.get("code", "")),
                        "source_update_time": f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]} {stamp}",
                        "last_price": row.get("price"), "open_price": row.get("open"),
                        "prev_close_price": row.get("last_close"), "high_price": row.get("high"),
                        "low_price": row.get("low"), "turnover": row.get("amount"), "volume": row.get("vol"),
                        "bid_price1": row.get("bid1"), "ask_price1": row.get("ask1"),
                        "bid_vol1": row.get("bid_vol1"), "ask_vol1": row.get("ask_vol1"),
                        "captured_at": captured.isoformat(), "capture_started_at": query_started.isoformat(),
                        "query_started_at": query_started.isoformat(), "returned_at": captured.isoformat()})
            if not rows:
                raise ValueError("TDX_NATIVE_QUOTES_UNAVAILABLE:EMPTY_QUOTE_RPC:" + self._host)
            return {"rows": rows, "raw_rows": raw, "source": "PYTDX_HQ_READ_ONLY_QUOTES",
                "source_method": "get_security_quotes", "host": self._host,
                "connection_prepared_before_capture": True,
                "connection_preparation_errors": tuple(self._connection_errors),
                "capture_started_at": started.isoformat(), "captured_at": _opening_clock(self.now()).isoformat(),
                "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
        except Exception:
            # A failed prepared socket is not reconnected inside the five-second
            # quote window. The owning prephase always closes both providers.
            self.close()
            raise


class NativeAOpeningSnapshotProvider:
    """Futu-first current quotes with true clocks, used only by the A prephase."""
    def __init__(self, *, primary=None, fallback=None, now=_opening_now, sleep=None):
        import time
        from infrastructure.futu_quote_provider import FutuQuoteProvider
        self.now = now
        self._sleep = time.sleep if sleep is None else sleep
        self.primary = primary if primary is not None else FutuQuoteProvider(now=now)
        self.fallback = fallback if fallback is not None else TdxOpeningQuoteProvider(now=now)
        self._primary_prepare_error = None
        self._fallback_prepare_error = None

    def prepare(self):
        try:
            if hasattr(self.primary, "prepare"):
                self.primary.prepare()
        except Exception as error:
            self._primary_prepare_error = f"FUTU_PREPARE:{type(error).__name__}:{error}"
        # OpenD can initialize successfully yet return future/invalid source
        # clocks at09:25. Prepare the existing fallback before the edge even
        # when the primary context is ready; preparation never requests quotes.
        try:
            if hasattr(self.fallback, "prepare"):
                self.fallback.prepare()
        except Exception as fallback_error:
            self._fallback_prepare_error = f"TDX_PREPARE:{type(fallback_error).__name__}:{fallback_error}"

    def close(self):
        try:
            if hasattr(self.primary, "close"):
                self.primary.close()
        finally:
            if hasattr(self.fallback, "close"):
                self.fallback.close()

    def snapshot(self, symbols, *, trade_date, stage_id="STAGE_0925", cutoff_at=None, capability_only=False):
        import math
        import re
        if stage_id != "STAGE_0925" or not re.fullmatch(r"\d{8}", trade_date):
            raise ValueError("native capture requires exact A STAGE_0925 date")
        codes = tuple(dict.fromkeys(symbols))
        if not codes or any(not re.fullmatch(r"A\.\d{6}", s) for s in codes):
            raise ValueError("native capture requires explicit canonical A codes")
        cutoff = _opening_clock(cutoff_at or f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}T09:25:05+08:00")
        if cutoff.strftime("%Y%m%d%H%M%S") != trade_date+"092505" or cutoff.microsecond:
            raise ValueError("native cutoff must be exact09:25:05 on the target date")
        edge = cutoff.replace(hour=9, minute=25, second=0, microsecond=0)
        started = _opening_clock(self.now())
        if started.strftime("%Y%m%d") != trade_date:
            raise ValueError("native quotes require the real current day")
        if not capability_only and not edge <= started <= cutoff:
            raise ValueError("native capture outside real09:25:00–09:25:05 window")
        batches = []
        errors = [error for error in (self._primary_prepare_error, self._fallback_prepare_error) if error]
        accepted, rejected, seen, quote_codes = [], [], set(), []
        from infrastructure.tdx_minute_replay_provider import _market_and_code
        for code in codes:
            try:_market_and_code(code)
            except ValueError as error:
                errors.append(str(error));rejected.append({"symbol":code,"reason":str(error)})
            else:quote_codes.append(code)

        def accept(row):
            try:
                code = row["symbol"]
                capture_start, captured = _opening_clock(row["capture_started_at"]), _opening_clock(row["captured_at"])
                source_time = _opening_clock(str(row["source_update_time"]))
                price = float(row.get("last_price") or 0)
                if (code not in quote_codes or code in seen or not math.isfinite(price) or price <= 0
                        or not edge <= capture_start <= captured <= cutoff
                        or source_time.strftime("%Y%m%d") != trade_date
                        or not edge <= source_time <= captured):
                    raise ValueError("identity/value/true capture/source time rejected")
                accepted.append(row);seen.add(code)
            except (KeyError, TypeError, ValueError) as error:
                rejected.append({"symbol":row.get("symbol"),"reason":str(error)})

        for offset in (range(0, len(quote_codes), 80) if self._primary_prepare_error is None else ()):
            if not capability_only and _opening_clock(self.now()) > cutoff:
                errors.append("PRIMARY_REAL_CUTOFF_EXCEEDED")
                break
            batch = quote_codes[offset:offset+80]
            try:
                payload = self.primary.snapshot(batch, trade_date=trade_date, stage_id=stage_id, cutoff_at=cutoff.isoformat())
                if (payload.get("trade_date") != trade_date or payload.get("stage_id") != stage_id
                        or any(payload.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))):
                    raise ValueError("native primary identity/safety conflict")
                payload = {**payload, "source_method": "get_market_snapshot"}
                batches.append(payload)
                for row in payload.get("rows", []):
                    accept({**row, "source": payload.get("source"), "source_method": "get_market_snapshot",
                        "capture_started_at": payload["capture_started_at"], "captured_at": payload["captured_at"]})
            except Exception as error:
                errors.append(f"FUTU_BATCH_{offset//80}:{type(error).__name__}:{error}")
        # Presence is not valid evidence: future/zero/invalid primary rows must
        # remain missing while the existing quote fallback can still run in time.
        missing = tuple(s for s in quote_codes if s not in seen)
        if missing and self._fallback_prepare_error is None and not capability_only and _opening_clock(self.now()) <= cutoff:
            try:
                payload = self.fallback.snapshot(missing, trade_date=trade_date, stage_id=stage_id, cutoff_at=cutoff.isoformat())
                batches.append(payload)
                if any(payload.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent")):
                    raise ValueError("native fallback safety conflict")
                for row in payload.get("rows", []):
                    accept({**row, "source": payload.get("source"), "source_method": "get_security_quotes"})
            except Exception as error:
                errors.append(f"TDX_QUOTES:{type(error).__name__}:{error}")
        # A first future/empty response at the edge is not proof that the
        # same authorized snapshot cannot update during the remaining window.
        # At most three extra calls, only for still-missing supported SH/SZ;
        # the original fallback is never queried again. True clocks and accept()
        # remain authoritative, including rejection of late SDK returns.
        for retry in range(3):
            missing = tuple(s for s in quote_codes if s not in seen)
            if not missing or capability_only or self._primary_prepare_error is not None:
                break
            wall = _opening_clock(self.now())
            if not edge <= wall < cutoff or (cutoff-wall).total_seconds() <= 0.5:
                break
            self._sleep(0.5)
            if not edge <= _opening_clock(self.now()) < cutoff:
                break
            batch = list(missing[:80])
            try:
                payload = self.primary.snapshot(batch, trade_date=trade_date, stage_id=stage_id, cutoff_at=cutoff.isoformat())
                if (payload.get("trade_date") != trade_date or payload.get("stage_id") != stage_id
                        or any(payload.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))):
                    raise ValueError("native primary identity/safety conflict")
                payload = {**payload, "source_method": "get_market_snapshot"}
                batches.append(payload)
                for row in payload.get("rows", []):
                    accept({**row, "source": payload.get("source"), "source_method": "get_market_snapshot",
                        "capture_started_at": payload["capture_started_at"], "captured_at": payload["captured_at"]})
            except Exception as error:
                errors.append(f"FUTU_RETRY_{retry+1}:{type(error).__name__}:{error}")
        finished = _opening_clock(self.now())
        return _opening_json({"schema_version": NATIVE_A_SCHEMA, "trade_date": trade_date, "stage_id": stage_id,
            "capture_started_at": started.isoformat(), "captured_at": finished.isoformat(), "market_cutoff_at": cutoff.isoformat(),
            "capture_mode": "CAPABILITY_ONLY_NOT_0925_REPLAY" if capability_only else "NATURAL",
            "temporal_cutoff_safe": not capability_only and edge <= started <= finished <= cutoff,
            "requested_symbols": codes, "rows": accepted, "raw_batches": batches,
            "rejected_rows": rejected, "errors": errors, "missing_symbols": [s for s in codes if s not in seen],
            "data_level": "NATIVE_QUOTE_SNAPSHOT_VISIBLE_L1_NOT_L2_NOT_TRANSACTION",
            "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False})


def write_native_a_opening_snapshot(root, payload, candidate):
    import hashlib
    import json
    from infrastructure.owned_io import SafeRoot
    if (payload.get("schema_version") != NATIVE_A_SCHEMA or payload.get("capture_mode") != "NATURAL"
            or payload.get("temporal_cutoff_safe") is not True
            or payload.get("trade_date") != candidate.trade_date
            or tuple(payload.get("requested_symbols", ())) != tuple(candidate.codes)
            or any(payload.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))):
        raise ValueError("native publication requires original candidate and real timely capture")
    raw = json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",", ":"),allow_nan=False).encode()
    digest = hashlib.sha256(raw).hexdigest()
    relative = f"native_opening/{candidate.trade_date}/STAGE_0925"
    manifest = {"schema_version": NATIVE_A_SCHEMA+".manifest", "trade_date": candidate.trade_date,
        "stage_id": "STAGE_0925", "artifact_relative": relative+"/snapshot.json", "artifact_sha256": digest,
        "candidate_current_sha256": candidate.current_sha256, "candidate_run_id": candidate.run_id,
        "requested_rows": len(candidate.codes), "captured_at": payload["captured_at"],
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    io=SafeRoot(root)
    # Immutable one-slot commit: manifest is last; partial files never authorize
    # consumption. Original native bytes are never replaced by a retry.
    io.write_bytes(relative+"/snapshot.json",raw,require_absent=True)
    io.write_bytes(relative+"/manifest.json",json.dumps(manifest,sort_keys=True,separators=(",", ":")).encode(),require_absent=True)
    return manifest


def read_native_a_opening_snapshot(root, candidate):
    import hashlib
    import json
    from infrastructure.owned_io import SafeRoot
    io=SafeRoot(root)
    relative=f"native_opening/{candidate.trade_date}/STAGE_0925"
    manifest=json.loads(io.read_bytes(relative+"/manifest.json"))
    raw=io.read_bytes(relative+"/snapshot.json")
    payload=json.loads(raw)
    if (manifest.get("schema_version") != NATIVE_A_SCHEMA+".manifest"
            or manifest.get("trade_date") != candidate.trade_date or manifest.get("stage_id") != "STAGE_0925"
            or manifest.get("requested_rows") != len(candidate.codes)
            or any(manifest.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))
            or manifest.get("artifact_relative") != relative+"/snapshot.json"
            or manifest.get("artifact_sha256") != hashlib.sha256(raw).hexdigest()
            or manifest.get("candidate_current_sha256") != candidate.current_sha256
            or manifest.get("candidate_run_id") != candidate.run_id
            or manifest.get("captured_at") != payload.get("captured_at")
            or payload.get("trade_date") != candidate.trade_date
            or payload.get("stage_id") != "STAGE_0925" or payload.get("schema_version") != NATIVE_A_SCHEMA
            or tuple(payload.get("requested_symbols", ())) != tuple(candidate.codes)
            or payload.get("capture_mode") != "NATURAL" or payload.get("temporal_cutoff_safe") is not True
            or any(payload.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))):
        raise ValueError("native snapshot identity/SHA/clock contract mismatch")
    start,captured,cutoff=map(_opening_clock,(payload["capture_started_at"],payload["captured_at"],payload["market_cutoff_at"]))
    if (cutoff.strftime("%Y%m%d%H%M%S") != candidate.trade_date+"092505"
            or not cutoff.replace(second=0,microsecond=0)<=start<=captured<=cutoff):
        raise ValueError("native snapshot real capture clock is not punctual")
    seen=set()
    for row in payload.get("rows", ()):
        code=row.get("symbol")
        row_start,row_end,source_time=map(_opening_clock,(row["capture_started_at"],row["captured_at"],row["source_update_time"]))
        if (code not in candidate.codes or code in seen
                or row.get("source_method") not in {"get_market_snapshot", "get_security_quotes"}
                or not start<=row_start<=row_end<=captured
                or not cutoff.replace(second=0,microsecond=0)<=source_time<=row_end):
            raise ValueError("native row identity/query/capture/source clock rejected")
        seen.add(code)
    return payload, manifest


def precapture_native_a_opening(config, trade_date, *, sleep, now=_opening_now, provider=None):
    """One native prephase, one per-date owner, no StageRaw/selection writes."""
    import hashlib
    import json
    from pathlib import Path
    import time
    from uuid import uuid4
    from infrastructure.owned_io import SafeRoot
    from stage_center.candidate_input import read_candidate_input
    from stage_center.runner import SlotLock
    flags = {"RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    wall = _opening_clock(now())
    cutoff = _opening_clock(f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}T09:25:05+08:00")
    edge = cutoff.replace(second=0, microsecond=0)
    if (wall.strftime("%Y%m%d") != trade_date or not edge.replace(minute=24) <= wall <= cutoff
            or any(config.get("safety", {}).get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))):
        return {"status": "CANNOT_CONFIRM", "error": "A_NATIVE_REAL_PRECAPTURE_WINDOW_OR_SAFETY_INVALID", "write_performed": False, **flags}
    root = Path(config["a_auction_root"]).expanduser().resolve()
    candidate = read_candidate_input(Path(config["candidate_acquisition_root"]), trade_date)
    lock = SlotLock(root/"native_opening"/trade_date/"STAGE_0925"/"capture.lock")
    if not lock.acquire():
        return {"status": "SKIPPED_SLOT_LOCKED", "write_performed": False, **flags}
    provider = provider or NativeAOpeningSnapshotProvider(now=now)
    attempt_id = uuid4().hex
    relative = f"native_opening/{trade_date}/STAGE_0925/attempts/{attempt_id}.json"
    record = {"trade_date": trade_date, "stage_id": "STAGE_0925", "attempt_id": attempt_id,
        "candidate_current_sha256": candidate.current_sha256, "candidate_run_id": candidate.run_id,
        "invoked_at": wall.isoformat(), "authorizes_selection": False, **flags}
    try:
        try:
            prior, manifest = read_native_a_opening_snapshot(root, candidate)
        except FileNotFoundError:
            pass
        else:
            return {"status": "NOOP_ALREADY_VERIFIED", "native_manifest": manifest, "write_performed": False, **flags}
        provider.prepare()  # Context only; no quote request before the boundary.
        wait_started = time.monotonic()
        while _opening_clock(now()) < edge:
            if time.monotonic()-wait_started > 65:
                raise ValueError("A_NATIVE_PRECAPTURE_CLOCK_WAIT_EXCEEDED")
            sleep(min(0.25, (edge-_opening_clock(now())).total_seconds()))
        read_candidate_input(Path(config["candidate_acquisition_root"]), trade_date, expected_current_sha256=candidate.current_sha256)
        payload = provider.snapshot(candidate.codes, trade_date=trade_date, cutoff_at=cutoff.isoformat())
        record["payload"] = payload
        read_candidate_input(Path(config["candidate_acquisition_root"]), trade_date, expected_current_sha256=candidate.current_sha256)
        if payload.get("temporal_cutoff_safe") is not True:
            raise ValueError("A_NATIVE_CAPTURE_FINISHED_AFTER_REAL_CUTOFF")
        if not payload.get("rows"):
            raise ValueError("A_NATIVE_NO_VALID_OBSERVATION_ROWS")
        manifest = write_native_a_opening_snapshot(root, payload, candidate)
        record.update(status="READY" if payload["rows"] else "READY_EMPTY", manifest=manifest)
        return {"status": record["status"], "native_manifest": manifest,
            "accepted_rows": len(payload["rows"]), "write_performed": True, **flags}
    except Exception as error:
        record.update(status="CANNOT_CONFIRM", error=f"{type(error).__name__}:{error}")
        return {"status": "CANNOT_CONFIRM", "error": record["error"], "attempt_evidence": str(root/relative), "write_performed": False, **flags}
    finally:
        try:
            record["finished_at"] = _opening_clock(now()).isoformat()
            raw = json.dumps(_opening_json(record),ensure_ascii=False,sort_keys=True,separators=(",", ":"),allow_nan=False).encode()
            SafeRoot(root).write_bytes(relative, raw, require_absent=True)
        finally:
            try:
                provider.close()
            finally:
                lock.release()


class QuoteSource(Protocol):
    def snapshot(
        self,
        symbols: Sequence[str],
        *,
        trade_date: str,
        stage_id: str,
        cutoff_at: str,
    ) -> dict[str, Any]: ...


class ReferenceSource(Protocol):
    def read_reference_workbench(
        self,
        trade_date: str,
        stage_id: str,
    ) -> dict[str, Any] | None: ...


class StageQuoteProvider:
    """Prefer punctual OpenD; otherwise combine A replay with HK stage evidence."""

    _PRIMARY_BATCH_SIZE = 220

    def __init__(
        self,
        *,
        primary: QuoteSource,
        a_replay: QuoteSource,
        references: ReferenceSource,
        hk_replay: QuoteSource | None = None,
    ) -> None:
        self._primary = primary
        self._a_replay = a_replay
        self._references = references
        self._hk_replay = hk_replay

    def snapshot(
        self,
        symbols: Sequence[str],
        *,
        trade_date: str,
        stage_id: str,
        cutoff_at: str,
    ) -> dict[str, Any]:
        if stage_id == "STAGE_0925":
            return self._tdxpy_auction_snapshot(
                symbols,
                trade_date=trade_date,
                stage_id=stage_id,
                cutoff_at=cutoff_at,
            )
        primary_error = ""
        try:
            primary = self._primary_snapshot(
                symbols,
                trade_date=trade_date,
                stage_id=stage_id,
                cutoff_at=cutoff_at,
            )
            if primary.get("temporal_cutoff_safe") is True:
                return primary
            primary_error = "FUTU_SNAPSHOT_CAPTURED_AFTER_STAGE_CUTOFF"
        except Exception as error:
            primary_error = f"FUTU_SNAPSHOT_FAILED: {type(error).__name__}: {error}"

        requested_a = sorted(symbol for symbol in symbols if str(symbol).startswith("A."))
        requested_hk = any(str(symbol).startswith("HK.") for symbol in symbols)
        rows: list[dict[str, Any]] = []
        sources: list[str] = []
        cannot_confirm = [primary_error]
        if requested_a:
            replay = self._a_replay.snapshot(
                requested_a,
                trade_date=trade_date,
                stage_id=stage_id,
                cutoff_at=cutoff_at,
            )
            rows.extend(deepcopy(replay.get("rows", [])))
            sources.append(str(replay.get("source") or "PYTDX_A_SHARE_1MIN_REPLAY"))
            cannot_confirm.extend(replay.get("cannot_confirm", []))

        if requested_hk:
            hk_rows, hk_source = self._hk_stage_rows(
                symbols,
                trade_date=trade_date,
                stage_id=stage_id,
                cutoff_at=cutoff_at,
            )
            rows.extend(hk_rows)
            if hk_rows:
                sources.append(hk_source)
                cannot_confirm.append(
                    "HK_STAGE_ROWS_FROM_HKCONNECT_STAGE_REPLAY"
                    if hk_source == "V3_5_HKCONNECT_AGGREGATED_STAGE_REPLAY"
                    else "HK_STAGE_ROWS_FROM_LOCAL_MIGRATED_REFERENCE"
                )
            else:
                cannot_confirm.append("HK_CUTOFF_SAFE_STAGE_EVIDENCE_UNAVAILABLE")

        return {
            "schema_version": "v3_5.read_only_quote_batch.v1",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "captured_at": cutoff_at,
            "temporal_cutoff_safe": True,
            "source": "V3_5_CUTOFF_SAFE_COMPOSITE",
            "component_sources": sources,
            "cannot_confirm": cannot_confirm,
            "rows": rows,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    def _tdxpy_auction_snapshot(
        self,
        symbols: Sequence[str],
        *,
        trade_date: str,
        stage_id: str,
        cutoff_at: str,
    ) -> dict[str, Any]:
        """Use the user-locked V3 tdxpy lane for A-share 09:25 evidence."""
        requested_a = sorted(symbol for symbol in symbols if str(symbol).startswith("A."))
        requested_hk = any(str(symbol).startswith("HK.") for symbol in symbols)
        rows: list[dict[str, Any]] = []
        sources: list[str] = []
        cannot_confirm: list[str] = []
        futu_rescue_used = False
        if requested_a:
            try:
                auction = self._a_replay.snapshot(
                    requested_a,
                    trade_date=trade_date,
                    stage_id=stage_id,
                    cutoff_at=cutoff_at,
                )
                if auction.get("temporal_cutoff_safe") is not True:
                    raise ValueError("tdxpy 09:25 evidence is not temporal cutoff safe")
            except Exception as error:
                tdxpy_error = (
                    f"A_SHARE_0925_TDXPY_FAILED: {type(error).__name__}: {error}"
                )
                try:
                    rescue = self._primary_snapshot(
                        requested_a,
                        trade_date=trade_date,
                        stage_id=stage_id,
                        cutoff_at=cutoff_at,
                    )
                    if rescue.get("trade_date") != trade_date or rescue.get("stage_id") != stage_id:
                        raise ValueError("Futu 09:25 rescue identity mismatch")
                    if rescue.get("temporal_cutoff_safe") is not True:
                        raise ValueError("Futu 09:25 rescue captured after stage cutoff")
                    unsafe = [
                        key
                        for key in ("production_allowed", "buy_gate_updated", "orders_sent")
                        if rescue.get(key) is not False
                    ]
                    if unsafe:
                        raise ValueError(
                            "Futu 09:25 rescue safety flags must be false: "
                            + ", ".join(unsafe)
                        )
                    rescue_rows = [
                        deepcopy(row)
                        for row in rescue.get("rows", [])
                        if isinstance(row, dict)
                    ]
                    returned = {str(row.get("symbol") or "") for row in rescue_rows}
                    if returned != set(requested_a):
                        missing = sorted(set(requested_a) - returned)
                        raise ValueError(
                            "Futu 09:25 rescue missing requested symbols: "
                            + ", ".join(missing)
                        )
                except Exception as rescue_error:
                    cannot_confirm.append(
                        f"A_SHARE_0925_EVIDENCE_FAILED: {type(error).__name__}: {error}"
                    )
                    cannot_confirm.append(
                        "FUTU_0925_RESCUE_FAILED: "
                        f"{type(rescue_error).__name__}: {rescue_error}"
                    )
                else:
                    rows.extend(rescue_rows)
                    sources.append(
                        str(rescue.get("source") or "FUTU_OPEND_READ_ONLY_SNAPSHOT")
                    )
                    cannot_confirm.extend(
                        [
                            tdxpy_error,
                            "FUTU_0925_READ_ONLY_SNAPSHOT_NOT_AUCTION_ORDER_BOOK",
                        ]
                    )
                    futu_rescue_used = True
            else:
                rows.extend(deepcopy(auction.get("rows", [])))
                sources.append(
                    str(auction.get("source") or "PYTDX_A_SHARE_0925_HISTORY_TRANSACTION")
                )
                cannot_confirm.extend(auction.get("cannot_confirm", []))
        if requested_hk:
            hk_rows, hk_source = self._hk_stage_rows(
                symbols,
                trade_date=trade_date,
                stage_id=stage_id,
                cutoff_at=cutoff_at,
            )
            rows.extend(hk_rows)
            if hk_rows:
                sources.append(hk_source)
                cannot_confirm.append(
                    "HK_STAGE_ROWS_FROM_HKCONNECT_STAGE_REPLAY"
                    if hk_source == "V3_5_HKCONNECT_AGGREGATED_STAGE_REPLAY"
                    else "HK_STAGE_ROWS_FROM_LOCAL_MIGRATED_REFERENCE"
                )
            else:
                cannot_confirm.append("HK_CUTOFF_SAFE_STAGE_EVIDENCE_UNAVAILABLE")
        return {
            "schema_version": "v3_5.read_only_quote_batch.v1",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "captured_at": cutoff_at,
            "temporal_cutoff_safe": True,
            "source": (
                "V3_5_0925_CUTOFF_SAFE_COMPOSITE"
                if futu_rescue_used
                else "V3_5_TDXPY_0925_COMPOSITE"
            ),
            "component_sources": sources,
            "cannot_confirm": cannot_confirm,
            "rows": rows,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    def _hk_stage_rows(
        self,
        symbols: Sequence[str],
        *,
        trade_date: str,
        stage_id: str,
        cutoff_at: str,
    ) -> tuple[list[dict[str, Any]], str]:
        requested_hk = sorted(symbol for symbol in symbols if str(symbol).startswith("HK."))
        if self._hk_replay is not None and requested_hk:
            try:
                replay = self._hk_replay.snapshot(
                    requested_hk,
                    trade_date=trade_date,
                    stage_id=stage_id,
                    cutoff_at=cutoff_at,
                )
            except FileNotFoundError:
                replay = None
            if replay is not None and replay.get("rows"):
                return (
                    [deepcopy(row) for row in replay["rows"]],
                    "V3_5_HKCONNECT_AGGREGATED_STAGE_REPLAY",
                )
        reference = self._references.read_reference_workbench(trade_date, stage_id)
        reference_rows = reference.get("unified_rows", []) if reference else []
        return (
            [
                self._reference_hk_row(row)
                for row in reference_rows
                if isinstance(row, dict)
                and str(row.get("market") or "").upper() == "HK"
            ],
            "V3_5_MIGRATED_REFERENCE_SNAPSHOT",
        )

    def _primary_snapshot(
        self,
        symbols: Sequence[str],
        *,
        trade_date: str,
        stage_id: str,
        cutoff_at: str,
    ) -> dict[str, Any]:
        if not symbols:
            raise ValueError("stage quote snapshot requires at least one symbol")
        batches = [
            symbols[index : index + self._PRIMARY_BATCH_SIZE]
            for index in range(0, len(symbols), self._PRIMARY_BATCH_SIZE)
        ]
        payloads = [
            self._primary.snapshot(
                batch,
                trade_date=trade_date,
                stage_id=stage_id,
                cutoff_at=cutoff_at,
            )
            for batch in batches
        ]
        primary = deepcopy(payloads[0])
        primary["rows"] = [
            deepcopy(row)
            for payload in payloads
            for row in payload.get("rows", [])
        ]
        primary["temporal_cutoff_safe"] = all(
            payload.get("temporal_cutoff_safe") is True for payload in payloads
        )
        return primary

    @staticmethod
    def _reference_hk_row(source: dict[str, Any]) -> dict[str, Any]:
        row = deepcopy(source)
        row["symbol"] = str(row.get("symbol") or row.get("code") or "")
        if row.get("pct_chg") in ("", None):
            row["pct_chg"] = row.get("current_change_pct")
        row["data_level"] = "MIGRATED_REFERENCE_WORKBENCH"
        row["recommendation_status"] = "WATCH_ONLY"
        return row
