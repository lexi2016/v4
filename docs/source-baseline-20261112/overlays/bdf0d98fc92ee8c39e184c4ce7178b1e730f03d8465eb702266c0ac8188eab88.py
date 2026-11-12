"""Local deterministic Review Core page/replay integration pipeline.

The pipeline is deliberately a small adapter around the already-validated
local producers.  It reads exact-date public fupan input, selector rows and
TDX files, writes immutable shadow artifacts, and then hands those explicit
paths to :func:`review.build_review_bundle`.  It never reads a generated V3
page payload or a historical replay directory as a production input.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping

from .core import DEFAULT_DATA_ROOT, EvidenceValidationError, inspect_bundle, normalize_trade_date, sha256_file
from .daily_replay_producer import (
    FORMAL_POOL_PROXY_SCOPE,
    FULL_MARKET_SCOPE,
    MARKET_UNIVERSE_SCOPES,
    build_daily_replay_payload,
)
from .fupan_page_producer import build_fupan_page_payload
from .producer_inputs import load_raw_page_inputs


PIPELINE_SCHEMA = "review_core.local_review_pipeline.v1"
PIPELINE_MANIFEST_SCHEMA = "review_core.local_review_pipeline.manifest.v1"
PIPELINE_RECEIPT_SCHEMA = "review_core.local_review_pipeline.receipt.v1"
PIPELINE_CURRENT_SCHEMA = "review_core.local_review_pipeline.current.v1"

DEFAULT_PUBLIC_SOURCE_ROOT = Path(r"C:\Users\huang\Desktop\学习\v3_shared_data\.runtime\data")
DEFAULT_SELECTOR_ROOT = Path(
    r"C:\Users\huang\Desktop\学习\数据\selector_ready_panels\data_layer_daily_formula_increment_update_v1"
)
DEFAULT_TDX_ROOT = Path(r"C:\new_tdx_mock")
DEFAULT_APP_DATA_ROOT = Path(
    r"C:\Users\huang\Desktop\学习\v3_system\30_runtime\opening_advisor_8771\data"
)
SAFETY_FLAGS = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
MARKET_SCOPE_FIELD = "market_scope"
MARKET_COMPLETENESS_FIELD = "market_completeness"

_SELECTOR_CURRENT_COLUMNS = ["trade_date", "ts_code", "name", "pct_chg", "amount", "bar_close_pos"]
_SELECTOR_MAPPING_COLUMNS = ["trade_date", "ts_code", "tdx_industry_code", "tdx_industry_name"]
_SELECTOR_NAME_COLUMNS = ["trade_date", "ts_code", "name"]


class LocalReviewPipelineError(EvidenceValidationError):
    """Raised when exact-date local review inputs cannot be verified."""


def _validate_market_scope(value: Any) -> str:
    scope = str(value or "").strip()
    if scope not in MARKET_UNIVERSE_SCOPES:
        raise LocalReviewPipelineError(
            "MARKET_SCOPE_REQUIRED: raw loader must explicitly declare FULL_MARKET or FORMAL_POOL_PROXY"
        )
    return scope


def _scope_completeness(scope: str) -> str:
    return "FULL_MARKET_VERIFIED" if scope == FULL_MARKET_SCOPE else "PROXY_ONLY_CANNOT_CONFIRM"


def _mark_page_scope(page_payload: Mapping[str, Any], scope: str, replay_rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Attach and enforce the universe contract at the page/replay integration seam.

    ``fupan_page_producer`` is intentionally kept backwards compatible.  The
    pipeline owns the provenance boundary and removes full-market wording from
    a proxy payload before it can reach ReviewBundle or a page consumer.
    """

    result = copy.deepcopy(dict(page_payload))
    completeness = _scope_completeness(scope)
    result[MARKET_SCOPE_FIELD] = scope
    result[MARKET_COMPLETENESS_FIELD] = completeness
    data_completeness = result.get("data_completeness")
    if not isinstance(data_completeness, dict):
        data_completeness = {}
    data_completeness[MARKET_SCOPE_FIELD] = scope
    data_completeness[MARKET_COMPLETENESS_FIELD] = completeness
    if scope == FORMAL_POOL_PROXY_SCOPE:
        data_completeness.update(
            {
                "status": "PROXY_ONLY_CANNOT_CONFIRM",
                "missing": list(data_completeness.get("missing") or []) + ["全市场 selector breadth/regime"],
                "meaning": "当前仅有正式池代理，不能确认全市场上涨/下跌、市场宽度或市场阶段。",
            }
        )
        result["cannot_confirm_items"] = [
            *list(result.get("cannot_confirm_items") or []),
            {
                "trade_date": result.get("trade_date"),
                "status": "CANNOT_CONFIRM_MARKET_REGIME_PROXY_ONLY",
                "description": "正式池代理不代表全市场，禁止生成全市场宽度/阶段结论。",
                "scope": scope,
            },
        ]
        sanitized_market_rows: list[dict[str, Any]] = []
        for raw in list(result.get("market_rows") or []):
            if not isinstance(raw, Mapping):
                continue
            row = dict(raw)
            metric = str(row.get("metric") or "")
            if metric in {"全市场行数", "上涨/下跌", "涨停/跌停代理", "涨幅均值/中位数"}:
                row["metric"] = f"正式池代理{metric}"
            row["scope"] = scope
            sanitized_market_rows.append(row)
        result["market_rows"] = sanitized_market_rows
        for row in list(result.get("anchor_rows") or []):
            if isinstance(row, dict) and str(row.get("role") or "").startswith("全市场"):
                row["role"] = f"正式池代理{row['role']}"
                row["boundary"] = "正式池代理角色，不代表全市场。"
        for card in list(result.get("summary_cards") or []):
            if not isinstance(card, dict):
                continue
            if card.get("title") == "市场宽度":
                card["title"] = "代理池范围"
                card["value"] = f"正式池代理 {len(replay_rows)} 行"
                card["body"] = "正式池代理不能代表全市场宽度或阶段。"
            card["scope"] = scope
        summary = result.get("summary")
        if isinstance(summary, dict):
            summary[MARKET_SCOPE_FIELD] = scope
            summary[MARKET_COMPLETENESS_FIELD] = completeness
            summary["one_line"] = "正式池代理复盘；全市场宽度与阶段 CANNOT_CONFIRM。"
    result["data_completeness"] = data_completeness
    return result


def _date8(value: str) -> str:
    try:
        return normalize_trade_date(value)
    except (TypeError, ValueError) as exc:
        raise LocalReviewPipelineError(f"invalid exact review date: {value!r}") from exc


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _identity_value(value: Any) -> Any:
    """Convert raw loader values into a deterministic, JSON-safe identity."""

    if isinstance(value, Mapping):
        return {str(key): _identity_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_identity_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest(), "bytes_len": len(value)}
    try:
        json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)
    return value


def _sha_bytes(value: Any) -> str:
    return hashlib.sha256(_canonical(_identity_value(value))).hexdigest()


def _atomic_json(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary = ""
    try:
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and Path(temporary).exists():
            Path(temporary).unlink()
    return hashlib.sha256(encoded).hexdigest()


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    import csv

    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_csv(path: Path, trade_date: str, *, required_field: str | None = None) -> list[dict[str, str]]:
    rows = _read_csv_rows(path)
    for row in rows:
        raw_date = row.get(required_field) if required_field else (row.get("trade_date") or row.get("review_date") or row.get("signal_date"))
        if required_field and not raw_date:
            raise LocalReviewPipelineError(f"input {required_field} missing: {path}")
        if raw_date and _date8(str(raw_date)) != trade_date:
            raise LocalReviewPipelineError(f"input date mismatch: {path}")
    return rows


def _load_pool_inputs(
    formal_path: Path,
    review_path: Path,
    trade_date: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]], set[str]]:
    """Load current formal rows and D-1 review rows with explicit lineage."""

    target = _date8(trade_date)
    formal_rows = _read_csv(formal_path, target, required_field="trade_date")
    review_rows = _read_csv_rows(review_path)
    formal_signal_dates: set[str] = set()
    for row in formal_rows:
        signal = row.get("signal_date")
        if not signal:
            continue
        signal_date = _date8(str(signal))
        if signal_date >= target:
            raise LocalReviewPipelineError(f"formal signal_date lineage invalid: {formal_path}")
        formal_signal_dates.add(signal_date)
    if not review_rows:
        return formal_rows, review_rows, formal_signal_dates
    if not formal_signal_dates:
        raise LocalReviewPipelineError(f"review pool lineage missing formal signal_date: {review_path}")
    for row in review_rows:
        explicit_trade = row.get("trade_date") or row.get("target_date") or row.get("review_date")
        if explicit_trade and _date8(str(explicit_trade)) != target:
            raise LocalReviewPipelineError(f"review pool trade_date mismatch: {review_path}")
        signal = row.get("signal_date")
        if not signal:
            raise LocalReviewPipelineError(f"review pool signal_date missing: {review_path}")
        signal_date = _date8(str(signal))
        if signal_date >= target or signal_date not in formal_signal_dates:
            raise LocalReviewPipelineError(f"review pool signal_date lineage mismatch: {review_path}")
    return formal_rows, review_rows, formal_signal_dates


_STAGE_STRUCTURED_DATE_RE = re.compile(r"^\s*(\d{8}|\d{4}-\d{2}-\d{2})(?=\s|T|$)")
_STAGE_PATH_DATE_RE = re.compile(r"(?<![A-Za-z0-9])20\d{6}(?![A-Za-z0-9])")
_STAGE_PROVENANCE_FIELDS = ("bar_window", "first_time", "last_time", "candidate_source_path", "source_path")


def _stage_date_tokens(field: str, value: str) -> list[str]:
    if field in {"bar_window", "first_time", "last_time"}:
        match = _STAGE_STRUCTURED_DATE_RE.match(value)
        return [match.group(1)] if match else []
    return _STAGE_PATH_DATE_RE.findall(value)


def _load_stage_rows(path: Path, trade_date: str, expected_stage: int | str) -> list[dict[str, str]]:
    target = _date8(trade_date)
    stage_number = str(expected_stage)
    if (
        not path.is_file()
        or path.parent.name != target
        or not path.name.startswith(f"generated_stage{stage_number}_")
        or target not in path.name
    ):
        raise LocalReviewPipelineError(f"stage exact-date path/date mismatch: {path}")
    rows = _read_csv_rows(path)
    if not rows:
        raise LocalReviewPipelineError(f"stage exact-date rows empty: {path}")
    label = f"stage{stage_number}_label"
    if label not in rows[0]:
        raise LocalReviewPipelineError(f"stage column missing {label}: {path}")
    normalized: list[dict[str, str]] = []
    for row in rows:
        explicit_trade = row.get("trade_date")
        if explicit_trade and _date8(str(explicit_trade)) != target:
            raise LocalReviewPipelineError(f"stage trade_date mismatch: {path}")
        target_evidence = False
        for field in _STAGE_PROVENANCE_FIELDS:
            value = str(row.get(field) or "")
            for token in _stage_date_tokens(field, value):
                try:
                    token_date = _date8(token)
                except (TypeError, ValueError) as exc:
                    raise LocalReviewPipelineError(f"stage provenance invalid: {path}") from exc
                if token_date != target:
                    raise LocalReviewPipelineError(f"stage provenance date conflict: {path}")
                target_evidence = True
        if not target_evidence:
            raise LocalReviewPipelineError(f"stage provenance missing exact date: {path}")
        materialized = dict(row)
        materialized["trade_date"] = target
        normalized.append(materialized)
    return normalized


def _selector_path(trade_date: str, selector_path: Path | str | None, selector_root: Path | str | None) -> Path:
    if selector_path is not None:
        path = Path(selector_path).absolute()
        if not path.is_file() or trade_date not in path.name:
            raise LocalReviewPipelineError(f"SELECTOR_EXACT_DATE_MISSING:{trade_date}")
        return path
    root = (Path(selector_root) if selector_root is not None else DEFAULT_SELECTOR_ROOT).absolute()
    candidates = sorted(root.rglob(f"selector_ready_current_to_{trade_date}*.parquet")) if root.is_dir() else []
    if len(candidates) != 1:
        label = "missing" if not candidates else "ambiguous"
        raise LocalReviewPipelineError(f"SELECTOR_EXACT_DATE_{label.upper()}:{trade_date}")
    return candidates[0]


def _selector_limit_pct(code: str, name: str) -> float:
    code_text = str(code)
    if code_text.endswith(".BJ"):
        return 30.0
    raw_code = code_text.split(".", 1)[0]
    if raw_code.startswith(("300", "301", "688")):
        return 20.0
    if "ST" in str(name).upper():
        return 5.0
    return 10.0


def _selector_pct(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _load_selector_name_map(dataset: Any, trade_date: str) -> dict[str, str]:
    target = _date8(trade_date)
    names: dict[str, str] = {}
    try:
        scanner = dataset.scanner(columns=_SELECTOR_NAME_COLUMNS, batch_size=65_536)
        for batch in scanner.to_batches():
            for raw in batch.to_pylist():
                raw_date = raw.get("trade_date")
                if not raw_date:
                    raise LocalReviewPipelineError("SELECTOR_NAME_DATE_MISSING")
                row_date = _date8(str(raw_date))
                if row_date > target:
                    raise LocalReviewPipelineError(f"SELECTOR_FUTURE_DATE:{row_date}:{target}")
                code = str(raw.get("ts_code") or "").strip()
                name = str(raw.get("name") or "").strip()
                if code and name:
                    # Frozen page name-map semantics: first historical name wins.
                    names.setdefault(code.split(".", 1)[0], name)
    except LocalReviewPipelineError:
        raise
    except Exception as exc:  # pragma: no cover - environment/read failures
        raise LocalReviewPipelineError(f"SELECTOR_NAME_MAP_READ_FAILED:{exc}") from exc
    return names


def _load_selector_rows(path: Path, trade_date: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    try:
        import pyarrow.dataset as ds

        dataset = ds.dataset(str(path), format="parquet")
        current = dataset.to_table(
            columns=_SELECTOR_CURRENT_COLUMNS,
            filter=ds.field("trade_date") == trade_date,
        ).to_pylist()
        mapping_rows = dataset.to_table(
            columns=_SELECTOR_MAPPING_COLUMNS,
            filter=ds.field("trade_date") == trade_date,
        ).to_pylist()
        selector_names = _load_selector_name_map(dataset, trade_date)
    except Exception as exc:  # pragma: no cover - exercised by environment failures
        raise LocalReviewPipelineError(f"SELECTOR_READ_FAILED:{path}:{exc}") from exc
    if not current:
        raise LocalReviewPipelineError(f"SELECTOR_EXACT_DATE_EMPTY:{trade_date}")
    mapping: dict[str, dict[str, Any]] = {}
    for raw in mapping_rows:
        code = str(raw.get("ts_code") or "").strip()
        if code:
            # Frozen load_market_rows semantics: mapping duplicates keep last.
            mapping[code] = dict(raw)
    normalized: list[dict[str, Any]] = []
    for raw in current:
        row = dict(raw)
        code = str(row.get("ts_code") or "").strip()
        if not code or not code.endswith((".SZ", ".SH", ".BJ")):
            continue
        mapped = mapping.get(code, {})
        row["trade_date"] = trade_date
        row["ts_code"] = code
        name = str(row.get("name") or row.get("stock_name") or "").strip()
        row["tdx_industry_code"] = mapped.get("tdx_industry_code")
        row["tdx_industry_name"] = mapped.get("tdx_industry_name")
        sector = mapped.get("tdx_industry_name")
        row["sector_name"] = "" if sector is None or (isinstance(sector, float) and math.isnan(sector)) else str(sector).strip()
        pct = _selector_pct(row.get("pct_chg"))
        limit_pct = _selector_limit_pct(code, name)
        row["limit_pct"] = limit_pct
        row["approx_limit_up"] = bool(pct is not None and pct >= limit_pct * 0.99)
        row["approx_limit_down"] = bool(pct is not None and pct <= -limit_pct * 0.99)
        normalized.append(row)
    if not normalized:
        raise LocalReviewPipelineError(f"SELECTOR_EXACT_DATE_NO_STOCK_ROWS:{trade_date}")
    return normalized, selector_names


def _default_public_reader(root: Path, trade_date: str) -> Mapping[str, Any]:
    package_root = Path(
        os.environ.get("REVIEW_CORE_SHARED_PACKAGE_ROOT", r"C:\Users\huang\Desktop\学习\v3_shared_data")
    ).absolute()
    if not package_root.is_dir():
        raise LocalReviewPipelineError(f"PUBLIC_FUPAN_SHARED_PACKAGE_MISSING:{package_root}")
    package_text = str(package_root)
    if package_text not in sys.path:
        sys.path.insert(0, package_text)
    try:
        from shared_data.public_fupan import read_public_fupan

        return read_public_fupan(root, trade_date)
    except Exception as exc:
        raise LocalReviewPipelineError(f"PUBLIC_FUPAN_EXACT_DATE_MISSING:{trade_date}:{exc}") from exc


def _validate_public_bundle(bundle: Mapping[str, Any], trade_date: str) -> dict[str, Any]:
    manifest = bundle.get("manifest")
    receipt = bundle.get("receipt")
    files = bundle.get("files")
    if not isinstance(manifest, Mapping) or not isinstance(receipt, Mapping) or not isinstance(files, Mapping):
        raise LocalReviewPipelineError(f"PUBLIC_FUPAN_PROVENANCE_MISSING:{trade_date}")
    if str(manifest.get("trade_date") or "") != trade_date or str(receipt.get("trade_date") or "") != trade_date:
        raise LocalReviewPipelineError(f"PUBLIC_FUPAN_DATE_MISMATCH:{trade_date}")
    run_id = str(manifest.get("run_id") or receipt.get("run_id") or "")
    if not run_id or str(receipt.get("run_id") or run_id) != run_id:
        raise LocalReviewPipelineError(f"PUBLIC_FUPAN_RUN_ID_MISMATCH:{trade_date}")
    if any(manifest.get(name) is not False or receipt.get(name) is not False for name in SAFETY_FLAGS):
        raise LocalReviewPipelineError(f"PUBLIC_FUPAN_UNSAFE:{trade_date}")
    required = {"plate.json", "lianban.json", "qingxu.json", "jiuyangongshe.html"}
    if not required <= {str(name) for name in files}:
        raise LocalReviewPipelineError(f"PUBLIC_FUPAN_RAW_FILES_MISSING:{trade_date}")
    return {
        "run_id": run_id,
        "manifest_sha256": str(receipt.get("manifest_sha256") or _sha_bytes(manifest)),
        "file_sha256": {str(name): hashlib.sha256(bytes(data)).hexdigest() for name, data in files.items()},
        "manifest": copy.deepcopy(dict(manifest)),
        "receipt": copy.deepcopy(dict(receipt)),
        "files": {str(name): bytes(data) for name, data in files.items()},
    }


def _stage_counts(stage_root: Path, trade_date: str) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    labels = {
        "4": "stage4_label",
        "5": "stage5_label",
        "6": "stage6_label",
        "7": "stage7_label",
    }
    for number, label in labels.items():
        matches = sorted(stage_root.glob(f"generated_stage{number}_*.csv")) if stage_root.is_dir() else []
        rows = _load_stage_rows(matches[0], trade_date, number) if matches else []
        counts: Counter[str] = Counter()
        for row in rows:
            value = str(row.get(label) or row.get("decision_label") or "未标注")
            counts[value] += 1
        result[f"stage{number}"] = dict(counts)
    return result


def _default_raw_loader(
    trade_date: str,
    *,
    public_bundle: Mapping[str, Any],
    selector_path: Path | str | None,
    selector_root: Path | str | None,
    tdx_root: Path | str | None,
    formal_pool_path: Path | str | None,
    review_pool_path: Path | str | None,
    stage_root: Path | str | None,
) -> dict[str, Any]:
    verified = _validate_public_bundle(public_bundle, trade_date)
    selector_file = _selector_path(trade_date, selector_path, selector_root)
    selector_rows, selector_names = _load_selector_rows(selector_file, trade_date)
    app_data = DEFAULT_APP_DATA_ROOT
    formal_path = Path(formal_pool_path) if formal_pool_path is not None else app_data / "formal_pools" / trade_date / f"formal_opening_pool_{trade_date}.csv"
    review_path = Path(review_pool_path) if review_pool_path is not None else app_data / "generated_pools" / trade_date / f"advisor_generated_premarket_pool_{trade_date}.csv"
    stages = Path(stage_root) if stage_root is not None else app_data / "generated_stages" / trade_date
    formal_rows, review_rows, _formal_signal_dates = _load_pool_inputs(formal_path, review_path, trade_date)
    stage_rows: list[dict[str, str]] = []
    for number in ("4", "5"):
        matches = sorted(stages.glob(f"generated_stage{number}_*.csv")) if stages.is_dir() else []
        if matches:
            stage_rows.extend(_load_stage_rows(matches[0], trade_date, number))
    name_map: dict[str, str] = {}
    for row in [*review_rows, *stage_rows]:
        code = str(row.get("ts_code") or row.get("stock_code") or "").split(".", 1)[0]
        name = str(row.get("name") or row.get("stock_name") or row.get("display_name") or "").replace("（选）", "")
        if code and name:
            name_map.setdefault(code, name)
    for code, name in selector_names.items():
        name_map.setdefault(code, name)

    files = verified["files"]
    with tempfile.TemporaryDirectory(prefix=f"review-core-public-{trade_date}-") as source_tmp:
        source_dir = Path(source_tmp)
        file_paths: dict[str, Path] = {}
        for name in ("plate.json", "lianban.json", "qingxu.json", "jiuyangongshe.html"):
            path = source_dir / name
            path.write_bytes(files[name])
            file_paths[name] = path
        try:
            raw = load_raw_page_inputs(
                trade_date,
                plate_json=file_paths["plate.json"],
                lianban_json=file_paths["lianban.json"],
                qingxu_json=file_paths["qingxu.json"],
                tdx_root=Path(tdx_root) if tdx_root is not None else DEFAULT_TDX_ROOT,
                name_map=name_map,
                jyg_html=file_paths["jiuyangongshe.html"],
            )
        except Exception as exc:
            raise LocalReviewPipelineError(f"RAW_PUBLIC_FUPAN_PARSE_FAILED:{trade_date}:{exc}") from exc
    raw.update(
        {
            "formal_rows": formal_rows,
            "review_rows": review_rows,
            "tplus1_rows": [],
            "stage_counts": _stage_counts(stages, trade_date),
            "rule_rows": [],
            "news_article_rows": [],
            "news_event_rows": [],
            "news_research_hit_rows": [],
            "news_event_source_paths": {},
            "morning_news_acceptance": {},
            "source_status_rows": list(raw.get("source_status") or []),
            "cannot_confirm_items": [],
            MARKET_SCOPE_FIELD: FULL_MARKET_SCOPE,
            MARKET_COMPLETENESS_FIELD: "FULL_MARKET_VERIFIED",
        }
    )
    return {
        "page_inputs": raw,
        "replay_rows": selector_rows,
        MARKET_SCOPE_FIELD: FULL_MARKET_SCOPE,
        MARKET_COMPLETENESS_FIELD: "FULL_MARKET_VERIFIED",
        "source_refs": [
            {"kind": "public_fupan_manifest", "path": f"public_fupan://{trade_date}/manifest.json", "sha256": verified["manifest_sha256"]},
            {"kind": "selector_ready_panel", "path": str(selector_file), "sha256": sha256_file(selector_file)},
        ],
        "public_identity": {
            "run_id": verified["run_id"],
            "manifest_sha256": verified["manifest_sha256"],
            "file_sha256": verified["file_sha256"],
        },
    }


def _video_for_page(
    trade_date: str,
    video_data_root: Path | str | None,
    video_loader: Callable[[str, Path | str | None], Mapping[str, Any]] | None,
) -> dict[str, Any] | None:
    if video_loader is not None:
        value = video_loader(trade_date, video_data_root)
        return dict(value) if value is not None else None
    try:
        manifest = inspect_bundle(trade_date, video_data_root or DEFAULT_DATA_ROOT)
    except Exception as exc:
        return {
            "trade_date": trade_date,
            "status": "CANNOT_CONFIRM",
            "date_scope": "DAILY_VIDEO_NOT_LOCKED",
            "bv_id": "",
            "cannot_confirm": [str(exc)],
        }
    return dict(manifest)


def _implementation_hashes() -> dict[str, str]:
    paths = {
        "producer_inputs.py": Path(__file__).with_name("producer_inputs.py"),
        "daily_replay_producer.py": Path(__file__).with_name("daily_replay_producer.py"),
        "fupan_page_producer.py": Path(__file__).with_name("fupan_page_producer.py"),
        "review_pipeline.py": Path(__file__),
    }
    return {name: sha256_file(path) for name, path in paths.items()}


def run_local_review_pipeline(
    trade_date: str,
    *,
    output_root: Path | str,
    data_root: Path | str | None = None,
    public_source_root: Path | str | None = None,
    selector_path: Path | str | None = None,
    selector_root: Path | str | None = None,
    tdx_root: Path | str | None = None,
    formal_pool_path: Path | str | None = None,
    review_pool_path: Path | str | None = None,
    stage_root: Path | str | None = None,
    video_data_root: Path | str | None = None,
    raw_loader: Callable[..., Mapping[str, Any]] | None = None,
    public_fupan_reader: Callable[[Path | str, str], Mapping[str, Any]] | None = None,
    video_loader: Callable[[str, Path | str | None], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    target = _date8(trade_date)
    root = (Path(data_root) if data_root is not None else Path(output_root)).absolute()
    output = Path(output_root).absolute()
    public_root = (Path(public_source_root) if public_source_root is not None else DEFAULT_PUBLIC_SOURCE_ROOT).absolute()
    reader = public_fupan_reader or _default_public_reader
    try:
        public_bundle = reader(public_root, target)
    except LocalReviewPipelineError:
        raise
    except Exception as exc:
        raise LocalReviewPipelineError(f"PUBLIC_FUPAN_EXACT_DATE_MISSING:{target}:{exc}") from exc
    verified_public = _validate_public_bundle(public_bundle, target)
    loader = raw_loader or _default_raw_loader
    loaded = loader(
        target,
        public_bundle=public_bundle,
        selector_path=selector_path,
        selector_root=selector_root,
        tdx_root=tdx_root,
        formal_pool_path=formal_pool_path,
        review_pool_path=review_pool_path,
        stage_root=stage_root,
    )
    if not isinstance(loaded, Mapping):
        raise LocalReviewPipelineError("LOCAL_RAW_LOADER_INVALID")
    page_inputs = loaded.get("page_inputs")
    replay_rows = loaded.get("replay_rows")
    if not isinstance(page_inputs, Mapping) or not isinstance(replay_rows, list) or not replay_rows:
        raise LocalReviewPipelineError(f"LOCAL_RAW_INPUTS_MISSING:{target}")
    market_scope = _validate_market_scope(loaded.get(MARKET_SCOPE_FIELD))
    market_completeness = _scope_completeness(market_scope)
    scoped_page_inputs = copy.deepcopy(dict(page_inputs))
    scoped_page_inputs[MARKET_SCOPE_FIELD] = market_scope
    scoped_page_inputs[MARKET_COMPLETENESS_FIELD] = market_completeness
    video = _video_for_page(target, video_data_root or root, video_loader)
    implementation = _implementation_hashes()
    source_refs = list(loaded.get("source_refs") or [])
    video_identity_fields = (
        "trade_date",
        "source_trade_date",
        "target_trade_date",
        "status",
        "date_scope",
        "bv_id",
        "title",
        "upload_date",
        "asr_status",
        "asr_segment_count",
        "gap_status",
        "gap_row_count",
        "targeted_spotcheck_count",
        "run_id",
        "manifest_sha256",
        "current_sha256",
        "current_path_sha256",
    )
    video_identity = {
        key: video.get(key)
        for key in video_identity_fields
        if isinstance(video, Mapping) and key in video
    }
    input_identity = {
        "schema": PIPELINE_SCHEMA,
        "trade_date": target,
        # The runtime root is part of provenance: two byte-identical video
        # manifests can still have different process accessibility on macOS
        # (for example Desktop privacy versus the managed service root).
        "video_data_root": str((Path(video_data_root) if video_data_root is not None else root).absolute()),
        "public": {
            "run_id": verified_public["run_id"],
            "manifest_sha256": verified_public["manifest_sha256"],
            "file_sha256": verified_public["file_sha256"],
        },
        "source_refs": source_refs,
        "market_scope": market_scope,
        "market_completeness": market_completeness,
        "page_inputs_sha256": _sha_bytes(scoped_page_inputs),
        "replay_rows_sha256": _sha_bytes(replay_rows),
        "video_sha256": _sha_bytes(video_identity),
        "implementation": implementation,
    }
    input_digest = hashlib.sha256(_canonical(input_identity)).hexdigest()
    run_id = f"local-review-{target}-{input_digest[:16]}"
    date_root = output / "local_review" / target
    run_dir = date_root / "runs" / run_id
    current_path = date_root / "current.json"
    manifest_path = run_dir / "manifest.json"
    receipt_path = run_dir / "receipt.json"
    if run_dir.is_dir():
        if not manifest_path.is_file() or not receipt_path.is_file():
            raise LocalReviewPipelineError(f"LOCAL_RUN_INCOMPLETE:{run_id}")
        try:
            existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            existing_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if (
                existing_manifest.get("run_id") != run_id
                or existing_manifest.get("trade_date") != target
                or existing_manifest.get("input_digest") != input_digest
                or existing_receipt.get("run_id") != run_id
                or existing_receipt.get("trade_date") != target
                or existing_receipt.get("manifest_sha256") != sha256_file(manifest_path)
            ):
                raise LocalReviewPipelineError(f"LOCAL_RUN_TAMPERED:{run_id}")
            if not current_path.is_file():
                raise LocalReviewPipelineError(f"LOCAL_CURRENT_MISSING:{run_id}")
            current = json.loads(current_path.read_text(encoding="utf-8"))
            if (
                current.get("run_id") != run_id
                or current.get("manifest_sha256") != sha256_file(manifest_path)
                or current.get("receipt_sha256") != sha256_file(receipt_path)
            ):
                raise LocalReviewPipelineError(f"LOCAL_CURRENT_TAMPERED:{run_id}")
        except LocalReviewPipelineError:
            raise
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise LocalReviewPipelineError(f"LOCAL_RUN_TAMPERED:{run_id}:{exc}") from exc
        return existing_receipt | {
            "idempotent": True,
            "current_path": str(current_path),
            "bundle_current_path": str(output / "review_bundle" / target / "current.json"),
        }
    run_dir.mkdir(parents=True, exist_ok=False)
    page_path = run_dir / f"fupan_payload_{target}.json"
    replay_dashboard_path = run_dir / f"replay_dashboard_{target}.json"
    semantic_path = run_dir / "local_semantic_model" / "independent_semantic_review.v1.json"
    try:
        page_payload = build_fupan_page_payload(target, scoped_page_inputs, video=video, run_id=run_id)
        page_payload = _mark_page_scope(page_payload, market_scope, replay_rows)
        replay_payload = build_daily_replay_payload(
            target,
            replay_rows,
            run_id=run_id,
            universe_scope=market_scope,
        )
        semantic_payload = copy.deepcopy(replay_payload.get("independent_review"))
        if not isinstance(semantic_payload, dict):
            raise LocalReviewPipelineError(f"LOCAL_SEMANTIC_REVIEW_MISSING:{target}")
        _atomic_json(page_path, page_payload)
        _atomic_json(replay_dashboard_path, replay_payload)
        _atomic_json(semantic_path, semantic_payload)
        from .review import build_review_bundle

        bundle_result = build_review_bundle(
            target,
            v3_payload_path=page_path,
            replay_review_path=semantic_path,
            video_data_root=video_data_root or root,
            output_root=output,
            page_source_kind="review_core_local_fupan_payload",
        )
        bundle_current_path = Path(bundle_result["current_path"])
        manifest = {
            "schema_version": PIPELINE_MANIFEST_SCHEMA,
            "trade_date": target,
            "run_id": run_id,
            "input_digest": input_digest,
            "page_inputs_sha256": input_identity["page_inputs_sha256"],
            "replay_rows_sha256": input_identity["replay_rows_sha256"],
            "video_sha256": input_identity["video_sha256"],
            "implementation_sha256": implementation,
            "source_refs": copy.deepcopy(source_refs),
            "public_identity": {"run_id": verified_public["run_id"], "manifest_sha256": verified_public["manifest_sha256"]},
            MARKET_SCOPE_FIELD: market_scope,
            MARKET_COMPLETENESS_FIELD: market_completeness,
            "page_path": str(page_path),
            "page_sha256": sha256_file(page_path),
            "replay_dashboard_path": str(replay_dashboard_path),
            "replay_dashboard_sha256": sha256_file(replay_dashboard_path),
            "independent_replay_path": str(semantic_path),
            "independent_replay_sha256": sha256_file(semantic_path),
            "bundle_current_path": str(bundle_current_path),
            "bundle_run_id": bundle_result.get("run_id", ""),
            "safety_flags": dict(SAFETY_FLAGS),
            **SAFETY_FLAGS,
        }
        _atomic_json(manifest_path, manifest)
        receipt = {
            "schema_version": PIPELINE_RECEIPT_SCHEMA,
            "status": bundle_result.get("status", "PARTIAL"),
            "trade_date": target,
            "run_id": run_id,
            "idempotent": False,
            "manifest_sha256": sha256_file(manifest_path),
            "page_path": str(page_path),
            "replay_path": str(semantic_path),
            "bundle_current_path": str(bundle_current_path),
            "bundle_run_id": bundle_result.get("run_id", ""),
            "video_status": (video or {}).get("status", "CANNOT_CONFIRM"),
            MARKET_SCOPE_FIELD: market_scope,
            MARKET_COMPLETENESS_FIELD: market_completeness,
            "safety_flags": dict(SAFETY_FLAGS),
            **SAFETY_FLAGS,
        }
        _atomic_json(receipt_path, receipt)
        _atomic_json(
            current_path,
            {
                "schema_version": PIPELINE_CURRENT_SCHEMA,
                "trade_date": target,
                "run_id": run_id,
                "run_path": f"local_review/{target}/runs/{run_id}",
                "manifest_path": f"local_review/{target}/runs/{run_id}/manifest.json",
                "receipt_path": f"local_review/{target}/runs/{run_id}/receipt.json",
                "manifest_sha256": sha256_file(manifest_path),
                "receipt_sha256": sha256_file(receipt_path),
                "safety_flags": dict(SAFETY_FLAGS),
            },
        )
        return {
            **receipt,
            "manifest_path": str(manifest_path),
            "current_path": str(current_path),
            "run_dir": str(run_dir),
            "bundle": bundle_result.get("bundle"),
            MARKET_SCOPE_FIELD: market_scope,
            MARKET_COMPLETENESS_FIELD: market_completeness,
        }
    except Exception:
        for path in sorted(run_dir.rglob("*"), reverse=True):
            if path.is_file() or path.is_symlink():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        run_dir.rmdir()
        raise


__all__ = ["LocalReviewPipelineError", "run_local_review_pipeline"]
