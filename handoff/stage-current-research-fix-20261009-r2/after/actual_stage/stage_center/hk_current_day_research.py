"""Read the explicitly authorized current-day HK security snapshot.

This adapter publishes no pool and writes no input.  Its only authority is the
user's 2026-10-09 acquisition declaration plus four byte SHA256 pins.  The
snapshot contains security metadata, not quotes or confirmed Connect membership.
The existing Stage collector and the unchanged selector still own those steps.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping
from zoneinfo import ZoneInfo

ROLE = "CURRENT_DAY_RESEARCH_ONLY"
EVIDENCE_PREFIX = "hk_current_day_research="
ROOT_PREFIX = "hk_current_day_research_root="
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_MAX_INPUT_BYTES = 16 * 1024 * 1024
_SECURITY_FIELDS = (
    "code", "name", "outstanding_shares", "circular_market_val", "listing_date",
    "lot_size", "stock_owner", "stock_child_type", "sec_status",
)
CAPTURE_20261009 = {
    "schema_version": "stage_center.hk_current_day_research.input.v1",
    "trade_date": "20261009",
    "universe_as_of": "20261008",
    "captured_at": "2026-10-09T15:38:41+08:00",
    "expected_rows": 695,
    "declaration_source": "USER_REPORTED_MAC_ACQUISITION_20261009",
    "source_files": {
        "snapshot": {"file": "snapshot_rows_projected.json", "sha256": "9c2396530e3de8059d49354a2c330a06829a060bfbac68ff2fb726111d9e0c30"},
        "receipt": {"file": "receipt.json", "sha256": "f8735ae71437a85067d7bca06b55f451bdd5dbfa7802cf2f680dfcab5f31a3ea"},
        "reference_codes": {"file": "reference_codes_20261008.json", "sha256": "9b837e801a1fae55893f3aba3548402ac59b4d1027627f6d698a10934027fb95"},
        "final_receipt": {"file": "FINAL_RECEIPT.json", "sha256": "3242a8ffbc4364ff96ef18a2855037521902617fa21a8c024e6f57445dbcf3f3"},
    },
}


class CurrentDayResearchError(ValueError):
    """The explicitly configured research input is unusable for this slot."""


def _fail(reason: str) -> None:
    raise CurrentDayResearchError("HK_CURRENT_DAY_RESEARCH_" + reason)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(metadata: Mapping[str, Any], codes: tuple[str, ...]) -> str:
    return hashlib.sha256(_canonical({"metadata": dict(metadata), "codes": list(codes)}).encode()).hexdigest()


def _safe_root(root: Path | str) -> Path:
    value = Path(root).expanduser().absolute()
    if any(part.is_symlink() for part in (value, *value.parents)):
        _fail("INPUT_SYMLINK_FORBIDDEN")
    if not value.is_dir():
        _fail("ROOT_MISSING")
    return value.resolve()


def _verified_json(root: Path, spec: Mapping[str, Any], label: str) -> Any:
    name, expected = spec.get("file"), spec.get("sha256")
    if (not isinstance(name, str) or Path(name).name != name or name in {"", ".", ".."}
            or not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected)):
        _fail(f"INPUT_DESCRIPTOR_INVALID:{label}")
    path = root / name
    if path.is_symlink():
        _fail(f"INPUT_SYMLINK_FORBIDDEN:{label}")
    try:
        with path.open("rb") as stream:
            raw = stream.read(_MAX_INPUT_BYTES + 1)
    except OSError as error:
        raise CurrentDayResearchError(f"HK_CURRENT_DAY_RESEARCH_INPUT_MISSING:{label}") from error
    if len(raw) > _MAX_INPUT_BYTES:
        _fail(f"INPUT_TOO_LARGE:{label}")
    if hashlib.sha256(raw).hexdigest() != expected:
        _fail(f"INPUT_SHA_MISMATCH:{label}")
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, ValueError) as error:
        raise CurrentDayResearchError(f"HK_CURRENT_DAY_RESEARCH_INPUT_JSON_INVALID:{label}") from error


def _code(value: Any) -> str:
    # This is a security-code format check, never a membership determination.
    if not isinstance(value, str) or not re.fullmatch(r"HK\.\d{5}", value):
        _fail("MEMBERSHIP_CODE_INVALID")
    return value


def _slot_cutoff(trade_date: str, stage_id: str) -> tuple[str, datetime]:
    from .contracts import EIGHT_STAGES
    stage = next((stage for stage in EIGHT_STAGES if stage.stage_id == stage_id), None)
    if stage is None or stage_id == "STAGE_0925":
        # The pinned afternoon snapshot can never replace a 09:20 auction.
        _fail("CAPTURE_AFTER_STAGE_CUTOFF")
    try:
        cutoff = datetime.strptime(trade_date + " " + stage.cutoff, "%Y%m%d %H:%M:%S").replace(tzinfo=_SHANGHAI)
    except ValueError as error:
        raise CurrentDayResearchError("HK_CURRENT_DAY_RESEARCH_CAPTURE_DATE_MISMATCH") from error
    return stage.cutoff, cutoff


def read_research_input(root: Path | str, trade_date: str, stage_id: str, *,
                        declaration: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Verify all four files and the slot boundary without writing any bytes.

    ``declaration`` is a narrow value seam for synthetic file-integrity tests.
    Production configuration exposes only the root and uses the fixed authorized
    declaration. Neither a root-supplied manifest nor today's date can replace
    these pins implicitly.
    """
    declared = dict(CAPTURE_20261009 if declaration is None else declaration)
    try:
        captured = datetime.fromisoformat(str(declared.get("captured_at", "")))
    except ValueError as error:
        raise CurrentDayResearchError("HK_CURRENT_DAY_RESEARCH_CAPTURE_DATE_MISMATCH") from error
    if (declared.get("trade_date") != trade_date or captured.tzinfo is None
            or captured.astimezone(_SHANGHAI).strftime("%Y%m%d") != trade_date):
        _fail("CAPTURE_DATE_MISMATCH")
    cutoff_at, cutoff = _slot_cutoff(trade_date, stage_id)
    if captured > cutoff:
        _fail("CAPTURE_AFTER_STAGE_CUTOFF")
    as_of = declared.get("universe_as_of")
    expected_rows = declared.get("expected_rows")
    if (not isinstance(as_of, str) or not re.fullmatch(r"\d{8}", as_of) or as_of > trade_date
            or type(expected_rows) is not int or expected_rows <= 0):
        _fail("MEMBERSHIP_DESCRIPTOR_INVALID")
    files = declared.get("source_files")
    if not isinstance(files, Mapping) or set(files) != {"snapshot", "receipt", "reference_codes", "final_receipt"}:
        _fail("INPUT_DESCRIPTOR_INVALID")
    resolved = _safe_root(root)
    inputs = {key: _verified_json(resolved, spec, key) for key, spec in files.items()}
    rows, references = inputs["snapshot"], inputs["reference_codes"]
    # The code-list file may be the original bare JSON array or its explicitly
    # named 'codes' envelope. No alternate time or eligibility field is inferred.
    if isinstance(references, Mapping):
        references = references.get("codes")
    if (not isinstance(rows, list) or len(rows) != expected_rows
            or not isinstance(references, list) or len(references) != expected_rows
            or not all(isinstance(row, Mapping) for row in rows)):
        _fail("MEMBERSHIP_ROW_COUNT_MISMATCH")
    codes = tuple(_code(code) for code in references)
    observed = tuple(_code(row.get("code")) for row in rows)
    if len(set(codes)) != expected_rows or len(set(observed)) != expected_rows or set(codes) != set(observed):
        _fail("MEMBERSHIP_CODE_SET_MISMATCH")
    if not isinstance(inputs["receipt"], Mapping) or not isinstance(inputs["final_receipt"], Mapping):
        _fail("RECEIPT_SHAPE_INVALID")
    metadata = {
        "schema_version": "stage_center.hk_current_day_research.binding.v1",
        "input_mode": ROLE,
        "trade_date": trade_date,
        "stage_id": stage_id,
        "cutoff_at": cutoff_at,
        "universe_as_of": as_of,
        "captured_at": captured.isoformat(),
        "stale_universe": as_of != trade_date,
        "current_connect_eligibility": "CANNOT_CONFIRM",
        "declaration_source": declared.get("declaration_source"),
        "receipt_semantics": "SHA_VERIFIED_USER_DECLARED_CAPTURE",
        "security_snapshot_is_quote": False,
        "source_rows": expected_rows,
        "source_files": {key: dict(spec) for key, spec in files.items()},
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    sha = _digest(metadata, codes)
    metadata["input_binding_sha256"] = sha
    evidence = (f"{ROOT_PREFIX}{resolved}", EVIDENCE_PREFIX + _canonical(metadata),
                f"hk_current_day_research_binding_sha256={sha}",
                "hk_acquisition_scope=CURRENT_DAY_RESEARCH_REFERENCE_CODES",
                "hk_connect_eligibility=CANNOT_CONFIRM", "RESEARCH_ONLY=true")
    return {"metadata": metadata, "sha256": sha, "codes": codes,
            "rows": tuple({key: row[key] for key in _SECURITY_FIELDS if key in row} for row in rows),
            "evidence": evidence}


def build_research_binding(root: Path | str, trade_date: str, stage_id: str):
    from .acquisition import StageUniverseBinding
    value = read_research_input(root, trade_date, stage_id)
    return StageUniverseBinding.ready(market="HK_CONNECT", trade_date=trade_date, role=ROLE,
        codes=value["codes"], source_run_id="hk-current-research-" + value["sha256"][:16],
        sha256=value["sha256"], evidence=value["evidence"])


def is_current_day_research(binding: Any) -> bool:
    return binding is not None and getattr(binding, "role", None) == ROLE


def research_metadata(binding: Any) -> dict[str, Any]:
    if not is_current_day_research(binding):
        _fail("BINDING_ROLE_INVALID")
    values = [item[len(EVIDENCE_PREFIX):] for item in binding.evidence if isinstance(item, str) and item.startswith(EVIDENCE_PREFIX)]
    if len(values) != 1:
        _fail("BINDING_METADATA_INVALID")
    try:
        metadata = json.loads(values[0])
    except ValueError as error:
        raise CurrentDayResearchError("HK_CURRENT_DAY_RESEARCH_BINDING_METADATA_INVALID") from error
    if not isinstance(metadata, dict):
        _fail("BINDING_METADATA_INVALID")
    identity = dict(metadata)
    sha = identity.pop("input_binding_sha256", None)
    if (binding.status != "READY" or binding.market != "HK_CONNECT" or binding.trade_date != metadata.get("trade_date")
            or metadata.get("input_mode") != ROLE or metadata.get("current_connect_eligibility") != "CANNOT_CONFIRM"
            or metadata.get("RESEARCH_ONLY") is not True
            or any(metadata.get(key) is not False for key in ("production_allowed", "buy_gate_updated", "orders_sent"))
            or sha != binding.sha256 or sha != _digest(identity, tuple(binding.codes))):
        _fail("BINDING_IDENTITY_INVALID")
    cutoff_at, cutoff = _slot_cutoff(metadata["trade_date"], str(metadata.get("stage_id")))
    try:
        captured = datetime.fromisoformat(str(metadata.get("captured_at", "")))
    except ValueError as error:
        raise CurrentDayResearchError("HK_CURRENT_DAY_RESEARCH_BINDING_CAPTURE_INVALID") from error
    if (captured.tzinfo is None or captured.astimezone(_SHANGHAI).strftime("%Y%m%d") != binding.trade_date
            or captured > cutoff or cutoff_at != metadata.get("cutoff_at")):
        _fail("BINDING_CUTOFF_INVALID")
    if (binding.source_run_id != "hk-current-research-" + binding.sha256[:16]
            or metadata.get("source_rows") != len(binding.codes)
            or len(set(binding.codes)) != len(binding.codes)
            or metadata.get("stale_universe") is not (metadata.get("universe_as_of") != binding.trade_date)):
        _fail("BINDING_IDENTITY_INVALID")
    return metadata


def candidate_from_research_binding(root: Path | str, trade_date: str, binding: Any):
    """Compatibility plan carrier; no fabricated current pointer or D1 trio."""
    from .candidate_input import CandidateInput
    metadata = research_metadata(binding)
    files = metadata["source_files"]
    return CandidateInput(root=Path(root), trade_date=trade_date,
        current_relative="", current_sha256=binding.sha256, run_id=binding.source_run_id,
        codes=tuple(binding.codes), artifact_sha256=files["snapshot"]["sha256"],
        manifest_sha256="", receipt_sha256=files["receipt"]["sha256"],
        source_projection_sha256=files["snapshot"]["sha256"],
        source_evidence=tuple(binding.evidence), strict_schema=ROLE,
        digest_mode="CURRENT_DAY_RESEARCH_DECLARATION_AND_RAW_FILE_SHA256")


def attach_security_metadata(source: Any, binding: Any):
    """Merge only declared security metadata while preserving actual quote fields."""
    metadata = research_metadata(binding)
    roots = [item[len(ROOT_PREFIX):] for item in binding.evidence if isinstance(item, str) and item.startswith(ROOT_PREFIX)]
    if len(roots) != 1:
        _fail("BINDING_ROOT_INVALID")
    snapshot = _verified_json(_safe_root(roots[0]), metadata["source_files"]["snapshot"], "snapshot")
    securities = {row["code"]: row for row in snapshot}
    merged_rows = []
    for row in source.rows:
        code = _code(row.get("code"))
        if code not in set(binding.codes) or code not in securities:
            _fail("MEMBERSHIP_QUOTE_OUTSIDE_BINDING")
        merged = dict(row)
        for key in _SECURITY_FIELDS:
            value = securities[code].get(key)
            if value is not None and key != "code":
                merged[key] = value
        merged["_hk_current_day_research"] = dict(metadata)
        merged_rows.append(merged)
    return replace(source, rows=tuple(merged_rows), status="PARTIAL_WITH_ROWS" if merged_rows else "CANNOT_CONFIRM",
        cannot_confirm=tuple(dict.fromkeys((*source.cannot_confirm, ROLE, "HK_CONNECT_ELIGIBILITY_CANNOT_CONFIRM",
                                          *(("STALE_UNIVERSE",) if metadata["stale_universe"] else ())))),
        source_evidence=tuple(dict.fromkeys((*source.source_evidence, *binding.evidence))))
