from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


TASK_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = TASK_ROOT / "candidate" / "app"
OPERATOR = TASK_ROOT / "prepare_manager_daily_binding.py"
SOURCE_DATA = TASK_ROOT / "manager_daily_canary_20261006_v2" / "data"
CLI_ROOT_ENV_KEYS = (
    "V35_APP_ROOT", "V35_DATA_ROOT", "V35_SHARED_DATA_ROOT",
    "V4_MANAGER_RESEARCH_STATE_ROOT", "V4_MANAGER_SECURITY_MASTER_ROOT",
    "V4_MANAGER_SCREEN_AUTHORITY_ROOT", "V35_RESEARCH_DATA_ROOT",
)
PRESERVED_ROOT_ENV_KEYS = (
    "V35_RUNTIME_ROOT", "V35_DISPATCH_LEDGER_ROOT", "V35_PRESELECTION_SOURCE_ROOT",
    "V35_STAGE_CENTER_SELECTION_ROOT", "V35_RELEASE_MANIFEST_PATH", "V4_DAILY_REVIEW_ROOT",
    "V4_REVIEW_GENERATION_BINDINGS_PATH", "V4_INTRADAY_RESEARCH_ROOT",
    "V35_REVIEW_CORE_PACKAGE_ROOT", "V35_REVIEW_CORE_RUNTIME_ROOT",
    "V35_REVIEW_CORE_FUPAN_STORE_ROOT", "V35_REVIEW_CORE_STAGE7_STORE_ROOT",
    "REVIEW_CORE_PACKAGE_ROOT", "REVIEW_CORE_DATA_ROOT", "REVIEW_CORE_FUPAN_POOL_ROOT",
    "REVIEW_CORE_STAGE7_POOL_ROOT", "V4_MANAGER_NEWS_DATA_ROOT",
    "V4_MANAGER_NEWS_OWNER_ROOT", "V35_REVIEW_CORE_CLOSE_ROOT",
    "V4_CLOSE_REBOUND_AUTHORITY_ROOT", "V35_MORNING_NEWS_DATA_ROOT",
    "V4_MANAGER_VIBE_BINDING", "V4_MANAGER_UNIVERSE_OWNER_ROOT",
    "V4_MANAGER_UNIVERSE_ROOT", "V4_MANAGER_PLAN_OWNER_BINDING_PATH",
    "V4_WECHAT_ARCHIVE_ROOT",
)


def _copy_owner_tree(source: Path, destination: Path) -> Path:
    shutil.copytree(source, destination)
    return destination.resolve()


def _assert_disjoint(paths: list[Path]) -> None:
    for index, left in enumerate(paths):
        for right in paths[index + 1 :]:
            assert left != right
            assert left not in right.parents
            assert right not in left.parents


def test_binding_operator_uses_distinct_roots_and_real_owner_http_readback(tmp_path: Path) -> None:
    fixture = tmp_path.resolve()
    data = _copy_owner_tree(SOURCE_DATA, fixture / "v4-owner-data")
    shared = (fixture / "v35-shared-data").resolve()
    manager_state = (fixture / "manager-state").resolve()
    security_master = (fixture / "manager-security-master").resolve()
    screen_authority = (fixture / "manager-screen-authority").resolve()
    research = _copy_owner_tree(SOURCE_DATA, fixture / "research-source")
    research_ledger = (fixture / "research-ledger").resolve()
    evidence = (fixture / "evidence").resolve()
    for root in (shared, manager_state, security_master, screen_authority, research_ledger):
        root.mkdir()

    # The CLI-owned roots intentionally start with different inherited values.
    # Other R17 owner roots are valid isolated fixtures and must remain intact.
    inherited = os.environ.copy()
    old_cli_roots = (fixture / "old-cli-roots").resolve()
    old_cli_roots.mkdir()
    for name in CLI_ROOT_ENV_KEYS:
        path = (old_cli_roots / name).resolve()
        path.mkdir()
        inherited[name] = str(path)
    inherited_roots = (fixture / "inherited-owner-roots").resolve()
    inherited_roots.mkdir()
    preserved_values: dict[str, str] = {}
    for name in PRESERVED_ROOT_ENV_KEYS:
        path = (inherited_roots / name).resolve()
        if name.endswith("_PATH") or name.endswith("_BINDING"):
            path.write_text("{}\n", encoding="utf-8")
        else:
            path.mkdir()
        preserved_values[name] = str(path)
        inherited[name] = str(path)

    roots = [APP_ROOT.resolve(), data, shared, manager_state, security_master,
             screen_authority, research, research_ledger,
             Path(preserved_values["V35_STAGE_CENTER_SELECTION_ROOT"]), evidence]
    _assert_disjoint(roots)

    # Bind the inherited HK-universe owner to an isolated copy of the exact
    # implementation file expected by that reader. The paired SHA is a
    # non-root config value and must survive too, but is not emitted in receipts.
    universe_owner = Path(preserved_values["V4_MANAGER_UNIVERSE_OWNER_ROOT"])
    owner_file = universe_owner / "stage_center" / "hk_universe_preflight.py"
    owner_file.parent.mkdir()
    shutil.copy2(APP_ROOT / "stage_center" / "hk_universe_preflight.py", owner_file)
    owner_sha = hashlib.sha256(owner_file.read_bytes()).hexdigest()
    inherited["V4_MANAGER_UNIVERSE_OWNER_SHA256"] = owner_sha
    inherited["V4_REVIEW_GENERATION_BINDINGS_SHA256"] = hashlib.sha256(
        Path(preserved_values["V4_REVIEW_GENERATION_BINDINGS_PATH"]).read_bytes()
    ).hexdigest()
    inherited["V35_RELEASE_MANIFEST_SHA256"] = hashlib.sha256(
        Path(preserved_values["V35_RELEASE_MANIFEST_PATH"]).read_bytes()
    ).hexdigest()

    # The Vibe binding is a real isolated config object with no date inputs, so
    # it remains a valid owner setting while correctly yielding missing inputs.
    vibe_state = (fixture / "inherited-owner-roots" / "vibe-state").resolve()
    vibe_state.mkdir()
    vibe_path = Path(preserved_values["V4_MANAGER_VIBE_BINDING"])
    vibe_path.write_text(json.dumps({
        "schema_version": "v4.manager_existing_vibe_binding.v1",
        "state_root": str(vibe_state),
        "implementation_manifest_sha256": "0" * 64,
        "input_sha256_by_date": {},
    }), encoding="utf-8")

    command = [
        sys.executable, str(OPERATOR),
        "--app-root", str(APP_ROOT.resolve()),
        "--data-root", str(data),
        "--shared-data-root", str(shared),
        "--manager-state-root", str(manager_state),
        "--security-master-root", str(security_master),
        "--screen-authority-root", str(screen_authority),
        "--research-data-root", str(research),
        "--research-ledger-root", str(research_ledger),
        "--target-date", "20261006",
        "--evidence-dir", str(evidence),
        "--execute-owner-write",
    ]
    result = subprocess.run(command, cwd=APP_ROOT, env=inherited, capture_output=True,
                            text=True, timeout=180, check=False)
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"

    receipt = json.loads((evidence / "preparation_receipt.json").read_text())
    assert receipt["schema_version"] == "manager_daily_chain.binding_preparation_receipt.v2"
    assert receipt["validation"] == "PASS"
    assert receipt["live_binding_installed"] is False
    owner_env = receipt["owner_root_environment"]
    inherited_owner_env = owner_env["inherited"]
    effective_owner_env = owner_env["effective"]
    assert set(owner_env["whitelist"]) == set(CLI_ROOT_ENV_KEYS) | set(PRESERVED_ROOT_ENV_KEYS)
    assert set(inherited_owner_env) == set(owner_env["whitelist"])
    assert set(effective_owner_env) == set(owner_env["whitelist"])
    assert set(CLI_ROOT_ENV_KEYS).issubset(owner_env["cli_overridden"])
    assert not ({"HTTP_PROXY", "HTTPS_PROXY", "V4_MANAGER_UNIVERSE_OWNER_SHA256"}
                & set(effective_owner_env))
    for name, expected in preserved_values.items():
        assert inherited_owner_env[name] == expected
        assert effective_owner_env[name] == expected
    assert inherited_owner_env["V4_MANAGER_UNIVERSE_OWNER_ROOT"] != str(security_master)
    assert inherited_owner_env["V4_MANAGER_NEWS_DATA_ROOT"] != str(data)
    cli_values = {
        "V35_APP_ROOT": str(APP_ROOT.resolve()),
        "V35_DATA_ROOT": str(data),
        "V35_SHARED_DATA_ROOT": str(shared),
        "V4_MANAGER_RESEARCH_STATE_ROOT": str(manager_state),
        "V4_MANAGER_SECURITY_MASTER_ROOT": str(security_master),
        "V4_MANAGER_SCREEN_AUTHORITY_ROOT": str(screen_authority),
        "V35_RESEARCH_DATA_ROOT": str(research),
    }
    for name, expected in cli_values.items():
        assert inherited_owner_env[name] != expected
        assert effective_owner_env[name] == expected
    assert receipt["resolved_roots"] == {
        "api_app_root": str(APP_ROOT.resolve()),
        "api_data_root": str(data),
        "v35_shared_data_root": str(shared),
        "manager_state_root": str(manager_state),
        "manager_security_master_root": str(security_master),
        "manager_screen_authority_root": str(screen_authority),
        "research_data_root": str(research),
        "research_ledger_root": str(research_ledger),
        "stage_center_selection_root": preserved_values["V35_STAGE_CENTER_SELECTION_ROOT"],
        "workspace_ledger_root": None,
        "us_peripheral_owner_root": str(data),
    }
    _assert_disjoint([APP_ROOT.resolve(), data, shared, manager_state,
                      security_master, screen_authority, research, research_ledger])

    binding_path = evidence / "candidate_manager_plan_binding.json"
    binding_raw = binding_path.read_bytes()
    binding = json.loads(binding_raw)
    assert hashlib.sha256(binding_raw).hexdigest() == receipt["binding_sha256"]
    assert binding["app_root"] == str(APP_ROOT.resolve())
    assert binding["security_master_root"] == str(security_master)
    assert binding["plan_activation_receipt"]["sha256"] == receipt["canary_sha256"]

    canary = json.loads((evidence / "plan_refresh_owner_evidence.v2.json").read_text())
    assert canary["schema_version"] == "manager_daily_chain.plan_refresh_owner_evidence.v2"
    assert canary["transport"] == "ASGI_TESTCLIENT_IN_PROCESS_NOT_LIVE_HTTP"
    assert canary["target_trade_date"] == "20261006"
    assert canary["owner"] == "ManagerResearchJobService.refresh_workspace_plan"
    assert canary["execution_kind"] == "MANUAL_REFRESH"
    assert canary["formal_recommendation_count"] == 0
    assert canary["research_only"] is True
    assert canary["production_allowed"] is False
    assert canary["buy_gate_updated"] is False
    assert canary["orders_sent"] is False

    run_id = canary["run_id"]
    plan_path = manager_state / "workspace_plans" / "20261006" / f"{run_id}.json"
    persisted = json.loads(plan_path.read_text())
    assert persisted["target_trade_date"] == "20261006"
    assert persisted["run_id"] == run_id
    assert persisted["sha256"] == canary["product_sha256"]
    assert persisted["execution_kind"] == "MANUAL_REFRESH"
    assert persisted["owner"] == canary["owner"]

    for response_name, body_name, expected_status in (
        ("POST", "refresh-response.bin", 200),
        ("GET", "readback-response.bin", 200),
    ):
        http = receipt["owner_http_evidence"]
        assert http[f"{response_name}_status"] == expected_status
        response = http[response_name]
        raw = (evidence / "owner_http_evidence" / body_name).read_bytes()
        assert response["bytes"] == len(raw)
        assert response["sha256"] == hashlib.sha256(raw).hexdigest()
        body = json.loads(raw)
        assert body["plan_product"]["status"] == "CURRENT"
        assert body["plan_product"]["run_id"] == run_id
        assert body["plan_product"]["sha256"] == persisted["sha256"]

    stage_observation = canary["stage_selection_observation"]
    assert stage_observation["root"] == preserved_values["V35_STAGE_CENTER_SELECTION_ROOT"]
    assert stage_observation["response_source"] == "SHARED_STAGE_CENTER"
    assert stage_observation["trade_date"] == "20261006"
    assert stage_observation["stage_id"] == "STAGE_0935_0940"
    assert stage_observation["hk_connect_market_present"] is True
    assert stage_observation["write_performed"] is False
    assert len(stage_observation["sha256"]) == 64


def test_binding_operator_rejects_manager_state_overlap_with_each_owner_root(tmp_path: Path) -> None:
    fixture = tmp_path.resolve()
    roots = {
        "owner-data": fixture / "v4-owner-data",
        "shared-data": fixture / "v35-shared-data",
        "security-master": fixture / "manager-security-master",
        "screen-authority": fixture / "manager-screen-authority",
        "research-data": fixture / "research-source",
        "research-ledger": fixture / "research-ledger",
        "workspace-ledger": fixture / "workspace-ledger",
        "stage-selection": fixture / "stage-selection",
    }
    for path in roots.values():
        path.mkdir()
    isolated_env = os.environ.copy()
    isolated_env["V35_STAGE_CENTER_SELECTION_ROOT"] = str(roots["stage-selection"].resolve())

    for name, overlapping_state in [("app", APP_ROOT.resolve()), *roots.items()]:
        evidence = fixture / f"blocked-evidence-{name}"
        command = [
            sys.executable, str(OPERATOR),
            "--app-root", str(APP_ROOT.resolve()),
            "--data-root", str(roots["owner-data"].resolve()),
            "--shared-data-root", str(roots["shared-data"].resolve()),
            "--manager-state-root", str(overlapping_state.resolve()),
            "--security-master-root", str(roots["security-master"].resolve()),
            "--screen-authority-root", str(roots["screen-authority"].resolve()),
            "--research-data-root", str(roots["research-data"].resolve()),
            "--research-ledger-root", str(roots["research-ledger"].resolve()),
            "--target-date", "20261006",
            "--evidence-dir", str(evidence.resolve()),
            "--execute-owner-write",
        ]
        if name == "workspace-ledger":
            command.extend(("--workspace-ledger-root", str(roots["workspace-ledger"].resolve())))
        result = subprocess.run(command, cwd=APP_ROOT, capture_output=True, text=True,
                                env=isolated_env, timeout=30, check=False)
        assert result.returncode != 0, f"overlap was accepted for {name}"
        assert "OWNER_STATE_PATHS_OVERLAP" in result.stderr, result.stderr
        assert not evidence.exists(), f"operator wrote evidence before rejecting {name} overlap"
