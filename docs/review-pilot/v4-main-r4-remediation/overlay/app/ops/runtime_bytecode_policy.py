"""Enforce the R4 source-only Python cache launch identity."""
from __future__ import annotations

import os
import sys


SOURCE_ONLY_PYCACHE_PREFIX = "/dev/null/v4-main-r4-source-only-pycache"
PYCACHE_POLICY_REQUIRED = "V4_SOURCE_ONLY_PYCACHE_REQUIRED"


def require_source_only_cache_policy() -> dict[str, object] | None:
    """Fail closed when a process launched for the R4 Main requires this policy."""

    if os.environ.get(PYCACHE_POLICY_REQUIRED) != "1":
        return None
    if sys.pycache_prefix != SOURCE_ONLY_PYCACHE_PREFIX:
        raise RuntimeError("SOURCE_ONLY_PYCACHE_PREFIX_MISMATCH")
    if not sys.dont_write_bytecode:
        raise RuntimeError("SOURCE_ONLY_PYCACHE_WRITES_ENABLED")
    return {
        "required": True,
        "source_only_prefix": sys.pycache_prefix,
        "environment_prefix": os.environ.get("PYTHONPYCACHEPREFIX"),
        "dont_write_bytecode": sys.dont_write_bytecode,
    }
