"""Import graph-defined optional preselection pools from explicit read-only inputs."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from infrastructure.preselection_overlay_store import PreselectionOverlayStore


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = REPO_ROOT / "contracts" / "migration" / "preselection_optional_pools_v1.json"
GRAPH_BASELINE = REPO_ROOT / "contracts" / "migration" / "v3_graph_baseline_v2.json"
DEFAULT_DATA_ROOT = REPO_ROOT / ".runtime" / "data"
EXPECTED_CONTRACT_RAW_SHA256 = "bb88f67e420b6bda9031b05dc5fcc50b9c80bc117008f314b95d927f0177457d"
EXPECTED_CONTRACT_SEMANTIC_HASH = "ec7c3faaa4024545c1a7fa4e93a9f9b0f9d9b9578d8d82f613e7156a27b8554b"
EXPECTED_GRAPH_BASELINE_SEMANTIC_HASH = "8b4b933858f0e573b4d9f34423cd7aceeeb09dbf50cc826de0b18b712a4cbdd7"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _semantic_hash(payload: Mapping[str, Any], field: str = "semantic_hash") -> str:
    body = {key: value for key, value in payload.items() if key != field}
    return hashlib.sha256(
        json.dumps(
            body,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _date(value: Any, field: str) -> str:
    from infrastructure.data_store import _date as strict_date

    try:
        return strict_date(str(value or ""))
    except ValueError as error:
        raise ValueError(f"invalid {field}") from error


def _false(value: Any, field: str) -> None:
    if value is not False and str(value).strip().casefold() not in {"false", "0"}:
        raise ValueError(f"{field} must remain false")


def _true(value: Any, field: str) -> None:
    if value is not True and str(value).strip().casefold() not in {"true", "1"}:
        raise ValueError(f"{field} must remain true")


def _a_symbol(item: Mapping[str, Any]) -> tuple[str, str]:
    ts_code = str(item.get("ts_code") or "").strip().upper()
    raw_code = str(item.get("code") or "").strip().upper()
    match = re.fullmatch(r"(\d{6})(?:\.(?:SH|SZ|BJ))?", ts_code or raw_code)
    if match is None:
        raise ValueError("invalid WeChat A-share code")
    code = match.group(1)
    return f"A.{code}", ts_code or code


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid WeChat manifest") from error
    if not isinstance(value, dict):
        raise ValueError("invalid WeChat manifest")
    return value


def _read_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            rows = [dict(item) for item in csv.DictReader(source)]
    except (OSError, UnicodeError, csv.Error) as error:
        raise ValueError("invalid WeChat rows CSV") from error
    if not rows:
        raise ValueError("WeChat rows CSV is empty")
    return rows


def build_optional_pool_overlay(
    manifest_path: Path,
    rows_path: Path,
    *,
    expected_manifest_sha256: str,
    expected_rows_sha256: str,
    expected_business_date: str,
    expected_row_count: int,
) -> dict[str, Any]:
    """Normalize two optional V3 pool identities without modifying the inputs."""
    manifest_path = Path(manifest_path)
    rows_path = Path(rows_path)
    for path, label in ((manifest_path, "manifest"), (rows_path, "rows")):
        if not path.is_file():
            raise ValueError(f"WeChat {label} input is not a regular file")
    if not _SHA256.fullmatch(expected_manifest_sha256) or _raw_sha256(manifest_path) != expected_manifest_sha256:
        raise ValueError("WeChat manifest SHA mismatch")
    if not _SHA256.fullmatch(expected_rows_sha256) or _raw_sha256(rows_path) != expected_rows_sha256:
        raise ValueError("WeChat rows SHA mismatch")
    business_date = _date(expected_business_date, "business date")
    if isinstance(expected_row_count, bool) or not isinstance(expected_row_count, int) or expected_row_count < 1:
        raise ValueError("invalid expected WeChat row count")

    manifest = _read_manifest(manifest_path)
    if manifest.get("status") != "WECHAT_V3_PRESELECT_READY":
        raise ValueError("WeChat manifest is not ready")
    signal_date = _date(manifest.get("signal_date"), "signal date")
    target_date = _date(manifest.get("target_date"), "target date")
    selector_score_date = _date(manifest.get("selector_score_date"), "selector score date")
    effective_trade_date = _date(manifest.get("effective_trade_date"), "effective trade date")
    article_publish_date = _date(manifest.get("article_publish_date"), "article publish date")
    if {signal_date, target_date, selector_score_date, article_publish_date} != {business_date}:
        raise ValueError("WeChat manifest date binding mismatch")
    validation = manifest.get("target_validation")
    if not isinstance(validation, Mapping) or validation.get("status") != "TARGET_DATE_CHECK_PASS":
        raise ValueError("WeChat target-date validation did not pass")
    _true(validation.get("date_match"), "date_match")
    _true(validation.get("title_match"), "title_match")
    _false(validation.get("allow_mismatch"), "allow_mismatch")
    boundary = manifest.get("boundary")
    if not isinstance(boundary, Mapping) or boundary.get("lane") != "research_lane_observation_preselect":
        raise ValueError("WeChat research-only lane mismatch")
    _false(boundary.get("formal_pool_write"), "formal_pool_write")
    _false(boundary.get("buy_gate_write"), "buy_gate_write")

    raw_rows = _read_rows(rows_path)
    counts = manifest.get("counts")
    if (
        len(raw_rows) != expected_row_count
        or not isinstance(counts, Mapping)
        or counts.get("wechat_unique_codes") != expected_row_count
        or counts.get("v3_matched_codes") != expected_row_count
        or counts.get("v3_unmatched_codes") != 0
    ):
        raise ValueError("WeChat manifest and CSV row counts disagree")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_rows, start=1):
        symbol, ts_code = _a_symbol(item)
        if symbol in seen:
            raise ValueError("duplicate WeChat symbol")
        seen.add(symbol)
        try:
            rank = int(str(item.get("wechat_v3_preselect_rank") or ""))
            score = round(float(str(item.get("candidate_score") or "")), 3)
            hit_count = int(str(item.get("wechat_hit_count") or "0"))
        except ValueError as error:
            raise ValueError("invalid WeChat rank or score") from error
        if rank != index:
            raise ValueError("WeChat rank sequence mismatch")
        if _date(item.get("trade_date"), "row trade date") != business_date:
            raise ValueError("WeChat row date mismatch")
        _true(item.get("v3_match"), "v3_match")
        _false(item.get("formal_pool_write"), "formal_pool_write")
        if str(item.get("buy_gate_write")).strip().casefold() not in {"false", "0"}:
            raise ValueError("WeChat row attempted BUY gate write")
        if item.get("wechat_pool_lane") != "research_lane_observation_preselect":
            raise ValueError("WeChat row lane mismatch")
        name = str(item.get("name") or item.get("display_name") or ts_code).strip()
        display_name = str(item.get("display_name") or name).strip()
        normalized.append({
            "market": "WECHAT",
            "market_label": "公众号",
            "pool_id": "wechat_public_account_v3_preselect",
            "rank": rank,
            "pool_rank": rank,
            "code": ts_code,
            "ts_code": ts_code,
            "symbol": symbol,
            "name": name,
            "stock_name": name,
            "display_name": display_name,
            "score": score,
            "pool_score": score,
            "status": str(item.get("v3_preselect_status") or "RESEARCH_ONLY"),
            "recommendation_status": "RESEARCH_ONLY",
            "trade_status_contract": "RESEARCH_ONLY_NO_BUY_GATE",
            "role": "公众号 OCR 观察预选",
            "source_label": "公众号股票池",
            "source_lanes": str(item.get("wechat_theme") or ""),
            "source_tags": str(item.get("source_tags") or "（研）"),
            "signal_date": signal_date,
            "source_signal_date": signal_date,
            "effective_trade_date": effective_trade_date,
            "selector_score_date": selector_score_date,
            "target_date": target_date,
            "date_match_status": "MATCH",
            "wechat_publish_date": str(item.get("publish_date") or ""),
            "wechat_article_title": str(item.get("article_title") or ""),
            "wechat_hit_count": hit_count,
            "wechat_source_ref": str(item.get("wechat_source_ref") or ""),
            "next_action": "进入 09:20/09:25 二筛和人工复核；不进入 BUY gate。",
            "stage_selection_eligible": False,
            "formal_pool_write": False,
            "buy_gate_write": False,
            "production_allowed": False,
            "orders_sent": False,
        })

    baimao_pool = _empty_baimao_pool(business_date)
    wechat_pool = {
        "pool_id": "wechat_public_account_v3_preselect",
        "market": "WECHAT",
        "display_name": "公众号股票池",
        "status": "WECHAT_V3_PRESELECT_READY",
        "recommendation_status": "RESEARCH_ONLY",
        "trade_status_contract": "RESEARCH_ONLY_NO_BUY_GATE",
        "stage_selection_eligible": False,
        "formal_pool_write": False,
        "production_allowed": False,
        "date_match_status": "MATCH",
        "source_signal_date": signal_date,
        "target_date": business_date,
        "pool_size": len(normalized),
        "returned_rows": len(normalized),
        "rows": normalized,
        "cannot_confirm": [{
            "scope": "wechat_public_account_v3_preselect",
            "reason": "RESEARCH_ONLY_NO_BUY_GATE",
            "description": "公众号股票池只作为观察预选和解释增强；不修改正式池、BUY gate 或交易系统。",
            "source_path": "",
        }],
        "evidence_paths": {
            "manifest": f"external-read-only:sha256:{expected_manifest_sha256}",
            "all_rows": f"external-read-only:sha256:{expected_rows_sha256}",
        },
    }
    return {
        "schema_version": "v3_5.preselection_overlay.v1",
        "trade_date": business_date,
        "module_id": "preselection_optional_pools",
        "source_status": "WECHAT_V3_PRESELECT_READY",
        "source_signal_date": signal_date,
        "effective_trade_date": effective_trade_date,
        "source_manifest_sha256": expected_manifest_sha256,
        "source_rows_sha256": expected_rows_sha256,
        "source_row_count": len(normalized),
        "write_policy": "read_only",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "pools": [baimao_pool, wechat_pool],
        "cannot_confirm": [
            "BAIMAO_RESEARCH_MAP_NOT_FOUND",
            "RESEARCH_ONLY_NO_BUY_GATE",
        ],
    }


def _empty_baimao_pool(trade_date: str) -> dict[str, Any]:
    return {
        "pool_id": "a_share_baimao_research_map",
        "market": "A",
        "display_name": "白毛卡点研究池",
        "status": "CANNOT_CONFIRM",
        "recommendation_status": "RESEARCH_ONLY",
        "trade_status_contract": "RESEARCH_ONLY_NO_BUY_GATE",
        "stage_selection_eligible": False,
        "write_policy": "RESEARCH_ONLY",
        "production_allowed": False,
        "opens_buy_gate": False,
        "pool_size": 0,
        "returned_rows": 0,
        "trade_date": trade_date,
        "rows": [],
        "cannot_confirm": ["BAIMAO_RESEARCH_MAP_NOT_FOUND"],
        "evidence_paths": {"research_map": ""},
    }


def _contract(path: Path) -> dict[str, Any]:
    try:
        resolved = Path(path).resolve(strict=True)
        trusted = DEFAULT_CONTRACT.resolve(strict=True)
    except OSError as error:
        raise ValueError("optional-pool contract cannot be resolved") from error
    if resolved != trusted:
        raise ValueError("optional-pool contract must use the frozen authority path")
    if _raw_sha256(trusted) != EXPECTED_CONTRACT_RAW_SHA256:
        raise ValueError("optional-pool contract raw SHA mismatch")
    try:
        value = json.loads(trusted.read_text(encoding="utf-8"))
        graph = json.loads(GRAPH_BASELINE.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("optional-pool authority cannot be read") from error
    if not isinstance(value, dict) or value.get("schema_version") != "v3_5.preselection_optional_pools_contract.v1":
        raise ValueError("invalid optional-pool contract")
    if (
        value.get("semantic_hash") != EXPECTED_CONTRACT_SEMANTIC_HASH
        or _semantic_hash(value) != EXPECTED_CONTRACT_SEMANTIC_HASH
    ):
        raise ValueError("optional-pool contract semantic SHA mismatch")
    if (
        not isinstance(graph, dict)
        or graph.get("schema_version") != "v3_5.graph_baseline.v2"
        or graph.get("semantic_hash") != EXPECTED_GRAPH_BASELINE_SEMANTIC_HASH
        or _semantic_hash(graph) != EXPECTED_GRAPH_BASELINE_SEMANTIC_HASH
        or value.get("graph_authority", {}).get("graph_baseline_semantic_hash")
        != EXPECTED_GRAPH_BASELINE_SEMANTIC_HASH
    ):
        raise ValueError("optional-pool graph authority mismatch")
    return value


def _allowed_data_root(path: Path) -> Path:
    allowed = DEFAULT_DATA_ROOT.resolve(strict=False)
    resolved = Path(path).resolve(strict=False)
    if resolved != allowed:
        raise ValueError("optional-pool output must use the V4 .runtime/data root")
    return resolved


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    args = parser.parse_args(argv)
    contract = _contract(args.contract)
    frozen = contract["frozen_inputs"]
    payload = build_optional_pool_overlay(
        args.manifest,
        args.rows,
        expected_manifest_sha256=frozen["wechat_manifest"]["raw_sha256"],
        expected_rows_sha256=frozen["wechat_rows"]["raw_sha256"],
        expected_business_date=contract["business_date"],
        expected_row_count=frozen["wechat_rows"]["row_count"],
    )
    result = PreselectionOverlayStore(_allowed_data_root(args.data_root)).import_overlay(payload)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
