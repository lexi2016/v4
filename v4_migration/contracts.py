from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

from .safe_io import read_absolute_file, write_new_absolute_file

HEX = set("0123456789abcdef")


def canonical_bytes(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def canonical_sha256(obj: Any) -> str:
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(read_absolute_file(path)).hexdigest()


def valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX


def require_sha(value: Any, label: str) -> str:
    if not valid_sha(value):
        raise ValueError(f"{label}_SHA256_INVALID")
    return value


def load_json(path: str | Path) -> Any:
    return json.loads(read_absolute_file(path).decode("utf-8"))


def immutable_write_json(path: str | Path, obj: Any) -> None:
    data = (json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    write_new_absolute_file(path, data)


def validate_authorization(
    receipt: dict[str, Any],
    *,
    candidate_sha: str,
    preflight_sha: str,
    binding_sha: str,
    required_actions: Iterable[str],
) -> None:
    """Deny cutover until an external, user/owner-approved trust root is configured."""
    raise ValueError("AUTHORIZATION_TRUST_ROOT_UNCONFIGURED")
