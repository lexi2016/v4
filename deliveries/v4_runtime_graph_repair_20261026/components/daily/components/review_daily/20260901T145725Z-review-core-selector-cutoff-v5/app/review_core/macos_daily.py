"""Stable, exact-date macOS entry point for the Review Core daily chain.

This module is intentionally narrower than :mod:`review_core.scheduler`:
launchd calls it repeatedly, but it may only select the requested/current
date.  All source/tool roots are supplied by the caller, and an already READY
exact-date ReviewBundle is a hard idempotency boundary that does not perform
discovery, download, or ASR again.
"""

from __future__ import annotations
from review_core.runtime_graph_notifications import notify as _graph_notify

import argparse
import csv
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from . import scheduler
from .core import normalize_trade_date


SAFETY_FLAGS = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}

SELECTOR_POINTER_SCHEMA = "review_core.selector_pointer.v1"
SELECTOR_A2_SCHEMA = "v35.a2.exact_d1_selector_panel_current.v2.acceptance_receipt"
SELECTOR_A2_STATUS = "EXACT_D1_SELECTOR_PANEL_CURRENT_READY"
SELECTOR_A3_SCHEMA = "v35.a3.stage_authority.compat_receipt.v1"
SELECTOR_A3_STATUS = "READY"
SELECTOR_A2_FINAL_SCHEMA = "v35.a2.exact_d1_selector_panel_current.v2.final_invariants"
SELECTOR_A2_MANIFEST_SCHEMA = "v35.a2.formal_panel_manifest.v1"
SELECTOR_A2_RECEIPT_SCHEMA = "v35.a2.formal_panel_receipt.v1"
SELECTOR_A2_POINTER_COMMIT_SCHEMA = "v35.a2.pointer_commit_receipt.v2"
SELECTOR_A2_PASS_STATUS = "PASS"
SELECTOR_A2_RECEIPT_STATUS = "READY"
SELECTOR_A2_POINTER_COMMIT_STATUS = "READY"
SELECTOR_ORIGIN = "CONTROLLED_MATERIALIZATION_NOT_NATURAL"
# These constants are exclusively for the already accepted 20260824 ->
# 20260825 A2+A3 compatibility branch.  Current A2 V2 routing below is
# derived from the pointer target basename and never consults these values.
LEGACY_SELECTOR_COMPAT_CUTOFF = "2026-08-24T17:00:00+08:00"
LEGACY_SELECTOR_COMPAT_SOURCE_DATE = "20260824"
LEGACY_SELECTOR_COMPAT_BUSINESS_DATE = "20260825"
LEGACY_SELECTOR_COMPAT_RUN_ID = "133000"
SELECTOR_SAFETY_FIELDS = ("production_allowed", "buy_gate_updated", "orders_sent")
SELECTOR_READY_SIGNALS = frozenset(
    {
        "SELECTOR_READY",
        "CURRENT_SELECTOR_READY_PANEL",
        "READY",
        "PASS_SELECTOR_READY",
    }
)
RECEIPT_ORIGINS = frozenset({"manual", "natural_scheduler"})
NATIVE_FORMULA_TASK = "data_layer_daily_formula_increment_update_v1"
NATIVE_FORMULA_FINAL_STATUS = "PASS_DATA_LAYER_DAILY_FORMULA_INCREMENT_UPDATE_V1"
NATIVE_FORMULA_ROLE = "A_SHARE_V192_PREMARKET_POOL_V3"
NATIVE_FORMULA_ORIGIN = "CONTROLLED_RECOVERY_NATIVE_FORMULA_PROMOTION"
NATIVE_SHARED_LATEST_SCHEMA = "v3_shared_data.latest.v1"
NATIVE_SHARED_MANIFEST_SCHEMA = "v3_shared_data.manifest.v1"
NATIVE_SHARED_RECEIPT_SCHEMA = "v3_shared_data.receipt.v1"


@dataclass(frozen=True)
class DailyPaths:
    """Explicit roots for one exact-date macOS invocation."""

    data_root: Path
    selector_pointer: Path
    selector_path: Path | None
    public_source_root: Path
    tdx_root: Path
    source_root: Path | None
    receipt_root: Path
    funasr_path: Path | None
    ffmpeg_path: Path | None
    ytdlp_path: Path | None
    python_path: Path | None
    shared_package_root: Path | None = None
    release_root: Path | None = None
    working_directory: Path | None = None
    selector_target_trade_date: str | None = None
    selector_cutoff: str | None = None
    require_runtime_contract: bool = False
    asr_python_path: Path | None = None
    formal_pool_path: Path | None = None
    review_pool_path: Path | None = None
    stage_root: Path | None = None

    def __post_init__(self) -> None:
        for field in (
            "data_root",
            "selector_pointer",
            "selector_path",
            "public_source_root",
            "tdx_root",
            "receipt_root",
            "funasr_path",
            "ffmpeg_path",
            "ytdlp_path",
            "python_path",
            "asr_python_path",
            "formal_pool_path",
            "review_pool_path",
            "stage_root",
            "shared_package_root",
            "release_root",
            "working_directory",
        ):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, Path(value).expanduser().absolute())
        if self.source_root is not None:
            object.__setattr__(self, "source_root", Path(self.source_root).expanduser().absolute())


def _canonical(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> tuple[str, int]:
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    digest = hashlib.sha256(encoded).hexdigest()
    return digest, len(encoded)


def _selector_target(pointer: Path) -> Path | None:
    metadata = _selector_pointer_document(Path(pointer))
    return _selector_target_from_document(Path(pointer), metadata)


def _selector_target_from_document(
    pointer: Path, document: Mapping[str, Any], *, resolve: bool = True
) -> Path | None:
    value = _selector_field(document, "selector_path", "path", "target", "panel_path")
    if not value:
        return None
    candidate = Path(str(value)).expanduser()
    if not candidate.is_absolute():
        candidate = Path(pointer).parent / candidate
    return candidate.resolve() if resolve else candidate.absolute()


def _regular_file_status(path: Path) -> str:
    """Classify a path without following symlinks for the contract checks."""

    try:
        if path.is_symlink():
            return "symlink"
        if path.is_file():
            return "regular"
        if path.exists():
            return "nonregular"
    except OSError:
        return "unreadable"
    return "missing"


def _selector_a2_a3_compatibility_document(pointer: Path, pointed: Path) -> dict[str, Any] | None:
    """Resolve the fixed A2/A3 receipts for the real plain-pointer contract.

    The pointer target directory is the only routing input.  Its basename
    carries source date, business date and producer run, so this function
    never searches receipt directories or chooses one by mtime.
    """

    pointer_path = Path(pointer).expanduser().absolute()
    if pointer_path.name != "CURRENT_SELECTOR_READY_PANEL.txt":
        return None
    if pointer_path.parent.name != "data_layer_interface_current":
        return None
    parent_match = re.fullmatch(
        r"selector_ready_current_to_(?P<source>\d{8})_(?P<business>\d{8})_(?P<run>\d{6})",
        pointed.parent.name,
    )
    file_match = re.fullmatch(r"selector_ready_current_to_(?P<source>\d{8})\.parquet", pointed.name)
    if parent_match is None or file_match is None or parent_match.group("source") != file_match.group("source"):
        return None
    state_root = pointer_path.parent.parent.parent.parent
    if state_root.name != "state":
        return None
    source_date = parent_match.group("source")
    business_date = parent_match.group("business")
    run_id = parent_match.group("run")
    native_formula_root = state_root / f"research_panel_daily/a_formula_runs/{business_date}_{run_id}"
    try:
        if native_formula_root.is_symlink():
            native_formula_root_status = "symlink"
        elif native_formula_root.is_dir():
            native_formula_root_status = "directory"
        elif native_formula_root.exists():
            native_formula_root_status = "nonregular"
        else:
            native_formula_root_status = "missing"
    except OSError:
        native_formula_root_status = "unreadable"

    def load(path: Path) -> dict[str, Any] | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        return dict(value) if isinstance(value, Mapping) else None

    native_formula_paths = {
        "meta": native_formula_root / "meta.json",
        "promote_manifest": native_formula_root / "promote_manifest.json",
        "generated_files_manifest": native_formula_root / "generated_files_manifest.csv",
        "promoted_parquet_quick_audit": native_formula_root / "promoted_parquet_quick_audit.json",
    }
    if native_formula_root_status != "missing":
        return {
            "selector_path": str(pointed),
            "_native_formula_compatibility": True,
            "_compatibility_selector_path": str(pointed),
            "_compatibility_selector_file_status": _regular_file_status(pointed),
            "_compatibility_state_root": str(state_root),
            "_compatibility_source_date": source_date,
            "_compatibility_business_date": business_date,
            "_compatibility_run_id": run_id,
            "_native_formula_root": str(native_formula_root),
            "_native_formula_root_status": native_formula_root_status,
            "_native_formula_paths": {name: str(path) for name, path in native_formula_paths.items()},
            "_native_formula_file_status": {
                name: _regular_file_status(path) for name, path in native_formula_paths.items()
            },
            "_native_formula_documents": {
                name: load(path)
                for name, path in native_formula_paths.items()
                if path.suffix.lower() == ".json"
            },
        }
    a2_path = state_root / (
        "research_panel_daily"
        f"/a2_exact_d1_runs/{business_date}_{run_id}/A2_V2_ACCEPTANCE_RECEIPT.json"
    )
    a2_run_root = a2_path.parent
    a3_path = state_root / (
        f"research_panel_daily/a3_authority_receipts/{business_date}T150000Z/a-{source_date}.json"
    )
    a2_v2_paths = {
        "a2": a2_path,
        "final_invariants": a2_run_root / "A2_V2_FINAL_INVARIANTS.json",
        "manifest": a2_run_root / "formal_panel_manifest.json",
        "receipt": a2_run_root / "formal_panel_receipt.json",
        "pointer_commit": a2_run_root / "pointer_commit_receipt.json",
    }

    a2 = load(a2_path)
    legacy_identity = (
        source_date == LEGACY_SELECTOR_COMPAT_SOURCE_DATE
        and business_date == LEGACY_SELECTOR_COMPAT_BUSINESS_DATE
        and run_id == LEGACY_SELECTOR_COMPAT_RUN_ID
    )
    a2_v2_hint = (
        isinstance(a2, Mapping)
        and bool(a2.get("pit_cutoff"))
        and bool(a2.get("target_trade_date"))
        and bool(a2.get("run_id"))
    ) or (
        not legacy_identity
        and any(
            name != "a2" and _regular_file_status(path) == "regular"
            for name, path in a2_v2_paths.items()
        )
    )
    if a2_v2_hint:
        return {
            "selector_path": str(pointed),
            "_a2_v2_compatibility": True,
            "_compatibility_selector_path": str(pointed),
            "_compatibility_selector_file_status": _regular_file_status(pointed),
            "_compatibility_state_root": str(state_root),
            "_compatibility_source_date": source_date,
            "_compatibility_business_date": business_date,
            "_compatibility_run_id": run_id,
            "_compatibility_a2_path": str(a2_path),
            "_compatibility_a2_file_status": _regular_file_status(a2_path),
            "_compatibility_a2": a2,
            "_compatibility_a2_v2_paths": {name: str(path) for name, path in a2_v2_paths.items()},
            "_compatibility_a2_v2_file_status": {
                name: _regular_file_status(path) for name, path in a2_v2_paths.items()
            },
            "_compatibility_a2_v2": {
                name: load(path) for name, path in a2_v2_paths.items() if name != "a2"
            },
        }
    return {
        "selector_path": str(pointed),
        "_a2_a3_compatibility": True,
        "_compatibility_selector_path": str(pointed),
        "_compatibility_selector_file_status": _regular_file_status(pointed),
        "_compatibility_state_root": str(state_root),
        "_compatibility_source_date": source_date,
        "_compatibility_business_date": business_date,
        "_compatibility_run_id": run_id,
        "_compatibility_a2_path": str(a2_path),
        "_compatibility_a3_path": str(a3_path),
        "_compatibility_a2_file_status": _regular_file_status(a2_path),
        "_compatibility_a3_file_status": _regular_file_status(a3_path),
        "_compatibility_a2": a2,
        "_compatibility_a3": load(a3_path),
    }


def _selector_pointer_document(pointer: Path) -> dict[str, Any]:
    """Read a selector pointer and its optional signed metadata sidecar.

    The upstream producer historically emitted a one-line text pointer.  That
    format remains readable for diagnostics, but it is deliberately not a
    READY contract: a caller must provide a JSON pointer or a JSON sidecar
    carrying the exact-date/PIT/SHA ledger.
    """

    try:
        text = pointer.read_text(encoding="utf-8-sig").strip()
    except (OSError, UnicodeError):
        return {}
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, Mapping):
        document = dict(parsed)
        nested = document.get("metadata")
        if isinstance(nested, Mapping):
            merged = dict(nested)
            merged.update(document)
            document = merged
        return document

    # Preserve the lexical target for the compatibility contract so a
    # symlink cannot be silently resolved into an apparently regular file.
    pointed = _selector_target_from_document(pointer, {"selector_path": text}, resolve=False)
    if pointed is not None:
        compatibility = _selector_a2_a3_compatibility_document(pointer, pointed)
        if compatibility is not None:
            return compatibility

    # Plain pointers may be accompanied by a producer-owned JSON contract.
    # We never infer metadata from the parquet itself and never use another
    # date's sidecar as a fallback.
    sidecars = (
        pointer.with_suffix(".json"),
        pointer.with_name(pointer.name + ".json"),
        pointer.with_name(f"{pointer.stem}.metadata.json"),
    )
    for sidecar in sidecars:
        if not sidecar.is_file():
            continue
        try:
            parsed_sidecar = json.loads(sidecar.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if isinstance(parsed_sidecar, Mapping):
            document = dict(parsed_sidecar)
            pointer_target = _selector_target_from_document(pointer, {"selector_path": text})
            declared_value = _selector_field(document, "selector_path", "path", "target", "panel_path")
            declared_target = (
                _selector_target_from_document(pointer, {"selector_path": declared_value})
                if declared_value
                else None
            )
            # The plain pointer text is authoritative.  A sidecar can add
            # signed metadata, but it may not redirect the consumer to a
            # different selector artifact.
            document["selector_path"] = text
            document["_pointer_text_target"] = str(pointer_target) if pointer_target else ""
            if declared_value:
                document["_sidecar_declared_target"] = str(declared_target) if declared_target else ""
                if pointer_target is None or declared_target != pointer_target:
                    document["_pointer_path_mismatch"] = True
            document["_plain_pointer_with_metadata"] = True
            return document
    return {"selector_path": text, "_legacy_plain_pointer": True}


def _selector_field(document: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = document.get(name)
        if value not in (None, ""):
            return value
    return None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _selector_date(value: Any) -> str | None:
    try:
        return normalize_trade_date(str(value))
    except (TypeError, ValueError):
        return None


def _selector_cutoff_date(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or "T" not in text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.strftime("%Y%m%d")


def _parquet_has_date(path: Path, target_date: str) -> bool:
    try:
        import pyarrow.parquet as parquet

        table = parquet.read_table(path, columns=["trade_date"])
        values = table.column("trade_date").to_pylist()
    except Exception:
        return False
    normalized = {str(value).replace("-", "")[:8] for value in values}
    return target_date in normalized


def _parquet_metadata(path: Path) -> dict[str, Any] | None:
    """Read only Parquet metadata/statistics needed by the exact selector gate.

    A missing ``trade_date`` column or any row group without complete
    min/max statistics is a hard failure.  Falling back to a full table scan
    would make the runtime gate both expensive and less deterministic.
    """

    try:
        import pyarrow.parquet as parquet

        metadata = parquet.ParquetFile(path).metadata
        if metadata is None:
            return None
        trade_date_index = None
        for index in range(len(metadata.schema)):
            if metadata.schema.column(index).name == "trade_date":
                trade_date_index = index
                break
        if trade_date_index is None:
            return None
        max_date: str | None = None
        for row_group_index in range(metadata.num_row_groups):
            column = metadata.row_group(row_group_index).column(trade_date_index)
            statistics = column.statistics
            if statistics is None or not bool(getattr(statistics, "has_min_max", False)):
                return None
            if statistics.min is None or statistics.max is None:
                return None
            if getattr(statistics, "null_count", 0) not in (None, 0):
                return None
            minimum = _selector_date(statistics.min)
            maximum = _selector_date(statistics.max)
            if minimum is None or maximum is None or minimum > maximum:
                return None
            if max_date is None or maximum > max_date:
                max_date = maximum
        if max_date is None:
            return None
        return {"rows": int(metadata.num_rows), "max_date": max_date}
    except Exception:
        return None


def _selector_receipt_identity(document: Any, *, direct: bool = False) -> dict[str, Any] | None:
    if not isinstance(document, Mapping):
        return None
    if direct:
        fields = {
            "path": document.get("selector_path"),
            "selector_sha256": document.get("selector_sha256"),
            "size": document.get("selector_size"),
            "rows": document.get("selector_rows"),
            "max_date": document.get("selector_max_date"),
        }
    else:
        fields = {
            "path": document.get("path"),
            "selector_sha256": document.get("sha256"),
            "size": document.get("size"),
            "rows": document.get("rows"),
            "max_date": document.get("max_date"),
        }
    try:
        size = int(fields["size"])
        rows = int(fields["rows"])
    except (TypeError, ValueError):
        return None
    sha = str(fields["selector_sha256"] or "").lower()
    max_date = _selector_date(fields["max_date"])
    path = str(fields["path"] or "")
    if not path or len(sha) != 64 or any(char not in "0123456789abcdef" for char in sha):
        return None
    if size <= 0 or rows <= 0 or max_date is None:
        return None
    return {
        "path": path,
        "selector_sha256": sha,
        "size": size,
        "rows": rows,
        "max_date": max_date,
    }


def _selector_identity_matches(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return all(left.get(field) == right.get(field) for field in ("path", "selector_sha256", "size", "rows", "max_date"))


def _selector_pointer_identity(path: Path) -> dict[str, Any] | None:
    """Return the immutable identity of a plain pointer file."""

    if _regular_file_status(path) != "regular":
        return None
    try:
        payload = path.read_bytes()
        stat = path.stat()
    except OSError:
        return None
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return {
        "bytes": text,
        "mode": stat.st_mode & 0o777,
        "path": str(path),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": len(payload),
    }


def _selector_pointer_identity_matches(document: Any, expected: Mapping[str, Any]) -> bool:
    if not isinstance(document, Mapping):
        return False
    if document.get("path") != expected.get("path"):
        return False
    if document.get("bytes") != expected.get("bytes"):
        return False
    if str(document.get("sha256") or "").lower() != str(expected.get("sha256") or "").lower():
        return False
    try:
        return int(document.get("size")) == int(expected.get("size"))
    except (TypeError, ValueError):
        return False


def _selector_a2_v2_safety_safe(document: Any) -> bool:
    if not isinstance(document, Mapping):
        return False
    if any(document.get(field) is not False for field in SELECTOR_SAFETY_FIELDS):
        return False
    safety = document.get("safety")
    if safety is None:
        return True
    return isinstance(safety, Mapping) and all(safety.get(field) is False for field in SELECTOR_SAFETY_FIELDS)


def _native_relative_file(root: Path, relative: Any) -> Path | None:
    """Resolve one ledger-relative file without following an escape or link."""

    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        return None
    candidate = root / relative
    try:
        resolved_root = root.resolve()
        resolved_candidate = candidate.resolve()
        if resolved_candidate != candidate.absolute():
            return None
        resolved_candidate.relative_to(resolved_root)
    except (OSError, ValueError):
        return None
    return candidate


def _native_formula_ledger(
    root: Path,
    ledger_path: Path,
    *,
    required: frozenset[str],
) -> tuple[dict[str, dict[str, Any]] | None, str | None]:
    """Verify every path/hash in the native promotion's generated ledger."""

    if _regular_file_status(ledger_path) != "regular":
        return None, "SELECTOR_NATIVE_FORMULA_LEDGER_NOT_REGULAR"
    entries: dict[str, dict[str, Any]] = {}
    try:
        with ledger_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                path_value = row.get("path") or row.get("\ufeffpath")
                relative = row.get("relative")
                if not isinstance(relative, str) or relative not in required:
                    continue
                candidate = _native_relative_file(root, relative)
                if candidate is None or str(path_value or "") != str(candidate):
                    return None, "SELECTOR_NATIVE_FORMULA_LEDGER_PATH_MISMATCH"
                relative_text = str(relative)
                if relative_text in entries:
                    return None, "SELECTOR_NATIVE_FORMULA_LEDGER_DUPLICATE"
                if _regular_file_status(candidate) != "regular":
                    return None, "SELECTOR_NATIVE_FORMULA_LEDGER_FILE_NOT_REGULAR"
                declared_sha = str(row.get("sha256") or "").lower()
                if len(declared_sha) != 64 or any(char not in "0123456789abcdef" for char in declared_sha):
                    return None, "SELECTOR_NATIVE_FORMULA_LEDGER_SHA_INVALID"
                actual_sha = _sha256_file(candidate)
                if actual_sha != declared_sha:
                    return None, "SELECTOR_NATIVE_FORMULA_LEDGER_SHA_MISMATCH"
                try:
                    declared_size_mb = float(row.get("size_mb"))
                    actual_size_mb = candidate.stat().st_size / (1024 * 1024)
                except (OSError, TypeError, ValueError):
                    return None, "SELECTOR_NATIVE_FORMULA_LEDGER_SIZE_INVALID"
                if abs(declared_size_mb - actual_size_mb) > 0.000001:
                    return None, "SELECTOR_NATIVE_FORMULA_LEDGER_SIZE_MISMATCH"
                entries[relative_text] = {
                    "path": str(candidate),
                    "sha256": actual_sha,
                    "size": candidate.stat().st_size,
                }
    except (OSError, UnicodeError, csv.Error):
        return None, "SELECTOR_NATIVE_FORMULA_LEDGER_READ_FAILED"
    if not required.issubset(entries):
        return None, "SELECTOR_NATIVE_FORMULA_LEDGER_INCOMPLETE"
    return entries, None


def _native_shared_reader(shared_package_root: Path) -> Any | None:
    """Load the verified shared consumer only from the configured package root."""

    package_root = shared_package_root / "shared_data"
    if _regular_file_status(package_root / "__init__.py") != "regular":
        return None
    try:
        loaded = sys.modules.get("shared_data.consumer")
        if loaded is None:
            package_text = str(shared_package_root)
            inserted = package_text not in sys.path
            if inserted:
                sys.path.insert(0, package_text)
            try:
                loaded = importlib.import_module("shared_data.consumer")
            finally:
                if inserted and sys.path and sys.path[0] == package_text:
                    sys.path.pop(0)
        module_file = Path(str(getattr(loaded, "__file__", ""))).resolve()
        if module_file.parent != package_root.resolve():
            return None
        reader = getattr(loaded, "read_verified_latest", None)
        return reader if callable(reader) else None
    except (ImportError, OSError, RuntimeError):
        return None


def _native_shared_provenance(
    shared_package_root: Path | None,
    *,
    source_date: str,
    selector_sha256: str,
    expected_target_trade_date: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve one indexed, verified A-share D1 handoff for the native panel."""

    if shared_package_root is None:
        return None, "SELECTOR_NATIVE_SHARED_PACKAGE_ROOT_MISSING"
    package_root = Path(shared_package_root).expanduser().absolute()
    if package_root.is_symlink() or not package_root.is_dir():
        return None, "SELECTOR_NATIVE_SHARED_PACKAGE_ROOT_NOT_REGULAR"
    data_root = package_root / ".runtime" / "data"
    if data_root.is_symlink() or not data_root.is_dir():
        return None, "SELECTOR_NATIVE_SHARED_DATA_ROOT_NOT_REGULAR"
    latest_path = data_root / "latest.json"
    if _regular_file_status(latest_path) != "regular":
        return None, "SELECTOR_NATIVE_SHARED_LATEST_NOT_REGULAR"
    try:
        latest_bytes = latest_path.read_bytes()
        latest = json.loads(latest_bytes.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "SELECTOR_NATIVE_SHARED_LATEST_INVALID"
    if not isinstance(latest, Mapping) or latest.get("schema_version") != NATIVE_SHARED_LATEST_SCHEMA:
        return None, "SELECTOR_NATIVE_SHARED_LATEST_SCHEMA_MISMATCH"
    entries = latest.get("entries")
    if not isinstance(entries, Mapping):
        return None, "SELECTOR_NATIVE_SHARED_LATEST_ENTRIES_INVALID"

    matches: list[tuple[str, Mapping[str, Any], Mapping[str, Any], Path]] = []
    for key, entry in entries.items():
        if not isinstance(key, str) or "/" not in key or not isinstance(entry, Mapping):
            continue
        key_date, key_role = key.split("/", 1)
        if key_role != NATIVE_FORMULA_ROLE:
            continue
        if _selector_date(key_date) is None:
            continue
        manifest_path = _native_relative_file(data_root, entry.get("manifest_relative"))
        if manifest_path is None or _regular_file_status(manifest_path) != "regular":
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        if not isinstance(manifest, Mapping):
            continue
        provenance = manifest.get("provenance")
        if (
            manifest.get("signal_date") == source_date
            and isinstance(provenance, Mapping)
            and provenance.get("signal_date") == source_date
            and str(provenance.get("panel_sha256") or "").lower() == selector_sha256
        ):
            matches.append((key_date, entry, manifest, manifest_path))
    if len(matches) != 1:
        return None, "SELECTOR_NATIVE_SHARED_PROVENANCE_NOT_UNIQUE" if len(matches) > 1 else "SELECTOR_NATIVE_SHARED_PROVENANCE_NOT_FOUND"

    key_date, latest_entry, manifest, manifest_path = matches[0]
    target_trade_date = _selector_date(manifest.get("trade_date"))
    if target_trade_date is None or target_trade_date != _selector_date(key_date) or target_trade_date <= source_date:
        return None, "SELECTOR_NATIVE_SHARED_DATE_IDENTITY_MISMATCH"
    if expected_target_trade_date is not None and target_trade_date != _selector_date(expected_target_trade_date):
        return None, "SELECTOR_NATIVE_TARGET_TRADE_DATE_MISMATCH"
    if manifest.get("schema_version") != NATIVE_SHARED_MANIFEST_SCHEMA:
        return None, "SELECTOR_NATIVE_SHARED_MANIFEST_SCHEMA_MISMATCH"
    if manifest.get("role") != NATIVE_FORMULA_ROLE:
        return None, "SELECTOR_NATIVE_SHARED_ROLE_MISMATCH"
    if manifest.get("temporal_cutoff_safe") is not True:
        return None, "SELECTOR_NATIVE_SHARED_TEMPORAL_CUTOFF_UNSAFE"
    if manifest.get("production_allowed") is not False or manifest.get("buy_gate_updated") is not False or manifest.get("orders_sent") is not False:
        return None, "SELECTOR_NATIVE_SHARED_SAFETY_FLAGS_UNSAFE"
    provenance = manifest.get("provenance")
    if not isinstance(provenance, Mapping):
        return None, "SELECTOR_NATIVE_SHARED_PROVENANCE_MISSING"
    if str(provenance.get("panel_sha256") or "").lower() != selector_sha256:
        return None, "SELECTOR_NATIVE_SHARED_PANEL_SHA_MISMATCH"
    if str(latest_entry.get("status") or "") != "READY":
        return None, "SELECTOR_NATIVE_SHARED_LATEST_NOT_READY"
    if latest_entry.get("run_id") in (None, ""):
        return None, "SELECTOR_NATIVE_SHARED_RUN_ID_MISSING"

    reader = _native_shared_reader(package_root)
    if reader is None:
        return None, "SELECTOR_NATIVE_SHARED_READER_UNAVAILABLE"
    try:
        verified = reader(data_root, target_trade_date, NATIVE_FORMULA_ROLE)
    except Exception:
        return None, "SELECTOR_NATIVE_SHARED_TRIO_NOT_VERIFIED"
    verified_manifest = getattr(verified, "manifest", None)
    verified_receipt = getattr(verified, "receipt", None)
    verified_latest = getattr(verified, "latest", None)
    if not isinstance(verified_manifest, Mapping) or not isinstance(verified_receipt, Mapping) or not isinstance(verified_latest, Mapping):
        return None, "SELECTOR_NATIVE_SHARED_TRIO_NOT_VERIFIED"
    if verified_manifest != manifest or verified_latest != latest_entry:
        return None, "SELECTOR_NATIVE_SHARED_READBACK_MISMATCH"
    if verified_receipt.get("schema_version") != NATIVE_SHARED_RECEIPT_SCHEMA or verified_receipt.get("status") != "READY":
        return None, "SELECTOR_NATIVE_SHARED_RECEIPT_NOT_READY"
    if any(verified_receipt.get(field) is not False for field in SELECTOR_SAFETY_FIELDS):
        return None, "SELECTOR_NATIVE_SHARED_RECEIPT_SAFETY_UNSAFE"
    try:
        latest_sha = hashlib.sha256(latest_bytes).hexdigest()
        manifest_sha = _sha256_file(manifest_path)
        receipt_path = Path(str(getattr(verified, "receipt_path", "")))
        artifact_path = Path(str(getattr(verified, "artifact_path", "")))
        receipt_sha = _sha256_file(receipt_path)
        artifact_sha = _sha256_file(artifact_path)
    except (OSError, TypeError):
        return None, "SELECTOR_NATIVE_SHARED_SHA_READ_FAILED"
    if latest_entry.get("manifest_sha256") != manifest_sha or latest_entry.get("receipt_sha256") != receipt_sha:
        return None, "SELECTOR_NATIVE_SHARED_LATEST_SHA_MISMATCH"
    if manifest.get("artifact_sha256") != artifact_sha or verified_receipt.get("artifact_sha256") != artifact_sha:
        return None, "SELECTOR_NATIVE_SHARED_ARTIFACT_SHA_MISMATCH"
    return {
        "latest_path": str(latest_path),
        "latest_sha256": latest_sha,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "receipt_path": str(receipt_path),
        "receipt_sha256": receipt_sha,
        "artifact_path": str(artifact_path),
        "artifact_sha256": artifact_sha,
        "role": NATIVE_FORMULA_ROLE,
        "run_id": str(latest_entry.get("run_id") or ""),
        "source_date": source_date,
        "trade_date": target_trade_date,
        "signal_date": source_date,
        "panel_sha256": selector_sha256,
        "cutoff_at": str(manifest.get("cutoff_at") or ""),
        "captured_at": str(manifest.get("captured_at") or ""),
        "available_at": str(verified_receipt.get("finished_at") or ""),
        "temporal_cutoff_safe": True,
    }, None


def _inspect_native_formula_compatibility(
    pointer: Path,
    pointed: Path,
    document: Mapping[str, Any],
    source_date: str,
    *,
    expected_path: Path | None,
    expected_sha256: str | None,
    expected_target_trade_date: str | None,
    expected_cutoff: str | None,
    shared_package_root: Path | None,
) -> dict[str, Any]:
    """Validate a native formula promotion plus the shared D1 handoff."""

    def fail(reason: str, **extra: Any) -> dict[str, Any]:
        return {"ready": False, "reason": reason, **extra}

    source = _selector_date(source_date)
    run_date = _selector_date(document.get("_compatibility_business_date"))
    run_component = str(document.get("_compatibility_run_id") or "")
    if source is None or run_date is None or run_date < source or not re.fullmatch(r"\d{6}", run_component):
        return fail(
            "SELECTOR_NATIVE_FORMULA_POINTER_IDENTITY_INVALID",
            source_date=str(source_date),
            run_date=str(document.get("_compatibility_business_date") or ""),
            run_id=run_component,
        )
    if _selector_date(document.get("_compatibility_source_date")) != source:
        return fail("SELECTOR_NATIVE_FORMULA_SOURCE_DATE_MISMATCH")
    if expected_cutoff is not None:
        return fail(
            "SELECTOR_NATIVE_CUTOFF_TIMESTAMP_UNPROVEN",
            native_cutoff_at="",
            expected_cutoff=str(expected_cutoff),
        )
    if _regular_file_status(pointer) != "regular":
        return fail("SELECTOR_POINTER_NOT_REGULAR")
    selector_status = str(document.get("_compatibility_selector_file_status") or "missing")
    if selector_status != "regular":
        return fail("SELECTOR_PATH_NOT_REGULAR", path_status=selector_status, path=str(pointed))
    formula_root = Path(str(document.get("_native_formula_root") or ""))
    if str(document.get("_native_formula_root_status") or "") != "directory":
        return fail("SELECTOR_NATIVE_FORMULA_ROOT_NOT_REGULAR", path_status=document.get("_native_formula_root_status"))
    paths = document.get("_native_formula_paths")
    statuses = document.get("_native_formula_file_status")
    documents = document.get("_native_formula_documents")
    if not isinstance(paths, Mapping) or not isinstance(statuses, Mapping) or not isinstance(documents, Mapping):
        return fail("SELECTOR_NATIVE_FORMULA_AUTHORITY_MISSING")
    for name in ("meta", "promote_manifest", "generated_files_manifest", "promoted_parquet_quick_audit"):
        if statuses.get(name) != "regular":
            return fail("SELECTOR_NATIVE_FORMULA_AUTHORITY_NOT_REGULAR", authority=name, path_status=statuses.get(name))
    meta = documents.get("meta")
    promote = documents.get("promote_manifest")
    audit = documents.get("promoted_parquet_quick_audit")
    if not isinstance(meta, Mapping) or not isinstance(promote, Mapping) or not isinstance(audit, Mapping):
        return fail("SELECTOR_NATIVE_FORMULA_AUTHORITY_MISSING")
    if meta.get("task_name") != NATIVE_FORMULA_TASK or meta.get("status") != "PASS" or meta.get("final_status") != NATIVE_FORMULA_FINAL_STATUS:
        return fail("SELECTOR_NATIVE_FORMULA_META_NOT_PASS")
    for field in ("formula_gate_status", "candidate_stage_status", "promote_stage_status"):
        if meta.get(field) != "PASS":
            return fail("SELECTOR_NATIVE_FORMULA_META_STAGE_NOT_PASS", field=field)
    if meta.get("run_dir") != str(formula_root) or meta.get("selector_final_path") != str(pointed):
        return fail("SELECTOR_NATIVE_FORMULA_META_PATH_MISMATCH")
    if _selector_date(meta.get("tdx_max_trade_date")) != source or _selector_date(meta.get("selector_after_max")) != source:
        return fail("SELECTOR_NATIVE_FORMULA_META_MAX_DATE_MISMATCH")
    try:
        native_rows = int(meta.get("selector_rows_after"))
    except (TypeError, ValueError):
        return fail("SELECTOR_NATIVE_FORMULA_META_ROWS_INVALID")
    if native_rows <= 0:
        return fail("SELECTOR_NATIVE_FORMULA_META_ROWS_INVALID")
    selector_after = promote.get("selector_after")
    if not isinstance(selector_after, Mapping):
        return fail("SELECTOR_NATIVE_FORMULA_PROMOTE_SELECTOR_MISSING")
    if (
        selector_after.get("pointer") != str(pointer)
        or selector_after.get("exists") is not True
        or selector_after.get("has_bom") is not False
        or selector_after.get("target") != str(pointed)
        or selector_after.get("target_exists") is not True
        or promote.get("selector_output") != str(pointed)
    ):
        return fail("SELECTOR_NATIVE_FORMULA_PROMOTE_SELECTOR_MISMATCH")
    selector_audit = audit.get("selector")
    if not isinstance(selector_audit, Mapping):
        return fail("SELECTOR_NATIVE_FORMULA_AUDIT_SELECTOR_MISSING")
    if (
        selector_audit.get("role") != "selector_current_after_promote"
        or selector_audit.get("path") != str(pointed)
        or selector_audit.get("exists") is not True
        or selector_audit.get("status") != "PASS"
        or selector_audit.get("future_forbidden_columns") != []
        or selector_audit.get("trade_date_null_count") != 0
        or _selector_date(selector_audit.get("trade_date_max")) != source
    ):
        return fail("SELECTOR_NATIVE_FORMULA_AUDIT_SELECTOR_MISMATCH")
    try:
        audit_rows = int(selector_audit.get("row_count"))
    except (TypeError, ValueError):
        return fail("SELECTOR_NATIVE_FORMULA_AUDIT_ROWS_INVALID")
    if audit_rows <= 0 or audit_rows != native_rows:
        return fail("SELECTOR_NATIVE_FORMULA_ROWS_MISMATCH", audit_rows=audit_rows, meta_rows=native_rows)
    if expected_path is not None and pointed != Path(expected_path).expanduser().resolve():
        return fail("SELECTOR_PATH_MISMATCH", path=str(pointed))
    try:
        actual_sha = _sha256_file(pointed)
        actual_size = pointed.stat().st_size
    except OSError:
        return fail("SELECTOR_SHA_READ_FAILED")
    if expected_sha256 is not None and actual_sha != str(expected_sha256).lower():
        return fail("SELECTOR_SHA_NOT_EXPECTED", actual_sha256=actual_sha)
    parquet_metadata = _parquet_metadata(pointed)
    if parquet_metadata is None:
        return fail("SELECTOR_PARQUET_METADATA_UNAVAILABLE")
    parquet_rows = parquet_metadata.get("rows")
    parquet_max = _selector_date(parquet_metadata.get("max_date"))
    if parquet_rows != audit_rows:
        return fail("SELECTOR_NATIVE_FORMULA_PARQUET_ROWS_MISMATCH", actual_rows=parquet_rows, expected_rows=audit_rows)
    if parquet_max != source:
        return fail("SELECTOR_NATIVE_FORMULA_PARQUET_MAX_DATE_MISMATCH", actual_max_date=parquet_max)

    ledger_paths = {str(name): Path(str(value)) for name, value in paths.items()}
    ledger, ledger_error = _native_formula_ledger(
        formula_root,
        ledger_paths["generated_files_manifest"],
        required=frozenset({"meta.json", "promote_manifest.json", "promoted_parquet_quick_audit.json"}),
    )
    if ledger is None:
        return fail(ledger_error or "SELECTOR_NATIVE_FORMULA_LEDGER_INVALID")
    meta_sha = ledger["meta.json"]["sha256"]
    promote_sha = ledger["promote_manifest.json"]["sha256"]
    audit_sha = ledger["promoted_parquet_quick_audit.json"]["sha256"]
    shared, shared_error = _native_shared_provenance(
        shared_package_root,
        source_date=source,
        selector_sha256=actual_sha,
        expected_target_trade_date=expected_target_trade_date,
    )
    if shared is None:
        return fail(shared_error or "SELECTOR_NATIVE_SHARED_PROVENANCE_INVALID")
    target_trade_date = str(shared["trade_date"])
    pointer_identity = _selector_pointer_identity(pointer)
    if pointer_identity is None:
        return fail("SELECTOR_POINTER_NOT_REGULAR")
    return {
        "ready": True,
        "reason": "SELECTOR_NATIVE_FORMULA_READY",
        "compatibility": "NATIVE_FORMULA_PROMOTION",
        "origin": NATIVE_FORMULA_ORIGIN,
        "path": str(pointed),
        "selector_sha256": actual_sha,
        "selector_size": actual_size,
        "selector_rows": audit_rows,
        "selector_max_date": source,
        "selector_metadata_rows": parquet_rows,
        "selector_metadata_max_date": parquet_max,
        "source_date": source,
        "run_date": run_date,
        "run_id": f"{run_date}_{run_component}",
        "target_trade_date": target_trade_date,
        "pit_date": source,
        "cutoff": str(shared.get("cutoff_at") or ""),
        "cutoff_at": str(shared.get("cutoff_at") or ""),
        "captured_at": str(shared.get("captured_at") or ""),
        "available_at": str(shared.get("available_at") or ""),
        "pit_safe": True,
        "temporal_cutoff_safe": True,
        "pre_cutoff_capture_verified": False,
        "pointer_path": str(pointer),
        "pointer_sha256": pointer_identity["sha256"],
        "native_formula_root": str(formula_root),
        "native_meta_path": str(ledger_paths["meta"]),
        "native_meta_sha256": meta_sha,
        "native_promote_manifest_path": str(ledger_paths["promote_manifest"]),
        "native_promote_manifest_sha256": promote_sha,
        "native_generated_files_manifest_path": str(ledger_paths["generated_files_manifest"]),
        "native_generated_files_manifest_sha256": _sha256_file(ledger_paths["generated_files_manifest"]),
        "native_promoted_audit_path": str(ledger_paths["promoted_parquet_quick_audit"]),
        "native_promoted_audit_sha256": audit_sha,
        "shared_package_root": str(shared_package_root) if shared_package_root else "",
        "shared_latest_path": shared["latest_path"],
        "shared_latest_sha256": shared["latest_sha256"],
        "shared_manifest_path": shared["manifest_path"],
        "shared_manifest_sha256": shared["manifest_sha256"],
        "shared_receipt_path": shared["receipt_path"],
        "shared_receipt_sha256": shared["receipt_sha256"],
        "shared_artifact_path": shared["artifact_path"],
        "shared_artifact_sha256": shared["artifact_sha256"],
        "shared_run_id": shared["run_id"],
        "shared_role": shared["role"],
        "shared_signal_date": shared["signal_date"],
        "shared_trade_date": shared["trade_date"],
        "shared_cutoff_at": shared["cutoff_at"],
        "shared_captured_at": shared["captured_at"],
        "shared_available_at": shared["available_at"],
        "shared_temporal_cutoff_safe": shared["temporal_cutoff_safe"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "evaluation_future": 0,
    }


def _inspect_a2_v2_compatibility(
    pointer: Path,
    pointed: Path,
    document: Mapping[str, Any],
    source_date: str,
    *,
    expected_path: Path | None,
    expected_sha256: str | None,
    expected_target_trade_date: str | None,
    expected_cutoff: str | None,
) -> dict[str, Any]:
    """Validate the current A2 V2 chain without requiring a withheld A3."""

    def fail(reason: str, **extra: Any) -> dict[str, Any]:
        return {"ready": False, "reason": reason, **extra}

    source = _selector_date(source_date)
    business = _selector_date(document.get("_compatibility_business_date"))
    run_component = str(document.get("_compatibility_run_id") or "")
    run_id = f"{business}_{run_component}" if business is not None else ""
    if source is None or business is None or not re.fullmatch(r"\d{8}", business) or not re.fullmatch(r"\d{6}", run_component):
        return fail(
            "SELECTOR_A2_V2_POINTER_IDENTITY_INVALID",
            source_date=str(source_date),
            business_date=str(document.get("_compatibility_business_date") or ""),
            run_id=run_id,
        )
    if _selector_date(document.get("_compatibility_source_date")) != source:
        return fail("SELECTOR_A2_V2_POINTER_SOURCE_MISMATCH")
    expected_target = _selector_date(expected_target_trade_date) if expected_target_trade_date is not None else business
    if expected_target is None or expected_target != business or expected_target <= source:
        return fail(
            "SELECTOR_A2_V2_TARGET_TRADE_DATE_MISMATCH",
            target_trade_date=business,
            expected_target_trade_date=expected_target,
        )

    statuses = {
        "a2": str(document.get("_compatibility_a2_file_status") or "missing"),
        **{
            f"{name}_authority": str(status or "missing")
            for name, status in (document.get("_compatibility_a2_v2_file_status") or {}).items()
            if name != "a2"
        },
    }
    for name, status in statuses.items():
        if status != "regular":
            return fail("SELECTOR_A2_V2_AUTHORITY_NOT_REGULAR", authority=name, path_status=status)
    a2 = document.get("_compatibility_a2")
    v2_documents = document.get("_compatibility_a2_v2")
    if not isinstance(a2, Mapping) or not isinstance(v2_documents, Mapping):
        return fail("SELECTOR_A2_V2_AUTHORITY_MISSING")
    invariants = v2_documents.get("final_invariants")
    manifest = v2_documents.get("manifest")
    receipt = v2_documents.get("receipt")
    pointer_commit = v2_documents.get("pointer_commit")
    if not all(isinstance(value, Mapping) for value in (invariants, manifest, receipt, pointer_commit)):
        return fail("SELECTOR_A2_V2_AUTHORITY_MISSING")

    if a2.get("schema") != SELECTOR_A2_SCHEMA:
        return fail("SELECTOR_A2_V2_SCHEMA_MISMATCH", schema=str(a2.get("schema") or ""))
    if a2.get("status") != SELECTOR_A2_STATUS:
        return fail("SELECTOR_A2_V2_STATUS_NOT_READY", status=str(a2.get("status") or ""))
    if invariants.get("schema") != SELECTOR_A2_FINAL_SCHEMA:
        return fail("SELECTOR_A2_V2_FINAL_INVARIANTS_SCHEMA_MISMATCH")
    if invariants.get("status") != SELECTOR_A2_PASS_STATUS:
        return fail("SELECTOR_A2_V2_FINAL_INVARIANTS_NOT_PASS")
    if manifest.get("schema") != SELECTOR_A2_MANIFEST_SCHEMA:
        return fail("SELECTOR_A2_V2_MANIFEST_SCHEMA_MISMATCH")
    if receipt.get("schema") != SELECTOR_A2_RECEIPT_SCHEMA:
        return fail("SELECTOR_A2_V2_RECEIPT_SCHEMA_MISMATCH")
    if receipt.get("status") != SELECTOR_A2_RECEIPT_STATUS:
        return fail("SELECTOR_A2_V2_RECEIPT_NOT_READY")
    if pointer_commit.get("schema") != SELECTOR_A2_POINTER_COMMIT_SCHEMA:
        return fail("SELECTOR_A2_V2_POINTER_COMMIT_SCHEMA_MISMATCH")
    if pointer_commit.get("commit_ok") is not True or pointer_commit.get("rollback_performed") is not False:
        return fail("SELECTOR_A2_V2_POINTER_COMMIT_NOT_VALID")

    authority_documents = {
        "a2": a2,
        "final_invariants": invariants,
        "manifest": manifest,
        "receipt": receipt,
        "pointer_commit": pointer_commit,
    }
    for name, authority in authority_documents.items():
        if authority.get("origin") != SELECTOR_ORIGIN:
            return fail("SELECTOR_A2_V2_ORIGIN_MISMATCH", authority=name)
        if not _selector_a2_v2_safety_safe(authority):
            return fail("SELECTOR_A2_V2_SAFETY_FLAGS_UNSAFE", authority=name)
        if "source_date" in authority and _selector_date(authority.get("source_date")) != source:
            return fail("SELECTOR_A2_V2_SOURCE_DATE_MISMATCH", authority=name)
        if "business_date" in authority and _selector_date(authority.get("business_date")) != source:
            return fail("SELECTOR_A2_V2_BUSINESS_DATE_MISMATCH", authority=name)
        if "target_date" in authority and _selector_date(authority.get("target_date")) != source:
            return fail("SELECTOR_A2_V2_TARGET_DATE_MISMATCH", authority=name)
        if "target_trade_date" in authority and _selector_date(authority.get("target_trade_date")) != business:
            return fail("SELECTOR_A2_V2_TARGET_TRADE_DATE_MISMATCH", authority=name)
        if "run_id" in authority and str(authority.get("run_id") or "") != run_id:
            return fail("SELECTOR_A2_V2_RUN_ID_MISMATCH", authority=name)
        if "pit_cutoff" in authority:
            if _selector_cutoff_date(authority.get("pit_cutoff")) != source:
                return fail("SELECTOR_A2_V2_PIT_CUTOFF_DATE_MISMATCH", authority=name)
            if expected_cutoff is not None and str(authority.get("pit_cutoff")) != str(expected_cutoff):
                return fail("SELECTOR_A2_V2_PIT_CUTOFF_MISMATCH", authority=name)

    evaluation = a2.get("evaluation")
    if not isinstance(evaluation, Mapping) or evaluation.get("future") != 0:
        return fail("SELECTOR_A2_V2_FUTURE_ROWS_PRESENT")
    if invariants.get("future_rows") != 0:
        return fail("SELECTOR_A2_V2_FINAL_INVARIANTS_FUTURE_ROWS")
    manifest_selector = manifest.get("entries", {}).get("selector") if isinstance(manifest.get("entries"), Mapping) else None
    candidate_selector = a2.get("candidates", {}).get("selector") if isinstance(a2.get("candidates"), Mapping) else None
    candidate_identity = _selector_receipt_identity(candidate_selector)
    manifest_identity = _selector_receipt_identity(manifest_selector)
    if candidate_identity is None or manifest_identity is None:
        return fail("SELECTOR_A2_V2_SELECTOR_IDENTITY_MISSING")
    if not _selector_identity_matches(candidate_identity, manifest_identity):
        return fail("SELECTOR_A2_V2_SELECTOR_IDENTITY_MISMATCH")
    if candidate_selector.get("future_rows") != 0 or manifest_selector.get("future_rows") != 0:
        return fail("SELECTOR_A2_V2_SELECTOR_FUTURE_ROWS_PRESENT")
    if candidate_identity["path"] != str(pointed):
        return fail("SELECTOR_A2_V2_SELECTOR_PATH_MISMATCH")
    if expected_path is not None and pointed != Path(expected_path).expanduser().absolute():
        return fail("SELECTOR_PATH_MISMATCH", path=str(pointed))
    if expected_sha256 is not None and candidate_identity["selector_sha256"] != str(expected_sha256).lower():
        return fail("SELECTOR_SHA_NOT_EXPECTED")

    actual_pointer = _selector_pointer_identity(pointer)
    if actual_pointer is None:
        return fail("SELECTOR_POINTER_NOT_REGULAR")
    formal_readback = a2.get("formal_current_readback")
    if not isinstance(formal_readback, Mapping) or not _selector_pointer_identity_matches(
        formal_readback.get("selector"), actual_pointer
    ):
        return fail("SELECTOR_A2_V2_FORMAL_POINTER_READBACK_MISMATCH")
    for name, authority in (
        ("a2", a2),
        ("receipt", receipt),
        ("pointer_commit", pointer_commit),
    ):
        pointer_after = authority.get("pointer_after") if isinstance(authority, Mapping) else None
        if not isinstance(pointer_after, Mapping) or not _selector_pointer_identity_matches(
            pointer_after.get("selector"), actual_pointer
        ):
            return fail("SELECTOR_A2_V2_POINTER_READBACK_MISMATCH", authority=name)
    if pointer_commit.get("targets", {}).get("selector") != str(pointer):
        return fail("SELECTOR_A2_V2_POINTER_TARGET_MISMATCH")

    a2_run_root = Path(str(document.get("_compatibility_a2_path"))).parent
    authority_paths = document.get("_compatibility_a2_v2_paths")
    if not isinstance(authority_paths, Mapping):
        return fail("SELECTOR_A2_V2_AUTHORITY_PATHS_MISSING")
    a2_path = Path(str(authority_paths.get("a2") or ""))
    manifest_path = Path(str(authority_paths.get("manifest") or ""))
    receipt_path = Path(str(authority_paths.get("receipt") or ""))
    pointer_commit_path = Path(str(authority_paths.get("pointer_commit") or ""))
    if a2_path.parent != a2_run_root or manifest_path.parent != a2_run_root or receipt_path.parent != a2_run_root:
        return fail("SELECTOR_A2_V2_AUTHORITY_PATH_MISMATCH")
    if a2.get("pointer_commit", {}).get("receipt_path") != str(pointer_commit_path):
        return fail("SELECTOR_A2_V2_POINTER_COMMIT_PATH_MISMATCH")
    try:
        manifest_sha = _sha256_file(manifest_path)
        pointer_commit_sha = _sha256_file(pointer_commit_path)
    except OSError:
        return fail("SELECTOR_A2_V2_AUTHORITY_SHA_READ_FAILED")
    if receipt.get("manifest_sha256") != manifest_sha:
        return fail("SELECTOR_A2_V2_MANIFEST_SHA_MISMATCH")
    if a2.get("pointer_commit", {}).get("receipt_sha256") != pointer_commit_sha:
        return fail("SELECTOR_A2_V2_POINTER_COMMIT_SHA_MISMATCH")

    receipt_artifacts = receipt.get("artifact_sha256s")
    receipt_rows = receipt.get("row_counts")
    receipt_max_dates = receipt.get("max_dates")
    receipt_future = receipt.get("future_rows")
    invariants_artifacts = invariants.get("artifact_sha256s")
    if not all(isinstance(value, Mapping) for value in (receipt_artifacts, receipt_rows, receipt_max_dates, receipt_future, invariants_artifacts)):
        return fail("SELECTOR_A2_V2_SELECTOR_LEDGER_MISSING")
    declared_sha = candidate_identity["selector_sha256"]
    if receipt_artifacts.get("selector") != declared_sha or invariants_artifacts.get("selector") != declared_sha:
        return fail("SELECTOR_A2_V2_ARTIFACT_SHA_MISMATCH")
    if receipt_rows.get("selector") != candidate_identity["rows"]:
        return fail("SELECTOR_A2_V2_RECEIPT_ROWS_MISMATCH")
    if _selector_date(receipt_max_dates.get("selector")) != source:
        return fail("SELECTOR_A2_V2_RECEIPT_MAX_DATE_MISMATCH")
    if receipt_future.get("selector") != 0:
        return fail("SELECTOR_A2_V2_RECEIPT_FUTURE_ROWS")

    if _regular_file_status(pointed) != "regular":
        return fail("SELECTOR_PATH_NOT_REGULAR", path_status=_regular_file_status(pointed))
    try:
        actual_sha = _sha256_file(pointed)
        actual_size = pointed.stat().st_size
    except OSError:
        return fail("SELECTOR_SHA_READ_FAILED")
    if actual_sha != declared_sha:
        return fail("SELECTOR_SHA_MISMATCH", selector_sha256=declared_sha, actual_sha256=actual_sha)
    if actual_size != candidate_identity["size"]:
        return fail("SELECTOR_SIZE_MISMATCH", selector_size=candidate_identity["size"], actual_size=actual_size)
    if candidate_identity["max_date"] != source:
        return fail("SELECTOR_FORMAL_MAX_DATE_MISMATCH", selector_max_date=candidate_identity["max_date"])
    parquet_metadata = _parquet_metadata(pointed)
    if parquet_metadata is None:
        return fail("SELECTOR_PARQUET_METADATA_UNAVAILABLE")
    if parquet_metadata.get("rows") != candidate_identity["rows"]:
        return fail("SELECTOR_PARQUET_ROWS_MISMATCH", actual_rows=parquet_metadata.get("rows"))
    parquet_max_date = _selector_date(parquet_metadata.get("max_date"))
    if parquet_max_date is None or parquet_max_date > source:
        return fail("SELECTOR_PARQUET_FUTURE_DATE_PRESENT", actual_max_date=parquet_max_date)
    if parquet_max_date != source:
        return fail("SELECTOR_PARQUET_MAX_DATE_MISMATCH", actual_max_date=parquet_max_date)

    hashes = {}
    for name, path in authority_paths.items():
        try:
            hashes[f"{name}_sha256"] = _sha256_file(Path(str(path)))
        except OSError:
            return fail("SELECTOR_A2_V2_AUTHORITY_SHA_READ_FAILED", authority=name)
    return {
        "ready": True,
        "reason": "SELECTOR_A2_EXACT_D1_V2_READY",
        "compatibility": "A2_EXACT_D1_V2",
        "path": str(pointed),
        "selector_sha256": declared_sha,
        "selector_size": candidate_identity["size"],
        "selector_rows": candidate_identity["rows"],
        "selector_max_date": candidate_identity["max_date"],
        "selector_metadata_rows": parquet_metadata["rows"],
        "selector_metadata_max_date": parquet_max_date,
        "source_date": source,
        "pit_date": source,
        "target_trade_date": business,
        "cutoff": str(a2.get("pit_cutoff")),
        "pit_safe": True,
        "pointer_path": str(pointer),
        "pointer_sha256": actual_pointer["sha256"],
        "a2_receipt_path": str(a2_path),
        "a2_receipt_sha256": hashes["a2_sha256"],
        "a2_final_invariants_path": str(authority_paths.get("final_invariants")),
        "a2_final_invariants_sha256": hashes["final_invariants_sha256"],
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "receipt_path": str(receipt_path),
        "receipt_sha256": hashes["receipt_sha256"],
        "pointer_commit_path": str(pointer_commit_path),
        "pointer_commit_sha256": pointer_commit_sha,
        "a2_status": SELECTOR_A2_STATUS,
        "a3_status": "WITHHELD",
        "evaluation_future": 0,
    }


def _inspect_a2_a3_compatibility(
    pointer: Path,
    pointed: Path,
    document: Mapping[str, Any],
    source_date: str,
    *,
    expected_path: Path | None,
    expected_sha256: str | None,
    expected_target_trade_date: str | None,
    expected_cutoff: str | None,
) -> dict[str, Any]:
    a2_path = Path(str(document.get("_compatibility_a2_path") or ""))
    a3_path = Path(str(document.get("_compatibility_a3_path") or ""))
    a2 = document.get("_compatibility_a2")
    a3 = document.get("_compatibility_a3")
    if (
        document.get("_compatibility_source_date") != LEGACY_SELECTOR_COMPAT_SOURCE_DATE
        or document.get("_compatibility_business_date") != LEGACY_SELECTOR_COMPAT_BUSINESS_DATE
        or document.get("_compatibility_run_id") != LEGACY_SELECTOR_COMPAT_RUN_ID
    ):
        return {
            "ready": False,
            "reason": "SELECTOR_A2_POINTER_IDENTITY_NOT_CURRENT",
            "source_date": str(document.get("_compatibility_source_date") or ""),
            "business_date": str(document.get("_compatibility_business_date") or ""),
            "run_id": str(document.get("_compatibility_run_id") or ""),
        }
    selector_file_status = str(document.get("_compatibility_selector_file_status") or "missing")
    if selector_file_status != "regular":
        return {
            "ready": False,
            "reason": "SELECTOR_PATH_NOT_REGULAR",
            "path_status": selector_file_status,
            "path": str(pointed),
        }
    a2_file_status = str(document.get("_compatibility_a2_file_status") or "missing")
    if a2_file_status != "regular":
        return {
            "ready": False,
            "reason": "SELECTOR_A2_RECEIPT_NOT_REGULAR" if a2_file_status != "missing" else "SELECTOR_A2_RECEIPT_MISSING",
            "a2_receipt_path": str(a2_path),
            "path_status": a2_file_status,
        }
    a3_file_status = str(document.get("_compatibility_a3_file_status") or "missing")
    if a3_file_status != "regular":
        return {
            "ready": False,
            "reason": "SELECTOR_A3_RECEIPT_NOT_REGULAR" if a3_file_status != "missing" else "SELECTOR_A3_RECEIPT_MISSING",
            "a3_receipt_path": str(a3_path),
            "path_status": a3_file_status,
        }
    if not isinstance(a2, Mapping):
        return {"ready": False, "reason": "SELECTOR_A2_RECEIPT_MISSING", "a2_receipt_path": str(a2_path)}
    if not isinstance(a3, Mapping):
        return {"ready": False, "reason": "SELECTOR_A3_RECEIPT_MISSING", "a3_receipt_path": str(a3_path)}
    if a2.get("schema") != SELECTOR_A2_SCHEMA:
        return {"ready": False, "reason": "SELECTOR_A2_SCHEMA_MISMATCH", "schema": str(a2.get("schema") or "")}
    if a2.get("status") != SELECTOR_A2_STATUS:
        return {"ready": False, "reason": "SELECTOR_A2_STATUS_NOT_READY", "status": str(a2.get("status") or "")}
    if a3.get("schema_version") != SELECTOR_A3_SCHEMA:
        return {"ready": False, "reason": "SELECTOR_A3_SCHEMA_MISMATCH", "schema": str(a3.get("schema_version") or "")}
    if a3.get("status") != SELECTOR_A3_STATUS:
        return {"ready": False, "reason": "SELECTOR_A3_STATUS_NOT_READY", "status": str(a3.get("status") or "")}
    if a2.get("origin") != SELECTOR_ORIGIN:
        return {
            "ready": False,
            "reason": "SELECTOR_A2_ORIGIN_MISMATCH",
            "origin": str(a2.get("origin") or ""),
        }
    a2_safety = a2.get("safety")
    if not isinstance(a2_safety, Mapping) or any(a2_safety.get(field) is not False for field in SELECTOR_SAFETY_FIELDS):
        return {"ready": False, "reason": "SELECTOR_A2_SAFETY_FLAGS_UNSAFE"}
    if a3.get("origin") != SELECTOR_ORIGIN:
        return {
            "ready": False,
            "reason": "SELECTOR_A3_ORIGIN_MISMATCH",
            "origin": str(a3.get("origin") or ""),
        }
    if any(a3.get(field) is not False for field in SELECTOR_SAFETY_FIELDS):
        return {"ready": False, "reason": "SELECTOR_A3_SAFETY_FLAGS_UNSAFE"}

    expected_source = _selector_date(source_date)
    pointer_business = _selector_date(document.get("_compatibility_business_date"))
    a2_business = _selector_date(a2.get("business_date"))
    a2_source = _selector_date(a2.get("source_date"))
    a2_pit = _selector_date(a2.get("pit_date"))
    a2_target = _selector_date(a2.get("target_date"))
    if expected_source is None or pointer_business is None:
        return {"ready": False, "reason": "SELECTOR_A2_POINTER_DATE_INVALID"}
    if a2_business != pointer_business or a2_source != expected_source or a2_pit != expected_source or a2_target != expected_source:
        return {
            "ready": False,
            "reason": "SELECTOR_A2_DATE_IDENTITY_MISMATCH",
            "source_date": str(a2.get("source_date") or ""),
            "business_date": str(a2.get("business_date") or ""),
        }
    expected_target = _selector_date(expected_target_trade_date) if expected_target_trade_date is not None else pointer_business
    if expected_target is None or expected_target != pointer_business or expected_target <= expected_source:
        return {
            "ready": False,
            "reason": "SELECTOR_A2_TARGET_TRADE_DATE_MISMATCH",
            "target_trade_date": pointer_business,
            "expected_target_trade_date": expected_target,
        }
    if expected_cutoff != LEGACY_SELECTOR_COMPAT_CUTOFF:
        return {
            "ready": False,
            "reason": "SELECTOR_COMPAT_CUTOFF_NOT_EXPECTED",
            "expected_cutoff": LEGACY_SELECTOR_COMPAT_CUTOFF,
            "cutoff": str(expected_cutoff or ""),
        }
    evaluation = a2.get("evaluation")
    if not isinstance(evaluation, Mapping) or evaluation.get("future") != 0:
        return {"ready": False, "reason": "SELECTOR_A2_FUTURE_ROWS_PRESENT"}

    candidates = a2.get("candidates")
    candidate_selector = _selector_receipt_identity(
        candidates.get("selector") if isinstance(candidates, Mapping) else None
    )
    formal_readback = a2.get("formal_current_readback")
    formal_selector = _selector_receipt_identity(
        formal_readback.get("selector") if isinstance(formal_readback, Mapping) else None
    )
    if candidate_selector is None or formal_selector is None or not _selector_identity_matches(candidate_selector, formal_selector):
        return {"ready": False, "reason": "SELECTOR_A2_SELECTOR_IDENTITY_MISMATCH"}
    if not bool(formal_selector.get("path") == str(pointed)):
        return {"ready": False, "reason": "SELECTOR_A2_PATH_MISMATCH"}

    a3_identity = _selector_receipt_identity(a3, direct=True)
    formula = a3.get("formula")
    formula_identity = _selector_receipt_identity(
        {
            "path": formula.get("selector"),
            "sha256": formula.get("selector_sha256"),
            "size": formula.get("selector_size"),
            "rows": formula.get("selector_rows"),
            "max_date": formula.get("selector_max_date"),
        }
        if isinstance(formula, Mapping)
        else None
    )
    if a3_identity is None or formula_identity is None:
        return {"ready": False, "reason": "SELECTOR_A3_SELECTOR_IDENTITY_MISSING"}
    if not _selector_identity_matches(formal_selector, a3_identity) or not _selector_identity_matches(a3_identity, formula_identity):
        return {"ready": False, "reason": "SELECTOR_A3_SELECTOR_IDENTITY_MISMATCH"}
    if _selector_date(a3.get("source_date")) != expected_source or _selector_date(a3.get("target_date")) != expected_source:
        return {"ready": False, "reason": "SELECTOR_A3_DATE_IDENTITY_MISMATCH"}
    if a3.get("a2_receipt_path") != str(a2_path):
        return {"ready": False, "reason": "SELECTOR_A3_A2_PATH_MISMATCH"}
    try:
        a2_sha = _sha256_file(a2_path)
    except OSError:
        return {"ready": False, "reason": "SELECTOR_A2_RECEIPT_SHA_READ_FAILED"}
    if str(a3.get("a2_receipt_sha256") or "").lower() != a2_sha:
        return {"ready": False, "reason": "SELECTOR_A3_A2_RECEIPT_SHA_MISMATCH"}
    if a3.get("a2_status") != SELECTOR_A2_STATUS:
        return {"ready": False, "reason": "SELECTOR_A3_A2_STATUS_MISMATCH"}
    if expected_path is not None and pointed != Path(expected_path).expanduser().resolve():
        return {"ready": False, "reason": "SELECTOR_PATH_MISMATCH", "path": str(pointed)}
    if expected_sha256 is not None and formal_selector["selector_sha256"] != str(expected_sha256).lower():
        return {"ready": False, "reason": "SELECTOR_SHA_NOT_EXPECTED"}
    try:
        actual_sha = _sha256_file(pointed)
        actual_size = pointed.stat().st_size
    except OSError:
        return {"ready": False, "reason": "SELECTOR_SHA_READ_FAILED"}
    if actual_sha != formal_selector["selector_sha256"]:
        return {
            "ready": False,
            "reason": "SELECTOR_SHA_MISMATCH",
            "selector_sha256": formal_selector["selector_sha256"],
            "actual_sha256": actual_sha,
        }
    if actual_size != formal_selector["size"]:
        return {
            "ready": False,
            "reason": "SELECTOR_SIZE_MISMATCH",
            "selector_size": formal_selector["size"],
            "actual_size": actual_size,
        }
    if formal_selector["max_date"] != expected_source:
        return {
            "ready": False,
            "reason": "SELECTOR_FORMAL_MAX_DATE_MISMATCH",
            "selector_max_date": formal_selector["max_date"],
            "expected_source_date": expected_source,
        }
    parquet_metadata = _parquet_metadata(pointed)
    if parquet_metadata is None:
        return {"ready": False, "reason": "SELECTOR_PARQUET_METADATA_UNAVAILABLE"}
    if parquet_metadata.get("rows") != formal_selector["rows"]:
        return {
            "ready": False,
            "reason": "SELECTOR_PARQUET_ROWS_MISMATCH",
            "selector_rows": formal_selector["rows"],
            "actual_rows": parquet_metadata.get("rows"),
        }
    parquet_max_date = _selector_date(parquet_metadata.get("max_date"))
    if parquet_max_date is None:
        return {"ready": False, "reason": "SELECTOR_PARQUET_MAX_DATE_MISSING"}
    if parquet_max_date > expected_source:
        return {
            "ready": False,
            "reason": "SELECTOR_PARQUET_FUTURE_DATE_PRESENT",
            "actual_max_date": parquet_max_date,
            "expected_source_date": expected_source,
        }
    if parquet_max_date != expected_source:
        return {
            "ready": False,
            "reason": "SELECTOR_PARQUET_MAX_DATE_MISMATCH",
            "actual_max_date": parquet_max_date,
            "expected_source_date": expected_source,
        }
    try:
        a3_sha = _sha256_file(a3_path)
        pointer_sha = _sha256_file(pointer)
    except OSError:
        return {"ready": False, "reason": "SELECTOR_COMPATIBILITY_RECEIPT_SHA_READ_FAILED"}
    return {
        "ready": True,
        "reason": "SELECTOR_A2_A3_EXACT_D1_READY",
        "compatibility": "A2_A3_EXACT_D1",
        "path": str(pointed),
        "selector_sha256": formal_selector["selector_sha256"],
        "selector_size": formal_selector["size"],
        "selector_rows": formal_selector["rows"],
        "selector_max_date": formal_selector["max_date"],
        "selector_metadata_rows": parquet_metadata["rows"],
        "selector_metadata_max_date": parquet_max_date,
        "source_date": expected_source,
        "pit_date": expected_source,
        "target_trade_date": pointer_business,
        "cutoff": LEGACY_SELECTOR_COMPAT_CUTOFF,
        "pit_safe": True,
        "pointer_path": str(pointer),
        "pointer_sha256": pointer_sha,
        "a2_receipt_path": str(a2_path),
        "a2_receipt_sha256": a2_sha,
        "a3_receipt_path": str(a3_path),
        "a3_receipt_sha256": a3_sha,
        "a2_status": SELECTOR_A2_STATUS,
        "a3_status": SELECTOR_A3_STATUS,
        "evaluation_future": 0,
    }


def inspect_selector_pointer(
    pointer: Path,
    source_date: str,
    expected_path: Path | None = None,
    *,
    expected_sha256: str | None = None,
    expected_target_trade_date: str | None = None,
    expected_cutoff: str | None = None,
    shared_package_root: Path | None = None,
) -> dict[str, Any]:
    """Validate the exact upstream selector contract without changing it.

    ``source_date`` is the date whose selector evidence is consumed.  The
    selector's ``target_trade_date`` is a separate, explicit field so a stale
    panel cannot be accepted merely because its parquet happens to contain a
    row for the requested date.
    """

    try:
        target = normalize_trade_date(source_date)
    except (TypeError, ValueError):
        return {"ready": False, "reason": "SELECTOR_SOURCE_DATE_INVALID"}
    document = _selector_pointer_document(Path(pointer))
    pointed = _selector_target_from_document(Path(pointer), document)
    if document.get("_compatibility_selector_path"):
        pointed = Path(str(document["_compatibility_selector_path"])).expanduser()
        if not pointed.is_absolute():
            pointed = Path(pointer).parent / pointed
        pointed = pointed.absolute()
    if pointed is None or not pointed.is_file():
        return {"ready": False, "reason": "SELECTOR_PATH_UNRESOLVED"}
    if document.get("_pointer_path_mismatch"):
        return {
            "ready": False,
            "reason": "SELECTOR_POINTER_PATH_MISMATCH",
            "pointer_target": str(document.get("_pointer_text_target") or pointed),
            "sidecar_target": str(document.get("_sidecar_declared_target") or ""),
        }
    if expected_path is not None:
        expected = Path(expected_path).expanduser().resolve()
        if pointed != expected:
            return {"ready": False, "reason": "SELECTOR_PATH_MISMATCH", "path": str(pointed)}
    if document.get("_native_formula_compatibility"):
        return _inspect_native_formula_compatibility(
            Path(pointer),
            pointed,
            document,
            target,
            expected_path=expected_path,
            expected_sha256=expected_sha256,
            expected_target_trade_date=expected_target_trade_date,
            expected_cutoff=expected_cutoff,
            shared_package_root=shared_package_root,
        )
    if document.get("_a2_v2_compatibility"):
        return _inspect_a2_v2_compatibility(
            Path(pointer),
            pointed,
            document,
            target,
            expected_path=expected_path,
            expected_sha256=expected_sha256,
            expected_target_trade_date=expected_target_trade_date,
            expected_cutoff=expected_cutoff,
        )
    if document.get("_a2_a3_compatibility"):
        return _inspect_a2_a3_compatibility(
            Path(pointer),
            pointed,
            document,
            target,
            expected_path=expected_path,
            expected_sha256=expected_sha256,
            expected_target_trade_date=expected_target_trade_date,
            expected_cutoff=expected_cutoff,
        )
    if document.get("_legacy_plain_pointer"):
        return {"ready": False, "reason": "SELECTOR_POINTER_METADATA_MISSING", "path": str(pointed)}
    if document.get("schema_version") != SELECTOR_POINTER_SCHEMA:
        return {
            "ready": False,
            "reason": "SELECTOR_POINTER_SCHEMA_MISMATCH",
            "schema_version": str(document.get("schema_version") or ""),
        }

    signal = str(_selector_field(document, "signal", "status", "readiness") or "").strip()
    if signal not in SELECTOR_READY_SIGNALS:
        return {"ready": False, "reason": "SELECTOR_SIGNAL_NOT_READY", "signal": signal}
    source_value = _selector_field(document, "source_date", "signal_date", "trade_date")
    source = _selector_date(source_value)
    if source != target:
        return {
            "ready": False,
            "reason": "SELECTOR_SOURCE_DATE_MISMATCH",
            "source_date": source or str(source_value or ""),
            "expected_source_date": target,
        }
    target_value = _selector_field(document, "target_trade_date", "target_date", "effective_trade_date")
    target_trade_date = _selector_date(target_value)
    if target_trade_date is None:
        return {"ready": False, "reason": "SELECTOR_TARGET_TRADE_DATE_MISSING"}
    if target_trade_date <= target:
        return {
            "ready": False,
            "reason": "SELECTOR_TARGET_TRADE_DATE_NOT_FORWARD",
            "target_trade_date": target_trade_date,
            "source_date": target,
        }
    if expected_target_trade_date is not None:
        expected_target = _selector_date(expected_target_trade_date)
        if expected_target is None or target_trade_date != expected_target:
            return {
                "ready": False,
                "reason": "SELECTOR_TARGET_TRADE_DATE_MISMATCH",
                "target_trade_date": target_trade_date,
                "expected_target_trade_date": expected_target or str(expected_target_trade_date),
            }
    cutoff_value = _selector_field(document, "cutoff", "cutoff_at", "pit_cutoff", "signal_cutoff")
    cutoff_date = _selector_cutoff_date(cutoff_value)
    if cutoff_date != target:
        return {
            "ready": False,
            "reason": "SELECTOR_CUTOFF_MISMATCH",
            "cutoff": str(cutoff_value or ""),
            "expected_source_date": target,
        }
    if expected_cutoff is not None and str(cutoff_value) != str(expected_cutoff):
        return {
            "ready": False,
            "reason": "SELECTOR_CUTOFF_NOT_EXPECTED",
            "cutoff": str(cutoff_value),
            "expected_cutoff": str(expected_cutoff),
        }
    pit_values = [
        document[name]
        for name in ("pit_safe", "temporal_cutoff_safe", "point_in_time_safe", "pit_verified")
        if name in document
    ]
    if not pit_values or any(value is not True for value in pit_values):
        return {"ready": False, "reason": "SELECTOR_PIT_UNVERIFIED"}

    declared_sha = str(
        _selector_field(document, "selector_sha256", "sha256", "artifact_sha256", "target_sha256") or ""
    ).lower()
    if len(declared_sha) != 64 or any(char not in "0123456789abcdef" for char in declared_sha):
        return {"ready": False, "reason": "SELECTOR_SHA_MISSING_OR_INVALID"}
    if expected_sha256 is not None and declared_sha != str(expected_sha256).lower():
        return {"ready": False, "reason": "SELECTOR_SHA_NOT_EXPECTED"}
    try:
        actual_sha = _sha256_file(pointed)
    except OSError:
        return {"ready": False, "reason": "SELECTOR_SHA_READ_FAILED"}
    if actual_sha != declared_sha:
        return {
            "ready": False,
            "reason": "SELECTOR_SHA_MISMATCH",
            "selector_sha256": declared_sha,
            "actual_sha256": actual_sha,
        }
    if not _parquet_has_date(pointed, target):
        return {"ready": False, "reason": "SELECTOR_EXACT_DATE_MISSING", "source_date": target}
    return {
        "ready": True,
        "reason": "SELECTOR_EXACT_PIT_READY",
        "path": str(pointed),
        "selector_sha256": actual_sha,
        "source_date": target,
        "target_trade_date": target_trade_date,
        "cutoff": str(cutoff_value),
        "pit_safe": True,
    }


def selector_is_ready(
    pointer: Path,
    target_date: str,
    expected_path: Path | None = None,
    *,
    expected_sha256: str | None = None,
    expected_target_trade_date: str | None = None,
    expected_cutoff: str | None = None,
    shared_package_root: Path | None = None,
) -> bool:
    """Require a signed, exact-date and point-in-time-safe selector."""

    return bool(
        inspect_selector_pointer(
            Path(pointer),
            target_date,
            expected_path,
            expected_sha256=expected_sha256,
            expected_target_trade_date=expected_target_trade_date,
            expected_cutoff=expected_cutoff,
            shared_package_root=shared_package_root,
        ).get("ready")
    )


def _safe_flags(payload: Mapping[str, Any]) -> bool:
    return all(payload.get(name, False) is False for name in SAFETY_FLAGS)


def review_bundle_is_ready(data_root: Path, target_date: str) -> bool:
    """Check the exact current ReviewBundle without touching the network."""

    target = normalize_trade_date(target_date)
    try:
        from .core import inspect_bundle
        from .review import inspect_review_bundle

        video = inspect_bundle(target, Path(data_root))
        review = inspect_review_bundle(target, Path(data_root))
    except Exception:
        return False
    if not isinstance(video, Mapping) or not isinstance(review, Mapping):
        return False
    if video.get("trade_date") != target or review.get("trade_date") != target:
        return False
    if video.get("discovery_status") != "TARGET_BV_LOCKED":
        return False
    if video.get("capture_status") in {"ACCESS_BLOCKED", "CAPTURE_NOT_AVAILABLE"}:
        return False
    asr_status = str(video.get("asr_status") or "").upper()
    if asr_status in {"", "NOT_RUN", "FAILED", "ASR_FAILED"}:
        return False
    try:
        if int(video.get("asr_segment_count") or 0) <= 0:
            return False
    except (TypeError, ValueError):
        return False
    if review.get("status") != "READY":
        return False
    return _safe_flags(video) and _safe_flags(review)


def _run_id(target_date: str, paths: DailyPaths, selector_path: Path | None = None) -> str:
    identity = {
        "trade_date": target_date,
        "data_root": str(paths.data_root),
        "selector": str(selector_path or paths.selector_path or ""),
        "public_source_root": str(paths.public_source_root),
        "tdx_root": str(paths.tdx_root),
    }
    digest = hashlib.sha256(_canonical(identity)).hexdigest()[:16]
    return f"review-core-daily-{target_date}-{digest}"


def _shared_public_fupan_importable(python_path: Path, shared_root: Path | None) -> bool:
    """Check that the configured shared package imports from this exact root."""

    if shared_root is None or not python_path.is_file():
        return False
    package_root = shared_root / "shared_data"
    required = (
        package_root / "__init__.py",
        package_root / "public_fupan.py",
        package_root / "hashing.py",
        package_root / "paths.py",
        package_root / "store.py",
    )
    if not package_root.is_dir() or any(not path.is_file() or path.is_symlink() for path in required):
        return False
    script = (
        "import pathlib, shared_data.public_fupan as module; "
        "root = pathlib.Path(module.__file__).resolve().parents[1]; "
        "raise SystemExit(0 if root == pathlib.Path(__import__('sys').argv[1]).resolve() "
        "and module.__package__ == 'shared_data' "
        "and callable(getattr(module, 'read_public_fupan', None)) else 1)"
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(shared_root)
    try:
        completed = subprocess.run(
            [str(python_path), "-B", "-c", script, str(shared_root)],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _tdx_has_supported_daily_file(tdx_root: Path) -> tuple[bool, list[str]]:
    """Require at least one real TDX daily file under a supported market."""

    markets: list[str] = []
    for market in ("sh", "sz", "bj"):
        lday = tdx_root / "vipdoc" / market / "lday"
        if not lday.is_dir() or lday.is_symlink():
            continue
        try:
            has_daily = any(
                path.is_file() and not path.is_symlink() and path.suffix.lower() == ".day"
                for path in lday.iterdir()
            )
        except OSError:
            has_daily = False
        if has_daily:
            markets.append(market)
    return bool(markets), markets


def runtime_contract(paths: DailyPaths) -> dict[str, Any]:
    """Return machine-checkable candidate runtime binding evidence.

    This is deliberately a report, not a deployment action.  It records the
    interpreter, import path, source/cwd/release roots and their local
    existence checks so the Sol controller can compare a candidate with the
    loaded LaunchAgent before any reload is considered.
    """

    python_path = Path(paths.python_path or os.environ.get("PYTHON", "") or os.sys.executable).expanduser()
    if not python_path.is_absolute():
        python_path = python_path.absolute()
    asr_python_path = Path(paths.asr_python_path or python_path).expanduser()
    if not asr_python_path.is_absolute():
        asr_python_path = asr_python_path.absolute()
    source_root = paths.source_root or Path(__file__).resolve().parent
    shared_root_value = paths.shared_package_root or os.environ.get("REVIEW_CORE_SHARED_PACKAGE_ROOT")
    shared_root = Path(shared_root_value).expanduser().absolute() if shared_root_value else None
    release_root_value = paths.release_root or os.environ.get("REVIEW_CORE_RELEASE_ROOT")
    release_root = Path(release_root_value).expanduser().absolute() if release_root_value else None
    expected_cwd = paths.working_directory or Path.cwd()
    expected_cwd = expected_cwd.expanduser().absolute()
    observed_cwd = Path.cwd().absolute()
    pythonpath_raw = os.environ.get("PYTHONPATH", "")
    raw_pythonpath_entries = pythonpath_raw.split(os.pathsep) if pythonpath_raw else []
    pythonpath_entries = [entry for entry in raw_pythonpath_entries if entry]
    pythonpath_paths = [Path(entry).expanduser().absolute() for entry in pythonpath_entries]
    pythonpath_entries_have_no_empty = bool(raw_pythonpath_entries) and all(
        bool(entry.strip()) for entry in raw_pythonpath_entries
    )
    pythonpath_entries_are_absolute = bool(raw_pythonpath_entries) and all(
        Path(entry).expanduser().is_absolute() for entry in raw_pythonpath_entries if entry
    ) and pythonpath_entries_have_no_empty
    pythonpath_entries_are_directories = all(path.is_dir() for path in pythonpath_paths)
    source_import_root = source_root.parent if source_root.name == "review_core" else source_root
    entrypoint_source_root = Path(__file__).resolve().parent
    shared_env_value = os.environ.get("REVIEW_CORE_SHARED_PACKAGE_ROOT", "")
    shared_env_root = Path(shared_env_value).expanduser().absolute() if shared_env_value else None
    source_root_matches_entrypoint = source_root == entrypoint_source_root
    source_root_matches_release = (
        release_root is not None and source_root == release_root / "app" / "review_core"
    )
    expected_pythonpath_paths = (
        [source_import_root, shared_root] if shared_root is not None else []
    )
    pythonpath_exact_canonical = (
        pythonpath_entries_have_no_empty
        and pythonpath_entries_are_absolute
        and shared_root is not None
        and pythonpath_paths == expected_pythonpath_paths
    )
    python_path_matches_runtime = python_path.resolve() == Path(os.sys.executable).resolve() if python_path.is_file() else False
    shared_package_env_matches_config = shared_root is not None and shared_env_root == shared_root
    shared_public_fupan_importable = _shared_public_fupan_importable(python_path, shared_root)
    tdx_supported_daily_file, tdx_supported_markets = _tdx_has_supported_daily_file(paths.tdx_root)
    return {
        "status": "CANDIDATE_ONLY",
        "python_path": str(python_path),
        "python_sha256": _sha256_file(python_path) if python_path.is_file() else "",
        "python_exists": python_path.is_file(),
        "asr_python_path": str(asr_python_path),
        "asr_python_sha256": _sha256_file(asr_python_path) if asr_python_path.is_file() else "",
        "asr_python_exists": asr_python_path.is_file(),
        "pythonpath": pythonpath_raw,
        "pythonpath_entries": pythonpath_entries,
        "pythonpath_entries_have_no_empty": pythonpath_entries_have_no_empty,
        "pythonpath_entries_are_absolute": pythonpath_entries_are_absolute,
        "pythonpath_entries_are_directories": pythonpath_entries_are_directories,
        "pythonpath_has_source_import_root": source_import_root in pythonpath_paths,
        "pythonpath_has_shared_package_root": shared_root is not None and shared_root in pythonpath_paths,
        "pythonpath_exact_canonical": pythonpath_exact_canonical,
        "source_root": str(source_root),
        "source_root_exists": source_root.is_dir(),
        "entrypoint_source_root": str(entrypoint_source_root),
        "source_root_matches_entrypoint": source_root_matches_entrypoint,
        "source_root_matches_release": source_root_matches_release,
        "module_file": str(Path(__file__).resolve()),
        "cwd": str(expected_cwd),
        "observed_cwd": str(observed_cwd),
        "cwd_matches_expected": expected_cwd == observed_cwd,
        "release_root": str(release_root) if release_root else "",
        "release_id": release_root.name if release_root else "",
        "release_root_exists": release_root.is_dir() if release_root else False,
        "shared_package_root": str(shared_root) if shared_root else "",
        "shared_package_root_exists": shared_root.is_dir() if shared_root else False,
        "shared_package_env_root": str(shared_env_root) if shared_env_root else "",
        "shared_package_env_matches_config": shared_package_env_matches_config,
        "shared_public_fupan_importable": shared_public_fupan_importable,
        "public_source_root": str(paths.public_source_root),
        "public_source_root_exists": paths.public_source_root.is_dir(),
        "tdx_root": str(paths.tdx_root),
        "tdx_root_exists": paths.tdx_root.is_dir(),
        "tdx_supported_markets": tdx_supported_markets,
        "tdx_supported_market_daily_file": tdx_supported_daily_file,
        "python_path_matches_runtime": python_path_matches_runtime,
        "consistency": {
            "python_path_is_file": python_path.is_file(),
            "asr_python_path_is_file": asr_python_path.is_file(),
            "python_path_matches_runtime": python_path_matches_runtime,
            "pythonpath_entries_have_no_empty": pythonpath_entries_have_no_empty,
            "pythonpath_entries_are_absolute": pythonpath_entries_are_absolute,
            "pythonpath_entries_are_directories": pythonpath_entries_are_directories,
            "pythonpath_has_source_import_root": source_import_root in pythonpath_paths,
            "pythonpath_has_shared_package_root": shared_root is not None and shared_root in pythonpath_paths,
            "pythonpath_exact_canonical": pythonpath_exact_canonical,
            "source_root_is_directory": source_root.is_dir(),
            "source_root_matches_entrypoint": source_root_matches_entrypoint,
            "source_root_matches_release": source_root_matches_release,
            "cwd_matches_expected": expected_cwd == observed_cwd,
            "release_root_is_directory": release_root.is_dir() if release_root else False,
            "shared_package_root_is_directory": shared_root.is_dir() if shared_root else False,
            "shared_package_env_matches_config": shared_package_env_matches_config,
            "shared_public_fupan_importable": shared_public_fupan_importable,
            "public_source_root_is_directory": paths.public_source_root.is_dir(),
            "tdx_root_is_directory": paths.tdx_root.is_dir(),
            "tdx_supported_market_daily_file": tdx_supported_daily_file,
        },
    }


def _runtime_contract_is_ready(contract: Mapping[str, Any]) -> bool:
    consistency = contract.get("consistency")
    return (
        isinstance(consistency, Mapping)
        and consistency.get("python_path_is_file") is True
        and consistency.get("asr_python_path_is_file") is True
        and consistency.get("python_path_matches_runtime") is True
        and consistency.get("pythonpath_entries_have_no_empty") is True
        and consistency.get("pythonpath_entries_are_absolute") is True
        and consistency.get("pythonpath_entries_are_directories") is True
        and consistency.get("pythonpath_exact_canonical") is True
        and consistency.get("source_root_is_directory") is True
        and consistency.get("source_root_matches_entrypoint") is True
        and consistency.get("source_root_matches_release") is True
        and consistency.get("cwd_matches_expected") is True
        and consistency.get("release_root_is_directory") is True
        and consistency.get("shared_package_root_is_directory") is True
        and consistency.get("shared_package_env_matches_config") is True
        and consistency.get("shared_public_fupan_importable") is True
        and consistency.get("public_source_root_is_directory") is True
        and consistency.get("tdx_root_is_directory") is True
        and consistency.get("tdx_supported_market_daily_file") is True
    )


def _write_result(
    target_date: str,
    paths: DailyPaths,
    payload: Mapping[str, Any],
    *,
    selector_path: Path | None = None,
    skip_runtime_contract: bool = False,
) -> dict[str, Any]:
    run_id = _run_id(target_date, paths, selector_path)
    finished_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    origin = str(payload.get("origin") or "manual")
    if origin not in RECEIPT_ORIGINS:
        origin = "manual"
    attempt_id = f"{run_id}-attempt-{datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%dT%H%M%S%f')}-{uuid.uuid4().hex[:12]}"
    receipt_runtime_contract: Mapping[str, Any]
    if skip_runtime_contract:
        receipt_runtime_contract = {
            "status": "NOT_RUN",
            "reason": str(payload.get("reason") or "RUNTIME_CONTRACT_NOT_RUN"),
        }
    else:
        receipt_runtime_contract = runtime_contract(paths)
    body = {
        "schema_version": "review_core.macos_daily_receipt.v1",
        **dict(payload),
        "run_id": run_id,
        "attempt": attempt_id,
        "attempt_id": attempt_id,
        "origin": origin,
        "finished_at": finished_at,
        "runtime_contract": receipt_runtime_contract,
        "safety_flags": dict(SAFETY_FLAGS),
        **SAFETY_FLAGS,
    }
    receipt_path = paths.receipt_root / target_date / f"{attempt_id}.json"
    if receipt_path.exists():
        raise RuntimeError(f"refusing to overwrite immutable receipt: {receipt_path}")
    receipt_sha, receipt_size = _atomic_json(receipt_path, body)
    current_path = paths.receipt_root / target_date / "current.json"
    _atomic_json(
        current_path,
        {
            "schema_version": "review_core.macos_daily_current.v1",
            "trade_date": target_date,
            "run_id": run_id,
            "attempt": attempt_id,
            "attempt_id": attempt_id,
            "origin": origin,
            "finished_at": finished_at,
            "receipt_path": str(receipt_path),
            "receipt_sha256": receipt_sha,
            **SAFETY_FLAGS,
        },
    )
    _graph_notify("REVIEW_CORE_DAILY", "review_core_daily", target_date, "COMMITTED",
                  run_id=attempt_id, source_path=receipt_path)
    result = dict(body)
    result.update({"receipt_path": str(receipt_path), "receipt_sha256": receipt_sha, "receipt_size": receipt_size, "current_path": str(current_path)})
    return result


def _current_receipt(paths: DailyPaths, target_date: str) -> dict[str, Any]:
    pointer = paths.receipt_root / target_date / "current.json"
    try:
        current = json.loads(pointer.read_text(encoding="utf-8-sig"))
        if not isinstance(current, dict):
            return {}
        if current.get("schema_version") != "review_core.macos_daily_current.v1":
            return {}
        if current.get("trade_date") != target_date:
            return {}
        if any(current.get(name) is not False for name in SAFETY_FLAGS):
            return {}
        receipt_path = Path(str(current.get("receipt_path") or ""))
        if not receipt_path.is_absolute():
            receipt_path = pointer.parent / receipt_path
        if not receipt_path.is_file():
            return {}
        expected_sha = str(current.get("receipt_sha256") or "")
        if not expected_sha or _sha256_file(receipt_path) != expected_sha:
            return {}
        payload = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    if not isinstance(payload, dict) or payload.get("trade_date") != target_date:
        return {}
    if payload.get("schema_version") != "review_core.macos_daily_receipt.v1":
        return {}
    for field in ("trade_date", "run_id", "attempt_id", "origin", "finished_at"):
        if not current.get(field) or current.get(field) != payload.get(field):
            return {}
    if current.get("origin") not in RECEIPT_ORIGINS:
        return {}
    if current.get("attempt") != payload.get("attempt"):
        return {}
    if any(payload.get(name) is not False for name in SAFETY_FLAGS):
        return {}
    receipt_flags = payload.get("safety_flags")
    if not isinstance(receipt_flags, Mapping) or any(receipt_flags.get(name) is not False for name in SAFETY_FLAGS):
        return {}
    return payload


def run_daily(
    trade_date: str | None = None,
    *,
    paths: DailyPaths,
    allow_network: bool = False,
    tools: Any = None,
    now: datetime | None = None,
    origin: str | None = None,
) -> dict[str, Any]:
    """Run exactly one date, with zero lookback and machine-verifiable receipt."""

    implicit = trade_date is None
    clock = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    else:
        clock = clock.astimezone(ZoneInfo("Asia/Shanghai"))
    # Resolve the calendar date locally before touching scheduler/runtime or
    # any selector/review inputs.  An implicit weekend launchd tick is a
    # harmless no-op; an explicit weekend request is a deliberate block.  In
    # both cases, never ask the scheduler for a prior Friday fallback.
    candidate_target = clock.strftime("%Y%m%d") if implicit else normalize_trade_date(trade_date)
    attempt_origin = origin or ("natural_scheduler" if implicit else "manual")
    if attempt_origin not in RECEIPT_ORIGINS:
        raise ValueError(f"unsupported receipt origin: {attempt_origin}")
    base = {
        "lookback_trading_days": 0,
        "allow_network": bool(allow_network),
        "network_used": False,
        "acquisition_count": 0,
        "asr_execution_count": 0,
        "selector_path": str(paths.selector_path or ""),
        "selector_pointer": str(paths.selector_pointer),
        "public_source_root": str(paths.public_source_root),
        "tdx_root": str(paths.tdx_root),
        "source_root": str(paths.source_root) if paths.source_root else "",
        "asr_python_path": str(paths.asr_python_path or paths.python_path or ""),
        "observed_at": clock.isoformat(),
        "origin": attempt_origin,
        "selector_expected_target_trade_date": paths.selector_target_trade_date or "",
        "selector_expected_cutoff": paths.selector_cutoff or "",
    }
    if datetime.strptime(candidate_target, "%Y%m%d").weekday() >= 5:
        return _write_result(
            candidate_target,
            paths,
            {
                **base,
                "trade_date": candidate_target,
                "calendar_date": candidate_target,
                "selected_dates": [],
                "status": "NOOP_SKIP" if implicit else "BLOCKED",
                "reason": "NON_TRADING_DAY" if implicit else "EXPLICIT_NON_TRADING_DAY",
            },
            skip_runtime_contract=True,
        )

    target = scheduler.resolve_trade_date(trade_date, now=clock)
    base.update(
        {
            "trade_date": target,
            "selected_dates": [target],
            "runtime_contract": runtime_contract(paths),
        }
    )
    if paths.require_runtime_contract and not _runtime_contract_is_ready(base["runtime_contract"]):
        return _write_result(
            target,
            paths,
            {
                **base,
                "status": "BLOCKED",
                "reason": "RUNTIME_CONTRACT_NOT_READY",
            },
        )
    if implicit and (clock.hour, clock.minute) < (20, 25):
        return _write_result(
            target,
            paths,
            {**base, "status": "WAITING_NOT_BEFORE_2025", "reason": "IMPLICIT_LAUNCHD_NOT_BEFORE_2025_SHANGHAI"},
        )
    # A fully verified exact-date bundle is the cheapest and safest path.  It
    # does not depend on today's selector pointer, and must not re-open that
    # mutable upstream gate just to prove an already completed run again.
    if review_bundle_is_ready(paths.data_root, target):
        return _write_result(
            target,
            paths,
            {
                **base,
                "status": "READY",
                "idempotent": True,
                "reason": "EXACT_REVIEW_BUNDLE_ALREADY_READY",
                "review_attempted": False,
            },
        )
    # Take one immutable selector validation snapshot for this attempt.  The
    # snapshot carries the resolved path, SHA and PIT fields into the receipt
    # and scheduler call; do not re-read the pointer through a second gate or
    # resolve it again after validation.
    selector_kwargs: dict[str, Any] = {
        "expected_path": paths.selector_path,
        "expected_target_trade_date": paths.selector_target_trade_date,
        "expected_cutoff": paths.selector_cutoff,
    }
    if paths.shared_package_root is not None:
        selector_kwargs["shared_package_root"] = paths.shared_package_root
    selector_validation = inspect_selector_pointer(paths.selector_pointer, target, **selector_kwargs)
    selector_ready = bool(selector_validation.get("ready"))
    base["selector_validation"] = selector_validation
    if not selector_ready:
        # Selector readiness is the natural entry gate.  Preserve the failed
        # evidence, but stop before scheduler/network execution.
        return _write_result(
            target,
            paths,
            {
                **base,
                "status": "BLOCKED",
                "reason": "SELECTOR_NOT_READY",
                "review_attempted": False,
            },
        )
    base["review_attempted"] = True
    selector_path: Path | None = None
    selector_sha256: str | None = None
    selector_target_trade_date: str | None = None
    selector_cutoff: str | None = None
    if selector_ready:
        base["selector_validated_source_date"] = str(selector_validation.get("source_date") or "")
        base["selector_validated_target_trade_date"] = str(selector_validation.get("target_trade_date") or "")
        selector_target_trade_date = str(selector_validation.get("target_trade_date") or "")
        selector_cutoff = str(
            selector_validation.get("cutoff") or selector_validation.get("pit_cutoff") or ""
        )
        selector_sha256 = str(selector_validation.get("selector_sha256") or "").lower()
        base["selector_validated_cutoff"] = selector_cutoff
        base["selector_validated_sha256"] = selector_sha256
        selector_path_value = selector_validation.get("path")
        if not selector_path_value:
            return _write_result(target, paths, {**base, "status": "BLOCKED", "reason": "SELECTOR_PATH_UNRESOLVED"})
        selector_path = Path(str(selector_path_value)).expanduser().resolve()
        base["selector_path"] = str(selector_path)

    previous = _current_receipt(paths, target) if implicit else {}
    if previous.get("network_used") or previous.get("last_network_at"):
        last_raw = str(previous.get("last_network_at") or previous.get("observed_at") or "")
        try:
            last_at = datetime.fromisoformat(last_raw)
            if last_at.tzinfo is None:
                last_at = last_at.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            elapsed = (clock - last_at.astimezone(ZoneInfo("Asia/Shanghai"))).total_seconds()
        except (TypeError, ValueError, OverflowError):
            elapsed = 300.0
        if elapsed < 300.0:
            return _write_result(
                target,
                paths,
                {
                    **base,
                    "status": "RETRY_BACKOFF",
                    "reason": "RECENT_NETWORK_ATTEMPT_BACKOFF_300_SECONDS",
                    "last_network_at": last_raw,
                },
                selector_path=selector_path,
            )

    if selector_ready and (not paths.public_source_root.is_dir() or not paths.tdx_root.is_dir()):
        missing = [
            label
            for label, path in (("PUBLIC_SOURCE_ROOT", paths.public_source_root), ("TDX_ROOT", paths.tdx_root))
            if not path.is_dir()
        ]
        return _write_result(target, paths, {**base, "status": "BLOCKED", "reason": ",".join(missing)}, selector_path=selector_path)

    try:
        scheduler_kwargs: dict[str, Any] = {
            "data_root": paths.data_root,
            "mode": "acquire",
            "allow_network": allow_network,
            "tools": tools,
            "source_root": paths.source_root,
            "lookback_trading_days": 0,
            "funasr_path": paths.funasr_path,
            "ffmpeg_path": paths.ffmpeg_path,
            "ytdlp_path": paths.ytdlp_path,
            "python_path": paths.python_path,
            "asr_python_path": paths.asr_python_path,
            "selector_path": selector_path,
            "selector_sha256": selector_sha256,
            "selector_target_trade_date": selector_target_trade_date,
            "selector_cutoff": selector_cutoff,
            "formal_pool_path": paths.formal_pool_path,
            "review_pool_path": paths.review_pool_path,
            "stage_root": paths.stage_root,
        }
        if selector_ready:
            scheduler_kwargs.update(
                {
                    "public_source_root": paths.public_source_root,
                    "tdx_root": paths.tdx_root,
                }
            )
        _graph_notify("REVIEW_CORE_DAILY", "review_core_daily", target, "EXECUTOR_ENTERED",
                      run_id=_run_id(target, paths, selector_path))
        scheduled = scheduler.run_once(
            target,
            **scheduler_kwargs,
        )
    except Exception as error:
        return _write_result(
            target,
            paths,
            {**base, "status": "BLOCKED", "reason": f"{type(error).__name__}: {error}"},
            selector_path=selector_path,
        )

    item = (scheduled.get("results") or [{}])[0] if isinstance(scheduled, Mapping) else {}
    scheduled_network_used = bool(scheduled.get("network_used"))
    scheduled_status = scheduled.get("status", "PARTIAL")
    scheduled_reason = "SCHEDULED" if scheduled_status == "SCHEDULED" else f"SCHEDULER_{str(scheduled_status or 'UNKNOWN')}"
    return _write_result(
        target,
        paths,
        {
            **base,
            "status": scheduled_status,
            "reason": scheduled_reason,
            "idempotent": bool(item.get("idempotent")),
            "scheduler_run_id": scheduled.get("scheduler_run_id", ""),
            "scheduler_receipt_path": scheduled.get("receipt_path", ""),
            "network_used": scheduled_network_used,
            "last_network_at": clock.isoformat() if scheduled_network_used else str(previous.get("last_network_at") or ""),
            "acquisition_count": int(item.get("acquisition_count", 0) or 0),
            "asr_execution_count": int(item.get("asr_execution_count", 0) or 0),
            "review_attempted": bool(item.get("review_attempted", selector_ready)),
            "results": scheduled.get("results", []),
        },
        selector_path=selector_path,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", dest="trade_date", default=None)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--selector-pointer", required=True, type=Path)
    parser.add_argument("--selector-path", required=False, type=Path)
    parser.add_argument("--public-source-root", required=True, type=Path)
    parser.add_argument("--tdx-root", required=True, type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--receipt-root", required=True, type=Path)
    parser.add_argument("--funasr-path", type=Path)
    parser.add_argument("--ffmpeg-path", type=Path)
    parser.add_argument("--ytdlp-path", type=Path)
    parser.add_argument("--python-path", type=Path)
    parser.add_argument("--asr-python-path", type=Path)
    parser.add_argument("--shared-package-root", type=Path)
    parser.add_argument("--release-root", type=Path)
    parser.add_argument("--working-directory", type=Path)
    parser.add_argument("--selector-target-trade-date")
    parser.add_argument("--selector-cutoff")
    parser.add_argument("--formal-pool-path", type=Path)
    parser.add_argument("--review-pool-path", type=Path)
    parser.add_argument("--stage-root", type=Path)
    parser.add_argument("--require-runtime-contract", action="store_true")
    parser.add_argument("--origin", choices=sorted(RECEIPT_ORIGINS))
    parser.add_argument("--allow-network", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    paths = DailyPaths(
        data_root=args.data_root,
        selector_pointer=args.selector_pointer,
        selector_path=args.selector_path,
        public_source_root=args.public_source_root,
        tdx_root=args.tdx_root,
        source_root=args.source_root,
        receipt_root=args.receipt_root,
        funasr_path=args.funasr_path,
        ffmpeg_path=args.ffmpeg_path,
        ytdlp_path=args.ytdlp_path,
        python_path=args.python_path,
        asr_python_path=args.asr_python_path,
        shared_package_root=args.shared_package_root,
        release_root=args.release_root,
        working_directory=args.working_directory,
        selector_target_trade_date=args.selector_target_trade_date,
        selector_cutoff=args.selector_cutoff,
        require_runtime_contract=args.require_runtime_contract,
        formal_pool_path=args.formal_pool_path,
        review_pool_path=args.review_pool_path,
        stage_root=args.stage_root,
    )
    result = run_daily(args.trade_date, paths=paths, allow_network=args.allow_network, origin=args.origin)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") in {"READY", "SCHEDULED", "WAITING_NOT_BEFORE_2025", "RETRY_BACKOFF", "NOOP_SKIP"} else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DailyPaths",
    "inspect_selector_pointer",
    "main",
    "review_bundle_is_ready",
    "run_daily",
    "runtime_contract",
    "selector_is_ready",
]
