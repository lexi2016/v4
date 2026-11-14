"""Immutable plan/input storage, crash-safe publication and per-key OS locks."""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Iterator
from infrastructure.owned_io import SafeRoot

from .contracts import JobRecord, JobState, PlanSnapshot, ReviewSummary, canonical, validate_date

_DEFAULT_READ_LIMIT = 64 * 1024 * 1024
_PLAN_READ_LIMIT = 128 * 1024 * 1024
_INPUT_READ_LIMIT = 128 * 1024 * 1024
_INPUT_REF_SCHEMA = "v4.manager_workbench.input_snapshot_ref.v1"
_INPUT_BODY_SCHEMA = "v4.manager_workbench.input_snapshot_body.v1"
_OVERLAY_REF_SCHEMA = "v4.manager_workbench.full_overlay_ref.v1"
_OVERLAY_FIELDS = ("full_overlay_projection", "full_overlay_stock_identities")


class StorageConflict(Exception):
    pass


class StorageUnavailable(Exception):
    pass


def _key(v: str) -> str:
    if not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", v):
        raise ValueError("STORAGE_KEY_INVALID")
    return v


class WorkbenchStore:
    def __init__(self, state_root: str | Path):
        self.root = Path(state_root) / "manager_workbench"
        self.io = SafeRoot(self.root)
        self._dir(self.root)

    def _dir(self, path: Path) -> Path:
        # Existing components must not be symbolic links, including STATE_ROOT parents.
        for parent in (path, *path.parents):
            if parent.is_symlink():
                raise StorageUnavailable("UNSAFE_STATE_ROOT")
        SafeRoot(path).ensure_directory()
        return path

    def _path(self, *parts: str) -> Path:
        if not parts or any(not _key(p) for p in parts):
            raise ValueError("STORAGE_KEY_INVALID")
        directory = self.root.joinpath(*parts[:-1])
        result = directory / f"{parts[-1]}.json"
        if result.is_symlink():
            raise StorageUnavailable("SYMLINK_DENIED")
        return result

    @contextlib.contextmanager
    def lock(self, key: str) -> Iterator[None]:
        lock_key = hashlib.sha256(key.encode()).hexdigest()
        with self.io.kernel_lock(f"locks/{lock_key}.lock", timeout=10):
            yield

    def _read(self, path: Path, *, max_bytes: int = _DEFAULT_READ_LIMIT) -> dict[str, Any] | None:
        try:
            raw = self.io.read_bytes(str(path.relative_to(self.root)), max_bytes=max_bytes)
        except FileNotFoundError:
            return None
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            raise StorageUnavailable("CORRUPT_RECORD")
        return obj

    @staticmethod
    def _sync_dir(path: Path) -> None:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _write(self, path: Path, obj: dict[str, Any], *, immutable: bool,
               collision_read_limit: int = _DEFAULT_READ_LIMIT) -> None:
        data = canonical(obj)
        try:
            self.io.write_bytes(str(path.relative_to(self.root)),data,require_absent=immutable)
        except FileExistsError:
            if self._read(path, max_bytes=collision_read_limit) != obj:
                raise StorageConflict("IMMUTABLE_COLLISION")

    def _content_path(self, directory: str, sha: str) -> str:
        if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{64}", sha) is None:
            raise ValueError("INPUT_SHA_INVALID")
        return str(self._path(directory, sha).relative_to(self.root))

    def _read_content(self, path: str) -> bytes | None:
        try:
            return self.io.read_bytes(path, max_bytes=_INPUT_READ_LIMIT)
        except FileNotFoundError:
            return None

    @staticmethod
    def _map_overlay_fields(context: Any, convert: Callable[[Any], Any]) -> Any:
        """Change only the owner's named US mapping fields, not arbitrary nested data."""
        if not isinstance(context, dict) or not isinstance(context.get("scope_refs"), dict):
            return context
        scope = context["scope_refs"]

        def map_binding(binding):
            if not isinstance(binding, dict):
                return binding
            for field in _OVERLAY_FIELDS:
                if field in binding:
                    value = convert(binding[field])
                    if value is not binding[field]:
                        binding = {**binding, field: value}
            return binding

        mapping = scope.get("US_MAPPING")
        mapped = map_binding(mapping)
        if mapped is not mapping:
            scope = {**scope, "US_MAPPING": mapped}
        owners = scope.get("owner_bindings")
        if isinstance(owners, dict):
            binding = owners.get("us_mapping")
            mapped = map_binding(binding)
            if mapped is not binding:
                scope = {**scope, "owner_bindings": {**owners, "us_mapping": mapped}}
        return context if scope is context["scope_refs"] else {**context, "scope_refs": scope}

    @classmethod
    def _map_input_contexts(cls, body: dict[str, Any],
                            convert: Callable[[Any], Any]) -> dict[str, Any]:
        context = cls._map_overlay_fields(body.get("context"), convert)
        batches = body.get("batches")
        if not isinstance(batches, list):
            return body
        changed = context is not body.get("context")
        result = []
        for batch in batches:
            if isinstance(batch, dict):
                context_before = batch.get("context")
                context_after = cls._map_overlay_fields(context_before, convert)
                if context_after is not context_before:
                    batch = {**batch, "context": context_after}
                    changed = True
            result.append(batch)
        return {**body, "context": context, "batches": result} if changed else body

    def _overlay_writer(self) -> Callable[[Any], Any]:
        reused: dict[str, dict[str, str]] = {}
        by_identity: dict[int, dict[str, str]] = {}

        def convert(value: Any) -> Any:
            if not isinstance(value, list) or not value:
                return value
            prior = by_identity.get(id(value))
            if prior is not None:
                return prior
            raw = canonical(value)
            if len(raw) > _INPUT_READ_LIMIT:
                raise StorageUnavailable("OVERLAY_TOO_LARGE")
            sha = hashlib.sha256(raw).hexdigest()
            prior = reused.get(sha)
            if prior is not None:
                by_identity[id(value)] = prior
                return prior
            path = self._content_path("overlay_blobs", sha)
            with self.lock("overlay:" + sha):
                existing = self._read_content(path)
                if existing is None:
                    self.io.write_bytes(path, raw, require_absent=True)
                elif existing != raw:
                    raise StorageUnavailable("OVERLAY_SHA_MISMATCH")
            ref = {"schema": _OVERLAY_REF_SCHEMA, "sha256": sha}
            reused[sha] = by_identity[id(value)] = ref
            return ref

        return convert

    def _overlay_reader(self) -> Callable[[Any], Any]:
        loaded: dict[str, tuple[list, int]] = {}
        expanded_bytes = 0

        def convert(value: Any) -> Any:
            nonlocal expanded_bytes
            if not isinstance(value, dict) or value.get("schema") != _OVERLAY_REF_SCHEMA:
                return value
            if set(value) != {"schema", "sha256"}:
                raise StorageUnavailable("OVERLAY_REF_INVALID")
            sha = value["sha256"]
            path = self._content_path("overlay_blobs", sha)
            repeated = sha in loaded
            if not repeated:
                raw = self._read_content(path)
                if raw is None:
                    raise StorageUnavailable("OVERLAY_MISSING")
                if hashlib.sha256(raw).hexdigest() != sha:
                    raise StorageUnavailable("OVERLAY_SHA_MISMATCH")
                projection = json.loads(raw)
                if not isinstance(projection, list):
                    raise StorageUnavailable("OVERLAY_INVALID")
                loaded[sha] = (projection, len(raw))
            projection, size = loaded[sha]
            expanded_bytes += size
            if expanded_bytes > _INPUT_READ_LIMIT:
                raise StorageUnavailable("OVERLAY_HYDRATION_TOO_LARGE")
            return deepcopy(projection) if repeated else projection

        return convert

    def _decode_input(self, raw: bytes, sha: str) -> dict[str, Any]:
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise StorageUnavailable("CORRUPT_RECORD")
        exact = raw
        if body.get("schema") == _INPUT_BODY_SCHEMA:
            if set(body) != {"schema", "body"} or not isinstance(body["body"], dict):
                raise StorageUnavailable("INPUT_SNAPSHOT_ENVELOPE_INVALID")
            body = self._map_input_contexts(body["body"], self._overlay_reader())
            exact = canonical(body)
        if len(exact) > _INPUT_READ_LIMIT or hashlib.sha256(exact).hexdigest() != sha:
            raise StorageUnavailable("INPUT_SNAPSHOT_SHA_MISMATCH")
        return body

    def _ensure_input(self, input_sha: str, data: dict[str, Any], raw: bytes | None = None) -> None:
        path = self._content_path("input_snapshots", input_sha)
        with self.lock("input:" + input_sha):
            existing = self._read_content(path)
            if existing is not None:
                if hashlib.sha256(existing).hexdigest() != input_sha:
                    self._decode_input(existing, input_sha)
                return
            raw = canonical(data) if raw is None else raw
            if len(raw) > _INPUT_READ_LIMIT:
                raise StorageUnavailable("INPUT_SNAPSHOT_TOO_LARGE")
            if hashlib.sha256(raw).hexdigest() != input_sha:
                raise StorageConflict("INPUT_SNAPSHOT_SHA_MISMATCH")
            compact = self._map_input_contexts(data, self._overlay_writer())
            if compact is not data:
                raw = canonical({"schema": _INPUT_BODY_SCHEMA, "body": compact})
                if len(raw) > _INPUT_READ_LIMIT:
                    raise StorageUnavailable("INPUT_SNAPSHOT_TOO_LARGE")
            self.io.write_bytes(path, raw, require_absent=True)

    def save_input(self, input_sha: str, data: dict[str, Any]) -> None:
        raw = canonical(data)
        if hashlib.sha256(raw).hexdigest() != input_sha:
            raise StorageConflict("INPUT_SNAPSHOT_SHA_MISMATCH")
        self._ensure_input(input_sha, data, raw)

    @staticmethod
    def _validate_input_body(body: Any) -> None:
        if (not isinstance(body, dict) or not isinstance(body.get("context"), dict)
                or not isinstance(body.get("batches"), list)):
            raise StorageUnavailable("INPUT_CHECKPOINT_INVALID")

    def _checkpoint_input_sha(self, checkpoint: dict[str, Any]) -> str:
        if "schema" not in checkpoint:
            self._validate_input_body(checkpoint)
            return hashlib.sha256(canonical(checkpoint)).hexdigest()  # legacy inline data
        if (checkpoint["schema"] != _INPUT_REF_SCHEMA
                or set(checkpoint) != {"schema", "input_snapshot_sha256"}):
            raise StorageUnavailable("INPUT_CHECKPOINT_INVALID")
        return checkpoint["input_snapshot_sha256"]

    def load_input_checkpoint(self, job_id: str) -> tuple[dict[str, Any] | None, str | None]:
        checkpoint = self.load_checkpoint(job_id, "LOAD_INPUTS")
        if checkpoint is None:
            return None, None
        input_sha = self._checkpoint_input_sha(checkpoint)
        if "schema" not in checkpoint:
            return checkpoint, input_sha
        body = self.load_input(input_sha)
        if body is None:
            raise StorageUnavailable("INPUT_SNAPSHOT_MISSING")
        self._validate_input_body(body)
        return body, input_sha

    def save_input_checkpoint(self, job_id: str, data: dict[str, Any], *, input_sha: str | None = None) -> str:
        """Publish the full body before the small resume reference; never replace a checkpoint."""
        self._validate_input_body(data)
        raw = None
        if input_sha is None:
            raw = canonical(data)
            input_sha = hashlib.sha256(raw).hexdigest()
        with self.lock(f"checkpoint:{job_id}:LOAD_INPUTS"):
            existing = self.load_checkpoint(job_id, "LOAD_INPUTS")
            if existing is not None and self._checkpoint_input_sha(existing) != input_sha:
                raise StorageConflict("INPUT_CHECKPOINT_COLLISION")
            self._ensure_input(input_sha, data, raw)
            if existing is None:
                self._write(self._path("checkpoints", _key(job_id), "LOAD_INPUTS"),
                            {"schema": _INPUT_REF_SCHEMA, "input_snapshot_sha256": input_sha}, immutable=True)
        return input_sha

    def save_job(self, job: JobRecord) -> None:
        # Attempts are mutable; successful plans are not.
        with self.lock("job:" + job.job_id):
            body = job.model_dump(mode="json")
            body["context"] = self._map_overlay_fields(body["context"], self._overlay_writer())
            self._write(self._path("attempts", _key(job.job_id)), body, immutable=False)

    def get_job(self, job_id: str) -> JobRecord | None:
        obj = self._read(self._path("attempts", _key(job_id)))
        if obj is None:
            return None
        return self._job_from_obj(obj)

    def _job_from_obj(self, obj: dict[str, Any]) -> JobRecord:
        obj["context"] = self._map_overlay_fields(obj.get("context"), self._overlay_reader())
        return JobRecord.model_validate(obj)

    def _catalog(self, snap: PlanSnapshot) -> Path:
        return self._path("catalog", snap.context.target_date, snap.context.phase.value, _key(snap.run_id))

    def commit_plan(self, snap: PlanSnapshot, *, freeze: bool = False, merger=None) -> PlanSnapshot:
        """Publication is atomic only after immutable readback passes model+run+SHA checks."""
        date, phase = snap.context.target_date, snap.context.phase.value
        key = f"publish:{date}:{phase}"
        with self.lock(key):
            pointer_path = self._path("pointers", date, phase)
            before = self._read(pointer_path)
            if before and (freeze or phase == "PREOPEN"):
                if before.get("run_id") == snap.run_id and before.get("product_sha256") == snap.product_sha256:
                    return self.read_plan(snap.run_id)
                raise StorageConflict("PREOPEN_FROZEN")
            if merger is not None:
                previous=self.read_plan(before["run_id"]) if before else None
                snap=merger(previous,snap)
            d = snap.model_dump(mode="json")
            self._write(self._path("snapshots", _key(snap.run_id)), d, immutable=True,
                        collision_read_limit=_PLAN_READ_LIMIT)
            saved = self.read_plan(snap.run_id)
            if saved.context != snap.context or saved.product_sha256 != snap.product_sha256 or saved.input_sha256 != snap.input_sha256:
                raise StorageConflict("READBACK_MISMATCH")
            catalog_path=self._catalog(saved)
            catalog_before=self._read(catalog_path)
            catalog_value={"run_id": saved.run_id, "product_sha256": saved.product_sha256,
                           "generated_at": saved.generated_at, "input_sha256": saved.input_sha256}
            self._write(catalog_path,catalog_value,immutable=True)
            try:
                self._write(pointer_path, {"run_id": saved.run_id, "product_sha256": saved.product_sha256,
                                           "generated_at": saved.generated_at}, immutable=False)
            except Exception:
                if catalog_before is None and self._read(pointer_path)==before:
                    self.io.unlink_if_same(str(catalog_path.relative_to(self.root)),canonical(catalog_value))
                raise
            return saved

    def read_plan(self, run_id: str) -> PlanSnapshot:
        obj = self._read(self._path("snapshots", _key(run_id)), max_bytes=_PLAN_READ_LIMIT)
        if obj is None:
            raise KeyError("PLAN_NOT_FOUND")
        saved = PlanSnapshot.model_validate(obj)
        if saved.run_id != run_id:
            raise StorageConflict("RUN_ID_MISMATCH")
        return saved

    def list_plans(self, date: str, phase: str | None = None) -> list[PlanSnapshot]:
        validate_date(date)
        phases = [phase] if phase else ["PREOPEN", "INTRADAY", "NEXT_DAY", "RETROSPECTIVE", "MANUAL"]
        result: list[PlanSnapshot] = []
        for name in phases:
            if name not in ("PREOPEN", "INTRADAY", "NEXT_DAY", "RETROSPECTIVE", "MANUAL"):
                raise ValueError("PHASE_INVALID")
            folder = self.root / "catalog" / date / name
            if not folder.exists():
                continue
            if folder.is_symlink():
                raise StorageUnavailable("SYMLINK_DENIED")
            for path in folder.glob("*.json"):
                if path.is_symlink():
                    raise StorageUnavailable("SYMLINK_DENIED")
                obj = self._read(path)
                if obj:
                    snap = self.read_plan(obj["run_id"])
                    if snap.context.target_date != date or snap.context.phase.value != name or obj["product_sha256"] != snap.product_sha256:
                        raise StorageConflict("CATALOG_MISMATCH")
                    result.append(snap)
        return sorted(result, key=lambda s: (s.generated_at, s.run_id), reverse=True)

    def get_plan(self, date: str, phase: str | None = None, run_id: str | None = None) -> PlanSnapshot | None:
        validate_date(date)
        if run_id:
            snap = self.read_plan(run_id)
            if snap.context.target_date != date or (phase and snap.context.phase.value != phase):
                raise KeyError("PLAN_NOT_FOUND")
            return snap
        phases=[phase] if phase else ["PREOPEN","INTRADAY","NEXT_DAY","RETROSPECTIVE","MANUAL"]
        plans=[]
        for name in phases:
            if name not in {"PREOPEN","INTRADAY","NEXT_DAY","RETROSPECTIVE","MANUAL"}:raise ValueError("PHASE_INVALID")
            pointer=self._read(self._path("pointers",date,name))
            if pointer:
                snapshot=self.read_plan(pointer["run_id"])
                if snapshot.product_sha256!=pointer.get("product_sha256") or snapshot.context.target_date!=date or snapshot.context.phase.value!=name:
                    raise StorageConflict("POINTER_READBACK_MISMATCH")
                plans.append(snapshot)
        return max(plans,key=lambda p:(p.generated_at,p.run_id)) if plans else None

    def find_reusable(self, date: str, phase: str, signature: str) -> PlanSnapshot | None:
        return next((p for p in self.list_plans(date, phase) if p.changes.get("fingerprint") == signature
                     and not any(l.state.value=="FAILED" or any(r.get("failure_code") for r in l.rows) for l in p.lanes)), None)

    def save_review(self, review: ReviewSummary) -> None:
        plan = self.read_plan(review.plan_run_id)
        if plan.context.target_date != review.target_date:
            raise StorageConflict("REVIEW_DATE_MISMATCH")
        with self.lock("review:" + review.plan_run_id):
            self._write(self._path("reviews", review.target_date, _key(review.plan_run_id)), review.model_dump(mode="json"), immutable=True)

    def get_review(self, date: str, run_id: str) -> ReviewSummary | None:
        validate_date(date)
        obj = self._read(self._path("reviews", date, _key(run_id)))
        return ReviewSummary.model_validate(obj) if obj else None

    def cursor(self, key: str) -> dict[str, Any] | None:
        return self._read(self._path("cursors", _key(key)))

    def set_cursor(self, key: str, value: dict[str, Any]) -> None:
        with self.lock("cursor:" + key):
            self._write(self._path("cursors", _key(key)), value, immutable=False)

    def recover_orphan_attempts(self, active_ids: set[str] | None = None) -> int:
        """Only mark interrupted when no live owner PID is observable.

        A reused PID is possible; the conservative response is to block duplicate
        execution, not to assert a task finished or start another model call.
        """
        active_ids = active_ids or set()
        root = self.root / "attempts"
        if not root.exists():
            return 0
        count = 0
        for path in root.glob("*.json"):
            if path.is_symlink():
                raise StorageUnavailable("SYMLINK_DENIED")
            obj = self._read(path)
            if (obj and obj.get("state") in (JobState.QUEUED, JobState.RUNNING)
                    and obj.get("job_id") not in active_ids):
                owner = next((r.get("pid") for r in obj.get("execution_refs", [])
                              if isinstance(r, dict) and r.get("kind") == "host"), None)
                if isinstance(owner,int) and self._pid_alive(owner):
                    continue
                item = self._job_from_obj(obj)
                item.state = JobState.INTERRUPTED
                item.failure_code = "PROCESS_IDENTITY_UNVERIFIED"
                item.retryable = True
                item.failed_steps = list(dict.fromkeys([*item.failed_steps, item.step]))
                self.save_job(item)
                count += 1
        return count

    def save_checkpoint(self, job_id: str, step: str, payload: dict[str, Any]) -> None:
        with self.lock(f"checkpoint:{job_id}:{step}"):
            limit = _PLAN_READ_LIMIT if step == "PUBLISH" else _DEFAULT_READ_LIMIT
            self._write(self._path("checkpoints", _key(job_id), _key(step)), payload,
                        immutable=True, collision_read_limit=limit)

    def load_checkpoint(self, job_id: str, step: str) -> dict[str, Any] | None:
        limits = {"PUBLISH": _PLAN_READ_LIMIT, "LOAD_INPUTS": _INPUT_READ_LIMIT}
        limit = limits.get(step, _DEFAULT_READ_LIMIT)
        return self._read(self._path("checkpoints", _key(job_id), _key(step)), max_bytes=limit)

    def load_input(self, input_sha: str) -> dict[str, Any] | None:
        raw = self._read_content(self._content_path("input_snapshots", input_sha))
        return self._decode_input(raw, input_sha) if raw is not None else None

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # unknown owner: do not assume it is safe to duplicate

    def active_claim(self, scope: str) -> JobRecord | None:
        """Caller holds submission lock; checks persisted active owner."""
        key = hashlib.sha256(scope.encode()).hexdigest()
        claim = self._read(self._path("claims", key))
        if not claim or not claim.get("job_id"):
            return None
        obj = self._read(self._path("attempts", _key(claim["job_id"])))
        if obj is None or obj.get("state") not in (JobState.QUEUED, JobState.RUNNING):
            return None
        current = self._job_from_obj(obj)
        if not self._pid_alive(claim.get("pid", -1)):
            current.state = JobState.INTERRUPTED
            current.failure_code = "PROCESS_IDENTITY_UNVERIFIED"
            current.retryable = True
            self.save_job(current)
            return None
        return current

    def set_claim(self, scope: str, job_id: str | None) -> None:
        key = hashlib.sha256(scope.encode()).hexdigest()
        self._write(self._path("claims", key), {"job_id":job_id, "pid":os.getpid() if job_id else None},immutable=False)

