"""Exact-input local research storage with fenced, atomic result publication.

A commit is ONE atomic JSON document containing a product, terminal jobs and
receipts with a checksum. Legacy objects remain readable; GET never migrates
files. A receipt mirror alone is not a committed result. New/old writers must
not share a root during cutover. Use a new local sandbox root for this version.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import re
from pathlib import Path
from threading import RLock, local
from typing import Any, Callable, Iterator, Mapping, Sequence
from infrastructure.owned_io import LockAcquireTimeout, SafeRoot
from .contracts import canonical_json, sha256_json, strict_trade_date
from .cache_contract import validate_cached_product
from .safety import assert_manager_safe_tree
_COMMIT_SCHEMA = 'v4.manager_research.commit.v1'
# Exact workspace-plan documents only; the shared SafeRoot default stays 64 MiB.
# Smallest 64 MiB quantum covering Issue #24's 333,005,411-byte legacy plan.
# This is also the writer's hard limit, not an automatic growth policy.
WORKSPACE_PLAN_MAX_BYTES = 320 * 1024 * 1024
_ACTIVE = {'QUEUED', 'RUNNING'}
_TERMINAL = {'READY', 'PARTIAL_WITH_ROWS', 'CANNOT_CONFIRM', 'FAILED', 'CANCELLED'}


class StoreError(RuntimeError):
    pass


class StoreConflict(StoreError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _safe_component(value: str, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 180
        or '/' in value
        or '\\' in value
        or '\x00' in value
        or value in {'.', '..'}
    ):
        raise StoreError(f'invalid {name}')
    return value


def _workspace_plan_file(relative: str) -> tuple[str, str] | None:
    parts = relative.split('/')
    if (len(parts) == 3 and parts[0] == 'workspace_plans'
            and re.fullmatch(r'[0-9]{8}', parts[1])
            and re.fullmatch(r'(?:latest|[0-9a-f]{32})\.json', parts[2])):
        return strict_trade_date(parts[1]), parts[2]
    return None


def _attempt(job: Mapping[str, Any]) -> tuple[int, Any]:
    value = job.get('attempt', 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise StoreError('JOB_ATTEMPT_INVALID')
    return (value, job.get('generation'))


class ManagerResearchStore:

    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser()
        self.jobs_root = self.root / 'jobs'
        self.products_root = self.root / 'products'
        self.receipts_root = self.root / 'receipts'
        self._lock = RLock()
        self._held = local()
        self._io = SafeRoot(self.root)
        for directory in ('jobs', 'products', 'receipts'):
            self._io.ensure_directory(directory)

    def _job_path(self, job_id: str) -> Path:
        return self.jobs_root / f"{_safe_component(job_id, 'job_id')}.json"

    def _product_path(self, target_trade_date: str, input_identity: str) -> Path:
        return self.products_root / strict_trade_date(target_trade_date) / f"{_safe_component(input_identity, 'input_identity')}.json"

    def _receipt_path(self, target_trade_date: str, job_id: str) -> Path:
        return self.receipts_root / strict_trade_date(target_trade_date) / f"{_safe_component(job_id, 'job_id')}.json"

    def _commit_path(self, date: str, identity: str) -> Path:
        return self.root / '.commits' / strict_trade_date(date) / f"{_safe_component(identity, 'input_identity')}.json"

    @contextmanager
    def _transaction(self, date: str, identity: str) -> Iterator[None]:
        key = f"{strict_trade_date(date)}-{_safe_component(identity, 'input_identity')}"
        # RLock serializes this instance; kernel lock serializes other instances
        # and processes. Reentrancy is per-thread and only for this exact key.
        with self._lock:
            held = getattr(self._held, 'keys', set())
            if key in held:
                yield
                return
            try:
                with self._io.kernel_lock(f'.locks/{key}.mutex'):
                    self._held.keys = held | {key}
                    try:
                        yield
                    finally:
                        self._held.keys = held
            except LockAcquireTimeout as exc:
                raise StoreConflict('STORE_KEY_LOCK_TIMEOUT') from exc

    def _read(self, path: Path) -> dict[str, Any] | None:
        try:
            relative = str(path.relative_to(self.root))
            if _workspace_plan_file(relative) is not None:
                raw = self._io.read_bytes(relative, max_bytes=WORKSPACE_PLAN_MAX_BYTES)
            else:
                raw = self._io.read_bytes(relative)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            raise StoreError('STORE_READ_BOUNDARY_FAILED') from exc
        try:
            value = json.loads(raw.decode('utf-8'))
            del raw  # Do not retain a second large plan buffer during validation.
            if not isinstance(value, dict):
                raise ValueError('not an object')
            assert_manager_safe_tree(value)
            canonical_json(value)
            return value
        except (UnicodeError, ValueError) as exc:
            raise StoreError('STORE_OBJECT_INVALID') from exc

    def _write_atomic(self, path: Path, value: Mapping[str, Any]) -> None:
        assert_manager_safe_tree(value)
        relative = str(path.relative_to(self.root))
        plan_file = _workspace_plan_file(relative)
        raw = canonical_json(dict(value))
        if plan_file is None:
            self._io.write_bytes(relative, raw)
            return
        if len(raw) > WORKSPACE_PLAN_MAX_BYTES:
            raise StoreError(f'WORKSPACE_PLAN_TOO_LARGE:{len(raw)}>{WORKSPACE_PLAN_MAX_BYTES}')
        # SafeRoot's atomic no-replace publication preserves every existing run.
        # latest.json remains the original same-date atomic pointer-document.
        try:
            self._io.write_bytes(relative, raw, require_absent=plan_file[1] != 'latest.json')
        except FileExistsError as exc:
            raise StoreConflict('WORKSPACE_PLAN_RUN_ALREADY_EXISTS') from exc

    def _read_commit(self, date: str, identity: str) -> dict[str, Any] | None:
        commit = self._read(self._commit_path(date, identity))
        if commit is None:
            return None
        content = {k: v for k, v in commit.items() if k != 'sha256'}
        if (
            commit.get('schema_version') != _COMMIT_SCHEMA
            or commit.get('sha256') != sha256_json(content)
            or commit.get('target_trade_date') != date
            or commit.get('input_identity') != identity
        ):
            raise StoreError('COMMIT_INTEGRITY_FAILED')
        product = commit.get('product')
        if (
            not isinstance(product, dict)
            or product.get('target_trade_date') != date
            or product.get('input_identity') != identity
        ):
            raise StoreError('COMMIT_PRODUCT_IDENTITY_FAILED')
        jobs, receipts = (commit.get('jobs'), commit.get('receipts'))
        if (
            not isinstance(jobs, dict)
            or not isinstance(receipts, dict)
            or not jobs
            or set(jobs) != set(receipts)
        ):
            raise StoreError('COMMIT_RECEIPT_SET_INVALID')
        for key, job in jobs.items():
            receipt = receipts[key]
            if not isinstance(job, dict) or not isinstance(receipt, dict):
                raise StoreError('COMMIT_MEMBER_INVALID')
            for item in (job, receipt):
                if (
                    item.get('job_id') != key
                    or item.get('target_trade_date') != date
                    or item.get('input_identity') != identity
                ):
                    raise StoreError('COMMIT_MEMBER_IDENTITY_FAILED')
            if job.get('status') not in _TERMINAL - {'CANCELLED'}:
                raise StoreError('COMMIT_TERMINAL_STATE_INVALID')
        return commit

    def read_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._read(self._job_path(job_id))
            if job is None:
                return None
            if job.get('job_id') != job_id:
                raise StoreError('JOB_IDENTITY_MISMATCH')
            date, identity = (job.get('target_trade_date'), job.get('input_identity'))
            if date and identity:
                commit = self._read_commit(date, identity)
                final = commit.get('jobs', {}).get(job_id) if commit else None
                if final is not None and _attempt(final) == _attempt(job):
                    return dict(final)
            return job

    def write_job(self, job: Mapping[str, Any]) -> dict[str, Any]:
        value = dict(job)
        job_id = _safe_component(str(value.get('job_id', '')), 'job_id')
        date = strict_trade_date(value.get('target_trade_date'))
        identity = _safe_component(str(value.get('input_identity', '')), 'input_identity')
        assert_manager_safe_tree(value)
        with self._transaction(date, identity):
            prior = self.read_job(job_id)
            if (
                prior is not None
                and (prior.get('target_trade_date') != date or prior.get('input_identity') != identity)
            ):
                raise StoreConflict('JOB_EXACT_INPUT_CONFLICT')
            if prior is not None:
                if _attempt(prior) != _attempt(value):
                    raise StoreConflict('JOB_GENERATION_SUPERSEDED')
                if prior.get('status') in _TERMINAL:
                    if canonical_json(prior) == canonical_json(value):
                        return prior
                    raise StoreConflict('JOB_ALREADY_TERMINAL')
            value.setdefault('updated_at', _now())
            self._write_atomic(self._job_path(job_id), value)
            return value

    def admit_job(self, job: Mapping[str, Any]) -> dict[str, Any]:
        """Compare-and-admit a fresh generation; no implicit orphan takeover."""
        value = dict(job)
        date = strict_trade_date(value.get('target_trade_date'))
        identity = _safe_component(str(value.get('input_identity', '')), 'input_identity')
        with self._transaction(date, identity):
            prior = self.read_job(value['job_id'])
            if (
                prior is not None
                and (prior.get('target_trade_date') != date or prior.get('input_identity') != identity)
            ):
                raise StoreConflict('JOB_EXACT_INPUT_CONFLICT')
            if prior is not None and prior.get('status') in _ACTIVE:
                raise StoreConflict('JOB_OWNER_UNCONFIRMED')
            expected = _attempt(prior)[0] + 1 if prior else 1
            if (
                _attempt(value)[0] != expected
                or not isinstance(value.get('generation'), str)
                or not value['generation']
                or value.get('status') != 'QUEUED'
            ):
                raise StoreConflict('JOB_ADMISSION_CONFLICT')
            self._write_atomic(self._job_path(value['job_id']), value)
            return value

    def cancel_job(self, job_id: str, target_trade_date: str | None=None) -> dict[str, Any] | None:
        job = self.read_job(job_id)
        if (
            job is None
            or (target_trade_date is not None and job.get('target_trade_date') != target_trade_date)
        ):
            return None
        with self._transaction(job['target_trade_date'], job['input_identity']):
            current = self.read_job(job_id)
            if current is None or current.get('status') in _TERMINAL:
                return current
            current.update(
                status='CANCELLED',
                error='CANCELLED_BY_REQUEST',
                can_retry=True,
                updated_at=_now(),
                completed_at=_now(),
            )
            self._write_atomic(self._job_path(job_id), current)
            return current

    def read_product(self, target_trade_date: str, input_identity: str) -> dict[str, Any] | None:
        with self._lock:
            commit = self._read_commit(target_trade_date, input_identity)
            product = dict(commit['product']) if commit else self._read(self._product_path(
                target_trade_date,
                input_identity,
            ))
            if (
                product is not None
                and (product.get('target_trade_date') != target_trade_date or product.get('input_identity') != input_identity)
            ):
                raise StoreError('PRODUCT_IDENTITY_MISMATCH')
            return product

    def read_compatible_product(
        self,
        target_trade_date: str,
        *,
        legacy_input_identity: str,
        input_source_sha256: str | None,
        input_row_count: int,
        stage_id: str,
        market: str,
        normalized_rows: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any] | None:
        date = strict_trade_date(target_trade_date)
        candidate = self.read_product(date, legacy_input_identity)
        if candidate is None:
            return None
        expected = dict(
            target_trade_date=date,
            input_identity=legacy_input_identity,
            input_source_sha256=input_source_sha256,
            input_row_count=input_row_count,
            stage_id=stage_id,
            market=market,
            rows=list(normalized_rows),
        )
        try:
            validate_cached_product(candidate, expected)
        except ValueError:
            return None
        return candidate

    def write_product(self, product: Mapping[str, Any]) -> dict[str, Any]:
        assert_manager_safe_tree(product)
        date = strict_trade_date(product.get('target_trade_date'))
        identity = _safe_component(str(product.get('input_identity', '')), 'input_identity')
        with self._transaction(date, identity):
            prior = self.read_product(date, identity)
            if prior is not None:
                if canonical_json(prior) != canonical_json(dict(product)):
                    raise StoreConflict('PRODUCT_IDENTITY_CONFLICT')
                return prior
            self._write_atomic(self._product_path(date, identity), product)
            return dict(product)

    def replace_product(self, product: Mapping[str, Any]) -> dict[str, Any]:
        """Legacy explicit replacement only; committed results require commit_result."""
        assert_manager_safe_tree(product)
        date = strict_trade_date(product.get('target_trade_date'))
        identity = _safe_component(str(product.get('input_identity', '')), 'input_identity')
        with self._transaction(date, identity):
            if self._read_commit(date, identity) is not None:
                raise StoreConflict('COMMITTED_UPDATE_REQUIRES_NEW_ATTEMPT')
            self._write_atomic(self._product_path(date, identity), product)
            return dict(product)

    def write_receipt(
        self,
        target_trade_date: str,
        job_id: str,
        receipt: Mapping[str, Any],
    ) -> dict[str, Any]:
        # Compatibility mirror. commit_result is the only result-visibility gate.
        with self._lock:
            self._write_atomic(self._receipt_path(target_trade_date, job_id), receipt)
            return dict(receipt)

    def read_receipt(self, target_trade_date: str, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._read(self._job_path(job_id))
            if job is not None:
                if job.get('target_trade_date') != target_trade_date:
                    return None
                identity = job.get('input_identity')
                if identity:
                    commit = self._read_commit(target_trade_date, identity)
                    if (
                        commit
                        and job_id in commit['receipts']
                        and _attempt(commit['jobs'][job_id]) == _attempt(job)
                    ):
                        return dict(commit['receipts'][job_id])
                    if job.get('generation'):
                        return None
            return self._read(self._receipt_path(target_trade_date, job_id))

    def commit_result(
        self,
        job: Mapping[str, Any],
        product: Mapping[str, Any],
        receipt: Mapping[str, Any],
        *,
        merge: Callable[[dict[str, Any]], dict[str, Any]] | None=None,
    ) -> dict[str, Any]:
        """Fence attempt/cancel and atomically publish product+terminal state+receipt.

        ``merge`` is pure and short: it receives the latest product *inside* the
        input-key critical section. It must never perform source collection.
        """
        date = strict_trade_date(job.get('target_trade_date'))
        identity = _safe_component(str(job.get('input_identity', '')), 'input_identity')
        job_id = _safe_component(str(job.get('job_id', '')), 'job_id')
        with self._transaction(date, identity):

            def check_owner() -> None:
                current = self.read_job(job_id)
                if (
                    current is None
                    or current.get('target_trade_date') != date
                    or current.get('input_identity') != identity
                    or _attempt(current) != _attempt(job)
                    or current.get('status') not in _ACTIVE
                ):
                    raise StoreConflict('JOB_COMMIT_FENCE_REJECTED')
            check_owner()
            if job.get('status') not in _TERMINAL - {'CANCELLED'}:
                raise StoreConflict('JOB_RESULT_NOT_PUBLISHABLE')
            latest = self.read_product(date, identity)
            if merge is not None:
                if latest is None:
                    raise StoreConflict('FINANCIAL_PRODUCT_MISSING')
                product = merge(latest)
            if job.get('mode') != 'EVENT_REFRESH' and product.get('status') != job.get('status'):
                raise StoreConflict('PRODUCT_JOB_STATUS_MISMATCH')
            for item in (product, receipt):
                if item.get('target_trade_date') != date or item.get('input_identity') != identity:
                    raise StoreConflict('COMMIT_IDENTITY_MISMATCH')
                assert_manager_safe_tree(item)
            if receipt.get('job_id') != job_id:
                raise StoreConflict('RECEIPT_JOB_MISMATCH')
            prior = self._read_commit(date, identity)
            jobs = dict(prior['jobs']) if prior else {}
            receipts = dict(prior['receipts']) if prior else {}
            jobs[job_id] = dict(job)
            receipts[job_id] = dict(receipt)
            commit = dict(
                schema_version=_COMMIT_SCHEMA,
                target_trade_date=date,
                input_identity=identity,
                revision=int(prior['revision']) + 1 if prior else 1,
                product=dict(product),
                jobs=jobs,
                receipts=receipts,
            )
            commit['sha256'] = sha256_json(commit)
            self.write_receipt(date, job_id, receipt)
            # also fences reentrant fault-injection/cancel callbacks
            check_owner()
            self._write_atomic(self._commit_path(date, identity), commit)
            return dict(product)

    def list_jobs(self, target_trade_date: str | None=None) -> list[dict[str, Any]]:
        date = strict_trade_date(target_trade_date) if target_trade_date is not None else None
        result = []
        for name in self._io.files('jobs'):
            item = self.read_job(name[:-5])
            if item is not None and (date is None or item.get('target_trade_date') == date):
                result.append(item)
        return result
