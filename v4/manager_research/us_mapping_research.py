"""Date-scoped, research-only US-to-HK relation projection for the Manager owner.

The reviewed 2026-09-30 report is an immutable retrospective research artifact.
Daily runs read only the injected exact-session US owner and a small reviewed
relation registry; they never fetch prices, assert PIT eligibility, or change
the existing Stage/selection/BUY paths.
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import threading
import time
from types import SimpleNamespace
from typing import Any, Mapping
from uuid import uuid4

from .contracts import canonical_json, sha256_json, strict_trade_date
from .safety import assert_manager_safe_tree
from .workspace_projection import FLAGS, HK, digest, timestamp
from .workspace_plan import plan_context

SCHEMA = "v4.manager_research.us_mapping_research.v1"
DAILY_SCHEMA = "v4.manager_research.us_mapping_daily_run.v1"
REVIEWED_PATH = Path(__file__).with_name("us_mapping_reviewed_20260930.json")
RELATION_REGISTRY_PATH = Path(__file__).with_name("us_mapping_relation_registry.json")
CURRENT_RELATION_EVIDENCE_PATH = Path(__file__).with_name("us_mapping_relation_evidence_20261011.json")
CURRENT_RELATION_REVIEW_PATH = Path(__file__).with_name("us_mapping_relation_evidence_review_20261011.json")
CURRENT_RELATION_REVIEW_RECEIPT_SHA256 = "5e24b82049ca848f7536b084166537415722375414cfc762da8b179919947350"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_TARGET_SEED = "20260930"
_DAILY_RELATION_TYPES = {"DIRECT_NAMED_COMPONENT_SUPPLY", "PRODUCT_PEER", "OPTICAL_TRANSPORT_PEER"}
_RELATION_TOKEN = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
MAX_PREPARATION_SECONDS = 5.0
DISPATCH_SCHEMA = "v4.manager_research.us_mapping_dispatch_attempt.v1"
_OWNER = "ManagerResearchJobService.refresh_us_mapping_research"
MAX_OWNER_SCAN_RUNS = 256
MAX_OWNER_SCAN_BYTES = 32 * 1024 * 1024
MAX_OWNER_RUN_BYTES = 1024 * 1024


class _ReadBudget:
    """One monotonic wall-clock and byte/file budget for owner-side recovery scans."""

    def __init__(self, deadline: float, *, max_runs: int = MAX_OWNER_SCAN_RUNS,
                 max_bytes: int = MAX_OWNER_SCAN_BYTES):
        self.deadline = deadline
        self.max_runs = max_runs
        self.max_bytes = max_bytes
        self.runs = 0
        self.bytes_read = 0

    def check(self) -> None:
        if time.monotonic() >= self.deadline:
            raise TimeoutError("US_MAPPING_OWNER_BUDGET_EXHAUSTED")

    def read_json(self, store: Any, path: Path, *, run_artifact: bool = False) -> dict[str, Any] | None:
        self.check()
        if run_artifact:
            self.runs += 1
            if self.runs > self.max_runs:
                raise TimeoutError("US_MAPPING_OWNER_SCAN_RUN_BOUND_EXCEEDED")
        relative = str(path.relative_to(store.root))
        try:
            raw = store._io.read_bytes(relative, max_bytes=MAX_OWNER_RUN_BYTES)
        except FileNotFoundError:
            self.check()
            return None
        self.check()
        self.bytes_read += len(raw)
        if self.bytes_read > self.max_bytes:
            raise TimeoutError("US_MAPPING_OWNER_SCAN_BYTE_BOUND_EXCEEDED")
        try:
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("not an object")
            assert_manager_safe_tree(value)
            canonical_json(value)
            return value
        except (UnicodeError, ValueError, TypeError) as exc:
            raise ValueError("US_MAPPING_OWNER_SCAN_OBJECT_INVALID") from exc


class _BuildJob:
    def __init__(self, service: Any, date: str, now: datetime):
        self.done = threading.Event()
        self.value: dict[str, Any] | None = None
        self.error: BaseException | None = None
        self.service = SimpleNamespace(
            _workspace_us_market_reader=getattr(service, "_workspace_us_market_reader", None),
        )
        self.date = date
        self.now = now


_BUILD_LOCK = threading.Lock()
_ACTIVE_BUILD: _BuildJob | None = None
_ACTIVE_WORKSPACE_READERS: set[int] = set()


def workspace_reader_busy(reader: Any) -> bool:
    """Return whether this exact injected reader is owned by a live bounded read."""
    if reader is None:
        return False
    with _BUILD_LOCK:
        active = _ACTIVE_BUILD
        build_busy = bool(active is not None and not active.done.is_set()
            and getattr(active.service, '_workspace_us_market_reader', None) is reader)
        return build_busy or id(reader) in _ACTIVE_WORKSPACE_READERS


def try_enter_workspace_reader(reader: Any) -> bool:
    """Claim a direct workspace read so a new bounded owner cannot race it."""
    if reader is None:
        return True
    with _BUILD_LOCK:
        active = _ACTIVE_BUILD
        if (active is not None and not active.done.is_set()
                and getattr(active.service, '_workspace_us_market_reader', None) is reader):
            return False
        key = id(reader)
        if key in _ACTIVE_WORKSPACE_READERS:
            return False
        _ACTIVE_WORKSPACE_READERS.add(key)
        return True


def leave_workspace_reader(reader: Any) -> None:
    if reader is None:
        return
    with _BUILD_LOCK:
        _ACTIVE_WORKSPACE_READERS.discard(id(reader))


def _bounded_build(service: Any, date: str, now: datetime, timeout_seconds: float) -> tuple[dict[str, Any] | None, str | None]:
    """Run only the pure source projection in one process-wide, non-queueing lane."""
    global _ACTIVE_BUILD
    with _BUILD_LOCK:
        reader = getattr(service, "_workspace_us_market_reader", None)
        if reader is not None and id(reader) in _ACTIVE_WORKSPACE_READERS:
            return None, "US_MAPPING_OWNER_READ_BUSY"
        if _ACTIVE_BUILD is not None and not _ACTIVE_BUILD.done.is_set():
            return None, "US_MAPPING_OWNER_READ_BUSY"
        job = _BuildJob(service, date, now)
        _ACTIVE_BUILD = job

        def compute() -> None:
            try:
                job.value = build_daily_run(job.service, job.date, now=job.now)
            except BaseException as exc:  # always release the single lane, including unexpected reader exits
                job.error = exc
            finally:
                job.done.set()

        threading.Thread(target=compute, name="manager-us-daily-build", daemon=True).start()
    if not job.done.wait(timeout_seconds):
        return None, "US_MAPPING_OWNER_READ_TIMEOUT"
    if job.error is not None:
        return None, "US_MAPPING_OWNER_BUILD_FAILED"
    return job.value, None


def _now_text(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _aware_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.isoformat()


def _execution_metadata(value: Mapping[str, Any] | None, *, target: str,
                        started_at: datetime, finished_at: datetime,
                        research_cutoff_policy: str) -> dict[str, Any]:
    supplied = dict(value) if isinstance(value, Mapping) else {}
    trigger_kind = supplied.get("trigger_kind", "UNKNOWN")
    timing = supplied.get("timing", "UNCLASSIFIED")
    if trigger_kind not in {"SCHEDULED", "MANUAL", "UNKNOWN"}:
        raise ValueError("US_MAPPING_EXECUTION_TRIGGER_KIND_INVALID")
    if timing not in {"ON_TIME", "LATE_CATCHUP", "RETROSPECTIVE", "UNCLASSIFIED"}:
        raise ValueError("US_MAPPING_EXECUTION_TIMING_INVALID")
    if supplied.get("natural_run_verified", False) is not False:
        raise ValueError("US_MAPPING_NATURAL_RUN_CANNOT_BE_INFERRED")
    scheduled_for = supplied.get("scheduled_for")
    if scheduled_for is not None and _aware_text(scheduled_for) is None:
        raise ValueError("US_MAPPING_SCHEDULED_FOR_MUST_BE_AWARE")
    trigger_id = supplied.get("trigger_id")
    if trigger_id is not None and not re.fullmatch(r"[0-9a-f]{64}", str(trigger_id)):
        raise ValueError("US_MAPPING_TRIGGER_ID_INVALID")
    result = {
        "trigger_kind": trigger_kind,
        "timing": timing,
        "scheduled_for": _aware_text(scheduled_for) if scheduled_for is not None else None,
        "started_at": started_at.isoformat(timespec="microseconds"),
        "finished_at": finished_at.isoformat(timespec="microseconds"),
        "natural_run_verified": False,
        "research_cutoff_policy": research_cutoff_policy,
        "owner": _OWNER,
    }
    if trigger_id is not None:
        result["trigger_id"] = trigger_id
    return result


def _target_bound_cutoff(target: str, actual_now: datetime) -> tuple[datetime, str, str]:
    """Past-date recovery reads only through the target's end-of-day boundary."""
    if actual_now.tzinfo is None or actual_now.utcoffset() is None:
        raise ValueError("US_MAPPING_CLOCK_MUST_BE_AWARE")
    target_day = datetime.strptime(target, "%Y%m%d").date()
    local_now = actual_now.astimezone(HK)
    if target_day > local_now.date():
        raise ValueError("US_MAPPING_FUTURE_TARGET_NOT_ELIGIBLE")
    if target_day < local_now.date():
        cutoff = datetime.combine(target_day, datetime.max.time(), HK)
        return cutoff, "TARGET_DATE_END_OF_DAY_RETROSPECTIVE", "RETROSPECTIVE"
    return actual_now.astimezone(HK), "ACTUAL_OWNER_EXECUTION_CUTOFF", "UNCLASSIFIED"


def _failure_result(date: str, code: str, *, now: datetime,
                    execution_context: Mapping[str, Any] | None = None,
                    research_cutoff: datetime | None = None,
                    cutoff_policy: str = "ACTUAL_OWNER_EXECUTION_CUTOFF") -> dict[str, Any]:
    finished = datetime.now(now.tzinfo)
    context = dict(execution_context or {})
    if context.get("timing") == "UNCLASSIFIED" and context.get("trigger_kind") == "SCHEDULED":
        context["timing"] = "LATE_CATCHUP"
    return {
        "schema_version": DAILY_SCHEMA,
        "status": "FAILED",
        "target_trade_date": date,
        "run_id": None,
        "generated_at": None,
        "us_session_date": None,
        "research_cutoff": research_cutoff.isoformat() if research_cutoff else None,
        "coverage": {"reviewed_us_symbol_count": None, "matched_us_symbol_count": None,
                      "matched_hk_relation_count": None, "configured_us_universe_count": None,
                      "available_us_universe_count": None, "full_market_coverage": False},
        "matches": [],
        "execution_status": code,
        "execution_context": _execution_metadata(
            context, target=date, started_at=now, finished_at=finished,
            research_cutoff_policy=cutoff_policy),
        "gaps": [code],
        **FLAGS,
    }


def _seal_dispatch(value: Mapping[str, Any]) -> dict[str, Any]:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return {**body, "sha256": sha256_json(body)}


def _dispatch_path(store: Any, date: str, trigger_id: str, suffix: str = "") -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", trigger_id):
        raise ValueError("US_MAPPING_TRIGGER_ID_INVALID")
    return store.root / "us_mapping_dispatch" / date / f"{trigger_id}{suffix}.json"


def _read_dispatch(store: Any, date: str, trigger_id: str, *,
                   read_budget: _ReadBudget | None = None) -> dict[str, Any] | None:
    path = _dispatch_path(store, date, trigger_id)
    row = read_budget.read_json(store, path) if read_budget else store._read(path)
    if row is None:
        return None
    attempt = row.get("attempt")
    attempt_context = attempt.get("execution_context") if isinstance(attempt, Mapping) else None
    attempt_start = _aware_text(attempt.get("started_at")) if isinstance(attempt, Mapping) else None
    attempt_finish = _aware_text(attempt.get("finished_at")) if isinstance(attempt, Mapping) else None
    if (row.get("schema_version") != DISPATCH_SCHEMA or row.get("target_trade_date") != date
            or row.get("trigger_id") != trigger_id or row.get("state") != "COMPLETED"
            or row.get("sha256") != _seal_dispatch(row)["sha256"]
            or not isinstance(attempt, Mapping) or attempt.get("trigger_id") != trigger_id
            or attempt_start is None or attempt_finish is None
            or datetime.fromisoformat(attempt_finish) < datetime.fromisoformat(attempt_start)
            or not isinstance(attempt_context, Mapping)
            or attempt_context.get("trigger_id") != trigger_id
            or attempt_context.get("started_at") is None or attempt_context.get("finished_at") is None
            or any(row.get(key) is not flag for key, flag in FLAGS.items())):
        raise ValueError("US_MAPPING_DISPATCH_RECEIPT_INVALID")
    return row


def _read_publication_intent(store: Any, date: str, trigger_id: str, *,
                             read_budget: _ReadBudget | None = None) -> dict[str, Any] | None:
    path = _dispatch_path(store, date, trigger_id, '.publishing')
    row = read_budget.read_json(store, path) if read_budget else store._read(path)
    if row is None:
        return None
    if (row.get('schema_version') != 'v4.manager_research.us_mapping_publication_intent.v1'
            or row.get('state') != 'PUBLISHING' or row.get('target_trade_date') != date
            or row.get('trigger_id') != trigger_id
            or not re.fullmatch(r'[0-9a-f]{32}', str(row.get('run_id') or ''))
            or not _SHA.fullmatch(str(row.get('artifact_sha256') or ''))
            or row.get('sha256') != _seal_dispatch(row)['sha256']
            or any(row.get(key) is not flag for key, flag in FLAGS.items())):
        raise ValueError('US_MAPPING_PUBLICATION_INTENT_INVALID')
    return row


def _write_publication_intent(store: Any, date: str, trigger_id: str,
                              started: Mapping[str, Any], saved: Mapping[str, Any], *,
                              read_budget: _ReadBudget) -> dict[str, Any]:
    read_budget.check()
    intent = _seal_dispatch({
        'schema_version': 'v4.manager_research.us_mapping_publication_intent.v1',
        'state': 'PUBLISHING', 'target_trade_date': date, 'trigger_id': trigger_id,
        'started_at': started.get('started_at'), 'run_id': saved.get('run_id'),
        'artifact_sha256': saved.get('artifact_sha256'), 'owner': _OWNER, **FLAGS,
    })
    path = _dispatch_path(store, date, trigger_id, '.publishing')
    relative = str(path.relative_to(store.root))
    raw = json.dumps(intent, ensure_ascii=False, sort_keys=True,
                     separators=(',', ':'), allow_nan=False).encode('utf-8')
    store._io.write_bytes(relative, raw, require_absent=True)
    read_budget.check()
    readback = read_budget.read_json(store, path)
    if readback != intent:
        raise ValueError('US_MAPPING_PUBLICATION_INTENT_READBACK_FAILED')
    return intent


def _latest_dispatch_attempt(store: Any, date: str) -> dict[str, Any] | None:
    names = store._io.files(f"us_mapping_dispatch/{date}")
    terminal_names = [name for name in names if re.fullmatch(r"[0-9a-f]{64}\.json", name)]
    started_names = [name for name in names if re.fullmatch(r"[0-9a-f]{64}\.started\.json", name)]
    if len(terminal_names) + len(started_names) > 2048:
        raise ValueError("US_MAPPING_DISPATCH_RECEIPT_BOUND_EXCEEDED")
    rows = []
    terminal_ids = set()
    for name in terminal_names:
        receipt = _read_dispatch(store, date, name[:-5])
        if receipt is None:
            continue
        terminal_ids.add(str(receipt.get('trigger_id')))
        finished_text = receipt.get("finished_at")
        finished = _aware_text(finished_text)
        if finished is None:
            raise ValueError("US_MAPPING_DISPATCH_FINISHED_AT_INVALID")
        rows.append((datetime.fromisoformat(finished), 'TERMINAL', receipt))
    for name in started_names:
        trigger_id = name[:-len('.started.json')]
        if trigger_id in terminal_ids:
            continue
        path = _dispatch_path(store, date, trigger_id, '.started')
        started = store._read(path)
        if started is None:
            continue
        started_at = _aware_text(started.get('started_at'))
        if (started.get('schema_version') != DISPATCH_SCHEMA or started.get('state') != 'RUNNING'
                or started.get('target_trade_date') != date or started.get('trigger_id') != trigger_id
                or started.get('sha256') != _seal_dispatch(started)['sha256']
                or started_at is None or any(started.get(key) is not flag for key, flag in FLAGS.items())):
            raise ValueError('US_MAPPING_DISPATCH_STARTED_RECEIPT_INVALID')
        intent = _read_publication_intent(store, date, trigger_id)
        pending = {
            'schema_version': DISPATCH_SCHEMA,
            'state': 'PUBLISHING' if intent else 'RUNNING',
            'status': 'CANNOT_CONFIRM',
            'execution_status': 'US_MAPPING_DISPATCH_RECONCILIATION_REQUIRED' if intent
                else 'US_MAPPING_DISPATCH_IN_PROGRESS',
            'target_trade_date': date, 'trigger_id': trigger_id,
            'started_at': started_at, 'finished_at': None,
            'execution_context': deepcopy(started.get('execution_context')),
            'run_id': intent.get('run_id') if intent else None,
            'artifact_sha256': intent.get('artifact_sha256') if intent else None,
            'research_cutoff': None, 'generated_at': None,
            'gaps': ['US_MAPPING_DISPATCH_RECONCILIATION_REQUIRED' if intent
                     else 'US_MAPPING_DISPATCH_TERMINAL_RECEIPT_MISSING'],
            'coverage': {'reviewed_us_symbol_count': None, 'matched_us_symbol_count': None,
                'matched_hk_relation_count': None, 'configured_us_universe_count': None,
                'available_us_universe_count': None, 'full_market_coverage': False},
            'receipt_sha256': started.get('sha256'),
            'receipt_path': f'us_mapping_dispatch/{date}/{trigger_id}.started.json',
            'owner': _OWNER, **FLAGS,
        }
        rows.append((datetime.fromisoformat(started_at), 'PENDING', pending))
    if not rows:
        return None
    _, row_kind, receipt = max(rows, key=lambda item: item[0].astimezone(timezone.utc))
    if row_kind == 'PENDING':
        return receipt
    result = receipt.get("result") if isinstance(receipt.get("result"), Mapping) else {}
    return {
        "status": result.get("status", "CANNOT_CONFIRM"),
        "state": receipt.get('state'),
        "execution_status": result.get("execution_status"),
        "research_cutoff": result.get("research_cutoff"),
        "generated_at": result.get("generated_at"),
        "run_id": result.get("run_id"),
        "artifact_sha256": result.get("artifact_sha256"),
        "trigger_id": (receipt.get("attempt", {}).get("trigger_id")
                       if isinstance(receipt.get("attempt"), Mapping) else receipt.get("trigger_id")),
        "started_at": (receipt.get("attempt", {}).get("started_at")
                       if isinstance(receipt.get("attempt"), Mapping) else receipt.get("started_at")),
        "finished_at": (receipt.get("attempt", {}).get("finished_at")
                         if isinstance(receipt.get("attempt"), Mapping) else receipt.get("finished_at")),
        "execution_context": deepcopy(
            receipt.get("attempt", {}).get("execution_context")
            if isinstance(receipt.get("attempt"), Mapping) else result.get("execution_context")),
        "run_execution_context": deepcopy(result.get("execution_context")),
        "gaps": deepcopy(result.get("gaps") or []),
        "coverage": deepcopy(result.get("coverage")),
        "receipt_sha256": receipt.get("sha256"),
        "receipt_path": f"us_mapping_dispatch/{date}/{receipt.get('trigger_id')}.json",
        "owner": _OWNER,
        **FLAGS,
    }


def _read_exact_run(store: Any, date: str, run_id: str, expected_sha: str | None = None, *,
                    read_budget: _ReadBudget | None = None) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{32}", str(run_id or "")):
        raise ValueError("US_MAPPING_DAILY_RUN_ID_INVALID")
    path = store.root / "us_mapping_research" / date / "runs" / f"{run_id}.json"
    artifact = (read_budget.read_json(store, path, run_artifact=True)
                if read_budget else store._read(path))
    if artifact is None:
        raise ValueError("US_MAPPING_DAILY_ARTIFACT_MISSING")
    unsigned = {key: item for key, item in artifact.items() if key != "artifact_sha256"}
    if (artifact.get("schema_version") != DAILY_SCHEMA or artifact.get("target_trade_date") != date
            or artifact.get("run_id") != run_id or artifact.get("artifact_sha256") != sha256_json(unsigned)
            or (expected_sha is not None and artifact.get("artifact_sha256") != expected_sha)):
        raise ValueError("US_MAPPING_DAILY_ARTIFACT_INTEGRITY_FAILED")
    _safe_tree(artifact)
    return artifact


def _run_for_trigger(store: Any, date: str, trigger_id: str, *,
                     read_budget: _ReadBudget | None = None) -> dict[str, Any] | None:
    intent = _read_publication_intent(store, date, trigger_id, read_budget=read_budget)
    if intent is not None:
        row = _read_exact_run(store, date, intent['run_id'], intent['artifact_sha256'],
                              read_budget=read_budget)
        if read_budget:
            read_budget.check()
        return row
    if read_budget:
        read_budget.check()
    names = store._io.files(f"us_mapping_research/{date}/runs")
    if read_budget:
        read_budget.check()
    if len(names) > 4096:
        raise ValueError("US_MAPPING_DAILY_RUN_BOUND_EXCEEDED")
    matches = []
    for name in names:
        if read_budget:
            read_budget.check()
        if not re.fullmatch(r"[0-9a-f]{32}\.json", name):
            raise ValueError("US_MAPPING_DAILY_RUN_NAME_INVALID")
        row = _read_exact_run(store, date, name[:-5], read_budget=read_budget)
        if read_budget:
            read_budget.check()
        if ((row.get("execution_context") or {}).get("trigger_id") == trigger_id):
            matches.append(row)
    if len(matches) > 1:
        raise ValueError("US_MAPPING_TRIGGER_RUN_AMBIGUOUS")
    return matches[0] if matches else None


def _equivalent_run(store: Any, date: str, candidate: Mapping[str, Any], *,
                    read_budget: _ReadBudget | None = None) -> dict[str, Any] | None:
    if read_budget:
        read_budget.check()
    names = store._io.files(f"us_mapping_research/{date}/runs")
    if read_budget:
        read_budget.check()
    if len(names) > 4096:
        raise ValueError("US_MAPPING_DAILY_RUN_BOUND_EXCEEDED")
    for name in names:
        if read_budget:
            read_budget.check()
        if not re.fullmatch(r"[0-9a-f]{32}\.json", name):
            raise ValueError("US_MAPPING_DAILY_RUN_NAME_INVALID")
        row = _read_exact_run(store, date, name[:-5], read_budget=read_budget)
        if read_budget:
            read_budget.check()
        if (row.get("input_identity") == candidate.get("input_identity")
                and row.get("source_identity") == candidate.get("source_identity")
                and row.get("relation_artifact_sha256") == candidate.get("relation_artifact_sha256")
                and row.get("status") == candidate.get("status")):
            return row
    return None


def _write_dispatch_terminal(store: Any, date: str, trigger_id: str,
                             started: Mapping[str, Any], result: Mapping[str, Any], *,
                             read_budget: _ReadBudget | None = None,
                             attempt_context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    result_summary = {
        "status": result.get("status"),
        "run_id": result.get("run_id"),
        "artifact_sha256": result.get("artifact_sha256"),
        "execution_status": result.get("execution_status"),
        "research_cutoff": result.get("research_cutoff"),
        "generated_at": result.get("generated_at"),
        "execution_context": deepcopy(result.get("execution_context")),
        "gaps": list(result.get("gaps") or []),
        "coverage": deepcopy(result.get("coverage")),
        **FLAGS,
    }
    # A failure has no immutable run to read back, so preserve its complete
    # unknown/null DTO inside the sealed dispatch terminal for idempotent
    # same-trigger replay. Successful rows remain referenced by exact run/SHA.
    if not isinstance(result.get("run_id"), str):
        result_summary["failure_dto"] = {
            key: deepcopy(result.get(key))
            for key in ("schema_version", "status", "target_trade_date", "run_id", "generated_at",
                        "us_session_date", "research_cutoff", "coverage", "matches",
                        "source_identity", "input_identity", "artifact_sha256",
                        "execution_status", "execution_context", "gaps", *FLAGS.keys())
            if key in result
        }
    attempt = {
        "trigger_id": trigger_id,
        "started_at": started.get("started_at"),
        "finished_at": ((attempt_context or {}).get("finished_at")
                         or result_summary.get("execution_context", {}).get("finished_at")),
        "execution_context": deepcopy(dict(attempt_context or result_summary.get("execution_context") or {})),
    }
    terminal = _seal_dispatch({
        "schema_version": DISPATCH_SCHEMA,
        "state": "COMPLETED",
        "target_trade_date": date,
        "trigger_id": trigger_id,
        "started_at": started["started_at"],
        "finished_at": attempt.get("finished_at"),
        "result": result_summary,
        "attempt": attempt,
        **FLAGS,
    })
    if read_budget:
        read_budget.check()
    raw = json.dumps(terminal, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    relative = str(_dispatch_path(store, date, trigger_id).relative_to(store.root))
    store._io.write_bytes(relative, raw, require_absent=True)
    if read_budget:
        read_budget.check()
    readback = (read_budget.read_json(store, _dispatch_path(store, date, trigger_id))
                if read_budget else store._read(_dispatch_path(store, date, trigger_id)))
    if readback != terminal:
        raise ValueError("US_MAPPING_DISPATCH_TERMINAL_READBACK_FAILED")
    return terminal


def _attempt_execution_context(supplied: Mapping[str, Any], *, target: str, started_at: datetime,
                               finished_at: datetime, cutoff_policy: str) -> dict[str, Any]:
    return _execution_metadata(supplied, target=target,
        started_at=started_at, finished_at=finished_at,
        research_cutoff_policy=cutoff_policy)


def _result_from_dispatch(store: Any, date: str, receipt: Mapping[str, Any]) -> dict[str, Any]:
    result = receipt.get("result")
    if not isinstance(result, Mapping):
        raise ValueError("US_MAPPING_DISPATCH_RESULT_INVALID")
    if isinstance(result.get("run_id"), str):
        saved = _read_exact_run(store, date, result["run_id"], result.get("artifact_sha256"))
        attempt = receipt.get("attempt") if isinstance(receipt.get("attempt"), Mapping) else {}
        saved["latest_attempt"] = {
            "status": result.get("status"),
            "execution_status": result.get("execution_status"),
            "trigger_id": attempt.get("trigger_id"),
            "started_at": attempt.get("started_at"),
            "finished_at": attempt.get("finished_at"),
            "execution_context": deepcopy(attempt.get("execution_context")),
            "run_id": result.get("run_id"),
            "artifact_sha256": result.get("artifact_sha256"),
            "run_execution_context": deepcopy(saved.get("execution_context")),
            **FLAGS,
        }
        return saved
    full_dto = result.get("failure_dto")
    if isinstance(full_dto, Mapping):
        return deepcopy(dict(full_dto))
    # Tolerate older terminal receipts without the additive full DTO fields.
    return {
        "schema_version": DAILY_SCHEMA,
        "target_trade_date": date,
        "status": result.get("status", "CANNOT_CONFIRM"),
        "run_id": None,
        "generated_at": None,
        "us_session_date": None,
        "research_cutoff": result.get("research_cutoff"),
        "coverage": deepcopy(result.get("coverage") or {
            "reviewed_us_symbol_count": None, "matched_us_symbol_count": None,
            "matched_hk_relation_count": None, "configured_us_universe_count": None,
            "available_us_universe_count": None, "full_market_coverage": False}),
        "matches": [],
        "execution_status": result.get("execution_status"),
        "execution_context": deepcopy(result.get("execution_context")),
        "gaps": list(result.get("gaps") or ["US_MAPPING_OWNER_FAILURE_DTO_UNAVAILABLE"]),
        **FLAGS,
    }


def _promote_recovered_run(store: Any, date: str, recovered: Mapping[str, Any], *,
                           read_budget: _ReadBudget) -> None:
    """Repair latest for an orphaned committed run without ever moving it backwards."""
    read_budget.check()
    with store._io.kernel_lock(
            ".locks/us-mapping-products.v1.mutex",
            timeout=max(0.0, read_budget.deadline - time.monotonic())):
        current = _read_saved(store, date, read_budget=read_budget)
        if current is not None:
            if current.get("run_id") == recovered.get("run_id"):
                return
            current_generated = _aware_text(current.get("generated_at"))
            recovered_generated = _aware_text(recovered.get("generated_at"))
            if current_generated is None or recovered_generated is None:
                raise ValueError("US_MAPPING_RECOVERY_GENERATED_AT_INVALID")
            current_time = datetime.fromisoformat(current_generated).astimezone(timezone.utc)
            recovered_time = datetime.fromisoformat(recovered_generated).astimezone(timezone.utc)
            if current_time >= recovered_time:
                return
            if recovered.get("status") not in {"COMPLETED", "VALID_EMPTY", "PARTIAL"}:
                return
        pointer = {
            "schema_version": "v4.manager_research.us_mapping_daily_pointer.v1",
            "target_trade_date": date,
            "run_id": recovered["run_id"],
            "artifact_sha256": recovered["artifact_sha256"],
            **FLAGS,
        }
        raw = json.dumps(pointer, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
        read_budget.check()
        store._io.write_bytes(f"us_mapping_research/{date}/latest.json", raw)
        read_budget.check()
        readback = _read_saved(store, date, read_budget=read_budget)
        if (readback is None or readback.get("run_id") != recovered.get("run_id")
                or readback.get("artifact_sha256") != recovered.get("artifact_sha256")):
            raise ValueError("US_MAPPING_RECOVERY_POINTER_READBACK_FAILED")


def _safe_tree(value: Mapping[str, Any]) -> None:
    for key, expected in FLAGS.items():
        if value.get(key) is not expected:
            raise ValueError("US_MAPPING_SAFETY_INVALID")


def _read_reviewed() -> dict[str, Any]:
    raw = REVIEWED_PATH.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("US_MAPPING_REVIEWED_ARTIFACT_INVALID")
    unsigned = {key: item for key, item in value.items() if key != "artifact_sha256"}
    if (value.get("schema_version") != "v4.manager_research.us_mapping_reviewed.v1"
            or value.get("target_trade_date") != _TARGET_SEED
            or value.get("artifact_sha256") != sha256_json(unsigned)
            or not isinstance(value.get("cards"), list)):
        raise ValueError("US_MAPPING_REVIEWED_ARTIFACT_INTEGRITY_FAILED")
    _safe_tree(value)
    return value


def _read_saved(store: Any, date: str, *, read_budget: _ReadBudget | None = None) -> dict[str, Any] | None:
    path = store.root / "us_mapping_research" / date / "latest.json"
    pointer = read_budget.read_json(store, path) if read_budget else store._read(path)
    if pointer is None:
        return None
    if (pointer.get("schema_version") != "v4.manager_research.us_mapping_daily_pointer.v1"
            or pointer.get("target_trade_date") != date
            or not isinstance(pointer.get("run_id"), str)
            or not _SHA.fullmatch(str(pointer.get("artifact_sha256") or ""))):
        raise ValueError("US_MAPPING_DAILY_POINTER_INVALID")
    artifact_path = path.parent / "runs" / f"{pointer['run_id']}.json"
    artifact = (read_budget.read_json(store, artifact_path, run_artifact=True)
                if read_budget else store._read(artifact_path))
    if artifact is None:
        raise ValueError("US_MAPPING_DAILY_ARTIFACT_MISSING")
    unsigned = {key: item for key, item in artifact.items() if key != "artifact_sha256"}
    if (artifact.get("schema_version") != DAILY_SCHEMA
            or artifact.get("target_trade_date") != date
            or artifact.get("run_id") != pointer["run_id"]
            or artifact.get("artifact_sha256") != pointer["artifact_sha256"]
            or sha256_json(unsigned) != pointer["artifact_sha256"]):
        raise ValueError("US_MAPPING_DAILY_ARTIFACT_INTEGRITY_FAILED")
    _safe_tree(artifact)
    return artifact


def read_workspace_mapping(service: Any, target_trade_date: str) -> dict[str, Any]:
    date = strict_trade_date(target_trade_date)
    try:
        daily = _read_saved(service.store, date)
    except (OSError, ValueError, KeyError, TypeError):
        daily = None
        read_status = "FAILED"
    else:
        read_status = "NOT_RUN"
    if daily is None:
        daily = {
            "schema_version": DAILY_SCHEMA,
            "status": read_status,
            "target_trade_date": date,
            "run_id": None,
            "generated_at": None,
            "us_session_date": None,
            "research_cutoff": None,
            "coverage": {
                "reviewed_us_symbol_count": None,
                "matched_us_symbol_count": None,
                "matched_hk_relation_count": None,
                "configured_us_universe_count": None,
                "available_us_universe_count": None,
                "full_market_coverage": False,
            },
            "matches": [],
            "gaps": ["DAILY_MAPPING_NOT_MATERIALIZED" if read_status == "NOT_RUN" else "DAILY_MAPPING_READBACK_INVALID"],
            "source_identity": None,
            "input_identity": None,
            **FLAGS,
        }
    try:
        latest_attempt = _latest_dispatch_attempt(service.store, date)
    except (OSError, ValueError, KeyError, TypeError):
        latest_attempt = {
            "status": "CANNOT_CONFIRM",
            "execution_status": "US_MAPPING_DISPATCH_READBACK_INVALID",
            "run_id": None,
            "artifact_sha256": None,
            "gaps": ["US_MAPPING_DISPATCH_READBACK_INVALID"],
            **FLAGS,
        }
    if latest_attempt is not None:
        daily["latest_attempt"] = latest_attempt
        if daily.get("status") == "NOT_RUN":
            attempt_result = latest_attempt
            daily.update({
                "status": attempt_result.get("status", "CANNOT_CONFIRM"),
                "run_id": attempt_result.get("run_id"),
                "generated_at": None,
                "research_cutoff": attempt_result.get("research_cutoff"),
                "coverage": deepcopy(attempt_result.get("coverage") or daily["coverage"]),
                "matches": [],
                "gaps": list(attempt_result.get("gaps") or []),
                "execution_context": deepcopy(attempt_result.get("execution_context")),
                "execution_status": attempt_result.get("execution_status"),
            })
        pending_state = latest_attempt.get('state') in {'RUNNING', 'PUBLISHING'}
        pending_matches_saved_run = bool(
            daily.get('run_id')
            and ((latest_attempt.get('run_id') == daily.get('run_id')
                  and latest_attempt.get('artifact_sha256') == daily.get('artifact_sha256'))
                 or ((daily.get('execution_context') or {}).get('trigger_id')
                     == latest_attempt.get('trigger_id'))))
        if pending_state and pending_matches_saved_run:
            daily['saved_product_status'] = daily.get('status')
            daily['saved_product_run_readback_status'] = 'VERIFIED'
            daily['saved_product_coverage'] = deepcopy(daily.get('coverage'))
            daily['saved_product_matches'] = deepcopy(daily.get('matches') or [])
            daily['status'] = 'CANNOT_CONFIRM'
            daily['execution_status'] = latest_attempt.get('execution_status')
            daily['coverage'] = {
                'reviewed_us_symbol_count': None, 'matched_us_symbol_count': None,
                'matched_hk_relation_count': None, 'configured_us_universe_count': None,
                'available_us_universe_count': None, 'full_market_coverage': False,
            }
            daily['matches'] = []
            daily['gaps'] = sorted(set([*(daily.get('gaps') or []),
                'US_MAPPING_OWNER_ATTEMPT_NOT_TERMINAL']))
    pending_product_attempt = (isinstance(daily.get('latest_attempt'), Mapping)
        and daily['latest_attempt'].get('state') in {'RUNNING', 'PUBLISHING'}
        and daily.get('saved_product_status') is not None)
    daily["run_readback"] = {
        "status": "CANNOT_CONFIRM" if pending_product_attempt else
            "VERIFIED" if daily.get("run_id") and daily.get("artifact_sha256") else "CANNOT_CONFIRM",
        "artifact_status": "VERIFIED" if pending_product_attempt else None,
        "target_trade_date": date,
        "run_id": daily.get("run_id"),
        "artifact_sha256": daily.get("artifact_sha256"),
        "owner": _OWNER,
        "read_at": datetime.now(HK).isoformat(timespec="microseconds"),
    }
    if date == _TARGET_SEED:
        try:
            reviewed = _read_reviewed()
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            reviewed = {
                "schema_version": "v4.manager_research.us_mapping_reviewed.v1",
                "target_trade_date": date,
                "status": "CANNOT_CONFIRM",
                "reviewed_at": None,
                "cards": [],
                "gaps": ["REVIEWED_US_HK_RELATION_ARTIFACT_INVALID"],
                **FLAGS,
            }
    else:
        reviewed = None
    return {
        "schema_version": SCHEMA,
        "target_trade_date": date,
        "daily_run": daily,
        "reviewed_research": reviewed,
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _relation_index() -> dict[str, list[dict[str, Any]]]:
    reviewed = _read_reviewed()
    out: dict[str, list[dict[str, Any]]] = {}
    for card in reviewed["cards"]:
        if not isinstance(card, Mapping):
            continue
        for symbol in card.get("daily_match_symbols", []):
            if isinstance(symbol, str) and re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", symbol):
                out.setdefault(symbol, []).append(dict(card))
    return out


def _relation_availability_details(reviewed: Mapping[str, Any]) -> tuple[
        datetime | None, str | None, dict[str, Any] | None]:
    """Return the release-pinned system availability and its source identities.

    The report's ``reviewed_at`` is a retrospective calendar date. It cannot
    establish when the rows became available inside this application. Both
    daily and current-workspace joins therefore require the separately pinned
    deployment registry.
    """
    try:
        raw = RELATION_REGISTRY_PATH.read_bytes()
        registry = json.loads(raw)
        if not isinstance(registry, Mapping):
            return None, "US_HK_RELATION_AVAILABILITY_UNVERIFIED", None
        unsigned = {key: item for key, item in registry.items() if key != "artifact_sha256"}
        seed_sha = hashlib.sha256(REVIEWED_PATH.read_bytes()).hexdigest()
        availability = timestamp(registry.get("available_at"))
        if (not isinstance(registry, Mapping)
                or registry.get("schema_version") != "v4.manager_research.us_mapping_relation_registry.v1"
                or registry.get("artifact_sha256") != sha256_json(unsigned)
                or registry.get("source_seed_sha256") != seed_sha
                or registry.get("source_report_sha256") != (reviewed.get("report") or {}).get("sha256")
                or not availability
                or registry.get("availability_basis") != "V4_RELEASE_PUBLICATION"
                or not isinstance(registry.get("release_id"), str)
                or not registry.get("release_id")
                or not _SHA.fullmatch(str(registry.get("release_manifest_sha256") or ""))
                or not _SHA.fullmatch(str(registry.get("deployment_receipt_sha256") or ""))):
            return None, "US_HK_RELATION_AVAILABILITY_UNVERIFIED", None
        return availability, None, {
            "registry_file_sha256": hashlib.sha256(raw).hexdigest(),
            "registry_artifact_sha256": registry["artifact_sha256"],
            "registry_schema_version": registry["schema_version"],
            "availability_basis": registry["availability_basis"],
            "availability_scope": registry["availability_scope"],
            "release_id": registry["release_id"],
            "release_manifest_sha256": registry["release_manifest_sha256"],
            "deployment_receipt_sha256": registry["deployment_receipt_sha256"],
            "available_at": availability.isoformat(),
            "seed_file_sha256": seed_sha,
            "source_report_sha256": registry["source_report_sha256"],
        }
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None, "US_HK_RELATION_AVAILABILITY_UNVERIFIED", None


def _relation_available_at(reviewed: Mapping[str, Any]) -> tuple[datetime | None, str | None]:
    availability, gap, _details = _relation_availability_details(reviewed)
    return availability, gap


def _reviewed_seed_relations(target_date: str, cutoff: datetime) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    """Project only the immutable reviewed seed rows whose release was available by cutoff."""
    try:
        reviewed = _read_reviewed()
        available_at, gap, availability = _relation_availability_details(reviewed)
        if gap or available_at is None or availability is None:
            return [], {}, [gap or "US_HK_RELATION_AVAILABILITY_UNVERIFIED"]
        if available_at > cutoff:
            return [], availability, ["US_HK_RELATION_NOT_AVAILABLE_AT_RESEARCH_CUTOFF"]
        seed_file_sha = str(availability["seed_file_sha256"])
        seed_artifact_sha = str(reviewed["artifact_sha256"])
        timing = ("RETROSPECTIVE_AFTER_TARGET_DATE"
                  if available_at.date().strftime("%Y%m%d") > target_date else "AVAILABLE_BY_TARGET_DATE")
        relations: list[dict[str, Any]] = []
        for raw_card in reviewed.get("cards", []):
            if not isinstance(raw_card, Mapping):
                continue
            card = dict(raw_card)
            if card.get("relationship_type") not in _DAILY_RELATION_TYPES:
                continue
            symbols = card.get("daily_match_symbols")
            if not isinstance(symbols, list):
                continue
            for raw_symbol in symbols:
                if not isinstance(raw_symbol, str) or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", raw_symbol):
                    continue
                sources = card.get("official_sources")
                if not isinstance(sources, list):
                    sources = []
                provenance = {
                    "relation_source": "RELEASE_PINNED_REVIEWED_SEED",
                    "reviewed_relation_artifact_sha256": seed_artifact_sha,
                    "reviewed_seed_file_sha256": seed_file_sha,
                    **availability,
                }
                relations.append({
                    "us_symbol": raw_symbol,
                    "hk_symbol": card.get("hk_symbol"),
                    "hk_code": card.get("hk_code"),
                    "hk_name": card.get("hk_name"),
                    "relationship_type": card.get("relationship_type"),
                    "direction": card.get("direction") or "NOT_STATED_IN_REVIEWED_CARD",
                    "reason": card.get("reason"),
                    "maturity": card.get("maturity"),
                    "limitations": deepcopy(card.get("limitations") or []),
                    "published_at": card.get("published_at"),
                    "sources": deepcopy(sources),
                    "official_sources": deepcopy(sources),
                    "relation_source": "RELEASE_PINNED_REVIEWED_SEED",
                    "evidence_review_status": "RELEASE_PINNED_REVIEWED_RESEARCH",
                    "evidence_timing": timing,
                    "available_at": available_at.isoformat(),
                    "target_date_eligibility": "CANNOT_CONFIRM",
                    "provenance": provenance,
                    **FLAGS,
                })
        return relations, availability, []
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return [], {}, ["US_HK_RELATION_AVAILABILITY_UNVERIFIED"]


def _current_relation_review(evidence_raw: bytes, evidence: Mapping[str, Any],
                             cards: list[Mapping[str, Any]],
                             assessments: list[Mapping[str, Any]]) -> tuple[dict[str, Any], str]:
    """Validate the independent semantic review against exact artifact and relation identities."""
    raw = CURRENT_RELATION_REVIEW_PATH.read_bytes()
    receipt_sha = hashlib.sha256(raw).hexdigest()
    if receipt_sha != CURRENT_RELATION_REVIEW_RECEIPT_SHA256:
        raise ValueError("US_RELATION_REVIEW_RECEIPT_SHA256_MISMATCH")
    receipt = json.loads(raw)
    if not isinstance(receipt, Mapping):
        raise ValueError("US_RELATION_REVIEW_RECEIPT_INVALID")
    artifact_version = evidence.get("schema_version")
    expected_review_version = {
        "v4.manager_research.us_mapping_relation_evidence.v1":
            "v4.manager_research.us_mapping_relation_evidence_review.v1",
        "v4.manager_research.us_mapping_relation_evidence.v2":
            "v4.manager_research.us_mapping_relation_evidence_review.v2",
    }.get(artifact_version)
    if (expected_review_version is None
            or receipt.get("schema_version") != expected_review_version
            or receipt.get("status") != "PASS"
            or receipt.get("reviewer_identity") != "/root/us_mapping_completion_review"
            or not isinstance(receipt.get("reviewed_scope"), str) or not receipt.get("reviewed_scope")
            or receipt.get("evidence_path") != "v4/manager_research/us_mapping_relation_evidence_20261011.json"
            or receipt.get("evidence_file_sha256") != hashlib.sha256(evidence_raw).hexdigest()
            or receipt.get("declared_artifact_sha256") != evidence.get("artifact_sha256")
            or receipt.get("recomputed_artifact_sha256") != evidence.get("artifact_sha256")
            or receipt.get("http_body_rehash_status") != "CANNOT_CONFIRM"
            or not isinstance(receipt.get("limitations"), list)
            or not isinstance(receipt.get("CANNOT_CONFIRM"), list)):
        raise ValueError("US_RELATION_REVIEW_RECEIPT_BINDING_INVALID")
    for key, expected in FLAGS.items():
        if receipt.get("safety", {}).get(key) is not expected:
            raise ValueError("US_RELATION_REVIEW_RECEIPT_SAFETY_INVALID")
    reviewed_at = timestamp(receipt.get("reviewed_at"))
    if reviewed_at is None:
        raise ValueError("US_RELATION_REVIEW_RECEIPT_TIME_INVALID")
    captured_times = [
        timestamp(item.get("available_at"))
        for item in [*cards, *assessments]
        if isinstance(item, Mapping)
    ]
    if any(value is None for value in captured_times) or any(value > reviewed_at for value in captured_times):
        raise ValueError("US_RELATION_REVIEW_RECEIPT_TIME_BEFORE_EVIDENCE")
    expected_pairs = {
        (card.get("us_symbol"), card.get("hk_symbol"), card.get("relationship_type"), card.get("direction"))
        for card in cards
    }
    raw_pairs = receipt.get("reviewed_pairs")
    if not isinstance(raw_pairs, list) or not raw_pairs:
        raise ValueError("US_RELATION_REVIEW_RECEIPT_PAIRS_INVALID")
    reviewed_pairs = set()
    for pair in raw_pairs:
        if not isinstance(pair, Mapping):
            raise ValueError("US_RELATION_REVIEW_RECEIPT_PAIRS_INVALID")
        reviewed_pairs.add((pair.get("us_symbol"), pair.get("hk_symbol"),
                            pair.get("relationship_type"), pair.get("direction")))
    if len(reviewed_pairs) != len(raw_pairs) or reviewed_pairs != expected_pairs:
        raise ValueError("US_RELATION_REVIEW_RECEIPT_PAIRS_MISMATCH")
    expected_assessments = {
        (assessment.get("us_symbol"), assessment.get("candidate_hk_code"),
         assessment.get("status"), assessment.get("conclusion"), sha256_json(assessment))
        for assessment in assessments
    }
    raw_assessments = receipt.get("reviewed_symbol_assessments", [])
    if assessments and not isinstance(raw_assessments, list):
        raise ValueError("US_RELATION_REVIEW_RECEIPT_ASSESSMENTS_INVALID")
    reviewed_assessments = set()
    for assessment in raw_assessments if isinstance(raw_assessments, list) else []:
        if not isinstance(assessment, Mapping):
            raise ValueError("US_RELATION_REVIEW_RECEIPT_ASSESSMENTS_INVALID")
        reviewed_assessments.add((assessment.get("us_symbol"), assessment.get("candidate_hk_code"),
                                  assessment.get("status"), assessment.get("conclusion"),
                                  assessment.get("assessment_sha256")))
    if (len(reviewed_assessments) != len(raw_assessments if isinstance(raw_assessments, list) else [])
            or reviewed_assessments != expected_assessments):
        raise ValueError("US_RELATION_REVIEW_RECEIPT_ASSESSMENTS_MISMATCH")
    # Bind issuer identities separately when a relation card does not itself
    # carry an identity-role source or an explicit exchange:ticker statement.
    # Older v1 receipts use one AMD object; v2 may use a list or a symbol-keyed
    # mapping. The independent review receipt, rather than a relation excerpt,
    # supplies the identity claim and its retrieval/capture provenance.
    raw_identity_evidence = receipt.get("us_symbol_identity_evidence")
    if isinstance(raw_identity_evidence, list):
        identity_entries = raw_identity_evidence
    elif isinstance(raw_identity_evidence, Mapping):
        if "us_symbol" in raw_identity_evidence:
            identity_entries = [raw_identity_evidence]
        else:
            identity_entries = [
                {"us_symbol": symbol, **deepcopy(dict(value))}
                for symbol, value in raw_identity_evidence.items()
                if isinstance(value, Mapping)
            ]
    else:
        identity_entries = []
    identity_by_symbol: dict[str, dict[str, Any]] = {}
    for identity in identity_entries:
        if not isinstance(identity, Mapping):
            raise ValueError("US_RELATION_REVIEW_RECEIPT_IDENTITIES_INVALID")
        symbol = identity.get("us_symbol")
        body_sha = identity.get("source_body_sha256")
        body_sha_status = identity.get("source_body_sha256_status")
        retrieved_at = timestamp(identity.get("retrieved_at"))
        if (not isinstance(symbol, str) or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", symbol)
                or identity.get("identity_status") != "VERIFIED"
                or not isinstance(identity.get("issuer"), str) or not identity.get("issuer")
                or not isinstance(identity.get("exchange"), str) or not identity.get("exchange")
                or not str(identity.get("url") or "").startswith("https://")
                or not isinstance(identity.get("source_locator"), str) or not identity.get("source_locator")
                or retrieved_at is None or retrieved_at > reviewed_at
                or (identity.get("source_capture_status") is not None
                    and (not isinstance(identity.get("source_capture_status"), str)
                         or not identity.get("source_capture_status")))
                or (body_sha is None and body_sha_status != "CANNOT_CONFIRM")
                or (body_sha is not None and (not isinstance(body_sha, str)
                    or not _SHA.fullmatch(body_sha)
                    or body_sha_status != "VERIFIED_SHA256_HTTP_RESPONSE_BODY_BYTES"))
                or symbol in identity_by_symbol):
            raise ValueError("US_RELATION_REVIEW_RECEIPT_IDENTITY_INVALID")
        identity_by_symbol[symbol] = deepcopy(dict(identity))

    identity_needed: set[str] = set()
    for card in cards:
        symbol = str(card.get("us_symbol") or "")
        has_identity_role = any(
            isinstance(source, Mapping) and source.get("role") == "US_SYMBOL_IDENTITY"
            for source in card.get("sources", [])
        )
        explicit_exchange_ticker = any(
            isinstance(source, Mapping)
            and re.search(rf"\b(?:NASDAQ|NYSE)\s*:\s*{re.escape(symbol)}\b",
                          str(source.get("excerpt") or ""), re.IGNORECASE)
            for source in card.get("sources", [])
        )
        if not has_identity_role and not explicit_exchange_ticker:
            identity_needed.add(symbol)
    if not identity_needed.issubset(identity_by_symbol):
        raise ValueError("US_RELATION_REVIEW_RECEIPT_IDENTITIES_MISSING")
    return {
        "receipt_sha256": receipt_sha,
        "reviewer_identity": receipt["reviewer_identity"],
        "reviewed_at": reviewed_at.isoformat(),
        "status": receipt["status"],
        "http_body_rehash_status": receipt["http_body_rehash_status"],
        "limitations": deepcopy(receipt["limitations"]),
        "cannot_confirm": deepcopy(receipt["CANNOT_CONFIRM"]),
        "us_symbol_identity_evidence": identity_by_symbol,
        "reviewed_symbol_assessments": deepcopy(raw_assessments),
    }, "INDEPENDENT_SEMANTIC_REVIEW_PASS_BODY_REHASH_CANNOT_CONFIRM"


def attach_current_relation_evidence(us_market: Mapping[str, Any]) -> dict[str, Any]:
    """Attach source-hashed relations only to the exact current workspace bridge.

    This is a read-only, retrospective research overlay. It never changes the
    saved target-date product, BUY state, or target-date eligibility.
    """
    result = deepcopy(dict(us_market))
    rows = result.get("symbol_assessments")
    if not isinstance(rows, list):
        result["relation_evidence"] = {
            "status": "CANNOT_CONFIRM", "artifact_sha256": None, "gaps": ["US_SYMBOL_ASSESSMENTS_NOT_AVAILABLE"],
            "target_date_eligibility": "CANNOT_CONFIRM", **FLAGS,
        }
        return result
    cutoff = timestamp(result.get("research_cutoff"))
    target_date = strict_trade_date(str(result.get("target_trade_date") or ""))
    source_identity = result.get("source_identity")
    bridge_source_payload_sha = (
        source_identity.get("payload_sha256") if isinstance(source_identity, Mapping) else None
    )
    session = result.get("expected_us_session")
    if (cutoff is None or not isinstance(session, str)
            or not _SHA.fullmatch(str(bridge_source_payload_sha or ""))):
        reason = "US_RELATION_EVIDENCE_BRIDGE_IDENTITY_UNVERIFIED"
        result["relation_evidence"] = {
            "status": "CANNOT_CONFIRM", "artifact_sha256": None, "gaps": [reason],
            "target_date_eligibility": "CANNOT_CONFIRM", "current_bridge_session": session,
            "current_bridge_source_payload_sha256": None, **FLAGS,
        }
        for row in rows:
            if isinstance(row, dict):
                row["relation_assessment_status"] = "NOT_EVALUATED"
                row["relation_count"] = None
                row["relations"] = []
                row["relation_gaps"] = [reason]
        return result

    evidence: Mapping[str, Any] | None = None
    evidence_raw = b""
    parsed_cards: list[dict[str, Any]] = []
    parsed_symbol_assessments: list[dict[str, Any]] = []
    withheld_candidates: list[Any] = []
    current_artifact_error: str | None = None
    try:
        raw = CURRENT_RELATION_EVIDENCE_PATH.read_bytes()
        evidence_raw = raw
        evidence = json.loads(raw)
        if not isinstance(evidence, Mapping):
            raise ValueError("US_RELATION_EVIDENCE_ARTIFACT_INVALID")
        unsigned = {key: value for key, value in evidence.items() if key != "artifact_sha256"}
        cards = evidence.get("relations")
        raw_symbol_assessments = evidence.get("symbol_assessments", [])
        withheld_candidates = evidence.get("withheld_candidates", [])
        if (evidence.get("schema_version") not in {
                "v4.manager_research.us_mapping_relation_evidence.v1",
                "v4.manager_research.us_mapping_relation_evidence.v2",
            }
                or evidence.get("artifact_sha256") != sha256_json(unsigned)
                or not isinstance(cards, list)
                or not isinstance(raw_symbol_assessments, list)
                or not isinstance(withheld_candidates, list)
                or evidence.get("source_hash_algorithm") != "SHA256_HTTP_RESPONSE_BODY_BYTES"):
            raise ValueError("US_RELATION_EVIDENCE_ARTIFACT_INTEGRITY_FAILED")
        _safe_tree(evidence)
        for candidate in withheld_candidates:
            if (not isinstance(candidate, Mapping)
                    or not isinstance(candidate.get("company"), str) or not candidate.get("company")
                    or not isinstance(candidate.get("us_symbol"), str)
                    or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", candidate["us_symbol"])
                    or not isinstance(candidate.get("candidate_hk_code"), str)
                    or not re.fullmatch(r"\d{5}", candidate["candidate_hk_code"])
                    or candidate.get("status") != "CANNOT_CONFIRM"
                    or not isinstance(candidate.get("reason"), str) or not candidate.get("reason")):
                raise ValueError("US_RELATION_EVIDENCE_WITHHELD_CANDIDATE_INVALID")
        cutoff = timestamp(result.get("research_cutoff"))
        target_date = strict_trade_date(str(result.get("target_trade_date") or ""))
        source_identity = result.get("source_identity")
        bridge_source_payload_sha = (
            source_identity.get("payload_sha256") if isinstance(source_identity, Mapping) else None
        )
        session = result.get("expected_us_session")
        if (cutoff is None or not isinstance(session, str)
                or not _SHA.fullmatch(str(bridge_source_payload_sha or ""))):
            raise ValueError("US_RELATION_EVIDENCE_BRIDGE_IDENTITY_UNVERIFIED")
        parsed_cards = []
        for raw_card in cards:
            if not isinstance(raw_card, Mapping):
                raise ValueError("US_RELATION_EVIDENCE_CARD_INVALID")
            card = deepcopy(dict(raw_card))
            symbol = card.get("us_symbol")
            sources = card.get("sources")
            available_at = timestamp(card.get("available_at"))
            if (not isinstance(symbol, str) or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", symbol)
                    or not isinstance(card.get("relationship_type"), str)
                    or not _RELATION_TOKEN.fullmatch(card["relationship_type"])
                    or not isinstance(card.get("direction"), str)
                    or not _RELATION_TOKEN.fullmatch(card["direction"])
                    or not isinstance(card.get("hk_code"), str) or not re.fullmatch(r"\d{5}", card["hk_code"])
                    or card.get("hk_symbol") != "HK." + card["hk_code"]
                    or not isinstance(card.get("hk_name"), str) or not card.get("hk_name")
                    or not isinstance(card.get("reason"), str) or not card.get("reason")
                    or not isinstance(card.get("maturity"), str) or not card.get("maturity")
                    or not isinstance(card.get("limitations"), list) or not card["limitations"]
                    or available_at is None or not isinstance(sources, list) or len(sources) < 2):
                raise ValueError("US_RELATION_EVIDENCE_CARD_FIELDS_INVALID")
            source_roles = set()
            source_retrieval_times: list[datetime] = []
            for source in sources:
                if not isinstance(source, Mapping):
                    raise ValueError("US_RELATION_EVIDENCE_SOURCE_INVALID")
                role = source.get("role")
                url = source.get("url")
                source_body_sha = source.get("source_body_sha256")
                retrieved_at = timestamp(source.get("retrieved_at"))
                retrieval_started_at = timestamp(source.get("retrieval_started_at"))
                if (role not in {"RELATION", "HK_LISTING_IDENTITY", "US_SYMBOL_IDENTITY"}
                        or not isinstance(url, str) or not url.startswith("https://")
                        or not isinstance(source.get("title"), str) or not source.get("title")
                        or not isinstance(source.get("excerpt"), str) or not source.get("excerpt")
                        or not _SHA.fullmatch(str(source_body_sha or "")) or retrieved_at is None
                        or retrieval_started_at is None or retrieval_started_at > retrieved_at
                        or source.get("http_status") != 200
                        or (source.get("published_at") is not None
                            and not isinstance(source.get("published_at"), str))
                        or not isinstance(source.get("source_locator"), str)):
                    raise ValueError("US_RELATION_EVIDENCE_SOURCE_FIELDS_INVALID")
                source_roles.add(role)
                source_retrieval_times.append(retrieved_at)
            if not {"RELATION", "HK_LISTING_IDENTITY"}.issubset(source_roles):
                raise ValueError("US_RELATION_EVIDENCE_IDENTITY_BASIS_INCOMPLETE")
            if max(source_retrieval_times) != available_at:
                raise ValueError("US_RELATION_EVIDENCE_AVAILABILITY_NOT_BOUND_TO_SOURCE_RECEIPTS")
            parsed_cards.append(card)
        parsed_symbol_assessments = []
        seen_assessed_symbols: set[str] = set()
        for raw_assessment in raw_symbol_assessments:
            if not isinstance(raw_assessment, Mapping):
                raise ValueError("US_RELATION_SYMBOL_ASSESSMENT_INVALID")
            assessment = deepcopy(dict(raw_assessment))
            symbol = assessment.get("us_symbol")
            code = assessment.get("candidate_hk_code")
            sources = assessment.get("sources")
            available_at = timestamp(assessment.get("available_at"))
            if (not isinstance(symbol, str) or not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", symbol)
                    or symbol in seen_assessed_symbols
                    or not isinstance(code, str) or not re.fullmatch(r"\d{5}", code)
                    or assessment.get("candidate_hk_symbol") != "HK." + code
                    or assessment.get("status") != "ASSESSED_WITH_GAPS"
                    or assessment.get("conclusion") != "CANNOT_CONFIRM"
                    or not isinstance(assessment.get("assessment_scope"), str)
                    or not assessment.get("assessment_scope")
                    or not isinstance(assessment.get("reason"), str) or not assessment.get("reason")
                    or not isinstance(assessment.get("limitations"), list) or not assessment["limitations"]
                    or available_at is None or not isinstance(sources, list) or not sources):
                raise ValueError("US_RELATION_SYMBOL_ASSESSMENT_FIELDS_INVALID")
            source_retrieval_times: list[datetime] = []
            for source in sources:
                if not isinstance(source, Mapping):
                    raise ValueError("US_RELATION_SYMBOL_ASSESSMENT_SOURCE_INVALID")
                role = source.get("role")
                url = source.get("url")
                body_sha = source.get("source_body_sha256")
                hash_status = source.get("source_body_sha256_status")
                capture_status = source.get("source_capture_status")
                retrieved_at = timestamp(source.get("retrieved_at"))
                retrieval_started_at = timestamp(source.get("retrieval_started_at"))
                if (role not in {"RELATION", "HISTORICAL_RELATION_CONTEXT", "SOURCE_RETRIEVAL_ATTEMPT"}
                        or not isinstance(url, str) or not url.startswith("https://")
                        or not isinstance(source.get("title"), str) or not source.get("title")
                        or not isinstance(source.get("excerpt"), str) or not source.get("excerpt")
                        or not isinstance(source.get("source_locator"), str) or not source.get("source_locator")
                        or retrieved_at is None
                        or (retrieval_started_at is not None and retrieval_started_at > retrieved_at)):
                    raise ValueError("US_RELATION_SYMBOL_ASSESSMENT_SOURCE_FIELDS_INVALID")
                if body_sha is None:
                    if hash_status != "CANNOT_CONFIRM" or capture_status not in {
                            "WEB_EXTRACTED_CONTENT_BODY_NOT_CAPTURED",
                            "HTTP_429_NO_RESPONSE_BODY",
                            "WEB_EXTRACTED_WITHDRAWN_SOURCE_BODY_NOT_CAPTURED",
                        }:
                        raise ValueError("US_RELATION_SYMBOL_ASSESSMENT_SOURCE_HASH_STATUS_INVALID")
                    if capture_status == "HTTP_429_NO_RESPONSE_BODY" and source.get("http_status") != 429:
                        raise ValueError("US_RELATION_SYMBOL_ASSESSMENT_SOURCE_HTTP_STATUS_INVALID")
                    if capture_status != "HTTP_429_NO_RESPONSE_BODY" and source.get("http_status") is not None:
                        raise ValueError("US_RELATION_SYMBOL_ASSESSMENT_SOURCE_HTTP_STATUS_INVALID")
                elif (not _SHA.fullmatch(str(body_sha))
                        or hash_status != "VERIFIED_SHA256_HTTP_RESPONSE_BODY_BYTES"
                        or capture_status != "HTTP_RESPONSE_BODY_CAPTURED"
                        or source.get("http_status") != 200):
                    raise ValueError("US_RELATION_SYMBOL_ASSESSMENT_SOURCE_HASH_STATUS_INVALID")
                if retrieval_started_at is not None and source.get("http_status") not in {200, 429}:
                    raise ValueError("US_RELATION_SYMBOL_ASSESSMENT_SOURCE_HTTP_STATUS_INVALID")
                source_retrieval_times.append(retrieved_at)
            if max(source_retrieval_times) != available_at:
                raise ValueError("US_RELATION_SYMBOL_ASSESSMENT_AVAILABILITY_NOT_BOUND_TO_SOURCES")
            seen_assessed_symbols.add(symbol)
            parsed_symbol_assessments.append(assessment)
        if not parsed_cards and not parsed_symbol_assessments:
            raise ValueError("US_RELATION_EVIDENCE_HAS_NO_RELATIONS_OR_ASSESSMENTS")
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        reason = str(exc) if str(exc).startswith("US_RELATION_EVIDENCE_") else "US_RELATION_EVIDENCE_ARTIFACT_INVALID"
        current_artifact_error = reason
        evidence = None
        parsed_cards = []
        parsed_symbol_assessments = []
        withheld_candidates = []

    review_info: dict[str, Any] | None = None
    current_review_status: str | None = None
    review_error: str | None = None
    if evidence is not None:
        try:
            review_info, current_review_status = _current_relation_review(
                evidence_raw, evidence, parsed_cards, parsed_symbol_assessments,
            )
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            review_error = str(exc) if str(exc).startswith("US_RELATION_REVIEW_") else "US_RELATION_REVIEW_RECEIPT_INVALID"

    configured_symbols = {
        str(row.get("symbol") or "").upper() for row in rows if isinstance(row, Mapping)
    }
    seed_relations, seed_availability, seed_gaps = _reviewed_seed_relations(target_date, cutoff)
    seed_relations = [
        relation for relation in seed_relations if relation.get("us_symbol") in configured_symbols
    ]
    eligible_current: list[dict[str, Any]] = []
    post_cutoff_count = 0
    post_cutoff_review_count = 0
    review_pending_count = 0
    eligible_current_symbol_assessments: list[dict[str, Any]] = []
    post_cutoff_assessment_count = 0
    post_cutoff_assessment_review_count = 0
    assessment_review_pending_count = 0
    current_reviewed_at = timestamp(review_info.get("reviewed_at")) if review_info else None
    for card in parsed_cards:
        if str(card.get("us_symbol") or "").upper() not in configured_symbols:
            continue
        available_at = timestamp(card.get("available_at"))
        if available_at is None:
            current_artifact_error = "US_RELATION_EVIDENCE_CARD_FIELDS_INVALID"
            continue
        if available_at > cutoff:
            post_cutoff_count += 1
            continue
        if review_info is None or current_reviewed_at is None:
            review_pending_count += 1
            continue
        if current_reviewed_at > cutoff:
            post_cutoff_review_count += 1
            continue
        effective_available_at = max(available_at, current_reviewed_at)
        relation = deepcopy(card)
        relation["relation_source"] = "CURRENT_REVIEWED_RELATION_EVIDENCE"
        relation["source_captured_available_at"] = available_at.isoformat()
        relation["available_at"] = effective_available_at.isoformat()
        relation["reviewed_at"] = current_reviewed_at.isoformat()
        relation["evidence_timing"] = (
            "RETROSPECTIVE_AFTER_TARGET_DATE"
            if effective_available_at.date().strftime("%Y%m%d") > target_date
            else "AVAILABLE_BY_TARGET_DATE"
        )
        relation["evidence_review_status"] = current_review_status
        relation["reviewer_identity"] = review_info["reviewer_identity"]
        relation["review_receipt_sha256"] = review_info["receipt_sha256"]
        relation["http_body_rehash_status"] = review_info["http_body_rehash_status"]
        relation["review_limitations"] = deepcopy(review_info["limitations"])
        relation["target_date_eligibility"] = "CANNOT_CONFIRM"
        relation["provenance"] = {
            "relation_source": relation["relation_source"],
            "evidence_path": "v4/manager_research/us_mapping_relation_evidence_20261011.json",
            "evidence_file_sha256": hashlib.sha256(evidence_raw).hexdigest(),
            "evidence_artifact_sha256": evidence.get("artifact_sha256"),
            "review_receipt_sha256": review_info["receipt_sha256"],
            "reviewer_identity": review_info["reviewer_identity"],
            "reviewed_at": current_reviewed_at.isoformat(),
            "source_captured_available_at": available_at.isoformat(),
            "available_at": effective_available_at.isoformat(),
            "http_body_rehash_status": review_info["http_body_rehash_status"],
        }
        identity = review_info.get("us_symbol_identity_evidence", {}).get(card.get("us_symbol"))
        if identity:
            identity = deepcopy(identity)
            relation["reviewer_identity_evidence"] = identity
            identity_source = {
                "role": "US_SYMBOL_IDENTITY",
                "title": identity.get("title") or f"{identity['issuer']} official issuer identity source",
                "url": identity["url"],
                "published_at": identity.get("published_at"),
                "retrieved_at": identity["retrieved_at"],
                "source_locator": identity["source_locator"],
                "source_body_sha256": identity.get("source_body_sha256"),
                "source_body_sha256_status": identity["source_body_sha256_status"],
                "evidence_source": "INDEPENDENT_REVIEW_RECEIPT",
            }
            if identity.get("source_capture_status"):
                identity_source["source_capture_status"] = identity["source_capture_status"]
            relation["sources"] = [*deepcopy(card.get("sources", [])), identity_source]
        relation.update(FLAGS)
        eligible_current.append(relation)

    for assessment in parsed_symbol_assessments:
        if str(assessment.get("us_symbol") or "").upper() not in configured_symbols:
            continue
        captured_at = timestamp(assessment.get("available_at"))
        if captured_at is None:
            current_artifact_error = "US_RELATION_SYMBOL_ASSESSMENT_FIELDS_INVALID"
            continue
        if captured_at > cutoff:
            post_cutoff_assessment_count += 1
            continue
        if review_info is None or current_reviewed_at is None:
            assessment_review_pending_count += 1
            continue
        if current_reviewed_at > cutoff:
            post_cutoff_assessment_review_count += 1
            continue
        effective_available_at = max(captured_at, current_reviewed_at)
        reviewed_assessment = deepcopy(assessment)
        reviewed_assessment["relation_source"] = "CURRENT_REVIEWED_SYMBOL_ASSESSMENT"
        reviewed_assessment["source_captured_available_at"] = captured_at.isoformat()
        reviewed_assessment["available_at"] = effective_available_at.isoformat()
        reviewed_assessment["reviewed_at"] = current_reviewed_at.isoformat()
        reviewed_assessment["evidence_timing"] = (
            "RETROSPECTIVE_AFTER_TARGET_DATE"
            if effective_available_at.date().strftime("%Y%m%d") > target_date
            else "AVAILABLE_BY_TARGET_DATE"
        )
        reviewed_assessment["evidence_review_status"] = current_review_status
        reviewed_assessment["reviewer_identity"] = review_info["reviewer_identity"]
        reviewed_assessment["review_receipt_sha256"] = review_info["receipt_sha256"]
        reviewed_assessment["assessment_sha256"] = sha256_json(assessment)
        reviewed_assessment["target_date_eligibility"] = "CANNOT_CONFIRM"
        reviewed_assessment["provenance"] = {
            "relation_source": reviewed_assessment["relation_source"],
            "evidence_path": "v4/manager_research/us_mapping_relation_evidence_20261011.json",
            "evidence_file_sha256": hashlib.sha256(evidence_raw).hexdigest(),
            "evidence_artifact_sha256": evidence.get("artifact_sha256"),
            "assessment_sha256": reviewed_assessment["assessment_sha256"],
            "review_receipt_sha256": review_info["receipt_sha256"],
            "reviewer_identity": review_info["reviewer_identity"],
            "reviewed_at": current_reviewed_at.isoformat(),
            "source_captured_available_at": captured_at.isoformat(),
            "available_at": effective_available_at.isoformat(),
        }
        reviewed_assessment.update(FLAGS)
        eligible_current_symbol_assessments.append(reviewed_assessment)

    # The old four relations were available under the separate release registry.
    # Dedupe identical typed/directed relations while keeping both provenance records.
    eligible_cards: list[dict[str, Any]] = []
    by_key: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for relation in [*seed_relations, *eligible_current]:
        key = (
            str(relation.get("us_symbol") or ""), str(relation.get("hk_symbol") or ""),
            str(relation.get("relationship_type") or ""), str(relation.get("direction") or ""),
        )
        existing = by_key.get(key)
        new_provenance = deepcopy(relation.get("provenance") or {})
        if existing is None:
            relation["evidence_provenance"] = [new_provenance]
            by_key[key] = relation
            eligible_cards.append(relation)
            continue
        provenance_rows = existing.get("evidence_provenance")
        if isinstance(provenance_rows, list) and new_provenance not in provenance_rows:
            provenance_rows.append(new_provenance)
        source_rows = existing.get("sources") if isinstance(existing.get("sources"), list) else []
        seen_source_ids = {
            (item.get("url"), item.get("title")) for item in source_rows if isinstance(item, Mapping)
        }
        for source in relation.get("sources", []) if isinstance(relation.get("sources"), list) else []:
            if isinstance(source, Mapping) and (source.get("url"), source.get("title")) not in seen_source_ids:
                source_rows.append(deepcopy(dict(source)))
                seen_source_ids.add((source.get("url"), source.get("title")))
        existing["sources"] = source_rows
        existing["evidence_review_status"] = "MULTIPLE_REVIEWED_EVIDENCE_SOURCES"

    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for card in eligible_cards:
        by_symbol.setdefault(str(card["us_symbol"]), []).append(card)
    assessed_gap_by_symbol = {
        str(assessment["us_symbol"]): assessment
        for assessment in eligible_current_symbol_assessments
    }
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper()
        linked = by_symbol.get(symbol, [])
        row["relations"] = deepcopy(linked)
        row["relation_count"] = len(linked) if linked else None
        if linked:
            sources = {relation.get("relation_source") for relation in linked}
            if sources == {"RELEASE_PINNED_REVIEWED_SEED"}:
                row["relation_assessment_status"] = "RELEASE_PINNED_REVIEWED_RELATIONS_AVAILABLE"
            elif sources == {"CURRENT_REVIEWED_RELATION_EVIDENCE"}:
                row["relation_assessment_status"] = "INDEPENDENTLY_REVIEWED_RELATIONS_AVAILABLE"
            else:
                row["relation_assessment_status"] = "MULTI_SOURCE_REVIEWED_RELATIONS_AVAILABLE"
            row["relation_gaps"] = []
        elif row.get("instrument_classification") == "ETF_PROXY":
            row["relation_assessment_status"] = "ETF_THEME_PROXY_ONLY"
            row["relation_gaps"] = ["ETF_PROXY_IS_NOT_AN_ISSUER_RELATION"]
        elif symbol in assessed_gap_by_symbol:
            row["relation_assessment_status"] = "ASSESSED_WITH_GAPS"
            row["relation_assessment_evidence"] = deepcopy(assessed_gap_by_symbol[symbol])
            row["relation_gaps"] = [str(assessed_gap_by_symbol[symbol]["reason"])]
        elif any(str(assessment.get("us_symbol") or "") == symbol for assessment in parsed_symbol_assessments):
            row["relation_assessment_status"] = "ASSESSED_WITH_GAPS_NOT_AVAILABLE_BY_CUTOFF"
            row["relation_gaps"] = ["SYMBOL_ASSESSMENT_OR_REVIEW_NOT_AVAILABLE_BY_CUTOFF"]
        else:
            row["relation_assessment_status"] = "NOT_EVALUATED"
            row["relation_gaps"] = ["RELATION_SEARCH_NOT_COMPLETE_FOR_SYMBOL"]
            pending_symbols = {str(card.get("us_symbol")) for card in parsed_cards}
            if symbol in pending_symbols and (post_cutoff_count or post_cutoff_review_count or review_pending_count):
                row["relation_gaps"] = ["CURRENT_RELATION_EVIDENCE_NOT_AVAILABLE_BY_CUTOFF"]
    current_evidence_selected = bool(eligible_current or eligible_current_symbol_assessments)
    artifact_sha = (
        str(evidence.get("artifact_sha256"))
        if evidence is not None and current_evidence_selected else None
    )
    gaps = ["RELATION_EVIDENCE_COVERAGE_NOT_COMPLETE"]
    if post_cutoff_count:
        gaps.append("RELATION_EVIDENCE_AFTER_CURRENT_CUTOFF")
    if post_cutoff_review_count:
        gaps.append("RELATION_REVIEW_AFTER_CURRENT_CUTOFF")
    if review_pending_count:
        gaps.append("RELATION_EVIDENCE_REVIEW_PENDING")
    if post_cutoff_assessment_count:
        gaps.append("SYMBOL_ASSESSMENT_AFTER_CURRENT_CUTOFF")
    if post_cutoff_assessment_review_count:
        gaps.append("SYMBOL_ASSESSMENT_REVIEW_AFTER_CURRENT_CUTOFF")
    if assessment_review_pending_count:
        gaps.append("SYMBOL_ASSESSMENT_REVIEW_PENDING")
    if review_error:
        gaps.append("US_RELATION_REVIEW_RECEIPT_INVALID")
    if current_artifact_error:
        gaps.append(current_artifact_error)
    gaps.extend(seed_gaps)

    # A saved workspace identity represents source bindings and the actual
    # cutoff decisions. It must not include the read clock itself: when the
    # source bytes, available_at results, counts, and gaps are unchanged, a
    # later dynamic replay is the same material identity. Crossing a real
    # source/review availability boundary changes these hashed results.
    identity_inputs = {
        "schema": "v4.manager_research.current_relation_assessment_identity.v2",
        "target_trade_date": target_date,
        "current_bridge_session": session,
        "current_bridge_source_payload_sha256": bridge_source_payload_sha,
        "configured_us_symbols": sorted(configured_symbols),
        "current_relation_source": {
            "evidence_file_sha256": hashlib.sha256(evidence_raw).hexdigest() if evidence_raw else None,
            "evidence_artifact_sha256": evidence.get("artifact_sha256") if evidence is not None else None,
            "review_receipt_sha256": review_info.get("receipt_sha256") if review_info else None,
            "reviewed_at": review_info.get("reviewed_at") if review_info else None,
        },
        "seed_source": deepcopy(dict(seed_availability)) if isinstance(seed_availability, Mapping) else None,
        "eligibility_results": {
            "eligible_relations": eligible_cards,
            "eligible_symbol_assessments": eligible_current_symbol_assessments,
            "post_cutoff_counts": {
                "relations": post_cutoff_count,
                "relation_reviews": post_cutoff_review_count,
                "review_pending_relations": review_pending_count,
                "symbol_assessments": post_cutoff_assessment_count,
                "symbol_assessment_reviews": post_cutoff_assessment_review_count,
                "review_pending_symbol_assessments": assessment_review_pending_count,
            },
            "current_review_status": current_review_status,
            "withheld_candidate_count": len(withheld_candidates),
            "gaps": sorted(set(gaps)),
        },
    }
    overlay_identity = digest(identity_inputs)
    relation_source_artifacts = []
    if seed_availability and seed_relations:
        relation_source_artifacts.append({
            "relation_source": "RELEASE_PINNED_REVIEWED_SEED",
            "reviewed_relation_artifact_sha256": seed_relations[0]["provenance"]["reviewed_relation_artifact_sha256"],
            "reviewed_seed_file_sha256": seed_availability["seed_file_sha256"],
            "availability_registry_file_sha256": seed_availability["registry_file_sha256"],
            "availability_registry_artifact_sha256": seed_availability["registry_artifact_sha256"],
            "release_id": seed_availability["release_id"],
            "available_at": seed_availability["available_at"],
            "eligible_relation_count": len(seed_relations),
        })
    if evidence is not None and current_evidence_selected:
        relation_source_artifacts.append({
            "relation_source": "CURRENT_REVIEWED_RELATION_EVIDENCE",
            "evidence_path": "v4/manager_research/us_mapping_relation_evidence_20261011.json",
            "evidence_file_sha256": hashlib.sha256(evidence_raw).hexdigest(),
            "evidence_artifact_sha256": artifact_sha,
            "review_receipt_sha256": review_info.get("receipt_sha256") if review_info else None,
            "reviewer_identity": review_info.get("reviewer_identity") if review_info else None,
            "reviewed_at": review_info.get("reviewed_at") if review_info else None,
            "http_body_rehash_status": review_info.get("http_body_rehash_status") if review_info else "CANNOT_CONFIRM",
            "eligible_relation_count": len(eligible_current),
            "source_card_count": len(parsed_cards),
            "symbol_assessment_count": len(parsed_symbol_assessments),
            "eligible_symbol_assessment_count": len(eligible_current_symbol_assessments),
        })
    explicitly_assessed_equities = {
        str(row.get("symbol") or "").upper()
        for row in rows if isinstance(row, Mapping)
        and row.get("instrument_classification") == "EQUITY_PROXY"
        and (by_symbol.get(str(row.get("symbol") or "").upper())
             or str(row.get("relation_assessment_status") or "").startswith("ASSESSED_WITH_GAPS"))
    }
    configured_equities = {
        str(row.get("symbol") or "").upper()
        for row in rows if isinstance(row, Mapping)
        and row.get("instrument_classification") == "EQUITY_PROXY"
    }
    result["relation_evidence"] = {
        "status": "PARTIAL_SOURCE_EVIDENCE_COVERAGE" if eligible_cards else "NOT_EVALUATED",
        "artifact_sha256": artifact_sha,
        "source_card_count": len(parsed_cards),
        "eligible_relation_count": len(eligible_cards),
        "post_cutoff_relation_count": post_cutoff_count,
        "post_cutoff_review_count": post_cutoff_review_count,
        "review_pending_relation_count": review_pending_count,
        "symbol_assessment_count": len(parsed_symbol_assessments),
        "eligible_symbol_assessment_count": len(eligible_current_symbol_assessments),
        "post_cutoff_symbol_assessment_count": post_cutoff_assessment_count,
        "post_cutoff_symbol_assessment_review_count": post_cutoff_assessment_review_count,
        "review_pending_symbol_assessment_count": assessment_review_pending_count,
        "reviewed_seed_relation_count": len(seed_relations),
        "current_reviewed_relation_count": len(eligible_current),
        "withheld_candidate_count": len(withheld_candidates),
        "withheld_candidates": deepcopy(withheld_candidates),
        "mapped_us_symbol_count": len(by_symbol),
        "configured_us_symbol_count": len(rows),
        "configured_equity_symbol_count": len(configured_equities),
        "explicitly_assessed_equity_symbol_count": len(explicitly_assessed_equities),
        "unassessed_equity_symbols": sorted(configured_equities - explicitly_assessed_equities),
        "equity_assessment_coverage_complete": configured_equities == explicitly_assessed_equities,
        "coverage_complete": False,
        "relation_source_artifacts": relation_source_artifacts,
        "review_receipt": deepcopy(review_info) if review_info else None,
        "source_body_rehash_status": review_info.get("http_body_rehash_status") if review_info else "CANNOT_CONFIRM",
        "assessment_identity": overlay_identity,
        "current_bridge_session": session,
        "current_bridge_source_payload_sha256": bridge_source_payload_sha,
        "target_date_eligibility": "CANNOT_CONFIRM",
        "retrospective_relations_present": any(
            card.get("evidence_timing") == "RETROSPECTIVE_AFTER_TARGET_DATE" for card in eligible_cards),
        "gaps": sorted(set(gaps)),
        **FLAGS,
    }
    return result


_DAILY_RELATION_ARTIFACT_KEYS = (
    "relation_source", "evidence_path", "evidence_file_sha256", "evidence_artifact_sha256",
    "review_receipt_sha256", "reviewed_relation_artifact_sha256", "reviewed_seed_file_sha256",
    "availability_registry_file_sha256", "availability_registry_artifact_sha256", "release_id",
    "available_at", "http_body_rehash_status", "eligible_relation_count", "source_card_count",
    "symbol_assessment_count", "eligible_symbol_assessment_count",
)
_DAILY_RELATION_SUMMARY_KEYS = (
    "status", "artifact_sha256", "source_card_count", "eligible_relation_count",
    "post_cutoff_relation_count", "post_cutoff_review_count", "review_pending_relation_count",
    "symbol_assessment_count", "eligible_symbol_assessment_count",
    "post_cutoff_symbol_assessment_count", "post_cutoff_symbol_assessment_review_count",
    "review_pending_symbol_assessment_count", "reviewed_seed_relation_count",
    "current_reviewed_relation_count", "withheld_candidate_count", "mapped_us_symbol_count",
    "configured_us_symbol_count", "configured_equity_symbol_count",
    "explicitly_assessed_equity_symbol_count", "equity_assessment_coverage_complete",
    "coverage_complete", "source_body_rehash_status", "assessment_identity",
    "current_bridge_session", "current_bridge_source_payload_sha256", "target_date_eligibility",
    "retrospective_relations_present", "gaps",
)


def _daily_relation_evidence_archive(value: Any) -> dict[str, Any]:
    """Persist cutoff-aware relation counts and source hashes, never review payloads."""
    if not isinstance(value, Mapping):
        return {"status": "CANNOT_CONFIRM", "gaps": ["US_RELATION_EVIDENCE_NOT_AVAILABLE"], **FLAGS}
    archived = {key: deepcopy(value[key]) for key in _DAILY_RELATION_SUMMARY_KEYS if key in value}
    source_artifacts = value.get("relation_source_artifacts")
    archived["relation_source_artifacts"] = [
        {key: deepcopy(source[key]) for key in _DAILY_RELATION_ARTIFACT_KEYS if key in source}
        for source in source_artifacts if isinstance(source, Mapping)
    ] if isinstance(source_artifacts, list) else []
    archived.setdefault("gaps", [])
    archived.update(FLAGS)
    return archived


def _daily_relation_source_identities(relation_evidence: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = relation_evidence.get("relation_source_artifacts")
    if not isinstance(rows, list):
        return []
    return [
        {key: deepcopy(row[key]) for key in _DAILY_RELATION_ARTIFACT_KEYS if key in row}
        for row in rows if isinstance(row, Mapping)
    ]


def _daily_relation_available(relation_evidence: Mapping[str, Any]) -> bool:
    def positive_count(key: str) -> bool:
        value = relation_evidence.get(key)
        return isinstance(value, int) and not isinstance(value, bool) and value > 0
    return any(positive_count(key) for key in (
        "reviewed_seed_relation_count", "current_reviewed_relation_count",
        "eligible_symbol_assessment_count",
    ))


def _daily_relation_artifact_sha256(relation_evidence: Mapping[str, Any]) -> str | None:
    if (isinstance(relation_evidence.get("current_reviewed_relation_count"), int)
            and relation_evidence.get("current_reviewed_relation_count", 0) > 0) or (
            isinstance(relation_evidence.get("eligible_symbol_assessment_count"), int)
            and relation_evidence.get("eligible_symbol_assessment_count", 0) > 0):
        value = relation_evidence.get("artifact_sha256")
        return value if isinstance(value, str) and _SHA.fullmatch(value) else None
    rows = relation_evidence.get("relation_source_artifacts")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, Mapping) and row.get("relation_source") == "RELEASE_PINNED_REVIEWED_SEED":
                value = row.get("reviewed_relation_artifact_sha256")
                return value if isinstance(value, str) and _SHA.fullmatch(value) else None
    return None


def build_daily_run(service: Any, target_trade_date: str, *, now: datetime) -> dict[str, Any]:
    date = strict_trade_date(target_trade_date)
    if now.tzinfo is None:
        raise ValueError("US_MAPPING_CLOCK_MUST_BE_AWARE")
    context = plan_context(date, now=now)
    from .us_market_bridge import project_us_market

    bridge = project_us_market(getattr(service, "_workspace_us_market_reader", None), date, context)
    bridge = attach_current_relation_evidence(bridge)
    relation_evidence_raw = bridge.get("relation_evidence")
    relation_evidence_raw = relation_evidence_raw if isinstance(relation_evidence_raw, Mapping) else {}
    relation_evidence = _daily_relation_evidence_archive(relation_evidence_raw)
    relation_source_identities = _daily_relation_source_identities(relation_evidence)
    relation_assessment_identity = relation_evidence_raw.get("assessment_identity")
    assessments = bridge.get("symbol_assessments")
    symbol_assessments = deepcopy(assessments) if isinstance(assessments, list) else []
    source_status = bridge.get("status")
    gaps = list(bridge.get("gaps") or [])
    gaps.extend(relation_evidence.get("gaps", []))
    matches: list[dict[str, Any]] = []
    complete_snapshot = source_status == "READY"
    row_mapping_eligible = complete_snapshot or (
        source_status == "PARTIAL" and bridge.get("mapping_eligible") is True
    )
    relation_available = _daily_relation_available(relation_evidence_raw)
    if not relation_available:
        gaps.append("US_HK_RELATION_NOT_AVAILABLE_AT_RESEARCH_CUTOFF")
    if row_mapping_eligible and relation_available:
        relations = {
            str(row.get("symbol") or "").upper(): row.get("relations", [])
            for row in symbol_assessments if isinstance(row, Mapping)
            and isinstance(row.get("relations"), list)
        }
        for row in bridge.get("raw_individual_up") or []:
            if not isinstance(row, Mapping):
                continue
            symbol = str(row.get("symbol") or "").upper()
            for card in relations.get(symbol, []):
                if not isinstance(card, Mapping):
                    continue
                provenance = card.get("provenance") if isinstance(card.get("provenance"), Mapping) else {}
                evidence_provenance = card.get("evidence_provenance")
                if not isinstance(evidence_provenance, list):
                    evidence_provenance = [deepcopy(dict(provenance))] if provenance else []
                sources = card.get("official_sources")
                if not isinstance(sources, list):
                    sources = card.get("sources") if isinstance(card.get("sources"), list) else []
                relation_sha = next((
                    item.get("evidence_artifact_sha256") or item.get("reviewed_relation_artifact_sha256")
                    for item in evidence_provenance if isinstance(item, Mapping)
                    and (item.get("evidence_artifact_sha256") or item.get("reviewed_relation_artifact_sha256"))
                ), None)
                relation_identity = digest([
                    symbol, card.get("hk_symbol"), card.get("relationship_type"), card.get("direction"),
                    evidence_provenance, sources,
                ])
                matches.append({
                    "us_symbol": symbol,
                    "change_pct": row.get("change_pct"),
                    "session_date": row.get("session_date"),
                    "hk_symbol": card.get("hk_symbol"),
                    "hk_code": card.get("hk_code"),
                    "hk_name": card.get("hk_name"),
                    "research_priority": card.get("research_priority"),
                    "relationship_type": card.get("relationship_type"),
                    "direction": card.get("direction"),
                    "reason": card.get("reason"),
                    "maturity": card.get("maturity"),
                    "limitations": deepcopy(card.get("limitations", [])),
                    "official_sources": deepcopy(sources),
                    "relation_source": card.get("relation_source"),
                    "evidence_review_status": card.get("evidence_review_status"),
                    "evidence_timing": card.get("evidence_timing"),
                    "available_at": card.get("available_at"),
                    "reviewed_at": card.get("reviewed_at"),
                    "reviewer_identity": card.get("reviewer_identity"),
                    "review_receipt_sha256": card.get("review_receipt_sha256"),
                    "http_body_rehash_status": card.get("http_body_rehash_status"),
                    "provenance": deepcopy(dict(provenance)),
                    "evidence_provenance": deepcopy(evidence_provenance),
                    "relation_identity_sha256": relation_identity,
                    "reviewed_relation_artifact_sha256": relation_sha,
                    "target_date_eligibility": "CANNOT_CONFIRM",
                    "source_row": deepcopy(dict(row)),
                })
    if source_status == "SOURCE_FAILED":
        status = "FAILED"
    elif source_status in {"INPUT_MISSING", "CANNOT_CONFIRM"}:
        status = "INPUT_MISSING" if source_status == "INPUT_MISSING" else "CANNOT_CONFIRM"
    elif source_status == "PARTIAL":
        status = "PARTIAL"
        gaps.append("US_MARKET_SOURCE_PARTIAL")
    elif complete_snapshot:
        status = "COMPLETED" if matches else "VALID_EMPTY" if relation_available else "PARTIAL"
    else:
        status = "CANNOT_CONFIRM"
        gaps.append("US_MARKET_SOURCE_STATUS_UNRECOGNIZED")

    coverage = bridge.get("coverage") if isinstance(bridge.get("coverage"), Mapping) else {}
    source_identity = bridge.get("source_identity") if isinstance(bridge.get("source_identity"), Mapping) else None
    relation_sha = _daily_relation_artifact_sha256(relation_evidence_raw) if relation_available else None
    identity = digest([
        date, bridge.get("expected_us_session"), bridge.get("research_cutoff"), source_identity,
        bridge.get("source_response_sha256"), bridge.get("captured_at"), source_status,
        relation_assessment_identity, relation_source_identities, matches, relation_sha,
    ])
    reviewed_symbol_count = relation_evidence_raw.get("mapped_us_symbol_count")
    if relation_available and not isinstance(reviewed_symbol_count, int):
        reviewed_symbol_count = 0
    elif not relation_available:
        reviewed_symbol_count = None
    run_id = uuid4().hex
    value = {
        "schema_version": DAILY_SCHEMA,
        "status": status,
        "target_trade_date": date,
        "run_id": run_id,
        "generated_at": _now_text(now),
        "us_session_date": bridge.get("expected_us_session"),
        "research_cutoff": bridge.get("research_cutoff"),
        "coverage_scope": "CUTOFF_ELIGIBLE_REVIEWED_RELATIONS_WITHIN_FIXED_33_CONFIGURED_SYMBOL_SAMPLE_NOT_FULL_MARKET",
        "coverage": {
            "reviewed_us_symbol_count": reviewed_symbol_count,
            "matched_us_symbol_count": len({row["us_symbol"] for row in matches}) if row_mapping_eligible and relation_available else None,
            "matched_hk_relation_count": len(matches) if row_mapping_eligible and relation_available else None,
            "configured_us_universe_count": coverage.get("requested_symbol_count") if row_mapping_eligible else None,
            "available_us_universe_count": coverage.get("available_symbol_count") if row_mapping_eligible else None,
            "full_market_coverage": False,
        },
        "matches": matches,
        "symbol_assessments": symbol_assessments,
        "relation_evidence": relation_evidence,
        "relation_assessment_identity": relation_assessment_identity,
        "relation_source_identities": relation_source_identities,
        "source_status": source_status,
        "source_identity": deepcopy(dict(source_identity)) if source_identity else None,
        "source_gaps": gaps,
        "input_identity": identity,
        "relation_artifact_sha256": relation_sha,
        "target_date_eligibility": "CANNOT_CONFIRM",
        "producer_owner": "ManagerResearchJobService / ResearchPeripheralStore read adapter",
        "readback_required": True,
        "gaps": sorted(set(gaps)),
        **FLAGS,
    }
    return value


def persist_daily_run(service: Any, target_trade_date: str, *, now: datetime,
                      timeout_seconds: float | None = None,
                      execution_context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    date = strict_trade_date(target_trade_date)
    budget = MAX_PREPARATION_SECONDS if timeout_seconds is None else timeout_seconds
    if isinstance(budget, bool) or not isinstance(budget, (int, float)) or not math.isfinite(budget) or not 0 < budget <= MAX_PREPARATION_SECONDS:
        raise ValueError("US_MAPPING_OWNER_BUDGET_INVALID")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("US_MAPPING_CLOCK_MUST_BE_AWARE")
    actual_started = now
    research_cutoff, cutoff_policy, resolved_timing = _target_bound_cutoff(date, actual_started)
    supplied_context = dict(execution_context or {})
    trigger_kind = supplied_context.get("trigger_kind", "UNKNOWN")
    timing = resolved_timing if resolved_timing == "RETROSPECTIVE" else supplied_context.get("timing", "UNCLASSIFIED")
    if trigger_kind == "SCHEDULED" and timing == "UNCLASSIFIED":
        timing = "LATE_CATCHUP"
    supplied_context.update({"trigger_kind": trigger_kind, "timing": timing})
    trigger_id = supplied_context.get("trigger_id")
    if trigger_id is not None and not re.fullmatch(r"[0-9a-f]{64}", str(trigger_id)):
        raise ValueError("US_MAPPING_TRIGGER_ID_INVALID")

    store = service.store
    deadline = time.monotonic() + float(budget)
    read_budget = _ReadBudget(deadline)
    trigger_lock = (store._io.kernel_lock(f".locks/us-mapping-trigger-{trigger_id}.mutex",
                                          timeout=max(0.0, deadline - time.monotonic()))
                    if trigger_id else nullcontext())
    try:
        with trigger_lock:
            started_path = _dispatch_path(store, date, str(trigger_id), ".started") if trigger_id else None
            terminal_path = _dispatch_path(store, date, str(trigger_id)) if trigger_id else None
            terminal = _read_dispatch(store, date, str(trigger_id), read_budget=read_budget) if trigger_id else None
            if terminal is not None:
                read_budget.check()
                return _result_from_dispatch(store, date, terminal)
            started = read_budget.read_json(store, started_path) if started_path is not None else None
            if started is not None:
                if (started.get("schema_version") != DISPATCH_SCHEMA or started.get("state") != "RUNNING"
                        or started.get("target_trade_date") != date or started.get("trigger_id") != trigger_id
                        or started.get("sha256") != _seal_dispatch(started)["sha256"]):
                    raise ValueError("US_MAPPING_DISPATCH_STARTED_RECEIPT_INVALID")
                reconciled = _run_for_trigger(store, date, str(trigger_id), read_budget=read_budget)
                if reconciled is not None:
                    _promote_recovered_run(store, date, reconciled, read_budget=read_budget)
                    finished = max(datetime.now(actual_started.tzinfo), actual_started)
                    prior_started = datetime.fromisoformat(started["started_at"])
                    attempt_context = _attempt_execution_context(supplied_context, target=date,
                        started_at=prior_started, finished_at=finished, cutoff_policy=cutoff_policy)
                    terminal = _write_dispatch_terminal(store, date, str(trigger_id), started,
                        reconciled, read_budget=read_budget, attempt_context=attempt_context)
                    return _result_from_dispatch(store, date, terminal)
                failure = _failure_result(date, "US_MAPPING_RECONCILIATION_REQUIRED", now=actual_started,
                    execution_context=supplied_context, research_cutoff=research_cutoff,
                    cutoff_policy=cutoff_policy)
                _write_dispatch_terminal(store, date, str(trigger_id), started, failure,
                    attempt_context=failure["execution_context"])
                return failure

            started_record = None
            if trigger_id:
                started_record = _seal_dispatch({
                    "schema_version": DISPATCH_SCHEMA, "state": "RUNNING",
                    "target_trade_date": date, "trigger_id": trigger_id,
                    "started_at": actual_started.isoformat(timespec="microseconds"),
                    "budget_seconds": float(budget), "owner": _OWNER,
                    "execution_context": {key: value for key, value in supplied_context.items()
                                          if key not in {"started_at", "finished_at"}},
                    **FLAGS,
                })
                raw_started = json.dumps(started_record, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":"), allow_nan=False).encode("utf-8")
                read_budget.check()
                store._io.write_bytes(str(started_path.relative_to(store.root)), raw_started, require_absent=True)
                read_budget.check()
                if read_budget.read_json(store, started_path) != started_record:
                    raise ValueError("US_MAPPING_DISPATCH_STARTED_READBACK_FAILED")

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                build = None
                build_error = "US_MAPPING_OWNER_READ_TIMEOUT"
            else:
                build, build_error = _bounded_build(service, date, research_cutoff, remaining)
            actual_finished = max(datetime.now(actual_started.tzinfo), actual_started)
            if build_error is not None or build is None:
                failure = _failure_result(date, build_error or "US_MAPPING_OWNER_BUILD_FAILED",
                    now=actual_started, execution_context=supplied_context,
                    research_cutoff=research_cutoff, cutoff_policy=cutoff_policy)
                if trigger_id and started_record is not None:
                    _write_dispatch_terminal(store, date, str(trigger_id), started_record, failure,
                        attempt_context=failure["execution_context"])
                return failure
            read_budget.check()

            value = dict(build)
            if value.get("target_trade_date") != date:
                raise ValueError("US_MAPPING_DAILY_TARGET_MISMATCH")
            context = _execution_metadata(supplied_context, target=date,
                started_at=actual_started, finished_at=actual_finished,
                research_cutoff_policy=cutoff_policy)
            value["generated_at"] = _now_text(actual_finished)
            value["execution_context"] = context
            value["research_cutoff_policy"] = cutoff_policy
            unsigned = dict(value)
            value["artifact_sha256"] = sha256_json(unsigned)
            _safe_tree(value)

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failure = _failure_result(date, "US_MAPPING_OWNER_PUBLICATION_BUDGET_EXHAUSTED",
                    now=actual_started, execution_context=supplied_context,
                    research_cutoff=research_cutoff, cutoff_policy=cutoff_policy)
                if trigger_id and started_record is not None:
                    _write_dispatch_terminal(store, date, str(trigger_id), started_record, failure,
                        attempt_context=failure["execution_context"])
                return failure

            with store._io.kernel_lock(".locks/us-mapping-products.v1.mutex", timeout=remaining):
                reusable = _equivalent_run(store, date, value, read_budget=read_budget)
                if reusable is None:
                    run_relative = f"us_mapping_research/{date}/runs/{value['run_id']}.json"
                    raw_value = json.dumps(value, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":"), allow_nan=False).encode("utf-8")
                    read_budget.check()
                    store._io.write_bytes(run_relative, raw_value, require_absent=True)
                    read_budget.check()
                    saved = _read_exact_run(store, date, value["run_id"], value["artifact_sha256"],
                                            read_budget=read_budget)
                else:
                    saved = reusable
                prior = _read_saved(store, date, read_budget=read_budget)
                if (saved.get("status") in {"COMPLETED", "VALID_EMPTY", "PARTIAL"} or prior is None):
                    if trigger_id and started_record is not None:
                        _write_publication_intent(store, date, str(trigger_id), started_record,
                            saved, read_budget=read_budget)
                    pointer = {
                        "schema_version": "v4.manager_research.us_mapping_daily_pointer.v1",
                        "target_trade_date": date,
                        "run_id": saved["run_id"],
                        "artifact_sha256": saved["artifact_sha256"],
                        **FLAGS,
                    }
                    raw_pointer = json.dumps(pointer, ensure_ascii=False, sort_keys=True,
                                             separators=(",", ":"), allow_nan=False).encode("utf-8")
                    read_budget.check()
                    store._io.write_bytes(f"us_mapping_research/{date}/latest.json", raw_pointer)
                    read_budget.check()
                    readback = _read_saved(store, date, read_budget=read_budget)
                    if readback is None or readback.get("run_id") != saved["run_id"]:
                        raise ValueError("US_MAPPING_DAILY_POINTER_READBACK_FAILED")
                else:
                    # Keep a previous same-date successful product visible;
                    # the failed/unknown attempt remains in its own immutable run/receipt.
                    readback = _read_saved(store, date, read_budget=read_budget)
                    if readback is None:
                        raise ValueError("US_MAPPING_DAILY_PRIOR_READBACK_FAILED")

            if trigger_id and started_record is not None:
                attempt_context = _attempt_execution_context(supplied_context, target=date,
                    started_at=actual_started, finished_at=max(datetime.now(actual_started.tzinfo), actual_started),
                    cutoff_policy=cutoff_policy)
                terminal = _write_dispatch_terminal(store, date, str(trigger_id), started_record, saved,
                    attempt_context=attempt_context)
                return _result_from_dispatch(store, date, terminal)
            return saved
    except (OSError, TimeoutError, ValueError) as exc:
        if str(exc) in {"US_MAPPING_OWNER_READ_TIMEOUT", "US_MAPPING_OWNER_READ_BUSY",
                        "US_MAPPING_OWNER_BUDGET_EXHAUSTED",
                        "US_MAPPING_OWNER_SCAN_RUN_BOUND_EXCEEDED",
                        "US_MAPPING_OWNER_SCAN_BYTE_BOUND_EXCEEDED"}:
            code = str(exc)
        elif "LOCK_TIMEOUT" in str(exc):
            code = "US_MAPPING_OWNER_LOCK_TIMEOUT"
        else:
            raise
        failure = _failure_result(date, code, now=actual_started,
            execution_context=supplied_context, research_cutoff=research_cutoff,
            cutoff_policy=cutoff_policy)
        return failure


__all__ = ["DAILY_SCHEMA", "SCHEMA", "attach_current_relation_evidence", "build_daily_run", "persist_daily_run", "read_workspace_mapping"]
