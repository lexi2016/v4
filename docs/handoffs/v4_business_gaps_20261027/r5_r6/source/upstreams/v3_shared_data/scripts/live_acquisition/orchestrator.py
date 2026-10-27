"""Shared live A-share minute orchestration: priority selection + persistence.

Deterministic core only: no network bridge, no OpenD, no subprocess.
``run_source_priority`` freezes the exact Futu -> PyTDX -> QMT call order and
fallback rules. ``persist_stage_result`` validates everything before any write,
writes a deterministic UTF-8-SIG artifact CSV into a temporary directory, then
injects a trusted SourceSpec into the existing SafeRootStore (single writer
``v3_shared_data``; V3/V3.5 remain read-only consumers). Idempotency/conflict
come from the store; the temporary directory is always cleaned up.
"""
from __future__ import annotations

import csv
import base64
import hashlib
import json
import math
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Callable, Mapping

from shared_data.allowlist import AllowlistRegistry, SourceSpec
from shared_data.constants import CANNOT_CONFIRM, READY, READY_EMPTY
from shared_data.hashing import sha256_json
from shared_data.paths import validate_date
from shared_data.store import SafeRootStore

from .contracts import (
    ARTIFACT_FIELDS,
    NORMALIZED_MINUTE_FIELDS,
    SOURCE_PRIORITY,
    STAGE_WINDOWS,
    StageSourceResult,
    market_role,
)

OWNER = "v3_shared_data"
_TIME_FMT = "%Y-%m-%d %H:%M:%S"


def recover_partial_stage_minutes(store_root: Path | str, *, trade_date: str, stage_id: str,
                                  raw_root: Path | str, raw_run_id: str,
                                  raw_artifact_sha256: str, raw_manifest_sha256: str,
                                  raw_receipt_sha256: str, candidate_root: Path | str,
                                  candidate_current_sha256: str, canary_result: Path | str,
                                  canary_result_sha256: str, canary_stdout: Path | str,
                                  dry_run: bool = False) -> dict[str, Any]:
    """Revalidate a partial original plus one recorded late probe, then use the original store.

    READY concerns recovered bar values only; it is never a natural/PIT assertion.
    The original diagnostic list is preserved byte-for-byte in provenance.
    """
    from stage_center.raw_store import RawStore
    from stage_center.candidate_input import read_candidate_input
    from .pytdx_hq import _parse_payload, _bind_unstamped_rows
    from .futu_minute import aggregate_futu_minute_window_rows

    if stage_id != 'STAGE_1445_1500':
        raise ValueError('RECOVERY_STAGE_NOT_ALLOWED')
    def pinned(path, digest):
        path = Path(path)
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('RECOVERY_SOURCE_SHA_MISMATCH')
        return path
    root=Path(raw_root).resolve()
    verified=RawStore(root).verify_run(trade_date, stage_id, 'A_SHARE', raw_run_id)
    artifact=pinned(root/verified['artifact_relative'],raw_artifact_sha256)
    manifest_path=pinned(root/verified['manifest_relative'],raw_manifest_sha256)
    pinned(root/verified['receipt_relative'],raw_receipt_sha256)
    manifest=json.loads(manifest_path.read_bytes())
    if (verified['status']!='CANNOT_CONFIRM' or manifest.get('source_id')!='pytdx_hq'
        or manifest.get('source_status')!='CANNOT_CONFIRM' or manifest.get('temporal_cutoff_safe') is not False):
        raise ValueError('RECOVERY_PRIOR_IDENTITY_MISMATCH')
    candidate=read_candidate_input(candidate_root,trade_date,expected_current_sha256=candidate_current_sha256)
    evidence=manifest.get('source_evidence') or []
    if ('candidate_current_sha256='+candidate_current_sha256 not in evidence
        or 'candidate_run_id='+candidate.run_id not in evidence):
        raise ValueError('RECOVERY_CANDIDATE_BINDING_MISMATCH')
    prior=manifest.get('cannot_confirm')
    missing=manifest.get('missing_symbols')
    if not isinstance(prior,list) or not all(isinstance(x,str) for x in prior) or not isinstance(missing,list) or len(missing)!=1:
        raise ValueError('RECOVERY_PRIOR_DIAGNOSTICS_INVALID')
    coverage=[x for x in prior if x.startswith(('PyTDX HQ exact-date/window coverage incomplete:', 'PyTDX HQ batch coverage incomplete:'))]
    if len(coverage)!=2:raise ValueError('RECOVERY_COVERAGE_DIAGNOSTICS_AMBIGUOUS')
    report=json.loads(pinned(canary_result,canary_result_sha256).read_bytes())
    if (report.get('trade_date')!=trade_date or report.get('stage_id')!=stage_id or report.get('codes')!=missing
        or report.get('historical_late_observation') is not True or report.get('natural_verified') is not False
        or report.get('pit_certified') is not False or report.get('status')!='COMPLETED'
        or report.get('RESEARCH_ONLY') is not True
        or any(report.get(key) is not False for key in ('production_allowed','buy_gate_updated','orders_sent'))):
        raise ValueError('RECOVERY_CANARY_IDENTITY_MISMATCH')
    try:
        started=datetime.fromisoformat(report['started_at']);finished=datetime.fromisoformat(report['finished_at'])
        cutoff=datetime.strptime(trade_date+' '+STAGE_WINDOWS[stage_id][2],'%Y%m%d %H:%M:%S').replace(tzinfo=ZoneInfo('Asia/Shanghai'))
        if started.utcoffset() is None or finished.utcoffset() is None or not cutoff < started <= finished:
            raise ValueError('clock')
    except (KeyError,TypeError,ValueError):raise ValueError('RECOVERY_CANARY_CLOCK_INVALID') from None
    calls=report.get('calls')
    if not isinstance(calls,list) or len(calls)!=1 or calls[0].get('returncode')!=0:
        raise ValueError('RECOVERY_CANARY_CALL_INVALID')
    stdout=pinned(canary_stdout,calls[0].get('stdout_sha256')).read_text(encoding='utf-8')
    payload=_parse_payload(stdout)
    if (payload.get('errors')!=[] or payload.get('no_data_codes')!=[]
        or payload.get('requested_code_count')!=1 or payload.get('completed_code_count')!=1):
        raise ValueError('RECOVERY_CANARY_COVERAGE_INVALID')
    raw=payload.get('raw_rows')
    if not isinstance(raw,list) or any(not isinstance(row,dict) or row.get('code')!=missing[0] for row in raw):
        raise ValueError('RECOVERY_CANARY_ROWS_INVALID')
    recovered=aggregate_futu_minute_window_rows(trade_date,stage_id,_bind_unstamped_rows(trade_date,raw))
    recorded=report.get('result') or {}
    if len(recovered)!=1 or recorded.get('status')!='READ_OK' or recorded.get('rows')!=recovered:
        raise ValueError('RECOVERY_CANARY_AGGREGATION_MISMATCH')
    with artifact.open(encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream)
        if tuple(reader.fieldnames or ())!=ARTIFACT_FIELDS:raise ValueError('RECOVERY_HEADER_MISMATCH')
        original=list(reader)
    if len(original)!=manifest.get('row_count') or len(original)+1!=manifest.get('requested_rows'):
        raise ValueError('RECOVERY_PRIOR_COVERAGE_MISMATCH')
    rows=[]
    for old in original:
        row={key:old[key] for key in NORMALIZED_MINUTE_FIELDS}
        row['batch_index']=int(row['batch_index']);row['bar_count']=int(row['bar_count'])
        if row['temporal_cutoff_safe']!='True':raise ValueError('RECOVERY_ROW_TEMPORAL_INVALID')
        row['temporal_cutoff_safe']=True;rows.append(row)
    rows.extend(recovered);_validate_rows(rows,trade_date,STAGE_WINDOWS[stage_id][0],STAGE_WINDOWS[stage_id][2])
    codes=[str(row['code']) for row in rows]
    if (len(codes)!=len(candidate.codes) or len(set(codes))!=len(codes)
        or {c.split('.',1)[-1] for c in codes}!={c.split('.',1)[-1] for c in candidate.codes}):
        raise ValueError('RECOVERY_FROZEN_UNIVERSE_MISMATCH')
    for row in rows:
        try:
            prices=[float(row[k]) for k in ('last_price','open_price','high_price','low_price')]
            quantities=[float(row[k]) for k in ('turnover','volume')]
            if (not all(math.isfinite(x) and x>0 for x in prices) or not all(math.isfinite(x) and x>=0 for x in quantities)
                or prices[2]<max(prices[0],prices[1],prices[3]) or prices[3]>min(prices[0],prices[1],prices[2])
                or row['bar_count']<=0):raise ValueError('price')
        except (KeyError,TypeError,ValueError,OverflowError):raise ValueError('RECOVERY_ROW_VALUES_INVALID') from None
    prior_bytes=json.dumps(prior,ensure_ascii=False,separators=(',',':')).encode()
    provenance={'recovery_kind':'HISTORICAL_STAGE_RAW_RESUME','prior_artifact_sha256':raw_artifact_sha256,
        'prior_manifest_sha256':raw_manifest_sha256,'prior_receipt_sha256':raw_receipt_sha256,
        'candidate_current_sha256':candidate_current_sha256,'canary_result_sha256':canary_result_sha256,
        'canary_observed_at_utc':finished.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),
        'canary_stdout_sha256':calls[0]['stdout_sha256'],'prior_diagnostics_sha256':hashlib.sha256(prior_bytes).hexdigest(),
        'prior_diagnostics_base64url':base64.urlsafe_b64encode(prior_bytes).decode(),'resolved_coverage_diagnostics_base64url':base64.urlsafe_b64encode(json.dumps(coverage,ensure_ascii=False).encode()).decode(),
        'unresolved_prior_diagnostic_count':str(len(prior)-len(coverage)),'historical_backfill':'true',
        'pre_cutoff_capture_verified':'false','pit_certified':'false','source_merge_role':'SOURCE_ONLY','stage_selection_eligible':'false'}
    with tempfile.TemporaryDirectory(prefix='v3_stage_resume_') as folder:
        path=Path(folder)/'historical_stage.csv'
        # Preserve each original row's values while restoring frozen candidate order.
        by_code={str(row['code']).split('.',1)[-1]:row for row in original}
        row=recovered[0];missing_code=str(row['code']).split('.',1)[-1]
        by_code[missing_code]={'trade_date':trade_date,
            'bar_time':datetime.strptime(row['update_time'],_TIME_FMT).strftime('%H:%M:%S'),**row}
        with path.open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=ARTIFACT_FIELDS,lineterminator='\n')
            writer.writeheader()
            for code in candidate.codes:
                writer.writerow(by_code[code.split('.',1)[-1]])
        spec=SourceSpec(source_id='pytdx_hq',role=market_role('A_SHARE',stage_id),trade_date=trade_date,market='A_SHARE',
            stages=(stage_id,),cutoff_at=STAGE_WINDOWS[stage_id][2],source_path=path,
            required_columns=('trade_date','bar_time'),bar_time_column='bar_time',expected_row_count=len(candidate.codes),provenance=provenance)
        store=SafeRootStore(root=Path(store_root),allowlist=AllowlistRegistry(entries={(trade_date,spec.role):(spec,)}))
        return store.replay_file(owner=OWNER,trade_date=trade_date,role=spec.role,source_id=spec.source_id,
                                 stage_id=stage_id,dry_run=dry_run,historical_backfill=True,require_absent=True)


def run_source_priority(
    runners: Mapping[str, Callable[[], StageSourceResult]],
) -> tuple[StageSourceResult, list[StageSourceResult]]:
    """Call sources in frozen priority order until one is READ_OK.

    ``runners`` must map exactly the three fixed source ids (SOURCE_PRIORITY)
    to zero-argument callables returning StageSourceResult. A result whose
    ``source_id`` does not match its key is rejected. Returns ``(selected,
    results)``: results in call order; selected is the first READ_OK, otherwise
    the first result with rows, otherwise the first result. Never invents a
    result and never calls a runner twice.
    """
    if set(runners) != set(SOURCE_PRIORITY):
        raise ValueError(f"runners must map exactly {SOURCE_PRIORITY!r}, got {sorted(runners)!r}")
    results: list[StageSourceResult] = []
    for source_id in SOURCE_PRIORITY:
        result = runners[source_id]()
        if result.source_id != source_id:
            raise ValueError(f"runner {source_id!r} returned a result for {result.source_id!r}")
        results.append(result)
        if result.status == "READ_OK":
            break
    selected = next((result for result in results if result.status == "READ_OK"), None)
    if selected is None:
        selected = next((result for result in results if result.rows), None)
    if selected is None:
        selected = results[0]
    return selected, results


def persist_stage_result(
    store_root: Path | str,
    trade_date: str,
    stage_id: str,
    selected: StageSourceResult,
    dry_run: bool = False,
    *,
    market: str = "A_SHARE",
    historical_backfill: bool = False,
    expected_previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist one selected live stage result into the shared SafeRootStore.

    Fails closed (ValueError, before any write) on invalid date, unknown
    stage, malformed row (missing/extra keys, non-dict), update_time not on
    trade_date, or bar_time past the stage cutoff. A dry run validates and
    returns a preview but creates neither store_root nor any temporary file.

    The artifact CSV carries exactly the 21 ARTIFACT_FIELDS: trade_date and
    bar_time (time-of-day of each preserved row's update_time) prefixed to the
    exact 19 V3 values, which are never transformed. Nested manifest
    provenance carries v3_fidelity / v3_source_id / v3_display_name and is
    path-neutral.
    """
    store_root = Path(store_root)
    trade_date = validate_date(trade_date)
    window = STAGE_WINDOWS.get(stage_id)
    if window is None:
        raise ValueError(f"unknown stage {stage_id!r}")
    rows = _validate_rows(selected.rows, trade_date, window[0], window[2])
    role = market_role(market, stage_id)
    status = _derive_status(selected, rows)
    if dry_run:
        return {
            "dry_run": True,
            "status": status,
            "trade_date": trade_date,
            "stage_id": stage_id,
            "role": role,
            "source_id": selected.source_id,
            "row_count": len(rows),
        }

    temp_root = Path(tempfile.mkdtemp(prefix="v3_live_acq_"))
    try:
        source_path = temp_root / f"adapter_{selected.source_id}_{stage_id}.csv"
        _write_artifact(source_path, trade_date, rows)
        spec = SourceSpec(
            source_id=selected.source_id,
            role=role,
            trade_date=trade_date,
            market=market,
            stages=(stage_id,),
            cutoff_at=window[2],
            source_path=source_path,
            required_columns=("trade_date", "bar_time"),
            bar_time_column="bar_time",
            expected_input_sha256=None,
            expected_row_count=None,
            cannot_confirm=tuple(selected.cannot_confirm or ()),
            provenance={
                "v3_fidelity": selected.fidelity,
                "v3_source_id": selected.source_id,
                "v3_display_name": selected.display_name,
                "shared_market": market,
                "requested_code_count": str(selected.requested_code_count or len(rows)),
                "completed_code_count": str(selected.completed_code_count or len(rows)),
                "no_data_code_count": str(len(selected.no_data_codes)),
                "no_data_codes_sha256": sha256_json(sorted(selected.no_data_codes)),
                "name_dictionary_sha256": selected.name_dictionary_sha256,
            },
        )
        store = SafeRootStore(
            root=store_root,
            allowlist=AllowlistRegistry(entries={(trade_date, role): (spec,)}),
        )
        return store.replay_file(
            owner=OWNER,
            trade_date=trade_date,
            role=role,
            source_id=selected.source_id,
            stage_id=stage_id,
            historical_backfill=historical_backfill,
            expected_previous=expected_previous,
        )
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def _validate_rows(
    rows: list[Any], trade_date: str, window_start_at: str, cutoff_at: str
) -> list[dict[str, Any]]:
    """Validate the 19-field rows; returns the rows unchanged on success."""
    expected_keys = set(NORMALIZED_MINUTE_FIELDS)
    expected_day = datetime.strptime(trade_date, "%Y%m%d").strftime("%Y-%m-%d")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("live rows must be dicts")
        if set(row) != expected_keys:
            raise ValueError("live row must carry exactly the 19 NORMALIZED_MINUTE_FIELDS")
        parsed: dict[str, datetime] = {}
        for field in ("update_time", "window_start", "window_end"):
            try:
                parsed[field] = datetime.strptime(str(row[field] or ""), _TIME_FMT)
            except ValueError as error:
                raise ValueError(f"malformed {field} {row[field]!r}") from error
            if parsed[field].strftime("%Y-%m-%d") != expected_day:
                raise ValueError(f"{field} {row[field]!r} is not on trade_date {trade_date}")
        lower = datetime.strptime(f"{expected_day} {window_start_at}", _TIME_FMT) + timedelta(minutes=1)
        upper = datetime.strptime(f"{expected_day} {cutoff_at}", _TIME_FMT)
        if not lower <= parsed["window_start"] <= parsed["window_end"] <= upper:
            raise ValueError("row window falls outside the frozen stage interval")
        if parsed["update_time"] != parsed["window_end"]:
            raise ValueError("update_time must equal window_end for an aggregated row")
    return rows


def _derive_status(selected: StageSourceResult, rows: list[dict[str, Any]]) -> str:
    """Explicit status: READY only for READ_OK rows without evidence."""
    if selected.status != "READ_OK" or selected.cannot_confirm:
        return CANNOT_CONFIRM
    if not rows:
        return READY_EMPTY
    return READY


def _write_artifact(path: Path, trade_date: str, rows: list[dict[str, Any]]) -> None:
    """Deterministic UTF-8-SIG CSV: 21-field header, preserved row order."""
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(ARTIFACT_FIELDS)
        for row in rows:
            bar_time = datetime.strptime(row["update_time"], _TIME_FMT).strftime("%H:%M:%S")
            writer.writerow([trade_date, bar_time] + [row[field] for field in NORMALIZED_MINUTE_FIELDS])
