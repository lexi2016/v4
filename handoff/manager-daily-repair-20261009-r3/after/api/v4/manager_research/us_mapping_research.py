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
_SHA = re.compile(r"^[0-9a-f]{64}$")
_TARGET_SEED = "20260930"
_DAILY_RELATION_TYPES = {"DIRECT_NAMED_COMPONENT_SUPPLY", "PRODUCT_PEER", "OPTICAL_TRANSPORT_PEER"}
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
        "coverage": {"reviewed_us_symbol_count": 4, "matched_us_symbol_count": None,
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
            'coverage': {'reviewed_us_symbol_count': 4, 'matched_us_symbol_count': None,
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
            "reviewed_us_symbol_count": 4, "matched_us_symbol_count": None,
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
                "reviewed_us_symbol_count": 4,
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
                'reviewed_us_symbol_count': 4, 'matched_us_symbol_count': None,
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


def _relation_available_at(reviewed: Mapping[str, Any]) -> tuple[datetime | None, str | None]:
    """Return only a release-pinned system availability time for reviewed rows.

    The report's ``reviewed_at`` is a retrospective calendar date. It cannot
    establish when the rows became available inside this application. Daily
    joins therefore require the separately pinned deployment registry.
    """
    try:
        raw = RELATION_REGISTRY_PATH.read_bytes()
        registry = json.loads(raw)
        if not isinstance(registry, Mapping):
            return None, "US_HK_RELATION_AVAILABILITY_UNVERIFIED"
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
            return None, "US_HK_RELATION_AVAILABILITY_UNVERIFIED"
        return availability, None
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None, "US_HK_RELATION_AVAILABILITY_UNVERIFIED"


def build_daily_run(service: Any, target_trade_date: str, *, now: datetime) -> dict[str, Any]:
    date = strict_trade_date(target_trade_date)
    if now.tzinfo is None:
        raise ValueError("US_MAPPING_CLOCK_MUST_BE_AWARE")
    context = plan_context(date, now=now)
    from .us_market_bridge import project_us_market

    bridge = project_us_market(getattr(service, "_workspace_us_market_reader", None), date, context)
    reviewed = _read_reviewed()
    source_status = bridge.get("status")
    gaps = list(bridge.get("gaps") or [])
    matches: list[dict[str, Any]] = []
    complete_snapshot = source_status == "READY"
    relation_available_at, relation_registry_gap = _relation_available_at(reviewed)
    cutoff = timestamp(bridge.get("research_cutoff"))
    relation_available = bool(
        relation_available_at is not None and cutoff is not None and relation_available_at <= cutoff
    )
    if relation_registry_gap:
        gaps.append(relation_registry_gap)
    elif not relation_available:
        gaps.append("US_HK_RELATION_NOT_AVAILABLE_AT_RESEARCH_CUTOFF")
    if complete_snapshot and relation_available:
        relations = _relation_index()
        for row in bridge.get("raw_individual_up") or []:
            if not isinstance(row, Mapping):
                continue
            symbol = str(row.get("symbol") or "").upper()
            for card in relations.get(symbol, []):
                matches.append({
                    "us_symbol": symbol,
                    "change_pct": row.get("change_pct"),
                    "session_date": row.get("session_date"),
                    "hk_symbol": card.get("hk_symbol"),
                    "hk_name": card.get("hk_name"),
                    "research_priority": card.get("research_priority"),
                    "relationship_type": card.get("relationship_type"),
                    "reason": card.get("reason"),
                    "maturity": card.get("maturity"),
                    "limitations": card.get("limitations"),
                    "official_sources": deepcopy(card.get("official_sources", [])),
                    "reviewed_relation_artifact_sha256": reviewed.get("artifact_sha256"),
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
    relation_sha = reviewed.get("artifact_sha256") if relation_available else None
    # Cutoff is evidence on the run, but moving a clock over unchanged inputs
    # does not create a distinct mapping product. Eligibility, exact source
    # lineage and relation publication identity do.
    identity = digest([date, bridge.get("expected_us_session"), source_identity,
                       bridge.get("source_response_sha256"), bridge.get("captured_at"),
                       bridge.get("status"), bool(relation_available),
                       relation_available_at.isoformat() if relation_available_at else None,
                       relation_registry_gap, matches, relation_sha])
    run_id = uuid4().hex
    value = {
        "schema_version": DAILY_SCHEMA,
        "status": status,
        "target_trade_date": date,
        "run_id": run_id,
        "generated_at": _now_text(now),
        "us_session_date": bridge.get("expected_us_session"),
        "research_cutoff": bridge.get("research_cutoff"),
        "coverage_scope": "FOUR_REVIEWED_US_TICKER_RELATIONS_WITHIN_FIXED_33_CONFIGURED_SYMBOL_SAMPLE_NOT_FULL_MARKET",
        "coverage": {
            "reviewed_us_symbol_count": 4,
            "matched_us_symbol_count": len({row["us_symbol"] for row in matches}) if complete_snapshot and relation_available else None,
            "matched_hk_relation_count": len(matches) if complete_snapshot and relation_available else None,
            "configured_us_universe_count": coverage.get("requested_symbol_count") if complete_snapshot else None,
            "available_us_universe_count": coverage.get("available_symbol_count") if complete_snapshot else None,
            "full_market_coverage": False,
        },
        "matches": matches,
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


__all__ = ["DAILY_SCHEMA", "SCHEMA", "build_daily_run", "persist_daily_run", "read_workspace_mapping"]
