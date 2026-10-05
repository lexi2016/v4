"""Frozen FMLA04/v1.9.2 candidate materialization and read-only contract.

The model implementation is kept in the local V4 oracle bundle and is bound
to the three frozen origin SHAs.  The generated CSV is published by the
existing single-writer immutable store so V3 and V3.5 can consume one run id
and artifact SHA.
"""
from __future__ import annotations

import csv
import datetime as _datetime
import math
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .allowlist import AllowlistRegistry, SourceSpec
from .consumer import VerifiedRun, read_verified_latest
from .hashing import sha256_file, sha256_json
from .paths import validate_date
from .store import SafeRootStore, StoreError
from . import v192_oracle_bundle


V192_LEGACY_ROLE = "A_SHARE_V192_PREMARKET_POOL"
V192_PREVIOUS_ROLE = "A_SHARE_V192_PREMARKET_POOL_V2"
V192_ROLE = "A_SHARE_V192_PREMARKET_POOL_V3"
V192_SELECTOR_VERSION = "v1.9.2_FMLA04_TRACE_AWARE_WAIT_SPLIT"
V192_SOURCE_KIND = "FMLA04_V192_CANONICAL_CANDIDATE"
V192_CANDIDATE_ROLE = "TEST_ONLY_BUY_CANDIDATE"
V192_RANK_BOUNDARY = "RANK_FOR_REVIEW_ONLY_NOT_BUY_PRIORITY"
V192_STAGE_ID = "D1_PREMARKET"
PREMARKET_SCORE_FORMULA = "V3_PREMARKET_POOL_V1"
CANONICAL_FORMULA_SOURCE = "computed_main_chart_formula_20260515"
_V192_SAFETY_FLAG_KEYS = ("production_allowed", "buy_gate_updated", "orders_sent")
V192_ENTRY_FIELDS = (
    "gold_brick_context",
    "brick_resonance_context",
    "brick_buy",
    "brick_buy1_low_absorb",
    "brick_buy2_attack",
    "primary_buy_signal",
    "secondary_buy_signal",
)
V192_INTERMEDIATE_FIELDS = (
    "brick_resonance1",
    "brick_resonance2",
    "brick_resonance",
)

# These fields are part of the selector-ready panel contract used by the
# frozen V3 premarket observation pool.  They are retained in the shared
# artifact so a consumer can use the materialized oracle score without
# treating v1.9.2 ``final_score`` or display metadata as a proxy.
_PREMARKET_SOURCE_FIELDS = (
    "primary_buy_signal",
    "secondary_buy_signal",
    "gold_brick_context",
    "brick_resonance_context",
    "brick_buy",
    "brick_buy1_low_absorb",
    "brick_buy2_attack",
    "brick_resonance1",
    "brick_resonance2",
    "brick_resonance",
    "ref_hold_score",
    "B1",
    "B2",
    "B3",
    "BG",
    "amount",
    "pct_chg",
    "route_context",
    "brick_context",
    "formula_source",
    "field_contract_version",
)
_PREMARKET_ARTIFACT_FIELDS = (
    *_PREMARKET_SOURCE_FIELDS,
    "premarket_pool_score",
    "premarket_score_formula",
    "premarket_score_source",
    "premarket_signal_policy",
)


class _V192ManifestStore(SafeRootStore):
    """Shared store writer that freezes V3 identity on the run manifest.

    ``SafeRootStore`` already emits the receipt role and safety flags, while
    its generic manifest schema intentionally has no artifact-role fields.
    This narrow subclass adds the V1.9.2 contract before the inherited writer
    hashes the manifest and receipt, keeping the run trio immutable thereafter.
    """

    def __init__(
        self,
        root: Path,
        *,
        role: str,
        allowlist: AllowlistRegistry | None = None,
    ) -> None:
        super().__init__(root, allowlist=allowlist)
        self._manifest_role = role

    def _write_json(self, destination: Path, value: Mapping[str, Any]) -> None:
        payload = dict(value)
        if destination.name == "manifest.json":
            additions = {
                "role": self._manifest_role,
                **{key: False for key in _V192_SAFETY_FLAG_KEYS},
            }
            # ``SafeRootStore.replay_file`` hashes its local manifest mapping
            # after calling ``_write_json``; update that mapping as well as the
            # serialized payload so the receipt binds the emitted bytes.
            if isinstance(value, dict):
                value.update(additions)
            payload.update(additions)
        super()._write_json(destination, payload)


FROZEN_ORACLE_SHA256S: dict[str, str] = dict(v192_oracle_bundle.ORACLE_ORIGIN_SHA256S)

_FIELDS = (
    "trade_date",
    "signal_date",
    "target_date",
    "bar_time",
    "candidate_id",
    "ts_code",
    "stock_code",
    "stock_name",
    "source_kind",
    "selector_version",
    "candidate_role",
    "multi_head_final_role",
    "entry_pool",
    "review_rank_v19",
    "final_score",
    "multi_entry_score",
    "multi_entry_risk_adjusted_score",
    "fresh_b2_entry_score",
    "continuation_entry_score",
    "hold_through_main_wave_score",
    "risk_chase_score",
    "rank_usage_boundary",
    "formal_recommendation_allowed",
    "test_only_notice",
    "source_trace",
    *_PREMARKET_ARTIFACT_FIELDS,
)


@dataclass(frozen=True)
class VerifiedV192Pool:
    run: VerifiedRun
    rows: tuple[dict[str, str], ...]

    @property
    def production_allowed(self) -> bool:
        return bool(self.run.receipt["production_allowed"])

    @property
    def buy_gate_updated(self) -> bool:
        return bool(self.run.receipt["buy_gate_updated"])

    @property
    def orders_sent(self) -> bool:
        return bool(self.run.receipt["orders_sent"])


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().upper() in {"1", "1.0", "TRUE", "YES", "Y", "是"}


def _entry_contract_issues(row: Mapping[str, Any]) -> list[str]:
    required = (*V192_ENTRY_FIELDS, *V192_INTERMEDIATE_FIELDS, "formula_source")
    missing = [field for field in required if field not in row]
    issues = [f"v1.9.2 entry fields missing: {','.join(missing)}"] if missing else []
    if str(row.get("formula_source") or "").strip() != CANONICAL_FORMULA_SOURCE:
        issues.append("v1.9.2 formula_source must be computed_main_chart_formula_20260515")
    gold = str(row.get("gold_brick_context") or "").strip()
    if gold not in {"none", "old_gold_candidate"}:
        issues.append("v1.9.2 gold_brick_context must be none/old_gold_candidate")
    numeric_fields = [field for field in (*V192_ENTRY_FIELDS, *V192_INTERMEDIATE_FIELDS) if field != "gold_brick_context"]
    for field in numeric_fields:
        if field not in row:
            continue
        value = row.get(field)
        if _is_empty(value):
            issues.append(f"v1.9.2 signal field missing: {field}")
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            issues.append(f"v1.9.2 signal field invalid: {field}")
            continue
        if numeric not in (0.0, 1.0):
            issues.append(f"v1.9.2 signal field invalid: {field}")
    return issues


def _falsey(value: Any) -> bool:
    if isinstance(value, bool):
        return not value
    if value is None:
        return True
    return str(value).strip().upper() in {"", "0", "0.0", "FALSE", "NO", "N", "否"}


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool) or type(value).__name__ == "bool_":
        # CSV is the existing artifact boundary.  Use the same 0/1 form that
        # the entry-field contract accepts after a runner returns bools.
        return "1" if bool(value) else "0"
    if isinstance(value, float) and math.isnan(value):
        return ""
    try:
        import pandas as pd

        if pd.isna(value):
            return ""
    except (ImportError, TypeError, ValueError):
        pass
    return str(value)


def _is_empty(value: Any) -> bool:
    """Treat null, NaN, and whitespace-only cells as missing at the boundary."""
    return _cell(value).strip() == ""


def _missing_premarket_source_fields(source: Mapping[str, Any]) -> list[str]:
    """Apply the frozen field contract, not an unconditional context nonempty rule.

    a_formula_field_contract_v0.csv: route_context is context_only and permits
    blank_allowed_when_no_b_route. Only an actual blank string is exempt; the
    physical column, null/NaN, B1/B2/B3 explanations and all other gates remain.
    BG and independent primary/secondary/brick entries do not create a B route.
    This function never changes values, scores, ranks or the candidate universe.
    """
    blank_without_b = (
        "route_context" in source
        and isinstance(source["route_context"], str)
        and source["route_context"] == ""
        and not any(_truthy(source.get(field)) for field in ("B1", "B2", "B3"))
    )
    return [
        field for field in _PREMARKET_SOURCE_FIELDS
        if field not in source or (
            _is_empty(source[field])
            and not (field == "route_context" and blank_without_b)
        )
    ]


def _number(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _premarket_score_fields(
    source: Mapping[str, Any], *, derive_from_b_fields: bool
) -> dict[str, Any]:
    """Materialize the legacy V3 premarket score from explicit panel fields.

    The selector panel occasionally carries all-zero explicit primary/
    secondary signals while B1/B2/B3/BG are populated.  The old producer
    then derives the two selector signals from those B-fields before applying
    the frozen score formula.  This is a single shared implementation for
    both V3.5 and other consumers; no selector metadata is consulted.
    """

    values = {field: source.get(field) for field in _PREMARKET_SOURCE_FIELDS}
    primary_present = "primary_buy_signal" in source
    secondary_present = "secondary_buy_signal" in source
    primary = _number(values["primary_buy_signal"])
    secondary = _number(values["secondary_buy_signal"])
    b1 = _number(values["B1"])
    b2 = _number(values["B2"])
    b3 = _number(values["B3"])
    bg = _number(values["BG"])
    if derive_from_b_fields and not primary_present:
        primary = 1.0 if (b1 > 0 or b2 > 0 or b3 > 0) else 0.0
    if derive_from_b_fields and not secondary_present:
        secondary = 1.0 if bg > 0 and primary <= 0 else 0.0
    if derive_from_b_fields and primary <= 0 and secondary <= 0 and (b1 > 0 or b2 > 0 or b3 > 0 or bg > 0):
        primary = 1.0 if (b1 > 0 or b2 > 0 or b3 > 0) else 0.0
        secondary = 1.0 if bg > 0 and primary <= 0 else 0.0
    amount = min(max(_number(values["amount"]), 0.0) / 100_000_000.0, 5.0)
    score = (
        primary * 100.0
        + secondary * 70.0
        + b1 * 8.0
        + b2 * 12.0
        + b3 * 5.0
        + bg * 5.0
        + _number(values["ref_hold_score"]) * 3.0
        + amount
    )
    has_score_inputs = any(
        key in source for key in ("primary_buy_signal", "secondary_buy_signal", "ref_hold_score", "B1", "B2", "B3", "BG", "amount")
    )
    values["primary_buy_signal"] = primary
    values["secondary_buy_signal"] = secondary
    if not has_score_inputs:
        values["premarket_pool_score"] = ""
        values["premarket_score_formula"] = ""
        values["premarket_score_source"] = ""
    else:
        values["premarket_pool_score"] = round(score, 8)
        values["premarket_score_formula"] = PREMARKET_SCORE_FORMULA
        values["premarket_score_source"] = "SELECTOR_READY_PANEL_EXPLICIT_FIELDS"
    return values


def _premarket_signal_policy(rows: list[Mapping[str, Any]]) -> str:
    markers = {
        str(row.get("premarket_signal_policy") or "").strip()
        for row in rows
        if str(row.get("premarket_signal_policy") or "").strip()
    }
    if "DERIVED_FROM_B1_B2_B3_BG" in markers:
        return "DERIVED_FROM_B1_B2_B3_BG"
    if "EXPLICIT_PRIMARY_SECONDARY" in markers:
        return "EXPLICIT_PRIMARY_SECONDARY"
    explicit_signal_count = sum(
        1
        for row in rows
        if _number(row.get("primary_buy_signal")) > 0
        or _number(row.get("secondary_buy_signal")) > 0
    )
    b_signal_count = sum(
        1
        for row in rows
        if _number(row.get("B1")) > 0
        or _number(row.get("B2")) > 0
        or _number(row.get("B3")) > 0
        or _number(row.get("BG")) > 0
    )
    return (
        "DERIVED_FROM_B1_B2_B3_BG"
        if explicit_signal_count == 0 and b_signal_count > 0
        else "EXPLICIT_PRIMARY_SECONDARY"
    )


def _normalized_hashes(values: Mapping[str, str]) -> dict[str, str]:
    return {str(key): str(value).lower() for key, value in values.items()}


def _require_frozen_hashes(values: Mapping[str, str]) -> dict[str, str]:
    normalized = _normalized_hashes(values)
    if normalized != FROZEN_ORACLE_SHA256S:
        raise StoreError("v1.9.2 oracle sha set does not match frozen contract")
    return normalized


def _normalize_rows(
    rows: Iterable[Mapping[str, Any]], *, signal_date: str, target_date: str
) -> list[dict[str, str]]:
    source_rows = [dict(source) for source in rows]
    signal_policy = _premarket_signal_policy(source_rows)
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, source in enumerate(source_rows, start=1):
        row = dict(source)
        code = str(row.get("ts_code") or "").strip().upper()
        if not code or code in seen:
            raise StoreError("v1.9.2 candidate ts_code is missing or duplicated")
        contract_issues = _entry_contract_issues(row)
        if contract_issues:
            raise StoreError("; ".join(contract_issues))
        if str(row.get("candidate_role") or "") != V192_CANDIDATE_ROLE:
            raise StoreError("v1.9.2 candidate_role must be TEST_ONLY_BUY_CANDIDATE")
        model_role = str(row.get("multi_head_final_role") or "").upper()
        if "B2_FRESH" not in model_role and "B3_CONTINUATION" not in model_role:
            raise StoreError("v1.9.2 model role is outside the frozen B2/B3 candidate contract")
        expected_entry_pool = any(_truthy(row.get(field)) for field in V192_ENTRY_FIELDS)
        if _truthy(row.get("entry_pool")) != expected_entry_pool:
            raise StoreError("v1.9.2 candidate must satisfy entry_pool")
        if str(row.get("rank_usage_boundary") or "") != V192_RANK_BOUNDARY:
            raise StoreError("v1.9.2 rank boundary mismatch")
        if not _falsey(row.get("formal_recommendation_allowed")):
            raise StoreError("v1.9.2 candidate cannot enable formal recommendation")
        seen.add(code)
        row.update(
            trade_date=target_date,
            signal_date=signal_date,
            target_date=target_date,
            bar_time="17:30",
            candidate_id=f"FMLA04_TRACE_AWARE_WAIT_SPLIT_{signal_date}_{code}",
            ts_code=code,
            stock_code=str(row.get("stock_code") or code.split(".", 1)[0]).zfill(6),
            source_kind=V192_SOURCE_KIND,
            selector_version=V192_SELECTOR_VERSION,
            review_rank_v19=row.get("review_rank_v19") or index,
            formal_recommendation_allowed=False,
            test_only_notice="TEST_ONLY_CANDIDATE_NOT_RECOMMENDATION",
        )
        score_fields = _premarket_score_fields(
            {**row, "premarket_signal_policy": signal_policy},
            derive_from_b_fields=signal_policy == "DERIVED_FROM_B1_B2_B3_BG",
        )
        score_fields["premarket_signal_policy"] = signal_policy
        normalized.append({
            field: _cell(row.get(field))
            for field in _FIELDS
            if field not in _PREMARKET_ARTIFACT_FIELDS
        } | {
            field: _cell(value)
            for field, value in score_fields.items()
        })
    return normalized


def publish_v192_rows(
    store_root: Path | str,
    *,
    panel_path: Path | str,
    signal_date: str,
    target_date: str,
    rows: Iterable[Mapping[str, Any]],
    oracle_sha256s: Mapping[str, str],
) -> dict[str, Any]:
    """Publish deterministic v1.9.2 rows into the shared single-writer store."""
    signal_date = validate_date(signal_date)
    target_date = validate_date(target_date)
    if signal_date >= target_date:
        raise StoreError("target_date must be after signal_date")
    local_bundle = verify_local_oracle_bundle()
    frozen_hashes = _require_frozen_hashes(oracle_sha256s)
    if frozen_hashes != local_bundle["origin_sha256s"]:
        raise StoreError("v1.9.2 supplied oracle sha set differs from local bundle origin")
    panel_path = Path(panel_path)
    if not panel_path.is_file():
        raise StoreError(f"selector-ready panel missing: {panel_path}")
    normalized = _normalize_rows(rows, signal_date=signal_date, target_date=target_date)
    panel_sha256 = sha256_file(panel_path)
    oracle_bundle_sha256 = sha256_json(frozen_hashes)

    with tempfile.TemporaryDirectory(prefix="v3sd_v192_publish_") as temporary:
        source = Path(temporary) / "v192_candidates.csv"
        with open(source, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(normalized)
        artifact_sha256 = sha256_file(source)
        provenance = {
            "signal_date": signal_date,
            "source_kind": V192_SOURCE_KIND,
            "selector_version": V192_SELECTOR_VERSION,
            "formula_source": CANONICAL_FORMULA_SOURCE,
            "entry_fields": ",".join(V192_ENTRY_FIELDS),
            "premarket_score_formula": PREMARKET_SCORE_FORMULA,
            "panel_sha256": panel_sha256,
            "oracle_bundle_sha256": oracle_bundle_sha256,
            "oracle_bundle_source_sha256": local_bundle["local_bundle_sha256"],
            "oracle_bundle_contract_version": local_bundle["contract_version"],
            "feature_vector_sha256": frozen_hashes["feature_vector"],
            "score_v19_multihead_sha256": frozen_hashes["score_v19_multihead"],
            "fmla04_role_sha256": frozen_hashes["fmla04_role"],
        }
        spec = SourceSpec(
            source_id="fmla04_v192_frozen_selector",
            role=V192_ROLE,
            trade_date=target_date,
            market="A_SHARE",
            stages=(V192_STAGE_ID,),
            cutoff_at="17:30:00",
            source_path=source,
            required_columns=(
                "trade_date",
                "signal_date",
                "target_date",
                "bar_time",
                "ts_code",
                "candidate_role",
                "multi_head_final_role",
                "entry_pool",
                *V192_ENTRY_FIELDS,
                *V192_INTERMEDIATE_FIELDS,
                "formula_source",
                "rank_usage_boundary",
                "formal_recommendation_allowed",
            ),
            bar_time_column="bar_time",
            expected_input_sha256=artifact_sha256,
            expected_row_count=len(normalized),
            provenance=provenance,
        )
        registry = AllowlistRegistry(entries={(target_date, V192_ROLE): (spec,)})
        store = _V192ManifestStore(
            Path(store_root), role=V192_ROLE, allowlist=registry
        )
        outcome = store.replay_file(
            owner="v3_shared_data",
            trade_date=target_date,
            role=V192_ROLE,
            source_id=spec.source_id,
            stage_id=V192_STAGE_ID,
        )
    read_verified_v192_pool(
        store_root,
        target_date=target_date,
        expected_signal_date=signal_date,
    )
    return outcome


def _validate_candidate_row(row: Mapping[str, Any], signal_date: str, target_date: str) -> None:
    if str(row.get("signal_date") or "") != signal_date:
        raise StoreError("v1.9.2 row signal_date mismatch")
    if str(row.get("trade_date") or "") != target_date or str(row.get("target_date") or "") != target_date:
        raise StoreError("v1.9.2 row target_date mismatch")
    _normalize_rows([row], signal_date=signal_date, target_date=target_date)
    if str(row.get("source_kind") or "") != V192_SOURCE_KIND:
        raise StoreError("v1.9.2 source_kind mismatch")
    if str(row.get("selector_version") or "") != V192_SELECTOR_VERSION:
        raise StoreError("v1.9.2 selector_version mismatch")


def read_verified_v192_pool(
    store_root: Path | str,
    *,
    target_date: str,
    expected_signal_date: str,
) -> VerifiedV192Pool:
    """Read and semantically verify one shared v1.9.2 candidate artifact."""
    target_date = validate_date(target_date)
    expected_signal_date = validate_date(expected_signal_date)
    run = read_verified_latest(store_root, target_date, V192_ROLE)
    receipt_role = run.receipt.get("role")
    if receipt_role != V192_ROLE:
        raise StoreError("v1.9.2 receipt role mismatch")
    manifest_role = run.manifest.get("role")
    if manifest_role is not None and manifest_role != receipt_role:
        raise StoreError("v1.9.2 manifest role mismatch")
    for key in _V192_SAFETY_FLAG_KEYS:
        if key in run.manifest and run.manifest[key] is not False:
            raise StoreError(f"v1.9.2 manifest safety flag {key!r} must be false")
    provenance = run.manifest.get("provenance")
    if not isinstance(provenance, Mapping):
        raise StoreError("v1.9.2 provenance missing")
    if run.manifest.get("signal_date") != expected_signal_date:
        raise StoreError("v1.9.2 manifest signal_date mismatch")
    if run.manifest.get("trade_date") != target_date:
        raise StoreError("v1.9.2 manifest target_date mismatch")
    expected_provenance = {
        "signal_date": expected_signal_date,
        "source_kind": V192_SOURCE_KIND,
        "selector_version": V192_SELECTOR_VERSION,
        "formula_source": CANONICAL_FORMULA_SOURCE,
        "entry_fields": ",".join(V192_ENTRY_FIELDS),
        "premarket_score_formula": PREMARKET_SCORE_FORMULA,
        "oracle_bundle_sha256": sha256_json(FROZEN_ORACLE_SHA256S),
        "oracle_bundle_source_sha256": v192_oracle_bundle.local_bundle_sha256(),
        "oracle_bundle_contract_version": v192_oracle_bundle.ORACLE_CONTRACT_VERSION,
        "feature_vector_sha256": FROZEN_ORACLE_SHA256S["feature_vector"],
        "score_v19_multihead_sha256": FROZEN_ORACLE_SHA256S["score_v19_multihead"],
        "fmla04_role_sha256": FROZEN_ORACLE_SHA256S["fmla04_role"],
    }
    for key, value in expected_provenance.items():
        if provenance.get(key) != value:
            raise StoreError(f"v1.9.2 provenance mismatch: {key}")
    panel_sha = str(provenance.get("panel_sha256") or "")
    if len(panel_sha) != 64 or any(char not in "0123456789abcdef" for char in panel_sha.lower()):
        raise StoreError("v1.9.2 panel sha missing")
    rows: list[dict[str, str]] = []
    with open(run.artifact_path, "r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            _validate_candidate_row(row, expected_signal_date, target_date)
            rows.append(dict(row))
    if len(rows) != run.verification["row_count"]:
        raise StoreError("v1.9.2 artifact row count mismatch")
    return VerifiedV192Pool(run=run, rows=tuple(rows))


@contextmanager
def _date_bounded_panel_for_oracle(
    panel_path: Path, signal_date: str
):
    """Expose the frozen oracle to a bounded parquet view of the source panel.

    The frozen feature oracle takes an inclusive start/end date but reads its
    parquet argument itself. Give it a temporary parquet with the same
    columns and Arrow schema, selected by the reader before any pandas frame
    exists. The original panel remains the provenance object.
    """
    try:
        import pyarrow as pa
        import pyarrow.parquet as parquet
    except ImportError as error:
        raise StoreError("pyarrow is required for the bounded v1.9.2 oracle panel") from error

    try:
        parquet_file = parquet.ParquetFile(panel_path)
        trade_type = parquet_file.schema_arrow.field("trade_date").type
    except (KeyError, OSError, TypeError, ValueError) as error:
        raise StoreError("v1.9.2 selector panel has no readable trade_date field") from error

    start_date = _datetime.date(2026, 1, 1)
    end_date = _datetime.date(
        int(signal_date[:4]), int(signal_date[4:6]), int(signal_date[6:])
    )
    if pa.types.is_integer(trade_type):
        filters = [[
            ("trade_date", ">=", 20260101),
            ("trade_date", "<=", int(signal_date)),
        ]]
    elif pa.types.is_date(trade_type):
        filters = [[
            ("trade_date", ">=", start_date),
            ("trade_date", "<=", end_date),
        ]]
    elif pa.types.is_timestamp(trade_type):
        filters = [[
            ("trade_date", ">=", _datetime.datetime.combine(start_date, _datetime.time())),
            (
                "trade_date",
                "<",
                _datetime.datetime.combine(
                    end_date + _datetime.timedelta(days=1), _datetime.time()
                ),
            ),
        ]]
    elif pa.types.is_string(trade_type) or pa.types.is_large_string(trade_type):
        iso_start = start_date.isoformat()
        iso_end = end_date.isoformat()
        filters = [
            [
                ("trade_date", ">=", "20260101"),
                ("trade_date", "<=", signal_date),
            ],
            [
                ("trade_date", ">=", iso_start),
                ("trade_date", "<=", iso_end),
            ],
        ]
    else:
        raise StoreError(
            f"v1.9.2 selector panel trade_date type is unsupported: {trade_type}"
        )

    try:
        bounded_table = parquet.read_table(panel_path, filters=filters)
    except Exception as error:
        raise StoreError("v1.9.2 selector panel date-bounded read failed") from error

    with tempfile.TemporaryDirectory(prefix="v3sd_v192_oracle_window_") as temporary:
        bounded_path = Path(temporary) / "selector_ready_bounded.parquet"
        try:
            parquet.write_table(bounded_table, bounded_path)
        except Exception as error:
            raise StoreError("v1.9.2 bounded selector panel write failed") from error
        try:
            yield bounded_path
        finally:
            pass


def _read_selector_panel_source_rows(
    panel_path: Path | str, signal_date: str
) -> dict[str, dict[str, Any]]:
    """Read source fields that the frozen feature window may omit.

    The selector-ready parquet is the independent source of the V3 premarket
    score.  ``feature.read_window`` intentionally projects a smaller feature
    matrix and currently drops ``ref_hold_score``; read the source columns
    directly so the materializer does not replace that field with a proxy.
    Missing optional columns are tolerated, while a missing date/code key
    yields no rows and therefore cannot silently create a score.
    """

    path = Path(panel_path)
    try:
        import pyarrow.parquet as parquet

        parquet_file = parquet.ParquetFile(path)
        available = set(parquet_file.schema.names)
        columns = [
            field
            for field in ("trade_date", "ts_code", *_PREMARKET_SOURCE_FIELDS)
            if field in available
        ]
        if "trade_date" not in columns or "ts_code" not in columns:
            return {}
        import pyarrow as pa

        trade_type = parquet_file.schema_arrow.field("trade_date").type
        if pa.types.is_integer(trade_type):
            date_literals: tuple[Any, ...] = (int(signal_date),)
        elif pa.types.is_date(trade_type):
            date_literals = (_datetime.date(int(signal_date[:4]), int(signal_date[4:6]), int(signal_date[6:])),)
        elif pa.types.is_timestamp(trade_type):
            date_literals = (
                _datetime.datetime(
                    int(signal_date[:4]), int(signal_date[4:6]), int(signal_date[6:])
                ),
            )
        else:
            date_literals = (
                signal_date,
                f"{signal_date[:4]}-{signal_date[4:6]}-{signal_date[6:]}",
            )
        filters = [[("trade_date", "=", literal)] for literal in date_literals]
        frame = parquet.read_table(path, columns=columns, filters=filters).to_pandas()
    except (ImportError, OSError, ValueError, TypeError):
        return {}

    def _matches_date(value: Any) -> bool:
        text = str(value or "").strip()
        if text == signal_date:
            return True
        digits = "".join(char for char in text if char.isdigit())
        return digits.startswith(signal_date)

    frame = frame.loc[frame["trade_date"].map(_matches_date)]
    rows: dict[str, dict[str, Any]] = {}
    for raw in frame.to_dict("records"):
        code = str(raw.get("ts_code") or "").strip().upper()
        if not code or code in rows:
            continue
        rows[code] = {
            field: raw.get(field)
            for field in _PREMARKET_SOURCE_FIELDS
            if field in raw
        }
    return rows


def verify_local_oracle_bundle() -> dict[str, Any]:
    """Verify the V4 closure and return its two provenance layers.

    The origin layer is the frozen SHA map of the three reference sources. The
    local layer is the byte SHA of this checkout's bundle module. Keeping both
    values explicit prevents the origin map digest from being mistaken for the
    local implementation bytes.
    """

    origin = _require_frozen_hashes(v192_oracle_bundle.ORACLE_ORIGIN_SHA256S)
    if v192_oracle_bundle.origin_bundle_sha256() != v192_oracle_bundle.ORIGIN_BUNDLE_SHA256:
        raise StoreError("v1.9.2 oracle origin bundle digest mismatch")
    missing = [
        name
        for name in v192_oracle_bundle.required_local_symbols()
        if not callable(getattr(v192_oracle_bundle, name, None))
    ]
    if missing:
        raise StoreError("v1.9.2 local oracle symbols missing: " + ",".join(missing))
    local_sha = str(v192_oracle_bundle.local_bundle_sha256()).lower()
    if len(local_sha) != 64 or any(char not in "0123456789abcdef" for char in local_sha):
        raise StoreError("v1.9.2 local oracle bundle sha is invalid")
    return {
        "origin_sha256s": origin,
        "origin_bundle_sha256": v192_oracle_bundle.ORIGIN_BUNDLE_SHA256,
        "local_bundle_sha256": local_sha,
        "contract_version": v192_oracle_bundle.ORACLE_CONTRACT_VERSION,
    }


def verify_oracle_sources() -> dict[str, str]:
    """Compatibility name returning the frozen origin SHA map.

    Runtime verification is local-only; reference source files are not opened.
    """

    return dict(verify_local_oracle_bundle()["origin_sha256s"])


def run_frozen_v192_oracle(
    panel_path: Path | str,
    signal_date: str,
) -> list[dict[str, Any]]:
    """Execute the exact frozen feature, score and FMLA04 role functions."""
    signal_date = validate_date(signal_date)
    panel_path = Path(panel_path)
    if not panel_path.is_file():
        raise StoreError(f"selector-ready panel missing: {panel_path}")
    verify_local_oracle_bundle()
    feature = v192_oracle_bundle
    scorer = v192_oracle_bundle
    roles = v192_oracle_bundle
    with _date_bounded_panel_for_oracle(panel_path, signal_date) as bounded_panel:
        raw = feature.read_window(bounded_panel, 20260101, int(signal_date))
    symbols = raw["ts_code"].astype(str).str.upper()
    raw = raw.loc[symbols.str.endswith((".SH", ".SZ", ".BJ"))].copy()
    # The exact signal-date selector-ready panel is authoritative for every
    # premarket source field.  ``feature.read_window`` and the frozen scorer
    # may carry stale/legacy projections of those fields; they are used only
    # to compute the frozen score and role outputs below.
    panel_rows = _read_selector_panel_source_rows(panel_path, signal_date)
    prepared = feature.vector_prepare_features(raw)
    scored = scorer.score_multi_head(scorer.score_v19(prepared))
    day = scored.loc[scored["date8"].astype(str).eq(signal_date)].copy()
    if day.empty:
        raise StoreError(f"v1.9.2 has no A-share rows for signal_date={signal_date}")
    day["entry_pool"] = roles.entry_pool(day)
    day["candidate_role"] = roles.base_fmla04_role(day)
    def _day_signal(field: str):
        if field in day.columns:
            return day[field].fillna(0).astype(float)
        return day.index.to_series().map(lambda _value: 0.0)

    day_primary = _day_signal("primary_buy_signal")
    day_secondary = _day_signal("secondary_buy_signal")
    day_b_signal = sum(
        (_day_signal(field) > 0) for field in ("B1", "B2", "B3", "BG")
    )
    explicit_signal_count = int(((day_primary > 0) | (day_secondary > 0)).sum())
    b_signal_count = int(day_b_signal.sum())
    premarket_signal_policy = (
        "DERIVED_FROM_B1_B2_B3_BG"
        if explicit_signal_count == 0 and b_signal_count > 0
        else "EXPLICIT_PRIMARY_SECONDARY"
    )
    selected = day.loc[day["candidate_role"].eq(V192_CANDIDATE_ROLE)].copy()
    selected["review_rank_v19"] = selected["final_score"].rank(method="first", ascending=False).astype(int)
    selected = selected.sort_values(
        ["review_rank_v19", "risk_chase_score", "stock_code"],
        ascending=[True, True, True],
    )
    output: list[dict[str, Any]] = []
    for _, row in selected.iterrows():
        code = str(row.get("ts_code") or "").strip().upper()
        panel_source = panel_rows.get(code)
        if panel_source is None:
            raise StoreError(
                f"v1.9.2 selector panel source row missing: signal_date={signal_date}; ts_code={code}"
            )
        missing_source_fields = _missing_premarket_source_fields(panel_source)
        if missing_source_fields:
            raise StoreError(
                "v1.9.2 selector panel source field missing: "
                + ",".join(missing_source_fields)
            )
        output.append(
            {
                "ts_code": row.get("ts_code"),
                "stock_code": row.get("stock_code"),
                "stock_name": row.get("stock_name"),
                "candidate_role": row.get("candidate_role"),
                "multi_head_final_role": row.get("multi_head_final_role"),
                "entry_pool": row.get("entry_pool"),
                "review_rank_v19": row.get("review_rank_v19"),
                "final_score": row.get("final_score"),
                "multi_entry_score": row.get("multi_entry_score"),
                "multi_entry_risk_adjusted_score": row.get("multi_entry_risk_adjusted_score"),
                "fresh_b2_entry_score": row.get("fresh_b2_entry_score"),
                "continuation_entry_score": row.get("continuation_entry_score"),
                "hold_through_main_wave_score": row.get("hold_through_main_wave_score"),
                "risk_chase_score": row.get("risk_chase_score"),
                "rank_usage_boundary": V192_RANK_BOUNDARY,
                "formal_recommendation_allowed": False,
                "source_trace": (
                    f"entry_pool={row.get('entry_pool')}; final_score={row.get('final_score')}; "
                    f"multihead_role={row.get('multi_head_final_role')}; "
                    f"risk_chase_score={row.get('risk_chase_score')}"
                ),
                **{
                    field: panel_source[field]
                    for field in _PREMARKET_SOURCE_FIELDS
                },
                "premarket_signal_policy": premarket_signal_policy,
            }
        )
    return output


def materialize_frozen_v192_selector(
    store_root: Path | str,
    *,
    panel_path: Path | str,
    signal_date: str,
    target_date: str,
    runner: Callable[[Path | str, str], list[dict[str, Any]]] = run_frozen_v192_oracle,
) -> dict[str, Any]:
    rows = runner(panel_path, signal_date)
    return publish_v192_rows(
        store_root,
        panel_path=panel_path,
        signal_date=signal_date,
        target_date=target_date,
        rows=rows,
        oracle_sha256s=verify_oracle_sources(),
    )
