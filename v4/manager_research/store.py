"""Atomic, date and input keyed storage for V4 manager research."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from threading import RLock
from typing import Any, Iterable, Mapping, Sequence

from .contracts import ContractError, canonical_json, strict_trade_date


class StoreError(RuntimeError):
    pass


class StoreConflict(StoreError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_component(value: str, name: str) -> str:
    if not isinstance(value, str) or not value or "/" in value or "\\" in value or value in {".", ".."}:
        raise StoreError(f"invalid {name}")
    return value


class ManagerResearchStore:
    """Own research state below one explicit state root.

    There is intentionally no ``current`` pointer.  A product is addressed by
    target date and the exact stage input identity, so a late response for a
    different date cannot overwrite the selected date's result.
    """

    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser()
        self.jobs_root = self.root / "jobs"
        self.products_root = self.root / "products"
        self.receipts_root = self.root / "receipts"
        self._lock = RLock()
        for directory in (self.jobs_root, self.products_root, self.receipts_root):
            directory.mkdir(parents=True, exist_ok=True)

    def _job_path(self, job_id: str) -> Path:
        return self.jobs_root / f"{_safe_component(job_id, 'job_id')}.json"

    def _product_path(self, target_trade_date: str, input_identity: str) -> Path:
        date_text = strict_trade_date(target_trade_date)
        return self.products_root / date_text / f"{_safe_component(input_identity, 'input_identity')}.json"

    def _receipt_path(self, target_trade_date: str, job_id: str) -> Path:
        date_text = strict_trade_date(target_trade_date)
        return self.receipts_root / date_text / f"{_safe_component(job_id, 'job_id')}.json"

    @staticmethod
    def _read(path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise StoreError(f"cannot read store object: {path}") from exc
        if not isinstance(value, dict):
            raise StoreError(f"store object must be an object: {path}")
        return value

    @staticmethod
    def _write_atomic(path: Path, value: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = canonical_json(dict(value))
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        except BaseException:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise

    def read_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._read(self._job_path(job_id))

    def write_job(self, job: Mapping[str, Any]) -> dict[str, Any]:
        job_id = _safe_component(str(job.get("job_id", "")), "job_id")
        with self._lock:
            value = dict(job)
            value.setdefault("updated_at", _now())
            self._write_atomic(self._job_path(job_id), value)
            return value

    def read_product(self, target_trade_date: str, input_identity: str) -> dict[str, Any] | None:
        with self._lock:
            return self._read(self._product_path(target_trade_date, input_identity))

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
        """Read one exact legacy product whose input identity was re-bound.

        The V4 input identity gained explicit stage-status evidence after the
        first cache was written.  A legacy product can therefore be reused
        only when its old identity and the persisted product metadata still
        prove the same date, stage, market, source artifact, row count and
        candidate order.  This method scans one date directory only; it never
        searches another date or a ``current`` pointer, and it performs no
        migration write.
        """

        date_text = strict_trade_date(target_trade_date)
        legacy_identity = _safe_component(legacy_input_identity, "legacy_input_identity")
        if not isinstance(input_row_count, int) or isinstance(input_row_count, bool) or input_row_count < 1:
            raise StoreError("input_row_count must be a positive integer")
        if not isinstance(stage_id, str) or not stage_id.strip():
            raise StoreError("stage_id must be a non-empty string")
        if not isinstance(market, str) or not market.strip():
            raise StoreError("market must be a non-empty string")
        expected_rows = list(normalized_rows)
        if len(expected_rows) != input_row_count:
            raise StoreError("normalized row count does not match input_row_count")

        def expected_key(row: Mapping[str, Any]) -> tuple[Any, Any, Any, Any]:
            return (
                row.get("code"),
                row.get("stage_rank"),
                row.get("name"),
                row.get("source_last_bar_time"),
            )

        expected_keys = [expected_key(row) for row in expected_rows]
        if any(not isinstance(key[0], str) or not key[0] for key in expected_keys):
            raise StoreError("normalized rows must contain candidate codes")
        if len({key[0] for key in expected_keys}) != len(expected_keys):
            raise StoreError("normalized rows contain duplicate candidate codes")

        date_root = self.products_root / date_text
        with self._lock:
            if not date_root.is_dir():
                return None
            for path in sorted(date_root.glob("*.json")):
                if path.stem != legacy_identity:
                    continue
                candidate = self._read(path)
                if candidate is None:
                    continue
                if (
                    candidate.get("target_trade_date") != date_text
                    or candidate.get("stage_id") != stage_id
                    or candidate.get("market") != market
                    or candidate.get("input_identity") != legacy_identity
                    or candidate.get("input_source_sha256") != input_source_sha256
                    or candidate.get("input_row_count") != input_row_count
                ):
                    continue
                rows = candidate.get("rows")
                if not isinstance(rows, list) or len(rows) != input_row_count:
                    continue
                candidate_keys: list[tuple[Any, Any, Any, Any]] = []
                valid_rows = True
                for row in rows:
                    if not isinstance(row, Mapping):
                        valid_rows = False
                        break
                    # Legacy products predate the nested row-date field, so
                    # missing values remain compatible.  When either field is
                    # persisted, however, it is part of the evidence bound to
                    # this exact product date.  Do not let a top-level date
                    # mask stale material from another trading day.
                    if "target_trade_date" in row and row.get("target_trade_date") != date_text:
                        valid_rows = False
                        break
                    observation = row.get("observation")
                    observation_map = observation if isinstance(observation, Mapping) else {}
                    if (
                        isinstance(observation, Mapping)
                        and "target_trade_date" in observation
                        and observation.get("target_trade_date") != date_text
                    ):
                        valid_rows = False
                        break
                    candidate_keys.append(
                        (
                            row.get("code"),
                            observation_map.get("stage_rank", row.get("stage_rank")),
                            row.get("name"),
                            observation_map.get("source_last_bar_time", row.get("source_last_bar_time")),
                        )
                    )
                if valid_rows and candidate_keys == expected_keys:
                    return candidate
            return None

    def write_product(self, product: Mapping[str, Any]) -> dict[str, Any]:
        date_text = strict_trade_date(product.get("target_trade_date"))
        input_identity = _safe_component(str(product.get("input_identity", "")), "input_identity")
        path = self._product_path(date_text, input_identity)
        with self._lock:
            prior = self._read(path)
            value = dict(product)
            if prior is not None and canonical_json(prior) != canonical_json(value):
                raise StoreConflict(f"product identity already contains different data: {date_text}/{input_identity}")
            if prior is None:
                self._write_atomic(path, value)
                return value
            return prior

    def replace_product(self, product: Mapping[str, Any]) -> dict[str, Any]:
        """Replace one exact input product during an explicit retry.

        The path remains immutable with respect to date and input identity;
        only a caller that has already requested a retry reaches this method.
        """

        date_text = strict_trade_date(product.get("target_trade_date"))
        input_identity = _safe_component(str(product.get("input_identity", "")), "input_identity")
        path = self._product_path(date_text, input_identity)
        with self._lock:
            value = dict(product)
            self._write_atomic(path, value)
            return value

    def write_receipt(self, target_trade_date: str, job_id: str, receipt: Mapping[str, Any]) -> dict[str, Any]:
        strict_trade_date(target_trade_date)
        _safe_component(job_id, "job_id")
        with self._lock:
            value = dict(receipt)
            self._write_atomic(self._receipt_path(target_trade_date, job_id), value)
            return value

    def read_receipt(self, target_trade_date: str, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._read(self._receipt_path(target_trade_date, job_id))

    def list_jobs(self, target_trade_date: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            paths: Iterable[Path]
            if target_trade_date is None:
                paths = self.jobs_root.glob("*.json")
            else:
                date_text = strict_trade_date(target_trade_date)
                paths = self.jobs_root.glob("*.json")
            result = []
            for path in sorted(paths):
                item = self._read(path)
                if item is not None and (target_trade_date is None or item.get("target_trade_date") == date_text):
                    result.append(item)
            return result
