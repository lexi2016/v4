from __future__ import annotations

import hashlib
import fcntl
import json
import os
import re
import stat
import time
from pathlib import Path
from typing import Any

from .contracts import canonical_sha256
from .safe_io import open_absolute_dir, read_relative_file_at, write_new_relative_file

_ENTRY = re.compile(r"^(\d{4,})_([A-Za-z0-9_.-]+)\.json$")


class AppendOnlyJournal:
    """Fsync-backed append-only journal; existing entries are revalidated on every append."""

    def __init__(self, root: str | Path):
        self.root = Path(os.path.abspath(os.fspath(root)))
        fd = open_absolute_dir(self.root, create=True)
        os.close(fd)

    def _entries(self, root_fd: int) -> list[tuple[str, dict[str, Any], str]]:
        names = [name for name in os.listdir(root_fd) if name.endswith(".json")]
        def sequence(name: str) -> int:
            match = _ENTRY.fullmatch(name)
            return int(match.group(1)) if match else -1
        names.sort(key=sequence)
        entries: list[tuple[str, dict[str, Any], str]] = []
        previous_sha: str | None = None
        for expected_seq, name in enumerate(names, 1):
            match = _ENTRY.fullmatch(name)
            if match is None or int(match.group(1)) != expected_seq:
                raise ValueError("JOURNAL_SEQUENCE_INVALID")
            raw = read_relative_file_at(root_fd, name)
            digest = hashlib.sha256(raw).hexdigest()
            record = json.loads(raw.decode("utf-8"))
            if not isinstance(record, dict) or record.get("schema") != "v4_migration.journal_receipt.v2":
                raise ValueError("JOURNAL_RECORD_INVALID")
            if record.get("seq") != expected_seq or record.get("phase") != match.group(2):
                raise ValueError("JOURNAL_RECORD_IDENTITY_INVALID")
            if record.get("previous_receipt_sha256") != previous_sha:
                raise ValueError("JOURNAL_CHAIN_INVALID")
            claimed = record.get("object_sha256")
            body = dict(record)
            body.pop("object_sha256", None)
            if claimed != canonical_sha256(body):
                raise ValueError("JOURNAL_OBJECT_SHA_MISMATCH")
            if not isinstance(record.get("payload"), dict):
                raise ValueError("JOURNAL_PAYLOAD_INVALID")
            entries.append((name, record, digest))
            previous_sha = digest
        return entries

    def append(self, phase: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(phase, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", phase):
            raise ValueError("JOURNAL_PHASE_INVALID")
        if not isinstance(payload, dict):
            raise ValueError("JOURNAL_PAYLOAD_INVALID")
        root_fd = open_absolute_dir(self.root, create=True)
        lock_fd = -1
        try:
            lock_fd = os.open(
                ".append.lock",
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
                mode=0o600,
                dir_fd=root_fd,
            )
            lock_stat = os.fstat(lock_fd)
            if not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_nlink != 1 or lock_stat.st_uid != os.getuid() or lock_stat.st_mode & 0o077:
                raise ValueError("JOURNAL_LOCK_NOT_REGULAR")
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                entries = self._entries(root_fd)
                previous = entries[-1][2] if entries else None
                seq = len(entries) + 1
                body = {
                    "schema": "v4_migration.journal_receipt.v2",
                    "seq": seq,
                    "phase": phase,
                    "created_monotonic_ns": time.monotonic_ns(),
                    "previous_receipt_sha256": previous,
                    "payload": payload,
                }
                record = dict(body, object_sha256=canonical_sha256(body))
                name = f"{seq:04d}_{phase}.json"
                raw = (json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
                write_new_relative_file(root_fd, name, raw)
                record["receipt_sha256"] = hashlib.sha256(raw).hexdigest()
                return record
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            if lock_fd >= 0:
                os.close(lock_fd)
            os.close(root_fd)
