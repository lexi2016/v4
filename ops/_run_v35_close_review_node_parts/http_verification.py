"""ops.run_v35_close_review_node: http_verification (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __validate_loopback_url_body(_v4_scope, /, url):
    try:
        parsed = _v4_global(_v4_scope, 'urlparse')(url)
    except _v4_global(_v4_scope, 'ValueError'):
        return False
    if parsed.scheme != "http":
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    if (parsed.hostname or "").lower() not in {"127.0.0.1", "localhost", "::1"}:
        return False
    try:
        if parsed.port != 8873:
            return False
    except _v4_global(_v4_scope, 'ValueError'):
        return False
    return True


def __http_status_body(_v4_scope, /, url, http_getter):
    try:
        return _v4_global(_v4_scope, 'int')(http_getter(url, _v4_global(_v4_scope, 'HTTP_TIMEOUT_SECONDS')))
    except _v4_global(_v4_scope, 'HTTPError') as error:
        try:
            return _v4_global(_v4_scope, 'int')(error.code)
        finally:
            error.close()
    except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'URLError')) as error:
        raise _v4_global(_v4_scope, 'HttpVerifyFailed')(
            f"{url}: {_v4_global(_v4_scope, 'type')(error).__name__}: {error}"
        ) from error
