"""Bounded original-owner I/O regressions; never publish a live panel."""
import ast
import copy
import importlib.util
import json
import os
import numpy as np
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest
from pandas.testing import assert_frame_equal


ROOT = Path(__file__).resolve().parents[1]
BEFORE = ROOT / "docs/handoffs/daily_incremental_io_20261111/research_panel_qfq.before.py"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


q = load(ROOT / "ops/research_panel_qfq.py", "daily_io_candidate")
original = load(BEFORE, "daily_io_original")


def ref(path):
    return dict(path=str(path), sha256=q.sha(path))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True))
    return ref(path)


@pytest.mark.parametrize("row_group_size", [2, 100])
def test_readonly_buckets_match_original_spool_without_writes(tmp_path, row_group_size):
    table = pa.table({"ts_code": ["000001.SZ", "002152.SZ", "00005.HK", "920202.BJ"] * 3,
                      "trade_date": list(range(12)), "close": [None, 2., 3., 4.] * 3})
    path = tmp_path / "current.parquet"
    pq.write_table(table, path, row_group_size=row_group_size)
    old = original.spool_current(path, tmp_path / "oracle", q.sha(path))
    new = q.spool_current(path, tmp_path / "not_created", q.sha(path))
    assert not (tmp_path / "not_created").exists()
    assert set(old) == set(new)
    for bucket, view in new.items():
        expected = pq.read_table(old[bucket])
        assert expected.equals(view.read(), check_metadata=True)
        assert expected.select(["trade_date"]).equals(view.read(columns=["trade_date"]))
    # Both calls remain entirely read-only, including an idempotent retry.
    q.spool_current(path, tmp_path / "not_created", q.sha(path))
    assert not (tmp_path / "not_created").exists()


def test_current_bucket_refuses_source_change(tmp_path):
    path = tmp_path / "current.parquet"
    table = pa.table({"ts_code": ["000001.SZ"], "trade_date": [20261110]})
    pq.write_table(table, path)
    view = next(iter(q.spool_current(path, tmp_path / "no_copy", q.sha(path)).values()))
    pq.write_table(pa.concat_tables([table, table]), path)
    with pytest.raises(q.QfqGateError, match="CURRENT_BUCKET_SOURCE_CHANGED"):
        view.read()


def test_dictionary_null_and_nan_columns_keep_original_bucket_values(tmp_path):
    table = pa.table(dict(ts_code=["000001.SZ", "920202.BJ", "000001.SZ", "00005.HK"],
                          trade_date=[20261109, 20261109, 20261110, 20261110],
                          value=pa.array([None, float('nan'), 1., 2.], from_pandas=False)))
    table = table.set_column(0, 'ts_code', pc.dictionary_encode(table['ts_code']))
    path = tmp_path / 'dictionary.parquet'
    pq.write_table(table, path, row_group_size=2)
    old = original.spool_current(path, tmp_path / 'oracle', q.sha(path))
    new = q.spool_current(path, tmp_path / 'no_copy', q.sha(path))
    for bucket in old:
        left, right = pq.read_table(old[bucket]), new[bucket].read()
        assert left.schema.equals(right.schema, check_metadata=True)
        assert_frame_equal(left.to_pandas(), right.to_pandas(), check_exact=True)
        assert left['value'].is_null().equals(right['value'].is_null())
    assert not (tmp_path / 'no_copy').exists()


@pytest.fixture
def partial(tmp_path, monkeypatch):
    snapshot = dict(asof_date=20261111, symbols={"000001.SZ": {"events": []}, "002152.SZ": {"events": []}})
    old = dict(input_sha256=q.canonical_sha(snapshot), adapter_sha256=q.sha(BEFORE),
               driver_sha256=q.DRIVER_SHA, formula_sha256=q.FORMULA_SHA,
               turnover_input_sha256="same-turnover")
    identity = {**old, "adapter_sha256": q.sha(Path(q.__file__))}
    baseline = {"selector": "original-selector-sha", "backtest": "original-backtest-sha"}
    generation = q.canonical_sha(dict(target=20261111, baseline_panel_sha256=baseline, **old))
    run = tmp_path / ("qfq_" + generation[:20])
    snapshot_ref = save(run / "adjustment_input_snapshot.json", snapshot)
    path = run / "symbol_checkpoints/000001.SZ.parquet"
    path.parent.mkdir()
    fingerprint = q.canonical_sha(dict(code="000001.SZ", item=snapshot["symbols"]["000001.SZ"], **old))
    table = pa.table({"ts_code": ["000001.SZ"], "trade_date": [20261111], "close": [42.]})
    pq.write_table(table.replace_schema_metadata({q.META_KEY: json.dumps(dict(checkpoint_id=fingerprint)).encode()}), path)
    receipt_ref = save(path.with_suffix(".receipt.json"), dict(checkpoint_id=fingerprint, sha256=q.sha(path)))
    payload = dict(schema="qfq_original_checkpoint_recovery_v1", recovery_scope="D11_PARTIAL_IO_ONLY_V1",
                   asof_date=20261111, source_identity=old, source_core=ref(BEFORE), source_run=str(run),
                   original_snapshot=snapshot_ref, factor_cache_identity="factor-identity", baseline_panel_sha256=baseline,
                   chunks={"000001.SZ": dict(artifact=ref(path), receipt=receipt_ref)},
                   retry_original_quarantined=[], completed_count=1, total_count=2, **q.FLAGS)
    monkeypatch.setattr(q, "factor_cache_identity", lambda *a: "factor-identity")
    return SimpleNamespace(snapshot=snapshot, identity=identity, baseline=baseline, payload=payload,
                           reference=save(tmp_path / "recovery.json", payload), path=path, root=tmp_path)


def recover(p):
    return q.checkpoint_recovery(p.reference, p.snapshot, p.identity, p.baseline, p.root)


def test_partial_reuses_true_original_file_without_recompute_or_copy(partial, monkeypatch):
    restored = recover(partial)
    monkeypatch.setattr(q, "rebuild_symbol", lambda *a: pytest.fail("recomputed accepted original checkpoint"))
    destination = partial.root / "new-symbol-checkpoints"
    for _ in range(2):
        code, path = q._symbol_checkpoint("000001.SZ", partial.snapshot["symbols"]["000001.SZ"], 20261111,
                                          partial.identity, destination, restored, None)
        assert code == "000001.SZ" and path == partial.path
        assert q.panel_contract(path)["checkpoint_id"] != q.canonical_sha(
            dict(code=code, item=partial.snapshot["symbols"][code], **partial.identity))
    assert not destination.exists()


def test_partial_missing_stock_uses_original_computation(partial, monkeypatch):
    restored = recover(partial)
    calls = []
    def compute(code, *args):
        calls.append(code)
        return pd.DataFrame(dict(ts_code=[code], trade_date=[20261111], close=[7.]))
    monkeypatch.setattr(q, "rebuild_symbol", compute)
    destination = partial.root / "new-symbol-checkpoints"
    destination.mkdir()
    for _ in range(2):
        q._symbol_checkpoint("002152.SZ", partial.snapshot["symbols"]["002152.SZ"], 20261111,
                             partial.identity, destination, restored, None)
    assert calls == ["002152.SZ"]
    assert pq.read_table(destination / "002152.SZ.parquet")["close"].to_pylist() == [7.]


def test_process_worker_preserves_readonly_checkpoint_result(partial, monkeypatch):
    restored = recover(partial)
    monkeypatch.setattr(q, "rebuild_symbol", lambda *a: pytest.fail("worker recomputed original checkpoint"))
    code, path, error = q._symbol_process_task(("000001.SZ", partial.snapshot["symbols"]["000001.SZ"],
        20261111, partial.identity, str(partial.root / "no_worker_copy"), restored))
    assert code == "000001.SZ" and path == str(partial.path) and error is None
    assert not (partial.root / "no_worker_copy").exists()


@pytest.mark.parametrize("change", ["date", "schema", "scope", "input", "turnover", "driver", "formula",
                                  "baseline", "factor", "source_sha", "artifact_sha", "receipt", "path", "count"])
def test_partial_recovery_rejects_drift(partial, change):
    p = partial.payload
    if change == "date": p["asof_date"] = 20261112
    if change == "schema": p["schema"] = "unknown"
    if change == "scope": p["recovery_scope"] = "unknown"
    if change in {"input", "turnover", "driver", "formula"}:
        key = {"input": "input_sha256", "turnover": "turnover_input_sha256", "driver": "driver_sha256", "formula": "formula_sha256"}[change]
        p["source_identity"][key] = "changed"
    if change == "baseline": p["baseline_panel_sha256"]["selector"] = "changed"
    if change == "factor": p["factor_cache_identity"] = "changed"
    if change == "source_sha": p["source_core"]["sha256"] = "0" * 64
    if change == "artifact_sha": p["chunks"]["000001.SZ"]["artifact"]["sha256"] = "0" * 64
    if change == "receipt":
        entry = p["chunks"]["000001.SZ"]
        entry["receipt"] = save(partial.path.with_suffix(".receipt.json"), dict(checkpoint_id="wrong", sha256=q.sha(partial.path)))
    if change == "path":
        alternate = partial.root / "elsewhere.parquet"
        alternate.write_bytes(partial.path.read_bytes())
        p["chunks"]["000001.SZ"]["artifact"] = ref(alternate)
    if change == "count": p["completed_count"] = 2
    partial.reference = save(partial.root / "recovery.json", p)
    with pytest.raises((q.QfqGateError, ValueError)):
        recover(partial)


@pytest.mark.parametrize("kind", ["artifact", "receipt"])
def test_partial_rejects_change_after_initial_verification(partial, kind):
    restored = recover(partial)
    path = partial.path if kind == "artifact" else partial.path.with_suffix(".receipt.json")
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(q.QfqGateError, match="CHANGED_AFTER_VERIFICATION"):
        q._partial_checkpoint_file(restored["000001.SZ"])


def test_mathematical_and_release_gate_sources_unchanged():
    assert q.computation_kernel_sha(BEFORE) == q.computation_kernel_sha(Path(q.__file__))
    assert q._partial_checkpoint_io_math_sha(BEFORE) == q._partial_checkpoint_io_math_sha(Path(q.__file__))


@pytest.mark.skipif(not os.environ.get("V4_TEST_ORIGINAL_APP"), reason="requires explicitly pinned original runtime")
def test_pinned_full_prefix_oracle_unchanged_on_small_boundaries(monkeypatch):
    app = Path(os.environ["V4_TEST_ORIGINAL_APP"])
    formula = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/workbench-daily-chain-20261031-r6-main/app/components/a_formula/build_canonical_formula_research_panel.py')
    driver, _ = original.authorities(app / "ops/vendor/data_layer_daily_formula_increment_update_v1.py", formula)
    dates = pd.bdate_range(end="2026-11-11", periods=90)
    revisions = {"002152.SZ": .1, "002275.SZ": .15, "002864.SZ": .0499, "300741.SZ": .05,
                 "301300.SZ": .198, "301529.SZ": .19853, "603279.SH": .5, "605338.SH": .2}
    for code in ["000001.SZ", "002717.SZ", *revisions, "688053.SH"]:
        chosen = dates[:-1] if code == "002717.SZ" else dates
        values = 10 + np.arange(len(chosen)) * .01 + np.sin(np.arange(len(chosen)))
        raw = pd.DataFrame(dict(ts_code=code, trade_date=[int(d.strftime('%Y%m%d')) for d in chosen],
            open=values, high=values + .2, low=values - .2, close=values + .05,
            amount=np.full(len(chosen), 1000000.), vol=np.full(len(chosen), 100000.), volume=np.full(len(chosen), 100000.)))
        item = dict(history_start_date=int(raw.trade_date.min()), events=[])
        if code in revisions:
            item['events'] = [dict(ex_date=20261111, a=1., b=-revisions[code], volume_a=1.)]
        monkeypatch.setattr(original, "resolved_raw_history", lambda *a, frame=raw: frame.copy())
        monkeypatch.setattr(q, "resolved_raw_history", lambda *a, frame=raw: frame.copy())
        expected = original.rebuild_symbol(code, item, 20261111, driver)
        actual = q.rebuild_symbol(code, item, 20261111, driver)
        assert_frame_equal(expected, actual, check_exact=True)


@pytest.mark.skipif(not os.environ.get("V4_TEST_D11_CHECKPOINTS"), reason="explicit real three-checkpoint read-only canary")
def test_three_real_d11_checkpoints_remain_readonly_and_exact(tmp_path):
    from ops import research_panel_qfq as deployed
    from ops.research_panel_turnover import load_daily
    app = Path(os.environ["V4_TEST_ORIGINAL_APP"])
    base = Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state')
    data = base / 'workspace/数据'
    run = base / 'research_panel_daily/a_formula_runs/qfq_5b6da037da39fae667c1'
    snapshot_path = run / 'adjustment_input_snapshot.json'
    snapshot = json.loads(snapshot_path.read_text())
    assert snapshot == json.loads(q.input_path(data).read_text())
    formula = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/workbench-daily-chain-20261031-r6-main/app/components/a_formula/build_canonical_formula_research_panel.py')
    contract = Path('/Users/lexi/Library/Application Support/com.lexi.research-panel.local/releases/20260821T073000Z-v35-hk0920-materialization-bridge/app/runtime/v1/authoritative_field_contract_v0.csv')
    old = deployed.generation_identity(snapshot, app / 'ops/vendor/data_layer_daily_formula_increment_update_v1.py', formula, contract)
    turnover = load_daily(data, base / 'research_panel_daily/tdx', 20261111)
    assert turnover.failure is None
    old['turnover_input_sha256'] = turnover.identity
    identity = {**old, 'adapter_sha256': q.sha(Path(q.__file__))}
    receipt = json.loads((base / 'research_panel_daily/a_formula_runs/qfq_231df8b469ade0ba8e62/candidate_receipt.json').read_text())
    chunks = {}
    for code in ['000001.SZ', '002164.SZ', '002906.SZ']:
        path = run / 'symbol_checkpoints' / (code + '.parquet')
        chunks[code] = dict(artifact=ref(path), receipt=ref(path.with_suffix('.receipt.json')))
    payload = dict(schema='qfq_original_checkpoint_recovery_v1', recovery_scope='D11_PARTIAL_IO_ONLY_V1',
        asof_date=20261111, source_identity=old, source_core=ref(app / 'ops/research_panel_qfq.py'),
        source_run=str(run), original_snapshot=ref(snapshot_path), factor_cache_identity=q.factor_cache_identity(data, 20261111, snapshot),
        baseline_panel_sha256=receipt['candidate_sha256'], chunks=chunks, retry_original_quarantined=[],
        completed_count=3, total_count=len(snapshot['symbols']), **q.FLAGS)
    restored = q.checkpoint_recovery(save(tmp_path / 'three_sample_only.json', payload), snapshot, identity,
                                     receipt['candidate_sha256'], data)
    for code, item in restored.items():
        result = q._symbol_checkpoint(code, snapshot['symbols'][code], 20261111, identity,
                                      tmp_path / 'no_new_numerical_files', restored, None)
        assert result == (code, Path(item['artifact']['path']))
    assert not (tmp_path / 'no_new_numerical_files').exists()


@pytest.mark.parametrize("checkpoint_ref", [None, {"path": "/explicit/recovery.json", "sha256": "a" * 64}])
def test_authority_only_forwards_explicit_recovery(tmp_path, monkeypatch, checkpoint_ref):
    authority = load(ROOT / "ops/macos_research_panel_daily_authority.py", "ops.daily_io_authority")
    from ops import research_storage_retention as retention
    captured = {}
    def run(rebuild, **kwargs):
        captured.update(kwargs)
        return dict(selector=str(tmp_path / "selector.parquet"), backtest=str(tmp_path / "backtest.parquet"),
                    authority={}, counts={"selector": {"target_date_symbols": 3}})
    monkeypatch.setattr(retention, "run_with_retention", run)
    monkeypatch.setattr(authority, "_ensure_pointer_seed", lambda *a: None)
    monkeypatch.setattr(authority, "_formula_artifact_binding", lambda *a: {})
    authority.run_windows_a_formula_authority(tmp_path / "legacy.py", tdx_root=tmp_path, data_root=tmp_path,
        selector_pointer=tmp_path / "selector.txt", backtest_pointer=tmp_path / "backtest.txt",
        selector_seed=None, backtest_seed=None, contract_csv=tmp_path / "contract.csv",
        canonical_formula_path=tmp_path / "formula.py", return_root=tmp_path, target_date="20261111",
        formula_max_workers=4, **({"checkpoint_resume": checkpoint_ref} if checkpoint_ref is not None else {}))
    assert captured["refresh_inputs"] is True and captured["publish"] is True
    assert captured["workers"] == 4
    if checkpoint_ref is None:
        assert "checkpoint_resume" not in captured
    else:
        assert captured["checkpoint_resume"] == checkpoint_ref


def owner_assembly(module, scope):
    function = next(node for node in ast.parse(Path(module.__file__).read_text()).body
                    if isinstance(node, ast.FunctionDef) and node.name == "run_daily_rebuild")
    block = next(node for node in ast.walk(function) if isinstance(node, ast.Try) and any(
        isinstance(item, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "old_spools" for t in item.targets)
        for item in node.body))
    start = next(i for i, item in enumerate(block.body) if isinstance(item, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "old_spools" for t in item.targets))
    end = next(i for i in range(start + 1, len(block.body)) if isinstance(block.body[i], ast.If)
               and isinstance(block.body[i].test, ast.Name) and block.body[i].test.id == "delta")
    stub = ast.parse("def original_owner_assembly():\n    pass\n").body[0]
    stub.args.args = [ast.arg(arg=name) for name in scope]
    stub.body = block.body[start:end] + [ast.Return(value=ast.Name(id="role_counts", ctx=ast.Load()))]
    namespace = {**module.__dict__, **scope}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[stub], type_ignores=[])), str(module.__file__), "exec"), namespace)
    return namespace["original_owner_assembly"](**scope)


def test_actual_owner_pair_assembly_matches_original_without_old_bucket_outputs(tmp_path, monkeypatch):
    # Mixed original market history plus new-day, no-bar, eight adjusted histories
    # and newly admitted history. Exact owner assembly is extracted from each file.
    adjusted = ["002152.SZ", "002275.SZ", "002864.SZ", "300741.SZ", "301300.SZ", "301529.SZ", "603279.SH", "605338.SH"]
    codes = ["000001.SZ", "002717.SZ", *adjusted, "688053.SH"]
    schema = pa.schema([("ts_code", pa.string()), ("trade_date", pa.int64()), ("close", pa.float64()),
                        ("signal", pa.int8()), ("name", pa.string())])
    def rows(code, dates, adjustment=0.):
        return [dict(ts_code=code, trade_date=day, close=10. + index - adjustment,
                     signal=index % 2, name=None) for index, day in enumerate(dates)]
    old_rows = [r for code in codes[:-1] for r in rows(code, [20261109, 20261110])]
    old_rows += rows("00005.HK", [20261110])
    old = pa.Table.from_pylist(old_rows, schema=schema)
    currents = {}
    for role in ("selector", "backtest"):
        currents[role] = tmp_path / (role + ".parquet")
        pq.write_table(old, currents[role], row_group_size=7)
    driver = SimpleNamespace(CONTRACT_PROVENANCE_FIELD_DEFAULTS={"field_contract_version": "unchanged"},
        validate_new_selector_rows=lambda *a: {"status": "PASS"},
        build_table_for_schema=lambda frame, schema, role: (pa.Table.from_pandas(frame[schema.names], schema=schema, preserve_index=False), []))
    common = dict(currents=currents, baseline_hashes={r: q.sha(p) for r, p in currents.items()},
        legacy_codes=set(), legacy_policy=None, quarantine_reasons={}, foreign={"00005.HK"},
        retained_history_codes=set(), unchanged_codes=set(), codes=codes, old_symbols={r: set(old["ts_code"].to_pylist()) for r in currents},
        snapshot={"symbols": {c: {"publish_roles": list(currents)} for c in codes}}, target=20261111,
        history=None, addition=None, delta=None, same_asof=None, incremental=None, retained_history=None,
        eligible={}, schemas={r: schema for r in currents}, role_start={r: 20261109 for r in currents},
        driver=driver, turnover=SimpleNamespace(apply_target=lambda code, frame: frame), run_id="same-output-contract",
        meta={"generation_id": "same-output-contract"})
    outputs = []
    counts = []
    writes = {}
    for module, label in [(original, "oracle"), (q, "candidate")]:
        run = tmp_path / label
        parts = run / "symbol_checkpoints"
        parts.mkdir(parents=True)
        paths = {}
        for code in codes:
            dates = [20261109, 20261110] if code == "002717.SZ" else [20261109, 20261110, 20261111]
            paths[code] = parts / (code + ".parquet")
            pq.write_table(pa.Table.from_pylist(rows(code, dates, .1 if code in adjusted else 0.), schema=schema), paths[code])
        if module is q:
            # The new assembler must also consume a verified original path;
            # there is deliberately no duplicate under the new parts directory.
            paths["000001.SZ"] = tmp_path / "oracle/symbol_checkpoints/000001.SZ.parquet"
            (parts / "000001.SZ.parquet").unlink()
        candidates = {r: run / (r + ".parquet") for r in currents}
        entries = []
        class CountingWriter:
            def __init__(self, path, *args, **kwargs):
                self.inner = pq.ParquetWriter(path, *args, **kwargs)
                self.record = dict(path=str(path), rows=0, arrow_bytes=0)
                entries.append(self.record)
            def __enter__(self): return self
            def __exit__(self, *args): return self.inner.__exit__(*args)
            def __getattr__(self, name): return getattr(self.inner, name)
            def write_table(self, table, *args, **kwargs):
                self.record['rows'] += len(table)
                self.record['arrow_bytes'] += table.nbytes
                return self.inner.write_table(table, *args, **kwargs)
        class CountingParquet:
            ParquetWriter = CountingWriter
            def __getattr__(self, name): return getattr(pq, name)
        monkeypatch.setattr(module, 'pq', CountingParquet())
        counts.append(owner_assembly(module, {**common, "run_dir": run, "parts_root": parts,
            "checkpoint_files": paths, "recovered": {}, "candidates": candidates}))
        writes[label] = entries
        outputs.append(candidates)
    assert counts[0] == counts[1]
    for role in currents:
        left, right = (pq.read_table(out[role]) for out in outputs)
        assert left.schema.equals(right.schema, check_metadata=True)
        assert_frame_equal(left.to_pandas(), right.to_pandas(), check_exact=True)
        assert not (tmp_path / "candidate" / ("current_" + role + "_buckets")).exists()
    assert sum(r['rows'] for r in writes['oracle']) - sum(r['rows'] for r in writes['candidate']) == 2 * len(old)
    assert all('_buckets/' not in r['path'] for r in writes['candidate'])
    save(tmp_path / 'WRITE_COUNTS.json', dict(scope='small owner-assembly fixture only, not production byte savings',
        original_rows_written=sum(r['rows'] for r in writes['oracle']),
        candidate_rows_written=sum(r['rows'] for r in writes['candidate']),
        avoided_old_copy_rows=2 * len(old), original_writer_count=len(writes['oracle']),
        candidate_writer_count=len(writes['candidate']), candidate_bucket_writer_count=0,
        outputs_identical_values_schema_footer_counts=True))
