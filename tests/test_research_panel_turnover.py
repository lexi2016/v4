import numpy as np
import pandas as pd
import pytest

from ops.research_panel_turnover import CapitalIndex, DailyTurnover, calculate


def row(date, category, before=100, after=100, total=200, *, code="000001", market=0):
    return dict(market=market, code=code, datetime=date, category=category,
                hongli_panqianliutong=float(before), peigujia_qianzongguben=0.0,
                songgu_qianzongguben=float(after), peigu_houzongguben=float(total))


def index(rows, end=20261028):
    return CapitalIndex.from_frame(pd.DataFrame(rows), end)


def test_dated_snapshot_and_native_shares_not_adjusted_volume():
    cap = index([row(20260102, 5, after=100, total=200),
                 row(20260301, 1, before=5, after=0, total=0),  # cash dividend
                 row(20260501, 5, before=100, after=200, total=300)])
    out = calculate("000001.SZ", [20260101, 20260102, 20260430, 20260501, 20261029],
                    [10000, 10000, 10000, 10000, 10000], cap)
    assert out.turnover_rate_pct.tolist()[1:4] == [1.0, 1.0, 0.5]
    assert np.isnan(out.turnover_rate_pct.iloc[0])
    assert out.turnover_status.iloc[0] == "NO_PRIOR_CAPITAL_SNAPSHOT"
    assert out.turnover_status.iloc[4] == "GBBQ_CAPTURE_DATE_UNCOVERED"


def test_conflicts_and_unsupported_events_are_unknown_until_a_resolving_snapshot():
    cap = index([row(20260101, 5, after=100), row(20260201, 5, before=120, after=140),
                 row(20260301, 11, before=0, after=2, total=0),
                 row(20260401, 5, before=140, after=150),
                 row(20260501, 5, before=150, after=160),
                 row(20260501, 5, before=150, after=170)])
    dates = [20260101, 20260102, 20260201, 20260301, 20260401, 20260501, 20261028]
    out = calculate("000001.SZ", dates, [10000] * len(dates), cap)
    assert list(out.turnover_status) == ["GBBQ_DATED_SNAPSHOT", "CAPITAL_CONTINUITY_CONFLICT",
        "GBBQ_DATED_SNAPSHOT", "UNRESOLVED_CAPITAL_EVENT", "GBBQ_DATED_SNAPSHOT",
        "SAME_DAY_CAPITAL_CONFLICT", "SAME_DAY_CAPITAL_CONFLICT"]
    assert out.turnover_rate_pct.isna().tolist() == [False, True, False, True, False, True, True]


def test_stock_distribution_barrier_invalid_capital_and_unknown_market_collision():
    cap = index([row(20260101, 5), row(20260201, 1, after=2, total=0),
                 row(20260301, 5, before=100, after=0),
                 row(20260101, 5, code="000002"), row(20260201, 5, code="000002", market=99)])
    out = calculate("000001.SZ", [20260101, 20260201, 20260301], [0, 0, 0], cap)
    assert out.turnover_rate_pct.iloc[0] == 0  # observed zero, not an imputed missing value
    assert list(out.turnover_status[1:]) == ["STOCK_DISTRIBUTION_WITHOUT_RESOLVED_SNAPSHOT", "INVALID_CAPITAL_SNAPSHOT"]
    assert calculate("000002.SZ", [20260301], [10000], cap).turnover_status.iloc[0] == "GBBQ_UNKNOWN_MARKET_CODE_COLLISION"


def test_daily_target_keeps_old_fields_and_uses_bound_g4_shares():
    cap = index([row(20260101, 5, after=200, total=400)])
    daily = DailyTurnover(20261028, cap, {(0, "000001"): 1234567}, {})
    frame = pd.DataFrame(dict(trade_date=[20261027, 20261028], turnover_rate_pct=[3.0, np.nan],
                              float_share_10k=[999.0, np.nan], volume=[999999.0, 999999.0]))
    out = daily.apply_target("000001.SZ", frame)
    assert out.turnover_rate_pct.iloc[0] == 3.0
    assert out.turnover_rate_pct.iloc[1] == pytest.approx(1234567 / 2000000 * 100)
    assert out.float_share_10k.iloc[1] == 200
    assert out.turnover_rate_denominator_10k.iloc[1] == 200
    assert out.turnover_rate_volume_source.iloc[1] == "TDX_OFFICIAL_G4DAY_NATIVE_SHARES"
    assert np.isnan(frame.turnover_rate_pct.iloc[1])
    backtest = daily.apply_target("000001.SZ", frame.drop(columns=["turnover_rate_pct", "float_share_10k"]))
    assert backtest.turnover_rate_pct.iloc[1] == pytest.approx(1234567 / 2000000 * 100)
    assert backtest.float_share_10k.iloc[1] == 200


def test_daily_unpriced_and_missing_inputs_stay_null_and_preserve_non_null():
    cap = index([row(20260101, 5)])
    frame = pd.DataFrame(dict(trade_date=[20261028], turnover_rate_pct=[np.nan], float_share_10k=[np.nan]))
    out = DailyTurnover(20261028, cap, {}, {}).apply_target("000001.SZ", frame)
    assert pd.isna(out.turnover_rate_pct.iloc[0])
    assert out.turnover_rate_status.iloc[0] == "G4_UNPRICED_OR_MISSING"
    out = DailyTurnover(20261028, None, {}, {}, "DAILY_SYNC_RECEIPT_MISSING").apply_target("000001.SZ", frame)
    assert pd.isna(out.turnover_rate_pct.iloc[0])
    assert out.turnover_rate_status.iloc[0] == "DAILY_SYNC_RECEIPT_MISSING"
    frame.loc[0, "turnover_rate_pct"] = 7.5
    assert DailyTurnover(20261028, cap, {(0, "000001"): 10000}, {}).apply_target("000001.SZ", frame).turnover_rate_pct.iloc[0] == 7.5


def test_invalid_native_volume_never_becomes_zero():
    cap = index([row(20260101, 5)])
    out = calculate("000001.SZ", [20261028, 20261028], [np.nan, -1], cap)
    assert out.turnover_rate_pct.isna().all()
    assert set(out.turnover_status) == {"NATIVE_SHARE_VOLUME_MISSING"}


def test_qfq_assembly_preserves_history_and_new_nulls_with_daily_overlay():
    import pyarrow as pa
    from ops import research_panel_qfq as qfq

    class Driver:
        CONTRACT_PROVENANCE_FIELD_DEFAULTS = {"field_contract_version": "bound"}

        @staticmethod
        def build_table_for_schema(frame, schema, role):
            # The existing driver can fill numeric nulls with zero. The QFQ
            # adapter must restore nulls in the classified context fields.
            arrays = []
            for field in schema:
                values = frame[field.name] if field.name in frame else pd.Series([None] * len(frame))
                if pa.types.is_floating(field.type):
                    values = pd.to_numeric(values, errors="coerce").fillna(0)
                arrays.append(pa.Array.from_pandas(values, type=field.type))
            return pa.Table.from_arrays(arrays, schema=schema), {}

    old = pd.DataFrame(dict(ts_code=["000001.SZ"], trade_date=[20261027],
                            turnover_rate_pct=[3.0], float_share_10k=[999.0]))
    rebuilt = pd.DataFrame(dict(ts_code=["000001.SZ", "000001.SZ"],
                                trade_date=[20261027, 20261028]))
    merged = qfq.merge_rebuilt(old, rebuilt, role="backtest", driver=Driver(), history_extension=True)
    schema = pa.schema([("ts_code", pa.string()), ("trade_date", pa.int32()),
        ("turnover_rate_pct", pa.float64()), ("float_share_10k", pa.float64()),
        ("turnover_rate_status", pa.string()), ("turnover_rate_volume_source", pa.string()),
        ("turnover_rate_denominator_10k", pa.float64())])
    missing = DailyTurnover(20261028, index([row(20260101, 5)]), {}, {}).apply_target("000001.SZ", merged)
    table = qfq._table(missing, schema, Driver(), "backtest", history_extension=True)
    assert table["turnover_rate_pct"].to_pylist() == [3.0, None]
    assert table["float_share_10k"].to_pylist() == [999.0, None]
    assert table["turnover_rate_status"].to_pylist() == [None, "G4_UNPRICED_OR_MISSING"]
    filled = DailyTurnover(20261028, index([row(20260101, 5)]), {(0, "000001"): 12345}, {}).apply_target("000001.SZ", merged)
    table = qfq._table(filled, schema, Driver(), "backtest", history_extension=True)
    assert table["turnover_rate_pct"].to_pylist() == pytest.approx([3.0, 1.2345])
    assert table["turnover_rate_denominator_10k"].to_pylist() == [None, 100.0]


def test_daily_readiness_watch_detects_missing_input_arrival(tmp_path):
    from types import SimpleNamespace
    from ops import research_panel_qfq as qfq
    tdx = tmp_path / "state" / "tdx"
    watch = qfq.turnover_source_watch(tmp_path / "data", tdx, 20261028, SimpleNamespace(binding={}))
    assert qfq.turnover_watch_unchanged(watch)
    summary = tdx.parent / "receipts/a_sync_authority/20261028/summary.json"
    summary.parent.mkdir(parents=True)
    summary.write_text("{}")
    assert not qfq.turnover_watch_unchanged(watch)


def test_original_owner_imports_bound_overlay_only_into_existing_null_keys(tmp_path, monkeypatch):
    import json
    import pyarrow as pa
    import pyarrow.parquet as pq
    from ops import research_panel_qfq as qfq
    from ops.research_panel_turnover import HistoricalOverlay, POLICY

    def ref(path):
        return dict(path=str(path), sha256=qfq.sha(path))

    def patch(code, date, rate, shares, denominator, status, source, event=20260101):
        return dict(ts_code=code, trade_date=date, turnover_rate_pct=rate,
            turnover_float_share_10k=denominator, native_volume_shares=shares,
            volume_source=source, capital_event_date=event, turnover_status=status)

    history_source = "TDX_VIPDOC_ARCHIVE_FIRST_NATIVE_DAY_AS_RECORDED"
    daily_source = "TDX_OFFICIAL_G4DAY_NATIVE_SHARES"
    hist = [patch("000001.SZ", 20261026, 1.0, 10000, 100, "GBBQ_DATED_SNAPSHOT", history_source),
            patch("000001.SZ", 20261027, 2.0, 20000, 100, "GBBQ_DATED_SNAPSHOT", history_source),
            patch("000001.SZ", 20261025, 4.0, 40000, 100, "GBBQ_DATED_SNAPSHOT", history_source),
            patch("000002.SZ", 20261027, None, None, None, "RAW_HISTORY_UNAVAILABLE", None)]
    repair = [patch("000002.SZ", 20261027, 3.0, 30000, 100, "GBBQ_DATED_SNAPSHOT", history_source)]
    daily = [patch("000001.SZ", 20261028, 5.0, 50000, 100, "GBBQ_DATED_SNAPSHOT", daily_source),
             patch("000002.SZ", 20261028, None, None, 100, "G4_UNPRICED_OR_MISSING", None)]
    for name, rows in (("history", hist), ("repair", repair), ("daily", daily)):
        pq.write_table(pa.Table.from_pylist(rows), tmp_path / (name + ".parquet"))
    for name in ("kernel", "projection_runner", "repair_runner"):
        (tmp_path / name).write_text(name)

    frame = pd.DataFrame(dict(ts_code=["000001.SZ"] * 5 + ["000002.SZ"] * 2 + ["00700.HK", "000001.SZ"],
        trade_date=[20261026, 20261027, 20261028, 20261029, 20261030, 20261027, 20261028, 20261028, 20261024],
        market_type=["A"] * 7 + ["HK", "A"],
        turnover_rate_pct=[None, 9.0, None, None, None, None, None, None, 7.0],
        float_share_10k=[None, 999.0, None, None, None, None, None, None, 77.0],
        close=[10.1, 10.2, 10.3, 10.4, 10.5, 11.1, 11.2, 100.0, 10.0]))
    metadata = dict(schema="a_share_qfq_panel_v1", generation_id="current-generation", asof_date=20261030,
                    generation_manifest_path=str(tmp_path / "baseline_generation_receipt.json"),
                    RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
    panels = {}
    for role in ("selector", "backtest"):
        path = tmp_path / (role + ".parquet")
        source_frame = frame if role == "selector" else frame.drop(columns=["turnover_rate_pct", "float_share_10k"])
        table = pa.Table.from_pandas(source_frame, preserve_index=False).replace_schema_metadata({qfq.META_KEY: json.dumps(metadata).encode()})
        pq.write_table(table, path, row_group_size=3)
        panels[role] = path
    projection_metadata = dict(schema="a_share_qfq_panel_v1", generation_id="projection-generation", asof_date=20261028,
        RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
    projection_panels = {}
    for role in ("selector", "backtest"):
        path = tmp_path / ("projection_" + role + ".parquet")
        table = pa.Table.from_pandas(frame.iloc[:1], preserve_index=False).replace_schema_metadata(
            {qfq.META_KEY: json.dumps(projection_metadata).encode()})
        pq.write_table(table, path)
        projection_panels[role] = path
    identity = dict(generation="projection-generation", panel=str(projection_panels["selector"]),
        panel_declared_sha256=qfq.sha(projection_panels["selector"]), helper_sha256=qfq.sha(tmp_path / "kernel"),
        code_sha256=qfq.sha(tmp_path / "projection_runner"))
    identity_sha = qfq.canonical_sha(identity)
    pq.write_table(pa.Table.from_pylist([patch("000001.SZ", 20261028, 5.0, 50000, 100,
        "GBBQ_DATED_SNAPSHOT", daily_source)]), tmp_path / "daily.parquet")
    (tmp_path / "daily_manifest.json").write_text(json.dumps(dict(identity=identity, artifact=ref(tmp_path / "daily.parquet"))))
    (tmp_path / "history_identity.json").write_text(json.dumps(dict(identity_sha256=identity_sha)))
    (tmp_path / "base_coverage.json").write_text(json.dumps(dict(identity_sha256=identity_sha,
        complete=True, completed_batches=1, total_batches=1)))
    (tmp_path / "coverage").write_text(json.dumps(dict(identity_sha256=identity_sha,
        base_coverage=str(tmp_path / "base_coverage.json"), base_coverage_sha256=qfq.sha(tmp_path / "base_coverage.json"),
        repair_artifact=ref(tmp_path / "repair.parquet"), codes=["000002.SZ"])))
    (tmp_path / "checkpoint.json").write_text(json.dumps(dict(identity_sha256=identity_sha,
        artifact=ref(tmp_path / "history.parquet"), symbols=2)))
    baseline_receipt = dict(schema="a_share_qfq_panel_v1", status="CANDIDATE_READY",
        generation_id="current-generation", asof_date=20261030, target_date=20261030,
        candidates={r: str(p) for r, p in panels.items()},
        candidate_sha256={r: qfq.sha(p) for r, p in panels.items()},
        counts={r: {"panel_rows": len(frame)} for r in panels},
        RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
    (tmp_path / "baseline_generation_receipt.json").write_text(json.dumps(baseline_receipt))
    binding = dict(schema="a_share_turnover_overlay_v2", policy=POLICY, cutoff=20261028,
        projection_generation_id="projection-generation", projection_asof_date=20261028,
        projection_baseline_roles={r: ref(p) for r, p in projection_panels.items()},
        baseline_generation_id="current-generation", baseline_asof_date=20261030,
        baseline_generation_receipt=ref(tmp_path / "baseline_generation_receipt.json"),
        baseline_roles={r: ref(p) for r, p in panels.items()},
        projection_identity_sha256=identity_sha, projection_kernel=ref(tmp_path / "kernel"),
        projection_runner=ref(tmp_path / "projection_runner"), repair_runner=ref(tmp_path / "repair_runner"),
        history_identity=ref(tmp_path / "history_identity.json"), coverage=ref(tmp_path / "coverage"),
        d28_manifest=ref(tmp_path / "daily_manifest.json"),
        historical_parts=[dict(**ref(tmp_path / "history.parquet"), codes=["000001.SZ", "000002.SZ"], checkpoint=ref(tmp_path / "checkpoint.json"))],
        repair=dict(**ref(tmp_path / "repair.parquet"), codes=["000002.SZ"], replacement_status="RAW_HISTORY_UNAVAILABLE"),
        d28=ref(tmp_path / "daily.parquet"), RESEARCH_ONLY=True, production_allowed=False,
        buy_gate_updated=False, orders_sent=False, historical_PIT=False)
    config = tmp_path / "overlay.json"
    config.write_text(json.dumps(binding))
    monkeypatch.setattr(qfq, "rebuild_symbol", lambda *a, **kw: pytest.fail("formula computation is forbidden"))
    receipt = qfq.build_turnover_overlay_candidate(overlay_ref=ref(config), panels=panels, output_root=tmp_path / "candidate")
    assert receipt["status"] == "READY_ISOLATED" and receipt["current_updated"] is False
    assert receipt["schema"] == "a_share_turnover_overlay_candidate_v2"
    assert receipt["projection_generation_id"] == "projection-generation"
    assert receipt["projection_asof_date"] == 20261028
    assert receipt["baseline_generation_id"] == "current-generation"
    assert receipt["baseline_asof_date"] == 20261030 and receipt["cutoff"] == 20261028
    assert receipt["counts"]["selector"]["source_rows"] == receipt["counts"]["selector"]["output_rows"] == len(frame)
    assert receipt["counts"]["selector"]["preserved_non_null"] == 2
    assert receipt["counts"]["backtest"]["preserved_non_null"] == 0
    assert receipt["counts"]["selector"]["baseline_rows_A_SHARE"] == 8
    assert receipt["counts"]["selector"]["baseline_rows_HK"] == 1
    for role in panels:
        out = pq.read_table(receipt["candidates"][role]["path"]).to_pandas()
        assert out.close.tolist() == frame.close.tolist()
        assert out.ts_code.tolist() == frame.ts_code.tolist()
        expected = [1.0, 9.0 if role == "selector" else 2.0, 5.0, np.nan, np.nan, 3.0, np.nan, np.nan,
                    7.0 if role == "selector" else np.nan]
        assert out.turnover_rate_pct.tolist() == pytest.approx(expected, nan_ok=True)
        assert out.trade_date.tolist() == frame.trade_date.tolist()
        assert out.float_share_10k.iloc[1] == (999.0 if role == "selector" else 100.0)
        assert pd.isna(out.turnover_rate_pct.iloc[3]) and pd.isna(out.turnover_rate_pct.iloc[4])
        assert pd.isna(out.turnover_rate_pct.iloc[7])
        assert out.iloc[3].close == frame.iloc[3].close and out.iloc[4].close == frame.iloc[4].close
        assert out.iloc[7].close == frame.iloc[7].close
        assert out.turnover_rate_denominator_10k.iloc[0] == 100.0
    assert pq.read_table(panels["selector"]).to_pandas().turnover_rate_pct.isna().sum() == 7
    assert not (tmp_path / "CURRENT").exists()
    with pytest.raises(qfq.QfqGateError, match="OUTPUT_ROOT_NOT_EMPTY"):
        qfq.build_turnover_overlay_candidate(overlay_ref=ref(config), panels=panels, output_root=tmp_path / "candidate")
    original_bytes = panels["selector"].read_bytes()
    original_verify = HistoricalOverlay.verify_sources
    def mutate_baseline_after_read(overlay):
        original_verify(overlay)
        panels["selector"].write_bytes(original_bytes + b"changed")
    monkeypatch.setattr(HistoricalOverlay, "verify_sources", mutate_baseline_after_read)
    with pytest.raises(qfq.QfqGateError, match="BASELINE_CHANGED_DURING_BUILD"):
        qfq.build_turnover_overlay_candidate(overlay_ref=ref(config), panels=panels, output_root=tmp_path / "drift_candidate")
    assert not (tmp_path / "drift_candidate/candidate_receipt.json").exists()
    panels["selector"].write_bytes(original_bytes)
    monkeypatch.setattr(HistoricalOverlay, "verify_sources", original_verify)
    # A new matching file hash cannot launder an arithmetically false patch.
    hist[0]["turnover_rate_pct"] = 11.0
    pq.write_table(pa.Table.from_pylist(hist), tmp_path / "history.parquet")
    binding["historical_parts"][0].update(ref(tmp_path / "history.parquet"))
    (tmp_path / "checkpoint.json").write_text(json.dumps(dict(identity_sha256=identity_sha,
        artifact=ref(tmp_path / "history.parquet"), symbols=2)))
    binding["historical_parts"][0]["checkpoint"] = ref(tmp_path / "checkpoint.json")
    config.write_text(json.dumps(binding))
    with pytest.raises(qfq.QfqGateError, match="ARITHMETIC_INVALID"):
        qfq.build_turnover_overlay_candidate(overlay_ref=ref(config), panels=panels, output_root=tmp_path / "bad_candidate")
    assert not (tmp_path / "bad_candidate/candidate_receipt.json").exists()


def test_convention_tuple_extension_is_bounded_and_kernel_pinned(tmp_path):
    import json
    from pathlib import Path
    from ops import research_panel_qfq as qfq

    def ref(path):
        return dict(path=str(path), sha256=qfq.sha(path))

    qfq_source = Path(qfq.__file__).resolve()
    helper_source = qfq_source.with_name("research_panel_turnover.py")
    primary_source = tmp_path / "primary_qfq.py"
    primary_source.write_bytes(qfq_source.read_bytes() + b"\n# original tuple source\n")
    primary = dict(driver_sha256="1" * 64, formula_sha256="2" * 64,
        adapter_sha256=qfq.sha(primary_source), input_adapter_sha256="3" * 64,
        factor_cache_sha256="4" * 64, tdx_adapter_sha256="5" * 64,
        user_formula_sha256="6" * 64, field_contract_sha256="7" * 64)
    existing = dict(primary, adapter_sha256="8" * 64, input_adapter_sha256="9" * 64,
        factor_cache_sha256="a" * 64, tdx_adapter_sha256="b" * 64)
    candidate = dict(existing, adapter_sha256=qfq.sha(qfq_source))
    assertions = dict(events_parity=True, volume_math_parity=True,
        original_provider_dates_preserved=True, source_and_code_pins_verified=True)

    old_proof_path = tmp_path / "old_proof.json"
    old_proof_path.write_text(json.dumps(dict(status="PASS_INPUT_EVENT_VOLUME_EQUIVALENCE",
        code_binding=existing, baseline_code_binding=primary, assertions=assertions,
        RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)))
    old_entry = dict(code_binding=existing, status="PASS", reviewer_id="/root/old_reviewer",
        equivalence_receipt=ref(old_proof_path))
    accepted = dict(tuple_compatibility_schema="qfq_exact_two_tuple_acceptance.v1",
        code_binding=primary, approved_tuple_entries=[old_entry])
    assert qfq._convention_tuple_accepted(accepted, primary)
    assert qfq._convention_tuple_accepted(accepted, existing)

    kernel_sha = qfq.computation_kernel_sha(qfq_source)
    new_proof = dict(status="PASS_INPUT_EVENT_VOLUME_EQUIVALENCE", code_binding=candidate,
        baseline_code_binding=primary, assertions=assertions, RESEARCH_ONLY=True,
        production_allowed=False, buy_gate_updated=False, orders_sent=False,
        provider_calls=0, new_displayed_oracle=False, author_id="/root/turnover_writer",
        independent_review_status="PASS", reviewer_id="/root/turnover_reviewer",
        qfq_kernel_equivalence=dict(schema="qfq_turnover_kernel_equivalence_v1",
            baseline_source=ref(primary_source), candidate_source=ref(qfq_source),
            helper_source=ref(helper_source), baseline_kernel_sha256=kernel_sha,
            candidate_kernel_sha256=kernel_sha))
    new_proof_path = tmp_path / "new_proof.json"
    new_proof_path.write_text(json.dumps(new_proof))
    new_entry = dict(code_binding=candidate, status="PENDING", equivalence_receipt=ref(new_proof_path))
    candidate_acceptance = dict(accepted, approved_tuple_entries=[old_entry, new_entry])
    assert not qfq._convention_tuple_accepted(candidate_acceptance, candidate)

    new_entry.update(status="PASS", reviewer_id="/root/turnover_reviewer")
    candidate_acceptance["approved_tuple_entries"] = [old_entry, new_entry]
    assert qfq._convention_tuple_accepted(candidate_acceptance, candidate)

    staged_ops = tmp_path / "isolated_profile" / "app" / "ops"
    staged_ops.mkdir(parents=True)
    staged_qfq, staged_helper = staged_ops / "research_panel_qfq.py", staged_ops / "research_panel_turnover.py"
    staged_qfq.write_bytes(qfq_source.read_bytes())
    staged_helper.write_bytes(helper_source.read_bytes())
    staged_proof = json.loads(json.dumps(new_proof))
    staged_kernel = staged_proof["qfq_kernel_equivalence"]
    staged_kernel["candidate_source"] = ref(staged_qfq)
    staged_kernel["helper_source"] = ref(staged_helper)
    new_proof_path.write_text(json.dumps(staged_proof))
    new_entry["equivalence_receipt"] = ref(new_proof_path)
    assert qfq._convention_tuple_accepted(candidate_acceptance, candidate)

    staged_helper_bytes = staged_helper.read_bytes()
    staged_helper.write_bytes(staged_helper_bytes + b"\n# wrong helper bytes\n")
    staged_kernel["helper_source"] = ref(staged_helper)
    new_proof_path.write_text(json.dumps(staged_proof))
    new_entry["equivalence_receipt"] = ref(new_proof_path)
    assert not qfq._convention_tuple_accepted(candidate_acceptance, candidate)
    staged_helper.write_bytes(staged_helper_bytes)

    wrong_helper = tmp_path / "unpaired" / "research_panel_turnover.py"
    wrong_helper.parent.mkdir()
    wrong_helper.write_bytes(staged_helper.read_bytes())
    staged_kernel["helper_source"] = ref(wrong_helper)
    new_proof_path.write_text(json.dumps(staged_proof))
    new_entry["equivalence_receipt"] = ref(new_proof_path)
    assert not qfq._convention_tuple_accepted(candidate_acceptance, candidate)

    unknown = dict(candidate, extra_sha256="c" * 64)
    assert not qfq._convention_tuple_accepted(candidate_acceptance, unknown)
    changed_other_field = dict(candidate, formula_sha256="c" * 64)
    assert not qfq._convention_tuple_accepted(candidate_acceptance, changed_other_field)
    assert not qfq._convention_tuple_accepted(dict(accepted,
        approved_tuple_entries=[old_entry, old_entry]), candidate)
    assert not qfq._convention_tuple_accepted(dict(accepted,
        approved_tuple_entries=[old_entry, new_entry, new_entry]), candidate)

    missing_kernel = dict(new_proof)
    del missing_kernel["qfq_kernel_equivalence"]
    bad_proof_path = tmp_path / "bad_proof.json"
    bad_proof_path.write_text(json.dumps(missing_kernel))
    bad_entry = dict(new_entry, equivalence_receipt=ref(bad_proof_path))
    assert not qfq._convention_tuple_accepted(dict(accepted,
        approved_tuple_entries=[old_entry, bad_entry]), candidate)

    wrong_kernel = dict(new_proof)
    wrong_kernel["qfq_kernel_equivalence"] = dict(wrong_kernel["qfq_kernel_equivalence"],
        candidate_kernel_sha256="f" * 64)
    bad_proof_path.write_text(json.dumps(wrong_kernel))
    bad_entry = dict(new_entry, equivalence_receipt=ref(bad_proof_path))
    assert not qfq._convention_tuple_accepted(dict(accepted,
        approved_tuple_entries=[old_entry, bad_entry]), candidate)
