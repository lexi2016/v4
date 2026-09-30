"""Fixed collector allowlist, keyed by (trade_date, date_role).

The formal package holds no host/V3 paths and parses no user-selected path
configuration. Allowlisted SourceSpec entries are constructed by trusted code
(isolated tooling: scripts/ for acceptance, tests/fixtures/ for tests) and
injected into ``AllowlistRegistry``; the registry itself is a neutral, fixed
mapping. The canary source path and its oracle pin live outside
``shared_data/``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .paths import validate_date, validate_role


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    role: str
    trade_date: str
    market: str
    stages: tuple[str, ...]
    cutoff_at: str
    source_path: Path
    collector: str = "file_replay"
    required_columns: tuple[str, ...] = ("trade_date", "bar_time", "open", "high", "low", "close", "volume")
    bar_time_column: str = "bar_time"
    expected_input_sha256: str | None = None
    expected_row_count: int | None = None
    cannot_confirm: tuple[str, ...] = ()
    provenance: dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        validate_date(self.trade_date)
        validate_role(self.role)
        if self.source_id in ("", ".", "..") or any(c in self.source_id for c in "/\\"):
            raise ValueError("invalid source_id")
        if not self.source_path.is_absolute():
            raise ValueError("allowlisted source path must be absolute")
        if not self.source_path.is_file():
            raise FileNotFoundError(f"allowlisted source missing: {self.source_path}")
        if self.cutoff_at.count(":") not in (1, 2):
            raise ValueError("cutoff_at must look like HH:MM or HH:MM:SS")
        for key, value in self.provenance.items():
            if not isinstance(key, str) or not isinstance(value, str) or not key:
                raise ValueError("provenance must be non-empty string pairs")
            if any(ch in value for ch in (":", "/", "\\")):
                raise ValueError("provenance values must be path-neutral")


class AllowlistRegistry:
    def __init__(self, entries: dict[tuple[str, str], tuple[SourceSpec, ...]] | None = None) -> None:
        # Neutral default: empty. Entries must be injected by callers.
        self._entries = dict(entries or {})

    def resolve(self, trade_date: str, role: str, source_id: str) -> SourceSpec:
        key = (validate_date(trade_date), validate_role(role))
        candidates = self._entries.get(key)
        if not candidates:
            raise ValueError(f"no allowlisted source for {trade_date} / {role}")
        for spec in candidates:
            if spec.source_id == source_id:
                spec.validate()
                return spec
        raise ValueError(f"source_id {source_id!r} not allowlisted for {trade_date} / {role}")

    def all_entries(self) -> dict[tuple[str, str], tuple[SourceSpec, ...]]:
        return dict(self._entries)
