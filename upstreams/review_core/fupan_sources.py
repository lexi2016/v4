"""Strict ReviewBundleV1 source adapter for the A-share D-1 fupan pool.

This module deliberately has one upstream: :func:`review.inspect_review_bundle`.
The verifier owns ReviewBundleV1 manifest, receipt, and SHA validation.  After
that verification succeeds we only read the exact-date ``current.json`` pointer
to carry its immutable source identity into the downstream pool artifact.
"""
from __future__ import annotations

import copy
import html as html_lib
import importlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

try:
    from . import review
except ImportError:  # pragma: no cover - direct focused invocation
    import review  # type: ignore[no-redef]


D1_FUPAN_REVIEW_POOL_V1 = "D1_FUPAN_REVIEW_POOL_V1"
SOURCE_SCHEMA = "review_core.d1_fupan_review_source.v1"
ANCHOR_ROLE = "anchor_role_v3_rows"
SAFETY_FLAGS = ("production_allowed", "buy_gate_updated", "orders_sent")

_CURRENT_SCHEMA = "review_core.review_bundle.current.v1"
_MARKET_CODE_RE = re.compile(r"^(?P<market>SH|SZ|BJ)[. ]?(?P<code>\d{6})$")
_CODE_MARKET_RE = re.compile(r"^(?P<code>\d{6})[. ]?(?P<market>SH|SZ|BJ)?$")


def _date8(value: Any, label: str = "signal_date") -> str:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise ValueError(f"{label} must use YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise ValueError(f"{label} must be a real calendar date") from error
    return value


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _canonical_json_read(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"review bundle current pointer unreadable: {path}") from error
    if not isinstance(value, Mapping):
        raise ValueError("review bundle current pointer must be an object")
    return value


def _current_pointer(signal_date: str, bundle_root: Path) -> tuple[dict[str, Any], dict[str, str]]:
    """Read only the exact-date pointer after the deep verifier has passed."""

    current_path = bundle_root / "review_bundle" / signal_date / "current.json"
    current = dict(_canonical_json_read(current_path))
    if current.get("schema_version") != _CURRENT_SCHEMA:
        raise ValueError("review bundle current pointer schema mismatch")
    if current.get("trade_date") != signal_date:
        raise ValueError("review bundle current pointer date mismatch")
    run_id = _text(current.get("run_id"))
    if not run_id:
        raise ValueError("review bundle current pointer run_id missing")

    expected_run = f"review_bundle/{signal_date}/runs/{run_id}"
    expected = {
        "run_path": expected_run,
        "bundle_path": f"{expected_run}/review_bundle.json",
        "manifest_path": f"{expected_run}/manifest.json",
        "receipt_path": f"{expected_run}/receipt.json",
    }
    paths: dict[str, str] = {"current": str(current_path)}
    for name, relative in expected.items():
        actual = _text(current.get(name)).replace("\\", "/")
        if actual != relative:
            raise ValueError(f"review bundle current pointer {name} is not exact-date")
        paths[name.removesuffix("_path")] = str(bundle_root / Path(relative))
    for name in ("bundle_sha256", "manifest_sha256", "receipt_sha256"):
        value = _text(current.get(name)).lower()
        # The deep ReviewBundle verifier owns SHA format/content validation;
        # this adapter only carries the non-empty ledger values forward.
        if not value:
            raise ValueError(f"review bundle current pointer {name} missing")
        current[name] = value
    for name in SAFETY_FLAGS:
        if current.get("safety_flags", {}).get(name) is not False:
            raise ValueError(f"review bundle current pointer unsafe flag: {name}")
    current["run_id"] = run_id
    return current, paths


def _error_source(signal_date: Any, reason: str) -> dict[str, Any]:
    flags = {name: False for name in SAFETY_FLAGS}
    return {
        "schema": SOURCE_SCHEMA,
        "schema_version": SOURCE_SCHEMA,
        "source_role": ANCHOR_ROLE,
        "status": "CANNOT_CONFIRM",
        "signal_date": signal_date,
        "source_run_id": "",
        "source_sha256": "",
        "source_manifest_sha256": "",
        "source_receipt_sha256": "",
        "public_fupan_run_id": "",
        "public_fupan_manifest_sha256": "",
        "public_fupan_plate_sha256": "",
        "public_fupan_plate_path": "",
        "source_paths": {name: "" for name in ("current", "run", "bundle", "manifest", "receipt")},
        "rows": [],
        "video": {"status": "CANNOT_CONFIRM"},
        "video_status": "CANNOT_CONFIRM",
        "cannot_confirm": [reason],
        "source_refs": [],
        "provenance": {},
        **flags,
        "safety_flags": flags,
    }


def _trusted_package_root() -> Path:
    configured = _text(os.environ.get("V3_SHARED_DATA_PACKAGE_ROOT"))
    root = Path(configured) if configured else Path(__file__).resolve().parent.parent / "v3_shared_data"
    root = root.absolute()
    if not root.is_dir():
        raise ValueError(f"trusted shared_data package root missing: {root}")
    return root


def _public_fupan_module() -> Any:
    trusted_root = _trusted_package_root()
    if str(trusted_root) not in sys.path:
        sys.path.insert(0, str(trusted_root))
    module = importlib.import_module("shared_data.public_fupan")
    module_file = getattr(module, "__file__", None)
    if not module_file:
        raise ValueError("trusted public_fupan module has no __file__")
    try:
        Path(module_file).resolve().relative_to(trusted_root.resolve())
    except ValueError as error:
        raise ValueError(f"trusted public_fupan module path mismatch: {module_file}") from error
    reader = getattr(module, "read_public_fupan", None)
    if not callable(reader):
        raise ValueError("trusted public_fupan reader missing")
    return module


def _clean_html_text(value: Any) -> str:
    text = html_lib.unescape(str(value or ""))
    text = re.sub(r"<[^>]*>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_plate_html(raw_html: Any) -> list[dict[str, str]]:
    if not isinstance(raw_html, str) or not raw_html.strip():
        raise ValueError("PUBLIC_FUPAN_HTML_MISSING")
    starts = list(re.finditer(r"<div\b[^>]*class\s*=\s*['\"][^'\"]*\bztitem\b[^'\"]*['\"][^>]*>", raw_html, re.I))
    if not starts:
        raise ValueError("PUBLIC_FUPAN_PLATE_BLOCKS_MISSING")
    selected: list[dict[str, str]] = []
    seen_codes: set[str] = set()
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(raw_html)
        block = raw_html[start.start() : end]
        board_match = re.search(r"<b\b[^>]*>(.*?)</b>", block, re.I | re.S)
        board = _clean_html_text(board_match.group(1) if board_match else "")
        if not board:
            raise ValueError("PUBLIC_FUPAN_THEME_MISSING")
        block_rows: list[dict[str, str]] = []
        for tr in re.findall(r"<tr\b[^>]*>.*?</tr>", block, re.I | re.S):
            code_attr = re.search(r"\bcode\s*=\s*['\"]([^'\"]*)['\"]", tr, re.I)
            if not code_attr:
                if re.search(r"\bkline\b", tr, re.I):
                    raise ValueError("PUBLIC_FUPAN_CODE_MISSING")
                continue
            code, exchange = _code_and_market(code_attr.group(1))
            if not code:
                raise ValueError("PUBLIC_FUPAN_CODE_INVALID")
            first_td = re.search(r"<td\b[^>]*>(.*?)</td>", tr, re.I | re.S)
            name = _clean_html_text(first_td.group(1) if first_td else "")
            if not name:
                raise ValueError("PUBLIC_FUPAN_NAME_MISSING")
            if code in seen_codes:
                raise ValueError("PUBLIC_FUPAN_CODE_DUPLICATE")
            seen_codes.add(code)
            block_rows.append({"theme": board, "name": name, "code": code, "exchange": exchange})
        selected.extend(block_rows[:8])
    if not selected:
        raise ValueError("PUBLIC_FUPAN_ROWS_MISSING")
    return selected


def _read_public_payload(
    shared_store_root: Path | str,
    signal_date: str,
    public_fupan_loader: Callable[[Path | str, str], Any] | None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    loader = public_fupan_loader
    if loader is None:
        loader = getattr(_public_fupan_module(), "read_public_fupan")
    try:
        verified = loader(shared_store_root, signal_date)
    except Exception as error:
        message = str(error)
        if message.startswith("PUBLIC_FUPAN_VERIFY_FAILED"):
            raise
        raise ValueError(f"PUBLIC_FUPAN_VERIFY_FAILED:{type(error).__name__}:{error}") from error
    if not isinstance(verified, Mapping):
        raise ValueError("PUBLIC_FUPAN_VERIFY_FAILED:NON_OBJECT")
    manifest = verified.get("manifest")
    receipt = verified.get("receipt")
    entry = verified.get("entry")
    files = verified.get("files")
    if not isinstance(manifest, Mapping) or not isinstance(receipt, Mapping) or not isinstance(entry, Mapping) or not isinstance(files, Mapping):
        raise ValueError("PUBLIC_FUPAN_VERIFY_FAILED:PROVENANCE_MISSING")
    run_id = _text(entry.get("run_id") or manifest.get("run_id") or receipt.get("run_id"))
    if not run_id or any(_text(item.get("run_id")) != run_id for item in (manifest, receipt)):
        raise ValueError("PUBLIC_FUPAN_VERIFY_FAILED:RUN_ID_MISMATCH")
    if any(_text(item.get("trade_date")) != signal_date for item in (manifest, receipt)):
        raise ValueError("PUBLIC_FUPAN_VERIFY_FAILED:DATE_MISMATCH")
    file_meta = manifest.get("files")
    plate_meta = file_meta.get("plate.json") if isinstance(file_meta, Mapping) else None
    plate_data = files.get("plate.json")
    if not isinstance(plate_meta, Mapping) or not isinstance(plate_data, (bytes, bytearray, str)):
        raise ValueError("PUBLIC_FUPAN_VERIFY_FAILED:PLATE_MISSING")
    plate_bytes = plate_data.encode("utf-8") if isinstance(plate_data, str) else bytes(plate_data)
    try:
        payload = json.loads(plate_bytes.decode("utf-8", "replace"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("PUBLIC_FUPAN_VERIFY_FAILED:PLATE_JSON_INVALID") from error
    if not isinstance(payload, Mapping) or payload.get("result") != "success" or not _text(payload.get("html")):
        raise ValueError("PUBLIC_FUPAN_VERIFY_FAILED:PLATE_NOT_READY")
    rows = _parse_plate_html(payload.get("html"))
    plate_path = _text(plate_meta.get("relative"))
    manifest_sha = _text(receipt.get("manifest_sha256"))
    plate_sha = _text(plate_meta.get("sha256"))
    if not plate_path or not manifest_sha or not plate_sha:
        raise ValueError("PUBLIC_FUPAN_VERIFY_FAILED:PLATE_PROVENANCE_MISSING")
    safe_plate_path = Path(plate_path.replace("\\", "/"))
    if safe_plate_path.is_absolute() or ".." in safe_plate_path.parts:
        raise ValueError("PUBLIC_FUPAN_VERIFY_FAILED:PLATE_PATH_UNSAFE")
    return rows, {
        "run_id": run_id,
        "manifest_sha256": manifest_sha,
        "plate_sha256": plate_sha,
        "plate_path": plate_path,
    }


def _code_and_market(value: Any) -> tuple[str, str]:
    text = _text(value).upper()
    if not text or "HK" in text:
        return "", ""
    match = _MARKET_CODE_RE.fullmatch(text)
    if match:
        return match.group("code"), match.group("market")
    match = _CODE_MARKET_RE.fullmatch(text)
    if not match:
        return "", ""
    code = match.group("code")
    market = match.group("market")
    if market:
        return code, market
    if code.startswith(("60", "68")):
        return code, "SH"
    if code.startswith(("43", "83", "87", "88")):
        return code, "BJ"
    return code, "SZ"


def normalize_a_share_code(value: Any) -> str:
    """Normalize an explicitly supplied A-share code to six digits.

    The accepted forms are six digits, ``SH/SZ/BJ`` prefixes or suffixes, and
    their dotted/space-separated variants.  HK symbols and all other markets
    are rejected rather than mapped by name or by a fallback table.
    """

    return _code_and_market(value)[0]


def market_for_a_share_code(value: Any) -> str:
    return _code_and_market(value)[1]


def _value_from(row: Mapping[str, Any], names: tuple[str, ...], default: Any = "") -> Any:
    for name in names:
        if name in row and row.get(name) not in (None, ""):
            return copy.deepcopy(row[name])
    return copy.deepcopy(default)


def _cannot_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return copy.deepcopy(value)
    if isinstance(value, tuple):
        return list(copy.deepcopy(value))
    return [copy.deepcopy(value)]


def _anchor_rows(
    bundle: Mapping[str, Any],
    *,
    public_rows: list[dict[str, str]],
    signal_date: str,
    source_run_id: str,
    source_paths: Mapping[str, str],
    source_sha256: str,
    source_manifest_sha256: str,
    source_receipt_sha256: str,
    video_status: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    compatibility = bundle.get("compatibility")
    if not isinstance(compatibility, Mapping):
        return [], ["ANCHOR_ROWS_MISSING"]
    raw_rows = compatibility.get(ANCHOR_ROLE)
    if not isinstance(raw_rows, list) or not raw_rows:
        return [], ["ANCHOR_ROWS_MISSING"]
    if len(raw_rows) != len(public_rows):
        return [], ["PUBLIC_FUPAN_ALIGNMENT_MISMATCH"]

    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for raw, public in zip(raw_rows, public_rows):
        if not isinstance(raw, Mapping):
            errors.append("ANCHOR_ROW_INVALID")
            continue
        name = _text(raw.get("stock") or raw.get("name") or raw.get("stock_name"))
        role = _text(raw.get("role_type"))
        theme = _text(raw.get("theme"))
        if not name:
            errors.append("ANCHOR_NAME_MISSING")
            continue
        if not role:
            errors.append("ANCHOR_ROLE_MISSING")
            continue
        if not theme:
            errors.append("ANCHOR_THEME_MISSING")
            continue
        if theme != public.get("theme") or name != public.get("name"):
            errors.append("PUBLIC_FUPAN_ALIGNMENT_MISMATCH")
            continue
        code = public.get("code", "")
        exchange = public.get("exchange", "")
        if not code:
            errors.append("PUBLIC_FUPAN_CODE_MISSING")
            continue
        row_source = {
            "kind": ANCHOR_ROLE,
            "signal_date": signal_date,
            "run_id": source_run_id,
            "bundle_sha256": source_sha256,
            "manifest_sha256": source_manifest_sha256,
            "receipt_sha256": source_receipt_sha256,
            "path": source_paths.get("bundle", ""),
        }
        public_source = {
            "kind": "public_fupan.plate.json",
            "signal_date": signal_date,
            "run_id": public.get("public_run_id", ""),
            "manifest_sha256": public.get("public_manifest_sha256", ""),
            "plate_sha256": public.get("public_plate_sha256", ""),
            "path": public.get("path", ""),
        }
        rows.append(
            {
                "rank": len(rows) + 1,
                "market": "A",
                "symbol": f"A.{code}",
                "code": code,
                "exchange": exchange,
                "name": name,
                "stock": name,
                "role": role,
                "role_type": role,
                "theme": theme,
                "trigger": _value_from(raw, ("trigger", "upgrade_trigger", "trigger_condition", "condition")),
                "fail": _value_from(raw, ("fail", "fail_condition", "downgrade_trigger")),
                "boundary": _value_from(raw, ("boundary", "risk_boundary", "boundary_condition")),
                "cannot_confirm": _cannot_list(raw.get("cannot_confirm")),
                "video_status": video_status,
                "source_merge_role": "SOURCE_ONLY",
                "stage_selection_eligible": False,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
                "safety_flags": {
                    "production_allowed": False,
                    "buy_gate_updated": False,
                    "orders_sent": False,
                },
                "source_refs": [copy.deepcopy(row_source), copy.deepcopy(public_source)],
                "provenance": {"review_bundle": copy.deepcopy(row_source), "public_fupan": copy.deepcopy(public_source)},
            }
        )
    return rows, list(dict.fromkeys(errors))


def load_review_bundle_source(
    exact_signal_date: str,
    bundle_root: Path | str,
    shared_store_root: Path | str,
    *,
    public_fupan_loader: Callable[[Path | str, str], Any] | None = None,
) -> dict[str, Any]:
    """Load and normalize one exact ReviewBundleV1 source.

    All failures are typed in the returned DTO.  Public fupan is read only
    through the trusted shared-data reader (or an injected test loader).  No
    previous-date pointer, name dictionary, V3/V3.5 pool, or fallback source is
    consulted.
    """

    try:
        signal_date = _date8(exact_signal_date)
    except Exception as error:
        return _error_source(exact_signal_date, f"SIGNAL_DATE_INVALID:{type(error).__name__}")
    root = Path(bundle_root).absolute()
    try:
        # This is intentionally the sole deep verifier call in this module.
        bundle = review.inspect_review_bundle(signal_date, root)
        if not isinstance(bundle, Mapping):
            raise ValueError("review bundle verifier returned a non-object")
        current, paths = _current_pointer(signal_date, root)
        if _text(bundle.get("trade_date")) != signal_date:
            raise ValueError("review bundle verified date mismatch")
        if _text(bundle.get("run_id")) != current["run_id"]:
            raise ValueError("review bundle verified run_id mismatch")
        for name in SAFETY_FLAGS:
            if bundle.get(name) is not False or bundle.get("safety_flags", {}).get(name) is not False:
                raise ValueError(f"review bundle unsafe flag: {name}")

        public_rows, public_meta = _read_public_payload(shared_store_root, signal_date, public_fupan_loader)
        for row in public_rows:
            row["path"] = public_meta["plate_path"]
            row["public_run_id"] = public_meta["run_id"]
            row["public_manifest_sha256"] = public_meta["manifest_sha256"]
            row["public_plate_sha256"] = public_meta["plate_sha256"]

        video = bundle.get("video")
        video = dict(video) if isinstance(video, Mapping) else {"status": "CANNOT_CONFIRM"}
        video_status = _text(video.get("status")).upper() or "CANNOT_CONFIRM"
        rows, row_errors = _anchor_rows(
            bundle,
            public_rows=public_rows,
            signal_date=signal_date,
            source_run_id=current["run_id"],
            source_paths=paths,
            source_sha256=current["bundle_sha256"],
            source_manifest_sha256=current["manifest_sha256"],
            source_receipt_sha256=current["receipt_sha256"],
            video_status=video_status,
        )
        cannot = list(row_errors)
        if video_status != "READY":
            cannot.append("DAILY_VIDEO_NOT_LOCKED")
        status = "CANNOT_CONFIRM" if row_errors else "READY" if video_status == "READY" else "PARTIAL"
        flags = {name: False for name in SAFETY_FLAGS}
        refs = bundle.get("source_refs")
        refs = copy.deepcopy(refs) if isinstance(refs, list) else []
        provenance = {
            "source_role": ANCHOR_ROLE,
            "signal_date": signal_date,
            "run_id": current["run_id"],
            "bundle_sha256": current["bundle_sha256"],
            "manifest_sha256": current["manifest_sha256"],
            "receipt_sha256": current["receipt_sha256"],
            "public_fupan_run_id": public_meta["run_id"],
            "public_fupan_manifest_sha256": public_meta["manifest_sha256"],
            "public_fupan_plate_sha256": public_meta["plate_sha256"],
            "public_fupan_plate_path": public_meta["plate_path"],
            "paths": copy.deepcopy(paths),
            "public_fupan": {
                "run_id": public_meta["run_id"],
                "manifest_sha256": public_meta["manifest_sha256"],
                "plate_sha256": public_meta["plate_sha256"],
                "plate_path": public_meta["plate_path"],
            },
        }
        refs.append(
            {
                "kind": "public_fupan.plate.json",
                "path": public_meta["plate_path"],
                "sha256": public_meta["plate_sha256"],
                "run_id": public_meta["run_id"],
                "manifest_sha256": public_meta["manifest_sha256"],
            }
        )
        return {
            "schema": SOURCE_SCHEMA,
            "schema_version": SOURCE_SCHEMA,
            "source_role": ANCHOR_ROLE,
            "status": status,
            "signal_date": signal_date,
            "source_run_id": current["run_id"],
            "source_sha256": current["bundle_sha256"],
            "source_manifest_sha256": current["manifest_sha256"],
            "source_receipt_sha256": current["receipt_sha256"],
            "public_fupan_run_id": public_meta["run_id"],
            "public_fupan_manifest_sha256": public_meta["manifest_sha256"],
            "public_fupan_plate_sha256": public_meta["plate_sha256"],
            "public_fupan_plate_path": public_meta["plate_path"],
            "source_paths": paths,
            "rows": rows if not row_errors else [],
            "video": video,
            "video_status": video_status,
            "cannot_confirm": list(dict.fromkeys(cannot)),
            "source_refs": refs,
            "provenance": provenance,
            **flags,
            "safety_flags": flags,
        }
    except Exception as error:
        message = str(error)
        if message.startswith("PUBLIC_FUPAN_VERIFY_FAILED"):
            reason = message
        elif message.startswith("PUBLIC_FUPAN_") or "trusted public_fupan" in message:
            reason = f"PUBLIC_FUPAN_VERIFY_FAILED:{type(error).__name__}:{error}"
        else:
            reason = f"REVIEW_BUNDLE_VERIFY_FAILED:{type(error).__name__}:{error}"
        return _error_source(signal_date, reason)


__all__ = [
    "ANCHOR_ROLE",
    "D1_FUPAN_REVIEW_POOL_V1",
    "SAFETY_FLAGS",
    "SOURCE_SCHEMA",
    "load_review_bundle_source",
    "market_for_a_share_code",
    "normalize_a_share_code",
]
