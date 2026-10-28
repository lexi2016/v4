"""V3.5-owned runtime graph composition and persistence."""
from __future__ import annotations

import json
import hashlib
import math
import os
import re
import sqlite3
import stat
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from contracts.trading_calendar import MarketScope, RunPolicy, SessionRequirement, TradingDayState, load_market_calendar, resolve_market_states
from domains.runtime_policy import evaluate_run_policy
from infrastructure.data_store import NativeDataStore

from .collectors import (
    _DEFAULT_API_DATE_FIELDS,
    _DEFAULT_RECEIPT_DATE_FIELDS,
    collect_node_evidence,
)
from .bindings import load_v35_evidence_bindings, overlay_node_evidence
from .contracts import (
    EvidenceLayer,
    EvidenceResult,
    GraphStatus,
    load_runtime_graph_contract,
    reduce_graph_status,
    reduce_status,
    required_evidence_layers,
)
from .evidence_requirements import validate_required_evidence_declarations
from .http_client import make_http_get
from .repair import RepairController, SnapshotState, _InterProcessFileLock
from .snapshot import SAFETY_FLAGS, build_snapshot as compose_snapshot
from .store import (
    AtomicSnapshotStore,
    RuntimeEventStore,
    _assert_safe_path,
    _file_identity,
    _reparse,
    list_events_read_only,
)
from .topology import load_topology, topology_version_sha, validate_topology


SHANGHAI = timezone(timedelta(hours=8))
CONTRACT_PATH = Path(__file__).resolve().parents[2] / "contracts" / "v3_runtime_graph_contract.json"
MAX_SNAPSHOT_BYTES = 1024 * 1024
# Full semantic snapshot reads remain capped at MAX_SNAPSHOT_BYTES.  The API
# may use this separate, still-bounded envelope reader to expose topology and
# evidence identity when verbose evidence details make the immutable snapshot
# exceed the full-read cap.  It never raises the full-read limit in place.
MAX_SNAPSHOT_PROJECTION_BYTES = 8 * 1024 * 1024
SNAPSHOT_MAX_AGE_SECONDS = 90
SNAPSHOT_FUTURE_SKEW_SECONDS = 60
_SNAPSHOT_CORE_FIELDS = frozenset(
    {
        'schema_version',
        'business_date',
        'generated_at',
        'topology_schema_version',
        'topology_authority_root',
        'topology_version_sha',
        'nodes',
        'edges',
        'status',
        'reason',
    }
)
_EMPTY_EVIDENCE_REASONS = frozenset(
    {
        'TOPOLOGY_TIME_UNAVAILABLE',
        'TOPOLOGY_FUTURE',
        'TOPOLOGY_STALE',
        'NO_EVIDENCE',
        'EVIDENCE_INVALID',
    }
)
_BASE_DATE_FIELDS = frozenset(
    {
        'business_date',
        'trade_date',
        'review_date',
        'execution_date',
        'current_date',
        'page_trade_date',
        'page_date',
        'date',
    }
)
_SEMANTIC_BUSINESS_DATE_FIELDS = {
    'a_selector_manifest': frozenset({'target_date'}),
    'fupan_review_v3': frozenset({'review_date'}),
    'hk_d1_manifest': frozenset({'target_date'}),
    'research_event': frozenset({'trade_date'}),
    'stage_visibility_status': frozenset({'trade_date'}),
    'stage_workbench_snapshot': frozenset({'trade_date'}),
    'tomorrow_pool_status': frozenset({'signal_date'}),
}
_SEMANTIC_TARGET_DATE_ALIASES = frozenset({"a_selector_v35", "hk_d1_v35"})


def _next_v35_trade_date(business_date: str) -> str:
    parsed = datetime.strptime(business_date, "%Y%m%d").date()
    calendar = load_market_calendar()
    for offset in range(1, 371):
        candidate = parsed + timedelta(days=offset)
        text = candidate.strftime("%Y%m%d")
        states = resolve_market_states(calendar, text)
        if states["a_share"] not in {TradingDayState.NON_TRADING_DAY, TradingDayState.UNKNOWN} or states["hk_connect"] not in {TradingDayState.NON_TRADING_DAY, TradingDayState.UNKNOWN}:
            return text
    raise ValueError("RUNTIME_GRAPH_TARGET_DATE_UNAVAILABLE")


def _next_market_trade_date(business_date: str, market: str) -> str:
    """Return the next eligible session for one lane's market only."""
    from infrastructure.runtime_graph._service_parts.calendar import __next_market_trade_date_body as _v4_impl
    return _v4_impl(globals(), business_date, market)


def _target_date_for_node(node_id: str, business_date: str) -> str:
    if node_id == "ashare_v193_slot_selector_premarket":
        return _next_market_trade_date(business_date, "a_share")
    if node_id == "hkconnect_d1_top100_prob_active":
        return _next_market_trade_date(business_date, "hk_connect")
    return _next_v35_trade_date(business_date)


def _is_semantic_date_field(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    return any(
        segment == "date"
        or segment.endswith("_date")
        for segment in value.lower().split(".")
    )


@dataclass(frozen=True)
class RuntimeGraphBuild:
    state: SnapshotState
    snapshot_published: bool
    events_recorded: bool
    event_count: int
_DATE_RE = re.compile(r"^\d{8}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _reparse(metadata: os.stat_result) -> bool:
    return stat.S_ISLNK(metadata.st_mode) or bool(
        int(getattr(metadata, "st_file_attributes", 0))
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x0400)
    )


def _within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath(
            (os.path.normcase(str(path)), os.path.normcase(str(root)))
        ) == os.path.normcase(str(root))
    except ValueError:
        return False


def _assert_no_reparse_ancestors(path: Path) -> None:
    from infrastructure.runtime_graph._service_parts.filesystem_policy import __assert_no_reparse_ancestors_body as _v4_impl
    return _v4_impl(globals(), path)


def _ensure_directory(path: Path, *, allowed_root: Path) -> Path:
    from infrastructure.runtime_graph._service_parts.filesystem_policy import __ensure_directory_body as _v4_impl
    return _v4_impl(globals(), path, allowed_root=allowed_root)


def _valid_date(value: str) -> str:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise ValueError("RUNTIME_GRAPH_DATE_INVALID")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise ValueError("RUNTIME_GRAPH_DATE_INVALID") from error
    return value


def _now_default() -> datetime:
    return datetime.now(SHANGHAI)


def _read_snapshot_date(data_root: Path) -> str:
    try:
        catalog = NativeDataStore(data_root).read_catalog()
        return _valid_date(str(catalog["system_date"]))
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return datetime.now(SHANGHAI).strftime("%Y%m%d")


def _calendar_decision(
    run_policy: str,
    business_date: str,
    *,
    evaluator: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    from infrastructure.runtime_graph._service_parts.calendar import __calendar_decision_body as _v4_impl
    return _v4_impl(globals(), run_policy, business_date, evaluator=evaluator)


def _parse_now(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("RUNTIME_GRAPH_TIME_INVALID") from error
    else:
        raise ValueError("RUNTIME_GRAPH_TIME_INVALID")
    return parsed.replace(tzinfo=SHANGHAI) if parsed.tzinfo is None else parsed.astimezone(SHANGHAI)


def _parse_snapshot_time(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("SNAPSHOT_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("SNAPSHOT_TIME_INVALID") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(hours=8):
        raise ValueError("SNAPSHOT_TIME_INVALID")
    return parsed.astimezone(SHANGHAI)


def _read_snapshot_bytes(runtime_root: Path) -> bytes:
    from infrastructure.runtime_graph._service_parts.snapshot_io import __read_snapshot_bytes_body as _v4_impl
    return _v4_impl(globals(), runtime_root)


def _read_snapshot_state(runtime_root: Path) -> SnapshotState:
    raw = _read_snapshot_bytes(runtime_root)

    def reject_constant(value: str) -> None:
        raise ValueError(value)

    def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key, value in pairs:
            if key in payload:
                raise ValueError("SNAPSHOT_DUPLICATE_FIELD")
            payload[key] = value
        return payload

    try:
        payload = json.loads(
            raw.decode("utf-8-sig"),
            object_pairs_hook=reject_duplicate_pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("SNAPSHOT_MALFORMED") from error
    if not isinstance(payload, dict):
        raise ValueError("SNAPSHOT_MALFORMED")
    return SnapshotState(raw=raw, payload=payload)


def _decode_snapshot_payload(raw: bytes) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(value)

    def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key, value in pairs:
            if key in payload:
                raise ValueError("SNAPSHOT_DUPLICATE_FIELD")
            payload[key] = value
        return payload

    try:
        payload = json.loads(
            raw.decode("utf-8-sig"),
            object_pairs_hook=reject_duplicate_pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("SNAPSHOT_MALFORMED") from error
    if not isinstance(payload, dict):
        raise ValueError("SNAPSHOT_MALFORMED")
    return payload


def _read_snapshot_projection_bytes(runtime_root: Path) -> bytes:
    """Read one immutable snapshot through a distinct bounded projection cap."""
    from infrastructure.runtime_graph._service_parts.snapshot_io import __read_snapshot_projection_bytes_body as _v4_impl
    return _v4_impl(globals(), runtime_root)


def _bounded_evidence_summary(evidence: Any) -> list[dict[str, Any]]:
    from infrastructure.runtime_graph._service_parts.primitives import __bounded_evidence_summary_body as _v4_impl
    return _v4_impl(globals(), evidence)


def _bounded_text(value: Any, maximum: int = 4096) -> Any:
    if not isinstance(value, str):
        return value
    if len(value.encode("utf-8")) <= maximum:
        return value
    encoded = value.encode("utf-8")[:maximum]
    return encoded.decode("utf-8", errors="ignore") + "…[TRUNCATED]"


def _bounded_snapshot_projection(payload: Mapping[str, Any], raw: bytes) -> dict[str, Any]:
    """Keep topology identity and node evidence locators while dropping bulk details."""
    from infrastructure.runtime_graph._service_parts.snapshot_io import __bounded_snapshot_projection_body as _v4_impl
    return _v4_impl(globals(), payload, raw)


def _receipt_path_templates(value: Any) -> list[str]:
    """Collect declared receipt locators without reading or creating artifacts."""
    from infrastructure.runtime_graph._service_parts.primitives import __receipt_path_templates_body as _v4_impl
    return _v4_impl(globals(), value)


class RuntimeGraphService:
    """Build and serve a topology-complete, evidence-conservative snapshot."""

    def __init__(self, data_root: Path, *, now_provider: Callable[[], datetime] | None = None) -> None:
        self.data_root = Path(os.path.abspath(str(data_root)))
        self.runtime_root = self.data_root / "runtime_graph"
        if not _within(self.runtime_root, self.data_root):
            raise ValueError("RUNTIME_GRAPH_PATH_UNSAFE")
        _assert_no_reparse_ancestors(self.data_root)
        _assert_no_reparse_ancestors(self.runtime_root)
        self.contract = load_runtime_graph_contract(CONTRACT_PATH)
        topology = self.contract.get("topology")
        if not isinstance(topology, dict):
            raise ValueError("RUNTIME_GRAPH_TOPOLOGY_MISSING")
        self.topology = load_topology_from_contract(topology)
        self.topology_version_sha = topology_version_sha(self.topology)
        self.evidence_bindings = load_v35_evidence_bindings()
        for descriptor in self.topology["nodes"]:
            validate_required_evidence_declarations(
                overlay_node_evidence(
                    descriptor,
                    self.evidence_bindings.get(str(descriptor["node_id"])),
                )
            )
        self.now_provider = now_provider or _now_default
        self.allowed_node_ids = frozenset(str(node["node_id"]) for node in self.topology["nodes"])
        self.repair_controller = RepairController(
            runtime_root=self.runtime_root,
            snapshot_provider=self._load_snapshot_state,
            rebuild_snapshot=lambda business_date: self.rebuild(
                business_date,
                _publication_lock_held=True,
            ),
            allowed_node_ids=self.allowed_node_ids,
        )

    def _business_date(self) -> str:
        return _read_snapshot_date(self.data_root)

    def _evidence(
        self,
        business_date: str,
        now: datetime,
        topology: dict[str, Any] | None = None,
        http_get: Callable[[str], Mapping[str, Any]] | None = None,
        read_text: Callable[[Path], str] | None = None,
        path_exists: Callable[[Path], bool] | None = None,
        path_lstat: Callable[[Path], os.stat_result | None] | None = None,
    ) -> dict[str, tuple[Any, ...]]:
        active_topology = topology or self.topology
        getter = http_get or make_http_get('http://127.0.0.1:8873')
        roots = {"data_root": self.data_root, "runtime_root": self.runtime_root}
        def collect(node: Mapping[str, Any]) -> tuple[Any, ...]:
            node_id = str(node["node_id"])
            return collect_node_evidence(
                node=overlay_node_evidence(node, self.evidence_bindings.get(node_id)),
                business_date=business_date,
                now=now,
                roots=roots,
                calendar_decision=_calendar_decision,
                http_get=getter,
                target_date=_target_date_for_node(node_id, business_date),
                read_text=read_text,
                path_exists=path_exists,
                path_lstat=path_lstat,
            )
        return {
            str(node["node_id"]): collect(node)
            for node in active_topology["nodes"]
        }

    def _runtime_topology_for_write(self, now: datetime) -> dict[str, Any]:
        from infrastructure.runtime_graph._service_parts.primitives import _RuntimeGraphService__runtime_topology_for_write_body as _v4_impl
        return _v4_impl(globals(), self, now)

    def _write_snapshot(self, payload: dict[str, Any]) -> SnapshotState:
        from infrastructure.runtime_graph._service_parts.graph_build import _RuntimeGraphService__write_snapshot_body as _v4_impl
        return _v4_impl(globals(), self, payload)

    def collect(
        self,
        business_date: str | None = None,
        *,
        now: Any = None,
        api_base: str = 'http://127.0.0.1:8873',
        http_get: Callable[[str], Mapping[str, Any]] | None = None,
        read_text: Callable[[Path], str] | None = None,
        path_exists: Callable[[Path], bool] | None = None,
        path_lstat: Callable[[Path], os.stat_result | None] | None = None,
        _publication_lock_held: bool = False,
    ) -> RuntimeGraphBuild:
        from infrastructure.runtime_graph._service_parts.graph_build import _RuntimeGraphService_collect_body as _v4_impl
        return _v4_impl(globals(), self, business_date, now=now, api_base=api_base, http_get=http_get, read_text=read_text, path_exists=path_exists, path_lstat=path_lstat, _publication_lock_held=_publication_lock_held)

    def _collect_locked(
        self,
        date: str,
        generated_at: datetime,
        getter: Callable[[str], Mapping[str, Any]],
        *,
        read_text: Callable[[Path], str] | None,
        path_exists: Callable[[Path], bool] | None,
        path_lstat: Callable[[Path], os.stat_result | None],
    ) -> RuntimeGraphBuild:
        from infrastructure.runtime_graph._service_parts.graph_build import _RuntimeGraphService__collect_locked_body as _v4_impl
        return _v4_impl(globals(), self, date, generated_at, getter, read_text=read_text, path_exists=path_exists, path_lstat=path_lstat)

    def rebuild(
        self,
        business_date: str | None = None,
        *,
        now: Any = None,
        api_base: str = 'http://127.0.0.1:8873',
        http_get: Callable[[str], Mapping[str, Any]] | None = None,
        read_text: Callable[[Path], str] | None = None,
        path_exists: Callable[[Path], bool] | None = None,
        path_lstat: Callable[[Path], os.stat_result | None] | None = None,
        _publication_lock_held: bool = False,
    ) -> SnapshotState:
        from infrastructure.runtime_graph._service_parts.graph_build import _RuntimeGraphService_rebuild_body as _v4_impl
        return _v4_impl(globals(), self, business_date, now=now, api_base=api_base, http_get=http_get, read_text=read_text, path_exists=path_exists, path_lstat=path_lstat, _publication_lock_held=_publication_lock_held)

    @staticmethod
    def _json_shape(value: Any) -> bool:
        from infrastructure.runtime_graph._service_parts.primitives import _RuntimeGraphService__json_shape_body as _v4_impl
        return _v4_impl(globals(), value)

    @staticmethod
    def _semantic_error() -> ValueError:
        return ValueError('SNAPSHOT_SEMANTICS_INVALID')

    @staticmethod
    def _declared_date_fields(value: Any, default: tuple[str, ...] = ()) -> tuple[str, ...]:
        if isinstance(value, str) and value:
            return (value,)
        if isinstance(value, list | tuple):
            fields = tuple(item for item in value if isinstance(item, str) and item)
            return fields or default
        return default

    def _validate_evidence_date(
        self,
        value: Any,
        business_date: str,
        *,
        matches_business_date: bool,
    ) -> None:
        from infrastructure.runtime_graph._service_parts.evidence_dates import _RuntimeGraphService__validate_evidence_date_body as _v4_impl
        return _v4_impl(globals(), self, value, business_date, matches_business_date=matches_business_date)

    def _validate_evidence_dates(
        self,
        evidence: Mapping[str, Any],
        descriptor: Mapping[str, Any],
        business_date: str,
        target_date: str | None = None,
    ) -> None:
        from infrastructure.runtime_graph._service_parts.evidence_dates import _RuntimeGraphService__validate_evidence_dates_body as _v4_impl
        return _v4_impl(globals(), self, evidence, descriptor, business_date, target_date)

    def _validate_node_runtime(
        self,
        node: Mapping[str, Any],
        descriptor: Mapping[str, Any],
        business_date: str,
        target_date: str | None = None,
    ) -> tuple[GraphStatus, str]:
        from infrastructure.runtime_graph._service_parts.node_semantics import _RuntimeGraphService__validate_node_runtime_body as _v4_impl
        return _v4_impl(globals(), self, node, descriptor, business_date, target_date)

    def _validate_snapshot_semantics(self, payload: Mapping[str, Any]) -> None:
        from infrastructure.runtime_graph._service_parts.node_semantics import _RuntimeGraphService__validate_snapshot_semantics_body as _v4_impl
        return _v4_impl(globals(), self, payload)

    def _load_snapshot_state(self) -> SnapshotState:
        from infrastructure.runtime_graph._service_parts.snapshot_state import _RuntimeGraphService__load_snapshot_state_body as _v4_impl
        return _v4_impl(globals(), self)

    def _load_bounded_snapshot_state(self) -> SnapshotState:
        from infrastructure.runtime_graph._service_parts.snapshot_io import _RuntimeGraphService__load_bounded_snapshot_state_body as _v4_impl
        return _v4_impl(globals(), self)

    def _load_readable_snapshot_state(self) -> SnapshotState:
        try:
            return self._load_snapshot_state()
        except ValueError as error:
            if str(error) != "SNAPSHOT_TOO_LARGE":
                raise
            return self._load_bounded_snapshot_state()

    # Kept explicit for collector and allowlisted repair callers.  API paths
    # use _load_snapshot_state and never fall back to this writer.
    def _load_or_build_state(self) -> SnapshotState:
        try:
            return self._load_snapshot_state()
        except (OSError, ValueError, TypeError, KeyError):
            pass
        return self.rebuild()

    def snapshot(self) -> dict[str, Any]:
        from infrastructure.runtime_graph._service_parts.reader_endpoints import _RuntimeGraphService_snapshot_body as _v4_impl
        return _v4_impl(globals(), self)

    def status(self) -> dict[str, Any]:
        from infrastructure.runtime_graph._service_parts.reader_endpoints import _RuntimeGraphService_status_body as _v4_impl
        return _v4_impl(globals(), self)

    def events(self, node_id: str, limit: int) -> dict[str, Any]:
        from infrastructure.runtime_graph._service_parts.reader_endpoints import _RuntimeGraphService_events_body as _v4_impl
        return _v4_impl(globals(), self, node_id, limit)


def load_topology_from_contract(topology: dict[str, Any]) -> dict[str, Any]:
    """Validate the frozen cardinalities before the topology enters runtime."""
    from infrastructure.runtime_graph._service_parts.primitives import _load_topology_from_contract_body as _v4_impl
    return _v4_impl(globals(), topology)


def load_topology_payload(topology: dict[str, Any]) -> dict[str, Any]:
    validate_topology(topology)
    return topology
