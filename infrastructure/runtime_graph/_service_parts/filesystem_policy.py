"""infrastructure.runtime_graph.service: filesystem_policy (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __assert_no_reparse_ancestors_body(_v4_scope, /, path):
    absolute = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'os').path.abspath(_v4_global(_v4_scope, 'str')(path)))
    current = _v4_global(_v4_scope, 'Path')(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            metadata = _v4_global(_v4_scope, 'os').lstat(current)
        except _v4_global(_v4_scope, 'FileNotFoundError'):
            continue
        except _v4_global(_v4_scope, 'OSError') as error:
            raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_PATH_UNSAFE") from error
        if _v4_global(_v4_scope, '_reparse')(metadata):
            raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_PATH_UNSAFE")


def __ensure_directory_body(_v4_scope, /, path, *, allowed_root):
    destination = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'os').path.abspath(_v4_global(_v4_scope, 'str')(path)))
    root = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'os').path.abspath(_v4_global(_v4_scope, 'str')(allowed_root)))
    if not _v4_global(_v4_scope, '_within')(destination, root):
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_PATH_UNSAFE")
    # The full parent chain is checked before mkdir, including missing roots'
    # existing ancestors.  This prevents a junction from redirecting creation.
    _v4_global(_v4_scope, '_assert_no_reparse_ancestors')(root)
    _v4_global(_v4_scope, '_assert_no_reparse_ancestors')(destination)
    try:
        metadata = _v4_global(_v4_scope, 'os').lstat(destination)
    except _v4_global(_v4_scope, 'FileNotFoundError'):
        metadata = None
    except _v4_global(_v4_scope, 'OSError') as error:
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_PATH_UNSAFE") from error
    if metadata is not None and (_v4_global(_v4_scope, '_reparse')(metadata) or not _v4_global(_v4_scope, 'stat').S_ISDIR(metadata.st_mode)):
        raise _v4_global(_v4_scope, 'ValueError')("RUNTIME_GRAPH_PATH_UNSAFE")
    if metadata is None:
        destination.mkdir(parents=True, exist_ok=True)
    _v4_global(_v4_scope, '_assert_no_reparse_ancestors')(destination)
    return destination
