"""Synthetic public-entry contracts, not a successful HK-only business replay.

The frozen runner cannot preserve the A branch on every internal failure.
Consequently the accepted HK coexisting path must report that interface block,
without spending either budget or touching A. Only the original A one-shot
continues to call the runner. No real approval or market data is created.
"""
from copy import deepcopy
from datetime import datetime
import base64
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from ops import run_stage_center_nodes as nodes
from ops._run_stage_center_nodes_parts import node_entry as entry
from stage_center.candidate_input import CandidateInput
from stage_center.contracts import SAFETY_FLAGS

DATE = "20260930"
STAGE = "STAGE_0925"
NOW = datetime(2026, 9, 30, 14, 3, tzinfo=ZoneInfo("Asia/Shanghai"))
BLOCK = "HK_RETRY_A_PRESERVATION_UNSUPPORTED"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def saved_files(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def case(tmp_path, monkeypatch):
    cfg = {k: str(tmp_path / k) for k in
           ("receipt_root", "candidate_acquisition_root", "selection_root")}
    cfg.update(node_max_attempts=3, safety=dict(SAFETY_FLAGS))
    path = Path(cfg["receipt_root"]) / DATE / STAGE / "receipt.json"
    path.parent.mkdir(parents=True)
    old = dict(schema_version="stage_center.runner.receipt.v1", trade_date=DATE,
        stage_id=STAGE, status="CANNOT_CONFIRM", node_attempt_count=3, retry_exhausted=True,
        error="TypeError: can't compare offset-naive and offset-aware datetimes",
        markets={"A_SHARE": {"selected_rows": 0}}, **SAFETY_FLAGS)
    raw = canonical(old) + b"\n"
    path.write_bytes(raw)
    codes = tuple(f"A.{600000+i:06}" for i in range(205))
    candidate = CandidateInput(Path(cfg["candidate_acquisition_root"]), DATE,
        "current.json", "d" * 64, "SYNTHETIC", codes, "a" * 64,
        "b" * 64, "c" * 64, "e" * 64, ())
    monkeypatch.setattr(entry, "_ISSUE11_RECEIPT_SHA", digest(raw))
    monkeypatch.setattr(entry, "_ISSUE11_CANDIDATE_SHA", candidate.artifact_sha256)
    monkeypatch.setattr(entry, "_ISSUE11_CODES_SHA", digest(canonical(list(codes))))
    monkeypatch.setattr(nodes, "_rearm_wall_now", lambda: NOW)
    monkeypatch.setattr("stage_center.candidate_input.read_candidate_input", lambda *a, **kw: candidate)
    pins = {"stage_center._live_collectors_parts.a_auction": "1" * 64,
            "infrastructure.tdx_minute_replay_provider": "2" * 64}
    monkeypatch.setattr(entry, "_issue11_loaded_repair_identity", lambda: pins)
    attempts = {}
    for number in range(1, 4):
        for event in ("START", "RETURN"):
            rel = f"attempt_evidence/SYNTHETIC-{number}/{event}.json"
            target = path.parent / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(canonical(dict(trade_date=DATE, stage_id=STAGE,
                attempt_number=number, event=event, detail={})))
            attempts[rel] = digest(target.read_bytes())
    auth = dict(schema_version="stage_center.a_auction_recovery_authorization.v1", issue=11,
        trade_date=DATE, stage_id=STAGE, market="A_SHARE", mode="RECOVERY", additional_attempts=1,
        approval_id="SYNTHETIC-NOT-EXECUTION-AUTHORIZATION", writer_id="synthetic-writer",
        reviewer_id="synthetic-reviewer", review_status="APPROVED", original_receipt_sha256=digest(raw),
        candidate_artifact_sha256=candidate.artifact_sha256, codes_sha256=digest(canonical(list(codes))),
        candidate_count=205, fixed_modules=pins, original_attempts=attempts, **SAFETY_FLAGS)
    cfg["a_0925_recovery_authorization"] = auth
    cfg["a_0925_recovery_authorization_sha256"] = digest(canonical(auth))
    # Do NOT inject the private capability: public run_nodes must create it.
    calls, writes = [], []
    decision = SimpleNamespace(trade_date=DATE, stage_id=STAGE, status="LATE_CATCHUP_REPLAY",
        scheduled_at=NOW.replace(hour=9, minute=25))

    def write(value, date, stage):
        value = {**value, "trade_date": date, "stage_id": stage, **SAFETY_FLAGS}
        writes.append(deepcopy(value))
        path.write_bytes(canonical(value))
        return value

    def run(decision):
        calls.append(decision)
        return {**old, "write_performed": False}

    runner = SimpleNamespace(config=SimpleNamespace(receipt_root=Path(cfg["receipt_root"])),
        due_decisions=lambda *a, **kw: [decision], _run_one=run,
        _write_receipt=write, _receipt_path=lambda *a: path)
    monkeypatch.setattr(nodes, "_calendar_gate", lambda *a, **kw: {"status": "ELIGIBLE"})
    return SimpleNamespace(root=tmp_path, cfg=cfg, path=path, old=old, raw=raw,
        auth=auth, candidate=candidate, runner=runner, calls=calls, writes=writes,
        decision=decision, marker=path.parent / entry._ISSUE11_MARKER)


def invoke(c, *, evaluated=NOW, date=DATE, stage=STAGE):
    return nodes.run_nodes(c.cfg, trade_date=date, evaluated_at=evaluated,
                           explicit_node=stage, runner=c.runner)


def partial(c, *, consumed=False, attempt=1):
    receipt = deepcopy(c.old)
    receipt.update(node_id=STAGE, dispatch_mode="RECOVERY", status="PARTIAL_WITH_ROWS",
                   node_outcome="SETTLED_PARTIAL", node_attempt_count=attempt,
                   retry_exhausted=attempt >= 3)
    receipt["markets"]["A_SHARE"] = {"selected_rows": 10, "run_id": "SYNTHETIC-A-DONE",
        "artifact_sha256": "a" * 64, "rows": [{"code": "A.600000", "trade_status": "NO_TRADE"}]}
    receipt["markets"]["HK_CONNECT"] = dict(market="HK_CONNECT", status="CANNOT_CONFIRM",
        source_status="CANNOT_CONFIRM", selection_status="CANNOT_CONFIRM", selected_rows=0,
        write_performed=False, cannot_confirm=["HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE"])
    c.path.write_bytes(canonical(receipt))
    if consumed:
        # Marker existence is an A denial, NOT proof of independent HK budget.
        c.marker.write_bytes(canonical({"fixture": "SYNTHETIC-CONSUMED", "additional_attempts": 1}))
    return receipt


@pytest.mark.parametrize("consumed", [False, True])
def test_public_coexisting_hk_request_reports_runner_contract_not_a_short_circuit(case, consumed):
    partial(case, consumed=consumed)
    before = saved_files(case.root)
    cfg_before = deepcopy(case.cfg)
    out = invoke(case)
    node = out["nodes"][0]
    assert node["first_failed_layer"] == BLOCK
    assert node["hk_recorded_remaining_attempts"] == 2
    assert node["hk_retry_executed"] is False
    assert node["additional_a_attempts_granted"] == 0
    assert node["a_recovery_marker_present"] is consumed
    assert out["status"] == "CANNOT_CONFIRM"
    assert node["write_performed"] is False
    assert case.calls == case.writes == []
    assert saved_files(case.root) == before
    assert case.cfg == cfg_before and "_issue11_explicit_request" not in case.cfg
    assert all(out[k] is False for k in SAFETY_FLAGS)


def test_consumed_marker_does_not_become_hk_authority_without_a_config(case):
    partial(case, consumed=True)
    case.cfg.pop("a_0925_recovery_authorization")
    case.cfg.pop("a_0925_recovery_authorization_sha256")
    before = saved_files(case.root)
    node = invoke(case)["nodes"][0]
    assert node["first_failed_layer"] == BLOCK
    assert saved_files(case.root) == before and not case.calls


def test_hk_route_does_not_validate_or_consume_a_grant(case, monkeypatch):
    partial(case)
    case.auth["review_status"] = "PENDING"
    case.cfg["a_0925_recovery_authorization_sha256"] = "f" * 64
    monkeypatch.setattr(entry, "_a_0925_repair_authority", lambda *a, **kw: pytest.fail("HK borrowed A grant"))
    before = saved_files(case.root)
    assert invoke(case)["nodes"][0]["first_failed_layer"] == BLOCK
    assert saved_files(case.root) == before and not case.marker.exists()


@pytest.mark.parametrize("change", ["both_exhausted", "future", "wrong_day", "unsafe_receipt", "unsafe_config"])
def test_public_coexistence_never_borrows_allowance_on_rejected_scope(case, monkeypatch, change):
    receipt = partial(case, consumed=True, attempt=3 if change == "both_exhausted" else 1)
    evaluated = NOW
    if change == "future":
        evaluated = NOW.replace(hour=15)
    elif change == "wrong_day":
        monkeypatch.setattr(nodes, "_rearm_wall_now", lambda: NOW.replace(month=10, day=1))
    elif change == "unsafe_receipt":
        receipt["orders_sent"] = True
        case.path.write_bytes(canonical(receipt))
    elif change == "unsafe_config":
        case.cfg["safety"]["orders_sent"] = True
    before = saved_files(case.root)
    out = invoke(case, evaluated=evaluated)
    assert not case.calls and not case.writes
    assert saved_files(case.root) == before
    assert out["nodes"][0].get("hk_retry_executed", False) is False
    if change in {"future", "wrong_day", "unsafe_config"}:
        assert out["nodes"][0]["first_failed_layer"] == "HK_COEXISTENCE_SCOPE_UNSAFE"
    elif change == "both_exhausted":
        assert out["status"] == "RETRY_EXHAUSTED"


def test_a_public_one_shot_is_still_one_and_preserves_original_attempts(case):
    before = saved_files(case.root)
    out = invoke(case)
    assert len(case.calls) == 1
    assert out["nodes"][0]["node_attempt_count"] == 4
    audit = json.loads(case.marker.read_bytes())
    assert base64.b64decode(audit["original_receipt_base64"]) == case.raw
    assert audit["candidate_count"] == 205
    assert all((case.root / p).read_bytes() == data for p, data in before.items()
               if p != str(case.path.relative_to(case.root)))
    assert invoke(case)["nodes"][0]["status"] == "SKIPPED_REPAIR_RECOVERY_CONSUMED"
    assert len(case.calls) == 1


def test_real_reported_code_sha_mismatch_does_not_mint_grant(case, monkeypatch):
    # Keep the production expected constant; do not reorder the synthetic list.
    monkeypatch.setattr(entry, "_ISSUE11_CODES_SHA",
                        "80f5a1c0bbed293b637d1a2bb25585de932ce5b235dd3ff0236fcb9a99d8eb69")
    case.auth["codes_sha256"] = entry._ISSUE11_CODES_SHA
    case.cfg["a_0925_recovery_authorization_sha256"] = digest(canonical(case.auth))
    before = saved_files(case.root)
    invoke(case)
    assert case.calls == case.writes == []
    assert saved_files(case.root) == before
