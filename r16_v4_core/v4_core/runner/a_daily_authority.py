"""Validate the official A-share slice and publish only the approved day delta."""
from __future__ import annotations

from hashlib import file_digest, sha256
import json
import math
import os
from pathlib import Path
import re
from typing import Any

from v4_core.ingest.a_share_tdx import TDX_DAY_STRUCT, parse_tdx_day_bytes
from v4_core.runner.evidence import DatedInputs, EvidenceError, SAFETY_FLAGS, iso_date, mapping, require, symbol
from v4_core.runner.state import ConcurrentHistoryChange, WriterLease, discard_published_file, file_identity, json_bytes, publish_bytes
from v4_core.storage.db import V4Store, date_variants

_OHLC = ("open", "high", "low", "close")
_NATIVE_DAY = re.compile(r"(sh|sz|bj)(\d{6})\.day", re.I)
_DIGEST = re.compile(r"[0-9a-f]{64}")
_NATIVE_EXCHANGES = {0: "SZ", 1: "SH", 2: "BJ"}
_ALLOWED_REASONS = {
    "TARGET_DATE_MISSING", "INVALID_BAR:non_positive_ohlc", "SUSPENSION_SOURCE_STALE_REVERIFY_REQUIRED",
}


def _native_symbol(raw: dict[str, Any]) -> str:
    exchange = _NATIVE_EXCHANGES.get(raw.get("market"))
    require(exchange is not None, "A_COVERAGE_RECEIPT_MARKET_UNRECOGNIZED")
    text = str(raw.get("symbol", ""))
    return symbol(f"{text}.{exchange}" if text.isdigit() else text, "A")


def _native_reason(raw: dict[str, Any]) -> str:
    code = raw.get("reason_code")
    if code == "INVALID_BAR":
        failure = raw.get("failure_type")
        return "INVALID_BAR:non_positive_ohlc" if failure == "invalid_bar:non_positive_ohlc" else str(code)
    return str(code)


def _a_rows(data: object, day: str) -> dict[str, dict]:
    require(isinstance(data, list), "A_TARGET_BARS_MUST_BE_ARRAY")
    bars: dict[str, dict] = {}
    for value in data:
        row = mapping(value, "A_TARGET_BAR_INVALID")
        code = symbol(row.get("symbol"), "A")
        require(row.get("market", "A") == "A" and iso_date(row.get("trade_date")) == day and code not in bars,
                "A_TARGET_BAR_DATE_MARKET_OR_DUPLICATE")
        try:
            prices = {key: float(row[key]) for key in _OHLC}
            amount = float(row["amount"])
            volume = int(row["volume"])
            previous = float(row["pre_close"]) if row.get("pre_close") is not None else None
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise EvidenceError("A_TARGET_BAR_INVALID") from exc
        require(all(math.isfinite(val) and val > 0 for val in prices.values())
                and math.isfinite(amount) and amount >= 0 and type(row["volume"]) is int and 0 <= volume <= 2**63 - 1
                and (previous is None or math.isfinite(previous) and previous >= 0),
                "A_ACCEPTED_BAR_VALUES_INVALID")
        bars[code] = {"market": "A", "symbol": code, "trade_date": day, **prices,
                      "amount": amount, "volume": volume, "pre_close": previous}
    return bars


def _review_quarantine(
    inputs: DatedInputs, raw: object, expected: dict[str, str], failed: dict[str, dict], coverage_sha: str,
) -> dict[str, dict]:
    require(isinstance(raw, list), "A_QUARANTINE_ALLOWLIST_UNAVAILABLE")
    checked: dict[str, dict] = {}
    for value in raw:
        entry = mapping(value, "A_QUARANTINE_ROW_INVALID")
        code = symbol(entry.get("symbol"), "A")
        reason = entry.get("reason")
        require(code not in checked and reason in _ALLOWED_REASONS and expected.get(code) == reason,
                "A_QUARANTINE_NOT_IN_AUTHORITY")
        evidence = inputs.file(entry.get("evidence"))
        record = mapping(evidence.json(), "A_QUARANTINE_EVIDENCE_INVALID")
        require(iso_date(record.get("trade_date")) == inputs.trade_date and symbol(record.get("symbol"), "A") == code
                and record.get("market") == "A" and record.get("reason") == reason
                and record.get("coverage_receipt_sha256") == coverage_sha
                and _DIGEST.fullmatch(str(record.get("source_sha256", "")))
                and record["source_sha256"] == failed[code].get("source_sha256_after")
                and record.get("classification_status") == "CANNOT_CONFIRM", "A_QUARANTINE_EVIDENCE_MISMATCH")
        raw_response = inputs.file(record["raw_response"]).identity() if record.get("raw_response") else None
        if reason == "INVALID_BAR:non_positive_ohlc":
            bar = mapping(record.get("bar"), "A_QUARANTINE_BAR_MISSING")
            require(all(type(bar.get(key)) in {int, float} and math.isfinite(bar[key]) for key in _OHLC)
                    and min(bar[key] for key in _OHLC) <= 0, "A_QUARANTINE_BAR_CAUSE_MISMATCH")
        if reason == "TARGET_DATE_MISSING":
            require(iso_date(record.get("latest_trade_date")) < inputs.trade_date, "A_QUARANTINE_DATE_CAUSE_MISMATCH")
        if reason == "SUSPENSION_SOURCE_STALE_REVERIFY_REQUIRED":
            require(iso_date(record.get("suspension_source_date")) < inputs.trade_date
                    and record.get("current_suspension_verified") is False,
                    "A_QUARANTINE_SUSPENSION_SOURCE_NOT_STALE")
        checked[code] = {"reason": reason, "evidence": evidence.identity(),
                         "source_sha256": record["source_sha256"], "raw_response": raw_response,
                         "halt_or_delist_status": "CANNOT_CONFIRM"}
    require(checked.keys() == expected.keys(), "A_QUARANTINE_ALLOWLIST_NOT_COMPLETE")
    return checked


def _verify_native_bars(
    entry: dict, official: dict[str, tuple[str, str]], bars: dict[str, dict], day: str,
) -> None:
    root = entry.get("native_source_root")
    require(isinstance(root, str) and Path(root).is_absolute(), "A_NATIVE_SOURCE_ROOT_UNBOUND")
    vendor_root = Path(root).resolve()
    require(vendor_root.is_dir(), "A_NATIVE_SOURCE_ROOT_UNAVAILABLE")
    record_size = TDX_DAY_STRUCT.size
    for code, (relative, digest) in official.items():
        path = (vendor_root / relative).resolve()
        require(path.is_relative_to(vendor_root), f"A_NATIVE_SOURCE_ESCAPES_ROOT:{code}")
        try:
            with path.open("rb") as stream:
                before = os.fstat(stream.fileno())
                size = before.st_size
                require(size >= record_size and size % record_size == 0, f"A_NATIVE_SOURCE_LENGTH_INVALID:{code}")
                actual = file_digest(stream, "sha256").hexdigest()
                length = min(size, record_size * 2)
                stream.seek(-length, os.SEEK_END)
                tail = stream.read(length)
                after = os.fstat(stream.fileno())
        except OSError as exc:
            raise EvidenceError(f"A_NATIVE_SOURCE_UNAVAILABLE:{code}") from exc
        require(actual == digest and len(tail) == length and all(
            getattr(before, f"st_{field}") == getattr(after, f"st_{field}")
            for field in ("dev", "ino", "size", "mtime_ns", "ctime_ns")
        ), f"A_NATIVE_SOURCE_SHA_OR_IDENTITY_MISMATCH:{code}")
        try:
            native_rows = parse_tdx_day_bytes(tail, code)
        except ValueError as exc:
            raise EvidenceError(f"A_NATIVE_SOURCE_LAST_RECORD_INVALID:{code}") from exc
        target = native_rows[-1]
        previous = native_rows[-2] if len(native_rows) == 2 else None
        require(target["trade_date"] == day and (previous is None or iso_date(previous["trade_date"]) < day),
                f"A_NATIVE_SOURCE_DATE_MISMATCH:{code}")
        if previous is not None:
            target["pre_close"] = previous["close"]
        require(target == bars[code], f"A_PROJECTED_BAR_DIFFERS_FROM_NATIVE_SOURCE:{code}")


def validate_a_daily(inputs: DatedInputs) -> tuple[dict[str, Any], list[dict], dict[str, dict]]:
    day = inputs.trade_date
    entry = inputs.entry("a_daily")
    manifest_file = inputs.file(entry.get("authority"))
    coverage_file = inputs.file(entry.get("coverage_receipt"))
    bars_file = inputs.file(entry.get("bars"))
    manifest = mapping(manifest_file.json(), "A_FORMULA_AUTHORITY_INVALID")
    coverage = mapping(coverage_file.json(), "A_COVERAGE_RECEIPT_INVALID")
    require(iso_date(manifest.get("target_date")) == iso_date(coverage.get("target_date")) == day,
            "A_AUTHORITY_TRADE_DATE_MISMATCH")
    require(all(manifest.get(key) is False for key in SAFETY_FLAGS if key != "research_only"),
            "A_FORMULA_AUTHORITY_UNSAFE")
    require((manifest.get("authority_status"), coverage.get("status")) in {
        ("REBUILD_REQUIRED", "PARTIAL"), ("READY", "READY"),
    }, "A_AUTHORITY_STATUS_UNRECOGNIZED")
    scope = mapping(coverage.get("scope_eligibility"), "A_COVERAGE_SCOPE_UNAVAILABLE")
    official_files = manifest.get("files")
    declared = entry.get("accepted_symbols")
    require(isinstance(official_files, list) and isinstance(declared, list) and declared,
            "A_AUTHORITY_ACCEPTED_SET_UNAVAILABLE")
    official: dict[str, tuple[str, str]] = {}
    for value in official_files:
        item = mapping(value, "A_FORMULA_FILE_INVALID")
        relative = str(item.get("relative_path", ""))
        match = _NATIVE_DAY.fullmatch(Path(relative).name)
        digest = item.get("sha256")
        require(match and isinstance(digest, str) and _DIGEST.fullmatch(digest), "A_FORMULA_FILE_IDENTITY_INVALID")
        exchange, code = match.groups()
        canonical = symbol(f"{code}.{exchange}", "A")
        require(canonical not in official, "A_FORMULA_FILE_IDENTITY_DUPLICATE")
        file_name = f"{exchange.lower()}{code}.day"
        expected_path = f"{exchange.lower()}/lday/{file_name}"
        require(relative == f"vipdoc/{expected_path}", "A_FORMULA_FILE_PATH_INVALID")
        official[canonical] = (relative, digest)
    reconciliation = mapping(coverage.get("reconciliation"), "A_RECONCILIATION_UNAVAILABLE").get("symbols")
    require(isinstance(reconciliation, list), "A_RECONCILIATION_SYMBOLS_UNAVAILABLE")
    reconciled: dict[str, str] = {}
    failed: dict[str, dict] = {}
    for row in reconciliation:
        if not isinstance(row, dict) or row.get("market") not in _NATIVE_EXCHANGES:
            continue
        code = _native_symbol(row)
        if row.get("target_date_ready") is True:
            require(code not in reconciled, "A_RECONCILIATION_SYMBOL_DUPLICATE")
            reconciled[code] = row.get("source_sha256_after")
        elif row.get("reason_code") in {"INVALID_BAR", *_ALLOWED_REASONS}:
            require(code not in failed, "A_QUARANTINE_RECONCILIATION_DUPLICATE")
            failed[code] = row
    accepted_codes = {symbol(item, "A") for item in declared}
    bars = _a_rows(bars_file.json(), day)
    require({code: value[1] for code, value in official.items()} == reconciled
            and official.keys() == accepted_codes == bars.keys()
            and len(declared) == len(accepted_codes) == coverage.get("accepted_count")
            and len(accepted_codes) == coverage.get("accepted_target_date_file_count"),
            "A_ACCEPTED_AUTHORITY_SETS_MISMATCH")
    unresolved_raw = scope.get("unresolved_eligible")
    require(isinstance(unresolved_raw, list), "A_UNRESOLVED_ELIGIBLE_UNAVAILABLE")
    unresolved = {}
    for row in unresolved_raw:
        code = _native_symbol(mapping(row, "A_UNRESOLVED_ELIGIBLE_ROW_INVALID"))
        require(code in failed and row.get("reason_code") == failed[code].get("reason_code"),
                "A_QUARANTINE_RECONCILIATION_MISMATCH")
        unresolved[code] = _native_reason(failed[code])
    eligible = scope.get("eligible_target_count")
    nominal = coverage.get("target_count")
    require(type(nominal) is int and type(eligible) is int and nominal >= eligible > 0
            and len(unresolved_raw) == len(unresolved) == scope.get("unresolved_eligible_count")
            and len(accepted_codes) + len(unresolved) == eligible and not (accepted_codes & unresolved.keys())
            and bool(unresolved) == (coverage["status"] == "PARTIAL"), "A_ELIGIBLE_AUTHORITY_SET_MISMATCH")
    quarantine = _review_quarantine(inputs, entry.get("quarantine"), unresolved, failed, coverage_file.sha256)
    _verify_native_bars(entry, official, bars, day)
    rows = [bars[code] for code in sorted(bars)]
    detail = {
        "status": "PARTIAL" if quarantine else "READY", "trade_date": day, "accepted_count": len(rows),
        "eligible_count": eligible, "nominal_count": nominal, "quarantined_count": len(quarantine),
        "quarantine": [{"symbol": code, **record} for code, record in sorted(quarantine.items())],
        "source_identity": {"authority": manifest_file.identity(), "coverage_receipt": coverage_file.identity(),
                            "bars": bars_file.identity(), "source_binding_sha256": inputs.entry_sha256("a_daily")},
        "native_tdx_files_verified": len(rows),
        "bars_projection_sha256": sha256(json_bytes(rows)).hexdigest(), **SAFETY_FLAGS,
    }
    return detail, rows, quarantine


def _read_snapshot(path: Path) -> tuple[dict[str, int] | None, bytes | None]:
    identity = file_identity(path)
    if identity is None:
        return None, None
    try:
        return identity, path.read_bytes()
    except FileNotFoundError:
        return identity, None


def _publish_immutable(path: Path, content: bytes, lease: WriterLease) -> None:
    if path.is_file():
        require(path.read_bytes() == content, "A_HISTORY_IMMUTABLE_OBJECT_SHA_MISMATCH")
    else:
        publish_bytes(path, content, lease=lease, expected=None)


def publish_a_daily(data_dir: Path, store: V4Store, inputs: DatedInputs, lease: WriterLease) -> dict[str, Any]:
    day = inputs.trade_date
    history = data_dir / "history"
    checkpoint_path = history / "checkpoint.json"
    before_checkpoint, before_bytes = _read_snapshot(checkpoint_path)
    detail, rows, quarantine = validate_a_daily(inputs)
    codes = {row["symbol"] for row in rows}
    delta = {"schema": "v4_core.a_daily_delta.v1", "accepted_symbols": sorted(codes), **detail}
    delta_bytes = json_bytes(delta)
    delta_sha = sha256(delta_bytes).hexdigest()
    delta_relative = f"deltas/{day}-{delta_sha}.json"
    delta_path = history / delta_relative
    checkpoint = {
        "schema": "v4_core.a_daily_checkpoint.v1", "trade_date": day,
        "delta": {"path": delta_relative, "sha256": delta_sha}, "accepted_count": len(rows),
        "bars_projection_sha256": detail["bars_projection_sha256"], **SAFETY_FLAGS,
    }
    checkpoint_bytes = json_bytes(checkpoint)
    checkpoint_sha = sha256(checkpoint_bytes).hexdigest()
    checkpoint_relative = f"checkpoints/{day}-{checkpoint_sha}.json"
    published = None
    checkpoint_attempted = False
    try:
        with store.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            variants = date_variants(day)
            dates = ",".join("?" for _ in variants)
            rows_in_db = conn.execute(
                f"SELECT symbol, trade_date FROM daily_bars WHERE market='A' AND trade_date IN ({dates})", variants,
            )
            require(all(row["symbol"] in codes and row["trade_date"] == day for row in rows_in_db),
                    "A_STORED_TARGET_SLICE_CONFLICTS_WITH_AUTHORITY")
            store.upsert_daily_bars(rows, connection=conn)
            for code, item in quarantine.items():
                store.record_quarantine("A", day, code, item["reason"], item, connection=conn, idempotent=True)
            _publish_immutable(delta_path, delta_bytes, lease)
            _publish_immutable(history / checkpoint_relative, checkpoint_bytes, lease)
            checkpoint_attempted = True
            publish_bytes(checkpoint_path, checkpoint_bytes, lease=lease, expected=before_checkpoint)
            published = file_identity(checkpoint_path)
            conn.execute(
                """INSERT INTO a_daily_publications
                   (trade_date, checkpoint_sha256, delta_path, delta_sha256, bars_projection_sha256, accepted_count)
                   VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(trade_date) DO UPDATE SET
                   checkpoint_sha256=excluded.checkpoint_sha256, delta_path=excluded.delta_path,
                   delta_sha256=excluded.delta_sha256, bars_projection_sha256=excluded.bars_projection_sha256,
                   accepted_count=excluded.accepted_count""",
                (day, checkpoint_sha, delta_relative, delta_sha, detail["bars_projection_sha256"], len(rows)),
            )
    except Exception as exc:
        # If replace succeeded but directory fsync raised, detect our exact bytes as well.
        current, current_bytes = _read_snapshot(checkpoint_path) if checkpoint_attempted else (None, None)
        if not isinstance(exc, ConcurrentHistoryChange) and current is not None and current_bytes == checkpoint_bytes and (
            current == published or (published is None and current != before_checkpoint)
        ):
            try:
                if before_bytes is None:
                    if before_checkpoint is None:
                        discard_published_file(checkpoint_path, current)
                else:
                    publish_bytes(checkpoint_path, before_bytes, lease=lease, expected=current)
            except (OSError, AssertionError) as recovery:
                exc.add_note(f"Checkpoint recovery failed: {recovery}")
        raise
    return {**detail, "history_delta_path": delta_relative, "history_delta_sha256": delta_sha,
            "history_checkpoint_path": checkpoint_relative, "history_checkpoint_sha256": checkpoint_sha}


def read_a_daily_publication(
    history: Path, store: V4Store, inputs: DatedInputs, terminal: dict[str, Any],
) -> dict[str, Any]:
    day = inputs.trade_date
    delta_sha = terminal.get("history_delta_sha256")
    checkpoint_sha = terminal.get("history_checkpoint_sha256")
    require(isinstance(delta_sha, str) and _DIGEST.fullmatch(delta_sha)
            and isinstance(checkpoint_sha, str) and _DIGEST.fullmatch(checkpoint_sha),
            "A_1610_HISTORY_DIGEST_UNBOUND")
    relative = f"deltas/{day}-{delta_sha}.json"
    checkpoint_relative = f"checkpoints/{day}-{checkpoint_sha}.json"
    require(terminal.get("history_delta_path") == relative
            and terminal.get("history_checkpoint_path") == checkpoint_relative, "A_1610_HISTORY_PATH_MISMATCH")
    try:
        checkpoint_bytes = (history / checkpoint_relative).read_bytes()
        delta_bytes = (history / relative).read_bytes()
        checkpoint = mapping(json.loads(checkpoint_bytes), "A_1610_CHECKPOINT_INVALID")
        delta = mapping(json.loads(delta_bytes), "A_1610_DELTA_INVALID")
    except (OSError, ValueError) as exc:
        raise EvidenceError("A_1610_HISTORY_PUBLICATION_UNAVAILABLE") from exc
    require(sha256(checkpoint_bytes).hexdigest() == checkpoint_sha and sha256(delta_bytes).hexdigest() == delta_sha
            and checkpoint.get("schema") == "v4_core.a_daily_checkpoint.v1"
            and delta.get("schema") == "v4_core.a_daily_delta.v1"
            and checkpoint.get("trade_date") == delta.get("trade_date") == terminal.get("trade_date") == day
            and checkpoint.get("delta") == {"path": relative, "sha256": delta_sha}
            and delta.get("source_identity") == terminal.get("source_identity")
            and mapping(delta.get("source_identity"), "A_1610_SOURCE_IDENTITY_UNBOUND").get("source_binding_sha256") == inputs.entry_sha256("a_daily"),
            "A_1610_HISTORY_SHA_OR_IDENTITY_MISMATCH")
    with store.connect() as conn:
        conn.execute("BEGIN")
        committed = conn.execute("SELECT * FROM a_daily_publications WHERE trade_date=?", (day,)).fetchone()
        stored_rows = [dict(row) for row in conn.execute(
            "SELECT * FROM daily_bars WHERE market='A' AND trade_date=? ORDER BY symbol", (day,),
        )]
    require(committed is not None and committed["checkpoint_sha256"] == checkpoint_sha
            and committed["delta_path"] == relative and committed["delta_sha256"] == delta_sha,
            "A_1610_SQLITE_PUBLICATION_UNCOMMITTED")
    bars_sha = sha256(json_bytes(stored_rows)).hexdigest()
    require(0 < len(stored_rows) == committed["accepted_count"] == checkpoint.get("accepted_count")
            == delta.get("accepted_count") == terminal.get("accepted_count")
            and bars_sha == committed["bars_projection_sha256"] == checkpoint.get("bars_projection_sha256")
            == delta.get("bars_projection_sha256") == terminal.get("bars_projection_sha256")
            and delta.get("accepted_symbols") == [row["symbol"] for row in stored_rows],
            "A_1610_PUBLISHED_DAILY_BAR_COUNT_OR_HASH_MISMATCH")
    return {"accepted_count": len(stored_rows), "history_delta_path": relative, "history_delta_sha256": delta_sha,
            "history_checkpoint_path": checkpoint_relative, "history_checkpoint_sha256": checkpoint_sha,
            "bars_projection_sha256": bars_sha}
