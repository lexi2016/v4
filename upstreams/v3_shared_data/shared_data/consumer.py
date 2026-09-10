"""Read-only verified consumer for the shared raw store (DS2A).

``read_verified_latest`` reuses the store's own verification contract
(``SafeRootStore.verify_latest`` -> ``verify_run``) and performs zero writes:
no lock, no temp file, no mkdir. Every returned path is re-checked with
``resolve_under`` so symlink / reparse / traversal escapes fail closed as
``StoreError``. Tampered artifact / manifest / receipt, a missing latest
entry, and invalid date / role all surface as ``StoreError`` (never as
partial data).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import resolve_under
from .store import SafeRootStore, StoreError


@dataclass(frozen=True)
class VerifiedRun:
    """Verified snapshot of the latest run for one (trade_date, role) slot."""

    root: Path
    artifact_path: Path
    manifest_path: Path
    receipt_path: Path
    latest: dict[str, Any]
    manifest: dict[str, Any]
    receipt: dict[str, Any]
    verification: dict[str, Any]


def read_verified_latest(root: Path | str, trade_date: str, role: str) -> VerifiedRun:
    """Read the latest verified run under ``root`` for the given slot.

    Validation is delegated to the store (``verify_latest``), never duplicated
    here. Entry-relative fields in ``latest.json`` are untrusted: the run's
    relative paths are taken from the re-verified result only. Every failure
    mode (missing/invalid latest entry, tampered trio, traversal or symlink
    escape, invalid date/role) raises ``StoreError``.
    """
    store = SafeRootStore(root=root)
    try:
        outcome = store.verify_latest(trade_date, role)
        latest = outcome["latest"]
        verification = outcome["verified"]
        artifact_path = resolve_under(store.root, verification["artifact_relative"])
        manifest_path = resolve_under(store.root, verification["manifest_relative"])
        receipt_path = resolve_under(store.root, verification["receipt_relative"])
        with open(manifest_path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        with open(receipt_path, "r", encoding="utf-8") as handle:
            receipt = json.load(handle)
    except (ValueError, OSError, KeyError, TypeError) as error:
        # Validation helpers raise ValueError; a file vanishing mid-read
        # raises OSError. StoreError passes through unchanged.
        raise StoreError(f"verified read failed closed: {error}") from error
    return VerifiedRun(
        root=store.root,
        artifact_path=artifact_path,
        manifest_path=manifest_path,
        receipt_path=receipt_path,
        latest=latest,
        manifest=manifest,
        receipt=receipt,
        verification=verification,
    )
