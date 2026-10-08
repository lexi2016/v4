"""Canonical hashing helpers (byte-identical to V3.5 data_store idioms)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SHA256_RE = "abcdef0123456789"  # informational; full check is 64-hex


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_bytes(value))


def is_sha256_hex(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
