"""Reviewed-source C364/base100 candidate decoding; not an official TDX format certificate.

Only raw binary uint32 inputs are accepted. Preserve `reserved` as provenance but
never decode the corrected output a second time. Caller must track encoding version.
"""
from decimal import Decimal, InvalidOperation

UINT32_MAX = (1 << 32) - 1
MASK = 0xffffff00
MARKER = 0xc3640000


class DecodeError(ValueError):
    pass


def decode_volume(vol_raw, reserved):
    for name, value in [('vol_raw', vol_raw), ('reserved', reserved)]:
        if type(value) is not int or not 0 <= value <= UINT32_MAX:
            raise DecodeError('RAW_UINT32_REQUIRED:' + name)
    if reserved & MASK != MARKER:
        return vol_raw
    remainder = reserved & 0xff
    if remainder > 99:
        raise DecodeError('REMAINDER_OUTSIDE_BASE100')
    result = vol_raw * 100 + remainder
    if result <= UINT32_MAX:
        raise DecodeError('MARKER_NOT_UINT32_OVERFLOW')
    return result


def validate_marker_envelope(decoded_volume, amount, raw_low, raw_high):
    """Independent arithmetic sanity check in *raw*, not QFQ, price coordinates.

    Tolerance matches the root audit: max(0.02 yuan, 0.2% of max absolute price).
    Passing this guard is necessary but not sufficient for official unit/PIT proof.
    """
    try:
        v, a, low, high = map(lambda x: Decimal(str(x)),
                              [decoded_volume, amount, raw_low, raw_high])
    except (InvalidOperation, ValueError) as exc:
        raise DecodeError('INVALID_NUMERIC_ENVELOPE') from exc
    if not all(x.is_finite() for x in [v, a, low, high]) or v <= 0 or a <= 0 or low <= 0 or high < low:
        raise DecodeError('INVALID_NUMERIC_ENVELOPE')
    tolerance = max(Decimal('.02'), Decimal('.002') * max(abs(low), abs(high)))
    vwap = a / v
    if not low - tolerance <= vwap <= high + tolerance:
        raise DecodeError('VWAP_OUTSIDE_RAW_OHLC')
    return True
