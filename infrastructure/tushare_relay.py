"""Bounded, research-only access to a configured third-party Tushare relay.

The installed SDK uses POST <base>/<api_name> with ts_type_name in params.
This wire-compatible implementation exists to enforce streaming limits, avoid
redirecting credentials, and retain the distinction between provider failures.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests


API_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,79}$")
FLAGS = {"RESEARCH_ONLY": True, "production_allowed": False,
         "buy_gate_updated": False, "orders_sent": False}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def endpoint(value: str) -> str:
    u = urlsplit(value)
    if (u.scheme != "https" or not u.hostname or u.username or u.password
            or u.query or u.fragment or not u.path.startswith("/")
            or u.path.endswith("/") or ".." in u.path.split("/")):
        raise ValueError("relay endpoint must be an HTTPS URL without credentials, query or fragment")
    return value


@dataclass(frozen=True)
class RelayConfig:
    token: str = field(repr=False)
    primary: str
    fallback: str | None = None

    @classmethod
    def from_file(cls, path: Path) -> "RelayConfig":
        # Do not follow symlinks or print the file/values in failures.
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, "r", encoding="utf-8") as fh:
            mode = os.fstat(fh.fileno()).st_mode
            if not stat.S_ISREG(mode) or stat.S_IMODE(mode) & 0o077:
                raise ValueError("credential file must be a private regular file")
            lines = fh.read(16385)
        if len(lines) > 16384:
            raise ValueError("credential file too large")
        values = {}
        for line in lines.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if "=" not in line:
                raise ValueError("malformed configuration")
            key, value = line.split("=", 1)
            if key not in {"TUSHARE_TOKEN", "TUSHARE_HTTP_URL", "TUSHARE_FALLBACK_HTTP_URL"} or key in values:
                raise ValueError("unexpected or duplicate configuration key")
            values[key] = value.strip().strip("\"'")
        token = values.get("TUSHARE_TOKEN", "")
        if not token or len(token) > 1024 or "\n" in token:
            raise ValueError("missing or invalid token")
        primary = endpoint(values.get("TUSHARE_HTTP_URL", ""))
        fallback = values.get("TUSHARE_FALLBACK_HTTP_URL")
        if token in primary or (fallback and token in fallback):
            raise ValueError("credential must not be embedded in an endpoint URL")
        return cls(token, primary, endpoint(fallback) if fallback else None)


def _redact(value: Any, token: str) -> Any:
    if isinstance(value, str):
        return value.replace(token, "[REDACTED]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {str(k).replace(token, "[REDACTED]"): _redact(v, token) for k, v in value.items()}
    return value


def _classify_provider(message: str) -> str:
    text = message.lower()
    if any(x in text for x in ("频次", "频率", "限流", "rate limit", "too many")):
        return "RATE_LIMITED"
    if any(x in text for x in ("权限", "积分", "permission", "access denied", "not authorized", "无权")):
        return "ACCESS_DENIED"
    if any(x in text for x in ("参数", "parameter", "invalid argument", "必填")):
        return "PARAMETER_OR_PROVIDER_ERROR"
    return "PROVIDER_ERROR"


def query(config: RelayConfig, api: str, params: dict[str, Any], *,
          fields: str = "", timeout: float = 20, max_bytes: int = 524288,
          allow_fallback: bool = False, session: Any = requests) -> dict[str, Any]:
    """One primary POST; explicit fallback only after connection/timeout errors.

    Provider messages and exception strings are never returned. No redirects
    are followed; the body is streamed with a strict decoded-byte bound.
    """
    if not API_RE.fullmatch(api):
        raise ValueError("invalid api name")
    if timeout <= 0 or timeout > 60 or max_bytes < 1024 or max_bytes > 2_097_152:
        raise ValueError("invalid network bounds")
    if not isinstance(params, dict) or not all(API_RE.fullmatch(k) for k in params):
        raise ValueError("invalid parameter keys")
    attempts = [config.primary]
    if allow_fallback and config.fallback and config.fallback != config.primary:
        attempts.append(config.fallback)
    for i, url in enumerate(attempts):
        payload = {"api_name": api, "token": config.token,
                   "params": {**params, "ts_type_name": url}, "fields": fields}
        try:
            with session.post(url + "/" + api, json=payload, timeout=(min(10, timeout), timeout),
                              allow_redirects=False, stream=True) as response:
                status = response.status_code
                result = {"endpoint": url, "endpoint_role": "primary" if i == 0 else "fallback",
                          "http_status": status}
                if 300 <= status < 400:
                    return {**result, "status": "REDIRECT_REJECTED"}
                if status != 200:
                    return {**result, "status": "HTTP_ERROR"}
                chunks = bytearray()
                for chunk in response.iter_content(chunk_size=16384):
                    chunks.extend(chunk)
                    if len(chunks) > max_bytes:
                        return {**result, "status": "RESPONSE_TOO_LARGE"}
                try:
                    obj = json.loads(chunks.decode("utf-8"),
                                     parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                except (ValueError, UnicodeDecodeError):
                    return {**result, "status": "MALFORMED_RESPONSE"}
                if not isinstance(obj, dict) or not isinstance(obj.get("code"), int):
                    return {**result, "status": "MALFORMED_RESPONSE"}
                code = obj["code"]
                if code != 0:
                    return {**result, "status": _classify_provider(str(obj.get("msg", ""))),
                            "provider_code": code}
                data = obj.get("data")
                if not isinstance(data, dict):
                    return {**result, "provider_code": code, "status": "MALFORMED_RESPONSE"}
                columns, rows = data.get("fields"), data.get("items")
                if (not isinstance(columns, list) or not all(isinstance(c, str) for c in columns)
                        or len(columns) != len(set(columns)) or not isinstance(rows, list)
                        or not all(isinstance(row, list) and len(row) == len(columns) for row in rows)):
                    return {**result, "provider_code": code, "status": "MALFORMED_RESPONSE"}
                # Avoid storing any reflected secret, even inside a data cell.
                data = _redact({"fields": columns, "items": rows}, config.token)
                return {**result, "provider_code": code,
                        "status": "SUCCESS_RESPONSE" if rows else "EMPTY_RESPONSE",
                        "row_count": len(rows), "data": data}
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            if i + 1 < len(attempts):
                continue
            return {"endpoint": url, "endpoint_role": "primary" if i == 0 else "fallback",
                    "status": "TRANSPORT_ERROR"}
        except requests.exceptions.RequestException:
            return {"endpoint": url, "endpoint_role": "primary" if i == 0 else "fallback",
                    "status": "TRANSPORT_ERROR"}
    raise AssertionError("unreachable")


def read_isolated_sample(root: Path, api: str) -> dict[str, Any]:
    """Verify and return one isolated sample for a future V4 owner to assess.

    This reader verifies byte and declared identity, not financial correctness,
    point-in-time eligibility, pool membership, or admission to a product.
    """
    if not API_RE.fullmatch(api):
        raise ValueError("invalid api name")
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_bytes())
    if manifest.get("schema") != "tushare_isolated_manifest.v1" or any(manifest.get(k) is not v for k, v in FLAGS.items()):
        raise ValueError("invalid isolated manifest")
    for name, key in (("official_catalog.json", "catalog_sha256"), ("capability_report.json", "report_sha256")):
        path = root / name
        if path.is_symlink() or sha256(path.read_bytes()) != manifest.get(key):
            raise ValueError("manifest input identity mismatch")
    entry = manifest.get("samples", {}).get(api)
    if not isinstance(entry, dict) or entry.get("path") != "sample_" + api + ".json":
        raise ValueError("sample not present in manifest")
    sample_path = root / entry["path"]
    if sample_path.is_symlink():
        raise ValueError("sample cannot be a symlink")
    raw = sample_path.read_bytes()
    if sha256(raw) != entry.get("sha256"):
        raise ValueError("sample identity mismatch")
    sample = json.loads(raw)
    if (sample.get("schema") != "tushare_isolated_sample.v1" or sample.get("api") != api
            or sample.get("run_id") != entry.get("run_id") or sample.get("market") != entry.get("market")
            or sample.get("source_date") != entry.get("source_date")
            or sample.get("source_kind") != "THIRD_PARTY_RELAY" or sample.get("pit_status") != "CANNOT_CONFIRM"
            or any(sample.get(k) is not v for k, v in FLAGS.items())):
        raise ValueError("sample provenance mismatch")
    return sample
