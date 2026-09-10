"""Immutable shared capture of the public inputs used by the V3 close review.

The date slot is single-owner and write-once.  A normal retry reuses the
verified run without performing another network request.  ``force_verify`` is
reserved for an explicit drift audit and fails closed when the public payload
differs from the published slot.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from .hashing import canonical_bytes, sha256_json
from .paths import resolve_under, validate_date
from .store import SafeRootStore

SCHEMA_VERSION = "v3_shared_data.public_fupan_bundle.v1"
LATEST_SCHEMA_VERSION = "v3_shared_data.public_fupan_latest.v1"
OWNER = "v3_shared_public_fupan_collector"
SAFETY = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://duanxianxia.com/web/fupan",
    "Origin": "https://duanxianxia.com",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}

_REQUESTS: tuple[tuple[str, str, Mapping[str, str]], ...] = (
    ("plate", "/api/getFupanByYidong", {"type": "plate"}),
    ("lianban", "/api/getFupanByYidong", {"type": "lianban"}),
    ("qingxu", "/api/getChartByQingxu", {}),
    ("strong", "/api/getChartByStrong", {"platetype": "strong", "platelist": ""}),
    ("amount", "/api/getChartByStrong", {"platetype": "amount", "platelist": ""}),
    ("zhuli", "/api/getChartByStrong", {"platetype": "zhuli", "platelist": ""}),
)

_TRANSIENT_SSL_EOF_MARKER = "UNEXPECTED_EOF_WHILE_READING"
_TRANSIENT_RETRY_ATTEMPTS = 3
_TRANSIENT_RETRY_DELAY_SECONDS = 1.0


class PublicFupanConflict(ValueError):
    """The immutable date slot already contains different evidence."""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _default_fetcher(kind: str, request: dict[str, str]) -> bytes:
    if kind == "jiuyangongshe":
        req = urllib.request.Request(
            request["url"],
            headers={"User-Agent": _HEADERS["User-Agent"], "Accept-Language": _HEADERS["Accept-Language"]},
        )
    else:
        req = urllib.request.Request(
            "https://duanxianxia.com" + request["path"],
            data=urllib.parse.urlencode({k: v for k, v in request.items() if k != "path"}).encode(),
            headers=_HEADERS,
            method="POST",
        )
    with urllib.request.urlopen(req, timeout=40) as response:
        return response.read()


def _latest_path(root: Path) -> Path:
    return resolve_under(root, "public_fupan/latest.json")


def _load_latest(root: Path) -> dict[str, Any]:
    path = _latest_path(root)
    if not path.is_file():
        return {"schema_version": LATEST_SCHEMA_VERSION, "entries": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != LATEST_SCHEMA_VERSION or not isinstance(payload.get("entries"), dict):
        raise ValueError("public fupan latest pointer is corrupt")
    return payload


def read_public_fupan(root: Path | str, trade_date: str) -> dict[str, Any]:
    root = Path(root)
    trade_date = validate_date(trade_date)
    latest = _load_latest(root)
    entry = latest["entries"].get(trade_date)
    if not isinstance(entry, dict):
        raise ValueError(f"public fupan slot missing: {trade_date}")
    run_dir = resolve_under(root, str(entry.get("run_relative") or ""))
    manifest_path = run_dir / "manifest.json"
    receipt_path = run_dir / "receipt.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("public fupan receipt or manifest unreadable") from error
    if (
        not isinstance(manifest, dict)
        or not isinstance(receipt, dict)
        or manifest.get("schema_version") != SCHEMA_VERSION
        or receipt.get("schema_version") != SCHEMA_VERSION
        or manifest.get("trade_date") != trade_date
        or receipt.get("trade_date") != trade_date
        or receipt.get("run_id") != entry.get("run_id")
        or receipt.get("manifest_sha256") != sha256_json(manifest)
        or any(receipt.get(key) is not False for key in SAFETY)
    ):
        raise ValueError("public fupan receipt identity mismatch")
    files: dict[str, bytes] = {}
    file_meta = manifest.get("files")
    if not isinstance(file_meta, dict) or not file_meta:
        raise ValueError("public fupan manifest files missing")
    for name, meta in file_meta.items():
        if not isinstance(meta, dict):
            raise ValueError("public fupan file metadata invalid")
        path = resolve_under(root, str(meta.get("relative") or ""))
        data = path.read_bytes()
        if _sha256_bytes(data) != meta.get("sha256"):
            raise ValueError(f"public fupan file SHA mismatch: {name}")
        files[str(name)] = data
    return {"entry": entry, "manifest": manifest, "receipt": receipt, "files": files}


def _collect(trade_date: str, fetcher: Callable[[str, dict[str, str]], bytes]) -> dict[str, bytes]:
    display_date = datetime.strptime(trade_date, "%Y%m%d").strftime("%Y-%m-%d")
    files: dict[str, bytes] = {}
    for kind, path, base in _REQUESTS:
        request = {**base, "path": path}
        if kind != "qingxu":
            request["date"] = display_date
        files[f"{kind}.json"] = bytes(fetcher(kind, request))
    files["jiuyangongshe.html"] = bytes(fetcher(
        "jiuyangongshe", {"url": f"https://www.jiuyangongshe.com/action/{display_date}"}
    ))
    for name in ("plate.json", "lianban.json", "qingxu.json", "strong.json", "amount.json", "zhuli.json"):
        try:
            payload = json.loads(files[name].decode("utf-8", "replace"))
        except ValueError as error:
            raise ValueError(f"public fupan JSON invalid: {name}") from error
        has_payload = bool(payload.get("html")) or bool(payload.get("series")) or bool(payload.get("dates"))
        if payload.get("result") != "success" or not has_payload:
            raise ValueError(f"public fupan source not ready: {name}")
    return files


def _is_transient_ssl_eof(error: urllib.error.URLError) -> bool:
    reason = getattr(error, "reason", "")
    return _TRANSIENT_SSL_EOF_MARKER in str(reason) or _TRANSIENT_SSL_EOF_MARKER in str(error)


def _collect_with_retry(
    trade_date: str,
    fetcher: Callable[[str, dict[str, str]], bytes],
    *,
    sleeper: Callable[[float], None],
) -> dict[str, bytes]:
    for attempt in range(_TRANSIENT_RETRY_ATTEMPTS):
        try:
            return _collect(trade_date, fetcher)
        except urllib.error.URLError as error:
            if not _is_transient_ssl_eof(error) or attempt + 1 >= _TRANSIENT_RETRY_ATTEMPTS:
                raise
            sleeper(_TRANSIENT_RETRY_DELAY_SECONDS)
    raise AssertionError("transient public fupan retry loop exhausted unexpectedly")


def capture_public_fupan(
    root: Path | str,
    trade_date: str,
    *,
    fetcher: Callable[[str, dict[str, str]], bytes] = _default_fetcher,
    force_verify: bool = False,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    root = Path(root)
    trade_date = validate_date(trade_date)
    existing = _load_latest(root)["entries"].get(trade_date)
    if isinstance(existing, dict) and not force_verify:
        verified = read_public_fupan(root, trade_date)
        return {"ok": True, "already_exists": True, **verified["receipt"], "files": verified["manifest"]["files"]}

    files = _collect_with_retry(trade_date, fetcher, sleeper=sleeper)
    file_shas = {name: _sha256_bytes(data) for name, data in sorted(files.items())}
    idempotency_key = sha256_json({"owner": OWNER, "trade_date": trade_date, "files": file_shas})
    run_id = f"{trade_date}-public-fupan-{idempotency_key[:12]}"
    run_relative = f"public_fupan/runs/{trade_date}/{run_id}"
    run_dir = resolve_under(root, run_relative)
    store = SafeRootStore(root)
    with store._lock():
        latest = _load_latest(root)
        current = latest["entries"].get(trade_date)
        if isinstance(current, dict):
            verified = read_public_fupan(root, trade_date)
            if current.get("idempotency_key") == idempotency_key:
                return {"ok": True, "already_exists": True, **verified["receipt"], "files": verified["manifest"]["files"]}
            raise PublicFupanConflict(f"public fupan date slot changed: {trade_date}")

        run_dir.mkdir(parents=True, exist_ok=False)
        manifest_files: dict[str, dict[str, Any]] = {}
        for name, data in sorted(files.items()):
            path = run_dir / name
            store._atomic_write_bytes(path, data)
            manifest_files[name] = {
                "relative": f"{run_relative}/{name}",
                "sha256": file_shas[name],
                "size": len(data),
            }
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "trade_date": trade_date,
            "run_id": run_id,
            "idempotency_key": idempotency_key,
            "files": manifest_files,
            "source_roles": ["DUANXIANXIA_PUBLIC_FUPAN", "JIUYANGONGSHE_PUBLIC_ACTION"],
            "temporal_contract": "captured once for exact close-review date; later reruns cannot overwrite",
            **SAFETY,
        }
        store._write_json(run_dir / "manifest.json", manifest)
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "status": "READY",
            "owner": OWNER,
            "trade_date": trade_date,
            "run_id": run_id,
            "idempotency_key": idempotency_key,
            "captured_at": _now(),
            "manifest_sha256": sha256_json(manifest),
            **SAFETY,
        }
        store._write_json(run_dir / "receipt.json", receipt)
        entries = dict(latest["entries"])
        entries[trade_date] = {
            "run_id": run_id,
            "idempotency_key": idempotency_key,
            "status": "READY",
            "run_relative": run_relative,
            "updated_at": _now(),
        }
        store._write_json(_latest_path(root), {"schema_version": LATEST_SCHEMA_VERSION, "entries": entries})
    verified = read_public_fupan(root, trade_date)
    return {"ok": True, "already_exists": False, **verified["receipt"], "files": verified["manifest"]["files"]}


__all__ = [
    "PublicFupanConflict",
    "capture_public_fupan",
    "read_public_fupan",
]
