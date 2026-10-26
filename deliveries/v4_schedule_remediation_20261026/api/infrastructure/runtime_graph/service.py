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
SNAPSHOT_MAX_AGE_SECONDS = 360
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
    if market not in {"a_share", "hk_connect", "hk_securities"}:
        raise ValueError("RUNTIME_GRAPH_MARKET_INVALID")
    parsed = datetime.strptime(business_date, "%Y%m%d").date()
    calendar = load_market_calendar()
    for offset in range(1, 371):
        candidate = parsed + timedelta(days=offset)
        text = candidate.strftime("%Y%m%d")
        state = resolve_market_states(calendar, text)[market]
        if state not in {TradingDayState.NON_TRADING_DAY, TradingDayState.UNKNOWN}:
            return text
    raise ValueError("RUNTIME_GRAPH_TARGET_DATE_UNAVAILABLE")


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
    absolute = Path(os.path.abspath(str(path)))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as error:
            raise ValueError("RUNTIME_GRAPH_PATH_UNSAFE") from error
        if _reparse(metadata):
            raise ValueError("RUNTIME_GRAPH_PATH_UNSAFE")


def _ensure_directory(path: Path, *, allowed_root: Path) -> Path:
    destination = Path(os.path.abspath(str(path)))
    root = Path(os.path.abspath(str(allowed_root)))
    if not _within(destination, root):
        raise ValueError("RUNTIME_GRAPH_PATH_UNSAFE")
    # The full parent chain is checked before mkdir, including missing roots'
    # existing ancestors.  This prevents a junction from redirecting creation.
    _assert_no_reparse_ancestors(root)
    _assert_no_reparse_ancestors(destination)
    try:
        metadata = os.lstat(destination)
    except FileNotFoundError:
        metadata = None
    except OSError as error:
        raise ValueError("RUNTIME_GRAPH_PATH_UNSAFE") from error
    if metadata is not None and (_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode)):
        raise ValueError("RUNTIME_GRAPH_PATH_UNSAFE")
    if metadata is None:
        destination.mkdir(parents=True, exist_ok=True)
    _assert_no_reparse_ancestors(destination)
    return destination


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
    date = _valid_date(business_date)
    if run_policy == "natural_day":
        return {"should_run": True, "status": "NATURAL_DAY", "business_date": date}
    policy_by_name = {
        "a_share_trade_day": (RunPolicy.A_SHARE_TRADE_DAY, MarketScope.A_SHARE),
        "hk_connect_trade_day": (RunPolicy.HK_CONNECT_TRADE_DAY, MarketScope.HK_CONNECT),
        "hk_securities_trade_day": (RunPolicy.HK_SECURITIES_TRADE_DAY, MarketScope.HK_CONNECT),
        "a_or_hk_connect_trade_day": (
            RunPolicy.A_OR_HK_CONNECT_TRADE_DAY,
            MarketScope.CROSS_MARKET,
        ),
        "a_or_hk_securities_trade_day": (
            RunPolicy.A_OR_HK_SECURITIES_TRADE_DAY,
            MarketScope.CROSS_MARKET,
        ),
    }
    selected = policy_by_name.get(run_policy)
    if selected is None:
        return {"should_run": False, "status": "CALENDAR_UNAVAILABLE"}
    policy, scope = selected
    try:
        decision = (evaluator or evaluate_run_policy)(
            policy=policy,
            trade_date=date,
            slot=None,
            market_scope=scope,
            session_requirement=SessionRequirement.DAY_ELIGIBILITY_ONLY,
        )
    except Exception:
        return {"should_run": False, "status": "CALENDAR_UNAVAILABLE"}
    if not getattr(decision, "eligible", False):
        return {
            "should_run": False,
            "status": str(getattr(decision, "calendar_status", "UNKNOWN")),
        }
    return {
        "should_run": True,
        "status": str(getattr(decision, "calendar_status", "TRADING_DAY")),
        "business_date": date,
    }


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
    path = runtime_root / "snapshots" / "current.json"
    try:
        _assert_safe_path(path, runtime_root)
        before = os.lstat(path)
    except FileNotFoundError as error:
        raise ValueError("SNAPSHOT_MISSING") from error
    except (OSError, ValueError) as error:
        raise ValueError("SNAPSHOT_PATH_UNSAFE") from error
    if _reparse(before) or not stat.S_ISREG(before.st_mode) or int(getattr(before, "st_nlink", 1)) != 1:
        raise ValueError("SNAPSHOT_PATH_UNSAFE")
    if before.st_size > MAX_SNAPSHOT_BYTES:
        raise ValueError("SNAPSHOT_TOO_LARGE")
    identity = _file_identity(before)
    try:
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            raw = handle.read(MAX_SNAPSHOT_BYTES + 1)
            closed = os.fstat(handle.fileno())
        after = os.lstat(path)
    except OSError as error:
        raise ValueError("SNAPSHOT_UNREADABLE") from error
    if (
        len(raw) > MAX_SNAPSHOT_BYTES
        or _reparse(after)
        or not stat.S_ISREG(after.st_mode)
        or int(getattr(after, "st_nlink", 1)) != 1
        or any(_file_identity(item) != identity for item in (opened, closed, after))
    ):
        raise ValueError("SNAPSHOT_PATH_UNSAFE")
    return raw


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
    path = runtime_root / "snapshots" / "current.json"
    try:
        _assert_safe_path(path, runtime_root)
        before = os.lstat(path)
    except FileNotFoundError as error:
        raise ValueError("SNAPSHOT_MISSING") from error
    except (OSError, ValueError) as error:
        raise ValueError("SNAPSHOT_PATH_UNSAFE") from error
    if _reparse(before) or not stat.S_ISREG(before.st_mode) or int(getattr(before, "st_nlink", 1)) != 1:
        raise ValueError("SNAPSHOT_PATH_UNSAFE")
    if before.st_size > MAX_SNAPSHOT_PROJECTION_BYTES:
        raise ValueError("SNAPSHOT_PROJECTION_TOO_LARGE")
    identity = _file_identity(before)
    try:
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            raw = handle.read(MAX_SNAPSHOT_PROJECTION_BYTES + 1)
            closed = os.fstat(handle.fileno())
        after = os.lstat(path)
    except OSError as error:
        raise ValueError("SNAPSHOT_UNREADABLE") from error
    if (
        len(raw) > MAX_SNAPSHOT_PROJECTION_BYTES
        or _reparse(after)
        or not stat.S_ISREG(after.st_mode)
        or int(getattr(after, "st_nlink", 1)) != 1
        or any(_file_identity(item) != identity for item in (opened, closed, after))
    ):
        raise ValueError("SNAPSHOT_PATH_UNSAFE")
    return raw


def _bounded_evidence_summary(evidence: Any) -> list[dict[str, Any]]:
    if not isinstance(evidence, list):
        return []
    summary: list[dict[str, Any]] = []
    for item in evidence:
        if not isinstance(item, Mapping):
            continue
        details = item.get("details")
        record: dict[str, Any] = {
            "layer": item.get("layer"),
            "status": item.get("status"),
            "reason": _bounded_text(item.get("reason")),
        }
        if isinstance(details, Mapping):
            for key in ("receipt_path", "artifact_path", "manifest_path", "artifact_sha256", "manifest_sha256", "receipt_sha256", "date_role"):
                value = details.get(key)
                if isinstance(value, (str, int, bool)):
                    record[key] = value
        summary.append(record)
    return summary


def _bounded_text(value: Any, maximum: int = 4096) -> Any:
    if not isinstance(value, str):
        return value
    if len(value.encode("utf-8")) <= maximum:
        return value
    encoded = value.encode("utf-8")[:maximum]
    return encoded.decode("utf-8", errors="ignore") + "…[TRUNCATED]"


def _bounded_snapshot_projection(payload: Mapping[str, Any], raw: bytes) -> dict[str, Any]:
    """Keep topology identity and node evidence locators while dropping bulk details."""
    nodes = payload.get("nodes")
    projected_nodes: list[dict[str, Any]] = []
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, Mapping):
                continue
            projected = {
                key: _bounded_text(value)
                for key, value in node.items()
                if key != "evidence"
            }
            projected["evidence_count"] = len(node.get("evidence") or []) if isinstance(node.get("evidence"), list) else 0
            projected["evidence"] = _bounded_evidence_summary(node.get("evidence"))
            projected_nodes.append(projected)
    projection = {
        key: _bounded_text(payload.get(key))
        for key in (
            "schema_version", "business_date", "generated_at", "topology_schema_version",
            "topology_authority_root", "topology_version_sha", "edges", "status", "reason",
            *SAFETY_FLAGS,
        )
        if key in payload
    }
    projection["nodes"] = projected_nodes
    projection["snapshot_projection"] = {
        "bounded": True,
        "source_bytes": len(raw),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "dropped_fields": ["evidence.details"],
        "max_bytes": MAX_SNAPSHOT_PROJECTION_BYTES,
        "semantic_status": "CANNOT_CONFIRM_FULL_DETAILS",
    }
    return projection


def _receipt_path_templates(value: Any) -> list[str]:
    """Collect declared receipt locators without reading or creating artifacts."""
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == "receipt_path" and isinstance(item, str) and item:
                paths.append(item)
            else:
                paths.extend(_receipt_path_templates(item))
    elif isinstance(value, list | tuple):
        for item in value:
            paths.extend(_receipt_path_templates(item))
    return paths


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
        topology = json.loads(json.dumps(self.contract["topology"], ensure_ascii=False))
        topology["generated_at"] = now.isoformat(timespec="seconds")
        topology = load_topology_from_contract(topology)
        path = self.runtime_root / "topology" / "current.json"
        _ensure_directory(self.runtime_root, allowed_root=self.data_root.parent)
        _assert_safe_path(self.runtime_root, self.data_root)
        _ensure_directory(path.parent, allowed_root=self.runtime_root)
        AtomicSnapshotStore(
            path,
            allowed_root=self.runtime_root,
            expected_schema="v3_runtime_topology.v1",
        ).write(topology)
        return load_topology(path)

    def _write_snapshot(self, payload: dict[str, Any]) -> SnapshotState:
        path = self.runtime_root / "snapshots" / "current.json"
        _ensure_directory(self.runtime_root, allowed_root=self.data_root.parent)
        _assert_safe_path(self.runtime_root, self.data_root)
        _ensure_directory(path.parent, allowed_root=self.runtime_root)
        _assert_safe_path(path.parent, self.runtime_root)
        AtomicSnapshotStore(path, allowed_root=self.runtime_root, expected_schema="v3_runtime_snapshot.v1").write(payload)
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise ValueError("RUNTIME_GRAPH_SNAPSHOT_WRITE_UNCONFIRMED") from error
        return SnapshotState(raw=raw, payload=payload)

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
        date = _valid_date(business_date or self._business_date())
        generated_at = _parse_now(now if now is not None else self.now_provider())
        getter = http_get or make_http_get(api_base)
        if _publication_lock_held:
            return self._collect_locked(
                date,
                generated_at,
                getter,
                read_text=read_text,
                path_exists=path_exists,
                path_lstat=path_lstat,
            )
        _ensure_directory(self.runtime_root, allowed_root=self.data_root.parent)
        _assert_safe_path(self.runtime_root, self.data_root)
        _ensure_directory(self.runtime_root / "state", allowed_root=self.runtime_root)
        lock = _InterProcessFileLock(self.runtime_root / "state" / "publication.lock")
        acquired = lock.acquire(blocking=True)
        if not acquired:
            raise ValueError("RUNTIME_GRAPH_PUBLICATION_BUSY")
        try:
            return self._collect_locked(
                date,
                generated_at,
                getter,
                read_text=read_text,
                path_exists=path_exists,
                path_lstat=path_lstat,
            )
        finally:
            lock.release()

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
        try:
            current = _read_snapshot_state(self.runtime_root)
            if (
                current.payload.get("business_date") == date
                and current.payload.get("topology_version_sha") == self.topology_version_sha
                and _parse_snapshot_time(current.payload.get("generated_at")) > generated_at
            ):
                self._validate_snapshot_semantics(current.payload)
                return RuntimeGraphBuild(
                    state=current,
                    snapshot_published=False,
                    events_recorded=False,
                    event_count=0,
                )
        except (OSError, TypeError, ValueError):
            pass
        topology = self._runtime_topology_for_write(generated_at)
        snapshot = compose_snapshot(
            topology=topology,
            evidence_by_node=self._evidence(
                date,
                generated_at,
                topology,
                http_get=getter,
                read_text=read_text,
                path_exists=path_exists,
                path_lstat=path_lstat,
            ),
            business_date=date,
            generated_at=generated_at,
            topology_freshness_seconds=self.contract['freshness_seconds']['topology'],
        )
        state = self._write_snapshot(snapshot)
        events_recorded = False
        event_count = 0
        try:
            _ensure_directory(self.runtime_root / 'state', allowed_root=self.runtime_root)
            event_count = RuntimeEventStore(
                self.runtime_root / 'state' / 'graph_state.db',
                observed_at=lambda: generated_at,
                allowed_root=self.runtime_root,
            ).record_transitions(snapshot)
            events_recorded = True
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            # The snapshot remains truthful; events are separately reported as a gap.
            pass
        return RuntimeGraphBuild(
            state=state,
            snapshot_published=True,
            events_recorded=events_recorded,
            event_count=event_count,
        )

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
        return self.collect(
            business_date,
            now=now,
            api_base=api_base,
            http_get=http_get,
            read_text=read_text,
            path_exists=path_exists,
            path_lstat=path_lstat,
            _publication_lock_held=_publication_lock_held,
        ).state

    @staticmethod
    def _json_shape(value: Any) -> bool:
        if value is None or type(value) in {str, int, bool}:
            return True
        if type(value) is float:
            return math.isfinite(value)
        if isinstance(value, list):
            return all(RuntimeGraphService._json_shape(item) for item in value)
        if isinstance(value, Mapping):
            return all(
                isinstance(key, str) and RuntimeGraphService._json_shape(item)
                for key, item in value.items()
            )
        return False

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
        if not isinstance(value, str) or _DATE_RE.fullmatch(value) is None:
            raise self._semantic_error()
        try:
            datetime.strptime(value, '%Y%m%d')
        except ValueError:
            raise self._semantic_error() from None
        if matches_business_date and value != business_date:
            raise self._semantic_error()

    def _validate_evidence_dates(
        self,
        evidence: Mapping[str, Any],
        descriptor: Mapping[str, Any],
        business_date: str,
        target_date: str | None = None,
    ) -> None:
        layer = evidence.get('layer')
        details = evidence.get('details')
        if not isinstance(details, Mapping):
            return
        # FAIL evidence may intentionally carry a previous-date receipt,
        # artifact, API payload, or page receipt to prove staleness.  Its date
        # shape remains strict, but equality with the snapshot date is a PASS
        # invariant rather than a requirement for recording the failure.
        require_business_date_match = (
            evidence.get('status') != GraphStatus.FAIL.value
        )

        if layer == EvidenceLayer.CALENDAR.value:
            if 'business_date' in details:
                self._validate_evidence_date(
                    details['business_date'], business_date, matches_business_date=True
                )
            return

        if layer == EvidenceLayer.EXECUTION.value:
            date_fields = self._declared_date_fields(
                descriptor.get('receipt_date_fields'), _DEFAULT_RECEIPT_DATE_FIELDS
            )
            records = details.get('receipts')
            if not isinstance(records, list):
                return
            for record in records:
                if not isinstance(record, Mapping) or not isinstance(record.get('receipt'), Mapping):
                    continue
                receipt = record['receipt']
                for field in date_fields:
                    target_role = descriptor.get('node_id') in {"ashare_v193_slot_selector_premarket", "hkconnect_d1_top100_prob_active"} and field in {"trade_date", "target_date"}
                    if field in receipt:
                        self._validate_evidence_date(
                            receipt[field],
                            target_date if target_role and target_date is not None else business_date,
                            matches_business_date=require_business_date_match,
                        )
            return

        if layer == EvidenceLayer.ARTIFACT.value:
            declarations = descriptor.get('status_sources')
            sources = details.get('sources')
            if not isinstance(sources, list):
                return
            for source in sources:
                if not isinstance(source, Mapping) or not isinstance(source.get('semantic_fields'), Mapping):
                    continue
                alias = source.get('semantic_alias')
                semantic_fields = source['semantic_fields']
                declared_date_fields: set[str] = set()
                if isinstance(declarations, list):
                    for declaration in declarations:
                        if not isinstance(declaration, Mapping) or declaration.get('semantic_alias') != alias:
                            continue
                        declared_date_fields.update(
                            self._declared_date_fields(declaration.get('date_fields'))
                        )
                        semantic_declaration = declaration.get('semantic_fields')
                        if isinstance(semantic_declaration, Mapping):
                            for name, path in semantic_declaration.items():
                                if not isinstance(name, str):
                                    continue
                                if _is_semantic_date_field(
                                    name
                                ) or _is_semantic_date_field(path):
                                    declared_date_fields.add(name)
                required_business_date_fields = (
                    _SEMANTIC_BUSINESS_DATE_FIELDS.get(alias, frozenset())
                    if isinstance(alias, str)
                    else frozenset()
                )
                for name, value in semantic_fields.items():
                    if not isinstance(name, str) or (
                        name not in declared_date_fields
                        and not _is_semantic_date_field(name)
                    ):
                        continue
                    target_role = alias in _SEMANTIC_TARGET_DATE_ALIASES and name in {"trade_date", "target_date"}
                    expected_date = target_date if target_role and target_date is not None else business_date
                    self._validate_evidence_date(
                        value,
                        expected_date,
                        matches_business_date=(
                            require_business_date_match
                            and (
                                target_role
                                or name in _BASE_DATE_FIELDS
                                or name in required_business_date_fields
                            )
                        ),
                    )
            return

        if layer == EvidenceLayer.API.value:
            probes = details.get('probes')
            if isinstance(probes, list):
                if not probes:
                    raise self._semantic_error()
                for record in probes:
                    if not isinstance(record, Mapping):
                        raise self._semantic_error()
                    role = record.get('date_role', 'business_date')
                    if role not in {'business_date', 'target_date'}:
                        raise self._semantic_error()
                    values = record.get('date_values')
                    if values is None and record.get('status') != GraphStatus.PASS.value:
                        continue
                    if not isinstance(values, list) or (record.get('status') == GraphStatus.PASS.value and not values):
                        raise self._semantic_error()
                    expected = target_date if role == 'target_date' and target_date is not None else business_date
                    for value in values:
                        self._validate_evidence_date(
                            value,
                            expected,
                            matches_business_date=require_business_date_match,
                        )
                return
            payload = details.get('payload')
            if not isinstance(payload, Mapping):
                return
            # A collector must be able to persist negative evidence for an
            # out-of-date API response.  Requiring an API_MISMATCH payload to
            # equal the snapshot date makes the collector's own fail-closed
            # snapshot impossible to load.  PASS evidence remains strict;
            # negative evidence still has to contain well-formed dates.
            declared = descriptor.get('api_date_fields')
            date_fields = (
                self._declared_date_fields(declared)
                if isinstance(declared, list | tuple)
                else _DEFAULT_API_DATE_FIELDS
            )
            for field in date_fields:
                if field in payload:
                    self._validate_evidence_date(
                        payload[field],
                        business_date,
                        matches_business_date=require_business_date_match,
                    )
            return

        if layer == EvidenceLayer.PAGE.value:
            receipt = details.get('receipt')
            if not isinstance(receipt, Mapping):
                return
            for field in ('business_date', 'page_date'):
                if field in receipt:
                    self._validate_evidence_date(
                        receipt[field],
                        business_date,
                        matches_business_date=require_business_date_match,
                    )

    def _validate_node_runtime(
        self,
        node: Mapping[str, Any],
        descriptor: Mapping[str, Any],
        business_date: str,
        target_date: str | None = None,
    ) -> tuple[GraphStatus, str]:
        runtime_fields = {'status', 'reason', 'evidence', *SAFETY_FLAGS}
        static_descriptor = {
            key: value
            for key, value in descriptor.items()
            if key not in {'status', 'reason', 'evidence', *SAFETY_FLAGS}
        }
        actual_static = {key: value for key, value in node.items() if key not in runtime_fields}
        if actual_static != static_descriptor:
            raise self._semantic_error()
        if set(node) != set(static_descriptor) | runtime_fields:
            raise self._semantic_error()
        for flag in SAFETY_FLAGS:
            if type(node.get(flag)) is not bool or node[flag] is not False:
                raise self._semantic_error()
        if type(node.get('status')) is not str or node['status'] not in {item.value for item in GraphStatus}:
            raise self._semantic_error()
        if type(node.get('reason')) is not str or not node['reason']:
            raise self._semantic_error()
        node_status = GraphStatus(node['status'])
        node_reason = node['reason']
        evidence = node.get('evidence')
        if not isinstance(evidence, list):
            raise self._semantic_error()
        if not evidence:
            if node_status is not GraphStatus.EVIDENCE_GAP or node_reason not in _EMPTY_EVIDENCE_REASONS:
                raise self._semantic_error()
            return node_status, node_reason
        evidence_keys = {'layer', 'status', 'reason', 'details'}
        results: list[EvidenceResult] = []
        for item in evidence:
            if not isinstance(item, Mapping) or set(item) != evidence_keys:
                raise self._semantic_error()
            if (
                type(item.get('layer')) is not str
                or type(item.get('status')) is not str
                or type(item.get('reason')) is not str
                or not item['reason']
                or not isinstance(item.get('details'), Mapping)
                or not self._json_shape(item['details'])
            ):
                raise self._semantic_error()
            self._validate_evidence_dates(item, descriptor, business_date, target_date)
            try:
                layer = EvidenceLayer(item['layer'])
                status = GraphStatus(item['status'])
                results.append(EvidenceResult(layer, status, item['reason'], item['details']))
            except (TypeError, ValueError):
                raise self._semantic_error() from None
        if len(results) == 1:
            if (
                results[0].layer is not EvidenceLayer.CALENDAR
                or results[0].status
                not in {GraphStatus.NOT_DUE, GraphStatus.SKIPPED_EXPECTED}
            ):
                raise self._semantic_error()
            if node_status is not results[0].status or node_reason != results[0].reason:
                raise self._semantic_error()
            return node_status, node_reason
        required = required_evidence_layers(descriptor)
        if len(results) != len(required) or any(
            item.status in {GraphStatus.NOT_DUE, GraphStatus.SKIPPED_EXPECTED}
            for item in results
        ):
            raise self._semantic_error()
        if [item.layer for item in results] != list(required):
            raise self._semantic_error()
        reduced = reduce_status(results, required)
        reduced_reason = next(item.reason for item in results if item.status is reduced)
        if node_status is not reduced or node_reason != reduced_reason:
            raise self._semantic_error()
        return node_status, node_reason

    def _validate_snapshot_semantics(self, payload: Mapping[str, Any]) -> None:
        expected_keys = _SNAPSHOT_CORE_FIELDS | set(SAFETY_FLAGS)
        if set(payload) != expected_keys:
            raise self._semantic_error()
        for flag in SAFETY_FLAGS:
            if type(payload.get(flag)) is not bool or payload[flag] is not False:
                raise self._semantic_error()
        if (
            payload.get('topology_schema_version') != self.topology['schema_version']
            or payload.get('topology_authority_root') != self.topology['authority_root']
            or payload.get('topology_version_sha') != self.topology_version_sha
        ):
            raise self._semantic_error()
        nodes = payload.get('nodes')
        if not isinstance(nodes, list) or len(nodes) != len(self.topology['nodes']):
            raise self._semantic_error()
        if payload.get('edges') != self.topology['edges']:
            raise self._semantic_error()
        statuses: list[GraphStatus] = []
        reasons: list[str] = []
        business_date = payload.get('business_date')
        if not isinstance(business_date, str):
            raise self._semantic_error()
        for node, descriptor in zip(nodes, self.topology['nodes']):
            if not isinstance(node, Mapping):
                raise self._semantic_error()
            try:
                target_date = _target_date_for_node(str(descriptor["node_id"]), business_date)
            except (KeyError, TypeError, ValueError):
                target_date = None
            status, reason = self._validate_node_runtime(node, descriptor, business_date, target_date)
            statuses.append(status)
            reasons.append(reason)
        graph_status = reduce_graph_status(statuses)
        if type(payload.get('status')) is not str or payload['status'] != graph_status.value:
            raise self._semantic_error()
        if type(payload.get('reason')) is not str or not payload['reason']:
            raise self._semantic_error()
        graph_reason = next(reason for status, reason in zip(statuses, reasons) if status is graph_status)
        if payload['reason'] != graph_reason:
            raise self._semantic_error()

    def _load_snapshot_state(self) -> SnapshotState:
        state = _read_snapshot_state(self.runtime_root)
        payload = state.payload
        required = {
            "schema_version",
            "business_date",
            "generated_at",
            "topology_schema_version",
            "topology_authority_root",
            "topology_version_sha",
            "nodes",
            "edges",
            "status",
            "reason",
        }
        if payload.get("schema_version") != "v3_runtime_snapshot.v1" or not required <= set(payload):
            raise ValueError("SNAPSHOT_SCHEMA_INVALID")
        business_date = payload.get("business_date")
        if not isinstance(business_date, str) or _DATE_RE.fullmatch(business_date) is None:
            raise ValueError("SNAPSHOT_SCHEMA_INVALID")
        try:
            datetime.strptime(business_date, "%Y%m%d")
        except ValueError as error:
            raise ValueError("SNAPSHOT_SCHEMA_INVALID") from error
        if (
            not isinstance(payload.get("topology_version_sha"), str)
            or _SHA_RE.fullmatch(str(payload["topology_version_sha"])) is None
            or not isinstance(payload.get("nodes"), list)
            or not isinstance(payload.get("edges"), list)
            or payload.get("status") not in {item.value for item in GraphStatus}
            or not isinstance(payload.get("reason"), str)
        ):
            raise ValueError("SNAPSHOT_SCHEMA_INVALID")
        generated_at = _parse_snapshot_time(payload.get("generated_at"))
        age = (_parse_now(self.now_provider()) - generated_at).total_seconds()
        if age < -SNAPSHOT_FUTURE_SKEW_SECONDS:
            raise ValueError("SNAPSHOT_FUTURE")
        if age > float(self.contract["freshness_seconds"]["runtime_snapshot"]):
            raise ValueError("SNAPSHOT_STALE")
        self._validate_snapshot_semantics(payload)
        return state

    def _load_bounded_snapshot_state(self) -> SnapshotState:
        raw = _read_snapshot_projection_bytes(self.runtime_root)
        payload = _decode_snapshot_payload(raw)
        required = _SNAPSHOT_CORE_FIELDS | set(SAFETY_FLAGS)
        if payload.get("schema_version") != "v3_runtime_snapshot.v1" or not required <= set(payload):
            raise ValueError("SNAPSHOT_SCHEMA_INVALID")
        business_date = payload.get("business_date")
        if not isinstance(business_date, str) or _DATE_RE.fullmatch(business_date) is None:
            raise ValueError("SNAPSHOT_SCHEMA_INVALID")
        try:
            datetime.strptime(business_date, "%Y%m%d")
        except ValueError as error:
            raise ValueError("SNAPSHOT_SCHEMA_INVALID") from error
        if (
            not isinstance(payload.get("topology_version_sha"), str)
            or _SHA_RE.fullmatch(str(payload["topology_version_sha"])) is None
            or payload["topology_version_sha"] != self.topology_version_sha
        ):
            raise ValueError("SNAPSHOT_SCHEMA_INVALID")
        if payload["topology_version_sha"] != self.topology_version_sha:
            raise ValueError("SNAPSHOT_TOPOLOGY_MISMATCH")
        generated_at = _parse_snapshot_time(payload.get("generated_at"))
        age = (_parse_now(self.now_provider()) - generated_at).total_seconds()
        if age < -SNAPSHOT_FUTURE_SKEW_SECONDS:
            raise ValueError("SNAPSHOT_FUTURE")
        if age > float(self.contract["freshness_seconds"]["runtime_snapshot"]):
            raise ValueError("SNAPSHOT_STALE")
        # Drop verbose evidence details only after the immutable source passes
        # the exact semantic, topology, node-count, and safety checks used by
        # the normal full snapshot reader.
        self._validate_snapshot_semantics(payload)
        return SnapshotState(raw=raw, payload=_bounded_snapshot_projection(payload, raw))

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
        try:
            state = self._load_readable_snapshot_state()
            payload = dict(state.payload)
            payload.setdefault("snapshot_identity", {
                "business_date": payload.get("business_date"),
                "topology_version_sha": payload.get("topology_version_sha"),
                "snapshot_sha256": hashlib.sha256(state.raw).hexdigest(),
            })
            return payload
        except (OSError, ValueError, TypeError, KeyError) as error:
            return {
                "ok": False,
                "status": GraphStatus.EVIDENCE_GAP.value,
                "reason": str(error) or "SNAPSHOT_UNAVAILABLE",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }

    def status(self) -> dict[str, Any]:
        try:
            state = self._load_readable_snapshot_state()
        except (OSError, ValueError, TypeError, KeyError) as error:
            return {
                "ok": False,
                "status": GraphStatus.EVIDENCE_GAP.value,
                "reason": str(error) or "SNAPSHOT_UNAVAILABLE",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        payload = state.payload
        counts = Counter(str(node.get("status")) for node in payload.get("nodes", []) if isinstance(node, dict))
        counts["total"] = len(payload.get("nodes", []))
        age = (_parse_now(self.now_provider()) - _parse_now(payload["generated_at"])).total_seconds()
        return {
            "ok": payload.get("status") != GraphStatus.EVIDENCE_GAP.value,
            "schema_version": payload.get("schema_version"),
            "status": payload.get("status"),
            "reason": payload.get("reason"),
            "business_date": payload.get("business_date"),
            "generated_at": payload.get("generated_at"),
            "topology_version_sha": payload.get("topology_version_sha"),
            "age_seconds": round(max(0.0, age), 3),
            "counts": dict(sorted(counts.items())),
            "snapshot_sha256": hashlib.sha256(state.raw).hexdigest(),
            "snapshot_projection": payload.get("snapshot_projection"),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    def events(self, node_id: str, limit: int) -> dict[str, Any]:
        try:
            events = list_events_read_only(
                self.runtime_root / "state" / "graph_state.db",
                allowed_root=self.runtime_root,
                node_id=node_id,
                limit=limit,
            )
        except (OSError, ValueError, TypeError):
            return {"ok": False, "status": GraphStatus.EVIDENCE_GAP.value, "reason": "EVENT_STORE_UNAVAILABLE", "events": []}
        descriptor = next(
            (item for item in self.topology["nodes"] if str(item.get("node_id")) == node_id),
            None,
        )
        binding = overlay_node_evidence(
            descriptor or {},
            self.evidence_bindings.get(node_id),
        )
        receipt_paths = sorted(set(_receipt_path_templates(binding)))
        projected_events = []
        for event in events:
            projected = dict(event)
            projected["receipt_paths"] = receipt_paths
            projected["receipt_path"] = receipt_paths[0] if receipt_paths else None
            projected_events.append(projected)
        dates = sorted({str(item.get("business_date")) for item in projected_events})
        invalid = [
            item for item in projected_events
            if item.get("status") in {GraphStatus.FAIL.value, GraphStatus.DEGRADED.value, GraphStatus.EVIDENCE_GAP.value}
            or "CANNOT_CONFIRM" in str(item.get("reason") or "")
            or "INVALID" in str(item.get("reason") or "")
        ]
        return {
            "ok": True,
            "status": GraphStatus.EVIDENCE_GAP.value if invalid else GraphStatus.PASS.value,
            "reason": "EVENTS_READ_WITH_CANNOT_CONFIRM" if invalid else "EVENTS_READ",
            "node_id": node_id,
            "topology_version_sha": self.topology_version_sha,
            "business_dates": dates,
            "receipt_paths": receipt_paths,
            "events": projected_events,
            "cannot_confirm": [
                f"EVENT_{item.get('id')}:{item.get('reason')}" for item in invalid
            ],
        }


def load_topology_from_contract(topology: dict[str, Any]) -> dict[str, Any]:
    """Validate the frozen cardinalities before the topology enters runtime."""
    loaded = load_topology_payload(topology)
    modules = Counter(str(node.get("module")) for node in loaded["nodes"])
    if len(loaded["nodes"]) != 34 or len(loaded["edges"]) != 20 or modules != Counter({
        "stage_selection": 5,
        "preselection": 5,
        "research": 8,
        "review": 7,
        "tasks": 3,
        "auxiliary": 6,
    }):
        raise ValueError("RUNTIME_GRAPH_FROZEN_TOPOLOGY_INVALID")
    return loaded


def load_topology_payload(topology: dict[str, Any]) -> dict[str, Any]:
    validate_topology(topology)
    return topology
