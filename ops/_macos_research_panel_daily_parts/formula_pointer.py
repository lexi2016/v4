"""ops.macos_research_panel_daily: formula_pointer (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _selector_pointer_is_ready_body(_v4_scope, /, pointer, target_date, formula_generation_pointer):
    """Return true only when the authoritative selector reaches target date.

    A generation pointer enables the strict V4 contract: the exact selector
    and source/sidecar provenance must be verified together.  The two argument
    form remains the compatibility path for older callers and fixtures.
    """

    if formula_generation_pointer is not None:
        try:
            generation = _v4_global(_v4_scope, 'read_formula_generation')(
                formula_generation_pointer,
                expected_target_date=_v4_global(_v4_scope, '_date')(target_date),
                require_source=True,
            )
            if pointer is None:
                return True
            from infrastructure.formula_generation import read_legacy_pointer

            return read_legacy_pointer(pointer) == generation["selector"]
        except (_v4_global(_v4_scope, 'FormulaGenerationError'), _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'ValueError')):
            return False

    target = _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, '_date')(target_date))
    if pointer is None:
        return False
    pointer_path = _v4_global(_v4_scope, 'Path')(pointer).expanduser().resolve()
    try:
        pointed = _v4_global(_v4_scope, 'Path')(pointer_path.read_text(encoding="utf-8-sig").strip()).expanduser()
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError')):
        return False
    if not pointed.is_absolute():
        pointed = pointer_path.parent / pointed
    pointed = pointed.resolve()
    try:
        generation = _v4_global(_v4_scope, '_find_formula_generation')(pointed)
        if generation is not None:
            pointed = generation["selector"]
        return pointed.is_file() and _v4_global(_v4_scope, '_parquet_max_date')(pointed) == target
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'SnapshotGateError')):
        return False


def __formula_generation_target_body(_v4_scope, /, output_root, payload, role):
    detail = payload.get(role)
    if not _v4_global(_v4_scope, 'isinstance')(detail, _v4_global(_v4_scope, 'Mapping')):
        raise _v4_global(_v4_scope, 'SnapshotGateError')(f"formula generation missing {role} target")
    raw_path = detail.get("path")
    if not _v4_global(_v4_scope, 'isinstance')(raw_path, _v4_global(_v4_scope, 'str')) or not raw_path.strip():
        raise _v4_global(_v4_scope, 'SnapshotGateError')(f"formula generation {role} path is invalid")
    candidate = _v4_global(_v4_scope, 'Path')(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = output_root / candidate
    resolved = candidate.resolve()
    if not _v4_global(_v4_scope, '_path_inside')(output_root, resolved) or candidate.is_symlink():
        raise _v4_global(_v4_scope, 'SnapshotGateError')(f"formula generation {role} target escapes output root")
    current = candidate
    while True:
        if current.is_symlink():
            raise _v4_global(_v4_scope, 'SnapshotGateError')(f"formula generation {role} target has symlink ancestry")
        if current == output_root:
            break
        if current.parent == current:
            raise _v4_global(_v4_scope, 'SnapshotGateError')(f"formula generation {role} target has invalid ancestry")
        current = current.parent
    if not resolved.is_file():
        raise _v4_global(_v4_scope, 'SnapshotGateError')(f"formula generation {role} target is missing")
    expected_bytes = detail.get("bytes")
    expected_sha = detail.get("sha256")
    if not _v4_global(_v4_scope, 'isinstance')(expected_bytes, _v4_global(_v4_scope, 'int')) or expected_bytes != resolved.stat().st_size:
        raise _v4_global(_v4_scope, 'SnapshotGateError')(f"formula generation {role} target bytes mismatch")
    if not _v4_global(_v4_scope, 'isinstance')(expected_sha, _v4_global(_v4_scope, 'str')) or _v4_global(_v4_scope, '_sha256_file')(resolved) != expected_sha:
        raise _v4_global(_v4_scope, 'SnapshotGateError')(f"formula generation {role} target SHA mismatch")
    return resolved


def __read_formula_generation_body(_v4_scope, /, output_root):
    root = _v4_global(_v4_scope, 'Path')(output_root).expanduser().resolve()
    path = root / _v4_global(_v4_scope, 'FORMULA_GENERATION_POINTER_NAME')
    if not path.is_file():
        return None
    if path.is_symlink():
        raise _v4_global(_v4_scope, 'SnapshotGateError')("formula generation pointer is symlinked")
    try:
        payload = _v4_global(_v4_scope, 'json').loads(path.read_text(encoding="utf-8"))
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
        raise _v4_global(_v4_scope, 'SnapshotGateError')("formula generation pointer is unreadable") from error
    if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'dict')) or payload.get("schema") != _v4_global(_v4_scope, 'FORMULA_GENERATION_SCHEMA') or payload.get("status") != "READY":
        raise _v4_global(_v4_scope, 'SnapshotGateError')("formula generation pointer schema/status is invalid")
    identity = {"selector": payload.get("selector"), "backtest": payload.get("backtest")}
    generation_id = payload.get("generation_id")
    expected_generation_id = _v4_global(_v4_scope, 'hashlib').sha256(
        _v4_global(_v4_scope, 'json').dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if not _v4_global(_v4_scope, 'isinstance')(generation_id, _v4_global(_v4_scope, 'str')) or generation_id != expected_generation_id:
        raise _v4_global(_v4_scope, 'SnapshotGateError')("formula generation identity mismatch")
    selector = _v4_global(_v4_scope, '_formula_generation_target')(root, payload, "selector")
    backtest = _v4_global(_v4_scope, '_formula_generation_target')(root, payload, "backtest")
    if selector == backtest:
        raise _v4_global(_v4_scope, 'SnapshotGateError')("formula generation selector/backtest targets must differ")
    return {
        "path": path,
        "sha256": _v4_global(_v4_scope, 'hashlib').sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
        "generation_id": generation_id,
        "selector": selector,
        "backtest": backtest,
    }


def __find_formula_generation_body(_v4_scope, /, target):
    current = target if target.is_dir() else target.parent
    for _ in _v4_global(_v4_scope, 'range')(64):
        try:
            generation = _v4_global(_v4_scope, '_read_formula_generation')(current)
        except _v4_global(_v4_scope, 'SnapshotGateError'):
            raise
        if generation is not None:
            return generation
        if current.parent == current:
            break
        current = current.parent
    return None
