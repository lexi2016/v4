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

from .contracts import EIGHT_STAGES, SAFETY_FLAGS
from .selection import SelectionError, SelectionStore, _validate_date, _validate_market, _validate_stage


RESPONSE_SOURCE = "SHARED_STAGE_CENTER"
READ_ONLY_CANNOT_CONFIRM = "SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID"
_KNOWN_MARKETS = frozenset({"A_SHARE", "HK_CONNECT"})
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_NAME_AUTHORITY_EXACT = "EXACT_DATE_READ_OVERLAY"
_NAME_AUTHORITY_NOT_NEEDED = "NOT_NEEDED"
_NAME_AUTHORITY_CANNOT_CONFIRM = "CANNOT_CONFIRM"
_NAME_AUTHORITY_CODE_NOT_FOUND = "NAME_AUTHORITY_CODE_NOT_FOUND"


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
    match = re.search(r"(\d{6})", raw)
    return f"A.{match.group(1)}" if match else raw


def _valid_name(value: Any, code: str) -> bool:
    normalized = str(value or "").strip()
    return bool(normalized) and normalized.upper() != str(code or "").strip().upper()


def _row_has_valid_name(row: Mapping[str, Any]) -> bool:
    code = str(row.get("code") or "").strip()
    return _valid_name(row.get("name"), code) or _valid_name(row.get("stock_name"), code)


def _authority_root(receipt_root: Path) -> Path:
    """Return the bounded state root for a dated authority receipt root."""
    resolved = receipt_root.expanduser().resolve()
    if resolved.name == "receipts" and resolved.parent.name == "research_panel_daily":
        return resolved.parent.parent
    return resolved.parent


def _file_sha256(path: Path) -> str:
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
        "requested_rows": 0,
        "source_rows": 0,
        "selected_rows": 0,
        "coverage_ratio": 0.0,
        "missing_symbols": [],
        "rows": [],
        "cannot_confirm": [READ_ONLY_CANNOT_CONFIRM],
    }


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

    def __init__(self, root: Any, *, a_name_authority_root: Path | str | None = None):
        self.store = SelectionStore(root)
        self.a_name_authority_root = (
            Path(a_name_authority_root).expanduser() if a_name_authority_root is not None else None
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
            "selector_sha_source": None,
            "error": "A name authority root is not configured",
        }
        try:
            if self.a_name_authority_root is None:
                raise ValueError(result["error"])
            receipt_root = self.a_name_authority_root.expanduser().resolve()
            receipt_path = receipt_root / f"a-{trade_date}.json"
            receipt_bytes = receipt_path.read_bytes()
            result["receipt_sha256"] = hashlib.sha256(receipt_bytes).hexdigest()
            receipt = json.loads(receipt_bytes.decode("utf-8-sig"))
            if not isinstance(receipt, Mapping):
                raise ValueError("A name authority receipt must be an object")
            if any(receipt.get(flag) is not False for flag in SAFETY_FLAGS):
                raise ValueError("A name authority receipt safety flags must be false")
            if _normalize_authority_date(receipt.get("target_date")) != trade_date:
                raise ValueError("A name authority receipt target_date mismatch")

            if receipt.get("status") == "READY":
                payload: Mapping[str, Any] = receipt
            elif receipt.get("status") == "ATTEMPTED":
                lanes = receipt.get("lanes")
                payload = lanes.get("A") if isinstance(lanes, Mapping) else None
                if not isinstance(payload, Mapping) or payload.get("status") != "READY":
                    raise ValueError("A name authority A lane status must be READY")
                if _normalize_authority_date(payload.get("target_date")) != trade_date:
                    raise ValueError("A name authority A lane target_date mismatch")
            else:
                raise ValueError("A name authority receipt status is not READY or ATTEMPTED")
            if any(payload.get(flag) is not False for flag in SAFETY_FLAGS):
                raise ValueError("A name authority A lane safety flags must be false")

            formula = payload.get("formula")
            if not isinstance(formula, Mapping) or formula.get("status") != "READY":
                raise ValueError("A name authority formula status must be READY")
            if _normalize_authority_date(formula.get("target_date")) != trade_date:
                raise ValueError("A name authority formula target_date mismatch")
            selector_value = formula.get("selector")
            if not isinstance(selector_value, str) or not selector_value.startswith("/"):
                raise ValueError("A name authority selector path must be absolute")
            selector_path = Path(selector_value).expanduser().resolve()
            try:
                selector_path.relative_to(_authority_root(receipt_root))
            except ValueError as error:
                raise ValueError("A name authority selector path is outside the authority root") from error
            if not selector_path.is_file():
                raise ValueError("A name authority selector is missing")
            actual_sha = _file_sha256(selector_path)
            declared_sha = str(
                formula.get("selector_sha256")
                or payload.get("selector_sha256")
                or receipt.get("selector_sha256")
                or ""
            ).strip()
            if declared_sha:
                if not _SHA256_RE.fullmatch(declared_sha):
                    raise ValueError("A name authority selector SHA is malformed")
                if actual_sha.lower() != declared_sha.lower():
                    raise ValueError("A name authority selector SHA mismatch")
                selector_sha_source = "DECLARED_AND_VERIFIED"
            else:
                selector_sha_source = "COMPUTED_FROM_AUTHORITY_PATH"

            try:
                import pyarrow.parquet as parquet

                schema = parquet.read_schema(selector_path)
                columns = set(schema.names)
                if not {"trade_date", "name"}.issubset(columns) or not ({"ts_code", "raw_code"} & columns):
                    raise ValueError("A name authority selector schema is missing")
                code_column = "ts_code" if "ts_code" in columns else "raw_code"
                read_columns = ["trade_date", code_column, "name"]
                if "stock_name" in columns:
                    read_columns.append("stock_name")
                table = parquet.read_table(
                    selector_path,
                    columns=read_columns,
                    filters=[("trade_date", "=", trade_date)],
                )
                records = table.to_pylist()
            except Exception as error:
                raise ValueError("A name authority selector is unreadable") from error
            if not records:
                raise ValueError("A name authority selector has no exact trade_date rows")
            mapping: dict[str, str] = {}
            for row in records:
                if not isinstance(row, Mapping):
                    raise ValueError("A name authority selector row is not an object")
                raw_code = row.get("ts_code") or row.get("raw_code")
                code = _normalize_a_code(raw_code)
                name = str(row.get("name") or row.get("stock_name") or "").strip()
                if not code or not _valid_name(name, code) or name == str(raw_code or "").strip():
                    continue
                previous = mapping.get(code)
                if previous is not None and previous != name:
                    raise ValueError(f"A name authority selector name conflict: {code}")
                mapping[code] = name
            if not mapping:
                raise ValueError("A name authority selector map is empty")
            result.update(
                {
                    "status": _NAME_AUTHORITY_EXACT,
                    "mapping": mapping,
                    "selector_sha256": actual_sha,
                    "selector_sha_source": selector_sha_source,
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
        rows = list(market_payload.get("rows") or [])
        missing_rows = [row for row in rows if isinstance(row, Mapping) and not _row_has_valid_name(row)]
        if not missing_rows:
            output = dict(market_payload)
            output.update(
                {
                    "name_authority_status": _NAME_AUTHORITY_NOT_NEEDED,
                    "name_authority_receipt_sha256": None,
                    "name_authority_selector_sha256": None,
                    "name_authority_selector_sha_source": None,
                    "name_authority_applied_count": 0,
                    "name_authority_missing_count": 0,
                    "name_authority_error": None,
                }
            )
            return output

        authority = self._load_a_name_authority(trade_date)
        output = dict(market_payload)
        output["name_authority_receipt_sha256"] = authority.get("receipt_sha256")
        output["name_authority_selector_sha256"] = authority.get("selector_sha256")
        output["name_authority_selector_sha_source"] = authority.get("selector_sha_source")
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

    def get(
        self,
        trade_date: str,
        stage_id: str,
        *,
        markets: Sequence[str] | None = None,
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
            try:
                envelope = self.store.read_verified(trade_date, stage_id, market)
                projected.append(self._overlay_a_names(_project_market(market, envelope), trade_date))
            except (SelectionError, OSError, ValueError, TypeError):
                # Missing latest, missing trio, malformed JSON, SHA mismatch,
                # and any other read-integrity error deliberately collapse to
                # the same external evidence state.
                projected.append(_invalid_market(market))

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
