"""Verified A-share selector security registry for shared, read-only consumers.

The registry is deliberately a small adapter around the V3 selector panel
contract.  It does not score or select securities: it only snapshots the
``trade_date == signal_date`` rows whose ``ts_code`` and ``name`` satisfy the
same filtering and first-seen name mapping used by V3's research pool.
"""
from __future__ import annotations

import csv
import json
import os
import re
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

from .hashing import canonical_bytes, sha256_file, sha256_json
from .paths import resolve_under, validate_date
from .store import StoreError


SCHEMA_VERSION = "v3_shared_data.a_share_security_master.v1"
MANIFEST_SCHEMA_VERSION = "v3_shared_data.a_share_security_master_manifest.v1"
RECEIPT_SCHEMA_VERSION = "v3_shared_data.a_share_security_master_receipt.v1"
LATEST_SCHEMA_VERSION = "v3_shared_data.a_share_security_master_latest.v1"
_FIELDS = ("ts_code", "code", "name", "market", "signal_date")
_CODE_RE = re.compile(r"^(\d{6})\.(SH|SZ|BJ)$")
_SAFETY = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _date_text(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    text = str(value or "").strip()
    if re.fullmatch(r"\d{8}", text):
        return text
    match = re.fullmatch(r"(\d{4})[-/]?(\d{2})[-/]?(\d{2})(?:[T ]|$).*", text)
    return "".join(match.groups()[:3]) if match else ""


def _selector_rows(selector_path: Path | str, signal_date: str) -> list[dict[str, str]]:
    """Read the exact selector date and apply V3 code/name semantics."""
    signal_date = validate_date(signal_date)
    selector_path = Path(selector_path)
    if not selector_path.is_file() or selector_path.is_symlink():
        raise StoreError("selector parquet must be an existing regular file")
    try:
        import pyarrow.parquet as pq

        parquet = pq.ParquetFile(selector_path)
        required = {"trade_date", "ts_code", "name"}
        missing = sorted(required - set(parquet.schema.names))
        if missing:
            raise StoreError(f"selector parquet columns missing: {','.join(missing)}")
        table = pq.read_table(selector_path, columns=["trade_date", "ts_code", "name"])
    except StoreError:
        raise
    except (ImportError, OSError, ValueError, TypeError) as error:
        raise StoreError(f"selector parquet unreadable: {error}") from error

    code_rows: dict[str, dict[str, str]] = {}
    names: dict[str, str] = {}
    dates_seen: set[str] = set()
    for raw_date, raw_ts_code, raw_name in zip(
        table.column("trade_date").to_pylist(),
        table.column("ts_code").to_pylist(),
        table.column("name").to_pylist(),
    ):
        row_date = _date_text(raw_date)
        if row_date:
            dates_seen.add(row_date)
        if row_date != signal_date:
            continue
        ts_code = str(raw_ts_code or "").strip().upper()
        match = _CODE_RE.fullmatch(ts_code)
        name = str(raw_name or "").strip()
        if not match or not name or len(name) < 2:
            continue
        code, market = match.groups()
        # V3 uses a set for code membership and setdefault for first-seen names.
        # Retain the first valid name for a code while preserving the input order
        # for duplicate display names.
        code_rows.setdefault(
            code,
            {
                "ts_code": ts_code,
                "code": code,
                "name": name,
                "market": market,
                "signal_date": signal_date,
            },
        )
        names.setdefault(name, code)
    if signal_date not in dates_seen:
        raise StoreError(f"selector parquet has no exact selector date: {signal_date}")
    # Keep first-seen code order.  This is intentional: V3's name mapping uses
    # ``setdefault`` while scanning the panel, so a duplicate display name must
    # resolve to the first valid code in panel order.
    rows = list(code_rows.values())
    if not rows:
        raise StoreError(f"selector parquet exact selector date is empty: {signal_date}")
    return rows


def _asset_root(store_root: Path | str) -> Path:
    return Path(store_root) / "assets" / "a_share_security_master"


def _latest_path(store_root: Path | str) -> Path:
    return _asset_root(store_root) / "latest.json"


def _entry_for_date(latest_path: Path, signal_date: str) -> dict[str, Any] | None:
    if not latest_path.is_file():
        return None
    try:
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise StoreError(f"A-share security-master latest invalid: {error}") from error
    if latest.get("schema_version") != LATEST_SCHEMA_VERSION or not isinstance(latest.get("entries"), dict):
        raise StoreError("A-share security-master latest schema invalid")
    entry = latest["entries"].get(signal_date)
    if entry is not None and not isinstance(entry, dict):
        raise StoreError("A-share security-master latest entry invalid")
    return entry


def publish_a_share_security_master(
    store_root: Path | str,
    *,
    signal_date: str,
    selector_path: Path | str,
) -> dict[str, Any]:
    """Publish one immutable exact-date selector registry.

    A date already present in ``latest.json`` can only be reused when the
    computed input/run identity is identical.  A different input is a hard
    conflict; the existing verified publication is never overwritten.
    """
    signal_date = validate_date(signal_date)
    selector_path = Path(selector_path)
    rows = _selector_rows(selector_path, signal_date)
    selector_sha256 = sha256_file(selector_path)
    codes = [row["code"] for row in rows]
    name_to_code: dict[str, str] = {}
    for row in rows:
        name_to_code.setdefault(row["name"], row["code"])
    run_id = sha256_json({
        "signal_date": signal_date,
        "selector_sha256": selector_sha256,
        "rows": rows,
        "name_to_code": name_to_code,
    })[:24]
    asset_root = _asset_root(store_root)
    latest_path = asset_root / "latest.json"
    existing = _entry_for_date(latest_path, signal_date)
    if existing is not None:
        if existing.get("run_id") != run_id:
            raise StoreError(f"A-share security-master conflict for {signal_date}")
        # Reusing requires a complete, untampered existing publication.
        _, manifest = load_verified_a_share_security_master(store_root, signal_date)
        if manifest.get("run_id") != run_id or manifest.get("selector_sha256") != selector_sha256:
            raise StoreError("A-share security-master existing publication identity mismatch")
        return {
            "status": "READY",
            "reused": True,
            "signal_date": signal_date,
            "run_id": run_id,
            "row_count": len(rows),
            **_SAFETY,
        }

    relative_root = f"runs/{signal_date}/{run_id}"
    run_root = asset_root / "runs" / signal_date / run_id
    artifact = run_root / "artifact.csv"
    if run_root.exists():
        raise StoreError("A-share security-master run directory conflicts")
    run_root.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".artifact.", suffix=".tmp", dir=run_root)
    try:
        with os.fdopen(handle, "w", encoding="utf-8-sig", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, artifact)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "signal_date": signal_date,
        "trade_date": signal_date,
        "run_id": run_id,
        "selector_sha256": selector_sha256,
        "row_count": len(rows),
        "code_count": len(codes),
        "name_count": len(name_to_code),
        "codes_sha256": sha256_json(codes),
        "name_to_code_sha256": sha256_json(name_to_code),
        "name_to_code": name_to_code,
        "selector_semantics": "V3_A_SHARE_PANEL_CODE_SET_AND_FIRST_SEEN_NAME_MAP",
        "source_kind": "EXPLICIT_SELECTOR_PARQUET",
        "research_only": True,
        "artifact_relative": f"{relative_root}/artifact.csv",
        "artifact_sha256": sha256_file(artifact),
        **_SAFETY,
    }
    _atomic_write(run_root / "manifest.json", canonical_bytes(manifest))
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": "READY",
        "signal_date": signal_date,
        "trade_date": signal_date,
        "run_id": run_id,
        "row_count": len(rows),
        "artifact_sha256": manifest["artifact_sha256"],
        "manifest_sha256": sha256_json(manifest),
        "research_only": True,
        **_SAFETY,
    }
    _atomic_write(run_root / "receipt.json", canonical_bytes(receipt))
    latest = {"schema_version": LATEST_SCHEMA_VERSION, "entries": {}}
    if latest_path.is_file():
        try:
            loaded = json.loads(latest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise StoreError(f"A-share security-master latest invalid: {error}") from error
        if loaded.get("schema_version") != LATEST_SCHEMA_VERSION or not isinstance(loaded.get("entries"), dict):
            raise StoreError("A-share security-master latest schema invalid")
        latest = loaded
    latest["entries"][signal_date] = {
        "run_id": run_id,
        "manifest_relative": f"{relative_root}/manifest.json",
        "receipt_relative": f"{relative_root}/receipt.json",
    }
    _atomic_write(latest_path, canonical_bytes(latest))
    return {
        **receipt,
        "reused": False,
        "row_count": len(rows),
        "manifest": manifest,
    }


def load_verified_a_share_security_master(
    store_root: Path | str, signal_date: str
) -> tuple[dict[str, dict[str, str]], dict[str, Any]]:
    """Load and verify the immutable registry, failing closed on any mismatch."""
    signal_date = validate_date(signal_date)
    asset_root = _asset_root(store_root)
    latest_path = asset_root / "latest.json"
    try:
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        if latest.get("schema_version") != LATEST_SCHEMA_VERSION:
            raise StoreError("A-share security-master latest schema mismatch")
        entry = latest["entries"][signal_date]
        manifest_path = resolve_under(asset_root, str(entry["manifest_relative"]))
        receipt_path = resolve_under(asset_root, str(entry["receipt_relative"]))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        artifact = resolve_under(asset_root, str(manifest["artifact_relative"]))
    except StoreError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise StoreError(f"A-share security-master metadata invalid: {error}") from error
    if (
        manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION
        or receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION
        or receipt.get("status") != "READY"
        or manifest.get("signal_date") != signal_date
        or manifest.get("trade_date") != signal_date
        or receipt.get("signal_date") != signal_date
        or receipt.get("trade_date") != signal_date
        or manifest.get("run_id") != entry.get("run_id")
        or receipt.get("run_id") != entry.get("run_id")
        or receipt.get("row_count") != manifest.get("row_count")
        or manifest.get("research_only") is not True
        or receipt.get("research_only") is not True
        or any(manifest.get(key) is not False or receipt.get(key) is not False for key in _SAFETY)
    ):
        raise StoreError("A-share security-master identity or safety contract invalid")
    if sha256_file(artifact) != manifest.get("artifact_sha256") or receipt.get("artifact_sha256") != manifest.get("artifact_sha256"):
        raise StoreError("A-share security-master artifact checksum mismatch")
    if sha256_json(manifest) != receipt.get("manifest_sha256"):
        raise StoreError("A-share security-master manifest checksum mismatch")
    rows: dict[str, dict[str, str]] = {}
    try:
        with artifact.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != _FIELDS:
                raise StoreError("A-share security-master artifact columns invalid")
            for row in reader:
                ts_code = str(row.get("ts_code") or "").strip().upper()
                match = _CODE_RE.fullmatch(ts_code)
                code = str(row.get("code") or "").strip()
                name = str(row.get("name") or "").strip()
                if (
                    not match
                    or match.group(1) != code
                    or row.get("market") != match.group(2)
                    or row.get("signal_date") != signal_date
                    or not name
                    or len(name) < 2
                ):
                    raise StoreError("A-share security-master artifact row invalid")
                if code in rows:
                    raise StoreError("A-share security-master artifact duplicate code")
                rows[code] = dict(row)
    except StoreError:
        raise
    except (OSError, UnicodeDecodeError, csv.Error) as error:
        raise StoreError(f"A-share security-master artifact unreadable: {error}") from error
    if len(rows) != int(manifest.get("row_count") or -1) or len(rows) != int(manifest.get("code_count") or -1):
        raise StoreError("A-share security-master row count mismatch")
    if sha256_json(list(rows)) != manifest.get("codes_sha256"):
        raise StoreError("A-share security-master code set checksum mismatch")
    name_to_code: dict[str, str] = {}
    for row in rows.values():
        name_to_code.setdefault(row["name"], row["code"])
    if (
        len(name_to_code) != int(manifest.get("name_count") or -1)
        or sha256_json(name_to_code) != manifest.get("name_to_code_sha256")
        or manifest.get("name_to_code") != name_to_code
    ):
        raise StoreError("A-share security-master name map checksum mismatch")
    return rows, manifest


__all__ = [
    "load_verified_a_share_security_master",
    "publish_a_share_security_master",
]


DISPLAY_SCHEMA = "v3_shared_data.a_share_display_names.v1"


class DisplayNameObservationMissing(StoreError):
    """Only an absent exact date permits bounded display fallback."""



def _display_security_page(api: Any, market: int, offset: int) -> dict[str, Any]:
    """Use the SDK wire request, quarantining only undecodable name records.

    HQ names are fixed-width GBK; an unrelated truncated fund name must not
    discard a thousand valid rows. Never repair or ignore bytes in a name.
    """
    import base64
    import struct
    from pytdx.parser.get_security_list import GetSecurityList

    class DisplaySecurityList(GetSecurityList):
        def parseResponse(self, body_buf):
            count, = struct.unpack("<H", body_buf[:2])
            if len(body_buf) != 2 + 29 * count:
                raise StoreError("HQ security-list body length mismatch")
            rows, quarantined = [], []
            for index in range(count):
                code, _, raw_name, _, _, _, _ = struct.unpack("<6sH8s4sBI4s", body_buf[2 + index * 29:2 + (index + 1) * 29])
                code = code.decode("ascii")
                try:
                    name = raw_name.rstrip(b"\x00").decode("gbk", errors="strict")
                except UnicodeDecodeError as error:
                    quarantined.append(dict(code=code, raw_name_hex=raw_name.hex(), error=str(error)))
                    continue
                rows.append(dict(code=code, name=name))
            return dict(rows=rows, raw_body_base64=base64.b64encode(body_buf).decode("ascii"), quarantined=quarantined)

    if not getattr(api, "client", None):
        return {"rows": api.get_security_list(market, offset), "quarantined": []}
    command = DisplaySecurityList(api.client, lock=api.lock)
    command.setParams(market, offset)
    return command.call_api()


def acquire_current_display_names(evidence_root: Path | str, *, observation_date: str,
                                  requested_codes: list[str], api: Any = None,
                                  official_rows: list[dict[str, Any]] | None = None,
                                  cache_only: bool = False, cached_page_pins: Mapping[str,str] | None = None,
                                  output_path: Path | str | None = None) -> dict[str, Any]:
    """Capture HQ security lists for display only, reusing the established host registry.

    This does not certify a selector, historical membership, quotes or PIT. Successful
    pages are immutable cache entries; subsequent calls do not request them again.
    """
    from datetime import timezone
    observation_date = validate_date(observation_date)
    root = Path(evidence_root)
    if cache_only:
        if not root.is_dir() or not cached_page_pins:raise StoreError("cache-only requires existing pinned evidence pages")
        for path,digest in cached_page_pins.items():
            if Path(path).parent != root or sha256_file(Path(path)) != digest:raise StoreError("cache-only published page SHA/path mismatch")
    else:root.mkdir(parents=True, exist_ok=True)
    wanted = sorted(set(requested_codes))
    if any(not _CODE_RE.fullmatch(code) for code in wanted):
        raise StoreError("display-name request requires explicit six-digit exchange identity")
    owned = api is None and not cache_only
    attempts = []
    if owned:
        from .a_d1_evidence import _host_port
        from pytdx.config.hosts import hq_hosts
        from pytdx.hq import TdxHq_API
        for entry in hq_hosts[:12]:
            host, port = _host_port(entry)
            candidate = TdxHq_API(heartbeat=False, raise_exception=True)
            try:
                if not candidate.connect(host, port, time_out=1.2):
                    raise ConnectionError("HQ connect returned false")
                probe = candidate.get_security_count(0)
                if not isinstance(probe, int) or probe <= 0:
                    raise ValueError("HQ security-count probe empty")
                candidate.client.settimeout(8.0)
                api = candidate
                break
            except Exception as error:
                attempts.append({"host": host, "port": port, "error": f"{type(error).__name__}:{error}"})
                candidate.disconnect()
        if api is None:
            _atomic_write(root / "connection_attempts.json", canonical_bytes(attempts))
            raise StoreError("current display-name HQ hosts unavailable; see connection_attempts.json")
    captured_at = datetime.now(timezone.utc).isoformat()
    host = str(api.client.getpeername()) if getattr(api, "client", None) else "INJECTED_TEST_API"
    pages = []
    names: dict[str, dict[str, Any]] = {}
    for row in official_rows or []:
        _verify_display_row(row, observation_date)
        if row["ts_code"] not in wanted or row["ts_code"] in names:
            raise StoreError("official display row duplicate/outside request")
        names[row["ts_code"]] = dict(row)
    conflicts: set[str] = set()
    try:
        for exchange, market in (("SZ", 0), ("SH", 1), ("BJ", 2)):
            if not any(code.endswith("." + exchange) and code not in names for code in wanted):
                continue
            count_path = root / f"hq-{exchange}-count.json"
            if count_path.is_file():
                count_evidence = json.loads(count_path.read_text())
                if count_evidence.get("observation_date") != observation_date:
                    raise StoreError("cached HQ count observation date mismatch")
                count = count_evidence["count"]
            else:
                if cache_only:raise StoreError("cache-only security count missing")
                count = api.get_security_count(market)
                count_evidence = dict(observation_date=observation_date, captured_at=captured_at,
                                      provider="PYTDX_HQ", method="get_security_count", host=host,
                                      market=market, count=count)
                _atomic_write(count_path, canonical_bytes(count_evidence))
            if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
                continue
            for offset in range(0, count, 1000):
                page_path = root / f"hq-{exchange}-{offset:05d}.json"
                if page_path.is_file():
                    page = json.loads(page_path.read_text())
                    if page.get("observation_date") != observation_date or page.get("market") != market or page.get("offset") != offset:
                        raise StoreError("cached HQ page identity mismatch")
                else:
                    if cache_only:raise StoreError("cache-only security page missing")
                    wire = _display_security_page(api, market, offset)
                    rows = wire.get("rows")
                    if not isinstance(rows, list) or not rows:
                        raise StoreError(f"HQ security-list page unavailable: {exchange}:{offset}")
                    page = dict(observation_date=observation_date, captured_at=captured_at,
                                provider="PYTDX_HQ", method="get_security_list", host=host,
                                market=market, exchange=exchange, offset=offset, count=count, **wire)
                    _atomic_write(page_path, canonical_bytes(page))
                digest = sha256_file(page_path)
                if cache_only and cached_page_pins.get(str(page_path)) != digest:raise StoreError("cache-only page not pinned by prior publication")
                pages.append({"path": str(page_path), "sha256": digest})
                for row in page["rows"]:
                    code = str(row.get("code") or "") + "." + exchange
                    name = str(row.get("name") or "").strip()
                    if code not in wanted or len(name) < 2 or name.isdigit():
                        continue
                    if cache_only and code in names:
                        if names[code]["name"] != name:conflicts.add(code)
                        continue
                    if code in names and names[code]["name"] != name:
                        conflicts.add(code)
                    names[code] = dict(ts_code=code, code=code[:6], exchange=exchange, name=name,
                                       provider="PYTDX_HQ", method="get_security_list", host=page["host"],
                                       observed_at=page["captured_at"], available_at=page["captured_at"],
                                       observation_date=observation_date, evidence_path=str(page_path),
                                       evidence_sha256=digest)
                if all(code in names for code in wanted if code.endswith("." + exchange)):
                    break
    finally:
        if owned:
            api.disconnect()
    for code in conflicts:
        names.pop(code, None)
    result = dict(schema_version=DISPLAY_SCHEMA, source_kind="DISPLAY_NAME_ONLY",
                  observation_date=observation_date, captured_at=captured_at,
                  requested_codes=wanted, rows=list(names.values()), pages=pages,
                  missing_codes=sorted(set(wanted) - set(names)), conflicted_codes=sorted(conflicts),
                  connection_attempts=attempts, research_only=True, **_SAFETY)
    if cache_only:
        result.update(cache_only=True, assembly_time=captured_at, capture_scope="ORIGINAL_CACHED_SOURCE_RESPONSES",
                      pages=[{"path":path,"sha256":digest} for path,digest in cached_page_pins.items()])
        if output_path is not None:
            destination=Path(output_path);destination.parent.mkdir(parents=True,exist_ok=True)
            with destination.open("xb") as stream:stream.write(canonical_bytes(result));stream.flush();os.fsync(stream.fileno())
    else:_atomic_write(root / "observation.json", canonical_bytes(result))
    return result


def publish_current_display_names(store_root: Path | str, observation: Mapping[str, Any], *,
                                  extend: bool = False, expected_prior_run_id: str | None = None,
                                  expected_index_sha256: str | None = None) -> dict[str, Any]:
    """One registry owner; extension is explicit, monotone and exact-prior bound."""
    from infrastructure.interprocess_lock import owned_interprocess_lock
    from .constants import STORE_LOCK_NAME
    if extend and (not expected_prior_run_id or not re.fullmatch(r"[0-9a-f]{64}",str(expected_index_sha256 or ""))):
        raise StoreError("display-name extension requires exact prior run/index SHA")
    if not extend and (expected_prior_run_id is not None or expected_index_sha256 is not None):
        raise StoreError("display-name prior pins require explicit extension")
    root=Path(store_root)/"assets"/"a_share_display_names"
    root.mkdir(parents=True,exist_ok=True)
    # Existing V4 mutex bridges the original store PID/token lock. No age-based
    # deletion; a live/unknown owner is refused immediately, including old callers.
    with owned_interprocess_lock(root/STORE_LOCK_NAME,timeout_seconds=0,
            timeout_message="display-name store owner busy",timeout_error=StoreError):
        return _publish_display_names_locked(root,observation,extend=extend,
            expected_prior_run_id=expected_prior_run_id,expected_index_sha256=expected_index_sha256)


def _publish_display_names_locked(root, observation, *, extend, expected_prior_run_id, expected_index_sha256):
    observation_date = validate_date(observation["observation_date"])
    if observation.get("schema_version") != DISPLAY_SCHEMA or observation.get("source_kind") != "DISPLAY_NAME_ONLY":
        raise StoreError("invalid display-name observation contract")
    if observation.get("missing_codes") or observation.get("conflicted_codes"):
        raise StoreError("display-name observation incomplete or conflicted")
    rows = observation.get("rows") or []
    if sorted(row["ts_code"] for row in rows) != sorted(set(observation["requested_codes"])) or len({row["code"] for row in rows})!=len(rows):
        raise StoreError("display-name request coverage/market identity mismatch")
    for row in rows:_verify_display_row(row,observation_date)
    latest=root/"latest.json";prior_raw=latest.read_bytes() if latest.is_file() else None
    index=json.loads(prior_raw) if prior_raw is not None else {"schema_version":DISPLAY_SCHEMA,"entries":{}}
    if not isinstance(index,Mapping) or index.get("schema_version")!=DISPLAY_SCHEMA or not isinstance(index.get("entries"),dict):
        raise StoreError("display-name registry index invalid")
    prior_entry=index["entries"].get(observation_date);extension=None
    if extend:
        import hashlib
        if prior_raw is None or hashlib.sha256(prior_raw).hexdigest()!=expected_index_sha256 or not isinstance(prior_entry,Mapping) or prior_entry.get("run_id")!=expected_prior_run_id:
            raise StoreError("display-name prior index/run CAS mismatch")
    if prior_entry is not None:
        old_mapping,prior_manifest=load_current_display_names(root.parents[1],observation_date)
        prior_run=resolve_under(root,prior_entry["run_relative"]);prior_observation=json.loads((prior_run/"artifact.json").read_text())
        if extend:
            old={row["ts_code"]:row for row in prior_observation["rows"]};new={row["ts_code"]:row for row in rows}
            if not set(old)<set(new) or any(canonical_bytes(new[code])!=canonical_bytes(row) for code,row in old.items()):
                raise StoreError("display-name extension must preserve all prior rows and strictly add coverage")
            new_pages={row["path"]:row for row in observation.get("pages",[])}
            if any(new_pages.get(row["path"])!=row for row in prior_observation.get("pages",[])):
                raise StoreError("display-name extension must preserve prior page pins")
            extension=dict(previous_run_id=prior_entry["run_id"],previous_index_sha256=expected_index_sha256,
                           previous_row_count=len(old),added_row_count=len(new)-len(old))
        else:
            stable_fields=("schema_version","source_kind","observation_date","requested_codes","rows","pages","missing_codes","conflicted_codes")
            if any(prior_observation.get(field)!=observation.get(field) for field in stable_fields):raise StoreError("display-name date publication conflict")
            return json.loads((prior_run/"receipt.json").read_text())
    elif extend:raise StoreError("display-name extension prior date missing")
    artifact=dict(observation)
    if extension:artifact["coverage_extension"]=extension
    run_id=sha256_json(artifact)[:24];run_root=root/"runs"/observation_date/run_id
    manifest=dict(schema_version=DISPLAY_SCHEMA,source_kind="DISPLAY_NAME_ONLY",observation_date=observation_date,
                  run_id=run_id,row_count=len(rows),artifact_sha256=sha256_json(artifact),
                  selector_certified=False,pit_certified=False,research_only=True,**_SAFETY)
    if extension:manifest["coverage_extension"]=extension
    receipt=dict(manifest,status="READY",manifest_sha256=sha256_json(manifest))
    for filename,data in (("artifact.json",artifact),("manifest.json",manifest),("receipt.json",receipt)):
        path=run_root/filename;content=canonical_bytes(data)
        if path.exists():
            if path.read_bytes()!=content:raise StoreError("immutable display publication conflict")
        else:_atomic_write(path,content)
    # The common owner mutex is still held. Recheck exact bytes immediately
    # before atomic replacement and preserve every other date entry.
    if (latest.read_bytes() if latest.is_file() else None)!=prior_raw:raise StoreError("display-name index changed under owner lock")
    index["entries"][observation_date]=dict(run_id=run_id,run_relative=f"runs/{observation_date}/{run_id}")
    _atomic_write(latest,canonical_bytes(index));return receipt


def load_current_display_names(store_root: Path | str, observation_date: str) -> tuple[dict[str, Any], dict[str, Any]]:
    observation_date = validate_date(observation_date)
    root = Path(store_root) / "assets" / "a_share_display_names"
    try:
        index = json.loads((root / "latest.json").read_text())
        if not isinstance(index, Mapping) or index.get("schema_version") != DISPLAY_SCHEMA or not isinstance(index.get("entries"), Mapping):
            raise StoreError("display-name registry index must contain an entries object")
        if observation_date not in index["entries"]:raise DisplayNameObservationMissing(f"display-name observation missing: {observation_date}")
        entry = index["entries"][observation_date]
        if not isinstance(entry, Mapping):
            raise StoreError("display-name registry entry must be an object")
        run = resolve_under(root, entry["run_relative"])
        artifact = json.loads((run / "artifact.json").read_text())
        manifest = json.loads((run / "manifest.json").read_text())
        receipt = json.loads((run / "receipt.json").read_text())
        for label, payload in (("artifact", artifact), ("manifest", manifest), ("receipt", receipt)):
            if not isinstance(payload, Mapping):
                raise StoreError(f"display-name registry {label} must be an object")
        if (not isinstance(artifact.get("rows"), list)
            or any(not isinstance(row, Mapping) for row in artifact["rows"])):
            raise StoreError("display-name artifact rows must contain objects")
        if (index.get("schema_version") != DISPLAY_SCHEMA or artifact.get("schema_version") != DISPLAY_SCHEMA
            or manifest.get("schema_version") != DISPLAY_SCHEMA or receipt.get("schema_version") != DISPLAY_SCHEMA
            or receipt.get("run_id") != entry["run_id"] or receipt.get("observation_date") != observation_date
            or manifest.get("source_kind") != "DISPLAY_NAME_ONLY" or manifest.get("observation_date") != observation_date
            or artifact.get("observation_date") != observation_date or receipt.get("status") != "READY"
            or receipt.get("manifest_sha256") != sha256_json(manifest)
            or manifest.get("artifact_sha256") != sha256_json(artifact)
            or manifest.get("run_id") != entry["run_id"] or artifact.get("missing_codes") or artifact.get("conflicted_codes")
            or any(manifest.get(flag) is not False for flag in _SAFETY)):
            raise StoreError("display-name publication verification failed")
        mapping = {}
        for row in artifact["rows"]:
            _verify_display_row(row, observation_date)
            if row["observation_date"] != observation_date or sha256_file(Path(row["evidence_path"])) != row["evidence_sha256"]:
                raise StoreError("display-name evidence date/SHA mismatch")
            if row["code"] in mapping or row["ts_code"] != row["code"] + "." + row["exchange"]:
                raise StoreError("display-name duplicate/exchange mismatch")
            mapping[row["code"]] = row
        if sorted(row["ts_code"] for row in mapping.values()) != sorted(set(artifact["requested_codes"])):
            raise StoreError("display-name request coverage mismatch")
        return mapping, manifest
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise StoreError(f"display-name authority unavailable: {error}") from error


def capture_official_display_document(evidence_root: Path | str, *, ts_code: str, name: str,
                                      url: str, published_date: str, observation_date: str,
                                      extract_text: Any) -> dict[str, Any]:
    """Capture an explicit official issuer document as display identity evidence."""
    from datetime import timezone
    from urllib.parse import urlparse
    from urllib.request import Request, urlopen
    if urlparse(url).scheme != "https" or urlparse(url).hostname not in {
        "www.bse.cn", "static.cninfo.com.cn", "dataclouds.cninfo.com.cn"
    } or not _CODE_RE.fullmatch(ts_code):
        raise StoreError("official display evidence source/identity invalid")
    observation_date = validate_date(observation_date)
    published_date = validate_date(published_date)
    if published_date > observation_date:
        raise StoreError("official document publication is after observation")
    root = Path(evidence_root)
    root.mkdir(parents=True, exist_ok=True)
    raw_path = root / f"official-{ts_code}.pdf"
    metadata_path = root / f"official-{ts_code}.json"
    if metadata_path.is_file():
        row = json.loads(metadata_path.read_text())
        if row["observation_date"] != observation_date or row["url"] != url:
            raise StoreError("official evidence cache identity mismatch")
        _verify_display_row(row, observation_date)
        return row
    captured_at = datetime.now(timezone.utc).isoformat()
    with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as response:
        body = response.read()
        response_status = response.status
    if not body.startswith(b"%PDF") or response_status != 200:
        raise StoreError("official display document is not a PDF response")
    _atomic_write(raw_path, body)
    extracted = extract_text(raw_path)
    normalized = re.sub(r"\s+", "", extracted)
    if ts_code[:6] not in normalized or re.sub(r"\s+", "", name) not in normalized:
        raise StoreError("official PDF does not attest the requested code/name")
    text_path = root / f"official-{ts_code}.txt"
    _atomic_write(text_path, extracted.encode("utf-8"))
    row = dict(ts_code=ts_code, code=ts_code[:6], exchange=ts_code[7:], name=name,
               provider="OFFICIAL_ISSUER_DISCLOSURE", method="PDF_TEXT_CODE_NAME_MATCH",
               url=url, host=urlparse(url).hostname, published_date=published_date,
               observed_at=captured_at, available_at=captured_at, observation_date=observation_date,
               evidence_path=str(raw_path), evidence_sha256=sha256_file(raw_path),
               extracted_text_path=str(text_path), extracted_text_sha256=sha256_file(text_path),
               response_status=response_status)
    _atomic_write(metadata_path, canonical_bytes(row))
    return row


def _verify_display_row(row: Mapping[str, Any], observation_date: str) -> None:
    text_fields = ("ts_code", "code", "exchange", "name", "provider", "observed_at", "available_at", "evidence_path", "evidence_sha256")
    if not isinstance(row, Mapping) or any(not isinstance(row.get(field), str) or not row[field].strip() for field in text_fields):
        raise StoreError("display-name row identity/evidence fields must be nonempty strings")
    if row.get("observation_date") != observation_date or not _CODE_RE.fullmatch(str(row.get("ts_code") or "")):
        raise StoreError("display-name row date/identity mismatch")
    if row["ts_code"] != row["code"] + "." + row["exchange"]:
        raise StoreError("display-name exchange mismatch")
    from zoneinfo import ZoneInfo
    for field in ("observed_at", "available_at"):
        timestamp = datetime.fromisoformat(str(row[field]).replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d") != observation_date:
            raise StoreError("display-name observation timestamp/date mismatch")
    path = Path(row["evidence_path"])
    if sha256_file(path) != row["evidence_sha256"]:
        raise StoreError("display-name raw evidence SHA mismatch")
    if row.get("provider") == "PYTDX_HQ":
        page = json.loads(path.read_text())
        if (not isinstance(page, Mapping) or not isinstance(page.get("rows"), list)
            or any(not isinstance(item, Mapping) for item in page["rows"])):
            raise StoreError("display-name HQ evidence must contain row objects")
        if (page.get("observation_date") != observation_date or page.get("exchange") != row["exchange"]
            or page.get("market") != {"SZ":0,"SH":1,"BJ":2}[row["exchange"]] or page.get("method") != "get_security_list"
            or not any(item.get("code") == row["code"] and item.get("name") == row["name"] for item in page["rows"])):
            raise StoreError("display-name HQ row does not match captured response")
    elif row.get("provider") == "OFFICIAL_ISSUER_DISCLOSURE":
        if any(not isinstance(row.get(field), str) for field in ("url", "extracted_text_path", "extracted_text_sha256")):
            raise StoreError("official display evidence references must be strings")
        from urllib.parse import urlparse
        if urlparse(row["url"]).hostname not in {"www.bse.cn", "static.cninfo.com.cn", "dataclouds.cninfo.com.cn"}:
            raise StoreError("unapproved official display source")
        text_path = Path(row["extracted_text_path"])
        if sha256_file(text_path) != row["extracted_text_sha256"] or not path.read_bytes().startswith(b"%PDF"):
            raise StoreError("official display text/raw evidence mismatch")
        content = re.sub(r"\s+", "", text_path.read_text())
        if row["code"] not in content or re.sub(r"\s+", "", row["name"]) not in content:
            raise StoreError("official display code/name assertion missing")
    else:
        raise StoreError("display-name evidence provider invalid")
