"""Read-only D-1 membership projection from the existing HK Connect owner.

This adapter joins the exact Futu Connect capture, its linked panel and
capture manifests, the existing V3.5 security-master reader, and the single
successful HK daily dispatch receipt. It does not create or refresh any input.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping

from .workspace_projection import FLAGS, canonical_symbol, date_token, digest, timestamp

_SHA = re.compile(r"^[0-9a-f]{64}$")
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,100}$")
_WORKLOAD = "research_panel_daily_hk"
_SLOT = "1720"
_PLATES = {"HK.GangGuTong", "HK.LIST1922"}


def _canonical_sha(value: Any) -> str:
    # Match the existing V3.5 HK capture's canonical JSON convention, which
    # allows JSON's historical NaN spelling in nullable reference fields.
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _valid_root(value: Path | str) -> Path:
    root = Path(value).expanduser()
    if not root.is_absolute() or ".." in root.parts or root.is_symlink():
        raise ValueError("HK_CONNECT_D1_ROOT_INVALID")
    resolved = root.resolve(strict=True)
    if resolved != root or not resolved.is_dir():
        raise ValueError("HK_CONNECT_D1_ROOT_INVALID")
    return resolved


def _read_bytes(root: Path, relative: str, *, limit: int = 64 * 1024 * 1024) -> bytes:
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise ValueError("HK_CONNECT_D1_PATH_INVALID")
    path = root
    for part in rel.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("HK_CONNECT_D1_PATH_SYMLINK")
    if not path.is_file():
        raise FileNotFoundError("HK_CONNECT_D1_FILE_MISSING")
    resolved = path.resolve(strict=True)
    if root not in resolved.parents or resolved.stat().st_size > limit:
        raise ValueError("HK_CONNECT_D1_FILE_BOUNDS_INVALID")
    return resolved.read_bytes()


def _load_json(root: Path, relative: str, *, limit: int = 64 * 1024 * 1024) -> tuple[dict[str, Any], bytes]:
    raw = _read_bytes(root, relative, limit=limit)
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("HK_CONNECT_D1_JSON_ENVELOPE_INVALID")
    return dict(value), raw


def _under(root: Path, absolute: Any) -> str:
    if not isinstance(absolute, str) or not absolute:
        raise ValueError("HK_CONNECT_D1_LINK_PATH_MISSING")
    path = Path(absolute)
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("HK_CONNECT_D1_LINK_PATH_INVALID")
    resolved = path.resolve(strict=True)
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("HK_CONNECT_D1_LINK_OUTSIDE_ROOT") from exc


def _flags_false(value: Mapping[str, Any]) -> bool:
    return (value.get("RESEARCH_ONLY", True) is True
            and all(value.get(key) is False for key in ("production_allowed", "buy_gate_updated", "orders_sent")))


def _load_dispatch(
    root: Path,
    *,
    source_date: str,
    panel: Mapping[str, Any],
    panel_sha: str,
    cutoff: datetime,
) -> tuple[dict[str, Any], str, str]:
    # The Manager binding names the exact live receipt root, while existing
    # direct callers may still supply the parent receipts root. Accept those
    # two explicit layouts without searching or ascending outside the root.
    slot_relative = (Path(source_date) / _SLOT if root.name == "live"
                     else Path("live") / source_date / _SLOT)
    # This is the existing HK daily workload's one scheduled slot, bounded to
    # one exact date directory. We accept only one receipt that verifies the
    # linked panel summary; no cross-date/latest search is performed.
    slot_path = root / slot_relative
    if slot_path.is_symlink() or not slot_path.is_dir():
        raise ValueError("HK_CONNECT_D1_DISPATCH_SLOT_MISSING")
    matches = sorted(slot_path.glob("*.dispatch-receipt.json"))
    if not matches:
        raise ValueError("HK_CONNECT_D1_DISPATCH_RECEIPT_MISSING")
    verified: list[tuple[dict[str, Any], str, str]] = []
    for path in matches:
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        receipt, raw = _load_json(root, relative, limit=8 * 1024 * 1024)
        sha = hashlib.sha256(raw).hexdigest()
        results = receipt.get("workload_results")
        if not isinstance(results, list):
            continue
        hk_results = [row for row in results if isinstance(row, Mapping) and row.get("workload_id") == _WORKLOAD]
        if len(hk_results) != 1:
            continue
        row = hk_results[0]
        summary = row.get("source_result")
        auth = row.get("_authoritative_payload")
        summary_hk = summary.get("lanes", {}).get("HK") if isinstance(summary, Mapping) else None
        auth_hk = auth.get("lanes", {}).get("HK") if isinstance(auth, Mapping) else None
        exact_summary = all(
            isinstance(value, Mapping)
            and value.get("status") == "READY"
            and value.get("target_date") == source_date
            and value.get("sha256") == panel_sha
            and value.get("row_count") == panel.get("row_count")
            for value in (summary_hk, auth_hk)
        )
        if not exact_summary:
            continue
        finish = timestamp(receipt.get("finished_at"))
        if (receipt.get("schema_version") != "v3_5.dispatch.v1"
                or receipt.get("status") != "SUCCEEDED"
                or receipt.get("target_date") != source_date
                or receipt.get("business_date") != source_date
                or receipt.get("scheduled_date") != source_date
                or receipt.get("slot") != _SLOT
                or receipt.get("selected_workload_ids") != [_WORKLOAD]
                or receipt.get("started_workload_ids") != [_WORKLOAD]
                or row.get("status") != "SUCCEEDED" or row.get("lane") != "HK"
                or row.get("lane_status") != "READY" or row.get("exit_code") != 0
                or path.name != str(receipt.get("run_id")) + ".dispatch-receipt.json"
                or not _RUN_ID.fullmatch(str(receipt.get("run_id") or ""))
                or finish is None
                or finish.strftime("%Y%m%d") != source_date or finish > cutoff
                or not _flags_false(receipt)
                or not _flags_false(row)
                or not all(isinstance(value, Mapping) and _flags_false(value) for value in (summary, auth))):
            continue
        verified.append((receipt, sha, finish.isoformat()))
    if len(verified) != 1:
        raise ValueError("HK_CONNECT_D1_DISPATCH_IDENTITY_AMBIGUOUS")
    return verified[0]


def read_d1_scope(
    context: Mapping[str, Any],
    *,
    security_master_root: Path | str,
    capture_receipt_root: Path | str,
    dispatch_receipt_root: Path | str,
    universe_reader: Callable[[Path, str], tuple[Mapping[str, Any], Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Verify the previous full-session Connect capture and project its codes.

    ``context.market_session`` is supplied by the native HK calendar in the
    saved plan context. It remains the source date; ``plan_trade_date`` stays
    the Manager target date.
    """
    target = date_token(str(context.get("plan_trade_date") or ""))
    source_date = date_token(str(context.get("market_session") or ""))
    result: dict[str, Any] = dict(
        status="CANNOT_CONFIRM", target_trade_date=target, source_date=source_date,
        codes=[], source=None, identity=None, gaps=[], read_only=True, **FLAGS,
    )
    try:
        cutoff = timestamp(context.get("research_cutoff"))
        if cutoff is None or source_date >= target:
            raise ValueError("HK_CONNECT_D1_PLAN_CONTEXT_INVALID")
        master_root = _valid_root(security_master_root)
        capture_root = _valid_root(capture_receipt_root)
        dispatch_root = _valid_root(dispatch_receipt_root)

        panel, panel_raw = _load_json(capture_root, f"HK-{source_date}.json", limit=16 * 1024 * 1024)
        panel_sha = hashlib.sha256(panel_raw).hexdigest()
        run_id = panel.get("capture_run_id")
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            raise ValueError("HK_CONNECT_D1_CAPTURE_RUN_INVALID")
        raw_relative = f"hk_capture/{source_date}/{run_id}.capture.json"
        capture_manifest_relative = f"hk_capture/{source_date}/{run_id}.json"
        linked_raw_relative = _under(capture_root, panel.get("capture_raw_path"))
        linked_manifest_relative = _under(capture_root, panel.get("capture_manifest_path"))
        if linked_raw_relative != raw_relative or linked_manifest_relative != capture_manifest_relative:
            raise ValueError("HK_CONNECT_D1_CAPTURE_LINK_MISMATCH")
        capture, capture_raw = _load_json(capture_root, raw_relative, limit=32 * 1024 * 1024)
        capture_manifest, capture_manifest_raw = _load_json(capture_root, capture_manifest_relative, limit=32 * 1024 * 1024)
        raw_sha = hashlib.sha256(capture_raw).hexdigest()
        capture_manifest_sha = hashlib.sha256(capture_manifest_raw).hexdigest()

        if (panel.get("schema_version") != "v3.macos.research_panel_receipt.v1"
                or panel.get("status") != "READY" or panel.get("lane") != "HK"
                or panel.get("target_date") != source_date
                or panel.get("capture_raw_sha256") != raw_sha
                or panel.get("source_sha256") != capture.get("source_sha256")
                or panel.get("row_count") != len(capture.get("rows") or [])
                or panel.get("universe_count") != len(capture.get("codes") or [])
                or not _SHA.fullmatch(str(panel.get("sha256") or ""))
                or panel.get("capture_run_id") != run_id
                or not _flags_false(panel)):
            raise ValueError("HK_CONNECT_D1_PANEL_RECEIPT_INVALID")
        panel_authority = panel.get("authority")
        if (not isinstance(panel_authority, Mapping)
                or panel_authority.get("status") != "READY"
                or panel_authority.get("target_date") != source_date
                or panel_authority.get("through_date") != source_date
                or not _flags_false(panel_authority)):
            raise ValueError("HK_CONNECT_D1_PANEL_LANE_INVALID")
        if (capture_manifest.get("schema_version") != "v3.macos.research_panel_hk_capture_manifest.v1"
                or capture_manifest.get("status") != "READY"
                or capture_manifest.get("target_date") != source_date
                or capture_manifest.get("capture_run_id") != run_id
                or capture_manifest.get("capture_raw_sha256") != raw_sha
                or capture_manifest.get("capture_sha256") != capture.get("capture_sha256")
                or _canonical_sha(capture_manifest.get("capture")) != _canonical_sha(capture)
                or capture_manifest.get("codes") != capture.get("codes")):
            raise ValueError("HK_CONNECT_D1_CAPTURE_MANIFEST_INVALID")

        codes = capture.get("codes")
        if (capture.get("schema_version") != "v3.macos.research_panel_hk_capture.v1"
                or capture.get("target_date") != source_date
                or not isinstance(codes, list) or not codes or codes != sorted(set(codes))
                or any(not isinstance(code, str) or canonical_symbol(code) != code for code in codes)
                or capture.get("plates") is None or set(capture.get("plates") or []) != _PLATES
                or not _flags_false(capture)
                or capture.get("capture_sha256") != _canonical_sha({k: v for k, v in capture.items() if k != "capture_sha256"})
                or not isinstance(capture.get("source_payload"), Mapping)
                or capture.get("source_sha256") != _canonical_sha(capture["source_payload"])
                or _canonical_sha(capture["source_payload"].get("rows")) != _canonical_sha(capture.get("rows"))):
            raise ValueError("HK_CONNECT_D1_RAW_CAPTURE_INVALID")
        row_codes = [row.get("code") for row in capture.get("rows") or [] if isinstance(row, Mapping)]
        if (len(row_codes) != len(capture.get("rows") or []) or len(row_codes) != len(set(row_codes))
                or any(code not in set(codes) for code in row_codes)
                or any(row.get("trade_date") != source_date for row in capture.get("rows") or [])):
            raise ValueError("HK_CONNECT_D1_CAPTURE_ROW_IDENTITY_INVALID")

        # Use the existing shared V3.5 security-master reader. Membership is
        # bound from captured code identifiers only; names/market fields are
        # not consulted as eligibility evidence.
        if universe_reader is None:
            from upstreams.v3_shared_data.shared_data.hk_security_master import load_verified_hk_security_master
            universe_reader = load_verified_hk_security_master
        names, master = universe_reader(master_root, source_date)
        master_codes = sorted(names) if isinstance(names, Mapping) else []
        if not master_codes or codes != master_codes:
            raise ValueError("HK_CONNECT_D1_CAPTURE_MASTER_CODE_SET_MISMATCH")
        asset_root = master_root / "assets" / "hk_security_master"
        latest, _latest_raw = _load_json(asset_root, "latest.json", limit=8 * 1024 * 1024)
        entries = latest.get("entries")
        entry = entries.get(source_date) if isinstance(entries, Mapping) else None
        if not isinstance(entry, Mapping):
            raise ValueError("HK_CONNECT_D1_MASTER_LATEST_ENTRY_MISSING")
        manifest_relative = str(entry.get("manifest_relative") or "")
        receipt_relative = str(entry.get("receipt_relative") or "")
        manifest, master_manifest_raw = _load_json(asset_root, manifest_relative, limit=4 * 1024 * 1024)
        receipt, master_receipt_raw = _load_json(asset_root, receipt_relative, limit=4 * 1024 * 1024)
        artifact_relative = str(manifest.get("artifact_relative") or "")
        artifact_raw = _read_bytes(asset_root, artifact_relative, limit=64 * 1024 * 1024)
        manifest_sha = hashlib.sha256(master_manifest_raw).hexdigest()
        receipt_sha = hashlib.sha256(master_receipt_raw).hexdigest()
        artifact_sha = hashlib.sha256(artifact_raw).hexdigest()
        security_master = panel.get("security_master")
        receipt_manifest_sha = _canonical_sha(manifest)
        if (not isinstance(security_master, Mapping)
                or security_master.get("status") != "READY"
                or security_master.get("trade_date") != source_date
                or security_master.get("row_count") != len(codes)
                or security_master.get("run_id") != manifest.get("run_id")
                or security_master.get("security_master_run_id") != manifest.get("run_id")
                or security_master.get("security_master_manifest_sha256") != manifest_sha
                or security_master.get("security_master_artifact_sha256") != artifact_sha
                or security_master.get("capture_sha256") != capture.get("capture_sha256")
                or security_master.get("source_sha256") != capture.get("source_sha256")
                or security_master.get("panel_sha256") != panel_authority.get("panel_sha256")
                or manifest.get("trade_date") != source_date
                or manifest.get("run_id") != entry.get("run_id")
                or manifest.get("row_count") != len(codes)
                or manifest.get("artifact_sha256") != artifact_sha
                or manifest.get("universe_codes_sha256") != _canonical_sha(codes)
                or any(manifest.get(key) is not False for key in ("later_snapshot_price_allowed", "production_allowed", "buy_gate_updated", "orders_sent"))
                or latest.get("schema_version") != "v3_shared_data.hk_security_master_latest.v1"
                or entry.get("manifest_relative") != manifest_relative
                or entry.get("receipt_relative") != receipt_relative
                or receipt.get("run_id") != manifest.get("run_id")
                or receipt.get("schema_version") != "v3_shared_data.hk_security_master_receipt.v1"
                or receipt.get("status") != "READY"
                or receipt.get("trade_date") != source_date
                or receipt.get("manifest_sha256") != receipt_manifest_sha
                or receipt.get("artifact_sha256") != artifact_sha
                or any(receipt.get(key) is not False for key in ("production_allowed", "buy_gate_updated", "orders_sent"))
                or not _flags_false(security_master)):
            raise ValueError("HK_CONNECT_D1_MASTER_LINK_INVALID")
        codes_sha = _canonical_sha(codes)
        if (manifest.get("universe_codes_sha256") != codes_sha
                or security_master.get("universe_codes_sha256") != codes_sha
                or capture_manifest.get("codes") != codes):
            raise ValueError("HK_CONNECT_D1_MASTER_CODE_IDENTITY_INVALID")
        master_captured = timestamp(manifest.get("captured_at"))
        if master_captured is None or master_captured > cutoff:
            raise ValueError("HK_CONNECT_D1_MASTER_AFTER_CUTOFF_OR_UNKNOWN")

        dispatch, dispatch_sha, dispatch_finished_at = _load_dispatch(
            dispatch_root, source_date=source_date, panel=panel,
            panel_sha=str(panel.get("sha256") or ""), cutoff=cutoff,
        )
        source = {
            "owner": "V3_5_FUTU_HK_CONNECT_CAPTURE_VIA_RESEARCH_PANEL_DAILY_DISPATCH",
            "role": "HK_CONNECT_FULL_MARKET_AUTHORITY",
            "market": "HK_CONNECT",
            "lane": "HK",
            "source_date": source_date,
            "sha256": raw_sha,
            "capture_manifest_sha256": capture_manifest_sha,
            "panel_receipt_sha256": panel_sha,
            "panel_summary_sha256": panel.get("sha256"),
            "master_manifest_sha256": manifest_sha,
            "master_receipt_sha256": receipt_sha,
            "master_artifact_sha256": artifact_sha,
            "master_run_id": manifest.get("run_id"),
            "dispatch_receipt_sha256": dispatch_sha,
            "dispatch_run_id": dispatch.get("run_id"),
            "dispatch_finished_at": dispatch_finished_at,
            "availability_upper_bound": dispatch_finished_at,
            "availability_semantics": "SUCCESSFUL_HK_DISPATCH_FINISH_UPPER_BOUND_FOR_CAPTURE_AVAILABILITY",
            "membership_semantics": "EXACT_PREVIOUS_FULL_SESSION_CAPTURED_CONNECT_CODES",
            "capture_run_id": run_id,
            "capture_codes_sha256": codes_sha,
            "plate_ids": sorted(_PLATES),
        }
        identity = digest([
            target, source_date, codes, raw_sha, capture_manifest_sha, panel_sha,
            manifest_sha, receipt_sha, artifact_sha, dispatch_sha, dispatch_finished_at,
        ])
        result.update(status="OWNER_VERIFIED", codes=list(codes), source=source,
            identity=identity, membership_semantics=source["membership_semantics"],
            availability_semantics=source["availability_semantics"],
            effective_available_at=dispatch_finished_at,
            dispatch_slot=_SLOT, target_date_source_status="D1_CAPTURE_VERIFIED")
    except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        reason = str(exc)
        if not re.fullmatch(r"[A-Z0-9_:. -]{1,180}", reason):
            reason = type(exc).__name__
        result["gaps"] = ["HK_CONNECT_D1_CAPTURE_UNVERIFIED:" + reason]
    return result


__all__ = ["read_d1_scope"]
