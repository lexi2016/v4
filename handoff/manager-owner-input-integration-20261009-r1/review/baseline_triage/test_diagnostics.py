"""Read-only baseline triage: synthetic projections and temporary SafeRoot I/O.

This is a diagnostic suite, not a replacement for the four original test files.
It neither edits the source snapshot nor relaxes its assertions. Network calls
are denied for this process, and all generated owner state is synthetic.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "work/baseline/app"
PACKAGE = ROOT / "input/package"
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(APP))


def deny_network(event, args):
    if event in {"socket.connect", "socket.connect_ex", "socket.bind",
                 "socket.getaddrinfo", "socket.sendto", "socket.gethostbyname"}:
        raise RuntimeError("TRIAGE_NETWORK_FORBIDDEN")


sys.addaudithook(deny_network)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_test(name):
    spec = importlib.util.spec_from_file_location("triage_" + name, APP / "tests" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixed_paths = sorted(p.relative_to(PACKAGE / "code/r2_chat_patch_target").as_posix()
                     for p in (PACKAGE / "code/r2_chat_patch_target").rglob("*") if p.is_file())
support_paths = [
    "v4/manager_research/announcement_observation.py",
    "v4/manager_research/announcement_catalog.py",
    "v4/manager_research/research_attention.py",
    "infrastructure/scheduling/manager_announcement_supervisor.py",
    "apps/api/__init__.py",
]
before = {p: sha(APP / p) for p in fixed_paths + support_paths}
REPORT = {
    "scope": "SYNTHETIC_OFFLINE_BASELINE_TRIAGE_NOT_MAC_ACCEPTANCE",
    "source_root": str(APP),
    "python_executable": sys.executable,
    "python_version": sys.version,
    "network": "DENIED_BY_PROCESS_AUDIT_HOOK",
    "fixed_r2_count": len(fixed_paths),
    "fixed_r2_matches_package": all(sha(APP / p) == sha(PACKAGE / "code/r2_chat_patch_target" / p)
                                    for p in fixed_paths),
    "before_sha256": before,
}


@pytest.fixture(scope="session", autouse=True)
def report_results():
    frozen_versions = json.loads((ROOT / "work/runtime_locked_identity.json").read_text())["versions"]
    REPORT["installed_versions"] = {name: importlib.metadata.version(name) for name in frozen_versions}
    REPORT["all_31_lock_versions_match"] = REPORT["installed_versions"] == frozen_versions
    assert REPORT["fixed_r2_count"] == 20 and REPORT["fixed_r2_matches_package"]
    assert REPORT["all_31_lock_versions_match"]
    yield
    REPORT["after_sha256"] = {p: sha(APP / p) for p in before}
    REPORT["source_and_original_tests_unchanged"] = REPORT["after_sha256"] == before
    (OUT / "diagnostic_results.json").write_text(json.dumps(REPORT, ensure_ascii=False, indent=2) + "\n")
    assert REPORT["source_and_original_tests_unchanged"]


def test_real_plan_readback_fault_boundaries(tmp_path, monkeypatch):
    t = load_test("test_manager_plan_readback_issue24")
    w, s = t.w, t.s
    outputs = []
    cases = ("normal", "first_product_read_error", "first_product_wrong_run",
             "first_product_wrong_sha", "final_product_read_error", "same_run_journal_read_error")
    for case in cases:
        store = s.ManagerResearchStore(tmp_path / case)
        writes, readbacks = [], []
        read_count = 0
        real_read = store._read
        real_write = store._write_atomic
        real_readback = w._readback_plan

        def recording_write(path, value):
            real_write(path, value)
            if "workspace_plan_runs" in path.parts:
                writes.append(dict(path_role="latest" if path.name == "latest.json" else "exact_run",
                                   state=value["state"], last_success_at=value.get("last_success_at"),
                                   success_scope=value.get("success_scope")))

        def faulting_read(path):
            nonlocal read_count
            value = real_read(path)
            if path == t.latest(store) and value is not None:
                read_count += 1
                if case == "first_product_read_error" and read_count == 1:
                    raise s.StoreError("TRIAGE_SYNTHETIC_FIRST_PRODUCT_READ_ERROR")
                if case == "first_product_wrong_run" and read_count == 1:
                    value = deepcopy(value)
                    value["run_id"] = "b" * 32
                    return t.seal(value)
                if case == "first_product_wrong_sha" and read_count == 1:
                    value = deepcopy(value)
                    value["sha256"] = "0" * 64
                    return value
                if case == "final_product_read_error" and read_count == 2:
                    raise s.StoreError("TRIAGE_SYNTHETIC_FINAL_PRODUCT_READ_ERROR")
            if (case == "same_run_journal_read_error" and "workspace_plan_runs" in path.parts
                    and path.name == t.RUN + ".json" and value is not None
                    and value.get("state") == "SUCCEEDED_EMPTY"):
                raise s.StoreError("TRIAGE_SYNTHETIC_EXACT_JOURNAL_READ_ERROR")
            return value

        def observed_readback(*args, **kwargs):
            value = real_readback(*args, **kwargs)
            readbacks.append(deepcopy(value.get("plan_product")))
            return value

        returned = None
        error = None
        with monkeypatch.context() as mp:
            mp.setattr(w, "_now", lambda: t.TIME)
            mp.setattr(w, "uuid4", lambda: SimpleNamespace(hex=t.RUN))
            mp.setattr(w, "get_workspace", lambda *args, **kwargs: t.current("SYNTHETIC_ONLY"))
            mp.setattr(store, "_read", faulting_read)
            mp.setattr(store, "_write_atomic", recording_write)
            mp.setattr(w, "_readback_plan", observed_readback)
            try:
                returned = w.refresh_workspace_plan(SimpleNamespace(store=store), t.DATE)
            except (ValueError, OSError, s.StoreError) as exc:
                error = dict(type=type(exc).__name__, message=str(exc))
        terminal = real_read(store.root / "workspace_plan_runs" / t.DATE / "latest.json")
        post_failure_or_success = real_readback(store, t.DATE, t.current())["plan_product"]
        row = dict(case=case, fault_injected=case != "normal", returned=returned is not None,
                   returned_product=returned.get("plan_product") if returned else None,
                   exception=error, journal_writes_completed=writes,
                   actual_readback_results=readbacks, terminal_state=terminal["state"],
                   terminal_last_success_at=terminal.get("last_success_at"),
                   terminal_has_success_scope="success_scope" in terminal,
                   subsequent_real_get_product=post_failure_or_success)
        outputs.append(row)
        if case == "normal":
            assert returned["plan_product"]["status"] == "CURRENT"
            assert returned["plan_product"]["consumed"] is True
            assert terminal["state"] == "SUCCEEDED_EMPTY"
        else:
            assert returned is None and error is not None
            assert terminal["state"] == "FAILED" and terminal.get("last_success_at") is None
            assert "success_scope" not in terminal
            assert post_failure_or_success["consumed"] is False
        if case.startswith("first_product"):
            assert {r["state"] for r in writes} <= {"RUNNING", "FAILED"}
        if case in {"final_product_read_error", "same_run_journal_read_error"}:
            assert any(r["state"] == "SUCCEEDED_EMPTY" for r in writes)
            assert readbacks[-1].get("consumed") is not True
    REPORT["plan_real_readback_probes"] = outputs
    print("PLAN_REAL_READBACK_PROBES=" + json.dumps(outputs, ensure_ascii=False))


def test_legacy_plan_missing_owner_journal_is_readable_but_not_consumed(tmp_path):
    t = load_test("test_manager_plan_readback_issue24")
    store = t.s.ManagerResearchStore(tmp_path)
    product = t.plan("SMALL_SYNTHETIC_ANALOGUE_OF_64_MIB_TEST")
    t.put_legacy(store, product)
    before_bytes = t.latest(store).read_bytes()
    assert t.w._read_plan(store, t.DATE) == product
    result = t.w._readback_plan(store, t.DATE, t.current())["plan_product"]
    assert result["status"] == "OWNER_ATTEMPT_UNVERIFIED"
    assert result["reason"] == "WORKSPACE_PLAN_ATTEMPT_MISSING" and result["consumed"] is False
    assert t.latest(store).read_bytes() == before_bytes
    REPORT["legacy_missing_journal_probe"] = result
    print("LEGACY_MISSING_JOURNAL_PROBE=" + json.dumps(result, ensure_ascii=False))


def test_issue8_fixture_and_projection_boundaries():
    t = load_test("test_issue8_selection_gaps")
    old_scope = t.scope()
    d1 = deepcopy(old_scope)
    d1["source"]["source_date"] = "20260930"
    old_reason = t.cs.filter_cards([{"symbol": "HK.01234"}], d1)[1][0]["reason"]
    d1["membership_semantics"] = "TARGET_DATE_CAPTURED_HK_CONNECT_AUTHORITY_V2"
    declared_v2_reason = t.cs.filter_cards([{"symbol": "HK.01234"}], d1)[1][0]["reason"]
    verified_scope = deepcopy(old_scope)
    verified_scope["membership_semantics"] = "TARGET_DATE_CAPTURED_HK_CONNECT_AUTHORITY_V2"

    review = t.review()
    lane = t.event_lane(review, {}, t.CTX)
    screen, old_filtered = t.cs.evidence_view({}, lane, old_scope)
    old_result = t.attention(old_filtered, screen)
    screen, v2_filtered = t.cs.evidence_view({}, lane, verified_scope)
    v2_result = t.attention(v2_filtered, screen)
    bridge_lane = deepcopy(lane)
    bridge_lane["positive_observations"] = deepcopy(review["positive_observations"])
    bridge_lane["positive_observations"].append(deepcopy(review["positive_observations"][0]))
    screen, bridge_filtered = t.cs.evidence_view({}, bridge_lane, t.UNKNOWN)
    bridge_result = t.attention(bridge_filtered, screen)
    row = dict(old_scope_error=old_reason, prior_day_with_explicit_v2=declared_v2_reason,
               event_lane_positive_observations_present="positive_observations" in lane,
               review_positive_count=len(review["positive_observations"]),
               old_scope_official_admitted=len(old_filtered["official_documents"]),
               v2_scope_official_admitted=len(v2_filtered["official_documents"]),
               old_scope_scored_symbols=[r["symbol"] for r in old_result["cards"]],
               v2_scope_scored_symbols=[r["symbol"] for r in v2_result["cards"]],
               v2_scope_observation_count=len(v2_result["observation_only"]["cards"]),
               synthetic_projection_probe="IN_MEMORY_FIELD_RESTORATION_ONLY_NOT_SOURCE_PATCH",
               bridge_duplicate_observation_count=len(bridge_result["observation_only"]["cards"]),
               bridge_scored_cards=bridge_result["cards"],
               bridge_observation_safety=[{k: r.get(k) for k in ("focus_eligible", "qualified", "buy_allowed", *t.FLAGS)}
                                          for r in bridge_result["observation_only"]["cards"]],
               frozen_selected_fields_in_package=(PACKAGE / "evidence/FROZEN_SELECTED_FIELDS.json").is_file())
    assert old_reason == "HK_CONNECT_MEMBERSHIP_SEMANTICS_UNVERIFIED"
    assert declared_v2_reason == "TARGET_HK_CONNECT_MEMBERSHIP_DATE_OR_ROLE_MISMATCH"
    assert "positive_observations" not in lane
    assert row["old_scope_scored_symbols"] == [] and row["v2_scope_scored_symbols"] == ["HK.01234"]
    assert row["v2_scope_observation_count"] == 0
    assert row["bridge_duplicate_observation_count"] == 1 and not row["bridge_scored_cards"]
    assert not row["frozen_selected_fields_in_package"]
    REPORT["issue8_probes"] = row
    print("ISSUE8_PROBES=" + json.dumps(row, ensure_ascii=False))


def test_catalog_source_identity_contract_and_binding_inventory(monkeypatch):
    t = load_test("test_manager_announcement_date_catalog")
    with monkeypatch.context() as mp:
        fixture = t._CaptureFixture(mp, {1: t._response(1, 1, [t._row(1, stock_code="H5354")]),
                                        2: t._response(2, 1, [])})
        catalog = t._collect(fixture)
        checked = t.catalog.verify_product_sources(catalog, fixture.store)
        assert checked["sha256"] == catalog["sha256"]
    from infrastructure.scheduling.manager_announcement_supervisor import (
        REQUIRED_FILES, PLAN_OWNER_REQUIRED_FILES, PLAN_OWNER_SOURCE_FILES)
    tree = json.loads((ROOT / "work/base_repository_tree.json").read_text())
    initializers = [r for r in tree["tree"] if any(r["path"] == p or r["path"].endswith("/" + p)
                    for p in ("apps/__init__.py", "apps/api/__init__.py"))]
    row = dict(status=catalog["status"], manager_consumer_use=catalog["manager_consumer_use"],
               source_identity_basis=catalog["source_identity_basis"],
               manager_consumer_row_count=catalog["manager_consumer_row_count"],
               manager_source_codes=catalog["manager_source_codes"],
               manager_matched_master_codes=catalog["manager_matched_master_codes"],
               connect_eligibility_status=catalog["connect_eligibility_status"],
               semantic_analysis=catalog["semantic_analysis"],
               source_rederivation="VERIFIED_AGAINST_SYNTHETIC_MEMORY_BLOBS",
               safety={k: catalog[k] for k in t.catalog.FLAGS},
               supervisor_missing_required=[p for p in REQUIRED_FILES if not (APP / p).is_file()],
               supervisor_missing_plan_owner_required=[p for p in PLAN_OWNER_REQUIRED_FILES if not (APP / p).is_file()],
               supervisor_missing_plan_owner_sources=[p for p in PLAN_OWNER_SOURCE_FILES if not (APP / p).is_file()],
               frozen_tree_truncated=tree["truncated"], original_initializer_candidates=initializers)
    assert row["manager_consumer_row_count"] == 1 and not row["manager_matched_master_codes"]
    assert row["connect_eligibility_status"] == "NOT_ASSESSED" and row["semantic_analysis"] == "NOT_RUN"
    assert row["supervisor_missing_required"] == ["apps/__init__.py"]
    assert row["supervisor_missing_plan_owner_required"] == ["apps/__init__.py"]
    assert row["supervisor_missing_plan_owner_sources"] == []
    REPORT["catalog_and_supervisor_probes"] = row
    print("CATALOG_AND_SUPERVISOR_PROBES=" + json.dumps(row, ensure_ascii=False))
