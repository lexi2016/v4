"""Build the research-only overnight edition and read the authoritative Fupan pool."""
from __future__ import annotations

from datetime import datetime
from hashlib import file_digest, sha256
import math
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from v4_core.runner.evidence import DatedInputs, EvidenceError, FileEvidence, SAFETY_FLAGS, iso_date, mapping, require, symbol

_BEIJING = ZoneInfo("Asia/Shanghai")
_SHA = re.compile(r"[0-9a-f]{64}")


def _a_pool(
    inputs: DatedInputs, entry: dict, target: str, pool_id: str, key: str,
) -> tuple[dict, list[dict], dict]:
    pool_file = inputs.file(entry.get(key))
    registry_file = inputs.file(entry.get("pool_registry"))
    pool = mapping(pool_file.json(), "NEXT_A_POOL_INVALID")
    registry = mapping(registry_file.json(), "NEXT_A_POOL_REGISTRY_INVALID")
    require(registry.get(pool_id) == pool_file.sha256 and pool.get("pool_id") == pool_id
            and pool.get("market") == "A" and iso_date(pool.get("trade_date")) == target
            and pool.get("schema_version") == "v3_5.preselection_pool.v1", "NEXT_A_POOL_REGISTRY_OR_IDENTITY_MISMATCH")
    require(all(pool.get(key) is False for key in SAFETY_FLAGS if key != "research_only"),
            "NEXT_A_POOL_UNSAFE")
    raw = pool.get("rows")
    require(isinstance(raw, list) and raw, "NEXT_A_POOL_ROWS_MISSING")
    selected = []
    for value in raw:
        row = mapping(value, "NEXT_A_POOL_ROW_INVALID")
        require(row.get("market") == "A" and iso_date(row.get("target_date")) == target
                and iso_date(row.get("signal_date")) == inputs.trade_date
                and all(row.get(key) is False for key in SAFETY_FLAGS if key != "research_only"),
                "NEXT_A_POOL_ROW_IDENTITY_OR_FLAGS_MISMATCH")
        code = symbol(row.get("ts_code") or row.get("symbol"), "A")
        try:
            rank = int(row.get("pool_rank"))
        except (TypeError, ValueError) as exc:
            raise EvidenceError("NEXT_A_POOL_RANK_INVALID") from exc
        require(rank > 0, "NEXT_A_POOL_RANK_INVALID")
        selected.append({
            "market": "A", "symbol": code, "name": row.get("stock_name") or row.get("name"),
            "pool_rank": rank, "signal_date": inputs.trade_date, "target_date": target,
            "recommendation_status": "WATCH_ONLY", "tradable": False, **SAFETY_FLAGS,
        })
    require(len({row["symbol"] for row in selected}) == len(selected)
            and sorted(row["pool_rank"] for row in selected) == list(range(1, len(selected) + 1)),
            "NEXT_A_POOL_INVALID_RANKS_OR_DUPLICATES")
    return pool, sorted(selected, key=lambda row: row["pool_rank"]), {
        "pool": pool_file.identity(), "pool_registry": registry_file.identity(),
    }


def build_next_day_observation(
    inputs: DatedInputs, entry: dict, target: str, hourly: dict, hourly_rows: list[dict],
) -> tuple[dict, dict[str, list]]:
    pool, rows, source = _a_pool(inputs, entry, target, "a_d1_premarket_pool", "candidate_pool")
    require(pool.get("status") == "V192_CANDIDATE_READY" and pool.get("source_role") == "SHARED_VERIFIED_V192"
            and iso_date(pool.get("signal_date")) == inputs.trade_date and iso_date(pool.get("target_date")) == target
            and pool.get("source_row_count") == len(rows) and pool.get("stage_selection_eligible") is True,
            "OBSERVATION_A_SELECTOR_NOT_READY")
    metrics = {}
    for item in hourly_rows:
        try:
            code = symbol(item.get("stock_code"), "A")
        except EvidenceError:
            continue
        score = item.get("research_score")
        if type(score) in {int, float} and math.isfinite(score):
            metrics[code] = score
    for row in rows:
        row["hourly_research_score"] = metrics.get(row["symbol"])
    return {
        "role": "NEXT_DAY_OBSERVATION_EDITION", "status": "READY", "source_status": pool["status"],
        "source_mode": "NATIVE_INPUT_MATERIALIZATION", "source_identity": source, "target_date": target,
        "upstream_hourly_publication_sha256": hourly["publication_sha256"],
        "markets": ["A"], "row_count": len(rows), **SAFETY_FLAGS,
    }, {"rows": rows}


def _managed_file(path_value, expected, root_name: str, *, stream: bool = False) -> tuple[FileEvidence, int]:
    root_value = os.environ.get(root_name)
    require(root_value and isinstance(path_value, str) and Path(path_value).is_absolute()
            and isinstance(expected, str) and _SHA.fullmatch(expected), f"FUPAN_OWNER_REF_UNBOUND:{root_name}")
    root, path = Path(root_value).resolve(), Path(path_value).resolve()
    require(path.is_relative_to(root), f"FUPAN_OWNER_PATH_ESCAPES_ROOT:{root_name}")
    try:
        with path.open("rb") as source:
            before = os.fstat(source.fileno())
            if stream:
                digest = file_digest(source, "sha256").hexdigest()
                data = b""
            else:
                require(before.st_size <= 8_000_000, f"FUPAN_OWNER_METADATA_SIZE_INVALID:{root_name}")
                data = source.read()
                digest = sha256(data).hexdigest()
            after = os.fstat(source.fileno())
    except OSError as exc:
        raise EvidenceError(f"FUPAN_OWNER_FILE_UNAVAILABLE:{root_name}:{path.name}") from exc
    require(expected == digest and before.st_size > 0
            and (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                == (after.st_size, after.st_mtime_ns, after.st_ctime_ns),
            f"FUPAN_OWNER_FILE_SHA_OR_IDENTITY_MISMATCH:{root_name}:{path.name}")
    return FileEvidence(str(path), digest, data), before.st_size


def _fupan_selector(manifest: dict, day: str) -> dict:
    selector = mapping(manifest.get("selector_source_binding"), "FUPAN_SELECTOR_GENERATION_UNBOUND")
    ref = mapping(selector.get("generation_receipt"), "FUPAN_SELECTOR_GENERATION_RECEIPT_UNBOUND")
    source_file, size = _managed_file(
        selector.get("path"), selector.get("sha256"), "V4_FUPAN_SELECTOR_ROOT", stream=True,
    )
    receipt_file, _ = _managed_file(
        ref.get("path"), ref.get("sha256"), "V4_FUPAN_SELECTOR_RECEIPT_ROOT",
    )
    receipt = mapping(receipt_file.json(), "FUPAN_SELECTOR_GENERATION_RECEIPT_INVALID")
    candidates = mapping(receipt.get("candidate_sha256"), "FUPAN_SELECTOR_GENERATION_CANDIDATE_HASH_UNBOUND")
    generation, input_sha = selector.get("generation_id"), selector.get("input_sha256")
    require(type(selector.get("bytes")) is int and selector["bytes"] == size
            and isinstance(generation, str) and _SHA.fullmatch(generation) and generation == receipt.get("generation_id")
            and isinstance(input_sha, str) and _SHA.fullmatch(input_sha) and input_sha == receipt.get("input_sha256")
            and iso_date(selector.get("signal_date")) == iso_date(receipt.get("target_date")) == day
            and iso_date(receipt.get("asof_date")) == day and receipt.get("schema") == "a_share_qfq_panel_v1"
            and receipt.get("status") == "CANDIDATE_READY" and candidates.get("selector") == source_file.sha256
            and receipt.get("RESEARCH_ONLY") is True
            and all(receipt.get(key) is False for key in SAFETY_FLAGS if key != "research_only"),
            "FUPAN_SELECTOR_GENERATION_RECEIPT_OR_ARTIFACT_MISMATCH")
    return {"status": "READY", "generation_id": generation, "input_sha256": input_sha,
            "selector_artifact": {**source_file.identity(), "bytes": size}, "generation_receipt": receipt_file.identity()}


def _fupan_video(manifest: dict, entry: dict, day: str) -> dict:
    paths = manifest.get("video_source_paths")
    require(manifest.get("video_fupan_status") == "VIDEO_FUPAN_GAP_MATRIX_READY"
            and isinstance(paths, list) and paths and all(isinstance(path, str) for path in paths)
            and len(set(paths)) == len(paths), "FUPAN_VIDEO_SECOND_REVIEW_INCOMPLETE")
    bound = mapping(entry.get("video_sources"), "FUPAN_VIDEO_SOURCE_HASH_BINDINGS_UNAVAILABLE")
    require(set(bound) == set(paths), "FUPAN_VIDEO_MANIFEST_SOURCE_SET_MISMATCH")
    files = {}
    for name in paths:
        file, _ = _managed_file(name, bound[name], "V4_FUPAN_VIDEO_ROOT")
        key = Path(name).name
        require(key not in files, "FUPAN_VIDEO_SOURCE_ROLE_DUPLICATE")
        files[key] = file
    compact = day.replace("-", "")
    acceptance = files.get(f"acceptance_{compact}.json")
    capture = files.get(f"capture_manifest_{compact}.json")
    gaps = files.get(f"video_gap_matrix_{compact}.csv")
    require(acceptance and capture and gaps, "FUPAN_VIDEO_ACCEPTANCE_CAPTURE_OR_GAP_MATRIX_UNBOUND")
    accepted = mapping(acceptance.json(), "FUPAN_VIDEO_ACCEPTANCE_INVALID")
    captured = mapping(capture.json(), "FUPAN_VIDEO_CAPTURE_MANIFEST_INVALID")
    require(accepted.get("schema_version") == "v3_5.bilibili_fupan_acceptance.v1"
            and accepted.get("status") == "VIDEO_METADATA_READY" and not accepted.get("cannot_confirm")
            and iso_date(accepted.get("trade_date")) == iso_date(captured.get("trade_date")) == day
            and captured.get("schema_version") == "v3_5.bilibili_capture_manifest.v1"
            and captured.get("source_acceptance_sha256") == acceptance.sha256
            and all(captured.get(key) is False for key in SAFETY_FLAGS if key != "research_only"),
            "FUPAN_VIDEO_ACCEPTANCE_CAPTURE_BINDING_MISMATCH")
    videos = accepted.get("locked_videos")
    require(isinstance(videos, list) and videos, "FUPAN_VIDEO_SAME_DAY_ACCEPTANCE_UNAVAILABLE")
    codes = set()
    for value in videos:
        video = mapping(value, "FUPAN_VIDEO_ACCEPTANCE_ROW_INVALID")
        bv = str(video.get("bv_id", ""))
        require(video.get("date_scope") == "SAME_DAY_FUPAN" and iso_date(video.get("upload_date")) == day
                and re.fullmatch(r"BV[0-9A-Za-z]+", bv), "FUPAN_VIDEO_ACCEPTANCE_DATE_OR_ID_INVALID")
        codes.add(bv)
    captured_videos = captured.get("videos")
    require(isinstance(captured_videos, list) and all(isinstance(item, dict) for item in captured_videos)
            and codes <= {row.get("bv_id") for row in captured_videos if row.get("status") == "ASR_REVIEW_REQUIRED"},
            "FUPAN_VIDEO_ASR_CAPTURE_UNAVAILABLE")
    gap_rows = gaps.csv()
    require(gap_rows and len(gap_rows) == manifest.get("video_fupan_gap_rows"), "FUPAN_VIDEO_GAP_MATRIX_COUNT_MISMATCH")
    for row in gap_rows:
        require((row.get("bv_id") or row.get("source_bv_id")) in codes
                and iso_date(row.get("trade_date") or row.get("signal_date")) == day,
                "FUPAN_VIDEO_GAP_MATRIX_VIDEO_OR_DATE_UNBOUND")
    return {"status": "READY", "gap_rows": len(gap_rows), "sources": {key: file.identity() for key, file in files.items()}}


def build_fupan_pool(
    inputs: DatedInputs, entry: dict, target: str, observed: datetime,
) -> tuple[dict, dict[str, list]]:
    pool, rows, identities = _a_pool(inputs, entry, target, "a_d1_fupan_watchlist_pool", "pool")
    manifest_file = inputs.file(entry.get("pool_manifest"))
    csv_file = inputs.file(entry.get("pool_csv"))
    manifest = mapping(manifest_file.json(), "FUPAN_POOL_MANIFEST_INVALID")
    combined = sha256((manifest_file.sha256 + csv_file.sha256).encode("ascii")).hexdigest()
    require(pool.get("source_role") == "VERIFIED_D1_FUPAN_REVIEW" and pool.get("source_sha256") == combined
            and str(pool.get("status", "")).startswith("FUPAN_WATCHLIST_POOL_READY")
            and pool.get("status") == manifest.get("status")
            and manifest.get("fupan_pool_rule") == "AUTO_FUPAN_THEN_VIDEO_SECOND_REVIEW"
            and iso_date(manifest.get("signal_date")) == inputs.trade_date and iso_date(manifest.get("target_date")) == target
            and manifest.get("row_count") == len(rows) and manifest.get("source_paths")
            and all(manifest.get(key) is False for key in SAFETY_FLAGS if key != "research_only"),
            "FUPAN_POOL_NATIVE_MANIFEST_MISMATCH")
    try:
        generated = datetime.fromisoformat(manifest.get("generated_at", ""))
    except (TypeError, ValueError) as exc:
        raise EvidenceError("FUPAN_POOL_NATIVE_GENERATION_TIME_UNVERIFIED") from exc
    if generated.utcoffset() is None:
        generated = generated.replace(tzinfo=_BEIJING)
    require(generated.astimezone(_BEIJING).date().isoformat() == inputs.trade_date and generated <= observed,
            "FUPAN_POOL_NATIVE_GENERATION_TIME_UNVERIFIED")
    csv_rows = csv_file.csv()
    csv_codes = []
    for row in csv_rows:
        require(iso_date(row.get("target_date")) == target and iso_date(row.get("signal_date")) == inputs.trade_date,
                "FUPAN_CSV_ROW_DATE_MISMATCH")
        csv_codes.append(symbol(row.get("ts_code"), "A"))
    require(csv_codes == [row["symbol"] for row in rows], "FUPAN_MANIFEST_CSV_POOL_MEMBERSHIP_MISMATCH")
    missing = []
    evidence = {}
    for role, validate in (
        ("selector", lambda: _fupan_selector(manifest, inputs.trade_date)),
        ("video", lambda: _fupan_video(manifest, entry, inputs.trade_date)),
    ):
        try:
            evidence[role] = validate()
        except EvidenceError as exc:
            evidence[role] = {"status": "CANNOT_CONFIRM", "reason": str(exc)}
            missing.append(str(exc))
    upstream_gaps = manifest.get("cannot_confirm")
    if upstream_gaps != [] or pool.get("cannot_confirm", []) != []:
        missing.append("FUPAN_NATIVE_UPSTREAM_GAPS_REMAIN")
    return {
        "role": "FUPAN_REVIEW_BUNDLE", "status": "PARTIAL" if missing else "READY",
        "source_status": pool["status"], "source_mode": "NATIVE_INPUT_MATERIALIZATION",
        "source_identity": {**identities, "pool_manifest": manifest_file.identity(), "pool_csv": csv_file.identity()},
        "row_count": len(rows), "target_date": target, "source_generated_at": generated.isoformat(),
        "cannot_confirm": missing, "readback": evidence,
        "upstream_gap_count": len(upstream_gaps) if isinstance(upstream_gaps, list) else None, **SAFETY_FLAGS,
    }, {"rows": rows}
