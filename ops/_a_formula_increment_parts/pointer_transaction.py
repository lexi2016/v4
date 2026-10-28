"""ops.a_formula_increment: pointer_transaction (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __atomic_parquet_body(_v4_scope, /, frame, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if _v4_global(_v4_scope, '_path_has_symlink')(destination.parent):
        raise _v4_global(_v4_scope, 'AuthorityError')(f"candidate output parent is symlinked: {destination.parent}")
    fd, raw = _v4_global(_v4_scope, 'tempfile').mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=_v4_global(_v4_scope, 'str')(destination.parent))
    _v4_global(_v4_scope, 'os').close(fd)
    temporary = _v4_global(_v4_scope, 'Path')(raw)
    try:
        frame.to_parquet(temporary, index=False, engine="pyarrow")
        with temporary.open("rb") as handle:
            _v4_global(_v4_scope, 'os').fsync(handle.fileno())
        _v4_global(_v4_scope, 'os').replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except _v4_global(_v4_scope, 'FileNotFoundError'):
            pass


def __write_pointer_pair_body(_v4_scope, /, selector_pointer, backtest_pointer, selector_target, backtest_target, output_root, generation_metadata):
    output_root = _v4_global(_v4_scope, '_resolved')(output_root)
    selector_pointer = _v4_global(_v4_scope, '_resolved')(selector_pointer)
    backtest_pointer = _v4_global(_v4_scope, '_resolved')(backtest_pointer)
    for pointer in (selector_pointer, backtest_pointer):
        pointer.parent.mkdir(parents=True, exist_ok=True)
        if _v4_global(_v4_scope, '_path_has_symlink')(pointer.parent, stop=output_root) or pointer.is_symlink():
            raise _v4_global(_v4_scope, 'AuthorityError')(f"pointer path is symlinked: {pointer}")
    generation_raw, generation = _v4_global(_v4_scope, '_generation_payload')(
        output_root,
        selector_target,
        backtest_target,
        generation_metadata,
    )
    generation_path = _v4_global(_v4_scope, '_generation_pointer_path')(output_root)
    before: dict[str, bytes | None] = {}
    before_generation: bytes | None = None
    generation_snapshot_captured = False
    written: list[tuple[Path, bytes | None]] = []
    try:
        with _v4_global(_v4_scope, 'owned_interprocess_lock')(output_root / ".a_formula_publish", timeout_seconds=5.0, timeout_message="A formula pointer publish lock timeout"):
            before = {"selector": _v4_global(_v4_scope, '_read_pointer_bytes')(selector_pointer), "backtest": _v4_global(_v4_scope, '_read_pointer_bytes')(backtest_pointer)}
            before_generation = _v4_global(_v4_scope, '_read_pointer_bytes')(generation_path)
            generation_snapshot_captured = True
            # The one-file commit is the authority.  SafeRoot writes a fully
            # fsynced temporary file and atomically replaces this document;
            # legacy text pointers are updated only as compatibility views.
            _v4_global(_v4_scope, 'SafeRoot')(output_root).write_bytes(_v4_global(_v4_scope, 'FORMULA_GENERATION_POINTER_NAME'), generation_raw)
            if _v4_global(_v4_scope, '_read_pointer_bytes')(generation_path) != generation_raw:
                raise _v4_global(_v4_scope, 'AuthorityError')("generation pointer readback mismatch")
            for pointer, target, name in ((selector_pointer, selector_target, "selector"), (backtest_pointer, backtest_target, "backtest")):
                old = _v4_global(_v4_scope, '_read_pointer_bytes')(pointer)
                _v4_global(_v4_scope, 'SafeRoot')(pointer.parent).write_bytes(pointer.name, _v4_global(_v4_scope, '_pointer_target_bytes')(_v4_global(_v4_scope, '_resolved')(target)))
                written.append((pointer, old))
            after = {"selector": _v4_global(_v4_scope, '_read_pointer_bytes')(selector_pointer), "backtest": _v4_global(_v4_scope, '_read_pointer_bytes')(backtest_pointer)}
            expected = {
                "selector": _v4_global(_v4_scope, '_pointer_target_bytes')(_v4_global(_v4_scope, '_resolved')(selector_target)),
                "backtest": _v4_global(_v4_scope, '_pointer_target_bytes')(_v4_global(_v4_scope, '_resolved')(backtest_target)),
            }
            if _v4_global(_v4_scope, 'any')(after[name] != expected[name] for name in expected):
                raise _v4_global(_v4_scope, 'AuthorityError')("legacy pointer projection readback mismatch")
    except _v4_global(_v4_scope, 'Exception'):
        for pointer, old in _v4_global(_v4_scope, 'reversed')(written):
            try:
                if old is None:
                    if pointer.exists() and not pointer.is_symlink():
                        pointer.unlink()
                else:
                    _v4_global(_v4_scope, 'SafeRoot')(pointer.parent).write_bytes(pointer.name, old)
            except _v4_global(_v4_scope, 'Exception'):
                pass
        if generation_snapshot_captured:
            try:
                if before_generation is None:
                    if generation_path.exists() and not generation_path.is_symlink():
                        generation_path.unlink()
                else:
                    _v4_global(_v4_scope, 'SafeRoot')(output_root).write_bytes(_v4_global(_v4_scope, 'FORMULA_GENERATION_POINTER_NAME'), before_generation)
            except _v4_global(_v4_scope, 'Exception'):
                pass
        raise
    return {
        "before": {name: _v4_global(_v4_scope, '_generation_evidence')(raw) for name, raw in before.items()},
        "after": {name: _v4_global(_v4_scope, '_generation_evidence')(raw) for name, raw in after.items()},
        "generation_pointer": {
            "path": _v4_global(_v4_scope, 'str')(generation_path),
            "schema": _v4_global(_v4_scope, 'FORMULA_GENERATION_SCHEMA'),
            "generation_id": generation["generation_id"],
            "sha256": _v4_global(_v4_scope, '_sha256_bytes')(generation_raw),
            "bytes": _v4_global(_v4_scope, 'len')(generation_raw),
            "selector": generation["selector"],
            "backtest": generation["backtest"],
        },
        "legacy_projection": True,
        "atomic_generation_commit": True,
    }
