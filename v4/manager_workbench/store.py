"""Immutable plan/input storage, crash-safe publication and per-key OS locks."""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any, Iterator
from infrastructure.owned_io import SafeRoot

from .contracts import JobRecord, JobState, PlanSnapshot, ReviewSummary, canonical, digest, validate_date


_DEFAULT_READ_LIMIT = 64 * 1024 * 1024
_PLAN_READ_LIMIT = 128 * 1024 * 1024
_INPUT_READ_LIMIT = 128 * 1024 * 1024


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

    def save_input(self, input_sha: str, data: dict[str, Any]) -> None:
        if len(input_sha) != 64 or any(c not in "0123456789abcdef" for c in input_sha):
            raise ValueError("INPUT_SHA_INVALID")
        with self.lock("input:" + input_sha):
            self._write(self._path("input_snapshots", input_sha), data, immutable=True,
                        collision_read_limit=_INPUT_READ_LIMIT)

    def save_input_checkpoint(self, job_id: str, data: dict[str, Any]) -> str:
        """Persist the immutable input body plus the legacy inline resume checkpoint."""
        input_sha = digest(data)
        self.save_input(input_sha, data)
        self.save_checkpoint(job_id, "LOAD_INPUTS", data)
        return input_sha

    def load_input_checkpoint(
        self, job_id: str
    ) -> tuple[dict[str, Any] | None, str | None]:
        """Read the backwards-compatible full JSON LOAD_INPUTS checkpoint."""
        checkpoint = self.load_checkpoint(job_id, "LOAD_INPUTS")
        if checkpoint is None:
            return None, None
        if "context" not in checkpoint or "batches" not in checkpoint:
            raise StorageUnavailable("INPUT_CHECKPOINT_INVALID")
        return checkpoint, digest(checkpoint)

    def save_job(self, job: JobRecord) -> None:
        # Attempts are mutable; successful plans are not.
        with self.lock("job:" + job.job_id):
            self._write(self._path("attempts", _key(job.job_id)), job.model_dump(mode="json"), immutable=False)

    def get_job(self, job_id: str) -> JobRecord | None:
        obj = self._read(self._path("attempts", _key(job_id)))
        return JobRecord.model_validate(obj) if obj is not None else None

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
            item = self.get_job(path.stem)
            if item and item.state in (JobState.QUEUED, JobState.RUNNING) and item.job_id not in active_ids:
                owner = next((r.get("pid") for r in item.execution_refs if r.get("kind") == "host"), None)
                if isinstance(owner,int) and self._pid_alive(owner):
                    continue
                item.state = JobState.INTERRUPTED
                item.failure_code = "PROCESS_IDENTITY_UNVERIFIED"
                item.retryable = True
                item.failed_steps = list(dict.fromkeys([*item.failed_steps, item.step]))
                self.save_job(item)
                count += 1
        return count

    def save_checkpoint(self, job_id: str, step: str, payload: dict[str, Any]) -> None:
        with self.lock(f"checkpoint:{job_id}:{step}"):
            limit = _PLAN_READ_LIMIT if step in {"PUBLISH", "LOAD_INPUTS"} else _DEFAULT_READ_LIMIT
            self._write(self._path("checkpoints", _key(job_id), _key(step)), payload,
                        immutable=True, collision_read_limit=limit)

    def _file_fingerprint(self, path: Path, *, max_bytes: int) -> tuple[int, str, int, int, int, int, int] | None:
        relative = str(path.relative_to(self.root))
        try:
            with self.io.parent(relative) as (parent, name):
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                try:
                    before = os.fstat(fd)
                    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                            or before.st_size < 0 or before.st_size > max_bytes):
                        return None
                    hasher = hashlib.sha256()
                    size = 0
                    while True:
                        chunk = os.read(fd, 1024 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > max_bytes:
                            return None
                        hasher.update(chunk)
                    after = os.fstat(fd)
                    visible = os.stat(name, dir_fd=parent, follow_symlinks=False)
                    identity_before = (before.st_dev, before.st_ino, before.st_size,
                                       before.st_mtime_ns, before.st_ctime_ns)
                    identity_after = (after.st_dev, after.st_ino, after.st_size,
                                      after.st_mtime_ns, after.st_ctime_ns)
                    identity_visible = (visible.st_dev, visible.st_ino, visible.st_size,
                                        visible.st_mtime_ns, visible.st_ctime_ns)
                    if (size != before.st_size or identity_before != identity_after
                            or identity_before != identity_visible):
                        return None
                    return (size, hasher.hexdigest(), before.st_dev, before.st_ino,
                            before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                finally:
                    os.close(fd)
        except FileNotFoundError:
            return None

    def _remove_checkpoint_if_peer(self, job_id: str, step: str, peer: Path, *, max_bytes: int) -> bool:
        with self.lock(f"checkpoint:{job_id}:{step}"):
            checkpoint = self._path("checkpoints", _key(job_id), _key(step))
            checkpoint_fp = self._file_fingerprint(checkpoint, max_bytes=max_bytes)
            peer_fp = self._file_fingerprint(peer, max_bytes=max_bytes)
            if checkpoint_fp is None or peer_fp is None or checkpoint_fp[:2] != peer_fp[:2]:
                return False
            relative = str(checkpoint.relative_to(self.root))
            with self.io.parent(relative) as (parent, name):
                try:
                    visible = os.stat(name, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    return False
                identity = (visible.st_dev, visible.st_ino, visible.st_size,
                            visible.st_mtime_ns, visible.st_ctime_ns)
                expected = checkpoint_fp[2:]
                if not stat.S_ISREG(visible.st_mode) or identity != expected:
                    return False
                peer_relative = str(peer.relative_to(self.root))
                with self.io.parent(peer_relative) as (peer_parent, peer_name):
                    try:
                        peer_visible = os.stat(peer_name, dir_fd=peer_parent, follow_symlinks=False)
                    except FileNotFoundError:
                        return False
                    peer_identity = (peer_visible.st_dev, peer_visible.st_ino,
                                     peer_visible.st_size, peer_visible.st_mtime_ns,
                                     peer_visible.st_ctime_ns)
                    if (not stat.S_ISREG(peer_visible.st_mode)
                            or peer_identity != peer_fp[2:]):
                        return False
                os.unlink(name, dir_fd=parent)
                os.fsync(parent)
                return True

    def remove_input_checkpoint_if_snapshot(self, job_id: str) -> bool:
        """Retire LOAD_INPUTS only when its canonical bytes match its SHA-named snapshot."""
        checkpoint = self._path("checkpoints", _key(job_id), "LOAD_INPUTS")
        fingerprint = self._file_fingerprint(checkpoint, max_bytes=_INPUT_READ_LIMIT)
        if fingerprint is None:
            return False
        peer = self._path("input_snapshots", fingerprint[1])
        return self._remove_checkpoint_if_peer(
            job_id, "LOAD_INPUTS", peer, max_bytes=_INPUT_READ_LIMIT)

    def remove_publish_checkpoint_if_plan(self, job_id: str, date: str, phase: str,
                                          run_id: str) -> bool:
        """Retire PUBLISH only when its canonical bytes equal the durable plan snapshot."""
        validate_date(date)
        key = _key(run_id)
        catalog = self._read(self._path("catalog", date, phase, key))
        if (catalog is None or catalog.get("run_id") != run_id
                or not isinstance(catalog.get("product_sha256"), str)):
            return False
        peer = self._path("snapshots", key)
        return self._remove_checkpoint_if_peer(
            job_id, "PUBLISH", peer, max_bytes=_PLAN_READ_LIMIT)

    def load_checkpoint(self, job_id: str, step: str) -> dict[str, Any] | None:
        limit = _PLAN_READ_LIMIT if step in {"PUBLISH", "LOAD_INPUTS"} else _DEFAULT_READ_LIMIT
        return self._read(self._path("checkpoints", _key(job_id), _key(step)), max_bytes=limit)

    def load_input(self, input_sha: str) -> dict[str, Any] | None:
        return self._read(self._path("input_snapshots", input_sha), max_bytes=_INPUT_READ_LIMIT)

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
        current = self.get_job(claim["job_id"])
        if current is None or current.state not in (JobState.QUEUED, JobState.RUNNING):
            return None
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

