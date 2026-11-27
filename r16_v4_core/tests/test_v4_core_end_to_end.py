"""End-to-end & regression tests covering pure V4 contracts, live hold_score passthrough, UNKNOWN quarantine & manifest dedup."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import stat
import pytest
from fastapi.testclient import TestClient

from v4_core.api.app import create_app
from v4_core.api.routes_sse import EventBus
from v4_core.config import InsufficientDiskSpaceError, V4Config, assert_disk_space
from v4_core.ingest.a_share_tdx import TDX_DAY_STRUCT, ingest_a_share_bars, parse_tdx_day_bytes
from v4_core.ingest.hk_daily import UINT32_MAX, ingest_hk_bars
from v4_core.qfq.engine import MissingAdjustmentFactorError, rebuild_qfq_for_date
from v4_core.runner.cli import (
    EmptyPipelineOutputError,
    generate_daily_scheduler_plist,
    generate_single_plist,
    run_pipeline,
)
from v4_core.runner.safe_archive import (
    filter_safe_archive_paths,
    load_manifest_paths,
    load_manifest_records,
)
from v4_core.storage.db import V4Store
from v4_core.strategies.selection_groups import classify_name_change, merge_selection_groups
from v4_core.strategies.workbench_score import RULE_VERSION


def _cfg(tmp_path: Path) -> V4Config:
    cfg = V4Config(
        base_dir=tmp_path,
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data/v4.sqlite3",
        bars_dir=tmp_path / "data/bars",
        logs_dir=tmp_path / "logs",
        min_free_gib=0.01,
    )
    cfg.ensure_dirs()
    return cfg


def test_tdx_32byte_parse_and_a_share_ingest(tmp_path: Path):
    store = V4Store(tmp_path / "v4.sqlite3")
    raw_bytes = TDX_DAY_STRUCT.pack(20261124, 1000, 1080, 990, 1050, 12345678.0, 500000, 0)
    parsed = parse_tdx_day_bytes(raw_bytes, "600519.SH")
    assert parsed[0]["trade_date"] == "2026-11-24" and parsed[0]["close"] == 10.50

    batch = parsed + [
        {"symbol": "830001.BJ", "trade_date": "2026-11-24", "open": 5, "high": 5, "low": 5, "close": 5, "volume": 100, "amount": 500},
        {"symbol": "000001.SZ", "trade_date": "2026-11-24", "open": 0, "high": 10, "low": 9, "close": 9.5, "volume": 100, "amount": 950},
    ]
    summary = ingest_a_share_bars(store, "2026-11-24", batch, verified_exclusions={"830001.BJ"})
    assert (summary.excluded_count, summary.accepted_count, summary.quarantined_count) == (1, 1, 1)


def test_hk_03033_uint32_overflow_quarantined(tmp_path: Path):
    store = V4Store(tmp_path / "v4.sqlite3")
    hk_rows = [
        {"symbol": "00700.HK", "trade_date": "2026-11-24", "open": 400, "high": 410, "low": 398, "close": 408, "volume": 12_000_000, "amount": 4.8e9},
        {"symbol": "03033.HK", "trade_date": "2026-11-24", "open": 4.1, "high": 4.2, "low": 4.0, "close": 4.15, "volume": 5_645_792_859, "amount": 2.3e10},
    ]
    assert hk_rows[1]["volume"] > UINT32_MAX
    summary = ingest_hk_bars(store, "2026-11-24", hk_rows, quarantine_uint32_overflow=True)
    assert summary.accepted_count == 1 and summary.quarantined_count == 1


def test_qfq_asof_snapshot_isolation_000026_d24_unchanged_after_d25_rebuild(tmp_path: Path):
    cfg = _cfg(tmp_path)
    store = V4Store(cfg.db_path)
    store.upsert_daily_bars([
        {"market": "A", "symbol": "000026.SZ", "trade_date": "2026-11-24", "open": 22.0, "high": 22.5, "low": 21.8, "close": 22.35, "volume": 1000, "amount": 22350, "pre_close": 22.0},
        {"market": "A", "symbol": "000026.SZ", "trade_date": "2026-11-25", "open": 11.2, "high": 11.5, "low": 11.0, "close": 11.30, "volume": 2000, "amount": 22600, "pre_close": 11.175},
    ])
    with pytest.raises(MissingAdjustmentFactorError):
        rebuild_qfq_for_date(store, "A", "2026-11-24")

    store.upsert_adj_factors([
        {"market": "A", "symbol": "000026.SZ", "trade_date": "2026-11-24", "adj_factor": 1.0},
        {"market": "A", "symbol": "000026.SZ", "trade_date": "2026-11-25", "adj_factor": 2.0},
    ])
    rebuild_qfq_for_date(store, "A", "2026-11-24")
    rebuild_qfq_for_date(store, "A", "2026-11-25")

    d24_snap = store.get_date_bars("A", "2026-11-24", table="qfq_bars", asof_date="2026-11-24")
    assert len(d24_snap) == 1 and d24_snap[0]["close"] == 22.35
    d25_view_of_d24 = store.get_date_bars("A", "2026-11-24", table="qfq_bars", asof_date="2026-11-25")
    assert len(d25_view_of_d24) == 1 and d25_view_of_d24[0]["close"] == 11.175

    d24 = "2026-11-24"
    symbol = "000026.SZ"
    scalar_columns = ("pre_close", "pct_chg", "user_v1_sell_signal_daily")
    store.upsert_qfq_bars([{**d24_snap[0], "pre_close": 22.0, "pct_chg": 1.59, "user_v1_sell_signal_daily": 1}])
    rebuild_qfq_for_date(store, "A", d24)
    equivalent = store.get_symbol_bars("A", symbol, asof_date=d24)[0]
    assert [equivalent[column] for column in scalar_columns] == [22.0, 1.59, 1]

    legacy = {key: value for key, value in equivalent.items() if key not in scalar_columns}
    store.upsert_qfq_bars([{**legacy, "pct_chg": None}])
    expected = {**equivalent, "pct_chg": None}
    assert store.get_symbol_bars("A", symbol, asof_date=d24) == [expected]
    with pytest.raises(ValueError, match="QFQ_KB_PREFIX_CONFLICT"):
        store.upsert_qfq_bars([{**legacy, "pct_chg": 2.0}, {**legacy, "trade_date": "2026-11-23"}])
    assert store.get_symbol_bars("A", symbol, asof_date=d24) == [expected]

    # The original full runner cannot emit a new score or event when a
    # legacy rebuild would replace the OHLC underpinning the bound scalars.
    daily = store.get_date_bars("A", d24)[0]
    store.upsert_daily_bars([{**daily, "close": 22.4}])
    emitted = []
    with pytest.raises(ValueError, match="QFQ_KB_PREFIX_CONFLICT"):
        run_pipeline(cfg, d24, "all", selection_groups={symbol: "192"},
                     sse_notifier=lambda *args: emitted.append(args))
    assert store.get_symbol_bars("A", symbol, asof_date=d24) == [expected]
    assert not store.get_workbench_scores(d24)
    assert not emitted


def test_empty_db_fails_closed_and_plist_generation(tmp_path: Path):
    cfg = _cfg(tmp_path)
    with pytest.raises(EmptyPipelineOutputError):
        run_pipeline(cfg, "2026-11-24", "all")

    api_plist = generate_single_plist(tmp_path, "/usr/bin/python3")
    daily_plist = generate_daily_scheduler_plist(tmp_path, "/usr/bin/python3")
    assert b"com.lexi.v4core.api" in api_plist and b"serve" in api_plist
    assert b"com.lexi.v4core.daily" in daily_plist and b"StartCalendarInterval" in daily_plist


def test_strict_sse_gate_never_emits_workbench_completed_on_qfq_only_or_zero_workbench(tmp_path: Path):
    cfg = _cfg(tmp_path)
    store = V4Store(cfg.db_path)
    store.upsert_daily_bars([
        {"market": "A", "symbol": "000026.SZ", "trade_date": "2026-11-24", "open": 22.0, "high": 22.5, "low": 21.8, "close": 22.35, "volume": 1000, "amount": 22350, "pre_close": 22.0},
    ])
    store.upsert_adj_factors([
        {"market": "A", "symbol": "000026.SZ", "trade_date": "2026-11-24", "adj_factor": 1.0},
    ])

    emitted: list[dict] = []

    def _capture(dt: str, summary: dict) -> bool:
        emitted.append({"date": dt, "summary": summary})
        return True

    res_qfq = run_pipeline(cfg, "2026-11-24", "qfq", sse_notifier=_capture)
    assert res_qfq["sse_notified"] is False and len(emitted) == 0

    with pytest.raises(EmptyPipelineOutputError):
        run_pipeline(cfg, "2026-11-24", "all", sse_notifier=_capture)
    assert len(emitted) == 0


def test_api_active_8873_contract_parity_bootstrap_assets_and_live_hold_score_passthrough(tmp_path: Path):
    cfg = _cfg(tmp_path)
    store = V4Store(cfg.db_path)
    bars, factors = [], []
    for day in range(1, 25):
        dt = f"2026-11-{day:02d}"
        bars.append({"market": "A", "symbol": "605577.SH", "trade_date": dt, "open": 10 + day * 0.2, "high": 10.5 + day * 0.2, "low": 9.8 + day * 0.2, "close": 10.2 + day * 0.2, "volume": 100000, "amount": 1.2e8, "pre_close": 10.0 + day * 0.2})
        bars.append({"market": "A", "symbol": "002936.SZ", "trade_date": dt, "open": 20.0, "high": 21.0, "low": 19.5, "close": 20.8, "volume": 200000, "amount": 4.0e8, "pre_close": 20.0})
        factors.append({"market": "A", "symbol": "605577.SH", "trade_date": dt, "adj_factor": 1.0})
        factors.append({"market": "A", "symbol": "002936.SZ", "trade_date": dt, "adj_factor": 1.0})
    store.upsert_daily_bars(bars)
    store.upsert_adj_factors(factors)
    store.upsert_workbench_selections([
        {"trade_date": "2026-11-24", "symbol": "605577.SH", "selection_group": "both", "display_name": "龙版传媒"},
        {"trade_date": "2026-11-24", "symbol": "999999.SZ", "selection_group": "UNKNOWN", "display_name": "隔离样本"},
    ])

    panel_root = tmp_path / "research-panel"
    (panel_root / "workbench-host" / "dot" / "shell").mkdir(parents=True)
    (panel_root / "workbench.html").write_text("<html>wb</html>", encoding="utf-8")
    (panel_root / "related-reports.js").write_text("console.log('rr');", encoding="utf-8")
    (panel_root / "workbench-host" / "bootstrap.mjs").write_text("export const ok = true;", encoding="utf-8")
    (panel_root / "workbench-host" / "dot" / "shell" / "workbench.css").write_text("body{}", encoding="utf-8")

    bus = EventBus()
    app = create_app(cfg, bus=bus, research_panel_root=panel_root)
    client = TestClient(app)

    def _post_sse(trade_date: str, summary: dict) -> bool:
        return client.post(
            "/api/v4/research/events/publish",
            json={"event": "workbench_completed", "data": {"source_date": trade_date, **summary}},
        ).status_code == 200

    res = run_pipeline(cfg, "2026-11-24", "all", sse_notifier=_post_sse)
    assert res["top200_count"] == 2 and res["workbench_count"] == 2 and res["sse_notified"] is True

    # Bootstrap resources HTTP 200
    assert client.get("/research-panel/workbench.html").headers.get("cache-control") == "no-store"
    assert client.get("/research-panel/related-reports.js").status_code == 200
    assert client.get("/research-panel/workbench-host/bootstrap.mjs").status_code == 200
    assert client.get("/research-panel/workbench-host/dot/shell/workbench.css").status_code == 200

    # Quarantined UNKNOWN row keeps b23_entry=UNKNOWN & pb2_confirm=UNKNOWN, display_name preserved
    wb = client.get("/api/v4/research/workbench/days/2026-11-24").json()
    assert wb["rows"][0]["source_row"]["display_name"] == "龙版传媒"
    # Native scoring must expose the KB contract; monotone bars have no
    # confirmed N swings, so a numeric legacy structural score is incorrect.
    computed = wb["rows"][0]["hold_score"]
    assert computed["kb_hold_close_up"] is True
    assert computed["kb_hold_volume_ok"] is True
    assert computed["kb_hold_score"] is None
    assert computed["kb_hold_score_status"] == "PARTIAL_UNKNOWN"
    assert wb["rows"][0]["history_rates"]["input_rows"] == 24
    assert wb["rows"][1]["group_states"]["b23_entry"] == "UNKNOWN"
    assert wb["rows"][1]["group_states"]["pb2_confirm"] == "UNKNOWN"

    # Regression for R6 HTTP 500: live hold_score dict WITHOUT status/action keys MUST return HTTP 200 on list, chart & single-research
    live_dict = {"exact_score": 4, "band": "STRONG"}
    store.save_workbench_scores("2026-11-24", [{
        "trade_date": "2026-11-24",
        "symbol": "605577.SH",
        "selection_group": "192",
        "rule_version": RULE_VERSION,
        "score": 4.0,
        "action": "HOLD_OR_WATCH",
        "status": "READY",
        "detail_json": json.dumps({"display_name": "龙版传媒", "hold_score": live_dict}, ensure_ascii=False),
    }])
    wb2 = client.get("/api/v4/research/workbench/days/2026-11-24")
    k2 = client.get("/api/v4/research/workbench/days/2026-11-24/formula-daily-k/605577.SH")
    sr2 = client.get("/api/v4/research/workbench/days/2026-11-24/single-research/605577.SH")
    assert wb2.status_code == 200 and wb2.json()["rows"][0]["hold_score"] == live_dict
    assert k2.status_code == 200 and k2.json()["score"]["hold_score"] == live_dict
    assert sr2.status_code == 200 and sr2.json()["row"]["hold_score"] == live_dict


def _write_archive_group(root: Path, paths_by_role: dict[str, list[str]]) -> Path:
    roles = {}
    for role, relative_paths in paths_by_role.items():
        role_dir = root / role
        role_dir.mkdir()
        app_root = role_dir.resolve() / "app"
        entries = []
        for relative in sorted(relative_paths):
            path = app_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(relative)
            info = path.stat()
            entries.append({
                "kind": "file", "path": relative, "sha256": sha256(path.read_bytes()).hexdigest(),
                "size": info.st_size, "mode": f"{stat.S_IMODE(info.st_mode):04o}",
            })
        startup = role_dir / "startup-manifest.json"
        inventory = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        startup.write_text(json.dumps({
            "app_root": str(app_root),
            "application_inventory": {
                "entries": entries, "entry_count": len(entries), "aggregate_sha256": sha256(inventory).hexdigest(),
            },
            "app_files": [{"path": entry["path"], "sha256": entry["sha256"]} for entry in entries],
        }), encoding="utf-8")
        role_manifest = role_dir / "release-manifest.json"
        role_manifest.write_text(json.dumps({
            "role": role,
            "app_root": str(app_root),
            "startup_manifest": {"path": str(startup)},
        }), encoding="utf-8")
        roles[role] = {"path": str(role_manifest)}
    group_manifest = root / "group-manifest.json"
    group_manifest.write_text(json.dumps({"activation_status": "ACTIVE", "roles": roles}), encoding="utf-8")
    return group_manifest


def test_safe_archive_dedup_three_level_manifest_and_c_class_mixed_roots(tmp_path: Path):
    group_manifest = _write_archive_group(tmp_path, {
        "main": ["ops/launch_v4_macos_scheduler.sh"],
        "api": ["apps/api/v4_api/run.py"],
        "stage": ["ops/run_stage_center_nodes.py"],
    })
    assert len(load_manifest_records(group_manifest)) == 3
    protected = load_manifest_paths(group_manifest)
    c_roots = [
        "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/x.json",
        "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/workspace/v3_shared_data/.runtime/data/x.db",
    ]
    filtered = filter_safe_archive_paths(
        candidate_paths=c_roots + ["apps/api/v35_api/app.py"],
        git_tracked_paths=set(c_roots) | {"apps/api/v35_api/app.py"},
        active_manifest_paths=protected,
    )
    assert filtered["safe_to_archive"] == ["apps/api/v35_api/app.py"]
    assert len(filtered["skipped_protected_evidence"]) == 2
    assert classify_name_change("*ST某某", "某某") == ("NAME_CHANGED_ST_TRANSITION", True)
    assert merge_selection_groups(["A"], ["A", "B"]) == {"A": "both", "B": "backtest"}

    with pytest.raises(InsufficientDiskSpaceError):
        assert_disk_space(tmp_path, min_free_gib=999999.0)


def test_safe_archive_canonical_aliases_and_rollback_dependencies(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "code").mkdir()
    for name in ("clean.py", "active.py", "dirty.py", "restoration.py", "live-target.py", "dirty-target.py"):
        (repo / "code" / name).write_text(name)
    outside = tmp_path / "outside.py"
    outside.write_text("outside")
    evidence = repo / "legacy_three_roles_backup"
    evidence.mkdir()
    (evidence / "roles.tsv").write_text("required")
    (repo / "code" / "com.lexi.v4.api.plist").write_text("original")
    (repo / "code" / "rollback_to_legacy_three_roles.sh").write_text("original")
    external_backup = tmp_path / "legacy_three_roles_backup"
    external_backup.symlink_to(repo / "code", target_is_directory=True)
    for alias, target in {
        "active-link.py": repo / "code" / "active.py",
        "active_manifest.py": repo / "code" / "live-target.py",
        "dirty_manifest.py": repo / "code" / "dirty-target.py",
        "dirty-link.py": repo / "code" / "dirty.py",
        "backup-link.tsv": evidence / "roles.tsv",
        "outside-link.py": outside,
        "clean-link.py": repo / "code" / "clean.py",
        "loop.py": repo / "loop.py",
    }.items():
        (repo / alias).symlink_to(target)

    candidates = [
        "code/clean.py", "./code/active.py", "active-link.py", "dirty-link.py",
        "backup-link.tsv", "legacy_three_roles_backup/roles.tsv", "code/com.lexi.v4.api.plist",
        "code/rollback_to_legacy_three_roles.sh", "code/restoration.py", "outside-link.py",
        "clean-link.py", "loop.py", "code/../code/clean.py", "code\\clean.py",
        " code/clean.py ", str(outside), "untracked.py", "code/live-target.py", "code/dirty-target.py",
    ]
    proof = load_manifest_paths(_write_archive_group(tmp_path, {
        "api": ["code/active.py", "active_manifest.py"],
        "main": ["ops/main.py"],
        "stage": ["ops/stage.py"],
    }))
    filtered = filter_safe_archive_paths(
        candidates, set(candidates) - {"untracked.py"}, proof,
        dirty_git_paths={"code/dirty.py", "dirty_manifest.py"},
        rollback_dependencies={str(external_backup / "restoration.py")}, repo_root=repo,
    )
    assert filtered["safe_to_archive"] == ["code/clean.py"]
    assert filtered["skipped_active_manifest"] == ["./code/active.py", "active-link.py", "code/live-target.py"]
    assert filtered["skipped_dirty_git"] == ["dirty-link.py", "code/dirty-target.py"]
    assert filtered["skipped_not_in_git"] == ["untracked.py"]
    assert set(filtered["skipped_protected_evidence"]) == set(candidates[4:-3])
    # An unreadable canonical guard must not authorize an otherwise clean path.
    blocked = filter_safe_archive_paths(
        ["code/clean.py"], {"code/clean.py"}, proof,
        rollback_dependencies={"loop.py"}, repo_root=repo,
    )
    assert blocked["safe_to_archive"] == []
    assert blocked["skipped_protected_evidence"] == ["code/clean.py"]
