"""R3 contracts for the actual API consumer and the separate HK child replay.

Every data file created here is synthetic and below pytest's tmp_path.  The
API-side reader is invoked through the real workspace_plan callsite; its
read_verified_daily_supplement function is never replaced by a spy.  The old
R1 tests and their two previously recorded screen failures remain unchanged.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

import test_hk_daily_publication_chain as original_chain
import test_hk_daily_supplement_r4 as original_supplement
from v3_shared_data.shared_data import hk_daily_supplement as api_supplement
from v4.manager_research import workspace_plan


ROOT = Path(__file__).resolve().parents[1]
HK_CHILD_ROOT = Path(os.environ.get(
    "V4_R3_HK_CHILD_ROOT", str(ROOT.parent / "hk_child_candidate"),
)).resolve()
INPUT_PACKAGE_ROOT = Path(os.environ.get(
    "V4_R3_INPUT_PACKAGE_ROOT",
    str(ROOT.parent / "input/remote/handoff/manager-daily-failure-20261009-r3/package"),
)).resolve()
OWNER_TEST_DEPENDENCY_ROOT = Path(os.environ.get(
    "V4_R3_OWNER_TEST_DEPENDENCY_ROOT",
    str(ROOT.parent / "hk_validation/test_dependencies"),
)).resolve()
API_SUPPLEMENT_SHA = "f71d6bb8bc0d55a0205d9734562c37d249654e3e39ccc85e18dd6398aa3c3862"
HK_FILES = {
    "ops/macos_research_panel_daily.py":
        "1963990fcde99b2681c837b8b66ea12f1ab066aba47729af5d0900073bc79ef3",
    "ops/_macos_research_panel_daily_parts/hk_capture_gate.py":
        "d07be30a40c35aee9d710fcdcc7ae66b031488cc4c5e7029824e3c76ed3fd71c",
    "ops/ensure_hk_security_master.py":
        "495ced4f0f06f170606ee576e035dafc99b540cd9fad0a28f2f2a36e5989ddb9",
    "ops/_macos_research_panel_daily_parts/_namespace.py":
        "45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1",
}
TARGET = original_supplement.TARGET
SESSIONS = original_supplement.SESSIONS


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inventory(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): _sha(path)
            for path in root.rglob("*") if path.is_file()}


def _api_consumer_read(root: Path, *, cutoff="2026-10-01T03:01:00+00:00",
                       requested=None, panel=None, master=None, names=None):
    expected_file = ROOT / "v3_shared_data/shared_data/hk_daily_supplement.py"
    assert Path(api_supplement.__file__).resolve() == expected_file.resolve()
    assert _sha(expected_file) == API_SUPPLEMENT_SHA
    panel = panel or {
        **original_supplement.PANEL_ID,
        "panel_available_at": original_supplement.PANEL_ID["manifest_prepared_at"],
    }
    master = master or dict(original_supplement.MASTER_ID)
    names = names or {code: {"name": "Synthetic issuer"}
                      for code in original_supplement.MASTER_CODES}
    return workspace_plan._read_hk02_daily_supplement_witness(
        root, TARGET, requested or list(SESSIONS), cutoff, panel, master, names,
    )


@pytest.fixture
def published_sidecar(tmp_path, monkeypatch):
    """Use the frozen original producer only to construct offline test bytes."""
    original_supplement._patch_capture_inputs(monkeypatch)
    monkeypatch.setattr(api_supplement, "requested_sessions",
                        lambda day: (list(SESSIONS), "e" * 64))
    fake = original_supplement.FakeAPI()
    root = tmp_path / "synthetic-authority"
    producer = original_supplement.supplement
    outcome = producer.capture_daily_supplement(
        root, target_date=TARGET,
        connector=lambda: (fake, f"{producer.SOURCE_HOST}:{producer.SOURCE_PORT}"),
        clock=original_supplement._clock(
            datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc)),
    )
    assert outcome["status"] == "PARTIAL_WITH_PENDING"
    assert fake.disconnected is True
    monkeypatch.setattr(api_supplement, "_connect",
                        lambda: pytest.fail("the API reader must not collect"))
    return root, outcome


def test_api_callsite_reads_real_sidecar_with_pending_and_unproven_units(published_sidecar):
    root, outcome = published_sidecar
    before = _inventory(root)
    result = _api_consumer_read(root)
    assert result is not None
    assert result["pointer"]["run_id"] == outcome["run_id"]
    assert result["manifest_sha256"] == outcome["manifest_sha256"]
    assert result["raw_capture_sha256"] == outcome["raw_capture_sha256"]
    assert result["records"]["HK.00001"]["status"] == "READY"
    assert result["records"]["HK.00002"]["status"] == "PENDING"
    assert result["records"]["HK.00002"]["missing_sessions"] == [TARGET]
    evidence = workspace_plan._screen_supplement_volume_evidence(result, list(SESSIONS))
    assert evidence["status"] == "NOT_PROVEN"
    assert evidence["unit"] is None
    assert evidence["scope"] == "ALL_SIX_REQUIRED_SESSIONS"
    assert evidence["gaps"] == ["SCREEN_VOLUME_UNIT_OR_SCALE_NOT_PROVEN"]
    assert _inventory(root) == before
    print(json.dumps({"api_consumer_file": api_supplement.__file__,
        "api_consumer_sha256": _sha(Path(api_supplement.__file__)),
        "callsite_file": workspace_plan.__file__,
        "callsite_sha256": _sha(Path(workspace_plan.__file__)),
        "scope": "SYNTHETIC_ACTUAL_API_READER_BEHAVIOR"}, sort_keys=True))


@pytest.mark.parametrize("mismatch", ["panel", "master", "universe"])
def test_api_callsite_rejects_different_source_identity(published_sidecar, mismatch):
    root, _ = published_sidecar
    options = {}
    error = "HK_DAILY_SUPPLEMENT_POINTER_IDENTITY_INVALID"
    if mismatch == "panel":
        options["panel"] = {**original_supplement.PANEL_ID,
            "panel_available_at": original_supplement.PANEL_ID["manifest_prepared_at"],
            "panel_sha256": "f" * 64}
    elif mismatch == "master":
        options["master"] = {**original_supplement.MASTER_ID,
                             "artifact_sha256": "f" * 64}
    else:
        options["names"] = {"HK.00001": {"name": "Synthetic issuer"}}
        error = "HK_DAILY_SUPPLEMENT_UNIVERSE_MISMATCH"
    before = _inventory(root)
    with pytest.raises(ValueError, match=error):
        _api_consumer_read(root, **options)
    assert _inventory(root) == before


def test_api_callsite_rejects_later_publication_and_wrong_six_sessions(published_sidecar):
    root, _ = published_sidecar
    before = _inventory(root)
    with pytest.raises(ValueError, match="HK_DAILY_SUPPLEMENT_POINTER_AFTER_CUTOFF"):
        _api_consumer_read(root, cutoff="2026-10-01T03:00:07+00:00")
    with pytest.raises(ValueError, match="HK_DAILY_SUPPLEMENT_REQUESTED_SESSIONS_INVALID"):
        _api_consumer_read(root, requested=[*SESSIONS[:-1], "20261001"])
    assert _inventory(root) == before


def test_api_callsite_rejects_corrupted_immutable_source(published_sidecar):
    root, _ = published_sidecar
    first = _api_consumer_read(root)
    raw = root / "assets/hk_0_2" / first["pointer"]["raw_capture_relative"]
    raw.write_bytes(raw.read_bytes() + b" ")
    before = _inventory(root)
    with pytest.raises(ValueError, match="HK_DAILY_SUPPLEMENT_CHECKSUM_MISMATCH"):
        _api_consumer_read(root)
    assert _inventory(root) == before


def test_api_callsite_missing_exact_sidecar_does_not_read_other_date(tmp_path, monkeypatch):
    monkeypatch.setattr(api_supplement, "requested_sessions",
                        lambda day: (list(SESSIONS), "e" * 64))
    root = tmp_path / "synthetic-authority"
    other = root / "assets/hk_0_2/daily_supplements/pointers/20260929.json"
    other.parent.mkdir(parents=True)
    other.write_text("not a valid substitute for the exact date", encoding="utf-8")
    before = _inventory(root)
    assert _api_consumer_read(root) is None
    assert _inventory(root) == before


def _load_exact_module(name, path, monkeypatch):
    parent_name, _, leaf = name.rpartition(".")
    parent = importlib.import_module(parent_name) if parent_name else None
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    if parent is not None:
        monkeypatch.setattr(parent, leaf, module, raising=False)
    spec.loader.exec_module(module)
    assert Path(module.__file__).resolve() == path.resolve()
    return module


@pytest.fixture
def original_owner_import_dependencies(monkeypatch):
    """Supply two frozen original imports only to the synthetic owner test.

    These are existing source bytes from the prior-round source inventory,
    not stubs. They are not deployed into either candidate or the HK02 owner.
    The source-head and both original inventory matches are recorded beside
    the files in DEPENDENCY_ORIGIN.json. Their presence here proves no Mac
    runtime dependency or collection/units contract.
    """
    dependencies = {
        "contracts": "ea20a940814915ec1d744b7df23ea48e4287e4baa9716889a648c9210ea3b34e",
        "orchestrator": "a95fa35e17b6090f3bb196ee6bb75a456d9fb918ce64dd4cd78d7d6005d4f46d",
    }
    loaded = {}
    for name, expected_sha in dependencies.items():
        path = OWNER_TEST_DEPENDENCY_ROOT / (
            f"upstreams/v3_shared_data/scripts/live_acquisition/{name}.py")
        assert path.is_file() and not path.is_symlink(), str(path)
        assert _sha(path) == expected_sha
        module = _load_exact_module(
            f"scripts.live_acquisition.{name}", path, monkeypatch)
        loaded[name] = {"file": module.__file__, "sha256": _sha(path)}
    print(json.dumps({"original_owner_test_dependencies": loaded,
        "scope": "FROZEN_PRIOR_SOURCE_IMPORTS_TEST_ONLY"}, sort_keys=True))


@pytest.fixture
def actual_hk_modules(monkeypatch, tmp_path):
    """Load exact child bytes in a separate test-only dependency assembly.

    The original ensure owner loads one pure contract adjacent to __file__.
    Preserve that real loader by copying its real dependency, rather than
    replacing the validation function or adding files to the HK candidate.
    """
    assembly = tmp_path / "child-code"
    for relative, expected_sha in HK_FILES.items():
        path = HK_CHILD_ROOT / relative
        assert path.is_file() and not path.is_symlink(), str(path)
        assert _sha(path) == expected_sha, relative
        target = assembly / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        assert _sha(target) == expected_sha
    contract_rel = "stage_center/hk_universe_preflight.py"
    contract_source = ROOT / contract_rel
    assert _sha(contract_source) == "9d3d2c2d5ff3bd1c7713a9485e88000ae882f58b0a457b734656094606ba2941"
    contract_target = assembly / contract_rel
    contract_target.parent.mkdir(parents=True)
    contract_target.write_bytes(contract_source.read_bytes())
    assert _sha(contract_target) == _sha(contract_source)
    namespace = _load_exact_module(
        "ops._macos_research_panel_daily_parts._namespace",
        assembly / "ops/_macos_research_panel_daily_parts/_namespace.py", monkeypatch)
    gate = _load_exact_module(
        "ops._macos_research_panel_daily_parts.hk_capture_gate",
        assembly / "ops/_macos_research_panel_daily_parts/hk_capture_gate.py", monkeypatch)
    ensure = _load_exact_module("ops.ensure_hk_security_master",
        assembly / "ops/ensure_hk_security_master.py", monkeypatch)
    entry = _load_exact_module("_manager_r3_actual_hk_child",
        assembly / "ops/macos_research_panel_daily.py", monkeypatch)
    monkeypatch.setattr(original_chain, "gate", gate)
    monkeypatch.setattr(original_chain, "_load_actual_layer", lambda: entry)
    return SimpleNamespace(namespace=namespace, gate=gate, ensure=ensure, entry=entry)


def test_actual_hk_entry_uses_preserved_namespace_and_rejects_panel_only(actual_hk_modules, tmp_path):
    modules = actual_hk_modules
    assert modules.namespace.read_global({"answer": 42}, "answer") == 42
    assert modules.namespace.read_global({}, "len")([1, 2]) == 2
    assert modules.gate._v4_global is modules.namespace.read_global
    original_chain.test_legacy_panel_only_lane_receipt_is_not_full_hk_ready(tmp_path)
    print(json.dumps({"hk_child_source_root": str(HK_CHILD_ROOT),
        "dependency_root": str(ROOT), "loaded_modules": {
            name: {"file": module.__file__, "sha256": _sha(Path(module.__file__))}
            for name, module in vars(modules).items()},
        "scope": "ISOLATED_EXPLICIT_CHILD_MODULE_BINDING"}, sort_keys=True))


def test_actual_hk_entry_historical_gap_stops_before_capture(actual_hk_modules, tmp_path, monkeypatch, capsys):
    modules = actual_hk_modules
    monkeypatch.setattr(modules.gate, "_today_shanghai", lambda: "20261009")
    monkeypatch.setattr(modules.gate, "_run_hk_capture_gate_body",
                        lambda *_args, **_kwargs: pytest.fail("old dates require their own exact capture"))
    original_chain.test_actual_entry_hk_lane_reaches_history_guard_without_replacing_a_runner(
        tmp_path, capsys)


def test_actual_hk_reader_keeps_prior_day_readable_after_latest_advances(actual_hk_modules, tmp_path):
    original_chain.test_next_day_pointer_promotion_keeps_prior_immutable_chain_readable(tmp_path)


@pytest.mark.parametrize("reject_readback", [False, True])
def test_actual_hk_entry_original_owner_roundtrip_and_final_gate(
    actual_hk_modules, original_owner_import_dependencies,
    tmp_path, monkeypatch, capsys, reject_readback,
):
    # Retain the original owner test's assertions. Its fake Futu/TDX boundary
    # and fixture updater are test dependencies, not an actual HK02 deployment.
    failures = []
    owner = actual_hk_modules.ensure.ensure_hk_security_master

    def observed_owner(*args, **kwargs):
        try:
            return owner(*args, **kwargs)
        except Exception as exc:
            failures.append({"type": type(exc).__name__, "reason": str(exc),
                             "cause": str(exc.__cause__) if exc.__cause__ else None})
            raise

    monkeypatch.setattr(actual_hk_modules.ensure, "ensure_hk_security_master", observed_owner)
    try:
        original_chain.test_actual_entry_publishes_and_reuses_full_hk_chain_with_original_owners(
            tmp_path, monkeypatch, capsys, reject_readback)
    except AssertionError:
        with capsys.disabled():
            print(json.dumps({"synthetic_owner_failures": failures}, sort_keys=True))
        raise


def test_actual_hk02_missing_supplement_owner_remains_unavailable(actual_hk_modules, tmp_path, monkeypatch):
    updater_root = INPUT_PACKAGE_ROOT / "source_snapshot/hk02_updater_actual"
    updater = updater_root / "scripts/update_hk_0_2_panel.py"
    assert _sha(updater) == "45d31c1e6608d1a9af163ffd56ea111d5caeb40000c58cd140534cf81859634e"
    assert not (updater_root / "shared_data/hk_daily_supplement.py").exists()
    modules = actual_hk_modules
    monkeypatch.setattr(modules.entry.subprocess, "run",
                        lambda *_args, **_kwargs: pytest.fail("missing owner must stop before subprocess"))
    result = modules.gate._run_daily_supplement(
        modules.entry.__dict__,
        args=SimpleNamespace(hk_asset_root=tmp_path / "assets/hk_0_2",
                             hk_tdx_root=tmp_path / "tdx"),
        authority_paths={"--hk-updater-script": updater},
        target="20261008", python_executable=sys.executable,
    )
    assert result == {"status": "CANNOT_CONFIRM", "target_date": "20261008",
                      "reason_code": "HK_DAILY_SUPPLEMENT_OWNER_UNAVAILABLE"}
    assert not (tmp_path / "assets").exists()
    assert not (tmp_path / "tdx").exists()
