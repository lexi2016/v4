"""Read-only projection of verified stage-center selection artifacts.

The consumer deliberately has no producer, scheduler, or persistence path.  It
only reads the immutable selection run trio and latest pointer through
``SelectionStore`` and normalizes unavailable or tampered evidence to the same
public ``CANNOT_CONFIRM`` response.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

from infrastructure.preselection_pool_store import PreselectionPoolStore

from .contracts import EIGHT_STAGES, SAFETY_FLAGS
from .execution_evidence import read_stage_execution
from .selection import SelectionError, SelectionStore, _validate_date, _validate_market, _validate_stage


RESPONSE_SOURCE = "SHARED_STAGE_CENTER"
READ_ONLY_CANNOT_CONFIRM = "SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID"
_KNOWN_MARKETS = frozenset({"A_SHARE", "HK_CONNECT"})
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_BACKFILL_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_BACKFILL_MARKERS = frozenset({"recovery_mode=HISTORICAL_BACKFILL", "due_status=HISTORICAL_BACKFILL", "HISTORICAL_BACKFILL"})
_NAME_AUTHORITY_EXACT = "EXACT_DATE_READ_OVERLAY"
_NAME_AUTHORITY_NOT_NEEDED = "NOT_NEEDED"
_NAME_AUTHORITY_CANNOT_CONFIRM = "CANNOT_CONFIRM"
_NAME_AUTHORITY_CODE_NOT_FOUND = "NAME_AUTHORITY_CODE_NOT_FOUND"
_NAME_AUTHORITY_SOURCE = "A_CANONICAL_PRESELECTION_POOLS"
_A_CODE_ALIAS_FIELDS = ("symbol", "stock_code", "ts_code", "code")
_A_CODE_RE = re.compile(r"(?:(?:A|SH|SZ|BJ)\.(\d{6})|(\d{6})(?:\.(?:SH|SZ|BJ))?)\Z")
_A_NAME_POOL_IDS = (
    "a_d1_premarket_pool",
    "a_d1_fupan_watchlist_pool",
    "a_d1_stage7_fenshi_review_pool",
    "a_share_research_recommendation_pool",
)


def _scheduled_markets(stage_id: str) -> tuple[str, ...]:
    for stage in EIGHT_STAGES:
        if stage.stage_id == stage_id:
            return stage.markets
    raise ValueError(f"unknown stage {stage_id!r}")


def _dedupe_markets(markets: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    for market in markets:
        if market not in _KNOWN_MARKETS:
            raise ValueError(f"unknown market {market!r}")
        if market not in result:
            result.append(market)
    return tuple(result)


def _normalize_authority_date(value: Any) -> str:
    return str(value or "").strip().replace("-", "")


def _normalize_a_code(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if not raw:
        return ""
    match = _A_CODE_RE.fullmatch(raw)
    if not match:
        return ""
    return f"A.{match.group(1) or match.group(2)}"


_CODE_LIKE_NAME_RE = re.compile(
    r"(?:(?:A|SH|SZ|BJ|HK)[. ]?)?\d+(?:[. ]?(?:SH|SZ|BJ|HK))?\Z", re.I
)
_PLACEHOLDER_NAMES = frozenset({
    "-", "--", "N/A", "NA", "NAN", "NONE", "NULL", "UNKNOWN",
    "CANNOT_CONFIRM", "未命名", "未知", "暂无", "无名称",
})
_TDX_PLACEHOLDER_RE = re.compile(r"TDX(?:[-_ ]?(?:DAY|MIN|MINUTE|HQ))?(?:[（(]选[）)])?\Z", re.I)


def _canonical_name(value: Any, code: str) -> str:
    # These are display names, never a security lookup or a new name producer.
    # A code under any alias and known source labels are not stock names.
    if not isinstance(value, str):
        return ""
    normalized = "".join(value.split())
    if (not normalized or normalized.upper() == str(code or "").strip().upper()
            or _CODE_LIKE_NAME_RE.fullmatch(normalized)
            or normalized.upper() in _PLACEHOLDER_NAMES
            or _TDX_PLACEHOLDER_RE.fullmatch(normalized)):
        return ""
    return normalized


def _valid_name(value: Any, code: str) -> bool:
    return bool(_canonical_name(value, code))


def _row_has_valid_name(row: Mapping[str, Any]) -> bool:
    code = str(row.get("code") or "").strip()
    return _valid_name(row.get("name"), code) or _valid_name(row.get("stock_name"), code)


def _canonical_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _invalid_market(market: str) -> dict[str, Any]:
    return {
        "market": market,
        "status": "CANNOT_CONFIRM",
        "selection_status": "CANNOT_CONFIRM",
        "artifact_id": None,
        "run_id": None,
        "algorithm_id": None,
        "algorithm_sha256": None,
        "raw_artifact_sha256": None,
        "source_status": "CANNOT_CONFIRM",
        "requested_rows": None,
        "source_rows": None,
        "selected_rows": None,
        "coverage_ratio": None,
        "missing_symbols": [],
        "rows": [],
        "cannot_confirm": [READ_ONLY_CANNOT_CONFIRM],
    }


def _invalid_market_with_reason(market: str, reason: str) -> dict[str, Any]:
    payload = _invalid_market(market)
    payload["cannot_confirm"] = [reason]
    return payload

def _append_reason(payload: dict[str, Any], reason: str) -> dict[str, Any]:
    reasons = list(payload.get("cannot_confirm") or [])
    if reason not in reasons:
        reasons.append(reason)
    payload["cannot_confirm"] = reasons
    return payload

def _safe_child(root: Path, *parts: str) -> Path | None:
    """Resolve a read-only child path without following any symlink component."""
    if root.is_symlink():
        return None
    candidate = root
    for part in parts:
        candidate = candidate / part
        if candidate.is_symlink():
            return None
    try:
        resolved_root = root.resolve()
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError):
        return None
    return candidate

def _project_market(market: str, envelope: Mapping[str, Any]) -> dict[str, Any]:
    rows = envelope.get("rows")
    if not isinstance(rows, list):
        raise SelectionError("selection rows are not a list")
    projected_rows: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    seen_ranks: set[int] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise SelectionError("selection row is not an object")
        code = str(row.get("code") or "").strip()
        if not code or code in seen_codes:
            raise SelectionError("selection row code is missing or duplicated")
        rank = row.get("rank")
        if isinstance(rank, bool) or not isinstance(rank, int) or rank <= 0 or rank in seen_ranks:
            raise SelectionError("selection row rank is missing, non-positive, or duplicated")
        seen_codes.add(code)
        seen_ranks.add(rank)
        # Preserve the source order and rank; consumers must not re-sort by
        # code or score.  Copying also prevents a caller from mutating the
        # verified envelope returned by SelectionStore.
        projected = deepcopy(dict(row))
        projected["order"] = len(projected_rows) + 1
        projected_rows.append(projected)
    status = str(envelope.get("selection_status") or "CANNOT_CONFIRM")
    return {
        "market": market,
        "status": status,
        "selection_status": status,
        "artifact_id": envelope.get("artifact_id"),
        "run_id": envelope.get("run_id"),
        "algorithm_id": envelope.get("algorithm_id"),
        "algorithm_sha256": envelope.get("algorithm_sha256"),
        "raw_artifact_sha256": envelope.get("raw_artifact_sha256"),
        "source_status": envelope.get("source_status"),
        "requested_rows": envelope.get("requested_rows", 0),
        "source_rows": envelope.get("source_rows", 0),
        "selected_rows": envelope.get("selected_rows", len(projected_rows)),
        "coverage_ratio": envelope.get("coverage_ratio", 0.0),
        "missing_symbols": list(envelope.get("missing_symbols") or []),
        "source_evidence": list(envelope.get("source_evidence") or []),
        "rows": projected_rows,
        "cannot_confirm": list(envelope.get("cannot_confirm") or []),
    }


def _is_integrity_failure(market: Mapping[str, Any]) -> bool:
    """Distinguish an unreadable run from a valid lane-level uncertainty.

    ``_invalid_market`` is the only path that emits the read-only sentinel
    with no artifact identity.  A producer may publish a verified,
    zero-row ``CANNOT_CONFIRM`` envelope when its exact-date input is
    unavailable; that evidence must remain visible and must not erase rows
    from the other market.
    """
    return (
        market.get("artifact_id") is None
        and market.get("cannot_confirm") == [READ_ONLY_CANNOT_CONFIRM]
    )


def _bundle_artifact_id(trade_date: str, stage_id: str, markets: Sequence[Mapping[str, Any]]) -> str:
    payload = {
        "trade_date": trade_date,
        "stage_id": stage_id,
        "markets": [
            {
                "market": item.get("market"),
                "artifact_id": item.get("artifact_id"),
                "algorithm_sha256": item.get("algorithm_sha256"),
                "raw_artifact_sha256": item.get("raw_artifact_sha256"),
                "status": item.get("status"),
            }
            for item in markets
        ],
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"bundle-{digest[:24]}"


def _summary_status(markets: Sequence[Mapping[str, Any]]) -> str:
    statuses = {str(item.get("status")) for item in markets}
    has_rows = any(int(item.get("selected_rows") or 0) > 0 for item in markets)
    if any(_is_integrity_failure(item) for item in markets) and not has_rows:
        # Missing, malformed, or tampered shared artifacts remain fail-closed
        # when no market has usable rows.
        return "CANNOT_CONFIRM"
    if statuses == {"READY"}:
        return "READY"
    if statuses == {"READY_EMPTY"}:
        return "READY_EMPTY"
    if "CANNOT_CONFIRM" in statuses and all(item.get("status") == "CANNOT_CONFIRM" for item in markets) and not has_rows:
        return "CANNOT_CONFIRM"
    if "CANNOT_CONFIRM" in statuses:
        # A verified lane-level CANNOT_CONFIRM is valid partial evidence. Keep
        # the healthy sibling's rows in the overall projection.  The same rule
        # applies when the other lane's artifact is unreadable: its own market
        # remains CANNOT_CONFIRM and the top-level response is still partial.
        if has_rows:
            return "PARTIAL_WITH_ROWS"
        return "CANNOT_CONFIRM"
    if "PARTIAL_WITH_ROWS" in statuses:
        return "PARTIAL_WITH_ROWS"
    if statuses == {"CANNOT_CONFIRM", "READY_EMPTY"}:
        return "CANNOT_CONFIRM"
    return "PARTIAL_WITH_ROWS"


class StageSelectionConsumer:
    """Read-only shared selection consumer for V3/V3.5 adapters."""

    def __init__(self, root: Any, *, a_name_pool_root: Path | str | None = None, execution_receipt_root: Path | str | None = None):
        self.store = SelectionStore(root)
        # This exact sibling layout is the existing Stage scheduler contract.
        # No broad root scan or latest/date fallback is permitted.
        selection_root = Path(root).expanduser()
        self.execution_receipt_root = (
            Path(execution_receipt_root).expanduser() if execution_receipt_root is not None
            else selection_root.parent / "receipts"
            if selection_root.name == "selection" and selection_root.parent.name == "stage"
            else None
        )
        self.runner_receipt_root = self.execution_receipt_root
        self.a_name_pool_root = (
            Path(a_name_pool_root).expanduser() if a_name_pool_root is not None else None
        )
        self._a_name_authority_cache: dict[str, dict[str, Any]] = {}

    def _load_a_name_authority(self, trade_date: str) -> dict[str, Any]:
        cached = self._a_name_authority_cache.get(trade_date)
        if cached is not None:
            return cached
        result: dict[str, Any] = {
            "status": _NAME_AUTHORITY_CANNOT_CONFIRM,
            "mapping": {},
            "receipt_sha256": None,
            "selector_sha256": None,
            "source_sha256": None,
            "source": _NAME_AUTHORITY_SOURCE,
            "pool_ids": list(_A_NAME_POOL_IDS),
            "selector_sha_source": None,
            "error": "A canonical preselection pool root is not configured",
        }
        try:
            if self.a_name_pool_root is None:
                raise ValueError(result["error"])
            pool_root = self.a_name_pool_root.expanduser().resolve()
            pool_store = PreselectionPoolStore(pool_root)
            mapping: dict[str, str] = {}
            artifact_shas: dict[str, str] = {}
            source_shas: dict[str, str] = {}
            receipt_shas: dict[str, str] = {}
            for pool_id in _A_NAME_POOL_IDS:
                pool = pool_store.read_pool(trade_date, pool_id)
                rows = pool.get("rows")
                if not isinstance(rows, list):
                    raise ValueError(f"A canonical preselection pool rows are invalid: {pool_id}")
                artifact_shas[pool_id] = _canonical_digest(pool)
                source_sha = str(pool.get("source_sha256") or "").strip().lower()
                if not _SHA256_RE.fullmatch(source_sha):
                    raise ValueError(f"A canonical preselection pool source SHA is invalid: {pool_id}")
                source_shas[pool_id] = source_sha
                receipt_path = pool_root / "preselection_pools" / trade_date / "receipts" / f"{pool_id}.json"
                receipt_shas[pool_id] = _file_digest(receipt_path)
                for index, row in enumerate(rows):
                    if not isinstance(row, Mapping):
                        raise ValueError(f"A canonical preselection pool row is invalid: {pool_id}[{index}]")
                    for date_field in ("trade_date", "target_date"):
                        if date_field in row and _normalize_authority_date(row.get(date_field)) != trade_date:
                            raise ValueError(
                                f"A canonical preselection pool {date_field} mismatch: {pool_id}[{index}]"
                            )
                    alias_codes: dict[str, str] = {}
                    for alias in _A_CODE_ALIAS_FIELDS:
                        raw_alias = str(row.get(alias) or "").strip()
                        if not raw_alias:
                            continue
                        normalized_alias = _normalize_a_code(raw_alias)
                        if not normalized_alias:
                            raise ValueError(
                                f"A canonical preselection pool code alias is invalid: {pool_id}[{index}].{alias}"
                            )
                        alias_codes[alias] = normalized_alias
                    if len(set(alias_codes.values())) > 1:
                        raise ValueError(
                            f"A canonical preselection pool code alias conflict: {pool_id}[{index}]"
                        )
                    code = next(iter(alias_codes.values()), "")
                    if not code:
                        continue
                    names = {
                        _canonical_name(row.get(field), code)
                        for field in ("name", "stock_name")
                        if _canonical_name(row.get(field), code)
                    }
                    if len(names) > 1:
                        raise ValueError(f"A canonical preselection pool name conflict: {code}")
                    if not names:
                        continue
                    name = next(iter(names))
                    previous = mapping.get(code)
                    if previous is not None and previous != name:
                        raise ValueError(f"A canonical preselection pool name conflict: {code}")
                    mapping[code] = name
            if not mapping:
                raise ValueError("A canonical preselection pool name map is empty")
            result.update(
                {
                    "status": _NAME_AUTHORITY_EXACT,
                    "mapping": mapping,
                    "receipt_sha256": _canonical_digest(receipt_shas),
                    "selector_sha256": _canonical_digest(artifact_shas),
                    "source_sha256": _canonical_digest(source_shas),
                    "selector_sha_source": "CANONICAL_PRESELECTION_POOL_ARTIFACTS",
                    "error": None,
                }
            )
        except Exception as error:
            result["error"] = str(error)
        if result.get("status") == _NAME_AUTHORITY_EXACT:
            self._a_name_authority_cache[trade_date] = result
        return result

    def _overlay_a_names(self, market_payload: dict[str, Any], trade_date: str) -> dict[str, Any]:
        if market_payload.get("market") != "A_SHARE":
            return market_payload
        rows = [dict(row) if isinstance(row, Mapping) else row
                for row in (market_payload.get("rows") or [])]
        for row in rows:
            if isinstance(row, dict):
                for field in ("name", "stock_name"):
                    if field in row and not _valid_name(row[field], str(row.get("code") or "")):
                        row[field] = None
        missing_rows = [row for row in rows if isinstance(row, Mapping) and not _row_has_valid_name(row)]
        if not missing_rows:
            output = dict(market_payload)
            output["rows"] = rows
            output.update(
                {
                    "name_authority_status": _NAME_AUTHORITY_NOT_NEEDED,
                    "name_authority_source": _NAME_AUTHORITY_SOURCE,
                    "name_authority_receipt_sha256": None,
                    "name_authority_selector_sha256": None,
                    "name_authority_source_sha256": None,
                    "name_authority_selector_sha_source": None,
                    "name_authority_pool_ids": list(_A_NAME_POOL_IDS),
                    "name_authority_applied_count": 0,
                    "name_authority_missing_count": 0,
                    "name_authority_error": None,
                }
            )
            return output

        authority = self._load_a_name_authority(trade_date)
        output = dict(market_payload)
        output["name_authority_source"] = authority.get("source")
        output["name_authority_receipt_sha256"] = authority.get("receipt_sha256")
        output["name_authority_selector_sha256"] = authority.get("selector_sha256")
        output["name_authority_source_sha256"] = authority.get("source_sha256")
        output["name_authority_selector_sha_source"] = authority.get("selector_sha_source")
        output["name_authority_pool_ids"] = list(authority.get("pool_ids") or _A_NAME_POOL_IDS)
        output["name_authority_applied_count"] = 0
        output["name_authority_missing_count"] = len(missing_rows)
        output["name_authority_error"] = authority.get("error")
        projected_rows = [dict(row) for row in rows]
        mapping = authority.get("mapping") if authority.get("status") == _NAME_AUTHORITY_EXACT else {}
        missing_codes: list[str] = []
        for row in projected_rows:
            if _row_has_valid_name(row):
                continue
            code = _normalize_a_code(row.get("code"))
            name = mapping.get(code)
            if name:
                row["name"] = name
                row["stock_name"] = name
                output["name_authority_applied_count"] += 1
            else:
                missing_codes.append(code)
        output["name_authority_missing_count"] = len(missing_codes)
        authority_exact = authority.get("status") == _NAME_AUTHORITY_EXACT
        output["name_authority_status"] = (
            _NAME_AUTHORITY_EXACT if not missing_codes and authority_exact else _NAME_AUTHORITY_CANNOT_CONFIRM
        )
        if missing_codes and authority_exact:
            cannot_confirm = list(output.get("cannot_confirm") or [])
            if _NAME_AUTHORITY_CODE_NOT_FOUND not in cannot_confirm:
                cannot_confirm.append(_NAME_AUTHORITY_CODE_NOT_FOUND)
            output["cannot_confirm"] = cannot_confirm
        output["rows"] = projected_rows
        return output


    def _verify_backfill_runner_receipt(
        self,
        *,
        trade_date: str,
        stage_id: str,
        market: str,
        backfill_run_id: str,
        envelope: Mapping[str, Any],
    ) -> tuple[bool, str | None]:
        root = self.runner_receipt_root
        if root is None:
            return False, None
        relative = ("backfill", backfill_run_id, trade_date, stage_id, "receipt.json")
        receipt_path = _safe_child(root, *relative)
        if receipt_path is None or not receipt_path.is_file():
            return False, None
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if not isinstance(receipt, Mapping):
                return False, None
            market_receipt = (receipt.get("markets") or {}).get(market)
            if not isinstance(market_receipt, Mapping):
                return False, None
            if (
                receipt.get("schema_version") != "stage_center.runner.receipt.v1"
                or receipt.get("runner") != "stage_center"
                or receipt.get("mode") != "BACKFILL"
                or receipt.get("backfill_run_id") != backfill_run_id
                or receipt.get("trade_date") != trade_date
                or receipt.get("stage_id") != stage_id
                or receipt.get("due_status") != "HISTORICAL_BACKFILL"
                or receipt.get("latest_updated") is not False
                or receipt.get("current_updated") is not False
                or receipt.get("write_performed") is not True
                or any(receipt.get(flag) is not False for flag in SAFETY_FLAGS)
                or market_receipt.get("run_id") != envelope.get("run_id")
                or market_receipt.get("artifact_id") != envelope.get("artifact_id")
                or market_receipt.get("raw_artifact_sha256") != envelope.get("raw_artifact_sha256")
                or market_receipt.get("selection_status") != envelope.get("selection_status")
            ):
                return False, None
            return True, _file_digest(receipt_path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return False, None

    def _backfill_candidates(
        self, trade_date: str, stage_id: str, market: str
    ) -> tuple[list[dict[str, Any]], str | None]:
        namespace_root = self.store.root / "backfill"
        if not namespace_root.exists():
            return [], None
        if namespace_root.is_symlink() or not namespace_root.is_dir():
            return [], "BACKFILL_NAMESPACE_CANNOT_CONFIRM"

        candidates: list[dict[str, Any]] = []
        conflicted = False
        try:
            children = sorted(namespace_root.iterdir(), key=lambda path: path.name)
        except OSError:
            return [], "BACKFILL_NAMESPACE_CANNOT_CONFIRM"
        for candidate_root in children:
            run_id = candidate_root.name
            if not _BACKFILL_ID_RE.fullmatch(run_id):
                continue
            if candidate_root.is_symlink() or not candidate_root.is_dir():
                continue
            try:
                candidate_store = SelectionStore(candidate_root)
                latest = candidate_store._latest()
                key = candidate_store._key(trade_date, stage_id, market)
                entry = latest.get("entries", {}).get(key)
                if not isinstance(entry, Mapping):
                    continue
                envelope = candidate_store.read_verified(trade_date, stage_id, market)
                evidence = envelope.get("source_evidence")
                evidence_values = {
                    str(item).strip()
                    for item in evidence
                } if isinstance(evidence, list) else set()
                if not (_BACKFILL_MARKERS & evidence_values):
                    conflicted = True
                    continue
                projected = _project_market(market, envelope)
                runner_verified, runner_sha = self._verify_backfill_runner_receipt(
                    trade_date=trade_date,
                    stage_id=stage_id,
                    market=market,
                    backfill_run_id=run_id,
                    envelope=envelope,
                )
                projected.update(
                    {
                        "selection_mode": "BACKFILL",
                        "backfill_run_id": run_id,
                        "backfill_run_ids": [run_id],
                        "selection_manifest_sha256": entry.get("manifest_sha256"),
                        "selection_receipt_sha256": entry.get("receipt_sha256"),
                        "selection_artifact_sha256": entry.get("artifact_sha256"),
                        "selection_manifest_receipt_verified": True,
                        "runner_receipt_verified": runner_verified,
                        "runner_receipt_status": "VERIFIED" if runner_verified else "CANNOT_CONFIRM",
                        "runner_receipt_sha256": runner_sha,
                        "recovery_provenance": {
                            "mode": "BACKFILL",
                            "backfill_run_id": run_id,
                            "selection_manifest_receipt_verified": True,
                            "runner_receipt_verified": runner_verified,
                            "runner_receipt_status": "VERIFIED" if runner_verified else "CANNOT_CONFIRM",
                            "runner_receipt_sha256": runner_sha,
                        },
                    }
                )
                if not runner_verified:
                    _append_reason(projected, "BACKFILL_RUNNER_RECEIPT_CANNOT_CONFIRM")
                candidates.append(projected)
            except (SelectionError, OSError, ValueError, TypeError, KeyError):
                # A lane that advertises this exact date/stage/market but does
                # not pass the normal SelectionStore checks cannot be selected.
                try:
                    candidate_store = SelectionStore(candidate_root)
                    latest = candidate_store._latest()
                    if candidate_store._key(trade_date, stage_id, market) in latest.get("entries", {}):
                        conflicted = True
                except (SelectionError, OSError, ValueError, TypeError):
                    continue
        if conflicted:
            return [], "BACKFILL_NAMESPACE_CONFLICT"
        return candidates, None

    def _market_from_store_or_backfill(
        self,
        trade_date: str,
        stage_id: str,
        market: str,
        *,
        allow_backfill: bool = False,
    ) -> dict[str, Any]:
        try:
            natural = _project_market(
                market, self.store.read_verified(trade_date, stage_id, market)
            )
            natural = self._overlay_a_names(natural, trade_date)
        except (SelectionError, OSError, ValueError, TypeError):
            natural = _invalid_market(market)

        # A verified ordinary result with rows, READY_EMPTY, or any successful
        # status remains authoritative.  Only a missing/unreadable lane or a
        # zero-row CANNOT_CONFIRM result can be repaired by a backfill lane.
        if not _is_integrity_failure(natural) and (
            int(natural.get("selected_rows") or 0) > 0
            or natural.get("status") != "CANNOT_CONFIRM"
        ):
            return natural

        # Historical recovery is a Stage workbench display capability. Other
        # readers, including manager and ensure paths, keep the ordinary
        # immutable-latest contract unless they explicitly opt in.
        if not allow_backfill:
            return natural

        candidates, scan_error = self._backfill_candidates(trade_date, stage_id, market)
        if scan_error:
            return _append_reason(natural, scan_error)
        if len(candidates) > 1:
            identities = {
                (
                    item.get("run_id"),
                    item.get("artifact_id"),
                    item.get("raw_artifact_sha256"),
                    item.get("selection_manifest_sha256"),
                    item.get("selection_receipt_sha256"),
                    item.get("selection_artifact_sha256"),
                )
                for item in candidates
            }
            if len(identities) != 1:
                return _invalid_market_with_reason(market, "BACKFILL_NAMESPACE_CONFLICT")
            # Several backfill wrappers can contain the same immutable
            # selection manifest/receipt/artifact. Keep its verified rows but
            # expose that no unique wrapper batch can be preferred.
            selected = dict(candidates[0])
            run_ids = sorted({
                str(item.get("backfill_run_id"))
                for item in candidates
                if item.get("backfill_run_id")
            })
            selected["backfill_run_id"] = None
            selected["backfill_run_ids"] = run_ids
            selected["runner_receipt_verified"] = False
            selected["runner_receipt_status"] = "CANNOT_CONFIRM"
            selected["runner_receipt_sha256"] = None
            provenance = dict(selected.get("recovery_provenance") or {})
            provenance.update(
                {
                    "backfill_run_id": None,
                    "backfill_run_ids": run_ids,
                    "runner_receipt_verified": False,
                    "runner_receipt_status": "CANNOT_CONFIRM",
                    "runner_receipt_sha256": None,
                    "namespace_conflict": True,
                    "candidate_batches": [
                        {
                            "backfill_run_id": item.get("backfill_run_id"),
                            "runner_receipt_verified": item.get("runner_receipt_verified") is True,
                            "runner_receipt_sha256": item.get("runner_receipt_sha256"),
                        }
                        for item in candidates
                    ],
                }
            )
            selected["recovery_provenance"] = provenance
            _append_reason(selected, "BACKFILL_NAMESPACE_CONFLICT")
            return self._overlay_a_names(selected, trade_date)
        if candidates:
            return self._overlay_a_names(candidates[0], trade_date)
        return natural

    def get(
        self,
        trade_date: str,
        stage_id: str,
        *,
        markets: Sequence[str] | None = None,
        allow_backfill: bool = False,
    ) -> dict[str, Any]:
        _validate_date(trade_date)
        _validate_stage(stage_id)
        scheduled = _scheduled_markets(stage_id)
        requested_markets = scheduled if markets is None else _dedupe_markets(markets)
        for market in requested_markets:
            if market not in scheduled:
                raise ValueError(f"market {market!r} is not scheduled for {stage_id!r}")
            _validate_market(stage_id, market)

        projected: list[dict[str, Any]] = []
        for market in requested_markets:
            projected.append(
                self._market_from_store_or_backfill(
                    trade_date, stage_id, market, allow_backfill=allow_backfill
                )
            )

        status = _summary_status(projected)
        invalid = any(_is_integrity_failure(item) for item in projected)
        bundle_artifact_id = _bundle_artifact_id(trade_date, stage_id, projected)
        response: dict[str, Any] = {
            "schema_version": "stage_center.selection_consumer.v1",
            "response_source": RESPONSE_SOURCE,
            "trade_date": trade_date,
            "stage_id": stage_id,
            "status": status,
            "markets": {item["market"]: item for item in projected},
            "artifact_id": bundle_artifact_id,
            "bundle_artifact_id": bundle_artifact_id,
            "run_id": projected[0].get("run_id") if len({item.get("run_id") for item in projected}) == 1 else None,
            "cannot_confirm": [READ_ONLY_CANNOT_CONFIRM] if invalid else [],
            "write_performed": False,
            **SAFETY_FLAGS,
        }
        response["execution_evidence"] = read_stage_execution(
            self.execution_receipt_root, trade_date, stage_id, response["markets"]
        )
        return response

    def ensure(
        self,
        trade_date: str,
        stage_id: str,
        *,
        markets: Sequence[str] | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Compatibility method that never produces or publishes artifacts."""
        response = self.get(trade_date, stage_id, markets=markets)
        response["ensure_status"] = (
            "READ_ONLY_VERIFIED" if response["status"] in {"READY", "READY_EMPTY"} else "READ_ONLY_CANNOT_CONFIRM"
        )
        response["force_ignored"] = bool(force)
        response["producer_called"] = False
        response["publish_called"] = False
        response["write_performed"] = False
        return response


def read_stage_selection(
    root: Any,
    trade_date: str,
    stage_id: str,
    *,
    markets: Sequence[str] | None = None,
) -> dict[str, Any]:
    return StageSelectionConsumer(root).get(trade_date, stage_id, markets=markets)


__all__ = ["READ_ONLY_CANNOT_CONFIRM", "RESPONSE_SOURCE", "StageSelectionConsumer", "read_stage_selection"]
