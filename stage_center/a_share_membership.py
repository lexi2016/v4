"""A-stock family guard and positive, dated original-target inventory witness.

The inventory is not an exchange security master. Absence stays UNKNOWN and
never removes a stock-shaped candidate; suspension and missing daily bars do
not change membership. Original acquisition commits and raw inputs stay intact.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import hashlib
import base64
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping

from contracts.a_share_instruments import a_share_instrument_rejection
from .calendar import TradingDayState, resolve_market_states

SCHEMA = "stage_center.a_share_membership.v1"
SELECTOR_POINTER_ENV = "V4_STAGE_A_MEMBERSHIP_SELECTOR_POINTER"
SELECTOR_POINTER_NAME = "CURRENT_SELECTOR_READY_PANEL.txt"
PRELISTING_AUTHORITY_ENV = "V4_STAGE_A_PRELISTING_AUTHORITY"
_SHA = re.compile(r"[0-9a-f]{64}")


def _canonical_code(value):
    match = re.fullmatch(r"(?:(?:A|SH|SZ|BJ)\.)?(\d{6})(?:\.(?:SH|SZ|BJ))?", str(value or "").upper())
    return "A." + match[1] if match else str(value or "")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_file(path: Path, *, root: Path | None = None) -> Path:
    if not path.is_absolute() or path.resolve() != path or path.is_symlink() or not path.is_file():
        raise ValueError("UNSAFE_AUTHORITY_PATH")
    if root is not None:
        try:
            path.relative_to(root)
        except ValueError as error:
            raise ValueError("AUTHORITY_PATH_OUTSIDE_ROOT") from error
    return path


def _prelisting_authority(value: str, trade_date: str) -> tuple[dict, dict | None]:
    """Verify one dated issuer event without changing the stock-family policy."""
    reference = json.loads(value)
    if (not isinstance(reference, dict) or set(reference) != {"path", "sha256"}
            or not _SHA.fullmatch(str(reference.get("sha256") or ""))):
        raise ValueError("PRELISTING_AUTHORITY_REF_INVALID")
    path = _safe_file(Path(reference["path"]))
    if path.stat().st_size > 64 * 1024:
        raise ValueError("PRELISTING_AUTHORITY_TOO_LARGE")
    raw = path.read_bytes()
    if _sha256_bytes(raw) != reference["sha256"]:
        raise ValueError("PRELISTING_AUTHORITY_SHA_MISMATCH")
    event = json.loads(raw)
    fields = {"schema_version", "trade_date", "code", "previous_code", "code_status",
              "published_date", "subscription_date", "transition_date", "sources",
              "RESEARCH_ONLY", "production_allowed", "buy_gate_updated", "orders_sent"}
    if (not isinstance(event, dict) or set(event) != fields
            or event["schema_version"] != "stage_center.a_share_prelisting_authority.v1"
            or event["code_status"] != "PRE_LISTING"
            or event["RESEARCH_ONLY"] is not True
            or any(event[flag] is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))):
        raise ValueError("PRELISTING_AUTHORITY_EVENT_INVALID")
    for field in ("trade_date", "published_date", "subscription_date", "transition_date"):
        if not isinstance(event[field], str) or not re.fullmatch(r"\d{8}", event[field]):
            raise ValueError("PRELISTING_AUTHORITY_DATE_INVALID")
        datetime.strptime(event[field], "%Y%m%d")
    if not event["published_date"] <= event["trade_date"] < event["subscription_date"] < event["transition_date"]:
        raise ValueError("PRELISTING_AUTHORITY_EVENT_ORDER_INVALID")
    if (re.fullmatch(r"920\d{3}\.BJ", str(event["code"])) is None
            or re.fullmatch(r"(?:43|83|87)\d{4}\.BJ", str(event["previous_code"])) is None):
        raise ValueError("PRELISTING_AUTHORITY_CODE_INVALID")
    sources = event["sources"]
    if not isinstance(sources, dict) or set(sources) != {"CODE_TRANSITION_NOTICE", "OFFERING_INQUIRY_NOTICE"}:
        raise ValueError("PRELISTING_AUTHORITY_SOURCES_INVALID")
    for source in sources.values():
        if (not isinstance(source, dict) or set(source) != {"path", "sha256", "url"}
                or not _SHA.fullmatch(str(source.get("sha256") or ""))
                or not str(source.get("url") or "").startswith("https://")):
            raise ValueError("PRELISTING_AUTHORITY_SOURCE_REF_INVALID")
        document = _safe_file(Path(source["path"]), root=path.parent)
        if document.stat().st_size > 8 * 1024 * 1024 or _sha256_file(document) != source["sha256"]:
            raise ValueError("PRELISTING_AUTHORITY_SOURCE_SHA_MISMATCH")
    report = {"status": "VERIFIED" if event["trade_date"] == trade_date else "OUTSIDE_EXACT_DATE",
              "reference": reference, "event": event}
    if event["trade_date"] != trade_date:
        return report, None
    exclusion = {"code": _canonical_code(event["code"]),
                 "reason": "VERIFIED_PRE_LISTING_BEFORE_SUBSCRIPTION",
                 "classification": "VERIFIED_PRE_LISTING",
                 "authority_sha256": reference["sha256"]}
    return report, exclusion


def _previous_a_trade_date(trade_date: str) -> str:
    if not re.fullmatch(r"\d{8}", str(trade_date)):
        raise ValueError("MEMBERSHIP_TARGET_DATE_INVALID")
    try:
        current = datetime.strptime(trade_date, "%Y%m%d").date()
    except ValueError as error:
        raise ValueError("MEMBERSHIP_TARGET_DATE_INVALID") from error
    if resolve_market_states(trade_date)["a_share"] not in {
        TradingDayState.FULL_TRADING_DAY,
        TradingDayState.HALF_TRADING_DAY_AM,
    }:
        raise ValueError("MEMBERSHIP_TARGET_NOT_A_TRADING_DAY")
    for _ in range(15):
        current -= timedelta(days=1)
        signal_date = current.strftime("%Y%m%d")
        state = resolve_market_states(signal_date)["a_share"]
        if state is TradingDayState.UNKNOWN:
            raise ValueError("MEMBERSHIP_SIGNAL_CALENDAR_UNKNOWN")
        if state in {TradingDayState.FULL_TRADING_DAY, TradingDayState.HALF_TRADING_DAY_AM}:
            return signal_date
    raise ValueError("MEMBERSHIP_PREVIOUS_TRADING_DAY_NOT_FOUND")


def _candidate_identity(candidate: Any, trade_date: str) -> tuple[tuple[str, ...], str, str]:
    if getattr(candidate, "trade_date", None) != trade_date:
        raise ValueError("MEMBERSHIP_CANDIDATE_DATE_MISMATCH")
    root = Path(getattr(candidate, "root", ""))
    relative = str(getattr(candidate, "current_relative", ""))
    if not root.is_absolute() or root.resolve() != root or not relative:
        raise ValueError("MEMBERSHIP_CANDIDATE_CURRENT_REF_INVALID")
    relative_path = Path(relative)
    if relative_path.is_absolute() or "\\" in relative or any(part in {"", ".", ".."} for part in relative_path.parts):
        raise ValueError("MEMBERSHIP_CANDIDATE_CURRENT_REF_INVALID")
    current_path = root / relative_path
    if current_path.is_symlink() or current_path.resolve() != current_path or not current_path.is_file():
        raise ValueError("MEMBERSHIP_CANDIDATE_CURRENT_UNSAFE")
    current_bytes = current_path.read_bytes()
    current_sha = _sha256_bytes(current_bytes)
    candidate_sha = str(getattr(candidate, "current_sha256", ""))
    if not _SHA.fullmatch(candidate_sha) or current_sha != candidate_sha:
        raise ValueError("MEMBERSHIP_CANDIDATE_CURRENT_SHA_MISMATCH")
    current = json.loads(current_bytes)
    if not isinstance(current, dict):
        raise ValueError("MEMBERSHIP_CANDIDATE_CURRENT_INVALID")
    codes = tuple(getattr(candidate, "codes", ()))
    original_codes = tuple(getattr(candidate, "original_codes", ()) or codes)
    if not set(codes).issubset(original_codes):
        raise ValueError("MEMBERSHIP_CANDIDATE_ORIGINAL_CODES_MISMATCH")
    run_id = str(getattr(candidate, "run_id", ""))
    current_codes_sha = _sha256_bytes(json.dumps(list(original_codes), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    schema_role = (current.get("schema_version"), current.get("role"))
    if schema_role == ("v3_5.stage_acquisition_universe.current.v3", "A_SHARE_STAGE_ACQUISITION_UNIVERSE_V3"):
        artifact_binding = current.get("artifact_canonical_sha256")
        manifest_binding = current.get("manifest_canonical_sha256")
        receipt_binding = current.get("receipt_canonical_sha256")
    elif schema_role == ("v3_5.stage_acquisition_universe.current.v2", "A_SHARE_STAGE_ACQUISITION_UNIVERSE_V2"):
        artifact_binding = current.get("artifact_sha256")
        manifest_binding = current.get("manifest_sha256")
        receipt_binding = current.get("receipt_sha256")
    else:
        raise ValueError("MEMBERSHIP_CANDIDATE_CURRENT_SCHEMA_INVALID")
    if (
        current.get("trade_date") != trade_date
        or current.get("status") != "READY"
        or current.get("run_id") != run_id
        or artifact_binding != getattr(candidate, "artifact_sha256", None)
        or manifest_binding != getattr(candidate, "manifest_sha256", None)
        or receipt_binding != getattr(candidate, "receipt_sha256", None)
        or current.get("codes_sha256") != current_codes_sha
        or current.get("row_count") != len(original_codes)
        or (schema_role[0].endswith(".v2") and current.get("source_projection_sha256") != getattr(candidate, "source_projection_sha256", None))
        or any(current.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
    ):
        raise ValueError("MEMBERSHIP_CANDIDATE_CURRENT_BINDING_MISMATCH")
    return codes, candidate_sha, run_id


def _normalise_date(value: Any, label: str) -> str:
    text = str(value).replace("-", "")
    if not re.fullmatch(r"\d{8}", text):
        raise ValueError(label + "_INVALID")
    return text


def _selector_refs(pointer_path: Path, signal_date: str) -> dict[str, Any]:
    """Resolve one explicit current selector to its footered QFQ generation.

    The daily A receipt is deliberately not consulted here: this lane proves
    only positive original-target inventory membership, not receipt readiness,
    listing identity, or PIT safety.
    """
    pointer_path = _safe_file(pointer_path)
    if pointer_path.name != SELECTOR_POINTER_NAME:
        raise ValueError("MEMBERSHIP_SELECTOR_POINTER_NAME_INVALID")
    pointer_bytes = pointer_path.read_bytes()
    pointer_sha = _sha256_bytes(pointer_bytes)
    pointer_text = pointer_bytes.decode("utf-8")
    pointer_lines = pointer_text.splitlines()
    if len(pointer_lines) != 1 or not pointer_lines[0] or pointer_lines[0].strip() != pointer_lines[0]:
        raise ValueError("MEMBERSHIP_SELECTOR_POINTER_INVALID")
    selector_path = _safe_file(Path(pointer_lines[0]))
    with selector_path.open("rb") as stream:
        selector_prefix = stream.read(len(b"V4_LOGICAL_PANEL_V1\n"))
    selector_bytes = selector_path.read_bytes() if selector_prefix.startswith(b"V4_LOGICAL_PANEL_V1\n") else None
    selector_sha = _sha256_bytes(selector_bytes) if selector_bytes is not None else _sha256_file(selector_path)
    footer = _selector_footer(selector_path, selector_bytes)
    generation_id = str(footer.get("generation_id", ""))
    input_sha = str(footer.get("input_sha256", ""))
    footer_date = _normalise_date(footer.get("asof_date"), "MEMBERSHIP_SELECTOR_ASOF")
    if footer_date != signal_date:
        raise ValueError("MEMBERSHIP_SELECTOR_DATE_MISMATCH")
    if not _SHA.fullmatch(generation_id) or not _SHA.fullmatch(input_sha):
        raise ValueError("MEMBERSHIP_SELECTOR_GENERATION_IDENTITY_INVALID")
    receipt_path = _safe_file(Path(str(footer.get("generation_manifest_path", ""))))
    if receipt_path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("MEMBERSHIP_GENERATION_RECEIPT_TOO_LARGE")
    receipt_bytes = receipt_path.read_bytes()
    receipt_sha = _sha256_bytes(receipt_bytes)
    receipt = json.loads(receipt_bytes)
    if not isinstance(receipt, dict):
        raise ValueError("MEMBERSHIP_GENERATION_RECEIPT_INVALID")
    candidates = receipt.get("candidates")
    candidate_shas = receipt.get("candidate_sha256")
    if not isinstance(candidates, Mapping) or not isinstance(candidate_shas, Mapping):
        raise ValueError("MEMBERSHIP_GENERATION_RECEIPT_CANDIDATE_MAP_INVALID")
    if (
        receipt.get("schema") != "a_share_qfq_panel_v1"
        or receipt.get("status") != "CANDIDATE_READY"
        or receipt.get("generation_id") != generation_id
        or receipt.get("input_sha256") != input_sha
        or _normalise_date(receipt.get("asof_date"), "MEMBERSHIP_RECEIPT_ASOF") != signal_date
        or _normalise_date(receipt.get("target_date"), "MEMBERSHIP_RECEIPT_TARGET") != signal_date
        or receipt.get("generation_manifest_path") != str(receipt_path)
        or candidates.get("selector") != str(selector_path)
        or candidate_shas.get("selector") != selector_sha
        or receipt.get("snapshot_file_sha256") != footer.get("snapshot_file_sha256")
        or receipt.get("RESEARCH_ONLY") is not True
        or any(receipt.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
    ):
        raise ValueError("MEMBERSHIP_GENERATION_RECEIPT_MISMATCH")
    snapshot_ref = receipt.get("adjustment_snapshot")
    if not isinstance(snapshot_ref, Mapping) or snapshot_ref.get("sha256") != receipt.get("snapshot_file_sha256"):
        raise ValueError("MEMBERSHIP_SNAPSHOT_REF_MISMATCH")
    snapshot_path = _safe_file(Path(str(snapshot_ref.get("path", ""))))
    snapshot_sha = str(snapshot_ref.get("sha256", ""))
    if not _SHA.fullmatch(snapshot_sha):
        raise ValueError("MEMBERSHIP_SNAPSHOT_SHA_MISMATCH")
    snapshot_bytes = snapshot_path.read_bytes()
    if _sha256_bytes(snapshot_bytes) != snapshot_sha:
        raise ValueError("MEMBERSHIP_SNAPSHOT_SHA_MISMATCH")
    snapshot = json.loads(snapshot_bytes)
    del snapshot_bytes
    if not isinstance(snapshot, dict):
        raise ValueError("MEMBERSHIP_SNAPSHOT_INVALID")
    if (
        snapshot.get("schema") not in {"a_share_qfq_adjustment_input_v1", "a_share_qfq_adjustment_input_research_cache_v1"}
        or _normalise_date(snapshot.get("asof_date"), "MEMBERSHIP_SNAPSHOT_ASOF") != signal_date
        or _normalise_date(snapshot.get("coverage_end_date"), "MEMBERSHIP_SNAPSHOT_COVERAGE") != signal_date
        or any(snapshot.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
    ):
        raise ValueError("MEMBERSHIP_SNAPSHOT_MISMATCH")
    targets = snapshot.get("original_target_codes")
    if not isinstance(targets, list) or not targets or len(targets) != len(set(targets)):
        raise ValueError("MEMBERSHIP_ORIGINAL_TARGET_INVENTORY_MISSING")
    if any(not isinstance(code, str) or not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", code) for code in targets):
        raise ValueError("MEMBERSHIP_ORIGINAL_TARGET_INVENTORY_INVALID")
    retained = set(snapshot.get("symbols", {})) | set(snapshot.get("quarantine_symbols", {})) | set(snapshot.get("original_quarantine_eligible", {}))
    if not set(targets).issubset(retained):
        raise ValueError("MEMBERSHIP_ORIGINAL_TARGET_INVENTORY_INCOMPLETE")
    inventory_sha = _sha256_bytes(json.dumps(targets, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if _sha256_file(snapshot_path) != snapshot_sha:
        raise ValueError("MEMBERSHIP_SNAPSHOT_AUTHORITY_DRIFT")
    if (
        _sha256_bytes(pointer_path.read_bytes()) != pointer_sha
        or pointer_path.read_text(encoding="utf-8").splitlines() != pointer_lines
        or _sha256_file(selector_path) != selector_sha
        or _sha256_file(receipt_path) != receipt_sha
    ):
        raise ValueError("MEMBERSHIP_SELECTOR_AUTHORITY_DRIFT")
    return {
        "pointer_path": pointer_path,
        "pointer_sha256": pointer_sha,
        "selector_path": selector_path,
        "selector_sha256": selector_sha,
        "receipt_path": receipt_path,
        "receipt_sha256": receipt_sha,
        "receipt": receipt,
        "snapshot_path": snapshot_path,
        "snapshot_sha256": snapshot_sha,
        "inventory_codes": tuple(targets),
        "inventory_sha256": inventory_sha,
        "generation_id": generation_id,
        "input_sha256": input_sha,
    }


def _selector_footer(path: Path, raw: bytes | None = None) -> dict[str, Any]:
    import pyarrow as pa
    import pyarrow.parquet as pq

    # Some selectors are small logical-panel anchors; ordinary parquet files
    # are inspected from their footer without materializing the full panel.
    if raw is None:
        with path.open("rb") as stream:
            prefix = stream.read(len(b"V4_LOGICAL_PANEL_V1\n"))
    else:
        prefix = raw[:len(b"V4_LOGICAL_PANEL_V1\n")]
    if prefix.startswith(b"V4_LOGICAL_PANEL_V1\n"):
        raw = (raw or path.read_bytes()).split(b"\n", 1)[1]
        anchor = json.loads(raw)
        if not isinstance(anchor, dict) or anchor.get("schema_version") != "v4.original_panel.arrow_blocks.v1":
            raise ValueError("MEMBERSHIP_LOGICAL_PANEL_SCHEMA_INVALID")
        schema = pa.ipc.read_schema(pa.BufferReader(base64.b64decode(anchor["arrow_schema"])))
    else:
        schema = pq.read_schema(path)
    raw_footer = (schema.metadata or {}).get(b"a_share_qfq_contract_v1")
    if raw_footer is None:
        raise ValueError("MEMBERSHIP_SELECTOR_FOOTER_MISSING")
    value = json.loads(raw_footer)
    if not isinstance(value, dict):
        raise ValueError("MEMBERSHIP_SELECTOR_FOOTER_INVALID")
    return value


@dataclass(frozen=True)
class Membership:
    codes: tuple[str, ...]
    report: dict

    @property
    def evidence(self):
        return ("a_share_membership=" + json.dumps(self.report, sort_keys=True, separators=(",", ":")),)

    def bind(self, binding):
        if binding.market != "A_SHARE":
            return binding
        if not self.codes:
            return replace(binding, codes=(), status="CANNOT_CONFIRM", error="NO_A_STOCK_FAMILY_CANDIDATES", evidence=(*binding.evidence, *self.evidence))
        return replace(binding, codes=self.codes, evidence=(*binding.evidence, *self.evidence))

    def source(self, source, market="A_SHARE"):
        if market != "A_SHARE":
            return source
        allowed = set(self.codes)
        rows = tuple(row for row in source.rows if _canonical_code(row.get("code") or row.get("symbol")) in allowed)
        missing = tuple(code for code in source.missing_symbols if _canonical_code(code) in allowed)
        reasons = list(source.cannot_confirm)
        if self.report["status"] != "BOUND_POSITIVE_INVENTORY":
            reasons.append("A_MEMBERSHIP_AUTHORITY_UNKNOWN")
        if self.report["unknown_codes"]:
            reasons.append("A_MEMBERSHIP_IDENTITIES_UNKNOWN:" + ",".join(self.report["unknown_codes"]))
        # A provider returning an unknown security is still an observation,
        # never affirmative identity proof or a reason to erase UNKNOWN.
        status = source.status
        if reasons and status == "READY":
            status = "PARTIAL_WITH_ROWS" if rows else "CANNOT_CONFIRM"
        return replace(source, rows=rows, requested_rows=len(self.codes), missing_symbols=missing,
                       status=status, cannot_confirm=tuple(dict.fromkeys(reasons)),
                       source_evidence=(*source.source_evidence, *self.evidence))

    def builder_raw(self, raw, source):
        return {**raw, "requested_rows":source.requested_rows, "missing_symbols":list(source.missing_symbols),
                "cannot_confirm":list(dict.fromkeys((*raw.get("cannot_confirm", ()), *source.cannot_confirm))),
                "source_evidence":list(dict.fromkeys((*raw.get("source_evidence", ()), *self.evidence)))}


def resolve_membership(candidate, trade_date, *, selector_pointer_path=None, environ=None):
    """Bind a verified same-day candidate to exact D-1 QFQ inventory evidence.

    The configured pointer is read once and must name the exact selector whose
    footer links its generation receipt. No static date config, daily A receipt,
    inferred sibling path, latest-date discovery, or nearby-date fallback is
    consulted. This proves positive inventory membership only, not PIT safety.
    """
    codes = tuple(getattr(candidate, "codes", ()))
    # Family exclusion is independent of dated inventory availability. A stale
    # witness must never re-admit a known ETF; unknown stock identities remain.
    quarantine = [{"code":code,"reason":reason,"classification":"KNOWN_NON_STOCK_FAMILY"}
                  for code in codes if (reason := a_share_instrument_rejection(code))]
    excluded = {row["code"] for row in quarantine}
    effective = tuple(code for code in codes if code not in excluded)
    report = dict(schema=SCHEMA, trade_date=trade_date, status="UNKNOWN", original_requested_rows=len(codes),
                  effective_requested_rows=len(effective), quarantined=quarantine, unknown_codes=[],
                  inventory_semantics="POSITIVE_ORIGINAL_TARGET_INVENTORY_NOT_SECURITY_MASTER",
                  inventory_is_listing_or_pit_proof=False)
    try:
        if not codes or len(codes) != len(set(codes)) or any(not isinstance(code, str) for code in codes):
            raise ValueError("MEMBERSHIP_CANDIDATE_CODES_INVALID")
        codes, candidate_sha, candidate_run_id = _candidate_identity(candidate, trade_date)
        env = os.environ if environ is None else environ
        prelisting_ref = env.get(PRELISTING_AUTHORITY_ENV)
        if prelisting_ref:
            try:
                authority, exclusion = _prelisting_authority(prelisting_ref, trade_date)
            except (OSError, TypeError, ValueError) as error:
                report["prelisting_authority"] = {"status": "CANNOT_CONFIRM", "reason": str(error)}
            else:
                report["prelisting_authority"] = authority
                if exclusion and exclusion["code"] in {_canonical_code(code) for code in effective}:
                    affected = tuple(code for code in effective if _canonical_code(code) == exclusion["code"])
                    quarantine.extend({**exclusion, "code": code} for code in affected)
                    effective = tuple(code for code in effective if code not in affected)
                    report["effective_requested_rows"] = len(effective)
        signal = _previous_a_trade_date(trade_date)
        pointer_value = selector_pointer_path or env.get(SELECTOR_POINTER_ENV)
        if not pointer_value:
            raise ValueError("MEMBERSHIP_SELECTOR_POINTER_REQUIRED")
        refs = _selector_refs(Path(pointer_value), signal)
        final_codes, final_sha, final_run_id = _candidate_identity(candidate, trade_date)
        if (final_codes, final_sha, final_run_id) != (codes, candidate_sha, candidate_run_id):
            raise ValueError("MEMBERSHIP_CANDIDATE_CURRENT_DRIFT")
        receipt = refs["receipt"]
        targets = refs["inventory_codes"]
        known = {_canonical_code(code) for code in targets}
        report.update(status="BOUND_POSITIVE_INVENTORY", effective_requested_rows=len(effective),
                      quarantined=quarantine, unknown_codes=[code for code in effective if _canonical_code(code) not in known],
                      inventory_rows=len(targets), inventory_sha256=refs["inventory_sha256"], signal_date=signal,
                      candidate_run_id=candidate_run_id, candidate_current_relative=candidate.current_relative,
                      candidate_current_sha256=candidate_sha,
                      selector_pointer={"path":str(refs["pointer_path"]),"sha256":refs["pointer_sha256"]},
                      receipt_path=str(refs["receipt_path"]), receipt_sha256=refs["receipt_sha256"],
                      receipt_status=receipt.get("status"), qfq_pit_certified=receipt.get("pit_certified"),
                      generation_id=refs["generation_id"], input_sha256=refs["input_sha256"],
                      snapshot={"path":str(refs["snapshot_path"]),"sha256":refs["snapshot_sha256"]},
                      selector={"path":str(refs["selector_path"]),"sha256":refs["selector_sha256"]},
                      outer_a_receipt="NOT_READ", membership_semantics="POSITIVE_INVENTORY_ONLY")
        return Membership(effective, report)
    except Exception as error:
        report["reason"] = type(error).__name__ + ":" + str(error)
        report["unknown_identity_count"] = len(effective)
        return Membership(effective, report)
