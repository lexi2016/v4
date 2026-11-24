"""HK daily checks embedded in the SHA-pinned runtime overlays."""

from __future__ import annotations


def _pack_hk_day_uint32(
    destination, rows, *, target_date, minimum_rows, expected_codes,
    record_struct, path_type, rows_as_dicts, normalize_date, validate_rows,
    build_record, atomic_write, grouped_result, gate_error, safety_flags,
):
    """Make all deterministic input and existing-file checks before the first write."""
    import hashlib
    import math
    import re
    import struct
    from decimal import Decimal, InvalidOperation

    def code_of(value):
        code = str(value).strip().upper()
        if re.fullmatch(r"(?:HK\.[0-9]{5}|[0-9]{1,5}(?:\.HK)?)", code) is None:
            raise gate_error(f"HK invalid security identity: {value!r}")
        return code.removeprefix("HK.").removesuffix(".HK").zfill(5)

    target = normalize_date(target_date)
    destination = path_type(destination)
    if destination.suffix.lower() == ".day" or record_struct.format != "<IfffffII":
        raise gate_error("invalid HK .day root or record ABI")
    incoming = rows_as_dicts(rows)
    actual = set()
    for row in incoming:
        code = code_of(row.get("code") or row.get("code_norm") or row.get("ts_code"))
        if code in actual:
            raise gate_error(f"HK duplicate code: {code}")
        actual.add(code)
        row["code"] = code
    expected = actual if expected_codes is None else {code_of(code) for code in expected_codes}
    if actual != expected:
        raise gate_error(f"HK snapshot coverage mismatch: {len(actual)}/{len(expected)}")
    checked, _ = validate_rows(incoming, target, minimum_rows=1, lane="HK")

    encoded = {}
    quarantine = []
    uint32_max = (1 << 32) - 1
    for row in checked:
        code = row["code"]
        field = "volume" if "volume" in row else "vol"
        raw = row.get(field)
        try:
            volume = Decimal(str(raw))
        except InvalidOperation as error:
            raise gate_error(f"HK invalid raw volume: {code}") from error
        if not volume.is_finite() or volume != volume.to_integral_value():
            raise gate_error(f"HK raw volume is not a finite integer: {code}")

        # A UInt32 overflow is the only per-symbol quarantine. Validate the
        # other fields first so a different bad record cannot ride that path.
        record = list(build_record(dict(row, volume=0)))
        if not all(math.isfinite(value) for value in record[1:6]):
            raise gate_error(f"HK non-finite .day field: {code}")
        try:
            record_struct.pack(*record)
        except (OverflowError, struct.error) as error:
            raise gate_error(f"HK non-volume .day encoding failed: {code}") from error
        if volume < 0 or volume > uint32_max:
            quarantine.append({
                "code": f"HK.{code}",
                "trade_date": target,
                "source": row.get("source"),
                "source_field": field,
                "raw_value": int(volume),
                "unit": "shares",
                "destination_field": "trade_v",
                "destination_type": "uint32_le",
                "byte_offset": 24,
                "minimum": 0,
                "maximum": uint32_max,
                "reason": "HK_DAY_UINT32_VOLUME_OUT_OF_RANGE",
            })
            continue
        record[6] = int(volume)
        encoded[code] = record_struct.pack(*record)

    evidence = {
        "expected_code_count": len(expected),
        "packable_code_count": len(encoded),
        "quarantined_code_count": len(quarantine),
        "quarantine": quarantine,
    }
    results = []
    packed_codes = []

    def coverage():
        return {
            **evidence,
            "packed_code_count": len(packed_codes),
            "packed_codes": packed_codes,
            "new_day_write_count": sum(not item["already_current"] for item in results),
            "coverage_rate": len(packed_codes) / max(len(expected), 1),
        }

    def reject(message):
        error = gate_error(message)
        error.hk_pack_evidence = coverage()
        raise error

    if len(encoded) < minimum_rows or not encoded:
        reject(f"HK post-quarantine minimum coverage requires {minimum_rows} rows, got {len(encoded)}")

    target_int = int(target)
    day_root = destination / "vipdoc" / "ds" / "lday"
    if day_root.resolve() != destination.resolve() / "vipdoc" / "ds" / "lday":
        reject("HK .day directory resolves outside its configured layout")
    existing_digests = {}
    current_codes = set()
    for path in sorted(day_root.glob("71#*.day")):
        code = path.name[3:-4]
        if re.fullmatch(r"[0-9]{5}", code) is None or path.is_symlink() or not path.is_file():
            reject(f"HK invalid existing .day identity: {path.name}")
        payload = path.read_bytes()
        if len(payload) % record_struct.size:
            reject(f"existing .day has trailing bytes: {path.name}")
        if code in encoded:
            existing_digests[code] = hashlib.sha256(payload).digest()
        target_records = []
        for offset in range(0, len(payload), record_struct.size):
            date_int = struct.unpack_from("<I", payload, offset)[0]
            if date_int > target_int and code in actual:
                reject(f"HK target date is older than existing file: {path.name}")
            if date_int == target_int:
                target_records.append(payload[offset : offset + record_struct.size])
        if target_records:
            if code not in encoded or target_records != [encoded[code]]:
                reject(f"HK target-date conflict: {path.name}")
            current_codes.add(code)

    for code, record in sorted(encoded.items()):
        path = day_root / f"71#{code}.day"
        existed = code in existing_digests
        if path.is_symlink() or path.exists() != existed:
            reject(f"HK .day changed after preflight: {path.name}")
        payload = path.read_bytes() if existed else b""
        if existed and hashlib.sha256(payload).digest() != existing_digests[code]:
            reject(f"HK .day changed after preflight: {path.name}")
        already_current = code in current_codes
        if not already_current:
            payload += record
            atomic_write(path, payload)
        results.append({
            "status": "READY",
            "already_current": already_current,
            "target_date": target,
            "row_count": 1,
            "coverage_rate": 1.0,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "path": str(path),
            **safety_flags,
        })
        packed_codes.append(f"HK.{code}")
    return grouped_result(results, target, lane="HK") | coverage()


def _verify_hk_packed_panel(asset_root, updater_script, authority, target, packed_codes):
    """Bind the legacy updater's formal manifest to the exact packed codes."""
    import json
    from pathlib import Path

    import pyarrow.parquet as pq

    from ops.ensure_hk_security_master import _read_verified_hk_panel_authority

    root = Path(asset_root).resolve()
    _read_verified_hk_panel_authority(
        asset_root=root,
        package_root=Path(updater_script).resolve().parents[1],
        authority=authority,
        trade_date=target,
    )
    pointer = root / "panel_latest.json"
    pointer_bytes = pointer.read_bytes()
    relative = authority["manifest_relative"]
    if json.loads(pointer_bytes).get("manifest_relative") != relative:
        raise ValueError("HK panel manifest identity changed")
    manifest_path = (root / relative).resolve()
    manifest_path.relative_to(root)
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("panel_sha256") != authority.get("panel_sha256") or manifest.get("panel_max_date") != target:
        raise ValueError("HK panel artifact identity changed")
    panel = (root / manifest["panel_relative"]).resolve()
    panel.relative_to(root)
    codes = pq.read_table(
        panel,
        columns=["code_norm"],
        filters=[("trade_date_compact", "=", target)],
    )["code_norm"].to_pylist()
    if len(codes) != len(packed_codes) or set(codes) != set(packed_codes):
        raise ValueError("HK panel exact-date membership differs from packed membership")
    if pointer.read_bytes() != pointer_bytes or manifest_path.read_bytes() != manifest_bytes:
        raise ValueError("HK panel manifest identity changed during membership read")


def _validate_pending_hk_sessions(
    increment, *, after_date, through_date, minimum_code_count,
    minimum_positive_coverage_rate, store_error,
):
    """Check exactly the rows the owner is about to append for every HK session."""
    from datetime import datetime, timedelta

    import pandas as pd

    try:
        from contracts.trading_calendar import TradingDayState, load_market_calendar, resolve_market_states

        calendar = load_market_calendar()
    except (ImportError, OSError, ValueError) as error:
        raise store_error("HK 0.2 authoritative securities calendar unavailable") from error

    first = datetime.strptime(after_date, "%Y%m%d").date() + timedelta(days=1)
    last = datetime.strptime(through_date, "%Y%m%d").date()
    days = {date: rows for date, rows in increment.groupby("trade_date_compact", sort=False)}
    for offset in range((last - first).days + 1):
        day = (first + timedelta(days=offset)).strftime("%Y%m%d")
        state = resolve_market_states(calendar, day)["hk_securities"]
        if state == TradingDayState.UNKNOWN:
            raise store_error(f"HK 0.2 securities market calendar date unconfirmed: {day}")
        rows = days.pop(day, None)
        if state == TradingDayState.NON_TRADING_DAY:
            if rows is not None or day == through_date:
                raise store_error(f"HK 0.2 VIPDOC date is not a securities session: {day}")
            continue
        if rows is None:
            raise store_error(f"HK 0.2 pending securities session missing: {day}")
        count = rows["code_norm"].nunique()
        if count < minimum_code_count:
            raise store_error(
                f"HK 0.2 pending session market coverage below minimum: "
                f"{day} {count}/{minimum_code_count}"
            )
        positive_trade = pd.to_numeric(rows["trade"], errors="coerce").fillna(0).gt(0).mean()
        positive_amount = pd.to_numeric(rows["amount"], errors="coerce").fillna(0).gt(0).mean()
        if min(positive_trade, positive_amount) < minimum_positive_coverage_rate:
            raise store_error(
                f"HK 0.2 pending session positive coverage below minimum: "
                f"{day} trade={positive_trade:.8f} amount={positive_amount:.8f} "
                f"minimum={minimum_positive_coverage_rate:.8f}"
            )
    if days:
        raise store_error(f"HK 0.2 VIPDOC increment dates outside owner bounds: {sorted(days)}")
