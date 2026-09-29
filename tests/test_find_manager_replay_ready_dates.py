from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "v4" / "manager_research" / "replay_readiness.py"


def _load():
    spec = importlib.util.spec_from_file_location("find_manager_replay_ready_dates", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("module loader missing")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _roots(tmp_path: Path, *, missing_app_sources=()):
    tmp_path = tmp_path.resolve()
    state = tmp_path / "state"
    universe = tmp_path / "universe"
    data = tmp_path / "data"
    news = tmp_path / "news"
    owner = tmp_path / "owner"
    rebound = tmp_path / "rebound"
    app = tmp_path / "materializer"
    for root in (state, universe, data, news, owner, rebound, app):
        root.mkdir(parents=True, exist_ok=True)
    (owner / "stage_center").mkdir()
    (owner / "stage_center" / "hk_universe_preflight.py").write_text("# owner\n", encoding="utf-8")
    (news / "ops").mkdir()
    (news / "ops" / "collect_hourly_research_input.py").write_text("# news\n", encoding="utf-8")
    from v4.manager_research.activation_canary import _MATERIALIZER_RUNTIME_FILES
    missing_app_sources = set(missing_app_sources)
    for relative in _MATERIALIZER_RUNTIME_FILES:
        if relative in missing_app_sources:
            continue
        path = app / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# synthetic app source " + relative + "\n", encoding="utf-8")
    return SimpleNamespace(state=state, universe=universe, data=data, news=news, owner=owner, rebound=rebound, app=app)


def _triple(roots, date: str) -> None:
    base = roots.state / "workbench_research" / date / "inputs"
    _write_json(base / "1530_futu_snapshot.json", {
        "trade_date": date,
        "started_at": f"{date[:4]}-{date[4:6]}-{date[6:]}T15:30:03+08:00",
        "available_at": f"{date[:4]}-{date[4:6]}-{date[6:]}T15:30:20+08:00",
    })
    _write_json(base / "1530_futu_snapshot.json.receipt.json", {"status": "READY"})
    _write_json(base / "1530_rebound_history.json", {"trade_date": date, "source_files": []})


def _complete_actual_inputs(roots, date: str) -> None:
    _triple(roots, date)
    _write_json(roots.universe / "universes" / date / "HK_CONNECT_FULL_MARKET.json", {"synthetic": True})
    _write_json(roots.rebound / "assets/hk_0_2/panel_latest.json", {"synthetic": True})
    _write_json(roots.rebound / "assets/hk_security_master/latest.json", {"synthetic": True})


class FakeReplayApi:
    def __init__(self, *, identity_ok: bool = True):
        self.identity_ok = identity_ok
        self.seed_calls = 0

    def build_replay_seed(self, source, destination, date):
        self.seed_calls += 1
        destination.mkdir(parents=True)
        src = source / "workbench_research" / date / "inputs"
        dst = destination / "workbench_research" / date / "inputs"
        dst.mkdir(parents=True)
        for name in ("1530_futu_snapshot.json", "1530_futu_snapshot.json.receipt.json", "1530_rebound_history.json"):
            (dst / name).write_bytes((src / name).read_bytes())
        return {"status": "READY", "trade_date": date}

    def validate_replay_spec(self, spec, *, state_root):
        return dict(spec)

    def input_identity(self, spec, state):
        if not self.identity_ok:
            return {"universe_date_tree": {"__identity_error__": "UNAVAILABLE_OR_UNSAFE"}}
        from v4.manager_research.activation_canary import _materializer_app_inventory

        app_sources = _materializer_app_inventory(
            Path(spec["materializer_app_root"]), tolerate_missing=True, include_worker_files=False,
        )
        return {
            "state_inputs": {"a": "a" * 64},
            "universe_date_tree": {f"universes/{spec['trade_date']}/HK_CONNECT_FULL_MARKET.json": "b" * 64},
            "rebound_inputs": {"assets/hk_0_2/panel_latest.json": "c" * 64},
            "news_inputs": {"prior_session_date": "20260924", "files": {}},
            "materializer_app_sources": app_sources,
            "universe_owner_source_sha256": "e" * 64,
            "news_owner_source_sha256": "f" * 64,
            "materializer_source_sha256": spec["materializer_source_sha256"],
        }

def _config(module, roots):
    return module.ScanConfig(
        state_root=roots.state,
        universe_root=roots.universe,
        data_root=roots.data,
        news_owner_root=roots.news,
        universe_owner_root=roots.owner,
        universe_owner_sha256=_sha(roots.owner / "stage_center" / "hk_universe_preflight.py"),
        rebound_authority_root=roots.rebound,
        materializer_app_root=roots.app,
        materializer_source_sha256=_sha(roots.app / "ops" / "materialize_manager_close_discovery.py"),
        max_dates=30,
    )


def _cli_args(module, roots, receipt: Path):
    config = _config(module, roots)
    return [
        "--state-root", str(config.state_root),
        "--universe-root", str(config.universe_root),
        "--data-root", str(config.data_root),
        "--news-owner-root", str(config.news_owner_root),
        "--universe-owner-root", str(config.universe_owner_root),
        "--universe-owner-sha256", config.universe_owner_sha256,
        "--rebound-authority-root", str(config.rebound_authority_root),
        "--materializer-app-root", str(config.materializer_app_root),
        "--materializer-source-sha256", config.materializer_source_sha256,
        "--receipt", str(receipt),
    ]


def test_missing_triple_is_not_ready_without_authority_call(tmp_path):
    module = _load()
    roots = _roots(tmp_path)
    date = "20260924"
    base = roots.state / "workbench_research" / date / "inputs"
    base.mkdir(parents=True)
    _write_json(base / "1530_futu_snapshot.json", {"trade_date": date})
    fake = FakeReplayApi()
    result = module.scan_replay_ready_dates(_config(module, roots), replay_api=fake, universe_validator=lambda **_: pytest.fail("must not validate universe"))
    assert result["ready_dates"] == []
    assert result["dates"][0]["status"] == "NOT_READY"
    assert "1530_futu_snapshot.json.receipt.json" in result["dates"][0]["missing"]
    assert fake.seed_calls == 0


def test_universe_authority_failure_keeps_date_not_ready(tmp_path):
    module = _load()
    roots = _roots(tmp_path)
    date = "20260924"
    _triple(roots, date)
    fake = FakeReplayApi()
    result = module.scan_replay_ready_dates(
        _config(module, roots), replay_api=fake,
        universe_validator=lambda **_: {"status": "CANNOT_CONFIRM", "reason": "UNIVERSE_RECEIPT_MISSING"},
    )
    row = result["dates"][0]
    assert row["status"] == "NOT_READY"
    assert row["reason"] == "UNIVERSE_RECEIPT_MISSING"
    assert result["ready_dates"] == []


def test_complete_chain_returns_ready_and_emits_replay_command(tmp_path):
    module = _load()
    roots = _roots(tmp_path)
    date = "20260924"
    _triple(roots, date)
    fake = FakeReplayApi()
    result = module.scan_replay_ready_dates(
        _config(module, roots), replay_api=fake,
        universe_validator=lambda **_: {
            "status": "VERIFIED",
            "run_id": "u-run",
            "sha256": "1" * 64,
            "available_at": "2026-09-24T15:20:00+08:00",
            "code_count": 612,
            "network_calls": 0,
            "external_process_calls": 0,
        },
    )
    assert result["ready_dates"] == [date]
    row = result["dates"][0]
    assert row["status"] == "READY_FOR_REPLAY_CANARY"
    assert row["universe"]["code_count"] == 612
    assert "ops.build_manager_materializer_replay_seed" in row["next_command"]
    assert row["source_unchanged"] is True


def test_identity_error_blocks_ready_even_when_universe_verifies(tmp_path):
    module = _load()
    roots = _roots(tmp_path)
    date = "20260924"
    _triple(roots, date)
    fake = FakeReplayApi(identity_ok=False)
    result = module.scan_replay_ready_dates(
        _config(module, roots), replay_api=fake,
        universe_validator=lambda **_: {"status": "VERIFIED", "network_calls": 0, "external_process_calls": 0},
    )
    assert result["ready_dates"] == []
    assert result["dates"][0]["reason"] == "REPLAY_INPUT_IDENTITY_UNSAFE"


def test_source_change_during_scan_stops_date(tmp_path):
    module = _load()
    roots = _roots(tmp_path)
    date = "20260924"
    _triple(roots, date)
    fake = FakeReplayApi()

    def mutate(**kwargs):
        path = roots.state / "workbench_research" / date / "inputs" / "1530_rebound_history.json"
        _write_json(path, {"trade_date": date, "source_files": [{"artifact_ref": "changed.json"}]})
        return {"status": "VERIFIED", "network_calls": 0, "external_process_calls": 0}

    result = module.scan_replay_ready_dates(_config(module, roots), replay_api=fake, universe_validator=mutate)
    assert result["ready_dates"] == []
    assert result["dates"][0]["reason"] == "SOURCE_CHANGED_DURING_SCAN"
    assert result["dates"][0]["source_unchanged"] is False


def test_scanner_never_executes_replay_or_producer(tmp_path):
    module = _load()
    roots = _roots(tmp_path)
    _triple(roots, "20260924")
    fake = FakeReplayApi()
    result = module.scan_replay_ready_dates(
        _config(module, roots), replay_api=fake,
        universe_validator=lambda **_: {
            "status": "VERIFIED", "network_calls": 0, "external_process_calls": 0,
            "producer_calls": 0,
        },
    )
    assert result["scanner_mode"] == "READ_ONLY_DISCOVERY"
    assert result["network_requests"] == 0
    assert result["producer_calls"] == 0
    assert result["canary_runs"] == 0


def test_mac_temp_root_is_resolved_and_current_v7_helpers_accept_complete_synthetic_fixture(tmp_path):
    module = _load()
    roots = _roots(tmp_path)
    date = "20260924"
    _complete_actual_inputs(roots, date)
    config = _config(module, roots)
    api = module._load_replay_api()
    expected_worker = ROOT.resolve() / "v4/manager_research/materializer_replay.py"
    assert Path(sys.modules[api.validate_replay_spec.__module__].__file__).resolve() == expected_worker
    assert config.materializer_app_root == roots.app
    assert config.materializer_app_root != expected_worker.parents[2]

    result = module.scan_replay_ready_dates(
        config,
        replay_api=api,
        universe_validator=lambda **_: {
            "status": "VERIFIED",
            "run_id": "synthetic-universe-run",
            "sha256": "1" * 64,
            "available_at": "2026-09-24T15:20:00+08:00",
            "code_count": 612,
            "network_calls": 0,
            "external_process_calls": 0,
            "producer_calls": 0,
        },
    )
    assert result["ready_dates"] == [date]
    assert result["dates"][0]["status"] == "READY_FOR_REPLAY_CANARY"


def test_worker_only_r4_files_are_not_required_in_bound_materializer_root(tmp_path):
    module = _load()
    roots = _roots(tmp_path)
    date = "20260924"
    _complete_actual_inputs(roots, date)
    for relative in (
        "ops/run_manager_materializer_offline_replay.py",
        "v4/manager_research/activation_canary.py",
        "v4/manager_research/materializer_replay.py",
    ):
        assert not (roots.app / relative).exists()
    result = module.scan_replay_ready_dates(
        _config(module, roots),
        replay_api=FakeReplayApi(),
        universe_validator=lambda **_: {
            "status": "VERIFIED", "run_id": "synthetic-universe-run",
            "sha256": "1" * 64, "available_at": "2026-09-24T15:20:00+08:00",
            "code_count": 612, "network_calls": 0, "external_process_calls": 0, "producer_calls": 0,
        },
    )
    assert result["ready_dates"] == [date]


@pytest.mark.parametrize(
    "missing_source",
    (
        "domains/manager_close_discovery.py",
        "apps/__init__.py",
        "apps/api/__init__.py",
        "apps/api/v35_api/__init__.py",
        "contracts/__init__.py",
        "infrastructure/__init__.py",
        "upstreams/v3_shared_data/shared_data/__init__.py",
        "upstreams/v3_shared_data/shared_data/allowlist.py",
        "upstreams/v3_shared_data/shared_data/collectors.py",
        "upstreams/v3_shared_data/shared_data/constants.py",
        "upstreams/v3_shared_data/shared_data/consumer.py",
        "upstreams/v3_shared_data/shared_data/hashing.py",
        "upstreams/v3_shared_data/shared_data/hk_0_2.py",
        "upstreams/v3_shared_data/shared_data/hk_security_master.py",
        "upstreams/v3_shared_data/shared_data/paths.py",
        "upstreams/v3_shared_data/shared_data/store.py",
    ),
)
def test_missing_actual_materializer_runtime_source_cannot_be_ready(tmp_path, missing_source):
    module = _load()
    roots = _roots(tmp_path, missing_app_sources=(missing_source,))
    date = "20260924"
    _complete_actual_inputs(roots, date)
    validator_calls = []
    def validator(**_kwargs):
        validator_calls.append(True)
        return {"status": "VERIFIED", "network_calls": 0, "external_process_calls": 0, "producer_calls": 0}
    result = module.scan_replay_ready_dates(_config(module, roots), universe_validator=validator)
    assert result["ready_dates"] == []
    assert result["dates"][0]["status"] == "NOT_READY"
    assert result["dates"][0]["reason"] == "REPLAY_INPUT_IDENTITY_UNSAFE"
    assert validator_calls == []


@pytest.mark.parametrize(
    "dependency_path",
    (
        "upstreams/v3_shared_data/shared_data/allowlist.py",
        "upstreams/v3_shared_data/shared_data/hk_security_master.py",
    ),
)
def test_stable_runtime_dependency_hash_change_is_not_a_fixed_authority_mismatch(tmp_path, dependency_path):
    module = _load()
    roots = _roots(tmp_path)
    date = "20260924"
    _complete_actual_inputs(roots, date)
    dependency = roots.app / dependency_path
    dependency.write_text("# different but stable source bytes\n", encoding="utf-8")
    result = module.scan_replay_ready_dates(
        _config(module, roots), replay_api=FakeReplayApi(),
        universe_validator=lambda **_: {
            "status": "VERIFIED", "run_id": "synthetic-universe-run",
            "sha256": "1" * 64, "available_at": "2026-09-24T15:20:00+08:00",
            "code_count": 612, "network_calls": 0, "external_process_calls": 0, "producer_calls": 0,
        },
    )
    assert result["ready_dates"] == [date]
    assert result["dates"][0]["status"] == "READY_FOR_REPLAY_CANARY"


@pytest.mark.parametrize(
    "dependency_path",
    (
        "upstreams/v3_shared_data/shared_data/allowlist.py",
        "upstreams/v3_shared_data/shared_data/hk_security_master.py",
    ),
)
def test_runtime_dependency_changed_during_scan_cannot_be_ready(tmp_path, dependency_path):
    module = _load()
    roots = _roots(tmp_path)
    date = "20260924"
    _complete_actual_inputs(roots, date)
    dependency = roots.app / dependency_path

    def mutate(**_kwargs):
        dependency.write_text("# changed between identity snapshots\n", encoding="utf-8")
        return {
            "status": "VERIFIED", "network_calls": 0,
            "external_process_calls": 0, "producer_calls": 0,
        }

    result = module.scan_replay_ready_dates(
        _config(module, roots), replay_api=FakeReplayApi(), universe_validator=mutate,
    )
    assert result["ready_dates"] == []
    assert result["dates"][0]["reason"] == "SOURCE_CHANGED_DURING_SCAN"
    assert result["dates"][0]["source_unchanged"] is False


@pytest.mark.parametrize(
    ("identity_field", "bad_key"),
    (
        ("universe_date_tree", r"universes/20260924/unexpected\name.json"),
        ("news_inputs.files", "research/incoming/20260924/../../escape.json"),
    ),
)
def test_current_r4_identity_path_gate_blocks_unsafe_keys_before_universe_validation(
    tmp_path, identity_field, bad_key
):
    module = _load()
    roots = _roots(tmp_path)
    date = "20260924"
    _complete_actual_inputs(roots, date)
    validator_calls = []

    class UnsafePathReplayApi(FakeReplayApi):
        def input_identity(self, spec, state):
            identity = super().input_identity(spec, state)
            if identity_field == "universe_date_tree":
                identity[identity_field] = {bad_key: "b" * 64}
            else:
                identity["news_inputs"]["files"] = {bad_key: "b" * 64}
            return identity

    def validator(**_kwargs):
        validator_calls.append(True)
        return {"status": "VERIFIED", "network_calls": 0, "external_process_calls": 0, "producer_calls": 0}

    result = module.scan_replay_ready_dates(
        _config(module, roots), replay_api=UnsafePathReplayApi(), universe_validator=validator
    )
    assert result["ready_dates"] == []
    assert result["dates"][0]["status"] == "NOT_READY"
    assert result["dates"][0]["reason"] == "REPLAY_INPUT_IDENTITY_UNSAFE"
    assert validator_calls == []


def test_input_parent_symlink_matches_v7_origin_fail_closed_gate(tmp_path):
    module = _load()
    roots = _roots(tmp_path)
    date = "20260924"
    outside_inputs = tmp_path.resolve() / "outside-inputs"
    _write_json(outside_inputs / "1530_futu_snapshot.json", {
        "trade_date": date,
        "started_at": "2026-09-24T15:30:03+08:00",
        "available_at": "2026-09-24T15:30:20+08:00",
    })
    _write_json(outside_inputs / "1530_futu_snapshot.json.receipt.json", {"status": "READY"})
    _write_json(outside_inputs / "1530_rebound_history.json", {"trade_date": date, "source_files": []})
    inputs = roots.state / "workbench_research" / date / "inputs"
    inputs.parent.mkdir(parents=True)
    inputs.symlink_to(outside_inputs, target_is_directory=True)
    fake = FakeReplayApi()
    result = module.scan_replay_ready_dates(
        _config(module, roots), replay_api=fake,
        universe_validator=lambda **_: pytest.fail("symlinked inputs must fail before Universe validation"),
    )
    row = result["dates"][0]
    assert row["status"] == "NOT_READY"
    assert row["reason"].startswith("REPLAY_ORIGIN_INPUT_SYMLINK:")
    assert fake.seed_calls == 0


@pytest.mark.parametrize(
    "root_name",
    ["state", "universe", "data", "news", "owner", "rebound", "app"],
)
def test_cli_receipt_is_rejected_inside_every_protected_root(root_name, tmp_path, monkeypatch):
    module = _load()
    roots = _roots(tmp_path)
    protected = getattr(roots, root_name)
    target = protected / "scanner-receipt.json"
    import ops.find_manager_replay_ready_dates as cli

    monkeypatch.setattr(cli, "scan_replay_ready_dates", lambda *_args, **_kwargs: pytest.fail("scan must not start"))
    with pytest.raises(SystemExit) as error:
        cli.main(_cli_args(module, roots, target))
    assert error.value.code == 2
    assert not target.exists()


def test_cli_receipt_symlink_alias_is_rejected_before_scan(tmp_path, monkeypatch):
    module = _load()
    roots = _roots(tmp_path)
    alias = tmp_path.resolve() / "state-alias"
    alias.symlink_to(roots.state, target_is_directory=True)
    target = alias / "scanner-receipt.json"
    import ops.find_manager_replay_ready_dates as cli

    monkeypatch.setattr(cli, "scan_replay_ready_dates", lambda *_args, **_kwargs: pytest.fail("scan must not start"))
    with pytest.raises(SystemExit) as error:
        cli.main(_cli_args(module, roots, target))
    assert error.value.code == 2
    assert not (roots.state / target.name).exists()


def test_cli_receipt_still_writes_to_an_unprotected_synthetic_root(tmp_path, monkeypatch, capsys):
    module = _load()
    roots = _roots(tmp_path)
    target = tmp_path.resolve() / "evidence-output" / "scanner-receipt.json"
    import ops.find_manager_replay_ready_dates as cli

    monkeypatch.setattr(cli, "scan_replay_ready_dates", lambda *_args, **_kwargs: {
        "schema_version": "v4.manager_research.replay_ready_date_scan.v1",
        "ready_count": 0,
        "ready_dates": [],
    })
    result = cli.main(_cli_args(module, roots, target))
    assert result == 3
    assert json.loads(target.read_text()) == {
        "schema_version": "v4.manager_research.replay_ready_date_scan.v1",
        "ready_count": 0,
        "ready_dates": [],
    }
    assert '"ready_count": 0' in capsys.readouterr().out
