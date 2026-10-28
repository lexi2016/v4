"""ops.run_v35_macos_scheduler: runtime_validation (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __with_runtime_metadata_body(_v4_scope, /, payload):
    """Normalize scheduler result metadata without inventing success evidence."""

    result = _v4_global(_v4_scope, 'dict')(payload)
    for field in ("failure_class", "retry_after"):
        value = result.get(field)
        result[field] = value if value not in (None, "") else None
    for field, env_name in (
        ("release_id", "V35_RELEASE_ID"),
        ("upstream_fingerprint", "V35_UPSTREAM_FINGERPRINT"),
    ):
        value = result.get(field) or _v4_global(_v4_scope, 'os').environ.get(env_name)
        result[field] = value if value not in (None, "") else None
    try:
        result["attempt"] = _v4_global(_v4_scope, 'max')(0, _v4_global(_v4_scope, 'int')(result.get("attempt") or 0))
    except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')):
        result["attempt"] = 0
    return result
