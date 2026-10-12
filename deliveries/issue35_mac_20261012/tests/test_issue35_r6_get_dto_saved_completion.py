"""Temp-only tests for the R6 reader-shaped GET validator and saved completion."""
from __future__ import annotations

import copy
import fcntl
import hashlib
import importlib.util
import json
from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pytest


TOOLS = Path(__file__).resolve().parents[1]
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
SPEC = importlib.util.spec_from_file_location(
    "issue35_r6_saved_completion_under_test",
    Path(__file__).with_name("complete_issue35_r6_saved_canary.py"),
)
assert SPEC is not None and SPEC.loader is not None
COMPLETION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMPLETION)
CANARY = COMPLETION.CANARY
COMMON = COMPLETION.common

TARGET = "20261013"
ARCHIVED_ID = "d8a35106712a4387accf214c3ee3772d"
CURRENT_ID = "357d984e400541a48c41f65ec0018b62"
FRESH_ID = "92f257a7a0a841c081d48005f8a3fe3e"
ARCHIVED_INPUT = "3c3f32668945d572af760fdc9b36ad5c577a7167720dc8aaba3fd60ccae9bbd3"
CURRENT_INPUT = "efbf9d580a587edeb58fb80fa4358b45afe45a5d10236f28ad1d3d9d50daa0c9"
FRESH_INPUT = "1d10c2e881ddda942884e7bc5252b0897eb65a2846f3a98cad97ca237b5c88af"
STARTED = "2026-10-12T06:02:59.487836+08:00"
CONTEXT_FINISHED = "2026-10-12T06:03:12.871346+08:00"
ATTEMPT_FINISHED = "2026-10-12T06:03:14.195417+08:00"
PARENT_FINISHED = "2026-10-11T22:03:31.528580+00:00"
NOW = datetime.fromisoformat("2026-10-12T06:20:00+08:00")


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _write_json(path: Path, value: dict) -> bytes:
    raw = _json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return raw


def _attempt(run_id: str, input_identity: str) -> dict:
    context = {
        "trigger_kind": "MANUAL", "timing": "UNCLASSIFIED", "scheduled_for": None,
        "started_at": STARTED, "natural_run_verified": False,
        "trigger_id": "2b031b633552d7923a3cc94a91e65744957c3b264275626bcfc69b683f4a8bbf",
        "finished_at": CONTEXT_FINISHED,
    }
    coverage = {
        "attempted_artifact_count": 57, "verified_artifact_count": 53,
        "excluded_after_cutoff_count": 0, "global_market_coverage": "NOT_ESTABLISHED",
        "plan_trade_date": TARGET, "research_cutoff": STARTED,
        "vibe_binding": {
            "status": "SOURCE_FAILED", "owner_verification_status": "FAILED",
            "network_requests": 0, "writes": 0,
            "gaps": ["VIBE_EXACT_INPUT_SHA_NOT_BOUND:20261012", "VIBE_OWNER_READ_FAILED:20261012"],
        },
    }
    value = {
        "schema_version": "manager_research.workspace_plan_attempt.v1",
        "target_trade_date": TARGET, "run_id": run_id,
        "input_identity": input_identity, "owner": COMMON.OWNER,
        "execution_kind": "MANUAL_REFRESH", "started_at": STARTED,
        "finished_at": ATTEMPT_FINISHED, "last_success_at": ATTEMPT_FINISHED,
        "state": "PARTIAL", "failure_reasons": [],
        "summary": {"formal_recommendation_count": 0, "stock_count": 0},
        "input_coverage": coverage, "execution_context": context,
        "success_scope": "EXACT_DATE_RESEARCH_PLAN_NOT_FORMAL_RECOMMENDATION_OR_NATURAL_CAPTURE",
        **COMMON.SAFETY,
    }
    value["sha256"] = COMMON.canonical_sha(value)
    return value


def _product_record(run_id: str, input_identity: str) -> dict:
    value = {
        "schema_version": "manager_research.workspace_plan.v1",
        "target_trade_date": TARGET, "run_id": run_id,
        "input_identity": input_identity, "owner": COMMON.OWNER,
        "execution_kind": "MANUAL_REFRESH", "generated_at": ATTEMPT_FINISHED,
        "plan_rows": [], **COMMON.SAFETY,
    }
    value["sha256"] = COMMON.canonical_sha(value)
    return value


def _api_pair() -> tuple[dict, dict, dict, dict]:
    attempt = _attempt(FRESH_ID, FRESH_INPUT)
    product_sha = _product_record(FRESH_ID, FRESH_INPUT)["sha256"]
    context = attempt["execution_context"]

    def product(status: str, last_checked: str) -> dict:
        return {
            "status": status, "consumed": True, "run_id": FRESH_ID,
            "sha256": product_sha, "original_owner": COMMON.OWNER,
            "execution_kind": "MANUAL_REFRESH", "last_checked_at": last_checked,
            "input_identity_diagnostics": {
                "status": "MATCH", "current_input_identity": FRESH_INPUT,
                "saved_input_identity": FRESH_INPUT, "changed_components": [],
            },
            "run_readback": {
                "status": "VERIFIED", "target_trade_date": TARGET,
                "run_id": FRESH_ID, "artifact_sha256": product_sha,
                "input_identity": FRESH_INPUT, "owner": COMMON.OWNER,
                "owner_attempt_run_id": FRESH_ID,
                "owner_attempt_sha256": attempt["sha256"],
                "owner_attempt_state": "PARTIAL", "owner_finished_at": ATTEMPT_FINISHED,
            },
        }

    persisted = {
        "target_trade_date": TARGET, "run_id": FRESH_ID,
        "product_sha256": product_sha, "execution_kind": "MANUAL_REFRESH",
        "owner": COMMON.OWNER, **COMMON.SAFETY,
    }
    gaps = ["SYNTHETIC_DATA_GAP"]
    runtime_gaps = ["SYNTHETIC_RUNTIME_GAP"]
    direct_safety = dict(COMMON.SAFETY)
    refresh = {
        "schema_version": "v4.manager_research.workspace.v1",
        "target_trade_date": TARGET, "formal_recommendation_count": 0,
        "store_latest_matches_http_plan_product": True,
        "input_identity": FRESH_INPUT, "execution_kind": "MANUAL_REFRESH",
        "safety": dict(COMMON.SAFETY), **direct_safety,
        "plan_product": product("CURRENT", "2026-10-12T06:03:14.857665+08:00"),
        "persisted_store": persisted,
        "workspace_plan_attempt": attempt,
        "workspace_plan_product_attempt": attempt,
        "execution_context": context, "gaps": gaps, "runtime_gaps": runtime_gaps,
    }
    # This is the production GET DTO shape: no top-level execution_kind and no
    # nested safety alias; nested product identity and direct safety are present.
    readback = {
        "schema_version": "v4.manager_research.workspace.v1",
        "target_trade_date": TARGET, "input_identity": FRESH_INPUT,
        **direct_safety,
        "plan_product": product("CURRENT", "2026-10-12T06:03:17.717108+08:00"),
        "workspace_plan_attempt": attempt,
        "workspace_plan_product_attempt": attempt,
        "execution_context": context, "gaps": gaps, "runtime_gaps": runtime_gaps,
    }
    return refresh, readback, attempt, persisted


def test_real_get_dto_without_optional_envelope_aliases_passes():
    refresh, readback, attempt, _ = _api_pair()
    assert "execution_kind" not in readback
    assert "safety" not in readback
    assert readback["plan_product"]["execution_kind"] == "MANUAL_REFRESH"
    assert all(type(readback[key]) is bool for key in COMMON.SAFETY)
    assert CANARY._validate_owner_pair(refresh, readback, TARGET) == (
        FRESH_ID, refresh["plan_product"]["sha256"], FRESH_INPUT, "PARTIAL"
    )
    assert attempt["sha256"] == refresh["workspace_plan_attempt"]["sha256"]


def test_matching_optional_get_aliases_are_accepted_but_contradictions_fail():
    refresh, readback, _, _ = _api_pair()
    readback["execution_kind"] = "MANUAL_REFRESH"
    readback["safety"] = dict(COMMON.SAFETY)
    CANARY._validate_owner_pair(refresh, readback, TARGET)

    for mutate in (
        lambda value: value.__setitem__("execution_kind", "SCHEDULED_PREOPEN"),
        lambda value: value.__setitem__("safety", {**COMMON.SAFETY, "orders_sent": True}),
        lambda value: value.__setitem__("safety", {**COMMON.SAFETY, "production_allowed": 0}),
    ):
        refresh, readback, _, _ = _api_pair()
        mutate(readback)
        with pytest.raises(ValueError, match="CANARY_OWNER_READBACK_MISMATCH"):
            CANARY._validate_owner_pair(refresh, readback, TARGET)


@pytest.mark.parametrize("key,bad_value", [
    ("RESEARCH_ONLY", False), ("production_allowed", True),
    ("buy_gate_updated", True), ("orders_sent", True),
])
def test_get_requires_each_direct_safety_flag_to_match_exactly(key, bad_value):
    refresh, readback, _, _ = _api_pair()
    readback[key] = bad_value
    with pytest.raises(ValueError, match="CANARY_OWNER_READBACK_MISMATCH"):
        CANARY._validate_owner_pair(refresh, readback, TARGET)


@pytest.mark.parametrize("key", list(COMMON.SAFETY))
def test_get_requires_every_direct_safety_flag_to_be_present(key):
    refresh, readback, _, _ = _api_pair()
    del readback[key]
    with pytest.raises(ValueError, match="CANARY_OWNER_READBACK_MISMATCH"):
        CANARY._validate_owner_pair(refresh, readback, TARGET)


@pytest.mark.parametrize("mutation,expected", [
    (lambda value: value["plan_product"].__setitem__("status", "STALE"), "CANARY_OWNER_READBACK_MISMATCH"),
    (lambda value: value["plan_product"].__setitem__("run_id", "f" * 32), "CANARY_OWNER_READBACK_MISMATCH"),
    (lambda value: value["plan_product"].__setitem__("sha256", "f" * 64), "CANARY_OWNER_READBACK_MISMATCH"),
    (lambda value: value.__setitem__("input_identity", "f" * 64), "CANARY_OWNER_READBACK_MISMATCH"),
    (lambda value: value["plan_product"]["input_identity_diagnostics"].__setitem__("status", "STALE"), "CANARY_OWNER_PRODUCT_READBACK_IDENTITY_MISMATCH"),
    (lambda value: value["plan_product"].__setitem__("original_owner", "other.owner"), "CANARY_OWNER_READBACK_MISMATCH"),
    (lambda value: value["plan_product"]["run_readback"].__setitem__("status", "UNVERIFIED"), "CANARY_OWNER_PRODUCT_READBACK_IDENTITY_MISMATCH"),
    (lambda value: value["workspace_plan_attempt"].__setitem__("state", "FAILED"), "CANARY_OWNER_TERMINAL_ATTEMPT_INVALID"),
])
def test_get_identity_diagnostics_owner_runreadback_and_attempt_still_fail_closed(mutation, expected):
    refresh, readback, _, _ = _api_pair()
    mutation(readback)
    with pytest.raises(ValueError, match=expected):
        CANARY._validate_owner_pair(refresh, readback, TARGET)


def test_get_requires_nested_product_execution_kind():
    refresh, readback, _, _ = _api_pair()
    del readback["plan_product"]["execution_kind"]
    with pytest.raises(ValueError, match="CANARY_PRODUCT_IDENTITY_INVALID"):
        CANARY._validate_owner_pair(refresh, readback, TARGET)


def test_completion_rejects_offline_verifier_source_drift(tmp_path: Path, monkeypatch):
    source_copy = tmp_path / "complete_issue35_r6_saved_canary.py"
    source_copy.write_bytes(Path(COMPLETION.__file__).read_bytes() + b"\n# drift\n")
    monkeypatch.setattr(COMPLETION, "__file__", str(source_copy))
    with pytest.raises(ValueError, match="R6_COMPLETION_SOURCE_SELF_PIN_MISMATCH"):
        COMPLETION._verify_source_pins()


def test_completion_rejects_fixed_validator_source_drift(tmp_path: Path, monkeypatch):
    validator_copy = tmp_path / "issue35_phase6_r6_canary_readback_fix.py"
    validator_copy.write_bytes(COMPLETION._FIXED_VALIDATOR_PATH.read_bytes() + b"\n# drift\n")
    monkeypatch.setattr(COMPLETION, "_FIXED_VALIDATOR_PATH", validator_copy)
    with pytest.raises(ValueError, match="R6_FIXED_VALIDATOR_SOURCE_SHA256_MISMATCH"):
        COMPLETION._verify_source_pins()


@pytest.fixture
def saved_execution(tmp_path: Path):
    """Create an isolated three-generation target and a reader-shaped saved pair."""
    task_root = tmp_path.resolve()
    source_dir = task_root / COMPLETION.PINS["source_dir_rel"]
    source_dir.mkdir(parents=True)
    parent_dir = task_root / COMPLETION.PINS["parent_execution_rel"]
    parent_dir.parent.mkdir(parents=True, exist_ok=True)
    scope_copy = task_root / COMPLETION.PINS["scope_rel"]
    scope_copy.parent.mkdir(parents=True, exist_ok=True)
    scope_copy.write_bytes((COMPLETION.TASK_ROOT / COMPLETION.PINS["scope_rel"]).read_bytes())
    review_copy = task_root / COMPLETION.PINS["review_rel"]
    review_copy.parent.mkdir(parents=True, exist_ok=True)
    review_copy.write_bytes((COMPLETION.TASK_ROOT / COMPLETION.PINS["review_rel"]).read_bytes())
    state_root = (task_root / "state").resolve()
    run_root = state_root / "workspace_plan_runs" / TARGET
    product_root = state_root / "workspace_plans" / TARGET
    run_root.mkdir(parents=True)
    product_root.mkdir(parents=True)
    lock_root = state_root / ".locks"
    lock_root.mkdir()
    (lock_root / f"{TARGET}-workspace-plan-refresh.mutex").write_bytes(b"")

    release = COMMON.load_release(Path(COMPLETION.PINS["app_root"]))
    preimage_refs = CANARY._r6_receipt_pins()
    pins = copy.deepcopy(COMPLETION.PINS)
    pins["state_root"] = str(state_root)
    pins["archived"] = {"run_id": ARCHIVED_ID, "input_identity": ARCHIVED_INPUT,
                         "product_sha256": "", "state": "PARTIAL"}
    pins["current_before"] = {"run_id": CURRENT_ID, "input_identity": CURRENT_INPUT,
                              "product_sha256": "", "state": "PARTIAL"}

    old_generations = {}
    for label, run_id, identity in (
        ("archived", ARCHIVED_ID, ARCHIVED_INPUT), ("current", CURRENT_ID, CURRENT_INPUT),
    ):
        attempt = _attempt(run_id, identity)
        product = _product_record(run_id, identity)
        run_raw, product_raw = _json_bytes(attempt), _json_bytes(product)
        (run_root / f"{run_id}.json").write_bytes(run_raw)
        (product_root / f"{run_id}.json").write_bytes(product_raw)
        old_generations[label] = {
            "run_id": run_id, "input_identity": identity,
            "product_sha256": product["sha256"], "state": "PARTIAL",
            "run_raw": run_raw, "product_raw": product_raw,
            "run_sha256": hashlib.sha256(run_raw).hexdigest(),
            "product_file_sha256": hashlib.sha256(product_raw).hexdigest(),
        }
    (run_root / "latest.json").write_bytes(old_generations["current"]["run_raw"])
    (product_root / "latest.json").write_bytes(old_generations["current"]["product_raw"])

    def row(path: Path) -> dict:
        raw = path.read_bytes()
        return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    files = {
        "archived_run": row(run_root / f"{ARCHIVED_ID}.json"),
        "archived_product": row(product_root / f"{ARCHIVED_ID}.json"),
        "current_run": row(run_root / f"{CURRENT_ID}.json"),
        "current_run_latest": row(run_root / "latest.json"),
        "current_product": row(product_root / f"{CURRENT_ID}.json"),
        "current_product_latest": row(product_root / "latest.json"),
    }
    archived = old_generations["archived"]
    current = old_generations["current"]
    pins["archived"].update({
        "product_sha256": archived["product_sha256"], "run_bytes": len(archived["run_raw"]),
        "run_sha256": archived["run_sha256"], "product_bytes": len(archived["product_raw"]),
        "product_sha256_file": archived["product_file_sha256"],
    })
    pins["current_before"].update({
        "product_sha256": current["product_sha256"], "run_bytes": len(current["run_raw"]),
        "run_sha256": current["run_sha256"], "product_bytes": len(current["product_raw"]),
        "product_sha256_file": current["product_file_sha256"],
    })
    receipt_pins = {
        "archived": {key: pins["archived"][key] for key in
                     ("run_id", "product_sha256", "input_identity", "state", "run_bytes",
                      "run_sha256", "product_bytes", "product_sha256_file")},
        "current": {key: pins["current_before"][key] for key in
                    ("run_id", "product_sha256", "input_identity", "state", "run_bytes",
                     "run_sha256", "product_bytes", "product_sha256_file")},
        "protected_dates_sha256": COMMON.protected_state_hashes(state_root),
        **{key: preimage_refs[key] for key in (
            "r4b_state_preimage_path", "r4b_state_preimage_sha256", "r4b_canary_path",
            "r4b_canary_sha256", "contract_review_path", "contract_review_sha256",
        )},
    }
    source_preimage = {
        "schema_version": "manager_daily_chain.plan_canary_preimage.v1",
        "target_trade_date": TARGET, "current_clock_local": "2026-10-12T06:02:58.374955+08:00",
        "manager_state_root": str(state_root), "target_preexisted": True,
        "protected_dates_sha256": receipt_pins["protected_dates_sha256"],
        "api_app_root": pins["app_root"], "release_manifest_sha256": pins["release_manifest_sha256"],
        "application_inventory_sha256": pins["application_inventory_sha256"],
        "owner_source_inventory_sha256": pins["owner_source_inventory_sha256"],
        "http_calls_expected": ["POST " + pins["refresh"]["url"], "GET " + pins["readback"]["url"]],
        "prior_target_owner_state": {
            "archived_generation": {key: pins["archived"][key] for key in
                                     ("run_id", "input_identity", "product_sha256", "state")},
            "r4b_current_generation": {key: pins["current_before"][key] for key in
                                        ("run_id", "input_identity", "product_sha256", "state")},
            "files": files,
        },
        "r4b_two_generation_receipt_pins": {
            key: receipt_pins[key] for key in (
                "r4b_state_preimage_path", "r4b_state_preimage_sha256", "r4b_canary_path",
                "r4b_canary_sha256", "contract_review_path", "contract_review_sha256",
            )
        },
        "safety": dict(COMMON.SAFETY),
    }
    preimage_raw = _write_json(source_dir / "state-preimage.json", source_preimage)
    pins["preimage"].update({"sha256": hashlib.sha256(preimage_raw).hexdigest(),
                             "bytes": len(preimage_raw)})

    failure = {
        "schema_version": "manager_daily_chain.plan_canary_failure.v1",
        "status": "FAIL_CANNOT_BIND_PLAN_ACTIVATION",
        "error_code": "CANARY_OWNER_READBACK_MISMATCH",
        "target_trade_date": TARGET, "manager_state_root": str(state_root),
        "activation_status": "NOT_ACTIVATED", "launchctl_called": False,
        "prior_owner_state_preservation": {
            "status": "FAIL_CANNOT_CONFIRM_EXACT_FAILED_JOURNAL_AND_PRIOR_PRODUCT_LATEST_PRESERVED",
            "error": "ValueError:R6_FAILURE_PRODUCT_WRITE_SET_MISMATCH", "writes": "NOT_ATTEMPTED",
        },
        "safety": dict(COMMON.SAFETY),
    }
    failure_raw = _write_json(source_dir / "failure-receipt.json", failure)
    pins["failure"].update({"sha256": hashlib.sha256(failure_raw).hexdigest(),
                            "bytes": len(failure_raw)})

    original_binding_path = (COMPLETION.TASK_ROOT / COMPLETION.PINS["source_dir_rel"]
                             / "canary-disabled-binding.json")
    disabled_binding = json.loads(original_binding_path.read_bytes())
    disabled_binding["manager_state_root"] = str(state_root)
    binding_raw = _write_json(source_dir / "canary-disabled-binding.json", disabled_binding)
    pins["disabled_binding"].update({"sha256": hashlib.sha256(binding_raw).hexdigest(),
                                    "bytes": len(binding_raw)})

    refresh, readback, attempt, _ = _api_pair()
    fresh_product_record = _product_record(FRESH_ID, FRESH_INPUT)
    fresh_run_raw = _json_bytes(attempt)
    fresh_product_raw = _json_bytes(fresh_product_record)
    (run_root / f"{FRESH_ID}.json").write_bytes(fresh_run_raw)
    (run_root / "latest.json").write_bytes(fresh_run_raw)
    (product_root / f"{FRESH_ID}.json").write_bytes(fresh_product_raw)
    (product_root / "latest.json").write_bytes(fresh_product_raw)
    pins["fresh"].update({
        "product_sha256": fresh_product_record["sha256"],
        "attempt_sha256": attempt["sha256"],
        "run_file_sha256": hashlib.sha256(fresh_run_raw).hexdigest(),
        "product_file_sha256": hashlib.sha256(fresh_product_raw).hexdigest(),
        "run_bytes": len(fresh_run_raw), "product_bytes": len(fresh_product_raw),
    })

    for label, body in (("refresh", refresh), ("readback", readback)):
        response_raw = _json_bytes(body)
        response_path = source_dir / f"{label}.response.bin"
        response_path.write_bytes(response_raw)
        evidence = {
            "schema_version": "manager_daily_chain.plan_owner_http_evidence.v1",
            "http_status": 200, "content_type": "application/json",
            "request": {"method": pins[label]["method"], "url": pins[label]["url"]},
            "response": {"path": str(response_path), "sha256": hashlib.sha256(response_raw).hexdigest(),
                         "bytes": len(response_raw)},
            "readback": body,
        }
        evidence_raw = _write_json(source_dir / f"{label}.http-evidence.json", evidence)
        pins[label].update({
            "response_sha256": hashlib.sha256(response_raw).hexdigest(),
            "response_bytes": len(response_raw),
            "evidence_sha256": hashlib.sha256(evidence_raw).hexdigest(),
            "evidence_bytes": len(evidence_raw),
        })

    parent_output = {
        "argv": [pins["parent_interpreter"], "-B", pins["original_canary_path"],
                 "--app-root", pins["app_root"], "--target-date", TARGET,
                 "--output-dir", str(source_dir), "--accept-existing-current13", "--execute"],
        "exit_code": 1, "finished_utc": PARENT_FINISHED,
        "stdout_path": str(task_root / pins["parent_stdout_rel"]),
        "stdout_sha256": hashlib.sha256(b"").hexdigest(),
        "stderr_path": str(task_root / pins["parent_stderr_rel"]),
        "stderr_sha256": "",
    }
    (task_root / pins["parent_stdout_rel"]).write_bytes(b"")
    stderr_raw = b"Traceback\nValueError: CANARY_OWNER_READBACK_MISMATCH\n"
    (task_root / pins["parent_stderr_rel"]).write_bytes(stderr_raw)
    parent_output["stderr_sha256"] = hashlib.sha256(stderr_raw).hexdigest()
    parent_raw = _write_json(task_root / pins["parent_execution_rel"], parent_output)
    pins["parent_execution_sha256"] = hashlib.sha256(parent_raw).hexdigest()
    pins["parent_stdout_sha256"] = hashlib.sha256(b"").hexdigest()
    pins["parent_stderr_sha256"] = hashlib.sha256(stderr_raw).hexdigest()
    pins["parent_exit_code"] = 1
    pins["parent_finished_utc"] = PARENT_FINISHED

    output = task_root / pins["output_dir_rel"]
    output.parent.mkdir(parents=True, exist_ok=True)
    return {
        "task_root": task_root, "source_dir": source_dir, "state_root": state_root,
        "release": release, "pins": pins, "receipt_pins": receipt_pins,
        "output_dir": output, "fresh_attempt": attempt,
        "source_artifact_hashes": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                   for path in source_dir.iterdir()},
    }


def test_saved_execution_completion_writes_only_new_temp_receipts(saved_execution, monkeypatch):
    fx = saved_execution
    before_state = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in fx["state_root"].rglob("*") if path.is_file()}
    monkeypatch.setattr(CANARY, "_execute_owner_canary",
                        lambda *args, **kwargs: pytest.fail("owner path must never execute"))
    result = COMPLETION.complete_saved_execution(
        task_root=fx["task_root"], state_root=fx["state_root"],
        output_dir=fx["output_dir"], release=fx["release"], now=NOW,
        pins=fx["pins"], receipt_pins=fx["receipt_pins"],
    )
    canary = json.loads((fx["output_dir"] / "plan-canary.json").read_bytes())
    receipt = json.loads((fx["output_dir"] / "completion-receipt.json").read_bytes())
    after_state = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in fx["state_root"].rglob("*") if path.is_file()}
    after_source = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in fx["source_dir"].iterdir()}
    assert result["status"] == "PASS_OFFLINE_SAVED_OWNER_READBACK_COMPLETION"
    assert canary["owner_attempt_state"] == "PARTIAL"
    assert canary["owner_materialization_outcome"] == "FRESH"
    assert canary["owner_http_requests_replayed"] is False
    assert "execution_kind" not in json.loads(
        (fx["output_dir"] / "readback.verified-projection.response.bin").read_bytes())
    assert "safety" not in json.loads(
        (fx["output_dir"] / "readback.verified-projection.response.bin").read_bytes())
    assert receipt["original_owner_http_call_count"] == 2
    assert receipt["offline_completion_actions"]["http_calls"] == 0
    assert receipt["offline_completion_actions"]["owner_calls"] == 0
    assert receipt["owner_result"]["business_completeness"] == "PARTIAL"
    assert receipt["owner_result"]["research_and_pit_completeness"] == "CANNOT_CONFIRM"
    assert receipt["owner_result"]["coverage_and_gap_summary"]["pit_and_source_coverage"]["vibe_exact_input_sha_bound"] is False
    assert before_state == after_state
    assert fx["source_artifact_hashes"] == after_source
    assert {path.name for path in fx["output_dir"].iterdir()} == {
        "refresh.verified-projection.response.bin", "refresh.verified-projection.http-evidence.json",
        "readback.verified-projection.response.bin", "readback.verified-projection.http-evidence.json",
        "plan-canary.json", "completion-receipt.json",
    }


@pytest.mark.parametrize("target,expected", [
    ("refresh.response.bin", "R6_REFRESH_BODY_SHA256_MISMATCH"),
    ("readback.http-evidence.json", "R6_READBACK_EVIDENCE_SHA256_MISMATCH"),
])
def test_saved_completion_rejects_raw_body_or_evidence_drift(saved_execution, target, expected):
    fx = saved_execution
    path = fx["source_dir"] / target
    raw = bytearray(path.read_bytes())
    raw[0] = raw[0] ^ 1
    path.write_bytes(raw)
    with pytest.raises(ValueError, match=expected):
        COMPLETION.verify_saved_execution(
            task_root=fx["task_root"], state_root=fx["state_root"],
            release=fx["release"], now=NOW, pins=fx["pins"],
            receipt_pins=fx["receipt_pins"],
        )
    assert not fx["output_dir"].exists()


def test_saved_completion_rejects_http_evidence_body_projection_mismatch(saved_execution):
    fx = saved_execution
    path = fx["source_dir"] / "readback.http-evidence.json"
    value = json.loads(path.read_bytes())
    value["readback"]["target_trade_date"] = "20261012"
    raw = _write_json(path, value)
    fx["pins"]["readback"]["evidence_sha256"] = hashlib.sha256(raw).hexdigest()
    fx["pins"]["readback"]["evidence_bytes"] = len(raw)
    with pytest.raises(ValueError, match="R6_SAVED_READBACK_HTTP_EVIDENCE_MISMATCH"):
        COMPLETION.verify_saved_execution(
            task_root=fx["task_root"], state_root=fx["state_root"],
            release=fx["release"], now=NOW, pins=fx["pins"],
            receipt_pins=fx["receipt_pins"],
        )


def test_saved_completion_rejects_changed_latest(saved_execution):
    fx = saved_execution
    path = fx["state_root"] / "workspace_plan_runs" / TARGET / "latest.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        COMPLETION.verify_saved_execution(
            task_root=fx["task_root"], state_root=fx["state_root"],
            release=fx["release"], now=NOW, pins=fx["pins"],
            receipt_pins=fx["receipt_pins"],
        )


def test_saved_completion_rejects_changed_preserved_history(saved_execution):
    fx = saved_execution
    path = fx["state_root"] / "workspace_plan_runs" / TARGET / f"{ARCHIVED_ID}.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="R6_PRESERVED_HISTORY_MUTATED:archived_run"):
        COMPLETION.verify_saved_execution(
            task_root=fx["task_root"], state_root=fx["state_root"],
            release=fx["release"], now=NOW, pins=fx["pins"],
            receipt_pins=fx["receipt_pins"],
        )


def test_saved_completion_rejects_extra_write_set_member(saved_execution):
    fx = saved_execution
    extra = fx["state_root"] / "workspace_plans" / TARGET / "unexpected.json"
    extra.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="R6_FRESH_PRODUCT_WRITE_SET_MISMATCH"):
        COMPLETION.verify_saved_execution(
            task_root=fx["task_root"], state_root=fx["state_root"],
            release=fx["release"], now=NOW, pins=fx["pins"],
            receipt_pins=fx["receipt_pins"],
        )


def test_saved_completion_rejects_protected_date_change(saved_execution):
    fx = saved_execution
    protected = fx["state_root"] / "workspace_plans" / "20261009"
    protected.mkdir(parents=True)
    (protected / "changed.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="R6_FRESH_PROTECTED_DATES_CHANGED"):
        COMPLETION.verify_saved_execution(
            task_root=fx["task_root"], state_root=fx["state_root"],
            release=fx["release"], now=NOW, pins=fx["pins"],
            receipt_pins=fx["receipt_pins"],
        )


def test_saved_completion_rejects_busy_mutex(saved_execution):
    fx = saved_execution
    lock = fx["state_root"] / ".locks" / f"{TARGET}-workspace-plan-refresh.mutex"
    with lock.open("r+") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            with pytest.raises(ValueError, match="R6_OWNER_LOCK_BUSY|R6_FRESH_OWNER_LOCK_BUSY"):
                COMPLETION.verify_saved_execution(
                    task_root=fx["task_root"], state_root=fx["state_root"],
                    release=fx["release"], now=NOW, pins=fx["pins"],
                    receipt_pins=fx["receipt_pins"],
                )
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def test_saved_completion_rejects_unsafe_or_stale_clock(saved_execution):
    fx = saved_execution
    with pytest.raises(ValueError, match="TARGET_IS_NOT_NEXT_HK_SESSION_AT_CURRENT_CLOCK"):
        COMPLETION.verify_saved_execution(
            task_root=fx["task_root"], state_root=fx["state_root"],
            release=fx["release"], now=datetime.fromisoformat("2026-10-13T08:00:00+08:00"),
            pins=fx["pins"], receipt_pins=fx["receipt_pins"],
        )
    with pytest.raises(ValueError, match="R6_OWNER_EXECUTION_CLOCK_ORDER_INVALID"):
        COMPLETION.verify_saved_execution(
            task_root=fx["task_root"], state_root=fx["state_root"],
            release=fx["release"], now=datetime.fromisoformat("2026-10-12T06:03:00+08:00"),
            pins=fx["pins"], receipt_pins=fx["receipt_pins"],
        )
