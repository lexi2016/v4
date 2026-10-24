"""Bind cached factor metadata and existing TDX history for the daily stage."""
from __future__ import annotations

import json
import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import struct
import zipfile
from typing import Any, Callable
import numpy as np

from ops.research_panel_qfq import _json, _source, _write, canonical_sha, input_path, sha, CODE, legacy_preservation
from ops.research_panel_factor_cache import QfqGateError, collect_metadata, _event_rows


HISTORY_RESOLUTION = "ARCHIVE_PRIMARY_NATIVE_MISSING_AND_TAIL_V2"


def history_event_coverage_bound(receipt: dict, start: int, target: int) -> bool:
    first, last = receipt.get("history_coverage_start_date"), receipt.get("history_coverage_end_date")
    return (type(first) is int and type(last) is int and first <= start and last >= target)




def _full_provider_response_events(receipt: dict, code: str, target: int, start: int,
                                   metadata: dict) -> tuple[list[dict], str]:
    """The original successful whole response, including an identified empty list."""
    if receipt.get("status") not in {"OK", "EMPTY"} or receipt.get("asof_date", target) != target:
        raise QfqGateError("HISTORY_FULL_RESPONSE_STATUS_OR_ASOF_CONFLICT:" + code)
    capture_date = receipt.get("capture_date")
    if capture_date is None:
        text = receipt.get("queried_at") or metadata.get("completed_at") or metadata.get("finished_at")
        try:
            observed = datetime.fromisoformat(text)
            if observed.tzinfo is None:
                raise ValueError("timezone missing")
            capture_date = int(observed.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d"))
        except (TypeError, ValueError) as exc:
            raise QfqGateError("HISTORY_FULL_RESPONSE_CAPTURE_DATE_UNBOUND:" + code) from exc
    try:
        if type(capture_date) is not int:
            raise ValueError("capture date type")
        datetime.strptime(str(capture_date), "%Y%m%d")
    except ValueError as exc:
        raise QfqGateError("HISTORY_FULL_RESPONSE_CAPTURE_DATE_UNBOUND:" + code) from exc
    if capture_date < target:
        raise QfqGateError("HISTORY_FULL_RESPONSE_CAPTURE_BEFORE_TARGET:" + code)
    response = json.loads(_source(receipt["response"], owner=code).read_text())
    rows = response.get("rows")
    if (response.get("return_code") != 0 or response.get("code") != code[-2:] + "." + code[:6]
            or not isinstance(rows, list) or receipt.get("row_count") != len(rows)
            or receipt["status"] != ("OK" if rows else "EMPTY")):
        raise QfqGateError("HISTORY_FULL_RESPONSE_IDENTITY_CONFLICT:" + code)
    scope = "provider_full_response_nonempty/chart-asof" if rows else "provider_full_response_zero_events/chart-asof"
    return _event_rows(rows, target, start), scope


def bind_full_response_history_metadata(metadata_ref: dict, bindings: dict[str, dict], target: int,
                                        destination: Path, *, fallback_ref: dict | None = None) -> dict:
    """Bind the original provider full response to an earlier chart prefix.

    get_rehab(code) has no date/page/limit request field. Coverage here means
    replay of its complete successfully cached response, not an independent
    promise of all historical publications or historical PIT certification.
    A successful identified EMPTY list has the same provider scope as nonempty.
    Missing, ERROR and unsupported responses never acquire no-event coverage.
    TDX coverage must come from a full-window replay of the original capture.
    """
    original = json.loads(_source(metadata_ref, owner="original full-response metadata").read_text())
    if original.get("asof_date") != target:
        raise QfqGateError("HISTORY_METADATA_ASOF_CONFLICT")
    fallback = json.loads(_source(fallback_ref, owner="original TDX full-window replay").read_text()) if fallback_ref else {}
    symbols, gaps = {}, []
    for code, binding in sorted(bindings.items()):
        receipt = dict(original.get("symbols", {}).get(code, {}))
        start = binding["history_start_date"]
        if receipt.get("status") in {"OK", "EMPTY"}:
            if not receipt.get("response"):
                gaps.append(dict(ts_code=code, status=receipt.get("status"), reason="SUCCESSFUL_RESPONSE_IDENTITY_UNBOUND"))
            else:
                events, response_scope = _full_provider_response_events(receipt, code, target, start, original)
                receipt.update(history_coverage_start_date=start, history_coverage_end_date=target,
                    provider_response_scope=response_scope, provider_event_count=len(events),
                    coverage_basis="FUTU_FULL_RESPONSE_CHART_ASOF_V1; " + response_scope + "; PROVIDER_SCOPE_INFERENCE_NOT_INDEPENDENT_HISTORY_CERTIFICATION")
        elif receipt.get("status") == "UNSUPPORTED_MARKET" and code.endswith(".BJ"):
            item = fallback.get("symbols", {}).get(code, {})
            if (fallback.get("asof_date") != target or item.get("event_coverage_complete") is not True
                    or item.get("unsupported_categories") != [] or not item.get("source_files")
                    or not item.get("conversion_receipt") or not history_event_coverage_bound(item, start, target)):
                gaps.append(dict(ts_code=code, reason="TDX_FULL_WINDOW_REPLAY_UNBOUND"))
            else:
                for ref in item["source_files"] + [item["conversion_receipt"]]:
                    _source(ref, owner=code)
                receipt.update(history_coverage_start_date=start, history_coverage_end_date=target,
                               coverage_basis="ORIGINAL_TDX_FULL_CAPTURE_WINDOW_REPLAY", fallback=fallback_ref)
        else:
            gaps.append(dict(ts_code=code, status=receipt.get("status"), reason="NO_SUCCESSFUL_IDENTIFIED_FULL_RESPONSE"))
        symbols[code] = receipt
    output = dict(schema="qfq_full_response_history_metadata_v1", asof_date=target,
        original_metadata=metadata_ref, original_fallback=fallback_ref,
        provider_contract="https://openapi.futunn.com/futu-api-doc/quote/get-rehab.html",
        original_capture_adapter=dict(path=str(Path(__file__).with_name("research_panel_factor_cache.py")),
                                      sha256=sha(Path(__file__).with_name("research_panel_factor_cache.py"))),
        historical_PIT=False, symbols=symbols, gaps=gaps,
        finished_at=original.get("finished_at"), completed_at=original.get("completed_at", original.get("finished_at")))
    _json(destination, output)
    return output


def history_raw_bindings(config: dict, binding_file: Path, driver, target: int, *, current_tdx_root: Path | None = None) -> dict[str, dict]:
    """Adapt the accepted per-code original refs, never the derived panel.

    Archive members are extracted byte-identically into the isolated input
    directory. The original container/member refs remain in every binding.
    No archive inventory, live-file discovery or stock-classification filter
    determines the explicitly bound historical membership.
    """
    source_ref = config["source_config"]
    source = json.loads(_source(source_ref, owner="accepted R2 source config").read_text())
    if source.get("source_resolution") != HISTORY_RESOLUTION:
        raise QfqGateError("HISTORY_SOURCE_RESOLUTION_UNBOUND")
    for ref in [config["source_policy"], *config["accepted_evidence"]]:
        _source(ref, owner="accepted history evidence")
    policy = json.loads(_source(config["source_policy"], owner="whole-row resolution policy").read_text())
    if (policy.get("name") != HISTORY_RESOLUTION or policy.get("selection_unit") != "COMPLETE_SOURCE_BAR"
            or policy.get("price_or_volume_conversion") != "NONE"):
        raise QfqGateError("HISTORY_WHOLE_ROW_POLICY_UNBOUND")
    archives = {ref["path"]: ref for ref in config.get("archive_refs", [])}
    opened, result = {}, {}
    try:
        for stock in source["stocks"]:
            code = stock["code"]
            if not CODE.fullmatch(code) or code in result:
                raise QfqGateError(f"HISTORY_CODE_BINDING_INVALID:{code}")
            refs, all_dates, roles = [], set(), set()
            for original in stock["sources"]:
                role = original.get("name")
                if role not in {"archive", "native"} or role in roles:
                    raise QfqGateError(f"HISTORY_SOURCE_ROLE_AMBIGUOUS:{code}:{role}")
                roles.add(role)
                if original.get("kind") == "archive_member":
                    container = archives.get(original["path"])
                    if not container:
                        raise QfqGateError(f"HISTORY_ARCHIVE_CONTAINER_UNBOUND:{code}")
                    if container["path"] not in opened:
                        opened[container["path"]] = zipfile.ZipFile(_source(container, owner="original archive"))
                    payload = opened[container["path"]].read(original["member"])
                    digest = hashlib.sha256(payload).hexdigest()
                    if digest != original["member_sha256"]:
                        raise QfqGateError(f"HISTORY_ARCHIVE_MEMBER_DRIFT:{code}")
                    path = binding_file.parent / "native_archive_members" / container["sha256"] / (code + ".day")
                    if path.exists() and path.read_bytes() != payload:
                        raise QfqGateError(f"IMMUTABLE_NATIVE_MEMBER_CONFLICT:{code}")
                    if not path.exists():
                        _write(path, payload)
                elif original.get("kind") == "day_bytes":
                    path = _source(original, owner=code)
                    payload = path.read_bytes()
                    digest = original["sha256"]
                else:
                    raise QfqGateError(f"HISTORY_SOURCE_KIND_UNSUPPORTED:{code}")
                if not payload or len(payload) % 32:
                    raise QfqGateError(f"HISTORY_SOURCE_RECORD_BOUNDARY:{code}:{role}")
                dates = np.frombuffer(payload, dtype=np.dtype([("date", "<u4"), ("_payload", "V28")]))["date"]
                if len(set(map(int, dates))) != len(dates) or np.any(dates <= 19000101):
                    raise QfqGateError(f"HISTORY_SOURCE_DATE_KEYS_INVALID:{code}:{role}")
                all_dates.update(int(d) for d in dates if int(d) <= target)
                refs.append(dict(path=str(path), sha256=digest, source_role=role, original_ref=original))
            if current_tdx_root is not None:
                # Keep every frozen native whole row. The original daily source
                # supplies only missing/new exact native keys, never field fills.
                live = current_tdx_root / "vipdoc" / code[-2:].lower() / "lday" / (code[-2:].lower() + code[:6] + ".day")
                if live.is_file():
                    current_payload = live.read_bytes()
                    if not current_payload or len(current_payload) % 32:
                        raise QfqGateError("DAILY_HISTORY_NATIVE_BOUNDARY:" + code)
                    live_ref = dict(path=str(live.resolve()), sha256=hashlib.sha256(current_payload).hexdigest())
                    previous = next((ref for ref in refs if ref["source_role"] == "native"), None)
                    prior_payload = Path(previous["path"]).read_bytes() if previous else b""
                    rows = {struct.unpack_from("<I", prior_payload, i)[0]: prior_payload[i:i+32]
                            for i in range(0, len(prior_payload), 32)}
                    new_dates = set()
                    seen = set()
                    for offset in range(0, len(current_payload), 32):
                        date = struct.unpack_from("<I", current_payload, offset)[0]
                        if date in seen or date <= 19000101:
                            raise QfqGateError("DAILY_HISTORY_NATIVE_KEYS_INVALID:" + code)
                        seen.add(date)
                        if date <= target and date not in rows:
                            rows[date] = current_payload[offset:offset+32]
                            new_dates.add(date)
                    payload = b"".join(rows[date] for date in sorted(rows))
                    if payload:
                        digest = hashlib.sha256(payload).hexdigest()
                        merged = binding_file.parent / "native_daily_history" / (code + "." + digest + ".day")
                        if not merged.exists():
                            _write(merged, payload)
                        lineage = dict(policy="FROZEN_NATIVE_WHOLE_ROW_THEN_DAILY_MISSING_KEYS_V1",
                                       frozen_native=previous, current_native=live_ref, added_dates=sorted(new_dates))
                        manifest = merged.with_suffix(".receipt.json")
                        if not manifest.exists():
                            _json(manifest, lineage)
                        refs = [ref for ref in refs if ref["source_role"] != "native"] + [dict(
                            path=str(merged), sha256=digest, source_role="native", original_ref=lineage,
                            native_update_receipt=dict(path=str(manifest), sha256=sha(manifest)))]
                        all_dates.update(date for date in rows if date <= target)
            if not all_dates:
                raise QfqGateError(f"HISTORY_SOURCE_WINDOW_EMPTY:{code}")
            start = min(all_dates)
            result[code] = dict(raw_files=refs, raw_resolution=HISTORY_RESOLUTION,
                history_start_date=start, history_end_date=max(all_dates), compute_start_date=start, required_output_start_date=start,
                publish_roles=["selector", "backtest"], warmup_records=0,
                warmup_policy="FULL_BOUND_OBSERVED_HISTORY_ORIGINAL_ENGINE",
                history_extension=True, source_config=source_ref,
                source_policy=config["source_policy"], accepted_evidence=config["accepted_evidence"])
    finally:
        for archive in opened.values():
            archive.close()
    return result


def existing_day_files(tdx_root: Path) -> list[tuple[str, Path]]:
    # Reuse the current Mac authority universe. The legacy Windows driver's
    # BJ-prefix table only accepts 8/9 and would omit existing 430xxx BJ files.
    from ops.macos_research_panel_daily import _a_day_files
    return [(path.stem[2:] + "." + path.stem[:2].upper(), path) for path in _a_day_files(tdx_root)]


def raw_bindings(tdx_root: Path, driver, binding_file: Path, *, required_start: dict[str, int] | None = None, target: int | None = None,
                 quarantine_eligible: dict | None = None, history_extension: dict | None = None,
                 retained_history: dict | None = None,
                 _exclude_codes: set[str] | None = None) -> dict[str, dict]:
    """Bind existing archive + current .day, never collect a second history.

    Optional explicit archive bindings are required where the daily cache is
    only a tail. Their per-file hashes are verified; conflicting overlaps are
    rejected by the full-history stage.
    """
    if history_extension is not None or retained_history is not None:
        historical = history_raw_bindings(history_extension or retained_history, binding_file, driver, target or 99991231,
                                         current_tdx_root=tdx_root if retained_history is not None else None)
        # The research-history set is an addition, never a mask for healthy
        # current members outside that set. Their original default gates apply.
        current = raw_bindings(tdx_root, driver, binding_file, required_start=required_start,
                               target=target, quarantine_eligible=quarantine_eligible,
                               _exclude_codes=set(historical))
        return {**current, **historical}
    supplied = json.loads(binding_file.read_text()) if binding_file.is_file() else {}
    archive = None
    if supplied.get("archive"):
        if supplied.get("overlap_policy") != "ARCHIVE_AUTHORITATIVE_CURRENT_POSTFIX_V1":
            raise QfqGateError("RAW_ARCHIVE_OVERLAP_POLICY_UNBOUND")
        archive = zipfile.ZipFile(_source(supplied["archive"], owner="original native TDX archive"))
    members = {name.replace("\\", "/").lower(): name for name in archive.namelist()} if archive else {}
    result = {}
    for code, current in existing_day_files(tdx_root):
        if code in (_exclude_codes or set()):
            continue
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
    if not result and _exclude_codes is None:
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
                     history_extension: dict | None = None, retained_history: dict | None = None,
                     **query_options) -> dict:
    root = input_path(data_root).parent
    sync_ref, eligible, floor = original_sync_contract(tdx_root, target)
    for code, status in eligible.items():
        if not status.get("path") or not status.get("source_sha256_after") or sha(Path(status["path"])) != status["source_sha256_after"]:
            raise QfqGateError(f"ORIGINAL_QUARANTINE_RAW_IDENTITY_DRIFT:{code}")
    archive_file = root / "qfq_raw_history_binding.json"
    archive_config = json.loads(archive_file.read_text()) if archive_file.is_file() else {}
    legacy_ref = archive_config.get("legacy_preservation_policy")
    legacy = legacy_preservation(legacy_ref)
    legacy_codes = set(legacy.get("codes", []))
    summary = json.loads(Path(sync_ref["path"]).read_text())
    markets = {0: "SZ", 1: "SH", 2: "BJ"}
    current_codes = {str(r["symbol"]).zfill(6) + "." + markets[int(r["market"])]
                     for r in summary.get("symbol_reconciliation", []) + summary.get("target_keys", [])}
    # A later target membership can change. Such a code must meet the normal
    # raw/factor gates, and cannot use this old non-target exception.
    legacy_codes = (legacy_codes & set(required_start or {})) - current_codes
    # Defensive market boundary also applies to manual first-generation callers.
    required_start = {c: d for c, d in (required_start or {}).items() if CODE.fullmatch(c) and c not in legacy_codes}
    bindings = raw_bindings(tdx_root, driver, root / "qfq_raw_history_binding.json", required_start=required_start,
                            target=target, quarantine_eligible=eligible, history_extension=history_extension, retained_history=retained_history)
    retained_codes = sorted(code for code, item in bindings.items() if retained_history is not None
                            and code in required_start and item.get("history_end_date", target) < target)
    bindings = {code: item for code, item in bindings.items() if code not in retained_codes}
    required_start = {code: date for code, date in required_start.items() if code not in retained_codes}
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
    if history_extension is None:
        metadata = collect_metadata(list(bindings), cache_root=factor_cache_root, target=target,
                                    client_factory=client_factory, force_refresh=force_refresh, **query_options)
    else:
        if client_factory is not None or force_refresh:
            raise QfqGateError("HISTORY_EXTENSION_IS_OFFLINE_ONLY")
        metadata = json.loads(_source(history_extension["adjustment_metadata"], owner="offline adjustment receipts").read_text())
        gaps = [dict(ts_code=code, reason="OFFLINE_ADJUSTMENT_HISTORY_COVERAGE_UNBOUND") for code, item in bindings.items()
                if not history_event_coverage_bound(metadata.get("symbols", {}).get(code, {}), item["history_start_date"], target)]
        if gaps:
            _json(root / "qfq_input_gaps.json", dict(asof_date=target, missing=gaps))
            raise QfqGateError(f"HISTORY_ADJUSTMENT_COVERAGE_INCOMPLETE:{len(gaps)}")
    fallback_file = root / "tdx_official_adjustment_fallback.json"
    unsupported = {code: bindings[code] for code, row in metadata["symbols"].items()
                   if code in bindings and not bindings[code].get("raw_binding_error") and row.get("status") == "UNSUPPORTED_MARKET"}
    if unsupported and history_extension is None:
        from ops.research_panel_tdx_adjustment_inputs import build_fallback
        fallback = build_fallback(root, unsupported, target, refresh_stale_capture=True)
    else:
        fallback = json.loads(fallback_file.read_text()) if fallback_file.is_file() else {}
    sources, symbols, missing = {sync_ref["path"]: sync_ref}, {}, []
    if history_extension is not None:
        for ref in [history_extension["binding_ref"], history_extension["source_config"], history_extension["source_policy"],
                    history_extension["adjustment_metadata"], *history_extension["archive_refs"], *history_extension["accepted_evidence"]]:
            sources[ref["path"]] = ref
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
        response_scope = None
        if receipt["status"] in ("OK", "EMPTY"):
            ref = receipt["response"]
            events, response_scope = _full_provider_response_events(receipt, code, target, binding["compute_start_date"], metadata)
            sources[ref["path"]] = ref
            method = "FUTU_GET_REHAB_AFFINE"
        else:
            item = fallback.get("symbols", {}).get(code, {})
            # Official TDX terms may cover Futu-unsupported symbols only when
            # the original source/category and conversion decision are bound.
            if (fallback.get("asof_date") != target or item.get("event_coverage_complete") is not True
                    or item.get("unsupported_categories") != [] or not item.get("conversion_receipt")
                    or "events" not in item or not item.get("source_files")
                    or (history_extension is not None and not history_event_coverage_bound(item, binding["history_start_date"], target))):
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
        if response_scope is not None:
            symbols[code]["provider_response_scope"] = response_scope
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
    if legacy_ref:
        snapshot["source_files"].append(legacy_ref)
        snapshot["legacy_preservation_policy"] = legacy_ref
        snapshot["legacy_preservation_codes"] = sorted(legacy_codes)
        snapshot["original_target_codes"] = sorted(current_codes)
    snapshot.update(quarantine_symbols=quarantine, original_quarantine_eligible=eligible, accepted_target_date_floor=floor)
    if retained_history is not None:
        snapshot["history_retention_binding"] = retained_history
        snapshot["retained_history_codes"] = retained_codes
    if history_extension is not None:
        snapshot["history_extension"] = history_extension["binding_ref"]
    snapshot["revision"] = canonical_sha(snapshot)
    path = input_path(data_root)
    existing = json.loads(path.read_text()) if path.is_file() else {}
    if existing.get("revision") == snapshot["revision"]:
        return existing
    snapshot["observed_at"] = metadata.get("completed_at") or metadata["finished_at"]
    immutable = root / "adjustment_snapshots" / (canonical_sha(snapshot) + ".json")
    if not immutable.exists():
        _json(immutable, snapshot)
    _json(path, snapshot)
    return snapshot
