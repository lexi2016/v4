"""Bounded, explicit-input A-share formula increment authority for V4.

This module is the V4 producer for the offline/replay path only.  It consumes a
caller-supplied manifest and parquet input, computes the reviewed formula on a
serial 260-row tail, builds one full source frame plus an authoritative
187-column selector and a 12-field auxiliary sidecar, and publishes one
atomic generation pointer only after every gate passes.  The two legacy text
pointer files remain compatibility projections; consumers must read the
generation pointer to obtain a coherent selector/backtest pair.

No network client, default data root, old release import, scheduler, or formal
state path is present here.  The historical implementation remains a
reference-only source for semantics.

Origin evidence (reference-only; never imported at runtime):
- formula builder SHA256: 074a038699eae84d093602ee6df551b5279368c5800ad78067902a496c990258
- increment implementation SHA256: 901d4802c784decda9d43e757b367496d1171e5e702485a29f4c66fad3c7ae2e
- field contract SHA256: feb845426d7d37aaf63791ff1c799b575b36821d647d0977b890c0b4389b583c
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import signal
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

# Preserve direct-file CLI discovery of the sibling review modules.
if __name__ == "__main__" and not __package__:
    import sys as _v4_import_sys
    from pathlib import Path as _v4_import_Path
    _v4_import_sys.path.insert(0, str(_v4_import_Path(__file__).resolve().parents[1]))


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
# A direct absolute-path invocation can leave another checkout in sys.path[0].
# Put this canonical project first so the child cannot import a same-named legacy
# infrastructure package from its caller's working directory.
_project_text = str(_PROJECT_ROOT)
if sys.path[:1] != [_project_text]:
    sys.path.insert(0, _project_text)

from infrastructure.interprocess_lock import owned_interprocess_lock
from infrastructure.owned_io import SafeRoot
from infrastructure.formula_generation import is_v4_formula_state_path
from upstreams.v3_shared_data.shared_data import a_formula_authority


SCHEMA_VERSION = "v4.a_formula_increment_authority.v1"
FORMULA_SOURCE = a_formula_authority.FORMULA_SOURCE
FORMULA_VERSION = a_formula_authority.FORMULA_VERSION
FORMULA_ORIGIN_SHA256 = a_formula_authority.ORIGIN_SHA256
INCREMENT_ORIGIN_SHA256 = "901d4802c784decda9d43e757b367496d1171e5e702485a29f4c66fad3c7ae2e"
CONTRACT_ORIGIN_SHA256 = "feb845426d7d37aaf63791ff1c799b575b36821d647d0977b890c0b4389b583c"
TAIL_RECORDS = 260
MAX_CLOSE_RATIO = 1.5
FORMULA_GENERATION_SCHEMA = "v4.a_formula.generation_pointer.v1"
FORMULA_GENERATION_POINTER_NAME = "CURRENT_FORMULA_GENERATION.json"
SAFETY_FLAGS = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
SIDEcar_COLUMNS = (
    "breakout",
    "close_higher_than_prev",
    "close_lower_than_prev",
    "double_breakout",
    "field_contract_version",
    "formula_source",
    "ref_hold_score",
    "ref_score_above_bbi",
    "ref_score_close_up",
    "ref_score_j_no_dead_cross",
    "ref_score_no_giant_true_yin",
    "ref_score_trend_up",
)
KEY_COLUMNS = ("ts_code", "trade_date")
BASE_COLUMNS = ("ts_code", "trade_date", "open", "high", "low", "close", "volume", "amount")
V192_ENTRY_FIELDS = (
    "gold_brick_context",
    "brick_resonance_context",
    "brick_buy",
    "brick_buy1_low_absorb",
    "brick_buy2_attack",
    "primary_buy_signal",
    "secondary_buy_signal",
)
V192_INTERMEDIATE_FIELDS = ("brick_exist_b", "brick_resonance1", "brick_resonance2", "brick_resonance")

# The historical selector/backtest seeds contain a small, already-produced
# HK/HK_FUND anomaly set.  Those rows are retained as-is while the new A-share
# increment remains subject to the normal strict row gate.  The counts and
# dates below describe the approved evidence only. Runtime exceptions require
# BOTH the frozen seed SHA and exact anomaly key set; counts never authorize gaps.
KNOWN_HISTORICAL_GAP_MARKETS = ("HK", "HK_FUND")
KNOWN_HISTORICAL_GAP_DATE_RANGE = (20260504, 20260507)
KNOWN_HISTORICAL_GAP_COUNTS = {"HK": 186, "HK_FUND": 168}
APPROVED_HISTORY_CONTRACT_SHA256 = '988e483ded86ed9df6862f4a3317f74394b713c288b8f0df12fdb13ab9c04f02'

# The frozen contract names the two seed roles ``selector`` and ``backtest``.
# Runtime receipts keep their historical ``*_history`` labels, so the alias
# must be explicit rather than allowing an unrecognized role to pass through
# as a no-exception audit.
HISTORY_CONTRACT_ROLE_ALIASES = {
    "selector": "selector",
    "backtest": "backtest",
    "selector_history": "selector",
    "backtest_history": "backtest",
}


class AuthorityError(ValueError):
    """Raised when an offline input or candidate gate cannot be proven."""


def _jsonable(value: Any) -> Any:
    from ops._a_formula_increment_parts.primitives_cli import __jsonable_body as _v4_impl
    return _v4_impl(globals(), value)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_has_symlink(path: Path, *, stop: Path | None = None) -> bool:
    from ops._a_formula_increment_parts.primitives_cli import __path_has_symlink_body as _v4_impl
    return _v4_impl(globals(), path, stop=stop)


def _resolved(path: Path | str) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _reject_formal_root(path: Path, label: str) -> None:
    text = str(path)
    if "/releases/" in text:
        raise AuthorityError(f"{label} cannot target formal release/application-support root")
    if "/Library/Application Support/" in text and not is_v4_formula_state_path(path):
        raise AuthorityError(f"{label} cannot target formal release/application-support root")
    if any(part in {"formal_state", "production_state", "current_state"} for part in path.parts):
        raise AuthorityError(f"{label} cannot target formal state root")


def _safe_output_root(data_root: Path, return_root: Path, selector_pointer: Path, backtest_pointer: Path) -> Path:
    from ops._a_formula_increment_parts.primitives_cli import __safe_output_root_body as _v4_impl
    return _v4_impl(globals(), data_root, return_root, selector_pointer, backtest_pointer)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AuthorityError(f"json unreadable: {path}") from error
    if not isinstance(value, dict):
        raise AuthorityError(f"json object required: {path}")
    return value


def _manifest_digest(manifest: Mapping[str, Any]) -> str:
    payload = dict(manifest)
    payload.pop("manifest_sha256", None)
    return _sha256_bytes(_canonical_bytes(payload))


def _require_pass_gate(value: Any, name: str) -> None:
    if not isinstance(value, Mapping) or str(value.get("status", "")).upper() not in {"PASS", "READY"}:
        raise AuthorityError(f"{name} must have status PASS")


def _safe_manifest_file(input_root: Path, raw: Any) -> Path:
    from ops._a_formula_increment_parts.input_manifest import __safe_manifest_file_body as _v4_impl
    return _v4_impl(globals(), input_root, raw)


def _load_input_manifest(input_root: Path | str, manifest_path: Path | str, target_date: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    from ops._a_formula_increment_parts.input_manifest import __load_input_manifest_body as _v4_impl
    return _v4_impl(globals(), input_root, manifest_path, target_date)


def _normalize_date_series(series: pd.Series) -> pd.Series:
    from ops._a_formula_increment_parts.primitives_cli import __normalize_date_series_body as _v4_impl
    return _v4_impl(globals(), series)


def _normalize_input_frame(frame: pd.DataFrame, target_date: int) -> pd.DataFrame:
    from ops._a_formula_increment_parts.feature_computation import __normalize_input_frame_body as _v4_impl
    return _v4_impl(globals(), frame, target_date)


def _read_seed(path: Path | str, role: str) -> pd.DataFrame:
    from ops._a_formula_increment_parts.primitives_cli import __read_seed_body as _v4_impl
    return _v4_impl(globals(), path, role)


def collect_increment_history(frame: pd.DataFrame, *, tail_records: int = TAIL_RECORDS) -> pd.DataFrame:
    """Keep the explicit per-symbol tail used by the reviewed increment path."""
    if tail_records < 1:
        raise AuthorityError("tail_records must be positive")
    return (
        frame.sort_values(["ts_code", "trade_date"], kind="mergesort")
        .groupby("ts_code", sort=False, group_keys=False)
        .tail(int(tail_records))
        .reset_index(drop=True)
    )


def _backfill_increment_contract_columns(
    features: pd.DataFrame,
    *current_frames: pd.DataFrame,
) -> pd.DataFrame:
    """Carry stable source/contract columns from the reviewed seed rows.

    The live ``.day`` adapter intentionally contains only market bars.  The
    existing selector/backtest seeds remain the authority for stable metadata
    (exchange, source, panel constants, and similar contract columns); formula
    values computed for the new rows are never replaced.  A symbol with no
    seed metadata fails closed instead of receiving a guessed default.
    """
    from ops._a_formula_increment_parts.feature_computation import __backfill_increment_contract_columns_body as _v4_impl
    return _v4_impl(globals(), features, *current_frames)


def compute_formula_features(history: pd.DataFrame) -> pd.DataFrame:
    """Compute the reviewed formula once through the V4 pure authority."""
    from ops._a_formula_increment_parts.feature_computation import _compute_formula_features_body as _v4_impl
    return _v4_impl(globals(), history)


def select_generated_increment_rows(features: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    if features.empty:
        return features.copy()
    if current.empty:
        return features.copy().reset_index(drop=True)
    latest = current.groupby("ts_code", sort=False)["trade_date"].max().to_dict()
    cutoff = features["ts_code"].map(latest).fillna(0).astype("int64")
    return features.loc[features["trade_date"].astype("int64") > cutoff].copy().reset_index(drop=True)


def filter_increment_rows(features: pd.DataFrame, current: pd.DataFrame, *, role: str = "selector") -> pd.DataFrame:
    """Compatibility wrapper retaining the reviewed date cutoff semantics."""
    del role
    return select_generated_increment_rows(features, current)


def _audit_increment_boundary(current: pd.DataFrame, increment: pd.DataFrame) -> dict[str, Any]:
    from ops._a_formula_increment_parts.primitives_cli import __audit_increment_boundary_body as _v4_impl
    return _v4_impl(globals(), current, increment)


def _key_sha256(frame: pd.DataFrame) -> str:
    """Hash the sorted authority keys for source/sidecar binding."""
    if any(column not in frame.columns for column in KEY_COLUMNS):
        raise AuthorityError("key digest requires authority key columns")
    rows = [
        [str(row[0]), int(row[1])]
        for row in frame.loc[:, list(KEY_COLUMNS)].sort_values(list(KEY_COLUMNS), kind="mergesort").itertuples(index=False, name=None)
    ]
    return _sha256_bytes(_canonical_bytes(rows))


def _retention_hash_table(frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    """Build a compact sorted key/row-hash table for large seed frames.

    The seeds are multi-gigabyte parquet inputs.  A Python dict of every cell
    would multiply their memory footprint, so retention is checked with
    pandas' stable row hash and a three-column key table instead.
    """
    from ops._a_formula_increment_parts.retention import __retention_hash_table_body as _v4_impl
    return _v4_impl(globals(), frame, columns)


def _align_retention_hash_frames(
    current: pd.DataFrame,
    combined: pd.DataFrame,
    columns: Sequence[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Normalize only dtype-promoted columns before hashing two frames.

    ``pd.concat`` may promote a historical integer column to float or a
    string extension column to object when the new increment is appended.  A
    value-preserving common dtype prevents that representation change from
    looking like a historical edit while still retaining changed numeric or
    textual values for comparison.
    """
    from ops._a_formula_increment_parts.retention import __align_retention_hash_frames_body as _v4_impl
    return _v4_impl(globals(), current, combined, columns)


def _hash_table_digest(table: pd.DataFrame, columns: Sequence[str], *, hash_column: str = "_retention_hash") -> str:
    digest = hashlib.sha256()
    digest.update(_canonical_bytes({"algorithm": "pandas.hash_pandas_object.v1", "columns": list(columns)}))
    digest.update(b"\0")
    values = table[hash_column].to_numpy(dtype="uint64", na_value=0).astype("<u8", copy=False)
    digest.update(values.tobytes())
    return digest.hexdigest()


def _external_market(ts_code: Any) -> str | None:
    match = re.fullmatch(r"\d{5}\.([A-Za-z_]+)", str(ts_code).strip())
    if not match:
        return None
    market = match.group(1).upper()
    return market if market in KNOWN_HISTORICAL_GAP_MARKETS else None


def _approved_history_gap_keys(role: str, seed_sha256: str, observed: set[tuple[str, int]]) -> dict[str, Any]:
    """Read frozen evidence; no path, row-count or same-window substitution."""
    from ops._a_formula_increment_parts.history_audit import __approved_history_gap_keys_body as _v4_impl
    return _v4_impl(globals(), role, seed_sha256, observed)


def _audit_existing_history(
    current: pd.DataFrame,
    combined: pd.DataFrame,
    *,
    role: str,
    target_date: int,
    seed_sha256: str,
) -> dict[str, Any]:
    """Prove append-only retention without re-gating known old HK anomalies.

    Only rows introduced by the current run are validated by the strict
    selector/backtest gates.  Existing rows must remain present with the same
    logical key/value content.  Known historical HK/HK_FUND close-range rows
    are reported as an unresolved health gap; any other historical structural
    issue still fails closed.
    """
    from ops._a_formula_increment_parts.history_audit import __audit_existing_history_body as _v4_impl
    return _v4_impl(globals(), current, combined, role=role, target_date=target_date, seed_sha256=seed_sha256)


def _historical_seed_health(*audits: Mapping[str, Any]) -> dict[str, Any]:
    """Keep seed health explicitly unresolved outside this increment scope."""
    from ops._a_formula_increment_parts.history_audit import __historical_seed_health_body as _v4_impl
    return _v4_impl(globals(), *audits)


def load_authoritative_contract_rows(contract_csv: Path | str) -> list[dict[str, str]]:
    from ops._a_formula_increment_parts.selector_contract import _load_authoritative_contract_rows_body as _v4_impl
    return _v4_impl(globals(), contract_csv)


def build_contract_policy(rows: list[dict[str, str]], contract_csv: Path | str) -> dict[str, Any]:
    from ops._a_formula_increment_parts.selector_contract import _build_contract_policy_body as _v4_impl
    return _v4_impl(globals(), rows, contract_csv)


def build_table_for_schema(new_df: pd.DataFrame, schema_columns: Sequence[str], role: str) -> pd.DataFrame:
    missing = [column for column in schema_columns if column not in new_df.columns]
    if missing:
        raise AuthorityError(f"{role} schema missing generated columns: {','.join(missing)}")
    return new_df.loc[:, list(schema_columns)].copy()


def _validate_signal_fields(frame: pd.DataFrame) -> None:
    for field in V192_ENTRY_FIELDS + V192_INTERMEDIATE_FIELDS:
        if field not in frame.columns:
            raise AuthorityError(f"missing V192 signal field: {field}")
        if field == "gold_brick_context":
            if frame[field].isna().any() or (~frame[field].astype(str).isin({"none", "old_gold_candidate"})).any():
                raise AuthorityError("invalid gold_brick_context")
        else:
            values = pd.to_numeric(frame[field], errors="coerce")
            if values.isna().any() or (~values.isin([0, 1])).any():
                raise AuthorityError(f"invalid V192 signal field: {field}")


def validate_new_selector_rows(frame: pd.DataFrame, target_date: int, *, role: str = "selector") -> dict[str, Any]:
    from ops._a_formula_increment_parts.selector_contract import _validate_new_selector_rows_body as _v4_impl
    return _v4_impl(globals(), frame, target_date, role=role)


def _validate_backtest_frame(frame: pd.DataFrame, target_date: int) -> dict[str, Any]:
    from ops._a_formula_increment_parts.selector_contract import __validate_backtest_frame_body as _v4_impl
    return _v4_impl(globals(), frame, target_date)


def build_official_selector_frame(frame: pd.DataFrame, policy: Mapping[str, Any]) -> pd.DataFrame:
    official = list(policy["official_columns"])
    missing = [column for column in official if column not in frame.columns]
    if missing:
        raise AuthorityError(f"official selector missing contract columns: {','.join(missing)}")
    output = frame.loc[:, official].copy()
    if list(output.columns) != official or len(output.columns) != 187:
        raise AuthorityError("official selector projection is not exactly 187 columns")
    return output


def build_sidecar_frame(frame: pd.DataFrame, policy: Mapping[str, Any]) -> pd.DataFrame:
    missing = [column for column in list(KEY_COLUMNS) + list(policy["sidecar_columns"]) if column not in frame.columns]
    if missing:
        raise AuthorityError(f"auxiliary sidecar missing columns: {','.join(missing)}")
    output = frame.loc[:, list(KEY_COLUMNS) + list(policy["sidecar_columns"])].copy()
    if output.duplicated(list(KEY_COLUMNS)).any():
        raise AuthorityError("auxiliary sidecar duplicate keys")
    if output[list(policy["sidecar_columns"])].isna().any().any():
        raise AuthorityError("auxiliary sidecar contains null lineage/formula fields")
    return output


def _append_rows(current: pd.DataFrame, increment: pd.DataFrame, *, role: str) -> pd.DataFrame:
    from ops._a_formula_increment_parts.primitives_cli import __append_rows_body as _v4_impl
    return _v4_impl(globals(), current, increment, role=role)


def _atomic_parquet(frame: pd.DataFrame, destination: Path) -> None:
    from ops._a_formula_increment_parts.pointer_transaction import __atomic_parquet_body as _v4_impl
    return _v4_impl(globals(), frame, destination)


def _read_pointer_bytes(pointer: Path) -> bytes | None:
    try:
        raw = pointer.read_bytes()
    except FileNotFoundError:
        return None
    if pointer.is_symlink():
        raise AuthorityError(f"pointer is symlinked: {pointer}")
    return raw


def _pointer_target_bytes(path: Path) -> bytes:
    return (str(path) + "\n").encode("utf-8")


def _generation_pointer_path(output_root: Path) -> Path:
    return _resolved(output_root) / FORMULA_GENERATION_POINTER_NAME


def _generation_target_metadata(path: Path, output_root: Path, role: str) -> dict[str, Any]:
    target = _resolved(path)
    root = _resolved(output_root)
    if not _within(target, root) or _path_has_symlink(path, stop=root) or target.is_symlink() or not target.is_file():
        raise AuthorityError(f"{role} target is missing or outside isolated output root")
    return {"path": str(target), "bytes": target.stat().st_size, "sha256": sha256_file(target)}


def _generation_payload(
    output_root: Path,
    selector_target: Path,
    backtest_target: Path,
    generation_metadata: Mapping[str, Any] | None = None,
) -> tuple[bytes, dict[str, Any]]:
    from ops._a_formula_increment_parts.primitives_cli import __generation_payload_body as _v4_impl
    return _v4_impl(globals(), output_root, selector_target, backtest_target, generation_metadata)


def _generation_evidence(raw: bytes | None) -> dict[str, Any]:
    return {
        "exists": raw is not None,
        "sha256": _sha256_bytes(raw) if raw is not None else "",
        "bytes": len(raw) if raw is not None else 0,
    }


def _copy_generation_owned_file(
    source: Path | str,
    destination: Path,
    *,
    role: str,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Copy one validated input document below the generation output root.

    The strict generation reader intentionally rejects provenance files that
    resolve outside the pointer's output root.  Keep the source bytes intact,
    but publish an owned copy beside the generated artifacts so an offline
    replay remains self-contained and its original digest is still auditable.
    """
    from ops._a_formula_increment_parts.generation_evidence import __copy_generation_owned_file_body as _v4_impl
    return _v4_impl(globals(), source, destination, role=role, expected_sha256=expected_sha256)


def _prepare_generation_owned_evidence(
    run_dir: Path,
    manifest: Mapping[str, Any],
    *,
    target_date: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Bind the input manifest and its sync receipt to this generation.

    ``a_formula_input_manifest`` records the receipt under
    ``sync_receipt_path``; accepted-only manifests use the older
    ``source_receipt_path`` spelling.  Both names are accepted as source
    provenance, then normalized to the strict generation reader's
    ``sync_receipt_*`` fields while preserving the original source SHA.
    """
    from ops._a_formula_increment_parts.generation_evidence import __prepare_generation_owned_evidence_body as _v4_impl
    return _v4_impl(globals(), run_dir, manifest, target_date=target_date)


def _write_pointer_pair(
    selector_pointer: Path,
    backtest_pointer: Path,
    selector_target: Path,
    backtest_target: Path,
    output_root: Path,
    generation_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    from ops._a_formula_increment_parts.pointer_transaction import __write_pointer_pair_body as _v4_impl
    return _v4_impl(globals(), selector_pointer, backtest_pointer, selector_target, backtest_target, output_root, generation_metadata)


def _write_receipt(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    SafeRoot(path.parent).write_bytes(path.name, (json.dumps(_jsonable(dict(payload)), ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))


def _run_success(
    *,
    target_date: int,
    input_root: Path,
    input_manifest: Path,
    data_root: Path,
    return_root: Path,
    selector_pointer: Path,
    backtest_pointer: Path,
    selector_seed: Path,
    backtest_seed: Path,
    contract_csv: Path,
    legacy_formula_source: str | None = None,
) -> dict[str, Any]:
    from ops._a_formula_increment_parts.increment_workflow import __run_success_body as _v4_impl
    return _v4_impl(globals(), target_date=target_date, input_root=input_root, input_manifest=input_manifest, data_root=data_root, return_root=return_root, selector_pointer=selector_pointer, backtest_pointer=backtest_pointer, selector_seed=selector_seed, backtest_seed=backtest_seed, contract_csv=contract_csv, legacy_formula_source=legacy_formula_source)


def run_increment_authority(
    *,
    target_date: str | int,
    input_root: Path | str,
    input_manifest: Path | str,
    data_root: Path | str,
    return_root: Path | str,
    selector_pointer: Path | str,
    backtest_pointer: Path | str,
    selector_seed: Path | str,
    backtest_seed: Path | str,
    contract_csv: Path | str,
    legacy_formula_source: str | None = None,
) -> dict[str, Any]:
    from ops._a_formula_increment_parts.increment_workflow import _run_increment_authority_body as _v4_impl
    return _v4_impl(globals(), target_date=target_date, input_root=input_root, input_manifest=input_manifest, data_root=data_root, return_root=return_root, selector_pointer=selector_pointer, backtest_pointer=backtest_pointer, selector_seed=selector_seed, backtest_seed=backtest_seed, contract_csv=contract_csv, legacy_formula_source=legacy_formula_source)


def _parser() -> argparse.ArgumentParser:
    from ops._a_formula_increment_parts.primitives_cli import __parser_body as _v4_impl
    return _v4_impl(globals())


def main(argv: Sequence[str] | None = None) -> int:
    from ops._a_formula_increment_parts.primitives_cli import _main_body as _v4_impl
    return _v4_impl(globals(), argv)


if __name__ == "__main__":
    raise SystemExit(main())
