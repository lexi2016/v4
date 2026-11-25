"""Verified HK cache handoff and source-only Stage7 replay from one raw registry."""
from __future__ import annotations

from datetime import datetime, time
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from typing import Any

from v4_core.runner.evidence import (
    DatedInputs, EvidenceError, FileEvidence, SAFETY_FLAGS, aware_time, entry_digest, iso_date, mapping, require, symbol,
)
from v4_core.runner.state import json_bytes, publish_json

STAGE7_ROLE = "A_SHARE_1MIN_STAGE_1445_1500"
STAGE7_ID = "STAGE_1445_1500"
STAGE7_POOL = "a_d1_stage7_fenshi_review_pool"
HK_CACHE_ROLE = "HK_CONNECT_D1_TOP100_0_2"
_STAGE_CLOCK = re.compile(r"(?:(\d{4}-\d{2}-\d{2}|\d{8})[ T])?(\d{2}:\d{2}(?::\d{2})?)")
_STAGE_UNSAFE_FIELDS = {
    "buy", "buy_signal", "primary_buy_signal", "secondary_buy_signal", "recommendation",
    "recommendation_status", "formal_recommendation", "trade_status", "selected", "stage_selected",
    "selection_status",
}


def _safe_flags(record: dict[str, Any], reason: str) -> None:
    require(all(record.get(key) is False for key in SAFETY_FLAGS if key != "research_only"), reason)
    require(record.get("research_only", True) is True, reason)


def _three_files(inputs: DatedInputs, entry: dict) -> dict[str, FileEvidence]:
    return {role: inputs.file(entry.get(role)) for role in ("artifact", "manifest", "receipt")}


def _file_ids(files: dict[str, FileEvidence]) -> dict[str, Any]:
    return {key: item.identity() for key, item in files.items()}


def _validate_hk_cache(
    files: dict[str, FileEvidence], source_date: str, target_date: str,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    manifest_file, artifact = files["manifest"], files["artifact"]
    manifest = mapping(manifest_file.json(), "INVALID_HK_CACHE_MANIFEST")
    receipt = mapping(files["receipt"].json(), "INVALID_HK_CACHE_RECEIPT")
    provenance = mapping(manifest.get("provenance"), "HK_CACHE_PROVENANCE_UNAVAILABLE")
    require(source_date < target_date and iso_date(manifest.get("signal_date")) == source_date
            and iso_date(provenance.get("signal_date")) == source_date
            and iso_date(manifest.get("trade_date")) == iso_date(receipt.get("trade_date")) == target_date,
            "HK_CACHE_DATE_MISMATCH")
    require(manifest.get("market") == "HK_CONNECT" and manifest.get("stage_id") == "D1_PREMARKET"
            and manifest.get("temporal_cutoff_safe") is True and manifest.get("cutoff_at") == "17:30:00"
            and receipt.get("role") == HK_CACHE_ROLE and receipt.get("stage_id") == "D1_PREMARKET"
            and receipt.get("status") == "READY" and isinstance(receipt.get("run_id"), str) and receipt["run_id"],
            "HK_CACHE_IDENTITY_MISMATCH")
    _safe_flags(receipt, "HK_CACHE_RECEIPT_UNSAFE")
    require(receipt.get("manifest_sha256") == manifest_file.sha256
            and receipt.get("artifact_sha256") == manifest.get("artifact_sha256") == artifact.sha256,
            "HK_CACHE_ARTIFACT_OR_MANIFEST_SHA_MISMATCH")
    rows = artifact.csv()
    require(type(manifest.get("row_count")) is int and manifest["row_count"] == len(rows) and 0 < len(rows) <= 100,
            "HK_CACHE_ROW_COUNT_MISMATCH")
    codes: set[str] = set()
    ranks: set[int] = set()
    for row in rows:
        raw_code = row.get("code_norm", "")
        code = symbol(f"{raw_code}.HK" if raw_code.isdigit() else raw_code, "HK")
        try:
            rank = int(row.get("rank", ""))
            probability = float(row.get("score_prob_active", ""))
        except ValueError as exc:
            raise EvidenceError("HK_CACHE_ROW_IDENTITY_INVALID") from exc
        require(code not in codes and rank not in ranks and math.isfinite(probability)
                and row.get("history_resolution_identity"), "HK_CACHE_ROW_IDENTITY_INVALID")
        require(iso_date(row.get("trade_date")) == target_date and iso_date(row.get("signal_date")) == source_date,
                "HK_CACHE_ROW_DATE_MISMATCH")
        codes.add(code)
        ranks.add(rank)
    require(ranks == set(range(1, len(rows) + 1)), "HK_CACHE_RANKS_MISMATCH")
    available = aware_time(receipt.get("finished_at"))
    require(available.date().isoformat() == source_date and available == aware_time(manifest.get("captured_at")),
            "HK_CACHE_SOURCE_PUBLICATION_TIME_MISMATCH")
    return {
        "available_at": available.isoformat(), "status": "READY", "role": HK_CACHE_ROLE, "signal_date": source_date, "target_date": target_date,
        "run_id": receipt["run_id"], "row_count": len(rows), "source_identity": _file_ids(files),
        "source_manifest_sha256": manifest_file.sha256, "source_receipt_sha256": files["receipt"].sha256,
        **SAFETY_FLAGS,
    }, rows


def verify_hk_model_pit(
    inputs: DatedInputs, binding: dict, source_date: str,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Verify the prior session's native cache chain for today's HK model."""
    return _validate_hk_cache(_three_files(inputs, binding), source_date, inputs.trade_date)


def write_hk_cache(data_dir: Path, inputs: DatedInputs, *, asof: datetime | None = None) -> dict[str, Any]:
    entry = inputs.entry("hk_cache")
    source, target = iso_date(entry.get("source_date")), iso_date(entry.get("target_date"))
    require(source == inputs.trade_date, "HK_CACHE_SUBMISSION_DATE_MISMATCH")
    files = _three_files(inputs, entry)
    result, _ = _validate_hk_cache(files, source, target)
    require(asof is None or aware_time(result["available_at"]) <= asof, "HK_CACHE_EVIDENCE_AFTER_READBACK")
    path = data_dir / "hk_cache" / f"{source}.json"
    cache = {**result, "schema": "v4_core.hk_cache.v1", "source_binding_sha256": inputs.entry_sha256("hk_cache"),
             "source_binding": entry,
             "content": {key: value.data.decode("utf-8") for key, value in files.items()}}
    if path.is_file():
        current, _ = read_hk_cache(data_dir, source, target, expected_entry=entry)
        require(current["source_identity"] == result["source_identity"], "HK_CACHE_ALREADY_PINNED")
        return current
    return {**result, "cache_sha256": publish_json(path, cache)}


def read_hk_cache(
    data_dir: Path, source_date: str, target_date: str | None = None, *, expected_entry: dict | None = None,
    asof: datetime | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    source_date = iso_date(source_date)
    path = data_dir / "hk_cache" / f"{source_date}.json"
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise EvidenceError("HK_CACHE_WRITER_OUTPUT_UNAVAILABLE") from exc
    digest = sha256(data).hexdigest()
    cache = mapping(FileEvidence(path.name, digest, data).json(), "HK_CACHE_FORMAT_INVALID")
    require(cache.get("schema") == "v4_core.hk_cache.v1" and iso_date(cache.get("signal_date")) == source_date,
            "HK_CACHE_WRITER_OUTPUT_IDENTITY_MISMATCH")
    target = iso_date(target_date if target_date is not None else cache.get("target_date"))
    binding = mapping(cache.get("source_binding"), "HK_CACHE_WRITER_SOURCE_UNBOUND")
    require(cache.get("source_binding_sha256") == entry_digest(source_date, ("hk_cache",), binding)
            and iso_date(binding.get("source_date")) == source_date and iso_date(binding.get("target_date")) == target
            and (expected_entry is None or expected_entry == binding), "HK_CACHE_WRITER_SOURCE_MISMATCH")
    identities = mapping(cache.get("source_identity"), "HK_CACHE_FILE_BINDINGS_UNAVAILABLE")
    content = mapping(cache.get("content"), "HK_CACHE_CONTENT_UNAVAILABLE")
    files: dict[str, FileEvidence] = {}
    for key in ("artifact", "manifest", "receipt"):
        identity = mapping(identities.get(key), "HK_CACHE_FILE_BINDING_INVALID")
        value = content.get(key)
        require(isinstance(value, str) and isinstance(identity.get("path"), str), "HK_CACHE_CONTENT_INVALID")
        original = value.encode("utf-8")
        actual = sha256(original).hexdigest()
        require(actual == identity.get("sha256") and len(original) == identity.get("bytes"),
                f"HK_CACHE_{key.upper()}_SHA_OR_SIZE_MISMATCH")
        expected = mapping(binding.get(key), "HK_CACHE_EXPECTED_IDENTITY_UNBOUND")
        require(actual == expected.get("sha256") and identity["path"] == expected.get("path"),
                f"HK_CACHE_{key.upper()}_WRITER_SOURCE_MISMATCH")
        files[key] = FileEvidence(identity["path"], actual, original)
    result, rows = _validate_hk_cache(files, source_date, target)
    require(asof is None or aware_time(result["available_at"]) <= asof, "HK_CACHE_EVIDENCE_AFTER_READBACK")
    require(cache.get("target_date") == target and cache.get("run_id") == result["run_id"]
            and cache.get("row_count") == len(rows) and cache.get("available_at") == result["available_at"]
            and all(cache.get(key) == result[key] for key in ("source_manifest_sha256", "source_receipt_sha256")),
            "HK_CACHE_WRITER_OUTPUT_IDENTITY_MISMATCH")
    return {**result, "cache_sha256": digest}, rows


def _stage_clock(value: str, source_date: str) -> time:
    match = _STAGE_CLOCK.fullmatch(value.strip())
    require(match, "STAGE7_ROW_CLOCK_INVALID")
    date_value, clock = match.groups()
    require(date_value is None or iso_date(date_value) == source_date, "STAGE7_ROW_CLOCK_DATE_MISMATCH")
    try:
        return time.fromisoformat(clock)
    except ValueError as exc:
        raise EvidenceError("STAGE7_ROW_CLOCK_INVALID") from exc


def _validate_stage7(
    inputs: DatedInputs, entry: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source, target = iso_date(entry.get("source_date")), iso_date(entry.get("target_date"))
    require(source == inputs.trade_date and source < target, "STAGE7_SOURCE_TARGET_DATE_MISMATCH")
    files = _three_files(inputs, entry)
    artifact = files["artifact"]
    manifest = mapping(files["manifest"].json(), "INVALID_STAGE7_MANIFEST")
    receipt = mapping(files["receipt"].json(), "INVALID_STAGE7_RECEIPT")
    for record in (manifest, receipt):
        require(iso_date(record.get("trade_date")) == source and record.get("role") == STAGE7_ROLE
                and record.get("stage_id") == STAGE7_ID and record.get("market") == "A_SHARE"
                and record.get("temporal_cutoff_safe") is True and record.get("status") == "READY"
                and record.get("artifact_sha256") == artifact.sha256, "STAGE7_SOURCE_IDENTITY_MISMATCH")
        _safe_flags(record, "STAGE7_SOURCE_UNSAFE")
    canonical_manifest_sha = sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    require(receipt.get("manifest_sha256") == canonical_manifest_sha, "STAGE7_MANIFEST_SHA_MISMATCH")
    require(isinstance(manifest.get("run_id"), str) and manifest["run_id"]
            and receipt.get("run_id") == manifest["run_id"] and receipt.get("cutoff_at") == "15:00:00",
            "STAGE7_RUN_OR_CUTOFF_MISMATCH")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    floor, ceiling = time(14, 45), time(15, 0)
    for raw in artifact.csv():
        require(iso_date(raw.get("trade_date")) == source, "STAGE7_ROW_DATE_MISMATCH")
        code = symbol(raw.get("code") or raw.get("symbol") or raw.get("ts_code"), "A")
        require(code not in seen, "STAGE7_ROW_CODE_DUPLICATE")
        bar = _stage_clock(raw.get("bar_time", ""), source)
        end = _stage_clock(raw.get("window_end", ""), source)
        start = _stage_clock(raw["window_start"], source) if raw.get("window_start") else floor
        require(floor <= bar <= end <= ceiling and floor <= start <= end
                and raw.get("temporal_cutoff_safe", "").strip().lower() == "true", "STAGE7_ROW_CUTOFF_UNSAFE")
        seen.add(code)
        rows.append({
            **{key: value for key, value in raw.items() if key.lower() not in _STAGE_UNSAFE_FIELDS},
            "rank": len(rows) + 1, "market": "A", "symbol": code, "signal_date": source, "target_date": target,
            "source_merge_role": "SOURCE_ONLY", "stage_selection_eligible": False, **SAFETY_FLAGS,
        })
    require(rows and type(manifest.get("row_count")) is int
            and len(rows) == manifest["row_count"] == receipt.get("row_count"), "STAGE7_ROW_COUNT_MISMATCH")
    return {
        "status": "READY", "stage_id": STAGE7_ID, "role": STAGE7_ROLE, "pool_id": STAGE7_POOL,
        "signal_date": source, "target_date": target, "row_count": len(rows), "run_id": manifest["run_id"],
        "source_identity": _file_ids(files), "manifest_canonical_sha256": canonical_manifest_sha,
        "formal_rows_sha256": sha256(json_bytes(rows)).hexdigest(),
        "source_merge_role": "SOURCE_ONLY", "stage_selection_eligible": False, **SAFETY_FLAGS,
    }, rows


def publish_stage7(data_dir: Path, inputs: DatedInputs) -> dict[str, Any]:
    result, rows = _validate_stage7(inputs, inputs.entry("stage7"))
    path = data_dir / "stage_raw" / f"{inputs.trade_date}.json"
    if path.is_file():
        current, _ = read_stage7(data_dir, inputs.trade_date, result["target_date"])
        require(current["source_identity"] == result["source_identity"], "STAGE7_SOURCE_ALREADY_PINNED")
        return current
    registry = {
        "schema": "v4_core.stage_raw.v1", "source_root": str(inputs.directory.parent),
        "source_binding_sha256": inputs.entry_sha256("stage7"), "binding": result, "formal_rows": rows,
    }
    return {**result, "registry_sha256": publish_json(path, registry)}


def read_stage7(
    data_dir: Path, source_date: str, target_date: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source_date = iso_date(source_date)
    path = data_dir / "stage_raw" / f"{source_date}.json"
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise EvidenceError("VERIFIED_STAGE7_REGISTRY_UNAVAILABLE") from exc
    digest = sha256(data).hexdigest()
    registry = mapping(FileEvidence(path.name, digest, data).json(), "INVALID_STAGE7_REGISTRY")
    require(registry.get("schema") == "v4_core.stage_raw.v1" and isinstance(registry.get("source_root"), str),
            "INVALID_STAGE7_REGISTRY")
    inputs = DatedInputs.load(Path(registry["source_root"]), source_date)
    require(inputs.entry_sha256("stage7") == registry.get("source_binding_sha256"), "STAGE7_INPUT_REGISTRY_SHA_MISMATCH")
    result, rows = _validate_stage7(inputs, inputs.entry("stage7"))
    require(registry.get("binding") == result and registry.get("formal_rows") == rows
            and (target_date is None or result["target_date"] == iso_date(target_date)),
            "STAGE7_REGISTRY_BINDING_MISMATCH")
    return {**result, "registry_sha256": digest}, rows
