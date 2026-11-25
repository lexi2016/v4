"""Read bounded evidence snapshots without invoking their external producers."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import re
from typing import Any

from v4_core.runner.state import json_bytes
from v4_core.storage.db import normalize_iso_date, normalize_symbol

_SHA256 = re.compile(r"[0-9a-f]{64}")
_A_SYMBOL = re.compile(r"\d{6}\.(?:SH|SZ|BJ)")
_HK_SYMBOL = re.compile(r"\d{5}\.HK")
SAFETY_FLAGS = {
    "research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
}


class EvidenceError(ValueError):
    """Missing or inconsistent evidence cannot authorize a V4 publication."""


def require(condition: object, reason: str) -> None:
    if not condition:
        raise EvidenceError(reason)


def mapping(value: object, reason: str) -> dict[str, Any]:
    require(isinstance(value, dict), reason)
    return value


def iso_date(value: object) -> str:
    try:
        return date.fromisoformat(normalize_iso_date(str(value))).isoformat()
    except ValueError as exc:
        raise EvidenceError("INVALID_EVIDENCE_DATE") from exc


def aware_time(value: object) -> datetime:
    try:
        observed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise EvidenceError("INVALID_EVIDENCE_TIME") from exc
    require(observed.utcoffset() is not None, "UNBOUND_EVIDENCE_TIMEZONE")
    return observed


def symbol(value: object, market: str) -> str:
    normalized = normalize_symbol(str(value or ""))
    pattern = _A_SYMBOL if market == "A" else _HK_SYMBOL
    require(pattern.fullmatch(normalized), f"INVALID_{market}_SYMBOL")
    return normalized


def entry_digest(trade_date: str, keys: tuple[str, ...], entry: dict[str, Any]) -> str:
    return sha256(json_bytes({"trade_date": iso_date(trade_date), "scope": keys, "entry": entry})).hexdigest()


@dataclass(frozen=True)
class FileEvidence:
    path: str
    sha256: str
    data: bytes

    def json(self) -> Any:
        try:
            return json.loads(self.data)
        except (UnicodeError, ValueError) as exc:
            raise EvidenceError(f"INVALID_JSON_EVIDENCE:{self.path}") from exc

    def csv(self) -> list[dict[str, str]]:
        try:
            rows = csv.DictReader(StringIO(self.data.decode("utf-8-sig"), newline=""), strict=True)
            require(rows.fieldnames and len(set(rows.fieldnames)) == len(rows.fieldnames), "INVALID_CSV_HEADER")
            records = list(rows)
            require(all(None not in row and all(value is not None for value in row.values()) for row in records),
                    "INVALID_CSV_ROW")
            return records
        except (UnicodeError, csv.Error) as exc:
            raise EvidenceError(f"INVALID_CSV_EVIDENCE:{self.path}") from exc

    def identity(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "bytes": len(self.data)}


@dataclass(frozen=True)
class DatedInputs:
    directory: Path
    trade_date: str
    payload: dict[str, Any]
    sha256: str

    @classmethod
    def load(cls, root: Path, trade_date: str) -> DatedInputs:
        trade_date = iso_date(trade_date)
        resolved_root = root.resolve()
        directory = (resolved_root / trade_date).resolve()
        require(directory.is_relative_to(resolved_root), "DATED_EVIDENCE_PATH_ESCAPES_ROOT")
        try:
            path = (directory / "inputs.json").resolve()
            require(path.is_relative_to(directory), "DATED_EVIDENCE_PATH_ESCAPES_ROOT")
            data = path.read_bytes()
        except OSError as exc:
            raise EvidenceError("DATED_INPUTS_UNAVAILABLE") from exc
        digest = sha256(data).hexdigest()
        payload = mapping(FileEvidence("inputs.json", digest, data).json(), "INVALID_DATED_INPUTS")
        require(payload.get("schema") == "v4_core.r16_inputs.v1", "UNKNOWN_DATED_INPUTS_SCHEMA")
        require(iso_date(payload.get("trade_date")) == trade_date, "DATED_INPUTS_DATE_MISMATCH")
        return cls(directory, trade_date, payload, digest)

    def referenced_path(self, ref: object) -> Path:
        binding = mapping(ref, "EVIDENCE_FILE_REF_UNAVAILABLE")
        relative, expected = binding.get("path"), binding.get("sha256")
        require(isinstance(relative, str) and relative and not Path(relative).is_absolute()
                and ".." not in Path(relative).parts, "EVIDENCE_FILE_PATH_NOT_RELATIVE")
        require(isinstance(expected, str) and _SHA256.fullmatch(expected), "EVIDENCE_SHA256_UNBOUND")
        path = (self.directory / relative).resolve()
        require(path.is_relative_to(self.directory), "EVIDENCE_FILE_PATH_ESCAPES_ROOT")
        return path

    def file(self, ref: object) -> FileEvidence:
        path = self.referenced_path(ref)
        relative, expected = ref["path"], ref["sha256"]
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise EvidenceError(f"EVIDENCE_FILE_UNAVAILABLE:{relative}") from exc
        require(sha256(data).hexdigest() == expected, f"EVIDENCE_SHA256_MISMATCH:{relative}")
        return FileEvidence(relative, expected, data)

    def entry(self, key: str) -> dict[str, Any]:
        return mapping(self.payload.get(key), f"{key.upper()}_EVIDENCE_UNAVAILABLE")

    def entry_sha256(self, *keys: str) -> str:
        entry = self.payload
        for key in keys:
            entry = mapping(entry.get(key), f"{key.upper()}_EVIDENCE_UNAVAILABLE")
        return entry_digest(self.trade_date, keys, entry)
