"""Refresh or exactly recover one research-only preselection pool."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from domains.preselection_materializer import build_hourly_research_pool
from infrastructure.data_store import _canonical_bytes, _date, _sha256
from infrastructure.preselection_pool_store import PreselectionPoolStore, validate_pool_artifact
from infrastructure.research_store import HourlyResearchStore
from v4_migration.write_authority_reference import (
    WriteAuthorityResolutionError,
    reject_cli_authority_declaration,
)


_RESEARCH_POOL_ID = "a_share_research_recommendation_pool"
_EXACT_SOURCE = re.compile(r"research/hourly/live/(?P<date>\d{8})/(?P<slot>\d{4})\.json")


class _ExactHistoricalHourlyStore:
    """Expose only the historical slot identities declared by a reviewed pool."""

    def __init__(self, delegate: HourlyResearchStore, allowed: Mapping[str, set[str]]) -> None:
        self._delegate = delegate
        self._allowed = {date: set(slots) for date, slots in allowed.items()}

    def list_slots(self, archive_date: str, *, mode: str) -> list[str]:
        if str(mode).upper() != "LIVE":
            raise ValueError("historical research recovery only accepts LIVE source slots")
        slots = sorted(self._allowed.get(archive_date, set()))
        if not slots:
            return []
        available = set(self._delegate.list_slots(archive_date, mode="LIVE"))
        missing = [slot for slot in slots if slot not in available]
        if missing:
            relative = f"research/hourly/live/{archive_date}/{missing[0]}.json"
            raise FileNotFoundError(f"exact historical research source slot missing: {relative}")
        return slots

    def read_exact(self, archive_date: str, slot: str, *, mode: str):
        if slot not in self._allowed.get(archive_date, set()):
            raise ValueError("historical research recovery attempted an undeclared source slot")
        return self._delegate.read_exact(archive_date, slot, mode=mode)


def _read_canonical_object(path: Path, *, label: str) -> dict[str, Any]:
    raw = Path(path).read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain an object")
    if raw != _canonical_bytes(value):
        raise ValueError(f"{label} bytes are not canonical")
    return value


def _exact_source_slots(artifact: Mapping[str, Any]) -> dict[str, set[str]]:
    paths = [part.strip() for part in str(artifact.get("source_path") or "").split("|") if part.strip()]
    if not paths:
        raise ValueError("historical research recovery source paths are missing")
    allowed: dict[str, set[str]] = {}
    seen: set[str] = set()
    for path in paths:
        match = _EXACT_SOURCE.fullmatch(path)
        if match is None or path in seen:
            raise ValueError("historical research recovery source path is invalid")
        seen.add(path)
        allowed.setdefault(match.group("date"), set()).add(match.group("slot"))
    return allowed


def _validate_recovery_trio(
    *,
    trade_date: str,
    artifact_path: Path,
    manifest_path: Path,
    receipt_path: Path,
    expected_recovery_sha256: str,
) -> tuple[dict[str, Any], str, dict[str, set[str]]]:
    trade_date = _date(trade_date)
    artifact = _read_canonical_object(artifact_path, label="recovery artifact")
    manifest = _read_canonical_object(manifest_path, label="recovery manifest")
    receipt = _read_canonical_object(receipt_path, label="recovery receipt")
    if validate_pool_artifact(artifact) != trade_date or artifact.get("pool_id") != _RESEARCH_POOL_ID:
        raise ValueError("historical research recovery artifact identity mismatch")
    if (
        artifact.get("source_role") != "VERIFIED_HOURLY_RESEARCH"
        or artifact.get("producer_id") != "v3_5_hourly_research_window_v1"
        or artifact.get("status") != "RESEARCH_RECOMMENDATION_POOL_READY"
        or not artifact.get("rows")
    ):
        raise ValueError("historical research recovery artifact is not a verified ready pool")
    digest = _sha256(artifact)
    expected = str(expected_recovery_sha256 or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected) or digest != expected:
        raise ValueError("historical research recovery approved artifact SHA mismatch")
    if manifest.get(_RESEARCH_POOL_ID) != digest:
        raise ValueError("recovery manifest does not bind the approved artifact")
    expected_receipt = PreselectionPoolStore._receipt(
        trade_date=trade_date,
        pool_id=_RESEARCH_POOL_ID,
        artifact_path=f"preselection_pools/{trade_date}/{_RESEARCH_POOL_ID}.json",
        artifact_sha256=digest,
        payload=artifact,
    )
    if receipt != expected_receipt:
        raise ValueError("recovery receipt does not bind the approved artifact")
    return artifact, digest, _exact_source_slots(artifact)


def recover_exact_research_preselection(
    *,
    data_root: Path,
    trade_date: str,
    recovery_artifact: Path,
    recovery_manifest: Path,
    recovery_receipt: Path,
    expected_old_sha256: str,
    expected_recovery_sha256: str,
) -> dict[str, Any]:
    candidate, digest, allowed = _validate_recovery_trio(
        trade_date=trade_date,
        artifact_path=recovery_artifact,
        manifest_path=recovery_manifest,
        receipt_path=recovery_receipt,
        expected_recovery_sha256=expected_recovery_sha256,
    )
    exact_store = _ExactHistoricalHourlyStore(HourlyResearchStore(Path(data_root)), allowed)
    rebuilt = build_hourly_research_pool(
        Path(data_root), trade_date=trade_date, store=exact_store
    )
    if _sha256(rebuilt) != digest or rebuilt != candidate:
        raise ValueError("historical research exact-slot rebuild SHA mismatch")
    publication = PreselectionPoolStore(Path(data_root)).recover_expected_missing(
        rebuilt,
        expected_old_sha256=expected_old_sha256,
    )
    return {
        "schema_version": "v4.research_preselection_exact_recovery.v1",
        "status": "RECOVERED_EXACT_HISTORICAL",
        "trade_date": _date(trade_date),
        "row_count": len(rebuilt["rows"]),
        "source_role": rebuilt["source_role"],
        "source_sha256": rebuilt["source_sha256"],
        "sha256": digest,
        "publication": publication,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def refresh_research_preselection(
    *,
    data_root: Path,
    trade_date: str,
) -> dict:
    artifact = build_hourly_research_pool(
        data_root,
        trade_date=trade_date,
    )
    publication = PreselectionPoolStore(data_root).materialize(artifact)
    return {
        "schema_version": "v3_5.research_preselection_refresh.v1",
        "status": "SUCCEEDED",
        "trade_date": trade_date,
        "row_count": len(artifact["rows"]),
        "source_role": artifact["source_role"],
        "source_sha256": artifact["source_sha256"],
        "publication": publication,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--recovery-artifact", type=Path)
    parser.add_argument("--recovery-manifest", type=Path)
    parser.add_argument("--recovery-receipt", type=Path)
    parser.add_argument("--expected-old-sha256")
    parser.add_argument("--expected-recovery-sha256")
    parser.add_argument("--rollback-current-sha256")
    parser.add_argument(
        "--write-authorization-ref",
        action="append",
        default=None,
        help="untrusted declaration; denied until a separately implemented owner trust provider exists",
    )
    args = parser.parse_args(argv)
    try:
        reject_cli_authority_declaration(args.write_authorization_ref)
    except WriteAuthorityResolutionError as error:
        result = {
            "schema_version": "v4.research_preselection_exact_recovery.v1",
            "status": "REJECTED",
            "trade_date": args.date,
            "reason": error.reason_code,
            "detail": str(error),
            "authorization_source": error.source,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 3
    recovery_values = (
        args.recovery_artifact,
        args.recovery_manifest,
        args.recovery_receipt,
        args.expected_old_sha256,
        args.expected_recovery_sha256,
    )
    try:
        if args.rollback_current_sha256:
            if any(recovery_values):
                raise ValueError("rollback cannot be combined with exact recovery inputs")
            publication = PreselectionPoolStore(args.data_root).rollback_recovery(
                args.date,
                _RESEARCH_POOL_ID,
                expected_current_sha256=args.rollback_current_sha256,
            )
            result = {
                "schema_version": "v4.research_preselection_exact_recovery.v1",
                "status": "ROLLED_BACK",
                "trade_date": _date(args.date),
                "publication": publication,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        elif any(recovery_values):
            if not all(recovery_values):
                raise ValueError("exact recovery requires artifact, manifest, receipt and both approved SHAs")
            result = recover_exact_research_preselection(
                data_root=args.data_root,
                trade_date=args.date,
                recovery_artifact=args.recovery_artifact,
                recovery_manifest=args.recovery_manifest,
                recovery_receipt=args.recovery_receipt,
                expected_old_sha256=args.expected_old_sha256,
                expected_recovery_sha256=args.expected_recovery_sha256,
            )
        else:
            result = refresh_research_preselection(
                data_root=args.data_root,
                trade_date=args.date,
            )
    except FileNotFoundError as error:
        result = {
            "schema_version": "v3_5.research_preselection_refresh.v1",
            "status": "NOT_MATERIALIZED",
            "trade_date": args.date,
            "reason": str(error),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 2
    except ValueError as error:
        result = {
            "schema_version": "v4.research_preselection_exact_recovery.v1",
            "status": "REJECTED",
            "trade_date": args.date,
            "reason": str(error),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 3
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
