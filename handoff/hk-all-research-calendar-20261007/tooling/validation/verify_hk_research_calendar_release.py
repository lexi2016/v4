#!/usr/bin/env python3
"""Read-only semantic verification for the two inactive release packages."""
from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any


EVIDENCE_ROOT = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_HK_ALL_RESEARCH_CALENDAR_20261007"
)
ACTIVE_ROOTS = {
    "api": Path(
        "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/"
        "hk-close-hk-calendar-r2-20261007-api/app"
    ),
    "scheduler": Path(
        "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/"
        "hk-close-hk-calendar-r2-20261007-scheduler/app"
    ),
}
PACKAGE_PARENT = EVIDENCE_ROOT / "release_candidates" / "hk-research-calendar-all-r1-20261007"
PYTHON = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/"
    "20260904T081111Z-v35-strict-stage-acquisition-v15/runtime/venvs/v3.5-mac/bin/python"
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _inventory(app_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for directory, directories, filenames in os.walk(app_root, followlinks=False):
        directories.sort()
        filenames.sort()
        kept: list[str] = []
        for name in directories:
            path = Path(directory) / name
            if path.is_symlink():
                rows.append({
                    "kind": "symlink",
                    "path": path.relative_to(app_root).as_posix(),
                    "target": os.readlink(path),
                    "target_exists": path.exists(),
                })
            else:
                kept.append(name)
        directories[:] = kept
        for name in filenames:
            path = Path(directory) / name
            if path.is_symlink():
                rows.append({
                    "kind": "symlink",
                    "path": path.relative_to(app_root).as_posix(),
                    "target": os.readlink(path),
                    "target_exists": path.exists(),
                })
            else:
                import stat

                info = path.lstat()
                rows.append({
                    "kind": "file",
                    "mode": f"{stat.S_IMODE(info.st_mode):04o}",
                    "path": path.relative_to(app_root).as_posix(),
                    "sha256": _sha256(path.read_bytes()),
                    "size": info.st_size,
                })
    return sorted(rows, key=lambda row: row["path"])


def _check_manifest(service: str) -> dict[str, Any]:
    release_id = f"hk-research-calendar-all-r1-20261007-{service}"
    release_root = PACKAGE_PARENT / release_id
    app_root = release_root / "app"
    manifest_path = release_root / "release-manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    candidate = manifest["candidate"]
    assert candidate["app_root"] == str(app_root)
    assert candidate["root"] == str(release_root)
    assert candidate["release_id"] == release_id
    assert manifest["activation_status"] == "NOT_ACTIVATED"
    assert manifest["deployment_status"] == "NOT_DEPLOYED"
    assert manifest["production_allowed"] is False
    assert manifest["buy_gate_updated"] is False
    assert manifest["orders_sent"] is False
    inventory = manifest["application_inventory"]
    observed = _inventory(app_root)
    assert observed == inventory["entries"]
    assert inventory["entry_count"] == len(observed)
    actual_inventory_sha = _sha256(
        json.dumps(observed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )
    assert actual_inventory_sha == inventory["aggregate_sha256"]
    return {
        "service": service,
        "release_id": release_id,
        "release_root": str(release_root),
        "app_root": str(app_root),
        "manifest_sha256": _sha256(manifest_bytes),
        "application_inventory_sha256": actual_inventory_sha,
        "application_inventory_entry_count": len(observed),
        "activation_status": manifest["activation_status"],
        "safety": {
            "production_allowed": manifest["production_allowed"],
            "buy_gate_updated": manifest["buy_gate_updated"],
            "orders_sent": manifest["orders_sent"],
        },
    }


def _function_source(path: Path, name: str) -> str:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    node = next(
        item for item in tree.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
    )
    return ast.get_source_segment(text, node) or ""


def _run_package_check(service: str, app_root: Path) -> dict[str, Any]:
    source = r'''
import json
from pathlib import Path

from contracts.trading_calendar import MarketScope, RunPolicy, SessionRequirement
from domains.runtime_policy import evaluate_run_policy
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.runtime_graph import service as runtime_graph

catalog = load_workload_catalog()
by_id = {item.workload_id: item for item in catalog.workloads}
expected = {
    "research_panel_daily_hk": RunPolicy.HK_SECURITIES_TRADE_DAY,
    "research_panel_runtime_evidence": RunPolicy.A_OR_HK_SECURITIES_TRADE_DAY,
    "review_core_pool_pipeline": RunPolicy.A_OR_HK_SECURITIES_TRADE_DAY,
    "preselection_pools": RunPolicy.A_OR_HK_SECURITIES_TRADE_DAY,
    "daily_materialize": RunPolicy.A_OR_HK_SECURITIES_TRADE_DAY,
    "hk_auction_0920": RunPolicy.HK_SECURITIES_TRADE_DAY,
    "hk_connect_close_review": RunPolicy.HK_SECURITIES_TRADE_DAY,
    "stage_workbench": RunPolicy.A_OR_HK_SECURITIES_TRADE_DAY,
    "fupan_review_start": RunPolicy.HK_SECURITIES_TRADE_DAY,
}
assert all(by_id[key].run_policy is policy for key, policy in expected.items())
assert by_id["stage_workbench"].enabled is False
assert by_id["hk_connect_close_review"].slots == ("1610",)

def evaluate(policy, date, scope):
    return evaluate_run_policy(
        policy, date, "2140", market_scope=scope,
        session_requirement=SessionRequirement.DAY_ELIGIBILITY_ONLY,
    )

hk_only = evaluate(RunPolicy.A_OR_HK_SECURITIES_TRADE_DAY, "20261005", MarketScope.CROSS_MARKET)
assert hk_only.eligible and hk_only.eligible_markets == ("hk_securities",)
connect_closed = evaluate(RunPolicy.A_OR_HK_CONNECT_TRADE_DAY, "20261005", MarketScope.CROSS_MARKET)
assert not connect_closed.eligible and connect_closed.blocked_markets == ("a_share", "hk_connect")
a_only = evaluate(RunPolicy.A_OR_HK_SECURITIES_TRADE_DAY, "20260403", MarketScope.CROSS_MARKET)
assert a_only.eligible and a_only.eligible_markets == ("a_share",)
nontrading = evaluate(RunPolicy.A_OR_HK_SECURITIES_TRADE_DAY, "20261004", MarketScope.CROSS_MARKET)
assert not nontrading.eligible

hk_api = runtime_graph._calendar_decision("hk_securities_trade_day", "20261005")
hk_cross_api = runtime_graph._calendar_decision("a_or_hk_securities_trade_day", "20261005")
connect_api = runtime_graph._calendar_decision("a_or_hk_connect_trade_day", "20261005")
assert hk_api["should_run"] is True
assert hk_cross_api["should_run"] is True
assert connect_api["should_run"] is False
assert runtime_graph._next_market_trade_date("20261004", "hk_securities") == "20261005"

from infrastructure.runtime_graph.v35_topology import load_v35_topology
load_v35_topology(Path.cwd() / "contracts/v35_runtime_graph_topology.json")
import infrastructure.scheduling.dispatcher
if __service__ == "scheduler":
    from ops.daily_materialize import _evaluate_calendar
    materialized = _evaluate_calendar("20261005")
    assert materialized["decision"].policy is RunPolicy.A_OR_HK_SECURITIES_TRADE_DAY
    assert materialized["decision"].eligible_markets == ("hk_securities",)
print(json.dumps({
    "catalog_workload_count": len(catalog.workloads),
    "target_workloads": sorted(expected),
    "stage_workbench_enabled": by_id["stage_workbench"].enabled,
    "hk_only_date_20261005": hk_cross_api,
    "a_only_date_20260403": list(a_only.eligible_markets),
    "connect_20261005": connect_api,
    "nontrading_20261004": nontrading.eligible,
    "topology_valid": True,
    "full_imports": True,
}, default=str, sort_keys=True))
'''.replace("__service__", repr(service))
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(app_root)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [str(PYTHON), "-c", source],
        cwd=app_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"{service} package import/behavior verification failed:\n"
            f"stdout={result.stdout[-4000:]}\nstderr={result.stderr[-4000:]}"
        )
    return json.loads(result.stdout.strip().splitlines()[-1])


def main() -> int:
    reports = []
    for service in ("api", "scheduler"):
        report = _check_manifest(service)
        behavior = _run_package_check(service, Path(report["app_root"]))
        report["behavior"] = behavior
        reports.append(report)

    for service, report in zip(("api", "scheduler"), reports, strict=True):
        preimage = ACTIVE_ROOTS[service] / "infrastructure/runtime_graph/service.py"
        candidate = Path(report["app_root"]) / "infrastructure/runtime_graph/service.py"
        if _function_source(preimage, "_target_date_for_node") != _function_source(candidate, "_target_date_for_node"):
            raise RuntimeError(f"{service} _target_date_for_node source differs from the live Connect mapping")
    print(json.dumps({
        "schema_version": "v4.hk_research_calendar_release_verification.v1",
        "status": "PASS",
        "services": reports,
        "target_date_for_node_connect_source_preserved": ["api", "scheduler"],
        "verification_command": (
            "PYTHONDONTWRITEBYTECODE=1 '/Users/lexi/Library/Application Support/"
            "com.lexi.v35.local/releases/20260904T081111Z-v35-strict-stage-acquisition-v15/"
            "runtime/venvs/v3.5-mac/bin/python' "
            "'/Users/lexi/Desktop/学习/agents调试/V4_HK_ALL_RESEARCH_CALENDAR_20261007/"
            "scripts/verify_hk_research_calendar_release.py'"
        ),
        "deployment_performed": False,
        "service_action_performed": False,
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
