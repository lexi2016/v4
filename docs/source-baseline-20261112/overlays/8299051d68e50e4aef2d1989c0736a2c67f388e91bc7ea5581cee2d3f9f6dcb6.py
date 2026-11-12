"""A-stock family guard and positive, dated original-target inventory witness.

The inventory is not an exchange security master. Absence stays UNKNOWN and
never removes a stock-shaped candidate; suspension and missing daily bars do
not change membership. Original acquisition commits and raw inputs stay intact.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import base64
import json
import os
from pathlib import Path
import re

from contracts.a_share_instruments import a_share_instrument_rejection

CONFIG_ENV = "V4_STAGE_A_MEMBERSHIP_CONFIG"
CONFIG_SHA_ENV = "V4_STAGE_A_MEMBERSHIP_CONFIG_SHA256"
SCHEMA = "stage_center.a_share_membership.v1"
_SHA = re.compile(r"[0-9a-f]{64}")


def _canonical_code(value):
    match = re.fullmatch(r"(?:(?:A|SH|SZ|BJ)\.)?(\d{6})(?:\.(?:SH|SZ|BJ))?", str(value or "").upper())
    return "A." + match[1] if match else str(value or "")


def _checked_bytes(ref):
    path = Path(ref["path"])
    if not path.is_absolute() or path.resolve() != path or path.is_symlink():
        raise ValueError("UNSAFE_AUTHORITY_PATH")
    raw = path.read_bytes()
    if not _SHA.fullmatch(str(ref.get("sha256", ""))) or hashlib.sha256(raw).hexdigest() != ref["sha256"]:
        raise ValueError("AUTHORITY_SHA_MISMATCH")
    return raw


def _read_ref(ref):
    return json.loads(_checked_bytes(ref))


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


def resolve_membership(codes, trade_date, *, candidate_sha256, environ=None):
    """Verify one explicit dated authority; never discover a mutable latest."""
    codes = tuple(codes)
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
    env = os.environ if environ is None else environ
    try:
        path, sha = env.get(CONFIG_ENV), env.get(CONFIG_SHA_ENV)
        if not path or not sha:
            raise ValueError("MEMBERSHIP_CONFIG_AND_SHA_REQUIRED_TOGETHER")
        config = _read_ref(dict(path=path, sha256=sha))
        if (config.get("schema") != SCHEMA + ".config" or config.get("trade_date") != trade_date
                or config.get("candidate_current_sha256") != candidate_sha256):
            raise ValueError("MEMBERSHIP_DATE_OR_CANDIDATE_MISMATCH")
        signal = config["signal_date"]
        if not re.fullmatch(r"\d{8}", signal) or signal >= trade_date:
            raise ValueError("MEMBERSHIP_SIGNAL_DATE_INVALID")
        if not _SHA.fullmatch(str(config.get("generation_id", ""))):
            raise ValueError("MEMBERSHIP_GENERATION_ID_INVALID")
        manifest = _read_ref(config["generation_manifest"])
        if (manifest.get("generation_id") != config["generation_id"]
                or str(manifest.get("asof_date")) != signal
                or str(manifest.get("target_date")) != signal
                or manifest.get("status") != "CANDIDATE_READY"
                or any(manifest.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))):
            raise ValueError("MEMBERSHIP_GENERATION_MISMATCH")
        panel_ref = config["selector"]
        panel_raw = _checked_bytes(panel_ref)
        if (manifest["candidates"]["selector"] != panel_ref["path"]
                or manifest["candidate_sha256"]["selector"] != panel_ref["sha256"]):
            raise ValueError("MEMBERSHIP_SELECTOR_BINDING_MISMATCH")
        # Read metadata only. The Stage role need not import Main's logical
        # block reader, nor scan successfully traded rows to infer membership.
        import pyarrow as pa
        import pyarrow.parquet as pq
        if panel_raw.startswith(b"V4_LOGICAL_PANEL_V1\n"):
            anchor = json.loads(panel_raw.split(b"\n", 1)[1])
            if anchor.get("schema_version") != "v4.original_panel.arrow_blocks.v1":
                raise ValueError("MEMBERSHIP_LOGICAL_PANEL_SCHEMA_INVALID")
            schema = pa.ipc.read_schema(pa.BufferReader(base64.b64decode(anchor["arrow_schema"])))
        else:
            schema = pq.read_schema(pa.BufferReader(panel_raw))
        footer = json.loads(schema.metadata[b"a_share_qfq_contract_v1"])
        if (footer.get("generation_id") != config["generation_id"]
                or str(footer.get("asof_date")) != signal
                or footer.get("generation_manifest_path") != config["generation_manifest"]["path"]
                or footer.get("snapshot_file_sha256") != manifest.get("snapshot_file_sha256")):
            raise ValueError("MEMBERSHIP_SELECTOR_FOOTER_MISMATCH")
        snapshot_ref = manifest["adjustment_snapshot"]
        snapshot = _read_ref(snapshot_ref)
        if (snapshot.get("schema") not in {"a_share_qfq_adjustment_input_v1", "a_share_qfq_adjustment_input_research_cache_v1"}
                or snapshot_ref["sha256"] != manifest.get("snapshot_file_sha256")
                or str(snapshot.get("asof_date")) != signal
                or str(snapshot.get("coverage_end_date")) != signal):
            raise ValueError("MEMBERSHIP_SNAPSHOT_MISMATCH")
        # Require the original full target inventory. Never substitute symbols
        # with successfully adjusted bars, a daily bar slice or a selected pool.
        targets = snapshot.get("original_target_codes")
        if not isinstance(targets, list) or not targets or len(targets) != len(set(targets)):
            raise ValueError("MEMBERSHIP_ORIGINAL_TARGET_INVENTORY_MISSING")
        if any(not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", x) for x in targets):
            raise ValueError("MEMBERSHIP_ORIGINAL_TARGET_INVENTORY_INVALID")
        retained = set(snapshot.get("symbols", {})) | set(snapshot.get("quarantine_symbols", {})) | set(snapshot.get("original_quarantine_eligible", {}))
        if not set(targets).issubset(retained):
            raise ValueError("MEMBERSHIP_ORIGINAL_TARGET_INVENTORY_INCOMPLETE")
        known = {_canonical_code(code) for code in targets}
        report.update(status="BOUND_POSITIVE_INVENTORY", effective_requested_rows=len(effective),
                      quarantined=quarantine, unknown_codes=[code for code in effective if _canonical_code(code) not in known],
                      inventory_rows=len(targets), signal_date=signal, generation_id=config["generation_id"],
                      config_path=path, config_sha256=sha, generation_manifest=config["generation_manifest"],
                      snapshot=snapshot_ref, selector=panel_ref)
        return Membership(effective, report)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as error:
        report["reason"] = type(error).__name__ + ":" + str(error)
        report["unknown_identity_count"] = len(effective)
        return Membership(effective, report)
