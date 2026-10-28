from __future__ import annotations

import csv, hashlib, importlib, os, re, sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

SOURCE_ROLE = "A_SHARE_1MIN_STAGE_1445_1500"; STAGE_ID = "STAGE_1445_1500"
SOURCE_SCHEMA = "review_core.d1_stage7_replay_source.v1"; SAFETY_FLAGS = ("production_allowed", "buy_gate_updated", "orders_sent")
_CODE_RE = re.compile(r"^(?:A\.)?(\d{6})$", re.I); _MARKET_CODE_RE = re.compile(r"^(SH|SZ|BJ)[. ]?(\d{6})$", re.I)
_CODE_MARKET_RE = re.compile(r"^(\d{6})[. ]?(SH|SZ|BJ)$", re.I); _CLOCK_RE = re.compile(r"(?:(\d{4}-\d{2}-\d{2}|\d{8})[ T])?(\d{2}:\d{2}(?::\d{2})?)")
_DENY_KEYS = frozenset({"buy", "buy_signal", "primary_buy_signal", "secondary_buy_signal", "recommendation", "recommendation_status", "formal_recommendation", "trade_status", "selected", "stage_selected", "selection_status"})


def _date8(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise ValueError(f"{label} must use YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise ValueError(f"{label} must be a real calendar date") from error
    return value


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _flags() -> dict[str, bool]:
    return {name: False for name in SAFETY_FLAGS}


def _get(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, Mapping) else getattr(value, name, default)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _error(signal_date: Any, target_date: Any, reason: str) -> dict[str, Any]:
    flags = _flags()
    return {
        "schema": SOURCE_SCHEMA, "schema_version": SOURCE_SCHEMA,
        "source_role": SOURCE_ROLE, "stage_id": STAGE_ID, "status": "CANNOT_CONFIRM",
        "signal_date": signal_date, "target_date": target_date, "source_run_id": "",
        "source_sha256": "", "source_artifact_sha256": "", "source_manifest_sha256": "",
        "source_receipt_sha256": "", "source_paths": {name: "" for name in ("current", "artifact", "manifest", "receipt")},
        "source_refs": [], "rows": [], "row_count": 0, "cannot_confirm": [reason],
        "provenance": {}, "source_merge_role": "SOURCE_ONLY", "stage_selection_eligible": False,
        **flags, "safety_flags": flags,
    }


def _trusted_root() -> Path:
    configured = _text(os.environ.get("V3_SHARED_DATA_PACKAGE_ROOT"))
    root = Path(configured) if configured else Path(__file__).resolve().parent.parent / "v3_shared_data"
    root = root.resolve()
    if not root.is_dir() or not (root / "shared_data").is_dir():
        raise ValueError(f"TRUSTED_SHARED_DATA_PACKAGE_MISSING:{root}")
    return root


def _under(root: Path, path: Path, label: str) -> Path:
    try:
        resolved = path.resolve()
        resolved.relative_to(root.resolve())
    except (OSError, ValueError) as error:
        raise ValueError(f"TRUSTED_PATH_ESCAPE:{label}:{path}") from error
    return resolved


def _assert_module(module: Any, root: Path, label: str) -> Any:
    module_file = _get(module, "__file__")
    if not module_file:
        raise ValueError(f"TRUSTED_{label}_MODULE_NO_FILE")
    _under(root, Path(str(module_file)), f"trusted {label} module")
    return module


def _verified_reader() -> Any:
    root = _trusted_root()
    parent = sys.modules.get("shared_data")
    if parent is not None:
        _assert_module(parent, root, "shared_data")
    module = sys.modules.get("shared_data.consumer")
    if module is None:
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        importlib.invalidate_caches()
        try:
            module = importlib.import_module("shared_data.consumer")
        except Exception as error:
            raise ValueError(f"TRUSTED_SHARED_DATA_CONSUMER_UNAVAILABLE:{error}") from error
    _assert_module(module, root, "consumer")
    reader = _get(module, "read_verified_latest")
    if not callable(reader):
        raise ValueError("TRUSTED_SHARED_DATA_READER_MISSING")
    return reader


def _store_root(value: Path | str | None) -> Path:
    if value is not None:
        return Path(value).resolve()
    configured = _text(os.environ.get("V3_SHARED_DATA_STORE_ROOT"))
    return (Path(configured) if configured else Path(__file__).resolve().parent.parent / "v3_shared_data" / ".runtime" / "data").resolve()


def _normalize_code(value: Any) -> str:
    text = _text(value).upper().replace(" ", "")
    for pattern, index in ((_CODE_RE, 1), (_MARKET_CODE_RE, 2), (_CODE_MARKET_RE, 1)):
        match = pattern.fullmatch(text)
        if match:
            return f"A.{match.group(index)}"
    return ""


def _clock(value: Any, signal_date: str, label: str) -> str:
    match = _CLOCK_RE.search(_text(value))
    if not match:
        raise ValueError(f"ROW_{label.upper()}_INVALID")
    date_part, clock = match.groups()
    if date_part and date_part.replace("-", "") != signal_date:
        raise ValueError(f"ROW_{label.upper()}_DATE_MISMATCH")
    clock = f"{clock}:00" if len(clock) == 5 else clock
    try:
        datetime.strptime(clock, "%H:%M:%S")
    except ValueError as error:
        raise ValueError(f"ROW_{label.upper()}_INVALID") from error
    return clock


def _safe(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def _normalize_rows(raw_rows: list[Mapping[str, Any]], signal_date: str, target_date: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_rows:
        if not isinstance(raw, Mapping) or _text(raw.get("trade_date")) != signal_date:
            raise ValueError("ROW_TRADE_DATE_MISMATCH")
        code = _normalize_code(raw.get("code") or raw.get("symbol") or raw.get("ts_code"))
        if not code or code in seen:
            raise ValueError("ROW_CODE_INVALID_OR_DUPLICATE")
        seen.add(code)
        bar = _clock(raw.get("bar_time"), signal_date, "bar_time")
        window_end = _clock(raw.get("window_end"), signal_date, "window_end")
        if not ("14:45:00" <= bar <= "15:00:00" and "14:45:00" <= window_end <= "15:00:00"):
            raise ValueError("ROW_STAGE_WINDOW_MISMATCH")
        if bar > window_end:
            raise ValueError("ROW_BAR_AFTER_WINDOW_END")
        if raw.get("window_start") not in (None, ""):
            start = _clock(raw.get("window_start"), signal_date, "window_start")
            if not ("14:45:00" <= start <= window_end):
                raise ValueError("ROW_STAGE_WINDOW_MISMATCH")
        if not _safe(raw.get("temporal_cutoff_safe")):
            raise ValueError("ROW_TEMPORAL_CUTOFF_UNSAFE")
        item = {str(key): value for key, value in raw.items() if str(key).lower() not in _DENY_KEYS}
        item.update({
            "rank": len(rows) + 1, "market": "A", "symbol": code, "code": code.removeprefix("A."),
            "normalized_code": code, "name": _text(raw.get("name") or raw.get("stock_name")),
            "signal_date": signal_date, "target_date": target_date, "source_merge_role": "SOURCE_ONLY",
            "stage_selection_eligible": False, **_flags(),
        })
        rows.append(item)
    return rows


def _optional_path(root: Path, value: Any, label: str) -> Path | None:
    text = _text(value)
    return _under(root, Path(text), label) if text else None


def _receipt_fingerprint(path: Path | None) -> str:
    if path is None or not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_stage7_source(
    signal_date: str, target_date: str, shared_store_root: Path | str | None = None
) -> dict[str, Any]:
    """Read one exact signal-date verified Stage7 run, never a fallback."""
    try:
        signal, target = _date8(signal_date, "signal_date"), _date8(target_date, "target_date")
    except Exception as error:
        return _error(signal_date, target_date, f"DATE_INVALID:{error}")
    try:
        root = _store_root(shared_store_root)
        reader = _verified_reader()
        verified = reader(root, signal, SOURCE_ROLE)
        manifest, receipt = _mapping(_get(verified, "manifest")), _mapping(_get(verified, "receipt"))
        latest, verification = _mapping(_get(verified, "latest")), _mapping(_get(verified, "verification"))
        if not manifest or not receipt or not latest or not verification:
            raise ValueError("VERIFIED_RESULT_INCOMPLETE")
        statuses = [_text(item.get("status")) for item in (receipt, verification, latest)]
        if manifest.get("status") not in (None, ""):
            statuses.append(_text(manifest.get("status")))
        if not statuses or any(status != statuses[0] for status in statuses):
            raise ValueError("VERIFIED_STATUS_MISMATCH")
        if statuses[0] != "READY":
            raise ValueError(f"VERIFIED_STATUS_NOT_READY:{statuses[0]}")
        for key, expected in (("trade_date", signal), ("role", SOURCE_ROLE), ("stage_id", STAGE_ID)):
            if receipt.get(key) != expected:
                raise ValueError(f"VERIFIED_RECEIPT_{key.upper()}_MISMATCH")
        for item in (manifest, latest, verification):
            for key in ("trade_date", "signal_date"):
                if item.get(key) not in (None, "", signal):
                    raise ValueError(f"VERIFIED_{key.upper()}_MISMATCH")
            if item.get("role") not in (None, "", SOURCE_ROLE) or item.get("stage_id") not in (None, "", STAGE_ID):
                raise ValueError("VERIFIED_IDENTITY_MISMATCH")
        run_id = _text(verification.get("run_id") or receipt.get("run_id") or latest.get("run_id"))
        if not run_id or any(item.get("run_id") not in (None, "", run_id) for item in (receipt, latest, verification)):
            raise ValueError("VERIFIED_RUN_ID_MISMATCH")
        nested = receipt.get("safety_flags")
        for name in SAFETY_FLAGS:
            if receipt.get(name) is not False or (isinstance(nested, Mapping) and nested.get(name) is not False):
                raise ValueError(f"VERIFIED_UNSAFE_FLAG:{name}")
        if manifest.get("market") not in (None, "", "A_SHARE") or manifest.get("cutoff_at") not in (None, "", "15:00:00"):
            raise ValueError("VERIFIED_STAGE_CONTRACT_MISMATCH")
        if manifest.get("temporal_cutoff_safe") not in (None, "") and not _safe(manifest.get("temporal_cutoff_safe")):
            raise ValueError("VERIFIED_TEMPORAL_CUTOFF_UNSAFE")
        artifact_path = _under(root, Path(str(_get(verified, "artifact_path") or "")), "verified artifact")
        if not artifact_path.is_file():
            raise ValueError("VERIFIED_ARTIFACT_MISSING")
        manifest_path = _optional_path(root, _get(verified, "manifest_path"), "verified manifest")
        receipt_path = _optional_path(root, _get(verified, "receipt_path"), "verified receipt")
        artifact_sha = _text(_get(verified, "artifact_sha256") or verification.get("artifact_sha256") or receipt.get("artifact_sha256")).lower()
        manifest_sha = _text(_get(verified, "manifest_sha256") or verification.get("manifest_sha256") or receipt.get("manifest_sha256")).lower()
        if not artifact_sha or not manifest_sha:
            raise ValueError("VERIFIED_PROVENANCE_SHA_MISSING")
        receipt_sha = _text(_get(verified, "receipt_sha256") or verification.get("receipt_sha256") or receipt.get("receipt_sha256") or latest.get("receipt_sha256")).lower()
        receipt_sha = receipt_sha or _receipt_fingerprint(receipt_path)
        with artifact_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = _normalize_rows(list(csv.DictReader(handle)), signal, target)
        if not rows:
            raise ValueError("ROW_EVIDENCE_EMPTY")
        paths = {
            "current": str(root / "latest.json"), "artifact": str(artifact_path),
            "manifest": str(manifest_path) if manifest_path else "", "receipt": str(receipt_path) if receipt_path else "",
        }
        refs = [{"role": SOURCE_ROLE, "run_id": run_id, "artifact_sha256": artifact_sha, "manifest_sha256": manifest_sha, "receipt_sha256": receipt_sha, "paths": dict(paths)}]
        flags = _flags()
        return {
            "schema": SOURCE_SCHEMA, "schema_version": SOURCE_SCHEMA, "source_role": SOURCE_ROLE, "stage_id": STAGE_ID,
            "status": "READY", "signal_date": signal, "target_date": target, "source_run_id": run_id,
            "source_sha256": artifact_sha, "source_artifact_sha256": artifact_sha, "source_manifest_sha256": manifest_sha,
            "source_receipt_sha256": receipt_sha, "source_paths": paths, "source_refs": refs,
            "provenance": {"manifest": dict(manifest), "receipt": dict(receipt), "verification": dict(verification)},
            "rows": rows, "row_count": len(rows), "cannot_confirm": [], "source_merge_role": "SOURCE_ONLY",
            "stage_selection_eligible": False, **flags, "safety_flags": flags,
        }
    except Exception as error:
        return _error(signal, target, f"SOURCE_LOAD_FAILED:{type(error).__name__}:{error}")


__all__ = ["load_stage7_source"]
