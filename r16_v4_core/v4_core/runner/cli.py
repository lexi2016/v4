"""Unified single-directory CLI runner with --step ingest, 6-slot execution_ref & strict SSE completion gate."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import plistlib
import sys
import time
from typing import Callable
import urllib.request
import uuid
from zoneinfo import ZoneInfo

from v4_core.config import V4Config, assert_disk_space
from v4_core.ingest.daily_ingest import ingest_trade_date
from v4_core.runner.dispatch import dispatch_window
from v4_core.runner.review_inputs import await_linked_observation
from v4_core.runner.schedule import (
    MAIN_STAGES, at_time, dispatch_evidence_deadline, read_dispatch_inputs, wait_for_dispatch_evidence,
)
from v4_core.runner.slots import SIX_SLOT_DEFS, run_slot
from v4_core.runner.state import WriterBusy, WriterLease, writer_lease
from v4_core.qfq.engine import MissingAdjustmentFactorError, rebuild_qfq_for_date
from v4_core.storage.db import V4Store, normalize_iso_date
from v4_core.strategies.selection_groups import merge_selection_groups
from v4_core.strategies.top200 import build_daily_top200
from v4_core.strategies.workbench_score import score_symbol_from_bars


BEIJING = ZoneInfo("Asia/Shanghai")
DAILY_WINDOW_GRACE_SECONDS = 120
DAILY_WINDOWS = dict(sorted({
    **{
        point: ("slot_3_intraday_stage", "main_stage")
        for point in MAIN_STAGES
    },
    (9, 25): ("slot_2_preopen_pool_freeze", "main_preopen"),
    (15, 0): ("slot_3_intraday_stage", "main_stage7"),
    (15, 40): ("slot_4_a_share_daily", "source_check"),
    (16, 10): ("slot_4_a_share_daily", "a_daily"),
    (17, 20): ("slot_5_hk_and_evening", "hk_ingest"),
    (17, 30): ("slot_5_hk_and_evening", "hk_cache_write"),
    (18, 0): ("slot_5_hk_and_evening", "hk_cache_read"),
    (19, 0): ("slot_5_hk_and_evening", "evening"),
    (21, 15): ("slot_6_review_and_maint", "review"),
}.items()))


class EmptyPipelineOutputError(RuntimeError):
    """Raised when a pipeline step produces 0 records — never silently report DONE or emit SSE."""


def generate_single_plist(app_root: Path, python_bin: str, label: str = "com.lexi.v4core.api", port: int = 8873) -> bytes:
    """Generate the single-directory KeepAlive API launchd plist."""
    payload = {
        "Label": label,
        "ProgramArguments": [python_bin, "-m", "v4_core", "serve", "--port", str(port)],
        "WorkingDirectory": str(app_root.resolve()),
        "EnvironmentVariables": {
            "PYTHONPATH": str(app_root.resolve()),
            "V4_CORE_HOME": str((app_root / "v4_data").resolve()),
        },
        "RunAtLoad": True,
        "KeepAlive": True,
    }
    return plistlib.dumps(payload)


def generate_daily_scheduler_plist(
    app_root: Path,
    python_bin: str,
    label: str = "com.lexi.v4core.daily",
    schedules: list[tuple[int, int]] | None = None,
    tdx_dir: Path | None = None,
    *,
    factors_json: Path | None = None,
    selections_json: Path | None = None,
    hk_bars_json: Path | None = None,
    evidence_dir: Path | None = None,
) -> bytes:
    """Generate the single-directory 6-slot natural daily schedule launchd plist."""
    windows = list(DAILY_WINDOWS) if schedules is None else schedules
    if not windows or len(windows) != len(set(windows)) or any(point not in DAILY_WINDOWS for point in windows):
        raise ValueError("Daily plist schedules must be distinct configured windows")
    root = app_root.resolve()
    env_vars = {
        "PYTHONPATH": str(root),
        "V4_CORE_HOME": str(root / "v4_data"),
        "TZ": "Asia/Shanghai",
    }
    if tdx_dir is not None:
        env_vars["V4_TDX_DIR"] = str(Path(tdx_dir).resolve())
    for key, path in (
        ("V4_FACTORS_JSON", factors_json),
        ("V4_SELECTIONS_JSON", selections_json),
        ("V4_HK_BARS_JSON", hk_bars_json),
        ("V4_R16_INPUT_DIR", evidence_dir),
    ):
        if path is not None:
            env_vars[key] = str(Path(path).resolve())
    payload = {
        "Label": label,
        "ProgramArguments": [python_bin, "-m", "v4_core", "run-slot", "--scheduled"],
        "WorkingDirectory": str(root),
        "EnvironmentVariables": env_vars,
        "StartCalendarInterval": [{"Hour": h, "Minute": m} for h, m in windows],
    }
    return plistlib.dumps(payload)


def notify_sse_completed(api_url: str, trade_date: str, summary: dict) -> bool:
    """Notify live 8873 API to broadcast workbench_completed over SSE with exact workbench lineage."""
    body = json.dumps(
        {"event": "workbench_completed", "data": {"source_date": trade_date, "trade_date": trade_date, **summary}},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{api_url.rstrip('/')}/api/v4/research/events/publish",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


def _load_selections_payload(trade_date: str, raw: object) -> list[dict[str, str]]:
    if isinstance(raw, list):
        return [
            {
                "trade_date": str(item.get("trade_date", trade_date)),
                "symbol": str(item["symbol"]),
                "selection_group": str(item.get("selection_group", "192")),
                "display_name": str(item.get("display_name") or item.get("name") or ""),
            }
            for item in raw
            if isinstance(item, dict) and "symbol" in item
        ]
    if isinstance(raw, dict):
        names_map = raw.get("names") if isinstance(raw.get("names"), dict) else {}
        merged = merge_selection_groups(list(raw.get("192", [])), list(raw.get("backtest", [])))
        return [
            {
                "trade_date": trade_date,
                "symbol": sym,
                "selection_group": grp,
                "display_name": str(names_map.get(sym, "")),
            }
            for sym, grp in merged.items()
        ]
    raise ValueError("Unsupported selections JSON format")


def _bind_scheduled_selections(cfg: V4Config, date: str, source: Path) -> None:
    raw = json.loads(source.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        raw = [row for row in raw if isinstance(row, dict) and
               normalize_iso_date(str(row.get("trade_date", ""))) == date]
    elif isinstance(raw, dict) and normalize_iso_date(str(raw.get("trade_date", ""))) == date:
        raw = {**raw, "trade_date": date}
    else:
        raise ValueError("Selection input is not bound to this scheduled trading date")
    rows = _load_selections_payload(date, raw)
    if not rows:
        raise ValueError("No selections bound to this scheduled trading date")
    for row in rows:
        row["trade_date"] = date
    V4Store(cfg.db_path).upsert_workbench_selections(rows)


def _has_receipt(path: Path) -> bool:
    try:
        return path.stat().st_size > 0
    except FileNotFoundError:
        return False


def run_scheduled_window(
    cfg: V4Config,
    observed_at: datetime,
    *,
    tdx_dir: Path | None = None,
    bars_json: Path | None = None,
    factors_json: Path | None = None,
    hk_bars_json: Path | None = None,
    selections_json: Path | None = None,
    sse_notifier: Callable[[str, dict], bool] | None = None,
    evidence_dir: Path | None = None,
    completion_clock: Callable[[], datetime] | None = None,
    wait_for_deadlines: bool = False,
    poll_sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Bind the current Beijing window and retain one receipt per scheduled instant."""
    if observed_at.utcoffset() is None:
        raise ValueError("Scheduled window requires an aware datetime")
    if wait_for_deadlines and completion_clock is None:
        raise ValueError("In-slot evidence waits require a progressing completion clock")
    local = observed_at.astimezone(BEIJING)
    date = local.date().isoformat()
    receipt_dir = cfg.logs_dir / "daily_windows"
    points = [
        (local.replace(hour=hour, minute=minute, second=0, microsecond=0), slot, phase)
        for (hour, minute), (slot, phase) in DAILY_WINDOWS.items()
    ]
    passed = [(start, slot, phase) for start, slot, phase in points if start <= local]
    earlier_unobserved = [
        start.strftime("%H:%M") for start, _, _ in passed
        if (local - start).total_seconds() > DAILY_WINDOW_GRACE_SECONDS
        and not _has_receipt(receipt_dir / f"{date}_{start:%H%M}.jsonl")
    ]
    binding = {"trade_date": date, "observed_at": local.isoformat(),
               "unobserved_earlier_windows": earlier_unobserved}
    if not passed or (local - passed[-1][0]).total_seconds() > DAILY_WINDOW_GRACE_SECONDS:
        return {**binding, "window": local.strftime("%H:%M"), "schedule_status": "NO_DUE_WORKLOADS",
                "reason": "OUTSIDE_CONFIGURED_WINDOW_GRACE"}
    start, slot, phase = passed[-1]
    delay = (local - start).total_seconds()
    binding.update(window=start.strftime("%H:%M"), scheduled_for=start.isoformat(), delay_seconds=delay,
                   timing_status="ON_TIME" if delay < 60 else "LATE_DISPATCH", slot_id=slot, phase=phase)
    cfg.ensure_dirs()
    receipt_dir.mkdir(exist_ok=True)
    receipt_path = receipt_dir / f"{date}_{start:%H%M}.jsonl"
    with receipt_path.open("a+", encoding="utf-8") as receipt:
        try:
            fcntl.flock(receipt, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {**binding, "schedule_status": "ALREADY_RUNNING"}
        receipt.seek(0)
        if receipt.read(1):
            return {**binding, "schedule_status": "ALREADY_ATTEMPTED"}

        def persist(status: str, **detail: object) -> dict:
            result = {**binding, "schedule_status": status, **detail}
            receipt.write(json.dumps(result, ensure_ascii=False) + "\n")
            receipt.flush()
            os.fsync(receipt.fileno())
            return result

        try:
            with writer_lease(cfg.data_dir, cfg.logs_dir, f"{date}/{start:%H:%M}/{phase}") as lease:
                persist("RUNNING")
                try:
                    current = completion_clock or (lambda: local)
                    if wait_for_deadlines:
                        main = MAIN_STAGES.get((start.hour, start.minute))
                        if main:
                            deadline = at_time(start, main.tasks[-1].verify_at)
                            remaining = (deadline - current()).total_seconds()
                            while remaining > 0:
                                poll_sleep(min(remaining, 60))
                                remaining = (deadline - current()).total_seconds()
                    root = evidence_dir or _environment_path("V4_R16_INPUT_DIR")
                    if wait_for_deadlines:
                        inputs, inputs_gap, finished = wait_for_dispatch_evidence(root, start, phase, current, poll_sleep)
                    else:
                        inputs, inputs_gap = read_dispatch_inputs(root, date)
                        finished = current()
                    if finished.utcoffset() is None:
                        raise ValueError("Completion clock requires an aware datetime")
                    completed_at = finished.astimezone(BEIJING)
                    if completed_at < local or completed_at.date() != local.date():
                        raise ValueError("Completion clock falls outside the dispatched Beijing date")
                    def run_a_pipeline() -> dict:
                        try:
                            selected = selections_json or _environment_path("V4_SELECTIONS_JSON")
                            if selected is not None:
                                _bind_scheduled_selections(cfg, date, selected)
                            return {
                                **run_pipeline(
                                    cfg, date, "all", lease=lease, include_hk=False, source_ingest=False,
                                    sse_notifier=sse_notifier,
                                ),
                                "status": "DONE",
                            }
                        except (MissingAdjustmentFactorError, EmptyPipelineOutputError, ValueError) as exc:
                            return {"status": "CANNOT_CONFIRM", "reason": str(exc)}

                    wait_for_observation = None
                    if wait_for_deadlines and root is not None and phase == "evening":
                        deadline = dispatch_evidence_deadline(start, phase)

                        def wait_for_observation(hourly: dict) -> dict:
                            nonlocal completed_at
                            observation, finalized = await_linked_observation(cfg, root, hourly, deadline, current, poll_sleep)
                            completed_at = finalized.astimezone(BEIJING)
                            return observation

                    status, workload, paired = dispatch_window(
                        cfg, start, completed_at, phase, slot, lease, inputs=inputs, inputs_gap=inputs_gap,
                        run_slot=run_slot, hk_bars_json=hk_bars_json, run_a_pipeline=run_a_pipeline,
                        wait_for_observation=wait_for_observation,
                    )
                    return persist(status, workload=workload, paired_workloads=paired,
                                   evidence_observed_through=completed_at.isoformat())
                except Exception as exc:
                    persist("FAILED", error=str(exc))
                    raise
        except WriterBusy as exc:
            return {**binding, "schedule_status": "WRITER_BUSY", "reason": str(exc)}


def _environment_path(key: str) -> Path | None:
    value = os.environ.get(key)
    return Path(value) if value else None


def materialize_workbench_for_date(
    store: V4Store,
    trade_date: str,
    *,
    selection_groups: dict[str, str] | None = None,
) -> list[dict]:
    """Score all selected symbols for trade_date using snapshot-isolated QFQ bars."""
    selections = selection_groups if selection_groups is not None else store.get_workbench_selections(trade_date)
    if not selections:
        raise EmptyPipelineOutputError(
            f"No workbench_selections found for {trade_date}; refusing to emit workbench_completed with 0 rows"
        )
    selection_names = store.get_workbench_selection_names(trade_date)
    scored_rows = []
    for symbol, group in sorted(selections.items()):
        bars = store.get_symbol_bars("A", symbol, table="qfq_bars", limit=None, asof_date=trade_date)
        row = score_symbol_from_bars(trade_date, symbol, group, bars)
        resolved_name = selection_names.get(symbol) or store.resolve_security_name(trade_date, symbol)
        if resolved_name:
            detail = json.loads(row["detail_json"])
            detail["display_name"] = resolved_name
            row["detail_json"] = json.dumps(detail, ensure_ascii=False)
        scored_rows.append(row)
    store.save_workbench_scores(trade_date, scored_rows)
    return scored_rows


def run_pipeline(cfg: V4Config, trade_date: str, step: str, *, lease: WriterLease | None = None, **options) -> dict:
    """Run the established pipeline under the same writer as scheduled slots."""
    guard = nullcontext(lease) if lease else writer_lease(cfg.data_dir, cfg.logs_dir, f"{trade_date}/{step}")
    with guard:
        return _run_pipeline(cfg, trade_date, step, **options)


def _run_pipeline(
    cfg: V4Config,
    trade_date: str,
    step: str,
    *,
    factor_map: dict[str, dict[str, float]] | None = None,
    selection_groups: dict[str, str] | None = None,
    allow_unit_factors: bool = False,
    sse_notifier: Callable[[str, dict], bool] | None = None,
    tdx_dir: Path | None = None,
    bars_json: Path | None = None,
    factors_json: Path | None = None,
    hk_bars_json: Path | None = None,
    security_master_json: Path | None = None,
    include_hk: bool = True,
    source_ingest: bool = True,
) -> dict:
    cfg.ensure_dirs()
    free_gib = assert_disk_space(cfg.data_dir, cfg.min_free_gib)
    store = V4Store(cfg.db_path)
    run_id = f"{trade_date}-{step}-{uuid.uuid4().hex[:8]}"
    summary: dict = {"trade_date": trade_date, "step": step, "free_gib": free_gib, "sse_notified": False}

    eff_tdx = tdx_dir or (Path(os.environ["V4_TDX_DIR"]) if os.environ.get("V4_TDX_DIR") else None)
    eff_bars = bars_json or (Path(os.environ["V4_BARS_JSON"]) if os.environ.get("V4_BARS_JSON") else None)
    eff_factors = factors_json or (Path(os.environ["V4_FACTORS_JSON"]) if os.environ.get("V4_FACTORS_JSON") else None)
    eff_hk = (hk_bars_json or _environment_path("V4_HK_BARS_JSON")) if include_hk else None
    eff_sm = security_master_json or (Path(os.environ["V4_SECURITY_MASTER_JSON"]) if os.environ.get("V4_SECURITY_MASTER_JSON") else None)
    has_ingest_source = any(x is not None for x in (eff_tdx, eff_bars, eff_factors, eff_hk, eff_sm))

    store.log_task_run(run_id, trade_date, step, "RUNNING", summary)
    try:
        if source_ingest and (step == "ingest" or (step == "all" and has_ingest_source)):
            ingest_res = ingest_trade_date(
                store,
                trade_date,
                tdx_dir=eff_tdx,
                bars_json=eff_bars,
                factors_json=eff_factors,
                hk_bars_json=eff_hk,
                security_master_json=eff_sm,
            )
            summary["ingest"] = ingest_res
            if ingest_res["db_a_share_bar_count"] == 0:
                raise EmptyPipelineOutputError(
                    f"Ingest produced 0 A-share daily_bars for {trade_date}; refusing to report DONE"
                )

        if step in {"all", "qfq"}:
            qfq_res = rebuild_qfq_for_date(
                store, "A", trade_date, factor_map=factor_map, allow_unit_factors=allow_unit_factors
            )
            summary["qfq"] = qfq_res
            if qfq_res["symbols_processed"] == 0:
                raise EmptyPipelineOutputError(f"No A-share daily_bars found for {trade_date}; refusing to report DONE")

        if step in {"all", "top200"}:
            top = build_daily_top200(store, trade_date)
            summary["top200_count"] = len(top)
            if len(top) == 0:
                raise EmptyPipelineOutputError(f"Top200 produced 0 rows for {trade_date}; refusing to report DONE")

        if step in {"all", "workbench"}:
            scored = materialize_workbench_for_date(store, trade_date, selection_groups=selection_groups)
            summary["workbench_count"] = len(scored)
            if len(scored) == 0:
                raise EmptyPipelineOutputError(f"Workbench produced 0 rows for {trade_date}; refusing to emit SSE")
            persisted = store.get_workbench_scores(trade_date)
            from v4_core.api.routes_workbench import compute_workbench_lineage

            summary.update(compute_workbench_lineage(trade_date, persisted))

        if step in {"all", "workbench"} and summary.get("workbench_count", 0) > 0:
            if sse_notifier is not None:
                summary["sse_notified"] = bool(sse_notifier(trade_date, summary))
            else:
                summary["sse_notified"] = notify_sse_completed(
                    f"http://{cfg.api_host}:{cfg.api_port}", trade_date, summary
                )

        slot_rec = store.record_slot_execution(
            trade_date,
            "slot_4_a_share_daily",
            "A股日更全链(Ingest/QFQ/Top200/Workbench/SSE)",
            "15:40/16:10",
            "DONE",
            run_id,
            summary,
        )
        summary["execution_ref"] = slot_rec["execution_ref"]

        store.log_task_run(run_id, trade_date, step, "DONE", summary)
        summary_file = cfg.logs_dir / f"run_{trade_date}_{step}.json"
        summary_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary
    except Exception as exc:
        summary["error"] = str(exc)
        store.record_slot_execution(
            trade_date,
            "slot_4_a_share_daily",
            "A股日更全链(Ingest/QFQ/Top200/Workbench/SSE)",
            "15:40/16:10",
            "FAILED",
            run_id,
            {"error": str(exc), "step": step},
        )
        store.log_task_run(run_id, trade_date, step, "FAILED", summary)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v4_core", description="Pure modular V4 single-root CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Run idempotent pipeline steps for a trade date")
    p_run.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    p_run.add_argument("--step", choices=["all", "ingest", "qfq", "top200", "workbench"], default="all")
    p_run.add_argument("--home", default=None)
    p_run.add_argument("--allow-unit-factors", action="store_true")
    p_run.add_argument("--tdx-dir", default=None, help="Directory of 32-byte TDX .day files")
    p_run.add_argument("--bars-json", default=None, help="Optional JSON list of raw A-share bars")
    p_run.add_argument("--factors-json", default=None, help="Optional JSON list of {market,symbol,trade_date,adj_factor}")
    p_run.add_argument("--hk-bars-json", default=None, help="Optional JSON list of HK daily bars")
    p_run.add_argument("--security-master-json", default=None, help="Optional JSON list of security_master rows")
    p_run.add_argument("--selections-json", default=None, help="Optional JSON list or {192:[...],backtest:[...],names:{...}}")

    p_clean = sub.add_parser("cleanup", help="Prune old summary logs")
    p_clean.add_argument("--days", type=int, default=30)
    p_clean.add_argument("--home", default=None)

    p_serve = sub.add_parser("serve", help="Start modular 8873 API server")
    p_serve.add_argument("--port", type=int, default=8873)
    p_serve.add_argument("--home", default=None)

    p_slot = sub.add_parser("run-slot", help="Execute one or all of the 6 core slots and write execution_ref")
    p_slot.add_argument("--date", default=None)
    mode = p_slot.add_mutually_exclusive_group(required=True)
    mode.add_argument("--slot", choices=["all", *SIX_SLOT_DEFS.keys()])
    mode.add_argument("--scheduled", action="store_true",
                      help="Use the current configured Beijing window from the Daily plist")
    p_slot.add_argument("--home", default=None)
    p_slot.add_argument("--evidence-dir", type=Path, default=None)
    p_slot.add_argument("--tdx-dir", default=None)
    p_slot.add_argument("--bars-json", default=None)
    p_slot.add_argument("--factors-json", default=None)
    p_slot.add_argument("--hk-bars-json", default=None)
    p_slot.add_argument("--selections-json", default=None)
    p_slot.add_argument("--allow-unit-factors", action="store_true")

    p_plist = sub.add_parser("gen-plist", help="Emit single-directory API or daily scheduler plist")
    p_plist.add_argument("--app-root", required=True)
    p_plist.add_argument("--role", choices=["api", "daily"], default="api")
    p_plist.add_argument("--python", default=sys.executable)
    p_plist.add_argument("--tdx-dir", default=None)
    for source in ("factors-json", "selections-json", "hk-bars-json", "evidence-dir"):
        p_plist.add_argument("--" + source, type=Path, default=None)

    args = parser.parse_args(argv)
    if args.cmd == "run":
        cfg = V4Config.from_env(args.home)
        with writer_lease(cfg.data_dir, cfg.logs_dir, f"{args.date}/{args.step}") as lease:
            store = V4Store(cfg.db_path)
            if args.factors_json and args.step not in {"all", "ingest"}:
                store.upsert_adj_factors(json.loads(Path(args.factors_json).read_text(encoding="utf-8")))
            if args.selections_json:
                raw_sel = json.loads(Path(args.selections_json).read_text(encoding="utf-8"))
                store.upsert_workbench_selections(_load_selections_payload(args.date, raw_sel))
            res = run_pipeline(
                cfg,
                args.date,
                args.step,
                lease=lease,
                allow_unit_factors=args.allow_unit_factors,
                tdx_dir=Path(args.tdx_dir) if args.tdx_dir else None,
                bars_json=Path(args.bars_json) if args.bars_json else None,
                factors_json=Path(args.factors_json) if args.factors_json else None,
                hk_bars_json=Path(args.hk_bars_json) if args.hk_bars_json else None,
                security_master_json=Path(args.security_master_json) if args.security_master_json else None,
            )
        print(json.dumps(res, ensure_ascii=False))
        return 0
    if args.cmd == "run-slot":
        cfg = V4Config.from_env(args.home)
        if args.scheduled:
            if args.date or args.allow_unit_factors:
                p_slot.error("--scheduled uses the current Beijing date and authoritative factors")
            result = run_scheduled_window(
                cfg, datetime.now(BEIJING),
                tdx_dir=Path(args.tdx_dir) if args.tdx_dir else None,
                bars_json=Path(args.bars_json) if args.bars_json else None,
                factors_json=Path(args.factors_json) if args.factors_json else None,
                hk_bars_json=Path(args.hk_bars_json) if args.hk_bars_json else None,
                selections_json=Path(args.selections_json) if args.selections_json else None,
                evidence_dir=args.evidence_dir, completion_clock=lambda: datetime.now(BEIJING),
                wait_for_deadlines=True,
            )
            print(json.dumps(result, ensure_ascii=False))
            return 0
        date = args.date or datetime.now().strftime("%Y-%m-%d")
        with writer_lease(cfg.data_dir, cfg.logs_dir, f"{date}/{args.slot}") as lease:
            if args.selections_json:
                raw = json.loads(Path(args.selections_json).read_text(encoding="utf-8"))
                V4Store(cfg.db_path).upsert_workbench_selections(_load_selections_payload(date, raw))
            target_slots = list(SIX_SLOT_DEFS.keys()) if args.slot == "all" else [args.slot]
            results = {}
            for sid in target_slots:
                results[sid] = run_slot(
                    cfg,
                    date,
                    sid,
                    lease=lease,
                    tdx_dir=Path(args.tdx_dir) if args.tdx_dir else None,
                    bars_json=Path(args.bars_json) if args.bars_json else None,
                    factors_json=Path(args.factors_json) if args.factors_json else None,
                    hk_bars_json=Path(args.hk_bars_json) if args.hk_bars_json else None,
                    allow_unit_factors=args.allow_unit_factors,
                )
        print(json.dumps(results, ensure_ascii=False))
        return 0
    if args.cmd == "cleanup":
        cfg = V4Config.from_env(args.home)
        removed = V4Store.prune_old_logs(cfg.logs_dir, keep_days=args.days)
        print(json.dumps({"removed_logs": removed}))
        return 0
    if args.cmd == "gen-plist":
        if args.role == "api":
            data = generate_single_plist(Path(args.app_root), args.python)
        else:
            data = generate_daily_scheduler_plist(
                Path(args.app_root), args.python, tdx_dir=Path(args.tdx_dir) if args.tdx_dir else None,
                factors_json=args.factors_json, selections_json=args.selections_json, hk_bars_json=args.hk_bars_json,
                evidence_dir=args.evidence_dir,
            )
        sys.stdout.buffer.write(data)
        return 0
    if args.cmd == "serve":
        import uvicorn
        from v4_core.api.app import create_app

        cfg = V4Config.from_env(args.home)
        uvicorn.run(create_app(cfg), host=cfg.api_host, port=args.port)
        return 0
    return 1
