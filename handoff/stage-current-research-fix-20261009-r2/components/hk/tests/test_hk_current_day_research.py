"""Synthetic current-day input tests; never claim the four Mac inputs were read."""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import sys

import pytest


COMPONENT = Path(__file__).resolve().parents[1]
TASK = COMPONENT.parents[1]
RUNTIME = Path(os.environ.get("V4_HK_TEST_RUNTIME", str(COMPONENT / "evidence" / "runtime")))
if not os.environ.get("V4_HK_TEST_RUNTIME"):
    shutil.copytree(TASK / "runtime_before" / "actual_stage", RUNTIME, dirs_exist_ok=True)
    shutil.copytree(COMPONENT / "after", RUNTIME, dirs_exist_ok=True)
    for sibling in (TASK / "components/collectors/after", TASK / "components/receipt/after/actual_stage"):
        if sibling.is_dir():
            shutil.copytree(sibling, RUNTIME, dirs_exist_ok=True)
sys.path.insert(0, str(RUNTIME))


def test_explicit_research_root_is_optional_and_forwarded(tmp_path):
    import ast
    declaration = next(node for node in ast.parse((RUNTIME / "stage_center/runner.py").read_text()).body
                       if isinstance(node, ast.FunctionDef) and node.name == "build_production_config")
    assert "hk_current_day_research_root" in {arg.arg for arg in declaration.args.kwonlyargs}
    from stage_center.runner import build_production_config
    import inspect
    assert "hk_current_day_research_root" in inspect.signature(build_production_config).parameters
    roots = dict(candidate_acquisition_root=tmp_path / "a", raw_root=tmp_path / "raw",
                 selection_root=tmp_path / "selection", receipt_root=tmp_path / "receipts")
    assert build_production_config(**roots).hk_current_day_research_root is None
    assert build_production_config(**roots, hk_current_day_research_root=tmp_path / "hk").hk_current_day_research_root == tmp_path / "hk"


def test_new_runner_config_field_preserves_existing_positional_parameters():
    from dataclasses import fields
    from stage_center.runner import RunnerConfig
    assert fields(RunnerConfig)[-1].name == "hk_current_day_research_root"


@pytest.fixture
def research():
    return importlib.import_module("stage_center.hk_current_day_research")


@pytest.fixture
def inputs(tmp_path, research):
    codes = [f"HK.{n:05d}" for n in range(1, 696)]
    rows = [{"code": code, "name": f"Synthetic {n}", "outstanding_shares": 1_000_000 + n,
             "circular_market_val": 2_000_000 + n, "listing_date": "2020-01-01",
             "lot_size": 100, "stock_owner": "", "stock_child_type": "EQ", "sec_status": "NORMAL"}
            for n, code in enumerate(codes)]
    declaration = copy.deepcopy(research.CAPTURE_20261009)
    documents = {"snapshot": rows, "receipt": {"synthetic": True}, "reference_codes": codes,
                 "final_receipt": {"synthetic": True}}
    for key, payload in documents.items():
        path = tmp_path / declaration["source_files"][key]["file"]
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        declaration["source_files"][key]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return tmp_path, declaration, codes, rows


def test_real_file_bytes_define_research_binding_without_d1_aliases(research, inputs):
    root, declaration, codes, _rows = inputs
    value = research.read_research_input(root, "20261009", "STAGE_1545_1555", declaration=declaration)
    assert list(value["codes"]) == codes
    meta = value["metadata"]
    assert meta["input_mode"] == "CURRENT_DAY_RESEARCH_ONLY"
    assert meta["current_connect_eligibility"] == "CANNOT_CONFIRM"
    assert meta["universe_as_of"] == "20261008" and meta["stale_universe"] is True
    assert meta["captured_at"] == "2026-10-09T15:38:41+08:00"
    assert meta["RESEARCH_ONLY"] is True
    assert not any(meta[k] for k in ("production_allowed", "buy_gate_updated", "orders_sent"))
    assert value["sha256"] == meta["input_binding_sha256"]
    assert not any("hk_d1" in item or "STRICT_0_2_READY" in item for item in value["evidence"])
    assert len(list(root.iterdir())) == 4


@pytest.mark.parametrize("stage", ["STAGE_0925", "STAGE_0930_0935", "STAGE_1300_1315", "STAGE_1445_1500"])
def test_afternoon_capture_cannot_be_used_for_earlier_stage(research, inputs, stage):
    root, declaration, *_ = inputs
    with pytest.raises(ValueError, match="AFTER_STAGE_CUTOFF"):
        research.read_research_input(root, "20261009", stage, declaration=declaration)


@pytest.mark.parametrize("date", ["20261008", "20261010"])
def test_current_day_capture_cannot_be_relabelled_to_another_date(research, inputs, date):
    root, declaration, *_ = inputs
    with pytest.raises(ValueError, match="CAPTURE_DATE_MISMATCH"):
        research.read_research_input(root, date, "STAGE_1545_1555", declaration=declaration)


@pytest.mark.parametrize("key", ["snapshot", "receipt", "reference_codes", "final_receipt"])
def test_every_input_file_is_rechecked_before_use(research, inputs, key):
    root, declaration, *_ = inputs
    research.read_research_input(root, "20261009", "STAGE_1545_1555", declaration=declaration)
    path = root / declaration["source_files"][key]["file"]
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="SHA_MISMATCH"):
        research.read_research_input(root, "20261009", "STAGE_1545_1555", declaration=declaration)


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "foreign"])
def test_snapshot_must_match_all_695_unique_reference_codes(research, inputs, mutation):
    root, declaration, codes, rows = inputs
    if mutation == "duplicate":
        rows[-1]["code"] = rows[0]["code"]
    elif mutation == "missing":
        rows.pop()
    else:
        rows[-1]["code"] = "HK.09999"
    path = root / declaration["source_files"]["snapshot"]["file"]
    path.write_text(json.dumps(rows), encoding="utf-8")
    declaration["source_files"]["snapshot"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="MEMBERSHIP"):
        research.read_research_input(root, "20261009", "STAGE_1545_1555", declaration=declaration)


def test_user_pins_are_not_silently_replaced_with_fixture_hashes(research, inputs):
    root, *_ = inputs
    with pytest.raises(ValueError, match="SHA_MISMATCH"):
        research.read_research_input(root, "20261009", "STAGE_1545_1555")


def test_symlink_input_is_rejected(research, inputs, tmp_path):
    root, declaration, *_ = inputs
    path = root / declaration["source_files"]["snapshot"]["file"]
    target = root / "outside.json"
    path.rename(target)
    path.symlink_to(target)
    with pytest.raises(ValueError, match="SYMLINK"):
        research.read_research_input(root, "20261009", "STAGE_1545_1555", declaration=declaration)


def test_binding_metadata_detects_code_or_metadata_tamper(research, inputs, monkeypatch):
    root, declaration, *_ = inputs
    monkeypatch.setattr(research, "CAPTURE_20261009", declaration)
    binding = research.build_research_binding(root, "20261009", "STAGE_1545_1555")
    assert research.research_metadata(binding)["input_binding_sha256"] == binding.sha256
    from dataclasses import replace
    with pytest.raises(ValueError, match="BINDING"):
        research.research_metadata(replace(binding, codes=binding.codes[:-1]))


def test_rehashed_binding_cannot_move_afternoon_capture_into_morning(research, inputs, monkeypatch):
    root, declaration, *_ = inputs
    monkeypatch.setattr(research, "CAPTURE_20261009", declaration)
    binding = research.build_research_binding(root, "20261009", "STAGE_1545_1555")
    metadata = research.research_metadata(binding)
    metadata["stage_id"] = "STAGE_0930_0935"
    metadata["cutoff_at"] = "09:35:05"
    metadata.pop("input_binding_sha256")
    sha = hashlib.sha256(json.dumps({"metadata": metadata, "codes": list(binding.codes)},
        ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    metadata["input_binding_sha256"] = sha
    from dataclasses import replace
    evidence = tuple(item for item in binding.evidence if not item.startswith(research.EVIDENCE_PREFIX))
    evidence += (research.EVIDENCE_PREFIX + json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")),)
    changed = replace(binding, sha256=sha, source_run_id="hk-current-research-" + sha[:16], evidence=evidence)
    with pytest.raises(ValueError, match="CUTOFF"):
        research.research_metadata(changed)


def test_metadata_overlay_preserves_actual_quotes_and_does_not_create_lane(research, inputs, monkeypatch):
    root, declaration, codes, _ = inputs
    monkeypatch.setattr(research, "CAPTURE_20261009", declaration)
    binding = research.build_research_binding(root, "20261009", "STAGE_1545_1555")
    from stage_center.acquisition import SourceResult
    row = {"code": codes[0], "close": 12.3, "last_price": 12.3,
           "data_time": "2026-10-09T15:55:00+08:00", "volume": 100}
    result = research.attach_security_metadata(SourceResult("pytdx", "READY", rows=(row,)), binding)
    assert result.rows[0]["close"] == 12.3
    assert result.rows[0]["data_time"] == row["data_time"]
    assert result.rows[0]["name"] == "Synthetic 0"
    assert "d1_status" not in result.rows[0]
    assert not result.rows[0].get("candidate_lanes")
    assert result.status == "PARTIAL_WITH_ROWS"


def test_explicit_invalid_root_never_falls_back_to_strict_d1(tmp_path, monkeypatch):
    import stage_center.runner as runner
    config = runner.build_production_config(candidate_acquisition_root=tmp_path / "a", raw_root=tmp_path / "r",
        selection_root=tmp_path / "s", receipt_root=tmp_path / "e", hk_d1_root=tmp_path / "strict",
        hk_current_day_research_root=tmp_path / "missing")
    def unexpected(*args, **kwargs):
        raise AssertionError("STRICT fallback is forbidden when research root is explicit")
    monkeypatch.setattr(runner, "_build_hk_stage_binding", unexpected)
    with pytest.raises(runner.RunnerError, match="HK_CURRENT_DAY_RESEARCH"):
        runner._build_configured_hk_binding(config, "20261009", "STAGE_1545_1555")


def test_default_binding_keeps_original_strict_authority(tmp_path, monkeypatch):
    import stage_center.runner as runner
    config = runner.build_production_config(candidate_acquisition_root=tmp_path / "a", raw_root=tmp_path / "r",
        selection_root=tmp_path / "s", receipt_root=tmp_path / "e", hk_d1_root=tmp_path / "strict")
    marker = object()
    monkeypatch.setattr(runner, "_build_hk_stage_binding", lambda root, date, **kwargs: marker)
    assert runner._build_configured_hk_binding(config, "20261009", "STAGE_1545_1555") is marker


def test_optional_a_context_roots_do_not_erase_verified_candidate(tmp_path):
    import stage_center.runner as runner
    config = runner.build_production_config(candidate_acquisition_root=tmp_path / "a", raw_root=tmp_path / "r",
        selection_root=tmp_path / "s", receipt_root=tmp_path / "e")
    evidence = runner._validate_exact_selection_inputs(config, "20261009", "STAGE_1300_1315", market="A_SHARE")
    assert "a_research_context_unavailable=ROOT_NOT_BOUND" in evidence
    raw = {}
    runner._attach_stage_research_roots(raw, config, "STAGE_1300_1315", market="A_SHARE")
    assert raw.get("_v4_research_data_root") is None


def test_node_config_accepts_explicit_research_root_without_formal_d1_root(tmp_path):
    from ops.run_stage_center_nodes import REQUIRED_CONFIG_KEYS, _load_config, _build_runner
    config = {key: str(tmp_path / key) for key in REQUIRED_CONFIG_KEYS if key != "hk_d1_root"}
    config["hk_current_day_research_root"] = str(tmp_path / "hk_current_snapshot")
    path = tmp_path / "research_tick_config.json"
    path.write_text(json.dumps(config))
    loaded = _load_config(path)
    runner = _build_runner(loaded)
    assert runner.config.hk_current_day_research_root == tmp_path / "hk_current_snapshot"
    assert runner.config.hk_d1_root is None
    config.pop("hk_current_day_research_root")
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="hk_d1_root"):
        _load_config(path)


def _quotes(codes):
    return tuple({"batch_index": index, "code": code, "name": code,
        "update_time": "2026-10-09 15:55:00", "last_price": 10 + index / 1000,
        "open_price": 10, "high_price": 12, "low_price": 9, "prev_close_price": 9.5,
        "turnover": 150_000_000 + index, "volume": 100_000 + index,
        "bid_price": "", "ask_price": "", "bid_vol": "", "ask_vol": "",
        "window_start": "2026-10-09 15:45:00", "window_end": "2026-10-09 15:55:00", "bar_count": 11,
        "temporal_cutoff_safe": True} for index, code in enumerate(codes, 1))


@pytest.mark.parametrize("mutate_after_collection", [False, True])
def test_actual_runner_to_original_four_lane_and_immutable_trios(research, inputs, monkeypatch, tmp_path,
                                                                 mutate_after_collection):
    """Only the provider boundary is synthetic; runner, formula and stores are native."""
    root, declaration, codes, _ = inputs
    monkeypatch.setattr(research, "CAPTURE_20261009", declaration)
    from datetime import datetime
    from stage_center.acquisition import SourceResult
    from stage_center.runner import build_production_config, StageCenterRunner
    from stage_center.selection import SelectionStore
    if os.environ.get("V4_RAW_SIGNATURE_SUPPORT", "strict_false") == "strict_false":
        from raw_store_test_support import install_strict_false_keyword_adapter
        adapter = install_strict_false_keyword_adapter(monkeypatch)
        with pytest.raises(ValueError, match="REFUSES_TEMPORAL_FALSE"):
            adapter({}, [], trade_date="20261009", stage_id="STAGE_1545_1555", market="HK_CONNECT",
                    allow_temporal_false_observation=True)
    calls = []
    def provider(plan, market):
        calls.append((plan.trade_date, plan.stage_id, market, len(plan.codes_for(market))))
        assert plan.universe_bindings[market].role == "CURRENT_DAY_RESEARCH_ONLY"
        if mutate_after_collection:
            path = root / declaration["source_files"]["final_receipt"]["file"]
            path.write_bytes(path.read_bytes() + b" ")
        observed = tuple(codes[:-11])
        return SourceResult("pytdx_exhq", "PARTIAL_WITH_ROWS", rows=_quotes(observed),
            requested_rows=695, missing_symbols=tuple(codes[-11:]),
            cannot_confirm=("SYNTHETIC_PROVIDER_11_SYMBOLS_MISSING",),
            source_evidence=("synthetic_provider=true", "source_last_bar_time=2026-10-09 15:55:00"))
    outputs = tmp_path / "output"
    config = build_production_config(candidate_acquisition_root=tmp_path / "missing_a",
        raw_root=outputs / "raw", selection_root=outputs / "selections", receipt_root=outputs / "receipts",
        hk_current_day_research_root=root, shared_data_root=tmp_path / "shared", python_path=Path(sys.executable))
    runner = StageCenterRunner(config, collectors={"HK_CONNECT": provider})
    result = runner.tick("20261009", datetime.fromisoformat("2026-10-09T17:05:26+08:00"), stage_id="STAGE_1545_1555")
    assert calls == [("20261009", "STAGE_1545_1555", "HK_CONNECT", 695)]
    if mutate_after_collection:
        assert result["write_performed"] is False
        assert "SHA_MISMATCH" in json.dumps(result)
        assert not (config.selection_root / "latest.json").exists()
        assert not (config.raw_root / "latest.json").exists()
        return
    assert result["write_performed"] is True, result
    selected = result["markets"]["HK_CONNECT"]
    assert selected["selected_rows"] == 10 and selected["requested_rows"] == 695
    assert selected["source_rows"] == 684
    assert selected["hk_current_day_research"]["current_connect_eligibility"] == "CANNOT_CONFIRM"
    assert result["execution_mode"] == "MANUAL_CURRENT_DAY_RESEARCH"
    assert result["natural_execution_verified"] is False
    assert result["input_bindings"]["HK_CONNECT"]["kind"] == "CURRENT_DAY_RESEARCH_ONLY"
    assert "runtime_source_identity" in selected
    assert selected["RESEARCH_ONLY"] is True
    verified = SelectionStore(config.selection_root)._verify_run("20261009", "STAGE_1545_1555", "HK_CONNECT", selected["run_id"])
    assert verified["envelope"] == selected
    binding = result["selection_artifacts"]["HK_CONNECT"]
    assert binding["run_id"] == selected["run_id"]
    for key in ("artifact", "manifest", "receipt"):
        payload = (config.selection_root / binding[key + "_relative"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == binding[key + "_bytes_sha256"]
    assert all(selected[k] is False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))


@pytest.mark.parametrize("observed_count", [205, 206])
def test_a_216_lane_keeps_original_top10_when_afternoon_hk_input_cannot_enter_1315(
        research, inputs, monkeypatch, tmp_path, observed_count):
    """Candidate reader alone is an explicit prevalidated-dataclass seam.

    This test proves lane isolation downstream of candidate validation. It does
    not claim to revalidate the unprovided Mac candidate-input current chain.
    Quotes are synthetic. Runner, exact-input gates, original selector, strict
    raw validator and immutable file publication are exercised.
    """
    from datetime import datetime
    import stage_center.runner as runner_module
    from stage_center.acquisition import SourceResult
    from stage_center.candidate_input import CandidateInput
    from stage_center.selection import SelectionStore
    if os.environ.get("V4_RAW_SIGNATURE_SUPPORT", "strict_false") == "strict_false":
        from raw_store_test_support import install_strict_false_keyword_adapter
        install_strict_false_keyword_adapter(monkeypatch)
    root, declaration, *_ = inputs
    monkeypatch.setattr(research, "CAPTURE_20261009", declaration)
    codes = tuple(f"A.{600000 + n:06d}" for n in range(216))
    digest = lambda label: hashlib.sha256(label.encode()).hexdigest()
    candidate = CandidateInput(root=tmp_path / "a_input", trade_date="20261009", current_relative="synthetic/current.json",
        current_sha256=digest("synthetic current"), run_id="synthetic-prevalidated-a-216", codes=codes,
        artifact_sha256=digest("synthetic artifact"), manifest_sha256=digest("synthetic manifest"),
        receipt_sha256=digest("synthetic receipt"), source_projection_sha256=digest("synthetic source"),
        source_evidence=("synthetic_candidate_reader=INJECTED_PREVALIDATED_DATACLASS",))
    def candidate_reader(_root, date, *, expected_current_sha256=None):
        assert date == candidate.trade_date
        assert expected_current_sha256 in (None, candidate.current_sha256)
        return candidate
    monkeypatch.setattr(runner_module, "read_candidate_input", candidate_reader)
    calls = []
    def a_provider(plan, market):
        calls.append((market, len(plan.codes_for(market))))
        rows = tuple({**row, "update_time": "2026-10-09 13:15:00",
                      "window_start": "2026-10-09 13:00:00", "window_end": "2026-10-09 13:15:00"}
                     for row in _quotes(codes[:observed_count]))
        return SourceResult("pytdx_hq", "PARTIAL_WITH_ROWS", rows=rows,
            requested_rows=216, missing_symbols=codes[observed_count:],
            cannot_confirm=("SYNTHETIC_PROVIDER_MISSING_INDIVIDUAL_SYMBOLS",),
            source_evidence=("synthetic_provider=true",))
    def forbidden_hk_provider(*_):
        raise AssertionError("HK afternoon capture must be rejected before collector")
    output = tmp_path / "a_hk_output"
    config = runner_module.build_production_config(candidate_acquisition_root=candidate.root,
        raw_root=output / "raw", selection_root=output / "selection", receipt_root=output / "receipt",
        hk_current_day_research_root=root, shared_data_root=tmp_path / "shared", python_path=Path(sys.executable))
    instance = runner_module.StageCenterRunner(config, collectors={"A_SHARE": a_provider, "HK_CONNECT": forbidden_hk_provider})
    result = instance.tick("20261009", datetime.fromisoformat("2026-10-09T17:05:26+08:00"), stage_id="STAGE_1300_1315")
    assert calls == [("A_SHARE", 216)]
    assert result["write_performed"] is True, result
    a_result, hk_result = result["markets"]["A_SHARE"], result["markets"]["HK_CONNECT"]
    assert a_result["selected_rows"] == 10 and a_result["requested_rows"] == 216
    assert a_result["source_rows"] == observed_count
    assert len(a_result["missing_symbols"]) == 216 - observed_count
    assert result["input_bindings"]["A_SHARE"]["row_count"] == 216
    assert hk_result["selected_rows"] == 0 and hk_result["write_performed"] is False
    assert "CAPTURE_AFTER_STAGE_CUTOFF" in json.dumps(hk_result)
    latest = json.loads((config.raw_root / "latest.json").read_text())["entries"]
    assert set(latest) == {"20261009/STAGE_1300_1315/A_SHARE"}
    stored = SelectionStore(config.selection_root)._verify_run("20261009", "STAGE_1300_1315", "A_SHARE", a_result["run_id"])
    assert stored["envelope"] == a_result
