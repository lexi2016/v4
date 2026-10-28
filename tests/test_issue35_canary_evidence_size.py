"""Regression tests for the bounded full-body plan-canary evidence contract."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_supervisor():
    override = os.environ.get("ISSUE35_SUPERVISOR_PATH")
    source = (Path(override) if override else
              REPO_ROOT / "infrastructure/scheduling/manager_announcement_supervisor.py")
    source = source.resolve(strict=True)
    spec = importlib.util.spec_from_file_location("issue35_supervisor_under_test", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load manager announcement supervisor: " + str(source))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SUPERVISOR = _load_supervisor()
OWNER = "ManagerResearchJobService.refresh_workspace_plan"
TARGET = "20261013"
RUN_ID = "d8a35106712a4387accf214c3ee3772d"
PRODUCT_SHA = "7ba36ad92af7cccaadbcdacca3a2eddc9488a80e28ddd9185ebba2e5afffc49c"
INPUT_IDENTITY = "3c3f32668945d572af760fdc9b36ad5c577a7167720dc8aaba3fd60ccae9bbd3"
SAFETY = {
    "RESEARCH_ONLY": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


def _json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _fixture(tmp_path: Path, *, pad_bytes: int = 0):
    root = tmp_path.resolve(strict=True)
    app = root / "app"
    state = root / "state"
    app.mkdir()
    state.mkdir()
    canary_dir = root / "canary"
    canary_dir.mkdir()

    product = {
        "status": "CURRENT",
        "run_id": RUN_ID,
        "sha256": PRODUCT_SHA,
        "original_owner": OWNER,
        "execution_kind": "MANUAL_REFRESH",
    }
    readback = {
        "target_trade_date": TARGET,
        "plan_product": product,
        "store_latest_matches_http_plan_product": True,
        "persisted_store": {
            "target_trade_date": TARGET,
            "run_id": RUN_ID,
            "product_sha256": PRODUCT_SHA,
            "execution_kind": "MANUAL_REFRESH",
            "owner": OWNER,
            **SAFETY,
        },
        "workspace_plan_attempt": {
            "execution_kind": "MANUAL_REFRESH",
            "state": "PARTIAL",
        },
        "safety": dict(SAFETY),
        "input_identity": INPUT_IDENTITY,
        "padding": "x" * pad_bytes,
    }

    evidence = {}
    files = {}
    for label, method, endpoint in (
        ("refresh", "POST", f"/api/v4/manager/research/workspace/refresh?date={TARGET}"),
        ("readback", "GET", f"/api/v4/manager/research/workspace?date={TARGET}"),
    ):
        body = _json_bytes(readback)
        body_path = canary_dir / f"{label}.response.bin"
        body_path.write_bytes(body)
        envelope = {
            "schema_version": "manager_daily_chain.plan_owner_http_evidence.v1",
            "http_status": 200,
            "content_type": "application/json",
            "request": {"method": method, "url": "http://127.0.0.1:8873" + endpoint},
            "response": {
                "path": str(body_path),
                "sha256": hashlib.sha256(body).hexdigest(),
                "bytes": len(body),
            },
            "readback": readback,
        }
        evidence_raw = _json_bytes(envelope)
        evidence_path = canary_dir / f"{label}.http-evidence.json"
        evidence_path.write_bytes(evidence_raw)
        evidence[label] = {
            "path": str(evidence_path),
            "sha256": hashlib.sha256(evidence_raw).hexdigest(),
        }
        files[label] = {"body": body_path, "evidence": evidence_path}

    canary = {
        "schema_version": SUPERVISOR.PLAN_CANARY_SCHEMA,
        "status": SUPERVISOR.PLAN_CANARY_STATUS,
        "app_root": str(app),
        "candidate_binding_app_root": str(app),
        "owner_execution_app_root": str(app),
        "manager_state_root": str(state),
        "policy_status": "PROPOSAL_ONLY",
        "scope": SUPERVISOR.PLAN_CANARY_NEXT_SCOPE,
        "plan_material_refresh_only": True,
        "execution_mode": "HISTORICAL_MANUAL_REFRESH_OWNER_HTTP_READBACK",
        "hook_executed": False,
        "announcement_collection_enabled": False,
        "announcement_network_requests": 0,
        **SAFETY,
        "research_only": True,
        "target_trade_date": TARGET,
        "run_id": RUN_ID,
        "product_sha256": PRODUCT_SHA,
        "input_identity": INPUT_IDENTITY,
        "execution_kind": "MANUAL_REFRESH",
        "owner": OWNER,
        "owner_attempt_state": "PARTIAL",
        "formal_recommendation_count": 0,
        "owner_evidence": evidence,
    }
    canary_path = canary_dir / "plan-canary.json"
    canary_raw = _json_bytes(canary)
    canary_path.write_bytes(canary_raw)
    ref = {"path": str(canary_path), "sha256": hashlib.sha256(canary_raw).hexdigest()}
    return ref, canary, files


def _write_canary(canary_path: Path, canary: dict) -> dict[str, str]:
    raw = _json_bytes(canary)
    canary_path.write_bytes(raw)
    return {"path": str(canary_path), "sha256": hashlib.sha256(raw).hexdigest()}


def test_accepts_complete_valid_owner_evidence_above_two_mib(tmp_path):
    ref, _, files = _fixture(tmp_path, pad_bytes=2_100_000)
    assert files["refresh"]["body"].stat().st_size > 2 * 1024 * 1024
    assert files["refresh"]["evidence"].stat().st_size > 2 * 1024 * 1024

    assert SUPERVISOR._validate_plan_canary(
        ref, app=Path(json.loads(Path(ref["path"]).read_text())["app_root"]),
        state=Path(json.loads(Path(ref["path"]).read_text())["manager_state_root"]),
    ) is None


def test_rejects_owner_evidence_hash_mismatch(tmp_path):
    ref, canary, files = _fixture(tmp_path)
    canary["owner_evidence"]["refresh"]["sha256"] = "0" * 64
    ref = _write_canary(Path(ref["path"]), canary)

    with pytest.raises(ValueError, match="PLAN_REFRESH_CANARY_EVIDENCE_SHA_MISMATCH"):
        SUPERVISOR._validate_plan_canary(ref, app=Path(canary["app_root"]),
                                         state=Path(canary["manager_state_root"]))


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("body_sha", "PLAN_REFRESH_CANARY_RESPONSE_SHA_MISMATCH"),
        ("body_length", "PLAN_REFRESH_CANARY_RESPONSE_INVALID"),
        ("readback", "PLAN_REFRESH_CANARY_RESPONSE_READBACK_MISMATCH"),
    ],
)
def test_rejects_body_corruption_and_readback_mismatch(tmp_path, mutation, expected):
    ref, canary, files = _fixture(tmp_path)
    evidence_path = files["refresh"]["evidence"]
    evidence = json.loads(evidence_path.read_bytes())
    if mutation == "body_sha":
        evidence["response"]["sha256"] = "0" * 64
    elif mutation == "body_length":
        evidence["response"]["bytes"] += 1
    else:
        evidence["readback"] = {**evidence["readback"], "padding": "different"}
    raw = _json_bytes(evidence)
    evidence_path.write_bytes(raw)
    canary["owner_evidence"]["refresh"]["sha256"] = hashlib.sha256(raw).hexdigest()
    ref = _write_canary(Path(ref["path"]), canary)

    with pytest.raises(ValueError, match=expected):
        SUPERVISOR._validate_plan_canary(ref, app=Path(canary["app_root"]),
                                         state=Path(canary["manager_state_root"]))


def test_rejects_evidence_envelope_over_sixty_four_mib(tmp_path):
    ref, canary, files = _fixture(tmp_path)
    evidence_path = files["refresh"]["evidence"]
    with evidence_path.open("wb") as stream:
        stream.truncate(64 * 1024 * 1024 + 1)
    canary["owner_evidence"]["refresh"]["sha256"] = "0" * 64
    ref = _write_canary(Path(ref["path"]), canary)

    with pytest.raises(ValueError, match="PLAN_REFRESH_CANARY_EVIDENCE_INVALID"):
        SUPERVISOR._validate_plan_canary(ref, app=Path(canary["app_root"]),
                                         state=Path(canary["manager_state_root"]))


def test_rejects_response_declaration_over_sixty_four_mib(tmp_path):
    body_path = tmp_path / "large-response.bin"
    body_path.touch()
    with pytest.raises(ValueError, match="PLAN_REFRESH_CANARY_RESPONSE_INVALID"):
        SUPERVISOR._response_body_identity(body_path, 64 * 1024 * 1024 + 1)
