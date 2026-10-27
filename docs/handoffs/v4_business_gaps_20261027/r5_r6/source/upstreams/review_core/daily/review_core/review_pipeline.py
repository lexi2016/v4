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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .core import DEFAULT_DATA_ROOT, EvidenceValidationError, inspect_bundle, normalize_trade_date, sha256_file
from .adapters.selector import (
    SelectorSnapshotValidationError,
    normalize_cutoff,
    validate_selector_snapshot,
)
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

_PRESELECTION_POOL_SCHEMA = "v3_5.preselection_pool.v1"
_PRESELECTION_RECEIPT_SCHEMA = "v3_5.preselection_pool_receipt.v1"
_PRESELECTION_POOL_SPECS: dict[str, dict[str, str]] = {
    "a_d1_premarket_pool": {
        "source_role": "SHARED_VERIFIED_V192",
        "status_prefix": "V192_CANDIDATE_READY",
        "stage": "",
    },
    "a_d1_fupan_watchlist_pool": {
        "source_role": "VERIFIED_D1_FUPAN_REVIEW",
        "status_prefix": "FUPAN_WATCHLIST_POOL_READY",
        "stage": "",
    },
    "a_d1_stage7_fenshi_review_pool": {
        "source_role": "VERIFIED_D1_STAGE7_REPLAY",
        "status_prefix": "STAGE7_TAIL_POOL_READY",
        "stage": "stage7",
    },
}
_FORMAL_SOURCE_ROLE = "FORMAL_POOL_CSV"
_PRESELECTION_CANDIDATE_ROLES = frozenset(
    spec["source_role"] for spec in _PRESELECTION_POOL_SPECS.values()
)
_CANDIDATE_STATUS_MARKERS = frozenset(
    {
        "WATCH_ONLY",
        "TEST_ONLY",
        "CANDIDATE",
        "CANDIDATE_ONLY",
        "V192_CANDIDATE_READY",
    }
)
_CANDIDATE_POOL_IDS = frozenset(
    {
        "A_D1_PREMARKET_POOL",
        "A_D1_FUPAN_WATCHLIST_POOL",
        "A_D1_STAGE7_FENSHI_REVIEW_POOL",
    }
)
_SHA256_TEXT_RE = re.compile(r"^[0-9a-fA-F]{64}$")


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


def _qfq_partial_coverage(evidence: Any, *, trade_date: str, target_date: str | None, selector_sha: str,
                          selector_path: Path, selector_rows: int, tdx_rows: int) -> dict[str, Any] | None:
    if evidence is None:
        return None
    if not target_date or _date8(target_date)<=_date8(trade_date):raise LocalReviewPipelineError('QFQ_TARGET_DATE_INVALID')
    if not isinstance(evidence, Mapping):raise LocalReviewPipelineError('QFQ_COVERAGE_EVIDENCE_INVALID')
    docs=[]
    for label in ('a_receipt','dispatch_receipt'):
        ref=evidence.get(label)
        if not isinstance(ref,Mapping):raise LocalReviewPipelineError('QFQ_COVERAGE_REF_MISSING:'+label)
        path=Path(str(ref.get('path') or ''));digest=str(ref.get('sha256') or '')
        if (not path.is_absolute() or path.is_symlink() or not path.is_file()
            or re.fullmatch(r'[0-9a-f]{64}',digest) is None):
            raise LocalReviewPipelineError('QFQ_COVERAGE_REF_INVALID:'+label)
        try:
            raw=path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=digest:raise LocalReviewPipelineError('QFQ_COVERAGE_REF_INVALID:'+label)
            doc=json.loads(raw)
        except (ValueError,OSError):raise LocalReviewPipelineError('QFQ_COVERAGE_DOCUMENT_INVALID:'+label) from None
        if not isinstance(doc,dict):raise LocalReviewPipelineError('QFQ_COVERAGE_DOCUMENT_INVALID:'+label)
        docs.append((path,digest,doc))
    (a_path,a_sha,a),(dispatch_path,dispatch_sha,dispatch)=docs
    formula=a.get('formula')
    if not isinstance(formula,Mapping):raise LocalReviewPipelineError('QFQ_FORMULA_MISSING')
    if (str(a.get('target_date'))!=trade_date or a.get('status')!='PARTIAL'
        or a.get('authority_status')!='REBUILD_REQUIRED' or a.get('reason')!='A_SYNC_AUTHORITY_REBUILD_REQUIRED'
        or str(formula.get('target_date'))!=trade_date or str(formula.get('asof_date'))!=trade_date
        or formula.get('status')!='READY' or formula.get('pit_certified') is not False
        or formula.get('selector_pointer_ready') is not True or a.get('selector_sha256')!=selector_sha
        or formula.get('selector_sha256')!=selector_sha or str(a.get('selector'))!=str(selector_path)
        or str(formula.get('selector'))!=str(selector_path)):
        raise LocalReviewPipelineError('QFQ_RECEIPT_BINDING_MISMATCH')
    generation=str(formula.get('generation_id') or '')
    accepted=a.get('accepted_count');total=a.get('target_count');quarantine=a.get('quarantine_count')
    if (re.fullmatch(r'[0-9a-f]{64}',generation) is None or any(type(x) is not int for x in (accepted,total,quarantine))
        or accepted<=0 or quarantine<=0 or accepted+quarantine!=total or selector_rows!=accepted or tdx_rows<=0):
        raise LocalReviewPipelineError('QFQ_COVERAGE_COUNTS_INVALID')
    if (dispatch.get('schema_version')!='v3_5.dispatch.v1' or dispatch.get('mode')!='LIVE'
        or dispatch.get('business_date')!=trade_date or dispatch.get('target_date')!=trade_date
        or 'research_panel_daily_a' not in dispatch.get('selected_workload_ids',[])
        or any(item.get(k) is not False for item in (a,formula,dispatch) for k in SAFETY_FLAGS)):
        raise LocalReviewPipelineError('QFQ_DISPATCH_BINDING_MISMATCH')
    matches=[x for x in dispatch.get('workload_results',[]) if isinstance(x,dict) and x.get('workload_id')=='research_panel_daily_a']
    if (len(matches)!=1 or matches[0].get('status')!='SUCCEEDED'
        or matches[0].get('reason')!=a.get('reason') or matches[0].get('accepted_count')!=accepted
        or matches[0].get('target_count')!=total or matches[0].get('quarantine_count')!=quarantine):
        raise LocalReviewPipelineError('QFQ_DISPATCH_RESULT_MISMATCH')
    try:
        available=datetime.fromisoformat(str(dispatch['finished_at']).replace('Z','+00:00'))
        if available.utcoffset() is None or available.astimezone(timezone.utc)>datetime.now(timezone.utc):raise ValueError('clock')
    except (ValueError,KeyError,TypeError):raise LocalReviewPipelineError('QFQ_AVAILABLE_TIME_INVALID') from None
    return {'schema_version':'review_core.qfq_partial_coverage.v1','source_date':trade_date,'target_date':_date8(target_date),
        'selector_sha256':selector_sha,'selector_path':str(selector_path),'generation_id':generation,'available_at':available.isoformat(),
        'a_receipt_path':str(a_path),'a_receipt_sha256':a_sha,'dispatch_receipt_path':str(dispatch_path),
        'dispatch_receipt_sha256':dispatch_sha,'accepted_count':accepted,'target_count':total,
        'quarantine_count':quarantine,'selector_rows':selector_rows,'tdx_daily_rows':tdx_rows,
        'authority_status':'PARTIAL','pit_certified':False,'pre_cutoff_capture_verified':False,
        'source_merge_role':'SOURCE_ONLY','stage_selection_eligible':False,**SAFETY_FLAGS}


def _mark_page_scope(page_payload: Mapping[str, Any], scope: str, replay_rows: list[Mapping[str, Any]], coverage: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Attach and enforce the universe contract at the page/replay integration seam.

    ``fupan_page_producer`` is intentionally kept backwards compatible.  The
    pipeline owns the provenance boundary and removes full-market wording from
    a proxy payload before it can reach ReviewBundle or a page consumer.
    """

    result = copy.deepcopy(dict(page_payload))
    completeness = "PARTIAL_COVERAGE" if coverage else _scope_completeness(scope)
    result[MARKET_SCOPE_FIELD] = scope
    result[MARKET_COMPLETENESS_FIELD] = completeness
    if coverage:
        result["coverage_evidence"] = copy.deepcopy(dict(coverage))
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
    if coverage:
        data_completeness.update(status="PARTIAL_COVERAGE", meaning="覆盖不完整，全市场宽度与阶段不能确认。")
        result["cannot_confirm_items"] = [*list(result.get("cannot_confirm_items") or []),
            {"trade_date": result.get("trade_date"), "status": "CANNOT_CONFIRM_PARTIAL_COVERAGE", "description": "覆盖不完整，不推导全市场宽度或阶段。"}]
        result["market_rows"] = []
        for row in list(result.get("anchor_rows") or []):
            if isinstance(row, dict) and str(row.get("role") or "").startswith("全市场"):
                row["role"] = "部分覆盖观察";row["boundary"] = "覆盖不完整，不代表全市场。"
        for card in list(result.get("summary_cards") or []):
            if isinstance(card,dict) and card.get("title") == "市场宽度":
                card.update(title="部分覆盖",value="全市场宽度不能确认",body="覆盖不完整。")
        if isinstance(result.get("summary"),dict):
            result["summary"].update(market_completeness="PARTIAL_COVERAGE",one_line="部分覆盖复盘；全市场宽度与阶段 CANNOT_CONFIRM。")
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


def _read_verified_pool_json(path: Path, label: str) -> dict[str, Any]:
    """Read one immutable, regular JSON pool or receipt file."""

    if path.is_symlink() or not path.is_file():
        raise LocalReviewPipelineError(f"POOL_FILE_MISSING_OR_NONREGULAR:{label}:{path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise LocalReviewPipelineError(f"POOL_JSON_INVALID:{label}:{path}:{exc}") from exc
    if not isinstance(value, Mapping):
        raise LocalReviewPipelineError(f"POOL_JSON_OBJECT_REQUIRED:{label}:{path}")
    return dict(value)


def _verified_sha(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA256_TEXT_RE.fullmatch(text):
        raise LocalReviewPipelineError(f"POOL_{label}_SHA_INVALID")
    return text


def _candidate_row_reasons(row: Mapping[str, Any]) -> list[str]:
    """Return explicit candidate/watch markers that cannot enter formal rows."""

    reasons: list[str] = []
    roles = {
        str(row.get(field) or "").strip().upper()
        for field in ("source_role", "input_source_role", "role", "pool_role")
    }
    for role in sorted(value for value in roles if value):
        if (
            role in _PRESELECTION_CANDIDATE_ROLES
            or role in _CANDIDATE_STATUS_MARKERS
            or "CANDIDATE" in role
            or "WATCH_ONLY" in role
            or "TEST_ONLY" in role
        ):
            reasons.append(f"candidate_source_role={role}")
    values = (
        row.get("status"),
        row.get("recommendation_status"),
        row.get("classification"),
        row.get("row_type"),
        row.get("input_type"),
        row.get("pool_id"),
    )
    for value in values:
        marker = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
        if not marker:
            continue
        if (
            marker in _CANDIDATE_STATUS_MARKERS
            or marker in _CANDIDATE_POOL_IDS
            or "CANDIDATE" in marker
            or "WATCH_ONLY" in marker
            or "TEST_ONLY" in marker
        ):
            reasons.append(f"candidate_marker={marker}")
    for field in ("candidate_only", "is_candidate", "watch_only", "test_only"):
        value = row.get(field)
        if value is True or str(value or "").strip().lower() == "true":
            reasons.append(f"candidate_flag={field}")
    for field in ("formal_pool_write", "formal_recommendation_allowed", "stage4_6_materialized"):
        value = row.get(field)
        if value is False or (isinstance(value, str) and value.strip().lower() == "false"):
            reasons.append(f"candidate_flag={field}=false")
    if not any(str(row.get(field) or "").strip() for field in ("stock_code", "ts_code", "code", "symbol")):
        reasons.append("required_stock_code_missing")
    if not str(row.get("signal_date") or "").strip():
        reasons.append("required_signal_date_missing")
    return sorted(set(reasons))


def _validate_explicit_formal_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    path: Path,
    formal_observed: Any,
    source_role: str,
) -> None:
    """Fail closed unless an explicit, role-compliant formal CSV is supplied."""

    if formal_observed is not True:
        raise LocalReviewPipelineError(
            f"FORMAL_POOL_OBSERVED_EXPLICIT_TRUE_REQUIRED:{path}"
        )
    if source_role != _FORMAL_SOURCE_ROLE:
        raise LocalReviewPipelineError(
            f"FORMAL_POOL_SOURCE_ROLE_INVALID:{path}:{source_role}"
        )
    violations: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            violations.append(f"row={index}:not_mapping")
            continue
        reasons = _candidate_row_reasons(row)
        if reasons:
            violations.append(f"row={index}:" + ",".join(reasons))
    if violations:
        raise LocalReviewPipelineError(
            f"FORMAL_POOL_SOURCE_NOT_COMPLIANT:{path}:" + ";".join(violations)
        )


def _preselection_state_data_root(public_source_root: Path) -> Path | None:
    """Return the sibling v3.5 state/data root for the canonical public root."""

    if (
        public_source_root.name != "data"
        or public_source_root.parent.name != ".runtime"
        or public_source_root.parent.parent.name != "v3_shared_data"
        or public_source_root.parent.parent.parent.name != "workspace"
        or public_source_root.parent.parent.parent.parent.name != "state"
    ):
        return None
    return public_source_root.parent.parent.parent.parent / "data"


def _verify_preselection_source_files(
    source_path: str,
    target: str,
    pool_id: str,
    public_source_root: Path | str | None,
) -> tuple[list[Path], str]:
    """Resolve and hash every declared upstream source file.

    v3.5 records one relative V192 artifact path, or a ``|``-separated pair
    of absolute manifest/data paths for the D-1 replay pools.  The producer
    computes a single-file SHA directly and a multi-file SHA as
    ``sha256(concat(file_sha256_ascii))``; the consumer must recompute that
    value from regular files instead of trusting the pool declaration.
    """

    entries = [item.strip() for item in source_path.split("|") if item.strip()]
    if not entries:
        raise LocalReviewPipelineError(f"POOL_SOURCE_PATH_MISSING:{pool_id}")
    public_root: Path | None = None
    state_data_root: Path | None = None
    if public_source_root is not None:
        public_root = Path(public_source_root).absolute()
        if public_root.is_symlink() or not public_root.is_dir():
            raise LocalReviewPipelineError(f"POOL_SOURCE_ROOT_INVALID:{pool_id}")
        state_data_root = _preselection_state_data_root(public_root)
        if state_data_root is None:
            raise LocalReviewPipelineError(f"POOL_SOURCE_ROOT_INVALID:{pool_id}")

    resolved: list[Path] = []
    hashes: list[str] = []
    for entry in entries:
        declared = Path(entry)
        if declared.is_absolute():
            if state_data_root is None:
                raise LocalReviewPipelineError(f"POOL_SOURCE_ROOT_MISSING:{pool_id}")
            raw_candidate = declared
            candidate = raw_candidate.resolve(strict=False)
            try:
                candidate.relative_to(state_data_root)
            except ValueError as exc:
                raise LocalReviewPipelineError(f"POOL_SOURCE_PATH_OUTSIDE_STATE_DATA:{pool_id}") from exc
        else:
            if public_root is None:
                raise LocalReviewPipelineError(f"POOL_SOURCE_ROOT_MISSING:{pool_id}")
            raw_candidate = public_root / declared
            candidate = raw_candidate.resolve(strict=False)
            try:
                candidate.relative_to(public_root)
            except ValueError as exc:
                raise LocalReviewPipelineError(f"POOL_SOURCE_PATH_OUTSIDE_PUBLIC_ROOT:{pool_id}") from exc
        if target not in candidate.parts:
            raise LocalReviewPipelineError(f"POOL_SOURCE_PATH_DATE_MISMATCH:{pool_id}")
        if raw_candidate.is_symlink() or candidate.is_symlink() or not candidate.is_file():
            raise LocalReviewPipelineError(f"POOL_SOURCE_FILE_MISSING_OR_NONREGULAR:{pool_id}:{candidate}")
        resolved.append(candidate)
        hashes.append(sha256_file(candidate))

    combined = hashes[0] if len(hashes) == 1 else hashlib.sha256("".join(hashes).encode("ascii")).hexdigest()
    return resolved, combined


def _preselection_pool_root_from_tdx(tdx_root: Path | str | None, trade_date: str) -> Path | None:
    """Derive the v3.5 state from the explicit ``research_panel_daily/tdx`` root.

    The derivation is deliberately structural and exact.  It never scans a
    state tree, follows a ``current``/``latest`` pointer, or chooses by mtime.
    A non-v3.5-shaped test/root keeps the legacy CSV fallback untouched.
    """

    if tdx_root is None:
        return None
    root = Path(tdx_root).absolute()
    if root.name != "tdx" or root.parent.name != "research_panel_daily":
        return None
    candidate = root.parent.parent / "data" / "preselection_pools" / _date8(trade_date)
    return candidate if candidate.is_dir() else None


def _load_verified_preselection_pools(
    pool_root: Path | str,
    trade_date: str,
    *,
    public_source_root: Path | str | None = None,
) -> dict[str, Any]:
    """Load the exact verified D-1 pool trio for one target date.

    The pool JSONs are a v3.5 materialization boundary, not a replacement for
    the producer.  Both the artifact and its colocated receipt are checked;
    the date-local ``current.json``/``latest.json`` pointers are intentionally
    ignored so a stale pointer cannot silently select another day.
    """

    target = _date8(trade_date)
    root = Path(pool_root).absolute()
    if root.is_symlink() or not root.is_dir() or root.name != target or root.parent.name != "preselection_pools":
        raise LocalReviewPipelineError(f"POOL_ROOT_EXACT_DATE_INVALID:{root}:{target}")

    loaded: dict[str, dict[str, Any]] = {}
    source_date: str | None = None
    for pool_id, spec in _PRESELECTION_POOL_SPECS.items():
        artifact_path = root / f"{pool_id}.json"
        receipt_path = root / "receipts" / f"{pool_id}.json"
        artifact = _read_verified_pool_json(artifact_path, f"artifact:{pool_id}")
        receipt = _read_verified_pool_json(receipt_path, f"receipt:{pool_id}")

        if artifact.get("schema_version") != _PRESELECTION_POOL_SCHEMA:
            raise LocalReviewPipelineError(f"POOL_SCHEMA_MISMATCH:{pool_id}")
        if artifact.get("pool_id") != pool_id or receipt.get("pool_id") != pool_id:
            raise LocalReviewPipelineError(f"POOL_ID_MISMATCH:{pool_id}")
        if artifact.get("trade_date") != target or receipt.get("trade_date") != target:
            raise LocalReviewPipelineError(f"POOL_DATE_MISMATCH:{pool_id}")
        artifact_target = artifact.get("target_date")
        if artifact_target not in (None, "") and _date8(str(artifact_target)) != target:
            raise LocalReviewPipelineError(f"POOL_TARGET_DATE_MISMATCH:{pool_id}")
        if receipt.get("schema_version") != _PRESELECTION_RECEIPT_SCHEMA:
            raise LocalReviewPipelineError(f"POOL_RECEIPT_SCHEMA_MISMATCH:{pool_id}")
        expected_artifact_path = f"preselection_pools/{target}/{pool_id}.json"
        if receipt.get("artifact_path") != expected_artifact_path:
            raise LocalReviewPipelineError(f"POOL_RECEIPT_PATH_MISMATCH:{pool_id}")
        artifact_sha = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        receipt_artifact_sha = _verified_sha(receipt.get("artifact_sha256"), "ARTIFACT")
        if receipt_artifact_sha != artifact_sha:
            raise LocalReviewPipelineError(f"POOL_ARTIFACT_SHA_MISMATCH:{pool_id}")
        declared_source_sha = _verified_sha(artifact.get("source_sha256"), "SOURCE")
        receipt_source_sha = _verified_sha(receipt.get("source_sha256"), "SOURCE")
        if declared_source_sha != receipt_source_sha:
            raise LocalReviewPipelineError(f"POOL_SOURCE_SHA_MISMATCH:{pool_id}")
        source_artifact_sha = artifact.get("source_artifact_sha256")
        if source_artifact_sha not in (None, "") and _verified_sha(source_artifact_sha, "SOURCE") != declared_source_sha:
            raise LocalReviewPipelineError(f"POOL_SOURCE_SHA_MISMATCH:{pool_id}")
        if artifact.get("source_role") != spec["source_role"] or receipt.get("source_role") != spec["source_role"]:
            raise LocalReviewPipelineError(f"POOL_SOURCE_ROLE_MISMATCH:{pool_id}")
        if pool_id == "a_d1_premarket_pool" and (
            artifact.get("formal_observed") is True
            or receipt.get("formal_observed") is True
        ):
            raise LocalReviewPipelineError(
                f"POOL_CANDIDATE_MARKED_FORMAL:{pool_id}"
            )
        artifact_run_id = artifact.get("source_run_id")
        receipt_run_id = receipt.get("source_run_id")
        if artifact_run_id not in (None, "") and receipt_run_id not in (None, "") and artifact_run_id != receipt_run_id:
            raise LocalReviewPipelineError(f"POOL_SOURCE_RUN_ID_MISMATCH:{pool_id}")
        status = str(artifact.get("status") or "")
        if not status.startswith(spec["status_prefix"]):
            raise LocalReviewPipelineError(f"POOL_STATUS_NOT_READY:{pool_id}")
        source_path = artifact.get("source_path")
        if not isinstance(source_path, str) or not source_path.strip() or "\x00" in source_path:
            raise LocalReviewPipelineError(f"POOL_SOURCE_PATH_MISSING:{pool_id}")
        if target not in source_path:
            raise LocalReviewPipelineError(f"POOL_SOURCE_PATH_DATE_MISMATCH:{pool_id}")
        for flag in SAFETY_FLAGS:
            if artifact.get(flag) is not False:
                raise LocalReviewPipelineError(f"POOL_UNSAFE:{pool_id}:{flag}")
            if flag in receipt and receipt.get(flag) is not False:
                raise LocalReviewPipelineError(f"POOL_UNSAFE:{pool_id}:{flag}")
        source_paths, verified_source_sha = _verify_preselection_source_files(
            source_path,
            target,
            pool_id,
            public_source_root,
        )
        if verified_source_sha != declared_source_sha:
            raise LocalReviewPipelineError(f"POOL_SOURCE_SHA_MISMATCH:{pool_id}")

        rows = artifact.get("rows")
        if not isinstance(rows, list) or not rows:
            raise LocalReviewPipelineError(f"POOL_ROWS_MISSING:{pool_id}")
        source_row_count = artifact.get("source_row_count")
        if source_row_count not in (None, ""):
            if isinstance(source_row_count, bool) or not isinstance(source_row_count, int) or source_row_count != len(rows):
                raise LocalReviewPipelineError(f"POOL_ROW_COUNT_MISMATCH:{pool_id}")
        receipt_row_count = receipt.get("source_row_count")
        if receipt_row_count not in (None, ""):
            if isinstance(receipt_row_count, bool) or not isinstance(receipt_row_count, int) or receipt_row_count != len(rows):
                raise LocalReviewPipelineError(f"POOL_RECEIPT_ROW_COUNT_MISMATCH:{pool_id}")
        if source_row_count not in (None, "") and receipt_row_count not in (None, "") and source_row_count != receipt_row_count:
            raise LocalReviewPipelineError(f"POOL_ROW_COUNT_MISMATCH:{pool_id}")

        artifact_signal = artifact.get("signal_date")
        if artifact_signal not in (None, ""):
            parsed_signal = _date8(str(artifact_signal))
            if parsed_signal >= target:
                raise LocalReviewPipelineError(f"POOL_SIGNAL_DATE_MISMATCH:{pool_id}")
            if source_date is None:
                source_date = parsed_signal
            elif source_date != parsed_signal:
                raise LocalReviewPipelineError(f"POOL_SIGNAL_DATE_MISMATCH:{pool_id}")
        loaded[pool_id] = {
            "artifact": artifact,
            "receipt": receipt,
            "artifact_path": artifact_path,
            "receipt_path": receipt_path,
            "artifact_sha256": artifact_sha,
            "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            "rows": rows,
            "source_role": spec["source_role"],
            "status": status,
            "source_sha256": declared_source_sha,
            "source_path": source_path,
            "source_paths": source_paths,
            "verified_source_sha256": verified_source_sha,
        }

    if source_date is None:
        raise LocalReviewPipelineError("POOL_SIGNAL_DATE_MISSING:a_d1_premarket_pool")
    for pool_id, item in loaded.items():
        for index, raw_row in enumerate(item["rows"]):
            if not isinstance(raw_row, Mapping):
                raise LocalReviewPipelineError(f"POOL_ROW_INVALID:{pool_id}:{index}")
            row = dict(raw_row)
            if row.get("pool_id") != pool_id:
                raise LocalReviewPipelineError(f"POOL_ROW_POOL_ID_MISMATCH:{pool_id}:{index}")
            row_trade = row.get("trade_date") or row.get("target_date") or row.get("target_trade_date")
            if not row_trade or _date8(str(row_trade)) != target:
                raise LocalReviewPipelineError(f"POOL_ROW_DATE_MISMATCH:{pool_id}:{index}")
            for date_field in ("trade_date", "target_date", "target_trade_date"):
                value = row.get(date_field)
                if value not in (None, "") and _date8(str(value)) != target:
                    raise LocalReviewPipelineError(f"POOL_ROW_TARGET_DATE_MISMATCH:{pool_id}:{index}")
            row_signal = row.get("signal_date")
            if not row_signal or _date8(str(row_signal)) != source_date:
                raise LocalReviewPipelineError(f"POOL_ROW_SIGNAL_DATE_MISMATCH:{pool_id}:{index}")
            for flag in SAFETY_FLAGS:
                if row.get(flag) is not False:
                    raise LocalReviewPipelineError(f"POOL_UNSAFE:{pool_id}:{index}:{flag}")
            item["rows"][index] = row

    stage_rows = loaded["a_d1_stage7_fenshi_review_pool"]["rows"]
    stage7_counts: Counter[str] = Counter()
    for index, row in enumerate(stage_rows):
        label = str(row.get("stage7_label") or row.get("stage_id") or "").strip()
        if not label:
            raise LocalReviewPipelineError(f"POOL_STAGE7_LABEL_MISSING:{index}")
        stage7_counts[label] += 1

    evidence: list[dict[str, Any]] = []
    for pool_id, item in loaded.items():
        evidence.append(
            {
                "pool_id": pool_id,
                "status": item["status"],
                "trade_date": target,
                "signal_date": source_date,
                "row_count": len(item["rows"]),
                "source_role": item["source_role"],
                "source_sha256": item["source_sha256"],
                "source_path": item["source_path"],
                "source_paths": [str(path) for path in item["source_paths"]],
                "source_file_refs": [
                    {"path": str(path), "sha256": sha256_file(path)} for path in item["source_paths"]
                ],
                "verified_source_sha256": item["verified_source_sha256"],
                "artifact_path": str(item["artifact_path"]),
                "artifact_sha256": item["artifact_sha256"],
                "receipt_path": str(item["receipt_path"]),
                "receipt_sha256": item["receipt_sha256"],
                "safety_flags": dict(SAFETY_FLAGS),
                "formal_observed": False,
                "formal_pool_observed": False,
                "formal_execution_attempted": False,
                "lineage_role": (
                    "PRIOR_PLAN_CANDIDATE"
                    if pool_id == "a_d1_premarket_pool"
                    else "PRIOR_PLAN_SUPPORT"
                ),
            }
        )
    return {
        "pool_root": str(root),
        "trade_date": target,
        "signal_date": source_date,
        # The verified V192 premarket pool is a candidate input, never a
        # formal pool observation.  Keep its rows as explicit D-1 lineage so
        # prior-plan generation can still consume the candidate evidence.
        "formal_rows": [],
        "prior_plan_lineage_rows": copy.deepcopy(loaded["a_d1_premarket_pool"]["rows"]),
        "review_rows": copy.deepcopy(loaded["a_d1_fupan_watchlist_pool"]["rows"]),
        "stage_rows": copy.deepcopy(stage_rows),
        "formal_observed": False,
        "formal_pool_observed": False,
        "formal_execution_attempted": False,
        "formal_source_role": "FORMAL_POOL_NOT_OBSERVED",
        "formal_pool_status": "CANNOT_CONFIRM_FORMAL_POOL_NOT_MATERIALIZED",
        "stage_counts": {"stage4": {}, "stage5": {}, "stage6": {}, "stage7": dict(stage7_counts)},
        "evidence": evidence,
    }


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
        path.is_symlink()
        or not path.is_file()
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


def _selector_path(
    trade_date: str,
    selector_path: Path | str | None,
    selector_root: Path | str | None,
    *,
    allow_unqualified: bool = False,
) -> Path:
    if selector_path is not None:
        path = Path(selector_path).absolute()
        if not path.is_file() or (not allow_unqualified and trade_date not in path.name):
            raise LocalReviewPipelineError(f"SELECTOR_EXACT_DATE_MISSING:{trade_date}")
        return path
    root = (Path(selector_root) if selector_root is not None else DEFAULT_SELECTOR_ROOT).absolute()
    candidates = sorted(root.rglob(f"selector_ready_current_to_{trade_date}*.parquet")) if root.is_dir() else []
    if len(candidates) != 1:
        label = "missing" if not candidates else "ambiguous"
        raise LocalReviewPipelineError(f"SELECTOR_EXACT_DATE_{label.upper()}:{trade_date}")
    return candidates[0]


def _selector_consumer_identity(
    trade_date: str,
    selector_path: Path | str | None,
    selector_root: Path | str | None,
    *,
    expected_sha256: str | None = None,
    expected_target_trade_date: str | None = None,
    expected_cutoff: str | None = None,
    expected_source_date: str | None = None,
    expected_pit_safe: bool | None = None,
    selector_metadata: Mapping[str, Any] | None = None,
    _exact_data_proof: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Revalidate the exact selector snapshot at the local consumer boundary.

    The old consumer path treated a regular file (and, optionally, its
    filename) as a ready selector.  A file is only an address, however; it is
    not proof of source date, forward target, PIT cutoff, or readiness.  This
    function therefore always uses the strict adapter and returns a
    fail-closed identity while those pins are incomplete.  ``_exact_data_proof``
    is supplied only after the consumer has read non-empty rows whose maximum
    date is the requested exact date.  That second observation is the sole
    place where a complete identity may become READY.
    """

    target = _date8(trade_date)
    path = _selector_path(
        target,
        selector_path,
        selector_root,
        allow_unqualified=True,
    )
    resolved = path.expanduser().resolve(strict=False)
    if not path.is_file() or path.is_symlink() or not resolved.is_file():
        raise LocalReviewPipelineError(f"SELECTOR_CONSUMER_PATH_NOT_REGULAR:{path}")
    if expected_sha256 is not None:
        expected = str(expected_sha256).lower()
        if not _SHA256_TEXT_RE.fullmatch(expected):
            raise LocalReviewPipelineError("SELECTOR_CONSUMER_SHA_INVALID")
    else:
        expected = ""
    try:
        actual = sha256_file(path)
    except OSError as exc:
        raise LocalReviewPipelineError(f"SELECTOR_CONSUMER_SHA_READ_FAILED:{path}") from exc
    if expected and actual != expected:
        raise LocalReviewPipelineError(
            f"SELECTOR_CONSUMER_SHA_MISMATCH:{path}:expected={expected}:actual={actual}"
        )

    # ``trade_date`` is the explicit source pin at this consumer boundary.
    # It is never inferred from a filename.  A producer-declared source date
    # or an explicit caller pin must agree with it.
    source_pin = _date8(expected_source_date) if expected_source_date not in (None, "") else target
    expected_target = ""
    if expected_target_trade_date not in (None, ""):
        try:
            expected_target = _date8(expected_target_trade_date)
        except (TypeError, ValueError) as exc:
            raise LocalReviewPipelineError("SELECTOR_CONSUMER_TARGET_DATE_INVALID") from exc
        if expected_target <= source_pin:
            raise LocalReviewPipelineError("SELECTOR_CONSUMER_TARGET_DATE_NOT_FORWARD")
    cutoff = ""
    if expected_cutoff not in (None, ""):
        try:
            cutoff = normalize_cutoff(expected_cutoff, source_pin)
        except SelectorSnapshotValidationError as exc:
            raise LocalReviewPipelineError(f"SELECTOR_CONSUMER_CUTOFF_INVALID:{exc}") from exc

    metadata = dict(selector_metadata or {})
    # These are explicit consumer pins, not defaults from a filename.  Do not
    # add PIT or a ready signal before exact rows have been observed.
    metadata.setdefault("source_date", source_pin)
    if expected_target:
        metadata.setdefault("target_trade_date", expected_target)
    if cutoff:
        metadata.setdefault("cutoff", cutoff)
    if expected_pit_safe is not None:
        metadata.setdefault("pit_safe", expected_pit_safe)
    if expected:
        metadata.setdefault("selector_sha256", expected)

    proof_ok = False
    proof_reason = "SELECTOR_EXACT_DATA_UNVERIFIED"
    if isinstance(_exact_data_proof, Mapping):
        rows = _exact_data_proof.get("rows")
        if isinstance(rows, list) and rows:
            dates: list[str] = []
            try:
                for row in rows:
                    if not isinstance(row, Mapping) or row.get("trade_date") in (None, ""):
                        raise ValueError("row date missing")
                    dates.append(_date8(row.get("trade_date")))
                max_date = _date8(_exact_data_proof.get("max_date") or max(dates))
            except (TypeError, ValueError):
                max_date = ""
            if dates and all(row_date == target for row_date in dates) and max_date == target:
                proof_ok = True
            else:
                proof_reason = "SELECTOR_EXACT_DATA_DATE_MISMATCH"
        else:
            proof_reason = "SELECTOR_EXACT_DATA_ROWS_MISSING"

    # An exact-data observation may complete the consumer-side PIT proof for
    # the explicit source pin.  A caller-provided false value remains unsafe;
    # a true value is not trusted until this branch is reached.
    if proof_ok:
        metadata.setdefault("pit_safe", True)
        metadata.setdefault("signal", "SELECTOR_READY")

    try:
        identity = validate_selector_snapshot(
            path,
            expected_target_trade_date=expected_target or None,
            expected_source_date=source_pin,
            expected_cutoff=cutoff or None,
            expected_pit_safe=expected_pit_safe,
            expected_sha256=expected or None,
            metadata=metadata,
        )
    except SelectorSnapshotValidationError as exc:
        reason = str(exc) or type(exc).__name__
        # Hash/path/date mismatches are tamper or identity errors, not a
        # harmless incomplete pin.  Preserve the old hard failure at the
        # consumer boundary while allowing missing evidence to remain a
        # typed CANNOT_CONFIRM identity for the loader.
        hard_failures = (
            "SHA_MISMATCH",
            "POINTER_PATH_MISMATCH",
            "PATH_DATE_MISMATCH",
            "TARGET_TRADE_DATE_NOT_FORWARD",
            "TARGET_TRADE_DATE_MISMATCH",
            "SOURCE_DATE_MISMATCH",
            "PIT_DATE_MISMATCH",
            "CUTOFF_DATE_MISMATCH",
            "CUTOFF_NOT_EXPECTED",
            "CUTOFF_INVALID",
            "SOURCE_DATE_INVALID",
            "TARGET_TRADE_DATE_INVALID",
        )
        if any(token in reason for token in hard_failures):
            raise LocalReviewPipelineError(f"SELECTOR_CONSUMER_CONTRACT:{reason}") from exc
        return {
            "schema_version": "review_core.selector_snapshot.v1",
            "path": str(resolved),
            "selector_path": str(resolved),
            "sha256": actual,
            "selector_sha256": actual,
            "source_date": source_pin,
            "pit_date": source_pin,
            "target_trade_date": expected_target,
            "cutoff": cutoff,
            "cutoff_at": cutoff,
            "pit_safe": False,
            "point_in_time_safe": False,
            "ready": False,
            "status": "CANNOT_CONFIRM",
            "reason": reason,
            "cannot_confirm": [reason],
            "safety_flags": dict(SAFETY_FLAGS),
            "metadata": copy.deepcopy(metadata),
        }
    except Exception as exc:
        raise LocalReviewPipelineError(f"SELECTOR_CONSUMER_CONTRACT:{type(exc).__name__}:{exc}") from exc

    # The strict adapter may validate a complete producer document before the
    # rows are read.  Keep that result non-ready until the consumer-side exact
    # data proof exists; this prevents a regular file or producer claim from
    # silently becoming PIT-safe at the old legacy boundary.
    if not proof_ok:
        return {
            "schema_version": identity.get("schema_version", "review_core.selector_snapshot.v1"),
            "path": str(identity["path"]),
            "selector_path": str(identity["selector_path"]),
            "sha256": str(identity["sha256"]),
            "selector_sha256": str(identity["selector_sha256"]),
            "source_date": str(identity["source_date"]),
            "pit_date": str(identity["pit_date"]),
            "target_trade_date": str(identity["target_trade_date"] or ""),
            "cutoff": str(identity["cutoff"]),
            "cutoff_at": str(identity["cutoff_at"]),
            "pit_safe": False,
            "point_in_time_safe": False,
            "ready": False,
            "status": "CANNOT_CONFIRM",
            "reason": proof_reason,
            "cannot_confirm": [proof_reason],
            "safety_flags": dict(SAFETY_FLAGS),
            "metadata": copy.deepcopy(identity.get("metadata") or metadata),
        }
    return {
        "path": str(identity["path"]),
        "selector_path": str(identity["selector_path"]),
        "sha256": str(identity["sha256"]),
        "selector_sha256": str(identity["selector_sha256"]),
        "source_date": str(identity["source_date"]),
        "pit_date": str(identity["pit_date"]),
        "target_trade_date": str(identity["target_trade_date"] or ""),
        "cutoff": str(identity["cutoff"]),
        "cutoff_at": str(identity["cutoff_at"]),
        "pit_safe": bool(identity["pit_safe"]),
        "point_in_time_safe": bool(identity.get("point_in_time_safe")),
        "status": str(identity.get("status") or "READY"),
        "ready": bool(identity.get("ready")),
        # ``READY`` remains the compatibility status alias.  This explicit
        # signal records that the READY state was minted only after the
        # consumer exact-date row/max-date proof, never by the producer.
        "ready_signal": "CONSUMER_VERIFIED_READY",
        "readiness_signal": "CONSUMER_VERIFIED_READY",
        "reason": "CONSUMER_VERIFIED_READY",
        "consumer_verified": True,
        "safety_flags": dict(SAFETY_FLAGS),
        "metadata": copy.deepcopy(identity.get("metadata") or metadata),
    }


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


_INPUT_PROVENANCE_FIELDS = {
    "source_role",
    "input_source_role",
    "input_source_path",
    "input_source_sha256",
}


def _stage_input_directory(stage_root: Path | str, trade_date: str) -> Path:
    """Resolve a caller's stage root without ever selecting another date."""

    target = _date8(trade_date)
    root = Path(stage_root).absolute()
    if root.name == target:
        return root
    date_root = root / target
    return date_root if date_root.is_dir() else root


def _exact_stage_matches(stage_root: Path | str, trade_date: str, stage_number: int | str) -> list[Path]:
    """Return the one exact-date file for a stage, or fail on ambiguity."""

    target = _date8(trade_date)
    number = str(stage_number)
    directory = _stage_input_directory(stage_root, target)
    if not directory.is_dir():
        return []
    date_token = re.compile(rf"(?<![A-Za-z0-9]){re.escape(target)}(?![A-Za-z0-9])")
    matches = sorted(
        path
        for path in directory.glob(f"generated_stage{number}_*.csv")
        if path.parent.name == target and date_token.search(path.name)
    )
    if len(matches) > 1:
        joined = ",".join(str(path) for path in matches)
        raise LocalReviewPipelineError(f"STAGE{number}_AMBIGUOUS_EXACT_DATE:{target}:{joined}")
    return matches


def _row_source_identity(row: Mapping[str, Any]) -> str:
    return _sha_bytes({key: value for key, value in row.items() if key not in _INPUT_PROVENANCE_FIELDS})


def _materialize_source_rows(
    rows: list[Mapping[str, Any]],
    *,
    target: str,
    source_role: str,
    source_path: str,
    source_sha256: str,
) -> list[dict[str, Any]]:
    """Attach local-input lineage and deterministically remove duplicate rows."""

    materialized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_row in enumerate(rows):
        if not isinstance(raw_row, Mapping):
            raise LocalReviewPipelineError(f"LOCAL_INPUT_ROW_INVALID:{source_role}:{index}")
        row = dict(raw_row)
        row.setdefault("source_role", source_role)
        row["input_source_role"] = source_role
        row["input_source_path"] = source_path
        row["input_source_sha256"] = source_sha256
        identity = _row_source_identity(row)
        if identity in seen:
            continue
        seen.add(identity)
        materialized.append(row)
    return materialized


def _local_input_record(
    path: Path,
    *,
    trade_date: str,
    source_role: str,
    row_count: int,
    kind: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a source-ref and status row for one local input file."""

    target = _date8(trade_date)
    regular = path.is_file() and not path.is_symlink()
    digest = sha256_file(path) if regular else ""
    status = "READY" if regular else ("MISSING" if not path.exists() else "NON_REGULAR")
    ref = {
        "kind": kind,
        "path": str(path),
        "sha256": digest,
        "row_count": row_count,
        "source_role": source_role,
        "trade_date": target,
    }
    status_row = {
        "trade_date": target,
        "source": kind,
        "status": status,
        "usable": regular,
        "rows": row_count,
        "row_count": row_count,
        "source_role": source_role,
        "role": source_role,
        "source_path": str(path),
        "sha256": digest,
    }
    return ref, status_row


def _is_regular_nonempty_file(path: Path) -> bool:
    """Return true only for a readable, regular, non-empty snapshot file."""

    if path.is_symlink() or not path.is_file():
        return False
    try:
        return path.stat().st_size > 0
    except OSError:
        return False


def _load_exact_stage_inputs(
    stage_root: Path | str,
    trade_date: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, int]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Load target-day stage 4-7 once, preserving missing-stage states."""

    target = _date8(trade_date)
    stage_rows: list[dict[str, Any]] = []
    stage_counts: dict[str, dict[str, int]] = {}
    source_refs: list[dict[str, Any]] = []
    source_status: list[dict[str, Any]] = []
    directory = _stage_input_directory(stage_root, target)
    for number in ("4", "5", "6", "7"):
        role = f"TARGET_DATE_STAGE{number}"
        label = f"stage{number}_label"
        matches = _exact_stage_matches(stage_root, target, number)
        if matches:
            path = matches[0]
            raw_rows = _load_stage_rows(path, target, number)
            digest = sha256_file(path)
            rows = _materialize_source_rows(
                raw_rows,
                target=target,
                source_role=role,
                source_path=str(path),
                source_sha256=digest,
            )
            counts: Counter[str] = Counter()
            for row in rows:
                value = str(row.get(label) or row.get("decision_label") or "未标注")
                counts[value] += 1
            stage_counts[f"stage{number}"] = dict(counts)
            ref, status = _local_input_record(
                path,
                trade_date=target,
                source_role=role,
                row_count=len(rows),
                kind="target_stage_input",
            )
            source_refs.append(ref)
            source_status.append(status)
            stage_rows.extend(rows)
        else:
            stage_counts[f"stage{number}"] = {}
            missing_path = directory / f"generated_stage{number}_*_{target}.csv"
            _ref, status = _local_input_record(
                missing_path,
                trade_date=target,
                source_role=role,
                row_count=0,
                kind="target_stage_input",
            )
            source_status.append(status)
    return stage_rows, stage_counts, source_refs, source_status


def _stage_counts(stage_root: Path, trade_date: str) -> dict[str, dict[str, int]]:
    return _load_exact_stage_inputs(stage_root, trade_date)[1]


def _default_raw_loader(
    trade_date: str,
    *,
    public_bundle: Mapping[str, Any],
    selector_path: Path | str | None,
    selector_root: Path | str | None,
    tdx_root: Path | str | None,
    public_source_root: Path | str | None = None,
    formal_pool_path: Path | str | None,
    review_pool_path: Path | str | None,
    stage_root: Path | str | None,
    selector_sha256: str | None = None,
    selector_target_trade_date: str | None = None,
    selector_cutoff: str | None = None,
    selector_source_date: str | None = None,
    selector_pit_safe: bool | None = None,
    selector_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    verified = _validate_public_bundle(public_bundle, trade_date)
    selector_identity = _selector_consumer_identity(
        trade_date,
        selector_path,
        selector_root,
        expected_sha256=selector_sha256,
        expected_target_trade_date=selector_target_trade_date,
        expected_cutoff=selector_cutoff,
        expected_source_date=selector_source_date,
        expected_pit_safe=selector_pit_safe,
        selector_metadata=selector_metadata,
    )
    selector_file = Path(selector_identity["path"])
    selector_rows, selector_names = _load_selector_rows(selector_file, trade_date)
    selector_dates = [
        _date8(row.get("trade_date"))
        for row in selector_rows
        if isinstance(row, Mapping) and row.get("trade_date") not in (None, "")
    ]
    if not selector_dates or any(row_date != _date8(trade_date) for row_date in selector_dates):
        raise LocalReviewPipelineError(f"SELECTOR_EXACT_DATA_DATE_MISMATCH:{trade_date}")
    selector_data_proof = {
        "rows": selector_rows,
        "max_date": max(selector_dates),
        "row_count": len(selector_rows),
    }
    after_selector_identity = _selector_consumer_identity(
        trade_date,
        selector_path,
        selector_root,
        expected_sha256=selector_sha256 or selector_identity["sha256"],
        expected_target_trade_date=selector_target_trade_date or selector_identity.get("target_trade_date") or None,
        expected_cutoff=selector_cutoff or selector_identity.get("cutoff") or None,
        expected_source_date=selector_source_date or None,
        expected_pit_safe=selector_pit_safe,
        selector_metadata=selector_metadata,
        _exact_data_proof=selector_data_proof,
    )
    if after_selector_identity["sha256"] != selector_identity["sha256"]:
        raise LocalReviewPipelineError(f"SELECTOR_CONSUMER_SHA_MISMATCH:{selector_file}")
    app_data = DEFAULT_APP_DATA_ROOT
    formal_path = Path(formal_pool_path) if formal_pool_path is not None else app_data / "formal_pools" / trade_date / f"formal_opening_pool_{trade_date}.csv"
    review_path = Path(review_pool_path) if review_pool_path is not None else app_data / "generated_pools" / trade_date / f"advisor_generated_premarket_pool_{trade_date}.csv"
    stages = Path(stage_root) if stage_root is not None else app_data / "generated_stages" / trade_date
    preselection = None
    # An explicit stage root is an additional target-day input, not an
    # instruction to discard the verified D-1 pool materialization.
    if formal_pool_path is None and review_pool_path is None:
        preselection_root = _preselection_pool_root_from_tdx(tdx_root, trade_date)
        if preselection_root is not None:
            preselection = _load_verified_preselection_pools(
                preselection_root,
                trade_date,
                public_source_root=public_source_root,
            )
    stage_rows, stage_counts, stage_source_refs, stage_source_status = _load_exact_stage_inputs(stages, trade_date)
    formal_observed = False
    formal_pool_observed = False
    formal_execution_attempted = False
    formal_source_role = "FORMAL_POOL_NOT_OBSERVED"
    prior_plan_lineage_rows: list[dict[str, Any]] = []
    formal_pool_status = "CANNOT_CONFIRM_FORMAL_POOL_NOT_MATERIALIZED"
    formal_source_error: str | None = None
    if preselection is not None:
        evidence_by_pool = {item["pool_id"]: item for item in preselection["evidence"]}
        formal_evidence = evidence_by_pool["a_d1_premarket_pool"]
        review_evidence = evidence_by_pool["a_d1_fupan_watchlist_pool"]
        d1_stage7_evidence = evidence_by_pool["a_d1_stage7_fenshi_review_pool"]
        # The verified preselection pool is D-1 candidate evidence.  It must
        # remain available for prior-plan lineage while never becoming a
        # formal-pool observation.
        prior_plan_lineage_rows = _materialize_source_rows(
            preselection["prior_plan_lineage_rows"],
            target=trade_date,
            source_role=formal_evidence["source_role"],
            source_path=formal_evidence["source_path"],
            source_sha256=formal_evidence["source_sha256"],
        )
        formal_rows = []
        review_rows = _materialize_source_rows(
            preselection["review_rows"],
            target=trade_date,
            source_role=review_evidence["source_role"],
            source_path=review_evidence["source_path"],
            source_sha256=review_evidence["source_sha256"],
        )
        prior_stage_rows = _materialize_source_rows(
            preselection["stage_rows"],
            target=trade_date,
            source_role=d1_stage7_evidence["source_role"],
            source_path=d1_stage7_evidence["source_path"],
            source_sha256=d1_stage7_evidence["source_sha256"],
        )
        prior_stage_counts = copy.deepcopy(preselection.get("stage_counts") or {})
        formal_observed = preselection.get("formal_observed") is True
        formal_pool_observed = preselection.get("formal_pool_observed") is True
        formal_execution_attempted = preselection.get("formal_execution_attempted") is True
        formal_source_role = str(preselection.get("formal_source_role") or "FORMAL_POOL_NOT_OBSERVED")
        formal_pool_status = str(
            preselection.get("formal_pool_status") or "CANNOT_CONFIRM_FORMAL_POOL_NOT_MATERIALIZED"
        )
    else:
        explicit_formal_path = formal_pool_path is not None
        formal_execution_attempted = explicit_formal_path
        formal_source_role = _FORMAL_SOURCE_ROLE if explicit_formal_path else "FORMAL_POOL_NOT_OBSERVED"
        formal_rows: list[dict[str, str]] = []
        review_rows: list[dict[str, str]] = []
        if explicit_formal_path and not _is_regular_nonempty_file(formal_path):
            formal_source_error = f"FORMAL_POOL_SOURCE_NOT_REGULAR_OR_EMPTY:{formal_path}"
        else:
            try:
                formal_rows, review_rows, _formal_signal_dates = _load_pool_inputs(
                    formal_path,
                    review_path,
                    trade_date,
                )
                if explicit_formal_path:
                    _validate_explicit_formal_rows(
                        formal_rows,
                        path=formal_path,
                        formal_observed=True,
                        source_role=formal_source_role,
                    )
            except (LocalReviewPipelineError, OSError, UnicodeError, ValueError, TypeError) as exc:
                if not explicit_formal_path:
                    raise
                # Preserve the rejected rows for the page validator to expose
                # as an invalid whole source; never promote a partial parse.
                formal_source_error = str(exc)
                if _is_regular_nonempty_file(formal_path):
                    try:
                        formal_rows = _read_csv_rows(formal_path)
                    except (OSError, UnicodeError, ValueError, TypeError):
                        formal_rows = []
                else:
                    formal_rows = []
                review_rows = []

        formal_observed = bool(
            explicit_formal_path
            and formal_source_error is None
            and _is_regular_nonempty_file(formal_path)
            and formal_rows
        )
        formal_pool_observed = formal_observed
        if explicit_formal_path:
            if formal_observed:
                formal_pool_status = "FORMAL_POOL_SOURCE_OBSERVED"
            elif formal_source_error:
                formal_pool_status = "CANNOT_CONFIRM_FORMAL_SOURCE_INVALID"
            else:
                formal_pool_status = "CANNOT_CONFIRM_FORMAL_POOL_NOT_MATERIALIZED"
        elif formal_rows:
            # A default-path file is not evidence of an observed formal pool.
            # Reject it rather than silently promoting its rows.
            raise LocalReviewPipelineError(
                f"FORMAL_POOL_SOURCE_PATH_EXPLICIT_REQUIRED:{formal_path}"
            )
        review_role = "D1_REVIEW_POOL_CSV"
        formal_digest = sha256_file(formal_path) if formal_path.is_file() and not formal_path.is_symlink() else ""
        review_digest = sha256_file(review_path) if review_path.is_file() and not review_path.is_symlink() else ""
        formal_rows = _materialize_source_rows(
            formal_rows,
            target=trade_date,
            source_role=formal_source_role,
            source_path=str(formal_path),
            source_sha256=formal_digest,
        )
        review_rows = _materialize_source_rows(
            review_rows,
            target=trade_date,
            source_role=review_role,
            source_path=str(review_path),
            source_sha256=review_digest,
        )
        prior_plan_lineage_rows = copy.deepcopy(formal_rows) if formal_observed else []
        prior_stage_rows = []
        prior_stage_counts = {}
    name_map: dict[str, str] = {}
    for row in [*review_rows, *prior_stage_rows, *stage_rows]:
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
    source_status_rows = list(raw.get("source_status") or [])
    if (selector_metadata or {}).get('qfq_coverage') is not None and selector_pit_safe is not False:
        raise LocalReviewPipelineError('QFQ_PIT_BOUNDARY_INVALID')
    coverage = _qfq_partial_coverage(
        (selector_metadata or {}).get('qfq_coverage'), trade_date=trade_date,
        target_date=selector_target_trade_date, selector_sha=after_selector_identity['sha256'],
        selector_path=selector_file, selector_rows=len(selector_rows), tdx_rows=len(raw.get('daily_rows') or []))
    source_refs = [
        {"kind": "public_fupan_manifest", "path": f"public_fupan://{trade_date}/manifest.json", "sha256": verified["manifest_sha256"]},
        {
            "kind": "selector_ready_panel",
            "path": str(selector_file),
            "sha256": after_selector_identity["sha256"],
            "source_role": "TARGET_DATE_SELECTOR",
            "trade_date": trade_date,
            "source_date": after_selector_identity.get("source_date", ""),
            "target_trade_date": after_selector_identity["target_trade_date"],
            "cutoff": after_selector_identity["cutoff"],
            "pit_date": after_selector_identity.get("pit_date", ""),
            "pit_safe": after_selector_identity.get("pit_safe", False),
            "point_in_time_safe": after_selector_identity.get("point_in_time_safe", False),
        },
    ]
    pool_source_refs: list[dict[str, Any]] = []
    pool_source_status: list[dict[str, Any]] = []
    if preselection is not None:
        for item in preselection["evidence"]:
            common = {
                "trade_date": trade_date,
                "source_role": item["source_role"],
                "row_count": item["row_count"],
                "source_sha256": item["source_sha256"],
            }
            pool_source_refs.extend(
                [
                    {
                        "kind": "preselection_pool_artifact",
                        "path": item["artifact_path"],
                        "sha256": item["artifact_sha256"],
                        **common,
                    },
                    {
                        "kind": "preselection_pool_receipt",
                        "path": item["receipt_path"],
                        "sha256": item["receipt_sha256"],
                        **common,
                    },
                ]
            )
            pool_source_refs.extend(
                {
                    "kind": "preselection_source_input",
                    "path": source["path"],
                    "sha256": source["sha256"],
                    **common,
                }
                for source in item.get("source_file_refs", [])
            )
            pool_source_status.append(
                {
                    "trade_date": trade_date,
                    "source": f"preselection:{item['pool_id']}",
                    "status": item["status"],
                    "usable": True,
                    "rows": item["row_count"],
                    "row_count": item["row_count"],
                    "source_role": item["source_role"],
                    "role": item["source_role"],
                    "signal_date": item["signal_date"],
                    "source_path": item["source_path"],
                    "source_paths": item["source_paths"],
                    "sha256": item["source_sha256"],
                    "artifact_path": item["artifact_path"],
                    "artifact_sha256": item["artifact_sha256"],
                    "receipt_path": item["receipt_path"],
                    "receipt_sha256": item["receipt_sha256"],
                    "formal_observed": False,
                    "formal_pool_observed": False,
                    "formal_execution_attempted": False,
                    "lineage_role": (
                        "PRIOR_PLAN_CANDIDATE"
                        if item["pool_id"] == "a_d1_premarket_pool"
                        else "PRIOR_PLAN_SUPPORT"
                    ),
                }
            )
    else:
        formal_ref, formal_status = _local_input_record(
            formal_path,
            trade_date=trade_date,
            source_role=formal_source_role,
            row_count=len(formal_rows),
            kind="formal_pool_input",
        )
        review_ref, review_status = _local_input_record(
            review_path,
            trade_date=trade_date,
            source_role="D1_REVIEW_POOL_CSV",
            row_count=len(review_rows),
            kind="review_pool_input",
        )
        pool_source_refs.extend((formal_ref, review_ref))
        pool_source_status.extend((formal_status, review_status))
    source_refs.extend(pool_source_refs)
    source_refs.extend(stage_source_refs)
    if coverage:
        source_refs.extend([{'kind':'qfq_a_receipt','path':coverage['a_receipt_path'],'sha256':coverage['a_receipt_sha256']},
                            {'kind':'qfq_dispatch_receipt','path':coverage['dispatch_receipt_path'],'sha256':coverage['dispatch_receipt_sha256']}])
        source_status_rows.append({'source':'qfq_a_authority','status':'PARTIAL','usable':True,'coverage_evidence':copy.deepcopy(coverage)})
    source_status_rows.extend(pool_source_status)
    source_status_rows.extend(stage_source_status)
    raw.update(
        {
            "formal_rows": formal_rows,
            "prior_plan_lineage_rows": prior_plan_lineage_rows,
            "review_rows": review_rows,
            "formal_observed": formal_observed,
            "formal_pool_observed": formal_pool_observed,
            "formal_execution_attempted": formal_execution_attempted,
            "formal_source_role": formal_source_role,
            "formal_pool_status": formal_pool_status,
            "formal_source_error": formal_source_error,
            "stage_rows": stage_rows,
            "prior_stage_rows": prior_stage_rows,
            "prior_stage_counts": prior_stage_counts,
            "tplus1_rows": [],
            "stage_counts": stage_counts,
            "rule_rows": [],
            "news_article_rows": [],
            "news_event_rows": [],
            "news_research_hit_rows": [],
            "news_event_source_paths": {},
            "morning_news_acceptance": {},
            "source_status_rows": source_status_rows,
            "source_status": copy.deepcopy(source_status_rows),
            "cannot_confirm_items": [],
            MARKET_SCOPE_FIELD: FULL_MARKET_SCOPE,
            MARKET_COMPLETENESS_FIELD: "PARTIAL_COVERAGE" if coverage else "FULL_MARKET_VERIFIED",
            "selector_identity": copy.deepcopy(after_selector_identity),
            # The fupan seam may re-run the strict selector adapter, but it
            # must also carry the consumer's exact-date row/max-date proof;
            # a producer READY claim alone is never a consumer verification.
            "selector_data_proof": copy.deepcopy(selector_data_proof),
        }
    )
    if preselection is not None:
        raw["preselection_pool_evidence"] = copy.deepcopy(preselection["evidence"])
    return {
        "page_inputs": raw,
        "replay_rows": selector_rows,
        "formal_rows": formal_rows,
        "prior_plan_lineage_rows": prior_plan_lineage_rows,
        "formal_observed": formal_observed,
        "formal_pool_observed": formal_pool_observed,
        "formal_execution_attempted": formal_execution_attempted,
        "formal_source_role": formal_source_role,
        "formal_source_error": formal_source_error,
        MARKET_SCOPE_FIELD: FULL_MARKET_SCOPE,
        MARKET_COMPLETENESS_FIELD: "PARTIAL_COVERAGE" if coverage else "FULL_MARKET_VERIFIED",
        "coverage_evidence": coverage,
        "source_refs": source_refs,
        "public_identity": {
            "run_id": verified["run_id"],
            "manifest_sha256": verified["manifest_sha256"],
            "file_sha256": verified["file_sha256"],
        },
        "selector_identity": after_selector_identity,
        "selector_data_proof": selector_data_proof,
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
    package_root = Path(__file__).resolve().parent
    paths = {
        "producer_inputs.py": package_root / "producer_inputs.py",
        "daily_replay_producer.py": package_root / "daily_replay_producer.py",
        "fupan_page_producer.py": package_root / "fupan_page_producer.py",
        "review_pipeline.py": package_root / "review_pipeline.py",
        "review.py": package_root / "review.py",
        "readiness.py": package_root / "readiness.py",
        "adapters/__init__.py": package_root / "adapters" / "__init__.py",
        "adapters/selector.py": package_root / "adapters" / "selector.py",
        "adapters/stage_center.py": package_root / "adapters" / "stage_center.py",
        "consumer.py": package_root / "consumer.py",
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
    selector_sha256: str | None = None,
    selector_target_trade_date: str | None = None,
    selector_cutoff: str | None = None,
    selector_source_date: str | None = None,
    selector_pit_safe: bool | None = None,
    selector_metadata: Mapping[str, Any] | None = None,
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
    selector_identity_before: dict[str, Any] | None = None
    if any(
        value is not None
        for value in (
            selector_path,
            selector_root,
            selector_sha256,
            selector_target_trade_date,
            selector_cutoff,
            selector_source_date,
            selector_pit_safe,
            selector_metadata,
        )
    ):
        selector_identity_before = _selector_consumer_identity(
            target,
            selector_path,
            selector_root,
            expected_sha256=selector_sha256,
            expected_target_trade_date=selector_target_trade_date,
            expected_cutoff=selector_cutoff,
            expected_source_date=selector_source_date,
            expected_pit_safe=selector_pit_safe,
            selector_metadata=selector_metadata,
        )
    loader = raw_loader or _default_raw_loader
    loader_kwargs = {
        "public_bundle": public_bundle,
        "selector_path": selector_path,
        "selector_root": selector_root,
        "tdx_root": tdx_root,
        "formal_pool_path": formal_pool_path,
        "review_pool_path": review_pool_path,
        "stage_root": stage_root,
        "selector_sha256": selector_sha256,
        "selector_target_trade_date": selector_target_trade_date,
        "selector_cutoff": selector_cutoff,
        "selector_source_date": selector_source_date,
        "selector_pit_safe": selector_pit_safe,
        "selector_metadata": selector_metadata,
    }
    if raw_loader is None:
        loader_kwargs["public_source_root"] = public_root
    loaded = loader(target, **loader_kwargs)
    if not isinstance(loaded, Mapping):
        raise LocalReviewPipelineError("LOCAL_RAW_LOADER_INVALID")
    selector_identity_after = selector_identity_before
    if selector_identity_before is not None:
        proof = loaded.get("selector_data_proof")
        selector_identity_after = _selector_consumer_identity(
            target,
            selector_path,
            selector_root,
            expected_sha256=selector_sha256 or selector_identity_before["sha256"],
            expected_target_trade_date=selector_target_trade_date or selector_identity_before.get("target_trade_date") or None,
            expected_cutoff=selector_cutoff or selector_identity_before.get("cutoff") or None,
            expected_source_date=selector_source_date or None,
            expected_pit_safe=selector_pit_safe,
            selector_metadata=selector_metadata,
            _exact_data_proof=proof if isinstance(proof, Mapping) else None,
        )
        if selector_identity_after["sha256"] != selector_identity_before["sha256"]:
            raise LocalReviewPipelineError(f"SELECTOR_CONSUMER_SHA_MISMATCH:{selector_identity_after['path']}")
    else:
        # A custom raw-loader is still an input boundary.  If it supplies a
        # selector identity, revalidate it through the same strict consumer
        # contract instead of allowing a claimed ``ready=True`` layer to
        # bypass source/target/cutoff/PIT/SHA/path evidence.  Loaders which do
        # not use a selector simply omit this field.
        loaded_selector = loaded.get("selector_identity")
        if loaded_selector is not None:
            if not isinstance(loaded_selector, Mapping):
                raise LocalReviewPipelineError("SELECTOR_CONSUMER_IDENTITY_INVALID")
            loaded_selector_path = loaded_selector.get("path") or loaded_selector.get("selector_path")
            if loaded_selector_path in (None, ""):
                raise LocalReviewPipelineError("SELECTOR_CONSUMER_PATH_MISSING")
            loaded_proof = loaded.get("selector_data_proof")
            selector_identity_after = _selector_consumer_identity(
                target,
                loaded_selector_path,
                None,
                expected_sha256=loaded_selector.get("selector_sha256") or loaded_selector.get("sha256") or None,
                expected_target_trade_date=loaded_selector.get("target_trade_date") or None,
                expected_cutoff=loaded_selector.get("cutoff") or loaded_selector.get("cutoff_at") or None,
                expected_source_date=loaded_selector.get("source_date") or None,
                expected_pit_safe=(
                    loaded_selector.get("pit_safe")
                    if "pit_safe" in loaded_selector
                    else None
                ),
                selector_metadata=loaded_selector,
                _exact_data_proof=loaded_proof if isinstance(loaded_proof, Mapping) else None,
            )
    page_inputs = loaded.get("page_inputs")
    replay_rows = loaded.get("replay_rows")
    if not isinstance(page_inputs, Mapping) or not isinstance(replay_rows, list) or not replay_rows:
        raise LocalReviewPipelineError(f"LOCAL_RAW_INPUTS_MISSING:{target}")
    market_scope = _validate_market_scope(loaded.get(MARKET_SCOPE_FIELD))
    coverage=loaded.get('coverage_evidence')
    if coverage is not None and (not isinstance(coverage,Mapping) or coverage.get('source_date')!=target
                                 or selector_pit_safe is not False):
        raise LocalReviewPipelineError('QFQ_COVERAGE_BINDING_MISMATCH')
    market_completeness = 'PARTIAL_COVERAGE' if coverage else _scope_completeness(market_scope)
    scoped_page_inputs = copy.deepcopy(dict(page_inputs))
    scoped_page_inputs[MARKET_SCOPE_FIELD] = market_scope
    scoped_page_inputs[MARKET_COMPLETENESS_FIELD] = market_completeness
    scoped_page_inputs.setdefault(
        "selector_identity",
        copy.deepcopy(selector_identity_after or loaded.get("selector_identity") or {}),
    )
    if isinstance(loaded.get("selector_data_proof"), Mapping):
        scoped_page_inputs.setdefault(
            "selector_data_proof",
            copy.deepcopy(loaded.get("selector_data_proof")),
        )
    if isinstance(loaded.get("stage_center"), Mapping):
        scoped_page_inputs.setdefault("stage_center", copy.deepcopy(loaded["stage_center"]))
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
        "selector_identity": selector_identity_after or loaded.get("selector_identity") or {},
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
        page_payload = _mark_page_scope(page_payload, market_scope, replay_rows, coverage)
        replay_payload = build_daily_replay_payload(
            target,
            replay_rows,
            run_id=run_id,
            universe_scope='PARTIAL_COVERAGE' if coverage else market_scope,
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
        bundle_payload = bundle_result.get("bundle")
        pipeline_readiness = (
            copy.deepcopy(bundle_payload.get("readiness"))
            if isinstance(bundle_payload, Mapping) and isinstance(bundle_payload.get("readiness"), Mapping)
            else copy.deepcopy(page_payload.get("readiness") or {})
        )
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
            "readiness": pipeline_readiness,
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
            "readiness": copy.deepcopy(pipeline_readiness),
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
                "readiness": copy.deepcopy(pipeline_readiness),
                "safety_flags": dict(SAFETY_FLAGS),
            },
        )
        return {
            **receipt,
            "manifest_path": str(manifest_path),
            "current_path": str(current_path),
            "run_dir": str(run_dir),
            "bundle": bundle_result.get("bundle"),
            "readiness": pipeline_readiness,
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
