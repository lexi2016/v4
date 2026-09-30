"""ops.materialize_research_peripherals: translation_validation (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __normalize_chinese_finance_translation_body(_v4_scope, /, value):
    text = _v4_global(_v4_scope, 'clean_text')(value)
    replacements = (
        ("HK$", "港元"),
        ("US$", "美元"),
        ("亿$", "亿美元"),
        ("$", "美元"),
        ("灵喜游戏", "灵犀游戏"),
        ("英维迪亚", "英伟达"),
    )
    for source, target in replacements:
        text = text.replace(source, target)
    return text


def __finance_amounts_body(_v4_scope, /, value):
    text = _v4_global(_v4_scope, 'clean_text')(value)
    amounts: list[tuple[str, float]] = []
    occupied: list[tuple[int, int]] = []

    def add(start: int, end: int, currency: str, number: str, unit: str = "") -> None:
        if _v4_global(_v4_scope, 'any')(start < old_end and end > old_start for old_start, old_end in occupied):
            return
        try:
            numeric = _v4_global(_v4_scope, 'float')(number.replace(",", ""))
        except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')):
            return
        multiplier = _v4_global(_v4_scope, '_FINANCE_UNIT_MULTIPLIERS').get(unit.lower(), _v4_global(_v4_scope, '_FINANCE_UNIT_MULTIPLIERS').get(unit, 1))
        amounts.append((currency, numeric * multiplier))
        occupied.append((start, end))

    for match in _v4_global(_v4_scope, '_WESTERN_AMOUNT_RE').finditer(text):
        if match.group("prefix_number"):
            raw_currency = match.group("prefix") or ""
            raw_number = match.group("prefix_number")
            raw_unit = match.group("prefix_unit") or ""
        else:
            raw_currency = match.group("suffix") or ""
            raw_number = match.group("suffix_number")
            raw_unit = match.group("suffix_unit") or ""
        currency = _v4_global(_v4_scope, '_FINANCE_CURRENCY_ALIASES').get(raw_currency.upper(), _v4_global(_v4_scope, '_FINANCE_CURRENCY_ALIASES').get(raw_currency, ""))
        if currency:
            add(match.start(), match.end(), currency, raw_number, raw_unit)
    for match in _v4_global(_v4_scope, '_CHINESE_AMOUNT_RE').finditer(text):
        currency = _v4_global(_v4_scope, '_FINANCE_CURRENCY_ALIASES').get(match.group("currency"), "")
        if currency:
            add(
                match.start(),
                match.end(),
                currency,
                match.group("number"),
                match.group("unit") or "",
            )
    return amounts


def __validate_finance_translation_body(_v4_scope, /, source, translated):
    """Check currency and order of magnitude before admitting translated text."""
    expected = _v4_global(_v4_scope, '_finance_amounts')(source)
    if not expected:
        return True
    actual = _v4_global(_v4_scope, '_finance_amounts')(translated)
    if _v4_global(_v4_scope, 'len')(expected) != _v4_global(_v4_scope, 'len')(actual):
        return False
    for (expected_currency, expected_value), (actual_currency, actual_value) in _v4_global(_v4_scope, 'zip')(expected, actual, strict=True):
        if expected_currency != actual_currency:
            return False
        tolerance = _v4_global(_v4_scope, 'max')(0.01, _v4_global(_v4_scope, 'abs')(expected_value) * 0.02)
        if _v4_global(_v4_scope, 'abs')(expected_value - actual_value) > tolerance:
            return False
    return True
