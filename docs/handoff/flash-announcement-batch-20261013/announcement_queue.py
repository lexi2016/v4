"""Persistent, research-only serial queue for an existing per-article engine.

This module owns queue state and ordering only. Callers supply the production
engine callback and the existing validator; this module never fetches sources,
starts a service, or interprets the domain meaning of a validated result.

All queues/processes for one model must use the same ``state_root``. The shared
model lock is scoped to that root and model ID. A different state root is a
different lock domain and cannot provide cross-root single-slot guarantees.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from typing import Any, Callable, Iterable, Iterator, Mapping


STATE_SCHEMA = "v4.announcement-engine-queue/v1"
IDENTITY_FIELDS = (
    "date",
    "market",
    "article_id",
    "source_sha256",
    "body_sha256",
    "prompt_sha256",
    "model_id",
    "configuration_sha256",
    "rules",
    "role",
    "stage",
)
HASH_FIELDS = ("source_sha256", "body_sha256", "prompt_sha256", "configuration_sha256")
STATUSES = ("PENDING", "RUNNING", "SUCCEEDED", "FAILED", "OVERSIZE", "MISSING_MATERIAL")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


class AnnouncementQueueError(RuntimeError):
    """Base error for queue state and callback contract failures."""


class CorruptQueueState(AnnouncementQueueError):
    """The persisted state is invalid; it is never silently reset."""


class IdempotencyConflict(AnnouncementQueueError):
    """One identity key was submitted with different payload bytes."""


class ModelSlotBusy(AnnouncementQueueError):
    """A nonblocking request could not acquire the model-wide slot."""


class ValidationRejected(AnnouncementQueueError):
    """An existing validator may raise this with a stable rejection code."""

    def __init__(self, message: str, *, code: str = "VALIDATOR_REJECTED") -> None:
        super().__init__(message)
        self.code = code


class ExecutorFailure(AnnouncementQueueError):
    """Transport adapters can preserve partial raw output when they fail."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "EXECUTOR_FAILURE",
        raw_response: str | bytes | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.raw_response = raw_response


@dataclass(frozen=True)
class QueueJob:
    idempotency_key: str
    queue_id: str
    model_id: str
    identity: Mapping[str, Any]
    payload: Mapping[str, Any]
    attempt: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _thread_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _THREAD_LOCKS[key] = lock
        return lock


@contextmanager
def _file_lock(path: Path, *, blocking: bool = True) -> Iterator[bool]:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    local_lock = _thread_lock(path)
    if not local_lock.acquire(blocking=blocking):
        yield False
        return
    fd = -1
    acquired = False
    try:
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.fchmod(fd, 0o600)
        operation = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(fd, operation)
            acquired = True
        except BlockingIOError:
            yield False
            return
        yield True
    finally:
        if fd >= 0:
            if acquired:
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        local_lock.release()


def _atomic_write(path: Path, raw: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def _mkdir_private(path: Path) -> None:
    existed = path.exists()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not existed:
        os.chmod(path, 0o700)
    if path.stat().st_mode & 0o077:
        raise PermissionError(f"queue directory must not be group/world accessible: {path}")


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


class SerialAnnouncementQueue:
    """Durable one-article-at-a-time queue with a model-wide file lock.

    The executor must return the unparsed response body as ``str`` or ``bytes``.
    If transport fails after receiving partial body bytes, raise
    ``ExecutorFailure(..., raw_response=body)`` so those bytes are committed
    before the failure is recorded. The validator receives parsed JSON only
    after the raw response is durably stored; it must return a JSON-serializable
    accepted value or raise to reject the article.
    """

    def __init__(
        self,
        state_root: str | Path,
        queue_id: str,
        model_id: str,
        *,
        max_attempts: int,
        max_body_bytes: int | None = None,
    ) -> None:
        if not queue_id or not queue_id.strip():
            raise ValueError("queue_id must be non-empty")
        if not model_id or not model_id.strip():
            raise ValueError("model_id must be non-empty")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        if max_body_bytes is not None and (
            isinstance(max_body_bytes, bool) or not isinstance(max_body_bytes, int) or max_body_bytes < 1
        ):
            raise ValueError("max_body_bytes must be a positive integer or None")
        self.state_root = Path(state_root).expanduser().resolve()
        self.queue_id = queue_id.strip()
        self.model_id = model_id.strip()
        self.max_attempts = int(max_attempts)
        self.max_body_bytes = int(max_body_bytes) if max_body_bytes is not None else None
        self.state_path = self.state_root / "queue-state.json"
        self._state_lock_path = self.state_root / "locks" / "queue-state.lock"
        self._model_lock_path = self.state_root / "locks" / f"model-{_sha256(self.model_id.encode())}.lock"
        self.jobs_root = self.state_root / "jobs"
        _mkdir_private(self.state_root)
        _mkdir_private(self.jobs_root)
        _mkdir_private(self.state_root / "locks")

    def _empty_state(self) -> dict[str, Any]:
        return {
            "schema": STATE_SCHEMA,
            "created_at": _utc_now(),
            "jobs": {},
            "events": [],
        }

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return self._empty_state()
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CorruptQueueState(f"queue state cannot be read: {type(exc).__name__}") from exc
        if (
            not isinstance(value, dict)
            or value.get("schema") != STATE_SCHEMA
            or not isinstance(value.get("jobs"), dict)
            or not isinstance(value.get("events"), list)
        ):
            raise CorruptQueueState("queue state schema is invalid")
        return value

    def _save_state(self, state: dict[str, Any]) -> None:
        _atomic_write(self.state_path, _canonical_bytes(state))

    def _event(
        self,
        state: dict[str, Any],
        item: dict[str, Any],
        event: str,
        **details: Any,
    ) -> None:
        state["events"].append(
            {
                "at": _utc_now(),
                "event": event,
                "idempotency_key": item["idempotency_key"],
                "queue_id": item["queue_id"],
                "model_id": item["model_id"],
                "attempt": item["attempt_count"],
                **details,
            }
        )

    @staticmethod
    def _identity(payload: Mapping[str, Any]) -> dict[str, Any]:
        return {name: payload.get(name) for name in IDENTITY_FIELDS}

    def _material_problems(self, payload: Mapping[str, Any]) -> list[str]:
        problems: list[str] = []
        for name in ("date", "market", "article_id", "model_id"):
            value = payload.get(name)
            if not isinstance(value, str) or not value.strip():
                problems.append(f"MISSING_{name.upper()}")
        if payload.get("rules") is None or payload.get("rules") == "":
            problems.append("MISSING_RULES")
        for name in HASH_FIELDS:
            value = payload.get(name)
            if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
                problems.append(f"INVALID_{name.upper()}")
        if not any(isinstance(payload.get(name), str) and payload[name].strip() for name in ("role", "stage")):
            problems.append("MISSING_ROLE_OR_STAGE")
        body = payload.get("article_body")
        if not isinstance(body, str) or not body.strip():
            problems.append("MISSING_ARTICLE_BODY")
        elif isinstance(payload.get("body_sha256"), str) and _SHA256_RE.fullmatch(payload["body_sha256"]):
            if _sha256(body.encode("utf-8")) != payload["body_sha256"]:
                problems.append("BODY_SHA256_MISMATCH")
        if payload.get("model_id") != self.model_id:
            problems.append("MODEL_ID_MISMATCH")
        return list(dict.fromkeys(problems))

    def enqueue(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Persist one input, preserving full body even when it is oversize."""
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping")
        try:
            payload_raw = _canonical_bytes(dict(payload))
            frozen_payload = json.loads(payload_raw.decode("utf-8"))
            identity = self._identity(frozen_payload)
        except (TypeError, ValueError, UnicodeError) as exc:
            raise ValueError(f"payload must contain JSON-serializable values: {type(exc).__name__}") from exc
        payload_sha = _sha256(payload_raw)
        missing = self._material_problems(frozen_payload)
        identity_key_material: Any = identity
        if missing:
            identity_key_material = {"incomplete_identity": identity, "payload_sha256": payload_sha}
        key = _sha256(_canonical_bytes(identity_key_material))
        body = frozen_payload.get("article_body")
        body_bytes = len(body.encode("utf-8")) if isinstance(body, str) else 0
        if missing:
            initial_status = "MISSING_MATERIAL"
        elif self.max_body_bytes is not None and body_bytes > self.max_body_bytes:
            initial_status = "OVERSIZE"
        else:
            initial_status = "PENDING"

        with _file_lock(self._state_lock_path) as acquired:
            assert acquired
            state = self._load_state()
            prior = state["jobs"].get(key)
            if prior is not None:
                if prior.get("payload_sha256") != payload_sha:
                    raise IdempotencyConflict("same identity key received different payload bytes")
                policy = {"max_attempts": self.max_attempts, "max_body_bytes": self.max_body_bytes}
                if prior.get("queue_policy", policy) != policy:
                    raise IdempotencyConflict("same identity key was submitted with a different queue policy")
                queue_ids = prior.setdefault("queue_ids", [prior["queue_id"]])
                if self.queue_id not in queue_ids:
                    queue_ids.append(self.queue_id)
                    self._event(state, prior, "identity_deduplicated", submitted_queue_id=self.queue_id)
                    self._save_state(state)
                return self._public_item(prior, self.state_root)

            item_dir = self.jobs_root / key
            _mkdir_private(item_dir)
            input_path = item_dir / "input.json"
            _atomic_write(input_path, payload_raw)
            now = _utc_now()
            item = {
                "idempotency_key": key,
                "queue_id": self.queue_id,
                "queue_ids": [self.queue_id],
                "model_id": self.model_id,
                "identity": identity,
                "payload_sha256": payload_sha,
                "input_path": _relative(input_path, self.state_root),
                "body_length_bytes": body_bytes,
                "max_attempts": self.max_attempts,
                "queue_policy": {"max_attempts": self.max_attempts, "max_body_bytes": self.max_body_bytes},
                "attempt_count": 0,
                "attempts": [],
                "status": initial_status,
                "missing_material": missing,
                "created_at": now,
                "updated_at": now,
                "raw_path": None,
                "raw_sha256": None,
                "validated_path": None,
                "validated_sha256": None,
                "last_error": None,
            }
            state["jobs"][key] = item
            self._event(
                state,
                item,
                "item_enqueued",
                status=initial_status,
                body_length_bytes=body_bytes,
                missing_material=missing,
            )
            self._save_state(state)
            return self._public_item(item, self.state_root)

    def enqueue_many(self, payloads: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """Persist each submitted row; repeated identities remain idempotent."""
        return [self.enqueue(payload) for payload in payloads]

    @staticmethod
    def _public_item(item: Mapping[str, Any], state_root: Path) -> dict[str, Any]:
        attempts = []
        for attempt in item.get("attempts", []):
            attempt_view = {
                name: attempt.get(name)
                for name in (
                    "number",
                    "consumer_queue_id",
                    "status",
                    "started_at",
                    "finished_at",
                    "duration_seconds",
                    "raw_sha256",
                    "raw_length_bytes",
                    "validated_sha256",
                    "error",
                )
            }
            attempt_view["raw_path"] = str(state_root / attempt["raw_path"]) if attempt.get("raw_path") else None
            attempt_view["validated_path"] = (
                str(state_root / attempt["validated_path"]) if attempt.get("validated_path") else None
            )
            attempts.append(attempt_view)
        return {
            "idempotency_key": item["idempotency_key"],
            "queue_id": item["queue_id"],
            "queue_ids": item.get("queue_ids", [item["queue_id"]]),
            "model_id": item["model_id"],
            "identity": item["identity"],
            "status": item["status"],
            "body_length_bytes": item["body_length_bytes"],
            "attempt_count": item["attempt_count"],
            "max_attempts": item["max_attempts"],
            "missing_material": item["missing_material"],
            "raw_path": str(state_root / item["raw_path"]) if item.get("raw_path") else None,
            "raw_sha256": item.get("raw_sha256"),
            "validated_path": str(state_root / item["validated_path"]) if item.get("validated_path") else None,
            "validated_sha256": item.get("validated_sha256"),
            "last_error": item.get("last_error"),
            "attempts": attempts,
        }

    def _read_payload(self, item: Mapping[str, Any]) -> dict[str, Any]:
        path = self.state_root / item["input_path"]
        try:
            raw = path.read_bytes()
            if _sha256(raw) != item["payload_sha256"]:
                raise CorruptQueueState(f"persisted input SHA mismatch: {item['idempotency_key']}")
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CorruptQueueState(f"persisted input is unreadable: {type(exc).__name__}") from exc
        if not isinstance(value, dict):
            raise CorruptQueueState("persisted input must be an object")
        return value

    def _recover_running_locked(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        recovered: list[dict[str, Any]] = []
        now = _utc_now()
        for item in state["jobs"].values():
            if item.get("model_id") != self.model_id or item.get("status") != "RUNNING":
                continue
            attempts = item.get("attempts") or []
            attempt = attempts[-1] if attempts else None
            if isinstance(attempt, dict):
                attempt["status"] = "INTERRUPTED"
                attempt["finished_at"] = now
                attempt["duration_seconds"] = None
                attempt["error"] = {"stage": "recovery", "code": "PROCESS_INTERRUPTED", "message": "process ended while the item was RUNNING"}
                attempt_number = attempt.get("number", item.get("attempt_count", 0))
                raw_path = self.jobs_root / item["idempotency_key"] / f"attempt-{attempt_number:04d}.raw"
                if raw_path.exists():
                    raw_bytes = raw_path.read_bytes()
                    attempt["raw_path"] = _relative(raw_path, self.state_root)
                    attempt["raw_sha256"] = _sha256(raw_bytes)
                    attempt["raw_length_bytes"] = len(raw_bytes)
                    item["raw_path"] = attempt["raw_path"]
                    item["raw_sha256"] = attempt["raw_sha256"]
            item["status"] = "PENDING" if item["attempt_count"] < item["max_attempts"] else "FAILED"
            item["updated_at"] = now
            item["last_error"] = {"stage": "recovery", "code": "PROCESS_INTERRUPTED", "message": "interrupted work was not marked successful"}
            self._event(state, item, "attempt_interrupted", recovered_status=item["status"])
            recovered.append(self._public_item(item, self.state_root))
        if recovered:
            self._save_state(state)
        return recovered

    def recover_interrupted(self, *, wait_for_model_slot: bool = True) -> list[dict[str, Any]]:
        """Recover stale RUNNING entries only after owning the model lock."""
        with _file_lock(self._model_lock_path, blocking=wait_for_model_slot) as acquired:
            if not acquired:
                raise ModelSlotBusy(f"model slot busy for {self.model_id}")
            with _file_lock(self._state_lock_path) as state_acquired:
                assert state_acquired
                return self._recover_running_locked(self._load_state())

    def _claim_next_locked(
        self,
        state: dict[str, Any],
        allowed_keys: set[str] | None = None,
    ) -> dict[str, Any] | None:
        self._recover_running_locked(state)
        eligible = [
            item
            for item in state["jobs"].values()
            if self.queue_id in item.get("queue_ids", [item.get("queue_id")])
            and item.get("model_id") == self.model_id
            and item.get("status") == "PENDING"
            and item.get("attempt_count", 0) < item.get("max_attempts", 0)
            and (allowed_keys is None or item.get("idempotency_key") in allowed_keys)
        ]
        if not eligible:
            return None
        item = min(
            eligible,
            key=lambda value: (value.get("body_length_bytes", 0), value.get("created_at", ""), value["idempotency_key"]),
        )
        now = _utc_now()
        number = item["attempt_count"] + 1
        item["attempt_count"] = number
        item["status"] = "RUNNING"
        item["updated_at"] = now
        item["last_error"] = None
        item["raw_path"] = None
        item["raw_sha256"] = None
        item["validated_path"] = None
        item["validated_sha256"] = None
        item["attempts"].append(
            {
                "number": number,
                "status": "RUNNING",
                "consumer_queue_id": self.queue_id,
                "started_at": now,
                "finished_at": None,
                "duration_seconds": None,
                "raw_path": None,
                "raw_sha256": None,
                "raw_length_bytes": None,
                "validated_path": None,
                "validated_sha256": None,
                "error": None,
            }
        )
        self._event(state, item, "attempt_started", status="RUNNING", body_length_bytes=item["body_length_bytes"])
        self._save_state(state)
        return item

    def _persist_raw(self, item: dict[str, Any], attempt: dict[str, Any], raw: str | bytes) -> bytes:
        if isinstance(raw, str):
            raw_bytes = raw.encode("utf-8")
        elif isinstance(raw, bytes):
            raw_bytes = raw
        else:
            raise TypeError("executor must return the unparsed raw response as str or bytes")
        attempt_number = attempt["number"]
        path = self.jobs_root / item["idempotency_key"] / f"attempt-{attempt_number:04d}.raw"
        _atomic_write(path, raw_bytes)
        digest = _sha256(raw_bytes)
        with _file_lock(self._state_lock_path) as acquired:
            assert acquired
            state = self._load_state()
            current = state["jobs"][item["idempotency_key"]]
            current_attempt = current["attempts"][-1]
            current_attempt["raw_path"] = _relative(path, self.state_root)
            current_attempt["raw_sha256"] = digest
            current_attempt["raw_length_bytes"] = len(raw_bytes)
            current["raw_path"] = _relative(path, self.state_root)
            current["raw_sha256"] = digest
            current["updated_at"] = _utc_now()
            self._event(state, current, "raw_persisted", raw_sha256=digest, raw_length_bytes=len(raw_bytes))
            self._save_state(state)
        attempt.update(
            {
                "raw_path": _relative(path, self.state_root),
                "raw_sha256": digest,
                "raw_length_bytes": len(raw_bytes),
            }
        )
        return raw_bytes

    def _record_failure(
        self,
        item_key: str,
        attempt_number: int,
        *,
        stage: str,
        code: str,
        error_type: str,
        message: str,
        duration: float,
    ) -> dict[str, Any]:
        now = _utc_now()
        failure = {
            "stage": stage,
            "code": code,
            "type": error_type,
            "message": message[:2000],
        }
        with _file_lock(self._state_lock_path) as acquired:
            assert acquired
            state = self._load_state()
            item = state["jobs"][item_key]
            attempt = item["attempts"][-1]
            if attempt["number"] != attempt_number:
                raise CorruptQueueState("attempt changed while the model lock was held")
            attempt.update({"status": "FAILED", "finished_at": now, "duration_seconds": round(duration, 6), "error": failure})
            item["status"] = "FAILED"
            item["last_error"] = failure
            item["updated_at"] = now
            self._event(state, item, "attempt_failed", status="FAILED", duration_seconds=round(duration, 6), error=failure)
            self._save_state(state)
            return self._public_item(item, self.state_root)

    def _record_success(
        self,
        item_key: str,
        attempt_number: int,
        validated: Any,
        duration: float,
    ) -> dict[str, Any]:
        validated_raw = _canonical_bytes(validated)
        path = self.jobs_root / item_key / f"attempt-{attempt_number:04d}.validated.json"
        _atomic_write(path, validated_raw)
        digest = _sha256(validated_raw)
        now = _utc_now()
        with _file_lock(self._state_lock_path) as acquired:
            assert acquired
            state = self._load_state()
            item = state["jobs"][item_key]
            attempt = item["attempts"][-1]
            if attempt["number"] != attempt_number:
                raise CorruptQueueState("attempt changed while the model lock was held")
            attempt.update(
                {
                    "status": "SUCCEEDED",
                    "finished_at": now,
                    "duration_seconds": round(duration, 6),
                    "validated_path": _relative(path, self.state_root),
                    "validated_sha256": digest,
                }
            )
            item.update(
                {
                    "status": "SUCCEEDED",
                    "updated_at": now,
                    "validated_path": _relative(path, self.state_root),
                    "validated_sha256": digest,
                    "last_error": None,
                }
            )
            self._event(
                state,
                item,
                "attempt_completed",
                status="SUCCEEDED",
                duration_seconds=round(duration, 6),
                validated_sha256=digest,
            )
            self._save_state(state)
            return self._public_item(item, self.state_root)

    @staticmethod
    def _exception_code(exc: Exception, stage: str) -> str:
        if isinstance(exc, ExecutorFailure):
            return exc.code
        if isinstance(exc, ValidationRejected):
            return exc.code
        if isinstance(exc, TimeoutError):
            return "TIMEOUT"
        if stage == "json_parse":
            return "INVALID_JSON"
        if stage == "raw_contract":
            return "RAW_RESPONSE_REQUIRED"
        if stage == "decode":
            return "INVALID_UTF8"
        if stage == "validator_output":
            return "INVALID_VALIDATOR_OUTPUT"
        if stage == "result_persist":
            return "RESULT_PERSIST_ERROR"
        return f"{stage.upper()}_ERROR"

    def run_next(
        self,
        executor: Callable[[QueueJob], str | bytes],
        validator: Callable[[QueueJob, Any], Any],
        *,
        wait_for_model_slot: bool = True,
        idempotency_keys: Iterable[str] | None = None,
    ) -> dict[str, Any] | None:
        """Execute at most one item; failures are persisted and returned."""
        if not callable(executor) or not callable(validator):
            raise TypeError("executor and validator callbacks are required")
        with _file_lock(self._model_lock_path, blocking=wait_for_model_slot) as model_acquired:
            if not model_acquired:
                raise ModelSlotBusy(f"model slot busy for {self.model_id}")
            with _file_lock(self._state_lock_path) as state_acquired:
                assert state_acquired
                state = self._load_state()
                allowed_keys = set(idempotency_keys) if idempotency_keys is not None else None
                item = self._claim_next_locked(state, allowed_keys)
            if item is None:
                return None

            attempt = item["attempts"][-1]
            started = time.monotonic()
            stage = "input_read"
            raw_persisted = False
            try:
                payload = self._read_payload(item)
                job = QueueJob(
                    idempotency_key=item["idempotency_key"],
                    queue_id=item["queue_id"],
                    model_id=item["model_id"],
                    identity=item["identity"],
                    payload=payload,
                    attempt=attempt["number"],
                )
                stage = "executor"
                raw = executor(job)
                stage = "raw_contract"
                if not isinstance(raw, (str, bytes)):
                    raise TypeError("executor must return unparsed raw response bytes or text")
                stage = "raw_persist"
                raw_bytes = self._persist_raw(item, attempt, raw)
                raw_persisted = True
                stage = "decode"
                raw_text = raw_bytes.decode("utf-8", errors="strict")
                stage = "json_parse"
                parsed = json.loads(raw_text)
                stage = "validator"
                validated = validator(job, parsed)
                stage = "result_persist"
                _canonical_bytes(validated)
                return self._record_success(
                    item["idempotency_key"],
                    attempt["number"],
                    validated,
                    time.monotonic() - started,
                )
            except Exception as exc:
                partial = getattr(exc, "raw_response", None)
                if not raw_persisted and isinstance(partial, (str, bytes)):
                    try:
                        self._persist_raw(item, attempt, partial)
                    except Exception as persist_exc:
                        stage = "raw_persist"
                        exc = persist_exc
                code = self._exception_code(exc, stage)
                return self._record_failure(
                    item["idempotency_key"],
                    attempt["number"],
                    stage=stage,
                    code=code,
                    error_type=type(exc).__name__,
                    message=str(exc) or type(exc).__name__,
                    duration=time.monotonic() - started,
                )

    def run_pending(
        self,
        executor: Callable[[QueueJob], str | bytes],
        validator: Callable[[QueueJob, Any], Any],
        *,
        idempotency_keys: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Run each currently pending item once; one failure never aborts the next."""
        outcomes: list[dict[str, Any]] = []
        allowed_keys = set(idempotency_keys) if idempotency_keys is not None else None
        while True:
            result = self.run_next(executor, validator, idempotency_keys=allowed_keys)
            if result is None:
                return outcomes
            outcomes.append(result)

    def retry_failed(self, idempotency_keys: Iterable[str] | None = None) -> list[str]:
        """Schedule only retryable failures; each item's attempt ceiling is frozen."""
        requested = set(idempotency_keys) if idempotency_keys is not None else None
        scheduled: list[str] = []
        with _file_lock(self._state_lock_path) as acquired:
            assert acquired
            state = self._load_state()
            for item in state["jobs"].values():
                if self.queue_id not in item.get("queue_ids", [item.get("queue_id")]) or item.get("model_id") != self.model_id:
                    continue
                if item.get("status") != "FAILED" or item.get("attempt_count", 0) >= item.get("max_attempts", 0):
                    continue
                if requested is not None and item["idempotency_key"] not in requested:
                    continue
                item["status"] = "PENDING"
                item["updated_at"] = _utc_now()
                self._event(state, item, "retry_scheduled", status="PENDING")
                scheduled.append(item["idempotency_key"])
            if scheduled:
                self._save_state(state)
        return scheduled

    def snapshot(self) -> dict[str, Any]:
        """Return UI-consumable progress counts without exposing article bodies."""
        with _file_lock(self._state_lock_path) as acquired:
            assert acquired
            state = self._load_state()
        items = [
            item
            for item in state["jobs"].values()
            if self.queue_id in item.get("queue_ids", [item.get("queue_id")]) and item.get("model_id") == self.model_id
        ]
        counts = {status: 0 for status in STATUSES}
        for item in items:
            status = item.get("status")
            if status not in counts:
                raise CorruptQueueState(f"unknown status: {status}")
            counts[status] += 1
        total = len(items)
        item_keys = {item["idempotency_key"] for item in items}
        visible_events = [event for event in state["events"] if event.get("idempotency_key") in item_keys]
        ordered_items = sorted(
            items,
            key=lambda value: (
                value.get("body_length_bytes", 0),
                value.get("created_at", ""),
                value["idempotency_key"],
            ),
        )
        return {
            "schema": STATE_SCHEMA,
            "queue_id": self.queue_id,
            "model_id": self.model_id,
            "state_root": str(self.state_root),
            "model_lock_scope": "same state_root and model_id across queues/processes",
            "total": total,
            "status_counts": counts,
            "unassessed_count": counts["PENDING"] + counts["RUNNING"],
            "not_selected_count": 0,
            "conservation_ok": sum(counts.values()) == total,
            "items": [self._public_item(item, self.state_root) for item in ordered_items],
            "event_count": len(visible_events),
            "recent_events": visible_events[-100:],
        }
