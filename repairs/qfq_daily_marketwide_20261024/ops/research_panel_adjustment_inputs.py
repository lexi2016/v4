"""Bind cached factor metadata and existing TDX history for the daily stage."""
from __future__ import annotations

import json
from pathlib import Path
import struct
import zipfile
from typing import Any, Callable
import numpy as np

from ops.research_panel_qfq import _json, _source, _write, canonical_sha, input_path, sha
from ops.research_panel_factor_cache import QfqGateError, collect_metadata, _event_rows


def existing_day_files(tdx_root: Path) -> list[tuple[str, Path]]:
    # Reuse the current Mac authority universe. The legacy Windows driver's
    # BJ-prefix table only accepts 8/9 and would omit existing 430xxx BJ files.
    from ops.macos_research_panel_daily import _a_day_files
    return [(path.stem[2:] + "." + path.stem[:2].upper(), path) for path in _a_day_files(tdx_root)]


def raw_bindings(tdx_root: Path, driver, binding_file: Path, *, required_start: dict[str, int] | None = None, target: int | None = None,
                 quarantine_eligible: dict | None = None) -> dict[str, dict]:
    """Bind existing archive + current .day, never collect a second history.

    Optional explicit archive bindings are required where the daily cache is
    only a tail. Their per-file hashes are verified; conflicting overlaps are
    rejected by the full-history stage.
    """
    supplied = json.loads(binding_file.read_text()) if binding_file.is_file() else {}
    archive = None
    if supplied.get("archive"):
        if supplied.get("overlap_policy") != "ARCHIVE_AUTHORITATIVE_CURRENT_POSTFIX_V1":
            raise QfqGateError("RAW_ARCHIVE_OVERLAP_POLICY_UNBOUND")
        archive = zipfile.ZipFile(_source(supplied["archive"], owner="original native TDX archive"))
    members = {name.replace("\\", "/").lower(): name for name in archive.namelist()} if archive else {}
    result = {}
    for code, current in existing_day_files(tdx_root):
        if not driver.is_a_bj_ts(code):
            continue
        if code in result:
            raise QfqGateError(f"DUPLICATE_DAY_AUTHORITY:{code}")
        item = supplied.get("symbols", {}).get(code, {})
        refs = list(item.get("archive_files", []))
        exchange, number = code[-2:].lower(), code[:6]
        member = members.get(f"{exchange}/lday/{exchange}{number}.day")
        cutoff = None
        if member:
            payload = archive.read(member)
            path = binding_file.parent / "native_archive_members" / supplied["archive"]["sha256"] / (code + ".day")
            if path.exists() and path.read_bytes() != payload:
                raise QfqGateError(f"IMMUTABLE_NATIVE_MEMBER_CONFLICT:{code}")
            if not path.exists():
                _write(path, payload)
            if len(payload) < 32 or len(payload) % 32:
                raise QfqGateError(f"RAW_ARCHIVE_MEMBER_BOUNDARY_INVALID:{code}")
            cutoff = max(struct.unpack_from("<I", payload, offset)[0] for offset in range(0, len(payload), 32))
            refs.append(dict(path=str(path), sha256=sha(path)))
        refs.append(dict(path=str(current.resolve()), sha256=sha(current), **({"from_date_exclusive": cutoff} if cutoff else {})))
        starts = []
        dates = []
        invalid = None
        for ref in refs:
            path = _source(ref, owner=code)
            if path.stat().st_size < 32 or path.stat().st_size % 32:
                invalid = f"RAW_DAY_RECORD_BOUNDARY_INVALID:{code}:{path}"
                if code not in (quarantine_eligible or {}):
                    raise QfqGateError(invalid)
                break
            with path.open("rb") as handle:
                starts.append(struct.unpack("<I", handle.read(4))[0])
            dated = np.fromfile(path, dtype=np.dtype([("date", "<u4"), ("_payload", "V28")]))["date"]
            dates.extend(int(d) for d in dated if max(19000101, ref.get("from_date_exclusive", 0)) < d <= (target or 99991231))
        ordered = sorted(set(dates))
        if not ordered and code not in (quarantine_eligible or {}):
            raise QfqGateError(f"RAW_HISTORY_WINDOW_EMPTY:{code}")
        if invalid or not ordered:
            result[code] = dict(raw_files=refs, raw_binding_error=invalid or "RAW_HISTORY_WINDOW_EMPTY", history_start_date=None)
            continue
        first_output = (required_start or {}).get(code, min((required_start or {}).values(), default=ordered[0]))
        first_index = int(np.searchsorted(ordered, first_output))
        compute_index = max(0, first_index - driver.DAILY_FORMULA_LOOKBACK_RECORDS)
        result[code] = dict(raw_files=refs, history_start_date=min(starts), publish_roles=["selector", "backtest"],
                            compute_start_date=ordered[compute_index], required_output_start_date=first_output,
                            warmup_records=first_index - compute_index, warmup_policy="ORIGINAL_DRIVER_260_PRECEDING_RECORDS")
    if not result:
        raise QfqGateError("RAW_DAY_MARKET_EMPTY")
    if archive:
        archive.close()
    return result


def original_sync_contract(tdx_root: Path, target: int) -> tuple[dict, dict, int]:
    path = tdx_root.parent / "receipts/a_sync_authority" / str(target) / "summary.json"
    if not path.is_file():
        raise QfqGateError(f"ORIGINAL_SYNC_RECEIPT_MISSING:{path}")
    receipt = json.loads(path.read_text())
    if str(receipt.get("target_date")) != str(target) or not receipt.get("target_keys"):
        raise QfqGateError("ORIGINAL_SYNC_RECEIPT_TARGET_INVALID")
    markets = {0: "SZ", 1: "SH", 2: "BJ"}
    eligible = {}
    for row in receipt.get("symbol_reconciliation", []):
        code = str(row["symbol"]).zfill(6) + "." + markets[int(row["market"])]
        if row.get("classification") == "QUARANTINED" and row.get("quarantine") is True and row.get("target_date_ready") is False:
            eligible[code] = {key: row.get(key) for key in ("classification", "quarantine", "target_date_ready", "reason_code", "source_sha256_after", "path")}
    floor = int(receipt.get("accepted_target_date_file_count", 0))
    if floor < 1:
        raise QfqGateError("ORIGINAL_ACCEPTED_FLOOR_UNCONFIRMED")
    return dict(path=str(path), sha256=sha(path)), eligible, floor


def prepare_snapshot(*, tdx_root: Path, data_root: Path, target: int, driver,
                     client_factory: Callable[[], Any] | None = None, force_refresh: bool = False,
                     required_start: dict[str, int] | None = None,
                     **query_options) -> dict:
    root = input_path(data_root).parent
    sync_ref, eligible, floor = original_sync_contract(tdx_root, target)
    for code, status in eligible.items():
        if not status.get("path") or not status.get("source_sha256_after") or sha(Path(status["path"])) != status["source_sha256_after"]:
            raise QfqGateError(f"ORIGINAL_QUARANTINE_RAW_IDENTITY_DRIFT:{code}")
    bindings = raw_bindings(tdx_root, driver, root / "qfq_raw_history_binding.json", required_start=required_start, target=target, quarantine_eligible=eligible)
    gaps = [dict(ts_code=code, required_start=date, available_start=bindings.get(code, {}).get("history_start_date"))
            for code, date in (required_start or {}).items()
            if code not in bindings or bindings[code].get("raw_binding_error") or bindings[code]["history_start_date"] > date]
    blocking_gaps = [row for row in gaps if row["ts_code"] not in eligible]
    if blocking_gaps:
        _json(root / "qfq_raw_history_gaps.json", dict(asof_date=target, missing=gaps))
        raise QfqGateError(f"RAW_FULL_HISTORY_INPUT_MISSING:{len(blocking_gaps)}:{root / 'qfq_raw_history_gaps.json'}")
    factor_cache_root = tdx_root.parent / "adjustment_inputs/futu_rehab"
    _json(root / "qfq_factor_cache_binding.json", dict(path=str(factor_cache_root.resolve())))
    # Real Stage-A quota evidence: 0.2s exceeded 60 requests/30s. Preserve the
    # reviewed cache component and enforce the safer cadence at this caller.
    query_options["min_interval"] = max(.65, float(query_options.get("min_interval", .65)))
    metadata = collect_metadata(list(bindings), cache_root=factor_cache_root, target=target,
                                client_factory=client_factory, force_refresh=force_refresh, **query_options)
    fallback_file = root / "tdx_official_adjustment_fallback.json"
    unsupported = {code: bindings[code] for code, row in metadata["symbols"].items()
                   if code in bindings and not bindings[code].get("raw_binding_error") and row.get("status") == "UNSUPPORTED_MARKET"}
    if unsupported:
        from ops.research_panel_tdx_adjustment_inputs import build_fallback
        fallback = build_fallback(root, unsupported, target)
    else:
        fallback = json.loads(fallback_file.read_text()) if fallback_file.is_file() else {}
    sources, symbols, missing = {sync_ref["path"]: sync_ref}, {}, []
    archive_binding = root / "qfq_raw_history_binding.json"
    if archive_binding.is_file():
        archive_config = json.loads(archive_binding.read_text())
        ref = dict(path=str(archive_binding), sha256=sha(archive_binding))
        sources[ref["path"]] = ref
        if archive_config.get("archive"):
            ref = archive_config["archive"]
            sources[ref["path"]] = ref
    quarantine = {row["ts_code"]: dict(reason="RAW_FULL_HISTORY_INPUT_MISSING", detail=row, original_status=eligible[row["ts_code"]]) for row in gaps if row["ts_code"] in eligible}
    for code, binding in bindings.items():
        if binding.get("raw_binding_error"):
            quarantine[code] = dict(reason=binding["raw_binding_error"], original_status=eligible[code])
    for code, binding in bindings.items():
        receipt = metadata["symbols"][code]
        if code in quarantine:
            continue
        if receipt["status"] in ("OK", "EMPTY"):
            ref = receipt["response"]
            response = json.loads(_source(ref, owner=code).read_text())
            events = _event_rows(response["rows"], target, binding["compute_start_date"])
            sources[ref["path"]] = ref
            method = "FUTU_GET_REHAB_AFFINE"
        else:
            item = fallback.get("symbols", {}).get(code, {})
            # Official TDX terms may cover Futu-unsupported symbols only when
            # the original source/category and conversion decision are bound.
            if (fallback.get("asof_date") != target or item.get("event_coverage_complete") is not True
                    or item.get("unsupported_categories") != [] or not item.get("conversion_receipt")
                    or "events" not in item or not item.get("source_files")):
                gap = dict(ts_code=code, status=receipt["status"], reason=receipt.get("error", receipt.get("reason")), needed=str(fallback_file))
                error = str(receipt.get("error", ""))
                unknown_stock = error.startswith("FUTU_GET_REHAB_RETURN_-1:未知股票 ")
                if code in eligible and (receipt["status"] != "ERROR" or unknown_stock):
                    quarantine[code] = dict(reason="ADJUSTMENT_INPUT_UNAVAILABLE", detail=gap, original_status=eligible[code], factor_evidence=receipt)
                    evidence = root / "quarantine_factor_evidence" / (canonical_sha(receipt) + ".json")
                    if not evidence.exists():
                        _json(evidence, receipt)
                    ref = dict(path=str(evidence), sha256=sha(evidence))
                    sources[ref["path"]] = ref
                    if receipt.get("response"):
                        ref = receipt["response"]
                        _source(ref, owner=code)
                        sources[ref["path"]] = ref
                else:
                    missing.append(gap)
                continue
            for ref in item["source_files"] + [item["conversion_receipt"]]:
                _source(ref, owner=code)
                sources[ref["path"]] = ref
            events, method = item["events"], "TDX_OFFICIAL_TERMS_BOUND_CONVERSION"
        symbols[code] = dict(**binding, events=events, source_method=method, event_coverage_complete=True)
    if missing:
        _json(root / "qfq_input_gaps.json", dict(asof_date=target, missing=missing))
        raise QfqGateError(f"ADJUSTMENT_MARKET_COVERAGE_INCOMPLETE:{len(missing)}:{root / 'qfq_input_gaps.json'}")
    for code in quarantine:
        for ref in bindings.get(code, {}).get("raw_files", []):
            sources[ref["path"]] = ref
    snapshot = dict(schema="a_share_qfq_adjustment_input_v1", asof_date=target, coverage_end_date=target,
                    price_basis="QFQ_ASOF", price_rounding="NONE_PROVIDER_AFFINE_PRECISION", volume_basis="QFQ_EVENT_VOLUME",
                    volume_adjustment="INDEPENDENT_PROVIDER_BACKWARD_A_NOT_RECIPROCAL_FORWARD_A",
                    amount_basis="RAW_TURNOVER", convention="FUTU_AFFINE_WITH_EXPLICIT_TDX_UNSUPPORTED_FALLBACK_V1",
                    historical_PIT=False, source_files=sorted(sources.values(), key=lambda x: x["path"]), symbols=symbols)
    snapshot.update(quarantine_symbols=quarantine, original_quarantine_eligible=eligible, accepted_target_date_floor=floor)
    snapshot["revision"] = canonical_sha(snapshot)
    path = input_path(data_root)
    existing = json.loads(path.read_text()) if path.is_file() else {}
    if existing.get("revision") == snapshot["revision"]:
        return existing
    snapshot["observed_at"] = metadata.get("completed_at", metadata["finished_at"])
    immutable = root / "adjustment_snapshots" / (canonical_sha(snapshot) + ".json")
    if not immutable.exists():
        _json(immutable, snapshot)
    _json(path, snapshot)
    return snapshot
