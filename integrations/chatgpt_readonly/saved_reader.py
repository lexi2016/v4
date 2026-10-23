"""Read fixed V4 artifact families without importing their write-capable stores."""
from __future__ import annotations

import hashlib
import http.client
import json
import math
import os
import re
import stat
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from . import VERSION

HK = ZoneInfo("Asia/Shanghai")
POOLS = (
    "a_d1_premarket_pool", "a_d1_fupan_watchlist_pool",
    "a_d1_stage7_fenshi_review_pool", "a_share_research_recommendation_pool",
    "a_share_baimao_research_map", "hkconnect_d1_top100",
    "wechat_public_account_v3_preselect",
)
PHASES = ("PREOPEN", "INTRADAY", "NEXT_DAY", "RETROSPECTIVE", "MANUAL")
SAFE_KEY = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
SYMBOL = re.compile(r"(?:HK\.[0-9]{5}|A\.[0-9]{6})\Z")
UNSAFE_TEXT = re.compile(
    r"(?<![:/\w])/[\w.]|file://|[A-Za-z]:[\\/]|"
    r"(?:bearer\s+|(?:api[_-]?key|password|secret|token|cookie)\s*[=:])|"
    r"sk-(?:proj-)?[A-Za-z0-9_-]{12,}", re.IGNORECASE,
)
SAFETY = {"RESEARCH_ONLY": True, "production_allowed": False,
          "buy_gate_updated": False, "orders_sent": False}


class ReadFailure(Exception):
    def __init__(self, code: str, http_status: int = 503):
        super().__init__(code)
        self.code, self.http_status = code, http_status


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def pool_digest(value: Any) -> str:
    # Pool v1 and manager v1 deliberately use different canonical-byte contracts.
    return hashlib.sha256(canonical(value)[:-1]).hexdigest()


def text(value: Any, maximum: int = 2000) -> str | None:
    if isinstance(value, str) and len(value) <= maximum and not UNSAFE_TEXT.search(value):
        return value
    return None


def stamp(value: Any) -> str | None:
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.isoformat() if parsed.tzinfo and parsed.utcoffset() is not None else None
    except (TypeError, ValueError):
        return None


def strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [safe for item in value if (safe := text(item)) is not None]


def project_stock(row: dict) -> dict:
    symbol = row.get("symbol")
    if not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol):
        raise ReadFailure("SAVED_STOCK_IDENTITY_INVALID")
    result = {"symbol": symbol, "name": text(row.get("name") or row.get("stock_name"), 128)}
    for key in ("decision", "membership_status", "review_status", "reuse_status", "recommendation_status"):
        if text(row.get(key), 128) is not None:
            result[key] = row[key]
    for key in ("reasons", "risks", "conditions", "invalidation_conditions"):
        result[key] = strings(row.get(key))
    result["summary_fields_omitted"] = any(
        isinstance(row.get(key), list) and len(result[key]) != len(row[key])
        for key in ("reasons", "risks", "conditions", "invalidation_conditions")
    )
    return result


@dataclass(frozen=True)
class Bindings:
    # These are operator bindings, never HTTP parameters. No directory is created.
    pool_root: Path
    workbench_root: Path  # WorkbenchStore.root, including its manager_workbench suffix.


class SavedFiles:
    def __init__(self, root: Path, deadline: float, evidence: list[dict]):
        self.root, self.deadline, self.evidence = root, deadline, evidence

    def read(self, relative: str, maximum: int = 64 * 1024 * 1024) -> tuple[dict, bytes]:
        if time.monotonic() > self.deadline:
            raise ReadFailure("READ_TIMEOUT", 504)
        parts = Path(relative).parts
        if (not self.root.is_absolute() or ".." in self.root.parts or not parts
                or relative.startswith("/") or any(p in {".", ".."} for p in parts)):
            raise ReadFailure("SAVED_PATH_INVALID")
        descriptors = []
        try:
            fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            descriptors.append(fd)
            for part in (*self.root.parts[1:], *parts[:-1]):
                fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                descriptors.append(fd)
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=fd)
            descriptors.append(fd)
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
                raise ReadFailure("SAVED_FILE_UNSAFE_OR_TOO_LARGE")
            chunks, size = [], 0
            while True:
                if time.monotonic() > self.deadline:
                    raise ReadFailure("READ_TIMEOUT", 504)
                chunk = os.read(fd, min(1024 * 1024, maximum + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > maximum:
                    raise ReadFailure("SAVED_FILE_UNSAFE_OR_TOO_LARGE")
            after = os.fstat(fd)
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ReadFailure("SAVED_FILE_CHANGED_DURING_READ")
            raw = b"".join(chunks)
            obj = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(obj, dict):
                raise ValueError()
            self.evidence.append({"relative": relative, "sha256": hashlib.sha256(raw).hexdigest(),
                                  "bytes": len(raw)})
            return obj, raw
        except FileNotFoundError:
            raise ReadFailure("SAVED_DATA_NOT_FOUND", 404) from None
        except (OSError, ValueError, UnicodeError, RecursionError):
            raise ReadFailure("SAVED_DATA_UNREADABLE") from None
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)

    def absent(self, relative: str) -> None:
        try:
            self.read(relative, 128 * 1024)
        except ReadFailure as exc:
            if exc.http_status == 404:
                return
            raise
        raise ReadFailure("PENDING_COMMIT_REQUIRES_EXISTING_OWNER")


def v4_available() -> bool:
    """Only the audited health endpoint; no proxy environment or redirect handling."""
    connection = http.client.HTTPConnection("127.0.0.1", 8873, timeout=2)
    try:
        connection.request("GET", "/healthz")
        response = connection.getresponse()
        return response.status == 200 and json.loads(response.read(1025)) == {"status": "ok"}
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        connection.close()


class SavedReader:
    def __init__(self, bindings: Bindings, *, available: Callable[[], bool] = v4_available,
                 now: Callable[[], datetime] | None = None, timeout: float = 8):
        if not 0 < timeout <= 15:
            raise ValueError("READ_TIMEOUT_INVALID")
        self.bindings, self.available, self.timeout = bindings, available, timeout
        self.now = now or (lambda: datetime.now(HK))

    def read(self, kind: str, params: dict) -> dict:
        started = time.monotonic()
        if not self.available():
            raise ReadFailure("V4_UNAVAILABLE")
        evidence: list[dict] = []
        deadline = started + self.timeout
        root = self.bindings.pool_root if kind == "pools" else self.bindings.workbench_root
        files = SavedFiles(root, deadline, evidence)
        if kind == "pools":
            payload, rows, source = self._pool(files, params)
            as_of = stamp(payload.get("as_of"))
        elif kind in {"research", "reviews"}:
            payload, source = self._plan(files, params)
            as_of = stamp(payload.get("available_at"))
            rows = [row for row in payload["stocks"] if row.get("symbol") == params["code"]] if kind == "research" else []
            rows = [project_stock(row) for row in rows]
            if kind == "research" and not rows:
                raise ReadFailure("STOCK_NOT_IN_SAVED_PLAN", 404)
            if kind == "reviews":
                run_id = payload["run_id"]
                review, raw = files.read(f"reviews/{params['trade_date']}/{run_id}.json")
                if review.get("target_date") != params["trade_date"] or review.get("plan_run_id") != run_id:
                    raise ReadFailure("REVIEW_IDENTITY_MISMATCH")
                denominator = review.get("selected_denominator")
                rows = [{"mode": text(review.get("mode"), 128),
                         "ranking_date": text(review.get("ranking_date"), 8),
                         "selected_denominator": denominator if type(denominator) is int and denominator >= 0 else None,
                         "uncovered_reasons": strings(review.get("uncovered_reasons")),
                         "gaps": strings(review.get("gaps")),
                         "scope": "SAVED_MANAGER_PLAN_REVIEW_SUMMARY_ONLY"}]
                source.append({"kind": "SAVED_MANAGER_REVIEW", "artifact_sha256": hashlib.sha256(raw).hexdigest()})
                payload, as_of = review, None
        elif kind == "announcements":
            payload, rows, source = self._announcements(files, params)
            as_of = None  # Delivery files have no authoritative saved-at timestamp.
        else:
            raise ReadFailure("ROUTE_NOT_ALLOWED", 404)
        total = len(rows)
        offset, limit = params.get("offset", 0), params.get("limit", 20)
        returned = rows[offset:offset + limit]
        raw_status = payload.get("status", payload.get("state", "UNKNOWN"))
        reasons = []
        known = raw_status in {"READY", "AVAILABLE", "MATERIALIZED", "SUCCEEDED"} or (
            isinstance(raw_status, str) and raw_status.endswith("_READY"))
        if payload.get("gaps") or not known:
            reasons.append("SOURCE_NOT_FULLY_CONFIRMED")
        if payload.get("cannot_confirm"):
            reasons.append("SOURCE_HAS_UNRESOLVED_EVIDENCE")
        if as_of is None:
            reasons.append("SOURCE_AS_OF_NOT_RECORDED")
        if kind == "announcements":
            reasons.append("SAVED_DELIVERY_ONLY_MEMBERSHIP_AND_SEMANTICS_NOT_REEVALUATED")
        status = "unknown" if reasons else (
            "stale" if self.now() - datetime.fromisoformat(as_of) > timedelta(hours=24) else "valid")
        if as_of and datetime.fromisoformat(as_of) > self.now() + timedelta(minutes=5):
            status = "unknown"
            reasons.append("SOURCE_TIMESTAMP_IN_FUTURE")
        if time.monotonic() > deadline:
            raise ReadFailure("READ_TIMEOUT", 504)
        return {"trade_date": params["trade_date"], "as_of": as_of,
                "observed_at": self.now().isoformat(), "status": status,
                "source_status": text(raw_status, 128), "missing_reasons": reasons,
                "version": {"gateway": VERSION, "source_schema": text(payload.get("schema_version") or payload.get("schema"), 128),
                            "rules": text(payload.get("context", {}).get("rules_version"), 128)},
                "source": source, "market": params["market"], "rows": returned,
                "coverage": {"scope": params.get("pool_id", kind), "total": total, "returned": len(returned),
                             "offset": offset, "limit": limit,
                             "next_offset": offset + len(returned) if offset + len(returned) < total else None,
                             "dataset_complete_in_response": offset == 0 and len(returned) == total},
                **SAFETY}

    def _pool(self, files: SavedFiles, p: dict) -> tuple[dict, list, list]:
        day, pool = p["trade_date"], p["pool_id"]
        if pool not in POOLS or p["market"] != ("HK" if pool == "hkconnect_d1_top100" else "A"):
            raise ReadFailure("POOL_MARKET_MISMATCH", 422)
        pending = f"preselection_pending_commits/{day}/{pool}.json"
        files.absent(pending)
        base = f"preselection_pools/{day}"
        manifest, manifest_raw = files.read(f"{base}/manifest.json", 128 * 1024)
        payload, raw = files.read(f"{base}/{pool}.json")
        receipt, receipt_raw = files.read(f"{base}/receipts/{pool}.json", 128 * 1024)
        sha = pool_digest(payload)
        expected = {"schema_version": "v3_5.preselection_pool_receipt.v1", "trade_date": day,
                    "pool_id": pool, "artifact_path": f"{base}/{pool}.json", "artifact_sha256": sha,
                    "source_sha256": payload.get("source_sha256"), "source_role": payload.get("source_role")}
        for key in ("source_row_count", "source_run_id"):
            if key in payload:
                expected[key] = payload[key]
        if (manifest.get(pool) != sha or receipt != expected or not SHA.fullmatch(str(payload.get("source_sha256", "")))
                or payload.get("schema_version") != "v3_5.preselection_pool.v1"
                or payload.get("trade_date") != day or payload.get("pool_id") != pool
                or payload.get("market") != p["market"]
                or payload.get("target_date", day) != day or not isinstance(payload.get("rows"), list)):
            raise ReadFailure("POOL_IDENTITY_OR_HASH_MISMATCH")
        rows = []
        for row in payload["rows"]:
            if not isinstance(row, dict) or row.get("target_date", day) != day:
                raise ReadFailure("POOL_ROW_IDENTITY_MISMATCH")
            projected = project_stock(row)
            if not projected["symbol"].startswith("HK." if p["market"] == "HK" else "A."):
                raise ReadFailure("POOL_ROW_MARKET_MISMATCH")
            projected["code"] = projected["symbol"].split(".")[1]
            for key in ("pool_rank", "pool_score", "pct_chg"):
                value = row.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                    projected[key] = value
            rows.append(projected)
        if len({r["symbol"] for r in rows}) != len(rows):
            raise ReadFailure("POOL_DUPLICATE_STOCK")
        if files.read(f"{base}/manifest.json", 128 * 1024)[1] != manifest_raw:
            raise ReadFailure("POOL_CHANGED_DURING_READ")
        files.absent(pending)
        return payload, rows, [{"kind": "SAVED_PRESELECTION_POOL", "pool_id": pool,
                               "source_role": text(payload.get("source_role"), 128),
                               "source_sha256": payload["source_sha256"],
                               "run_id": text(payload.get("source_run_id"), 128),
                               "artifact_sha256": hashlib.sha256(raw).hexdigest(),
                               "semantic_sha256": sha, "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
                               "receipt_sha256": hashlib.sha256(receipt_raw).hexdigest()}]

    def _plan(self, files: SavedFiles, p: dict) -> tuple[dict, list]:
        day, phase = p["trade_date"], p["phase"]
        if phase not in PHASES or p["market"] != "HK":
            raise ReadFailure("PLAN_SCOPE_INVALID", 422)
        pointer_path = f"pointers/{day}/{phase}.json"
        pointer, pointer_raw = files.read(pointer_path, 8192)
        run = pointer.get("run_id")
        if not isinstance(run, str) or not SAFE_KEY.fullmatch(run):
            raise ReadFailure("PLAN_POINTER_INVALID")
        payload, raw = files.read(f"snapshots/{run}.json")
        body = {k: v for k, v in payload.items() if k != "product_sha256"}
        expected = digest(body)
        context = payload.get("context", {})
        if (payload.get("schema_version") != "v4.manager_workbench.v1" or payload.get("run_id") != run
                or context.get("target_date") != day or context.get("phase") != phase
                or expected != pointer.get("product_sha256") or expected != payload.get("product_sha256")
                or not isinstance(payload.get("stocks"), list)):
            raise ReadFailure("PLAN_IDENTITY_OR_HASH_MISMATCH")
        if files.read(pointer_path, 8192)[1] != pointer_raw:
            raise ReadFailure("PLAN_CHANGED_DURING_READ")
        return payload, [{"kind": "SAVED_MANAGER_PLAN", "run_id": run,
                          "artifact_sha256": hashlib.sha256(raw).hexdigest(), "product_sha256": expected,
                          "pointer_sha256": hashlib.sha256(pointer_raw).hexdigest()}]

    def _announcements(self, files: SavedFiles, p: dict) -> tuple[dict, list, list]:
        if p["market"] != "HK":
            raise ReadFailure("ANNOUNCEMENT_MARKET_INVALID", 422)
        index_path = "cursors/announcement_flash_delivery_index.json"
        index, index_raw = files.read(index_path, 128 * 1024)
        matching = [v for v in index.get("items", []) if isinstance(v, dict) and v.get("target_date") == p["trade_date"]]
        if not matching:
            raise ReadFailure("SAVED_DELIVERY_NOT_FOUND", 404)
        job = matching[-1].get("job_id")
        if not isinstance(job, str) or not re.fullmatch(r"[0-9a-f]{32}", job):
            raise ReadFailure("DELIVERY_INDEX_INVALID")
        base = f"announcement_flash/jobs/{job}/deliveries"
        binding, binding_raw = files.read(f"{base}/latest.json", 8192)
        sha = binding.get("sha256")
        schema = "v4.manager_workbench.announcement_delivery.v1"
        if (not isinstance(sha, str) or not SHA.fullmatch(sha) or binding.get("schema") != schema
                or binding.get("job_id") != job or binding.get("artifact_ref") != f"{base}/{sha}.json"):
            raise ReadFailure("DELIVERY_BINDING_INVALID")
        payload, raw = files.read(f"{base}/{sha}.json")
        if (hashlib.sha256(raw).hexdigest() != sha or payload.get("schema") != schema
                or payload.get("job_id") != job or payload.get("target_trade_date") != p["trade_date"]
                or not isinstance(payload.get("stocks"), list)):
            raise ReadFailure("DELIVERY_IDENTITY_OR_HASH_MISMATCH")
        rows = []
        for row in payload["stocks"]:
            projected = project_stock(row)
            if not projected["symbol"].startswith("HK."):
                raise ReadFailure("DELIVERY_MARKET_MISMATCH")
            articles = []
            for item in row.get("articles", []):
                articles.append({k: text(item.get(k)) for k in
                                 ("article_id", "title", "source_date", "publication_date", "source_sha256",
                                  "body_sha256", "review_status", "state", "direction", "reason")})
            projected["articles"] = articles
            rows.append(projected)
        if (files.read(index_path, 128 * 1024)[1] != index_raw
                or files.read(f"{base}/latest.json", 8192)[1] != binding_raw):
            raise ReadFailure("DELIVERY_CHANGED_DURING_READ")
        return payload, rows, [{"kind": "SAVED_ANNOUNCEMENT_DELIVERY", "job_id": job,
                               "artifact_sha256": sha, "index_sha256": hashlib.sha256(index_raw).hexdigest(),
                               "binding_sha256": hashlib.sha256(binding_raw).hexdigest()}]
