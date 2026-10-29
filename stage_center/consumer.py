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

from infrastructure.preselection_pool_store import (
    POOL_ORDER,
    PreselectionPoolArtifactMissing,
    PreselectionPoolIntegrityError,
    PreselectionPoolStore,
)

from .contracts import EIGHT_STAGES, SAFETY_FLAGS
from .execution_evidence import read_stage_execution, research_source_projection
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
_NAME_AUTHORITY_NAME_CONFLICT = "NAME_AUTHORITY_NAME_CONFLICT"
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


def read_a_opening_source_failure(payload, *, config):
    """Bind original committed failure diagnostics; never certify selection/run."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from infrastructure.owned_io import SafeRoot
    from infrastructure.runtime_graph.current import safe, read_events
    from .candidate_input import read_candidate_input, CandidateInputError

    date = payload.get("trade_date")
    if payload.get("stage_id") != "STAGE_0925" or not isinstance(date, str) or not re.fullmatch(r"\d{8}", date):
        return None
    markets = payload.get("markets") or {}
    if not isinstance(markets, dict):
        return None
    market = markets.get("A_SHARE") or {}
    execution = payload.get("execution_evidence") or {}
    if not isinstance(market, dict) or not isinstance(execution, dict):
        return None
    if (market.get("status") != "CANNOT_CONFIRM" or market.get("rows")
            or market.get("selection_manifest_receipt_verified") is True):
        return None
    try:
        native = config.get("native_reader_roots") or {}
        roots = [Path(value) for value in (native.get("stage_a_opening_root"),
            native.get("stage_candidate_root"), config.get("stage_receipt_root"))]
        if any(not root.is_absolute() or root.resolve(strict=True) != root or not root.is_dir() for root in roots):
            raise ValueError("failure roots unbound or unsafe")
        opening, candidate_path, receipts = roots
        relative = f"native_opening/{date}/STAGE_0925"
        if (opening / relative / "manifest.json").exists():
            raise ValueError("native manifest exists; failure overlay not applicable")
        receipt_raw = SafeRoot(receipts).read_bytes(f"{date}/STAGE_0925/receipt.json", max_bytes=1024*1024)
        receipt_sha = hashlib.sha256(receipt_raw).hexdigest()
        if execution.get("observed_sha256") != receipt_sha:
            raise ValueError("failure runner receipt observation SHA differs")
        receipt = json.loads(receipt_raw)
        safe(receipt)
        if (receipt.get("schema_version") != "stage_center.runner.receipt.v1"
                or receipt.get("runner") != "stage_center" or receipt.get("trade_date") != date
                or receipt.get("stage_id") != "STAGE_0925" or execution.get("due_status") != "DUE"):
            raise ValueError("failure runner identity/due state differs")
        candidate_sha = receipt["candidate_current_sha256"]
        if not isinstance(candidate_sha, str) or not _SHA256_RE.fullmatch(candidate_sha):
            raise ValueError("failure candidate SHA invalid")
        if any(execution.get(key) != receipt.get(key) for key in ("candidate_current_sha256", "candidate_run_id")):
            raise ValueError("failure runner candidate differs")
        candidate = read_candidate_input(candidate_path, date, expected_current_sha256=candidate_sha)
        if candidate.run_id != receipt.get("candidate_run_id"):
            raise ValueError("failure candidate run differs")
        observations = []
        for event in read_events(config, "PRECAPTURE_A_0925", 128, scan_limit=4096)["events"]:
            hint = event.get("hint") or {}
            if (hint.get("business_date") != date or hint.get("phase") != "COMMITTED"
                    or hint.get("owner") != "STAGE_PRECAPTURE" or hint.get("node_id") != "PRECAPTURE_A_0925"):
                continue
            safe(event)
            hint_raw = (json.dumps(hint, sort_keys=True, allow_nan=False) + "\n").encode()
            if (hint.get("schema_version") != "v4.runtime_graph_hint.v1"
                    or event.get("hint_sha256") != hashlib.sha256(hint_raw).hexdigest()
                    or any(item.get(key) is not False for item in (event, hint) for key in SAFETY_FLAGS)):
                raise ValueError("failure committed hint identity/SHA/safety differs")
            source = Path(hint["source_path"])
            attempt_id = source.stem
            if (not re.fullmatch(r"[a-f0-9]{32}", attempt_id)
                    or source != opening / relative / "attempts" / (attempt_id + ".json")):
                raise ValueError("failure source path differs")
            raw = SafeRoot(opening).read_bytes(relative + "/attempts/" + source.name, max_bytes=16*1024*1024)
            if hashlib.sha256(raw).hexdigest() != hint.get("source_sha256"):
                raise ValueError("failure attempt SHA differs from original committed hint")
            attempt = json.loads(raw)
            safe(attempt)
            if any(attempt.get(key) != receipt.get(key) for key in ("candidate_current_sha256", "candidate_run_id")):
                continue
            detail = attempt["payload"]
            if (attempt.get("trade_date") != date or attempt.get("stage_id") != "STAGE_0925"
                    or attempt.get("attempt_id") != attempt_id
                    or attempt.get("authorizes_selection") is not False or attempt.get("RESEARCH_ONLY") is not True
                    or attempt.get("status") != "CANNOT_CONFIRM"
                    or attempt.get("error") != "ValueError:A_NATIVE_NO_VALID_OBSERVATION_ROWS"
                    or detail.get("schema_version") != "stage_center.a_opening_native_snapshot.v1"
                    or detail.get("trade_date") != date or detail.get("stage_id") != "STAGE_0925"
                    or detail.get("capture_mode") != "NATURAL" or detail.get("temporal_cutoff_safe") is not True
                    or detail.get("rows") != [] or tuple(detail.get("requested_symbols", ())) != tuple(candidate.codes)
                    or any(item.get(key) is not False for item in (receipt, attempt, detail) for key in SAFETY_FLAGS)):
                raise ValueError("failure capture identity/count/safety differs")
            observations.append((attempt, detail, hint))
        if len(observations) != 1:
            raise ValueError("failure original committed attempt absent or ambiguous")
        attempt, detail, hint = observations[0]
        zone = ZoneInfo("Asia/Shanghai")
        def clock(value):
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                raise ValueError("failure clock zone missing")
            return parsed.astimezone(zone)
        start, captured, cutoff, finished, notified = map(clock, (detail["capture_started_at"], detail["captured_at"],
            detail["market_cutoff_at"], attempt["finished_at"], hint["observed_at"]))
        if (cutoff.strftime("%Y%m%d%H%M%S") != date + "092505"
                or not cutoff.replace(second=0, microsecond=0) <= start <= captured <= finished <= cutoff
                or notified < finished or notified.strftime("%Y%m%d") != date):
            raise ValueError("failure capture clock differs")
        raw_rows = [row for batch in detail["raw_batches"] for row in batch["raw_rows"]]
        requested = len(candidate.codes)
        if not requested or len(raw_rows) != requested or len(detail["rejected_rows"]) != requested:
            raise ValueError("failure raw/rejected coverage differs")
        missing_time = sum(not row.get("update_time") for row in raw_rows)
        future_time = sum(bool(row.get("update_time")) and
                          datetime.fromisoformat(row["update_time"]).replace(tzinfo=zone) > captured for row in raw_rows)
        reason = "A_NATIVE_NO_VALID_OBSERVATION_ROWS"
        return {
            "source_status": "CANNOT_CONFIRM", "requested_rows": requested, "source_rows": 0,
            "source_evidence": [
                reason, "failed_capture_scope=OWNER_COMMITTED_HINT_SHA_BOUND_DIAGNOSTIC_NOT_INDEPENDENT_CERTIFICATION",
                "attempt_path=" + hint["source_path"], "attempt_sha256=" + hint["source_sha256"],
                "runner_receipt_observed_sha256=" + receipt_sha, "candidate_current_sha256=" + candidate_sha,
                f"raw_rows={len(raw_rows)};rejected_rows={requested};accepted_rows=0;source_time_after_capture={future_time};source_time_missing={missing_time}",
                "actual_captured_at=" + detail["captured_at"], "authorizes_selection=false;natural_verified=false;pit_certified=false",
            ],
            "cannot_confirm": list(dict.fromkeys([*(market.get("cannot_confirm") or []), reason,
                f"A_NATIVE_REJECTED_ROWS:{requested}:SOURCE_TIME_AFTER_CAPTURE={future_time}:SOURCE_TIME_MISSING={missing_time}"])),
        }
    except (CandidateInputError, OSError, ValueError, KeyError, TypeError, AttributeError, UnicodeError):
        return None


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

def _project_market(market: str, envelope: Mapping[str, Any], *, trade_date: str, stage_id: str) -> dict[str, Any]:
    if any(envelope.get(key) != expected for key, expected in (
            ("trade_date", trade_date), ("stage_id", stage_id), ("market", market))):
        raise SelectionError("selection envelope date/stage/market mismatch")
    rows = envelope.get("rows")
    if not isinstance(rows, list):
        raise SelectionError("selection rows are not a list")
    if type(envelope.get("selected_rows")) is not int or envelope["selected_rows"] != len(rows):
        raise SelectionError("selection selected_rows differs from actual rows")
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
    projected = {
        "trade_date": trade_date,
        "stage_id": stage_id,
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
        **research_source_projection(envelope.get("source_evidence"), trade_date, market),
        "rows": projected_rows,
        "cannot_confirm": list(envelope.get("cannot_confirm") or []),
    }
    evidence = set(projected["source_evidence"])
    if market == "HK_CONNECT" and (
        "selection_mode=BACKFILL" in evidence or bool(_BACKFILL_MARKERS & evidence)
    ):
        # Historical evidence can also occupy the ordinary latest key. Its
        # immutable selection trio proves identity, not a natural/formal run.
        # Label every known backfill marker irrespective of row count/status.
        projected["selection_mode"] = "BACKFILL"
    return projected


def _verified_selection_provenance(
    store: SelectionStore,
    *,
    trade_date: str,
    stage_id: str,
    market: str,
    run_id: str,
) -> dict[str, Any]:
    """Expose SelectionStore identity only after rechecking its exact latest run."""
    latest = store._latest()
    entry = latest.get("entries", {}).get(store._key(trade_date, stage_id, market))
    if not isinstance(entry, Mapping) or entry.get("run_id") != run_id:
        raise SelectionError("selection latest identity changed during provenance projection")
    verified = store._verify_run(trade_date, stage_id, market, run_id)
    if verified.get("run_id") != run_id:
        raise SelectionError("selection run identity mismatch during provenance projection")
    for latest_field, verified_field in (
        ("manifest_sha256", "manifest_sha256"),
        ("receipt_sha256", "receipt_sha256"),
        ("artifact_sha256", "artifact_sha256"),
    ):
        if entry.get(latest_field) != verified.get(verified_field):
            raise SelectionError("selection latest pointer SHA mismatch during provenance projection")
    return {
        "selection_run_id": run_id,
        "selection_manifest_sha256": verified["manifest_sha256"],
        "selection_receipt_sha256": verified["receipt_sha256"],
        "selection_artifact_sha256": verified["artifact_sha256"],
        "selection_manifest_receipt_verified": True,
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
    """Read-only shared selection consumer for V3/V4 adapters."""

    def __init__(self, root: Any, *, a_name_pool_root: Path | str | None = None, execution_receipt_root: Path | str | None = None):
        self.store = SelectionStore(root)
        # This exact sibling layout is the existing Stage scheduler contract.
        # No broad root scan or latest/date fallback is permitted.
        selection_root = Path(root).expanduser()
        self.execution_receipt_root = (
            Path(execution_receipt_root).expanduser() if execution_receipt_root is not None
            else selection_root.parent / "receipts"
            if selection_root.name == "selection" and selection_root.parent.name == "stage"
            else selection_root.parents[2] / "receipts" / "backfill" / selection_root.name
            if len(selection_root.parents) >= 3
            and selection_root.parent.name == "backfill"
            and selection_root.parents[1].name == "selection"
            and selection_root.name not in {".", ".."}
            and _BACKFILL_ID_RE.fullmatch(selection_root.name)
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
            "verification_status": "CANNOT_CONFIRM",
            "pool_ids": [],
            "expected_pool_ids": list(_A_NAME_POOL_IDS),
            "verified_pool_ids": [],
            "unverified_pool_ids": list(_A_NAME_POOL_IDS),
            "pool_status": "CANNOT_CONFIRM",
            "pool_audit": {},
            "conflicted_codes": [],
            "selector_sha_source": None,
            "error": None,
        }
        if self.a_name_pool_root is None:
            result["error"] = "A canonical preselection pool root is not configured"
            return result

        # The manifest and its owning root are shared evidence. Validate them
        # once outside the per-pool isolation boundary so a missing or unsafe
        # shared root can never be mistaken for an ordinary missing pool.
        try:
            pool_store = PreselectionPoolStore(self.a_name_pool_root.expanduser())
            pool_root = pool_store.root
            manifest_relative = f"preselection_pools/{trade_date}/manifest.json"
            manifest_bytes = pool_store._io.read_bytes(manifest_relative)
            manifest = json.loads(manifest_bytes.decode("utf-8"))
            if not isinstance(manifest, Mapping):
                raise ValueError("shared preselection manifest must contain an object")
            canonical_manifest_bytes = json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            if manifest_bytes != canonical_manifest_bytes:
                raise ValueError("shared preselection manifest bytes are not canonical")
            for pool_id, digest in manifest.items():
                if pool_id not in POOL_ORDER or not _SHA256_RE.fullmatch(str(digest or "")):
                    raise ValueError("shared preselection manifest entries are invalid")
            manifest_raw_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        except Exception as error:
            result["error"] = f"SHARED_PRESELECTION_ROOT_OR_MANIFEST_CANNOT_CONFIRM:{error}"
            return result

        mapping: dict[str, str] = {}
        conflicted_codes: set[str] = set()
        artifact_shas: dict[str, str] = {}
        source_shas: dict[str, str] = {}
        receipt_shas: dict[str, str] = {}
        pool_audit: dict[str, dict[str, Any]] = {}
        verified_pool_ids: list[str] = []
        try:
            for pool_id in _A_NAME_POOL_IDS:
                try:
                    snapshot = pool_store.read_pool_snapshot(trade_date, pool_id)
                except PreselectionPoolArtifactMissing:
                    pool_audit[pool_id] = {
                        "status": "MISSING",
                        "verification_status": "CANNOT_CONFIRM",
                        "reason": "POOL_ARTIFACT_MISSING",
                    }
                    continue
                except PreselectionPoolIntegrityError as error:
                    pool_audit[pool_id] = {
                        "status": "ISOLATED",
                        "verification_status": "CANNOT_CONFIRM",
                        "reason": error.reason,
                    }
                    continue

                # A changed shared root or manifest invalidates the full read;
                # it is deliberately outside the per-pool contract handler.
                snapshot_root = snapshot.get("physical_source_root")
                if (
                    (snapshot_root is not None and Path(str(snapshot_root)) != pool_root)
                    or snapshot.get("manifest_raw_sha256") != manifest_raw_sha256
                ):
                    raise RuntimeError("shared preselection root or manifest changed during name read")

                pool = snapshot.get("artifact")
                try:
                    if not isinstance(pool, Mapping) or pool.get("pool_id") != pool_id:
                        raise ValueError("pool snapshot identity is invalid")
                    rows = pool.get("rows")
                    if not isinstance(rows, list):
                        raise ValueError("pool rows are invalid")
                    source_sha = str(pool.get("source_sha256") or "").strip().lower()
                    if not _SHA256_RE.fullmatch(source_sha):
                        raise ValueError("pool source SHA is invalid")

                    pool_mapping: dict[str, str] = {}
                    pool_conflicts: set[str] = set()
                    for index, row in enumerate(rows):
                        if not isinstance(row, Mapping):
                            raise ValueError(f"pool row is invalid at index {index}")
                        for date_field in ("trade_date", "target_date"):
                            if (
                                date_field in row
                                and _normalize_authority_date(row.get(date_field)) != trade_date
                            ):
                                raise ValueError(f"pool {date_field} mismatch at row {index}")
                        alias_codes: dict[str, str] = {}
                        for alias in _A_CODE_ALIAS_FIELDS:
                            raw_alias = str(row.get(alias) or "").strip()
                            if not raw_alias:
                                continue
                            normalized_alias = _normalize_a_code(raw_alias)
                            if not normalized_alias:
                                raise ValueError(f"pool code alias is invalid at row {index}: {alias}")
                            alias_codes[alias] = normalized_alias
                        if len(set(alias_codes.values())) > 1:
                            raise ValueError(f"pool code alias conflict at row {index}")
                        code = next(iter(alias_codes.values()), "")
                        if not code or code in pool_conflicts:
                            continue
                        names = {
                            name
                            for name in (
                                _canonical_name(row.get("name"), code),
                                _canonical_name(row.get("stock_name"), code),
                            )
                            if name
                        }
                        if len(names) > 1:
                            pool_mapping.pop(code, None)
                            pool_conflicts.add(code)
                            continue
                        if not names:
                            continue
                        name = next(iter(names))
                        previous = pool_mapping.get(code)
                        if previous is not None and previous != name:
                            pool_mapping.pop(code, None)
                            pool_conflicts.add(code)
                        else:
                            pool_mapping[code] = name
                except (KeyError, TypeError, ValueError) as error:
                    pool_audit[pool_id] = {
                        "status": "ISOLATED",
                        "verification_status": "CANNOT_CONFIRM",
                        "reason": f"POOL_CONTENT_INVALID:{error}",
                    }
                    continue

                for code, name in pool_mapping.items():
                    if code in conflicted_codes:
                        continue
                    previous = mapping.get(code)
                    if previous is not None and previous != name:
                        mapping.pop(code, None)
                        conflicted_codes.add(code)
                    else:
                        mapping[code] = name
                for code in pool_conflicts:
                    mapping.pop(code, None)
                    conflicted_codes.add(code)

                artifact_sha = str(snapshot.get("artifact_sha256") or "").lower()
                artifact_raw_sha = str(snapshot.get("artifact_raw_sha256") or "").lower()
                receipt_raw_sha = str(snapshot.get("receipt_raw_sha256") or "").lower()
                if not all(
                    _SHA256_RE.fullmatch(value)
                    for value in (artifact_sha, artifact_raw_sha, receipt_raw_sha)
                ):
                    raise RuntimeError(f"shared preselection pool snapshot SHA is invalid: {pool_id}")
                artifact_shas[pool_id] = artifact_sha
                source_shas[pool_id] = source_sha
                receipt_shas[pool_id] = receipt_raw_sha
                verified_pool_ids.append(pool_id)
                pool_audit[pool_id] = {
                    "status": "VERIFIED",
                    "verification_status": "VERIFIED",
                    "source_sha256": source_sha,
                    "trio_raw_sha256": {
                        "artifact": artifact_raw_sha,
                        "manifest": manifest_raw_sha256,
                        "receipt": receipt_raw_sha,
                    },
                }
        except Exception as error:
            result.update(
                {
                    "error": f"SHARED_PRESELECTION_ROOT_OR_MANIFEST_CANNOT_CONFIRM:{error}",
                    "pool_audit": pool_audit,
                    "mapping": {},
                    "pool_ids": [],
                    "verified_pool_ids": [],
                    "unverified_pool_ids": list(_A_NAME_POOL_IDS),
                    "pool_status": "CANNOT_CONFIRM",
                }
            )
            return result

        unverified_pool_ids = [
            pool_id for pool_id in _A_NAME_POOL_IDS if pool_id not in verified_pool_ids
        ]
        result.update(
            {
                "mapping": mapping,
                "pool_ids": list(verified_pool_ids),
                "verified_pool_ids": list(verified_pool_ids),
                "unverified_pool_ids": unverified_pool_ids,
                "pool_status": "COMPLETE" if not unverified_pool_ids else "PARTIAL_SOURCE_SET",
                "verification_status": "CANNOT_CONFIRM" if unverified_pool_ids else "VERIFIED",
                "pool_audit": pool_audit,
                "conflicted_codes": sorted(conflicted_codes),
                "receipt_sha256": _canonical_digest(receipt_shas) if receipt_shas else None,
                "selector_sha256": _canonical_digest(artifact_shas) if artifact_shas else None,
                "source_sha256": _canonical_digest(source_shas) if source_shas else None,
                "selector_sha_source": (
                    "CANONICAL_PRESELECTION_POOL_ARTIFACTS" if verified_pool_ids else None
                ),
            }
        )
        if mapping or conflicted_codes:
            result["status"] = _NAME_AUTHORITY_EXACT
        else:
            result["status"] = _NAME_AUTHORITY_CANNOT_CONFIRM

        if unverified_pool_ids or conflicted_codes:
            audit_summary = {
                "pool_status": result["pool_status"],
                "verification_status": result["verification_status"],
                "verified_pool_ids": verified_pool_ids,
                "unverified_pools": {
                    pool_id: pool_audit.get(pool_id, {}) for pool_id in unverified_pool_ids
                },
                "trio_raw_sha256": {
                    pool_id: pool_audit[pool_id]["trio_raw_sha256"]
                    for pool_id in verified_pool_ids
                },
                "conflicted_codes": sorted(conflicted_codes),
            }
            result["error"] = "NAME_POOL_AUDIT:" + json.dumps(
                audit_summary,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        elif result["status"] == _NAME_AUTHORITY_CANNOT_CONFIRM:
            result["error"] = "VALIDATED_NAME_POOLS_CONTAIN_NO_USABLE_NAMES"

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
        output["name_authority_pool_ids"] = list(authority.get("pool_ids") or [])
        output["name_authority_expected_pool_ids"] = list(
            authority.get("expected_pool_ids") or _A_NAME_POOL_IDS
        )
        output["name_authority_unverified_pool_ids"] = list(
            authority.get("unverified_pool_ids") or []
        )
        output["name_authority_pool_status"] = authority.get("pool_status")
        output["name_authority_verification_status"] = authority.get("verification_status")
        output["name_authority_pool_audit"] = dict(authority.get("pool_audit") or {})
        output["name_authority_conflicted_codes"] = list(
            authority.get("conflicted_codes") or []
        )
        output["name_authority_applied_count"] = 0
        output["name_authority_missing_count"] = len(missing_rows)
        output["name_authority_error"] = authority.get("error")
        projected_rows = [dict(row) for row in rows]
        mapping = authority.get("mapping") if authority.get("status") == _NAME_AUTHORITY_EXACT else {}
        conflicted_codes = set(authority.get("conflicted_codes") or [])
        missing_codes: list[str] = []
        conflicted_rows: list[str] = []
        for row in projected_rows:
            if _row_has_valid_name(row):
                continue
            code = _normalize_a_code(row.get("code"))
            if code in conflicted_codes:
                missing_codes.append(code)
                conflicted_rows.append(code)
                continue
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
            if (
                any(code not in conflicted_rows for code in missing_codes)
                and _NAME_AUTHORITY_CODE_NOT_FOUND not in cannot_confirm
            ):
                cannot_confirm.append(_NAME_AUTHORITY_CODE_NOT_FOUND)
            if conflicted_rows and _NAME_AUTHORITY_NAME_CONFLICT not in cannot_confirm:
                cannot_confirm.append(_NAME_AUTHORITY_NAME_CONFLICT)
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
                projected = _project_market(market, envelope, trade_date=trade_date, stage_id=stage_id)
                # Keep the already configured/verified original namespace for
                # the reader's independent check; this object never leaves get().
                projected["_verified_selection_store"] = candidate_store
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
            envelope = self.store.read_verified(trade_date, stage_id, market)
            natural = _project_market(
                market, envelope, trade_date=trade_date, stage_id=stage_id,
            )
            # Expose the same verified immutable trio for ordinary saved
            # selections; it must not be available only on backfill results.
            natural.update(_verified_selection_provenance(
                self.store,
                trade_date=trade_date,
                stage_id=stage_id,
                market=market,
                run_id=str(envelope.get("run_id") or ""),
            ))
            if natural.get("selection_mode") == "BACKFILL":
                # The immutable selection trio proves artifact identity, not
                # natural or formal execution. Keep it out of the ordinary
                # Stage result while preserving explicit historical display.
                if not allow_backfill:
                    return _invalid_market_with_reason(
                        market, "BACKFILL_NOT_FORMAL_STAGE_SELECTION"
                    )
                natural.update(
                    runner_receipt_verified=False,
                    runner_receipt_status="CANNOT_CONFIRM",
                    runner_receipt_sha256=None,
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
        selection_stores: dict[str, SelectionStore] = {}
        for market in requested_markets:
            item = self._market_from_store_or_backfill(
                trade_date, stage_id, market, allow_backfill=allow_backfill
            )
            selection_stores[market] = item.pop("_verified_selection_store", self.store)
            projected.append(item)

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
            "RESEARCH_ONLY": True,
            **SAFETY_FLAGS,
        }
        response["execution_evidence"] = read_stage_execution(
            self.execution_receipt_root, trade_date, stage_id, response["markets"],
            selection_store=self.store, selection_stores=selection_stores,
        )
        # Current observations are a separate delivery lane; original formal
        # selected counts, execution/PIT status and failed receipts stay exact.
        from stage_center.snapshot_recovery import read_for_api
        a_formal = response.get("markets", {}).get("A_SHARE", {})
        if a_formal.get("selection_manifest_receipt_verified") is True or a_formal.get("rows"):
            response["snapshot_recovery"] = {"mode": "SNAPSHOT_RECOVERY_OBSERVATION", "status": "FORMAL_RESULT_AVAILABLE", "markets": {}}
        else:
            response["snapshot_recovery"] = read_for_api(self.store.root, trade_date, stage_id)
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
