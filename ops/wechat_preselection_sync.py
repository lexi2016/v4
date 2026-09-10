"""Narrow exact-date WeChat preselection materialization for V3.5.

Only the active input pair
``V35_PRESELECTION_INPUT_ROOT/<effective_date>/wechat_{manifest,rows}`` is
read.  This entry point does not collect, enumerate, or invoke any other
stage owner.  A missing pair is an explicit ``CANNOT_CONFIRM`` result; a
partial, unsafe, stale, or conflicting pair fails closed before the store is
allowed to write.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from domains.preselection_materializer import build_wechat_pool
from infrastructure.preselection_pool_store import PreselectionPoolStore


POOL_ID = "wechat_public_account_v3_preselect"
INPUT_ROOT_ENV = "V35_PRESELECTION_INPUT_ROOT"
DATA_ROOT_ENV = "V35_DATA_ROOT"
SYNC_RECEIPT_SCHEMA = "v3_5.wechat_preselection_sync_receipt.v1"
_DATE_RE = re.compile(r"^\d{8}$")
_CODE_RE = re.compile(r"^\d{6}\.(?:SH|SZ|BJ)$", re.IGNORECASE)
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_EXPECTED_V35_INPUT_CONTRACT = "V3_WECHAT_PRESELECT_TO_V35_EXACT_EFFECTIVE_DATE_V1"
_FORMAL_DATA_ROOT = (
    Path.home()
    / "Library"
    / "Application Support"
    / "com.lexi.v35.local"
    / "state"
    / "data"
)
_DOCUMENTS_CODEX_ROOT = Path.home() / "Documents" / "Codex"
_SAFETY_KEYS = frozenset(
    {
        "production_allowed",
        "buy_gate_updated",
        "orders_sent",
        "order_sent",
        "formal_pool_write",
        "buy_gate_write",
        "opens_buy_gate",
        "order_allowed",
    }
)


class WechatSyncError(ValueError):
    """Raised when an exact-date active WeChat pair cannot be trusted."""


def _date(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise WechatSyncError(f"{field} must be a real YYYYMMDD date")
    text = value.strip()
    if not _DATE_RE.fullmatch(text):
        raise WechatSyncError(f"{field} must be a real YYYYMMDD date")
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError as error:
        raise WechatSyncError(f"{field} must be a real YYYYMMDD date") from error
    return text


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_is_under(path: Path, base: Path) -> bool:
    return path == base or base in path.parents


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            if current.is_symlink():
                raise WechatSyncError(f"symlink path is not allowed: {path}")
        except OSError as error:
            raise WechatSyncError(f"path cannot be inspected for symlink safety: {path}") from error


def _validate_scoped_path(value: Path | str, *, label: str) -> Path:
    try:
        raw = os.fspath(value)
    except TypeError as error:
        raise WechatSyncError(f"{label} path is invalid") from error
    if not isinstance(raw, str) or not raw or "\\" in raw:
        raise WechatSyncError(f"{label} path is outside allowed roots")
    if re.match(r"^(?:[A-Za-z]:|//|\\\\)", raw):
        raise WechatSyncError(f"{label} path is outside allowed roots")
    path = Path(os.path.normpath(os.path.expanduser(raw)))
    if not path.is_absolute():
        raise WechatSyncError(f"{label} path must be absolute")
    if any(part.casefold() in {"desktop", "windows"} for part in path.parts):
        raise WechatSyncError(f"{label} path is outside allowed roots")

    formal = Path(os.path.normpath(os.fspath(_FORMAL_DATA_ROOT)))
    documents = Path(os.path.normpath(os.fspath(_DOCUMENTS_CODEX_ROOT)))
    in_test_root = False
    if _path_is_under(path, documents):
        for ancestor in (path, *path.parents):
            if _path_is_under(ancestor, documents) and ancestor.name.startswith(
                "v35-stage-selection-"
            ):
                in_test_root = True
                break
    if not _path_is_under(path, formal) and not in_test_root:
        raise WechatSyncError(f"{label} path is outside allowed roots")
    _reject_symlink_components(path)
    return path


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path = _validate_scoped_path(Path(path), label="receipt")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        content = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
            "utf-8"
        )
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _resolve_root(value: Path | str | None, env_name: str) -> Path:
    raw = value if value is not None else os.environ.get(env_name)
    if raw in (None, ""):
        raise WechatSyncError(f"{env_name} is required")
    return _validate_scoped_path(Path(raw), label=env_name)


def _active_pair(input_root: Path, effective_date: str) -> tuple[Path, Path] | None:
    _validate_scoped_path(input_root, label="input root")
    day = input_root / effective_date
    manifest = day / "wechat_manifest.json"
    rows = day / "wechat_rows.csv"
    _reject_symlink_components(day)
    _reject_symlink_components(manifest)
    _reject_symlink_components(rows)
    manifest_exists = manifest.exists()
    rows_exists = rows.exists()
    if not manifest_exists and not rows_exists:
        return None
    if manifest_exists != rows_exists:
        raise WechatSyncError("partial exact-date WeChat input pair")
    if not manifest.is_file() or not rows.is_file():
        raise WechatSyncError("exact-date WeChat input pair must contain regular files")
    # The active root is the only permitted source boundary. A symlinked file
    # or ancestor would turn this narrow consumer into an accidental
    # cross-root collector.
    if day.parent != input_root:
        raise WechatSyncError("WeChat input date escaped active input root")
    if manifest.parent != day or rows.parent != day:
        raise WechatSyncError("WeChat input pair escaped exact-date directory")
    return manifest, rows


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise WechatSyncError("invalid exact-date WeChat manifest") from error
    if not isinstance(value, dict):
        raise WechatSyncError("exact-date WeChat manifest must be an object")
    return value


def _read_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if not reader.fieldnames:
                raise WechatSyncError("exact-date WeChat rows CSV header missing")
            rows = [dict(row) for row in reader]
            return rows, list(reader.fieldnames)
    except WechatSyncError:
        raise
    except (OSError, UnicodeError, csv.Error) as error:
        raise WechatSyncError("invalid exact-date WeChat rows CSV") from error


def _is_safe_false(value: Any) -> bool:
    if value is False or value == 0 or value is None or value == "":
        return True
    return isinstance(value, str) and value.strip().casefold() in {"false", "0"}


def _reject_unsafe(value: Any, *, context: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).casefold() in _SAFETY_KEYS and not _is_safe_false(nested):
                raise WechatSyncError(f"unsafe {context} safety flag: {key}")
            _reject_unsafe(nested, context=context)
    elif isinstance(value, list):
        for nested in value:
            _reject_unsafe(nested, context=context)


def _article_date(value: Any, signal_date: str) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if _DATE_RE.fullmatch(text):
        try:
            parsed = _date(text, "article_publish_date")
        except WechatSyncError:
            return False
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            parsed = _date(text.replace("-", ""), "article_publish_date")
        except WechatSyncError:
            return False
    else:
        return False
    return parsed == signal_date


def _validate_pair(
    manifest_path: Path, rows_path: Path, effective_date: str
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    manifest = _read_manifest(manifest_path)
    rows, fields = _read_rows(rows_path)
    if manifest.get("status") != "WECHAT_V3_PRESELECT_READY":
        raise WechatSyncError("WeChat manifest is not READY")
    manifest_effective_date = _date(
        manifest.get("effective_trade_date"), "effective_trade_date"
    )
    if manifest_effective_date != effective_date:
        raise WechatSyncError("WeChat effective trade-date mismatch")
    signal_date = _date(manifest.get("signal_date"), "signal_date")
    article_date = _date(manifest.get("article_publish_date"), "article_publish_date")
    selector_score_date = _date(manifest.get("selector_score_date"), "selector_score_date")
    manifest_target_date = _date(manifest.get("target_date"), "target_date")
    if article_date != signal_date:
        raise WechatSyncError("WeChat article/signal date mismatch")
    if manifest_target_date != signal_date:
        raise WechatSyncError("WeChat target/signal date mismatch")
    if datetime.strptime(selector_score_date, "%Y%m%d") > datetime.strptime(
        signal_date, "%Y%m%d"
    ):
        raise WechatSyncError("WeChat selector score date is after signal date")
    target_validation = manifest.get("target_validation")
    if not isinstance(target_validation, Mapping) or target_validation.get("status") not in {
        "PASS",
        "TARGET_DATE_CHECK_PASS",
    }:
        raise WechatSyncError("WeChat target-date evidence missing")
    for key, expected in (
        ("date_match", True),
        ("title_match", True),
        ("allow_mismatch", False),
    ):
        if type(target_validation.get(key)) is not bool or target_validation.get(key) is not expected:
            raise WechatSyncError(f"WeChat target validation {key} is not {expected}")
    target_date = _date(
        target_validation.get("target_date"), "target_validation.target_date"
    )
    if target_date != signal_date:
        raise WechatSyncError("WeChat target-date validation does not equal signal date")

    if manifest.get("v35_input_contract") != _EXPECTED_V35_INPUT_CONTRACT:
        raise WechatSyncError("WeChat v35_input_contract is invalid")
    v35_input = manifest.get("v35_input")
    if not isinstance(v35_input, Mapping):
        raise WechatSyncError("WeChat v35_input contract is missing")
    v35_effective_date = _date(
        v35_input.get("effective_trade_date"), "v35_input.effective_trade_date"
    )
    v35_selector_date = _date(
        v35_input.get("selector_score_date"), "v35_input.selector_score_date"
    )
    v35_signal_date = _date(
        v35_input.get("source_signal_date"), "v35_input.source_signal_date"
    )
    if v35_effective_date != manifest_effective_date or v35_selector_date != selector_score_date:
        raise WechatSyncError("WeChat v35_input calendar binding mismatch")
    if v35_signal_date != signal_date:
        raise WechatSyncError("WeChat v35_input source signal mismatch")
    source_rows_count = v35_input.get("source_rows_count")
    if type(source_rows_count) is not int or source_rows_count != len(rows):
        raise WechatSyncError("WeChat v35_input source row count mismatch")
    source_rows_sha256 = v35_input.get("source_rows_sha256")
    if not isinstance(source_rows_sha256, str) or not _SHA256_RE.fullmatch(source_rows_sha256):
        raise WechatSyncError("WeChat v35_input source rows hash is invalid")
    if source_rows_sha256.casefold() != _sha256(rows_path):
        raise WechatSyncError("WeChat v35_input source rows hash mismatch")
    source_manifest_sha256 = v35_input.get("source_manifest_sha256")
    if not isinstance(source_manifest_sha256, str) or not _SHA256_RE.fullmatch(
        source_manifest_sha256
    ):
        raise WechatSyncError("WeChat publisher manifest identity/hash contract is missing")
    source_fields = v35_input.get("source_fields")
    if source_fields is not None and (
        not isinstance(source_fields, list)
        or any(not isinstance(field, str) for field in source_fields)
        or source_fields != fields
    ):
        raise WechatSyncError("WeChat v35_input source fields mismatch")

    boundary = manifest.get("boundary")
    if (
        not isinstance(boundary, Mapping)
        or boundary.get("formal_pool_write") is not False
        or boundary.get("buy_gate_write") is not False
    ):
        raise WechatSyncError("WeChat research-only safety boundary mismatch")
    _reject_unsafe(manifest, context="manifest")
    if manifest.get("score_scope") != "wechat_pool_ts_codes_only":
        raise WechatSyncError("WeChat score scope mismatch")
    counts = manifest.get("counts")
    expected_count = counts.get("v3_matched_codes") if isinstance(counts, Mapping) else None
    if type(expected_count) is not int or expected_count <= 0:
        raise WechatSyncError("WeChat matched row count invalid")
    if len(rows) != expected_count:
        raise WechatSyncError("WeChat manifest/rows count conflict")

    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        _reject_unsafe(row, context="row")
        raw_code = ""
        for key in ("ts_code", "stock_code", "code"):
            candidate = row.get(key)
            if candidate not in (None, ""):
                raw_code = str(candidate).strip().upper()
                break
        if not _CODE_RE.fullmatch(raw_code) or raw_code in seen:
            raise WechatSyncError("WeChat row code identity conflict")
        if "publish_date" in row and not _article_date(row.get("publish_date"), signal_date):
            raise WechatSyncError("WeChat row article publish date mismatch")
        if "trade_date" in row:
            if _date(row.get("trade_date"), "row.trade_date") != selector_score_date:
                raise WechatSyncError("WeChat row selector trade date mismatch")
        if "target_date" in row:
            if _date(row.get("target_date"), "row.target_date") != effective_date:
                raise WechatSyncError("WeChat row effective trade-date mismatch")
        if "v3_match" in row and str(row.get("v3_match") or "").strip().casefold() != "true":
            raise WechatSyncError("WeChat row v3_match is not true")
        if "wechat_pool_lane" in row and row.get("wechat_pool_lane") != "research_lane_observation_preselect":
            raise WechatSyncError("WeChat row lane mismatch")
        if "wechat_v3_preselect_rank" in row:
            rank = str(row.get("wechat_v3_preselect_rank") or "")
            if not rank.isdigit() or int(rank) != index:
                raise WechatSyncError("WeChat row rank conflict")
        seen.add(raw_code)
    return manifest, rows


def _existing_artifact(
    store: PreselectionPoolStore,
    effective_date: str,
    artifact: Mapping[str, Any],
) -> tuple[bool, dict[str, Any] | None]:
    artifact_path = store.root / "preselection_pools" / effective_date / f"{POOL_ID}.json"
    receipt_path = store.root / "preselection_pools" / effective_date / "receipts" / f"{POOL_ID}.json"
    manifest_path = store.root / "preselection_pools" / effective_date / "manifest.json"
    any_existing = any(path.exists() for path in (artifact_path, receipt_path, manifest_path))
    if not any_existing:
        return False, None
    try:
        existing = store.read_pool(effective_date, POOL_ID)
    except (FileNotFoundError, OSError, ValueError) as error:
        raise WechatSyncError("conflicting or partial existing WeChat materialization") from error
    if dict(existing) != dict(artifact):
        raise WechatSyncError("conflicting exact-date WeChat materialization")
    return True, existing


def _receipt_base(
    *,
    effective_date: str,
    status: str,
    cannot_confirm: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SYNC_RECEIPT_SCHEMA,
        "sync_type": "V35_WECHAT_EXACT_DATE_PRESELECTION",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "effective_trade_date": effective_date,
        "status": status,
        "cannot_confirm": list(cannot_confirm or []),
        "artifact_created": False,
        "run_created": False,
        "no_run_created": True,
        "no_run": True,
        "publish": False,
        "publish_allowed": False,
        "no_publish": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _write_optional_receipt(receipt: dict[str, Any], receipt_path: Path | str | None) -> dict[str, Any]:
    if receipt_path is not None:
        path = _validate_scoped_path(Path(receipt_path), label="receipt")
        receipt["receipt_path"] = str(path)
        _write_json(path, receipt)
    return receipt


def _reject_overlapping_paths(left: Path, right: Path, *, message: str) -> None:
    if left == right or left in right.parents or right in left.parents:
        raise WechatSyncError(message)


def sync_wechat_preselection(
    effective_date: str,
    *,
    input_root: Path | str | None = None,
    data_root: Path | str | None = None,
    receipt_path: Path | str | None = None,
) -> dict[str, Any]:
    """Materialize one exact active WeChat input pair into the V3.5 pool store."""

    effective_date = _date(effective_date, "effective_trade_date")
    active_root = _resolve_root(input_root, INPUT_ROOT_ENV)
    validated_receipt: Path | None = None
    if receipt_path is not None:
        validated_receipt = _validate_scoped_path(Path(receipt_path), label="receipt")
        _reject_overlapping_paths(
            active_root,
            validated_receipt,
            message="receipt path overlaps read-only active input root",
        )
    pair = _active_pair(active_root, effective_date)
    if pair is None:
        return _write_optional_receipt(
            {
                **_receipt_base(
                    effective_date=effective_date,
                    status="CANNOT_CONFIRM",
                    cannot_confirm=["WECHAT_EXACT_DATE_INPUT_MISSING"],
                ),
                "input_root": str(active_root),
                "input_manifest_path": None,
                "input_rows_path": None,
            },
            validated_receipt,
        )

    destination_root = _resolve_root(data_root, DATA_ROOT_ENV)
    _reject_overlapping_paths(
        active_root,
        destination_root,
        message="V3.5 data root overlaps read-only active input root",
    )
    manifest_path, rows_path = pair
    manifest, rows = _validate_pair(manifest_path, rows_path, effective_date)
    try:
        artifact = build_wechat_pool(manifest_path, rows_path, effective_date)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise WechatSyncError(f"WeChat domain build rejected exact-date input: {error}") from error
    if artifact.get("pool_id") != POOL_ID or artifact.get("status") != "WECHAT_V3_PRESELECT_READY":
        raise WechatSyncError("WeChat domain build did not produce READY pool")
    if len(artifact.get("rows") or []) != len(rows):
        raise WechatSyncError("WeChat domain build row count conflict")
    for key in ("production_allowed", "buy_gate_updated", "orders_sent"):
        if artifact.get(key) is not False:
            raise WechatSyncError(f"WeChat artifact safety flag is not false: {key}")

    store = PreselectionPoolStore(destination_root)
    reused, _existing = _existing_artifact(store, effective_date, artifact)
    try:
        store_result = store.materialize(artifact)
    except (OSError, ValueError) as error:
        raise WechatSyncError(f"WeChat store materialization rejected exact-date input: {error}") from error
    receipt = _receipt_base(effective_date=effective_date, status="READY")
    receipt.update(
        {
            "reused": reused,
            "artifact_created": not reused,
            "input_root": str(active_root),
            "input_manifest_path": str(manifest_path),
            "input_rows_path": str(rows_path),
            "input_manifest_sha256": _sha256(manifest_path),
            "input_rows_sha256": _sha256(rows_path),
            "row_count": len(rows),
            "store": store_result,
            "pool_artifact_path": store_result["artifact_path"],
            "pool_receipt_path": store_result["receipt_path"],
            "pool_id": POOL_ID,
            "source_role": artifact.get("source_role"),
            "manifest_status": manifest.get("status"),
        }
    )
    return _write_optional_receipt(receipt, validated_receipt)


# Keep call-site vocabulary flexible without introducing a second workflow.
sync_active_wechat_preselection = sync_wechat_preselection
materialize_wechat_preselection = sync_wechat_preselection
run_sync = sync_wechat_preselection


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize one exact-date active WeChat V3 preselection pair")
    parser.add_argument("--effective-date", required=True)
    parser.add_argument("--input-root", type=Path, default=None)
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        result = sync_wechat_preselection(
            args.effective_date,
            input_root=args.input_root,
            data_root=args.data_root,
            receipt_path=args.receipt,
        )
    except WechatSyncError as error:
        print(json.dumps({"status": "REJECTED", "error": str(error)}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
