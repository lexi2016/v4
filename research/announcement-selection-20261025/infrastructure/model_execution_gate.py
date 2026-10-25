"""Thin business-state adapter over the unchanged, validated legacy queue gate.

The physical model flock stays at its existing path so unchanged clients retain
mutual exclusion. Only business recovery selection and binding checks are added;
claim, transport invocation and result persistence remain the vendor's code.
"""
from __future__ import annotations

import hashlib
import fcntl
import os
from pathlib import Path
import stat
from typing import Any, Callable, Mapping


class ModelExecutionBindingError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def legacy_model_slot_busy(legacy_queue_root: Path, model_id: str) -> bool:
    """Read-only probe: never create, replace, unlink or migrate the legacy lock."""
    lock = Path(legacy_queue_root) / 'locks' / (
        'model-' + hashlib.sha256(model_id.encode()).hexdigest() + '.lock')
    fd = -1
    try:
        if any(path.is_symlink() for path in (lock, *lock.parents)):
            return True
        fd = os.open(lock, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return True
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except OSError:
        return True
    finally:
        if fd >= 0:
            os.close(fd)


def frozen_file_guard(files: Mapping[Path, str]) -> Callable[[], None]:
    frozen = {Path(path).absolute(): digest for path, digest in files.items()}
    if not frozen:
        raise ModelExecutionBindingError('MODEL_EXECUTION_BINDING_EMPTY')

    def verify() -> None:
        for path, digest in frozen.items():
            try:
                if (any(part.is_symlink() for part in (path, *path.parents))
                        or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
                    raise ModelExecutionBindingError('MODEL_EXECUTION_BINDING_CHANGED')
            except OSError as exc:
                raise ModelExecutionBindingError('MODEL_EXECUTION_BINDING_CHANGED') from exc
    return verify


def create_business_queue(queue_module: Any, state_root: Path, queue_id: str, model_id: str, *,
                          legacy_queue_root: Path, binding_guard: Callable[[], None],
                          recover_running: bool = True, max_attempts: int = 1) -> Any:
    """Retain the old physical slot and filter business/allowed keys before recovery."""
    lock = Path(legacy_queue_root).absolute() / 'locks' / (
        'model-' + hashlib.sha256(model_id.encode()).hexdigest() + '.lock')
    try:
        if any(path.is_symlink() for path in (lock, *lock.parents)):
            raise ModelExecutionBindingError('LEGACY_MODEL_GATE_UNAVAILABLE')
        original = lock.stat()
        if not stat.S_ISREG(original.st_mode):
            raise ModelExecutionBindingError('LEGACY_MODEL_GATE_UNAVAILABLE')
    except OSError as exc:
        raise ModelExecutionBindingError('LEGACY_MODEL_GATE_UNAVAILABLE') from exc

    def verify() -> None:
        try:
            current = lock.stat()
            if (lock.is_symlink() or not stat.S_ISREG(current.st_mode)
                    or (current.st_dev, current.st_ino) != (original.st_dev, original.st_ino)):
                raise ModelExecutionBindingError('LEGACY_MODEL_GATE_CHANGED')
        except OSError as exc:
            raise ModelExecutionBindingError('LEGACY_MODEL_GATE_CHANGED') from exc
        binding_guard()

    verify()

    class BusinessQueue(queue_module.SerialAnnouncementQueue):
        def _save_state(self, state):
            # Vendor recovery saves its view. Keep every foreign record and the
            # complete event ledger in that save, without rewriting its fields.
            full = getattr(self, '_recovery_full_state', None)
            return super()._save_state(full if full is not None else state)

        def _recover_running_locked(self, state):
            self.binding_guard()
            if not recover_running:
                return []
            allowed = getattr(self, '_claim_allowed_keys', None)
            selected = {key: item for key, item in state['jobs'].items()
                        if item.get('queue_id') == self.queue_id
                        and item.get('model_id') == self.model_id
                        and (allowed is None or key in allowed)}
            # All item/event objects stay shared with the complete state; only
            # the recovery iterator is restricted before vendor recovery runs.
            self._recovery_full_state = state
            try:
                return super()._recover_running_locked({**state, 'jobs': selected})
            finally:
                self._recovery_full_state = None

        def _claim_next_locked(self, state, allowed_keys=None):
            self.binding_guard()  # Own the physical model slot; recheck after wait.
            # Select both the business and explicit allowed keys before recovery
            # and claim. An unselected RUNNING item is never a recovery mandate.
            selected_keys = {key for key, item in state['jobs'].items()
                             if item.get('queue_id') == self.queue_id
                             and item.get('model_id') == self.model_id
                             and (allowed_keys is None or key in allowed_keys)}
            self._claim_allowed_keys = selected_keys
            try:
                return super()._claim_next_locked(state, selected_keys)
            finally:
                self._claim_allowed_keys = None

        def run_next(self, executor, validator, *, wait_for_model_slot=True, idempotency_keys=None):
            self.binding_guard()  # Reject frozen drift before any claim/attempt.
            def execute(job):
                self.binding_guard()  # Last check immediately before dispatch.
                return executor(job)
            return super().run_next(execute, validator, wait_for_model_slot=wait_for_model_slot,
                                    idempotency_keys=idempotency_keys)

        def recover_interrupted(self, *, wait_for_model_slot=True):
            self.binding_guard()
            # Vendor acquires this exact legacy flock before calling the filtered
            # recovery hook, so a healthy old or new owner is never cancelled.
            return super().recover_interrupted(wait_for_model_slot=wait_for_model_slot)

    queue = BusinessQueue(state_root, queue_id, model_id, max_attempts=max_attempts, max_body_bytes=None)
    queue._model_lock_path = lock
    queue.binding_guard = verify
    return queue
