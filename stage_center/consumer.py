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
from .selection import SelectionError, SelectionStore, _validate_date, _validate_market, _validate_stage


RESPONSE_SOURCE = "SHARED_STAGE_CENTER"
READ_ONLY_CANNOT_CONFIRM = "SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID"
_KNOWN_MARKETS = frozenset({"A_SHARE", "HK_CONNECT"})
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_BACKFILL_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_BACKFILL_MARKERS = frozenset(
    {
        "recovery_mode=HISTORICAL_BACKFILL",
        "due_status=HISTORICAL_BACKFILL",
        "HISTORICAL_BACKFILL",
    }
)
_NAME_AUTHORITY_EXACT = "EXACT_DATE_READ_OVERLAY"
_NAME_AUTHORITY_NOT_NEEDED = "NOT_NEEDED"
_NAME_AUTHORITY_CANNOT_CONFIRM = "CANNOT_CONFIRM"
_NAME_AUTHORITY_CODE_NOT_FOUND = "NAME_AUTHORITY_CODE_NOT_FOUND"
_NAME_AUTHORITY_NAME_CONFLICT = "NAME_AUTHORITY_NAME_CONFLICT"
_NAME_AUTHORITY_SOURCE = "A_CANONICAL_PRESELECTION_POOLS"
_A_CODE_ALIAS_FIELDS = ("symbol", "stock_code", "ts_code", "code")
_A_CODE_RE = re.compile(r"(?:(?:A|SH|SZ|BJ)\.(\d{6})|(\d{6})(?:\.(?:SH|SZ))?)\Z")
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


def _valid_name(value: Any, code: str) -> bool:
    normalized = str(value or "").strip()
    return bool(normalized) and normalized.upper() != str(code or "").strip().upper()


def _canonical_name(value: Any, code: str) -> str:
    normalized = "".join(str(value or "").split())
    return normalized if normalized and normalized.upper() != str(code or "").strip().upper() else ""


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


def _project_market(
    market: str,
    envelope: Mapping[str, Any],
    *,
    trade_date: str | None = None,
    stage_id: str | None = None,
) -> dict[str, Any]:
    if ((trade_date is not None and envelope.get("trade_date") != trade_date)
            or (stage_id is not None and envelope.get("stage_id") != stage_id)
            or envelope.get("market", market) != market):
        raise SelectionError("selection envelope date/stage/market mismatch")
    rows = envelope.get("rows")
    if not isinstance(rows, list):
        raise SelectionError("selection rows are not a list")
    if "selected_rows" in envelope and (
        type(envelope.get("selected_rows")) is not int or envelope["selected_rows"] != len(rows)
    ):
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
        **({"trade_date": trade_date} if trade_date is not None else {}),
        **({"stage_id": stage_id} if stage_id is not None else {}),
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
    evidence = set(projected["source_evidence"])
    if market == "HK_CONNECT" and (
        "selection_mode=BACKFILL" in evidence or bool(_BACKFILL_MARKERS & evidence)
    ):
        # A backfill marker can occupy the ordinary latest key. Its selection
        # identity is useful provenance, but does not prove a natural Stage run.
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
    """Expose immutable SelectionStore identity only after rereading its run."""
    latest = store._latest()
    entry = latest.get("entries", {}).get(store._key(trade_date, stage_id, market))
    if not isinstance(entry, Mapping) or entry.get("run_id") != run_id:
        raise SelectionError("selection latest identity changed during provenance projection")
    verified = store._verify_run(trade_date, stage_id, market, run_id)
    if verified.get("run_id") != run_id:
        raise SelectionError("selection run identity mismatch during provenance projection")
    for field in ("manifest_sha256", "receipt_sha256", "artifact_sha256"):
        if entry.get(field) != verified.get(field):
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
                "selection_mode": item.get("selection_mode"),
                "backfill_run_id": item.get("backfill_run_id"),
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

    def __init__(
        self,
        root: Any,
        *,
        a_name_pool_root: Path | str | None = None,
        runner_receipt_root: Path | str | None = None,
    ):
        self.store = SelectionStore(root)
        self.a_name_pool_root = (
            Path(a_name_pool_root).expanduser() if a_name_pool_root is not None else None
        )
        self.runner_receipt_root = (
            Path(runner_receipt_root).expanduser()
            if runner_receipt_root is not None
            else self.store.root.parent / "receipts"
        )
        self._a_name_authority_cache: dict[str, dict[str, Any]] = {}

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
            natural = _project_market(market, envelope, trade_date=trade_date, stage_id=stage_id)
            natural.update(_verified_selection_provenance(
                self.store, trade_date=trade_date, stage_id=stage_id,
                market=market, run_id=str(envelope.get("run_id") or ""),
            ))
            if natural.get("selection_mode") == "BACKFILL":
                if not allow_backfill:
                    return _invalid_market_with_reason(
                        market, "BACKFILL_NOT_FORMAL_STAGE_SELECTION"
                    )
                natural.update(runner_receipt_verified=False,
                               runner_receipt_status="CANNOT_CONFIRM",
                               runner_receipt_sha256=None)
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
        rows = list(market_payload.get("rows") or [])
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
                    trade_date,
                    stage_id,
                    market,
                    allow_backfill=allow_backfill,
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
