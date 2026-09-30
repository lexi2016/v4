"""Real source-bound 205-code array; all authority/I/O context is synthetic.

Only the read-only guard is invoked. No dispatcher, runner, collector,
reservation write, real approval, or saved production receipt is exercised.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from ops._run_stage_center_nodes_parts import node_entry as entry
from stage_center import candidate_input

DATE = "20260930"
STAGE = "STAGE_0925"
MODE = "ORDERED_CODES_UTF8_LF_JOIN_NO_TRAILING_LF_V1"
EXPECTED = "80f5a1c0bbed293b637d1a2bb25585de932ce5b235dd3ff0236fcb9a99d8eb69"
COMPACT = "ed7370dd8a81ddc621d606c61b8df95095cdc2c9def7909ab8be5e02b214b073"
FILE_SHA = "cf16619116f85832c9bf1ba80c60a6166f37afee52f3ed4b379e76b6e708b71c"
DATA = Path(__file__).parent / "data" / "a0925_candidate_codes_original_order.json"
FLAGS = {k: False for k in ("production_allowed", "buy_gate_updated", "orders_sent")}
NOW = datetime(2026, 9, 30, 14, 3, tzinfo=ZoneInfo("Asia/Shanghai"))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def file_bytes(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def test_exact_real_array_has_three_distinct_serialization_identities():
    raw = DATA.read_bytes()
    codes = json.loads(raw)
    assert len(codes) == len(set(codes)) == 205
    assert len(raw) == 2873 and sha(raw) == FILE_SHA
    joined = "\n".join(codes).encode("utf-8")
    assert len(joined) == 1844 and not joined.endswith(b"\n")
    assert sha(joined) == EXPECTED
    assert sha(canonical(codes)) == COMPACT
    assert sha(joined + b"\n") != EXPECTED
    assert len({FILE_SHA, COMPACT, EXPECTED}) == 3


@pytest.fixture
def case(tmp_path, monkeypatch):
    # The ONLY production input here is the ordered code array. Receipt,
    # attempts, current identity, approval and loaded-code boundary are fixtures.
    codes = tuple(json.loads(DATA.read_bytes()))
    path = tmp_path / "receipts" / DATE / STAGE / "receipt.json"
    path.parent.mkdir(parents=True)
    receipt = dict(schema_version="stage_center.runner.receipt.v1", trade_date=DATE,
        stage_id=STAGE, status="CANNOT_CONFIRM", node_attempt_count=3, retry_exhausted=True,
        markets={"A_SHARE": {"selected_rows": 0}},
        error="SYNTHETIC TypeError: cannot compare offset-naive and offset-aware datetimes",
        **FLAGS)
    raw = canonical(receipt) + b"\n"
    path.write_bytes(raw)
    monkeypatch.setattr(entry, "_ISSUE11_RECEIPT_SHA", sha(raw))
    attempts = {}
    for number in (1, 2, 3):
        for event in ("START", "RETURN"):
            relative = f"attempt_evidence/SYNTHETIC-{number}/{event}.json"
            data = canonical(dict(trade_date=DATE, stage_id=STAGE, attempt_number=number,
                                  event=event, detail={"fixture": "SYNTHETIC"}))
            destination = path.parent / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            attempts[relative] = sha(data)
    candidate = candidate_input.CandidateInput(
        root=tmp_path / "candidate", trade_date=DATE, current_relative="current.json",
        current_sha256="1" * 64, run_id="SYNTHETIC_GUARD_ONLY", codes=codes,
        artifact_sha256=entry._ISSUE11_CANDIDATE_SHA, manifest_sha256="2" * 64,
        receipt_sha256="3" * 64, source_projection_sha256="4" * 64, source_evidence=())
    fixed = {"stage_center._live_collectors_parts.a_auction": "5" * 64,
             "infrastructure.tdx_minute_replay_provider": "6" * 64}
    auth = dict(schema_version="stage_center.a_auction_recovery_authorization.v1",
        issue=11, trade_date=DATE, stage_id=STAGE, market="A_SHARE", mode="RECOVERY",
        review_status="APPROVED", approval_id="SYNTHETIC-NOT-A-REAL-GRANT",
        writer_id="synthetic-writer", reviewer_id="synthetic-reviewer", additional_attempts=1,
        original_receipt_sha256=sha(raw), candidate_artifact_sha256=entry._ISSUE11_CANDIDATE_SHA,
        codes_sha256=EXPECTED, candidate_count=205, original_attempts=attempts,
        fixed_modules=fixed, **FLAGS)
    config = dict(candidate_acquisition_root=str(tmp_path / "candidate"),
        selection_root=str(tmp_path / "selection"), node_max_attempts=3, safety=dict(FLAGS),
        _issue11_explicit_request=entry._ISSUE11_EXPLICIT,
        a_0925_recovery_authorization=auth,
        a_0925_recovery_authorization_sha256=sha(canonical(auth)))
    c = SimpleNamespace(root=tmp_path, path=path, receipt=receipt, raw=raw,
                        candidate=candidate, auth=auth, config=config)
    monkeypatch.setattr(candidate_input, "read_candidate_input", lambda *a, **kw: c.candidate)
    monkeypatch.setattr(entry, "_issue11_loaded_repair_identity", lambda: dict(fixed))
    c.scope = {"_receipt_path": lambda *a: path, "_rearm_wall_now": lambda: NOW,
               "_as_shanghai": lambda value: value.astimezone(ZoneInfo("Asia/Shanghai"))}
    # Never patch the production codes pin to make this test pass.
    assert entry._ISSUE11_CODES_SHA == EXPECTED
    return c


def check(c):
    before = file_bytes(c.root)
    auth_before = deepcopy(c.auth)
    candidate_before = c.candidate
    result = entry._a_0925_repair_authority(
        c.scope, c.config, DATE, STAGE, c.receipt, NOW, "RECOVERY")
    assert file_bytes(c.root) == before
    assert c.auth == auth_before and c.candidate == candidate_before
    return result


@pytest.mark.parametrize("declared_mode", [None, MODE], ids=["legacy-auth-unchanged", "explicit-lf-mode"])
def test_real_order_passes_guard_without_rewriting_authorization(case, declared_mode):
    if declared_mode is not None:
        case.auth["codes_digest_mode"] = declared_mode
    case.config["a_0925_recovery_authorization_sha256"] = sha(canonical(case.auth))
    result = check(case)
    assert result is not None, "the real unchanged 205-code order must pass the codes guard"
    assert result["codes_sha256"] == EXPECTED
    assert result["codes_digest_mode"] == MODE == entry._ISSUE11_CODES_DIGEST_MODE
    assert result["candidate_current_sha256"] == "1" * 64
    assert result["candidate_artifact_sha256"] == entry._ISSUE11_CANDIDATE_SHA
    assert result["authorization_sha256"] == sha(canonical(case.auth))
    assert result["candidate_count"] == 205
    assert result["original_attempt_count"] == 3 and result["additional_attempts"] == 1
    assert all(result[k] is False for k in FLAGS)


@pytest.mark.parametrize("mutation", ["swap", "missing", "extra", "compact-json-digest", "wrong-declared-mode"])
def test_wrong_order_count_or_algorithm_is_rejected(case, mutation):
    codes = list(case.candidate.codes)
    if mutation == "swap":
        codes[0], codes[1] = codes[1], codes[0]
    elif mutation == "missing":
        codes.pop()
    elif mutation == "extra":
        codes.append("A.999999")
    elif mutation == "compact-json-digest":
        case.auth["codes_sha256"] = COMPACT
    else:
        case.auth["codes_digest_mode"] = "COMPACT_JSON_UTF8_V1"
    case.candidate = replace(case.candidate, codes=tuple(codes))
    case.config["a_0925_recovery_authorization_sha256"] = sha(canonical(case.auth))
    assert check(case) is None
    assert entry._ISSUE11_CODES_SHA == EXPECTED
