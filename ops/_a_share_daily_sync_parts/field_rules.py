"""ops.a_share_daily_sync: field_rules (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __field_signature_violation_body(_v4_scope, /, *, symbol, market, date_value, row_index, raw, source_ref, source_file_sha256, native_path, run_id, recorded_at):
    return {
        "symbol": _v4_global(_v4_scope, 'str')(symbol),
        "market": _v4_global(_v4_scope, 'int')(market),
        "date": _v4_global(_v4_scope, 'int')(date_value),
        "row_index": _v4_global(_v4_scope, 'int')(row_index),
        "native_path": native_path,
        "source_ref": source_ref,
        "source_file_sha256": source_file_sha256,
        "native_file_sha256": source_file_sha256,
        "raw_row_sha256": _v4_global(_v4_scope, 'hashlib').sha256(raw).hexdigest(),
        "amount_bits": f"0x{_v4_global(_v4_scope, 'struct').unpack_from('<I', raw, 20)[0]:08x}",
        "volume_raw_uint32": _v4_global(_v4_scope, 'struct').unpack_from("<I", raw, 24)[0],
        "reason_code": _v4_global(_v4_scope, 'KNOWN_MALFORMED_AMOUNT_VOLUME_SIGNATURE'),
        "field_rule_id": _v4_global(_v4_scope, 'FIELD_RULE_ID'),
        "field_rule_version": _v4_global(_v4_scope, 'FIELD_RULE_VERSION'),
        "run_id": run_id,
        "recorded_at": recorded_at,
        "transform_applied": False,
    }


def __local_field_signature_violations_body(_v4_scope, /, path, *, symbol, market, run_id, recorded_at):
    """Scan every existing native record without decoding away raw bits."""
    if _v4_global(_v4_scope, '_local_path_failure')(path) is not None or not path.exists():
        return []
    try:
        raw_file = path.read_bytes()
    except _v4_global(_v4_scope, 'OSError'):
        return []
    if _v4_global(_v4_scope, 'len')(raw_file) % _v4_global(_v4_scope, 'DAY_STRUCT').size:
        return []
    source_sha256 = _v4_global(_v4_scope, 'hashlib').sha256(raw_file).hexdigest()
    violations: list[dict[str, Any]] = []
    for row_index, offset in _v4_global(_v4_scope, 'enumerate')(_v4_global(_v4_scope, 'range')(0, _v4_global(_v4_scope, 'len')(raw_file), _v4_global(_v4_scope, 'DAY_STRUCT').size)):
        raw = raw_file[offset : offset + _v4_global(_v4_scope, 'DAY_STRUCT').size]
        if not _v4_global(_v4_scope, '_has_known_malformed_amount_volume_signature')(raw):
            continue
        date_value = _v4_global(_v4_scope, 'struct').unpack_from("<I", raw, 0)[0]
        violations.append(
            _v4_global(_v4_scope, '_field_signature_violation')(
                symbol=symbol,
                market=market,
                date_value=date_value,
                row_index=row_index,
                raw=raw,
                source_ref=f"{path}:byte_offset={offset}",
                source_file_sha256=source_sha256,
                native_path=_v4_global(_v4_scope, 'str')(path),
                run_id=run_id,
                recorded_at=recorded_at,
            )
        )
    return violations


def __provider_field_signature_violation_body(_v4_scope, /, bar, *, symbol, market, row_index, run_id, recorded_at):
    try:
        raw = _v4_global(_v4_scope, 'pack_hq_bar')(_v4_global(_v4_scope, 'dict')(bar))
    except (_v4_global(_v4_scope, 'KeyError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'OverflowError'), _v4_global(_v4_scope, 'struct').error):
        return None
    if not _v4_global(_v4_scope, '_has_known_malformed_amount_volume_signature')(raw):
        return None
    return _v4_global(_v4_scope, '_field_signature_violation')(
        symbol=symbol,
        market=market,
        date_value=_v4_global(_v4_scope, 'day_int')(_v4_global(_v4_scope, 'dict')(bar)),
        row_index=row_index,
        raw=raw,
        source_ref=f"provider:{symbol}:response_index={row_index}",
        source_file_sha256=None,
        native_path=None,
        run_id=run_id,
        recorded_at=recorded_at,
    )


def __bars_equivalent_body(_v4_scope, /, left, right):
    """Compare a revalidated target bar without introducing a rewrite path."""
    try:
        if _v4_global(_v4_scope, 'day_int')(_v4_global(_v4_scope, 'dict')(left)) != _v4_global(_v4_scope, 'day_int')(_v4_global(_v4_scope, 'dict')(right)):
            return False
        for key in ("open", "high", "low", "close"):
            if not _v4_global(_v4_scope, 'math').isclose(_v4_global(_v4_scope, 'float')(left[key]), _v4_global(_v4_scope, 'float')(right[key]), rel_tol=1e-9, abs_tol=0.005):
                return False
        for key in ("amount", "vol"):
            if not _v4_global(_v4_scope, 'math').isclose(_v4_global(_v4_scope, 'float')(left[key]), _v4_global(_v4_scope, 'float')(right[key]), rel_tol=1e-6, abs_tol=1e-6):
                return False
    except (_v4_global(_v4_scope, 'KeyError'), _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')):
        return False
    return True
