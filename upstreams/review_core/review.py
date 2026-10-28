"""Immutable ReviewBundleV1 producer and strict read-only oracle loader.

The bundle is an integration/acceptance layer only.  It preserves the
independent replay output and places shared Review Core video evidence in the
separate video-gap layer; it never changes model scores or promotes video into
independent market facts.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping

from .core import (
    DEFAULT_DATA_ROOT,
    EvidenceValidationError,
    inspect_bundle,
    sha256_file,
)


BUNDLE_SCHEMA_VERSION = "review_core.review_bundle.v1"
BUNDLE_MANIFEST_SCHEMA_VERSION = "review_core.review_bundle.manifest.v1"
BUNDLE_RECEIPT_SCHEMA_VERSION = "review_core.review_bundle.receipt.v1"
BUNDLE_CURRENT_SCHEMA_VERSION = "review_core.review_bundle.current.v1"
COMPATIBILITY_SCHEMA_VERSION = "review_core.v3_compatibility.v1"
FULL_MARKET_SCOPE = "FULL_MARKET"
FORMAL_POOL_PROXY_SCOPE = "FORMAL_POOL_PROXY"
MARKET_UNIVERSE_SCOPES = frozenset({FULL_MARKET_SCOPE, FORMAL_POOL_PROXY_SCOPE})

COMPATIBILITY_FIELDS = (
    "status",
    "display_status",
    "data_completeness",
    "summary",
    "summary_cards",
    "formal_pool_validation",
    "prior_plan_rows",
    "intraday_handoff_rows",
    "anchor_role_v3_rows",
    "scenario_tree_rows",
    "rule_adoption_rows",
    "board_rows",
    "market_rows",
    "news_article_rows",
    "news_event_rows",
    "news_research_hit_rows",
    "news_event_source_paths",
    "morning_news_acceptance",
    "anchor_rows",
    "catalyst_rows",
    "trigger_rows",
    "source_status_rows",
    "cannot_confirm_items",
    "video",
    "video_gap_rows",
    "video_learning_rows",
    "trade_date",
    "schema_version",
    "safety_flags",
    "independent_review",
)

DEFAULT_V3_ARTIFACT_ROOT = Path(
    r"C:\Users\huang\Desktop\学习\v3_system\40_artifacts\runtime_debug"
)
DEFAULT_REPLAY_ROOT = Path(
    r"C:\Users\huang\Desktop\学习\v3_system\复盘\data\daily_replay_research_v1"
)
DEFAULT_VIDEO_DATA_ROOT = DEFAULT_DATA_ROOT

SAFETY_FLAGS = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}

LAYER_NAMES = (
    "今天看什么",
    "昨日预案兑现",
    "全板块覆盖",
    "主线支线失败",
    "龙头容量风险后排",
    "明日观察升级失效",
    "视频差距红队",
    "证据验收附录",
)


class ReviewBundleValidationError(EvidenceValidationError):
    """Raised when a ReviewBundleV1 input or pointer is not safe to consume."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewBundleValidationError(f"invalid JSON source: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReviewBundleValidationError(f"JSON source is not an object: {path}")
    return value


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _write_json_atomic(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary_name = ""
    try:
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if temporary_name and Path(temporary_name).exists():
            Path(temporary_name).unlink()
    return hashlib.sha256(encoded).hexdigest()


def _date8(value: str) -> str:
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) != 8:
        raise ReviewBundleValidationError(f"invalid review trade date: {value!r}")
    try:
        from datetime import datetime

        datetime.strptime(digits, "%Y%m%d")
    except ValueError as exc:
        raise ReviewBundleValidationError(f"invalid review trade date: {value!r}") from exc
    return digits


def _source_ref(path: Path, *, kind: str) -> dict[str, Any]:
    path = path.absolute()
    if not path.is_file():
        raise ReviewBundleValidationError(f"required source missing: {path}")
    return {"kind": kind, "path": str(path), "sha256": sha256_file(path)}


def _payload_path(
    trade_date: str,
    *,
    v3_artifact_root: Path | str | None,
    v3_payload_path: Path | str | None,
) -> Path:
    target = _date8(trade_date)
    if v3_payload_path is not None:
        path = Path(v3_payload_path).absolute()
        if path.name != f"fupan_payload_{target}.json":
            raise ReviewBundleValidationError("V3 payload path is not exact-date")
        return path
    root = (Path(v3_artifact_root) if v3_artifact_root is not None else DEFAULT_V3_ARTIFACT_ROOT).absolute()
    return root / f"{target}_fupan_page_complete" / f"fupan_payload_{target}.json"


def _replay_review_path(
    trade_date: str,
    *,
    replay_root: Path | str | None,
    replay_review_path: Path | str | None,
) -> Path:
    target = _date8(trade_date)
    if replay_review_path is not None:
        path = Path(replay_review_path).absolute()
        if path.name != "independent_semantic_review.v1.json":
            raise ReviewBundleValidationError("independent replay path has unexpected filename")
        return path
    root = (Path(replay_root) if replay_root is not None else DEFAULT_REPLAY_ROOT).absolute()
    date_root = root / target
    direct = date_root / "local_semantic_model" / "independent_semantic_review.v1.json"
    if direct.is_file():
        return direct
    candidates = sorted(date_root.glob(f"REPLAY_RESEARCH_V1_{target}_*/local_semantic_model/independent_semantic_review.v1.json"))
    if not candidates:
        raise ReviewBundleValidationError(f"exact-date independent replay missing: {target}")
    if len(candidates) != 1:
        raise ReviewBundleValidationError(f"ambiguous exact-date independent replay: {target}")
    return candidates[0]


def _validate_v3_payload(payload: dict[str, Any], trade_date: str) -> None:
    if str(payload.get("trade_date") or "") != trade_date:
        raise ReviewBundleValidationError("V3 payload date mismatch")
    if not payload.get("status"):
        raise ReviewBundleValidationError("V3 payload status missing")
    scope = str(payload.get("market_scope") or "").strip()
    if scope not in MARKET_UNIVERSE_SCOPES:
        raise ReviewBundleValidationError("V3 payload market_scope missing or unrecognized")
    expected_completeness = "FULL_MARKET_VERIFIED" if scope == FULL_MARKET_SCOPE else "PROXY_ONLY_CANNOT_CONFIRM"
    if str(payload.get("market_completeness") or "") != expected_completeness:
        raise ReviewBundleValidationError("V3 payload market_completeness mismatch")


def _market_contract(payload: Mapping[str, Any], *, allow_legacy: bool = False) -> tuple[str, str]:
    scope = str(payload.get("market_scope") or "").strip()
    if scope not in MARKET_UNIVERSE_SCOPES:
        if allow_legacy and not scope and not payload.get("market_completeness"):
            return "LEGACY_UNVERIFIED", "LEGACY_UNVERIFIED"
        raise ReviewBundleValidationError("market_scope missing or unrecognized")
    completeness = str(payload.get("market_completeness") or "").strip()
    expected = "FULL_MARKET_VERIFIED" if scope == FULL_MARKET_SCOPE else "PROXY_ONLY_CANNOT_CONFIRM"
    if completeness != expected:
        raise ReviewBundleValidationError("market_completeness mismatch")
    return scope, completeness


def _validate_independent_review(review: dict[str, Any], trade_date: str) -> None:
    if review.get("schema_version") != "local_fupan_independent_review.v1":
        raise ReviewBundleValidationError("independent replay schema mismatch")
    if str(review.get("review_date") or "") != trade_date:
        raise ReviewBundleValidationError("independent replay date mismatch")
    boundary = review.get("boundary")
    if not isinstance(boundary, dict):
        raise ReviewBundleValidationError("independent replay boundary missing")
    required_true = ("research_only", "not_buy_advice")
    required_false = ("target_video_used", "future_result_used", "dev_used", "holdout_used", "model_promoted")
    for name in required_true:
        if boundary.get(name) is not True:
            raise ReviewBundleValidationError(f"unsafe independent boundary: {name}")
    for name in required_false:
        if boundary.get(name) is not False:
            raise ReviewBundleValidationError(f"unsafe independent boundary: {name}")


def _video_source_refs(video_data_root: Path | str | None, trade_date: str) -> list[dict[str, Any]]:
    if video_data_root is None:
        return []
    root = Path(video_data_root).absolute()
    current_path = root / "review" / trade_date / "current.json"
    if not current_path.is_file():
        return []
    refs = [_source_ref(current_path, kind="review_core_video_current")]
    current = _read_json(current_path)
    for key, kind in (("manifest_path", "review_core_video_manifest"), ("receipt_path", "review_core_video_receipt")):
        relative = current.get(key)
        if not isinstance(relative, str) or not relative:
            continue
        safe = Path(relative)
        if safe.is_absolute() or ".." in safe.parts:
            raise ReviewBundleValidationError("video current pointer contains unsafe path")
        candidate = root / safe
        if candidate.is_file():
            refs.append(_source_ref(candidate, kind=kind))
    return refs


def _shared_video_gap_rows(
    trade_date: str,
    *,
    video_data_root: Path | str | None,
    manifest: dict[str, Any],
    video: dict[str, Any],
) -> list[Any]:
    """Load layer-7 rows only from the validated Review Core gap artifact.

    A missing reference is treated as an empty test seam, never as permission
    to fall back to the V3 payload.  Real ``inspect_bundle`` manifests always
    carry the required ``video_gap_audit`` reference and validate its SHA
    before this adapter is reached.
    """

    if video.get("status") != "READY":
        return []
    refs = manifest.get("artifact_refs")
    if not isinstance(refs, list):
        return []
    matches = [ref for ref in refs if isinstance(ref, dict) and ref.get("kind") == "video_gap_audit"]
    if not matches:
        return []
    if len(matches) != 1:
        raise ReviewBundleValidationError("ambiguous Review Core video gap artifact")
    ref = matches[0]
    relative = ref.get("path")
    if not isinstance(relative, str) or not relative:
        raise ReviewBundleValidationError("Review Core video gap artifact path missing")
    safe = Path(relative)
    if safe.is_absolute() or ".." in safe.parts:
        raise ReviewBundleValidationError("unsafe Review Core video gap artifact path")
    root = (Path(video_data_root) if video_data_root is not None else DEFAULT_VIDEO_DATA_ROOT).absolute()
    candidate = (root / safe).absolute()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ReviewBundleValidationError("Review Core video gap artifact escapes data root") from exc
    if not candidate.is_file():
        raise ReviewBundleValidationError("Review Core video gap artifact missing")
    expected_sha = str(ref.get("sha256") or "")
    if not expected_sha or sha256_file(candidate) != expected_sha:
        raise ReviewBundleValidationError("Review Core video gap artifact SHA mismatch")
    gap = _read_json(candidate)
    if gap.get("schema_version") != "ReviewCoreVideoGapAuditV1":
        raise ReviewBundleValidationError("Review Core video gap artifact schema mismatch")
    if gap.get("trade_date") != trade_date or gap.get("bv_id") != video.get("bv_id"):
        raise ReviewBundleValidationError("Review Core video gap artifact identity mismatch")
    rows = gap.get("gap_rows")
    if not isinstance(rows, list):
        raise ReviewBundleValidationError("Review Core video gap rows missing")
    if gap.get("gap_row_count") != len(rows) or gap.get("gap_row_count") != video.get("gap_row_count"):
        raise ReviewBundleValidationError("Review Core video gap row count mismatch")
    if gap.get("targeted_spotcheck_count") != video.get("targeted_spotcheck_count"):
        raise ReviewBundleValidationError("Review Core video targeted spotcheck mismatch")
    return copy.deepcopy(rows)


def _map_video(
    trade_date: str,
    *,
    video_data_root: Path | str | None,
    v3_payload: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        manifest = inspect_bundle(trade_date, video_data_root or DEFAULT_VIDEO_DATA_ROOT)
    except (EvidenceValidationError, OSError, ValueError) as exc:
        return (
            {
                "status": "CANNOT_CONFIRM",
                "trade_date": trade_date,
                "target_trade_date": trade_date,
                "bv_id": "",
                "title": "",
                "upload_date": "",
                "date_scope": "DAILY_VIDEO_NOT_LOCKED",
                "discovery_status": "DAILY_VIDEO_NOT_LOCKED",
                "capture_status": "NOT_RUN",
                "asr_status": "NOT_RUN",
                "asr_segment_count": 0,
                "gap_status": "DAILY_VIDEO_NOT_LOCKED",
                "gap_row_count": 0,
                "targeted_spotcheck_count": 0,
                "media_sha256": "",
                "transcript_sha256": "",
                "artifact_refs": [],
                "cannot_confirm": [str(exc)],
                "video_input_count": 0,
                "video_augmented": False,
                **SAFETY_FLAGS,
            },
            [],
        )
    if str(manifest.get("trade_date") or "") != trade_date or str(manifest.get("target_trade_date") or "") != trade_date:
        raise ReviewBundleValidationError("Review Core video manifest exact-date mismatch")
    for name, expected in SAFETY_FLAGS.items():
        if manifest.get(name) is not expected:
            raise ReviewBundleValidationError(f"unsafe Review Core video flag: {name}")
    date_scope = str(manifest.get("date_scope") or "DAILY_VIDEO_NOT_LOCKED")
    capture_status = str(manifest.get("capture_status") or "NOT_RUN")
    asr_status = str(manifest.get("asr_status") or "NOT_RUN")
    try:
        asr_segment_count = int(manifest.get("asr_segment_count") or 0)
    except (TypeError, ValueError):
        asr_segment_count = 0
    capture_usable = capture_status not in {"NOT_RUN", "ACCESS_BLOCKED", "CAPTURE_NOT_AVAILABLE", "WRONG_UPLOADER"}
    asr_usable = asr_status in {"ASR_REVIEW_REQUIRED", "TRANSCRIPT_READY", "READY"} and asr_segment_count > 0
    has_locked_video = (
        bool(str(manifest.get("bv_id") or ""))
        and date_scope != "DAILY_VIDEO_NOT_LOCKED"
        and capture_usable
        and asr_usable
    )
    cannot_confirm = list(manifest.get("cannot_confirm") or [])
    if not has_locked_video and "exact-date video is not locked" not in cannot_confirm:
        cannot_confirm.append("exact-date video is not locked")
    if not capture_usable and "video capture is not usable" not in cannot_confirm:
        cannot_confirm.append("video capture is not usable")
    if not asr_usable and "ASR transcript is not usable" not in cannot_confirm:
        cannot_confirm.append("ASR transcript is not usable")
    video = {
        "status": "READY" if has_locked_video else "CANNOT_CONFIRM",
        "trade_date": trade_date,
        "target_trade_date": trade_date,
        "bv_id": str(manifest.get("bv_id") or ""),
        "title": str(manifest.get("title") or ""),
        "upload_date": str(manifest.get("upload_date") or ""),
        "date_scope": date_scope,
        "discovery_status": str(manifest.get("discovery_status") or "DAILY_VIDEO_NOT_LOCKED"),
        "capture_status": capture_status,
        "asr_status": asr_status,
        "asr_segment_count": asr_segment_count,
        "gap_status": str(manifest.get("gap_status") or "DAILY_VIDEO_NOT_LOCKED"),
        "gap_row_count": int(manifest.get("gap_row_count") or 0),
        "targeted_spotcheck_count": int(manifest.get("targeted_spotcheck_count") or 0),
        "media_sha256": str(manifest.get("media_sha256") or ""),
        "transcript_sha256": str(manifest.get("transcript_sha256") or ""),
        "artifact_refs": copy.deepcopy(manifest.get("artifact_refs") or []),
        "cannot_confirm": cannot_confirm,
        "video_input_count": 0,
        "video_augmented": False,
        "video_evidence_boundary": "ENHANCEMENT_ONLY_INDEPENDENT_REVIEW_NOT_VIDEO_AUGMENTED",
        **SAFETY_FLAGS,
    }
    gap_rows = _shared_video_gap_rows(
        trade_date,
        video_data_root=video_data_root,
        manifest=manifest,
        video=video,
    )
    return video, gap_rows if has_locked_video else []


def _layer(index: int, name: str, rows: Iterable[Any], *, status: str = "READY", **metadata: Any) -> dict[str, Any]:
    materialized = copy.deepcopy(list(rows))
    result = {
        "index": index,
        "name": name,
        "status": status,
        "row_count": len(materialized),
        "rows": materialized,
    }
    result.update(copy.deepcopy(metadata))
    return result


def _mainline_rows(board_rows: list[Any]) -> list[dict[str, Any]]:
    mapped: list[dict[str, Any]] = []
    for row in board_rows:
        if not isinstance(row, dict):
            mapped.append({"source_row": copy.deepcopy(row), "role": "UNCLASSIFIED", "cannot_confirm": ["board row is not an object"]})
            continue
        mapped.append(
            {
                "direction": row.get("section") or row.get("board") or row.get("board_name") or "",
                "role": row.get("today_role") or row.get("role") or "UNCLASSIFIED",
                "anchors": copy.deepcopy(row.get("anchors") or []),
                "local_evidence": row.get("local_evidence", ""),
                "cannot_confirm": copy.deepcopy(row.get("cannot_confirm") or []),
                "source_row": copy.deepcopy(row),
            }
        )
    return mapped


def _independent_view(review: dict[str, Any]) -> dict[str, Any]:
    # Preserve independent fields verbatim, then append immutable boundary fields.
    result = copy.deepcopy(review)
    result["video_input_count"] = 0
    result["video_augmented"] = False
    result["video_boundary"] = "VIDEO_ONLY_LAYER_7_ENHANCEMENT"
    return result


def _independent_v3_projection(
    trade_date: str,
    replay: Mapping[str, Any],
    *,
    market_scope: str,
) -> dict[str, Any]:
    """Project independent replay into the read-only V3 page's field shape.

    The page consumes legacy names, but the values must come from the validated
    independent replay.  In particular, this adapter never reconstructs a
    market conclusion from page row counts or from the V3 payload itself.
    """

    def text(value: Any, default: str = "") -> str:
        if isinstance(value, str):
            return value.strip() or default
        if isinstance(value, (list, tuple)):
            values = [str(item).strip() for item in value if str(item).strip()]
            return "；".join(values) or default
        if value is None:
            return default
        return str(value).strip() or default

    def rows(value: Any) -> list[dict[str, Any]]:
        return [copy.deepcopy(row) for row in value if isinstance(row, dict)] if isinstance(value, list) else []

    market_judgment = replay.get("market_judgment") if isinstance(replay.get("market_judgment"), dict) else {}
    market_conclusion = text(market_judgment.get("conclusion"), "独立复盘结论待补，保持观察。")
    market_phase = text(market_judgment.get("market_phase"), "CANNOT_CONFIRM")
    market_counterevidence = rows(market_judgment.get("counterevidence"))
    market_evidence_refs = copy.deepcopy(market_judgment.get("evidence_refs") or [])

    mainline_rows: list[dict[str, Any]] = []
    for source in rows(replay.get("board_conclusions")):
        board = text(source.get("board_name") or source.get("board") or source.get("section"), "CANNOT_CONFIRM")
        role = text(source.get("role") or source.get("board_role"), "UNCLASSIFIED")
        evidence = text(source.get("conclusion") or source.get("evidence"), "CANNOT_CONFIRM")
        counterevidence = copy.deepcopy(source.get("counterevidence") or [])
        mainline_rows.append(
            {
                "board": board,
                "board_name": board,
                "role": role,
                "board_role": role,
                "evidence": evidence,
                "local_evidence": evidence,
                "counterevidence": counterevidence,
                "cannot_confirm": copy.deepcopy(counterevidence),
                "evidence_refs": copy.deepcopy(source.get("evidence_refs") or []),
                "trade_date": trade_date,
            }
        )

    role_names = {"risk", "risk_mainline", "risk_anchor", "weak_branch", "weaker", "failure"}
    risk_rows = [row for row in mainline_rows if str(row.get("role", "")).lower() in role_names]
    if not risk_rows:
        risk_rows = [
            {
                "board": "全市场风险线" if market_scope == FULL_MARKET_SCOPE else "正式池代理风险线",
                "board_name": "全市场风险线" if market_scope == FULL_MARKET_SCOPE else "正式池代理风险线",
                "role": "RISK_MAINLINE",
                "board_role": "RISK_MAINLINE",
                "risk": text(replay.get("abstain_reason"), "保持观察；未建立正式核心票。"),
                "evidence": market_conclusion,
                "local_evidence": market_conclusion,
                "counterevidence": copy.deepcopy(market_counterevidence),
                "cannot_confirm": copy.deepcopy(market_counterevidence),
                "evidence_refs": market_evidence_refs,
                "trade_date": trade_date,
            }
        ]
    layered_board_rows = copy.deepcopy(mainline_rows) + copy.deepcopy(risk_rows)

    observations = rows(replay.get("tomorrow_observation"))
    observation_by_stock: dict[str, dict[str, Any]] = {}
    for observation in observations:
        subject = text(observation.get("subject"))
        stock_name = subject.rsplit(" / ", 1)[-1] if " / " in subject else subject
        if stock_name:
            observation_by_stock[stock_name] = observation

    stock_rows: list[dict[str, Any]] = []
    for source in rows(replay.get("stock_role_conclusions")):
        stock_name = text(source.get("stock_name") or source.get("name"), "CANNOT_CONFIRM")
        stock_code = text(source.get("stock_code") or source.get("code"))
        observation = observation_by_stock.get(stock_name, {})
        subject = text(observation.get("subject"))
        board = subject.split(" / ", 1)[0] if " / " in subject else text(source.get("board_name") or source.get("board"))
        role = text(source.get("role") or source.get("role_type"), "UNCLASSIFIED")
        conclusion = text(source.get("conclusion") or source.get("evidence"), "CANNOT_CONFIRM")
        invalidation = text(source.get("invalidation") or observation.get("downgrade_trigger"), "CANNOT_CONFIRM")
        stock_rows.append(
            {
                "stock_name": stock_name,
                "stock_code": stock_code,
                "name": stock_name,
                "code": stock_code,
                "board": board,
                "board_name": board,
                "role": role,
                "role_type": role,
                "primary_role": role,
                "role_explanation": conclusion,
                "local_evidence": conclusion,
                "evidence": conclusion,
                "why_this_role": conclusion,
                "invalidation": invalidation,
                "cannot_confirm": invalidation,
                "evidence_refs": copy.deepcopy(source.get("evidence_refs") or []),
                "trade_date": trade_date,
            }
        )

    trigger_rows: list[dict[str, Any]] = []
    for source in observations:
        trigger_rows.append(
            {
                "direction": text(source.get("subject"), "次日观察"),
                "upgrade": text(source.get("upgrade_trigger"), "下一交易日真实价量证据确认后再升级。"),
                "invalidation": text(source.get("downgrade_trigger"), "证据不足时保持观察。"),
                "trade_date": trade_date,
            }
        )

    first_trigger = trigger_rows[0] if trigger_rows else {}
    board_text = "；".join(text(row.get("board")) for row in mainline_rows[:4] if text(row.get("board"))) or market_conclusion
    stock_text = "、".join(text(row.get("stock_name")) for row in stock_rows[:8] if text(row.get("stock_name")))
    scope_title = "全市场宽度" if market_scope == FULL_MARKET_SCOPE else "正式池代理范围"
    first_screen_big_picture = [
        {"title": "指数阶段", "value": market_phase},
        {"title": scope_title, "value": market_conclusion},
        {"title": "今日主线与风险线", "value": board_text},
        {"title": "核心锚与风险锚", "value": stock_text or "CANNOT_CONFIRM"},
        {"title": "明天先看什么", "value": text(first_trigger.get("upgrade"), "下一交易日真实价量证据确认后再升级。")},
        {"title": "升级条件", "value": text(first_trigger.get("upgrade"), "下一交易日真实价量证据确认后再升级。")},
        {"title": "失效条件", "value": text(first_trigger.get("invalidation"), "证据不足时保持观察。")},
    ]
    localized_role_rows = [
        {
            "股票": row.get("stock_name", ""),
            "代码": row.get("stock_code", ""),
            "板块": row.get("board", ""),
            "角色": row.get("primary_role", ""),
            "证据": row.get("role_explanation", ""),
            "边界": row.get("invalidation", ""),
        }
        for row in stock_rows
    ]
    risk_tone = text(replay.get("abstain_reason"), "保持观察")
    customer_digest = {
        "headline": market_conclusion,
        "market_regime": market_phase,
        "risk_tone": risk_tone,
        "as_of": trade_date,
        "mainlines": copy.deepcopy(layered_board_rows),
        "core_stocks": copy.deepcopy(stock_rows),
    }
    return {
        "headline": market_conclusion,
        "market_regime": market_phase,
        "risk_tone": risk_tone,
        "first_screen_big_picture": first_screen_big_picture,
        "mainline_board": layered_board_rows,
        "risk_mainline": risk_rows,
        "stock_roles": copy.deepcopy(stock_rows),
        "localized_role_rows": localized_role_rows,
        "next_day_trigger_tree_v2": trigger_rows,
        "big_picture": copy.deepcopy(first_screen_big_picture),
        "mainlines": copy.deepcopy(layered_board_rows),
        "core_stocks": copy.deepcopy(stock_rows),
        "next_day_trigger_tree": copy.deepcopy(trigger_rows),
        "customer_digest": customer_digest,
    }


def _compatibility_dto(
    trade_date: str,
    *,
    v3_payload: dict[str, Any],
    replay: dict[str, Any],
    video: dict[str, Any],
    video_gap_rows: list[Any],
    source_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Embed the read-only V3-compatible DTO without retaining V3 as a source.

    Independent review fields are copied as data, while every video value is
    derived from the exact shared Review Core manifest and gap artifact.
    """

    def payload_value(name: str, default: Any) -> Any:
        value = v3_payload.get(name)
        return copy.deepcopy(value if value is not None else default)

    market_scope, market_completeness = _market_contract(v3_payload)
    data_completeness = payload_value("data_completeness", {})
    if not isinstance(data_completeness, dict):
        data_completeness = {}
    data_completeness["market_scope"] = market_scope
    data_completeness["market_completeness"] = market_completeness

    independent_projection = _independent_v3_projection(
        trade_date,
        replay,
        market_scope=market_scope,
    )
    shared_learning_rows: list[dict[str, Any]] = []
    if video.get("status") == "READY":
        shared_learning_rows = [
            {
                "source": "ReviewCoreVideoEvidenceV1.layer7",
                "trade_date": trade_date,
                "bv_id": video.get("bv_id", ""),
                "date_scope": video.get("date_scope", ""),
                "asr_status": video.get("asr_status", ""),
                "asr_segment_count": video.get("asr_segment_count", 0),
                "gap_status": video.get("gap_status", ""),
                "gap_row_count": video.get("gap_row_count", 0),
                "targeted_spotcheck_count": video.get("targeted_spotcheck_count", 0),
                "status": video.get("status", ""),
            }
        ]
    compatibility = {
        "schema_version": COMPATIBILITY_SCHEMA_VERSION,
        "trade_date": trade_date,
        "status": payload_value("status", "CANNOT_CONFIRM"),
        "display_status": payload_value("display_status", payload_value("status", "CANNOT_CONFIRM")),
        "data_completeness": data_completeness,
        "market_scope": market_scope,
        "market_completeness": market_completeness,
        "summary": payload_value("summary", {}),
        "summary_cards": payload_value("summary_cards", []),
        "formal_pool_validation": payload_value("formal_pool_validation", {}),
        "prior_plan_rows": payload_value("prior_plan_rows", []),
        "intraday_handoff_rows": payload_value("intraday_handoff_rows", []),
        "anchor_role_v3_rows": payload_value("anchor_role_v3_rows", []),
        "scenario_tree_rows": payload_value("scenario_tree_rows", []),
        "rule_adoption_rows": payload_value("rule_adoption_rows", []),
        "board_rows": payload_value("board_rows", []),
        "market_rows": payload_value("market_rows", []),
        "news_article_rows": payload_value("news_article_rows", []),
        "news_event_rows": payload_value("news_event_rows", []),
        "news_research_hit_rows": payload_value("news_research_hit_rows", []),
        "news_event_source_paths": payload_value("news_event_source_paths", {}),
        "morning_news_acceptance": payload_value("morning_news_acceptance", {}),
        "anchor_rows": payload_value("anchor_rows", []),
        "catalyst_rows": payload_value("catalyst_rows", []),
        "trigger_rows": payload_value("trigger_rows", []),
        "source_status_rows": payload_value("source_status_rows", []),
        "cannot_confirm_items": payload_value("cannot_confirm_items", []),
        "video": copy.deepcopy(video),
        "video_gap_rows": copy.deepcopy(video_gap_rows),
        "video_learning_rows": shared_learning_rows,
        "independent_review": _independent_view(replay),
        "source_refs": copy.deepcopy(source_refs),
        "video_input_count": 0,
        "video_augmented": False,
        "video_boundary": "VIDEO_ONLY_LAYER_7_ENHANCEMENT",
        **independent_projection,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "safety_flags": dict(SAFETY_FLAGS),
    }
    return compatibility


def _implementation_hashes() -> dict[str, dict[str, str]]:
    import review_core.core as core_module

    return {
        "review.py": {"path": str(Path(__file__).absolute()), "sha256": sha256_file(Path(__file__))},
        "core.py": {"path": str(Path(core_module.__file__).absolute()), "sha256": sha256_file(Path(core_module.__file__))},
    }


def _safe_bundle_paths(output_root: Path, trade_date: str, run_id: str) -> dict[str, Path]:
    relative = f"review_bundle/{trade_date}/runs/{run_id}"
    return {
        "bundle_root": output_root / "review_bundle" / trade_date,
        "run_dir": output_root / relative,
        "current_path": output_root / "review_bundle" / trade_date / "current.json",
        "run_rel": Path(relative),
    }


def _bundle_quality(bundle: Mapping[str, Any]) -> tuple[int, int, int, int, int]:
    """Return an evidence ordering used only for exact-date current CAS."""

    return (
        1 if bundle.get("status") == "READY" else 0,
        1 if bundle.get("market_scope") == FULL_MARKET_SCOPE else 0,
        1 if bundle.get("market_completeness") == "FULL_MARKET_VERIFIED" else 0,
        1 if isinstance(bundle.get("video"), Mapping) and bundle["video"].get("status") == "READY" else 0,
        len(bundle.get("source_refs") or []) if isinstance(bundle.get("source_refs"), list) else 0,
    )


def _current_pointer_for_run(root: Path, trade_date: str, run_id: str) -> dict[str, Any]:
    """Build a pointer from an immutable run without trusting its current pointer."""

    paths = _safe_bundle_paths(root, trade_date, run_id)
    bundle_path = paths["run_dir"] / "review_bundle.json"
    manifest_path = paths["run_dir"] / "manifest.json"
    receipt_path = paths["run_dir"] / "receipt.json"
    if not all(path.is_file() for path in (bundle_path, manifest_path, receipt_path)):
        raise ReviewBundleValidationError(f"immutable review bundle run is incomplete: {run_id}")
    bundle = _read_json(bundle_path)
    manifest = _read_json(manifest_path)
    _read_json(receipt_path)
    return {
        "schema_version": BUNDLE_CURRENT_SCHEMA_VERSION,
        "trade_date": trade_date,
        "run_id": run_id,
        "run_path": paths["run_rel"].as_posix(),
        "bundle_path": f"{paths['run_rel'].as_posix()}/review_bundle.json",
        "manifest_path": f"{paths['run_rel'].as_posix()}/manifest.json",
        "receipt_path": f"{paths['run_rel'].as_posix()}/receipt.json",
        "bundle_sha256": sha256_file(bundle_path),
        "manifest_sha256": sha256_file(manifest_path),
        "receipt_sha256": sha256_file(receipt_path),
        "input_digest": bundle.get("input_digest") or manifest.get("input_digest"),
        "market_scope": bundle.get("market_scope") or manifest.get("market_scope"),
        "market_completeness": bundle.get("market_completeness") or manifest.get("market_completeness"),
        "safety_flags": dict(SAFETY_FLAGS),
    }


def _inspect_run_bundle(root: Path, trade_date: str, run_id: str) -> dict[str, Any]:
    """Strictly inspect an immutable run independently of the date current pointer."""

    pointer = _current_pointer_for_run(root, trade_date, run_id)
    return inspect_review_bundle(trade_date, root, _current_override=pointer)


def _should_publish_current(current_path: Path, candidate: Mapping[str, Any], trade_date: str, root: Path) -> bool:
    """Publish a non-weaker valid candidate for the exact date.

    Equal-quality candidates are accepted because the candidate has already
    passed strict source/SHA inspection; this permits a corrected immutable run
    with the same evidence tier to become current while never allowing a
    strictly weaker candidate to replace a stronger one.
    """

    if not current_path.is_file():
        return True
    try:
        current = inspect_review_bundle(trade_date, root)
    except ReviewBundleValidationError:
        return True
    return _bundle_quality(candidate) >= _bundle_quality(current)


def build_review_bundle(
    trade_date: str,
    *,
    v3_artifact_root: Path | str | None = None,
    v3_payload_path: Path | str | None = None,
    replay_root: Path | str | None = None,
    replay_review_path: Path | str | None = None,
    video_data_root: Path | str | None = None,
    output_root: Path | str | None = None,
    v3_root: Path | str | None = None,
    video_root: Path | str | None = None,
    page_source_kind: str = "v3_fupan_payload",
) -> dict[str, Any]:
    """Build an immutable bundle from exact-date read-only inputs.

    ``output_root`` is intentionally explicit in production callers.  Tests
    should pass a temporary directory; no canonical runtime path is touched by
    this function unless the caller explicitly supplies it.
    """

    target = _date8(trade_date)
    if v3_artifact_root is None and v3_root is not None:
        v3_artifact_root = v3_root
    if video_data_root is None and video_root is not None:
        video_data_root = video_root
    v3_path = _payload_path(target, v3_artifact_root=v3_artifact_root, v3_payload_path=v3_payload_path)
    replay_path = _replay_review_path(target, replay_root=replay_root, replay_review_path=replay_review_path)
    v3_payload = _read_json(v3_path)
    replay = _read_json(replay_path)
    _validate_v3_payload(v3_payload, target)
    market_scope, market_completeness = _market_contract(v3_payload)
    _validate_independent_review(replay, target)
    if not isinstance(page_source_kind, str) or not page_source_kind.strip():
        raise ReviewBundleValidationError("review bundle page source kind missing")
    source_refs = [
        _source_ref(v3_path, kind=page_source_kind.strip()),
        _source_ref(replay_path, kind="independent_replay"),
    ]
    source_refs.extend(_video_source_refs(video_data_root, target))
    source_sha256 = {str(ref["kind"]): str(ref["sha256"]) for ref in source_refs}
    implementation_sha256 = _implementation_hashes()
    input_digest = hashlib.sha256(
        _canonical_json(
            {
                "schema_version": BUNDLE_SCHEMA_VERSION,
                "trade_date": target,
                "source_sha256": source_sha256,
                "implementation_sha256": implementation_sha256,
            }
        )
    ).hexdigest()
    run_id = f"rbv1-{target}-{input_digest[:16]}"
    root = (Path(output_root) if output_root is not None else DEFAULT_DATA_ROOT).absolute()
    paths = _safe_bundle_paths(root, target, run_id)
    existing_run = paths["run_dir"]
    if existing_run.exists():
        candidate_path = existing_run / "review_bundle.json"
        if not candidate_path.is_file():
            raise ReviewBundleValidationError(f"immutable review bundle run is incomplete: {run_id}")
        candidate = _read_json(candidate_path)
        if candidate.get("run_id") != run_id or candidate.get("trade_date") != target:
            raise ReviewBundleValidationError("immutable bundle run identity collision")
        inspected = _inspect_run_bundle(root, target, run_id)
        current_published = _should_publish_current(paths["current_path"], inspected, target, root)
        if current_published:
            _write_json_atomic(paths["current_path"], _current_pointer_for_run(root, target, run_id))
        return {
            "status": str(inspected.get("status") or "PARTIAL"),
            "idempotent": True,
            "current_published": current_published,
            "trade_date": target,
            "run_id": run_id,
            "current_path": str(paths["current_path"]),
            "run_dir": str(existing_run),
            "bundle": inspected,
        }

    video, video_gap_rows = _map_video(target, video_data_root=video_data_root, v3_payload=v3_payload)
    bundle_status = (
        "READY"
        if video.get("status") == "READY" and market_scope == FULL_MARKET_SCOPE
        else "PARTIAL"
    )
    summary_cards = v3_payload.get("summary_cards")
    if not isinstance(summary_cards, list):
        summary_cards = [v3_payload.get("summary") or {}]
    prior_rows = v3_payload.get("prior_plan_rows") if isinstance(v3_payload.get("prior_plan_rows"), list) else []
    board_rows = v3_payload.get("board_rows") if isinstance(v3_payload.get("board_rows"), list) else []
    anchor_rows = v3_payload.get("anchor_role_v3_rows") if isinstance(v3_payload.get("anchor_role_v3_rows"), list) else []
    scenario_rows = v3_payload.get("scenario_tree_rows") if isinstance(v3_payload.get("scenario_tree_rows"), list) else []
    source_status_rows = v3_payload.get("source_status_rows") if isinstance(v3_payload.get("source_status_rows"), list) else []
    cannot_rows = v3_payload.get("cannot_confirm_items") if isinstance(v3_payload.get("cannot_confirm_items"), list) else []
    appendix_rows = [
        {"kind": "source_status", "value": copy.deepcopy(row)} for row in source_status_rows
    ] + [
        {"kind": "cannot_confirm", "value": copy.deepcopy(row)} for row in cannot_rows
    ]
    layers = [
        _layer(1, LAYER_NAMES[0], summary_cards, summary=v3_payload.get("summary") or {}),
        _layer(2, LAYER_NAMES[1], prior_rows),
        _layer(3, LAYER_NAMES[2], board_rows),
        _layer(4, LAYER_NAMES[3], _mainline_rows(board_rows)),
        _layer(5, LAYER_NAMES[4], anchor_rows),
        _layer(
            6,
            LAYER_NAMES[5],
            scenario_rows,
            trigger_rows=copy.deepcopy(v3_payload.get("trigger_rows") if isinstance(v3_payload.get("trigger_rows"), list) else []),
            independent_tomorrow_observation=copy.deepcopy(replay.get("tomorrow_observation") or []),
        ),
        _layer(
            7,
            LAYER_NAMES[6],
            video_gap_rows if video.get("status") == "READY" else [],
            status="READY" if video.get("status") == "READY" else "CANNOT_CONFIRM",
            video=video,
        ),
        _layer(8, LAYER_NAMES[7], appendix_rows, source_refs=copy.deepcopy(source_refs)),
    ]
    compatibility = _compatibility_dto(
        target,
        v3_payload=v3_payload,
        replay=replay,
        video=video,
        video_gap_rows=video_gap_rows if video.get("status") == "READY" else [],
        source_refs=source_refs,
    )
    bundle = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "trade_date": target,
        "run_id": run_id,
        "layer_order": list(LAYER_NAMES),
        "layers": layers,
        "compatibility": compatibility,
        "independent_review": _independent_view(replay),
        "video": video,
        "market_scope": market_scope,
        "market_completeness": market_completeness,
        "source_refs": source_refs,
        "source_sha256": source_sha256,
        "input_digest": input_digest,
        "implementation_sha256": implementation_sha256,
        "video_input_count": 0,
        "video_augmented": False,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "safety_flags": dict(SAFETY_FLAGS),
        "cannot_confirm": list(video.get("cannot_confirm") or []),
        "status": bundle_status,
    }
    paths["run_dir"].parent.mkdir(parents=True, exist_ok=True)
    stage = paths["run_dir"].parent / f".{run_id}.staging"
    if stage.exists():
        raise ReviewBundleValidationError(f"immutable staging run already exists: {stage}")
    stage.mkdir(parents=True, exist_ok=False)
    try:
        bundle_path = stage / "review_bundle.json"
        _write_json_atomic(bundle_path, bundle)
        bundle_sha = sha256_file(bundle_path)
        manifest = {
            "schema_version": BUNDLE_MANIFEST_SCHEMA_VERSION,
            "bundle_schema_version": BUNDLE_SCHEMA_VERSION,
            "trade_date": target,
            "run_id": run_id,
            "bundle_path": f"{paths['run_rel'].as_posix()}/review_bundle.json",
            "bundle_sha256": bundle_sha,
            "layer_order": list(LAYER_NAMES),
            "layer_row_counts": {layer["name"]: layer["row_count"] for layer in layers},
            "compatibility_schema_version": compatibility["schema_version"],
            "source_refs": copy.deepcopy(source_refs),
            "source_sha256": source_sha256,
            "input_digest": input_digest,
            "implementation_sha256": bundle["implementation_sha256"],
            "market_scope": market_scope,
            "market_completeness": market_completeness,
            "safety_flags": dict(SAFETY_FLAGS),
            **SAFETY_FLAGS,
        }
        manifest_path = stage / "manifest.json"
        _write_json_atomic(manifest_path, manifest)
        manifest_sha = sha256_file(manifest_path)
        receipt = {
            "schema_version": BUNDLE_RECEIPT_SCHEMA_VERSION,
            "trade_date": target,
            "run_id": run_id,
            "status": bundle_status,
            "bundle_sha256": bundle_sha,
            "manifest_sha256": manifest_sha,
            "source_sha256": source_sha256,
            "market_scope": market_scope,
            "market_completeness": market_completeness,
            "safety_flags": dict(SAFETY_FLAGS),
        }
        receipt_path = stage / "receipt.json"
        _write_json_atomic(receipt_path, receipt)
        receipt_sha = sha256_file(receipt_path)
        if paths["run_dir"].exists():
            raise ReviewBundleValidationError(f"refusing to overwrite immutable run: {paths['run_dir']}")
        os.replace(stage, paths["run_dir"])
    except Exception:
        if stage.exists():
            for child in sorted(stage.rglob("*"), reverse=True):
                if child.is_file() or child.is_symlink():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            stage.rmdir()
        raise

    current_published = _should_publish_current(paths["current_path"], bundle, target, root)
    if current_published:
        _write_json_atomic(paths["current_path"], _current_pointer_for_run(root, target, run_id))
        inspected = inspect_review_bundle(target, root)
    else:
        inspected = bundle
    return {
        "status": bundle_status,
        "idempotent": False,
        "current_published": current_published,
        "trade_date": target,
        "run_id": run_id,
        "current_path": str(paths["current_path"]),
        "run_dir": str(paths["run_dir"]),
        "bundle": inspected,
    }


def _exact_relative(value: Any, expected: str, label: str) -> str:
    if not isinstance(value, str) or value.replace("\\", "/") != expected:
        raise ReviewBundleValidationError(f"{label} is not exact-date")
    if value.startswith("/") or ".." in Path(value).parts:
        raise ReviewBundleValidationError(f"unsafe {label}")
    return expected


def inspect_review_bundle(
    trade_date: str,
    output_root: Path | str | None = None,
    *,
    _current_override: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate only the exact-date ReviewBundleV1 pointer and referenced SHAs."""

    target = _date8(trade_date)
    root = (Path(output_root) if output_root is not None else DEFAULT_DATA_ROOT).absolute()
    current_path = root / "review_bundle" / target / "current.json"
    if _current_override is None:
        if not current_path.is_file():
            raise ReviewBundleValidationError(f"exact-date review bundle pointer missing: {target}")
        current = _read_json(current_path)
    else:
        current = dict(_current_override)
    if current.get("schema_version") != BUNDLE_CURRENT_SCHEMA_VERSION:
        raise ReviewBundleValidationError("review bundle current pointer schema mismatch")
    if current.get("trade_date") != target:
        raise ReviewBundleValidationError("review bundle current pointer date mismatch")
    for name, expected in SAFETY_FLAGS.items():
        if current.get("safety_flags", {}).get(name) is not expected:
            raise ReviewBundleValidationError(f"unsafe review bundle current flag: {name}")
    run_rel = _exact_relative(current.get("run_path"), f"review_bundle/{target}/runs/{current.get('run_id', '')}", "run_path")
    bundle_rel = _exact_relative(current.get("bundle_path"), f"{run_rel}/review_bundle.json", "bundle_path")
    manifest_rel = _exact_relative(current.get("manifest_path"), f"{run_rel}/manifest.json", "manifest_path")
    receipt_rel = _exact_relative(current.get("receipt_path"), f"{run_rel}/receipt.json", "receipt_path")
    bundle_path, manifest_path, receipt_path = (root / Path(rel) for rel in (bundle_rel, manifest_rel, receipt_rel))
    for path, label in ((bundle_path, "bundle"), (manifest_path, "manifest"), (receipt_path, "receipt")):
        if not path.is_file():
            raise ReviewBundleValidationError(f"review bundle {label} missing")
    bundle_sha, manifest_sha, receipt_sha = (sha256_file(path) for path in (bundle_path, manifest_path, receipt_path))
    if bundle_sha != str(current.get("bundle_sha256") or ""):
        raise ReviewBundleValidationError("review bundle SHA mismatch")
    if manifest_sha != str(current.get("manifest_sha256") or ""):
        raise ReviewBundleValidationError("review bundle manifest SHA mismatch")
    if receipt_sha != str(current.get("receipt_sha256") or ""):
        raise ReviewBundleValidationError("review bundle receipt SHA mismatch")
    bundle = _read_json(bundle_path)
    manifest = _read_json(manifest_path)
    receipt = _read_json(receipt_path)
    if bundle.get("schema_version") != BUNDLE_SCHEMA_VERSION:
        raise ReviewBundleValidationError("review bundle schema mismatch")
    if bundle.get("trade_date") != target or bundle.get("run_id") != current.get("run_id"):
        raise ReviewBundleValidationError("review bundle identity mismatch")
    market_scope, market_completeness = _market_contract(bundle, allow_legacy=True)
    if bundle.get("status") == "READY" and market_scope == FORMAL_POOL_PROXY_SCOPE:
        raise ReviewBundleValidationError("proxy market review bundle cannot be READY")
    if manifest.get("schema_version") != BUNDLE_MANIFEST_SCHEMA_VERSION or manifest.get("bundle_schema_version") != BUNDLE_SCHEMA_VERSION:
        raise ReviewBundleValidationError("review bundle manifest schema mismatch")
    if manifest.get("trade_date") != target or manifest.get("run_id") != bundle.get("run_id"):
        raise ReviewBundleValidationError("review bundle manifest identity mismatch")
    if manifest.get("compatibility_schema_version") != COMPATIBILITY_SCHEMA_VERSION:
        raise ReviewBundleValidationError("review bundle compatibility schema mismatch")
    if manifest.get("bundle_sha256") != bundle_sha:
        raise ReviewBundleValidationError("review bundle manifest bundle SHA mismatch")
    if manifest.get("source_sha256") != bundle.get("source_sha256"):
        raise ReviewBundleValidationError("review bundle source SHA ledger mismatch")
    if manifest.get("input_digest") != bundle.get("input_digest"):
        raise ReviewBundleValidationError("review bundle input digest mismatch")
    if market_scope != "LEGACY_UNVERIFIED" and (
        manifest.get("market_scope") != market_scope
        or manifest.get("market_completeness") != market_completeness
    ):
        raise ReviewBundleValidationError("review bundle market contract ledger mismatch")
    if receipt.get("schema_version") != BUNDLE_RECEIPT_SCHEMA_VERSION:
        raise ReviewBundleValidationError("review bundle receipt schema mismatch")
    if receipt.get("trade_date") != target or receipt.get("run_id") != bundle.get("run_id"):
        raise ReviewBundleValidationError("review bundle receipt identity mismatch")
    if receipt.get("bundle_sha256") != bundle_sha or receipt.get("manifest_sha256") != manifest_sha:
        raise ReviewBundleValidationError("review bundle receipt SHA ledger mismatch")
    if market_scope != "LEGACY_UNVERIFIED" and (
        receipt.get("market_scope") != market_scope
        or receipt.get("market_completeness") != market_completeness
    ):
        raise ReviewBundleValidationError("review bundle receipt market contract mismatch")
    for name, expected in SAFETY_FLAGS.items():
        if bundle.get(name) is not expected or manifest.get(name) is not expected:
            raise ReviewBundleValidationError(f"unsafe review bundle flag: {name}")
        if receipt.get("safety_flags", {}).get(name) is not expected:
            raise ReviewBundleValidationError(f"unsafe review bundle receipt flag: {name}")
    if bundle.get("layer_order") != list(LAYER_NAMES) or manifest.get("layer_order") != list(LAYER_NAMES):
        raise ReviewBundleValidationError("review bundle layer order mismatch")
    layers = bundle.get("layers")
    if not isinstance(layers, list) or len(layers) != len(LAYER_NAMES):
        raise ReviewBundleValidationError("review bundle layer count mismatch")
    for index, layer in enumerate(layers, start=1):
        if not isinstance(layer, dict) or layer.get("index") != index or layer.get("name") != LAYER_NAMES[index - 1]:
            raise ReviewBundleValidationError("review bundle layer identity mismatch")
        rows = layer.get("rows")
        if not isinstance(rows, list) or layer.get("row_count") != len(rows):
            raise ReviewBundleValidationError("review bundle layer row count mismatch")
    independent = bundle.get("independent_review")
    if not isinstance(independent, dict) or independent.get("video_input_count") != 0 or independent.get("video_augmented") is not False:
        raise ReviewBundleValidationError("independent review video boundary mismatch")
    _validate_independent_review(independent, target)
    if bundle.get("video_input_count") != 0 or bundle.get("video_augmented") is not False:
        raise ReviewBundleValidationError("review bundle video boundary mismatch")
    video = bundle.get("video")
    if not isinstance(video, dict) or video.get("trade_date") != target or video.get("target_trade_date") != target:
        raise ReviewBundleValidationError("review bundle video identity mismatch")
    if video.get("video_input_count") != 0 or video.get("video_augmented") is not False:
        raise ReviewBundleValidationError("review bundle video boundary mismatch")
    if video.get("status") == "CANNOT_CONFIRM" and video.get("bv_id"):
        raise ReviewBundleValidationError("cannot-confirm video layer contains a BV fallback")
    compatibility = bundle.get("compatibility")
    if not isinstance(compatibility, dict) or compatibility.get("schema_version") != COMPATIBILITY_SCHEMA_VERSION:
        raise ReviewBundleValidationError("review bundle compatibility DTO missing or invalid")
    if compatibility.get("trade_date") != target:
        raise ReviewBundleValidationError("review bundle compatibility date mismatch")
    if market_scope != "LEGACY_UNVERIFIED" and (
        compatibility.get("market_scope") != market_scope
        or compatibility.get("market_completeness") != market_completeness
    ):
        raise ReviewBundleValidationError("review bundle compatibility market contract mismatch")
    missing_compatibility = [name for name in COMPATIBILITY_FIELDS if name not in compatibility]
    if missing_compatibility:
        raise ReviewBundleValidationError(
            "review bundle compatibility fields missing: " + ",".join(missing_compatibility)
        )
    for name, expected in SAFETY_FLAGS.items():
        if compatibility.get("safety_flags", {}).get(name) is not expected:
            raise ReviewBundleValidationError(f"unsafe review bundle compatibility flag: {name}")
        if compatibility.get(name) is not expected:
            raise ReviewBundleValidationError(f"unsafe review bundle compatibility boundary: {name}")
    if compatibility.get("video_input_count") != 0 or compatibility.get("video_augmented") is not False:
        raise ReviewBundleValidationError("review bundle compatibility video boundary mismatch")
    compatibility_video = compatibility.get("video")
    if not isinstance(compatibility_video, dict):
        raise ReviewBundleValidationError("review bundle compatibility video missing")
    for name in ("status", "trade_date", "target_trade_date", "bv_id", "upload_date", "date_scope", "asr_segment_count", "gap_row_count", "targeted_spotcheck_count"):
        if compatibility_video.get(name) != video.get(name):
            raise ReviewBundleValidationError(f"review bundle compatibility video mismatch: {name}")
    if compatibility.get("video_gap_rows") != layers[6].get("rows"):
        raise ReviewBundleValidationError("review bundle compatibility gap rows mismatch")
    if "20260807" in json.dumps(compatibility, ensure_ascii=False):
        raise ReviewBundleValidationError("stale date residue in review bundle compatibility")
    refs = bundle.get("source_refs")
    if not isinstance(refs, list) or not refs:
        raise ReviewBundleValidationError("review bundle source refs missing")
    for ref in refs:
        if not isinstance(ref, dict) or not ref.get("path") or not ref.get("sha256"):
            raise ReviewBundleValidationError("invalid review bundle source ref")
        source_path = Path(str(ref["path"]))
        if not source_path.is_file() or sha256_file(source_path) != ref["sha256"]:
            raise ReviewBundleValidationError(f"review bundle source SHA mismatch: {source_path}")
    return bundle


def run_review(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Stable review entry with local exact-date production by default.

    Legacy V3/replay inputs remain available only when the caller explicitly
    supplies one of the frozen compatibility paths.
    """

    legacy_keys = (
        "v3_artifact_root",
        "v3_payload_path",
        "replay_root",
        "replay_review_path",
        "v3_root",
    )
    if any(kwargs.get(name) is not None for name in legacy_keys):
        legacy_allowed = {
            "v3_artifact_root",
            "v3_payload_path",
            "replay_root",
            "replay_review_path",
            "video_data_root",
            "output_root",
            "v3_root",
            "video_root",
            "page_source_kind",
        }
        return build_review_bundle(*args, **{name: value for name, value in kwargs.items() if name in legacy_allowed})
    from .review_pipeline import run_local_review_pipeline

    return run_local_review_pipeline(*args, **{name: value for name, value in kwargs.items() if name not in legacy_keys})


__all__ = [
    "BUNDLE_SCHEMA_VERSION",
    "DEFAULT_REPLAY_ROOT",
    "DEFAULT_V3_ARTIFACT_ROOT",
    "LAYER_NAMES",
    "ReviewBundleValidationError",
    "build_review_bundle",
    "inspect_review_bundle",
    "run_review",
]
