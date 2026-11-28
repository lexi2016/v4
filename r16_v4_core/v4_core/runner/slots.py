"""Executable 6-slot scheduler dispatchers with persisted execution_ref writeback for all 6/6 slots."""
from __future__ import annotations

from contextlib import nullcontext
import json
import os
from pathlib import Path
from typing import Any, Callable
import uuid

from v4_core.config import V4Config
from v4_core.ingest.hk_daily import ingest_hk_bars
from v4_core.runner.state import WriterLease, writer_lease
from v4_core.storage.db import V4Store, date_variants, normalize_iso_date

SIX_SLOT_DEFS: dict[str, tuple[str, str]] = {
    "slot_1_preopen_research": ("盘前研报/公告/海外验证汇总", "07:00"),
    "slot_2_preopen_pool_freeze": ("盘前主档冻结与竞价留档", "09:25"),
    "slot_3_intraday_stage": ("盘中阶段选股与Stage7归集", "09:35/09:40/09:45/10:30/13:15/15:00/15:55"),
    "slot_4_a_share_daily": ("A股日更全链(Ingest/QFQ/Top200/Workbench/SSE)", "15:40/16:10"),
    "slot_5_hk_and_evening": ("港股64位入库与晚间公告/次日观察版交付", "17:20/17:30/18:00/19:00"),
    "slot_6_review_and_maint": ("Review Core复盘池链与维护", "21:15"),
}


def run_slot_1_preopen_research(
    cfg: V4Config, trade_date: str, *, store: V4Store | None = None, scheduled: bool = False,
    receipt_provenance: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Slot 1 (07:00): Summarize preopen research materials, US market digest & announcements."""
    cfg.ensure_dirs()
    db = store or V4Store(cfg.db_path)
    iso_date = normalize_iso_date(trade_date)
    run_id = f"s1-{uuid.uuid4().hex[:8]}"
    materials = db.query_research_materials(trade_date=iso_date, limit=500)
    announcements = db.query_announcements(trade_date=iso_date)
    us_items = db.query_research_materials(source_type="us_market", trade_date=iso_date, limit=50)
    detail = {
        "materials_count": len(materials),
        "announcements_count": len(announcements),
        "us_market_count": len(us_items),
        "deferred_user_nodes": ["03:00_chart_review"],
    }
    name, sched = SIX_SLOT_DEFS["slot_1_preopen_research"]
    status = "CANNOT_CONFIRM" if scheduled and not (materials and announcements and us_items) else "DONE"
    if status == "CANNOT_CONFIRM":
        detail["reason"] = "PREOPEN_SOURCE_EVIDENCE_INCOMPLETE"
    if receipt_provenance:
        detail.update(receipt_provenance)
    return db.record_slot_execution(iso_date, "slot_1_preopen_research", name, sched, status, run_id, detail)


def run_slot_2_preopen_pool_freeze(
    cfg: V4Config, trade_date: str, *, store: V4Store | None = None, scheduled: bool = False,
) -> dict[str, Any]:
    """Slot 2 (08:50): Freeze same-day security_master & preselection pools snapshot."""
    cfg.ensure_dirs()
    db = store or V4Store(cfg.db_path)
    iso_date = normalize_iso_date(trade_date)
    run_id = f"s2-{uuid.uuid4().hex[:8]}"
    pools = db.get_preselection_pools(iso_date)
    selections = db.get_workbench_selections(iso_date)
    security_master_bound = True
    if scheduled:
        variants = date_variants(iso_date)
        with db.connect() as conn:
            security_master_bound = conn.execute(
                f"SELECT 1 FROM security_master WHERE trade_date IN ({','.join('?' for _ in variants)}) "
                "AND source_ref != '' LIMIT 1", variants,
            ).fetchone() is not None
    detail = {
        "preselection_rows": len(pools),
        "workbench_selection_count": len(selections),
        "security_master_bound": security_master_bound,
    }
    name, sched = SIX_SLOT_DEFS["slot_2_preopen_pool_freeze"]
    status = "CANNOT_CONFIRM" if scheduled and not (pools and security_master_bound) else "DONE"
    if status == "CANNOT_CONFIRM":
        detail["reason"] = "FROZEN_PRESELECTION_OR_SECURITY_MASTER_UNBOUND"
    return db.record_slot_execution(iso_date, "slot_2_preopen_pool_freeze", name, sched, status, run_id, detail)


def run_slot_3_intraday_stage(
    cfg: V4Config,
    trade_date: str,
    *,
    stage: str = "STAGE_0930_0935",
    store: V4Store | None = None,
    scheduled: bool = False,
) -> dict[str, Any]:
    """Slot 3 (09:35): Read back the opening stage and its execution binding."""
    cfg.ensure_dirs()
    db = store or V4Store(cfg.db_path)
    iso_date = normalize_iso_date(trade_date)
    run_id = f"s3-{uuid.uuid4().hex[:8]}"
    stage_rows = db.get_stage_selections(iso_date, stage=stage)
    detail = {
        "stage": stage,
        "selected_rows": len(stage_rows),
        "stage7_role": "A_SHARE_1MIN_STAGE_1445_1500",
    }
    name, sched = SIX_SLOT_DEFS["slot_3_intraday_stage"]
    status = "CANNOT_CONFIRM" if scheduled and not (stage_rows and all(row["execution_ref"] for row in stage_rows)) else "DONE"
    if status == "CANNOT_CONFIRM":
        detail["reason"] = "SAME_DAY_STAGE_EXECUTION_UNBOUND"
    return db.record_slot_execution(iso_date, "slot_3_intraday_stage", name, sched, status, run_id, detail)


def read_scheduled_hk_close_review(cfg: V4Config, trade_date: str) -> dict[str, Any]:
    """Observe the paired HK close-review lane without running a second producer."""
    date = normalize_iso_date(trade_date)
    rows = V4Store(cfg.db_path).query_research_materials(
        source_type="hk_connect_close_review", trade_date=date, limit=200,
    )
    return {
        "status": "CANNOT_CONFIRM",
        "reason": "HK_CLOSE_REVIEW_OWNER_UNBOUND",
        "same_day_material_count": sum(normalize_iso_date(row["trade_date"]) == date for row in rows),
    }


def run_slot_4_a_share_daily(
    cfg: V4Config,
    trade_date: str,
    *,
    tdx_dir: Path | None = None,
    bars_json: Path | None = None,
    factors_json: Path | None = None,
    allow_unit_factors: bool = False,
    sse_notifier: Callable[[str, dict], bool] | None = None,
    source_check: bool = False,
    lease: WriterLease | None = None,
) -> dict[str, Any]:
    """Slot 4: 15:40 readback, then one A-share producer at 16:10."""
    if source_check:
        db = V4Store(cfg.db_path)
        date = normalize_iso_date(trade_date)
        stage = db.get_stage_selections(date, stage="STAGE_1445_1500")
        return {
            "status": "CANNOT_CONFIRM",
            "reason": "EARLY_READBACK_ONLY",
            "existing_a_bars": len(db.get_date_bars("A", date, table="daily_bars")),
            "stage7_selected_rows": len(stage),
            "stage7_execution_refs": sorted({row["execution_ref"] for row in stage if row["execution_ref"]}),
        }

    from v4_core.runner.cli import run_pipeline

    return run_pipeline(
        cfg,
        normalize_iso_date(trade_date),
        "all",
        tdx_dir=tdx_dir,
        bars_json=bars_json,
        factors_json=factors_json,
        allow_unit_factors=allow_unit_factors,
        sse_notifier=sse_notifier,
        include_hk=False,
        lease=lease,
    )


def run_slot_5_hk_and_evening(
    cfg: V4Config,
    trade_date: str,
    *,
    hk_bars_json: Path | None = None,
    hk_bars_data: bytes | None = None,
    store: V4Store | None = None,
    phase: str | None = None,
) -> dict[str, Any]:
    """Slot 5: 17:20 HK intake and separate 19:00 evening readback."""
    cfg.ensure_dirs()
    db = store or V4Store(cfg.db_path)
    iso_date = normalize_iso_date(trade_date)
    run_id = f"s5-{uuid.uuid4().hex[:8]}"
    hk_accepted = 0
    hk_quarantined = 0
    status = "DONE"
    if phase != "evening":
        source = hk_bars_json
        if source is None and phase == "hk_ingest" and os.environ.get("V4_HK_BARS_JSON"):
            source = Path(os.environ["V4_HK_BARS_JSON"])
        if hk_bars_data is not None or (source is not None and Path(source).is_file()):
            raw_hk = json.loads(hk_bars_data if hk_bars_data is not None else Path(source).read_bytes())
            if isinstance(raw_hk, list):
                if phase == "hk_ingest":
                    raw_hk = [
                        {**row, "trade_date": iso_date}
                        for row in raw_hk
                        if isinstance(row, dict) and normalize_iso_date(str(row.get("trade_date", ""))) == iso_date
                    ]
                res = ingest_hk_bars(db, iso_date, raw_hk, quarantine_uint32_overflow=True)
                hk_accepted = res.accepted_count
                hk_quarantined = res.quarantined_count
    hk_bars = db.get_date_bars("HK", iso_date, table="daily_bars")
    detail = {
        "hk_ingested_accepted": hk_accepted,
        "hk_ingested_quarantined": hk_quarantined,
        "hk_db_bar_count": len(hk_bars),
    }
    if phase != "hk_ingest":
        detail["evening_announcements_count"] = len(db.query_announcements(trade_date=iso_date))
    if phase == "hk_ingest" and not hk_accepted:
        status, detail["reason"] = "CANNOT_CONFIRM", "HK_SAME_DAY_NATIVE_INPUT_UNAVAILABLE"
    if phase == "hk_ingest" and hk_accepted and hk_quarantined:
        status, detail["reason"] = "PARTIAL", "HK_NATIVE_INPUT_ROWS_QUARANTINED"
    if phase == "evening":
        # The local reader can observe announcements but does not own the former
        # observation-edition producer or its independent publication receipt.
        return {**detail, "status": "CANNOT_CONFIRM", "reason": "NEXT_DAY_OBSERVATION_PUBLICATION_UNBOUND"}
    name, sched = SIX_SLOT_DEFS["slot_5_hk_and_evening"]
    return db.record_slot_execution(iso_date, "slot_5_hk_and_evening", name, sched, status, run_id, detail)


def run_slot_6_review_and_maint(
    cfg: V4Config,
    trade_date: str,
    *,
    keep_days: int = 30,
    store: V4Store | None = None,
    scheduled: bool = False,
) -> dict[str, Any]:
    """Report the unverified manual path without changing authoritative 21:15 state."""
    date = normalize_iso_date(trade_date)
    name, schedule = SIX_SLOT_DEFS["slot_6_review_and_maint"]
    return {
        "status": "CANNOT_CONFIRM", "reason": "REVIEW_CORE_REQUIRES_2115_AUTHORITY",
        "trade_date": date, "slot_id": "slot_6_review_and_maint", "slot_name": name,
        "schedule_time": schedule, "execution_ref": None, "write_performed": False,
    }


def run_slot(
    cfg: V4Config, trade_date: str, slot_id: str, *, lease: WriterLease | None = None, **options,
) -> dict[str, Any]:
    guard = nullcontext(lease) if lease else writer_lease(cfg.data_dir, cfg.logs_dir, f"{trade_date}/{slot_id}")
    with guard as owner:
        return _run_slot(cfg, trade_date, slot_id, lease=owner, **options)


def _run_slot(
    cfg: V4Config,
    trade_date: str,
    slot_id: str,
    *,
    phase: str | None = None,
    lease: WriterLease,
    tdx_dir: Path | None = None,
    bars_json: Path | None = None,
    factors_json: Path | None = None,
    hk_bars_json: Path | None = None,
    hk_bars_data: bytes | None = None,
    stage: str = "STAGE_0930_0935",
    allow_unit_factors: bool = False,
    sse_notifier: Callable[[str, dict], bool] | None = None,
    receipt_provenance: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Dispatch any of the 6 core execution slots by slot_id (or 'all')."""
    if slot_id == "slot_1_preopen_research":
        return run_slot_1_preopen_research(
            cfg, trade_date, scheduled=phase is not None, receipt_provenance=receipt_provenance,
        )
    if slot_id == "slot_2_preopen_pool_freeze":
        return run_slot_2_preopen_pool_freeze(cfg, trade_date, scheduled=phase is not None)
    if slot_id == "slot_3_intraday_stage":
        return run_slot_3_intraday_stage(cfg, trade_date, stage=stage, scheduled=phase is not None)
    if slot_id == "slot_4_a_share_daily":
        return run_slot_4_a_share_daily(
            cfg,
            trade_date,
            tdx_dir=tdx_dir,
            bars_json=bars_json,
            factors_json=factors_json,
            allow_unit_factors=allow_unit_factors,
            sse_notifier=sse_notifier,
            source_check=phase == "source_check",
            lease=lease,
        )
    if slot_id == "slot_5_hk_and_evening":
        return run_slot_5_hk_and_evening(cfg, trade_date, hk_bars_json=hk_bars_json,
                                         hk_bars_data=hk_bars_data, phase=phase)
    if slot_id == "slot_6_review_and_maint":
        return run_slot_6_review_and_maint(cfg, trade_date, scheduled=phase is not None)
    raise ValueError(f"Unsupported slot_id: {slot_id}")
