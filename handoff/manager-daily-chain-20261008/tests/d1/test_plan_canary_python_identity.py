from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


TASK = Path(__file__).resolve().parents[1]
SCRIPT = TASK / "run_plan_only_historical_canary.py"


def _module():
    spec = importlib.util.spec_from_file_location("d1_historical_canary_python_identity", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_real_staged_api_plist_uses_binding_python_without_scheduler_env_key(tmp_path, monkeypatch):
    module = _module()
    output = tmp_path / "unused-output"
    monkeypatch.setattr(module, "OUTPUT_ROOT", output)

    # Load the actual staged API LaunchAgent plist and R2 disabled binding.
    # Its interpreter is in ProgramArguments; the scheduler-only environment
    # key intentionally is absent from the extracted API environment.
    identity, environment = module._load_release_and_runtime()
    assert "V4_MANAGER_ANNOUNCEMENT_PYTHON" not in environment
    assert "V35_DISPATCH_LEDGER_ROOT" not in environment
    assert identity["binding"]["python"] == sys.executable
    module._validate_execution_python(identity)
    roots = identity["api_runtime_roots"]
    assert roots["data_root"] == Path(environment["V35_DATA_ROOT"])
    assert roots["shared_data_root"] == Path(environment["V35_SHARED_DATA_ROOT"])
    assert roots["ledger_root"] is None
    assert roots["stage_selection_root"] == Path(
        "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/selection")
    assert roots["stage_mode"] == "shared"

    captured = {}
    monkeypatch.setattr(module, "_configure_runtime_environment", lambda _environment: None)
    module._create_candidate_api_app(
        identity, lambda **kwargs: captured.update(kwargs) or object())
    assert captured == {
        "data_root": Path(environment["V35_DATA_ROOT"]),
        "preselection_source_root": None,
        "shared_data_root": Path(environment["V35_SHARED_DATA_ROOT"]),
        "ledger_root": None,
        "stage_center_selection_root": Path(
            "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/selection"),
        "manager_research_state_root": module.FORMAL_MANAGER_STATE,
    }
    result = module.dry_run()
    assert result["status"] == "DRY_RUN_NO_HTTP_NO_WRITE"
    assert result["api_app_root"] == str(module.API_ROOT)
    assert result["release_manifest_sha256"] == module._sha(
        (module.API_RELEASE_ROOT / "release-manifest.json").read_bytes())
    assert result["http_calls"] == []
    assert result["launchctl_called"] is False
    assert not output.exists()


def test_actual_staged_run_arguments_override_environment_and_wrong_root_rejects(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "OUTPUT_ROOT", tmp_path / "unused-output")
    identity, environment = module._load_release_and_runtime()
    plist = module.plistlib.loads(module.PLIST_PATH.read_bytes())
    arguments = list(plist["ProgramArguments"])
    module_index = arguments.index("apps.api.v35_api.run")
    stage_root_arg = arguments.index("--stage-selection-root", module_index + 1)

    # The pinned run.py applies parsed CLI paths before environment fallbacks.
    arguments[stage_root_arg + 1] = str(tmp_path)
    arguments.extend(["--data-root", str(tmp_path)])
    env_stage_root = tmp_path / "env-stage"
    env_stage_root.mkdir()
    env_ledger_root = tmp_path / "env-ledger"
    env_ledger_root.mkdir()
    env_with_roots = {
        **environment,
        "V35_STAGE_CENTER_SELECTION_ROOT": str(env_stage_root),
        "V35_DISPATCH_LEDGER_ROOT": str(env_ledger_root),
    }
    roots = module._resolve_api_runtime_roots(arguments, env_with_roots, str(module.API_ROOT))
    assert roots["data_root"] == tmp_path
    assert roots["stage_selection_root"] == tmp_path
    assert roots["ledger_root"] == env_ledger_root

    # Removing the staged CLI option falls back to the exact run.py env key.
    env_fallback_arguments = list(plist["ProgramArguments"])
    env_stage_index = env_fallback_arguments.index("--stage-selection-root")
    del env_fallback_arguments[env_stage_index:env_stage_index + 2]
    env_fallback = module._resolve_api_runtime_roots(
        env_fallback_arguments, env_with_roots, str(module.API_ROOT))
    assert env_fallback["stage_selection_root"] == env_stage_root
    assert env_fallback["ledger_root"] == env_ledger_root

    # An explicit CLI ledger root wins over the same environment key.
    cli_ledger_root = tmp_path / "cli-ledger"
    cli_ledger_root.mkdir()
    cli_ledger_arguments = list(plist["ProgramArguments"]) + [
        "--ledger-root", str(cli_ledger_root)]
    cli_ledger = module._resolve_api_runtime_roots(
        cli_ledger_arguments, env_with_roots, str(module.API_ROOT))
    assert cli_ledger["ledger_root"] == cli_ledger_root

    wrong_arguments = list(plist["ProgramArguments"])
    wrong_module_index = wrong_arguments.index("apps.api.v35_api.run")
    wrong_stage_root_arg = wrong_arguments.index("--stage-selection-root", wrong_module_index + 1)
    wrong_arguments[wrong_stage_root_arg + 1] = str(tmp_path / "missing")
    with pytest.raises(ValueError, match="D1_API_STAGE_ROOT_NOT_EXACT"):
        module._resolve_api_runtime_roots(wrong_arguments, environment, str(module.API_ROOT))
    assert not (tmp_path / "missing").exists()


def test_wrong_python_is_rejected_before_canary_output_or_state_preimage(tmp_path, monkeypatch):
    module = _module()
    output = tmp_path / "execution-03"
    binding_python = "/allowed/runtime/venvs/v3.5-mac/bin/python"
    monkeypatch.setattr(module, "OUTPUT_ROOT", output)
    monkeypatch.setattr(module, "_load_release_and_runtime", lambda: ({"binding": {"python": binding_python}}, {}))
    monkeypatch.setattr(module.sys, "executable", "/wrong/runtime/venvs/v3.5-mac/bin/python")
    monkeypatch.setattr(module, "_check_target_preimage", lambda: pytest.fail("state preimage read before Python validation"))

    with pytest.raises(ValueError, match="D1_CANARY_PYTHON_IDENTITY_MISMATCH"):
        module.execute()
    assert not output.exists()
