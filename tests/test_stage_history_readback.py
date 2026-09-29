"""Synthetic sealed selections only; not historical market/production acceptance."""
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path

import pytest

from stage_center.contracts import EIGHT_STAGES, SAFETY_FLAGS
from stage_center.consumer import StageSelectionConsumer
from stage_center.selection import SelectionError, SelectionStore, _selection_envelope

DATE = "20260928"
STAGE = "STAGE_0930_0935"
LANES = [(s.stage_id, market) for s in EIGHT_STAGES for market in s.markets]


def envelope(stage=STAGE, market="A_SHARE", *, empty=False, formal=False, token="a"):
    rows = [] if empty else [{"code": "A.600000" if market == "A_SHARE" else "HK.00001",
        "name": "SYNTHETIC", "rank": 1, "score": 12.5, "status": "观察",
        "source_mode": "SYNTHETIC_CONTRACT", "trade_status": "NO_TRADE",
        "action_level": "NO_BUY", "formal_eligible": False, "current_change_pct": None}]
    return _selection_envelope(trade_date=DATE, stage_id=stage, market=market,
        raw_artifact_sha256=token * 64, source_status="CANNOT_CONFIRM" if empty else "READY",
        input_rows=len(rows), rows=rows, requested_rows=1, missing_symbols=[],
        cannot_confirm=["SYNTHETIC_ORIGINAL_FAILURE"] if empty else [],
        source_evidence=[] if formal else ["due_status=HISTORICAL_BACKFILL"])


def setup_history(root, stage=STAGE, market="A_SHARE", *, backfill="synthetic-history", token="a"):
    env = envelope(stage, market, token=token)
    store = SelectionStore(root / "backfill" / backfill)
    store.publish(env, market=market)
    verified = store._verify_run(DATE, stage, market, env["run_id"])
    return env, {"trade_date": DATE, "stage_id": stage, "market": market,
        "backfill_run_id": backfill, "selection_run_id": env["run_id"],
        **{f"expected_{key}": verified[key] for key in
           ("artifact_sha256", "manifest_sha256", "receipt_sha256")}}


def api():
    assert importlib.util.find_spec("stage_center.historical_readback") is not None
    return importlib.import_module("stage_center.historical_readback")


def file_hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def test_existing_ordinary_consumer_ignores_explicit_history_binding_before_repair(tmp_path):
    env, args = setup_history(tmp_path)
    # Written directly to demonstrate the old consumer ignores even an exact,
    # valid binding. No newest-directory/mtime discovery is part of this test.
    binding = {"schema_version": "stage_center.historical_readback.v1",
        "owner": "stage_center", "origin": "HISTORICAL_BACKFILL", "real_time_success": False,
        "recommendation_status": "RESEARCH_ONLY", **SAFETY_FLAGS,
        **{k: v for k, v in args.items() if not k.startswith("expected_")},
        **{k.removeprefix("expected_"): v for k, v in args.items() if k.startswith("expected_")}}
    path = tmp_path / "historical_readbacks" / DATE / STAGE / "A_SHARE.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(binding))
    result = StageSelectionConsumer(tmp_path).get(DATE, STAGE, markets=["A_SHARE"])
    assert result["markets"]["A_SHARE"]["rows"][0]["code"] == env["rows"][0]["code"]


@pytest.mark.parametrize("stage,market", LANES)
def test_exact_binding_restores_ordinary_consumer_without_writing_formal_history(tmp_path, stage, market):
    natural = envelope(stage, market, empty=True, formal=True, token="b")
    SelectionStore(tmp_path).publish(natural, market=market)
    history, args = setup_history(tmp_path, stage, market)
    before_bind = file_hashes(tmp_path)
    api().bind_history(tmp_path, **args)
    after_bind = file_hashes(tmp_path)
    assert all(after_bind[p] == sha for p, sha in before_bind.items())
    before_read = file_hashes(tmp_path)
    result = StageSelectionConsumer(tmp_path).get(DATE, stage, markets=[market])
    read = result["markets"][market]
    assert read["rows"][0]["code"] == history["rows"][0]["code"]
    assert read["rows"][0]["trade_status"] == "NO_TRADE"
    assert read["run_id"] == history["run_id"]
    assert read["result_origin"] == "HISTORICAL_BACKFILL"
    assert result["historical_readbacks"][0]["original_formal"]["run_id"] == natural["run_id"]
    assert result["historical_readbacks"][0]["original_formal"]["cannot_confirm"] == natural["cannot_confirm"]
    assert result["historical_readbacks"][0]["real_time_success"] is False
    assert all(result[k] is False for k in SAFETY_FLAGS)
    assert file_hashes(tmp_path) == before_read
    assert SelectionStore(tmp_path).read_verified(DATE, stage, market) == natural
    assert api().bind_history(tmp_path, **args)["write_performed"] is False


@pytest.mark.parametrize("field,value", [
    ("trade_date", "20260929"), ("stage_id", "STAGE_0935_0940"),
    ("market", "HK_CONNECT"), ("backfill_run_id", "wrong-run"),
    ("backfill_run_id", "../escape"), ("backfill_run_id", "."),
    ("selection_run_id", "run-wrong"),
    ("expected_artifact_sha256", "f" * 64),
    ("expected_manifest_sha256", "f" * 64),
    ("expected_receipt_sha256", "f" * 64),
])
def test_binding_rejects_wrong_identity_and_sha(tmp_path, field, value):
    _, args = setup_history(tmp_path)
    args[field] = value
    with pytest.raises((ValueError, OSError)):
        api().bind_history(tmp_path, **args)
    assert not (tmp_path / "historical_readbacks").exists()


def test_no_implicit_latest_directory_fallback(tmp_path):
    setup_history(tmp_path)
    result = StageSelectionConsumer(tmp_path).get(DATE, STAGE, markets=["A_SHARE"])
    assert result["markets"]["A_SHARE"]["rows"] == []


def test_valid_formal_result_wins_and_empty_ready_is_not_a_failure(tmp_path):
    _, args = setup_history(tmp_path)
    api().bind_history(tmp_path, **args)
    formal = envelope(formal=True, token="b")
    SelectionStore(tmp_path).publish(formal, market="A_SHARE")
    result = StageSelectionConsumer(tmp_path).get(DATE, STAGE, markets=["A_SHARE"])
    assert result["markets"]["A_SHARE"]["run_id"] == formal["run_id"]
    assert result.get("historical_readbacks", []) == []


@pytest.mark.parametrize("part", ["artifact.csv", "manifest.json", "receipt.json", "binding"])
def test_tampered_binding_or_trio_is_rejected_but_other_market_survives(tmp_path, part):
    _, a = setup_history(tmp_path)
    _, hk = setup_history(tmp_path, market="HK_CONNECT")
    api().bind_history(tmp_path, **a)
    api().bind_history(tmp_path, **hk)
    if part == "binding":
        path = tmp_path / "historical_readbacks" / DATE / STAGE / "A_SHARE.json"
    else:
        path = (tmp_path / "backfill" / a["backfill_run_id"] / "selection_runs" / DATE /
                f"A_SHARE_SELECTION_{STAGE}" / a["selection_run_id"] / part)
    path.write_bytes(path.read_bytes() + b"CORRUPTION")
    result = StageSelectionConsumer(tmp_path).get(DATE, STAGE)
    assert result["markets"]["A_SHARE"]["rows"] == []
    assert len(result["markets"]["HK_CONNECT"]["rows"]) == 1
    assert result["status"] == "PARTIAL_WITH_ROWS"


def test_symlinked_history_and_conflicting_binding_rejected(tmp_path):
    _, args = setup_history(tmp_path)
    api().bind_history(tmp_path, **args)
    _, other = setup_history(tmp_path, backfill="different", token="b")
    with pytest.raises(ValueError, match="conflict"):
        api().bind_history(tmp_path, **other)
    link = tmp_path / "backfill" / "link"
    link.symlink_to(tmp_path / "backfill" / args["backfill_run_id"], target_is_directory=True)
    args["backfill_run_id"] = "link"
    with pytest.raises(ValueError, match="symlink"):
        api().bind_history(tmp_path, **args)


def test_hk_only_stage_rejects_a_market(tmp_path):
    with pytest.raises(ValueError):
        StageSelectionConsumer(tmp_path).get(DATE, "STAGE_1545_1555", markets=["A_SHARE"])


def test_ordinary_api_aliases_and_ensure_share_the_same_verified_readback(tmp_path):
    from fastapi.testclient import TestClient
    from apps.api.v35_api.app import create_app
    root = tmp_path / "selection"
    for stage, market in LANES:
        _, args = setup_history(root, stage, market)
        api().bind_history(root, **args)
    app = create_app(data_root=tmp_path / "data", ledger_root=tmp_path / "ledger",
                     stage_center_selection_root=root, current_date=DATE)
    before = file_hashes(root)
    with TestClient(app) as client:
        for stage in EIGHT_STAGES:
            params = {"date": DATE, "stage": stage.stage_id}
            ordinary = client.get("/api/v3/workbench/stage", params=params)
            shared = client.get("/api/v3/stage-center/selection", params=params)
            assert ordinary.status_code == shared.status_code == 200
            assert ordinary.json() == shared.json()
            payload = ordinary.json()
            assert len(payload["historical_readbacks"]) == len(stage.markets)
            assert payload["selected_total_rows"] == len(stage.markets)
            for market, alias in (("A_SHARE", "A"), ("HK_CONNECT", "HK")):
                if market not in stage.markets:
                    assert alias not in payload["markets"]
                    continue
                canonical = payload["selection_markets"][market]
                row = payload["markets"][alias]["rows"][0]
                assert canonical["run_id"] == payload["markets"][alias]["run_id"]
                assert canonical["rows"][0] == row
                assert row["trade_status"] == "NO_TRADE" and row["current_change_pct"] is None
            restored = client.post("/api/v3/workbench/stage/ensure", params={**params, "force": True}).json()
            assert restored["historical_readbacks"] == payload["historical_readbacks"]
            assert restored["producer_called"] is False and restored["write_performed"] is False
    assert file_hashes(root) == before


def test_ready_empty_formal_and_unmarked_history_are_not_promoted(tmp_path):
    history, args = setup_history(tmp_path)
    api().bind_history(tmp_path, **args)
    formal = envelope(empty=True, formal=True, token="b")
    formal = _selection_envelope(trade_date=DATE, stage_id=STAGE, market="A_SHARE",
        raw_artifact_sha256="b" * 64, source_status="READY_EMPTY", input_rows=0, rows=[],
        requested_rows=0, missing_symbols=[], cannot_confirm=[], source_evidence=[])
    SelectionStore(tmp_path).publish(formal, market="A_SHARE")
    actual = StageSelectionConsumer(tmp_path).get(DATE, STAGE, markets=["A_SHARE"])
    assert actual["markets"]["A_SHARE"]["status"] == "READY_EMPTY"
    assert actual["historical_readbacks"] == []
    copied_root = tmp_path / "copy"
    copied = envelope(formal=True)
    store = SelectionStore(copied_root / "backfill" / "copied-formal")
    store.publish(copied, market="A_SHARE")
    verified = store._verify_run(DATE, STAGE, "A_SHARE", copied["run_id"])
    args.update(backfill_run_id="copied-formal", selection_run_id=copied["run_id"])
    args.update({f"expected_{k}": verified[k] for k in api().HASH_KEYS})
    with pytest.raises(ValueError, match="no explicit backfill evidence"):
        api().bind_history(copied_root, **args)
