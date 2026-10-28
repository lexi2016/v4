"""Read-only, source-tagged union view over the audited HK B/C snapshots.

The adapter preserves C rows for overlapping keys and adds only B-only rows.
It never writes market data, derives features, or enables scoring.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Optional, Sequence


NUMERIC_FIELDS = ("open", "high", "low", "close", "amount", "trade")
B_COLUMNS = ("code", "date", "open", "high", "low", "close", "trade", "amount")
C_KEY_COLUMNS = ("code_norm", "trade_date")
C_RECONCILE_COLUMNS = ("code_norm", "trade_date", *NUMERIC_FIELDS)
DEFAULT_BATCH_SIZE = 65_536
MAX_QUERY_LIMIT = 1_000
DEFAULT_RTOL = 1e-6
DEFAULT_ATOL = 1e-6


class HKResearchHistoryError(RuntimeError):
    """Base error for an invalid descriptor or unusable source snapshot."""


class SourceIdentityError(HKResearchHistoryError):
    """A source file no longer matches its pinned descriptor identity."""


class SourceSchemaError(HKResearchHistoryError):
    """A source Parquet schema does not match the descriptor contract."""


class DuplicateKeyError(HKResearchHistoryError):
    """A source has more than one row for a normalized symbol/date key."""


class InvalidKeyError(HKResearchHistoryError):
    """A source row or query contains a malformed symbol/date key."""


class QueryValidationError(ValueError):
    """A query is invalid or would exceed the bounded result contract."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def source_descriptor_sha256(source_descriptor: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(source_descriptor)).hexdigest()


def _canonical_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return [type(value).__name__, value]
    if isinstance(value, float):
        if math.isnan(value):
            return ["float", "nan"]
        if math.isinf(value):
            return ["float", "+inf" if value > 0 else "-inf"]
        return ["float", value.hex()]
    if isinstance(value, (date, datetime)):
        return [type(value).__name__, value.isoformat()]
    if hasattr(value, "as_py"):
        return _canonical_scalar(value.as_py())
    raise TypeError("unsupported source scalar type: " + type(value).__name__)


def _row_digest(row: Mapping[str, Any], columns: Sequence[str]) -> str:
    canonical = [[name, _canonical_scalar(row.get(name))] for name in columns]
    return hashlib.sha256(_canonical_json(canonical)).hexdigest()


def _update_digest(accumulator: Any, row_digest: str) -> None:
    accumulator.update(bytes.fromhex(row_digest))


def _read_file_identity(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise SourceIdentityError("source is missing, non-regular, or symlinked")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
            size += len(block)
    return {"path": str(path), "size_bytes": size, "sha256": digest.hexdigest()}


def _read_stable_json_bytes(path: Path) -> tuple[bytes, dict[str, Any]]:
    """Read one regular, non-symlink file and reject in-place replacement."""
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise SourceIdentityError("owner metadata must be a regular non-symlink file")
        raw = path.read_bytes()
        after = path.lstat()
    except OSError as exc:
        raise SourceIdentityError("unable to read owner metadata") from exc
    if (
        before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or len(raw) != after.st_size
    ):
        raise SourceIdentityError("owner metadata changed during read")
    return raw, {
        "path": str(path),
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def normalize_symbol(value: Any) -> int:
    """Normalize HK.00001, 00001.HK, or 1 to the five-digit numeric code."""
    if value is None or isinstance(value, bool):
        raise InvalidKeyError("invalid HK symbol")
    text = str(value).strip().upper()
    if text.startswith("HK."):
        text = text[3:]
    elif text.endswith(".HK"):
        text = text[:-3]
    if not text or not text.isdigit():
        raise InvalidKeyError("invalid HK symbol")
    code = int(text)
    if code < 1 or code > 99_999:
        raise InvalidKeyError("HK symbol is outside the supported code range")
    return code


def normalize_date(value: Any) -> int:
    """Normalize YYYYMMDD, YYYY-MM-DD, or an integer YYYYMMDD date."""
    if value is None or isinstance(value, bool):
        raise InvalidKeyError("invalid HK trade date")
    if isinstance(value, (date, datetime)):
        text = value.strftime("%Y%m%d")
    elif isinstance(value, int):
        text = str(value)
    elif isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            text = text.replace("-", "")
    else:
        raise InvalidKeyError("invalid HK trade date")
    if not re.fullmatch(r"\d{8}", text):
        raise InvalidKeyError("trade date must be YYYYMMDD")
    try:
        date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError as exc:
        raise InvalidKeyError("trade date is not a calendar date") from exc
    return int(text)


def _packed_key(symbol: Any, trade_date: Any) -> int:
    return normalize_date(trade_date) * 100_000 + normalize_symbol(symbol)


def _key_text(key: int) -> dict[str, str]:
    trade_date, code = divmod(key, 100_000)
    return {"symbol": "HK." + str(code).zfill(5), "date": str(trade_date).zfill(8)}


def _pyarrow():
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - depends on installed runtime
        raise HKResearchHistoryError("PyArrow is required to read HK history") from exc
    return pq


def _iter_rows(path: Path, columns: Sequence[str], batch_size: int = DEFAULT_BATCH_SIZE):
    parquet = _pyarrow().ParquetFile(str(path))
    for batch in parquet.iter_batches(batch_size=batch_size, columns=list(columns)):
        yield from batch.to_pylist()


def _is_null(value: Any) -> bool:
    return value is None


def _numeric_equal(left: Any, right: Any, rtol: float, atol: float) -> bool:
    if _is_null(left) or _is_null(right):
        return _is_null(left) and _is_null(right)
    try:
        left_num = float(left)
        right_num = float(right)
    except (TypeError, ValueError, OverflowError):
        return left == right
    if math.isnan(left_num) or math.isnan(right_num):
        return math.isnan(left_num) and math.isnan(right_num)
    if math.isinf(left_num) or math.isinf(right_num):
        return left_num == right_num
    return math.isclose(left_num, right_num, rel_tol=rtol, abs_tol=atol)


def _safe_output_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "as_py"):
        return _safe_output_value(value.as_py())
    return value


class HKResearchHistory:
    """Verified, read-only union view configured by one source descriptor."""

    def __init__(
        self,
        source_descriptor: Mapping[str, Any],
        descriptor_sha256: Optional[str] = None,
    ) -> None:
        self.descriptor = dict(source_descriptor)
        actual_descriptor_sha = source_descriptor_sha256(self.descriptor)
        if descriptor_sha256 is not None and descriptor_sha256 != actual_descriptor_sha:
            raise SourceIdentityError("source descriptor SHA256 does not match")
        self.descriptor_sha256 = actual_descriptor_sha
        self._validate_descriptor()

    @classmethod
    def from_path(cls, descriptor_path: os.PathLike[str] | str) -> "HKResearchHistory":
        path = Path(descriptor_path)
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SourceIdentityError("unable to read source descriptor") from exc
        descriptor = document.get("source_descriptor", document)
        claimed_sha = document.get("descriptor_sha256")
        if not isinstance(descriptor, dict):
            raise SourceIdentityError("source descriptor must be an object")
        return cls(descriptor, claimed_sha)

    def _validate_descriptor(self) -> None:
        if self.descriptor.get("schema_version") != 1:
            raise SourceSchemaError("unsupported source descriptor schema")
        if self.descriptor.get("market") != "HK":
            raise SourceSchemaError("descriptor market must be HK")
        sources = self.descriptor.get("sources")
        if not isinstance(sources, dict) or not all(name in sources for name in ("B", "C")):
            raise SourceSchemaError("descriptor must define B and C sources")
        for name in ("B", "C"):
            source = sources[name]
            if not isinstance(source, dict):
                raise SourceSchemaError(name + " source descriptor must be an object")
            if not isinstance(source.get("path"), str) or not source.get("path"):
                raise SourceSchemaError(name + " source path is required")
            if not re.fullmatch(r"[0-9a-f]{64}", str(source.get("sha256", ""))):
                raise SourceSchemaError(name + " source SHA256 is required")
            if not isinstance(source.get("size_bytes"), int) or source["size_bytes"] < 0:
                raise SourceSchemaError(name + " source size is required")
            if not isinstance(source.get("row_count"), int) or source["row_count"] < 0:
                raise SourceSchemaError(name + " source row_count is required")
            expected_columns = source.get("columns")
            required = list(B_COLUMNS) if name == "B" else list(C_KEY_COLUMNS) + list(NUMERIC_FIELDS)
            if (
                not isinstance(expected_columns, list)
                or len(expected_columns) != len(set(expected_columns))
                or (name == "B" and expected_columns != required)
                or (name == "C" and not set(required).issubset(expected_columns))
            ):
                raise SourceSchemaError(name + " source columns do not match the adapter contract")
        c_manifest = sources["C"].get("manifest")
        if c_manifest is not None:
            if not isinstance(c_manifest, dict):
                raise SourceSchemaError("C manifest identity must be an object")
            if not isinstance(c_manifest.get("path"), str) or not re.fullmatch(
                r"[0-9a-f]{64}", str(c_manifest.get("sha256", ""))
            ):
                raise SourceSchemaError("C manifest path and SHA256 are required")

    def _source(self, name: str) -> dict[str, Any]:
        return self.descriptor["sources"][name]

    def verify_inputs(self) -> dict[str, Any]:
        """Hash all data inputs and the optional C manifest before reading."""
        identity: dict[str, Any] = {}
        for name in ("B", "C"):
            source = self._source(name)
            actual = _read_file_identity(Path(source["path"]))
            if actual["size_bytes"] != source["size_bytes"] or actual["sha256"] != source["sha256"]:
                raise SourceIdentityError(name + " source identity differs from descriptor")
            identity[name] = actual
        manifest = self._source("C").get("manifest")
        if manifest:
            actual = _read_file_identity(Path(manifest["path"]))
            if actual["sha256"] != manifest["sha256"]:
                raise SourceIdentityError("C manifest identity differs from descriptor")
            if "size_bytes" in manifest and actual["size_bytes"] != manifest["size_bytes"]:
                raise SourceIdentityError("C manifest size differs from descriptor")
            identity["C_manifest"] = actual
        return identity

    def _check_parquet_schema(self, name: str) -> None:
        source = self._source(name)
        parquet = _pyarrow().ParquetFile(source["path"])
        actual_columns = parquet.schema_arrow.names
        if actual_columns != source["columns"]:
            raise SourceSchemaError(name + " Parquet columns differ from descriptor")
        if parquet.metadata.num_rows != source["row_count"]:
            raise SourceSchemaError(name + " Parquet row count differs from descriptor")

    def _row_key(self, source_name: str, row: Mapping[str, Any]) -> int:
        if source_name == "B":
            return _packed_key(row.get("code"), row.get("date"))
        return _packed_key(row.get("code_norm"), row.get("trade_date"))

    def reconcile(self) -> dict[str, Any]:
        """Compute a deterministic partition report without exporting raw rows."""
        before = self.verify_inputs()
        self._check_parquet_schema("B")
        self._check_parquet_schema("C")
        rtol = float(self.descriptor.get("rtol", DEFAULT_RTOL))
        atol = float(self.descriptor.get("atol", DEFAULT_ATOL))

        c_numeric: dict[int, tuple[tuple[Any, ...], str]] = {}
        c_digest = hashlib.sha256()
        c_invalid = hashlib.sha256()
        c_rows = 0
        c_invalid_count = 0
        for row in _iter_rows(Path(self._source("C")["path"]), C_RECONCILE_COLUMNS):
            c_rows += 1
            try:
                key = self._row_key("C", row)
            except InvalidKeyError:
                c_invalid_count += 1
                _update_digest(c_invalid, _row_digest(row, C_RECONCILE_COLUMNS))
                continue
            if key in c_numeric:
                raise DuplicateKeyError("duplicate normalized key in C source")
            values = tuple(row.get(field) for field in NUMERIC_FIELDS)
            digest = _row_digest(row, C_RECONCILE_COLUMNS)
            c_numeric[key] = (values, digest)
            _update_digest(c_digest, digest)

        b_counts = {
            "B-only": 0,
            "raw_matching_overlap": 0,
            "raw_conflicting_overlap": 0,
            "invalid_key": 0,
        }
        b_digests = {category: hashlib.sha256() for category in b_counts}
        b_seen: set[int] = set()
        b_rows = 0
        field_mismatch_counts = {field: 0 for field in NUMERIC_FIELDS}
        known_pattern_counts = {"20260706": 0, "20260722": 0}
        canaries: dict[str, Any] = {}
        b_columns = self._source("B")["columns"]

        for row in _iter_rows(Path(self._source("B")["path"]), b_columns):
            b_rows += 1
            row_hash = _row_digest(row, b_columns)
            try:
                key = self._row_key("B", row)
            except InvalidKeyError:
                category = "invalid_key"
                b_counts[category] += 1
                _update_digest(b_digests[category], row_hash)
                continue
            if key in b_seen:
                raise DuplicateKeyError("duplicate normalized key in B source")
            b_seen.add(key)
            if key not in c_numeric:
                category = "B-only"
                b_counts[category] += 1
                _update_digest(b_digests[category], row_hash)
                if category not in canaries:
                    canaries[category] = {**_key_text(key), "b_row_sha256": row_hash}
                continue

            c_values, c_row_hash = c_numeric[key]
            b_values = tuple(row.get(field) for field in NUMERIC_FIELDS)
            mismatches = [
                field for field, b_value, c_value in zip(NUMERIC_FIELDS, b_values, c_values)
                if not _numeric_equal(b_value, c_value, rtol, atol)
            ]
            category = "raw_conflicting_overlap" if mismatches else "raw_matching_overlap"
            b_counts[category] += 1
            _update_digest(b_digests[category], row_hash)
            for field in mismatches:
                field_mismatch_counts[field] += 1
            key_info = {
                **_key_text(key),
                "b_row_sha256": row_hash,
                "c_row_sha256": c_row_hash,
            }
            if category not in canaries:
                canaries[category] = {**key_info, "differing_fields": mismatches}
            trade_i = NUMERIC_FIELDS.index("trade")
            amount_i = NUMERIC_FIELDS.index("amount")
            trade_b, trade_c = b_values[trade_i], c_values[trade_i]
            amount_b, amount_c = b_values[amount_i], c_values[amount_i]
            if (
                category == "raw_conflicting_overlap"
                and str(_key_text(key)["date"]) in known_pattern_counts
                and trade_b is not None and amount_b is not None
                and trade_c is not None and amount_c is not None
                and float(trade_b) > 0 and float(amount_b) > 0
                and float(trade_c) == 0 and float(amount_c) == 0
            ):
                key_date = _key_text(key)["date"]
                known_pattern_counts[key_date] += 1
                if "known_zero_in_c" not in canaries:
                    canaries["known_zero_in_c"] = {
                        **key_info,
                        "differing_fields": mismatches,
                        "pattern": "B trade and amount positive; C trade and amount zero",
                    }

        if b_rows != self._source("B")["row_count"] or c_rows != self._source("C")["row_count"]:
            raise SourceSchemaError("observed Parquet rows differ from descriptor")

        c_only_digest = hashlib.sha256()
        c_only_count = 0
        for key, (_, digest) in c_numeric.items():
            if key not in b_seen:
                c_only_count += 1
                _update_digest(c_only_digest, digest)

        after = self.verify_inputs()
        if before != after:
            raise SourceIdentityError("source identity changed during reconciliation")

        common = b_counts["raw_matching_overlap"] + b_counts["raw_conflicting_overlap"]
        union_count = len(b_seen) + c_only_count
        observed_targets = {
            "B_rows": b_rows,
            "common_keys": common,
            "B_only_keys": b_counts["B-only"],
            "C_only_keys": c_only_count,
            "union_keys": union_count,
            "B_invalid_keys": b_counts["invalid_key"],
            "C_invalid_keys": c_invalid_count,
        }
        target_values = self.descriptor.get("acceptance_targets", {})
        if not isinstance(target_values, dict):
            raise SourceSchemaError("acceptance_targets must be an object")
        count_checks = {
            key: observed_targets.get(key) == value
            for key, value in target_values.items()
        }
        mismatch_targets = self.descriptor.get("overlap_field_mismatch_targets", {})
        if not isinstance(mismatch_targets, dict):
            raise SourceSchemaError("overlap_field_mismatch_targets must be an object")
        mismatch_checks = {
            field: field_mismatch_counts.get(field) == value
            for field, value in mismatch_targets.items()
        }
        passed = (
            all(count_checks.values())
            and all(mismatch_checks.values())
            and b_counts["invalid_key"] == 0
            and c_invalid_count == 0
        )
        result = {
            "status": "PASS_CANARY" if passed else "FAIL_CANARY",
            "descriptor_sha256": self.descriptor_sha256,
            "source_identity_before": before,
            "source_identity_after": after,
            "row_counts": {
                "B": b_rows,
                "C": c_rows,
                "B_classified_rows": sum(b_counts.values()),
                "C_valid_keys": len(c_numeric),
                "B_valid_keys": len(b_seen),
            },
            "key_partition": {
                "B_only": b_counts["B-only"],
                "raw_matching_overlap": b_counts["raw_matching_overlap"],
                "raw_conflicting_overlap": b_counts["raw_conflicting_overlap"],
                "common": common,
                "C_only": c_only_count,
                "union_keys": union_count,
            },
            "classification_counts": b_counts,
            "duplicate_key_counts": {"B": 0, "C": 0},
            "invalid_key_counts": {"B": b_counts["invalid_key"], "C": c_invalid_count},
            "field_mismatch_counts": field_mismatch_counts,
            "known_conflict_pattern_counts": known_pattern_counts,
            "overlap_field_mismatch_checks": mismatch_checks,
            "digests": {
                "algorithm": "sha256 over source-order row SHA256 bytes; B uses raw 8 fields and C uses normalized key plus six raw numeric fields",
                "B_classifications": {
                    category: digest.hexdigest() for category, digest in b_digests.items()
                },
                "C_valid_rows": c_digest.hexdigest(),
                "C_invalid_rows": c_invalid.hexdigest(),
                "C_only_rows": c_only_digest.hexdigest(),
            },
            "canaries": canaries,
            "target_checks": count_checks,
            "raw_market_rows_exported": False,
            "semantic_or_unit_equivalence_claimed": False,
            "scoring_allowed": False,
            "research_only": True,
        }
        if target_values:
            result["acceptance_targets_sha256"] = source_descriptor_sha256(target_values)
        return result

    def query_union(
        self,
        symbol: Any,
        start_date: Any,
        end_date: Any,
        *,
        limit: int = 100,
        offset: int = 0,
        _policy: Any = None,
        required_fields: Sequence[str] = NUMERIC_FIELDS,
    ) -> dict[str, Any]:
        """Return a bounded symbol/date slice; C owns overlap, B adds B-only."""
        code = normalize_symbol(symbol)
        start = normalize_date(start_date)
        end = normalize_date(end_date)
        if start > end:
            raise QueryValidationError("start_date must be on or before end_date")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_QUERY_LIMIT:
            raise QueryValidationError("limit must be between 1 and 1000")
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 1_000_000:
            raise QueryValidationError("offset must be between 0 and 1000000")

        before = self.verify_inputs()
        self._check_parquet_schema("B")
        self._check_parquet_schema("C")
        selected_c: dict[int, dict[str, Any]] = {}
        selected_b: dict[int, dict[str, Any]] = {}
        seen_c: set[int] = set()
        seen_b: set[int] = set()
        c_rows = 0
        b_rows = 0
        c_columns = self._source("C")["columns"]
        b_columns = self._source("B")["columns"]
        for row in _iter_rows(Path(self._source("C")["path"]), c_columns):
            c_rows += 1
            key = self._row_key("C", row)
            if key in seen_c:
                raise DuplicateKeyError("duplicate normalized key in C source")
            seen_c.add(key)
            trade_date, key_code = divmod(key, 100_000)
            if key_code != code or not start <= trade_date <= end:
                continue
            selected_c[key] = row
        for row in _iter_rows(Path(self._source("B")["path"]), b_columns):
            b_rows += 1
            key = self._row_key("B", row)
            if key in seen_b:
                raise DuplicateKeyError("duplicate normalized key in B source")
            seen_b.add(key)
            trade_date, key_code = divmod(key, 100_000)
            if key_code != code or not start <= trade_date <= end:
                continue
            selected_b[key] = row
        if b_rows != self._source("B")["row_count"] or c_rows != self._source("C")["row_count"]:
            raise SourceSchemaError("observed Parquet rows differ from descriptor")

        result_rows: list[dict[str, Any]] = []
        rtol = float(self.descriptor.get("rtol", DEFAULT_RTOL))
        atol = float(self.descriptor.get("atol", DEFAULT_ATOL))
        for key, c_row in selected_c.items():
            b_row = selected_b.get(key)
            if b_row is None:
                overlap = "C_only"
                different: list[str] = []
            else:
                different = [
                    field for field in NUMERIC_FIELDS
                    if not _numeric_equal(b_row.get(field), c_row.get(field), rtol, atol)
                ]
                overlap = "raw_conflicting_overlap" if different else "raw_matching_overlap"
            result_rows.append(self._tagged_row(
                "C", key, c_row, overlap,
                conflict_fields=different,
                counterpart_row=b_row,
            ))
        for key, b_row in selected_b.items():
            if key not in selected_c:
                result_rows.append(self._tagged_row("B", key, b_row, "B-only"))
        result_rows.sort(key=lambda row: (row["date"], row["symbol"]))
        quarantine = []
        if _policy is not None:
            usable = []
            for row in result_rows:
                held = _policy.held_fields(row["symbol"], row["date"], required_fields, source=row["source"])
                if held:
                    quarantine.append(dict(symbol=row["symbol"], date=row["date"], fields=held,
                                           reason="HK_HISTORY_FIELD_QUARANTINED", row_sha256=row["row_sha256"]))
                    continue
                row["raw_fields"] = _policy.effective_values(row['symbol'],row['date'],
                    {field:row['raw_fields'].get(field) for field in required_fields},source=row['source'])
                row["counterpart"] = None  # original B variants require explicit audit mode
                row["usable_fields"] = list(required_fields)
                decision = _policy.decisions.get((row["symbol"], row["date"]))
                row["field_admission"] = {
                    field: (_policy.field_admission(row['symbol'],row['date'],field) if row['source']=='C'
                            else "B_ONLY_RESEARCH_NO_SCORING_ADMISSION")
                    for field in required_fields
                }
                if any(value=='CORRECTED_TDX_RETROSPECTIVE_CHANNEL' for value in row['field_admission'].values()):
                    row['correction_source'] = dict(channel='TDX_PROTOCOL_PARAM1_FIXED',
                        rule=_policy.manifest['correction_rule_version'],ledger_sha256=_policy.corrections_sha256,
                        original_C_row_sha256=row['row_sha256'],historical_PIT='UNKNOWN',adjustment_name='UNKNOWN')
                usable.append(row)
            result_rows = usable
        page = result_rows[offset:offset + limit]
        after = self.verify_inputs()
        if before != after:
            raise SourceIdentityError("source identity changed during query")
        return {
            "rows": page,
            "total_matching_rows": len(result_rows),
            "limit": limit,
            "offset": offset,
            "descriptor_sha256": self.descriptor_sha256,
            "research_only": True,
            "scoring_allowed": False,
            "quarantine_count": len(quarantine),
            "quarantine_reasons": quarantine[:MAX_QUERY_LIMIT],
        }

    def _tagged_row(
        self,
        source_name: str,
        key: int,
        row: Mapping[str, Any],
        overlap: str,
        *,
        conflict_fields: Sequence[str] = (),
        counterpart_row: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        source = self._source(source_name)
        raw_fields = {name: _safe_output_value(value) for name, value in row.items()}
        row_columns = B_COLUMNS if source_name == "B" else C_RECONCILE_COLUMNS
        counterpart_source = "B" if source_name == "C" and counterpart_row is not None else None
        counterpart_digest = (
            _row_digest(counterpart_row, B_COLUMNS)
            if counterpart_source == "B" and counterpart_row is not None
            else None
        )
        counterpart_source_sha = (
            self._source(counterpart_source)["sha256"]
            if counterpart_source is not None
            else None
        )
        field_difference_mask = (
            {field: field in conflict_fields for field in NUMERIC_FIELDS}
            if counterpart_row is not None
            else {}
        )
        field_hold_reasons = {
            field: (
                "RAW_VALUES_DIFFER; source units, currency, adjustment basis, and PIT semantics are unresolved"
            )
            for field in conflict_fields
        }
        counterpart_projection = None
        if counterpart_row is not None and counterpart_source is not None:
            counterpart_columns = B_COLUMNS if counterpart_source == "B" else C_RECONCILE_COLUMNS
            counterpart_projection = {
                "source": counterpart_source,
                "source_sha256": counterpart_source_sha,
                "row_sha256": counterpart_digest,
                "raw_fields": {
                    name: _safe_output_value(value)
                    for name, value in counterpart_row.items()
                },
            }
            # The counterpart hash is over the full source contract even when
            # a panel has extra display/provenance columns.
            counterpart_projection["row_sha256"] = _row_digest(
                counterpart_row, counterpart_columns
            )
        if source_name == "C" and counterpart_source == "B":
            selection_reason = "C_OWNER_PRECEDENCE_ONLY; LEGACY_BASELINE_NOT_VERIFIED"
        elif source_name == "B":
            selection_reason = "B_ROW_ADDED_ONLY_WHEN_ABSENT_FROM_C_OWNER"
        else:
            selection_reason = "EXISTING_C_OWNER_ROW; NO_B_COUNTERPART"
        disposition = (
            "UNRESOLVED_SOURCE_SEMANTICS"
            if overlap == "raw_conflicting_overlap"
            else "NO_RAW_FIELD_CONFLICT_OR_C_ONLY"
        )
        return {
            **_key_text(key),
            "source": source_name,
            "source_sha256": source["sha256"],
            "row_sha256": _row_digest(row, row_columns),
            "overlap_status": overlap,
            "counterpart": counterpart_projection,
            "conflict_metadata": {
                "status": overlap,
                "disposition": disposition,
                "selection_reason": selection_reason,
                "comparison_basis": "raw_numeric_values_with_frozen_rtol_atol",
                "compared_fields": list(NUMERIC_FIELDS) if counterpart_row is not None else [],
                "differing_fields": list(conflict_fields),
                "field_difference_mask": field_difference_mask,
                "field_hold_reasons": field_hold_reasons,
                "comparison_rtol": float(self.descriptor.get("rtol", DEFAULT_RTOL)),
                "comparison_atol": float(self.descriptor.get("atol", DEFAULT_ATOL)),
                "selected_raw_source": source_name,
                "counterpart_source": counterpart_source,
                "counterpart_source_sha256": counterpart_source_sha,
                "counterpart_row_sha256": counterpart_digest,
                "semantic_resolution": "UNRESOLVED",
                "canonical_scoring_admission": "NO_CANONICAL_SCORING_ADMISSION",
            },
            "raw_fields": raw_fields,
            "units_status": "UNKNOWN",
            "adjustment_basis_status": "UNKNOWN",
            "currency_basis_status": "UNKNOWN",
            "pit_safety_status": "UNKNOWN",
            "research_only": True,
            "scoring_allowed": False,
        }


class OwnedHKResearchHistory:
    """Resolve the current HK panel from its existing shared-data owner per query."""

    DESCRIPTOR_FILENAME = "research_history.json"
    POINTER_RELATIVE = "panel_latest.json"
    ASSET_SCHEMA_VERSION = "v3_shared_data.hk_0_2_panel_asset.v2"

    def __init__(self, owner_root: os.PathLike[str] | str) -> None:
        candidate = Path(owner_root)
        try:
            root_stat = candidate.lstat()
            if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
                raise SourceIdentityError("HK owner root must be a real directory")
            self.owner_root = candidate.resolve(strict=True)
        except OSError as exc:
            raise SourceIdentityError("HK owner root is unavailable") from exc
        if self.owner_root.name != "hk_0_2":
            raise SourceIdentityError("unexpected HK owner asset root")

    @classmethod
    def from_shared_root(cls, shared_root: os.PathLike[str] | str) -> "OwnedHKResearchHistory":
        if shared_root is None:
            raise SourceIdentityError("shared research root is unavailable")
        return cls(Path(shared_root) / "assets" / "hk_0_2")

    def _confined_file(self, relative: Any) -> Path:
        if not isinstance(relative, str) or not relative or "\\" in relative or "\x00" in relative:
            raise SourceIdentityError("owner-relative path is invalid")
        rel = PurePosixPath(relative)
        if rel.is_absolute() or any(part in ("", ".", "..") for part in rel.parts):
            raise SourceIdentityError("owner-relative path escapes the asset root")
        path = self.owner_root
        try:
            for part in rel.parts:
                path = path / part
                if path.is_symlink():
                    raise SourceIdentityError("owner-relative paths may not contain symlinks")
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise SourceIdentityError("owner-relative file is unavailable") from exc
        if not resolved.is_relative_to(self.owner_root):
            raise SourceIdentityError("owner-relative path escapes the asset root")
        if not resolved.is_file():
            raise SourceIdentityError("owner-relative path is not a regular file")
        return resolved

    def _read_descriptor(self) -> tuple[dict[str, Any], str, dict[str, Any]]:
        path = self.owner_root / self.DESCRIPTOR_FILENAME
        raw, identity = _read_stable_json_bytes(path)
        try:
            document = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SourceIdentityError("HK history owner descriptor is invalid JSON") from exc
        if not isinstance(document, dict) or not isinstance(document.get("source_descriptor"), dict):
            raise SourceIdentityError("HK history owner descriptor is malformed")
        descriptor = document["source_descriptor"]
        claimed_sha = document.get("descriptor_sha256")
        actual_sha = source_descriptor_sha256(descriptor)
        if claimed_sha != actual_sha:
            raise SourceIdentityError("HK history owner descriptor SHA256 does not match")
        self._validate_owner_descriptor(descriptor)
        return descriptor, actual_sha, identity

    def _material_identities(self, descriptor: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        """Require every active raw/metadata reference to resolve inside the C owner's materials."""
        material_root = self.owner_root / "research_materials"
        try:
            root_stat = material_root.lstat()
        except OSError as exc:
            raise SourceIdentityError("C-owned research materials are unavailable") from exc
        if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
            raise SourceIdentityError("C-owned research materials must be a real directory")

        references: list[tuple[str, Mapping[str, Any]]] = [
            ("B", descriptor["sources"]["B"]),
            *((str(item["id"]), item) for item in descriptor["metadata_only"]),
        ]
        identities: dict[str, dict[str, Any]] = {}
        owner_device = self.owner_root.stat().st_dev
        for ref_id, reference in references:
            raw_path = reference.get("path")
            if not isinstance(raw_path, str):
                raise SourceIdentityError(f"{ref_id} material path is invalid")
            candidate = Path(raw_path)
            try:
                relative = candidate.relative_to(material_root)
            except ValueError as exc:
                raise SourceIdentityError(f"{ref_id} material path is outside C-owned research materials") from exc
            if not relative.parts or any(part in ("", ".", "..") for part in relative.parts):
                raise SourceIdentityError(f"{ref_id} material path is invalid")

            current = material_root
            try:
                for part in relative.parts:
                    current = current / part
                    item_stat = current.lstat()
                    if stat.S_ISLNK(item_stat.st_mode):
                        raise SourceIdentityError(f"{ref_id} material path contains a symlink")
                resolved = current.resolve(strict=True)
                item_stat = current.lstat()
            except OSError as exc:
                raise SourceIdentityError(f"{ref_id} material file is unavailable") from exc
            if resolved != current or not resolved.is_relative_to(material_root):
                raise SourceIdentityError(f"{ref_id} material path escapes C-owned research materials")
            if not stat.S_ISREG(item_stat.st_mode) or item_stat.st_size != reference["size_bytes"]:
                raise SourceIdentityError(f"{ref_id} material identity differs from descriptor")
            if item_stat.st_dev != owner_device:
                raise SourceIdentityError(f"{ref_id} material is outside the C owner's volume")
            identities[ref_id] = {
                "path": str(resolved),
                "size_bytes": item_stat.st_size,
                "device": item_stat.st_dev,
                "inode": item_stat.st_ino,
                "mtime_ns": item_stat.st_mtime_ns,
            }
        return identities

    @staticmethod
    def _validate_owner_descriptor(descriptor: Mapping[str, Any]) -> None:
        if descriptor.get("schema_version") != 1 or descriptor.get("market") != "HK":
            raise SourceSchemaError("unsupported HK history owner descriptor")
        owner = descriptor.get("owner")
        if (
            not isinstance(owner, dict)
            or owner.get("asset_id") != "hk_0_2"
            or owner.get("pointer_relative") != OwnedHKResearchHistory.POINTER_RELATIVE
            or owner.get("manifest_relative_field") != "manifest_relative"
            or owner.get("asset_schema_version") != OwnedHKResearchHistory.ASSET_SCHEMA_VERSION
        ):
            raise SourceSchemaError("HK history descriptor does not bind the existing asset owner")
        sources = descriptor.get("sources")
        if not isinstance(sources, dict) or set(sources) != {"B", "C"}:
            raise SourceSchemaError("HK history descriptor must define B and C")
        b_source = sources.get("B")
        c_source = sources.get("C")
        if not isinstance(b_source, dict) or not isinstance(c_source, dict):
            raise SourceSchemaError("HK source descriptors must be objects")
        if (
            not isinstance(b_source.get("path"), str)
            or not Path(b_source["path"]).is_absolute()
            or not re.fullmatch(r"[0-9a-f]{64}", str(b_source.get("sha256", "")))
            or not isinstance(b_source.get("size_bytes"), int)
            or b_source["size_bytes"] < 0
            or not isinstance(b_source.get("row_count"), int)
            or b_source["row_count"] < 0
            or b_source.get("columns") != list(B_COLUMNS)
        ):
            raise SourceSchemaError("B raw-history identity is incomplete")
        if (
            c_source.get("dynamic") is not True
            or c_source.get("owner") != "hk_0_2"
            or "path" in c_source
            or "sha256" in c_source
        ):
            raise SourceSchemaError("C must be resolved dynamically from its existing owner")
        for key in ("rtol", "atol"):
            value = descriptor.get(key, DEFAULT_RTOL if key == "rtol" else DEFAULT_ATOL)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise SourceSchemaError("numeric comparison tolerance is invalid")
        metadata = descriptor.get("metadata_only")
        required_refs = {"A_feature", "A_label", "B_operator_feature", "B_operator_label"}
        if not isinstance(metadata, list) or {item.get("id") for item in metadata if isinstance(item, dict)} != required_refs:
            raise SourceSchemaError("preservation metadata references are incomplete")
        for item in metadata:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("path"), str)
                or not Path(item["path"]).is_absolute()
                or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", "")))
                or not isinstance(item.get("size_bytes"), int)
                or item["size_bytes"] < 0
                or item.get("read_policy") != "METADATA_ONLY"
            ):
                raise SourceSchemaError("preservation metadata reference is invalid")
            item_id = item.get("id")
            if isinstance(item_id, str) and item_id.endswith("label") and item.get("label_values_read") is not False:
                raise SourceSchemaError("label payloads must remain unopened")

    def _capture(self) -> tuple[HKResearchHistory, dict[str, Any]]:
        owner_descriptor, owner_descriptor_sha, owner_descriptor_identity = self._read_descriptor()
        material_identities = self._material_identities(owner_descriptor)
        owner = owner_descriptor["owner"]
        pointer_path = self._confined_file(owner["pointer_relative"])
        pointer_bytes, pointer_identity = _read_stable_json_bytes(pointer_path)
        try:
            pointer_document = json.loads(pointer_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SourceIdentityError("HK panel pointer is invalid JSON") from exc
        manifest_relative = pointer_document.get(owner["manifest_relative_field"]) if isinstance(pointer_document, dict) else None
        manifest_path = self._confined_file(manifest_relative)
        manifest_bytes, manifest_identity = _read_stable_json_bytes(manifest_path)
        try:
            manifest = json.loads(manifest_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SourceIdentityError("current HK panel manifest is invalid JSON") from exc
        if not isinstance(manifest, dict):
            raise SourceSchemaError("current HK panel manifest must be an object")
        if manifest.get("asset_schema_version") != owner["asset_schema_version"]:
            raise SourceSchemaError("current HK panel asset schema is unsupported")
        if (
            manifest.get("research_only") is not True
            or manifest.get("production_allowed") is not False
            or manifest.get("buy_gate_updated") is not False
            or manifest.get("orders_sent") is not False
        ):
            raise SourceSchemaError("current HK panel safety flags do not match the research contract")
        panel_relative = manifest.get("panel_relative")
        panel_path = self._confined_file(panel_relative)
        panel_sha = manifest.get("panel_sha256")
        panel_rows = manifest.get("panel_rows")
        if not re.fullmatch(r"[0-9a-f]{64}", str(panel_sha or "")):
            raise SourceSchemaError("current HK panel SHA256 is invalid")
        if isinstance(panel_rows, bool) or not isinstance(panel_rows, int) or panel_rows < 0:
            raise SourceSchemaError("current HK panel row count is invalid")
        parquet = _pyarrow().ParquetFile(str(panel_path))
        columns = parquet.schema_arrow.names
        required = set(C_KEY_COLUMNS) | set(NUMERIC_FIELDS)
        if len(columns) != len(set(columns)) or not required.issubset(columns):
            raise SourceSchemaError("current HK panel schema is missing raw history fields")
        if parquet.metadata.num_rows != panel_rows:
            raise SourceSchemaError("current HK panel row count differs from its manifest")
        panel_stat = panel_path.stat()
        if not stat.S_ISREG(panel_stat.st_mode):
            raise SourceIdentityError("current HK panel is not a regular file")

        b_source = dict(owner_descriptor["sources"]["B"])
        current_c_source = {
            "path": str(panel_path),
            "size_bytes": panel_stat.st_size,
            "sha256": panel_sha,
            "row_count": panel_rows,
            "columns": columns,
            "manifest": {
                "path": str(manifest_path),
                "sha256": manifest_identity["sha256"],
                "size_bytes": manifest_identity["size_bytes"],
            },
        }
        runtime_descriptor = {
            "schema_version": 1,
            "market": "HK",
            "rtol": owner_descriptor.get("rtol", DEFAULT_RTOL),
            "atol": owner_descriptor.get("atol", DEFAULT_ATOL),
            "sources": {"B": b_source, "C": current_c_source},
        }
        adapter = HKResearchHistory(runtime_descriptor)
        capture = {
            "owner_descriptor_sha256": owner_descriptor_sha,
            "owner_descriptor_file_sha256": owner_descriptor_identity["sha256"],
            "owner_descriptor_file_size_bytes": owner_descriptor_identity["size_bytes"],
            "material_identities": material_identities,
            "pointer_relative": owner["pointer_relative"],
            "pointer_sha256": pointer_identity["sha256"],
            "manifest_relative": manifest_relative,
            "manifest_sha256": manifest_identity["sha256"],
            "panel_sha256": panel_sha,
            "panel_rows": panel_rows,
            "asset_schema_version": owner["asset_schema_version"],
        }
        return adapter, capture

    def _verify_capture_unchanged(self, capture: Mapping[str, Any]) -> None:
        owner_descriptor, descriptor_sha, descriptor_identity = self._read_descriptor()
        if (
            descriptor_sha != capture["owner_descriptor_sha256"]
            or descriptor_identity["sha256"] != capture["owner_descriptor_file_sha256"]
        ):
            raise SourceIdentityError("HK owner descriptor changed during query")
        if self._material_identities(owner_descriptor) != capture["material_identities"]:
            raise SourceIdentityError("HK owner material references changed during query")
        pointer_path = self._confined_file(capture["pointer_relative"])
        _, pointer_identity = _read_stable_json_bytes(pointer_path)
        if pointer_identity["sha256"] != capture["pointer_sha256"]:
            raise SourceIdentityError("HK panel pointer changed during query")
        manifest_path = self._confined_file(capture["manifest_relative"])
        _, manifest_identity = _read_stable_json_bytes(manifest_path)
        if manifest_identity["sha256"] != capture["manifest_sha256"]:
            raise SourceIdentityError("HK panel manifest changed during query")

    def query_union(
        self,
        symbol: Any,
        start_date: Any,
        end_date: Any,
        *,
        limit: int = 100,
        offset: int = 0,
        mode: str = "usable",
        required_fields: Sequence[str] = NUMERIC_FIELDS,
    ) -> dict[str, Any]:
        adapter, capture = self._capture()
        if mode not in ("usable", "audit"):
            raise QueryValidationError("mode must be usable or audit")
        policy = None
        if mode == "usable":
            from upstreams.v3_shared_data.shared_data.hk_history_resolution import ResolutionPolicy, fields
            required_fields = fields(required_fields)
            policy = ResolutionPolicy(self.owner_root)
            policy.check_panel(capture["panel_sha256"])
        result = adapter.query_union(symbol, start_date, end_date, limit=limit, offset=offset,
                                     _policy=policy, required_fields=required_fields)
        result["mode"] = mode
        if policy is not None:
            result["history_resolution_proof"] = policy.proof(required_fields=required_fields,
                start=start_date,end=end_date,consumer="HK_HISTORY_USABLE_SLICE_V1")
        self._verify_capture_unchanged(capture)
        result["owner_snapshot"] = {
            key: capture[key]
            for key in (
                "owner_descriptor_sha256",
                "pointer_relative",
                "pointer_sha256",
                "manifest_relative",
                "manifest_sha256",
                "panel_sha256",
                "panel_rows",
                "asset_schema_version",
            )
        }
        return result
