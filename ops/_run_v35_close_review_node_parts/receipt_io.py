"""ops.run_v35_close_review_node: receipt_io (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __is_reusable_body(_v4_scope, /, receipt, *, node, date):
    if receipt is None:
        return False
    if receipt.get("node_id") != node or receipt.get("date") != date:
        return False
    if receipt.get("status") not in _v4_global(_v4_scope, 'REUSABLE_STATUSES'):
        return False
    return _v4_global(_v4_scope, 'all')(
        _v4_global(_v4_scope, 'Path')(path).exists() for path in _v4_global(_v4_scope, '_artifact_local_paths')(receipt.get("artifacts"))
    )


def __atomic_write_body(_v4_scope, /, path, receipt):
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = _v4_global(_v4_scope, 'json').dumps(receipt, ensure_ascii=False, sort_keys=True).encode("utf-8")
    handle, temporary = _v4_global(_v4_scope, 'tempfile').mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with _v4_global(_v4_scope, 'os').fdopen(handle, "wb") as output:
            output.write(encoded)
            output.flush()
            _v4_global(_v4_scope, 'os').fsync(output.fileno())
        _v4_global(_v4_scope, 'os').replace(temporary, path)
    finally:
        if _v4_global(_v4_scope, 'os').path.exists(temporary):
            _v4_global(_v4_scope, 'os').unlink(temporary)


def __atomic_write_str_body(_v4_scope, /, path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = _v4_global(_v4_scope, 'tempfile').mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with _v4_global(_v4_scope, 'os').fdopen(handle, "wb") as output:
            output.write(value.encode("utf-8"))
            output.flush()
            _v4_global(_v4_scope, 'os').fsync(output.fileno())
        _v4_global(_v4_scope, 'os').replace(temporary, path)
    finally:
        if _v4_global(_v4_scope, 'os').path.exists(temporary):
            _v4_global(_v4_scope, 'os').unlink(temporary)
