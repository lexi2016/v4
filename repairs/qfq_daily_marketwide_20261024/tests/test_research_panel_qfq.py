from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import struct

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ops import research_panel_adjustment_inputs as inputs
from ops import research_panel_qfq as qfq

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "ops/vendor/data_layer_daily_formula_increment_update_v1.py"
FORMULA = ROOT / "ops/vendor/build_canonical_formula_research_panel.py"


@pytest.fixture
def driver():
    return qfq.authorities(DRIVER, FORMULA)[0]


def raw_frame(code="002612.SZ", count=300):
    x = np.arange(count)
    close = np.round(12 + x / 150 + np.sin(x / 8) * 1.5, 2)
    return pd.DataFrame(dict(ts_code=code, trade_date=pd.bdate_range("2025-01-01", periods=count).strftime("%Y%m%d").astype(int),
                             open=close - .1, high=close + .5, low=close - .5, close=close,
                             vol=10000 + ((x * 913) % 100000), volume=10000 + ((x * 913) % 100000), amount=1000000 + x * 123))


def write_day(path, frame):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        for row in frame.itertuples():
            handle.write(struct.pack("<IIIIIfII", row.trade_date, round(row.open * 100), round(row.high * 100),
                                     round(row.low * 100), round(row.close * 100), row.amount, row.vol, 0))


def test_affine_composition_and_independent_volume_factor_preserve_actual_amount():
    raw = raw_frame(count=10)
    events = [dict(ex_date=int(raw.trade_date[4]), a=.77, b=-.29, volume_a=1.29754), dict(ex_date=int(raw.trade_date[8]), a=1, b=-.123, volume_a=1)]
    adjusted = qfq.apply_adjustments(raw, events, int(raw.trade_date.iloc[-1]))
    assert adjusted.close[0] == (raw.close[0] * .77 - .29) - .123
    assert adjusted.close[4] == raw.close[4] - .123
    assert adjusted.close[8] == raw.close[8]
    np.testing.assert_allclose(adjusted.volume[:4], raw.volume[:4] * 1.29754)
    pd.testing.assert_series_equal(adjusted.amount, raw.amount)


def test_controller_counterexample_forbids_cent_rounding_and_raw_volume():
    raw = pd.DataFrame(dict(ts_code=["001283.SZ"] * 3, trade_date=[20260522, 20260525, 20260526],
                            open=[82.21, 79.68, 61.11], high=[82.21, 79.68, 61.11], low=[82.21, 79.68, 61.11],
                            close=[82.21, 79.68, 61.11], volume=[10070953, 6898523, 4000000],
                            vol=[10070953, 6898523, 4000000], amount=[1., 2., 3.]))
    out = qfq.apply_adjustments(raw, [dict(ex_date=20260526, a=.77069, b=-.29046, volume_a=1.29754)], 20260526)
    assert out.close[0] == pytest.approx(82.21 * .77069 - .29046)
    assert out.close[0] != round(out.close[0], 2)
    assert out.volume[0] == pytest.approx(10070953 * 1.29754)
    assert out.volume[0] != raw.volume[0]
    # The SDK's rounded event coefficients and server's internal coefficients
    # need not be bitwise equal. This is evidence of the stated precision
    # boundary, never a coefficient fitting objective.
    assert abs(out.close[0] - 63.067899522) < .001
    assert abs(out.volume[0] - 13067463) < 2
    assert out.volume[2] == raw.volume[2]


def test_pair_retains_key_types_and_promotes_only_frozen_core_to_double(tmp_path, driver):
    kwargs, _, _ = fixture_panel(tmp_path, driver)
    old_columns = {}
    old_date_types = {}
    for role, pointer in kwargs["pointers"].items():
        path = Path(pointer.read_text())
        old = pq.read_table(path).to_pandas()
        if role == "selector":
            old["trade_date"] = old.trade_date.astype(str)
        else:
            old["trade_date"] = old.trade_date.astype("int32")
            for col in ("open", "high", "low", "close", "volume", "BBI", "J", "zge_white_line", "zge_yellow_line"):
                old[col] = old[col].astype("float32")
        pq.write_table(pa.Table.from_pandas(old, preserve_index=False), path)
        old_columns[role] = old.columns.tolist()
        old_date_types[role] = pq.ParquetFile(path).schema_arrow.field("trade_date").type
    result = qfq.run_daily_rebuild(**kwargs)
    for role, path in result["candidates"].items():
        schema = pq.ParquetFile(path).schema_arrow
        assert schema.names == old_columns[role]
        assert schema.field("trade_date").type == old_date_types[role]
        for col in ("open", "high", "low", "close", "volume", "BBI", "J", "zge_white_line", "zge_yellow_line"):
            assert schema.field(col).type == pa.float64()


def test_exact_original_formula_against_independent_scalar_oracle(tmp_path, driver):
    raw = raw_frame()
    path = tmp_path / "sz002612.day"
    write_day(path, raw)
    item = dict(raw_files=[dict(path=str(path), sha256=qfq.sha(path))], history_start_date=int(raw.trade_date.min()),
                events=[dict(ex_date=int(raw.trade_date[210]), a=.77069, b=-.29046, volume_a=1.29754)])
    actual = qfq.rebuild_symbol("002612.SZ", item, int(raw.trade_date.iloc[-1]), driver)
    price = qfq.apply_adjustments(raw, item["events"], int(raw.trade_date.iloc[-1]))
    close, volume = price.close.tolist(), price.volume.tolist()
    def ma(values, at, n):
        return sum(values[max(0, at - n + 1):at + 1]) / min(n, at + 1)
    first_ema, white, j_values, b1, b2, b3 = [], [], [], [], [], []
    k = d = 50.0
    for at, value in enumerate(close):
        first_ema.append(value if at == 0 else (2 * value + 9 * first_ema[-1]) / 11)
        white.append(first_ema[-1] if at == 0 else (2 * first_ema[-1] + 9 * white[-1]) / 11)
        yellow = sum(ma(close, at, n) for n in (14, 28, 57, 114)) / 4
        bbi = sum(ma(close, at, n) for n in (3, 6, 12, 24)) / 4
        low, high = price.low[max(0, at - 8):at + 1].min(), price.high[max(0, at - 8):at + 1].max()
        rsv = (value - low) / (high - low) * 100
        k = (2 * k + rsv) / 3
        d = (2 * d + k) / 3
        j_values.append(3 * k - 2 * d)
        change = (value / close[at - 1] - 1) * 100 if at else np.nan
        previous_change = (close[at - 1] / close[at - 2] - 1) * 100 if at >= 2 else np.nan
        previous_ma = ma(volume[:-1], at - 1, 4) if at else np.nan
        yest_ma = ma(volume[:-2], at - 2, 4) if at >= 2 else np.nan
        yesterday_up = at >= 2 and volume[at - 1] > yest_ma * 1.15
        ratio = volume[at] / volume[at - 1] if at else np.nan
        true_break = change > 0 or (change > -3 and (ratio < .6 or ratio > .9))
        b1.append(int(bbi > white[-1] > yellow and j_values[-1] <= 13))
        b2.append(int(any(j < 13 for j in j_values[max(0, at - 2):]) and volume[at] > previous_ma * 1.25 and change > 4 and j_values[-1] < 70 and white[-1] > yellow))
        b3.append(int(at >= 2 and j_values[at - 2] < 20 and yesterday_up and previous_change > 3 and white[-1] > yellow and true_break))
        assert actual.BBI[at] == pytest.approx(bbi, abs=1e-12)
        assert actual.zge_yellow_line[at] == pytest.approx(yellow, abs=1e-12)
    np.testing.assert_allclose(actual.zge_white_line, white, atol=1e-12)
    np.testing.assert_allclose(actual.J, j_values, atol=1e-10)
    np.testing.assert_array_equal(actual.B1, b1)
    np.testing.assert_array_equal(actual.B2, b2)
    np.testing.assert_array_equal(actual.B3, b3)
    np.testing.assert_allclose(actual.pre_close, price.close.shift(), equal_nan=True)


def test_pair_second_write_failure_restores_exact_bytes_and_crash_journal(tmp_path, monkeypatch):
    pointers = {r: tmp_path / (r + ".txt") for r in ("selector", "backtest")}
    expected = dict(selector=b"\xef\xbb\xbf/old/selector\r\n", backtest=b"/old/backtest\n")
    for role, path in pointers.items():
        path.write_bytes(expected[role])
    candidates = {r: tmp_path / (r + ".parquet") for r in pointers}
    original = qfq._write
    writes = []
    def fail_second(path, payload):
        if path in pointers.values():
            writes.append(path)
            if len(writes) == 2:
                raise OSError("injected second pointer failure")
        original(path, payload)
    monkeypatch.setattr(qfq, "_write", fail_second)
    journal = tmp_path / "journal.json"
    with pytest.raises(OSError, match="injected"):
        qfq.publish_pair(pointers, candidates, expected, journal)
    assert {r: p.read_bytes() for r, p in pointers.items()} == expected
    record = json.loads(journal.read_text())
    assert record["status"] == "ROLLED_BACK"
    record["status"] = "PREPARED"
    pointers["selector"].write_text(record["after"]["selector"])
    journal.write_text(json.dumps(record))
    qfq.recover_pair(journal, pointers)
    assert {r: p.read_bytes() for r, p in pointers.items()} == expected


def fixture_panel(tmp_path, driver):
    tdx = tmp_path / "tdx"
    data = tmp_path / "data"
    source = tmp_path / "factor_source.json"
    source.write_text('{"kind":"synthetic software fixture"}')
    symbols, frames = {}, []
    for code in ("002612.SZ", "001283.SZ"):
        raw = raw_frame(code)
        path = tdx / "vipdoc/sz/lday" / ("sz" + code[:6] + ".day")
        write_day(path, raw)
        item = dict(raw_files=[dict(path=str(path), sha256=qfq.sha(path))], history_start_date=int(raw.trade_date.min()),
                    events=[], event_coverage_complete=True, publish_roles=["selector", "backtest"])
        symbols[code] = item
        frames.append(qfq.rebuild_symbol(code, item, int(raw.trade_date.iloc[-1]), driver))
    frame = pd.concat(frames).reset_index(drop=True)
    target = int(frame.trade_date.max())
    selected = ["ts_code", "trade_date", "open", "high", "low", "close", "volume", "amount", "pre_close", "BBI", "J", "zge_white_line", "zge_yellow_line", "B1", "B2", "B3", "kdj_k", "kdj_d", *driver.V192_ENTRY_FIELDS, *driver.V192_INTERMEDIATE_FIELDS, "formula_source"]
    selected = list(dict.fromkeys(selected + [c for c in driver.CRITICAL_SELECTOR_FORMULA_COLUMNS if c in frame]))
    old = frame.loc[frame.trade_date.lt(target), selected].copy()
    old["name"] = "historical name"
    old["B1"] = 0
    pointers = {"selector": data / "data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt",
                "backtest": data / "backtest_panel_interface_current/CURRENT_BACKTEST_BASE_PANEL.txt"}
    for role, pointer in pointers.items():
        pointer.parent.mkdir(parents=True)
        current = tmp_path / (role + "_old.parquet")
        pq.write_table(pa.Table.from_pandas(old, preserve_index=False), current)
        pointer.write_text(str(current))
    snapshot = dict(schema="a_share_qfq_adjustment_input_v1", asof_date=target, coverage_end_date=target,
                    price_basis="QFQ_ASOF", volume_basis="QFQ_EVENT_VOLUME", amount_basis="RAW_TURNOVER", convention="SOFTWARE_FIXTURE",
                    revision="fixture1", observed_at=datetime.now(timezone.utc).isoformat(),
                    source_files=[dict(path=str(source), sha256=qfq.sha(source))], symbols=symbols)
    qfq._json(qfq.input_path(data), snapshot)
    contract = tmp_path / "field_contract.csv"
    contract.write_text("synthetic software fixture\n")
    kwargs = dict(driver_path=DRIVER, formula_path=FORMULA, tdx_root=tdx, data_root=data, pointers=pointers,
                  contract_csv=contract, return_root=tmp_path / "runs", target=target, workers=2)
    return kwargs, snapshot, frame


def test_full_history_revision_candidate_idempotence_and_original_versions_preserved(tmp_path, driver):
    kwargs, snapshot, _ = fixture_panel(tmp_path, driver)
    pointers = kwargs["pointers"]
    before = {r: p.read_bytes() for r, p in pointers.items()}
    old_paths = {r: Path(p.read_text()) for r, p in pointers.items()}
    old_hashes = {r: qfq.sha(p) for r, p in old_paths.items()}
    first = qfq.run_daily_rebuild(**kwargs)
    assert first["status"] == "CANDIDATE_READY"
    assert {r: p.read_bytes() for r, p in pointers.items()} == before
    candidates = {r: Path(p) for r, p in first["candidates"].items()}
    current = pq.read_table(candidates["selector"]).to_pandas()
    assert current.trade_date.max() == kwargs["target"]
    assert not current.duplicated(["ts_code", "trade_date"]).any()
    qfq.publish_pair(pointers, candidates, before, tmp_path / "journal.json")
    second = qfq.run_daily_rebuild(**kwargs)
    assert second["status"] == "READY" and second["already_current"] is True
    code = "002612.SZ"
    snapshot["symbols"][code]["events"] = [dict(ex_date=int(current.trade_date.max()), a=1, b=-1, volume_a=1)]
    snapshot["revision"] = "fixture2"
    qfq._json(qfq.input_path(kwargs["data_root"]), snapshot)
    revised = qfq.run_daily_rebuild(**kwargs)
    updated = pq.read_table(revised["candidates"]["selector"]).to_pandas()
    early = updated.ts_code.eq(code) & updated.trade_date.lt(kwargs["target"])
    np.testing.assert_allclose(updated.loc[early, "close"], current.loc[early, "close"] - 1)
    assert {r: qfq.sha(p) for r, p in old_paths.items()} == old_hashes
    assert qfq.sha(candidates["selector"]) == first["candidate_sha256"]["selector"]


def test_missing_factor_or_history_fails_without_pointer_changes(tmp_path, driver):
    kwargs, snapshot, _ = fixture_panel(tmp_path, driver)
    expected = {r: p.read_bytes() for r, p in kwargs["pointers"].items()}
    snapshot["symbols"].pop("002612.SZ")
    qfq._json(qfq.input_path(kwargs["data_root"]), snapshot)
    with pytest.raises(qfq.QfqGateError, match="MARKETWIDE_ADJUSTMENT_COVERAGE_MISSING"):
        qfq.run_daily_rebuild(**kwargs)
    assert {r: p.read_bytes() for r, p in kwargs["pointers"].items()} == expected
    old = pd.DataFrame(dict(trade_date=[20200101], ts_code=["002612.SZ"], close=[12.]))
    with pytest.raises(qfq.QfqGateError, match="RAW_HISTORY_KEYS_MISSING"):
        qfq.merge_rebuilt(old, raw_frame(count=20), role="selector", driver=driver)


def test_publish_requires_futu_oracle_and_snapshot_revision_invalidates_ready(tmp_path, driver):
    kwargs, snapshot, _ = fixture_panel(tmp_path, driver)
    before = {r: p.read_bytes() for r, p in kwargs["pointers"].items()}
    qfq._json(qfq.input_path(kwargs["data_root"]).with_name("qfq_expected_current.json"), qfq.baseline_binding(kwargs["pointers"]))
    with pytest.raises(qfq.QfqGateError, match="FUTU_DISPLAY_ORACLE_MISSING"):
        qfq.run_daily_rebuild(**kwargs, publish=True)
    assert {r: p.read_bytes() for r, p in kwargs["pointers"].items()} == before


def test_raw_history_gap_blocks_network(tmp_path, driver):
    tdx = tmp_path / "tdx"
    raw = raw_frame(count=10)
    write_day(tdx / "vipdoc/sz/lday/sz002612.day", raw)
    qfq._json(tdx.parent / "receipts/a_sync_authority" / str(raw.trade_date.iloc[-1]) / "summary.json",
              dict(target_date=str(raw.trade_date.iloc[-1]), target_keys=["fixture"], accepted_target_date_file_count=1, symbol_reconciliation=[]))
    def forbidden():
        raise AssertionError("history preflight must run before OpenD")
    with pytest.raises(qfq.QfqGateError, match="RAW_FULL_HISTORY_INPUT_MISSING"):
        inputs.prepare_snapshot(tdx_root=tdx, data_root=tmp_path / "data", target=int(raw.trade_date.iloc[-1]), driver=driver,
                                required_start={"002612.SZ": 20200101}, client_factory=forbidden)


def test_display_oracle_string_date_and_future_convention_acceptance(tmp_path, driver):
    kwargs, _, _ = fixture_panel(tmp_path, driver)
    path = Path(kwargs["pointers"]["selector"].read_text())
    old = pq.read_table(path).to_pandas()
    old.trade_date = old.trade_date.astype(str)
    pq.write_table(pa.Table.from_pandas(old, preserve_index=False), path)
    result = qfq.run_daily_rebuild(**kwargs)
    output = Path(result["candidates"]["selector"])
    values = pq.read_table(output).to_pandas()
    identity = {key: result[key] for key in qfq.generation_identity(json.loads(qfq.input_path(kwargs["data_root"]).read_text()), DRIVER, FORMULA, kwargs["contract_csv"])}
    rows, dates = [], {}
    for code, part in values.groupby("ts_code"):
        selected = part.sort_values("trade_date").tail(2)
        dates[code] = [int(x) for x in selected.trade_date]
        for _, row in selected.iterrows():
            value = dict(ts_code=code, trade_date=int(row.trade_date))
            value.update({col: format(float(row[col]), ".3f") for col in ("BBI", "zge_white_line", "zge_yellow_line", "J")})
            value.update({col: int(row[col]) for col in ("B1", "B2", "B3")})
            rows.append(value)
    source = tmp_path / "independent_capture_fixture.json"
    source.write_text('{"scope":"synthetic display gate only"}')
    oracle = dict(asof_date=kwargs["target"], input_sha256=identity["input_sha256"], observed_at="fixture", rows=rows,
                  required_dates=dates, source_files=[dict(path=str(source), sha256=qfq.sha(source))])
    qfq.verify_display_oracle(oracle, output, identity, kwargs["target"])
    wrong = json.loads(json.dumps(oracle))
    wrong["rows"][0]["zge_yellow_line"] = "999.000"
    with pytest.raises(qfq.QfqGateError, match="PROVIDER_CONVENTION_CONFLICT"):
        qfq.verify_display_oracle(wrong, output, identity, kwargs["target"])
    root = qfq.input_path(kwargs["data_root"]).parent
    acceptance = dict(status="PASS", reviewer_id="independent fixture", code_binding=qfq._code_binding(identity),
                      convention=result["convention"], initial_asof_date=kwargs["target"],
                      initial_oracle_receipt=dict(path=str(source), sha256=qfq.sha(source)))
    source.write_text(json.dumps(dict(status="PASS_FUTU_DISPLAY_ORACLE", asof_date=kwargs["target"], code_binding=qfq._code_binding(identity))))
    acceptance["initial_oracle_receipt"]["sha256"] = qfq.sha(source)
    qfq._json(root / "qfq_convention_acceptance.json", acceptance)
    qfq.verify_release_gate(root, output, identity, kwargs["target"] + 1, result["convention"])
    acceptance["code_binding"]["formula_sha256"] = "0" * 64
    qfq._json(root / "qfq_convention_acceptance.json", acceptance)
    with pytest.raises(qfq.QfqGateError, match="CONVENTION_NOT_ACCEPTED"):
        qfq.verify_release_gate(root, output, identity, kwargs["target"] + 1, result["convention"])


def seed_factor_cache(kwargs, snapshot):
    input_file = qfq.input_path(kwargs["data_root"])
    cache = input_file.parent / "futu_rehab" / str(kwargs["target"])
    state = dict(asof_date=kwargs["target"], status="READY", completed_at=datetime.now(timezone.utc).isoformat(), symbols={})
    for code in snapshot["symbols"]:
        response = cache / (code + "_empty.json")
        qfq._json(response, dict(code=code[-2:] + "." + code[:6], rows=[]))
        ref = dict(path=str(response), sha256=qfq.sha(response))
        state["symbols"][code] = dict(status="EMPTY", queried_at=datetime.now(timezone.utc).isoformat(), response=ref)
        snapshot["source_files"].append(ref)
        snapshot["symbols"][code]["source_method"] = "FUTU_GET_REHAB_AFFINE"
    qfq._json(cache / "checkpoint.json", state)
    qfq._json(input_file, snapshot)
    return cache, state


def test_ready_requires_paired_generation_and_same_asof_revision(tmp_path, driver):
    kwargs, snapshot, _ = fixture_panel(tmp_path, driver)
    seed_factor_cache(kwargs, snapshot)
    before = {r: p.read_bytes() for r, p in kwargs["pointers"].items()}
    result = qfq.run_daily_rebuild(**kwargs)
    qfq.publish_pair(kwargs["pointers"], {r: Path(p) for r, p in result["candidates"].items()}, before, tmp_path / "publish.json")
    qfq.run_daily_rebuild(**kwargs)  # idempotent path creates the validated readiness stamp
    input_file = qfq.input_path(kwargs["data_root"])
    assert qfq.pointer_ready(kwargs["pointers"]["selector"], kwargs["target"], input_file)
    snapshot["revision"] = "same-day-source-revision"
    qfq._json(input_file, snapshot)
    assert not qfq.pointer_ready(kwargs["pointers"]["selector"], kwargs["target"], input_file)


def test_latest_same_asof_cache_revision_invalidates_ready_but_requery_does_not(tmp_path, driver):
    kwargs, snapshot, _ = fixture_panel(tmp_path, driver)
    cache, original = seed_factor_cache(kwargs, snapshot)
    checkpoint = cache / "checkpoint.json"
    before = {r: p.read_bytes() for r, p in kwargs["pointers"].items()}
    result = qfq.run_daily_rebuild(**kwargs)
    qfq.publish_pair(kwargs["pointers"], {r: Path(p) for r, p in result["candidates"].items()}, before, tmp_path / "publish.json")
    qfq.run_daily_rebuild(**kwargs)
    input_file = qfq.input_path(kwargs["data_root"])
    snapshot_bytes = input_file.read_bytes()
    ready = lambda: qfq.pointer_ready(kwargs["pointers"]["selector"], kwargs["target"], input_file)
    assert ready()
    changed = json.loads(json.dumps(original))
    changed["symbols"]["002612.SZ"]["queried_at"] = datetime.now(timezone.utc).isoformat()
    changed["completed_at"] = datetime.now(timezone.utc).isoformat()
    # Extra unrelated checkpoint records and query-time changes are not price
    # revisions of the relevant input.
    changed["symbols"]["999999.SZ"] = dict(status="ERROR", error="unrelated")
    qfq._json(checkpoint, changed)
    assert ready()
    response = cache / "revised_response.json"
    qfq._json(response, dict(code="SZ.002612", rows=[dict(ex_div_date=str(kwargs["target"]), forward_adj_factorA=1,
                    forward_adj_factorB=-1, backward_adj_factorA=1)]))
    changed["symbols"]["002612.SZ"].update(status="OK", response=dict(path=str(response), sha256=qfq.sha(response)))
    qfq._json(checkpoint, changed)
    assert input_file.read_bytes() == snapshot_bytes
    assert not ready()  # original independent R1 reproduction
    for invalid in (dict(status="QUERYING"), dict(status="ERROR", error="network failure"),
                    dict(status="EMPTY", response=dict(path=str(response), sha256="0" * 64))):
        changed = json.loads(json.dumps(original))
        changed["symbols"]["002612.SZ"].update(invalid)
        qfq._json(checkpoint, changed)
        assert not ready()
    changed = json.loads(json.dumps(original))
    changed["symbols"].pop("002612.SZ")
    qfq._json(checkpoint, changed)
    assert not ready()
    qfq._json(checkpoint, original)
    assert ready()
    Path(original["symbols"]["002612.SZ"]["response"]["path"]).write_text("corrupted response bytes")
    assert not ready()


def test_factor_cache_identity_preserves_explicit_quarantine_and_tdx_states(tmp_path):
    data = tmp_path / "data"
    cache = qfq.input_path(data).parent / "futu_rehab/20261023"
    response = cache / "bj_unsupported.json"
    qfq._json(response, dict(code="BJ.830779", error="format of code is wrong"))
    ref = dict(path=str(response), sha256=qfq.sha(response))
    cached = dict(asof_date=20261023, symbols={"830779.BJ": dict(status="UNSUPPORTED_MARKET", response=ref),
        "000004.SZ": dict(status="ERROR", error="unknown stock")})
    qfq._json(cache / "checkpoint.json", cached)
    snapshot = dict(source_files=[ref], symbols={"830779.BJ": dict(source_method="TDX_OFFICIAL_TERMS_BOUND_CONVERSION")},
        quarantine_symbols={"000004.SZ": dict(factor_evidence=cached["symbols"]["000004.SZ"])})
    first = qfq.factor_cache_identity(data, 20261023, snapshot)
    cached["symbols"]["000004.SZ"]["queried_at"] = "timestamp-only-requery"
    qfq._json(cache / "checkpoint.json", cached)
    assert qfq.factor_cache_identity(data, 20261023, snapshot) == first
    cached["symbols"]["000004.SZ"]["status"] = "QUERYING"
    qfq._json(cache / "checkpoint.json", cached)
    with pytest.raises(qfq.QfqGateError, match="STATE_INVALID_OR_CHANGED"):
        qfq.factor_cache_identity(data, 20261023, snapshot)


def test_cache_state_change_during_build_cannot_publish_a_ready_generation(tmp_path, driver, monkeypatch):
    kwargs, snapshot, _ = fixture_panel(tmp_path, driver)
    cache, state = seed_factor_cache(kwargs, snapshot)
    pointers = kwargs["pointers"]
    before = {role: path.read_bytes() for role, path in pointers.items()}
    original = qfq.merge_rebuilt
    changed = False
    def change_cache(*args, **options):
        nonlocal changed
        frame = original(*args, **options)
        if not changed:
            changed = True
            state["symbols"]["002612.SZ"]["status"] = "OK"
            qfq._json(cache / "checkpoint.json", state)
        return frame
    monkeypatch.setattr(qfq, "merge_rebuilt", change_cache)
    with pytest.raises(qfq.QfqGateError, match="FACTOR_CACHE_CHANGED_DURING_BUILD"):
        qfq.run_daily_rebuild(**kwargs)
    assert {role: path.read_bytes() for role, path in pointers.items()} == before


def test_expected_baseline_rejects_pointer_and_target_content_drift(tmp_path, driver):
    kwargs, _, _ = fixture_panel(tmp_path, driver)
    pointers = kwargs["pointers"]
    baseline = qfq.baseline_binding(pointers)
    qfq.check_baseline(pointers, baseline)
    target = Path(pointers["selector"].read_text())
    with target.open("ab") as handle:
        handle.write(b"changed")
    with pytest.raises(qfq.QfqGateError, match="TARGET_HASH_CONFLICT"):
        qfq.check_baseline(pointers, baseline)


def test_original_quarantined_missing_raw_keeps_all_old_rows_and_values(tmp_path, driver):
    kwargs, snapshot, _ = fixture_panel(tmp_path, driver)
    code = "000004.SZ"
    old_values = {}
    for role, pointer in kwargs["pointers"].items():
        path = Path(pointer.read_text())
        frame = pq.read_table(path).to_pandas()
        excluded = frame.loc[frame.ts_code.eq("002612.SZ")].copy()
        excluded.ts_code = code
        # Old unknown-basis values must survive in quarantine exactly.
        excluded.close = 123.456
        old_values[role] = excluded.reset_index(drop=True)
        pq.write_table(pa.Table.from_pandas(pd.concat([frame, excluded], ignore_index=True), preserve_index=False), path)
    status = dict(classification="QUARANTINED", quarantine=True, target_date_ready=False)
    snapshot["quarantine_symbols"] = {code: dict(reason="RAW_HISTORY_KEYS_MISSING", original_status=status)}
    snapshot["accepted_target_date_floor"] = 2
    qfq._json(qfq.input_path(kwargs["data_root"]), snapshot)
    result = qfq.run_daily_rebuild(**kwargs)
    manifest = json.loads(Path(result["quarantine_manifest"]["path"]).read_text())
    for role in kwargs["pointers"]:
        current = pq.read_table(result["candidates"][role]).to_pandas()
        assert code not in set(current.ts_code)
        quarantined = pq.read_table(manifest["artifacts"][role]["path"]).to_pandas()
        pd.testing.assert_frame_equal(quarantined.reset_index(drop=True), old_values[role])
        assert manifest["counts"][role]["old_key_conservation"] is True
    snapshot["quarantine_symbols"][code]["original_status"]["quarantine"] = False
    qfq._json(qfq.input_path(kwargs["data_root"]), snapshot)
    with pytest.raises(qfq.QfqGateError, match="OUTSIDE_ORIGINAL"):
        qfq.run_daily_rebuild(**kwargs)


def test_canary_uses_same_pure_transform_and_never_current(tmp_path, driver):
    import zipfile
    from ops import canary_research_panel_qfq as canary
    symbols, dates = {}, {}
    archive = tmp_path / "hsjday.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for code in ("002612.SZ", "001283.SZ"):
            raw = raw_frame(code)
            native = tmp_path / (code + ".day")
            write_day(native, raw)
            member = "sz\\lday\\sz" + code[:6] + ".day"
            z.writestr(member, native.read_bytes())
            factor = tmp_path / (code + ".csv")
            factor.write_text("ex_div_date,forward_adj_factorA,forward_adj_factorB,backward_adj_factorA\n2025-06-01,1,-1,1\n")
            symbols[code] = dict(archive=dict(path=str(archive), member=member, member_sha256=qfq.sha(native)),
                                 live=dict(path=str(native), sha256=qfq.sha(native)), factor_csv=dict(path=str(factor), sha256=qfq.sha(factor)))
            dates[code] = raw.trade_date.iloc[-2:].astype(int).tolist()
    for item in symbols.values():
        item["archive"]["sha256"] = qfq.sha(archive)
    binding = tmp_path / "binding.json"
    binding.write_text(json.dumps(dict(schema="original_daily_qfq_two_symbol_canary_v1", overlap_policy="ARCHIVE_AUTHORITATIVE_CURRENT_POSTFIX_V1",
                                     asof_date=dates["002612.SZ"][-1], symbols=symbols, verification_dates=dates)))
    result = canary.run(binding, tmp_path / "output")
    assert result["status"] == "CANARY_COMPUTED_NOT_ACCEPTED"
    assert not list(tmp_path.rglob("CURRENT*"))
    assert all(len(item["samples"]) == 2 for item in result["symbols"].values())


def test_raw_boundary_error_is_only_isolated_for_original_quarantine(tmp_path, driver):
    root = tmp_path / "tdx"
    path = root / "vipdoc/sz/lday/sz000004.day"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"invalid trailing bytes")
    binding = tmp_path / "absent_binding.json"
    with pytest.raises(qfq.QfqGateError, match="RECORD_BOUNDARY_INVALID"):
        inputs.raw_bindings(root, driver, binding, target=20261023)
    result = inputs.raw_bindings(root, driver, binding, target=20261023,
                                 quarantine_eligible={"000004.SZ": dict(quarantine=True)})
    assert "RECORD_BOUNDARY_INVALID" in result["000004.SZ"]["raw_binding_error"]


def test_explicit_native_archive_prefix_wins_without_using_old_panel_prices(tmp_path, driver):
    import zipfile
    raw = raw_frame()
    native = tmp_path / "native.day"
    write_day(native, raw.iloc[:200])
    archive = tmp_path / "hsjday.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("sz\\lday\\sz002612.day", native.read_bytes())
    root = tmp_path / "tdx"
    current = raw.copy()
    current.loc[:199, "vol"] = 100  # simulated legacy rounded/conflicting overlap
    write_day(root / "vipdoc/sz/lday/sz002612.day", current)
    binding = tmp_path / "raw_binding.json"
    binding.write_text(json.dumps(dict(overlap_policy="ARCHIVE_AUTHORITATIVE_CURRENT_POSTFIX_V1",
                                      archive=dict(path=str(archive), sha256=qfq.sha(archive)))))
    item = inputs.raw_bindings(root, driver, binding, target=int(raw.trade_date.iloc[-1]))["002612.SZ"]
    assert item["raw_files"][-1]["from_date_exclusive"] == int(raw.trade_date.iloc[199])
    output = qfq.rebuild_symbol("002612.SZ", {**item, "events": []}, int(raw.trade_date.iloc[-1]), driver)
    assert len(output) == len(raw)
    np.testing.assert_allclose(output.volume, raw.volume)


def test_r3_shared_hk_rows_are_retained_and_do_not_enter_a_coverage_or_floor(tmp_path, driver):
    kwargs, snapshot, _ = fixture_panel(tmp_path, driver)
    originals = {}
    for role, pointer in kwargs["pointers"].items():
        path = Path(pointer.read_text())
        table = pq.read_table(path)
        extra = table.slice(0, 3)
        extra = extra.set_column(extra.schema.get_field_index("ts_code"), "ts_code", pa.array(["00700.HK", "00700.HK_CONNECT", "02800.HK_FUND"], type=table.schema.field("ts_code").type))
        # A valid NaN must remain a valid NaN, distinct from a null.
        extra = extra.set_column(extra.schema.get_field_index("close"), "close", pa.array([float("nan"), None, 123.456], type=pa.float64()))
        originals[role] = extra
        pq.write_table(pa.concat_tables([table, extra]), path)
    assert all(qfq.CODE.fullmatch(c) for c in qfq.required_a_history(kwargs["pointers"]))
    snapshot["accepted_target_date_floor"] = 2
    qfq._json(qfq.input_path(kwargs["data_root"]), snapshot)
    result = qfq.run_daily_rebuild(**kwargs)
    for role, path in result["candidates"].items():
        current = pq.read_table(path)
        retained = current.filter(pa.array([not bool(qfq.CODE.fullmatch(c)) for c in current['ts_code'].to_pylist()]))
        # Bucket order may change; every original cell/null/NaN is retained.
        for code in originals[role]['ts_code'].to_pylist():
            actual = retained.filter(pa.array([c == code for c in retained['ts_code'].to_pylist()]))
            original = originals[role].filter(pa.array([c == code for c in originals[role]['ts_code'].to_pylist()]))
            for name in original.column_names:
                assert actual[name].null_count == original[name].null_count
                for a, b in zip(actual[name].to_pylist(), original[name].to_pylist()):
                    assert a == b or (isinstance(a, float) and isinstance(b, float) and np.isnan(a) and np.isnan(b))
        meta = qfq.panel_contract(Path(path))
        assert meta['price_basis'] == 'MIXED_BY_MARKET'
        assert meta['market_basis']['HK']['price_basis'] == 'UNKNOWN_NATIVE'
        counts = result['counts'][role]
        assert counts['retained_non_a_old_rows'] == 3
        assert counts['target_date_symbols'] == 2
        assert counts['original_old_rows'] == counts['replaced_old_rows'] + counts['retained_non_a_old_rows'] + counts['quarantined_old_rows']


def test_r3_exact_non_target_legacy_preservation_is_bound_to_old_keys(tmp_path, driver, monkeypatch):
    kwargs, snapshot, _ = fixture_panel(tmp_path, driver)
    code = '430017.BJ'
    summary = tmp_path / 'original_summary.json'
    qfq._json(summary, dict(target_keys=[dict(symbol='002612', market=0)], symbol_reconciliation=[]))
    policy = dict(schema='qfq_exact_legacy_preservation_v1', codes=[code], reason='RAW_MISSING_LEGACY_IDENTITY_UNKNOWN',
                  original_sync_summary=dict(path=str(summary), sha256=qfq.sha(summary)), original_membership_codes=['002612.SZ'],
                  original_membership_sha256=qfq.canonical_sha(['002612.SZ']), roles={})
    original_values = {}
    for role, pointer in kwargs['pointers'].items():
        path = Path(pointer.read_text()); table = pq.read_table(path)
        legacy = table.slice(0, 2).set_column(table.schema.get_field_index('ts_code'), 'ts_code', pa.array([code,code], type=table.schema.field('ts_code').type))
        pq.write_table(pa.concat_tables([table,legacy]), path)
        dates = sorted(map(int, legacy['trade_date'].to_pylist()))
        policy['roles'][role] = dict(original_sha256=qfq.sha(path), keys={code:dict(rows=2,date_sha256=qfq.canonical_sha(dates))})
        original_values[role] = legacy
    p = tmp_path / 'exact_policy.json'; qfq._json(p,policy)
    monkeypatch.setattr(qfq,'EXACT_LEGACY_POLICY_SHA', qfq.sha(p))
    snapshot['legacy_preservation_policy'] = dict(path=str(p),sha256=qfq.sha(p))
    snapshot['legacy_preservation_codes'] = [code]
    snapshot['source_files'].append(snapshot['legacy_preservation_policy'])
    qfq._json(qfq.input_path(kwargs['data_root']),snapshot)
    result = qfq.run_daily_rebuild(**kwargs)
    manifest = json.loads(Path(result['quarantine_manifest']['path']).read_text())
    for role in kwargs['pointers']:
        legacy = pq.read_table(manifest['artifacts'][role]['path'])
        assert legacy.replace_schema_metadata(None).equals(original_values[role].replace_schema_metadata(None))
        assert code not in pq.read_table(result['candidates'][role],columns=['ts_code'])['ts_code'].to_pylist()
    # An altered row under the same code may not use the approved exception.
    pointer = kwargs['pointers']['backtest']; path = Path(pointer.read_text())
    table = pq.read_table(path); pq.write_table(pa.concat_tables([table,table.slice(len(table)-1)]),path)
    with pytest.raises(qfq.QfqGateError,match='LEGACY_PRESERVATION_KEYS_OR_BASELINE_CHANGED'):
        qfq.run_daily_rebuild(**kwargs)
    with pytest.raises(qfq.QfqGateError,match='NOT_APPROVED'):
        qfq.legacy_preservation(dict(path=str(p),sha256='0'*64))


def test_r3_prepare_defensively_excludes_foreign_required_history_before_raw_gate(tmp_path, driver, monkeypatch):
    tdx=tmp_path/'tdx'; data=tmp_path/'data'
    monkeypatch.setattr(inputs,'original_sync_contract',lambda *a:(dict(path=str(tmp_path/'sync.json'),sha256='fixture'),{},1))
    qfq._json(tmp_path/'sync.json',dict(target_keys=[],symbol_reconciliation=[]))
    captured={}
    def raw(*args,**kwargs):
        captured.update(kwargs['required_start'])
        return {'002612.SZ':dict(history_start_date=20200101)}
    monkeypatch.setattr(inputs,'raw_bindings',raw)
    def stop(*a,**k): raise RuntimeError('REACHED_METADATA_WITHOUT_FOREIGN_GAP')
    monkeypatch.setattr(inputs,'collect_metadata',stop)
    with pytest.raises(RuntimeError,match='REACHED_METADATA_WITHOUT_FOREIGN_GAP'):
        inputs.prepare_snapshot(tdx_root=tdx,data_root=data,target=20261023,driver=driver,
                                required_start={'002612.SZ':20210101,'00700.HK':19990101,'00700.HK_CONNECT':19990101})
    assert captured == {'002612.SZ':20210101}


def test_r3_missing_a_outside_exact_legacy_policy_still_blocks(tmp_path, driver):
    kwargs, _, _ = fixture_panel(tmp_path,driver)
    for pointer in kwargs['pointers'].values():
        path=Path(pointer.read_text()); table=pq.read_table(path)
        other=table.slice(0,1).set_column(table.schema.get_field_index('ts_code'),'ts_code',pa.array(['430999.BJ'],type=table.schema.field('ts_code').type))
        pq.write_table(pa.concat_tables([table,other]),path)
    with pytest.raises(qfq.QfqGateError,match='MARKETWIDE_ADJUSTMENT_COVERAGE_MISSING'):
        qfq.run_daily_rebuild(**kwargs)
