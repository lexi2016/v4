"""Read the exact-date Review Core bundle for the V3.5 A-share consumer.

This module is deliberately a read-only boundary.  The Review Core bundle is
the source of the rich A-share review rows; V3.5 only validates its identity,
SHA chain, date and safety flags before projecting it into the existing API.
No other date is consulted when the requested bundle is absent or invalid.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from domains.a_share_review import build_a_share_review, validate_a_share_review
from domains.video_evidence_content import video_transcript_content
from infrastructure.data_store import _date


_SAFETY = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
_BUNDLE_SCHEMA = "review_core.review_bundle.v1"
_CURRENT_SCHEMA = "review_core.review_bundle.current.v1"
_SOURCE_ROLE = "REVIEW_CORE_BUNDLE_V1"
_SHA256 = set("0123456789abcdef")
_REVIEW_NAMESPACE_DATE = re.compile(
    r"(?<![^/\\])review(?:_bundle)?[/\\]"
    r"(?P<date>\d{8}|\d{4}[-_]\d{2}[-_]\d{2})(?=[/\\]|$)"
)
_RICH_FIELDS = (
    "summary_cards", "market_rows", "prior_plan_rows", "board_rows", "anchor_rows",
    "anchor_role_v3_rows", "intraday_handoff_rows", "catalyst_rows", "trigger_rows",
    "scenario_tree_rows", "video", "video_gap_rows", "source_status_rows",
    "formal_pool_validation", "rule_adoption_rows", "video_learning_rows",
    "cannot_confirm_items",
)


def _object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_bytes().decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Review Core evidence must be an object: {path}")
    return value


def _sha_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _valid_sha(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and set(text) <= _SHA256


def _require_safe(payload: Mapping[str, Any], label: str) -> None:
    if not isinstance(payload, Mapping):
        raise ValueError(f"invalid {label} safety flags")
    for key, expected in _SAFETY.items():
        if payload.get(key) is not expected:
            raise ValueError(f"unsafe {label} flag: {key}")
    nested = payload.get("safety_flags")
    if nested is not None and (
        not isinstance(nested, Mapping)
        or any(nested.get(key) is not expected for key, expected in _SAFETY.items())
    ):
        raise ValueError(f"unsafe {label} safety_flags")


def _standard_review_core_root() -> Path:
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "com.lexi.review-core.local"
        / "state"
        / "data"
    ).resolve()


def _root_for(data_root: Path) -> Path:
    """Resolve the Review Core data root without relying on Windows paths."""
    configured = str(os.environ.get("REVIEW_CORE_DATA_ROOT") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    candidate = Path(data_root).expanduser().resolve()
    standard = _standard_review_core_root()
    home = Path.home().resolve()
    active_v35 = home / "Library" / "Application Support" / "com.lexi.v35.local" / "state" / "data"
    project_runtime = Path(__file__).resolve().parents[1] / ".runtime" / "data"
    # The installed V3.5 runtime and this checkout's own .runtime/data are
    # consumers, not Review Core stores.  They must bridge to the one local
    # Review Core root when it exists.
    if candidate in {active_v35.resolve(), project_runtime.resolve()}:
        return standard if (standard / "review_bundle").is_dir() else candidate
    # Unit fixtures and explicitly supplied roots own their review_bundle or
    # legacy close_review_sources tree.  Never let them read real user dates.
    return candidate


def _safe_child(root: Path, relative: Any, label: str) -> Path:
    value = str(relative or "")
    if not value or Path(value).is_absolute() or ".." in Path(value).parts:
        raise ValueError(f"invalid Review Core {label} path")
    root = root.resolve()
    path = (root / value).resolve(strict=False)
    if path != root and root not in path.parents:
        raise ValueError(f"Review Core {label} path escapes data root")
    return path


def _require_receipt_safety(payload: Mapping[str, Any], label: str) -> None:
    flags = payload.get("safety_flags")
    if not isinstance(flags, Mapping) or any(
        flags.get(key) is not expected for key, expected in _SAFETY.items()
    ):
        raise ValueError(f"unsafe {label} safety_flags")


def _load_bundle(trade_date: str, data_root: Path) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, Any]]:
    target = _date(trade_date)
    root = _root_for(data_root)
    current_path = root / "review_bundle" / target / "current.json"
    current = _object(current_path)
    if current is None:
        raise FileNotFoundError(f"Review Core current pointer missing for {target}")
    if current.get("schema_version") != _CURRENT_SCHEMA or current.get("trade_date") != target:
        raise ValueError("Review Core current pointer exact-date identity mismatch")
    _require_safe(current.get("safety_flags") or {}, "Review Core current pointer")
    bundle_rel = current.get("bundle_path")
    bundle_path = _safe_child(root, bundle_rel, "bundle")
    if not bundle_path.is_file():
        raise FileNotFoundError(f"Review Core bundle missing for {target}")
    source_sha = str(current.get("bundle_sha256") or "")
    if not _valid_sha(source_sha) or _sha_bytes(bundle_path) != source_sha:
        raise ValueError("Review Core bundle SHA mismatch")
    bundle = _object(bundle_path)
    if bundle is None:
        raise ValueError("Review Core bundle is missing or invalid")
    if bundle.get("schema_version") != _BUNDLE_SCHEMA or bundle.get("trade_date") != target:
        raise ValueError("Review Core bundle exact-date identity mismatch")
    if bundle.get("run_id") != current.get("run_id"):
        raise ValueError("Review Core bundle/current run mismatch")
    _require_safe(bundle, "Review Core bundle")

    manifest_path = None
    manifest = None
    receipt_path = None
    receipt = None
    for field, schema, label in (
        ("manifest_path", "manifest_sha256", "manifest"),
        ("receipt_path", "receipt_sha256", "receipt"),
    ):
        path = _safe_child(root, current.get(field), label)
        expected = str(current.get(schema) or "")
        if not path.is_file() or not _valid_sha(expected) or _sha_bytes(path) != expected:
            raise ValueError(f"Review Core {label} SHA mismatch")
        if label == "manifest":
            manifest_path, manifest = path, _object(path)
        else:
            receipt_path, receipt = path, _object(path)
    if manifest is None or receipt is None:
        raise ValueError("Review Core manifest or receipt is invalid")
    if (
        manifest.get("schema_version") != "review_core.review_bundle.manifest.v1"
        or manifest.get("trade_date") != target
        or manifest.get("run_id") != current.get("run_id")
        or manifest.get("bundle_path") != current.get("bundle_path")
        or manifest.get("bundle_schema_version") != _BUNDLE_SCHEMA
        or manifest.get("bundle_sha256") != source_sha
    ):
        raise ValueError("Review Core manifest identity mismatch")
    _require_safe(manifest, "Review Core manifest")
    if (
        receipt.get("schema_version") != "review_core.review_bundle.receipt.v1"
        or receipt.get("trade_date") != target
        or receipt.get("run_id") != current.get("run_id")
        or receipt.get("bundle_sha256") != source_sha
        or receipt.get("manifest_sha256") != current.get("manifest_sha256")
    ):
        raise ValueError("Review Core receipt identity mismatch")
    _require_receipt_safety(receipt, "Review Core receipt")
    return bundle, current, source_sha, manifest


def review_core_a_share_bundle_required(data_root: Path, trade_date: str) -> bool:
    """Return true only when the exact requested Review Core current exists."""
    target = _date(trade_date)
    root = _root_for(Path(data_root))
    return (root / "review_bundle" / target / "current.json").is_file()


def _rows(value: Any, target: str, *, label: str = "rich rows") -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Review Core {label} must be a list")
    result: list[dict[str, Any]] = []
    for row in value:
        if not isinstance(row, Mapping):
            raise ValueError(f"Review Core {label} rows must be objects")
        copied = deepcopy(dict(row))
        row_date = copied.get("trade_date") or copied.get("review_date")
        if row_date not in (None, "") and str(row_date) != target:
            raise ValueError("Review Core rich row date does not match requested date")
        copied.setdefault("trade_date", target)
        result.append(copied)
    return result


def _empty_video(target: str, reason: str = "") -> dict[str, Any]:
    cannot_confirm = ["DAILY_VIDEO_NOT_LOCKED: exact-date video identity is missing or invalid"]
    if reason:
        cannot_confirm.append(reason)
    return {
        "status": "CANNOT_CONFIRM",
        "date_scope": "DAILY_VIDEO_NOT_LOCKED",
        "target_trade_date": target,
        "trade_date": target,
        "bv_id": "",
        "title": "",
        "upload_date": "",
        "artifact_refs": [],
        "video_input_count": 0,
        "video_augmented": False,
        "video_augmented_review_complete": False,
        "video_evidence_boundary": "EXACT_DATE_VIDEO_NOT_LOCKED",
        "cannot_confirm": cannot_confirm,
    }


def _video_has_same_day_artifacts(video: Mapping[str, Any], target: str) -> bool:
    artifact_refs = video.get("artifact_refs", [])
    if artifact_refs is None:
        artifact_refs = []
    if not isinstance(artifact_refs, list):
        return False
    for ref in artifact_refs:
        if not isinstance(ref, Mapping):
            return False
        for key in ("trade_date", "target_trade_date"):
            value = ref.get(key)
            if value not in (None, "") and str(value) != target:
                return False
        for key in ("path", "source_path", "uri", "url"):
            value = ref.get(key)
            if value in (None, ""):
                continue
            review_dates = {
                match.group("date").replace("-", "").replace("_", "")
                for match in _REVIEW_NAMESPACE_DATE.finditer(str(value))
            }
            if any(found != target for found in review_dates):
                return False
    return True


def _project_video(value: Any, target: str) -> dict[str, Any]:
    if value is None:
        return _empty_video(target)
    if not isinstance(value, Mapping):
        raise ValueError("Review Core video must be an object")
    target_trade_date = value.get("target_trade_date")
    trade_date = value.get("trade_date")
    if (
        target_trade_date in (None, "")
        or trade_date in (None, "")
        or str(target_trade_date) != target
        or str(trade_date) != target
    ):
        return _empty_video(target)
    if not _video_has_same_day_artifacts(value, target):
        return _empty_video(target)
    projected = deepcopy(dict(value))
    projected["target_trade_date"] = target
    projected["trade_date"] = target
    return projected


def _projection(bundle: Mapping[str, Any], target: str, source_sha: str, current: Mapping[str, Any], *, source_root: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    compatibility = bundle.get("compatibility")
    independent = bundle.get("independent_review")
    if not isinstance(compatibility, Mapping) or not isinstance(independent, Mapping):
        raise ValueError("Review Core compatibility or independent review missing")
    bundle_cannot_confirm = bundle.get("cannot_confirm")
    if bundle_cannot_confirm is not None and (
        not isinstance(bundle_cannot_confirm, list)
        or any(not isinstance(item, str) for item in bundle_cannot_confirm)
    ):
        raise ValueError("Review Core bundle cannot_confirm must be a list of strings")
    summary = compatibility.get("summary")
    if summary is not None and not isinstance(summary, Mapping):
        raise ValueError("Review Core compatibility summary must be an object")
    market_summary = compatibility.get("market_summary")
    if market_summary is not None and not isinstance(market_summary, Mapping):
        raise ValueError("Review Core compatibility market_summary must be an object")
    if compatibility.get("trade_date") != target or independent.get("review_date") != target:
        raise ValueError("Review Core nested review date mismatch")
    if independent.get("video_input_count") != 0 or independent.get("video_augmented") is not False:
        raise ValueError("Review Core independent review video boundary mismatch")

    cannot_items = compatibility.get("cannot_confirm_items")
    if cannot_items is not None and (
        not isinstance(cannot_items, list) or any(not isinstance(item, str) for item in cannot_items)
    ):
        raise ValueError("Review Core cannot_confirm_items must be a list of strings")
    formal_pool = compatibility.get("formal_pool_validation")
    if formal_pool is not None and not isinstance(formal_pool, Mapping):
        raise ValueError("Review Core formal_pool_validation must be an object")
    rich = {}
    for key in _RICH_FIELDS:
        if key == "video":
            rich[key] = _project_video(compatibility.get(key), target)
            rich[key].update(video_transcript_content(rich[key], target, source_root, manifest))
        elif key == "formal_pool_validation":
            rich[key] = deepcopy(dict(formal_pool or {}))
        elif key == "cannot_confirm_items":
            rich[key] = deepcopy(list(cannot_items or []))
        else:
            rich[key] = _rows(compatibility.get(key), target, label=key)
    video_cannot = rich["video"].get("cannot_confirm") if isinstance(rich["video"], Mapping) else []
    rich["cannot_confirm_items"] = list(dict.fromkeys(
        list(rich["cannot_confirm_items"])
        + [str(item) for item in (video_cannot or []) if str(item)]
    ))
    headline = compatibility.get("headline")
    if headline is not None and not isinstance(headline, str):
        raise ValueError("Review Core headline must be a string")
    cannot = [str(value) for value in (
        list(rich["cannot_confirm_items"] or [])
        + list(bundle_cannot_confirm or [])
    ) if str(value)]
    source_refs = _rows(bundle.get("source_refs"), target)
    source_refs.extend([
        {
            "source_role": _SOURCE_ROLE,
            "run_id": str(bundle.get("run_id") or ""),
            "bundle_sha256": source_sha,
            "manifest_sha256": str(current.get("manifest_sha256") or ""),
            "receipt_sha256": str(current.get("receipt_sha256") or ""),
            "bundle_path": str(current.get("bundle_path") or ""),
            "trade_date": target,
        }
    ])
    market = compatibility.get("market_regime") or (summary or {}).get("one_line") or "CANNOT_CONFIRM"
    model = {
        "schema_version": "replay_model_v1",
        "status": "INDEPENDENT_CLOSE_REVIEW_READY",
        "producer_type": "DETERMINISTIC_PYTHON",
        "producer": "REVIEW_CORE_BUNDLE",
        "review_date": target,
        "visibility_stage": "POST_CLOSE_REVIEW_ONLY",
        "semantic_model_call_count": 0,
        "model_promotion": "NO_MODEL_PROMOTED",
        "source_role": _SOURCE_ROLE,
        "source_run_id": str(bundle.get("run_id") or ""),
        "source_sha256": source_sha,
        "market_summary": deepcopy(dict(market_summary or {})),
        "board_rows": deepcopy(rich["board_rows"]),
        "anchor_role_rows": deepcopy(rich["anchor_role_v3_rows"]),
        "previous_plan_realization": "；".join(
            str(row.get("close_result") or row.get("mapped_theme") or "")
            for row in rich["prior_plan_rows"] if isinstance(row, Mapping)
        ) or "CANNOT_CONFIRM_PREVIOUS_PLAN_REALIZATION_WITHOUT_BOUND_PRIOR_PLAN",
        "target_video_review_status": str((rich["video"] or {}).get("status") or "CANNOT_CONFIRM"),
        "safety": {"SHADOW_ONLY": True, "NOT_BUY_ADVICE": True, "NO_BUY_GATE": True, "HOLDOUT_ACCESS_COUNT": 0},
        "independent_review": deepcopy(dict(independent)),
    }
    review = build_a_share_review(
        target,
        big_picture=deepcopy(rich["summary_cards"]),
        mainlines=deepcopy(_rows(compatibility.get("mainlines"), target, label="mainlines")),
        core_stocks=deepcopy(_rows(compatibility.get("core_stocks"), target)),
        observation_pool=deepcopy(rich["anchor_rows"]),
        trigger_rows=deepcopy(
            _rows(compatibility.get("next_day_trigger_tree_v2"), target)
            if isinstance(compatibility.get("next_day_trigger_tree_v2"), list)
            else rich["trigger_rows"]
        ),
        quality_gate_rows=deepcopy(rich["source_status_rows"]),
        source_sha256=source_sha,
        market_regime=str(market),
        risk_tone=str(compatibility.get("risk_tone") or "CANNOT_CONFIRM"),
        cannot_confirm=cannot,
        model_review=model,
        source_evidence=source_refs,
        source_role=_SOURCE_ROLE,
    )
    review.update(rich)
    review.update({
        "status": "MODEL_REVIEW_READY",
        "headline": headline or f"A股复盘 {target}",
        "source_run_id": str(bundle.get("run_id") or ""),
        "artifact_sha256": source_sha,
        "review_core_bundle": {
            "schema_version": _BUNDLE_SCHEMA,
            "source_role": _SOURCE_ROLE,
            "trade_date": target,
            "run_id": str(bundle.get("run_id") or ""),
            "bundle_sha256": source_sha,
            "manifest_sha256": str(current.get("manifest_sha256") or ""),
            "receipt_sha256": str(current.get("receipt_sha256") or ""),
            "bundle_path": str(current.get("bundle_path") or ""),
        },
    })
    validate_a_share_review(review)
    return review


def load_review_core_a_share_review(trade_date: str, data_root: Path) -> dict[str, Any]:
    bundle, current, source_sha, manifest = _load_bundle(trade_date, data_root)
    return _projection(bundle, _date(trade_date), source_sha, current, source_root=_root_for(data_root), manifest=manifest)


def _daily_replay(trade_date: str, review: Mapping[str, Any]) -> dict[str, Any]:
    model = review.get("model_review") if isinstance(review.get("model_review"), Mapping) else {}
    market = model.get("market_summary") if isinstance(model.get("market_summary"), Mapping) else {}
    counts = [market.get(key) for key in ("up_count", "down_count", "flat_count")]
    source_rows = sum(int(value) for value in counts) if all(isinstance(value, int) for value in counts) else None
    status = str(model.get("status") or "NOT_MATERIALIZED")
    return {
        "title": "本日每日独立复盘", "status": status, "trade_date": trade_date,
        "run_id": str(model.get("source_run_id") or model.get("run_id") or ""),
        "source_row_count": source_rows, "board_count": len(review.get("board_rows") or []),
        "anchor_count": len(review.get("anchor_role_v3_rows") or []),
        "target_video_input": int(review.get("video_input_count") or 0),
        "video_augmented": bool(review.get("video_augmented_review_complete", False)),
        "message": "本日每日独立复盘已就绪" if status == "INDEPENDENT_CLOSE_REVIEW_READY" else "本日每日独立复盘尚未物化",
    }


def _legacy_video_layer(data_root: Path, trade_date: str) -> dict[str, Any]:
    base = data_root / "close_review_sources" / trade_date / "bilibili"
    session = _object(base / "video_session.json")
    gap = _object(base / "video_gap" / "video_gap_audit.json")
    if session is None or gap is None:
        return {"title": "目标交易日视频差距审计", "status": "NOT_MATERIALIZED", "target_trade_date": trade_date, "targeted_spotcheck_count": 0, "ready_stock_mention_count": 0, "targeted_stock_mention_count": 0, "stock_mentions": [], "message": "目标交易日视频差距尚未物化", "spotcheck_message": "没有已确认的定点抽查片段"}
    if session.get("target_trade_date") != trade_date or gap.get("trade_date") != trade_date:
        raise ValueError("review video evidence date mismatch")
    _require_safe(session, "video session")
    _require_safe(gap, "video gap")
    mentions = [dict(row) for row in gap.get("gap_rows") or [] if isinstance(row, Mapping) and str(row.get("row_id") or "").startswith("S")]
    targeted = int(session.get("targeted_spotcheck_count") or 0)
    if sum(row.get("status") == "ASR_SEGMENT_SPOTCHECK_REQUIRED" for row in mentions) != targeted:
        raise ValueError("review video targeted spotcheck count mismatch")
    return {
        "title": "目标交易日视频差距审计", "status": str(gap.get("status") or "NOT_MATERIALIZED"),
        "target_trade_date": trade_date, "bv_id": str(session.get("bv_id") or ""),
        "video_title": str(session.get("title") or ""), "upload_date": str(session.get("upload_date") or ""),
        "date_scope": str(session.get("date_scope") or ""), "asr_status": str(session.get("asr_status") or ""),
        "asr_segment_count": int(session.get("asr_segment_count") or 0), "gap_row_count": int(gap.get("gap_row_count") or 0),
        "closed_rows": int(gap.get("closed_rows") or 0), "targeted_spotcheck_count": targeted,
        "ready_stock_mention_count": sum(row.get("status") == "ASR_STOCKDICT_OBSERVATION_READY" for row in mentions),
        "targeted_stock_mention_count": sum(row.get("status") == "ASR_SEGMENT_SPOTCHECK_REQUIRED" for row in mentions),
        "stock_mentions": mentions, "message": f"{trade_date} 目标交易日复盘", "spotcheck_message": f"仅 {targeted} 个异常片段待定点抽查" if targeted else "股票词典命中均为机器范围观察证据",
    }


def load_review_evidence_layers(data_root: Path, trade_date: str, review: Mapping[str, Any], *, allow_legacy_fixture: bool = False) -> dict[str, Any]:
    target = _date(trade_date)
    if review.get("trade_date") != target:
        raise ValueError("review evidence layer date mismatch")
    try:
        loaded = load_review_core_a_share_review(target, data_root)
        daily = _daily_replay(target, loaded)
        video = deepcopy(dict(loaded.get("video") or {}))
        video.setdefault("target_trade_date", target)
    except (FileNotFoundError, ValueError):
        daily = _daily_replay(target, review)
        legacy_fixture = Path(data_root) / "close_review_sources"
        video = _legacy_video_layer(Path(data_root), target) if allow_legacy_fixture or legacy_fixture.is_dir() else {"title": "目标交易日视频差距审计", "status": "NOT_MATERIALIZED", "target_trade_date": target, "targeted_spotcheck_count": 0, "ready_stock_mention_count": 0, "targeted_stock_mention_count": 0, "stock_mentions": [], "message": "目标交易日视频差距尚未物化", "spotcheck_message": "没有已确认的定点抽查片段"}
    return {
        "schema_version": "v3_5.review_evidence_layers.v1", "trade_date": target,
        "historical_strict_audit": {"title": "历史严格审计样本（防泄漏基准）", "status": "HISTORICAL_SAMPLE_NOT_AVAILABLE_FOR_DATE", "trade_date": target, "available_dates": []},
        "daily_independent_replay": daily, "video_gap_audit": video, **_SAFETY,
    }


def list_review_evidence_dates(data_root: Path) -> list[str]:
    supplied = Path(data_root).expanduser().resolve()
    if (supplied / "close_review_sources").is_dir() and not (supplied / "review_bundle").is_dir():
        dates: list[str] = []
        for candidate in supplied.joinpath("close_review_sources").iterdir():
            try:
                target = _date(candidate.name)
                layer = _legacy_video_layer(supplied, target)
                if layer.get("status") == "VIDEO_GAP_AUDIT_READY":
                    dates.append(target)
            except (OSError, ValueError):
                continue
        return sorted(set(dates), reverse=True)
    root = _root_for(supplied)
    review_root = root / "review_bundle"
    if not review_root.is_dir():
        return []
    dates: list[str] = []
    for candidate in review_root.iterdir():
        if not candidate.is_dir():
            continue
        try:
            target = _date(candidate.name)
            if (candidate / "current.json").is_file():
                _load_bundle(target, data_root)
                dates.append(target)
        except (OSError, ValueError, FileNotFoundError):
            continue
    return sorted(set(dates), reverse=True)


def list_video_gap_audit_dates(data_root: Path) -> list[str]:
    return list_review_evidence_dates(data_root)
