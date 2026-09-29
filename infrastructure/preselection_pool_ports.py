"""Type-only ports implemented by the existing pool-store module.

A module object is passed at the original call boundary. This retains runtime
patch seams without copying globals, reflection, singleton binding or cycles.
"""
from __future__ import annotations
from typing import Any, Callable, Protocol

class PoolAPI(Protocol):
    POOL_ORDER: tuple[str, ...]
    _SHA256: Any
    _RECOVERABLE_EXPECTED_MISSING_ROLES: dict[str, str]
    _canonical_bytes: Callable[..., bytes]
    _date: Callable[..., str]
    _sha256: Callable[..., str]
    _sha256_bytes: Callable[..., str]
    _is_exact_expected_missing_placeholder: Callable[..., bool]
    validate_pool_artifact: Callable[..., str]
    _assert_safe: Callable[..., None]
