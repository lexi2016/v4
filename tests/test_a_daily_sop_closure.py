"""Bounded synthetic source/window/typed proof/tuple checks; no live writes."""
import copy
import importlib.util
from datetime import datetime
import json
from pathlib import Path
import urllib.error
from zoneinfo import ZoneInfo

import pytest

from ops import research_panel_daily_source as source
from ops import research_panel_qfq as qfq
from ops import research_panel_factor_cache as fc
from test_a_share_daily_zip_source import packet, ref, TARGET
from test_factor_cache_carry_forward import case, CODES, put


def moment(text):
    return datetime.strptime(text, "%Y%m%d%H%M").replace(tzinfo=ZoneInfo("Asia/Shanghai"))


def test_source_one_download_then_immutable_verified_reuse(tmp_path):
    calls = []
    def fetch():
        calls.append("dated URL fetch")
        return packet()
    first = source.acquire_daily_input(TARGET, tmp_path, fetch=fetch, now=moment("202610291610"))
    again = source.acquire_daily_input(TARGET, tmp_path, fetch=lambda: pytest.fail("duplicate download"), now=moment("202610291615"))
    assert first == again and len(calls) == 1
    descriptor = json.loads(Path(first["path"]).read_text())
    assert descriptor["previous_session"] == "20261028"
    Path(descriptor["package"]["path"]).write_bytes(b"drift")
    with pytest.raises(ValueError, match="SHA_MISMATCH"):
        source.acquire_daily_input(TARGET, tmp_path, fetch=lambda: pytest.fail("bad cache must stop"), now=moment("202610291615"))


@pytest.mark.parametrize("when", ["202610291609", "202610281610"])
def test_source_wait_window_does_not_fetch_or_publish(tmp_path, when):
    with pytest.raises(fc.QfqGateError, match="WAIT_WINDOW"):
        source.acquire_daily_input(TARGET, tmp_path, fetch=lambda: pytest.fail("early fetch"), now=moment(when))
    assert not list(tmp_path.iterdir())


def test_source_unready_bounded_attempts_preserve_failure(tmp_path):
    calls, sleeps = [], []
    def unready():
        calls.append(1)
        raise urllib.error.HTTPError("official", 404, "not yet published", {}, None)
    with pytest.raises(fc.QfqGateError, match="SOURCE_NOT_READY"):
        source.acquire_daily_input(TARGET, tmp_path, fetch=unready, now=moment("202610291610"), sleep=sleeps.append)
    assert len(calls) == 2 and sleeps == [2]
    assert not list(tmp_path.rglob("input.json"))
    assert json.loads(next(tmp_path.rglob("WAIT.json")).read_text())["status"] == "SOURCE_NOT_READY"


def test_bad_source_is_not_published_or_retried_as_tcp(tmp_path):
    with pytest.raises(Exception):
        source.acquire_daily_input(TARGET, tmp_path, fetch=lambda: b"bad ZIP", now=moment("202610291610"))
    assert not list(tmp_path.rglob("input.json"))


def typed_snapshot(case):
    root, cfg = case
    cfg["prequery_sync_ref"] = put(root / "sync.json", dict(target_date=TARGET, target_keys=[dict(symbol="000001", market=0)],
        symbol_reconciliation=[], RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False))
    cfgref = put(root / "cfg.json", cfg)
    proof = fc.collect_research_metadata(CODES, cache_root=root / "cache", target=TARGET, config_ref=cfgref,
        client_factory=lambda: pytest.fail("unexpected provider"))
    symbols = {c: dict(source_method=fc.RESEARCH_CARRY_LABEL, events=[], event_coverage_complete=True,
        history_start_date=20260101, raw_files=[put(root / (c + ".raw.json"), {"original": True})], publish_roles=["selector", "backtest"]) for c in CODES}
    sources = [x["original_provider_response"] for x in proof["symbols"].values()] + [cfgref]
    value = dict(schema=source.RESEARCH_SCHEMA, label=fc.RESEARCH_CARRY_LABEL, asof_date=TARGET, coverage_end_date=TARGET,
        price_basis="QFQ_ASOF", volume_basis="QFQ_EVENT_VOLUME", amount_basis="RAW_TURNOVER", convention="original unchanged math",
        revision="bound synthetic", observed_at="2026-10-29T10:00:00+00:00", research_factor_receipts=proof,
        research_cache_configuration=cfgref, symbols=symbols, source_files=sources,
        provider_revision_coverage="CANNOT_CONFIRM", historical_PIT=False,
        RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
    return root, value


def test_typed_consumer_keeps_old_observation_and_freshness_separate(case):
    root, value = typed_snapshot(case)
    path = root / "snapshot.json"
    path.write_text(json.dumps(value))
    accepted = qfq.load_snapshot(path, TARGET)
    assert qfq.factor_cache_identity(root, TARGET, accepted) == qfq._research_cache_semantics(value, TARGET)
    for row in accepted["research_factor_receipts"]["symbols"].values():
        assert row["original_capture_date"] == 20261028 and row["target_date"] == TARGET
        assert row["provider_queried_for_this_record"] is False


@pytest.mark.parametrize("corruption", ["label", "target", "detector", "provider_latest", "receipt", "mixed_schema"])
def test_typed_consumer_rejects_missing_or_mixed_proof(case, corruption):
    root, value = typed_snapshot(case)
    if corruption == "label": value["label"] = "OK"
    if corruption == "target": value["research_factor_receipts"]["asof_date"] = 20261028
    if corruption == "detector": value["research_factor_receipts"]["detector_binding"] = "0" * 64
    if corruption == "provider_latest": value["provider_revision_coverage"] = "COMPLETE"
    if corruption == "receipt": value["research_factor_receipts"]["symbols"][CODES[0]]["provider_queried_for_this_record"] = True
    if corruption == "mixed_schema": value["schema"] = "a_share_qfq_adjustment_input_v1"
    if corruption == "mixed_schema":
        # Old same-day schema cannot silently accept a typed carry snapshot.
        value.pop("research_cache_configuration")
        with pytest.raises(fc.QfqGateError):
            qfq._research_cache_semantics(value, TARGET)
    else:
        with pytest.raises((fc.QfqGateError, KeyError)):
            qfq._research_cache_semantics(value, TARGET)


def test_complete_current_tuple_and_exact_old_tuple_only(tmp_path, monkeypatch):
    old = json.loads((Path(qfq.__file__).resolve().parents[1] / "contracts/a_share_generation_compatibility.json").read_text())["accepted_old_generations"][0]
    refs = []
    for name, expected in [("driver", qfq.DRIVER_SHA), ("formula", qfq.FORMULA_SHA), ("fields", old["module_tuple"]["field_contract_sha256"])]:
        refs.append(dict(path=str(tmp_path / name), sha256=expected))
    # Test tuple matching independently from the separately tested file hash
    # and release-inventory admission; no data artifact is read here.
    monkeypatch.setattr(qfq, "_source", lambda x, **kw: Path(x["path"]))
    monkeypatch.setattr(qfq, "_release_tuple_bound", lambda: True)
    snapshot = tmp_path / "snapshot.json";snapshot.write_text("{}")
    (tmp_path / "qfq_readiness.json").write_text(json.dumps(dict(code_refs=refs)))
    current = dict(driver_sha256=qfq.DRIVER_SHA, formula_sha256=qfq.FORMULA_SHA,
        adapter_sha256=qfq.sha(Path(qfq.__file__)), input_adapter_sha256=qfq.sha(Path(qfq.__file__).with_name("research_panel_adjustment_inputs.py")),
        factor_cache_sha256=qfq.sha(Path(qfq.__file__).with_name("research_panel_factor_cache.py")),
        tdx_adapter_sha256=qfq.sha(Path(qfq.__file__).with_name("research_panel_tdx_adjustment_inputs.py")),
        user_formula_sha256=qfq.USER_FORMULA_SHA, field_contract_sha256=refs[2]["sha256"])
    assert qfq._generation_tuple_compatible(current, snapshot)
    old = json.loads((Path(qfq.__file__).resolve().parents[1] / "contracts/a_share_generation_compatibility.json").read_text())["accepted_old_generations"][0]
    old_contract = dict(old["module_tuple"], generation_id=old["generation_id"], asof_date=old["target"], input_sha256=old["input_sha256"])
    monkeypatch.setattr(qfq, "sha", lambda p: old["snapshot_sha256"] if p == snapshot else "candidate module")
    assert qfq._generation_tuple_compatible(old_contract, snapshot)
    for key in qfq._GENERATION_TUPLE_KEYS:
        mixed = dict(old_contract, **{key: "candidate module"})
        assert not qfq._generation_tuple_compatible(mixed, snapshot)
    assert not qfq._generation_tuple_compatible(dict(old_contract, generation_id="another"), snapshot)


@pytest.mark.parametrize("consumer", ["Main", "API"])
def test_convention_old_primary_and_one_independent_exact_successor(tmp_path, consumer):
    if consumer == "Main":
        module = qfq
    else:
        import os
        path = Path(os.environ["A_DAILY_API_CANDIDATE_SOURCE"])
        spec = importlib.util.spec_from_file_location("sop_api_convention_under_test", path)
        module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    old = {k: "old-" + k for k in qfq._GENERATION_TUPLE_KEYS}
    new = {k: "new-" + k for k in qfq._GENERATION_TUPLE_KEYS}
    accepted = dict(code_binding=old)
    assert module._convention_tuple_accepted(accepted, old)
    assert not module._convention_tuple_accepted(accepted, new)
    proof = dict(status="PASS_INPUT_EVENT_VOLUME_EQUIVALENCE", code_binding=new, baseline_code_binding=old,
        assertions={k: True for k in ("events_parity", "volume_math_parity", "original_provider_dates_preserved", "source_and_code_pins_verified")},
        RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
    receipt = put(tmp_path / "proof.json", proof)
    accepted.update(tuple_compatibility_schema="qfq_exact_two_tuple_acceptance.v1", approved_tuple_entries=[
        dict(code_binding=new, status="PASS", reviewer_id="independent reviewer", equivalence_receipt=receipt)])
    assert module._convention_tuple_accepted(accepted, old)
    assert module._convention_tuple_accepted(accepted, new)
    for key in qfq._GENERATION_TUPLE_KEYS:
        assert not module._convention_tuple_accepted(accepted, dict(new, **{key: old[key]}))
    assert not module._convention_tuple_accepted(accepted, {k: v for k, v in new.items() if k != "factor_cache_sha256"})
    pending = copy.deepcopy(accepted);pending["approved_tuple_entries"][0]["status"] = "PENDING"
    assert not module._convention_tuple_accepted(pending, new)
    expanded = copy.deepcopy(accepted);expanded["approved_tuple_entries"] *= 2
    assert not module._convention_tuple_accepted(expanded, new)
    Path(receipt["path"]).write_text("{}")
    with pytest.raises(Exception):
        module._convention_tuple_accepted(accepted, new)


def test_process_task_returns_quarantine_to_parent_and_has_no_shared_state(tmp_path, monkeypatch):
    monkeypatch.setattr(qfq, "_symbol_checkpoint", lambda *a: (_ for _ in ()).throw(fc.QfqGateError("bound raw quarantine")))
    assert qfq._symbol_process_task((CODES[0], {}, TARGET, {}, str(tmp_path), {})) == (CODES[0], None, "bound raw quarantine")
    monkeypatch.setattr(qfq, "_symbol_checkpoint", lambda *a: (CODES[0], tmp_path / "single.parquet"))
    assert qfq._symbol_process_task((CODES[0], {}, TARGET, {}, str(tmp_path), {})) == (CODES[0], str(tmp_path / "single.parquet"), None)
