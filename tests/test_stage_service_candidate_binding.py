import json
import os
import plistlib
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from infrastructure.preselection_pool_store import PreselectionPoolStore, PreselectionSourceResolver
from ops.build_release_candidate import _render_stage_service_binding


def test_stage_service_binding_uses_explicit_runtime_and_preserves_stage_contract(tmp_path):
    candidate = tmp_path / "candidate"
    app = candidate / "app"
    script = app / "ops" / "run_stage_center_nodes.py"
    config = app / "stage_center_tick_config.json"
    package = app / "upstreams" / "v3_shared_data"
    script.parent.mkdir(parents=True)
    package.mkdir(parents=True)
    script.write_text("# candidate entrypoint\n")
    data_paths = {
        "candidate_acquisition_root": "/v4/state/data",
        "raw_root": "/v4/state/stage/raw",
        "selection_root": "/v4/state/stage/selection",
        "receipt_root": "/v4/state/stage/receipts",
        "v4_research_data_root": "/v35/state/data",
        "hk_d1_root": "/v4/state/data",
        "preselection_source_root": "/v35/state/data",
        "hk_second_filter_root": "/v4/state/data/opening_second_filter",
        "hk_full_universe_root": "/v4/state/data",
        "a_auction_root": "/v4/state/data/stage_inputs",
        "hk_auction_root": "/v4/state/data/opening_second_filter",
        "hk_stage_replay_root": "/v4/state/data/stage_references",
        "a_research_panel_receipt_root": "/v4/state/research_panel_daily/receipts",
    }
    config.write_text(json.dumps({
        "release_id": "old-release",
        "python_path": "/runtime/shared/bin/python",
        "shared_data_root": "/old-release/app/upstreams/v3_shared_data",
        "node_calendar_wait_max_seconds": 5,
        "node_max_attempts": 3,
        "node_retry_backoff_seconds": 60,
        "safety": {
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
        **data_paths,
    }))

    source_plist = tmp_path / "source.plist"
    source_plist.write_bytes(plistlib.dumps({
        "Label": "com.lexi.stage-center.scheduler",
        "ProgramArguments": [
            "/runtime/shared/bin/python", "-B", "/old-release/app/ops/run_stage_center_nodes.py",
            "--config", "/old-release/app/stage_center_tick_config.json",
        ],
        "WorkingDirectory": "/old-release/app",
        "StartCalendarInterval": [{"Hour": 9, "Minute": 35}],
        "EnvironmentVariables": {
            "NODE_CALENDAR_WAIT_MAX_SECONDS": "5",
            "NODE_MAX_ATTEMPTS": "3",
            "NODE_RETRY_BACKOFF_SECONDS": "60",
            "PRODUCTION_ALLOWED": "false",
            "BUY_GATE_UPDATED": "false",
            "ORDERS_SENT": "false",
            "STAGE_CENTER_RUNTIME_ROOT": "/runtime",
            "REVIEW_CORE_STAGE7_POOL_ROOT": "/v4/state/data/stage7_store",
        },
    }))

    manifest = candidate / "release-manifest.json"
    manifest.write_text("{}\n")
    runtime_target = tmp_path / "runtime" / "cpython-3.14" / "bin" / "python3.14"
    runtime_target.parent.mkdir(parents=True)
    runtime_target.write_text("#!/bin/sh\nexit 0\n")
    runtime_link = tmp_path / "runtime" / "venvs" / "stage-3.14" / "bin" / "python"
    runtime_link.parent.mkdir(parents=True)
    runtime_link.symlink_to(runtime_target)
    result = _render_stage_service_binding(
        source_plist=source_plist,
        candidate_root=candidate,
        release_id="stage-candidate-r1",
        manifest_path=manifest,
        manifest_sha256="a" * 64,
        runtime_python=runtime_link,
        source_runtime_python=Path("/runtime/shared/bin/python"),
    )

    staged = plistlib.loads(Path(result["path"]).read_bytes())
    expected_python = str(runtime_link)
    assert staged["ProgramArguments"] == [expected_python, "-B", str(script), "--config", str(config)]
    assert staged["WorkingDirectory"] == str(app)
    assert staged["StartCalendarInterval"] == [{"Hour": 9, "Minute": 35}]
    assert staged["EnvironmentVariables"]["NODE_CALENDAR_WAIT_MAX_SECONDS"] == "5"
    assert staged["EnvironmentVariables"]["NODE_MAX_ATTEMPTS"] == "3"
    assert staged["EnvironmentVariables"]["NODE_RETRY_BACKOFF_SECONDS"] == "60"
    assert staged["EnvironmentVariables"]["STAGE_CENTER_RUNTIME_ROOT"] == "/runtime"
    assert staged["EnvironmentVariables"]["V4_STAGE_DEADLINE_POLICY"] == "observe"
    assert staged["EnvironmentVariables"]["V35_RELEASE_MANIFEST_SHA256"] == "a" * 64
    assert all(staged["EnvironmentVariables"][key] == "false" for key in (
        "PRODUCTION_ALLOWED", "BUY_GATE_UPDATED", "ORDERS_SENT"
    ))

    staged_config = json.loads(config.read_text())
    assert staged_config["release_id"] == "stage-candidate-r1"
    assert staged_config["python_path"] == expected_python
    assert staged_config["shared_data_root"] == str(package)
    assert {key: staged_config[key] for key in data_paths} == data_paths
    assert staged_config["node_calendar_wait_max_seconds"] == 5
    assert staged_config["node_max_attempts"] == 3
    assert staged_config["node_retry_backoff_seconds"] == 60
    assert result["activation_status"] == "NOT_ACTIVATED"
    assert result["launchctl_called"] is False


def _strict_hk_d1_payload(trade_date: str, signal_date: str) -> dict:
    rows = [
        {
            "market": "HK",
            "pool_id": "hkconnect_d1_top100",
            "pool_rank": rank,
            "signal_date": signal_date,
            "symbol": f"HK.{rank:05d}",
            "target_date": trade_date,
        }
        for rank in range(1, 101)
    ]
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": trade_date,
        "target_date": trade_date,
        "signal_date": signal_date,
        "pool_id": "hkconnect_d1_top100",
        "display_name": "HK Connect D-1 Top100",
        "market": "HK",
        "status": "STRICT_0_2_READY",
        "producer_id": "v3_shared_hk_0_2_consumer_v1",
        "source_role": "SHARED_VERIFIED_HK_0_2",
        "source_path": "read-only-fixture",
        "source_sha256": "a" * 64,
        "stage_selection_eligible": True,
        "rows": rows,
        "cannot_confirm": [],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def test_stage_d1_resolver_falls_back_only_when_primary_exact_date_is_absent(tmp_path):
    from stage_center.runner import RunnerError, _validate_hk_d1, build_production_config

    trade_date = "20260924"
    signal_date = "20260923"
    v4_root = tmp_path / "v4-state-data"
    legacy_root = tmp_path / "v35-state-data"
    legacy_root.mkdir()
    store = PreselectionPoolStore(legacy_root)
    store.materialize(_strict_hk_d1_payload(trade_date, signal_date))

    config = build_production_config(
        candidate_acquisition_root=tmp_path / "candidate",
        raw_root=tmp_path / "raw",
        selection_root=tmp_path / "selection",
        receipt_root=tmp_path / "receipts",
        hk_d1_root=v4_root,
        preselection_source_root=legacy_root,
    )
    assert config.preselection_source_root == legacy_root.resolve()
    resolver = PreselectionSourceResolver(v4_root, source_root=legacy_root)
    assert resolver.root_for_date(trade_date) == legacy_root.resolve()
    path, _digest = _validate_hk_d1(
        config.hk_d1_root,
        trade_date,
        preselection_source_root=config.preselection_source_root,
    )
    assert path == legacy_root / "preselection_pools" / trade_date / "hkconnect_d1_top100.json"

    # A partial V4 date directory owns the date. A valid legacy snapshot must
    # not shadow it or turn the current V4 partial into a ready D1 pool.
    (v4_root / "preselection_pools" / trade_date).mkdir(parents=True)
    assert resolver.root_for_date(trade_date) == v4_root.resolve()
    with pytest.raises(RunnerError, match="snapshot integrity invalid"):
        _validate_hk_d1(
            config.hk_d1_root,
            trade_date,
            preselection_source_root=config.preselection_source_root,
        )


def test_stage_candidate_builder_preserves_active_release_outside_allowlisted_overlay(tmp_path, monkeypatch):
    from ops.build_release_candidate import (
        STAGE_SERVICE_LABEL,
        STAGE_SERVICE_OVERLAY_PATHS,
        build_stage_service_candidate,
        inventory_digest,
        inventory_tree,
    )

    monkeypatch.setattr("ops.build_release_candidate._run_git", lambda *_args, **_kwargs: "fixture-source-commit")

    source = tmp_path / "source"
    base_release = tmp_path / "formal" / "releases" / "active-r1"
    base_app = base_release / "app"
    candidate_root = tmp_path / "candidates" / "stage-r5-test"
    source_script = source / "ops/run_stage_center_nodes.py"
    source_runner = source / "stage_center/runner.py"
    source_config = source / "stage_center_tick_config.json"
    source_script.parent.mkdir(parents=True)
    source_runner.parent.mkdir(parents=True)
    source_script.write_text("# current stage entry\n")
    source_runner.write_text("# current stage runner\n")
    (source / "apps/web/src").mkdir(parents=True)
    (source / "apps/web/src/App.vue").write_text("current dirty manager UI\n")
    data_roots = {
        "candidate_acquisition_root": "/v4/state/data",
        "raw_root": "/v4/state/stage/raw",
        "selection_root": "/v4/state/stage/selection",
        "receipt_root": "/v4/state/stage/receipts",
        "v4_research_data_root": "/v35/state/data",
        "hk_d1_root": "/v4/state/data",
        "hk_second_filter_root": "/v4/state/data/opening_second_filter",
        "hk_full_universe_root": "/v4/state/data",
        "a_auction_root": "/v4/state/data/stage_inputs",
        "hk_auction_root": "/v4/state/data/opening_second_filter",
        "hk_stage_replay_root": "/v4/state/data/stage_references",
        "a_research_panel_receipt_root": "/v4/state/research_panel_daily/receipts",
    }
    source_config.write_text(json.dumps({
        "schema_version": "stage_center.tick_config.v1",
        "release_id": "current-workspace",
        "python_path": sys.executable,
        "shared_data_root": "/old/source/package",
        "node_calendar_wait_max_seconds": 5,
        "node_max_attempts": 3,
        "node_retry_backoff_seconds": 60,
        "safety": {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
        **data_roots,
    }))

    active_config = {
        "schema_version": "stage_center.tick_config.v1",
        "release_id": "active-r1",
        "python_path": sys.executable,
        "shared_data_root": str(base_app / "upstreams/v3_shared_data"),
        "preselection_source_root": "/v35/authoritative/preselection",
        "node_calendar_wait_max_seconds": 5,
        "node_max_attempts": 3,
        "node_retry_backoff_seconds": 60,
        "safety": {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
        **data_roots,
    }
    (base_app / "ops").mkdir(parents=True)
    (base_app / "stage_center").mkdir(parents=True)
    (base_app / "upstreams/v3_shared_data").mkdir(parents=True)
    (base_app / "apps/web/src").mkdir(parents=True)
    (base_app / "ops/run_stage_center_nodes.py").write_text("# active entry\n")
    (base_app / "stage_center/runner.py").write_text("# active runner\n")
    (base_app / "infrastructure").mkdir(parents=True)
    (base_app / "infrastructure/stage_acquisition_universe_commit.py").write_text(
        "# active R1 constructor and source lease\n"
    )
    (base_app / "infrastructure/stage_acquisition_universe_contracts.py").write_text(
        "# active R1 contract helper dependency\n"
    )
    (base_app / "apps/web/src/App.vue").write_text("active release UI byte baseline\n")
    (base_app / "stage_center_tick_config.json").write_text(json.dumps(active_config))
    (source / "infrastructure").mkdir(parents=True)
    (source / "infrastructure/stage_acquisition_universe_commit.py").write_text(
        "# stale workspace overlay\n"
    )

    manifest = {
        "schema_version": "fixture.active.release.v1",
        "release_id": "active-r1",
        "release_root": str(base_release),
        "app_root": str(base_app),
    }
    app_inventory = inventory_tree(base_app)
    manifest["application_inventory"] = {
        "aggregate_sha256": inventory_digest(app_inventory),
        "entries": app_inventory,
    }
    (base_release / "release-manifest.json").write_text(json.dumps(manifest))

    plist_path = tmp_path / "launchagents" / "stage.plist"
    plist_path.parent.mkdir()
    plist_path.write_bytes(plistlib.dumps({
        "Label": STAGE_SERVICE_LABEL,
        "ProgramArguments": [
            sys.executable, "-B", str(base_app / "ops/run_stage_center_nodes.py"),
            "--config", str(base_app / "stage_center_tick_config.json"),
        ],
        "WorkingDirectory": str(base_app),
        "EnvironmentVariables": {
            "NODE_CALENDAR_WAIT_MAX_SECONDS": "5",
            "NODE_MAX_ATTEMPTS": "3",
            "NODE_RETRY_BACKOFF_SECONDS": "60",
            "PRODUCTION_ALLOWED": "false",
            "BUY_GATE_UPDATED": "false",
            "ORDERS_SENT": "false",
        },
    }))
    receipt = build_stage_service_candidate(
        source_root=source,
        candidate_root=candidate_root,
        stage_plist_path=plist_path,
        runtime_python=Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python"),
        release_id="stage-r5-test",
        formal_release_root=tmp_path / "formal",
        receipt_path=tmp_path / "evidence/build-receipt.json",
        baseline_release_root=base_release,
        overlay_paths=("ops/run_stage_center_nodes.py", "stage_center/runner.py", "stage_center_tick_config.json"),
    )
    candidate_app = candidate_root / "app"
    assert (candidate_app / "apps/web/src/App.vue").read_text() == "active release UI byte baseline\n"
    assert (candidate_app / "ops/run_stage_center_nodes.py").read_text() == "# current stage entry\n"
    config = json.loads((candidate_app / "stage_center_tick_config.json").read_text())
    assert config["preselection_source_root"] == "/v35/authoritative/preselection"
    assert config["candidate_acquisition_root"] == data_roots["candidate_acquisition_root"]
    manifest_out = json.loads((candidate_root / "release-manifest.json").read_text())
    assert manifest_out["source"]["stage_overlay"]["workspace_full_tree_copied"] is False
    assert manifest_out["source"]["stage_overlay"]["non_overlay_active_release_bytes_preserved"] is True
    assert "infrastructure/stage_acquisition_universe_commit.py" not in STAGE_SERVICE_OVERLAY_PATHS
    assert "infrastructure/stage_acquisition_universe_contracts.py" not in STAGE_SERVICE_OVERLAY_PATHS
    assert (candidate_app / "infrastructure/stage_acquisition_universe_commit.py").read_text() == (
        "# active R1 constructor and source lease\n"
    )
    assert (candidate_app / "infrastructure/stage_acquisition_universe_contracts.py").read_text() == (
        "# active R1 contract helper dependency\n"
    )
    assert receipt["activation_status"] == "NOT_ACTIVATED"


class _FakeMonotonic:
    def __init__(self, value: int = 1):
        self.value = value

    def __call__(self) -> int:
        return self.value


def test_deadline_enforce_stops_before_first_business_write(monkeypatch):
    from stage_center import end_to_end_deadline as deadline

    clock = _FakeMonotonic()
    trace = deadline.Trace(
        entry_ns=1,
        entry_wall_ns=1_800_000_000_000_000_000,
        policy="enforce",
        mono=clock,
        wall=lambda: 1_800_000_000_000_000_000,
    )
    deadline.set_current(trace)
    try:
        clock.value = 1 + deadline.BUDGET_NS + 1
        with pytest.raises(deadline.DeadlineExceeded, match="END_TO_END_5S_EXCEEDED"):
            deadline.begin_write("RAW_PUBLISH")
        assert trace.writes_possible is False
    finally:
        deadline.set_current(None)
        trace.close()


def test_deadline_enforce_downgrades_unwritten_receipt_before_persistence():
    from stage_center import end_to_end_deadline as deadline

    clock = _FakeMonotonic()
    trace = deadline.Trace(
        entry_ns=1,
        entry_wall_ns=1_800_000_000_000_000_000,
        policy="enforce",
        mono=clock,
        wall=lambda: 1_800_000_000_000_000_000,
    )
    deadline.set_current(trace)
    try:
        clock.value = 1 + deadline.BUDGET_NS + 1
        result = deadline.before_receipt({"status": "READY", "write_performed": False})
        assert result["status"] == "CANNOT_CONFIRM"
        assert result["first_failed_layer"] == "END_TO_END_DEADLINE"
        assert result["partial_commit_possible"] is False
    finally:
        deadline.set_current(None)
        trace.close()


def test_deadline_after_durable_receipt_rewrites_failure_and_clears_marker(tmp_path):
    from stage_center import end_to_end_deadline as deadline

    receipt_path = tmp_path / "20260924" / "STAGE_0925" / "receipt.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(json.dumps({"status": "READY", "write_performed": True}))
    clock = _FakeMonotonic()
    trace = deadline.Trace(
        entry_ns=1,
        entry_wall_ns=1_800_000_000_000_000_000,
        policy="enforce",
        mono=clock,
        wall=lambda: 1_800_000_000_000_000_000,
    )
    trace.writes_possible = True
    deadline.set_current(trace)
    persisted = []
    marker_during_rewrite = []
    try:
        clock.value = 1 + deadline.BUDGET_NS + 1

        def rewrite(value):
            marker_during_rewrite.append(deadline.pending_receipt_marker(receipt_path).is_file())
            receipt_path.write_text(json.dumps(dict(value)))
            persisted.append(dict(value))
            return dict(value)

        result = deadline.complete_receipt(
            receipt_path,
            {"status": "READY", "write_performed": True, "node_outcome": "SETTLED"},
            rewrite=rewrite,
        )
        assert result["status"] == "PARTIAL_COMMIT_RETRY_REQUIRED"
        assert result["deadline_receipt_pending_marker_status"] == "CREATED"
        assert marker_during_rewrite == [True]
        assert result["deadline_status"] == "EXCEEDED"
        assert result["partial_commit_possible"] is True
        assert persisted and json.loads(receipt_path.read_text())["status"] == "PARTIAL_COMMIT_RETRY_REQUIRED"
        assert result["deadline_receipt_pending_marker_cleanup_status"] == "REMOVED"
        assert not deadline.pending_receipt_marker(receipt_path).exists()
        assert trace.final["status"] == "PARTIAL_COMMIT_RETRY_REQUIRED"
        assert [event["phase"] for event in trace.events].count("FINAL_RECEIPT_COMPLETED") == 2
    finally:
        deadline.set_current(None)
        trace.close()


def test_failed_deadline_receipt_rewrite_leaves_pending_marker_fail_closed(tmp_path):
    from ops import run_stage_center_nodes as nodes
    from stage_center import end_to_end_deadline as deadline

    trade_date = "20260924"
    stage_id = "STAGE_0925"
    receipt_path = tmp_path / trade_date / stage_id / "receipt.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(json.dumps({"trade_date": trade_date, "stage_id": stage_id, "status": "READY"}))
    clock = _FakeMonotonic()
    trace = deadline.Trace(
        entry_ns=1,
        entry_wall_ns=1_800_000_000_000_000_000,
        policy="enforce",
        mono=clock,
        wall=lambda: 1_800_000_000_000_000_000,
    )
    trace.writes_possible = True
    deadline.set_current(trace)
    try:
        clock.value = 1 + deadline.BUDGET_NS + 1

        def fail_rewrite(_value):
            raise OSError("fixture rewrite failure")

        result = deadline.complete_receipt(
            receipt_path,
            {"status": "READY", "write_performed": True, "node_outcome": "SETTLED"},
            rewrite=fail_rewrite,
        )
        assert result["deadline_receipt_rewrite_status"] == "FAILED"
        assert deadline.pending_receipt_marker(receipt_path).is_file()
        reread = nodes._read_receipt({"receipt_root": str(tmp_path)}, trade_date, stage_id)
        assert reread["status"] == "CANNOT_CONFIRM"
        assert reread["deadline_receipt_pending"] is True
    finally:
        deadline.set_current(None)
        trace.close()


def test_stage_check_exposes_observe_only_timing_without_provider_or_business_writes(
    tmp_path, monkeypatch, capsys
):
    import sys

    from ops import run_stage_center_nodes as nodes

    config = {key: str(tmp_path / key) for key in nodes.REQUIRED_CONFIG_KEYS}
    config.update(
        python_path=sys.executable,
        shared_data_root=str(Path(__file__).resolve().parents[1] / "upstreams/v3_shared_data"),
        node_max_attempts=3,
        node_retry_backoff_seconds=60,
        node_calendar_wait_max_seconds=5,
        safety={"production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
    )
    path = tmp_path / "stage_center_tick_config.json"
    path.write_text(json.dumps(config))
    before = path.read_bytes()
    monkeypatch.setenv("V4_STAGE_DEADLINE_POLICY", "observe")
    monkeypatch.delenv("V4_STAGE_TRACE_PATH", raising=False)
    monkeypatch.delenv("V4_STAGE_PARENT_START_NS", raising=False)

    rc = nodes.main(["--config", str(path), "--check", "--trade-date", "20260924"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["status"] == "CHECK_OK"
    timing = payload["end_to_end_deadline"]
    assert timing["budget_ns"] == 5_000_000_000
    assert timing["policy"] == "observe"
    assert timing["business_write_may_have_occurred"] is False
    assert timing["final_receipt"] is None
    assert {event["phase"] for event in timing["events"]} >= {
        "ENTRY_ANCHOR", "IMPORTS_ARGUMENTS_DONE", "CONFIG_LOADED"
    }
    assert path.read_bytes() == before


def _r6_candidate_app() -> Path:
    value = os.environ.get("V4_STAGE_R6_CANDIDATE_APP")
    if not value:
        pytest.skip("R6 release-composition tests require V4_STAGE_R6_CANDIDATE_APP")
    app = Path(value).expanduser().resolve()
    if not (app.parent / "release-manifest.json").is_file():
        pytest.fail(f"R6 final candidate manifest is missing: {app.parent}")
    return app


def _run_r6_candidate_script(candidate_app: Path, tmp_path: Path, script: str) -> str:
    env = os.environ.copy()
    inherited_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(candidate_app), inherited_pythonpath) if value
    )
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-B", "-c", textwrap.dedent(script), str(candidate_app), str(tmp_path.resolve())],
        cwd=candidate_app,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout


def test_final_r6_release_materializer_reaches_commit_publish(tmp_path):
    candidate_app = _r6_candidate_app()
    output = _run_r6_candidate_script(
        candidate_app,
        tmp_path,
        """
        import hashlib
        import sys
        from pathlib import Path

        app = Path(sys.argv[1]).resolve()
        scratch = Path(sys.argv[2]).resolve()
        materializer_path = app / "ops/materialize_stage_acquisition_universe.py"
        commit_path = app / "infrastructure/stage_acquisition_universe_commit.py"
        contracts_path = app / "infrastructure/stage_acquisition_universe_contracts.py"
        expected_sha = "93337cce801dcff612725399e67bc4400e63750794570f319f6b910be67f202c"
        expected_commit_sha = "4241eeaba00dd2d313bb9cc77e59c947107b7a5943f25bd8cd6a13205365fffe"
        expected_contracts_sha = "f3b5403b9ece54c24f47ed69fffdd88e3cb01503f5129a63bdb217012b784d87"
        assert hashlib.sha256(materializer_path.read_bytes()).hexdigest() == expected_sha
        assert hashlib.sha256(commit_path.read_bytes()).hexdigest() == expected_commit_sha
        assert hashlib.sha256(contracts_path.read_bytes()).hexdigest() == expected_contracts_sha

        from ops import materialize_stage_acquisition_universe as materializer
        assert Path(materializer.__file__).resolve() == materializer_path

        import infrastructure.stage_acquisition_universe_commit as commit_module
        import infrastructure.stage_acquisition_universe_contracts as contracts_module
        from infrastructure.preselection_pool_store import PreselectionSourceResolver
        from infrastructure.stage_acquisition_universe_commit import StageAcquisitionUniverseCommit
        assert Path(commit_module.__file__).resolve() == commit_path
        assert Path(contracts_module.__file__).resolve() == contracts_path

        data_root = scratch / "stage-data"
        source_root = scratch / "source-data"
        data_root.mkdir(parents=True)
        source_root.mkdir(parents=True)
        calls = []
        materializer.build_artifact = lambda *args, **kwargs: {
            "schema_version": "test-only",
            "trade_date": "20260925",
        }

        def record_publish(self, payload, *, run_id=None, identity=None):
            assert isinstance(self, StageAcquisitionUniverseCommit)
            assert isinstance(self.pool_reader, PreselectionSourceResolver)
            assert self.pool_reader.source_root == source_root
            calls.append((dict(payload), run_id, identity))
            return {"artifact": dict(payload), "run_id": run_id}

        StageAcquisitionUniverseCommit.publish = record_publish
        result = materializer.materialize_stage_acquisition_universe(
            data_root,
            "20260925",
            run_id="r6-materializer-contract",
            release_id="r6-test-only",
            preselection_source_root=source_root,
        )
        assert len(calls) == 1
        assert calls[0][0]["trade_date"] == "20260925"
        assert calls[0][1] == "r6-materializer-contract"
        assert result["run_id"] == "r6-materializer-contract"
        assert result["artifact"]["schema_version"] == "test-only"
        print("FINAL_MATERIALIZER_COMMIT_CALL=PASS")
        """,
    )
    assert "FINAL_MATERIALIZER_COMMIT_CALL=PASS" in output


def test_final_r6_release_shared_source_lock_failure_fails_closed(tmp_path):
    candidate_app = _r6_candidate_app()
    output = _run_r6_candidate_script(
        candidate_app,
        tmp_path,
        """
        import fcntl
        import json
        import os
        import sys
        from pathlib import Path

        app = Path(sys.argv[1]).resolve()
        scratch = Path(sys.argv[2]).resolve()
        sys.path.insert(0, str(app))
        import infrastructure.stage_acquisition_universe_commit as commit_module
        from infrastructure.preselection_pool_store import PreselectionSourceResolver

        trade_date = "20260925"
        source_root = scratch / "source-data"
        stage_root = scratch / "stage-data"
        source_pool_root = source_root / "preselection_pools"
        (source_pool_root / trade_date).mkdir(parents=True)
        stage_root.mkdir(parents=True)
        lock_path = source_pool_root / ".materialize.lock"
        lock_path.write_text(json.dumps({
            "schema_version": "v3_5_interprocess_lock.v1",
            "pid": 2147483647,
            "token": "RELEASED",
        }))
        lock_path.chmod(0o600)
        lock_fd = os.open(lock_path, os.O_RDONLY)
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        original_lease = PreselectionSourceResolver.source_read_lease
        def immediate_shared_lease(self, date):
            return original_lease(self, date, timeout_seconds=0)
        PreselectionSourceResolver.source_read_lease = immediate_shared_lease

        class SecureSpy:
            entered = False
            def __enter__(self):
                self.entered = True
                return self
            def __exit__(self, *_args):
                return False

        secure = SecureSpy()
        module = commit_module
        module.read_strict_a_preselection_snapshot = lambda *_args, **_kwargs: object()
        module._validate_physical_input = lambda *_args, **_kwargs: None
        module._normalize_strict_artifact = lambda payload, *_args, **_kwargs: dict(payload)
        module._validate_artifact = lambda *_args, **_kwargs: None
        module._canonical_bytes = lambda *_args, **_kwargs: b"{}"
        module._canonical_sha = lambda *_args, **_kwargs: "a" * 64
        module._raw_sha = lambda *_args, **_kwargs: "b" * 64
        module._safe_run = lambda *_args, **_kwargs: "r6-lock-failure"
        module._paths = lambda *_args, **_kwargs: {}
        module._manifest = lambda *_args, **_kwargs: {}
        module._receipt = lambda *_args, **_kwargs: {}

        store = module.StageAcquisitionUniverseCommit(
            stage_root,
            preselection_source_root=source_root,
        )
        store._secure = lambda: secure
        identity = module.EvidenceIdentity(
            owner_id="V3_5_STAGE_CENTER",
            producer_id="ops.materialize_stage_acquisition_universe",
            release_id="r6-test-only",
            lane_id="A_SHARE_STAGE_ACQUISITION",
        )
        try:
            try:
                store.publish({"trade_date": trade_date}, run_id="r6-lock-failure", identity=identity)
            except ValueError as error:
                assert str(error) == "preselection source read-lock timeout"
            else:
                raise AssertionError("shared source lock failure did not stop publication")
            assert secure.entered is False
            assert not list(stage_root.rglob("*.json"))
            print("SHARED_SOURCE_LOCK_FAILURE_FAIL_CLOSED=PASS")
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        """,
    )
    assert "SHARED_SOURCE_LOCK_FAILURE_FAIL_CLOSED=PASS" in output
