#!/usr/bin/env python3
"""Read-only application review using the unchanged original synthetic fixture.

Writes only a fresh directory below review_announcement. Application source,
original fixture, and existing owner archives are never written. Product build,
Reviewer registration, reference import, owner receipt, GET and CONSUMED checks
all use the candidate implementation. Only the fixture source catalog and clock
are injected. This is synthetic integration evidence, not a real-market replay.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types


REVIEW_ROOT = Path(__file__).resolve().parent
DEFAULT_CANDIDATE = REVIEW_ROOT.parent / "candidate"
FIXTURE_SHA = "22fccef9d1904c2ea0f52f645e4810cef876574bb8574722109fa37f0a29b4ed"
EARLY = datetime(2026, 10, 8, 1, tzinfo=timezone.utc)
LATE = datetime(2026, 10, 11, 4, tzinfo=timezone.utc)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_snapshot(candidate):
    return {str(path.relative_to(candidate)): sha(path)
            for scope in ("v4", "apps", "ops", "tests")
            for path in sorted((candidate / scope).rglob("*.py"))}


def load_fixture(candidate):
    sys.path.insert(0, str(candidate))
    from tests.r3_scoped_loader import install
    install()
    fixture_path = candidate / "tests/three_lane_announcement_original_fixture.py"
    assert sha(fixture_path) == FIXTURE_SHA, "Original fixture identity changed"
    spec = importlib.util.spec_from_file_location("original_announcement_review_fixture", fixture_path)
    fixture = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = fixture
    spec.loader.exec_module(fixture)
    return fixture, fixture_path


@contextmanager
def fixture_clock(fixture, workspace):
    import pytest
    old_now = fixture.NOW

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return (fixture.NOW.astimezone(tz) if tz
                    else fixture.NOW.replace(tzinfo=None))

    try:
        with pytest.MonkeyPatch.context() as clock:
            clock.setattr(fixture.api, "datetime", Clock)
            clock.setattr(fixture.consumer, "_now", lambda: fixture.NOW.isoformat())
            clock.setattr(workspace, "_now", lambda: fixture.NOW.isoformat())
            yield
    finally:
        fixture.NOW = old_now


@contextmanager
def source_issuer(fixture, issuer):
    """Change both generator input literals BEFORE it builds source artifacts.

    The fixture has no issuer parameter. Replacing only its two code constants
    preserves its bytecode and leaves every production parser/validator intact.
    Catalog, article receipt, corpus manifest and all hashes are generated from
    this input. _fixture then reads that catalog to build matching semantic
    issuer records and decisions before registering the reviewed handoff.
    """
    original = fixture._write_complete_evidence
    if issuer == "HK.01234":
        yield
        return
    assert issuer == "H5354"
    assert original.__code__.co_consts.count("HK.01234") == 1
    assert original.__code__.co_consts.count("01234") == 1
    altered = original.__code__.replace(co_consts=tuple(
        issuer if item in ("HK.01234", "01234") else item
        for item in original.__code__.co_consts))
    assert altered.co_code == original.__code__.co_code
    replacement = types.FunctionType(altered, original.__globals__, original.__name__,
                                     original.__defaults__, original.__closure__)
    replacement.__kwdefaults__ = original.__kwdefaults__
    fixture._write_complete_evidence = replacement
    try:
        yield
    finally:
        fixture._write_complete_evidence = original


def get_json(client, url, **params):
    response = client.get(url, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def announcement(workspace, fixture):
    product = next(row for row in workspace["announcement_reviewed_analysis"]["products"]
                   if row["target_trade_date"] == fixture.TARGET
                   and row["publication_date"] == fixture.PUBLICATION)
    return workspace["daily_channels"]["channels"][0], product


def summary(workspace, fixture):
    channel, consumed = announcement(workspace, fixture)
    return {
        "read_context": workspace.get("read_context"),
        "cutoff": workspace["plan_context"]["research_cutoff"],
        "plan_product_status": (workspace.get("plan_product") or {}).get("status"),
        "announcement_status": channel["status"],
        "announcement_count": channel["candidate_count"],
        "analysis_consumption_status": consumed["status"],
        "owner_available_at": consumed.get("owner_available_at"),
        "gaps": channel["gaps"],
        "product_sha256": consumed.get("product_sha256"),
        "point_in_time_status": consumed.get("point_in_time_status"),
    }


def false_zero(fixture, out):
    fixture.NOW = EARLY
    results = []
    for issuer in ("HK.01234", "H5354"):
        service = fixture._FixtureService(out / ("original_import_" + issuer.replace(".", "_")))
        try:
            with source_issuer(fixture, issuer):
                product, registered = fixture._fixture(service)
            with fixture._client(service) as client:
                imported = fixture._import(client, registered)
                initial = fixture._snapshot(service.store.root)
                readback = get_json(client, "/api/v4/manager/research/announcements/analysis",
                                    date=fixture.TARGET, publication_date=fixture.PUBLICATION)
                value = get_json(client, "/api/v4/manager/research/workspace",
                                 date=fixture.TARGET, view="dynamic", announcement_date="20261007")
                assert fixture._snapshot(service.store.root) == initial, "GET mutated owner state"
            channel, consumed = announcement(value, fixture)
            selection = readback["analysis"]["stock_selection"]
            assert imported["consumption_validation"]["validation_status"] == "VERIFIED"
            assert selection["status"] == "VERIFIED"
            assert selection["selected_stock_count"] == 1
            assert consumed["status"] == "CONSUMED"
            assert consumed["product_sha256"] == product["sha256"]
            result = {
                "issuer_input": issuer,
                "import_validation_status": imported["consumption_validation"]["validation_status"],
                "read_selection_status": selection["status"],
                "owner_selected_count": selection["selected_stock_count"],
                "owner_selection_codes": [row["stock_code"] for row in selection["stocks"]],
                "consumption_status": consumed["status"],
                "channel_status": channel["status"],
                "channel_count": channel["candidate_count"],
                "channel_rows": len(channel["rows"]),
                "gaps": channel["gaps"],
                "product_sha256": product["sha256"],
                "owner_import_receipt_sha256": readback["owner_import_receipt"]["sha256"],
                "get_wrote_state": False,
                "false_valid_zero": channel["status"] == "READY_EMPTY" and channel["candidate_count"] == 0,
            }
            (out / (issuer.replace(".", "_") + "_workspace.json")).write_text(
                json.dumps(value, ensure_ascii=False, indent=2) + "\n")
            results.append(result)
        finally:
            service.close()
    return results


def retrospective(fixture, workspace_module, out):
    fixture.NOW = EARLY
    service = fixture._FixtureService(out / "retrospective_saved_plan")
    try:
        # Real owner materialization; do not use the pytest owner fixture, whose
        # refresh_workspace_plan override deliberately forbids all plan writes.
        service.refresh_workspace_plan(fixture.TARGET, now=EARLY)
        early = service.get_workspace(fixture.TARGET, view="dynamic")
        assert early["plan_product"]["status"] == "CURRENT"
        early_cutoff = early["plan_context"]["research_cutoff"]
        fixture.NOW = LATE
        product, registered = fixture._fixture(service)
        with fixture._client(service) as client:
            imported = fixture._import(client, registered)
            assert imported["consumption_validation"]["validation_status"] == "VERIFIED"
            initial = fixture._snapshot(service.store.root)
            shown = get_json(client, "/api/v4/manager/research/workspace",
                             date=fixture.TARGET, view="dynamic")
            control = workspace_module.get_workspace(service, fixture.TARGET,
                         view="dynamic", now=fixture.NOW, include_saved=False)
            assert fixture._snapshot(service.store.root) == initial, "GET mutated owner state"
        shown_summary, control_summary = summary(shown, fixture), summary(control, fixture)
        assert control_summary["analysis_consumption_status"] == "CONSUMED"
        assert control_summary["announcement_count"] == 1
        for name, value in (("retrospective_api_workspace", shown), ("retrospective_control_workspace", control)):
            (out / (name + ".json")).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        return {
            "early_cutoff": early_cutoff,
            "now": fixture.NOW.isoformat(),
            "dynamic_saved_path": shown_summary,
            "dynamic_no_saved_context_control": control_summary,
            "product_sha256": product["sha256"],
            "get_wrote_state": False,
            "stale_cutoff_observed": shown_summary["cutoff"] == early_cutoff,
        }
    finally:
        service.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--out", type=Path, required=True, help="Fresh directory below review_announcement")
    parser.add_argument("--scenario", choices=("all", "false-zero", "retrospective"), default="all")
    args = parser.parse_args()
    candidate, out = args.candidate.resolve(), args.out.resolve()
    assert out.is_relative_to(REVIEW_ROOT) and out != REVIEW_ROOT, "Output must be isolated in review_announcement"
    out.mkdir(parents=True, exist_ok=False)
    before = source_snapshot(candidate)
    fixture, fixture_path = load_fixture(candidate)
    from v4.manager_research import workspace
    result = {
        "scope": "SYNTHETIC_ORIGINAL_FULL_BUILD_REVIEWER_HANDOFF_IMPORT_OWNER_CONSUMED_GET",
        "candidate": str(candidate),
        "fixture_path": str(fixture_path), "fixture_sha256": sha(fixture_path),
        "python_version": sys.version,
        "source_hashes_before": before,
    }
    try:
        with fixture_clock(fixture, workspace):
            if args.scenario in ("all", "false-zero"):
                result["false_zero"] = false_zero(fixture, out)
            if args.scenario in ("all", "retrospective"):
                result["retrospective"] = retrospective(fixture, workspace, out)
    finally:
        result["source_hashes_after"] = source_snapshot(candidate)
        result["source_unchanged_during_run"] = before == result["source_hashes_after"]
        (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    assert result["source_unchanged_during_run"], "Source changed during review; result not an acceptance run"
    print(json.dumps({key: value for key, value in result.items() if not key.startswith("source_hashes")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
