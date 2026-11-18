"""Versioned, fail-closed resume adapter for the pinned P5.15 R2 rule.

The transition body is loaded from the byte-pinned original ``event_rules.py``.
Only its function signature, initial local-state restoration, EOF behavior, and
return tuple are transformed in memory. Intermediate chunk boundaries never
close an active PB or family. This module verifies supplied anchor/checkpoint
bytes against caller-provided independent SHA pins; it does not fetch Drive
objects or certify a real listing/reset record itself.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any


ADAPTER_VERSION = "P515_R2_RESUME_ADAPTER_V1"
SNAPSHOT_SCHEMA = "P515_R2_RESUME_SNAPSHOT_V1"
ANCHOR_SCHEMA = "P515_R2_ANCHOR_RECEIPT_V1"
ORIGINAL_RULE = "P5146_EVENT_RULE_R2"
ORIGINAL_SOURCE_SHA256 = "0c5f20e93072701c2c06d9cddcf4b28832888028b67eece2d7fc14be1ccb1381"

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_FLOAT_TAG = "$p515_r2_type"


class R2ResumeError(ValueError):
    """Raised when provenance, identity, state, or continuity cannot be proved."""


@dataclass(frozen=True)
class R2AnchorGrant:
    """Independent caller-side pin/grant for an anchor receipt.

    ``pinned_receipt_sha256`` and ``authorization_receipt_sha256`` must come
    from the existing external authorization/readback process. This adapter
    checks their bytes and scope fields; a string in this object is not itself
    proof that such an external check occurred.
    """

    pinned_receipt_sha256: str
    verifier_id: str
    verification_method: str
    authorization_receipt_sha256: str

    def __post_init__(self) -> None:
        _require_sha(self.pinned_receipt_sha256, "pinned_receipt_sha256")
        _require_sha(self.authorization_receipt_sha256, "authorization_receipt_sha256")
        if not self.verifier_id.strip():
            raise R2ResumeError("ANCHOR_GRANT_VERIFIER_REQUIRED")
        if not self.verification_method.strip():
            raise R2ResumeError("ANCHOR_GRANT_METHOD_REQUIRED")


@dataclass(frozen=True)
class R2Delta:
    """Newly appended rows from one successful feed/finalize operation."""

    observations: list[dict[str, Any]]
    candidates: list[dict[str, Any]]
    completed: list[dict[str, Any]]
    pullbacks: list[dict[str, Any]]
    input_rows_sha256: str
    runtime_state_sha256: str


def _require_sha(value: str, field: str) -> None:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise R2ResumeError(f"INVALID_SHA256:{field}")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _wire(value: Any) -> Any:
    """Encode JSON-compatible values without NaN/Infinity or map-tag collisions."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return {_FLOAT_TAG: "float", "value": "nan"}
        if math.isinf(value):
            return {_FLOAT_TAG: "float", "value": "+inf" if value > 0 else "-inf"}
        return value
    if isinstance(value, Mapping):
        items = []
        for key in sorted(value):
            if not isinstance(key, str):
                raise R2ResumeError("NON_STRING_MAPPING_KEY")
            items.append([key, _wire(value[key])])
        return {_FLOAT_TAG: "map", "value": items}
    if isinstance(value, (list, tuple)):
        return {_FLOAT_TAG: "list", "value": [_wire(item) for item in value]}
    raise R2ResumeError(f"UNSUPPORTED_STATE_VALUE:{type(value).__name__}")


def _unwire(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if not isinstance(value, dict) or set(value) != {_FLOAT_TAG, "value"}:
        raise R2ResumeError("INVALID_WIRE_VALUE")
    kind = value[_FLOAT_TAG]
    payload = value["value"]
    if kind == "float":
        if payload == "nan":
            return float("nan")
        if payload == "+inf":
            return float("inf")
        if payload == "-inf":
            return float("-inf")
        raise R2ResumeError("INVALID_WIRE_FLOAT")
    if kind == "list":
        if not isinstance(payload, list):
            raise R2ResumeError("INVALID_WIRE_LIST")
        return [_unwire(item) for item in payload]
    if kind == "map":
        if not isinstance(payload, list):
            raise R2ResumeError("INVALID_WIRE_MAP")
        result: dict[str, Any] = {}
        for pair in payload:
            if not isinstance(pair, list) or len(pair) != 2 or not isinstance(pair[0], str):
                raise R2ResumeError("INVALID_WIRE_MAP_ENTRY")
            if pair[0] in result:
                raise R2ResumeError("DUPLICATE_WIRE_MAP_KEY")
            result[pair[0]] = _unwire(pair[1])
        return result
    raise R2ResumeError("UNKNOWN_WIRE_TYPE")


def _canonical_wire_bytes(value: Any) -> bytes:
    return json.dumps(_wire(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _strict_json_loads(data: bytes, label: str) -> Any:
    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise R2ResumeError(f"DUPLICATE_JSON_KEY:{label}:{key}")
            out[key] = value
        return out

    def reject_constant(constant: str) -> None:
        raise R2ResumeError(f"NONSTANDARD_JSON_CONSTANT:{label}:{constant}")

    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=no_duplicates, parse_constant=reject_constant)
    except R2ResumeError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise R2ResumeError(f"INVALID_JSON:{label}") from exc


def _identity(source_identity: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    if not isinstance(source_identity, Mapping) or not source_identity:
        raise R2ResumeError("SOURCE_IDENTITY_REQUIRED")
    normalized = deepcopy(dict(source_identity))
    if any(not isinstance(key, str) for key in normalized):
        raise R2ResumeError("SOURCE_IDENTITY_KEYS_MUST_BE_STRINGS")
    generation_keys = ("generation", "panel_generation", "source_generation")
    basis_keys = ("factor", "price_basis", "adjustment_basis", "price_factor")
    if not any(str(normalized.get(key, "")).strip() for key in generation_keys):
        raise R2ResumeError("SOURCE_GENERATION_REQUIRED")
    if not str(normalized.get("market", "")).strip():
        raise R2ResumeError("SOURCE_MARKET_REQUIRED")
    if not any(str(normalized.get(key, "")).strip() for key in basis_keys):
        raise R2ResumeError("SOURCE_ADJUSTMENT_BASIS_REQUIRED")
    digest = _sha256(_canonical_wire_bytes(normalized))
    return normalized, digest


def source_identity_fingerprint(source_identity: Mapping[str, Any]) -> str:
    """Canonical identity digest to bind a receipt to a V4 source lineage."""
    return _identity(source_identity)[1]


def _calendar(calendar: Sequence[Any]) -> tuple[list[str], str]:
    if isinstance(calendar, (str, bytes)) or not isinstance(calendar, Sequence) or not calendar:
        raise R2ResumeError("CALENDAR_REQUIRED")
    sessions = [str(day) for day in calendar]
    if len(sessions) != len(set(sessions)):
        raise R2ResumeError("CALENDAR_DUPLICATE_SESSION")
    digest = _sha256(_canonical_wire_bytes(sessions))
    return sessions, digest


def calendar_identity_sha256(calendar: Sequence[Any]) -> str:
    """Canonical calendar digest used by anchor and resume receipts."""
    return _calendar(calendar)[1]


def _base_input_chain(symbol: str, calendar_sha256: str, source_identity_sha256: str) -> str:
    payload = f"P515_R2_INPUT_CHAIN_V1\0{symbol}\0{calendar_sha256}\0{source_identity_sha256}".encode("utf-8")
    return _sha256(payload)


def _new_runtime_state(symbol: str, sessions: list[str], calendar_sha256: str,
                       source_identity: dict[str, Any], source_identity_sha256: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "calendar_sessions": sessions,
        "calendar_sha256": calendar_sha256,
        "source_identity": source_identity,
        "source_identity_sha256": source_identity_sha256,
        "prior": [],
        "completed": [],
        "observations": [],
        "candidates": [],
        "pullbacks": [],
        "current": None,
        "prev_date": None,
        "seen_dates": [],
        "input_record_count": 0,
        "input_chain_sha256": _base_input_chain(symbol, calendar_sha256, source_identity_sha256),
        "finalized": False,
    }


def _runtime_sha256(runtime_state: dict[str, Any]) -> str:
    return _sha256(_canonical_wire_bytes(runtime_state))


def listing_initial_state_sha256(symbol: str, calendar: Sequence[Any],
                                 source_identity: Mapping[str, Any]) -> str:
    """Return the empty pre-first-bar state hash a listing receipt must bind."""
    sessions, calendar_hash = _calendar(calendar)
    identity, identity_hash = _identity(source_identity)
    return _runtime_sha256(_new_runtime_state(symbol, sessions, calendar_hash, identity, identity_hash))


def _source_runner():
    source_path = Path(__file__).resolve().parent / "evidence" / "event_rules.py"
    try:
        raw = source_path.read_bytes()
    except OSError as exc:
        raise R2ResumeError("PINNED_R2_SOURCE_NOT_AVAILABLE") from exc
    actual_sha = _sha256(raw)
    if actual_sha != ORIGINAL_SOURCE_SHA256:
        raise R2ResumeError(f"PINNED_R2_SOURCE_SHA_MISMATCH:{actual_sha}")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise R2ResumeError("PINNED_R2_SOURCE_NOT_UTF8") from exc

    patches = [
        (
            "def run_symbol(symbol, rows, calendar):",
            "def run_symbol(symbol, rows, calendar, _resume_state=None, _finalize=False):",
            "function signature",
        ),
        (
            "    seen = set()\n",
            "    seen = set()\n"
            "    if _resume_state is not None:\n"
            "        prior = deque(deepcopy(_resume_state[\"prior\"]), maxlen=20)\n"
            "        completed = deepcopy(_resume_state[\"completed\"])\n"
            "        observations = deepcopy(_resume_state[\"observations\"])\n"
            "        candidates = deepcopy(_resume_state[\"candidates\"])\n"
            "        pullbacks = deepcopy(_resume_state[\"pullbacks\"])\n"
            "        current = deepcopy(_resume_state[\"current\"])\n"
            "        prev_date = _resume_state[\"prev_date\"]\n"
            "        seen = set(_resume_state[\"seen_dates\"])\n",
            "local-state restore",
        ),
        (
            "    if current:\n"
            "        finish_pullback(\"UNKNOWN_OPEN_AT_SNAPSHOT\",prev_date)\n"
            "        finish_family(\"UNKNOWN_OPEN_AT_SNAPSHOT\",prev_date,\"NO_END_OBSERVED\")\n"
            "    return observations,candidates,completed,pullbacks",
            "    if _finalize and current:\n"
            "        finish_pullback(\"UNKNOWN_OPEN_AT_SNAPSHOT\",prev_date)\n"
            "        finish_family(\"UNKNOWN_OPEN_AT_SNAPSHOT\",prev_date,\"NO_END_OBSERVED\")\n"
            "    continuation = {\"prior\":list(prior),\"completed\":completed,\"observations\":observations,\n"
            "        \"candidates\":candidates,\"pullbacks\":pullbacks,\"current\":current,\n"
            "        \"prev_date\":prev_date,\"seen_dates\":seen}\n"
            "    return observations,candidates,completed,pullbacks,continuation",
            "EOF/snapshot and state return",
        ),
    ]
    for old, new, name in patches:
        occurrences = text.count(old)
        if occurrences != 1:
            raise R2ResumeError(f"PINNED_R2_TRANSFORM_MISMATCH:{name}:{occurrences}")
        text = text.replace(old, new, 1)

    namespace: dict[str, Any] = {
        "__file__": str(source_path),
        "__name__": "_p515_pinned_r2_adapter",
        "deepcopy": deepcopy,
    }
    try:
        exec(compile(text, f"{source_path}::{ADAPTER_VERSION}", "exec"), namespace)
    except Exception as exc:
        raise R2ResumeError("PINNED_R2_TRANSFORM_COMPILE_FAILED") from exc
    runner = namespace.get("run_symbol")
    if not callable(runner):
        raise R2ResumeError("PINNED_R2_RUNNER_MISSING")
    return runner


_RUN_R2 = _source_runner()


def _verify_grant_and_receipt(receipt_bytes: bytes, grant: R2AnchorGrant,
                              *, expected_kind: str, symbol: str,
                              calendar_sha256: str, source_identity_sha256: str) -> dict[str, Any]:
    if not isinstance(receipt_bytes, bytes):
        raise R2ResumeError("ANCHOR_RECEIPT_BYTES_REQUIRED")
    actual = _sha256(receipt_bytes)
    if actual != grant.pinned_receipt_sha256:
        raise R2ResumeError("ANCHOR_RECEIPT_SHA_MISMATCH")
    receipt = _strict_json_loads(receipt_bytes, "anchor_receipt")
    if not isinstance(receipt, dict):
        raise R2ResumeError("ANCHOR_RECEIPT_OBJECT_REQUIRED")
    required = {
        "schema", "anchor_kind", "symbol", "boundary_date", "boundary_basis",
        "rule_source_sha256", "calendar_sha256", "source_identity_sha256",
        "boundary_state_sha256", "authorization_receipt_sha256", "verified_by",
        "verification_method", "verification_id", "verified_at",
    }
    missing = sorted(required - set(receipt))
    if missing:
        raise R2ResumeError(f"ANCHOR_RECEIPT_FIELDS_MISSING:{','.join(missing)}")
    if receipt["schema"] != ANCHOR_SCHEMA:
        raise R2ResumeError("ANCHOR_RECEIPT_SCHEMA_MISMATCH")
    if receipt["anchor_kind"] != expected_kind:
        raise R2ResumeError("ANCHOR_KIND_NOT_PERMITTED")
    if receipt["symbol"] != symbol:
        raise R2ResumeError("ANCHOR_SYMBOL_MISMATCH")
    if receipt["rule_source_sha256"] != ORIGINAL_SOURCE_SHA256:
        raise R2ResumeError("ANCHOR_RULE_SHA_MISMATCH")
    if receipt["calendar_sha256"] != calendar_sha256:
        raise R2ResumeError("ANCHOR_CALENDAR_SHA_MISMATCH")
    if receipt["source_identity_sha256"] != source_identity_sha256:
        raise R2ResumeError("ANCHOR_SOURCE_IDENTITY_MISMATCH")
    _require_sha(receipt["boundary_state_sha256"], "boundary_state_sha256")
    if receipt["authorization_receipt_sha256"] != grant.authorization_receipt_sha256:
        raise R2ResumeError("ANCHOR_AUTHORIZATION_MISMATCH")
    if receipt["verified_by"] != grant.verifier_id:
        raise R2ResumeError("ANCHOR_VERIFIER_MISMATCH")
    if receipt["verification_method"] != grant.verification_method:
        raise R2ResumeError("ANCHOR_METHOD_MISMATCH")
    for key in ("boundary_date", "boundary_basis", "verification_id", "verified_at"):
        if not isinstance(receipt[key], str) or not receipt[key].strip():
            raise R2ResumeError(f"ANCHOR_RECEIPT_FIELD_INVALID:{key}")
    if expected_kind == "LISTING_INCEPTION":
        if receipt["boundary_basis"] != "VERIFIED_LISTING_INCEPTION":
            raise R2ResumeError("LISTING_INCEPTION_BASIS_REQUIRED")
    elif expected_kind == "PROVEN_CLEAN_RESET":
        if receipt["boundary_basis"] != "VERIFIED_CLEAN_RULE_RESET":
            raise R2ResumeError("CLEAN_RESET_BASIS_REQUIRED")
        reset_reason = receipt.get("reset_reason_code")
        if reset_reason != "UPSTREAM_EXPLICIT_RESET":
            raise R2ResumeError("RESET_REASON_NOT_PROVEN_CLEAN")
        if receipt.get("no_feed_gap_substitution") is not True:
            raise R2ResumeError("RESET_FEED_GAP_SUBSTITUTION_NOT_EXCLUDED")
    else:
        raise R2ResumeError("ANCHOR_KIND_NOT_PERMITTED")
    return receipt


def _provenance(receipt: dict[str, Any], grant: R2AnchorGrant) -> dict[str, Any]:
    return {
        "kind": receipt["anchor_kind"],
        "receipt_sha256": grant.pinned_receipt_sha256,
        "authorization_receipt_sha256": grant.authorization_receipt_sha256,
        "verifier_id": grant.verifier_id,
        "verification_method": grant.verification_method,
        "verification_id": receipt["verification_id"],
        "verified_at": receipt["verified_at"],
        "boundary_date": receipt["boundary_date"],
        "boundary_basis": receipt["boundary_basis"],
        "boundary_state_sha256": receipt["boundary_state_sha256"],
    }


def _strict_json_canonical_envelope(snapshot_bytes: bytes, expected_sha256: str) -> dict[str, Any]:
    _require_sha(expected_sha256, "pinned_snapshot_sha256")
    if not isinstance(snapshot_bytes, bytes):
        raise R2ResumeError("SNAPSHOT_BYTES_REQUIRED")
    if _sha256(snapshot_bytes) != expected_sha256:
        raise R2ResumeError("SNAPSHOT_SHA_MISMATCH")
    envelope = _strict_json_loads(snapshot_bytes, "snapshot")
    if not isinstance(envelope, dict):
        raise R2ResumeError("SNAPSHOT_OBJECT_REQUIRED")
    canonical = json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if canonical != snapshot_bytes:
        raise R2ResumeError("SNAPSHOT_NOT_CANONICAL_JSON")
    required = {
        "schema", "adapter_version", "original_source_sha256", "symbol", "calendar_sha256",
        "source_identity_sha256", "runtime_state", "runtime_state_sha256", "provenance",
    }
    if set(envelope) != required:
        raise R2ResumeError("SNAPSHOT_ENVELOPE_FIELDS_MISMATCH")
    if envelope["schema"] != SNAPSHOT_SCHEMA or envelope["adapter_version"] != ADAPTER_VERSION:
        raise R2ResumeError("SNAPSHOT_VERSION_MISMATCH")
    if envelope["original_source_sha256"] != ORIGINAL_SOURCE_SHA256:
        raise R2ResumeError("SNAPSHOT_RULE_SOURCE_MISMATCH")
    if not isinstance(envelope["provenance"], dict):
        raise R2ResumeError("SNAPSHOT_PROVENANCE_OBJECT_REQUIRED")
    runtime_wire = envelope["runtime_state"]
    runtime_hash = _sha256(json.dumps(runtime_wire, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8"))
    if runtime_hash != envelope["runtime_state_sha256"]:
        raise R2ResumeError("SNAPSHOT_RUNTIME_STATE_SHA_MISMATCH")
    return envelope


def _decode_runtime(envelope: dict[str, Any]) -> dict[str, Any]:
    runtime = _unwire(envelope["runtime_state"])
    if not isinstance(runtime, dict):
        raise R2ResumeError("SNAPSHOT_RUNTIME_STATE_OBJECT_REQUIRED")
    return runtime


def _validate_runtime(runtime: dict[str, Any], *, symbol: str, sessions: list[str],
                      calendar_sha256: str, source_identity: dict[str, Any],
                      source_identity_sha256: str) -> None:
    expected_keys = {
        "symbol", "calendar_sessions", "calendar_sha256", "source_identity", "source_identity_sha256",
        "prior", "completed", "observations", "candidates", "pullbacks", "current", "prev_date",
        "seen_dates", "input_record_count", "input_chain_sha256", "finalized",
    }
    if set(runtime) != expected_keys:
        raise R2ResumeError("RUNTIME_STATE_FIELDS_MISMATCH")
    if runtime["symbol"] != symbol or runtime["calendar_sessions"] != sessions:
        raise R2ResumeError("RUNTIME_SYMBOL_OR_CALENDAR_MISMATCH")
    if runtime["calendar_sha256"] != calendar_sha256:
        raise R2ResumeError("RUNTIME_CALENDAR_SHA_MISMATCH")
    if runtime["source_identity"] != source_identity or runtime["source_identity_sha256"] != source_identity_sha256:
        raise R2ResumeError("RUNTIME_SOURCE_IDENTITY_MISMATCH")
    if not isinstance(runtime["prior"], list) or len(runtime["prior"]) > 20:
        raise R2ResumeError("RUNTIME_PRIOR_INVALID")
    for field in ("completed", "observations", "candidates", "pullbacks", "seen_dates"):
        if not isinstance(runtime[field], list):
            raise R2ResumeError(f"RUNTIME_LIST_INVALID:{field}")
    if len(runtime["seen_dates"]) != len(set(runtime["seen_dates"])):
        raise R2ResumeError("RUNTIME_SEEN_DATES_DUPLICATE")
    if runtime["input_record_count"] != len(runtime["seen_dates"]):
        raise R2ResumeError("RUNTIME_INPUT_COUNT_MISMATCH")
    _require_sha(runtime["input_chain_sha256"], "input_chain_sha256")
    if not isinstance(runtime["finalized"], bool):
        raise R2ResumeError("RUNTIME_FINALIZED_FLAG_INVALID")
    if runtime["finalized"] and runtime["current"] is not None:
        raise R2ResumeError("FINALIZED_STATE_HAS_ACTIVE_FAMILY")
    if runtime["seen_dates"]:
        if runtime["prev_date"] != runtime["seen_dates"][-1]:
            raise R2ResumeError("RUNTIME_PREV_DATE_MISMATCH")
        session_set = set(sessions)
        if any(day not in session_set for day in runtime["seen_dates"]):
            raise R2ResumeError("RUNTIME_DATE_OUTSIDE_CALENDAR")
        calendar_index = {day: index for index, day in enumerate(sessions)}
        positions = [calendar_index[day] for day in runtime["seen_dates"]]
        if any(right <= left for left, right in zip(positions, positions[1:])):
            raise R2ResumeError("RUNTIME_SEEN_DATES_NOT_MONOTONIC")
    elif runtime["prev_date"] is not None:
        raise R2ResumeError("RUNTIME_EMPTY_SEEN_HAS_PREV_DATE")
    prior_dates = [row.get("trade_date") for row in runtime["prior"] if isinstance(row, dict)]
    if len(prior_dates) != len(runtime["prior"]):
        raise R2ResumeError("RUNTIME_PRIOR_ROW_INVALID")
    if any(day not in runtime["seen_dates"] for day in prior_dates):
        raise R2ResumeError("RUNTIME_PRIOR_DATE_NOT_SEEN")
    if prior_dates and prior_dates[-1] != runtime["prev_date"]:
        raise R2ResumeError("RUNTIME_PRIOR_LAST_DATE_MISMATCH")


def _check_anchor_against_provenance(receipt: dict[str, Any], grant: R2AnchorGrant,
                                     provenance: Any) -> None:
    expected = _provenance(receipt, grant)
    if provenance != expected:
        raise R2ResumeError("SNAPSHOT_ANCHOR_PROVENANCE_MISMATCH")


class R2Session:
    """Stateful view of the pinned R2 transition function.

    Use ``from_listing_inception`` or ``from_proven_reset`` for the first
    state, then persist ``snapshot()`` and resume with both an external
    checkpoint SHA pin and the original pinned anchor receipt/grant.
    """

    def __init__(self, runtime_state: dict[str, Any], provenance: dict[str, Any], *,
                 symbol: str, sessions: list[str], calendar_sha256: str,
                 source_identity: dict[str, Any], source_identity_sha256: str) -> None:
        self._runtime = deepcopy(runtime_state)
        self._provenance = deepcopy(provenance)
        self.symbol = symbol
        self.calendar = list(sessions)
        self.calendar_sha256 = calendar_sha256
        self.source_identity = deepcopy(source_identity)
        self.source_identity_sha256 = source_identity_sha256

    @classmethod
    def from_listing_inception(cls, *, symbol: str, calendar: Sequence[Any],
                               source_identity: Mapping[str, Any], receipt_bytes: bytes,
                               grant: R2AnchorGrant) -> "R2Session":
        sessions, calendar_hash = _calendar(calendar)
        identity, identity_hash = _identity(source_identity)
        if not isinstance(symbol, str) or not symbol.strip():
            raise R2ResumeError("SYMBOL_REQUIRED")
        receipt = _verify_grant_and_receipt(
            receipt_bytes, grant, expected_kind="LISTING_INCEPTION", symbol=symbol,
            calendar_sha256=calendar_hash, source_identity_sha256=identity_hash,
        )
        initial = _new_runtime_state(symbol, sessions, calendar_hash, identity, identity_hash)
        if receipt["boundary_date"] != sessions[0]:
            raise R2ResumeError("LISTING_BOUNDARY_NOT_FIRST_CALENDAR_SESSION")
        if receipt["boundary_state_sha256"] != _runtime_sha256(initial):
            raise R2ResumeError("LISTING_EMPTY_STATE_SHA_MISMATCH")
        return cls(initial, _provenance(receipt, grant), symbol=symbol, sessions=sessions,
                   calendar_sha256=calendar_hash, source_identity=identity,
                   source_identity_sha256=identity_hash)

    @classmethod
    def from_proven_reset(cls, *, snapshot_bytes: bytes, pinned_snapshot_sha256: str,
                          symbol: str, calendar: Sequence[Any],
                          source_identity: Mapping[str, Any], receipt_bytes: bytes,
                          grant: R2AnchorGrant) -> "R2Session":
        sessions, calendar_hash = _calendar(calendar)
        identity, identity_hash = _identity(source_identity)
        envelope = _strict_json_canonical_envelope(snapshot_bytes, pinned_snapshot_sha256)
        cls._check_envelope_identity(envelope, symbol, sessions, calendar_hash, identity_hash)
        runtime = _decode_runtime(envelope)
        _validate_runtime(runtime, symbol=symbol, sessions=sessions, calendar_sha256=calendar_hash,
                          source_identity=identity, source_identity_sha256=identity_hash)
        receipt = _verify_grant_and_receipt(
            receipt_bytes, grant, expected_kind="PROVEN_CLEAN_RESET", symbol=symbol,
            calendar_sha256=calendar_hash, source_identity_sha256=identity_hash,
        )
        if runtime["current"] is not None or runtime["prior"]:
            raise R2ResumeError("RESET_STATE_NOT_CLEARED")
        if runtime["prev_date"] is None or receipt["boundary_date"] != runtime["prev_date"]:
            raise R2ResumeError("RESET_BOUNDARY_DATE_MISMATCH")
        if receipt["boundary_state_sha256"] != envelope["runtime_state_sha256"]:
            raise R2ResumeError("RESET_STATE_SHA_MISMATCH")
        return cls(runtime, _provenance(receipt, grant), symbol=symbol, sessions=sessions,
                   calendar_sha256=calendar_hash, source_identity=identity,
                   source_identity_sha256=identity_hash)

    @classmethod
    def resume(cls, *, snapshot_bytes: bytes, pinned_snapshot_sha256: str,
               symbol: str, calendar: Sequence[Any], source_identity: Mapping[str, Any],
               receipt_bytes: bytes, grant: R2AnchorGrant) -> "R2Session":
        sessions, calendar_hash = _calendar(calendar)
        identity, identity_hash = _identity(source_identity)
        envelope = _strict_json_canonical_envelope(snapshot_bytes, pinned_snapshot_sha256)
        cls._check_envelope_identity(envelope, symbol, sessions, calendar_hash, identity_hash)
        receipt = _verify_grant_and_receipt(
            receipt_bytes, grant, expected_kind=envelope.get("provenance", {}).get("kind"),
            symbol=symbol, calendar_sha256=calendar_hash, source_identity_sha256=identity_hash,
        )
        _check_anchor_against_provenance(receipt, grant, envelope["provenance"])
        runtime = _decode_runtime(envelope)
        _validate_runtime(runtime, symbol=symbol, sessions=sessions, calendar_sha256=calendar_hash,
                          source_identity=identity, source_identity_sha256=identity_hash)
        if runtime["finalized"]:
            raise R2ResumeError("CANNOT_RESUME_FINALIZED_SNAPSHOT")
        return cls(runtime, _provenance(receipt, grant), symbol=symbol, sessions=sessions,
                   calendar_sha256=calendar_hash, source_identity=identity,
                   source_identity_sha256=identity_hash)

    @staticmethod
    def _check_envelope_identity(envelope: dict[str, Any], symbol: str, sessions: list[str],
                                 calendar_sha256: str, source_identity_sha256: str) -> None:
        if envelope["symbol"] != symbol:
            raise R2ResumeError("SNAPSHOT_SYMBOL_MISMATCH")
        if envelope["calendar_sha256"] != calendar_sha256:
            raise R2ResumeError("SNAPSHOT_CALENDAR_MISMATCH")
        if envelope["source_identity_sha256"] != source_identity_sha256:
            raise R2ResumeError("SNAPSHOT_SOURCE_IDENTITY_MISMATCH")
        runtime_wire = envelope["runtime_state"]
        runtime = _unwire(runtime_wire)
        if not isinstance(runtime, dict) or runtime.get("calendar_sessions") != sessions:
            raise R2ResumeError("SNAPSHOT_CALENDAR_CONTENT_MISMATCH")

    @property
    def finalized(self) -> bool:
        return bool(self._runtime["finalized"])

    @property
    def processed_rows(self) -> int:
        return int(self._runtime["input_record_count"])

    @property
    def last_trade_date(self) -> str | None:
        """Last processed exchange date, exposed for cutoff binding."""
        return self._runtime["prev_date"]

    @property
    def current_event(self) -> dict[str, Any] | None:
        return deepcopy(self._runtime["current"])

    @property
    def prior_warmup_rows(self) -> list[dict[str, Any]]:
        return deepcopy(self._runtime["prior"])

    def feed(self, rows: Sequence[Mapping[str, Any]], *,
             source_identity: Mapping[str, Any]) -> R2Delta:
        if self.finalized:
            raise R2ResumeError("FEED_AFTER_FINALIZE")
        identity, identity_hash = _identity(source_identity)
        if identity_hash != self.source_identity_sha256 or identity != self.source_identity:
            raise R2ResumeError("FEED_SOURCE_IDENTITY_CHANGED")
        if isinstance(rows, (str, bytes)) or not isinstance(rows, Sequence) or not rows:
            raise R2ResumeError("NONEMPTY_ROW_SEQUENCE_REQUIRED")
        normalized_rows = [dict(row) for row in rows]
        before = {name: len(self._runtime[name]) for name in ("observations", "candidates", "completed", "pullbacks")}
        input_sha = _sha256(_canonical_wire_bytes(normalized_rows))
        chain = self._runtime["input_chain_sha256"]
        for row in normalized_rows:
            row_sha = _sha256(_canonical_wire_bytes(row))
            chain = _sha256(bytes.fromhex(chain) + bytes.fromhex(row_sha))
        if self._runtime["input_record_count"] == 0 and self._provenance["kind"] == "LISTING_INCEPTION":
            first_date = str(normalized_rows[0].get("trade_date", ""))
            if first_date != self._provenance["boundary_date"]:
                raise R2ResumeError("FIRST_ROW_NOT_LISTING_INCEPTION_BOUNDARY")
        state_for_engine = {
            "prior": self._runtime["prior"],
            "completed": self._runtime["completed"],
            "observations": self._runtime["observations"],
            "candidates": self._runtime["candidates"],
            "pullbacks": self._runtime["pullbacks"],
            "current": self._runtime["current"],
            "prev_date": self._runtime["prev_date"],
            "seen_dates": self._runtime["seen_dates"],
        }
        try:
            observations, candidates, completed, pullbacks, engine_state = _RUN_R2(
                self.symbol, normalized_rows, self.calendar, _resume_state=state_for_engine, _finalize=False
            )
        except Exception:
            # The source runner receives copied locals. A failed chunk leaves the
            # live session/checkpoint unchanged and consumes no adapter rows.
            raise
        updated = deepcopy(self._runtime)
        updated.update(engine_state)
        updated["seen_dates"] = self._runtime["seen_dates"] + [str(row["trade_date"]) for row in normalized_rows]
        updated["input_record_count"] += len(normalized_rows)
        updated["input_chain_sha256"] = chain
        _validate_runtime(updated, symbol=self.symbol, sessions=self.calendar,
                          calendar_sha256=self.calendar_sha256, source_identity=self.source_identity,
                          source_identity_sha256=self.source_identity_sha256)
        self._runtime = updated
        return R2Delta(
            observations=deepcopy(observations[before["observations"]:]),
            candidates=deepcopy(candidates[before["candidates"]:]),
            completed=deepcopy(completed[before["completed"]:]),
            pullbacks=deepcopy(pullbacks[before["pullbacks"]:]),
            input_rows_sha256=input_sha,
            runtime_state_sha256=_runtime_sha256(self._runtime),
        )

    def finalize(self) -> R2Delta:
        """Apply the original end-of-run UNKNOWN_OPEN_AT_SNAPSHOT close once."""
        if self.finalized:
            raise R2ResumeError("ALREADY_FINALIZED")
        before = {name: len(self._runtime[name]) for name in ("observations", "candidates", "completed", "pullbacks")}
        state_for_engine = {
            "prior": self._runtime["prior"],
            "completed": self._runtime["completed"],
            "observations": self._runtime["observations"],
            "candidates": self._runtime["candidates"],
            "pullbacks": self._runtime["pullbacks"],
            "current": self._runtime["current"],
            "prev_date": self._runtime["prev_date"],
            "seen_dates": self._runtime["seen_dates"],
        }
        observations, candidates, completed, pullbacks, engine_state = _RUN_R2(
            self.symbol, [], self.calendar, _resume_state=state_for_engine, _finalize=True
        )
        updated = deepcopy(self._runtime)
        updated.update(engine_state)
        updated["seen_dates"] = self._runtime["seen_dates"]
        updated["finalized"] = True
        _validate_runtime(updated, symbol=self.symbol, sessions=self.calendar,
                          calendar_sha256=self.calendar_sha256, source_identity=self.source_identity,
                          source_identity_sha256=self.source_identity_sha256)
        self._runtime = updated
        return R2Delta(
            observations=deepcopy(observations[before["observations"]:]),
            candidates=deepcopy(candidates[before["candidates"]:]),
            completed=deepcopy(completed[before["completed"]:]),
            pullbacks=deepcopy(pullbacks[before["pullbacks"]:]),
            input_rows_sha256=_sha256(b""),
            runtime_state_sha256=_runtime_sha256(self._runtime),
        )

    def readout(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]],
                               list[dict[str, Any]], list[dict[str, Any]]]:
        """Return all four accumulated R2 output streams; does not finalize."""
        return tuple(deepcopy(self._runtime[name]) for name in
                     ("observations", "candidates", "completed", "pullbacks"))  # type: ignore[return-value]

    def snapshot(self) -> bytes:
        """Serialize all mutable R2 state without applying an EOF close."""
        envelope = {
            "schema": SNAPSHOT_SCHEMA,
            "adapter_version": ADAPTER_VERSION,
            "original_source_sha256": ORIGINAL_SOURCE_SHA256,
            "symbol": self.symbol,
            "calendar_sha256": self.calendar_sha256,
            "source_identity_sha256": self.source_identity_sha256,
            "runtime_state": _wire(self._runtime),
            "runtime_state_sha256": _runtime_sha256(self._runtime),
            "provenance": deepcopy(self._provenance),
        }
        return json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _run_original_for_equivalence(symbol: str, rows: Sequence[Mapping[str, Any]],
                                  calendar: Sequence[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]],
                                                                    list[dict[str, Any]], list[dict[str, Any]]]:
    """Run the unadapted pinned source once for synthetic equivalence tests only.

    This utility exists so the repository tests can compare all four outputs
    against the preserved source. Production callers should use ``R2Session``.
    """
    source_path = Path(__file__).resolve().parent / "evidence" / "event_rules.py"
    raw = source_path.read_bytes()
    actual = _sha256(raw)
    if actual != ORIGINAL_SOURCE_SHA256:
        raise R2ResumeError(f"PINNED_R2_SOURCE_SHA_MISMATCH:{actual}")
    namespace: dict[str, Any] = {"__file__": str(source_path), "__name__": "_p515_r2_equivalence_original"}
    exec(compile(raw.decode("utf-8"), str(source_path), "exec"), namespace)
    return tuple(namespace["run_symbol"](symbol, rows, calendar))  # type: ignore[return-value]
