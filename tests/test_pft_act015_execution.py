from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ops import pft_act015_execution as study


def book_fixture(n=12,codes=("000001.SZ",)):
    dates=pd.bdate_range("2024-11-01",periods=n).strftime("%Y%m%d").tolist()
    rows=[]
    for code in codes:
        for day in dates:
            rows.append(dict(ts_code=code,trade_date=day,open=10.,high=10.2,low=9.8,
                             close=10.,vol=100.,pct_chg=0.,pre_close=10.,tradeable_basic=1.))
    return study.PriceBook.from_frame(pd.DataFrame(rows))


def test_f5_signed_weak_ties_endpoint_and_causality():
    counts=pd.Series([1]*39+[1,4,2])
    result=study.f5_s1(counts)
    assert result.iloc[:39].isna().all()
    assert result.iloc[39]==1.0  # Weak CDF differs materially from average rank.
    assert result.iloc[40]==1.0
    assert result.iloc[41]==39/40
    assert result.iloc[:41].equals(study.f5_s1(counts.iloc[:41]))


def test_exact_market_clock_never_skips_missing_security_bar():
    book=book_fixture(8,codes=("000001.SZ","920001.BJ"))
    book.valid[3,1]=False
    book.values["close"][:,0]=np.arange(10.,18.)
    result=book.forward_returns(3)
    assert result[0,0]==pytest.approx(.3)
    assert np.isnan(result[0,1])
    assert np.isnan(result[-1]).all()


def test_h_sleeves_hold_cash_ramp_up_and_no_overlap_leverage():
    book=book_fixture()
    book.values["close"][:]=11.
    signals={i:[0] for i in range(8)}
    daily,stats=study.simulate(book,signals,3,"ideal",book.dates[0],book.dates[-1])
    assert daily.nav.eq(1.).all()
    assert daily.position_lots.iloc[:4].tolist()==[1,2,3,3]
    assert daily.holding_count.max()==1
    assert daily.gross_exposure.max()<=1.+1e-12
    assert stats["fills"]==8
    assert stats["residual_positions"]==0
    assert daily.cash.iloc[-1]==pytest.approx(1.)


def test_open_clock_and_per_side_costs_have_closed_form_oracle():
    book=book_fixture(8)
    book.values["open"][:]=10.
    book.values["close"][:]=11.
    # One of three cash sleeves enters at T1 open and exits at D+3 close.
    daily,stats=study.simulate(book,{0:[0]},3,"constrained",book.dates[0],book.dates[-1])
    expected=2/3+(1/3)/(1+.0015)*1.1*(1-.0015)
    assert daily.nav.iloc[0]==1.
    assert daily.nav.iloc[-1]==pytest.approx(expected)
    assert stats["fills"]==1
    assert stats["buy_fees"]>0 and stats["sell_fees"]>0
    assert daily.holding_count.iloc[3]==0


def test_blocked_equal_weight_entry_keeps_its_cash_no_replacement():
    book=book_fixture(8,codes=("000001.SZ","000002.SZ"))
    book.values["open"][1,1]=10.6
    book.values["close"][1:,0]=11.
    daily,stats=study.simulate(book,{0:[0,1]},3,"constrained",book.dates[0],book.dates[-1])
    assert stats["attempts"]==2 and stats["fills"]==1
    assert stats["blocked"]["main_5_to_10_unknown_strict_exclusion"]==1
    expected=5/6+(1/6)/(1+.0015)*1.1*(1-.0015)
    assert daily.nav.iloc[-1]==pytest.approx(expected)


def test_entry_proxy_does_not_inspect_t1_high_low_close():
    book=book_fixture()
    before=study.entry_status(book,1,0)
    book.values["high"][1,0]=999.
    book.values["low"][1,0]=0.
    book.values["close"][1,0]=np.nan
    assert study.entry_status(book,1,0)==before
    assert before[0]


def test_proxy_board_caps_and_missing_reference_fail_closed():
    book=book_fixture(codes=("000001.SZ","300001.SZ","688001.SH","920001.BJ"))
    for i,code in enumerate(book.codes):
        band=study.board_band(code)
        book.values["open"][1,i]=10*(1+band-.002)
        assert not study.entry_status(book,1,i)[0]
        book.values["open"][1,i]=10*(1+band-.01)
        assert study.entry_status(book,1,i)[0]
    book.values["pre_close"][1,0]=np.nan
    assert study.entry_status(book,1,0)==(False,"unknown_reference_or_board")
    book.values["tradeable_basic"][1,1]=np.nan
    assert not study.entry_status(book,1,1)[0]


def test_native_cap_takes_precedence_over_conservative_proxy():
    book=book_fixture()
    book.values["limit_up_price"]=np.full(book.valid.shape,11.)
    book.values["open"][1,0]=10.6
    assert study.entry_status(book,1,0)==(True,"native_cap_proxy_fill")
    book.values["open"][1,0]=11.
    assert study.entry_status(book,1,0)==(False,"native_upper_cap_block")


def test_unsellable_exit_stays_in_nav_and_delays_without_substitution():
    book=book_fixture(9)
    for name in ("open","high","low","close"):
        book.values[name][3,0]=9.5
    book.values["close"][4,0]=9.7
    daily,stats=study.simulate(book,{0:[0]},3,"constrained",book.dates[0],book.dates[-1])
    assert daily.holding_count.iloc[3]==1
    assert daily.holding_count.iloc[4]==0
    assert stats["delayed_positions"]==1
    assert stats["delayed_exit_sessions"]==1
    expected=2/3+(1/3)/(1+.0015)*.97*(1-.0015)
    assert daily.nav.iloc[-1]==pytest.approx(expected)


def test_missing_exit_stale_mark_residual_is_not_dropped():
    book=book_fixture(4)
    book.valid[3,0]=False
    daily,stats=study.simulate(book,{0:[0]},3,"constrained",book.dates[0],book.dates[-1])
    assert stats["stale_mark_sessions"]==1
    assert stats["residual_positions"]==1
    assert stats["residual_market_value"]>0
    assert daily.nav.iloc[-1]>2/3


def test_terminal_immature_signals_remain_cash_without_peeking_at_exit():
    book=book_fixture(6)
    daily,stats=study.simulate(book,{4:[0]},3,"constrained",book.dates[0],book.dates[-1])
    assert stats["attempts"]==0
    assert stats["immature_signal_count"]==1
    assert daily.nav.eq(1.).all()


def test_relative_nav_metrics_and_drawdown_include_initial_capital():
    values=study.metric_values([-.10,.10],[.05,-.05])
    assert values["absolute_return"]==pytest.approx(-.01)
    assert values["excess_return_relative_nav"]==pytest.approx(.99/.9975-1)
    assert values["mdd"]==pytest.approx(-.10)


def candidates_fixture():
    dates=["20231002","20240701","20240702","20240703","20240926","20241101","20250102"]
    rows=[]
    for i,day in enumerate(dates):
        row={x:float(i) for x in study.MODEL_FEATURES}
        row.update(ts_code="000001.SZ",trade_date=day,clean_union=True,b_any=True,
                   f5_s1_pass=True,label=float(i%2),label_target_date="20240930" if i==4 else day,
                   _anchor_date="20240701" if i in (2,5) else "",
                   rebuild_episode_id="same" if i in (3,5) else "",session=i,code_index=0)
        rows.append(row)
    return pd.DataFrame(rows)


def test_quarter_train_boundary_purge_balanced_weights_and_single_fit():
    calls=[]
    class Estimator:
        def fit(self,x,y,sample_weight):
            calls.append((x.copy(),y.copy(),sample_weight.copy()))
            return self
        def predict_proba(self,x):
            return np.column_stack([np.full(len(x),.4),np.full(len(x),.6)])
    candidates=candidates_fixture()
    out,reports=study.fit_quarters(candidates,estimator_factory=Estimator)
    q4=next(x for x in reports if x["quarter"]=="2024Q4")
    assert q4["train_start"]=="20231001"
    assert q4["purged_rows"]==2
    assert q4["fits"]==1
    assert q4["latest_train_target"]<"20241001"
    assert out.loc[out.trade_date.eq("20241101"),"p_hgb"].iloc[0]==.6
    for _,y,weights in calls:
        assert weights[y==0].sum()==pytest.approx(weights[y==1].sum())
    assert sum(x["fits"] for x in reports)==len(calls)


def test_top20_ties_are_code_sorted_and_never_filled_outside_pool():
    rows=[]
    for i in reversed(range(25)):
        rows.append(dict(ts_code=f"{i:06d}.SZ",trade_date="20241101",session=0,code_index=i,
                         clean_union=True,b_any=True,f5_s1_pass=i!=0,p_hgb=.5))
    result=study.select_signals(pd.DataFrame(rows))
    assert result[study.STRATEGIES[-1]][0]==list(range(1,21))
    assert len(result["clean"][0])==25
    assert len(result["clean_b_f5_s1"][0])==24


def test_projected_reader_calls_authority_once_and_excludes_non_a(monkeypatch):
    import pyarrow as pa
    from ops.research_panel_logical import parquet
    frame=pd.DataFrame([{name:1. for name in study.v12.ALIASES} for _ in range(2)])
    frame["ts_code"]=["000001.SZ","00700.HK"]
    frame["market_type"]=["SZ","HK"]
    frame["trade_date"]=[20241101,20241101]
    table=pa.Table.from_pandas(frame,preserve_index=False)
    calls=[]
    monkeypatch.setattr(parquet,"read_schema",lambda path:table.schema)
    def read(path,columns,filters):
        calls.append((columns,filters))
        return table.select(columns)
    monkeypatch.setattr(parquet,"read_table",read)
    result,meta=study.read_projected(study.Path("/synthetic/authority"))
    assert len(calls)==1 and meta["logical_read_calls"]==1
    assert result.ts_code.tolist()==["000001.SZ"]
    assert set(calls[0][0])==set(study.v12.ALIASES)
    assert calls[0][1][1][2]==20261120


def formula_fixture():
    rows=[]
    dates=pd.bdate_range("2024-01-01",periods=180).strftime("%Y%m%d").tolist()
    for code,multiplier in (("000001.SZ",1.),("920001.BJ",1.8)):
        for i,day in enumerate(dates):
            if code.endswith("BJ") and i==91:
                continue
            phase=i%30
            close=9. if phase<2 else (12. if phase<4 else 12.1)
            volume=2000. if phase==2 else 100.
            rows.append(dict(ts_code=code,trade_date=day,market_type=code[-2:],
                open=(close-.02)*multiplier,high=(close+.1)*multiplier,
                low=(close-.1)*multiplier,close=close*multiplier,vol=volume,
                pct_chg=1. if code.endswith("SZ") else -1.,bbi=11.5*multiplier,
                j=10.,zge_white_line=11.*multiplier,zge_yellow_line=10.*multiplier,
                pre_close=close*multiplier,tradeable_basic=1.))
    return pd.DataFrame(rows).sort_values(["ts_code","trade_date"]).reset_index(drop=True)


def test_cohort_formula_reuse_global_features_and_exact_labels_match():
    raw=formula_fixture()
    book=study.PriceBook.from_frame(raw)
    one,meta_one=study.build_candidates(raw,book,book.dates[0],cohort_size=1)
    both,meta_both=study.build_candidates(raw,book,book.dates[0],cohort_size=256)
    assert len(one)>0
    keys=["ts_code","trade_date"]
    columns=[*keys,*study.MODEL_FEATURES,"clean_union","b_any","label","label_target_date"]
    pd.testing.assert_frame_equal(one[columns].sort_values(keys).reset_index(drop=True),
                                  both[columns].sort_values(keys).reset_index(drop=True))
    pd.testing.assert_series_equal(meta_one["raw_union_counts"],meta_both["raw_union_counts"])
    # Opposing pct-change signs produce an all-A breadth of 1/2, not each
    # per-symbol helper's temporary 0 or 1.
    assert set(one.market_breadth_up_fraction.unique())=={.5}
    assert one.label.notna().any()
    assert one["label_excess_t5"].dropna().abs().max()<1e-12


def test_daily_fill_counts_follow_execution_quarter_and_regime():
    book=book_fixture(8,codes=("000001.SZ","000002.SZ"))
    book.dates=pd.bdate_range("2024-12-31",periods=8).strftime("%Y%m%d").tolist()
    book.values["open"][1,1]=10.6
    daily,stats=study.simulate(book,{0:[0,1]},3,"constrained",book.dates[0],book.dates[-1])
    assert daily.attempts.tolist()==[0,2,0,0,0,0,0,0]
    assert daily.fills.tolist()==[0,1,0,0,0,0,0,0]
    assert daily.attempts.sum()==stats["attempts"]
    assert daily.fills.sum()==stats["fills"]
    daily=daily.assign(strategy="clean",horizon=3,mode="constrained",daily_return=0.,
                       benchmark_daily_return=0.,regime=["bull","bear",*["sideways"]*6])
    metrics=study.aggregate_metrics(daily)
    q4=metrics.loc[metrics.segment.eq("2024Q4")].iloc[0]
    q1=metrics.loc[metrics.segment.eq("2025Q1")].iloc[0]
    bear=metrics.loc[metrics.segment.eq("bear")].iloc[0]
    assert q4.attempts==0 and pd.isna(q4.fill_rate)
    assert q1.attempts==2 and q1.fills==1 and q1.fill_rate==.5
    assert bear.attempts==2 and bear.fill_rate==.5


class ReplayPredictor:
    def fit(self,*args,**kwargs):
        raise AssertionError("Replay must never fit")
    def predict_proba(self,x):
        return np.column_stack([np.full(len(x),.4),np.full(len(x),.6)])


def replay_fixture(path):
    import joblib
    quarters=["2024Q4",*[f"{year}Q{q}" for year in (2025,2026) for q in (1,2,3,4)]]
    reports=[]
    candidates=[]
    for q in quarters:
        report=dict(quarter=q,fits=1,status="FIT_COMPLETE",predict_rows=1)
        filename=f"hgb_{q}.joblib"
        joblib.dump(dict(model=ReplayPredictor(),features=study.MODEL_FEATURES,
                         fit=report.copy(),signed_doc=study.SIGNED_DOC,**study.FLAGS),path/filename)
        reports.append({**report,"model_file":filename})
        day="20241101" if q=="2024Q4" else study.quarter_start(q)
        candidates.append({**{x:1. for x in study.MODEL_FEATURES},"trade_date":day,"b_any":True})
    accounting=dict(HGB=9,S=0,search=0,expected_evaluation_quarters=9,quarters=reports)
    binding={**study.a9.EXPECTED_BINDING,"asof_date":str(study.a9.EXPECTED_BINDING["asof_date"])}
    summary=dict(status="COMPLETED_ESTIMATED_EXECUTION_RESEARCH",signed_doc=study.SIGNED_DOC,
                 binding=binding,evaluation_window=[study.START,study.END],model_features=list(study.MODEL_FEATURES),
                 fit_accounting=accounting,**study.FLAGS)
    study._write_json(path/"fit_accounting.json",accounting)
    study._write_json(path/"run_summary.json",summary)
    return pd.DataFrame(candidates),binding


def test_replay_uses_all_nine_frozen_weights_without_fit(tmp_path):
    candidates,binding=replay_fixture(tmp_path)
    before={x.name:x.read_bytes() for x in tmp_path.iterdir()}
    predicted,report=study.replay_quarters(candidates,tmp_path,binding)
    assert predicted.p_hgb.eq(.6).all()
    assert report["HGB"]==0 and report["reused_HGB"]==9
    assert report["source_checks"]["protected_policy_ast"]=="MATCH"
    assert all(x["fits"]==0 for x in report["quarters"])
    assert before=={x.name:x.read_bytes() for x in tmp_path.iterdir()}


def test_replay_rejects_different_binding_or_population(tmp_path):
    candidates,binding=replay_fixture(tmp_path)
    with pytest.raises(study.ExecutionError,match="ORIGINAL_RUN_CONTRACT"):
        study.replay_quarters(candidates,tmp_path,{**binding,"generation_id":"different"})
    with pytest.raises(study.ExecutionError,match="PREDICTION_POPULATION_CHANGED"):
        study.replay_quarters(pd.concat([candidates,candidates.iloc[:1]]),tmp_path,binding)
