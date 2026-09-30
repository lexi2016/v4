"""domains.hk_prefix_research: scan_execution (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __load_scan_function_body(_v4_scope, /, path):
    extractor = _v4_global(_v4_scope, 'Path')(path)
    if not extractor.is_file():
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("accepted prefix extractor is missing")
    module_name = "v4_hk_prefix_reference_" + _v4_global(_v4_scope, 'sha256_file')(extractor)[:16]
    spec = _v4_global(_v4_scope, 'importlib').util.spec_from_file_location(module_name, extractor)
    if spec is None or spec.loader is None:
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("cannot load accepted prefix extractor")
    module = _v4_global(_v4_scope, 'importlib').util.module_from_spec(spec)
    spec.loader.exec_module(module)
    scan = _v4_global(_v4_scope, 'getattr')(module, "scan_prefix", None)
    if not _v4_global(_v4_scope, 'callable')(scan):
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("accepted prefix extractor does not expose scan_prefix")
    return scan


def __scan_artifact_body(_v4_scope, /, rows, *, scan, expected_rows, asof):
    _v4_global(_v4_scope, '_validate_scan_input')(rows)
    result = scan(
        rows,
        rows[-1]["close_at"] if asof is None else asof,
        evidence_basis=_v4_global(_v4_scope, 'EVIDENCE_BASIS'),
    )
    expected_count = _v4_global(_v4_scope, 'len')(rows) if expected_rows is None else _v4_global(_v4_scope, 'int')(expected_rows)
    if not result or _v4_global(_v4_scope, 'len')(result) != expected_count:
        raise _v4_global(_v4_scope, 'HKPrefixResearchError')("reference extractor did not consume exactly the 60-row prefix")
    result_rows = _v4_global(_v4_scope, 'tuple')(_v4_global(_v4_scope, '_safe_json')(record) for record in result)
    states = [_v4_global(_v4_scope, 'str')(record.get("state") or "") for record in result_rows]
    unknown_reasons = _v4_global(_v4_scope, 'Counter')(
        _v4_global(_v4_scope, 'str')(record.get("reason") or f"{record.get('state')}_STATE")
        for record in result_rows
        if record.get("state") in _v4_global(_v4_scope, '_INDETERMINATE_TERMINAL_STATES')
    )
    unknown_count = _v4_global(_v4_scope, 'sum')(state == "UNKNOWN" for state in states)
    indeterminate_count = _v4_global(_v4_scope, 'sum')(state in _v4_global(_v4_scope, '_INDETERMINATE_TERMINAL_STATES') for state in states)
    # ``known_count`` means terminal-calculation inputs with a determinate
    # state.  WARMUP is a real state label but remains indeterminate for the
    # endpoint contract, just like UNKNOWN.
    known_count = _v4_global(_v4_scope, 'len')(states) - indeterminate_count
    qualifying_count = _v4_global(_v4_scope, 'sum')(state in _v4_global(_v4_scope, '_QUALIFYING_STATES') for state in states)
    terminal_state = states[-1]
    terminal = _v4_global(_v4_scope, '_terminal_endpoint_metrics')(states)
    return result_rows, {
        "terminal_state": terminal_state,
        "unknown_count": unknown_count,
        "indeterminate_count": indeterminate_count,
        "known_count": known_count,
        "qualifying_count": qualifying_count,
        **terminal,
        # Descriptive path occupancy is retained under an explicit secondary
        # name; it is never used as the terminal endpoint or pair delta.
        "occupancy_lower_rate": qualifying_count / _v4_global(_v4_scope, 'len')(states),
        "occupancy_upper_rate": (qualifying_count + indeterminate_count) / _v4_global(_v4_scope, 'len')(states),
        "unknown_reason_counts": _v4_global(_v4_scope, 'dict')(_v4_global(_v4_scope, 'sorted')(unknown_reasons.items())),
    }
