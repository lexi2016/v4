"""Resolve existing V3.5 Daily owner products without writing or copying their files."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from v4_core.runner.evidence import DatedInputs, EvidenceError, FileEvidence, iso_date, mapping, require
from v4_core.runner.state import json_bytes

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_MAX_OWNER_BYTES = 64 * 1024**2


def _read_file(path: Path, expected: str | None) -> tuple[bytes, str, float]:
    with path.open("rb") as stream:
        stat = path.stat()
        require(stat.st_size <= _MAX_OWNER_BYTES, "OWNER_EVIDENCE_READ_LIMIT")
        data = stream.read(_MAX_OWNER_BYTES + 1)
        final = path.stat()
    require((stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns) ==
            (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns, final.st_ctime_ns)
            and len(data) == stat.st_size, "OWNER_EVIDENCE_CHANGED_DURING_READ")
    digest = sha256(data).hexdigest()
    require(expected is None or digest == expected, "OWNER_EVIDENCE_SHA_MISMATCH")
    return data, digest, stat.st_mtime


def read_owner_inputs(
    base: DatedInputs | None, day: str, phase: str, owner_root: Path,
    calendar_path: Path | None = None, calendar_sha256: str | None = None,
) -> DatedInputs | None:
    if phase not in {"a_daily", "evening", "review"}:
        return base
    owner_root = owner_root.resolve()
    files = dict(base.owner_files) if base else {}
    timestamps: dict[str, float] = {}
    payload = dict(base.payload) if base else {"schema": "v4_core.r16_inputs.v1", "trade_date": day}
    workloads = dict(payload.get("workloads", {})) if isinstance(payload.get("workloads", {}), dict) else {}
    source_day = date.fromisoformat(day)
    current = source_day.strftime("%Y%m%d")
    data = owner_root / "data"

    def bind(path: Path, expected: str | None = None) -> dict:
        path = path.resolve(strict=True)
        require(path.is_relative_to(owner_root), "OWNER_EVIDENCE_PATH_ESCAPES_ROOT")
        key = "v35_owner/" + path.relative_to(owner_root).as_posix()
        if key not in files:
            raw, digest, modified = _read_file(path, expected)
            files[key] = (FileEvidence(key, digest, raw), path)
            timestamps[key] = modified
        evidence = files[key][0]
        require(expected is None or evidence.sha256 == expected, "OWNER_EVIDENCE_SHA_MISMATCH")
        return {"path": key, "sha256": evidence.sha256}

    def body(ref: dict) -> dict:
        return mapping(files[ref["path"]][0].json(), "OWNER_EVIDENCE_NOT_OBJECT")

    def observed(*refs: dict) -> str:
        latest = max(timestamps[ref["path"]] for ref in refs)
        return datetime.fromtimestamp(latest, _SHANGHAI).isoformat()

    def generated(name: str, content: dict) -> dict:
        key = f"v35_owner/calendar/{name}.json"
        raw = json_bytes(content)
        digest = sha256(raw).hexdigest()
        files[key] = (FileEvidence(key, digest, raw), None)
        return {"path": key, "sha256": digest}

    def calendar_binding() -> dict:
        require(calendar_path is not None and isinstance(calendar_sha256, str)
                and re.fullmatch(r"[0-9a-f]{64}", calendar_sha256), "OWNER_A_CALENDAR_UNPINNED")
        raw, digest, _ = _read_file(calendar_path, calendar_sha256)
        calendar = mapping(FileEvidence("", digest, raw).json(), "OWNER_A_CALENDAR_INVALID")
        require(calendar.get("year") == source_day.year and calendar.get("timezone") == "Asia/Shanghai",
                "OWNER_A_CALENDAR_OUTSIDE_COVERAGE")
        market = mapping(calendar["markets"].get("a_share"), "OWNER_A_CALENDAR_MARKET_UNAVAILABLE")
        holidays = [(date.fromisoformat(item["start"]), date.fromisoformat(item["end"]))
                    for item in market["holiday_periods"]]

        def in_session(value: date) -> bool:
            return value.weekday() < 5 and not any(start <= value <= end for start, end in holidays)

        require(in_session(source_day), "OWNER_A_SOURCE_DAY_CLOSED")
        target = source_day + timedelta(days=1)
        sessions = [{"trade_date": day, "is_session": True}]
        while target.year == source_day.year and not in_session(target):
            sessions.append({"trade_date": target.isoformat(), "is_session": False})
            target += timedelta(days=1)
        require(target.year == source_day.year, "OWNER_A_NEXT_SESSION_OUTSIDE_COVERAGE")
        sessions.append({"trade_date": target.isoformat(), "is_session": True})
        identity = {"market": "A", "source_date": day, "target_date": target.isoformat(), "status": "READY",
                    "source_identity": "sha256:" + digest, "production_allowed": False, "orders_sent": False,
                    "buy_gate_updated": False}
        calendar_ref = generated("calendar", {
            "schema": "v4_core.a_session_binding.v1", **identity, "sessions": sessions,
        })
        receipt_ref = generated("receipt", {
            "schema": "v4_core.a_session_binding_receipt.v1", **identity, "calendar_sha256": calendar_ref["sha256"],
        })
        return {"calendar": calendar_ref, "receipt": receipt_ref}

    def hourly() -> dict:
        rel = Path(f"research/hourly/live/{current}/1900.json")
        receipt = bind(data / "receipts" / rel)
        owner = body(receipt)
        require(iso_date(owner.get("archive_date")) == day and owner.get("mode") == "LIVE"
                and all(isinstance(owner.get(key), str) and re.fullmatch(r"[0-9a-f]{64}", owner[key])
                        for key in ("source_input_sha256", "payload_sha256")), "OWNER_HOURLY_RECEIPT_UNBOUND")
        source = bind(data / "research" / "incoming" / current / "1900.json", owner["source_input_sha256"])
        artifact = bind(data / rel, owner["payload_sha256"])
        return {"status": body(artifact).get("status"), "observed_at": observed(source, artifact, receipt),
                "source": source, "artifact": artifact, "receipt": receipt}

    def hk_model_pit(pool: dict) -> dict:
        relative = pool.get("source_path")
        require(isinstance(relative, str)
                and re.fullmatch(rf"runs/{current}/HK_CONNECT_D1_TOP100_0_2/[a-z0-9-]+/artifact\.csv", relative)
                and isinstance(pool.get("source_artifact_sha256"), str), "OWNER_HK_PIT_SOURCE_UNBOUND")
        location = owner_root / "workspace/v3_shared_data/.runtime/data" / relative
        receipt = bind(location.with_name("receipt.json"))
        digest = body(receipt).get("manifest_sha256")
        require(isinstance(digest, str), "OWNER_HK_PIT_MANIFEST_UNBOUND")
        return {"artifact": bind(location, pool["source_artifact_sha256"]),
                "manifest": bind(location.with_name("manifest.json"), digest), "receipt": receipt}

    def hk_close() -> dict:
        registry = data / "preselection_pools" / current
        refset = {
            "close_snapshot": bind(data / "hkconnect_close_snapshots" / f"{current}.json"),
            "close_snapshot_receipt": bind(data / "receipts" / "hkconnect_close_snapshots" / f"{current}.json"),
            "model_pool": bind(registry / "hkconnect_d1_top100.json"),
        }
        entry = {"status": body(refset["close_snapshot"]).get("status"),
                 "observed_at": observed(*refset.values()), **refset}
        try:
            artifact = bind(data / "close_reviews" / f"{current}.json")
            receipt = bind(data / "receipts" / "close_reviews" / f"{current}.json")
            require(iso_date(body(artifact).get("trade_date")) == day, "OWNER_HK_CLOSE_REVIEW_DATE_MISMATCH")
            entry.update(artifact=artifact, receipt=receipt, close_review=artifact, close_review_receipt=receipt,
                         status=body(artifact).get("status"), observed_at=observed(*refset.values(), artifact, receipt))
        except (OSError, EvidenceError):
            pass
        try:
            entry["model_pit"] = hk_model_pit(body(refset["model_pool"]))
        except (OSError, EvidenceError):
            pass
        return entry

    def observation(target: str) -> dict:
        folder = data / "preselection_pools" / target
        pool = bind(folder / "a_d1_premarket_pool.json")
        registry = bind(folder / "manifest.json")
        return {"candidate_pool": pool, "pool_registry": registry, "observed_at": observed(pool, registry)}

    def fupan(target: str) -> dict:
        folder = data / "preselection_pools" / target
        native = data / "preselection_inputs" / target
        refs = {"pool": bind(folder / "a_d1_fupan_watchlist_pool.json"), "pool_registry": bind(folder / "manifest.json"),
                "pool_manifest": bind(native / "fupan.manifest.json"), "pool_csv": bind(native / "fupan.csv")}
        root = (data / "d1_review_sources" / current / "native/video").resolve()
        video = {}
        for value in body(refs["pool_manifest"]).get("video_source_paths") or []:
            if isinstance(value, str) and Path(value).is_absolute() and Path(value).resolve().is_relative_to(root):
                try:
                    video[value] = bind(Path(value))["sha256"]
                except (OSError, EvidenceError):
                    continue
        return {**refs, "observed_at": observed(*refs.values()), "video_sources": video}

    def try_lane(name, build) -> None:
        if name not in workloads:
            try:
                workloads[name] = build()
            except (OSError, ValueError, TypeError, KeyError):
                pass

    target = None
    if phase in {"evening", "review"}:
        try:
            if "next_a_session" not in payload:
                payload["next_a_session"] = calendar_binding()
            session = payload["next_a_session"]["calendar"]
            calendar = body(session) if session["path"] in files else base.file(session).json()
            target = iso_date(calendar["target_date"]).replace("-", "")
        except (OSError, ValueError, TypeError, KeyError):
            pass
        try_lane("hourly_announcements", hourly)
        if target:
            try_lane("next_day_observation", lambda: observation(target))
            if phase == "review":
                try_lane("fupan", lambda: fupan(target))
    if phase in {"a_daily", "review"}:
        try_lane("hk_close", hk_close)
    if workloads:
        payload["workloads"] = workloads
    if base is not None and payload == base.payload:
        return base
    if base is None and not workloads and "next_a_session" not in payload:
        return None
    directory = base.directory if base else owner_root / "data"
    return DatedInputs(directory, day, payload, sha256(json_bytes(payload)).hexdigest(), files)
