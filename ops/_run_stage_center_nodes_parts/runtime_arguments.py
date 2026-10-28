"""ops.run_stage_center_nodes: runtime_arguments (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __load_config_body(_v4_scope, /, path):
    payload = _v4_global(_v4_scope, 'json').loads(path.read_text(encoding="utf-8"))
    if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'dict')):
        raise _v4_global(_v4_scope, 'ValueError')("node config must be a JSON object")
    for key in _v4_global(_v4_scope, 'REQUIRED_CONFIG_KEYS'):
        value = payload.get(key)
        if not _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'str')) or not value.startswith("/"):
            raise _v4_global(_v4_scope, 'ValueError')(f"explicit absolute config root required: {key}")
    for key, value in payload.items():
        if key.endswith("_root") or key.endswith("_path"):
            if value is None or not _v4_global(_v4_scope, 'str')(value).startswith("/"):
                raise _v4_global(_v4_scope, 'ValueError')(f"config path must be absolute: {key}")
    if payload.get("schema_version") not in (None, "stage_center.tick_config.v1"):
        raise _v4_global(_v4_scope, 'ValueError')("unsupported stage-center config schema")
    max_attempts = _v4_global(_v4_scope, 'int')(payload.get("node_max_attempts", _v4_global(_v4_scope, 'DEFAULT_MAX_ATTEMPTS')))
    if max_attempts < 1 or max_attempts > 3:
        raise _v4_global(_v4_scope, 'ValueError')("node_max_attempts must be between 1 and 3")
    retry_backoff = _v4_global(_v4_scope, 'float')(
        payload.get("node_retry_backoff_seconds", _v4_global(_v4_scope, 'DEFAULT_RETRY_BACKOFF_SECONDS'))
    )
    if retry_backoff < 0 or retry_backoff > 3600:
        raise _v4_global(_v4_scope, 'ValueError')("node_retry_backoff_seconds is outside the bounded range")
    max_nodes = _v4_global(_v4_scope, 'int')(payload.get("node_max_nodes_per_run", _v4_global(_v4_scope, 'DEFAULT_MAX_NODES_PER_RUN')))
    if max_nodes < 1 or max_nodes > _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'NODES')):
        raise _v4_global(_v4_scope, 'ValueError')("node_max_nodes_per_run is outside the bounded range")
    payload["node_max_attempts"] = max_attempts
    payload["node_retry_backoff_seconds"] = retry_backoff
    payload["node_max_nodes_per_run"] = max_nodes
    return payload
